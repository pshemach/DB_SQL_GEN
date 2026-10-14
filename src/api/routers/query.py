"""Legacy single-shot query endpoint. Prefer /conversations for chat threads."""

from fastapi import APIRouter, HTTPException
from langsmith import traceable
from loguru import logger

from ...agents.tools.access_context import (
    extract_allowed_rep_codes_from_phone_auth,
    extract_user_id_from_phone_auth,
    extract_user_role_from_phone_auth,
)
from ...agents.tools.chat_memory import chat_memory
from ...agents.tools.chatbot_auth_client import chatbot_auth_client
from ..data_models import QueryRequest, QueryResponse
from ..services.conversation import execute_turn

router = APIRouter(tags=["query"])


@traceable(name="text_to_sql_query", run_type="chain", tags=["api", "query-execution"])
@router.post("/query", response_model=QueryResponse)
async def query_database(request: QueryRequest):
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

        session = chat_memory.get_session(request.session_id) if request.session_id else {}
        turn_type = "follow_up" if session and session.get("messages") else "start"

        result = await execute_turn(
            question=request.question,
            session_id=request.session_id,
            user_id=user_id,
            user_role=user_role,
            allowed_rep_codes=allowed_rep_codes,
            turn_type=turn_type,
            clarification_answer=request.clarification_answer,
        )

        return QueryResponse(
            success=result.get("success", False),
            error=result.get("error"),
            error_type=result.get("error_type"),
            session_id=result.get("session_id"),
            waiting_for_user=result.get("waiting_for_user", False),
            question_to_user=result.get("question_to_user"),
            plan=result.get("plan"),
            sql_query=result.get("sql_query"),
            query_result=result.get("query_result"),
            result_summary=result.get("result_summary"),
            table_title=result.get("table_title"),
            visualizations=result.get("visualizations"),
            requested_chart_type=result.get("requested_chart_type"),
        )
    except Exception as e:
        logger.error(f"Query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
