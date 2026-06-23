"""Focused mart SQL builders for recommendation and query insight families."""

from __future__ import annotations

from .mart_filters import _mart_company_filter, _mart_environment_filter
from .mart_names import mart_object_name

__all__ = [
    "build_mart_recommendation_idle_sql",
    "build_mart_recommendation_spill_sql",
    "build_mart_recommendation_failed_tasks_sql",
    "build_mart_recommendation_query_errors_sql",
    "build_mart_query_bottleneck_sql",
    "build_mart_query_degradation_sql",
]


def build_mart_recommendation_idle_sql(company: str = "ALFA") -> str:
    """Build idle warehouse recommendation candidates from hourly summary facts."""
    wh_table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    q_table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    query_env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        WITH wh AS (
            SELECT
                hour_start,
                company,
                warehouse_name,
                SUM(COALESCE(credits_used, 0)) AS credits_used
            FROM {wh_table}
            WHERE hour_start >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
              AND warehouse_name IS NOT NULL
              AND COALESCE(credits_used, 0) > 0
              {company_filter}
            GROUP BY hour_start, company, warehouse_name
        ),
        q AS (
            SELECT
                hour_start,
                company,
                warehouse_name,
                SUM(COALESCE(query_count, 0)) AS query_count
            FROM {q_table}
            WHERE hour_start >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
              AND warehouse_name IS NOT NULL
              {company_filter}
              {query_env_filter}
            GROUP BY hour_start, company, warehouse_name
        )
        SELECT
            wh.warehouse_name,
            COUNT(*) AS idle_hours,
            ROUND(SUM(wh.credits_used), 6) AS idle_credits
        FROM wh
        LEFT JOIN q
            ON wh.hour_start = q.hour_start
           AND wh.company = q.company
           AND wh.warehouse_name = q.warehouse_name
        WHERE COALESCE(q.query_count, 0) = 0
        GROUP BY wh.warehouse_name
        HAVING idle_credits >= 1
        ORDER BY idle_credits DESC
        LIMIT 10
    """

def build_mart_recommendation_spill_sql(company: str = "ALFA") -> str:
    """Build remote spill recommendation candidates from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            warehouse_name,
            MAX(warehouse_size) AS warehouse_size,
            ROUND(SUM(COALESCE(total_spill_bytes, 0)) / POWER(1024, 3), 2) AS remote_gb
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY warehouse_name
        HAVING remote_gb > 5
        ORDER BY remote_gb DESC
        LIMIT 10
    """

def build_mart_recommendation_failed_tasks_sql(company: str = "ALFA") -> str:
    """Build task failure recommendation candidates from task run facts."""
    table = mart_object_name("FACT_TASK_RUN")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            task_name,
            COUNT(*) AS failures
        FROM {table}
        WHERE scheduled_time >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
          AND UPPER(COALESCE(state, '')) IN ('FAILED', 'FAILED_WITH_ERROR')
          {company_filter}
          {env_filter}
        GROUP BY task_name
        HAVING failures > 3
        ORDER BY failures DESC
        LIMIT 5
    """

def build_mart_recommendation_query_errors_sql(company: str = "ALFA", min_failures: int = 10) -> str:
    """Build query failure recommendation candidates from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            warehouse_name,
            SUM(COALESCE(failed_count, 0)) AS failures
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY warehouse_name
        HAVING failures > {int(min_failures)}
        ORDER BY failures DESC
        LIMIT 5
    """

def build_mart_query_bottleneck_sql(
    days_back: int,
    min_elapsed_ms: int,
    company: str = "ALFA",
    extra_filter: str = "",
) -> str:
    """Build Query Analysis bottleneck rows from recent query-detail mart."""
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            q.query_id,
            q.user_name,
            q.warehouse_name,
            q.warehouse_size,
            q.execution_status,
            q.start_time,
            COALESCE(q.total_elapsed_time, 0) / 1000 AS elapsed_sec,
            COALESCE(q.compilation_time, 0) / 1000 AS compile_sec,
            COALESCE(q.execution_time, 0) / 1000 AS exec_sec,
            (
                COALESCE(q.queued_overload_time, 0)
              + COALESCE(q.queued_provisioning_time, 0)
              + COALESCE(q.queued_repair_time, 0)
            ) / 1000 AS queued_sec,
            COALESCE(q.bytes_scanned, 0) / POWER(1024, 3) AS gb_scanned,
            COALESCE(q.bytes_spilled_to_remote_storage, 0) / POWER(1024, 3) AS remote_spill_gb,
            COALESCE(q.partitions_scanned, 0) * 100.0 / NULLIF(COALESCE(q.partitions_total, 0), 0) AS partition_pct,
            COALESCE(q.rows_produced, 0) AS rows_produced,
            0::FLOAT AS metered_credits,
            SUBSTR(COALESCE(q.query_text, ''), 1, 500) AS query_text
        FROM {table} q
        WHERE q.start_time >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND COALESCE(q.total_elapsed_time, 0) > {int(min_elapsed_ms)}
          {company_filter}
          {env_filter}
          {extra_filter}
        ORDER BY q.total_elapsed_time DESC
        LIMIT 500
    """

def build_mart_query_degradation_sql(company: str = "ALFA", extra_filter: str = "") -> str:
    """Build query-pattern degradation rows from recent query-detail mart."""
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        WITH base AS (
            SELECT
                COALESCE(q.query_hash, SUBSTR(q.query_text, 1, 200)) AS sig,
                q.start_time,
                q.total_elapsed_time
            FROM {table} q
            WHERE q.start_time >= DATEADD('DAY', -14, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {company_filter}
              {env_filter}
              {extra_filter}
        ),
        sig_recent AS (
            SELECT sig,
                   AVG(total_elapsed_time) / 1000 AS avg_sec,
                   COUNT(*) AS cnt
            FROM base
            WHERE start_time >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
            GROUP BY sig
            HAVING cnt >= 5
        ),
        sig_prior AS (
            SELECT sig,
                   AVG(total_elapsed_time) / 1000 AS avg_sec,
                   COUNT(*) AS cnt
            FROM base
            WHERE start_time < DATEADD('DAY', -7, CURRENT_TIMESTAMP())
            GROUP BY sig
            HAVING cnt >= 5
        )
        SELECT
            r.sig,
            r.avg_sec AS recent_sec,
            p.avg_sec AS prior_sec,
            ROUND((r.avg_sec - p.avg_sec) / NULLIF(p.avg_sec, 0) * 100, 1) AS pct_change
        FROM sig_recent r
        JOIN sig_prior p ON r.sig = p.sig
        WHERE r.avg_sec > p.avg_sec * 1.25
          AND r.avg_sec > 5
        ORDER BY pct_change DESC
        LIMIT 50
    """
