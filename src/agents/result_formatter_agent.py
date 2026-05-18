# import json
# import pandas as pd
# from langchain_openai import ChatOpenAI
# from langchain_anthropic import ChatAnthropic
# from langchain_core.prompts import ChatPromptTemplate
# from loguru import logger
# from ..config import settings
# from ..prompt import RESULT_FORMATTER_PROMPT
# from ..utils.json_utils import extract_json


# class ResultFormatterAgent:
#     def __init__(self):
#         # self.llm = ChatOpenAI(
#         #     model=settings.openai_model_fast,
#         #     api_key=settings.openai_api_key,
#         #     temperature=0
#         # )
#         self.llm = ChatAnthropic(
#             model=settings.anthropic_model_fast,
#             api_key=settings.anthropic_api_key
#         )


#         self.prompt = ChatPromptTemplate.from_messages([
#             ("system", RESULT_FORMATTER_PROMPT),
#             ("human", "{question}")
#         ])

#         self.chain = self.prompt | self.llm

#     def format(self, state: dict) -> dict:
#         rows = state.get("query_result") or []

#         if not rows:
#             return {
#                 "result_summary": "No records found.",
#                 "table_title": "Query Result",
#                 "visualization_config": {
#                     "enabled": False,
#                     "chart_type": "none",
#                     "x_column": None,
#                     "y_column": None,
#                     "color_column": None
#                 }
#             }

#         df = self._rows_to_dataframe(rows)

#         if df.empty:
#             return {
#                 "result_summary": "Query completed successfully.",
#                 "table_title": "Query Result",
#                 "visualization_config": {"enabled": False}
#             }

#         sample_rows = df.head(10).to_dict(orient="records")

#         try:
#             response = self.chain.invoke({
#                 "question": state.get("question", ""),
#                 "sql_query": state.get("sql_query", ""),
#                 "columns": list(df.columns),
#                 "sample_rows": sample_rows
#             })

#             result = extract_json(response.content)

#             return {
#                 "result_summary": result.get("summary"),
#                 "table_title": result.get("table_title", "Query Result"),
#                 "visualization_config": result.get("chart", {"enabled": False})
#             }

#         except Exception as e:
#             logger.error(f"Result formatter error: {e}")

#             return {
#                 "result_summary": "Query completed successfully.",
#                 "table_title": "Query Result",
#                 "visualization_config": self._fallback_chart_config(df)
#             }

#     def _rows_to_dataframe(self, rows):
#         if hasattr(rows[0], "_mapping"):
#             df = pd.DataFrame([dict(row._mapping) for row in rows])
#         elif isinstance(rows[0], dict):
#             df = pd.DataFrame(rows)
#         else:
#             df = pd.DataFrame(rows)

#         for col in df.columns:
#             converted = pd.to_numeric(
#                 df[col].astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False),
#                 errors="coerce"
#             )
#             if converted.notna().sum() >= max(1, len(df) * 0.7):
#                 df[col] = converted

#         return df

#     def _fallback_chart_config(self, df):
#         numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
#         label_cols = [c for c in df.columns if c not in numeric_cols]

#         if not numeric_cols or not label_cols:
#             return {"enabled": False, "chart_type": "none"}

#         return {
#             "enabled": True,
#             "chart_type": "horizontal_bar" if len(df) > 10 else "bar",
#             "x_column": label_cols[0],
#             "y_column": numeric_cols[0],
#             "color_column": None
#         }


# def result_formatter_node(state: dict) -> dict:
#     return ResultFormatterAgent().format(state)

import base64
import pandas as pd
import plotly.express as px
from loguru import logger
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
import json

from ..config import settings
from ..utils.json_utils import extract_json


# RESULT_FORMATTER_PROMPT = """
# You are a BI result formatter.

# Your task:
# Given the user question and executed result table metadata, return:
# 1. short business summary
# 2. table title
# 3. best visualization config

# User Question:
# {question}

# SQL:
# {sql_query}

# Columns:
# {columns}

# Sample Rows:
# {sample_rows}

# Numeric Columns:
# {numeric_columns}

# Category Columns:
# {category_columns}

# Rules:
# 1. Return ONLY valid JSON.
# 2. Do not invent numbers.
# 3. Recommend a chart only if at least one numeric column exists.
# 4. Prefer horizontal_bar when many rows or long labels.
# 5. Prefer line chart for date/time trend.
# 6. Prefer pie only for small category share data.
# 7. x_column and y_column must be from the provided columns only.
# 8. color_column can be null or one category column.

# JSON format:
# {{
#   "summary": "short business summary",
#   "table_title": "business table title",
#   "visualization_config": {{
#     "enabled": true,
#     "chart_type": "bar | horizontal_bar | line | pie | scatter | none",
#     "x_column": "column name or null",
#     "y_column": "column name or null",
#     "color_column": null
#   }}
# }}
# """

RESULT_FORMATTER_PROMPT = """
You are a BI result formatter.

Your task:
Given the user question and executed result table metadata, return:
1. short business summary
2. table title
3. up to 3 suitable visualizations

User Question:
{question}

SQL:
{sql_query}

Columns:
{columns}

Sample Rows:
{sample_rows}

Numeric Columns:
{numeric_columns}

Category Columns:
{category_columns}

Rules:
1. Return ONLY valid JSON.
2. Do not invent numbers.
3. Return 0 to 3 visualizations.
4. Each visualization must use only provided columns.
5. Prefer bar / horizontal_bar for category vs metric.
6. Prefer line for trend/date columns.
7. Prefer pie only for small category-share cases.
8. Avoid duplicate graphs with the same meaning.
9. If no suitable chart exists, return an empty visualizations array.
10.Select chart type for meaning full business columns. 

JSON format:
{{
  "summary": "short summary",
  "table_title": "business table title",
  "visualizations": [
    {{
      "title": "chart title",
      "chart_type": "bar | horizontal_bar | line | pie | scatter",
      "x_column": "column name",
      "y_column": "column name",
      "color_column": null
    }}
  ]
}}
"""


# class ResultFormatterAgent:
#     def __init__(self):
#         self.llm = ChatOpenAI(
#             model=settings.openai_model_fast,
#             api_key=settings.openai_api_key,
#             temperature=0
#         )

#         self.prompt = ChatPromptTemplate.from_messages([
#             ("system", RESULT_FORMATTER_PROMPT),
#             ("human", "{question}")
#         ])

#         self.chain = self.prompt | self.llm

#     def format(self, state: dict) -> dict:
#         rows = state.get("query_result") or []

#         if not rows:
#             return {
#                 "result_summary": "No records found for the requested query.",
#                 "table_title": "Query Result",
#                 "visualization_config": {
#                     "enabled": False,
#                     "chart_type": "none",
#                     "x_column": None,
#                     "y_column": None,
#                     "color_column": None
#                 },
#                 "chart_json": None,
#                 "chart_image_base64": None
#             }

#         df = self._rows_to_dataframe(rows)
#         df = self._prepare_dataframe(df)

#         if df.empty:
#             return {
#                 "result_summary": "Query executed successfully, but no table data was available.",
#                 "table_title": "Query Result",
#                 "visualization_config": {
#                     "enabled": False,
#                     "chart_type": "none",
#                     "x_column": None,
#                     "y_column": None,
#                     "color_column": None
#                 },
#                 "chart_json": None,
#                 "chart_image_base64": None
#             }

#         numeric_columns = df.select_dtypes(include=["number"]).columns.tolist()
#         category_columns = [c for c in df.columns if c not in numeric_columns]

#         sample_rows = (
#             df.head(10)
#             .where(pd.notna(df), None)
#             .to_dict(orient="records")
#         )

#         try:
#             response = self.chain.invoke({
#                 "question": state.get("question", ""),
#                 "sql_query": state.get("sql_query", ""),
#                 "columns": list(df.columns),
#                 "sample_rows": sample_rows,
#                 "numeric_columns": numeric_columns,
#                 "category_columns": category_columns
#             })

#             result = extract_json(response.content)

#             config = self._validate_config(
#                 config=result.get("visualization_config") or {},
#                 df=df,
#                 numeric_columns=numeric_columns,
#                 category_columns=category_columns
#             )

#             fig = self._build_plotly_figure(df, config)

#             chart_json = None
#             chart_image_base64 = None

#             if fig:
#                 chart_json = json.loads(fig.to_json())

#                 try:
#                     png_bytes = fig.to_image(format="png")
#                     chart_image_base64 = base64.b64encode(png_bytes).decode("utf-8")
#                 except Exception as e:
#                     logger.warning(f"PNG chart export failed: {e}")

#             return {
#                 "result_summary": result.get("summary") or "Query executed successfully.",
#                 "table_title": result.get("table_title") or "Query Result",
#                 "visualization_config": config,
#                 "chart_json": chart_json,
#                 "chart_image_base64": chart_image_base64
#             }

#         except Exception as e:
#             logger.error(f"Result formatter failed: {e}")

#             config = self._fallback_config(
#                 df=df,
#                 numeric_columns=numeric_columns,
#                 category_columns=category_columns
#             )

#             fig = self._build_plotly_figure(df, config)

#             chart_json = json.loads(fig.to_json()) if fig else None
#             chart_image_base64 = None

#             if fig:
#                 try:
#                     png_bytes = fig.to_image(format="png")
#                     chart_image_base64 = base64.b64encode(png_bytes).decode("utf-8")
#                 except Exception:
#                     pass

#             return {
#                 "result_summary": "Query executed successfully.",
#                 "table_title": "Query Result",
#                 "visualization_config": config,
#                 "chart_json": chart_json,
#                 "chart_image_base64": chart_image_base64
#             }

#     def _rows_to_dataframe(self, rows):
#         if hasattr(rows[0], "_mapping"):
#             return pd.DataFrame([dict(row._mapping) for row in rows])

#         if isinstance(rows[0], dict):
#             return pd.DataFrame(rows)

#         return pd.DataFrame(rows)

#     def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
#         df = df.copy()

#         null_values = ["None", "none", "NULL", "null", "NaN", "nan", "", " "]
#         df = df.replace(null_values, pd.NA)

#         for col in df.columns:
#             cleaned = (
#                 df[col]
#                 .astype(str)
#                 .str.replace(",", "", regex=False)
#                 .str.replace("%", "", regex=False)
#                 .str.strip()
#             )

#             converted = pd.to_numeric(cleaned, errors="coerce")

#             non_null_count = df[col].notna().sum()
#             numeric_count = converted.notna().sum()

#             if numeric_count > 0 and numeric_count >= max(1, non_null_count * 0.5):
#                 df[col] = converted

#         return df

#     # def _validate_config(self, config, df, numeric_columns, category_columns):
#     #     if not numeric_columns:
#     #         return {
#     #             "enabled": False,
#     #             "chart_type": "none",
#     #             "x_column": None,
#     #             "y_column": None,
#     #             "color_column": None
#     #         }

#     #     x_col = config.get("x_column")
#     #     y_col = config.get("y_column")
#     #     color_col = config.get("color_column")

#     #     if y_col not in numeric_columns:
#     #         y_col = numeric_columns[0]

#     #     if x_col not in df.columns:
#     #         x_col = category_columns[0] if category_columns else df.columns[0]

#     #     if color_col not in df.columns:
#     #         color_col = None

#     #     chart_type = config.get("chart_type") or "bar"

#     #     allowed = ["bar", "horizontal_bar", "line", "pie", "scatter"]
#     #     if chart_type not in allowed:
#     #         chart_type = "bar"

#     #     if df[y_col].dropna().empty:
#     #         return {
#     #             "enabled": False,
#     #             "chart_type": "none",
#     #             "x_column": None,
#     #             "y_column": None,
#     #             "color_column": None
#     #         }

#     #     return {
#     #         "enabled": True,
#     #         "chart_type": chart_type,
#     #         "x_column": x_col,
#     #         "y_column": y_col,
#     #         "color_column": color_col
#     #     }
    
#     def _validate_config(self, config, df, numeric_columns, category_columns):
#         if not numeric_columns:
#             return {
#                 "enabled": False,
#                 "chart_type": "none",
#                 "x_column": None,
#                 "y_column": None,
#                 "color_column": None
#             }

#         x_col = config.get("x_column")
#         y_col = config.get("y_column")
#         color_col = config.get("color_column")

#         # y must be numeric
#         if y_col not in numeric_columns:
#             y_col = numeric_columns[0]

#         # x should preferably be category/text/date, not same as y
#         if x_col not in df.columns or x_col == y_col or x_col in numeric_columns:
#             if category_columns:
#                 x_col = category_columns[0]
#             else:
#                 # If no category column exists, use row number label
#                 df["_row_label"] = [f"Row {i + 1}" for i in range(len(df))]
#                 x_col = "_row_label"

#         if color_col not in df.columns or color_col == x_col or color_col == y_col:
#             color_col = None

#         chart_type = config.get("chart_type") or "bar"

#         allowed = ["bar", "horizontal_bar", "line", "pie", "scatter"]
#         if chart_type not in allowed:
#             chart_type = "bar"

#         if df[y_col].dropna().empty:
#             return {
#                 "enabled": False,
#                 "chart_type": "none",
#                 "x_column": None,
#                 "y_column": None,
#                 "color_column": None
#             }

#         return {
#             "enabled": True,
#             "chart_type": chart_type,
#             "x_column": x_col,
#             "y_column": y_col,
#             "color_column": color_col
#         }

#     # def _fallback_config(self, df, numeric_columns, category_columns):
#     #     if not numeric_columns:
#     #         return {
#     #             "enabled": False,
#     #             "chart_type": "none",
#     #             "x_column": None,
#     #             "y_column": None,
#     #             "color_column": None
#     #         }

#     #     y_col = numeric_columns[0]
#     #     x_col = category_columns[0] if category_columns else df.columns[0]

#     #     chart_type = "horizontal_bar" if len(df) > 10 else "bar"

#     #     return {
#     #         "enabled": True,
#     #         "chart_type": chart_type,
#     #         "x_column": x_col,
#     #         "y_column": y_col,
#     #         "color_column": None
#     #     }
    
#     def _fallback_config(self, df, numeric_columns, category_columns):
#         if not numeric_columns:
#             return {
#                 "enabled": False,
#                 "chart_type": "none",
#                 "x_column": None,
#                 "y_column": None,
#                 "color_column": None
#             }

#         y_col = numeric_columns[0]

#         if category_columns:
#             x_col = category_columns[0]
#         else:
#             df["_row_label"] = [f"Row {i + 1}" for i in range(len(df))]
#             x_col = "_row_label"

#         chart_type = "horizontal_bar" if len(df) > 10 else "bar"

#         return {
#             "enabled": True,
#             "chart_type": chart_type,
#             "x_column": x_col,
#             "y_column": y_col,
#             "color_column": None
#         }

#     def _build_plotly_figure(self, df: pd.DataFrame, config: dict):
#         if not config or not config.get("enabled"):
#             return None

#         x_col = config.get("x_column")
#         y_col = config.get("y_column")
#         color_col = config.get("color_column")
#         chart_type = config.get("chart_type")

#         if x_col not in df.columns or y_col not in df.columns:
#             return None

#         if color_col not in df.columns:
#             color_col = None

#         chart_df = df.copy()
#         chart_df = chart_df.dropna(subset=[x_col, y_col])

#         if chart_df.empty:
#             return None

#         chart_df = chart_df.sort_values(by=y_col, ascending=False)

#         # Limit large charts
#         if len(chart_df) > 30:
#             chart_df = chart_df.head(30)

#         title = f"{y_col} by {x_col}"

#         if chart_type == "horizontal_bar":
#             fig = px.bar(
#                 chart_df.sort_values(by=y_col, ascending=True),
#                 x=y_col,
#                 y=x_col,
#                 color=color_col,
#                 orientation="h",
#                 text=y_col,
#                 title=title
#             )

#         elif chart_type == "line":
#             fig = px.line(
#                 chart_df,
#                 x=x_col,
#                 y=y_col,
#                 color=color_col,
#                 markers=True,
#                 title=title
#             )

#         elif chart_type == "pie":
#             fig = px.pie(
#                 chart_df,
#                 names=x_col,
#                 values=y_col,
#                 color=color_col,
#                 title=f"{y_col} share by {x_col}"
#             )

#         elif chart_type == "scatter":
#             fig = px.scatter(
#                 chart_df,
#                 x=x_col,
#                 y=y_col,
#                 color=color_col,
#                 size=y_col,
#                 title=title
#             )

#         else:
#             fig = px.bar(
#                 chart_df,
#                 x=x_col,
#                 y=y_col,
#                 color=color_col,
#                 text=y_col,
#                 title=title
#             )
#             fig.update_layout(xaxis_tickangle=-45)

#         fig.update_layout(
#             template="plotly_white",
#             height=500,
#             margin=dict(l=40, r=40, t=70, b=40)
#         )

#         return fig


# def result_formatter_node(state: dict) -> dict:
#     return ResultFormatterAgent().format(state)

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
                "result_summary": "No records found for the requested query.",
                "table_title": "Query Result",
                "visualizations": []
            }

        df = self._rows_to_dataframe(rows)
        df = self._prepare_dataframe(df)

        if df.empty:
            return {
                "result_summary": "Query executed successfully, but no table data was available.",
                "table_title": "Query Result",
                "visualizations": []
            }

        numeric_columns = self._get_numeric_columns(df)
        category_columns = [col for col in df.columns if col not in numeric_columns]

        sample_rows = (
            df.head(10)
            .where(pd.notna(df), None)
            .to_dict(orient="records")
        )

        try:
            response = self.chain.invoke({
                "question": state.get("question", ""),
                "sql_query": state.get("sql_query", ""),
                "columns": list(df.columns),
                "sample_rows": sample_rows,
                "numeric_columns": numeric_columns,
                "category_columns": category_columns
            })

            result = extract_json(response.content)

            raw_visualizations = result.get("visualizations", [])

            visualizations = self._build_visualizations(
                df=df,
                raw_visualizations=raw_visualizations,
                numeric_columns=numeric_columns,
                category_columns=category_columns
            )

            if not visualizations:
                fallback_specs = self._fallback_visualization_specs(
                    df=df,
                    numeric_columns=numeric_columns,
                    category_columns=category_columns
                )

                visualizations = self._build_visualizations(
                    df=df,
                    raw_visualizations=fallback_specs,
                    numeric_columns=numeric_columns,
                    category_columns=category_columns
                )

            return {
                "result_summary": result.get("summary") or "Query executed successfully.",
                "table_title": result.get("table_title") or "Query Result",
                "visualizations": visualizations
            }

        except Exception as e:
            logger.error(f"Result formatter failed: {e}")

            fallback_specs = self._fallback_visualization_specs(
                df=df,
                numeric_columns=numeric_columns,
                category_columns=category_columns
            )

            visualizations = self._build_visualizations(
                df=df,
                raw_visualizations=fallback_specs,
                numeric_columns=numeric_columns,
                category_columns=category_columns
            )

            return {
                "result_summary": "Query executed successfully.",
                "table_title": "Query Result",
                "visualizations": visualizations
            }

    def _rows_to_dataframe(self, rows):
        if hasattr(rows[0], "_mapping"):
            return pd.DataFrame([dict(row._mapping) for row in rows])

        if isinstance(rows[0], dict):
            return pd.DataFrame(rows)

        return pd.DataFrame(rows)

    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        null_values = ["None", "none", "NULL", "null", "NaN", "nan", "", " "]
        df = df.replace(null_values, pd.NA)

        for col in df.columns:
            cleaned = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.strip()
            )

            converted = pd.to_numeric(cleaned, errors="coerce")

            non_null_count = df[col].notna().sum()
            numeric_count = converted.notna().sum()

            if numeric_count > 0 and numeric_count >= max(1, non_null_count * 0.5):
                df[col] = converted

        return df

    def _get_numeric_columns(self, df: pd.DataFrame) -> list:
        numeric_columns = []

        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                if df[col].dropna().shape[0] > 0:
                    numeric_columns.append(col)

        return numeric_columns

    def _build_visualizations(
        self,
        df: pd.DataFrame,
        raw_visualizations: list,
        numeric_columns: list,
        category_columns: list
    ) -> list:
        output = []

        if not raw_visualizations:
            return output

        used_pairs = set()

        for raw in raw_visualizations[:3]:
            config = {
                "enabled": True,
                "chart_type": raw.get("chart_type", "bar"),
                "x_column": raw.get("x_column"),
                "y_column": raw.get("y_column"),
                "color_column": raw.get("color_column")
            }

            config = self._validate_config(
                config=config,
                df=df,
                numeric_columns=numeric_columns,
                category_columns=category_columns
            )

            if not config.get("enabled"):
                continue

            pair_key = (
                config.get("x_column"),
                config.get("y_column"),
                config.get("chart_type"),
                config.get("color_column")
            )

            if pair_key in used_pairs:
                continue

            used_pairs.add(pair_key)

            title = raw.get("title") or f"{config['y_column']} by {config['x_column']}"

            fig = self._build_plotly_figure(
                df=df,
                config=config,
                title=title
            )

            if not fig:
                continue

            chart_json = None
            chart_image_base64 = None

            try:
                chart_json = json.loads(fig.to_json())
            except Exception as e:
                logger.warning(f"Chart JSON generation failed: {e}")

            try:
                png_bytes = fig.to_image(format="png")
                chart_image_base64 = base64.b64encode(png_bytes).decode("utf-8")
            except Exception as e:
                logger.warning(f"PNG chart export failed: {e}")

            output.append({
                "title": title,
                "visualization_config": config,
                "chart_json": chart_json,
                "chart_image_base64": chart_image_base64
            })

        return output

    def _validate_config(
        self,
        config: dict,
        df: pd.DataFrame,
        numeric_columns: list,
        category_columns: list
    ) -> dict:
        if not numeric_columns:
            return self._disabled_config()

        x_col = config.get("x_column")
        y_col = config.get("y_column")
        color_col = config.get("color_column")
        chart_type = config.get("chart_type") or "bar"

        allowed_chart_types = ["bar", "horizontal_bar", "line", "pie", "scatter"]

        if chart_type not in allowed_chart_types:
            chart_type = "bar"

        # y axis must be numeric
        if y_col not in numeric_columns:
            y_col = self._choose_best_numeric_column(numeric_columns)

        # x axis should not be same as y and should preferably be categorical/date
        if x_col not in df.columns or x_col == y_col or x_col in numeric_columns:
            if category_columns:
                x_col = self._choose_best_category_column(category_columns)
            else:
                df["_row_label"] = [f"Row {i + 1}" for i in range(len(df))]
                x_col = "_row_label"

        # color must be a valid category column and should not duplicate x/y
        if color_col not in df.columns or color_col == x_col or color_col == y_col:
            color_col = None

        if color_col and color_col in numeric_columns:
            color_col = None

        if df[y_col].dropna().empty:
            return self._disabled_config()

        return {
            "enabled": True,
            "chart_type": chart_type,
            "x_column": x_col,
            "y_column": y_col,
            "color_column": color_col
        }

    def _fallback_visualization_specs(
        self,
        df: pd.DataFrame,
        numeric_columns: list,
        category_columns: list
    ) -> list:
        if not numeric_columns:
            return []

        if category_columns:
            x_col = self._choose_best_category_column(category_columns)
        else:
            df["_row_label"] = [f"Row {i + 1}" for i in range(len(df))]
            x_col = "_row_label"

        specs = []

        priority_numeric_cols = self._sort_numeric_columns_by_business_priority(numeric_columns)

        for y_col in priority_numeric_cols[:3]:
            chart_type = "horizontal_bar" if len(df) > 10 else "bar"

            if self._looks_like_date_column(x_col):
                chart_type = "line"

            specs.append({
                "title": f"{y_col} by {x_col}",
                "chart_type": chart_type,
                "x_column": x_col,
                "y_column": y_col,
                "color_column": None
            })

        return specs

    def _choose_best_category_column(self, category_columns: list) -> str:
        priority_terms = [
            "name",
            "rep",
            "customer",
            "outlet",
            "product",
            "route",
            "brand",
            "category",
            "type",
            "date",
            "month"
        ]

        for term in priority_terms:
            for col in category_columns:
                if term in col.lower():
                    return col

        return category_columns[0]

    def _choose_best_numeric_column(self, numeric_columns: list) -> str:
        priority_terms = [
            "achievement_percentage",
            "percentage",
            "percent",
            "pct",
            "achievement",
            "net_sales",
            "sales",
            "target",
            "value",
            "amount",
            "qty",
            "quantity",
            "volume",
            "count",
            "calls",
            "visits"
        ]

        for term in priority_terms:
            for col in numeric_columns:
                if term in col.lower():
                    return col

        return numeric_columns[0]

    def _sort_numeric_columns_by_business_priority(self, numeric_columns: list) -> list:
        priority_terms = [
            "achievement_percentage",
            "percentage",
            "percent",
            "pct",
            "achievement",
            "net_sales",
            "sales",
            "target",
            "value",
            "amount",
            "qty",
            "quantity",
            "volume",
            "count",
            "calls",
            "visits"
        ]

        scored = []

        for col in numeric_columns:
            score = 999

            for index, term in enumerate(priority_terms):
                if term in col.lower():
                    score = index
                    break

            scored.append((score, col))

        scored.sort(key=lambda x: x[0])
        return [col for _, col in scored]

    def _looks_like_date_column(self, col: str) -> bool:
        terms = ["date", "month", "year", "day", "week"]
        return any(term in col.lower() for term in terms)

    def _disabled_config(self) -> dict:
        return {
            "enabled": False,
            "chart_type": "none",
            "x_column": None,
            "y_column": None,
            "color_column": None
        }

    def _build_plotly_figure(
        self,
        df: pd.DataFrame,
        config: dict,
        title: str = None
    ):
        if not config or not config.get("enabled"):
            return None

        x_col = config.get("x_column")
        y_col = config.get("y_column")
        color_col = config.get("color_column")
        chart_type = config.get("chart_type")

        if x_col not in df.columns or y_col not in df.columns:
            return None

        if color_col not in df.columns:
            color_col = None

        chart_df = df.copy()
        chart_df = chart_df.dropna(subset=[x_col, y_col])

        if chart_df.empty:
            return None

        if chart_type != "line":
            chart_df = chart_df.sort_values(by=y_col, ascending=False)

        if len(chart_df) > 30:
            chart_df = chart_df.head(30)

        title = title or f"{y_col} by {x_col}"

        if chart_type == "horizontal_bar":
            fig = px.bar(
                chart_df.sort_values(by=y_col, ascending=True),
                x=y_col,
                y=x_col,
                color=color_col,
                orientation="h",
                text=y_col,
                title=title
            )

        elif chart_type == "line":
            fig = px.line(
                chart_df,
                x=x_col,
                y=y_col,
                color=color_col,
                markers=True,
                title=title
            )

        elif chart_type == "pie":
            fig = px.pie(
                chart_df,
                names=x_col,
                values=y_col,
                color=color_col,
                title=title
            )

        elif chart_type == "scatter":
            fig = px.scatter(
                chart_df,
                x=x_col,
                y=y_col,
                color=color_col,
                size=y_col,
                title=title
            )

        else:
            fig = px.bar(
                chart_df,
                x=x_col,
                y=y_col,
                color=color_col,
                text=y_col,
                title=title
            )
            fig.update_layout(xaxis_tickangle=-45)

        fig.update_layout(
            template="plotly_white",
            height=500,
            margin=dict(l=40, r=40, t=70, b=40)
        )

        return fig


def result_formatter_node(state: dict) -> dict:
    return ResultFormatterAgent().format(state)