"""Short-term conversation records stored for a sales chat session."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ConversationTurn:
    """One user or assistant message inside a session."""

    role: str
    content: str
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
