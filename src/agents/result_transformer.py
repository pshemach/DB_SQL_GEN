"""Apply in-memory operations on the session's last query result (no new SQL)."""

from __future__ import annotations

from loguru import logger

from src.tools.result_cache import result_cache
from src.utils.cached_result_ops import apply_cached_follow_up


class ResultTransformer:
    """Reuse and reshape cached rows for follow-up turns."""

    def transform(self, state: dict) -> dict:
        session_id = state.get("session_id")
        question = state.get("question") or ""

        cached = result_cache.get_cached_result(session_id)
        if not cached:
            logger.error(f"No cached result for session {session_id}")
            return {
                "query_result": None,
                "transformation_applied": {"type": "error"},
                "rows_returned": 0,
                "explanation": "Cached result expired",
                "current_phase": "error",
            }

        data, applied = apply_cached_follow_up(list(cached.result_data), question)
        applied["from_question"] = cached.original_question

        if applied.get("error") == "rank_out_of_range":
            return {
                "query_result": None,
                "transformation_applied": applied,
                "rows_returned": 0,
                "explanation": "That position is not in the previous result.",
                "current_phase": "error",
            }

        logger.info(
            f"Follow-up on cached result: {applied.get('type')} "
            f"({len(data)} rows, session={session_id})"
        )

        explanation = _explain_transform(applied, len(data))

        return {
            "query_result": data,
            "transformation_applied": applied,
            "rows_returned": len(data),
            "explanation": explanation,
            "current_phase": "analyze",
            "sql_query": cached.sql_query,
            "reused_previous_result": True,
        }


def _explain_transform(applied: dict, row_count: int) -> str:
    t = applied.get("type")
    if t == "filter":
        return (
            f"Filtered previous result: {applied.get('rows_before')} → "
            f"{applied.get('rows_after')} row(s) ({row_count} shown)."
        )
    if t == "ranking":
        return f"Ranked previous result by {applied.get('column')} ({row_count} row(s))."
    if t == "lookup":
        return f"Selected row {applied.get('rank')} from previous result."
    return f"Reused {row_count} row(s) from previous query (no new SQL)."


result_transformer = ResultTransformer()


def transform_result_node(state: dict) -> dict:
    """Graph node wrapper for result transformation."""
    result = result_transformer.transform(state)
    cached = result_cache.get_cached_result(state.get("session_id"))
    question = state.get("question") or ""
    if cached and cached.original_question:
        enriched = (
            f"Previous question: {cached.original_question}\n"
            f"Follow-up: {question}"
        )
    else:
        enriched = question

    out = {
        **state,
        "question": enriched,
        "enriched_question": enriched,
        "query_result": result.get("query_result"),
        "transformation_applied": result.get("transformation_applied", {}),
        "current_phase": result.get("current_phase", "analyze"),
        "turn_action": "transform_previous",
        "reused_previous_result": result.get("reused_previous_result", True),
        "visualizations": [],
        "plan": None,
        "plan_steps": None,
    }
    if result.get("sql_query"):
        out["sql_query"] = result["sql_query"]
    if result.get("explanation"):
        out["result_preview"] = result["explanation"]
    return out
