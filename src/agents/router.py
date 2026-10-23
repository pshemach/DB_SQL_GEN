"""Small-LLM turn classifier. Security denies stay local; grain and metric come from the model."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from src.agents.prompts import ROUTER_PROMPT
from src.infrastructure.json import extract_json
from src.infrastructure.llm.llm_provider import openai_llm
from src.semantic.layer import kpis, load_layer

DENY_PATTERN = re.compile(r"(?i)\b(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|INSERT\s+INTO)\b")
ACTIONS = {"chitchat", "deny", "transform_previous", "kpi", "analyze", "adhoc", "clarify"}


def route_turn(question: str, session_frame: str = "", has_cached_result: bool = False) -> dict[str, Any]:
    q = (question or "").strip()
    if len(q) < 2:
        return _deny("Question too short.")
    if DENY_PATTERN.search(q):
        return _deny("Suspicious or mutating request.")
    return _llm_route(q, session_frame, has_cached_result)


def next_node(decision: dict[str, Any]) -> str:
    action = decision.get("turn_action") or "analyze"
    if action == "deny":
        return "safe_response"
    if action == "chitchat":
        return "chitchat"
    if action == "clarify":
        return "hitl"
    if action == "transform_previous":
        return "transform"
    if action == "kpi" and decision.get("dimensions") and decision.get("metric_keys"):
        return "kpi"
    return "analyst"


def normalize_router_payload(parsed: dict[str, Any], question: str) -> dict[str, Any]:
    layer = load_layer()
    known_metrics = set(kpis())
    known_dimensions = set((layer.get("dimensions") or {}).keys())
    known_periods = set((layer.get("time_templates") or {}).keys()) or {"current_month", "last_month"}

    action = parsed.get("action") or "analyze"
    if action not in ACTIONS:
        action = "analyze"
    if action == "adhoc":
        action = "analyze"

    metrics = [key for key in (parsed.get("metric_keys") or []) if key in known_metrics]
    dimensions = [key for key in (parsed.get("dimensions") or []) if key in known_dimensions]
    period = parsed.get("period") if parsed.get("period") in known_periods else "current_month"
    if action == "kpi" and (not metrics or not dimensions):
        action = "analyze"

    return {
        "turn_action": action,
        "router_confidence": float(parsed.get("confidence") or 0.6),
        "metric_keys": metrics,
        "period": period,
        "dimensions": dimensions,
        "analysis_types": list(parsed.get("analysis_types") or []),
        "enriched_question": parsed.get("enriched_question") or question,
        "question_to_user": parsed.get("clarification_question"),
        "needs_clarification": action == "clarify",
        "waiting_for_user": action == "clarify",
        "access_denied": action == "deny",
        "access_denied_reason": None,
        "error": None,
        "error_type": None,
    }


def _llm_route(question: str, session_frame: str, has_cached_result: bool) -> dict[str, Any]:
    frame = session_frame or ""
    if has_cached_result:
        frame = f"{frame}\nA previous result is cached for this session.".strip()
    try:
        chain = ChatPromptTemplate.from_template(ROUTER_PROMPT) | openai_llm()
        parsed = extract_json(chain.invoke({"question": question, "session_frame": frame}).content)
        return normalize_router_payload(parsed, question)
    except Exception as e:
        logger.warning(f"Router LLM failed: {e}")
        return normalize_router_payload({"action": "analyze", "enriched_question": question}, question)


def _deny(reason: str) -> dict[str, Any]:
    return {
        "turn_action": "deny",
        "router_confidence": 1.0,
        "metric_keys": [],
        "period": "current_month",
        "dimensions": [],
        "analysis_types": [],
        "enriched_question": None,
        "needs_clarification": False,
        "waiting_for_user": False,
        "access_denied": True,
        "access_denied_reason": reason,
        "error": reason,
        "error_type": "guardrail_rejection",
        "question_to_user": None,
    }
