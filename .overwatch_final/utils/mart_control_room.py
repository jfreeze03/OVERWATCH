"""Focused mart SQL builders for the control room family."""

from __future__ import annotations

from .mart_filters import _mart_company_filter, _mart_environment_filter
from .mart_names import mart_object_name

__all__ = [
    "build_mart_control_room_summary_sql",
    "build_mart_control_room_credits_sql",
    "build_mart_control_room_cost_drivers_sql",
    "build_mart_control_room_warehouse_pressure_sql",
    "build_mart_control_room_failed_queries_sql",
    "build_mart_control_room_object_changes_sql",
    "build_mart_control_room_failed_logins_sql",
    "build_mart_control_room_task_failures_sql",
]


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
    """Build top DBA Control Room cost drivers from fast summary facts.

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
