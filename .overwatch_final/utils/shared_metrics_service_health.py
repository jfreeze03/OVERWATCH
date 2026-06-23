"""Shared service-health metric loaders."""

from __future__ import annotations

import pandas as pd

from .company_filter import (
    get_active_company,
    get_combined_filter_clause,
    get_company_scope_key,
    get_db_filter_clause,
    get_environment_filter_clause,
    get_user_company_filter_clause,
)
from .compatibility import build_task_health_sql, filter_existing_columns
from .mart import (
    build_mart_service_login_health_sql,
    build_mart_service_query_health_sql,
    build_mart_service_task_health_sql,
    build_mart_service_warehouse_health_sql,
)
from .query import run_query
from .shared_metrics_cache import _load_or_reuse
from .shared_metrics_contracts import SharedMetricResult

def _first_numeric_value(df: pd.DataFrame, column: str) -> float:
    if df is None or df.empty or column not in df.columns:
        return 0.0
    try:
        return float(pd.to_numeric(df.get(column), errors="coerce").fillna(0).iloc[0])
    except Exception:
        return 0.0


def _service_query_history_exprs(session: object) -> dict[str, str]:
    """Return Service Health QUERY_HISTORY expressions across Snowflake versions."""
    qh_cols = set(
        filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            [
                "ERROR_CODE",
                "WAREHOUSE_SIZE",
                "QUEUED_OVERLOAD_TIME",
                "TRANSACTION_BLOCKED_TIME",
                "BYTES_SPILLED_TO_REMOTE_STORAGE",
                "PERCENTAGE_SCANNED_FROM_CACHE",
            ],
        )
    )
    return {
        "error_pred": (
            "q.error_code IS NOT NULL"
            if "ERROR_CODE" in qh_cols
            else "UPPER(q.execution_status) = 'FAILED_WITH_ERROR'"
        ),
        "queued_pred": (
            "q.queued_overload_time > 0"
            if "QUEUED_OVERLOAD_TIME" in qh_cols
            else "FALSE"
        ),
        "blocked_pred": (
            "q.transaction_blocked_time > 0"
            if "TRANSACTION_BLOCKED_TIME" in qh_cols
            else "FALSE"
        ),
        "wh_size_expr": (
            "MAX(q.warehouse_size)"
            if "WAREHOUSE_SIZE" in qh_cols
            else "NULL::VARCHAR"
        ),
        "queued_sec_expr": (
            "ROUND(SUM(q.queued_overload_time) / 1000, 2)"
            if "QUEUED_OVERLOAD_TIME" in qh_cols
            else "0::FLOAT"
        ),
        "remote_spill_expr": (
            "ROUND(SUM(q.bytes_spilled_to_remote_storage) / POWER(1024, 3), 2)"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0::FLOAT"
        ),
        "cache_expr": (
            "ROUND(AVG(q.percentage_scanned_from_cache), 2)"
            if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols
            else "0::FLOAT"
        ),
    }


def load_shared_service_query_health(
    session: object,
    hours: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load hourly query processor health for Service Health surfaces."""
    company = company or get_active_company()
    hours = max(1, int(hours or 24))

    def _loader() -> SharedMetricResult:
        mart_df = run_query(
            build_mart_service_query_health_sql(hours, company=company),
            ttl_key=get_company_scope_key("shared_service_query_health_mart", hours),
            tier="recent",
            section=section,
        )
        if not mart_df.empty and _first_numeric_value(mart_df, "TOTAL_QUERIES") > 0:
            return SharedMetricResult(
                data=mart_df,
                source="Fast query summary",
                available=True,
                effective_days=hours,
            )

        exprs = _service_query_history_exprs(session)
        query_company_filter = get_combined_filter_clause(
            db_col="q.database_name",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            company=company,
        )
        query_environment_filter = get_environment_filter_clause("q.database_name", company=company)
        live_df = run_query(
            f"""
            SELECT
                COUNT(*) AS total_queries,
                SUM(IFF({exprs["error_pred"]}, 1, 0)) AS failed_queries,
                SUM(IFF({exprs["queued_pred"]}, 1, 0)) AS queued_queries,
                SUM(IFF({exprs["blocked_pred"]}, 1, 0)) AS blocked_queries,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time) / 1000, 2) AS p95_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {query_company_filter}
              {query_environment_filter}
            """,
            ttl_key=get_company_scope_key("shared_service_query_health_live", hours),
            tier="recent",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            available=not live_df.empty,
            effective_days=hours,
        )

    return _load_or_reuse("shared_service_query_health", (company, hours), _loader, force=force)


def load_shared_service_warehouse_health(
    session: object,
    hours: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load hourly warehouse pressure rows for Service Health surfaces."""
    company = company or get_active_company()
    hours = max(1, int(hours or 24))

    def _loader() -> SharedMetricResult:
        mart_df = run_query(
            build_mart_service_warehouse_health_sql(hours, company=company),
            ttl_key=get_company_scope_key("shared_service_warehouse_health_mart", hours),
            tier="recent",
            section=section,
        )
        if not mart_df.empty:
            return SharedMetricResult(
                data=mart_df,
                source="Fast warehouse pressure summary",
                available=True,
                effective_days=hours,
            )

        exprs = _service_query_history_exprs(session)
        query_company_filter = get_combined_filter_clause(
            db_col="q.database_name",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            company=company,
        )
        query_environment_filter = get_environment_filter_clause("q.database_name", company=company)
        live_df = run_query(
            f"""
            SELECT
                q.warehouse_name,
                {exprs["wh_size_expr"]} AS warehouse_size,
                COUNT(*) AS total_queries,
                SUM(IFF({exprs["error_pred"]}, 1, 0)) AS failed_queries,
                {exprs["queued_sec_expr"]} AS queued_sec,
                {exprs["remote_spill_expr"]} AS remote_spill_gb,
                {exprs["cache_expr"]} AS avg_cache_pct
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {query_company_filter}
              {query_environment_filter}
            GROUP BY q.warehouse_name
            ORDER BY queued_sec DESC, remote_spill_gb DESC, failed_queries DESC
            LIMIT 100
            """,
            ttl_key=get_company_scope_key("shared_service_warehouse_health_live", hours),
            tier="recent",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            available=not live_df.empty,
            effective_days=hours,
        )

    return _load_or_reuse("shared_service_warehouse_health", (company, hours), _loader, force=force)


def load_shared_service_login_health(
    hours: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load hourly login/auth health for Service Health surfaces."""
    company = company or get_active_company()
    hours = max(1, int(hours or 24))

    def _loader() -> SharedMetricResult:
        if hours >= 24:
            mart_df = run_query(
                build_mart_service_login_health_sql(hours, company=company),
                ttl_key=get_company_scope_key("shared_service_login_health_mart", hours),
                tier="recent",
                section=section,
            )
            if not mart_df.empty:
                return SharedMetricResult(
                    data=mart_df,
                    source="Fast login summary",
                    available=True,
                    effective_days=hours,
                )

        live_df = run_query(
            f"""
            SELECT
                COUNT(*) AS login_events,
                SUM(IFF(is_success = 'NO', 1, 0)) AS failed_logins,
                COUNT(DISTINCT user_name) AS login_users,
                COUNT(DISTINCT client_ip) AS distinct_ips
            FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
            WHERE event_timestamp >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
              {get_user_company_filter_clause("user_name", company)}
            """,
            ttl_key=get_company_scope_key("shared_service_login_health_live", hours),
            tier="recent",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY",
            available=not live_df.empty,
            effective_days=hours,
        )

    return _load_or_reuse("shared_service_login_health", (company, hours), _loader, force=force)


def load_shared_service_task_health(
    session: object,
    hours: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load hourly task service health for Service Health surfaces."""
    company = company or get_active_company()
    hours = max(1, int(hours or 24))

    def _loader() -> SharedMetricResult:
        try:
            mart_df = run_query(
                build_mart_service_task_health_sql(hours, company=company),
                ttl_key=get_company_scope_key("shared_service_task_health_mart", hours),
                tier="recent",
                section=section,
            )
            if not mart_df.empty:
                return SharedMetricResult(
                    data=mart_df,
                    source="Fast task summary",
                    available=True,
                    effective_days=hours,
                )

            live_df = run_query(
                build_task_health_sql(
                    session,
                    f"scheduled_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())",
                    company=company,
                ),
                ttl_key=get_company_scope_key("shared_service_task_health_live", hours),
                tier="recent",
                section=section,
            )
            return SharedMetricResult(
                data=live_df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                available=not live_df.empty,
                effective_days=hours,
            )
        except Exception as exc:
            return SharedMetricResult(
                data=pd.DataFrame([{
                    "TASK_RUNS": 0,
                    "FAILED_TASKS": 0,
                    "SUCCEEDED_TASKS": 0,
                    "DISTINCT_TASKS": 0,
                }]),
                source="Unavailable",
                available=False,
                message=str(exc),
                effective_days=hours,
            )

    return _load_or_reuse("shared_service_task_health", (company, hours), _loader, force=force)


def load_shared_service_pipe_health(
    hours: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load hourly COPY_HISTORY health for Service Health surfaces."""
    company = company or get_active_company()
    hours = max(1, int(hours or 24))

    def _loader() -> SharedMetricResult:
        df = run_query(
            f"""
            SELECT
                COUNT(*) AS load_events,
                SUM(IFF(status = 'LOAD_FAILED', 1, 0)) AS failed_loads,
                ROUND(SUM(row_count), 0) AS rows_loaded,
                ROUND(SUM(file_size) / POWER(1024, 3), 2) AS gb_loaded
            FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
            WHERE last_load_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
              {get_db_filter_clause("table_catalog_name", company)}
            """,
            ttl_key=get_company_scope_key("shared_service_pipe_health", hours),
            tier="recent",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live: SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY",
            available=not df.empty,
            effective_days=hours,
        )

    return _load_or_reuse("shared_service_pipe_health", (company, hours), _loader, force=force)


