"""
In-memory SQL execution engine using DuckDB on top of cached session dataframes.
Bypasses the production MySQL database for standard filters, sorts, and slices.
"""

from typing import List, Dict, Any, Tuple
import pandas as pd
import duckdb
from loguru import logger
from langchain_core.prompts import ChatPromptTemplate

from ...utils.llm_factory import groq_llm
from ...utils.json_utils import extract_json

LOCAL_SQL_PROMPT = """You are an in-memory SQL execution planner.
Your task is to write a single standard SQL query that answers the follow-up question by querying a local virtual table named 'last_result'.

VIRTUAL TABLE SCHEMA:
- Table name: 'last_result'
- Columns and Types: {columns_and_types}

SAMPLE ROWS:
{sample_rows}

FOLLOW-UP QUESTION:
{follow_up_question}

RULES:
1. Write standard, ANSI-compliant SQL.
2. Query ONLY the virtual table named 'last_result'.
3. Use only column names listed in the schema.
4. If the question cannot be answered using ONLY these columns (e.g., requires other tables, joins, or details not present in this dataset), set "needs_live_db" to true.

Return ONLY valid JSON:
{{
  "needs_live_db": false,
  "sql": "SELECT col1, SUM(col2) FROM last_result WHERE col3 = 'Active' GROUP BY col1",
  "explanation": "Brief explanation of what the query calculates"
}}
"""

class LocalSQLEngine:
    """Runs high-performance SQL queries on cached datasets in RAM using DuckDB."""
    
    def __init__(self):
        self.llm = groq_llm(temperature=0)
        self.prompt = ChatPromptTemplate.from_template(LOCAL_SQL_PROMPT)
        self.chain = self.prompt | self.llm

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
            resp = self.chain.invoke({
                "follow_up_question": follow_up_question,
                "columns_and_types": columns_and_types,
                "sample_rows": sample_rows
            })
            
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

local_sql_engine = LocalSQLEngine()
