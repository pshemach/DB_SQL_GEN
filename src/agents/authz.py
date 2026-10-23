"""Ingress authz: length, injection patterns, required RLS identity."""

from __future__ import annotations

import re
from typing import Any

DANGEROUS_PATTERNS = [
    r"(?i)(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE)",
    r"(?i)(UNION\s+SELECT|OR\s+1\s*=\s*1)",
]


def authz_node(state: dict[str, Any]) -> dict:
    question = (state.get("question") or "").strip()
    if len(question) > 2000:
        return _deny("Question exceeds maximum length.")
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, question):
            return _deny("Suspicious pattern detected in question.")
    if not (state.get("allowed_rep_codes") or []):
        return _deny("Access denied. No allowed rep codes were provided.")
    return {"access_denied": False}


def _deny(reason: str) -> dict:
    return {
        "turn_action": "deny",
        "access_denied": True,
        "access_denied_reason": reason,
        "error": reason,
        "error_type": "access_denied" if "Access denied" in reason else "guardrail_rejection",
        "final_answer": reason,
        "should_retry": False,
    }
