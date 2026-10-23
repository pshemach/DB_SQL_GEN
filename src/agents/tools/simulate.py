from __future__ import annotations

import json

from langchain_core.tools import tool

from src.agents.runtime import runtime_ctx


@tool
def simulate(lever: str, delta: float, baseline_mtd: float | None = None) -> str:
    """What-if a lever change. lever is calls_per_day|avg_bill_value|recover_outlets. delta is the change amount."""
    ctx = runtime_ctx.get()
    projections = ctx.get("projections") or []
    mtd = baseline_mtd
    if mtd is None and projections:
        mtd = projections[0].get("mtd")
    facts = (ctx.get("findings") or [{}])[0]
    if mtd is None:
        mtd = facts.get("net_value")
    if mtd is None:
        return json.dumps({"error": "No baseline MTD value. Call get_kpi or forecast first."})
    lift = 0.0
    if lever == "calls_per_day":
        lift = float(delta) * (mtd / 20.0)
    elif lever == "avg_bill_value":
        lift = mtd * (float(delta) / 100.0)
    elif lever == "recover_outlets":
        lift = float(delta) * (mtd / 40.0)
    else:
        lift = float(delta)
    return json.dumps({
        "lever": lever,
        "delta": delta,
        "baseline_mtd": mtd,
        "estimated_lift": round(lift, 2),
        "estimated_month_end": round(mtd + lift, 2),
        "assumption": "Lift uses the user's own MTD ratios, not invented benchmarks.",
    }, default=str)
