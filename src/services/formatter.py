"""Facts-first narrative and optional charts."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from src.agents.prompts import FORMATTER_PROMPT
from src.infrastructure.config import settings
from src.infrastructure.json import extract_json
from src.infrastructure.llm.llm_provider import openai_llm
from src.services.chart_request import detect_requested_chart_type


def format_result(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("waiting_for_user") and state.get("question_to_user"):
        msg = state["question_to_user"]
        return {"final_answer": msg, "result_summary": msg, "visualizations": []}
    if state.get("turn_action") == "chitchat" and state.get("final_answer"):
        return {"result_summary": state["final_answer"], "visualizations": []}
    if state.get("access_denied"):
        msg = state.get("access_denied_reason") or "Access denied."
        return {"final_answer": msg, "result_summary": msg, "visualizations": [], "error": msg}

    rows = state.get("query_result") or []
    if not rows:
        msg = state.get("final_answer") or state.get("error") or "No records found for the requested query."
        return {"final_answer": msg, "result_summary": msg, "table_title": "Query Result", "visualizations": []}

    df = pd.DataFrame(rows)
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    facts = {
        "row_count": int(len(df)),
        "columns": list(df.columns),
        "metrics": {},
    }
    for col in numeric[:6]:
        series = df[col].dropna()
        if series.empty:
            continue
        facts["metrics"][col] = {
            "sum": float(series.sum()),
            "avg": float(series.mean()),
            "min": float(series.min()),
            "max": float(series.max()),
        }
    requested = detect_requested_chart_type(state.get("question") or "")
    try:
        chain = ChatPromptTemplate.from_template(FORMATTER_PROMPT) | openai_llm()
        parsed = extract_json(chain.invoke({
            "question": state.get("enriched_question") or state.get("question") or "",
            "facts": json.dumps(facts, default=str),
            "dataset_profile": json.dumps({"rows": len(df), "columns": list(df.columns)}),
            "requested_chart_type": requested or "none",
            "currency_symbol": settings.currency_symbol or "Rs",
        }).content)
        summary = (parsed.get("summary") or "").strip() or _fallback_summary(df, numeric)
        return {
            "result_summary": summary,
            "final_answer": summary,
            "table_title": parsed.get("table_title") or "Query results",
            "visualizations": parsed.get("visualizations") or [],
            "requested_chart_type": requested,
        }
    except Exception as e:
        logger.warning(f"Formatter LLM failed: {e}")
        summary = _fallback_summary(df, numeric)
        return {
            "result_summary": summary,
            "final_answer": summary,
            "table_title": "Query results",
            "visualizations": [],
            "requested_chart_type": requested,
        }


def _fallback_summary(df: pd.DataFrame, numeric: list[str]) -> str:
    if df.empty:
        return "No rows matched the request."
    if not numeric:
        return f"Found {len(df)} matching row(s)."
    col = numeric[0]
    total = df[col].sum()
    return f"Found {len(df)} rows. Total {col} is {total:,.2f}."
