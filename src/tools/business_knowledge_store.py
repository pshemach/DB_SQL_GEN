import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from ..config import settings
from .business_knowledge_retriever import business_knowledge_retriever


class BusinessKnowledgeStore:
    def __init__(self, yaml_path: str = None):
        yaml_path = yaml_path or settings.business_doc_yaml_path
        self.yaml_path = Path(yaml_path)
        self.definitions = self._load()
        
        # Initialize vector store retriever
        self.retriever = business_knowledge_retriever

    def _load(self) -> Dict[str, Any]:
        if not self.yaml_path.exists():
            self.yaml_path.parent.mkdir(parents=True, exist_ok=True)
            self._save({"definitions": {}})

        with open(self.yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return data.get("definitions", {})

    def reload(self):
        self.definitions = self._load()
    
    def _save(self, data: Dict[str, Any]):
        with open(self.yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                explicit_end=False,
                explicit_start=False,
                width=120,  # Prevents unnecessary line breaks
                indent=2,   # Consistent indentation
                default_style=None  # Preserve custom representer style
            )
            
    def save_definitions(self):
        self._save({"definitions": self.definitions})
        
    def list_definitions(self) -> Dict[str, Any]:
        return self.definitions
    
    def get_definition(self, key: str) -> Optional[Dict[str, Any]]:
        return self.definitions.get(key)
    
    def upsert_definition(
        self,
        key: str,
        keywords: List[str],
        definition: str
    ):
        clean_key = self.normalize_key(key)
        
        # Update YAML
        self.definitions[clean_key] = {
            "keywords": keywords,
            "definition": definition.strip()
        }

        self.save_definitions()
        self.reload()
        
        # Update vector store
        self.retriever.update_business_definition(
            name=clean_key,
            keywords=keywords,
            definition=definition
        )

        return clean_key
    
    def delete_definition(self, key: str):
        if key in self.definitions:
            del self.definitions[key]
            self.save_definitions()
            self.reload()
            
            # Delete from vector store
            self.retriever.delete_business_definition(name=key)

    def get_all_definitions_text(self) -> str:
        parts = []

        for name, item in self.definitions.items():
            parts.append(
                f"KPI: {name}\n"
                f"Keywords: {item.get('keywords', [])}\n"
                f"Definition:\n{item.get('definition', '')}"
            )

        return "\n\n".join(parts)

    def keyword_search(self, question: str) -> List[Dict[str, Any]]:
        q = question.lower()
        matches = []

        for name, item in self.definitions.items():
            keywords = item.get("keywords", [])

            if any(str(k).lower() in q for k in keywords):
                matches.append({
                    "name": name,
                    "definition": item.get("definition", ""),
                    "keywords": keywords
                })

        return matches

    def add_definition(self, name: str, keywords: List[str], definition: str):
        key = name.lower().replace(" ", "_")

        self.definitions[key] = {
            "keywords": keywords,
            "definition": definition
        }

        with open(self.yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {"definitions": self.definitions},
                f,
                allow_unicode=True,
                sort_keys=False
            )
        
        # Sync to vector store
        self.retriever.add_business_definition(
            name=key,
            keywords=keywords,
            definition=definition
            )
            
    @staticmethod
    def normalize_key(value: str) -> str:
        return (
            value.strip()
            .lower()
            .replace(" ", "_")
            .replace("-", "_")
        )


business_knowledge_store = BusinessKnowledgeStore(
    # yaml_path="data/business_definitions.yaml"
)