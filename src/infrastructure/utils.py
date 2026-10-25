"""Shared helpers: LLM JSON parsing, graph metrics, and JSON-safe values."""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, time as time_of_day
from decimal import Decimal
from typing import Any


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response."""
    text = text.strip().replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found: {text}")
    return json.loads(match.group(0))


def init_metrics() -> dict[str, Any]:
    return {
        "cache_hit": False,
        "router_action": None,
        "sql_retries": 0,
        "node_timings_ms": {},
        "started_at": time.time(),
    }


def record_node_timing(metrics: dict | None, node_name: str, elapsed_ms: float) -> dict:
    current = metrics or init_metrics()
    timings = current.setdefault("node_timings_ms", {})
    timings[node_name] = round(elapsed_ms, 2)
    return current


def set_router_action(metrics: dict | None, action: str) -> dict:
    current = metrics or init_metrics()
    current["router_action"] = action
    return current


def finalize_metrics(metrics: dict | None, total_latency_ms: float | None = None) -> dict:
    current = metrics or init_metrics()
    if total_latency_ms is not None:
        current["total_latency_ms"] = round(total_latency_ms, 2)
    if current.get("started_at"):
        current["wall_clock_ms"] = round((time.time() - current["started_at"]) * 1000, 2)
    return current


def _is_sqlalchemy_type(value: Any) -> bool:
    try:
        from sqlalchemy.sql.type_api import TypeEngine

        if isinstance(value, TypeEngine):
            return True
    except ImportError:
        pass
    module = getattr(type(value), "__module__", "") or ""
    return module.startswith("sqlalchemy") and type(value).__name__ in (
        "DATE",
        "DATETIME",
        "TIMESTAMP",
        "TIME",
        "INTEGER",
        "SMALLINT",
        "BIGINT",
        "FLOAT",
        "BOOLEAN",
        "TEXT",
        "VARCHAR",
        "NVARCHAR",
        "DECIMAL",
        "NUMERIC",
    )


def json_safe_value(value: Any) -> Any:
    """Convert one value to a checkpoint-safe type."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time_of_day)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if _is_sqlalchemy_type(value):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe_value(item) for key, item in value.items()}

    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return json_safe_value(value.tolist())
        if isinstance(value, (np.integer, np.floating)):
            return value.item()
    except ImportError:
        pass

    if hasattr(value, "_mapping"):
        return json_safe_value(dict(value._mapping))

    type_name = type(value).__name__
    if type_name in ("DATE", "DATETIME", "TIMESTAMP", "TIME", "TIMEDELTA"):
        return str(value)
    return str(value)


def serialize_query_result(query_result: Any) -> list[dict] | str | None:
    """Turn SQL rows into plain dicts before they enter graph state or the API."""
    if query_result is None or isinstance(query_result, str):
        return query_result
    if not isinstance(query_result, (list, tuple)):
        return json_safe_value(query_result)

    serialized: list[dict] = []
    for row in query_result:
        if hasattr(row, "_mapping"):
            raw = dict(row._mapping)
        elif isinstance(row, dict):
            raw = row
        elif hasattr(row, "__iter__") and not isinstance(row, (str, bytes)):
            raw = dict(zip(range(len(row)), row))
        else:
            raw = {"value": row}
        serialized.append({str(key): json_safe_value(item) for key, item in raw.items()})
    return serialized


def sanitize_state(data: Any) -> Any:
    """Make graph output safe for the checkpointer."""
    if data is None or isinstance(data, (str, int, float, bool)):
        return data
    if isinstance(data, (datetime, date, time_of_day)):
        return data.isoformat()
    if isinstance(data, Decimal):
        return float(data)
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    if _is_sqlalchemy_type(data):
        return str(data)
    if isinstance(data, dict):
        return {str(key): sanitize_state(item) for key, item in data.items()}
    if isinstance(data, (list, tuple)):
        return [sanitize_state(item) for item in data]
    if hasattr(data, "_mapping"):
        return sanitize_state(dict(data._mapping))

    try:
        import numpy as np

        if isinstance(data, np.ndarray):
            return sanitize_state(data.tolist())
        if isinstance(data, (np.integer, np.floating)):
            return data.item()
    except ImportError:
        pass

    return json_safe_value(data)
