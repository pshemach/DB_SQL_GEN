# """Initiating Request/Response Models"""

# from pydantic import BaseModel, Field
# from typing import Optional, List

# # Request/Response Models
# class QueryRequest(BaseModel):
#     question: str = Field(..., description="Natural language question")
#     use_cache: bool = Field(default=True, description="Whether to use semantic cache")
#     max_iterations: int = Field(default=3, description="Max correction attempts")
#     session_id: Optional[str] = None

# class QueryResponse(BaseModel):
#     success: bool
    
#     sql_query: Optional[str] = None
#     result_preview: Optional[str] = None
#     error: Optional[str] = None
    
#     execution_time_ms: Optional[float] = None
#     total_latency_ms: Optional[float] = None
    
#     iterations: int = 0
#     cache_hit: bool = False
    
#     plan: Optional[str] = None
#     relevant_tables: Optional[List[str]] = None
    
#     session_id: Optional[str] = None
#     waiting_for_user: bool = False
#     question_to_user: Optional[str] = None

#     gap_type: Optional[str] = None
#     gap_reason: Optional[str] = None
#     confidence: Optional[float] = None


# class ExampleRequest(BaseModel):
#     question: str
#     sql: str
#     explanation: Optional[str] = None
#     complexity: str = Field(default="medium", pattern="^(simple|medium|complex)$")


# class HealthResponse(BaseModel):
#     status: str
#     database_connected: bool
#     total_tables: int
#     cache_enabled: bool
#     few_shot_enabled: bool

"""Initiating Request/Response Models"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class QueryRequest(BaseModel):
    question: str = Field(..., description="Natural language question")
    session_id: Optional[str] = Field(default=None, description="Conversation/session ID")
    
    # allowed_rep_codes: Optional[List[str]] = Field(
    #     default=None,
    #     description="RepCodes this user is allowed to access"
    # )

    # user_role: Optional[str] = Field(
    #     default=None,
    #     description="rep | asm | rsm | customer"
    # )
    phone_no: Optional[str] = Field(
        default="94718543880",
        description="RepCodes this user is allowed to access"
    )

    use_cache: bool = Field(default=True, description="Whether to use semantic cache")
    max_iterations: int = Field(default=2, description="Max correction attempts")
    clarification_answer: Optional[str] = Field(
        default=None,
        description="User answer when resuming from a clarification interrupt (HITL)",
    )


class QueryResponse(BaseModel):
    # =============================
    # STATUS
    # =============================
    success: bool
    error: Optional[str] = None
    error_type: Optional[str] = None

    # =============================
    # SESSION / CONVERSATION
    # =============================
    session_id: Optional[str] = None
    waiting_for_user: bool = False
    question_to_user: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None

    # =============================
    # GAP DETECTION / CLARIFICATION
    # =============================
    gap_type: Optional[str] = None
    gap_reason: Optional[str] = None
    confidence: Optional[float] = None
    missing_pieces: Optional[List[str]] = None

    # =============================
    # PLANNER
    # =============================
    plan: Optional[str] = None
    plan_steps: Optional[List[str]] = None

    # =============================
    # SCHEMA LINKER
    # =============================
    relevant_tables: Optional[List[str]] = None
    relevant_columns: Optional[Dict[str, List[str]]] = None

    # =============================
    # SQL GENERATOR
    # =============================
    sql_query: Optional[str] = None
    sql_explanation: Optional[str] = None

    # =============================
    # EXECUTION RESULT
    # =============================
    query_result: Optional[Any] = None
    result_preview: Optional[Any] = None
    execution_time_ms: Optional[float] = None

    # =============================
    # RESULT FORMATTER / VISUALIZATION
    # =============================
    result_summary: Optional[str] = None
    table_title: Optional[str] = None
    # visualization_config: Optional[Dict[str, Any]] = None

    # =============================
    # RUNTIME
    # =============================
    total_latency_ms: Optional[float] = None
    iterations: int = 0
    cache_hit: bool = False
    
    # chart_json: Optional[Dict[str, Any]] = None
    # chart_image_base64: Optional[str] = None
    
    visualizations: Optional[List[Dict[str, Any]]] = None


class ExampleRequest(BaseModel):
    question: str
    sql: str
    explanation: Optional[str] = None
    complexity: str = Field(default="medium", pattern="^(simple|medium|complex)$")


class HealthResponse(BaseModel):
    status: str
    database_connected: bool
    total_tables: int
    cache_enabled: bool
    few_shot_enabled: bool