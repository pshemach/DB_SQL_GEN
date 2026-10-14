import json
import base64
import pandas as pd
import plotly.express as px
from loguru import logger
from langchain_core.prompts import ChatPromptTemplate

from ...config import settings
from ...utils.chart_request import detect_requested_chart_type
from ...utils.json_utils import extract_json
from ...utils.llm_factory import openai_llm

RESULT_FORMATTER_PROMPT = """
You are a BI result formatter and chart planner for a field sales analytics assistant.

User Question:
{question}

Dataset Profile:
{dataset_profile}

Computed Facts from the FULL dataset:
{computed_facts}

Chartable Columns:
{chartable_columns}

User Requested Chart Type:
{requested_chart_type}

Currency symbol:
{currency_symbol}

Conversation memory context:
{memory_context}

Your task:
Return ONLY valid JSON.

Rules:
- Use ONLY computed facts. Do not calculate totals, max, min, averages, rankings, or percentages yourself.
- Choose 1–3 meaningful charts when charts add value.
- If only one chart is meaningful, return only one.
- If no chart is meaningful, return an empty visualizations list.
- If the user requested a chart type, use that chart type.
- Do not invent column names.
- Do not mention SQL unless the user asks.
- Write a factual summary, not a description of the chart.
- The summary must use Computed Facts and include: how many groups, the total, the average, the top 3 names with their values, and the lowest name with its value.
- Copy amounts from Computed Facts. Do not invent or recalculate numbers.
- Do not answer with only "the chart illustrates" or "highlighting top and bottom performers" unless those people and amounts are named.
- Decide which numeric columns are monetary amounts. Return those exact column names in currency_columns.
- Prefix only those monetary amounts with the currency symbol. Leave rates, counts, and identifiers unprefixed.
- Avoid duplicate charts that show the same x_column, y_column, and chart_type.

Chart selection guidance:
- bar/horizontal_bar: category vs numeric metric, rep/customer/product ranking, top/bottom comparison.
- line: date/month/week trend.
- pie: share of a numeric metric across categories.
- scatter: relationship between two numeric metrics.
- no_chart: if chart would not add value.

Return JSON format:
{{
  "summary": "factual answer with if available (count, total, average, top 3 names and values, and the lowest name and value)",
  "table_title": "short business table title",
  "currency_columns": ["monetary column names only"],
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
                "requested_chart_type": None,
            }

        df = self._rows_to_dataframe(rows)
        df = self._prepare_dataframe(df)

        if df.empty:
            return {
                "result_summary": "Query executed successfully, but no table data was available.",
                "table_title": "Query Result",
                "visualizations": [],
                "requested_chart_type": None,
            }

        numeric_columns = self._get_numeric_columns(df)
        category_columns = [col for col in df.columns if col not in numeric_columns]

        reused = bool(state.get("reused_previous_result"))
        
        dataset_profile = self._build_dataset_profile(
            df=df,
            numeric_columns=numeric_columns,
            category_columns=category_columns,
            )
        
        computed_facts = self._build_computed_facts(
            df=df,
            numeric_columns=numeric_columns,
            category_columns=category_columns,
            )
        chartable_columns = self._build_chartable_columns(
            df=df,
            numeric_columns=numeric_columns,
            category_columns=category_columns,
            )
        requested_chart_type = detect_requested_chart_type(
            state.get("question", "")
            )
        
        table_title = self._table_title(state, reused)
        memory_context = state.get("memory_context") or ""

        try:
            response = self.chain.invoke({
                "question": state.get("question", ""),
                # "sql_query": state.get("sql_query", ""),
                "dataset_profile": json.dumps(dataset_profile, default=str),
                "computed_facts": json.dumps(computed_facts, default=str),
                "chartable_columns": json.dumps(chartable_columns, default=str),
                "requested_chart_type": requested_chart_type or "none",
                "currency_symbol": settings.currency_symbol or "Rs",
                "memory_context": memory_context or "",
            })

            result = extract_json(response.content)
            currency_columns = self._currency_columns_from_model(result, numeric_columns)

            raw_visualizations = result.get("visualizations", [])
            if requested_chart_type:
                raw_visualizations = self._specs_for_requested_chart(
                    raw_visualizations,
                    requested_chart_type,
                    df,
                    numeric_columns,
                    category_columns,
                )

            visualizations = self._build_visualizations(
                df=df,
                raw_visualizations=raw_visualizations,
                numeric_columns=numeric_columns,
                category_columns=category_columns,
                currency_columns=currency_columns,
            )

            if not visualizations:
                fallback_specs = self._fallback_visualization_specs(
                    df=df,
                    numeric_columns=numeric_columns,
                    category_columns=category_columns
                )
                if requested_chart_type:
                    fallback_specs = self._specs_for_requested_chart(
                        fallback_specs,
                        requested_chart_type,
                        df,
                        numeric_columns,
                        category_columns,
                    )

                visualizations = self._build_visualizations(
                    df=df,
                    raw_visualizations=fallback_specs,
                    numeric_columns=numeric_columns,
                    category_columns=category_columns,
                    currency_columns=currency_columns,
                )

            summary = self._choose_summary(
                llm_summary=(result.get("summary") or "").strip(),
                df=df,
                numeric_columns=numeric_columns,
                category_columns=category_columns,
                visualizations=visualizations,
                currency_columns=currency_columns,
            )

            return {
                "result_summary": summary,
                "final_answer": summary,
                "table_title": result.get("table_title") or table_title,
                "visualizations": visualizations,
                "requested_chart_type": requested_chart_type,
            }

        except Exception as e:
            logger.error(f"Result formatter failed: {e}")

            fallback_specs = self._fallback_visualization_specs(
                df=df,
                numeric_columns=numeric_columns,
                category_columns=category_columns
            )
            if requested_chart_type:
                fallback_specs = self._specs_for_requested_chart(
                    fallback_specs,
                    requested_chart_type,
                    df,
                    numeric_columns,
                    category_columns,
                )

            visualizations = self._build_visualizations(
                df=df,
                raw_visualizations=fallback_specs,
                numeric_columns=numeric_columns,
                category_columns=category_columns,
                currency_columns=[],
            )
            fallback_summary = self._choose_summary(
                llm_summary="",
                df=df,
                numeric_columns=numeric_columns,
                category_columns=category_columns,
                visualizations=visualizations,
                currency_columns=[],
            )

            return {
                "result_summary": fallback_summary,
                "final_answer": fallback_summary,
                "table_title": table_title,
                "visualizations": visualizations,
                "requested_chart_type": requested_chart_type,
            }
            
    def _build_dataset_profile(self, df: pd.DataFrame, numeric_columns: list, category_columns: list) -> dict:
        return {
            "row_count": int(len(df)),
            "columns": list(df.columns),
            "numeric_columns": numeric_columns,
            "category_columns": category_columns,
        }
        
    def _build_computed_facts(self, df: pd.DataFrame, numeric_columns: list, category_columns: list) -> dict:
        facts = {
            "row_count": int(len(df)),
            "metrics": {},
            "top_rows": {},
            "bottom_rows": {},
        }

        if df.empty or not numeric_columns:
            return facts

        label_col = self._choose_best_category_column(category_columns) if category_columns else None

        for col in numeric_columns:
            series = df[col].dropna()

            if series.empty:
                continue

            metric_facts = {
                "sum": self._format_number(series.sum()),
                "min": self._format_number(series.min()),
                "max": self._format_number(series.max()),
                "avg": self._format_number(series.mean()),
            }

            max_idx = series.idxmax()
            min_idx = series.idxmin()

            if label_col:
                metric_facts["max_label"] = str(df.loc[max_idx, label_col])
                metric_facts["min_label"] = str(df.loc[min_idx, label_col])

            facts["metrics"][col] = metric_facts

            sorted_df = df.dropna(subset=[col]).sort_values(by=col, ascending=False)

            keep_cols = []
            if label_col:
                keep_cols.append(label_col)
            keep_cols.append(col)

            facts["top_rows"][col] = (
                sorted_df[keep_cols]
                .head(5)
                .where(pd.notna(sorted_df[keep_cols]), None)
                .to_dict(orient="records")
            )

            facts["bottom_rows"][col] = (
                sorted_df[keep_cols]
                .tail(5)
                .where(pd.notna(sorted_df[keep_cols]), None)
                .to_dict(orient="records")
            )

        return facts
    
    def _specs_for_requested_chart(
        self,
        raw_visualizations: list,
        requested_chart_type: str,
        df: pd.DataFrame,
        numeric_columns: list,
        category_columns: list,
    ) -> list:
        """Keep one chart and force the type the user asked for."""
        specs = [dict(spec) for spec in (raw_visualizations or []) if isinstance(spec, dict)]
        if not specs:
            specs = self._fallback_visualization_specs(
                df=df,
                numeric_columns=numeric_columns,
                category_columns=category_columns,
            )
        if not specs:
            return []

        primary = dict(specs[0])
        primary["chart_type"] = requested_chart_type
        return [primary]

    def _build_chartable_columns(
        self,
        df: pd.DataFrame,
        numeric_columns: list,
        category_columns: list
    ) -> dict:
        date_like_columns = [
            col for col in df.columns
            if self._looks_like_date_column(col)
        ]

        return {
            "numeric_columns": numeric_columns,
            "category_columns": category_columns,
            "date_like_columns": date_like_columns,
            "row_count": int(len(df)),
            "recommended_x_candidates": category_columns[:8] + date_like_columns[:5],
            "recommended_y_candidates": self._sort_numeric_columns_by_business_priority(numeric_columns)[:8],
        }
        
    def _table_title(self, state: dict, reused: bool) -> str:
        q = (state.get("question") or "").strip()
        if reused and "Follow-up:" in q:
            line = q.split("Follow-up:")[-1].strip().split("\n")[0]
            return (line[:80] + "…") if len(line) > 80 else line or "Follow-up results"
        if reused:
            return "Follow-up results"
        return "Query results"

    @staticmethod
    def _currency_columns_from_model(result: dict, numeric_columns: list) -> list:
        raw = result.get("currency_columns") if isinstance(result, dict) else None
        if not isinstance(raw, list):
            return []
        allowed = set(numeric_columns)
        return [col for col in raw if isinstance(col, str) and col in allowed]

    @staticmethod
    def _format_number(value, as_currency: bool = False) -> str:
        try:
            num = float(value)
            if abs(num) >= 1000:
                formatted = f"{num:,.2f}".rstrip("0").rstrip(".")
            else:
                formatted = f"{num:.2f}".rstrip("0").rstrip(".")
            if as_currency:
                symbol = settings.currency_symbol or "Rs"
                return f"{symbol} {formatted}"
            return formatted
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _humanize_column(name: str) -> str:
        chars = []
        for index, char in enumerate(name or ""):
            if index and char.isupper() and (name[index - 1].islower() or name[index - 1].isdigit()):
                chars.append(" ")
            chars.append(char)
        return "".join(chars).replace("_", " ").strip().title()

    @staticmethod
    def _summary_is_thin(summary: str) -> bool:
        """A useful answer names amounts, not only that a chart exists."""
        return sum(ch.isdigit() for ch in (summary or "")) < 3

    def _choose_summary(
        self,
        llm_summary: str,
        df: pd.DataFrame,
        numeric_columns: list,
        category_columns: list,
        visualizations: list,
        currency_columns: list | None = None,
    ) -> str:
        chart_metric = None
        if visualizations:
            chart_metric = (visualizations[0].get("visualization_config") or {}).get("y_column")

        factual = self._build_data_driven_summary(
            df,
            numeric_columns,
            category_columns=category_columns,
            preferred_metric=chart_metric,
            currency_columns=currency_columns,
        )
        if llm_summary and not self._summary_is_thin(llm_summary):
            return llm_summary
        return factual

    def _build_data_driven_summary(
        self,
        df: pd.DataFrame,
        numeric_columns: list,
        category_columns: list | None = None,
        preferred_metric: str | None = None,
        currency_columns: list | None = None,
    ) -> str:
        """Deterministic summary grounded in actual query results."""
        if df.empty:
            return (
                "No rows match your follow-up filter on the previous result. "
                "See the prior answer for the full result."
            )
        if not numeric_columns:
            return f"Found **{len(df)}** matching row(s). See the table below."

        category_columns = category_columns or [
            col for col in df.columns if col not in numeric_columns
        ]
        money_columns = set(currency_columns or [])

        if len(df) == 1:
            parts = []
            ordered = []
            if preferred_metric in numeric_columns:
                ordered.append(preferred_metric)
            ordered.extend(col for col in numeric_columns if col not in ordered)
            for col in ordered[:3]:
                val = df[col].iloc[0]
                if pd.notna(val):
                    parts.append(
                        f"**{self._humanize_column(col)}** is "
                        f"**{self._format_number(val, as_currency=col in money_columns)}**"
                    )
            if parts:
                return "Based on your data, " + " and ".join(parts) + "."

        if preferred_metric in numeric_columns:
            primary = preferred_metric
        else:
            primary = self._choose_best_numeric_column(numeric_columns)

        ranked = df.dropna(subset=[primary]).sort_values(by=primary, ascending=False)
        if ranked.empty:
            return f"Found {len(df)} row(s). No numeric values to summarize."

        metric = self._humanize_column(primary)
        as_currency = primary in money_columns
        total = self._format_number(ranked[primary].sum(), as_currency=as_currency)
        average = self._format_number(ranked[primary].mean(), as_currency=as_currency)
        label_col = (
            self._choose_best_category_column(category_columns)
            if category_columns else None
        )
        count = len(ranked)
        grouped_by = (
            f" by **{self._humanize_column(label_col)}**" if label_col else ""
        )

        lead = (
            f"**{count}** rows{grouped_by}. "
            f"Total **{metric}** is **{total}**, "
            f"and the average is **{average}**."
        )

        if not label_col:
            return (
                f"{lead} "
                f"Values range from **{self._format_number(ranked[primary].min(), as_currency=as_currency)}** "
                f"to **{self._format_number(ranked[primary].max(), as_currency=as_currency)}**."
            )

        top_bits = []
        for _, row in ranked.head(3).iterrows():
            top_bits.append(
                f"**{row[label_col]}** ({self._format_number(row[primary], as_currency=as_currency)})"
            )
        detail = f" Highest: {', '.join(top_bits)}."
        if count > 3:
            bottom = ranked.iloc[-1]
            detail += (
                f" Lowest: **{bottom[label_col]}** "
                f"({self._format_number(bottom[primary], as_currency=as_currency)})."
            )
        return lead + detail

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
        category_columns: list,
        currency_columns: list | None = None,
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
                title=title,
                currency_columns=currency_columns,
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
                png_bytes = fig.to_image(
                    format="png",
                    width=1200,
                    height=700,
                    scale=2
                )
                chart_image_base64 = base64.b64encode(png_bytes).decode("utf-8")
            except Exception as e:
                logger.error(
                    "PNG chart export failed. Install or fix Kaleido: pip install -U kaleido. "
                    f"Original error: {e}"
                )
                chart_image_base64 = None

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
        if df.empty or not numeric_columns:
            return self._disabled_config()

        x_col = config.get("x_column")
        y_col = config.get("y_column")
        color_col = config.get("color_column")
        chart_type = config.get("chart_type") or "bar"

        allowed_chart_types = ["bar", "horizontal_bar", "line", "pie", "scatter"]

        if chart_type not in allowed_chart_types:
            chart_type = "bar"

        # y must be numeric
        if y_col not in numeric_columns:
            y_col = self._choose_best_numeric_column(numeric_columns)

        # scatter needs two numeric axes
        if chart_type == "scatter":
            if x_col not in numeric_columns or x_col == y_col:
                numeric_alt = [c for c in numeric_columns if c != y_col]
                if numeric_alt:
                    x_col = numeric_alt[0]
                else:
                    return self._disabled_config()

        # line should use date-like/category x
        elif chart_type == "line":
            if x_col not in df.columns or x_col == y_col:
                date_cols = [c for c in df.columns if self._looks_like_date_column(c)]
                if date_cols:
                    x_col = date_cols[0]
                elif category_columns:
                    x_col = self._choose_best_category_column(category_columns)
                else:
                    df["_row_label"] = [f"Row {i + 1}" for i in range(len(df))]
                    x_col = "_row_label"

        elif chart_type == "pie":
            if not category_columns:
                return self._disabled_config()

            if x_col not in category_columns:
                x_col = self._choose_best_category_column(category_columns)

        # bar/horizontal_bar
        else:
            if x_col not in df.columns or x_col == y_col or x_col in numeric_columns:
                if category_columns:
                    x_col = self._choose_best_category_column(category_columns)
                else:
                    df["_row_label"] = [f"Row {i + 1}" for i in range(len(df))]
                    x_col = "_row_label"

        if color_col not in df.columns or color_col == x_col or color_col == y_col:
            color_col = None

        if color_col and color_col in numeric_columns:
            color_col = None

        if y_col not in df.columns or df[y_col].dropna().empty:
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
        if df.empty or not numeric_columns:
            return []

        specs = []
        priority_numeric_cols = self._sort_numeric_columns_by_business_priority(numeric_columns)

        if category_columns:
            x_col = self._choose_best_category_column(category_columns)
        else:
            df["_row_label"] = [f"Row {i + 1}" for i in range(len(df))]
            x_col = "_row_label"

        # Single value: only one simple chart if useful
        if len(df) == 1:
            y_col = priority_numeric_cols[0]
            specs.append({
                "title": f"{y_col}",
                "chart_type": "bar",
                "x_column": x_col,
                "y_column": y_col,
                "color_column": None
            })
            return specs

        for y_col in priority_numeric_cols[:3]:
            if self._looks_like_date_column(x_col):
                chart_type = "line"
            elif len(df) > 10:
                chart_type = "horizontal_bar"
            else:
                chart_type = "bar"

            specs.append({
                "title": f"{y_col} by {x_col}",
                "chart_type": chart_type,
                "x_column": x_col,
                "y_column": y_col,
                "color_column": None
                })

        return specs[:3]

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
        title: str = None,
        currency_columns: list | None = None,
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
                
        if chart_type in ["bar", "horizontal_bar"]:
            fig.update_traces(
                texttemplate="%{text:,.2f}",
                textposition="outside",
                cliponaxis=False
            )

        symbol = settings.currency_symbol or "Rs"

        axis_update = {}
        if y_col in set(currency_columns or []):
            prefix = f"{symbol} "

            if chart_type == "horizontal_bar":
                axis_update["xaxis"] = dict(tickprefix=prefix)
            elif chart_type != "pie":
                axis_update["yaxis"] = dict(tickprefix=prefix)

        fig.update_layout(
            template="plotly_white",
            height=700,
            width=1200,
            title=dict(
                text=title,
                x=0.02,
                xanchor="left",
                font=dict(size=22)
            ),
            margin=dict(l=80, r=50, t=90, b=90),
            font=dict(size=14),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            **axis_update
        )

        return fig


def result_formatter_node(state: dict) -> dict:
    return ResultFormatterAgent().format(state)