from __future__ import annotations

import json
from datetime import date

from langchain_core.tools import tool

from src.agents.runtime import runtime_ctx
from src.agents.tools._facts import compact_facts, execute_select, store_result
from src.semantic.compiler import QuerySpec, compile_sql
from src.services.analytics import run_rate_projection


@tool
def forecast(metric: str = "net_value") -> str:
    """Month-end run-rate projection from month-to-date KPI values."""
    ctx = runtime_ctx.get()
    sql = compile_sql(QuerySpec(metrics=[metric], dimensions=["rep"], period="current_month"))
    rows, error, rewritten, _ = execute_select(sql, ctx.get("allowed_rep_codes") or [])
    if error:
        return json.dumps({"error": error, "sql": rewritten})
    today = date.today()
    elapsed = max(today.day, 1)
    import calendar
    remaining_days = max(calendar.monthrange(today.year, today.month)[1] - elapsed, 0)
    working_elapsed = max(int(elapsed * 5 / 7), 1)
    working_remaining = int(remaining_days * 5 / 7)
    facts = compact_facts(rows)
    projections = []
    for row in rows[:20]:
        mtd = None
        for key, value in row.items():
            try:
                mtd = float(value)
                metric_key = key
            except (TypeError, ValueError):
                continue
        if mtd is None:
            continue
        projected = run_rate_projection(mtd, working_elapsed, working_remaining)
        projections.append({
            **{k: v for k, v in row.items() if not isinstance(v, (int, float))},
            **projected,
            "required_daily": projected["daily_run_rate"],
        })
    result_id = store_result(ctx.get("session_id") or "", ctx.get("question") or "", rewritten, rows, [metric])
    ctx["last_sql"] = rewritten
    ctx["last_rows"] = rows
    ctx["projections"] = projections
    return json.dumps({
        "result_id": result_id,
        "working_days_elapsed": working_elapsed,
        "working_days_remaining": working_remaining,
        "facts": facts,
        "projections": projections[:10],
        "sql": rewritten,
    }, default=str)
