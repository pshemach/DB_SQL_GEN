from __future__ import annotations

import json
from typing import Any

from src.infrastructure.db.mysql_client import db_manager
from src.infrastructure.db.sql_safety import verify_sql
from src.infrastructure.serialization import serialize_query_result
from src.memory.result_store import result_cache


def compact_facts(rows: list[dict[str, Any]], max_top: int = 5) -> dict[str, Any]:
    if not rows:
        return {"row_count": 0, "columns": [], "aggregates": {}, "top_n": [], "sample": []}
    columns = list(rows[0].keys())
    numeric: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            try:
                numeric.setdefault(key, []).append(float(value))
            except (TypeError, ValueError):
                continue
    aggregates = {}
    for key, values in numeric.items():
        if not values:
            continue
        aggregates[key] = {
            "sum": round(sum(values), 2),
            "avg": round(sum(values) / len(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }
    return {
        "row_count": len(rows),
        "columns": columns,
        "aggregates": aggregates,
        "top_n": rows[:max_top],
        "sample": rows[:3],
    }


def execute_select(sql: str, allowed_rep_codes: list[str]) -> tuple[list[dict], str | None, str, float | None]:
    kind, message, rewritten = verify_sql(sql)
    if kind != "ok":
        return [], message or "SQL rejected", rewritten, None
    result, error, elapsed = db_manager.allowed_execute_query(rewritten, allowed_rep_codes=allowed_rep_codes)
    if error:
        return [], error, rewritten, elapsed
    rows = serialize_query_result(result) or []
    if not isinstance(rows, list):
        rows = []
    return rows, None, rewritten, elapsed


def store_result(session_id: str, question: str, sql: str, rows: list[dict], tables: list[str] | None = None) -> str:
    if not session_id or not rows:
        return ""
    schema = {str(k): type(v).__name__ for k, v in rows[0].items()}
    return result_cache.cache_result(
        session_id=session_id,
        question=question,
        sql=sql,
        data=rows,
        tables=tables or [],
        schema=schema,
    )


def tool_payload(result_id: str, rows: list[dict], extra: dict | None = None) -> str:
    payload = compact_facts(rows)
    payload["result_id"] = result_id
    if extra:
        payload.update(extra)
    return json.dumps(payload, default=str)
