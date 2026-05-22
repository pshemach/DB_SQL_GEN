"""Shared OpenAI embedding client for vector stores and semantic cache."""

from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from loguru import logger

from ..config import settings


@lru_cache(maxsize=1)
def get_embeddings() -> OpenAIEmbeddings:
    """Return a singleton OpenAIEmbeddings instance."""
    logger.info(f"Initializing OpenAI embeddings: {settings.embedding_model}")
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key,
    )
