"""
Core state management for the Text-to-SQL agent.
Defines the AgentState that flows through the LangGraph workflow.
"""

from typing import TypedDict, Annotated, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage
import operator


class AgentState(TypedDict):
    """
    State object that flows through the agent graph.
    Maintains all context needed for the DRGC (Decomposition-Retrieval-Generation-Correction) pipeline.
    """
    
    # Input
    question: str  # Original user question
    
    # Planning Phase
    plan: Optional[str]  # Logical plan from Decomposer
    plan_steps: Optional[List[str]]  # Individual steps from plan
    
    # Schema Retrieval Phase
    relevant_tables: Optional[List[str]]  # Selected table names
    schema_context: Optional[str]  # DDL/Schema info for relevant tables
    schema_metadata: Optional[Dict[str, Any]]  # Additional metadata
    
    # Generation Phase
    sql_query: Optional[str]  # Generated SQL
    sql_explanation: Optional[str]  # Chain-of-thought explanation
    few_shot_examples: Optional[List[Dict[str, str]]]  # Retrieved examples
    
    # Execution Phase
    query_result: Optional[Any]  # Execution result
    result_preview: Optional[str]  # First few rows as string
    execution_time_ms: Optional[float]  # Query performance metric
    
    # Error Handling
    error: Optional[str]  # Error message if execution failed
    error_type: Optional[str]  # Type of error (syntax, runtime, logic)
    
    # Control Flow
    iterations: int  # Number of correction attempts
    should_retry: bool  # Whether to attempt correction
    
    # Conversation History
    messages: Annotated[List[BaseMessage], operator.add]
    
    # Metadata
    start_time: Optional[float]  # For latency tracking
    cache_hit: Optional[bool]  # Whether result came from cache