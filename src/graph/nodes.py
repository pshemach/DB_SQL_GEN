import time
from ..tools.chat_memory import chat_memory
from ..tools import semantic_cache
from ..tools.result_cache import result_cache
from ..agents import knowledge_capture_agent
from ..utils.serialization import serialize_query_result
from .graph_state import AgentState

def memory_loader_node(state: dict) -> dict:
    session_id = state["session_id"]
    previous_state = chat_memory.get_last_state(session_id)

    chat_memory.add_message(
        session_id=session_id,
        role="user",
        content=state["question"],
        message_type="question"
    )

    return {
        "previous_state": previous_state,
        "messages": chat_memory.get_session(session_id).get("messages", []),
        "memory_context": chat_memory.build_memory_context(session_id),
        "waiting_for_user": bool(previous_state and previous_state.get("waiting_for_user"))
    }
    
    
def clarification_resolver_node(state: dict) -> dict:
    previous_state = state["previous_state"]
    user_answer = state["question"]
    session_id = state["session_id"]

    chat_memory.resolve_latest_clarification(session_id, user_answer)

    # Knowledge gap answer
    if previous_state.get("gap_type") == "knowledge_gap":
        updated_state = knowledge_capture_agent.capture(previous_state, user_answer)

        return {
            **updated_state,
            "session_id": session_id,
            "waiting_for_user": False,
            "needs_clarification": False,
            "question_to_user": None,
            "memory_context": chat_memory.build_memory_context(session_id)
        }

    # Parameter clarification answer
    combined_question = f"""
Original Question:
{previous_state.get("pending_original_question")}

Clarification Answer:
{user_answer}
""".strip()

    return {
        **previous_state,
        "session_id": session_id,
        "question": combined_question,
        "clarification_answer": user_answer,
        "waiting_for_user": False,
        "needs_clarification": False,
        "question_to_user": None,
        "memory_context": chat_memory.build_memory_context(session_id)
    }
    
def new_question_reset_node(state: dict) -> dict:
    return {
        "question": state["question"],
        "original_question": state["question"],
        "waiting_for_user": False,
        "needs_clarification": False,
        "question_to_user": None,
        "pending_original_question": None,
        "gap_type": None,
        "gap_reason": None,
        "missing_pieces": [],
        "business_definitions": "",
        "plan": None,
        "plan_steps": None,
        "sql_query": None,
        "error": None,
        "iterations": 0,
        "should_retry": True
    }
    
    

def save_memory_node(state: AgentState) -> dict:
    """
    Save conversation memory (only user questions and assistant answers).
    
    Technical artifacts (SQL, plan) are NOT saved as messages but stored in last_state
    so they don't pollute the memory context used by the LLM for reasoning.
    """
    session_id = state.get("session_id")

    if not session_id:
        return {}

    # Determine what assistant message to save, in priority order
    assistant_content = None
    message_type = None
    
    if state.get("waiting_for_user"):
        # Save the clarification question the assistant asked
        assistant_content = state.get("question_to_user")
        message_type = "clarification_question"
    
    elif state.get("error"):
        # Save errors
        assistant_content = state.get("error")
        message_type = "error"
    
    elif state.get("result_summary"):
        # Save result summary when query succeeds
        assistant_content = state.get("result_summary")
        message_type = "answer"
    
    elif state.get("final_answer"):
        # Save final answers
        assistant_content = state.get("final_answer")
        message_type = "answer"
    
    # Save the assistant message if we have one
    if assistant_content:
        chat_memory.add_message(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            message_type=message_type
        )
    
    # DO NOT save SQL queries, plans as messages - they are internal artifacts
    # They are preserved in last_state for reference, but not in conversation memory

    # Always save the full state for retrieval if needed
    chat_memory.set_last_state(session_id, state)

    return {
        "messages": chat_memory.get_session(session_id).get("messages", []),
        "memory_context": chat_memory.build_memory_context(session_id)
    }
    


def cache_result_node(state: AgentState) -> dict:
    """
    Stores successful query results in semantic cache for future use.
    Also caches the last result set per session for follow-up lookups (no re-SQL).
    """
    if state.get("error") is not None:
        return {}

    question_key = state.get("enriched_question") or state.get("question") or ""

    if state.get("sql_query") and not state.get("reused_previous_result"):
        result_to_cache = {
            "sql_query": state["sql_query"],
            "query_result": state.get("query_result"),
            "result_preview": state.get("result_preview"),
            "plan": state.get("plan"),
            "relevant_tables": state.get("relevant_tables"),
        }
        semantic_cache.set(question_key, result_to_cache)

    # Session result cache: only after a fresh SQL run (not transform / semantic hit)
    if state.get("reused_previous_result") or state.get("turn_action") in (
        "transform_previous",
        "cache_hit",
    ):
        return {}

    session_id = state.get("session_id")
    rows = serialize_query_result(state.get("query_result"))
    if session_id and isinstance(rows, list) and rows:
        tables = state.get("relevant_tables") or []
        if isinstance(tables, str):
            tables = [tables]
        schema = {str(k): type(v).__name__ for k, v in rows[0].items()}
        result_cache.cache_result(
            session_id=session_id,
            question=question_key,
            sql=state.get("sql_query") or "",
            data=rows,
            tables=list(tables),
            schema=schema,
        )

    return {}