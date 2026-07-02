"""Tests for transform spec post-process + execution (no LLM)."""

from src.utils.cached_result_ops import execute_transform_spec
from src.utils.transform_spec_postprocess import normalize_and_validate_spec

ROWS = [
    {"RepCode": "R1", "ProductName": "A", "NetSales": 100.0},
    {"RepCode": "R1", "ProductName": "B", "NetSales": 500.0},
    {"RepCode": "R2", "ProductName": "C", "NetSales": 300.0},
    {"RepCode": "R2", "ProductName": "D", "NetSales": 50.0},
]
COLS = ["RepCode", "ProductName", "NetSales"]


def test_compound_operation_string():
    """LLM returns 'use_all | sort | row_at_rank' — postprocess still works."""
    raw = {
        "can_answer_from_cache": True,
        "needs_new_sql": False,
        "operation": "use_all | sort | row_at_rank",
        "filters": [],
        "sort": {"column": "net_sales", "direction": "desc"},
        "rank": 1,
    }
    spec = normalize_and_validate_spec(raw, COLS, len(ROWS))
    assert spec["operation"] == "row_at_rank"
    assert spec["sort"]["column"] == "NetSales"
    data, meta = execute_transform_spec(ROWS, spec)
    assert len(data) == 1
    assert data[0]["NetSales"] == 500.0
    print("OK compound op + column resolve")


def test_group_top_per():
    raw = {
        "can_answer_from_cache": True,
        "needs_new_sql": False,
        "operation": "group_top_per",
        "group_top_per": {
            "group_by": "RepCode",
            "value_column": "NetSales",
            "direction": "desc",
            "take_per_group": 1,
        },
    }
    spec = normalize_and_validate_spec(
        raw,
        COLS,
        len(ROWS),
        explanation="top product for each rep",
    )
    data, meta = execute_transform_spec(ROWS, spec)
    assert len(data) == 2
    assert {r["ProductName"] for r in data} == {"B", "C"}
    print("OK group_top_per")


def test_per_group_without_columns_needs_sql():
    raw = {
        "can_answer_from_cache": True,
        "needs_new_sql": False,
        "operation": "row_at_rank",
        "sort": {"column": "net_sales", "direction": "desc"},
        "rank": 1,
    }
    spec = normalize_and_validate_spec(
        raw,
        ["OnlyMetric"],
        1,
        explanation="best item for each sales representative",
    )
    assert spec["needs_new_sql"] is True
    print("OK per-group infeasible -> needs_new_sql")


def test_sort_column_missing_needs_sql():
    raw = {
        "can_answer_from_cache": True,
        "operation": "row_at_rank",
        "sort": {"column": "nonexistent_col", "direction": "desc"},
        "rank": 1,
    }
    spec = normalize_and_validate_spec(raw, COLS, len(ROWS))
    assert spec["needs_new_sql"] is True
    print("OK missing sort column -> needs_new_sql")


if __name__ == "__main__":
    test_compound_operation_string()
    test_group_top_per()
    test_per_group_without_columns_needs_sql()
    test_sort_column_missing_needs_sql()
    print("All postprocess tests passed.")
