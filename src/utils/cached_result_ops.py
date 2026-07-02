"""Execute validated transform specs on cached rows (safe pandas only)."""

from __future__ import annotations

from typing import Any

import pandas as pd
from loguru import logger

from .transform_spec_postprocess import resolve_column

_FILTER_OPS = {"gt", "gte", "lt", "lte", "eq", "ne", "contains"}


def execute_transform_spec(
    data: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Apply a post-processed transform spec.
    Returns (rows, metadata). metadata.type=needs_new_sql triggers SQL fallback.
    """
    if not data:
        return [], {"type": "empty", "spec": spec}

    if spec.get("needs_new_sql") or not spec.get("can_answer_from_cache"):
        return [], {"type": "needs_new_sql", "spec": spec}

    df = pd.DataFrame(data)
    columns = [str(c) for c in df.columns]
    meta: dict[str, Any] = {
        "type": spec.get("operation", "use_all"),
        "spec": spec,
        "steps_applied": [],
    }

    # 1) Per-group top rows (e.g. best product per rep)
    group_cfg = spec.get("group_top_per")
    if isinstance(group_cfg, dict):
        df, step = _apply_group_top_per(df, group_cfg, columns)
        if step.get("skipped"):
            return [], {"type": "needs_new_sql", "spec": spec, "reason": step.get("reason")}
        meta["steps_applied"].append(step)
        meta["rows_after"] = len(df)
        return df.to_dict("records"), meta

    # 2) Filters
    for f in spec.get("filters") or []:
        if not isinstance(f, dict):
            continue
        col = f.get("column") or resolve_column(f.get("column"), columns)
        if not col or col not in df.columns:
            continue
        op = (f.get("op") or "eq").lower()
        val = f.get("value")
        if op not in _FILTER_OPS:
            continue
        series = _coerce_numeric(df[col]) if op != "contains" else df[col].astype(str)
        try:
            if op == "gt":
                df = df.loc[series > float(val)]
            elif op == "gte":
                df = df.loc[series >= float(val)]
            elif op == "lt":
                df = df.loc[series < float(val)]
            elif op == "lte":
                df = df.loc[series <= float(val)]
            elif op == "eq":
                df = df.loc[series == val]
            elif op == "ne":
                df = df.loc[series != val]
            elif op == "contains":
                df = df.loc[series.str.contains(str(val), case=False, na=False)]
            meta["steps_applied"].append(f"filter:{col}{op}{val}")
        except (TypeError, ValueError) as e:
            logger.warning(f"Filter skipped ({col} {op} {val}): {e}")

    # 3) Sort
    sort_cfg = spec.get("sort")
    sort_applied = False
    if isinstance(sort_cfg, dict):
        col = sort_cfg.get("column") or resolve_column(sort_cfg.get("column"), columns)
        if col and col in df.columns:
            asc = (sort_cfg.get("direction") or "desc").lower() == "asc"
            df = df.copy()
            df["_sort_val"] = _coerce_numeric(df[col])
            df = df.dropna(subset=["_sort_val"]).sort_values(
                "_sort_val", ascending=asc
            ).drop(columns=["_sort_val"])
            sort_applied = True
            meta["steps_applied"].append(f"sort:{col}:{sort_cfg.get('direction')}")

    # 4) Rank (requires prior sort when specified in spec)
    rank = spec.get("rank")
    if rank is not None:
        if isinstance(sort_cfg, dict) and not sort_applied:
            return [], {
                **meta,
                "type": "needs_new_sql",
                "reason": "sort column missing for rank",
            }
        try:
            r = int(rank)
            idx = (len(df) - 1) if r == -1 else (r - 1)
            if 0 <= idx < len(df):
                df = df.iloc[[idx]]
                meta["steps_applied"].append(f"rank:{r}")
            else:
                return [], {**meta, "error": "rank_out_of_range"}
        except (TypeError, ValueError):
            pass

    # 5) Limit / head
    limit = spec.get("limit")
    if limit is not None:
        try:
            df = df.head(int(limit))
            meta["steps_applied"].append(f"limit:{limit}")
        except (TypeError, ValueError):
            pass
    elif spec.get("operation") == "head" and limit is None:
        df = df.head(10)
        meta["steps_applied"].append("head:10")

    meta["rows_after"] = len(df)
    return df.to_dict("records"), meta


def _apply_group_top_per(
    df: pd.DataFrame, cfg: dict, columns: list[str]
) -> tuple[pd.DataFrame, dict]:
    gb = cfg.get("group_by") or resolve_column(cfg.get("group_by"), columns)
    vc = cfg.get("value_column") or resolve_column(cfg.get("value_column"), columns)
    if not gb or not vc or gb not in df.columns or vc not in df.columns:
        return df, {
            "skipped": True,
            "reason": f"group_top_per columns missing: group={gb} value={vc}",
        }
    ascending = (cfg.get("direction") or "desc").lower() == "asc"
    take = max(1, int(cfg.get("take_per_group") or 1))
    work = df.copy()
    work["_sort_val"] = _coerce_numeric(work[vc])
    work = work.dropna(subset=["_sort_val"])
    if work.empty:
        return work, {"skipped": True, "reason": "no numeric values for group_top_per"}
    work = work.sort_values("_sort_val", ascending=ascending)
    out = work.groupby(gb, as_index=False, sort=False).head(take)
    out = out.drop(columns=["_sort_val"], errors="ignore")
    return out, {"group_top_per": gb, "value_column": vc, "take": take}


def _coerce_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
