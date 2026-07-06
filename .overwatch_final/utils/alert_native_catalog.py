"""Native alert, data-quality, and remediation catalog helpers.

This module owns the generated SQL and metadata loaders for native Snowflake
alert candidates, DBA-managed threshold/data-quality configuration, and
review-only remediation policy/dry-run objects. Runtime triage, delivery, rule
catalogs, and action-queue routing remain in focused sibling modules.
"""
from __future__ import annotations

import pandas as pd

from config import ALERT_DB, ALERT_SCHEMA
from .query import run_query, safe_identifier, sql_literal


ALERT_DATA_QUALITY_CHECK_TABLE = "ALERT_DATA_QUALITY_CHECKS"
ALERT_NATIVE_OBJECT_REGISTRY_TABLE = "ALERT_NATIVE_OBJECT_REGISTRY"
ALERT_REMEDIATION_POLICY_TABLE = "ALERT_REMEDIATION_POLICY"
ALERT_REMEDIATION_DRY_RUN_TABLE = "ALERT_REMEDIATION_DRY_RUN"


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


def build_alert_threshold_seed_rows() -> list[dict[str, object]]:
    """Default alert thresholds used to seed the DBA-owned configuration table."""
    return [
        {
            "THRESHOLD_KEY": "SECURITY_FAILED_LOGIN_SPIKE",
            "CATEGORY": "Security",
            "SIGNAL_NAME": "Failed login spike",
            "SEVERITY": "High",
            "THRESHOLD_VALUE": 10,
            "BASELINE_WINDOW_DAYS": 14,
            "CURRENT_WINDOW_MINUTES": 60,
            "OWNER": "DBA / Security",
            "NOTIFICATION_CHANNEL": "DBA_SECURITY",
        },
        {
            "THRESHOLD_KEY": "SECURITY_PRIVILEGE_ESCALATION",
            "CATEGORY": "Security",
            "SIGNAL_NAME": "Privileged role grant",
            "SEVERITY": "Critical",
            "THRESHOLD_VALUE": 1,
            "BASELINE_WINDOW_DAYS": 7,
            "CURRENT_WINDOW_MINUTES": 1440,
            "OWNER": "Security Review",
            "NOTIFICATION_CHANNEL": "DBA_SECURITY",
        },
        {
            "THRESHOLD_KEY": "COST_WAREHOUSE_CREDIT_SPIKE",
            "CATEGORY": "Cost",
            "SIGNAL_NAME": "Warehouse credit spike",
            "SEVERITY": "High",
            "THRESHOLD_VALUE": 1.5,
            "BASELINE_WINDOW_DAYS": 30,
            "CURRENT_WINDOW_MINUTES": 1440,
            "OWNER": "DBA / Cost owner",
            "NOTIFICATION_CHANNEL": "COST",
        },
        {
            "THRESHOLD_KEY": "COST_CORTEX_SPEND_SPIKE",
            "CATEGORY": "Cost",
            "SIGNAL_NAME": "Cortex spend spike",
            "SEVERITY": "High",
            "THRESHOLD_VALUE": 25,
            "BASELINE_WINDOW_DAYS": 30,
            "CURRENT_WINDOW_MINUTES": 10080,
            "OWNER": "DBA / AI cost route",
            "NOTIFICATION_CHANNEL": "COST",
        },
        {
            "THRESHOLD_KEY": "BEHAVIOR_USER_QUERY_ANOMALY",
            "CATEGORY": "Behavior",
            "SIGNAL_NAME": "User query behavior anomaly",
            "SEVERITY": "High",
            "THRESHOLD_VALUE": 10,
            "BASELINE_WINDOW_DAYS": 14,
            "CURRENT_WINDOW_MINUTES": 120,
            "OWNER": "DBA / Workload reviewer",
            "NOTIFICATION_CHANNEL": "DBA_ONCALL",
        },
        {
            "THRESHOLD_KEY": "PERF_QUEUE_PRESSURE",
            "CATEGORY": "Performance",
            "SIGNAL_NAME": "Warehouse queue pressure",
            "SEVERITY": "High",
            "THRESHOLD_VALUE": 300,
            "BASELINE_WINDOW_DAYS": 14,
            "CURRENT_WINDOW_MINUTES": 60,
            "OWNER": "DBA / Platform",
            "NOTIFICATION_CHANNEL": "DBA_ONCALL",
        },
        {
            "THRESHOLD_KEY": "PIPELINE_TASK_FAILURE",
            "CATEGORY": "Task / Pipeline",
            "SIGNAL_NAME": "Production task failure",
            "SEVERITY": "Critical",
            "THRESHOLD_VALUE": 1,
            "BASELINE_WINDOW_DAYS": 7,
            "CURRENT_WINDOW_MINUTES": 1440,
            "OWNER": "DBA / Pipeline Route",
            "NOTIFICATION_CHANNEL": "PIPELINE_ONCALL",
        },
        {
            "THRESHOLD_KEY": "DQ_FRESHNESS_SLA",
            "CATEGORY": "Data Quality",
            "SIGNAL_NAME": "Freshness SLA missed",
            "SEVERITY": "High",
            "THRESHOLD_VALUE": 1,
            "BASELINE_WINDOW_DAYS": 7,
            "CURRENT_WINDOW_MINUTES": 1440,
            "OWNER": "Data Route",
            "NOTIFICATION_CHANNEL": "DATA_QUALITY",
        },
        {
            "THRESHOLD_KEY": "OPT_UNUSED_WAREHOUSE",
            "CATEGORY": "Optimization",
            "SIGNAL_NAME": "Unused or oversized warehouse",
            "SEVERITY": "Medium",
            "THRESHOLD_VALUE": 14,
            "BASELINE_WINDOW_DAYS": 30,
            "CURRENT_WINDOW_MINUTES": 1440,
            "OWNER": "DBA / Cost owner",
            "NOTIFICATION_CHANNEL": "COST",
        },
    ]


def build_alert_data_quality_check_seed_rows() -> list[dict[str, object]]:
    """Starter metadata-driven data-quality checks for DBA-managed configuration."""
    return [
        {
            "CHECK_KEY": "DQ_ORDER_FRESHNESS",
            "DATABASE_NAME": "ALFA_EDW_PRD",
            "SCHEMA_NAME": "CURATED",
            "TABLE_NAME": "FACT_ORDER",
            "COLUMN_NAME": "LOAD_TS",
            "CHECK_TYPE": "FRESHNESS_SLA_HOURS",
            "THRESHOLD_VALUE": 24,
            "COMPARISON_OPERATOR": ">",
            "SEVERITY": "High",
            "OWNER": "Data Route",
            "NOTIFICATION_CHANNEL": "DATA_QUALITY",
            "ENABLED": False,
        },
        {
            "CHECK_KEY": "DQ_POLICY_NULL_RATE",
            "DATABASE_NAME": "ALFA_EDW_PRD",
            "SCHEMA_NAME": "CURATED",
            "TABLE_NAME": "DIM_POLICY",
            "COLUMN_NAME": "POLICY_ID",
            "CHECK_TYPE": "NULL_RATE_PCT",
            "THRESHOLD_VALUE": 0,
            "COMPARISON_OPERATOR": ">",
            "SEVERITY": "Critical",
            "OWNER": "Data Route",
            "NOTIFICATION_CHANNEL": "DATA_QUALITY",
            "ENABLED": False,
        },
        {
            "CHECK_KEY": "DQ_CLAIM_VOLUME_DROP",
            "DATABASE_NAME": "ALFA_EDW_PRD",
            "SCHEMA_NAME": "CURATED",
            "TABLE_NAME": "FACT_CLAIM",
            "COLUMN_NAME": "*",
            "CHECK_TYPE": "ROW_COUNT_DROP_PCT",
            "THRESHOLD_VALUE": 35,
            "COMPARISON_OPERATOR": ">",
            "SEVERITY": "High",
            "OWNER": "Data Route",
            "NOTIFICATION_CHANNEL": "DATA_QUALITY",
            "ENABLED": False,
        },
    ]


def _values_clause(rows: list[dict[str, object]], columns: list[str]) -> str:
    values = []
    for row in rows:
        values.append("(" + ", ".join(sql_literal(row.get(column, ""), 4000) if isinstance(row.get(column, ""), str) else str(row.get(column, "NULL")) for column in columns) + ")")
    return ",\n    ".join(values)


def build_alert_data_quality_checks_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    rows = build_alert_data_quality_check_seed_rows()
    columns = [
        "CHECK_KEY",
        "DATABASE_NAME",
        "SCHEMA_NAME",
        "TABLE_NAME",
        "COLUMN_NAME",
        "CHECK_TYPE",
        "THRESHOLD_VALUE",
        "COMPARISON_OPERATOR",
        "SEVERITY",
        "OWNER",
        "NOTIFICATION_CHANNEL",
        "ENABLED",
    ]
    return f"""CREATE TABLE IF NOT EXISTS {_command_center_fqn(ALERT_DATA_QUALITY_CHECK_TABLE, db, schema)} (
  CHECK_KEY            VARCHAR(200) PRIMARY KEY,
  DATABASE_NAME        VARCHAR(300) NOT NULL,
  SCHEMA_NAME          VARCHAR(300) NOT NULL,
  TABLE_NAME           VARCHAR(300) NOT NULL,
  COLUMN_NAME          VARCHAR(300) DEFAULT '*',
  CHECK_TYPE           VARCHAR(100) NOT NULL,
  THRESHOLD_VALUE      FLOAT,
  COMPARISON_OPERATOR  VARCHAR(20) DEFAULT '>',
  SEVERITY             VARCHAR(20) DEFAULT 'Medium',
  OWNER                VARCHAR(200),
  NOTIFICATION_CHANNEL VARCHAR(200),
  ENABLED              BOOLEAN DEFAULT FALSE,
  FRESHNESS_COLUMN     VARCHAR(300),
  KEY_COLUMNS          VARCHAR(1000),
  FILTER_SQL           VARCHAR(4000),
  BUSINESS_IMPACT      VARCHAR(4000),
  UPDATED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY           VARCHAR(200) DEFAULT CURRENT_USER()
);

MERGE INTO {_command_center_fqn(ALERT_DATA_QUALITY_CHECK_TABLE, db, schema)} tgt
USING (
  SELECT * FROM VALUES
    {_values_clause(rows, columns)}
) src({", ".join(columns)})
ON tgt.CHECK_KEY = src.CHECK_KEY
WHEN MATCHED THEN UPDATE SET
  DATABASE_NAME = src.DATABASE_NAME,
  SCHEMA_NAME = src.SCHEMA_NAME,
  TABLE_NAME = src.TABLE_NAME,
  COLUMN_NAME = src.COLUMN_NAME,
  CHECK_TYPE = src.CHECK_TYPE,
  THRESHOLD_VALUE = src.THRESHOLD_VALUE,
  COMPARISON_OPERATOR = src.COMPARISON_OPERATOR,
  SEVERITY = src.SEVERITY,
  OWNER = src.OWNER,
  NOTIFICATION_CHANNEL = src.NOTIFICATION_CHANNEL,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  ({", ".join(columns)})
VALUES
  ({", ".join("src." + column for column in columns)});
"""


def build_alert_native_object_registry_seed_rows(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> list[dict[str, object]]:
    """Return approved native Snowflake ALERT candidates without enabling them."""
    event_table = _command_center_fqn("ALERT_EVENTS", db, schema)
    return [
        {
            "REGISTRY_KEY": "NATIVE_COST_CORTEX_SPEND_SPIKE",
            "ALERT_KEY": "COST_CORTEX_SPEND_SPIKE",
            "CATEGORY": "Cost",
            "ALERT_OBJECT_NAME": "OVERWATCH_ALERT_CORTEX_SPEND_SPIKE",
            "TARGET_ROUTE": "Cost & Contract",
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "SCHEDULE_TEXT": "60 MINUTE",
            "STATUS": "CANDIDATE",
            "CONDITION_SOURCE": "FACT_CORTEX_DAILY company-labeled 7-day spend vs shared threshold",
            "ACTION_SOURCE": "Insert recommend-only event into ALERT_EVENTS",
            "GENERATED_CREATE_SQL": f"""CREATE OR REPLACE ALERT OVERWATCH_ALERT_CORTEX_SPEND_SPIKE
  WAREHOUSE = WH_ALFA_OVERWATCH
  SCHEDULE = '60 MINUTE'
  IF (EXISTS (
    SELECT 1
    FROM FACT_CORTEX_DAILY
    WHERE USAGE_DATE >= DATEADD('day', -7, CURRENT_DATE())
    GROUP BY COMPANY
    HAVING SUM(EST_COST_USD) > 25
  ))
  THEN INSERT INTO {event_table}
    (COMPANY, ENVIRONMENT, ALERT_KEY, CATEGORY, SEVERITY, STATUS, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, ENTITY_NAME, CURRENT_VALUE, REMEDIATION_MODE, EVIDENCE, DEDUPE_KEY)
    SELECT COALESCE(COMPANY, 'Account-Wide'), 'ALL', 'COST_CORTEX_SPEND_SPIKE', 'Cost', 'High', 'New', 'DBA / AI cost route',
           'Review Cortex user/source spend, quota settings, grants, and company scope before changing access.',
           'CORTEX', 'CORTEX', SUM(EST_COST_USD), 'RECOMMEND',
           'Native candidate detected Cortex spend above threshold.',
           SHA2('COST_CORTEX_SPEND_SPIKE|' || COALESCE(COMPANY, 'Account-Wide') || '|' || TO_VARCHAR(CURRENT_DATE()), 256)
    FROM FACT_CORTEX_DAILY
    WHERE USAGE_DATE >= DATEADD('day', -7, CURRENT_DATE())
    GROUP BY COMPANY
    HAVING SUM(EST_COST_USD) > 25;""",
            "GENERATED_DROP_SQL": "DROP ALERT IF EXISTS OVERWATCH_ALERT_CORTEX_SPEND_SPIKE;",
            "ENABLED_BY_DEFAULT": False,
            "SAFETY_NOTE": "Recommend-only. Do not alter Cortex access automatically.",
        },
        {
            "REGISTRY_KEY": "NATIVE_COST_WAREHOUSE_CREDIT_SPIKE",
            "ALERT_KEY": "COST_WAREHOUSE_CREDIT_SPIKE",
            "CATEGORY": "Cost",
            "ALERT_OBJECT_NAME": "OVERWATCH_ALERT_WAREHOUSE_CREDIT_SPIKE",
            "TARGET_ROUTE": "Cost & Contract",
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "SCHEDULE_TEXT": "60 MINUTE",
            "STATUS": "CANDIDATE",
            "CONDITION_SOURCE": "FACT_WAREHOUSE_HOURLY company-labeled current-day CREDITS_USED vs 30-day baseline",
            "ACTION_SOURCE": "Insert recommend-only cost movement event into ALERT_EVENTS",
            "GENERATED_CREATE_SQL": f"""CREATE OR REPLACE ALERT OVERWATCH_ALERT_WAREHOUSE_CREDIT_SPIKE
  WAREHOUSE = WH_ALFA_OVERWATCH
  SCHEDULE = '60 MINUTE'
  IF (EXISTS (
    WITH current_window AS (
      SELECT COMPANY, WAREHOUSE_NAME, SUM(CREDITS_USED) AS CURRENT_CREDITS
      FROM FACT_WAREHOUSE_HOURLY
      WHERE HOUR_START >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      GROUP BY COMPANY, WAREHOUSE_NAME
    ),
    baseline AS (
      SELECT COMPANY, WAREHOUSE_NAME, AVG(DAILY_CREDITS) AS BASELINE_DAILY_CREDITS
      FROM (
        SELECT COMPANY, WAREHOUSE_NAME, DATE_TRUNC('day', HOUR_START) AS USAGE_DAY, SUM(CREDITS_USED) AS DAILY_CREDITS
        FROM FACT_WAREHOUSE_HOURLY
        WHERE HOUR_START >= DATEADD('day', -31, CURRENT_TIMESTAMP())
          AND HOUR_START < DATEADD('day', -1, CURRENT_TIMESTAMP())
        GROUP BY COMPANY, WAREHOUSE_NAME, DATE_TRUNC('day', HOUR_START)
      )
      GROUP BY COMPANY, WAREHOUSE_NAME
    )
    SELECT 1
    FROM current_window c
    LEFT JOIN baseline b USING (COMPANY, WAREHOUSE_NAME)
    WHERE c.CURRENT_CREDITS > GREATEST(10, COALESCE(b.BASELINE_DAILY_CREDITS, 0) * 1.5)
  ))
  THEN INSERT INTO {event_table}
    (COMPANY, ENVIRONMENT, ALERT_KEY, CATEGORY, SEVERITY, STATUS, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, ENTITY_NAME, WAREHOUSE_NAME, CURRENT_VALUE, BASELINE_VALUE, REMEDIATION_MODE, EVIDENCE, DEDUPE_KEY)
    WITH current_window AS (
      SELECT COMPANY, WAREHOUSE_NAME, SUM(CREDITS_USED) AS CURRENT_CREDITS
      FROM FACT_WAREHOUSE_HOURLY
      WHERE HOUR_START >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      GROUP BY COMPANY, WAREHOUSE_NAME
    ),
    baseline AS (
      SELECT COMPANY, WAREHOUSE_NAME, AVG(DAILY_CREDITS) AS BASELINE_DAILY_CREDITS
      FROM (
        SELECT COMPANY, WAREHOUSE_NAME, DATE_TRUNC('day', HOUR_START) AS USAGE_DAY, SUM(CREDITS_USED) AS DAILY_CREDITS
        FROM FACT_WAREHOUSE_HOURLY
        WHERE HOUR_START >= DATEADD('day', -31, CURRENT_TIMESTAMP())
          AND HOUR_START < DATEADD('day', -1, CURRENT_TIMESTAMP())
        GROUP BY COMPANY, WAREHOUSE_NAME, DATE_TRUNC('day', HOUR_START)
      )
      GROUP BY COMPANY, WAREHOUSE_NAME
    )
    SELECT COALESCE(c.COMPANY, 'Shared/Unclassified'), 'ALL', 'COST_WAREHOUSE_CREDIT_SPIKE', 'Cost', 'High', 'New', 'DBA / Cost owner',
           'Explain the warehouse credit spike with run-rate, top query, setting, and company-scope telemetry before changing capacity.',
           'WAREHOUSE', c.WAREHOUSE_NAME, c.WAREHOUSE_NAME, c.CURRENT_CREDITS, COALESCE(b.BASELINE_DAILY_CREDITS, 0), 'RECOMMEND',
           'Native candidate detected warehouse credits above baseline.',
           SHA2('COST_WAREHOUSE_CREDIT_SPIKE|' || COALESCE(c.COMPANY, 'Shared/Unclassified') || '|' || c.WAREHOUSE_NAME || '|' || TO_VARCHAR(CURRENT_DATE()), 256)
    FROM current_window c
    LEFT JOIN baseline b USING (COMPANY, WAREHOUSE_NAME)
    WHERE c.CURRENT_CREDITS > GREATEST(10, COALESCE(b.BASELINE_DAILY_CREDITS, 0) * 1.5);""",
            "GENERATED_DROP_SQL": "DROP ALERT IF EXISTS OVERWATCH_ALERT_WAREHOUSE_CREDIT_SPIKE;",
            "ENABLED_BY_DEFAULT": False,
            "SAFETY_NOTE": "Recommend-only. Do not resize, suspend, or alter warehouses automatically.",
        },
        {
            "REGISTRY_KEY": "NATIVE_SECURITY_PRIVILEGE_ESCALATION",
            "ALERT_KEY": "SECURITY_PRIVILEGE_ESCALATION",
            "CATEGORY": "Security",
            "ALERT_OBJECT_NAME": "OVERWATCH_ALERT_PRIVILEGE_ESCALATION",
            "TARGET_ROUTE": "Security Monitoring",
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "SCHEDULE_TEXT": "60 MINUTE",
            "STATUS": "CANDIDATE",
            "CONDITION_SOURCE": "FACT_GRANT_DAILY company-labeled privileged role grants",
            "ACTION_SOURCE": "Insert status-review event into ALERT_EVENTS",
            "GENERATED_CREATE_SQL": f"""CREATE OR REPLACE ALERT OVERWATCH_ALERT_PRIVILEGE_ESCALATION
  WAREHOUSE = WH_ALFA_OVERWATCH
  SCHEDULE = '60 MINUTE'
  IF (EXISTS (
    SELECT 1
    FROM FACT_GRANT_DAILY
    WHERE SNAPSHOT_DATE >= DATEADD('day', -2, CURRENT_DATE())
      AND CREATED_ON >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND DELETED_ON IS NULL
      AND UPPER(ROLE_NAME) IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'ORGADMIN')
  ))
  THEN INSERT INTO {event_table}
    (COMPANY, ENVIRONMENT, ALERT_KEY, CATEGORY, SEVERITY, STATUS, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, ENTITY_NAME, USER_NAME, ROLE_NAME, REMEDIATION_MODE, EVIDENCE, DEDUPE_KEY)
    SELECT COALESCE(COMPANY, 'Shared/Unclassified'), 'No Database Context', 'SECURITY_PRIVILEGE_ESCALATION', 'Security', 'Critical', 'New', 'Security Reviewer',
           'Validate ticket, reviewer, MFA posture, and access purpose before accepting the privileged grant.',
           'USER', GRANTEE_NAME, GRANTEE_NAME, ROLE_NAME, 'STATUS_REVIEW',
           'Native candidate detected privileged role grant: ' || ROLE_NAME,
           SHA2('SECURITY_PRIVILEGE_ESCALATION|' || COALESCE(COMPANY, 'Shared/Unclassified') || '|' || GRANTEE_NAME || '|' || ROLE_NAME || '|' || TO_VARCHAR(CREATED_ON), 256)
    FROM FACT_GRANT_DAILY
    WHERE SNAPSHOT_DATE >= DATEADD('day', -2, CURRENT_DATE())
      AND CREATED_ON >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND DELETED_ON IS NULL
      AND UPPER(ROLE_NAME) IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'ORGADMIN');""",
            "GENERATED_DROP_SQL": "DROP ALERT IF EXISTS OVERWATCH_ALERT_PRIVILEGE_ESCALATION;",
            "ENABLED_BY_DEFAULT": False,
            "SAFETY_NOTE": "Status-review only. Never auto-revoke from this alert.",
        },
        {
            "REGISTRY_KEY": "NATIVE_PIPELINE_TASK_FAILURE",
            "ALERT_KEY": "PIPELINE_TASK_FAILURE",
            "CATEGORY": "Task / Pipeline",
            "ALERT_OBJECT_NAME": "OVERWATCH_ALERT_TASK_FAILURE",
            "TARGET_ROUTE": "Workload Operations",
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "SCHEDULE_TEXT": "30 MINUTE",
            "STATUS": "CANDIDATE",
            "CONDITION_SOURCE": "FACT_TASK_RUN company/environment-labeled failed/skipped task graph rows",
            "ACTION_SOURCE": "Insert status-review event into ALERT_EVENTS",
            "GENERATED_CREATE_SQL": f"""CREATE OR REPLACE ALERT OVERWATCH_ALERT_TASK_FAILURE
  WAREHOUSE = WH_ALFA_OVERWATCH
  SCHEDULE = '30 MINUTE'
  IF (EXISTS (
    SELECT 1
    FROM FACT_TASK_RUN
    WHERE SCHEDULED_TIME >= DATEADD('hour', -2, CURRENT_TIMESTAMP())
      AND UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'SKIPPED', 'CANCELLED')
  ))
  THEN INSERT INTO {event_table}
    (COMPANY, ENVIRONMENT, ALERT_KEY, CATEGORY, SEVERITY, STATUS, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, ENTITY_NAME, DATABASE_NAME, SCHEMA_NAME, QUERY_ID, REMEDIATION_MODE, EVIDENCE, DEDUPE_KEY)
    SELECT COALESCE(COMPANY, 'Shared/Unclassified'), COALESCE(ENVIRONMENT, 'No Database Context'), 'PIPELINE_TASK_FAILURE', 'Task / Pipeline', 'Critical', 'New', 'DBA / Pipeline Owner',
           'Identify root task, failed child, last success, downstream SLA, and safe rerun conditions.',
           'TASK', DATABASE_NAME || '.' || SCHEMA_NAME || '.' || TASK_NAME, DATABASE_NAME, SCHEMA_NAME, QUERY_ID, 'STATUS_REVIEW',
           COALESCE(ERROR_MESSAGE, STATE),
           SHA2('PIPELINE_TASK_FAILURE|' || COALESCE(COMPANY, 'Shared/Unclassified') || '|' || COALESCE(ROOT_TASK_NAME, TASK_NAME) || '|' || TO_VARCHAR(SCHEDULED_TIME), 256)
    FROM FACT_TASK_RUN
    WHERE SCHEDULED_TIME >= DATEADD('hour', -2, CURRENT_TIMESTAMP())
      AND UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'SKIPPED', 'CANCELLED');""",
            "GENERATED_DROP_SQL": "DROP ALERT IF EXISTS OVERWATCH_ALERT_TASK_FAILURE;",
            "ENABLED_BY_DEFAULT": False,
            "SAFETY_NOTE": "Status-review only. Reruns require task graph safety checks.",
        },
        {
            "REGISTRY_KEY": "NATIVE_BEHAVIOR_USER_QUERY_ANOMALY",
            "ALERT_KEY": "BEHAVIOR_USER_QUERY_ANOMALY",
            "CATEGORY": "Behavior",
            "ALERT_OBJECT_NAME": "OVERWATCH_ALERT_USER_QUERY_BEHAVIOR",
            "TARGET_ROUTE": "Workload Operations",
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "SCHEDULE_TEXT": "60 MINUTE",
            "STATUS": "CANDIDATE",
            "CONDITION_SOURCE": "FACT_QUERY_DETAIL_RECENT company/environment-labeled user failure, runtime, spill, and warehouse pressure patterns",
            "ACTION_SOURCE": "Insert status-review behavior event into ALERT_EVENTS",
            "GENERATED_CREATE_SQL": f"""CREATE OR REPLACE ALERT OVERWATCH_ALERT_USER_QUERY_BEHAVIOR
  WAREHOUSE = WH_ALFA_OVERWATCH
  SCHEDULE = '60 MINUTE'
  IF (EXISTS (
    SELECT 1
    FROM FACT_QUERY_DETAIL_RECENT
    WHERE START_TIME >= DATEADD('hour', -2, CURRENT_TIMESTAMP())
    GROUP BY COMPANY, ENVIRONMENT, USER_NAME, ROLE_NAME, WAREHOUSE_NAME
    HAVING COUNT_IF(UPPER(COALESCE(EXECUTION_STATUS, '')) NOT IN ('SUCCESS', '')) >= 10
        OR SUM(COALESCE(TOTAL_ELAPSED_TIME, 0)) / 1000 >= 7200
        OR SUM(COALESCE(BYTES_SPILLED_TO_REMOTE_STORAGE, 0)) / POWER(1024, 3) >= 25
  ))
  THEN INSERT INTO {event_table}
    (COMPANY, ENVIRONMENT, ALERT_KEY, CATEGORY, SEVERITY, STATUS, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, ENTITY_NAME, USER_NAME, ROLE_NAME, WAREHOUSE_NAME, CURRENT_VALUE, REMEDIATION_MODE, EVIDENCE, DEDUPE_KEY)
    SELECT COALESCE(COMPANY, 'Shared/Unclassified'), COALESCE(ENVIRONMENT, 'No Database Context'), 'BEHAVIOR_USER_QUERY_ANOMALY', 'Behavior', 'High', 'New', 'DBA / Workload reviewer',
           'Review the user, role, repeated query pattern, recent guidance, and downstream system impact before coaching or controls.',
           'USER', COALESCE(USER_NAME, 'Unknown user'), USER_NAME, ROLE_NAME, WAREHOUSE_NAME,
           COUNT(*) AS CURRENT_VALUE, 'STATUS_REVIEW',
           'Native candidate detected repeated failures, long runtime, or remote spill for a user/role/warehouse pattern.',
           SHA2('BEHAVIOR_USER_QUERY_ANOMALY|' || COALESCE(COMPANY, 'Shared/Unclassified') || '|' || COALESCE(USER_NAME, '') || '|' || COALESCE(ROLE_NAME, '') || '|' || COALESCE(WAREHOUSE_NAME, '') || '|' || TO_VARCHAR(CURRENT_DATE()), 256)
    FROM FACT_QUERY_DETAIL_RECENT
    WHERE START_TIME >= DATEADD('hour', -2, CURRENT_TIMESTAMP())
    GROUP BY COMPANY, ENVIRONMENT, USER_NAME, ROLE_NAME, WAREHOUSE_NAME
    HAVING COUNT_IF(UPPER(COALESCE(EXECUTION_STATUS, '')) NOT IN ('SUCCESS', '')) >= 10
        OR SUM(COALESCE(TOTAL_ELAPSED_TIME, 0)) / 1000 >= 7200
        OR SUM(COALESCE(BYTES_SPILLED_TO_REMOTE_STORAGE, 0)) / POWER(1024, 3) >= 25;""",
            "GENERATED_DROP_SQL": "DROP ALERT IF EXISTS OVERWATCH_ALERT_USER_QUERY_BEHAVIOR;",
            "ENABLED_BY_DEFAULT": False,
            "SAFETY_NOTE": "Status-review only. Do not cancel queries, disable users, or change grants automatically.",
        },
    ]


def build_alert_remediation_policy_seed_rows() -> list[dict[str, object]]:
    """Return safe default remediation policies for alert dry-run review."""
    return [
        {
            "POLICY_ID": "POLICY_CORTEX_QUOTA_REVIEW",
            "ALERT_KEY": "COST_CORTEX_SPEND_SPIKE",
            "CATEGORY": "Cost",
            "ACTION_TYPE": "Cortex quota or access review",
            "REMEDIATION_MODE": "RECOMMEND",
            "AUTO_ELIGIBLE": False,
            "REQUIRED_REVIEW": "DBA / AI cost route plus Security when grants change",
            "BEFORE_STATE_SQL": "SHOW PARAMETERS LIKE 'CORTEX%' IN ACCOUNT;",
            "DRY_RUN_SQL": "-- Review top FACT_CORTEX_DAILY users/sources and candidate quota setting; do not execute from Alert Center.",
            "EXECUTION_SQL_TEMPLATE": "-- No automatic Cortex access change. Use approved DBA workflow after review.",
            "ROLLBACK_GUIDANCE": "Restore prior Cortex parameter, role grant, or quota setting captured in before-state notes.",
            "VERIFICATION_SQL": "SELECT * FROM FACT_CORTEX_DAILY WHERE USAGE_DATE >= DATEADD('day', -7, CURRENT_DATE()) ORDER BY EST_COST_USD DESC LIMIT 100;",
        },
        {
            "POLICY_ID": "POLICY_IDLE_WAREHOUSE_TIMEOUT_REVIEW",
            "ALERT_KEY": "OPT_UNUSED_WAREHOUSE",
            "CATEGORY": "Optimization",
            "ACTION_TYPE": "Warehouse auto-suspend timeout review",
            "REMEDIATION_MODE": "STATUS_REVIEW",
            "AUTO_ELIGIBLE": False,
            "REQUIRED_REVIEW": "DBA / Cost owner",
            "BEFORE_STATE_SQL": "SHOW WAREHOUSES;",
            "DRY_RUN_SQL": "-- Generate ALTER WAREHOUSE <name> SET AUTO_SUSPEND = <seconds> after route review.",
            "EXECUTION_SQL_TEMPLATE": "ALTER WAREHOUSE IDENTIFIER('<warehouse_name>') SET AUTO_SUSPEND = <seconds>;",
            "ROLLBACK_GUIDANCE": "Reset AUTO_SUSPEND to the captured before-state value.",
            "VERIFICATION_SQL": "SHOW WAREHOUSES LIKE '<warehouse_name>';",
        },
        {
            "POLICY_ID": "POLICY_WAREHOUSE_SPIKE_COST_REVIEW",
            "ALERT_KEY": "COST_WAREHOUSE_CREDIT_SPIKE",
            "CATEGORY": "Cost",
            "ACTION_TYPE": "Warehouse cost spike review",
            "REMEDIATION_MODE": "RECOMMEND",
            "AUTO_ELIGIBLE": False,
            "REQUIRED_REVIEW": "DBA / Cost owner plus workload owner",
            "BEFORE_STATE_SQL": "SELECT * FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = '<warehouse_name>' ORDER BY HOUR_START DESC LIMIT 168;",
            "DRY_RUN_SQL": "-- Compare current/prior run-rate, top query hashes, warehouse settings, and company scope; no ALTER WAREHOUSE from Alert Center.",
            "EXECUTION_SQL_TEMPLATE": "-- No automatic warehouse change. Use guarded Admin workflow if a setting change is approved.",
            "ROLLBACK_GUIDANCE": "Restore prior warehouse settings only through guarded Admin review with before-state evidence.",
            "VERIFICATION_SQL": "SELECT * FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = '<warehouse_name>' ORDER BY HOUR_START DESC LIMIT 168;",
        },
        {
            "POLICY_ID": "POLICY_USER_QUERY_BEHAVIOR_REVIEW",
            "ALERT_KEY": "BEHAVIOR_USER_QUERY_ANOMALY",
            "CATEGORY": "Behavior",
            "ACTION_TYPE": "User/query behavior review",
            "REMEDIATION_MODE": "STATUS_REVIEW",
            "AUTO_ELIGIBLE": False,
            "REQUIRED_REVIEW": "DBA / Workload reviewer",
            "BEFORE_STATE_SQL": "SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, QUERY_ID, EXECUTION_STATUS, TOTAL_ELAPSED_TIME, QUERY_TEXT FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE USER_NAME = '<user_name>' ORDER BY START_TIME DESC LIMIT 100;",
            "DRY_RUN_SQL": "-- Compare repeated query hash, failures, role, warehouse, and recent coaching/change source before any control action.",
            "EXECUTION_SQL_TEMPLATE": "-- No automatic cancel, disable, revoke, or warehouse change from behavior alerts.",
            "ROLLBACK_GUIDANCE": "If a manual control was applied, restore access/settings only after verified query behavior and owner approval.",
            "VERIFICATION_SQL": "SELECT USER_NAME, ROLE_NAME, WAREHOUSE_NAME, COUNT(*) AS QUERY_COUNT FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD('day', -1, CURRENT_TIMESTAMP()) GROUP BY 1,2,3 ORDER BY QUERY_COUNT DESC;",
        },
        {
            "POLICY_ID": "POLICY_TASK_RERUN_STATUS_REVIEW",
            "ALERT_KEY": "PIPELINE_TASK_FAILURE",
            "CATEGORY": "Task / Pipeline",
            "ACTION_TYPE": "Task rerun review",
            "REMEDIATION_MODE": "STATUS_REVIEW",
            "AUTO_ELIGIBLE": False,
            "REQUIRED_REVIEW": "DBA / Pipeline Owner",
            "BEFORE_STATE_SQL": "SELECT * FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY()) ORDER BY SCHEDULED_TIME DESC LIMIT 100;",
            "DRY_RUN_SQL": "-- Confirm root cause, dependency state, and downstream idempotency before EXECUTE TASK.",
            "EXECUTION_SQL_TEMPLATE": "EXECUTE TASK IDENTIFIER('<database.schema.task_name>');",
            "ROLLBACK_GUIDANCE": "Record downstream cleanup plan or rerun blocker before manual execution.",
            "VERIFICATION_SQL": "SELECT * FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY()) ORDER BY SCHEDULED_TIME DESC LIMIT 100;",
        },
        {
            "POLICY_ID": "POLICY_SECURITY_ACCESS_STATUS_REVIEW",
            "ALERT_KEY": "SECURITY_PRIVILEGE_ESCALATION",
            "CATEGORY": "Security",
            "ACTION_TYPE": "Access rollback review",
            "REMEDIATION_MODE": "STATUS_REVIEW",
            "AUTO_ELIGIBLE": False,
            "REQUIRED_REVIEW": "Security Reviewer",
            "BEFORE_STATE_SQL": "SHOW GRANTS TO USER <user_name>;",
            "DRY_RUN_SQL": "-- Compare grant, ticket, reviewer, and MFA posture before any revoke.",
            "EXECUTION_SQL_TEMPLATE": "-- Revoke SQL is intentionally not generated for AUTO mode.",
            "ROLLBACK_GUIDANCE": "Re-grant only after reviewer approval and ticket evidence.",
            "VERIFICATION_SQL": "SHOW GRANTS TO USER <user_name>;",
        },
    ]


def build_alert_native_registry_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    rows = build_alert_native_object_registry_seed_rows(db=db, schema=schema)
    columns = [
        "REGISTRY_KEY",
        "ALERT_KEY",
        "CATEGORY",
        "ALERT_OBJECT_NAME",
        "TARGET_ROUTE",
        "WAREHOUSE_NAME",
        "SCHEDULE_TEXT",
        "STATUS",
        "CONDITION_SOURCE",
        "ACTION_SOURCE",
        "GENERATED_CREATE_SQL",
        "GENERATED_DROP_SQL",
        "ENABLED_BY_DEFAULT",
        "SAFETY_NOTE",
    ]
    values = _values_clause(rows, columns)
    table = _command_center_fqn(ALERT_NATIVE_OBJECT_REGISTRY_TABLE, db, schema)
    return f"""CREATE TABLE IF NOT EXISTS {table} (
  REGISTRY_KEY          VARCHAR(200) PRIMARY KEY,
  ALERT_KEY             VARCHAR(200),
  CATEGORY              VARCHAR(100),
  ALERT_OBJECT_NAME     VARCHAR(300),
  TARGET_ROUTE          VARCHAR(200),
  WAREHOUSE_NAME        VARCHAR(300),
  SCHEDULE_TEXT         VARCHAR(100),
  STATUS                VARCHAR(40) DEFAULT 'CANDIDATE',
  CONDITION_SOURCE      VARCHAR(1000),
  ACTION_SOURCE         VARCHAR(1000),
  GENERATED_CREATE_SQL  VARCHAR(16000),
  GENERATED_DROP_SQL    VARCHAR(4000),
  ENABLED_BY_DEFAULT    BOOLEAN DEFAULT FALSE,
  SAFETY_NOTE           VARCHAR(4000),
  UPDATED_AT            TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY            VARCHAR(200) DEFAULT CURRENT_USER()
);

MERGE INTO {table} tgt
USING (
  SELECT * FROM VALUES
    {values}
) src({", ".join(columns)})
ON tgt.REGISTRY_KEY = src.REGISTRY_KEY
WHEN MATCHED THEN UPDATE SET
  ALERT_KEY = src.ALERT_KEY,
  CATEGORY = src.CATEGORY,
  ALERT_OBJECT_NAME = src.ALERT_OBJECT_NAME,
  TARGET_ROUTE = src.TARGET_ROUTE,
  WAREHOUSE_NAME = src.WAREHOUSE_NAME,
  SCHEDULE_TEXT = src.SCHEDULE_TEXT,
  STATUS = src.STATUS,
  CONDITION_SOURCE = src.CONDITION_SOURCE,
  ACTION_SOURCE = src.ACTION_SOURCE,
  GENERATED_CREATE_SQL = src.GENERATED_CREATE_SQL,
  GENERATED_DROP_SQL = src.GENERATED_DROP_SQL,
  ENABLED_BY_DEFAULT = src.ENABLED_BY_DEFAULT,
  SAFETY_NOTE = src.SAFETY_NOTE,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  ({", ".join(columns)})
VALUES
  ({", ".join("src." + column for column in columns)});
"""


def build_alert_remediation_policy_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    rows = build_alert_remediation_policy_seed_rows()
    columns = [
        "POLICY_ID",
        "ALERT_KEY",
        "CATEGORY",
        "ACTION_TYPE",
        "REMEDIATION_MODE",
        "AUTO_ELIGIBLE",
        "REQUIRED_REVIEW",
        "BEFORE_STATE_SQL",
        "DRY_RUN_SQL",
        "EXECUTION_SQL_TEMPLATE",
        "ROLLBACK_GUIDANCE",
        "VERIFICATION_SQL",
    ]
    policy_table = _command_center_fqn(ALERT_REMEDIATION_POLICY_TABLE, db, schema)
    dry_run_table = _command_center_fqn(ALERT_REMEDIATION_DRY_RUN_TABLE, db, schema)
    values = _values_clause(rows, columns)
    return f"""CREATE TABLE IF NOT EXISTS {policy_table} (
  POLICY_ID              VARCHAR(200) PRIMARY KEY,
  ALERT_KEY              VARCHAR(200),
  CATEGORY               VARCHAR(100),
  ACTION_TYPE            VARCHAR(200),
  REMEDIATION_MODE       VARCHAR(40) DEFAULT 'RECOMMEND',
  AUTO_ELIGIBLE          BOOLEAN DEFAULT FALSE,
  REQUIRED_REVIEW        VARCHAR(500),
  BEFORE_STATE_SQL       VARCHAR(8000),
  DRY_RUN_SQL            VARCHAR(8000),
  EXECUTION_SQL_TEMPLATE VARCHAR(8000),
  ROLLBACK_GUIDANCE      VARCHAR(4000),
  VERIFICATION_SQL       VARCHAR(8000),
  ACTIVE                 BOOLEAN DEFAULT TRUE,
  UPDATED_AT             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY             VARCHAR(200) DEFAULT CURRENT_USER()
);

CREATE TABLE IF NOT EXISTS {dry_run_table} (
  DRY_RUN_ID          NUMBER AUTOINCREMENT PRIMARY KEY,
  POLICY_ID           VARCHAR(200),
  EVENT_ID            NUMBER,
  ALERT_KEY           VARCHAR(200),
  CREATED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CREATED_BY          VARCHAR(200) DEFAULT CURRENT_USER(),
  DRY_RUN_STATUS      VARCHAR(100),
  BEFORE_STATE        VARCHAR(8000),
  PROPOSED_SQL        VARCHAR(16000),
  EXPECTED_EFFECT     VARCHAR(4000),
  BLOCKING_REASON     VARCHAR(4000),
  VERIFICATION_SQL    VARCHAR(8000)
);

MERGE INTO {policy_table} tgt
USING (
  SELECT * FROM VALUES
    {values}
) src({", ".join(columns)})
ON tgt.POLICY_ID = src.POLICY_ID
WHEN MATCHED THEN UPDATE SET
  ALERT_KEY = src.ALERT_KEY,
  CATEGORY = src.CATEGORY,
  ACTION_TYPE = src.ACTION_TYPE,
  REMEDIATION_MODE = src.REMEDIATION_MODE,
  AUTO_ELIGIBLE = src.AUTO_ELIGIBLE,
  REQUIRED_REVIEW = src.REQUIRED_REVIEW,
  BEFORE_STATE_SQL = src.BEFORE_STATE_SQL,
  DRY_RUN_SQL = src.DRY_RUN_SQL,
  EXECUTION_SQL_TEMPLATE = src.EXECUTION_SQL_TEMPLATE,
  ROLLBACK_GUIDANCE = src.ROLLBACK_GUIDANCE,
  VERIFICATION_SQL = src.VERIFICATION_SQL,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  ({", ".join(columns)})
VALUES
  ({", ".join("src." + column for column in columns)});
"""


def build_alert_native_deployment_review_rows(
    registry_rows: pd.DataFrame | list[dict[str, object]] | None = None,
) -> pd.DataFrame:
    """Return operator-facing deployment readiness rows for native alert candidates."""
    if registry_rows is None:
        rows = pd.DataFrame(build_alert_native_object_registry_seed_rows())
    elif isinstance(registry_rows, pd.DataFrame):
        rows = registry_rows.copy()
    else:
        rows = pd.DataFrame(registry_rows)
    if rows.empty:
        return pd.DataFrame(columns=[
            "DEPLOYMENT_STATE",
            "CATEGORY",
            "ALERT_KEY",
            "ALERT_OBJECT_NAME",
            "TARGET_ROUTE",
            "WAREHOUSE_NAME",
            "SCHEDULE_TEXT",
            "DEPLOYMENT_SQL_PRESENT",
            "ROLLBACK_SQL_PRESENT",
            "DEPLOYMENT_NEXT_STEP",
            "VALIDATION_SQL",
            "SAFETY_NOTE",
        ])

    rows = rows.copy()
    for column in [
        "STATUS",
        "ENABLED_BY_DEFAULT",
        "CATEGORY",
        "ALERT_KEY",
        "ALERT_OBJECT_NAME",
        "TARGET_ROUTE",
        "WAREHOUSE_NAME",
        "SCHEDULE_TEXT",
        "GENERATED_CREATE_SQL",
        "GENERATED_DROP_SQL",
        "SAFETY_NOTE",
    ]:
        if column not in rows.columns:
            rows[column] = None

    status = rows["STATUS"].fillna("CANDIDATE").astype(str).str.upper()
    enabled = rows["ENABLED_BY_DEFAULT"].fillna(False).astype(bool)
    rows["DEPLOYMENT_STATE"] = "CANDIDATE_REVIEW_REQUIRED"
    rows.loc[status.isin(["APPROVED", "READY", "READY_TO_DEPLOY"]), "DEPLOYMENT_STATE"] = "READY_FOR_MANUAL_DEPLOY"
    rows.loc[status.isin(["DEPLOYED", "ACTIVE"]), "DEPLOYMENT_STATE"] = "DEPLOYED_MONITOR"
    rows.loc[enabled, "DEPLOYMENT_STATE"] = "BLOCKED_ENABLED_BY_DEFAULT"
    rows["DEPLOYMENT_SQL_PRESENT"] = rows["GENERATED_CREATE_SQL"].fillna("").astype(str).str.contains("CREATE OR REPLACE ALERT", case=False, regex=False)
    rows["ROLLBACK_SQL_PRESENT"] = rows["GENERATED_DROP_SQL"].fillna("").astype(str).str.contains("DROP ALERT", case=False, regex=False)
    rows["DEPLOYMENT_NEXT_STEP"] = rows["DEPLOYMENT_STATE"].map({
        "READY_FOR_MANUAL_DEPLOY": "Run generated CREATE ALERT SQL manually in Snowflake after owner, threshold, and warehouse review.",
        "DEPLOYED_MONITOR": "Monitor ALERT_EVENTS, ALERT_RUN_HISTORY, notification logs, and remediation dry-runs.",
        "BLOCKED_ENABLED_BY_DEFAULT": "Set ENABLED_BY_DEFAULT to false before deployment review can continue.",
    }).fillna("Review threshold, schedule, owner, route, safety note, and generated SQL before marking approved.")
    rows["VALIDATION_SQL"] = rows["ALERT_OBJECT_NAME"].fillna("").astype(str).apply(
        lambda name: f"SHOW ALERTS LIKE '{name}';" if name else "SHOW ALERTS IN SCHEMA;"
    )
    return rows[[
        "DEPLOYMENT_STATE",
        "CATEGORY",
        "ALERT_KEY",
        "ALERT_OBJECT_NAME",
        "TARGET_ROUTE",
        "WAREHOUSE_NAME",
        "SCHEDULE_TEXT",
        "DEPLOYMENT_SQL_PRESENT",
        "ROLLBACK_SQL_PRESENT",
        "DEPLOYMENT_NEXT_STEP",
        "VALIDATION_SQL",
        "SAFETY_NOTE",
        "GENERATED_CREATE_SQL",
        "GENERATED_DROP_SQL",
    ]]


def build_alert_native_deployment_review_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Return safe SQL objects for reviewing native-alert deployment and dry-runs."""
    registry = _command_center_fqn(ALERT_NATIVE_OBJECT_REGISTRY_TABLE, db, schema)
    policy = _command_center_fqn(ALERT_REMEDIATION_POLICY_TABLE, db, schema)
    dry_run = _command_center_fqn(ALERT_REMEDIATION_DRY_RUN_TABLE, db, schema)
    events = _command_center_fqn("ALERT_EVENTS", db, schema)
    view = _command_center_fqn("ALERT_NATIVE_DEPLOYMENT_REVIEW_V", db, schema)
    proc = _command_center_fqn("SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN", db, schema)
    return f"""-- Native Snowflake alert deployment review and remediation dry-run staging.
-- This script never executes GENERATED_CREATE_SQL or GENERATED_DROP_SQL.
-- Operators review SQL first, deploy selected alerts manually, and keep all
-- remediation as dry-run/status-review until a separate guarded automation
-- path is explicitly approved.

CREATE OR REPLACE VIEW {view} AS
SELECT
  REGISTRY_KEY,
  ALERT_KEY,
  CATEGORY,
  ALERT_OBJECT_NAME,
  TARGET_ROUTE,
  WAREHOUSE_NAME,
  SCHEDULE_TEXT,
  STATUS,
  ENABLED_BY_DEFAULT,
  CASE
    WHEN COALESCE(ENABLED_BY_DEFAULT, FALSE) THEN 'BLOCKED_ENABLED_BY_DEFAULT'
    WHEN UPPER(COALESCE(STATUS, 'CANDIDATE')) IN ('APPROVED', 'READY', 'READY_TO_DEPLOY') THEN 'READY_FOR_MANUAL_DEPLOY'
    WHEN UPPER(COALESCE(STATUS, 'CANDIDATE')) IN ('DEPLOYED', 'ACTIVE') THEN 'DEPLOYED_MONITOR'
    ELSE 'CANDIDATE_REVIEW_REQUIRED'
  END AS DEPLOYMENT_STATE,
  IFF(GENERATED_CREATE_SQL ILIKE '%CREATE OR REPLACE ALERT%', TRUE, FALSE) AS DEPLOYMENT_SQL_PRESENT,
  IFF(GENERATED_DROP_SQL ILIKE '%DROP ALERT%', TRUE, FALSE) AS ROLLBACK_SQL_PRESENT,
  CASE
    WHEN COALESCE(ENABLED_BY_DEFAULT, FALSE) THEN 'Set ENABLED_BY_DEFAULT to FALSE before review can continue.'
    WHEN UPPER(COALESCE(STATUS, 'CANDIDATE')) IN ('APPROVED', 'READY', 'READY_TO_DEPLOY') THEN 'Run GENERATED_CREATE_SQL manually after owner, threshold, schedule, and warehouse approval.'
    WHEN UPPER(COALESCE(STATUS, 'CANDIDATE')) IN ('DEPLOYED', 'ACTIVE') THEN 'Monitor ALERT_EVENTS and dry-run outcomes; use GENERATED_DROP_SQL only for rollback.'
    ELSE 'Review owner, threshold, route, safety note, and generated SQL before marking approved.'
  END AS DEPLOYMENT_NEXT_STEP,
  'SHOW ALERTS LIKE ''' || ALERT_OBJECT_NAME || ''';' AS VALIDATION_SQL,
  SAFETY_NOTE,
  GENERATED_CREATE_SQL,
  GENERATED_DROP_SQL,
  UPDATED_AT,
  UPDATED_BY
FROM {registry};

CREATE OR REPLACE PROCEDURE {proc}(
  P_EVENT_ID NUMBER,
  P_ALERT_KEY VARCHAR
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
BEGIN
  INSERT INTO {dry_run}
    (POLICY_ID, EVENT_ID, ALERT_KEY, DRY_RUN_STATUS, BEFORE_STATE, PROPOSED_SQL,
     EXPECTED_EFFECT, BLOCKING_REASON, VERIFICATION_SQL)
  SELECT
    p.POLICY_ID,
    e.EVENT_ID,
    e.ALERT_KEY,
    CASE
      WHEN COALESCE(p.AUTO_ELIGIBLE, FALSE) THEN 'REVIEW_REQUIRED_AUTO_DISABLED'
      ELSE 'BLOCKED_REVIEW_REQUIRED'
    END AS DRY_RUN_STATUS,
    p.BEFORE_STATE_SQL AS BEFORE_STATE,
    COALESCE(NULLIF(p.EXECUTION_SQL_TEMPLATE, ''), p.DRY_RUN_SQL) AS PROPOSED_SQL,
    'Dry-run only. Capture before-state, review route owner, and verify expected impact before any manual action.' AS EXPECTED_EFFECT,
    CASE
      WHEN COALESCE(p.AUTO_ELIGIBLE, FALSE) THEN 'AUTO_ELIGIBLE is not sufficient for execution; guarded automation is not enabled in OVERWATCH.'
      ELSE 'AUTO_ELIGIBLE is false. Manual review is required before any action.'
    END AS BLOCKING_REASON,
    p.VERIFICATION_SQL
  FROM {events} e
  JOIN {policy} p
    ON UPPER(p.ALERT_KEY) = UPPER(e.ALERT_KEY)
   AND COALESCE(p.ACTIVE, TRUE)
  WHERE (P_EVENT_ID IS NULL OR e.EVENT_ID = P_EVENT_ID)
    AND (P_ALERT_KEY IS NULL OR UPPER(e.ALERT_KEY) = UPPER(P_ALERT_KEY))
    AND NOT EXISTS (
      SELECT 1
      FROM {dry_run} d
      WHERE d.EVENT_ID = e.EVENT_ID
        AND d.POLICY_ID = p.POLICY_ID
        AND d.CREATED_AT >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
    );

  RETURN 'Remediation dry-run staging completed. Review ALERT_REMEDIATION_DRY_RUN before any manual action.';
END;
$$;
"""


def load_alert_native_object_registry(section: str = "Alert Center") -> pd.DataFrame:
    """Load reviewed native Snowflake alert candidates from the mart registry."""
    table = _command_center_fqn(ALERT_NATIVE_OBJECT_REGISTRY_TABLE)
    columns = [
        "REGISTRY_KEY",
        "ALERT_KEY",
        "CATEGORY",
        "ALERT_OBJECT_NAME",
        "TARGET_ROUTE",
        "WAREHOUSE_NAME",
        "SCHEDULE_TEXT",
        "STATUS",
        "CONDITION_SOURCE",
        "ACTION_SOURCE",
        "ENABLED_BY_DEFAULT",
        "SAFETY_NOTE",
        "UPDATED_AT",
        "UPDATED_BY",
        "GENERATED_CREATE_SQL",
        "GENERATED_DROP_SQL",
    ]
    df = run_query(f"""
        SELECT
            REGISTRY_KEY,
            ALERT_KEY,
            CATEGORY,
            ALERT_OBJECT_NAME,
            TARGET_ROUTE,
            WAREHOUSE_NAME,
            SCHEDULE_TEXT,
            STATUS,
            CONDITION_SOURCE,
            ACTION_SOURCE,
            ENABLED_BY_DEFAULT,
            SAFETY_NOTE,
            UPDATED_AT,
            UPDATED_BY,
            GENERATED_CREATE_SQL,
            GENERATED_DROP_SQL
        FROM {table}
        ORDER BY ENABLED_BY_DEFAULT DESC, TARGET_ROUTE, CATEGORY, ALERT_KEY
        LIMIT 200
    """, ttl_key="alert_native_object_registry", tier="metadata", section=section, max_rows=200)
    for column in columns:
        if column not in df.columns:
            df[column] = None
    return df[columns]


def load_alert_remediation_policy(section: str = "Alert Center") -> pd.DataFrame:
    """Load safe remediation policy rows from the mart policy catalog."""
    table = _command_center_fqn(ALERT_REMEDIATION_POLICY_TABLE)
    columns = [
        "POLICY_ID",
        "ALERT_KEY",
        "CATEGORY",
        "ACTION_TYPE",
        "REMEDIATION_MODE",
        "AUTO_ELIGIBLE",
        "REQUIRED_REVIEW",
        "BEFORE_STATE_SQL",
        "DRY_RUN_SQL",
        "EXECUTION_SQL_TEMPLATE",
        "ROLLBACK_GUIDANCE",
        "VERIFICATION_SQL",
        "ACTIVE",
        "UPDATED_AT",
        "UPDATED_BY",
    ]
    df = run_query(f"""
        SELECT
            POLICY_ID,
            ALERT_KEY,
            CATEGORY,
            ACTION_TYPE,
            REMEDIATION_MODE,
            AUTO_ELIGIBLE,
            REQUIRED_REVIEW,
            BEFORE_STATE_SQL,
            DRY_RUN_SQL,
            EXECUTION_SQL_TEMPLATE,
            ROLLBACK_GUIDANCE,
            VERIFICATION_SQL,
            ACTIVE,
            UPDATED_AT,
            UPDATED_BY
        FROM {table}
        ORDER BY ACTIVE DESC, AUTO_ELIGIBLE ASC, CATEGORY, ALERT_KEY, POLICY_ID
        LIMIT 300
    """, ttl_key="alert_remediation_policy", tier="metadata", section=section, max_rows=300)
    for column in columns:
        if column not in df.columns:
            df[column] = None
    return df[columns]


def load_alert_remediation_dry_runs(
    *,
    days: int = 14,
    limit: int = 200,
    section: str = "Alert Center",
) -> pd.DataFrame:
    """Load recent remediation dry-run audit rows without executing any action."""
    days = max(1, min(int(days or 14), 365))
    limit = max(1, min(int(limit or 200), 1000))
    table = _command_center_fqn(ALERT_REMEDIATION_DRY_RUN_TABLE)
    columns = [
        "DRY_RUN_ID",
        "POLICY_ID",
        "EVENT_ID",
        "ALERT_KEY",
        "CREATED_AT",
        "CREATED_BY",
        "DRY_RUN_STATUS",
        "BEFORE_STATE",
        "PROPOSED_SQL",
        "EXPECTED_EFFECT",
        "BLOCKING_REASON",
        "VERIFICATION_SQL",
    ]
    df = run_query(f"""
        SELECT
            DRY_RUN_ID,
            POLICY_ID,
            EVENT_ID,
            ALERT_KEY,
            CREATED_AT,
            CREATED_BY,
            DRY_RUN_STATUS,
            BEFORE_STATE,
            PROPOSED_SQL,
            EXPECTED_EFFECT,
            BLOCKING_REASON,
            VERIFICATION_SQL
        FROM {table}
        WHERE CREATED_AT >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        ORDER BY CREATED_AT DESC, DRY_RUN_ID DESC
        LIMIT {limit}
    """, ttl_key=f"alert_remediation_dry_runs_{days}_{limit}", tier="recent", section=section, max_rows=limit)
    for column in columns:
        if column not in df.columns:
            df[column] = None
    return df[columns]

