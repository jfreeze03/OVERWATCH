"""Cost & Contract render panels backed by cost-intelligence boards."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.cost_contract_advisor import _build_attribution_gap_summary
from sections.cost_contract_intelligence import (
    _build_cost_allocation_trust_board,
    _build_cost_control_coverage_board,
    _build_cost_decomposition_board,
    _build_cost_drilldown_command_map,
    _build_cost_source_health_board,
)
from sections.shell_helpers import render_shell_snapshot
from utils.workflows import render_priority_dataframe


def _render_cost_source_health(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    attribution: pd.DataFrame,
    service_lens: pd.DataFrame,
) -> None:
    summary, board = _build_cost_source_health_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        attribution=attribution,
        service_lens=service_lens,
    )
    if board.empty:
        return
    st.markdown("**Cost Data Health**")
    render_shell_snapshot((
        ("Ready Inputs", f"{summary['ready']:,}"),
        ("Review / On Demand", f"{summary['review']:,}"),
        ("Unavailable", f"{summary['unavailable']:,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost data health",
        priority_columns=["STATE", "SOURCE", "SCOPE", "ROWS_LOADED", "FRESHNESS", "EVIDENCE", "NEXT_ACTION"],
        sort_by=["STATE", "SOURCE"],
        ascending=[True, True],
        raw_label="All cost data-health rows",
        height=260,
        max_rows=8,
    )


def _render_query_attribution_gap(reconciliation: pd.DataFrame, credit_price: float, error: str = "") -> None:
    if error:
        st.caption(f"Query attribution gap unavailable: {error}")
        return
    if reconciliation is None or getattr(reconciliation, "empty", True):
        return
    summary = _build_attribution_gap_summary(reconciliation, credit_price)
    st.markdown("**Query Attribution Gap**")
    render_shell_snapshot((
        ("Metered Credits", f"{summary['exact_credits']:,.2f}"),
        ("Query-Attributed", f"{summary['query_credits']:,.2f}"),
        ("Unallocated / Idle Gap", f"{summary['gap_credits']:,.2f} ({summary['gap_pct']:+.1f}%)"),
        ("Gap Dollars", f"${summary['gap_usd']:,.0f}"),
    ))
    st.caption(
        f"Top gap warehouse: {summary['top_gap_warehouse']}. "
        "Query attribution is execution-only; idle, serverless, storage, data transfer, cloud services, and AI token costs remain outside query-level attribution."
    )
    render_priority_dataframe(
        reconciliation,
        title="Warehouse metering to query attribution reconciliation",
        priority_columns=[
            "RECONCILIATION_STATUS", "WAREHOUSE_NAME", "USAGE_DAY", "EXACT_METERED_CREDITS",
            "ALLOCATED_QUERY_CREDITS", "OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS",
            "VARIANCE_CREDITS", "VARIANCE_PCT", "ATTRIBUTION_SOURCE",
        ],
        sort_by=["VARIANCE_CREDITS"],
        ascending=[False],
        raw_label="All query attribution reconciliation rows",
        height=280,
        max_rows=8,
    )


def _render_cost_control_coverage_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    summary, board = _build_cost_control_coverage_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
    )
    if board.empty:
        return
    st.markdown("**Cost Control Coverage**")
    render_shell_snapshot((
        ("Ready", f"{summary['ready']:,}"),
        ("Review", f"{summary['review']:,}"),
        ("Load Needed", f"{summary['load_needed']:,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost telemetry coverage",
        priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
        sort_by=["STATE", "CONTROL"],
        ascending=[True, True],
        raw_label="All cost control coverage rows",
        max_rows=12,
    )


def _render_cost_allocation_trust_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    summary, board = _build_cost_allocation_trust_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
    )
    if board.empty:
        return
    st.markdown("**Cost Allocation Trust**")
    render_shell_snapshot((
        ("Exact / Ready", f"{summary['exact']:,}"),
        ("Allocated / Estimated", f"{summary['estimated']:,}"),
        ("Review / Load", f"{summary['review'] + summary['load_needed']:,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost attribution trust states",
        priority_columns=["TRUST_STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
        sort_by=["TRUST_STATE", "CONTROL"],
        ascending=[True, True],
        raw_label="All cost allocation trust rows",
        max_rows=10,
    )


def _render_cost_drilldown_command_map(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    summary, board = _build_cost_drilldown_command_map(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
    )
    if board.empty:
        return
    st.markdown("**Cost Drilldown Status**")
    render_shell_snapshot((
        ("Ready", f"{summary['ready']:,}"),
        ("Review", f"{summary['review']:,}"),
        ("Load Needed", f"{summary['load_needed']:,}"),
        ("Allocated", f"{summary['estimated']:,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost drilldowns to trust or load next",
        priority_columns=[
            "COMMAND_PRIORITY", "STATE", "DRILLDOWN", "TRUST", "ROWS_LOADED", "PRIMARY_METRIC",
            "NEXT_ACTION", "WORKFLOW",
        ],
        sort_by=["COMMAND_PRIORITY", "DRILLDOWN"],
        ascending=[True, True],
        raw_label="All cost drilldown status rows",
        height=280,
        max_rows=10,
    )


def _render_cost_decomposition_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    summary, board = _build_cost_decomposition_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
    )
    if board.empty:
        return
    st.markdown("**Cost Decomposition**")
    render_shell_snapshot((
        ("Ready", f"{summary['ready']:,}"),
        ("Review", f"{summary['review']:,}"),
        ("Drivers", f"{len(board):,}"),
    ))
    render_priority_dataframe(
        board,
        title="Cost decomposition and next trust step",
        priority_columns=["STATUS", "DRIVER", "TRUST", "EVIDENCE", "NEXT_ACTION"],
        sort_by=["STATUS", "DRIVER"],
        ascending=[True, True],
        raw_label="All cost decomposition rows",
        max_rows=10,
    )
