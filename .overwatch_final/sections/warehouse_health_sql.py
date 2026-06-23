# sections/warehouse_health_sql.py - Warehouse Health SQL builders.
from __future__ import annotations

from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE
from sections.base import lazy_util as _lazy_util
from sections.warehouse_health_contracts import (
    WAREHOUSE_OPERABILITY_FACT_TABLE,
    WAREHOUSE_SETTING_REVIEW_TABLE,
)
from sections.warehouse_health_dataframes import _warehouse_text


safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")
mart_object_name = _lazy_util("mart_object_name")
get_environment_filter_clause = _lazy_util("get_environment_filter_clause")
action_queue_environment_clause = _lazy_util("action_queue_environment_clause")


def _admin_audit_fqn() -> str:
    from utils.admin import ADMIN_AUDIT_FQN

    return ADMIN_AUDIT_FQN


def warehouse_setting_review_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = WAREHOUSE_SETTING_REVIEW_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def build_warehouse_setting_review_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = WAREHOUSE_SETTING_REVIEW_TABLE,
) -> str:
    fqn = warehouse_setting_review_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_ID                  VARCHAR(64),
    SNAPSHOT_TS                  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY                      VARCHAR(100),
    ENVIRONMENT                  VARCHAR(100),
    WAREHOUSE_NAME               VARCHAR(300),
    SEVERITY                     VARCHAR(40),
    SIGNAL                       VARCHAR(120),
    OWNER                        VARCHAR(200),
    ESCALATION_TARGET            VARCHAR(200),
    OWNER_SOURCE                 VARCHAR(200),
    APPROVER                     VARCHAR(200),
    APPROVAL_REQUIRED            VARCHAR(20),
    ROLLBACK_REQUIRED            VARCHAR(20),
    SAFE_CHANGE_PATH             VARCHAR(4000),
    SETTING_CHANGE_CANDIDATE     VARCHAR(4000),
    CHANGE_RISK                  VARCHAR(2000),
    POST_CHANGE_VERIFICATION     VARCHAR(2000),
    PRESSURE_EVIDENCE            VARCHAR(2000),
    BASELINE_CAPACITY_SCORE      FLOAT,
    BASELINE_QUEUED_QUERIES      NUMBER,
    BASELINE_SPILL_QUERIES       NUMBER,
    BASELINE_HIGH_LATENCY_QUERIES NUMBER,
    BASELINE_P95_ELAPSED_SEC     FLOAT,
    BASELINE_METERED_CREDITS     FLOAT,
    VERIFICATION_QUERY           VARCHAR(8000),
    GENERATED_REVIEW_SQL         VARCHAR(8000),
    IMPACT_TELEMETRY_REQUIRED VARCHAR(20),
    APPROVAL_STATE               VARCHAR(80),
    CHANGE_TICKET_ID             VARCHAR(200),
    CURRENT_SETTINGS_JSON        VARCHAR(8000),
    PROPOSED_SETTINGS_JSON       VARCHAR(8000),
    ROLLBACK_SQL                 VARCHAR(8000),
    EXECUTED_SQL_HASH            VARCHAR(80),
    EXECUTION_STATUS             VARCHAR(80),
    EXECUTED_BY                  VARCHAR(200),
    EXECUTED_AT                  TIMESTAMP_NTZ,
    POST_CHANGE_VERIFICATION_STATUS VARCHAR(80),
    POST_CHANGE_VERIFICATION_RESULT VARCHAR(4000),
    VERIFIED_MONTHLY_SAVINGS    FLOAT,
    AUDIT_READINESS              VARCHAR(100),
    AUDIT_BLOCKERS               VARCHAR(2000),
    NEXT_CONTROL_ACTION          VARCHAR(4000),
    SOURCE                       VARCHAR(500)
);"""


def build_warehouse_setting_review_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = WAREHOUSE_SETTING_REVIEW_TABLE,
) -> list[str]:
    """Return additive migrations for deployed warehouse setting review tables."""
    fqn = warehouse_setting_review_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS APPROVAL_STATE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CHANGE_TICKET_ID VARCHAR(200)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CURRENT_SETTINGS_JSON VARCHAR(8000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS PROPOSED_SETTINGS_JSON VARCHAR(8000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ROLLBACK_SQL VARCHAR(8000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EXECUTED_SQL_HASH VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EXECUTION_STATUS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EXECUTED_BY VARCHAR(200)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EXECUTED_AT TIMESTAMP_NTZ",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS POST_CHANGE_VERIFICATION_STATUS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS POST_CHANGE_VERIFICATION_RESULT VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS VERIFIED_MONTHLY_SAVINGS FLOAT",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS AUDIT_READINESS VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS AUDIT_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
    ]


def warehouse_operability_fact_fqn(table: str = WAREHOUSE_OPERABILITY_FACT_TABLE) -> str:
    return mart_object_name(table)


def build_warehouse_operability_fact_ddl(table: str = WAREHOUSE_OPERABILITY_FACT_TABLE) -> str:
    fqn = warehouse_operability_fact_fqn(table=table)
    return f"""CREATE TRANSIENT TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_DATE              DATE,
    COMPANY                    VARCHAR(100),
    ENVIRONMENT                VARCHAR(100),
    WAREHOUSE_NAME             VARCHAR(300),
    CONTROL_SOURCE             VARCHAR(80),
    SEVERITY                   VARCHAR(40),
    SIGNAL                     VARCHAR(120),
    CONTROL_STATE              VARCHAR(120),
    CONTROL_RANK               NUMBER,
    CAPACITY_SCORE             FLOAT,
    QUERY_ROWS                 NUMBER,
    QUEUE_PRESSURE_ROWS        NUMBER,
    SPILL_PRESSURE_ROWS        NUMBER,
    HIGH_LATENCY_ROWS          NUMBER,
    METERED_CREDITS            FLOAT,
    CREDIT_ALLOCATION_METHOD   VARCHAR(160),
    REVIEW_ROWS                NUMBER,
    APPROVAL_REQUIRED_ROWS     NUMBER,
    ROLLBACK_REQUIRED_ROWS     NUMBER,
    IMPACT_TELEMETRY_ROWS  NUMBER,
    OPEN_ACTIONS               NUMBER,
    OVERDUE_OPEN               NUMBER,
    FIXED_WITHOUT_VERIFICATION NUMBER,
    VERIFIED_CLOSURES          NUMBER,
    OWNER_APPROVAL_GAP_ROWS    NUMBER,
    NEXT_CONTROL_ACTION        VARCHAR(4000),
    LAST_ACTIVITY_TS           TIMESTAMP_NTZ,
    LOAD_TS                    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);"""


def build_warehouse_operability_fact_migration_sql(
    table: str = WAREHOUSE_OPERABILITY_FACT_TABLE,
) -> list[str]:
    fqn = warehouse_operability_fact_fqn(table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_SOURCE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS SIGNAL VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_RANK NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CAPACITY_SCORE FLOAT",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS QUERY_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS QUEUE_PRESSURE_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS SPILL_PRESSURE_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS HIGH_LATENCY_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CREDIT_ALLOCATION_METHOD VARCHAR(160)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_GAP_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LAST_ACTIVITY_TS TIMESTAMP_NTZ",
    ]


def _warehouse_sql_identifier(name: object) -> str:
    """Return a quoted Snowflake identifier for generated review SQL."""
    text = _warehouse_text(name)
    if not text:
        return '""'
    return '"' + text.replace('"', '""') + '"'


def _warehouse_cost_control_review_sql(warehouse_name: object, recommended_suspend: int = 60) -> str:
    """Generate review-only SQL for warehouse auto-suspend/auto-resume posture."""
    wh_name = _warehouse_text(warehouse_name)
    if not wh_name:
        return "-- Load warehouse metadata before generating warehouse cost-control SQL."
    wh_like = sql_literal(wh_name, 300)
    wh_ident = _warehouse_sql_identifier(wh_name)
    recommended_suspend = max(60, int(recommended_suspend or 60))
    return f"""-- Review only: warehouse cost-control posture for {wh_name}
-- Confirm workload latency, shared usage, and owner impact before executing ALTER WAREHOUSE.
SHOW WAREHOUSES LIKE {wh_like};

-- Candidate setting for DBA review; do not execute without approval for shared warehouses.
ALTER WAREHOUSE {wh_ident}
  SET AUTO_SUSPEND = {recommended_suspend}
      AUTO_RESUME = TRUE;
"""


def _overwatch_dedicated_warehouse_setup_sql() -> str:
    """Return advisory setup SQL for a future dedicated OVERWATCH warehouse."""
    return """-- Future dedicated OVERWATCH warehouse pattern.
-- Review naming, role grants, and resource monitor policy before execution.
CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Dedicated OVERWATCH Snowflake DBA monitoring warehouse';

-- Optional guardrail after resource monitor policy is approved.
-- ALTER WAREHOUSE COMPUTE_WH SET RESOURCE_MONITOR = COMPUTE_WH_RM;
"""


def _warehouse_capacity_verification_sql(
    warehouse_name: str,
    days: int = 7,
    environment: str | None = None,
    company: str | None = None,
) -> str:
    """Build read-only post-change telemetry for one warehouse and environment scope."""
    wh = sql_literal(warehouse_name, 300)
    days = max(1, min(int(days or 7), 30))
    env_clause = get_environment_filter_clause(
        "database_name",
        environment=environment,
        company=company,
    )
    return f"""WITH query_window AS (
    SELECT
        warehouse_name,
        COUNT(*) AS total_queries,
        SUM(IFF(
            COALESCE(queued_overload_time, 0)
            + COALESCE(queued_provisioning_time, 0)
            + COALESCE(queued_repair_time, 0) > 0,
            1,
            0
        )) AS queued_queries,
        SUM(IFF(
            COALESCE(bytes_spilled_to_local_storage, 0)
            + COALESCE(bytes_spilled_to_remote_storage, 0) > 0,
            1,
            0
        )) AS spill_queries,
        AVG(total_elapsed_time) / 1000 AS avg_elapsed_sec,
        APPROX_PERCENTILE(total_elapsed_time / 1000, 0.95) AS p95_elapsed_sec,
        MAX(start_time) AS latest_query_time
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND warehouse_name = {wh}
      {env_clause}
    GROUP BY warehouse_name
),
metering_window AS (
    SELECT
        warehouse_name,
        SUM(COALESCE(credits_used_compute, credits_used)) AS metered_credits,
        MAX(end_time) AS latest_metering_time
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND warehouse_name = {wh}
    GROUP BY warehouse_name
)
SELECT
    COALESCE(q.warehouse_name, m.warehouse_name) AS warehouse_name,
    COALESCE(q.total_queries, 0) AS total_queries,
    COALESCE(q.queued_queries, 0) AS queued_queries,
    COALESCE(q.spill_queries, 0) AS spill_queries,
    ROUND(COALESCE(q.avg_elapsed_sec, 0), 2) AS avg_elapsed_sec,
    ROUND(COALESCE(q.p95_elapsed_sec, 0), 2) AS p95_elapsed_sec,
    ROUND(COALESCE(m.metered_credits, 0), 4) AS metered_credits,
    q.latest_query_time,
    m.latest_metering_time
FROM query_window q
FULL OUTER JOIN metering_window m
  ON m.warehouse_name = q.warehouse_name
ORDER BY metered_credits DESC
LIMIT 50"""


def _warehouse_setting_review_sql(warehouse_name: object, action_type: object, days: int = 7) -> str:
    """Generate review-only SQL for a warehouse setting candidate."""
    wh_name = str(warehouse_name or "").strip()
    if not wh_name or wh_name == "Unknown warehouse":
        return "-- Load warehouse settings and telemetry before generating review SQL."
    wh = sql_literal(wh_name, 300)
    days = max(1, int(days or 7))
    return f"""-- Review only: {action_type} for {wh_name}
-- Do not run ALTER WAREHOUSE from this packet. Use the guarded settings workflow after review.
SHOW WAREHOUSES LIKE {wh};

SELECT warehouse_name,
       ROUND(SUM(COALESCE(credits_used, 0)), 4) AS metered_credits,
       MIN(start_time) AS first_metered_hour,
       MAX(end_time) AS last_metered_hour
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = {wh}
  AND start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
GROUP BY warehouse_name;

SELECT warehouse_name,
       COUNT(*) AS query_count,
       COUNT_IF(UPPER(COALESCE(execution_status, '')) <> 'SUCCESS') AS non_success_queries,
       ROUND(AVG(COALESCE(queued_overload_time, 0)) / 1000, 2) AS avg_queue_sec,
       ROUND(SUM(COALESCE(bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2) AS remote_spill_gb,
       ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY COALESCE(total_elapsed_time, 0)) / 1000, 2) AS p95_elapsed_sec
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE warehouse_name = {wh}
  AND start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
GROUP BY warehouse_name;
"""


def _warehouse_setting_review_history_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = warehouse_setting_review_fqn()
    where = [f"SNAPSHOT_TS >= DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_value = str(environment or "").strip()
    if env_value and env_value.upper() != "ALL":
        where.append(f"ENVIRONMENT = {sql_literal(env_value, 100)}")
    where_clause = " AND ".join(where)
    return f"""
SELECT
    WAREHOUSE_NAME,
    OWNER,
    ESCALATION_TARGET,
    COUNT(*) AS REVIEW_ROWS,
    COUNT_IF(APPROVAL_REQUIRED = 'Yes') AS APPROVAL_REQUIRED_ROWS,
    COUNT_IF(ROLLBACK_REQUIRED = 'Yes') AS ROLLBACK_REQUIRED_ROWS,
    COUNT_IF(IMPACT_TELEMETRY_REQUIRED = 'Yes') AS IMPACT_TELEMETRY_ROWS,
    MIN(BASELINE_CAPACITY_SCORE) AS WORST_BASELINE_CAPACITY_SCORE,
    MAX(BASELINE_QUEUED_QUERIES) AS MAX_BASELINE_QUEUED_QUERIES,
    MAX(BASELINE_SPILL_QUERIES) AS MAX_BASELINE_SPILL_QUERIES,
    MAX(BASELINE_METERED_CREDITS) AS MAX_BASELINE_METERED_CREDITS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX_BY(SIGNAL, SNAPSHOT_TS) AS LAST_SIGNAL,
    MAX_BY(SETTING_CHANGE_CANDIDATE, SNAPSHOT_TS) AS LAST_SETTING_CHANGE_CANDIDATE
FROM {fqn}
WHERE {where_clause}
GROUP BY WAREHOUSE_NAME, OWNER, ESCALATION_TARGET
ORDER BY
    WORST_BASELINE_CAPACITY_SCORE ASC,
    APPROVAL_REQUIRED_ROWS DESC,
    LAST_SNAPSHOT_TS DESC
LIMIT 100""".strip()


def _warehouse_setting_execution_audit_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Join persisted setting reviews to guarded ALTER WAREHOUSE audit telemetry."""
    review_fqn = warehouse_setting_review_fqn()
    admin_audit_fqn = _admin_audit_fqn()
    days = max(1, min(int(days or 30), 180))
    review_where = [f"SNAPSHOT_TS >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())"]
    audit_where = [
        f"ACTION_TS >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())",
        "UPPER(ACTION_TYPE) = 'ALTER WAREHOUSE'",
    ]
    if str(company or "").upper() != "ALL":
        company_sql = sql_literal(company, 100)
        review_where.append(f"COMPANY = {company_sql}")
        audit_where.append(f"COMPANY = {company_sql}")
    env_clause_review = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause_review:
        review_where.append(env_clause_review)
        audit_where.append(env_clause_review)
    return f"""
WITH review_rows AS (
    SELECT
        WAREHOUSE_NAME,
        MAX_BY(OWNER, SNAPSHOT_TS) AS OWNER,
        MAX_BY(APPROVER, SNAPSHOT_TS) AS APPROVER,
        MAX_BY(APPROVAL_STATE, SNAPSHOT_TS) AS APPROVAL_STATE,
        MAX_BY(CHANGE_TICKET_ID, SNAPSHOT_TS) AS CHANGE_TICKET_ID,
        MAX_BY(ROLLBACK_SQL, SNAPSHOT_TS) AS ROLLBACK_SQL,
        MAX_BY(POST_CHANGE_VERIFICATION_STATUS, SNAPSHOT_TS) AS POST_CHANGE_VERIFICATION_STATUS,
        MAX_BY(POST_CHANGE_VERIFICATION_RESULT, SNAPSHOT_TS) AS POST_CHANGE_VERIFICATION_RESULT,
        MAX_BY(AUDIT_READINESS, SNAPSHOT_TS) AS LAST_REVIEW_AUDIT_READINESS,
        MAX_BY(AUDIT_BLOCKERS, SNAPSHOT_TS) AS LAST_REVIEW_AUDIT_BLOCKERS,
        COUNT(*) AS REVIEW_ROWS,
        COUNT_IF(APPROVAL_REQUIRED = 'Yes') AS APPROVAL_REQUIRED_ROWS,
        COUNT_IF(ROLLBACK_REQUIRED = 'Yes') AS ROLLBACK_REQUIRED_ROWS,
        COUNT_IF(IMPACT_TELEMETRY_REQUIRED = 'Yes') AS IMPACT_TELEMETRY_REQUIRED_ROWS,
        MAX(SNAPSHOT_TS) AS LAST_REVIEW_TS
    FROM {review_fqn}
    WHERE {" AND ".join(review_where)}
    GROUP BY WAREHOUSE_NAME
),
audit_rows AS (
    SELECT
        TARGET_OBJECT AS WAREHOUSE_NAME,
        COUNT(*) AS AUDIT_ROWS,
        COUNT_IF(UPPER(RESULT_STATUS) = 'SUCCESS') AS SUCCESSFUL_CHANGES,
        COUNT_IF(UPPER(RESULT_STATUS) = 'FAILED') AS FAILED_CHANGES,
        MAX_BY(SQL_HASH, ACTION_TS) AS LAST_SQL_HASH,
        MAX_BY(SNOWFLAKE_USER, ACTION_TS) AS LAST_EXECUTED_BY,
        MAX_BY(SNOWFLAKE_ROLE, ACTION_TS) AS LAST_EXECUTED_ROLE,
        MAX_BY(RESULT_STATUS, ACTION_TS) AS LAST_EXECUTION_STATUS,
        MAX_BY(RESULT_MESSAGE, ACTION_TS) AS LAST_EXECUTION_MESSAGE,
        MAX_BY(CONTROL_CONTEXT, ACTION_TS) AS LAST_CONTROL_CONTEXT,
        MAX(ACTION_TS) AS LAST_EXECUTED_AT
    FROM {admin_audit_fqn}
    WHERE {" AND ".join(audit_where)}
    GROUP BY TARGET_OBJECT
)
SELECT
    COALESCE(r.WAREHOUSE_NAME, a.WAREHOUSE_NAME) AS WAREHOUSE_NAME,
    COALESCE(r.OWNER, '') AS OWNER,
    COALESCE(r.APPROVER, '') AS APPROVER,
    COALESCE(r.APPROVAL_STATE, '') AS APPROVAL_STATE,
    COALESCE(r.CHANGE_TICKET_ID, '') AS CHANGE_TICKET_ID,
    COALESCE(r.ROLLBACK_SQL, '') AS ROLLBACK_SQL,
    COALESCE(r.POST_CHANGE_VERIFICATION_STATUS, '') AS POST_CHANGE_VERIFICATION_STATUS,
    COALESCE(r.POST_CHANGE_VERIFICATION_RESULT, '') AS POST_CHANGE_VERIFICATION_RESULT,
    COALESCE(r.LAST_REVIEW_AUDIT_READINESS, '') AS LAST_REVIEW_AUDIT_READINESS,
    COALESCE(r.LAST_REVIEW_AUDIT_BLOCKERS, '') AS LAST_REVIEW_AUDIT_BLOCKERS,
    COALESCE(r.REVIEW_ROWS, 0) AS REVIEW_ROWS,
    COALESCE(r.APPROVAL_REQUIRED_ROWS, 0) AS APPROVAL_REQUIRED_ROWS,
    COALESCE(r.ROLLBACK_REQUIRED_ROWS, 0) AS ROLLBACK_REQUIRED_ROWS,
    COALESCE(r.IMPACT_TELEMETRY_REQUIRED_ROWS, 0) AS IMPACT_TELEMETRY_REQUIRED_ROWS,
    r.LAST_REVIEW_TS,
    COALESCE(a.AUDIT_ROWS, 0) AS AUDIT_ROWS,
    COALESCE(a.SUCCESSFUL_CHANGES, 0) AS SUCCESSFUL_CHANGES,
    COALESCE(a.FAILED_CHANGES, 0) AS FAILED_CHANGES,
    COALESCE(a.LAST_SQL_HASH, '') AS LAST_SQL_HASH,
    COALESCE(a.LAST_EXECUTED_BY, '') AS LAST_EXECUTED_BY,
    COALESCE(a.LAST_EXECUTED_ROLE, '') AS LAST_EXECUTED_ROLE,
    COALESCE(a.LAST_EXECUTION_STATUS, 'Not Executed') AS LAST_EXECUTION_STATUS,
    COALESCE(a.LAST_EXECUTION_MESSAGE, '') AS LAST_EXECUTION_MESSAGE,
    COALESCE(a.LAST_CONTROL_CONTEXT, '') AS LAST_CONTROL_CONTEXT,
    a.LAST_EXECUTED_AT,
    CASE
        WHEN COALESCE(a.FAILED_CHANGES, 0) > 0 THEN 'Execution failed'
        WHEN COALESCE(r.REVIEW_ROWS, 0) > 0 AND COALESCE(a.AUDIT_ROWS, 0) = 0 THEN 'Reviewed but not executed'
        WHEN COALESCE(a.SUCCESSFUL_CHANGES, 0) > 0
             AND UPPER(COALESCE(r.POST_CHANGE_VERIFICATION_STATUS, '')) <> 'VERIFIED' THEN 'Executed - telemetry pending'
        WHEN COALESCE(r.IMPACT_TELEMETRY_REQUIRED_ROWS, 0) > 0
             AND LENGTH(TRIM(COALESCE(r.POST_CHANGE_VERIFICATION_RESULT, ''))) < 15 THEN 'Impact telemetry pending'
        WHEN COALESCE(a.SUCCESSFUL_CHANGES, 0) > 0 THEN 'Executed and audit linked'
        ELSE 'No setting review'
    END AS EXECUTION_AUDIT_READINESS,
    CASE
        WHEN COALESCE(a.FAILED_CHANGES, 0) > 0 THEN 'Open failed admin audit row and confirm rollback/no-op state.'
        WHEN COALESCE(r.REVIEW_ROWS, 0) > 0 AND COALESCE(a.AUDIT_ROWS, 0) = 0 THEN 'Execute only through the guarded warehouse settings workflow after review, ticket, and rollback SQL are present.'
        WHEN COALESCE(a.SUCCESSFUL_CHANGES, 0) > 0
             AND UPPER(COALESCE(r.POST_CHANGE_VERIFICATION_STATUS, '')) <> 'VERIFIED' THEN 'Refresh post-change telemetry before closure.'
        WHEN COALESCE(r.IMPACT_TELEMETRY_REQUIRED_ROWS, 0) > 0
             AND LENGTH(TRIM(COALESCE(r.POST_CHANGE_VERIFICATION_RESULT, ''))) < 15 THEN 'Wait for measured impact telemetry for the credit-control change.'
        WHEN COALESCE(a.SUCCESSFUL_CHANGES, 0) > 0 THEN 'Keep SQL hash, executor, role, rollback, and telemetry status.'
        ELSE 'Create a setting review snapshot before changing this warehouse.'
    END AS NEXT_CONTROL_ACTION
FROM review_rows r
FULL OUTER JOIN audit_rows a
  ON UPPER(r.WAREHOUSE_NAME) = UPPER(a.WAREHOUSE_NAME)
ORDER BY
    CASE EXECUTION_AUDIT_READINESS
        WHEN 'Execution failed' THEN 1
        WHEN 'Executed - telemetry pending' THEN 2
        WHEN 'Impact telemetry pending' THEN 3
        WHEN 'Reviewed but not executed' THEN 4
        WHEN 'No setting review' THEN 8
        ELSE 9
    END,
    LAST_EXECUTED_AT DESC NULLS LAST,
    LAST_REVIEW_TS DESC NULLS LAST
LIMIT 100""".strip()


def _warehouse_action_queue_closure_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier(ACTION_QUEUE_TABLE)}"
    where = [
        "SOURCE IN ('Warehouse Health - Capacity Brief', 'Warehouse Health - Efficiency')",
        f"COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_TIMESTAMP())",
    ]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
WITH scoped_actions AS (
    SELECT
        COALESCE(ENTITY_NAME, 'Unknown warehouse') AS WAREHOUSE_NAME,
        COALESCE(SOURCE, '') AS SOURCE,
        COALESCE(OWNER, '') AS OWNER,
        COALESCE(APPROVER, '') AS APPROVER,
        COALESCE(STATUS, 'New') AS STATUS,
        COALESCE(SEVERITY, 'Medium') AS SEVERITY,
        COALESCE(TICKET_ID, '') AS TICKET_ID,
        DUE_DATE,
        COALESCE(VERIFICATION_STATUS, '') AS VERIFICATION_STATUS,
        COALESCE(VERIFICATION_QUERY, PROOF_QUERY, '') AS VERIFICATION_QUERY,
        COALESCE(VERIFICATION_RESULT, '') AS VERIFICATION_RESULT,
        COALESCE(OWNER_APPROVAL_STATUS, '') AS OWNER_APPROVAL_STATUS,
        COALESCE(RECOVERY_SLA_STATE, '') AS RECOVERY_SLA_STATE,
        COALESCE(RECOVERY_EVIDENCE, '') AS RECOVERY_EVIDENCE,
        COALESCE(UPDATED_AT, CREATED_AT) AS LAST_ACTIVITY_TS
    FROM {fqn}
    WHERE {where_clause}
),
rollup AS (
    SELECT
        WAREHOUSE_NAME,
        MAX_BY(SOURCE, LAST_ACTIVITY_TS) AS LAST_SOURCE,
        MAX_BY(OWNER, LAST_ACTIVITY_TS) AS OWNER,
        MAX_BY(APPROVER, LAST_ACTIVITY_TS) AS APPROVER,
        COUNT(*) AS TOTAL_ACTIONS,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
        COUNT_IF(UPPER(STATUS) = 'FIXED') AS FIXED_ACTIONS,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND UPPER(VERIFICATION_STATUS) = 'VERIFIED'
            AND LENGTH(TRIM(VERIFICATION_RESULT)) >= 15
        ) AS VERIFIED_CLOSURES,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND (
                UPPER(VERIFICATION_STATUS) <> 'VERIFIED'
                OR LENGTH(TRIM(VERIFICATION_RESULT)) < 15
            )
        ) AS FIXED_WITHOUT_VERIFICATION,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
        COUNT_IF(UPPER(OWNER) IN ('', 'DBA', 'UNKNOWN', 'N/A')) AS OWNER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(TICKET_ID)) = 0) AS TICKET_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(APPROVER)) = 0) AS APPROVER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(VERIFICATION_QUERY)) = 0) AS VERIFICATION_QUERY_GAP_ROWS,
        COUNT_IF(UPPER(OWNER_APPROVAL_STATUS) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
        COUNT_IF(
            UPPER(RECOVERY_SLA_STATE) ILIKE '%BREACH%'
            OR UPPER(RECOVERY_SLA_STATE) ILIKE '%LATE%'
            OR (
                UPPER(STATUS) = 'FIXED'
                AND LENGTH(TRIM(RECOVERY_EVIDENCE)) < 15
            )
        ) AS RECOVERY_RISK_ROWS,
        MIN(IFF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED'), DUE_DATE, NULL)) AS NEXT_DUE_DATE,
        MAX(LAST_ACTIVITY_TS) AS LAST_ACTIVITY_TS,
        MAX_BY(STATUS, LAST_ACTIVITY_TS) AS LAST_STATUS,
        MAX_BY(SEVERITY, LAST_ACTIVITY_TS) AS LAST_SEVERITY
    FROM scoped_actions
    GROUP BY WAREHOUSE_NAME
)
SELECT
    WAREHOUSE_NAME,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Overdue closure'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Closed pending telemetry'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Control metadata gap'
        WHEN OPEN_ACTIONS > 0 THEN 'Open'
        WHEN VERIFIED_CLOSURES > 0 THEN 'Closed'
        ELSE 'No recent action'
    END AS CLOSURE_READINESS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 0
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 1
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 2
        WHEN OPEN_ACTIONS > 0 THEN 3
        WHEN VERIFIED_CLOSURES > 0 THEN 8
        ELSE 9
    END AS CLOSURE_RANK,
    LAST_SOURCE,
    OWNER,
    APPROVER,
    TOTAL_ACTIONS,
    OPEN_ACTIONS,
    FIXED_ACTIONS,
    VERIFIED_CLOSURES,
    FIXED_WITHOUT_VERIFICATION,
    OVERDUE_OPEN,
    OWNER_GAP_ROWS,
    TICKET_GAP_ROWS,
    APPROVER_GAP_ROWS,
    VERIFICATION_QUERY_GAP_ROWS,
    OWNER_APPROVAL_GAP_ROWS,
    RECOVERY_RISK_ROWS,
    NEXT_DUE_DATE,
    LAST_STATUS,
    LAST_SEVERITY,
    LAST_ACTIVITY_TS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Escalate the warehouse route and ticket before changing settings.'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Wait for post-change queue/spill/credit telemetry or reopen the action.'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Complete route, ticket, reviewer, and telemetry metadata.'
        WHEN OPEN_ACTIONS > 0 THEN 'Work the open warehouse action and retain rollback plus post-change status.'
        ELSE 'Keep closure status visible for capacity and cost trend review.'
    END AS NEXT_ACTION
FROM rollup
ORDER BY CLOSURE_RANK, OVERDUE_OPEN DESC, FIXED_WITHOUT_VERIFICATION DESC, OPEN_ACTIONS DESC, LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _warehouse_operability_fact_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Read warehouse capacity, setting-review, and closure blockers from the fast summary."""
    table = warehouse_operability_fact_fqn()
    where = [f"SNAPSHOT_DATE >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_DATE())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
SELECT
    SNAPSHOT_DATE,
    COMPANY,
    ENVIRONMENT,
    WAREHOUSE_NAME,
    CONTROL_SOURCE,
    SEVERITY,
    SIGNAL,
    CONTROL_STATE,
    CONTROL_RANK,
    CAPACITY_SCORE,
    QUERY_ROWS,
    QUEUE_PRESSURE_ROWS,
    SPILL_PRESSURE_ROWS,
    HIGH_LATENCY_ROWS,
    METERED_CREDITS,
    CREDIT_ALLOCATION_METHOD,
    REVIEW_ROWS,
    APPROVAL_REQUIRED_ROWS,
    ROLLBACK_REQUIRED_ROWS,
    IMPACT_TELEMETRY_ROWS,
    OPEN_ACTIONS,
    OVERDUE_OPEN,
    FIXED_WITHOUT_VERIFICATION,
    VERIFIED_CLOSURES,
    OWNER_APPROVAL_GAP_ROWS,
    NEXT_CONTROL_ACTION,
    LAST_ACTIVITY_TS,
    LOAD_TS
FROM {table}
WHERE {where_clause}
ORDER BY
    CONTROL_RANK,
    OVERDUE_OPEN DESC,
    FIXED_WITHOUT_VERIFICATION DESC,
    QUEUE_PRESSURE_ROWS DESC,
    SPILL_PRESSURE_ROWS DESC,
    METERED_CREDITS DESC,
    LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()
