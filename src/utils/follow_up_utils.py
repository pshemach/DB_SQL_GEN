"""Small helpers for follow-up turns on cached query results (no phrase lists)."""

from __future__ import annotations

import re
from typing import Optional

_ORDINAL_WORDS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "sixth": 6,
    "6th": 6,
    "seventh": 7,
    "7th": 7,
    "eighth": 8,
    "8th": 8,
    "ninth": 9,
    "9th": 9,
    "tenth": 10,
    "10th": 10,
    "last": -1,
    "bottom": -1,
}


def extract_rank_from_question(question: str) -> Optional[int]:
    """
    Extract 1-based rank when the user asks for a specific position in a list.
    Returns -1 for 'last' / 'bottom'.
    """
    q = (question or "").lower()
    m = re.search(r"#\s*(\d+)", q)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)(?:st|nd|rd|th)\b", q)
    if m:
        return int(m.group(1))
    for word, rank in _ORDINAL_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", q):
            return rank
    return None


def extract_limit_from_question(question: str) -> Optional[int]:
    """Extract a row limit from phrases like 'top 5' or 'limit 3'."""
    q = (question or "").lower()
    m = re.search(r"\btop\s+(\d+)\b", q)
    if m:
        return int(m.group(1))
    m = re.search(r"\blimit\s+(\d+)\b", q)
    if m:
        return int(m.group(1))
    m = re.search(r"\bfirst\s+(\d+)\b", q)
    if m:
        return int(m.group(1))
    return None
