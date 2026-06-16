"""Security monitoring command surface for Snowflake account telemetry."""
from __future__ import annotations

import importlib
from datetime import date

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_DAY_WINDOW, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    render_shell_snapshot,
    render_shell_workflows,
    render_signal_lane_board,
)
from utils.command_board import load_or_reuse_command_board


VIEWS = ("Security Posture",)
_FULL_WORKSPACE_KEY = "_security_monitoring_full_workspace_requested"
_BRIEF_MODE_KEY = "_security_monitoring_brief_mode"
_FAST_ENTRY_VERSION_KEY = "_security_monitoring_fast_entry_version"
_FAST_ENTRY_VERSION = 1
_COMMAND_BOARD_DATA_KEY = "security_monitoring_command_board_data"
_COMMAND_BOARD_SUMMARY_KEY = "security_monitoring_command_board_summary"
_COMMAND_BOARD_META_KEY = "security_monitoring_command_board_meta"
_COMMAND_BOARD_REFRESH_MARKER_KEY = "security_monitoring_command_board_refresh_marker"
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


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value if value is not None else default))
    except (TypeError, ValueError):
        return default


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _window_days() -> int:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return max(1, (end - start).days + 1)
    return int(DEFAULT_DAY_WINDOW)


def _command_summary() -> dict:
    summary = st.session_state.get(_COMMAND_BOARD_SUMMARY_KEY)
    if isinstance(summary, dict) and summary.get("loaded"):
        return dict(summary)
    return {}


def _load_command_board() -> None:
    load_or_reuse_command_board(
        data_key=_COMMAND_BOARD_DATA_KEY,
        summary_key=_COMMAND_BOARD_SUMMARY_KEY,
        meta_key=_COMMAND_BOARD_META_KEY,
        refresh_marker_key=_COMMAND_BOARD_REFRESH_MARKER_KEY,
        company=_active_company(),
        environment=_active_environment(),
        days=_window_days(),
    )


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
    command_summary = _command_summary()
    if command_summary and not any((security_summary, security_exceptions)):
        failed_logins = _safe_int(command_summary.get("failed_logins"))
        privileged = _safe_int(command_summary.get("privileged_grants"))
        dormant = _safe_int(command_summary.get("dormant_users"))
        active_users = _safe_int(command_summary.get("active_users"))
        open_actions = _safe_int(command_summary.get("open_actions"))
        critical_high = _safe_int(command_summary.get("critical_high_alerts"))
        return (
            {
                "label": "Login anomalies",
                "value": f"{failed_logins:,}",
                "state": "Auth",
                "detail": "Failed-login movement is visible before opening security detail.",
            },
            {
                "label": "Privileged access",
                "value": f"{privileged:,}",
                "state": "Access",
                "detail": "High-privilege grant exposure is tracked from Snowflake account metadata.",
            },
            {
                "label": "Dormant users",
                "value": f"{dormant:,}",
                "state": "Identity",
                "detail": f"{active_users:,} active user(s) are in the current monitoring scope.",
            },
            {
                "label": "Security signals",
                "value": f"{critical_high:,}",
                "state": "Risk",
                "detail": "Security pressure shares the same alert/action queue facts as the other command sections.",
            },
            {
                "label": "Action route",
                "value": f"{open_actions:,}",
                "state": "Queue",
                "detail": "Potential security work routes into monitored actions with current Snowflake telemetry.",
            },
            {
                "label": "Sensitive access",
                "value": "Tracked",
                "state": "Access",
                "detail": "Open Security Detail for access-history and sharing analysis.",
            },
            {
                "label": "Public exposure",
                "value": "Tracked",
                "state": "Risk",
                "detail": "Broad grants, external stages, integrations, and shares stay in the security lane.",
            },
            {
                "label": "Data sharing",
                "value": "Tracked",
                "state": "Sharing",
                "detail": "Provider/consumer share patterns remain visible without change-management scope.",
            },
        )
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
    command_summary = _command_summary()
    st.markdown("**Security Monitoring Command Board**")
    render_signal_lane_board("Security Monitoring Command Board", _security_lanes(), max_lanes=8)
    if command_summary and not security_summary:
        render_shell_snapshot((
            ("Failed Logins", f"{_safe_int(command_summary.get('failed_logins')):,}"),
            ("Privileged Grants", f"{_safe_int(command_summary.get('privileged_grants')):,}"),
            ("Dormant Users", f"{_safe_int(command_summary.get('dormant_users')):,}"),
            ("Open Actions", f"{_safe_int(command_summary.get('open_actions')):,}"),
        ))
    else:
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

    _load_command_board()
    _render_metric_board()
    _render_workflow_launchpad()
