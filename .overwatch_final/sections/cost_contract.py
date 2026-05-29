# sections/cost_contract.py - Consolidated cost and contract workflow
from __future__ import annotations

import streamlit as st

from sections import (
    cortex_monitor,
    cost_center,
    recommendations,
    snowflake_value,
    spcs_tracker,
)
from utils.workflows import render_signal_confidence, render_workflow_guide, render_workflow_selector

WORKFLOWS = (
    "Explain bill / attribution / contract",
    "Recommendations and action queue",
    "Snowflake value log",
    "AI and Cortex spend",
    "SPCS spend",
)


def render() -> None:
    if st.session_state.get("exceptions_only_mode") and "cost_contract_workflow" not in st.session_state:
        st.session_state["cost_contract_workflow"] = "Explain bill / attribution / contract"
    st.header("Cost & Contract")
    st.caption(
        "One operating workflow for bill explanation, cost attribution, contract pacing, "
        "optimization actions, AI/Cortex usage, and Snowpark Container Services spend."
    )
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="allocated",
        scope_note="Warehouse totals are exact; user/query chargeback is allocated unless noted.",
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: prioritize bill deltas, open action queue items, and contract risk.")
    render_workflow_guide(
        "Explain the bill first, convert findings into owned actions, log validated savings, "
        "then inspect special-cost surfaces like Cortex and SPCS.",
        [
            ("Why did the bill move?", "Use Explain bill / attribution / contract."),
            ("What should we fix first?", "Use Recommendations and action queue."),
            ("How do we prove savings?", "Use Snowflake value log."),
            ("Are AI costs controlled?", "Use AI and Cortex spend."),
            ("Are container services costing us?", "Use SPCS spend."),
        ],
    )

    workflow = render_workflow_selector(
        "Cost workflow",
        "cost_contract_workflow",
        WORKFLOWS,
    )

    if workflow == "Explain bill / attribution / contract":
        cost_center.render()
    elif workflow == "Recommendations and action queue":
        recommendations.render()
    elif workflow == "Snowflake value log":
        snowflake_value.render()
    elif workflow == "AI and Cortex spend":
        cortex_monitor.render()
    else:
        spcs_tracker.render()
