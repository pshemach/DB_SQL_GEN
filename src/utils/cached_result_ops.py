"""Deterministic pandas ops on cached query rows for follow-up turns."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

import pandas as pd

from .follow_up_utils import extract_limit_from_question, extract_rank_from_question

Op = Literal["gt", "gte", "lt", "lte", "eq"]

_VALUE_COLUMN_HINTS = (
    "netsales",
    "net_sales",
    "sales",
    "revenue",
    "amount",
    "total",
    "value",
    "achievement",
    "target",
    "in_sales",
)

_SUPERLATIVE_MAX = re.compile(
    r"\b(best|highest|top|maximum|max|leading|greatest)\b",
    re.I,
)
_SUPERLATIVE_MIN = re.compile(
    r"\b(worst|lowest|bottom|minimum|min|poorest|smallest)\b",
    re.I,
)


def extract_numeric_threshold(question: str) -> Optional[tuple[Op, float]]:
    """Parse comparisons like 'above 30000', 'greater than 1.5m'."""
    q = (question or "").lower().replace(",", "")
    patterns: list[tuple[str, Op]] = [
        (r"(?:above|over|more\s+than|greater\s+than|>\s*)\s*([\d.]+)\s*([km])?", "gt"),
        (r"(?:at\s+least|minimum\s+of|>=\s*)\s*([\d.]+)\s*([km])?", "gte"),
        (r"(?:below|under|less\s+than|fewer\s+than|<\s*)\s*([\d.]+)\s*([km])?", "lt"),
        (r"(?:at\s+most|maximum\s+of|<=\s*)\s*([\d.]+)\s*([km])?", "lte"),
        (r"(?:equal\s+to|exactly)\s*([\d.]+)\s*([km])?", "eq"),
    ]
    for pattern, op in patterns:
        m = re.search(pattern, q)
        if m:
            val = float(m.group(1))
            suffix = (m.group(2) or "").lower()
            if suffix == "k":
                val *= 1000
            elif suffix == "m":
                val *= 1_000_000
            return op, val
    return None


def is_ranking_question(question: str) -> bool:
    q = question or ""
    return bool(_SUPERLATIVE_MAX.search(q) or _SUPERLATIVE_MIN.search(q))


def pick_value_column(df: pd.DataFrame, question: str = "") -> Optional[str]:
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric:
        for c in df.columns:
            try:
                pd.to_numeric(df[c].replace({",": ""}, regex=True), errors="coerce")
                numeric.append(c)
            except Exception:
                pass
    if not numeric:
        return None

    q = (question or "").lower()
    for col in numeric:
        key = col.lower().replace(" ", "_")
        if any(h in key for h in _VALUE_COLUMN_HINTS) or any(
            h in q for h in _VALUE_COLUMN_HINTS if h in key
        ):
            return col
    return numeric[0]


def pick_label_column(df: pd.DataFrame, value_col: str) -> Optional[str]:
    for c in df.columns:
        if c == value_col:
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            return c
    return None


def _coerce_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(
        df[col].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )


def apply_filter(df: pd.DataFrame, col: str, op: Op, value: float) -> pd.DataFrame:
    series = _coerce_numeric(df, col)
    if op == "gt":
        mask = series > value
    elif op == "gte":
        mask = series >= value
    elif op == "lt":
        mask = series < value
    elif op == "lte":
        mask = series <= value
    else:
        mask = series == value
    return df.loc[mask.fillna(False)].copy()


def apply_cached_follow_up(
    data: list[dict[str, Any]],
    question: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Apply follow-up logic on the previous result set (no SQL).
    Returns (rows, metadata about transform).
    """
    if not data:
        return [], {"type": "empty"}

    df = pd.DataFrame(data)
    meta: dict[str, Any] = {"type": "reuse_cache"}
    q = question or ""

    rank = extract_rank_from_question(q)
    if rank is not None:
        index = (len(df) - 1) if rank == -1 else (rank - 1)
        if 0 <= index < len(df):
            return [df.iloc[index].to_dict()], {"type": "lookup", "rank": rank}
        return [], {"type": "lookup", "rank": rank, "error": "rank_out_of_range"}

    value_col = pick_value_column(df, q)
    if value_col is None:
        limit = extract_limit_from_question(q)
        if limit:
            return df.head(limit).to_dict("records"), {"type": "limit", "limit": limit}
        return df.to_dict("records"), meta

    threshold = extract_numeric_threshold(q)
    if threshold is not None:
        op, val = threshold
        filtered = apply_filter(df, value_col, op, val)
        meta = {
            "type": "filter",
            "column": value_col,
            "op": op,
            "value": val,
            "rows_before": len(df),
            "rows_after": len(filtered),
        }
        return filtered.to_dict("records"), meta

    if is_ranking_question(q):
        series = _coerce_numeric(df, value_col)
        df = df.copy()
        df["_sort_val"] = series
        df = df.dropna(subset=["_sort_val"])
        if df.empty:
            return [], {"type": "ranking", "error": "no_numeric_values"}
        ascending = bool(_SUPERLATIVE_MIN.search(q)) and not _SUPERLATIVE_MAX.search(q)
        df = df.sort_values("_sort_val", ascending=ascending)
        df = df.drop(columns=["_sort_val"])
        limit = 1
        if re.search(r"\btop\s+(\d+)\b", q, re.I):
            limit = int(re.search(r"\btop\s+(\d+)\b", q, re.I).group(1))
        meta = {"type": "ranking", "column": value_col, "ascending": ascending, "limit": limit}
        return df.head(limit).to_dict("records"), meta

    limit = extract_limit_from_question(q)
    if limit:
        return df.head(limit).to_dict("records"), {"type": "limit", "limit": limit}

    return df.to_dict("records"), meta
