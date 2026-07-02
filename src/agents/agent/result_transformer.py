"""Apply LLM-planned transforms on the session's last query result (no new SQL)."""

from __future__ import annotations
from loguru import logger

from src.agents.tools.result_cache import result_cache
from src.agents.tools.local_sql_engine import local_sql_engine
from src.agents.agent.table_analyst import table_analyst

from langchain_core.prompts import ChatPromptTemplate
from src.utils.llm_factory import groq_llm
from src.utils.json_utils import extract_json

FOLLOW_UP_CLASSIFIER_PROMPT = """
You are a follow-up query classifier for a Sales BI assistant.

The user has already received a previous table result.
You must decide how to answer the latest follow-up question.

Previous question:
{previous_question}

Previous result schema:
{schema}

Latest follow-up question:
{question}

Conversation context:
{memory_context}

Classify the follow-up into exactly one action:

1. semantic_analysis
Use this when the user asks for explanation, insight, reasoning, summary, interpretation, highlights, comparison meaning, business meaning, or trend explanation using the previous result.

2. local_transform
Use this when the user asks to sort, filter, limit, rank, calculate total/average/count, group, show top/bottom, or reshape the previous result using columns already available in the previous result schema.

3. needs_new_sql
Use this when the user asks for a new metric, new column, new table, new date range, new entity, drilldown not available in previous result, or anything that cannot be answered using only the previous result schema.

Return ONLY valid JSON:
{{
  "action": "semantic_analysis | local_transform | needs_new_sql",
  "reason": "short reason",
  "required_columns": [],
  "missing_columns": []
}}
"""

class ResultTransformer:
    """Dynamic follow-up via LLM classifier + DuckDB local SQL + Table Analyst."""

    def __init__(self):
        self.classifier_prompt = ChatPromptTemplate.from_messages([
            ("system", FOLLOW_UP_CLASSIFIER_PROMPT),
            ("human", "{question}")
        ])
        self.classifier_chain = self.classifier_prompt | groq_llm(temperature=0)

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
            analysis_text = table_analyst.analyze_table(
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
        result = local_sql_engine.execute_follow_up(
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
            response = self.classifier_chain.invoke({
                "question": question,
                "previous_question": cached.original_question,
                "schema": cached.schema,
                "memory_context": memory_context,
            })

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