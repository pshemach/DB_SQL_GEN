"""
Core state management for the Text-to-SQL agent.
Defines the AgentState that flows through the LangGraph workflow.
"""

from typing import TypedDict, List, Optional, Dict, Any


class AgentState(TypedDict):
    """
    State object that flows through the agent graph.
    Maintains all context needed for the Text-to-SQL pipeline.
    """

    # =============================
    # INPUT / SESSION
    # =============================
    session_id: Optional[str]
    question: str
    original_question: Optional[str]

    # =============================
    # CONVERSATION MEMORY
    # =============================
    messages: List[Dict[str, Any]]
    memory_context: Optional[str]

    # =============================
    # CONVERSATION ROUTING
    # =============================
    conversation_route: Optional[str]
    # normal_question | clarification_answer | new_question

    previous_state: Optional[Dict[str, Any]]
    waiting_for_user: bool

    # =============================
    # GAP DETECTION
    # =============================
    needs_clarification: bool
    gap_type: Optional[str]  # knowledge_gap | parameter_gap | none
    gap_reason: Optional[str]
    confidence: Optional[float]
    missing_pieces: Optional[List[str]]

    # =============================
    # CLARIFICATION
    # =============================
    question_to_user: Optional[str]
    pending_original_question: Optional[str]
    clarification_answer: Optional[str]
    clarifications: Optional[List[Dict[str, Any]]]

    # =============================
    # BUSINESS KNOWLEDGE
    # =============================
    business_definitions: Optional[str]
    matched_knowledge: Optional[List[Dict[str, Any]]]
    captured_business_rule: Optional[Dict[str, Any]]

    # =============================
    # PLANNING
    # =============================
    plan: Optional[str]
    plan_steps: Optional[List[str]]

    # =============================
    # SCHEMA RETRIEVAL
    # =============================
    relevant_tables: Optional[List[str]]
    relevant_columns: Optional[Dict[str, List[str]]]
    schema_context: Optional[str]
    schema_metadata: Optional[Dict[str, Any]]

    # =============================
    # SQL GENERATION
    # =============================
    sql_query: Optional[str]
    sql_explanation: Optional[str]
    few_shot_examples: Optional[List[Dict[str, Any]]]

    # =============================
    # EXECUTION
    # =============================
    query_result: Optional[Any]
    result_preview: Optional[Any]
    execution_time_ms: Optional[float]

    # =============================
    # RESULT FORMATTER / VISUALIZATION
    # =============================
    result_summary: Optional[str]
    table_title: Optional[str]
    # visualization_config: Optional[Dict[str, Any]]

    # # Plotly graph output
    # chart_json: Optional[Dict[str, Any]] = None
    # chart_image_base64: Optional[str]
    visualizations: Optional[List[Dict[str, Any]]]

    # =============================
    # ERROR HANDLING
    # =============================
    error: Optional[str]
    error_type: Optional[str]

    # =============================
    # CONTROL FLOW
    # =============================
    iterations: int
    should_retry: bool

    # =============================
    # FINAL OUTPUT
    # =============================
    final_answer: Optional[str]

    # =============================
    # METADATA
    # =============================
    start_time: Optional[float]
    total_latency_ms: Optional[float]
    cache_hit: Optional[bool]
    
    allowed_rep_codes: Optional[List[str]]
    user_role: Optional[str]
    security_filter_sql: Optional[str]
    access_denied: Optional[bool]
    access_denied_reason: Optional[str]
    
    
# # --- INNER SUB-GRAPH STATE ---
# class SQLSubState(TypedDict):
#     # Inputs passed from Parent
#     question: str
#     business_definitions: Optional[str]
    
#     # Working properties (Isolated from conversation history)
#     plan: Optional[str]
#     plan_steps: Optional[List[str]]
#     relevant_tables: Optional[List[str]]
#     schema_context: Optional[str]
#     sql_query: Optional[str]
#     error: Optional[str]
#     iterations: int
#     should_retry: bool
    
#     # Outputs to pass back to Parent
#     subgraph_output: Optional[dict]

# --- INNER SUB-GRAPH STATE ---
class SQLSubState(TypedDict, total=False):
    # Inputs passed from Parent
    question: str
    business_definitions: Optional[str]
    allowed_rep_codes: Optional[List[str]]
    security_filter_sql: Optional[str]
    few_shot_examples: Optional[List[Dict[str, Any]]]

    # Working properties (isolated from conversation history)
    plan: Optional[str]
    plan_steps: Optional[List[str]]
    relevant_tables: Optional[List[str]]
    relevant_columns: Optional[Dict[str, List[str]]]
    schema_context: Optional[str]
    schema_metadata: Optional[Dict[str, Any]]
    sql_query: Optional[str]
    sql_explanation: Optional[str]
    query_result: Optional[Any]
    result_preview: Optional[Any]
    execution_time_ms: Optional[float]
    error: Optional[str]
    error_type: Optional[str]
    iterations: int
    should_retry: bool
    pre_exec_approved: Optional[bool]

    # Outputs to pass back to Parent
    subgraph_output: Optional[dict]