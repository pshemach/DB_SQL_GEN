from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from langsmith import traceable

from ..config import settings
from ..utils.json_utils import extract_json
from ..tools.business_knowledge_store import business_knowledge_store
from ..tools.chat_memory import chat_memory
from ..graph.graph_state import AgentState

KNOWLEDGE_CAPTURE_PROMPT = """
You are a business knowledge capture agent.

Original User Question:
{original_question}

User Answer / Business Definition:
{user_answer}

Convert this into a reusable KPI/business definition.

Return ONLY valid JSON:
{{
  "name": "snake_case_kpi_name",
  "keywords": ["..."],
  "definition": "clear business definition and calculation logic"
}}

Rules:
1. Do not write SQL.
2. Include aggregation rules if the user gave them.
3. Include filters/exclusions if the user gave them.
4. Keep it reusable for future questions.
5. Do not mention specific RepCodes etc.
6. Keep definition as common for the system.
"""


class KnowledgeCaptureAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model_fast,
            api_key=settings.openai_api_key,
            temperature=0
        )
        
        # self.llm = ChatAnthropic(
        #     model=settings.anthropic_model_fast,
        #     api_key=settings.anthropic_api_key
        # )


        self.prompt = ChatPromptTemplate.from_messages([
            ("system", KNOWLEDGE_CAPTURE_PROMPT),
            ("human", "{user_answer}")
        ])

        self.chain = self.prompt | self.llm

    def capture(self, state: dict) -> dict:
        """
        Capture business knowledge from clarification answer.
        
        Expects in state:
        - pending_original_question: The original question from user
        - clarification_answer: The user's answer to clarification
        - session_id: Session identifier
        """
        original_question = state.get("pending_original_question") or state.get("question")
        user_answer = state.get("clarification_answer", "")
        session_id = state.get("session_id")

        if not user_answer:
            logger.warning("No clarification answer in state")
            return {
                **state,
                "needs_clarification": False,
                "waiting_for_user": False
            }

        try:
            response = self.chain.invoke({
                "original_question": original_question,
                "user_answer": user_answer
            })

            result = extract_json(response.content)

            # Resolve clarification in memory
            if session_id:
                chat_memory.resolve_latest_clarification(session_id, user_answer)
                chat_memory.resolve_latest_knowledge_gap(session_id)

            combined_question = f"""
Original Question:
{original_question}

User Provided Business Definition:
{result["definition"]}
""".strip()

            return {
                **state,
                "question": combined_question,
                "clarification_answer": user_answer,
                "business_definitions": result["definition"],
                "needs_clarification": False,
                "waiting_for_user": False,
                "captured_business_rule": result
            }

        except Exception as e:
            logger.error(f"Knowledge capture failed: {e}")
            return {
                **state,
                "error": f"Knowledge capture failed: {str(e)}",
                "should_retry": False
            }


knowledge_capture_agent = KnowledgeCaptureAgent()


@traceable(name="knowledge_capture_node", run_type="chain", tags=["agent", "knowledge-capture"])
def knowledge_capture_node(state: dict) -> dict:
    """Node wrapper for knowledge capture agent."""
    return knowledge_capture_agent.capture(state)