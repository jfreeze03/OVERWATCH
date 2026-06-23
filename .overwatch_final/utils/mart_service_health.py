"""Focused mart SQL builders for the service health family."""

from __future__ import annotations

from .mart_filters import _mart_company_filter, _mart_environment_filter
from .mart_names import mart_object_name

__all__ = [
    "build_mart_service_query_health_sql",
    "build_mart_service_warehouse_health_sql",
    "build_mart_service_login_health_sql",
    "build_mart_service_task_health_sql",
]


def build_mart_service_query_health_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build service-health query processor summary from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COALESCE(SUM(query_count), 0) AS total_queries,
            COALESCE(SUM(failed_count), 0) AS failed_queries,
            COALESCE(SUM(IFF(total_queued_ms > 0, query_count, 0)), 0) AS queued_queries,
            0::NUMBER AS blocked_queries,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec,
            ROUND(MAX(p95_execution_ms) / 1000, 2) AS p95_elapsed_sec
        FROM {table}
        WHERE hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
    """

def build_mart_service_warehouse_health_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build service-health warehouse pressure detail from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            warehouse_name,
            MAX(warehouse_size) AS warehouse_size,
            COALESCE(SUM(query_count), 0) AS total_queries,
            COALESCE(SUM(failed_count), 0) AS failed_queries,
            ROUND(COALESCE(SUM(total_queued_ms), 0) / 1000, 2) AS queued_sec,
            ROUND(COALESCE(SUM(total_spill_bytes), 0) / POWER(1024, 3), 2) AS remote_spill_gb,
            NULL::FLOAT AS avg_cache_pct
        FROM {table}
        WHERE hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY warehouse_name
        ORDER BY queued_sec DESC, remote_spill_gb DESC, failed_queries DESC
        LIMIT 100
    """

def build_mart_service_login_health_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build service-health login summary from daily login facts."""
    table = mart_object_name("FACT_LOGIN_DAILY")
    company_filter = _mart_company_filter(company)
    days = max(1, int((int(hours_back) + 23) / 24))
    return f"""
        SELECT
            COALESCE(SUM(success_count), 0) + COALESCE(SUM(failure_count), 0) AS login_events,
            COALESCE(SUM(failure_count), 0) AS failed_logins,
            COUNT(DISTINCT user_name) AS login_users,
            COUNT(DISTINCT client_ip) AS distinct_ips
        FROM {table}
        WHERE login_date >= DATEADD('DAY', -{days}, CURRENT_DATE())
          {company_filter}
    """

def build_mart_service_task_health_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build service-health task summary from task run facts."""
    table = mart_object_name("FACT_TASK_RUN")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COUNT(*) AS task_runs,
            COALESCE(SUM(IFF(UPPER(COALESCE(state, '')) IN ('FAILED', 'FAILED_WITH_ERROR'), 1, 0)), 0) AS failed_tasks,
            COALESCE(SUM(IFF(UPPER(COALESCE(state, '')) IN ('SUCCEEDED', 'SUCCESS'), 1, 0)), 0) AS succeeded_tasks,
            COUNT(DISTINCT task_name) AS distinct_tasks
        FROM {table}
        WHERE scheduled_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          {company_filter}
          {env_filter}
    """
