from __future__ import annotations

import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from loguru import logger

from src.agents.prompts import SQL_GENERATE_PROMPT, SQL_PLAN_PROMPT, SQL_REPAIR_PROMPT, SQL_TABLE_PROMPT
from src.agents.runtime import runtime_ctx
from src.agents.tools._facts import execute_select, store_result, tool_payload
from src.infrastructure.json import extract_json
from src.infrastructure.llm.llm_provider import anthropic_llm
from src.semantic.knowledge_store import business_knowledge_store
from src.semantic.layer import parse_selected_tables, schema_cards


def _business_definitions(question: str) -> str:
    try:
        return business_knowledge_store.relevant_definitions_text(question)
    except Exception:
        return "No matching business definition."


def _text(raw) -> str:
    if hasattr(raw, "content"):
        raw = raw.content
    if isinstance(raw, list):
        parts = []
        for block in raw:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(getattr(block, "text", str(block)))
        raw = "".join(parts)
    return str(raw).strip()


def _parse_sql(raw) -> dict:
    text = _text(raw)
    try:
        return extract_json(text)
    except Exception:
        cleaned = text.replace("```sql", "").replace("```", "").strip()
        return {"sql": cleaned, "assumptions": [], "confidence": 0.5}


def _catalog(cards: dict[str, str]) -> str:
    lines = []
    for name, text in cards.items():
        lines.append(f"{name}: {text}")
    return "\n".join(lines)


def _cards_for(cards: dict[str, str], tables: list[str]) -> str:
    return "\n".join(f"{name}: {cards[name]}" for name in tables if name in cards)


def _invoke(prompt: str, **values) -> str:
    chain = ChatPromptTemplate.from_template(prompt) | anthropic_llm()
    return _text(chain.invoke(values))


@tool
def adhoc_query(question: str) -> str:
    """Plan the question, select the tables, then generate and run SQL."""
    ctx = runtime_ctx.get()
    cards = schema_cards()
    definitions = _business_definitions(question)
    memory = ctx.get("memory_context") or "none"
    table_names = ", ".join(cards) or "sales_flat, sales_hierarchy_nodes"

    plan = _invoke(
        SQL_PLAN_PROMPT,
        question=question,
        business_definitions=definitions,
        memory_context=memory,
        table_names=table_names,
    ) or question
    logger.info("SQL plan:\n{}", plan)

    chosen = parse_selected_tables(
        _invoke(SQL_TABLE_PROMPT, question=question, plan=plan, catalog=_catalog(cards)),
        set(cards),
    )
    if not chosen:
        chosen = parse_selected_tables("sales_flat, sales_hierarchy_nodes", set(cards))
    logger.info("Selected tables: {}", ", ".join(chosen))
    selected_cards = _cards_for(cards, chosen)
    ctx["sql_plan"] = plan

    parsed = _parse_sql(_invoke(
        SQL_GENERATE_PROMPT,
        question=question,
        plan=plan,
        business_definitions=definitions,
        schema_cards=selected_cards,
    ))
    sql = (parsed.get("sql") or "").strip()
    rows, error, rewritten, _ = execute_select(sql, ctx.get("allowed_rep_codes") or [])
    if error:
        repair = ChatPromptTemplate.from_template(SQL_REPAIR_PROMPT) | anthropic_llm()
        parsed = _parse_sql(repair.invoke({
            "question": question,
            "plan": plan,
            "business_definitions": definitions,
            "sql": rewritten or sql,
            "error": error,
            "schema_cards": selected_cards,
        }))
        sql = (parsed.get("sql") or "").strip()
        rows, error, rewritten, _ = execute_select(sql, ctx.get("allowed_rep_codes") or [])
        if error:
            escalate = ChatPromptTemplate.from_template(SQL_REPAIR_PROMPT) | anthropic_llm(escalate=True)
            parsed = _parse_sql(escalate.invoke({
                "question": question,
                "plan": plan,
                "business_definitions": definitions,
                "sql": rewritten or sql,
                "error": error,
                "schema_cards": selected_cards,
            }))
            sql = (parsed.get("sql") or "").strip()
            rows, error, rewritten, _ = execute_select(sql, ctx.get("allowed_rep_codes") or [])
            if error:
                return json.dumps({"error": error, "sql": rewritten})

    result_id = store_result(ctx.get("session_id") or "", question, rewritten, rows, chosen)
    ctx["last_sql"] = rewritten
    ctx["last_rows"] = rows
    return tool_payload(result_id, rows, {"sql": rewritten, "assumptions": parsed.get("assumptions") or []})
