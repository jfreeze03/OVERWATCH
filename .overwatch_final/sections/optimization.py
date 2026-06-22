"""Simplified cost and warehouse optimization workspace."""

from __future__ import annotations

import streamlit as st

from utils.operator_model import load_operator_snapshot, money, short_number


def _metric(label: str, value: str, help_text: str = "") -> None:
    st.metric(label, value, help=help_text or None)


def render() -> None:
    """Render cost, warehouse, storage, Cortex, and recommendation actions."""
    snapshot = load_operator_snapshot()
    summary = snapshot.board.summary

    st.markdown("### OPTIMIZATION")
    st.caption("What is getting expensive, who owns it, and what should we do next.")

    cols = st.columns(4)
    with cols[0]:
        _metric("Current Spend", money(summary.get("current_cost_usd")), "Selected-window spend from compact cost summaries.")
    with cols[1]:
        _metric("Spend Movement", money(summary.get("spend_delta_cost_usd")), "Positive movement should be reviewed before changing controls.")
    with cols[2]:
        _metric("Cortex Spend", money(summary.get("cortex_cost_usd")), "Cortex is retained as a cost-risk signal.")
    with cols[3]:
        _metric("Storage Cost", money(summary.get("storage_cost_usd")), "Storage growth belongs in optimization, not a separate dashboard.")

    cols2 = st.columns(4)
    with cols2[0]:
        _metric("Credits", short_number(summary.get("current_credits")), "Warehouse credits in the selected summary window.")
    with cols2[1]:
        _metric("Queued Queries", short_number(summary.get("queued_queries")), "Capacity pressure requiring review.")
    with cols2[2]:
        _metric("Remote Spill", short_number(summary.get("remote_spill_gb"), "GB"), "SQL/warehouse tuning signal.")
    with cols2[3]:
        _metric("Top Driver", str(summary.get("top_cost_driver") or "No driver"), "Highest visible cost driver in the summary.")

    st.markdown("#### Top Recommendations")
    st.dataframe(snapshot.recommendations, hide_index=True, width="stretch", height=260)

    with st.expander("View Details / Advanced", expanded=False):
        st.write(
            "Detailed warehouse health, storage, Cortex, and cost-attribution tools are intentionally "
            "kept behind this advanced area so the normal workflow stays focused on recommendations."
        )
        st.info("Use Settings to open legacy diagnostics when a DBA needs deep evidence.")

