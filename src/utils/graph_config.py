"""LangGraph invoke/compile configuration helpers."""

from __future__ import annotations

from ..config import settings


def build_invoke_config(session_id: str | None = None) -> dict:
    """
    Runtime config for graph.invoke / ainvoke.

    recursion_limit is set at invoke time (not compile) in current LangGraph versions.
    """
    config: dict = {"recursion_limit": settings.graph_recursion_limit}
    if session_id:
        config["configurable"] = {"thread_id": session_id}
    return config
