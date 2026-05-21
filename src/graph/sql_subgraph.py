from langgraph.graph import StateGraph, END, START
from ..agents import (
    planner_node,
    schema_linker_node,
    generator_node,
    executor_node,
    reflector_node
)
from .graph_state import SQLSubState

def route_after_executor(state: SQLSubState) -> str:
    """Decides if the pipeline needs self-correction loop or is done."""
    if state.get("error") and state.get("iterations", 0) < 3:
        return "reflect"
    return "complete"

def build_sql_subgraph():
    sub_workflow = StateGraph(SQLSubState)
    
    # Add Technical Workers
    sub_workflow.add_node("planner", planner_node)
    sub_workflow.add_node("schema_retriever", schema_linker_node)
    sub_workflow.add_node("generator", generator_node)
    sub_workflow.add_node("executor", executor_node)
    sub_workflow.add_node("reflector", reflector_node)
    
    # Bind Sequence Flow
    sub_workflow.add_edge(START, "planner")
    sub_workflow.add_edge("planner", "schema_retriever")
    sub_workflow.add_edge("schema_retriever", "generator")
    sub_workflow.add_edge("generator", "executor")
    
    # Conditional Repair Loop
    sub_workflow.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "reflect": "reflector",
            "complete": END
        }
    )
    sub_workflow.add_edge("reflector", "executor")
    
    return sub_workflow.compile()