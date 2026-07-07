"""Alert command-center setup SQL and runbook helpers.

This module owns the SQL contract for alert lifecycle tables, event
materialization, acknowledgement/remediation audit inserts, signal-query
catalogs, privilege readiness, optional integrations, and the operator runbook.
Runtime dataframe normalization and visible alert boards live in focused
sibling modules while ``utils.alerts`` stays as the compatibility facade.
"""
from __future__ import annotations

import pandas as pd

from config import ALERT_DB, ALERT_SCHEMA
from .alert_native_catalog import (
    _values_clause,
    build_alert_data_quality_checks_ddl,
    build_alert_native_deployment_review_sql,
    build_alert_native_registry_ddl,
    build_alert_remediation_policy_ddl,
    build_alert_threshold_seed_rows,
)
from .alert_status import normalize_command_center_alert_status as normalize_alert_status
from .query import safe_identifier, sql_literal


def alert_triage_view_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    view: str = "OVERWATCH_ALERT_TRIAGE_V",
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(view)}"
    return f"{db}.{schema}.{view}"


ALERT_COMMAND_CENTER_TABLES = (
    "ALERT_CONFIG",
    "ALERT_EVENTS",
    "ALERT_RUN_HISTORY",
    "ALERT_ACKNOWLEDGEMENTS",
    "ALERT_REMEDIATION_LOG",
    "ALERT_NOTIFICATION_LOG",
    "ALERT_THRESHOLDS",
    "ALERT_WORKFLOW_ROUTING",
)
ALERT_COMMAND_CENTER_CATEGORIES = (
    "Security",
    "Cost",
    "Performance",
    "Task / Pipeline",
    "Data Quality",
    "Optimization",
)


def _command_center_fqn(
    object_name: str,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    *,
    quoted: bool = True,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(object_name)}"
    return f"{db}.{schema}.{object_name}"


def _alert_event_id_expr(event_id: int | str) -> str:
    return f"TRY_TO_NUMBER({sql_literal(str(event_id or '').strip(), 100)})"


def build_alert_acknowledgement_insert_sql(
    *,
    event_id: int | str,
    alert_key: str = "",
    note: str,
    actor: str = "OVERWATCH",
    owner: str = "",
    status_after_ack: str = "Acknowledged",
    next_checkpoint_hours: int | None = None,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Return an insert into ALERT_ACKNOWLEDGEMENTS for auditable alert lifecycle actions."""
    note_clean = str(note or "").strip()
    if len(note_clean) < 5:
        raise ValueError("Alert acknowledgement requires a note with route, ticket, or investigation context.")
    checkpoint_expr = "NULL"
    if next_checkpoint_hours is not None:
        checkpoint_expr = f"DATEADD('hour', {max(1, int(next_checkpoint_hours))}, CURRENT_TIMESTAMP())"
    return f"""
INSERT INTO {_command_center_fqn("ALERT_ACKNOWLEDGEMENTS", db, schema)}
    (EVENT_ID, ALERT_KEY, ACKNOWLEDGED_AT, ACKNOWLEDGED_BY, ACK_NOTE,
     STATUS_AFTER_ACK, OWNER_ASSIGNED, NEXT_CHECKPOINT_AT)
SELECT
    {_alert_event_id_expr(event_id)} AS EVENT_ID,
    {sql_literal(alert_key, 200)} AS ALERT_KEY,
    CURRENT_TIMESTAMP() AS ACKNOWLEDGED_AT,
    {sql_literal(actor, 200)} AS ACKNOWLEDGED_BY,
    {sql_literal(note_clean, 4000)} AS ACK_NOTE,
    {sql_literal(normalize_alert_status(status_after_ack), 40)} AS STATUS_AFTER_ACK,
    NULLIF({sql_literal(owner, 200)}, '') AS OWNER_ASSIGNED,
    {checkpoint_expr} AS NEXT_CHECKPOINT_AT;
""".strip()


def build_alert_remediation_log_insert_sql(
    *,
    event_id: int | str,
    alert_key: str = "",
    remediation_mode: str = "RECOMMEND",
    action_type: str,
    action_sql: str = "",
    before_state: str = "",
    after_state: str = "",
    execution_status: str = "REQUESTED",
    error_message: str = "",
    rollback_guidance: str = "",
    affected_user: str = "",
    affected_object: str = "",
    affected_warehouse: str = "",
    affected_task: str = "",
    verification_sql: str = "",
    verification_result: str = "",
    actor: str = "OVERWATCH",
    approved_by: str = "",
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Return an insert into ALERT_REMEDIATION_LOG; callers still decide whether to execute."""
    action_type_clean = str(action_type or "").strip()
    if not action_type_clean:
        raise ValueError("Alert remediation log requires an action type.")
    mode = str(remediation_mode or "RECOMMEND").upper().replace(" ", "_")
    if mode in {"APPROVAL_REQUIRED", "VERIFICATION_REQUIRED"}:
        mode = "STATUS_REVIEW"
    if mode not in {"OFF", "RECOMMEND", "STATUS_REVIEW", "AUTO"}:
        mode = "RECOMMEND"
    approved_at_expr = "CURRENT_TIMESTAMP()" if str(approved_by or "").strip() else "NULL"
    approved_by_expr = f"NULLIF({sql_literal(approved_by, 200)}, '')"
    return f"""
INSERT INTO {_command_center_fqn("ALERT_REMEDIATION_LOG", db, schema)}
    (EVENT_ID, ALERT_KEY, REQUESTED_AT, REQUESTED_BY, APPROVED_AT, APPROVED_BY,
     REMEDIATION_MODE, ACTION_TYPE, ACTION_SQL, BEFORE_STATE, AFTER_STATE,
     EXECUTION_STATUS, ERROR_MESSAGE, ROLLBACK_GUIDANCE, AFFECTED_USER,
     AFFECTED_OBJECT, AFFECTED_WAREHOUSE, AFFECTED_TASK, VERIFICATION_SQL,
     VERIFICATION_RESULT)
SELECT
    {_alert_event_id_expr(event_id)} AS EVENT_ID,
    {sql_literal(alert_key, 200)} AS ALERT_KEY,
    CURRENT_TIMESTAMP() AS REQUESTED_AT,
    {sql_literal(actor, 200)} AS REQUESTED_BY,
    {approved_at_expr} AS APPROVED_AT,
    {approved_by_expr} AS APPROVED_BY,
    {sql_literal(mode, 40)} AS REMEDIATION_MODE,
    {sql_literal(action_type_clean, 100)} AS ACTION_TYPE,
    {sql_literal(action_sql, 16000)} AS ACTION_SQL,
    {sql_literal(before_state, 8000)} AS BEFORE_STATE,
    {sql_literal(after_state, 8000)} AS AFTER_STATE,
    {sql_literal(execution_status, 100)} AS EXECUTION_STATUS,
    {sql_literal(error_message, 4000)} AS ERROR_MESSAGE,
    {sql_literal(rollback_guidance, 4000)} AS ROLLBACK_GUIDANCE,
    NULLIF({sql_literal(affected_user, 300)}, '') AS AFFECTED_USER,
    NULLIF({sql_literal(affected_object, 500)}, '') AS AFFECTED_OBJECT,
    NULLIF({sql_literal(affected_warehouse, 300)}, '') AS AFFECTED_WAREHOUSE,
    NULLIF({sql_literal(affected_task, 500)}, '') AS AFFECTED_TASK,
    {sql_literal(verification_sql, 16000)} AS VERIFICATION_SQL,
    {sql_literal(verification_result, 8000)} AS VERIFICATION_RESULT;
""".strip()


def build_alert_event_materialization_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    *,
    days: int = 7,
) -> str:
    days = max(1, min(int(days or 7), 90))
    triage_view = alert_triage_view_fqn(db=db, schema=schema, quoted=True)
    events_table = _command_center_fqn("ALERT_EVENTS", db, schema)
    config_table = _command_center_fqn("ALERT_CONFIG", db, schema)
    run_table = _command_center_fqn("ALERT_RUN_HISTORY", db, schema)
    return f"""-- Materialize current Alert Center rows into durable alert lifecycle events.
-- Safe to schedule after OVERWATCH_ALERTS / OVERWATCH_ALERT_TRIAGE_V are populated.
SET OVERWATCH_ALERT_RUN_ID = 'ALERT_ENGINE_' || TO_VARCHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISS');

INSERT INTO {run_table}
  (RUN_ID, STARTED_AT, STATUS, DATA_WINDOW_START, DATA_WINDOW_END, TELEMETRY_LATENCY_NOTE)
VALUES
  ($OVERWATCH_ALERT_RUN_ID, CURRENT_TIMESTAMP(), 'RUNNING',
   DATEADD('day', -{days}, CURRENT_TIMESTAMP()), CURRENT_TIMESTAMP(),
   'ACCOUNT_USAGE-backed alerts may lag; near-real-time task/event-table checks should be configured separately.');

MERGE INTO {events_table} tgt
USING (
  SELECT
    COALESCE(NULLIF(a.ALERT_TYPE, ''), NULLIF(a.CATEGORY, ''), 'OVERWATCH_ALERT') AS ALERT_KEY,
    COALESCE(a.COMPANY, 'Shared/Unclassified') AS COMPANY,
    COALESCE(a.ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
    COALESCE(a.ALERT_TS, CURRENT_TIMESTAMP()) AS EVENT_TS,
    COALESCE(a.ALERT_TS, CURRENT_TIMESTAMP()) AS FIRST_SEEN_AT,
    CURRENT_TIMESTAMP() AS LAST_SEEN_AT,
    CURRENT_TIMESTAMP() AS DETECTED_AT,
    COALESCE(a.CATEGORY, 'Alert Center') AS CATEGORY,
    COALESCE(a.SEVERITY, cfg.DEFAULT_SEVERITY, 'Medium') AS SEVERITY,
    COALESCE(a.STATUS, 'New') AS STATUS,
    COALESCE(a.MESSAGE, a.DETAIL, a.ALERT_RUNBOOK, 'Alert Center event') AS BUSINESS_IMPACT,
    CASE
      WHEN UPPER(COALESCE(a.CATEGORY, '')) LIKE '%COST%' THEN 'Potential spend or contract burn impact'
      WHEN UPPER(COALESCE(a.CATEGORY, '')) LIKE '%SECURITY%' THEN 'Potential access, data exposure, or control-plane impact'
      WHEN UPPER(COALESCE(a.CATEGORY, a.ALERT_TYPE, '')) REGEXP 'TASK|PIPELINE|PROCEDURE' THEN 'Potential production pipeline SLA impact'
      ELSE 'Operational risk requires route triage'
    END AS IMPACT_ESTIMATE,
    COALESCE(a.ROUTED_OWNER, a.OWNER, cfg.OWNER, 'DBA') AS OWNER,
    COALESCE(a.SUGGESTED_ACTION, a.ALERT_RUNBOOK, 'Review alert telemetry and assign route.') AS RECOMMENDED_ACTION,
    CASE
      WHEN UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) LIKE '%TASK%' THEN 'TASK'
      WHEN UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) LIKE '%WAREHOUSE%' THEN 'WAREHOUSE'
      WHEN UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) LIKE '%USER%' THEN 'USER'
      ELSE 'ALERT'
    END AS ENTITY_TYPE,
    COALESCE(a.ENTITY_NAME, a.ENTITY, 'Snowflake account') AS ENTITY_NAME,
    a.WAREHOUSE_NAME,
    a.DATABASE_NAME,
    a.SCHEMA_NAME,
    a.PROOF_QUERY,
    COALESCE(cfg.REMEDIATION_MODE, 'RECOMMEND') AS REMEDIATION_MODE,
    COALESCE(a.MESSAGE, a.DETAIL, '') AS EVIDENCE,
    SHA2(
      COALESCE(NULLIF(a.ALERT_TYPE, ''), NULLIF(a.CATEGORY, ''), 'OVERWATCH_ALERT') || '|' ||
      COALESCE(a.ENTITY_NAME, a.ENTITY, 'Snowflake account') || '|' ||
      TO_VARCHAR(DATE_TRUNC('hour', COALESCE(a.ALERT_TS, CURRENT_TIMESTAMP()))) || '|' ||
      COALESCE(a.MESSAGE, a.DETAIL, ''),
      256
    ) AS DEDUPE_KEY,
    OBJECT_CONSTRUCT_KEEP_NULL(
      'ALERT_ID', a.ALERT_ID,
      'SLA_STATE', a.SLA_STATE,
      'ALERT_ROUTE', a.ALERT_ROUTE,
      'REVIEW_TARGET', a.REVIEW_TARGET
    ) AS RAW_EVENT
  FROM {triage_view} a
  LEFT JOIN {config_table} cfg
    ON UPPER(cfg.ALERT_KEY) = UPPER(COALESCE(NULLIF(a.ALERT_TYPE, ''), NULLIF(a.CATEGORY, ''), 'OVERWATCH_ALERT'))
  WHERE COALESCE(a.ALERT_TS, CURRENT_TIMESTAMP()) >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
) src
ON tgt.DEDUPE_KEY = src.DEDUPE_KEY
WHEN MATCHED THEN UPDATE SET
  LAST_SEEN_AT = src.LAST_SEEN_AT,
  COMPANY = src.COMPANY,
  ENVIRONMENT = src.ENVIRONMENT,
  STATUS = src.STATUS,
  SEVERITY = src.SEVERITY,
  OWNER = src.OWNER,
  RECOMMENDED_ACTION = src.RECOMMENDED_ACTION,
  EVIDENCE = src.EVIDENCE,
  RAW_EVENT = src.RAW_EVENT
WHEN NOT MATCHED THEN INSERT
  (ALERT_KEY, COMPANY, ENVIRONMENT, EVENT_TS, FIRST_SEEN_AT, LAST_SEEN_AT, DETECTED_AT, CATEGORY, SEVERITY, STATUS,
   BUSINESS_IMPACT, IMPACT_ESTIMATE, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, ENTITY_NAME,
   WAREHOUSE_NAME, DATABASE_NAME, SCHEMA_NAME, PROOF_QUERY, REMEDIATION_MODE, EVIDENCE, DEDUPE_KEY, RAW_EVENT)
VALUES
  (src.ALERT_KEY, src.COMPANY, src.ENVIRONMENT, src.EVENT_TS, src.FIRST_SEEN_AT, src.LAST_SEEN_AT, src.DETECTED_AT, src.CATEGORY, src.SEVERITY, src.STATUS,
   src.BUSINESS_IMPACT, src.IMPACT_ESTIMATE, src.OWNER, src.RECOMMENDED_ACTION, src.ENTITY_TYPE, src.ENTITY_NAME,
   src.WAREHOUSE_NAME, src.DATABASE_NAME, src.SCHEMA_NAME, src.PROOF_QUERY, src.REMEDIATION_MODE, src.EVIDENCE, src.DEDUPE_KEY, src.RAW_EVENT);

UPDATE {run_table}
SET COMPLETED_AT = CURRENT_TIMESTAMP(),
    STATUS = 'SUCCESS',
    ALERTS_EVALUATED = (SELECT COUNT(*) FROM {triage_view} WHERE COALESCE(ALERT_TS, CURRENT_TIMESTAMP()) >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())),
    ALERTS_CREATED = (SELECT COUNT(*) FROM {events_table} WHERE DETECTED_AT >= DATEADD('minute', -10, CURRENT_TIMESTAMP()))
WHERE RUN_ID = $OVERWATCH_ALERT_RUN_ID;
"""


def build_alert_command_center_setup_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """DDL for proactive alert monitoring configuration, event, and audit objects."""
    threshold_rows = build_alert_threshold_seed_rows()
    threshold_columns = [
        "THRESHOLD_KEY",
        "CATEGORY",
        "SIGNAL_NAME",
        "SEVERITY",
        "THRESHOLD_VALUE",
        "BASELINE_WINDOW_DAYS",
        "CURRENT_WINDOW_MINUTES",
        "OWNER",
        "NOTIFICATION_CHANNEL",
    ]
    threshold_values = _values_clause(threshold_rows, threshold_columns)
    config_values = _values_clause([
        {
            "ALERT_KEY": row["THRESHOLD_KEY"],
            "CATEGORY": row["CATEGORY"],
            "SIGNAL_NAME": row["SIGNAL_NAME"],
            "SEVERITY": row["SEVERITY"],
            "OWNER": row["OWNER"],
            "ROUTE": {
                "Security": "Security Posture",
                "Cost": "Cost & Contract",
                "Performance": "Workload Operations",
                "Task / Pipeline": "Workload Operations",
                "Data Quality": "Workload Operations",
                "Optimization": "Optimization Advisor",
            }.get(str(row["CATEGORY"]), "Alert Center"),
            "NOTIFICATION_CHANNEL": row["NOTIFICATION_CHANNEL"],
        }
        for row in threshold_rows
    ], [
        "ALERT_KEY",
        "CATEGORY",
        "SIGNAL_NAME",
        "SEVERITY",
        "OWNER",
        "ROUTE",
        "NOTIFICATION_CHANNEL",
    ])
    return f"""-- OVERWATCH Alert Monitoring
-- DBA-grade alert detection, acknowledgement, notification, and remediation audit contract.
-- ACCOUNT_USAGE views can lag; ALERT_CONFIG.TELEMETRY_LATENCY documents delayed vs near-real-time checks.

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_CONFIG", db, schema)} (
  ALERT_KEY                 VARCHAR(200) PRIMARY KEY,
  CATEGORY                  VARCHAR(100) NOT NULL,
  SIGNAL_NAME               VARCHAR(200) NOT NULL,
  DESCRIPTION               VARCHAR(4000),
  DEFAULT_SEVERITY          VARCHAR(20) DEFAULT 'Medium',
  ENABLED                   BOOLEAN DEFAULT TRUE,
  OWNER                     VARCHAR(200),
  ROUTE                     VARCHAR(200),
  BUSINESS_IMPACT_WEIGHT    NUMBER DEFAULT 50,
  DETECTION_SQL             VARCHAR(16000),
  TELEMETRY_SOURCE          VARCHAR(500),
  TELEMETRY_LATENCY         VARCHAR(200),
  NOTIFICATION_CHANNEL      VARCHAR(200),
  REMEDIATION_MODE          VARCHAR(40) DEFAULT 'RECOMMEND',
  DEDUPE_WINDOW_MINUTES     NUMBER DEFAULT 60,
  SUPPRESSION_WINDOW_MINUTES NUMBER DEFAULT 0,
  QUIET_HOURS_START         VARCHAR(20),
  QUIET_HOURS_END           VARCHAR(20),
  AUTO_RESOLVE_AFTER_HOURS  NUMBER DEFAULT 24,
  CREATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CREATED_BY                VARCHAR(200) DEFAULT CURRENT_USER(),
  UPDATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY                VARCHAR(200) DEFAULT CURRENT_USER()
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_THRESHOLDS", db, schema)} (
  THRESHOLD_KEY             VARCHAR(200) PRIMARY KEY,
  CATEGORY                  VARCHAR(100) NOT NULL,
  SIGNAL_NAME               VARCHAR(200) NOT NULL,
  SEVERITY                  VARCHAR(20) DEFAULT 'Medium',
  THRESHOLD_VALUE           FLOAT,
  BASELINE_WINDOW_DAYS      NUMBER DEFAULT 14,
  CURRENT_WINDOW_MINUTES    NUMBER DEFAULT 60,
  OWNER                     VARCHAR(200),
  NOTIFICATION_CHANNEL      VARCHAR(200),
  ENABLED                   BOOLEAN DEFAULT TRUE,
  UPDATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY                VARCHAR(200) DEFAULT CURRENT_USER()
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_EVENTS", db, schema)} (
  EVENT_ID                  NUMBER AUTOINCREMENT PRIMARY KEY,
  COMPANY                   VARCHAR(100),
  ENVIRONMENT               VARCHAR(100),
  ALERT_KEY                 VARCHAR(200),
  EVENT_TS                  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  FIRST_SEEN_AT             TIMESTAMP_NTZ,
  LAST_SEEN_AT              TIMESTAMP_NTZ,
  DETECTED_AT               TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  RESOLVED_AT               TIMESTAMP_NTZ,
  CATEGORY                  VARCHAR(100),
  SEVERITY                  VARCHAR(20),
  STATUS                    VARCHAR(40) DEFAULT 'New',
  BUSINESS_IMPACT           VARCHAR(4000),
  IMPACT_ESTIMATE           VARCHAR(1000),
  OWNER                     VARCHAR(200),
  RECOMMENDED_ACTION        VARCHAR(4000),
  ENTITY_TYPE               VARCHAR(100),
  ENTITY_NAME               VARCHAR(500),
  USER_NAME                 VARCHAR(300),
  ROLE_NAME                 VARCHAR(300),
  WAREHOUSE_NAME            VARCHAR(300),
  DATABASE_NAME             VARCHAR(300),
  SCHEMA_NAME               VARCHAR(300),
  OBJECT_NAME               VARCHAR(500),
  QUERY_ID                  VARCHAR(200),
  SOURCE_IP                 VARCHAR(200),
  BASELINE_VALUE            FLOAT,
  CURRENT_VALUE             FLOAT,
  THRESHOLD_VALUE           FLOAT,
  EVIDENCE                  VARCHAR(8000),
  PROOF_QUERY               VARCHAR(16000),
  REMEDIATION_MODE          VARCHAR(40) DEFAULT 'RECOMMEND',
  REMEDIATION_SQL           VARCHAR(16000),
  NOTIFICATION_STATUS       VARCHAR(100),
  DEDUPE_KEY                VARCHAR(500),
  RAW_EVENT                 VARIANT
);

ALTER TABLE IF EXISTS {_command_center_fqn("ALERT_EVENTS", db, schema)} ADD COLUMN IF NOT EXISTS COMPANY VARCHAR(100);
ALTER TABLE IF EXISTS {_command_center_fqn("ALERT_EVENTS", db, schema)} ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_RUN_HISTORY", db, schema)} (
  RUN_ID                    VARCHAR(200) PRIMARY KEY,
  STARTED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  COMPLETED_AT              TIMESTAMP_NTZ,
  STATUS                    VARCHAR(40),
  ALERTS_EVALUATED          NUMBER DEFAULT 0,
  ALERTS_CREATED            NUMBER DEFAULT 0,
  ALERTS_RESOLVED           NUMBER DEFAULT 0,
  ERROR_MESSAGE             VARCHAR(4000),
  DATA_WINDOW_START         TIMESTAMP_NTZ,
  DATA_WINDOW_END           TIMESTAMP_NTZ,
  TELEMETRY_LATENCY_NOTE    VARCHAR(2000),
  RUN_BY                    VARCHAR(200) DEFAULT CURRENT_USER()
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_ACKNOWLEDGEMENTS", db, schema)} (
  ACK_ID                    NUMBER AUTOINCREMENT PRIMARY KEY,
  EVENT_ID                  NUMBER,
  ALERT_KEY                 VARCHAR(200),
  ACKNOWLEDGED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  ACKNOWLEDGED_BY           VARCHAR(200) DEFAULT CURRENT_USER(),
  ACK_NOTE                  VARCHAR(4000),
  STATUS_AFTER_ACK          VARCHAR(40) DEFAULT 'Acknowledged',
  OWNER_ASSIGNED            VARCHAR(200),
  NEXT_CHECKPOINT_AT        TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_NOTIFICATION_LOG", db, schema)} (
  NOTIFICATION_ID           NUMBER AUTOINCREMENT PRIMARY KEY,
  EVENT_ID                  NUMBER,
  ALERT_KEY                 VARCHAR(200),
  NOTIFICATION_TS           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CHANNEL                   VARCHAR(200),
  DESTINATION               VARCHAR(500),
  SEVERITY                  VARCHAR(20),
  STATUS                    VARCHAR(100),
  DEDUPE_KEY                VARCHAR(500),
  ESCALATION_LEVEL          NUMBER DEFAULT 0,
  ERROR_MESSAGE             VARCHAR(4000),
  PAYLOAD                   VARIANT,
  SENT_BY                   VARCHAR(200) DEFAULT CURRENT_USER()
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_REMEDIATION_LOG", db, schema)} (
  REMEDIATION_ID            NUMBER AUTOINCREMENT PRIMARY KEY,
  EVENT_ID                  NUMBER,
  ALERT_KEY                 VARCHAR(200),
  REQUESTED_AT              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  REQUESTED_BY              VARCHAR(200) DEFAULT CURRENT_USER(),
  APPROVED_AT               TIMESTAMP_NTZ,
  APPROVED_BY               VARCHAR(200),
  REMEDIATION_MODE          VARCHAR(40),
  ACTION_TYPE               VARCHAR(100),
  ACTION_SQL                VARCHAR(16000),
  BEFORE_STATE              VARCHAR(8000),
  AFTER_STATE               VARCHAR(8000),
  EXECUTION_STATUS          VARCHAR(100),
  ERROR_MESSAGE             VARCHAR(4000),
  ROLLBACK_GUIDANCE         VARCHAR(4000),
  AFFECTED_USER             VARCHAR(300),
  AFFECTED_OBJECT           VARCHAR(500),
  AFFECTED_WAREHOUSE        VARCHAR(300),
  AFFECTED_TASK             VARCHAR(500),
  VERIFICATION_SQL          VARCHAR(16000),
  VERIFICATION_RESULT       VARCHAR(8000)
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_WORKFLOW_ROUTING", db, schema)} (
  ROUTE_KEY                 VARCHAR(200) PRIMARY KEY,
  CATEGORY                  VARCHAR(100),
  ENTITY_TYPE               VARCHAR(100),
  ENTITY_PATTERN            VARCHAR(500),
  OWNER_NAME                VARCHAR(200),
  ROUTE_EMAIL               VARCHAR(500),
  REVIEW_PRIMARY            VARCHAR(200),
  REVIEW_SECONDARY          VARCHAR(200),
  REVIEW_GROUP            VARCHAR(200),
  REVIEW_TARGET         VARCHAR(200),
  NOTIFICATION_CHANNEL      VARCHAR(200),
  SEVERITY_MIN              VARCHAR(20) DEFAULT 'Medium',
  SERVICE_TIER              VARCHAR(40) DEFAULT 'Tier 2',
  ACTIVE                    BOOLEAN DEFAULT TRUE,
  UPDATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY                VARCHAR(200) DEFAULT CURRENT_USER()
);

{build_alert_data_quality_checks_ddl(db=db, schema=schema).strip()}

{build_alert_native_registry_ddl(db=db, schema=schema).strip()}

{build_alert_remediation_policy_ddl(db=db, schema=schema).strip()}

{build_alert_native_deployment_review_sql(db=db, schema=schema).strip()}

MERGE INTO {_command_center_fqn("ALERT_THRESHOLDS", db, schema)} tgt
USING (
  SELECT * FROM VALUES
    {threshold_values}
) src({", ".join(threshold_columns)})
ON tgt.THRESHOLD_KEY = src.THRESHOLD_KEY
WHEN MATCHED THEN UPDATE SET
  CATEGORY = src.CATEGORY,
  SIGNAL_NAME = src.SIGNAL_NAME,
  SEVERITY = src.SEVERITY,
  THRESHOLD_VALUE = src.THRESHOLD_VALUE,
  BASELINE_WINDOW_DAYS = src.BASELINE_WINDOW_DAYS,
  CURRENT_WINDOW_MINUTES = src.CURRENT_WINDOW_MINUTES,
  OWNER = src.OWNER,
  NOTIFICATION_CHANNEL = src.NOTIFICATION_CHANNEL,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  ({", ".join(threshold_columns)})
VALUES
  ({", ".join("src." + column for column in threshold_columns)});

MERGE INTO {_command_center_fqn("ALERT_CONFIG", db, schema)} tgt
USING (
  SELECT * FROM VALUES
    {config_values}
) src(ALERT_KEY, CATEGORY, SIGNAL_NAME, DEFAULT_SEVERITY, OWNER, ROUTE, NOTIFICATION_CHANNEL)
ON tgt.ALERT_KEY = src.ALERT_KEY
WHEN MATCHED THEN UPDATE SET
  CATEGORY = src.CATEGORY,
  SIGNAL_NAME = src.SIGNAL_NAME,
  DEFAULT_SEVERITY = src.DEFAULT_SEVERITY,
  OWNER = src.OWNER,
  ROUTE = src.ROUTE,
  NOTIFICATION_CHANNEL = src.NOTIFICATION_CHANNEL,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  (ALERT_KEY, CATEGORY, SIGNAL_NAME, DEFAULT_SEVERITY, OWNER, ROUTE, NOTIFICATION_CHANNEL, TELEMETRY_LATENCY)
VALUES
  (src.ALERT_KEY, src.CATEGORY, src.SIGNAL_NAME, src.DEFAULT_SEVERITY, src.OWNER, src.ROUTE, src.NOTIFICATION_CHANNEL, 'ACCOUNT_USAGE delayed unless otherwise documented');
"""


def build_alert_signal_query_catalog(hours: int = 24) -> pd.DataFrame:
    """Return bounded, Snowflake-native detection query templates for the Alert Center."""
    hours = max(1, min(int(hours or 24), 168))
    rows = [
        {
            "CATEGORY": "Security",
            "SIGNAL": "Failed login spike",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY",
            "FRESHNESS": "Delayed ACCOUNT_USAGE telemetry",
            "OWNER": "DBA / Security",
            "WHY_THIS_MATTERS": "Password spray, stale automation secrets, or compromised users can show up before an incident ticket exists.",
            "RECOMMENDED_ACTION": "Group by user, source IP, client, error code, and country; lock down risky routes through IAM/security review.",
            "SQL": f"""
WITH recent AS (
  SELECT USER_NAME, CLIENT_IP, REPORTED_CLIENT_TYPE, ERROR_CODE, COUNT(*) AS FAILED_LOGINS
  FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
  WHERE EVENT_TIMESTAMP >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
    AND IS_SUCCESS = 'NO'
  GROUP BY 1,2,3,4
),
baseline AS (
  SELECT USER_NAME, AVG(DAILY_FAILS) AS AVG_DAILY_FAILS
  FROM (
    SELECT USER_NAME, DATE_TRUNC('day', EVENT_TIMESTAMP) AS EVENT_DAY, COUNT(*) AS DAILY_FAILS
    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
    WHERE EVENT_TIMESTAMP >= DATEADD('day', -14, CURRENT_TIMESTAMP())
      AND EVENT_TIMESTAMP < DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
      AND IS_SUCCESS = 'NO'
    GROUP BY 1,2
  )
  GROUP BY 1
)
SELECT 'SECURITY_FAILED_LOGIN_SPIKE' AS ALERT_KEY, 'Security' AS CATEGORY, 'High' AS SEVERITY,
       recent.USER_NAME AS ENTITY_NAME, recent.CLIENT_IP AS SOURCE_IP,
       FAILED_LOGINS AS CURRENT_VALUE, COALESCE(AVG_DAILY_FAILS, 0) AS BASELINE_VALUE,
       'Investigate failed login spike for user/IP/client.' AS RECOMMENDED_ACTION
FROM recent
LEFT JOIN baseline USING (USER_NAME)
WHERE FAILED_LOGINS >= GREATEST(10, COALESCE(AVG_DAILY_FAILS, 0) * 3)
ORDER BY FAILED_LOGINS DESC
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Security",
            "SIGNAL": "Privileged role grant or escalation",
            "SEVERITY": "Critical",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS / GRANTS_TO_ROLES",
            "FRESHNESS": "Delayed ACCOUNT_USAGE telemetry",
            "OWNER": "Security Review",
            "WHY_THIS_MATTERS": "ACCOUNTADMIN, SECURITYADMIN, SYSADMIN, or ORGADMIN expansion is a control-plane event, not a routine alert.",
            "RECOMMENDED_ACTION": "Check ticket/reviewer, user purpose, MFA posture, and review date before accepting the grant.",
            "SQL": f"""
SELECT 'SECURITY_PRIVILEGE_ESCALATION' AS ALERT_KEY, 'Security' AS CATEGORY, 'Critical' AS SEVERITY,
       GRANTEE_NAME AS ENTITY_NAME, ROLE AS ROLE_NAME, CREATED_ON AS EVENT_TS,
       GRANTED_BY, 'Privileged role grant requires review status and access review date.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
WHERE CREATED_ON >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND DELETED_ON IS NULL
  AND UPPER(ROLE) IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'ORGADMIN')
ORDER BY CREATED_ON DESC
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Security",
            "SIGNAL": "Sensitive access or large unload",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY + QUERY_HISTORY",
            "FRESHNESS": "Delayed ACCOUNT_USAGE telemetry",
            "OWNER": "DBA / Security",
            "WHY_THIS_MATTERS": "Large exports and spikes against sensitive tables are early signs of data loss or security drift.",
            "RECOMMENDED_ACTION": "Confirm business purpose, destination stage, role used, masking policy coverage, and downstream status.",
            "SQL": f"""
SELECT 'SECURITY_SENSITIVE_EXPORT' AS ALERT_KEY, 'Security' AS CATEGORY, 'High' AS SEVERITY,
       q.USER_NAME AS ENTITY_NAME, q.ROLE_NAME, q.WAREHOUSE_NAME, q.QUERY_ID,
       q.START_TIME AS EVENT_TS, q.BYTES_SCANNED AS CURRENT_VALUE,
       LEFT(q.QUERY_TEXT, 500) AS EVIDENCE,
       'Review query text, destination stage, access history objects, and status.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
WHERE q.START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND (q.QUERY_TEXT ILIKE 'COPY INTO @%' OR q.QUERY_TEXT ILIKE '%COPY INTO @%')
ORDER BY q.BYTES_SCANNED DESC NULLS LAST
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Cost",
            "SIGNAL": "Warehouse credit spike vs baseline",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
            "FRESHNESS": "Finalized metering windows can lag",
            "OWNER": "DBA / Cost attribution",
            "WHY_THIS_MATTERS": "Warehouse metering is the official compute source of truth; spikes need route, workload, and contract-burn context.",
            "RECOMMENDED_ACTION": "Compare current credits to 30-day baseline, then inspect query drivers and warehouse setting changes.",
            "SQL": f"""
WITH current_window AS (
  SELECT WAREHOUSE_NAME, SUM(CREDITS_USED) AS CURRENT_CREDITS
  FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
  WHERE START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  GROUP BY 1
),
baseline AS (
  SELECT WAREHOUSE_NAME, AVG(DAILY_CREDITS) AS BASELINE_DAILY_CREDITS
  FROM (
    SELECT WAREHOUSE_NAME, DATE_TRUNC('day', START_TIME) AS USAGE_DAY, SUM(CREDITS_USED) AS DAILY_CREDITS
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
      AND START_TIME < DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
    GROUP BY 1,2
  )
  GROUP BY 1
)
SELECT 'COST_WAREHOUSE_CREDIT_SPIKE' AS ALERT_KEY, 'Cost' AS CATEGORY, 'High' AS SEVERITY,
       current_window.WAREHOUSE_NAME AS ENTITY_NAME,
       CURRENT_CREDITS AS CURRENT_VALUE, COALESCE(BASELINE_DAILY_CREDITS, 0) AS BASELINE_VALUE,
       'Explain warehouse credit spike with official metering and top query drivers.' AS RECOMMENDED_ACTION
FROM current_window
LEFT JOIN baseline USING (WAREHOUSE_NAME)
WHERE CURRENT_CREDITS > GREATEST(10, COALESCE(BASELINE_DAILY_CREDITS, 0) * 1.5)
ORDER BY CURRENT_CREDITS DESC
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Cost",
            "SIGNAL": "Cortex spend spike and quota drift",
            "SEVERITY": "High",
            "TELEMETRY": "FACT_CORTEX_DAILY plus Cortex ACCOUNT_USAGE views",
            "FRESHNESS": "Cortex facts are task-loaded; raw Cortex ACCOUNT_USAGE views can lag or be unavailable by feature",
            "OWNER": "DBA / AI cost route",
            "WHY_THIS_MATTERS": "Cortex usage can grow from user behavior, shared advice, or new features before normal warehouse cost controls catch it.",
            "RECOMMENDED_ACTION": "Review top Cortex users, request sources, 7-day cost, quota settings, grants, and whether usage belongs to ALFA or Trexis.",
            "SQL": f"""
WITH recent AS (
  SELECT USER_ID, SOURCE, SUM(EST_COST_USD) AS CURRENT_VALUE, SUM(REQUEST_COUNT) AS REQUESTS
  FROM FACT_CORTEX_DAILY
  WHERE USAGE_DATE >= DATEADD('day', -7, CURRENT_DATE())
  GROUP BY 1,2
),
baseline AS (
  SELECT USER_ID, SOURCE, AVG(DAILY_COST_USD) AS BASELINE_VALUE
  FROM (
    SELECT USER_ID, SOURCE, USAGE_DATE, SUM(EST_COST_USD) AS DAILY_COST_USD
    FROM FACT_CORTEX_DAILY
    WHERE USAGE_DATE >= DATEADD('day', -37, CURRENT_DATE())
      AND USAGE_DATE < DATEADD('day', -7, CURRENT_DATE())
    GROUP BY 1,2,3
  )
  GROUP BY 1,2
)
SELECT 'CORTEX_SPEND_AND_QUOTA' AS ALERT_KEY, 'Cost' AS CATEGORY, 'High' AS SEVERITY,
       COALESCE(recent.USER_ID, 'CORTEX') AS ENTITY_NAME,
       recent.SOURCE, recent.CURRENT_VALUE, COALESCE(baseline.BASELINE_VALUE, 0) AS BASELINE_VALUE,
       recent.REQUESTS,
       'Review Cortex user/source spend, quota settings, grants, and route before enforcing controls.' AS RECOMMENDED_ACTION
FROM recent
LEFT JOIN baseline USING (USER_ID, SOURCE)
WHERE recent.CURRENT_VALUE > GREATEST(25, COALESCE(baseline.BASELINE_VALUE, 0) * 1.5)
ORDER BY recent.CURRENT_VALUE DESC
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Performance",
            "SIGNAL": "Queue, spill, blocking, and long-running query pressure",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY / INFORMATION_SCHEMA.QUERY_HISTORY",
            "FRESHNESS": "Use INFORMATION_SCHEMA for near-real-time triage; ACCOUNT_USAGE for historical baseline",
            "OWNER": "DBA / Platform",
            "WHY_THIS_MATTERS": "Queueing, remote spill, and lock waits are the difference between noisy SQL and production contention.",
            "RECOMMENDED_ACTION": "Open Query Investigation or Performance & Contention with the exact query_id and warehouse telemetry.",
            "SQL": f"""
SELECT 'PERF_QUERY_PRESSURE' AS ALERT_KEY, 'Performance' AS CATEGORY,
       CASE WHEN COALESCE(TRANSACTION_BLOCKED_TIME, 0) > 0 THEN 'Critical' ELSE 'High' END AS SEVERITY,
       QUERY_ID, USER_NAME, ROLE_NAME, WAREHOUSE_NAME, DATABASE_NAME, SCHEMA_NAME,
       TOTAL_ELAPSED_TIME AS CURRENT_VALUE,
       QUEUED_PROVISIONING_TIME + QUEUED_REPAIR_TIME + QUEUED_OVERLOAD_TIME AS QUEUE_MS,
       TRANSACTION_BLOCKED_TIME AS BLOCKED_MS,
       BYTES_SPILLED_TO_REMOTE_STORAGE,
       LEFT(QUERY_TEXT, 500) AS EVIDENCE,
       'Review warehouse pressure, query plan, lock route, pruning, spill, and status result.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND (
    TOTAL_ELAPSED_TIME > 1800000
    OR COALESCE(TRANSACTION_BLOCKED_TIME, 0) > 0
    OR COALESCE(BYTES_SPILLED_TO_REMOTE_STORAGE, 0) > 0
    OR (COALESCE(QUEUED_PROVISIONING_TIME, 0) + COALESCE(QUEUED_REPAIR_TIME, 0) + COALESCE(QUEUED_OVERLOAD_TIME, 0)) > 300000
  )
ORDER BY TOTAL_ELAPSED_TIME DESC
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Task / Pipeline",
            "SIGNAL": "Failed, skipped, late, or long-running task graph",
            "SEVERITY": "Critical",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY and event tables when configured",
            "FRESHNESS": "ACCOUNT_USAGE delayed; task graph error notifications can be near-real-time when configured",
            "OWNER": "DBA / Pipeline Route",
            "WHY_THIS_MATTERS": "Snowflake pipeline reliability depends on task graphs having SLA, failure, retry, and route telemetry.",
            "RECOMMENDED_ACTION": "Identify root task, failed child, error signature, retry count, last success, and downstream SLA risk before rerun.",
            "SQL": f"""
SELECT 'PIPELINE_TASK_FAILURE' AS ALERT_KEY, 'Task / Pipeline' AS CATEGORY, 'Critical' AS SEVERITY,
       DATABASE_NAME, SCHEMA_NAME, NAME AS ENTITY_NAME, ROOT_TASK_ID,
       STATE, SCHEDULED_TIME AS EVENT_TS, COMPLETED_TIME, QUERY_ID, ERROR_CODE, ERROR_MESSAGE,
       'Open task graph, isolate failed child/root task, confirm route and safe rerun conditions.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE SCHEDULED_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'SKIPPED', 'CANCELLED')
ORDER BY SCHEDULED_TIME DESC
LIMIT 200;
""".strip(),
        },
        {
            "CATEGORY": "Task / Pipeline",
            "SIGNAL": "COPY load failures",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY",
            "FRESHNESS": "Optional ACCOUNT_USAGE view; depends on account edition and grants",
            "OWNER": "DBA / Data Engineering",
            "WHY_THIS_MATTERS": "Load failures and late data are often the earliest visible pipeline incident.",
            "RECOMMENDED_ACTION": "Group by table/stage/error and confirm whether the downstream task graph is stale or blocked.",
            "SQL": f"""
SELECT 'PIPELINE_COPY_FAILURE' AS ALERT_KEY, 'Task / Pipeline' AS CATEGORY, 'High' AS SEVERITY,
       TABLE_CATALOG || '.' || TABLE_SCHEMA || '.' || TABLE_NAME AS ENTITY_NAME,
       LAST_LOAD_TIME AS EVENT_TS, FILE_NAME, STATUS, ERROR_COUNT AS CURRENT_VALUE,
       FIRST_ERROR_MESSAGE AS EVIDENCE,
       'Fix load error, validate file format/stage permissions, and confirm downstream freshness SLA.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
WHERE LAST_LOAD_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND UPPER(COALESCE(STATUS, '')) NOT IN ('LOADED')
ORDER BY LAST_LOAD_TIME DESC
LIMIT 200;
""".strip(),
        },
        {
            "CATEGORY": "Task / Pipeline",
            "SIGNAL": "Dynamic table refresh failure or lag",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY",
            "FRESHNESS": "Optional ACCOUNT_USAGE view; use only when dynamic tables exist and grants expose it",
            "OWNER": "DBA / Data Engineering",
            "WHY_THIS_MATTERS": "Dynamic table lag can create freshness incidents without an obvious failed task row.",
            "RECOMMENDED_ACTION": "Compare target lag, refresh state, error text, upstream task/query pressure, and downstream SLA.",
            "SQL": f"""
SELECT 'PIPELINE_DYNAMIC_TABLE_REFRESH' AS ALERT_KEY, 'Task / Pipeline' AS CATEGORY, 'High' AS SEVERITY,
       DATABASE_NAME || '.' || SCHEMA_NAME || '.' || NAME AS ENTITY_NAME,
       REFRESH_START_TIME AS EVENT_TS, STATE, STATE_CODE, ERROR_MESSAGE,
       'Review dynamic table refresh history, target lag, upstream query pressure, and downstream SLA.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY
WHERE REFRESH_START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND UPPER(COALESCE(STATE, '')) NOT IN ('SUCCEEDED', 'SUCCESS')
ORDER BY REFRESH_START_TIME DESC
LIMIT 200;
""".strip(),
        },
        {
            "CATEGORY": "Data Quality",
            "SIGNAL": "Metadata-driven data quality check failed",
            "SEVERITY": "High",
            "TELEMETRY": "ALERT_CONFIG / ALERT_THRESHOLDS plus table metadata checks",
            "FRESHNESS": "Near-real-time if the configured query targets INFORMATION_SCHEMA or live table metadata",
            "OWNER": "Data Route",
            "WHY_THIS_MATTERS": "Freshness, volume, null, duplicate, and schema drift checks need route-tunable thresholds without code changes.",
            "RECOMMENDED_ACTION": "Configure table/column/check/threshold/route in ALERT_CONFIG or ALERT_THRESHOLDS, then route failures to the data route.",
            "SQL": f"""
SELECT 'DQ_CONFIG_REQUIRED' AS ALERT_KEY, 'Data Quality' AS CATEGORY, 'Medium' AS SEVERITY,
       ALERT_KEY AS ENTITY_NAME, CATEGORY || ': ' || SIGNAL_NAME AS EVIDENCE,
       'Define database/schema/table/column/check type/threshold/route before enabling data-quality alerts.' AS RECOMMENDED_ACTION
FROM {_command_center_fqn("ALERT_CONFIG")}
WHERE CATEGORY = 'Data Quality'
  AND ENABLED
  AND COALESCE(DETECTION_SQL, '') = ''
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Optimization",
            "SIGNAL": "Warehouse sizing, auto-suspend, unused objects, and repeated expensive query candidates",
            "SEVERITY": "Medium",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES / QUERY_HISTORY / TABLES",
            "FRESHNESS": "Delayed ACCOUNT_USAGE telemetry",
            "OWNER": "DBA / Cost attribution",
            "WHY_THIS_MATTERS": "Optimization alerts should be telemetry-ranked candidates, not generic tune-the-query advice.",
            "RECOMMENDED_ACTION": "Route only with before/after telemetry, review status, rollback path, and expected savings or reliability gain.",
            "SQL": f"""
SELECT 'OPT_WAREHOUSE_AUTOSUSPEND' AS ALERT_KEY, 'Optimization' AS CATEGORY, 'Medium' AS SEVERITY,
       WAREHOUSE_NAME AS ENTITY_NAME, AUTO_SUSPEND AS CURRENT_VALUE,
       'Warehouse auto-suspend setting may be too high or disabled.' AS EVIDENCE,
       'Validate workload class, route SLA, queue/spill baseline, and changed-only warehouse setting recommendation.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES
WHERE DELETED IS NULL
  AND (AUTO_SUSPEND IS NULL OR AUTO_SUSPEND > 600)
ORDER BY AUTO_SUSPEND DESC NULLS FIRST
LIMIT 100;
""".strip(),
        },
    ]
    return pd.DataFrame(rows)


def build_alert_required_privileges() -> pd.DataFrame:
    rows = [
        ("Imported privileges on SNOWFLAKE database", "ACCOUNT_USAGE views: QUERY_HISTORY, WAREHOUSE_METERING_HISTORY, LOGIN_HISTORY, ACCESS_HISTORY, TASK_HISTORY, ALERT_HISTORY, GRANTS views"),
        ("USAGE on monitored databases/schemas", "INFORMATION_SCHEMA checks and task/pipe metadata where ACCOUNT_USAGE lag is too slow"),
        ("SELECT on OVERWATCH schema tables", "ALERT_CONFIG, ALERT_EVENTS, ALERT_THRESHOLDS, ALERT_WORKFLOW_ROUTING, notification/remediation logs"),
        ("OPERATE for reviewed remediation", "Only needed for reviewed task/warehouse/query/user actions; detection works without it"),
        ("Notification integration usage", "Only needed when sending Snowflake email/webhook/cloud notifications from procedures or alerts"),
    ]
    return pd.DataFrame(rows, columns=["PRIVILEGE_ASSUMPTION", "WHY_REQUIRED"])


def build_alert_optional_integrations() -> pd.DataFrame:
    rows = [
        ("Snowflake ALERT objects", "Periodic condition evaluation and SQL action execution", "Recommended for reviewed scheduled detection"),
        ("Email notification integration", "SYSTEM$SEND_EMAIL alert digests and escalations", "Optional but useful for DBA review"),
        ("Webhook / Slack / Teams integration", "External routing when account and network policies allow it", "Optional; keep payloads logged"),
        ("Event tables with LOG_LEVEL >= ERROR", "Task graph and stored procedure error events", "Recommended for near-real-time pipeline failures"),
        ("Status/Snowflake task bridge", "Incident tickets, route assignment, workflow handoff", "Optional; use action queue until reviewed"),
    ]
    return pd.DataFrame(rows, columns=["INTEGRATION", "CAPABILITY", "STATUS_NOTE"])



def build_alert_command_center_runbook_markdown() -> str:
    return """# OVERWATCH Alert Monitoring Runbook

## Operating Rule
The Alert Center is a triage and monitoring surface. It should detect, prioritize, route, notify, and audit. It should not silently mutate Snowflake objects.

## Severity
- CRITICAL: security breach risk, runaway spend, failed production pipeline, disabled controls, privilege escalation, repeated task failures.
- HIGH: major cost/performance anomaly, warehouse saturation, excessive queueing, blocked work, failed important job.
- MEDIUM: optimization opportunity, suspicious behavior, growing costs, route gaps.
- LOW: informational or early warning.

## Daily DBA Flow
1. Open DBA Daily Brief and work Critical/High rows first.
2. Check Security, Cost, Performance, and Pipeline categories before optimization work.
3. Use telemetry status and bounded detail before declaring an incident.
4. Acknowledge or suppress planned work with a telemetry note.
5. Route status-backed actions to the action queue with ticket, telemetry SQL, and closure status.

## Telemetry Status
ACCOUNT_USAGE views are authoritative for history but can lag. Use INFORMATION_SCHEMA table functions, task graph notifications, Snowflake ALERT objects, and event tables for near-real-time incident checks where available.

## Remediation Policy
Default mode is RECOMMEND. AUTO is allowed only for safe, explicitly reviewed actions. Dangerous operations such as cancel query, revoke grant, disable user, alter warehouse, resume task, or suspend warehouse require status review and ALERT_REMEDIATION_LOG telemetry.
"""
