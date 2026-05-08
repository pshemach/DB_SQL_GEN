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

def route_after_gap_detection(state: AgentState) -> Literal["clarify", "planner"]:
    if state.get("needs_clarification"):
        return "clarify"
    return "planner"

