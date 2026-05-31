# utils/cost.py — Credit/dollar formatting + metered credit CTE builder
import pandas as pd
import streamlit as st
from config import CREDIT_RATES, COMPUTE_CREDIT_CASE, DEFAULTS

# Re-export for convenience
__all__ = [
    "format_credits", "credits_to_dollars", "estimate_live_credits",
    "build_metered_credit_cte", "build_idle_warehouse_sql",
    "build_monitoring_cost_sql", "build_app_runtime_cost_sql",
    "build_cost_reconciliation_sql", "metric_confidence_label", "freshness_note",
    "CREDIT_RATES", "COMPUTE_CREDIT_CASE",
]


def _get_credit_price() -> float:
    return st.session_state.get("credit_price", DEFAULTS["credit_price"])


def format_credits(credits: float, credit_price: float = None) -> str:
    """Format credits as 'X.XX (${dollar})' — consistent across all sections."""
    if credits is None or (isinstance(credits, float) and pd.isna(credits)):
        return "0 ($0.00)"
    credits = float(credits)
    if credit_price is None:
        credit_price = _get_credit_price()
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
        credit_price = _get_credit_price()
    return round((credits or 0) * credit_price, 2)


def estimate_live_credits(row) -> float:
    """Fallback estimator for LIVE queries where metering data is not yet available.
    Uses warehouse size credit rate × elapsed seconds / 3600.
    """
    size = row.get("WAREHOUSE_SIZE", "") or ""
    exec_sec = float(
        row.get("EXEC_SEC", 0) or row.get("ELAPSED_SEC", 0) or 0
    )
    rate = CREDIT_RATES.get(size, 1)
    return round(rate * (exec_sec / 3600), 6)


def build_metered_credit_cte(
    days_back: int = None,
    hours_back: int = None,
    include_recent: bool = False,
) -> str:
    """Build CTE that allocates exact warehouse metering to queries by hourly execution share.

    Args:
        days_back:       Time window in days (used if hours_back not set).
        hours_back:      Time window in hours (takes priority over days_back).
        include_recent:  If True, extends upper bound to CURRENT_TIMESTAMP()
                         (use for live/recent views). If False, upper bound is
                         DATEADD('hour', -24, ...) to avoid partial billing windows.

    Returns:
        SQL CTE fragment (metered_hourly, query_exec_share, per_query_credits).
        The warehouse-hour total is exact; per-query credits are allocated estimates.
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
    ),
    per_query_credits AS (
        SELECT
            qs.query_id,
            qs.warehouse_name,
            qs.hour_bucket,
            ROUND(
                COALESCE(m.hourly_compute_credits, 0)
                * qs.exec_ms / NULLIF(qs.hour_total_exec_ms, 0),
                6
            ) AS metered_credits
        FROM query_exec_share qs
        LEFT JOIN metered_hourly m
          ON  qs.warehouse_name = m.warehouse_name
          AND qs.hour_bucket    = m.hour_bucket
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
            SUM(credits_used) AS hourly_credits
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
            'QUERY_HISTORY query_tag = OVERWATCH:v3, allocated from warehouse metering' AS source
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
            'WAREHOUSE_METERING_HISTORY where warehouse_name indicates Streamlit' AS source
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND (warehouse_name ILIKE 'SYSTEM$STREAMLIT%' OR warehouse_name ILIKE '%STREAMLIT%')
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
          AND (warehouse_name ILIKE 'SYSTEM$STREAMLIT%' OR warehouse_name ILIKE '%STREAMLIT%')
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


def build_cost_reconciliation_sql(days_back: int = 30) -> str:
    """Compare exact warehouse credits to allocated query credits by warehouse/day.

    WAREHOUSE_METERING_HISTORY is the source of truth. Query-level costs are
    allocated by execution-time share and will not always reconcile perfectly
    when warehouses are idle, when cloud services are involved, or when
    ACCOUNT_USAGE has latency.
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
    {build_metered_credit_cte(days_back=days_back, include_recent=False)},
    allocated_daily AS (
        SELECT
            DATE_TRUNC('day', q.start_time) AS usage_day,
            q.warehouse_name,
            COUNT(*) AS query_count,
            ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 6) AS allocated_query_credits
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


def metric_confidence_label(kind: str) -> str:
    """Small UI label explaining whether a metric is exact or estimated."""
    labels = {
        "exact": "Confidence: Exact",
        "allocated": "Confidence: Allocated / Estimated from exact warehouse metering",
        "estimated": "Confidence: Estimated",
        "forecast": "Confidence: Forecast based on recent observed burn",
        "projection": "Confidence: Projection based on recent observed burn",
        "composite": "Confidence: Composite score from weighted operational signals",
        "account": "Confidence: Account-wide",
        "account-wide": "Confidence: Account-wide",
    }
    return labels.get(str(kind or "").lower(), "Confidence: Calculation depends on available account metadata")


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
