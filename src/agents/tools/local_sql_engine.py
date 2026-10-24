"""
In-memory SQL execution engine using DuckDB on top of cached session dataframes.
Bypasses the production MySQL database for standard filters, sorts, and slices.
"""

from typing import List, Dict, Any, Tuple
import pandas as pd
import duckdb
from loguru import logger
from src.infrastructure.db.sql_safety import assess_sql
from src.utils.json_utils import extract_json
from src.agents.prompts.agent_prompts import build_local_sql_prompt, chat_messages
from src.infrastructure.llm import get_fast_chat_llm

class LocalSQLEngine:
    """Runs high-performance SQL queries on cached datasets in RAM using DuckDB."""
    
    def __init__(self):
        self.llm = get_fast_chat_llm(temperature=0)

    def execute_follow_up(
        self, 
        follow_up_question: str, 
        cached_data: List[Dict[str, Any]], 
        schema: Dict[str, str]
    ) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Plans and runs local SQL on cached data.
        
        Returns:
            (needs_live_db, query_results, explanation)
        """
        if not cached_data:
            return True, [], "No cached data available."

        try:
            # 1. Convert cached data to Pandas DataFrame
            df = pd.DataFrame(cached_data)
            columns_and_types = {col: str(dtype) for col, dtype in df.dtypes.items()}
            sample_rows = df.head(5).to_markdown()

            # 2. Ask LLM to generate local SQL
            system_prompt, user_prompt = build_local_sql_prompt(
                follow_up_question, columns_and_types, sample_rows
            )
            resp = self.llm.invoke(chat_messages(system_prompt, user_prompt))
            
            text = resp.content if hasattr(resp, "content") else str(resp)
            plan = extract_json(text)
        except Exception as e:
            logger.error(f"Failed to generate local SQL plan: {e}")
            return True, [], str(e)

        if plan.get("needs_live_db", False) or not plan.get("sql"):
            logger.info("Local SQL Planner indicated new live DB query is required.")
            return True, [], plan.get("explanation", "Requires new database query.")

        # 3. Run local SQL using DuckDB
        local_sql = plan["sql"]
        kind, message = assess_sql(local_sql)
        if kind != "ok":
            logger.warning(f"Blocked local SQL: {message}")
            return True, [], message or "Only SELECT queries are allowed."

        logger.info(f"Executing Local DuckDB SQL: {local_sql}")
        
        try:
            # Register pandas DataFrame in current context so DuckDB can query it
            last_result = df  # registered in local namespace for DuckDB
            result_df = duckdb.query(local_sql).to_df()
            
            # Convert back to list of dicts
            results = result_df.to_dict(orient="records")
            return False, results, plan.get("explanation", "Success")
        except Exception as e:
            logger.error(f"DuckDB local query failed: {e}. Falling back to live DB.")
            return True, [], f"Local SQL error: {e}"
