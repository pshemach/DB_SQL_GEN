import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from ..config import settings
from .business_knowledge_retriever import business_knowledge_retriever

class LiteralString(str):
    pass


def literal_str_representer(dumper, data):
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str",
        data,
        style="|"
    )


class CustomYamlDumper(yaml.SafeDumper):
    pass


CustomYamlDumper.add_representer(LiteralString, literal_str_representer)

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
        data = {
            "definitions": self._format_definitions_for_yaml()
        }
        with open(self.yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                Dumper=CustomYamlDumper,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=1000
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
        key = self.normalize_key(name)

        self.definitions[key] = {
            "keywords": keywords,
            "definition": definition.strip()
        }

        self.save_definitions()
        self.reload()

        self.retriever.add_business_definition(
            name=key,
            keywords=keywords,
            definition=definition
        )

        return key
        
    def _format_definitions_for_yaml(self):
        formatted = {}

        for key, value in self.definitions.items():
            definition = value.get("definition", "")

            formatted[key] = {
                "keywords": value.get("keywords", []),
                "definition": LiteralString(definition.strip())
            }

        return formatted
            
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