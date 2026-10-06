"""FastAPI application assembly."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from ..config import settings
from ..core import db_manager
from .routers import auth, cache, conversations, examples, feedback, health, knowledge, query, schema

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

app = FastAPI(
    title="Text-to-SQL Agent API",
    description="REST API for the Text-to-SQL multi-agent system",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(knowledge.router)
app.include_router(feedback.router)
app.include_router(schema.router)
app.include_router(examples.router)
app.include_router(cache.router)
app.include_router(query.router)


@app.get("/app", include_in_schema=False)
async def serve_app():
    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not found. Missing web/index.html")
    return FileResponse(index)


static_dir = WEB_DIR / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.on_event("startup")
async def startup_event():
    logger.info("Starting Text-to-SQL Agent API")
    logger.info(f"Database: {settings.database_uri}")
    logger.info(
        f"Semantic Cache: {'Enabled' if settings.enable_semantic_cache else 'Disabled'}"
    )
    logger.info(
        f"Few-Shot Learning: {'Enabled' if settings.enable_dynamic_few_shot else 'Disabled'}"
    )


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Text-to-SQL Agent API")
    db_manager.close()
