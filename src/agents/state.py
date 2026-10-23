from typing import Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    session_id: Optional[str]
    question: str
    user_id: Optional[str]
    user_role: Optional[str]
    allowed_rep_codes: Optional[list[str]]

    messages: list
    memory_context: Optional[str]
    session_frame: Optional[str]

    turn_action: Optional[str]
    question_to_user: Optional[str]
    waiting_for_user: bool

    sql_query: Optional[str]
    sql_explanation: Optional[str]
    query_result: Optional[Any]
    execution_time_ms: Optional[float]
    plan: Optional[str]

    result_summary: Optional[str]
    table_title: Optional[str]
    visualizations: Optional[list]
    requested_chart_type: Optional[str]
    final_answer: Optional[str]

    error: Optional[str]
    error_type: Optional[str]
    iterations: int
    should_retry: bool
    start_time: Optional[float]
    total_latency_ms: Optional[float]
    cache_hit: Optional[bool]
    metrics: Optional[dict[str, Any]]

    user_message_id: Optional[str]
    user_message_saved: Optional[bool]
    assistant_message_id: Optional[str]
    assistant_message_saved: Optional[bool]
    sql_execution_saved: Optional[bool]
    access_denied: Optional[bool]
