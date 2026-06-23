# sections/warehouse_health_view_heatmap.py - Warehouse Health workload heatmap renderer.
from __future__ import annotations

import streamlit as st

from sections.base import lazy_util as _lazy_util
from sections.shell_helpers import render_shell_snapshot
from sections.warehouse_health_dataframes import _warehouse_meta_matches, _warehouse_scope_meta
from utils.section_guidance import defer_source_note


day_window_selectbox = _lazy_util("day_window_selectbox")
format_snowflake_error = _lazy_util("format_snowflake_error")
load_shared_warehouse_heatmap = _lazy_util("load_shared_warehouse_heatmap")


def _render_warehouse_heatmap_view(
    company: str,
    environment: str,
    *,
    global_warehouse: str = "",
    global_user: str = "",
    global_role: str = "",
    global_database: str = "",
    global_start_date=None,
    global_end_date=None,
) -> None:
    st.subheader("Workload Concurrency Heatmap")
    hm_days = day_window_selectbox("Lookback", key="hm_days", default=30)

    if st.button("Refresh Heatmap", key="hm_build"):
        try:
            result = load_shared_warehouse_heatmap(
                hm_days,
                company,
                warehouse_contains=global_warehouse,
                user_contains=global_user,
                role_contains=global_role,
                database_contains=global_database,
                start_date=global_start_date,
                end_date=global_end_date,
                force=True,
                section="Warehouse Health",
            )
            if result.message:
                st.warning(result.message)
            st.session_state["wh_df_hm"] = result.data
            st.session_state["wh_df_hm_meta"] = _warehouse_scope_meta(company, environment, hm_days)
            st.session_state["wh_df_hm_source"] = result.source
        except Exception as e:
            st.warning(f"Workload heatmap unavailable in this role/context: {format_snowflake_error(e)}")

    if (
        st.session_state.get("wh_df_hm") is not None
        and not _warehouse_meta_matches(
            st.session_state.get("wh_df_hm_meta"),
            _warehouse_scope_meta(company, environment, hm_days),
        )
    ):
        st.info("Loaded workload heatmap is stale for the active scope. Refresh Heatmap before acting.")
    elif st.session_state.get("wh_df_hm") is not None and not st.session_state["wh_df_hm"].empty:
        df_hm = st.session_state["wh_df_hm"]
        if st.session_state.get("wh_df_hm_source"):
            defer_source_note(str(st.session_state.get("wh_df_hm_source")))
        whs = df_hm["WAREHOUSE_NAME"].unique()
        sel_wh = st.selectbox("Warehouse", whs, key="hm_wh_sel")

        if sel_wh:
            wh_data = df_hm[df_hm["WAREHOUSE_NAME"] == sel_wh]
            pivot = wh_data.pivot_table(
                index="DAY_OF_WEEK", columns="HOUR_OF_DAY",
                values="QUERY_COUNT", aggfunc="sum"
            ).fillna(0)
            day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
            pivot.index = pivot.index.map(lambda x: day_names.get(int(x), str(x)))
            st.subheader(f"Query Volume Heatmap - {sel_wh}")
            st.dataframe(pivot.style.background_gradient(cmap="YlOrRd"), width="stretch")
            render_shell_snapshot((
                ("Total Queries", f"{int(wh_data['QUERY_COUNT'].sum()):,}"),
                ("Peak Hour", f"{int(pivot.max().max()):,}"),
                ("Avg Elapsed", f"{wh_data['AVG_ELAPSED_SEC'].mean():.1f}s"),
            ))
