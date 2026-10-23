from __future__ import annotations

import json

from langchain_core.tools import tool

from src.agents.runtime import runtime_ctx


@tool
def ask_user(question: str, options: list[str] | None = None) -> str:
    """Ask the user a clarification. Ends the analyst loop. Provide option labels when names are ambiguous."""
    ctx = runtime_ctx.get()
    options = options or []
    if options:
        numbered = "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options))
        text = f"{question}\n{numbered}"
    else:
        text = question
    ctx["waiting_for_user"] = True
    ctx["question_to_user"] = text
    return json.dumps({"waiting_for_user": True, "question_to_user": text})
