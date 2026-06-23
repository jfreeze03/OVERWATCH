"""Pure Account Health FQN, DDL, and migration SQL builders."""
from __future__ import annotations

from config import ACTION_QUEUE_TABLE, ALERT_DB, ALERT_SCHEMA
from sections.account_health_contracts import (
    ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE,
    CHECKLIST_HISTORY_TABLE,
)
from sections.base import lazy_util as _lazy_util


mart_object_name = _lazy_util("mart_object_name")
safe_identifier = _lazy_util("safe_identifier")


def account_health_checklist_history_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHECKLIST_HISTORY_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def account_health_action_queue_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ACTION_QUEUE_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def account_health_operability_fact_fqn(table: str = ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE) -> str:
    return mart_object_name(table)


def build_account_health_checklist_history_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHECKLIST_HISTORY_TABLE,
) -> str:
    fqn = account_health_checklist_history_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_ID       VARCHAR(64),
    SNAPSHOT_TS       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY           VARCHAR(100),
    ENVIRONMENT       VARCHAR(100),
    CHECK_NAME        VARCHAR(200),
    STATUS            VARCHAR(80),
    SEVERITY          VARCHAR(40),
    EVIDENCE          VARCHAR(2000),
    OWNER             VARCHAR(200),
    ESCALATION_TARGET VARCHAR(200),
    OWNER_SOURCE      VARCHAR(200),
    ROUTE             VARCHAR(120),
    NEXT_ACTION       VARCHAR(4000),
    PROOF_REQUIRED    VARCHAR(2000),
    ENVIRONMENT_SCOPE VARCHAR(100),
    DATABASE_CONTEXT  VARCHAR(80),
    SCOPE_CONFIDENCE  VARCHAR(160),
    SCOPE_EVIDENCE    VARCHAR(2000),
    APPROVAL_REQUIRED VARCHAR(20),
    QUEUE_READINESS   VARCHAR(80),
    QUEUE_BLOCKERS    VARCHAR(2000),
    VERIFICATION_QUERY VARCHAR(8000),
    RECOVERY_SLA_TARGET_HOURS FLOAT,
    CONTROL_READINESS VARCHAR(100),
    CONTROL_BLOCKERS  VARCHAR(2000),
    NEXT_CONTROL_ACTION VARCHAR(4000),
    HEALTH_SCORE      FLOAT,
    DETAIL_SOURCE     VARCHAR(500),
    ACTIONABLE        BOOLEAN
);"""


def build_account_health_operability_fact_ddl(table: str = ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE) -> str:
    fqn = account_health_operability_fact_fqn(table=table)
    return f"""CREATE TRANSIENT TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_DATE                   DATE,
    COMPANY                         VARCHAR(100),
    ENVIRONMENT                     VARCHAR(100),
    CONTROL_SOURCE                  VARCHAR(80),
    CHECK_NAME                      VARCHAR(200),
    ROUTE                           VARCHAR(120),
    SEVERITY                        VARCHAR(40),
    CONTROL_STATE                   VARCHAR(120),
    CONTROL_RANK                    NUMBER,
    HEALTH_SCORE                    FLOAT,
    ISSUE_ROWS                      NUMBER,
    ROUTE_BLOCKER_ROWS              NUMBER,
    QUEUE_REQUIRED_ROWS             NUMBER,
    ACCESS_HYGIENE_ROWS             NUMBER,
    FAILED_LOGIN_ROWS               NUMBER,
    PRIVILEGED_GRANT_ROWS           NUMBER,
    OPEN_ACTIONS                    NUMBER,
    OVERDUE_OPEN                    NUMBER,
    FIXED_WITHOUT_VERIFICATION      NUMBER,
    VERIFIED_CLOSURES               NUMBER,
    OWNER_APPROVAL_GAP_ROWS         NUMBER,
    RECOVERY_RISK_ROWS              NUMBER,
    NEXT_CONTROL_ACTION             VARCHAR(4000),
    LAST_ACTIVITY_TS                TIMESTAMP_NTZ,
    LOAD_TS                         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);"""


def build_account_health_operability_fact_migration_sql(
    table: str = ACCOUNT_HEALTH_OPERABILITY_FACT_TABLE,
) -> list[str]:
    fqn = account_health_operability_fact_fqn(table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_SOURCE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_RANK NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS HEALTH_SCORE FLOAT",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ISSUE_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ROUTE_BLOCKER_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS QUEUE_REQUIRED_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ACCESS_HYGIENE_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS FAILED_LOGIN_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS PRIVILEGED_GRANT_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_GAP_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS RECOVERY_RISK_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LAST_ACTIVITY_TS TIMESTAMP_NTZ",
    ]


def build_account_health_checklist_history_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHECKLIST_HISTORY_TABLE,
) -> list[str]:
    """Return additive migrations for existing Daily DBA Checklist history tables."""
    fqn = account_health_checklist_history_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ENVIRONMENT_SCOPE VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS DATABASE_CONTEXT VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS SCOPE_CONFIDENCE VARCHAR(160)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS SCOPE_EVIDENCE VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS APPROVAL_REQUIRED VARCHAR(20)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS QUEUE_READINESS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS QUEUE_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS VERIFICATION_QUERY VARCHAR(8000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS RECOVERY_SLA_TARGET_HOURS FLOAT",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_READINESS VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
    ]


__all__ = [
    "account_health_action_queue_fqn",
    "account_health_checklist_history_fqn",
    "account_health_operability_fact_fqn",
    "build_account_health_checklist_history_ddl",
    "build_account_health_checklist_history_migration_sql",
    "build_account_health_operability_fact_ddl",
    "build_account_health_operability_fact_migration_sql",
]
