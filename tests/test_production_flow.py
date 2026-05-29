"""Tests for production graph utilities (no live LLM/DB required)."""

import re

import pytest

from src.utils.error_taxonomy import classify_db_error, is_retryable
from src.agents.graph.sql_pipeline_nodes import static_validator_node, FORBIDDEN_SQL
from src.graph.ingress_nodes import authz_guardrails_node, DANGEROUS_PATTERNS


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
        assert out.get("pre_exec_approved") is True or "error" not in out


class TestAuthzGuardrails:
    def test_denies_without_rep_codes(self):
        out = authz_guardrails_node({"question": "What are total sales?", "allowed_rep_codes": []})
        assert out.get("access_denied") is True
        assert out.get("turn_action") == "deny"

    def test_rejects_injection_pattern(self):
        out = authz_guardrails_node({
            "question": "'; DROP TABLE users; --",
            "allowed_rep_codes": ["R001"],
        })
        assert out.get("access_denied") is True

    def test_passes_valid_question(self):
        out = authz_guardrails_node({
            "question": "What are sales for last month?",
            "allowed_rep_codes": ["R001"],
        })
        assert out.get("access_denied") is False


class TestGuardrailPatterns:
    def test_dangerous_patterns_compile(self):
        for p in DANGEROUS_PATTERNS:
            assert re.compile(p)

    def test_forbidden_sql_matches_delete(self):
        assert FORBIDDEN_SQL.search("DELETE FROM t")
