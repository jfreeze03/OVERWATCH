"""Reusable warehouse metering SQL shapes shared by mart and live paths."""

from __future__ import annotations


def build_cost_cockpit_metering_sql(
    table: str,
    timestamp_column: str,
    filter_clause: str = "",
    *,
    days: int = 7,
) -> str:
    """Build current/prior warehouse credit movement for the cost cockpit."""
    days = int(days)
    return f"""
        WITH current_period AS (
            SELECT
                warehouse_name,
                SUM(COALESCE(credits_used, 0)) AS credits
            FROM {table}
            WHERE {timestamp_column} >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
              AND {timestamp_column} < CURRENT_TIMESTAMP()
              {filter_clause}
            GROUP BY warehouse_name
        ),
        prior_period AS (
            SELECT
                warehouse_name,
                SUM(COALESCE(credits_used, 0)) AS credits
            FROM {table}
            WHERE {timestamp_column} >= DATEADD('DAY', -{days * 2}, CURRENT_TIMESTAMP())
              AND {timestamp_column} < DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
              {filter_clause}
            GROUP BY warehouse_name
        ),
        deltas AS (
            SELECT
                COALESCE(c.warehouse_name, p.warehouse_name) AS warehouse_name,
                COALESCE(c.credits, 0) AS current_credits,
                COALESCE(p.credits, 0) AS prior_credits,
                COALESCE(c.credits, 0) - COALESCE(p.credits, 0) AS credit_delta
            FROM current_period c
            FULL OUTER JOIN prior_period p
                ON c.warehouse_name = p.warehouse_name
        )
        SELECT
            SUM(current_credits) AS current_credits,
            SUM(prior_credits) AS prior_credits,
            COUNT_IF(current_credits > 0) AS active_warehouses,
            MAX_BY(warehouse_name, credit_delta) AS top_increase_warehouse,
            MAX(credit_delta) AS top_increase_credits
        FROM deltas
    """


def build_cost_run_rate_metering_sql(
    table: str,
    timestamp_column: str,
    filter_clause: str = "",
) -> str:
    """Build complete-day 7d/30d run-rate and YOY warehouse cost trend."""
    return f"""
        WITH bounds AS (
            SELECT
                DATE_TRUNC('DAY', CURRENT_TIMESTAMP()) AS today_start,
                DATEADD('DAY', -7, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS current_7d_start,
                DATEADD('DAY', -30, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS current_30d_start,
                DATEADD('YEAR', -1, DATEADD('DAY', -7, DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))) AS yoy_7d_start,
                DATEADD('YEAR', -1, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS yoy_7d_end,
                DATEADD('YEAR', -1, DATEADD('DAY', -30, DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))) AS yoy_30d_start,
                DATEADD('YEAR', -1, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS yoy_30d_end
        ),
        metering AS (
            SELECT
                {timestamp_column} AS usage_ts,
                warehouse_name,
                COALESCE(credits_used, 0) AS credits_used
            FROM {table}, bounds
            WHERE {timestamp_column} >= yoy_30d_start
              AND {timestamp_column} < today_start
              {filter_clause}
        ),
        aggregate_trend AS (
            SELECT
                SUM(IFF(usage_ts >= current_7d_start AND usage_ts < today_start, credits_used, 0)) AS credits_7d,
                SUM(IFF(usage_ts >= current_30d_start AND usage_ts < today_start, credits_used, 0)) AS credits_30d,
                SUM(IFF(usage_ts >= yoy_7d_start AND usage_ts < yoy_7d_end, credits_used, 0)) AS yoy_7d_credits,
                SUM(IFF(usage_ts >= yoy_30d_start AND usage_ts < yoy_30d_end, credits_used, 0)) AS yoy_30d_credits,
                COUNT(DISTINCT IFF(usage_ts >= current_7d_start AND usage_ts < today_start, TO_DATE(usage_ts), NULL)) AS observed_days_7d,
                COUNT(DISTINCT IFF(usage_ts >= current_30d_start AND usage_ts < today_start, TO_DATE(usage_ts), NULL)) AS observed_days_30d,
                COUNT(DISTINCT IFF(usage_ts >= yoy_7d_start AND usage_ts < yoy_7d_end, TO_DATE(usage_ts), NULL)) AS yoy_days_7d,
                COUNT(DISTINCT IFF(usage_ts >= yoy_30d_start AND usage_ts < yoy_30d_end, TO_DATE(usage_ts), NULL)) AS yoy_days_30d
            FROM metering, bounds
        ),
        warehouse_yoy AS (
            SELECT
                warehouse_name,
                SUM(IFF(usage_ts >= current_7d_start AND usage_ts < today_start, credits_used, 0)) AS current_7d_credits,
                SUM(IFF(usage_ts >= yoy_7d_start AND usage_ts < yoy_7d_end, credits_used, 0)) AS yoy_7d_credits
            FROM metering, bounds
            GROUP BY warehouse_name
        ),
        top_yoy AS (
            SELECT
                warehouse_name AS top_yoy_increase_warehouse,
                current_7d_credits - yoy_7d_credits AS top_yoy_increase_credits
            FROM warehouse_yoy
            WHERE current_7d_credits > 0 OR yoy_7d_credits > 0
            QUALIFY ROW_NUMBER() OVER (
                ORDER BY current_7d_credits - yoy_7d_credits DESC, current_7d_credits DESC
            ) = 1
        )
        SELECT
            ROUND(COALESCE(a.credits_7d, 0), 4) AS credits_7d,
            ROUND(COALESCE(a.credits_7d, 0) / 7, 4) AS avg_daily_7d,
            ROUND(COALESCE(a.credits_30d, 0), 4) AS credits_30d,
            ROUND(COALESCE(a.credits_30d, 0) / 30, 4) AS avg_daily_30d,
            ROUND((COALESCE(a.credits_7d, 0) / 7) * 30, 4) AS projected_30d_from_7d,
            ROUND(COALESCE(a.yoy_7d_credits, 0), 4) AS yoy_7d_credits,
            ROUND(COALESCE(a.yoy_30d_credits, 0), 4) AS yoy_30d_credits,
            a.observed_days_7d,
            a.observed_days_30d,
            a.yoy_days_7d,
            a.yoy_days_30d,
            CASE
                WHEN COALESCE(a.credits_30d, 0) = 0 THEN NULL
                ELSE ROUND(((COALESCE(a.credits_7d, 0) / 7) - (a.credits_30d / 30)) / NULLIF(a.credits_30d / 30, 0) * 100, 2)
            END AS pct_vs_30d_avg,
            CASE
                WHEN a.yoy_days_7d < 5 OR COALESCE(a.yoy_7d_credits, 0) = 0 THEN NULL
                ELSE ROUND((COALESCE(a.credits_7d, 0) - a.yoy_7d_credits) / NULLIF(a.yoy_7d_credits, 0) * 100, 2)
            END AS yoy_7d_pct,
            CASE
                WHEN a.yoy_days_30d < 20 OR COALESCE(a.yoy_30d_credits, 0) = 0 THEN NULL
                ELSE ROUND((COALESCE(a.credits_30d, 0) - a.yoy_30d_credits) / NULLIF(a.yoy_30d_credits, 0) * 100, 2)
            END AS yoy_30d_pct,
            CASE
                WHEN COALESCE(a.credits_30d, 0) = 0 THEN 'No 30-day baseline'
                WHEN ((COALESCE(a.credits_7d, 0) / 7) - (a.credits_30d / 30)) / NULLIF(a.credits_30d / 30, 0) >= 0.15 THEN 'Accelerating'
                WHEN ((COALESCE(a.credits_7d, 0) / 7) - (a.credits_30d / 30)) / NULLIF(a.credits_30d / 30, 0) <= -0.15 THEN 'Cooling'
                ELSE 'Stable'
            END AS run_rate_state,
            CASE
                WHEN a.yoy_days_7d < 5 THEN 'No prior-year baseline'
                WHEN COALESCE(a.yoy_7d_credits, 0) = 0 THEN 'No prior-year spend'
                WHEN (COALESCE(a.credits_7d, 0) - a.yoy_7d_credits) / NULLIF(a.yoy_7d_credits, 0) >= 0.20 THEN 'Above prior year'
                WHEN (COALESCE(a.credits_7d, 0) - a.yoy_7d_credits) / NULLIF(a.yoy_7d_credits, 0) <= -0.20 THEN 'Below prior year'
                ELSE 'Near prior year'
            END AS yoy_state,
            COALESCE(t.top_yoy_increase_warehouse, 'No warehouse baseline') AS top_yoy_increase_warehouse,
            ROUND(COALESCE(t.top_yoy_increase_credits, 0), 4) AS top_yoy_increase_credits
        FROM aggregate_trend a
        LEFT JOIN top_yoy t ON TRUE
    """
