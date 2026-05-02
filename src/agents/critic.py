"""
Critic Agent (Refiner): Validates, executes, and corrects SQL queries.
"""

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from ..core import AgentState, db_manager
from ..config import settings
from ..prompt import REFLECTION_PROMPT


class CriticAgent:
    """
    Validates, executes, and corrects SQL queries.
    Implements closed-loop error correction with execution feedback.
    """
    
    def __init__(self):

        self.llm = ChatOpenAI(
            model=settings.openai_model_fast,
            api_key=settings.openai_api_key
        )
        # self.llm = ChatAnthropic(
        #     model=settings.anthropic_model_fast,
        #     api_key=settings.anthropic_api_key
        # )
            
        self.reflection_prompt = ChatPromptTemplate.from_messages([
            ("system", REFLECTION_PROMPT),
            ("user", "Fix the query:")
        ])
    
    def execute_and_validate(self, state: AgentState) -> dict:
        """
        Execute SQL query and handle results/errors.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with results or error information
        """
        logger.info("CRITIC: Executing and validating SQL query")
        
        sql_query = state.get("sql_query")
        if not sql_query:
            return {
                "error": "No SQL query to execute",
                "should_retry": False
            }
        
        try:
            # Execute the query
            result, error, exec_time = db_manager.execute_query(
                sql_query,
                timeout=settings.query_timeout_seconds
            )
            
            if error:
                # Query failed - prepare for reflection
                logger.warning(f"Query execution failed: {error}")
                error_type = self._classify_error(error)
                
                return {
                    "error": error,
                    "error_type": error_type,
                    "query_result": None,
                    "execution_time_ms": exec_time,
                    "should_retry": True
                }
            else:
                # Query succeeded
                logger.info(f"Query executed successfully in {exec_time:.2f}ms")
                result_preview = self._format_result_preview(result)
                
                return {
                    "query_result": result,
                    "result_preview": result_preview,
                    "execution_time_ms": exec_time,
                    "error": None,
                    "should_retry": False
                }
                
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {
                "error": str(e),
                "error_type": "runtime",
                "should_retry": True
            }
    
    def reflect_and_fix(self, state: AgentState) -> dict:
        """
        Analyze error and generate corrected SQL.
        
        Args:
            state: Current agent state with error information
            
        Returns:
            Updated state with corrected SQL
        """
        logger.info("CRITIC: Reflecting on error and fixing SQL")
        
        iterations = state.get("iterations", 0)
        
        # Check if we've exceeded max iterations
        if iterations >= settings.max_iterations:
            logger.error(f"Max iterations ({settings.max_iterations}) reached")
            return {
                "should_retry": False,
                "error": f"Failed to generate valid SQL after {settings.max_iterations} attempts"
            }
        
        question = state["question"]
        plan = state.get("plan", "")
        schema_context = state.get("schema_context", "")
        sql_query = state.get("sql_query", "")
        error = state.get("error", "")
        
        try:
            chain = self.reflection_prompt | self.llm
            
            response = chain.invoke({
                "question": question,
                "plan": plan,
                "schema_context": schema_context,
                "sql_query": sql_query,
                "error": error
            })
            
            # Clean the fixed SQL
            from agents.generator import SQLGeneratorAgent
            generator = SQLGeneratorAgent()
            fixed_sql = generator._clean_sql(response.content)
            
            logger.info(f"Generated corrected SQL (iteration {iterations + 1})")
            logger.debug(f"Fixed SQL: {fixed_sql}")
            
            return {
                "sql_query": fixed_sql,
                "iterations": iterations + 1,
                "should_retry": True
            }
            
        except Exception as e:
            logger.error(f"Reflection error: {e}")
            return {
                "error": f"Failed to correct SQL: {str(e)}",
                "should_retry": False
            }
    
    def _classify_error(self, error_msg: str) -> str:
        """
        Classify error type for better handling.
        
        Args:
            error_msg: Error message from database
            
        Returns:
            Error category
        """
        error_lower = error_msg.lower()
        
        if "column" in error_lower and ("does not exist" in error_lower or "not found" in error_lower):
            return "column_not_found"
        elif "table" in error_lower and ("does not exist" in error_lower or "not found" in error_lower):
            return "table_not_found"
        elif "syntax" in error_lower:
            return "syntax_error"
        elif "ambiguous" in error_lower:
            return "ambiguous_column"
        elif "timeout" in error_lower:
            return "timeout"
        else:
            return "runtime_error"
    
    def _format_result_preview(self, result, max_rows: int = 5) -> str:
        """
        Format query result for display.
        
        Args:
            result: Query result (list of rows or message)
            max_rows: Maximum rows to include in preview
            
        Returns:
            Formatted string preview
        """
        if isinstance(result, str):
            return result
        
        if not result:
            return "Query returned no results"
        
        try:
            # If result is a list of Row objects
            if hasattr(result[0], '_mapping'):
                rows = [dict(row._mapping) for row in result[:max_rows]]
                preview = f"Returned {len(result)} row(s). Preview:\n"
                for i, row in enumerate(rows, 1):
                    preview += f"Row {i}: {row}\n"
                
                if len(result) > max_rows:
                    preview += f"... ({len(result) - max_rows} more rows)"
                
                return preview
            else:
                return str(result[:max_rows])
                
        except Exception as e:
            logger.warning(f"Could not format result: {e}")
            return str(result)[:500]  # Truncate to 500 chars


# Node functions for LangGraph
def executor_node(state: AgentState) -> dict:
    """LangGraph node wrapper for execution."""
    agent = CriticAgent()
    return agent.execute_and_validate(state)


def reflector_node(state: AgentState) -> dict:
    """LangGraph node wrapper for reflection/correction."""
    agent = CriticAgent()
    return agent.reflect_and_fix(state)
