"""Recall and save helpers over the short-term session store."""

from __future__ import annotations

from src.memory.st_store import chat_memory


class MemoryRecaller:
    """Read recent turns and the text block injected into the SQL agents."""

    def recall(self, session_id: str) -> str:
        return chat_memory.build_memory_context(session_id)

    def last_state(self, session_id: str) -> dict:
        return chat_memory.get_last_state(session_id) or {}


class MemoryWriter:
    """Persist a turn and the latest agent state for the next follow-up."""

    def add_message(self, session_id: str, role: str, content: str, **kwargs):
        return chat_memory.add_message(session_id, role, content, **kwargs)

    def save_state(self, session_id: str, state: dict) -> None:
        chat_memory.set_last_state(session_id, state)


recaller = MemoryRecaller()
writer = MemoryWriter()
