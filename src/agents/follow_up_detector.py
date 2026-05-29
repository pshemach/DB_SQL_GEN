"""Follow-Up Detector Agent - Classify query type and detect cached result reusability."""
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from loguru import logger
from src.agents.tools.result_cache import result_cache
from src.config import settings
from ..utils.llm_factory import groq_llm
import json
import re


class FollowUpDetector:
    """Detect if query is follow-up and determine if cached result can be reused."""

    def __init__(self):
        self.llm = groq_llm(temperature=0)

    def detect(self, state: dict) -> dict:
        """
        Classify current query as follow-up or new query.
        
        Classification types:
        - new_query: Completely different from previous
        - filter: Same base query + filters applied
        - transform: Same result + sort/group/limit applied
        - refinement: Same query with different parameters
        - clarification: User asking about previous result
        
        Returns:
            {
                "is_follow_up": bool,
                "follow_up_type": str,
                "can_reuse_cached_result": bool,
                "required_transformations": [str],
                "cached_result_id": str or None
            }
        """
        session_id = state.get("session_id")
        current_question = state.get("question")

        # Try to get previous cached result
        cached = result_cache.get_cached_result(session_id)

        if not cached:
            logger.info("No cached result found - treating as new query")
            return {
                "is_follow_up": False,
                "follow_up_type": "new_query",
                "can_reuse_cached_result": False,
                "required_transformations": [],
                "cached_result_id": None
            }

        # Analyze if this is a follow-up
        analysis = self._analyze_query_relationship(
            previous_question=cached.original_question,
            current_question=current_question,
            cached_tables=cached.tables_used
        )

        logger.info(f"Follow-up detection: {analysis.get('type')} "
                   f"(confidence: {analysis.get('confidence', 0)})")

        return {
            "is_follow_up": analysis.get("is_follow_up", False),
            "follow_up_type": analysis.get("type", "new_query"),
            "can_reuse_cached_result": analysis.get("can_reuse", False),
            "required_transformations": analysis.get("transformations", []),
            "cached_result_id": cached.query_id if analysis.get("can_reuse") else None
        }

    def _analyze_query_relationship(self, previous_question: str, current_question: str,
                                     cached_tables: list) -> dict:
        """
        Use LLM to classify query relationship.
        Returns: {type, is_follow_up, can_reuse, transformations[], confidence}
        """
        prompt = f"""Analyze if this is a follow-up query.

Previous Question: {previous_question}
Current Question: {current_question}
Tables Used Previously: {cached_tables}

Classify as ONE of:
1. "new_query" - Completely different subject
2. "filter" - Same base query with additional filters
3. "transform" - Same data with different sort/group/limit
4. "refinement" - Same query with parameter changes
5. "clarification" - User asking about previous result

Return ONLY JSON:
{{
  "type": "...",
  "is_follow_up": true/false,
  "can_reuse": true/false,
  "transformations": ["filter_region", "sort_desc"],
  "confidence": 0.8
}}"""

        try:
            response = self.llm.invoke(prompt)
            result = self._parse_response(response.content)
            return result
        except Exception as e:
            logger.warning(f"Follow-up analysis failed: {e}, treating as new")
            return {
                "type": "new_query",
                "is_follow_up": False,
                "can_reuse": False,
                "transformations": [],
                "confidence": 0.0
            }

    def _parse_response(self, response: str) -> dict:
        """Extract JSON from LLM response."""
        try:
            json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except (json.JSONDecodeError, AttributeError):
            pass

        return {
            "type": "new_query",
            "is_follow_up": False,
            "can_reuse": False,
            "transformations": [],
            "confidence": 0.0
        }


follow_up_detector = FollowUpDetector()


def follow_up_detector_node(state: dict) -> dict:
    """Graph node wrapper for follow-up detection."""
    result = follow_up_detector.detect(state)
    
    # Add to state for routing
    return {
        **state,
        "is_follow_up": result.get("is_follow_up", False),
        "follow_up_type": result.get("follow_up_type", "new_query"),
        "can_reuse_cached_result": result.get("can_reuse_cached_result", False),
        "required_transformations": result.get("required_transformations", []),
        "cached_result_id": result.get("cached_result_id")
    }
