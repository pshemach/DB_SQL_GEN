"""
Sales SQL orchestrator.

One class owns one LangGraph. Large specialists stay in their own modules
(router, planner, schema linker, SQL generator, critic, formatter).
SQL generation is a path on this graph, not a nested subgraph.

Flow:
    recall memory → cache → access check → router
        → security → plan → schema → SQL → validate → execute
        | transform previous | chitchat | clarify | deny
        → format → save memory
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from langgraph.types import Command
from langsmith import traceable
from loguru import logger

from src.agents.critic import CriticAgent
from src.agents.formatter import ResultFormatterAgent
from src.agents.generator import SQLGeneratorAgent
from src.agents.planner import PlannerAgent
from src.agents.prompts.agent_prompts import (
    build_chitchat_prompt,
    build_pre_exec_critic_prompt,
    chat_messages,
)
from src.agents.retriever import SchemaLinkerAgent
from src.agents.router import TurnRouterAgent
from src.agents.state import AgentState
from src.agents.transformer import ResultTransformer
from src.infrastructure.config import (
    ENABLE_DYNAMIC_FEW_SHOT,
    ENABLE_PRE_EXEC_CRITIC,
    ENABLE_PRODUCTION_GRAPH,
    ENABLE_RESULT_VERIFIER,
    ENABLE_SEMANTIC_CACHE,
    ENABLE_TRANSFORM_PREVIOUS,
    FEW_SHOT_EXAMPLES_COUNT,
    LANGCHAIN_API_KEY,
    LANGCHAIN_ENDPOINT,
    LANGCHAIN_PROJECT,
    LANGCHAIN_TRACING_V2,
    MAX_ITERATIONS,
    SQL_MAX_ROWS,
)
from src.infrastructure.db.sql_safety import assess_sql
from src.infrastructure.llm import (
    get_direct_llm,
    get_generator_llm,
    get_planner_llm,
    get_router_llm,
    get_schema_selection_llm,
)
from src.infrastructure.vector_store import few_shot_retriever
from src.utils.error_taxonomy import is_retryable
from src.memory import chat_memory
from src.memory.result_cache import result_cache
from src.infrastructure.cache import semantic_cache
from src.utils.graph_config import build_invoke_config
from src.utils.metrics import finalize_metrics, init_metrics, record_node_timing
from src.utils.serialization import sanitize_state, serialize_query_result

NODE_STATUS = {
    "init": "Starting...",
    "memory_loader": "Loading conversation...",
    "semantic_cache": "Checking previous answers...",
    "authz": "Checking access...",
    "turn_router": "Understanding your question...",
    "security_policy": "Checking row access...",
    "planner": "Planning the query...",
    "parallel_retrieval": "Selecting tables...",
    "generator": "Writing SQL...",
    "static_validator": "Checking the SQL...",
    "pre_exec_critic": "Reviewing the SQL...",
    "executor": "Running the query...",
    "reflector": "Fixing the query...",
    "result_verifier": "Checking the result...",
    "transform_result": "Updating the previous result...",
    "formatter": "Writing the answer...",
    "chitchat": "Writing a reply...",
    "hitl_clarify": "Need a bit more detail...",
    "safe_response": "Preparing a response...",
    "cache_result": "Saving the result...",
    "save_memory": "Saving the conversation...",
}

FORBIDDEN_SQL = re.compile(
    r"(?i)\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b"
)


def _setup_langsmith() -> None:
    if not LANGCHAIN_TRACING_V2:
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = LANGCHAIN_PROJECT
    os.environ["LANGCHAIN_ENDPOINT"] = LANGCHAIN_ENDPOINT


def add_start_time(state: AgentState) -> dict:
    """Add timestamp at start of workflow."""
    return {"start_time": time.time()}


def route_after_cache(state: AgentState) -> Literal["formatter", "authz"]:
    if state.get("cache_hit"):
        return "formatter"
    return "authz"


def route_after_authz(state: AgentState) -> Literal["safe_response", "turn_router"]:
    if state.get("access_denied") or state.get("turn_action") == "deny":
        return "safe_response"
    return "turn_router"


def route_after_turn_router(
    state: AgentState,
) -> Literal["transform_result", "security_policy", "safe_response", "formatter", "hitl_clarify", "chitchat"]:
    """Route the turn. Clarification is a normal node, not a graph interrupt."""
    action = state.get("turn_action", "run_sql")

    if action == "transform_previous" and ENABLE_TRANSFORM_PREVIOUS:
        sid = state.get("session_id")
        if sid and result_cache.get_cached_result(sid):
            return "transform_result"
        logger.warning(
            "transform_previous requested but no session cache found - falling back to SQL"
        )
        return "security_policy"

    if action == "clarify":
        return "hitl_clarify"
    if action in ("deny", "cancel"):
        return "safe_response"
    if action == "cache_hit":
        return "formatter"
    if action == "chitchat":
        return "chitchat"
    return "security_policy"


def route_after_transform(state: AgentState) -> Literal["formatter", "security_policy"]:
    """LLM planner may decide cached rows are insufficient → new SQL."""
    if state.get("needs_new_sql"):
        logger.info("Follow-up planner requested new SQL")
        return "security_policy"
    if state.get("query_result") is None and state.get("current_phase") == "error":
        return "security_policy"
    return "formatter"


DANGEROUS_PATTERNS = [
    r"(?i)(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE)",
    r"(?i)(UNION\s+SELECT|OR\s+1\s*=\s*1)",
    r"(?i)(--\s*$|;\s*DROP)",
]

def save_memory_node(state: AgentState) -> dict:
    session_id = state.get("session_id")

    if not session_id:
        return {}

    assistant_content = None
    message_type = None

    if state.get("waiting_for_user"):
        assistant_content = state.get("question_to_user")
        message_type = "clarification"

    elif state.get("error"):
        assistant_content = state.get("error")
        message_type = "error"

    elif state.get("result_summary"):
        assistant_content = state.get("result_summary")
        message_type = "answer"

    elif state.get("final_answer"):
        assistant_content = state.get("final_answer")
        message_type = "answer"

    assistant_message_id = state.get("assistant_message_id")

    if assistant_content and not state.get("assistant_message_saved"):
        assistant_message_id = chat_memory.add_message(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            message_type=message_type,
            user_id=state.get("user_id"),
            user_role=state.get("user_role"),
        )

    # Save SQL execution once, after successful SQL run
    sql_execution_saved = state.get("sql_execution_saved", False)

    if (
        state.get("sql_query")
        and state.get("query_result") is not None
        and not state.get("error")
        and not sql_execution_saved
        and state.get("turn_action") not in ("cache_hit", "transform_previous")
    ):
        execution_time_ms = state.get("execution_time_ms") or 0

        chat_memory.save_sql_execution(
            session_id=session_id,
            user_id=state.get("user_id"),
            sql=state.get("sql_query"),
            result=state.get("query_result"),
            execution_time_ms=execution_time_ms,
        )

        sql_execution_saved = True

    state_to_save = {
        **state,
        "assistant_message_id": assistant_message_id,
        "assistant_message_saved": bool(assistant_content),
        "sql_execution_saved": sql_execution_saved,
    }

    chat_memory.set_last_state(session_id, state_to_save)

    return {
        "messages": chat_memory.get_session(session_id).get("messages", []),
        "memory_context": chat_memory.build_memory_context(session_id),
        "assistant_message_id": assistant_message_id,
        "assistant_message_saved": bool(assistant_content),
        "sql_execution_saved": sql_execution_saved,
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

    user_message_id = None

    # Save user question only once per graph run
    if not state.get("user_message_saved"):
        user_message_id = chat_memory.add_message(
            session_id=session_id,
            role="user",
            content=state["question"],
            message_type="question",
            user_id=state.get("user_id"),
            user_role=state.get("user_role"),
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
        "user_message_id": user_message_id,
        "user_message_saved": True,
        "metrics": metrics,
    }

def semantic_cache_lookup_node(state: AgentState) -> dict:
    """Early semantic cache exit before any schema-bearing LLM call."""
    t0 = time.time()
    if not ENABLE_SEMANTIC_CACHE:
        return {"cache_hit": False}

    cached = semantic_cache.get(state["question"])
    metrics = record_node_timing(
        state.get("metrics") or init_metrics(),
        "semantic_cache_lookup",
        (time.time() - t0) * 1000,
    )

    if not cached:
        return {"cache_hit": False, "metrics": metrics}

    logger.info("Semantic cache HIT — skipping SQL generation")
    metrics["cache_hit"] = True
    from src.utils.serialization import sanitize_state

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
        "waiting_for_user": True,

        # clear SQL artifacts
        "query_result": None,
        "result_preview": None,
        "sql_query": None,
        "sql_explanation": None,
        "plan": None,
        "plan_steps": None,
        "relevant_tables": None,
        "table_title": None,
        "error": None,
    }
    
def _format_state(state: AgentState, formatter: ResultFormatterAgent) -> dict:
    """Format results and sanitize for checkpointer (plotly/numpy/date)."""
    return sanitize_state(formatter.format(state))

def _transform_state(state: dict, transformer: ResultTransformer) -> dict:
    """Graph node wrapper for result transformation."""
    result = transformer.transform(state)

    cached = result_cache.get_cached_result(state.get("session_id"))
    question = state.get("original_question") or state.get("question") or ""

    if cached and cached.original_question:
        enriched = (
            f"Previous question: {cached.original_question}\n"
            f"Follow-up: {question}"
        )
    else:
        enriched = question

    needs_new_sql = result.get("needs_new_sql", False)
    formatter_mode = result.get("formatter_mode")

    out = {
        **state,

        "question": enriched,
        "enriched_question": result.get("enriched_question") or enriched,

        "query_result": result.get("query_result"),
        "needs_new_sql": needs_new_sql,
        "transformation_applied": result.get("transformation_applied", {}),
        "current_phase": result.get("current_phase", "analyze"),

        "turn_action": "run_sql" if needs_new_sql else "transform_previous",
        "reused_previous_result": result.get("reused_previous_result", False),

        "visualizations": [],
        "plan": None,
        "plan_steps": None,

        "formatter_mode": formatter_mode,
        "rows_returned": result.get("rows_returned", 0),
    }

    if result.get("sql_query"):
        out["sql_query"] = result["sql_query"]

    if result.get("local_sql_query"):
        out["local_sql_query"] = result["local_sql_query"]

    # Only semantic explanation should directly become final answer.
    if formatter_mode == "semantic_answer":
        explanation = result.get("explanation") or ""
        out["result_preview"] = explanation
        out["final_answer"] = explanation
        out["result_summary"] = explanation
        out["table_title"] = "Analysis of Previous Result"

    # For DuckDB transformed data, DO NOT set final_answer/result_summary.
    # Let formatter_node dynamically summarize the transformed query_result.
    elif formatter_mode == "dynamic_result":
        out["result_preview"] = result.get("explanation")
        out["final_answer"] = None
        out["result_summary"] = None
        out["table_title"] = None

    # If local result cannot answer and live SQL is needed.
    elif needs_new_sql:
        out["query_result"] = None
        out["final_answer"] = None
        out["result_summary"] = None
        out["result_preview"] = result.get("explanation")

    return out

_CHITCHAT_FALLBACK = (
    "I can help with sales analytics, KPIs, reps, customers, products, targets, and outlet performance."
)


def _sql_question(state: AgentState) -> str:
    """Question the SQL path should answer. Follow-ups use the enriched form."""
    return state.get("enriched_question") or state.get("question") or ""


def _with_sql_question(state: AgentState) -> dict:
    payload = dict(state)
    payload["question"] = _sql_question(state)
    return payload


def security_policy_node(state: AgentState) -> dict:
    """Inject row-level security context. Fail closed without rep codes."""
    allowed = state.get("allowed_rep_codes") or []
    if not allowed:
        return {
            "error": "Access denied. No allowed rep codes were provided.",
            "error_type": "access_denied",
            "should_retry": False,
        }
    codes_sql = ", ".join(f"'{c}'" for c in allowed)
    return {
        "security_filter_sql": f"RepCode IN ({codes_sql})",
        "access_denied": False,
        "error": None,
        "error_type": None,
    }


def static_validator_node(state: AgentState) -> dict:
    """Deterministic SQL validation before execution."""
    sql = (state.get("sql_query") or "").strip()
    if not sql:
        return {
            "error": "No SQL query generated",
            "error_type": "validation",
            "should_retry": True,
        }

    if FORBIDDEN_SQL.search(sql):
        return {
            "error": "Query contains forbidden DDL/DML statements",
            "error_type": "validation",
            "should_retry": False,
        }

    kind, message = assess_sql(sql)
    if kind == "policy":
        return {
            "error": message,
            "error_type": "validation",
            "should_retry": False,
        }
    if kind == "parse":
        return {
            "error": f"SQL parse error: {message}",
            "error_type": "syntax",
            "should_retry": True,
        }

    update = {
        "error": None,
        "error_type": None,
        "should_retry": False,
    }
    sql_upper = sql.upper()
    if "LIMIT" not in sql_upper and "TOP " not in sql_upper:
        logger.info("Enforcing row cap via TOP clause recommendation in state")
        note = f"-- validator: consider TOP {SQL_MAX_ROWS}"
        update["sql_explanation"] = (state.get("sql_explanation") or "") + f"\n{note}"
    return update


def result_verifier_node(state: AgentState) -> dict:
    """Sanity-check execution results before formatting."""
    if not ENABLE_RESULT_VERIFIER or state.get("error"):
        return {}
    result = state.get("query_result")
    if result is None:
        return {}
    if isinstance(result, list) and len(result) == 0:
        preview = state.get("result_preview") or "Query returned no rows."
        return {"result_preview": preview}
    return {}


def route_after_security(state: AgentState) -> Literal["planner", "formatter"]:
    if state.get("error"):
        return "formatter"
    return "planner"


def route_after_static_validator(state: AgentState) -> str:
    if state.get("error"):
        if is_retryable(state.get("error_type"), state.get("should_retry", True)):
            if state.get("iterations", 0) < MAX_ITERATIONS:
                return "reflect"
        return "formatter"
    return "pre_exec_critic" if ENABLE_PRE_EXEC_CRITIC else "executor"


def route_after_pre_exec(state: AgentState) -> str:
    if state.get("error"):
        if is_retryable(state.get("error_type"), state.get("should_retry", True)):
            if state.get("iterations", 0) < MAX_ITERATIONS:
                return "reflect"
        return "formatter"
    return "executor"


def route_after_executor(state: AgentState) -> str:
    if state.get("error") is None:
        return "result_verifier"
    if not is_retryable(state.get("error_type"), state.get("should_retry", True)):
        return "formatter"
    if state.get("iterations", 0) >= MAX_ITERATIONS:
        return "formatter"
    return "reflect"


class AgentOrchestrator:
    """One class owns the graph and the specialist agents."""

    def __init__(
        self,
        llm_router: Any,
        llm_planner: Any,
        llm_schema_selection: Any,
        llm_generator: Any,
        llm_direct: Any,
    ) -> None:
        _setup_langsmith()
        self.llm_direct = llm_direct
        self.router = TurnRouterAgent(llm_router)
        self.planner = PlannerAgent(llm_planner)
        self.schema_linker = SchemaLinkerAgent(llm_schema_selection)
        self.generator = SQLGeneratorAgent(llm_generator)
        self.critic = CriticAgent(llm_direct)
        self.formatter = ResultFormatterAgent(llm_direct)
        self.transformer = ResultTransformer(llm_router, analyst_llm=llm_direct)
        self.graph = self._build_graph()

    def _build_graph(self):
        logger.info("Building sales SQL orchestrator")
        workflow = StateGraph(AgentState)

        workflow.add_node("init", add_start_time)
        workflow.add_node("memory_loader", memory_loader_node)
        workflow.add_node("semantic_cache", semantic_cache_lookup_node)
        workflow.add_node("authz", authz_guardrails_node)
        workflow.add_node("turn_router", self.turn_router_node)
        workflow.add_node("transform_result", self.transform_result_node)
        workflow.add_node("safe_response", safe_response_node)
        workflow.add_node("chitchat", self.chitchat_node)
        workflow.add_node("hitl_clarify", hitl_clarify_node)
        workflow.add_node("security_policy", security_policy_node)
        workflow.add_node("planner", self.planner_node)
        workflow.add_node("parallel_retrieval", self.parallel_retrieval_node)
        workflow.add_node("generator", self.generator_node)
        workflow.add_node("static_validator", static_validator_node)
        workflow.add_node("pre_exec_critic", self.pre_exec_critic_node)
        workflow.add_node("executor", self.executor_node)
        workflow.add_node("reflector", self.reflector_node)
        workflow.add_node("result_verifier", result_verifier_node)
        workflow.add_node("formatter", self.formatter_node)
        workflow.add_node("cache_result", cache_result_node)
        workflow.add_node("save_memory", save_memory_node)

        workflow.set_entry_point("init")
        workflow.add_edge("init", "memory_loader")
        workflow.add_edge("memory_loader", "semantic_cache")
        workflow.add_conditional_edges(
            "semantic_cache",
            route_after_cache,
            {"formatter": "formatter", "authz": "authz"},
        )
        workflow.add_conditional_edges(
            "authz",
            route_after_authz,
            {"safe_response": "safe_response", "turn_router": "turn_router"},
        )
        workflow.add_conditional_edges(
            "turn_router",
            route_after_turn_router,
            {
                "hitl_clarify": "hitl_clarify",
                "transform_result": "transform_result",
                "security_policy": "security_policy",
                "safe_response": "safe_response",
                "formatter": "formatter",
                "chitchat": "chitchat",
            },
        )
        workflow.add_conditional_edges(
            "transform_result",
            route_after_transform,
            {"formatter": "formatter", "security_policy": "security_policy"},
        )
        workflow.add_conditional_edges(
            "security_policy",
            route_after_security,
            {"planner": "planner", "formatter": "formatter"},
        )
        workflow.add_edge("planner", "parallel_retrieval")
        workflow.add_edge("parallel_retrieval", "generator")
        workflow.add_edge("generator", "static_validator")
        workflow.add_conditional_edges(
            "static_validator",
            route_after_static_validator,
            {
                "pre_exec_critic": "pre_exec_critic",
                "executor": "executor",
                "reflect": "reflector",
                "formatter": "formatter",
            },
        )
        workflow.add_conditional_edges(
            "pre_exec_critic",
            route_after_pre_exec,
            {"executor": "executor", "reflect": "reflector", "formatter": "formatter"},
        )
        workflow.add_conditional_edges(
            "executor",
            route_after_executor,
            {
                "reflect": "reflector",
                "result_verifier": "result_verifier",
                "formatter": "formatter",
            },
        )
        workflow.add_edge("reflector", "static_validator")
        workflow.add_edge("result_verifier", "formatter")
        workflow.add_edge("safe_response", "save_memory")
        workflow.add_edge("formatter", "cache_result")
        workflow.add_edge("cache_result", "save_memory")
        workflow.add_edge("save_memory", END)
        workflow.add_edge("hitl_clarify", "save_memory")
        workflow.add_edge("chitchat", "save_memory")
        return workflow.compile()

    def turn_router_node(self, state: AgentState) -> dict:
        return self.router.route(state)

    def planner_node(self, state: AgentState) -> dict:
        return self.planner.plan(_with_sql_question(state))

    def parallel_retrieval_node(self, state: AgentState) -> dict:
        """Fetch schema context and few-shot examples in parallel."""
        t0 = time.time()
        question = _sql_question(state)
        payload = _with_sql_question(state)
        linker = self.schema_linker

        def _schema():
            return linker.retrieve_schema(payload)

        def _few_shot():
            if not ENABLE_DYNAMIC_FEW_SHOT:
                return {"few_shot_examples": []}
            try:
                examples = few_shot_retriever.retrieve(question, k=FEW_SHOT_EXAMPLES_COUNT)
                return {"few_shot_examples": examples}
            except Exception as exc:
                logger.warning(f"Few-shot retrieval failed: {exc}")
                return {"few_shot_examples": []}

        with ThreadPoolExecutor(max_workers=2) as pool:
            schema_out = pool.submit(_schema).result()
            few_out = pool.submit(_few_shot).result()

        logger.info(f"Parallel retrieval completed in {(time.time() - t0) * 1000:.0f}ms")
        return {**schema_out, **few_out}

    def generator_node(self, state: AgentState) -> dict:
        return self.generator.generate(
            _with_sql_question(state),
            few_shot_examples=state.get("few_shot_examples"),
        )

    def pre_exec_critic_node(self, state: AgentState) -> dict:
        """Optional LLM review of SQL before execution."""
        if not ENABLE_PRE_EXEC_CRITIC:
            return {}
        try:
            system_prompt, user_prompt = build_pre_exec_critic_prompt(
                _sql_question(state), state.get("sql_query", "")
            )
            resp = self.llm_direct.invoke(chat_messages(system_prompt, user_prompt))
            content = (resp.content or "").strip()
            if content.upper().startswith("REJECT"):
                return {
                    "error": content,
                    "error_type": "validation",
                    "should_retry": True,
                }
        except Exception as exc:
            logger.warning(f"Pre-exec critic failed: {exc}")
        return {}

    def executor_node(self, state: AgentState) -> dict:
        return self.critic.execute_and_validate(state)

    def reflector_node(self, state: AgentState) -> dict:
        return self.critic.reflect_and_fix(state)

    def formatter_node(self, state: AgentState) -> dict:
        return _format_state(state, self.formatter)

    def transform_result_node(self, state: AgentState) -> dict:
        return _transform_state(state, self.transformer)

    def chitchat_node(self, state: AgentState) -> dict:
        try:
            system_prompt, user_prompt = build_chitchat_prompt(
                state.get("question") or "",
                state.get("memory_context") or "",
            )
            response = self.llm_direct.invoke(chat_messages(system_prompt, user_prompt))
            msg = response.content if hasattr(response, "content") else str(response)
            msg = (msg or "").strip() or _CHITCHAT_FALLBACK
        except Exception as exc:
            logger.error(f"Chitchat node failed: {exc}")
            msg = _CHITCHAT_FALLBACK
        return {
            "turn_action": "chitchat",
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
            "error": None,
        }

    def run(self, question: str, **kwargs) -> dict:
        return run_agent(question, **kwargs)


def build_agent() -> AgentOrchestrator:
    """Build the orchestrator with one LLM client per role."""
    return AgentOrchestrator(
        llm_router=get_router_llm(),
        llm_planner=get_planner_llm(temperature=0),
        llm_schema_selection=get_schema_selection_llm(),
        llm_generator=get_generator_llm(temperature=0.0),
        llm_direct=get_direct_llm(),
    )


def _initial_state(
    question: str,
    session_id: str,
    allowed_rep_codes: list[str] | None = None,
    user_role: str | None = None,
    user_id: str | None = None,
) -> dict:
    return {
        "session_id": session_id,
        "question": question,
        "original_question": question,
        "allowed_rep_codes": allowed_rep_codes or [],
        "user_role": user_role,
        "security_filter_sql": None,
        "access_denied": False,
        "access_denied_reason": None,
        "previous_state": None,
        "messages": [],
        "memory_context": "",
        "turn_action": None,
        "enriched_question": None,
        "metrics": init_metrics(),
        "question_to_user": None,
        "waiting_for_user": False,
        "plan": None,
        "plan_steps": None,
        "relevant_tables": None,
        "schema_context": None,
        "sql_query": None,
        "sql_explanation": None,
        "few_shot_examples": None,
        "query_result": None,
        "result_preview": None,
        "execution_time_ms": None,
        "error": None,
        "error_type": None,
        "iterations": 0,
        "should_retry": True,
        "start_time": time.time(),
        "cache_hit": False,
        "final_answer": None,
        "user_message_id": None,
        "user_message_saved": False,
        "assistant_message_id": None,
        "assistant_message_saved": False,
        "user_id": user_id,
        "sql_execution_saved": False,
    }


def _finalize(result: dict) -> dict:
    if result.get("start_time"):
        total = (time.time() - result["start_time"]) * 1000
        result["total_latency_ms"] = total
        result["metrics"] = finalize_metrics(result.get("metrics"), total_latency_ms=total)
    if "__interrupt__" in result:
        interrupts = result["__interrupt__"]
        if interrupts:
            payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
            if isinstance(payload, dict):
                result["waiting_for_user"] = True
                result["question_to_user"] = payload.get("question_to_user")
                result["gap_type"] = payload.get("gap_type") or result.get("gap_type")
    if result.get("error"):
        logger.error(f"Agent failed: {result['error']}")
    return sanitize_state(result)


def _resolve_turn_type(session_id: str, turn_type: str | None, clarification_answer: str | None) -> str:
    if turn_type in ("start", "follow_up"):
        return turn_type
    if clarification_answer:
        return "follow_up"
    session = chat_memory.get_session(session_id) or {}
    if session.get("messages"):
        return "follow_up"
    return "start"


def _graph_input(resolved_turn: str, clarification_answer: str | None, initial_state: dict) -> Any:
    if resolved_turn == "follow_up" and clarification_answer and ENABLE_PRODUCTION_GRAPH:
        return Command(resume=clarification_answer)
    return initial_state


def _prepare_turn(
    question: str,
    session_id: str | None,
    allowed_rep_codes: list[str] | None,
    user_role: str | None,
    clarification_answer: str | None,
    user_id: str | None,
    turn_type: str | None,
) -> tuple[str, str, dict, Any]:
    session_id = chat_memory.get_or_create_session(session_id, user_id=user_id, user_role=user_role)
    resolved_turn = _resolve_turn_type(session_id, turn_type, clarification_answer)
    if resolved_turn == "follow_up" and not clarification_answer:
        last_state = chat_memory.get_last_state(session_id) or {}
        if last_state.get("waiting_for_user"):
            clarification_answer = question
    initial_state = _initial_state(question, session_id, allowed_rep_codes, user_role, user_id)
    stream_input = _graph_input(resolved_turn, clarification_answer, initial_state)
    return session_id, resolved_turn, initial_state, stream_input


orchestrator = build_agent()
graph = orchestrator.graph


@traceable(name="sales-sql-agent-production", run_type="chain", tags=["text-to-sql", "production"])
def run_agent(question: str, **kwargs) -> dict:
    """Synchronous entry point."""
    session_id, _resolved, initial_state, graph_input = _prepare_turn(
        question,
        kwargs.get("session_id"),
        kwargs.get("allowed_rep_codes"),
        kwargs.get("user_role"),
        kwargs.get("clarification_answer"),
        kwargs.get("user_id"),
        kwargs.get("turn_type"),
    )
    try:
        final_state = graph.invoke(graph_input, build_invoke_config(session_id))
        return _finalize(final_state)
    except Exception as exc:
        logger.error(f"Orchestrator error: {exc}")
        return {**initial_state, "error": str(exc), "should_retry": False}


async def run_agent_async(
    question: str,
    session_id: str | None = None,
    allowed_rep_codes: list[str] | None = None,
    user_role: str | None = None,
    clarification_answer: str | None = None,
    user_id: str = None,
    turn_type: str | None = None,
) -> dict:
    session_id, resolved_turn, initial_state, graph_input = _prepare_turn(
        question, session_id, allowed_rep_codes, user_role, clarification_answer, user_id, turn_type
    )
    try:
        result = await graph.ainvoke(graph_input, build_invoke_config(session_id))
        finalized = _finalize(result)
        finalized["turn_type"] = resolved_turn
        return finalized
    except Exception as exc:
        logger.error(f"Graph execution error: {exc}")
        return {**initial_state, "error": str(exc), "should_retry": False, "turn_type": resolved_turn}


def _normalize_stream_item(item: Any) -> tuple[str, Any]:
    if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
        return item[0], item[1]
    return "updates", item


async def run_agent_stream(
    question: str,
    session_id: str | None = None,
    allowed_rep_codes: list[str] | None = None,
    user_role: str | None = None,
    clarification_answer: str | None = None,
    user_id: str = None,
    turn_type: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    session_id, resolved_turn, initial_state, graph_input = _prepare_turn(
        question, session_id, allowed_rep_codes, user_role, clarification_answer, user_id, turn_type
    )
    merged: dict[str, Any] = dict(initial_state)
    try:
        try:
            stream = graph.astream(graph_input, build_invoke_config(session_id), stream_mode=["updates", "values"])
        except TypeError:
            stream = graph.astream(graph_input, build_invoke_config(session_id), stream_mode="updates")
        async for item in stream:
            mode, data = _normalize_stream_item(item)
            if mode == "values" and isinstance(data, dict):
                merged = data
                continue
            if mode != "updates" or not isinstance(data, dict):
                continue
            for node_name, update in data.items():
                label = NODE_STATUS.get(node_name)
                if label:
                    yield {"type": "status", "text": label, "node": node_name}
                if isinstance(update, dict):
                    merged.update(update)
        finalized = _finalize(merged)
        finalized["turn_type"] = resolved_turn
        yield {"type": "complete", "state": finalized}
    except Exception as exc:
        logger.error(f"Graph stream error: {exc}")
        yield {
            "type": "complete",
            "state": {**initial_state, "error": str(exc), "should_retry": False, "turn_type": resolved_turn},
        }


def build_production_graph():
    return orchestrator.graph


def compile_production_graph():
    return orchestrator.graph
