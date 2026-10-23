from __future__ import annotations

import json

import duckdb
import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool

from src.agents.prompts import LOCAL_SQL_PROMPT, TABLE_ANALYST_PROMPT
from src.agents.runtime import runtime_ctx
from src.agents.tools._facts import compact_facts, store_result
from src.infrastructure.db.sql_safety import assess_sql
from src.infrastructure.json import extract_json
from src.infrastructure.llm.llm_provider import groq_llm, openai_llm
from src.memory.result_store import result_cache


@tool
def transform_results(question: str, mode: str = "local_transform") -> str:
    """Sort, filter, rank, or explain the previous result. mode is local_transform or semantic_analysis."""
    ctx = runtime_ctx.get()
    cached = result_cache.get_cached_result(ctx.get("session_id") or "")
    if not cached:
        return json.dumps({"error": "No previous result to transform.", "needs_new_sql": True})
    if mode == "semantic_analysis":
        df = pd.DataFrame(cached.result_data)
        table = df.head(40).to_markdown(index=False)
        llm = openai_llm()
        chain = ChatPromptTemplate.from_template(TABLE_ANALYST_PROMPT) | llm
        resp = chain.invoke({
            "follow_up_question": question,
            "source_question": cached.original_question,
            "total_rows": len(df),
            "columns": ", ".join(df.columns),
            "table_markdown": table,
        })
        text = resp.content if hasattr(resp, "content") else str(resp)
        ctx["last_rows"] = cached.result_data
        ctx["semantic_answer"] = text
        return json.dumps({"result_id": cached.query_id, "analysis": text, "row_count": len(cached.result_data)})

    df = pd.DataFrame(cached.result_data)
    llm = groq_llm()
    chain = ChatPromptTemplate.from_template(LOCAL_SQL_PROMPT) | llm
    resp = chain.invoke({
        "follow_up_question": question,
        "columns_and_types": {c: str(t) for c, t in df.dtypes.items()},
        "sample_rows": df.head(5).to_markdown(index=False),
    })
    plan = extract_json(resp.content if hasattr(resp, "content") else str(resp))
    if plan.get("needs_live_db") or not plan.get("sql"):
        return json.dumps({"needs_new_sql": True, "reason": plan.get("explanation")})
    local_sql = plan["sql"]
    kind, message = assess_sql(local_sql)
    if kind != "ok":
        return json.dumps({"needs_new_sql": True, "reason": message})
    last_result = df  # noqa: F841  DuckDB scans this name
    result_df = duckdb.query(local_sql).to_df()
    rows = result_df.to_dict(orient="records")
    result_id = store_result(ctx.get("session_id") or "", question, local_sql, rows, ["last_result"])
    ctx["last_rows"] = rows
    ctx["last_sql"] = cached.sql_query
    payload = compact_facts(rows)
    payload.update({"result_id": result_id, "local_sql": local_sql, "reused_previous_result": True})
    return json.dumps(payload, default=str)
