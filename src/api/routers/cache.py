from fastapi import APIRouter, HTTPException
from loguru import logger

from ...agents.tools import semantic_cache

router = APIRouter(tags=["cache"])


@router.delete("/cache")
async def clear_cache():
    try:
        semantic_cache.clear()
        return {"message": "Cache cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))
