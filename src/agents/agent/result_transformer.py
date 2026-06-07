"""Apply LLM-planned transforms on the session's last query result (no new SQL)."""

from __future__ import annotations
from loguru import logger

from src.agents.tools.result_cache import result_cache
from src.agents.tools.local_sql_engine import local_sql_engine
from src.agents.agent.table_analyst import table_analyst

class ResultTransformer:
    """Dynamic follow-up via DuckDB local SQL engine + Table Analyst agent."""

    def transform(self, state: dict) -> dict:
        session_id = state.get("session_id")
        question = state.get("original_question") or state.get("question") or ""
        memory_context = state.get("memory_context") or ""

        # 1. Retrieve the cached query result
        cached = result_cache.get_cached_result(session_id)
        if not cached:
            logger.error(f"No cached result found for session {session_id}")
            return {
                "query_result": None,
                "needs_new_sql": True,
                "transformation_applied": {"type": "error", "reason": "cache_expired"},
                "rows_returned": 0,
                "explanation": "Cached result expired or unavailable.",
                "current_phase": "error",
            }

        # 2. Intent Classification (Semantic/Explain vs. Computational/Filter)
        semantic_keywords = ["why", "explain", "summarize", "highlights", "insights", "reason", "describe", "trend", "cause"]
        is_semantic_explanation = any(kw in question.lower() for kw in semantic_keywords)

        if is_semantic_explanation:
            # PATH A: Semantic reasoning / Natural Language explanation
            logger.info("Follow-up classified as SEMANTIC EXPLANATION. Routing to Table Analyst.")
            analysis_text = table_analyst.analyze_table(
                follow_up_question=question,
                cached_data=cached.result_data,
                source_question=cached.original_question,
                memory_context=memory_context
            )
            
            return {
                "query_result": cached.result_data, # Return unchanged rows
                "needs_new_sql": False,
                "transformation_applied": {
                    "type": "semantic_analysis",
                    "from_question": cached.original_question
                },
                "rows_returned": len(cached.result_data),
                "explanation": analysis_text,
                "current_phase": "analyze",
                "sql_query": cached.sql_query,
                "reused_previous_result": True,
            }

        # PATH B: Computational subsetting / Sorting / Filtering / Aggregating
        logger.info("Follow-up classified as COMPUTATIONAL TRANSFORMATION. Routing to DuckDB.")
        needs_live_db, local_results, explanation = local_sql_engine.execute_follow_up(
            follow_up_question=question,
            cached_data=cached.result_data,
            schema=cached.schema
        )

        if needs_live_db:
            logger.info(f"Local SQL engine indicates live DB is needed. Reason: {explanation}")
            return {
                "query_result": None,
                "needs_new_sql": True,
                "transformation_applied": {"type": "needs_new_sql", "reason": explanation},
                "rows_returned": 0,
                "explanation": explanation,
                "current_phase": "error",
                "enriched_question": question,
            }

        # Local execution succeeded
        logger.info(f"Successfully processed local DuckDB query. Returned {len(local_results)} rows.")
        return {
            "query_result": local_results,
            "needs_new_sql": False,
            "transformation_applied": {
                "type": "duckdb_sql",
                "sql": plan_sql if 'plan_sql' in locals() else "local_duckdb",
                "from_question": cached.original_question
            },
            "rows_returned": len(local_results),
            "explanation": explanation,
            "current_phase": "analyze",
            "sql_query": cached.sql_query,
            "reused_previous_result": True,
        }

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
        "turn_action": "transform_previous" if not result.get("needs_new_sql") else "run_sql",
        "reused_previous_result": result.get("reused_previous_result", False),
        "visualizations": [],
        "plan": None,
        "plan_steps": None,
    }
    
    if result.get("sql_query"):
        out["sql_query"] = result["sql_query"]
    if result.get("explanation"):
        # Put analysis text directly in result preview so Formatter renders it
        out["result_preview"] = result["explanation"]
        out["final_answer"] = result["explanation"]
        out["result_summary"] = result["explanation"]
        
    return out
