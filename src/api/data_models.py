"""Initiating Request/Response Models"""

from pydantic import BaseModel, Field
from typing import Optional, List

# Request/Response Models
class QueryRequest(BaseModel):
    question: str = Field(..., description="Natural language question")
    use_cache: bool = Field(default=True, description="Whether to use semantic cache")
    max_iterations: int = Field(default=3, description="Max correction attempts")
    session_id: Optional[str] = None

class QueryResponse(BaseModel):
    success: bool
    
    sql_query: Optional[str] = None
    result_preview: Optional[str] = None
    error: Optional[str] = None
    
    execution_time_ms: Optional[float] = None
    total_latency_ms: Optional[float] = None
    
    iterations: int = 0
    cache_hit: bool = False
    
    plan: Optional[str] = None
    relevant_tables: Optional[List[str]] = None
    
    session_id: Optional[str] = None
    waiting_for_user: bool = False
    question_to_user: Optional[str] = None

    gap_type: Optional[str] = None
    gap_reason: Optional[str] = None
    confidence: Optional[float] = None


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
