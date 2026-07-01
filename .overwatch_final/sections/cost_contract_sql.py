"""Pure Cost & Contract SQL builders.

This module owns SQL string construction for the Cost & Contract section. It
does not call Streamlit, mutate session state, or render UI; ``cost_contract``
imports and re-exports these helpers for compatibility.
"""

from __future__ import annotations

from config import DEFAULTS, ETL_AUDIT_DB, ETL_AUDIT_SCHEMA
from utils.admin import safe_identifier
from utils.company_filter import get_user_company_filter_clause, get_wh_filter_clause
from utils.cost import build_snowflake_service_cost_trend_sql
from utils.mart import build_mart_bill_warehouse_delta_sql
from utils.metering_sql import build_cost_cockpit_metering_sql, build_cost_run_rate_metering_sql
from utils.primitives import safe_float
from utils.shared_metrics import build_shared_bill_warehouse_delta_live_sql
from utils.sql_safe import sql_literal


def _build_cost_cockpit_sql(company: str, days: int) -> str:
    return build_cost_cockpit_metering_sql(
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        "start_time",
        get_wh_filter_clause("warehouse_name", company),
        days=int(days),
    )


def _build_cost_run_rate_sql(company: str) -> str:
    """Build live fallback SQL for complete-day 7d/30d run-rate and YOY cost trend."""
    return build_cost_run_rate_metering_sql(
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        "start_time",
        get_wh_filter_clause("warehouse_name", company),
    )


def _warehouse_hourly_table() -> str:
    return f"{safe_identifier(ETL_AUDIT_DB)}.{safe_identifier(ETL_AUDIT_SCHEMA)}.{safe_identifier('FACT_WAREHOUSE_HOURLY')}"


def _cortex_daily_table() -> str:
    return f"{safe_identifier(ETL_AUDIT_DB)}.{safe_identifier(ETL_AUDIT_SCHEMA)}.{safe_identifier('FACT_CORTEX_DAILY')}"


def _snowflake_user_chart_expr(alias: str, fallback_expr: str) -> str:
    """Return the daily-safe Snowflake user chart label expression."""
    first_last = f"TRIM(COALESCE({alias}.FIRST_NAME, '') || ' ' || COALESCE({alias}.LAST_NAME, ''))"
    return f"COALESCE(NULLIF({first_last}, ''), NULLIF({alias}.DISPLAY_NAME, ''), {alias}.NAME, {fallback_expr}, 'Unknown user')"


def _build_cost_splash_daily_trend_sql(company: str, days: int, *, mart: bool = True) -> str:
    table = _warehouse_hourly_table() if mart else "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
    ts_col = "hour_start" if mart else "start_time"
    company_filter = (
        ""
        if str(company or "").upper() == "ALL"
        else f"AND COMPANY = {sql_literal(company, 100)}"
        if mart
        else get_wh_filter_clause("warehouse_name", company)
    )
    return f"""
        SELECT
            TO_DATE({ts_col}) AS usage_date,
            ROUND(SUM(COALESCE(credits_used, 0)), 4) AS daily_credits
        FROM {table}
        WHERE {ts_col} >= DATEADD('DAY', -{int(days)}, CURRENT_TIMESTAMP())
          AND {ts_col} < CURRENT_TIMESTAMP()
          AND warehouse_name IS NOT NULL
          {company_filter}
        GROUP BY TO_DATE({ts_col})
        ORDER BY usage_date
    """


def _build_cost_monitor_service_trend_sql(days: int, credit_price: float | None = None, ai_credit_price: float | None = None) -> str:
    return build_snowflake_service_cost_trend_sql(days, credit_price, ai_credit_price)


def _build_cost_splash_warehouse_delta_sql(company: str, days: int, *, mart: bool = True) -> str:
    days_int = int(days)
    current_start = f"DATEADD('DAY', -{days_int}, CURRENT_TIMESTAMP())"
    current_end = "CURRENT_TIMESTAMP()"
    prior_start = f"DATEADD('DAY', -{days_int * 2}, CURRENT_TIMESTAMP())"
    prior_end = f"DATEADD('DAY', -{days_int}, CURRENT_TIMESTAMP())"
    if mart:
        return build_mart_bill_warehouse_delta_sql(
            current_start,
            current_end,
            prior_start,
            prior_end,
            company,
        )
    return build_shared_bill_warehouse_delta_live_sql(
        current_start,
        current_end,
        prior_start,
        prior_end,
        company=company,
        include_global_warehouse_filter=False,
    )


def _build_cost_splash_cortex_sql(company: str, days: int, ai_credit_price: float, *, mart: bool = True) -> str:
    days_int = max(int(days), 1)
    ai_credit_rate = safe_float(ai_credit_price, safe_float(DEFAULTS.get("ai_credit_price"), 2.20))
    if mart:
        table = _cortex_daily_table()
        company_filter = (
            ""
            if str(company or "").upper() == "ALL"
            else f"AND UPPER(COALESCE(company, '')) = UPPER({sql_literal(company, 100)})"
        )
        return f"""
            WITH user_rollup AS (
                SELECT
                    COALESCE(NULLIF(user_name, ''), NULLIF(user_id, ''), 'Unknown user') AS stable_user_name,
                    COALESCE(
                        NULLIF(user_chart_label, ''),
                        NULLIF(user_display_name, ''),
                        NULLIF(user_name, ''),
                        NULLIF(user_id, ''),
                        'Unknown user'
                    ) AS user_label,
                    SUM(COALESCE(credits_used, 0)) AS total_credits,
                    SUM(COALESCE(est_cost_usd, COALESCE(credits_used, 0) * {ai_credit_rate})) AS spend_usd,
                    SUM(COALESCE(request_count, 0)) AS requests
                FROM {table}
                WHERE usage_date >= DATEADD('DAY', -{days_int}, CURRENT_DATE())
                  AND usage_date < CURRENT_DATE()
                  {company_filter}
                GROUP BY
                    COALESCE(NULLIF(user_name, ''), NULLIF(user_id, ''), 'Unknown user'),
                    COALESCE(
                        NULLIF(user_chart_label, ''),
                        NULLIF(user_display_name, ''),
                        NULLIF(user_name, ''),
                        NULLIF(user_id, ''),
                        'Unknown user'
                    )
            ),
            totals AS (
                SELECT
                    SUM(total_credits) AS cortex_credits,
                    SUM(spend_usd) AS cortex_spend_usd,
                    SUM(requests) AS cortex_requests
                FROM user_rollup
            ),
            top_user AS (
                SELECT
                    user_label AS top_cortex_user,
                    spend_usd AS top_cortex_user_spend_usd
                FROM user_rollup
                QUALIFY ROW_NUMBER() OVER (ORDER BY spend_usd DESC, user_label) = 1
            )
            SELECT
                ROUND(COALESCE(t.cortex_spend_usd, 0), 2) AS cortex_spend_usd,
                ROUND(COALESCE(t.cortex_credits, 0), 6) AS cortex_credits,
                COALESCE(t.cortex_requests, 0) AS cortex_requests,
                COALESCE(u.top_cortex_user, 'No Cortex user') AS top_cortex_user,
                ROUND(COALESCE(u.top_cortex_user_spend_usd, 0), 2) AS top_cortex_user_spend_usd,
                'Fast Cortex summary' AS cortex_source
            FROM totals t
            LEFT JOIN top_user u ON TRUE
        """

    stable_user_expr = "COALESCE(u.NAME, TO_VARCHAR(c.USER_ID), 'Unknown user')"
    user_expr = _snowflake_user_chart_expr("u", "TO_VARCHAR(c.USER_ID)")
    user_filter = get_user_company_filter_clause("COALESCE(u.NAME, TO_VARCHAR(c.USER_ID), '')", company)
    return f"""
        WITH combined AS (
            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, 'SNOWSIGHT' AS source
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD('DAY', -{days_int}, CURRENT_TIMESTAMP())
              AND USAGE_TIME < CURRENT_TIMESTAMP()
            UNION ALL
            SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, 'CLI' AS source
            FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
            WHERE USAGE_TIME >= DATEADD('DAY', -{days_int}, CURRENT_TIMESTAMP())
              AND USAGE_TIME < CURRENT_TIMESTAMP()
        ),
        user_rollup AS (
            SELECT
                {stable_user_expr} AS stable_user_name,
                {user_expr} AS user_label,
                SUM(COALESCE(c.TOKEN_CREDITS, 0)) AS total_credits,
                SUM(COALESCE(c.TOKEN_CREDITS, 0)) * {ai_credit_rate} AS spend_usd,
                COUNT(*) AS requests
            FROM combined c
            LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON c.USER_ID = u.USER_ID
            WHERE 1=1 {user_filter}
            GROUP BY {stable_user_expr}, {user_expr}
        ),
        totals AS (
            SELECT
                SUM(total_credits) AS cortex_credits,
                SUM(spend_usd) AS cortex_spend_usd,
                SUM(requests) AS cortex_requests
            FROM user_rollup
        ),
        top_user AS (
            SELECT
                user_label AS top_cortex_user,
                spend_usd AS top_cortex_user_spend_usd
            FROM user_rollup
            QUALIFY ROW_NUMBER() OVER (ORDER BY spend_usd DESC, user_label) = 1
        )
        SELECT
            ROUND(COALESCE(t.cortex_spend_usd, 0), 2) AS cortex_spend_usd,
            ROUND(COALESCE(t.cortex_credits, 0), 6) AS cortex_credits,
            COALESCE(t.cortex_requests, 0) AS cortex_requests,
            COALESCE(u.top_cortex_user, 'No Cortex user') AS top_cortex_user,
            ROUND(COALESCE(u.top_cortex_user_spend_usd, 0), 2) AS top_cortex_user_spend_usd,
            'Live fallback: CORTEX_CODE usage history' AS cortex_source
        FROM totals t
        LEFT JOIN top_user u ON TRUE
    """


def _build_resource_monitor_guardrail_sql(
    warehouse_name: str,
    *,
    credit_quota: float,
    monitor_name: str = "",
) -> str:
    wh = safe_identifier(warehouse_name or "TOP_WAREHOUSE")
    quota = max(safe_float(credit_quota), 1.0)
    monitor = safe_identifier(monitor_name or f"OVERWATCH_{wh}_RM")
    return f"""-- Review-only resource monitor guardrail for a user-managed warehouse.
-- Resource monitors are warehouse-only controls; use separate spend thresholds for serverless, shared, and AI costs.
-- Notification email must be enabled/verified in Snowflake user preferences; NOTIFY_USERS accepts Snowflake user names, not email addresses.
USE ROLE ACCOUNTADMIN;

CREATE RESOURCE MONITOR IF NOT EXISTS {monitor}
  WITH CREDIT_QUOTA = {quota:.2f}
       FREQUENCY = MONTHLY
       START_TIMESTAMP = IMMEDIATELY
       TRIGGERS ON 75 PERCENT DO NOTIFY
                ON 90 PERCENT DO SUSPEND
                ON 100 PERCENT DO SUSPEND_IMMEDIATE;

ALTER RESOURCE MONITOR IF EXISTS {monitor}
  SET CREDIT_QUOTA = {quota:.2f};

ALTER WAREHOUSE IF EXISTS {wh}
  SET RESOURCE_MONITOR = {monitor};

SHOW RESOURCE MONITORS;
SHOW WAREHOUSES LIKE {sql_literal(warehouse_name or "TOP_WAREHOUSE", 200)};
"""
