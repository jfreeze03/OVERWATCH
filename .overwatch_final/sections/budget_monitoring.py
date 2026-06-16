# sections/budget_monitoring.py - Snowflake budget and AI quota monitoring
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.shell_helpers import render_shell_snapshot
from utils import run_query, format_snowflake_error
from utils.workflows import (
    add_cost_companion_columns,
    apply_operator_status_labels,
    prioritize_context_columns,
    render_operator_briefing,
    render_priority_dataframe,
    render_signal_confidence,
)


BUDGET_MONITORING_VERSION = "2026-06-15-budget-monitoring-v1"


BUDGET_MONITORING_SIGNALS = (
    {
        "CAPABILITY": "Account Budget Tracking",
        "STATE": "Tracked",
        "OVERWATCH_SIGNAL": "Account spend threshold activity, monthly burn, and renewal exposure route into Cost & Contract.",
        "SNOWFLAKE_SOURCE": "SNOWFLAKE.LOCAL.ACCOUNT_ROOT_BUDGET and spending history.",
        "OPERATING_NOTE": "Use threshold movement to explain current run rate and forecast pressure.",
        "WATCH_NEXT": "Budget threshold movement, current spend, rolling burn, and forecast variance.",
        "WEIGHT": 20,
    },
    {
        "CAPABILITY": "Cortex AI Spend",
        "STATE": "Tracked",
        "OVERWATCH_SIGNAL": "Cortex dollar movement, heavy AI users, and monthly AI burn surface in the executive wall.",
        "SNOWFLAKE_SOURCE": "Cortex AI usage history and AI cost facts.",
        "OPERATING_NOTE": "Treat AI usage spikes as cost incidents when they move materially against trend.",
        "WATCH_NEXT": "Cortex dollars, request volume, user concentration, and service mix.",
        "WEIGHT": 20,
    },
    {
        "CAPABILITY": "User Quota Pressure",
        "STATE": "Monitoring Pattern",
        "OVERWATCH_SIGNAL": "Per-user AI quota pressure is reported as a signal, not as an access-change workflow.",
        "SNOWFLAKE_SOURCE": "Cortex usage by user and monthly quota reference data when available.",
        "OPERATING_NOTE": "Use the signal to route review; this page does not change user access.",
        "WATCH_NEXT": "Users near quota, over quota, newly active, or concentrated in one AI source.",
        "WEIGHT": 16,
    },
    {
        "CAPABILITY": "Shared Resource Budgets",
        "STATE": "Tracked",
        "OVERWATCH_SIGNAL": "Shared AI resource budgets show whether pooled Cortex services are consuming budget faster than expected.",
        "SNOWFLAKE_SOURCE": "Budget shared resources, spend history, and Cortex service usage.",
        "OPERATING_NOTE": "Separate shared AI pressure from warehouse compute pressure before escalating.",
        "WATCH_NEXT": "AI FUNCTION, CORTEX CODE, CORTEX AGENT, and SNOWFLAKE INTELLIGENCE movement.",
        "WEIGHT": 16,
    },
    {
        "CAPABILITY": "Budget Incident Feed",
        "STATE": "Tracked",
        "OVERWATCH_SIGNAL": "Budget threshold events feed Alert Center and Cost & Contract incident context.",
        "SNOWFLAKE_SOURCE": "Budget notifications and action queue telemetry.",
        "OPERATING_NOTE": "Incidents should explain demand, cost driver, service family, and current forecast.",
        "WATCH_NEXT": "Projected threshold, actual threshold, repeated threshold, and unresolved cost incidents.",
        "WEIGHT": 16,
    },
    {
        "CAPABILITY": "Anomaly Explanation",
        "STATE": "Partial",
        "OVERWATCH_SIGNAL": "Budget movement is joined to warehouse, query, task, procedure, and Cortex facts where available.",
        "SNOWFLAKE_SOURCE": "Cost Explorer, query history marts, warehouse meter facts, and Cortex facts.",
        "OPERATING_NOTE": "Explanation quality depends on telemetry coverage for the active time window.",
        "WATCH_NEXT": "Missing cost driver, unknown service family, unexplained spike, and stale telemetry.",
        "WEIGHT": 12,
    },
)


def _budget_monitoring_score(board: pd.DataFrame) -> dict:
    if board is None or board.empty:
        return {"score": 0, "ready": 0, "pattern": 0, "partial": 0, "gap": 0}

    weights = pd.to_numeric(board.get("WEIGHT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    total_weight = max(float(weights.sum()), 1.0)
    state_score = {
        "TRACKED": 1.0,
        "MONITORING PATTERN": 0.78,
        "PARTIAL": 0.55,
        "GAP": 0.0,
    }
    states = board.get("STATE", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
    score = int(round(sum(weights.iloc[idx] * state_score.get(states.iloc[idx], 0.35) for idx in range(len(board))) / total_weight * 100))
    return {
        "score": max(0, min(100, score)),
        "ready": int(states.eq("TRACKED").sum()),
        "pattern": int(states.eq("MONITORING PATTERN").sum()),
        "partial": int(states.eq("PARTIAL").sum()),
        "gap": int(states.eq("GAP").sum()),
    }


def _build_budget_monitoring_board() -> tuple[dict, pd.DataFrame]:
    board = pd.DataFrame(BUDGET_MONITORING_SIGNALS)
    board["_STATE_RANK"] = board["STATE"].map({
        "Gap": 0,
        "Partial": 1,
        "Monitoring Pattern": 2,
        "Tracked": 3,
    }).fillna(9)
    ordered = board.sort_values(["_STATE_RANK", "CAPABILITY"]).drop(columns=["_STATE_RANK"]).reset_index(drop=True)
    return _budget_monitoring_score(ordered), ordered


def _load_budget_inventory() -> pd.DataFrame:
    return run_query(
        "SELECT SYSTEM$SHOW_BUDGETS_IN_ACCOUNT() AS BUDGETS_IN_ACCOUNT",
        ttl_key="budget_monitoring_inventory",
        tier="recent",
        section="Cost & Contract",
    )


def render() -> None:
    summary, board = _build_budget_monitoring_board()

    render_signal_confidence(
        source="Snowflake Budgets + ACCOUNT_USAGE",
        confidence="monitoring",
        scope_note="Read-only monitor. This page reports budget signals and does not run budget or access changes.",
    )
    render_operator_briefing(
        [
            ("Budget events", "Spend thresholds and budget movement are treated as monitoring signals."),
            ("Cortex dollars", "AI cost is separated from warehouse compute so spikes are easier to explain."),
            ("Quota pressure", "Per-user pressure appears as a review signal, not an in-app access workflow."),
            ("Incident flow", "Budget incidents route to Alert Center and Cost & Contract with cost context."),
        ],
        title="Budget Monitoring Brief",
        columns=4,
    )

    render_shell_snapshot((
        ("Tracked Signals", f"{summary['ready']:,}"),
        ("Patterns", f"{summary['pattern']:,}"),
        ("Partial", f"{summary['partial']:,}"),
        ("Controls", f"{len(board):,}"),
    ))

    render_priority_dataframe(
        board,
        title="Budget monitoring coverage",
        priority_columns=[
            "STATE", "CAPABILITY", "OVERWATCH_SIGNAL", "SNOWFLAKE_SOURCE", "OPERATING_NOTE", "WATCH_NEXT",
        ],
        sort_by=["STATE", "CAPABILITY"],
        ascending=[True, True],
        raw_label="All Budget Monitoring signals",
        max_rows=6,
        height=300,
    )

    with st.expander("Budget inventory telemetry", expanded=False):
        if st.button("Refresh Budget Inventory", key="budget_monitoring_load_inventory"):
            try:
                st.session_state["budget_monitoring_inventory"] = _load_budget_inventory()
                st.session_state["budget_monitoring_inventory_error"] = ""
            except Exception as exc:
                st.session_state["budget_monitoring_inventory"] = pd.DataFrame()
                st.session_state["budget_monitoring_inventory_error"] = format_snowflake_error(exc)

        err = st.session_state.get("budget_monitoring_inventory_error", "")
        if err:
            st.warning(f"Budget inventory unavailable: {err}")

        inventory = st.session_state.get("budget_monitoring_inventory")
        if isinstance(inventory, pd.DataFrame) and not inventory.empty:
            display_inventory = apply_operator_status_labels(
                add_cost_companion_columns(prioritize_context_columns(inventory))
            )
            st.dataframe(display_inventory, width="stretch", hide_index=True)
        else:
            st.caption("Inventory refresh only reads Snowflake budget metadata.")
