"""
Schema Linker Agent (Selector): Identifies relevant tables and columns.
"""

from typing import List
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from ..core import  db_manager
from ..graph.graph_state import AgentState
from ..config import settings
from ..prompt import TABLE_SELECTION_TABLE, COLUMN_SELECTION_TABLE

class SchemaLinkerAgent:
    """
    Performs schema pruning to reduce context noise.
    Identifies only the relevant tables and columns needed for the query.
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
        self.table_selection_prompt = ChatPromptTemplate.from_messages([
                ("system", TABLE_SELECTION_TABLE),
                 ("human","{question}")
                 ])
        
        self.column_selection_prompt = ChatPromptTemplate.from_messages([
            ("system", COLUMN_SELECTION_TABLE)
        ])
    def select_tables(self, question: str, plan: str, all_tables: List[str]) -> List[str]:
        """
        Select relevant tables using LLM reasoning.
        
        Args:
            question: User's question
            plan: Logical plan
            all_tables: All available table names
            
        Returns:
            List of relevant table names
        """
        
        try:
            chain = self.table_selection_prompt | self.llm
            response = chain.invoke({
                "question": question,
                "plan": plan,
                # "all_tables": ", ".join(all_tables)
            })
            
            # Parse comma-separated table names
            selected = [t.strip() for t in response.content.split(",")]
            # Filter out any invalid table names
            selected = [t for t in selected if t in all_tables]
            
            logger.info(f"Selected {len(selected)} tables from {len(all_tables)} available")
            return selected
            
        except Exception as e:
            logger.error(f"Table selection error: {e}")
            # Fallback: return top 5 tables (simple heuristic)
            return ['sales_flat', "sales_targets", 'sales_hierarchy_nodes',
                    'external_parties', 'products', 'planned_routes', 'route_customer_assignments']
            
    def retrieve_schema(self, state: AgentState) -> dict:
        """
        Retrieve and prune schema information to only relevant tables.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with schema context
        """
        logger.info("SCHEMA LINKER: Retrieving relevant tables and schema")
        
        question = state["question"]
        plan = state.get("plan", "")
        
        try:
            # Step 1: Get all available tables
            all_tables = db_manager.get_all_table_names()
            logger.info(f"Database has {len(all_tables)} tables")
            
            # Step 2: Select relevant tables using LLM
            if plan:
                selected_tables = self.select_tables(question, plan, all_tables)
            else:
                # Fallback: use all using tables if no plan available
                selected_tables = ['sales_flat', "sales_targets", 'sales_hierarchy_nodes','external_parties', 
                                   'products', 'planned_routes', 'route_customer_assignments']
            
            # Step 3: Retrieve DDL schema for selected tables
            schema_context = db_manager.get_schema_for_tables(selected_tables)
            
            # Step 4: Get metadata (keys, indexes, etc.)
            schema_metadata = {}
            for table in selected_tables:
                metadata = db_manager.get_table_metadata(table)
                schema_metadata[table] = metadata
            
            logger.info(f"Selected {len(selected_tables)} tables: {', '.join(selected_tables)}")
            
            return {
                "relevant_tables": selected_tables,
                "schema_context": schema_context,
                "schema_metadata": schema_metadata
            }
            
        except Exception as e:
            logger.error(f"Schema retrieval error: {e}")
            return {
                "error": f"Schema retrieval failed: {str(e)}",
                "should_retry": False
            }


# Node function for LangGraph
def schema_linker_node(state: AgentState) -> dict:
    """LangGraph node wrapper for SchemaLinkerAgent."""
    agent = SchemaLinkerAgent()
    return agent.retrieve_schema(state)
