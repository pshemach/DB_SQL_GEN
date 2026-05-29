"""Apply LLM-planned transforms on the session's last query result (no new SQL)."""

from __future__ import annotations

from loguru import logger

from src.agents.agent.cache_follow_up_agent import cache_follow_up_agent
from src.agents.tools.result_cache import result_cache
from src.utils.cached_result_ops import execute_transform_spec


class ResultTransformer:
    """Dynamic follow-up via CacheFollowUpAgent + safe row operations."""

    def transform(self, state: dict) -> dict:
        session_id = state.get("session_id")
        question = state.get("original_question") or state.get("question") or ""

        cached = result_cache.get_cached_result(session_id)
        if not cached:
            logger.error(f"No cached result for session {session_id}")
            return {
                "query_result": None,
                "needs_new_sql": True,
                "transformation_applied": {"type": "error"},
                "rows_returned": 0,
                "explanation": "Cached result expired",
                "current_phase": "error",
            }

        spec = cache_follow_up_agent.plan(
            follow_up_question=question,
            cached=cached,
            memory_context=state.get("memory_context") or "",
        )

        if spec.get("needs_new_sql") or not spec.get("can_answer_from_cache"):
            logger.info("Follow-up needs new SQL (LLM planner)")
            return {
                "query_result": None,
                "needs_new_sql": True,
                "transform_spec": spec,
                "transformation_applied": {"type": "needs_new_sql", "spec": spec},
                "rows_returned": 0,
                "explanation": spec.get("explanation")
                or "This follow-up requires a new database query.",
                "current_phase": "error",
                "enriched_question": question,
            }

        data, applied = execute_transform_spec(list(cached.result_data), spec)
        applied["from_question"] = cached.original_question

        if applied.get("type") == "needs_new_sql":
            logger.info(f"Transform execution needs SQL: {applied.get('reason')}")
            return {
                "query_result": None,
                "needs_new_sql": True,
                "transform_spec": spec,
                "transformation_applied": applied,
                "rows_returned": 0,
                "explanation": applied.get("reason")
                or spec.get("explanation")
                or "Cached rows cannot answer this follow-up.",
                "current_phase": "error",
                "enriched_question": question,
            }

        if applied.get("error") == "rank_out_of_range":
            return {
                "query_result": None,
                "needs_new_sql": False,
                "transformation_applied": applied,
                "rows_returned": 0,
                "explanation": "That position is not in the previous result.",
                "current_phase": "error",
            }

        logger.info(
            f"Follow-up on cached result: {applied.get('type')} "
            f"({len(data)} rows, session={session_id})"
        )

        explanation = spec.get("explanation") or _explain_transform(applied, len(data))

        return {
            "query_result": data,
            "needs_new_sql": False,
            "transform_spec": spec,
            "transformation_applied": applied,
            "rows_returned": len(data),
            "explanation": explanation,
            "current_phase": "analyze",
            "sql_query": cached.sql_query,
            "reused_previous_result": True,
        }


def _explain_transform(applied: dict, row_count: int) -> str:
    spec = applied.get("spec") or {}
    if spec.get("explanation"):
        return spec["explanation"]
    return f"Answered from previous result ({row_count} row(s), no new SQL)."


result_transformer = ResultTransformer()


def transform_result_node(state: dict) -> dict:
    """Graph node wrapper for result transformation."""
    result = result_transformer.transform(state)
    cached = result_cache.get_cached_result(state.get("session_id"))
    question = state.get("original_question") or state.get("question") or ""

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
        "enriched_question": result.get("enriched_question") or enriched,
        "query_result": result.get("query_result"),
        "needs_new_sql": result.get("needs_new_sql", False),
        "transformation_applied": result.get("transformation_applied", {}),
        "current_phase": result.get("current_phase", "analyze"),
        "turn_action": "transform_previous",
        "reused_previous_result": result.get("reused_previous_result", False),
        "visualizations": [],
        "plan": None,
        "plan_steps": None,
    }
    if result.get("sql_query"):
        out["sql_query"] = result["sql_query"]
    if result.get("explanation"):
        out["result_preview"] = result["explanation"]
    return out
