import asyncio
import json
import uuid
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from loguru import logger
from typing import Optional

from src.graph import run_agent_async
from src.utils.serialization import json_safe_value, serialize_query_result
from src.core.database import db_manager
from src.tools.business_knowledge_store import business_knowledge_store
from src.tools.chat_memory import chat_memory
from src.guardrails.pipeline import guardrail_pipeline
from src.guardrails.social_messages import is_social_message


# =============================
# PAGE CONFIG
# =============================

st.set_page_config(
    page_title="Text-to-SQL Agent",
    page_icon="💬",
    layout="wide"
)

st.title("SFA SmartAnalyst")
st.caption("Your AI-Powered Sales Intelligence Assistant")

# =============================
# RAW YAML PREVIEW
# =============================

# with st.expander("🧾 Raw Knowledge Preview"):
#     try:
#         import yaml

#         yaml_text = yaml.safe_dump(
#             {"definitions": business_knowledge_store.list_definitions()},
#             allow_unicode=True,
#             sort_keys=False,
#             default_flow_style=False
#         )

#         st.code(yaml_text, language="yaml")

#     except Exception as e:
#         st.error(f"Failed to show YAML preview: {e}")
        
# =============================
# KNOWLEDGE BASE EDITOR
# =============================

mode = st.session_state.get("kb_editor_mode")

if mode in ["add", "edit"]:
    st.markdown("---")

    is_edit = mode == "edit"
    selected_key = st.session_state.get("selected_kpi")

    existing = {}
    if is_edit and selected_key:
        existing = business_knowledge_store.get_definition(selected_key) or {}

    st.subheader("✏️ Edit KPI Definition" if is_edit else "➕ Add KPI Definition")

    with st.form("kb_definition_form"):
        kpi_key = st.text_input(
            "KPI Key",
            value=selected_key if is_edit else "",
            help="Example: productive_calls, outlet_productivity"
        )

        keywords_text = st.text_area(
            "Keywords",
            value="\n".join(existing.get("keywords", [])),
            height=120,
            help="Enter one keyword per line"
        )

        definition_text = st.text_area(
            "Definition",
            value=existing.get("definition", ""),
            height=260,
            help="Write business meaning, formula, filters, aggregation rules, and defaults"
        )

        with st.expander("📋 Definition Template"):
            st.code(
                """<KPI Name> measures ...

Calculation:
- Step 1:
- Step 2:

Filters:
- Use current month if no time period is specified.
- Apply RepCode when the question refers to a rep or says "my".

Aggregation:
- Explain whether this is single-level or multi-level aggregation.

Exclusions:
- Exclude returns unless specifically requested.
""",
                language="text"
            )

        col_save, col_cancel = st.columns([1, 1])

        with col_save:
            save_clicked = st.form_submit_button("💾 Save")

        with col_cancel:
            cancel_clicked = st.form_submit_button("Cancel")

        if save_clicked:
            if not kpi_key.strip():
                st.error("KPI key is required.")
            elif not definition_text.strip():
                st.error("Definition is required.")
            else:
                keywords = [
                    x.strip()
                    for x in keywords_text.splitlines()
                    if x.strip()
                ]

                if not keywords:
                    st.error("At least one keyword is required.")
                else:
                    saved_key = business_knowledge_store.upsert_definition(
                        key=kpi_key,
                        keywords=keywords,
                        definition=definition_text
                    )

                    st.success(f"Saved KPI definition: {saved_key}")

                    st.session_state["kb_editor_mode"] = None
                    st.session_state["selected_kpi"] = None
                    st.rerun()

        if cancel_clicked:
            st.session_state["kb_editor_mode"] = None
            st.session_state["selected_kpi"] = None
            st.rerun()

# =============================
# SESSION STATE
# =============================

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

if "last_result" not in st.session_state:
    st.session_state.last_result = None

if "query_count" not in st.session_state:
    st.session_state.query_count = 0

if "kb_editor_mode" not in st.session_state:
    st.session_state.kb_editor_mode = None

if "selected_kpi" not in st.session_state:
    st.session_state.selected_kpi = None


# =============================
# HELPERS
# =============================

def _has_analytics_payload(result: dict) -> bool:
    """True when this turn actually produced query output (ignore stale turn_action)."""
    qr = result.get("query_result")
    if isinstance(qr, list) and len(qr) > 0:
        return True
    if isinstance(qr, dict) and qr:
        return True
    if result.get("visualizations"):
        return True
    if result.get("sql_query"):
        return True
    return False


def is_non_analytics_turn(result: dict) -> bool:
    """Greeting, chitchat, or deny — no table/chart/SQL from this turn."""
    # Checkpoint can keep turn_action=chitchat from a prior hello; data wins
    if _has_analytics_payload(result):
        return False

    if result.get("error") and not result.get("final_answer") and not result.get("result_summary"):
        return False

    action = (result.get("turn_action") or "").lower()
    if action in ("chitchat", "deny"):
        return True

    q = (result.get("question") or "").strip()
    if "Follow-up:" in q:
        q = q.split("Follow-up:")[-1].strip()
    if is_social_message(q):
        return True

    return bool(result.get("final_answer") or result.get("result_summary"))


def prepare_result_for_ui(result: dict) -> dict:
    """Normalize agent result for Streamlit display and session storage."""
    out = dict(result)
    if is_non_analytics_turn(out):
        out["query_result"] = None
        out["visualizations"] = []
        out["sql_query"] = None
        out["sql_explanation"] = None
        out["plan"] = None
        out["plan_steps"] = None
        out["result_preview"] = None
        out["table_title"] = None
        return out
    if out.get("query_result") is not None:
        out["query_result"] = serialize_query_result(out["query_result"])
    return out


def _arrow_safe_cell(value):
    """Normalize a single cell for Streamlit / PyArrow (numpy, Decimal, SQL types)."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    safe = json_safe_value(value)
    if safe is None:
        return None
    if isinstance(safe, (int, float, bool, str)):
        return safe
    return str(safe)


def sanitize_df_for_streamlit(df: pd.DataFrame) -> pd.DataFrame:
    """Convert dtypes to Arrow-compatible columns for st.dataframe."""
    if df.empty:
        return df

    out = df.copy()
    out.columns = [str(c) for c in out.columns]

    for col in out.columns:
        s = out[col]
        dtype_name = str(s.dtype)

        # pandas 2.x object columns (numpy ObjectDType) break PyArrow
        if (
            pd.api.types.is_object_dtype(s)
            or "ObjectDType" in dtype_name
            or isinstance(s.dtype, pd.StringDtype)
            or dtype_name == "string"
        ):
            cleaned = s.map(_arrow_safe_cell)
            numeric = pd.to_numeric(cleaned, errors="coerce")
            if numeric.notna().sum() >= max(1, len(out) * 0.5):
                out[col] = numeric
            else:
                out[col] = cleaned.map(
                    lambda x: None if x is None else str(x)
                )
            continue

        if pd.api.types.is_datetime64_any_dtype(s) or pd.api.types.is_timedelta64_dtype(s):
            out[col] = s.map(
                lambda x: x.isoformat() if pd.notna(x) else None
            )
            continue

        if pd.api.types.is_bool_dtype(s):
            out[col] = s.astype(bool)
            continue

        if pd.api.types.is_numeric_dtype(s):
            try:
                import numpy as np
                if isinstance(s.dtype, np.dtype) and s.dtype.kind in ("i", "u", "f"):
                    out[col] = pd.to_numeric(s, errors="coerce")
            except ImportError:
                pass
            continue

        out[col] = s.map(_arrow_safe_cell)

    return out


def run_async_agent(
    question: str,
    session_id: str,
    user_role: Optional[str] = None,
    allowed_rep_codes: Optional[list] = None,
    user_id: Optional[str] = None
):
    """Execute query with user context for access control and logging."""
    
    async def execute_with_guardrails():
        # === GUARDRAILS CHECK ===
        guardrail_context = {
            "conversation_history": [],
            "previous_topics": [],
            "user_role": user_role
        }
        
        # Get conversation context from chat memory if session exists
        if session_id:
            session = chat_memory.get_session(session_id)
            if session:
                guardrail_context["conversation_history"] = session.get("messages", [])
        
        # Evaluate guardrails
        guardrail_result = await guardrail_pipeline.evaluate(
            question,
            guardrail_context
        )
        
        # If guardrails reject, return error (unless greeting — let agent handle chitchat)
        if not guardrail_result.get("passed", False):
            if not is_social_message(question):
                logger.warning(
                    f"Query rejected by guardrails: {guardrail_result.get('reason')}"
                )
                return {
                    "error": guardrail_result.get(
                        "reason", "Query rejected by safety checks"
                    ),
                    "error_type": "guardrail_rejection",
                    "waiting_for_user": False,
                    "session_id": session_id,
                }
        
        # === PROCEED TO AGENT ===
        return await run_agent_async(
            question=question,
            session_id=session_id,
            user_role=user_role,
            allowed_rep_codes=allowed_rep_codes
        )
    
    return asyncio.run(execute_with_guardrails())


def add_message(role: str, content: str, msg_type: str = "message", result: dict | None = None):
    entry = {"role": role, "content": content, "type": msg_type}
    if result is not None:
        entry["result"] = result
    st.session_state.messages.append(entry)


def format_agent_response(result: dict) -> str:
    if result.get("waiting_for_user"):
        return result.get("question_to_user", "Please provide more details.")

    if result.get("error"):
        return f"Error: {result.get('error')}"

    if result.get("result_summary"):
        return result["result_summary"]

    if result.get("final_answer"):
        return result["final_answer"]

    if result.get("result_preview"):
        return result["result_preview"]

    if result.get("query_result"):
        return "Here are your query results below."

    return "Done."


def render_agent_visualizations(result: dict, key_prefix: str):
    """Render formatter-produced Plotly charts in chat or tabs."""
    visualizations = result.get("visualizations") or []
    if not visualizations:
        return

    chart_df = prepare_chart_dataframe(result_to_dataframe(result))

    for i, viz in enumerate(visualizations):
        title = viz.get("title") or f"Chart {i + 1}"
        st.markdown(f"**{title}**")
        rendered = False

        chart_json = viz.get("chart_json")
        if chart_json:
            try:
                payload = chart_json if isinstance(chart_json, str) else json.dumps(chart_json)
                fig = pio.from_json(payload)
                st.plotly_chart(fig, width="stretch", key=f"{key_prefix}_chart_{i}")
                rendered = True
            except Exception as e:
                logger.warning(f"Plotly chart_json render failed: {e}")

        if not rendered:
            config = viz.get("visualization_config")
            if config and config.get("enabled") and not chart_df.empty:
                fig = build_chart_figure(chart_df, config, title=title)
                if fig is not None:
                    st.plotly_chart(
                        fig,
                        width="stretch",
                        key=f"{key_prefix}_chart_{i}_rebuild",
                    )
                    rendered = True

        if not rendered:
            img_b64 = viz.get("chart_image_base64")
            if img_b64:
                st.image(f"data:image/png;base64,{img_b64}", width="stretch")


def render_assistant_in_chat(result: dict, key_prefix: str):
    """Full assistant turn in chat: summary, table, graph, SQL, plan."""
    if result.get("waiting_for_user"):
        st.info(result.get("question_to_user"))
        return

    if result.get("error"):
        st.error(result.get("error"))
        return

    summary = result.get("result_summary") or result.get("final_answer")
    if summary:
        st.markdown(summary)

    if is_non_analytics_turn(result):
        return

    df = result_to_dataframe(result)
    if not df.empty:
        title = result.get("table_title") or "Results"
        with st.expander(f"📊 {title}", expanded=len(df) <= 5):
            try:
                st.dataframe(df, width="stretch", hide_index=True)
            except Exception as display_err:
                logger.warning(f"st.dataframe failed, using string fallback: {display_err}")
                st.dataframe(df.astype(str), width="stretch", hide_index=True)
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇️ Download CSV",
                data=csv,
                file_name="query_result.csv",
                mime="text/csv",
                key=f"{key_prefix}_csv",
            )

    visualizations = result.get("visualizations") or []
    if visualizations or not df.empty:
        with st.expander("📈 Graph", expanded=bool(visualizations)):
            if visualizations:
                render_agent_visualizations(result, key_prefix=key_prefix)
            elif not df.empty:
                render_dynamic_graph(
                    df=prepare_chart_dataframe(df),
                    key_prefix=f"{key_prefix}_graph",
                )

    if result.get("sql_query"):
        with st.expander("SQL", expanded=False):
            st.code(result["sql_query"], language="sql")
            st.download_button(
                label="⬇️ Download SQL",
                data=result["sql_query"],
                file_name="query.sql",
                mime="text/plain",
                key=f"{key_prefix}_sql",
            )

    plan = result.get("plan")
    plan_steps = result.get("plan_steps")
    if plan or plan_steps:
        with st.expander("Plan", expanded=False):
            if plan:
                st.text(plan)
            if plan_steps:
                for i, step in enumerate(plan_steps, 1):
                    st.markdown(f"{i}. {step}")

def result_to_dataframe(result: dict) -> pd.DataFrame:
    query_result = result.get("query_result")

    if query_result is None:
        return pd.DataFrame()

    if isinstance(query_result, str):
        return pd.DataFrame()

    if isinstance(query_result, dict):
        rows = [query_result]
    elif isinstance(query_result, list):
        rows = query_result
    else:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    try:
        first = rows[0]
        if hasattr(first, "_mapping"):
            df = pd.DataFrame([dict(row._mapping) for row in rows])
        elif isinstance(first, dict):
            df = pd.DataFrame(rows)
        else:
            return pd.DataFrame()

        # Dynamic numeric conversion (avoid pandas StringDtype — breaks Arrow)
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                continue

            cleaned = df[col].map(lambda x: "" if pd.isna(x) else str(x))
            cleaned = (
                cleaned.str.replace(",", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.strip()
            )
            converted = pd.to_numeric(cleaned, errors="coerce")

            if converted.notna().sum() >= max(1, len(df) * 0.7):
                df[col] = converted

        return sanitize_df_for_streamlit(df)

    except Exception as e:
        logger.warning(f"Failed to convert query_result to DataFrame: {e}")
        return pd.DataFrame()


def get_numeric_columns(df: pd.DataFrame):
    return df.select_dtypes(include=["number"]).columns.tolist()


def get_text_columns(df: pd.DataFrame):
    return df.select_dtypes(exclude=["number"]).columns.tolist()

def build_chart_figure(
    df: pd.DataFrame,
    config: dict,
    title: str | None = None,
) -> go.Figure | None:
    if df.empty or not config or not config.get("enabled"):
        return None

    x_col = config.get("x_column")
    y_col = config.get("y_column")
    color_col = config.get("color_column")
    chart_type = config.get("chart_type", "bar")

    if not x_col or not y_col or x_col not in df.columns or y_col not in df.columns:
        return None

    if color_col not in df.columns:
        color_col = None

    chart_df = df.copy().dropna(subset=[x_col, y_col])
    if chart_df.empty:
        return None

    if chart_type != "line":
        chart_df = chart_df.sort_values(by=y_col, ascending=False)

    if len(chart_df) > 30:
        chart_df = chart_df.head(30)

    chart_title = title or f"{y_col} by {x_col}"

    if chart_type == "horizontal_bar":
        fig = px.bar(
            chart_df.sort_values(by=y_col, ascending=True),
            x=y_col,
            y=x_col,
            color=color_col,
            orientation="h",
            text=y_col,
            title=chart_title,
        )
        fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")

    elif chart_type == "line":
        fig = px.line(
            chart_df,
            x=x_col,
            y=y_col,
            color=color_col,
            markers=True,
            title=chart_title,
        )

    elif chart_type == "pie":
        fig = px.pie(
            chart_df,
            names=x_col,
            values=y_col,
            color=color_col,
            title=chart_title,
        )

    elif chart_type == "scatter":
        fig = px.scatter(
            chart_df,
            x=x_col,
            y=y_col,
            color=color_col,
            size=y_col,
            title=chart_title,
        )

    else:
        fig = px.bar(
            chart_df,
            x=x_col,
            y=y_col,
            color=color_col,
            text=y_col,
            title=chart_title,
        )
        fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig.update_layout(xaxis_tickangle=-45)

    return fig


def render_chart_from_config(df: pd.DataFrame, config: dict):
    if df.empty:
        st.info("No data available for chart.")
        return

    if not config or not config.get("enabled"):
        st.info("No chart recommendation available.")
        return

    fig = build_chart_figure(df, config)
    if fig is None:
        st.warning("Chart columns not found in result table.")
        st.write("Available columns:", list(df.columns))
        st.write("Chart config:", config)
        return

    st.plotly_chart(fig, width="stretch")

def prepare_chart_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    chart_df = df.copy()

    # Convert common null-like values to real NaN
    null_values = ["None", "none", "NULL", "null", "NaN", "nan", "", " "]
    chart_df = chart_df.replace(null_values, pd.NA)

    # Convert numeric-looking columns safely
    for col in chart_df.columns:
        cleaned = (
            chart_df[col]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("%", "", regex=False)
            .str.strip()
        )

        converted = pd.to_numeric(cleaned, errors="coerce")

        # Convert if at least one numeric value exists
        if converted.notna().sum() > 0:
            chart_df[col] = converted

    return sanitize_df_for_streamlit(chart_df)

def get_chart_numeric_columns(df: pd.DataFrame):
    numeric_cols = []

    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            if df[col].notna().sum() > 0:
                numeric_cols.append(col)

    return numeric_cols

def render_pivot_table(df: pd.DataFrame, key_prefix: str = "pivot"):
    if df.empty:
        st.info("No data available for pivot table.")
        return

    st.markdown("### Pivot Table")

    # Detect numeric and non-numeric columns
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    all_cols = df.columns.tolist()

    if not numeric_cols:
        st.warning("No numeric columns available for pivot values.")
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        index_cols = st.multiselect(
            "Rows",
            options=all_cols,
            default=[all_cols[0]] if all_cols else [],
            key=f"{key_prefix}_index_cols"
        )

    with col2:
        column_cols = st.multiselect(
            "Columns",
            options=[c for c in all_cols if c not in index_cols],
            default=[],
            key=f"{key_prefix}_column_cols"
        )

    with col3:
        value_col = st.selectbox(
            "Values",
            options=numeric_cols,
            key=f"{key_prefix}_value_col"
        )

    with col4:
        agg_func = st.selectbox(
            "Aggregation",
            options=["sum", "mean", "count", "min", "max"],
            key=f"{key_prefix}_agg_func"
        )

    if not index_cols:
        st.warning("Please select at least one row field.")
        return

    try:
        pivot_df = pd.pivot_table(
            df,
            index=index_cols,
            columns=column_cols if column_cols else None,
            values=value_col,
            aggfunc=agg_func,
            fill_value=0,
            margins=True,
            margins_name="Total"
        )

        # Flatten multi-index columns if needed
        if isinstance(pivot_df.columns, pd.MultiIndex):
            pivot_df.columns = [
                " | ".join(str(x) for x in col if str(x) != "")
                for col in pivot_df.columns
            ]

        pivot_df = pivot_df.reset_index()

        st.dataframe(pivot_df, width="stretch")

        csv = pivot_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download Pivot CSV",
            data=csv,
            file_name="pivot_result.csv",
            mime="text/csv",
            key=f"{key_prefix}_download"
        )

    except Exception as e:
        st.error(f"Failed to create pivot table: {e}")
        
def render_dynamic_graph(df: pd.DataFrame, key_prefix: str):
    chart_df = prepare_chart_dataframe(df)

    numeric_cols = get_chart_numeric_columns(chart_df)
    non_numeric_cols = [col for col in chart_df.columns if col not in numeric_cols]

    if not numeric_cols:
        st.warning("No numeric column found for chart.")
        st.write(chart_df.dtypes)
        return

    x_default = non_numeric_cols[0] if non_numeric_cols else chart_df.columns[0]
    y_default = numeric_cols[0]

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        x_col = st.selectbox(
            "X Axis",
            options=chart_df.columns.tolist(),
            index=chart_df.columns.tolist().index(x_default),
            key=f"{key_prefix}_x"
        )

    with col_b:
        y_col = st.selectbox(
            "Y Axis",
            options=numeric_cols,
            index=numeric_cols.index(y_default),
            key=f"{key_prefix}_y"
        )

    with col_c:
        chart_type = st.selectbox(
            "Chart Type",
            options=["Bar", "Horizontal Bar", "Line", "Pie", "Scatter"],
            key=f"{key_prefix}_type"
        )

    chart_df = chart_df.dropna(subset=[x_col, y_col])

    if chart_df.empty:
        st.warning("No rows available for selected chart columns.")
        return

    row_count = len(chart_df)

    if row_count == 1:
        top_n = 1
    else:
        top_n = st.slider(
            "Rows to show",
            min_value=1,
            max_value=min(100, row_count),
            value=min(20, row_count),
            step=1,
            key=f"{key_prefix}_topn"
        )

    chart_df = chart_df.sort_values(by=y_col, ascending=False).head(top_n)

    if chart_type == "Horizontal Bar":
        fig = px.bar(
            chart_df.sort_values(by=y_col, ascending=True),
            x=y_col,
            y=x_col,
            orientation="h",
            text=y_col,
            title=f"{y_col} by {x_col}"
        )

    elif chart_type == "Line":
        fig = px.line(
            chart_df,
            x=x_col,
            y=y_col,
            markers=True,
            title=f"{y_col} by {x_col}"
        )

    elif chart_type == "Pie":
        fig = px.pie(
            chart_df,
            names=x_col,
            values=y_col,
            title=f"{y_col} share by {x_col}"
        )

    elif chart_type == "Scatter":
        fig = px.scatter(
            chart_df,
            x=x_col,
            y=y_col,
            size=y_col,
            title=f"{y_col} by {x_col}"
        )

    else:
        fig = px.bar(
            chart_df,
            x=x_col,
            y=y_col,
            text=y_col,
            title=f"{y_col} by {x_col}"
        )
        fig.update_layout(xaxis_tickangle=-45)

    st.plotly_chart(fig, width="stretch")
        
# =============================
# USER AUTHENTICATION
# =============================

if "user" not in st.session_state:
    st.session_state.user = None
    st.session_state.user_role = None
    st.session_state.allowed_rep_codes = None

# Login sidebar
with st.sidebar:
    st.subheader("👤 User Login")
    
    if st.session_state.user is None:
        user_role = st.selectbox(
            "User Role",
            options=["rep", "asm", "rsm", "customer"],
            key="login_role"
        )
        
        if user_role == "rep":
            rep_code_input = st.text_input(
                "Rep Code (e.g., MATREP001)",
                key="login_rep_code"
            )
            allowed_reps = [rep_code_input] if rep_code_input else []
            
        elif user_role == "asm":
            st.info("ASM can access multiple rep codes")
            rep_codes_text = st.text_area(
                "Rep Codes (one per line)",
                value="",
                key="login_asm_codes"
            )
            allowed_reps = [r.strip() for r in rep_codes_text.split("\n") if r.strip()]
            
        elif user_role == "rsm":
            st.info("RSM can access all rep codes")
            allowed_reps = ["ALL"]
            
        else:  # customer
            st.info("Customer has limited access")
            allowed_reps = []
        
        if st.button("Login", width="stretch"):
            if user_role == "rep" and not rep_code_input:
                st.error("Please enter Rep Code")
            else:
                st.session_state.user = f"user_{user_role}_{uuid.uuid4().hex[:8]}"
                st.session_state.user_role = user_role
                st.session_state.allowed_rep_codes = allowed_reps
                st.success(f"Logged in as {user_role}")
                st.rerun()
    
    else:
        st.success(f"✅ Logged in as: **{st.session_state.user_role.upper()}**")
        if st.session_state.allowed_rep_codes and st.session_state.allowed_rep_codes != ["ALL"]:
            st.info(f"Rep Codes: {', '.join(st.session_state.allowed_rep_codes)}")
        
        if st.button("Logout", width="stretch"):
            st.session_state.user = None
            st.session_state.user_role = None
            st.session_state.allowed_rep_codes = None
            st.rerun()

# Require login to continue
if st.session_state.user is None:
    st.warning("⚠️ Please login first")
    st.stop()

# =============================
# SIDEBAR
# =============================

with st.sidebar:
    st.header("⚙️ Session")

    st.text_input(
        "Session ID",
        value=st.session_state.session_id,
        disabled=True
    )

    if st.button("🔄 New Chat", width="stretch"):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.last_result = None
        st.session_state.query_count = 0
        st.rerun()

    st.markdown("---")

    # =============================
    # KNOWLEDGE BASE SIDEBAR
    # =============================

    st.subheader("📘 Business Knowledge Base")

    if st.button("🔄 Reload KB", width="stretch"):
        business_knowledge_store.reload()
        st.success("Knowledge base reloaded")

    if st.button("➕ Add KPI Definition", width="stretch"):
        st.session_state["kb_editor_mode"] = "add"
        st.session_state["selected_kpi"] = None

    definitions = business_knowledge_store.list_definitions()

    if not definitions:
        st.info("No KPI definitions found.")
    else:
        selected_kpi = st.selectbox(
            "Select KPI definition",
            options=list(definitions.keys()),
            key="kb_selected_kpi"
        )

        col1, col2 = st.columns(2)

        with col1:
            if st.button("✏️ Edit", width="stretch"):
                st.session_state["kb_editor_mode"] = "edit"
                st.session_state["selected_kpi"] = selected_kpi

        with col2:
            if st.button("🗑️ Delete", width="stretch"):
                business_knowledge_store.delete_definition(selected_kpi)
                st.success(f"Deleted: {selected_kpi}")
                st.rerun()

        current = definitions.get(selected_kpi, {})

        with st.expander("View Definition", expanded=False):
            st.markdown("**Keywords**")
            st.write(", ".join(current.get("keywords", [])))

            st.markdown("**Definition**")
            st.text(current.get("definition", ""))

    st.markdown("---")

    st.header("📊 Stats")
    st.metric("Queries", st.session_state.query_count)


# =============================
# CHAT HISTORY
# =============================

for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and msg.get("result"):
            render_assistant_in_chat(
                prepare_result_for_ui(msg["result"]),
                key_prefix=f"hist_{st.session_state.session_id}_{i}",
            )
        else:
            st.markdown(msg["content"])


# =============================
# CHAT INPUT
# =============================

user_question = st.chat_input("Ask a sales/business question...")

if user_question:
    add_message("user", user_question)

    with st.chat_message("user"):
        st.markdown(user_question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                result = run_async_agent(
                    question=user_question,
                    session_id=st.session_state.session_id,
                    user_role=st.session_state.user_role,             
                    allowed_rep_codes=st.session_state.allowed_rep_codes,  
                    user_id=st.session_state.user )                   

                ui_result = prepare_result_for_ui(result)
                st.session_state.last_result = ui_result
                st.session_state.query_count += 1

                assistant_text = format_agent_response(ui_result)
                render_assistant_in_chat(
                    ui_result,
                    key_prefix=f"chat_{st.session_state.session_id}_{st.session_state.query_count}",
                )

                add_message(
                    "assistant",
                    assistant_text,
                    "clarification" if ui_result.get("waiting_for_user") else "answer",
                    result=ui_result,
                )

            except Exception as e:
                logger.error(f"Streamlit app error: {e}")
                error_text = f"Unexpected error: {str(e)}"
                st.error(error_text)
                add_message("assistant", error_text, "error")
