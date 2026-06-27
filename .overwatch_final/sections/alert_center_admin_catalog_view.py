"""Alert Center Detection Catalog renderer."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st

from sections.alert_center_contracts import defer_source_note
from utils.alert_command_center import build_alert_signal_query_catalog
from utils.alert_native_catalog import (
    build_alert_native_deployment_review_rows,
    build_alert_native_object_registry_seed_rows,
    load_alert_native_object_registry,
)
from utils.explicit_load import explicit_load_dataframe
from utils.workflows import render_priority_dataframe


def render_alert_detection_catalog_tool(
    *,
    action_session_factory: Callable[[str], object | None],
    format_error: Callable[[Exception], str],
    threshold_rows_loader: Callable[[], pd.DataFrame],
    operations_rows_loader: Callable[[pd.DataFrame], pd.DataFrame],
) -> None:
    st.subheader("Detection Catalog")
    catalog = build_alert_signal_query_catalog(hours=24)
    category_options = ["All"] + sorted(catalog["CATEGORY"].dropna().astype(str).unique().tolist())
    selected_category = st.selectbox("Catalog category", category_options, key="alert_detection_catalog_category")
    visible = catalog if selected_category == "All" else catalog[catalog["CATEGORY"].astype(str) == selected_category]
    visible_display = visible.drop(columns=["SQL"], errors="ignore").rename(columns={"OWNER": "ROUTE"})
    render_priority_dataframe(
        visible_display,
        title="Snowflake-native alert signals",
        priority_columns=[
            "CATEGORY", "SIGNAL", "SEVERITY", "TELEMETRY", "FRESHNESS",
            "ROUTE", "WHY_THIS_MATTERS", "RECOMMENDED_ACTION",
        ],
        raw_label="All detection catalog rows",
        height=360,
    )
    if not visible.empty:
        signal_options = visible["SIGNAL"].dropna().astype(str).tolist()
        selected_signal = st.selectbox("Signal detail", signal_options, key="alert_detection_catalog_signal")
        selected = visible[visible["SIGNAL"].astype(str) == selected_signal].iloc[0]
        st.caption(str(selected.get("RECOMMENDED_ACTION") or "Review this alert signal with the owning DBA team."))
    c1, c2 = st.columns([1, 3])
    with c1:
        def _load_native_registry() -> pd.DataFrame:
            # SESSION_OPEN_ADMIN_OK boundary=admin reason=post_click_session budget=advanced_diagnostics owner=platform
            session = action_session_factory("load native alert registry")
            if session is None:
                return pd.DataFrame()
            return load_alert_native_object_registry(section="Alert Center")

        def _native_registry_error(exc: Exception) -> None:
            st.info(f"Native alert registry is not available in this environment yet. {format_error(exc)}")

        loaded_native = explicit_load_dataframe(
            button_label="Load Native Registry",
            button_key="alert_catalog_load_native_registry",
            state_key="alert_native_registry_live",
            loader=_load_native_registry,
            on_error=_native_registry_error,
        )
        if isinstance(loaded_native, pd.DataFrame) and not loaded_native.empty:
            st.session_state["alert_native_registry_source"] = "Live registry table"
    with c2:
        st.caption("Native registry rows are disabled-by-default implementation candidates until reviewed and enabled in Snowflake.")

    live_native_rows = st.session_state.get("alert_native_registry_live")
    registry_source = st.session_state.get("alert_native_registry_source", "Built-in seed candidates")
    native_rows = live_native_rows if isinstance(live_native_rows, pd.DataFrame) and not live_native_rows.empty else pd.DataFrame(build_alert_native_object_registry_seed_rows())
    if not native_rows.empty:
        native_rows = native_rows.copy()
        if "REGISTRY_SOURCE" not in native_rows.columns:
            native_rows["REGISTRY_SOURCE"] = registry_source
    if not native_rows.empty:
        render_priority_dataframe(
            native_rows,
            title="Native Snowflake alert implementation candidates",
            priority_columns=[
                "REGISTRY_SOURCE", "STATUS", "CATEGORY", "ALERT_KEY", "ALERT_OBJECT_NAME",
                "TARGET_ROUTE", "SCHEDULE_TEXT", "CONDITION_SOURCE",
                "ACTION_SOURCE", "SAFETY_NOTE",
            ],
            raw_label="All native alert registry candidates",
            height=260,
            max_rows=8,
        )
        deployment_rows = build_alert_native_deployment_review_rows(native_rows)
        render_priority_dataframe(
            deployment_rows,
            title="Native alert deployment review",
            priority_columns=[
                "DEPLOYMENT_STATE", "CATEGORY", "ALERT_KEY", "ALERT_OBJECT_NAME",
                "TARGET_ROUTE", "WAREHOUSE_NAME", "SCHEDULE_TEXT",
                "DEPLOYMENT_SQL_PRESENT", "ROLLBACK_SQL_PRESENT",
                "DEPLOYMENT_NEXT_STEP", "VALIDATION_SQL",
            ],
            raw_label="All native alert deployment review fields",
            height=280,
            max_rows=8,
        )
    threshold_rows = threshold_rows_loader()
    render_priority_dataframe(
        threshold_rows,
        title="Threshold tuning review plan",
        priority_columns=[
            "REVIEW_STATE", "THRESHOLD_KEY", "CATEGORY", "SIGNAL_NAME",
            "CONFIGURED_THRESHOLD", "WINDOW", "OWNER", "SOURCE_OBJECT",
            "NEXT_ACTION",
        ],
        raw_label="All threshold tuning fields",
        height=300,
        max_rows=9,
    )
    operations_rows = operations_rows_loader(native_rows)
    render_priority_dataframe(
        operations_rows,
        title="Native alert operations review checklist",
        priority_columns=["STATE", "REVIEW_AREA", "COUNT", "EVIDENCE", "NEXT_ACTION"],
        raw_label="All operations review checklist rows",
        height=240,
        max_rows=5,
    )
    defer_source_note("Run snowflake/OVERWATCH_ALERT_OPERATIONS_REVIEW.sql for live threshold, company-scope, and promotion evidence.")
    defer_source_note("Detection Catalog lists alert signals and required Snowflake telemetry.")


__all__ = ["render_alert_detection_catalog_tool"]
