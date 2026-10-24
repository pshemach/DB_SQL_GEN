"""
LLM-driven follow-up on cached query results + strict post-processing.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from src.memory.result_cache import CachedQueryResult
from src.utils.json_utils import extract_json
from src.utils.transform_spec_postprocess import normalize_and_validate_spec
from src.agents.prompts.agent_prompts import CACHE_FOLLOW_UP_PROMPT
from src.infrastructure.llm import get_chat_llm

class CacheFollowUpAgent:
    def __init__(self):
        self.llm = get_chat_llm(temperature=0)
        # self.llm = get_fast_chat_llm(temperature=0)
        
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
