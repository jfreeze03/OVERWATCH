"""Shared SQL escaping helpers for OVERWATCH.

This module is the single source of truth for turning Python values into safe
SQL string literals that are embedded into generated DML/DDL. Historically this
helper was copy-pasted into several modules (``query``, ``logging``, ``admin``
and ``company_filter``); those modules now re-export :func:`sql_literal` from
here so existing import paths keep working.
"""
from __future__ import annotations

DEFAULT_MAX_LEN = 8000


def sql_literal(value, max_len: int = DEFAULT_MAX_LEN) -> str:
    """Return a quoted SQL string literal for generated DML/DDL.

    ``None`` maps to the SQL ``NULL`` keyword (unquoted). Any other value is
    stringified, stripped of NUL bytes, truncated to ``max_len`` characters and
    single-quote escaped by doubling embedded quotes. Percent signs and
    underscores are intentionally preserved verbatim because they are only
    special inside ``LIKE`` patterns, not in ordinary string literals.
    """
    if value is None:
        return "NULL"
    text = str(value).replace("\x00", "")[:max_len]
    return "'" + text.replace("'", "''") + "'"
