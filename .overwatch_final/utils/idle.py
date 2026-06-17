"""Idle-query guard for OVERWATCH Snowflake sessions."""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st


DEFAULT_IDLE_TIMEOUT_SECONDS = 15 * 60
MIN_IDLE_TIMEOUT_SECONDS = 60
MAX_IDLE_TIMEOUT_SECONDS = 8 * 60 * 60

_LAST_ACTIVITY_KEY = "_overwatch_last_operator_activity_ts"
_PAUSED_KEY = "_overwatch_queries_paused"
_PAUSED_AT_KEY = "_overwatch_query_paused_at_ts"
_PAUSE_REASON_KEY = "_overwatch_query_pause_reason"
_TIMEOUT_KEY = "overwatch_idle_timeout_seconds"
_WARNING_KEY = "_overwatch_query_pause_warning_shown"


def clamp_idle_timeout_seconds(value: object, default: int = DEFAULT_IDLE_TIMEOUT_SECONDS) -> int:
    """Return a bounded idle timeout in seconds."""
    try:
        seconds = int(value)
    except Exception:
        seconds = int(default)
    return max(MIN_IDLE_TIMEOUT_SECONDS, min(MAX_IDLE_TIMEOUT_SECONDS, seconds))


def get_idle_timeout_seconds() -> int:
    """Return the configured OVERWATCH idle timeout."""
    return clamp_idle_timeout_seconds(st.session_state.get(_TIMEOUT_KEY, DEFAULT_IDLE_TIMEOUT_SECONDS))


def ensure_idle_state(now: float | None = None) -> None:
    """Seed idle tracking without marking activity on already-paused sessions."""
    timestamp = float(now if now is not None else time.time())
    st.session_state.setdefault(_LAST_ACTIVITY_KEY, timestamp)
    st.session_state.setdefault(_TIMEOUT_KEY, DEFAULT_IDLE_TIMEOUT_SECONDS)


def idle_elapsed_seconds(now: float | None = None) -> int:
    """Return seconds since the last explicit OVERWATCH operator activity."""
    ensure_idle_state(now)
    timestamp = float(now if now is not None else time.time())
    last_activity = float(st.session_state.get(_LAST_ACTIVITY_KEY, timestamp) or timestamp)
    return max(0, int(timestamp - last_activity))


def _disable_background_refresh() -> None:
    """Stop known background polling controls when the app becomes idle."""
    st.session_state["lm_auto"] = False


def pause_queries(reason: str = "idle", now: float | None = None) -> None:
    """Pause Snowflake query execution for the current OVERWATCH session."""
    timestamp = float(now if now is not None else time.time())
    st.session_state[_PAUSED_KEY] = True
    st.session_state[_PAUSED_AT_KEY] = timestamp
    st.session_state[_PAUSE_REASON_KEY] = str(reason or "idle")
    _disable_background_refresh()


def resume_queries(now: float | None = None) -> None:
    """Resume Snowflake query execution and mark explicit operator activity."""
    timestamp = float(now if now is not None else time.time())
    st.session_state[_LAST_ACTIVITY_KEY] = timestamp
    st.session_state[_PAUSED_KEY] = False
    st.session_state.pop(_PAUSED_AT_KEY, None)
    st.session_state.pop(_PAUSE_REASON_KEY, None)
    st.session_state.pop(_WARNING_KEY, None)
    _disable_background_refresh()


def mark_operator_activity(reason: str = "interaction", now: float | None = None) -> None:
    """Record explicit operator activity when the query guard is not paused."""
    if queries_paused(now):
        return
    timestamp = float(now if now is not None else time.time())
    st.session_state[_LAST_ACTIVITY_KEY] = timestamp
    st.session_state[_PAUSED_KEY] = False
    st.session_state[_PAUSE_REASON_KEY] = str(reason or "interaction")


def queries_paused(now: float | None = None) -> bool:
    """Return True when OVERWATCH should avoid Snowflake query execution."""
    ensure_idle_state(now)
    if bool(st.session_state.get(_PAUSED_KEY, False)):
        _disable_background_refresh()
        return True
    if idle_elapsed_seconds(now) >= get_idle_timeout_seconds():
        pause_queries("idle", now=now)
        return True
    return False


def query_pause_message() -> str:
    """Return a short operator-facing pause message."""
    timeout_min = max(1, int(round(get_idle_timeout_seconds() / 60)))
    return (
        f"OVERWATCH paused Snowflake queries after {timeout_min} minutes of inactivity. "
        "Resume when you need fresh telemetry."
    )


def empty_paused_result(ttl_key: str = "", section: str = "") -> pd.DataFrame:
    """Return an empty result and warn once while idle guard is active."""
    warn_key = f"{_WARNING_KEY}_{section}_{ttl_key}"
    if not st.session_state.get(warn_key):
        st.info(query_pause_message())
        st.session_state[warn_key] = True
    return pd.DataFrame()
