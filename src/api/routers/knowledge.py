from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...agents.tools.business_knowledge_store import business_knowledge_store
from ..data_models import KnowledgeDefinitionRequest
from ..dependencies import require_knowledge_admin

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/definitions")
async def list_definitions(_user: dict[str, Any] = Depends(require_knowledge_admin)):
    return {"success": True, "definitions": business_knowledge_store.list_definitions() or {}}


@router.post("/reload")
async def reload_definitions(_user: dict[str, Any] = Depends(require_knowledge_admin)):
    business_knowledge_store.reload()
    return {
        "success": True,
        "message": "Knowledge base reloaded",
        "definitions": business_knowledge_store.list_definitions(),
    }


@router.post("/definitions")
async def upsert_definition(
    request: KnowledgeDefinitionRequest,
    _user: dict[str, Any] = Depends(require_knowledge_admin),
):
    key = (request.key or "").strip()
    definition = (request.definition or "").strip()
    keywords = [x.strip() for x in (request.keywords or []) if str(x).strip()]

    if not key:
        raise HTTPException(status_code=400, detail="KPI key is required.")
    if not definition:
        raise HTTPException(status_code=400, detail="Definition is required.")
    if not keywords:
        raise HTTPException(status_code=400, detail="At least one keyword is required.")

    saved_key = business_knowledge_store.upsert_definition(
        key=key,
        keywords=keywords,
        definition=definition,
    )
    return {
        "success": True,
        "message": f"Saved KPI definition: {saved_key}",
        "key": saved_key,
        "definitions": business_knowledge_store.list_definitions(),
    }


@router.delete("/definitions/{key}")
async def delete_definition(key: str, _user: dict[str, Any] = Depends(require_knowledge_admin)):
    business_knowledge_store.delete_definition(key)
    return {
        "success": True,
        "message": f"Deleted: {key}",
        "definitions": business_knowledge_store.list_definitions(),
    }
