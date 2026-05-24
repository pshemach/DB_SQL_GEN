"""Central LLM clients: Anthropic for planner/SQL gen; OpenAI for everything else."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from ..config import settings


def anthropic_llm(*, temperature: float | None = 0.0) -> ChatAnthropic:
    """Planner, SQL generator, and other reasoning-heavy SQL steps."""
    kwargs: dict = {
        "model": settings.anthropic_model_fast,
        "api_key": settings.anthropic_api_key,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatAnthropic(**kwargs)


def openai_llm(*, temperature: float | None = 0.0) -> ChatOpenAI:
    """Routers, formatters, guardrails, critics, retrieval helpers, etc."""
    kwargs: dict = {
        "model": settings.openai_model_fast,
        "api_key": settings.openai_api_key,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)
