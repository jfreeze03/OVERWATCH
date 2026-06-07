# utils/deployment.py - release and mart migration readiness helpers
from __future__ import annotations

import pandas as pd


OVERWATCH_SCHEMA_VERSION = "2026.06.04-cost-proof-mart"
MIGRATION_TABLE = "OVERWATCH_SCHEMA_MIGRATION"


def build_schema_migration_contract() -> pd.DataFrame:
    """Return the baseline mart/setup versions expected by this app release."""
    rows = [
        {
            "COMPONENT": "Core mart setup",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_SETTINGS",
            "WHY_IT_MATTERS": "Stores cost, alert, and runtime settings used by every DBA workflow.",
            "READY_CRITERIA": "Version row exists and OVERWATCH_SETTINGS is queryable.",
        },
        {
            "COMPONENT": "Action queue and closure proof",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_ACTION_QUEUE",
            "WHY_IT_MATTERS": "Keeps recommendations, alert routes, cost actions, and closure evidence auditable.",
            "READY_CRITERIA": "Queue table exists with owner, SLA, approval, and verification columns.",
        },
        {
            "COMPONENT": "Alert automation",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_ALERT_DELIVERY_LOG",
            "WHY_IT_MATTERS": "Stores digest delivery proof, escalation acknowledgement, and email readiness history.",
            "READY_CRITERIA": "Delivery log exists and Alert Center can write digest evidence.",
        },
        {
            "COMPONENT": "Alert automation",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_ANNOTATIONS",
            "WHY_IT_MATTERS": "Stores suppression windows used by the hourly anomaly task to avoid duplicate alert noise.",
            "READY_CRITERIA": "Annotation table exists before OVERWATCH_ANOMALY_CHECK is resumed.",
        },
        {
            "COMPONENT": "FinOps verification",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_COST_SAVINGS_VERIFICATION_RUN",
            "WHY_IT_MATTERS": "Separates estimated savings from verified savings with metering evidence.",
            "READY_CRITERIA": "Verification table, procedure, view, and scheduled task are deployed.",
        },
        {
            "COMPONENT": "No-touch automation",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_AUTOMATION_RUN",
            "WHY_IT_MATTERS": "Records scheduled queue seeding, owner routing, alert digest, executive packet, and evidence-feed runs.",
            "READY_CRITERIA": "Automation run ledger, health view, refresh procedure, and task are deployed.",
        },
        {
            "COMPONENT": "No-touch automation",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_EXTERNAL_CONTROL_FEED",
            "WHY_IT_MATTERS": "Normalizes Control-M, Jira, Terraform, and Flyway evidence so Change & Drift can show exception rollups.",
            "READY_CRITERIA": "External feed table exists and SP_OVERWATCH_REFRESH_AUTOMATION can upsert feed rows.",
        },
        {
            "COMPONENT": "Cost proof mart",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "FACT_COST_DAILY",
            "WHY_IT_MATTERS": "Persists billed cost by Snowflake service type so the UI does not rescan daily metering views.",
            "READY_CRITERIA": "Daily service-cost mart and source-health mart exist.",
        },
        {
            "COMPONENT": "Procedure runtime context",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "FACT_PROCEDURE_RUN",
            "WHY_IT_MATTERS": "Keeps stored procedure failures, runtime spikes, and child-query evidence scoped to database and schema.",
            "READY_CRITERIA": "Procedure run fact exists with DATABASE_NAME, SCHEMA_NAME, ENVIRONMENT, and PROCEDURE_NAME.",
        },
        {
            "COMPONENT": "Change evidence integration",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_SOURCE_CONTROL_CHANGE",
            "WHY_IT_MATTERS": "Connects Snowflake drift to Terraform/Flyway/Git evidence and approval context.",
            "READY_CRITERIA": "Source-control and ITSM evidence tables exist.",
        },
        {
            "COMPONENT": "Change evidence feed ingress",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_SOURCE_CONTROL_CHANGE_STAGE",
            "WHY_IT_MATTERS": "Gives CI/CD a Snowflake landing point for Terraform/Flyway/Git evidence exports.",
            "READY_CRITERIA": "Source-control and ITSM evidence stages plus CSV file format exist.",
        },
        {
            "COMPONENT": "Schema migration ledger",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": MIGRATION_TABLE,
            "WHY_IT_MATTERS": "Shows whether the deployed Snowflake mart is aligned to the app release.",
            "READY_CRITERIA": "Ledger contains the current app/setup version row.",
        },
    ]
    return pd.DataFrame(rows)


def build_schema_migration_status_sql(
    *,
    database: str = "DBA_MAINT_DB",
    schema: str = "OVERWATCH",
    required_version: str = OVERWATCH_SCHEMA_VERSION,
) -> str:
    """Build a Snowflake status query for setup/migration readiness."""
    db = str(database).replace('"', '""')
    sch = str(schema).replace('"', '""')
    version = str(required_version).replace("'", "''")
    return f"""
WITH required_objects AS (
    SELECT * FROM VALUES
        ('Core mart setup', 'OVERWATCH_SETTINGS', 'TABLE', '{version}'),
        ('Action queue and closure proof', 'OVERWATCH_ACTION_QUEUE', 'TABLE', '{version}'),
        ('Alert automation', 'OVERWATCH_ALERT_DELIVERY_LOG', 'TABLE', '{version}'),
        ('Alert automation', 'OVERWATCH_ANNOTATIONS', 'TABLE', '{version}'),
        ('FinOps verification', 'OVERWATCH_COST_SAVINGS_VERIFICATION_RUN', 'TABLE', '{version}'),
        ('FinOps verification', 'OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V', 'VIEW', '{version}'),
        ('No-touch automation', 'OVERWATCH_AUTOMATION_RUN', 'TABLE', '{version}'),
        ('No-touch automation', 'OVERWATCH_AUTOMATION_HEALTH_V', 'VIEW', '{version}'),
        ('No-touch automation', 'OVERWATCH_EXECUTIVE_PACKET', 'TABLE', '{version}'),
        ('No-touch automation', 'OVERWATCH_EXTERNAL_CONTROL_FEED', 'TABLE', '{version}'),
        ('Cost proof mart', 'FACT_COST_DAILY', 'TABLE', '{version}'),
        ('Cost proof mart', 'FACT_COST_SOURCE_HEALTH_DAILY', 'TABLE', '{version}'),
        ('Procedure runtime context', 'FACT_PROCEDURE_RUN', 'TABLE', '{version}'),
        ('Change evidence integration', 'OVERWATCH_SOURCE_CONTROL_CHANGE', 'TABLE', '{version}'),
        ('Change evidence integration', 'OVERWATCH_ITSM_TICKET', 'TABLE', '{version}'),
        ('Change evidence feed ingress', 'OVERWATCH_CHANGE_EVIDENCE_CSV_FORMAT', 'FILE FORMAT', '{version}'),
        ('Change evidence feed ingress', 'OVERWATCH_SOURCE_CONTROL_CHANGE_STAGE', 'STAGE', '{version}'),
        ('Change evidence feed ingress', 'OVERWATCH_ITSM_TICKET_STAGE', 'STAGE', '{version}'),
        ('Schema migration ledger', 'OVERWATCH_SCHEMA_MIGRATION', 'TABLE', '{version}')
    AS t(component, object_name, object_type, required_version)
),
object_inventory AS (
    SELECT table_name AS object_name, table_type AS object_type
    FROM {db}.INFORMATION_SCHEMA.TABLES
    WHERE table_schema = '{sch}'
    UNION ALL
    SELECT stage_name AS object_name, 'STAGE' AS object_type
    FROM {db}.INFORMATION_SCHEMA.STAGES
    WHERE stage_schema = '{sch}'
    UNION ALL
    SELECT file_format_name AS object_name, 'FILE FORMAT' AS object_type
    FROM {db}.INFORMATION_SCHEMA.FILE_FORMATS
    WHERE file_format_schema = '{sch}'
),
ledger AS (
    SELECT
        MAX_BY(MIGRATION_VERSION, APPLIED_AT) AS latest_version,
        MAX(APPLIED_AT) AS latest_applied_at
    FROM {db}.{sch}.OVERWATCH_SCHEMA_MIGRATION
)
SELECT
    r.component,
    r.object_name,
    r.object_type,
    IFF(i.object_name IS NULL, 'Missing', 'Present') AS object_state,
    r.required_version,
    COALESCE(l.latest_version, 'Unknown') AS deployed_version,
    l.latest_applied_at,
    CASE
        WHEN i.object_name IS NULL THEN 'Blocked'
        WHEN COALESCE(l.latest_version, '') <> r.required_version THEN 'Version Drift'
        ELSE 'Ready'
    END AS migration_state,
    CASE
        WHEN i.object_name IS NULL THEN 'Deploy snowflake/OVERWATCH_MART_SETUP.sql.'
        WHEN COALESCE(l.latest_version, '') <> r.required_version THEN 'Rerun setup SQL or apply the matching additive migration.'
        ELSE 'No action.'
    END AS next_action
FROM required_objects r
LEFT JOIN object_inventory i
    ON i.object_name = r.object_name
LEFT JOIN ledger l
    ON TRUE
ORDER BY
    CASE migration_state WHEN 'Blocked' THEN 0 WHEN 'Version Drift' THEN 1 ELSE 2 END,
    component,
    object_name
"""


def build_schema_migration_ddl(required_version: str = OVERWATCH_SCHEMA_VERSION) -> str:
    """Return the additive setup ledger DDL used by the Snowflake setup bundle."""
    version = str(required_version).replace("'", "''")
    return f"""
CREATE TABLE IF NOT EXISTS OVERWATCH_SCHEMA_MIGRATION (
  MIGRATION_VERSION   VARCHAR(100) NOT NULL,
  MIGRATION_NAME      VARCHAR(300) NOT NULL,
  APPLIED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  APPLIED_BY          VARCHAR(200) DEFAULT CURRENT_USER(),
  SOURCE_FILE         VARCHAR(500),
  NOTES               VARCHAR(1000)
);

MERGE INTO OVERWATCH_SCHEMA_MIGRATION tgt
USING (
  SELECT
    '{version}' AS MIGRATION_VERSION,
    'Cost proof mart, procedure context, evidence feed health, alert automation, and migration ledger' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Baseline setup ledger row for the app release, including cost proof marts, procedure database/schema context, and Terraform/Jira evidence feed ingress.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);
"""
