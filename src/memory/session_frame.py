"""Compact session frame: last metric, entities, period, and SQL — not raw chat."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SessionFrame:
    last_question: str = ""
    last_metrics: list[str] = field(default_factory=list)
    last_entities: dict[str, Any] = field(default_factory=dict)
    last_period: str = "current_month"
    last_sql: str = ""
    last_result_id: str = ""
    pending_clarification: str = ""
    advice_given: list[str] = field(default_factory=list)

    def as_prompt(self) -> str:
        if not self.last_question and not self.pending_clarification:
            return ""
        parts = [
            f"Last question: {self.last_question}" if self.last_question else "",
            f"Metrics: {', '.join(self.last_metrics)}" if self.last_metrics else "",
            f"Entities: {self.last_entities}" if self.last_entities else "",
            f"Period: {self.last_period}",
            f"Pending clarification: {self.pending_clarification}" if self.pending_clarification else "",
        ]
        return "\n".join(p for p in parts if p)


_FRAMES: dict[str, SessionFrame] = {}


def load_frame(session_id: str | None) -> SessionFrame:
    if not session_id:
        return SessionFrame()
    return _FRAMES.get(session_id) or SessionFrame()


def save_frame(session_id: str | None, frame: SessionFrame) -> None:
    if session_id:
        _FRAMES[session_id] = frame


def frame_from_state(state: dict[str, Any]) -> SessionFrame:
    existing = load_frame(state.get("session_id"))
    return SessionFrame(
        last_question=state.get("question") or existing.last_question,
        last_metrics=existing.last_metrics,
        last_entities=existing.last_entities,
        last_period=existing.last_period,
        last_sql=state.get("sql_query") or existing.last_sql,
        last_result_id=existing.last_result_id,
        pending_clarification=state.get("question_to_user") or "",
        advice_given=existing.advice_given,
    )


def frame_dict(frame: SessionFrame) -> dict[str, Any]:
    return asdict(frame)
