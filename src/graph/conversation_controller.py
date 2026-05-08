from uuid import uuid4
from loguru import logger
import time
import os
from langsmith import traceable
from ..tools.chat_memory import chat_memory
from .multiagent_graph import graph
from ..config import settings

def _setup_langsmith():
    """
    Set LangChain environment variables from settings so every
    """
    if not settings.langchain_tracing_v2:
        return                           # tracing off — skip

    os.environ["LANGCHAIN_TRACING_V2"]  = "true"
    os.environ["LANGCHAIN_API_KEY"]     = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"]     = settings.langchain_project
    os.environ["LANGCHAIN_ENDPOINT"]    = settings.langchain_endpoint

# Call once when this module is imported
_setup_langsmith()


@traceable(
    name    = "sales-sql-agent",          # trace name in LangSmith UI
    run_type= "chain",                    # shows as a chain in the UI
    tags    = ["text-to-sql", "openai", "anthropic"],
)
async def run_agent_async(question: str, session_id: str | None = None) -> dict:
    
    session_id = chat_memory.get_or_create_session(session_id)

    initial_state = {
        "session_id": session_id,
        "question": question,
        "original_question": question,

        "previous_state": None,
        "messages": [],
        "memory_context": "",

        "conversation_route": None,

        "needs_clarification": False,
        "gap_type": None,
        "gap_reason": None,
        "confidence": None,
        "missing_pieces": [],

        "question_to_user": None,
        "waiting_for_user": False,
        "pending_original_question": None,
        "clarification_answer": None,

        "business_definitions": "",
        "matched_knowledge": [],

        "plan": None,
        "plan_steps": None,

        "relevant_tables": None,
        "schema_context": None,
        "schema_metadata": None,

        "sql_query": None,
        "sql_explanation": None,

        "query_result": None,
        "result_preview": None,
        "execution_time_ms": None,

        "error": None,
        "error_type": None,
        "iterations": 0,
        "should_retry": True,

        "start_time": time.time(),
        "cache_hit": False
    }

    try:
        result = await graph.ainvoke(initial_state)

        if result.get("start_time"):
            result["total_latency_ms"] = (time.time() - result["start_time"]) * 1000

        return result

    except Exception as e:
        logger.error(f"Graph execution error: {e}")
        return {
            **initial_state,
            "error": str(e),
            "should_retry": False
        }