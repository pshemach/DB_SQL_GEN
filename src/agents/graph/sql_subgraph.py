"""
Isolated SQL execution subgraph (DRGC core + production gates).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from loguru import logger

from .. import (
    executor_node,
    generator_node,
    planner_node,
    reflector_node,
)
from ...config import settings
from ...utils.error_taxonomy import is_retryable
from .graph_state import SQLSubState
from .sql_pipeline_nodes import (
    parallel_retrieval_node,
    pre_exec_critic_node,
    result_verifier_node,
    route_sql_subgraph_executor,
    security_policy_node,
    static_validator_node,
)

_sql_subgraph = None


def route_after_static_validator(state: SQLSubState) -> str:
    if state.get("error"):
        if is_retryable(state.get("error_type"), state.get("should_retry", True)):
            if state.get("iterations", 0) < settings.max_iterations:
                return "reflect"
        return "complete"
    return "pre_exec_critic" if settings.enable_pre_exec_critic else "executor"


def route_after_pre_exec(state: SQLSubState) -> str:
    if state.get("error"):
        if is_retryable(state.get("error_type"), state.get("should_retry", True)):
            if state.get("iterations", 0) < settings.max_iterations:
                return "reflect"
        return "complete"
    return "executor"


def build_sql_subgraph():
    """Build and compile the SQL pipeline subgraph."""
    workflow = StateGraph(SQLSubState)

    workflow.add_node("security_policy", security_policy_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("parallel_retrieval", parallel_retrieval_node)
    workflow.add_node("generator", generator_node)
    workflow.add_node("static_validator", static_validator_node)
    workflow.add_node("pre_exec_critic", pre_exec_critic_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("reflector", reflector_node)
    workflow.add_node("result_verifier", result_verifier_node)

    workflow.add_edge(START, "security_policy")

    workflow.add_conditional_edges(
        "security_policy",
        lambda s: "complete" if s.get("error") else "planner",
        {"planner": "planner", "complete": END},
    )

    workflow.add_edge("planner", "parallel_retrieval")
    workflow.add_edge("parallel_retrieval", "generator")
    workflow.add_edge("generator", "static_validator")

    workflow.add_conditional_edges(
        "static_validator",
        route_after_static_validator,
        {
            "pre_exec_critic": "pre_exec_critic",
            "executor": "executor",
            "reflect": "reflector",
            "complete": END,
        },
    )

    if settings.enable_pre_exec_critic:
        workflow.add_conditional_edges(
            "pre_exec_critic",
            route_after_pre_exec,
            {
                "executor": "executor",
                "reflect": "reflector",
                "complete": END,
            },
        )

    workflow.add_conditional_edges(
        "executor",
        route_sql_subgraph_executor,
        {
            "reflect": "reflector",
            "result_verifier": "result_verifier",
            "complete": END,
        },
    )

    workflow.add_edge("reflector", "executor")
    workflow.add_edge("result_verifier", END)

    return workflow.compile()


def get_sql_subgraph():
    global _sql_subgraph
    if _sql_subgraph is None:
        logger.info("Compiling SQL subgraph...")
        _sql_subgraph = build_sql_subgraph()
    return _sql_subgraph
