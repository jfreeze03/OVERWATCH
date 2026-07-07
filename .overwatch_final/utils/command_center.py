"""Mart-first Command Center helpers for Phase 2F.

Executive Landing reads only the compact summary mart. Investigation findings,
evidence, and recommendations are explicit-load only.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from .mart import mart_object_name
from .query import run_query, sql_literal


COMMAND_CENTER_INVESTIGATION_TYPES = (
    "ALL",
    "Cost Spike",
    "Warehouse Slow",
    "Recent Change",
    "Failure / SLA",
    "Security Risk",
    "Executive Risk",
)
COMMAND_CENTER_RISK_LABELS = ("Critical", "High", "Medium", "Low")
COMMAND_CENTER_CONFIDENCE_LABELS = ("exact", "allocated", "estimated", "fallback")
COMMAND_CENTER_CAUSALITY_LABELS = ("root-cause candidate", "likely driver", "possible correlation")


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
    selected = [str(value or "").strip() for value in values if str(value or "").strip() in allowed]
    if not selected:
        return "AND 1 = 0"
    literals = ", ".join(sql_literal(value, 100) for value in selected)
    return f"AND {column} IN ({literals})"


def load_command_center_summary(
    company: str,
    environment: str,
    *,
    days: int = 35,
) -> pd.DataFrame:
    """Load compact first-paint-safe Command Center summary rows."""
    table = mart_object_name("MART_COMMAND_CENTER_SUMMARY")
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
            INVESTIGATION_TYPE,
            QUESTION_TEXT,
            FINDING_COUNT,
            HIGH_RISK_COUNT,
            WORKFLOW_GAP_COUNT,
            RELATED_CHANGE_COUNT,
            RELATED_ALERT_COUNT,
            RELATED_SCORECARD_COUNT,
            RELATED_FORECAST_COUNT,
            REVIEW_PLAN_COUNT,
            EXPECTED_VALUE_USD,
            TOP_ROOT_CAUSE_CANDIDATE,
            TOP_EVIDENCE_SUMMARY,
            TOP_RECOMMENDED_ACTION,
            CONFIDENCE,
            RISK_LEVEL,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          INVESTIGATION_TYPE,
          QUESTION_TEXT,
          FINDING_COUNT,
          HIGH_RISK_COUNT,
          WORKFLOW_GAP_COUNT,
          RELATED_CHANGE_COUNT,
          RELATED_ALERT_COUNT,
          RELATED_SCORECARD_COUNT,
          RELATED_FORECAST_COUNT,
          REVIEW_PLAN_COUNT,
          EXPECTED_VALUE_USD,
          TOP_ROOT_CAUSE_CANDIDATE,
          TOP_EVIDENCE_SUMMARY,
          TOP_RECOMMENDED_ACTION,
          CONFIDENCE,
          RISK_LEVEL,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY INVESTIGATION_TYPE
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY
          CASE INVESTIGATION_TYPE
            WHEN 'Cost Spike' THEN 1 WHEN 'Warehouse Slow' THEN 2
            WHEN 'Recent Change' THEN 3 WHEN 'Failure / SLA' THEN 4
            WHEN 'Security Risk' THEN 5 WHEN 'Executive Risk' THEN 6 ELSE 7
          END
        """,
        ttl_key=f"command_center_summary_{company}_{environment}_{window_days}",
        tier="historical",
        section="Executive Landing",
        max_rows=20,
    )


def load_command_center_finding_detail(
    company: str,
    environment: str,
    *,
    investigation_types: Sequence[str] | None = None,
    days: int = 180,
) -> pd.DataFrame:
    """Load gated Command Center finding rows."""
    table = mart_object_name("OVERWATCH_COMMAND_CENTER_FINDING")
    window_days = max(1, int(days or 180))
    scope = _scope_clause(company, environment)
    scope_rank = _scope_rank_expr(company, environment)
    type_filter = _list_clause("INVESTIGATION_TYPE", investigation_types, COMMAND_CENTER_INVESTIGATION_TYPES)
    return run_query(
        f"""
        WITH scoped AS (
          SELECT
            SNAPSHOT_TS,
            COMPANY,
            ENVIRONMENT,
            FINDING_ID,
            QUESTION_KEY,
            INVESTIGATION_TYPE,
            QUESTION_TEXT,
            ROOT_CAUSE_CANDIDATE,
            EVIDENCE_SUMMARY,
            CONFIDENCE,
            BUSINESS_IMPACT,
            TECHNICAL_IMPACT,
            WORKFLOW_ROUTE,
            WORKFLOW_GAP,
            RELATED_CHANGES,
            RELATED_ALERTS,
            RELATED_SCORECARD_DRIVERS,
            RELATED_FORECASTS,
            RECOMMENDED_ACTION,
            RISK_LEVEL,
            EXECUTION_PLAN_REF,
            EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD,
            VERIFICATION_PATH,
            CAUSALITY_LABEL,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
            {type_filter}
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          FINDING_ID,
          QUESTION_KEY,
          INVESTIGATION_TYPE,
          QUESTION_TEXT,
          ROOT_CAUSE_CANDIDATE,
          EVIDENCE_SUMMARY,
          CONFIDENCE,
          BUSINESS_IMPACT,
          TECHNICAL_IMPACT,
          WORKFLOW_ROUTE,
          WORKFLOW_GAP,
          RELATED_CHANGES,
          RELATED_ALERTS,
          RELATED_SCORECARD_DRIVERS,
          RELATED_FORECASTS,
          RECOMMENDED_ACTION,
          RISK_LEVEL,
          EXECUTION_PLAN_REF,
          EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD,
          VERIFICATION_PATH,
          CAUSALITY_LABEL,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY FINDING_ID
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY
          CASE RISK_LEVEL WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
          EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD DESC,
          LAST_REFRESHED_TS DESC
        """,
        ttl_key=f"command_center_findings_{company}_{environment}_{'_'.join(investigation_types or ())}_{window_days}",
        tier="historical",
        section="Command Center",
        max_rows=500,
    )


def load_command_center_evidence_detail(
    company: str,
    environment: str,
    *,
    investigation_types: Sequence[str] | None = None,
    days: int = 180,
) -> pd.DataFrame:
    """Load gated Command Center evidence rows."""
    evidence = mart_object_name("OVERWATCH_COMMAND_CENTER_EVIDENCE")
    findings = mart_object_name("OVERWATCH_COMMAND_CENTER_FINDING")
    window_days = max(1, int(days or 180))
    scope = _scope_clause(company, environment, table_alias="e")
    type_filter = _list_clause("f.INVESTIGATION_TYPE", investigation_types, COMMAND_CENTER_INVESTIGATION_TYPES)
    return run_query(
        f"""
        SELECT
          e.SNAPSHOT_TS,
          e.COMPANY,
          e.ENVIRONMENT,
          f.INVESTIGATION_TYPE,
          e.FINDING_ID,
          e.EVIDENCE_ID,
          e.EVIDENCE_TYPE,
          e.SOURCE_OBJECT,
          e.RELATED_OBJECT,
          e.EVIDENCE_SUMMARY,
          e.CONFIDENCE,
          e.CAUSALITY_LABEL,
          e.LAST_REFRESHED_TS
        FROM {evidence} e
        JOIN {findings} f
          ON f.FINDING_ID = e.FINDING_ID
         AND f.SNAPSHOT_TS = e.SNAPSHOT_TS
        WHERE e.SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
          {scope}
          {type_filter}
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY e.EVIDENCE_ID
          ORDER BY e.SNAPSHOT_TS DESC, e.LOAD_TS DESC
        ) = 1
        ORDER BY e.LAST_REFRESHED_TS DESC
        """,
        ttl_key=f"command_center_evidence_{company}_{environment}_{'_'.join(investigation_types or ())}_{window_days}",
        tier="historical",
        section="Command Center",
        max_rows=500,
    )


def load_command_center_recommendation_detail(
    company: str,
    environment: str,
    *,
    investigation_types: Sequence[str] | None = None,
    days: int = 180,
) -> pd.DataFrame:
    """Load gated Command Center recommendation rows. This never executes actions."""
    recommendations = mart_object_name("OVERWATCH_COMMAND_CENTER_RECOMMENDATION")
    findings = mart_object_name("OVERWATCH_COMMAND_CENTER_FINDING")
    window_days = max(1, int(days or 180))
    scope = _scope_clause(company, environment, table_alias="r")
    type_filter = _list_clause("f.INVESTIGATION_TYPE", investigation_types, COMMAND_CENTER_INVESTIGATION_TYPES)
    return run_query(
        f"""
        SELECT
          r.SNAPSHOT_TS,
          r.COMPANY,
          r.ENVIRONMENT,
          f.INVESTIGATION_TYPE,
          r.FINDING_ID,
          r.RECOMMENDATION_ID,
          r.RECOMMENDED_ACTION,
          r.RISK_LEVEL,
          r.WORKFLOW_ROUTE,
          r.EXECUTION_PLAN_REF,
          r.REVIEW_REQUIRED,
          r.EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD,
          r.VERIFICATION_PATH,
          r.SAFETY_NOTE,
          r.LAST_REFRESHED_TS
        FROM {recommendations} r
        JOIN {findings} f
          ON f.FINDING_ID = r.FINDING_ID
         AND f.SNAPSHOT_TS = r.SNAPSHOT_TS
        WHERE r.SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
          {scope}
          {type_filter}
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY r.RECOMMENDATION_ID
          ORDER BY r.SNAPSHOT_TS DESC, r.LOAD_TS DESC
        ) = 1
        ORDER BY
          CASE r.RISK_LEVEL WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
          r.EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD DESC,
          r.LAST_REFRESHED_TS DESC
        """,
        ttl_key=f"command_center_recommendations_{company}_{environment}_{'_'.join(investigation_types or ())}_{window_days}",
        tier="historical",
        section="Command Center",
        max_rows=500,
    )
