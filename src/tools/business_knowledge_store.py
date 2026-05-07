import yaml
from pathlib import Path
from typing import List, Dict, Any
from ..config import settings

class BusinessKnowledgeStore:
    def __init__(self, yaml_path: str):
        self.yaml_path = Path(yaml_path) or Path(settings.business_doc_ymal_path)
        self.definitions = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.yaml_path.exists():
            return {}

        with open(self.yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return data.get("definitions", {})

    def reload(self):
        self.definitions = self._load()

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


business_knowledge_store = BusinessKnowledgeStore(
    # yaml_path="data/business_definitions.yaml"
)