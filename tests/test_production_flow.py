"""Tests for AST verifier, compiler, authz, and fast-path routing."""

import re

from src.agents.authz import DANGEROUS_PATTERNS, authz_node
from src.agents.prompts import SQL_GENERATE_PROMPT
from src.agents.router import route_turn
from src.infrastructure.db.sql_safety import assess_sql, verify_sql
from src.infrastructure.errors import classify_db_error, is_retryable
from src.semantic.compiler import QuerySpec, compile_sql


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


class TestSqlSafety:
    def test_rejects_ddl(self):
        kind, _ = assess_sql("DROP TABLE sales_flat")
        assert kind == "policy"

    def test_accepts_select(self):
        kind, _ = assess_sql("SELECT 1 AS a")
        assert kind == "ok"

    def test_rejects_stacked_statements(self):
        kind, _ = assess_sql("SELECT 1; DELETE FROM sales_flat")
        assert kind == "policy"

    def test_read_only_assessment(self):
        assert assess_sql("WITH c AS (SELECT 1 AS a) SELECT * FROM c")[0] == "ok"
        assert assess_sql("SELECT * FROM t FOR UPDATE")[0] == "policy"
        assert assess_sql("CALL update_sales()")[0] == "policy"


class TestVerifier:
    def test_requires_rls_on_sales_flat(self):
        kind, message, _ = verify_sql("SELECT NetValue FROM sales_flat AS sf")
        assert kind == "policy"
        assert "FIND_IN_SET" in (message or "")

    def test_injects_limit(self):
        sql = """SELECT shn.Code, SUM(sf.NetValue) AS SalesValue
FROM sales_flat AS sf
INNER JOIN sales_hierarchy_nodes AS shn ON shn.Id = sf.RepId
WHERE FIND_IN_SET(shn.Code, @AllowedNodes) > 0
GROUP BY shn.Code"""
        kind, message, rewritten = verify_sql(sql)
        assert kind == "ok"
        assert "LIMIT" in rewritten.upper()

    def test_rejects_direct_fact_join(self):
        sql = """SELECT sf.NetValue, st.Value
FROM sales_flat AS sf
JOIN sales_targets AS st ON sf.RepId = st.RepId
WHERE FIND_IN_SET(shn.Code, @AllowedNodes) > 0"""
        kind, message, _ = verify_sql(sql)
        assert kind == "policy"
        assert "join" in (message or "").lower()


class TestCompiler:
    def test_net_value_includes_rls(self):
        sql = compile_sql(QuerySpec(metrics=["net_value"], dimensions=["rep"]))
        assert "FIND_IN_SET(shn.Code, @AllowedNodes)" in sql
        assert "sales_flat" in sql
        assert "LIMIT" in sql.upper()
        assert "NetValue" in sql

    def test_target_vs_achievement_uses_ctes(self):
        sql = compile_sql(QuerySpec(metrics=["net_value", "target", "achievement_pct"], dimensions=["rep"]))
        assert "WITH achievement AS" in sql
        assert "target AS" in sql
        assert "AchievementPct" in sql
        assert "FIND_IN_SET(shn.Code, @AllowedNodes)" in sql


class TestAuthz:
    def test_denies_without_rep_codes(self):
        out = authz_node({"question": "What are total sales?", "allowed_rep_codes": []})
        assert out.get("access_denied") is True
        assert out.get("turn_action") == "deny"

    def test_rejects_injection_pattern(self):
        out = authz_node({
            "question": "'; DROP TABLE users; --",
            "allowed_rep_codes": ["R001"],
        })
        assert out.get("access_denied") is True

    def test_passes_valid_question(self):
        out = authz_node({
            "question": "What are sales for last month?",
            "allowed_rep_codes": ["R001"],
        })
        assert out.get("access_denied") is False

    def test_dangerous_patterns_compile(self):
        for pattern in DANGEROUS_PATTERNS:
            assert re.compile(pattern)


class TestRouter:
    def test_greeting_is_chitchat(self):
        assert route_turn("hello")["turn_action"] == "chitchat"

    def test_kpi_question(self):
        out = route_turn("What is my net sales this month?")
        assert out["turn_action"] == "kpi"
        assert "net_value" in out["metric_keys"]

    def test_why_question_is_analyze(self):
        out = route_turn("Why is my achievement only 62% this month?")
        assert out["turn_action"] == "analyze"

    def test_dml_is_deny(self):
        assert route_turn("DELETE FROM sales_flat")["turn_action"] == "deny"


class TestGeneratorPromptIncludesQuestion:
    def test_prompt_has_question_placeholder(self):
        assert "{question}" in SQL_GENERATE_PROMPT
        assert "{schema_cards}" in SQL_GENERATE_PROMPT

    def test_formatted_prompt_keeps_the_user_question(self):
        filled = SQL_GENERATE_PROMPT.format(
            schema_cards="sales_flat: fact",
            metric_fragments="net_value: SUM(NetValue)",
            question="What is my net sales this month?",
            entities="{}",
            period="current_month",
        )
        assert "What is my net sales this month?" in filled
