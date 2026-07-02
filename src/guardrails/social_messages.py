"""Detect greetings and other non-analytics messages handled by the agent."""

from __future__ import annotations

import re

# Short social messages → pass guardrails; turn_router responds with chitchat
_SOCIAL_PATTERN = re.compile(
    r"^(?:"
    r"hi|hello|hellow|hey|hiya|howdy|greetings|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"thanks|thank\s+you|thx|bye|goodbye|see\s+you|"
    r"ok|okay|yes|no|yo|sup|what'?s\s+up"
    r")(?:[!.,?\s]|$)",
    re.IGNORECASE,
)


def is_social_message(question: str) -> bool:
    """True for greetings / small talk that should not hit analytics guardrails."""
    q = (question or "").strip()
    if not q:
        return False
    if _SOCIAL_PATTERN.match(q):
        return True
    # Very short tokens that are clearly greetings
    if len(q) <= 3 and q.lower() in {"hi", "hey", "yo", "ok", "sup", "bye"}:
        return True
    return False
