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


def render() -> None:
    st.header("Cost & Contract")
    st.caption(
        "One operating workflow for bill explanation, cost attribution, contract pacing, "
        "optimization actions, AI/Cortex usage, and Snowpark Container Services spend."
    )

    workflow = st.radio(
        "Cost workflow",
        [
            "Explain bill / attribution / contract",
            "Recommendations and action queue",
            "Snowflake value log",
            "AI and Cortex spend",
            "SPCS spend",
        ],
        horizontal=True,
        label_visibility="collapsed",
        key="cost_contract_workflow",
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
