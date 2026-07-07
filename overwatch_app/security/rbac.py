"""Snowflake-role based RBAC for OVERWATCH v2."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable


def _role_set(env_name: str, defaults: tuple[str, ...]) -> set[str]:
    configured = os.getenv(env_name, "")
    values = [item.strip().upper() for item in configured.split(",") if item.strip()]
    return set(values or [item.upper() for item in defaults])


ADMIN_ROLES = _role_set("OVERWATCH_ADMIN_ROLES", ("OVERWATCH_ADMIN", "ACCOUNTADMIN", "SECURITYADMIN"))
LIVE_ROLES = _role_set("OVERWATCH_LIVE_ROLES", ("OVERWATCH_LIVE_OPERATOR", "OVERWATCH_ADMIN", "ACCOUNTADMIN"))
QUERY_SEARCH_ROLES = _role_set("OVERWATCH_QUERY_SEARCH_ROLES", ("OVERWATCH_ANALYST", "OVERWATCH_ADMIN", "ACCOUNTADMIN"))
DESTRUCTIVE_ROLES = _role_set("OVERWATCH_DESTRUCTIVE_ROLES", ("OVERWATCH_ADMIN", "ACCOUNTADMIN"))
SECURITY_DETAIL_ROLES = _role_set("OVERWATCH_SECURITY_DETAIL_ROLES", ("OVERWATCH_SECURITY", "SECURITYADMIN", "OVERWATCH_ADMIN", "ACCOUNTADMIN"))
EXPORT_ROLES = _role_set("OVERWATCH_EXPORT_ROLES", ("OVERWATCH_ANALYST", "OVERWATCH_ADMIN", "ACCOUNTADMIN"))
ALERT_WRITE_ROLES = _role_set("OVERWATCH_ALERT_WRITE_ROLES", ("OVERWATCH_OPERATOR", "OVERWATCH_ADMIN", "ACCOUNTADMIN"))


@dataclass(frozen=True)
class RbacContext:
    snowflake_role: str
    snowflake_user: str = ""
    app_user: str = ""
    session_id: str = ""

    @property
    def role(self) -> str:
        return str(self.snowflake_role or "").upper()


def context_from_session(session: Any = None, *, default_role: str = "") -> RbacContext:
    """Build RBAC context from Snowflake/session data, never user-controlled UI state."""
    role = default_role or os.getenv("OVERWATCH_ROLE", "")
    user = os.getenv("OVERWATCH_USER", "")
    session_id = os.getenv("OVERWATCH_SESSION_ID", "")
    if session is not None:
        role = _session_scalar(session, "CURRENT_ROLE()") or role
        user = _session_scalar(session, "CURRENT_USER()") or user
        session_id = _session_scalar(session, "CURRENT_SESSION()") or session_id
    return RbacContext(
        snowflake_role=str(role or ""),
        snowflake_user=str(user or ""),
        app_user=str(user or os.getenv("USER", "")),
        session_id=str(session_id or ""),
    )


def _session_scalar(session: Any, expression: str) -> str:
    try:
        rows = session.sql(f"SELECT {expression} AS VALUE").collect()
        if not rows:
            return ""
        row = rows[0]
        if isinstance(row, dict):
            return str(row.get("VALUE") or "")
        return str(getattr(row, "VALUE", "") or row[0] or "")
    except Exception:
        return ""


def _has_role(context: RbacContext | None, allowed: set[str]) -> bool:
    ctx = context or context_from_session()
    return ctx.role in allowed


def can_view_admin_workflows(context: RbacContext | None = None) -> bool:
    return _has_role(context, ADMIN_ROLES)


def can_use_live_panic_mode(context: RbacContext | None = None) -> bool:
    return _has_role(context, LIVE_ROLES)


def can_run_query_search(context: RbacContext | None = None) -> bool:
    return _has_role(context, QUERY_SEARCH_ROLES | ADMIN_ROLES)


def can_kill_query(context: RbacContext | None = None) -> bool:
    return _has_role(context, DESTRUCTIVE_ROLES)


def can_change_alert_status(context: RbacContext | None = None) -> bool:
    return _has_role(context, ALERT_WRITE_ROLES | ADMIN_ROLES)


def can_view_security_details(context: RbacContext | None = None) -> bool:
    return _has_role(context, SECURITY_DETAIL_ROLES | ADMIN_ROLES)


def can_export_data(context: RbacContext | None = None) -> bool:
    return _has_role(context, EXPORT_ROLES | ADMIN_ROLES)


PERMISSIONS: dict[str, Callable[[RbacContext | None], bool]] = {
    "admin_workflow": can_view_admin_workflows,
    "live_panic_mode": can_use_live_panic_mode,
    "query_search": can_run_query_search,
    "kill_query": can_kill_query,
    "alert_status_change": can_change_alert_status,
    "security_details": can_view_security_details,
    "export_data": can_export_data,
}


def require_permission(
    permission: str,
    context: RbacContext | None,
    *,
    audit: Callable[..., bool] | None = None,
    **audit_fields: Any,
) -> bool:
    checker = PERMISSIONS.get(permission)
    allowed = bool(checker(context)) if checker else False
    if not allowed and audit is not None:
        audit(
            action_type=f"rbac_denied:{permission}",
            status="DENIED",
            message="Access denied by Snowflake role policy.",
            rbac_context=context,
            **audit_fields,
        )
    return allowed
