"""Decision Workspace performance budgets and local UI query telemetry."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from typing import Any

import streamlit as st


DECISION_FIRST_PAINT_QUERY_BUDGET = 1
DECISION_WARM_QUERY_BUDGET = 0
TARGETED_EVIDENCE_DEFAULT_LIMIT = 200
TARGETED_EVIDENCE_MAX_LIMIT = 500
ACCOUNT_USAGE_TARGETED_SCAN_ALLOWED = False

_UI_QUERY_EVENTS_KEY = "_overwatch_ui_query_events"


def _safe_message(error: object) -> str:
    text = str(error or "").strip()
    if not text:
        return ""
    for token in ("SELECT ", "WITH ", "FROM ", "WHERE ", "JOIN ", "CALL ", "SP_", "MART_", "FACT_"):
        if token in text.upper():
            return "Query failed; see admin diagnostics."
    return text[:500]


def record_ui_query_event(
    *,
    section: str = "",
    workflow: str = "",
    query_tier: str = "",
    ttl_key: str = "",
    cache_hit_or_use_cache: object = "",
    elapsed_ms: float = 0.0,
    row_count: int = 0,
    max_rows: int | None = None,
    error: object = "",
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    """Record lightweight, SQL-free UI query telemetry in session state."""
    event = {
        "event_id": uuid4().hex[:16],
        "section": str(section or ""),
        "workflow": str(workflow or ""),
        "query_tier": str(query_tier or ""),
        "ttl_key": str(ttl_key or ""),
        "cache_hit_or_use_cache": str(cache_hit_or_use_cache),
        "elapsed_ms": round(float(elapsed_ms or 0), 2),
        "row_count": int(row_count or 0),
        "max_rows": None if max_rows is None else int(max_rows),
        "error": _safe_message(error),
        "started_at": started_at or datetime.now().isoformat(timespec="milliseconds"),
        "finished_at": finished_at or datetime.now().isoformat(timespec="milliseconds"),
    }
    try:
        events = st.session_state.setdefault(_UI_QUERY_EVENTS_KEY, [])
        events.append(event)
        if len(events) > 250:
            del events[:-250]
    except Exception:
        pass
    return event


def get_ui_query_events() -> list[dict[str, Any]]:
    try:
        events = st.session_state.get(_UI_QUERY_EVENTS_KEY, [])
    except Exception:
        return []
    if not isinstance(events, list):
        return []
    return [dict(event) for event in events if isinstance(event, dict)]


def clear_ui_query_events() -> None:
    try:
        st.session_state[_UI_QUERY_EVENTS_KEY] = []
    except Exception:
        pass


def render_performance_debug_panel() -> None:
    """Render query telemetry only in explicit debug/admin surfaces."""
    events = get_ui_query_events()
    if not events:
        st.caption("No Decision Workspace UI query events recorded in this session.")
        return
    st.dataframe(events, width="stretch", hide_index=True)
