"""Load the SFA semantic layer (entities, KPIs, schema cards)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.infrastructure.config import settings
from src.infrastructure.json import extract_json


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


_RLS_TABLES = {"sales_flat", "sales_targets", "planned_routes", "routes", "route_customer_assignments"}


def parse_selected_tables(raw, known: set[str]) -> list[str]:
    """Keep only catalog tables, then add the join bridges those tables require."""
    text = getattr(raw, "content", raw)
    if isinstance(text, list):
        text = " ".join(str(part) for part in text)
    text = str(text or "")
    names: list[str] = []
    try:
        payload = extract_json(text)
        values = payload.get("tables") if isinstance(payload, dict) else None
        if isinstance(values, list):
            names = [str(item) for item in values]
    except Exception:
        names = []
    if not names:
        plain = text.replace("```json", "").replace("```", "")
        names = [part.strip(" `\"'[]{}") for part in plain.replace("\n", ",").split(",")]

    known_by_lower = {name.lower(): name for name in known}
    selected: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        canonical = known_by_lower.get(name.strip().lower())
        if canonical and canonical not in seen:
            seen.add(canonical)
            selected.append(canonical)

    for name in names:
        add(name)
    if seen & _RLS_TABLES:
        add("sales_hierarchy_nodes")
    if "planned_routes" in seen or "route_customer_assignments" in seen:
        add("routes")
    if "route_customer_assignments" in seen:
        add("external_parties")
    if "sales_targets" in seen:
        add("sales_hierarchy_nodes")
    return selected


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
