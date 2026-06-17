"""Shared metric dataset loaders for high-repeat section queries.

The section modules should keep their workflow-specific rendering, but common
Snowflake fact reads should live here so mart-first/live-fallback behavior,
cache keys, and source captions stay consistent across the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd
import streamlit as st

from .company_filter import (
    get_active_company,
    get_company_scope_key,
    get_db_filter_clause,
    get_global_db_filter_clause,
    get_global_filter_clause,
    get_global_wh_filter_clause,
    get_wh_filter_clause,
    get_user_filter_clause,
)
from .compatibility import build_task_failure_summary_sql, filter_existing_columns
from .cost import build_idle_warehouse_sql
from .data import normalize_df
from .mart import (
    build_mart_recommendation_failed_tasks_sql,
    build_mart_recommendation_idle_sql,
    build_mart_recommendation_query_errors_sql,
    build_mart_recommendation_spill_sql,
    build_mart_warehouse_scaling_sql,
    build_mart_storage_db_detail_sql,
    build_mart_storage_trend_sql,
    build_mart_usage_overview_sql,
    build_mart_usage_metering_sql,
    build_mart_usage_pressure_sql,
    build_mart_usage_storage_sql,
    build_mart_warehouse_overview_sql,
    mart_object_name,
)
from .query import run_query, sql_literal


LIVE_STORAGE_FALLBACK_MAX_DAYS = 90


@dataclass
class SharedMetricResult:
    """Container for a shared metric frame and its source metadata."""

    data: pd.DataFrame
    source: str
    available: bool = True
    message: str = ""
    effective_days: int | None = None


def _empty_result(source: str, message: str = "", effective_days: int | None = None) -> SharedMetricResult:
    return SharedMetricResult(
        data=pd.DataFrame(),
        source=source,
        available=False,
        message=message,
        effective_days=effective_days,
    )


def _shared_state_key(metric: str, *parts: object) -> str:
    return f"_shared_metric_{get_company_scope_key(metric, *parts)}"


def _get_cached_result(state_key: str) -> SharedMetricResult | None:
    result = st.session_state.get(state_key)
    return result if isinstance(result, SharedMetricResult) else None


def _store_result(state_key: str, result: SharedMetricResult) -> SharedMetricResult:
    st.session_state[state_key] = result
    return result


def _load_or_reuse(
    metric: str,
    parts: tuple[object, ...],
    loader: Callable[[], SharedMetricResult],
    *,
    force: bool = False,
) -> SharedMetricResult:
    state_key = _shared_state_key(metric, *parts)
    if not force:
        cached = _get_cached_result(state_key)
        if cached is not None:
            return cached
    return _store_result(state_key, loader())


def _storage_summary_from_trend(trend: pd.DataFrame, days: int) -> pd.DataFrame:
    """Build Usage Overview storage KPIs from a shared storage trend frame."""
    if trend is None or trend.empty:
        return pd.DataFrame()

    df = normalize_df(trend.copy())
    if "USAGE_DATE" not in df.columns or "STORAGE_GB" not in df.columns:
        return pd.DataFrame()

    df["USAGE_DATE"] = pd.to_datetime(df["USAGE_DATE"], errors="coerce")
    df = df.dropna(subset=["USAGE_DATE"]).sort_values("USAGE_DATE")
    if df.empty:
        return pd.DataFrame()

    for col in ("STORAGE_GB", "FAILSAFE_GB"):
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    latest = df.iloc[-1]
    target_date = latest["USAGE_DATE"] - pd.Timedelta(days=int(days))
    prior_rows = df[df["USAGE_DATE"] <= target_date]
    prior_active_tb = (
        float(prior_rows.iloc[-1].get("STORAGE_GB", 0.0)) / 1024.0
        if not prior_rows.empty
        else 0.0
    )
    return pd.DataFrame([{
        "ACTIVE_STORAGE_TB": round(float(latest.get("STORAGE_GB", 0.0)) / 1024.0, 3),
        "FAILSAFE_STORAGE_TB": round(float(latest.get("FAILSAFE_GB", 0.0)) / 1024.0, 3),
        "PRIOR_ACTIVE_STORAGE_TB": round(prior_active_tb, 3),
    }])


def load_shared_storage_trend(
    days: int,
    company: str | None = None,
    *,
    allow_live_fallback: bool = True,
    max_live_days: int = LIVE_STORAGE_FALLBACK_MAX_DAYS,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load daily storage trend once per active scope and reuse it across sections."""
    company = company or get_active_company()
    days = int(days)
    max_live_days = int(max_live_days)

    def _loader() -> SharedMetricResult:
        df = run_query(
            build_mart_storage_trend_sql(days, company),
            ttl_key=get_company_scope_key("shared_storage_trend_mart", days),
            tier="historical",
            section=section,
        )
        if not df.empty:
            return SharedMetricResult(
                data=df,
                source="Fast storage summary",
                effective_days=days,
            )
        if not allow_live_fallback:
            return _empty_result("Fast storage summary", "Storage mart returned no rows.", effective_days=days)

        fallback_days = min(days, max_live_days)
        stage_storage_cte = (
            f"""
            stage_storage AS (
                SELECT usage_date, SUM(average_stage_bytes) AS stage_bytes
                FROM SNOWFLAKE.ACCOUNT_USAGE.STAGE_STORAGE_USAGE_HISTORY
                WHERE usage_date >= DATEADD('day', -{fallback_days}, CURRENT_DATE())
                GROUP BY usage_date
            )
            """
            if company == "ALL"
            else """
            stage_storage AS (
                SELECT usage_date, 0 AS stage_bytes
                FROM database_storage
            )
            """
        )
        df = run_query(
            f"""
            WITH database_storage AS (
                SELECT usage_date,
                       SUM(average_database_bytes) AS storage_bytes,
                       SUM(average_failsafe_bytes) AS failsafe_bytes
                FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
                WHERE usage_date >= DATEADD('day', -{fallback_days}, CURRENT_DATE())
                  {get_db_filter_clause("database_name", company)}
                GROUP BY usage_date
            ),
            {stage_storage_cte}
            SELECT COALESCE(d.usage_date, s.usage_date)        AS usage_date,
                   COALESCE(d.storage_bytes,  0)/POWER(1024,3) AS storage_gb,
                   COALESCE(d.failsafe_bytes, 0)/POWER(1024,3) AS failsafe_gb,
                   COALESCE(s.stage_bytes,    0)/POWER(1024,3) AS stage_gb,
                   (COALESCE(d.storage_bytes,0)+COALESCE(d.failsafe_bytes,0)+COALESCE(s.stage_bytes,0))
                       /POWER(1024,4)                           AS total_storage_tb
            FROM database_storage d
            FULL OUTER JOIN stage_storage s ON d.usage_date = s.usage_date
            ORDER BY usage_date
            """,
            ttl_key=get_company_scope_key("shared_storage_trend_live", fallback_days),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE storage views",
            available=not df.empty,
            effective_days=fallback_days,
        )

    return _load_or_reuse(
        "shared_storage_trend",
        (company, days, allow_live_fallback, max_live_days),
        _loader,
        force=force,
    )


def load_shared_usage_storage_kpis(
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load the storage KPI row used by executive/usage surfaces."""
    company = company or get_active_company()
    days = int(days)

    def _loader() -> SharedMetricResult:
        database_contains = str(st.session_state.get("global_database", "") or "").strip()
        if not database_contains:
            trend_result = load_shared_storage_trend(
                max(days * 2, 14),
                company,
                allow_live_fallback=True,
                force=force,
                section=section,
            )
            trend_summary = _storage_summary_from_trend(trend_result.data, days)
            if not trend_summary.empty:
                return SharedMetricResult(
                    data=trend_summary,
                    source=trend_result.source,
                    available=trend_result.available,
                    message=trend_result.message,
                    effective_days=trend_result.effective_days,
                )

        df = run_query(
            build_mart_usage_storage_sql(days, company=company, database_contains=database_contains),
            ttl_key=get_company_scope_key("shared_usage_storage_mart", days),
            tier="historical",
            section=section,
        )
        if not df.empty:
            return SharedMetricResult(data=df, source="Fast storage summary", effective_days=days)

        df = run_query(
            f"""
            WITH scoped AS (
                SELECT database_name, average_database_bytes, average_failsafe_bytes, usage_date
                FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
                WHERE usage_date >= DATEADD('day', -{max(days * 2, 14)}, CURRENT_DATE())
                  {get_db_filter_clause("database_name", company)}
                  {get_global_db_filter_clause("database_name")}
            ),
            current_latest AS (
                SELECT database_name, average_database_bytes, average_failsafe_bytes,
                       ROW_NUMBER() OVER (PARTITION BY database_name ORDER BY usage_date DESC) AS rn
                FROM scoped
            ),
            prior_latest AS (
                SELECT database_name, average_database_bytes,
                       ROW_NUMBER() OVER (PARTITION BY database_name ORDER BY usage_date DESC) AS rn
                FROM scoped
                WHERE usage_date <= DATEADD('day', -{days}, CURRENT_DATE())
            )
            SELECT
                ROUND(SUM(COALESCE(c.average_database_bytes, 0)) / POWER(1024, 4), 3) AS active_storage_tb,
                ROUND(SUM(COALESCE(c.average_failsafe_bytes, 0)) / POWER(1024, 4), 3) AS failsafe_storage_tb,
                ROUND(SUM(COALESCE(p.average_database_bytes, 0)) / POWER(1024, 4), 3) AS prior_active_storage_tb
            FROM current_latest c
            LEFT JOIN prior_latest p
              ON c.database_name = p.database_name
             AND p.rn = 1
            WHERE c.rn = 1
            """,
            ttl_key=get_company_scope_key("shared_usage_storage_live", days),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_usage_storage", (company, days), _loader, force=force)


def _query_history_rollup_exprs(session: object) -> dict[str, str]:
    """Return QUERY_HISTORY expressions that tolerate optional account columns."""
    from .compatibility import filter_existing_columns

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
    warehouse_contains = str(st.session_state.get("global_warehouse", "") or "").strip()
    user_contains = str(st.session_state.get("global_user", "") or "").strip()
    role_contains = str(st.session_state.get("global_role", "") or "").strip()
    database_contains = str(st.session_state.get("global_database", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")

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
    warehouse_contains = str(st.session_state.get("global_warehouse", "") or "").strip()
    user_contains = str(st.session_state.get("global_user", "") or "").strip()
    role_contains = str(st.session_state.get("global_role", "") or "").strip()
    database_contains = str(st.session_state.get("global_database", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")

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


def load_shared_usage_metering_kpis(
    session: object,
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load account-level warehouse metering KPIs once for usage/cost surfaces."""

    company = company or get_active_company()
    days = int(days)
    warehouse_contains = str(st.session_state.get("global_warehouse", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")

    def _loader() -> SharedMetricResult:
        mart_df = run_query(
            build_mart_usage_metering_sql(
                days,
                company=company,
                warehouse_contains=warehouse_contains,
                start_date=global_start_date,
                end_date=global_end_date,
            ),
            ttl_key=get_company_scope_key("shared_usage_metering_mart", days),
            tier="historical",
            section=section,
        )
        if not mart_df.empty:
            return SharedMetricResult(
                data=mart_df,
                source="Fast metering summary",
                available=True,
                effective_days=days,
            )

        from .compatibility import filter_existing_columns

        wm_cols = set(
            filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
            )
        )
        compute_expr = (
            f"ROUND(SUM(IFF(start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), "
            "credits_used_compute, 0)), 4)"
            if "CREDITS_USED_COMPUTE" in wm_cols
            else f"ROUND(SUM(IFF(start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), credits_used, 0)), 4)"
        )
        cloud_expr = (
            f"ROUND(SUM(IFF(start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), "
            "credits_used_cloud_services, 0)), 4)"
            if "CREDITS_USED_CLOUD_SERVICES" in wm_cols
            else "0"
        )
        live_df = run_query(
            f"""
            SELECT
                ROUND(SUM(IFF(start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), credits_used, 0)), 4) AS total_credits,
                ROUND(SUM(IFF(start_time >= DATEADD('day', -{days * 2}, CURRENT_TIMESTAMP())
                              AND start_time < DATEADD('day', -{days}, CURRENT_TIMESTAMP()),
                              credits_used, 0)), 4) AS prior_credits,
                {compute_expr} AS compute_credits,
                {cloud_expr} AS warehouse_cloud_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE start_time >= DATEADD('day', -{days * 2}, CURRENT_TIMESTAMP())
              {get_wh_filter_clause("warehouse_name", company)}
              {get_global_wh_filter_clause("warehouse_name")}
            """,
            ttl_key=get_company_scope_key("shared_usage_metering_live", days),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
            available=not live_df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_usage_metering", (company, days), _loader, force=force)


def load_shared_storage_db_detail(
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load latest per-database storage detail once for the active scope."""
    company = company or get_active_company()

    def _loader() -> SharedMetricResult:
        df = run_query(
            build_mart_storage_db_detail_sql(company),
            ttl_key=get_company_scope_key("shared_storage_db_detail_mart"),
            tier="standard",
            section=section,
        )
        if not df.empty:
            return SharedMetricResult(data=df, source="Fast storage summary")

        df = run_query(
            f"""
            SELECT database_name,
                   usage_date,
                   average_database_bytes/POWER(1024,3) AS database_gb,
                   average_failsafe_bytes/POWER(1024,3) AS failsafe_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
            WHERE usage_date = (SELECT MAX(usage_date)
                                FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY)
              {get_db_filter_clause("database_name", company)}
            ORDER BY database_gb DESC
            LIMIT 50
            """,
            ttl_key=get_company_scope_key("shared_storage_db_detail_live"),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live fallback: DATABASE_STORAGE_USAGE_HISTORY",
            available=not df.empty,
        )

    return _load_or_reuse("shared_storage_db_detail", (company,), _loader, force=force)


def load_shared_warehouse_daily_credits(
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load daily warehouse metering credits for forecasts and burn-rate reuse."""
    company = company or get_active_company()
    days = int(days)

    def _loader() -> SharedMetricResult:
        df = run_query(
            f"""
            SELECT DATE_TRUNC('day', start_time) AS day,
                   SUM(credits_used) AS daily_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              {get_wh_filter_clause("warehouse_name", company)}
            GROUP BY day
            ORDER BY day
            """,
            ttl_key=get_company_scope_key("shared_warehouse_daily_credits", days),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_warehouse_daily_credits", (company, days), _loader, force=force)


def load_shared_warehouse_daily_credits_by_warehouse(
    session: object,
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load daily warehouse metering credits with latest observed warehouse size."""

    company = company or get_active_company()
    days = int(days)

    def _loader() -> SharedMetricResult:
        from .compatibility import filter_existing_columns

        qh_cols = set(
            filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["WAREHOUSE_SIZE"],
            )
        )
        warehouse_size_expr = "warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
        df = run_query(
            f"""
            WITH latest_size AS (
                SELECT warehouse_name, warehouse_size
                FROM (
                    SELECT warehouse_name, {warehouse_size_expr},
                           ROW_NUMBER() OVER (PARTITION BY warehouse_name ORDER BY start_time DESC) AS rn
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      {get_wh_filter_clause("warehouse_name", company)}
                      {get_global_wh_filter_clause("warehouse_name")}
                )
                WHERE rn = 1
            )
            SELECT DATE_TRUNC('day', m.start_time) AS day,
                   m.warehouse_name,
                   ls.warehouse_size,
                   SUM(m.credits_used) AS daily_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
            LEFT JOIN latest_size ls ON m.warehouse_name = ls.warehouse_name
            WHERE m.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              {get_wh_filter_clause("m.warehouse_name", company)}
              {get_global_wh_filter_clause("m.warehouse_name")}
            GROUP BY day, m.warehouse_name, ls.warehouse_size
            ORDER BY day
            """,
            ttl_key=get_company_scope_key("shared_warehouse_daily_credits_by_warehouse", days),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY by warehouse",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_warehouse_daily_credits_by_warehouse", (company, days), _loader, force=force)


def load_shared_warehouse_overview(
    session: object,
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load per-warehouse pressure and current/prior credit movement."""

    company = company or get_active_company()
    days = int(days)
    warehouse_contains = str(st.session_state.get("global_warehouse", "") or "").strip()
    user_contains = str(st.session_state.get("global_user", "") or "").strip()
    role_contains = str(st.session_state.get("global_role", "") or "").strip()
    database_contains = str(st.session_state.get("global_database", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")

    def _loader() -> SharedMetricResult:
        mart_df = run_query(
            build_mart_warehouse_overview_sql(
                days,
                company=company,
                warehouse_contains=warehouse_contains,
                user_contains=user_contains,
                role_contains=role_contains,
                database_contains=database_contains,
                start_date=global_start_date,
                end_date=global_end_date,
            ),
            ttl_key=get_company_scope_key("shared_warehouse_overview_mart", days),
            tier="historical",
            section=section,
        )
        if not mart_df.empty:
            return SharedMetricResult(
                data=mart_df,
                source="Fast warehouse summary (cache and warehouse size require live ACCOUNT_USAGE)",
                available=True,
                effective_days=days,
            )

        from .compatibility import filter_existing_columns

        qh_cols = set(
            filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                [
                    "WAREHOUSE_SIZE",
                    "QUEUED_OVERLOAD_TIME",
                    "BYTES_SPILLED_TO_REMOTE_STORAGE",
                    "PERCENTAGE_SCANNED_FROM_CACHE",
                    "BYTES_SCANNED",
                ],
            )
        )
        wm_cols = set(
            filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
            )
        )
        warehouse_size_expr = "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
        queue_avg_expr = "AVG(q.queued_overload_time) / 1000" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0"
        remote_spill_expr = (
            "SUM(q.bytes_spilled_to_remote_storage)"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        )
        cache_expr = "AVG(q.percentage_scanned_from_cache)" if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols else "NULL::FLOAT"
        bytes_scanned_expr = "SUM(q.bytes_scanned)" if "BYTES_SCANNED" in qh_cols else "0"
        compute_meter_expr = "m.credits_used_compute" if "CREDITS_USED_COMPUTE" in wm_cols else "m.credits_used"
        cloud_meter_expr = "m.credits_used_cloud_services" if "CREDITS_USED_CLOUD_SERVICES" in wm_cols else "0::FLOAT"
        query_filters = get_global_filter_clause(
            date_col="q.start_time",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            db_col="q.database_name",
        )
        metering_filters = "\n".join(
            filter(
                None,
                [
                    get_wh_filter_clause("m.warehouse_name", company),
                    get_global_wh_filter_clause("m.warehouse_name"),
                ],
            )
        )
        live_df = run_query(
            f"""
            WITH query_rollup AS (
                SELECT q.warehouse_name,
                       {warehouse_size_expr} AS warehouse_size,
                       COUNT(*) AS total_queries,
                       AVG(q.total_elapsed_time) / 1000 AS avg_elapsed_sec,
                       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.total_elapsed_time) / 1000 AS p95_elapsed_sec,
                       {queue_avg_expr} AS avg_queued_sec,
                       {remote_spill_expr} / POWER(1024, 3) AS total_remote_spill_gb,
                       {cache_expr} AS avg_cache_pct,
                       SUM(CASE WHEN UPPER(q.execution_status) = 'FAILED_WITH_ERROR' THEN 1 ELSE 0 END) AS error_count,
                       {bytes_scanned_expr} / POWER(1024, 3) AS total_gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {query_filters}
                GROUP BY q.warehouse_name
            ),
            credit_rollup AS (
                SELECT
                    m.warehouse_name,
                    ROUND(SUM(IFF(m.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), COALESCE(m.credits_used, 0), 0)), 4) AS metered_credits,
                    ROUND(SUM(IFF(m.start_time >= DATEADD('day', -{days * 2}, CURRENT_TIMESTAMP())
                                  AND m.start_time < DATEADD('day', -{days}, CURRENT_TIMESTAMP()),
                                  COALESCE(m.credits_used, 0), 0)), 4) AS prior_metered_credits,
                    ROUND(SUM(IFF(m.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), COALESCE({compute_meter_expr}, 0), 0)), 4) AS credits_used_compute,
                    ROUND(SUM(IFF(m.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), COALESCE({cloud_meter_expr}, 0), 0)), 4) AS credits_used_cloud_services
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
                WHERE m.start_time >= DATEADD('day', -{days * 2}, CURRENT_TIMESTAMP())
                  {metering_filters}
                GROUP BY m.warehouse_name
            )
            SELECT
                COALESCE(q.warehouse_name, c.warehouse_name) AS warehouse_name,
                q.warehouse_size,
                COALESCE(q.total_queries, 0) AS total_queries,
                COALESCE(q.avg_elapsed_sec, 0) AS avg_elapsed_sec,
                COALESCE(q.p95_elapsed_sec, 0) AS p95_elapsed_sec,
                COALESCE(q.avg_queued_sec, 0) AS avg_queued_sec,
                COALESCE(q.total_remote_spill_gb, 0) AS total_remote_spill_gb,
                q.avg_cache_pct,
                COALESCE(q.error_count, 0) AS error_count,
                COALESCE(q.total_gb_scanned, 0) AS total_gb_scanned,
                COALESCE(c.metered_credits, 0) AS metered_credits,
                COALESCE(c.prior_metered_credits, 0) AS prior_metered_credits,
                ROUND(COALESCE(c.metered_credits, 0) - COALESCE(c.prior_metered_credits, 0), 4) AS credit_delta,
                ROUND(
                    (COALESCE(c.metered_credits, 0) - COALESCE(c.prior_metered_credits, 0))
                    / NULLIF(COALESCE(c.prior_metered_credits, 0), 0) * 100,
                    1
                ) AS credit_delta_pct,
                COALESCE(c.credits_used_compute, 0) AS credits_used_compute,
                COALESCE(c.credits_used_cloud_services, 0) AS credits_used_cloud_services,
                NULL::TIMESTAMP AS mart_load_ts
            FROM query_rollup q
            FULL OUTER JOIN credit_rollup c ON q.warehouse_name = c.warehouse_name
            ORDER BY COALESCE(q.total_queries, 0) DESC, COALESCE(c.metered_credits, 0) DESC
            """,
            ttl_key=get_company_scope_key("shared_warehouse_overview_live", days),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY + WAREHOUSE_METERING_HISTORY",
            available=not live_df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_warehouse_overview", (company, days), _loader, force=force)


def load_shared_warehouse_scaling_events(
    session: object,
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load warehouse metering/scaling events once for warehouse detail views."""

    company = company or get_active_company()
    days = int(days)
    warehouse_contains = str(st.session_state.get("global_warehouse", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")

    def _loader() -> SharedMetricResult:
        mart_df = run_query(
            build_mart_warehouse_scaling_sql(
                days,
                company=company,
                warehouse_contains=warehouse_contains,
                start_date=global_start_date,
                end_date=global_end_date,
            ),
            ttl_key=get_company_scope_key("shared_warehouse_scaling_mart", days),
            tier="historical",
            section=section,
        )
        if not mart_df.empty:
            return SharedMetricResult(
                data=mart_df,
                source="Fast warehouse summary",
                available=True,
                effective_days=days,
            )

        from .compatibility import filter_existing_columns

        qh_cols = set(
            filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["WAREHOUSE_SIZE"],
            )
        )
        wm_cols = set(
            filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
            )
        )
        latest_size_expr = "q.warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
        compute_meter_expr = "m.credits_used_compute" if "CREDITS_USED_COMPUTE" in wm_cols else "m.credits_used"
        cloud_meter_expr = "m.credits_used_cloud_services" if "CREDITS_USED_CLOUD_SERVICES" in wm_cols else "0::FLOAT"
        query_filters = get_global_filter_clause(
            date_col="q.start_time",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            db_col="q.database_name",
        )
        metering_filters = "\n".join(
            filter(
                None,
                [
                    get_wh_filter_clause("m.warehouse_name", company),
                    get_global_wh_filter_clause("m.warehouse_name"),
                ],
            )
        )
        live_df = run_query(
            f"""
            WITH latest_size AS (
                SELECT warehouse_name, warehouse_size
                FROM (
                    SELECT q.warehouse_name,
                           {latest_size_expr} AS warehouse_size,
                           ROW_NUMBER() OVER (PARTITION BY q.warehouse_name ORDER BY q.start_time DESC) AS rn
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                      AND q.warehouse_name IS NOT NULL
                      {query_filters}
                )
                WHERE rn = 1
            )
            SELECT m.warehouse_name,
                   ls.warehouse_size,
                   m.start_time,
                   m.end_time,
                   m.credits_used,
                   {compute_meter_expr} AS credits_used_compute,
                   {cloud_meter_expr} AS credits_used_cloud_services
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY m
            LEFT JOIN latest_size ls ON m.warehouse_name = ls.warehouse_name
            WHERE m.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              {metering_filters}
            ORDER BY m.credits_used DESC
            LIMIT 200
            """,
            ttl_key=get_company_scope_key("shared_warehouse_scaling_live", days),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
            available=not live_df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_warehouse_scaling", (company, days), _loader, force=force)


def load_shared_task_health_summary(
    session: object,
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load reusable TASK_HISTORY health counters for DBA summary surfaces."""

    company = company or get_active_company()
    days = int(days)

    def _loader() -> SharedMetricResult:
        try:
            from .compatibility import build_task_health_sql

            df = run_query(
                build_task_health_sql(
                    session,
                    f"scheduled_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())",
                    company=company,
                ),
                ttl_key=get_company_scope_key("shared_task_health", days),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                available=not df.empty,
                effective_days=days,
            )
        except Exception as exc:
            return SharedMetricResult(
                data=pd.DataFrame([{
                    "TASK_RUNS": 0,
                    "FAILED_TASKS": 0,
                    "SUCCEEDED_TASKS": 0,
                    "DISTINCT_TASKS": 0,
                }]),
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                available=False,
                message=str(exc),
                effective_days=days,
            )

    return _load_or_reuse("shared_task_health", (company, days), _loader, force=force)


def _shared_user_exprs(session: object) -> dict[str, str]:
    """Return USERS projections for MFA/password signals across Snowflake versions."""
    from .compatibility import filter_existing_columns

    user_cols = set(
        filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.USERS",
            ["HAS_MFA", "EXT_AUTHN_DUO", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
        )
    )
    if "HAS_MFA" in user_cols:
        mfa_bool_expr = "COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.has_mfa)), FALSE)"
        mfa_source_expr = "'HAS_MFA'"
        mfa_signal_expr = "COALESCE(TO_VARCHAR(u.has_mfa), 'unknown')"
    elif "EXT_AUTHN_DUO" in user_cols:
        mfa_bool_expr = "COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.ext_authn_duo)), FALSE)"
        mfa_source_expr = "'EXT_AUTHN_DUO'"
        mfa_signal_expr = "COALESCE(TO_VARCHAR(u.ext_authn_duo), 'unknown')"
    else:
        mfa_bool_expr = "NULL::BOOLEAN"
        mfa_source_expr = "'UNAVAILABLE'"
        mfa_signal_expr = "'unknown'"
    return {
        "has_password_expr": (
            "COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.has_password)), FALSE)"
            if "HAS_PASSWORD" in user_cols else "NULL::BOOLEAN"
        ),
        "has_password_signal": (
            "COALESCE(TO_VARCHAR(u.has_password), 'false')"
            if "HAS_PASSWORD" in user_cols else "'unknown'"
        ),
        "mfa_bool_expr": mfa_bool_expr,
        "mfa_source_expr": mfa_source_expr,
        "mfa_signal_expr": mfa_signal_expr,
        "last_success_expr": (
            "u.last_success_login"
            if "LAST_SUCCESS_LOGIN" in user_cols else "NULL::TIMESTAMP_NTZ"
        ),
    }


def load_shared_mfa_coverage(
    session: object,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load active-user MFA posture once for security surfaces."""

    company = company or get_active_company()

    def _loader() -> SharedMetricResult:
        exprs = _shared_user_exprs(session)
        df = run_query(
            f"""
            SELECT
                u.name AS user_name,
                {exprs["has_password_expr"]} AS has_password,
                {exprs["mfa_bool_expr"]} AS has_mfa,
                {exprs["mfa_source_expr"]} AS mfa_source,
                u.disabled,
                COALESCE({exprs["last_success_expr"]}, u.created_on) AS last_login
            FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
            WHERE u.deleted_on IS NULL
              AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
              {get_user_filter_clause("u.name", company)}
            ORDER BY has_mfa, user_name
            """,
            ttl_key=get_company_scope_key("shared_mfa_coverage"),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.USERS",
            available=not df.empty,
        )

    return _load_or_reuse("shared_mfa_coverage", (company,), _loader, force=force)


def load_shared_grants_to_users(
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load active user-role grants once for security/access review surfaces."""

    company = company or get_active_company()

    def _loader() -> SharedMetricResult:
        try:
            company_filter = ""
            if str(company or "ALL").upper() != "ALL":
                company_filter = f"AND g.company = {sql_literal(company, 100)}"
            table = mart_object_name("FACT_GRANT_DAILY")
            mart_df = run_query(
                f"""
                WITH latest AS (
                    SELECT MAX(snapshot_date) AS snapshot_date
                    FROM {table}
                )
                SELECT
                    g.grantee_name,
                    g.role_name AS role,
                    g.granted_to,
                    NULL::VARCHAR AS granted_by,
                    MIN(g.created_on) AS created_on,
                    NULL::TIMESTAMP_NTZ AS deleted_on
                FROM {table} g
                JOIN latest l ON g.snapshot_date = l.snapshot_date
                WHERE g.deleted_on IS NULL
                  {company_filter}
                  {get_user_filter_clause("g.grantee_name", company)}
                GROUP BY g.grantee_name, g.role_name, g.granted_to
                ORDER BY created_on DESC
                LIMIT 500
                """,
                ttl_key=get_company_scope_key("shared_grants_to_users_mart"),
                tier="standard",
                section=section,
            )
            if not mart_df.empty:
                return SharedMetricResult(data=mart_df, source="Fast grant summary", available=True)
        except Exception:
            pass

        live_df = run_query(
            f"""
            SELECT grantee_name,
                   role,
                   granted_to,
                   granted_by,
                   created_on,
                   deleted_on
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
            WHERE deleted_on IS NULL
              {get_user_filter_clause("grantee_name", company)}
            ORDER BY created_on DESC
            LIMIT 500
            """,
            ttl_key=get_company_scope_key("shared_grants_to_users_live"),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS",
            available=not live_df.empty,
        )

    return _load_or_reuse("shared_grants_to_users", (company,), _loader, force=force)


def load_shared_access_hygiene_snapshot(
    session: object,
    days: int,
    company: str | None = None,
    *,
    environment: str = "ALL",
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load account-level user/login/grant hygiene once for Account Health/Security."""

    company = company or get_active_company()
    days = max(1, int(days or 30))
    env_label = sql_literal(str(environment or "ALL"), 100)

    def _loader() -> SharedMetricResult:
        exprs = _shared_user_exprs(session)
        df = run_query(
            f"""
            WITH login_rollup AS (
                SELECT
                    lh.user_name,
                    COUNT_IF(lh.is_success = 'NO') AS failed_logins,
                    COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.client_ip, NULL)) AS failed_ips,
                    MAX(IFF(lh.is_success = 'YES', lh.event_timestamp, NULL)) AS last_login_from_history
                FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
                WHERE lh.event_timestamp >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  {get_user_filter_clause("lh.user_name", company)}
                GROUP BY lh.user_name
            ),
            admin_grants AS (
                SELECT
                    g.grantee_name AS user_name,
                    COUNT(DISTINCT g.role) AS admin_role_count,
                    LISTAGG(DISTINCT g.role, ', ') WITHIN GROUP (ORDER BY g.role) AS admin_roles
                FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
                WHERE g.deleted_on IS NULL
                  {get_user_filter_clause("g.grantee_name", company)}
                  AND (
                      UPPER(g.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN')
                      OR UPPER(g.role) LIKE '%ADMIN%'
                      OR UPPER(g.role) LIKE '%SECURITY%'
                  )
                GROUP BY g.grantee_name
            ),
            user_posture AS (
                SELECT
                    u.name AS user_name,
                    COALESCE(TO_VARCHAR(u.disabled), 'false') AS disabled,
                    {exprs["has_password_signal"]} AS has_password,
                    {exprs["mfa_signal_expr"]} AS mfa_signal,
                    COALESCE(lr.last_login_from_history, {exprs["last_success_expr"]}, u.created_on) AS last_seen,
                    COALESCE(lr.failed_logins, 0) AS failed_logins,
                    COALESCE(lr.failed_ips, 0) AS failed_ips,
                    COALESCE(ag.admin_role_count, 0) AS admin_role_count,
                    COALESCE(ag.admin_roles, '') AS admin_roles
                FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
                LEFT JOIN login_rollup lr ON UPPER(u.name) = UPPER(lr.user_name)
                LEFT JOIN admin_grants ag ON UPPER(u.name) = UPPER(ag.user_name)
                WHERE u.deleted_on IS NULL
                  {get_user_filter_clause("u.name", company)}
            )
            SELECT
                user_name,
                disabled,
                has_password,
                mfa_signal,
                last_seen,
                failed_logins,
                failed_ips,
                admin_role_count,
                admin_roles,
                DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) AS days_since_seen,
                CASE
                    WHEN failed_logins >= 25 OR failed_ips >= 5 THEN 'High'
                    WHEN admin_role_count > 0 AND (mfa_signal = 'unknown' OR LOWER(mfa_signal) <> 'true') THEN 'High'
                    WHEN DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) >= 90 THEN 'Medium'
                    WHEN failed_logins > 0 OR admin_role_count > 0 OR (mfa_signal <> 'unknown' AND LOWER(mfa_signal) <> 'true') THEN 'Medium'
                    ELSE 'Low'
                END AS severity,
                CONCAT_WS('; ',
                    IFF(disabled = 'true', 'disabled user retained in account', NULL),
                    IFF(failed_logins > 0, failed_logins || ' failed login(s)', NULL),
                    IFF(failed_ips >= 5, failed_ips || ' failed login source IP(s)', NULL),
                    IFF(admin_role_count > 0, admin_role_count || ' privileged role grant(s)', NULL),
                    IFF(mfa_signal <> 'unknown' AND LOWER(mfa_signal) <> 'true', 'MFA signal missing', NULL),
                    IFF(DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) >= 90, 'dormant >= 90 days', NULL)
                ) AS posture_findings,
                'No Database Context' AS database_context,
                'No Database Context' AS environment_scope,
                {env_label} AS selected_environment,
                'Account-Level Control' AS scope_confidence,
                'USERS, LOGIN_HISTORY, and GRANTS_TO_USERS do not expose database context; company scope uses user naming only.' AS scope_evidence,
                'Confirm IAM route, admin-role business need, MFA posture, and recent login telemetry before disabling users or changing grants.' AS next_action,
                'user, IAM ticket, failed login context, MFA/admin-role telemetry' AS proof_required
            FROM user_posture
            WHERE
                failed_logins > 0
                OR admin_role_count > 0
                OR (mfa_signal <> 'unknown' AND LOWER(mfa_signal) <> 'true')
                OR DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) >= 90
            ORDER BY
                CASE severity WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
                failed_logins DESC,
                admin_role_count DESC,
                days_since_seen DESC
            LIMIT 100
            """,
            ttl_key=get_company_scope_key("shared_access_hygiene", days, environment),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.USERS + LOGIN_HISTORY + GRANTS_TO_USERS",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_access_hygiene", (company, days, environment), _loader, force=force)


def load_shared_recommendation_idle_warehouses(
    company: str | None = None,
    *,
    days: int = 7,
    min_idle_credits: float = 1.0,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load idle-warehouse advisor candidates once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_idle_credits = float(min_idle_credits or 0)

    def _loader() -> SharedMetricResult:
        mart_message = ""
        if days == 7 and min_idle_credits <= 1.0:
            try:
                df = run_query(
                    build_mart_recommendation_idle_sql(company),
                    ttl_key=get_company_scope_key("shared_rec_idle_mart"),
                    tier="historical",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(data=df, source="Fast recommendation summary", available=True)
                mart_message = "Idle warehouse mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for non-default idle threshold or lookback."

        try:
            df = run_query(
                build_idle_warehouse_sql(
                    days_back=days,
                    wh_filter=get_wh_filter_clause("warehouse_name"),
                    min_idle_credits=min_idle_credits,
                ),
                ttl_key=get_company_scope_key("shared_rec_idle_live", days, min_idle_credits),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE warehouse/query history",
                available=not df.empty,
                message="" if not df.empty else mart_message,
            )
        except Exception as exc:
            return _empty_result("Idle warehouse advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse("shared_rec_idle", (company, days, min_idle_credits), _loader, force=force)


def load_shared_recommendation_spill_warehouses(
    session: object,
    company: str | None = None,
    *,
    days: int = 7,
    min_remote_gb: float = 5.0,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load remote-spill advisor candidates once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_remote_gb = float(min_remote_gb or 0)

    def _loader() -> SharedMetricResult:
        mart_message = ""
        if days == 7 and min_remote_gb <= 5.0:
            try:
                df = run_query(
                    build_mart_recommendation_spill_sql(company),
                    ttl_key=get_company_scope_key("shared_rec_spill_mart"),
                    tier="historical",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(data=df, source="Fast recommendation summary", available=True)
                mart_message = "Remote spill mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for non-default spill threshold or lookback."

        try:
            qh_cols = set(filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["WAREHOUSE_SIZE", "BYTES_SPILLED_TO_REMOTE_STORAGE"],
            ))
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" not in qh_cols:
                return _empty_result("Remote spill advisor", "QUERY_HISTORY remote spill column is not available.")
            wh_size_expr = "MAX(warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
            query_filters = get_global_filter_clause(
                date_col="start_time",
                wh_col="warehouse_name",
                user_col="user_name",
                role_col="role_name",
                db_col="database_name",
            )
            df = run_query(
                f"""
                SELECT warehouse_name, {wh_size_expr} AS warehouse_size,
                       ROUND(SUM(bytes_spilled_to_remote_storage)/POWER(1024,3), 2) AS remote_gb
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND bytes_spilled_to_remote_storage > 0
                  AND warehouse_name IS NOT NULL
                  {query_filters}
                GROUP BY warehouse_name
                HAVING remote_gb > {min_remote_gb}
                ORDER BY remote_gb DESC
                LIMIT 10
                """,
                ttl_key=get_company_scope_key("shared_rec_spill_live", days, min_remote_gb),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
            )
        except Exception as exc:
            return _empty_result("Remote spill advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse("shared_rec_spill", (company, days, min_remote_gb), _loader, force=force)


def load_shared_recommendation_failed_tasks(
    session: object,
    company: str | None = None,
    *,
    days: int = 7,
    min_failures: int = 3,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load task-failure advisor candidates once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_failures = max(0, int(min_failures or 0))

    def _loader() -> SharedMetricResult:
        mart_message = ""
        if days == 7 and min_failures <= 3:
            try:
                df = run_query(
                    build_mart_recommendation_failed_tasks_sql(company),
                    ttl_key=get_company_scope_key("shared_rec_failed_tasks_mart"),
                    tier="historical",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(data=df, source="Fast recommendation summary", available=True)
                mart_message = "Failed task mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for non-default task-failure threshold or lookback."

        try:
            failed_task_sql = build_task_failure_summary_sql(
                session,
                f"scheduled_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())",
                limit=25,
                company=company,
            )
            df = run_query(
                f"""
                WITH failed_tasks AS ({failed_task_sql})
                SELECT *
                FROM failed_tasks
                WHERE failures > {min_failures}
                ORDER BY failures DESC
                LIMIT 5
                """,
                ttl_key=get_company_scope_key("shared_rec_failed_tasks_live", days, min_failures),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
            )
        except Exception as exc:
            return _empty_result("Failed task advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse("shared_rec_failed_tasks", (company, days, min_failures), _loader, force=force)


def load_shared_recommendation_query_failures(
    company: str | None = None,
    *,
    days: int = 7,
    min_failures: int = 10,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load query-failure advisor candidates once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_failures = max(0, int(min_failures or 0))

    def _loader() -> SharedMetricResult:
        mart_message = ""
        if days == 7:
            try:
                df = run_query(
                    build_mart_recommendation_query_errors_sql(company, min_failures=min_failures),
                    ttl_key=get_company_scope_key("shared_rec_query_failures_mart", min_failures),
                    tier="historical",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(data=df, source="Fast recommendation summary", available=True)
                mart_message = "Query failure mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for non-default query-failure lookback."

        try:
            query_filters = get_global_filter_clause(
                date_col="start_time",
                wh_col="warehouse_name",
                user_col="user_name",
                role_col="role_name",
                db_col="database_name",
            )
            df = run_query(
                f"""
                SELECT warehouse_name, COUNT(*) AS failures
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND UPPER(execution_status) = 'FAILED_WITH_ERROR'
                  AND warehouse_name IS NOT NULL
                  {query_filters}
                GROUP BY warehouse_name
                HAVING failures > {min_failures}
                ORDER BY failures DESC
                LIMIT 5
                """,
                ttl_key=get_company_scope_key("shared_rec_query_failures_live", days, min_failures),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
            )
        except Exception as exc:
            return _empty_result("Query failure advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse("shared_rec_query_failures", (company, days, min_failures), _loader, force=force)
