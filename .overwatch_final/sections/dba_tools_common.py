# sections/dba_tools_common.py - Shared DBA Tools helpers.

import pandas as pd
import streamlit as st

from sections.dba_tools_contracts import ACCOUNT_PARAMETER_ADMIN_ROLES
from utils import (
    build_task_history_sql,
    ensure_column_alias,
    first_existing_column,
    get_active_company,
    load_task_inventory,
    scope_metadata_df,
    scope_warehouse_names,
    show_to_df,
)

def _load_button(label, key):
    return st.button(label, key=key)


def _typed_confirmation(prompt: str, expected: str, key: str) -> bool:
    entered = st.text_input(prompt, key=key, placeholder=expected)
    return str(st.session_state.get(key) or entered or "").strip() == expected


def _require_typed_confirmation(confirmed: bool, expected: str) -> bool:
    if confirmed:
        return True
    st.warning(f"Type `{expected}` exactly before running this action.")
    return False


def _current_role_allows_alter_account(role: str | None = None) -> bool:
    """Return whether the active caller role is allowed to run ALTER ACCOUNT."""
    current_role = str(
        st.session_state.get("_overwatch_current_role", "") if role is None else role
    ).strip().upper()
    return current_role in ACCOUNT_PARAMETER_ADMIN_ROLES


def _scope_warehouse_names(df: pd.DataFrame, name_col: str = "name") -> pd.DataFrame:
    """Apply ALFA/Trexis warehouse visibility to SHOW-style result sets."""
    return scope_warehouse_names(df, name_col=name_col, company=get_active_company())


def _scope_metadata_df(df: pd.DataFrame) -> pd.DataFrame:
    """Apply ALFA/Trexis visibility to SHOW-style metadata result sets."""
    return scope_metadata_df(df, company=get_active_company())


def _select_option(
    label: str,
    options: list[str],
    key: str,
    fallback: str = "",
    *,
    allow_current_outside_options: bool = True,
) -> str:
    choices = list(options or [])
    current = str(st.session_state.get(key) or fallback or "").strip()
    if choices:
        if current and current not in choices:
            if allow_current_outside_options:
                choices = [current] + choices
            else:
                current = fallback if fallback in choices else choices[0]
                st.session_state[key] = current
        index = choices.index(current) if current in choices else 0
        return str(st.selectbox(label, choices, index=index, key=key))
    return str(st.text_input(label, value=current or fallback, key=key))


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _qualified_name(*parts: str) -> str:
    return ".".join(_quote_identifier(part) for part in parts if str(part or "").strip())


def _as_bool(value, default: bool = False) -> bool:
    if value is None or str(value).lower() in ("", "nan", "none"):
        return default
    return str(value).strip().lower() in ("true", "yes", "1", "on")


def _as_int(value, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _query_context_expr() -> str:
    return """
        CASE
            WHEN database_name IS NULL OR TRIM(database_name) = '' THEN 'NO DATABASE CONTEXT'
            WHEN schema_name IS NULL OR TRIM(schema_name) = '' THEN database_name
            ELSE database_name || '.' || schema_name
        END AS query_context
    """


def _prioritize_query_context(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    frame = df.copy()
    if "QUERY_CONTEXT" not in frame.columns and "DATABASE_NAME" in frame.columns:
        db = frame["DATABASE_NAME"].fillna("").astype(str).str.strip()
        schema = (
            frame["SCHEMA_NAME"].fillna("").astype(str).str.strip()
            if "SCHEMA_NAME" in frame.columns else pd.Series([""] * len(frame), index=frame.index)
        )
        frame["QUERY_CONTEXT"] = db.where(db != "", "NO DATABASE CONTEXT")
        both = (db != "") & (schema != "")
        frame.loc[both, "QUERY_CONTEXT"] = db[both] + "." + schema[both]
    first_cols = [
        "QUERY_ID", "QUERY_CONTEXT", "DATABASE_NAME", "SCHEMA_NAME",
        "EXECUTION_STATUS", "USER_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
    ]
    ordered = [col for col in first_cols if col in frame.columns]
    ordered.extend([col for col in frame.columns if col not in ordered])
    return frame[ordered]


def _show_to_df(session, stmt: str, force_refresh: bool = False) -> pd.DataFrame:
    return show_to_df(session, stmt, force_refresh=force_refresh)


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str:
    return first_existing_column(df, candidates)


def _ensure_column_alias(df: pd.DataFrame, target: str, candidates: list[str], default="") -> pd.DataFrame:
    return ensure_column_alias(df, target, candidates, default)


def _load_task_inventory(session, force_refresh: bool = False) -> pd.DataFrame:
    return load_task_inventory(session, get_active_company(), force_refresh=force_refresh)


def _task_history_sql(session, time_predicate: str, limit: int = 500) -> str:
    """Build TASK_HISTORY SQL using only columns exposed by this account."""
    return build_task_history_sql(
        session,
        time_predicate,
        limit=limit,
        company=get_active_company(),
    )
