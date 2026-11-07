"""Dashboard layout, chart mapping, and read-only refresh checks."""

from src.services.dashboard_service.filters import (
    filter_columns,
    filter_values,
    has_filters,
    inject_filters_into_sql,
    merge_filter_fields,
    normalize_filters,
    question_with_filters,
)
from src.services.dashboard_service.planner import apply_slicer_to_questions
from src.services.dashboard_service.layout import (
    extend_layout,
    normalize_plan_widgets,
    pack_layout,
)
from src.services.dashboard_service.composer import DashboardComposer
from src.agents.dashboard.orchestrator import (
    DashboardComposeOrchestrator,
    compose_orchestrator,
    filter_orchestrator,
    refresh_orchestrator,
)
from src.agents.formatter import ResultFormatterAgent
from src.agents.orchestrator import orchestrator


class StubFormatter(ResultFormatterAgent):
    def __init__(self):
        pass


class TestDashboardLayout:
    def test_normalizes_and_dedupes_widgets(self):
        widgets = normalize_plan_widgets([
            {"title": "Net sales", "type": "kpi", "chart_type": "kpi", "question": "Total net sales this month"},
            {"title": "Copy", "type": "chart", "chart_type": "bar", "question": "Total net sales this month"},
            {"title": "Bad", "type": "chart", "chart_type": "bar", "question": ""},
            {"title": "Trend", "type": "weird", "chart_type": "line", "question": "Daily net sales this month"},
        ])
        assert len(widgets) == 2
        assert widgets[0]["type"] == "kpi"
        assert widgets[1]["type"] == "chart"
        assert widgets[1]["chart_type"] == "line"

    def test_packs_kpis_on_one_row(self):
        widgets = [
            {"widget_id": f"w{i}", "type": "kpi"}
            for i in range(4)
        ]
        layout = pack_layout(widgets)
        assert [item["y"] for item in layout] == [0, 0, 0, 0]
        assert layout[-1]["x"] == 9

    def test_extends_layout_into_open_gap(self):
        existing = [{"id": "w1", "x": 0, "y": 0, "w": 6, "h": 5}]
        added = [{"widget_id": "w2", "type": "chart"}]
        layout = extend_layout(existing, added)
        assert layout[1]["id"] == "w2"
        assert layout[1]["x"] == 6
        assert layout[1]["y"] == 0

    def test_extends_layout_fills_second_row_gap(self):
        existing = [
            {"id": "w1", "x": 0, "y": 0, "w": 6, "h": 5},
            {"id": "w2", "x": 6, "y": 0, "w": 6, "h": 5},
            {"id": "w3", "x": 0, "y": 5, "w": 6, "h": 5},
        ]
        added = [{"widget_id": "w4", "type": "chart"}]
        layout = extend_layout(existing, added)
        assert layout[3]["id"] == "w4"
        assert layout[3]["x"] == 6
        assert layout[3]["y"] == 5


class TestDashboardChartSpec:
    def test_kpi_uses_first_numeric_value(self):
        formatter = StubFormatter()
        spec = formatter.chart_spec_from_rows(
            [{"rep": "A", "net_sales": 1250}],
            requested_chart_type="kpi",
            widget_type="kpi",
            title="Net sales",
        )
        assert spec["enabled"] is True
        assert spec["chart_type"] == "kpi"
        assert spec["kpi_value"] == 1250
        assert spec["kpi_column"] == "net_sales"

    def test_line_prefers_date_axis(self):
        formatter = StubFormatter()
        spec = formatter.chart_spec_from_rows(
            [
                {"sale_date": "2026-11-01", "net_sales": 10},
                {"sale_date": "2026-11-02", "net_sales": 20},
            ],
            requested_chart_type="line",
            widget_type="chart",
        )
        assert spec["enabled"] is True
        assert spec["chart_type"] == "line"
        assert spec["x_column"] == "sale_date"
        assert spec["y_column"] == "net_sales"


class TestDashboardSqlSafety:
    def test_run_sql_only_stops_without_rep_codes(self):
        out = orchestrator.run_sql_only("What are total sales?", allowed_rep_codes=[])
        assert out["access_denied"] is True
        assert out["error_type"] == "access_denied"

    def test_refresh_rejects_write_sql(self):
        composer = DashboardComposer()
        updated = composer.refresh_widget(
            {
                "widget_id": "w1",
                "title": "Bad",
                "type": "chart",
                "sql_query": "DELETE FROM sales_flat",
                "last_rows": [],
            },
            allowed_rep_codes=["R001"],
        )
        assert updated["status"] == "error"
        assert "SELECT" in (updated["last_error"] or "")


class TestDashboardFilters:
    def test_normalize_keeps_only_named_values(self):
        filters = normalize_filters({
            "date_from": " 2026-01-01 ",
            "date_to": "",
            "fields": [
                {"column": " Region ", "values": ["West", "", None]},
                {"column": "", "values": ["East"]},
            ],
        })
        assert filters["date_from"] == "2026-01-01"
        assert filters["date_to"] is None
        assert filters["fields"] == [{"column": "Region", "values": ["West"]}]
        assert has_filters(filters) is True
        assert has_filters({}) is False

    def test_question_appends_filter_override(self):
        question = question_with_filters("Net sales this month", {
            "date_from": "2026-01-01",
            "date_to": "2026-01-31",
            "fields": [{"column": "Region", "values": ["West", "East"]}],
        })
        assert "Net sales this month" in question
        assert "2026-01-01" in question
        assert "Region is one of: West, East" in question
        assert "WHERE-style" in question
        assert "Do not group" in question

    def test_field_options_come_from_widget_rows(self):
        widgets = [{
            "last_rows": [
                {"Region": "West", "net_sales": 10},
                {"Region": "East", "net_sales": 20},
            ],
        }]
        assert filter_columns(widgets) == ["Region"]
        assert filter_values(widgets, "Region") == ["East", "West"]

    def test_merge_includes_planned_slicer_dimensions(self):
        widgets = [{
            "last_rows": [
                {"Product": "SKU-1", "net_sales": 10},
                {"Product": "SKU-2", "net_sales": 20},
            ],
        }]
        fields = merge_filter_fields(widgets, {
            "dimensions": ["region"],
            "dimension_values": {"region": ["West", "East"]},
        })
        columns = [item["column"] for item in fields]
        assert columns == ["region"]
        assert fields[0]["values"] == ["East", "West"]

    def test_inject_reuses_existing_sql(self):
        sql = """
        WITH sales_agg AS (
            SELECT sf.ProductName, SUM(sf.NetValue) AS net_sales
            FROM sales_flat sf
            INNER JOIN sales_hierarchy_nodes shn ON shn.Id = sf.RepId
            WHERE sf.Date >= '2026-10-01'
            GROUP BY sf.ProductName
        )
        SELECT ProductName, net_sales FROM sales_agg
        """
        updated = inject_filters_into_sql(sql, {
            "fields": [{"column": "region", "values": ["West"]}],
            "dimension_columns": {"region": "sf.Region"},
        })
        assert "ProductName" in updated
        assert "GROUP BY" in updated.upper()
        assert "sf.Region" in updated or "sf.`Region`" in updated
        assert "West" in updated
        assert "FROM sales_agg" in updated

    def test_slicer_note_keeps_widget_breakdown(self):
        widgets = apply_slicer_to_questions(
            [{"title": "By product", "question": "Product-wise net sales last month"}],
            ["region"],
        )
        question = widgets[0]["question"]
        assert "Product-wise net sales last month" in question
        assert "region" in question
        assert "dashboard filter applied later" in question
        again = apply_slicer_to_questions(widgets, ["region"])
        assert again[0]["question"].count("dashboard filter applied later") == 1


class _StubPlanner:
    def plan(self, requirement, existing_widgets=None, mode="compose"):
        return {
            "title": "Board",
            "widgets": [{
                "widget_id": "w1",
                "title": "Net sales",
                "type": "kpi",
                "chart_type": "kpi",
                "question": "Total net sales",
            }],
            "filter_dimensions": [],
        }


class TestDashboardOrchestrators:
    def test_compose_graph_builds_stubbed_widget(self):
        orch = DashboardComposeOrchestrator()
        orch.guard = lambda requirement, user_role: None
        orch.build_filtered_widget = lambda spec, **kwargs: {
            **spec,
            "status": "ready",
            "last_rows": [],
            "sql_query": "SELECT 1",
        }
        out = orch.run("total sales", allowed_rep_codes=["R001"], planner=_StubPlanner())
        assert out["success"] is True
        assert out["title"] == "Board"
        assert out["widgets"][0]["status"] == "ready"
        assert out["layout"][0]["id"] == "w1"

    def test_compose_graph_stops_without_rep_codes(self):
        out = compose_orchestrator.run("total sales", allowed_rep_codes=[])
        assert out["success"] is False
        assert "rep codes" in out["error"]

    def test_refresh_graph_rejects_write_sql(self):
        widgets = refresh_orchestrator.run(
            [{
                "widget_id": "w1",
                "title": "Bad",
                "type": "chart",
                "sql_query": "DELETE FROM sales_flat",
                "last_rows": [],
            }],
            ["R001"],
        )
        assert widgets[0]["status"] == "error"
        assert "SELECT" in (widgets[0]["last_error"] or "")

    def test_filter_graph_skips_empty_board(self):
        out = filter_orchestrator.run([], None, allowed_rep_codes=["R001"])
        assert out["success"] is True
        assert out["widgets"] == []

    def test_graphs_keep_separate_nodes(self):
        assert "planner" in set(compose_orchestrator.graph.get_graph().nodes)
        assert "build_widget" in set(compose_orchestrator.graph.get_graph().nodes)
        assert "refresh" in set(refresh_orchestrator.graph.get_graph().nodes)
        assert "apply_widget" in set(filter_orchestrator.graph.get_graph().nodes)
