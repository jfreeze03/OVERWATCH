"""Combined Governance & Security command surface.

This is the production-facing consolidation point for access security,
review, object/change drift, schema compare, and guarded DBA action workflows.
Legacy route keys still set ``governance_security_view`` before landing here.
"""
from __future__ import annotations

import importlib

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    action_state_label,
    evidence_caption,
    evidence_label,
    full_workspace_requested,
    render_refresh_contract,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
    render_shell_workflows,
    scope_label,
)


VIEWS = ("Security Posture", "Change & Drift")
VIEW_LABELS = {
    "Security Posture": "Access & Security",
    "Change & Drift": "Change Control",
}
VIEW_HELP = {
    "Security Posture": "Login risk, privileged grants, role sprawl, data sharing, and access-review evidence.",
    "Change & Drift": "DDL, schema/object drift, procedure lineage, data movement, and guarded admin action evidence.",
}
_FULL_WORKSPACE_KEY = "_governance_security_full_workspace_requested"
_BRIEF_MODE_KEY = "_governance_security_brief_mode"
_FAST_ENTRY_VERSION_KEY = "_governance_security_fast_entry_version"
_FAST_ENTRY_VERSION = 1
_FULL_WORKSPACE_STATE_KEYS = (
    "security_posture_summary",
    "security_posture_exceptions",
    "change_drift_summary",
    "change_drift_exceptions",
)
_WORKFLOWS = (
    {
        "VIEW": "Security Posture",
        "BUTTON_LABEL": "Open Security",
        "MOVE": "Load login risk, privileged grants, public access, data sharing, and access-review proof.",
    },
    {
        "VIEW": "Change & Drift",
        "BUTTON_LABEL": "Open Change Control",
        "MOVE": "Load DDL drift, schema compare, object change, procedure lineage, and rollback proof.",
    },
)


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _active_view() -> str:
    requested = str(st.session_state.get("governance_security_view") or VIEWS[0])
    return requested if requested in VIEWS else VIEWS[0]


def _full_workspace_requested() -> bool:
    """Keep Governance navigation lightweight; open detailed proof from a selected lane."""
    _ = full_workspace_requested
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    st.session_state.setdefault(_BRIEF_MODE_KEY, True)
    return False


def _apply_fast_entry_default() -> None:
    if st.session_state.get(_FAST_ENTRY_VERSION_KEY) == _FAST_ENTRY_VERSION:
        return
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FAST_ENTRY_VERSION_KEY] = _FAST_ENTRY_VERSION


def _prime_legacy_workspace(view: str) -> None:
    if view == "Change & Drift":
        st.session_state["_change_drift_full_workspace_requested"] = True
        st.session_state["_change_drift_brief_mode"] = False
        return
    st.session_state["_security_posture_full_workspace_requested"] = True
    st.session_state["_security_posture_brief_mode"] = False


def _open_workspace(view: str) -> None:
    st.session_state["governance_security_view"] = view
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    _prime_legacy_workspace(view)
    st.rerun()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.session_state["_security_posture_full_workspace_requested"] = False
    st.session_state["_change_drift_full_workspace_requested"] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="governance_security_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_view_selector() -> str:
    current = _active_view()
    st.session_state["governance_security_view"] = current
    selected = st.radio(
        "Governance lane",
        VIEWS,
        index=VIEWS.index(current),
        horizontal=True,
        key="governance_security_view",
        format_func=lambda value: VIEW_LABELS.get(str(value), str(value)),
        help="Switch between access/security evidence and change/schema evidence without leaving the consolidated governance surface.",
    )
    st.caption(VIEW_HELP.get(str(selected), "Governance evidence."))
    return str(selected)


def _delegate_full_workspace() -> None:
    view = _render_view_selector()
    _prime_legacy_workspace(view)

    module_name = "sections.change_drift" if view == "Change & Drift" else "sections.security_posture"
    module = importlib.import_module(module_name)
    module.render()


def _render_status_strip() -> None:
    detail = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "Security and change proof are loaded only after choosing a governance lane.",
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="Governance command view: access risk, role posture, schema drift, and controlled change proof.",
        detail=detail,
    )


def _render_kpi_row() -> None:
    render_shell_kpi_row((
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Access", "On demand"),
        ("Change", "On demand"),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
    ))


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


def _render_metric_board() -> None:
    security_meta = st.session_state.get("security_posture_meta")
    change_meta = st.session_state.get("change_drift_meta")
    freshness_meta = security_meta if isinstance(security_meta, dict) and security_meta else change_meta
    st.markdown("**Governance Metric Board**")
    render_refresh_contract(
        freshness_meta if isinstance(freshness_meta, dict) else {},
        source="SECURITY_POSTURE / CHANGE_DRIFT facts",
        target_minutes=60,
        refresh_method="Scheduled access and change-control refresh",
        live_fallback="Explicit governance lane",
    )
    render_shell_snapshot((
        ("Security Summary", "Loaded" if _frame_len(st.session_state.get("security_posture_summary")) else "On demand"),
        ("Security Exceptions", f"{_frame_len(st.session_state.get('security_posture_exceptions')):,}" if _frame_len(st.session_state.get("security_posture_exceptions")) else "On demand"),
        ("Change Summary", "Loaded" if _frame_len(st.session_state.get("change_drift_summary")) else "On demand"),
        ("Change Exceptions", f"{_frame_len(st.session_state.get('change_drift_exceptions')):,}" if _frame_len(st.session_state.get("change_drift_exceptions")) else "On demand"),
    ))


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["VIEW"]))

    render_shell_workflows(
        "Governance Investigation Lanes",
        _WORKFLOWS,
        label_key="VIEW",
        key_prefix="governance_security",
        on_open=_open,
    )


def render() -> None:
    _apply_fast_entry_default()
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    _render_status_strip()
    _render_kpi_row()
    _render_metric_board()
    _render_workflow_launchpad()
