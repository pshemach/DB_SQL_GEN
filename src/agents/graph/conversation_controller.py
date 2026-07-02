from __future__ import annotations

import os
import time

from langgraph.types import Command
from langsmith import traceable
from loguru import logger

from ...config import settings
from ..tools.chat_memory import chat_memory
from ...utils.metrics import finalize_metrics, init_metrics
from ...utils.serialization import sanitize_state
from ...utils.graph_config import build_invoke_config
from .multiagent_graph import graph


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
async def run_agent_async(
    question: str,
    session_id: str | None = None,
    allowed_rep_codes: list[str] | None = None,
    user_role: str | None = None,
    clarification_answer: str | None = None,
    user_id: str = None
):
    session_id = chat_memory.get_or_create_session(session_id)
    config = build_invoke_config(session_id)
    initial_state = _build_initial_state(
        question, session_id, allowed_rep_codes, user_role, clarification_answer, user_id
    )

    try:
        input_payload = (
            Command(resume=clarification_answer)
            if clarification_answer and settings.enable_production_graph
            else initial_state
        )

        final_state = dict(initial_state)

        async for event in graph.astream(
            input_payload,
            config,
            stream_mode="updates",
        ):
            if not isinstance(event, dict):
                continue

            for node_name, node_state in event.items():
                if not isinstance(node_state, dict):
                    continue

                final_state.update(node_state)

                if node_state.get("error"):
                    yield {
                        "type": "error",
                        "node": node_name,
                        "error": node_state.get("error"),
                        "should_retry": False,
                    }

                elif node_state.get("waiting_for_user") or node_state.get("question_to_user"):
                    yield {
                        "type": "clarification",
                        "node": node_name,
                        "question_to_user": node_state.get("question_to_user"),
                        "pending_original_question": node_state.get("pending_original_question"),
                        "gap_type": node_state.get("gap_type"),
                    }

                elif node_state.get("final_answer"):
                    yield {
                        "type": "answer",
                        "node": node_name,
                        "text": node_state.get("final_answer"),
                    }

                else:
                    yield {
                        "type": "status",
                        "node": node_name,
                        "message": f"{node_name} completed",
                    }

        finalized = _finalize(final_state)

        yield {
            "type": "final",
            "result": finalized,
        }

    except Exception as e:
        logger.error(f"Graph execution error: {e}")
        yield {
            "type": "error",
            "error": str(e),
            "should_retry": False,
        }