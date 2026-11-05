from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger

from src.api.data_models import (
    DashboardComposeRequest,
    DashboardFilterRequest,
    DashboardSaveRequest,
    DashboardWidgetAddRequest,
)
from src.api.dependencies import require_user
from src.services.dashboard_service import (
    add_widget,
    public_dashboard,
    refresh_dashboard,
    save_dashboard,
    stream_apply_filters_and_save,
    stream_compose_and_save,
)
from src.memory.dashboard_store import dashboard_store

router = APIRouter(tags=["dashboards"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str, ensure_ascii=False)}\n\n"


def _user_id(user: dict[str, Any]) -> str:
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Please login first.")
    return str(user_id)


async def _sse_compose(**kwargs) -> AsyncIterator[str]:
    try:
        async for event in stream_compose_and_save(**kwargs):
            yield _sse(event)
    except Exception as exc:
        logger.error(f"Dashboard compose error: {exc}")
        yield _sse({"type": "error", "error": str(exc)})
        yield _sse({"type": "done"})


async def _sse_filter(**kwargs) -> AsyncIterator[str]:
    try:
        async for event in stream_apply_filters_and_save(**kwargs):
            yield _sse(event)
    except Exception as exc:
        logger.error(f"Dashboard filter error: {exc}")
        yield _sse({"type": "error", "error": str(exc)})
        yield _sse({"type": "done"})


@router.get("/dashboards")
async def list_dashboards(user: dict[str, Any] = Depends(require_user)):
    return {
        "success": True,
        "dashboards": dashboard_store.list_for_user(_user_id(user)),
    }


@router.post("/dashboards/compose")
async def compose_dashboard(
    request: DashboardComposeRequest,
    user: dict[str, Any] = Depends(require_user),
):
    requirement = (request.requirement or "").strip()
    if not requirement:
        raise HTTPException(status_code=400, detail="Describe the dashboard you need.")

    return StreamingResponse(
        _sse_compose(
            requirement=requirement,
            user_id=_user_id(user),
            user_role=user.get("user_role"),
            allowed_rep_codes=user.get("allowed_rep_codes") or [],
            dashboard_id=request.dashboard_id,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(dashboard_id: str, user: dict[str, Any] = Depends(require_user)):
    record = dashboard_store.get(dashboard_id, _user_id(user))
    if not record:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    return public_dashboard(record)


@router.put("/dashboards/{dashboard_id}")
async def update_dashboard(
    dashboard_id: str,
    request: DashboardSaveRequest,
    user: dict[str, Any] = Depends(require_user),
):
    result = save_dashboard(
        dashboard_id=dashboard_id,
        user_id=_user_id(user),
        title=request.title,
        layout=request.layout,
        widgets=request.widgets,
        filters=request.filters,
    )
    if result.get("status_code") == 404:
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.post("/dashboards/{dashboard_id}/refresh")
async def refresh_saved_dashboard(
    dashboard_id: str,
    user: dict[str, Any] = Depends(require_user),
):
    result = refresh_dashboard(
        dashboard_id=dashboard_id,
        user_id=_user_id(user),
        allowed_rep_codes=user.get("allowed_rep_codes") or [],
    )
    if result.get("status_code") == 404:
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.post("/dashboards/{dashboard_id}/filter")
async def filter_dashboard(
    dashboard_id: str,
    request: DashboardFilterRequest,
    user: dict[str, Any] = Depends(require_user),
):
    return StreamingResponse(
        _sse_filter(
            dashboard_id=dashboard_id,
            user_id=_user_id(user),
            user_role=user.get("user_role"),
            allowed_rep_codes=user.get("allowed_rep_codes") or [],
            filters=request.model_dump(),
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/dashboards/{dashboard_id}/widgets")
async def add_dashboard_widget(
    dashboard_id: str,
    request: DashboardWidgetAddRequest,
    user: dict[str, Any] = Depends(require_user),
):
    requirement = (request.requirement or "").strip()
    if not requirement:
        raise HTTPException(status_code=400, detail="Describe the widget to add.")
    result = add_widget(
        dashboard_id=dashboard_id,
        requirement=requirement,
        user_id=_user_id(user),
        user_role=user.get("user_role"),
        allowed_rep_codes=user.get("allowed_rep_codes") or [],
    )
    status = result.pop("status_code", None)
    if status == 404:
        raise HTTPException(status_code=404, detail=result.get("error"))
    if status == 400:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.delete("/dashboards/{dashboard_id}")
async def delete_dashboard(dashboard_id: str, user: dict[str, Any] = Depends(require_user)):
    deleted = dashboard_store.delete(dashboard_id, _user_id(user))
    if not deleted:
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    return {"success": True, "dashboard_id": dashboard_id}
