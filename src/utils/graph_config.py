"""LangGraph invoke/compile configuration helpers."""

from __future__ import annotations
from src.infrastructure.config import GRAPH_RECURSION_LIMIT

def build_invoke_config(session_id: str | None = None) -> dict:
    """
    Runtime config for graph.invoke / ainvoke.

    recursion_limit is set at invoke time (not compile) in current LangGraph versions.
    """
    config: dict = {"recursion_limit": GRAPH_RECURSION_LIMIT}
    if session_id:
        config["configurable"] = {"thread_id": session_id}
    return config
