"""Cost Center Burn Rate renderer."""
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
    render_time_series_chart,
    run_query,
    safe_float,
    safe_int,
)


def render_burn_rate(session, company: str, credit_price: float, max_wh_size_expr: str, bytes_scanned_sum_expr: str, query_tag_dimension_expr: str) -> None:
    st.subheader("Burn Rate & Forecast")
    br_days = day_window_selectbox("Lookback", key="br_days", default=30)
    if st.button("Load Burn Rate & Forecast", key="br_load"):
        try:
            burn_result = load_shared_warehouse_daily_credits_by_warehouse(
                session,
                br_days,
                company,
                force=True,
                section="Cost & Contract",
            )
            st.session_state["df_br"] = burn_result.data
            st.session_state["cc_burn_source"] = burn_result.source
        except Exception as e:
            st.warning(f"Burn-rate data unavailable in this role/context: {format_snowflake_error(e)}")

    if st.session_state.get("df_br") is not None and not st.session_state["df_br"].empty:
        df_b = st.session_state["df_br"]
        total_cr = df_b["DAILY_CREDITS"].sum()
        render_shell_snapshot((
            ("Total Credits", format_credits(total_cr)),
            ("Total Cost", f"${credits_to_dollars(total_cr, credit_price):,.2f}"),
            ("Avg Daily Credits", f"{total_cr / max(br_days,1):,.2f}"),
        ))
        defer_source_note(
            metric_confidence_label("exact"),
            st.session_state.get("cc_burn_source", freshness_note("WAREHOUSE_METERING_HISTORY")),
        )
        daily = df_b.groupby("DAY")["DAILY_CREDITS"].sum().reset_index()
        render_chart_with_data_toggle(
            "Daily Credit Burn",
            "cc_burn_daily_credits",
            lambda: render_time_series_chart(daily, "DAY", "DAILY_CREDITS"),
            daily,
            priority_columns=["DAY", "DAILY_CREDITS"],
            sort_by=["DAY"],
            ascending=True,
            max_rows=30,
        )
        by_wh = (
            df_b.groupby("WAREHOUSE_NAME")["DAILY_CREDITS"]
            .sum().reset_index()
            .sort_values("DAILY_CREDITS", ascending=False)
        )
        st.subheader("Credits by Warehouse")
        render_drillable_bar_chart(
            by_wh, dimension="WAREHOUSE_NAME", measure="DAILY_CREDITS",
            key="cc_wh_credits", drilldown_column="warehouse_name",
            lookback_hours=br_days * 24,
        )
        download_csv(df_b, "burn_rate.csv")


__all__ = [
    "render_burn_rate",
]
