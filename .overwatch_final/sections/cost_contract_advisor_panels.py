"""Cost & Contract advisor and action render panels."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from runtime_state import set_state
from sections.cost_contract_advisor import (
    _build_cost_advisor_board,
    _build_cost_closure_analytics,
    _cost_advisor_action_summary,
    _cost_advisor_detail_options,
)
from sections.cost_contract_charts import (
    _render_cost_advisor_category_chart,
    _render_cost_chart_with_data_toggle,
    _render_service_cost_movement_chart,
)
from sections.cost_contract_contracts import LEGACY_COST_WORKFLOW_ALIASES, WORKFLOWS
from sections.cost_contract_dataframes import _service_lens_movement_rows
from sections.cost_contract_helpers import get_current_ai_credit_price
from sections.cost_contract_intelligence import _build_service_cost_lens_summary
from sections.cost_contract_overview_panels import _render_metric_items
from sections.shell_helpers import (
    _clean_display_text,
    render_escaped_labeled_text,
    render_shell_snapshot,
)
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note
from utils.workflows import render_priority_dataframe


def _render_savings_closure_control(queue: pd.DataFrame, credit_price: float) -> None:
    summary, detail = _build_cost_closure_analytics(queue, credit_price)
    st.markdown("**Cost Action Closure**")
    defer_source_note(
        "Optimization impact remains estimated until the action is fixed and later telemetry shows the signal improved."
    )
    render_shell_snapshot((
        ("Cost Actions", f"{summary['cost_actions']:,}"),
        ("Open Est. Savings", f"${summary['open_estimated_monthly_savings']:,.0f}/mo"),
        ("Blocked Est. Savings", f"${summary['blocked_estimated_monthly_savings']:,.0f}/mo"),
        ("Measured Impact", f"${summary['verified_period_delta_dollars']:,.0f}"),
        ("Closed With Telemetry", f"{summary['audit_ready_pct']:,.1f}%"),
    ))

    if detail.empty:
        st.info("No cost-control or chargeback actions are currently visible in the loaded action queue scope.")
        return

    render_priority_dataframe(
        detail,
        title="Cost actions that still need review, telemetry, or closure status",
        priority_columns=[
            "SEVERITY", "CLOSURE_STATE", "CATEGORY", "ENTITY_NAME", "OWNER",
            "OWNER_EMAIL", "ONCALL_PRIMARY", "APPROVAL_GROUP", "OWNER_SOURCE",
            "STATUS", "OWNER_APPROVAL_STATUS", "TELEMETRY_STATUS",
            "BASELINE_VALUE", "CURRENT_VALUE", "MEASURED_DELTA",
            "MEASURED_IMPACT_DOLLARS", "RECOVERY_SLA_STATE",
            "IMPACT_EVIDENCE", "TICKET_ID", "APPROVER",
        ],
        sort_by=["QUEUE_PRIORITY", "SEVERITY"],
        ascending=[True, True],
        raw_label="All loaded cost closure rows",
        height=260,
        max_rows=10,
    )


def _render_cost_advisor_detail(board: pd.DataFrame | None) -> None:
    options = _cost_advisor_detail_options(board)
    if options.empty:
        return
    st.markdown("**Open Cost Advisor Finding**")
    selected_label = st.selectbox(
        "Advisor finding",
        options["DETAIL_LABEL"].tolist(),
        key="cost_advisor_detail_select",
    )
    selected = options[options["DETAIL_LABEL"].eq(selected_label)]
    if selected.empty:
        return
    row = selected.iloc[0]
    render_shell_snapshot((
        ("Priority", str(row.get("SEVERITY") or row.get("PRIORITY") or "Review")),
        ("Action", str(row.get("ACTION_TYPE") or "Investigate")),
        ("Route", LEGACY_COST_WORKFLOW_ALIASES.get(str(row.get("WORKFLOW_ROUTE") or ""), str(row.get("WORKFLOW_ROUTE") or "Cost Recommendations"))),
        ("Metric", str(row.get("PRIMARY_METRIC") or "")),
    ))
    st.caption(_clean_display_text(str(row.get("TELEMETRY_SUMMARY") or row.get("EVIDENCE") or "")))
    render_escaped_labeled_text("Next move", row.get("SAFE_NEXT_ACTION") or "Review the loaded telemetry.")
    render_escaped_labeled_text(
        "Proof",
        row.get("VALIDATION_NEEDED") or row.get("PROOF_REQUIRED") or "Confirm in the next completed telemetry window.",
    )
    do_not_do = str(row.get("DO_NOT_DO") or "").strip()
    if do_not_do:
        st.caption(f"Guardrail: {_clean_display_text(do_not_do)}")
    route = str(row.get("WORKFLOW_ROUTE") or "").strip()
    if route in WORKFLOWS and st.button(f"Open {route}", key="cost_advisor_detail_route", width="stretch"):
        set_state("cost_contract_workflow", route)
        st.rerun()


def _render_cost_advisor_board(
    *,
    efficiency_summary: pd.DataFrame,
    warehouse_efficiency: pd.DataFrame,
    clustering_cost: pd.DataFrame,
    reconciliation: pd.DataFrame,
    service_lens: pd.DataFrame,
    credit_price: float,
    days: int,
    storage_table_metrics: pd.DataFrame | None = None,
    storage_db_detail: pd.DataFrame | None = None,
    storage_cost_per_tb: float | None = None,
) -> None:
    summary, board = _build_cost_advisor_board(
        efficiency_summary=efficiency_summary,
        warehouse_efficiency=warehouse_efficiency,
        clustering_cost=clustering_cost,
        reconciliation=reconciliation,
        service_lens=service_lens,
        credit_price=credit_price,
        days=days,
        storage_table_metrics=storage_table_metrics,
        storage_db_detail=storage_db_detail,
        storage_cost_per_tb=storage_cost_per_tb,
    )
    st.session_state["cost_contract_cost_advisor_summary"] = summary
    st.session_state["cost_contract_cost_advisor_board"] = board
    if board.empty:
        return
    st.markdown("**Cost Advisor**")
    render_shell_snapshot((
        ("Findings", f"{summary['findings']:,}"),
        ("High Priority", f"{summary['high']:,}"),
        ("Est. Savings / Mo", f"${safe_float(summary.get('estimated_monthly_savings')):,.0f}"),
        ("Value at Risk", f"${safe_float(summary.get('estimated_monthly_impact')):,.0f}"),
    ))
    st.caption(
        "Advisor findings are conservative and telemetry-backed. Savings are estimates; pressure and attribution rows are investigation/value-at-risk signals."
    )
    action_summary = _cost_advisor_action_summary(board)
    if not action_summary.empty:
        render_priority_dataframe(
            action_summary,
            title="Cost advisor action rollup",
            priority_columns=[
                "TOP_PRIORITY", "ACTION_TYPE", "WORKFLOW_ROUTE", "FINDINGS", "HIGH_FINDINGS",
                "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD", "NEXT_MOVE",
            ],
            sort_by=["TOP_PRIORITY", "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD"],
            ascending=[True, False, False],
            raw_label="All cost advisor action groups",
            height=260,
            max_rows=8,
        )
    _render_cost_advisor_category_chart(board)
    render_priority_dataframe(
        board,
        title="Ranked cost advisor findings",
            priority_columns=[
                "SEVERITY", "ACTION_TYPE", "WORKFLOW_ROUTE", "CATEGORY", "ENTITY", "EXECUTION_MODE", "PRIMARY_METRIC",
                "ESTIMATE_TYPE",
                "EST_MONTHLY_SAVINGS_USD", "VALUE_AT_RISK_USD", "EST_MONTHLY_IMPACT_USD",
                "QUEUE_PRESSURE_SECONDS", "REMOTE_SPILL_BYTES", "LOCAL_SPILL_BYTES", "SAVINGS_ESTIMATE_STATUS",
                "TELEMETRY_SUMMARY", "SAFE_NEXT_ACTION", "VALIDATION_NEEDED", "DO_NOT_DO", "CONFIDENCE",
            ],
        sort_by=["SEVERITY", "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD"],
        ascending=[True, False, False],
        raw_label="All cost advisor findings",
        height=340,
        max_rows=12,
    )
    _render_cost_advisor_detail(board)


def _render_account_service_cost_lens(service_lens: pd.DataFrame, credit_price: float, error: str = "") -> None:
    if error:
        st.caption(f"Account service-cost lens unavailable: {error}")
        return
    if service_lens is None or getattr(service_lens, "empty", True):
        return
    summary = _build_service_cost_lens_summary(service_lens)
    st.markdown("**Account Service Cost Lens**")
    metrics = [
        {"label": "Total Credits", "value": f"{summary['total_credits']:,.2f}"},
        {
            "label": "Non-Warehouse Credits",
            "value": f"{summary['non_warehouse_credits']:,.2f}",
            "delta_color": "inverse",
        },
    ]
    if safe_float(summary.get("ai_credits")) >= 0.005:
        metrics.append({
            "label": "AI / Cortex Credits",
            "value": f"{summary['ai_credits']:,.2f}",
            "delta_color": "inverse",
        })
    if safe_float(summary.get("serverless_credits")) >= 0.005:
        metrics.append({
            "label": "Serverless Credits",
            "value": f"{summary['serverless_credits']:,.2f}",
            "delta_color": "inverse",
        })
    if safe_float(summary.get("top_moving_delta")):
        mover = str(summary.get("top_moving_service") or "No movement")
        metrics.append({
            "label": "Top Service Move",
            "value": mover if len(mover) <= 24 else mover[:21] + "...",
            "delta": f"{safe_float(summary.get('top_moving_delta')):+,.2f} cr",
            "delta_color": "inverse",
        })
    _render_metric_items(metrics)
    st.caption(
        f"Top service: {summary['top_service']}. "
        f"Official Cost Monitor formula: METERING_HISTORY total credits through the completed 24-hour window, "
        f"with Snowflake services at ${credit_price:,.2f}/credit and Cortex/AI at ${get_current_ai_credit_price():,.2f}/AI credit."
    )
    _render_cost_chart_with_data_toggle(
        "Service Spend Movement",
        "cost_contract_service_movement",
        lambda: _render_service_cost_movement_chart(service_lens, credit_price),
        _service_lens_movement_rows(service_lens, credit_price, limit=16),
        priority_columns=[
            "SERVICE_CATEGORY", "SERVICE_TYPE", "CURRENT_SPEND_USD",
            "PRIOR_SPEND_USD", "COST_DELTA_USD", "CREDIT_DELTA",
        ],
        sort_by=["COST_DELTA_USD"],
        max_rows=16,
    )
    render_priority_dataframe(
        service_lens,
        title="Cost by Snowflake service type",
        priority_columns=[
            "SERVICE_CATEGORY", "SERVICE_TYPE", "CREDITS_BILLED", "ESTIMATED_COST_USD",
            "CREDITS_BILLED_PRIOR", "CREDIT_DELTA", "COST_DELTA_USD", "PCT_DELTA",
            "CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES", "OBSERVED_DAYS",
        ],
        sort_by=["CREDITS_BILLED"],
        ascending=[False],
        raw_label="All service-cost lens rows",
        height=280,
        max_rows=10,
    )


def _render_cost_efficiency_rca(
    efficiency_summary: pd.DataFrame,
    warehouse_efficiency: pd.DataFrame,
    clustering_cost: pd.DataFrame,
    credit_price: float,
    errors: dict | None = None,
) -> None:
    errors = errors or {}
    loaded_any = any(
        isinstance(frame, pd.DataFrame) and not frame.empty
        for frame in (efficiency_summary, warehouse_efficiency, clustering_cost)
    )
    if not loaded_any:
        for label, err in errors.items():
            if err:
                st.caption(f"{label} unavailable: {err}")
        return

    st.markdown("**Cost Efficiency RCA**")
    if isinstance(efficiency_summary, pd.DataFrame) and not efficiency_summary.empty:
        row = efficiency_summary.iloc[0]
        render_shell_snapshot((
            ("Cost / Query", f"${safe_float(row.get('COST_PER_QUERY_USD')):,.4f}"),
            ("Cost / TB", f"${safe_float(row.get('COST_PER_TB_USD')):,.2f}"),
            ("Failed Waste", f"${safe_float(row.get('FAILED_QUERY_WASTE_USD')):,.0f}"),
            ("Avg Cache", f"{safe_float(row.get('AVG_CACHE_PCT')):,.1f}%"),
        ))
        st.caption(
            f"{safe_int(row.get('QUERY_COUNT')):,} query rows, "
            f"{safe_float(row.get('TB_SCANNED')):,.2f} TB scanned, "
            f"{safe_int(row.get('FAILED_QUERIES')):,} failed query rows. "
            f"{str(row.get('ATTRIBUTION_SOURCE') or 'OVERWATCH allocated fallback')}"
        )

    if isinstance(warehouse_efficiency, pd.DataFrame) and not warehouse_efficiency.empty:
        render_priority_dataframe(
            warehouse_efficiency,
            title="Warehouse efficiency and pressure",
            priority_columns=[
                "WAREHOUSE_NAME", "COST_USD", "QUERY_COUNT", "COST_PER_QUERY_USD",
                "COST_PER_TB_USD", "CREDITS_PER_EXEC_HOUR", "QUEUE_SECONDS",
                "REMOTE_SPILL_GB", "FAILED_QUERIES", "FAILED_QUERY_WASTE_USD",
                "AVG_CACHE_PCT",
            ],
            sort_by=["FAILED_QUERY_WASTE_USD", "REMOTE_SPILL_GB", "COST_USD"],
            ascending=[False, False, False],
            raw_label="All warehouse efficiency rows",
            height=300,
            max_rows=12,
        )

    if isinstance(clustering_cost, pd.DataFrame) and not clustering_cost.empty:
        total_clustering = safe_float(clustering_cost.get("CLUSTERING_COST_USD", pd.Series(dtype=float)).sum())
        st.caption(f"Automatic clustering cost loaded: ${total_clustering:,.0f} in the selected window.")
        render_priority_dataframe(
            clustering_cost,
            title="Automatic clustering cost and churn",
            priority_columns=[
                "TABLE_NAME", "CLUSTERING_COST_USD", "CLUSTERING_CREDITS",
                "TB_RECLUSTERED", "ROWS_RECLUSTERED", "COST_PER_TB_RECLUSTERED",
            ],
            sort_by=["CLUSTERING_COST_USD", "COST_PER_TB_RECLUSTERED"],
            ascending=[False, False],
            raw_label="All clustering cost rows",
            height=260,
            max_rows=10,
        )

    for label, err in errors.items():
        if err:
            st.caption(f"{label} unavailable: {err}")
    defer_source_note(
        "Cost efficiency RCA uses completed ACCOUNT_USAGE windows and query-attribution fallback where official query attribution is unavailable."
    )
