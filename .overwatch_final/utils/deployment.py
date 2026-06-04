# utils/deployment.py - release and mart migration readiness helpers
from __future__ import annotations

import pandas as pd


OVERWATCH_SCHEMA_VERSION = "2026.06.03-operating-surfaces"
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
            "COMPONENT": "FinOps verification",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_COST_SAVINGS_VERIFICATION_RUN",
            "WHY_IT_MATTERS": "Separates estimated savings from verified savings with metering evidence.",
            "READY_CRITERIA": "Verification table, procedure, view, and scheduled task are deployed.",
        },
        {
            "COMPONENT": "Change evidence integration",
            "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
            "REQUIRED_OBJECT": "OVERWATCH_SOURCE_CONTROL_CHANGE",
            "WHY_IT_MATTERS": "Connects Snowflake drift to Terraform/Git evidence and approval context.",
            "READY_CRITERIA": "Source-control and ITSM evidence tables exist.",
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
        ('FinOps verification', 'OVERWATCH_COST_SAVINGS_VERIFICATION_RUN', 'TABLE', '{version}'),
        ('FinOps verification', 'OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V', 'VIEW', '{version}'),
        ('Change evidence integration', 'OVERWATCH_SOURCE_CONTROL_CHANGE', 'TABLE', '{version}'),
        ('Change evidence integration', 'OVERWATCH_ITSM_TICKET', 'TABLE', '{version}'),
        ('Schema migration ledger', 'OVERWATCH_SCHEMA_MIGRATION', 'TABLE', '{version}')
    AS t(component, object_name, object_type, required_version)
),
object_inventory AS (
    SELECT table_name AS object_name, table_type AS object_type
    FROM {db}.INFORMATION_SCHEMA.TABLES
    WHERE table_schema = '{sch}'
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
    'Dashboard polish, alert automation, FinOps controls, role UX, and migration ledger' AS MIGRATION_NAME,
    'snowflake/OVERWATCH_MART_SETUP.sql' AS SOURCE_FILE,
    'Baseline setup ledger row for the app release.' AS NOTES
) src
ON tgt.MIGRATION_VERSION = src.MIGRATION_VERSION
WHEN MATCHED THEN UPDATE SET
  MIGRATION_NAME = src.MIGRATION_NAME,
  SOURCE_FILE = src.SOURCE_FILE,
  NOTES = src.NOTES
WHEN NOT MATCHED THEN INSERT (MIGRATION_VERSION, MIGRATION_NAME, SOURCE_FILE, NOTES)
VALUES (src.MIGRATION_VERSION, src.MIGRATION_NAME, src.SOURCE_FILE, src.NOTES);
"""
