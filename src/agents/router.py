"""
Unified turn router — replaces sequential conversation_router, gap_detector, and follow_up_detector.
Performs stateless turn classification and history-based context enrichment.
"""

from __future__ import annotations
import json
from typing import Any
from loguru import logger
from langgraph.types import interrupt

from src.agents.state import AgentState
from src.agents.tools.business_knowledge_retriever import business_knowledge_retriever
from src.agents.tools.business_knowledge_store import business_knowledge_store
from src.memory import chat_memory
from src.utils.json_utils import extract_json
from src.utils.metrics import set_router_action
from src.agents.guardrail import is_social_message
from src.agents.prompts.agent_prompts import build_router_prompt, chat_messages
from src.infrastructure.llm import get_router_llm

# ==========================================
# 1. PROMPT DEFINITIONS
# ==========================================

# ==========================================
# 2. AGENT CODE
# ==========================================

class TurnRouterAgent:
    def __init__(self, llm=None):
        self.llm = llm or get_router_llm()

    def route(self, state: AgentState) -> dict[str, Any]:
        logger.info("Route orchestrator running...")
        question = state["question"]
        session_id = state.get("session_id")
        metrics = state.get("metrics")

        # 1. Retrieve existing domain knowledge from store
        retrieved_knowledge = self._retrieve_knowledge(question)
        
        # 2. Extract memory context (default to loaded memory_context from state)
        memory_context = state.get("memory_context") or ""
        
        # 3. Invoke Dialogue Orchestration LLM
        try:
            system_prompt, user_prompt = build_router_prompt(
                question, memory_context, retrieved_knowledge
            )
            resp = self.llm.invoke(chat_messages(system_prompt, user_prompt))
            text = resp.content if hasattr(resp, "content") else str(resp)
            result = extract_json(text)
        except Exception as e:
            logger.error(f"Orchestration routing failed: {e}")
            result = {"action": "run_sql", "confidence": 0.5}

        action = result.get("action", "run_sql")
        logger.info(f"Dialogue Orchestrator classified action: {action}")

        # Clear stale state results when moving to a fresh SQL pipeline run or clarification
        cleaned_state_updates = {}
        if action in ["run_sql", "clarify"]:
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
            "enriched_question": result.get("enriched_question") or question,
            "question_to_user": result.get("clarification_question"),
            "waiting_for_user": action == "clarify",

            "metrics": set_router_action(metrics, action)
        }
        
        # If enriched_question was compiled, overwrite standard question context for SQL generator
        if result.get("enriched_question"):
            out["question"] = result["enriched_question"]

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