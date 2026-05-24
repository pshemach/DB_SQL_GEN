"""
LLM-driven follow-up on cached query results + strict post-processing.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from ..tools.result_cache import CachedQueryResult
from ..utils.json_utils import extract_json
from ..utils.llm_factory import openai_llm
from ..utils.transform_spec_postprocess import normalize_and_validate_spec

CACHE_FOLLOW_UP_PROMPT = """You plan how to answer a follow-up using ONLY the previous query result rows.

Previous question: {previous_question}
Columns (use these exact names): {columns}
Row count: {row_count}
Sample rows (JSON): {sample_rows}

Follow-up question: {follow_up_question}

Return ONLY valid JSON (one operation value, no pipes):
{{
  "can_answer_from_cache": true,
  "needs_new_sql": false,
  "operation": "use_all",
  "filters": [],
  "sort": null,
  "limit": null,
  "rank": null,
  "group_top_per": null,
  "explanation": "brief reason"
}}

operation must be exactly ONE of:
- use_all — return rows unchanged (after filters if any)
- filter — row filters only
- sort — sort rows (set sort object)
- head — take first N rows after sort (set sort + limit)
- row_at_rank — pick Nth row after sort (set sort + rank)
- group_top_per — best/top row per group (set group_top_per object)

group_top_per shape:
{{"group_by": "<exact column>", "value_column": "<exact numeric column>", "direction": "asc|desc", "take_per_group": 1}}

Rules:
- needs_new_sql=true if the follow-up needs other tables, new joins, new date scope, or metrics not in these columns.
- needs_new_sql=true for "for each X find best Y" unless group_by and value_column exist in the column list (then use group_top_per).
- filters/sort/rank: column names MUST match the Columns list exactly (copy from sample).
- Do not combine operations with | or commas in the operation field.
- Never invent column names.
"""


class CacheFollowUpAgent:
    def __init__(self):
        self.llm = openai_llm(temperature=0)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", CACHE_FOLLOW_UP_PROMPT),
            ("human", "{follow_up_question}"),
        ])
        self.chain = self.prompt | self.llm

    def plan(
        self,
        follow_up_question: str,
        cached: CachedQueryResult,
        memory_context: str = "",
    ) -> dict[str, Any]:
        rows = cached.result_data or []
        sample = rows[:25]
        columns = list(cached.schema.keys()) if cached.schema else (
            list(sample[0].keys()) if sample else []
        )
        columns = [str(c) for c in columns]

        try:
            response = self.chain.invoke({
                "follow_up_question": follow_up_question,
                "previous_question": cached.original_question,
                "columns": columns,
                "row_count": len(rows),
                "sample_rows": json.dumps(sample, default=str),
            })
            text = response.content if hasattr(response, "content") else str(response)
            raw = extract_json(text)
        except Exception as e:
            logger.warning(f"Cache follow-up LLM failed: {e}")
            raw = {
                "can_answer_from_cache": False,
                "needs_new_sql": True,
                "operation": "use_all",
                "explanation": f"Planner error: {e}",
            }

        return normalize_and_validate_spec(
            raw,
            columns=columns,
            row_count=len(rows),
            explanation=raw.get("explanation") or "",
        )


cache_follow_up_agent = CacheFollowUpAgent()
