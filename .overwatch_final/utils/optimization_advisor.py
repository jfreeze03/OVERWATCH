# utils/optimization_advisor.py - Warehouse Health optimization advisor UI helper
import pandas as pd
import streamlit as st

from config import THRESHOLDS, WAREHOUSE_ADVISOR_CONFIG
from runtime_state import get_state, set_state
from sections.shell_helpers import render_shell_snapshot

from .company_filter import get_active_company
from .cost import (
    credits_to_dollars,
    format_credits,
    get_credit_price,
    metric_confidence_label,
)
from .display import day_window_selectbox, download_csv, render_drillable_bar_chart
from .helpers import safe_float
from .recommendation_intelligence import duplicate_query_decision, harden_recommendation, warehouse_sizing_decision
from .query import format_snowflake_error
from .session import get_session
from .shared_metrics import (
    load_shared_duplicate_query_patterns,
    load_shared_recommendation_idle_warehouses,
    load_shared_warehouse_right_sizing,
)
from .workflows import render_priority_dataframe, render_workflow_selector


OPTIMIZATION_ADVISOR_PANES = (
    "Idle Warehouse Costs",
    "Duplicate Queries",
    "Right-Sizing Advisor",
)


def _monthly_idle_savings_usd(idle_credits: object, days: int, credit_price: float) -> float:
    lookback_days = max(1, int(days or 7))
    return round(credits_to_dollars(safe_float(idle_credits) / lookback_days * 30, credit_price), 2)


def _right_size_monthly_savings_usd(row, days: int, credit_price: float) -> float:
    if not _right_size_savings_candidate(row, days, credit_price):
        return 0.0
    monthly_run_rate = _right_size_monthly_run_rate_usd(row, days, credit_price)
    return round(monthly_run_rate * safe_float(WAREHOUSE_ADVISOR_CONFIG.get("downsize_recoverable_rate"), 0.40), 2)


def _right_size_lookback_days(row, days: int) -> int:
    value = row.get("LOOKBACK_DAYS", row.get("WINDOW_DAYS", row.get("DAYS", days))) if hasattr(row, "get") else days
    return max(1, int(safe_float(value, days or 14) or days or 14))


def _right_size_monthly_run_rate_usd(row, days: int, credit_price: float) -> float:
    lookback_days = _right_size_lookback_days(row, days)
    monthly_credits = safe_float(row.get("TOTAL_CREDITS", 0)) / lookback_days * 30
    return credits_to_dollars(monthly_credits, credit_price)


def _right_size_savings_candidate(row, days: int, credit_price: float) -> bool:
    decision = str(row.get("DECISION", "") or "").lower()
    if "downsize candidate" in decision:
        return True
    size = str(row.get("WAREHOUSE_SIZE", "") or "").upper().replace("-", "").replace(" ", "")
    if size in {"", "XSMALL", "UNKNOWN", "UNKNOWNSIZE"}:
        return False
    if safe_float(row.get("TOTAL_QUERIES", 0)) <= 0:
        return False
    if safe_float(row.get("AVG_QUEUE_SEC", 0)) > safe_float(WAREHOUSE_ADVISOR_CONFIG.get("downsize_max_queue_sec"), 1.0):
        return False
    if safe_float(row.get("REMOTE_SPILL_GB", 0)) > safe_float(WAREHOUSE_ADVISOR_CONFIG.get("downsize_max_spill_gb"), 1.0):
        return False
    return _right_size_monthly_run_rate_usd(row, days, credit_price) >= safe_float(
        WAREHOUSE_ADVISOR_CONFIG.get("downsize_min_monthly_usd"),
        100.0,
    )


def _right_size_recommendation_message(row) -> str:
    savings = safe_float(row.get("EST_MONTHLY_SAVINGS_USD"))
    run_rate = safe_float(row.get("EST_MONTHLY_RUN_RATE_USD"))
    spill = safe_float(row.get("REMOTE_SPILL_GB"))
    queue = safe_float(row.get("AVG_QUEUE_SEC"))
    credits = safe_float(row.get("TOTAL_CREDITS"))
    decision = str(row.get("DECISION", "Review warehouse sizing"))
    value_phrase = (
        f"Estimated savings: ${savings:,.0f}/mo"
        if savings > 0
        else f"Monthly run-rate: ${run_rate:,.0f}"
    )
    return (
        f"**{row.get('WAREHOUSE_NAME', '')}**: {decision}. {value_phrase}; "
        f"remote spill: {spill:,.2f} GB; avg queue: {queue:,.2f}s; window credits: {credits:,.2f}. "
        f"{row.get('SAFE_NEXT_ACTION', '')} Proof: {row.get('PROOF_REQUIRED', '')}"
    )


def _advisor_value_type(row) -> str:
    savings = safe_float(row.get("EST_MONTHLY_SAVINGS_USD", 0))
    decision = str(row.get("DECISION", "") or "")
    if savings > 0:
        return "Estimated savings"
    if "incident" in decision.lower() or "pressure" in decision.lower() or "spill" in decision.lower():
        return "Reliability / performance"
    return "Review only"


def _idle_warehouse_advisor_decision(row, credit_price: float) -> dict:
    idle_credits = safe_float(row.get("IDLE_CREDITS", 0))
    idle_hours = int(safe_float(row.get("IDLE_HOURS", 0)))
    warehouse = str(row.get("WAREHOUSE_NAME") or "Warehouse")
    monthly_savings = credits_to_dollars(idle_credits / 7 * 30, credit_price)
    hardened = harden_recommendation({
        "Source": "Idle warehouse detector",
        "Severity": "High",
        "Category": "Cost Control",
        "Entity Type": "Warehouse",
        "Entity": warehouse,
        "Route": "Warehouse route / DBA capacity reviewer",
        "Finding": f"{warehouse} idle {idle_hours}h, wasting {format_credits(idle_credits)}",
        "Action": f"Reduce AUTO_SUSPEND to <= {THRESHOLDS['idle_warehouse_minutes']} minutes",
        "Idle Hours": idle_hours,
        "Estimated Monthly Savings": round(monthly_savings, 2),
        "Baseline Value": round(idle_credits, 4),
        "Current Value": round(idle_credits, 4),
    })
    return {
        "DECISION": hardened["Decision"],
        "EVIDENCE_PACKET": hardened["Evidence Packet"],
        "SAFE_NEXT_ACTION": hardened["Safe Next Action"],
        "APPROVAL_GATE": hardened["APPROVAL_GATE"],
        "EVIDENCE_PACKAGE": hardened["EVIDENCE_PACKAGE"],
        "VERIFY_NEXT": hardened["VERIFY_NEXT"],
        "EXECUTION_BOUNDARY": hardened["EXECUTION_BOUNDARY"],
        "CLOSURE_RULE": hardened["CLOSURE_RULE"],
        "PROOF_REQUIRED": hardened["Proof Required"],
        "DO_NOT_DO": hardened["Do Not Do"],
    }


def render_optimization_advisor():
    credit_price = get_credit_price()
    company = get_active_company()

    active_view = render_workflow_selector(
        "Optimization advisor view",
        "optimization_advisor_active_view",
        OPTIMIZATION_ADVISOR_PANES,
        columns=3,
        show_label=True,
    )

    if active_view == "Idle Warehouse Costs":
        st.subheader("Idle Warehouse Cost Detection")
        st.caption("Identifies credit spend during hours with zero query activity.")
        idle_days = day_window_selectbox("Lookback", key="idle_days", default=7)

        if st.button("Find Idle Credits", key="idle_load"):
            try:
                idle_result = load_shared_recommendation_idle_warehouses(
                    company,
                    days=idle_days,
                    min_idle_credits=THRESHOLDS["idle_credit_waste_min"],
                    force=True,
                    section="Warehouse Health",
                )
                set_state("opt_df_idle", idle_result.data)
                set_state("opt_df_idle_source", idle_result.source)
            except Exception as e:
                st.warning(f"Idle warehouse scan unavailable: {format_snowflake_error(e)}")

        opt_df_idle = get_state("opt_df_idle")
        if opt_df_idle is not None and not opt_df_idle.empty:
            df_i = opt_df_idle.copy()
            decision_rows = [_idle_warehouse_advisor_decision(row, credit_price) for _, row in df_i.iterrows()]
            df_i = pd.concat([df_i.reset_index(drop=True), pd.DataFrame(decision_rows)], axis=1)
            df_i["EST_MONTHLY_SAVINGS_USD"] = df_i["IDLE_CREDITS"].apply(
                lambda value: _monthly_idle_savings_usd(value, idle_days, credit_price)
            )
            df_i["VALUE_TYPE"] = "Estimated idle savings"
            total_idle = df_i["IDLE_CREDITS"].sum()
            total_monthly_savings = safe_float(df_i["EST_MONTHLY_SAVINGS_USD"].sum())
            render_shell_snapshot((
                ("Warehouses Wasting", f"{len(df_i):,}"),
                ("Total Idle Credits", format_credits(total_idle)),
                ("7d Idle Cost", f"${credits_to_dollars(total_idle, credit_price):,.2f}"),
                ("Est. Savings / Mo", f"${total_monthly_savings:,.0f}"),
            ))
            source = get_state("opt_df_idle_source") or "Warehouse metering and query telemetry"
            st.caption(f"{source} | {metric_confidence_label('exact')}")
            render_priority_dataframe(
                df_i,
                title="Idle warehouse waste candidates",
                priority_columns=[
                    "DECISION",
                    "EVIDENCE_PACKET",
                    "SAFE_NEXT_ACTION",
                    "APPROVAL_GATE",
                    "EVIDENCE_PACKAGE",
                    "VERIFY_NEXT",
                    "EXECUTION_BOUNDARY",
                    "CLOSURE_RULE",
                    "PROOF_REQUIRED",
                    "DO_NOT_DO",
                    "WAREHOUSE_NAME",
                    "VALUE_TYPE",
                    "EST_MONTHLY_SAVINGS_USD",
                    "IDLE_HOURS",
                    "IDLE_CREDITS",
                    "TOTAL_CREDITS",
                    "QUERY_COUNT",
                    "CONFIDENCE",
                ],
                sort_by=["IDLE_CREDITS", "IDLE_HOURS"],
                ascending=[False, False],
                raw_label="Idle warehouse detail",
            )
            render_drillable_bar_chart(
                df_i,
                dimension="WAREHOUSE_NAME",
                measure="IDLE_CREDITS",
                key="opt_idle_credits",
                drilldown_column="warehouse_name",
                lookback_hours=idle_days * 24,
            )
            for _, row in df_i.iterrows():
                st.warning(
                    f"**{row['WAREHOUSE_NAME']}**: {int(row['IDLE_HOURS'])} idle hours, "
                    f"{format_credits(row['IDLE_CREDITS'])} wasted - "
                    f"{row.get('SAFE_NEXT_ACTION', '')} Boundary: {row.get('EXECUTION_BOUNDARY', '')}"
                )
            download_csv(df_i, "idle_warehouses.csv")
        elif opt_df_idle is not None:
            st.success("No significant idle warehouse credits detected.")

    elif active_view == "Duplicate Queries":
        st.subheader("Duplicate & Redundant Query Detection")
        st.caption(
            "Same query text executed multiple times within a time window - "
            "candidates for result caching or materialization."
        )
        dup_days = day_window_selectbox("Lookback", key="dup_days", default=7)

        if st.button("Find Duplicates", key="dup_load"):
            try:
                session = get_session()
                duplicate_result = load_shared_duplicate_query_patterns(
                    session,
                    company,
                    days=dup_days,
                    min_executions=5,
                    force=True,
                    section="Warehouse Health",
                )
                set_state("opt_df_dup", duplicate_result.data)
                set_state("opt_df_dup_source", duplicate_result.source)
            except Exception as e:
                st.warning(f"Duplicate query analysis unavailable: {format_snowflake_error(e)}")

        opt_df_dup = get_state("opt_df_dup")
        if opt_df_dup is not None and not opt_df_dup.empty:
            df_d = opt_df_dup
            decision_rows = [duplicate_query_decision(row) for _, row in df_d.iterrows()]
            df_d = pd.concat([df_d.reset_index(drop=True), pd.DataFrame(decision_rows)], axis=1)
            render_shell_snapshot((("Duplicate Query Patterns", f"{len(df_d):,}"),))
            st.caption(f"{get_state('opt_df_dup_source', 'Query history')} | {metric_confidence_label('estimated')}")
            render_priority_dataframe(
                df_d,
                title="Duplicate query candidates",
                priority_columns=[
                    "DECISION",
                    "EVIDENCE_PACKET",
                    "SAFE_NEXT_ACTION",
                    "APPROVAL_GATE",
                    "EVIDENCE_PACKAGE",
                    "VERIFY_NEXT",
                    "EXECUTION_BOUNDARY",
                    "CLOSURE_RULE",
                    "PROOF_REQUIRED",
                    "DO_NOT_DO",
                    "QUERY_SIG",
                    "EXECUTION_COUNT",
                    "USER_COUNT",
                    "AVG_ELAPSED_SEC",
                    "TOTAL_WASTED_SEC",
                    "CLOUD_CREDITS",
                ],
                sort_by=["EXECUTION_COUNT", "TOTAL_WASTED_SEC"],
                ascending=[False, False],
                raw_label="Duplicate query detail",
            )
            download_csv(df_d, "duplicate_queries.csv")

    elif active_view == "Right-Sizing Advisor":
        st.subheader("Warehouse Right-Sizing Advisor")
        st.caption("Warehouses with low utilization or persistent spill - downsize or upsize candidates.")
        sz_days = day_window_selectbox("Lookback", key="sz_days", default=14)

        if st.button("Analyze Sizing", key="sz_load"):
            try:
                session = get_session()
                sizing_result = load_shared_warehouse_right_sizing(
                    session,
                    company,
                    days=sz_days,
                    force=True,
                    section="Warehouse Health",
                )
                set_state("opt_df_sz", sizing_result.data)
                set_state("opt_df_sz_source", sizing_result.source)
            except Exception as e:
                st.warning(f"Warehouse recommendation scan unavailable: {format_snowflake_error(e)}")

        opt_df_sz = get_state("opt_df_sz")
        if opt_df_sz is not None and not opt_df_sz.empty:
            df_s = opt_df_sz.copy()
            decision_rows = [warehouse_sizing_decision(row) for _, row in df_s.iterrows()]
            df_s = pd.concat([df_s.reset_index(drop=True), pd.DataFrame(decision_rows)], axis=1)
            df_s["EST_MONTHLY_RUN_RATE_USD"] = df_s.apply(
                lambda row: _right_size_monthly_run_rate_usd(row, sz_days, credit_price),
                axis=1,
            )
            df_s["EST_MONTHLY_SAVINGS_USD"] = df_s.apply(
                lambda row: _right_size_monthly_savings_usd(row, sz_days, credit_price),
                axis=1,
            )
            df_s["VALUE_TYPE"] = df_s.apply(_advisor_value_type, axis=1)
            savings_candidates = int((df_s["EST_MONTHLY_SAVINGS_USD"] > 0).sum())
            monthly_savings = safe_float(df_s["EST_MONTHLY_SAVINGS_USD"].sum())
            reliability_candidates = int(df_s["VALUE_TYPE"].astype(str).str.contains("Reliability", case=False, na=False).sum())
            render_shell_snapshot((
                ("Warehouses Reviewed", f"{len(df_s):,}"),
                ("Savings Candidates", f"{savings_candidates:,}"),
                ("Est. Savings / Mo", f"${monthly_savings:,.0f}"),
                ("Reliability Items", f"{reliability_candidates:,}"),
            ))
            st.caption(f"{get_state('opt_df_sz_source', 'Warehouse telemetry')} | {metric_confidence_label('exact')}")
            render_priority_dataframe(
                df_s,
                title="Right-sizing candidates",
                priority_columns=[
                    "DECISION",
                    "VALUE_TYPE",
                    "EST_MONTHLY_RUN_RATE_USD",
                    "EST_MONTHLY_SAVINGS_USD",
                    "EVIDENCE_PACKET",
                    "SAFE_NEXT_ACTION",
                    "APPROVAL_GATE",
                    "EVIDENCE_PACKAGE",
                    "VERIFY_NEXT",
                    "EXECUTION_BOUNDARY",
                    "CLOSURE_RULE",
                    "PROOF_REQUIRED",
                    "DO_NOT_DO",
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "TOTAL_CREDITS",
                    "TOTAL_QUERIES",
                    "AVG_QUEUE_SEC",
                    "REMOTE_SPILL_GB",
                    "AVG_CACHE_PCT",
                ],
                sort_by=["EST_MONTHLY_SAVINGS_USD", "REMOTE_SPILL_GB", "AVG_QUEUE_SEC", "TOTAL_CREDITS"],
                ascending=[False, False, False, False],
                raw_label="Warehouse sizing detail",
            )

            st.subheader("Recommendations")
            for _, row in df_s.iterrows():
                decision = str(row.get("DECISION", ""))
                if decision == "No sizing change from this evidence":
                    continue
                message = _right_size_recommendation_message(row)
                if "incident" in decision.lower():
                    st.error(message)
                elif "candidate" in decision.lower():
                    st.info(message)
                else:
                    st.warning(message)

            download_csv(df_s, "right_sizing.csv")
