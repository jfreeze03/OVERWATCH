"""Admin-only setup health for Decision Workspace summaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape as _escape_html
from typing import Mapping

import streamlit as st


SETUP_HEALTH_KEY = "_overwatch_decision_setup_health"


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
    admin_detail: str = ""
    suggested_remediation: str = ""
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
        admin_detail=str(raw.get("admin_detail", "")),
        suggested_remediation=str(raw.get("suggested_remediation", "")),
        recorded_at=str(raw.get("recorded_at", "")),
    )


def record_decision_bootstrap_health(
    *,
    status: str,
    user_message: str,
    selected_procedure: str = "",
    fallback_used: bool = False,
    validation: object | None = None,
    admin_detail: str = "",
    suggested_remediation: str = "",
) -> DecisionBootstrapHealth:
    """Store the latest setup health details for Settings/Admin surfaces."""
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
        admin_detail=str(admin_detail or getattr(validation, "admin_detail", "") or ""),
        suggested_remediation=str(
            suggested_remediation
            or "Deploy the latest OVERWATCH mart setup, then run CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();"
        ),
    )
    st.session_state[SETUP_HEALTH_KEY] = asdict(health)
    return health


def load_decision_setup_health(session: object | None = None) -> DecisionBootstrapHealth | None:
    """Return the latest locally recorded setup health snapshot."""
    raw = st.session_state.get(SETUP_HEALTH_KEY)
    if isinstance(raw, DecisionBootstrapHealth):
        return raw
    if isinstance(raw, Mapping):
        return _health_from_mapping(raw)
    return None


def _list_text(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "None"


def render_decision_setup_health_panel() -> None:
    """Render admin diagnostics without leaking them into daily Decision Workspace UI."""
    health = load_decision_setup_health()
    if health is None:
        return
    with st.expander("Decision Summary Setup Health", expanded=False):
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
        if health.admin_detail:
            st.code(health.admin_detail)
        st.info(health.suggested_remediation)


__all__ = [
    "DecisionBootstrapHealth",
    "SETUP_HEALTH_KEY",
    "load_decision_setup_health",
    "record_decision_bootstrap_health",
    "render_decision_setup_health_panel",
]
