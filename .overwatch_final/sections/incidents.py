"""Simplified incident queue for OVERWATCH operators."""

from __future__ import annotations

import streamlit as st

from utils.operator_model import CATEGORIES, SEVERITIES, load_operator_snapshot


def render() -> None:
    """Render one incident queue organized by operator decision fields."""
    snapshot = load_operator_snapshot()
    incidents = snapshot.incidents.copy()

    st.markdown("### INCIDENTS")
    st.caption("One queue for what is broken, what changed, who owns it, and what to do next.")

    filter_cols = st.columns([1, 1, 1, 2])
    with filter_cols[0]:
        severity = st.selectbox("Severity", ("All", *SEVERITIES), key="operator_incident_severity")
    with filter_cols[1]:
        category = st.selectbox("Category", ("All", *CATEGORIES), key="operator_incident_category")
    with filter_cols[2]:
        company = st.selectbox("Company", ("All", "ALL", "ALFA", "Trexis"), key="operator_incident_company")

    if severity != "All":
        incidents = incidents[incidents["Severity"].astype(str).eq(severity)]
    if category != "All":
        incidents = incidents[incidents["Category"].astype(str).eq(category)]
    if company != "All":
        incidents = incidents[incidents["Company"].astype(str).str.upper().eq(company.upper())]

    display_columns = [
        "Severity",
        "Category",
        "Company",
        "Owner",
        "Impact",
        "Recommended Action",
    ]
    st.dataframe(
        incidents[display_columns] if not incidents.empty else incidents,
        hide_index=True,
        width="stretch",
        height=360,
    )

    st.markdown("#### View Details")
    if incidents.empty:
        st.info("No incidents match the current filters.")
    else:
        for idx, row in incidents.head(10).reset_index(drop=True).iterrows():
            title = f"{row.get('Severity')} - {row.get('Category')} - {row.get('Owner')}"
            with st.expander(title, expanded=False):
                st.write(row.get("Details") or "No detail text was provided.")
                st.write(f"Impact: {row.get('Impact')}")
                st.write(f"Recommended action: {row.get('Recommended Action')}")
                st.caption("Advanced evidence and diagnostics remain on demand to avoid hidden Snowflake cost.")

    with st.expander("Advanced diagnostics", expanded=False):
        st.caption(
            "Use Settings for schema/data compare, validation, role readiness, alert setup, "
            "refresh diagnostics, and legacy deep-dive tools."
        )

