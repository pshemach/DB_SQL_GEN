from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from ..graph.graph_state import AgentState
from ..config import settings
from ..prompt import CLARIFICATION_AGENT_PROMPT
from ..utils.json_utils import extract_json
from ..tools import chat_memory
from ..utils.llm_factory import groq_llm


class ClarificationAgent:
    def __init__(self):
        self.llm = groq_llm(temperature=0)

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", CLARIFICATION_AGENT_PROMPT),
            ("human", "{question}")
        ])

        self.chain = self.prompt | self.llm
        
    def clarify(self, state: AgentState) -> dict:
        
        question = state['question']
        session_id = state['session_id']
        
        try:
            response = self.chain.invoke({
                "question": question,
                "gap_type": state.get("gap_type"),
                "gap_reason": state.get("gap_reason"),
                "missing_pieces": state.get("missing_pieces", []),
                "memory_context": state.get("memory_context", "")
            })
            
            result = extract_json(response.content)
            question_to_user = result["question_to_user"]
            
            if session_id:
                chat_memory.add_clarification(
                    session_id=session_id,
                    original_question=question,
                    clarification_question=question_to_user,
                    resolved=False
                )

                if state.get("gap_type") == "knowledge_gap":
                    chat_memory.add_knowledge_gap(
                        session_id=session_id,
                        question=question,
                        missing_pieces=state.get("missing_pieces", []),
                        reason=state.get("gap_reason") or "",
                        resolved=False
                    )
            return {
                "question_to_user": question_to_user,
                "waiting_for_user": True,
                "pending_original_question": question,
                "should_retry": False
            }
        
        except Exception as e:
            logger.error(f"Clarification generation failed: {e}")

            return {
                "question_to_user": "Please provide more details about how this should be calculated.",
                "waiting_for_user": True,
                "pending_original_question": question,
                "should_retry": False
            }
            
            
def clarification_node(state: dict) -> dict:
    return ClarificationAgent().clarify(state)