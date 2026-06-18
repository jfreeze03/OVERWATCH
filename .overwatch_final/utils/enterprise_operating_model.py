"""Mart-first helpers for the enterprise operating model.

This module keeps the four Phase 1 enterprise capabilities out of section
code. Every query here reads an OVERWATCH table or mart; it never scans live
ACCOUNT_USAGE surfaces. Detail loaders are intended to be called only from
explicit Load buttons in the UI.
"""

from __future__ import annotations

import pandas as pd

from .mart import mart_object_name
from .query import run_query, sql_literal


CONFIDENCE_LABELS = ("exact", "allocated", "estimated", "fallback")


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


def _surface_clause(surface: str, *, table_alias: str = "") -> str:
    value = str(surface or "").strip()
    if not value:
        return ""
    prefix = f"{table_alias}." if table_alias else ""
    return f"AND COALESCE({prefix}SURFACE, '') = {sql_literal(value, 200)}"


def load_enterprise_operating_rollups(
    company: str,
    environment: str,
    *,
    days: int = 35,
) -> dict[str, pd.DataFrame]:
    """Load compact first-paint-safe rollups for Executive Landing."""
    window_days = max(1, int(days or 35))
    scope = _scope_clause(company, environment)
    trust_table = mart_object_name("MART_DATA_TRUST_SUMMARY")
    ownership_table = mart_object_name("MART_OPERATIONAL_OWNER_COVERAGE")
    value_table = mart_object_name("MART_EXECUTIVE_VALUE_LEDGER")
    app_table = mart_object_name("MART_APP_OBSERVABILITY_SUMMARY")
    return {
        "trust": run_query(
            f"""
            SELECT *
            FROM {trust_table}
            WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
              {scope}
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY COMPANY, ENVIRONMENT, SOURCE_NAME
              ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
            ) = 1
            ORDER BY
              CASE STATUS WHEN 'Missing' THEN 0 WHEN 'Stale' THEN 1 WHEN 'No Rows' THEN 2 ELSE 3 END,
              FRESHNESS_MINUTES DESC NULLS FIRST,
              SOURCE_NAME
            """,
            ttl_key=f"enterprise_trust_rollup_{company}_{environment}",
            tier="historical",
            section="Executive Landing",
            max_rows=100,
        ),
        "ownership": run_query(
            f"""
            SELECT *
            FROM {ownership_table}
            WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
              {scope}
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY COMPANY, ENVIRONMENT, SURFACE, ENTITY_TYPE
              ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
            ) = 1
            ORDER BY GAP_ITEMS DESC, SURFACE, ENTITY_TYPE
            """,
            ttl_key=f"enterprise_ownership_rollup_{company}_{environment}",
            tier="historical",
            section="Executive Landing",
            max_rows=100,
        ),
        "value": run_query(
            f"""
            SELECT *
            FROM {value_table}
            WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
              {scope}
              AND WINDOW_DAYS = 35
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY COMPANY, ENVIRONMENT, STATUS, OWNER_ROUTE, CONFIDENCE
              ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
            ) = 1
            ORDER BY VERIFIED_SAVINGS_USD DESC, EXPECTED_SAVINGS_USD DESC, STATUS
            """,
            ttl_key=f"enterprise_value_rollup_{company}_{environment}",
            tier="historical",
            section="Executive Landing",
            max_rows=100,
        ),
        "app": run_query(
            f"""
            SELECT *
            FROM {app_table}
            WHERE SNAPSHOT_TS >= DATEADD('DAY', -{window_days}, CURRENT_TIMESTAMP())
              {scope}
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY COMPANY, ENVIRONMENT, SECTION_NAME
              ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
            ) = 1
            ORDER BY
              CASE HEALTH_STATE WHEN 'Critical' THEN 0 WHEN 'Review' THEN 1 WHEN 'No Rows' THEN 2 ELSE 3 END,
              P95_RENDER_MS DESC NULLS LAST,
              SECTION_NAME
            """,
            ttl_key=f"enterprise_app_rollup_{company}_{environment}",
            tier="historical",
            section="Executive Landing",
            max_rows=100,
        ),
    }


def load_data_trust_detail(company: str, environment: str, *, days: int = 35) -> pd.DataFrame:
    """Load source-level trust diagnostics for DBA Control Room."""
    table = mart_object_name("OVERWATCH_DATA_TRUST_STATUS")
    scope = _scope_clause(company, environment)
    return run_query(
        f"""
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          SOURCE_NAME,
          SOURCE_OBJECT,
          SOURCE_CLASS,
          LATEST_SOURCE_TS,
          AGE_MINUTES,
          TARGET_FRESHNESS_MIN,
          STATUS,
          CONFIDENCE,
          OWNER_ROUTE AS ROUTE,
          BUSINESS_IMPACT,
          NEXT_ACTION
        FROM {table}
        WHERE SNAPSHOT_TS >= DATEADD('DAY', -{max(1, int(days or 35))}, CURRENT_TIMESTAMP())
          {scope}
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY COMPANY, ENVIRONMENT, SOURCE_KEY
          ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY
          CASE STATUS WHEN 'Missing' THEN 0 WHEN 'Stale' THEN 1 WHEN 'No Rows' THEN 2 ELSE 3 END,
          AGE_MINUTES DESC NULLS FIRST,
          SOURCE_NAME
        """,
        ttl_key=f"enterprise_data_trust_detail_{company}_{environment}",
        tier="historical",
        section="DBA Control Room",
        max_rows=200,
    )


def load_app_observability_detail(company: str, environment: str, *, days: int = 7) -> pd.DataFrame:
    """Load app self-observability detail for DBA Control Room."""
    table = mart_object_name("OVERWATCH_APP_OBSERVABILITY")
    scope = _scope_clause(company, environment)
    return run_query(
        f"""
        SELECT
          EVENT_TS,
          COMPANY,
          ENVIRONMENT,
          APP_VERSION,
          SECTION_NAME,
          EVENT_TYPE,
          RENDER_MS,
          QUERY_COUNT,
          QUERY_FAILURE_COUNT,
          OVERWATCH_COST_USD,
          VALIDATION_STATUS,
          DEPLOYMENT_VERSION,
          LAST_DEPLOYMENT_TS,
          DETAIL
        FROM {table}
        WHERE EVENT_TS >= DATEADD('DAY', -{max(1, int(days or 7))}, CURRENT_TIMESTAMP())
          {scope}
        ORDER BY EVENT_TS DESC, QUERY_FAILURE_COUNT DESC, RENDER_MS DESC NULLS LAST
        """,
        ttl_key=f"enterprise_app_detail_{company}_{environment}_{days}",
        tier="historical",
        section="DBA Control Room",
        max_rows=500,
    )


def load_ownership_coverage_rollup(
    company: str,
    environment: str,
    *,
    surface: str = "",
    days: int = 35,
) -> pd.DataFrame:
    """Load compact operational ownership coverage for an app section."""
    table = mart_object_name("MART_OPERATIONAL_OWNER_COVERAGE")
    scope = _scope_clause(company, environment)
    return run_query(
        f"""
        SELECT
          SNAPSHOT_TS,
          COMPANY,
          ENVIRONMENT,
          SURFACE,
          ENTITY_TYPE,
          TOTAL_ITEMS,
          ROUTED_ITEMS,
          GAP_ITEMS,
          COVERAGE_PCT,
          TRUST_LEVEL,
          CONFIDENCE,
          TOP_GAP_ENTITY,
          OWNER_ROUTE AS ROUTE,
          NEXT_ACTION
        FROM {table}
        WHERE SNAPSHOT_TS >= DATEADD('DAY', -{max(1, int(days or 35))}, CURRENT_TIMESTAMP())
          {scope}
          {_surface_clause(surface)}
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY COMPANY, ENVIRONMENT, SURFACE, ENTITY_TYPE
          ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY GAP_ITEMS DESC, COVERAGE_PCT ASC, ENTITY_TYPE
        """,
        ttl_key=f"enterprise_owner_rollup_{company}_{environment}_{surface}",
        tier="historical",
        section=surface or "Enterprise Ownership",
        max_rows=100,
    )


def load_value_ledger_rollup(company: str, environment: str, *, days: int = 35) -> pd.DataFrame:
    """Load compact value ledger rollup for Cost & Contract first paint."""
    table = mart_object_name("MART_EXECUTIVE_VALUE_LEDGER")
    scope = _scope_clause(company, environment)
    days_int = max(1, int(days or 35))
    return run_query(
        f"""
        SELECT *
        FROM {table}
        WHERE SNAPSHOT_TS >= DATEADD('DAY', -35, CURRENT_TIMESTAMP())
          {scope}
          AND WINDOW_DAYS = {days_int if days_int in {35, 90, 180} else 35}
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY COMPANY, ENVIRONMENT, STATUS, OWNER_ROUTE, CONFIDENCE
          ORDER BY SNAPSHOT_TS DESC, LOAD_TS DESC
        ) = 1
        ORDER BY VERIFIED_SAVINGS_USD DESC, EXPECTED_SAVINGS_USD DESC, STATUS
        """,
        ttl_key=f"enterprise_value_ledger_rollup_{company}_{environment}_{days_int}",
        tier="historical",
        section="Cost & Contract",
        max_rows=100,
    )


def load_value_ledger_detail(company: str, environment: str, *, days: int = 180) -> pd.DataFrame:
    """Load verification-detail value ledger rows for Cost & Contract."""
    ledger = mart_object_name("OVERWATCH_VALUE_LEDGER")
    queue = mart_object_name("OVERWATCH_ACTION_QUEUE")
    scope = _scope_clause(company, environment, table_alias="src")
    days_int = max(1, int(days or 180))
    return run_query(
        f"""
        WITH src AS (
          SELECT
            'VALUE_LEDGER' AS SOURCE,
            LEDGER_ID AS ITEM_ID,
            COMPANY,
            ENVIRONMENT,
            FINDING,
            ENTITY_TYPE,
            ENTITY_NAME,
            OWNER_ROUTE AS ROUTE,
            STATUS,
            EXPECTED_SAVINGS_USD,
            IFF(VERIFIED_AT IS NOT NULL, COALESCE(ACTUAL_VERIFIED_SAVINGS_USD, 0), 0) AS ACTUAL_VERIFIED_SAVINGS_USD,
            IFF(VERIFIED_AT IS NULL, COALESCE(EXPECTED_SAVINGS_USD, 0), 0) AS UNVERIFIED_ESTIMATE_USD,
            CONFIDENCE,
            TRUST_LEVEL,
            BUSINESS_IMPACT,
            ACTION_TAKEN,
            EVIDENCE AS SUPPORTING_SIGNAL,
            VERIFICATION_WINDOW_START,
            VERIFICATION_WINDOW_END,
            VERIFIED_BY,
            VERIFIED_AT,
            ROLLBACK_NOTES,
            UPDATED_AT
          FROM {ledger}
          WHERE UPDATED_AT >= DATEADD('DAY', -{days_int}, CURRENT_TIMESTAMP())
          UNION ALL
          SELECT
            'ACTION_QUEUE' AS SOURCE,
            ACTION_ID AS ITEM_ID,
            COMPANY,
            ENVIRONMENT,
            FINDING,
            ENTITY_TYPE,
            ENTITY_NAME,
            COALESCE(NULLIF(OWNER, ''), NULLIF(ONCALL_PRIMARY, ''), NULLIF(ESCALATION_TARGET, ''), 'DBA / Cost owner') AS ROUTE,
            STATUS,
            COALESCE(EST_MONTHLY_SAVINGS, 0) AS EXPECTED_SAVINGS_USD,
            IFF(
              UPPER(COALESCE(VERIFICATION_STATUS, '')) IN ('VERIFIED', 'COMPLETE', 'PASSED')
              AND VERIFIED_AT IS NOT NULL,
              COALESCE(ABS(MEASURED_DELTA), 0),
              0
            ) AS ACTUAL_VERIFIED_SAVINGS_USD,
            IFF(
              UPPER(COALESCE(VERIFICATION_STATUS, '')) IN ('VERIFIED', 'COMPLETE', 'PASSED')
              AND VERIFIED_AT IS NOT NULL,
              0,
              COALESCE(EST_MONTHLY_SAVINGS, 0)
            ) AS UNVERIFIED_ESTIMATE_USD,
            'estimated' AS CONFIDENCE,
            IFF(VERIFIED_AT IS NOT NULL, 'Value Verified', 'Verification Pending') AS TRUST_LEVEL,
            CATEGORY AS BUSINESS_IMPACT,
            RECOMMENDED_ACTION AS ACTION_TAKEN,
            COALESCE(VERIFICATION_RESULT, VERIFICATION_NOTES, PROOF_QUERY, RECOVERY_EVIDENCE) AS SUPPORTING_SIGNAL,
            CREATED_AT AS VERIFICATION_WINDOW_START,
            VERIFIED_AT AS VERIFICATION_WINDOW_END,
            VERIFIED_BY,
            VERIFIED_AT,
            IGNORED_REASON AS ROLLBACK_NOTES,
            UPDATED_AT
          FROM {queue}
          WHERE COALESCE(CATEGORY, SOURCE, '') ILIKE '%COST%'
             OR COALESCE(FINDING, RECOMMENDED_ACTION, '') ILIKE '%SAVING%'
             OR COALESCE(EST_MONTHLY_SAVINGS, 0) <> 0
        )
        SELECT *
        FROM src
        WHERE UPDATED_AT >= DATEADD('DAY', -{days_int}, CURRENT_TIMESTAMP())
          {scope}
        ORDER BY ACTUAL_VERIFIED_SAVINGS_USD DESC, EXPECTED_SAVINGS_USD DESC, UPDATED_AT DESC
        """,
        ttl_key=f"enterprise_value_ledger_detail_{company}_{environment}_{days_int}",
        tier="historical",
        section="Cost & Contract",
        max_rows=500,
    )
