"""Mart-first Closed Loop Operations helpers for Phase 2E.

Executive Landing reads only the compact summary mart. Workflow, approval,
execution-plan, verification, and evidence detail are explicit-load only.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from .mart import mart_object_name
from .query import run_query, sql_literal


CLOSED_LOOP_DOMAINS = ("ALL", "Cost", "Operations", "Security", "Workload", "Alert")
CLOSED_LOOP_RISK_LABELS = ("Critical", "High", "Medium", "Low")
CLOSED_LOOP_EXECUTION_MODES = (
    "REVIEW_SQL_ONLY",
    "MANUAL_REVIEW",
    "RECOMMEND_ONLY",
    "DRY_RUN_ONLY",
    "EXTERNAL_EXECUTION_RECORDED",
)
CLOSED_LOOP_CONFIDENCE_LABELS = ("exact", "allocated", "estimated", "fallback")


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


def load_closed_loop_summary(
    company: str,
    environment: str,
    *,
    days: int = 35,
) -> pd.DataFrame:
    """Load compact first-paint-safe Closed Loop Operations summary rows."""
    table = mart_object_name("MART_CLOSED_LOOP_OPERATIONS_SUMMARY")
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
            ACTION_DOMAIN,
            OPEN_ACTION_COUNT,
            APPROVAL_REQUIRED_COUNT,
            APPROVED_COUNT,
            EXECUTION_PLAN_COUNT,
            VERIFICATION_PENDING_COUNT,
            VERIFIED_COUNT,
            CLOSED_COUNT,
            HIGH_RISK_COUNT,
            OWNER_GAP_COUNT,
            EVIDENCE_COUNT,
            EXPECTED_SAVINGS_USD,
            ACTUAL_VERIFIED_SAVINGS_USD,
            UNVERIFIED_EXPECTED_USD,
            TOP_FINDING,
            NEXT_ACTION,
            CONFIDENCE,
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
          ACTION_DOMAIN,
          OPEN_ACTION_COUNT,
          APPROVAL_REQUIRED_COUNT,
          APPROVED_COUNT,
          EXECUTION_PLAN_COUNT,
          VERIFICATION_PENDING_COUNT,
          VERIFIED_COUNT,
          CLOSED_COUNT,
          HIGH_RISK_COUNT,
          OWNER_GAP_COUNT,
          EVIDENCE_COUNT,
          EXPECTED_SAVINGS_USD,
          ACTUAL_VERIFIED_SAVINGS_USD,
          UNVERIFIED_EXPECTED_USD,
          TOP_FINDING,
          NEXT_ACTION,
          CONFIDENCE,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY ACTION_DOMAIN
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY
          CASE ACTION_DOMAIN
            WHEN 'ALL' THEN 0 WHEN 'Cost' THEN 1 WHEN 'Operations' THEN 2
            WHEN 'Security' THEN 3 WHEN 'Workload' THEN 4 ELSE 5
          END
        """,
        ttl_key=f"closed_loop_summary_{company}_{environment}_{window_days}",
        tier="historical",
        section="Executive Landing",
        max_rows=20,
    )


def load_closed_loop_workflow_detail(
    company: str,
    environment: str,
    *,
    domains: Sequence[str] | None = None,
    days: int = 180,
) -> pd.DataFrame:
    """Load gated action workflow rows."""
    table = mart_object_name("OVERWATCH_ACTION_WORKFLOW")
    window_days = max(1, int(days or 180))
    scope = _scope_clause(company, environment)
    scope_rank = _scope_rank_expr(company, environment)
    domain_filter = _list_clause("ACTION_DOMAIN", domains, CLOSED_LOOP_DOMAINS)
    return run_query(
        f"""
        WITH scoped AS (
          SELECT
            SNAPSHOT_TS,
            COMPANY,
            ENVIRONMENT,
            WORKFLOW_ID,
            ACTION_SOURCE,
            SOURCE_ID,
            ACTION_DOMAIN,
            FINDING,
            SOURCE_TELEMETRY,
            ENTITY_TYPE,
            ENTITY_NAME,
            OWNER_ROUTE,
            OWNER_GAP,
            BUSINESS_IMPACT,
            RISK_LEVEL,
            RECOMMENDED_ACTION,
            ACTION_STATUS,
            APPROVAL_STATUS,
            APPROVED_BY,
            APPROVAL_TS,
            EXECUTION_MODE,
            REVIEW_SQL_TEXT,
            REVIEW_ACTION_TEXT,
            ROLLBACK_GUIDANCE,
            VERIFICATION_STEPS,
            VERIFICATION_STATUS,
            EXPECTED_SAVINGS_USD,
            ACTUAL_VERIFIED_SAVINGS_USD,
            EVIDENCE,
            CLOSED_TS,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
            {domain_filter}
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          WORKFLOW_ID,
          ACTION_SOURCE,
          SOURCE_ID,
          ACTION_DOMAIN,
          FINDING,
          SOURCE_TELEMETRY,
          ENTITY_TYPE,
          ENTITY_NAME,
          OWNER_ROUTE,
          OWNER_GAP,
          BUSINESS_IMPACT,
          RISK_LEVEL,
          RECOMMENDED_ACTION,
          ACTION_STATUS,
          APPROVAL_STATUS,
          APPROVED_BY,
          APPROVAL_TS,
          EXECUTION_MODE,
          REVIEW_SQL_TEXT,
          REVIEW_ACTION_TEXT,
          ROLLBACK_GUIDANCE,
          VERIFICATION_STEPS,
          VERIFICATION_STATUS,
          EXPECTED_SAVINGS_USD,
          ACTUAL_VERIFIED_SAVINGS_USD,
          EVIDENCE,
          CLOSED_TS,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY WORKFLOW_ID
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY
          CASE RISK_LEVEL WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
          LAST_REFRESHED_TS DESC
        """,
        ttl_key=f"closed_loop_workflow_{company}_{environment}_{'_'.join(domains or ())}_{window_days}",
        tier="historical",
        section="Closed Loop Operations",
        max_rows=500,
    )


def load_closed_loop_execution_plan_detail(
    company: str,
    environment: str,
    *,
    domains: Sequence[str] | None = None,
    days: int = 180,
) -> pd.DataFrame:
    """Load gated review SQL/action-plan rows. This never executes the plan."""
    table = mart_object_name("OVERWATCH_ACTION_EXECUTION_PLAN")
    window_days = max(1, int(days or 180))
    scope = _scope_clause(company, environment)
    scope_rank = _scope_rank_expr(company, environment)
    domain_filter = _list_clause("ACTION_DOMAIN", domains, CLOSED_LOOP_DOMAINS)
    return run_query(
        f"""
        WITH scoped AS (
          SELECT
            SNAPSHOT_TS,
            COMPANY,
            ENVIRONMENT,
            WORKFLOW_ID,
            ACTION_DOMAIN,
            EXECUTION_MODE,
            EXECUTION_STATUS,
            REVIEW_SQL_TEXT,
            REVIEW_ACTION_TEXT,
            DANGEROUS_ACTION_FLAG,
            EXECUTION_ALLOWED_IN_APP,
            ROLLBACK_GUIDANCE,
            VERIFICATION_STEPS,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
            {domain_filter}
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          WORKFLOW_ID,
          ACTION_DOMAIN,
          EXECUTION_MODE,
          EXECUTION_STATUS,
          REVIEW_SQL_TEXT,
          REVIEW_ACTION_TEXT,
          DANGEROUS_ACTION_FLAG,
          EXECUTION_ALLOWED_IN_APP,
          ROLLBACK_GUIDANCE,
          VERIFICATION_STEPS,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY WORKFLOW_ID
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY DANGEROUS_ACTION_FLAG DESC, LAST_REFRESHED_TS DESC
        """,
        ttl_key=f"closed_loop_execution_plan_{company}_{environment}_{'_'.join(domains or ())}_{window_days}",
        tier="historical",
        section="Closed Loop Operations",
        max_rows=500,
    )


def load_closed_loop_verification_detail(
    company: str,
    environment: str,
    *,
    domains: Sequence[str] | None = None,
    days: int = 180,
) -> pd.DataFrame:
    """Load gated verification and savings measurement rows."""
    table = mart_object_name("OVERWATCH_ACTION_VERIFICATION")
    window_days = max(1, int(days or 180))
    scope = _scope_clause(company, environment)
    scope_rank = _scope_rank_expr(company, environment)
    domain_filter = _list_clause("ACTION_DOMAIN", domains, CLOSED_LOOP_DOMAINS)
    return run_query(
        f"""
        WITH scoped AS (
          SELECT
            SNAPSHOT_TS,
            COMPANY,
            ENVIRONMENT,
            WORKFLOW_ID,
            ACTION_DOMAIN,
            VERIFICATION_STATUS,
            VERIFICATION_STEPS,
            EXPECTED_SAVINGS_USD,
            ACTUAL_VERIFIED_SAVINGS_USD,
            VERIFICATION_WINDOW_START,
            VERIFICATION_WINDOW_END,
            VERIFIED_BY,
            VERIFIED_AT,
            EVIDENCE,
            LAST_REFRESHED_TS,
            LOAD_TS,
            {scope_rank} AS SCOPE_RANK
          FROM {table}
          WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
            {scope}
            {domain_filter}
        )
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          WORKFLOW_ID,
          ACTION_DOMAIN,
          VERIFICATION_STATUS,
          VERIFICATION_STEPS,
          EXPECTED_SAVINGS_USD,
          ACTUAL_VERIFIED_SAVINGS_USD,
          VERIFICATION_WINDOW_START,
          VERIFICATION_WINDOW_END,
          VERIFIED_BY,
          VERIFIED_AT,
          EVIDENCE,
          LAST_REFRESHED_TS
        FROM scoped
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY WORKFLOW_ID
          ORDER BY SCOPE_RANK ASC, SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY ACTUAL_VERIFIED_SAVINGS_USD DESC, EXPECTED_SAVINGS_USD DESC, LAST_REFRESHED_TS DESC
        """,
        ttl_key=f"closed_loop_verification_{company}_{environment}_{'_'.join(domains or ())}_{window_days}",
        tier="historical",
        section="Closed Loop Operations",
        max_rows=500,
    )
