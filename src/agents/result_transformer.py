"""Result Transformer Agent - Apply in-memory transformations to cached results."""
from langchain_anthropic import ChatAnthropic
from loguru import logger
from src.tools.result_cache import result_cache
from src.config import settings
import json
import re
import pandas as pd
from ..utils.llm_factory import groq_llm


class ResultTransformer:
    """Apply filters, sorts, and limits to cached results in-memory."""

    def __init__(self):
        # self.llm = ChatAnthropic(model=settings.anthropic_model_fast)
        self.llm = groq_llm()

    def transform(self, state: dict) -> dict:
        """
        Apply transformations to cached result.
        
        Supports:
        - filter: Apply WHERE conditions
        - sort: Order by column
        - limit: LIMIT/TOP
        - group: GROUP BY aggregation
        
        Returns:
            {
                "query_result": transformed data,
                "transformation_applied": {type, filters, sorts, limit},
                "rows_returned": count,
                "explanation": user-friendly summary
            }
        """
        session_id = state.get("session_id")
        question = state.get("question")
        cached_result_id = state.get("cached_result_id")

        # Get cached result
        cached = result_cache.get_cached_result(session_id, cached_result_id)
        if not cached:
            logger.error(f"Cached result {cached_result_id} not found")
            return {
                "query_result": None,
                "transformation_applied": {},
                "rows_returned": 0,
                "explanation": "Cached result expired",
                "current_phase": "error"
            }

        # Parse what transformations are needed
        transformation_spec = self._parse_transformation_request(
            question,
            cached.question,
            cached.schema
        )

        logger.info(f"Applying transformations: {transformation_spec}")

        # Apply transformations
        try:
            transformed_data = self._apply_transforms(
                cached.result_data,
                transformation_spec
            )

            return {
                "query_result": transformed_data,
                "transformation_applied": transformation_spec,
                "rows_returned": len(transformed_data),
                "explanation": self._generate_explanation(transformation_spec),
                "current_phase": "analyze"
            }

        except Exception as e:
            logger.error(f"Transformation failed: {e}")
            return {
                "query_result": None,
                "transformation_applied": {},
                "rows_returned": 0,
                "explanation": f"Transformation failed: {str(e)}",
                "current_phase": "error"
            }

    def _parse_transformation_request(self, current_question: str, 
                                      original_question: str, schema: dict) -> dict:
        """Use LLM to parse what transformations are needed."""
        prompt = f"""Extract transformation operations from this query.

Original Query: {original_question}
Current Query: {current_question}
Available Columns: {list(schema.keys())}

Return ONLY JSON:
{{
  "filters": {{"column": "condition"}},
  "sorts": [{{\"column\": \"ascending\"}}],
  "limit": 10,
  "group_by": ["column"],
  "aggregations": {{}}
}}"""

        try:
            response = self.llm.invoke(prompt)
            result = self._parse_response(response.content)
            return result
        except Exception as e:
            logger.warning(f"Could not parse transformation: {e}")
            return {"filters": {}, "sorts": [], "limit": None}

    def _apply_transforms(self, data: list, spec: dict) -> list:
        """Apply transformations to data."""
        # Convert to DataFrame for easier manipulation
        df = pd.DataFrame(data)
        
        # Apply filters
        filters = spec.get("filters", {})
        for col, condition in filters.items():
            if col in df.columns:
                try:
                    df = df.query(f"{col} {condition}")
                except Exception as e:
                    logger.warning(f"Filter failed: {e}")

        # Apply sorts
        sorts = spec.get("sorts", [])
        for sort_spec in sorts:
            col = sort_spec.get("column")
            if col in df.columns:
                ascending = sort_spec.get("direction", "ascending") == "ascending"
                df = df.sort_values(col, ascending=ascending)

        # Apply limit
        limit = spec.get("limit")
        if limit:
            df = df.head(limit)

        return df.to_dict("records")

    def _parse_response(self, response: str) -> dict:
        """Extract JSON from LLM response."""
        try:
            json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except (json.JSONDecodeError, AttributeError):
            pass

        return {"filters": {}, "sorts": [], "limit": None}

    def _generate_explanation(self, spec: dict) -> str:
        """Generate user-friendly explanation of transformations applied."""
        parts = []
        
        if spec.get("filters"):
            parts.append(f"Applied {len(spec['filters'])} filter(s)")
        
        if spec.get("sorts"):
            parts.append(f"Sorted by {len(spec['sorts'])} column(s)")
        
        if spec.get("limit"):
            parts.append(f"Limited to {spec['limit']} rows")
        
        return " | ".join(parts) if parts else "No transformations applied"


result_transformer = ResultTransformer()


def transform_result_node(state: dict) -> dict:
    """Graph node wrapper for result transformation."""
    result = result_transformer.transform(state)
    
    return {
        **state,
        "query_result": result.get("query_result"),
        "transformation_applied": result.get("transformation_applied", {}),
        "current_phase": result.get("current_phase", "analyze")
    }
