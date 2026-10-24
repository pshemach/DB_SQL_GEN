"""
Application configuration.

CONFIGURATION POLICY
====================
Non-secret values load from config/param.yaml and config/models.yaml.
Secrets (API keys, database URI) live ONLY in .env and are read with os.getenv().
An environment variable overrides the YAML value when it is set.

Model roles used by infrastructure.llm:
    Routing:    OpenAI fast model   — classification and schema linking
    Chat:       OpenAI fast model   — formatting, critique, chit-chat
    Reasoning:  Anthropic           — planner and SQL generation
    Fast chat:  Groq reasoning      — in-memory SQL planner
    Extractor:  Groq fast model     — short structured extraction
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv
from loguru import logger

# ========================================
# Project Paths
# ========================================

# src/infrastructure/config.py -> project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _PROJECT_ROOT / "config"

load_dotenv(_PROJECT_ROOT / ".env")

PROJECT_ROOT = _PROJECT_ROOT


# ========================================
# YAML Config Loading
# ========================================

def _load_yaml(filename: str) -> Dict[str, Any]:
    """Load a YAML config file. Missing files yield an empty dict."""
    filepath = _CONFIG_DIR / filename
    if not filepath.exists():
        return {}
    with open(filepath, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _get_nested(data: Dict, *keys, default=None):
    """Get a nested dictionary value safely."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return default if current is None else current


def _coerce(raw: str, sample: Any) -> Any:
    """Cast an environment string to the type of the YAML/default value."""
    if isinstance(sample, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(sample, int) and not isinstance(sample, bool):
        return int(raw)
    if isinstance(sample, float):
        return float(raw)
    return raw


def _setting(env_name: str, yaml_value: Any, default: Any) -> Any:
    """Environment wins, then YAML, then the hardcoded default."""
    sample = default if yaml_value is None else yaml_value
    raw = os.getenv(env_name)
    if raw is not None and str(raw).strip() != "":
        return _coerce(raw, sample)
    if yaml_value is not None:
        return yaml_value
    return default


_PARAMS = _load_yaml("param.yaml")
_MODELS = _load_yaml("models.yaml")


# ========================================
# Model Names
# ========================================

OPENAI_MODEL_FAST = _setting(
    "OPENAI_MODEL_FAST",
    _get_nested(_MODELS, "openai", "chat", "fast"),
    "gpt-4o-mini",
)
ANTHROPIC_MODEL_FAST = _setting(
    "ANTHROPIC_MODEL_FAST",
    _get_nested(_MODELS, "anthropic", "chat", "fast"),
    "claude-opus-4-5",
)
GROQ_MODEL_REASONING = _setting(
    "GROQ_MODEL_REASONING",
    _get_nested(_MODELS, "groq", "chat", "reasoning"),
    "llama-3.3-70b-versatile",
)
GROQ_MODEL_FAST = _setting(
    "GROQ_MODEL_FAST",
    _get_nested(_MODELS, "groq", "chat", "fast"),
    "llama-3.1-8b-instant",
)
GROQ_TEMPERATURE = _setting("GROQ_TEMPERATURE", _get_nested(_PARAMS, "llm", "temperature"), 0.0)

EMBEDDING_TIER = _get_nested(_PARAMS, "embedding", "tier", default="small")
EMBEDDING_MODEL = _setting(
    "EMBEDDING_MODEL",
    _get_nested(_MODELS, "openai", "embedding", EMBEDDING_TIER),
    "text-embedding-3-small",
)

# text-embedding-3-small / ada-002 -> 1536; text-embedding-3-large -> 3072
EMBEDDING_DIM = 3072 if "large" in str(EMBEDDING_MODEL).lower() else 1536

# ========================================
# Model roles (consumed by infrastructure.llm)
# ========================================

ROUTER_MODEL = OPENAI_MODEL_FAST
ROUTER_PROVIDER = "openai"

CHAT_MODEL = OPENAI_MODEL_FAST
CHAT_PROVIDER = "openai"

REASONING_MODEL = ANTHROPIC_MODEL_FAST
REASONING_PROVIDER = "anthropic"

FAST_CHAT_MODEL = OPENAI_MODEL_FAST
FAST_CHAT_PROVIDER = "openai"

EXTRACTOR_MODEL = OPENAI_MODEL_FAST
EXTRACTOR_PROVIDER = "openai"

LLM_TEMPERATURE = _setting("LLM_TEMPERATURE", _get_nested(_PARAMS, "llm", "temperature"), 0.0)


# ========================================
# Secrets — environment only
# ========================================

def get_api_key(provider: Optional[str] = None) -> Optional[str]:
    """Return the API key for a provider. Secrets are never read from YAML."""
    provider = (provider or "openai").lower()
    key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    env_var = key_map.get(provider, f"{provider.upper()}_API_KEY")
    value = os.getenv(env_var)
    return value or None


# ========================================
# Database, vector store, auth, tracing
# ========================================

DATABASE_URI = os.getenv("DATABASE_URI", "")

VECTOR_STORE_PATH = _setting(
    "VECTOR_STORE_PATH",
    _get_nested(_PARAMS, "paths", "vector_store"),
    "./database/vector_store",
)
CHROMA_COLLECTION_NAME = _setting(
    "SQL_EXAMPLES_COLLECTION_NAME",
    _get_nested(_PARAMS, "vector_store", "chroma_collection_name"),
    "sql_examples",
)
BUSINESS_DEFINITION_COLLECTION_NAME = _get_nested(
    _PARAMS, "vector_store", "business_definition_collection_name", default="business_definition"
)
BUSINESS_DOC_YAML_PATH = _setting(
    "BUSINESS_DOC_YAML_PATH",
    _get_nested(_PARAMS, "paths", "business_doc_yaml"),
    "data/business_definitions.yaml",
)

ENABLE_SEMANTIC_CACHE = _setting(
    "ENABLE_SEMANTIC_CACHE",
    _get_nested(_PARAMS, "cache", "enable_semantic_cache"),
    True,
)
CACHE_SIMILARITY_THRESHOLD = _setting(
    "CACHE_SIMILARITY_THRESHOLD",
    _get_nested(_PARAMS, "cache", "similarity_threshold"),
    0.99,
)

MAX_ITERATIONS = _setting("MAX_ITERATIONS", _get_nested(_PARAMS, "agent", "max_iterations"), 1)
ENABLE_SELF_CORRECTION = _setting(
    "ENABLE_SELF_CORRECTION",
    _get_nested(_PARAMS, "agent", "enable_self_correction"),
    True,
)
ENABLE_DYNAMIC_FEW_SHOT = _setting(
    "ENABLE_DYNAMIC_FEW_SHOT",
    _get_nested(_PARAMS, "agent", "enable_dynamic_few_shot"),
    True,
)
FEW_SHOT_EXAMPLES_COUNT = _setting(
    "FEW_SHOT_EXAMPLES_COUNT",
    _get_nested(_PARAMS, "agent", "few_shot_examples_count"),
    3,
)
QUERY_TIMEOUT_SECONDS = _setting(
    "QUERY_TIMEOUT_SECONDS",
    _get_nested(_PARAMS, "agent", "query_timeout_seconds"),
    60,
)

ENABLE_PRODUCTION_GRAPH = _setting(
    "ENABLE_PRODUCTION_GRAPH",
    _get_nested(_PARAMS, "graph", "enable_production_graph"),
    True,
)
ENABLE_CLARIFY = _setting("ENABLE_CLARIFY", _get_nested(_PARAMS, "graph", "enable_clarify"), True)
ENABLE_TRANSFORM_PREVIOUS = _setting(
    "ENABLE_TRANSFORM_PREVIOUS",
    _get_nested(_PARAMS, "graph", "enable_transform_previous"),
    True,
)
ENABLE_PRE_EXEC_CRITIC = _setting(
    "ENABLE_PRE_EXEC_CRITIC",
    _get_nested(_PARAMS, "graph", "enable_pre_exec_critic"),
    False,
)
ENABLE_RESULT_VERIFIER = _setting(
    "ENABLE_RESULT_VERIFIER",
    _get_nested(_PARAMS, "graph", "enable_result_verifier"),
    True,
)
GRAPH_RECURSION_LIMIT = _setting(
    "GRAPH_RECURSION_LIMIT",
    _get_nested(_PARAMS, "graph", "recursion_limit"),
    50,
)
GRAPH_TIMEOUT_SECONDS = _setting(
    "GRAPH_TIMEOUT_SECONDS",
    _get_nested(_PARAMS, "graph", "timeout_seconds"),
    120,
)
SQL_MAX_ROWS = _setting("SQL_MAX_ROWS", _get_nested(_PARAMS, "graph", "sql_max_rows"), 1000)
CURRENCY_SYMBOL = _setting("CURRENCY_SYMBOL", _get_nested(_PARAMS, "graph", "currency_symbol"), "Rs")

LANGCHAIN_TRACING_V2 = _setting(
    "LANGCHAIN_TRACING_V2",
    _get_nested(_PARAMS, "langsmith", "tracing_v2"),
    False,
)
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT = _setting(
    "LANGCHAIN_PROJECT",
    _get_nested(_PARAMS, "langsmith", "project"),
    "sales-text-to-sql",
)
LANGCHAIN_ENDPOINT = _setting(
    "LANGCHAIN_ENDPOINT",
    _get_nested(_PARAMS, "langsmith", "endpoint"),
    "https://api.smith.langchain.com",
)

CHATBOT_AUTH_URL = os.getenv("CHATBOT_AUTH_URL", "")
CHATBOT_API_KEY = os.getenv("CHATBOT_API_KEY", "")
CHATBOT_BASE_URL = os.getenv("CHATBOT_BASE_URL", "")
CHATBOT_SYSTEM_LOGIN_URL = os.getenv("CHATBOT_SYSTEM_LOGIN_URL", "")

QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "") or None
QDRANT_URL = os.getenv("QDRANT_URL", "") or None
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "")


# ========================================
# Helpers
# ========================================

def validate() -> None:
    """
    Check required secrets.

    Raises:
        ValueError: If a required environment variable is missing.
    """
    required = {
        "OPENAI_API_KEY": get_api_key("openai"),
        "ANTHROPIC_API_KEY": get_api_key("anthropic"),
        "GROQ_API_KEY": get_api_key("groq"),
        "DATABASE_URI": DATABASE_URI,
        "CHATBOT_AUTH_URL": CHATBOT_AUTH_URL,
        "CHATBOT_API_KEY": CHATBOT_API_KEY,
        "CHATBOT_BASE_URL": CHATBOT_BASE_URL,
        "CHATBOT_SYSTEM_LOGIN_URL": CHATBOT_SYSTEM_LOGIN_URL,
        "QDRANT_API_KEY": QDRANT_API_KEY,
        "QDRANT_URL": QDRANT_URL,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            f"Missing required secrets: {joined}. Add them to the .env file."
        )


def dump() -> None:
    """Log active non-secret configuration."""
    logger.info("=" * 60)
    logger.info("CONFIGURATION (NON-SECRETS ONLY)")
    logger.info("=" * 60)
    logger.info(f"Router model: {ROUTER_PROVIDER} / {ROUTER_MODEL}")
    logger.info(f"Chat model: {CHAT_PROVIDER} / {CHAT_MODEL}")
    logger.info(f"Reasoning model: {REASONING_PROVIDER} / {REASONING_MODEL}")
    logger.info(f"Fast chat model: {FAST_CHAT_PROVIDER} / {FAST_CHAT_MODEL}")
    logger.info(f"Extractor model: {EXTRACTOR_PROVIDER} / {EXTRACTOR_MODEL}")
    logger.info(f"Embedding model: {EMBEDDING_MODEL} ({EMBEDDING_DIM} dims)")
    logger.info(f"Vector store: {VECTOR_STORE_PATH}")
    logger.info(f"Semantic cache: {ENABLE_SEMANTIC_CACHE}")
    logger.info(f"Few-shot: {ENABLE_DYNAMIC_FEW_SHOT} (k={FEW_SHOT_EXAMPLES_COUNT})")
    logger.info(f"Production graph: {ENABLE_PRODUCTION_GRAPH}")
    logger.info(f"Qdrant URL: {'set' if QDRANT_URL else 'not set'}")
    logger.info("=" * 60)


def get_all_models() -> Dict[str, Any]:
    """Return the model catalog loaded from models.yaml."""
    return _MODELS


def get_config() -> Dict[str, Any]:
    """Return the parameter dictionary loaded from param.yaml."""
    return _PARAMS
