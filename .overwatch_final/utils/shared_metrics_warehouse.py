"""Shared warehouse health and cost metric loaders."""

from __future__ import annotations

from .company_filter import (
    get_active_company,
    get_company_scope_key,
    get_global_filter_clause,
    get_global_wh_filter_clause,
    get_wh_filter_clause,
)
from .compatibility import filter_existing_columns
from .cost import build_metered_credit_cte
from .mart import (
    build_mart_warehouse_heatmap_sql,
    build_mart_warehouse_overview_sql,
    build_mart_warehouse_scaling_sql,
    mart_object_name,
)
from .query import run_query
from .shared_metrics_cache import _company_column_filter, _empty_result, _global_filter_values, _load_or_reuse
from .shared_metrics_contracts import SharedMetricResult

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
    warehouse_contains, _, _, _, global_start_date, global_end_date = _global_filter_values()

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
                    {days} AS lookback_days,
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

