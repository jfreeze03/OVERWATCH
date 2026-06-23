"""Cost Center SQL builders."""
from __future__ import annotations

import pandas as pd

from sections.cost_center_contracts import NO_DATABASE_CONTEXT_VALUES
from sections.cost_center_models import _row_text
from utils import (
    build_metered_credit_cte,
    filter_existing_columns,
    get_company_case_expr,
    get_environment_case_expr,
    get_environment_filter_clause,
    get_global_filter_clause,
    sql_literal,
)


def _annual_service_projection_sql() -> str:
    """Return account-wide annual service projection SQL from Snowflake metering."""
    return """
        SELECT
            DATE_TRUNC('day', start_time)::DATE AS usage_date,
            SUM(COALESCE(credits_used, 0)) AS daily_credits,
            SUM(COALESCE(credits_used_compute, 0)) AS compute_credits,
            SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits,
            COUNT(DISTINCT service_type) AS active_services
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
        WHERE start_time >= DATE_TRUNC('year', CURRENT_DATE())
          AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
        GROUP BY DATE_TRUNC('day', start_time)::DATE
        ORDER BY usage_date
    """


def _snowflake_admin_reconciliation_sql(days_back: int = 30) -> str:
    """Return official account-level cost totals for Admin/Cost Management reconciliation."""
    days_back = max(1, int(days_back or 30))
    return f"""
        WITH bounds AS (
            SELECT
                DATEADD('day', -{days_back}, DATEADD('hour', -24, CURRENT_TIMESTAMP())) AS start_ts,
                DATEADD('hour', -24, CURRENT_TIMESTAMP()) AS end_ts
        ),
        account_metering AS (
            SELECT ROUND(SUM(COALESCE(credits_used, 0)), 6) AS account_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY, bounds
            WHERE start_time >= bounds.start_ts
              AND start_time < bounds.end_ts
        ),
        warehouse_metering AS (
            SELECT ROUND(SUM(COALESCE(credits_used, 0)), 6) AS warehouse_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
            WHERE start_time >= bounds.start_ts
              AND start_time < bounds.end_ts
        )
        SELECT
            'Snowflake Admin account total' AS measurement,
            'ALL' AS scope,
            COALESCE(account_credits, 0) AS credits,
            'SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY' AS source,
            'Exact account-level' AS confidence,
            'Do not split by company without service-specific attribution.' AS company_split_note
        FROM account_metering
        UNION ALL
        SELECT
            'Official warehouse compute total' AS measurement,
            'ALL' AS scope,
            COALESCE(warehouse_credits, 0) AS credits,
            'SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY' AS source,
            'Exact warehouse-level' AS confidence,
            'Can be split by configured warehouse ownership.' AS company_split_note
        FROM warehouse_metering
        UNION ALL
        SELECT
            'Account service / other credits' AS measurement,
            'ALL' AS scope,
            GREATEST(COALESCE(account_credits, 0) - COALESCE(warehouse_credits, 0), 0) AS credits,
            'METERING_HISTORY minus WAREHOUSE_METERING_HISTORY' AS source,
            'Exact account-level bridge' AS confidence,
            'Keep account-wide unless a service view exposes owner, user, warehouse, or database.' AS company_split_note
        FROM account_metering, warehouse_metering
    """


def _cost_center_query_history_expressions(session) -> tuple[str, str, str]:
    """Return optional QUERY_HISTORY expressions for Cost Center renderers."""
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE", "BYTES_SCANNED", "QUERY_TAG"],
    ))
    max_wh_size_expr = "MAX(q.warehouse_size)" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR"
    bytes_scanned_sum_expr = "SUM(q.bytes_scanned)" if "BYTES_SCANNED" in qh_cols else "0"
    query_tag_dimension_expr = "COALESCE(q.query_tag, 'UNTAGGED')" if "QUERY_TAG" in qh_cols else "'UNTAGGED'"
    return max_wh_size_expr, bytes_scanned_sum_expr, query_tag_dimension_expr


def _cost_explorer_live_sql(
    days: int,
    company: str,
    warehouse_size_expr: str,
    department_contains: str = "",
) -> str:
    company_expr = get_company_case_expr("q.warehouse_name", "q.database_name", "q.user_name", "q.role_name")
    environment_expr = get_environment_case_expr("q.database_name")
    scope = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name", "q.schema_name"
    )
    dept_filter = (
        f"AND COALESCE(t.cost_center_tag, t.owner_tag, '') ILIKE '%' || {sql_literal(department_contains, 300)} || '%'"
        if str(department_contains or "").strip()
        else ""
    )
    return f"""
    WITH {build_metered_credit_cte(days_back=days)},
    warehouse_tags AS (
        SELECT
            object_name AS warehouse_name,
            MAX(IFF(
                UPPER(tag_name) IN ('COST_CENTER', 'COSTCENTER', 'DEPARTMENT', 'BILLING_OWNER'),
                tag_value,
                NULL
            )) AS cost_center_tag,
            MAX(IFF(
                UPPER(tag_name) IN ('OWNER', 'BUSINESS_OWNER', 'SERVICE_OWNER', 'DATA_OWNER', 'APPLICATION_OWNER'),
                tag_value,
                NULL
            )) AS owner_tag
        FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
        WHERE UPPER(COALESCE(domain, '')) = 'WAREHOUSE'
        GROUP BY object_name
    ),
    query_costs AS (
        SELECT
            {company_expr} AS company,
            {environment_expr} AS environment,
            COALESCE(q.database_name, 'NO_DATABASE_CONTEXT') AS database_name,
            COALESCE(q.user_name, 'Unknown user') AS user_name,
            COALESCE(q.role_name, 'Unknown role') AS role_name,
            COALESCE(q.warehouse_name, 'Unknown warehouse') AS warehouse_name,
            {warehouse_size_expr} AS warehouse_size,
            COALESCE(NULLIF(t.cost_center_tag, ''), NULLIF(t.owner_tag, ''), 'Unassigned') AS department,
            COALESCE(NULLIF(t.cost_center_tag, ''), NULLIF(t.owner_tag, ''), 'Unassigned') AS cost_owner,
            IFF(COALESCE(t.cost_center_tag, t.owner_tag, '') <> '', 'WAREHOUSE_TAG', 'QUERY_USER') AS owner_source,
            IFF(COALESCE(t.cost_center_tag, t.owner_tag, '') <> '',
                'Warehouse tag evidence from TAG_REFERENCES.',
                'Query user only; validate owner or department before billing.'
            ) AS owner_evidence,
            COUNT(*) AS query_count,
            ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS total_credits,
            MIN(q.start_time::DATE) AS first_usage_date,
            MAX(q.start_time::DATE) AS last_usage_date,
            COUNT(DISTINCT q.start_time::DATE) AS active_days
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
        LEFT JOIN warehouse_tags t ON UPPER(t.warehouse_name) = UPPER(q.warehouse_name)
        WHERE q.start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {scope}
          {dept_filter}
        GROUP BY 1,2,3,4,5,6,8,9,10,11
    )
    SELECT
        company,
        environment,
        database_name,
        user_name,
        role_name,
        warehouse_name,
        warehouse_size,
        department,
        cost_owner,
        owner_source,
        owner_evidence,
        query_count,
        total_credits,
        first_usage_date,
        last_usage_date,
        active_days
    FROM query_costs
    ORDER BY total_credits DESC, query_count DESC
    LIMIT 10000
    """


def _chargeback_cost_verification_sql(
    row: pd.Series,
    *,
    lookback_days: int = 30,
    company: str = "",
) -> str:
    """Build read-only evidence for a chargeback/cost-outlier queue item."""
    days = max(1, min(int(lookback_days or 30), 90))
    wh = _row_text(row, "WAREHOUSE_NAME") or "Unknown warehouse"
    user = _row_text(row, "USER_NAME")
    database = _row_text(row, "DATABASE_NAME")
    environment = _row_text(row, "ENVIRONMENT")
    row_company = _row_text(row, "COMPANY") or company
    wh_clause = f"AND q.warehouse_name = {sql_literal(wh, 300)}"
    user_clause = (
        f"AND q.user_name = {sql_literal(user, 300)}"
        if user and user.upper() not in {"UNKNOWN USER", "UNKNOWN_USER"}
        else ""
    )
    database_clause = ""
    if database and database.upper() not in NO_DATABASE_CONTEXT_VALUES:
        database_clause = f"AND q.database_name = {sql_literal(database, 300)}"
    elif environment and environment.upper() not in {"ALL", "NO DATABASE CONTEXT", "NO_DATABASE_CONTEXT"}:
        env_filter = get_environment_filter_clause(
            "q.database_name",
            environment=environment,
            company=row_company,
        )
        database_clause = env_filter

    return f"""WITH query_scope AS (
    SELECT
        q.warehouse_name,
        COALESCE(q.database_name, 'NO_DATABASE_CONTEXT') AS database_name,
        COALESCE(q.user_name, 'UNKNOWN_USER') AS user_name,
        COUNT(*) AS query_count,
        SUM(COALESCE(q.total_elapsed_time, 0)) / 1000 AS total_elapsed_sec,
        AVG(COALESCE(q.total_elapsed_time, 0)) / 1000 AS avg_elapsed_sec,
        APPROX_PERCENTILE(COALESCE(q.total_elapsed_time, 0) / 1000, 0.95) AS p95_elapsed_sec,
        SUM(COALESCE(q.bytes_scanned, 0)) / POWER(1024, 4) AS tb_scanned,
        SUM(
            COALESCE(q.bytes_spilled_to_local_storage, 0)
            + COALESCE(q.bytes_spilled_to_remote_storage, 0)
        ) / POWER(1024, 3) AS spill_gb,
        MAX(q.start_time) AS latest_query_time
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
    WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      {wh_clause}
      {user_clause}
      {database_clause}
    GROUP BY q.warehouse_name, COALESCE(q.database_name, 'NO_DATABASE_CONTEXT'), COALESCE(q.user_name, 'UNKNOWN_USER')
),
metering_scope AS (
    SELECT
        warehouse_name,
        SUM(COALESCE(credits_used_compute, credits_used)) AS warehouse_compute_credits,
        SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits,
        MAX(end_time) AS latest_metering_time
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND warehouse_name = {sql_literal(wh, 300)}
    GROUP BY warehouse_name
),
owner_tag_scope AS (
    SELECT
        domain,
        object_database,
        object_name,
        tag_name,
        tag_value
    FROM SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES
    WHERE UPPER(tag_name) IN ('COST_OWNER', 'DATA_OWNER', 'APP_OWNER', 'APPLICATION_OWNER', 'BUSINESS_OWNER', 'SERVICE_OWNER')
      AND tag_value IS NOT NULL
      AND (
        (UPPER(domain) = 'WAREHOUSE' AND UPPER(object_name) = UPPER({sql_literal(wh, 300)}))
        OR (
          UPPER(domain) = 'DATABASE'
          AND UPPER(COALESCE(object_database, object_name)) = UPPER({sql_literal(database, 300)})
        )
      )
)
SELECT
    q.warehouse_name,
    q.database_name,
    q.user_name,
    q.query_count,
    ROUND(q.total_elapsed_sec, 2) AS total_elapsed_sec,
    ROUND(q.avg_elapsed_sec, 2) AS avg_elapsed_sec,
    ROUND(q.p95_elapsed_sec, 2) AS p95_elapsed_sec,
    ROUND(q.tb_scanned, 4) AS tb_scanned,
    ROUND(q.spill_gb, 4) AS spill_gb,
    ROUND(COALESCE(m.warehouse_compute_credits, 0), 4) AS warehouse_compute_credits,
    ROUND(COALESCE(m.cloud_services_credits, 0), 4) AS cloud_services_credits,
    'Allocated / Estimated' AS allocation_confidence,
    LISTAGG(DISTINCT o.domain || ':' || o.tag_name || '=' || o.tag_value, '; ') AS owner_tag_evidence,
    q.latest_query_time,
    m.latest_metering_time
FROM query_scope q
LEFT JOIN metering_scope m
  ON m.warehouse_name = q.warehouse_name
LEFT JOIN owner_tag_scope o
  ON 1 = 1
GROUP BY
    q.warehouse_name,
    q.database_name,
    q.user_name,
    q.query_count,
    q.total_elapsed_sec,
    q.avg_elapsed_sec,
    q.p95_elapsed_sec,
    q.tb_scanned,
    q.spill_gb,
    m.warehouse_compute_credits,
    m.cloud_services_credits,
    q.latest_query_time,
    m.latest_metering_time
ORDER BY total_elapsed_sec DESC, query_count DESC
LIMIT 50"""


def _warehouse_cost_verification_sql(warehouse_name: str, lookback_days: int = 7) -> str:
    wh = sql_literal(warehouse_name, 300)
    days = max(1, int(lookback_days or 7))
    return f"""-- Exact warehouse-metering comparison
WITH daily AS (
    SELECT TO_DATE(start_time) AS usage_date,
           warehouse_name,
           SUM(COALESCE(credits_used, 0)) AS credits_used,
           SUM(COALESCE(credits_used_compute, 0)) AS compute_credits,
           SUM(COALESCE(credits_used_cloud_services, 0)) AS cloud_services_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE warehouse_name = {wh}
      AND start_time >= DATEADD('day', -{days * 2}, CURRENT_TIMESTAMP())
    GROUP BY usage_date, warehouse_name
)
SELECT CASE WHEN usage_date >= DATEADD('day', -{days}, CURRENT_DATE()) THEN 'CURRENT' ELSE 'PRIOR' END AS period,
       warehouse_name,
       SUM(credits_used) AS credits_used,
       SUM(compute_credits) AS compute_credits,
       SUM(cloud_services_credits) AS cloud_services_credits
FROM daily
GROUP BY period, warehouse_name
ORDER BY period;

-- After action, rerun this query for the next complete period and attach the measured delta to the action queue.
"""


__all__ = ['_annual_service_projection_sql', '_snowflake_admin_reconciliation_sql', '_cost_center_query_history_expressions', '_cost_explorer_live_sql', '_chargeback_cost_verification_sql', '_warehouse_cost_verification_sql']
