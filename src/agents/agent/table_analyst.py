"""
Table Analyst Agent: Performs business analysis and explains trends over cached query results.
"""

from typing import List, Dict, Any
import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from ...utils.llm_factory import groq_llm, openai_llm
from ...config import settings

TABLE_ANALYST_PROMPT = """You are a senior Business Intelligence Analyst.
Your task is to analyze the provided data table and answer the user's follow-up question.

PREVIOUS CONVERSATION CONTEXT:
{memory_context}

DATA TABLE SUMMARY (Source Question: {source_question}):
- Total Rows: {total_rows}
- Columns: {columns}

DATA ROWS (Markdown format):
```markdown
{table_markdown}
```

USER'S FOLLOW-UP QUESTION:
{follow_up_question}

INSTRUCTIONS:
1. Provide a professional, concise, and business-focused answer.
2. Ground all numbers and calculations exactly in the provided dataset. Do not invent metrics.
3. Call out interesting anomalies, outliers, top performers, or percentage distributions if relevant.
4. Keep the explanation clear, readable, and structured using markdown lists/tables.
"""

class TableAnalystAgent:
    """Performs business analysis and explains trends over cached query results."""
    
    def __init__(self):
        # Using the reasoning model for deep analysis
        # self.llm = groq_llm(temperature=0, model=settings.groq_model_reasoning)
        self.llm = openai_llm()
        self.prompt = ChatPromptTemplate.from_template(TABLE_ANALYST_PROMPT)
        self.chain = self.prompt | self.llm

    def analyze_table(
        self,
        follow_up_question: str,
        cached_data: List[Dict[str, Any]],
        source_question: str,
        memory_context: str = ""
    ) -> str:
        """
        Analyzes the cached query results to answer the follow-up question.
        """
        if not cached_data:
            return "No data available from the previous query to analyze."

        try:
            df = pd.DataFrame(cached_data)
            
            # Limit rows in LLM context to prevent token bloat (take top 40 for context)
            context_rows = df.head(40)
            table_markdown = context_rows.to_markdown(index=False)
            
            if len(df) > 40:
                table_markdown += f"\n\n*Note: Displaying first 40 of {len(df)} total rows. Summarize accordingly.*"

            resp = self.chain.invoke({
                "follow_up_question": follow_up_question,
                "source_question": source_question,
                "total_rows": len(df),
                "columns": ", ".join(df.columns),
                "table_markdown": table_markdown,
                "memory_context": memory_context
            })
            return resp.content.strip()
        except Exception as e:
            logger.error(f"Table Analyst failed: {e}")
            return f"Failed to perform table analysis: {e}"

table_analyst = TableAnalystAgent()
