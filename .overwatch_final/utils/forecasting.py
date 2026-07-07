"""Mart-first forecasting helpers for Phase 2C.

Executive Landing reads only the compact forecasting summary mart. Cost,
workload, and DBA detail panels call the history loader only after an explicit
Load button, keeping forecast evidence away from first paint.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from .mart import mart_object_name
from .query import run_query, sql_literal


FORECAST_KEYS = (
    "EOM_SPEND",
    "EOQ_SPEND",
    "CONTRACT_BURN",
    "CREDIT_ANOMALY",
    "STORAGE_GROWTH",
    "WAREHOUSE_PRESSURE",
    "SLA_RISK",
)
FORECAST_CONFIDENCE_LABELS = ("High", "Medium", "Low")
FORECAST_TREND_LABELS = ("Up", "Down", "Flat", "Unknown")


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


def _forecast_key_clause(forecast_keys: Sequence[str] | None) -> str:
    if not forecast_keys:
        return ""
    normalized = [str(key or "").strip().upper() for key in forecast_keys]
    allowed = [key for key in normalized if key in FORECAST_KEYS]
    if not allowed:
        return "AND 1 = 0"
    values = ", ".join(sql_literal(key, 100) for key in allowed)
    return f"AND FORECAST_KEY IN ({values})"


def _domain_clause(domain: str) -> str:
    value = str(domain or "").strip()
    if not value:
        return ""
    return f"AND FORECAST_DOMAIN = {sql_literal(value, 100)}"


def load_executive_forecast_summary(
    company: str,
    environment: str,
    *,
    days: int = 35,
) -> pd.DataFrame:
    """Load compact first-paint-safe forecast rows."""
    table = mart_object_name("MART_EXECUTIVE_FORECAST_SUMMARY")
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
            FORECAST_KEY,
            FORECAST_NAME,
            DISPLAY_ORDER,
            FORECAST_DOMAIN,
            FORECAST_VALUE,
            CURRENT_ACTUAL,
            PRIOR_PERIOD_VALUE,
            TREND_DIRECTION,
            CONFIDENCE,
            METHODOLOGY,
            MAIN_DRIVER,
            RECOMMENDED_ACTION,
            WORKFLOW_ROUTE,
            WORKFLOW_GAP,
            VALUE_UNIT,
            VALUE_AT_RISK_USD,
            SOURCE_OBJECTS,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
          QUALIFY ROW_NUMBER() OVER (
            PARTITION BY COMPANY, ENVIRONMENT, FORECAST_KEY
            ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
          ) = 1
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          FORECAST_KEY,
          FORECAST_NAME,
          DISPLAY_ORDER,
          FORECAST_DOMAIN,
          FORECAST_VALUE,
          CURRENT_ACTUAL,
          PRIOR_PERIOD_VALUE,
          TREND_DIRECTION,
          CONFIDENCE,
          METHODOLOGY,
          MAIN_DRIVER,
          RECOMMENDED_ACTION,
          WORKFLOW_ROUTE,
          WORKFLOW_GAP,
          VALUE_UNIT,
          VALUE_AT_RISK_USD,
          SOURCE_OBJECTS,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY FORECAST_KEY
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY DISPLAY_ORDER
        """,
        ttl_key=f"executive_forecast_summary_{company}_{environment}_{window_days}",
        tier="historical",
        section="Executive Landing",
        max_rows=20,
    )


def load_forecast_detail(
    company: str,
    environment: str,
    *,
    forecast_keys: Sequence[str] | None = None,
    domain: str = "",
    days: int = 180,
) -> pd.DataFrame:
    """Load explicit forecast history rows for gated section drilldowns."""
    table = mart_object_name("OVERWATCH_FORECAST_HISTORY")
    window_days = max(1, int(days or 180))
    scope = _scope_clause(company, environment)
    scope_rank = _scope_rank_expr(company, environment)
    key_filter = _forecast_key_clause(forecast_keys)
    domain_filter = _domain_clause(domain)
    return run_query(
        f"""
        WITH scoped AS (
          SELECT
            SNAPSHOT_TS,
            COMPANY,
            ENVIRONMENT,
            FORECAST_KEY,
            FORECAST_NAME,
            FORECAST_DOMAIN,
            FORECAST_VALUE,
            CURRENT_ACTUAL,
            PRIOR_PERIOD_VALUE,
            TREND_DIRECTION,
            CONFIDENCE,
            METHODOLOGY,
            MAIN_DRIVER,
            RECOMMENDED_ACTION,
            WORKFLOW_ROUTE,
            WORKFLOW_GAP,
            VALUE_UNIT,
            VALUE_AT_RISK_USD,
            SOURCE_OBJECTS,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
            {key_filter}
            {domain_filter}
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          FORECAST_KEY,
          FORECAST_NAME,
          FORECAST_DOMAIN,
          FORECAST_VALUE,
          CURRENT_ACTUAL,
          PRIOR_PERIOD_VALUE,
          TREND_DIRECTION,
          CONFIDENCE,
          METHODOLOGY,
          MAIN_DRIVER,
          RECOMMENDED_ACTION,
          WORKFLOW_ROUTE,
          WORKFLOW_GAP,
          VALUE_UNIT,
          VALUE_AT_RISK_USD,
          SOURCE_OBJECTS,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY SNAPSHOT_TS, FORECAST_KEY
          ORDER BY SCOPE_RANK ASC, LOAD_TS DESC
        ) = 1
        ORDER BY SNAPSHOT_TS DESC, FORECAST_KEY
        """,
        ttl_key=f"forecast_detail_{company}_{environment}_{domain}_{'_'.join(forecast_keys or ())}_{window_days}",
        tier="historical",
        section="Forecasting",
        max_rows=500,
    )
