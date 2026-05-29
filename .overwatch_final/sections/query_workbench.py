# sections/query_workbench.py - Consolidated query investigation workflow
from __future__ import annotations

import streamlit as st

from sections import detailed_diagnosis, live_monitor, query_analysis, query_search


def render() -> None:
    st.header("Query Workbench")
    st.caption(
        "One place for live query triage, slow-query diagnosis, pattern analysis, "
        "and historical query search. Use this before jumping into cost, warehouse, "
        "or security follow-up."
    )

    tab_live, tab_diagnosis, tab_patterns, tab_history = st.tabs(
        [
            "Live Triage",
            "Diagnosis",
            "Patterns",
            "History Search",
        ]
    )

    with tab_live:
        live_monitor.render()

    with tab_diagnosis:
        detailed_diagnosis.render()

    with tab_patterns:
        query_analysis.render()

    with tab_history:
        query_search.render()
