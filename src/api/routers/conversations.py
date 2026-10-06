from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger

from ...agents.tools.chat_memory import chat_memory
from ..data_models import ConversationFollowUpRequest, ConversationStartRequest
from ..dependencies import AUTH_SESSIONS, bearer_token, require_user
from ..services.conversation import execute_turn, stream_turn

router = APIRouter(tags=["conversations"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _bind_session(token: Optional[str], session_id: str) -> None:
    if token and token in AUTH_SESSIONS:
        AUTH_SESSIONS[token]["session_id"] = session_id


def _ensure_session(request_session_id: Optional[str], user: dict[str, Any], authorization: Optional[str]) -> str:
    session_id = request_session_id or user.get("session_id") or str(uuid4())
    chat_memory.get_or_create_session(
        session_id=session_id,
        user_id=user.get("user_id"),
        user_role=user.get("user_role"),
    )
    _bind_session(bearer_token(authorization), session_id)
    return session_id


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str, ensure_ascii=False)}\n\n"


async def _sse_from_turn(**kwargs) -> AsyncIterator[str]:
    try:
        async for event in stream_turn(**kwargs):
            yield _sse(event)
    except Exception as e:
        logger.error(f"Conversation stream error: {e}")
        yield _sse({"type": "error", "error": str(e)})
        yield _sse({"type": "done"})


@router.post("/conversations")
async def start_conversation(
    request: ConversationStartRequest = Body(default_factory=ConversationStartRequest),
    user: dict[str, Any] = Depends(require_user),
    authorization: Optional[str] = Header(default=None),
):
    session_id = _ensure_session(request.session_id, user, authorization)

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


@router.post("/conversations/stream")
async def start_conversation_stream(
    request: ConversationStartRequest = Body(default_factory=ConversationStartRequest),
    user: dict[str, Any] = Depends(require_user),
    authorization: Optional[str] = Header(default=None),
):
    session_id = _ensure_session(request.session_id, user, authorization)
    question = (request.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")

    return StreamingResponse(
        _sse_from_turn(
            question=question,
            session_id=session_id,
            user_id=user.get("user_id"),
            user_role=user.get("user_role"),
            allowed_rep_codes=user.get("allowed_rep_codes") or [],
            turn_type="start",
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


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


@router.post("/conversations/{session_id}/follow-up/stream")
async def follow_up_conversation_stream(
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

    return StreamingResponse(
        _sse_from_turn(
            question=question,
            session_id=session_id,
            user_id=user.get("user_id"),
            user_role=user.get("user_role"),
            allowed_rep_codes=user.get("allowed_rep_codes") or [],
            turn_type="follow_up",
            clarification_answer=request.clarification_answer,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
