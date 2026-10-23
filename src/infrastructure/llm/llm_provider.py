"""LLM factories: mid-tier for SQL, small models for routing/tools, Opus for escalation."""

from __future__ import annotations

from typing import Any

from src.infrastructure.config import settings


def anthropic_llm(*, temperature: float | None = 0.0, escalate: bool = False):
    from langchain_anthropic import ChatAnthropic

    model = settings.anthropic_model_escalate if escalate else settings.anthropic_model_fast
    kwargs: dict[str, Any] = {"model": model, "api_key": settings.anthropic_api_key}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatAnthropic(**kwargs)


def openai_llm(*, temperature: float | None = 0.0):
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": settings.openai_model_fast,
        "api_key": settings.openai_api_key,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


def groq_llm(*, temperature: float | None = 0.0, model: str | None = None):
    from langchain_groq import ChatGroq

    kwargs: dict[str, Any] = {
        "model": model or settings.groq_model_reasoning,
        "api_key": settings.groq_api_key,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatGroq(**kwargs)
