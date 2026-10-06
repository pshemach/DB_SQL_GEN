"""Shared conversation turn execution for start and follow-up paths."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Optional

from loguru import logger

from ...agents.graph import run_agent_async, run_agent_stream
from ...agents.tools.chat_memory import chat_memory
from ...guardrails.pipeline import guardrail_pipeline
from ...utils.chart_request import detect_requested_chart_type
from ...utils.serialization import serialize_query_result


def format_agent_response(result: dict) -> str:
    if result.get("waiting_for_user"):
        return result.get("question_to_user") or "Please provide more details."
    if result.get("error"):
        return str(result.get("error"))
    if result.get("final_answer"):
        return str(result.get("final_answer"))
    if result.get("query_result"):
        return "Query executed successfully."
    if result.get("sql_query"):
        return "SQL generated successfully."
    return "Done."


def charts_for_message(result: dict, question: str) -> list[dict[str, Any]]:
    requested = result.get("requested_chart_type") or detect_requested_chart_type(question)
    if not requested:
        return []

    charts = []
    for viz in result.get("visualizations") or []:
        chart_json = viz.get("chart_json")
        if not chart_json:
            continue
        config = viz.get("visualization_config") or {}
        charts.append({
            "title": viz.get("title"),
            "chart_type": config.get("chart_type") or requested,
            "chart_json": chart_json,
        })
    return charts


def strip_heavy_visualizations(visualizations: Optional[list]) -> list:
    cleaned = []
    for viz in visualizations or []:
        if not isinstance(viz, dict):
            continue
        item = dict(viz)
        item.pop("chart_image_base64", None)
        cleaned.append(item)
    return cleaned


def build_turn_response(result: dict, question: str, session_id: str) -> dict[str, Any]:
    query_result = serialize_query_result(result.get("query_result"))
    if not isinstance(query_result, list):
        query_result = []

    return {
        "success": result.get("error") is None,
        "error": result.get("error"),
        "error_type": result.get("error_type"),
        "session_id": result.get("session_id") or session_id,
        "waiting_for_user": result.get("waiting_for_user", False),
        "question_to_user": result.get("question_to_user"),
        "plan": result.get("plan"),
        "sql_query": result.get("sql_query"),
        "query_result": query_result,
        "result_summary": result.get("result_summary"),
        "table_title": result.get("table_title") or "Extracted Table",
        "visualizations": strip_heavy_visualizations(result.get("visualizations")),
        "requested_chart_type": result.get("requested_chart_type"),
        "final_answer": result.get("final_answer"),
        "assistant_message_id": result.get("assistant_message_id"),
        "answer_text": format_agent_response(result),
        "charts": charts_for_message(result, question),
        "question": question,
        "turn_type": result.get("turn_type"),
    }


async def execute_turn(
    *,
    question: str,
    session_id: str,
    user_id: Any = None,
    user_role: Optional[str] = None,
    allowed_rep_codes: Optional[list] = None,
    turn_type: str,
    clarification_answer: Optional[str] = None,
) -> dict[str, Any]:
    guardrail_context = {
        "conversation_history": [],
        "previous_topics": [],
        "user_role": user_role,
    }
    session = chat_memory.get_session(session_id)
    if session:
        guardrail_context["conversation_history"] = session.get("messages", [])

    guardrail_result = await guardrail_pipeline.evaluate(question, guardrail_context)
    if not guardrail_result.get("passed", False):
        error_text = guardrail_result.get("reason", "Query rejected by safety checks")
        logger.warning(f"Query rejected by guardrails: {error_text}")
        return _guardrail_failure(error_text, session_id, turn_type)

    result = await run_agent_async(
        question=question,
        session_id=session_id,
        user_role=user_role,
        allowed_rep_codes=allowed_rep_codes or [],
        clarification_answer=clarification_answer,
        user_id=user_id,
        turn_type=turn_type,
    )
    return build_turn_response(result, question, session_id)


async def iter_answer_tokens(text: str, chunk_size: int = 28) -> AsyncIterator[str]:
    if not text:
        return
    index = 0
    length = len(text)
    while index < length:
        end = min(index + chunk_size, length)
        if end < length:
            space = text.find(" ", end)
            newline = text.find("\n", end)
            boundaries = [pos for pos in (space, newline) if pos != -1]
            if boundaries:
                end = min(boundaries) + 1
        yield text[index:end]
        index = end
        await asyncio.sleep(0.018)


def _guardrail_failure(error_text: str, session_id: str, turn_type: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": error_text,
        "error_type": "guardrail_rejection",
        "session_id": session_id,
        "waiting_for_user": False,
        "answer_text": error_text,
        "charts": [],
        "query_result": None,
        "turn_type": turn_type,
    }


async def stream_turn(
    *,
    question: str,
    session_id: str,
    user_id: Any = None,
    user_role: Optional[str] = None,
    allowed_rep_codes: Optional[list] = None,
    turn_type: str,
    clarification_answer: Optional[str] = None,
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "status", "text": "Thinking..."}

    guardrail_context = {
        "conversation_history": [],
        "previous_topics": [],
        "user_role": user_role,
    }
    session = chat_memory.get_session(session_id)
    if session:
        guardrail_context["conversation_history"] = session.get("messages", [])

    guardrail_result = await guardrail_pipeline.evaluate(question, guardrail_context)
    if not guardrail_result.get("passed", False):
        error_text = guardrail_result.get("reason", "Query rejected by safety checks")
        logger.warning(f"Query rejected by guardrails: {error_text}")
        payload = _guardrail_failure(error_text, session_id, turn_type)
        async for token in iter_answer_tokens(error_text):
            yield {"type": "token", "text": token}
        yield {"type": "result", "payload": payload}
        yield {"type": "done"}
        return

    result_state = None
    async for event in run_agent_stream(
        question=question,
        session_id=session_id,
        user_role=user_role,
        allowed_rep_codes=allowed_rep_codes or [],
        clarification_answer=clarification_answer,
        user_id=user_id,
        turn_type=turn_type,
    ):
        if event.get("type") == "status":
            yield event
        elif event.get("type") == "complete":
            result_state = event.get("state") or {}

    payload = build_turn_response(result_state or {}, question, session_id)
    async for token in iter_answer_tokens(payload.get("answer_text") or ""):
        yield {"type": "token", "text": token}
    yield {"type": "result", "payload": payload}
    yield {"type": "done"}
