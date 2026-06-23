"""Focused mart SQL builders for the cost family."""

from __future__ import annotations

from .mart_filters import _mart_company_filter, _mart_environment_filter, _mart_text_filter
from .mart_names import mart_object_name
from .metering_sql import build_cost_cockpit_metering_sql, build_cost_run_rate_metering_sql
from .query import sql_literal

__all__ = [
    "build_mart_bill_summary_sql",
    "build_mart_bill_warehouse_delta_sql",
    "build_mart_chargeback_sql",
    "build_mart_cost_explorer_sql",
    "build_mart_cost_cockpit_sql",
    "build_mart_cost_service_lens_sql",
    "build_mart_cost_run_rate_sql",
]


def build_mart_bill_summary_sql(
    current_start: str,
    current_end: str,
    prior_start: str,
    prior_end: str,
    company: str = "ALFA",
    warehouse_contains: str = "",
) -> str:
    """Build a bill-summary query from hourly warehouse summary facts."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND COMPANY = {sql_literal(company, 100)}"
    warehouse_filter = (
        f"AND WAREHOUSE_NAME ILIKE '%' || {sql_literal(warehouse_contains, 300)} || '%'"
        if str(warehouse_contains or "").strip()
        else ""
    )
    return f"""
        WITH bounds AS (
            SELECT
                {current_start} AS current_start,
                {current_end} AS current_end,
                {prior_start} AS prior_start,
                {prior_end} AS prior_end
        ),
        metering AS (
            SELECT 'CURRENT' AS period, warehouse_name, hour_start, credits_used
            FROM {table}, bounds
            WHERE hour_start >= current_start
              AND hour_start < current_end
              {company_filter}
              {warehouse_filter}
            UNION ALL
            SELECT 'PRIOR' AS period, warehouse_name, hour_start, credits_used
            FROM {table}, bounds
            WHERE hour_start >= prior_start
              AND hour_start < prior_end
              {company_filter}
              {warehouse_filter}
        )
        SELECT
            period,
            ROUND(SUM(credits_used), 4) AS credits,
            COUNT(DISTINCT warehouse_name) AS active_warehouses,
            COUNT(DISTINCT TO_DATE(hour_start)) AS active_days
        FROM metering
        GROUP BY period
    """

def build_mart_bill_warehouse_delta_sql(
    current_start: str,
    current_end: str,
    prior_start: str,
    prior_end: str,
    company: str = "ALFA",
    warehouse_contains: str = "",
) -> str:
    """Build warehouse-period delta query from hourly warehouse summary facts."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND COMPANY = {sql_literal(company, 100)}"
    warehouse_filter = (
        f"AND WAREHOUSE_NAME ILIKE '%' || {sql_literal(warehouse_contains, 300)} || '%'"
        if str(warehouse_contains or "").strip()
        else ""
    )
    return f"""
        WITH bounds AS (
            SELECT
                {current_start} AS current_start,
                {current_end} AS current_end,
                {prior_start} AS prior_start,
                {prior_end} AS prior_end
        ),
        current_wh AS (
            SELECT warehouse_name, SUM(credits_used) AS credits
            FROM {table}, bounds
            WHERE hour_start >= current_start
              AND hour_start < current_end
              {company_filter}
              {warehouse_filter}
            GROUP BY warehouse_name
        ),
        prior_wh AS (
            SELECT warehouse_name, SUM(credits_used) AS credits
            FROM {table}, bounds
            WHERE hour_start >= prior_start
              AND hour_start < prior_end
              {company_filter}
              {warehouse_filter}
            GROUP BY warehouse_name
        )
        SELECT
            COALESCE(c.warehouse_name, p.warehouse_name) AS warehouse_name,
            ROUND(COALESCE(c.credits, 0), 4) AS current_credits,
            ROUND(COALESCE(p.credits, 0), 4) AS prior_credits,
            ROUND(COALESCE(c.credits, 0) - COALESCE(p.credits, 0), 4) AS credit_delta,
            CASE
                WHEN COALESCE(p.credits, 0) = 0 THEN NULL
                ELSE ROUND(((COALESCE(c.credits, 0) - p.credits) / NULLIF(p.credits, 0)) * 100, 2)
            END AS pct_delta
        FROM current_wh c
        FULL OUTER JOIN prior_wh p ON c.warehouse_name = p.warehouse_name
        ORDER BY ABS(COALESCE(c.credits, 0) - COALESCE(p.credits, 0)) DESC
        LIMIT 25
    """

def build_mart_chargeback_sql(
    days_back: int = 30,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
) -> str:
    """Build chargeback detail from the daily chargeback snapshot mart."""
    table = mart_object_name("FACT_CHARGEBACK_DAILY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("ENVIRONMENT", company)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_text_filter("DATABASE_NAME", database_contains)
    return f"""
        SELECT
            COMPANY,
            ENVIRONMENT,
            ENVIRONMENT_ROLLUP,
            DATABASE_NAME,
            USER_NAME,
            ROLE_NAME,
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE,
            SUM(QUERY_COUNT) AS QUERY_COUNT,
            ROUND(SUM(ALLOCATED_CREDITS), 4) AS TOTAL_CREDITS,
            ROUND(SUM(EST_COST_USD), 2) AS EST_COST,
            ALLOCATION_CONFIDENCE,
            ALLOCATION_BASIS,
            CHARGEBACK_READY,
            SCOPE_REVIEW,
            COST_OWNER,
            OWNER_SOURCE,
            OWNER_EVIDENCE,
            MAX(LOAD_TS) AS MART_LOAD_TS
        FROM {table}
        WHERE USAGE_DATE >= DATEADD('DAY', -{int(days_back)}, CURRENT_DATE())
          {company_filter}
          {env_filter}
          {wh_filter}
          {user_filter}
          {role_filter}
          {db_filter}
        GROUP BY
            COMPANY,
            ENVIRONMENT,
            ENVIRONMENT_ROLLUP,
            DATABASE_NAME,
            USER_NAME,
            ROLE_NAME,
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE,
            ALLOCATION_CONFIDENCE,
            ALLOCATION_BASIS,
            CHARGEBACK_READY,
            SCOPE_REVIEW,
            COST_OWNER,
            OWNER_SOURCE,
            OWNER_EVIDENCE
        ORDER BY TOTAL_CREDITS DESC, QUERY_COUNT DESC
    """

def build_mart_cost_explorer_sql(
    days_back: int = 30,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    department_contains: str = "",
) -> str:
    """Build a multi-dimension Cost Explorer detail query from chargeback facts."""
    table = mart_object_name("FACT_CHARGEBACK_DAILY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("ENVIRONMENT", company)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_text_filter("DATABASE_NAME", database_contains)
    dept_filter = _mart_text_filter("COALESCE(COST_OWNER, 'Unassigned')", department_contains)
    return f"""
        SELECT
            COMPANY,
            ENVIRONMENT,
            ENVIRONMENT_ROLLUP,
            DATABASE_NAME,
            USER_NAME,
            ROLE_NAME,
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE,
            COALESCE(NULLIF(COST_OWNER, ''), 'Unassigned') AS DEPARTMENT,
            COST_OWNER,
            OWNER_SOURCE,
            OWNER_EVIDENCE,
            ALLOCATION_CONFIDENCE,
            ALLOCATION_BASIS,
            CHARGEBACK_READY,
            SCOPE_REVIEW,
            SUM(QUERY_COUNT) AS QUERY_COUNT,
            ROUND(SUM(ALLOCATED_CREDITS), 4) AS TOTAL_CREDITS,
            ROUND(SUM(EST_COST_USD), 2) AS EST_COST,
            MIN(USAGE_DATE) AS FIRST_USAGE_DATE,
            MAX(USAGE_DATE) AS LAST_USAGE_DATE,
            COUNT(DISTINCT USAGE_DATE) AS ACTIVE_DAYS,
            MAX(LOAD_TS) AS MART_LOAD_TS
        FROM {table}
        WHERE USAGE_DATE >= DATEADD('DAY', -{int(days_back)}, CURRENT_DATE())
          {company_filter}
          {env_filter}
          {wh_filter}
          {user_filter}
          {role_filter}
          {db_filter}
          {dept_filter}
        GROUP BY
            COMPANY,
            ENVIRONMENT,
            ENVIRONMENT_ROLLUP,
            DATABASE_NAME,
            USER_NAME,
            ROLE_NAME,
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE,
            COALESCE(NULLIF(COST_OWNER, ''), 'Unassigned'),
            COST_OWNER,
            OWNER_SOURCE,
            OWNER_EVIDENCE,
            ALLOCATION_CONFIDENCE,
            ALLOCATION_BASIS,
            CHARGEBACK_READY,
            SCOPE_REVIEW
        ORDER BY TOTAL_CREDITS DESC, QUERY_COUNT DESC
    """

def build_mart_cost_cockpit_sql(company: str = "ALFA", days: int = 7) -> str:
    """Build the Cost & Contract landing cockpit from hourly warehouse facts."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    return build_cost_cockpit_metering_sql(table, "hour_start", company_filter, days=int(days))

def build_mart_cost_service_lens_sql(
    days_back: int = 7,
    credit_price: float = 3.68,
    ai_credit_price: float = 2.20,
) -> str:
    """Build account service-cost lens from the daily cost mart."""
    table = mart_object_name("FACT_COST_DAILY")
    days_back = max(1, int(days_back or 7))
    credit_price = float(credit_price or 3.68)
    ai_credit_price = float(ai_credit_price or 2.20)
    return f"""
        WITH perioded AS (
            SELECT
                SERVICE_CATEGORY,
                SERVICE_TYPE,
                CASE
                    WHEN UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%CORTEX%'
                      OR UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%AI%'
                      OR UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%INTELLIGENCE%'
                        THEN {ai_credit_price:.4f}
                    ELSE {credit_price:.4f}
                END AS RATE_USD,
                CASE
                    WHEN USAGE_DATE >= DATEADD('DAY', -{days_back}, CURRENT_DATE()) THEN 'CURRENT'
                    ELSE 'PRIOR'
                END AS PERIOD,
                COALESCE(CREDITS_BILLED, 0) AS CREDITS_BILLED,
                COALESCE(CREDITS_USED_COMPUTE, 0) AS CREDITS_USED_COMPUTE,
                COALESCE(CREDITS_USED_CLOUD_SERVICES, 0) AS CREDITS_USED_CLOUD_SERVICES,
                COALESCE(CREDITS_ADJUSTMENT_CLOUD_SERVICES, 0) AS CREDITS_ADJUSTMENT_CLOUD_SERVICES,
                COALESCE(
                    EST_COST_USD,
                    CREDITS_BILLED * CASE
                        WHEN UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%CORTEX%'
                          OR UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%AI%'
                          OR UPPER(COALESCE(SERVICE_TYPE, 'UNKNOWN')) ILIKE '%INTELLIGENCE%'
                            THEN {ai_credit_price:.4f}
                        ELSE {credit_price:.4f}
                    END
                ) AS EST_COST_USD,
                USAGE_DATE
            FROM {table}
            WHERE USAGE_DATE >= DATEADD('DAY', -{days_back * 2}, CURRENT_DATE())
              AND USAGE_DATE < CURRENT_DATE()
        )
        SELECT
            SERVICE_CATEGORY,
            SERVICE_TYPE,
            MAX(RATE_USD) AS RATE_USD,
            ROUND(SUM(IFF(PERIOD = 'CURRENT', CREDITS_BILLED, 0)), 4) AS CREDITS_BILLED,
            ROUND(SUM(IFF(PERIOD = 'PRIOR', CREDITS_BILLED, 0)), 4) AS CREDITS_BILLED_PRIOR,
            ROUND(
                SUM(IFF(PERIOD = 'CURRENT', CREDITS_BILLED, 0))
                - SUM(IFF(PERIOD = 'PRIOR', CREDITS_BILLED, 0)),
                4
            ) AS CREDIT_DELTA,
            CASE
                WHEN SUM(IFF(PERIOD = 'PRIOR', CREDITS_BILLED, 0)) = 0 THEN NULL
                ELSE ROUND(
                    (
                        SUM(IFF(PERIOD = 'CURRENT', CREDITS_BILLED, 0))
                        - SUM(IFF(PERIOD = 'PRIOR', CREDITS_BILLED, 0))
                    ) / NULLIF(SUM(IFF(PERIOD = 'PRIOR', CREDITS_BILLED, 0)), 0) * 100,
                    2
                )
            END AS PCT_DELTA,
            ROUND(SUM(IFF(PERIOD = 'CURRENT', CREDITS_USED_COMPUTE, 0)), 4) AS CREDITS_USED_COMPUTE,
            ROUND(SUM(IFF(PERIOD = 'CURRENT', COALESCE(CREDITS_USED_CLOUD_SERVICES, 0), 0)), 4) AS CREDITS_USED_CLOUD_SERVICES,
            ROUND(SUM(IFF(PERIOD = 'CURRENT', CREDITS_ADJUSTMENT_CLOUD_SERVICES, 0)), 4) AS CREDITS_ADJUSTMENT_CLOUD_SERVICES,
            ROUND(SUM(IFF(PERIOD = 'CURRENT', EST_COST_USD, 0)), 2) AS ESTIMATED_COST_USD,
            ROUND(SUM(IFF(PERIOD = 'PRIOR', EST_COST_USD, 0)), 2) AS PRIOR_ESTIMATED_COST_USD,
            ROUND(
                SUM(IFF(PERIOD = 'CURRENT', EST_COST_USD, 0))
                - SUM(IFF(PERIOD = 'PRIOR', EST_COST_USD, 0)),
                2
            ) AS COST_DELTA_USD,
            COUNT(DISTINCT IFF(PERIOD = 'CURRENT', USAGE_DATE, NULL)) AS OBSERVED_DAYS,
            'Fast cost summary' AS SNOWFLAKE_SOURCE
        FROM perioded
        GROUP BY SERVICE_CATEGORY, SERVICE_TYPE
        HAVING ABS(SUM(CREDITS_BILLED)) > 0
            OR ABS(SUM(CREDITS_USED_COMPUTE)) > 0
            OR ABS(SUM(COALESCE(CREDITS_USED_CLOUD_SERVICES, 0))) > 0
        ORDER BY ABS(CREDIT_DELTA) DESC, CREDITS_BILLED DESC, SERVICE_CATEGORY, SERVICE_TYPE
    """

def build_mart_cost_run_rate_sql(company: str = "ALFA") -> str:
    """Build complete-day 7d/30d run-rate and YOY cost trend from fast summary facts."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    return build_cost_run_rate_metering_sql(table, "hour_start", company_filter)
