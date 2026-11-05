"""Grid packing and widget-spec cleanup for dashboards."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

MAX_WIDGETS = 6
GRID_COLUMNS = 12
ALLOWED_TYPES = {"kpi", "chart", "table"}
ALLOWED_CHARTS = {
    "kpi",
    "bar",
    "horizontal_bar",
    "line",
    "pie",
    "scatter",
    "table",
}
WIDGET_SIZES = {
    "kpi": (3, 3),
    "chart": (6, 5),
    "table": (12, 5),
}

_SPACE = re.compile(r"\s+")


def new_widget_id() -> str:
    return f"w-{uuid4().hex[:10]}"


def normalize_widget_spec(raw: Any, index: int = 0) -> dict[str, Any] | None:
    """Keep one planner widget if it has a usable question."""
    if not isinstance(raw, dict):
        return None

    question = str(raw.get("question") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not question:
        return None

    widget_type = str(raw.get("type") or "chart").strip().lower()
    if widget_type not in ALLOWED_TYPES:
        widget_type = "chart"

    chart_type = str(raw.get("chart_type") or widget_type).strip().lower()
    if widget_type == "kpi":
        chart_type = "kpi"
    elif widget_type == "table":
        chart_type = "table"
    elif chart_type == "kpi":
        widget_type = "kpi"
    elif chart_type == "table":
        widget_type = "table"
    elif chart_type not in ALLOWED_CHARTS:
        chart_type = "bar"

    return {
        "widget_id": str(raw.get("widget_id") or new_widget_id()),
        "title": title or f"Widget {index + 1}",
        "type": widget_type,
        "chart_type": chart_type,
        "question": question,
    }


def dedupe_widget_specs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for spec in specs:
        key = _SPACE.sub(" ", f"{spec.get('question') or spec.get('title') or ''}").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(spec)
        if len(unique) >= MAX_WIDGETS:
            break
    return unique


def normalize_plan_widgets(raw_widgets: Any) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    if not isinstance(raw_widgets, list):
        return specs
    for index, raw in enumerate(raw_widgets):
        spec = normalize_widget_spec(raw, index)
        if spec:
            specs.append(spec)
    return dedupe_widget_specs(specs)


def _occupied_cells(layout: list[dict[str, Any]]) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for item in layout or []:
        try:
            x = int(item.get("x") or 0)
            y = int(item.get("y") or 0)
            width = int(item.get("w") or 1)
            height = int(item.get("h") or 1)
        except (TypeError, ValueError):
            continue
        for row in range(y, y + height):
            for col in range(x, x + width):
                cells.add((col, row))
    return cells


def _first_fit(
    layout: list[dict[str, Any]],
    width: int,
    height: int,
) -> tuple[int, int]:
    """Top-left empty slot that fits this widget on the 12-column board."""
    cells = _occupied_cells(layout)
    max_y = 0
    for _col, row in cells:
        max_y = max(max_y, row + 1)
    for y in range(0, max_y + 1):
        for x in range(0, GRID_COLUMNS - width + 1):
            if all(
                (col, row) not in cells
                for row in range(y, y + height)
                for col in range(x, x + width)
            ):
                return x, y
    return 0, max_y


def extend_layout(
    existing_layout: list[dict[str, Any]] | None,
    new_widgets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep current tiles and drop new ones into the first open gap."""
    layout = [dict(item) for item in (existing_layout or []) if isinstance(item, dict)]
    for widget in new_widgets:
        width, height = WIDGET_SIZES.get(widget.get("type") or "chart", WIDGET_SIZES["chart"])
        x, y = _first_fit(layout, width, height)
        layout.append({
            "id": widget.get("widget_id"),
            "x": x,
            "y": y,
            "w": width,
            "h": height,
        })
    return layout


def pack_layout(widgets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Place widgets left-to-right on a 12-column GridStack board."""
    x = 0
    y = 0
    row_height = 0
    layout: list[dict[str, Any]] = []

    for widget in widgets:
        width, height = WIDGET_SIZES.get(widget.get("type") or "chart", WIDGET_SIZES["chart"])
        if x + width > GRID_COLUMNS:
            x = 0
            y += row_height
            row_height = 0
        layout.append({
            "id": widget.get("widget_id"),
            "x": x,
            "y": y,
            "w": width,
            "h": height,
        })
        x += width
        row_height = max(row_height, height)

    return layout


def layout_map(layout: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in layout or []
        if isinstance(item, dict) and item.get("id")
    }
