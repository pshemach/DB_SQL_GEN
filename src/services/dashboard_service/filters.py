"""Dashboard-wide filters. Field names come from the planned requirement, not a fixed list."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp


def empty_filters() -> dict[str, Any]:
    return {
        "date_from": None,
        "date_to": None,
        "fields": [],
        "dimensions": [],
        "dimension_values": {},
        "dimension_columns": {},
    }


def normalize_dimensions(raw: Any) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        name = str(item or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def normalize_filters(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    fields: list[dict[str, Any]] = []
    for item in data.get("fields") or []:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column") or "").strip()
        values = [
            str(value)
            for value in (item.get("values") or [])
            if value is not None and str(value).strip() != ""
        ]
        if column and values:
            fields.append({"column": column, "values": values})
    dimension_values: dict[str, list[str]] = {}
    raw_values = data.get("dimension_values") if isinstance(data.get("dimension_values"), dict) else {}
    for key, vals in raw_values.items():
        name = str(key or "").strip()
        if not name:
            continue
        cleaned = [
            str(value)
            for value in (vals or [])
            if value is not None and str(value).strip() != ""
        ]
        if cleaned:
            dimension_values[name] = cleaned
    dimension_columns: dict[str, str] = {}
    raw_cols = data.get("dimension_columns") if isinstance(data.get("dimension_columns"), dict) else {}
    for key, val in raw_cols.items():
        name = str(key or "").strip()
        column = str(val or "").strip()
        if name and column:
            dimension_columns[name] = column
    return {
        "date_from": _clean_date(data.get("date_from")),
        "date_to": _clean_date(data.get("date_to")),
        "fields": fields,
        "dimensions": normalize_dimensions(data.get("dimensions")),
        "dimension_values": dimension_values,
        "dimension_columns": dimension_columns,
    }


def has_filters(filters: Any) -> bool:
    data = normalize_filters(filters)
    return bool(data["date_from"] or data["date_to"] or data["fields"])


def format_filter_block(filters: Any) -> str:
    data = normalize_filters(filters)
    lines: list[str] = []
    if data["date_from"] and data["date_to"]:
        lines.append(f"- Date range: {data['date_from']} to {data['date_to']}")
    elif data["date_from"]:
        lines.append(f"- Date from: {data['date_from']}")
    elif data["date_to"]:
        lines.append(f"- Date to: {data['date_to']}")
    for item in data["fields"]:
        joined = ", ".join(item["values"])
        lines.append(f"- {item['column']} is one of: {joined}")
    return "\n".join(lines)


def question_with_filters(question: str, filters: Any) -> str:
    """Keep the original widget question and append active dashboard filters."""
    block = format_filter_block(filters)
    if not block:
        return question or ""
    return (
        f"{question or ''}\n\n"
        "Apply these dashboard filters as WHERE-style restrictions only. "
        "Keep the original metric and chart breakdown. Do not group or split "
        "the result by these filter fields. They override any conflicting "
        "time period already in the question.\n"
        f"{block}"
    )


def filter_columns(widgets: list[dict[str, Any]] | None) -> list[str]:
    """Category-like columns taken from current widget rows."""
    names: list[str] = []
    seen: set[str] = set()
    for widget in widgets or []:
        rows = widget.get("last_rows") or []
        if not isinstance(rows, list) or not rows:
            continue
        sample = rows[0]
        if not isinstance(sample, dict):
            continue
        for column in sample.keys():
            key = str(column)
            if key in seen or _column_is_numeric(rows, key):
                continue
            seen.add(key)
            names.append(key)
    return names


def filter_values(widgets: list[dict[str, Any]] | None, column: str, limit: int = 80) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for widget in widgets or []:
        for row in widget.get("last_rows") or []:
            if not isinstance(row, dict) or column not in row:
                continue
            raw = row.get(column)
            if raw is None or str(raw).strip() == "":
                continue
            text = str(raw)
            if text in seen:
                continue
            seen.add(text)
            values.append(text)
            if len(values) >= limit:
                return values
    values.sort()
    return values


def merge_filter_fields(
    widgets: list[dict[str, Any]] | None,
    filters: Any = None,
) -> list[dict[str, Any]]:
    """Only slicer dimensions from the dashboard requirement."""
    data = normalize_filters(filters)
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    stored_values = data.get("dimension_values") or {}
    stored_lower = {str(key).lower(): vals for key, vals in stored_values.items()}

    for column in data.get("dimensions") or []:
        key = column.lower()
        if not column or key in seen:
            continue
        seen.add(key)
        stored = stored_values.get(column) or stored_lower.get(key) or []
        from_rows = filter_values(widgets, column)
        fields.append({"column": column, "values": from_rows or list(stored)})
    return fields


def base_sql(widget: dict[str, Any] | None) -> str:
    data = widget or {}
    return str(data.get("base_sql_query") or data.get("sql_query") or "").strip()


def inject_filters_into_sql(sql: str, filters: Any) -> str:
    """Add WHERE predicates to existing SQL. Does not generate a new query."""
    text = (sql or "").strip()
    data = normalize_filters(filters)
    if not text or not has_filters(data):
        return text

    parsed = None
    for dialect in ("mysql", "tsql"):
        try:
            parsed = sqlglot.parse_one(text, dialect=dialect)
            break
        except Exception:
            continue
    if parsed is None:
        return text

    cte_names = {
        str(cte.alias or "").lower()
        for cte in parsed.find_all(exp.CTE)
        if cte.alias
    }
    predicates_by_ident = _filter_predicates(data)
    if not predicates_by_ident:
        return text

    injected = False
    for select in list(parsed.find_all(exp.Select)):
        if not _selects_base_tables(select, cte_names):
            continue
        combined = None
        for ident, predicate in predicates_by_ident:
            column = _column_for_select(select, ident, cte_names)
            node = predicate.copy()
            node.set("this", column)
            combined = node if combined is None else exp.and_(combined, node)
        if combined is not None:
            select.where(combined, copy=False)
            injected = True
    if not injected:
        return text
    return parsed.sql(dialect="mysql")


def _filter_predicates(data: dict[str, Any]) -> list[tuple[str, exp.Expression]]:
    items: list[tuple[str, exp.Expression]] = []
    columns = data.get("dimension_columns") or {}
    columns_lower = {str(key).lower(): val for key, val in columns.items()}
    for field in data.get("fields") or []:
        ident = columns.get(field["column"]) or columns_lower.get(str(field["column"]).lower()) or field["column"]
        values = [
            exp.Literal.string(str(value))
            for value in field.get("values") or []
            if value is not None and str(value).strip() != ""
        ]
        if not values:
            continue
        items.append((ident, exp.In(this=exp.column(ident), expressions=values)))
    return items


def _selects_base_tables(select: exp.Select, cte_names: set[str]) -> bool:
    return any(
        (table.name or "").lower() not in cte_names
        for table in _from_tables(select)
        if table.name
    )


def _from_tables(select: exp.Select) -> list[exp.Table]:
    tables: list[exp.Table] = []
    from_node = select.args.get("from_") or select.args.get("from")
    source = from_node.this if from_node is not None else None
    table = _as_table(source)
    if table:
        tables.append(table)
    for join in select.args.get("joins") or []:
        joined = _as_table(join.this)
        if joined:
            tables.append(joined)
    return tables


def _as_table(node: exp.Expression | None) -> exp.Table | None:
    if node is None:
        return None
    alias = None
    table = node
    if isinstance(node, exp.Alias):
        alias = node.alias
        table = node.this
    if not isinstance(table, exp.Table):
        return None
    if alias and not table.alias:
        table = table.copy()
        table.set("alias", exp.to_identifier(alias))
    return table


def selected_sql_column(sql: str | None) -> str | None:
    """First selected column from a DISTINCT-values query, with table alias if present."""
    text = (sql or "").strip()
    if not text:
        return None
    parsed = None
    for dialect in ("mysql", "tsql"):
        try:
            parsed = sqlglot.parse_one(text, dialect=dialect)
            break
        except Exception:
            continue
    if parsed is None:
        return None
    select = parsed if isinstance(parsed, exp.Select) else parsed.find(exp.Select)
    if select is None or not select.expressions:
        return None
    first = select.expressions[0]
    column = first.this if isinstance(first, exp.Alias) else first
    if not isinstance(column, exp.Column) or not column.name:
        return None
    table = column.table
    return f"{table}.{column.name}" if table else column.name


def _split_ident(ident: str) -> tuple[str | None, str]:
    cleaned = str(ident or "").replace("`", "").replace('"', "").strip()
    if "." in cleaned:
        table, name = cleaned.split(".", 1)
        return table, name
    return None, cleaned


def _column_for_select(select: exp.Select, ident: str, cte_names: set[str]) -> exp.Column:
    table_part, name = _split_ident(ident)
    tables = [
        table for table in _from_tables(select)
        if (table.name or "").lower() not in cte_names
    ]
    by_alias = {(table.alias or table.name or "").lower(): table for table in tables}
    by_name = {(table.name or "").lower(): table for table in tables}
    if table_part:
        matched = by_alias.get(table_part.lower()) or by_name.get(table_part.lower())
        if matched:
            return exp.column(name, table=matched.alias_or_name)
    if len(tables) == 1:
        return exp.column(name, table=tables[0].alias_or_name)
    return exp.column(name)


def _clean_date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _column_is_numeric(rows: list[dict[str, Any]], column: str) -> bool:
    seen = 0
    numeric = 0
    for row in rows[:40]:
        value = row.get(column)
        if value is None or str(value).strip() == "":
            continue
        seen += 1
        try:
            float(str(value).replace(",", ""))
            numeric += 1
        except (TypeError, ValueError):
            return False
    return seen > 0 and numeric == seen
