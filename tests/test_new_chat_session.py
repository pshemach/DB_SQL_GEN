"""New Chat must not reuse the previous conversation session."""

import importlib.util
from pathlib import Path

_SESSION_PATH = Path(__file__).resolve().parents[1] / "src" / "api" / "session.py"
_SPEC = importlib.util.spec_from_file_location("conversation_session", _SESSION_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
resolve_start_session_id = _MODULE.resolve_start_session_id


class TestResolveStartSessionId:
    def test_new_chat_without_id_does_not_reuse_current(self):
        session_id = resolve_start_session_id(
            None,
            current_session_id="old-session",
            new_conversation=True,
        )
        assert session_id
        assert session_id != "old-session"

    def test_new_chat_rejects_stale_current_session(self):
        session_id = resolve_start_session_id(
            "old-session",
            current_session_id="old-session",
            new_conversation=True,
        )
        assert session_id != "old-session"

    def test_new_chat_accepts_client_generated_id(self):
        session_id = resolve_start_session_id(
            "brand-new-session",
            current_session_id="old-session",
            new_conversation=True,
        )
        assert session_id == "brand-new-session"

    def test_start_with_question_uses_requested_session(self):
        session_id = resolve_start_session_id(
            "login-session",
            current_session_id="login-session",
            new_conversation=False,
        )
        assert session_id == "login-session"

    def test_start_without_session_does_not_fall_back_to_current(self):
        session_id = resolve_start_session_id(
            None,
            current_session_id="old-session",
            new_conversation=False,
        )
        assert session_id
        assert session_id != "old-session"
