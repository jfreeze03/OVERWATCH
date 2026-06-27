# sections/task_management_common.py - Shared Task Management controls/helpers
import time

import pandas as pd
import streamlit as st

from utils import (
    format_snowflake_error,
    get_active_company,
    get_active_environment,
    load_task_inventory,
    log_admin_action,
    run_query,
)

_EXECUTION_CONTEXT_CACHE_TTL_SECONDS = 300

def _qualified_name(*parts: str) -> str:
    return ".".join(f'"{str(part).replace(chr(34), chr(34) + chr(34))}"' for part in parts)

def _typed_confirmation(prompt: str, expected: str, key: str) -> bool:
    entered = st.text_input(prompt, key=key, placeholder=expected)
    return str(st.session_state.get(key) or entered or "").strip() == expected

def _require_typed_confirmation(confirmed: bool, expected: str) -> bool:
    if confirmed:
        return True
    st.warning(f"Type `{expected}` exactly before running this action.")
    return False

def _show_tasks(session, force_refresh: bool = False) -> pd.DataFrame:
    return load_task_inventory(session, get_active_company(), force_refresh=force_refresh)

def _run_admin_sql_list(
    session,
    sql_statements: list[str],
    action_type: str,
    object_name: str,
    confirmation_text: str = "",
    control_context: str = "",
) -> tuple[int, list[str]]:
    errors: list[str] = []
    completed = 0
    for sql_text in sql_statements:
        try:
            # DIRECT_SQL_ADMIN_OK boundary=metadata reason=metadata_probe budget=advanced_diagnostics
            session.sql(sql_text).collect()
            _log_admin_action(
                session,
                action_type,
                object_name,
                sql_text,
                "SUCCESS",
                "Statement completed.",
                confirmation_text=confirmation_text,
                control_context=control_context,
            )
            completed += 1
        except Exception as e:
            message = format_snowflake_error(e)
            _log_admin_action(
                session,
                action_type,
                object_name,
                sql_text,
                "FAILED",
                message,
                confirmation_text=confirmation_text,
                control_context=control_context,
            )
            errors.append(f"{sql_text}: {message}")
    return completed, errors

def _current_execution_context(session) -> dict:
    app_user = str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")
    role = str(st.session_state.get("_overwatch_current_role", "") or "")
    cache_key = "_task_management_execution_context_cache"
    cached = st.session_state.get(cache_key, {})
    if cached:
        age_sec = time.time() - float(cached.get("loaded_at", 0) or 0)
        data = cached.get("data")
        if age_sec <= _EXECUTION_CONTEXT_CACHE_TTL_SECONDS and isinstance(data, dict):
            return {
                "snowflake_user": app_user,
                "snowflake_role": role,
                "snowflake_warehouse": str(data.get("snowflake_warehouse", "") or ""),
            }
    warehouse = ""
    try:
        # DIRECT_SQL_ADMIN_OK boundary=metadata reason=metadata_probe budget=advanced_diagnostics
        row = session.sql("SELECT CURRENT_WAREHOUSE() AS current_warehouse").collect()[0]
        warehouse = str(row["CURRENT_WAREHOUSE"] or "")
    except Exception:
        warehouse = ""
    data = {
        "snowflake_user": app_user,
        "snowflake_role": role,
        "snowflake_warehouse": warehouse,
    }
    st.session_state[cache_key] = {"loaded_at": time.time(), "data": data}
    return data

def _log_admin_action(
    session,
    action_type: str,
    object_name: str,
    sql_text: str,
    status: str,
    message: str,
    confirmation_text: str = "",
    control_context: str = "",
) -> None:
    log_admin_action(
        session,
        action_type=action_type,
        target_object=object_name,
        sql_text=sql_text,
        result_status=status,
        result_message=message,
        confirmation_text=confirmation_text,
        control_context=control_context,
        company=get_active_company(),
        environment=get_active_environment(),
    )

__all__ = ['_qualified_name', '_typed_confirmation', '_require_typed_confirmation', '_show_tasks', '_run_admin_sql_list', '_current_execution_context', '_log_admin_action', '_EXECUTION_CONTEXT_CACHE_TTL_SECONDS']
