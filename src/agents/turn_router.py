"""
Unified turn router — replaces sequential conversation_router, gap_detector, and follow_up_detector.
"""

from __future__ import annotations

import json
from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from langgraph.types import interrupt

from ..config import settings
from ..graph.graph_state import AgentState
from ..tools import business_knowledge_store, business_knowledge_retriever
from ..tools.chat_memory import chat_memory
from ..utils.json_utils import extract_json
from ..utils.metrics import set_router_action
from ..utils.llm_factory import groq_llm
from ..guardrails.social_messages import is_social_message

# ==========================================
# 1. PROMPT DEFINITIONS
# ==========================================

ORCHESTRATOR_SYSTEM_PROMPT = """You are the dialogue manager for a Text-to-SQL Sales BI Assistant.
Your task is to analyze the user's query and decide the next best action.

CONVERSATION CONTEXT:
<memory_context>
{memory_context}
</memory_context>

<retrieved_business_definitions>
{retrieved_knowledge}
</retrieved_business_definitions>

Evaluate if the question contains any unknown business term or undefined metric.
If a business definition is missing, set action to "clarify" and ask a clear question explaining the gap.

Return ONLY a valid JSON object:
{{
  "action": "run_sql | clarify | transform_previous | deny | chitchat | cancel",
  "confidence": 0.0,
  "clarification_question": "Explain defined business KPI rules only if action is clarify",
  "gap_type": "knowledge_gap | none",
  "gap_reason": "Explanation of the knowledge gap if any",
  "enriched_question": "Rewritten question incorporating system scope (no SQL)"
}}
"""

KNOWLEDGE_EXTRACT_PROMPT = """You are a business knowledge extraction agent.
A user has provided a definition for an unknown metric. Extract the clean business formula.

Original User Question:
{original_question}

User Answer / Definition:
{user_answer}

Return ONLY valid JSON:
{{
  "name": "snake_case_metric_name",
  "keywords": ["synonyms"],
  "definition": "A clear description of the calculation logic and filters"
}}
"""

# ==========================================
# 2. AGENT CODE
# ==========================================

class TurnRouterAgent:
    def __init__(self):
        # Using the standard model instance
        self.llm = groq_llm(temperature=0)
        
        self.orchestration_prompt = ChatPromptTemplate.from_messages([
            ("system", ORCHESTRATOR_SYSTEM_PROMPT),
            ("human", "{question}"),
        ])
        
        self.extraction_prompt = ChatPromptTemplate.from_messages([
            ("system", KNOWLEDGE_EXTRACT_PROMPT),
            ("human", "{user_answer}"),
        ])
        
        self.orchestrator_chain = self.orchestration_prompt | self.llm
        self.extractor_chain = self.extraction_prompt | self.llm

    def route(self, state: AgentState) -> dict[str, Any]:
        question = state["question"]
        session_id = state.get("session_id")
        metrics = state.get("metrics")

        # 2. Retrieve existing domain knowledge from store
        retrieved_knowledge = self._retrieve_knowledge(question)
        
        # 3. Invoke Dialogue Orchestration LLM
        try:
            resp = self.orchestrator_chain.invoke({
                "question": question,
                "memory_context": state.get("memory_context") or "",
                "retrieved_knowledge": retrieved_knowledge
            })
            result = extract_json(resp.content)
        except Exception as e:
            logger.error(f"Orchestration routing failed: {e}")
            result = {"action": "run_sql", "confidence": 0.5}

        action = result.get("action", "run_sql")
        
        # ======================================================
        # INTERRUPT & CAPTURE LOGIC (IN-LINE RESUME FLOW)
        # ======================================================
        if action == "clarify":
            question_to_user = result.get("clarification_question") or "Could you define that KPI?"
            
            # Save clarification prompt to memory history
            chat_memory.add_message(
                session_id=session_id,
                role="assistant",
                content=question_to_user,
                message_type="clarification_question"
            )
            
            # Suspend LangGraph execution and wait for user's text input
            user_response = interrupt({
                "type": "clarification_pause",
                "question_to_user": question_to_user,
                "gap_type": "knowledge_gap",
                "pending_original_question": question
            })
            
            # --- EXECUTION RESUMES HERE WHEN USER ANSWERS ---
            logger.info("Resuming orchestrator node; capturing user answer...")
            
            try:
                # Capture and structure the user's business formula
                extract_resp = self.extractor_chain.invoke({
                    "original_question": question,
                    "user_answer": user_response
                })
                extracted_rule = extract_json(extract_resp.content)
                definition_text = extracted_rule.get("definition", "")
            except Exception as e:
                logger.error(f"Failed to structure captured knowledge: {e}")
                definition_text = str(user_response)
                extracted_rule = {"definition": definition_text}

            # Update session logs with resolved gaps
            chat_memory.resolve_latest_clarification(session_id, user_response)
            chat_memory.resolve_latest_knowledge_gap(session_id)

            # Package combined question and set dynamic business context
            combined_question = f"Original Question: {question}\nBusiness Definition: {definition_text}"
            
            return {
                "turn_action": "run_sql",
                "question": combined_question,
                "enriched_question": combined_question,
                "business_definitions": definition_text,
                "waiting_for_user": False,
                "needs_clarification": False,
                "captured_business_rule": extracted_rule,
                "metrics": set_router_action(metrics, "run_sql")
            }

        # 4. Standard action paths
        out = {
            "turn_action": action,
            "router_confidence": float(result.get("confidence", 1.0)),
            "enriched_question": result.get("enriched_question") or question,
            "gap_type": result.get("gap_type"),
            "gap_reason": result.get("gap_reason"),
            "metrics": set_router_action(metrics, action)
        }
        
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

# Node wrapper for LangGraph
def turn_router_node(state: AgentState) -> dict:
    orchestrator = TurnRouterAgent()
    return orchestrator.route(state)