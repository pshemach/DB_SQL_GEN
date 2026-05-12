from pathlib import Path
import yaml
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from langchain_chroma import Chroma
import os
from typing import List, Dict
from ..config import settings

class BusinessKnowledgeRetriever:
    """
    Manages a vector store of business definitions.
    """
    def __init__(self, yaml_path: str = None):
        
        self.yaml_path = yaml_path or settings.business_doc_ymal_path
        self.business_info_dict = self._load_yaml()
        
        # Initialize embeddings with HuggingFace model (local)
        self.embeddings = HuggingFaceEmbeddings(
            model_name=settings.embedding_model
        )
        
        # Initialize vector store
        persist_directory = settings.vector_store_path
        os.makedirs(persist_directory, exist_ok=True)
        
        self.vectorstore = Chroma(
            collection_name=settings.business_definition_collection_name,
            embedding_function=self.embeddings,
            persist_directory=persist_directory
        )
        
        
    def _load_yaml(self):
        data = yaml.safe_load(
            Path(self.yaml_path).read_text(encoding='utf-8')
            )
        return data.get("definitions", {})
    
    def seed_business_definitions(self):
        
        docs = []
        for name, entry in self.business_info_dict.items():
            docs.append(
                Document(
                    page_content=entry["definition"].strip(),
                    metadata={
                        "name": name,
                        "keywords": entry.get("keywords", [])
                    }
                )
            )
            
        self.vectorstore.add_documents(docs)
        
    def get_relevant_definition_docs(self, question: str, k: int = 3) -> List[Dict]:
        
        docs = self.vectorstore.similarity_search(question, k=k)
        
        # results = self.vectorstore.similarity_search_with_score(question, k=k)
        
        # threshold = 0.7   # tune this
        # docs = []
        
        # for doc , score in results:
        #     print(score)
        #     if score > threshold:
        #         docs.append(doc)
            
        return docs
    
    def retrieve_business_definitions_block(self, question: str, k: int = 3) -> str:
        
        docs = self.get_relevant_definition_docs(question, k)
        
        lines = []
        for doc in docs:
            name = doc.metadata.get("name", "---").replace("_", " ")
            lines.append(f"{name}:")
            lines.append(doc.page_content.strip())
            lines.append("")
            
        return "\n".join(lines).strip()
    
    def retrieve_business_keywords(self, question: str, k: int = 3) -> str:
        
        docs = self.get_relevant_definition_docs(question=question, k=k)
        
        keywords_lines = []
        for doc in docs:
            # name = doc.metadata.get("name", "---").replace("_", " ")
            keywords = doc.metadata.get("keywords", ["-"])
            keywords = " ".join(keywords).strip()
            # keywords_lines.append(f"{name}:")
            keywords_lines.append(keywords)
            
        return "\n".join(keywords_lines).strip()
    
business_knowledge_retriever = BusinessKnowledgeRetriever()