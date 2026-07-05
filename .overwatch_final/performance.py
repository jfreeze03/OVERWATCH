"""Decision Workspace performance budgets and local UI query telemetry."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from hashlib import sha1
import inspect
from pathlib import Path
from uuid import uuid4
from typing import Any, Iterable, Mapping
import os
import re

import streamlit as st

from runtime_boundaries import APPROVED_RELEASE_EXECUTION_BOUNDARIES, normalize_release_boundary


DECISION_FIRST_PAINT_QUERY_BUDGET = 1
DECISION_WARM_QUERY_BUDGET = 0
SECTION_ROUTE_QUERY_BUDGET = 0
EVIDENCE_CLICK_QUERY_BUDGET = 1
ADMIN_CLICK_QUERY_BUDGET = 3
DECISION_BOOTSTRAP_QUERY_BUDGET = 20
ACCOUNT_USAGE_FALLBACK_QUERY_BUDGET = 1
TARGETED_EVIDENCE_DEFAULT_LIMIT = 200
TARGETED_EVIDENCE_MAX_LIMIT = 500
ACCOUNT_USAGE_TARGETED_SCAN_ALLOWED = False
COST_WORKBENCH_FIRST_PAINT_ALLOWED = False
QUERY_SEARCH_NO_CLICK_QUERY_BUDGET = 0

_UI_QUERY_EVENTS_KEY = "_overwatch_ui_query_events"
_FIRST_PAINT_STACK_KEY = "_overwatch_first_paint_stack"
_SNOWFLAKE_EXECUTION_EVENTS_KEY = "_overwatch_snowflake_execution_events"
_FIRST_PAINT_BUDGET_VIOLATIONS_KEY = "_overwatch_first_paint_budget_violations"
_SNOWFLAKE_SESSION_OPEN_EVENTS_KEY = "_overwatch_snowflake_session_open_events"
_QUERY_LINT_FINDINGS_KEY = "_overwatch_query_lint_findings"
_DIRECT_SQL_EVENTS_KEY = "_overwatch_direct_sql_events"
_DIRECT_SQL_ALLOWANCE_STACK_KEY = "_overwatch_direct_sql_allowance_stack"
_ROLE_CAPTURE_EVENTS_KEY = "_overwatch_role_capture_events"
_QUERY_BUDGET_CONTEXT_STACK_KEY = "_overwatch_query_budget_context_stack"
_QUERY_BUDGET_CONTEXT_EVENTS_KEY = "_overwatch_query_budget_context_events"
_VALID_CACHE_LAYERS = {"none", "session", "streamlit_cache", "paused", "budget_blocked", "unknown"}
_VALID_QUERY_BOUNDARIES = set(APPROVED_RELEASE_EXECUTION_BOUNDARIES)
_QUERY_BOUNDARY_ALIASES = {
    "first_paint_packet": "decision_packet",
    "warm_first_paint": "decision_packet",
    "route_action": "metadata_bounded",
    "evidence_action": "evidence_targeted",
    "compact_evidence": "evidence_targeted",
    "detail_mart": "evidence_targeted",
    "query_search_no_click": "metadata_bounded",
    "query_search_explicit": "query_search_exact",
    "cost_workbench": "evidence_targeted",
    "deep_history_fallback": "query_search_broad_explicit",
    "setup_health": "admin_setup_health",
    "live_validation": "live_validation",
    "admin": "setup_admin",
    "metadata": "metadata_bounded",
    "account_usage": "query_search_broad_explicit",
    "evidence": "evidence_targeted",
    "query_search": "query_search_exact",
    "query_preview": "metadata_bounded",
    "cost_evidence": "evidence_targeted",
}
_FIRST_PAINT_BOUNDARIES = set(APPROVED_RELEASE_EXECUTION_BOUNDARIES)
_QUERY_BUDGET_LIMITS = {
    "first_paint": DECISION_FIRST_PAINT_QUERY_BUDGET,
    "warm_first_paint": DECISION_WARM_QUERY_BUDGET,
    "route_action": SECTION_ROUTE_QUERY_BUDGET,
    "evidence_click": EVIDENCE_CLICK_QUERY_BUDGET,
    "refresh_packet": 1,
    "query_search_exact": 1,
    "query_search_signature": 1,
    "query_search_text": 1,
    "query_preview": 1,
    "account_usage_fallback": ACCOUNT_USAGE_FALLBACK_QUERY_BUDGET,
    "deep_history_fallback": ACCOUNT_USAGE_FALLBACK_QUERY_BUDGET,
    "query_search_no_click": QUERY_SEARCH_NO_CLICK_QUERY_BUDGET,
    "cost_workbench_first_paint": 0,
    "admin_setup": ADMIN_CLICK_QUERY_BUDGET,
    "advanced_diagnostics": ADMIN_CLICK_QUERY_BUDGET,
}


def normalize_query_boundary(query_boundary: str) -> str:
    """Map product workflow boundaries to the execution boundary vocabulary."""
    raw = str(query_boundary or "other").strip().lower()
    normalized = _QUERY_BOUNDARY_ALIASES.get(raw, raw)
    return normalize_release_boundary(normalized)


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


def _query_budget_limit(name: str, budget: int | None = None) -> int:
    if budget is not None:
        return max(int(budget), 0)
    return int(_QUERY_BUDGET_LIMITS.get(str(name or "").strip().lower(), ADMIN_CLICK_QUERY_BUDGET))


def begin_query_budget_context(
    name: str,
    *,
    section: str = "",
    workflow: str = "",
    budget: int | None = None,
) -> str:
    """Open a scoped query budget for route, evidence, search, or admin actions."""
    token = uuid4().hex[:16]
    _session_list(_QUERY_BUDGET_CONTEXT_STACK_KEY).append({
        "token": token,
        "name": str(name or "other"),
        "section": str(section or ""),
        "workflow": str(workflow or ""),
        "budget": _query_budget_limit(name, budget),
        "actual_snowflake_executions": 0,
        "session_open_count": 0,
        "direct_sql_events": 0,
        "metadata_probe_events": 0,
        "role_capture_events": 0,
        "query_events": 0,
        "boundaries": {},
        "actual_boundaries": {},
        "started_at": datetime.now().isoformat(timespec="milliseconds"),
    })
    return token


def _active_query_budget_context() -> dict[str, Any]:
    stack = _session_list(_QUERY_BUDGET_CONTEXT_STACK_KEY)
    if not stack:
        return {}
    top = stack[-1]
    return top if isinstance(top, dict) else {}


def _record_query_budget_context_event(
    *,
    query_boundary: str,
    actual_execution: bool = False,
    session_open: bool = False,
    direct_sql: bool = False,
    metadata_probe: bool = False,
    role_capture: bool = False,
) -> None:
    context = _active_query_budget_context()
    if not context:
        return
    if not session_open and not direct_sql and not metadata_probe and not role_capture:
        context["query_events"] = int(context.get("query_events") or 0) + 1
    if actual_execution:
        context["actual_snowflake_executions"] = int(context.get("actual_snowflake_executions") or 0) + 1
    if session_open:
        context["session_open_count"] = int(context.get("session_open_count") or 0) + 1
    if direct_sql:
        context["direct_sql_events"] = int(context.get("direct_sql_events") or 0) + 1
    if metadata_probe:
        context["metadata_probe_events"] = int(context.get("metadata_probe_events") or 0) + 1
    if role_capture:
        context["role_capture_events"] = int(context.get("role_capture_events") or 0) + 1
    boundaries = context.setdefault("boundaries", {})
    if isinstance(boundaries, dict):
        boundary = str(query_boundary or "other")
        boundaries[boundary] = int(boundaries.get(boundary, 0) or 0) + 1
    if actual_execution:
        actual_boundaries = context.setdefault("actual_boundaries", {})
        if isinstance(actual_boundaries, dict):
            boundary = str(query_boundary or "other")
            actual_boundaries[boundary] = int(actual_boundaries.get(boundary, 0) or 0) + 1


def end_query_budget_context(token: str) -> dict[str, Any]:
    """Close a query budget and record a pass/fail summary."""
    summary: dict[str, Any] = {
        "token": str(token or ""),
        "name": "",
        "section": "",
        "workflow": "",
        "budget": 0,
        "actual_snowflake_executions": 0,
        "session_open_count": 0,
        "direct_sql_events": 0,
        "metadata_probe_events": 0,
        "role_capture_events": 0,
        "query_events": 0,
        "passed_budget": True,
        "passed_query_budget": True,
        "failure_reason": "",
        "boundaries": {},
        "actual_boundaries": {},
        "finished_at": datetime.now().isoformat(timespec="milliseconds"),
    }
    stack = _session_list(_QUERY_BUDGET_CONTEXT_STACK_KEY)
    selected: dict[str, Any] | None = None
    for idx in range(len(stack) - 1, -1, -1):
        item = stack[idx]
        if isinstance(item, dict) and item.get("token") == token:
            selected = dict(item)
            del stack[idx:]
            break
    if selected:
        actual = int(selected.get("actual_snowflake_executions") or 0)
        budget = int(selected.get("budget") or 0)
        name = str(selected.get("name") or "")
        boundaries = dict(selected.get("boundaries") or {})
        actual_boundaries = dict(selected.get("actual_boundaries") or {})
        session_open_count = int(selected.get("session_open_count") or 0)
        direct_sql_events = int(selected.get("direct_sql_events") or 0)
        metadata_probe_events = int(selected.get("metadata_probe_events") or 0)
        role_capture_events = int(selected.get("role_capture_events") or 0)
        failure_reasons: list[str] = []
        if actual > budget:
            failure_reasons.append(f"actual_snowflake_executions {actual} exceeded budget {budget}")
        if name == "route_action":
            if session_open_count:
                failure_reasons.append("route_action opened a Snowflake session")
            if direct_sql_events:
                failure_reasons.append("route_action emitted direct SQL")
            if metadata_probe_events:
                failure_reasons.append("route_action emitted a metadata probe")
            if role_capture_events:
                failure_reasons.append("route_action captured role metadata")
        if name == "evidence_click":
            evidence_count = int(actual_boundaries.get("evidence") or 0) + int(actual_boundaries.get("evidence_targeted") or 0)
            if evidence_count > 1:
                failure_reasons.append("evidence_click emitted more than one evidence boundary")
            if metadata_probe_events:
                failure_reasons.append("evidence_click emitted an unallowlisted metadata probe")
            if int(actual_boundaries.get("account_usage") or 0) or int(actual_boundaries.get("query_search_broad_explicit") or 0):
                failure_reasons.append("evidence_click emitted Account Usage work")
        query_search_exact_count = int(actual_boundaries.get("query_search") or 0) + int(actual_boundaries.get("query_search_exact") or 0)
        if name == "query_search_exact" and query_search_exact_count > 1:
            failure_reasons.append("query_search_exact emitted more than one query_search boundary")
        if name == "query_search_related" and int(actual_boundaries.get("query_search") or 0) > 1:
            failure_reasons.append("query_search_related emitted more than one query_search boundary")
        query_preview_count = int(actual_boundaries.get("query_preview") or 0) + int(actual_boundaries.get("query_search_exact") or 0)
        if name == "query_preview" and query_preview_count > 1:
            failure_reasons.append("query_preview emitted more than one query_preview boundary")
        if name == "account_usage_fallback":
            account_cost = (
                int(actual_boundaries.get("account_usage") or 0)
                + int(actual_boundaries.get("query_search_broad_explicit") or 0)
                + metadata_probe_events
            )
            if account_cost > budget:
                failure_reasons.append(f"account_usage_fallback cost {account_cost} exceeded budget {budget}")
        passed = not failure_reasons
        summary.update({
            "name": name,
            "section": str(selected.get("section") or ""),
            "workflow": str(selected.get("workflow") or ""),
            "budget": budget,
            "actual_snowflake_executions": actual,
            "session_open_count": session_open_count,
            "direct_sql_events": direct_sql_events,
            "metadata_probe_events": metadata_probe_events,
            "role_capture_events": role_capture_events,
            "query_events": int(selected.get("query_events") or 0),
            "passed_budget": passed,
            "passed_query_budget": passed,
            "failure_reason": "; ".join(failure_reasons),
            "boundaries": boundaries,
            "actual_boundaries": actual_boundaries,
            "started_at": selected.get("started_at"),
        })
    try:
        events = _session_list(_QUERY_BUDGET_CONTEXT_EVENTS_KEY)
        events.append(summary)
        if len(events) > 250:
            del events[:-250]
    except Exception:
        pass
    return summary


def assert_query_budget_context_passed(summary: dict[str, Any]) -> None:
    """Raise when a query-budget context exceeded its section/action SLO."""
    if bool(summary.get("passed_query_budget", summary.get("passed_budget", True))):
        return
    reason = _safe_message(summary.get("failure_reason") or "Query budget context failed.")
    raise AssertionError(reason or "Query budget context failed.")


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _fixture_mode_enabled() -> bool:
    return _env_flag("OVERWATCH_UI_FIXTURE_MODE")


def _strict_query_budget_context_mode() -> bool:
    """Return whether live UI query-budget accounting should interrupt rendering."""
    return _env_flag("OVERWATCH_TEST_MODE") or _fixture_mode_enabled() or _env_flag("OVERWATCH_STRICT_QUERY_BUDGETS")


@contextmanager
def query_budget_context(
    name: str,
    *,
    section: str = "",
    workflow: str = "",
    budget: int | None = None,
):
    """Context manager for user-action query budgets."""
    active = _active_query_budget_context()
    if str(active.get("name") or "") == str(name or "other"):
        yield str(active.get("token") or "")
        return
    token = begin_query_budget_context(name, section=section, workflow=workflow, budget=budget)
    try:
        yield token
    finally:
        summary = end_query_budget_context(token)
        if _strict_query_budget_context_mode():
            assert_query_budget_context_passed(summary)


def get_query_budget_context_events() -> list[dict[str, Any]]:
    events = _session_list(_QUERY_BUDGET_CONTEXT_EVENTS_KEY)
    return [dict(event) for event in events if isinstance(event, dict)]


def clear_query_budget_context_events() -> None:
    try:
        st.session_state[_QUERY_BUDGET_CONTEXT_STACK_KEY] = []
        st.session_state[_QUERY_BUDGET_CONTEXT_EVENTS_KEY] = []
    except Exception:
        pass


def first_paint_gate_mode() -> str:
    """Return the current first-paint gate mode."""
    return "strict" if _strict_first_paint_mode() else "record-only"


def _strict_first_paint_mode() -> bool:
    """Return whether first-paint violations should fail before execution."""
    return _env_flag("OVERWATCH_TEST_MODE") or _fixture_mode_enabled()


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
    product_boundary = str(query_boundary or "other")
    boundary = normalize_query_boundary(product_boundary)
    event = {
        "event_id": uuid4().hex[:16],
        "render_id": str(render_id or context.get("render_id") or ""),
        "section": str(section or context.get("section") or ""),
        "workflow": str(context.get("workflow") or ""),
        "boundary": boundary,
        "product_boundary": product_boundary,
        "execution_boundary": boundary,
        "query_boundary": product_boundary,
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
    boundary = normalize_query_boundary(query_boundary)
    violation_reason = ""
    if boundary != "decision_packet":
        violation_reason = f"First paint allows only decision_packet queries, not {boundary}."
    elif max_rows is None or int(max_rows) != 1:
        violation_reason = "Decision packet first-paint queries must request max_rows=1."
    if not violation_reason:
        return
    record_first_paint_budget_violation(
        query_boundary=query_boundary,
        section=section or current_first_paint_section(),
        ttl_key=ttl_key,
        tier=tier,
        max_rows=max_rows,
        reason=violation_reason,
    )
    if _strict_first_paint_mode():
        raise AssertionError(violation_reason)


def record_snowflake_session_open_event(
    *,
    section: str = "",
    workflow: str = "",
    reason: str = "",
    query_boundary: str = "other",
    allowed: bool = True,
    role_capture_deferred: bool = False,
    marker_boundary: str = "",
    marker_budget: str = "",
    marker_owner: str = "",
) -> dict[str, Any]:
    """Record SQL-free Snowflake session creation telemetry."""
    context = _current_first_paint_context()
    boundary = normalize_query_boundary(query_boundary)
    if not (marker_boundary or marker_budget or marker_owner):
        marker_metadata = _runtime_marker_metadata(_SESSION_OPEN_MARKER)
        marker_boundary = marker_metadata.get("marker_boundary", "")
        marker_budget = marker_metadata.get("marker_budget", "")
        marker_owner = marker_metadata.get("marker_owner", "")
    event = {
        "event_id": uuid4().hex[:16],
        "render_id": str(context.get("render_id") or ""),
        "section": str(section or context.get("section") or ""),
        "workflow": str(workflow or context.get("workflow") or ""),
        "reason": str(reason or "session_open")[:200],
        "boundary": boundary,
        "query_boundary": boundary,
        "allowed": bool(allowed),
        "role_capture_deferred": bool(role_capture_deferred),
        "marker_boundary": str(marker_boundary or ""),
        "marker_budget": str(marker_budget or ""),
        "marker_owner": str(marker_owner or ""),
        "first_paint_active": bool(context.get("render_id")),
        "gate_mode": first_paint_gate_mode(),
        "recorded_at": datetime.now().isoformat(timespec="milliseconds"),
    }
    try:
        events = _session_list(_SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
        events.append(event)
        if len(events) > 100:
            del events[:-100]
    except Exception:
        pass
    _record_query_budget_context_event(
        query_boundary=boundary,
        session_open=True,
    )
    try:
        from runtime_state import record_runtime_event

        record_runtime_event(
            event_type="session_open",
            section=str(event.get("section") or ""),
            workflow=str(event.get("workflow") or ""),
            boundary=boundary,
            product_boundary=str(query_boundary or ""),
            execution_boundary=boundary,
            source_module="performance.record_snowflake_session_open_event",
            session_open_count_delta=1,
            started_at=str(event.get("recorded_at") or ""),
            finished_at=str(event.get("recorded_at") or ""),
            raw_sql_included=False,
            extra={"allowed": bool(allowed), "reason": str(event.get("reason") or "")},
        )
    except Exception:
        pass
    return event


def get_snowflake_session_open_events() -> list[dict[str, Any]]:
    """Return Snowflake session-open events without SQL or credentials."""
    events = _session_list(_SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
    return [dict(event) for event in events if isinstance(event, dict)]


def clear_snowflake_session_open_events() -> None:
    try:
        st.session_state[_SNOWFLAKE_SESSION_OPEN_EVENTS_KEY] = []
    except Exception:
        pass


def assert_first_paint_session_open_allowed(
    *,
    section: str = "",
    workflow: str = "",
    reason: str = "",
    query_boundary: str = "other",
    max_rows: int | None = None,
) -> None:
    """Prevent direct session creation during first paint outside packet lookup."""
    if not is_first_paint_active():
        return
    boundary = normalize_query_boundary(query_boundary)
    allowed = boundary == "decision_packet" and max_rows == 1
    if allowed:
        return
    violation_reason = "First paint may open a Snowflake session only for the single decision packet lookup."
    record_snowflake_session_open_event(
        section=section or current_first_paint_section(),
        workflow=workflow,
        reason=reason or violation_reason,
        query_boundary=boundary,
        allowed=False,
    )
    record_first_paint_budget_violation(
        query_boundary=boundary,
        section=section or current_first_paint_section(),
        ttl_key="session_open",
        tier="session",
        max_rows=max_rows,
        reason=violation_reason,
    )
    if _strict_first_paint_mode():
        raise AssertionError(violation_reason)


def _sql_fingerprint(sql: object) -> str:
    text = re.sub(r"'(?:''|[^'])*'", "''", str(sql or ""), flags=re.DOTALL)
    normalized = re.sub(r"\s+", " ", text.strip().upper())
    return sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:16]


_RUNTIME_MARKER_FIELDS = {"boundary", "reason", "budget", "owner"}
_SESSION_OPEN_MARKER = "SESSION_OPEN" + "_ADMIN_OK"
_DIRECT_SQL_MARKER = "DIRECT_SQL" + "_ADMIN_OK"


def _registry_runtime_marker_metadata(filename: str, function_name: str, marker_name: str) -> dict[str, str]:
    try:
        root = Path(__file__).resolve().parents[1]
        relative = Path(filename).resolve().relative_to(root)
        module = str(relative).replace("\\", "/")
    except Exception:
        return {}
    if not module.startswith(".overwatch_final/"):
        module = f".overwatch_final/{module}" if module.startswith("overwatch_final/") else module
    try:
        entries: Iterable[Mapping[str, object]]
        if marker_name == _SESSION_OPEN_MARKER:
            from contracts.session_open_allowlist import SESSION_OPEN_ALLOWLIST

            entries = SESSION_OPEN_ALLOWLIST
        else:
            from contracts.direct_sql_allowlist import DIRECT_SQL_ALLOWLIST

            entries = DIRECT_SQL_ALLOWLIST
    except Exception:
        return {}
    for entry in entries:
        if str(entry.get("module") or "") != module:
            continue
        if str(entry.get("function") or "") != str(function_name or ""):
            continue
        return {
            "marker_boundary": str(entry.get("boundary") or ""),
            "marker_budget": str(entry.get("budget") or ""),
            "marker_owner": str(entry.get("owner") or ""),
        }
    return {}


def _parse_runtime_marker(line: str, marker_name: str) -> dict[str, str]:
    if marker_name not in str(line or ""):
        return {}
    payload = str(line or "").split(marker_name, 1)[1]
    fields: dict[str, str] = {}
    for match in re.finditer(r"\b(boundary|reason|budget|owner)=([A-Za-z0-9_.:-]+)", payload):
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        if key in _RUNTIME_MARKER_FIELDS:
            fields[key] = value
    return fields


def _runtime_marker_metadata(marker_name: str) -> dict[str, str]:
    """Attach local structured marker metadata from marked helper call sites."""
    try:
        frames = inspect.stack(context=0)
    except Exception:
        return {}
    skip_suffixes = (
        "/performance.py",
        "/utils/session.py",
        "/utils/query.py",
    )
    for frame in frames[2:12]:
        filename = str(getattr(frame, "filename", "") or "")
        normalized = filename.replace("\\", "/").lower()
        if not filename or any(normalized.endswith(suffix) for suffix in skip_suffixes):
            continue
        registry = _registry_runtime_marker_metadata(filename, str(getattr(frame, "function", "") or ""), marker_name)
        if registry:
            return registry
        try:
            lines = Path(filename).read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        call_line = int(getattr(frame, "lineno", 0) or 0)
        for idx in range(max(0, call_line - 4), max(0, call_line - 1)):
            fields = _parse_runtime_marker(lines[idx], marker_name)
            if fields:
                return {
                    "marker_boundary": fields.get("boundary", ""),
                    "marker_budget": fields.get("budget", ""),
                    "marker_owner": fields.get("owner", ""),
                }
    return {}


def begin_direct_sql_allowance(
    *,
    query_boundary: str = "other",
    section: str = "",
    ttl_key: str = "",
    max_rows: int | None = None,
) -> str:
    """Allow the central query runner to cross the guarded session.sql boundary."""
    token = uuid4().hex[:16]
    context = _current_first_paint_context()
    _session_list(_DIRECT_SQL_ALLOWANCE_STACK_KEY).append({
        "token": token,
        "render_id": str(context.get("render_id") or ""),
        "query_boundary": normalize_query_boundary(query_boundary),
        "section": str(section or context.get("section") or ""),
        "ttl_key": str(ttl_key or "")[:160],
        "max_rows": None if max_rows is None else int(max_rows),
    })
    return token


def end_direct_sql_allowance(token: str) -> None:
    if not token:
        return
    stack = _session_list(_DIRECT_SQL_ALLOWANCE_STACK_KEY)
    for idx in range(len(stack) - 1, -1, -1):
        item = stack[idx]
        if isinstance(item, dict) and item.get("token") == token:
            del stack[idx:]
            return


def _current_direct_sql_allowance() -> dict[str, Any]:
    stack = _session_list(_DIRECT_SQL_ALLOWANCE_STACK_KEY)
    if not stack:
        return {}
    top = stack[-1]
    return dict(top) if isinstance(top, dict) else {}


def record_direct_sql_event(
    *,
    query_text: object = "",
    section: str = "",
    workflow: str = "",
    query_boundary: str = "other",
    allowed: bool = True,
    reason: str = "",
    role_capture: bool = False,
    marker_boundary: str = "",
    marker_budget: str = "",
    marker_owner: str = "",
) -> dict[str, Any]:
    """Record a SQL-free direct session.sql call event."""
    context = _current_first_paint_context()
    boundary = normalize_query_boundary(query_boundary)
    if not (marker_boundary or marker_budget or marker_owner):
        marker_metadata = _runtime_marker_metadata(_DIRECT_SQL_MARKER)
        marker_boundary = marker_metadata.get("marker_boundary", "")
        marker_budget = marker_metadata.get("marker_budget", "")
        marker_owner = marker_metadata.get("marker_owner", "")
    allowance = _current_direct_sql_allowance()
    reason_text = str(reason or "")
    if not allowed:
        direct_sql_kind = "unallowlisted_direct_sql"
    elif role_capture:
        direct_sql_kind = "role_capture"
    elif allowance and boundary == "decision_packet":
        direct_sql_kind = "packet_direct_sql"
    elif allowance:
        direct_sql_kind = "runner_sql"
    elif boundary == "query_search_broad_explicit" and re.search(r"metadata|probe|columns|filter_existing", reason_text, re.IGNORECASE):
        direct_sql_kind = "account_usage_metadata_probe"
    elif boundary == "metadata_bounded" or re.search(r"\b(show|describe|desc|metadata|current_role|select 1)\b", reason_text, re.IGNORECASE):
        direct_sql_kind = "metadata_probe"
    elif boundary in {"setup_admin", "admin_setup_health", "live_validation", "explicit_connection_test"}:
        direct_sql_kind = "admin_direct_sql"
    else:
        direct_sql_kind = "direct_sql"
    event = {
        "event_id": uuid4().hex[:16],
        "render_id": str(context.get("render_id") or ""),
        "section": str(section or context.get("section") or ""),
        "workflow": str(workflow or context.get("workflow") or ""),
        "boundary": boundary,
        "query_boundary": boundary,
        "allowed": bool(allowed),
        "reason": _safe_message(reason) or str(reason or "")[:240],
        "direct_sql_kind": direct_sql_kind,
        "marker_boundary": str(marker_boundary or ""),
        "marker_budget": str(marker_budget or ""),
        "marker_owner": str(marker_owner or ""),
        "fingerprint": _sql_fingerprint(query_text),
        "first_paint_active": bool(context.get("render_id")),
        "role_capture": bool(role_capture),
        "recorded_at": datetime.now().isoformat(timespec="milliseconds"),
    }
    try:
        events = _session_list(_DIRECT_SQL_EVENTS_KEY)
        events.append(event)
        if len(events) > 250:
            del events[:-250]
    except Exception:
        pass
    metadata_probe = direct_sql_kind in {"metadata_probe", "account_usage_metadata_probe", "role_capture"}
    _record_query_budget_context_event(
        query_boundary=boundary,
        actual_execution=bool(allowed and not allowance),
        direct_sql=True,
        metadata_probe=metadata_probe,
        role_capture=bool(role_capture),
    )
    try:
        from runtime_state import record_runtime_event

        record_runtime_event(
            event_type="direct_sql",
            section=str(event.get("section") or ""),
            workflow=str(event.get("workflow") or ""),
            boundary=boundary,
            product_boundary=str(query_boundary or ""),
            execution_boundary=boundary,
            source_module="performance.record_direct_sql_event",
            direct_sql_count_delta=1,
            metadata_probe_count_delta=1 if metadata_probe else 0,
            account_usage_count_delta=1 if normalize_release_boundary(query_boundary) == "query_search_broad_explicit" else 0,
            started_at=str(event.get("recorded_at") or ""),
            finished_at=str(event.get("recorded_at") or ""),
            raw_sql_included=False,
            extra={"allowed": bool(allowed), "direct_sql_kind": direct_sql_kind},
        )
    except Exception:
        pass
    return event


def get_direct_sql_events() -> list[dict[str, Any]]:
    events = _session_list(_DIRECT_SQL_EVENTS_KEY)
    return [dict(event) for event in events if isinstance(event, dict)]


def clear_direct_sql_events() -> None:
    try:
        st.session_state[_DIRECT_SQL_EVENTS_KEY] = []
        st.session_state[_DIRECT_SQL_ALLOWANCE_STACK_KEY] = []
    except Exception:
        pass


def assert_direct_sql_allowed(
    query_text: object = "",
    *,
    section: str = "",
    workflow: str = "",
    reason: str = "session.sql",
    role_capture: bool = False,
) -> None:
    """Block direct session.sql during first paint unless the query runner allowed it."""
    allowance = _current_direct_sql_allowance()
    boundary = normalize_query_boundary(str(allowance.get("query_boundary") or "other"))
    max_rows = allowance.get("max_rows")
    allowed = True
    violation_reason = ""
    if is_first_paint_active():
        allowed = (
            boundary == "decision_packet"
            and max_rows == 1
            and bool(allowance.get("render_id"))
        )
        if not allowed:
            violation_reason = "Direct Snowflake SQL is not allowed during first paint outside the packet query."
    record_direct_sql_event(
        query_text=query_text,
        section=section or str(allowance.get("section") or ""),
        workflow=workflow,
        query_boundary=boundary,
        allowed=allowed,
        reason=reason if allowed else violation_reason,
        role_capture=role_capture,
    )
    if not allowed:
        record_first_paint_budget_violation(
            query_boundary=boundary,
            section=section or current_first_paint_section(),
            ttl_key="direct_session_sql",
            tier="direct",
            max_rows=max_rows if isinstance(max_rows, int) else None,
            reason=violation_reason,
        )
        if _strict_first_paint_mode():
            raise AssertionError(violation_reason)


def record_role_capture_event(
    *,
    section: str = "",
    query_boundary: str = "other",
    deferred: bool = False,
    executed: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    """Record role-capture behavior without storing SQL."""
    context = _current_first_paint_context()
    boundary = normalize_query_boundary(query_boundary)
    event = {
        "event_id": uuid4().hex[:16],
        "render_id": str(context.get("render_id") or ""),
        "section": str(section or context.get("section") or ""),
        "workflow": str(context.get("workflow") or ""),
        "boundary": boundary,
        "query_boundary": boundary,
        "deferred": bool(deferred),
        "executed": bool(executed),
        "first_paint_active": bool(context.get("render_id")),
        "reason": str(reason or "")[:240],
        "recorded_at": datetime.now().isoformat(timespec="milliseconds"),
    }
    try:
        events = _session_list(_ROLE_CAPTURE_EVENTS_KEY)
        events.append(event)
        if len(events) > 100:
            del events[:-100]
    except Exception:
        pass
    _record_query_budget_context_event(
        query_boundary=boundary,
        metadata_probe=bool(executed),
        role_capture=True,
    )
    try:
        from runtime_state import record_runtime_event

        record_runtime_event(
            event_type="role_capture",
            section=str(event.get("section") or ""),
            workflow=str(event.get("workflow") or ""),
            boundary=boundary,
            product_boundary=str(query_boundary or ""),
            execution_boundary=boundary,
            source_module="performance.record_role_capture_event",
            metadata_probe_count_delta=1 if executed else 0,
            started_at=str(event.get("recorded_at") or ""),
            finished_at=str(event.get("recorded_at") or ""),
            raw_sql_included=False,
            extra={"deferred": bool(deferred), "executed": bool(executed)},
        )
    except Exception:
        pass
    return event


def get_role_capture_events() -> list[dict[str, Any]]:
    events = _session_list(_ROLE_CAPTURE_EVENTS_KEY)
    return [dict(event) for event in events if isinstance(event, dict)]


def clear_role_capture_events() -> None:
    try:
        st.session_state[_ROLE_CAPTURE_EVENTS_KEY] = []
    except Exception:
        pass


def record_query_lint_finding(
    *,
    fingerprint: str = "",
    code: str = "",
    severity: str = "",
    message: str = "",
    boundary: str = "other",
    section: str = "",
    ttl_key: str = "",
    tier: str = "",
    contract_id: str = "",
) -> dict[str, Any]:
    """Record sanitized query lint findings from the central runner."""
    event = {
        "event_id": uuid4().hex[:16],
        "fingerprint": str(fingerprint or "")[:32],
        "code": str(code or "")[:80],
        "severity": str(severity or "")[:40],
        "message": _safe_message(message) or str(message or "")[:300],
        "boundary": str(boundary or "other"),
        "section": str(section or ""),
        "ttl_key": str(ttl_key or "")[:160],
        "tier": str(tier or ""),
        "contract_id": str(contract_id or "")[:120],
        "recorded_at": datetime.now().isoformat(timespec="milliseconds"),
    }
    try:
        events = _session_list(_QUERY_LINT_FINDINGS_KEY)
        events.append(event)
        if len(events) > 250:
            del events[:-250]
    except Exception:
        pass
    return event


def get_query_lint_findings() -> list[dict[str, Any]]:
    events = _session_list(_QUERY_LINT_FINDINGS_KEY)
    return [dict(event) for event in events if isinstance(event, dict)]


def clear_query_lint_findings() -> None:
    try:
        st.session_state[_QUERY_LINT_FINDINGS_KEY] = []
    except Exception:
        pass


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
    query_contract_id: str = "",
    target_label: str = "",
    target_context_present: bool | None = None,
    target_columns_used: tuple[str, ...] | list[str] | None = None,
    target_predicate_marker_present: bool | None = None,
    target_fallback_used: bool | None = None,
    target_predicate_plan_id: str = "",
    first_paint_sensitive: bool = False,
    render_id: str | None = None,
) -> dict[str, Any]:
    """Record lightweight, SQL-free UI query telemetry in session state."""
    cache_layer = str(cache_layer or "unknown")
    if cache_layer not in _VALID_CACHE_LAYERS:
        cache_layer = "unknown"
    original_boundary = str(query_boundary or "other")
    query_boundary = normalize_query_boundary(original_boundary)
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
        # A known real execution is never a cache hit, even when it was stored
        # through a cache layer; only unknown execution falls back to the layer.
        "cache_hit": (
            actual_query_executed is False
            or (
                actual_query_executed is None
                and cache_layer in {"session", "streamlit_cache", "paused"}
            )
        ),
        "boundary": query_boundary,
        "product_boundary": original_boundary,
        "query_boundary": query_boundary,
        "query_contract_id": str(query_contract_id or "")[:120],
        "target_label": str(target_label or "")[:250],
        "target_context_present": target_context_present,
        "target_columns_used": [str(column)[:120] for column in (target_columns_used or [])],
        "target_predicate_marker_present": target_predicate_marker_present,
        "target_fallback_used": target_fallback_used,
        "target_predicate_plan_id": str(target_predicate_plan_id or "")[:80],
        "first_paint_sensitive": bool(first_paint_sensitive),
        "raw_sql_included": False,
    }
    try:
        events = st.session_state.setdefault(_UI_QUERY_EVENTS_KEY, [])
        events.append(event)
        if len(events) > 250:
            del events[:-250]
    except Exception:
        pass
    _record_query_budget_context_event(
        query_boundary=original_boundary,
        # UI query events are diagnostic. Actual Snowflake execution budgets are
        # driven by increment_snowflake_execution_counter() and direct SQL
        # events so a single runner call is not counted twice.
        actual_execution=False,
    )
    try:
        from runtime_state import record_runtime_event

        record_runtime_event(
            event_type="query",
            section=str(event.get("section") or ""),
            workflow=str(event.get("workflow") or ""),
            boundary=query_boundary,
            product_boundary=original_boundary,
            execution_boundary=query_boundary,
            query_tier=str(query_tier or ""),
            ttl_key=str(ttl_key or ""),
            cache_hit=bool(event.get("cache_hit")),
            elapsed_ms=float(event.get("elapsed_ms") or 0),
            row_count=int(event.get("row_count") or 0),
            max_rows=event.get("max_rows") if isinstance(event.get("max_rows"), int) else None,
            error=str(event.get("error") or ""),
            source_module="performance.record_ui_query_event",
            query_count_delta=1,
            account_usage_count_delta=1 if original_boundary.strip().lower() == "account_usage" else 0,
            started_at=str(event.get("started_at") or ""),
            finished_at=str(event.get("finished_at") or ""),
            raw_sql_included=False,
            extra={
                "actual_query_executed": event.get("actual_query_executed"),
                "cache_layer": cache_layer,
                "first_paint_sensitive": bool(first_paint_sensitive),
            },
        )
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
        "session_open_events": len([
            event for event in get_snowflake_session_open_events()
            if str(event.get("render_id") or "") in render_ids
        ]),
        "direct_sql_violation_events": len([
            event for event in get_direct_sql_events()
            if str(event.get("render_id") or "") in render_ids and not bool(event.get("allowed"))
        ]),
        "role_capture_queries_first_paint": len([
            event for event in get_role_capture_events()
            if str(event.get("render_id") or "") in render_ids and bool(event.get("executed"))
        ]),
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
    boundary = normalize_query_boundary(query_boundary)
    context = _current_first_paint_context()
    event = {
        "event_id": uuid4().hex[:16],
        "render_id": str(context.get("render_id") or ""),
        "section": str(section or context.get("section") or ""),
        "boundary": boundary,
        "query_boundary": boundary,
        "ttl_key": str(ttl_key or ""),
        "tier": str(tier or ""),
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "raw_sql_included": False,
    }
    try:
        events = _session_list(_SNOWFLAKE_EXECUTION_EVENTS_KEY)
        events.append(event)
        if len(events) > 250:
            del events[:-250]
    except Exception:
        pass
    _record_query_budget_context_event(query_boundary=str(query_boundary or "other"), actual_execution=True)
    try:
        from runtime_state import record_runtime_event

        record_runtime_event(
            event_type="snowflake_execution",
            section=str(event.get("section") or ""),
            workflow="",
            boundary=boundary,
            product_boundary=str(query_boundary or ""),
            execution_boundary=boundary,
            query_tier=str(tier or ""),
            ttl_key=str(ttl_key or ""),
            source_module="performance.increment_snowflake_execution_counter",
            query_count_delta=1,
            account_usage_count_delta=1 if str(query_boundary or "").strip().lower() == "account_usage" else 0,
            started_at=str(event.get("timestamp") or ""),
            finished_at=str(event.get("timestamp") or ""),
            raw_sql_included=False,
        )
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
        st.session_state[_SNOWFLAKE_SESSION_OPEN_EVENTS_KEY] = []
        st.session_state[_QUERY_LINT_FINDINGS_KEY] = []
        st.session_state[_DIRECT_SQL_EVENTS_KEY] = []
        st.session_state[_DIRECT_SQL_ALLOWANCE_STACK_KEY] = []
        st.session_state[_ROLE_CAPTURE_EVENTS_KEY] = []
        st.session_state[_QUERY_BUDGET_CONTEXT_STACK_KEY] = []
        st.session_state[_QUERY_BUDGET_CONTEXT_EVENTS_KEY] = []
    except Exception:
        pass


def render_performance_debug_panel() -> None:
    """Render query telemetry only in explicit debug/admin surfaces."""
    events = get_ui_query_events()
    if not events:
        st.caption("No Decision Workspace UI query events recorded in this session.")
        return
    st.dataframe(events, width="stretch", hide_index=True)
