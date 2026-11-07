"""Turn a dashboard requirement into widget specs."""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.agents.prompts.dashboard_agent_prompts import (
    build_dashboard_planner_prompt,
    dashboard_messages,
)
from src.infrastructure.llm import get_router_llm
from src.infrastructure.utils import extract_json
from src.services.chat_service.knowledge_retriever import BusinessKnowledgeRetriever
from src.services.chat_service.knowledge_store import BusinessKnowledgeStore

business_knowledge_retriever = BusinessKnowledgeRetriever()
business_knowledge_store = BusinessKnowledgeStore()
from src.services.dashboard_service.filters import normalize_dimensions
from src.services.dashboard_service.layout import normalize_plan_widgets

FALLBACK_TITLE = "Sales dashboard"
SLICER_QUESTION_MARK = "dashboard filter applied later"
FALLBACK_WIDGETS = [
    {
        "title": "Net sales",
        "type": "kpi",
        "chart_type": "kpi",
        "question": "What is my total net sales for the current month?",
    },
    {
        "title": "Daily net sales",
        "type": "chart",
        "chart_type": "line",
        "question": "Show daily net sales for the current month for my reps.",
    },
    {
        "title": "Top products",
        "type": "chart",
        "chart_type": "bar",
        "question": "Top 10 products by net sales this month for my reps.",
    },
    ]
    
class DashboardPlaner:
    """Planner agent for a dashboard brief."""
    def __init__(self, llm: Any = None) -> None:
        self.llm = llm

    def plan(
        self,
        requirement: str,
        existing_widgets: list[dict[str, Any]] | None = None,
        mode: str = "compose",
    ) -> dict[str, Any]:
        model = self.llm or get_router_llm()
        knowledge = self.retrieve_knowledge(requirement)
        existing_text = self._format_existing(existing_widgets)
        try:
            system_prompt, user_prompt = build_dashboard_planner_prompt(
                requirement=requirement,
                retrieved_knowledge=knowledge,
                existing_widgets=existing_text,
                mode=mode,
            )
            response = model.invoke(dashboard_messages(system_prompt, user_prompt))
            parsed = extract_json((response.content or "").strip())
        except Exception as exc:
            logger.error(f"Dashboard planner failed: {exc}")
            parsed = {}

        title = str(parsed.get("title") or "").strip() or self.FALLBACK_TITLE
        widgets = normalize_plan_widgets(parsed.get("widgets"))
        if not widgets and mode == "compose":
            widgets = normalize_plan_widgets(self.FALLBACK_WIDGETS)
        if mode == "add":
            widgets = widgets[:2]
        dimensions = normalize_dimensions(parsed.get("filter_dimensions"))
        return {
            "title": title,
            "widgets": self.apply_slicer_to_questions(widgets, dimensions),
            "filter_dimensions": dimensions,
        }

    @classmethod
    def apply_slicer_to_questions(
        cls,
        widgets: list[dict[str, Any]],
        dimensions: list[str],
    ) -> list[dict[str, Any]]:
        names = normalize_dimensions(dimensions)
        if not names:
            return widgets
        listed = ", ".join(names)
        note = (
            f" Do not group, split, or rank by {listed}; "
            "that is a dashboard filter applied later, not a chart breakdown."
        )
        updated = []
        for widget in widgets:
            item = dict(widget)
            question = str(item.get("question") or "").rstrip()
            if question and cls.SLICER_QUESTION_MARK not in question.lower():
                item["question"] = f"{question}{note}"
            updated.append(item)
        return updated

    def retrieve_knowledge(self, question: str) -> str:
        keyword_matches = business_knowledge_store.keyword_search(question)
        keyword_knowledge = "\n".join(
            f"KPI: {match['name']}\n{match['definition']}" for match in keyword_matches
        )
        vector_knowledge = ""
        if business_knowledge_retriever:
            try:
                vector_knowledge = business_knowledge_retriever.retrieve_business_definitions_block(
                    question
                )
            except Exception:
                vector_knowledge = ""
        return "\n\n".join(part for part in [keyword_knowledge, vector_knowledge] if part)

    @staticmethod
    def _format_existing(existing_widgets: list[dict[str, Any]] | None) -> str:
        if not existing_widgets:
            return ""
        lines = []
        for widget in existing_widgets:
            title = widget.get("title") or "Untitled"
            question = widget.get("question") or ""
            lines.append(f"- {title}: {question}")
        return "\n".join(lines)
