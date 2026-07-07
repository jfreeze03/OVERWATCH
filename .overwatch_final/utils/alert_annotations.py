"""Alert annotation and triage-view DDL helpers."""
from __future__ import annotations

from config import ALERT_DB, ALERT_SCHEMA, ALERT_TABLE
from .query import safe_identifier


ANNOTATION_TABLE = "OVERWATCH_ANNOTATIONS"


def build_annotation_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Generate DDL for the OVERWATCH_ANNOTATIONS table."""
    return f"""-- OVERWATCH Annotation System
-- Prevents re-alerting on known events such as high-volume validation windows, deployments, or planned maintenance.

CREATE TABLE IF NOT EXISTS {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(ANNOTATION_TABLE)} (
    ANNOTATION_ID   NUMBER AUTOINCREMENT PRIMARY KEY,
    CREATED_BY      VARCHAR(200),
    CREATED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    ENTITY          VARCHAR(500),
    ENTITY_TYPE     VARCHAR(50),
    WINDOW_START    TIMESTAMP_NTZ NOT NULL,
    WINDOW_END      TIMESTAMP_NTZ NOT NULL,
    ANNOTATION_TYPE VARCHAR(100),
    DESCRIPTION     VARCHAR(2000),
    SUPPRESS_ALERTS BOOLEAN DEFAULT TRUE,
    ACTIVE          BOOLEAN DEFAULT TRUE
);
"""


def build_alert_triage_view_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
) -> str:
    db = safe_identifier(db)
    schema = safe_identifier(schema)
    table = safe_identifier(table)
    return f"""CREATE OR REPLACE VIEW {db}.{schema}.OVERWATCH_ALERT_TRIAGE_V AS
WITH base AS (
    SELECT
        a.*,
        COALESCE(r.OWNER, a.OWNER, 'DBA') AS ROUTED_OWNER,
        NULL AS EMAIL_TARGET,
        COALESCE(r.OWNER, a.OWNER, 'DBA Review') AS REVIEWED_BY,
        NULL AS REVIEWED_BY,
        NULL AS REVIEW_STATUS,
        COALESCE(r.OWNER, a.ESCALATED_TO, a.OWNER, 'DBA Lead') AS WORKFLOW_ROUTE,
        CASE WHEN r.OWNER IS NOT NULL THEN 'ALERT_RULE' ELSE 'ALERT_ROW' END AS ALLOCATION_SOURCE,
        CASE WHEN r.OWNER IS NOT NULL THEN 'Matched alert rule owner' ELSE 'Using alert row owner or DBA fallback' END AS ALLOCATION_BASIS,
        COALESCE(
            r.SLA_HOURS,
            CASE UPPER(COALESCE(a.SEVERITY, 'Medium'))
                WHEN 'CRITICAL' THEN 4
                WHEN 'HIGH' THEN 8
                WHEN 'LOW' THEN 72
                ELSE 24
            END
        ) AS SLA_TARGET_HOURS,
        GREATEST(0, COALESCE(DATEDIFF('hour', a.ALERT_TS, CURRENT_TIMESTAMP()), 0)) AS ALERT_AGE_HOURS,
        COALESCE(r.ROUTE, 'Alert Center') AS ALERT_ROUTE,
        COALESCE(r.RUNBOOK, a.SUGGESTED_ACTION, 'Review the Alert Center issue and route it through the DBA action queue.') AS ALERT_RUNBOOK
    FROM {db}.{schema}.{table} a
    LEFT JOIN {db}.{schema}.OVERWATCH_ALERT_RULES r
      ON UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) = UPPER(COALESCE(r.ALERT_TYPE, r.CATEGORY, ''))
     AND COALESCE(r.IS_ACTIVE, TRUE)
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY COALESCE(TO_VARCHAR(a.ALERT_ID), TO_VARCHAR(a.ALERT_TS), COALESCE(a.ENTITY_NAME, a.ENTITY, 'UNKNOWN'))
        ORDER BY COALESCE(r.SLA_HOURS, 0) DESC
    ) = 1
),
sla AS (
    SELECT
        base.*,
        CASE
            WHEN UPPER(REPLACE(COALESCE(STATUS, 'New'), ' ', '_')) IN ('FIXED', 'IGNORED', 'RESOLVED') THEN 'Closed'
            WHEN ALERT_AGE_HOURS > SLA_TARGET_HOURS THEN 'Overdue'
            WHEN ALERT_AGE_HOURS >= (SLA_TARGET_HOURS * 0.75) THEN 'Due Soon'
            ELSE 'Within SLA'
        END AS SLA_STATE
    FROM base
)
SELECT
    sla.*,
    CASE
        WHEN SLA_STATE = 'Overdue' AND UPPER(COALESCE(SEVERITY, 'Medium')) IN ('CRITICAL', 'HIGH') THEN COALESCE(WORKFLOW_ROUTE, ESCALATED_TO, 'DBA Lead')
        ELSE COALESCE(WORKFLOW_ROUTE, ROUTED_OWNER, OWNER, 'DBA')
    END AS WORKFLOW_ROUTE,
    (
        CASE UPPER(COALESCE(SEVERITY, 'Medium'))
            WHEN 'CRITICAL' THEN 0
            WHEN 'HIGH' THEN 1
            WHEN 'MEDIUM' THEN 2
            WHEN 'LOW' THEN 3
            ELSE 4
        END * 100
        + CASE SLA_STATE
            WHEN 'Overdue' THEN 0
            WHEN 'Due Soon' THEN 1
            WHEN 'Within SLA' THEN 2
            WHEN 'Closed' THEN 9
            ELSE 5
          END * 10
        + CASE UPPER(REPLACE(COALESCE(STATUS, 'New'), ' ', '_'))
            WHEN 'NEW' THEN 0
            WHEN 'EMAIL_READY' THEN 0
            WHEN 'EMAIL_QUEUED' THEN 0
            WHEN 'OPEN' THEN 0
            WHEN 'ACTIVE' THEN 0
            WHEN 'PENDING' THEN 0
            WHEN 'ACKNOWLEDGED' THEN 1
            WHEN 'IN_PROGRESS' THEN 1
            WHEN 'FIXED' THEN 3
            WHEN 'RESOLVED' THEN 3
            WHEN 'IGNORED' THEN 4
            ELSE 2
          END
    ) AS TRIAGE_PRIORITY
FROM sla;"""
