"""Snowflake session management for OVERWATCH."""

from datetime import datetime

import streamlit as st


# How long before we force a session health check.
_SESSION_TTL_MINUTES = 55

# Query tag applied to all OVERWATCH SQL for attribution and filtering.
_QUERY_TAG = "OVERWATCH"

# Session statement timeout in seconds. This stays under a common 1000s
# warehouse timeout so OVERWATCH gets cleaner failures for long scans.
_STMT_TIMEOUT_SECONDS = 840


def _has_streamlit_snowflake_secrets() -> bool:
    """Return True when Streamlit secrets define a Snowflake connection."""
    try:
        connections = st.secrets.get("connections", {})
        snowflake_cfg = connections.get("snowflake", {}) if connections else {}
        return bool(snowflake_cfg)
    except Exception:
        return False


def _make_streamlit_connection_session():
    """Create a Snowpark session from Streamlit connection secrets."""
    conn = st.connection("snowflake")
    return conn.session()


def _make_session():
    """Create a Snowflake session and apply OVERWATCH session parameters."""
    if _has_streamlit_snowflake_secrets():
        try:
            sess = _make_streamlit_connection_session()
        except Exception:
            st.warning(
                "Snowflake connection is not available from Streamlit secrets. "
                "Check the configured Snowflake account, user, role, warehouse, database, and schema."
            )
            st.stop()
    else:
        try:
            # Streamlit-in-Snowflake injects the active Snowpark session.
            from snowflake.snowpark.context import get_active_session

            sess = get_active_session()
        except Exception:
            try:
                sess = _make_streamlit_connection_session()
            except Exception:
                st.warning(
                    "Snowflake connection is not available in this environment. "
                    "Deploy OVERWATCH inside Snowflake Streamlit or configure a Streamlit Snowflake connection."
                )
                st.stop()

    for stmt in [
        f"ALTER SESSION SET QUERY_TAG = '{_QUERY_TAG}'",
        f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {_STMT_TIMEOUT_SECONDS}",
        "ALTER SESSION SET TIMEZONE = 'UTC'",
    ]:
        try:
            sess.sql(stmt).collect()
            if stmt.startswith("ALTER SESSION SET QUERY_TAG"):
                st.session_state["_overwatch_active_query_tag"] = _QUERY_TAG
        except Exception:
            pass

    _capture_current_role(sess)
    return sess


def _capture_current_role(sess) -> str:
    """Cache CURRENT_ROLE for role-based navigation without blocking startup."""
    try:
        rows = sess.sql("SELECT CURRENT_ROLE() AS R").collect()
        role = rows[0]["R"] if rows else ""
        role = str(role or "").upper()
        st.session_state["_overwatch_current_role"] = role
        return role
    except Exception:
        st.session_state.setdefault("_overwatch_current_role", "")
        return ""


def _session_is_alive(sess) -> bool:
    """Return False if the Snowflake session has been recycled or expired."""
    try:
        sess.sql("SELECT 1").collect()
        return True
    except Exception:
        return False


def get_session():
    """Return a live, validated Snowflake session."""
    now = datetime.now()
    last_created = st.session_state.get("_sf_session_created_at")
    needs_check = False
    if last_created:
        age_min = (now - last_created).total_seconds() / 60
        needs_check = age_min >= _SESSION_TTL_MINUTES
    elif "sf_session" in st.session_state:
        st.session_state["_sf_session_created_at"] = now

    if needs_check and "sf_session" in st.session_state:
        if not _session_is_alive(st.session_state["sf_session"]):
            st.session_state.pop("sf_session", None)
        st.session_state["_sf_session_created_at"] = now

    if "sf_session" not in st.session_state:
        sess = _make_session()
        st.session_state["sf_session"] = sess
        st.session_state["_sf_session_created_at"] = now
    elif "_overwatch_current_role" not in st.session_state:
        _capture_current_role(st.session_state["sf_session"])

    return st.session_state["sf_session"]


def invalidate_session():
    """Force-drop the cached Snowflake session."""
    st.session_state.pop("sf_session", None)
    st.session_state.pop("_sf_session_created_at", None)
