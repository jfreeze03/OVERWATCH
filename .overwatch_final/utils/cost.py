# utils/cost.py - Credit/dollar formatting + metered credit CTE builder
import pandas as pd
import streamlit as st
from config import CREDIT_RATES, COMPUTE_CREDIT_CASE, DEFAULTS

# Re-export for convenience
__all__ = [
    "get_credit_price", "get_storage_cost_per_tb",
    "format_credits", "credits_to_dollars", "estimate_live_credits",
    "query_attribution_supported",
    "build_metered_credit_cte", "build_idle_warehouse_sql",
    "build_monitoring_cost_sql", "build_app_runtime_cost_sql",
    "build_cost_reconciliation_sql", "build_snowflake_cost_management_account_sql",
    "build_snowflake_billed_credit_reconciliation_sql",
    "build_snowflake_org_currency_cost_sql", "build_snowflake_rate_sheet_reconciliation_sql",
    "build_snowflake_service_cost_lens_sql", "metric_confidence_label", "freshness_note",
    "CREDIT_RATES", "COMPUTE_CREDIT_CASE",
]


def get_credit_price() -> float:
    """Return the active credit price, defaulting to the mart contract setting."""
    return float(st.session_state.get("credit_price", DEFAULTS["credit_price"]))


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


def build_snowflake_cost_management_account_sql(
    days_back: int = 7,
    credit_price: float = None,
    wh_filter: str = "",
) -> str:
    """Return an Account Overview-style warehouse cost summary.

    Snowflake documents the Account Overview top-warehouse tile as querying
    ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY. This query keeps that warehouse
    credit source and dollarizes it with the configured ALFA rate.
    """
    days_back = max(1, int(days_back or 7))
    if credit_price is None:
        credit_price = DEFAULTS["credit_price"]
    credit_price = float(credit_price or DEFAULTS["credit_price"])
    wh_filter = wh_filter or ""
    return f"""
    WITH bounds AS (
        SELECT
            DATEADD('DAY', -{days_back}, CURRENT_DATE()) AS start_date,
            CURRENT_DATE() AS end_date,
            {credit_price:.4f}::FLOAT AS configured_credit_price_usd
    ),
    warehouse_daily AS (
        SELECT
            TO_DATE(start_time) AS usage_date,
            warehouse_name,
            SUM(COALESCE(credits_used, 0)) AS warehouse_credits,
            SUM(COALESCE(credits_used_compute, credits_used, 0)) AS compute_credits,
            SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
        WHERE start_time >= start_date
          AND start_time < end_date
          {wh_filter}
        GROUP BY usage_date, warehouse_name
    ),
    top_warehouses AS (
        SELECT
            warehouse_name,
            ROUND(SUM(warehouse_credits), 4) AS warehouse_credits
        FROM warehouse_daily
        GROUP BY warehouse_name
        QUALIFY ROW_NUMBER() OVER (ORDER BY SUM(warehouse_credits) DESC, warehouse_name) <= 5
    ),
    summary AS (
        SELECT
            ROUND(COALESCE(SUM(warehouse_credits), 0), 4) AS spend_in_credits,
            ROUND(COALESCE(SUM(compute_credits), 0), 4) AS compute_credits,
            ROUND(COALESCE(SUM(cloud_services_credits), 0), 4) AS cloud_services_credits,
            COUNT(DISTINCT warehouse_name) AS active_warehouses,
            COUNT(DISTINCT usage_date) AS observed_days
        FROM warehouse_daily
    )
    SELECT
        spend_in_credits,
        compute_credits,
        cloud_services_credits,
        ROUND(spend_in_credits * configured_credit_price_usd, 2) AS spend_in_currency_est_usd,
        configured_credit_price_usd AS compute_price_per_credit_usd,
        ROUND(spend_in_credits / NULLIF(observed_days, 0), 4) AS average_daily_credits,
        ROUND(spend_in_credits * configured_credit_price_usd / NULLIF(observed_days, 0), 2) AS average_daily_cost_est_usd,
        active_warehouses,
        observed_days,
        'SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY' AS snowflake_source,
        (
            SELECT LISTAGG(warehouse_name || ': ' || warehouse_credits || ' cr', ', ')
                WITHIN GROUP (ORDER BY warehouse_credits DESC, warehouse_name)
            FROM top_warehouses
        ) AS top_warehouses_by_cost
    FROM summary, bounds
    """


def build_snowflake_billed_credit_reconciliation_sql(days_back: int = 7) -> str:
    """Return account-level billed warehouse credits from METERING_DAILY_HISTORY."""
    days_back = max(1, int(days_back or 7))
    return f"""
    WITH bounds AS (
        SELECT
            DATEADD('DAY', -{days_back}, CURRENT_DATE()) AS start_date,
            CURRENT_DATE() AS end_date
    )
    SELECT
        ROUND(SUM(COALESCE(credits_used_compute, 0)), 4) AS account_compute_credits,
        ROUND(SUM(COALESCE(credits_used_cloud_services, 0)), 4) AS account_cloud_services_credits,
        ROUND(SUM(COALESCE(credits_adjustment_cloud_services, 0)), 4) AS account_cloud_services_adjustment,
        ROUND(SUM(COALESCE(credits_billed, 0)), 4) AS account_billed_warehouse_credits,
        COUNT(DISTINCT usage_date) AS billed_days,
        'SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY' AS snowflake_source
    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY, bounds
    WHERE usage_date >= start_date
      AND usage_date < end_date
      AND UPPER(service_type) = 'WAREHOUSE_METERING'
    """


def build_snowflake_org_currency_cost_sql(days_back: int = 7) -> str:
    """Return official organization currency spend when the role can access it."""
    days_back = max(1, int(days_back or 7))
    return f"""
    WITH bounds AS (
        SELECT
            DATEADD('DAY', -{days_back}, CURRENT_DATE()) AS start_date,
            CURRENT_DATE() AS end_date
    ),
    scoped AS (
        SELECT
            usage,
            usage_in_currency,
            currency,
            balance_source
        FROM SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY, bounds
        WHERE usage_date >= start_date
          AND usage_date < end_date
          AND UPPER(rating_type) = 'COMPUTE'
          AND UPPER(service_type) = 'WAREHOUSE_METERING'
          AND (
              UPPER(account_locator) = UPPER(CURRENT_ACCOUNT())
              OR UPPER(account_name) = UPPER(CURRENT_ACCOUNT_NAME())
          )
    )
    SELECT
        ROUND(COALESCE(SUM(usage), 0), 4) AS official_compute_credits,
        ROUND(COALESCE(SUM(usage_in_currency), 0), 2) AS official_spend_in_currency,
        ROUND(COALESCE(SUM(usage_in_currency), 0) / NULLIF(SUM(usage), 0), 4) AS official_effective_price_per_credit,
        ROUND(SUM(IFF(UPPER(COALESCE(balance_source, '')) = 'CAPACITY', usage_in_currency, 0)), 2) AS capacity_spend_in_currency,
        ROUND(SUM(IFF(UPPER(COALESCE(balance_source, '')) = 'ROLLOVER', usage_in_currency, 0)), 2) AS rollover_spend_in_currency,
        ROUND(SUM(IFF(UPPER(COALESCE(balance_source, '')) = 'OVERAGE', usage_in_currency, 0)), 2) AS overage_spend_in_currency,
        LISTAGG(DISTINCT COALESCE(balance_source, 'unknown'), ', ')
            WITHIN GROUP (ORDER BY COALESCE(balance_source, 'unknown')) AS balance_source_mix,
        COALESCE(MIN(currency), 'N/A') AS currency,
        'SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY' AS snowflake_source
    FROM scoped
    """


def build_snowflake_rate_sheet_reconciliation_sql(
    days_back: int = 7,
    configured_credit_price: float = None,
) -> str:
    """Return official effective rate comparison from ORGANIZATION_USAGE.RATE_SHEET_DAILY."""
    days_back = max(1, int(days_back or 7))
    if configured_credit_price is None:
        configured_credit_price = DEFAULTS["credit_price"]
    configured_credit_price = float(configured_credit_price or DEFAULTS["credit_price"])
    return f"""
    WITH bounds AS (
        SELECT
            DATEADD('DAY', -{days_back}, CURRENT_DATE()) AS start_date,
            CURRENT_DATE() AS end_date,
            {configured_credit_price:.4f}::FLOAT AS configured_credit_price_usd
    ),
    scoped AS (
        SELECT
            date AS rate_date,
            contract_number,
            account_name,
            account_locator,
            currency,
            effective_rate
        FROM SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY, bounds
        WHERE date >= start_date
          AND date < end_date
          AND UPPER(rating_type) = 'COMPUTE'
          AND UPPER(service_type) = 'WAREHOUSE_METERING'
          AND (
              UPPER(account_locator) = UPPER(CURRENT_ACCOUNT())
              OR UPPER(account_name) = UPPER(CURRENT_ACCOUNT_NAME())
          )
    )
    SELECT
        ROUND(AVG(effective_rate), 4) AS official_effective_rate,
        ROUND(MIN(effective_rate), 4) AS min_effective_rate,
        ROUND(MAX(effective_rate), 4) AS max_effective_rate,
        configured_credit_price_usd,
        ROUND(configured_credit_price_usd - AVG(effective_rate), 4) AS configured_vs_official_delta,
        ROUND(100 * (configured_credit_price_usd - AVG(effective_rate)) / NULLIF(AVG(effective_rate), 0), 2) AS configured_vs_official_pct,
        COUNT(DISTINCT rate_date) AS observed_rate_days,
        COUNT(DISTINCT contract_number) AS observed_contracts,
        COALESCE(MIN(currency), 'N/A') AS currency,
        'SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY' AS snowflake_source
    FROM scoped, bounds
    GROUP BY configured_credit_price_usd
    """


def build_snowflake_service_cost_lens_sql(
    days_back: int = 7,
    credit_price: float = None,
) -> str:
    """Return account service cost by official Snowflake service type.

    This uses METERING_DAILY_HISTORY so the UI can separate warehouse spend from
    serverless, AI/Cortex, storage, and data-transfer surfaces without rescanning
    high-cardinality query history.
    """
    days_back = max(1, int(days_back or 7))
    if credit_price is None:
        credit_price = DEFAULTS["credit_price"]
    credit_price = float(credit_price or DEFAULTS["credit_price"])
    return f"""
    WITH scoped AS (
        SELECT
            usage_date,
            UPPER(COALESCE(service_type, 'UNKNOWN')) AS service_type,
            COALESCE(credits_used_compute, 0) AS credits_used_compute,
            COALESCE(credits_used_cloud_services, 0) AS credits_used_cloud_services,
            COALESCE(credits_adjustment_cloud_services, 0) AS credits_adjustment_cloud_services,
            COALESCE(credits_billed, 0) AS credits_billed
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
        WHERE usage_date >= DATEADD('DAY', -{days_back}, CURRENT_DATE())
          AND usage_date < CURRENT_DATE()
    ),
    categorized AS (
        SELECT
            usage_date,
            service_type,
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
            credits_used_compute,
            credits_used_cloud_services,
            credits_adjustment_cloud_services,
            credits_billed
        FROM scoped
    )
    SELECT
        service_category,
        service_type,
        ROUND(SUM(credits_billed), 4) AS credits_billed,
        ROUND(SUM(credits_used_compute), 4) AS credits_used_compute,
        ROUND(SUM(COALESCE(credits_used_cloud_services, 0)), 4) AS credits_used_cloud_services,
        ROUND(SUM(credits_adjustment_cloud_services), 4) AS credits_adjustment_cloud_services,
        ROUND(SUM(credits_billed) * {credit_price:.4f}, 2) AS estimated_cost_usd,
        COUNT(DISTINCT usage_date) AS observed_days,
        'SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY' AS snowflake_source
    FROM categorized
    GROUP BY service_category, service_type
    HAVING ABS(SUM(credits_billed)) > 0
        OR ABS(SUM(credits_used_compute)) > 0
        OR ABS(SUM(COALESCE(credits_used_cloud_services, 0))) > 0
    ORDER BY credits_billed DESC, service_category, service_type
    """


def estimate_live_credits(row) -> float:
    """Fallback estimator for LIVE queries where metering data is not yet available.
    Uses warehouse size credit rate times elapsed seconds / 3600.
    """
    size = row.get("WAREHOUSE_SIZE", "") or ""
    exec_sec = float(
        row.get("EXEC_SEC", 0) or row.get("ELAPSED_SEC", 0) or 0
    )
    rate = CREDIT_RATES.get(size, 1)
    return round(rate * (exec_sec / 3600), 6)


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


def metric_confidence_label(kind: str) -> str:
    """Small UI label explaining the source basis for a metric."""
    labels = {
        "exact": "Source basis: Exact",
        "allocated": "Source basis: Allocated / estimated from exact warehouse metering",
        "estimated": "Source basis: Estimated",
        "forecast": "Source basis: Forecast from recent observed burn",
        "projection": "Source basis: Projection from recent observed burn",
        "composite": "Source basis: Composite score from weighted operational signals",
        "account": "Source basis: Account-wide",
        "account-wide": "Source basis: Account-wide",
    }
    return labels.get(str(kind or "").lower(), "Source basis: Calculation depends on available account metadata")


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
