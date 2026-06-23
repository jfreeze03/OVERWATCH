# sections/warehouse_health_overview_panels.py - Warehouse Health brief/launchpad panels.
from __future__ import annotations

import streamlit as st

from sections.shell_helpers import (
    render_escaped_bold_text,
    render_shell_kpi_row,
    render_shell_status_strip,
)
from sections.warehouse_health_contracts import (
    WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION,
    WAREHOUSE_HEALTH_BRIEF_WORKFLOWS,
    WAREHOUSE_HEALTH_DETAILS,
    WAREHOUSE_HEALTH_VIEWS,
)
from sections.warehouse_health_dataframes import (
    _warehouse_column_average,
    _warehouse_column_sum,
    _warehouse_frame_has_rows,
    _warehouse_frame_len,
    _warehouse_looks_like_frame,
    _warehouse_meta_matches,
    _warehouse_scope_meta,
    _warehouse_value_count,
)
from utils.primitives import safe_float, safe_int


def _warehouse_action_brief(company: str, environment: str, days: int) -> dict:
    overview = st.session_state.get("wh_df_wh")
    overview_meta = st.session_state.get("wh_df_wh_meta")
    overview_expected = _warehouse_scope_meta(company, environment, days)
    overview_loaded = _warehouse_looks_like_frame(overview)
    overview_current = overview_loaded and _warehouse_meta_matches(overview_meta, overview_expected)

    capacity_days = safe_int(st.session_state.get("wh_capacity_days", 7), 7) or 7
    capacity_meta = st.session_state.get("wh_capacity_meta")
    capacity_expected = _warehouse_scope_meta(company, environment, capacity_days)
    capacity_current = _warehouse_meta_matches(capacity_meta, capacity_expected)
    summary = st.session_state.get("wh_capacity_summary")
    exceptions = st.session_state.get("wh_capacity_exceptions")
    high_risk = _warehouse_value_count(exceptions, "SEVERITY", {"Critical", "High"}) if capacity_current else 0

    if overview_loaded and not overview_current:
        return {
            "state": "Stale",
            "headline": "Reload Warehouse Data before acting.",
            "detail": "Loaded warehouse telemetry does not match the active company, environment, lookback, or triage filters.",
        }
    if high_risk:
        queued = 0
        spill = 0
        if _warehouse_frame_has_rows(summary):
            row = summary.iloc[0]
            queued = safe_int(row.get("QUEUED_QUERIES", 0))
            spill = safe_int(row.get("SPILL_QUERIES", 0))
        return {
            "state": "Capacity Review",
            "headline": "Review high-risk warehouse pressure first.",
            "detail": (
                f"{high_risk:,} Critical/High exception(s); confirm "
                f"{queued:,} queued and {spill:,} spill signal(s) before settings changes."
            ),
        }
    if overview_current and _warehouse_frame_has_rows(overview):
        warehouses = _warehouse_frame_len(overview)
        total_queries = int(_warehouse_column_sum(overview, "TOTAL_QUERIES"))
        remote_spill = _warehouse_column_sum(overview, "TOTAL_REMOTE_SPILL_GB")
        return {
            "state": "Loaded",
            "headline": "Use the loaded overview before changing warehouse settings.",
            "detail": (
                f"{warehouses:,} warehouse(s), {total_queries:,} queries, "
                f"and {remote_spill:,.1f} GB remote spill in the selected window."
            ),
        }
    if overview_current and overview_loaded:
        return {
            "state": "No Rows",
            "headline": "No warehouse activity found for this scope.",
            "detail": "Confirm filters before opening specialist warehouse workflows.",
        }
    if st.session_state.get("wh_settings_inventory_error"):
        return {
            "state": "Metadata Gap",
            "headline": "Warehouse metadata needs access before guardrails are complete.",
            "detail": "Load overview telemetry when Snowflake grants are ready; specialist workflows stay gated.",
        }
    return {
        "state": "Ready",
        "headline": "Load Warehouse Data before changing size, clusters, or suspend policy.",
        "detail": "The overview stays quiet until the selected DBA scope is requested.",
    }


def _render_warehouse_action_brief(brief: dict) -> None:
    render_shell_status_strip(
        state=brief.get("state") or "Review",
        headline=brief.get("headline") or "Review warehouse telemetry.",
        detail=brief.get("detail") or "",
    )


def _warehouse_operating_snapshot(company: str, environment: str, days: int) -> dict:
    overview = st.session_state.get("wh_df_wh")
    expected_meta = _warehouse_scope_meta(company, environment, days)
    if not _warehouse_looks_like_frame(overview) or not _warehouse_meta_matches(
        st.session_state.get("wh_df_wh_meta"),
        expected_meta,
    ):
        return {
            "loaded": False,
            "scope": str(company or "All"),
            "window": f"{safe_int(days, 14):d}d",
            "evidence": "Load overview",
            "focus": "Pressure",
        }
    return {
        "loaded": True,
        "warehouses": _warehouse_frame_len(overview),
        "queries": safe_int(_warehouse_column_sum(overview, "TOTAL_QUERIES")),
        "spill_gb": _warehouse_column_sum(overview, "TOTAL_REMOTE_SPILL_GB"),
        "avg_queue": _warehouse_column_average(overview, "AVG_QUEUED_SEC"),
    }


def _render_warehouse_operating_snapshot(snapshot: dict) -> None:
    loaded = bool(snapshot.get("loaded"))
    if not loaded:
        render_shell_kpi_row((
            ("Scope", str(snapshot.get("scope") or "All")),
            ("Window", str(snapshot.get("window") or "14d")),
            ("Telemetry", str(snapshot.get("evidence") or "Load overview")),
        ))
        return
    render_shell_kpi_row((
        ("Warehouses", f"{safe_int(snapshot.get('warehouses')):,}"),
        ("Queries", f"{safe_int(snapshot.get('queries')):,}"),
        ("Spill GB", f"{safe_float(snapshot.get('spill_gb')):,.1f}"),
        ("Avg Queue", f"{safe_float(snapshot.get('avg_queue')):,.1f}s"),
    ))


def _queue_warehouse_health_view(view: str) -> None:
    if view in WAREHOUSE_HEALTH_VIEWS:
        st.session_state["warehouse_health_requested_view"] = view
        st.rerun()


def _apply_queued_warehouse_health_view() -> None:
    requested_view = st.session_state.pop("warehouse_health_requested_view", None)
    if requested_view in WAREHOUSE_HEALTH_VIEWS:
        st.session_state["warehouse_health_view"] = requested_view


def _warehouse_support_panels_have_state() -> bool:
    return any(
        st.session_state.get(key) is not None
        for key in (
            "wh_capacity_summary",
            "wh_capacity_exceptions",
            "wh_operability_fact",
            "wh_setting_review_snapshot",
            "wh_action_closure",
        )
    )


def _apply_warehouse_brief_first_default() -> None:
    if st.session_state.get("_warehouse_health_brief_first_version") == WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION:
        return
    has_overview_rows = _warehouse_frame_has_rows(st.session_state.get("wh_df_wh"))
    if (
        not has_overview_rows
        and not _warehouse_support_panels_have_state()
        and st.session_state.get("warehouse_health_view") not in (None, "Overview & Scaling")
    ):
        st.session_state["warehouse_health_view"] = "Overview & Scaling"
    st.session_state["_warehouse_health_brief_first_version"] = WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION


def _warehouse_brief_workflow_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in WAREHOUSE_HEALTH_BRIEF_WORKFLOWS:
        view = str(item["VIEW"])
        rows.append({
            "VIEW": view,
            "BUTTON_LABEL": str(item["BUTTON_LABEL"]),
            "DBA_MOVE": str(item["DBA_MOVE"]),
            "WHEN": str(item["WHEN"]),
            "SOURCES": WAREHOUSE_HEALTH_DETAILS.get(view, "Warehouse workflow detail"),
        })
    return rows


def _render_warehouse_brief_launchpad() -> None:
    st.markdown("**Warehouse Investigation Workflows**")
    rows = _warehouse_brief_workflow_rows()
    for offset in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, row in zip(cols, rows[offset:offset + 3]):
            with col:
                render_escaped_bold_text(row["VIEW"])
                help_text = f"{row['DBA_MOVE']} When: {row['WHEN']}"
                if st.button(
                    row["BUTTON_LABEL"],
                    key=f"warehouse_brief_{row['VIEW']}",
                    help=help_text,
                    width="stretch",
                ):
                    _queue_warehouse_health_view(row["VIEW"])
