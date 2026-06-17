# utils/optimization_advisor.py - Warehouse Health optimization advisor UI helper
import pandas as pd
import streamlit as st

from config import DEFAULTS, THRESHOLDS
from sections.shell_helpers import render_shell_snapshot

from .company_filter import get_active_company
from .cost import (
    credits_to_dollars,
    format_credits,
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
    session = get_session()
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])
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
                st.session_state["opt_df_idle"] = idle_result.data
                st.session_state["opt_df_idle_source"] = idle_result.source
            except Exception as e:
                st.warning(f"Idle warehouse scan unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("opt_df_idle") is not None and not st.session_state["opt_df_idle"].empty:
            df_i = st.session_state["opt_df_idle"].copy()
            decision_rows = [_idle_warehouse_advisor_decision(row, credit_price) for _, row in df_i.iterrows()]
            df_i = pd.concat([df_i.reset_index(drop=True), pd.DataFrame(decision_rows)], axis=1)
            total_idle = df_i["IDLE_CREDITS"].sum()
            render_shell_snapshot((
                ("Warehouses Wasting", f"{len(df_i):,}"),
                ("Total Idle Credits", format_credits(total_idle)),
                ("Idle Cost", f"${credits_to_dollars(total_idle, credit_price):,.2f}"),
            ))
            source = st.session_state.get("opt_df_idle_source") or "Warehouse metering and query telemetry"
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
        elif st.session_state.get("opt_df_idle") is not None:
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
                duplicate_result = load_shared_duplicate_query_patterns(
                    session,
                    company,
                    days=dup_days,
                    min_executions=5,
                    force=True,
                    section="Warehouse Health",
                )
                st.session_state["opt_df_dup"] = duplicate_result.data
                st.session_state["opt_df_dup_source"] = duplicate_result.source
            except Exception as e:
                st.warning(f"Duplicate query analysis unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("opt_df_dup") is not None and not st.session_state["opt_df_dup"].empty:
            df_d = st.session_state["opt_df_dup"]
            decision_rows = [duplicate_query_decision(row) for _, row in df_d.iterrows()]
            df_d = pd.concat([df_d.reset_index(drop=True), pd.DataFrame(decision_rows)], axis=1)
            render_shell_snapshot((("Duplicate Query Patterns", f"{len(df_d):,}"),))
            st.caption(f"{st.session_state.get('opt_df_dup_source', 'Query history')} | {metric_confidence_label('estimated')}")
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
                sizing_result = load_shared_warehouse_right_sizing(
                    session,
                    company,
                    days=sz_days,
                    force=True,
                    section="Warehouse Health",
                )
                st.session_state["opt_df_sz"] = sizing_result.data
                st.session_state["opt_df_sz_source"] = sizing_result.source
            except Exception as e:
                st.warning(f"Warehouse recommendation scan unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("opt_df_sz") is not None and not st.session_state["opt_df_sz"].empty:
            df_s = st.session_state["opt_df_sz"].copy()
            decision_rows = [warehouse_sizing_decision(row) for _, row in df_s.iterrows()]
            df_s = pd.concat([df_s.reset_index(drop=True), pd.DataFrame(decision_rows)], axis=1)
            st.caption(f"{st.session_state.get('opt_df_sz_source', 'Warehouse telemetry')} | {metric_confidence_label('exact')}")
            render_priority_dataframe(
                df_s,
                title="Right-sizing candidates",
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
                    "WAREHOUSE_SIZE",
                    "TOTAL_CREDITS",
                    "TOTAL_QUERIES",
                    "AVG_QUEUE_SEC",
                    "REMOTE_SPILL_GB",
                    "AVG_CACHE_PCT",
                ],
                sort_by=["REMOTE_SPILL_GB", "AVG_QUEUE_SEC", "TOTAL_CREDITS"],
                ascending=[False, False, False],
                raw_label="Warehouse sizing detail",
            )

            st.subheader("Recommendations")
            for _, row in df_s.iterrows():
                decision = str(row.get("DECISION", ""))
                if decision == "No sizing change from this evidence":
                    continue
                message = (
                    f"**{row.get('WAREHOUSE_NAME', '')}**: {decision}. "
                    f"{row.get('SAFE_NEXT_ACTION', '')} Proof: {row.get('PROOF_REQUIRED', '')}"
                )
                if "incident" in decision.lower():
                    st.error(message)
                elif "candidate" in decision.lower():
                    st.info(message)
                else:
                    st.warning(message)

            download_csv(df_s, "right_sizing.csv")
