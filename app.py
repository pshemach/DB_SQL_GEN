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

import asyncio
import uuid
import streamlit as st
import pandas as pd
from loguru import logger

from src.graph import run_agent_async
from src.core.database import db_manager


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
# HELPER
# =============================

def run_async_agent(question: str, session_id: str):
    """
    Runs async agent from Streamlit safely.
    """
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

    if result.get("result_preview"):
        return str(result.get("result_preview"))

    if result.get("sql_query"):
        return "Query generated successfully."

    if result.get("final_answer"):
        return result.get("final_answer")

    return "Done."


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

    tab1, tab2, tab3, tab4 = st.tabs([
        "Result",
        "SQL",
        "Plan",
        "Debug"
    ])

    with tab1:
        if result.get("waiting_for_user"):
            st.info(result.get("question_to_user"))

        elif result.get("error"):
            st.error(result.get("error"))

        else:
            result_preview = result.get("result_preview")

            if result_preview:
                st.text(result_preview)
            else:
                st.info("No result preview available.")

            query_result = result.get("query_result")

            if query_result and isinstance(query_result, list):
                try:
                    if len(query_result) > 0 and hasattr(query_result[0], "_mapping"):
                        df = pd.DataFrame([dict(row._mapping) for row in query_result])
                        st.dataframe(df, use_container_width=True)
                except Exception:
                    pass

    with tab2:
        if show_sql and result.get("sql_query"):
            st.code(result["sql_query"], language="sql")

            st.download_button(
                "Download SQL",
                data=result["sql_query"],
                file_name="query.sql",
                mime="text/plain"
            )
        else:
            st.info("No SQL generated yet.")

    with tab3:
        if show_plan and result.get("plan"):
            st.text(result["plan"])
        else:
            st.info("No plan available.")

    with tab4:
        if show_debug:
            st.json(result)
        else:
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

            st.json(debug_summary)