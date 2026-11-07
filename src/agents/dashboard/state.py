"""State that moves through the dashboard graphs.

Partial updates are normal, so every field is optional.
"""

from typing import Any, TypedDict


class ComposeState(TypedDict, total=False):
    requirement: str
    mode: str
    allowed_rep_codes: list[str]
    user_role: str | None
    user_id: str | None
    existing_widgets: list[dict[str, Any]]
    filters: dict[str, Any] | None
    error: str | None
    title: str | None
    specs: list[dict[str, Any]]
    filter_dimensions: list[str]
    built: list[dict[str, Any]]
    index: int
    dimension_values: dict[str, list[str]]
    dimension_columns: dict[str, str]
    widgets: list[dict[str, Any]]
    layout: list[dict[str, Any]]


class RefreshState(TypedDict, total=False):
    widgets: list[dict[str, Any]]
    allowed_rep_codes: list[str]
    error: str | None


class FilterState(TypedDict, total=False):
    widgets: list[dict[str, Any]]
    filters: dict[str, Any] | None
    allowed_rep_codes: list[str]
    user_role: str | None
    user_id: str | None
    index: int
    updated: list[dict[str, Any]]
    error: str | None


class WidgetSqlState(TypedDict, total=False):
    question: str
    widget_type: str
    chart_type: str
    allowed_rep_codes: list[str]
    plan: str | None
    relevant_tables: list[str] | None
    schema_context: str | None
    sql_query: str | None
    sql_explanation: str | None
    query_result: Any
    error: str | None
    error_type: str | None
    iterations: int
    should_retry: bool
