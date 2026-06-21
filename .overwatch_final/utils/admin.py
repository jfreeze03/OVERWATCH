"""Shared guardrails and audit helpers for live DBA actions."""
from __future__ import annotations

import hashlib
import re
from datetime import timedelta

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, ADMIN_ACCESS_ROLES
from runtime_state import (
    ACTIVE_COMPANY,
    ADMIN_ACTIONS_ENABLED,
    CURRENT_ROLE,
    OVERWATCH_ACTOR,
    get_state,
    set_state,
)
from .company_filter import get_active_environment
from .sql_safe import sql_literal  # re-exported for backward compatibility


def safe_identifier(value: str, allow_qualified: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Identifier cannot be blank")
    parts = raw.split(".") if allow_qualified else [raw]
    ident_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")
    if any(not ident_re.match(part) for part in parts):
        raise ValueError(f"Unsafe Snowflake identifier: {raw}")
    return ".".join(parts)


ADMIN_ACTIONS_KEY = ADMIN_ACTIONS_ENABLED
ADMIN_AUDIT_TABLE = "OVERWATCH_ADMIN_ACTION_AUDIT"
ADMIN_AUDIT_FQN = (
    f"{safe_identifier(ALERT_DB)}."
    f"{safe_identifier(ALERT_SCHEMA)}."
    f"{safe_identifier(ADMIN_AUDIT_TABLE)}"
)

ADMIN_ACTION_DEFAULT_ROLES = set(ADMIN_ACCESS_ROLES)


def _normalized_current_role() -> str:
    return str(get_state(CURRENT_ROLE, "") or "").strip().upper()


def admin_actions_default_enabled() -> bool:
    """Return whether Admin actions should default on."""
    return True


def initialize_admin_actions_default() -> None:
    """Keep the legacy admin-actions state key pinned on."""
    set_state(ADMIN_ACTIONS_KEY, True)


def admin_actions_enabled() -> bool:
    """Return whether live account-changing controls are enabled."""
    initialize_admin_actions_default()
    return True


def clamp_global_date_range(
    start_date,
    end_date,
    standard_days: int = 35,
    admin_days: int = 90,
) -> tuple:
    """Clamp a requested global date window to the current admin policy."""
    if not start_date or not end_date:
        return start_date, end_date, False, int(standard_days)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    max_days = int(admin_days)
    span_days = (end_date - start_date).days + 1
    if span_days <= max_days:
        return start_date, end_date, False, max_days

    clamped_start = end_date - timedelta(days=max_days - 1)
    return clamped_start, end_date, True, max_days


def admin_disabled_reason() -> str:
    return "Admin action is unavailable for the selected target."


def admin_button_disabled(disabled: bool = False) -> bool:
    """Return caller-specific disabled state in admin-only mode."""
    initialize_admin_actions_default()
    return bool(disabled)


def require_admin_enabled(action: str = "this action") -> bool:
    """Compatibility helper for admin-only mode."""
    initialize_admin_actions_default()
    return True


def _current_execution_context(session) -> dict:
    """Best-effort Snowflake execution context for audit rows."""
    try:
        rows = session.sql("""
            SELECT CURRENT_USER() AS SNOWFLAKE_USER,
                   CURRENT_ROLE() AS SNOWFLAKE_ROLE
        """).collect()
        row = rows[0] if rows else {}
        return {
            "snowflake_user": str(row["SNOWFLAKE_USER"] if "SNOWFLAKE_USER" in row else ""),
            "snowflake_role": str(row["SNOWFLAKE_ROLE"] if "SNOWFLAKE_ROLE" in row else ""),
        }
    except Exception:
        return {"snowflake_user": "", "snowflake_role": ""}


def build_admin_audit_insert_sql(
    *,
    company: str,
    environment: str,
    app_user: str,
    snowflake_user: str,
    snowflake_role: str,
    action_type: str,
    target_object: str,
    sql_text: str,
    confirmation_text: str,
    control_context: str,
    result_status: str,
    result_message: str,
) -> str:
    """Build the audit insert SQL matching OVERWATCH_MART_SETUP.sql."""
    sql_hash = hashlib.sha256(str(sql_text or "").encode("utf-8")).hexdigest()
    return f"""
        INSERT INTO {ADMIN_AUDIT_FQN} (
            COMPANY, ENVIRONMENT, APP_USER, SNOWFLAKE_USER, SNOWFLAKE_ROLE,
            ACTION_TYPE, TARGET_OBJECT, SQL_TEXT, SQL_HASH, CONFIRMATION_TEXT,
            CONTROL_CONTEXT, RESULT_STATUS, RESULT_MESSAGE
        )
        VALUES (
            {sql_literal(company, 100)},
            {sql_literal(environment, 50)},
            {sql_literal(app_user, 200)},
            {sql_literal(snowflake_user, 200)},
            {sql_literal(snowflake_role, 200)},
            {sql_literal(action_type, 100)},
            {sql_literal(target_object, 1000)},
            {sql_literal(sql_text, 8000)},
            {sql_literal(sql_hash, 80)},
            {sql_literal(confirmation_text, 1000)},
            {sql_literal(control_context, 4000)},
            {sql_literal(result_status, 40)},
            {sql_literal(result_message, 4000)}
        )
    """


def log_admin_action(
    session,
    *,
    action_type: str,
    target_object: str,
    sql_text: str,
    result_status: str,
    result_message: str,
    confirmation_text: str = "",
    control_context: str = "",
    company: str = "",
    environment: str = "",
) -> bool:
    """Write an admin action audit row when the OVERWATCH audit table exists."""
    try:
        exec_context = _current_execution_context(session)
        app_user = str(get_state(OVERWATCH_ACTOR, "OVERWATCH") or "OVERWATCH")
        company = str(company or get_state(ACTIVE_COMPANY, "") or "")
        environment = str(environment or get_active_environment() or "")
        session.sql(build_admin_audit_insert_sql(
            company=company,
            environment=environment,
            app_user=app_user,
            snowflake_user=exec_context.get("snowflake_user", ""),
            snowflake_role=exec_context.get("snowflake_role", ""),
            action_type=action_type,
            target_object=target_object,
            sql_text=sql_text,
            confirmation_text=confirmation_text,
            control_context=control_context,
            result_status=result_status,
            result_message=result_message,
        )).collect()
        return True
    except Exception:
        return False
