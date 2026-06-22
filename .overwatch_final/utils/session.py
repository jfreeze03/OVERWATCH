"""Snowflake session management for OVERWATCH."""

from datetime import datetime
import os
import re

import streamlit as st

from runtime_state import (
    ACTIVE_COMPANY,
    ACTIVE_QUERY_TAG,
    ACTIVE_QUERY_TAG_SECTION,
    ACTIVE_SECTION,
    BROAD_ROLE_WARNING_SHOWN,
    CONNECTION_AVAILABLE,
    CONNECTION_SURFACE,
    CONNECTION_UNAVAILABLE,
    CURRENT_ROLE,
    CURRENT_ROLE_SOURCE,
    DETAILED_QUERY_TAGS_ENABLED,
    GLOBAL_ENVIRONMENT,
    NAV_SECTION,
    PERF_RUN_ID,
    SF_SESSION,
    SF_SESSION_CREATED_AT,
    ensure_default_state,
    get_state,
    pop_state,
    set_state,
)


# How long before we force a session health check.
_SESSION_TTL_MINUTES = 55

# Query tag applied to all OVERWATCH SQL for attribution and filtering.
_QUERY_TAG = "OVERWATCH"
_QUERY_TAG_MAX_LEN = 250

# Session statement timeout in seconds. This stays under a common 1000s
# warehouse timeout so OVERWATCH gets cleaner failures for long scans.
_STMT_TIMEOUT_SECONDS = 840


def _perf_run_id() -> str:
    """Return optional release-validation run id for query attribution."""
    try:
        value = get_state(PERF_RUN_ID, "")
    except Exception:
        value = ""
    value = value or os.environ.get("OVERWATCH_PERF_RUN_ID", "")
    return re.sub(r"[^A-Za-z0-9_.:-]+", "", str(value or ""))[:80]


def _detailed_query_tags_enabled() -> bool:
    """Return whether section-aware query tags should be applied."""
    try:
        return bool(get_state(DETAILED_QUERY_TAGS_ENABLED, True))
    except Exception:
        return True


def _query_tag_part(value: object, max_len: int = 72) -> str:
    """Normalize a query tag component while keeping it human-readable."""
    text = re.sub(r"[^A-Za-z0-9 _&:/.-]+", "", str(value or "")).strip()
    text = re.sub(r"\s+", "_", text)
    return (text or "Unknown")[:max_len]


def _active_section_label(section: str = "") -> str:
    """Resolve the current section label without importing app routing code."""
    if section:
        return str(section)
    for key in (ACTIVE_SECTION, NAV_SECTION):
        try:
            value = str(get_state(key) or "").strip()
        except Exception:
            value = ""
        if value:
            return value
    return "Unknown"


def _section_from_query_tag(query_tag: str) -> str:
    match = re.search(r"(?:^|\|)section=([^|]+)", str(query_tag or ""))
    return match.group(1) if match else ""


def build_overwatch_query_tag(
    section: str = "",
    *,
    ttl_key: str = "",
    tier: str = "",
) -> str:
    """Build a compact Snowflake QUERY_TAG for OVERWATCH cost attribution."""
    if not _detailed_query_tags_enabled():
        return _QUERY_TAG

    section_part = _query_tag_part(_active_section_label(section))
    company_part = _query_tag_part(get_state(ACTIVE_COMPANY, "ALFA"), 24)
    environment = str(get_state(GLOBAL_ENVIRONMENT, "") or "").strip()
    tier_part = _query_tag_part(tier, 20) if tier else ""
    parts = [
        _QUERY_TAG,
        f"section={section_part}",
        f"company={company_part}",
    ]
    if environment:
        parts.append(f"env={_query_tag_part(environment, 24)}")
    if tier_part:
        parts.append(f"tier={tier_part}")
    perf = _perf_run_id()
    if perf:
        parts.append(f"perf={perf[:48]}")
    return "|".join(parts)[:_QUERY_TAG_MAX_LEN]


def apply_overwatch_query_tag(session=None, query_tag: str = "", *, section: str = "") -> None:
    """Record OVERWATCH query attribution locally without mutating Snowflake session state."""
    tag = str(query_tag or build_overwatch_query_tag(section=section))[:_QUERY_TAG_MAX_LEN] or _QUERY_TAG
    if get_state(ACTIVE_QUERY_TAG) == tag:
        return
    set_state(ACTIVE_QUERY_TAG, tag)
    set_state(
        ACTIVE_QUERY_TAG_SECTION,
        _section_from_query_tag(tag) or _query_tag_part(_active_section_label(section))
    )


def _ensure_active_section_query_tag(session) -> None:
    """Keep direct Snowpark SQL calls attributed to the active section."""
    if not _detailed_query_tags_enabled():
        apply_overwatch_query_tag(session, _QUERY_TAG)
        return

    active_section = _active_section_label()
    active_part = _query_tag_part(active_section)
    current_section = str(get_state(ACTIVE_QUERY_TAG_SECTION) or "")
    current_tag = str(get_state(ACTIVE_QUERY_TAG) or "")
    if current_section == active_part and current_tag.startswith(f"{_QUERY_TAG}|"):
        return

    apply_overwatch_query_tag(
        session,
        build_overwatch_query_tag(section=active_section, tier="section"),
        section=active_section,
    )


def _has_streamlit_snowflake_secrets() -> bool:
    """Return True when Streamlit secrets define a Snowflake connection."""
    try:
        connections = st.secrets.get("connections", {})
        snowflake_cfg = connections.get("snowflake", {}) if connections else {}
        return bool(snowflake_cfg)
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def _quiet_streamlit_snowflake_connection():
    """Create Streamlit's Snowflake connection without exposing framework spinner text."""
    from streamlit.connections import SnowflakeConnection

    return SnowflakeConnection(connection_name="snowflake")


def _make_streamlit_connection_session():
    """Create a Snowpark session from Streamlit connection secrets."""
    conn = _quiet_streamlit_snowflake_connection()
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

    try:
        sess.sql(
            "ALTER SESSION SET "
            f"STATEMENT_TIMEOUT_IN_SECONDS = {_STMT_TIMEOUT_SECONDS}, "
            "TIMEZONE = 'UTC'"
        ).collect()
        set_state(ACTIVE_QUERY_TAG, _QUERY_TAG)
        set_state(ACTIVE_QUERY_TAG_SECTION, "")
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
        set_state(CURRENT_ROLE, role)
        set_state(CURRENT_ROLE_SOURCE, "session")
        _warn_on_broad_role(role)
        return role
    except Exception:
        ensure_default_state(CURRENT_ROLE, "")
        ensure_default_state(CURRENT_ROLE_SOURCE, "unknown")
        return ""


def _warn_on_broad_role(role: str) -> None:
    """Warn once when OVERWATCH is running with a break-glass admin role."""
    if str(role or "").upper() not in {"ACCOUNTADMIN", "ORGADMIN", "SECURITYADMIN"}:
        return
    try:
        if get_state(BROAD_ROLE_WARNING_SHOWN):
            return
        st.warning(
            "OVERWATCH is running with a broad administrator role. "
            "For app access, use SNOW_ACCOUNTADMINS or SNOW_SYSADMINS."
        )
        set_state(BROAD_ROLE_WARNING_SHOWN, True)
    except Exception:
        pass


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
    last_created = get_state(SF_SESSION_CREATED_AT)
    needs_check = False
    if last_created:
        age_min = (now - last_created).total_seconds() / 60
        needs_check = age_min >= _SESSION_TTL_MINUTES
    elif get_state(SF_SESSION) is not None:
        set_state(SF_SESSION_CREATED_AT, now)

    session = get_state(SF_SESSION)
    if needs_check and session is not None:
        if not _session_is_alive(session):
            pop_state(SF_SESSION, None)
            session = None
        set_state(SF_SESSION_CREATED_AT, now)

    if session is None:
        sess = _make_session()
        set_state(SF_SESSION, sess)
        set_state(SF_SESSION_CREATED_AT, now)
        session = sess
    elif get_state(CURRENT_ROLE) is None:
        _capture_current_role(session)

    _ensure_active_section_query_tag(session)
    return session


def snowflake_connection_known_unavailable() -> bool:
    """Return True when startup already proved Snowflake is unavailable."""
    return bool(
        get_state(CONNECTION_UNAVAILABLE)
        or get_state(CONNECTION_AVAILABLE) is False
    )


def get_session_for_action(
    action: str,
    *,
    surface: str = "OVERWATCH",
    offline_note: str = "Static setup and source summaries remain available without a connection.",
):
    """Return a session for explicit live actions, or None with a consistent UI guard."""
    if snowflake_connection_known_unavailable():
        st.info(f"Snowflake connection is required to {action}. {offline_note}")
        return None
    try:
        return get_session()
    except BaseException as exc:
        if exc.__class__.__name__ != "StopException":
            raise
        st.info(f"Snowflake connection is required to {action}. {offline_note}")
        set_state(CONNECTION_UNAVAILABLE, True)
        set_state(CONNECTION_AVAILABLE, False)
        set_state(CONNECTION_SURFACE, surface)
        return None


def invalidate_session():
    """Force-drop the cached Snowflake session."""
    pop_state(SF_SESSION, None)
    pop_state(SF_SESSION_CREATED_AT, None)
