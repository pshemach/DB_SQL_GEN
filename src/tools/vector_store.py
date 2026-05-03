"""
Vector store for dynamic few-shot example retrieval.
"""

from typing import List, Dict
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from loguru import logger
from ..config import settings
import os

class FewShotRetriever:
    """
    Manages a vector store of SQL examples for dynamic few-shot learning.
    """
    def __init__(self):
        self.enabled = settings.enable_dynamic_few_shot