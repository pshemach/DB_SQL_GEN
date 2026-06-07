"""FastAPI REST API for the Text-to-SQL agent."""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from langsmith import traceable

from ..agents.graph import run_agent_async
from ..agents.tools import seed_examples, semantic_cache, few_shot_retriever
from ..agents.tools.chat_memory import chat_memory
from ..core import db_manager
from ..config import settings
from ..guardrails.pipeline import guardrail_pipeline

from .data_models import (
    QueryRequest,
    QueryResponse,
    ExampleRequest,
    HealthResponse
)
from ..agents.tools.chatbot_auth_client import chatbot_auth_client
from ..agents.tools.access_context import (
    extract_allowed_rep_codes_from_phone_auth,
    extract_user_role_from_phone_auth,
    extract_user_id_from_phone_auth
    )

# =============================
# FASTAPI APP
# =============================

app = FastAPI(
    title="Text-to-SQL Agent API",
    description="REST API for the Text-to-SQL multi-agent system",
    version="1.0.0"
)


# =============================
# CORS
# =============================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================
# ROOT
# =============================

@app.get("/")
async def root():
    return {
        "name": "Text-to-SQL Agent API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# =============================
# HEALTH CHECK
# =============================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    try:
        tables = db_manager.get_all_table_names()

        return HealthResponse(
            status="healthy",
            database_connected=True,
            total_tables=len(tables),
            cache_enabled=settings.enable_semantic_cache,
            few_shot_enabled=settings.enable_dynamic_few_shot
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")

        return HealthResponse(
            status="unhealthy",
            database_connected=False,
            total_tables=0,
            cache_enabled=settings.enable_semantic_cache,
            few_shot_enabled=settings.enable_dynamic_few_shot
        )


# =============================
# MAIN QUERY ENDPOINT
# =============================

@traceable(name="text_to_sql_query", run_type="chain", tags=["api", "query-execution"])
@app.post("/query", response_model=QueryResponse)
async def query_database(request: QueryRequest):
    """
    Execute a natural language query against the database.

    Supports:
    - session-based conversation
    - clarification handling
    - knowledge gap detection
    - SQL generation
    - execution result
    - visualization config
    """

    logger.info(f"Query: {request.question}")
    logger.info(f"Session ID: {request.session_id}")

    try:
        auth_result = await chatbot_auth_client.authenticate_phone(request.phone_no)
        
        if not auth_result.get("success"):
            return auth_result
        
        auth_data = auth_result.get("data") or {}
        
        allowed_rep_codes = extract_allowed_rep_codes_from_phone_auth(auth_data)
        user_role = extract_user_role_from_phone_auth(auth_data)
        user_id = extract_user_id_from_phone_auth(auth_data)
        
        # === GUARDRAILS CHECK ===
        # Run pre-graph validation pipeline
        guardrail_context = {
            "conversation_history": [],
            "previous_topics": [],
            "user_role": user_role
        }
        
        # Get conversation context from chat memory if session exists
        if request.session_id:
            session = chat_memory.get_session(request.session_id)
            if session:
                guardrail_context["conversation_history"] = session.get("messages", [])
        
        # Evaluate guardrails
        guardrail_result = await guardrail_pipeline.evaluate(
            request.question,
            guardrail_context
        )
        
        # If guardrails reject, return early
        if not guardrail_result.get("passed", False):
            logger.warning(f"Query rejected by guardrails: {guardrail_result.get('reason')}")
            return QueryResponse(
                success=False,
                error=guardrail_result.get("reason", "Query rejected by safety checks"),
                error_type="guardrail_rejection",
                session_id=request.session_id,
                waiting_for_user=False
            )
        
        # === PROCEED TO AGENT GRAPH ===
        result = await run_agent_async(
            question=request.question,
            session_id=request.session_id,
            user_role=user_role,
            allowed_rep_codes=allowed_rep_codes,
            clarification_answer=request.clarification_answer,
            user_id=user_id
            
        )

        return QueryResponse(
            # status
            success=result.get("error") is None,
            error=result.get("error"),
            error_type=result.get("error_type"),

            # session / conversation
            session_id=result.get("session_id"),
            waiting_for_user=result.get("waiting_for_user", False),
            question_to_user=result.get("question_to_user"),

            # gap detection
            gap_type=result.get("gap_type"),
            gap_reason=result.get("gap_reason"),
            confidence=result.get("confidence"),
            missing_pieces=result.get("missing_pieces"),

            # planner
            plan=result.get("plan"),
            plan_steps=result.get("plan_steps"),

            # schema
            relevant_tables=result.get("relevant_tables"),
            relevant_columns=result.get("relevant_columns"),

            # SQL
            sql_query=result.get("sql_query"),
            sql_explanation=result.get("sql_explanation"),

            # execution result
            query_result=serialize_query_result(result.get("query_result")),
            result_preview=result.get("result_preview"),
            execution_time_ms=result.get("execution_time_ms"),

            # result interpretation / visualization
            result_summary=result.get("result_summary"),
            table_title=result.get("table_title"),
            # visualization_config=result.get("visualization_config"),
            
            visualizations=result.get("visualizations"),

            # runtime
            total_latency_ms=result.get("total_latency_ms"),
            iterations=result.get("iterations", 0),
            cache_hit=result.get("cache_hit", False),

            # optional debug
            messages=result.get("messages"),
            
            # chart_json=result.get("chart_json"),
            # chart_image_base64=result.get("chart_image_base64"),
        )

    except Exception as e:
        logger.error(f"Query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================
# QUERY RESULT SERIALIZER
# =============================

def serialize_query_result(query_result):
    """Delegates to shared serializer (handles DATE, Decimal, Row, etc.)."""
    from ..utils.serialization import serialize_query_result as _serialize

    try:
        return _serialize(query_result)
    except Exception as e:
        logger.warning(f"Failed to serialize query result: {e}")
        return None


# =============================
# DATABASE SCHEMA ENDPOINTS
# =============================

@app.get("/schema/tables")
async def get_tables():
    try:
        tables = db_manager.get_all_table_names()
        return {
            "tables": tables,
            "count": len(tables)
        }

    except Exception as e:
        logger.error(f"Error fetching tables: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/schema/table/{table_name}")
async def get_table_schema(table_name: str):
    try:
        metadata = db_manager.get_table_metadata(table_name)
        schema = db_manager.get_schema_for_tables([table_name])

        return {
            "table_name": table_name,
            "metadata": metadata,
            "schema": schema
        }

    except Exception as e:
        logger.error(f"Error fetching schema for {table_name}: {e}")
        raise HTTPException(
            status_code=404,
            detail=f"Table not found: {table_name}"
        )


# =============================
# FEW-SHOT EXAMPLE ENDPOINTS
# =============================

@app.post("/examples")
async def add_example(request: ExampleRequest):
    try:
        few_shot_retriever.add_example(
            question=request.question,
            sql=request.sql,
            explanation=request.explanation,
            complexity=request.complexity
        )

        return {
            "message": "Example added successfully"
        }

    except Exception as e:
        logger.error(f"Error adding example: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/examples/seed")
async def seed_default_examples(background_tasks: BackgroundTasks):
    try:
        background_tasks.add_task(seed_examples)

        return {
            "message": "Seeding examples in background"
        }

    except Exception as e:
        logger.error(f"Error seeding examples: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/examples/search")
async def search_examples(query: str, k: int = 3):
    try:
        examples = few_shot_retriever.retrieve(query, k=k)

        return {
            "examples": examples,
            "count": len(examples)
        }

    except Exception as e:
        logger.error(f"Error searching examples: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================
# CACHE ENDPOINTS
# =============================

@app.delete("/cache")
async def clear_cache():
    try:
        semantic_cache.clear()

        return {
            "message": "Cache cleared successfully"
        }

    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================
# STARTUP / SHUTDOWN
# =============================

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Text-to-SQL Agent API")
    logger.info(f"Database: {settings.database_uri}")
    logger.info(
        f"Semantic Cache: {'Enabled' if settings.enable_semantic_cache else 'Disabled'}"
    )
    logger.info(
        f"Few-Shot Learning: {'Enabled' if settings.enable_dynamic_few_shot else 'Disabled'}"
    )


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Text-to-SQL Agent API")
    db_manager.close()