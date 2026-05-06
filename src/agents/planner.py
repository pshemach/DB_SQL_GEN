from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from ..core.state import AgentState
from ..config import settings
from ..prompt import PLANNER_PROMPT
from ..tools import BusinessKnowledgeStore

doc_retriever = BusinessKnowledgeStore()

class PlannerAgent:
    """Decomposes natural language questions into structured logical plans."""
    
    def __init__(self):
        # self.llm = ChatOpenAI(
        #     model= settings.openai_model_fast,
        #     api_key=settings.openai_api_key
        # )
        
        self.llm = ChatAnthropic(
            model=settings.anthropic_model_fast,
            api_key=settings.anthropic_api_key
        )
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", PLANNER_PROMPT),
            ("human", "{question}")
        ])
        
        self.chain = self.prompt | self.llm
        
    def plan(self, state: AgentState) -> dict:
        """Generate a logical plan for the question."""
        logger.info("PLANNER: Decomposing question into logical steps")
        
        question = state["question"]
        business_definitions = doc_retriever.retrieve_business_definitions_block(question=question)
        
        try:
            response = self.chain.invoke({
                "question": question,
                "business_definitions": business_definitions
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