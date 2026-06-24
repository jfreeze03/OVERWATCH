"""App-level Snowflake access and role checks for OVERWATCH.

The shell uses this module to decide whether it can render protected DBA
surfaces. Section-level dangerous actions still apply their own review gates.
"""
from __future__ import annotations

import threading

import streamlit as st
from streamlit.runtime.scriptrunner import StopException

from config import ADMIN_ACCESS_ROLES
from runtime_state import (
    CONNECTION_AVAILABLE,
    CONNECTION_UNAVAILABLE,
    CURRENT_ROLE,
    CURRENT_ROLE_SOURCE,
    LAST_ALLOWED_ROLE,
    get_state,
    set_state,
)
from utils.session import get_session


_SNOWFLAKE_AVAILABLE_PROCESS_CACHE: bool | None = None
_SNOWFLAKE_AVAILABLE_LOCK = threading.Lock()


def seed_current_role_from_secrets() -> None:
    """Use configured Snowflake role as a zero-query startup hint when present."""
    if get_state(CURRENT_ROLE):
        return
    try:
        connections = st.secrets.get("connections", {})
        snowflake_cfg = connections.get("snowflake", {}) if connections else {}
        role = str(snowflake_cfg.get("role") or "").strip().upper()
    except Exception:
        role = ""
    if role:
        set_state(CURRENT_ROLE, role)
        set_state(CURRENT_ROLE_SOURCE, "secrets")
        if current_role_allows_app_access(role):
            set_state(LAST_ALLOWED_ROLE, role)


def get_current_role() -> str:
    """Return the current Snowflake role captured for the shell."""
    return str(get_state(CURRENT_ROLE, "") or "").upper()


def get_last_allowed_role() -> str:
    """Return the last captured admin role for smooth reruns during scope changes."""
    return str(get_state(LAST_ALLOWED_ROLE, "") or "").upper()


def get_stable_current_role() -> str:
    """Return the captured role, falling back to the last allowed role during transient reruns."""
    return get_current_role() or get_last_allowed_role()


def current_role_allows_app_access(role: str) -> bool:
    """Return whether the current Snowflake role may open the admin monitor."""
    return str(role or "").strip().upper() in set(ADMIN_ACCESS_ROLES)


def refresh_current_role_for_access(connection_available: bool) -> str:
    """Capture CURRENT_ROLE before deciding whether the admin monitor can render."""
    role = get_current_role()
    if not connection_available:
        return role or get_last_allowed_role()
    if role and get_state(CURRENT_ROLE_SOURCE) == "session":
        return role
    if role and get_state(CURRENT_ROLE_SOURCE) == "secrets":
        return role
    if not role and get_last_allowed_role():
        return get_last_allowed_role()
    try:
        get_session()
    except StopException:
        set_state(CONNECTION_UNAVAILABLE, True)
    except Exception:
        pass
    return get_stable_current_role()


def cached_snowflake_available(default: bool = False) -> bool:
    """Return cached connection availability without probing Snowflake."""
    return bool(get_state(CONNECTION_AVAILABLE, default))


def admin_access_is_allowed(role: str, connection_available: bool) -> bool:
    """Allow local no-connection shells, but gate Snowflake sessions to admin roles."""
    if not connection_available:
        return True
    return current_role_allows_app_access(role or get_last_allowed_role())


def probe_snowflake_available(force: bool = False) -> bool:
    """Return whether the app appears to have a Snowflake connection path."""
    global _SNOWFLAKE_AVAILABLE_PROCESS_CACHE
    if not force and CONNECTION_AVAILABLE in st.session_state:
        return cached_snowflake_available()
    if not force and _SNOWFLAKE_AVAILABLE_PROCESS_CACHE is not None:
        available = bool(_SNOWFLAKE_AVAILABLE_PROCESS_CACHE)
        set_state(CONNECTION_AVAILABLE, available)
        set_state(CONNECTION_UNAVAILABLE, not available)
        return available
    if not force and not _SNOWFLAKE_AVAILABLE_LOCK.acquire(blocking=False):
        available = bool(_SNOWFLAKE_AVAILABLE_PROCESS_CACHE) if _SNOWFLAKE_AVAILABLE_PROCESS_CACHE is not None else False
        set_state(CONNECTION_AVAILABLE, available)
        set_state(CONNECTION_UNAVAILABLE, not available)
        return available

    available = False
    try:
        if not force:
            _SNOWFLAKE_AVAILABLE_PROCESS_CACHE = False
        if force:
            try:
                get_session()
                available = True
            except StopException:
                available = False
            except Exception:
                available = False
        else:
            try:
                from snowflake.snowpark.context import get_active_session

                get_active_session()
                available = True
            except Exception:
                available = False
    finally:
        if not force and _SNOWFLAKE_AVAILABLE_LOCK.locked():
            _SNOWFLAKE_AVAILABLE_LOCK.release()

    if available:
        set_state(CONNECTION_AVAILABLE, True)
        set_state(CONNECTION_UNAVAILABLE, False)
    elif force:
        set_state(CONNECTION_AVAILABLE, False)
        set_state(CONNECTION_UNAVAILABLE, True)
    if not force:
        _SNOWFLAKE_AVAILABLE_PROCESS_CACHE = available
    return available
