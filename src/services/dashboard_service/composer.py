"""Compose dashboard widgets through the dashboard orchestrators."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from src.agents.dashboard.orchestrator import (
    DashboardComposeOrchestrator,
    DashboardFilterOrchestrator,
    DashboardRefreshOrchestrator,
)


class DashboardComposer:
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
        return DashboardComposeOrchestrator().run(
            requirement,
            allowed_rep_codes=allowed_rep_codes,
            user_role=user_role,
            user_id=user_id,
            existing_widgets=existing_widgets,
            mode=mode,
            filters=filters,
        )

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
        async for event in DashboardComposeOrchestrator().stream(
            requirement,
            allowed_rep_codes=allowed_rep_codes,
            user_role=user_role,
            user_id=user_id,
            existing_widgets=existing_widgets,
            mode=mode,
            filters=filters,
        ):
            yield event

    def build_widget(
        self,
        spec: dict[str, Any],
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
        question_override: str | None = None,
    ) -> dict[str, Any]:
        return DashboardComposeOrchestrator().build_widget(
            spec,
            allowed_rep_codes=allowed_rep_codes,
            user_role=user_role,
            user_id=user_id,
            question_override=question_override,
        )

    def refresh_widgets(
        self,
        widgets: list[dict[str, Any]],
        allowed_rep_codes: list[str],
    ) -> list[dict[str, Any]]:
        return DashboardRefreshOrchestrator().run(widgets, allowed_rep_codes)

    def refresh_widget(
        self,
        widget: dict[str, Any],
        allowed_rep_codes: list[str],
    ) -> dict[str, Any]:
        return DashboardRefreshOrchestrator().refresh_widget(widget, allowed_rep_codes)

    def load_dimension_values(
        self,
        dimensions: list[str],
        widgets: list[dict[str, Any]],
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        return DashboardComposeOrchestrator().load_dimension_values(
            dimensions,
            widgets,
            allowed_rep_codes=allowed_rep_codes,
            user_role=user_role,
            user_id=user_id,
        )

    async def stream_apply_filters(
        self,
        widgets: list[dict[str, Any]],
        filters: dict[str, Any] | None,
        *,
        allowed_rep_codes: list[str],
        user_role: str | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in DashboardFilterOrchestrator().stream(
            widgets,
            filters,
            allowed_rep_codes=allowed_rep_codes,
            user_role=user_role,
            user_id=user_id,
        ):
            yield event

    def apply_filters_to_widget(
        self,
        widget: dict[str, Any],
        filters: dict[str, Any] | None,
        allowed_rep_codes: list[str],
    ) -> dict[str, Any]:
        return DashboardFilterOrchestrator().apply_filters_to_widget(
            widget,
            filters,
            allowed_rep_codes,
        )
