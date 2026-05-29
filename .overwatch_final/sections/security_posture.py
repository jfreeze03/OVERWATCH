# sections/security_posture.py - Consolidated security and access workflow
from __future__ import annotations

import streamlit as st

from sections import data_sharing, security_access
from utils.workflows import render_signal_confidence, render_workflow_guide, render_workflow_selector

WORKFLOWS = ("Access posture", "Data sharing exposure")


def render() -> None:
    if st.session_state.get("exceptions_only_mode") and "security_posture_workflow" not in st.session_state:
        st.session_state["security_posture_workflow"] = "Access posture"
    st.header("Security Posture")
    st.caption(
        "One DBA workflow for login posture, MFA, grants, exfiltration signals, "
        "data lineage, and shared-data exposure."
    )
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="exact",
        scope_note="Company scope uses user/database naming where Snowflake does not expose company ownership.",
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: prioritize failed logins, MFA gaps, risky grants, and external exposure.")
    render_workflow_guide(
        "Start with identity/access posture, then inspect data sharing when the question "
        "is exposure, external access, or audit evidence.",
        [
            ("Login failures, MFA, grants, or risky access", "Use Access posture."),
            ("External consumers or shared data exposure", "Use Data sharing exposure."),
        ],
    )

    workflow = render_workflow_selector(
        "Security workflow",
        "security_posture_workflow",
        WORKFLOWS,
    )

    if workflow == "Access posture":
        security_access.render()
    else:
        data_sharing.render()
