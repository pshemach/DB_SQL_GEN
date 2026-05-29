from __future__ import annotations

import re
import time
from loguru import logger

from ...config import settings
from ...tools import semantic_cache
from ...tools.chat_memory import chat_memory
from ...utils.metrics import init_metrics, record_node_timing
from .graph_state import AgentState
from ...utils.serialization import serialize_query_result
from ...tools.result_cache import result_cache
from ..result_formatter_agent import result_formatter_node
from ...utils.serialization import sanitize_state


DANGEROUS_PATTERNS = [
    r"(?i)(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE)",
    r"(?i)(UNION\s+SELECT|OR\s+1\s*=\s*1)",
    r"(?i)(--\s*$|;\s*DROP)",
]

def save_memory_node(state: AgentState) -> dict:
    """
    Save conversation memory (only user questions and assistant answers).
    
    Technical artifacts (SQL, plan) are NOT saved as messages but stored in last_state
    so they don't pollute the memory context used by the LLM for reasoning.
    """
    session_id = state.get("session_id")

    if not session_id:
        return {}

    # Determine what assistant message to save, in priority order
    assistant_content = None
    message_type = None
    
    if state.get("waiting_for_user"):
        # Save the clarification question the assistant asked
        assistant_content = state.get("question_to_user")
        message_type = "clarification_question"
    
    elif state.get("error"):
        # Save errors
        assistant_content = state.get("error")
        message_type = "error"
    
    elif state.get("result_summary"):
        # Save result summary when query succeeds
        assistant_content = state.get("result_summary")
        message_type = "answer"
    
    elif state.get("final_answer"):
        # Save final answers
        assistant_content = state.get("final_answer")
        message_type = "answer"
    
    # Save the assistant message if we have one
    if assistant_content:
        chat_memory.add_message(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            message_type=message_type
        )
    
    # DO NOT save SQL queries, plans as messages - they are internal artifacts
    # They are preserved in last_state for reference, but not in conversation memory

    # Always save the full state for retrieval if needed
    chat_memory.set_last_state(session_id, state)

    return {
        "messages": chat_memory.get_session(session_id).get("messages", []),
        "memory_context": chat_memory.build_memory_context(session_id)
    }
    


def cache_result_node(state: AgentState) -> dict:
    """
    Stores successful query results in semantic cache for future use.
    Also caches the last result set per session for follow-up lookups (no re-SQL).
    """
    if state.get("error") is not None:
        return {}

    question_key = state.get("enriched_question") or state.get("question") or ""

    if state.get("sql_query") and not state.get("reused_previous_result"):
        result_to_cache = {
            "sql_query": state["sql_query"],
            "query_result": state.get("query_result"),
            "result_preview": state.get("result_preview"),
            "plan": state.get("plan"),
            "relevant_tables": state.get("relevant_tables"),
        }
        semantic_cache.set(question_key, result_to_cache)

    # Session result cache: only after a fresh SQL run (not transform / semantic hit)
    if state.get("reused_previous_result") or state.get("turn_action") in (
        "transform_previous",
        "cache_hit",
    ):
        return {}

    session_id = state.get("session_id")
    rows = serialize_query_result(state.get("query_result"))
    if session_id and isinstance(rows, list) and rows:
        tables = state.get("relevant_tables") or []
        if isinstance(tables, str):
            tables = [tables]
        schema = {str(k): type(v).__name__ for k, v in rows[0].items()}
        result_cache.cache_result(
            session_id=session_id,
            question=question_key,
            sql=state.get("sql_query") or "",
            data=rows,
            tables=list(tables),
            schema=schema,
        )

    return {}

def memory_loader_node(state: dict) -> dict:
    """Load session memory and prior turn state."""
    t0 = time.time()
    session_id = state["session_id"]
    previous_state = chat_memory.get_last_state(session_id)

    chat_memory.add_message(
        session_id=session_id,
        role="user",
        content=state["question"],
        message_type="question",
    )

    metrics = record_node_timing(
        state.get("metrics") or init_metrics(),
        "memory_loader",
        (time.time() - t0) * 1000,
    )

    return {
        "previous_state": previous_state,
        "messages": chat_memory.get_session(session_id).get("messages", []),
        "memory_context": chat_memory.build_memory_context(session_id),
        "waiting_for_user": bool(previous_state and previous_state.get("waiting_for_user")),
        "metrics": metrics,
    }


def semantic_cache_lookup_node(state: AgentState) -> dict:
    """Early semantic cache exit before any schema-bearing LLM call."""
    t0 = time.time()
    if not settings.enable_semantic_cache:
        return {"cache_hit": False}

    cached = semantic_cache.get(state["question"])
    metrics = record_node_timing(
        state.get("metrics") or init_metrics(),
        "semantic_cache_lookup",
        (time.time() - t0) * 1000,
    )

    if not cached:
        return {"cache_hit": False, "metrics": metrics}

    logger.info("Semantic cache HIT — skipping SQL subgraph")
    metrics["cache_hit"] = True
    from ...utils.serialization import sanitize_state

    return sanitize_state({
        "cache_hit": True,
        "turn_action": "cache_hit",
        "sql_query": cached.get("sql_query"),
        "query_result": cached.get("query_result"),
        "result_preview": cached.get("result_preview"),
        "plan": cached.get("plan"),
        "relevant_tables": cached.get("relevant_tables"),
        "error": None,
        "metrics": metrics,
    })


def authz_guardrails_node(state: AgentState) -> dict:
    """Fail-closed authz and input guardrails before schema exposure."""
    t0 = time.time()
    question = (state.get("question") or "").strip()
    metrics = state.get("metrics") or init_metrics()

    if len(question) < 2:
        return _deny("Question too short.", metrics, t0, "validation")
    if len(question) > 2000:
        return _deny("Question exceeds maximum length.", metrics, t0, "validation")

    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, question):
            return _deny("Suspicious pattern detected in question.", metrics, t0, "guardrail_rejection")

    allowed = state.get("allowed_rep_codes") or []
    if not allowed:
        return _deny(
            "Access denied. No allowed rep codes were provided.",
            metrics,
            t0,
            "access_denied",
        )

    metrics = record_node_timing(metrics, "authz_guardrails", (time.time() - t0) * 1000)
    return {"access_denied": False, "metrics": metrics}


def _deny(reason: str, metrics: dict, t0: float, error_type: str) -> dict:
    metrics = record_node_timing(metrics, "authz_guardrails", (time.time() - t0) * 1000)
    return {
        "turn_action": "deny",
        "access_denied": True,
        "access_denied_reason": reason,
        "error": reason,
        "error_type": error_type,
        "should_retry": False,
        "final_answer": reason,
        "metrics": metrics,
    }


def safe_response_node(state: AgentState) -> dict:
    """Terminal responses for deny/chitchat without SQL."""
    if state.get("access_denied"):
        msg = state.get("access_denied_reason") or state.get("error") or "Access denied."
    elif state.get("turn_action") == "chitchat":
        msg = (
            "Hello! I'm your sales analytics assistant. "
            "Ask me about net sales, customers, products, rep performance, KPIs, "
            "or targets for the current period."
        )
    else:
        msg = state.get("error") or "Unable to process your request."

    # Clear prior query artifacts so UI/history do not show last SQL table or charts
    return {
        "final_answer": msg,
        "result_summary": msg,
        "waiting_for_user": False,
        "query_result": None,
        "result_preview": None,
        "visualizations": [],
        "sql_query": None,
        "sql_explanation": None,
        "plan": None,
        "plan_steps": None,
        "table_title": None,
        "relevant_tables": None,
        "error": None if state.get("turn_action") == "chitchat" else state.get("error"),
    }

def hitl_clarify_node(state: AgentState) -> dict:
    question_to_user = (
        state.get("clarification_question")
        or state.get("question_to_user")
        or "Could you provide more details?"
    )

    return {
        "turn_action": "clarify",
        "final_answer": question_to_user,
        "result_summary": question_to_user,
        "question_to_user": question_to_user,
        "pending_original_question": state.get("question"),
        "waiting_for_user": True,
        "needs_clarification": True,
        "query_result": None,
        "result_preview": None,
        "sql_query": None,
        "sql_explanation": None,
        "plan": None,
        "plan_steps": None,
        "relevant_tables": None,
        "error": None,
    }
    
def formatter_node(state: AgentState) -> dict:
    """Format results and sanitize for checkpointer (plotly/numpy/date)."""
    return sanitize_state(result_formatter_node(state))