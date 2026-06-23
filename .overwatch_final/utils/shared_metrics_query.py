"""Shared query-history metric loaders."""

from __future__ import annotations

import pandas as pd

from .company_filter import get_active_company, get_company_scope_key, get_global_filter_clause
from .compatibility import filter_existing_columns
from .mart import build_mart_usage_overview_sql, build_mart_usage_pressure_sql
from .query import run_query
from .shared_metrics_cache import _global_filter_values, _load_or_reuse
from .shared_metrics_contracts import SharedMetricResult

def _query_history_rollup_exprs(session: object) -> dict[str, str]:
    """Return QUERY_HISTORY expressions that tolerate optional account columns."""
    qh_cols = set(
        filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            [
                "ERROR_CODE",
                "QUEUED_OVERLOAD_TIME",
                "QUEUED_PROVISIONING_TIME",
                "QUEUED_REPAIR_TIME",
                "CREDITS_USED_CLOUD_SERVICES",
                "BYTES_SPILLED_TO_REMOTE_STORAGE",
                "EXECUTION_TIME",
            ],
        )
    )
    success_expr = (
        "SUM(IFF(q.error_code IS NULL, 1, 0))"
        if "ERROR_CODE" in qh_cols
        else "SUM(IFF(UPPER(q.execution_status) = 'SUCCESS', 1, 0))"
    )
    failed_expr = (
        "SUM(IFF(q.error_code IS NOT NULL, 1, 0))"
        if "ERROR_CODE" in qh_cols
        else "SUM(IFF(UPPER(q.execution_status) = 'FAILED_WITH_ERROR', 1, 0))"
    )
    queue_terms = [
        f"q.{col.lower()} > 0"
        for col in ("QUEUED_OVERLOAD_TIME", "QUEUED_PROVISIONING_TIME", "QUEUED_REPAIR_TIME")
        if col in qh_cols
    ]
    queued_expr = (
        "SUM(IFF(" + " OR ".join(queue_terms) + ", 1, 0))"
        if queue_terms
        else "0"
    )
    cloud_expr = (
        "ROUND(SUM(COALESCE(q.credits_used_cloud_services, 0)), 4)"
        if "CREDITS_USED_CLOUD_SERVICES" in qh_cols
        else "0"
    )
    remote_spill_expr = (
        "ROUND(SUM(COALESCE(q.bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
        else "0"
    )
    avg_execution_expr = (
        "ROUND(AVG(q.execution_time) / 1000, 2)"
        if "EXECUTION_TIME" in qh_cols
        else "NULL::FLOAT"
    )
    return {
        "success_expr": success_expr,
        "failed_expr": failed_expr,
        "queued_expr": queued_expr,
        "cloud_expr": cloud_expr,
        "remote_spill_expr": remote_spill_expr,
        "avg_execution_expr": avg_execution_expr,
    }


def load_shared_query_history_rollup(
    session: object,
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load top-level query health counters once for usage and DBA surfaces."""

    company = company or get_active_company()
    days = int(days)
    (
        warehouse_contains,
        user_contains,
        role_contains,
        database_contains,
        global_start_date,
        global_end_date,
    ) = _global_filter_values()

    def _loader() -> SharedMetricResult:
        mart_df = run_query(
            build_mart_usage_overview_sql(
                days,
                company=company,
                warehouse_contains=warehouse_contains,
                user_contains=user_contains,
                role_contains=role_contains,
                database_contains=database_contains,
                start_date=global_start_date,
                end_date=global_end_date,
            ),
            ttl_key=get_company_scope_key("shared_query_history_rollup_mart", days),
            tier="historical",
            section=section,
        )
        if not mart_df.empty:
            total_queries = 0.0
            try:
                total_queries = float(pd.to_numeric(mart_df.get("TOTAL_QUERIES"), errors="coerce").fillna(0).iloc[0])
            except Exception:
                total_queries = 0.0
            if total_queries > 0:
                return SharedMetricResult(
                    data=mart_df,
                    source="Fast usage summary",
                    available=True,
                    effective_days=days,
                )

        exprs = _query_history_rollup_exprs(session)
        query_filters = get_global_filter_clause(
            date_col="q.start_time",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            db_col="q.database_name",
        )
        live_df = run_query(
            f"""
            SELECT
                COUNT(*) AS total_queries,
                COUNT(DISTINCT q.user_name) AS total_users,
                COUNT(DISTINCT q.database_name) AS active_databases,
                ROUND(100 * {exprs["success_expr"]} / NULLIF(COUNT(*), 0), 1) AS query_success_rate,
                {exprs["failed_expr"]} AS failed_queries,
                {exprs["queued_expr"]} AS queued_queries,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                {exprs["avg_execution_expr"]} AS avg_execution_sec,
                {exprs["cloud_expr"]} AS cloud_service_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {query_filters}
            """,
            ttl_key=get_company_scope_key("shared_query_history_rollup_live", days),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            available=not live_df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_query_history_rollup", (company, days), _loader, force=force)


def load_shared_warehouse_pressure_summary(
    session: object,
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load active and pressured warehouse counts once for summary surfaces."""

    company = company or get_active_company()
    days = int(days)
    (
        warehouse_contains,
        user_contains,
        role_contains,
        database_contains,
        global_start_date,
        global_end_date,
    ) = _global_filter_values()

    def _loader() -> SharedMetricResult:
        mart_df = run_query(
            build_mart_usage_pressure_sql(
                days,
                company=company,
                warehouse_contains=warehouse_contains,
                user_contains=user_contains,
                role_contains=role_contains,
                database_contains=database_contains,
                start_date=global_start_date,
                end_date=global_end_date,
            ),
            ttl_key=get_company_scope_key("shared_warehouse_pressure_mart", days),
            tier="historical",
            section=section,
        )
        if not mart_df.empty:
            return SharedMetricResult(
                data=mart_df,
                source="Fast warehouse pressure summary",
                available=True,
                effective_days=days,
            )

        exprs = _query_history_rollup_exprs(session)
        query_filters = get_global_filter_clause(
            date_col="q.start_time",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            db_col="q.database_name",
        )
        live_df = run_query(
            f"""
            WITH wh AS (
                SELECT
                    q.warehouse_name,
                    COUNT(*) AS total_queries,
                    {exprs["failed_expr"]} AS failed_queries,
                    {exprs["queued_expr"]} AS queued_queries,
                    {exprs["remote_spill_expr"]} AS remote_spill_gb
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {query_filters}
                GROUP BY q.warehouse_name
            )
            SELECT
                COUNT(*) AS active_warehouses,
                SUM(IFF(queued_queries > 0 OR remote_spill_gb > 1 OR failed_queries > 0, 1, 0)) AS pressure_warehouses
            FROM wh
            """,
            ttl_key=get_company_scope_key("shared_warehouse_pressure_live", days),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            available=not live_df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_warehouse_pressure", (company, days), _loader, force=force)


