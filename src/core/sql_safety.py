"""Allow only a single read-only SELECT before any SQL is sent to the database."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

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


def _parse(sql: str) -> tuple[list[exp.Expression], str | None]:
    last_error = "Failed to parse SQL"
    for dialect in _DIALECTS:
        try:
            statements = [stmt for stmt in sqlglot.parse(sql, dialect=dialect) if stmt is not None]
            return statements, None
        except Exception as exc:
            last_error = str(exc)
    return [], last_error
