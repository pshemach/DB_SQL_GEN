"""Dashboard orchestrators.

Chat keeps its own graph. Dashboards do not call that graph.

- compose: scope, plan widgets, run the widget SQL graph, load slicer values
- widget SQL: plan, tables, SELECT, review, repair, execute
- refresh: re-run each widget's stored SELECT
- filter: inject dashboard filters into stored SQL and re-run

Graph steps live in this file. State is in ``state.py``. The widget
planner is in ``dashboard_planer.py``. Layout math and SQL filter rewriting
stay in the dashboard service.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

from langgraph.graph import END, StateGraph
from loguru import logger

from src.agents.chat.formatter import ResultFormatterAgent
from src.agents.dashboard.dashboard_planer import DashboardPlaner
from src.agents.dashboard.state import ComposeState, FilterState, RefreshState, WidgetSqlState
from src.agents.prompts.dashboard_agent_prompts import (
    build_dashboard_scope_prompt,
    build_dashboard_sql_critic_prompt,
    build_dashboard_sql_generator_prompt,
    build_dashboard_sql_planner_prompt,
    build_dashboard_sql_repair_prompt,
    build_dashboard_table_prompt,
    dashboard_messages,
)
from src.infrastructure.config import (
    ENABLE_PRE_EXEC_CRITIC,
    ENABLE_SELF_CORRECTION,
    MAX_ITERATIONS,
    QUERY_TIMEOUT_SECONDS,
)
from src.infrastructure.db.database import DatabaseManager
from src.infrastructure.db.sql_safety import assess_sql, classify_db_error, is_retryable
from src.infrastructure.llm.llm_provider import (
    get_direct_llm,
    get_generator_llm,
    get_planner_llm,
    get_router_llm,
    get_schema_selection_llm,
)
from src.infrastructure.utils import extract_json, serialize_query_result
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

db_manager = DatabaseManager()

WIDGET_ROW_CAP = 200
NO_REP_CODES = "Access denied. No allowed rep codes were provided."
GRAPH_RECURSION_LIMIT = 64


def _cap_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return rows[:WIDGET_ROW_CAP]


def _placeholders(existing: list[dict[str, Any]] | None, mode: str) -> list[dict[str, Any]]:
    if mode == "add" and existing:
        return list(existing)
    return []


FORBIDDEN_SQL = re.compile(
    r"(?i)\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b"
)
_INJECTION_PATTERNS = (
    r"(?i)(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE)",
    r"(?i)(UNION\s+SELECT|OR\s+1\s*=\s*1)",
    r"(?i)(--\s*$|;\s*DROP)",
    r"(?i)({.*exec.*}|<script|javascript:)",
)
_MAX_REQUIREMENT_LENGTH = 2000
_FALLBACK_TABLES = [
    "sales_flat",
    "sales_targets",
    "sales_hierarchy_nodes",
    "external_parties",
    "products",
    "planned_routes",
    "route_customer_assignments",
]


def _clean_sql(raw_sql: str) -> str:
    sql = (raw_sql or "").replace("```sql", "").replace("```", "").strip()
    lines = sql.split("\n")
    for index, line in enumerate(lines):
        if any(keyword in line.upper() for keyword in ("SELECT", "WITH")):
            return "\n".join(lines[index:]).strip()
    return sql


def _chart_spec(rows: list, spec: dict[str, Any]) -> dict:
    formatter = ResultFormatterAgent.__new__(ResultFormatterAgent)
    return formatter.chart_spec_from_rows(
        rows,
        requested_chart_type=spec.get("chart_type"),
        widget_type=spec.get("type") or "chart",
        title=spec.get("title"),
    )


class DashboardWidgetSqlOrchestrator:
    """One widget question → plan → tables → SELECT → review → execute."""

    def __init__(self) -> None:
        self.graph = self._build_graph()

    def run(
        self,
        question: str,
        *,
        widget_type: str = "chart",
        chart_type: str = "bar",
        allowed_rep_codes: list[str] | None = None,
    ) -> dict:
        state: WidgetSqlState = {
            "question": question,
            "widget_type": widget_type or "chart",
            "chart_type": chart_type or widget_type or "bar",
            "allowed_rep_codes": allowed_rep_codes or [],
            "iterations": 0,
            "should_retry": True,
            "error": None,
            "sql_query": None,
            "query_result": None,
        }
        if not state["allowed_rep_codes"]:
            return {
                **state,
                "access_denied": True,
                "error": NO_REP_CODES,
                "error_type": "access_denied",
                "should_retry": False,
            }
        return self.graph.invoke(state, {"recursion_limit": GRAPH_RECURSION_LIMIT})

    def plan_node(self, state: WidgetSqlState) -> dict:
        try:
            system_prompt, user_prompt = build_dashboard_sql_planner_prompt(
                state.get("question") or "",
                DashboardPlaner().retrieve_knowledge(state.get("question") or ""),
                state.get("widget_type") or "chart",
                state.get("chart_type") or "bar",
            )
            response = get_planner_llm(temperature=0).invoke(
                dashboard_messages(system_prompt, user_prompt)
            )
            return {"plan": (response.content or "").strip(), "iterations": 0, "should_retry": True}
        except Exception as exc:
            logger.error(f"Widget SQL plan failed: {exc}")
            return {"error": f"Planning failed: {exc}", "should_retry": False, "error_type": "runtime"}

    def schema_node(self, state: WidgetSqlState) -> dict:
        question = state.get("question") or ""
        plan = state.get("plan") or ""
        try:
            all_tables = db_manager.get_all_table_names()
            system_prompt, user_prompt = build_dashboard_table_prompt(
                question,
                plan,
                state.get("widget_type") or "chart",
                state.get("chart_type") or "bar",
            )
            response = get_schema_selection_llm().invoke(
                dashboard_messages(system_prompt, user_prompt)
            )
            selected = [name.strip() for name in (response.content or "").split(",")]
            selected = [name for name in selected if name in all_tables]
            if "sales_hierarchy_nodes" not in selected:
                selected.append("sales_hierarchy_nodes")
            if not selected:
                selected = [name for name in _FALLBACK_TABLES if name in all_tables] or list(all_tables)
            schema_context = db_manager.get_schema_for_tables(selected)
            return {"relevant_tables": selected, "schema_context": schema_context, "error": None}
        except Exception as exc:
            logger.error(f"Widget schema selection failed: {exc}")
            return {
                "error": f"Schema retrieval failed: {exc}",
                "error_type": "runtime",
                "should_retry": False,
            }

    def generate_node(self, state: WidgetSqlState) -> dict:
        if not state.get("schema_context"):
            return {
                "error": "Cannot generate SQL without schema context",
                "error_type": "validation",
                "should_retry": False,
            }
        try:
            system_prompt, user_prompt = build_dashboard_sql_generator_prompt(
                state.get("question") or "",
                state.get("plan") or "",
                state.get("schema_context") or "",
                state.get("widget_type") or "chart",
                state.get("chart_type") or "bar",
            )
            response = get_generator_llm(temperature=0.0).invoke(
                dashboard_messages(system_prompt, user_prompt)
            )
            sql = _clean_sql(response.content or "")
            return {"sql_query": sql, "sql_explanation": response.content, "error": None}
        except Exception as exc:
            logger.error(f"Widget SQL generation failed: {exc}")
            return {"error": f"SQL generation failed: {exc}", "error_type": "runtime", "should_retry": False}

    def validate_node(self, state: WidgetSqlState) -> dict:
        sql = (state.get("sql_query") or "").strip()
        if not sql:
            return {"error": "No SQL query generated", "error_type": "validation", "should_retry": True}
        if FORBIDDEN_SQL.search(sql):
            return {
                "error": "Query contains forbidden DDL/DML statements",
                "error_type": "validation",
                "should_retry": False,
            }
        kind, message = assess_sql(sql)
        if kind == "policy":
            return {"error": message, "error_type": "validation", "should_retry": False}
        if kind == "parse":
            return {"error": f"SQL parse error: {message}", "error_type": "syntax", "should_retry": True}
        return {"error": None, "error_type": None, "should_retry": False}

    def critic_node(self, state: WidgetSqlState) -> dict:
        if not ENABLE_PRE_EXEC_CRITIC:
            return {}
        try:
            system_prompt, user_prompt = build_dashboard_sql_critic_prompt(
                state.get("question") or "",
                state.get("sql_query") or "",
                state.get("widget_type") or "chart",
                state.get("chart_type") or "bar",
            )
            response = get_direct_llm(temperature=0).invoke(
                dashboard_messages(system_prompt, user_prompt)
            )
            content = (response.content or "").strip()
            if content.upper().startswith("REJECT"):
                return {"error": content, "error_type": "validation", "should_retry": True}
        except Exception as exc:
            logger.warning(f"Widget SQL review failed: {exc}")
        return {}

    def execute_node(self, state: WidgetSqlState) -> dict:
        allowed = state.get("allowed_rep_codes") or []
        sql_query = state.get("sql_query")
        if not allowed:
            return {
                "error": NO_REP_CODES,
                "error_type": "access_denied",
                "should_retry": False,
            }
        if not sql_query:
            return {"error": "No SQL query to execute", "error_type": "validation", "should_retry": False}
        try:
            result, error, _elapsed = db_manager.allowed_execute_query(
                sql_query,
                allowed_rep_codes=allowed,
                timeout=QUERY_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.error(f"Widget SQL execution error: {exc}")
            return {"error": str(exc), "error_type": "runtime", "should_retry": True}
        if error:
            error_type = classify_db_error(error)
            return {
                "error": error,
                "error_type": error_type,
                "query_result": None,
                "should_retry": is_retryable(error_type, True) and ENABLE_SELF_CORRECTION,
            }
        return {
            "query_result": serialize_query_result(result),
            "error": None,
            "error_type": None,
            "should_retry": False,
        }

    def repair_node(self, state: WidgetSqlState) -> dict:
        iterations = int(state.get("iterations") or 0)
        if not is_retryable(state.get("error_type"), state.get("should_retry", True)):
            return {"should_retry": False}
        if iterations >= MAX_ITERATIONS:
            return {
                "should_retry": False,
                "iterations": iterations,
                "error": f"Failed to generate valid SQL after {MAX_ITERATIONS} attempts",
            }
        try:
            system_prompt, user_prompt = build_dashboard_sql_repair_prompt(
                state.get("question") or "",
                state.get("plan") or "",
                state.get("schema_context") or "",
                state.get("sql_query") or "",
                state.get("error") or "",
                state.get("widget_type") or "chart",
                state.get("chart_type") or "bar",
            )
            response = get_direct_llm(temperature=0).invoke(
                dashboard_messages(system_prompt, user_prompt)
            )
            return {
                "sql_query": _clean_sql(response.content or ""),
                "iterations": iterations + 1,
                "should_retry": True,
                "error": None,
            }
        except Exception as exc:
            logger.error(f"Widget SQL repair failed: {exc}")
            return {
                "error": f"Failed to correct SQL: {exc}",
                "iterations": iterations + 1,
                "should_retry": False,
            }

    def route_after_plan(self, state: WidgetSqlState) -> str:
        if state.get("error"):
            return "end"
        return "schema"

    def route_after_schema(self, state: WidgetSqlState) -> str:
        if state.get("error"):
            return "end"
        return "generate"

    def route_after_generate(self, state: WidgetSqlState) -> str:
        if state.get("error"):
            return "end"
        return "validate"

    def _can_repair(self, state: WidgetSqlState) -> bool:
        return (
            is_retryable(state.get("error_type"), state.get("should_retry", True))
            and int(state.get("iterations") or 0) < MAX_ITERATIONS
        )

    def route_after_validate(self, state: WidgetSqlState) -> str:
        if state.get("error"):
            return "repair" if self._can_repair(state) else "end"
        return "critic" if ENABLE_PRE_EXEC_CRITIC else "execute"

    def route_after_critic(self, state: WidgetSqlState) -> str:
        if state.get("error"):
            return "repair" if self._can_repair(state) else "end"
        return "execute"

    def route_after_execute(self, state: WidgetSqlState) -> str:
        if state.get("error") is None:
            return "end"
        return "repair" if self._can_repair(state) else "end"

    def _build_graph(self):
        logger.info("Building dashboard widget SQL orchestrator")
        workflow = StateGraph(WidgetSqlState)
        workflow.add_node("plan", self.plan_node)
        workflow.add_node("schema", self.schema_node)
        workflow.add_node("generate", self.generate_node)
        workflow.add_node("validate", self.validate_node)
        workflow.add_node("critic", self.critic_node)
        workflow.add_node("execute", self.execute_node)
        workflow.add_node("repair", self.repair_node)
        workflow.set_entry_point("plan")
        workflow.add_conditional_edges("plan", self.route_after_plan, {"schema": "schema", "end": END})
        workflow.add_conditional_edges("schema", self.route_after_schema, {"generate": "generate", "end": END})
        workflow.add_conditional_edges(
            "generate", self.route_after_generate, {"validate": "validate", "end": END}
        )
        workflow.add_conditional_edges(
            "validate",
            self.route_after_validate,
            {"critic": "critic", "execute": "execute", "repair": "repair", "end": END},
        )
        workflow.add_conditional_edges(
            "critic",
            self.route_after_critic,
            {"execute": "execute", "repair": "repair", "end": END},
        )
        workflow.add_conditional_edges(
            "execute",
            self.route_after_execute,
            {"repair": "repair", "end": END},
        )
        workflow.add_edge("repair", "validate")
        return workflow.compile()


class DashboardAgent:
    """Planner, guardrail, and widget steps used by every dashboard graph."""

    def widget_sql(self) -> DashboardWidgetSqlOrchestrator:
        orchestrator = getattr(self, "_widget_sql", None)
        if orchestrator is None:
            orchestrator = DashboardWidgetSqlOrchestrator()
            self._widget_sql = orchestrator
        return orchestrator

    def access_error(self, allowed_rep_codes: list[str] | None) -> str | None:
        if allowed_rep_codes:
            return None
        return NO_REP_CODES

    def guard(self, requirement: str, user_role: str | None) -> str | None:
        text = requirement or ""
        if len(text) > _MAX_REQUIREMENT_LENGTH:
            return "Query is too long. Please shorten your query to 2000 characters or less."
        for pattern in _INJECTION_PATTERNS:
            if re.search(pattern, text):
                logger.warning(f"Dashboard request rejected by injection check: {pattern}")
                return "Your question contains suspicious patterns. Please rephrase."
        try:
            system_prompt, user_prompt = build_dashboard_scope_prompt(text, user_role or "")
            response = get_router_llm().invoke(dashboard_messages(system_prompt, user_prompt))
            parsed = extract_json((response.content or "").strip()) or {}
        except Exception as exc:
            logger.warning(f"Dashboard scope check failed open: {exc}")
            return None
        if str(parsed.get("classification") or "in_scope") == "in_scope":
            return None
        reason = parsed.get("reason") or "This request is outside sales analytics."
        logger.warning(f"Dashboard request rejected: {reason}")
        return str(reason)

    def plan(
        self,
        requirement: str,
        existing_widgets: list[dict[str, Any]] | None = None,
        mode: str = "compose",
        llm: Any = None,
    ) -> dict[str, Any]:
        return DashboardPlaner(llm=llm).plan(requirement, existing_widgets, mode)

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
        result = self.widget_sql().run(
            question,
            widget_type=spec.get("type") or "chart",
            chart_type=spec.get("chart_type") or spec.get("type") or "chart",
            allowed_rep_codes=allowed_rep_codes,
        )
        rows = _cap_rows(serialize_query_result(result.get("query_result")))
        error = result.get("error")
        chart = _chart_spec(rows if isinstance(rows, list) else [], spec)
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

    def build_filtered_widget(
        self,
        spec: dict[str, Any],
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        widget = self.build_widget(
            spec,
            allowed_rep_codes=allowed_rep_codes,
            user_role=user_role,
            user_id=user_id,
        )
        if has_filters(filters):
            return self.apply_filters_to_widget(widget, filters, allowed_rep_codes)
        return widget

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
        chart = _chart_spec(safe_rows if isinstance(safe_rows, list) else [], widget)
        updated["last_rows"] = safe_rows if isinstance(safe_rows, list) else []
        updated["last_error"] = None
        updated["chart"] = chart
        updated["chart_type"] = chart.get("chart_type") or widget.get("chart_type")
        updated["status"] = "ready"
        return updated

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
        result = self.widget_sql().run(
            (
                f"List distinct {dimension} names I am allowed to see. "
                "Return one column of names only, at most 80 rows. "
                "Do not aggregate sales."
            ),
            widget_type="table",
            chart_type="table",
            allowed_rep_codes=allowed_rep_codes,
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

    @staticmethod
    def _failed(error: str) -> dict[str, Any]:
        return {
            "success": False,
            "error": error,
            "title": None,
            "widgets": [],
            "layout": [],
        }


class DashboardComposeOrchestrator(DashboardAgent):
    """Requirement → widget plan → SQL widgets → slicer values."""

    def __init__(self) -> None:
        self.graph = self._build_graph()

    def run(
        self,
        requirement: str,
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
        existing_widgets: list[dict[str, Any]] | None = None,
        mode: str = "compose",
        filters: dict[str, Any] | None = None,
        planner: Any = None,
    ) -> dict[str, Any]:
        state: ComposeState = {
            "requirement": requirement,
            "mode": mode,
            "allowed_rep_codes": allowed_rep_codes or [],
            "user_role": user_role,
            "user_id": user_id,
            "existing_widgets": list(existing_widgets or []),
            "filters": filters,
            "error": None,
            "specs": [],
            "built": [],
            "index": 0,
            "filter_dimensions": [],
            "dimension_values": {},
            "dimension_columns": {},
            "widgets": [],
            "layout": [],
        }
        final = self.graph.invoke(
            state,
            {"recursion_limit": GRAPH_RECURSION_LIMIT, "configurable": {"planner": planner}},
        )
        if final.get("error"):
            return self._failed(final["error"])
        return {
            "success": True,
            "error": None,
            "title": final.get("title") or DashboardPlaner.FALLBACK_TITLE,
            "widgets": final.get("widgets") or [],
            "layout": final.get("layout") or [],
            "filter_dimensions": final.get("filter_dimensions") or [],
            "dimension_values": final.get("dimension_values") or {},
            "dimension_columns": final.get("dimension_columns") or {},
        }

    async def stream(
        self,
        requirement: str,
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
        existing_widgets: list[dict[str, Any]] | None = None,
        mode: str = "compose",
        filters: dict[str, Any] | None = None,
        planner: Any = None,
    ) -> AsyncIterator[dict[str, Any]]:
        denied = self.access_error(allowed_rep_codes)
        if denied:
            yield {"type": "error", "error": denied}
            yield {"type": "done"}
            return

        yield {"type": "status", "text": "Checking your request..."}
        reason = await asyncio.to_thread(self.guard, requirement, user_role)
        if reason:
            yield {"type": "error", "error": reason}
            yield {"type": "done"}
            return

        yield {"type": "status", "text": "Planning widgets..."}
        if planner is not None:
            plan = await asyncio.to_thread(
                planner.plan,
                requirement,
                existing_widgets=existing_widgets,
                mode=mode,
            )
        else:
            plan = await asyncio.to_thread(
                self.plan,
                requirement,
                existing_widgets=existing_widgets,
                mode=mode,
            )
        specs = plan.get("widgets") or []
        placeholders = _placeholders(existing_widgets, mode)
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
        dimensions = normalize_dimensions(plan.get("filter_dimensions"))
        yield {
            "type": "plan",
            "title": plan.get("title") or DashboardPlaner.FALLBACK_TITLE,
            "widgets": planned,
            "layout": pack_layout(planned),
            "filter_dimensions": dimensions,
        }

        built: list[dict[str, Any]] = list(placeholders)
        total = len(specs)
        for index, spec in enumerate(specs, start=1):
            yield {
                "type": "status",
                "text": f"Building widget {index} of {total}: {spec.get('title')}",
            }
            widget = await asyncio.to_thread(
                self.build_filtered_widget,
                spec,
                allowed_rep_codes=allowed_rep_codes,
                user_role=user_role,
                user_id=user_id,
                filters=filters,
            )
            built.append(widget)
            yield {"type": "widget_ready", "widget": widget}

        dimension_values: dict[str, list[str]] = {}
        dimension_columns: dict[str, str] = {}
        if dimensions:
            yield {"type": "status", "text": "Loading filter values..."}
            dimension_values, dimension_columns = await asyncio.to_thread(
                self.load_dimension_values,
                dimensions,
                built,
                allowed_rep_codes=allowed_rep_codes,
                user_role=user_role,
                user_id=user_id,
            )

        yield {
            "type": "result",
            "payload": {
                "success": True,
                "error": None,
                "title": plan.get("title") or DashboardPlaner.FALLBACK_TITLE,
                "widgets": built,
                "layout": pack_layout(built),
                "filter_dimensions": dimensions,
                "dimension_values": dimension_values,
                "dimension_columns": dimension_columns,
            },
        }
        yield {"type": "done"}

    def access_node(self, state: ComposeState) -> dict:
        reason = self.access_error(state.get("allowed_rep_codes"))
        if reason:
            return {"error": reason}
        return {}

    def guard_node(self, state: ComposeState) -> dict:
        reason = self.guard(state.get("requirement") or "", state.get("user_role"))
        if reason:
            return {"error": reason}
        return {}

    def plan_node(self, state: ComposeState, config: dict | None = None) -> dict:
        planner = ((config or {}).get("configurable") or {}).get("planner")
        if planner is not None:
            plan = planner.plan(
                state.get("requirement") or "",
                existing_widgets=state.get("existing_widgets"),
                mode=state.get("mode") or "compose",
            )
        else:
            plan = self.plan(
                state.get("requirement") or "",
                existing_widgets=state.get("existing_widgets"),
                mode=state.get("mode") or "compose",
            )
        return {
            "title": plan.get("title") or DashboardPlaner.FALLBACK_TITLE,
            "specs": plan.get("widgets") or [],
            "filter_dimensions": normalize_dimensions(plan.get("filter_dimensions")),
            "built": _placeholders(state.get("existing_widgets"), state.get("mode") or "compose"),
            "index": 0,
        }

    def build_widget_node(self, state: ComposeState) -> dict:
        index = int(state.get("index") or 0)
        spec = (state.get("specs") or [])[index]
        widget = self.build_filtered_widget(
            spec,
            allowed_rep_codes=state.get("allowed_rep_codes") or [],
            user_role=state.get("user_role"),
            user_id=state.get("user_id"),
            filters=state.get("filters"),
        )
        built = list(state.get("built") or [])
        built.append(widget)
        return {"built": built, "index": index + 1}

    def dimensions_node(self, state: ComposeState) -> dict:
        values, columns = self.load_dimension_values(
            state.get("filter_dimensions") or [],
            state.get("built") or [],
            allowed_rep_codes=state.get("allowed_rep_codes") or [],
            user_role=state.get("user_role"),
            user_id=state.get("user_id"),
        )
        return {"dimension_values": values, "dimension_columns": columns}

    def finalize_node(self, state: ComposeState) -> dict:
        widgets = list(state.get("built") or [])
        return {"widgets": widgets, "layout": pack_layout(widgets)}

    def route_after_access(self, state: ComposeState) -> str:
        if state.get("error"):
            return "end"
        return "guardrail"

    def route_after_guard(self, state: ComposeState) -> str:
        if state.get("error"):
            return "end"
        return "planner"

    def route_after_plan(self, state: ComposeState) -> str:
        return self._route_widgets(state)

    def route_after_widget(self, state: ComposeState) -> str:
        return self._route_widgets(state)

    @staticmethod
    def _route_widgets(state: ComposeState) -> str:
        if int(state.get("index") or 0) < len(state.get("specs") or []):
            return "build_widget"
        if state.get("filter_dimensions"):
            return "dimensions"
        return "finalize"

    def _build_graph(self):
        logger.info("Building dashboard compose orchestrator")
        workflow = StateGraph(ComposeState)
        workflow.add_node("access", self.access_node)
        workflow.add_node("guardrail", self.guard_node)
        workflow.add_node("planner", self.plan_node)
        workflow.add_node("build_widget", self.build_widget_node)
        workflow.add_node("dimensions", self.dimensions_node)
        workflow.add_node("finalize", self.finalize_node)

        workflow.set_entry_point("access")
        workflow.add_conditional_edges(
            "access",
            self.route_after_access,
            {"guardrail": "guardrail", "end": END},
        )
        workflow.add_conditional_edges(
            "guardrail",
            self.route_after_guard,
            {"planner": "planner", "end": END},
        )
        workflow.add_conditional_edges(
            "planner",
            self.route_after_plan,
            {
                "build_widget": "build_widget",
                "dimensions": "dimensions",
                "finalize": "finalize",
            },
        )
        workflow.add_conditional_edges(
            "build_widget",
            self.route_after_widget,
            {
                "build_widget": "build_widget",
                "dimensions": "dimensions",
                "finalize": "finalize",
            },
        )
        workflow.add_edge("dimensions", "finalize")
        workflow.add_edge("finalize", END)
        return workflow.compile()


class DashboardRefreshOrchestrator(DashboardAgent):
    """Re-run stored SELECT statements for an existing board."""

    def __init__(self) -> None:
        self.graph = self._build_graph()

    def run(
        self,
        widgets: list[dict[str, Any]],
        allowed_rep_codes: list[str],
    ) -> list[dict[str, Any]]:
        state: RefreshState = {
            "widgets": list(widgets or []),
            "allowed_rep_codes": allowed_rep_codes or [],
            "error": None,
        }
        final = self.graph.invoke(state, {"recursion_limit": GRAPH_RECURSION_LIMIT})
        return list(final.get("widgets") or [])

    def access_node(self, state: RefreshState) -> dict:
        reason = self.access_error(state.get("allowed_rep_codes"))
        if not reason:
            return {}
        denied = [
            {**widget, "last_error": reason, "status": "error"}
            for widget in state.get("widgets") or []
        ]
        return {"error": reason, "widgets": denied}

    def refresh_node(self, state: RefreshState) -> dict:
        codes = state.get("allowed_rep_codes") or []
        refreshed = [
            self.refresh_widget(widget, codes)
            for widget in state.get("widgets") or []
        ]
        return {"widgets": refreshed}

    def route_after_access(self, state: RefreshState) -> str:
        if state.get("error"):
            return "end"
        return "refresh"

    def _build_graph(self):
        logger.info("Building dashboard refresh orchestrator")
        workflow = StateGraph(RefreshState)
        workflow.add_node("access", self.access_node)
        workflow.add_node("refresh", self.refresh_node)
        workflow.set_entry_point("access")
        workflow.add_conditional_edges(
            "access",
            self.route_after_access,
            {"refresh": "refresh", "end": END},
        )
        workflow.add_edge("refresh", END)
        return workflow.compile()


class DashboardFilterOrchestrator(DashboardAgent):
    """Apply shared filters by rewriting each widget SELECT, then re-run it."""

    def __init__(self) -> None:
        self.graph = self._build_graph()

    def run(
        self,
        widgets: list[dict[str, Any]],
        filters: dict[str, Any] | None,
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        state: FilterState = {
            "widgets": list(widgets or []),
            "filters": filters,
            "allowed_rep_codes": allowed_rep_codes or [],
            "user_role": user_role,
            "user_id": user_id,
            "index": 0,
            "updated": [],
            "error": None,
        }
        final = self.graph.invoke(state, {"recursion_limit": GRAPH_RECURSION_LIMIT})
        if final.get("error"):
            return {"success": False, "error": final["error"], "widgets": []}
        return {
            "success": True,
            "error": None,
            "widgets": final.get("updated") or [],
        }

    async def stream(
        self,
        widgets: list[dict[str, Any]],
        filters: dict[str, Any] | None,
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        denied = self.access_error(allowed_rep_codes)
        if denied:
            yield {"type": "error", "error": denied}
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
            rebuilt = await asyncio.to_thread(
                self.apply_filters_to_widget,
                widget,
                filters,
                allowed_rep_codes,
            )
            built.append(rebuilt)
            yield {"type": "widget_ready", "widget": rebuilt}

        yield {
            "type": "result",
            "payload": {"success": True, "error": None, "widgets": built},
        }
        yield {"type": "done"}

    def access_node(self, state: FilterState) -> dict:
        reason = self.access_error(state.get("allowed_rep_codes"))
        if reason:
            return {"error": reason}
        return {}

    def apply_node(self, state: FilterState) -> dict:
        index = int(state.get("index") or 0)
        widget = (state.get("widgets") or [])[index]
        rebuilt = self.apply_filters_to_widget(
            widget,
            state.get("filters"),
            state.get("allowed_rep_codes") or [],
        )
        updated = list(state.get("updated") or [])
        updated.append(rebuilt)
        return {"updated": updated, "index": index + 1}

    def route_after_access(self, state: FilterState) -> str:
        if state.get("error"):
            return "end"
        if not state.get("widgets"):
            return "end"
        return "apply_widget"

    def route_after_apply(self, state: FilterState) -> str:
        if int(state.get("index") or 0) < len(state.get("widgets") or []):
            return "apply_widget"
        return "end"

    def _build_graph(self):
        logger.info("Building dashboard filter orchestrator")
        workflow = StateGraph(FilterState)
        workflow.add_node("access", self.access_node)
        workflow.add_node("apply_widget", self.apply_node)
        workflow.set_entry_point("access")
        workflow.add_conditional_edges(
            "access",
            self.route_after_access,
            {"apply_widget": "apply_widget", "end": END},
        )
        workflow.add_conditional_edges(
            "apply_widget",
            self.route_after_apply,
            {"apply_widget": "apply_widget", "end": END},
        )
        return workflow.compile()
