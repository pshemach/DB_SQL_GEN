from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from src.agents.state import AgentState
from src.agents.prompts.agent_prompts import PLANNER_PROMPT
from src.agents.tools.business_knowledge_retriever import business_knowledge_retriever as doc_retriever
from src.infrastructure.llm import get_reasoning_llm

class PlannerAgent:
    """Decomposes natural language questions into structured logical plans."""
    
    def __init__(self):
        # self.llm = get_fast_chat_llm(temperature=0)
        self.llm = get_reasoning_llm(temperature=0)
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", PLANNER_PROMPT),
            ("human", "{question}")
        ])
        
        self.chain = self.prompt | self.llm
        
    def plan(self, state: AgentState) -> dict:
        """Generate a logical plan for the question."""
        logger.info("PLANNER: Decomposing question into logical steps")
        
        question = state["question"]
        business_definitions = doc_retriever.retrieve_business_definitions_block(
            question=question, k=4)
        
        try:
            response = self.chain.invoke({
                "question": question,
                "business_definitions": business_definitions,
                "memory_context": state.get("memory_context", ""),
                })
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

# Node function for LangGraph
def planner_node(state: AgentState) -> dict:
    """LangGraph node wrapper for PlannerAgent."""
    agent = PlannerAgent()
    return agent.plan(state)