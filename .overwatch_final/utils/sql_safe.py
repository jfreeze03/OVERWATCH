"""Shared SQL escaping helpers for OVERWATCH.

This module is the single source of truth for turning Python values into
SQL string literals. Historically this helper was copy/pasted into several
``utils`` modules (``query``, ``admin``, ``logging``, ``company_filter``);
those modules now re-export :func:`sql_literal` from here so every caller
shares one tested implementation.

The module deliberately has no third-party or intra-package dependencies so it
can be imported from anywhere without risking circular imports.
"""
from __future__ import annotations


def sql_literal(value, max_len: int = 8000) -> str:
    """Return a quoted SQL string literal for generated DML/DDL.

    ``None`` renders as the SQL keyword ``NULL`` (unquoted). Any other value is
    coerced to ``str``, stripped of NUL bytes, truncated to ``max_len``
    characters, and single-quoted with embedded single quotes doubled per the
    SQL standard escaping rules.
    """
    if value is None:
        return "NULL"
    text = str(value).replace("\x00", "")[:max_len]
    return "'" + text.replace("'", "''") + "'"
