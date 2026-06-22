"""App-level Snowflake access and role checks for OVERWATCH.

The shell uses this module to decide whether it can render protected DBA
surfaces. Section-level dangerous actions still apply their own review gates.
"""
from __future__ import annotations

import streamlit as st
from streamlit.runtime.scriptrunner import StopException

from config import ADMIN_ACCESS_ROLES
from runtime_state import (
    CONNECTION_AVAILABLE,
    CONNECTION_UNAVAILABLE,
    CURRENT_ROLE,
    CURRENT_ROLE_SOURCE,
    get_state,
    set_state,
)
from utils.session import get_session


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


def get_current_role() -> str:
    """Return the current Snowflake role captured for the shell."""
    return str(get_state(CURRENT_ROLE, "") or "").upper()


def current_role_allows_app_access(role: str) -> bool:
    """Return whether the current Snowflake role may open the admin monitor."""
    return str(role or "").strip().upper() in set(ADMIN_ACCESS_ROLES)


def refresh_current_role_for_access(connection_available: bool) -> str:
    """Capture CURRENT_ROLE before deciding whether the admin monitor can render."""
    role = get_current_role()
    if not connection_available:
        return role
    if role and get_state(CURRENT_ROLE_SOURCE) == "session":
        return role
    if role and get_state(CURRENT_ROLE_SOURCE) == "secrets":
        return role
    try:
        get_session()
    except StopException:
        set_state(CONNECTION_UNAVAILABLE, True)
    except Exception:
        pass
    return get_current_role()


def cached_snowflake_available(default: bool = False) -> bool:
    """Return cached connection availability without probing Snowflake."""
    return bool(get_state(CONNECTION_AVAILABLE, default))


def admin_access_is_allowed(role: str, connection_available: bool) -> bool:
    """Allow local no-connection shells, but gate Snowflake sessions to admin roles."""
    if not connection_available:
        return True
    return current_role_allows_app_access(role)


def probe_snowflake_available(force: bool = False) -> bool:
    """Return whether the app appears to have a Snowflake connection path."""
    if not force and CONNECTION_AVAILABLE in st.session_state:
        return cached_snowflake_available()

    available = False
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

    if available:
        set_state(CONNECTION_AVAILABLE, True)
        set_state(CONNECTION_UNAVAILABLE, False)
    elif force:
        set_state(CONNECTION_AVAILABLE, False)
        set_state(CONNECTION_UNAVAILABLE, True)
    return available
