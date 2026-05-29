"""
Legacy LangGraph workflow (pre-production architecture).
"""

from typing import Literal
from langgraph.graph import StateGraph, END
from loguru import logger
import time

import os
from langsmith import traceable

from .graph_state import AgentState
from .. import (
    planner_node,
    schema_linker_node,
    generator_node,
    executor_node,
    reflector_node,
    knowledge_gap_detector_node,
    clarification_node,
    conversation_router_node,
    result_formatter_node,
    knowledge_capture_node
)
from ..follow_up_detector import follow_up_detector_node
from ..result_transformer import transform_result_node

from .conditional_methods import (
    add_start_time,
    route_after_conversation_router,
    route_after_gap_detection,
    route_after_executor,
    route_after_follow_up_detection
    )
from .nodes import (
    memory_loader_node,
    clarification_resolver_node,
    new_question_reset_node, 
    save_memory_node,
    cache_result_node
)
from ...config import settings
from ...tools.chat_memory import chat_memory
from ...utils.langsmith_utils import setup_langsmith

setup_langsmith()


def build_graph() -> StateGraph:
    logger.info("Building legacy Text-to-SQL agent graph...")
    
    workflow = StateGraph(AgentState)
    
    workflow.add_node("init", add_start_time)
    workflow.add_node("memory_loader", memory_loader_node)
    workflow.add_node("conversation_router", conversation_router_node)
    workflow.add_node("clarification_resolver", clarification_resolver_node)
    workflow.add_node("new_question_reset", new_question_reset_node)
    workflow.add_node("gap_detector", knowledge_gap_detector_node)
    workflow.add_node("clarifier", clarification_node)
    workflow.add_node("knowledge_capture", knowledge_capture_node)
    workflow.add_node("follow_up_detector", follow_up_detector_node)
    workflow.add_node("transform_result", transform_result_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("schema_retriever", schema_linker_node)
    workflow.add_node("generator", generator_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("reflector", reflector_node)
    workflow.add_node("result_formatter", result_formatter_node)
    workflow.add_node("cache_result", cache_result_node)
    workflow.add_node("save_memory", save_memory_node)
    
    workflow.set_entry_point("init")
    workflow.add_edge("init", "memory_loader")
    workflow.add_edge("memory_loader", "conversation_router")
    
    workflow.add_conditional_edges(
        "conversation_router",
        route_after_conversation_router,
        {
            "gap_detector": "gap_detector",
            "clarification_resolver": "clarification_resolver",
            "new_question_reset": "new_question_reset"
        }
    )
    
    workflow.add_edge("new_question_reset", "gap_detector")
    workflow.add_edge("clarification_resolver", "gap_detector")

    workflow.add_conditional_edges(
        "gap_detector",
        route_after_gap_detection,
        {
            "clarify": "clarifier",
            "follow_up_detector": "follow_up_detector"
        }
    )
    
    workflow.add_edge("clarifier", "knowledge_capture")
    workflow.add_edge("knowledge_capture", "gap_detector")
    
    workflow.add_conditional_edges(
        "follow_up_detector",
        route_after_follow_up_detection,
        {
            "planner": "planner",
            "transform_result": "transform_result"
        }
    )
    
    workflow.add_edge("transform_result", "result_formatter")
    workflow.add_edge("planner", "schema_retriever")
    workflow.add_edge("schema_retriever", "generator")
    workflow.add_edge("generator", "executor")
    
    workflow.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "reflect": "reflector",
            "result_formatter": "result_formatter",
            "save_memory": "save_memory"
        }
    )
    
    workflow.add_edge("result_formatter", "cache_result")
    workflow.add_edge("cache_result", "save_memory")
    workflow.add_edge("reflector", "executor")
    workflow.add_edge("save_memory", END)
    
    logger.info("Legacy graph built successfully")
    return workflow

def compile_graph():
    workflow = build_graph()
    app = workflow.compile()
    logger.info("Legacy graph compiled and ready")
    return app

graph = compile_graph()


@traceable(
    name="sales-sql-agent",
    run_type="chain",
    tags=["text-to-sql", "openai"],
)
def run_agent(question: str) -> dict:
    logger.info(f"Running legacy Text-to-SQL Agent: {question}")
    
    initial_state: AgentState = {
        "question": question,
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
        "messages": [],
        "start_time": None,
        "cache_hit": False,
        "result_summary": None,
        "table_title": None,
        "visualizations": None,
    }
    
    try:
        final_state = graph.invoke(initial_state)
        if final_state.get("start_time"):
            total_time = (time.time() - final_state["start_time"]) * 1000
            final_state["total_latency_ms"] = total_time
        return final_state
    except Exception as e:
        logger.error(f"Graph execution error: {e}")
        return {**initial_state, "error": str(e), "should_retry": False}
