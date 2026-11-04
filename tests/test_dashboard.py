"""Dashboard layout, chart mapping, and read-only refresh checks."""

from src.agents.dashboard_layout import (
    extend_layout,
    normalize_plan_widgets,
    pack_layout,
)
from src.agents.dashboard_composer import DashboardComposer
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
