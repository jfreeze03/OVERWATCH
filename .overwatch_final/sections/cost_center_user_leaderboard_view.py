"""Cost Center User Leaderboard renderer."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.cost_center_action_queue import _queue_bill_exceptions, _queue_cost_outliers
from sections.cost_center_contracts import COST_EXPLORER_LENSES, NO_DATABASE_CONTEXT_VALUES
from sections.cost_center_models import (
    _annotate_allocation_quality,
    _annotate_cost_routes,
    _annual_service_projection_metrics,
    _bill_driver_summary,
    _bill_period_bounds,
    _build_bill_waterfall,
    _build_explain_bill_markdown,
    _build_finance_movement_summary,
    _cost_explorer_gap_board,
    _cost_explorer_summary,
    _first_value,
    _fmt_delta,
    _normalize_cost_explorer_detail,
    _pct_delta,
    _prepare_cost_forecast_rows,
    _service_cost_category,
)
from sections.cost_center_sql import (
    _annual_service_projection_sql,
    _cost_explorer_live_sql,
    _snowflake_admin_reconciliation_sql,
)
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from utils import (
    build_cost_reconciliation_sql,
    build_mart_chargeback_sql,
    build_mart_cost_explorer_sql,
    build_metered_credit_cte,
    burn_trend_label,
    credits_to_dollars,
    day_window_selectbox,
    defer_source_note,
    download_csv,
    format_credits,
    format_snowflake_error,
    freshness_note,
    get_active_environment,
    get_company_case_expr,
    get_environment_case_expr,
    get_global_filter_clause,
    load_mart_table,
    load_shared_bill_metering_summary,
    load_shared_bill_warehouse_delta,
    load_shared_warehouse_daily_credits,
    load_shared_warehouse_daily_credits_by_warehouse,
    mart_source_caption,
    metric_confidence_label,
    query_attribution_supported,
    render_chart_with_data_toggle,
    render_drillable_bar_chart,
    render_entity_query_drilldown,
    render_priority_dataframe,
    render_ranked_bar_chart,
    run_query,
    safe_float,
    safe_int,
)


def render_user_leaderboard(session, company: str, credit_price: float, max_wh_size_expr: str, bytes_scanned_sum_expr: str, query_tag_dimension_expr: str) -> None:
    st.subheader("Cost by User / Role")
    days = day_window_selectbox("Lookback", key="cc_lead_days", default=30)
    gf = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name", "q.schema_name"
    )

    if st.button("Load Leaderboard", key="cc_lead_load"):
        try:
            df_lead = run_query(f"""
            WITH {build_metered_credit_cte(days_back=days)}
            SELECT
                q.user_name,
                q.warehouse_name,
                {max_wh_size_expr} AS warehouse_size,
                COUNT(*)                                     AS query_count,
                ROUND(AVG(q.total_elapsed_time)/1000, 2)    AS avg_elapsed_sec,
                ROUND(SUM(pqc.metered_credits), 4)          AS total_credits,
                ROUND({bytes_scanned_sum_expr}/POWER(1024,3),2) AS total_gb_scanned
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
            WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {gf}
            GROUP BY q.user_name, q.warehouse_name
            ORDER BY total_credits DESC
            LIMIT 200
            """, ttl_key=f"cc_lead_{company}_{days}", tier="standard")
            st.session_state["df_lead"] = df_lead
        except Exception as e:
            st.warning(f"Cost leaderboard unavailable in this role/context: {format_snowflake_error(e)}")

    if st.session_state.get("df_lead") is not None and not st.session_state["df_lead"].empty:
        df_l = st.session_state["df_lead"]
        df_l["COST"] = df_l["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
        render_shell_snapshot((
            ("Distinct Users", df_l["USER_NAME"].nunique()),
            ("Total Credits", format_credits(df_l["TOTAL_CREDITS"].sum())),
            ("Total Est. Cost", f"${df_l['COST'].sum():,.2f}"),
        ))
        defer_source_note(metric_confidence_label("allocated"), freshness_note("ACCOUNT_USAGE"))

        st.subheader("Top Users by Cost")
        df_l = _annotate_cost_routes(df_l, "User Cost")
        user_agg = (
            df_l.groupby("USER_NAME")["COST"]
            .sum().reset_index()
            .sort_values("COST", ascending=False)
            .head(20)
        )
        render_chart_with_data_toggle(
            "Cost leaderboard drivers",
            "cc_user_cost_driver",
            lambda: render_drillable_bar_chart(
                user_agg,
                dimension="USER_NAME",
                measure="COST",
                key="cc_user_cost",
                drilldown_column="user_name",
                lookback_hours=days * 24,
            ),
            df_l,
            priority_columns=[
                "USER_NAME",
                "WAREHOUSE_NAME",
                "WAREHOUSE_SIZE",
                "TOTAL_CREDITS",
                "COST",
                "QUERY_COUNT",
                "AVG_ELAPSED_SEC",
                "TOTAL_GB_SCANNED",
                "NEXT_WORKFLOW",
                "NEXT_ACTION",
            ],
            sort_by=["TOTAL_CREDITS", "COST", "QUERY_COUNT"],
            ascending=[False, False, False],
            raw_label="All user/warehouse cost rows",
        )

        # User profile drill-through
        st.divider()
        st.subheader("User Profile Drill-Down")
        if "USER_NAME" in df_l.columns:
            user_options = [""] + df_l["USER_NAME"].dropna().astype(str).unique().tolist()
            user_col, load_col = st.columns([4, 1])
            with user_col:
                sel_user = st.selectbox(
                    "Select user for full query breakdown",
                    user_options,
                    key="cc_user_profile_sel",
                    format_func=lambda value: "(select user)" if not value else str(value),
                )
            with load_col:
                st.write("")
                if st.button("Load", key="cc_user_profile_load", width="stretch", disabled=not bool(sel_user)):
                    st.session_state["cc_user_profile_requested"] = sel_user
            if (
                sel_user
                and st.session_state.get("cc_user_profile_requested") == sel_user
            ):
                render_entity_query_drilldown(
                    sel_user, key="cc_user_profile",
                    entity_column="user_name", lookback_hours=days * 24,
                )

        download_csv(df_l, "cost_leaderboard.csv")
        if st.button("Save top cost outliers to Action Queue", key="cc_lead_queue"):
            _queue_cost_outliers(session, df_l, credit_price, "Cost & Contract - User Leaderboard")


__all__ = [
    "render_user_leaderboard",
]
