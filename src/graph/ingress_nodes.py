"""Deterministic ingress nodes (no LLM)."""

from __future__ import annotations

import re
import time
from loguru import logger

from ..config import settings
from ..tools import semantic_cache
from ..tools.chat_memory import chat_memory
from ..utils.metrics import init_metrics, record_node_timing
from .graph_state import AgentState
from ..agents import knowledge_capture_agent


DANGEROUS_PATTERNS = [
    r"(?i)(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE)",
    r"(?i)(UNION\s+SELECT|OR\s+1\s*=\s*1)",
    r"(?i)(--\s*$|;\s*DROP)",
]


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
    from ..utils.serialization import sanitize_state

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
    """
    Human-in-the-loop clarification via LangGraph interrupt.
    On resume, merges user answer and optionally captures business knowledge.
    """
    from langgraph.types import interrupt

    from ..agents.clarification_agent import ClarificationAgent

    # Resume path: clarification_answer supplied via Command(resume=...) or state
    resume_answer = state.get("clarification_answer")
    if resume_answer and not state.get("_hitl_resume_processed"):
        if state.get("gap_type") == "knowledge_gap":
            return knowledge_capture_agent.capture(
                {**state, "pending_original_question": state.get("pending_original_question") or state.get("question")}
            )
        original = state.get("pending_original_question") or state.get("original_question") or state.get("question")
        combined = f"Original Question:\n{original}\n\nClarification Answer:\n{resume_answer}".strip()
        return {
            "question": combined,
            "clarification_answer": resume_answer,
            "waiting_for_user": False,
            "needs_clarification": False,
            "question_to_user": None,
            "enriched_question": combined,
        }

    question_to_user = state.get("question_to_user")
    clarifier_out = {}
    if not question_to_user:
        agent = ClarificationAgent()
        clarifier_out = agent.clarify(state)
        question_to_user = clarifier_out.get("question_to_user") or "Could you provide more details?"

    user_response = interrupt(
        {
            "type": "clarification",
            "question_to_user": question_to_user,
            "gap_type": state.get("gap_type"),
            "pending_original_question": state.get("pending_original_question") or state.get("question"),
        }
    )

    resume_state = {
        **state,
        **clarifier_out,
        "clarification_answer": user_response if isinstance(user_response, str) else str(user_response),
        "waiting_for_user": False,
    }

    if state.get("gap_type") == "knowledge_gap":
        return knowledge_capture_agent.capture(resume_state)

    original = resume_state.get("pending_original_question") or resume_state.get("question")
    combined = f"Original Question:\n{original}\n\nClarification Answer:\n{resume_state['clarification_answer']}".strip()
    return {
        **resume_state,
        "question": combined,
        "enriched_question": combined,
        "needs_clarification": False,
        "question_to_user": None,
    }
