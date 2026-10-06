from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from typing import Any

from langgraph.types import Command
from langsmith import traceable
from loguru import logger

from ...config import settings
from ..tools.chat_memory import chat_memory
from ...utils.metrics import finalize_metrics, init_metrics
from ...utils.serialization import sanitize_state
from ...utils.graph_config import build_invoke_config
from .multiagent_graph import graph

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


def _setup_langsmith():
    if not settings.langchain_tracing_v2:
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint


_setup_langsmith()


def _build_initial_state(
    question: str,
    session_id: str,
    allowed_rep_codes: list[str] | None = None,
    user_role: str | None = None,
    clarification_answer: str | None = None,
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
        "gap_type": None,
        "gap_reason": None,
        "confidence": None,
        "missing_pieces": [],
        "question_to_user": None,
        "waiting_for_user": False,
        "pending_original_question": None,
        "clarification_answer": clarification_answer,
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

    # Detect LangGraph interrupt payload for HITL
    if "__interrupt__" in result:
        interrupts = result["__interrupt__"]
        if interrupts:
            payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
            if isinstance(payload, dict):
                result["waiting_for_user"] = True
                result["question_to_user"] = payload.get("question_to_user")
                result["pending_original_question"] = payload.get("pending_original_question")
                result["gap_type"] = payload.get("gap_type") or result.get("gap_type")

    return sanitize_state(result)


@traceable(
    name="sales-sql-agent",
    run_type="chain",
    tags=["text-to-sql", "openai", "anthropic", "production"],
)
def _resolve_turn_type(
    session_id: str,
    turn_type: str | None,
    clarification_answer: str | None,
) -> str:
    if turn_type in ("start", "follow_up"):
        return turn_type
    if clarification_answer:
        return "follow_up"
    session = chat_memory.get_session(session_id) or {}
    if session.get("messages"):
        return "follow_up"
    return "start"


async def run_agent_async(
    question: str,
    session_id: str | None = None,
    allowed_rep_codes: list[str] | None = None,
    user_role: str | None = None,
    clarification_answer: str | None = None,
    user_id: str = None,
    turn_type: str | None = None,
) -> dict:
    session_id = chat_memory.get_or_create_session(session_id)
    resolved_turn = _resolve_turn_type(session_id, turn_type, clarification_answer)

    if resolved_turn == "follow_up" and not clarification_answer:
        last_state = chat_memory.get_last_state(session_id) or {}
        if last_state.get("waiting_for_user"):
            clarification_answer = question

    config = build_invoke_config(session_id)
    initial_state = _build_initial_state(
        question, session_id, allowed_rep_codes, user_role, clarification_answer, user_id
    )
    initial_state["is_follow_up"] = resolved_turn == "follow_up"

    try:
        result = await graph.ainvoke(_graph_input(resolved_turn, clarification_answer, initial_state), config)
        finalized = _finalize(result)
        finalized["turn_type"] = resolved_turn
        return finalized

    except Exception as e:
        logger.error(f"Graph execution error: {e}")
        return {
            **initial_state,
            "error": str(e),
            "should_retry": False,
            "turn_type": resolved_turn,
        }


def _graph_input(resolved_turn: str, clarification_answer: str | None, initial_state: dict) -> Any:
    if (
        resolved_turn == "follow_up"
        and clarification_answer
        and settings.enable_production_graph
    ):
        return Command(resume=clarification_answer)
    return initial_state


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
    session_id = chat_memory.get_or_create_session(session_id)
    resolved_turn = _resolve_turn_type(session_id, turn_type, clarification_answer)

    if resolved_turn == "follow_up" and not clarification_answer:
        last_state = chat_memory.get_last_state(session_id) or {}
        if last_state.get("waiting_for_user"):
            clarification_answer = question

    config = build_invoke_config(session_id)
    initial_state = _build_initial_state(
        question, session_id, allowed_rep_codes, user_role, clarification_answer, user_id
    )
    initial_state["is_follow_up"] = resolved_turn == "follow_up"
    stream_input = _graph_input(resolved_turn, clarification_answer, initial_state)
    merged: dict[str, Any] = dict(initial_state)

    try:
        try:
            stream = graph.astream(stream_input, config, stream_mode=["updates", "values"])
        except TypeError:
            stream = graph.astream(stream_input, config, stream_mode="updates")

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
    except Exception as e:
        logger.error(f"Graph stream error: {e}")
        yield {
            "type": "complete",
            "state": {
                **initial_state,
                "error": str(e),
                "should_retry": False,
                "turn_type": resolved_turn,
            },
        }
