"""Cost Center Cost Explorer renderer."""
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


def render_cost_explorer(session, company: str, credit_price: float, max_wh_size_expr: str, bytes_scanned_sum_expr: str, query_tag_dimension_expr: str) -> None:
    st.subheader("Cost Explorer")
    st.caption("Cost drilldown by company, route, warehouse, database, role, and user.")

    c1, c2, c3, c4 = st.columns([1, 1.35, 1, 1.2])
    with c1:
        explorer_days = day_window_selectbox("Lookback", key="cc_explorer_days", default=30)
    with c2:
        explorer_lens = st.selectbox("Break down by", COST_EXPLORER_LENSES, key="cc_explorer_lens")
    with c3:
        min_est_cost = st.number_input(
            "Min cost",
            min_value=0.0,
            value=0.0,
            step=50.0,
            key="cc_explorer_min_cost",
        )
    with c4:
        department_contains = st.text_input(
            "Department contains",
            value="",
            key="cc_explorer_department_contains",
        )

    if st.button("Load Cost Explorer", key="cc_explorer_load", type="primary"):
        try:
            mart_sql = build_mart_cost_explorer_sql(
                explorer_days,
                company=company,
                warehouse_contains=st.session_state.get("global_warehouse", ""),
                user_contains=st.session_state.get("global_user", ""),
                role_contains=st.session_state.get("global_role", ""),
                database_contains=st.session_state.get("global_database", ""),
                department_contains=department_contains,
            )
            mart_result = load_mart_table(
                "FACT_CHARGEBACK_DAILY",
                mart_sql,
                source_label="FACT_CHARGEBACK_DAILY",
            )
            if mart_result.available and not mart_result.data.empty:
                explorer_detail = mart_result.data
                explorer_source = mart_source_caption(mart_result)
            else:
                live_sql = _cost_explorer_live_sql(
                    explorer_days,
                    company,
                    max_wh_size_expr,
                    department_contains=department_contains,
                )
                explorer_detail = run_query(
                    live_sql,
                    ttl_key=(
                        f"cc_cost_explorer_{company}_{get_active_environment()}_"
                        f"{explorer_days}_{st.session_state.get('global_warehouse', '')}_"
                        f"{st.session_state.get('global_user', '')}_"
                        f"{st.session_state.get('global_role', '')}_"
                        f"{st.session_state.get('global_database', '')}_{department_contains}"
                    ),
                    tier="standard",
                )
                fallback_note = ""
                if mart_result.message:
                    fallback_note = f" Fast summary unavailable: {mart_result.message[:160]}"
                elif mart_result.available:
                    fallback_note = " Mart returned no rows for the selected scope."
                explorer_source = (
                    "Live fallback: ACCOUNT_USAGE query allocation. "
                    "Use this for DBA triage; exact chargeback still needs warehouse metering reconciliation."
                    f"{fallback_note}"
                )
            st.session_state["df_cost_explorer_detail"] = _normalize_cost_explorer_detail(
                explorer_detail,
                credit_price,
            )
            st.session_state["df_cost_explorer_source"] = explorer_source
        except Exception as e:
            st.warning(f"Cost Explorer unavailable in this role/context: {format_snowflake_error(e)}")

    detail = st.session_state.get("df_cost_explorer_detail")
    if detail is not None and not detail.empty:
        detail = _normalize_cost_explorer_detail(detail, credit_price)
        if min_est_cost > 0 and "EST_COST" in detail.columns:
            detail = detail[detail["EST_COST"] >= float(min_est_cost)].copy()
        if detail.empty:
            st.info("No cost rows match the current minimum-cost threshold.")
        else:
            summary = _cost_explorer_summary(detail, explorer_lens)
            gap_board = _cost_explorer_gap_board(detail, summary)
            total_cost = safe_float(detail["EST_COST"].sum())
            total_credits = safe_float(detail["TOTAL_CREDITS"].sum())
            denominator = max(total_cost, 0.01)
            readiness = detail["CHARGEBACK_READY"].fillna("").astype(str).str.upper()
            owner_source = detail["OWNER_SOURCE"].fillna("").astype(str).str.upper()
            database = detail["DATABASE_NAME"].fillna("").astype(str).str.upper()
            no_context = database.isin(NO_DATABASE_CONTEXT_VALUES) | detail["ENVIRONMENT_ROLLUP"].fillna("").astype(str).str.upper().eq("NO DATABASE CONTEXT")
            ready_cost = safe_float(detail.loc[readiness.eq("READY"), "EST_COST"].sum())
            tag_cost = safe_float(detail.loc[owner_source.str.contains("TAG", na=False), "EST_COST"].sum())
            no_context_cost = safe_float(detail.loc[no_context, "EST_COST"].sum())
            top_share = safe_float(summary.iloc[0].get("PCT_OF_COST")) if not summary.empty else 0.0

            render_shell_snapshot((
                ("Estimated spend", f"${total_cost:,.0f}"),
                ("Allocated credits", format_credits(total_credits)),
                ("Ready cost", f"{ready_cost / denominator * 100:.0f}%"),
                ("Tag proof", f"{tag_cost / denominator * 100:.0f}%"),
                ("No DB context", f"${no_context_cost:,.0f}"),
                ("Top driver", f"{top_share:.0f}%"),
            ))
            defer_source_note(st.session_state.get(
                "df_cost_explorer_source",
                "Cost Explorer measurement: available after refresh",
            ))

            render_chart_with_data_toggle(
                f"Top {explorer_lens} cost drivers",
                f"cc_explorer_{explorer_lens.lower().replace(' ', '_')}",
                lambda: render_ranked_bar_chart(
                    summary,
                    "DIMENSION",
                    "EST_COST",
                    top_n=20,
                    color="#0ea5e9",
                ),
                summary,
                priority_columns=[
                    "DIMENSION",
                    "EST_COST",
                    "PCT_OF_COST",
                    "TOTAL_CREDITS",
                    "QUERY_COUNT",
                    "ACTIVE_DAYS",
                    "USERS",
                    "ROLES",
                    "WAREHOUSES",
                    "DATABASES",
                    "ENVIRONMENTS",
                    "CHARGEBACK_READY",
                    "ROUTE_TELEMETRY",
                    "ALLOCATION_CONFIDENCE",
                    "FIRST_USAGE_DATE",
                    "LAST_USAGE_DATE",
                ],
                sort_by=["EST_COST", "TOTAL_CREDITS", "QUERY_COUNT"],
                ascending=[False, False, False],
                max_rows=30,
                raw_label="All cost-drilldown rows",
            )
            defer_source_note("Cost Explorer bars are sorted highest to lowest by estimated cost; switch to Data for exact rows.")
            render_priority_dataframe(
                gap_board,
                title="Cost attribution gaps",
                priority_columns=["GAP", "STATE", "EST_COST", "ROWS", "TOP_DRIVER", "ACTION"],
                sort_by=["STATE", "EST_COST"],
                ascending=[True, False],
                max_rows=8,
                raw_label="All cost-attribution gaps",
            )
            render_priority_dataframe(
                detail,
                title="Cost explorer detail",
                priority_columns=[
                    "COMPANY",
                    "ENVIRONMENT_ROLLUP",
                    "DATABASE_NAME",
                    "DEPARTMENT",
                    "WAREHOUSE_NAME",
                    "USER_NAME",
                    "ROLE_NAME",
                    "TOTAL_CREDITS",
                    "EST_COST",
                    "QUERY_COUNT",
                    "ALLOCATION_CONFIDENCE",
                    "CHARGEBACK_READY",
                    "OWNER_SOURCE",
                    "FIRST_USAGE_DATE",
                    "LAST_USAGE_DATE",
                ],
                sort_by=["EST_COST", "TOTAL_CREDITS", "QUERY_COUNT"],
                ascending=[False, False, False],
                max_rows=40,
                raw_label="Raw Cost Explorer detail",
            )
            download_csv(detail, "cost_explorer_detail.csv")
            if st.button("Save cost explorer outliers to Action Queue", key="cc_explorer_queue"):
                _queue_cost_outliers(session, detail, credit_price, "Cost & Contract - Cost Explorer")


__all__ = [
    "render_cost_explorer",
]
