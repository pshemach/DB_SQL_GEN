from typing import Optional, Any
from loguru import logger
import asyncio
from src.agents.tools import chat_memory
from src.guardrails.pipeline import guardrail_pipeline
from src.agents.graph import run_agent_async


async def stream_async_agent(
    question: str,
    session_id: str,
    user_role: Optional[str] = None,
    allowed_rep_codes: Optional[list] = None,
    user_id: Optional[str] = None
):
    """Execute the query and stream partial updates to the UI."""

    guardrail_context = {
        "conversation_history": [],
        "previous_topics": [],
        "user_role": user_role,
    }

    if session_id:
        session = chat_memory.get_session(session_id)
        if session:
            guardrail_context["conversation_history"] = session.get("messages", [])

    guardrail_result = await guardrail_pipeline.evaluate(
        question,
        guardrail_context,
    )

    if not guardrail_result.get("passed", False):
        logger.warning(f"Query rejected by guardrails: {guardrail_result.get('reason')}")
        yield {
            "type": "final",
            "result": {
                "error": guardrail_result.get("reason", "Query rejected by safety checks"),
                "error_type": "guardrail_rejection",
                "waiting_for_user": False,
                "session_id": session_id,
            },
        }
        return

    async for chunk in run_agent_async(
        question=question,
        session_id=session_id,
        user_role=user_role,
        allowed_rep_codes=allowed_rep_codes,
        user_id=user_id,
    ):
        yield chunk


def run_async_agent(
    question: str,
    session_id: str,
    user_role: Optional[str] = None,
    allowed_rep_codes: Optional[list] = None,
    user_id: Optional[str] = None
):
    """Backward-compatible blocking wrapper for existing call sites."""

    async def execute_with_guardrails():
        final_result = None
        async for chunk in stream_async_agent(
            question=question,
            session_id=session_id,
            user_role=user_role,
            allowed_rep_codes=allowed_rep_codes,
            user_id=user_id,
        ):
            if chunk.get("type") == "final":
                final_result = chunk.get("result")

        return final_result or {
            "error": "No result produced",
            "should_retry": False,
        }

    return asyncio.run(execute_with_guardrails())