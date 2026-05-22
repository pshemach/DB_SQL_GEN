"""Routing functions for the production agent graph."""

from __future__ import annotations

from typing import Literal

from ..config import settings
from .graph_state import AgentState


def route_after_cache(state: AgentState) -> Literal["formatter", "authz"]:
    if state.get("cache_hit"):
        return "formatter"
    return "authz"


def route_after_authz(state: AgentState) -> Literal["safe_response", "turn_router"]:
    if state.get("access_denied") or state.get("turn_action") == "deny":
        return "safe_response"
    return "turn_router"


def route_after_turn_router(state: AgentState) -> Literal[
    "hitl_clarify", "transform_result", "sql_pipeline", "safe_response"
]:
    action = state.get("turn_action", "run_sql")

    if action == "clarify" and settings.enable_clarify:
        return "hitl_clarify"
    if action == "transform_previous" and settings.enable_transform_previous:
        return "transform_result"
    if action in ("deny", "chitchat"):
        return "safe_response"
    if action == "cache_hit":
        return "formatter"
    return "sql_pipeline"


def route_after_hitl(state: AgentState) -> Literal["turn_router", "sql_pipeline"]:
    """After clarification resume, re-route or run SQL directly."""
    if state.get("turn_action") == "run_sql" or state.get("enriched_question"):
        return "sql_pipeline"
    return "turn_router"
