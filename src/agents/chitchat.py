from loguru import logger
from src.agents.state import AgentState
from src.agents.prompts.agent_prompts import build_chitchat_prompt, chat_messages
from src.infrastructure.llm import get_chat_llm

class ChitChatAgent:
    def __init__(self):
        self.llm = get_chat_llm()
        
    def chitchat(self, state: AgentState) -> dict:
        """
        LLM-based friendly non-SQL response.
        Does not run SQL.
        """
        try:
            question = state.get("question") or ""
            memory_context = state.get("memory_context") or ""
            
            system_prompt, user_prompt = build_chitchat_prompt(question, memory_context)
            response = self.llm.invoke(chat_messages(system_prompt, user_prompt))
            
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