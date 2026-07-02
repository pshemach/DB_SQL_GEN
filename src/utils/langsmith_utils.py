from ..config import settings
import os

def setup_langsmith():
    """
    Set LangChain environment variables from settings so every
    """
    if not settings.langchain_tracing_v2:
        return                           # tracing off — skip

    os.environ["LANGCHAIN_TRACING_V2"]  = "true"
    os.environ["LANGCHAIN_API_KEY"]     = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"]     = settings.langchain_project
    os.environ["LANGCHAIN_ENDPOINT"]    = settings.langchain_endpoint