"""Compile a QuerySpec into MySQL with RLS and LIMIT by construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.infrastructure.config import settings
from src.semantic.layer import load_layer


@dataclass
class QuerySpec:
    metrics: list[str]
    dimensions: list[str] = field(default_factory=list)
    period: str = "current_month"
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int | None = None


def compile_sql(spec: QuerySpec) -> str:
    layer = load_layer()
    kpis = layer.get("kpis") or {}
    dimensions = layer.get("dimensions") or {}
    time_templates = layer.get("time_templates") or {}
    period = spec.period if spec.period in time_templates else "current_month"
    limit = spec.limit or settings.sql_max_rows

    metric_keys = list(spec.metrics)
    if "achievement_pct" in metric_keys:
        for required in ("net_value", "target"):
            if required not in metric_keys:
                metric_keys.insert(0, required)

    sales_metrics = [k for k in metric_keys if (kpis.get(k) or {}).get("fact_table") == "sales_flat"]
    target_metrics = [k for k in metric_keys if (kpis.get(k) or {}).get("fact_table") == "sales_targets"]
    dim_keys = [d for d in spec.dimensions if d in dimensions]

    uses_sales = bool(sales_metrics) or any(d in ("route", "customer", "product", "brand", "date") for d in dim_keys)
    uses_target = bool(target_metrics) or "target" in metric_keys or "achievement_pct" in spec.metrics

    if uses_sales and uses_target:
        return _compile_combined(spec, sales_metrics or ["net_value"], target_metrics or ["target"], dim_keys, period, limit, layer)

    if uses_target and not uses_sales:
        return _compile_single_fact("sales_targets", target_metrics or ["target"], dim_keys, period, limit, spec, layer)

    return _compile_single_fact("sales_flat", sales_metrics or ["net_value"], dim_keys, period, limit, spec, layer)


def _time_filter(layer: dict, period: str, fact: str) -> str:
    templates = (layer.get("time_templates") or {}).get(period) or {}
    return templates.get(fact) or "1=1"


def _metric_select(kpis: dict, keys: list[str]) -> list[str]:
    selects = []
    for key in keys:
        spec = kpis.get(key) or {}
        if spec.get("derived"):
            continue
        expr = spec.get("expression")
        alias = spec.get("alias") or key
        if expr:
            selects.append(f"{expr} AS {alias}")
    return selects or ["COUNT(*) AS RowCount"]


def _group_select(dimensions: dict, dim_keys: list[str], fact: str) -> tuple[list[str], list[str]]:
    select_cols: list[str] = []
    group_cols: list[str] = []
    for key in dim_keys:
        dim = dimensions.get(key) or {}
        expr = dim.get("expr")
        label = dim.get("label")
        if fact == "sales_targets" and key not in ("rep",):
            continue
        if not expr:
            continue
        alias_code = dim.get("alias_code") or key
        alias_name = dim.get("alias_name") or key
        select_cols.append(f"{expr} AS {alias_code}")
        group_cols.append(expr)
        if label and label != expr:
            select_cols.append(f"{label} AS {alias_name}")
            group_cols.append(label)
    return select_cols, group_cols


def _extra_filters(spec: QuerySpec, kpis: dict, keys: list[str]) -> list[str]:
    clauses: list[str] = []
    for key in keys:
        extra = (kpis.get(key) or {}).get("extra_filter")
        if extra:
            clauses.append(extra)
    if spec.filters.get("rep_code"):
        clauses.append(f"shn.Code = '{_escape(spec.filters['rep_code'])}'")
    if spec.filters.get("customer_name"):
        clauses.append(f"sf.CustomerName LIKE '%{_escape(spec.filters['customer_name'])}%'")
    if spec.filters.get("brand"):
        clauses.append(f"sf.Brand LIKE '%{_escape(spec.filters['brand'])}%'")
    if spec.filters.get("route"):
        clauses.append(f"sf.Route LIKE '%{_escape(spec.filters['route'])}%'")
    return clauses


def _escape(value: Any) -> str:
    return str(value).replace("'", "''")


def _compile_single_fact(
    fact: str,
    metric_keys: list[str],
    dim_keys: list[str],
    period: str,
    limit: int,
    spec: QuerySpec,
    layer: dict,
) -> str:
    kpis = layer.get("kpis") or {}
    dimensions = layer.get("dimensions") or {}
    alias = "sf" if fact == "sales_flat" else "st"
    id_col = "sf.RepId" if fact == "sales_flat" else "st.RepId"
    dim_select, group_cols = _group_select(dimensions, dim_keys or ["rep"], fact)
    metric_select = _metric_select(kpis, metric_keys)
    where = [
        "FIND_IN_SET(shn.Code, @AllowedNodes) > 0",
        _time_filter(layer, period, fact),
        *_extra_filters(spec, kpis, metric_keys),
    ]
    select_list = ",\n    ".join(dim_select + metric_select)
    group_sql = ", ".join(group_cols) if group_cols else "shn.Code, shn.Name"
    return f"""SELECT
    {select_list}
FROM {fact} AS {alias}
INNER JOIN sales_hierarchy_nodes AS shn ON shn.Id = {id_col}
WHERE {' AND '.join(where)}
GROUP BY {group_sql}
LIMIT {limit}"""


def _compile_combined(
    spec: QuerySpec,
    sales_metrics: list[str],
    target_metrics: list[str],
    dim_keys: list[str],
    period: str,
    limit: int,
    layer: dict,
) -> str:
    kpis = layer.get("kpis") or {}
    sales_select = _metric_select(kpis, sales_metrics)
    target_select = _metric_select(kpis, target_metrics)
    sales_where = [
        "FIND_IN_SET(shn.Code, @AllowedNodes) > 0",
        _time_filter(layer, period, "sales_flat"),
        *_extra_filters(spec, kpis, sales_metrics),
    ]
    target_where = [
        "FIND_IN_SET(shn.Code, @AllowedNodes) > 0",
        _time_filter(layer, period, "sales_targets"),
        *_extra_filters(spec, kpis, target_metrics),
    ]
    outer_metrics = ["a.NetSales", "t.SalesTarget"]
    if "achievement_pct" in spec.metrics:
        outer_metrics.append("ROUND(a.NetSales / NULLIF(t.SalesTarget, 0) * 100, 2) AS AchievementPct")
        outer_metrics.append("t.SalesTarget - a.NetSales AS Balance")
    sales_metric_sql = ",\n           ".join(sales_select) or "SUM(CASE WHEN sf.Type = 'sales' THEN sf.NetValue ELSE -sf.NetValue END) AS NetSales"
    target_metric_sql = ",\n           ".join(target_select) or "SUM(st.Value) AS SalesTarget"
    return f"""WITH achievement AS (
    SELECT shn.Code AS RepCode,
           shn.Name AS RepName,
           {sales_metric_sql}
    FROM sales_flat AS sf
    INNER JOIN sales_hierarchy_nodes AS shn ON shn.Id = sf.RepId
    WHERE {' AND '.join(sales_where)}
    GROUP BY shn.Code, shn.Name
),
target AS (
    SELECT shn.Code AS RepCode,
           shn.Name AS RepName,
           {target_metric_sql}
    FROM sales_targets AS st
    INNER JOIN sales_hierarchy_nodes AS shn ON shn.Id = st.RepId
    WHERE {' AND '.join(target_where)}
    GROUP BY shn.Code, shn.Name
)
SELECT a.RepCode,
       a.RepName,
       {', '.join(outer_metrics)}
FROM achievement AS a
LEFT JOIN target AS t ON t.RepCode = a.RepCode
LIMIT {limit}"""
