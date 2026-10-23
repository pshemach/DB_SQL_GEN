from __future__ import annotations

import json

from langchain_core.tools import tool

from src.agents.runtime import runtime_ctx


@tool
def rank_actions() -> str:
    """Rank 2-4 concrete next actions from diagnose/forecast/segment findings already in this turn."""
    ctx = runtime_ctx.get()
    findings = ctx.get("findings") or []
    projections = ctx.get("projections") or []
    actions = []
    for finding in findings:
        lever = finding.get("lever")
        if lever == "target_gap" and finding.get("on_track") is False:
            actions.append({
                "action": "Close target gap",
                "evidence": finding,
                "why": f"Achievement is {finding.get('achievement_pct')}% with gap {finding.get('gap')}.",
            })
        elif lever == "returns":
            actions.append({
                "action": "Review high-return SKUs and outlets",
                "evidence": finding,
                "why": f"Returns are {finding.get('return_rate_pct')}% of related value.",
            })
        elif lever == "bill_value":
            actions.append({
                "action": "Raise lines per bill on low-value invoices",
                "evidence": finding,
                "why": "Average bill value is a primary sales lever.",
            })
        elif lever == "productive_calls":
            actions.append({
                "action": "Recover missed planned outlets",
                "evidence": finding,
                "why": "Productive call volume is below the coverage needed for target.",
            })
    if projections:
        actions.append({
            "action": "Protect daily run-rate",
            "evidence": projections[0],
            "why": "Month-end projection depends on holding today's daily pace.",
        })
    if not actions:
        actions.append({
            "action": "Review net sales vs target for the current month",
            "evidence": {},
            "why": "No driver-tree findings yet; start with get_kpi and diagnose_gap.",
        })
    ctx["advice_given"] = [a["action"] for a in actions[:4]]
    return json.dumps({"actions": actions[:4]}, default=str)
