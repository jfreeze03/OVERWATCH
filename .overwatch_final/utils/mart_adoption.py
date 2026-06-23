"""Focused mart SQL builders for the adoption family."""

from __future__ import annotations

from .mart_filters import _mart_company_filter, _mart_environment_filter
from .mart_names import mart_object_name

__all__ = [
    "build_mart_adoption_summary_sql",
    "build_mart_adoption_warehouse_size_sql",
    "build_mart_adoption_trend_sql",
    "build_mart_adoption_users_wh_sql",
    "build_mart_adoption_users_db_sql",
    "build_mart_adoption_role_type_sql",
]


def build_mart_adoption_summary_sql(days_back: int, company: str = "ALFA") -> str:
    """Build adoption KPI summary from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COALESCE(SUM(query_count), 0) AS total_queries,
            COUNT(DISTINCT user_name) AS total_users,
            ROUND(COALESCE(SUM(query_count), 0) / NULLIF(COUNT(DISTINCT user_name), 0), 1) AS queries_per_user,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_time_per_query_sec,
            ROUND(100 * COALESCE(SUM(failed_count), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0), 1) AS error_rate
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
    """

def build_mart_adoption_warehouse_size_sql(days_back: int, company: str = "ALFA") -> str:
    """Build adoption by warehouse size from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COALESCE(warehouse_size, 'UNKNOWN') AS warehouse_size,
            COALESCE(SUM(query_count), 0) AS query_count,
            COUNT(DISTINCT user_name) AS users,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY warehouse_size
        ORDER BY query_count DESC
    """

def build_mart_adoption_trend_sql(days_back: int, company: str = "ALFA") -> str:
    """Build daily adoption trend from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            DATE_TRUNC('DAY', hour_start) AS activity_day,
            COALESCE(SUM(query_count), 0) AS total_queries,
            COUNT(DISTINCT user_name) AS users,
            ROUND(COALESCE(SUM(query_count), 0) / NULLIF(COUNT(DISTINCT user_name), 0), 1) AS queries_per_user,
            ROUND(100 * COALESCE(SUM(failed_count), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0), 1) AS error_rate
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY activity_day
        ORDER BY activity_day
    """

def build_mart_adoption_users_wh_sql(days_back: int, company: str = "ALFA") -> str:
    """Build users per warehouse from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            warehouse_name,
            COUNT(DISTINCT user_name) AS users,
            COALESCE(SUM(query_count), 0) AS query_count,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY warehouse_name
        ORDER BY users DESC, query_count DESC
        LIMIT 50
    """

def build_mart_adoption_users_db_sql(days_back: int, company: str = "ALFA") -> str:
    """Build users per database from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COALESCE(database_name, 'UNKNOWN') AS database_name,
            COUNT(DISTINCT user_name) AS users,
            COALESCE(SUM(query_count), 0) AS query_count,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY database_name
        ORDER BY users DESC, query_count DESC
        LIMIT 50
    """

def build_mart_adoption_role_type_sql(days_back: int, company: str = "ALFA") -> str:
    """Build role/query-type mix from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COALESCE(role_name, 'UNKNOWN') AS role_name,
            COALESCE(query_type, 'UNKNOWN') AS query_type,
            COALESCE(SUM(query_count), 0) AS query_count,
            COUNT(DISTINCT user_name) AS users,
            ROUND(100 * COALESCE(SUM(failed_count), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0), 1) AS error_rate
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY role_name, query_type
        ORDER BY query_count DESC
        LIMIT 100
    """
