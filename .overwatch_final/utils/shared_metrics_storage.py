"""Shared storage metric loaders."""

from __future__ import annotations

import pandas as pd

from .company_filter import (
    get_active_company,
    get_company_scope_key,
    get_db_filter_clause,
    get_global_db_filter_clause,
)
from .cost import get_storage_cost_per_tb
from .data import normalize_df
from .mart import (
    build_mart_storage_db_detail_sql,
    build_mart_storage_trend_sql,
    build_mart_usage_storage_sql,
)
from .query import run_query
from .shared_metrics_cache import _empty_result, _global_filter_values, _load_or_reuse
from .shared_metrics_contracts import LIVE_STORAGE_FALLBACK_MAX_DAYS, SharedMetricResult


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
        account_storage_cte = (
            f"""
            account_storage AS (
                SELECT
                    usage_date,
                    SUM(COALESCE(hybrid_table_storage_bytes, 0)) AS hybrid_table_storage_bytes,
                    SUM(COALESCE(archive_storage_cool_bytes, 0)) AS archive_storage_cool_bytes,
                    SUM(COALESCE(archive_storage_cold_bytes, 0)) AS archive_storage_cold_bytes
                FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
                WHERE usage_date >= DATEADD('day', -{fallback_days}, CURRENT_DATE())
                GROUP BY usage_date
            )
            """
            if company == "ALL"
            else """
            account_storage AS (
                SELECT
                    usage_date,
                    0 AS hybrid_table_storage_bytes,
                    0 AS archive_storage_cool_bytes,
                    0 AS archive_storage_cold_bytes
                FROM database_storage
            )
            """
        )
        standard_storage_rate = get_storage_cost_per_tb()
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
            {stage_storage_cte},
            {account_storage_cte}
            SELECT COALESCE(d.usage_date, s.usage_date, a.usage_date) AS usage_date,
                   COALESCE(d.storage_bytes,  0)/POWER(1024,3)        AS storage_gb,
                   COALESCE(d.failsafe_bytes, 0)/POWER(1024,3)        AS failsafe_gb,
                   COALESCE(s.stage_bytes,    0)/POWER(1024,3)        AS stage_gb,
                   COALESCE(a.hybrid_table_storage_bytes, 0)/POWER(1024,3) AS hybrid_storage_gb,
                   COALESCE(a.archive_storage_cool_bytes, 0)/POWER(1024,3) AS archive_cool_gb,
                   COALESCE(a.archive_storage_cold_bytes, 0)/POWER(1024,3) AS archive_cold_gb,
                   ROUND(
                       (COALESCE(d.storage_bytes,0)+COALESCE(d.failsafe_bytes,0)+COALESCE(s.stage_bytes,0))
                       / POWER(1024,4) * {standard_storage_rate},
                       2
                   ) AS standard_storage_cost_usd,
                   ROUND(COALESCE(a.hybrid_table_storage_bytes, 0) / POWER(1024,3) * 0.34, 2) AS hybrid_storage_cost_usd,
                   ROUND(COALESCE(a.archive_storage_cool_bytes, 0) / POWER(1024,4) * 4, 2) AS archive_cool_cost_usd,
                   ROUND(COALESCE(a.archive_storage_cold_bytes, 0) / POWER(1024,4) * 1, 2) AS archive_cold_cost_usd,
                   (
                       COALESCE(d.storage_bytes,0)
                       + COALESCE(d.failsafe_bytes,0)
                       + COALESCE(s.stage_bytes,0)
                       + COALESCE(a.hybrid_table_storage_bytes,0)
                       + COALESCE(a.archive_storage_cool_bytes,0)
                       + COALESCE(a.archive_storage_cold_bytes,0)
                   ) / POWER(1024,4) AS total_storage_tb
            FROM database_storage d
            FULL OUTER JOIN stage_storage s ON d.usage_date = s.usage_date
            FULL OUTER JOIN account_storage a ON COALESCE(d.usage_date, s.usage_date) = a.usage_date
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
        _, _, _, database_contains, _, _ = _global_filter_values()
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
