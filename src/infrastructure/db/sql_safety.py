"""Read-only SQL policy plus AST checks for RLS, LIMIT, and join safety."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from src.infrastructure.config import settings

_READ_ONLY = (exp.Select, exp.Union, exp.Intersect, exp.Except)

_WRITE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Drop",
    "Create",
    "Alter",
    "Command",
    "Merge",
    "Grant",
    "Revoke",
    "Set",
    "TruncateTable",
    "Execute",
    "Transaction",
    "Commit",
    "Rollback",
    "Copy",
    "Use",
    "DropPartition",
)
_WRITE_TYPES = tuple(getattr(exp, name) for name in _WRITE_NAMES if hasattr(exp, name))

_DIALECTS = ("mysql", "tsql")


def assess_sql(sql: str) -> tuple[str, str | None]:
    """
    Classify SQL before execution.

    Returns ("ok", None), ("policy", message), or ("parse", message).
    Policy failures must not be executed or retried into a write.
    """
    text = (sql or "").strip()
    if not text:
        return "policy", "Access denied. Only SELECT queries are allowed."

    statements, parse_error = _parse(text)
    if parse_error:
        return "parse", parse_error
    if len(statements) != 1:
        return "policy", "Access denied. Only a single SELECT statement is allowed."

    statement = statements[0]
    if not isinstance(statement, _READ_ONLY):
        return "policy", "Access denied. Only SELECT queries are allowed."

    for node in statement.walk():
        if isinstance(node, _WRITE_TYPES) or isinstance(node, exp.Into) or isinstance(node, exp.Lock):
            return "policy", "Access denied. Only SELECT queries are allowed."
        if isinstance(node, exp.Select) and node.args.get("locks"):
            return "policy", "Access denied. Only SELECT queries are allowed."

    return "ok", None


_REP_SCOPED = re.compile(r"\b(sales_flat|sales_targets|planned_routes)\b", re.IGNORECASE)
_FIND_IN_SET = re.compile(r"FIND_IN_SET\s*\(\s*shn\.Code\s*,\s*@AllowedNodes\s*\)", re.IGNORECASE)
_DIRECT_FACT_JOIN = re.compile(
    r"FROM\s+sales_flat[\s\S]{0,500}JOIN\s+sales_targets|FROM\s+sales_targets[\s\S]{0,500}JOIN\s+sales_flat",
    re.IGNORECASE,
)
_LIMIT = re.compile(r"\bLIMIT\b|\bTOP\s+\d+", re.IGNORECASE)


def inject_limit(sql: str, max_rows: int | None = None) -> str:
    cap = max_rows or settings.sql_max_rows
    text = (sql or "").rstrip().rstrip(";")
    if _LIMIT.search(text):
        return text
    return f"{text}\nLIMIT {cap}"


def verify_sql(sql: str) -> tuple[str, str | None, str]:
    """
    Policy + RLS + join-safety check.

    Returns (kind, message, maybe_rewritten_sql).
    kind is ok, policy, or parse.
    """
    kind, message = assess_sql(sql)
    if kind != "ok":
        return kind, message, sql

    rewritten = inject_limit(sql)
    body = rewritten or ""

    if _REP_SCOPED.search(body) and not _FIND_IN_SET.search(body):
        return (
            "policy",
            "Row-level security missing: FIND_IN_SET(shn.Code, @AllowedNodes) is required.",
            rewritten,
        )

    if _DIRECT_FACT_JOIN.search(body) and "WITH" not in body.upper():
        return (
            "policy",
            "Never join raw sales_flat to raw sales_targets. Aggregate each fact in a CTE first.",
            rewritten,
        )

    return "ok", None, rewritten


def _parse(sql: str) -> tuple[list[exp.Expression], str | None]:
    last_error = "Failed to parse SQL"
    for dialect in _DIALECTS:
        try:
            statements = [stmt for stmt in sqlglot.parse(sql, dialect=dialect) if stmt is not None]
            return statements, None
        except Exception as exc:
            last_error = str(exc)
    return [], last_error
