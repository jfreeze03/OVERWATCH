"""Cost Center Reconciliation renderer."""
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


def render_cost_reconciliation(session, company: str, credit_price: float, max_wh_size_expr: str, bytes_scanned_sum_expr: str, query_tag_dimension_expr: str) -> None:
    st.subheader("Cost Reconciliation")
    defer_source_note(
        "Compares exact warehouse metering to query-level allocated credits. "
        "Large variances usually mean idle warehouse time, non-query activity, latency, or chargeback assumptions need review. "
        "The load also bridges Snowflake Admin account totals to scoped OVERWATCH warehouse and workload views."
    )
    st.caption(
        "Snowflake Admin bridge: account totals, official warehouse metering, scoped warehouse totals, "
        "and allocated query workload stay side by side after load."
    )
    recon_days = day_window_selectbox("Reconciliation window", key="cc_recon_days", default=30)
    if st.button("Load Reconciliation", key="cc_recon_load"):
        try:
            use_official_attribution = query_attribution_supported(session)
            st.session_state["df_cc_recon"] = run_query(
                build_cost_reconciliation_sql(
                    recon_days,
                    prefer_query_attribution=use_official_attribution,
                ),
                ttl_key=f"cc_recon_{company}_{recon_days}_{int(use_official_attribution)}",
                tier="standard",
                section="Cost & Contract",
            )
            st.session_state["cc_recon_attribution_source"] = (
                "QUERY_ATTRIBUTION_HISTORY preferred with OVERWATCH allocation fallback"
                if use_official_attribution
                else "OVERWATCH allocated fallback"
            )
            try:
                st.session_state["df_cc_admin_recon"] = run_query(
                    _snowflake_admin_reconciliation_sql(recon_days),
                    ttl_key=f"cc_admin_recon_{recon_days}",
                    tier="standard",
                    section="Cost & Contract",
                )
                st.session_state["cc_admin_recon_error"] = ""
            except Exception as admin_exc:
                st.session_state["df_cc_admin_recon"] = pd.DataFrame()
                st.session_state["cc_admin_recon_error"] = format_snowflake_error(admin_exc)
        except Exception as e:
            st.warning(f"Cost reconciliation unavailable in this role/context: {format_snowflake_error(e)}")

    if st.session_state.get("df_cc_recon") is not None and not st.session_state["df_cc_recon"].empty:
        df_r = st.session_state["df_cc_recon"]
        total_exact = float(df_r["EXACT_METERED_CREDITS"].sum()) if "EXACT_METERED_CREDITS" in df_r.columns else 0.0
        total_alloc = float(df_r["ALLOCATED_QUERY_CREDITS"].sum()) if "ALLOCATED_QUERY_CREDITS" in df_r.columns else 0.0
        total_var = total_exact - total_alloc
        render_shell_snapshot((
            ("Exact Metered", format_credits(total_exact)),
            ("Allocated to Queries", format_credits(total_alloc)),
            ("Unallocated / Variance", format_credits(total_var)),
        ))
        defer_source_note(
            f"{metric_confidence_label('exact')} for metering; "
            f"{metric_confidence_label('allocated')} for query attribution. "
            f"Source: {st.session_state.get('cc_recon_attribution_source', 'OVERWATCH allocated fallback')} | "
            f"{freshness_note('WAREHOUSE_METERING_HISTORY')}"
        )
        admin_recon = st.session_state.get("df_cc_admin_recon")
        if admin_recon is not None and not admin_recon.empty:
            admin_view = admin_recon.copy()
            admin_view.columns = [str(col).upper() for col in admin_view.columns]
            admin_view["CREDITS"] = pd.to_numeric(admin_view.get("CREDITS", 0), errors="coerce").fillna(0)
            account_total = float(
                admin_view.loc[
                    admin_view["MEASUREMENT"].astype(str).str.upper().eq("SNOWFLAKE ADMIN ACCOUNT TOTAL"),
                    "CREDITS",
                ].sum()
            )
            official_warehouse = float(
                admin_view.loc[
                    admin_view["MEASUREMENT"].astype(str).str.upper().eq("OFFICIAL WAREHOUSE COMPUTE TOTAL"),
                    "CREDITS",
                ].sum()
            )
            service_other = float(
                admin_view.loc[
                    admin_view["MEASUREMENT"].astype(str).str.upper().eq("ACCOUNT SERVICE / OTHER CREDITS"),
                    "CREDITS",
                ].sum()
            )
            render_shell_snapshot((
                ("Snowflake Admin Total", f"{format_credits(account_total)} / ${credits_to_dollars(account_total, credit_price):,.2f}"),
                ("Official Warehouse Total", f"{format_credits(official_warehouse)} / ${credits_to_dollars(official_warehouse, credit_price):,.2f}"),
                ("Account Service / Other", f"{format_credits(service_other)} / ${credits_to_dollars(service_other, credit_price):,.2f}"),
                ("Scoped Warehouse Total", f"{format_credits(total_exact)} / ${credits_to_dollars(total_exact, credit_price):,.2f}"),
            ))
            bridge_rows = admin_view[[
                "MEASUREMENT", "SCOPE", "CREDITS", "SOURCE", "CONFIDENCE", "COMPANY_SPLIT_NOTE"
            ]].copy()
            bridge_rows["COST_USD"] = bridge_rows["CREDITS"].apply(
                lambda value: credits_to_dollars(safe_float(value), credit_price)
            )
            bridge_rows = pd.concat([
                bridge_rows,
                pd.DataFrame([
                    {
                        "MEASUREMENT": f"OVERWATCH scoped warehouse total ({company})",
                        "SCOPE": company,
                        "CREDITS": round(total_exact, 6),
                        "COST_USD": round(credits_to_dollars(total_exact, credit_price), 2),
                        "SOURCE": "Scoped WAREHOUSE_METERING_HISTORY",
                        "CONFIDENCE": "Exact within configured warehouse scope",
                        "COMPANY_SPLIT_NOTE": "Company-specific when warehouse ownership is configured.",
                    },
                    {
                        "MEASUREMENT": f"OVERWATCH allocated query workload ({company})",
                        "SCOPE": company,
                        "CREDITS": round(total_alloc, 6),
                        "COST_USD": round(credits_to_dollars(total_alloc, credit_price), 2),
                        "SOURCE": st.session_state.get("cc_recon_attribution_source", "OVERWATCH allocated fallback"),
                        "CONFIDENCE": "Allocated / directional",
                        "COMPANY_SPLIT_NOTE": "Use for workload chargeback directionally; shared idle overhead remains separate.",
                    },
                ]),
            ], ignore_index=True)
            render_priority_dataframe(
                bridge_rows,
                title="Snowflake Admin / OVERWATCH reconciliation bridge",
                priority_columns=[
                    "MEASUREMENT", "SCOPE", "CREDITS", "COST_USD",
                    "CONFIDENCE", "COMPANY_SPLIT_NOTE", "SOURCE",
                ],
                sort_by=["CREDITS"],
                ascending=False,
                raw_label="All reconciliation bridge rows",
                height=300,
            )
            defer_source_note(
                "Snowflake Admin/Cost Management totals are account-wide. "
                "OVERWATCH company rows stay separate unless the source exposes warehouse, database, user, or role ownership."
            )
        elif st.session_state.get("cc_admin_recon_error"):
            st.info(
                "Snowflake Admin/Cost Management account bridge is unavailable for this role/context: "
                f"{st.session_state['cc_admin_recon_error']}"
            )
        if "RECONCILIATION_STATUS" in df_r.columns:
            status_counts = (
                df_r["RECONCILIATION_STATUS"]
                .value_counts()
                .rename_axis("RECONCILIATION_STATUS")
                .reset_index(name="WAREHOUSE_COUNT")
            )
            render_chart_with_data_toggle(
                "Reconciliation Status",
                "cc_reconciliation_status",
                lambda: render_ranked_bar_chart(
                    status_counts,
                    "RECONCILIATION_STATUS",
                    "WAREHOUSE_COUNT",
                    top_n=10,
                ),
                status_counts,
                priority_columns=["RECONCILIATION_STATUS", "WAREHOUSE_COUNT"],
                sort_by=["WAREHOUSE_COUNT"],
                ascending=False,
                max_rows=10,
            )
        render_priority_dataframe(
            df_r,
            title="Reconciliation variances to review",
            priority_columns=[
                "WAREHOUSE_NAME",
                "EXACT_METERED_CREDITS",
                "ALLOCATED_QUERY_CREDITS",
                "OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS",
                "OVERWATCH_ALLOCATED_CREDITS",
                "OFFICIAL_ATTRIBUTED_QUERIES",
                "ATTRIBUTION_SOURCE",
                "VARIANCE_CREDITS",
                "VARIANCE_PCT",
                "RECONCILIATION_STATUS",
            ],
            sort_by=["VARIANCE_CREDITS", "VARIANCE_PCT", "EXACT_METERED_CREDITS"],
            ascending=[False, False, False],
            raw_label="All reconciliation rows",
            height=420,
        )
        download_csv(df_r, "cost_reconciliation.csv")


__all__ = [
    "render_cost_reconciliation",
]
