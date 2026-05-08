from ..tools.chat_memory import chat_memory
from ..agents.intent_switch_agent import intent_switch_agent
from ..agents.knowledge_capture_agent import knowledge_capture_agent
from ..graph.multiagent_graph import graph


async def continue_after_user_reply(
    previous_state: dict,
    user_reply: str
) -> dict:
    session_id = previous_state["session_id"]

    decision = intent_switch_agent.detect(previous_state, user_reply)

    if decision == "NEW_QUESTION":
        chat_memory.add_message(
            session_id=session_id,
            role="user",
            content=user_reply,
            message_type="new_question"
        )

        return await graph.ainvoke({
            **previous_state,
            "question": user_reply,
            "original_question": user_reply,
            "waiting_for_user": False,
            "needs_clarification": False,
            "question_to_user": None,
            "memory_context": chat_memory.build_memory_context(session_id)
        })

    # ANSWER
    chat_memory.add_message(
        session_id=session_id,
        role="user",
        content=user_reply,
        message_type="clarification_answer"
    )

    if previous_state.get("gap_type") == "knowledge_gap":
        updated_state = knowledge_capture_agent.capture(previous_state, user_reply)
    else:
        chat_memory.resolve_latest_clarification(session_id, user_reply)

        combined_question = f"""
Original Question:
{previous_state.get("pending_original_question")}

Clarification Answer:
{user_reply}
""".strip()

        updated_state = {
            **previous_state,
            "question": combined_question,
            "clarification_answer": user_reply,
            "waiting_for_user": False,
            "needs_clarification": False,
            "question_to_user": None,
            "memory_context": chat_memory.build_memory_context(session_id)
        }

    return await graph.ainvoke(updated_state)