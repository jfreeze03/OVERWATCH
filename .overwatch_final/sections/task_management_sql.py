# sections/task_management_sql.py - Task Management SQL builders
import pandas as pd

from config import ALERT_DB, ALERT_SCHEMA, ETL_AUDIT_DB, ETL_AUDIT_SCHEMA, ETL_AUDIT_TABLE
from sections.task_management_models import _task_environment, _task_full_name
from utils import filter_existing_columns, safe_identifier, safe_int, sql_literal

ETL_AUDIT_FQN = (
    f"{safe_identifier(ETL_AUDIT_DB)}."
    f"{safe_identifier(ETL_AUDIT_SCHEMA)}."
    f"{safe_identifier(ETL_AUDIT_TABLE)}"
)
ADMIN_AUDIT_FQN = (
    f"{safe_identifier(ALERT_DB)}."
    f"{safe_identifier(ALERT_SCHEMA)}."
    f"{safe_identifier('OVERWATCH_ADMIN_ACTION_AUDIT')}"
)

def _query_detail_sql(session, query_ids: list[str]) -> str:
    clean_ids = [str(qid) for qid in query_ids if str(qid or "").strip()]
    if not clean_ids:
        return ""
    cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "QUERY_ID", "USER_NAME", "ROLE_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
            "DATABASE_NAME", "SCHEMA_NAME", "QUERY_TYPE", "EXECUTION_STATUS",
            "START_TIME", "END_TIME", "TOTAL_ELAPSED_TIME", "ERROR_CODE",
            "ERROR_MESSAGE", "QUERY_TEXT", "CREDITS_USED_CLOUD_SERVICES",
            "BYTES_SCANNED", "ROWS_PRODUCED",
        ],
    ))

    def expr(col: str, fallback: str) -> str:
        return col if col in cols else fallback

    id_list = ", ".join(sql_literal(qid, 200) for qid in clean_ids[:500])
    return f"""
        SELECT
            {expr("QUERY_ID", "NULL::VARCHAR")} AS query_id,
            {expr("USER_NAME", "NULL::VARCHAR")} AS user_name,
            {expr("ROLE_NAME", "NULL::VARCHAR")} AS role_name,
            {expr("WAREHOUSE_NAME", "NULL::VARCHAR")} AS warehouse_name,
            {expr("WAREHOUSE_SIZE", "NULL::VARCHAR")} AS warehouse_size,
            {expr("DATABASE_NAME", "NULL::VARCHAR")} AS database_name,
            {expr("SCHEMA_NAME", "NULL::VARCHAR")} AS schema_name,
            {expr("QUERY_TYPE", "NULL::VARCHAR")} AS query_type,
            {expr("EXECUTION_STATUS", "NULL::VARCHAR")} AS execution_status,
            {expr("START_TIME", "NULL::TIMESTAMP_NTZ")} AS start_time,
            {expr("END_TIME", "NULL::TIMESTAMP_NTZ")} AS end_time,
            {expr("TOTAL_ELAPSED_TIME", "0::NUMBER")} / 1000 AS query_elapsed_sec,
            {expr("CREDITS_USED_CLOUD_SERVICES", "0::FLOAT")} AS cloud_credits,
            {expr("BYTES_SCANNED", "0::NUMBER")} AS bytes_scanned,
            {expr("ROWS_PRODUCED", "0::NUMBER")} AS rows_produced,
            {expr("ERROR_CODE", "NULL::VARCHAR")} AS query_error_code,
            {expr("ERROR_MESSAGE", "NULL::VARCHAR")} AS query_error_message,
            SUBSTR({expr("QUERY_TEXT", "''")}, 1, 4000) AS query_text
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE query_id IN ({id_list})
    """

def _admin_sql_for_task(row: pd.Series, action: str) -> list[str]:
    full_name = _task_full_name(row)
    action = str(action or "").upper()
    if action == "SUSPEND":
        return [f"ALTER TASK {full_name} SUSPEND"]
    if action == "RESUME":
        return [f"ALTER TASK {full_name} RESUME"]
    if action in {"EXECUTE", "RETRY"}:
        return [f"EXECUTE TASK {full_name}"]
    raise ValueError(f"Unsupported task action: {action}")

def _admin_sql_for_graph(graph_tasks: pd.DataFrame, root_name: str, action: str) -> list[str]:
    if graph_tasks is None or graph_tasks.empty:
        return []
    action = str(action or "").upper()
    root_rows = graph_tasks[graph_tasks["NAME"].astype(str) == str(root_name)] if "NAME" in graph_tasks.columns else pd.DataFrame()
    if root_rows.empty:
        return []
    root_row = root_rows.iloc[0]
    if action == "SUSPEND":
        # Suspending the root stops future graph scheduling without forcing every branch offline.
        return _admin_sql_for_task(root_row, "SUSPEND")
    if action == "EXECUTE" or action == "RETRY":
        return _admin_sql_for_task(root_row, "EXECUTE")
    if action == "RESUME":
        child_rows = graph_tasks[graph_tasks["NAME"].astype(str) != str(root_name)].copy()
        child_sql = [_admin_sql_for_task(row, "RESUME")[0] for _, row in child_rows.iterrows()]
        return child_sql + _admin_sql_for_task(root_row, "RESUME")
    raise ValueError(f"Unsupported graph action: {action}")

def build_admin_preflight_sql(row: pd.Series) -> str:
    full_name = _task_full_name(row)
    database_name = safe_identifier(row.get("DATABASE_NAME", ""))
    task_name = str(row.get("NAME") or "<task_name>")
    return f"""-- Read-only pre-flight before live task action
-- CURRENT_USER() can be blocked inside Snowflake-hosted Streamlit.
SELECT CURRENT_ROLE() AS current_role,
       CURRENT_WAREHOUSE() AS current_warehouse;

SHOW GRANTS ON TASK {full_name};

SELECT *
FROM TABLE({database_name}.INFORMATION_SCHEMA.TASK_HISTORY(
    TASK_NAME => {sql_literal(task_name, 512)},
    RESULT_LIMIT => 20
))
ORDER BY SCHEDULED_TIME DESC;

-- Confirm the active role has OPERATE or OWNERSHIP on the task before ALTER/EXECUTE/CANCEL.
-- Confirm the selected company/environment is correct before running generated admin SQL.
"""

def _task_reliability_verification_sql(row: pd.Series, lookback_days: int = 7) -> str:
    task_name = str(row.get("TASK_NAME") or row.get("NAME") or "").strip()
    task_fqn = str(row.get("TASK_FQN") or "").strip()
    name_filter = ""
    if task_name:
        name_filter = f"AND name = {sql_literal(task_name, 500)}"
    return f"""-- Task reliability telemetry and post-fix status
-- Task FQN: {task_fqn or task_name or 'UNKNOWN'}
SELECT name,
       database_name,
       schema_name,
       state,
       scheduled_time,
       completed_time,
       query_id,
       error_code,
       error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE scheduled_time >= DATEADD('day', -{max(1, int(lookback_days or 7))}, CURRENT_TIMESTAMP())
  {name_filter}
ORDER BY scheduled_time DESC
LIMIT 50;

-- Status rule: latest run should be SUCCEEDED and runtime/credits should return inside the selected SLA baseline.
"""

def _task_reliability_proof_sql(row: pd.Series, lookback_days: int = 7) -> str:
    """Return richer human telemetry text while keeping runnable status SQL separate."""
    verification_sql = _task_reliability_verification_sql(row, lookback_days).strip()
    query_id = str(row.get("QUERY_ID") or "").strip()
    if not query_id:
        return verification_sql
    return f"""{verification_sql}

-- Linked QUERY_HISTORY telemetry for root-cause review:
SELECT query_id,
       execution_status,
       start_time,
       end_time,
       total_elapsed_time / 1000 AS elapsed_sec,
       error_code,
       error_message,
       SUBSTR(query_text, 1, 4000) AS query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_id = {sql_literal(query_id, 200)};
"""

def _task_reliability_generated_sql(row: pd.Series) -> str:
    retry_sql = str(row.get("RETRY_SQL") or "").strip()
    task_fqn = str(row.get("TASK_FQN") or row.get("TASK_NAME") or "UNKNOWN_TASK")
    incident_priority = str(row.get("INCIDENT_PRIORITY") or "").strip()
    recovery_readiness = str(row.get("RECOVERY_READINESS") or "").strip()
    owner_approval_state = str(row.get("OWNER_APPROVAL_STATE") or "").strip()
    if retry_sql and not retry_sql.startswith("--"):
        retry_line = retry_sql
    else:
        retry_line = f"-- EXECUTE TASK {task_fqn};"
    return (
        "-- Reviewed recovery plan. Do not execute until root cause is fixed.\n"
        f"-- Task: {task_fqn}\n"
        f"-- Priority: {incident_priority or 'Unranked'}\n"
        f"-- Recovery status: {recovery_readiness or 'DBA review required'}\n"
        f"-- Status: {owner_approval_state or 'Required before close'}\n"
        f"-- Graph role: {row.get('GRAPH_ROLE', '')}; downstream tasks: {safe_int(row.get('DOWNSTREAM_TASK_COUNT'))}\n"
        f"-- Linked procedure: {row.get('PROCEDURE_NAME', '')}\n"
        f"-- Impact objects: {row.get('IMPACT_OBJECTS', '')}\n"
        f"{retry_line}\n"
        "-- After retry, run the status query and record telemetry in the action queue."
    )

__all__ = ['ETL_AUDIT_FQN', 'ADMIN_AUDIT_FQN', '_query_detail_sql', '_admin_sql_for_task', '_admin_sql_for_graph', 'build_admin_preflight_sql', '_task_reliability_verification_sql', '_task_reliability_proof_sql', '_task_reliability_generated_sql']
