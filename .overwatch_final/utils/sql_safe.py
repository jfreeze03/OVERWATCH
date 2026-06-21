"""Small SQL string escaping primitives shared by utility modules."""
from __future__ import annotations


def sql_literal(value, max_len: int = 8000) -> str:
    """Return a quoted SQL string literal for generated DML/DDL."""
    if value is None:
        return "NULL"
    text = str(value).replace("\x00", "")[:max_len]
    return "'" + text.replace("'", "''") + "'"
