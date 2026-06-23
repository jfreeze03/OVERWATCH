"""Focused mart SQL builders for the warehouse health family."""

from __future__ import annotations

from .mart_filters import (
    _mart_company_filter,
    _mart_database_filter,
    _mart_text_filter,
    _mart_window_condition,
    _mart_window_filter,
)
from .mart_names import mart_object_name

__all__ = [
    "build_mart_warehouse_overview_sql",
    "build_mart_warehouse_heatmap_sql",
    "build_mart_warehouse_scaling_sql",
]


def build_mart_warehouse_overview_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build a warehouse health overview from hourly summary facts.

    The mart does not store query cache percentage, so callers should label
    cache as unavailable/estimated instead of an exact live fact.
    """
    query_table = mart_object_name("FACT_QUERY_HOURLY")
    warehouse_table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    query_window = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    credit_window = _mart_window_condition("HOUR_START", days_back, start_date, end_date)
    prior_start = f"DATEADD('DAY', -{int(days_back) * 2}, CURRENT_TIMESTAMP())"
    prior_end = f"DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())"
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        WITH query_rollup AS (
            SELECT
                warehouse_name,
                MAX(warehouse_size) AS warehouse_size,
                SUM(query_count) AS total_queries,
                ROUND(SUM(total_elapsed_ms) / NULLIF(SUM(query_count), 0) / 1000, 3) AS avg_elapsed_sec,
                ROUND(MAX(p95_execution_ms) / 1000, 3) AS p95_elapsed_sec,
                ROUND(SUM(total_queued_ms) / NULLIF(SUM(query_count), 0) / 1000, 3) AS avg_queued_sec,
                ROUND(SUM(total_spill_bytes) / POWER(1024, 3), 3) AS total_remote_spill_gb,
                NULL::FLOAT AS avg_cache_pct,
                SUM(failed_count) AS error_count,
                ROUND(SUM(total_bytes_scanned) / POWER(1024, 3), 3) AS total_gb_scanned
            FROM {query_table}
            WHERE warehouse_name IS NOT NULL
              {company_filter}
              {query_window}
              {wh_filter}
              {user_filter}
              {role_filter}
              {db_filter}
            GROUP BY warehouse_name
        ),
        credit_rollup AS (
            SELECT
                warehouse_name,
                ROUND(SUM(IFF({credit_window}, COALESCE(credits_used, 0), 0)), 4) AS metered_credits,
                ROUND(SUM(IFF(HOUR_START >= {prior_start} AND HOUR_START < {prior_end}, COALESCE(credits_used, 0), 0)), 4) AS prior_metered_credits,
                ROUND(
                    SUM(IFF({credit_window}, COALESCE(credits_used, 0), 0))
                    - SUM(IFF(HOUR_START >= {prior_start} AND HOUR_START < {prior_end}, COALESCE(credits_used, 0), 0)),
                    4
                ) AS credit_delta,
                ROUND(
                    (
                        SUM(IFF({credit_window}, COALESCE(credits_used, 0), 0))
                        - SUM(IFF(HOUR_START >= {prior_start} AND HOUR_START < {prior_end}, COALESCE(credits_used, 0), 0))
                    ) / NULLIF(SUM(IFF(HOUR_START >= {prior_start} AND HOUR_START < {prior_end}, COALESCE(credits_used, 0), 0)), 0) * 100,
                    1
                ) AS credit_delta_pct,
                ROUND(SUM(IFF({credit_window}, COALESCE(credits_used_compute, 0), 0)), 4) AS credits_used_compute,
                ROUND(SUM(IFF({credit_window}, COALESCE(credits_used_cloud_services, 0), 0)), 4) AS credits_used_cloud_services,
                MAX(load_ts) AS mart_load_ts
            FROM {warehouse_table}
            WHERE warehouse_name IS NOT NULL
              AND HOUR_START >= {prior_start}
              {company_filter}
              {wh_filter}
            GROUP BY warehouse_name
        )
        SELECT
            q.warehouse_name,
            q.warehouse_size,
            q.total_queries,
            q.avg_elapsed_sec,
            q.p95_elapsed_sec,
            q.avg_queued_sec,
            q.total_remote_spill_gb,
            q.avg_cache_pct,
            q.error_count,
            q.total_gb_scanned,
            COALESCE(c.metered_credits, 0) AS metered_credits,
            COALESCE(c.prior_metered_credits, 0) AS prior_metered_credits,
            COALESCE(c.credit_delta, 0) AS credit_delta,
            c.credit_delta_pct,
            COALESCE(c.credits_used_compute, 0) AS credits_used_compute,
            COALESCE(c.credits_used_cloud_services, 0) AS credits_used_cloud_services,
            c.mart_load_ts
        FROM query_rollup q
        LEFT JOIN credit_rollup c ON q.warehouse_name = c.warehouse_name
        ORDER BY q.total_queries DESC, COALESCE(c.metered_credits, 0) DESC
    """

def build_mart_warehouse_heatmap_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build a warehouse heatmap from the hourly query mart."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        SELECT
            warehouse_name,
            DAYOFWEEK(HOUR_START) AS day_of_week,
            HOUR(HOUR_START) AS hour_of_day,
            SUM(query_count) AS query_count,
            ROUND(
                COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000,
                2
            ) AS avg_elapsed_sec
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          {company_filter}
          {window_filter}
          {wh_filter}
          {user_filter}
          {role_filter}
          {db_filter}
        GROUP BY warehouse_name, day_of_week, hour_of_day
        ORDER BY warehouse_name, day_of_week, hour_of_day
    """

def build_mart_warehouse_scaling_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build a lightweight scaling/metering event list from the warehouse mart."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    return f"""
        SELECT
            warehouse_name,
            NULL::VARCHAR AS warehouse_size,
            hour_start AS start_time,
            DATEADD('HOUR', 1, hour_start) AS end_time,
            credits_used,
            credits_used_compute,
            credits_used_cloud_services,
            load_ts AS mart_load_ts
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          {company_filter}
          {window_filter}
          {wh_filter}
        ORDER BY credits_used DESC, start_time DESC
        LIMIT 200
    """
