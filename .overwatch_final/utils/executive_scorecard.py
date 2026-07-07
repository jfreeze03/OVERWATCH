"""Mart-first Executive Scorecard helpers for Phase 2B.

Executive Landing must stay first-paint safe, so the summary loader reads only
the compact scorecard mart. Driver history is intended for explicit Load
buttons in section surfaces and still reads only OVERWATCH mart/history tables.
"""

from __future__ import annotations

import pandas as pd

from .mart import mart_object_name
from .query import run_query, sql_literal


SCORE_KEYS = (
    "SNOWFLAKE_HEALTH",
    "COST_EFFICIENCY",
    "SECURITY",
    "OPERATIONAL_RISK",
    "DATA_TRUST",
    "PRODUCTION_READINESS",
)
SCORE_STATUS_LABELS = ("Green", "Yellow", "Red", "Unknown")


def score_status_for_value(
    score: object,
    *,
    yellow_below: float = 85.0,
    red_below: float = 70.0,
) -> str:
    """Return the leadership score status label for a numeric score."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "Unknown"
    if value < red_below:
        return "Red"
    if value < yellow_below:
        return "Yellow"
    return "Green"


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


def _score_key_clause(score_key: str) -> str:
    key = str(score_key or "").strip().upper()
    if not key:
        return ""
    if key not in SCORE_KEYS:
        return "AND 1 = 0"
    return f"AND SCORE_KEY = {sql_literal(key, 100)}"


def load_executive_scorecard_summary(
    company: str,
    environment: str,
    *,
    days: int = 35,
) -> pd.DataFrame:
    """Load compact first-paint-safe leadership scorecard rows."""
    table = mart_object_name("MART_EXECUTIVE_SCORECARD_SUMMARY")
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
            SCORE_KEY,
            SCORE_NAME,
            DISPLAY_ORDER,
            CURRENT_SCORE,
            STATUS,
            TREND,
            TREND_DELTA,
            RISK_LEVEL,
            TOP_DRIVER,
            RECOMMENDED_ACTION,
            WORKFLOW_ROUTE,
            WORKFLOW_GAP,
            VALUE_AT_RISK_USD,
            CONFIDENCE,
            SOURCE_OBJECTS,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
          QUALIFY ROW_NUMBER() OVER (
            PARTITION BY COMPANY, ENVIRONMENT, SCORE_KEY
            ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
          ) = 1
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          SCORE_KEY,
          SCORE_NAME,
          DISPLAY_ORDER,
          CURRENT_SCORE,
          STATUS,
          TREND,
          TREND_DELTA,
          RISK_LEVEL,
          TOP_DRIVER,
          RECOMMENDED_ACTION,
          WORKFLOW_ROUTE,
          WORKFLOW_GAP,
          VALUE_AT_RISK_USD,
          CONFIDENCE,
          SOURCE_OBJECTS,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY SCORE_KEY
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY DISPLAY_ORDER
        """,
        ttl_key=f"executive_scorecard_summary_{company}_{environment}_{window_days}",
        tier="historical",
        section="Executive Landing",
        max_rows=20,
    )


def load_executive_scorecard_detail(
    company: str,
    environment: str,
    *,
    score_key: str = "",
    days: int = 180,
) -> pd.DataFrame:
    """Load explicit score driver history rows for section drilldowns."""
    table = mart_object_name("OVERWATCH_EXECUTIVE_SCORECARD_HISTORY")
    window_days = max(1, int(days or 180))
    scope = _scope_clause(company, environment)
    scope_rank = _scope_rank_expr(company, environment)
    score_filter = _score_key_clause(score_key)
    return run_query(
        f"""
        WITH scoped AS (
          SELECT
            SNAPSHOT_TS,
            COMPANY,
            ENVIRONMENT,
            SCORE_KEY,
            SCORE_NAME,
            CURRENT_SCORE,
            STATUS,
            TREND,
            TREND_DELTA,
            RISK_LEVEL,
            TOP_DRIVER,
            RECOMMENDED_ACTION,
            WORKFLOW_ROUTE,
            WORKFLOW_GAP,
            VALUE_AT_RISK_USD,
            CONFIDENCE,
            SOURCE_OBJECTS,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
            {score_filter}
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          SCORE_KEY,
          SCORE_NAME,
          CURRENT_SCORE,
          STATUS,
          TREND,
          TREND_DELTA,
          RISK_LEVEL,
          TOP_DRIVER,
          RECOMMENDED_ACTION,
          WORKFLOW_ROUTE,
          WORKFLOW_GAP,
          VALUE_AT_RISK_USD,
          CONFIDENCE,
          SOURCE_OBJECTS,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY SNAPSHOT_TS, SCORE_KEY
          ORDER BY SCOPE_RANK ASC, LOAD_TS DESC
        ) = 1
        ORDER BY SNAPSHOT_TS DESC, SCORE_KEY
        """,
        ttl_key=f"executive_scorecard_detail_{company}_{environment}_{score_key}_{window_days}",
        tier="historical",
        section="Executive Scorecard",
        max_rows=500,
    )
