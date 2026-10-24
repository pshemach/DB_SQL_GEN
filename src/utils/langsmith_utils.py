
import os
from src.infrastructure.config import LANGCHAIN_API_KEY, LANGCHAIN_ENDPOINT, LANGCHAIN_PROJECT, LANGCHAIN_TRACING_V2

def setup_langsmith():
    """
    Set LangChain environment variables from settings so every
    """
    if not LANGCHAIN_TRACING_V2:
        return                           # tracing off — skip

    os.environ["LANGCHAIN_TRACING_V2"]  = "true"
    os.environ["LANGCHAIN_API_KEY"]     = LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"]     = LANGCHAIN_PROJECT
    os.environ["LANGCHAIN_ENDPOINT"]    = LANGCHAIN_ENDPOINT