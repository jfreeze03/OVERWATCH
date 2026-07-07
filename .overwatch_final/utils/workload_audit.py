# utils/workload_audit.py - immutable recovery audit setup for task/procedure work
from __future__ import annotations

from config import ALERT_DB, ALERT_SCHEMA
from .query import safe_identifier


WORKLOAD_RECOVERY_AUDIT_TABLE = "OVERWATCH_WORKLOAD_RECOVERY_AUDIT"


def workload_recovery_audit_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = WORKLOAD_RECOVERY_AUDIT_TABLE,
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"
    return f"{db}.{schema}.{table}"


def build_workload_recovery_audit_ddl(db: str = ALERT_DB, schema: str = ALERT_SCHEMA) -> str:
    """Return DDL for DBA task/procedure recovery evidence."""
    db_safe = safe_identifier(db)
    schema_safe = safe_identifier(schema)
    table = safe_identifier(WORKLOAD_RECOVERY_AUDIT_TABLE)
    return f"""-- OVERWATCH immutable workload recovery audit
CREATE TABLE IF NOT EXISTS {db_safe}.{schema_safe}.{table} (
    RECOVERY_AUDIT_ID        NUMBER AUTOINCREMENT PRIMARY KEY,
    RECOVERY_AUDIT_TS        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    ACTION_ID                VARCHAR(64),
    COMPANY                  VARCHAR(100),
    ENVIRONMENT              VARCHAR(100),
    ENTITY_TYPE              VARCHAR(100),
    ENTITY_NAME              VARCHAR(500),
    INCIDENT_TYPE            VARCHAR(200),
    INCIDENT_PRIORITY        VARCHAR(100),
    WORKFLOW_ROUTE           VARCHAR(200),
    EMAIL_TARGET              VARCHAR(500),
    REVIEWED_BY           VARCHAR(200),
    REVIEW_STATUS           VARCHAR(200),
    APPROVER                 VARCHAR(200),
    REVIEW_STATUS    VARCHAR(40),
    RECOVERY_SLA_STATE       VARCHAR(100),
    RECOVERY_SLA_HOURS       FLOAT,
    RECOVERY_SLA_TARGET_HOURS FLOAT,
    TICKET_ID                VARCHAR(200),
    ACTION_TAKEN             VARCHAR(4000),
    BEFORE_STATE             VARCHAR(4000),
    AFTER_STATE              VARCHAR(4000),
    VERIFICATION_QUERY       VARCHAR(8000),
    VERIFICATION_RESULT      VARCHAR(8000),
    RECOVERY_EVIDENCE        VARCHAR(8000),
    EXECUTED_BY              VARCHAR(200) DEFAULT CURRENT_USER(),
    SOURCE                   VARCHAR(200),
    SOURCE_QUERY_ID          VARCHAR(200),
    NOTES                    VARCHAR(4000)
);

CREATE OR REPLACE VIEW {db_safe}.{schema_safe}.OVERWATCH_WORKLOAD_RECOVERY_AUDIT_LATEST_V AS
SELECT *
FROM {db_safe}.{schema_safe}.{table}
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY COALESCE(ACTION_ID, ENTITY_NAME), ENTITY_TYPE
    ORDER BY RECOVERY_AUDIT_TS DESC, RECOVERY_AUDIT_ID DESC
) = 1;"""
