# """Streamlit web interface for the Text-to-SQL agent."""

# import streamlit as st
# import pandas as pd
# from pathlib import Path
# from loguru import logger

# from src.graph import run_agent
# from src.tools import seed_examples, semantic_cache, few_shot_retriever
# from src.core.database import db_manager
# from src.core.data_loader import DataLoader

# # Page configuration
# st.set_page_config(
#     page_title="Text-to-SQL Agent",
#     page_icon="🔍",
#     layout="wide",
#     initial_sidebar_state="expanded"
# )

# # Title
# st.title("🔍 Text-to-SQL Agent")
# st.markdown("**State-of-the-Art Multi-Agent Architecture for Complex Database Queries**")
# st.markdown("---")

# # Sidebar configuration
# with st.sidebar:
#     st.header("⚙️ Configuration")
    
#     # Database info
#     st.subheader("Database")
#     tables = db_manager.get_all_table_names()
#     st.info(f"Connected: {len(tables)} tables")
    
#     with st.expander("View Tables"):
#         for table in tables:
#             st.text(f"• {table}")
    
#     st.markdown("---")
    
#     # Agent settings
#     st.subheader("Agent Settings")
    
#     show_plan = st.checkbox("Show Query Plan", value=True)
#     show_schema = st.checkbox("Show Selected Schema", value=False)
#     show_iterations = st.checkbox("Show Correction Iterations", value=True)
    
#     st.markdown("---")
    
#     # Tools
#     st.subheader("Tools")
    
#     if st.button("🌱 Seed Examples"):
#         with st.spinner("Seeding example queries..."):
#             seed_examples()
#         st.success("Examples seeded!")
    
#     if st.button("🗑️ Clear Cache"):
#         semantic_cache.clear()
#         st.success("Cache cleared!")
    
#     if st.button("📚 Add Custom Example"):
#         st.session_state['show_example_form'] = True
    
#     # File Upload Section
#     st.markdown("---")
#     st.subheader("📁 Upload Data")
    
#     with st.expander("Upload CSV/Excel Files"):
#         uploaded_files = st.file_uploader(
#             "Choose files",
#             type=['csv', 'xlsx', 'xls'],
#             accept_multiple_files=True
#         )
        
#         if uploaded_files and st.button("🚀 Load Files"):
#             import tempfile
#             loader = DataLoader(db_path="./data/database.db")
            
#             with st.spinner("Loading files..."):
#                 for uploaded_file in uploaded_files:
#                     try:
#                         with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
#                             tmp_file.write(uploaded_file.read())
#                             stats = loader.load_file(tmp_file.name, if_exists='replace')
#                             st.success(f"✓ {stats['table_name']}: {stats['rows']} rows")
#                             Path(tmp_file.name).unlink()
#                     except Exception as e:
#                         st.error(f"Error: {e}")
#                 db_manager.__init__()
#                 st.rerun()
    
#     st.markdown("---")
    
#     # Stats
#     st.subheader("📊 Stats")
#     if 'query_count' not in st.session_state:
#         st.session_state['query_count'] = 0
#     st.metric("Queries Run", st.session_state['query_count'])

# # Main content
# col1, col2 = st.columns([2, 1])

# with col1:
#     st.subheader("💬 Ask Your Question")
    
#     # Example questions
#     st.markdown("**Example Questions:**")
#     examples = [
#         "What is the total revenue by product category?",
#         "Show me the top 5 customers by purchase amount",
#         "Calculate the month-over-month growth in sales",
#         "Which products have never been ordered?"
#     ]
    
#     example_cols = st.columns(2)
#     for i, example in enumerate(examples):
#         with example_cols[i % 2]:
#             if st.button(example, key=f"ex_{i}"):
#                 st.session_state['question'] = example
    
#     # Question input
#     question = st.text_area(
#         "Enter your question:",
#         value=st.session_state.get('question', ''),
#         height=100,
#         key='question_input'
#     )
    
#     col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 3])
    
#     with col_btn1:
#         submit = st.button("🚀 Run Query", type="primary", use_container_width=True)
    
#     with col_btn2:
#         clear = st.button("🔄 Clear", use_container_width=True)
#         if clear:
#             st.session_state['question'] = ''
#             st.rerun()

# with col2:
#     st.subheader("ℹ️ About")
#     st.markdown("""
#     This agent uses a multi-stage DRGC pipeline:
    
#     1. **📋 Planner**: Decomposes the question
#     2. **🔍 Schema Linker**: Finds relevant tables
#     3. **⚙️ Generator**: Writes SQL with CoT
#     4. **✅ Critic**: Validates and self-corrects
    
#     **Features:**
#     - Semantic caching
#     - Dynamic few-shot learning
#     - Execution-guided error correction
#     - Support for complex nested queries
#     """)

# # Process query
# if submit and question:
#     st.session_state['query_count'] += 1
    
#     with st.spinner("🤖 Agent is working..."):
#         try:
#             # Run the agent
#             result = run_agent(question)
            
#             # Display results
#             st.markdown("---")
#             st.subheader("📊 Results")
            
#             # Success/Error indicator
#             if result.get('error'):
#                 st.error(f"❌ **Error**: {result['error']}")
#             else:
#                 st.success("✅ **Query Successful**")
            
#             # Tabs for different views
#             tab1, tab2, tab3, tab4 = st.tabs(["SQL Query", "Results", "Execution Details", "Agent Trace"])
            
#             with tab1:
#                 st.markdown("**Generated SQL:**")
#                 sql = result.get('sql_query', 'N/A')
#                 st.code(sql, language='sql')
                
#                 # Copy button (simulated)
#                 if sql != 'N/A':
#                     st.download_button(
#                         label="📋 Copy SQL",
#                         data=sql,
#                         file_name="query.sql",
#                         mime="text/plain"
#                     )
            
#             with tab2:
#                 if result.get('error'):
#                     st.error(result['error'])
#                 else:
#                     result_preview = result.get('result_preview', 'No results')
#                     st.text(result_preview)
                    
#                     # Try to display as dataframe
#                     query_result = result.get('query_result')
#                     if query_result and isinstance(query_result, list):
#                         try:
#                             if hasattr(query_result[0], '_mapping'):
#                                 df = pd.DataFrame([dict(row._mapping) for row in query_result])
#                                 st.dataframe(df, use_container_width=True)
#                         except:
#                             pass
            
#             with tab3:
#                 metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
                
#                 with metrics_col1:
#                     exec_time = result.get('execution_time_ms', 0)
#                     st.metric("Execution Time", f"{exec_time:.2f}ms" if exec_time else "N/A")
                
#                 with metrics_col2:
#                     total_time = result.get('total_latency_ms', 0)
#                     st.metric("Total Latency", f"{total_time:.2f}ms" if total_time else "N/A")
                
#                 with metrics_col3:
#                     iterations = result.get('iterations', 0)
#                     st.metric("Correction Iterations", iterations)
                
#                 st.markdown("---")
                
#                 # Cache hit
#                 if result.get('cache_hit'):
#                     st.info("⚡ **Cache Hit** - Result retrieved from semantic cache")
                
#                 # Selected tables
#                 if show_schema and result.get('relevant_tables'):
#                     st.markdown("**Selected Tables:**")
#                     st.write(", ".join(result['relevant_tables']))
            
#             with tab4:
#                 if show_plan and result.get('plan'):
#                     st.markdown("**📋 Logical Plan:**")
#                     st.text(result['plan'])
#                     st.markdown("---")
                
#                 if show_iterations and result.get('iterations', 0) > 0:
#                     st.markdown(f"**🔄 Self-Correction:** {result['iterations']} iteration(s)")
#                     if result.get('error_type'):
#                         st.text(f"Error Type: {result['error_type']}")
                
#                 if result.get('few_shot_examples'):
#                     st.markdown("**📚 Retrieved Examples:**")
#                     st.text(f"Used {len(result['few_shot_examples'])} similar examples")
        
#         except Exception as e:
#             st.error(f"An error occurred: {str(e)}")
#             logger.error(f"Streamlit error: {e}")

# # Custom example form
# if st.session_state.get('show_example_form', False):
#     st.markdown("---")
#     st.subheader("➕ Add Custom Example")
    
#     with st.form("example_form"):
#         ex_question = st.text_input("Question")
#         ex_sql = st.text_area("SQL", height=150)
#         ex_complexity = st.selectbox("Complexity", ["simple", "medium", "complex"])
        
#         col1, col2 = st.columns([1, 4])
#         with col1:
#             submit_ex = st.form_submit_button("Add")
#         with col2:
#             cancel_ex = st.form_submit_button("Cancel")
        
#         if submit_ex and ex_question and ex_sql:
#             few_shot_retriever.add_example(
#                 question=ex_question,
#                 sql=ex_sql,
#                 complexity=ex_complexity
#             )
#             st.success("Example added!")
#             st.session_state['show_example_form'] = False
#             st.rerun()
        
#         if cancel_ex:
#             st.session_state['show_example_form'] = False
#             st.rerun()

# # Footer
# st.markdown("---")
# st.markdown("<div style='text-align: center; color: gray;'><small>Multi-Agent Text-to-SQL System powered by LangGraph & Groq</small></div>", unsafe_allow_html=True)


"""
Streamlit chat interface for Text-to-SQL agent.
Uses current async LangGraph workflow: run_agent_async(question, session_id).
"""

# import asyncio
# import uuid
# import streamlit as st
# import pandas as pd
# from loguru import logger

# from src.graph import run_agent_async
# from src.core.database import db_manager
# import yaml
# from src.tools.business_knowledge_store import business_knowledge_store

# # =============================
# # PAGE CONFIG
# # =============================

# st.set_page_config(
#     page_title="Text-to-SQL Agent",
#     page_icon="💬",
#     layout="wide"
# )

# st.title("💬 Text-to-SQL Agent")
# st.caption("Conversational BI assistant powered by LangGraph")


# # =============================
# # SESSION STATE
# # =============================

# if "session_id" not in st.session_state:
#     st.session_state.session_id = str(uuid.uuid4())

# if "messages" not in st.session_state:
#     st.session_state.messages = []

# if "last_result" not in st.session_state:
#     st.session_state.last_result = None

# if "query_count" not in st.session_state:
#     st.session_state.query_count = 0


# # =============================
# # SIDEBAR
# # =============================

# with st.sidebar:
#     st.header("⚙️ Session")

#     st.text_input(
#         "Session ID",
#         value=st.session_state.session_id,
#         disabled=True
#     )

#     if st.button("🔄 New Chat", use_container_width=True):
#         st.session_state.session_id = str(uuid.uuid4())
#         st.session_state.messages = []
#         st.session_state.last_result = None
#         st.session_state.query_count = 0
#         st.rerun()
        
#     st.markdown("---")
#     st.subheader("📘 Business Knowledge Base")
    
#     if st.button("🔄 Reload KB", use_container_width=True):
#         business_knowledge_store.reload()
#         st.success("Knowledge base reloaded")

#     if st.button("➕ Add KPI Definition", use_container_width=True):
#         st.session_state["kb_editor_mode"] = "add"
#         st.session_state["selected_kpi"] = None

#     definitions = business_knowledge_store.list_definitions()

#     if not definitions:
#         st.info("No KPI definitions found.")
#     else:
#         selected_kpi = st.selectbox(
#             "Select KPI definition",
#             options=list(definitions.keys()),
#             key="kb_selected_kpi"
#         )

#         col1, col2, col3 = st.columns([1, 1, 4])

#         with col1:
#             if st.button("✏️ Edit", use_container_width=True):
#                 st.session_state["kb_editor_mode"] = "edit"
#                 st.session_state["selected_kpi"] = selected_kpi

#         with col2:
#             if st.button("🗑️ Delete", use_container_width=True):
#                 business_knowledge_store.delete_definition(selected_kpi)
#                 st.success(f"Deleted: {selected_kpi}")
#                 st.rerun()

#         current = definitions.get(selected_kpi, {})

#         with st.expander("View Definition", expanded=False):
#             st.markdown("**Keywords**")
#             st.write(", ".join(current.get("keywords", [])))

#             st.markdown("**Definition**")
#             st.text(current.get("definition", ""))
#     st.markdown("---")

#     st.header("🗄️ Database")

#     try:
#         tables = db_manager.get_all_table_names()
#         st.success(f"Connected: {len(tables)} tables")

#         with st.expander("View Tables"):
#             for table in tables:
#                 st.text(f"• {table}")

#     except Exception as e:
#         st.error(f"Database error: {e}")

#     st.markdown("---")

#     st.header("📊 Stats")
#     st.metric("Queries", st.session_state.query_count)

#     st.markdown("---")

#     show_plan = st.checkbox("Show Plan", value=True)
#     show_sql = st.checkbox("Show SQL", value=True)
#     show_debug = st.checkbox("Show Debug State", value=False)


# # =============================
# # HELPER
# # =============================

# def run_async_agent(question: str, session_id: str):
#     """
#     Runs async agent from Streamlit safely.
#     """
#     return asyncio.run(
#         run_agent_async(
#             question=question,
#             session_id=session_id
#         )
#     )


# def add_message(role: str, content: str, msg_type: str = "message"):
#     st.session_state.messages.append({
#         "role": role,
#         "content": content,
#         "type": msg_type
#     })


# def format_agent_response(result: dict) -> str:
#     if result.get("waiting_for_user"):
#         return result.get("question_to_user", "Please provide more details.")

#     if result.get("error"):
#         return f"Error: {result.get('error')}"

#     if result.get("result_preview"):
#         return str(result.get("result_preview"))

#     if result.get("sql_query"):
#         return "Query generated successfully."

#     if result.get("final_answer"):
#         return result.get("final_answer")

#     return "Done."


# # =============================
# # CHAT HISTORY
# # =============================

# for msg in st.session_state.messages:
#     with st.chat_message(msg["role"]):
#         st.markdown(msg["content"])


# # =============================
# # CHAT INPUT
# # =============================

# user_question = st.chat_input("Ask a sales/business question...")

# if user_question:
#     add_message("user", user_question)

#     with st.chat_message("user"):
#         st.markdown(user_question)

#     with st.chat_message("assistant"):
#         with st.spinner("Thinking..."):
#             try:
#                 result = run_async_agent(
#                     question=user_question,
#                     session_id=st.session_state.session_id
#                 )

#                 st.session_state.last_result = result
#                 st.session_state.query_count += 1

#                 assistant_text = format_agent_response(result)

#                 st.markdown(assistant_text)

#                 add_message(
#                     "assistant",
#                     assistant_text,
#                     "clarification" if result.get("waiting_for_user") else "answer"
#                 )

#             except Exception as e:
#                 logger.error(f"Streamlit app error: {e}")
#                 error_text = f"Unexpected error: {str(e)}"
#                 st.error(error_text)
#                 add_message("assistant", error_text, "error")


# # =============================
# # RESULT DETAILS
# # =============================

# result = st.session_state.last_result

# if result:
#     st.markdown("---")
#     st.subheader("Agent Output")

#     tab1, tab2, tab3, tab4 = st.tabs([
#         "Result",
#         "SQL",
#         "Plan",
#         "Debug"
#     ])

#     with tab1:
#         if result.get("waiting_for_user"):
#             st.info(result.get("question_to_user"))

#         elif result.get("error"):
#             st.error(result.get("error"))

#         else:
#             result_preview = result.get("result_preview")

#             if result_preview:
#                 st.text(result_preview)
#             else:
#                 st.info("No result preview available.")

#             query_result = result.get("query_result")

#             if query_result and isinstance(query_result, list):
#                 try:
#                     if len(query_result) > 0 and hasattr(query_result[0], "_mapping"):
#                         df = pd.DataFrame([dict(row._mapping) for row in query_result])
#                         st.dataframe(df, use_container_width=True)
#                 except Exception:
#                     pass

#     with tab2:
#         if show_sql and result.get("sql_query"):
#             st.code(result["sql_query"], language="sql")

#             st.download_button(
#                 "Download SQL",
#                 data=result["sql_query"],
#                 file_name="query.sql",
#                 mime="text/plain"
#             )
#         else:
#             st.info("No SQL generated yet.")

#     with tab3:
#         if show_plan and result.get("plan"):
#             st.text(result["plan"])
#         else:
#             st.info("No plan available.")

#     with tab4:
#         if show_debug:
#             st.json(result)
#         else:
#             debug_summary = {
#                 "session_id": result.get("session_id"),
#                 "waiting_for_user": result.get("waiting_for_user"),
#                 "question_to_user": result.get("question_to_user"),
#                 "gap_type": result.get("gap_type"),
#                 "gap_reason": result.get("gap_reason"),
#                 "confidence": result.get("confidence"),
#                 "relevant_tables": result.get("relevant_tables"),
#                 "iterations": result.get("iterations"),
#                 "execution_time_ms": result.get("execution_time_ms"),
#                 "total_latency_ms": result.get("total_latency_ms"),
#                 "cache_hit": result.get("cache_hit")
#             }

#             st.json(debug_summary)
            
# mode = st.session_state.get("kb_editor_mode")

# if mode in ["add", "edit"]:
#     st.markdown("---")

#     is_edit = mode == "edit"
#     selected_key = st.session_state.get("selected_kpi")

#     existing = {}
#     if is_edit and selected_key:
#         existing = business_knowledge_store.get_definition(selected_key) or {}

#     st.subheader("✏️ Edit KPI Definition" if is_edit else "➕ Add KPI Definition")

#     with st.form("kb_definition_form"):
#         kpi_key = st.text_input(
#             "KPI Key",
#             value=selected_key if is_edit else "",
#             help="Example: productive_calls, outlet_productivity"
#         )

#         keywords_text = st.text_area(
#             "Keywords",
#             value="\n".join(existing.get("keywords", [])),
#             height=120,
#             help="Enter one keyword per line"
#         )

#         definition_text = st.text_area(
#             "Definition",
#             value=existing.get("definition", ""),
#             height=220,
#             help="Write business meaning, formula, filters, aggregation rules, and defaults"
#         )

#         col_save, col_cancel = st.columns([1, 1])

#         with col_save:
#             save_clicked = st.form_submit_button("💾 Save")

#         with col_cancel:
#             cancel_clicked = st.form_submit_button("Cancel")

#         if save_clicked:
#             if not kpi_key.strip():
#                 st.error("KPI key is required.")
#             elif not definition_text.strip():
#                 st.error("Definition is required.")
#             else:
#                 keywords = [
#                     x.strip()
#                     for x in keywords_text.splitlines()
#                     if x.strip()
#                 ]

#                 if not keywords:
#                     st.error("At least one keyword is required.")
#                 else:
#                     saved_key = business_knowledge_store.upsert_definition(
#                         key=kpi_key,
#                         keywords=keywords,
#                         definition=definition_text
#                     )

#                     st.success(f"Saved KPI definition: {saved_key}")

#                     st.session_state["kb_editor_mode"] = None
#                     st.session_state["selected_kpi"] = None
#                     st.rerun()

#         if cancel_clicked:
#             st.session_state["kb_editor_mode"] = None
#             st.session_state["selected_kpi"] = None
#             st.rerun()


"""
Streamlit chat interface for Text-to-SQL agent.
Includes:
- Chat UI
- Knowledge Base YAML editor
- Result table
- Graph view
- SQL / Plan / Debug tabs
"""

import asyncio
import uuid
import streamlit as st
import pandas as pd
import plotly.express as px
from loguru import logger

from src.graph import run_agent_async
from src.core.database import db_manager
from src.tools.business_knowledge_store import business_knowledge_store


# =============================
# PAGE CONFIG
# =============================

st.set_page_config(
    page_title="Text-to-SQL Agent",
    page_icon="💬",
    layout="wide"
)

st.title("💬 Text-to-SQL Agent")
st.caption("Conversational BI assistant powered by LangGraph")


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

def run_async_agent(question: str, session_id: str):
    return asyncio.run(
        run_agent_async(
            question=question,
            session_id=session_id
        )
    )


def add_message(role: str, content: str, msg_type: str = "message"):
    st.session_state.messages.append({
        "role": role,
        "content": content,
        "type": msg_type
    })


def format_agent_response(result: dict) -> str:
    if result.get("waiting_for_user"):
        return result.get("question_to_user", "Please provide more details.")

    if result.get("error"):
        return f"Error: {result.get('error')}"

    if result.get("query_result"):
        return "Query executed successfully."

    if result.get("sql_query"):
        return "SQL generated successfully."

    if result.get("final_answer"):
        return result.get("final_answer")

    return "Done."


# def result_to_dataframe(result: dict) -> pd.DataFrame:
#     query_result = result.get("query_result")

#     if not query_result:
#         return pd.DataFrame()

#     try:
#         # SQLAlchemy Row objects
#         if hasattr(query_result[0], "_mapping"):
#             return pd.DataFrame([dict(row._mapping) for row in query_result])

#         # List of dictionaries
#         if isinstance(query_result[0], dict):
#             return pd.DataFrame(query_result)

#         # List of tuples fallback
#         return pd.DataFrame(query_result)

#     except Exception as e:
#         logger.warning(f"Failed to convert query_result to DataFrame: {e}")
#         return pd.DataFrame()

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
        st.session_state.messages = []
        st.session_state.last_result = None
        st.session_state.query_count = 0
        st.rerun()

    st.markdown("---")

    # =============================
    # KNOWLEDGE BASE SIDEBAR
    # =============================

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
    # DATABASE
    # =============================

    st.header("🗄️ Database")

    try:
        tables = db_manager.get_all_table_names()
        st.success(f"Connected: {len(tables)} tables")

        with st.expander("View Tables"):
            for table in tables:
                st.text(f"• {table}")

    except Exception as e:
        st.error(f"Database error: {e}")

    st.markdown("---")

    st.header("📊 Stats")
    st.metric("Queries", st.session_state.query_count)

    st.markdown("---")

    show_plan = st.checkbox("Show Plan", value=True)
    show_sql = st.checkbox("Show SQL", value=True)
    show_debug = st.checkbox("Show Debug State", value=False)


# =============================
# CHAT HISTORY
# =============================

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
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
                    session_id=st.session_state.session_id
                )

                st.session_state.last_result = result
                st.session_state.query_count += 1

                assistant_text = format_agent_response(result)
                st.markdown(assistant_text)

                add_message(
                    "assistant",
                    assistant_text,
                    "clarification" if result.get("waiting_for_user") else "answer"
                )

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
    st.markdown("---")
    st.subheader("Agent Output")

    tab_table, tab_graph, tab_sql, tab_plan, tab_debug = st.tabs([
        "Extracted Table",
        "Graph",
        "SQL",
        "Plan",
        "Debug"
    ])

    df = result_to_dataframe(result)

    # -----------------------------
    # TABLE TAB
    # -----------------------------
    with tab_table:
        if result.get("waiting_for_user"):
            st.info(result.get("question_to_user"))

        elif result.get("error"):
            st.error(result.get("error"))

        else:
            if not df.empty:
                st.markdown("### Extracted Table")
                st.dataframe(df, use_container_width=True)

                csv = df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="⬇️ Download CSV",
                    data=csv,
                    file_name="query_result.csv",
                    mime="text/csv"
                )
            else:
                st.info("No tabular result available.")

                if result.get("result_preview"):
                    st.markdown("### Result Preview")
                    st.text(result.get("result_preview"))

    # # -----------------------------
    # # GRAPH TAB
    # # -----------------------------
    # with tab_graph:
    #     if result.get("waiting_for_user"):
    #         st.info("Graph will be available after the query is completed.")

    #     elif result.get("error"):
    #         st.error(result.get("error"))

    #     elif df.empty:
    #         st.info("No data available for graph.")

    #     else:
    #         st.markdown("### Graph View")

    #         numeric_cols = get_numeric_columns(df)
    #         text_cols = get_text_columns(df)

    #         if not numeric_cols:
    #             st.warning("No numeric column found for chart.")
    #         else:
    #             all_cols = df.columns.tolist()

    #             default_x_index = 0
    #             if text_cols:
    #                 default_x_index = all_cols.index(text_cols[0])

    #             x_col = st.selectbox(
    #                 "X Axis",
    #                 options=all_cols,
    #                 index=default_x_index,
    #                 key="graph_x_col"
    #             )

    #             y_col = st.selectbox(
    #                 "Y Axis",
    #                 options=numeric_cols,
    #                 key="graph_y_col"
    #             )

    #             chart_type = st.selectbox(
    #                 "Chart Type",
    #                 options=["Bar", "Line", "Pie"],
    #                 key="chart_type"
    #             )

    #             chart_df = df.copy()

    #             # Try sorting chart by Y value for better readability
    #             try:
    #                 chart_df = chart_df.sort_values(by=y_col, ascending=False)
    #             except Exception:
    #                 pass

    #             if chart_type == "Bar":
    #                 fig = px.bar(
    #                     chart_df,
    #                     x=x_col,
    #                     y=y_col,
    #                     text=y_col,
    #                     title=f"{y_col} by {x_col}"
    #                 )
    #                 fig.update_traces(textposition="outside")
    #                 st.plotly_chart(fig, use_container_width=True)

    #             elif chart_type == "Line":
    #                 fig = px.line(
    #                     chart_df,
    #                     x=x_col,
    #                     y=y_col,
    #                     markers=True,
    #                     title=f"{y_col} by {x_col}"
    #                 )
    #                 st.plotly_chart(fig, use_container_width=True)

    #             elif chart_type == "Pie":
    #                 fig = px.pie(
    #                     chart_df,
    #                     names=x_col,
    #                     values=y_col,
    #                     title=f"{y_col} share by {x_col}"
    #                 )
    #                 st.plotly_chart(fig, use_container_width=True)
    
    with tab_graph:
        if result.get("waiting_for_user"):
            st.info("Graph will be available after the query is completed.")

        elif result.get("error"):
            st.error(result.get("error"))

        elif df.empty:
            st.info("No data available for graph.")

        else:
            st.markdown("### Graph View")

            # -----------------------------
            # Convert numeric-looking columns
            # -----------------------------
            chart_df = df.copy()

            for col in chart_df.columns:
                cleaned = (
                    chart_df[col]
                    .astype(str)
                    .str.replace(",", "", regex=False)
                    .str.replace("%", "", regex=False)
                    .str.strip()
                )

                converted = pd.to_numeric(cleaned, errors="coerce")

                # Convert only if most values are numeric
                if converted.notna().sum() >= max(1, len(chart_df) * 0.7):
                    chart_df[col] = converted

            numeric_cols = chart_df.select_dtypes(include=["number"]).columns.tolist()
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
                # Dynamic default X axis
                # -----------------------------
                preferred_x_names = [
                    "name", "customername", "customer_name", "outlet",
                    "outletname", "repname", "rep_name", "repcode",
                    "productname", "product_name", "route", "brand",
                    "category", "type", "date"
                ]

                x_default = None

                for preferred in preferred_x_names:
                    for col in non_numeric_cols:
                        normalized = col.lower().replace(" ", "").replace("_", "")
                        if normalized == preferred.replace("_", ""):
                            x_default = col
                            break
                    if x_default:
                        break

                if not x_default:
                    x_default = non_numeric_cols[0] if non_numeric_cols else chart_df.columns[0]

                # -----------------------------
                # Dynamic default Y metric
                # -----------------------------
                preferred_y_terms = [
                    "percentage", "percent", "pct", "achievement",
                    "sales", "target", "value", "amount", "qty",
                    "quantity", "volume", "count", "calls", "visits"
                ]

                y_default = None

                for term in preferred_y_terms:
                    for col in numeric_cols:
                        if term in col.lower():
                            y_default = col
                            break
                    if y_default:
                        break

                if not y_default:
                    y_default = numeric_cols[0]

                # -----------------------------
                # Dynamic color/group column
                # -----------------------------
                possible_group_cols = []

                for col in non_numeric_cols:
                    unique_count = chart_df[col].nunique(dropna=True)

                    # Good grouping column: not too many unique values
                    if 1 < unique_count <= 10 and col != x_default:
                        possible_group_cols.append(col)

                # -----------------------------
                # Controls
                # -----------------------------
                col_a, col_b, col_c = st.columns(3)

                with col_a:
                    x_col = st.selectbox(
                        "X Axis / Label",
                        options=chart_df.columns.tolist(),
                        index=chart_df.columns.tolist().index(x_default),
                        key="graph_x_col"
                    )

                with col_b:
                    y_col = st.selectbox(
                        "Y Axis / Metric",
                        options=numeric_cols,
                        index=numeric_cols.index(y_default),
                        key="graph_y_col"
                    )

                with col_c:
                    chart_type = st.selectbox(
                        "Chart Type",
                        options=["Auto", "Bar", "Horizontal Bar", "Line", "Pie", "Scatter"],
                        key="chart_type"
                    )

                color_col = None

                if possible_group_cols:
                    color_options = ["None"] + possible_group_cols
                    selected_color = st.selectbox(
                        "Group / Color By",
                        options=color_options,
                        key="graph_color_col"
                    )

                    if selected_color != "None":
                        color_col = selected_color

                        selected_groups = st.multiselect(
                            f"Filter {color_col}",
                            options=sorted(chart_df[color_col].dropna().unique()),
                            default=sorted(chart_df[color_col].dropna().unique())
                        )

                        chart_df = chart_df[chart_df[color_col].isin(selected_groups)]

                # -----------------------------
                # Top N control
                # -----------------------------
                if len(chart_df) > 1:
                    max_n = min(100, len(chart_df))
                    top_n = st.slider(
                        "Rows to show",
                        min_value=1,
                        max_value=max_n,
                        value=min(20, max_n),
                        step=1
                    )
                else:
                    top_n = len(chart_df)

                # Sort by selected metric
                chart_df = chart_df.sort_values(by=y_col, ascending=False).head(top_n)

                # -----------------------------
                # Auto chart type
                # -----------------------------
                final_chart_type = chart_type

                if chart_type == "Auto":
                    if len(chart_df) <= 8 and chart_df[x_col].nunique() <= 8:
                        final_chart_type = "Bar"
                    elif len(chart_df) > 15:
                        final_chart_type = "Horizontal Bar"
                    else:
                        final_chart_type = "Bar"

                # -----------------------------
                # Render chart
                # -----------------------------
                title = f"{y_col} by {x_col}"

                if final_chart_type == "Bar":
                    fig = px.bar(
                        chart_df,
                        x=x_col,
                        y=y_col,
                        color=color_col,
                        text=y_col,
                        title=title
                    )
                    fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
                    fig.update_layout(xaxis_tickangle=-45)
                    st.plotly_chart(fig, use_container_width=True)

                elif final_chart_type == "Horizontal Bar":
                    fig = px.bar(
                        chart_df.sort_values(by=y_col, ascending=True),
                        x=y_col,
                        y=x_col,
                        color=color_col,
                        text=y_col,
                        orientation="h",
                        title=title
                    )
                    fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
                    st.plotly_chart(fig, use_container_width=True)

                elif final_chart_type == "Line":
                    fig = px.line(
                        chart_df,
                        x=x_col,
                        y=y_col,
                        color=color_col,
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
                        color=color_col,
                        title=f"{y_col} share by {x_col}"
                    )
                    st.plotly_chart(fig, use_container_width=True)

                elif final_chart_type == "Scatter":
                    fig = px.scatter(
                        chart_df,
                        x=x_col,
                        y=y_col,
                        color=color_col,
                        size=y_col if y_col in numeric_cols else None,
                        title=title
                    )
                    st.plotly_chart(fig, use_container_width=True)

                st.markdown("### Chart Data")
                st.dataframe(chart_df, use_container_width=True)

                with st.expander("Detected Columns"):
                    st.write({
                        "numeric_columns": numeric_cols,
                        "non_numeric_columns": non_numeric_cols,
                        "default_x": x_default,
                        "default_y": y_default,
                        "group_columns": possible_group_cols
                    })

    # -----------------------------
    # SQL TAB
    # -----------------------------
    with tab_sql:
        if show_sql and result.get("sql_query"):
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
        if show_plan and result.get("plan"):
            st.text(result["plan"])
        else:
            st.info("No plan available.")

    # -----------------------------
    # DEBUG TAB
    # -----------------------------
    with tab_debug:
        debug_summary = {
            "session_id": result.get("session_id"),
            "waiting_for_user": result.get("waiting_for_user"),
            "question_to_user": result.get("question_to_user"),
            "gap_type": result.get("gap_type"),
            "gap_reason": result.get("gap_reason"),
            "confidence": result.get("confidence"),
            "relevant_tables": result.get("relevant_tables"),
            "iterations": result.get("iterations"),
            "execution_time_ms": result.get("execution_time_ms"),
            "total_latency_ms": result.get("total_latency_ms"),
            "cache_hit": result.get("cache_hit")
        }

        if show_debug:
            st.json(result)
        else:
            st.json(debug_summary)


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
# RAW YAML PREVIEW
# =============================

with st.expander("🧾 Raw Knowledge YAML Preview"):
    try:
        import yaml

        yaml_text = yaml.safe_dump(
            {"definitions": business_knowledge_store.list_definitions()},
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False
        )

        st.code(yaml_text, language="yaml")

    except Exception as e:
        st.error(f"Failed to show YAML preview: {e}")