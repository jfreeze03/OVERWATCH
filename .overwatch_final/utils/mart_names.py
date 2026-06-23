"""Name helpers for optional OVERWATCH mart objects."""

from __future__ import annotations

from config import ETL_AUDIT_DB, ETL_AUDIT_SCHEMA
from .query import safe_identifier


def mart_object_name(table_name: str) -> str:
    """Return a safe fully qualified mart table name."""
    table = safe_identifier(table_name)
    db = safe_identifier(ETL_AUDIT_DB)
    schema = safe_identifier(ETL_AUDIT_SCHEMA)
    return f"{db}.{schema}.{table}"


__all__ = ["mart_object_name"]
