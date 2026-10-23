"""Deterministic fast-path plus a small-LLM fallback for turn classification."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from src.agents.prompts import ROUTER_PROMPT
from src.guardrails.social_messages import is_social_message
from src.infrastructure.json import extract_json
from src.infrastructure.llm.llm_provider import openai_llm
from src.semantic.layer import match_kpi_keys, period_from_question

DENY_PATTERN = re.compile(r"(?i)\b(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|INSERT\s+INTO)\b")
TRANSFORM_HINTS = (
    "sort", "filter", "top ", "bottom ", "rank", "only show", "chart", "explain this", "what does this mean",
)
ANALYZE_HINTS = (
    "why", "forecast", "predict", "will i hit", "what should", "improve", "compare", "vs last",
    "gap", "projection", "recommend", "and then", "also tell",
)


def route_turn(question: str, session_frame: str = "", has_cached_result: bool = False) -> dict[str, Any]:
    q = (question or "").strip()
    if len(q) < 2:
        return _result("deny", "Question too short.")
    if DENY_PATTERN.search(q):
        return _result("deny", "Suspicious or mutating request.")
    if is_social_message(q):
        return _result("chitchat")

    ql = q.lower()
    metrics = match_kpi_keys(q)
    period = period_from_question(q)
    if has_cached_result and any(h in ql for h in TRANSFORM_HINTS) and not any(h in ql for h in ANALYZE_HINTS):
        return _result("transform_previous", metrics=metrics, period=period, enriched=q)
    if any(h in ql for h in ANALYZE_HINTS):
        analysis = []
        if any(w in ql for w in ("why", "gap")):
            analysis.append("diagnose")
        if any(w in ql for w in ("forecast", "predict", "will i hit", "projection")):
            analysis.append("forecast")
        if "compare" in ql or "vs last" in ql:
            analysis.append("compare")
        if any(w in ql for w in ("what should", "improve", "recommend")):
            analysis.append("recommend")
        return _result("analyze", metrics=metrics or ["net_value"], period=period, analysis=analysis or ["diagnose"], enriched=q)
    if metrics and not any(w in ql for w in ("join", "invoice no", "column")):
        return _result("kpi", metrics=metrics, period=period, enriched=q)

    return _llm_route(q, session_frame, metrics, period)


def _llm_route(question: str, session_frame: str, metrics: list[str], period: str) -> dict[str, Any]:
    try:
        chain = ChatPromptTemplate.from_template(ROUTER_PROMPT) | openai_llm()
        parsed = extract_json((chain.invoke({"question": question, "session_frame": session_frame})).content)
        action = parsed.get("action") or "analyze"
        return {
            "turn_action": action,
            "router_confidence": float(parsed.get("confidence") or 0.6),
            "metric_keys": parsed.get("metric_keys") or metrics,
            "period": parsed.get("period") or period,
            "dimensions": parsed.get("dimensions") or ["rep"],
            "analysis_types": parsed.get("analysis_types") or [],
            "enriched_question": parsed.get("enriched_question") or question,
            "question_to_user": parsed.get("clarification_question"),
            "needs_clarification": action == "clarify",
            "waiting_for_user": action == "clarify",
        }
    except Exception as e:
        logger.warning(f"Router LLM fallback failed: {e}")
        return _result("analyze", metrics=metrics or ["net_value"], period=period, enriched=question)


def _result(
    action: str,
    reason: str | None = None,
    metrics: list | None = None,
    period: str = "current_month",
    analysis: list | None = None,
    enriched: str | None = None,
) -> dict[str, Any]:
    out = {
        "turn_action": action,
        "router_confidence": 0.95,
        "metric_keys": metrics or [],
        "period": period,
        "dimensions": ["rep"],
        "analysis_types": analysis or [],
        "enriched_question": enriched,
        "needs_clarification": action == "clarify",
        "waiting_for_user": action == "clarify",
        "access_denied": action == "deny",
        "access_denied_reason": reason if action == "deny" else None,
        "error": reason if action == "deny" else None,
        "error_type": "guardrail_rejection" if action == "deny" else None,
        "question_to_user": reason if action == "clarify" else None,
    }
    return out
