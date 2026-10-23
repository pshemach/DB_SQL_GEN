"""SFA Smart Analyst graph: ingress, fast path, tool-calling analyst, persist."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from langsmith import traceable
from loguru import logger

from src.agents.authz import authz_node
from src.agents.prompts import ANALYST_SYSTEM, CHITCHAT_PROMPT
from src.agents.router import route_turn
from src.agents.runtime import runtime_ctx
from src.agents.state import AgentState
from src.agents.tools import ANALYST_TOOLS
from src.agents.tools.get_kpi import get_kpi
from src.agents.tools.transform_results import transform_results
from src.infrastructure.config import settings
from src.infrastructure.llm.llm_provider import openai_llm
from src.infrastructure.metrics import finalize_metrics, init_metrics, record_node_timing, set_router_action
from src.infrastructure.observability import build_invoke_config, setup_langsmith
from src.infrastructure.serialization import sanitize_state
from src.memory.chat_store import chat_memory
from src.memory.result_store import result_cache
from src.memory.semantic_cache import semantic_cache
from src.memory.session_frame import frame_from_state, load_frame, save_frame
from src.services.formatter import format_result

setup_langsmith()

TOOL_MAP = {t.name: t for t in ANALYST_TOOLS}

NODE_STATUS = {
    "init": "Starting...",
    "memory_loader": "Loading conversation...",
    "semantic_cache": "Checking previous answers...",
    "authz": "Checking access...",
    "router": "Understanding your question...",
    "analyst": "Analyzing...",
    "kpi": "Loading KPIs...",
    "transform": "Updating the previous result...",
    "formatter": "Writing the answer...",
    "chitchat": "Writing a reply...",
    "safe_response": "Preparing a response...",
    "save_memory": "Saving the conversation...",
}


def init_node(state: AgentState) -> dict:
    return {"start_time": time.time(), "metrics": state.get("metrics") or init_metrics()}


def memory_loader_node(state: AgentState) -> dict:
    t0 = time.time()
    session_id = state.get("session_id")
    user_message_id = None
    if session_id and not state.get("user_message_saved"):
        user_message_id = chat_memory.add_message(
            session_id=session_id,
            role="user",
            content=state["question"],
            message_type="question",
            user_id=state.get("user_id"),
            user_role=state.get("user_role"),
        )
    frame = load_frame(session_id)
    return {
        "memory_context": chat_memory.build_memory_context(session_id) if session_id else "",
        "session_frame": frame.as_prompt(),
        "user_message_id": user_message_id,
        "user_message_saved": True,
        "metrics": record_node_timing(state.get("metrics") or init_metrics(), "memory_loader", (time.time() - t0) * 1000),
    }


def semantic_cache_node(state: AgentState) -> dict:
    if not settings.enable_semantic_cache:
        return {"cache_hit": False}
    cached = semantic_cache.get(state["question"])
    if not cached:
        return {"cache_hit": False}
    return sanitize_state({
        "cache_hit": True,
        "turn_action": "cache_hit",
        "sql_query": cached.get("sql_query"),
        "query_result": cached.get("query_result"),
        "result_preview": cached.get("result_preview"),
        "error": None,
    })


def router_node(state: AgentState) -> dict:
    cached = bool(state.get("session_id") and result_cache.get_cached_result(state["session_id"]))
    routed = route_turn(state["question"], state.get("session_frame") or "", has_cached_result=cached)
    if routed.get("enriched_question"):
        routed["question"] = routed["enriched_question"]
    routed["metrics"] = set_router_action(state.get("metrics"), routed.get("turn_action") or "analyze")
    return routed


def chitchat_node(state: AgentState) -> dict:
    try:
        chain = ChatPromptTemplate.from_template(CHITCHAT_PROMPT) | openai_llm()
        msg = chain.invoke({"question": state.get("question") or ""}).content.strip()
    except Exception:
        msg = "I can help with sales, targets, outlets, routes, forecasts, and what to do next."
    return {
        "turn_action": "chitchat",
        "final_answer": msg,
        "result_summary": msg,
        "query_result": None,
        "sql_query": None,
        "visualizations": [],
        "error": None,
        "waiting_for_user": False,
    }


def safe_response_node(state: AgentState) -> dict:
    msg = state.get("access_denied_reason") or state.get("error") or "Unable to process your request."
    return {
        "final_answer": msg,
        "result_summary": msg,
        "query_result": None,
        "sql_query": None,
        "visualizations": [],
        "waiting_for_user": False,
    }


def hitl_node(state: AgentState) -> dict:
    question_to_user = state.get("question_to_user") or "Could you provide more details?"
    return {
        "turn_action": "clarify",
        "final_answer": question_to_user,
        "result_summary": question_to_user,
        "waiting_for_user": True,
        "needs_clarification": True,
        "query_result": None,
        "sql_query": None,
        "visualizations": [],
    }


def _bind_runtime(state: AgentState):
    ctx = {
        "session_id": state.get("session_id"),
        "question": state.get("enriched_question") or state.get("question"),
        "allowed_rep_codes": state.get("allowed_rep_codes") or [],
        "user_role": state.get("user_role"),
        "period": state.get("period") or "current_month",
        "resolved_entities": state.get("resolved_entities") or {},
        "last_rows": None,
        "last_sql": None,
        "waiting_for_user": False,
        "question_to_user": None,
        "findings": [],
        "projections": [],
    }
    token = runtime_ctx.set(ctx)
    return token, ctx


def kpi_node(state: AgentState) -> dict:
    token, ctx = _bind_runtime(state)
    try:
        payload = get_kpi.invoke({
            "metrics": state.get("metric_keys") or ["net_value"],
            "period": state.get("period") or "current_month",
            "dimensions": state.get("dimensions") or ["rep"],
        })
        return _from_ctx(ctx, payload, plan="get_kpi")
    finally:
        runtime_ctx.reset(token)


def transform_node(state: AgentState) -> dict:
    token, ctx = _bind_runtime(state)
    fallback = False
    try:
        payload = transform_results.invoke({
            "question": state.get("original_question") or state.get("question"),
            "mode": "local_transform",
        })
        parsed = _maybe_json(payload)
        if parsed.get("needs_new_sql"):
            fallback = True
        else:
            return _from_ctx(ctx, payload, plan="transform_results", reused=True)
    finally:
        runtime_ctx.reset(token)
    if fallback:
        return analyst_node(state)
    return {}


def analyst_node(state: AgentState) -> dict:
    token, ctx = _bind_runtime(state)
    try:
        llm = openai_llm().bind_tools(ANALYST_TOOLS)
        question = state.get("enriched_question") or state.get("question") or ""
        frame = state.get("session_frame") or ""
        messages: list = [
            SystemMessage(content=ANALYST_SYSTEM),
            HumanMessage(content=f"Session frame:\n{frame}\n\nQuestion:\n{question}"),
        ]
        final_text = ""
        trace: list[str] = []
        for _ in range(settings.max_tool_calls):
            ai = llm.invoke(messages)
            messages.append(ai)
            if not getattr(ai, "tool_calls", None):
                final_text = (ai.content or "").strip()
                break
            for call in ai.tool_calls:
                name = call.get("name")
                tool = TOOL_MAP.get(name)
                trace.append(name or "")
                if tool is None:
                    result = f"Unknown tool: {name}"
                else:
                    try:
                        result = tool.invoke(call.get("args") or {})
                    except Exception as e:
                        logger.error(f"Tool {name} failed: {e}")
                        result = json.dumps({"error": str(e)})
                messages.append(ToolMessage(content=str(result), tool_call_id=call.get("id")))
            if ctx.get("waiting_for_user"):
                break
        else:
            final_text = final_text or "I gathered the available facts. See the table below."

        out = _from_ctx(ctx, None, plan=" -> ".join(t for t in trace if t) or "analyst")
        if ctx.get("waiting_for_user"):
            out.update({
                "waiting_for_user": True,
                "needs_clarification": True,
                "question_to_user": ctx.get("question_to_user"),
                "final_answer": ctx.get("question_to_user"),
                "result_summary": ctx.get("question_to_user"),
                "turn_action": "clarify",
            })
        elif final_text:
            out["final_answer"] = final_text
            out["result_summary"] = final_text
        out["tool_trace"] = trace
        return out
    finally:
        runtime_ctx.reset(token)


def _maybe_json(payload: Any) -> dict:
    if isinstance(payload, dict):
        return payload
    try:
        return json.loads(payload)
    except Exception:
        return {}


def _from_ctx(ctx: dict, payload: Any, plan: str, reused: bool = False) -> dict:
    parsed = _maybe_json(payload) if payload is not None else {}
    rows = ctx.get("last_rows")
    sql = ctx.get("last_sql") or parsed.get("sql")
    error = parsed.get("error")
    return {
        "query_result": rows,
        "sql_query": sql,
        "plan": plan,
        "error": error,
        "error_type": "runtime" if error else None,
        "reused_previous_result": reused,
        "waiting_for_user": False,
    }


def formatter_node(state: AgentState) -> dict:
    if state.get("waiting_for_user"):
        return {}
    if state.get("final_answer") and state.get("turn_action") in ("chitchat", "deny", "clarify"):
        return {}
    return sanitize_state(format_result(dict(state)))


def cache_result_node(state: AgentState) -> dict:
    if state.get("error") or not state.get("sql_query"):
        return {}
    question_key = state.get("enriched_question") or state.get("question") or ""
    if not state.get("reused_previous_result") and state.get("turn_action") not in ("cache_hit", "transform_previous"):
        semantic_cache.set(question_key, {
            "sql_query": state.get("sql_query"),
            "query_result": state.get("query_result"),
            "result_preview": state.get("result_preview"),
        })
    return {}


def save_memory_node(state: AgentState) -> dict:
    session_id = state.get("session_id")
    if not session_id:
        return {}
    assistant_content = (
        state.get("question_to_user") if state.get("waiting_for_user")
        else state.get("error") or state.get("result_summary") or state.get("final_answer")
    )
    message_type = "clarification" if state.get("waiting_for_user") else ("error" if state.get("error") else "answer")
    assistant_message_id = state.get("assistant_message_id")
    if assistant_content and not state.get("assistant_message_saved"):
        assistant_message_id = chat_memory.add_message(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            message_type=message_type,
            user_id=state.get("user_id"),
            user_role=state.get("user_role"),
        )
    if state.get("sql_query") and state.get("query_result") is not None and not state.get("error") and not state.get("sql_execution_saved"):
        chat_memory.save_sql_execution(
            session_id=session_id,
            user_id=state.get("user_id"),
            sql=state.get("sql_query"),
            result=state.get("query_result"),
            execution_time_ms=state.get("execution_time_ms") or 0,
        )
    save_frame(session_id, frame_from_state(dict(state)))
    chat_memory.set_last_state(session_id, {**dict(state), "assistant_message_id": assistant_message_id})
    return {
        "assistant_message_id": assistant_message_id,
        "assistant_message_saved": bool(assistant_content),
        "sql_execution_saved": True,
        "memory_context": chat_memory.build_memory_context(session_id),
    }


def route_after_cache(state: AgentState) -> Literal["formatter", "authz"]:
    return "formatter" if state.get("cache_hit") else "authz"


def route_after_authz(state: AgentState) -> Literal["safe_response", "router"]:
    return "safe_response" if state.get("access_denied") else "router"


def route_after_router(state: AgentState) -> str:
    action = state.get("turn_action") or "analyze"
    if action == "deny":
        return "safe_response"
    if action == "chitchat":
        return "chitchat"
    if action == "clarify":
        return "hitl"
    if action == "transform_previous":
        return "transform"
    if action == "kpi":
        return "kpi"
    return "analyst"


def build_graph() -> StateGraph:
    workflow = StateGraph(AgentState)
    workflow.add_node("init", init_node)
    workflow.add_node("memory_loader", memory_loader_node)
    workflow.add_node("semantic_cache", semantic_cache_node)
    workflow.add_node("authz", authz_node)
    workflow.add_node("router", router_node)
    workflow.add_node("chitchat", chitchat_node)
    workflow.add_node("safe_response", safe_response_node)
    workflow.add_node("hitl", hitl_node)
    workflow.add_node("kpi", kpi_node)
    workflow.add_node("transform", transform_node)
    workflow.add_node("analyst", analyst_node)
    workflow.add_node("formatter", formatter_node)
    workflow.add_node("cache_result", cache_result_node)
    workflow.add_node("save_memory", save_memory_node)

    workflow.set_entry_point("init")
    workflow.add_edge("init", "memory_loader")
    workflow.add_edge("memory_loader", "semantic_cache")
    workflow.add_conditional_edges("semantic_cache", route_after_cache, {"formatter": "formatter", "authz": "authz"})
    workflow.add_conditional_edges("authz", route_after_authz, {"safe_response": "safe_response", "router": "router"})
    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {
            "safe_response": "safe_response",
            "chitchat": "chitchat",
            "hitl": "hitl",
            "transform": "transform",
            "kpi": "kpi",
            "analyst": "analyst",
        },
    )
    workflow.add_edge("kpi", "formatter")
    workflow.add_edge("transform", "formatter")
    workflow.add_edge("analyst", "formatter")
    workflow.add_edge("chitchat", "save_memory")
    workflow.add_edge("safe_response", "save_memory")
    workflow.add_edge("hitl", "save_memory")
    workflow.add_edge("formatter", "cache_result")
    workflow.add_edge("cache_result", "save_memory")
    workflow.add_edge("save_memory", END)
    return workflow


graph = build_graph().compile()


def _initial_state(question: str, session_id: str, kwargs: dict) -> AgentState:
    return {
        "session_id": session_id,
        "question": question,
        "original_question": question,
        "allowed_rep_codes": kwargs.get("allowed_rep_codes") or [],
        "user_role": kwargs.get("user_role"),
        "user_id": kwargs.get("user_id"),
        "messages": [],
        "metrics": init_metrics(),
        "iterations": 0,
        "should_retry": True,
        "start_time": time.time(),
        "cache_hit": False,
        "waiting_for_user": False,
        "needs_clarification": False,
    }


def _finalize(result: dict) -> dict:
    if result.get("start_time"):
        total = (time.time() - result["start_time"]) * 1000
        result["total_latency_ms"] = total
        result["metrics"] = finalize_metrics(result.get("metrics"), total_latency_ms=total)
    return sanitize_state(result)


@traceable(name="sfa-smart-analyst", run_type="chain", tags=["sfa", "analyst"])
def run_agent(question: str, **kwargs) -> dict:
    session_id = chat_memory.get_or_create_session(
        kwargs.get("session_id"),
        user_id=kwargs.get("user_id"),
        user_role=kwargs.get("user_role"),
    )
    initial = _initial_state(question, session_id, kwargs)
    try:
        result = graph.invoke(initial, build_invoke_config(session_id))
        return _finalize(result)
    except Exception as e:
        logger.error(f"Analyst graph error: {e}")
        return {**initial, "error": str(e), "should_retry": False}


async def run_agent_async(question: str, session_id: str | None = None, **kwargs) -> dict:
    session_id = chat_memory.get_or_create_session(
        session_id, user_id=kwargs.get("user_id"), user_role=kwargs.get("user_role")
    )
    initial = _initial_state(question, session_id, kwargs)
    try:
        result = await graph.ainvoke(initial, build_invoke_config(session_id))
        finalized = _finalize(result)
        finalized["turn_type"] = kwargs.get("turn_type") or "start"
        return finalized
    except Exception as e:
        logger.error(f"Analyst graph error: {e}")
        return {**initial, "error": str(e), "should_retry": False, "turn_type": kwargs.get("turn_type")}


async def run_agent_stream(question: str, session_id: str | None = None, **kwargs) -> AsyncIterator[dict[str, Any]]:
    session_id = chat_memory.get_or_create_session(
        session_id, user_id=kwargs.get("user_id"), user_role=kwargs.get("user_role")
    )
    initial = _initial_state(question, session_id, kwargs)
    merged = dict(initial)
    try:
        async for item in graph.astream(initial, build_invoke_config(session_id), stream_mode="updates"):
            if not isinstance(item, dict):
                continue
            for node_name, update in item.items():
                label = NODE_STATUS.get(node_name)
                if label:
                    yield {"type": "status", "text": label, "node": node_name}
                if isinstance(update, dict):
                    merged.update(update)
        yield {"type": "complete", "state": _finalize(merged)}
    except Exception as e:
        logger.error(f"Analyst stream error: {e}")
        yield {"type": "complete", "state": {**initial, "error": str(e), "should_retry": False}}
