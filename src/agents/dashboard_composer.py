"""Compose dashboard widgets by planning, then reusing the SQL pipeline."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from src.agents.dashboard_layout import pack_layout
from src.agents.dashboard_planner import DashboardPlanner
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
        if mode == "add" and existing_widgets:
            widgets = list(existing_widgets) + widgets
        return {
            "success": True,
            "error": None,
            "title": plan.get("title") or "Sales dashboard",
            "widgets": widgets,
            "layout": pack_layout(widgets),
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
        yield {
            "type": "plan",
            "title": plan.get("title") or "Sales dashboard",
            "widgets": planned,
            "layout": layout,
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
            built.append(widget)
            yield {"type": "widget_ready", "widget": widget}

        payload = {
            "success": True,
            "error": None,
            "title": plan.get("title") or "Sales dashboard",
            "widgets": built,
            "layout": pack_layout(built),
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
    ) -> dict[str, Any]:
        question = spec.get("question") or ""
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
            "question": question,
            "sql_query": result.get("sql_query"),
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
