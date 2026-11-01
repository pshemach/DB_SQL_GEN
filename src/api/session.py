"""Session ID rules for starting conversations."""

from __future__ import annotations

from typing import Optional
from uuid import uuid4


def resolve_start_session_id(
    request_session_id: Optional[str],
    *,
    current_session_id: Optional[str] = None,
    new_conversation: bool = False,
) -> str:
    """Choose a session for a start request.

    New chats never reuse the auth-token session. That fallback was
    loading the previous chat's memory after New Chat was clicked.
    """
    requested = (request_session_id or "").strip() or None
    current = (current_session_id or "").strip() or None
    if new_conversation:
        if requested and requested != current:
            return requested
        return str(uuid4())
    return requested or str(uuid4())
