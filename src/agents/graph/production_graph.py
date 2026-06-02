"""
Production-grade Text-to-SQL LangGraph workflow.

Architecture: Thin Orchestrator (Single-node dialog management) + Isolated SQL Subgraph + Ingress/Egress Gates.
"""

from __future__ import annotations

import time
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from loguru import logger
from langsmith import traceable

from ...config import settings
from ...utils.langsmith_utils import setup_langsmith
from ...utils.metrics import finalize_metrics, init_metrics
from ...utils.graph_config import build_invoke_config
from .graph_state import AgentState
from .nodes import (
    authz_guardrails_node,
    memory_loader_node,
    safe_response_node,
    semantic_cache_lookup_node,
    hitl_clarify_node,
    cache_result_node, 
    save_memory_node,
    formatter_node
)
from .production_conditional import (
    route_after_authz,
    route_after_cache,
    route_after_transform,
    add_start_time,
    route_after_turn_router
)
from ...utils.serialization import sanitize_state
from .sql_subgraph import get_sql_subgraph

setup_langsmith()


def sql_pipeline_node(state: AgentState) -> dict:
    """Invoke compiled SQL subgraph with parent/sub state mapping."""
    from .sql_pipeline_nodes import _parent_to_sub, _sub_to_parent
    subgraph = get_sql_subgraph()
    sub_in = _parent_to_sub(state)
    sub_out = subgraph.invoke(sub_in)
    merged = _sub_to_parent(sub_out)
    return sanitize_state(merged) if merged else {}


def build_production_graph() -> StateGraph:
    logger.info("Building production Text-to-SQL graph with Unified Turn Orchestration...")
    
    from ..agent.turn_router import turn_router_node
    from ..agent.result_transformer import transform_result_node

    workflow = StateGraph(AgentState)

    # Ingress (No-LLM security and caching)
    workflow.add_node("init", add_start_time)
    workflow.add_node("memory_loader", memory_loader_node)
    workflow.add_node("semantic_cache", semantic_cache_lookup_node)
    workflow.add_node("authz", authz_guardrails_node)

    # The Single Unified Orchestration Node (routing + inline HITL + knowledge capture)
    workflow.add_node("turn_router", turn_router_node)
    workflow.add_node("transform_result", transform_result_node)
    workflow.add_node("safe_response", safe_response_node)
    
    # Clarification for user
    workflow.add_node("hitl_clarify", hitl_clarify_node)

    # SQL Subgraph
    workflow.add_node("sql_pipeline", sql_pipeline_node)

    # Egress
    workflow.add_node("formatter", formatter_node)
    workflow.add_node("cache_result", cache_result_node)
    workflow.add_node("save_memory", save_memory_node)

    # Graph Edges Wiring
    workflow.set_entry_point("init")
    workflow.add_edge("init", "memory_loader")
    workflow.add_edge("memory_loader", "semantic_cache")

    workflow.add_conditional_edges(
        "semantic_cache",
        route_after_cache,
        {"formatter": "formatter", "authz": "authz"},
    )

    workflow.add_conditional_edges(
        "authz",
        route_after_authz,
        {"safe_response": "safe_response", "turn_router": "turn_router"},
    )

    workflow.add_conditional_edges(
        "turn_router",
        route_after_turn_router,
        {
            "hitl_clarify":"hitl_clarify",
            "transform_result": "transform_result",
            "sql_pipeline": "sql_pipeline",
            "safe_response": "safe_response",
            "formatter": "formatter",
        },
    )

    workflow.add_conditional_edges(
        "transform_result",
        route_after_transform,
        {"formatter": "formatter", "sql_pipeline": "sql_pipeline"},
    )
    
    workflow.add_edge("sql_pipeline", "formatter")
    workflow.add_edge("safe_response", "save_memory")
    workflow.add_edge("formatter", "cache_result")
    workflow.add_edge("cache_result", "save_memory")
    workflow.add_edge("save_memory", END)
    
    workflow.add_edge("hitl_clarify", "save_memory")

    logger.info("Production graph compiled successfully")
    return workflow


# In-memory session saver (use PostgresSaver in server environment)
_checkpointer = MemorySaver()


def compile_production_graph():
    workflow = build_production_graph()
    return workflow.compile(
        # checkpointer=_checkpointer
        )


# Global compiled graph instance
graph = compile_production_graph()


@traceable(
    name="sales-sql-agent-production",
    run_type="chain",
    tags=["text-to-sql", "production"],
)
def run_agent(question: str, **kwargs) -> dict:
    """Synchronous entry point for production graph."""
    from ..tools.chat_memory import chat_memory

    session_id = chat_memory.get_or_create_session(kwargs.get("session_id"))
    initial_state = _build_initial_state(question, session_id, kwargs)

    try:
        config = build_invoke_config(session_id)
        final_state = graph.invoke(initial_state, config)
        return _finalize_state(final_state)
    except Exception as e:
        logger.error(f"Production graph error: {e}")
        return {**initial_state, "error": str(e), "should_retry": False}


def _build_initial_state(question: str, session_id: str, kwargs: dict) -> AgentState:
    return {
        "session_id": session_id,
        "question": question,
        "original_question": question,
        "allowed_rep_codes": kwargs.get("allowed_rep_codes") or [],
        "user_role": kwargs.get("user_role"),
        "security_filter_sql": None,
        "access_denied": False,
        "access_denied_reason": None,
        "previous_state": None,
        "messages": [],
        "memory_context": "",
        "conversation_route": None,
        "turn_action": None,
        "router_confidence": None,
        "enriched_question": None,
        "follow_up_type": None,
        "is_follow_up": False,
        "can_reuse_cached_result": False,
        "cached_result_id": None,
        "required_transformations": [],
        "metrics": init_metrics(),
        "needs_clarification": False,
        "gap_type": None,
        "gap_reason": None,
        "confidence": None,
        "missing_pieces": [],
        "question_to_user": None,
        "waiting_for_user": False,
        "pending_original_question": None,
        "clarification_answer": kwargs.get("clarification_answer"),
        "business_definitions": "",
        "matched_knowledge": [],
        "plan": None,
        "plan_steps": None,
        "relevant_tables": None,
        "schema_context": None,
        "schema_metadata": None,
        "sql_query": None,
        "sql_explanation": None,
        "few_shot_examples": None,
        "query_result": None,
        "result_preview": None,
        "execution_time_ms": None,
        "error": None,
        "error_type": None,
        "iterations": 0,
        "should_retry": True,
        "start_time": time.time(),
        "cache_hit": False,
        "final_answer": None,
        "user_message_id": None,
        "user_message_saved": False,
        "assistant_message_id": None,
        "assistant_message_saved": False,
        "user_id": kwargs.get("user_id"),
        "sql_execution_saved": False,
    }


def _finalize_state(final_state: dict) -> dict:
    if final_state.get("start_time"):
        total = (time.time() - final_state["start_time"]) * 1000
        final_state["total_latency_ms"] = total
        final_state["metrics"] = finalize_metrics(
            final_state.get("metrics"), total_latency_ms=total
        )
    if final_state.get("error"):
        logger.error(f"Agent failed: {final_state['error']}")
    else:
        logger.info("Agent succeeded")
    return final_state
