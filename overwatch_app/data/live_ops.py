"""Live DBA operations for v2 Panic Mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from overwatch_app.data.audit import log_audit_event
from overwatch_app.data.query import execute_sql
from overwatch_app.data.sql import sql_literal
from overwatch_app.security.rbac import RbacContext, require_permission


@dataclass(frozen=True)
class QueryKillRequest:
    query_id: str
    confirmation: str
    reason: str = ""
    company: str = "ALL"
    environment: str = "ALL"
    section: str = "DBA Control Room"
    workflow: str = "Live Mode"


def live_mode_allowed(context: RbacContext) -> bool:
    return require_permission(
        "live_panic_mode",
        context,
        audit=log_audit_event,
        section="DBA Control Room",
        workflow="Live Mode",
        target_type="live_mode",
    )


def build_query_kill_sql(query_id: str) -> str:
    return f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(query_id, 200)});"


def kill_query_with_confirmation(session: Any, request: QueryKillRequest, context: RbacContext) -> bool:
    """Cancel a query only after explicit confirmation, RBAC, and audit."""
    expected = f"KILL {request.query_id}".strip().upper()
    actual = str(request.confirmation or "").strip().upper()
    if actual != expected:
        log_audit_event(
            session,
            action_type="query_kill",
            status="DENIED",
            message="Missing query-kill confirmation.",
            rbac_context=context,
            company=request.company,
            environment=request.environment,
            section=request.section,
            workflow=request.workflow,
            target_type="query",
            target_name=request.query_id,
        )
        return False
    if not require_permission(
        "kill_query",
        context,
        audit=lambda **fields: log_audit_event(session, **fields),
        company=request.company,
        environment=request.environment,
        section=request.section,
        workflow=request.workflow,
        target_type="query",
        target_name=request.query_id,
    ):
        return False
    execute_sql(session, build_query_kill_sql(request.query_id))
    log_audit_event(
        session,
        action_type="query_kill",
        status="SUCCESS",
        message=request.reason,
        rbac_context=context,
        company=request.company,
        environment=request.environment,
        section=request.section,
        workflow=request.workflow,
        target_type="query",
        target_name=request.query_id,
    )
    return True
