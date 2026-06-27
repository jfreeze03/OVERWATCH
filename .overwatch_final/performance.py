"""Decision Workspace performance budgets and local UI query telemetry."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from typing import Any
import re

import streamlit as st


DECISION_FIRST_PAINT_QUERY_BUDGET = 1
DECISION_WARM_QUERY_BUDGET = 0
TARGETED_EVIDENCE_DEFAULT_LIMIT = 200
TARGETED_EVIDENCE_MAX_LIMIT = 500
ACCOUNT_USAGE_TARGETED_SCAN_ALLOWED = False

_UI_QUERY_EVENTS_KEY = "_overwatch_ui_query_events"
_VALID_CACHE_LAYERS = {"none", "session", "streamlit_cache", "paused", "budget_blocked", "unknown"}
_VALID_QUERY_BOUNDARIES = {
    "decision_packet",
    "evidence",
    "metadata",
    "account_usage",
    "setup_health",
    "other",
}


def _safe_message(error: object) -> str:
    text = str(error or "").strip()
    if not text:
        return ""
    if re.search(r"\b(SELECT|WITH|FROM|JOIN|CALL)\b|SP_|MART_|FACT_|ACCOUNT_USAGE", text, flags=re.IGNORECASE):
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
    actual_query_executed: bool | None = None,
    cache_layer: str = "unknown",
    query_boundary: str = "other",
    first_paint_sensitive: bool = False,
) -> dict[str, Any]:
    """Record lightweight, SQL-free UI query telemetry in session state."""
    cache_layer = str(cache_layer or "unknown")
    if cache_layer not in _VALID_CACHE_LAYERS:
        cache_layer = "unknown"
    query_boundary = str(query_boundary or "other")
    if query_boundary not in _VALID_QUERY_BOUNDARIES:
        query_boundary = "other"
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
        "actual_query_executed": actual_query_executed,
        "cache_layer": cache_layer,
        "query_boundary": query_boundary,
        "first_paint_sensitive": bool(first_paint_sensitive),
    }
    try:
        events = st.session_state.setdefault(_UI_QUERY_EVENTS_KEY, [])
        events.append(event)
        if len(events) > 250:
            del events[:-250]
    except Exception:
        pass
    return event


def summarize_first_paint_query_budget(section: str | None = None) -> dict[str, Any]:
    """Summarize first-paint-sensitive UI query events without SQL text."""
    section_filter = str(section or "").strip().lower()
    events = [
        event for event in get_ui_query_events()
        if bool(event.get("first_paint_sensitive"))
        and (not section_filter or str(event.get("section", "")).strip().lower() == section_filter)
    ]

    def _count(boundary: str, *, actual_only: bool | None = None) -> int:
        subset = [event for event in events if event.get("query_boundary") == boundary]
        if actual_only is True:
            subset = [event for event in subset if event.get("actual_query_executed") is True]
        elif actual_only is False:
            subset = [event for event in subset if event.get("actual_query_executed") is False]
        return len(subset)

    return {
        "section": section or "",
        "first_paint_event_count": len(events),
        "decision_packet_events": _count("decision_packet"),
        "decision_packet_actual_queries": _count("decision_packet", actual_only=True),
        "decision_packet_session_hits": len(
            [event for event in events if event.get("query_boundary") == "decision_packet" and event.get("cache_layer") == "session"]
        ),
        "evidence_events": _count("evidence"),
        "evidence_actual_queries": _count("evidence", actual_only=True),
        "metadata_events": _count("metadata"),
        "account_usage_events": _count("account_usage"),
        "account_usage_actual_queries": _count("account_usage", actual_only=True),
        "budget_blocked_events": len([event for event in events if event.get("cache_layer") == "budget_blocked"]),
        "paused_events": len([event for event in events if event.get("cache_layer") == "paused"]),
    }


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
