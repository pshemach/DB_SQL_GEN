"""Compose dashboard widgets by planning, then reusing the SQL pipeline."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from src.services.dashboard_service.filters import (
    base_sql,
    filter_columns,
    filter_values,
    has_filters,
    inject_filters_into_sql,
    normalize_dimensions,
    selected_sql_column,
)
from src.services.dashboard_service.layout import pack_layout
from src.services.dashboard_service.planner import DashboardPlanner
from src.agents.orchestrator import orchestrator
from src.infrastructure.db import db_manager
from src.infrastructure.db.sql_safety import assess_sql
from src.infrastructure.utils import serialize_query_result

WIDGET_ROW_CAP = 200


class DashboardComposer:
    def __init__(self, planner: DashboardPlanner | None = None) -> None:
        self._planner = planner

    @property
    def planner(self) -> DashboardPlanner:
        if self._planner is None:
            self._planner = DashboardPlanner()
        return self._planner

    def compose(
        self,
        requirement: str,
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
        existing_widgets: list[dict[str, Any]] | None = None,
        mode: str = "compose",
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        denied = self._access_error(allowed_rep_codes)
        if denied:
            return denied

        guard = self._guard(requirement, user_role)
        if guard:
            return guard

        plan = self.planner.plan(
            requirement,
            existing_widgets=existing_widgets,
            mode=mode,
        )
        widgets = [
            self.build_widget(
                spec,
                allowed_rep_codes=allowed_rep_codes,
                user_role=user_role,
                user_id=user_id,
            )
            for spec in plan.get("widgets") or []
        ]
        if has_filters(filters):
            widgets = [
                self.apply_filters_to_widget(widget, filters, allowed_rep_codes)
                for widget in widgets
            ]
        if mode == "add" and existing_widgets:
            widgets = list(existing_widgets) + widgets
        dimensions = normalize_dimensions(plan.get("filter_dimensions"))
        dimension_values, dimension_columns = self.load_dimension_values(
            dimensions,
            widgets,
            allowed_rep_codes=allowed_rep_codes,
            user_role=user_role,
            user_id=user_id,
        )
        return {
            "success": True,
            "error": None,
            "title": plan.get("title") or "Sales dashboard",
            "widgets": widgets,
            "layout": pack_layout(widgets),
            "filter_dimensions": dimensions,
            "dimension_values": dimension_values,
            "dimension_columns": dimension_columns,
        }

    async def stream_compose(
        self,
        requirement: str,
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
        existing_widgets: list[dict[str, Any]] | None = None,
        mode: str = "compose",
        filters: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        denied = self._access_error(allowed_rep_codes)
        if denied:
            yield {"type": "error", "error": denied["error"]}
            yield {"type": "done"}
            return

        yield {"type": "status", "text": "Checking your request..."}
        guard = self._guard(requirement, user_role)
        if guard:
            yield {"type": "error", "error": guard["error"]}
            yield {"type": "done"}
            return

        yield {"type": "status", "text": "Planning widgets..."}
        plan = await _to_thread(
            self.planner.plan,
            requirement,
            existing_widgets=existing_widgets,
            mode=mode,
        )
        specs = plan.get("widgets") or []
        placeholders = list(existing_widgets or []) if mode == "add" else []
        planned = placeholders + [
            {
                **spec,
                "sql_query": None,
                "sql_explanation": None,
                "last_rows": [],
                "last_error": None,
                "chart": {"chart_type": spec.get("chart_type")},
                "status": "pending",
            }
            for spec in specs
        ]
        layout = pack_layout(planned)
        dimensions = normalize_dimensions(plan.get("filter_dimensions"))
        yield {
            "type": "plan",
            "title": plan.get("title") or "Sales dashboard",
            "widgets": planned,
            "layout": layout,
            "filter_dimensions": dimensions,
        }

        built: list[dict[str, Any]] = list(placeholders)
        total = len(specs)
        for index, spec in enumerate(specs, start=1):
            yield {
                "type": "status",
                "text": f"Building widget {index} of {total}: {spec.get('title')}",
            }
            widget = await _to_thread(
                self.build_widget,
                spec,
                allowed_rep_codes=allowed_rep_codes,
                user_role=user_role,
                user_id=user_id,
            )
            if has_filters(filters):
                widget = self.apply_filters_to_widget(widget, filters, allowed_rep_codes)
            built.append(widget)
            yield {"type": "widget_ready", "widget": widget}

        dimension_values: dict[str, list[str]] = {}
        dimension_columns: dict[str, str] = {}
        if dimensions:
            yield {"type": "status", "text": "Loading filter values..."}
            dimension_values, dimension_columns = await _to_thread(
                self.load_dimension_values,
                dimensions,
                built,
                allowed_rep_codes=allowed_rep_codes,
                user_role=user_role,
                user_id=user_id,
            )

        payload = {
            "success": True,
            "error": None,
            "title": plan.get("title") or "Sales dashboard",
            "widgets": built,
            "layout": pack_layout(built),
            "filter_dimensions": dimensions,
            "dimension_values": dimension_values,
            "dimension_columns": dimension_columns,
        }
        yield {"type": "result", "payload": payload}
        yield {"type": "done"}

    def build_widget(
        self,
        spec: dict[str, Any],
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
        question_override: str | None = None,
    ) -> dict[str, Any]:
        original_question = spec.get("question") or ""
        question = question_override or original_question
        result = orchestrator.run_sql_only(
            question,
            allowed_rep_codes=allowed_rep_codes,
            user_role=user_role,
            user_id=user_id,
        )
        rows = _cap_rows(serialize_query_result(result.get("query_result")))
        error = result.get("error")
        chart = orchestrator.formatter.chart_spec_from_rows(
            rows if isinstance(rows, list) else [],
            requested_chart_type=spec.get("chart_type"),
            widget_type=spec.get("type") or "chart",
            title=spec.get("title"),
        )
        return {
            "widget_id": spec.get("widget_id"),
            "title": spec.get("title") or "Widget",
            "type": spec.get("type") or "chart",
            "chart_type": (chart.get("chart_type") if chart.get("enabled") else spec.get("chart_type")),
            "question": original_question,
            "sql_query": result.get("sql_query"),
            "base_sql_query": spec.get("base_sql_query") or result.get("sql_query"),
            "sql_explanation": result.get("sql_explanation"),
            "last_rows": rows if isinstance(rows, list) else [],
            "last_error": error,
            "chart": chart,
            "status": "error" if error else "ready",
        }

    def refresh_widgets(
        self,
        widgets: list[dict[str, Any]],
        allowed_rep_codes: list[str],
    ) -> list[dict[str, Any]]:
        denied = self._access_error(allowed_rep_codes)
        if denied:
            return [
                {**widget, "last_error": denied["error"], "status": "error"}
                for widget in widgets
            ]
        refreshed = []
        for widget in widgets:
            refreshed.append(self.refresh_widget(widget, allowed_rep_codes))
        return refreshed

    def refresh_widget(
        self,
        widget: dict[str, Any],
        allowed_rep_codes: list[str],
    ) -> dict[str, Any]:
        sql = (widget.get("sql_query") or "").strip()
        updated = dict(widget)
        if not sql:
            updated["last_error"] = "This widget has no SQL to refresh."
            updated["status"] = "error"
            return updated

        kind, message = assess_sql(sql)
        if kind != "ok":
            updated["last_error"] = message or "Access denied. Only SELECT queries are allowed."
            updated["status"] = "error"
            return updated

        rows, error, _elapsed = db_manager.allowed_execute_query(
            sql,
            allowed_rep_codes=allowed_rep_codes,
        )
        if error:
            updated["last_error"] = error
            updated["status"] = "error"
            return updated

        safe_rows = _cap_rows(serialize_query_result(rows))
        chart = orchestrator.formatter.chart_spec_from_rows(
            safe_rows if isinstance(safe_rows, list) else [],
            requested_chart_type=widget.get("chart_type") or (widget.get("chart") or {}).get("chart_type"),
            widget_type=widget.get("type") or "chart",
            title=widget.get("title"),
        )
        updated["last_rows"] = safe_rows if isinstance(safe_rows, list) else []
        updated["last_error"] = None
        updated["chart"] = chart
        updated["chart_type"] = chart.get("chart_type") or widget.get("chart_type")
        updated["status"] = "ready"
        return updated

    def load_dimension_values(
        self,
        dimensions: list[str],
        widgets: list[dict[str, Any]],
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        values: dict[str, list[str]] = {}
        columns: dict[str, str] = {}
        known = {column.lower(): column for column in filter_columns(widgets)}
        for dimension in dimensions:
            match = known.get(dimension.lower())
            if match:
                found = filter_values(widgets, match)
                if found:
                    values[dimension] = found
                    columns[dimension] = match
                    continue
            found, column = self._distinct_dimension_values(
                dimension,
                allowed_rep_codes=allowed_rep_codes,
                user_role=user_role,
                user_id=user_id,
            )
            values[dimension] = found
            if column:
                columns[dimension] = column
        return values, columns

    def _distinct_dimension_values(
        self,
        dimension: str,
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
    ) -> tuple[list[str], str | None]:
        result = orchestrator.run_sql_only(
            (
                f"List distinct {dimension} names I am allowed to see. "
                "Return one column of names only, at most 80 rows. "
                "Do not aggregate sales."
            ),
            allowed_rep_codes=allowed_rep_codes,
            user_role=user_role,
            user_id=user_id,
        )
        rows = serialize_query_result(result.get("query_result"))
        if not isinstance(rows, list) or not rows:
            return [], None
        sample = rows[0]
        if not isinstance(sample, dict) or not sample:
            return [], None
        column = next(iter(sample.keys()))
        found: list[str] = []
        seen: set[str] = set()
        for row in rows[:80]:
            if not isinstance(row, dict):
                continue
            raw = row.get(column)
            if raw is None or str(raw).strip() == "":
                continue
            text = str(raw)
            if text in seen:
                continue
            seen.add(text)
            found.append(text)
        found.sort()
        qualified = selected_sql_column(result.get("sql_query"))
        return found, qualified or str(column)

    async def stream_apply_filters(
        self,
        widgets: list[dict[str, Any]],
        filters: dict[str, Any] | None,
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        denied = self._access_error(allowed_rep_codes)
        if denied:
            yield {"type": "error", "error": denied["error"]}
            yield {"type": "done"}
            return

        total = len(widgets)
        if not widgets:
            yield {
                "type": "result",
                "payload": {"success": True, "error": None, "widgets": []},
            }
            yield {"type": "done"}
            return

        built: list[dict[str, Any]] = []
        for index, widget in enumerate(widgets, start=1):
            yield {
                "type": "status",
                "text": f"Applying filters to widget {index} of {total}: {widget.get('title')}",
            }
            rebuilt = await _to_thread(
                self.apply_filters_to_widget,
                widget,
                filters,
                allowed_rep_codes,
            )
            built.append(rebuilt)
            yield {"type": "widget_ready", "widget": rebuilt}

        yield {
            "type": "result",
            "payload": {
                "success": True,
                "error": None,
                "widgets": built,
            },
        }
        yield {"type": "done"}

    def apply_filters_to_widget(
        self,
        widget: dict[str, Any],
        filters: dict[str, Any] | None,
        allowed_rep_codes: list[str],
    ) -> dict[str, Any]:
        original = dict(widget)
        source_sql = base_sql(widget)
        original["base_sql_query"] = source_sql or original.get("base_sql_query")
        if not source_sql:
            original["last_error"] = "This widget has no SQL to filter."
            original["status"] = "error"
            return original
        sql = inject_filters_into_sql(source_sql, filters) if has_filters(filters) else source_sql
        original["sql_query"] = sql
        return self.refresh_widget(original, allowed_rep_codes)

    def _guard(self, requirement: str, user_role: str | None) -> dict[str, Any] | None:
        result = orchestrator.guardrail.check(
            requirement or "",
            {"conversation_history": [], "user_role": user_role},
        )
        if result.get("passed", False):
            return None
        reason = result.get("reason") or "This request is outside sales analytics."
        logger.warning(f"Dashboard request rejected: {reason}")
        return {
            "success": False,
            "error": reason,
            "title": None,
            "widgets": [],
            "layout": [],
        }

    @staticmethod
    def _access_error(allowed_rep_codes: list[str] | None) -> dict[str, Any] | None:
        if allowed_rep_codes:
            return None
        return {
            "success": False,
            "error": "Access denied. No allowed rep codes were provided.",
            "title": None,
            "widgets": [],
            "layout": [],
        }


def _cap_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return rows[:WIDGET_ROW_CAP]


async def _to_thread(func, *args, **kwargs):
    import asyncio

    return await asyncio.to_thread(func, *args, **kwargs)


dashboard_composer = DashboardComposer()
