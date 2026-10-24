"""Follow-up transforms on the last query result, plus table analysis."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
from loguru import logger

from src.agents.prompts.agent_prompts import (
    build_follow_up_prompt,
    build_table_analyst_prompt,
    chat_messages,
)
from src.agents.tools.local_sql_engine import LocalSQLEngine
from src.infrastructure.llm import get_direct_llm, get_router_llm
from src.memory.result_cache import result_cache
from src.utils.json_utils import extract_json

class TableAnalystAgent:
    """Performs business analysis and explains trends over cached query results."""
    
    def __init__(self, llm=None):
        self.llm = llm or get_direct_llm()

    def analyze_table(
        self,
        follow_up_question: str,
        cached_data: List[Dict[str, Any]],
        source_question: str,
        memory_context: str = ""
    ) -> str:
        """
        Analyzes the cached query results to answer the follow-up question.
        """
        if not cached_data:
            return "No data available from the previous query to analyze."

        try:
            df = pd.DataFrame(cached_data)
            
            # Limit rows in LLM context to prevent token bloat (take top 40 for context)
            context_rows = df.head(40)
            table_markdown = context_rows.to_markdown(index=False)
            
            if len(df) > 40:
                table_markdown += f"\n\n*Note: Displaying first 40 of {len(df)} total rows. Summarize accordingly.*"

            system_prompt, user_prompt = build_table_analyst_prompt(
                follow_up_question,
                source_question,
                len(df),
                ", ".join(df.columns),
                table_markdown,
                memory_context,
            )
            resp = self.llm.invoke(chat_messages(system_prompt, user_prompt))
            return resp.content.strip()
        except Exception as e:
            logger.error(f"Table Analyst failed: {e}")
            return f"Failed to perform table analysis: {e}"

class ResultTransformer:
    """Dynamic follow-up via LLM classifier + DuckDB local SQL + Table Analyst."""

    def __init__(self, llm=None, analyst_llm=None):
        self.llm = llm or get_router_llm(temperature=0)
        self.analyst = TableAnalystAgent(analyst_llm)

    def transform(self, state: dict) -> dict:
        session_id = state.get("session_id")
        question = state.get("original_question") or state.get("question") or ""
        memory_context = state.get("memory_context") or ""

        cached = result_cache.get_cached_result(session_id)

        if not cached:
            logger.error(f"No cached result found for session {session_id}")
            return {
                "query_result": None,
                "needs_new_sql": True,
                "transformation_applied": {
                    "type": "error",
                    "reason": "cache_expired"
                },
                "rows_returned": 0,
                "explanation": "Cached result expired or unavailable.",
                "current_phase": "error",
                "enriched_question": question,
                "formatter_mode": "new_sql_required",
            }

        decision = self._classify_follow_up(
            question=question,
            cached=cached,
            memory_context=memory_context
        )

        action = decision.get("action")
        logger.info(f"Follow-up classified as {action}: {decision.get('reason')}")

        if action == "semantic_analysis":
            analysis_text = self.analyst.analyze_table(
                follow_up_question=question,
                cached_data=cached.result_data,
                source_question=cached.original_question,
                memory_context=memory_context
            )

            return {
                "query_result": cached.result_data,
                "needs_new_sql": False,
                "transformation_applied": {
                    "type": "semantic_analysis",
                    "from_question": cached.original_question,
                    "classifier_reason": decision.get("reason")
                },
                "rows_returned": len(cached.result_data),
                "explanation": analysis_text,
                "current_phase": "semantic_analysis",
                "sql_query": cached.sql_query,
                "reused_previous_result": True,
                "formatter_mode": "semantic_answer",
            }

        if action == "needs_new_sql":
            return {
                "query_result": None,
                "needs_new_sql": True,
                "transformation_applied": {
                    "type": "needs_new_sql",
                    "reason": decision.get("reason"),
                    "missing_columns": decision.get("missing_columns", [])
                },
                "rows_returned": 0,
                "explanation": decision.get("reason"),
                "current_phase": "needs_new_sql",
                "enriched_question": question,
                "formatter_mode": "new_sql_required",
            }

        # local_transform
        result = LocalSQLEngine().execute_follow_up(
            follow_up_question=question,
            cached_data=cached.result_data,
            schema=cached.schema
        )

        local_sql = None

        if len(result) == 4:
            needs_live_db, local_results, explanation, local_sql = result
        else:
            needs_live_db, local_results, explanation = result

        if needs_live_db:
            return {
                "query_result": None,
                "needs_new_sql": True,
                "transformation_applied": {
                    "type": "needs_new_sql",
                    "reason": explanation
                },
                "rows_returned": 0,
                "explanation": explanation,
                "current_phase": "needs_new_sql",
                "enriched_question": question,
                "formatter_mode": "new_sql_required",
            }

        return {
            "query_result": local_results,
            "needs_new_sql": False,
            "transformation_applied": {
                "type": "duckdb_sql",
                "sql": local_sql or "local_duckdb",
                "from_question": cached.original_question,
                "classifier_reason": decision.get("reason")
            },
            "rows_returned": len(local_results),
            "explanation": explanation,
            "current_phase": "local_transform",
            "sql_query": cached.sql_query,
            "local_sql_query": local_sql,
            "reused_previous_result": True,
            "formatter_mode": "dynamic_result",
        }
        
    def _classify_follow_up(
        self,
        question: str,
        cached,
        memory_context: str
    ) -> dict:
        try:
            system_prompt, user_prompt = build_follow_up_prompt(
                question,
                cached.original_question,
                cached.schema,
                memory_context,
            )
            response = self.llm.invoke(chat_messages(system_prompt, user_prompt))

            text = response.content if hasattr(response, "content") else str(response)
            result = extract_json(text)

            action = result.get("action")

            if action not in ["semantic_analysis", "local_transform", "needs_new_sql"]:
                return {
                    "action": "needs_new_sql",
                    "reason": "Invalid classifier action.",
                    "required_columns": [],
                    "missing_columns": []
                }

            return result

        except Exception as e:
            logger.error(f"Follow-up classifier failed: {e}")
            return {
                "action": "needs_new_sql",
                "reason": "Classifier failed; using live SQL fallback.",
                "required_columns": [],
                "missing_columns": []
            }
