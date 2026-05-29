# utils/cost.py — Credit/dollar formatting + metered credit CTE builder
import pandas as pd
import streamlit as st
from config import CREDIT_RATES, COMPUTE_CREDIT_CASE, DEFAULTS

# Re-export for convenience
__all__ = [
    "format_credits", "credits_to_dollars", "estimate_live_credits",
    "build_metered_credit_cte", "build_idle_warehouse_sql",
    "metric_confidence_label", "CREDIT_RATES", "COMPUTE_CREDIT_CASE",
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
            SUM(credits_used)               AS hourly_compute_credits
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


def metric_confidence_label(kind: str) -> str:
    """Small UI label explaining whether a metric is exact or estimated."""
    labels = {
        "exact": "Confidence: Exact Snowflake metering",
        "allocated": "Confidence: Allocated from exact warehouse metering",
        "estimated": "Confidence: Estimated from observed runtime",
        "account": "Confidence: Account-wide Snowflake metering",
    }
    return labels.get(str(kind or "").lower(), "Confidence: Calculation depends on available account metadata")
