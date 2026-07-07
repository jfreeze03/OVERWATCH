"""Writable Alert Center actions for v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from overwatch_app.data.audit import log_audit_event
from overwatch_app.data.query import execute_sql
from overwatch_app.data.sql import sql_literal
from overwatch_app.security.rbac import RbacContext, can_change_alert_status, require_permission


ALERT_STATE_TABLE = "OVERWATCH_ALERT_STATE"
ALERT_HISTORY_TABLE = "OVERWATCH_ALERT_STATE_HISTORY"

ALERT_STATUSES = {
    "acknowledge": "ACKNOWLEDGED",
    "in_progress": "IN_PROGRESS",
    "resolve": "RESOLVED",
    "suppress": "SUPPRESSED",
    "reopen": "OPEN",
}


@dataclass(frozen=True)
class AlertActionRequest:
    alert_id: str
    action: str
    note: str = ""
    ticket_id: str = ""
    company: str = "ALL"
    environment: str = "ALL"
    section: str = "Alert Center"
    workflow: str = "Active Alerts"
    target_name: str = ""


def build_alert_state_tables_ddl() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {ALERT_STATE_TABLE} (
  ALERT_ID             VARCHAR(200) PRIMARY KEY,
  STATUS               VARCHAR(40),
  STATUS_TS            TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
  STATUS_BY            VARCHAR(200),
  TICKET_ID            VARCHAR(200),
  LAST_NOTE            VARCHAR(4000),
  UPDATED_AT           TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {ALERT_HISTORY_TABLE} (
  EVENT_ID             VARCHAR(64),
  ALERT_ID             VARCHAR(200),
  STATUS               VARCHAR(40),
  STATUS_TS            TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
  STATUS_BY            VARCHAR(200),
  TICKET_ID            VARCHAR(200),
  NOTE                 VARCHAR(4000),
  ACTION_TYPE          VARCHAR(100)
);
""".strip()


def normalize_alert_action(action: str) -> str:
    key = str(action or "").strip().lower().replace(" ", "_")
    if key not in ALERT_STATUSES:
        raise ValueError(f"Unsupported alert action: {action}")
    return key


def build_alert_status_sql(request: AlertActionRequest, context: RbacContext) -> str:
    action = normalize_alert_action(request.action)
    status = ALERT_STATUSES[action]
    alert_id = sql_literal(request.alert_id, 200)
    status_lit = sql_literal(status, 40)
    actor = sql_literal(context.snowflake_user or context.app_user or context.snowflake_role, 200)
    note = sql_literal(request.note, 4000)
    ticket = sql_literal(request.ticket_id, 200)
    return f"""
MERGE INTO {ALERT_STATE_TABLE} tgt
USING (SELECT {alert_id} AS ALERT_ID) src
ON tgt.ALERT_ID = src.ALERT_ID
WHEN MATCHED THEN UPDATE SET
  STATUS = {status_lit},
  STATUS_TS = CURRENT_TIMESTAMP(),
  STATUS_BY = {actor},
  TICKET_ID = COALESCE(NULLIF({ticket}, ''), tgt.TICKET_ID),
  LAST_NOTE = COALESCE(NULLIF({note}, ''), tgt.LAST_NOTE),
  UPDATED_AT = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  ALERT_ID, STATUS, STATUS_TS, STATUS_BY, TICKET_ID, LAST_NOTE, UPDATED_AT
) VALUES (
  {alert_id}, {status_lit}, CURRENT_TIMESTAMP(), {actor}, NULLIF({ticket}, ''), NULLIF({note}, ''), CURRENT_TIMESTAMP()
);

INSERT INTO {ALERT_HISTORY_TABLE} (
  EVENT_ID, ALERT_ID, STATUS, STATUS_TS, STATUS_BY, TICKET_ID, NOTE, ACTION_TYPE
)
SELECT UUID_STRING(), {alert_id}, {status_lit}, CURRENT_TIMESTAMP(), {actor}, NULLIF({ticket}, ''), NULLIF({note}, ''), {sql_literal(action, 100)};
""".strip()


def apply_alert_action(
    session: Any,
    request: AlertActionRequest,
    context: RbacContext,
) -> bool:
    """Apply an alert action with RBAC and audit logging."""
    if not require_permission(
        "alert_status_change",
        context,
        audit=lambda **fields: log_audit_event(session, **fields),
        company=request.company,
        environment=request.environment,
        section=request.section,
        workflow=request.workflow,
        target_type="alert",
        target_name=request.alert_id,
    ):
        return False
    if not can_change_alert_status(context):
        return False
    execute_sql(session, build_alert_status_sql(request, context))
    log_audit_event(
        session,
        action_type=f"alert:{normalize_alert_action(request.action)}",
        status="SUCCESS",
        message=request.note,
        rbac_context=context,
        company=request.company,
        environment=request.environment,
        section=request.section,
        workflow=request.workflow,
        target_type="alert",
        target_name=request.alert_id,
    )
    return True
