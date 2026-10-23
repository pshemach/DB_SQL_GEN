from __future__ import annotations

import json

from langchain_core.tools import tool

from src.agents.runtime import runtime_ctx
from src.agents.tools._facts import compact_facts, execute_select, store_result
from src.semantic.compiler import QuerySpec, compile_sql


@tool
def compare(metric: str = "net_value", dimensions: list[str] | None = None) -> str:
    """Compare current month vs last month for a KPI."""
    ctx = runtime_ctx.get()
    allowed = ctx.get("allowed_rep_codes") or []
    dims = dimensions or ["rep"]
    current_sql = compile_sql(QuerySpec(metrics=[metric], dimensions=dims, period="current_month"))
    last_sql = compile_sql(QuerySpec(metrics=[metric], dimensions=dims, period="last_month"))
    current_rows, err_a, sql_a, _ = execute_select(current_sql, allowed)
    last_rows, err_b, sql_b, _ = execute_select(last_sql, allowed)
    if err_a or err_b:
        return json.dumps({"error": err_a or err_b, "sql": sql_a or sql_b})
    result_id = store_result(ctx.get("session_id") or "", ctx.get("question") or "", sql_a, current_rows, [metric])
    ctx["last_sql"] = sql_a
    ctx["last_rows"] = current_rows
    return json.dumps({
        "result_id": result_id,
        "current": compact_facts(current_rows),
        "last_month": compact_facts(last_rows),
        "sql": sql_a,
    }, default=str)
