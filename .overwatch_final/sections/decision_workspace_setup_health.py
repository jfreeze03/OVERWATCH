"""Admin-only setup health for Decision Workspace summaries."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from html import escape as _escape_html
from typing import Mapping
from uuid import uuid4

import streamlit as st

from config import ADMIN_ACCESS_ROLES
from utils.performance import ADMIN_CLICK_QUERY_BUDGET, query_budget_context
from runtime_state import CURRENT_ROLE, SIDEBAR_PANEL


SETUP_HEALTH_KEY = "_overwatch_decision_setup_health"
SETUP_HEALTH_PANEL_OPEN_KEY = "_overwatch_show_decision_setup_health"
SETUP_HEALTH_TABLE = "OVERWATCH_DECISION_SETUP_HEALTH"


@dataclass(frozen=True)
class DecisionBootstrapHealth:
    status: str
    user_message: str
    global_status: str = "UNKNOWN"
    selected_scope_status: str = "UNKNOWN"
    current_section_status: str = "UNKNOWN"
    selected_procedure: str = ""
    fallback_used: bool = False
    current_packet_count: int = 0
    sections_present: tuple[str, ...] = ()
    missing_sections: tuple[str, ...] = ()
    duplicate_current_keys: int = 0
    stale_sections: tuple[str, ...] = ()
    data_gap_sections: tuple[str, ...] = ()
    missing_metric_sections: tuple[str, ...] = ()
    degraded_sections: tuple[str, ...] = ()
    invalid_sections: tuple[str, ...] = ()
    warning_sections: tuple[str, ...] = ()
    max_packet_bytes: int | None = None
    requested_scope: str = ""
    resolved_scope: str = ""
    admin_detail: str = ""
    suggested_remediation: str = ""
    actor_role: str = ""
    app_version: str = ""
    persistence_status: str = "local_only"
    persistence_error: str = ""
    recorded_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def _tuple_from(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    try:
        return tuple(str(item) for item in value if str(item))
    except TypeError:
        return (str(value),)


def _health_from_mapping(raw: Mapping[str, object]) -> DecisionBootstrapHealth:
    return DecisionBootstrapHealth(
        status=str(raw.get("status", "")),
        user_message=str(raw.get("user_message", "")),
        global_status=str(raw.get("global_status", "") or "UNKNOWN"),
        selected_scope_status=str(raw.get("selected_scope_status", "") or "UNKNOWN"),
        current_section_status=str(raw.get("current_section_status", "") or "UNKNOWN"),
        selected_procedure=str(raw.get("selected_procedure", "")),
        fallback_used=bool(raw.get("fallback_used", False)),
        current_packet_count=int(raw.get("current_packet_count") or 0),
        sections_present=_tuple_from(raw.get("sections_present")),
        missing_sections=_tuple_from(raw.get("missing_sections")),
        duplicate_current_keys=int(raw.get("duplicate_current_keys") or 0),
        stale_sections=_tuple_from(raw.get("stale_sections")),
        data_gap_sections=_tuple_from(raw.get("data_gap_sections")),
        missing_metric_sections=_tuple_from(raw.get("missing_metric_sections")),
        degraded_sections=_tuple_from(raw.get("degraded_sections")),
        invalid_sections=_tuple_from(raw.get("invalid_sections")),
        warning_sections=_tuple_from(raw.get("warning_sections")),
        max_packet_bytes=raw.get("max_packet_bytes") if raw.get("max_packet_bytes") is None else int(raw.get("max_packet_bytes") or 0),
        requested_scope=str(raw.get("requested_scope", "")),
        resolved_scope=str(raw.get("resolved_scope", "")),
        admin_detail=str(raw.get("admin_detail", "")),
        suggested_remediation=str(raw.get("suggested_remediation", "")),
        actor_role=str(raw.get("actor_role", "")),
        app_version=str(raw.get("app_version", "")),
        persistence_status=str(raw.get("persistence_status", "") or "local_only"),
        persistence_error=str(raw.get("persistence_error", "")),
        recorded_at=str(raw.get("recorded_at", "")),
    )


def _sql_literal(value: object, max_len: int = 4000) -> str:
    text = str(value if value is not None else "")
    if max_len > 0:
        text = text[:max_len]
    return "'" + text.replace("'", "''") + "'"


def _json_array(values: tuple[str, ...]) -> str:
    return json.dumps(tuple(values or ()))


def _health_table_ddl() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {SETUP_HEALTH_TABLE} (
  EVENT_ID VARCHAR(64),
  EVENT_TS TIMESTAMP_NTZ,
  STATUS VARCHAR(40),
  USER_MESSAGE VARCHAR(2000),
  GLOBAL_STATUS VARCHAR(40),
  SELECTED_SCOPE_STATUS VARCHAR(40),
  CURRENT_SECTION_STATUS VARCHAR(40),
  SELECTED_PROCEDURE VARCHAR(300),
  FALLBACK_USED BOOLEAN,
  CURRENT_PACKET_COUNT NUMBER,
  SECTIONS_PRESENT VARIANT,
  MISSING_SECTIONS VARIANT,
  DUPLICATE_CURRENT_KEYS NUMBER,
  STALE_SECTIONS VARIANT,
  DATA_GAP_SECTIONS VARIANT,
  MISSING_METRIC_SECTIONS VARIANT,
  DEGRADED_SECTIONS VARIANT,
  INVALID_SECTIONS VARIANT,
  WARNING_SECTIONS VARIANT,
  MAX_PACKET_BYTES NUMBER,
  REQUESTED_SCOPE VARCHAR(500),
  RESOLVED_SCOPE VARCHAR(500),
  ADMIN_DETAIL VARCHAR(8000),
  SUGGESTED_REMEDIATION VARCHAR(4000),
  ACTOR_ROLE VARCHAR(200),
  APP_VERSION VARCHAR(120),
  PERSISTENCE_STATUS VARCHAR(40),
  PERSISTENCE_ERROR VARCHAR(4000),
  LOAD_TS TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
"""


def _health_table_migration_sql() -> tuple[str, ...]:
    return (
        f"ALTER TABLE IF EXISTS {SETUP_HEALTH_TABLE} ADD COLUMN IF NOT EXISTS GLOBAL_STATUS VARCHAR(40)",
        f"ALTER TABLE IF EXISTS {SETUP_HEALTH_TABLE} ADD COLUMN IF NOT EXISTS SELECTED_SCOPE_STATUS VARCHAR(40)",
        f"ALTER TABLE IF EXISTS {SETUP_HEALTH_TABLE} ADD COLUMN IF NOT EXISTS CURRENT_SECTION_STATUS VARCHAR(40)",
        f"ALTER TABLE IF EXISTS {SETUP_HEALTH_TABLE} ADD COLUMN IF NOT EXISTS DEGRADED_SECTIONS VARIANT",
        f"ALTER TABLE IF EXISTS {SETUP_HEALTH_TABLE} ADD COLUMN IF NOT EXISTS INVALID_SECTIONS VARIANT",
        f"ALTER TABLE IF EXISTS {SETUP_HEALTH_TABLE} ADD COLUMN IF NOT EXISTS WARNING_SECTIONS VARIANT",
        f"ALTER TABLE IF EXISTS {SETUP_HEALTH_TABLE} ADD COLUMN IF NOT EXISTS PERSISTENCE_STATUS VARCHAR(40)",
        f"ALTER TABLE IF EXISTS {SETUP_HEALTH_TABLE} ADD COLUMN IF NOT EXISTS PERSISTENCE_ERROR VARCHAR(4000)",
    )


def persist_decision_setup_health(session: object | None, health: DecisionBootstrapHealth) -> bool:
    """Persist setup health when Snowflake is available; never fail daily UI."""
    if session is None:
        raw = st.session_state.get(SETUP_HEALTH_KEY)
        if isinstance(raw, Mapping):
            updated = dict(raw)
            updated["persistence_status"] = "local_only"
            updated["persistence_error"] = ""
            st.session_state[SETUP_HEALTH_KEY] = updated
        return False
    try:
        session.sql(_health_table_ddl()).collect()
        for migration_sql in _health_table_migration_sql():
            session.sql(migration_sql).collect()
        event_id = uuid4().hex
        sql = f"""
INSERT INTO {SETUP_HEALTH_TABLE} (
  EVENT_ID, EVENT_TS, STATUS, USER_MESSAGE, GLOBAL_STATUS, SELECTED_SCOPE_STATUS,
  CURRENT_SECTION_STATUS, SELECTED_PROCEDURE, FALLBACK_USED,
  CURRENT_PACKET_COUNT, SECTIONS_PRESENT, MISSING_SECTIONS, DUPLICATE_CURRENT_KEYS,
  STALE_SECTIONS, DATA_GAP_SECTIONS, MISSING_METRIC_SECTIONS, DEGRADED_SECTIONS,
  INVALID_SECTIONS, WARNING_SECTIONS, MAX_PACKET_BYTES,
  REQUESTED_SCOPE, RESOLVED_SCOPE, ADMIN_DETAIL, SUGGESTED_REMEDIATION, ACTOR_ROLE,
  APP_VERSION, PERSISTENCE_STATUS, PERSISTENCE_ERROR
)
SELECT
  {_sql_literal(event_id, 64)},
  CURRENT_TIMESTAMP(),
  {_sql_literal(health.status, 40)},
  {_sql_literal(health.user_message, 2000)},
  {_sql_literal(health.global_status, 40)},
  {_sql_literal(health.selected_scope_status, 40)},
  {_sql_literal(health.current_section_status, 40)},
  {_sql_literal(health.selected_procedure, 300)},
  {str(bool(health.fallback_used)).upper()},
  {int(health.current_packet_count or 0)},
  PARSE_JSON({_sql_literal(_json_array(health.sections_present), 8000)}),
  PARSE_JSON({_sql_literal(_json_array(health.missing_sections), 8000)}),
  {int(health.duplicate_current_keys or 0)},
  PARSE_JSON({_sql_literal(_json_array(health.stale_sections), 8000)}),
  PARSE_JSON({_sql_literal(_json_array(health.data_gap_sections), 8000)}),
  PARSE_JSON({_sql_literal(_json_array(health.missing_metric_sections), 8000)}),
  PARSE_JSON({_sql_literal(_json_array(health.degraded_sections), 8000)}),
  PARSE_JSON({_sql_literal(_json_array(health.invalid_sections), 8000)}),
  PARSE_JSON({_sql_literal(_json_array(health.warning_sections), 8000)}),
  {"NULL" if health.max_packet_bytes is None else int(health.max_packet_bytes)},
  {_sql_literal(health.requested_scope, 500)},
  {_sql_literal(health.resolved_scope, 500)},
  {_sql_literal(health.admin_detail, 8000)},
  {_sql_literal(health.suggested_remediation, 4000)},
  {_sql_literal(health.actor_role, 200)},
  {_sql_literal(health.app_version, 120)},
  'persisted',
  {_sql_literal(health.persistence_error, 4000)}
"""
        session.sql(sql).collect()
        raw = st.session_state.get(SETUP_HEALTH_KEY)
        if isinstance(raw, Mapping):
            updated = dict(raw)
            updated["persistence_status"] = "persisted"
            updated["persistence_error"] = ""
            st.session_state[SETUP_HEALTH_KEY] = updated
        return True
    except Exception as exc:
        raw = st.session_state.get(SETUP_HEALTH_KEY)
        if isinstance(raw, Mapping):
            updated = dict(raw)
            detail = str(updated.get("admin_detail", ""))
            updated["admin_detail"] = "; ".join(
                part for part in (detail, f"Setup health persistence failed: {exc}") if part
            )
            updated["persistence_status"] = "unavailable"
            updated["persistence_error"] = str(exc)
            st.session_state[SETUP_HEALTH_KEY] = updated
        return False


def record_decision_bootstrap_health(
    *,
    status: str,
    user_message: str,
    selected_procedure: str = "",
    fallback_used: bool = False,
    validation: object | None = None,
    admin_detail: str = "",
    suggested_remediation: str = "",
    session: object | None = None,
) -> DecisionBootstrapHealth:
    """Store the latest setup health details for Settings/Admin surfaces."""
    def _scope_label(prefix: str) -> str:
        company = str(getattr(validation, f"{prefix}_company", "") or "").strip()
        environment = str(getattr(validation, f"{prefix}_environment", "") or "").strip()
        window_days = str(getattr(validation, f"{prefix}_window_days", "") or "").strip()
        if not (company or environment or window_days):
            return ""
        return f"{company or 'Unknown'} / {environment or 'Unknown'} / {window_days or 'Unknown'} days"

    health = DecisionBootstrapHealth(
        status=str(status or "unknown").upper(),
        user_message=str(user_message or ""),
        global_status=str(getattr(validation, "global_status", "") or "UNKNOWN").upper(),
        selected_scope_status=str(getattr(validation, "selected_scope_status", "") or "UNKNOWN").upper(),
        current_section_status=str(getattr(validation, "current_section_status", "") or "UNKNOWN").upper(),
        selected_procedure=str(selected_procedure or ""),
        fallback_used=bool(fallback_used),
        current_packet_count=int(getattr(validation, "current_packet_count", 0) or 0),
        sections_present=tuple(getattr(validation, "sections_present", ()) or ()),
        missing_sections=tuple(getattr(validation, "missing_sections", ()) or ()),
        duplicate_current_keys=int(getattr(validation, "duplicate_current_keys", 0) or 0),
        stale_sections=tuple(getattr(validation, "stale_sections", ()) or ()),
        data_gap_sections=tuple(getattr(validation, "data_gap_sections", ()) or ()),
        missing_metric_sections=tuple(getattr(validation, "missing_metric_sections", ()) or ()),
        degraded_sections=tuple(getattr(validation, "degraded_sections", ()) or ()),
        invalid_sections=tuple(getattr(validation, "invalid_sections", ()) or ()),
        warning_sections=tuple(getattr(validation, "warning_sections", ()) or ()),
        max_packet_bytes=getattr(validation, "max_packet_bytes", None),
        requested_scope=_scope_label("requested"),
        resolved_scope=_scope_label("resolved"),
        admin_detail=str(admin_detail or getattr(validation, "admin_detail", "") or ""),
        suggested_remediation=str(
            suggested_remediation
            or "Deploy the latest OVERWATCH mart setup, then run CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();"
        ),
        actor_role=str(st.session_state.get(CURRENT_ROLE, "") or ""),
        app_version="OVERWATCH Decision Workspace",
    )
    st.session_state[SETUP_HEALTH_KEY] = asdict(health)
    persisted = persist_decision_setup_health(session, health)
    if session is None:
        health = replace(health, persistence_status="local_only", persistence_error="")
    elif persisted:
        health = replace(health, persistence_status="persisted", persistence_error="")
    else:
        raw = st.session_state.get(SETUP_HEALTH_KEY, {})
        error = raw.get("persistence_error", "") if isinstance(raw, Mapping) else ""
        health = replace(health, persistence_status="unavailable", persistence_error=str(error or "Persistence failed"))
    st.session_state[SETUP_HEALTH_KEY] = asdict(health)
    return health


def load_decision_setup_health(session: object | None = None) -> DecisionBootstrapHealth | None:
    """Return the latest locally or persistently recorded setup health snapshot."""
    raw = st.session_state.get(SETUP_HEALTH_KEY)
    if isinstance(raw, DecisionBootstrapHealth):
        return raw
    if isinstance(raw, Mapping):
        return _health_from_mapping(raw)
    if session is not None:
        try:
            rows = session.sql(
                f"""
SELECT
  STATUS, USER_MESSAGE, GLOBAL_STATUS, SELECTED_SCOPE_STATUS, CURRENT_SECTION_STATUS,
  SELECTED_PROCEDURE, FALLBACK_USED, CURRENT_PACKET_COUNT,
  SECTIONS_PRESENT, MISSING_SECTIONS, DUPLICATE_CURRENT_KEYS, STALE_SECTIONS,
  DATA_GAP_SECTIONS, MISSING_METRIC_SECTIONS, DEGRADED_SECTIONS, INVALID_SECTIONS,
  WARNING_SECTIONS, MAX_PACKET_BYTES, REQUESTED_SCOPE,
  RESOLVED_SCOPE, ADMIN_DETAIL, SUGGESTED_REMEDIATION, ACTOR_ROLE, APP_VERSION,
  PERSISTENCE_STATUS, PERSISTENCE_ERROR, TO_VARCHAR(EVENT_TS) AS RECORDED_AT
FROM {SETUP_HEALTH_TABLE}
ORDER BY EVENT_TS DESC
LIMIT 1
"""
            ).collect()
        except Exception:
            return None
        if rows:
            first = rows[0]
            if hasattr(first, "as_dict"):
                mapping = first.as_dict()
            elif isinstance(first, Mapping):
                mapping = first
            else:
                mapping = {}
            normalized = {str(k).lower(): v for k, v in mapping.items()}
            normalized["persistence_status"] = "persisted"
            health = _health_from_mapping(normalized)
            st.session_state[SETUP_HEALTH_KEY] = asdict(health)
            return health
    return None


def load_decision_setup_health_history(session: object | None = None, *, limit: int = 5) -> tuple[DecisionBootstrapHealth, ...]:
    """Return recent persisted setup-health events for Settings/Admin surfaces."""
    if session is None:
        latest = load_decision_setup_health(session=None)
        return (latest,) if latest is not None else ()
    try:
        rows = session.sql(
            f"""
SELECT
  STATUS, USER_MESSAGE, GLOBAL_STATUS, SELECTED_SCOPE_STATUS, CURRENT_SECTION_STATUS,
  SELECTED_PROCEDURE, FALLBACK_USED, CURRENT_PACKET_COUNT,
  SECTIONS_PRESENT, MISSING_SECTIONS, DUPLICATE_CURRENT_KEYS, STALE_SECTIONS,
  DATA_GAP_SECTIONS, MISSING_METRIC_SECTIONS, DEGRADED_SECTIONS, INVALID_SECTIONS,
  WARNING_SECTIONS, MAX_PACKET_BYTES, REQUESTED_SCOPE,
  RESOLVED_SCOPE, ADMIN_DETAIL, SUGGESTED_REMEDIATION, ACTOR_ROLE, APP_VERSION,
  PERSISTENCE_STATUS, PERSISTENCE_ERROR, TO_VARCHAR(EVENT_TS) AS RECORDED_AT
FROM {SETUP_HEALTH_TABLE}
ORDER BY EVENT_TS DESC
LIMIT {max(1, int(limit or 5))}
"""
        ).collect()
    except Exception:
        return ()
    history: list[DecisionBootstrapHealth] = []
    for row in rows:
        if hasattr(row, "as_dict"):
            mapping = row.as_dict()
        elif isinstance(row, Mapping):
            mapping = row
        else:
            mapping = {}
        normalized = {str(k).lower(): v for k, v in mapping.items()}
        normalized["persistence_status"] = normalized.get("persistence_status") or "persisted"
        history.append(_health_from_mapping(normalized))
    return tuple(history)


def _list_text(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "None"


def open_decision_setup_health() -> None:
    """Open Settings and expand the Decision setup health panel."""
    st.session_state[SIDEBAR_PANEL] = "settings"
    st.session_state[SETUP_HEALTH_PANEL_OPEN_KEY] = True


def can_open_decision_setup_health() -> bool:
    """Return whether the daily fallback may show a safe Settings route."""
    role = str(st.session_state.get(CURRENT_ROLE, "") or "").strip().upper()
    if os.environ.get("OVERWATCH_TEST_MODE") == "1" or os.environ.get("OVERWATCH_ALLOW_SETUP_HEALTH_LOCAL") == "1":
        return True
    if not role:
        return False
    try:
        from access_control import admin_access_is_allowed

        return bool(admin_access_is_allowed(role, True))
    except Exception:
        return role in set(ADMIN_ACCESS_ROLES)


def render_decision_setup_health_panel(session: object | None = None) -> None:
    """Render admin diagnostics without leaking them into daily Decision Workspace UI."""
    health = load_decision_setup_health(session=session)
    if health is None:
        return
    expanded = bool(st.session_state.pop(SETUP_HEALTH_PANEL_OPEN_KEY, False))
    with st.expander("Decision Summary Setup Health", expanded=expanded):
        st.markdown(
            f"""
            <div class="ow-setup-health-panel">
                <div class="ow-setup-health-header">
                    <strong class="ow-setup-health-badge" data-status="{_escape_html(health.status.upper())}">
                        {_escape_html(health.status.upper())}
                    </strong>
                    <span>{_escape_html(health.user_message)}</span>
                </div>
                <div class="ow-setup-health-grid">
                    <span><b>Global</b>{_escape_html(health.global_status or "UNKNOWN")}</span>
                    <span><b>Selected scope</b>{_escape_html(health.selected_scope_status or "UNKNOWN")}</span>
                    <span><b>Current section</b>{_escape_html(health.current_section_status or "UNKNOWN")}</span>
                    <span><b>Recorded</b>{_escape_html(health.recorded_at or "Unavailable")}</span>
                    <span><b>Procedure</b>{_escape_html(health.selected_procedure or "Unavailable")}</span>
                    <span><b>Fallback</b>{'Yes' if health.fallback_used else 'No'}</span>
                    <span><b>Packets</b>{int(health.current_packet_count or 0)}</span>
                    <span><b>Requested</b>{_escape_html(health.requested_scope or "Unavailable")}</span>
                    <span><b>Resolved</b>{_escape_html(health.resolved_scope or "Unavailable")}</span>
                    <span><b>Duplicates</b>{int(health.duplicate_current_keys or 0)}</span>
                    <span><b>Persistence</b>{_escape_html(health.persistence_status or "local_only")}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write(f"Sections present: {_list_text(health.sections_present)}")
        st.write(f"Missing sections: {_list_text(health.missing_sections)}")
        st.write(f"Stale sections: {_list_text(health.stale_sections)}")
        st.write(f"Data Gap sections: {_list_text(health.data_gap_sections)}")
        st.write(f"Missing metric sections: {_list_text(health.missing_metric_sections)}")
        st.write(f"Degraded sections: {_list_text(health.degraded_sections)}")
        st.write(f"Invalid sections: {_list_text(health.invalid_sections)}")
        st.write(f"Warning sections: {_list_text(health.warning_sections)}")
        st.write(f"Packet budget: {health.max_packet_bytes if health.max_packet_bytes is not None else 'Unavailable'} bytes")
        if st.button("Refresh Setup Health", key="decision_setup_health_refresh", type="secondary"):
            with query_budget_context(
                "admin_setup",
                section="Settings/Admin Setup Health",
                workflow="Setup Health",
                budget=ADMIN_CLICK_QUERY_BUDGET,
            ):
                st.session_state[SETUP_HEALTH_PANEL_OPEN_KEY] = True
                st.session_state["_overwatch_decision_setup_health_refresh_requested"] = True
        history = tuple(item for item in load_decision_setup_health_history(session=session) if item.recorded_at != health.recorded_at)
        if history:
            st.markdown("**Recent setup-health events**")
            for item in history[:5]:
                st.write(
                    f"{item.recorded_at or 'Unknown time'} - {item.status or 'UNKNOWN'} - "
                    f"{item.requested_scope or 'scope unavailable'} -> {item.resolved_scope or 'unresolved'}"
                )
        if health.admin_detail:
            admin_detail = health.admin_detail
            if health.persistence_error:
                admin_detail = "; ".join((admin_detail, f"Persistence error: {health.persistence_error}"))
            st.code(admin_detail)
            st.code(
                "\n".join(
                    part for part in (
                        f"Status: {health.status}",
                        f"Procedure: {health.selected_procedure or 'Unavailable'}",
                        f"Requested: {health.requested_scope or 'Unavailable'}",
                        f"Resolved: {health.resolved_scope or 'Unavailable'}",
                        f"Missing sections: {_list_text(health.missing_sections)}",
                        f"Data gaps: {_list_text(health.data_gap_sections)}",
                        f"Persistence: {health.persistence_status}",
                        f"Remediation: {health.suggested_remediation}",
                    )
                ),
                language="text",
            )
        st.info(health.suggested_remediation)


__all__ = [
    "DecisionBootstrapHealth",
    "SETUP_HEALTH_KEY",
    "SETUP_HEALTH_PANEL_OPEN_KEY",
    "SETUP_HEALTH_TABLE",
    "load_decision_setup_health",
    "load_decision_setup_health_history",
    "open_decision_setup_health",
    "can_open_decision_setup_health",
    "persist_decision_setup_health",
    "record_decision_bootstrap_health",
    "render_decision_setup_health_panel",
]
