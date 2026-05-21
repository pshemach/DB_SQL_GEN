import time 
from loguru import logger
from typing import Literal
from ..config import settings
from .graph_state import AgentState
from ..tools import semantic_cache, chat_memory


def add_start_time(state: AgentState) -> dict:
    """Add timestamp at start of workflow."""
    return {"start_time": time.time()}


def should_continue(state: AgentState) -> Literal["reflect", "end", "cache_success"]:
    """
    Determines the next step in the workflow after query execution.
    
    Decision flow:
    - If query succeeded: cache result and end
    - If max iterations reached: end with error
    - If self-correction disabled: end with error
    - Otherwise: attempt to fix the error
    
    Args:
        state: Current agent state
        
    Returns:
        Next node name: "cache_success", "end", or "reflect"
    """
    # If there's no error, cache and end
    if state.get("error") is None:
        logger.info("✓ Query successful - caching and ending workflow")
        return "cache_success"
    
    # If max iterations reached, stop
    if state.get("iterations", 0) >= settings.max_iterations:
        logger.warning(f"✗ Max iterations ({settings.max_iterations}) reached - ending workflow")
        return "end"
    
    # If self-correction is disabled, stop
    if not settings.enable_self_correction:
        logger.warning("✗ Self-correction disabled - ending workflow")
        return "end"
    
    # If should_retry flag is False, stop
    if not state.get("should_retry", True):
        logger.warning("✗ Retry flag is False - ending workflow")
        return "end"
    
    # Otherwise, attempt reflection/correction
    logger.info(f"↻ Attempting correction (iteration {state.get('iterations', 0) + 1})")
    return "reflect"


def route_after_conversation_router(state: dict) -> Literal[
    "gap_detector",
    "clarification_resolver",
    "new_question_reset"
]:
    route = state.get("conversation_route")

    if route == "clarification_answer":
        return "clarification_resolver"

    if route == "new_question":
        return "new_question_reset"

    return "gap_detector"

def route_after_gap_detection(state: AgentState) -> Literal["clarify", "follow_up_detector"]:
    """
    Route after knowledge gap detection.
    
    - If clarification needed: ask user
    - Otherwise: proceed to follow-up detection
    """
    if state.get("needs_clarification"):
        return "clarify"
    return "follow_up_detector"

def route_after_executor(state: AgentState) -> Literal["reflect", "result_formatter", "save_memory"]:
    # Success
    if state.get("error") is None:
        return "result_formatter"

    # If executor says not retryable
    if not state.get("should_retry", True):
        logger.warning("SQL error is not retryable. Stopping workflow.")
        return "save_memory"

    # Stop if max iterations reached
    if state.get("iterations", 0) >= settings.max_iterations:
        logger.warning(f"✗ Max iterations ({settings.max_iterations}) reached → save_memory")
        return "save_memory"

    logger.info(f"↻ Reflecting on error (iteration {state.get('iterations', 0) + 1}/{settings.max_iterations})")
    return "reflect"


def route_after_follow_up_detection(state: AgentState) -> Literal["planner", "transform_result"]:
    """
    Route based on follow-up type detection.
    
    - new_query: Run full planner → schema_retriever → generator → executor flow
    - filter/transform: Apply in-memory transformation to cached result
    - refinement/clarification: Treat as new query and run planner
    """
    follow_up_type = state.get("follow_up_type", "new_query")
    
    if follow_up_type in ["filter", "transform"]:
        logger.info(f"→ Follow-up detected: {follow_up_type}, applying cached result transformation")
        return "transform_result"
    else:
        logger.info(f"→ New query or refinement, running full planning flow ({follow_up_type})")
        return "planner"