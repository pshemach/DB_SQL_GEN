from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from src.agents.state import AgentState
from src.agents.prompts.agent_prompts import CHITCHAT_SYSTEM_PROMPT
from src.infrastructure.llm import get_chat_llm

class ChitChatAgent:
    def __init__(self):
        # self.llm = get_fast_chat_llm()
        self.llm = get_chat_llm()
        self.chitchat_prompt = ChatPromptTemplate.from_messages([
            ("system", CHITCHAT_SYSTEM_PROMPT),
            ("user", "{question}")
        ])
        self.chitchat_chain = self.chitchat_prompt | self.llm
        
    def chitchat(self, state: AgentState) -> dict:
        """
        LLM-based friendly non-SQL response.
        Does not run SQL.
        """
        try:
            question = state.get("question") or ""
            memory_context = state.get("memory_context") or ""
            
            response = self.chitchat_chain.invoke({
                "question": question,
                "memory_context": memory_context
            })
            
            msg = response.content if hasattr(response, "content") else str(response)
            msg = msg.strip()
            
            if not msg:
                msg = "I can help with sales analytics, KPIs, reps, customers, products, targets, and outlet performance."

        except Exception as e:
            logger.error(f"Chitchat node failed: {e}")
            msg = "I can help with sales analytics, KPIs, reps, customers, products, targets, and outlet performance."

        return {
            "turn_action": "chitchat",
            "final_answer": msg,
            "result_summary": msg,
            "waiting_for_user": False,

            # clear SQL artifacts
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
        }

chitchat_agent = ChitChatAgent()

def chitchat_node(state: AgentState) -> dict:
    return chitchat_agent.chitchat(state=state)