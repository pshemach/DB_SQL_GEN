"""State that moves through the sales SQL graph.

Each field is read by a node, the API, or the web UI. Partial updates are
normal, so every field is optional.
"""

from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    # Who is asking
    session_id: Optional[str]
    user_id: Optional[str]
    user_role: Optional[str]
    question: str
    original_question: Optional[str]
    enriched_question: Optional[str]
    messages: List[Dict[str, Any]]
    memory_context: Optional[str]
    previous_state: Optional[Dict[str, Any]]

    # What this turn should do
    turn_action: Optional[str]
    waiting_for_user: bool
    question_to_user: Optional[str]
    metrics: Optional[Dict[str, Any]]

    # Row access
    allowed_rep_codes: Optional[List[str]]
    security_filter_sql: Optional[str]
    access_denied: Optional[bool]
    access_denied_reason: Optional[str]

    # SQL path
    plan: Optional[str]
    plan_steps: Optional[List[str]]
    relevant_tables: Optional[List[str]]
    schema_context: Optional[str]
    few_shot_examples: Optional[List[Dict[str, Any]]]
    sql_query: Optional[str]
    sql_explanation: Optional[str]
    query_result: Optional[Any]
    result_preview: Optional[Any]
    execution_time_ms: Optional[float]
    error: Optional[str]
    error_type: Optional[str]
    iterations: int
    should_retry: bool

    # Follow-up on the previous result
    needs_new_sql: Optional[bool]
    current_phase: Optional[str]
    formatter_mode: Optional[str]
    local_sql_query: Optional[str]

    # Answer shown to the user
    final_answer: Optional[str]
    result_summary: Optional[str]
    table_title: Optional[str]
    visualizations: Optional[List[Dict[str, Any]]]
    requested_chart_type: Optional[str]
    cache_hit: Optional[bool]

    # Saved once per turn
    user_message_id: Optional[str]
    user_message_saved: Optional[bool]
    assistant_message_id: Optional[str]
    assistant_message_saved: Optional[bool]
    sql_execution_saved: Optional[bool]
    start_time: Optional[float]
    total_latency_ms: Optional[float]
