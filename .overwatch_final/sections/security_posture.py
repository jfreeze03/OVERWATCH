# sections/security_posture.py - Consolidated security and access workflow
from __future__ import annotations

import streamlit as st

from sections import data_sharing, security_access


def render() -> None:
    st.header("Security Posture")
    st.caption(
        "One DBA workflow for login posture, MFA, grants, exfiltration signals, "
        "data lineage, and shared-data exposure."
    )

    workflow = st.radio(
        "Security workflow",
        ["Access posture", "Data sharing exposure"],
        horizontal=True,
        label_visibility="collapsed",
        key="security_posture_workflow",
    )

    if workflow == "Access posture":
        security_access.render()
    else:
        data_sharing.render()
