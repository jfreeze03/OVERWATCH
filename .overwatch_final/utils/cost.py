# utils/cost.py — Credit/dollar formatting + metered credit CTE builder
import pandas as pd
import streamlit as st
from config import CREDIT_RATES, COMPUTE_CREDIT_CASE, DEFAULTS

# Re-export for convenience
__all__ = [
    "format_credits", "credits_to_dollars", "estimate_live_credits",
    "build_metered_credit_cte", "CREDIT_RATES", "COMPUTE_CREDIT_CASE",
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
    """Build CTE that allocates metered warehouse credits to individual queries
    using hourly execution-time share.

    Args:
        days_back:       Time window in days (used if hours_back not set).
        hours_back:      Time window in hours (takes priority over days_back).
        include_recent:  If True, extends upper bound to CURRENT_TIMESTAMP()
                         (use for live/recent views). If False, upper bound is
                         DATEADD('hour', -24, ...) to avoid partial billing windows.

    Returns:
        SQL CTE fragment (metered_hourly, query_exec_share, per_query_credits).
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

    return f"""
    metered_hourly AS (
        SELECT
            warehouse_name,
            DATE_TRUNC('hour', start_time)  AS hour_bucket,
            SUM(credits_used_compute)       AS hourly_compute_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= {time_filter}
          AND start_time <  {upper_bound}
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
