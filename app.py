import os
import warnings
import logging

os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)

try:
    from transformers.utils import logging as transformers_logging
    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()
except Exception:
    pass

from datetime import datetime
from uuid import uuid4
import asyncio
import uuid
import streamlit as st
import pandas as pd
import plotly.express as px
from loguru import logger
from typing import Optional, Dict, Any

from src.agents.tools.business_knowledge_store import business_knowledge_store
from src.agents.tools.chat_memory import chat_memory
from ui.agent_runner import run_async_agent
from ui.user_utils import login_with_phone, login_with_system

# =============================
# PAGE CONFIG
# =============================

st.set_page_config(
    page_title="EVision Agent",
    page_icon="💬",
    layout="wide"
)

st.title("SFA SmartAnalyst")
st.caption("Your AI-Powered Sales Intelligence Assistant")
        
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

# Initialize chat memory flag
if "chat_memory_initialized" not in st.session_state:
    st.session_state.chat_memory_initialized = False

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


def add_message(
    role: str,
    content: str,
    msg_type: str = "message",
    metadata: Optional[Dict[str, Any]] = None,
    message_id: Optional[str] = None
) -> str:
    """
    Add message to Streamlit UI only.
    Backend graph owns DB/memory persistence.
    """
    message_id = message_id or str(uuid4())

    st.session_state.messages.append({
        "role": role,
        "content": content,
        "type": msg_type,
        "message_id": message_id,
        "metadata": metadata or {}
    })

    return message_id


def format_agent_response(result: dict) -> str:
    if result.get("waiting_for_user"):
        return result.get("question_to_user", "Please provide more details.")

    if result.get("error"):
        return f"{result.get('error')}"
    
    if result.get("final_answer"):
        return result.get("final_answer")

    if result.get("query_result"):
        return "Query executed successfully."

    if result.get("sql_query"):
        return "SQL generated successfully."

    return "Done."

def result_to_dataframe(result: dict) -> pd.DataFrame:
    query_result = result.get("query_result")

    if not query_result:
        return pd.DataFrame()

    try:
        if hasattr(query_result[0], "_mapping"):
            df = pd.DataFrame([dict(row._mapping) for row in query_result])
        elif isinstance(query_result[0], dict):
            df = pd.DataFrame(query_result)
        else:
            df = pd.DataFrame(query_result)

        # Dynamic numeric conversion
        for col in df.columns:
            cleaned = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.strip()
            )

            converted = pd.to_numeric(cleaned, errors="coerce")

            if converted.notna().sum() >= max(1, len(df) * 0.7):
                df[col] = converted

        return df

    except Exception as e:
        logger.warning(f"Failed to convert query_result to DataFrame: {e}")
        return pd.DataFrame()


def get_numeric_columns(df: pd.DataFrame):
    return df.select_dtypes(include=["number"]).columns.tolist()


def get_text_columns(df: pd.DataFrame):
    return df.select_dtypes(exclude=["number"]).columns.tolist()

def render_chart_from_config(df: pd.DataFrame, config: dict):
    if df.empty:
        st.info("No data available for chart.")
        return

    if not config or not config.get("enabled"):
        st.info("No chart recommendation available.")
        return

    x_col = config.get("x_column")
    y_col = config.get("y_column")
    color_col = config.get("color_column")
    chart_type = config.get("chart_type", "bar")

    if x_col not in df.columns or y_col not in df.columns:
        st.warning("Chart columns not found in result table.")
        st.write("Available columns:", list(df.columns))
        st.write("Chart config:", config)
        return

    if color_col not in df.columns:
        color_col = None

    chart_df = df.copy()

    if y_col in chart_df.columns:
        chart_df = chart_df.sort_values(by=y_col, ascending=False)

    if chart_type == "horizontal_bar":
        fig = px.bar(
            chart_df.sort_values(by=y_col, ascending=True),
            x=y_col,
            y=x_col,
            color=color_col,
            orientation="h",
            text=y_col,
            title=f"{y_col} by {x_col}"
        )
        fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")

    elif chart_type == "line":
        fig = px.line(
            chart_df,
            x=x_col,
            y=y_col,
            color=color_col,
            markers=True,
            title=f"{y_col} by {x_col}"
        )

    elif chart_type == "pie":
        fig = px.pie(
            chart_df,
            names=x_col,
            values=y_col,
            color=color_col,
            title=f"{y_col} share by {x_col}"
        )

    elif chart_type == "scatter":
        fig = px.scatter(
            chart_df,
            x=x_col,
            y=y_col,
            color=color_col,
            size=y_col,
            title=f"{y_col} by {x_col}"
        )

    else:
        fig = px.bar(
            chart_df,
            x=x_col,
            y=y_col,
            color=color_col,
            text=y_col,
            title=f"{y_col} by {x_col}"
        )
        fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig.update_layout(xaxis_tickangle=-45)

    st.plotly_chart(fig, use_container_width=True)

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

    return chart_df

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

        st.dataframe(pivot_df, use_container_width=True)

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

    st.plotly_chart(fig, use_container_width=True)
        
def render_agent_output_inline(result: dict, key_prefix: str):
    df = result_to_dataframe(result)

    if result.get("waiting_for_user"):
        st.info(result.get("question_to_user"))
        return

    if result.get("error"):
        st.error(result.get("error"))
        return

    if result.get("result_summary"):
        st.success(result["result_summary"])

    if not df.empty:
        with st.expander("📊 Result Table", expanded=True):
            st.dataframe(df, use_container_width=True)

            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇️ Download CSV",
                data=csv,
                file_name="query_result.csv",
                mime="text/csv",
                key=f"{key_prefix}_csv"
            )

    if result.get("sql_query"):
        with st.expander("SQL", expanded=False):
            st.code(result["sql_query"], language="sql")

    if result.get("plan"):
        with st.expander("Plan", expanded=False):
            st.text(result["plan"])

    if not df.empty:
        with st.expander("📈 Graph", expanded=False):
            render_dynamic_graph(
                df=df,
                key_prefix=f"{key_prefix}_graph"
            )
            
def render_message_with_feedback(message: Dict, session_id: str, user_id: str):
    message_id = message.get("message_id")
    role = message.get("role")
    content = message.get("content")
    msg_type = message.get("type")

    if role == "user":
        st.chat_message("user").write(content)
        return

    with st.chat_message("assistant"):
        if message_id and user_id and msg_type in ["answer", "clarification"]:
            col_content, col_like, col_dislike = st.columns([0.7, 0.15, 0.15])

            with col_content:
                st.write(content)

            with col_like:
                if st.button("👍", key=f"like_{message_id}", help="Like"):
                    chat_memory.save_feedback(
                        session_id=session_id,
                        user_id=user_id,
                        message_id=message_id,
                        message_type=msg_type,
                        message_content=content[:500],
                        feedback_type="like"
                    )
                    st.success("Feedback saved.")
                    st.rerun()

            with col_dislike:
                if st.button("👎", key=f"dislike_{message_id}", help="Dislike"):
                    chat_memory.save_feedback(
                        session_id=session_id,
                        user_id=user_id,
                        message_id=message_id,
                        message_type=msg_type,
                        message_content=content[:500],
                        feedback_type="dislike"
                    )
                    st.warning("Feedback saved.")
                    st.rerun()
        else:
            st.write(content)
                
                
# =============================
# USER AUTHENTICATION
# =============================

if "user" not in st.session_state:
    st.session_state.user = None
    
if "user_id" not in st.session_state:
    st.session_state.user_id = None

if "user_role" not in st.session_state:
    st.session_state.user_role = None

if "allowed_rep_codes" not in st.session_state:
    st.session_state.allowed_rep_codes = None

if "allowed_node_ids" not in st.session_state:
    st.session_state.allowed_node_ids = None

if "login_method" not in st.session_state:
    st.session_state.login_method = None

if "auth_data" not in st.session_state:
    st.session_state.auth_data = None


with st.sidebar:
    st.subheader("👤 Login")

    if st.session_state.user is None:
        login_method = st.radio(
            "Login Method",
            options=["Phone Number", "User Login"],
            horizontal=True,
            key="login_method_selector"
        )

        if login_method == "Phone Number":
            phone_no = st.text_input(
                "Phone Number",
                placeholder="0718543880",
                key="login_phone_no"
            )

            if st.button("Login", use_container_width=True):
                if not phone_no.strip():
                    st.error("Please enter phone number.")
                else:
                    try:
                        with st.spinner("Authenticating phone number..."):
                            login_context = login_with_phone(phone_no.strip())

                        if not login_context.get("success"):
                            st.error(login_context.get("error", "Login failed."))
                            st.stop()

                        allowed_rep_codes = login_context.get("allowed_rep_codes") or []

                        if not allowed_rep_codes:
                            st.error("Access denied. No allowed rep codes found.")
                            st.stop()

                        # Phone login success:
                        if login_context.get("success"):
                            st.session_state.user = login_context["display_name"]
                            st.session_state.user_id = login_context["user_id"]
                            st.session_state.user_role = login_context["user_role"]
                            st.session_state.allowed_rep_codes = login_context.get("allowed_rep_codes") or []
                            st.session_state.login_method = "phone"
                            st.session_state.auth_data = login_context.get("auth_data")
                            
                            # Initialize chat_memory session
                            chat_memory.get_or_create_session(
                                session_id=st.session_state.session_id,
                                user_id=st.session_state.user_id,
                                user_role=st.session_state.user_role
                            )
                            st.session_state.chat_memory_initialized = True
                            
                            st.success("Login successful.")
                            st.rerun()

                    except Exception as e:
                        logger.error(f"Phone login failed: {e}")
                        st.error(f"Login failed: {str(e)}")

        else:
            username = st.text_input(
                "Username",
                key="login_username"
            )

            password = st.text_input(
                "Password",
                type="password",
                key="login_password"
            )

            if st.button("Login", use_container_width=True):
                if not username.strip() or not password.strip():
                    st.error("Please enter username and password.")
                else:
                    try:
                        with st.spinner("Authenticating user..."):
                            login_context = login_with_system(
                                username.strip(),
                                password.strip()
                            )

                        if not login_context.get("success"):
                            st.error(login_context.get("error", "Login failed."))
                            st.stop()

                        allowed_rep_codes = login_context.get("allowed_rep_codes") or []

                        if not allowed_rep_codes:
                            st.error("Access denied. No allowed rep codes found.")
                            st.stop()

                        # System login success:
                        if login_context.get("success"):
                            st.session_state.user = login_context["display_name"]
                            st.session_state.user_id = login_context["user_id"]
                            st.session_state.user_role = login_context["user_role"]
                            st.session_state.allowed_rep_codes = login_context.get("allowed_rep_codes") or []
                            st.session_state.allowed_node_ids = login_context.get("allowed_node_ids")
                            st.session_state.login_method = "system"
                            st.session_state.auth_data = login_context.get("auth_data")
                            
                            # Initialize chat_memory session
                            chat_memory.get_or_create_session(
                                session_id=st.session_state.session_id,
                                user_id=st.session_state.user_id,
                                user_role=st.session_state.user_role
                            )
                            st.session_state.chat_memory_initialized = True
                            
                            st.success("Login successful.")
                            st.rerun()

                    except Exception as e:
                        logger.error(f"System login failed: {e}")
                        st.error(f"Login failed: {str(e)}")

    else:
        st.success(f"✅ Logged in as: **{st.session_state.user}**")
        st.caption(f"Role: {st.session_state.user_role or 'unknown'}")
        st.caption(f"Login method: {st.session_state.login_method}")

        if st.session_state.allowed_rep_codes:
            with st.expander("Allowed Rep Codes", expanded=False):
                st.write(", ".join(st.session_state.allowed_rep_codes))

        # if st.session_state.allowed_node_ids:
        #     with st.expander("Allowed Node IDs", expanded=False):
        #         st.write(", ".join(st.session_state.allowed_node_ids))

        # Update logout (around line 875):
        if st.button("Logout", use_container_width=True):
            st.session_state.user = None
            st.session_state.user_id = None
            st.session_state.user_role = None
            st.session_state.allowed_rep_codes = None
            st.session_state.allowed_node_ids = None
            st.session_state.login_method = None
            st.session_state.auth_data = None
            st.session_state.messages = []
            st.session_state.last_result = None
            st.session_state.query_count = 0
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.chat_memory_initialized = False  # ✅ ADD THIS
            st.rerun()


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

    if st.button("🔄 New Chat", use_container_width=True):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.chat_memory_initialized = False
        st.session_state.messages = []
        st.session_state.last_result = None
        st.session_state.query_count = 0
        st.rerun()

    st.markdown("---")
    
    # # ✅ ADD THIS: Feedback Stats
    # st.subheader("📊 Session Feedback")
    # try:
    #     stats = chat_memory.get_session_feedback_stats(st.session_state.session_id)
    #     col_a, col_b, col_c = st.columns(3)
        
    #     with col_a:
    #         st.metric("👍", stats.get("likes", 0))
    #     with col_b:
    #         st.metric("👎", stats.get("dislikes", 0))
    #     with col_c:
    #         satisfaction = stats.get("satisfaction", 0)
    #         st.metric("😊", f"{satisfaction:.0f}%")
    # except Exception as e:
    #     logger.warning(f"Error displaying feedback stats: {e}")
    
    # st.markdown("---")

    # =============================
    # KNOWLEDGE BASE SIDEBAR
    # =============================

    if st.session_state.user_role not in ["Rep", "rep"]:

        st.subheader("📘 Business Knowledge Base")

        if st.button("🔄 Reload KB", use_container_width=True):
            business_knowledge_store.reload()
            st.success("Knowledge base reloaded")

        if st.button("➕ Add KPI Definition", use_container_width=True):
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
                if st.button("✏️ Edit", use_container_width=True):
                    st.session_state["kb_editor_mode"] = "edit"
                    st.session_state["selected_kpi"] = selected_kpi

            with col2:
                if st.button("🗑️ Delete", use_container_width=True):
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


# =============================
# CHAT HISTORY
# =============================

for msg in st.session_state.messages:
    render_message_with_feedback(
        message=msg,
        session_id=st.session_state.session_id,
        user_id=st.session_state.user_id
    )


# =============================
# CHAT INPUT
# =============================

user_question = st.chat_input("Ask a sales/business question...")


if user_question:
    add_message("user", user_question, "question")

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
                    user_id=st.session_state.user_id
                )

                st.session_state.last_result = result
                st.session_state.query_count += 1

                assistant_text = format_agent_response(result)
                st.markdown(assistant_text)

                current_message_type = (
                    "clarification" if result.get("waiting_for_user") else "answer"
                )

                assistant_message_id = result.get("assistant_message_id")

                if assistant_message_id:
                    add_message(
                        "assistant",
                        assistant_text,
                        current_message_type,
                        message_id=assistant_message_id
                    )
                else:
                    add_message(
                        "assistant",
                        assistant_text,
                        current_message_type
                    )
                    logger.warning("assistant_message_id missing from backend result; feedback will not link to DB message.")

                result["message_id"] = assistant_message_id

                st.rerun()

            except Exception as e:
                logger.error(f"Streamlit app error: {e}")
                error_text = f"Unexpected error: {str(e)}"
                st.error(error_text)
                add_message("assistant", error_text, "error")
                
# =============================
# RESULT DETAILS
# =============================

result = st.session_state.last_result

if result:
    df = result_to_dataframe(result)
    
    # Check if there's any substantive output (table, SQL, or plan)
    has_table = not df.empty
    has_sql = bool(result.get("sql_query"))
    has_plan = bool(result.get("plan"))
    
    # Show tabs only if there are table results OR SQL/plan data
    if has_table or has_sql or has_plan:
        tab_table, tab_graph, tab_sql, tab_plan = st.tabs([
            "Extracted Table",
            "Graph",
            "SQL",
            "Plan"
        ])       
        with tab_table:
            if result.get("waiting_for_user"):
                st.info(result.get("question_to_user"))

            elif result.get("error"):
                st.error(result.get("error"))

            else:
                # if result.get("result_summary"):
                #     st.success(result["result_summary"])

                table_title = result.get("table_title", "Extracted Table")
                st.markdown(f"### {table_title}")

                if not df.empty:
                    # st.markdown("### Raw Result Table")
                    st.dataframe(df, use_container_width=True)
                    
                    st.markdown("---")
                    with st.expander("📊 Create Pivot Table", expanded=False):
                        render_pivot_table(
                            df,
                            key_prefix=f"pivot_{st.session_state.session_id}_{st.session_state.query_count}"
                        )

                    csv = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="⬇️ Download CSV",
                        data=csv,
                        file_name="query_result.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("No tabular result available.")

        # -----------------------------
        # GRAPH TAB
        # -----------------------------    
        with tab_graph:
            if result.get("waiting_for_user"):
                st.info("Graph will be available after the query is completed.")

            elif result.get("error"):
                st.error(result.get("error"))

            elif df.empty:
                st.info("No data available for graph.")

            else:
                st.markdown("### Graph View")

                graph_key = f"{st.session_state.session_id}_{st.session_state.query_count}"

                chart_df = prepare_chart_dataframe(df)

                numeric_cols = get_chart_numeric_columns(chart_df)
                non_numeric_cols = [
                    col for col in chart_df.columns
                    if col not in numeric_cols
                ]

                if not numeric_cols:
                    st.warning("No numeric column found for chart.")
                    st.write("Detected column types:")
                    st.write(chart_df.dtypes)
                    st.dataframe(chart_df.head(), use_container_width=True)

                else:
                    # -----------------------------
                    # Optional category filter
                    # -----------------------------
                    possible_group_cols = []

                    for col in non_numeric_cols:
                        unique_count = chart_df[col].nunique(dropna=True)

                        if 1 < unique_count <= 20:
                            possible_group_cols.append(col)

                    filter_col = None

                    if possible_group_cols:
                        filter_col = st.selectbox(
                            "Optional Filter Column",
                            options=["None"] + possible_group_cols,
                            key=f"filter_col_{graph_key}"
                        )

                        if filter_col != "None":
                            filter_values = sorted(chart_df[filter_col].dropna().unique())

                            selected_values = st.multiselect(
                                f"Filter {filter_col}",
                                options=filter_values,
                                default=filter_values,
                                key=f"filter_values_{graph_key}_{filter_col}"
                            )

                            chart_df = chart_df[chart_df[filter_col].isin(selected_values)]

                    # Recalculate numeric columns after filter
                    numeric_cols = get_chart_numeric_columns(chart_df)

                    if not numeric_cols:
                        st.warning("No numeric values available after filtering.")
                        st.dataframe(chart_df, use_container_width=True)
                    else:
                        # -----------------------------
                        # Default X axis
                        # -----------------------------
                        preferred_x_terms = [
                            "name", "rep", "customer", "outlet", "product",
                            "route", "brand", "category", "type", "date"
                        ]

                        x_default = None

                        for term in preferred_x_terms:
                            for col in non_numeric_cols:
                                if term in col.lower():
                                    x_default = col
                                    break
                            if x_default:
                                break

                        if not x_default:
                            x_default = non_numeric_cols[0] if non_numeric_cols else chart_df.columns[0]

                        # -----------------------------
                        # Default Y metric
                        # -----------------------------
                        y_default = numeric_cols[0]

                        col_a, col_b, col_c = st.columns(3)

                        with col_a:
                            x_col = st.selectbox(
                                "X Axis / Label",
                                options=chart_df.columns.tolist(),
                                index=chart_df.columns.tolist().index(x_default),
                                key=f"graph_x_col_{graph_key}"
                            )

                        with col_b:
                            y_col = st.selectbox(
                                "Y Axis / Metric",
                                options=numeric_cols,
                                index=numeric_cols.index(y_default),
                                key=f"graph_y_col_{graph_key}"
                            )

                        with col_c:
                            chart_type = st.selectbox(
                                "Chart Type",
                                options=["Auto", "Bar", "Horizontal Bar", "Line", "Pie", "Scatter"],
                                key=f"chart_type_{graph_key}"
                            )

                        # -----------------------------
                        # Remove rows where selected metric is null
                        # -----------------------------
                        chart_df = chart_df.dropna(subset=[y_col])

                        if chart_df.empty:
                            st.warning(f"No values available for selected metric: {y_col}")
                            st.dataframe(df, use_container_width=True)
                        else:
                            # Remove null labels
                            chart_df = chart_df.dropna(subset=[x_col])

                            if chart_df.empty:
                                st.warning(f"No labels available for selected X axis: {x_col}")
                                st.dataframe(df, use_container_width=True)
                            else:
                                # -----------------------------
                                # Top N
                                # -----------------------------
                                # max_n = min(100, len(chart_df))

                                # top_n = st.slider(
                                #     "Rows to show",
                                #     min_value=1,
                                #     max_value=max_n,
                                #     value=min(20, max_n),
                                #     step=1,
                                #     key=f"graph_top_n_{graph_key}"
                                # )

                                # chart_df = (
                                #     chart_df
                                #     .sort_values(by=y_col, ascending=False)
                                #     .head(top_n)
                                # )
                                
                                row_count = len(chart_df)

                                if row_count == 0:
                                    st.warning("No rows available for chart after filtering.")
                                    st.dataframe(df, use_container_width=True)
                                else:
                                    max_n = min(100, row_count)

                                    if row_count == 1:
                                        top_n = 1
                                        st.info("Only 1 row available for chart.")
                                    else:
                                        top_n = st.slider(
                                            "Rows to show",
                                            min_value=1,
                                            max_value=max_n,
                                            value=min(20, max_n),
                                            step=1,
                                            key=f"graph_top_n_{graph_key}"
                                        )

                                    chart_df = (
                                        chart_df
                                        .sort_values(by=y_col, ascending=False)
                                        .head(top_n)
                                    )

                                    # continue render chart below this block

                                # -----------------------------
                                # Auto chart type
                                # -----------------------------
                                final_chart_type = chart_type

                                if chart_type == "Auto":
                                    if len(chart_df) > 15:
                                        final_chart_type = "Horizontal Bar"
                                    else:
                                        final_chart_type = "Bar"

                                title = f"{y_col} by {x_col}"

                                # -----------------------------
                                # Render chart
                                # -----------------------------
                                if final_chart_type == "Bar":
                                    fig = px.bar(
                                        chart_df,
                                        x=x_col,
                                        y=y_col,
                                        text=y_col,
                                        title=title
                                    )
                                    fig.update_traces(
                                        texttemplate="%{text:.2f}",
                                        textposition="outside"
                                    )
                                    fig.update_layout(xaxis_tickangle=-45)
                                    st.plotly_chart(fig, use_container_width=True)

                                elif final_chart_type == "Horizontal Bar":
                                    fig = px.bar(
                                        chart_df.sort_values(by=y_col, ascending=True),
                                        x=y_col,
                                        y=x_col,
                                        text=y_col,
                                        orientation="h",
                                        title=title
                                    )
                                    fig.update_traces(
                                        texttemplate="%{text:.2f}",
                                        textposition="outside"
                                    )
                                    st.plotly_chart(fig, use_container_width=True)

                                elif final_chart_type == "Line":
                                    fig = px.line(
                                        chart_df,
                                        x=x_col,
                                        y=y_col,
                                        markers=True,
                                        title=title
                                    )
                                    fig.update_layout(xaxis_tickangle=-45)
                                    st.plotly_chart(fig, use_container_width=True)

                                elif final_chart_type == "Pie":
                                    fig = px.pie(
                                        chart_df,
                                        names=x_col,
                                        values=y_col,
                                        title=f"{y_col} share by {x_col}"
                                    )
                                    st.plotly_chart(fig, use_container_width=True)

                                elif final_chart_type == "Scatter":
                                    fig = px.scatter(
                                        chart_df,
                                        x=x_col,
                                        y=y_col,
                                        size=y_col,
                                        title=title
                                    )
                                    st.plotly_chart(fig, use_container_width=True)

                                st.markdown("### Chart Data")
                                st.dataframe(chart_df, use_container_width=True)

                                with st.expander("Detected Columns"):
                                    st.write({
                                        "numeric_columns": numeric_cols,
                                        "non_numeric_columns": non_numeric_cols,
                                        "selected_x": x_col,
                                        "selected_y": y_col,
                                        "rows_after_null_filter": len(chart_df)
                                    })
            

        # -----------------------------
        # SQL TAB
        # -----------------------------
        with tab_sql:
            # if show_sql and result.get("sql_query"):
            if result.get("sql_query"):
                st.code(result["sql_query"], language="sql")

                st.download_button(
                    "⬇️ Download SQL",
                    data=result["sql_query"],
                    file_name="query.sql",
                    mime="text/plain"
                )
            else:
                st.info("No SQL generated yet.")

        # -----------------------------
        # PLAN TAB
        # -----------------------------
        with tab_plan:
            # if show_plan and result.get("plan"):
            if result.get("plan"):
                st.text(result["plan"])
            else:
                st.info("No plan available.")