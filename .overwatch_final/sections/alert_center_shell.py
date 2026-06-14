"""Fast first-paint shell for the Alert Center route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import action_state_label, evidence_caption, evidence_label, evidence_loaded, full_workspace_requested, render_shell_kpi_row, render_shell_status_strip, render_shell_workflows, scope_label


_FULL_WORKSPACE_KEY = "_alert_center_full_workspace_requested"
_BRIEF_MODE_KEY = "_alert_center_brief_mode"
_FULL_WORKSPACE_STATE_KEYS = (
    "alert_center_data",
    "alert_center_annotations",
)

_WORKFLOWS = (
    {
        "VIEW": "Command Center",
        "BUTTON_LABEL": "Open Command Center",
        "MOVE": "Start with severity-ranked risk, category owners, freshness, and business impact.",
    },
    {
        "VIEW": "DBA Morning Brief",
        "BUTTON_LABEL": "Open Morning Brief",
        "MOVE": "Work overnight failures, security events, cost anomalies, and missed SLAs in order.",
    },
    {
        "VIEW": "Detection Catalog",
        "BUTTON_LABEL": "Open Detection Catalog",
        "MOVE": "Review Snowflake-native security, cost, performance, pipeline, data-quality, and optimization checks.",
    },
    {
        "VIEW": "Issue Inbox",
        "BUTTON_LABEL": "Open Issue Inbox",
        "MOVE": "Start with the combined alert and action-queue inbox for morning triage.",
    },
    {
        "VIEW": "Triage Digest",
        "BUTTON_LABEL": "Open Triage Digest",
        "MOVE": "Escalate critical, high, overdue, and owner-ready alert rows first.",
    },
    {
        "VIEW": "Email Delivery",
        "BUTTON_LABEL": "Open Delivery",
        "MOVE": "Prove which alerts are email-ready, sent, logged, or still waiting.",
    },
    {
        "VIEW": "Action Queue Routing",
        "BUTTON_LABEL": "Open Queue Routing",
        "MOVE": "Move alert evidence into accountable owner work and closure proof.",
    },
    {
        "VIEW": "Control Health",
        "BUTTON_LABEL": "Open Control Health",
        "MOVE": "Check source readiness, owner routing, alert rules, and control gaps.",
    },
    {
        "VIEW": "Automation Readiness",
        "BUTTON_LABEL": "Open Automation",
        "MOVE": "Review alert refresh, digest delivery, owner routing, and in-app action handoff readiness.",
    },
    {
        "VIEW": "Notifications & Remediation",
        "BUTTON_LABEL": "Open Remediation",
        "MOVE": "Review notification routing and approval-gated remediation contracts before action.",
    },
    {
        "VIEW": "Setup & Runbook",
        "BUTTON_LABEL": "Open Setup",
        "MOVE": "Deploy alert config, events, thresholds, owner routing, notification, and remediation audit tables.",
    },
)


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _window_label() -> str:
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        days = max(1, (end - start).days + 1)
        return f"{days}d"
    return "Selected"


def _full_workspace_requested() -> bool:
    return full_workspace_requested(st.session_state, _FULL_WORKSPACE_KEY, _BRIEF_MODE_KEY)


def _open_workspace(view: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if view:
        st.session_state["alert_center_requested_view"] = view
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import alert_center

    alert_center.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="alert_center_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_status_strip() -> None:
    detail = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "Command center, morning brief, detection catalog, routing, notifications, and remediation proof open from the workflow grid.",
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="Alert command view: open risk, owners, source freshness, and remediation control.",
        detail=detail,
    )


def _render_kpi_row() -> None:
    render_shell_kpi_row((
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
        ("Primary route", "Command Center"),
    ))


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["VIEW"]))

    render_shell_workflows(
        "Alert Command Workflows",
        _WORKFLOWS,
        label_key="VIEW",
        key_prefix="alert_center_shell",
        on_open=_open,
    )


def render() -> None:
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("alert_center_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _render_status_strip()
    _render_kpi_row()
    _render_workflow_launchpad()
