"""
Single scope guardrail for the sales analytics assistant.

Checks, in order: empty or oversized input, prompt/SQL injection,
request rate, greetings (allowed through), then an LLM domain check.
Out-of-scope questions are refused. Classifier errors fail open.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Literal

from loguru import logger

from src.infrastructure.llm import get_router_llm
from src.agents.prompts.agent_prompts import build_domain_classifier_prompt, chat_messages

GuardrailVerdict = Literal["in_scope", "out_of_scope"]

_SOCIAL_PATTERN = re.compile(
    r"^(?:"
    r"hi|hello|hellow|hey|hiya|howdy|greetings|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"thanks|thank\s+you|thx|bye|goodbye|see\s+you|"
    r"ok|okay|yes|no|yo|sup|what'?s\s+up"
    r")(?:[!.,?\s]|$)",
    re.IGNORECASE,
)

_INJECTION_PATTERNS = (
    r"(?i)(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE)",
    r"(?i)(UNION\s+SELECT|OR\s+1\s*=\s*1)",
    r"(?i)(--\s*$|;\s*DROP)",
    r"(?i)({.*exec.*}|<script|javascript:)",
)

_MAX_LENGTH = 2000
_MIN_LENGTH = 2
_RATE_LIMIT = 100
_RATE_WINDOW_SECONDS = 60


def is_social_message(question: str) -> bool:
    """True for greetings and other short non-analytics messages."""
    text = (question or "").strip()
    if not text:
        return False
    if _SOCIAL_PATTERN.match(text):
        return True
    return len(text) <= 3 and text.lower() in {"hi", "hey", "yo", "ok", "sup", "bye"}


class Guardrail:
    """Input and domain filter used before the orchestrator runs."""

    def __init__(self, llm: Any = None) -> None:
        self.llm = llm or get_router_llm()
        self._requests: dict[str, list[datetime]] = {}

    async def evaluate(self, question: str, context: dict | None = None) -> dict:
        """Return ``{"passed": bool, "reason": str}`` for the API layer."""
        context = context or {}
        text = question or ""
        stripped = text.strip()

        if is_social_message(stripped):
            return {"passed": True, "reason": "Social message"}

        if not stripped or len(stripped) < _MIN_LENGTH:
            return {"passed": False, "reason": "Please enter a valid question (3-2000 characters)"}
        if len(text) > _MAX_LENGTH:
            return {"passed": False, "reason": "Please enter a valid question (3-2000 characters)"}

        for pattern in _INJECTION_PATTERNS:
            if re.search(pattern, text):
                logger.warning(f"Injection pattern detected: {pattern}")
                return {
                    "passed": False,
                    "reason": "Your question contains suspicious patterns. Please rephrase.",
                }

        session_id = context.get("session_id", "anonymous")
        if not self._within_rate_limit(session_id):
            return {"passed": False, "reason": "You're sending requests too quickly. Please wait a moment."}

        verdict, reason = self._classify(stripped, context)
        if verdict == "out_of_scope":
            return {
                "passed": False,
                "reason": reason
                or "This question appears to be outside the scope of sales analytics. Please ask about sales metrics, KPIs, or rep performance.",
            }
        return {"passed": True, "reason": reason or "In scope"}

    def _within_rate_limit(self, session_id: str) -> bool:
        cutoff = datetime.now() - timedelta(seconds=_RATE_WINDOW_SECONDS)
        recent = [stamp for stamp in self._requests.get(session_id, []) if stamp > cutoff]
        if len(recent) >= _RATE_LIMIT:
            logger.warning(f"Rate limit exceeded for session {session_id}")
            return False
        recent.append(datetime.now())
        self._requests[session_id] = recent
        return True

    def _classify(self, question: str, context: dict) -> tuple[GuardrailVerdict, str]:
        history = context.get("conversation_history") or []
        try:
            system_prompt, user_prompt = build_domain_classifier_prompt(
                question,
                ", ".join(_topics(history)[-5:]) or "None",
                _summarize(history),
                context.get("user_role", "analyst"),
            )
            response = self.llm.invoke(chat_messages(system_prompt, user_prompt))
        except Exception as exc:
            logger.warning("Guardrail LLM error (failing open): {}", exc)
            return "in_scope", "Classifier error (fail-open)"

        raw = response.content if hasattr(response, "content") else str(response)
        parsed = _extract_json(raw)
        if not parsed:
            return "in_scope", "Classifier parsing failed (fail-open)"

        in_scope = parsed.get("classification", "IN_SCOPE") == "IN_SCOPE"
        confidence = float(parsed.get("confidence", 0.0))
        reason = parsed.get("reason", "Classification complete")
        if not in_scope and confidence > 0.7:
            logger.info(f"Rejected out-of-scope question (confidence: {confidence})")
            return "out_of_scope", reason
        return "in_scope", reason


def _summarize(history: list, max_chars: int = 800) -> str:
    if not history:
        return "No previous conversation"
    lines = []
    for message in history[-6:]:
        text = _message_text(message)
        if text:
            lines.append(f"{_message_role(message)}: {text[:180]}")
    summary = "; ".join(lines)
    return (summary[:max_chars] if summary else "No previous conversation")


def _topics(history: list) -> list[str]:
    topics = []
    for message in history[-10:]:
        if isinstance(message, dict) and message.get("role") not in (None, "user"):
            continue
        text = _message_text(message)
        if text:
            topics.append(text[:120])
    return topics


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        return (message.get("content") or message.get("question") or "").strip()
    return str(message).strip()


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return (message.get("role") or "user").strip()
    return "user"


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            return None
    return None
