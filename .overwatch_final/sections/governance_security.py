"""Combined Governance & Security command surface.

This is the production-facing consolidation point for access security,
review, object/change drift, schema compare, and guarded DBA action workflows.
Legacy route keys still set ``governance_security_view`` before landing here.
"""
from __future__ import annotations

import importlib

import streamlit as st


VIEWS = ("Security Posture", "Change & Drift")
VIEW_LABELS = {
    "Security Posture": "Access & Security",
    "Change & Drift": "Change Control",
}
VIEW_HELP = {
    "Security Posture": "Login risk, privileged grants, role sprawl, data sharing, and access-review evidence.",
    "Change & Drift": "DDL, schema/object drift, procedure lineage, data movement, and guarded admin action evidence.",
}


def _active_view() -> str:
    requested = str(st.session_state.get("governance_security_view") or VIEWS[0])
    return requested if requested in VIEWS else VIEWS[0]


def _prime_legacy_workspace(view: str) -> None:
    if view == "Change & Drift":
        st.session_state["_change_drift_full_workspace_requested"] = True
        st.session_state["_change_drift_brief_mode"] = False
        return
    st.session_state["_security_posture_full_workspace_requested"] = True
    st.session_state["_security_posture_brief_mode"] = False


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


def render() -> None:
    view = _render_view_selector()
    _prime_legacy_workspace(view)

    module_name = "sections.change_drift" if view == "Change & Drift" else "sections.security_posture"
    module = importlib.import_module(module_name)
    module.render()
