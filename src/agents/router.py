"""
RouterAgent. Classifies the turn and chooses the next step:
a direct text reply, reuse the previous result, deny, or run SQL.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.agents.prompts.agent_prompts import build_router_prompt, chat_messages
from src.agents.state import AgentState
from src.services.chat_service.knowledge_retriever import business_knowledge_retriever
from src.services.chat_service.knowledge_store import business_knowledge_store
from src.infrastructure.llm import get_router_llm
from src.infrastructure.utils import extract_json, set_router_action


class RouterAgent:
    def __init__(self, llm=None):
        self.llm = llm or get_router_llm()

    def route(self, state: AgentState) -> dict[str, Any]:
        logger.info("Supervisor running...")
        question = state["question"]
        metrics = state.get("metrics")

        retrieved_knowledge = self._retrieve_knowledge(question)
        memory_context = state.get("memory_context") or ""

        try:
            system_prompt, user_prompt = build_router_prompt(
                question, memory_context, retrieved_knowledge
            )
            resp = self.llm.invoke(chat_messages(system_prompt, user_prompt))
            text = resp.content if hasattr(resp, "content") else str(resp)
            result = extract_json(text)
        except Exception as e:
            logger.error(f"Supervisor routing failed: {e}")
            result = {"action": "run_sql", "confidence": 0.5}

        action = result.get("action", "run_sql")
        if action in ("clarify", "chitchat"):
            action = "direct"
        logger.info(f"Supervisor classified action: {action}")

        cleaned_state_updates = {}
        if action in ("run_sql", "direct"):
            cleaned_state_updates = {
                "query_result": None,
                "result_preview": None,
                "visualizations": [],
                "sql_query": None,
                "sql_explanation": None,
                "plan": None,
                "plan_steps": None,
                "table_title": None,
                "relevant_tables": None,
                "error": None,
                "final_answer": None,
                "result_summary": None,
            }

        out = {
            **cleaned_state_updates,
            "turn_action": action,
            "question_description": result.get("question_description") or question,
            "metrics": set_router_action(metrics, action),
        }

        if result.get("question_description"):
            out["question"] = result["question_description"]

        return out

    def _retrieve_knowledge(self, question: str) -> str:
        keyword_matches = business_knowledge_store.keyword_search(question)
        keyword_knowledge = "\n".join(
            f"KPI: {m['name']}\n{m['definition']}" for m in keyword_matches
        )
        vector_knowledge = ""
        if business_knowledge_retriever:
            try:
                vector_knowledge = business_knowledge_retriever.retrieve_business_definitions_block(question)
            except Exception:
                pass
        return "\n\n".join(x for x in [keyword_knowledge, vector_knowledge] if x)
