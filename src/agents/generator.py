"""
SQL Generator Agent: Translates logical plans into SQL queries.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger
from src.agents.state import AgentState
from src.agents.prompts.agent_prompts import build_generator_prompt
from src.infrastructure.config import ENABLE_DYNAMIC_FEW_SHOT
from src.infrastructure.llm import get_generator_llm

class SQLGeneratorAgent:
    """
    Translates logical plans into valid SQL queries using Chain-of-Thought reasoning.
    """
    
    def __init__(self, llm=None):
        self.llm = llm or get_generator_llm(temperature=0.0)
    
    def generate(self, state: AgentState, few_shot_examples=None) -> dict:
        """
        Generate SQL query from plan and schema.
        
        Args:
            state: Current agent state
            few_shot_examples: Optional list of example queries for few-shot learning
            
        Returns:
            Updated state with generated SQL
        """
        logger.info("SQL GENERATOR: Creating SQL query from plan")
        
        question = state["question"]
        plan = state.get("plan", "")
        schema_context = state.get("schema_context", "")
        
        if not schema_context:
            logger.error("No schema context available")
            return {
                "error": "Cannot generate SQL without schema context",
                "should_retry": False
            }
        
        try:
            system_prompt, user_prompt = build_generator_prompt(question, plan, schema_context)
            messages = [SystemMessage(content=system_prompt)]
            if few_shot_examples and ENABLE_DYNAMIC_FEW_SHOT:
                for example in few_shot_examples:
                    messages.append(HumanMessage(content=example.get("question", "")))
                    messages.append(AIMessage(content=example.get("sql", "")))
            messages.append(HumanMessage(content=user_prompt))
            response = self.llm.invoke(messages)
            
            # Clean the SQL output
            sql = self._clean_sql(response.content)
            
            logger.info(f"Generated SQL ({len(sql)} characters)")
            logger.debug(f"SQL: {sql}")
            
            return {
                "sql_query": sql,
                "sql_explanation": response.content  # Keep full response with reasoning
            }
            
        except Exception as e:
            logger.error(f"SQL generation error: {e}")
            return {
                "error": f"SQL generation failed: {str(e)}",
                "should_retry": False
            }
    
    @staticmethod
    def _clean_sql(raw_sql: str) -> str:
        """
        Clean SQL output from LLM response.
        Removes markdown formatting and extracts SQL query.
        
        Args:
            raw_sql: Raw SQL from LLM
            
        Returns:
            Cleaned SQL string
        """
        # Remove markdown code blocks
        sql = raw_sql.replace("```sql", "").replace("```", "").strip()
        
        # Extract SQL from response (if it contains reasoning + SQL)
        # Look for SQL keywords: SELECT, WITH, INSERT, UPDATE, DELETE
        lines = sql.split("\n")
        sql_start_idx = None
        
        for i, line in enumerate(lines):
            if any(keyword in line.upper() for keyword in ["SELECT", "WITH", "INSERT", "UPDATE", "DELETE"]):
                sql_start_idx = i
                break
        
        if sql_start_idx is not None:
            sql = "\n".join(lines[sql_start_idx:])
        
        return sql.strip()
