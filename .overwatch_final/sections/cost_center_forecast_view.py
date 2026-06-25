"""Cost Center Forecast renderer."""
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
from sections.chart_helpers import render_area_time_series_chart, render_ranked_bar_chart
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
    run_query,
    safe_float,
    safe_int,
)


def render_cost_forecast(session, company: str, credit_price: float, max_wh_size_expr: str, bytes_scanned_sum_expr: str, query_tag_dimension_expr: str) -> None:
    st.subheader("Run-Rate Projection")
    if st.button("Generate Run-Rate Projection", key="fc_load"):
        try:
            result = load_shared_warehouse_daily_credits(
                30,
                company,
                force=True,
                section="Cost & Contract",
            )
            st.session_state["df_fc"] = result.data
            st.session_state["cc_forecast_source"] = result.source
        except Exception as e:
            st.warning(f"Run-rate projection data unavailable in this role/context: {format_snowflake_error(e)}")

    if st.session_state.get("df_fc") is not None and not st.session_state["df_fc"].empty:
        df_f = _prepare_cost_forecast_rows(st.session_state["df_fc"])
        avg_daily = df_f["DAILY_CREDITS"].mean()
        proj_30   = avg_daily * 30
        proj_cost = credits_to_dollars(proj_30, credit_price)
        render_shell_snapshot((
            ("Avg Daily Credits", f"{avg_daily:.2f}"),
            ("Projected 30-day", format_credits(proj_30)),
            ("Projected 30-day Cost", f"${proj_cost:,.2f}"),
        ))
        defer_source_note(st.session_state.get("cc_forecast_source", freshness_note("WAREHOUSE_METERING_HISTORY")))
        render_chart_with_data_toggle(
            "Projected Daily Credits",
            "cc_forecast_daily_credits",
            lambda: render_area_time_series_chart(df_f, "DAY", "DAILY_CREDITS"),
            df_f,
            priority_columns=["DAY", "DAILY_CREDITS"],
            sort_by=["DAY"],
            ascending=True,
            max_rows=90,
        )

    st.divider()
    st.subheader("Annual Service Projection")
    st.caption(
        "Account-wide projection from Snowflake service metering. "
        "Use this to compare OVERWATCH against Snowflake Admin/Cost Management totals."
    )
    annual_period = st.selectbox(
        "Run-rate basis",
        [30, 60, 90],
        index=0,
        key="cc_annual_projection_days",
        format_func=lambda value: f"Last {value} observed service days",
    )
    if st.button("Load Annual Service Projection", key="cc_annual_projection_load"):
        try:
            df_annual = run_query(
                _annual_service_projection_sql(),
                ttl_key=f"cc_annual_service_projection_{annual_period}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["df_cc_annual_projection"] = df_annual
            st.session_state["cc_annual_projection_source"] = (
                "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY, completed 24-hour window"
            )
        except Exception as e:
            st.warning(f"Annual service projection unavailable: {format_snowflake_error(e)}")

    annual_data = st.session_state.get("df_cc_annual_projection")
    if annual_data is not None and not annual_data.empty:
        annual_metrics = _annual_service_projection_metrics(annual_data, annual_period)
        if annual_metrics:
            projected_year = safe_float(annual_metrics.get("PROJECTED_YEAR_CREDITS"))
            projected_remaining = safe_float(annual_metrics.get("PROJECTED_REMAINING_CREDITS"))
            ytd_actual = safe_float(annual_metrics.get("YTD_ACTUAL_CREDITS"))
            render_shell_snapshot((
                ("YTD Actual", format_credits(ytd_actual, credit_price)),
                ("Recent Daily Avg", f"{safe_float(annual_metrics.get('RECENT_DAILY_AVG_CREDITS')):,.2f}"),
                ("Projected Remainder", format_credits(projected_remaining, credit_price)),
                ("Projected Year", format_credits(projected_year, credit_price)),
                ("Days Remaining", f"{safe_int(annual_metrics.get('DAYS_REMAINING')):,}"),
                ("Latest Usage Date", str(annual_metrics.get("LATEST_USAGE_DATE", ""))),
            ))
            defer_source_note(
                metric_confidence_label("projection"),
                st.session_state.get("cc_annual_projection_source", "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY"),
                freshness_note("ACCOUNT_USAGE"),
                "Account-wide; not company-scoped. Reconcile to Snowflake Admin/Cost Management before finance signoff.",
            )
            annual_display = annual_data.copy()
            annual_display["USAGE_DATE"] = pd.to_datetime(annual_display["USAGE_DATE"], errors="coerce")
            annual_display["DAILY_COST_USD"] = annual_display["DAILY_CREDITS"].apply(
                lambda value: credits_to_dollars(safe_float(value), credit_price)
            )
            render_chart_with_data_toggle(
                "YTD Service Credits",
                "cc_annual_service_projection",
                lambda: render_area_time_series_chart(
                    annual_display,
                    "USAGE_DATE",
                    "DAILY_CREDITS",
                    title="YTD Service Credits",
                ),
                annual_display,
                priority_columns=[
                    "USAGE_DATE",
                    "DAILY_CREDITS",
                    "DAILY_COST_USD",
                    "COMPUTE_CREDITS",
                    "CLOUD_SERVICES_CREDITS",
                    "ACTIVE_SERVICES",
                ],
                sort_by=["USAGE_DATE"],
                ascending=True,
                max_rows=370,
                raw_label="All annual service projection rows",
            )


__all__ = [
    "render_cost_forecast",
]
