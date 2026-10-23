import os

from src.infrastructure.config import settings


def setup_langsmith() -> None:
    if not settings.langchain_tracing_v2:
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint


def build_invoke_config(session_id: str | None = None) -> dict:
    config: dict = {"recursion_limit": settings.graph_recursion_limit}
    if session_id:
        config["configurable"] = {"thread_id": session_id}
    return config
