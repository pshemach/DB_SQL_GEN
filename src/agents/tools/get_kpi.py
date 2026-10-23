from __future__ import annotations

from langchain_core.tools import tool

from src.agents.runtime import runtime_ctx
from src.agents.tools._facts import execute_select, store_result, tool_payload
from src.semantic.compiler import QuerySpec, compile_sql


@tool
def get_kpi(
    metrics: list[str],
    period: str = "current_month",
    dimensions: list[str] | None = None,
    rep_code: str | None = None,
) -> str:
    """Run a compiled KPI query. metrics like net_value, target, return_value, bill_count, productive_calls. dimensions like rep, route, customer, product, brand, date."""
    ctx = runtime_ctx.get()
    spec = QuerySpec(
        metrics=metrics or ["net_value"],
        dimensions=dimensions or ["rep"],
        period=period or "current_month",
        filters={"rep_code": rep_code} if rep_code else {},
    )
    sql = compile_sql(spec)
    rows, error, rewritten, _elapsed = execute_select(sql, ctx.get("allowed_rep_codes") or [])
    if error:
        return f'{{"error": {error!r}, "sql": {rewritten!r}}}'
    result_id = store_result(ctx.get("session_id") or "", ctx.get("question") or "", rewritten, rows, spec.metrics)
    ctx["last_sql"] = rewritten
    ctx["last_rows"] = rows
    return tool_payload(result_id, rows, {"sql": rewritten, "metrics": spec.metrics, "period": spec.period})
