"""
Schema Linker Agent (Selector): Identifies relevant tables and columns.
"""

from typing import List, Dict
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from ..core import db_manager
from ..graph.graph_state import AgentState
from ..config import settings
from ..prompt import TABLE_SELECTION_TABLE, COLUMN_SELECTION_TABLE
from ..tools.schema_vector_store import schema_vector_store

class SchemaLinkerAgent:
    """
    Performs schema pruning to reduce context noise.
    Identifies only the relevant tables and columns needed for the query.
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
        self.table_selection_prompt = ChatPromptTemplate.from_messages([
            ("system", TABLE_SELECTION_TABLE),
            ("human", "Question: {question}\nCandidate Tables: {candidate_tables}")
        ])
        
        self.column_selection_prompt = ChatPromptTemplate.from_messages([
            ("system", COLUMN_SELECTION_TABLE)
        ])
        
    def select_tables(self, question: str, plan: str, candidate_tables: List[str]) -> List[str]:
        """
        Select relevant tables using LLM reasoning from pruned candidate list.
        
        Args:
            question: User's question
            plan: Logical plan
            candidate_tables: List of pre-filtered candidate table names
            
        Returns:
            List of relevant table names
        """
        try:
            chain = self.table_selection_prompt | self.llm
            response = chain.invoke({
                "question": question,
                "plan": plan,
                "candidate_tables": ", ".join(candidate_tables)
            })
            
            # Parse comma-separated table names
            selected = [t.strip() for t in response.content.split(",")]
            # Filter out any table names not in the candidates list
            selected = [t for t in selected if t in candidate_tables]
            
            logger.info(f"SchemaLinker: Selected {len(selected)} tables from {len(candidate_tables)} vector candidates.")
            return selected
            
        except Exception as e:
            logger.error(f"Table selection error: {e}")
            # Fallback: return top 5 tables (simple heuristic)
            return ['sales_flat', "sales_targets", 'sales_hierarchy_nodes',
                    'external_parties', 'products', 'planned_routes', 'route_customer_assignments']
            
    def retrieve_schema(self, state: AgentState) -> dict:
        """
        Retrieve and prune schema information using a 2-stage retriever:
        Stage 1: Vector search for candidates
        Stage 2: LLM pruning of candidates and key validation
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with schema context
        """
        logger.info("SCHEMA LINKER: Retrieving relevant tables and schema using Vector candidates")
        
        question = state["question"]
        plan = state.get("plan", "")
        
        try:
            # Stage 1: Vector similarity candidate retrieval
            # Merge question and plan to capture both the vocabulary and structural intent
            query_context = f"{question} {plan}" if plan else question
            candidate_tables = schema_vector_store.retrieve_candidate_tables(query_context, k=15)
            logger.info(f"SchemaLinker Stage 1: Found {len(candidate_tables)} candidate tables from VectorDB.")
            
            # Stage 2: Select relevant tables from vector candidates using LLM
            if plan:
                selected_tables = self.select_tables(question, plan, candidate_tables)
            else:
                # Fallback: use core subset present in candidates
                core_fallback = ['sales_flat', "sales_targets", 'sales_hierarchy_nodes', 'external_parties', 
                                 'products', 'planned_routes', 'route_customer_assignments']
                selected_tables = [t for t in core_fallback if t in candidate_tables]
                if not selected_tables:
                    selected_tables = ['sales_flat', 'sales_targets', 'sales_hierarchy_nodes']
            
            # Enforce Mandatory Rules: If sales_targets is selected, sales_hierarchy_nodes MUST be selected.
            if "sales_targets" in selected_tables and "sales_hierarchy_nodes" not in selected_tables:
                selected_tables.append("sales_hierarchy_nodes")
                logger.info("SchemaLinker: Appended mandatory bridge 'sales_hierarchy_nodes'.")
            
            # Retrieve DDL schema for selected tables
            schema_context = db_manager.get_schema_for_tables(selected_tables)
            
            # Get metadata (keys, indexes, etc.)
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
