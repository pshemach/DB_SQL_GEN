import sys 
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.chat_service.knowledge_retriever import BusinessKnowledgeRetriever

BusinessKnowledgeRetriever().seed_business_definitions()