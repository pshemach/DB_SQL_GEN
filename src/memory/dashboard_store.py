"""MySQL persistence for user-owned dashboard specs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from sqlalchemy import text

from src.infrastructure.db import db_manager


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _as_json(value: Any) -> str:
    return json.dumps(value if value is not None else [], default=str)


def _load_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


class DashboardStore:
    """Create, load, update, and delete dashboards for one user."""

    def __init__(self) -> None:
        self.table_name = "user_dashboards"
        self._create_table()

    def _create_table(self) -> None:
        sql = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            dashboard_id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(50) NOT NULL,
            title VARCHAR(200) NOT NULL,
            requirement_text TEXT,
            layout_json JSON,
            widgets_json JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_user_id (user_id),
            INDEX idx_updated_at (updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
        try:
            with db_manager.engine.begin() as conn:
                conn.execute(text(sql))
            logger.info("Dashboard table initialized")
        except Exception as exc:
            logger.warning(f"Dashboard table may already exist: {exc}")

    def create(
        self,
        *,
        user_id: str,
        title: str,
        requirement_text: str = "",
        layout: Optional[list[dict[str, Any]]] = None,
        widgets: Optional[list[dict[str, Any]]] = None,
        dashboard_id: Optional[str] = None,
    ) -> dict[str, Any]:
        record = {
            "dashboard_id": dashboard_id or str(uuid4()),
            "user_id": str(user_id),
            "title": (title or "Untitled dashboard").strip()[:200],
            "requirement_text": requirement_text or "",
            "layout": layout or [],
            "widgets": widgets or [],
            "created_at": _now(),
            "updated_at": _now(),
        }
        insert_sql = f"""
        INSERT INTO {self.table_name}
            (dashboard_id, user_id, title, requirement_text, layout_json, widgets_json, created_at, updated_at)
        VALUES
            (:dashboard_id, :user_id, :title, :requirement_text, :layout_json, :widgets_json, :created_at, :updated_at)
        """
        with db_manager.engine.begin() as conn:
            conn.execute(text(insert_sql), {
                "dashboard_id": record["dashboard_id"],
                "user_id": record["user_id"],
                "title": record["title"],
                "requirement_text": record["requirement_text"],
                "layout_json": _as_json(record["layout"]),
                "widgets_json": _as_json(record["widgets"]),
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            })
        return record

    def get(self, dashboard_id: str, user_id: str) -> Optional[dict[str, Any]]:
        sql = f"""
        SELECT dashboard_id, user_id, title, requirement_text, layout_json, widgets_json, created_at, updated_at
        FROM {self.table_name}
        WHERE dashboard_id = :dashboard_id AND user_id = :user_id
        """
        with db_manager.engine.connect() as conn:
            row = conn.execute(text(sql), {
                "dashboard_id": dashboard_id,
                "user_id": str(user_id),
            }).mappings().first()
        if not row:
            return None
        return self._from_row(row)

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        sql = f"""
        SELECT dashboard_id, user_id, title, requirement_text, layout_json, widgets_json, created_at, updated_at
        FROM {self.table_name}
        WHERE user_id = :user_id
        ORDER BY updated_at DESC
        """
        with db_manager.engine.connect() as conn:
            rows = conn.execute(text(sql), {"user_id": str(user_id)}).mappings().all()
        summaries = []
        for row in rows:
            record = self._from_row(row)
            summaries.append({
                "dashboard_id": record["dashboard_id"],
                "title": record["title"],
                "requirement_text": record["requirement_text"],
                "widget_count": len(record.get("widgets") or []),
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            })
        return summaries

    def update(
        self,
        dashboard_id: str,
        user_id: str,
        *,
        title: Optional[str] = None,
        requirement_text: Optional[str] = None,
        layout: Optional[list[dict[str, Any]]] = None,
        widgets: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[dict[str, Any]]:
        current = self.get(dashboard_id, user_id)
        if not current:
            return None
        if title is not None:
            current["title"] = (title or "Untitled dashboard").strip()[:200]
        if requirement_text is not None:
            current["requirement_text"] = requirement_text
        if layout is not None:
            current["layout"] = layout
        if widgets is not None:
            current["widgets"] = widgets
        current["updated_at"] = _now()

        sql = f"""
        UPDATE {self.table_name}
        SET title = :title,
            requirement_text = :requirement_text,
            layout_json = :layout_json,
            widgets_json = :widgets_json,
            updated_at = :updated_at
        WHERE dashboard_id = :dashboard_id AND user_id = :user_id
        """
        with db_manager.engine.begin() as conn:
            conn.execute(text(sql), {
                "dashboard_id": dashboard_id,
                "user_id": str(user_id),
                "title": current["title"],
                "requirement_text": current["requirement_text"],
                "layout_json": _as_json(current["layout"]),
                "widgets_json": _as_json(current["widgets"]),
                "updated_at": current["updated_at"],
            })
        return current

    def upsert(
        self,
        *,
        user_id: str,
        title: str,
        requirement_text: str = "",
        layout: Optional[list[dict[str, Any]]] = None,
        widgets: Optional[list[dict[str, Any]]] = None,
        dashboard_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if dashboard_id:
            updated = self.update(
                dashboard_id,
                user_id,
                title=title,
                requirement_text=requirement_text,
                layout=layout,
                widgets=widgets,
            )
            if updated:
                return updated
        return self.create(
            user_id=user_id,
            title=title,
            requirement_text=requirement_text,
            layout=layout,
            widgets=widgets,
            dashboard_id=dashboard_id,
        )

    def delete(self, dashboard_id: str, user_id: str) -> bool:
        sql = f"""
        DELETE FROM {self.table_name}
        WHERE dashboard_id = :dashboard_id AND user_id = :user_id
        """
        with db_manager.engine.begin() as conn:
            result = conn.execute(text(sql), {
                "dashboard_id": dashboard_id,
                "user_id": str(user_id),
            })
        return bool(result.rowcount)

    def _from_row(self, row: Any) -> dict[str, Any]:
        data = dict(row)
        created = data.get("created_at")
        updated = data.get("updated_at")
        return {
            "dashboard_id": data.get("dashboard_id"),
            "user_id": data.get("user_id"),
            "title": data.get("title"),
            "requirement_text": data.get("requirement_text") or "",
            "layout": _load_json(data.get("layout_json"), []),
            "widgets": _load_json(data.get("widgets_json"), []),
            "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
            "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
        }


dashboard_store = DashboardStore()
