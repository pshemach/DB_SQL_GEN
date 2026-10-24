"""
Sales SQL orchestrator.

One class owns the LangGraph. Specialist steps stay in their own modules
(router, planner, SQL generator, critic, formatter) and are wired here.

Flow:
    recall memory → cache → access check → router
        → SQL pipeline | transform previous | chitchat | clarify | deny
        → format → save memory
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from langgraph.types import Command
from langsmith import traceable
from loguru import logger

from src.agents.chitchat import chitchat_node
from src.agents.nodes import (
    authz_guardrails_node,
    cache_result_node,
    formatter_node,
    hitl_clarify_node,
    memory_loader_node,
    safe_response_node,
    save_memory_node,
    semantic_cache_lookup_node,
)
from src.agents.router import turn_router_node
from src.agents.sql_pipeline import _parent_to_sub, _sub_to_parent, get_sql_subgraph
from src.agents.state import AgentState
from src.agents.transformer import transform_result_node
from src.infrastructure.config import (
    ENABLE_PRODUCTION_GRAPH,
    ENABLE_TRANSFORM_PREVIOUS,
    LANGCHAIN_API_KEY,
    LANGCHAIN_ENDPOINT,
    LANGCHAIN_PROJECT,
    LANGCHAIN_TRACING_V2,
)
from src.memory import chat_memory
from src.memory.result_cache import result_cache
from src.utils.graph_config import build_invoke_config
from src.utils.metrics import finalize_metrics, init_metrics
from src.utils.serialization import sanitize_state

NODE_STATUS = {
    "init": "Starting...",
    "memory_loader": "Loading conversation...",
    "semantic_cache": "Checking previous answers...",
    "authz": "Checking access...",
    "turn_router": "Understanding your question...",
    "sql_pipeline": "Generating and running SQL...",
    "transform_result": "Updating the previous result...",
    "formatter": "Writing the answer...",
    "chitchat": "Writing a reply...",
    "hitl_clarify": "Need a bit more detail...",
    "safe_response": "Preparing a response...",
    "cache_result": "Saving the result...",
    "save_memory": "Saving the conversation...",
}


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
) -> Literal["transform_result", "sql_pipeline", "safe_response", "formatter", "hitl_clarify", "chitchat"]:
    """Route the turn. Clarification is a normal node, not a graph interrupt."""
    action = state.get("turn_action", "run_sql")

    if action == "transform_previous" and ENABLE_TRANSFORM_PREVIOUS:
        sid = state.get("session_id")
        if sid and result_cache.get_cached_result(sid):
            return "transform_result"
        logger.warning(
            "transform_previous requested but no session cache found - falling back to sql_pipeline"
        )
        return "sql_pipeline"

    if action == "clarify":
        return "hitl_clarify"
    if action in ("deny", "cancel"):
        return "safe_response"
    if action == "cache_hit":
        return "formatter"
    if action == "chitchat":
        return "chitchat"
    return "sql_pipeline"


def route_after_transform(state: AgentState) -> Literal["formatter", "sql_pipeline"]:
    """LLM planner may decide cached rows are insufficient → new SQL."""
    if state.get("needs_new_sql"):
        logger.info("Follow-up planner requested new SQL — routing to sql_pipeline")
        return "sql_pipeline"
    if state.get("query_result") is None and state.get("current_phase") == "error":
        return "sql_pipeline"
    return "formatter"


def sql_pipeline_node(state: AgentState) -> dict:
    """Run planner → schema link → SQL generation → execute."""
    sub_out = get_sql_subgraph().invoke(_parent_to_sub(state))
    merged = _sub_to_parent(sub_out)
    return sanitize_state(merged) if merged else {}


class AgentOrchestrator:
    """Builds and runs the sales Text-to-SQL graph."""

    def __init__(self) -> None:
        _setup_langsmith()
        self.graph = self._build_graph()

    def _build_graph(self):
        logger.info("Building sales SQL orchestrator")
        workflow = StateGraph(AgentState)

        workflow.add_node("init", add_start_time)
        workflow.add_node("memory_loader", memory_loader_node)
        workflow.add_node("semantic_cache", semantic_cache_lookup_node)
        workflow.add_node("authz", authz_guardrails_node)
        workflow.add_node("turn_router", turn_router_node)
        workflow.add_node("transform_result", transform_result_node)
        workflow.add_node("safe_response", safe_response_node)
        workflow.add_node("chitchat", chitchat_node)
        workflow.add_node("hitl_clarify", hitl_clarify_node)
        workflow.add_node("sql_pipeline", sql_pipeline_node)
        workflow.add_node("formatter", formatter_node)
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
                "sql_pipeline": "sql_pipeline",
                "safe_response": "safe_response",
                "formatter": "formatter",
                "chitchat": "chitchat",
            },
        )
        workflow.add_conditional_edges(
            "transform_result",
            route_after_transform,
            {"formatter": "formatter", "sql_pipeline": "sql_pipeline"},
        )
        workflow.add_edge("sql_pipeline", "formatter")
        workflow.add_edge("safe_response", "save_memory")
        workflow.add_edge("formatter", "cache_result")
        workflow.add_edge("cache_result", "save_memory")
        workflow.add_edge("save_memory", END)
        workflow.add_edge("hitl_clarify", "save_memory")
        workflow.add_edge("chitchat", "save_memory")
        return workflow.compile()

    def run(self, question: str, **kwargs) -> dict:
        return run_agent(question, **kwargs)


def build_agent() -> AgentOrchestrator:
    """Return the process-wide orchestrator."""
    return orchestrator


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
        "conversation_route": None,
        "turn_action": None,
        "router_confidence": None,
        "enriched_question": None,
        "follow_up_type": None,
        "is_follow_up": False,
        "can_reuse_cached_result": False,
        "cached_result_id": None,
        "required_transformations": [],
        "metrics": init_metrics(),
        "needs_clarification": False,
        "question_to_user": None,
        "waiting_for_user": False,
        "business_definitions": "",
        "matched_knowledge": [],
        "plan": None,
        "plan_steps": None,
        "relevant_tables": None,
        "schema_context": None,
        "schema_metadata": None,
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
    initial_state["is_follow_up"] = resolved_turn == "follow_up"
    stream_input = _graph_input(resolved_turn, clarification_answer, initial_state)
    return session_id, resolved_turn, initial_state, stream_input


orchestrator = AgentOrchestrator()
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
