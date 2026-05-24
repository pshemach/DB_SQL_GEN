"""SQL error taxonomy for production retry routing."""

from __future__ import annotations

RETRYABLE_ERRORS = frozenset({
    "syntax",
    "syntax_error",
    "column_not_found",
    "table_not_found",
    "ambiguous_column",
    "runtime",
    "runtime_error",
})

NON_RETRYABLE_ERRORS = frozenset({
    "permission",
    "access_denied",
    "timeout",
    "guardrail_rejection",
    "validation",
})


def classify_db_error(error_msg: str) -> str:
    """Map database error text to a normalized error_type."""
    error_lower = (error_msg or "").lower()

    if "column" in error_lower and ("does not exist" in error_lower or "not found" in error_lower):
        return "column_not_found"
    if "table" in error_lower and ("does not exist" in error_lower or "not found" in error_lower):
        return "table_not_found"
    if "syntax" in error_lower:
        return "syntax_error"
    if "ambiguous" in error_lower:
        return "ambiguous_column"
    if "timeout" in error_lower or "timed out" in error_lower:
        return "timeout"
    if "permission" in error_lower or "denied" in error_lower:
        return "permission"
    return "runtime_error"


def is_retryable(error_type: str | None, should_retry: bool = True) -> bool:
    if not should_retry:
        return False
    if not error_type:
        return False
    if error_type in NON_RETRYABLE_ERRORS:
        return False
    return error_type in RETRYABLE_ERRORS or error_type.startswith("syntax")