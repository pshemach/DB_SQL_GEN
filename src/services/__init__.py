"""Service helpers.

Submodules are imported directly. Eager imports here pull the conversation
layer, which imports the agent graph, and that cycles when a graph tool
imports ``src.services.analytics``.
"""

from __future__ import annotations

__all__ = ["execute_turn", "stream_turn"]


def __getattr__(name: str):
    if name in {"execute_turn", "stream_turn"}:
        from src.services.conversation import execute_turn, stream_turn

        return {"execute_turn": execute_turn, "stream_turn": stream_turn}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
