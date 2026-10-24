"""OpenAI embedding client shared by vector stores and the semantic cache."""

from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from loguru import logger

from src.infrastructure.config import EMBEDDING_MODEL, get_api_key


@lru_cache(maxsize=1)
def get_default_embeddings() -> OpenAIEmbeddings:
    """Return a process-wide OpenAIEmbeddings instance."""
    logger.info(f"Initializing OpenAI embeddings: {EMBEDDING_MODEL}")
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        api_key=get_api_key("openai"),
    )


def get_embeddings() -> OpenAIEmbeddings:
    """Alias kept for call sites that still say get_embeddings()."""
    return get_default_embeddings()
