from typing import Optional, Any
from loguru import logger
import asyncio
from src.agents.tools import chat_memory
from src.guardrails.pipeline import guardrail_pipeline
from src.agents.graph import run_agent_async

def run_async_agent(
    question: str,
    session_id: str,
    user_role: Optional[str] = None,
    allowed_rep_codes: Optional[list] = None,
    user_id: Optional[str] = None
):
    """Execute query with user context for access control and logging."""
    
    async def execute_with_guardrails():
        # === GUARDRAILS CHECK ===
        guardrail_context = {
            "conversation_history": [],
            "previous_topics": [],
            "user_role": user_role
        }
        
        # Get conversation context from chat memory if session exists
        if session_id:
            session = chat_memory.get_session(session_id)
            if session:
                guardrail_context["conversation_history"] = session.get("messages", [])
                
        # Evaluate guardrails
        guardrail_result = await guardrail_pipeline.evaluate(
            question,
            guardrail_context
        )
        
        # If guardrails reject, return error
        if not guardrail_result.get("passed", False):
            logger.warning(f"Query rejected by guardrails: {guardrail_result.get('reason')}")
            return {
                "error": guardrail_result.get("reason", "Query rejected by safety checks"),
                "error_type": "guardrail_rejection",
                "waiting_for_user": False,
                "session_id": session_id
            }
            
        # === PROCEED TO AGENT ===
        return await run_agent_async(
                question=question,
                session_id=session_id,
                user_role=user_role,
                allowed_rep_codes=allowed_rep_codes,
                user_id=user_id
            )
    return asyncio.run(execute_with_guardrails())