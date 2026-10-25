"""Tests for production graph utilities (no live LLM/DB required)."""

import pytest

from src.infrastructure.db.sql_safety import classify_db_error, is_retryable
from src.agents.orchestrator import FORBIDDEN_SQL, missing_rep_codes, static_validator_node
from src.infrastructure.db.sql_safety import assess_sql

class TestErrorTaxonomy:
    def test_syntax_error_retryable(self):
        assert classify_db_error("syntax error near SELECT") == "syntax_error"
        assert is_retryable("syntax_error", True)

    def test_timeout_not_retryable(self):
        assert classify_db_error("query timeout exceeded") == "timeout"
        assert not is_retryable("timeout", True)

    def test_permission_not_retryable(self):
        assert not is_retryable("permission", True)
        assert not is_retryable("access_denied", True)

class TestStaticValidator:
    def test_rejects_ddl(self):
        out = static_validator_node({
            "sql_query": "DROP TABLE sales_flat",
            "question": "test",
        })
        assert out.get("error_type") == "validation"
        assert out.get("should_retry") is False

    def test_accepts_select(self):
        out = static_validator_node({
            "sql_query": "SELECT TOP 10 * FROM sales_flat",
            "question": "test",
        })
        assert out.get("error") is None
        assert out.get("should_retry") is False

    def test_rejects_replace_and_stacked_statements(self):
        replace_out = static_validator_node({
            "sql_query": "REPLACE INTO sales_flat VALUES (1)",
            "question": "test",
        })
        assert replace_out.get("error_type") == "validation"
        assert replace_out.get("should_retry") is False

        stacked_out = static_validator_node({
            "sql_query": "SELECT 1; DELETE FROM sales_flat",
            "question": "test",
        })
        assert stacked_out.get("error_type") == "validation"
        assert stacked_out.get("should_retry") is False

    def test_read_only_assessment(self):
        assert assess_sql("WITH c AS (SELECT 1 AS a) SELECT * FROM c")[0] == "ok"
        assert assess_sql("SELECT * FROM t FOR UPDATE")[0] == "policy"
        assert assess_sql("CALL update_sales()")[0] == "policy"

class TestRepCodeGate:
    def test_stops_without_rep_codes(self):
        out = missing_rep_codes([], {"question": "What are total sales?"})
        assert out["access_denied"] is True
        assert out["turn_action"] == "deny"
        assert out["error_type"] == "access_denied"

    def test_allows_when_codes_exist(self):
        assert missing_rep_codes(["R001"], {"question": "What are sales?"}) is None

class TestGuardrailPatterns:
    def test_forbidden_sql_matches_delete(self):
        assert FORBIDDEN_SQL.search("DELETE FROM t")
