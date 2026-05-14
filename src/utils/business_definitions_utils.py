import re
import yaml
from pathlib import Path
from typing import Dict, List, Tuple
from ..config import settings

_definitions: Dict = {}          # raw loaded data
_keyword_index: List[Tuple] = [] # [(compiled_pattern, def_name, definition_text)]

def _load():
    """Load YAML and build keyword index. Called once at import time."""
    
    global _definitions, _keyword_index
    
    _YAML_PATH = Path(settings.business_doc_yaml_path)
 
    if not _YAML_PATH.exists():
        raise FileNotFoundError(
            f"business_definitions.yaml not found at {_YAML_PATH}\n"
            f"Create it alongside definition_loader.py"
        )
 
    data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    _definitions = data.get("definitions", {})
    _keyword_index = []
 
    for def_name, entry in _definitions.items():
        keywords   = entry.get("keywords", [])
        definition = entry.get("definition", "").strip()
        if not keywords or not definition:
            continue
        # Build one regex per definition: word/phrase boundary match
        # Handles multi-word phrases like "net sales", " pc " correctly
        patterns = [re.escape(str(kw).strip()) for kw in keywords]
        pattern  = re.compile(
            r'(?:^|[\s,./])(?:' + '|'.join(patterns) + r')(?:$|[\s,./!?])',
            re.IGNORECASE
        )
        _keyword_index.append((pattern, def_name, definition))
        
def reload_definitions():
    """Force reload from disk — call after editing the YAML without restarting."""
    global _definitions, _keyword_index
    _definitions    = {}
    _keyword_index  = []
    _load()
    return f"Reloaded {len(_keyword_index)} definitions"


def get_relevant_definitions(question: str) -> Tuple[str, List[str]]:
    """
    Scan the question for keyword matches and return the matching
    definition block as a formatted string, plus a list of matched names.
 
    Parameters
    ----------
    question : str
        The user's natural language question.
 
    Returns
    -------
    (definition_block, matched_names)
        definition_block : str  — formatted text ready to inject into prompt.
                                  Empty string if no definitions matched.
        matched_names    : list — names of matched definitions (for logging).
    """
    if not _keyword_index:
        _load()
 
    # Pad question so boundary patterns match at start/end
    padded  = f" {question} "
    matched = []
 
    for pattern, def_name, definition in _keyword_index:
        if pattern.search(padded):
            matched.append((def_name, definition))
 
    if not matched:
        return "", []
 
    lines = []
    for def_name, definition in matched:
        lines.append(definition.rstrip())
        lines.append("")
 
    return "\n".join(lines).strip(), [name for name, _ in matched]
 
 
def list_all_definitions() -> str:
    """Return all definitions as a formatted string (for debugging)."""
    if not _keyword_index:
        _load()
    lines = []
    for _, def_name, definition in _keyword_index:
        lines.append(f"[{def_name}]")
        lines.append(definition.strip())
        lines.append("")
    return "\n".join(lines)