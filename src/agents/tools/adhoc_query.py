from __future__ import annotations

import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool

from src.agents.prompts import SQL_EDIT_PROMPT, SQL_GENERATE_PROMPT, SQL_REPAIR_PROMPT
from src.agents.runtime import runtime_ctx
from src.agents.tools._facts import execute_select, store_result, tool_payload
from src.infrastructure.json import extract_json
from src.infrastructure.llm.llm_provider import anthropic_llm
from src.semantic.few_shot import few_shot_retriever
from src.semantic.layer import kpis, match_kpi_keys, schema_cards_text


def _metric_fragments(question: str) -> str:
    keys = match_kpi_keys(question)
    registry = kpis()
    lines = []
    for key in keys or list(registry)[:4]:
        spec = registry.get(key) or {}
        lines.append(f"{key}: {spec.get('definition')} expr={spec.get('expression')} alias={spec.get('alias')}")
    return "\n".join(lines)


def _parse_sql(raw) -> dict:
    if hasattr(raw, "content"):
        raw = raw.content
    try:
        return extract_json(str(raw))
    except Exception:
        text = str(raw).replace("```sql", "").replace("```", "").strip()
        return {"sql": text, "assumptions": [], "confidence": 0.5}


@tool
def adhoc_query(question: str) -> str:
    """Generate and run SQL for a question that KPI templates cannot answer. Uses retrieve-and-edit when a verified example exists."""
    ctx = runtime_ctx.get()
    cards = schema_cards_text()
    fragments = _metric_fragments(question)
    entities = ctx.get("resolved_entities") or {}
    period = ctx.get("period") or "current_month"
    examples = []
    try:
        examples = few_shot_retriever.retrieve(question, k=1)
    except Exception:
        examples = []

    if examples and examples[0].get("sql"):
        chain = ChatPromptTemplate.from_template(SQL_EDIT_PROMPT) | anthropic_llm()
        parsed = _parse_sql(chain.invoke({
            "question": question,
            "example_sql": examples[0]["sql"],
            "schema_cards": cards,
        }))
    else:
        chain = ChatPromptTemplate.from_template(SQL_GENERATE_PROMPT) | anthropic_llm()
        parsed = _parse_sql(chain.invoke({
            "question": question,
            "schema_cards": cards,
            "metric_fragments": fragments,
            "entities": entities,
            "period": period,
        }))

    sql = (parsed.get("sql") or "").strip()
    rows, error, rewritten, _ = execute_select(sql, ctx.get("allowed_rep_codes") or [])
    if error:
        repair = ChatPromptTemplate.from_template(SQL_REPAIR_PROMPT) | anthropic_llm()
        parsed = _parse_sql(repair.invoke({
            "question": question,
            "sql": rewritten or sql,
            "error": error,
            "schema_cards": cards,
        }))
        sql = (parsed.get("sql") or "").strip()
        rows, error, rewritten, _ = execute_select(sql, ctx.get("allowed_rep_codes") or [])
        if error:
            escalate = ChatPromptTemplate.from_template(SQL_REPAIR_PROMPT) | anthropic_llm(escalate=True)
            parsed = _parse_sql(escalate.invoke({
                "question": question,
                "sql": rewritten or sql,
                "error": error,
                "schema_cards": cards,
            }))
            sql = (parsed.get("sql") or "").strip()
            rows, error, rewritten, _ = execute_select(sql, ctx.get("allowed_rep_codes") or [])
            if error:
                return json.dumps({"error": error, "sql": rewritten})

    result_id = store_result(ctx.get("session_id") or "", question, rewritten, rows, ["adhoc"])
    ctx["last_sql"] = rewritten
    ctx["last_rows"] = rows
    return tool_payload(result_id, rows, {"sql": rewritten, "assumptions": parsed.get("assumptions") or []})
