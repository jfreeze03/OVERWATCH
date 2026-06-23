"""Focused mart SQL builders for the usage family."""

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
    "build_mart_usage_overview_sql",
    "build_mart_usage_metering_sql",
    "build_mart_usage_storage_sql",
    "build_mart_usage_pressure_sql",
    "build_mart_usage_cost_drivers_sql",
    "build_mart_usage_query_mix_sql",
    "build_mart_usage_database_adoption_sql",
]


def build_mart_usage_overview_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build top-level Usage Overview KPI SQL from the hourly query mart."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        SELECT
            COALESCE(SUM(query_count), 0) AS total_queries,
            COUNT(DISTINCT user_name) AS total_users,
            COUNT(DISTINCT database_name) AS active_databases,
            ROUND(
                100 * (COALESCE(SUM(query_count), 0) - COALESCE(SUM(failed_count), 0))
                / NULLIF(COALESCE(SUM(query_count), 0), 0),
                1
            ) AS query_success_rate,
            COALESCE(SUM(failed_count), 0) AS failed_queries,
            COALESCE(SUM(IFF(total_queued_ms > 0, query_count, 0)), 0) AS queued_queries,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec,
            ROUND(
                COALESCE(SUM(avg_execution_ms * query_count), 0)
                / NULLIF(COALESCE(SUM(query_count), 0), 0)
                / 1000,
                2
            ) AS avg_execution_sec,
            0::FLOAT AS cloud_service_credits
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          {company_filter}
          {window_filter}
          {wh_filter}
          {user_filter}
          {role_filter}
          {db_filter}
    """

def build_mart_usage_metering_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build Usage Overview credit KPI SQL from the hourly warehouse mart."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    current_window = _mart_window_condition("HOUR_START", days_back, start_date, end_date)
    prior_start = f"DATEADD('DAY', -{int(days_back) * 2}, CURRENT_TIMESTAMP())"
    prior_end = f"DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())"
    return f"""
        SELECT
            ROUND(SUM(IFF({current_window}, COALESCE(credits_used, 0), 0)), 4) AS total_credits,
            ROUND(SUM(IFF(HOUR_START >= {prior_start} AND HOUR_START < {prior_end}, COALESCE(credits_used, 0), 0)), 4) AS prior_credits,
            ROUND(SUM(IFF({current_window}, COALESCE(credits_used_compute, 0), 0)), 4) AS compute_credits,
            ROUND(SUM(IFF({current_window}, COALESCE(credits_used_cloud_services, 0), 0)), 4) AS warehouse_cloud_credits
        FROM {table}
        WHERE HOUR_START >= {prior_start}
          {company_filter}
          {wh_filter}
    """

def build_mart_usage_storage_sql(
    days_back: int,
    company: str = "ALFA",
    database_contains: str = "",
) -> str:
    """Build Usage Overview storage KPIs from daily storage facts."""
    table = mart_object_name("FACT_STORAGE_DAILY")
    company_filter = _mart_company_filter(company)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    span_days = max(14, int(days_back) * 2)
    return f"""
        WITH scoped AS (
            SELECT database_name, active_bytes, failsafe_bytes, snapshot_date
            FROM {table}
            WHERE snapshot_date >= DATEADD('DAY', -{span_days}, CURRENT_DATE())
              {company_filter}
              {db_filter}
        ),
        current_latest AS (
            SELECT
                database_name,
                active_bytes,
                failsafe_bytes,
                ROW_NUMBER() OVER (PARTITION BY database_name ORDER BY snapshot_date DESC) AS rn
            FROM scoped
        ),
        prior_latest AS (
            SELECT
                database_name,
                active_bytes,
                ROW_NUMBER() OVER (PARTITION BY database_name ORDER BY snapshot_date DESC) AS rn
            FROM scoped
            WHERE snapshot_date <= DATEADD('DAY', -{int(days_back)}, CURRENT_DATE())
        )
        SELECT
            ROUND(SUM(COALESCE(c.active_bytes, 0)) / POWER(1024, 4), 3) AS active_storage_tb,
            ROUND(SUM(COALESCE(c.failsafe_bytes, 0)) / POWER(1024, 4), 3) AS failsafe_storage_tb,
            ROUND(SUM(COALESCE(p.active_bytes, 0)) / POWER(1024, 4), 3) AS prior_active_storage_tb
        FROM current_latest c
        LEFT JOIN prior_latest p
          ON c.database_name = p.database_name
         AND p.rn = 1
        WHERE c.rn = 1
    """

def build_mart_usage_pressure_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build Usage Overview warehouse pressure SQL from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        WITH wh AS (
            SELECT
                warehouse_name,
                SUM(query_count) AS total_queries,
                SUM(failed_count) AS failed_queries,
                SUM(total_queued_ms) AS queued_ms,
                SUM(total_spill_bytes) / POWER(1024, 3) AS remote_spill_gb
            FROM {table}
            WHERE warehouse_name IS NOT NULL
              {company_filter}
              {window_filter}
              {wh_filter}
              {user_filter}
              {role_filter}
              {db_filter}
            GROUP BY warehouse_name
        )
        SELECT
            COUNT(*) AS active_warehouses,
            SUM(IFF(queued_ms > 0 OR remote_spill_gb > 1 OR failed_queries > 0, 1, 0)) AS pressure_warehouses
        FROM wh
    """

def build_mart_usage_cost_drivers_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build top warehouse cost drivers and prior-period movement from hourly warehouse facts."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    current_window = _mart_window_condition("HOUR_START", days_back, start_date, end_date)
    prior_start = f"DATEADD('DAY', -{int(days_back) * 2}, CURRENT_TIMESTAMP())"
    prior_end = f"DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())"
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    return f"""
        SELECT
            warehouse_name,
            ROUND(SUM(IFF({current_window}, COALESCE(credits_used, 0), 0)), 4) AS total_credits,
            ROUND(SUM(IFF(HOUR_START >= {prior_start} AND HOUR_START < {prior_end}, COALESCE(credits_used, 0), 0)), 4) AS prior_credits,
            ROUND(
                SUM(IFF({current_window}, COALESCE(credits_used, 0), 0))
                - SUM(IFF(HOUR_START >= {prior_start} AND HOUR_START < {prior_end}, COALESCE(credits_used, 0), 0)),
                4
            ) AS credit_delta,
            ROUND(
                (
                    SUM(IFF({current_window}, COALESCE(credits_used, 0), 0))
                    - SUM(IFF(HOUR_START >= {prior_start} AND HOUR_START < {prior_end}, COALESCE(credits_used, 0), 0))
                ) / NULLIF(SUM(IFF(HOUR_START >= {prior_start} AND HOUR_START < {prior_end}, COALESCE(credits_used, 0), 0)), 0) * 100,
                1
            ) AS credit_delta_pct,
            ROUND(SUM(IFF({current_window}, COALESCE(credits_used_compute, 0), 0)), 4) AS compute_credits,
            ROUND(SUM(IFF({current_window}, COALESCE(credits_used_cloud_services, 0), 0)), 4) AS cloud_credits
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          AND HOUR_START >= {prior_start}
          {company_filter}
          {wh_filter}
        GROUP BY warehouse_name
        ORDER BY credit_delta DESC, total_credits DESC
        LIMIT 20
    """

def build_mart_usage_query_mix_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build query type mix from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        SELECT
            COALESCE(query_type, 'UNKNOWN') AS query_type,
            COALESCE(SUM(query_count), 0) AS query_count,
            COUNT(DISTINCT user_name) AS users,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec,
            COALESCE(SUM(failed_count), 0) AS failed_queries
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          {company_filter}
          {window_filter}
          {wh_filter}
          {user_filter}
          {role_filter}
          {db_filter}
        GROUP BY query_type
        ORDER BY query_count DESC
        LIMIT 25
    """

def build_mart_usage_database_adoption_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build database adoption from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        SELECT
            COALESCE(database_name, 'UNKNOWN') AS database_name,
            COUNT(DISTINCT user_name) AS users,
            COALESCE(SUM(query_count), 0) AS query_count
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          {company_filter}
          {window_filter}
          {wh_filter}
          {user_filter}
          {role_filter}
          {db_filter}
        GROUP BY database_name
        ORDER BY users DESC, query_count DESC
        LIMIT 20
    """
