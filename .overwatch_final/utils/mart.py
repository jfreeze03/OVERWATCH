"""Helpers for reading the optional OVERWATCH Snowflake mart.

The app must keep working before the mart setup SQL is installed, so these
helpers always fail closed: callers get an empty frame plus a short reason and
can fall back to the existing live ACCOUNT_USAGE queries.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import ETL_AUDIT_DB, ETL_AUDIT_SCHEMA, ENVIRONMENT_CONFIG, DEFAULT_ENVIRONMENT
from .data import normalize_df
from .query import safe_identifier, sql_literal
from .session import get_session


@dataclass(frozen=True)
class MartResult:
    data: pd.DataFrame
    available: bool
    source: str
    message: str = ""


def mart_object_name(table_name: str) -> str:
    """Return a safe fully qualified mart table name."""
    table = safe_identifier(table_name)
    db = safe_identifier(ETL_AUDIT_DB)
    schema = safe_identifier(ETL_AUDIT_SCHEMA)
    return f"{db}.{schema}.{table}"


def load_mart_table(
    table_name: str,
    sql: str,
    source_label: str | None = None,
) -> MartResult:
    """Run a mart query and return a fallback-friendly result object."""
    source = source_label or mart_object_name(table_name)
    try:
        df = normalize_df(get_session().sql(sql).to_pandas())
        return MartResult(data=df, available=True, source=source)
    except Exception as exc:
        return MartResult(data=pd.DataFrame(), available=False, source=source, message=str(exc))


def load_latest_control_room_mart(company: str = "ALFA", max_age_hours: int = 6) -> MartResult:
    """Load the latest DBA Control Room mart row for the active company."""
    table = mart_object_name("MART_DBA_CONTROL_ROOM")
    company = str(company or "ALFA")
    company_filter = ""
    if company.upper() != "ALL":
        company_filter = f"AND COMPANY = {sql_literal(company, 100)}"
    sql = f"""
        WITH latest AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY COMPANY
                       ORDER BY SNAPSHOT_TS DESC
                   ) AS RN
            FROM {table}
            WHERE SNAPSHOT_TS >= DATEADD('HOUR', -{int(max_age_hours)}, CURRENT_TIMESTAMP())
              {company_filter}
        )
        SELECT
            SNAPSHOT_TS,
            COMPANY,
            HEALTH_SCORE,
            FAILED_QUERIES_24H,
            FAILED_TASKS_24H,
            QUEUED_MS_24H,
            CREDITS_24H,
            COST_24H_USD,
            CORTEX_COST_7D_USD,
            SECURITY_EVENTS_24H,
            OBJECT_CHANGES_24H,
            TOP_RISK,
            LOAD_TS
        FROM latest
        WHERE RN = 1
        ORDER BY COMPANY
    """
    return load_mart_table("MART_DBA_CONTROL_ROOM", sql, source_label=table)


def build_mart_control_room_summary_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build DBA Control Room summary metrics from recent query-detail facts."""
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            COUNT(*) AS total_queries,
            SUM(CASE WHEN q.error_code IS NOT NULL
                       OR UPPER(COALESCE(q.execution_status, '')) = 'FAILED_WITH_ERROR'
                     THEN 1 ELSE 0 END) AS failed_queries,
            SUM(CASE WHEN COALESCE(q.queued_overload_time, 0)
                        + COALESCE(q.queued_provisioning_time, 0)
                        + COALESCE(q.queued_repair_time, 0) > 0
                     THEN 1 ELSE 0 END) AS queued_queries,
            SUM(CASE WHEN COALESCE(q.bytes_spilled_to_remote_storage, 0) > 0
                     THEN 1 ELSE 0 END) AS remote_spill_queries,
            ROUND(AVG(COALESCE(q.total_elapsed_time, 0)) / 1000, 2) AS avg_elapsed_sec,
            ROUND(APPROX_PERCENTILE(COALESCE(q.total_elapsed_time, 0) / 1000, 0.95), 2) AS p95_elapsed_sec,
            COUNT(DISTINCT q.warehouse_name) AS active_warehouses,
            COUNT(DISTINCT q.user_name) AS active_users
        FROM {table} q
        WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
    """


def build_mart_control_room_credits_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build period/prior credit totals from hourly warehouse facts."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    return f"""
        SELECT
            SUM(CASE WHEN hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
                     THEN COALESCE(credits_used, 0) ELSE 0 END) AS period_credits,
            SUM(CASE WHEN hour_start >= DATEADD('HOUR', -{int(hours_back * 2)}, CURRENT_TIMESTAMP())
                      AND hour_start < DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
                     THEN COALESCE(credits_used, 0) ELSE 0 END) AS prior_credits
        FROM {table}
        WHERE hour_start >= DATEADD('HOUR', -{int(hours_back * 2)}, CURRENT_TIMESTAMP())
          {company_filter}
    """


def build_mart_control_room_cost_drivers_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build top DBA Control Room cost drivers from mart facts.

    Warehouse credits are exact at the warehouse/hour level, then allocated to
    users by elapsed-time share inside each warehouse for the selected window.
    """
    q_table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    wh_table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter_q = _mart_company_filter(company).replace("COMPANY", "q.company")
    company_filter_wh = _mart_company_filter(company).replace("COMPANY", "w.company")
    env_filter_q = _mart_environment_filter("q.database_name", company)
    return f"""
        WITH wh_credits AS (
            SELECT warehouse_name, SUM(COALESCE(credits_used, 0)) AS warehouse_credits
            FROM {wh_table} w
            WHERE w.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
              {company_filter_wh}
            GROUP BY warehouse_name
        ),
        wh_elapsed AS (
            SELECT
                q.warehouse_name,
                SUM(COALESCE(q.total_elapsed_time, 0)) AS wh_elapsed_ms
            FROM {q_table} q
            WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {company_filter_q}
            GROUP BY q.warehouse_name
        ),
        query_work AS (
            SELECT
                q.user_name,
                q.warehouse_name,
                COUNT(*) AS query_count,
                SUM(COALESCE(q.total_elapsed_time, 0)) AS elapsed_ms,
                SUM(COALESCE(q.bytes_scanned, 0)) AS bytes_scanned,
                AVG(COALESCE(q.total_elapsed_time, 0)) AS avg_elapsed_ms
            FROM {q_table} q
            WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {company_filter_q}
              {env_filter_q}
            GROUP BY q.user_name, q.warehouse_name
        )
        SELECT
            qw.user_name,
            qw.warehouse_name,
            qw.query_count,
            ROUND(COALESCE(wc.warehouse_credits, 0) * qw.elapsed_ms / NULLIF(we.wh_elapsed_ms, 0), 4) AS allocated_credits,
            ROUND(qw.bytes_scanned / POWER(1024, 3), 2) AS gb_scanned,
            ROUND(qw.avg_elapsed_ms / 1000, 2) AS avg_elapsed_sec
        FROM query_work qw
        LEFT JOIN wh_credits wc ON qw.warehouse_name = wc.warehouse_name
        LEFT JOIN wh_elapsed we ON qw.warehouse_name = we.warehouse_name
        WHERE COALESCE(wc.warehouse_credits, 0) > 0
        ORDER BY allocated_credits DESC, gb_scanned DESC
        LIMIT 10
    """


def build_mart_control_room_warehouse_pressure_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build warehouse pressure exceptions from query-detail facts."""
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            q.warehouse_name,
            MAX(q.warehouse_size) AS warehouse_size,
            COUNT(*) AS total_queries,
            SUM(CASE WHEN COALESCE(q.queued_overload_time, 0)
                        + COALESCE(q.queued_provisioning_time, 0)
                        + COALESCE(q.queued_repair_time, 0) > 0
                     THEN 1 ELSE 0 END) AS queued_queries,
            SUM(CASE WHEN COALESCE(q.bytes_spilled_to_remote_storage, 0) > 0
                     THEN 1 ELSE 0 END) AS remote_spill_queries,
            ROUND(SUM(COALESCE(q.bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2) AS remote_spill_gb,
            ROUND(APPROX_PERCENTILE(COALESCE(q.total_elapsed_time, 0) / 1000, 0.95), 2) AS p95_elapsed_sec
        FROM {table} q
        WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY q.warehouse_name
        HAVING queued_queries > 0 OR remote_spill_queries > 0 OR p95_elapsed_sec >= 60
        ORDER BY queued_queries DESC, remote_spill_gb DESC, p95_elapsed_sec DESC
        LIMIT 10
    """


def build_mart_control_room_failed_queries_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build recent failed query samples from query-detail facts."""
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            q.query_id,
            q.user_name,
            q.role_name,
            q.warehouse_name,
            q.database_name,
            q.query_type,
            q.error_code,
            LEFT(q.error_message, 240) AS error_message,
            q.start_time
        FROM {table} q
        WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND (q.error_code IS NOT NULL OR UPPER(COALESCE(q.execution_status, '')) = 'FAILED_WITH_ERROR')
          {company_filter}
          {env_filter}
        ORDER BY q.start_time DESC
        LIMIT 25
    """


def build_mart_control_room_object_changes_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build object/access change samples from object-change facts."""
    table = mart_object_name("FACT_OBJECT_CHANGE")
    company_filter = _mart_company_filter(company).replace("COMPANY", "c.company")
    env_filter = _mart_environment_filter("c.database_name", company)
    return f"""
        SELECT
            c.start_time,
            c.user_name,
            c.role_name,
            c.query_type,
            c.database_name,
            c.schema_name,
            NULL::VARCHAR AS warehouse_name,
            LEFT(c.query_text, 220) AS query_preview
        FROM {table} c
        WHERE c.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          {company_filter}
          {env_filter}
        ORDER BY c.start_time DESC
        LIMIT 25
    """


def build_mart_control_room_failed_logins_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build failed-login samples from daily login facts."""
    table = mart_object_name("FACT_LOGIN_DAILY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "l.company")
    days_back = max(1, int((int(hours_back) + 23) / 24))
    return f"""
        SELECT
            l.login_date AS event_timestamp,
            l.user_name,
            l.client_ip,
            l.reported_client_type,
            NULL::VARCHAR AS error_code,
            'Aggregated failed login count: ' || SUM(COALESCE(l.failure_count, 0)) AS error_message
        FROM {table} l
        WHERE l.login_date >= DATEADD('DAY', -{days_back}, CURRENT_DATE())
          AND COALESCE(l.failure_count, 0) > 0
          {company_filter}
        GROUP BY l.login_date, l.user_name, l.client_ip, l.reported_client_type
        ORDER BY l.login_date DESC, SUM(COALESCE(l.failure_count, 0)) DESC
        LIMIT 25
    """


def build_mart_control_room_task_failures_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build task failure summary from task-run facts."""
    table = mart_object_name("FACT_TASK_RUN")
    company_filter = _mart_company_filter(company).replace("COMPANY", "t.company")
    env_filter = _mart_environment_filter("t.database_name", company)
    return f"""
        SELECT
            t.task_name,
            t.database_name,
            t.schema_name,
            t.root_task_name,
            COUNT(*) AS failures,
            MAX(t.scheduled_time) AS last_failure,
            MAX(t.error_message) AS last_error
        FROM {table} t
        WHERE t.scheduled_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND UPPER(COALESCE(t.state, '')) IN ('FAILED', 'FAILED_WITH_ERROR')
          {company_filter}
          {env_filter}
        GROUP BY t.task_name, t.database_name, t.schema_name, t.root_task_name
        ORDER BY failures DESC, last_failure DESC
        LIMIT 10
    """


def build_mart_account_health_storage_sql(company: str = "ALFA") -> str:
    """Build Account Health latest storage KPI from daily storage facts."""
    table = mart_object_name("FACT_STORAGE_DAILY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "s.company")
    latest_filter = _mart_company_filter(company).replace("COMPANY", "company")
    latest_env_filter = _mart_environment_filter("database_name", company)
    env_filter = _mart_environment_filter("s.database_name", company)
    return f"""
        WITH latest AS (
            SELECT MAX(snapshot_date) AS snapshot_date
            FROM {table}
            WHERE 1 = 1
              {latest_filter}
              {latest_env_filter}
        )
        SELECT
            COALESCE(ROUND(SUM(COALESCE(s.est_storage_tb, 0)), 2), 0) AS storage_tb
        FROM {table} s
        JOIN latest l ON s.snapshot_date = l.snapshot_date
        WHERE 1 = 1
          {company_filter}
          {env_filter}
    """


def build_mart_account_health_cost_drivers_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build Account Health top cost drivers from mart facts.

    This returns the legacy Account Health column names so the UI can remain
    stable while the source moves from live ACCOUNT_USAGE to preloaded facts.
    """
    q_table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    wh_table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter_q = _mart_company_filter(company).replace("COMPANY", "q.company")
    company_filter_wh = _mart_company_filter(company).replace("COMPANY", "w.company")
    env_filter_q = _mart_environment_filter("q.database_name", company)
    return f"""
        WITH wh_credits AS (
            SELECT
                warehouse_name,
                SUM(COALESCE(credits_used, 0)) AS warehouse_credits
            FROM {wh_table} w
            WHERE w.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
              {company_filter_wh}
            GROUP BY warehouse_name
        ),
        wh_elapsed AS (
            SELECT
                q.warehouse_name,
                SUM(COALESCE(q.total_elapsed_time, 0)) AS wh_elapsed_ms
            FROM {q_table} q
            WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {company_filter_q}
            GROUP BY q.warehouse_name
        ),
        query_work AS (
            SELECT
                q.user_name,
                q.warehouse_name,
                MAX(q.warehouse_size) AS warehouse_size,
                COUNT(*) AS query_count,
                SUM(COALESCE(q.total_elapsed_time, 0)) AS elapsed_ms,
                SUM(COALESCE(q.bytes_scanned, 0)) AS bytes_scanned
            FROM {q_table} q
            WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {company_filter_q}
              {env_filter_q}
            GROUP BY q.user_name, q.warehouse_name
        )
        SELECT
            qw.user_name,
            qw.warehouse_name,
            qw.warehouse_size,
            qw.query_count,
            ROUND(COALESCE(wc.warehouse_credits, 0) * qw.elapsed_ms / NULLIF(we.wh_elapsed_ms, 0), 4) AS total_credits,
            ROUND(qw.bytes_scanned / POWER(1024, 3), 2) AS gb_scanned
        FROM query_work qw
        LEFT JOIN wh_credits wc ON qw.warehouse_name = wc.warehouse_name
        LEFT JOIN wh_elapsed we ON qw.warehouse_name = we.warehouse_name
        WHERE COALESCE(wc.warehouse_credits, 0) > 0
        ORDER BY total_credits DESC, gb_scanned DESC
        LIMIT 5
    """


def build_mart_account_health_change_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build Account Health what-changed deltas from hourly query and warehouse facts."""
    query_table = mart_object_name("FACT_QUERY_HOURLY")
    warehouse_table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter_q = _mart_company_filter(company).replace("COMPANY", "q.company")
    company_filter_w = _mart_company_filter(company).replace("COMPANY", "w.company")
    env_filter_q = _mart_environment_filter("q.database_name", company)
    return f"""
        WITH query_periods AS (
            SELECT
                CASE
                    WHEN q.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP()) THEN 'CURRENT'
                    ELSE 'PRIOR'
                END AS period,
                SUM(COALESCE(q.query_count, 0)) AS queries,
                SUM(COALESCE(q.failed_count, 0)) AS failures
            FROM {query_table} q
            WHERE q.hour_start >= DATEADD('HOUR', -{int(hours_back * 2)}, CURRENT_TIMESTAMP())
              AND q.hour_start < CURRENT_TIMESTAMP()
              {company_filter_q}
              {env_filter_q}
            GROUP BY period
        ),
        credit_periods AS (
            SELECT
                CASE
                    WHEN w.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP()) THEN 'CURRENT'
                    ELSE 'PRIOR'
                END AS period,
                SUM(COALESCE(w.credits_used, 0)) AS credits
            FROM {warehouse_table} w
            WHERE w.hour_start >= DATEADD('HOUR', -{int(hours_back * 2)}, CURRENT_TIMESTAMP())
              AND w.hour_start < CURRENT_TIMESTAMP()
              {company_filter_w}
            GROUP BY period
        )
        SELECT
            COALESCE(MAX(IFF(q.period = 'CURRENT', q.queries, NULL)), 0)
              - COALESCE(MAX(IFF(q.period = 'PRIOR', q.queries, NULL)), 0) AS query_delta,
            ROUND(
                COALESCE(MAX(IFF(c.period = 'CURRENT', c.credits, NULL)), 0)
                - COALESCE(MAX(IFF(c.period = 'PRIOR', c.credits, NULL)), 0),
                4
            ) AS credit_delta,
            COALESCE(MAX(IFF(q.period = 'CURRENT', q.failures, NULL)), 0)
              - COALESCE(MAX(IFF(q.period = 'PRIOR', q.failures, NULL)), 0) AS failure_delta
        FROM query_periods q
        FULL OUTER JOIN credit_periods c ON q.period = c.period
    """


def build_mart_account_health_failure_types_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build Morning Report failure groups from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            q.query_type,
            SUM(COALESCE(q.failed_count, 0)) AS fail_count,
            COUNT(DISTINCT IFF(COALESCE(q.failed_count, 0) > 0, q.user_name, NULL)) AS affected_users,
            COUNT(DISTINCT IFF(COALESCE(q.failed_count, 0) > 0, q.warehouse_name, NULL)) AS affected_wh
        FROM {table} q
        WHERE q.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND COALESCE(q.failed_count, 0) > 0
          {company_filter}
          {env_filter}
        GROUP BY q.query_type
        ORDER BY fail_count DESC
    """


def build_mart_account_health_long_queries_sql(hours_back: int, company: str = "ALFA", limit: int = 10) -> str:
    """Build Morning Report long-query watchlist from recent query details."""
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            q.query_id,
            q.user_name,
            q.warehouse_name,
            SUBSTR(COALESCE(q.query_text, ''), 1, 100) AS query_preview,
            COALESCE(q.total_elapsed_time, 0) / 1000 AS elapsed_sec,
            q.execution_status
        FROM {table} q
        WHERE q.start_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        ORDER BY COALESCE(q.total_elapsed_time, 0) DESC
        LIMIT {int(limit)}
    """


def build_mart_account_health_credits_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build period/prior-period credit totals for Account Health briefings."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "w.company")
    return f"""
        SELECT
            SUM(CASE WHEN w.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
                      AND w.hour_start < CURRENT_TIMESTAMP()
                     THEN COALESCE(w.credits_used, 0) ELSE 0 END) AS period_credits,
            SUM(CASE WHEN w.hour_start >= DATEADD('HOUR', -{int(hours_back * 2)}, CURRENT_TIMESTAMP())
                      AND w.hour_start < DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
                     THEN COALESCE(w.credits_used, 0) ELSE 0 END) AS prior_period_credits,
            SUM(CASE WHEN w.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
                      AND w.hour_start < CURRENT_TIMESTAMP()
                     THEN COALESCE(w.credits_used, 0) ELSE 0 END) AS overnight_credits
        FROM {table} w
        WHERE w.hour_start >= DATEADD('HOUR', -{int(hours_back * 2)}, CURRENT_TIMESTAMP())
          AND w.hour_start < CURRENT_TIMESTAMP()
          {company_filter}
    """


def build_mart_account_health_failure_count_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build query failure count for Account Health briefings."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            COALESCE(SUM(q.failed_count), 0) AS fail_count
        FROM {table} q
        WHERE q.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          {company_filter}
          {env_filter}
    """


def build_mart_account_health_top_driver_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build top cost driver for Account Health executive briefing."""
    base_sql = build_mart_account_health_cost_drivers_sql(hours_back, company)
    return f"""
        WITH drivers AS (
            {base_sql}
        )
        SELECT
            user_name,
            warehouse_name,
            total_credits AS credits
        FROM drivers
        ORDER BY credits DESC
        LIMIT 1
    """


def build_mart_account_health_queued_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build queued query count for Account Health briefing inputs."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            COALESCE(SUM(IFF(COALESCE(q.total_queued_ms, 0) > 0, q.query_count, 0)), 0) AS queued
        FROM {table} q
        WHERE q.hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          {company_filter}
          {env_filter}
    """


def build_mart_account_health_ytd_credits_sql(company: str = "ALFA") -> str:
    """Build YTD credits from warehouse hourly mart for contract pacing."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company).replace("COMPANY", "w.company")
    return f"""
        SELECT
            COALESCE(SUM(w.credits_used), 0) AS ytd_credits
        FROM {table} w
        WHERE w.hour_start >= DATE_TRUNC('YEAR', CURRENT_DATE())
          AND w.hour_start < DATEADD('HOUR', -24, CURRENT_TIMESTAMP())
          {company_filter}
    """


def build_mart_bill_summary_sql(
    current_start: str,
    current_end: str,
    prior_start: str,
    prior_end: str,
    company: str = "ALFA",
    warehouse_contains: str = "",
) -> str:
    """Build a bill-summary query from hourly warehouse mart facts."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND COMPANY = {sql_literal(company, 100)}"
    warehouse_filter = (
        f"AND WAREHOUSE_NAME ILIKE '%' || {sql_literal(warehouse_contains, 300)} || '%'"
        if str(warehouse_contains or "").strip()
        else ""
    )
    return f"""
        WITH bounds AS (
            SELECT
                {current_start} AS current_start,
                {current_end} AS current_end,
                {prior_start} AS prior_start,
                {prior_end} AS prior_end
        ),
        metering AS (
            SELECT 'CURRENT' AS period, warehouse_name, hour_start, credits_used
            FROM {table}, bounds
            WHERE hour_start >= current_start
              AND hour_start < current_end
              {company_filter}
              {warehouse_filter}
            UNION ALL
            SELECT 'PRIOR' AS period, warehouse_name, hour_start, credits_used
            FROM {table}, bounds
            WHERE hour_start >= prior_start
              AND hour_start < prior_end
              {company_filter}
              {warehouse_filter}
        )
        SELECT
            period,
            ROUND(SUM(credits_used), 4) AS credits,
            COUNT(DISTINCT warehouse_name) AS active_warehouses,
            COUNT(DISTINCT TO_DATE(hour_start)) AS active_days
        FROM metering
        GROUP BY period
    """


def build_mart_bill_warehouse_delta_sql(
    current_start: str,
    current_end: str,
    prior_start: str,
    prior_end: str,
    company: str = "ALFA",
    warehouse_contains: str = "",
) -> str:
    """Build warehouse-period delta query from hourly warehouse mart facts."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND COMPANY = {sql_literal(company, 100)}"
    warehouse_filter = (
        f"AND WAREHOUSE_NAME ILIKE '%' || {sql_literal(warehouse_contains, 300)} || '%'"
        if str(warehouse_contains or "").strip()
        else ""
    )
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
            FROM {table}, bounds
            WHERE hour_start >= current_start
              AND hour_start < current_end
              {company_filter}
              {warehouse_filter}
            GROUP BY warehouse_name
        ),
        prior_wh AS (
            SELECT warehouse_name, SUM(credits_used) AS credits
            FROM {table}, bounds
            WHERE hour_start >= prior_start
              AND hour_start < prior_end
              {company_filter}
              {warehouse_filter}
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


def build_mart_chargeback_sql(
    days_back: int = 30,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
) -> str:
    """Build chargeback detail from the daily chargeback snapshot mart."""
    table = mart_object_name("FACT_CHARGEBACK_DAILY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("ENVIRONMENT", company)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_text_filter("DATABASE_NAME", database_contains)
    return f"""
        SELECT
            COMPANY,
            ENVIRONMENT,
            ENVIRONMENT_ROLLUP,
            DATABASE_NAME,
            USER_NAME,
            ROLE_NAME,
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE,
            SUM(QUERY_COUNT) AS QUERY_COUNT,
            ROUND(SUM(ALLOCATED_CREDITS), 4) AS TOTAL_CREDITS,
            ROUND(SUM(EST_COST_USD), 2) AS EST_COST,
            ALLOCATION_CONFIDENCE,
            ALLOCATION_BASIS,
            CHARGEBACK_READY,
            SCOPE_REVIEW,
            COST_OWNER,
            OWNER_SOURCE,
            OWNER_EVIDENCE,
            MAX(LOAD_TS) AS MART_LOAD_TS
        FROM {table}
        WHERE USAGE_DATE >= DATEADD('DAY', -{int(days_back)}, CURRENT_DATE())
          {company_filter}
          {env_filter}
          {wh_filter}
          {user_filter}
          {role_filter}
          {db_filter}
        GROUP BY
            COMPANY,
            ENVIRONMENT,
            ENVIRONMENT_ROLLUP,
            DATABASE_NAME,
            USER_NAME,
            ROLE_NAME,
            WAREHOUSE_NAME,
            WAREHOUSE_SIZE,
            ALLOCATION_CONFIDENCE,
            ALLOCATION_BASIS,
            CHARGEBACK_READY,
            SCOPE_REVIEW,
            COST_OWNER,
            OWNER_SOURCE,
            OWNER_EVIDENCE
        ORDER BY TOTAL_CREDITS DESC, QUERY_COUNT DESC
    """


def build_mart_cost_cockpit_sql(company: str = "ALFA", days: int = 7) -> str:
    """Build the Cost & Contract landing cockpit from hourly warehouse facts."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    days = int(days)
    return f"""
        WITH current_period AS (
            SELECT
                warehouse_name,
                SUM(COALESCE(credits_used, 0)) AS credits
            FROM {table}
            WHERE hour_start >= DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
              AND hour_start < CURRENT_TIMESTAMP()
              {company_filter}
            GROUP BY warehouse_name
        ),
        prior_period AS (
            SELECT
                warehouse_name,
                SUM(COALESCE(credits_used, 0)) AS credits
            FROM {table}
            WHERE hour_start >= DATEADD('DAY', -{days * 2}, CURRENT_TIMESTAMP())
              AND hour_start < DATEADD('DAY', -{days}, CURRENT_TIMESTAMP())
              {company_filter}
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


def _mart_text_filter(column: str, value: str = "") -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    return f"AND {column} ILIKE '%' || {sql_literal(value, 300)} || '%'"


def _mart_company_filter(company: str = "ALFA") -> str:
    if str(company or "").upper() == "ALL":
        return ""
    return f"AND COMPANY = {sql_literal(company, 100)}"


def _active_environment() -> str:
    try:
        import streamlit as st

        env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    except Exception:
        env = DEFAULT_ENVIRONMENT
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _mart_environment_column(column: str = "ENVIRONMENT") -> str:
    """Return the environment column matching a mart database column or alias."""
    raw = str(column or "ENVIRONMENT").strip()
    if not raw:
        return "ENVIRONMENT"
    parts = raw.split(".")
    leaf = parts[-1].strip('"').upper()
    if leaf in {"DATABASE_NAME", "PROCEDURE_CATALOG", "TABLE_CATALOG", "TABLE_CATALOG_NAME"}:
        return ".".join(parts[:-1] + ["environment"]) if len(parts) > 1 else "ENVIRONMENT"
    return raw


def _mart_environment_filter(column: str = "ENVIRONMENT", company: str = "ALFA") -> str:
    if str(company or "").upper() == "TREXIS":
        return ""
    environment = _active_environment()
    if environment.upper() == "ALL":
        return ""
    env_col = _mart_environment_column(column)
    if environment == "DEV_ALL":
        values = ENVIRONMENT_CONFIG.get(environment, {}).get("db_patterns", [])
    else:
        cfg = ENVIRONMENT_CONFIG.get(environment, ENVIRONMENT_CONFIG[DEFAULT_ENVIRONMENT])
        values = [environment] if environment == "PROD" else cfg.get("db_patterns", [])
    if not values:
        return ""
    parts = [f"{env_col} = {sql_literal(value, 300)}" for value in values]
    return "AND (" + " OR ".join(parts) + ")"


def _mart_database_filter(column: str = "DATABASE_NAME", value: str = "", company: str = "ALFA") -> str:
    return " ".join(
        filter(
            None,
            [
                _mart_text_filter(column, value),
                _mart_environment_filter(column, company),
            ],
        )
    )


def _mart_window_filter(column: str, days_back: int, start_date: object = None, end_date: object = None) -> str:
    clauses = [f"{column} >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())"]
    if start_date:
        clauses.append(f"{column} >= TO_TIMESTAMP_NTZ({sql_literal(str(start_date) + ' 00:00:00', 40)})")
    if end_date:
        clauses.append(
            f"{column} < DATEADD('DAY', 1, TO_TIMESTAMP_NTZ({sql_literal(str(end_date) + ' 00:00:00', 40)}))"
        )
    return "AND " + " AND ".join(clauses)


def build_mart_warehouse_overview_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build a warehouse health overview from hourly mart facts.

    The mart does not store query cache percentage, so callers should label
    cache as unavailable/estimated instead of an exact live fact.
    """
    query_table = mart_object_name("FACT_QUERY_HOURLY")
    warehouse_table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    query_window = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        WITH query_rollup AS (
            SELECT
                warehouse_name,
                MAX(warehouse_size) AS warehouse_size,
                SUM(query_count) AS total_queries,
                ROUND(SUM(total_elapsed_ms) / NULLIF(SUM(query_count), 0) / 1000, 3) AS avg_elapsed_sec,
                ROUND(MAX(p95_execution_ms) / 1000, 3) AS p95_elapsed_sec,
                ROUND(SUM(total_queued_ms) / NULLIF(SUM(query_count), 0) / 1000, 3) AS avg_queued_sec,
                ROUND(SUM(total_spill_bytes) / POWER(1024, 3), 3) AS total_remote_spill_gb,
                NULL::FLOAT AS avg_cache_pct,
                SUM(failed_count) AS error_count,
                ROUND(SUM(total_bytes_scanned) / POWER(1024, 3), 3) AS total_gb_scanned
            FROM {query_table}
            WHERE warehouse_name IS NOT NULL
              {company_filter}
              {query_window}
              {wh_filter}
              {user_filter}
              {role_filter}
              {db_filter}
            GROUP BY warehouse_name
        ),
        credit_rollup AS (
            SELECT
                warehouse_name,
                ROUND(SUM(COALESCE(credits_used, 0)), 4) AS metered_credits,
                ROUND(SUM(COALESCE(credits_used_compute, 0)), 4) AS credits_used_compute,
                ROUND(SUM(COALESCE(credits_used_cloud_services, 0)), 4) AS credits_used_cloud_services,
                MAX(load_ts) AS mart_load_ts
            FROM {warehouse_table}
            WHERE warehouse_name IS NOT NULL
              {company_filter}
              {query_window}
              {wh_filter}
            GROUP BY warehouse_name
        )
        SELECT
            q.warehouse_name,
            q.warehouse_size,
            q.total_queries,
            q.avg_elapsed_sec,
            q.p95_elapsed_sec,
            q.avg_queued_sec,
            q.total_remote_spill_gb,
            q.avg_cache_pct,
            q.error_count,
            q.total_gb_scanned,
            COALESCE(c.metered_credits, 0) AS metered_credits,
            COALESCE(c.credits_used_compute, 0) AS credits_used_compute,
            COALESCE(c.credits_used_cloud_services, 0) AS credits_used_cloud_services,
            c.mart_load_ts
        FROM query_rollup q
        LEFT JOIN credit_rollup c ON q.warehouse_name = c.warehouse_name
        ORDER BY q.total_queries DESC, COALESCE(c.metered_credits, 0) DESC
    """


def build_mart_warehouse_scaling_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build a lightweight scaling/metering event list from the warehouse mart."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    return f"""
        SELECT
            warehouse_name,
            NULL::VARCHAR AS warehouse_size,
            hour_start AS start_time,
            DATEADD('HOUR', 1, hour_start) AS end_time,
            credits_used,
            credits_used_compute,
            credits_used_cloud_services,
            load_ts AS mart_load_ts
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          {company_filter}
          {window_filter}
          {wh_filter}
        ORDER BY credits_used DESC, start_time DESC
        LIMIT 200
    """


def build_mart_usage_overview_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build top-level Usage Overview KPI SQL from the hourly query mart."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        SELECT
            COALESCE(SUM(query_count), 0) AS total_queries,
            COUNT(DISTINCT user_name) AS total_users,
            COUNT(DISTINCT database_name) AS active_databases,
            ROUND(
                100 * (COALESCE(SUM(query_count), 0) - COALESCE(SUM(failed_count), 0))
                / NULLIF(COALESCE(SUM(query_count), 0), 0),
                1
            ) AS query_success_rate,
            COALESCE(SUM(failed_count), 0) AS failed_queries,
            COALESCE(SUM(IFF(total_queued_ms > 0, query_count, 0)), 0) AS queued_queries,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec,
            ROUND(
                COALESCE(SUM(avg_execution_ms * query_count), 0)
                / NULLIF(COALESCE(SUM(query_count), 0), 0)
                / 1000,
                2
            ) AS avg_execution_sec,
            0::FLOAT AS cloud_service_credits
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          {company_filter}
          {window_filter}
          {wh_filter}
          {user_filter}
          {role_filter}
          {db_filter}
    """


def build_mart_usage_metering_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build Usage Overview credit KPI SQL from the hourly warehouse mart."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    current_window = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    prior_start = f"DATEADD('DAY', -{int(days_back) * 2}, CURRENT_TIMESTAMP())"
    prior_end = f"DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())"
    return f"""
        SELECT
            ROUND(SUM(IFF({current_window.replace('AND ', '', 1)}, COALESCE(credits_used, 0), 0)), 4) AS total_credits,
            ROUND(SUM(IFF(HOUR_START >= {prior_start} AND HOUR_START < {prior_end}, COALESCE(credits_used, 0), 0)), 4) AS prior_credits,
            ROUND(SUM(IFF({current_window.replace('AND ', '', 1)}, COALESCE(credits_used_compute, 0), 0)), 4) AS compute_credits,
            ROUND(SUM(IFF({current_window.replace('AND ', '', 1)}, COALESCE(credits_used_cloud_services, 0), 0)), 4) AS warehouse_cloud_credits
        FROM {table}
        WHERE HOUR_START >= {prior_start}
          {company_filter}
          {wh_filter}
    """


def build_mart_usage_pressure_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build Usage Overview warehouse pressure SQL from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        WITH wh AS (
            SELECT
                warehouse_name,
                SUM(query_count) AS total_queries,
                SUM(failed_count) AS failed_queries,
                SUM(total_queued_ms) AS queued_ms,
                SUM(total_spill_bytes) / POWER(1024, 3) AS remote_spill_gb
            FROM {table}
            WHERE warehouse_name IS NOT NULL
              {company_filter}
              {window_filter}
              {wh_filter}
              {user_filter}
              {role_filter}
              {db_filter}
            GROUP BY warehouse_name
        )
        SELECT
            COUNT(*) AS active_warehouses,
            SUM(IFF(queued_ms > 0 OR remote_spill_gb > 1 OR failed_queries > 0, 1, 0)) AS pressure_warehouses
        FROM wh
    """


def build_mart_usage_cost_drivers_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build top warehouse cost drivers from hourly warehouse facts."""
    table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    return f"""
        SELECT
            warehouse_name,
            ROUND(SUM(COALESCE(credits_used, 0)), 4) AS total_credits,
            ROUND(SUM(COALESCE(credits_used_compute, 0)), 4) AS compute_credits,
            ROUND(SUM(COALESCE(credits_used_cloud_services, 0)), 4) AS cloud_credits
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          {company_filter}
          {window_filter}
          {wh_filter}
        GROUP BY warehouse_name
        ORDER BY total_credits DESC
        LIMIT 20
    """


def build_mart_usage_query_mix_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build query type mix from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        SELECT
            COALESCE(query_type, 'UNKNOWN') AS query_type,
            COALESCE(SUM(query_count), 0) AS query_count,
            COUNT(DISTINCT user_name) AS users,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec,
            COALESCE(SUM(failed_count), 0) AS failed_queries
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          {company_filter}
          {window_filter}
          {wh_filter}
          {user_filter}
          {role_filter}
          {db_filter}
        GROUP BY query_type
        ORDER BY query_count DESC
        LIMIT 25
    """


def build_mart_usage_database_adoption_sql(
    days_back: int,
    company: str = "ALFA",
    warehouse_contains: str = "",
    user_contains: str = "",
    role_contains: str = "",
    database_contains: str = "",
    start_date: object = None,
    end_date: object = None,
) -> str:
    """Build database adoption from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    window_filter = _mart_window_filter("HOUR_START", days_back, start_date, end_date)
    wh_filter = _mart_text_filter("WAREHOUSE_NAME", warehouse_contains)
    user_filter = _mart_text_filter("USER_NAME", user_contains)
    role_filter = _mart_text_filter("ROLE_NAME", role_contains)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        SELECT
            COALESCE(database_name, 'UNKNOWN') AS database_name,
            COUNT(DISTINCT user_name) AS users,
            COALESCE(SUM(query_count), 0) AS query_count
        FROM {table}
        WHERE warehouse_name IS NOT NULL
          {company_filter}
          {window_filter}
          {wh_filter}
          {user_filter}
          {role_filter}
          {db_filter}
        GROUP BY database_name
        ORDER BY users DESC, query_count DESC
        LIMIT 20
    """


def build_mart_adoption_summary_sql(days_back: int, company: str = "ALFA") -> str:
    """Build adoption KPI summary from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COALESCE(SUM(query_count), 0) AS total_queries,
            COUNT(DISTINCT user_name) AS total_users,
            ROUND(COALESCE(SUM(query_count), 0) / NULLIF(COUNT(DISTINCT user_name), 0), 1) AS queries_per_user,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_time_per_query_sec,
            ROUND(100 * COALESCE(SUM(failed_count), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0), 1) AS error_rate
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
    """


def build_mart_adoption_warehouse_size_sql(days_back: int, company: str = "ALFA") -> str:
    """Build adoption by warehouse size from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COALESCE(warehouse_size, 'UNKNOWN') AS warehouse_size,
            COALESCE(SUM(query_count), 0) AS query_count,
            COUNT(DISTINCT user_name) AS users,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY warehouse_size
        ORDER BY query_count DESC
    """


def build_mart_adoption_trend_sql(days_back: int, company: str = "ALFA") -> str:
    """Build daily adoption trend from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            DATE_TRUNC('DAY', hour_start) AS activity_day,
            COALESCE(SUM(query_count), 0) AS total_queries,
            COUNT(DISTINCT user_name) AS users,
            ROUND(COALESCE(SUM(query_count), 0) / NULLIF(COUNT(DISTINCT user_name), 0), 1) AS queries_per_user,
            ROUND(100 * COALESCE(SUM(failed_count), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0), 1) AS error_rate
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY activity_day
        ORDER BY activity_day
    """


def build_mart_adoption_users_wh_sql(days_back: int, company: str = "ALFA") -> str:
    """Build users per warehouse from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            warehouse_name,
            COUNT(DISTINCT user_name) AS users,
            COALESCE(SUM(query_count), 0) AS query_count,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY warehouse_name
        ORDER BY users DESC, query_count DESC
        LIMIT 50
    """


def build_mart_adoption_users_db_sql(days_back: int, company: str = "ALFA") -> str:
    """Build users per database from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COALESCE(database_name, 'UNKNOWN') AS database_name,
            COUNT(DISTINCT user_name) AS users,
            COALESCE(SUM(query_count), 0) AS query_count,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY database_name
        ORDER BY users DESC, query_count DESC
        LIMIT 50
    """


def build_mart_adoption_role_type_sql(days_back: int, company: str = "ALFA") -> str:
    """Build role/query-type mix from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COALESCE(role_name, 'UNKNOWN') AS role_name,
            COALESCE(query_type, 'UNKNOWN') AS query_type,
            COALESCE(SUM(query_count), 0) AS query_count,
            COUNT(DISTINCT user_name) AS users,
            ROUND(100 * COALESCE(SUM(failed_count), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0), 1) AS error_rate
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY role_name, query_type
        ORDER BY query_count DESC
        LIMIT 100
    """


def build_mart_storage_trend_sql(days_back: int, company: str = "ALFA") -> str:
    """Build storage trend from daily storage facts."""
    table = mart_object_name("FACT_STORAGE_DAILY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            snapshot_date AS usage_date,
            SUM(active_bytes) / POWER(1024, 3) AS storage_gb,
            SUM(failsafe_bytes) / POWER(1024, 3) AS failsafe_gb,
            0::FLOAT AS stage_gb,
            SUM(active_bytes + failsafe_bytes + retained_for_clone_bytes + time_travel_bytes) / POWER(1024, 4) AS total_storage_tb,
            SUM(est_cost_usd) AS est_monthly_cost_usd
        FROM {table}
        WHERE snapshot_date >= DATEADD('DAY', -{int(days_back)}, CURRENT_DATE())
          {company_filter}
          {env_filter}
        GROUP BY snapshot_date
        ORDER BY snapshot_date
    """


def build_mart_storage_db_detail_sql(company: str = "ALFA") -> str:
    """Build latest per-database storage detail from daily storage facts."""
    table = mart_object_name("FACT_STORAGE_DAILY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    env_filter_s = _mart_environment_filter("s.database_name", company)
    return f"""
        WITH latest AS (
            SELECT MAX(snapshot_date) AS snapshot_date
            FROM {table}
            WHERE 1 = 1
              {company_filter}
              {env_filter}
        )
        SELECT
            database_name,
            s.snapshot_date AS usage_date,
            active_bytes / POWER(1024, 3) AS database_gb,
            failsafe_bytes / POWER(1024, 3) AS failsafe_gb,
            est_storage_tb,
            est_cost_usd
        FROM {table} s
        JOIN latest l ON s.snapshot_date = l.snapshot_date
        WHERE 1 = 1
          {company_filter}
          {env_filter_s}
        ORDER BY database_gb DESC
        LIMIT 50
    """


def build_mart_pipeline_freshness_sql(stale_hours: int, company: str = "ALFA") -> str:
    """Build stale-table watchlist from the latest table snapshot mart."""
    table = mart_object_name("DIM_TABLE_SNAPSHOT")
    latest_company_filter = _mart_company_filter(company)
    table_company_filter = _mart_company_filter(company).replace("COMPANY", "t.company")
    latest_env_filter = _mart_environment_filter("DATABASE_NAME", company)
    table_env_filter = _mart_environment_filter("t.database_name", company)
    return f"""
        WITH latest AS (
            SELECT MAX(snapshot_ts) AS latest_snapshot_ts
            FROM {table}
            WHERE 1 = 1
              {latest_company_filter}
              {latest_env_filter}
        )
        SELECT
            t.database_name,
            t.schema_name,
            t.table_name,
            t.table_type,
            t.row_count,
            t.bytes / POWER(1024, 3) AS size_gb,
            t.last_altered,
            DATEDIFF('HOUR', t.last_altered, CURRENT_TIMESTAMP()) AS hours_since_change
        FROM {table} t
        JOIN latest l ON t.snapshot_ts = l.latest_snapshot_ts
        WHERE t.last_altered IS NOT NULL
          AND DATEDIFF('HOUR', t.last_altered, CURRENT_TIMESTAMP()) >= {int(stale_hours)}
          {table_company_filter}
          {table_env_filter}
        ORDER BY hours_since_change DESC, size_gb DESC
        LIMIT 300
    """


def build_mart_pipeline_load_failures_sql(load_days: int, company: str = "ALFA") -> str:
    """Build load failure groups from the daily COPY_HISTORY mart."""
    table = mart_object_name("FACT_COPY_LOAD_DAILY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            database_name,
            schema_name,
            table_name,
            status,
            SUM(file_count) AS file_count,
            SUM(row_count) AS row_count,
            SUM(error_count) AS error_count,
            SUM(file_size_bytes) AS file_size_bytes,
            SUM(bytes_billed) AS bytes_billed,
            MAX(last_seen) AS last_seen,
            MAX(latest_error) AS latest_error
        FROM {table}
        WHERE load_date >= DATEADD('DAY', -{int(load_days)}, CURRENT_DATE())
          AND UPPER(COALESCE(status, '')) <> 'LOADED'
          {company_filter}
          {env_filter}
        GROUP BY database_name, schema_name, table_name, status
        ORDER BY file_count DESC, last_seen DESC
        LIMIT 300
    """


def build_mart_pipeline_volume_sql(min_gb: float, company: str = "ALFA") -> str:
    """Build table volume watchlist from the latest table snapshot mart."""
    table = mart_object_name("DIM_TABLE_SNAPSHOT")
    latest_company_filter = _mart_company_filter(company)
    table_company_filter = _mart_company_filter(company).replace("COMPANY", "t.company")
    latest_env_filter = _mart_environment_filter("DATABASE_NAME", company)
    table_env_filter = _mart_environment_filter("t.database_name", company)
    return f"""
        WITH latest AS (
            SELECT MAX(snapshot_ts) AS latest_snapshot_ts
            FROM {table}
            WHERE 1 = 1
              {latest_company_filter}
              {latest_env_filter}
        )
        SELECT
            t.database_name,
            t.schema_name,
            t.table_name,
            t.row_count,
            ROUND(t.bytes / POWER(1024, 3), 2) AS size_gb,
            t.last_altered,
            CASE
                WHEN COALESCE(t.row_count, 0) = 0 AND COALESCE(t.bytes, 0) > 0 THEN 'Storage without rows'
                WHEN DATEDIFF('DAY', t.last_altered, CURRENT_TIMESTAMP()) > 90 THEN 'Large and quiet'
                ELSE 'Active large table'
            END AS watch_reason
        FROM {table} t
        JOIN latest l ON t.snapshot_ts = l.latest_snapshot_ts
        WHERE t.bytes / POWER(1024, 3) >= {float(min_gb or 0)}
          {table_company_filter}
          {table_env_filter}
        ORDER BY size_gb DESC
        LIMIT 300
    """


def build_mart_recommendation_idle_sql(company: str = "ALFA") -> str:
    """Build idle warehouse recommendation candidates from hourly mart facts."""
    wh_table = mart_object_name("FACT_WAREHOUSE_HOURLY")
    q_table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    query_env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        WITH wh AS (
            SELECT
                hour_start,
                company,
                warehouse_name,
                SUM(COALESCE(credits_used, 0)) AS credits_used
            FROM {wh_table}
            WHERE hour_start >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
              AND warehouse_name IS NOT NULL
              AND COALESCE(credits_used, 0) > 0
              {company_filter}
            GROUP BY hour_start, company, warehouse_name
        ),
        q AS (
            SELECT
                hour_start,
                company,
                warehouse_name,
                SUM(COALESCE(query_count, 0)) AS query_count
            FROM {q_table}
            WHERE hour_start >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
              AND warehouse_name IS NOT NULL
              {company_filter}
              {query_env_filter}
            GROUP BY hour_start, company, warehouse_name
        )
        SELECT
            wh.warehouse_name,
            COUNT(*) AS idle_hours,
            ROUND(SUM(wh.credits_used), 6) AS idle_credits
        FROM wh
        LEFT JOIN q
            ON wh.hour_start = q.hour_start
           AND wh.company = q.company
           AND wh.warehouse_name = q.warehouse_name
        WHERE COALESCE(q.query_count, 0) = 0
        GROUP BY wh.warehouse_name
        HAVING idle_credits >= 1
        ORDER BY idle_credits DESC
        LIMIT 10
    """


def build_mart_recommendation_spill_sql(company: str = "ALFA") -> str:
    """Build remote spill recommendation candidates from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            warehouse_name,
            MAX(warehouse_size) AS warehouse_size,
            ROUND(SUM(COALESCE(total_spill_bytes, 0)) / POWER(1024, 3), 2) AS remote_gb
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY warehouse_name
        HAVING remote_gb > 5
        ORDER BY remote_gb DESC
        LIMIT 10
    """


def build_mart_recommendation_failed_tasks_sql(company: str = "ALFA") -> str:
    """Build task failure recommendation candidates from task run facts."""
    table = mart_object_name("FACT_TASK_RUN")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            task_name,
            COUNT(*) AS failures
        FROM {table}
        WHERE scheduled_time >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
          AND UPPER(COALESCE(state, '')) IN ('FAILED', 'FAILED_WITH_ERROR')
          {company_filter}
          {env_filter}
        GROUP BY task_name
        HAVING failures > 3
        ORDER BY failures DESC
        LIMIT 5
    """


def build_mart_recommendation_query_errors_sql(company: str = "ALFA", min_failures: int = 10) -> str:
    """Build query failure recommendation candidates from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            warehouse_name,
            SUM(COALESCE(failed_count, 0)) AS failures
        FROM {table}
        WHERE hour_start >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY warehouse_name
        HAVING failures > {int(min_failures)}
        ORDER BY failures DESC
        LIMIT 5
    """


def build_mart_query_bottleneck_sql(
    days_back: int,
    min_elapsed_ms: int,
    company: str = "ALFA",
    extra_filter: str = "",
) -> str:
    """Build Query Analysis bottleneck rows from recent query-detail mart."""
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        SELECT
            q.query_id,
            q.user_name,
            q.warehouse_name,
            q.warehouse_size,
            q.execution_status,
            q.start_time,
            COALESCE(q.total_elapsed_time, 0) / 1000 AS elapsed_sec,
            COALESCE(q.compilation_time, 0) / 1000 AS compile_sec,
            COALESCE(q.execution_time, 0) / 1000 AS exec_sec,
            (
                COALESCE(q.queued_overload_time, 0)
              + COALESCE(q.queued_provisioning_time, 0)
              + COALESCE(q.queued_repair_time, 0)
            ) / 1000 AS queued_sec,
            COALESCE(q.bytes_scanned, 0) / POWER(1024, 3) AS gb_scanned,
            COALESCE(q.bytes_spilled_to_remote_storage, 0) / POWER(1024, 3) AS remote_spill_gb,
            COALESCE(q.partitions_scanned, 0) * 100.0 / NULLIF(COALESCE(q.partitions_total, 0), 0) AS partition_pct,
            COALESCE(q.rows_produced, 0) AS rows_produced,
            0::FLOAT AS metered_credits,
            SUBSTR(COALESCE(q.query_text, ''), 1, 500) AS query_text
        FROM {table} q
        WHERE q.start_time >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          AND COALESCE(q.total_elapsed_time, 0) > {int(min_elapsed_ms)}
          {company_filter}
          {env_filter}
          {extra_filter}
        ORDER BY q.total_elapsed_time DESC
        LIMIT 500
    """


def build_mart_query_degradation_sql(company: str = "ALFA", extra_filter: str = "") -> str:
    """Build query-pattern degradation rows from recent query-detail mart."""
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    company_filter = _mart_company_filter(company).replace("COMPANY", "q.company")
    env_filter = _mart_environment_filter("q.database_name", company)
    return f"""
        WITH base AS (
            SELECT
                COALESCE(q.query_hash, SUBSTR(q.query_text, 1, 200)) AS sig,
                q.start_time,
                q.total_elapsed_time
            FROM {table} q
            WHERE q.start_time >= DATEADD('DAY', -14, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {company_filter}
              {env_filter}
              {extra_filter}
        ),
        sig_recent AS (
            SELECT sig,
                   AVG(total_elapsed_time) / 1000 AS avg_sec,
                   COUNT(*) AS cnt
            FROM base
            WHERE start_time >= DATEADD('DAY', -7, CURRENT_TIMESTAMP())
            GROUP BY sig
            HAVING cnt >= 5
        ),
        sig_prior AS (
            SELECT sig,
                   AVG(total_elapsed_time) / 1000 AS avg_sec,
                   COUNT(*) AS cnt
            FROM base
            WHERE start_time < DATEADD('DAY', -7, CURRENT_TIMESTAMP())
            GROUP BY sig
            HAVING cnt >= 5
        )
        SELECT
            r.sig,
            r.avg_sec AS recent_sec,
            p.avg_sec AS prior_sec,
            ROUND((r.avg_sec - p.avg_sec) / NULLIF(p.avg_sec, 0) * 100, 1) AS pct_change
        FROM sig_recent r
        JOIN sig_prior p ON r.sig = p.sig
        WHERE r.avg_sec > p.avg_sec * 1.25
          AND r.avg_sec > 5
        ORDER BY pct_change DESC
        LIMIT 50
    """


def build_mart_task_inventory_sql(
    company: str = "ALFA",
    database_contains: str = "",
) -> str:
    """Build latest task inventory from the task snapshot mart."""
    table = mart_object_name("DIM_TASK_SNAPSHOT")
    latest_company_filter = _mart_company_filter(company)
    latest_db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    task_company_filter = _mart_company_filter(company).replace("COMPANY", "t.company")
    task_db_filter = _mart_database_filter("t.database_name", database_contains, company)
    return f"""
        WITH latest AS (
            SELECT MAX(snapshot_ts) AS latest_snapshot_ts
            FROM {table}
            WHERE 1 = 1
              {latest_company_filter}
              {latest_db_filter}
        )
        SELECT
            t.task_name AS name,
            t.database_name,
            t.schema_name,
            t.state,
            t.schedule,
            t.warehouse_name AS warehouse,
            TO_VARCHAR(t.predecessors) AS predecessors,
            t.definition,
            t.root_task_name,
            t.procedure_name,
            t.snapshot_ts
        FROM {table} t
        JOIN latest l ON t.snapshot_ts = l.latest_snapshot_ts
        WHERE 1 = 1
          {task_company_filter}
          {task_db_filter}
        ORDER BY t.database_name, t.schema_name, t.root_task_name, t.task_name
    """


def build_mart_task_history_sql(
    days_back: int,
    company: str = "ALFA",
    database_contains: str = "",
    limit: int = 1000,
) -> str:
    """Build task history detail from FACT_TASK_RUN."""
    table = mart_object_name("FACT_TASK_RUN")
    company_filter = _mart_company_filter(company)
    db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    return f"""
        SELECT
            scheduled_time,
            scheduled_time AS query_start_time,
            completed_time,
            database_name,
            schema_name,
            task_name,
            task_name AS name,
            state,
            error_code,
            error_message,
            query_id,
            NULL::VARCHAR AS root_task_id,
            NULL::VARCHAR AS graph_run_group_id,
            COALESCE(duration_ms, 0) / 1000 AS duration_sec
        FROM {table}
        WHERE scheduled_time >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          {company_filter}
          {db_filter}
        ORDER BY scheduled_time DESC
        LIMIT {int(limit)}
    """


def build_mart_task_critical_path_sql(
    days_back: int,
    company: str = "ALFA",
    database_contains: str = "",
    limit: int = 200,
) -> str:
    """Build latest persisted task graph critical-path facts."""
    table = mart_object_name("FACT_TASK_CRITICAL_PATH")
    company_filter = _mart_company_filter(company).replace("COMPANY", "t.company")
    db_filter = _mart_database_filter("t.database_name", database_contains, company)
    return f"""
        WITH latest AS (
            SELECT
                t.*,
                ROW_NUMBER() OVER (
                    PARTITION BY t.company, t.database_name, t.root_task_name
                    ORDER BY t.snapshot_ts DESC
                ) AS rn
            FROM {table} t
            WHERE t.snapshot_ts >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
              {company_filter}
              {db_filter}
        )
        SELECT
            snapshot_ts,
            company,
            environment,
            database_name,
            root_task_name,
            critical_path_state,
            critical_path_score,
            task_count,
            downstream_task_count,
            suspended_tasks,
            failures_7d AS failures,
            runs_7d AS runs,
            successes_7d AS successes,
            max_duration_sec,
            last_run_at,
            blast_radius,
            warehouses,
            procedures,
            owner_role,
            approval_path,
            source_freshness
        FROM latest
        WHERE rn = 1
        ORDER BY critical_path_score DESC, downstream_task_count DESC, max_duration_sec DESC
        LIMIT {int(limit)}
    """


def build_mart_query_detail_recent_sql(query_ids: list[str]) -> str:
    """Build recent query detail lookup from FACT_QUERY_DETAIL_RECENT."""
    clean_ids = [str(qid) for qid in query_ids if str(qid or "").strip()]
    id_list = ", ".join(sql_literal(qid, 200) for qid in clean_ids[:500])
    table = mart_object_name("FACT_QUERY_DETAIL_RECENT")
    if not id_list:
        return ""
    return f"""
        SELECT
            query_id,
            user_name,
            role_name,
            warehouse_name,
            warehouse_size,
            database_name,
            schema_name,
            query_type,
            execution_status,
            start_time,
            end_time,
            COALESCE(total_elapsed_time, 0) / 1000 AS query_elapsed_sec,
            0::FLOAT AS cloud_credits,
            COALESCE(bytes_scanned, 0) AS bytes_scanned,
            COALESCE(rows_produced, 0) AS rows_produced,
            error_code AS query_error_code,
            error_message AS query_error_message,
            SUBSTR(COALESCE(query_text, ''), 1, 4000) AS query_text
        FROM {table}
        WHERE query_id IN ({id_list})
    """


def build_mart_procedure_inventory_sql(
    company: str = "ALFA",
    database_contains: str = "",
) -> str:
    """Build latest stored procedure inventory from DIM_PROCEDURE_SNAPSHOT."""
    table = mart_object_name("DIM_PROCEDURE_SNAPSHOT")
    latest_company_filter = _mart_company_filter(company)
    latest_db_filter = _mart_database_filter("DATABASE_NAME", database_contains, company)
    proc_company_filter = _mart_company_filter(company).replace("COMPANY", "p.company")
    proc_db_filter = _mart_database_filter("p.database_name", database_contains, company)
    return f"""
        WITH latest AS (
            SELECT MAX(snapshot_ts) AS latest_snapshot_ts
            FROM {table}
            WHERE 1 = 1
              {latest_company_filter}
              {latest_db_filter}
        )
        SELECT
            p.database_name AS procedure_catalog,
            p.schema_name AS procedure_schema,
            p.procedure_name,
            p.argument_signature,
            p.owner_role AS procedure_owner,
            p.procedure_language,
            NULL::TIMESTAMP_NTZ AS created,
            p.last_altered,
            p.is_orphan_candidate,
            p.snapshot_ts AS snapshot_ts
        FROM {table} p
        JOIN latest l ON p.snapshot_ts = l.latest_snapshot_ts
        WHERE 1 = 1
          {proc_company_filter}
          {proc_db_filter}
        ORDER BY p.last_altered DESC NULLS LAST, p.procedure_name
        LIMIT 500
    """


def build_mart_procedure_calls_sql(
    days_back: int,
    company: str = "ALFA",
) -> str:
    """Build procedure call summary from FACT_PROCEDURE_RUN."""
    table = mart_object_name("FACT_PROCEDURE_RUN")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("ENVIRONMENT", company)
    return f"""
        SELECT
            procedure_name,
            COUNT(*) AS call_count,
            SUM(COALESCE(child_query_count, 0)) AS downstream_query_count,
            ROUND(SUM(COALESCE(est_credits, 0)), 6) AS total_credits,
            0::FLOAT AS cloud_credits,
            MAX(start_time) AS last_call,
            AVG(COALESCE(total_duration_ms, 0)) / 1000 AS avg_elapsed_sec
        FROM {table}
        WHERE start_time >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          {company_filter}
          {env_filter}
        GROUP BY procedure_name
        ORDER BY call_count DESC
        LIMIT 500
    """


def build_mart_procedure_sla_sql(
    days_back: int,
    company: str = "ALFA",
) -> str:
    """Build procedure run detail for SLA/cost regression from FACT_PROCEDURE_RUN."""
    table = mart_object_name("FACT_PROCEDURE_RUN")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("ENVIRONMENT", company)
    return f"""
        SELECT
            procedure_name,
            database_name,
            root_query_id,
            NULL::VARCHAR AS user_name,
            NULL::VARCHAR AS role_name,
            NULL::VARCHAR AS warehouse_name,
            NULL::VARCHAR AS warehouse_size,
            start_time,
            NULL::VARCHAR AS call_text,
            COALESCE(child_query_count, 0) AS downstream_query_count,
            COALESCE(total_duration_ms, 0) / 1000 AS total_elapsed_sec,
            0::FLOAT AS cloud_credits,
            COALESCE(est_credits, 0) AS est_total_credits,
            status,
            error_message
        FROM {table}
        WHERE start_time >= DATEADD('DAY', -{int(days_back)}, CURRENT_TIMESTAMP())
          {company_filter}
          {env_filter}
        ORDER BY start_time DESC
        LIMIT 1000
    """


def build_mart_service_query_health_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build service-health query processor summary from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COALESCE(SUM(query_count), 0) AS total_queries,
            COALESCE(SUM(failed_count), 0) AS failed_queries,
            COALESCE(SUM(IFF(total_queued_ms > 0, query_count, 0)), 0) AS queued_queries,
            0::NUMBER AS blocked_queries,
            ROUND(COALESCE(SUM(total_elapsed_ms), 0) / NULLIF(COALESCE(SUM(query_count), 0), 0) / 1000, 2) AS avg_elapsed_sec,
            ROUND(MAX(p95_execution_ms) / 1000, 2) AS p95_elapsed_sec
        FROM {table}
        WHERE hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
    """


def build_mart_service_warehouse_health_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build service-health warehouse pressure detail from hourly query facts."""
    table = mart_object_name("FACT_QUERY_HOURLY")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            warehouse_name,
            MAX(warehouse_size) AS warehouse_size,
            COALESCE(SUM(query_count), 0) AS total_queries,
            COALESCE(SUM(failed_count), 0) AS failed_queries,
            ROUND(COALESCE(SUM(total_queued_ms), 0) / 1000, 2) AS queued_sec,
            ROUND(COALESCE(SUM(total_spill_bytes), 0) / POWER(1024, 3), 2) AS remote_spill_gb,
            NULL::FLOAT AS avg_cache_pct
        FROM {table}
        WHERE hour_start >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          AND warehouse_name IS NOT NULL
          {company_filter}
          {env_filter}
        GROUP BY warehouse_name
        ORDER BY queued_sec DESC, remote_spill_gb DESC, failed_queries DESC
        LIMIT 100
    """


def build_mart_service_login_health_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build service-health login summary from daily login facts."""
    table = mart_object_name("FACT_LOGIN_DAILY")
    company_filter = _mart_company_filter(company)
    days = max(1, int((int(hours_back) + 23) / 24))
    return f"""
        SELECT
            COALESCE(SUM(success_count), 0) + COALESCE(SUM(failure_count), 0) AS login_events,
            COALESCE(SUM(failure_count), 0) AS failed_logins,
            COUNT(DISTINCT user_name) AS login_users,
            COUNT(DISTINCT client_ip) AS distinct_ips
        FROM {table}
        WHERE login_date >= DATEADD('DAY', -{days}, CURRENT_DATE())
          {company_filter}
    """


def build_mart_service_task_health_sql(hours_back: int, company: str = "ALFA") -> str:
    """Build service-health task summary from task run facts."""
    table = mart_object_name("FACT_TASK_RUN")
    company_filter = _mart_company_filter(company)
    env_filter = _mart_environment_filter("DATABASE_NAME", company)
    return f"""
        SELECT
            COUNT(*) AS task_runs,
            COALESCE(SUM(IFF(UPPER(COALESCE(state, '')) IN ('FAILED', 'FAILED_WITH_ERROR'), 1, 0)), 0) AS failed_tasks,
            COALESCE(SUM(IFF(UPPER(COALESCE(state, '')) IN ('SUCCEEDED', 'SUCCESS'), 1, 0)), 0) AS succeeded_tasks,
            COUNT(DISTINCT task_name) AS distinct_tasks
        FROM {table}
        WHERE scheduled_time >= DATEADD('HOUR', -{int(hours_back)}, CURRENT_TIMESTAMP())
          {company_filter}
          {env_filter}
    """


def mart_source_caption(result: MartResult, fallback_source: str = "ACCOUNT_USAGE") -> str:
    """Human-readable mart/fallback source label for captions."""
    if result.available and not result.data.empty:
        return f"OVERWATCH mart: {result.source}"
    return fallback_source
