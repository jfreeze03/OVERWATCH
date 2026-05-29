# sections/query_workbench.py - Consolidated query investigation workflow
from __future__ import annotations

import streamlit as st

from sections import detailed_diagnosis, live_monitor, query_analysis, query_search
from utils.workflows import render_signal_confidence, render_workflow_guide, render_workflow_selector

WORKFLOWS = (
    "Live Triage",
    "Diagnosis",
    "Patterns",
    "History Search",
)


def render() -> None:
    if st.session_state.get("exceptions_only_mode") and "query_workbench_workflow" not in st.session_state:
        st.session_state["query_workbench_workflow"] = "Diagnosis"
    st.header("Query Workbench")
    st.caption(
        "One place for live query triage, slow-query diagnosis, pattern analysis, "
        "and historical query search. Use this before jumping into cost, warehouse, "
        "or security follow-up."
    )
    render_signal_confidence(
        source="INFORMATION_SCHEMA",
        confidence="exact",
        scope_note="Current activity is live; history is ACCOUNT_USAGE-backed.",
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: start with Diagnosis unless you need currently running queries.")

    render_workflow_guide(
        "Confirm whether the query is still running, diagnose the bottleneck, "
        "compare recurring patterns, then pull exact query text/history for evidence.",
        [
            ("Something is running now", "Use Live Triage."),
            ("Something was slow, queued, blocked, or spilling", "Use Diagnosis."),
            ("A user, role, warehouse, or query type keeps recurring", "Use Patterns."),
            ("You have a query ID or need exact SQL text", "Use History Search."),
        ],
    )

    workflow = render_workflow_selector(
        "Query workflow",
        "query_workbench_workflow",
        WORKFLOWS,
    )

    if workflow == "Live Triage":
        live_monitor.render()
    elif workflow == "Diagnosis":
        detailed_diagnosis.render()
    elif workflow == "Patterns":
        query_analysis.render()
    else:
        query_search.render()
