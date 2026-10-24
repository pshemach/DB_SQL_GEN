"""
Chat LLM providers.

Role-sized constructors, same shape as a class-based service layer:
    get_router_llm()      — intent and schema classification (OpenAI)
    get_chat_llm()        — formatting, critique, and conversation (OpenAI)
    get_reasoning_llm()   — planner and SQL generation (Anthropic)
    get_fast_chat_llm()   — Groq path used by the in-memory SQL planner
    get_extractor_llm()   — short structured extraction (Groq fast model)

Which agent calls which function is unchanged from the previous factory.
"""

from typing import Any, Optional

from langchain_anthropic import ChatAnthropic
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from src.infrastructure.config import (
    CHAT_MODEL,
    CHAT_PROVIDER,
    EXTRACTOR_MODEL,
    EXTRACTOR_PROVIDER,
    FAST_CHAT_MODEL,
    FAST_CHAT_PROVIDER,
    REASONING_MODEL,
    REASONING_PROVIDER,
    ROUTER_MODEL,
    ROUTER_PROVIDER,
    get_api_key,
)


def _build_llm(
    model: str,
    provider: str,
    temperature: Optional[float] = 0.0,
    **kwargs: Any,
):
    """Build a chat model for one provider. Native SDKs, not a shared proxy."""
    llm_kwargs: dict[str, Any] = {"model": model, **kwargs}
    if temperature is not None:
        llm_kwargs["temperature"] = temperature

    if provider == "anthropic":
        llm_kwargs["api_key"] = get_api_key("anthropic")
        return ChatAnthropic(**llm_kwargs)
    if provider == "groq":
        llm_kwargs["api_key"] = get_api_key("groq")
        return ChatGroq(**llm_kwargs)
    if provider == "openai":
        llm_kwargs["api_key"] = get_api_key("openai")
        return ChatOpenAI(**llm_kwargs)

    raise ValueError(f"Unsupported LLM provider: {provider}")


def get_router_llm(temperature: Optional[float] = 0.0, **kwargs: Any) -> ChatOpenAI:
    """LLM for routing, schema linking, and other classification steps."""
    return _build_llm(ROUTER_MODEL, ROUTER_PROVIDER, temperature=temperature, **kwargs)


def get_chat_llm(temperature: Optional[float] = 0.0, **kwargs: Any) -> ChatOpenAI:
    """LLM for user-facing synthesis: formatting, critique, and chit-chat."""
    return _build_llm(CHAT_MODEL, CHAT_PROVIDER, temperature=temperature, **kwargs)


def get_reasoning_llm(temperature: Optional[float] = 0.0, **kwargs: Any) -> ChatAnthropic:
    """LLM for the planner and the SQL generator."""
    return _build_llm(REASONING_MODEL, REASONING_PROVIDER, temperature=temperature, **kwargs)


def get_fast_chat_llm(
    temperature: Optional[float] = 0.0,
    model: Optional[str] = None,
    **kwargs: Any,
) -> ChatGroq:
    """Groq client. Default model is the configured reasoning model."""
    return _build_llm(
        model or FAST_CHAT_MODEL,
        FAST_CHAT_PROVIDER,
        temperature=temperature,
        **kwargs,
    )


def get_extractor_llm(temperature: Optional[float] = 0.0, **kwargs: Any) -> ChatGroq:
    """Groq fast model for short structured extraction."""
    return _build_llm(EXTRACTOR_MODEL, EXTRACTOR_PROVIDER, temperature=temperature, **kwargs)
