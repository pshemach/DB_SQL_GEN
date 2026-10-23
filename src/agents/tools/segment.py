from __future__ import annotations

import json

from langchain_core.tools import tool

from src.agents.runtime import runtime_ctx
from src.agents.tools._facts import compact_facts, execute_select, store_result
from src.memory.result_store import result_cache
from src.semantic.compiler import QuerySpec, compile_sql


@tool
def segment(by: str = "customer", metric: str = "net_value", period: str = "current_month") -> str:
    """Rank outlets, products, brands, or routes by a KPI. by is customer|product|brand|route|rep."""
    ctx = runtime_ctx.get()
    dim = by if by in {"customer", "product", "brand", "route", "rep"} else "customer"
    cached = result_cache.get_cached_result(ctx.get("session_id") or "")
    if cached and dim in (cached.columns_used or []) and metric.lower() in " ".join(cached.columns_used).lower():
        rows = list(cached.result_data)
        facts = compact_facts(rows)
        return json.dumps({"result_id": cached.query_id, "reused": True, **facts}, default=str)
    sql = compile_sql(QuerySpec(metrics=[metric], dimensions=[dim], period=period, limit=50))
    rows, error, rewritten, _ = execute_select(sql, ctx.get("allowed_rep_codes") or [])
    if error:
        return json.dumps({"error": error, "sql": rewritten})
    result_id = store_result(ctx.get("session_id") or "", ctx.get("question") or "", rewritten, rows, [dim])
    ctx["last_sql"] = rewritten
    ctx["last_rows"] = rows
    return tool_json(result_id, rows, rewritten)


def tool_json(result_id, rows, sql):
    payload = compact_facts(rows, max_top=10)
    payload["result_id"] = result_id
    payload["sql"] = sql
    return json.dumps(payload, default=str)
