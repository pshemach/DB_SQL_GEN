"""
Normalize and validate LLM transform specs before execution.
No question-specific rules — schema and row feasibility only.
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

_ALLOWED_OPS = frozenset({"use_all", "filter", "sort", "head", "row_at_rank", "group_top_per"})


def resolve_column(name: str | None, columns: list[str]) -> str | None:
    """Map LLM column name to an actual result column (case/snake insensitive)."""
    if not name or not columns:
        return None
    if name in columns:
        return name

    norm = _col_key(name)
    by_key = {_col_key(c): c for c in columns}
    if norm in by_key:
        return by_key[norm]

    # Partial match (e.g. netsales -> NetSales)
    for key, original in by_key.items():
        if norm in key or key in norm:
            return original
    return None


def _col_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def parse_operation(raw: str | None) -> str:
    """
    LLMs often return compound ops like 'use_all | sort | row_at_rank'.
    Pick the effective primary op for logging; execution always runs filter→sort→rank→limit.
    """
    if not raw:
        return "use_all"
    text = str(raw).lower()
    parts = [p.strip() for p in re.split(r"\||,", text) if p.strip()]
    priority = ("group_top_per", "row_at_rank", "filter", "sort", "head", "use_all")
    for op in priority:
        if op in parts:
            return op
    first = parts[0] if parts else "use_all"
    return first if first in _ALLOWED_OPS else "use_all"


def normalize_and_validate_spec(
    spec: dict[str, Any],
    columns: list[str],
    row_count: int,
    explanation: str = "",
) -> dict[str, Any]:
    """
    Resolve columns, coerce types, and downgrade to needs_new_sql when
    the plan cannot run on the cached row set.
    """
    out: dict[str, Any] = {
        "can_answer_from_cache": bool(spec.get("can_answer_from_cache", True)),
        "needs_new_sql": bool(spec.get("needs_new_sql", False)),
        "operation": parse_operation(spec.get("operation")),
        "filters": [],
        "sort": None,
        "limit": _safe_int(spec.get("limit")),
        "rank": _safe_int(spec.get("rank")),
        "group_top_per": None,
        "explanation": (spec.get("explanation") or explanation or "").strip(),
        "postprocess_notes": [],
    }

    raw_group = spec.get("group_top_per") or spec.get("group_by_top")
    if isinstance(raw_group, dict):
        out["group_top_per"] = _normalize_group_top(raw_group, columns)

    for f in spec.get("filters") or []:
        if not isinstance(f, dict):
            continue
        col = resolve_column(f.get("column"), columns)
        if not col:
            out["postprocess_notes"].append(f"filter column not found: {f.get('column')}")
            continue
        out["filters"].append({
            "column": col,
            "op": (f.get("op") or "eq").lower(),
            "value": f.get("value"),
        })

    sort_raw = spec.get("sort")
    if isinstance(sort_raw, dict):
        col = resolve_column(sort_raw.get("column"), columns)
        if col:
            direction = (sort_raw.get("direction") or "desc").lower()
            if direction not in ("asc", "desc"):
                direction = "desc"
            out["sort"] = {"column": col, "direction": direction}
        else:
            out["postprocess_notes"].append(
                f"sort column not found: {sort_raw.get('column')}"
            )

    notes = out["postprocess_notes"]
    expl = out["explanation"].lower()

    # Per-entity aggregation ("for each rep", "by customer", …) needs group_top_per or SQL
    if _implies_per_group(expl) or out["operation"] == "group_top_per":
        if out["group_top_per"]:
            gb = out["group_top_per"].get("group_by")
            vc = out["group_top_per"].get("value_column")
            if not gb or not vc:
                out["needs_new_sql"] = True
                out["can_answer_from_cache"] = False
                notes.append("group_top_per missing group_by or value_column")
        elif not out["group_top_per"]:
            inferred = _infer_group_top(columns, expl)
            if inferred:
                out["group_top_per"] = inferred
                out["operation"] = "group_top_per"
            else:
                out["needs_new_sql"] = True
                out["can_answer_from_cache"] = False
                notes.append("per-group question but no groupable columns in cache")

    # rank/sort requested but sort column missing → cannot answer from cache
    if out["rank"] is not None and out["sort"] is None and not out["group_top_per"]:
        if any("sort column not found" in n for n in notes):
            out["needs_new_sql"] = True
            out["can_answer_from_cache"] = False
            notes.append("rank requires valid sort column")

    if out["filters"] and not columns:
        out["needs_new_sql"] = True
        out["can_answer_from_cache"] = False

    if row_count == 0:
        out["needs_new_sql"] = True
        out["can_answer_from_cache"] = False

    if out["needs_new_sql"]:
        out["can_answer_from_cache"] = False

    if notes:
        logger.info(f"Transform spec postprocess: {notes}")

    return out


def _normalize_group_top(raw: dict, columns: list[str]) -> dict[str, Any] | None:
    gb = resolve_column(raw.get("group_by") or raw.get("group_column"), columns)
    vc = resolve_column(
        raw.get("value_column") or raw.get("metric_column") or raw.get("sort_column"),
        columns,
    )
    if not gb or not vc:
        return None
    direction = (raw.get("direction") or "desc").lower()
    return {
        "group_by": gb,
        "value_column": vc,
        "direction": "asc" if direction == "asc" else "desc",
        "take_per_group": max(1, _safe_int(raw.get("take_per_group") or raw.get("take") or 1) or 1),
    }


def _infer_group_top(columns: list[str], explanation: str) -> dict[str, Any] | None:
    """Infer group_by + value from column names only (no fixed business terms)."""
    if not columns:
        return None
    expl = explanation.lower()
    group_candidates = []
    value_candidates = []
    for c in columns:
        key = _col_key(c)
        if any(
            t in key
            for t in ("rep", "customer", "client", "outlet", "region", "route", "name", "code")
        ):
            if "product" not in key or "rep" in key:
                group_candidates.append(c)
        if any(
            t in key
            for t in ("sales", "amount", "revenue", "net", "total", "value", "qty", "quantity")
        ):
            value_candidates.append(c)
    if not group_candidates or not value_candidates:
        return None
    if not _implies_per_group(expl):
        return None
    return {
        "group_by": group_candidates[0],
        "value_column": value_candidates[0],
        "direction": "desc",
        "take_per_group": 1,
    }


def _implies_per_group(text: str) -> bool:
    if not text:
        return False
    return bool(
        re.search(
            r"\b(?:each|per|for every|by\s+\w+|top\s+\w+\s+(?:for|per|by))\b",
            text,
            re.I,
        )
    )


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
