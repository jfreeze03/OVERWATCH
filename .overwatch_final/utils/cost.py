# utils/cost.py - Credit/dollar formatting + metered credit CTE builder
import pandas as pd
import streamlit as st
from config import CREDIT_RATES, CREDIT_SOURCE_LABELS, COMPUTE_CREDIT_CASE, DEFAULTS

# Re-export for convenience
__all__ = [
    "get_credit_price", "get_ai_credit_price", "get_storage_cost_per_tb",
    "format_credits", "credits_to_dollars",
    "_estimate_live_credits_fallback", "estimate_live_credits",
    "query_attribution_supported",
    "build_metered_credit_cte", "build_idle_warehouse_sql",
    "build_monitoring_cost_sql", "build_app_runtime_cost_sql",
    "build_cost_reconciliation_sql", "build_snowflake_service_cost_lens_sql",
    "build_cost_efficiency_summary_sql", "build_warehouse_efficiency_sql",
    "build_clustering_cost_sql",
    "metric_confidence_label", "freshness_note",
    "CREDIT_RATES", "CREDIT_SOURCE_LABELS", "COMPUTE_CREDIT_CASE",
]


def get_credit_price() -> float:
    """Return the active credit price, defaulting to the mart contract setting."""
    return float(st.session_state.get("credit_price", DEFAULTS["credit_price"]))


def get_ai_credit_price() -> float:
    """Return the active Cortex AI credit price."""
    return float(st.session_state.get("ai_credit_price", DEFAULTS["ai_credit_price"]))


def get_storage_cost_per_tb() -> float:
    """Return the active storage cost estimate for display-only dollarization."""
    return float(st.session_state.get("storage_cost_per_tb", DEFAULTS["storage_cost_per_tb"]))


def format_credits(credits: float, credit_price: float = None) -> str:
    """Format credits as 'X.XX (${dollar})' consistently across all sections."""
    if credits is None or (isinstance(credits, float) and pd.isna(credits)):
        return "0 ($0.00)"
    credits = float(credits)
    if credit_price is None:
        credit_price = get_credit_price()
    dollars = credits * credit_price

    if credits < 0.01:
        cr_str = f"{credits:.4f}"
    elif credits < 1:
        cr_str = f"{credits:.3f}"
    elif credits < 100:
        cr_str = f"{credits:.2f}"
    else:
        cr_str = f"{credits:,.0f}"

    if dollars < 1:
        d_str = f"${dollars:.2f}"
    elif dollars < 1_000:
        d_str = f"${dollars:,.2f}"
    else:
        d_str = f"${dollars:,.0f}"

    return f"{cr_str} ({d_str})"


def credits_to_dollars(credits: float, credit_price: float = None) -> float:
    """Convert credits to dollars using configured credit price."""
    if credit_price is None:
        credit_price = get_credit_price()
    return round((credits or 0) * credit_price, 2)


def build_snowflake_service_cost_lens_sql(
    days_back: int = 7,
    credit_price: float = None,
    ai_credit_price: float = None,
) -> str:
    """Return account service cost by official Snowflake service type.

    This follows the COST_MONITOR_DB source-of-truth formula: completed account
    service usage from METERING_HISTORY, ending 24 hours before now, with current
    and prior windows split from the same bounded scan.
    """
    days_back = max(1, int(days_back or 7))
    if credit_price is None:
        credit_price = DEFAULTS["credit_price"]
    credit_price = float(credit_price or DEFAULTS["credit_price"])
    if ai_credit_price is None:
        ai_credit_price = DEFAULTS["ai_credit_price"]
    ai_credit_price = float(ai_credit_price or DEFAULTS["ai_credit_price"])
    return f"""
    WITH period_data AS (
        SELECT
            DATE(start_time) AS usage_date,
            UPPER(COALESCE(service_type, 'UNKNOWN')) AS service_type,
            SUM(COALESCE(credits_used_compute, 0)) AS compute_credits,
            SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits,
            SUM(COALESCE(credits_used, 0)) AS total_credits,
            CASE
                WHEN DATE(start_time) > DATEADD('day', -{days_back}, DATEADD('hour', -24, CURRENT_TIMESTAMP()))
                    THEN 'CURRENT'
                ELSE 'PRIOR'
            END AS period,
            COUNT(*) AS metering_rows
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back * 2}, DATEADD('hour', -24, CURRENT_TIMESTAMP()))
          AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
        GROUP BY DATE(start_time), UPPER(COALESCE(service_type, 'UNKNOWN'))
    ),
    categorized AS (
        SELECT
            usage_date,
            service_type,
            period,
            CASE
                WHEN service_type ILIKE '%CORTEX%' OR service_type ILIKE '%AI%' OR service_type ILIKE '%INTELLIGENCE%'
                    THEN 'AI / Cortex'
                WHEN service_type IN (
                    'AUTOMATIC_CLUSTERING', 'COPY_FILES', 'MATERIALIZED_VIEW',
                    'QUERY_ACCELERATION', 'SEARCH_OPTIMIZATION', 'SERVERLESS_ALERTS',
                    'SERVERLESS_TASK', 'SNOWPIPE', 'SNOWPIPE_STREAMING',
                    'SNOWPARK_CONTAINER_SERVICES', 'REPLICATION'
                )
                    THEN 'Serverless / Managed Compute'
                WHEN service_type ILIKE '%STORAGE%' THEN 'Storage'
                WHEN service_type ILIKE '%DATA_TRANSFER%' OR service_type ILIKE '%PRIVATELINK%'
                    THEN 'Data Transfer / Network'
                WHEN service_type = 'WAREHOUSE_METERING' THEN 'Warehouse'
                ELSE 'Other'
            END AS service_category,
            CASE
                WHEN service_type ILIKE '%CORTEX%' OR service_type ILIKE '%AI%' OR service_type ILIKE '%INTELLIGENCE%'
                    THEN {ai_credit_price:.4f}
                ELSE {credit_price:.4f}
            END AS rate_usd,
            compute_credits,
            cloud_services_credits,
            total_credits,
            metering_rows
        FROM period_data
    )
    SELECT
        service_category,
        service_type,
        MAX(rate_usd) AS rate_usd,
        ROUND(SUM(IFF(period = 'CURRENT', total_credits, 0)), 4) AS credits_billed,
        ROUND(SUM(IFF(period = 'PRIOR', total_credits, 0)), 4) AS credits_billed_prior,
        ROUND(
            SUM(IFF(period = 'CURRENT', total_credits, 0))
            - SUM(IFF(period = 'PRIOR', total_credits, 0)),
            4
        ) AS credit_delta,
        CASE
            WHEN SUM(IFF(period = 'PRIOR', total_credits, 0)) = 0 THEN NULL
            ELSE ROUND(
                (
                    SUM(IFF(period = 'CURRENT', total_credits, 0))
                    - SUM(IFF(period = 'PRIOR', total_credits, 0))
                ) / NULLIF(SUM(IFF(period = 'PRIOR', total_credits, 0)), 0) * 100,
                2
            )
        END AS pct_delta,
        ROUND(SUM(IFF(period = 'CURRENT', compute_credits, 0)), 4) AS credits_used_compute,
        ROUND(SUM(IFF(period = 'CURRENT', cloud_services_credits, 0)), 4) AS credits_used_cloud_services,
        0::NUMBER(18,4) AS credits_adjustment_cloud_services,
        ROUND(SUM(IFF(period = 'CURRENT', total_credits * rate_usd, 0)), 2) AS estimated_cost_usd,
        ROUND(SUM(IFF(period = 'PRIOR', total_credits * rate_usd, 0)), 2) AS prior_estimated_cost_usd,
        ROUND(
            SUM(IFF(period = 'CURRENT', total_credits * rate_usd, 0))
            - SUM(IFF(period = 'PRIOR', total_credits * rate_usd, 0)),
            2
        ) AS cost_delta_usd,
        COUNT(DISTINCT IFF(period = 'CURRENT', usage_date, NULL)) AS observed_days,
        SUM(IFF(period = 'CURRENT', metering_rows, 0)) AS metering_rows,
        'SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY' AS snowflake_source
    FROM categorized
    GROUP BY service_category, service_type
        HAVING ABS(SUM(total_credits)) > 0
        OR ABS(SUM(compute_credits)) > 0
        OR ABS(SUM(cloud_services_credits)) > 0
    ORDER BY ABS(credit_delta) DESC, credits_billed DESC, service_category, service_type
    """


def _estimate_live_credits_fallback(row) -> float:
    """Last-resort live estimator used only before official metering arrives.

    Uses warehouse size credit rate times elapsed seconds / 3600.
    """
    size = row.get("WAREHOUSE_SIZE", "") or ""
    exec_sec = float(
        row.get("EXEC_SEC", 0) or row.get("ELAPSED_SEC", 0) or 0
    )
    rate = CREDIT_RATES.get(size, 1)
    return round(rate * (exec_sec / 3600), 6)


# Backward-compatible alias for older sections. New work should use official
# metering first and call _estimate_live_credits_fallback only as a labeled gap.
estimate_live_credits = _estimate_live_credits_fallback


def query_attribution_supported(session) -> bool:
    """Return whether Snowflake's official query attribution view is usable."""
    try:
        from .compatibility import filter_existing_columns

        columns = set(filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY",
            [
                "QUERY_ID",
                "START_TIME",
                "CREDITS_ATTRIBUTED_COMPUTE",
                "CREDITS_USED_QUERY_ACCELERATION",
            ],
        ))
        return {
            "QUERY_ID",
            "START_TIME",
            "CREDITS_ATTRIBUTED_COMPUTE",
            "CREDITS_USED_QUERY_ACCELERATION",
        }.issubset(columns)
    except Exception:
        return False


def build_metered_credit_cte(
    days_back: int = None,
    hours_back: int = None,
    include_recent: bool = False,
    prefer_query_attribution: bool = False,
) -> str:
    """Build CTE that estimates per-query credits from the best available source.

    Args:
        days_back:       Time window in days (used if hours_back not set).
        hours_back:      Time window in hours (takes priority over days_back).
        include_recent:  If True, extends upper bound to CURRENT_TIMESTAMP()
                         (use for live/recent views). If False, upper bound is
                         DATEADD('hour', -24, ...) to avoid partial billing windows.
        prefer_query_attribution:
                         If True, prefer QUERY_ATTRIBUTION_HISTORY compute
                         credits and fall back to OVERWATCH allocation for gaps.

    Returns:
        SQL CTE fragment (metered_hourly, query_exec_share, per_query_credits).
        Query-attribution credits are Snowflake official execution-only compute.
        Fallback allocation uses warehouse-hour metering by execution-time share.
        Caller wraps this in WITH ... SELECT ...
    """
    if hours_back:
        time_filter = f"DATEADD('hours', -{hours_back}, CURRENT_TIMESTAMP())"
    else:
        time_filter = f"DATEADD('day', -{days_back or 7}, CURRENT_TIMESTAMP())"

    upper_bound = (
        "CURRENT_TIMESTAMP()"
        if include_recent
        else "DATEADD('hour', -24, CURRENT_TIMESTAMP())"
    )
    try:
        from .company_filter import get_wh_filter_clause

        metered_scope = get_wh_filter_clause("warehouse_name")
        query_scope = get_wh_filter_clause("q.warehouse_name")
    except Exception:
        metered_scope = ""
        query_scope = ""

    official_attribution_cte = ""
    official_join = ""
    official_credit_expr = "NULL::FLOAT"
    credit_source_expr = "'OVERWATCH_ALLOCATED'"
    if prefer_query_attribution:
        official_attribution_cte = f""",
    official_query_attribution AS (
        SELECT
            query_id,
            ROUND(
                SUM(
                    COALESCE(credits_attributed_compute, 0)
                    + COALESCE(credits_used_query_acceleration, 0)
                ),
                6
            ) AS official_attributed_compute_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
        WHERE start_time >= {time_filter}
          AND start_time <  {upper_bound}
        GROUP BY query_id
    )"""
        official_join = """
        LEFT JOIN official_query_attribution oqa
          ON qs.query_id = oqa.query_id"""
        official_credit_expr = "oqa.official_attributed_compute_credits"
        credit_source_expr = (
            "IFF(oqa.official_attributed_compute_credits IS NOT NULL, "
            "'QUERY_ATTRIBUTION_HISTORY', 'OVERWATCH_ALLOCATED')"
        )

    return f"""
    metered_hourly AS (
        SELECT
            warehouse_name,
            DATE_TRUNC('hour', start_time)  AS hour_bucket,
            SUM(COALESCE(credits_used_compute, credits_used))
                                           AS hourly_compute_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= {time_filter}
          AND start_time <  {upper_bound}
          {metered_scope}
        GROUP BY warehouse_name, hour_bucket
    ),
    query_exec_share AS (
        SELECT
            q.query_id,
            q.warehouse_name,
            DATE_TRUNC('hour', q.start_time)  AS hour_bucket,
            q.execution_time                   AS exec_ms,
            SUM(q.execution_time) OVER (
                PARTITION BY q.warehouse_name, DATE_TRUNC('hour', q.start_time)
            )                                  AS hour_total_exec_ms
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= {time_filter}
          AND q.start_time <  {upper_bound}
          AND q.warehouse_name IS NOT NULL
          AND q.execution_time > 0
          {query_scope}
    ){official_attribution_cte},
    per_query_credits AS (
        SELECT
            qs.query_id,
            qs.warehouse_name,
            qs.hour_bucket,
            ROUND(
                COALESCE(m.hourly_compute_credits, 0)
                * qs.exec_ms / NULLIF(qs.hour_total_exec_ms, 0),
                6
            ) AS allocated_metered_credits,
            {official_credit_expr} AS official_attributed_compute_credits,
            {credit_source_expr} AS credit_source,
            ROUND(
                COALESCE(
                    {official_credit_expr},
                    COALESCE(m.hourly_compute_credits, 0)
                    * qs.exec_ms / NULLIF(qs.hour_total_exec_ms, 0)
                ),
                6
            ) AS metered_credits
        FROM query_exec_share qs
        LEFT JOIN metered_hourly m
          ON  qs.warehouse_name = m.warehouse_name
          AND qs.hour_bucket    = m.hour_bucket
        {official_join}
    )
    """


def build_idle_warehouse_sql(
    days_back: int = 7,
    wh_filter: str = "",
    min_idle_credits: float = 1.0,
) -> str:
    """Return the standard idle warehouse detector SQL.

    Uses WAREHOUSE_METERING_HISTORY as the exact credit source and only counts
    completed billing hours to avoid partial-hour noise.
    """
    return f"""
    WITH metering AS (
        SELECT
            warehouse_name,
            DATE_TRUNC('hour', start_time) AS hour_bucket,
            SUM(COALESCE(credits_used_compute, credits_used)) AS hourly_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
          {wh_filter}
        GROUP BY warehouse_name, hour_bucket
    ),
    query_activity AS (
        SELECT
            warehouse_name,
            DATE_TRUNC('hour', start_time) AS hour_bucket,
            COUNT(*) AS query_count,
            NULL::VARCHAR AS warehouse_size
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {wh_filter}
        GROUP BY warehouse_name, hour_bucket
    )
    SELECT
        m.warehouse_name,
        MAX(query_activity.warehouse_size) AS warehouse_size,
        ROUND(SUM(m.hourly_credits), 4) AS idle_credits,
        COUNT(*) AS idle_hours
    FROM metering m
    LEFT JOIN query_activity
      ON m.warehouse_name = query_activity.warehouse_name
     AND m.hour_bucket = query_activity.hour_bucket
    WHERE COALESCE(query_activity.query_count, 0) = 0
    GROUP BY m.warehouse_name
    HAVING idle_credits > {float(min_idle_credits)}
    ORDER BY idle_credits DESC
    """


def build_monitoring_cost_sql(days_back: int = 7) -> str:
    """Return SQL for the OVERWATCH cost-of-monitoring panel."""
    try:
        from .company_filter import get_wh_filter_clause

        wh_filter = get_wh_filter_clause("warehouse_name")
        q_wh_filter = get_wh_filter_clause("q.warehouse_name")
    except Exception:
        wh_filter = ""
        q_wh_filter = ""

    return f"""
    WITH {build_metered_credit_cte(days_back=days_back, include_recent=True)},
    overwatch_queries AS (
        SELECT
            'OVERWATCH tagged queries' AS component,
            COUNT(*) AS events,
            ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS credits,
            'Allocated' AS confidence,
            'QUERY_HISTORY query_tag = OVERWATCH, allocated from warehouse metering' AS source
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
        WHERE q.start_time >= DATEADD('day', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND (q.query_tag ILIKE 'OVERWATCH:%' OR q.query_tag ILIKE 'OVERWATCH%')
          {q_wh_filter}
    ),
    streamlit_warehouse AS (
        SELECT
            'Streamlit warehouse' AS component,
            COUNT(*) AS events,
            ROUND(SUM(credits_used), 4) AS credits,
            'Exact' AS confidence,
            'WAREHOUSE_METERING_HISTORY for OVERWATCH_WH and Streamlit-style warehouses' AS source
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND (
              warehouse_name = 'OVERWATCH_WH'
              OR warehouse_name ILIKE 'SYSTEM$STREAMLIT%'
              OR warehouse_name ILIKE '%STREAMLIT%'
          )
          {wh_filter}
    ),
    cortex_cost AS (
        SELECT
            'Cortex services' AS component,
            COUNT(*) AS events,
            ROUND(SUM(credits_used), 4) AS credits,
            'Account-wide' AS confidence,
            'METERING_HISTORY service_type contains Cortex; not warehouse/company attributable' AS source
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND service_type ILIKE '%CORTEX%'
    ),
    alert_tasks AS (
        SELECT
            'OVERWATCH alert tasks' AS component,
            COUNT(*) AS events,
            ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS credits,
            'Allocated' AS confidence,
            'QUERY_HISTORY task/alert SQL matched to warehouse metering' AS source
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
        WHERE q.start_time >= DATEADD('day', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND (
              q.query_tag ILIKE '%OVERWATCH_ALERT%'
              OR q.query_text ILIKE '%OVERWATCH_ALERT%'
              OR q.query_text ILIKE '%OVERWATCH_ACTION_QUEUE%'
          )
          {q_wh_filter}
    )
    SELECT * FROM overwatch_queries
    UNION ALL SELECT * FROM streamlit_warehouse
    UNION ALL SELECT * FROM cortex_cost
    UNION ALL SELECT * FROM alert_tasks
    ORDER BY credits DESC
    """


def build_app_runtime_cost_sql(days_back: int = 30) -> str:
    """Return a measured OVERWATCH runtime cost aggregate.

    This intentionally uses Snowflake metering data only: tagged OVERWATCH
    queries are allocated from warehouse-hour metering, Streamlit warehouses are
    counted directly, and Cortex/alert-task usage is included where available.
    No fixed 24x7 warehouse assumption is used.
    """
    days_back = int(days_back or 30)
    try:
        from .company_filter import get_wh_filter_clause

        wh_filter = get_wh_filter_clause("warehouse_name")
        q_wh_filter = get_wh_filter_clause("q.warehouse_name")
    except Exception:
        wh_filter = ""
        q_wh_filter = ""

    return f"""
    WITH {build_metered_credit_cte(days_back=days_back, include_recent=True)},
    components AS (
        SELECT
            'OVERWATCH tagged queries' AS component,
            ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
        WHERE q.start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND (q.query_tag ILIKE 'OVERWATCH:%' OR q.query_tag ILIKE 'OVERWATCH%')
          {q_wh_filter}

        UNION ALL
        SELECT
            'Streamlit warehouse' AS component,
            ROUND(SUM(credits_used), 4) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND (
              warehouse_name = 'OVERWATCH_WH'
              OR warehouse_name ILIKE 'SYSTEM$STREAMLIT%'
              OR warehouse_name ILIKE '%STREAMLIT%'
          )
          {wh_filter}

        UNION ALL
        SELECT
            'Cortex services' AS component,
            ROUND(SUM(credits_used), 4) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND service_type ILIKE '%CORTEX%'

        UNION ALL
        SELECT
            'OVERWATCH alert tasks' AS component,
            ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
        WHERE q.start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND (
              q.query_tag ILIKE '%OVERWATCH_ALERT%'
              OR q.query_text ILIKE '%OVERWATCH_ALERT%'
              OR q.query_text ILIKE '%OVERWATCH_ACTION_QUEUE%'
          )
          {q_wh_filter}
    )
    SELECT
        ROUND(COALESCE(SUM(credits), 0), 4) AS app_credits_30d,
        LISTAGG(IFF(COALESCE(credits, 0) > 0, component, NULL), ', ')
            WITHIN GROUP (ORDER BY credits DESC) AS app_warehouse,
        COUNT_IF(COALESCE(credits, 0) > 0) AS measured_components
    FROM components
    """


def build_cost_reconciliation_sql(days_back: int = 30, prefer_query_attribution: bool = False) -> str:
    """Compare exact warehouse credits to allocated query credits by warehouse/day.

    WAREHOUSE_METERING_HISTORY is the source of truth. Query-level costs are
    official execution-only compute when QUERY_ATTRIBUTION_HISTORY is available,
    otherwise allocated by execution-time share. Query-level totals will not
    fully reconcile when warehouses are idle, when cloud services are involved,
    or when ACCOUNT_USAGE has latency.
    """
    days_back = max(1, int(days_back or 30))
    try:
        from .company_filter import get_wh_filter_clause

        metered_scope = get_wh_filter_clause("warehouse_name")
        query_scope = get_wh_filter_clause("q.warehouse_name")
    except Exception:
        metered_scope = ""
        query_scope = ""

    return f"""
    WITH metered_daily AS (
        SELECT
            DATE_TRUNC('day', start_time) AS usage_day,
            warehouse_name,
            ROUND(SUM(credits_used), 6) AS exact_metered_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
          {metered_scope}
        GROUP BY usage_day, warehouse_name
    ),
    {build_metered_credit_cte(
        days_back=days_back,
        include_recent=False,
        prefer_query_attribution=prefer_query_attribution,
    )},
    allocated_daily AS (
        SELECT
            DATE_TRUNC('day', q.start_time) AS usage_day,
            q.warehouse_name,
            COUNT(*) AS query_count,
            ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 6) AS allocated_query_credits,
            ROUND(SUM(COALESCE(pqc.allocated_metered_credits, 0)), 6) AS overwatch_allocated_credits,
            ROUND(SUM(COALESCE(pqc.official_attributed_compute_credits, 0)), 6) AS official_attributed_compute_credits,
            COUNT_IF(pqc.credit_source = 'QUERY_ATTRIBUTION_HISTORY') AS official_attributed_queries,
            CASE
                WHEN COUNT_IF(pqc.credit_source = 'QUERY_ATTRIBUTION_HISTORY') > 0
                    THEN 'QUERY_ATTRIBUTION_HISTORY preferred; OVERWATCH fallback for gaps'
                ELSE 'OVERWATCH allocated fallback'
            END AS attribution_source
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        LEFT JOIN per_query_credits pqc
          ON q.query_id = pqc.query_id
        WHERE q.start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND q.start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {query_scope}
        GROUP BY usage_day, q.warehouse_name
    )
    SELECT
        COALESCE(m.usage_day, a.usage_day) AS usage_day,
        COALESCE(m.warehouse_name, a.warehouse_name) AS warehouse_name,
        COALESCE(a.query_count, 0) AS query_count,
        COALESCE(m.exact_metered_credits, 0) AS exact_metered_credits,
        COALESCE(a.allocated_query_credits, 0) AS allocated_query_credits,
        COALESCE(a.overwatch_allocated_credits, 0) AS overwatch_allocated_credits,
        COALESCE(a.official_attributed_compute_credits, 0) AS official_attributed_compute_credits,
        COALESCE(a.official_attributed_queries, 0) AS official_attributed_queries,
        COALESCE(a.attribution_source, 'No query attribution') AS attribution_source,
        ROUND(COALESCE(m.exact_metered_credits, 0) - COALESCE(a.allocated_query_credits, 0), 6) AS variance_credits,
        ROUND(
            100 * ABS(COALESCE(m.exact_metered_credits, 0) - COALESCE(a.allocated_query_credits, 0))
            / NULLIF(COALESCE(m.exact_metered_credits, 0), 0),
            2
        ) AS variance_pct,
        CASE
            WHEN COALESCE(m.exact_metered_credits, 0) = 0 THEN 'No metering'
            WHEN ABS(COALESCE(m.exact_metered_credits, 0) - COALESCE(a.allocated_query_credits, 0))
                 <= GREATEST(0.05, COALESCE(m.exact_metered_credits, 0) * 0.05) THEN 'Reconciled'
            WHEN COALESCE(a.query_count, 0) = 0 THEN 'Idle or non-query warehouse usage'
            ELSE 'Variance review'
        END AS reconciliation_status
    FROM metered_daily m
    FULL OUTER JOIN allocated_daily a
      ON m.usage_day = a.usage_day
     AND m.warehouse_name = a.warehouse_name
    ORDER BY
        ABS(COALESCE(m.exact_metered_credits, 0) - COALESCE(a.allocated_query_credits, 0)) DESC,
        usage_day DESC,
        warehouse_name
    """


def build_cost_efficiency_summary_sql(
    days_back: int = 7,
    company: str = None,
    credit_price: float = None,
    *,
    prefer_query_attribution: bool = True,
) -> str:
    """Return single-row cost efficiency telemetry for Cost & Contract."""
    days_back = max(1, int(days_back or 7))
    rate = float(credit_price if credit_price is not None else DEFAULTS["credit_price"])
    try:
        from .company_filter import get_global_filter_clause, get_wh_filter_clause

        metered_scope = get_wh_filter_clause("warehouse_name", company)
        query_scope = get_global_filter_clause(
            date_col="",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            db_col="q.database_name",
        )
    except Exception:
        metered_scope = ""
        query_scope = ""

    failed_expr = "UPPER(COALESCE(q.execution_status, '')) IN ('FAIL', 'FAILED_WITH_ERROR')"
    return f"""
    WITH {build_metered_credit_cte(
        days_back=days_back,
        include_recent=False,
        prefer_query_attribution=prefer_query_attribution,
    )},
    metered AS (
        SELECT
            ROUND(SUM(COALESCE(credits_used, 0)), 6) AS exact_metered_credits,
            ROUND(SUM(COALESCE(credits_used_compute, credits_used)), 6) AS exact_compute_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {metered_scope}
    ),
    query_efficiency AS (
        SELECT
            COUNT(*) AS query_count,
            ROUND(SUM(COALESCE(q.bytes_scanned, 0)) / POWER(1024, 4), 4) AS tb_scanned,
            ROUND(AVG(COALESCE(q.percentage_scanned_from_cache, 0)), 2) AS avg_cache_pct,
            COUNT_IF({failed_expr}) AS failed_queries,
            ROUND(SUM(IFF({failed_expr}, COALESCE(q.total_elapsed_time, 0), 0)) / 1000 / 3600, 4) AS failed_runtime_hours,
            ROUND(SUM(IFF({failed_expr}, COALESCE(pqc.metered_credits, 0), 0)), 6) AS failed_query_credits,
            ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 6) AS attributed_query_credits,
            COUNT_IF(pqc.credit_source = 'QUERY_ATTRIBUTION_HISTORY') AS official_attributed_queries
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        LEFT JOIN per_query_credits pqc
          ON q.query_id = pqc.query_id
        WHERE q.start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND q.start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {query_scope}
    )
    SELECT
        ROUND(COALESCE(m.exact_metered_credits, 0) * {rate:.4f}, 2) AS total_cost_usd,
        q.query_count,
        ROUND(COALESCE(m.exact_metered_credits, 0) * {rate:.4f} / NULLIF(q.query_count, 0), 4) AS cost_per_query_usd,
        q.tb_scanned,
        ROUND(COALESCE(m.exact_metered_credits, 0) * {rate:.4f} / NULLIF(q.tb_scanned, 0), 2) AS cost_per_tb_usd,
        q.avg_cache_pct,
        q.failed_queries,
        ROUND(q.failed_query_credits * {rate:.4f}, 2) AS failed_query_waste_usd,
        q.failed_runtime_hours,
        q.attributed_query_credits,
        q.official_attributed_queries,
        CASE
            WHEN q.official_attributed_queries > 0 THEN 'QUERY_ATTRIBUTION_HISTORY preferred; OVERWATCH fallback for gaps'
            ELSE 'OVERWATCH allocated fallback'
        END AS attribution_source
    FROM metered m, query_efficiency q
    """


def build_warehouse_efficiency_sql(
    days_back: int = 7,
    company: str = None,
    credit_price: float = None,
    *,
    top: int = 50,
    prefer_query_attribution: bool = True,
) -> str:
    """Return per-warehouse unit economics and pressure metrics."""
    days_back = max(1, int(days_back or 7))
    top = max(1, int(top or 50))
    rate = float(credit_price if credit_price is not None else DEFAULTS["credit_price"])
    try:
        from .company_filter import get_global_filter_clause, get_wh_filter_clause

        metered_scope = get_wh_filter_clause("warehouse_name", company)
        query_scope = get_global_filter_clause(
            date_col="",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            db_col="q.database_name",
        )
    except Exception:
        metered_scope = ""
        query_scope = ""

    failed_expr = "UPPER(COALESCE(q.execution_status, '')) IN ('FAIL', 'FAILED_WITH_ERROR')"
    return f"""
    WITH {build_metered_credit_cte(
        days_back=days_back,
        include_recent=False,
        prefer_query_attribution=prefer_query_attribution,
    )},
    metered AS (
        SELECT
            warehouse_name,
            ROUND(SUM(COALESCE(credits_used, 0)), 6) AS exact_metered_credits,
            ROUND(SUM(COALESCE(credits_used_compute, credits_used)), 6) AS exact_compute_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {metered_scope}
        GROUP BY warehouse_name
    ),
    query_stats AS (
        SELECT
            q.warehouse_name,
            COUNT(*) AS query_count,
            ROUND(SUM(COALESCE(q.total_elapsed_time, 0)) / 1000 / 3600, 4) AS exec_hours,
            ROUND(SUM(COALESCE(q.bytes_scanned, 0)) / POWER(1024, 4), 4) AS tb_scanned,
            ROUND(AVG(COALESCE(q.percentage_scanned_from_cache, 0)), 2) AS avg_cache_pct,
            ROUND(SUM(COALESCE(q.queued_overload_time, 0) + COALESCE(q.queued_provisioning_time, 0)) / 1000, 2) AS queue_seconds,
            ROUND(SUM(COALESCE(q.bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2) AS remote_spill_gb,
            COUNT_IF({failed_expr}) AS failed_queries,
            ROUND(SUM(IFF({failed_expr}, COALESCE(pqc.metered_credits, 0), 0)), 6) AS failed_query_credits,
            ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 6) AS attributed_query_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        LEFT JOIN per_query_credits pqc
          ON q.query_id = pqc.query_id
        WHERE q.start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
          AND q.start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {query_scope}
        GROUP BY q.warehouse_name
    )
    SELECT
        COALESCE(m.warehouse_name, q.warehouse_name) AS warehouse_name,
        ROUND(COALESCE(m.exact_metered_credits, 0) * {rate:.4f}, 2) AS cost_usd,
        COALESCE(q.query_count, 0) AS query_count,
        ROUND(COALESCE(m.exact_metered_credits, 0) * {rate:.4f} / NULLIF(q.query_count, 0), 4) AS cost_per_query_usd,
        COALESCE(q.tb_scanned, 0) AS tb_scanned,
        ROUND(COALESCE(m.exact_metered_credits, 0) * {rate:.4f} / NULLIF(q.tb_scanned, 0), 2) AS cost_per_tb_usd,
        COALESCE(q.exec_hours, 0) AS exec_hours,
        ROUND(COALESCE(m.exact_compute_credits, 0) / NULLIF(q.exec_hours, 0), 4) AS credits_per_exec_hour,
        COALESCE(q.avg_cache_pct, 0) AS avg_cache_pct,
        COALESCE(q.queue_seconds, 0) AS queue_seconds,
        COALESCE(q.remote_spill_gb, 0) AS remote_spill_gb,
        COALESCE(q.failed_queries, 0) AS failed_queries,
        ROUND(COALESCE(q.failed_query_credits, 0) * {rate:.4f}, 2) AS failed_query_waste_usd,
        COALESCE(q.attributed_query_credits, 0) AS attributed_query_credits
    FROM metered m
    FULL OUTER JOIN query_stats q
      ON m.warehouse_name = q.warehouse_name
    ORDER BY cost_usd DESC, failed_query_waste_usd DESC, remote_spill_gb DESC
    LIMIT {top}
    """


def build_clustering_cost_sql(
    days_back: int = 7,
    company: str = None,
    credit_price: float = None,
    *,
    top: int = 50,
) -> str:
    """Return automatic clustering cost and recluster churn by table."""
    days_back = max(1, int(days_back or 7))
    top = max(1, int(top or 50))
    rate = float(credit_price if credit_price is not None else DEFAULTS["credit_price"])
    try:
        from .company_filter import get_db_filter_clause

        db_scope = get_db_filter_clause("database_name", company)
    except Exception:
        db_scope = ""

    return f"""
    SELECT
        database_name || '.' || schema_name || '.' || table_name AS table_name,
        ROUND(SUM(COALESCE(credits_used, 0)), 4) AS clustering_credits,
        ROUND(SUM(COALESCE(credits_used, 0)) * {rate:.4f}, 2) AS clustering_cost_usd,
        ROUND(SUM(COALESCE(num_bytes_reclustered, 0)) / POWER(1024, 4), 4) AS tb_reclustered,
        SUM(COALESCE(num_rows_reclustered, 0)) AS rows_reclustered,
        ROUND(
            SUM(COALESCE(credits_used, 0)) * {rate:.4f}
            / NULLIF(SUM(COALESCE(num_bytes_reclustered, 0)) / POWER(1024, 4), 0),
            2
        ) AS cost_per_tb_reclustered
    FROM SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY
    WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
      AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND database_name IS NOT NULL
      {db_scope}
    GROUP BY database_name, schema_name, table_name
    HAVING SUM(COALESCE(credits_used, 0)) > 0
    ORDER BY clustering_cost_usd DESC, cost_per_tb_reclustered DESC
    LIMIT {top}
    """


def metric_confidence_label(kind: str) -> str:
    """Small UI label explaining how a metric is measured."""
    labels = {
        "exact": "Measurement: Exact",
        "allocated": "Measurement: Allocated from warehouse metering",
        "estimated": "Measurement: Estimated",
        "forecast": "Measurement: Forecast from recent observed burn",
        "projection": "Measurement: Projection from recent observed burn",
        "composite": "Measurement: Composite rollup from operational signals",
        "account": "Measurement: Account-wide",
        "account-wide": "Measurement: Account-wide",
    }
    return labels.get(str(kind or "").lower(), "Measurement depends on available account metadata")


def freshness_note(source: str) -> str:
    """Return expected Snowflake source latency for metric captions."""
    source_key = str(source or "").lower()
    if "information_schema" in source_key or source_key in {"live", "is"}:
        return "Freshness: live INFORMATION_SCHEMA view"
    if "account_usage" in source_key or source_key in {"account", "query_history", "warehouse_metering_history"}:
        return "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes"
    if "organization_usage" in source_key:
        return "Freshness: ORGANIZATION_USAGE can lag several hours"
    if "session" in source_key:
        return "Freshness: current Streamlit session only"
    return "Freshness: depends on source view availability"
