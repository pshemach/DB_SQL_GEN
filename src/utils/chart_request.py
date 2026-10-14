import re

# Longer phrases first. "chat" is accepted as a typo for "chart".
_REQUESTED_CHART_PATTERNS = (
    (r"horizontal\s+bar", "horizontal_bar"),
    (r"\bbar\s+(chart|graph|chat|plot)s?\b", "bar"),
    (r"\bbarchart\b", "bar"),
    (r"\b(line|trend)\s+(chart|graph|chat|plot)s?\b", "line"),
    (r"\bpie\s+(chart|graph|chat|plot)s?\b", "pie"),
    (r"\bscatter(?:\s+(?:plot|chart|graph|chat))?s?\b", "scatter"),
    (r"\bas\s+an?\s+bar\b", "bar"),
    (r"\bas\s+an?\s+line\b", "line"),
    (r"\bas\s+an?\s+pie\b", "pie"),
)


def detect_requested_chart_type(question: str) -> str | None:
    """Return a chart type when the user explicitly asks for one."""
    q = (question or "").lower()
    for pattern, chart_type in _REQUESTED_CHART_PATTERNS:
        if re.search(pattern, q):
            return chart_type
    return None
