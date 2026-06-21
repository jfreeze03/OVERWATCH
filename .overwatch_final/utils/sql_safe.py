"""Shared SQL escaping helpers."""

from __future__ import annotations


def sql_literal(value, max_len: int = 8000) -> str:
    """Return a Snowflake SQL string literal or NULL for generated SQL."""
    if value is None:
        return "NULL"
    text = str(value).replace("\x00", "")[:max_len]
    return "'" + text.replace("'", "''") + "'"
