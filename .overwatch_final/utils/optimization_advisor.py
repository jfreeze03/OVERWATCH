# utils/optimization_advisor.py - Warehouse Health optimization advisor UI helper
import pandas as pd
import streamlit as st

from config import DEFAULTS, THRESHOLDS
from sections.shell_helpers import render_shell_snapshot

from .compatibility import filter_existing_columns
from .company_filter import get_active_company, get_global_filter_clause, get_wh_filter_clause
from .cost import (
    build_idle_warehouse_sql,
    credits_to_dollars,
    format_credits,
    metric_confidence_label,
)
from .display import day_window_selectbox, download_csv, render_drillable_bar_chart
from .helpers import safe_float
from .recommendation_intelligence import duplicate_query_decision, harden_recommendation, warehouse_sizing_decision
from .query import format_snowflake_error, run_query
from .session import get_session
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
    qh_caps = None

    def _query_history_capabilities() -> dict[str, str]:
        nonlocal qh_caps
        if qh_caps is not None:
            return qh_caps
        qh_cols = set(filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            [
                "CREDITS_USED_CLOUD_SERVICES",
                "QUEUED_OVERLOAD_TIME",
                "BYTES_SPILLED_TO_REMOTE_STORAGE",
                "PERCENTAGE_SCANNED_FROM_CACHE",
                "WAREHOUSE_SIZE",
            ],
        ))
        qh_caps = {
            "duplicate_cloud_expr": (
                "SUM(COALESCE(credits_used_cloud_services, 0))"
                if "CREDITS_USED_CLOUD_SERVICES" in qh_cols
                else "0"
            ),
            "sizing_wh_size_expr": (
                "MAX(warehouse_size)"
                if "WAREHOUSE_SIZE" in qh_cols
                else "NULL::VARCHAR"
            ),
            "sizing_queue_expr": (
                "AVG(queued_overload_time) / 1000"
                if "QUEUED_OVERLOAD_TIME" in qh_cols
                else "0"
            ),
            "sizing_spill_expr": (
                "SUM(bytes_spilled_to_remote_storage) / POWER(1024, 3)"
                if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
                else "0"
            ),
            "sizing_cache_expr": (
                "AVG(percentage_scanned_from_cache)"
                if "PERCENTAGE_SCANNED_FROM_CACHE" in qh_cols
                else "0"
            ),
        }
        return qh_caps

    query_filters = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )

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
                df_idle = run_query(
                    build_idle_warehouse_sql(
                        days_back=idle_days,
                        wh_filter=get_wh_filter_clause("warehouse_name"),
                        min_idle_credits=THRESHOLDS["idle_credit_waste_min"],
                    ),
                    ttl_key=f"optimization_idle_{company}_{idle_days}",
                    tier="historical",
                )
                st.session_state["opt_df_idle"] = df_idle
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
            st.caption(metric_confidence_label("exact"))
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
                qh = _query_history_capabilities()
                duplicate_cloud_expr = qh["duplicate_cloud_expr"]
                df_dup = run_query(f"""
                    SELECT SUBSTR(query_text, 1, 200) AS query_sig,
                           COUNT(DISTINCT user_name) AS user_count,
                           COUNT(*)                  AS execution_count,
                           SUM(total_elapsed_time) / NULLIF(COUNT(*), 0) / 1000 AS avg_elapsed_sec,
                           SUM(total_elapsed_time) / 1000                       AS total_wasted_sec,
                           {duplicate_cloud_expr}                               AS cloud_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{dup_days}, CURRENT_TIMESTAMP())
                      AND UPPER(execution_status) = 'SUCCESS'
                      AND warehouse_name IS NOT NULL
                      {query_filters}
                    GROUP BY query_sig
                    HAVING COUNT(*) >= 5
                    ORDER BY execution_count DESC
                    LIMIT 100
                """, ttl_key=f"optimization_duplicates_{company}_{dup_days}", tier="standard")
                st.session_state["opt_df_dup"] = df_dup
            except Exception as e:
                st.warning(f"Duplicate query analysis unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("opt_df_dup") is not None and not st.session_state["opt_df_dup"].empty:
            df_d = st.session_state["opt_df_dup"]
            decision_rows = [duplicate_query_decision(row) for _, row in df_d.iterrows()]
            df_d = pd.concat([df_d.reset_index(drop=True), pd.DataFrame(decision_rows)], axis=1)
            render_shell_snapshot((("Duplicate Query Patterns", f"{len(df_d):,}"),))
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
                qh = _query_history_capabilities()
                sizing_wh_size_expr = qh["sizing_wh_size_expr"]
                sizing_queue_expr = qh["sizing_queue_expr"]
                sizing_spill_expr = qh["sizing_spill_expr"]
                sizing_cache_expr = qh["sizing_cache_expr"]
                df_sz = run_query(f"""
                    WITH query_stats AS (
                        SELECT
                            warehouse_name,
                            {sizing_wh_size_expr} AS warehouse_size,
                            COUNT(*) AS total_queries,
                            {sizing_queue_expr} AS avg_queue_sec,
                            {sizing_spill_expr} AS remote_spill_gb,
                            {sizing_cache_expr} AS avg_cache_pct
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('day', -{sz_days}, CURRENT_TIMESTAMP())
                          AND warehouse_name IS NOT NULL
                          {query_filters}
                        GROUP BY warehouse_name
                    ),
                    metering AS (
                        SELECT
                            warehouse_name,
                            ROUND(SUM(credits_used), 4) AS total_credits
                        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                        WHERE start_time >= DATEADD('day', -{sz_days}, CURRENT_TIMESTAMP())
                          AND start_time <  DATEADD('hour', -24, CURRENT_TIMESTAMP())
                          {get_wh_filter_clause("warehouse_name")}
                        GROUP BY warehouse_name
                    )
                    SELECT
                        q.warehouse_name,
                        q.warehouse_size,
                        q.total_queries,
                        ROUND(q.avg_queue_sec, 2) AS avg_queue_sec,
                        ROUND(q.remote_spill_gb, 2) AS remote_spill_gb,
                        ROUND(q.avg_cache_pct, 2) AS avg_cache_pct,
                        COALESCE(m.total_credits, 0) AS total_credits
                    FROM query_stats q
                    LEFT JOIN metering m
                      ON q.warehouse_name = m.warehouse_name
                    ORDER BY total_credits DESC
                """, ttl_key=f"optimization_sizing_{company}_{sz_days}", tier="historical")
                st.session_state["opt_df_sz"] = df_sz
            except Exception as e:
                st.warning(f"Warehouse recommendation scan unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("opt_df_sz") is not None and not st.session_state["opt_df_sz"].empty:
            df_s = st.session_state["opt_df_sz"].copy()
            decision_rows = [warehouse_sizing_decision(row) for _, row in df_s.iterrows()]
            df_s = pd.concat([df_s.reset_index(drop=True), pd.DataFrame(decision_rows)], axis=1)
            st.caption(metric_confidence_label("exact"))
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
