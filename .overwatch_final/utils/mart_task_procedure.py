"""Focused mart SQL builders for the task procedure family."""

from __future__ import annotations

from .mart_filters import _mart_company_filter, _mart_database_filter, _mart_environment_filter
from .mart_names import mart_object_name
from .query import sql_literal

__all__ = [
    "build_mart_task_inventory_sql",
    "build_mart_task_history_sql",
    "build_mart_task_critical_path_sql",
    "build_mart_query_detail_recent_sql",
    "build_mart_procedure_inventory_sql",
    "build_mart_procedure_calls_sql",
    "build_mart_procedure_sla_sql",
]


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
            database_name,
            schema_name,
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
        GROUP BY database_name, schema_name, procedure_name
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
            database_name,
            schema_name,
            procedure_name,
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
