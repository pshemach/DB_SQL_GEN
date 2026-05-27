"""
Unified turn router — replaces sequential conversation_router, gap_detector, and follow_up_detector.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from ..config import settings
from ..graph.graph_state import AgentState
from ..tools import business_knowledge_store, business_knowledge_retriever
from ..tools.result_cache import result_cache
from ..utils.json_utils import extract_json
from ..utils.metrics import set_router_action
from ..utils.llm_factory import openai_llm
from ..guardrails.social_messages import is_social_message
from ..utils.llm_factory import groq_llm


TURN_ROUTER_PROMPT = """You are the conversation orchestrator for a Text-to-SQL sales analytics assistant.

Analyze the current question and decide the best routing action.

CONTEXT:
Memory context: {memory_context}
Retrieved KPIs/metrics (known definitions): {retrieved_knowledge}
Previous question: {previous_question}
Cached result available: {has_cached_result}
Last result summary: {last_result_context}
Current question: {question}

DECISION RULES:

1. **KNOWLEDGE GAP DETECTION**: 
   - Extract all KPIs/metrics mentioned in the current question
   - Check if they appear in "Retrieved KPIs/metrics" above
   - If ANY metric is undefined (not in retrieved knowledge), set action=clarify with gap_type=knowledge_gap
   - Examples: "What is revenue trend?" (check if 'revenue' defined), "Show me churn rate" (check if 'churn rate' defined)
   - Examples of legitimate unknowns: custom metrics, business-specific jargon, undefined acronyms

2. **PARAMETER HANDLING**:
   - NEVER clarify for missing parameters: time period, date range, rep code, customer, product, route
   - These are handled downstream with system defaults (rep scope injected, current month for dates)
   - If missing, action=run_sql (system will apply defaults)

3. **CACHED RESULT REUSE**:
   - If has_cached_result=yes and question is a simple transformation (filter, sort, rank, select) on last result rows only → action=transform_previous
   - If cached but needs different data/tables/timeframe → action=run_sql

4. **FALLBACK LOGIC**:
   - Off-topic or social → action=chitchat
   - Empty/nonsense → action=deny
   - Clear, queryable → action=run_sql
   - Follow-up clarifying a pending question → action=run_sql with enriched_question

Return ONLY valid JSON (no markdown, no extra text):
{{
  "action": "run_sql | clarify | transform_previous | deny | chitchat",
  "confidence": 0.0,
  "clarification_question": "What is the business definition for [specific metric]?" or null,
  "gap_type": "knowledge_gap | none",
  "gap_reason": "[reason if gap_type=knowledge_gap]" or null,
  "missing_pieces": ["metric1", "metric2"] or [],
  "follow_up_type": "new_query | filter | transform | refinement",
  "enriched_question": "[rewritten question preserving business meaning, never write SQL]" or null
}}
"""

class TurnRouterAgent:
    def __init__(self):
        # self.llm = openai_llm()
        self.llm = groq_llm()
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", TURN_ROUTER_PROMPT),
            ("human", "{question}"),
        ])
        self.chain = self.prompt | self.llm

    def route(self, state: AgentState) -> dict[str, Any]:
        question = state["question"]
        session_id = state.get("session_id")

        if is_social_message(question):
            metrics = set_router_action(state.get("metrics"), "chitchat")
            return {
                "turn_action": "chitchat",
                "router_confidence": 1.0,
                "metrics": metrics,
            }

        retrieved_knowledge = _retrieve_business_knowledge(question)
        previous_question = _previous_question(session_id)
        cached = result_cache.get_cached_result(session_id) if session_id else None
        last_result_context = (
            result_cache.get_result_context(session_id) if session_id else ""
        )

        try:
            response = self.chain.invoke({
                "question": question,
                "memory_context": state.get("memory_context") or "",
                "retrieved_knowledge": retrieved_knowledge,
                "previous_question": previous_question or "",
                "has_cached_result": "yes" if cached else "no",
                "last_result_context": last_result_context or "(none)",
            })
            result = extract_json(response.content) or _parse_json_fallback(response.content)
        except Exception as e:
            logger.warning(f"Turn router LLM failed: {e}")
            if cached:
                result = {
                    "action": "transform_previous",
                    "confidence": 0.5,
                    "follow_up_type": "refinement",
                }
            else:
                result = {"action": "run_sql", "confidence": 0.5, "follow_up_type": "new_query"}

        action = _normalize_action(result.get("action", "run_sql"))
        action = _apply_feature_flags(action, result)
        action, result = _apply_clarify_policy(action, result, question)

        out: dict[str, Any] = {
            "turn_action": action,
            "router_confidence": float(result.get("confidence", 0.0)),
            "follow_up_type": result.get("follow_up_type", "new_query"),
            "gap_type": result.get("gap_type"),
            "gap_reason": result.get("gap_reason"),
            "missing_pieces": result.get("missing_pieces", []),
            "metrics": set_router_action(state.get("metrics"), action),
        }

        enriched = result.get("enriched_question") or question
        out["question"] = enriched
        out["enriched_question"] = enriched

        if action == "clarify":
            out.update({
                "needs_clarification": True,
                "waiting_for_user": True,
                "question_to_user": result.get("clarification_question")
                or "What is the business definition for this metric?",
                "pending_original_question": question,
                "gap_type": "knowledge_gap",
            })
        elif action == "transform_previous":
            cached = result_cache.get_cached_result(session_id) if session_id else None
            out.update({
                "is_follow_up": True,
                "can_reuse_cached_result": cached is not None,
                "cached_result_id": cached.query_id if cached else None,
            })
        elif action == "run_sql":
            out["needs_clarification"] = False

        return out


def turn_router_node(state: AgentState) -> dict:
    return TurnRouterAgent().route(state)


def _retrieve_business_knowledge(question: str) -> str:
    keyword_matches = business_knowledge_store.keyword_search(question)
    keyword_knowledge = "\n".join(
        f"KPI: {m['name']}\n{m['definition']}" for m in keyword_matches
    )
    vector_knowledge = ""
    if business_knowledge_retriever:
        try:
            vector_knowledge = business_knowledge_retriever.retrieve_business_definitions_block(question)
        except Exception:
            pass
    return "\n\n".join(x for x in [keyword_knowledge, vector_knowledge] if x)


def _previous_question(session_id: str | None) -> str | None:
    if not session_id:
        return None
    cached = result_cache.get_cached_result(session_id)
    return cached.original_question if cached else None

def _normalize_action(action: str) -> str:
    action = (action or "run_sql").strip().lower()
    allowed = {"run_sql", "clarify", "transform_previous", "deny", "chitchat", "cache_hit"}
    return action if action in allowed else "run_sql"


def _apply_feature_flags(action: str, result: dict) -> str:
    if action == "clarify" and not settings.enable_clarify:
        return "run_sql"
    if action == "transform_previous" and not settings.enable_transform_previous:
        return "run_sql"
    return action


# Phrases that indicate parameter-gap style clarification (never allowed)
_PARAMETER_CLARIFY_MARKERS = (
    "time period",
    "date range",
    "which date",
    "rep code",
    "rep,",
    "specific rep",
    "customer",
    "product",
    "route",
    "any filters",
    "would you like to filter",
    "specify:",
    "could you please specify",
)


def _apply_clarify_policy(action: str, result: dict, question: str) -> tuple[str, dict]:
    """
    Never clarify for parameter gaps. Rep scope and defaults are applied downstream.
    """
    gap_type = (result.get("gap_type") or "none").strip().lower()
    clarify_text = (result.get("clarification_question") or "").lower()

    if action != "clarify":
        return action, result

    # Force run_sql for parameter_gap or parameter-style questions
    if gap_type == "parameter_gap":
        logger.info("Turn router: parameter_gap ignored → run_sql")
        return "run_sql", {**result, "gap_type": "none", "action": "run_sql"}

    if any(marker in clarify_text for marker in _PARAMETER_CLARIFY_MARKERS):
        logger.info("Turn router: parameter-style clarification blocked → run_sql")
        enriched = result.get("enriched_question") or question
        return "run_sql", {
            **result,
            "action": "run_sql",
            "gap_type": "none",
            "enriched_question": enriched,
            "clarification_question": None,
        }

    # clarify only for knowledge_gap
    if gap_type not in ("knowledge_gap", ""):
        return "run_sql", {**result, "gap_type": "none", "action": "run_sql"}

    return action, result


def _parse_json_fallback(text: str) -> dict:
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except json.JSONDecodeError:
        pass
    return {"action": "run_sql", "confidence": 0.5}