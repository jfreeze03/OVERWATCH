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
    get_environment_case_expr,
    get_environment_filter_clause,
    get_global_db_filter_clause,
    get_global_filter_clause,
    get_global_wh_filter_clause,
    get_wh_filter_clause,
    get_user_filter_clause,
)
from .compatibility import build_task_failure_summary_sql, build_task_history_sql, filter_existing_columns
from .cost import (
    build_clustering_cost_sql,
    build_idle_warehouse_sql,
    build_metered_credit_cte,
    build_snowflake_service_cost_lens_sql,
    build_snowflake_service_cost_trend_sql,
)
from .data import normalize_df
from .mart import (
    build_mart_bill_summary_sql,
    build_mart_bill_warehouse_delta_sql,
    build_mart_recommendation_failed_tasks_sql,
    build_mart_recommendation_idle_sql,
    build_mart_recommendation_query_errors_sql,
    build_mart_recommendation_spill_sql,
    build_mart_procedure_calls_sql,
    build_mart_procedure_inventory_sql,
    build_mart_procedure_sla_sql,
    build_mart_service_login_health_sql,
    build_mart_service_query_health_sql,
    build_mart_service_task_health_sql,
    build_mart_service_warehouse_health_sql,
    build_mart_warehouse_scaling_sql,
    build_mart_storage_db_detail_sql,
    build_mart_storage_trend_sql,
    build_mart_usage_overview_sql,
    build_mart_usage_metering_sql,
    build_mart_usage_pressure_sql,
    build_mart_usage_storage_sql,
    build_mart_warehouse_overview_sql,
    build_mart_warehouse_heatmap_sql,
    build_mart_task_history_sql,
    mart_object_name,
)
from .query import run_query, run_query_or_raise, sql_literal


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


def _company_column_filter(column: str, company: str | None) -> str:
    if not company or str(company).upper() == "ALL":
        return ""
    return f"AND UPPER({column}) = UPPER({sql_literal(company, 100)})"


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


def load_shared_service_cost_lens(
    days: int,
    company: str | None = None,
    *,
    credit_price: float = 0.0,
    ai_credit_price: float = 0.0,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load official service cost movement once per scope for cost surfaces."""
    company = company or get_active_company()
    days = max(1, int(days or 7))
    credit_price = float(credit_price or 0)
    ai_credit_price = float(ai_credit_price or 0)

    def _loader() -> SharedMetricResult:
        df = run_query_or_raise(
            build_snowflake_service_cost_lens_sql(
                days,
                credit_price or None,
                ai_credit_price or None,
            ),
            ttl_key=get_company_scope_key(
                "shared_service_cost_lens_official",
                days,
                credit_price,
                ai_credit_price,
            ),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Official Cost Monitor: SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse(
        "shared_service_cost_lens",
        (company, days, credit_price, ai_credit_price),
        _loader,
        force=force,
    )


def load_shared_service_cost_trend(
    days: int,
    company: str | None = None,
    *,
    credit_price: float = 0.0,
    ai_credit_price: float = 0.0,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load daily official service cost once per scope for cost surfaces."""
    company = company or get_active_company()
    days = max(1, int(days or 7))
    credit_price = float(credit_price or 0)
    ai_credit_price = float(ai_credit_price or 0)

    def _loader() -> SharedMetricResult:
        df = run_query_or_raise(
            build_snowflake_service_cost_trend_sql(
                days,
                credit_price or None,
                ai_credit_price or None,
            ),
            ttl_key=get_company_scope_key(
                "shared_service_cost_trend_official",
                days,
                credit_price,
                ai_credit_price,
            ),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Official Cost Monitor: SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse(
        "shared_service_cost_trend",
        (company, days, credit_price, ai_credit_price),
        _loader,
        force=force,
    )


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
              {get_wh_filter_clause("q.warehouse_name", company)}
              {get_db_filter_clause("q.database_name", company)}
              {get_user_filter_clause("q.user_name", company)}
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
              {get_wh_filter_clause("q.warehouse_name", company)}
              {get_db_filter_clause("q.database_name", company)}
              {get_user_filter_clause("q.user_name", company)}
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
              {get_user_filter_clause("user_name", company)}
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

            from .compatibility import build_task_health_sql

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


def _warehouse_contains_filter(
    column: str,
    warehouse_contains: str = "",
    *,
    include_global_warehouse_filter: bool = True,
) -> str:
    warehouse_contains = str(warehouse_contains or "").strip()
    if not warehouse_contains:
        return get_global_wh_filter_clause(column) if include_global_warehouse_filter else ""
    return f"AND {column} ILIKE '%' || {sql_literal(warehouse_contains, 300)} || '%'"


def build_shared_bill_metering_summary_live_sql(
    current_start: str,
    current_end: str,
    prior_start: str,
    prior_end: str,
    *,
    company: str,
    warehouse_contains: str = "",
    include_global_warehouse_filter: bool = True,
) -> str:
    wh_filter = " ".join(filter(None, [
        get_wh_filter_clause("warehouse_name", company),
        _warehouse_contains_filter(
            "warehouse_name",
            warehouse_contains,
            include_global_warehouse_filter=include_global_warehouse_filter,
        ),
    ]))
    return f"""
        WITH bounds AS (
            SELECT
                {current_start} AS current_start,
                {current_end} AS current_end,
                {prior_start} AS prior_start,
                {prior_end} AS prior_end
        ),
        metering AS (
            SELECT 'CURRENT' AS period, warehouse_name, start_time, credits_used
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
            WHERE start_time >= current_start
              AND start_time < current_end
              {wh_filter}
            UNION ALL
            SELECT 'PRIOR' AS period, warehouse_name, start_time, credits_used
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
            WHERE start_time >= prior_start
              AND start_time < prior_end
              {wh_filter}
        )
        SELECT
            period,
            ROUND(SUM(credits_used), 4) AS credits,
            COUNT(DISTINCT warehouse_name) AS active_warehouses,
            COUNT(DISTINCT TO_DATE(start_time)) AS active_days
        FROM metering
        GROUP BY period
    """


def build_shared_bill_warehouse_delta_live_sql(
    current_start: str,
    current_end: str,
    prior_start: str,
    prior_end: str,
    *,
    company: str,
    warehouse_contains: str = "",
    include_global_warehouse_filter: bool = True,
) -> str:
    wh_filter = " ".join(filter(None, [
        get_wh_filter_clause("warehouse_name", company),
        _warehouse_contains_filter(
            "warehouse_name",
            warehouse_contains,
            include_global_warehouse_filter=include_global_warehouse_filter,
        ),
    ]))
    return f"""
        WITH bounds AS (
            SELECT
                {current_start} AS current_start,
                {current_end} AS current_end,
                {prior_start} AS prior_start,
                {prior_end} AS prior_end
        ),
        current_wh AS (
            SELECT warehouse_name, SUM(credits_used) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
            WHERE start_time >= current_start
              AND start_time < current_end
              {wh_filter}
            GROUP BY warehouse_name
        ),
        prior_wh AS (
            SELECT warehouse_name, SUM(credits_used) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
            WHERE start_time >= prior_start
              AND start_time < prior_end
              {wh_filter}
            GROUP BY warehouse_name
        )
        SELECT
            COALESCE(c.warehouse_name, p.warehouse_name) AS warehouse_name,
            ROUND(COALESCE(c.credits, 0), 4) AS current_credits,
            ROUND(COALESCE(p.credits, 0), 4) AS prior_credits,
            ROUND(COALESCE(c.credits, 0) - COALESCE(p.credits, 0), 4) AS credit_delta,
            CASE
                WHEN COALESCE(p.credits, 0) = 0 THEN NULL
                ELSE ROUND(((COALESCE(c.credits, 0) - p.credits) / NULLIF(p.credits, 0)) * 100, 2)
            END AS pct_delta
        FROM current_wh c
        FULL OUTER JOIN prior_wh p ON c.warehouse_name = p.warehouse_name
        ORDER BY ABS(COALESCE(c.credits, 0) - COALESCE(p.credits, 0)) DESC
        LIMIT 25
    """


def load_shared_bill_metering_summary(
    current_start: str,
    current_end: str,
    prior_start: str,
    prior_end: str,
    company: str | None = None,
    *,
    warehouse_contains: str = "",
    prefer_mart: bool = True,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load current/prior bill metering totals from the shared mart, then live metering."""

    company = company or get_active_company()
    warehouse_contains = str(warehouse_contains or "").strip()
    bounds = (current_start, current_end, prior_start, prior_end)

    def _loader() -> SharedMetricResult:
        if prefer_mart:
            mart_df = run_query(
                build_mart_bill_summary_sql(
                    current_start,
                    current_end,
                    prior_start,
                    prior_end,
                    company=company,
                    warehouse_contains=warehouse_contains,
                ),
                ttl_key=get_company_scope_key("shared_bill_summary_mart", *bounds, warehouse_contains),
                tier="historical",
                section=section,
            )
            if not mart_df.empty:
                return SharedMetricResult(
                    data=mart_df,
                    source="Fast billing summary",
                    available=True,
                )
            if not allow_live_fallback:
                return _empty_result(
                    "Fast billing summary",
                    message="Fast billing summary returned no rows.",
                )

        live_df = run_query(
            build_shared_bill_metering_summary_live_sql(
                current_start,
                current_end,
                prior_start,
                prior_end,
                company=company,
                warehouse_contains=warehouse_contains,
            ),
            ttl_key=get_company_scope_key("shared_bill_summary_live", *bounds, warehouse_contains),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source=(
                "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                if prefer_mart
                else "Live: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
            ),
            available=not live_df.empty,
            message="Fast billing summary unavailable or stale." if prefer_mart else "",
        )

    return _load_or_reuse(
        "shared_bill_metering_summary",
        (company, *bounds, warehouse_contains, prefer_mart, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_bill_warehouse_delta(
    current_start: str,
    current_end: str,
    prior_start: str,
    prior_end: str,
    company: str | None = None,
    *,
    warehouse_contains: str = "",
    prefer_mart: bool = True,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load current/prior warehouse bill movement from the shared mart, then live metering."""

    company = company or get_active_company()
    warehouse_contains = str(warehouse_contains or "").strip()
    bounds = (current_start, current_end, prior_start, prior_end)

    def _loader() -> SharedMetricResult:
        if prefer_mart:
            mart_df = run_query(
                build_mart_bill_warehouse_delta_sql(
                    current_start,
                    current_end,
                    prior_start,
                    prior_end,
                    company=company,
                    warehouse_contains=warehouse_contains,
                ),
                ttl_key=get_company_scope_key("shared_bill_warehouse_delta_mart", *bounds, warehouse_contains),
                tier="historical",
                section=section,
            )
            if not mart_df.empty:
                return SharedMetricResult(
                    data=mart_df,
                    source="Fast billing summary",
                    available=True,
                )
            if not allow_live_fallback:
                return _empty_result(
                    "Fast billing summary",
                    message="Fast warehouse movement summary returned no rows.",
                )

        live_df = run_query(
            build_shared_bill_warehouse_delta_live_sql(
                current_start,
                current_end,
                prior_start,
                prior_end,
                company=company,
                warehouse_contains=warehouse_contains,
            ),
            ttl_key=get_company_scope_key("shared_bill_warehouse_delta_live", *bounds, warehouse_contains),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source=(
                "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                if prefer_mart
                else "Live: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
            ),
            available=not live_df.empty,
            message="Fast warehouse movement summary unavailable or stale." if prefer_mart else "",
        )

    return _load_or_reuse(
        "shared_bill_warehouse_delta",
        (company, *bounds, warehouse_contains, prefer_mart, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_warehouse_credit_anomalies(
    company: str | None = None,
    *,
    days: int = 30,
    zscore_threshold: float = 1.5,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load completed-day warehouse credit anomalies from the shared mart first."""

    company = company or get_active_company()
    days = max(7, int(days or 30))
    zscore_threshold = float(zscore_threshold or 1.5)
    scan_days = days + 7

    def _anomaly_sql(source_table: str, date_col: str, credit_col: str, extra_filter: str = "") -> str:
        return f"""
            WITH daily AS (
                SELECT
                    warehouse_name,
                    DATE_TRUNC('day', {date_col}) AS day,
                    SUM(COALESCE({credit_col}, 0)) AS daily_credits
                FROM {source_table}
                WHERE {date_col} >= DATEADD('day', -{scan_days}, CURRENT_TIMESTAMP())
                  AND {date_col} < CURRENT_DATE()
                  AND warehouse_name IS NOT NULL
                  {extra_filter}
                GROUP BY warehouse_name, day
            ),
            stats AS (
                SELECT
                    warehouse_name,
                    day,
                    daily_credits,
                    AVG(daily_credits) OVER (
                        PARTITION BY warehouse_name
                        ORDER BY day ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                    ) AS rolling_avg,
                    STDDEV(daily_credits) OVER (
                        PARTITION BY warehouse_name
                        ORDER BY day ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                    ) AS rolling_std
                FROM daily
            )
            SELECT
                warehouse_name,
                day,
                ROUND(daily_credits, 4) AS daily_credits,
                ROUND(rolling_avg, 4) AS rolling_avg,
                ROUND((daily_credits - rolling_avg) / NULLIF(rolling_std, 0), 2) AS zscore,
                CASE
                    WHEN (daily_credits - rolling_avg) / NULLIF(rolling_std, 0) > 2 THEN 'SPIKE'
                    WHEN (daily_credits - rolling_avg) / NULLIF(rolling_std, 0) > {zscore_threshold} THEN 'ELEVATED'
                    ELSE NULL
                END AS anomaly_flag
            FROM stats
            WHERE day >= DATEADD('day', -{days}, CURRENT_DATE())
              AND rolling_avg IS NOT NULL
              AND rolling_std > 0
              AND (daily_credits - rolling_avg) / NULLIF(rolling_std, 0) > {zscore_threshold}
            ORDER BY day DESC, zscore DESC, daily_credits DESC
        """

    def _loader() -> SharedMetricResult:
        mart_message = ""
        try:
            mart_df = run_query(
                _anomaly_sql(
                    mart_object_name("FACT_WAREHOUSE_HOURLY"),
                    "hour_start",
                    "credits_used",
                    "\n                  ".join(
                        filter(
                            None,
                            [
                                _company_column_filter("company", company),
                                get_global_wh_filter_clause("warehouse_name"),
                            ],
                        )
                    ),
                ),
                ttl_key=get_company_scope_key("shared_warehouse_credit_anomalies_mart", days, zscore_threshold),
                tier="historical",
                section=section,
            )
            if not mart_df.empty:
                return SharedMetricResult(
                    data=mart_df,
                    source="Fast warehouse credit summary",
                    available=True,
                    effective_days=days,
                )
            mart_message = "Warehouse credit summary returned no anomaly rows."
        except Exception as exc:
            mart_message = str(exc)

        if not allow_live_fallback:
            return _empty_result("Fast warehouse credit summary", mart_message, effective_days=days)

        try:
            live_df = run_query(
                _anomaly_sql(
                    "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                    "start_time",
                    "credits_used",
                    "\n                  ".join(
                        filter(
                            None,
                            [
                                get_wh_filter_clause("warehouse_name", company),
                                get_global_wh_filter_clause("warehouse_name"),
                            ],
                        )
                    ),
                ),
                ttl_key=get_company_scope_key("shared_warehouse_credit_anomalies_live", days, zscore_threshold),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=live_df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                available=not live_df.empty,
                message="" if not live_df.empty else mart_message,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Warehouse credit anomalies", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse(
        "shared_warehouse_credit_anomalies",
        (company, days, zscore_threshold, allow_live_fallback),
        _loader,
        force=force,
    )


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


def _warehouse_health_exprs(session: object) -> dict[str, str]:
    """Return Warehouse Health QUERY_HISTORY expressions across Snowflake versions."""

    qh_cols = set(
        filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            [
                "WAREHOUSE_SIZE",
                "QUEUED_OVERLOAD_TIME",
                "BYTES_SPILLED_TO_LOCAL_STORAGE",
                "BYTES_SPILLED_TO_REMOTE_STORAGE",
                "PERCENTAGE_SCANNED_FROM_CACHE",
            ],
        )
    )
    return {
        "wh_size_expr": "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "plain_wh_size_expr": "MAX(warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR",
        "queue_sum_expr": "SUM(q.queued_overload_time)" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0",
        "remote_spill_sum_expr": (
            "SUM(q.bytes_spilled_to_remote_storage)"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "local_spill_expr": (
            "SUM(bytes_spilled_to_local_storage)"
            if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
            else "0"
        ),
        "local_spill_row_expr": (
            "bytes_spilled_to_local_storage"
            if "BYTES_SPILLED_TO_LOCAL_STORAGE" in qh_cols
            else "0"
        ),
        "remote_spill_expr": (
            "SUM(bytes_spilled_to_remote_storage)"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "remote_spill_row_expr": (
            "bytes_spilled_to_remote_storage"
            if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
            else "0"
        ),
        "cache_expr": "AVG(q.percentage_scanned_from_cache)" if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols else "0",
    }


def load_shared_warehouse_efficiency(
    session: object,
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load Warehouse Health efficiency risks through one explicit drilldown query."""

    company = company or get_active_company()
    days = max(1, int(days or 7))

    def _loader() -> SharedMetricResult:
        exprs = _warehouse_health_exprs(session)
        query_filters = get_global_filter_clause(
            date_col="q.start_time",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            db_col="q.database_name",
        )
        df = run_query(
            f"""
            WITH {build_metered_credit_cte(days_back=days, include_recent=True)}
            SELECT q.warehouse_name,
                   {exprs["wh_size_expr"]} AS warehouse_size,
                   COUNT(*) AS query_count,
                   ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS metered_credits,
                   ROUND(SUM(COALESCE(pqc.metered_credits, 0)) / NULLIF(COUNT(*), 0), 6) AS credits_per_query,
                   ROUND({exprs["queue_sum_expr"]} / 1000 / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 2) AS queue_sec_per_credit,
                   ROUND({exprs["remote_spill_sum_expr"]} / POWER(1024,3) / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 2) AS remote_spill_gb_per_credit,
                   ROUND({exprs["cache_expr"]}, 2) AS avg_cache_pct,
                   ROUND(100
                         - LEAST(COALESCE({exprs["queue_sum_expr"]} / 1000 / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 0), 25)
                         - LEAST(COALESCE({exprs["remote_spill_sum_expr"]} / POWER(1024,3) / NULLIF(SUM(COALESCE(pqc.metered_credits, 0)), 0), 0), 25)
                         - LEAST(COALESCE(SUM(COALESCE(pqc.metered_credits, 0)) / NULLIF(COUNT(*), 0), 0) * 10, 25),
                         1) AS efficiency_score
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
            WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {query_filters}
            GROUP BY q.warehouse_name
            ORDER BY efficiency_score ASC, metered_credits DESC
            LIMIT 200
            """,
            ttl_key=get_company_scope_key("shared_warehouse_efficiency", days),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY + query-attributed metering",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_warehouse_efficiency", (company, days), _loader, force=force)


def load_shared_warehouse_spill(
    session: object,
    days: int,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load Warehouse Health spill and memory pressure through one explicit drilldown query."""

    company = company or get_active_company()
    days = max(1, int(days or 7))

    def _loader() -> SharedMetricResult:
        exprs = _warehouse_health_exprs(session)
        query_filters = get_global_filter_clause(
            date_col="start_time",
            wh_col="warehouse_name",
            user_col="user_name",
            role_col="role_name",
            db_col="database_name",
        )
        df = run_query(
            f"""
            SELECT warehouse_name, {exprs["plain_wh_size_expr"]} AS warehouse_size,
                   COUNT(*) AS spill_query_count,
                   ROUND({exprs["local_spill_expr"]}/POWER(1024,3),2) AS local_spill_gb,
                   ROUND({exprs["remote_spill_expr"]}/POWER(1024,3),2) AS remote_spill_gb,
                   ROUND(AVG(total_elapsed_time)/1000,2) AS avg_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND ({exprs["local_spill_row_expr"]} > 0 OR {exprs["remote_spill_row_expr"]} > 0)
              AND warehouse_name IS NOT NULL
              {query_filters}
            GROUP BY warehouse_name
            ORDER BY local_spill_gb + remote_spill_gb DESC
            """,
            ttl_key=get_company_scope_key("shared_warehouse_spill", days),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_warehouse_spill", (company, days), _loader, force=force)


def load_shared_warehouse_heatmap(
    days: int,
    company: str | None = None,
    *,
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load Warehouse Health heatmap from mart first with bounded live fallback."""

    company = company or get_active_company()
    days = max(1, int(days or 30))

    def _loader() -> SharedMetricResult:
        mart_sql = build_mart_warehouse_heatmap_sql(
            days,
            company=company,
            warehouse_contains=warehouse_contains,
            user_contains=user_contains,
            role_contains=role_contains,
            database_contains=database_contains,
            start_date=start_date,
            end_date=end_date,
        )
        mart_df = run_query(
            mart_sql,
            ttl_key=get_company_scope_key("shared_warehouse_heatmap_mart", days),
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

        live_days = min(days, 30)
        query_filters = get_global_filter_clause(
            date_col="start_time",
            wh_col="warehouse_name",
            user_col="user_name",
            role_col="role_name",
            db_col="database_name",
        )
        live_df = run_query(
            f"""
            SELECT warehouse_name,
                   DAYOFWEEK(start_time) AS day_of_week,
                   HOUR(start_time) AS hour_of_day,
                   COUNT(*) AS query_count,
                   ROUND(AVG(total_elapsed_time)/1000,2) AS avg_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE start_time >= DATEADD('day', -{live_days}, CURRENT_TIMESTAMP())
              AND warehouse_name IS NOT NULL
              {query_filters}
            GROUP BY warehouse_name, day_of_week, hour_of_day
            ORDER BY warehouse_name, day_of_week, hour_of_day
            """,
            ttl_key=get_company_scope_key("shared_warehouse_heatmap_live", live_days),
            tier="historical",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Bounded live warehouse history",
            available=not live_df.empty,
            message=(
                "Workload heatmap live fallback is capped at 30 days to avoid broad query-history scans."
                if live_days < days
                else ""
            ),
            effective_days=live_days,
        )

    return _load_or_reuse(
        "shared_warehouse_heatmap",
        (
            company,
            days,
            warehouse_contains,
            user_contains,
            role_contains,
            database_contains,
            start_date,
            end_date,
        ),
        _loader,
        force=force,
    )


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


def load_shared_task_history_detail(
    session: object,
    days: int,
    company: str | None = None,
    *,
    database_contains: str = "",
    limit: int = 1000,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load task-history detail once for Task Management and DBA detail paths."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    database_contains = str(database_contains or "").strip()
    limit = max(1, int(limit or 1000))

    def _loader() -> SharedMetricResult:
        mart_message = ""
        try:
            mart_df = run_query(
                build_mart_task_history_sql(
                    days,
                    company=company,
                    database_contains=database_contains,
                    limit=limit,
                ),
                ttl_key=get_company_scope_key("shared_task_history_detail_mart", company, days, database_contains, limit),
                tier="historical",
                section=section,
            )
            if not mart_df.empty:
                return SharedMetricResult(
                    data=mart_df,
                    source="Fast task run summary",
                    available=True,
                    effective_days=days,
                )
            mart_message = "Fast task run summary returned no rows."
        except Exception as exc:
            mart_message = f"Fast task run summary unavailable: {exc}"

        if not allow_live_fallback:
            return _empty_result("Fast task run summary", mart_message, effective_days=days)

        try:
            live_df = run_query(
                build_task_history_sql(
                    session,
                    f"scheduled_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())",
                    limit=limit,
                    company=company,
                ),
                ttl_key=get_company_scope_key("shared_task_history_detail_live", company, days, database_contains, limit),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=live_df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                available=not live_df.empty,
                message=mart_message,
                effective_days=days,
            )
        except Exception as exc:
            message = f"{mart_message} Live fallback unavailable: {exc}".strip()
            return _empty_result(
                "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
                message,
                effective_days=days,
            )

    return _load_or_reuse(
        "shared_task_history_detail",
        (company, days, database_contains, limit, allow_live_fallback),
        _loader,
        force=force,
    )


def shared_mfa_count_expr(user_cols: set[str]) -> str:
    """Return a compatible aggregate expression for active users missing MFA."""
    normalized = {str(col or "").upper() for col in user_cols}
    if "HAS_MFA" in normalized:
        return "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_mfa)), FALSE) = FALSE)"
    if "EXT_AUTHN_DUO" in normalized:
        return "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(ext_authn_duo)), FALSE) = FALSE)"
    return "NULL::NUMBER"


def shared_mfa_gap_predicate(user_cols: set[str], alias: str = "u") -> str:
    """Return a compatible row predicate for active users missing MFA."""
    normalized = {str(col or "").upper() for col in user_cols}
    prefix = f"{alias}." if alias else ""
    if "HAS_MFA" in normalized:
        return f"AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR({prefix}has_mfa)), FALSE) = FALSE"
    if "EXT_AUTHN_DUO" in normalized:
        return f"AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR({prefix}ext_authn_duo)), FALSE) = FALSE"
    return "AND 1 = 0"


def shared_mfa_proof_label(user_cols: set[str]) -> str:
    """Return the source label used for MFA exception proof rows."""
    normalized = {str(col or "").upper() for col in user_cols}
    if "HAS_MFA" in normalized:
        return "ACCOUNT_USAGE.USERS HAS_MFA signal"
    if "EXT_AUTHN_DUO" in normalized:
        return "ACCOUNT_USAGE.USERS EXT_AUTHN_DUO signal"
    return "ACCOUNT_USAGE.USERS MFA signal unavailable"


def _shared_user_exprs_from_columns(user_cols: set[str] | list[str] | tuple[str, ...]) -> dict[str, str]:
    """Return USERS projections for MFA/password signals from discovered columns."""
    user_cols = {str(col or "").upper() for col in user_cols}
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


def _shared_user_exprs(session: object) -> dict[str, str]:
    """Return USERS projections for MFA/password signals across Snowflake versions."""
    from .compatibility import filter_existing_columns

    user_cols = filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.USERS",
        ["HAS_MFA", "EXT_AUTHN_DUO", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
    )
    return _shared_user_exprs_from_columns(user_cols)


def _shared_security_user_columns(session: object) -> set[str]:
    return set(
        filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.USERS",
            ["HAS_MFA", "EXT_AUTHN_DUO", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
        )
    )


def build_shared_security_summary_sql(session: object, days: int, company: str) -> tuple[str, str]:
    """Build live ACCOUNT_USAGE security summary and exception SQL."""
    days = max(1, int(days or 30))
    user_cols = _shared_security_user_columns(session)
    mfa_count_expr = shared_mfa_count_expr(user_cols)
    mfa_gap_predicate = shared_mfa_gap_predicate(user_cols)
    mfa_proof = shared_mfa_proof_label(user_cols)
    password_count_expr = (
        "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_password)), FALSE) = TRUE)"
        if "HAS_PASSWORD" in user_cols else "NULL::NUMBER"
    )
    last_seen_expr = "u.last_success_login" if "LAST_SUCCESS_LOGIN" in user_cols else "u.created_on"
    user_filter_lh = get_user_filter_clause("lh.user_name")
    user_filter_u = get_user_filter_clause("u.name")
    user_filter_g = get_user_filter_clause("g.grantee_name")
    db_filter = get_db_filter_clause("d.database_name")
    object_grant_db_filter = get_db_filter_clause("gor.table_catalog")
    company_label = sql_literal(company, 100)

    summary_sql = f"""
    WITH login_events AS (
        SELECT
            COUNT(*) AS login_events,
            COUNT_IF(lh.is_success = 'NO') AS failed_logins,
            COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.user_name, NULL)) AS failed_users,
            COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.client_ip, NULL)) AS failed_ips
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
        WHERE lh.event_timestamp >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {user_filter_lh}
    ),
    users AS (
        SELECT
            COUNT(*) AS active_users,
            {mfa_count_expr} AS users_without_mfa,
            {password_count_expr} AS password_users
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
    ),
    recent_grants AS (
        SELECT COUNT(*) AS recent_grants
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
        WHERE g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {user_filter_g}
    ),
    shared_dbs AS (
        SELECT COUNT(*) AS shared_databases
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES d
        WHERE d.deleted IS NULL
          AND d.type IN ('IMPORTED DATABASE', 'SHARE')
          {db_filter}
    )
    SELECT
        {company_label} AS company,
        login_events.login_events,
        login_events.failed_logins,
        login_events.failed_users,
        login_events.failed_ips,
        users.active_users,
        users.users_without_mfa,
        users.password_users,
        recent_grants.recent_grants AS recent_grants,
        shared_dbs.shared_databases
    FROM login_events, users, recent_grants, shared_dbs
    """
    exceptions_sql = f"""
    WITH failed_logins AS (
        SELECT
            'Failed Login' AS finding_type,
            IFF(COUNT(*) >= 25 OR COUNT(DISTINCT client_ip) >= 5, 'High', 'Medium') AS severity,
            user_name AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT client_ip) AS distinct_sources,
            MAX(event_timestamp) AS last_seen,
            'LOGIN_HISTORY failed login attempts by user/IP' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
        WHERE lh.event_timestamp >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND lh.is_success = 'NO'
          {user_filter_lh}
        GROUP BY user_name
        HAVING COUNT(*) >= 3
    ),
    mfa_gaps AS (
        SELECT
            'MFA Gap' AS finding_type,
            'High' AS severity,
            u.name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            COALESCE({last_seen_expr}, u.created_on) AS last_seen,
            '{mfa_proof}' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
          {mfa_gap_predicate}
    ),
    recent_grants AS (
        SELECT
            'Recent Grant' AS finding_type,
            IFF(COUNT(*) >= 10, 'Medium', 'Low') AS severity,
            g.grantee_name AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT g.role) AS distinct_sources,
            MAX(g.created_on) AS last_seen,
            'ACCOUNT_USAGE.GRANTS_TO_USERS active grants created recently' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
        WHERE g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {user_filter_g}
        GROUP BY g.grantee_name
        HAVING COUNT(*) >= 3
    ),
    object_grants AS (
        SELECT
            'Object Grant' AS finding_type,
            IFF(COUNT(*) >= 10 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0, 'High', 'Medium') AS severity,
            COALESCE(gor.table_catalog || '.' || gor.table_schema || '.' || gor.name, gor.table_catalog, gor.name) AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT gor.grantee_name) AS distinct_sources,
            MAX(gor.created_on) AS last_seen,
            'ACCOUNT_USAGE.GRANTS_TO_ROLES object grants by database/schema/object' AS proof_query,
            gor.table_catalog AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES gor
        WHERE gor.deleted_on IS NULL
          AND gor.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND gor.table_catalog IS NOT NULL
          {object_grant_db_filter}
        GROUP BY gor.table_catalog, gor.table_schema, gor.name
        HAVING COUNT(*) >= 3 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0
    ),
    shared_exposure AS (
        SELECT
            'Shared Database Exposure' AS finding_type,
            'Medium' AS severity,
            d.database_name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            d.created AS last_seen,
            'ACCOUNT_USAGE.DATABASES imported database/share metadata' AS proof_query,
            d.database_name AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES d
        WHERE d.deleted IS NULL
          AND d.type IN ('IMPORTED DATABASE', 'SHARE')
          {db_filter}
    )
    SELECT * FROM failed_logins
    UNION ALL
    SELECT * FROM mfa_gaps
    UNION ALL
    SELECT * FROM recent_grants
    UNION ALL
    SELECT * FROM object_grants
    UNION ALL
    SELECT * FROM shared_exposure
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        event_count DESC,
        last_seen DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def build_shared_security_mart_brief_sql(session: object, days: int, company: str) -> tuple[str, str]:
    """Build mart-backed security summary SQL with bounded live metadata."""
    days = max(1, int(days or 30))
    user_cols = _shared_security_user_columns(session)
    mfa_count_expr = shared_mfa_count_expr(user_cols)
    mfa_gap_predicate = shared_mfa_gap_predicate(user_cols)
    mfa_proof = shared_mfa_proof_label(user_cols)
    password_count_expr = (
        "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_password)), FALSE) = TRUE)"
        if "HAS_PASSWORD" in user_cols else "NULL::NUMBER"
    )
    last_seen_expr = "u.last_success_login" if "LAST_SUCCESS_LOGIN" in user_cols else "u.created_on"
    user_filter_lh = get_user_filter_clause("lh.user_name")
    user_filter_u = get_user_filter_clause("u.name")
    user_filter_g = get_user_filter_clause("g.grantee_name")
    db_filter = get_db_filter_clause("d.database_name")
    object_grant_db_filter = get_db_filter_clause("gor.table_catalog")
    login_table = mart_object_name("FACT_LOGIN_DAILY")
    grant_table = mart_object_name("FACT_GRANT_DAILY")
    login_company_filter = "" if str(company or "").upper() == "ALL" else f"AND lh.company = {sql_literal(company, 100)}"
    grant_company_filter = "" if str(company or "").upper() == "ALL" else f"AND g.company = {sql_literal(company, 100)}"
    company_label = sql_literal(company, 100)

    summary_sql = f"""
    WITH login_events AS (
        SELECT
            COALESCE(SUM(success_count), 0) + COALESCE(SUM(failure_count), 0) AS login_events,
            COALESCE(SUM(failure_count), 0) AS failed_logins,
            COUNT(DISTINCT IFF(COALESCE(failure_count, 0) > 0, lh.user_name, NULL)) AS failed_users,
            COUNT(DISTINCT IFF(COALESCE(failure_count, 0) > 0, lh.client_ip, NULL)) AS failed_ips
        FROM {login_table} lh
        WHERE lh.login_date >= DATEADD('day', -{days}, CURRENT_DATE())
          {login_company_filter}
          {user_filter_lh}
    ),
    users AS (
        SELECT
            COUNT(*) AS active_users,
            {mfa_count_expr} AS users_without_mfa,
            {password_count_expr} AS password_users
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
    ),
    recent_grants AS (
        SELECT COALESCE(SUM(grant_count), 0) AS recent_grants
        FROM {grant_table} g
        WHERE 1 = 1
          {grant_company_filter}
          AND g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {user_filter_g}
    ),
    shared_dbs AS (
        SELECT COUNT(*) AS shared_databases
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES d
        WHERE d.deleted IS NULL
          AND d.type IN ('IMPORTED DATABASE', 'SHARE')
          {db_filter}
    )
    SELECT
        {company_label} AS company,
        login_events.login_events,
        login_events.failed_logins,
        login_events.failed_users,
        login_events.failed_ips,
        users.active_users,
        users.users_without_mfa,
        users.password_users,
        recent_grants.recent_grants AS recent_grants,
        shared_dbs.shared_databases
    FROM login_events, users, recent_grants, shared_dbs
    """
    exceptions_sql = f"""
    WITH failed_logins AS (
        SELECT
            'Failed Login' AS finding_type,
            IFF(SUM(failure_count) >= 25 OR COUNT(DISTINCT client_ip) >= 5, 'High', 'Medium') AS severity,
            user_name AS entity,
            COALESCE(SUM(failure_count), 0) AS event_count,
            COUNT(DISTINCT client_ip) AS distinct_sources,
            MAX(login_date)::TIMESTAMP_NTZ AS last_seen,
            'FACT_LOGIN_DAILY failed login attempts by user/IP' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM {login_table} lh
        WHERE lh.login_date >= DATEADD('day', -{days}, CURRENT_DATE())
          {login_company_filter}
          AND COALESCE(failure_count, 0) > 0
          {user_filter_lh}
        GROUP BY user_name
        HAVING COALESCE(SUM(failure_count), 0) >= 3
    ),
    mfa_gaps AS (
        SELECT
            'MFA Gap' AS finding_type,
            'High' AS severity,
            u.name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            COALESCE({last_seen_expr}, u.created_on) AS last_seen,
            '{mfa_proof}' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
          {mfa_gap_predicate}
    ),
    recent_grants AS (
        SELECT
            'Recent Grant' AS finding_type,
            IFF(SUM(grant_count) >= 10, 'Medium', 'Low') AS severity,
            g.grantee_name AS entity,
            COALESCE(SUM(grant_count), 0) AS event_count,
            COUNT(DISTINCT g.role_name) AS distinct_sources,
            MAX(g.created_on) AS last_seen,
            'FACT_GRANT_DAILY active grants created recently' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM {grant_table} g
        WHERE 1 = 1
          {grant_company_filter}
          AND g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {user_filter_g}
        GROUP BY g.grantee_name
        HAVING COALESCE(SUM(grant_count), 0) >= 3
    ),
    object_grants AS (
        SELECT
            'Object Grant' AS finding_type,
            IFF(COUNT(*) >= 10 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0, 'High', 'Medium') AS severity,
            COALESCE(gor.table_catalog || '.' || gor.table_schema || '.' || gor.name, gor.table_catalog, gor.name) AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT gor.grantee_name) AS distinct_sources,
            MAX(gor.created_on) AS last_seen,
            'ACCOUNT_USAGE.GRANTS_TO_ROLES object grants by database/schema/object' AS proof_query,
            gor.table_catalog AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES gor
        WHERE gor.deleted_on IS NULL
          AND gor.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND gor.table_catalog IS NOT NULL
          {object_grant_db_filter}
        GROUP BY gor.table_catalog, gor.table_schema, gor.name
        HAVING COUNT(*) >= 3 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0
    ),
    shared_exposure AS (
        SELECT
            'Shared Database Exposure' AS finding_type,
            'Medium' AS severity,
            d.database_name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            d.created AS last_seen,
            'ACCOUNT_USAGE.DATABASES imported database/share metadata' AS proof_query,
            d.database_name AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES d
        WHERE d.deleted IS NULL
          AND d.type IN ('IMPORTED DATABASE', 'SHARE')
          {db_filter}
    )
    SELECT * FROM failed_logins
    UNION ALL
    SELECT * FROM mfa_gaps
    UNION ALL
    SELECT * FROM recent_grants
    UNION ALL
    SELECT * FROM object_grants
    UNION ALL
    SELECT * FROM shared_exposure
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        event_count DESC,
        last_seen DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def build_shared_security_privileged_grant_review_sql(
    days: int,
    company: str,
    environment: str = "ALL",
) -> str:
    """Return high-risk account-role and object grants with environment-aware object scope."""

    days = max(1, min(int(days or 30), 90))
    user_filter = get_user_filter_clause("gtu.grantee_name")
    object_env_filter = get_environment_filter_clause(
        "gor.table_catalog",
        environment=environment,
        company=company,
    )
    object_env_expr = get_environment_case_expr("gor.table_catalog")
    return f"""WITH privileged_role_grants AS (
    SELECT
        'Privileged Role Grant' AS finding_type,
        IFF(UPPER(gtu.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN'), 'Critical', 'High') AS severity,
        gtu.grantee_name AS entity,
        gtu.role AS role_name,
        NULL::VARCHAR AS privilege,
        FALSE AS grant_option,
        NULL::VARCHAR AS object_name,
        NULL::VARCHAR AS database_name,
        FALSE AS database_context,
        'No Database Context' AS environment,
        'ACCOUNT_USAGE.GRANTS_TO_USERS privileged role grants' AS proof_query,
        gtu.granted_by,
        gtu.created_on,
        DATEDIFF('day', gtu.created_on, CURRENT_TIMESTAMP()) AS grant_age_days,
        'Business justification, ticket/reference, review-by date, and telemetry status required.' AS proof_required,
        'Review account-level privileged role grant; do not hide this row behind a database environment filter.' AS next_action
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS gtu
    WHERE gtu.deleted_on IS NULL
      AND (
          UPPER(gtu.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN')
          OR UPPER(gtu.role) ILIKE '%ADMIN%'
          OR UPPER(gtu.role) ILIKE '%SECURITY%'
      )
      {user_filter}
),
object_privilege_grants AS (
    SELECT
        'Privileged Object Grant' AS finding_type,
        IFF(
            UPPER(gor.privilege) IN ('OWNERSHIP', 'APPLY MASKING POLICY', 'APPLY ROW ACCESS POLICY')
            OR COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true',
            'High',
            'Medium'
        ) AS severity,
        gor.grantee_name AS entity,
        NULL::VARCHAR AS role_name,
        gor.privilege AS privilege,
        COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true' AS grant_option,
        gor.name AS object_name,
        gor.table_catalog AS database_name,
        TRUE AS database_context,
        {object_env_expr} AS environment,
        'ACCOUNT_USAGE.GRANTS_TO_ROLES privileged object grants' AS proof_query,
        gor.granted_by,
        gor.created_on,
        DATEDIFF('day', gor.created_on, CURRENT_TIMESTAMP()) AS grant_age_days,
        'Privilege justification, ticket/reference, review-by date, and rollback status required.' AS proof_required,
        'Review database-scoped object privilege before revoke/narrowing action.' AS next_action
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES gor
    WHERE gor.deleted_on IS NULL
      AND gor.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND gor.table_catalog IS NOT NULL
      AND (
          UPPER(gor.privilege) IN (
              'OWNERSHIP',
              'MANAGE GRANTS',
              'APPLY MASKING POLICY',
              'APPLY ROW ACCESS POLICY',
              'CREATE DATABASE ROLE',
              'CREATE SCHEMA',
              'CREATE TABLE',
              'CREATE VIEW'
          )
          OR COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true'
      )
      {object_env_filter}
)
SELECT
    finding_type,
    severity,
    entity,
    role_name,
    privilege,
    grant_option,
    object_name,
    database_name,
    database_context,
    environment,
    proof_query,
    granted_by,
    created_on,
    grant_age_days,
    proof_required,
    next_action
FROM privileged_role_grants
UNION ALL
SELECT
    finding_type,
    severity,
    entity,
    role_name,
    privilege,
    grant_option,
    object_name,
    database_name,
    database_context,
    environment,
    proof_query,
    granted_by,
    created_on,
    grant_age_days,
    proof_required,
    next_action
FROM object_privilege_grants
ORDER BY
    CASE severity WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
    created_on DESC
LIMIT 200""".strip()


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


def build_shared_access_hygiene_sql(
    session: object,
    days: int,
    company: str | None = None,
    environment: str = "ALL",
    *,
    user_columns: set[str] | list[str] | tuple[str, ...] | None = None,
) -> str:
    """Build account-level user/login/grant hygiene SQL for shared security surfaces."""
    company = company or get_active_company()
    days = max(1, int(days or 30))
    env_label = sql_literal(str(environment or "ALL"), 100)
    exprs = (
        _shared_user_exprs_from_columns(user_columns)
        if user_columns is not None
        else _shared_user_exprs(session)
    )
    return f"""
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
            """.strip()


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

    def _loader() -> SharedMetricResult:
        df = run_query(
            build_shared_access_hygiene_sql(session, days, company, environment),
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
    allow_live_fallback: bool = True,
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

        if not allow_live_fallback:
            return _empty_result("Fast recommendation summary", mart_message)

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

    return _load_or_reuse(
        "shared_rec_idle",
        (company, days, min_idle_credits, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_recommendation_spill_warehouses(
    session: object,
    company: str | None = None,
    *,
    days: int = 7,
    min_remote_gb: float = 5.0,
    allow_live_fallback: bool = True,
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

        if not allow_live_fallback:
            return _empty_result("Fast recommendation summary", mart_message)

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

    return _load_or_reuse(
        "shared_rec_spill",
        (company, days, min_remote_gb, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_recommendation_failed_tasks(
    session: object,
    company: str | None = None,
    *,
    days: int = 7,
    min_failures: int = 3,
    allow_live_fallback: bool = True,
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

        if not allow_live_fallback:
            return _empty_result("Fast recommendation summary", mart_message)

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

    return _load_or_reuse(
        "shared_rec_failed_tasks",
        (company, days, min_failures, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_recommendation_query_failures(
    company: str | None = None,
    *,
    days: int = 7,
    min_failures: int = 10,
    allow_live_fallback: bool = True,
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

        if not allow_live_fallback:
            return _empty_result("Fast recommendation summary", mart_message)

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

    return _load_or_reuse(
        "shared_rec_query_failures",
        (company, days, min_failures, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_recommendation_storage_retention(
    company: str | None = None,
    *,
    min_time_travel_tb: float = 0.25,
    min_time_travel_ratio: float = 0.25,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load time-travel-heavy database candidates once for recommendation surfaces."""

    company = company or get_active_company()
    min_time_travel_tb = float(min_time_travel_tb or 0)
    min_time_travel_ratio = float(min_time_travel_ratio or 0)

    def _loader() -> SharedMetricResult:
        try:
            df = run_query(
                f"""
                SELECT table_catalog AS database_name,
                       ROUND(SUM(COALESCE(active_bytes, 0)) / POWER(1024, 4), 3) AS active_tb,
                       ROUND(SUM(COALESCE(time_travel_bytes, 0)) / POWER(1024, 4), 3) AS time_travel_tb,
                       ROUND(SUM(COALESCE(failsafe_bytes, 0)) / POWER(1024, 4), 3) AS failsafe_tb
                FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
                WHERE (deleted IS NULL OR deleted = FALSE)
                  AND table_catalog IS NOT NULL
                  {get_db_filter_clause("table_catalog", company)}
                GROUP BY table_catalog
                HAVING time_travel_tb >= {min_time_travel_tb}
                   AND time_travel_tb >= active_tb * {min_time_travel_ratio}
                ORDER BY time_travel_tb DESC
                LIMIT 10
                """,
                ttl_key=get_company_scope_key(
                    "shared_rec_storage_retention",
                    min_time_travel_tb,
                    min_time_travel_ratio,
                ),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live: SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS",
                available=not df.empty,
            )
        except Exception as exc:
            return _empty_result("Storage retention advisor", f"Live storage-retention scan unavailable: {exc}")

    return _load_or_reuse(
        "shared_rec_storage_retention",
        (company, min_time_travel_tb, min_time_travel_ratio),
        _loader,
        force=force,
    )


def load_shared_recommendation_clustering_cost(
    company: str | None = None,
    *,
    days: int = 7,
    credit_price: float = 0.0,
    top: int = 10,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load automatic clustering cost candidates once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    top = max(1, int(top or 10))
    credit_price = float(credit_price or 0)

    def _loader() -> SharedMetricResult:
        try:
            df = run_query(
                build_clustering_cost_sql(days, company=company, credit_price=credit_price or None, top=top),
                ttl_key=get_company_scope_key("shared_rec_clustering_cost", days, credit_price, top),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live: SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY",
                available=not df.empty,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Clustering cost advisor", f"Live clustering-cost scan unavailable: {exc}")

    return _load_or_reuse("shared_rec_clustering_cost", (company, days, credit_price, top), _loader, force=force)


def load_shared_recommendation_repeated_queries(
    session: object,
    company: str | None = None,
    *,
    days: int = 7,
    min_runs: int = 50,
    min_total_exec_hours: float = 2.0,
    allow_live_fallback: bool = True,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load repeated expensive query patterns once for recommendation surfaces."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_runs = max(1, int(min_runs or 1))
    min_total_exec_hours = float(min_total_exec_hours or 0)

    def _loader() -> SharedMetricResult:
        mart_message = ""
        query_filters = get_global_filter_clause(
            date_col="start_time",
            wh_col="warehouse_name",
            user_col="user_name",
            role_col="role_name",
            db_col="database_name",
        )
        if days <= 30:
            try:
                table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
                df = run_query(
                    f"""
                    SELECT query_hash,
                           COUNT(*) AS runs,
                           COUNT(DISTINCT user_name) AS user_count,
                           ROUND(SUM(COALESCE(total_elapsed_time, 0)) / 1000 / 3600, 2) AS total_exec_hours,
                           ROUND(SUM(COALESCE(bytes_scanned, 0)) / POWER(1024, 4), 2) AS tb_scanned,
                           SUBSTR(MAX(query_text), 1, 500) AS sample_query,
                           'QUERY_HASH' AS hash_column
                    FROM {table}
                    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      AND UPPER(COALESCE(execution_status, '')) = 'SUCCESS'
                      AND query_hash IS NOT NULL
                      {_company_column_filter("company", company)}
                      {query_filters}
                    GROUP BY query_hash
                    HAVING runs >= {min_runs} OR total_exec_hours >= {min_total_exec_hours}
                    ORDER BY total_exec_hours DESC, runs DESC
                    LIMIT 10
                    """,
                    ttl_key=get_company_scope_key(
                        "shared_rec_repeated_queries_mart",
                        days,
                        min_runs,
                        min_total_exec_hours,
                    ),
                    tier="historical",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(
                        data=df,
                        source="Fast query-detail summary",
                        available=True,
                        effective_days=days,
                    )
                mart_message = "Repeated-query mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for repeated-query lookbacks beyond retained query detail."

        if not allow_live_fallback:
            return _empty_result("Fast query-detail summary", mart_message, effective_days=days)

        try:
            qh_columns = set(filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["QUERY_PARAMETERIZED_HASH", "QUERY_HASH"],
            ))
            hash_column = (
                "QUERY_PARAMETERIZED_HASH"
                if "QUERY_PARAMETERIZED_HASH" in qh_columns
                else "QUERY_HASH" if "QUERY_HASH" in qh_columns else ""
            )
            if not hash_column:
                return _empty_result(
                    "Repeated query advisor",
                    f"{mart_message} QUERY_HISTORY does not expose a query hash column.",
                    effective_days=days,
                )
            hash_ident = hash_column
            df = run_query(
                f"""
                SELECT {hash_ident} AS query_hash,
                       COUNT(*) AS runs,
                       COUNT(DISTINCT user_name) AS user_count,
                       ROUND(SUM(COALESCE(total_elapsed_time, 0)) / 1000 / 3600, 2) AS total_exec_hours,
                       ROUND(SUM(COALESCE(bytes_scanned, 0)) / POWER(1024, 4), 2) AS tb_scanned,
                       SUBSTR(MAX(query_text), 1, 500) AS sample_query,
                       '{hash_column}' AS hash_column
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND warehouse_name IS NOT NULL
                  AND UPPER(COALESCE(execution_status, '')) = 'SUCCESS'
                  AND {hash_ident} IS NOT NULL
                  {query_filters}
                GROUP BY {hash_ident}
                HAVING runs >= {min_runs} OR total_exec_hours >= {min_total_exec_hours}
                ORDER BY total_exec_hours DESC, runs DESC
                LIMIT 10
                """,
                ttl_key=get_company_scope_key(
                    "shared_rec_repeated_queries_live",
                    days,
                    min_runs,
                    min_total_exec_hours,
                    hash_column,
                ),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Repeated query advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse(
        "shared_rec_repeated_queries",
        (company, days, min_runs, min_total_exec_hours, allow_live_fallback),
        _loader,
        force=force,
    )


def load_shared_duplicate_query_patterns(
    session: object,
    company: str | None = None,
    *,
    days: int = 7,
    min_executions: int = 5,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load duplicate/redundant query candidates once for advisor panels."""

    company = company or get_active_company()
    days = max(1, int(days or 7))
    min_executions = max(1, int(min_executions or 1))

    def _loader() -> SharedMetricResult:
        query_filters = get_global_filter_clause(
            date_col="start_time",
            wh_col="warehouse_name",
            user_col="user_name",
            role_col="role_name",
            db_col="database_name",
        )
        mart_message = ""
        if days <= 30:
            try:
                table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
                df = run_query(
                    f"""
                    SELECT SUBSTR(query_text, 1, 200) AS query_sig,
                           COUNT(DISTINCT user_name) AS user_count,
                           COUNT(*) AS execution_count,
                           SUM(total_elapsed_time) / NULLIF(COUNT(*), 0) / 1000 AS avg_elapsed_sec,
                           SUM(total_elapsed_time) / 1000 AS total_wasted_sec,
                           0::FLOAT AS cloud_credits
                    FROM {table}
                    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                      AND UPPER(COALESCE(execution_status, '')) = 'SUCCESS'
                      AND warehouse_name IS NOT NULL
                      AND query_text IS NOT NULL
                      {_company_column_filter("company", company)}
                      {query_filters}
                    GROUP BY query_sig
                    HAVING execution_count >= {min_executions}
                    ORDER BY execution_count DESC, total_wasted_sec DESC
                    LIMIT 100
                    """,
                    ttl_key=get_company_scope_key("shared_duplicate_queries_mart", days, min_executions),
                    tier="standard",
                    section=section,
                )
                if not df.empty:
                    return SharedMetricResult(
                        data=df,
                        source="Fast query-detail summary",
                        available=True,
                        effective_days=days,
                    )
                mart_message = "Duplicate-query mart returned no rows."
            except Exception as exc:
                mart_message = str(exc)
        else:
            mart_message = "Live scan required for duplicate-query lookbacks beyond retained query detail."

        try:
            qh_cols = set(filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["CREDITS_USED_CLOUD_SERVICES"],
            ))
            cloud_expr = (
                "SUM(COALESCE(credits_used_cloud_services, 0))"
                if "CREDITS_USED_CLOUD_SERVICES" in qh_cols
                else "0"
            )
            df = run_query(
                f"""
                SELECT SUBSTR(query_text, 1, 200) AS query_sig,
                       COUNT(DISTINCT user_name) AS user_count,
                       COUNT(*) AS execution_count,
                       SUM(total_elapsed_time) / NULLIF(COUNT(*), 0) / 1000 AS avg_elapsed_sec,
                       SUM(total_elapsed_time) / 1000 AS total_wasted_sec,
                       {cloud_expr} AS cloud_credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND UPPER(execution_status) = 'SUCCESS'
                  AND warehouse_name IS NOT NULL
                  {query_filters}
                GROUP BY query_sig
                HAVING COUNT(*) >= {min_executions}
                ORDER BY execution_count DESC
                LIMIT 100
                """,
                ttl_key=get_company_scope_key("shared_duplicate_queries_live", days, min_executions),
                tier="standard",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Duplicate query advisor", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse("shared_duplicate_queries", (company, days, min_executions), _loader, force=force)


def load_shared_warehouse_right_sizing(
    session: object,
    company: str | None = None,
    *,
    days: int = 14,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load warehouse right-sizing telemetry once for advisor panels."""

    company = company or get_active_company()
    days = max(1, int(days or 14))

    def _loader() -> SharedMetricResult:
        try:
            qh_cols = set(filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                [
                    "WAREHOUSE_SIZE",
                    "QUEUED_OVERLOAD_TIME",
                    "BYTES_SPILLED_TO_REMOTE_STORAGE",
                    "PERCENTAGE_SCANNED_FROM_CACHE",
                ],
            ))
            wh_size_expr = "MAX(warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
            queue_expr = "AVG(queued_overload_time) / 1000" if "QUEUED_OVERLOAD_TIME" in qh_cols else "0"
            spill_expr = (
                "SUM(bytes_spilled_to_remote_storage) / POWER(1024, 3)"
                if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
                else "0"
            )
            cache_expr = "AVG(percentage_scanned_from_cache)" if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols else "0"
            query_filters = get_global_filter_clause(
                date_col="start_time",
                wh_col="warehouse_name",
                user_col="user_name",
                role_col="role_name",
                db_col="database_name",
            )
            df = run_query(
                f"""
                WITH query_stats AS (
                    SELECT
                        warehouse_name,
                        {wh_size_expr} AS warehouse_size,
                        COUNT(*) AS total_queries,
                        {queue_expr} AS avg_queue_sec,
                        {spill_expr} AS remote_spill_gb,
                        {cache_expr} AS avg_cache_pct
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                      AND warehouse_name IS NOT NULL
                      {query_filters}
                    GROUP BY warehouse_name
                ),
                metering AS (
                    SELECT
                        warehouse_name,
                        ROUND(SUM(credits_used), 4) AS total_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                      AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("warehouse_name", company)}
                    GROUP BY warehouse_name
                )
                SELECT
                    q.warehouse_name,
                    q.warehouse_size,
                    q.total_queries,
                    ROUND(q.avg_queue_sec, 2) AS avg_queue_sec,
                    ROUND(q.remote_spill_gb, 2) AS remote_spill_gb,
                    ROUND(q.avg_cache_pct, 2) AS avg_cache_pct,
                    COALESCE(m.total_credits, 0) AS total_credits
                FROM query_stats q
                LEFT JOIN metering m
                  ON q.warehouse_name = m.warehouse_name
                ORDER BY total_credits DESC
                """,
                ttl_key=get_company_scope_key("shared_warehouse_right_sizing", days),
                tier="historical",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY + WAREHOUSE_METERING_HISTORY",
                available=not df.empty,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Warehouse right-sizing advisor", f"Warehouse sizing telemetry unavailable: {exc}")

    return _load_or_reuse("shared_warehouse_right_sizing", (company, days), _loader, force=force)


def load_shared_procedure_inventory(
    company: str | None = None,
    *,
    database_contains: str = "",
    live_sql: str = "",
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load stored procedure inventory once, preferring the procedure snapshot mart."""

    company = company or get_active_company()
    database_contains = str(database_contains or "").strip()

    def _loader() -> SharedMetricResult:
        mart_message = ""
        try:
            df = run_query(
                build_mart_procedure_inventory_sql(company=company, database_contains=database_contains),
                ttl_key=get_company_scope_key("shared_procedure_inventory_mart", database_contains),
                tier="metadata",
                section=section,
            )
            if not df.empty:
                return SharedMetricResult(data=df, source="Fast procedure inventory", available=True)
            mart_message = "Procedure inventory mart returned no rows."
        except Exception as exc:
            mart_message = str(exc)

        live_sql_value = live_sql() if callable(live_sql) else live_sql
        if not live_sql_value:
            return _empty_result("Procedure inventory", mart_message)
        try:
            df = run_query(
                live_sql_value,
                ttl_key=get_company_scope_key("shared_procedure_inventory_live", database_contains),
                tier="metadata",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.PROCEDURES",
                available=not df.empty,
                message="" if not df.empty else mart_message,
            )
        except Exception as exc:
            return _empty_result("Procedure inventory", f"{mart_message} Live fallback unavailable: {exc}")

    return _load_or_reuse("shared_procedure_inventory", (company, database_contains), _loader, force=force)


def load_shared_procedure_calls(
    company: str | None = None,
    *,
    days: int = 7,
    live_sql: str = "",
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load stored procedure call summary once, preferring FACT_PROCEDURE_RUN."""

    company = company or get_active_company()
    days = max(1, int(days or 7))

    def _loader() -> SharedMetricResult:
        mart_message = ""
        try:
            df = run_query(
                build_mart_procedure_calls_sql(days, company=company),
                ttl_key=get_company_scope_key("shared_procedure_calls_mart", days),
                tier="standard",
                section=section,
            )
            if not df.empty:
                return SharedMetricResult(data=df, source="Fast procedure run summary", available=True, effective_days=days)
            mart_message = "Procedure call mart returned no rows."
        except Exception as exc:
            mart_message = str(exc)

        live_sql_value = live_sql() if callable(live_sql) else live_sql
        if not live_sql_value:
            return _empty_result("Procedure call summary", mart_message, effective_days=days)
        try:
            df = run_query(
                live_sql_value,
                ttl_key=get_company_scope_key("shared_procedure_calls_live", days),
                tier="standard",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Procedure call summary", f"{mart_message} Live fallback unavailable: {exc}", effective_days=days)

    return _load_or_reuse("shared_procedure_calls", (company, days), _loader, force=force)


def load_shared_procedure_sla(
    company: str | None = None,
    *,
    days: int = 7,
    live_sql: str = "",
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load procedure SLA/cost detail once, preferring FACT_PROCEDURE_RUN."""

    company = company or get_active_company()
    days = max(1, int(days or 7))

    def _loader() -> SharedMetricResult:
        mart_message = ""
        try:
            df = run_query(
                build_mart_procedure_sla_sql(days, company=company),
                ttl_key=get_company_scope_key("shared_procedure_sla_mart", days),
                tier="standard",
                section=section,
            )
            if not df.empty:
                return SharedMetricResult(data=df, source="Fast procedure SLA summary", available=True, effective_days=days)
            mart_message = "Procedure SLA mart returned no rows."
        except Exception as exc:
            mart_message = str(exc)

        live_sql_value = live_sql() if callable(live_sql) else live_sql
        if not live_sql_value:
            return _empty_result("Procedure SLA/cost watch", mart_message, effective_days=days)
        try:
            df = run_query(
                live_sql_value,
                ttl_key=get_company_scope_key("shared_procedure_sla_live", days),
                tier="standard",
                section=section,
            )
            return SharedMetricResult(
                data=df,
                source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                available=not df.empty,
                message="" if not df.empty else mart_message,
                effective_days=days,
            )
        except Exception as exc:
            return _empty_result("Procedure SLA/cost watch", f"{mart_message} Live fallback unavailable: {exc}", effective_days=days)

    return _load_or_reuse("shared_procedure_sla", (company, days), _loader, force=force)
