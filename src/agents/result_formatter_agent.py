import json
import pandas as pd
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from ..config import settings
from ..prompt import RESULT_FORMATTER_PROMPT
from ..utils.json_utils import extract_json


class ResultFormatterAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model_fast,
            api_key=settings.openai_api_key,
            temperature=0
        )

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", RESULT_FORMATTER_PROMPT),
            ("human", "{question}")
        ])

        self.chain = self.prompt | self.llm

    def format(self, state: dict) -> dict:
        rows = state.get("query_result") or []

        if not rows:
            return {
                "result_summary": "No records found.",
                "table_title": "Query Result",
                "visualization_config": {
                    "enabled": False,
                    "chart_type": "none",
                    "x_column": None,
                    "y_column": None,
                    "color_column": None
                }
            }

        df = self._rows_to_dataframe(rows)

        if df.empty:
            return {
                "result_summary": "Query completed successfully.",
                "table_title": "Query Result",
                "visualization_config": {"enabled": False}
            }

        sample_rows = df.head(10).to_dict(orient="records")

        try:
            response = self.chain.invoke({
                "question": state.get("question", ""),
                "sql_query": state.get("sql_query", ""),
                "columns": list(df.columns),
                "sample_rows": sample_rows
            })

            result = extract_json(response.content)

            return {
                "result_summary": result.get("summary"),
                "table_title": result.get("table_title", "Query Result"),
                "visualization_config": result.get("chart", {"enabled": False})
            }

        except Exception as e:
            logger.error(f"Result formatter error: {e}")

            return {
                "result_summary": "Query completed successfully.",
                "table_title": "Query Result",
                "visualization_config": self._fallback_chart_config(df)
            }

    def _rows_to_dataframe(self, rows):
        if hasattr(rows[0], "_mapping"):
            df = pd.DataFrame([dict(row._mapping) for row in rows])
        elif isinstance(rows[0], dict):
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(rows)

        for col in df.columns:
            converted = pd.to_numeric(
                df[col].astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False),
                errors="coerce"
            )
            if converted.notna().sum() >= max(1, len(df) * 0.7):
                df[col] = converted

        return df

    def _fallback_chart_config(self, df):
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        label_cols = [c for c in df.columns if c not in numeric_cols]

        if not numeric_cols or not label_cols:
            return {"enabled": False, "chart_type": "none"}

        return {
            "enabled": True,
            "chart_type": "horizontal_bar" if len(df) > 10 else "bar",
            "x_column": label_cols[0],
            "y_column": numeric_cols[0],
            "color_column": None
        }


def result_formatter_node(state: dict) -> dict:
    return ResultFormatterAgent().format(state)