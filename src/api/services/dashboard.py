"""Dashboard compose, persist, and refresh helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Optional

from src.agents.dashboard_layout import extend_layout, pack_layout
from src.agents.dashboard_composer import dashboard_composer
from src.memory.dashboard_store import dashboard_store


def public_dashboard(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    widgets = record.get("widgets") or []
    layout = record.get("layout") or pack_layout(widgets)
    return {
        "dashboard_id": record.get("dashboard_id"),
        "title": record.get("title"),
        "requirement_text": record.get("requirement_text") or "",
        "layout": layout,
        "widgets": widgets,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "success": True,
        "error": None,
    }


async def stream_compose_and_save(
    *,
    requirement: str,
    user_id: str,
    user_role: Optional[str],
    allowed_rep_codes: list[str],
    dashboard_id: Optional[str] = None,
) -> AsyncIterator[dict[str, Any]]:
    existing = None
    if dashboard_id:
        existing = dashboard_store.get(dashboard_id, user_id)

    payload = None
    async for event in dashboard_composer.stream_compose(
        requirement,
        allowed_rep_codes=allowed_rep_codes,
        user_role=user_role,
        user_id=user_id,
        mode="compose",
    ):
        if event.get("type") == "result":
            payload = event.get("payload") or {}
            if payload.get("success"):
                saved = dashboard_store.upsert(
                    user_id=user_id,
                    title=payload.get("title") or (existing or {}).get("title") or "Sales dashboard",
                    requirement_text=requirement,
                    layout=payload.get("layout") or [],
                    widgets=payload.get("widgets") or [],
                    dashboard_id=dashboard_id or (existing or {}).get("dashboard_id"),
                )
                public = public_dashboard(saved)
                event = {"type": "result", "payload": public}
        yield event
        if event.get("type") == "done" and payload is None:
            return


def add_widget(
    *,
    dashboard_id: str,
    requirement: str,
    user_id: str,
    user_role: Optional[str],
    allowed_rep_codes: list[str],
) -> dict[str, Any]:
    current = dashboard_store.get(dashboard_id, user_id)
    if not current:
        return {"success": False, "error": "Dashboard not found.", "status_code": 404}

    composed = dashboard_composer.compose(
        requirement,
        allowed_rep_codes=allowed_rep_codes,
        user_role=user_role,
        user_id=user_id,
        existing_widgets=current.get("widgets") or [],
        mode="add",
    )
    if not composed.get("success"):
        composed["status_code"] = 400
        return composed

    existing_ids = {widget.get("widget_id") for widget in current.get("widgets") or []}
    new_widgets = [
        widget for widget in (composed.get("widgets") or [])
        if widget.get("widget_id") not in existing_ids
    ]
    layout = extend_layout(current.get("layout") or [], new_widgets)
    saved = dashboard_store.update(
        dashboard_id,
        user_id,
        widgets=composed.get("widgets") or [],
        layout=layout,
        title=current.get("title"),
    )
    return public_dashboard(saved) or composed


def refresh_dashboard(
    *,
    dashboard_id: str,
    user_id: str,
    allowed_rep_codes: list[str],
) -> dict[str, Any]:
    current = dashboard_store.get(dashboard_id, user_id)
    if not current:
        return {"success": False, "error": "Dashboard not found.", "status_code": 404}

    widgets = dashboard_composer.refresh_widgets(
        current.get("widgets") or [],
        allowed_rep_codes,
    )
    saved = dashboard_store.update(
        dashboard_id,
        user_id,
        widgets=widgets,
        layout=current.get("layout") or pack_layout(widgets),
    )
    return public_dashboard(saved) or {"success": False, "error": "Failed to save refresh."}


def save_dashboard(
    *,
    dashboard_id: str,
    user_id: str,
    title: Optional[str] = None,
    layout: Optional[list[dict[str, Any]]] = None,
    widgets: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    saved = dashboard_store.update(
        dashboard_id,
        user_id,
        title=title,
        layout=layout,
        widgets=widgets,
    )
    if not saved:
        return {"success": False, "error": "Dashboard not found.", "status_code": 404}
    return public_dashboard(saved) or saved
