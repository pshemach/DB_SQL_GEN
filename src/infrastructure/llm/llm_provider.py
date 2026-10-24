"""
Chat LLM providers. One constructor per agent role:

    get_router_llm()            — turn routing
    get_planner_llm()           — logical plan
    get_schema_selection_llm()  — table selection
    get_generator_llm()         — SQL generation
    get_direct_llm()            — answers, critique, and chitchat
    get_fast_chat_llm()         — in-memory SQL planner
"""

from typing import Any, Optional

from langchain_anthropic import ChatAnthropic
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from src.infrastructure.config import (
    DIRECT_MODEL,
    DIRECT_PROVIDER,
    FAST_CHAT_MODEL,
    FAST_CHAT_PROVIDER,
    GENERATOR_MODEL,
    GENERATOR_PROVIDER,
    PLANNER_MODEL,
    PLANNER_PROVIDER,
    ROUTER_MODEL,
    ROUTER_PROVIDER,
    SCHEMA_SELECTION_MODEL,
    SCHEMA_SELECTION_PROVIDER,
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


def get_router_llm(temperature: Optional[float] = 0.0, **kwargs: Any):
    """LLM for turn routing."""
    return _build_llm(ROUTER_MODEL, ROUTER_PROVIDER, temperature=temperature, **kwargs)


def get_planner_llm(temperature: Optional[float] = 0.0, **kwargs: Any):
    """LLM for the logical plan."""
    return _build_llm(PLANNER_MODEL, PLANNER_PROVIDER, temperature=temperature, **kwargs)


def get_schema_selection_llm(temperature: Optional[float] = 0.0, **kwargs: Any):
    """LLM for choosing tables and columns."""
    return _build_llm(
        SCHEMA_SELECTION_MODEL, SCHEMA_SELECTION_PROVIDER, temperature=temperature, **kwargs
    )


def get_generator_llm(temperature: Optional[float] = 0.0, **kwargs: Any):
    """LLM for SQL generation."""
    return _build_llm(GENERATOR_MODEL, GENERATOR_PROVIDER, temperature=temperature, **kwargs)


def get_direct_llm(temperature: Optional[float] = 0.0, **kwargs: Any):
    """LLM for answers, critique, and chitchat."""
    return _build_llm(DIRECT_MODEL, DIRECT_PROVIDER, temperature=temperature, **kwargs)


def get_chat_llm(temperature: Optional[float] = 0.0, **kwargs: Any):
    """Alias of get_direct_llm."""
    return get_direct_llm(temperature=temperature, **kwargs)


def get_reasoning_llm(temperature: Optional[float] = 0.0, **kwargs: Any):
    """Alias of get_planner_llm."""
    return get_planner_llm(temperature=temperature, **kwargs)


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


def get_extractor_llm(temperature: Optional[float] = 0.0, **kwargs: Any):
    """Short structured extraction. Uses the fast chat model."""
    return get_fast_chat_llm(temperature=temperature, **kwargs)
