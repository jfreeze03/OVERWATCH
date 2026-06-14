"""Shared Snowflake-native readiness boards for first-paint shells."""

from __future__ import annotations

import streamlit as st

from sections.shell_helpers import render_setup_health_board, render_signal_lane_board
from utils.native_snowflake import (
    build_alert_object_registry_sql,
    build_data_quality_dmf_sql,
    build_tag_allocation_sql,
    native_capability_lanes,
    native_capability_setup_objects,
)


def render_native_readiness_board(
    *,
    title: str = "Native Snowflake Readiness",
    max_lanes: int = 6,
) -> None:
    """Render the cross-section native Snowflake control contract."""
    st.markdown(f"**{title}**")
    render_signal_lane_board("Native Control Coverage", native_capability_lanes(), max_lanes=max_lanes)
    render_setup_health_board(
        "Native Proof Objects",
        native_capability_setup_objects()[:4],
        cadence="Scheduled proof refresh plus explicit setup validation",
        fallback="Friendly unavailable-source messages",
        owner="DBA / Security / FinOps",
    )


def render_governance_native_proof_board() -> None:
    """Render native security/governance proof expected by production review."""
    st.markdown("**Native Governance Proof**")
    render_signal_lane_board(
        "Governance Native Sources",
        (
            {
                "label": "Privileged grants",
                "value": "GRANTS views",
                "state": "Access",
                "detail": "ACCOUNTADMIN, SECURITYADMIN, SYSADMIN, ORGADMIN, ownership, future grants, and public grants.",
            },
            {
                "label": "Sensitive access",
                "value": "ACCESS_HISTORY",
                "state": "Security",
                "detail": "Sensitive object access spikes, unloads, shares, and unusual role/user patterns.",
            },
            {
                "label": "Tag ownership",
                "value": "TAG_REFERENCES",
                "state": "Owner",
                "detail": "Owner, cost center, and criticality tags should replace hidden naming-only routing.",
            },
            {
                "label": "Data quality / DMF",
                "value": "DATA_METRIC_FUNCTIONS",
                "state": "Optional",
                "detail": "Use Snowflake DMFs when enabled; otherwise show metadata-driven checks and privilege gaps.",
            },
        ),
        max_lanes=4,
    )
    render_setup_health_board(
        "Governance SQL Contracts",
        (
            ("Tag allocation", "SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES"),
            ("DMF registry", "DATA_METRIC_FUNCTION_REFERENCES"),
            ("Alert registry", "SHOW ALERTS / ALERT_HISTORY"),
            ("Compliance", "OVERWATCH_COMPLIANCE_READINESS_V"),
        ),
        cadence="60 min governance refresh",
        fallback="Explicit governance lane",
        owner="Security / DBA",
    )


def render_workload_data_quality_board() -> None:
    """Render data-quality and reconciliation proof without starting a scan."""
    st.markdown("**Data Quality & Compare Proof**")
    render_signal_lane_board(
        "Reconciliation Command Model",
        (
            {
                "label": "DMF registry",
                "value": "DATA_METRIC_FUNCTION_REFERENCES",
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
                "value": "Mismatch SQL",
                "state": "Proof",
                "detail": "Generate keyed or set-style diff SQL only for mismatched buckets/tables.",
            },
        ),
        max_lanes=4,
    )
    render_setup_health_board(
        "Data Quality SQL Contracts",
        (
            ("DMF query", build_data_quality_dmf_sql().splitlines()[0]),
            ("Recon config", "OVERWATCH_RECON_CONFIG"),
            ("Recon runs", "OVERWATCH_RECON_RUN"),
            ("Schema DDL", "OVERWATCH_SCHEMA_DIFF_RESULT"),
        ),
        cadence="Explicit compare or scheduled DQ sweep",
        fallback="Metadata-only compare when DMFs are unavailable",
        owner="DBA / Data Owner",
    )


def render_alert_native_registry_board() -> None:
    """Render native Snowflake ALERT object proof for Alert Center."""
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
                "label": "Run proof",
                "value": "ALERT_HISTORY",
                "state": "Evidence",
                "detail": "Recent alert executions, failures, and error messages prove the schedule is alive.",
            },
            {
                "label": "Template",
                "value": "OVERWATCH_NATIVE_ALERT_TEMPLATES.sql",
                "state": "Deploy",
                "detail": "Notification-only examples should stay approval-gated until routing is approved.",
            },
            {
                "label": "SQL contract",
                "value": "Registry ready",
                "state": "Review",
                "detail": build_alert_object_registry_sql().splitlines()[0],
            },
        ),
        max_lanes=4,
    )


def render_tag_allocation_hint() -> None:
    """Render a small tag SQL hint where a full board would be too much."""
    st.caption(f"Tag allocation SQL: {build_tag_allocation_sql().splitlines()[0]}")
