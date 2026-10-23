"""Load the SFA semantic layer (entities, KPIs, schema cards)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.infrastructure.config import settings


@lru_cache(maxsize=1)
def load_layer() -> dict[str, Any]:
    path = Path(settings.semantic_layer_path)
    if not path.exists():
        return {"kpis": {}, "dimensions": {}, "schema_cards": {}, "time_templates": {}, "entities": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data


def reload_layer() -> dict[str, Any]:
    load_layer.cache_clear()
    return load_layer()


def kpis() -> dict[str, Any]:
    return load_layer().get("kpis") or {}


def schema_cards() -> dict[str, str]:
    return load_layer().get("schema_cards") or {}


def schema_cards_text() -> str:
    cards = schema_cards()
    return "\n".join(f"{name}: {text}" for name, text in cards.items())


def match_kpi_keys(question: str) -> list[str]:
    q = (question or "").lower()
    matched: list[str] = []
    for key, spec in kpis().items():
        names = [key.replace("_", " ")] + list(spec.get("keywords") or [])
        if any(name.lower() in q for name in names):
            matched.append(key)
    if not matched and any(word in q for word in ("sales", "achievement", "target")):
        matched.append("net_value")
    return matched


def period_from_question(question: str) -> str:
    q = (question or "").lower()
    if "last month" in q or "previous month" in q:
        return "last_month"
    return "current_month"
