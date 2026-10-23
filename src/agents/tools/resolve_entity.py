from __future__ import annotations

from langchain_core.tools import tool
from sqlalchemy import text

from src.agents.runtime import runtime_ctx
from src.infrastructure.db.mysql_client import db_manager


@tool
def resolve_entity(kind: str, name: str) -> str:
    """Map a rep, customer, product, brand, or route name to codes. kind is rep|customer|product|brand|route."""
    name = (name or "").strip()
    if not name:
        return '{"error": "empty name"}'
    allowed = runtime_ctx.get().get("allowed_rep_codes") or []
    mapping = {
        "rep": ("SELECT Code AS code, Name AS name FROM sales_hierarchy_nodes WHERE Name LIKE :q OR Code LIKE :q LIMIT 8",),
        "customer": ("SELECT DISTINCT CustomerCode AS code, CustomerName AS name FROM sales_flat WHERE CustomerName LIKE :q LIMIT 8",),
        "product": ("SELECT DISTINCT ProductCode AS code, ProductName AS name FROM sales_flat WHERE ProductName LIKE :q LIMIT 8",),
        "brand": ("SELECT DISTINCT Brand AS code, Brand AS name FROM sales_flat WHERE Brand LIKE :q LIMIT 8",),
        "route": ("SELECT DISTINCT Route AS code, Route AS name FROM sales_flat WHERE Route LIKE :q LIMIT 8",),
    }
    sql = (mapping.get(kind) or mapping["rep"])[0]
    with db_manager.engine.connect() as conn:
        rows = conn.execute(text(sql), {"q": f"%{name}%"}).mappings().all()
    candidates = [dict(r) for r in rows]
    if kind == "rep" and allowed:
        candidates = [c for c in candidates if c.get("code") in allowed] or candidates
    if len(candidates) == 1:
        return f'{{"resolved": true, "kind": "{kind}", "code": "{candidates[0]["code"]}", "name": "{candidates[0]["name"]}"}}'
    if not candidates:
        return f'{{"resolved": false, "kind": "{kind}", "candidates": []}}'
    return str({"resolved": False, "kind": kind, "candidates": candidates}).replace("'", '"')
