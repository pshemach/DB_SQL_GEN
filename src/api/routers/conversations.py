from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from loguru import logger

from ...agents.tools.chat_memory import chat_memory
from ..data_models import ConversationFollowUpRequest, ConversationStartRequest
from ..dependencies import AUTH_SESSIONS, bearer_token, require_user
from ..services.conversation import execute_turn

router = APIRouter(tags=["conversations"])


def _bind_session(token: Optional[str], session_id: str) -> None:
    if token and token in AUTH_SESSIONS:
        AUTH_SESSIONS[token]["session_id"] = session_id


@router.post("/conversations")
async def start_conversation(
    request: ConversationStartRequest = Body(default_factory=ConversationStartRequest),
    user: dict[str, Any] = Depends(require_user),
    authorization: Optional[str] = Header(default=None),
):
    session_id = request.session_id or user.get("session_id") or str(uuid4())
    chat_memory.get_or_create_session(
        session_id=session_id,
        user_id=user.get("user_id"),
        user_role=user.get("user_role"),
    )
    _bind_session(bearer_token(authorization), session_id)

    question = (request.question or "").strip()
    if not question:
        return {"success": True, "session_id": session_id, "turn_type": "start"}

    try:
        result = await execute_turn(
            question=question,
            session_id=session_id,
            user_id=user.get("user_id"),
            user_role=user.get("user_role"),
            allowed_rep_codes=user.get("allowed_rep_codes") or [],
            turn_type="start",
        )
        return result
    except Exception as e:
        logger.error(f"Conversation start error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.post("/conversations/{session_id}/follow-up")
async def follow_up_conversation(
    session_id: str,
    request: ConversationFollowUpRequest,
    user: dict[str, Any] = Depends(require_user),
):
    question = (request.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")

    session = chat_memory.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found. Start a new conversation first.")

    try:
        return await execute_turn(
            question=question,
            session_id=session_id,
            user_id=user.get("user_id"),
            user_role=user.get("user_role"),
            allowed_rep_codes=user.get("allowed_rep_codes") or [],
            turn_type="follow_up",
            clarification_answer=request.clarification_answer,
        )
    except Exception as e:
        logger.error(f"Conversation follow-up error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
