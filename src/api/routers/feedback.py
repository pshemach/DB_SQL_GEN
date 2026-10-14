from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...agents.tools.chat_memory import chat_memory
from ..data_models import FeedbackRequest
from ..dependencies import require_user

router = APIRouter(tags=["feedback"])


@router.post("/feedback")
async def save_feedback(request: FeedbackRequest, user: dict[str, Any] = Depends(require_user)):
    if request.feedback_type not in ("like", "dislike"):
        raise HTTPException(status_code=400, detail="feedback_type must be like or dislike.")

    chat_memory.save_feedback(
        session_id=request.session_id,
        user_id=str(user.get("user_id") or ""),
        message_id=request.message_id,
        message_type=request.message_type,
        message_content=(request.message_content or "")[:500],
        feedback_type=request.feedback_type,
    )
    return {"success": True, "message": "Feedback saved."}
