"""Mart-first Change Intelligence helpers for Phase 2D.

Executive Landing reads only the compact summary mart. Change events and
possible correlations are explicit-load only so first paint does not probe live
Snowflake metadata or broad account history.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from .mart import mart_object_name
from .query import run_query, sql_literal


CHANGE_TYPES = (
    "WAREHOUSE_CHANGE",
    "ROLE_CHANGE",
    "GRANT_CHANGE",
    "TASK_CHANGE",
    "PROCEDURE_CHANGE",
    "NETWORK_POLICY_CHANGE",
    "INTEGRATION_CHANGE",
    "OBJECT_CHANGE",
    "SECURITY_SENSITIVE_CHANGE",
)
CHANGE_RISK_LABELS = ("Critical", "High", "Medium", "Low")
CHANGE_CONFIDENCE_LABELS = ("exact", "allocated", "estimated", "fallback")
CHANGE_CORRELATION_LABELS = ("possible correlation",)


def _scope_clause(company: str, environment: str, *, table_alias: str = "") -> str:
    prefix = f"{table_alias}." if table_alias else ""
    company_value = str(company or "ALL")
    environment_value = str(environment or "ALL")
    company_sql = sql_literal(company_value, 100)
    env_sql = sql_literal(environment_value, 100)
    return f"""
      AND ({company_sql} = 'ALL' OR COALESCE({prefix}COMPANY, 'ALL') IN ('ALL', {company_sql}))
      AND ({env_sql} = 'ALL' OR COALESCE({prefix}ENVIRONMENT, 'ALL') IN ('ALL', {env_sql}))
    """


def _scope_rank_expr(company: str, environment: str) -> str:
    company_sql = sql_literal(str(company or "ALL"), 100)
    env_sql = sql_literal(str(environment or "ALL"), 100)
    return f"""
      IFF({company_sql} = 'ALL', IFF(COALESCE(COMPANY, 'ALL') = 'ALL', 0, 1), IFF(COALESCE(COMPANY, 'ALL') = {company_sql}, 0, 1)) +
      IFF({env_sql} = 'ALL', IFF(COALESCE(ENVIRONMENT, 'ALL') = 'ALL', 0, 1), IFF(COALESCE(ENVIRONMENT, 'ALL') = {env_sql}, 0, 1))
    """


def _list_clause(column: str, values: Sequence[str] | None, allowed: Sequence[str]) -> str:
    if not values:
        return ""
    normalized = [str(value or "").strip() for value in values]
    selected = [value for value in normalized if value in allowed]
    if not selected:
        return "AND 1 = 0"
    literals = ", ".join(sql_literal(value, 100) for value in selected)
    return f"AND {column} IN ({literals})"


def load_change_intelligence_summary(
    company: str,
    environment: str,
    *,
    days: int = 35,
) -> pd.DataFrame:
    """Load compact first-paint-safe Change Intelligence summary rows."""
    table = mart_object_name("MART_CHANGE_INTELLIGENCE_SUMMARY")
    window_days = max(1, int(days or 35))
    scope = _scope_clause(company, environment)
    scope_rank = _scope_rank_expr(company, environment)
    return run_query(
        f"""
        WITH scoped AS (
          SELECT
            SNAPSHOT_TS,
            COMPANY,
            ENVIRONMENT,
            CHANGE_TYPE,
            CHANGE_CATEGORY,
            OBJECT_TYPE,
            CHANGE_COUNT,
            HIGH_RISK_COUNT,
            OWNER_GAP_COUNT,
            RELATED_ALERT_COUNT,
            CORRELATION_CANDIDATE_COUNT,
            LATEST_CHANGE_TS,
            TOP_OBJECT_NAME,
            TOP_CHANGED_BY,
            RISK_LEVEL,
            BUSINESS_IMPACT,
            OWNER_ROUTE,
            CONFIDENCE,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
          QUALIFY ROW_NUMBER() OVER (
            PARTITION BY COMPANY, ENVIRONMENT, CHANGE_TYPE
            ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
          ) = 1
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          CHANGE_TYPE,
          CHANGE_CATEGORY,
          OBJECT_TYPE,
          CHANGE_COUNT,
          HIGH_RISK_COUNT,
          OWNER_GAP_COUNT,
          RELATED_ALERT_COUNT,
          CORRELATION_CANDIDATE_COUNT,
          LATEST_CHANGE_TS,
          TOP_OBJECT_NAME,
          TOP_CHANGED_BY,
          RISK_LEVEL,
          BUSINESS_IMPACT,
          OWNER_ROUTE,
          CONFIDENCE,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY CHANGE_TYPE
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY
          CASE RISK_LEVEL WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
          CHANGE_COUNT DESC,
          CHANGE_TYPE
        """,
        ttl_key=f"change_intelligence_summary_{company}_{environment}_{window_days}",
        tier="historical",
        section="Executive Landing",
        max_rows=40,
    )


def load_change_event_detail(
    company: str,
    environment: str,
    *,
    change_types: Sequence[str] | None = None,
    risk_levels: Sequence[str] | None = None,
    days: int = 180,
) -> pd.DataFrame:
    """Load gated normalized change events."""
    table = mart_object_name("OVERWATCH_CHANGE_EVENT")
    window_days = max(1, int(days or 180))
    scope = _scope_clause(company, environment)
    scope_rank = _scope_rank_expr(company, environment)
    type_filter = _list_clause("CHANGE_TYPE", change_types, CHANGE_TYPES)
    risk_filter = _list_clause("RISK_LEVEL", risk_levels, CHANGE_RISK_LABELS)
    return run_query(
        f"""
        WITH scoped AS (
          SELECT
            SNAPSHOT_TS,
            COMPANY,
            ENVIRONMENT,
            CHANGE_ID,
            CHANGE_TYPE,
            CHANGE_CATEGORY,
            OBJECT_TYPE,
            OBJECT_NAME,
            CHANGED_BY,
            CHANGE_TS,
            BEFORE_VALUE,
            AFTER_VALUE,
            RISK_LEVEL,
            BUSINESS_IMPACT,
            OWNER_ROUTE,
            OWNER_GAP,
            RELATED_ALERT_COUNT,
            RELATED_INCIDENTS,
            CONFIDENCE,
            SOURCE_OBJECTS,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
            {type_filter}
            {risk_filter}
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          CHANGE_ID,
          CHANGE_TYPE,
          CHANGE_CATEGORY,
          OBJECT_TYPE,
          OBJECT_NAME,
          CHANGED_BY,
          CHANGE_TS,
          BEFORE_VALUE,
          AFTER_VALUE,
          RISK_LEVEL,
          BUSINESS_IMPACT,
          OWNER_ROUTE,
          OWNER_GAP,
          RELATED_ALERT_COUNT,
          RELATED_INCIDENTS,
          CONFIDENCE,
          SOURCE_OBJECTS,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY CHANGE_ID
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY CHANGE_TS DESC, CHANGE_TYPE
        """,
        ttl_key=f"change_event_detail_{company}_{environment}_{'_'.join(change_types or ())}_{'_'.join(risk_levels or ())}_{window_days}",
        tier="historical",
        section="Change Intelligence",
        max_rows=500,
    )


def load_change_correlation_detail(
    company: str,
    environment: str,
    *,
    change_types: Sequence[str] | None = None,
    correlation_types: Sequence[str] | None = None,
    days: int = 180,
) -> pd.DataFrame:
    """Load gated possible correlation rows."""
    table = mart_object_name("OVERWATCH_CHANGE_CORRELATION")
    window_days = max(1, int(days or 180))
    scope = _scope_clause(company, environment)
    scope_rank = _scope_rank_expr(company, environment)
    type_filter = _list_clause("CHANGE_TYPE", change_types, CHANGE_TYPES)
    correlation_filter = _list_clause("CORRELATION_TYPE", correlation_types, ("Cost", "Security", "Workload", "Alert"))
    return run_query(
        f"""
        WITH scoped AS (
          SELECT
            SNAPSHOT_TS,
            COMPANY,
            ENVIRONMENT,
            CHANGE_ID,
            CHANGE_TYPE,
            OBJECT_TYPE,
            OBJECT_NAME,
            CHANGE_TS,
            CHANGED_BY,
            CORRELATION_TYPE,
            RELATED_SIGNAL,
            RELATED_ENTITY,
            RELATED_TS,
            RELATED_ALERT_COUNT,
            CORRELATION_WINDOW_HOURS,
            CORRELATION_STRENGTH,
            CORRELATION_LABEL,
            RISK_LEVEL,
            BUSINESS_IMPACT,
            OWNER_ROUTE,
            CONFIDENCE,
            EVIDENCE,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
            {type_filter}
            {correlation_filter}
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          CHANGE_ID,
          CHANGE_TYPE,
          OBJECT_TYPE,
          OBJECT_NAME,
          CHANGE_TS,
          CHANGED_BY,
          CORRELATION_TYPE,
          RELATED_SIGNAL,
          RELATED_ENTITY,
          RELATED_TS,
          RELATED_ALERT_COUNT,
          CORRELATION_WINDOW_HOURS,
          CORRELATION_STRENGTH,
          CORRELATION_LABEL,
          RISK_LEVEL,
          BUSINESS_IMPACT,
          OWNER_ROUTE,
          CONFIDENCE,
          EVIDENCE,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY CHANGE_ID, CORRELATION_TYPE, RELATED_SIGNAL, RELATED_ENTITY, RELATED_TS
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY RELATED_TS DESC, CHANGE_TS DESC
        """,
        ttl_key=f"change_correlation_detail_{company}_{environment}_{'_'.join(change_types or ())}_{'_'.join(correlation_types or ())}_{window_days}",
        tier="historical",
        section="Change Intelligence",
        max_rows=500,
    )
