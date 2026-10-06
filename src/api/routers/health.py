from fastapi import APIRouter
from loguru import logger

from ...config import settings
from ...core import db_manager
from ..data_models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/")
async def root():
    return {
        "name": "Text-to-SQL Agent API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "app": "/app",
    }


@router.get("/health", response_model=HealthResponse)
async def health_check():
    try:
        tables = db_manager.get_all_table_names()
        return HealthResponse(
            status="healthy",
            database_connected=True,
            total_tables=len(tables),
            cache_enabled=settings.enable_semantic_cache,
            few_shot_enabled=settings.enable_dynamic_few_shot,
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            database_connected=False,
            total_tables=0,
            cache_enabled=settings.enable_semantic_cache,
            few_shot_enabled=settings.enable_dynamic_few_shot,
        )
