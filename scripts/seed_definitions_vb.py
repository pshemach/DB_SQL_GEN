import sys 
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import business_knowledge_retriever

business_knowledge_retriever.seed_business_definitions()