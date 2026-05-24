"""
JSON/msgpack-safe serialization for graph state and API responses.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


def _is_sqlalchemy_type(value: Any) -> bool:
    """Detect SQLAlchemy TypeEngine / dialect type objects (e.g. DATE())."""
    try:
        from sqlalchemy.sql.type_api import TypeEngine

        if isinstance(value, TypeEngine):
            return True
    except ImportError:
        pass
    mod = getattr(type(value), "__module__", "") or ""
    return mod.startswith("sqlalchemy") and type(value).__name__ in (
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
    """Convert a single value to a checkpoint/JSON-safe type."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if _is_sqlalchemy_type(value):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [json_safe_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe_value(v) for k, v in value.items()}

    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return json_safe_value(value.tolist())
        if isinstance(value, (np.integer, np.floating)):
            return value.item()
    except ImportError:
        pass

    # Row-like objects
    if hasattr(value, "_mapping"):
        return json_safe_value(dict(value._mapping))

    type_name = type(value).__name__
    if type_name in ("DATE", "DATETIME", "TIMESTAMP", "TIME", "TIMEDELTA"):
        return str(value)

    return str(value)


def serialize_query_result(query_result: Any) -> list[dict] | str | None:
    """
    Convert SQLAlchemy rows into plain dicts with JSON/msgpack-safe values.
    Required before storing query_result in LangGraph state (checkpointer).
    """
    if query_result is None:
        return None

    if isinstance(query_result, str):
        return query_result

    if not isinstance(query_result, (list, tuple)):
        return json_safe_value(query_result)

    serialized: list[dict] = []
    for row in query_result:
        if hasattr(row, "_mapping"):
            raw = dict(row._mapping)
        elif isinstance(row, dict):
            raw = row
        else:
            raw = (
                dict(zip(range(len(row)), row))
                if hasattr(row, "__iter__") and not isinstance(row, (str, bytes))
                else {"value": row}
            )

        serialized.append({str(k): json_safe_value(v) for k, v in raw.items()})

    return serialized


def sanitize_state(data: Any) -> Any:
    """
    Deep-sanitize graph node output for LangGraph checkpointer (msgpack).
    Handles SQLAlchemy schema types, rows, numpy, dates, etc.
    """
    if data is None or isinstance(data, (str, int, float, bool)):
        return data
    if isinstance(data, (datetime, date, time)):
        return data.isoformat()
    if isinstance(data, Decimal):
        return float(data)
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    if _is_sqlalchemy_type(data):
        return str(data)
    if isinstance(data, dict):
        return {str(k): sanitize_state(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [sanitize_state(v) for v in data]
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

    try:
        from sqlalchemy.sql.type_api import TypeEngine

        if isinstance(data, TypeEngine):
            return str(data)
    except ImportError:
        pass

    return json_safe_value(data)