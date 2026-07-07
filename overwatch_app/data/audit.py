"""V2 app audit logging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from overwatch_app.data.query import execute_sql
from overwatch_app.data.sql import sql_literal
from overwatch_app.security.rbac import RbacContext

LOGGER = logging.getLogger(__name__)

AUDIT_TABLE = "OVERWATCH_APP_AUDIT_LOG"


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    event_ts: datetime
    app_user: str
    snowflake_user: str
    snowflake_role: str
    company: str
    environment: str
    section: str
    workflow: str
    action_type: str
    target_type: str
    target_name: str
    status: str
    message: str
    query_hash: str
    session_id: str


def build_audit_table_ddl(table_name: str = AUDIT_TABLE) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {table_name} (
  EVENT_ID        VARCHAR(64) PRIMARY KEY,
  EVENT_TS        TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
  APP_USER        VARCHAR(200),
  SNOWFLAKE_USER  VARCHAR(200),
  SNOWFLAKE_ROLE  VARCHAR(200),
  COMPANY         VARCHAR(100),
  ENVIRONMENT     VARCHAR(100),
  SECTION         VARCHAR(100),
  WORKFLOW        VARCHAR(100),
  ACTION_TYPE     VARCHAR(100),
  TARGET_TYPE     VARCHAR(100),
  TARGET_NAME     VARCHAR(500),
  STATUS          VARCHAR(40),
  MESSAGE         VARCHAR(4000),
  QUERY_HASH      VARCHAR(128),
  SESSION_ID      VARCHAR(128)
);
""".strip()


def make_audit_event(
    *,
    action_type: str,
    status: str,
    message: str = "",
    rbac_context: RbacContext | None = None,
    company: str = "ALL",
    environment: str = "ALL",
    section: str = "",
    workflow: str = "",
    target_type: str = "",
    target_name: str = "",
    query_hash: str = "",
) -> AuditEvent:
    ctx = rbac_context or RbacContext(snowflake_role="")
    return AuditEvent(
        event_id=uuid4().hex,
        event_ts=datetime.now(timezone.utc),
        app_user=ctx.app_user,
        snowflake_user=ctx.snowflake_user,
        snowflake_role=ctx.snowflake_role,
        company=company,
        environment=environment,
        section=section,
        workflow=workflow,
        action_type=action_type,
        target_type=target_type,
        target_name=target_name,
        status=status,
        message=message,
        query_hash=query_hash,
        session_id=ctx.session_id,
    )


def build_audit_insert_sql(event: AuditEvent, table_name: str = AUDIT_TABLE) -> str:
    ts = event.event_ts.isoformat()
    return f"""
INSERT INTO {table_name} (
  EVENT_ID, EVENT_TS, APP_USER, SNOWFLAKE_USER, SNOWFLAKE_ROLE,
  COMPANY, ENVIRONMENT, SECTION, WORKFLOW, ACTION_TYPE, TARGET_TYPE,
  TARGET_NAME, STATUS, MESSAGE, QUERY_HASH, SESSION_ID
)
SELECT
  {sql_literal(event.event_id, 64)},
  TO_TIMESTAMP_TZ({sql_literal(ts, 64)}),
  {sql_literal(event.app_user, 200)},
  {sql_literal(event.snowflake_user, 200)},
  {sql_literal(event.snowflake_role, 200)},
  {sql_literal(event.company, 100)},
  {sql_literal(event.environment, 100)},
  {sql_literal(event.section, 100)},
  {sql_literal(event.workflow, 100)},
  {sql_literal(event.action_type, 100)},
  {sql_literal(event.target_type, 100)},
  {sql_literal(event.target_name, 500)},
  {sql_literal(event.status, 40)},
  {sql_literal(event.message, 4000)},
  {sql_literal(event.query_hash, 128)},
  {sql_literal(event.session_id, 128)};
""".strip()


def log_audit_event(session: Any = None, **fields: Any) -> bool:
    """Write an audit event, returning False instead of blocking UI on failure."""
    event = make_audit_event(**fields)
    try:
        return execute_sql(session, build_audit_insert_sql(event))
    except Exception as exc:
        LOGGER.warning("OVERWATCH audit insert failed: %s", exc)
        return False
