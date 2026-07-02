"""
Unified turn router — replaces sequential conversation_router, gap_detector, and follow_up_detector.
Performs stateless turn classification and history-based context enrichment.
"""

from __future__ import annotations
import json
from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from langgraph.types import interrupt

from ...config import settings
from ..graph.graph_state import AgentState
from ..tools import business_knowledge_store, business_knowledge_retriever
from ..tools.chat_memory import chat_memory
from ...utils.json_utils import extract_json
from ...utils.metrics import set_router_action
from ...utils.llm_factory import groq_llm
from ...guardrails.social_messages import is_social_message

# ==========================================
# 1. PROMPT DEFINITIONS
# ==========================================

ORCHESTRATOR_SYSTEM_PROMPT = """You are the dialogue manager for a Text-to-SQL Sales BI Assistant.
Your task is to analyze the user's current query in the context of the conversation history, and decide the next best action.

CONVERSATION CONTEXT:
<memory_context>
{memory_context}
</memory_context>

<retrieved_business_definitions>
{retrieved_knowledge}
</retrieved_business_definitions>

DIAGNOSTIC & CLASSIFICATION RULES:
1. Stateless Context Enrichment (Pronoun / Antecedent Resolution):
   - If the user's query is a follow-up that refers to a person, rep, node, date range, or context from previous turns (e.g. "Show me his planned routes too", "Show their targets", "Filter to John's assignments"), you MUST resolve all pronouns ("his", "them", "their", "it") and abbreviations based on the conversation logs in `<memory_context>`.
   - Rewrite the query into a fully self-contained, concrete question. Return this in the `enriched_question` parameter in JSON, and set `action` to `run_sql`.
   - Example: User asks "Show me his route assignments too" after looking at "John Smith (REP_108)". You output `enriched_question` = "Show planned route assignments for representative John Smith (Rep Code: REP_108)" and `action` = "run_sql".

2. Clarification Answer Capture:
   - If the last assistant message in `<memory_context>` was a clarification question (e.g. asking how a metric is calculated or which representative is referred to) and the user's current query is answering it:
     - Merge the user's answer into the original request in history to build a complete, solid question.
     - Return this consolidated question in `enriched_question` and set `action` to `run_sql`.

3. In-Memory Transformation vs. Live DB SQL:
   - **`transform_previous`**: Set action to this ONLY if the query is a simple post-processing action on the previous query result (e.g., sorting, filtering, summing, or explaining columns) AND all columns needed are already in the cached schema.
   - **`run_sql`**: Set action to this if the query requires new metrics, columns, tables, or database joins not available in the previous query results.

4. Chitchat & Social Banter:
   - If the user query is a greeting, thank you, or general social conversation, set `action` to `chitchat`.

5. Security Denials:
   - If the query asks to alter database structure (DROP, DELETE, TRUNCATE, DML/DDL) or is out of scope, set `action` to `deny`.
   
Return ONLY a valid JSON object:
{{
  "action": "run_sql | clarify | transform_previous | deny | chitchat",
  "confidence": 0.95,
  "clarification_question": "Explain defined business KPI rules only if action is clarify, else null",
  "gap_type": "knowledge_gap | none",
  "gap_reason": "Explanation of the knowledge gap if any",
  "enriched_question": "Consolidated, pronoun-resolved, fully self-contained question"
}}
"""

# ==========================================
# 2. AGENT CODE
# ==========================================

class TurnRouterAgent:
    def __init__(self):
        self.llm = groq_llm(temperature=0)
        self.orchestration_prompt = ChatPromptTemplate.from_messages([
            ("system", ORCHESTRATOR_SYSTEM_PROMPT),
            ("human", "{question}"),
        ])
        self.orchestrator_chain = self.orchestration_prompt | self.llm

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
            resp = self.orchestrator_chain.invoke({
                "question": question,
                "memory_context": memory_context,
                "retrieved_knowledge": retrieved_knowledge
            })
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
            "router_confidence": float(result.get("confidence", 1.0)),
            "enriched_question": result.get("enriched_question") or question,
            "question_to_user": result.get("clarification_question"),

            "gap_type": result.get("gap_type"),
            "gap_reason": result.get("gap_reason"),

            "needs_clarification": action == "clarify",
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

# Node wrapper for LangGraph
def turn_router_node(state: AgentState) -> dict:
    orchestrator = TurnRouterAgent()
    return orchestrator.route(state)