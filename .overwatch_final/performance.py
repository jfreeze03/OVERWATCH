"""Decision Workspace performance budgets and local UI query telemetry."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from typing import Any
import os
import re

import streamlit as st


DECISION_FIRST_PAINT_QUERY_BUDGET = 1
DECISION_WARM_QUERY_BUDGET = 0
SECTION_ROUTE_QUERY_BUDGET = 0
EVIDENCE_CLICK_QUERY_BUDGET = 1
ADMIN_CLICK_QUERY_BUDGET = 3
ACCOUNT_USAGE_FALLBACK_QUERY_BUDGET = 1
TARGETED_EVIDENCE_DEFAULT_LIMIT = 200
TARGETED_EVIDENCE_MAX_LIMIT = 500
ACCOUNT_USAGE_TARGETED_SCAN_ALLOWED = False

_UI_QUERY_EVENTS_KEY = "_overwatch_ui_query_events"
_FIRST_PAINT_STACK_KEY = "_overwatch_first_paint_stack"
_SNOWFLAKE_EXECUTION_EVENTS_KEY = "_overwatch_snowflake_execution_events"
_FIRST_PAINT_BUDGET_VIOLATIONS_KEY = "_overwatch_first_paint_budget_violations"
_VALID_CACHE_LAYERS = {"none", "session", "streamlit_cache", "paused", "budget_blocked", "unknown"}
_VALID_QUERY_BOUNDARIES = {
    "decision_packet",
    "evidence",
    "metadata",
    "account_usage",
    "setup_health",
    "other",
}
_FIRST_PAINT_BOUNDARIES = {"decision_packet", "evidence", "metadata", "account_usage"}


def _session_list(key: str) -> list[Any]:
    try:
        value = st.session_state.setdefault(key, [])
    except Exception:
        return []
    if not isinstance(value, list):
        try:
            st.session_state[key] = []
            return st.session_state[key]
        except Exception:
            return []
    return value


def _current_first_paint_context() -> dict[str, Any]:
    stack = _session_list(_FIRST_PAINT_STACK_KEY)
    if not stack:
        return {}
    top = stack[-1]
    return dict(top) if isinstance(top, dict) else {}


def begin_first_paint(section: str, workflow: str = "") -> str:
    """Open a render-scoped first-paint window for performance budgeting."""
    render_id = uuid4().hex[:16]
    _session_list(_FIRST_PAINT_STACK_KEY).append({
        "render_id": render_id,
        "section": str(section or ""),
        "workflow": str(workflow or ""),
        "started_at": datetime.now().isoformat(timespec="milliseconds"),
    })
    return render_id


def end_first_paint(render_id: str) -> None:
    """Close the matching first-paint window without disturbing older telemetry."""
    if not render_id:
        return
    stack = _session_list(_FIRST_PAINT_STACK_KEY)
    for idx in range(len(stack) - 1, -1, -1):
        item = stack[idx]
        if isinstance(item, dict) and item.get("render_id") == render_id:
            del stack[idx:]
            return


def current_first_paint_render_id() -> str:
    """Return the active first-paint render id, if any."""
    return str(_current_first_paint_context().get("render_id") or "")


def is_first_paint_active() -> bool:
    """Return True while a section-entry first-paint window is open."""
    return bool(current_first_paint_render_id())


def current_first_paint_section() -> str:
    """Return the section currently protected by the first-paint query gate."""
    return str(_current_first_paint_context().get("section") or "")


def _strict_first_paint_mode() -> bool:
    """Return whether first-paint violations should fail before execution."""
    return any(
        str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}
        for name in ("OVERWATCH_TEST_MODE", "OVERWATCH_UI_FIXTURE_MODE", "OVERWATCH_ALLOW_FIXTURE_MODE")
    )


def record_first_paint_budget_violation(
    *,
    query_boundary: str = "other",
    section: str = "",
    ttl_key: str = "",
    tier: str = "",
    max_rows: int | None = None,
    reason: str = "",
    render_id: str | None = None,
) -> dict[str, Any]:
    """Record a SQL-free first-paint SLO violation for admin diagnostics."""
    context = _current_first_paint_context()
    boundary = str(query_boundary or "other")
    if boundary not in _VALID_QUERY_BOUNDARIES:
        boundary = "other"
    event = {
        "event_id": uuid4().hex[:16],
        "render_id": str(render_id or context.get("render_id") or ""),
        "section": str(section or context.get("section") or ""),
        "workflow": str(context.get("workflow") or ""),
        "query_boundary": boundary,
        "ttl_key": str(ttl_key or "")[:160],
        "tier": str(tier or ""),
        "max_rows": None if max_rows is None else int(max_rows),
        "reason": str(reason or "First-paint query budget violation.")[:500],
        "recorded_at": datetime.now().isoformat(timespec="milliseconds"),
    }
    try:
        events = _session_list(_FIRST_PAINT_BUDGET_VIOLATIONS_KEY)
        events.append(event)
        if len(events) > 100:
            del events[:-100]
    except Exception:
        pass
    return event


def get_first_paint_budget_violations() -> list[dict[str, Any]]:
    """Return SQL-free first-paint SLO violations."""
    events = _session_list(_FIRST_PAINT_BUDGET_VIOLATIONS_KEY)
    return [dict(event) for event in events if isinstance(event, dict)]


def clear_first_paint_budget_violations() -> None:
    try:
        st.session_state[_FIRST_PAINT_BUDGET_VIOLATIONS_KEY] = []
    except Exception:
        pass


def assert_first_paint_query_allowed(
    query_boundary: str,
    section: str = "",
    ttl_key: str = "",
    tier: str = "",
    max_rows: int | None = None,
) -> None:
    """Enforce the first-paint SLO before any Snowflake execution can start."""
    if not is_first_paint_active():
        return
    boundary = str(query_boundary or "other")
    if boundary not in _VALID_QUERY_BOUNDARIES:
        boundary = "other"
    violation_reason = ""
    if boundary != "decision_packet":
        violation_reason = f"First paint allows only decision_packet queries, not {boundary}."
    elif max_rows is not None and int(max_rows) != 1:
        violation_reason = "Decision packet first-paint queries must request max_rows=1."
    if not violation_reason:
        return
    record_first_paint_budget_violation(
        query_boundary=boundary,
        section=section or current_first_paint_section(),
        ttl_key=ttl_key,
        tier=tier,
        max_rows=max_rows,
        reason=violation_reason,
    )
    if _strict_first_paint_mode():
        raise AssertionError(violation_reason)


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
    render_id: str | None = None,
) -> dict[str, Any]:
    """Record lightweight, SQL-free UI query telemetry in session state."""
    cache_layer = str(cache_layer or "unknown")
    if cache_layer not in _VALID_CACHE_LAYERS:
        cache_layer = "unknown"
    query_boundary = str(query_boundary or "other")
    if query_boundary not in _VALID_QUERY_BOUNDARIES:
        query_boundary = "other"
    active_context = _current_first_paint_context()
    event_render_id = str(render_id or active_context.get("render_id") or "")
    if event_render_id:
        first_paint_sensitive = bool(first_paint_sensitive or query_boundary in _FIRST_PAINT_BOUNDARIES)
    else:
        first_paint_sensitive = False
    event = {
        "event_id": uuid4().hex[:16],
        "render_id": event_render_id,
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
    """Summarize render-window-scoped first-paint UI query events without SQL text."""
    section_filter = str(section or "").strip().lower()
    events = [
        event for event in get_ui_query_events()
        if bool(event.get("first_paint_sensitive"))
        and str(event.get("render_id") or "").strip()
        and (not section_filter or str(event.get("section", "")).strip().lower() == section_filter)
    ]
    render_ids = {str(event.get("render_id")) for event in events if event.get("render_id")}

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
        "first_paint_allowed_queries": _count("decision_packet"),
        "first_paint_blocked_queries": len(get_first_paint_budget_violations()),
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
        "render_ids": sorted(render_ids),
        "snowflake_execution_events": len([
            event for event in get_snowflake_execution_counter()
            if str(event.get("render_id") or "") in render_ids
            and (not section_filter or str(event.get("section", "")).strip().lower() == section_filter)
        ]),
    }


def increment_snowflake_execution_counter(
    query_boundary: str,
    section: str = "",
    ttl_key: str = "",
    tier: str = "",
) -> dict[str, Any]:
    """Record that a real Snowflake execution crossed the app boundary."""
    boundary = str(query_boundary or "other")
    if boundary not in _VALID_QUERY_BOUNDARIES:
        boundary = "other"
    context = _current_first_paint_context()
    event = {
        "event_id": uuid4().hex[:16],
        "render_id": str(context.get("render_id") or ""),
        "section": str(section or context.get("section") or ""),
        "query_boundary": boundary,
        "ttl_key": str(ttl_key or ""),
        "tier": str(tier or ""),
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
    }
    try:
        events = _session_list(_SNOWFLAKE_EXECUTION_EVENTS_KEY)
        events.append(event)
        if len(events) > 250:
            del events[:-250]
    except Exception:
        pass
    return event


def get_snowflake_execution_counter(render_id: str | None = None) -> list[dict[str, Any]]:
    """Return real Snowflake execution events, optionally scoped to a render id."""
    events = _session_list(_SNOWFLAKE_EXECUTION_EVENTS_KEY)
    selected = [dict(event) for event in events if isinstance(event, dict)]
    if render_id:
        selected = [event for event in selected if str(event.get("render_id") or "") == str(render_id)]
    return selected


def clear_snowflake_execution_counter() -> None:
    try:
        st.session_state[_SNOWFLAKE_EXECUTION_EVENTS_KEY] = []
    except Exception:
        pass


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
        st.session_state[_FIRST_PAINT_STACK_KEY] = []
        st.session_state[_FIRST_PAINT_BUDGET_VIOLATIONS_KEY] = []
    except Exception:
        pass


def render_performance_debug_panel() -> None:
    """Render query telemetry only in explicit debug/admin surfaces."""
    events = get_ui_query_events()
    if not events:
        st.caption("No Decision Workspace UI query events recorded in this session.")
        return
    st.dataframe(events, width="stretch", hide_index=True)
