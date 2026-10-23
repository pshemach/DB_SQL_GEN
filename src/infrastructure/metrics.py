"""Lightweight runtime metrics attached to agent state."""

from __future__ import annotations

import time
from typing import Any


def init_metrics() -> dict[str, Any]:
    return {
        "cache_hit": False,
        "router_action": None,
        "sql_retries": 0,
        "node_timings_ms": {},
        "started_at": time.time(),
    }


def record_node_timing(metrics: dict | None, node_name: str, elapsed_ms: float) -> dict:
    m = metrics or init_metrics()
    timings = m.setdefault("node_timings_ms", {})
    timings[node_name] = round(elapsed_ms, 2)
    return m


def bump_sql_retries(metrics: dict | None) -> dict:
    m = metrics or init_metrics()
    m["sql_retries"] = m.get("sql_retries", 0) + 1
    return m


def set_router_action(metrics: dict | None, action: str) -> dict:
    m = metrics or init_metrics()
    m["router_action"] = action
    return m


def finalize_metrics(metrics: dict | None, total_latency_ms: float | None = None) -> dict:
    m = metrics or init_metrics()
    if total_latency_ms is not None:
        m["total_latency_ms"] = round(total_latency_ms, 2)
    if m.get("started_at"):
        m["wall_clock_ms"] = round((time.time() - m["started_at"]) * 1000, 2)
    return m
