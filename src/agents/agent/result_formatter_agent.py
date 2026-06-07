import base64
import pandas as pd
import plotly.express as px
from loguru import logger
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
import json
from ...config import settings
from ...utils.json_utils import extract_json
from ...utils.llm_factory import groq_llm, openai_llm

RESULT_FORMATTER_PROMPT = """
You are a BI result formatter for a field sales analytics assistant.

User Question:
{question}

SQL:
{sql_query}

Row count: {row_count}

Columns:
{columns}

Sample Rows (use ONLY these values in the summary — do not invent numbers):
{sample_rows}

Numeric Columns:
{numeric_columns}

Category Columns:
{category_columns}

Data hints:
{data_hints}

Your task — return ONLY valid JSON:
1. **summary**: 1–4 sentences that answer the user's question in plain business language.
   - For a single aggregate row (e.g. one net_sales value), state the metric name and exact value from sample rows.
   - For multiple rows, highlight the top insight (highest/lowest, total, or trend).
   - Format monetary amounts with **Rs** prefix (e.g. Rs 12,345.67) — not for percentages or counts.
   - Use thousands separators for large numbers in the summary text.
   - don't mention calculation methods or how derive the answer
   - don't summation values due to all row not given
2. **table_title**: Short business title for the table.
3. **visualizations**: 0–3 charts using only provided column names.

Chart rules:
- Prefer bar / horizontal_bar for category vs metric.
- Prefer line when x is a date/time column.
- Prefer pie only for ≤8 categories showing share of one metric.
- For a single aggregate value (one row, one metric), use bar with a simple row label on x and the metric on y, or return [] if not meaningful.

JSON format:
{{
  "summary": "...",
  "table_title": "...",
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

class ResultFormatterAgent:
    def __init__(self):
        # self.llm = groq_llm(temperature=0)
        self.llm = openai_llm()

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", RESULT_FORMATTER_PROMPT),
            ("human", "{question}")
        ])

        self.chain = self.prompt | self.llm

    def format(self, state: dict) -> dict:
        rows = state.get("query_result") or []

        if not rows:
            msg = "No records found for the requested query."
            return {
                "result_summary": msg,
                "final_answer": msg,
                "table_title": "Query Result",
                "visualizations": [],
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

        reused = bool(state.get("reused_previous_result"))
        max_sample = 100 if reused else 25
        sample_df = df.head(max_sample) if len(df) > max_sample else df
        sample_rows = (
            sample_df.where(pd.notna(sample_df), None).to_dict(orient="records")
        )
        data_hints = self._build_data_hints(df, numeric_columns, category_columns)
        fallback_summary = self._build_data_driven_summary(
            df, state.get("question", ""), numeric_columns
        )
        table_title = self._table_title(state, reused)

        # if reused or len(df) <= 15:
        #     return {
        #         "result_summary": fallback_summary,
        #         "final_answer": fallback_summary,
        #         "table_title": table_title,
        #         "visualizations": self._visualizations_for_df(
        #             df, numeric_columns, category_columns
        #         ),
        #     }

        try:
            response = self.chain.invoke({
                "question": state.get("question", ""),
                "sql_query": state.get("sql_query", ""),
                "row_count": len(df),
                "columns": list(df.columns),
                "sample_rows": sample_rows,
                "numeric_columns": numeric_columns,
                "category_columns": category_columns,
                "data_hints": data_hints,
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

            summary = (result.get("summary") or "").strip() or fallback_summary

            return {
                "result_summary": summary,
                "final_answer": summary,
                "table_title": result.get("table_title") or table_title,
                "visualizations": visualizations,
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
                "result_summary": fallback_summary,
                "final_answer": fallback_summary,
                "table_title": table_title,
                "visualizations": visualizations,
            }

    def _table_title(self, state: dict, reused: bool) -> str:
        q = (state.get("question") or "").strip()
        if reused and "Follow-up:" in q:
            line = q.split("Follow-up:")[-1].strip().split("\n")[0]
            return (line[:80] + "…") if len(line) > 80 else line or "Follow-up results"
        if reused:
            return "Follow-up results"
        return "Query results"

    def _visualizations_for_df(
        self, df: pd.DataFrame, numeric_columns: list, category_columns: list
    ) -> list:
        if df.empty or not numeric_columns:
            return []
        specs = self._fallback_visualization_specs(
            df=df,
            numeric_columns=numeric_columns,
            category_columns=category_columns,
        )
        return self._build_visualizations(
            df=df,
            raw_visualizations=specs,
            numeric_columns=numeric_columns,
            category_columns=category_columns,
        )

    _CURRENCY_COLUMN_TERMS = (
        "sales", "revenue", "amount", "value", "target", "in_sales",
        "net", "gross", "price", "cost", "margin", "earning",
    )
    _NON_CURRENCY_COLUMN_TERMS = (
        "percent", "pct", "percentage", "ratio", "count", "qty",
        "quantity", "calls", "visits", "rank", "index", "id",
    )

    @staticmethod
    def _is_currency_column(column_name: str | None) -> bool:
        if not column_name:
            return True
        c = column_name.lower()
        if any(t in c for t in ResultFormatterAgent._NON_CURRENCY_COLUMN_TERMS):
            return False
        return any(t in c for t in ResultFormatterAgent._CURRENCY_COLUMN_TERMS)

    @staticmethod
    def _format_number(value, column_name: str | None = None) -> str:
        try:
            num = float(value)
            if abs(num) >= 1000:
                formatted = f"{num:,.2f}".rstrip("0").rstrip(".")
            else:
                formatted = f"{num:.2f}".rstrip("0").rstrip(".")
            if ResultFormatterAgent._is_currency_column(column_name):
                symbol = settings.currency_symbol or "Rs"
                return f"{symbol} {formatted}"
            return formatted
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _humanize_column(name: str) -> str:
        return name.replace("_", " ").strip().title()

    def _build_data_hints(
        self, df: pd.DataFrame, numeric_columns: list, category_columns: list
    ) -> str:
        symbol = settings.currency_symbol or "Rs"
        lines = [
            f"Total rows: {len(df)}",
            f"Currency for monetary columns: {symbol}",
        ]
        if len(df) == 1 and numeric_columns:
            for col in numeric_columns:
                val = df[col].iloc[0]
                if pd.notna(val):
                    lines.append(
                        f"Single value — {self._humanize_column(col)}: "
                        f"{self._format_number(val, col)}"
                    )
        elif numeric_columns and len(df) > 1:
            col = self._choose_best_numeric_column(numeric_columns)
            series = df[col].dropna()
            if not series.empty:
                lines.append(
                    f"{self._humanize_column(col)} — min: {self._format_number(series.min(), col)}, "
                    f"max: {self._format_number(series.max(), col)}, "
                    f"sum: {self._format_number(series.sum(), col)}"
                )
        if category_columns and len(df) > 1:
            lines.append(f"Categories available: {', '.join(category_columns[:5])}")
        return "\n".join(lines)

    def _build_data_driven_summary(
        self, df: pd.DataFrame, question: str, numeric_columns: list
    ) -> str:
        """Deterministic summary grounded in actual query results."""
        if df.empty:
            return (
                "No rows match your follow-up filter on the previous result. "
                "See the prior answer for the full customer list."
            )
        if not numeric_columns:
            return f"Found **{len(df)}** matching row(s). See the table below."

        q = (question or "").strip()
        period = ""
        if any(t in q.lower() for t in ("month", "week", "today", "year", "quarter")):
            period = " for the requested period"
        elif "current" in (q + " ").lower() or "this month" in q.lower():
            period = " for the current month"

        if len(df) == 1:
            parts = []
            for col in numeric_columns[:3]:
                val = df[col].iloc[0]
                if pd.notna(val):
                    parts.append(
                        f"**{self._humanize_column(col)}** is "
                        f"**{self._format_number(val, col)}**"
                    )
            if parts:
                return (
                    f"Based on your data{period}, "
                    + " and ".join(parts)
                    + "."
                )

        if len(df) == 1 and len(df.columns) == 1:
            col = df.columns[0]
            val = df[col].iloc[0]
            if pd.notna(val):
                return (
                    f"**{self._humanize_column(col)}**{period} is "
                    f"**{self._format_number(val, col)}**."
                )

        primary = self._choose_best_numeric_column(numeric_columns)
        series = df[primary].dropna()
        if series.empty:
            return f"Found {len(df)} row(s). No numeric values to summarize."

        top_idx = series.idxmax()
        top_row = df.loc[top_idx]
        label_col = None
        for c in df.columns:
            if c != primary and c not in numeric_columns:
                label_col = c
                break

        if len(df) == 1 and label_col is not None:
            label = top_row.get(label_col, top_idx)
            val = top_row[primary]
            return (
                f"Based on the previous result{period}, "
                f"**{label}** has **{self._humanize_column(primary)}** of "
                f"**{self._format_number(val, primary)}**."
            )

        if label_col is not None:
            label = top_row.get(label_col, top_idx)
            return (
                f"Showing **{len(df)}** results{period}. "
                f"Highest **{self._humanize_column(primary)}** is "
                f"**{self._format_number(series.max(), primary)}** ({label})."
            )

        return (
            f"Showing **{len(df)}** results{period}. "
            f"**{self._humanize_column(primary)}** ranges from "
            f"**{self._format_number(series.min(), primary)}** to "
            f"**{self._format_number(series.max(), primary)}**."
        )

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

        layout_kwargs = dict(
            template="plotly_white",
            height=500,
            margin=dict(l=40, r=40, t=70, b=40),
        )
        symbol = settings.currency_symbol or "Rs"
        if self._is_currency_column(y_col):
            prefix = f"{symbol} "
            if chart_type == "horizontal_bar":
                layout_kwargs["xaxis"] = dict(tickprefix=prefix)
            else:
                layout_kwargs["yaxis"] = dict(tickprefix=prefix)
        fig.update_layout(**layout_kwargs)

        return fig


def result_formatter_node(state: dict) -> dict:
    return ResultFormatterAgent().format(state)