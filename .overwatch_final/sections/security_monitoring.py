"""Security monitoring command surface for Snowflake account telemetry."""
from __future__ import annotations

import importlib

import streamlit as st

from sections.shell_helpers import (
    render_shell_snapshot,
    render_shell_workflows,
    render_signal_lane_board,
)


VIEWS = ("Security Posture",)
_FULL_WORKSPACE_KEY = "_security_monitoring_full_workspace_requested"
_BRIEF_MODE_KEY = "_security_monitoring_brief_mode"
_FAST_ENTRY_VERSION_KEY = "_security_monitoring_fast_entry_version"
_FAST_ENTRY_VERSION = 1
_WORKFLOWS = (
    {
        "VIEW": "Security Posture",
        "BUTTON_LABEL": "Open Security Detail",
        "MOVE": "Review login anomalies, privileged grants, public access, data sharing, and access-review telemetry.",
    },
)


def _frame_len(value: object) -> int:
    try:
        if value is None or bool(getattr(value, "empty", False)):
            return 0
    except Exception:
        if value is None:
            return 0
    try:
        return max(0, int(len(value)))
    except Exception:
        return 0


def _apply_fast_entry_default() -> None:
    if st.session_state.get(_FAST_ENTRY_VERSION_KEY) == _FAST_ENTRY_VERSION:
        return
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FAST_ENTRY_VERSION_KEY] = _FAST_ENTRY_VERSION


def _full_workspace_requested() -> bool:
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    st.session_state.setdefault(_BRIEF_MODE_KEY, True)
    return False


def _open_workspace(view: str) -> None:
    st.session_state["security_monitoring_view"] = view
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    st.session_state["_security_posture_full_workspace_requested"] = True
    st.session_state["_security_posture_brief_mode"] = False
    st.rerun()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.session_state["_security_posture_full_workspace_requested"] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Board", key="security_monitoring_back_to_board", width="stretch"):
            _return_to_brief()


def _delegate_full_workspace() -> None:
    module = importlib.import_module("sections.security_posture")
    module.render()


def _security_lanes() -> tuple[dict[str, str], ...]:
    security_summary = _frame_len(st.session_state.get("security_posture_summary"))
    security_exceptions = _frame_len(st.session_state.get("security_posture_exceptions"))
    if not any((security_summary, security_exceptions)):
        return (
            {
                "label": "Privileged access",
                "value": "On demand",
                "state": "Security",
                "detail": "ACCOUNTADMIN, SECURITYADMIN, SYSADMIN, ORGADMIN, grant-option exposure, and ownership changes.",
            },
            {
                "label": "Login anomalies",
                "value": "On demand",
                "state": "Auth",
                "detail": "Failed spikes, odd-hour logins, unusual source IPs, and dormant users suddenly active.",
            },
            {
                "label": "Sensitive access",
                "value": "On demand",
                "state": "Access",
                "detail": "ACCESS_HISTORY and query telemetry flag sensitive object access spikes.",
            },
            {
                "label": "Public grants",
                "value": "On demand",
                "state": "Risk",
                "detail": "Broad grants, shares, stages, integrations, and policy drift stay visible.",
            },
            {
                "label": "MFA posture",
                "value": "On demand",
                "state": "Identity",
                "detail": "Login and user metadata reveal users that need identity review.",
            },
            {
                "label": "Data sharing",
                "value": "On demand",
                "state": "Sharing",
                "detail": "Share exposure, provider/consumer patterns, and sensitive object access stay visible.",
            },
        )

    return (
        {
            "label": "Security summary",
            "value": f"{security_summary:,}" if security_summary else "Loaded",
            "state": "Access",
            "detail": "Login risk, privileged grants, sharing, and access-review signals.",
        },
        {
            "label": "Security exceptions",
            "value": f"{security_exceptions:,}",
            "state": "Risk",
            "detail": "Open security exceptions from the loaded Snowflake telemetry.",
        },
        {
            "label": "Public exposure",
            "value": "Loaded",
            "state": "Risk",
            "detail": "Public grants, external stages, integrations, and broad shares.",
        },
        {
            "label": "Access trend",
            "value": "Loaded",
            "state": "Trend",
            "detail": "Failed-login and privileged-access movement for the selected window.",
        },
    )


def _render_metric_board() -> None:
    security_summary = _frame_len(st.session_state.get("security_posture_summary"))
    security_exceptions = _frame_len(st.session_state.get("security_posture_exceptions"))
    st.markdown("**Security Monitoring Command Board**")
    render_signal_lane_board("Security Monitoring Command Board", _security_lanes(), max_lanes=8)
    render_shell_snapshot((
        ("Security Summary", "Loaded" if security_summary else "On demand"),
        ("Security Exceptions", f"{security_exceptions:,}" if security_exceptions else "On demand"),
        ("Privileged Access", "Tracked"),
        ("Login Risk", "Tracked"),
    ))


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["VIEW"]))

    render_shell_workflows(
        "Security Monitoring Detail",
        _WORKFLOWS,
        label_key="VIEW",
        key_prefix="security_monitoring",
        on_open=_open,
    )


def render() -> None:
    _apply_fast_entry_default()
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    _render_metric_board()
    _render_workflow_launchpad()
