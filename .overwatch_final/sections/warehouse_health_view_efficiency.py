# sections/warehouse_health_view_efficiency.py - Warehouse Health efficiency workflow renderer.
from __future__ import annotations

import streamlit as st

from sections.base import lazy_util as _lazy_util
from sections.shell_helpers import render_shell_snapshot
from sections.warehouse_health_dataframes import _warehouse_meta_matches, _warehouse_scope_meta
from sections.warehouse_health_loader import _warehouse_action_session
from sections.warehouse_health_queue import _queue_efficiency_findings
from utils.section_guidance import defer_source_note


day_window_selectbox = _lazy_util("day_window_selectbox")
download_csv = _lazy_util("download_csv")
format_credits = _lazy_util("format_credits")
format_snowflake_error = _lazy_util("format_snowflake_error")
freshness_note = _lazy_util("freshness_note")
load_shared_warehouse_efficiency = _lazy_util("load_shared_warehouse_efficiency")
metric_confidence_label = _lazy_util("metric_confidence_label")
render_drillable_bar_chart = _lazy_util("render_drillable_bar_chart")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _render_warehouse_efficiency_view(company: str, environment: str) -> None:
    st.subheader("Warehouse Efficiency Risks")
    eff_days = day_window_selectbox("Lookback", key="wh_eff_days", default=7)
    if st.button("Load Efficiency Metrics", key="wh_eff_load"):
        try:
            session = _warehouse_action_session("load warehouse efficiency metrics")
            if session is None:
                return
            result = load_shared_warehouse_efficiency(
                session,
                eff_days,
                company,
                force=True,
                section="Warehouse Health",
            )
            st.session_state["wh_efficiency"] = result.data
            st.session_state["wh_efficiency_meta"] = _warehouse_scope_meta(company, environment, eff_days)
            st.session_state["wh_efficiency_source"] = result.source
        except Exception as e:
            st.warning(f"Efficiency metrics unavailable in this role/context: {format_snowflake_error(e)}")

    df_eff = st.session_state.get("wh_efficiency")
    if (
        df_eff is not None
        and not _warehouse_meta_matches(
            st.session_state.get("wh_efficiency_meta"),
            _warehouse_scope_meta(company, environment, eff_days),
        )
    ):
        st.info("Loaded efficiency metrics are stale for the active scope. Reload Efficiency Metrics before acting.")
    elif df_eff is not None and not df_eff.empty:
        low = df_eff[df_eff["EFFICIENCY_SCORE"] < 70]
        render_shell_snapshot((
            ("Warehouses Reviewed", len(df_eff)),
            ("Needs Review", len(low)),
            ("Total metered credits", format_credits(float(df_eff["METERED_CREDITS"].sum()))),
        ))
        defer_source_note(
            metric_confidence_label("allocated"),
            st.session_state.get("wh_efficiency_source", freshness_note("ACCOUNT_USAGE")),
        )
        df_eff_display = df_eff.rename(columns={"EFFICIENCY_SCORE": "REVIEW_PRIORITY"})
        render_priority_dataframe(
            df_eff_display,
            title="Warehouse efficiency risks",
            priority_columns=[
                "WAREHOUSE_NAME",
                "WAREHOUSE_SIZE",
                "REVIEW_PRIORITY",
                "METERED_CREDITS",
                "CREDITS_PER_QUERY",
                "QUEUE_SEC_PER_CREDIT",
                "REMOTE_SPILL_GB_PER_CREDIT",
                "AVG_CACHE_PCT",
            ],
            sort_by=["REVIEW_PRIORITY", "METERED_CREDITS"],
            ascending=[True, False],
            raw_label="All warehouse efficiency rows",
        )
        render_drillable_bar_chart(
            df_eff_display,
            dimension="WAREHOUSE_NAME",
            measure="REVIEW_PRIORITY",
            key="wh_efficiency_review_priority",
            drilldown_column="warehouse_name",
            lookback_hours=eff_days * 24,
        )
        download_csv(df_eff, "warehouse_efficiency.csv")
        if st.button("Save low-efficiency warehouses to Action Queue", key="wh_eff_queue"):
            session = _warehouse_action_session("save warehouse efficiency findings to the action queue")
            if session is not None:
                _queue_efficiency_findings(session, df_eff)
