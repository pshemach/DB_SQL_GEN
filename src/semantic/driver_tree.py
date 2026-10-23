"""SFA driver tree: net sales decomposes into coverage, strike rate, bill value, returns."""

from __future__ import annotations

from typing import Any

DRIVER_NODES = (
    "net_value",
    "sales_value",
    "return_value",
    "productive_calls",
    "bill_count",
    "target",
)


def decompose(facts_by_kpi: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    net = _metric(facts_by_kpi, "net_value")
    target = _metric(facts_by_kpi, "target")
    returns = _metric(facts_by_kpi, "return_value")
    bills = _metric(facts_by_kpi, "bill_count")
    calls = _metric(facts_by_kpi, "productive_calls")

    if target and net is not None:
        pct = round(net / target * 100, 2) if target else None
        gap = round(target - net, 2)
        findings.append({
            "lever": "target_gap",
            "net_value": net,
            "target": target,
            "achievement_pct": pct,
            "gap": gap,
            "on_track": bool(pct is not None and pct >= 100),
        })
    if returns and net:
        findings.append({
            "lever": "returns",
            "return_value": returns,
            "return_rate_pct": round(returns / (abs(net) + returns) * 100, 2),
        })
    if bills:
        avg_bill = round(net / bills, 2) if net and bills else None
        findings.append({"lever": "bill_value", "bill_count": bills, "avg_bill_value": avg_bill})
    if calls:
        findings.append({"lever": "productive_calls", "productive_calls": calls})
    return findings


def _metric(facts_by_kpi: dict[str, dict[str, Any]], key: str) -> float | None:
    block = facts_by_kpi.get(key) or {}
    aggregates = block.get("aggregates") or {}
    for value in aggregates.values():
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
