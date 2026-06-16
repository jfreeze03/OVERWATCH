"""Shared Snowflake-native monitoring boards for first-paint shells."""

from __future__ import annotations

import streamlit as st

from sections.shell_helpers import render_signal_lane_board


def render_workload_data_quality_board() -> None:
    """Render data-quality and reconciliation telemetry without starting a scan."""
    st.markdown("**Data Quality & Compare**")
    render_signal_lane_board(
        "Reconciliation Command Model",
        (
            {
                "label": "DMF registry",
                "value": "DMF health",
                "state": "Native",
                "detail": "DMF schedules, states, last runs, and failures become data-quality signals when enabled.",
            },
            {
                "label": "Row-count pass",
                "value": "Counts first",
                "state": "Cheap",
                "detail": "Compare matching tables by metadata and row counts before hashing large data.",
            },
            {
                "label": "Hash pass",
                "value": "HASH_AGG",
                "state": "Targeted",
                "detail": "Use explicit columns and bucket isolation so one bad table does not trigger a full-schema scan.",
            },
            {
                "label": "Forensic diff",
                "value": "Mismatch review",
                "state": "Telemetry",
                "detail": "Generate keyed or set-style diff review only for mismatched buckets/tables.",
            },
        ),
        max_lanes=4,
    )


def render_alert_native_registry_board() -> None:
    """Render native Snowflake ALERT object telemetry for Alert Center."""
    render_signal_lane_board(
        "Native Alert Registry",
        (
            {
                "label": "Inventory",
                "value": "SHOW ALERTS IN ACCOUNT",
                "state": "Native",
                "detail": "Tracks Snowflake ALERT objects, schedule, warehouse, and current state.",
            },
            {
                "label": "Run telemetry",
                "value": "ALERT_HISTORY",
                "state": "Telemetry",
                "detail": "Recent alert executions, failures, and error messages show whether the schedule is alive.",
            },
            {
                "label": "Template",
                "value": "Review gated",
                "state": "Review",
                "detail": "Notification examples stay gated until routing is reviewed.",
            },
            {
                "label": "Registry",
                "value": "Registry ready",
                "state": "Review",
                "detail": "Inventory checks stay read-only and route failures to Alert Center.",
            },
        ),
        max_lanes=4,
    )


def render_tag_allocation_hint() -> None:
    """Render a small tag allocation hint where a full board would be too much."""
    st.caption("Tag allocation uses Snowflake account metadata when enabled.")
