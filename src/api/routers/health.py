from fastapi import APIRouter
from loguru import logger

from src.infrastructure.db import db_manager
from src.api.data_models import HealthResponse
from src.infrastructure.config import ENABLE_DYNAMIC_FEW_SHOT, ENABLE_SEMANTIC_CACHE

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
            cache_enabled=ENABLE_SEMANTIC_CACHE,
            few_shot_enabled=ENABLE_DYNAMIC_FEW_SHOT,
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            database_connected=False,
            total_tables=0,
            cache_enabled=ENABLE_SEMANTIC_CACHE,
            few_shot_enabled=ENABLE_DYNAMIC_FEW_SHOT,
        )
