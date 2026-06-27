"""Offline-safe mart loaders for OVERWATCH summary tables."""

from __future__ import annotations

import pandas as pd

from .mart_contracts import MartResult
from .mart_names import mart_object_name
from .query import run_query, sql_literal

__all__ = [
    "load_mart_table",
    "load_latest_control_room_mart",
]


def load_mart_table(
    table_name: str,
    sql: str,
    source_label: str | None = None,
) -> MartResult:
    """Run a mart query and return a fallback-friendly result object."""
    source = source_label or mart_object_name(table_name)
    try:
        df = run_query(
            sql,
            ttl_key=f"mart_{str(table_name).lower()}",
            tier="historical",
            section="Mart",
        )
        if df.empty:
            return MartResult(data=df, available=False, source=source, message="No summary rows returned.")
        return MartResult(data=df, available=True, source=source)
    except Exception as exc:
        return MartResult(data=pd.DataFrame(), available=False, source=source, message=str(exc))


def load_latest_control_room_mart(company: str = "ALFA", max_age_hours: int = 6) -> MartResult:
    """Load the latest DBA Control Room mart row for the active company."""
    table = mart_object_name("MART_DBA_CONTROL_ROOM")
    company = str(company or "ALFA")
    company_filter = ""
    if company.upper() != "ALL":
        company_filter = f"AND COMPANY = {sql_literal(company, 100)}"
    sql = f"""
        WITH latest AS (
            SELECT
                   SNAPSHOT_TS,
                   COMPANY,
                   HEALTH_SCORE,
                   FAILED_QUERIES_24H,
                   FAILED_TASKS_24H,
                   QUEUED_MS_24H,
                   CREDITS_24H,
                   COST_24H_USD,
                   CORTEX_COST_7D_USD,
                   SECURITY_EVENTS_24H,
                   OBJECT_CHANGES_24H,
                   TOP_RISK,
                   LOAD_TS,
                   ROW_NUMBER() OVER (
                       PARTITION BY COMPANY
                       ORDER BY SNAPSHOT_TS DESC
                   ) AS RN
            FROM {table}
            WHERE SNAPSHOT_TS >= DATEADD('HOUR', -{int(max_age_hours)}, CURRENT_TIMESTAMP())
              {company_filter}
        )
        SELECT
            SNAPSHOT_TS,
            COMPANY,
            HEALTH_SCORE,
            FAILED_QUERIES_24H,
            FAILED_TASKS_24H,
            QUEUED_MS_24H,
            CREDITS_24H,
            COST_24H_USD,
            CORTEX_COST_7D_USD,
            SECURITY_EVENTS_24H,
            OBJECT_CHANGES_24H,
            TOP_RISK,
            LOAD_TS
        FROM latest
        WHERE RN = 1
        ORDER BY COMPANY
    """
    return load_mart_table("MART_DBA_CONTROL_ROOM", sql, source_label=table)
