"""Cost Center Burn Rate renderer."""
from __future__ import annotations

from datetime import date, datetime

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
from runtime_state import GLOBAL_END_DATE, GLOBAL_START_DATE, get_state
from sections.decision_workspace_scope import active_decision_window_days
from sections.chart_helpers import render_ranked_bar_chart, render_time_series_chart
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from utils import (
    build_cost_reconciliation_sql,
    build_mart_chargeback_sql,
    build_mart_cost_explorer_sql,
    build_metered_credit_cte,
    burn_trend_label,
    credits_to_dollars,
    defer_source_note,
    download_csv,
    format_credits,
    format_snowflake_error,
    get_ai_credit_price,
    freshness_note,
    get_active_environment,
    get_company_case_expr,
    get_environment_case_expr,
    get_global_filter_clause,
    load_mart_table,
    load_shared_bill_metering_summary,
    load_shared_bill_warehouse_delta,
    load_shared_service_cost_trend,
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


def _burn_rate_window_days(default: int = 30) -> int:
    """Use the global Decision Workspace window for billing comparisons."""
    return active_decision_window_days(default)


def _coerce_window_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _burn_rate_window_bounds() -> tuple[date | None, date | None]:
    """Return the selected global date bounds without depending on section import cache."""
    return _coerce_window_date(get_state(GLOBAL_START_DATE)), _coerce_window_date(get_state(GLOBAL_END_DATE))


def _account_billing_summary(account_billing: pd.DataFrame | None, warehouse_credits: float, credit_price: float) -> dict:
    """Summarize Snowsight-aligned account billing rows separately from warehouse rows."""
    if account_billing is None or account_billing.empty:
        return {
            "available": False,
            "account_credits": 0.0,
            "account_cost_usd": 0.0,
            "avg_daily_account_credits": 0.0,
            "service_other_credits": 0.0,
        }
    credits = pd.to_numeric(account_billing.get("DAILY_CREDITS", pd.Series(dtype=float)), errors="coerce").fillna(0)
    spend = pd.to_numeric(account_billing.get("DAILY_SPEND_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
    account_credits = safe_float(credits.sum())
    account_cost = safe_float(spend.sum()) or credits_to_dollars(account_credits, credit_price)
    observed_days = max(int(credits.astype(float).ne(0).sum()), 1)
    return {
        "available": True,
        "account_credits": account_credits,
        "account_cost_usd": account_cost,
        "avg_daily_account_credits": account_credits / observed_days,
        "service_other_credits": max(account_credits - safe_float(warehouse_credits), 0.0),
    }


def render_burn_rate(session, company: str, credit_price: float, max_wh_size_expr: str, bytes_scanned_sum_expr: str, query_tag_dimension_expr: str) -> None:
    st.subheader("Burn Rate & Forecast")
    br_days = _burn_rate_window_days(30)
    window_start, window_end = _burn_rate_window_bounds()
    st.session_state["br_days"] = br_days
    if window_start and window_end:
        st.caption(f"Window: selected Decision Workspace date range ({window_start} to {window_end}, {br_days} days).")
    else:
        st.caption(f"Window: selected Decision Workspace date range ({br_days} days).")
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
            st.warning(f"Warehouse burn-rate data unavailable in this role/context: {format_snowflake_error(e)}")
            st.session_state["df_br"] = pd.DataFrame()
            st.session_state["cc_burn_source"] = freshness_note("WAREHOUSE_METERING_HISTORY")
        try:
            account_result = load_shared_service_cost_trend(
                br_days,
                company,
                credit_price=credit_price,
                ai_credit_price=get_ai_credit_price(),
                start_date=window_start,
                end_date=window_end,
                force=True,
                section="Cost & Contract",
            )
            st.session_state["df_br_account_billing"] = account_result.data
            st.session_state["cc_burn_account_source"] = account_result.source
            st.session_state["cc_burn_account_unavailable"] = ""
        except Exception as e:
            st.session_state["df_br_account_billing"] = pd.DataFrame()
            st.session_state["cc_burn_account_source"] = "Account billing reconciliation unavailable"
            st.session_state["cc_burn_account_unavailable"] = format_snowflake_error(e)

    df_b_state = st.session_state.get("df_br")
    account_daily = st.session_state.get("df_br_account_billing")
    has_warehouse_rows = isinstance(df_b_state, pd.DataFrame) and not df_b_state.empty
    has_account_rows = isinstance(account_daily, pd.DataFrame) and not account_daily.empty
    if has_warehouse_rows or has_account_rows:
        df_b = df_b_state if has_warehouse_rows else pd.DataFrame(columns=["DAY", "WAREHOUSE_NAME", "DAILY_CREDITS"])
        total_cr = df_b["DAILY_CREDITS"].sum()
        account = _account_billing_summary(account_daily, total_cr, credit_price)
        if account["available"]:
            render_shell_snapshot((
                ("Account Billed Credits", f"{safe_float(account.get('account_credits')):,.2f} cr"),
                ("Account Billed Cost", f"${safe_float(account.get('account_cost_usd')):,.2f}"),
                ("Warehouse Credits", format_credits(total_cr)),
                ("Service / Other Bridge", f"{safe_float(account.get('service_other_credits')):,.2f} cr"),
                ("Avg Daily Billed Credits", f"{safe_float(account.get('avg_daily_account_credits')):,.2f}"),
            ))
            defer_source_note(
                metric_confidence_label("exact"),
                "Account billed metrics use completed METERING_HISTORY windows like Snowsight Admin Cost Management; "
                f"warehouse rows below use {st.session_state.get('cc_burn_source', freshness_note('WAREHOUSE_METERING_HISTORY'))}.",
            )
        else:
            render_shell_snapshot((
                ("Warehouse Credits", format_credits(total_cr)),
                ("Warehouse Cost", f"${credits_to_dollars(total_cr, credit_price):,.2f}"),
                ("Avg Daily Warehouse Credits", f"{total_cr / max(br_days,1):,.2f}"),
            ))
            account_gap = st.session_state.get("cc_burn_account_unavailable")
            if account_gap:
                st.caption(
                    "Snowsight account-billed reconciliation is unavailable for this role/context; "
                    "showing warehouse-only credits below."
                )
            defer_source_note(
                metric_confidence_label("exact"),
                st.session_state.get("cc_burn_source", freshness_note("WAREHOUSE_METERING_HISTORY")),
            )
        if has_warehouse_rows:
            daily = df_b.groupby("DAY")["DAILY_CREDITS"].sum().reset_index()
            render_chart_with_data_toggle(
                "Daily Warehouse Credit Burn",
                "cc_burn_daily_credits",
                lambda: render_time_series_chart(daily, "DAY", "DAILY_CREDITS"),
                daily,
                priority_columns=["DAY", "DAILY_CREDITS"],
                sort_by=["DAY"],
                ascending=True,
                max_rows=30,
            )
        else:
            st.caption("No warehouse-attributed credits were returned for the selected company/window.")
        if has_account_rows:
            render_chart_with_data_toggle(
                "Daily Account Billed Cost",
                "cc_burn_account_daily_cost",
                lambda: render_time_series_chart(account_daily, "USAGE_DATE", "DAILY_SPEND_USD"),
                account_daily,
                priority_columns=["USAGE_DATE", "DAILY_CREDITS", "DAILY_SPEND_USD"],
                sort_by=["USAGE_DATE"],
                ascending=True,
                max_rows=30,
            )
        if has_warehouse_rows:
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
