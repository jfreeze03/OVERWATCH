"""Focused mart SQL builders for the storage and pipeline families."""

from __future__ import annotations

from .mart_filters import _mart_company_filter, _mart_environment_filter
from .mart_names import mart_object_name

__all__ = [
    "build_mart_storage_trend_sql",
    "build_mart_storage_db_detail_sql",
    "build_mart_pipeline_freshness_sql",
    "build_mart_pipeline_load_failures_sql",
    "build_mart_pipeline_volume_sql",
]


def build_mart_storage_trend_sql(days_back: int, company: str = "ALFA") -> str:
    """Build storage trend from daily storage facts."""
    table = mart_object_name("FACT_STORAGE_DAILY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            snapshot_date AS usage_date,
            SUM(active_bytes) / POWER(1024, 3) AS storage_gb,
            SUM(failsafe_bytes) / POWER(1024, 3) AS failsafe_gb,
            SUM(COALESCE(stage_bytes, 0)) / POWER(1024, 3) AS stage_gb,
            SUM(COALESCE(hybrid_table_storage_bytes, 0)) / POWER(1024, 3) AS hybrid_storage_gb,
            SUM(COALESCE(archive_storage_cool_bytes, 0)) / POWER(1024, 3) AS archive_cool_gb,
            SUM(COALESCE(archive_storage_cold_bytes, 0)) / POWER(1024, 3) AS archive_cold_gb,
            SUM(
                active_bytes
                + failsafe_bytes
                + retained_for_clone_bytes
                + time_travel_bytes
                + COALESCE(stage_bytes, 0)
                + COALESCE(hybrid_table_storage_bytes, 0)
                + COALESCE(archive_storage_cool_bytes, 0)
                + COALESCE(archive_storage_cold_bytes, 0)
            ) / POWER(1024, 4) AS total_storage_tb,
            SUM(COALESCE(standard_storage_cost_usd, est_cost_usd, 0)) AS standard_storage_cost_usd,
            SUM(COALESCE(hybrid_storage_cost_usd, 0)) AS hybrid_storage_cost_usd,
            SUM(COALESCE(archive_cool_cost_usd, 0)) AS archive_cool_cost_usd,
            SUM(COALESCE(archive_cold_cost_usd, 0)) AS archive_cold_cost_usd,
            SUM(est_cost_usd) AS est_monthly_cost_usd
        FROM {table}
        WHERE snapshot_date >= DATEADD('DAY', -{int(days_back)}, CURRENT_DATE())
          {company_filter}
          {env_filter}
        GROUP BY snapshot_date
        ORDER BY snapshot_date
    """

def build_mart_storage_db_detail_sql(company: str = "ALFA") -> str:
    """Build latest per-database storage detail from daily storage facts."""
    table = mart_object_name("FACT_STORAGE_DAILY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    env_filter_s = _mart_environment_filter("s.database_name", company)
    return f"""
        WITH latest AS (
            SELECT MAX(snapshot_date) AS snapshot_date
            FROM {table}
            WHERE 1 = 1
              {company_filter}
              {env_filter}
        )
        SELECT
            database_name,
            s.snapshot_date AS usage_date,
            active_bytes / POWER(1024, 3) AS database_gb,
            failsafe_bytes / POWER(1024, 3) AS failsafe_gb,
            est_storage_tb,
            est_cost_usd
        FROM {table} s
        JOIN latest l ON s.snapshot_date = l.snapshot_date
        WHERE 1 = 1
          {company_filter}
          {env_filter_s}
        ORDER BY database_gb DESC
        LIMIT 50
    """

def build_mart_pipeline_freshness_sql(stale_hours: int, company: str = "ALFA") -> str:
    """Build stale-table watchlist from the latest table snapshot mart."""
    table = mart_object_name("DIM_TABLE_SNAPSHOT")
    latest_company_filter = _mart_company_filter(company)
    table_company_filter = _mart_company_filter(company).replace("COMPANY", "t.company")
    latest_env_filter = _mart_environment_filter("DATABASE_NAME", company)
    table_env_filter = _mart_environment_filter("t.database_name", company)
    return f"""
        WITH latest AS (
            SELECT MAX(snapshot_ts) AS latest_snapshot_ts
            FROM {table}
            WHERE 1 = 1
              {latest_company_filter}
              {latest_env_filter}
        )
        SELECT
            t.database_name,
            t.schema_name,
            t.table_name,
            t.table_type,
            t.row_count,
            t.bytes / POWER(1024, 3) AS size_gb,
            t.last_altered,
            DATEDIFF('HOUR', t.last_altered, CURRENT_TIMESTAMP()) AS hours_since_change
        FROM {table} t
        JOIN latest l ON t.snapshot_ts = l.latest_snapshot_ts
        WHERE t.last_altered IS NOT NULL
          AND DATEDIFF('HOUR', t.last_altered, CURRENT_TIMESTAMP()) >= {int(stale_hours)}
          {table_company_filter}
          {table_env_filter}
        ORDER BY hours_since_change DESC, size_gb DESC
        LIMIT 300
    """

def build_mart_pipeline_load_failures_sql(load_days: int, company: str = "ALFA") -> str:
    """Build load failure groups from the daily COPY_HISTORY mart."""
    table = mart_object_name("FACT_COPY_LOAD_DAILY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            database_name,
            schema_name,
            table_name,
            status,
            SUM(file_count) AS file_count,
            SUM(row_count) AS row_count,
            SUM(error_count) AS error_count,
            SUM(file_size_bytes) AS file_size_bytes,
            SUM(bytes_billed) AS bytes_billed,
            MAX(last_seen) AS last_seen,
            MAX(latest_error) AS latest_error
        FROM {table}
        WHERE load_date >= DATEADD('DAY', -{int(load_days)}, CURRENT_DATE())
          AND UPPER(COALESCE(status, '')) <> 'LOADED'
          {company_filter}
          {env_filter}
        GROUP BY database_name, schema_name, table_name, status
        ORDER BY file_count DESC, last_seen DESC
        LIMIT 300
    """

def build_mart_pipeline_volume_sql(min_gb: float, company: str = "ALFA") -> str:
    """Build table volume watchlist from the latest table snapshot mart."""
    table = mart_object_name("DIM_TABLE_SNAPSHOT")
    latest_company_filter = _mart_company_filter(company)
    table_company_filter = _mart_company_filter(company).replace("COMPANY", "t.company")
    latest_env_filter = _mart_environment_filter("DATABASE_NAME", company)
    table_env_filter = _mart_environment_filter("t.database_name", company)
    return f"""
        WITH latest AS (
            SELECT MAX(snapshot_ts) AS latest_snapshot_ts
            FROM {table}
            WHERE 1 = 1
              {latest_company_filter}
              {latest_env_filter}
        )
        SELECT
            t.database_name,
            t.schema_name,
            t.table_name,
            t.row_count,
            ROUND(t.bytes / POWER(1024, 3), 2) AS size_gb,
            t.last_altered,
            CASE
                WHEN COALESCE(t.row_count, 0) = 0 AND COALESCE(t.bytes, 0) > 0 THEN 'Storage without rows'
                WHEN DATEDIFF('DAY', t.last_altered, CURRENT_TIMESTAMP()) > 90 THEN 'Large and quiet'
                ELSE 'Active large table'
            END AS watch_reason
        FROM {table} t
        JOIN latest l ON t.snapshot_ts = l.latest_snapshot_ts
        WHERE t.bytes / POWER(1024, 3) >= {float(min_gb or 0)}
          {table_company_filter}
          {table_env_filter}
        ORDER BY size_gb DESC
        LIMIT 300
    """
