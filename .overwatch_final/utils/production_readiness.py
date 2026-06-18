"""Mart-first production readiness helpers for Phase 2A.

The Production Readiness Dashboard must stay first-paint safe. Summary helpers
read only compact OVERWATCH marts. Detail helpers are intended for explicit DBA
Load buttons and still read OVERWATCH readiness tables, not live account usage.
"""

from __future__ import annotations

import pandas as pd

from .mart import mart_object_name
from .query import run_query, sql_literal


READINESS_STATUS_LABELS = ("Ready", "Review", "Blocked", "Unknown")


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


def _domain_clause(domain: str, *, table_alias: str = "") -> str:
    value = str(domain or "").strip()
    if not value:
        return ""
    prefix = f"{table_alias}." if table_alias else ""
    return f"AND COALESCE({prefix}CHECK_DOMAIN, '') = {sql_literal(value, 100)}"


def load_production_readiness_summary(
    company: str,
    environment: str,
    *,
    days: int = 35,
) -> pd.DataFrame:
    """Load compact first-paint-safe production readiness summary rows."""
    table = mart_object_name("MART_PRODUCTION_READINESS_SUMMARY")
    window_days = max(1, int(days or 35))
    scope = _scope_clause(company, environment)
    return run_query(
        f"""
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          DEPLOYMENT_VERSION,
          LAST_DEPLOYMENT_TS,
          LAST_VALIDATION_TS,
          VALIDATION_STATUS,
          MISSING_PRIVILEGES,
          FAILED_MART_REFRESHES,
          MISSING_SUMMARY_MARTS,
          STALE_SOURCE_COUNT,
          CONFIG_DRIFT_COUNT,
          ENVIRONMENT_READINESS,
          READINESS_SCORE,
          TOP_RISK,
          CONFIDENCE,
          NEXT_ACTION
        FROM {table}
        WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
          {scope}
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY COMPANY, ENVIRONMENT
          ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY
          CASE VALIDATION_STATUS WHEN 'Blocked' THEN 0 WHEN 'Review' THEN 1 WHEN 'Unknown' THEN 2 ELSE 3 END,
          COMPANY
        """,
        ttl_key=f"production_readiness_summary_{company}_{environment}_{window_days}",
        tier="historical",
        section="Executive Landing",
        max_rows=20,
    )


def load_production_validation_detail(
    company: str,
    environment: str,
    *,
    domain: str = "",
    days: int = 35,
) -> pd.DataFrame:
    """Load explicit production validation rows for DBA Control Room diagnostics."""
    table = mart_object_name("OVERWATCH_PRODUCTION_VALIDATION_STATUS")
    window_days = max(1, int(days or 35))
    scope = _scope_clause(company, environment)
    domain_filter = _domain_clause(domain)
    return run_query(
        f"""
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          CHECK_DOMAIN,
          CHECK_KEY,
          CHECK_NAME,
          VALIDATION_STATUS,
          RISK_LEVEL,
          VALUE,
          VALUE_DETAIL,
          SOURCE_OBJECT,
          FRESHNESS_MINUTES,
          OWNER_ROUTE AS ROUTE,
          RUNBOOK_STEP,
          CONFIDENCE
        FROM {table}
        WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
          {scope}
          {domain_filter}
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY COMPANY, ENVIRONMENT, CHECK_DOMAIN, CHECK_KEY
          ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY
          CASE VALIDATION_STATUS WHEN 'Blocked' THEN 0 WHEN 'Review' THEN 1 WHEN 'Unknown' THEN 2 ELSE 3 END,
          CASE RISK_LEVEL WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
          CHECK_DOMAIN,
          CHECK_NAME
        """,
        ttl_key=f"production_validation_detail_{company}_{environment}_{domain}_{window_days}",
        tier="historical",
        section="DBA Control Room",
        max_rows=500,
    )
