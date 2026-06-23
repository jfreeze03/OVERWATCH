# sections/warehouse_health_view_spill.py - Warehouse Health spill workflow renderer.
from __future__ import annotations

import streamlit as st

from sections.base import lazy_util as _lazy_util
from sections.shell_helpers import render_shell_snapshot
from sections.warehouse_health_dataframes import _warehouse_meta_matches, _warehouse_scope_meta
from sections.warehouse_health_loader import _warehouse_action_session
from utils.section_guidance import defer_source_note


day_window_selectbox = _lazy_util("day_window_selectbox")
download_csv = _lazy_util("download_csv")
format_snowflake_error = _lazy_util("format_snowflake_error")
load_shared_warehouse_spill = _lazy_util("load_shared_warehouse_spill")
render_drillable_bar_chart = _lazy_util("render_drillable_bar_chart")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _render_warehouse_spill_view(company: str, environment: str) -> None:
    st.subheader("Spill & Memory Pressure")
    sp_days = day_window_selectbox("Lookback", key="sp_days", default=7)

    if st.button("Load Spill Data", key="sp_load"):
        try:
            session = _warehouse_action_session("load warehouse spill data")
            if session is None:
                return
            result = load_shared_warehouse_spill(
                session,
                sp_days,
                company,
                force=True,
                section="Warehouse Health",
            )
            st.session_state["wh_df_sp"] = result.data
            st.session_state["wh_df_sp_meta"] = _warehouse_scope_meta(company, environment, sp_days)
            st.session_state["wh_df_sp_source"] = result.source
        except Exception as e:
            st.warning(f"Spill data unavailable in this role/context: {format_snowflake_error(e)}")

    if (
        st.session_state.get("wh_df_sp") is not None
        and not _warehouse_meta_matches(
            st.session_state.get("wh_df_sp_meta"),
            _warehouse_scope_meta(company, environment, sp_days),
        )
    ):
        st.info("Loaded spill data is stale for the active scope. Reload Spill Data before acting.")
    elif st.session_state.get("wh_df_sp") is not None and not st.session_state["wh_df_sp"].empty:
        df_sp = st.session_state["wh_df_sp"]
        render_shell_snapshot((
            ("Spilling Warehouses", len(df_sp)),
            ("Total Local Spill", f"{df_sp['LOCAL_SPILL_GB'].sum():.1f} GB"),
            ("Total Remote Spill", f"{df_sp['REMOTE_SPILL_GB'].sum():.1f} GB"),
        ))
        defer_source_note(st.session_state.get("wh_df_sp_source", "Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))
        render_priority_dataframe(
            df_sp,
            title="Spill and memory pressure",
            priority_columns=[
                "WAREHOUSE_NAME",
                "WAREHOUSE_SIZE",
                "SPILL_QUERY_COUNT",
                "LOCAL_SPILL_GB",
                "REMOTE_SPILL_GB",
                "AVG_ELAPSED_SEC",
            ],
            sort_by=["REMOTE_SPILL_GB", "LOCAL_SPILL_GB", "AVG_ELAPSED_SEC"],
            ascending=[False, False, False],
            raw_label="All spill rows",
        )
        df_sp["TOTAL_SPILL_GB"] = df_sp["LOCAL_SPILL_GB"] + df_sp["REMOTE_SPILL_GB"]
        render_drillable_bar_chart(
            df_sp,
            dimension="WAREHOUSE_NAME",
            measure="TOTAL_SPILL_GB",
            key="wh_spill_total",
            drilldown_column="warehouse_name",
            lookback_hours=sp_days * 24,
        )
        for _, row in df_sp.iterrows():
            if row["REMOTE_SPILL_GB"] > 10:
                st.error(f"**{row['WAREHOUSE_NAME']}**: {row['REMOTE_SPILL_GB']:.1f} GB remote spill - upsize immediately")
        download_csv(df_sp, "spill_report.csv")
