"""Admin-only setup health for Decision Workspace summaries."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape as _escape_html
from typing import Mapping
from uuid import uuid4

import streamlit as st

from runtime_state import CURRENT_ROLE, SIDEBAR_PANEL


SETUP_HEALTH_KEY = "_overwatch_decision_setup_health"
SETUP_HEALTH_PANEL_OPEN_KEY = "_overwatch_show_decision_setup_health"
SETUP_HEALTH_TABLE = "OVERWATCH_DECISION_SETUP_HEALTH"


@dataclass(frozen=True)
class DecisionBootstrapHealth:
    status: str
    user_message: str
    selected_procedure: str = ""
    fallback_used: bool = False
    current_packet_count: int = 0
    sections_present: tuple[str, ...] = ()
    missing_sections: tuple[str, ...] = ()
    duplicate_current_keys: int = 0
    stale_sections: tuple[str, ...] = ()
    data_gap_sections: tuple[str, ...] = ()
    missing_metric_sections: tuple[str, ...] = ()
    max_packet_bytes: int | None = None
    requested_scope: str = ""
    resolved_scope: str = ""
    admin_detail: str = ""
    suggested_remediation: str = ""
    actor_role: str = ""
    app_version: str = ""
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
        selected_procedure=str(raw.get("selected_procedure", "")),
        fallback_used=bool(raw.get("fallback_used", False)),
        current_packet_count=int(raw.get("current_packet_count") or 0),
        sections_present=_tuple_from(raw.get("sections_present")),
        missing_sections=_tuple_from(raw.get("missing_sections")),
        duplicate_current_keys=int(raw.get("duplicate_current_keys") or 0),
        stale_sections=_tuple_from(raw.get("stale_sections")),
        data_gap_sections=_tuple_from(raw.get("data_gap_sections")),
        missing_metric_sections=_tuple_from(raw.get("missing_metric_sections")),
        max_packet_bytes=raw.get("max_packet_bytes") if raw.get("max_packet_bytes") is None else int(raw.get("max_packet_bytes") or 0),
        requested_scope=str(raw.get("requested_scope", "")),
        resolved_scope=str(raw.get("resolved_scope", "")),
        admin_detail=str(raw.get("admin_detail", "")),
        suggested_remediation=str(raw.get("suggested_remediation", "")),
        actor_role=str(raw.get("actor_role", "")),
        app_version=str(raw.get("app_version", "")),
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
  SELECTED_PROCEDURE VARCHAR(300),
  FALLBACK_USED BOOLEAN,
  CURRENT_PACKET_COUNT NUMBER,
  SECTIONS_PRESENT VARIANT,
  MISSING_SECTIONS VARIANT,
  DUPLICATE_CURRENT_KEYS NUMBER,
  STALE_SECTIONS VARIANT,
  DATA_GAP_SECTIONS VARIANT,
  MISSING_METRIC_SECTIONS VARIANT,
  MAX_PACKET_BYTES NUMBER,
  REQUESTED_SCOPE VARCHAR(500),
  RESOLVED_SCOPE VARCHAR(500),
  ADMIN_DETAIL VARCHAR(8000),
  SUGGESTED_REMEDIATION VARCHAR(4000),
  ACTOR_ROLE VARCHAR(200),
  APP_VERSION VARCHAR(120),
  LOAD_TS TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
"""


def persist_decision_setup_health(session: object | None, health: DecisionBootstrapHealth) -> bool:
    """Persist setup health when Snowflake is available; never fail daily UI."""
    if session is None:
        return False
    try:
        session.sql(_health_table_ddl()).collect()
        event_id = uuid4().hex
        sql = f"""
INSERT INTO {SETUP_HEALTH_TABLE} (
  EVENT_ID, EVENT_TS, STATUS, USER_MESSAGE, SELECTED_PROCEDURE, FALLBACK_USED,
  CURRENT_PACKET_COUNT, SECTIONS_PRESENT, MISSING_SECTIONS, DUPLICATE_CURRENT_KEYS,
  STALE_SECTIONS, DATA_GAP_SECTIONS, MISSING_METRIC_SECTIONS, MAX_PACKET_BYTES,
  REQUESTED_SCOPE, RESOLVED_SCOPE, ADMIN_DETAIL, SUGGESTED_REMEDIATION, ACTOR_ROLE, APP_VERSION
)
SELECT
  {_sql_literal(event_id, 64)},
  CURRENT_TIMESTAMP(),
  {_sql_literal(health.status, 40)},
  {_sql_literal(health.user_message, 2000)},
  {_sql_literal(health.selected_procedure, 300)},
  {str(bool(health.fallback_used)).upper()},
  {int(health.current_packet_count or 0)},
  PARSE_JSON({_sql_literal(_json_array(health.sections_present), 8000)}),
  PARSE_JSON({_sql_literal(_json_array(health.missing_sections), 8000)}),
  {int(health.duplicate_current_keys or 0)},
  PARSE_JSON({_sql_literal(_json_array(health.stale_sections), 8000)}),
  PARSE_JSON({_sql_literal(_json_array(health.data_gap_sections), 8000)}),
  PARSE_JSON({_sql_literal(_json_array(health.missing_metric_sections), 8000)}),
  {"NULL" if health.max_packet_bytes is None else int(health.max_packet_bytes)},
  {_sql_literal(health.requested_scope, 500)},
  {_sql_literal(health.resolved_scope, 500)},
  {_sql_literal(health.admin_detail, 8000)},
  {_sql_literal(health.suggested_remediation, 4000)},
  {_sql_literal(health.actor_role, 200)},
  {_sql_literal(health.app_version, 120)}
"""
        session.sql(sql).collect()
        return True
    except Exception as exc:
        raw = st.session_state.get(SETUP_HEALTH_KEY)
        if isinstance(raw, Mapping):
            updated = dict(raw)
            detail = str(updated.get("admin_detail", ""))
            updated["admin_detail"] = "; ".join(
                part for part in (detail, f"Setup health persistence failed: {exc}") if part
            )
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
        status=str(status or "unknown"),
        user_message=str(user_message or ""),
        selected_procedure=str(selected_procedure or ""),
        fallback_used=bool(fallback_used),
        current_packet_count=int(getattr(validation, "current_packet_count", 0) or 0),
        sections_present=tuple(getattr(validation, "sections_present", ()) or ()),
        missing_sections=tuple(getattr(validation, "missing_sections", ()) or ()),
        duplicate_current_keys=int(getattr(validation, "duplicate_current_keys", 0) or 0),
        stale_sections=tuple(getattr(validation, "stale_sections", ()) or ()),
        data_gap_sections=tuple(getattr(validation, "data_gap_sections", ()) or ()),
        missing_metric_sections=tuple(getattr(validation, "missing_metric_sections", ()) or ()),
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
    persist_decision_setup_health(session, health)
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
  STATUS, USER_MESSAGE, SELECTED_PROCEDURE, FALLBACK_USED, CURRENT_PACKET_COUNT,
  SECTIONS_PRESENT, MISSING_SECTIONS, DUPLICATE_CURRENT_KEYS, STALE_SECTIONS,
  DATA_GAP_SECTIONS, MISSING_METRIC_SECTIONS, MAX_PACKET_BYTES, REQUESTED_SCOPE,
  RESOLVED_SCOPE, ADMIN_DETAIL, SUGGESTED_REMEDIATION, ACTOR_ROLE, APP_VERSION,
  TO_VARCHAR(EVENT_TS) AS RECORDED_AT
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
            health = _health_from_mapping(normalized)
            st.session_state[SETUP_HEALTH_KEY] = asdict(health)
            return health
    return None


def _list_text(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "None"


def open_decision_setup_health() -> None:
    """Open Settings and expand the Decision setup health panel."""
    st.session_state[SIDEBAR_PANEL] = "settings"
    st.session_state[SETUP_HEALTH_PANEL_OPEN_KEY] = True


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
                <strong>{_escape_html(health.status.upper())}</strong>
                <span>{_escape_html(health.user_message)}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write(f"Recorded: {health.recorded_at}")
        st.write(f"Selected procedure: {health.selected_procedure or 'Unavailable'}")
        st.write(f"Fallback procedure used: {'Yes' if health.fallback_used else 'No'}")
        st.write(f"Current packet count: {health.current_packet_count}")
        st.write(f"Sections present: {_list_text(health.sections_present)}")
        st.write(f"Missing sections: {_list_text(health.missing_sections)}")
        st.write(f"Duplicate current keys: {health.duplicate_current_keys}")
        st.write(f"Stale sections: {_list_text(health.stale_sections)}")
        st.write(f"Data Gap sections: {_list_text(health.data_gap_sections)}")
        st.write(f"Missing metric sections: {_list_text(health.missing_metric_sections)}")
        st.write(f"Max packet bytes: {health.max_packet_bytes if health.max_packet_bytes is not None else 'Unavailable'}")
        if health.requested_scope:
            st.write(f"Requested scope: {health.requested_scope}")
        if health.resolved_scope:
            st.write(f"Resolved scope: {health.resolved_scope}")
        if health.admin_detail:
            st.code(health.admin_detail)
            st.code(
                "\n".join(
                    part for part in (
                        f"Status: {health.status}",
                        f"Procedure: {health.selected_procedure or 'Unavailable'}",
                        f"Requested: {health.requested_scope or 'Unavailable'}",
                        f"Resolved: {health.resolved_scope or 'Unavailable'}",
                        f"Missing sections: {_list_text(health.missing_sections)}",
                        f"Data gaps: {_list_text(health.data_gap_sections)}",
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
    "open_decision_setup_health",
    "persist_decision_setup_health",
    "record_decision_bootstrap_health",
    "render_decision_setup_health_panel",
]
