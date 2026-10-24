"""
LLM-driven follow-up on cached query results + strict post-processing.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from src.memory.result_cache import CachedQueryResult
from src.utils.json_utils import extract_json
from src.utils.transform_spec_postprocess import normalize_and_validate_spec
from src.agents.prompts.agent_prompts import build_cache_follow_up_prompt, chat_messages
from src.infrastructure.llm import get_chat_llm

class CacheFollowUpAgent:
    def __init__(self):
        self.llm = get_chat_llm(temperature=0)

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
            system_prompt, user_prompt = build_cache_follow_up_prompt(
                follow_up_question,
                cached.original_question,
                columns,
                len(rows),
                json.dumps(sample, default=str),
            )
            response = self.llm.invoke(chat_messages(system_prompt, user_prompt))
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
