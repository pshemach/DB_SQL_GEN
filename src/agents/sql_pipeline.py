"""SQL subgraph pipeline nodes: security, retrieval, validation, verification."""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from loguru import logger

from src.agents.critic import executor_node, reflector_node
from src.agents.generator import generator_node
from src.agents.planner import planner_node
from src.agents.retriever import SchemaLinkerAgent
from src.agents.prompts.agent_prompts import PRE_EXEC_CRITIC_SYSTEM
from src.infrastructure.vector_store import few_shot_retriever
from src.infrastructure.config import (
    ENABLE_DYNAMIC_FEW_SHOT,
    ENABLE_PRE_EXEC_CRITIC,
    ENABLE_RESULT_VERIFIER,
    FEW_SHOT_EXAMPLES_COUNT,
    MAX_ITERATIONS,
    SQL_MAX_ROWS,
)
from src.infrastructure.llm import get_chat_llm
from src.infrastructure.db.sql_safety import assess_sql
from src.utils.error_taxonomy import classify_db_error, is_retryable
from src.utils.metrics import bump_sql_retries, record_node_timing
from src.agents.state import AgentState, SQLSubState

FORBIDDEN_SQL = re.compile(
    r"(?i)\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b"
)

def _parent_to_sub(state: AgentState) -> SQLSubState:
    return {
        "question": state.get("enriched_question") or state["question"],
        "business_definitions": state.get("business_definitions") or "",
        "allowed_rep_codes": state.get("allowed_rep_codes") or [],
        "security_filter_sql": state.get("security_filter_sql"),
        "plan": state.get("plan"),
        "plan_steps": state.get("plan_steps"),
        "relevant_tables": state.get("relevant_tables"),
        "relevant_columns": state.get("relevant_columns"),
        "schema_context": state.get("schema_context"),
        "schema_metadata": state.get("schema_metadata"),
        "sql_query": state.get("sql_query"),
        "sql_explanation": state.get("sql_explanation"),
        "few_shot_examples": state.get("few_shot_examples"),
        "query_result": state.get("query_result"),
        "result_preview": state.get("result_preview"),
        "execution_time_ms": state.get("execution_time_ms"),
        "error": state.get("error"),
        "error_type": state.get("error_type"),
        "iterations": state.get("iterations", 0),
        "should_retry": state.get("should_retry", True),
    }

def _sub_to_parent(sub: SQLSubState) -> dict:
    return {
        k: sub[k]
        for k in (
            "plan", "plan_steps", "relevant_tables", "relevant_columns",
            "schema_context", "schema_metadata", "sql_query", "sql_explanation",
            "few_shot_examples", "query_result", "result_preview",
            "execution_time_ms", "error", "error_type", "iterations", "should_retry",
        )
        if k in sub and sub[k] is not None
    }

def security_policy_node(state: SQLSubState) -> dict:
    """Inject row-level security context; fail closed without rep codes."""
    allowed = state.get("allowed_rep_codes") or []
    if not allowed:
        return {
            "error": "Access denied. No allowed rep codes were provided.",
            "error_type": "access_denied",
            "should_retry": False,
        }
    codes_sql = ", ".join(f"'{c}'" for c in allowed)
    filter_sql = f"RepCode IN ({codes_sql})"
    return {"security_filter_sql": filter_sql, "access_denied": False}

def parallel_retrieval_node(state: SQLSubState) -> dict:
    """Fetch schema context and few-shot examples in parallel (requires plan)."""
    t0 = time.time()
    question = state["question"]

    def _schema():
        linker = SchemaLinkerAgent()
        return linker.retrieve_schema(dict(state))

    def _few_shot():
        if not ENABLE_DYNAMIC_FEW_SHOT:
            return {"few_shot_examples": []}
        try:
            examples = few_shot_retriever.retrieve(question, k=FEW_SHOT_EXAMPLES_COUNT)
            return {"few_shot_examples": examples}
        except Exception as e:
            logger.warning(f"Few-shot retrieval failed: {e}")
            return {"few_shot_examples": []}

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_schema = pool.submit(_schema)
        f_few = pool.submit(_few_shot)
        schema_out = f_schema.result()
        few_out = f_few.result()

    logger.info(f"Parallel retrieval completed in {(time.time() - t0) * 1000:.0f}ms")
    return {**schema_out, **few_out}

def static_validator_node(state: SQLSubState) -> dict:
    """Deterministic SQL validation before execution."""
    sql = (state.get("sql_query") or "").strip()
    if not sql:
        return {
            "error": "No SQL query generated",
            "error_type": "validation",
            "should_retry": True,
        }

    if FORBIDDEN_SQL.search(sql):
        return {
            "error": "Query contains forbidden DDL/DML statements",
            "error_type": "validation",
            "should_retry": False,
        }

    kind, message = assess_sql(sql)
    if kind == "policy":
        return {
            "error": message,
            "error_type": "validation",
            "should_retry": False,
        }
    if kind == "parse":
        return {
            "error": f"SQL parse error: {message}",
            "error_type": "syntax",
            "should_retry": True,
        }

    sql_upper = sql.upper()
    if "LIMIT" not in sql_upper and "TOP " not in sql_upper:
        logger.info("Enforcing row cap via TOP clause recommendation in state")
        state_note = f"-- validator: consider TOP {SQL_MAX_ROWS}"
        return {
            "sql_explanation": (state.get("sql_explanation") or "") + f"\n{state_note}",
            "error": None,
            "error_type": None,
            "should_retry": False,
        }

    return {
        "pre_exec_approved": True,
        "error": None,
        "error_type": None,
        "should_retry": False,
    }

def pre_exec_critic_node(state: SQLSubState) -> dict:
    """Optional LLM review of SQL before execution (feature-flagged)."""
    if not ENABLE_PRE_EXEC_CRITIC:
        return {}

    # llm = ChatAnthropic(
    #     model=ANTHROPIC_MODEL_FAST,
    #     api_key=ANTHROPIC_API_KEY,
    # )
    llm = get_chat_llm(temperature=0)
    prompt = ChatPromptTemplate.from_messages([
        ("system", PRE_EXEC_CRITIC_SYSTEM),
        ("human", "Question: {question}\nSQL:\n{sql}"),
    ])
    try:
        resp = (prompt | llm).invoke({
            "question": state["question"],
            "sql": state.get("sql_query", ""),
        })
        content = resp.content.strip()
        if content.upper().startswith("REJECT"):
            return {
                "error": content,
                "error_type": "validation",
                "should_retry": True,
            }
    except Exception as e:
        logger.warning(f"Pre-exec critic failed: {e}")
    return {"pre_exec_approved": True}

def result_verifier_node(state: SQLSubState) -> dict:
    """Sanity-check execution results before caching."""
    if not ENABLE_RESULT_VERIFIER:
        return {}

    if state.get("error"):
        return {}

    result = state.get("query_result")
    if result is None:
        return {}

    if isinstance(result, list) and len(result) == 0:
        preview = state.get("result_preview") or "Query returned no rows."
        return {"result_preview": preview, "verified_empty": True}

    return {"verified_empty": False}

def sql_subgraph_invoke_node(state: AgentState) -> dict:
    """Bridge parent AgentState through the compiled SQL subgraph."""
    subgraph = get_sql_subgraph()
    sub_in = _parent_to_sub(state)
    sub_out = subgraph.invoke(sub_in)
    merged = _sub_to_parent(sub_out)
    if sub_out.get("error") and is_retryable(sub_out.get("error_type"), sub_out.get("should_retry", True)):
        metrics = bump_sql_retries(state.get("metrics"))
        merged["metrics"] = metrics
    return merged

def route_sql_subgraph_executor(state: SQLSubState) -> str:
    if state.get("error") is None:
        return "result_verifier"
    if not is_retryable(state.get("error_type"), state.get("should_retry", True)):
        return "complete"
    if state.get("iterations", 0) >= MAX_ITERATIONS:
        return "complete"
    return "reflect"


def route_after_static_validator(state: SQLSubState) -> str:
    if state.get("error"):
        if is_retryable(state.get("error_type"), state.get("should_retry", True)):
            if state.get("iterations", 0) < MAX_ITERATIONS:
                return "reflect"
        return "complete"
    return "pre_exec_critic" if ENABLE_PRE_EXEC_CRITIC else "executor"

def route_after_pre_exec(state: SQLSubState) -> str:
    if state.get("error"):
        if is_retryable(state.get("error_type"), state.get("should_retry", True)):
            if state.get("iterations", 0) < MAX_ITERATIONS:
                return "reflect"
        return "complete"
    return "executor"

def build_sql_subgraph():
    """Build and compile the SQL pipeline subgraph."""
    workflow = StateGraph(SQLSubState)

    workflow.add_node("security_policy", security_policy_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("parallel_retrieval", parallel_retrieval_node)
    workflow.add_node("generator", generator_node)
    workflow.add_node("static_validator", static_validator_node)
    workflow.add_node("pre_exec_critic", pre_exec_critic_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("reflector", reflector_node)
    workflow.add_node("result_verifier", result_verifier_node)

    workflow.add_edge(START, "security_policy")

    workflow.add_conditional_edges(
        "security_policy",
        lambda s: "complete" if s.get("error") else "planner",
        {"planner": "planner", "complete": END},
    )

    workflow.add_edge("planner", "parallel_retrieval")
    workflow.add_edge("parallel_retrieval", "generator")
    workflow.add_edge("generator", "static_validator")

    workflow.add_conditional_edges(
        "static_validator",
        route_after_static_validator,
        {
            "pre_exec_critic": "pre_exec_critic",
            "executor": "executor",
            "reflect": "reflector",
            "complete": END,
        },
    )

    if ENABLE_PRE_EXEC_CRITIC:
        workflow.add_conditional_edges(
            "pre_exec_critic",
            route_after_pre_exec,
            {
                "executor": "executor",
                "reflect": "reflector",
                "complete": END,
            },
        )

    workflow.add_conditional_edges(
        "executor",
        route_sql_subgraph_executor,
        {
            "reflect": "reflector",
            "result_verifier": "result_verifier",
            "complete": END,
        },
    )

    workflow.add_edge("reflector", "static_validator")
    workflow.add_edge("result_verifier", END)

    return workflow.compile()

_sql_subgraph = None


def get_sql_subgraph():
    global _sql_subgraph
    if _sql_subgraph is None:
        logger.info("Compiling SQL subgraph...")
        _sql_subgraph = build_sql_subgraph()
    return _sql_subgraph
