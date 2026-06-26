"""Executive Landing snapshot and observability loaders."""
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from config import (
    ACTION_QUEUE_TABLE,
    ALERT_DB,
    ALERT_SCHEMA,
    DEFAULT_COMPANY,
    DEFAULT_DAY_WINDOW,
    DEFAULT_ENVIRONMENT,
    DEFAULTS,
    DAY_WINDOW_OPTIONS,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.navigation import apply_navigation_state, apply_section_workflow_navigation
from sections.shell_helpers import (
    render_escaped_bold_text,
    render_refresh_contract,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
)
from runtime_state import EXECUTIVE_LANDING_WORKFLOW
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note


pd = lazy_pandas()

build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_schema_migration_status_sql = _lazy_util("build_schema_migration_status_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_environment_label = _lazy_util("get_environment_label")
get_session_for_action = _lazy_util("get_session_for_action")
load_action_queue = _lazy_util("load_action_queue")
load_alert_history = _lazy_util("load_alert_history")
mart_object_name = _lazy_util("mart_object_name")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
build_loaded_section_alert_signal_board = _lazy_util("build_loaded_section_alert_signal_board")
load_enterprise_operating_rollups = _lazy_util("load_enterprise_operating_rollups")
load_change_intelligence_summary = _lazy_util("load_change_intelligence_summary")
load_closed_loop_summary = _lazy_util("load_closed_loop_summary")
load_command_center_summary = _lazy_util("load_command_center_summary")
load_executive_scorecard_summary = _lazy_util("load_executive_scorecard_summary")
load_executive_forecast_summary = _lazy_util("load_executive_forecast_summary")
load_production_readiness_summary = _lazy_util("load_production_readiness_summary")
render_workflow_selector = _lazy_util("render_workflow_selector")
run_query = _lazy_util("run_query")
safe_identifier = _lazy_util("safe_identifier")
snowflake_connection_known_unavailable = _lazy_util("snowflake_connection_known_unavailable")
sql_literal = _lazy_util("sql_literal")


from sections.executive_landing_contracts import *
from sections.executive_landing_common import _active_company, _active_environment
from sections.executive_landing_models import _executive_snapshot_scope, _obs_rows


_OBS_COLUMNS = [
    "PANEL",
    "METRIC",
    "DIMENSION",
    "PERIOD_START",
    "VALUE",
    "VALUE_USD",
    "UNIT",
    "SORT_ORDER",
]


def _load_alerts(session, company: str, environment: str, days: int) -> pd.DataFrame:
    return load_alert_history(
        session,
        company=company,
        environment=environment,
        days=int(days),
        limit=100,
        section="Executive Landing",
    )

def _company_filter_sql(alias: str = "") -> str:
    company = _active_company()
    if str(company or "").upper() == "ALL":
        return ""
    prefix = f"{alias}." if alias else ""
    return f"AND {prefix}COMPANY = {sql_literal(company, 100)}"

def _environment_filter_sql(alias: str = "") -> str:
    environment = _active_environment()
    if str(environment or "").upper() == "ALL":
        return ""
    prefix = f"{alias}." if alias else ""
    return f"AND UPPER(COALESCE({prefix}ENVIRONMENT, 'ALL')) = {sql_literal(environment.upper(), 100)}"

def _build_executive_observability_sql(
    company: str,
    environment: str,
    days: int,
    *,
    credit_price: float,
    ai_credit_price: float,
) -> str:
    """Return the tiny first-paint executive board query."""
    days = max(1, int(days or DEFAULT_DAY_WINDOW))
    _ = (credit_price, ai_credit_price)
    company_value = "ALL" if str(company or "").upper() == "ALL" else str(company or DEFAULT_COMPANY)
    environment_value = "ALL" if str(environment or "").upper() == "ALL" else str(environment or DEFAULT_ENVIRONMENT)
    company_lit = sql_literal(company_value.upper(), 100)
    environment_lit = sql_literal(environment_value.upper(), 100)
    board_table = mart_object_name("MART_EXECUTIVE_OBSERVABILITY")
    return f"""
WITH candidate AS (
    SELECT
        PANEL,
        METRIC,
        DIMENSION,
        PERIOD_START,
        VALUE,
        VALUE_USD,
        UNIT,
        SORT_ORDER,
        COMPANY,
        ENVIRONMENT,
        SNAPSHOT_TS
    FROM {board_table}
    WHERE WINDOW_DAYS = {days}
      AND UPPER(COMPANY) IN ({company_lit}, 'ALL')
      AND (
        UPPER(COALESCE(ENVIRONMENT, 'ALL')) = 'ALL'
        OR UPPER(COALESCE(ENVIRONMENT, 'ALL')) = {environment_lit}
      )
      AND SNAPSHOT_TS >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
),
ranked AS (
    SELECT
        PANEL,
        METRIC,
        DIMENSION,
        PERIOD_START,
        VALUE,
        VALUE_USD,
        UNIT,
        SORT_ORDER,
        ROW_NUMBER() OVER (
            PARTITION BY PANEL, METRIC, DIMENSION, PERIOD_START, SORT_ORDER
            ORDER BY
                IFF(UPPER(COMPANY) = {company_lit}, 0, 1),
                IFF(UPPER(COALESCE(ENVIRONMENT, 'ALL')) = {environment_lit}, 0, 1),
                SNAPSHOT_TS DESC
        ) AS RN
    FROM candidate
)
SELECT PANEL, METRIC, DIMENSION, PERIOD_START, VALUE, VALUE_USD, UNIT, SORT_ORDER
FROM ranked
WHERE RN = 1
ORDER BY PANEL, SORT_ORDER, PERIOD_START, VALUE DESC
"""

def _observability_scope(company: str, environment: str, days: int) -> tuple[str, str, int]:
    return str(company), str(environment), int(days)

def _normalise_observability_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=_OBS_COLUMNS)
    rows = frame.copy()
    for column in _OBS_COLUMNS:
        if column not in rows.columns:
            rows[column] = None
    return rows[_OBS_COLUMNS]

def _sort_observability_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    rows = _normalise_observability_frame(frame)
    if rows.empty:
        return rows
    rows["SORT_ORDER"] = pd.to_numeric(rows["SORT_ORDER"], errors="coerce").fillna(9999)
    return rows.sort_values(
        ["PANEL", "SORT_ORDER", "DIMENSION"],
        na_position="last",
    ).reset_index(drop=True)

def _observability_status_frame(statuses: list[dict]) -> pd.DataFrame:
    rows = []
    for idx, status in enumerate(statuses, start=1):
        rows.append({
            "PANEL": "SOURCE_STATUS",
            "METRIC": str(status.get("state") or "Unknown"),
            "DIMENSION": str(status.get("source") or "Unknown source"),
            "PERIOD_START": None,
            "VALUE": None,
            "VALUE_USD": None,
            "UNIT": str(status.get("detail") or ""),
            "SORT_ORDER": 990 + idx,
        })
    return pd.DataFrame(rows, columns=_OBS_COLUMNS)

def _store_observability_payload(
    board: pd.DataFrame | None,
    *,
    company: str,
    environment: str,
    days: int,
    source: str,
    error: str = "",
) -> bool:
    normalised = _sort_observability_frame(board)
    st.session_state[OBSERVABILITY_STATE_KEY] = {
        "data": normalised,
        "scope": _observability_scope(company, environment, int(days)),
        "source": source,
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
        "error": error,
    }
    return not _obs_rows(normalised, "KPI").empty

def _store_connection_unavailable_observability(company: str, environment: str, days: int) -> bool:
    return _store_observability_payload(
        _observability_status_frame([{
            "source": "Connection",
            "state": "Unavailable",
            "detail": (
                "Snowflake connection is not available yet. Executive Landing is showing local shell "
                "state until the app has a live Snowflake session or Refresh Decision Brief is used after configuration."
            ),
        }]),
        company=company,
        environment=environment,
        days=int(days),
        source=OBSERVABILITY_OFFLINE_SOURCE,
        error="Snowflake connection is not available yet; showing local Executive Landing shell state.",
    )

def _build_executive_observability_query_parts(
    company: str,
    environment: str,
    days: int,
    *,
    credit_price: float,
    ai_credit_price: float,
) -> list[tuple[str, str, str]]:
    """Build independent fast queries so one missing source cannot blank the board."""
    days = max(1, int(days or DEFAULT_DAY_WINDOW))
    company_clause = "" if str(company or "").upper() == "ALL" else f"AND COMPANY = {sql_literal(company, 100)}"
    env_clause = "" if str(environment or "").upper() == "ALL" else f"AND UPPER(COALESCE(ENVIRONMENT, 'ALL')) = {sql_literal(str(environment).upper(), 100)}"
    cost_table = mart_object_name("FACT_COST_DAILY")
    cortex_table = mart_object_name("FACT_CORTEX_DAILY")
    query_table = mart_object_name("FACT_QUERY_HOURLY")
    query_detail_table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    task_table = mart_object_name("FACT_TASK_RUN")
    storage_table = mart_object_name("FACT_STORAGE_DAILY")
    control_table = mart_object_name("MART_DBA_CONTROL_ROOM")
    alert_table = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier('ALERT_EVENTS')}"
    queue_table = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier(ACTION_QUEUE_TABLE)}"

    cost_sql = f"""
WITH cost_daily AS (
    SELECT
        USAGE_DATE,
        COALESCE(SERVICE_CATEGORY, 'Unknown') AS SERVICE_CATEGORY,
        COALESCE(SERVICE_TYPE, 'Unknown') AS SERVICE_TYPE,
        SUM(COALESCE(CREDITS_BILLED, CREDITS_USED_COMPUTE, 0)) AS CREDITS,
        SUM(COALESCE(
            EST_COST_USD,
            COALESCE(CREDITS_BILLED, CREDITS_USED_COMPUTE, 0) * {float(credit_price):.4f}
        )) AS COST_USD,
        MAX(LOAD_TS) AS LOAD_TS
    FROM {cost_table}
    WHERE USAGE_DATE >= DATEADD('MONTH', -6, CURRENT_DATE())
      AND USAGE_DATE < CURRENT_DATE()
      {company_clause}
    GROUP BY USAGE_DATE, COALESCE(SERVICE_CATEGORY, 'Unknown'), COALESCE(SERVICE_TYPE, 'Unknown')
),
cost_current AS (
    SELECT
        SUM(IFF(USAGE_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE()), CREDITS, 0)) AS CURRENT_CREDITS,
        SUM(IFF(USAGE_DATE >= DATEADD('DAY', -{days * 2}, CURRENT_DATE()) AND USAGE_DATE < DATEADD('DAY', -{days}, CURRENT_DATE()), CREDITS, 0)) AS PRIOR_CREDITS,
        SUM(IFF(USAGE_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE()), COST_USD, 0)) AS CURRENT_COST_USD,
        SUM(IFF(USAGE_DATE >= DATEADD('DAY', -{days * 2}, CURRENT_DATE()) AND USAGE_DATE < DATEADD('DAY', -{days}, CURRENT_DATE()), COST_USD, 0)) AS PRIOR_COST_USD,
        MAX(LOAD_TS) AS LOAD_TS
    FROM cost_daily
),
monthly_cost AS (
    SELECT
        DATE_TRUNC('MONTH', USAGE_DATE) AS PERIOD_START,
        SUM(CREDITS) AS CREDITS,
        SUM(COST_USD) AS COST_USD
    FROM cost_daily
    GROUP BY DATE_TRUNC('MONTH', USAGE_DATE)
),
cost_driver_ranked AS (
    SELECT
        SERVICE_CATEGORY || ' / ' || SERVICE_TYPE AS DRIVER,
        SUM(CREDITS) AS CREDITS,
        SUM(COST_USD) AS COST_USD,
        ROW_NUMBER() OVER (
            ORDER BY SUM(COST_USD) DESC, SERVICE_CATEGORY || ' / ' || SERVICE_TYPE
        ) AS RN
    FROM cost_daily
    WHERE USAGE_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE())
    GROUP BY SERVICE_CATEGORY, SERVICE_TYPE
)
SELECT 'KPI' AS PANEL, 'Credits Used' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(CURRENT_CREDITS, 0)::FLOAT AS VALUE, COALESCE(CURRENT_COST_USD, 0)::FLOAT AS VALUE_USD, 'credits_usd' AS UNIT, 1 AS SORT_ORDER
FROM cost_current
UNION ALL
SELECT 'KPI', 'Spend Delta', 'Current vs prior', NULL::TIMESTAMP_NTZ,
       COALESCE(CURRENT_CREDITS, 0) - COALESCE(PRIOR_CREDITS, 0),
       COALESCE(CURRENT_COST_USD, 0) - COALESCE(PRIOR_COST_USD, 0), 'credits_usd', 2
FROM cost_current
UNION ALL
SELECT 'DAILY_COST', 'Daily Spend', TO_VARCHAR(USAGE_DATE), TO_TIMESTAMP_NTZ(USAGE_DATE),
       SUM(CREDITS), SUM(COST_USD), 'credits_usd', 101
FROM cost_daily
WHERE USAGE_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE())
GROUP BY USAGE_DATE
UNION ALL
SELECT 'MONTHLY_COST', 'Monthly Spend', TO_VARCHAR(PERIOD_START, 'YYYY-MM'), TO_TIMESTAMP_NTZ(PERIOD_START),
       CREDITS, COST_USD, 'credits_usd', 201
FROM monthly_cost
UNION ALL
SELECT 'COST_DRIVER', 'Cost Drivers', DRIVER, NULL::TIMESTAMP_NTZ,
       CREDITS, COST_USD, 'credits_usd', 251
FROM cost_driver_ranked
WHERE RN <= 8
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Cost facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 901
FROM cost_daily
"""

    cortex_sql = f"""
WITH cortex_daily AS (
    SELECT
        USAGE_DATE,
        SUM(COALESCE(CREDITS_USED, 0)) AS CREDITS,
        SUM(COALESCE(EST_COST_USD, COALESCE(CREDITS_USED, 0) * {float(ai_credit_price):.4f})) AS COST_USD,
        SUM(COALESCE(REQUEST_COUNT, 0)) AS REQUESTS,
        MAX(LOAD_TS) AS LOAD_TS
    FROM {cortex_table}
    WHERE USAGE_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE())
      AND USAGE_DATE < CURRENT_DATE()
      {company_clause}
    GROUP BY USAGE_DATE
)
SELECT 'KPI' AS PANEL, 'Cortex Spend' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(SUM(CREDITS), 0)::FLOAT AS VALUE, COALESCE(SUM(COST_USD), 0)::FLOAT AS VALUE_USD, 'credits_usd' AS UNIT, 3 AS SORT_ORDER
FROM cortex_daily
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Cortex facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 904
FROM cortex_daily
"""

    query_sql = f"""
WITH query_daily AS (
    SELECT
        TO_DATE(HOUR_START) AS USAGE_DATE,
        SUM(COALESCE(QUERY_COUNT, 0)) AS QUERIES,
        SUM(COALESCE(FAILED_COUNT, 0)) AS FAILED_QUERIES,
        SUM(COALESCE(TOTAL_ELAPSED_MS, 0)) AS ELAPSED_MS,
        SUM(COALESCE(TOTAL_QUEUED_MS, 0)) AS QUEUED_MS,
        SUM(COALESCE(TOTAL_SPILL_BYTES, 0)) AS SPILL_BYTES,
        SUM(COALESCE(TOTAL_BYTES_SCANNED, 0)) AS BYTES_SCANNED,
        MAX(COALESCE(P95_EXECUTION_MS, 0)) AS P95_EXECUTION_MS,
        MAX(LOAD_TS) AS LOAD_TS
    FROM {query_table}
    WHERE HOUR_START >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
    GROUP BY TO_DATE(HOUR_START)
),
query_type AS (
    SELECT
        COALESCE(QUERY_TYPE, 'Unknown') AS QUERY_TYPE,
        SUM(COALESCE(QUERY_COUNT, 0)) AS QUERIES
    FROM {query_table}
    WHERE HOUR_START >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
    GROUP BY COALESCE(QUERY_TYPE, 'Unknown')
),
query_type_ranked AS (
    SELECT QUERY_TYPE, QUERIES,
           ROW_NUMBER() OVER (ORDER BY QUERIES DESC, QUERY_TYPE) AS RN
    FROM query_type
),
query_database AS (
    SELECT
        COALESCE(DATABASE_NAME, 'Unknown') AS DATABASE_NAME,
        SUM(COALESCE(QUERY_COUNT, 0)) AS QUERIES
    FROM {query_table}
    WHERE HOUR_START >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
    GROUP BY COALESCE(DATABASE_NAME, 'Unknown')
),
query_database_ranked AS (
    SELECT DATABASE_NAME, QUERIES,
           ROW_NUMBER() OVER (ORDER BY QUERIES DESC, DATABASE_NAME) AS RN
    FROM query_database
),
warehouse_pressure AS (
    SELECT
        COALESCE(WAREHOUSE_NAME, 'Unknown') AS WAREHOUSE_NAME,
        SUM(COALESCE(QUERY_COUNT, 0)) AS QUERIES,
        SUM(COALESCE(TOTAL_QUEUED_MS, 0)) AS QUEUED_MS,
        SUM(COALESCE(TOTAL_SPILL_BYTES, 0)) AS SPILL_BYTES,
        MAX(COALESCE(P95_EXECUTION_MS, 0)) AS P95_EXECUTION_MS
    FROM {query_table}
    WHERE HOUR_START >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
    GROUP BY COALESCE(WAREHOUSE_NAME, 'Unknown')
),
warehouse_pressure_ranked AS (
    SELECT WAREHOUSE_NAME, QUERIES, QUEUED_MS, SPILL_BYTES, P95_EXECUTION_MS,
           ROW_NUMBER() OVER (
               ORDER BY QUEUED_MS DESC, SPILL_BYTES DESC, P95_EXECUTION_MS DESC, WAREHOUSE_NAME
           ) AS RN
    FROM warehouse_pressure
)
SELECT 'KPI' AS PANEL, 'Total Queries' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(SUM(QUERIES), 0)::FLOAT AS VALUE, NULL::FLOAT AS VALUE_USD, 'queries' AS UNIT, 4 AS SORT_ORDER
FROM query_daily
UNION ALL
SELECT 'KPI', 'Avg Runtime', 'Current window', NULL::TIMESTAMP_NTZ,
       COALESCE(SUM(ELAPSED_MS) / NULLIF(SUM(QUERIES), 0) / 1000, 0), NULL::FLOAT, 'seconds', 5
FROM query_daily
UNION ALL
SELECT 'KPI', 'P95 Runtime', 'Current window', NULL::TIMESTAMP_NTZ,
       COALESCE(MAX(P95_EXECUTION_MS) / 1000, 0), NULL::FLOAT, 'seconds', 6
FROM query_daily
UNION ALL
SELECT 'KPI', 'Queue Time', 'Current window', NULL::TIMESTAMP_NTZ,
       COALESCE(SUM(QUEUED_MS) / 1000, 0), NULL::FLOAT, 'seconds', 7
FROM query_daily
UNION ALL
SELECT 'KPI', 'Remote Spill', 'Current window', NULL::TIMESTAMP_NTZ,
       COALESCE(SUM(SPILL_BYTES) / POWER(1024, 3), 0), NULL::FLOAT, 'gb', 8
FROM query_daily
UNION ALL
SELECT 'KPI', 'Failed Queries', 'Current window', NULL::TIMESTAMP_NTZ,
       COALESCE(SUM(FAILED_QUERIES), 0), NULL::FLOAT, 'queries', 9
FROM query_daily
UNION ALL
SELECT 'DAILY_WORKLOAD', 'Avg Runtime', TO_VARCHAR(USAGE_DATE), TO_TIMESTAMP_NTZ(USAGE_DATE),
       COALESCE(ELAPSED_MS / NULLIF(QUERIES, 0) / 1000, 0), NULL::FLOAT, 'seconds', 301
FROM query_daily
UNION ALL
SELECT 'DAILY_WORKLOAD', 'P95 Runtime', TO_VARCHAR(USAGE_DATE), TO_TIMESTAMP_NTZ(USAGE_DATE),
       COALESCE(P95_EXECUTION_MS / 1000, 0), NULL::FLOAT, 'seconds', 302
FROM query_daily
UNION ALL
SELECT 'DAILY_WORKLOAD', 'Queue Seconds', TO_VARCHAR(USAGE_DATE), TO_TIMESTAMP_NTZ(USAGE_DATE),
       COALESCE(QUEUED_MS / 1000, 0), NULL::FLOAT, 'seconds', 303
FROM query_daily
UNION ALL
SELECT 'QUERY_TYPE', 'Queries by Type', QUERY_TYPE, NULL::TIMESTAMP_NTZ,
       QUERIES, NULL::FLOAT, 'queries', 401
FROM query_type_ranked
WHERE RN <= 8
UNION ALL
SELECT 'QUERY_DATABASE', 'Queries by Database', DATABASE_NAME, NULL::TIMESTAMP_NTZ,
       QUERIES, NULL::FLOAT, 'queries', 451
FROM query_database_ranked
WHERE RN <= 8
UNION ALL
SELECT 'WAREHOUSE_PRESSURE', 'Queue Seconds', WAREHOUSE_NAME, NULL::TIMESTAMP_NTZ,
       COALESCE(QUEUED_MS / 1000, 0), NULL::FLOAT, 'seconds', 501
FROM warehouse_pressure_ranked
WHERE RN <= 8
UNION ALL
SELECT 'WAREHOUSE_PRESSURE', 'Remote Spill GB', WAREHOUSE_NAME, NULL::TIMESTAMP_NTZ,
       COALESCE(SPILL_BYTES / POWER(1024, 3), 0), NULL::FLOAT, 'gb', 502
FROM warehouse_pressure_ranked
WHERE RN <= 8
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Query facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 902
FROM query_daily
"""

    execution_status_sql = f"""
WITH status_ranked AS (
    SELECT
        COALESCE(EXECUTION_STATUS, 'Unknown') AS EXECUTION_STATUS,
        COUNT(*) AS QUERIES,
        MAX(LOAD_TS) AS LOAD_TS,
        ROW_NUMBER() OVER (
            ORDER BY COUNT(*) DESC, COALESCE(EXECUTION_STATUS, 'Unknown')
        ) AS RN
    FROM {query_detail_table}
    WHERE START_TIME >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
    GROUP BY COALESCE(EXECUTION_STATUS, 'Unknown')
)
SELECT 'EXEC_STATUS' AS PANEL, 'Execution Status' AS METRIC, EXECUTION_STATUS AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       QUERIES::FLOAT AS VALUE, NULL::FLOAT AS VALUE_USD, 'queries' AS UNIT, 461 AS SORT_ORDER
FROM status_ranked
WHERE RN <= 8
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Query detail facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 908
FROM status_ranked
"""

    task_sql = f"""
WITH task_rollup AS (
    SELECT
        COUNT(*) AS TASK_RUNS,
        COUNT_IF(UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR')) AS FAILED_TASKS,
        MAX(LOAD_TS) AS LOAD_TS
    FROM {task_table}
    WHERE SCHEDULED_TIME >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
      {company_clause}
      {env_clause}
)
SELECT 'KPI' AS PANEL, 'Failed Tasks' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(MAX(FAILED_TASKS), 0)::FLOAT AS VALUE, NULL::FLOAT AS VALUE_USD, 'tasks' AS UNIT, 10 AS SORT_ORDER
FROM task_rollup
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Task facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 903
FROM task_rollup
"""

    storage_sql = f"""
WITH storage_rollup AS (
    SELECT
        SUM(COALESCE(EST_STORAGE_TB, 0)) AS STORAGE_TB,
        SUM(COALESCE(EST_COST_USD, 0)) AS STORAGE_COST_USD,
        MAX(LOAD_TS) AS LOAD_TS
    FROM {storage_table}
    WHERE SNAPSHOT_DATE >= DATEADD('DAY', -{days}, CURRENT_DATE())
      {company_clause}
      {env_clause}
)
SELECT 'KPI' AS PANEL, 'Storage' AS METRIC, 'Current snapshot' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(MAX(STORAGE_TB), 0)::FLOAT AS VALUE, COALESCE(MAX(STORAGE_COST_USD), 0)::FLOAT AS VALUE_USD, 'tb_usd' AS UNIT, 13 AS SORT_ORDER
FROM storage_rollup
UNION ALL
SELECT 'FRESHNESS', 'Latest Load', 'Storage facts', MAX(LOAD_TS), NULL::FLOAT, NULL::FLOAT, 'timestamp', 905
FROM storage_rollup
"""

    control_sql = f"""
WITH control_latest AS (
    SELECT *
    FROM {control_table}
    WHERE SNAPSHOT_TS >= DATEADD('HOUR', -24, CURRENT_TIMESTAMP())
      {company_clause}
    QUALIFY ROW_NUMBER() OVER (PARTITION BY COMPANY ORDER BY SNAPSHOT_TS DESC) = 1
)
SELECT 'KPI' AS PANEL, 'Platform Health' AS METRIC, 'Latest control room' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(MAX(HEALTH_SCORE), 0)::FLOAT AS VALUE, NULL::FLOAT AS VALUE_USD, 'score' AS UNIT, 14 AS SORT_ORDER
FROM control_latest
"""

    alert_sql = f"""
SELECT 'KPI' AS PANEL, 'Critical High Alerts' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(COUNT_IF(UPPER(COALESCE(SEVERITY, '')) IN ('CRITICAL', 'HIGH')
           AND UPPER(COALESCE(STATUS, 'NEW')) NOT IN ('RESOLVED', 'FIXED', 'IGNORED', 'CLOSED')), 0)::FLOAT AS VALUE,
       NULL::FLOAT AS VALUE_USD, 'alerts' AS UNIT, 11 AS SORT_ORDER
FROM {alert_table}
WHERE EVENT_TS >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
"""

    queue_sql = f"""
SELECT 'KPI' AS PANEL, 'Open Actions' AS METRIC, 'Current window' AS DIMENSION, NULL::TIMESTAMP_NTZ AS PERIOD_START,
       COALESCE(COUNT_IF(UPPER(COALESCE(STATUS, 'NEW')) NOT IN ('FIXED', 'IGNORED', 'CLOSED', 'RESOLVED')), 0)::FLOAT AS VALUE,
       NULL::FLOAT AS VALUE_USD, 'actions' AS UNIT, 12 AS SORT_ORDER
FROM {queue_table}
WHERE CREATED_AT >= DATEADD('DAY', -{days * 2}, CURRENT_TIMESTAMP())
  {company_clause}
"""

    return [
        ("cost", "Cost facts", cost_sql),
        ("cortex", "Cortex facts", cortex_sql),
        ("query", "Query performance facts", query_sql),
        ("query_detail", "Query detail facts", execution_status_sql),
        ("task", "Task facts", task_sql),
        ("storage", "Storage facts", storage_sql),
        ("control", "Platform health facts", control_sql),
        ("alert", "Alert events", alert_sql),
        ("queue", "Action queue", queue_sql),
    ]

def _load_executive_observability_from_parts(
    company: str,
    environment: str,
    days: int,
    *,
    credit_price: float,
    ai_credit_price: float,
    initial_statuses: list[dict] | None = None,
) -> bool:
    frames: list[pd.DataFrame] = []
    statuses = list(initial_statuses or [])
    for key, label, sql in _build_executive_observability_query_parts(
        company,
        environment,
        int(days),
        credit_price=credit_price,
        ai_credit_price=ai_credit_price,
    ):
        try:
            frame = run_query(
                sql,
                ttl_key=f"executive_observability_part_{key}_{company}_{environment}_{int(days)}",
                tier="recent",
                section="Executive Landing",
            )
            normalised = _normalise_observability_frame(frame)
            frames.append(normalised)
            statuses.append({
                "source": label,
                "state": "Loaded" if not normalised.empty else "No Rows",
                "detail": (
                    f"{len(normalised):,} summary row(s) loaded."
                    if not normalised.empty else "No rows for this scope."
                ),
            })
        except Exception as exc:
            statuses.append({
                "source": label,
                "state": "Unavailable",
                "detail": format_snowflake_error(exc),
            })
    frames.append(_observability_status_frame(statuses))
    board = pd.concat(frames, ignore_index=True) if frames else _observability_status_frame(statuses)
    return _store_observability_payload(
        board,
        company=company,
        environment=environment,
        days=int(days),
        source="Executive monitoring facts",
        error="" if any(status.get("state") == "Loaded" for status in statuses) else "No executive fact sources loaded.",
    )

def _load_executive_observability(
    company: str,
    environment: str,
    days: int,
    *,
    credit_price: float,
) -> bool:
    ai_credit_price = safe_float(st.session_state.get("ai_credit_price", DEFAULTS.get("ai_credit_price", 2.20)), 2.20)
    try:
        board = run_query(
            _build_executive_observability_sql(
                company,
                environment,
                int(days),
                credit_price=credit_price,
                ai_credit_price=ai_credit_price,
            ),
            ttl_key=f"executive_observability_{company}_{environment}_{int(days)}",
            tier="recent",
            section="Executive Landing",
        )
        normalised = _normalise_observability_frame(board)
        mart_status = {
            "source": "MART_EXECUTIVE_OBSERVABILITY",
            "state": "Loaded" if not normalised.empty else "No Rows",
            "detail": (
                f"{len(normalised):,} summary row(s) loaded from the executive observability mart."
                if not normalised.empty
                else "The executive observability mart returned no rows for this scope."
            ),
        }
        if not _obs_rows(normalised, "KPI").empty:
            return _store_observability_payload(
                pd.concat([normalised, _observability_status_frame([mart_status])], ignore_index=True),
                company=company,
                environment=environment,
                days=int(days),
                source="MART_EXECUTIVE_OBSERVABILITY",
                error="",
            )
        return _load_executive_observability_from_parts(
            company,
            environment,
            int(days),
            credit_price=credit_price,
            ai_credit_price=ai_credit_price,
            initial_statuses=[mart_status],
        )
    except Exception as exc:
        detail = format_snowflake_error(exc)
        return _load_executive_observability_from_parts(
            company,
            environment,
            int(days),
            credit_price=credit_price,
            ai_credit_price=ai_credit_price,
            initial_statuses=[{
                "source": "MART_EXECUTIVE_OBSERVABILITY",
                "state": "Unavailable",
                "detail": detail,
            }],
        )

def _current_observability_board(company: str, environment: str, days: int) -> tuple[pd.DataFrame, dict]:
    payload = st.session_state.get(OBSERVABILITY_STATE_KEY)
    if not isinstance(payload, dict):
        return pd.DataFrame(), {}
    if payload.get("scope") != _observability_scope(company, environment, int(days)):
        return pd.DataFrame(), {}
    data = payload.get("data")
    return (data if isinstance(data, pd.DataFrame) else pd.DataFrame()), payload

def _observability_payload_is_offline(payload: dict) -> bool:
    return isinstance(payload, dict) and payload.get("source") == OBSERVABILITY_OFFLINE_SOURCE

def _executive_observability_board_empty(board) -> bool:
    return not isinstance(board, pd.DataFrame) or board.empty

def _executive_observability_autoload_allowed() -> bool:
    """Executive first paint must not query Snowflake automatically."""
    return False

def _executive_observability_connection_unavailable() -> bool:
    return (
        st.session_state.get("_overwatch_connection_available") is not True
        or snowflake_connection_known_unavailable()
    )

def _load_executive_snapshot(company: str, environment: str, days: int) -> bool:
    session = get_session_for_action(
        "load Executive Landing snapshot",
        surface="Executive Landing",
        offline_note="Executive Landing shell remains available without Snowflake.",
    )
    if session is None:
        return False
    st.session_state.pop(PLATFORM_SUMMARY_STATE_KEY, None)
    snapshot = {"errors": []}
    try:
        snapshot["cost"] = run_query(
            build_mart_cost_cockpit_sql(company, int(days)),
            ttl_key=f"executive_cost_{company}_{days}",
            tier="historical",
            section="Executive Landing",
        )
    except Exception as exc:
        snapshot["cost"] = pd.DataFrame()
        snapshot["errors"].append(f"Cost summary unavailable: {format_snowflake_error(exc)}")
    try:
        snapshot["alerts"] = _load_alerts(session, company, environment, int(days))
    except Exception as exc:
        snapshot["alerts"] = pd.DataFrame()
        snapshot["errors"].append(f"Alert telemetry unavailable: {format_snowflake_error(exc)}")
    try:
        snapshot["queue"] = load_action_queue(session)
    except Exception as exc:
        snapshot["queue"] = pd.DataFrame()
        snapshot["errors"].append(f"Action queue unavailable: {format_snowflake_error(exc)}")
    try:
        snapshot["migration"] = run_query(
            build_schema_migration_status_sql(),
            ttl_key="executive_migration_status",
            tier="recent",
            section="Executive Landing",
        )
    except Exception as exc:
        snapshot["migration"] = pd.DataFrame()
        snapshot["errors"].append(f"Migration ledger unavailable: {format_snowflake_error(exc)}")
    snapshot["meta"] = {"company": company, "environment": environment, "days": int(days)}
    st.session_state["executive_landing_snapshot"] = snapshot
    st.session_state["_executive_landing_auto_load_scope"] = _executive_snapshot_scope(company, environment, days)
    return True


__all__ = ['_load_alerts', '_company_filter_sql', '_environment_filter_sql', '_build_executive_observability_sql', '_observability_scope', '_normalise_observability_frame', '_sort_observability_frame', '_observability_status_frame', '_store_observability_payload', '_store_connection_unavailable_observability', '_build_executive_observability_query_parts', '_load_executive_observability_from_parts', '_load_executive_observability', '_current_observability_board', '_observability_payload_is_offline', '_executive_observability_board_empty', '_executive_observability_autoload_allowed', '_executive_observability_connection_unavailable', '_load_executive_snapshot']
