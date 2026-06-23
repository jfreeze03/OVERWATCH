"""Shared usage and billing metering loaders."""

from __future__ import annotations

from .company_filter import (
    get_active_company,
    get_company_scope_key,
    get_global_wh_filter_clause,
    get_wh_filter_clause,
)
from .compatibility import filter_existing_columns
from .mart import (
    build_mart_bill_summary_sql,
    build_mart_bill_warehouse_delta_sql,
    build_mart_usage_metering_sql,
)
from .query import run_query, sql_literal
from .shared_metrics_cache import _empty_result, _global_filter_values, _load_or_reuse
from .shared_metrics_contracts import SharedMetricResult


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
    warehouse_contains, _, _, _, global_start_date, global_end_date = _global_filter_values()

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
