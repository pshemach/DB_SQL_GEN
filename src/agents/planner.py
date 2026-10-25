from loguru import logger
from src.agents.state import AgentState
from src.agents.prompts.agent_prompts import build_planner_prompt, chat_messages
from src.services.knowledge.retriever import business_knowledge_retriever as doc_retriever
from src.infrastructure.llm import get_planner_llm

class PlannerAgent:
    """Decomposes natural language questions into structured logical plans."""
    
    def __init__(self, llm=None):
        self.llm = llm or get_planner_llm(temperature=0)
        
    def plan(self, state: AgentState) -> dict:
        """Generate a logical plan for the question."""
        logger.info("PLANNER: Decomposing question into logical steps")
        
        question = state["question"]
        business_definitions = doc_retriever.retrieve_business_definitions_block(
            question=question, k=4)
        
        try:
            system_prompt, user_prompt = build_planner_prompt(
                question,
                business_definitions,
                state.get("memory_context", ""),
            )
            response = self.llm.invoke(chat_messages(system_prompt, user_prompt))
            plan = response.content
            
            # Extract numbered steps from the plan
            import re
            steps = re.findall(r'^\d+\..*$', plan, re.MULTILINE)
            logger.info(f"Generated plan with {len(steps)} steps")
            
            return {
                "plan": plan,
                "plan_steps": steps,
                "iterations": 0,
                "should_retry": True
            }
        except Exception as e:
            logger.error(f"Planner error: {e}")
            return {"error": f"Planning failed: {str(e)}", "should_retry": False}