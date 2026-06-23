"""Focused mart SQL builders for the account health family."""

from __future__ import annotations

from .mart_filters import _mart_company_filter, _mart_environment_filter
from .mart_names import mart_object_name

__all__ = [
    "build_mart_account_health_storage_sql",
    "build_mart_account_health_cost_drivers_sql",
    "build_mart_account_health_change_sql",
    "build_mart_account_health_failure_types_sql",
    "build_mart_account_health_long_queries_sql",
    "build_mart_account_health_credits_sql",
    "build_mart_account_health_failure_count_sql",
    "build_mart_account_health_top_driver_sql",
    "build_mart_account_health_queued_sql",
    "build_mart_account_health_ytd_credits_sql",
]


def build_mart_account_health_storage_sql(company: str = "ALFA") -> str:
    """Build Account Health latest storage KPI from daily storage facts."""
    table = mart_object_name("FACT_STORAGE_DAILY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "s.company")
    latest_filter = _mart_company_filter(company).replace("COMPANY", "company")
    latest_env_filter = _mart_environment_filter("database_name", company)
    env_filter = _mart_environment_filter("s.database_name", company)
    return f"""
        WITH latest AS (
            SELECT MAX(snapshot_date) AS snapshot_date
            FROM {table}
            WHERE 1 = 1
              {latest_filter}
              {latest_env_filter}
        )
        SELECT
            COALESCE(ROUND(SUM(COALESCE(s.est_storage_tb, 0)), 2), 0) AS storage_tb
        FROM {table} s
        JOIN latest l ON s.snapshot_date = l.snapshot_date
        WHERE 1 = 1
          {company_filter}
          {env_filter}
    """

def build_mart_account_health_cost_drivers_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build Account Health top cost drivers from fast summary facts.

    This returns the legacy Account Health column names so the UI can remain
    stable while the source moves from live ACCOUNT_USAGE to preloaded facts.
    """
    q_table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    wh_table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter_q = _mart_company_filter(company).replace("COMPANY", "q.company")
    company_filter_wh = _mart_company_filter(company).replace("COMPANY", "w.company")
    env_filter_q = _mart_environment_filter("q.database_name", company)
    return f"""
        WITH wh_credits AS (
            SELECT
                warehouse_name,
                SUM(COALESCE(credits_used, 0)) AS warehouse_credits
            FROM {wh_table} w
            WHERE w.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
              {company_filter_wh}
            GROUP BY warehouse_name
        ),
        wh_elapsed AS (
            SELECT
                q.warehouse_name,
                SUM(COALESCE(q.total_elapsed_time, 0)) AS wh_elapsed_ms
            FROM {q_table} q
            WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {company_filter_q}
            GROUP BY q.warehouse_name
        ),
        query_work AS (
            SELECT
                q.user_name,
                q.warehouse_name,
                MAX(q.warehouse_size) AS warehouse_size,
                COUNT(*) AS query_count,
                SUM(COALESCE(q.total_elapsed_time, 0)) AS elapsed_ms,
                SUM(COALESCE(q.bytes_scanned, 0)) AS bytes_scanned
            FROM {q_table} q
            WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {company_filter_q}
              {env_filter_q}
            GROUP BY q.user_name, q.warehouse_name
        )
        SELECT
            qw.user_name,
            qw.warehouse_name,
            qw.warehouse_size,
            qw.query_count,
            ROUND(COALESCE(wc.warehouse_credits, 0) * qw.elapsed_ms / NULLIF(we.wh_elapsed_ms, 0), 4) AS total_credits,
            ROUND(qw.bytes_scanned / POWER(1024, 3), 2) AS gb_scanned
        FROM query_work qw
        LEFT JOIN wh_credits wc ON qw.warehouse_name = wc.warehouse_name
        LEFT JOIN wh_elapsed we ON qw.warehouse_name = we.warehouse_name
        WHERE COALESCE(wc.warehouse_credits, 0) > 0
        ORDER BY total_credits DESC, gb_scanned DESC
        LIMIT 5
    """

def build_mart_account_health_change_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build Account Health what-changed deltas from hourly query and warehouse facts."""
    query_table = mart_object_name("FACT_QUERY_HOURLY")
    warehouse_table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter_q = _mart_company_filter(company).replace("COMPANY", "q.company")
    company_filter_w = _mart_company_filter(company).replace("COMPANY", "w.company")
    env_filter_q = _mart_environment_filter("q.database_name", company)
    return f"""
        WITH query_periods AS (
            SELECT
                CASE
                    WHEN q.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP()) THEN 'CURRENT'
                    ELSE 'PRIOR'
                END AS period,
                SUM(COALESCE(q.query_count, 0)) AS queries,
                SUM(COALESCE(q.failed_count, 0)) AS failures
            FROM {query_table} q
            WHERE q.hour_start >= DATEADD('HOUR', -{int(hours_back * 2)}, CURRENT_TIMESTAMP())
              AND q.hour_start < CURRENT_TIMESTAMP()
              {company_filter_q}
              {env_filter_q}
            GROUP BY period
        ),
        credit_periods AS (
            SELECT
                CASE
                    WHEN w.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP()) THEN 'CURRENT'
                    ELSE 'PRIOR'
                END AS period,
                SUM(COALESCE(w.credits_used, 0)) AS credits
            FROM {warehouse_table} w
            WHERE w.hour_start >= DATEADD('HOUR', -{int(hours_back * 2)}, CURRENT_TIMESTAMP())
              AND w.hour_start < CURRENT_TIMESTAMP()
              {company_filter_w}
            GROUP BY period
        )
        SELECT
            COALESCE(MAX(IFF(q.period = 'CURRENT', q.queries, NULL)), 0)
              - COALESCE(MAX(IFF(q.period = 'PRIOR', q.queries, NULL)), 0) AS query_delta,
            ROUND(
                COALESCE(MAX(IFF(c.period = 'CURRENT', c.credits, NULL)), 0)
                - COALESCE(MAX(IFF(c.period = 'PRIOR', c.credits, NULL)), 0),
                4
            ) AS credit_delta,
            COALESCE(MAX(IFF(q.period = 'CURRENT', q.failures, NULL)), 0)
              - COALESCE(MAX(IFF(q.period = 'PRIOR', q.failures, NULL)), 0) AS failure_delta
        FROM query_periods q
        FULL OUTER JOIN credit_periods c ON q.period = c.period
    """

def build_mart_account_health_failure_types_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build Morning Report failure groups from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            q.query_type,
            SUM(COALESCE(q.failed_count, 0)) AS fail_count,
            COUNT(DISTINCT IFF(COALESCE(q.failed_count, 0) > 0, q.user_name, NULL)) AS affected_users,
            COUNT(DISTINCT IFF(COALESCE(q.failed_count, 0) > 0, q.warehouse_name, NULL)) AS affected_wh
        FROM {table} q
        WHERE q.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND COALESCE(q.failed_count, 0) > 0
          {company_filter}
          {env_filter}
        GROUP BY q.query_type
        ORDER BY fail_count DESC
    """

def build_mart_account_health_long_queries_sql(hours_back: int, company: str = "ALFA", limit: int = 10) -> str:
    """Build Morning Report long-query watchlist from recent query details."""
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            q.query_id,
            q.user_name,
            q.warehouse_name,
            SUBSTR(COALESCE(q.query_text, ''), 1, 100) AS query_preview,
            COALESCE(q.total_elapsed_time, 0) / 1000 AS elapsed_sec,
            q.execution_status
        FROM {table} q
        WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        ORDER BY COALESCE(q.total_elapsed_time, 0) DESC
        LIMIT {int(limit)}
    """

def build_mart_account_health_credits_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build period/prior-period credit totals for Account Health briefings."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "w.company")
    return f"""
        SELECT
            SUM(CASE WHEN w.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
                      AND w.hour_start < CURRENT_TIMESTAMP()
                     THEN COALESCE(w.credits_used, 0) ELSE 0 END) AS period_credits,
            SUM(CASE WHEN w.hour_start >= DATEADD('HOUR', -{int(hours_back * 2)}, CURRENT_TIMESTAMP())
                      AND w.hour_start < DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
                     THEN COALESCE(w.credits_used, 0) ELSE 0 END) AS prior_period_credits,
            SUM(CASE WHEN w.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
                      AND w.hour_start < CURRENT_TIMESTAMP()
                     THEN COALESCE(w.credits_used, 0) ELSE 0 END) AS overnight_credits
        FROM {table} w
        WHERE w.hour_start >= DATEADD('HOUR', -{int(hours_back * 2)}, CURRENT_TIMESTAMP())
          AND w.hour_start < CURRENT_TIMESTAMP()
          {company_filter}
    """

def build_mart_account_health_failure_count_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build query failure count for Account Health briefings."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            COALESCE(SUM(q.failed_count), 0) AS fail_count
        FROM {table} q
        WHERE q.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          {company_filter}
          {env_filter}
    """

def build_mart_account_health_top_driver_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build top cost driver for Account Health executive briefing."""
    base_sql = build_mart_account_health_cost_drivers_sql(hours_back, company)
    return f"""
        WITH drivers AS (
            {base_sql}
        )
        SELECT
            user_name,
            warehouse_name,
            total_credits AS credits
        FROM drivers
        ORDER BY credits DESC
        LIMIT 1
    """

def build_mart_account_health_queued_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build queued query count for Account Health briefing inputs."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            COALESCE(SUM(IFF(COALESCE(q.total_queued_ms, 0) > 0, q.query_count, 0)), 0) AS queued
        FROM {table} q
        WHERE q.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          {company_filter}
          {env_filter}
    """

def build_mart_account_health_ytd_credits_sql(company: str = "ALFA") -> str:
    """Build YTD credits from warehouse hourly summaries for contract pacing."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "w.company")
    return f"""
        SELECT
            COALESCE(SUM(w.credits_used), 0) AS ytd_credits
        FROM {table} w
        WHERE w.hour_start >= DATE_TRUNC('YEAR', CURRENT_DATE())
          AND w.hour_start < DATEADD('HOUR', -24, CURRENT_TIMESTAMP())
          {company_filter}
    """
