"""
SQL Generator Agent: Translates logical plans into SQL queries.
"""

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate
from loguru import logger
from ..core import AgentState
from ..config import settings
from ..prompt import GENERATOR_PROMPT


class SQLGeneratorAgent:
    """
    Translates logical plans into valid SQL queries using Chain-of-Thought reasoning.
    """
    
    def __init__(self):

        # self.llm = ChatOpenAI(
        #     model=settings.openai_model_fast,
        #     api_key=settings.openai_api_key
        # )
        
        self.llm = ChatAnthropic(
            model=settings.anthropic_model_fast,
            api_key=settings.anthropic_api_key
        )

        self.system_prompt = GENERATOR_PROMPT
        
        self.generation_prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("user", "Generate the SQL query:")
        ])
    
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
            # Build prompt with or without few-shot examples
            if few_shot_examples and settings.enable_dynamic_few_shot:
                # Create few-shot prompt with examples
                examples = [
                    {"question": ex.get("question", ""), "sql": ex.get("sql", "")}
                    for ex in few_shot_examples
                ]
                
                example_prompt = ChatPromptTemplate.from_messages([
                    ("human", "{question}"),
                    ("ai", "{sql}")
                ])
                
                few_shot_prompt = FewShotChatMessagePromptTemplate(
                    example_prompt=example_prompt,
                    examples=examples
                )
                
                # Combine with main prompt
                full_prompt = ChatPromptTemplate.from_messages([
                    ("system", self.system_prompt),
                    few_shot_prompt,
                    ("user", "Generate the SQL query:")
                ])
                
                chain = full_prompt | self.llm
            else:
                chain = self.generation_prompt | self.llm
            
            # Generate SQL
            response = chain.invoke({
                "question": question,
                "plan": plan,
                "schema_context": schema_context
            })
            
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
    
    def _clean_sql(self, raw_sql: str) -> str:
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


# Node function for LangGraph
def generator_node(state: AgentState) -> dict:
    """LangGraph node wrapper for SQLGeneratorAgent."""
    agent = SQLGeneratorAgent()
    
    # Get few-shot examples from state (retrieved in previous step)
    few_shot = state.get("few_shot_examples", None)
    
    return agent.generate(state, few_shot_examples=few_shot)
