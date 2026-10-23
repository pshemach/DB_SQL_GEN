from __future__ import annotations

import json

from langchain_core.tools import tool

from src.agents.runtime import runtime_ctx
from src.agents.tools._facts import compact_facts, execute_select, store_result
from src.semantic.compiler import QuerySpec, compile_sql
from src.semantic.driver_tree import decompose


@tool
def diagnose_gap(period: str = "current_month", rep_code: str | None = None) -> str:
    """Explain a sales vs target gap using the SFA driver tree (net sales, target, returns, bills, productive calls)."""
    ctx = runtime_ctx.get()
    allowed = ctx.get("allowed_rep_codes") or []
    filters = {"rep_code": rep_code} if rep_code else {}
    facts_by_kpi: dict = {}
    last_sql = ""
    last_rows: list = []

    combined = compile_sql(QuerySpec(
        metrics=["net_value", "target", "achievement_pct"],
        dimensions=["rep"],
        period=period,
        filters=filters,
    ))
    rows, error, rewritten, _ = execute_select(combined, allowed)
    if not error:
        last_sql, last_rows = rewritten, rows
        packed = compact_facts(rows)
        facts_by_kpi["net_value"] = packed
        facts_by_kpi["target"] = packed

    for metric in ("return_value", "bill_count", "productive_calls"):
        sql = compile_sql(QuerySpec(metrics=[metric], dimensions=["rep"], period=period, filters=filters))
        rows, err, rewritten, _ = execute_select(sql, allowed)
        if err:
            facts_by_kpi[metric] = {"error": err}
            continue
        facts_by_kpi[metric] = compact_facts(rows)
        if not last_rows:
            last_sql, last_rows = rewritten, rows

    findings = decompose(facts_by_kpi)
    result_id = store_result(ctx.get("session_id") or "", ctx.get("question") or "", last_sql, last_rows, ["diagnose"])
    ctx["last_sql"] = last_sql
    ctx["last_rows"] = last_rows
    ctx["findings"] = findings
    return json.dumps({"result_id": result_id, "findings": findings, "facts": facts_by_kpi, "sql": last_sql}, default=str)
