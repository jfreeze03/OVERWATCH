"""Idle-query guard for OVERWATCH Snowflake sessions."""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from runtime_state import (
    IDLE_TIMEOUT_SECONDS,
    LAST_OPERATOR_ACTIVITY_TS,
    LIVE_MONITOR_AUTO_REFRESH,
    QUERIES_PAUSED,
    QUERY_PAUSED_AT_TS,
    QUERY_PAUSE_REASON,
    QUERY_PAUSE_WARNING_PREFIX,
    ensure_default_state,
    get_state,
    pop_state,
    set_state,
)


DEFAULT_IDLE_TIMEOUT_SECONDS = 15 * 60
MIN_IDLE_TIMEOUT_SECONDS = 60
MAX_IDLE_TIMEOUT_SECONDS = 8 * 60 * 60


def clamp_idle_timeout_seconds(value: object, default: int = DEFAULT_IDLE_TIMEOUT_SECONDS) -> int:
    """Return a bounded idle timeout in seconds."""
    try:
        seconds = int(value)
    except Exception:
        seconds = int(default)
    return max(MIN_IDLE_TIMEOUT_SECONDS, min(MAX_IDLE_TIMEOUT_SECONDS, seconds))


def get_idle_timeout_seconds() -> int:
    """Return the configured OVERWATCH idle timeout."""
    return clamp_idle_timeout_seconds(get_state(IDLE_TIMEOUT_SECONDS, DEFAULT_IDLE_TIMEOUT_SECONDS))


def ensure_idle_state(now: float | None = None) -> None:
    """Seed idle tracking without marking activity on already-paused sessions."""
    timestamp = float(now if now is not None else time.time())
    ensure_default_state(LAST_OPERATOR_ACTIVITY_TS, timestamp)
    ensure_default_state(IDLE_TIMEOUT_SECONDS, DEFAULT_IDLE_TIMEOUT_SECONDS)


def idle_elapsed_seconds(now: float | None = None) -> int:
    """Return seconds since the last explicit OVERWATCH operator activity."""
    ensure_idle_state(now)
    timestamp = float(now if now is not None else time.time())
    last_activity = float(get_state(LAST_OPERATOR_ACTIVITY_TS, timestamp) or timestamp)
    return max(0, int(timestamp - last_activity))


def _disable_background_refresh() -> None:
    """Stop known background polling controls when the app becomes idle."""
    set_state(LIVE_MONITOR_AUTO_REFRESH, False)


def pause_queries(reason: str = "idle", now: float | None = None) -> None:
    """Pause Snowflake query execution for the current OVERWATCH session."""
    timestamp = float(now if now is not None else time.time())
    set_state(QUERIES_PAUSED, True)
    set_state(QUERY_PAUSED_AT_TS, timestamp)
    set_state(QUERY_PAUSE_REASON, str(reason or "idle"))
    _disable_background_refresh()


def resume_queries(now: float | None = None) -> None:
    """Resume Snowflake query execution and mark explicit operator activity."""
    timestamp = float(now if now is not None else time.time())
    set_state(LAST_OPERATOR_ACTIVITY_TS, timestamp)
    set_state(QUERIES_PAUSED, False)
    pop_state(QUERY_PAUSED_AT_TS, None)
    pop_state(QUERY_PAUSE_REASON, None)
    pop_state(QUERY_PAUSE_WARNING_PREFIX, None)
    _disable_background_refresh()


def mark_operator_activity(reason: str = "interaction", now: float | None = None) -> None:
    """Record explicit operator activity when the query guard is not paused."""
    if queries_paused(now):
        return
    timestamp = float(now if now is not None else time.time())
    set_state(LAST_OPERATOR_ACTIVITY_TS, timestamp)
    set_state(QUERIES_PAUSED, False)
    set_state(QUERY_PAUSE_REASON, str(reason or "interaction"))


def queries_paused(now: float | None = None) -> bool:
    """Return True when OVERWATCH should avoid Snowflake query execution."""
    ensure_idle_state(now)
    if bool(get_state(QUERIES_PAUSED, False)):
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
    warn_key = f"{QUERY_PAUSE_WARNING_PREFIX}_{section}_{ttl_key}"
    if not get_state(warn_key):
        st.info(query_pause_message())
        set_state(warn_key, True)
    return pd.DataFrame()
