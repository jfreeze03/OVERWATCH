# sections/change_drift.py - Consolidated change, drift, and lineage workflow
from __future__ import annotations

import streamlit as st

from sections import dba_tools, object_change_monitor, stored_proc_tracker


def render() -> None:
    st.header("Change & Drift")
    st.caption(
        "One workflow for who-changed-what investigations, stored procedure lineage, "
        "schema/object drift, dynamic tables, replication, and controlled DBA maintenance."
    )

    workflow = st.radio(
        "Change workflow",
        [
            "Object and access changes",
            "Stored procedure lineage",
            "DBA toolkit and drift checks",
        ],
        horizontal=True,
        label_visibility="collapsed",
        key="change_drift_workflow",
    )

    if workflow == "Object and access changes":
        object_change_monitor.render()
    elif workflow == "Stored procedure lineage":
        stored_proc_tracker.render()
    else:
        dba_tools.render()
