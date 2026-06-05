# sections/finops_control.py - Cost/FinOps control center
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import DAY_WINDOW_OPTIONS, DEFAULT_DAY_WINDOW
from utils import (
    build_cost_formula_audit,
    build_schema_migration_contract,
    build_schema_migration_status_sql,
    build_snowflake_cost_management_account_sql,
    credits_to_dollars,
    defer_source_note,
    format_snowflake_error,
    get_active_company,
    get_credit_price,
    get_session_for_action,
    get_wh_filter_clause,
    run_query,
    safe_float,
)
from utils.workflows import render_priority_dataframe


def _resource_monitor_sql() -> str:
    return """
    SELECT
        NAME,
        CREDIT_QUOTA,
        USED_CREDITS,
        REMAINING_CREDITS,
        LEVEL,
        FREQUENCY,
        START_TIME,
        END_TIME
    FROM SNOWFLAKE.ACCOUNT_USAGE.RESOURCE_MONITORS
    ORDER BY USED_CREDITS DESC NULLS LAST
    """


def _finops_readiness_rows(
    cost_parity: pd.DataFrame,
    resource_monitors: pd.DataFrame,
    migration: pd.DataFrame,
    formulas: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    rows.append({
        "CONTROL": "Snowflake Cost Management parity",
        "STATE": "Ready" if isinstance(cost_parity, pd.DataFrame) and not cost_parity.empty else "Load Needed",
        "EVIDENCE": "Account Overview-style warehouse metering loaded." if isinstance(cost_parity, pd.DataFrame) and not cost_parity.empty else "Load cost parity before reconciling leadership screenshots.",
        "NEXT_ACTION": "Use parity for Snowflake UI comparison; use billed-credit/currency views for invoice reconciliation.",
    })
    rows.append({
        "CONTROL": "Resource monitor guardrails",
        "STATE": "Ready" if isinstance(resource_monitors, pd.DataFrame) and not resource_monitors.empty else "Review",
        "EVIDENCE": f"{len(resource_monitors):,} resource monitor row(s) loaded." if isinstance(resource_monitors, pd.DataFrame) else "No monitor evidence loaded.",
        "NEXT_ACTION": "Confirm OVERWATCH_WH_RM and high-spend business warehouses have notify/suspend thresholds.",
    })
    drift = (
        int(migration["MIGRATION_STATE"].astype(str).isin(["Blocked", "Version Drift"]).sum())
        if isinstance(migration, pd.DataFrame) and not migration.empty and "MIGRATION_STATE" in migration.columns
        else 0
    )
    rows.append({
        "CONTROL": "Mart/schema version",
        "STATE": "Ready" if drift == 0 and isinstance(migration, pd.DataFrame) and not migration.empty else "Blocked" if drift else "Load Needed",
        "EVIDENCE": f"{drift:,} migration blocker(s)." if isinstance(migration, pd.DataFrame) and not migration.empty else "Migration ledger has not loaded.",
        "NEXT_ACTION": "Rerun setup SQL or additive migrations before trusting scheduled verification.",
    })
    official = (
        formulas["CONFIDENCE"].astype(str).str.contains("Official|Metered", case=False, na=False).sum()
        if isinstance(formulas, pd.DataFrame) and not formulas.empty and "CONFIDENCE" in formulas.columns
        else 0
    )
    rows.append({
        "CONTROL": "Exact vs allocated labels",
        "STATE": "Ready",
        "EVIDENCE": f"{official:,} formula row(s) identify official or metered source basis.",
        "NEXT_ACTION": "Keep chargeback views labeled as allocated unless Snowflake exposes exact billing grain.",
    })
    return pd.DataFrame(rows)


def render() -> None:
    company = get_active_company()
    credit_price = safe_float(get_credit_price()) or 3.68
    st.caption("FinOps control surface for parity, guardrails, verified savings, and formula trust.")
    defer_source_note(
        "FinOps Control Center uses Snowflake Cost Management parity sources where available and keeps ALFA's configured $3.68 compute credit rate."
    )

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        days = st.selectbox(
            "FinOps window",
            DAY_WINDOW_OPTIONS,
            index=DAY_WINDOW_OPTIONS.index(DEFAULT_DAY_WINDOW),
            format_func=lambda value: f"{value} days",
        )
    with c2:
        if st.button("Load FinOps Controls", key="finops_control_load", type="primary", width="stretch"):
            session = get_session_for_action(
                "load FinOps controls",
                surface="Cost & Contract",
                offline_note="FinOps shell and formula trust remain visible without Snowflake.",
            )
            if session is not None:
                state = {"errors": []}
                try:
                    state["cost_parity"] = run_query(
                        build_snowflake_cost_management_account_sql(
                            int(days),
                            credit_price,
                            get_wh_filter_clause("warehouse_name", company),
                        ),
                        ttl_key=f"finops_cost_parity_{company}_{days}",
                        tier="historical",
                        section="Cost & Contract",
                    )
                except Exception as exc:
                    state["cost_parity"] = pd.DataFrame()
                    state["errors"].append(f"Cost Management parity unavailable: {format_snowflake_error(exc)}")
                try:
                    state["resource_monitors"] = run_query(
                        _resource_monitor_sql(),
                        ttl_key="finops_resource_monitors",
                        tier="recent",
                        section="Cost & Contract",
                    )
                except Exception as exc:
                    state["resource_monitors"] = pd.DataFrame()
                    state["errors"].append(f"Resource monitor evidence unavailable: {format_snowflake_error(exc)}")
                try:
                    state["migration"] = run_query(
                        build_schema_migration_status_sql(),
                        ttl_key="finops_migration_status",
                        tier="recent",
                        section="Cost & Contract",
                    )
                except Exception as exc:
                    state["migration"] = pd.DataFrame()
                    state["errors"].append(f"Migration ledger unavailable: {format_snowflake_error(exc)}")
                st.session_state["finops_control_state"] = state
    with c3:
        st.info("Use this before budget changes, contract conversations, or claiming verified savings.")

    formulas = build_cost_formula_audit()
    state = st.session_state.get("finops_control_state", {})
    if isinstance(state, dict):
        for error in state.get("errors", []):
            defer_source_note(error)
    cost_parity = state.get("cost_parity", pd.DataFrame()) if isinstance(state, dict) else pd.DataFrame()
    resource_monitors = state.get("resource_monitors", pd.DataFrame()) if isinstance(state, dict) else pd.DataFrame()
    migration = state.get("migration", pd.DataFrame()) if isinstance(state, dict) else pd.DataFrame()

    render_priority_dataframe(
        _finops_readiness_rows(cost_parity, resource_monitors, migration, formulas),
        title="FinOps controls to verify first",
        priority_columns=["CONTROL", "STATE", "EVIDENCE", "NEXT_ACTION"],
        sort_by=["STATE", "CONTROL"],
        ascending=[True, True],
        raw_label="All FinOps control rows",
        height=230,
    )

    if isinstance(cost_parity, pd.DataFrame) and not cost_parity.empty:
        total_credits = safe_float(cost_parity.get("SPEND_IN_CREDITS", pd.Series(dtype=float)).sum())
        total_cost = credits_to_dollars(total_credits, credit_price)
        m1, m2, m3 = st.columns(3)
        m1.metric("Parity Credits", f"{total_credits:,.2f}")
        m2.metric("Estimated Cost", f"${total_cost:,.0f}")
        m3.metric("Active Warehouses", f"{safe_float(cost_parity.get('ACTIVE_WAREHOUSES', pd.Series(dtype=float)).sum()):,.0f}")
        render_priority_dataframe(
            cost_parity,
            title="Snowflake Cost Management parity evidence",
            priority_columns=[
                "SPEND_IN_CREDITS", "COMPUTE_CREDITS", "CLOUD_SERVICES_CREDITS",
                "SPEND_IN_CURRENCY_EST_USD", "COMPUTE_PRICE_PER_CREDIT_USD",
                "AVERAGE_DAILY_CREDITS", "AVERAGE_DAILY_COST_EST_USD",
                "ACTIVE_WAREHOUSES", "OBSERVED_DAYS", "SNOWFLAKE_SOURCE",
                "TOP_WAREHOUSES_BY_COST",
            ],
            sort_by=["SPEND_IN_CREDITS"],
            ascending=False,
            raw_label="All cost parity rows",
            height=280,
        )

    if isinstance(resource_monitors, pd.DataFrame) and not resource_monitors.empty:
        render_priority_dataframe(
            resource_monitors,
            title="Resource monitor guardrails",
            priority_columns=["NAME", "CREDIT_QUOTA", "USED_CREDITS", "REMAINING_CREDITS", "LEVEL", "FREQUENCY"],
            sort_by=["USED_CREDITS"],
            ascending=False,
            raw_label="All resource monitors",
            height=240,
        )

    render_priority_dataframe(
        build_schema_migration_contract(),
        title="FinOps setup contract",
        priority_columns=["COMPONENT", "REQUIRED_OBJECT", "REQUIRED_VERSION", "READY_CRITERIA"],
        raw_label="All setup contract rows",
        height=240,
    )
