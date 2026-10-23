"""Small-LLM turn classifier. Data questions always generate SQL."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from src.agents.prompts import ROUTER_PROMPT
from src.infrastructure.json import extract_json
from src.infrastructure.llm.llm_provider import openai_llm

DENY_PATTERN = re.compile(r"(?i)\b(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|INSERT\s+INTO)\b")
ACTIONS = {"chitchat", "clarify", "generate"}


def route_turn(question: str, session_frame: str = "", has_cached_result: bool = False) -> dict[str, Any]:
    q = (question or "").strip()
    if len(q) < 2:
        return _deny("Question too short.")
    if DENY_PATTERN.search(q):
        return _deny("Suspicious or mutating request.")
    return _llm_route(q, session_frame, has_cached_result)


def next_node(decision: dict[str, Any]) -> str:
    action = decision.get("turn_action") or "generate"
    if action == "deny":
        return "safe_response"
    if action == "chitchat":
        return "chitchat"
    if action == "clarify":
        return "hitl"
    return "generate"


def normalize_router_payload(parsed: dict[str, Any], question: str) -> dict[str, Any]:
    action = parsed.get("action") or "generate"
    if action not in ACTIONS:
        action = "generate"
    clarification = parsed.get("clarification_question")
    return {
        "turn_action": action,
        "question_to_user": clarification if action == "clarify" else None,
        "waiting_for_user": action == "clarify",
        "access_denied": False,
        "error": None,
        "error_type": None,
        "question": question,
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
        return normalize_router_payload({"action": "generate"}, question)


def _deny(reason: str) -> dict[str, Any]:
    return {
        "turn_action": "deny",
        "question_to_user": None,
        "waiting_for_user": False,
        "access_denied": True,
        "error": reason,
        "error_type": "guardrail_rejection",
    }
