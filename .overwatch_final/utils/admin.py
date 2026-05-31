"""Shared guardrails and audit helpers for live DBA actions."""
from __future__ import annotations

import hashlib

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA
from .query import safe_identifier, sql_literal


ADMIN_ACTIONS_KEY = "admin_actions_enabled"
ADMIN_AUDIT_TABLE = "OVERWATCH_ADMIN_ACTION_AUDIT"
ADMIN_AUDIT_FQN = (
    f"{safe_identifier(ALERT_DB)}."
    f"{safe_identifier(ALERT_SCHEMA)}."
    f"{safe_identifier(ADMIN_AUDIT_TABLE)}"
)


def admin_actions_enabled() -> bool:
    """Return whether live account-changing controls are enabled."""
    return bool(st.session_state.get(ADMIN_ACTIONS_KEY, False))


def admin_disabled_reason() -> str:
    return "Enable Admin actions in Settings before running live Snowflake changes."


def admin_button_disabled(disabled: bool = False) -> bool:
    """Combine a caller-specific disabled flag with the global admin gate."""
    return bool(disabled) or not admin_actions_enabled()


def require_admin_enabled(action: str = "this action") -> bool:
    """Show a consistent warning and return False when admin actions are locked."""
    if admin_actions_enabled():
        return True
    st.warning(f"Admin actions are locked. Enable Admin actions in Settings to run {action}.")
    return False


def render_admin_mode_control() -> None:
    """Render the global live-action toggle."""
    st.toggle(
        "Enable Admin actions",
        key=ADMIN_ACTIONS_KEY,
        help=(
            "Allows live ALTER, EXECUTE, RESUME, SUSPEND, and CANCEL operations. "
            "Keep off for read-only demos and leadership reviews."
        ),
    )


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
        app_user = str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")
        company = str(company or st.session_state.get("active_company", "") or "")
        environment = str(environment or st.session_state.get("active_environment", "") or "")
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
