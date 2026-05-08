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
    session_id: Optional[str]
    question: str  # Original user question
    original_question: Optional[str]
    
    # Conversation memory
    messages: List[Dict[str, Any]]
    memory_context: Optional[str]
    
    # conversation routing
    conversation_route: Optional[str]  
    # normal_question | clarification_answer | new_question
    
    # previous waiting state
    previous_state: Optional[Dict[str, Any]]
    waiting_for_user: bool
    
    # Gap detection
    needs_clarification: bool
    gap_type: Optional[str]  # knowledge_gap | parameter_gap | none
    gap_reason: Optional[str]
    confidence: Optional[float]
    missing_pieces: Optional[List[str]]

    # Clarification
    question_to_user: Optional[str]
    waiting_for_user: bool
    pending_original_question: Optional[str]
    clarification_answer: Optional[str]
    clarifications: Optional[List[Dict[str, Any]]]

    # Business knowledge
    business_definitions: Optional[str]
    matched_knowledge: Optional[List[Dict[str, Any]]]
    captured_business_rule: Optional[Dict[str, Any]]
    
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
    # messages: Annotated[List[BaseMessage], operator.add]
    
    final_answer: Optional[str]
    
    # Metadata
    start_time: Optional[float]  # For latency tracking
    total_latency_ms: Optional[float]
    cache_hit: Optional[bool]  # Whether result came from cache