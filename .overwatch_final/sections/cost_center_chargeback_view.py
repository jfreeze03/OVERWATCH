"""Cost Center Chargeback renderer."""
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
    _chargeback_readiness_label,
    _first_value,
    _fmt_delta,
    _mixed_label,
    _normalize_cost_explorer_detail,
    _pct_delta,
    _prepare_cost_forecast_rows,
    _route_telemetry_label,
    _service_cost_category,
)
from sections.cost_center_sql import (
    _annual_service_projection_sql,
    _cost_explorer_live_sql,
    _snowflake_admin_reconciliation_sql,
)
from sections.chart_helpers import render_ranked_bar_chart
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


def render_chargeback(session, company: str, credit_price: float, max_wh_size_expr: str, bytes_scanned_sum_expr: str, query_tag_dimension_expr: str) -> None:
    st.subheader("Chargeback / Company Split")
    st.caption("Allocated credits split by company, environment, database, user, and warehouse.")
    defer_source_note(
        "Database-attributed cost is directional because shared warehouses cannot be exactly split by PROD/DEV."
    )
    cb_days = day_window_selectbox("Lookback", key="cc_cb_days", default=30)

    if st.button("Load Chargeback / Company Split", key="cc_cb_load"):
        try:
            mart_sql = build_mart_chargeback_sql(
                cb_days,
                company=company,
                warehouse_contains=st.session_state.get("global_warehouse", ""),
                user_contains=st.session_state.get("global_user", ""),
                role_contains=st.session_state.get("global_role", ""),
                database_contains=st.session_state.get("global_database", ""),
            )
            mart_result = load_mart_table(
                "FACT_CHARGEBACK_DAILY",
                mart_sql,
                source_label="FACT_CHARGEBACK_DAILY",
            )
            if mart_result.available and not mart_result.data.empty:
                df_cb = mart_result.data
                source_caption = mart_source_caption(mart_result)
            else:
                # FIX: replaced hardcoded CASE with get_company_case_expr()
                # which reads from COMPANY_CONFIG and includes all WH_ALFA_* warehouses
                company_expr = get_company_case_expr(
                    "q.warehouse_name", "q.database_name", "q.user_name", "q.role_name"
                )
                environment_expr = get_environment_case_expr("q.database_name")
                cb_scope = get_global_filter_clause(
                    "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name", "q.schema_name"
                )
                live_chargeback_sql = f"""
            WITH {build_metered_credit_cte(days_back=cb_days)},
            query_costs AS (
                SELECT
                    {company_expr}         AS company,
                    {environment_expr}     AS environment,
                    COALESCE(q.database_name, 'NO_DATABASE_CONTEXT') AS database_name,
                    q.user_name,
                    q.role_name,
                    q.warehouse_name,
                    {max_wh_size_expr} AS warehouse_size,
                    COUNT(*)               AS query_count,
                    SUM(COALESCE(pqc.metered_credits,0)) AS total_credits
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('day', -{cb_days}, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {cb_scope}
                GROUP BY 1, 2, 3, q.user_name, q.role_name, q.warehouse_name
            )
            SELECT company, environment, database_name, user_name, role_name, warehouse_name, warehouse_size, query_count,
                   ROUND(total_credits, 4) AS total_credits
            FROM query_costs
            ORDER BY total_credits DESC
            """
                df_cb = run_query(
                    live_chargeback_sql,
                    ttl_key=f"cc_chargeback_{company}_{get_active_environment()}_{cb_days}",
                    tier="standard",
                )
                fallback_note = ""
                if mart_result.message:
                    fallback_note = f" Fast summary unavailable: {mart_result.message[:160]}"
                elif mart_result.available:
                    fallback_note = " Mart returned no chargeback rows for the selected scope."
                source_caption = (
                    "Live fallback: ACCOUNT_USAGE query allocation. "
                    "Database-attributed cost remains Allocated / Estimated."
                    f"{fallback_note}"
                )
            st.session_state["df_chargeback"] = df_cb
            st.session_state["df_chargeback_source"] = source_caption
        except Exception as e:
            st.warning(f"Chargeback / company split data unavailable in this role/context: {format_snowflake_error(e)}")

    if st.session_state.get("df_chargeback") is not None and not st.session_state["df_chargeback"].empty:
        df_cb = _annotate_allocation_quality(st.session_state["df_chargeback"])
        df_cb["EST_COST"] = df_cb["TOTAL_CREDITS"].apply(lambda x: credits_to_dollars(x, credit_price))
        defer_source_note(st.session_state.get(
            "df_chargeback_source",
            "Chargeback measurement: available after refresh",
        ))

        # Summary by company - the key chargeback output
        summary = (
            df_cb.groupby("COMPANY", as_index=False)
            .agg(
                TOTAL_CREDITS=("TOTAL_CREDITS", "sum"),
                EST_COST=("EST_COST", "sum"),
                QUERY_COUNT=("QUERY_COUNT", "sum"),
                ALLOCATION_CONFIDENCE=("ALLOCATION_CONFIDENCE", _mixed_label),
                CHARGEBACK_READY=("CHARGEBACK_READY", _chargeback_readiness_label),
                ROUTE_TELEMETRY=("ROUTE_SOURCE", _route_telemetry_label),
            )
            .sort_values("EST_COST", ascending=False)
        )
        render_shell_snapshot(tuple(
            (
                str(srow["COMPANY"]),
                f"${srow['EST_COST']:,.2f} ({format_credits(srow['TOTAL_CREDITS'])})",
            )
            for _, srow in summary.iterrows()
        ))

        st.subheader("Summary by Company")
        render_priority_dataframe(
            summary,
            title="Chargeback summary",
            priority_columns=[
                "COMPANY", "ALLOCATION_CONFIDENCE", "CHARGEBACK_READY", "ROUTE_TELEMETRY",
                "TOTAL_CREDITS", "EST_COST", "QUERY_COUNT",
            ],
            sort_by=["EST_COST", "TOTAL_CREDITS"],
            ascending=[False, False],
            raw_label="All chargeback summary rows",
        )
        if "ENVIRONMENT" in df_cb.columns:
            st.subheader("Summary by Environment Rollup")
            env_summary = (
                df_cb.groupby(["COMPANY", "ENVIRONMENT_ROLLUP"], as_index=False)
                .agg(
                    TOTAL_CREDITS=("TOTAL_CREDITS", "sum"),
                    EST_COST=("EST_COST", "sum"),
                    QUERY_COUNT=("QUERY_COUNT", "sum"),
                    ALLOCATION_CONFIDENCE=("ALLOCATION_CONFIDENCE", _mixed_label),
                    CHARGEBACK_READY=("CHARGEBACK_READY", _chargeback_readiness_label),
                    ROUTE_TELEMETRY=("ROUTE_SOURCE", _route_telemetry_label),
                )
                .sort_values("EST_COST", ascending=False)
            )
            render_priority_dataframe(
                env_summary,
                title="Chargeback environment summary",
                priority_columns=[
                    "COMPANY", "ENVIRONMENT_ROLLUP", "ALLOCATION_CONFIDENCE", "CHARGEBACK_READY", "ROUTE_TELEMETRY",
                    "TOTAL_CREDITS", "EST_COST", "QUERY_COUNT",
                ],
                sort_by=["EST_COST", "TOTAL_CREDITS"],
                ascending=[False, False],
                raw_label="All environment chargeback rows",
            )
            dev_rows = df_cb[df_cb["ENVIRONMENT_ROLLUP"] == "DEV_ALL"]
            if not dev_rows.empty:
                dev_summary = (
                    dev_rows.groupby(["COMPANY", "ENVIRONMENT", "DATABASE_NAME"], as_index=False)
                    .agg(
                        TOTAL_CREDITS=("TOTAL_CREDITS", "sum"),
                        EST_COST=("EST_COST", "sum"),
                        QUERY_COUNT=("QUERY_COUNT", "sum"),
                        ALLOCATION_CONFIDENCE=("ALLOCATION_CONFIDENCE", _mixed_label),
                        ROUTE_TELEMETRY=("ROUTE_SOURCE", _route_telemetry_label),
                    )
                    .sort_values("EST_COST", ascending=False)
                )
                render_priority_dataframe(
                    dev_summary,
                    title="Chargeback individual DEV databases",
                    priority_columns=[
                        "COMPANY", "ENVIRONMENT", "DATABASE_NAME", "ALLOCATION_CONFIDENCE", "ROUTE_TELEMETRY",
                        "TOTAL_CREDITS", "EST_COST", "QUERY_COUNT",
                    ],
                    sort_by=["EST_COST", "TOTAL_CREDITS"],
                    ascending=[False, False],
                    raw_label="All chargeback individual DEV database rows",
                )

        st.subheader("Detail by User / Warehouse")
        company_filter = st.selectbox(
            "Filter by company", ["All"] + summary["COMPANY"].tolist(), key="cb_co_filter"
        )
        df_show = df_cb if company_filter == "All" else df_cb[df_cb["COMPANY"] == company_filter]
        df_show = _annotate_cost_routes(df_show, "Chargeback")
        render_priority_dataframe(
            df_show,
            title="Chargeback detail drivers",
            priority_columns=[
                "COMPANY",
                "ENVIRONMENT_ROLLUP",
                "ENVIRONMENT",
                "DATABASE_NAME",
                "ALLOCATION_CONFIDENCE",
                "CHARGEBACK_READY",
                "SCOPE_REVIEW",
                "COST_ATTRIBUTION",
                "ROUTE_SOURCE",
                "ROUTE_EVIDENCE",
                "USER_NAME",
                "ROLE_NAME",
                "WAREHOUSE_NAME",
                "WAREHOUSE_SIZE",
                "TOTAL_CREDITS",
                "EST_COST",
                "QUERY_COUNT",
                "NEXT_WORKFLOW",
                "NEXT_ACTION",
            ],
            sort_by=["EST_COST", "TOTAL_CREDITS", "QUERY_COUNT"],
            ascending=[False, False, False],
            raw_label="All chargeback detail rows",
        )
        download_csv(df_show, "chargeback_detail.csv")
        if st.button("Save chargeback outliers to Action Queue", key="cc_chargeback_queue"):
            _queue_cost_outliers(session, df_show, credit_price, "Cost & Contract - Chargeback")


__all__ = [
    "render_chargeback",
]
