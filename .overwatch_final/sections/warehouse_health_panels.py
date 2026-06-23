# sections/warehouse_health_panels.py - Warehouse Health capacity/source panels.
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.base import lazy_util as _lazy_util
from sections.shell_helpers import render_shell_snapshot
from sections.warehouse_health_actions import (
    _warehouse_capacity_priority_view,
    _warehouse_intervention_matrix,
    _warehouse_setting_control_board,
)
from sections.warehouse_health_capacity import (
    _build_warehouse_capacity_markdown,
    _build_warehouse_capacity_sql,
    _render_warehouse_watch_floor,
)
from sections.warehouse_health_contracts import WAREHOUSE_HEALTH_FAST_ENTRY_VERSION
from sections.warehouse_health_dataframes import (
    _warehouse_meta_matches,
    _warehouse_operator_next_moves,
    _warehouse_overview_exceptions,
    _warehouse_scope_meta,
    _warehouse_source_health_rows,
)
from sections.warehouse_health_helpers import _warehouse_capacity_score
from sections.warehouse_health_loader import _warehouse_action_session
from sections.warehouse_health_queue import _queue_capacity_findings
from sections.warehouse_health_setting_panels import _save_warehouse_setting_review_snapshot
from sections.warehouse_health_sql import (
    _warehouse_action_queue_closure_sql,
    _warehouse_operability_fact_sql,
    _warehouse_setting_execution_audit_sql,
    _warehouse_setting_review_history_sql,
)
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note


day_window_selectbox = _lazy_util("day_window_selectbox")
format_credits = _lazy_util("format_credits")
format_snowflake_error = _lazy_util("format_snowflake_error")
render_load_status = _lazy_util("render_load_status")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
run_query = _lazy_util("run_query")


def _render_capacity_brief(company: str, environment: str) -> None:
    with st.expander("Capacity Brief", expanded=bool(st.session_state.get("exceptions_only_mode"))):
        days = day_window_selectbox("Capacity lookback", key="wh_capacity_days", default=7)
        if st.button("Load Capacity Brief", key="wh_capacity_load"):
            with render_load_status("Building warehouse capacity brief", "Warehouse capacity brief ready"):
                try:
                    session = _warehouse_action_session("load the warehouse capacity brief")
                    if session is None:
                        return
                    summary_sql, exceptions_sql = _build_warehouse_capacity_sql(session, days)
                    summary = run_query(
                        summary_sql,
                        ttl_key=f"wh_capacity_summary_{company}_{environment}_{days}",
                        tier="historical",
                        section="Warehouse Health",
                    )
                    exceptions = run_query(
                        exceptions_sql,
                        ttl_key=f"wh_capacity_exceptions_{company}_{environment}_{days}",
                        tier="historical",
                        section="Warehouse Health",
                    )
                    st.session_state["wh_capacity_summary"] = summary
                    st.session_state["wh_capacity_exceptions"] = exceptions
                    st.session_state["wh_capacity_sql"] = {
                        "summary": summary_sql,
                        "exceptions": exceptions_sql,
                    }
                    st.session_state["wh_capacity_meta"] = _warehouse_scope_meta(company, environment, days)
                    try:
                        operability_sql = _warehouse_operability_fact_sql(days, company, environment)
                        st.session_state["wh_operability_fact_sql"] = operability_sql
                        st.session_state["wh_operability_fact"] = run_query(
                            operability_sql,
                            ttl_key=f"wh_operability_fact_{company}_{environment}_{days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state.pop("wh_operability_fact_error", None)
                    except Exception as fact_exc:
                        st.session_state["wh_operability_fact"] = pd.DataFrame()
                        st.session_state["wh_operability_fact_error"] = format_snowflake_error(fact_exc)
                except Exception as e:
                    st.warning(f"Capacity brief unavailable in this role/context: {format_snowflake_error(e)}")

        summary = st.session_state.get("wh_capacity_summary")
        exceptions = st.session_state.get("wh_capacity_exceptions")
        meta = st.session_state.get("wh_capacity_meta", {})
        if (
            summary is None
            or summary.empty
            or meta.get("company") != company
            or meta.get("environment") != environment
            or meta.get("days") != int(days)
        ):
            return
        exceptions = _warehouse_capacity_priority_view(exceptions)
        row = summary.iloc[0].to_dict()
        score = _warehouse_capacity_score(
            queued_queries=safe_int(row.get("QUEUED_QUERIES")),
            spill_queries=safe_int(row.get("SPILL_QUERIES")),
            high_latency_queries=safe_int(row.get("HIGH_LATENCY_QUERIES")),
            total_queries=safe_int(row.get("TOTAL_QUERIES")),
            credit_spike_pct=safe_float(row.get("CREDIT_SPIKE_PCT")),
        )
        render_shell_snapshot((
            ("Queued", f"{safe_int(row.get('QUEUED_QUERIES')):,}"),
            ("Spill", f"{safe_int(row.get('SPILL_QUERIES')):,}"),
            ("Metered Credits", format_credits(safe_float(row.get("METERED_CREDITS")))),
        ))
        if score < 65:
            st.error("Capacity risk: warehouse pressure is high enough to affect service levels or cost control.")
        elif score < 78:
            st.warning("Pressure: review exception warehouses before expanding workload growth.")
        elif score < 90:
            st.info("Watch: warehouse pressure exists, but it is not currently dominant.")
        else:
            st.success("Healthy: no major warehouse pressure signal in this scope.")

        operability_fact = st.session_state.get("wh_operability_fact")
        if operability_fact is not None and not operability_fact.empty:
            st.subheader("Warehouse Control Summary")
            render_shell_snapshot((
                ("Rows", f"{len(operability_fact):,}"),
                ("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
                (
                    "Pressure Signals",
                    f"{int(operability_fact.get('QUEUE_PRESSURE_ROWS', pd.Series(dtype=int)).sum() + operability_fact.get('SPILL_PRESSURE_ROWS', pd.Series(dtype=int)).sum()):,}",
                ),
                ("Closed", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
            ))
            render_priority_dataframe(
                operability_fact,
                title="Warehouse blockers",
                priority_columns=[
                    "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "ENVIRONMENT",
                    "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                    "QUERY_ROWS", "QUEUE_PRESSURE_ROWS", "SPILL_PRESSURE_ROWS",
                    "HIGH_LATENCY_ROWS", "METERED_CREDITS", "CREDIT_ALLOCATION_METHOD", "REVIEW_ROWS",
                    "APPROVAL_REQUIRED_ROWS", "ROLLBACK_REQUIRED_ROWS",
                    "IMPACT_TELEMETRY_ROWS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                    "FIXED_WITHOUT_VERIFICATION", "VERIFIED_CLOSURES", "NEXT_CONTROL_ACTION",
                ],
                sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "METERED_CREDITS"],
                ascending=[True, False, False, False],
                raw_label="All warehouse control rows",
                height=300,
            )
            with st.expander("Warehouse Control Status", expanded=False):
                render_shell_snapshot((
                    ("Control summary", "Ready"),
                    ("Escalation route", "Review"),
                    ("Closure status", "Required"),
                    ("Execution", "Runbook only"),
                ))
        elif st.session_state.get("wh_operability_fact_error"):
            defer_source_note(
                "Warehouse control summary is not available yet; refresh data health to enable the fast blocker surface."
            )

        _render_warehouse_watch_floor(score, exceptions, row)
        if exceptions is not None and not exceptions.empty:
            audit_col, audit_hint_col = st.columns([1, 3])
            with audit_col:
                if st.button("Load Execution Audit", key="wh_setting_execution_audit_load", width="stretch"):
                    try:
                        audit_sql = _warehouse_setting_execution_audit_sql(30, company, environment)
                        audit = run_query(
                            audit_sql,
                            ttl_key=f"wh_setting_execution_audit_{company}_{environment}_30",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_setting_execution_audit"] = audit
                        st.session_state["wh_setting_execution_audit_sql"] = audit_sql
                        st.session_state["wh_setting_execution_audit_meta"] = _warehouse_scope_meta(
                            company, environment, 30
                        )
                    except Exception as exc:
                        st.session_state["wh_setting_execution_audit"] = pd.DataFrame()
                        st.warning(f"Warehouse execution audit unavailable: {format_snowflake_error(exc)}")
            with audit_hint_col:
                defer_source_note(
                    "Joins setting-review snapshots to guarded ALTER WAREHOUSE audit rows so changes have "
                    "review status, rollback, SQL hash, executor, and post-change telemetry."
                )

            closure_days_for_board = safe_int(st.session_state.get("wh_action_closure_days", 30)) or 30
            closure_for_board = st.session_state.get("wh_action_closure")
            if not _warehouse_meta_matches(
                st.session_state.get("wh_action_closure_meta"),
                _warehouse_scope_meta(company, environment, closure_days_for_board),
            ):
                closure_for_board = pd.DataFrame()
            audit_for_board = st.session_state.get("wh_setting_execution_audit")
            if not _warehouse_meta_matches(
                st.session_state.get("wh_setting_execution_audit_meta"),
                _warehouse_scope_meta(company, environment, 30),
            ):
                audit_for_board = pd.DataFrame()

            control_board = _warehouse_setting_control_board(
                exceptions,
                closure=closure_for_board,
                execution_audit=audit_for_board,
            )
            operator_moves = _warehouse_operator_next_moves(
                score=score,
                exceptions=exceptions,
                control_board=control_board,
                closure=closure_for_board,
                execution_audit=audit_for_board,
                operability_fact=operability_fact,
            )
            render_priority_dataframe(
                operator_moves,
                title="Warehouse operator next-move gates",
                priority_columns=["GATE", "STATE", "COUNT", "PROOF_REQUIRED", "NEXT_ACTION"],
                sort_by=["GATE_RANK", "COUNT"],
                ascending=[True, False],
                raw_label="All warehouse operator gates",
                height=220,
                max_rows=5,
            )
            intervention_matrix = _warehouse_intervention_matrix(
                exceptions,
                control_board=control_board,
                closure=closure_for_board,
            )
            if not intervention_matrix.empty:
                render_priority_dataframe(
                    intervention_matrix,
                    title="Warehouse DBA intervention matrix",
                    priority_columns=[
                        "DBA_PRIORITY", "INTERVENTION_STATE", "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                        "METERED_CREDITS", "PRESSURE_EVIDENCE",
                        "CONTROL_STATE", "CLOSURE_READINESS", "NEXT_DECISION",
                        "PROOF_REQUIRED", "NEXT_WORKFLOW",
                    ],
                    sort_by=["DBA_PRIORITY", "METERED_CREDITS"],
                    ascending=[True, False],
                    raw_label="All warehouse DBA intervention rows",
                    height=280,
                    max_rows=8,
                )
            if not control_board.empty:
                render_priority_dataframe(
                    control_board,
                    title="Warehouse setting control board",
                    priority_columns=[
                        "CONTROL_STATE", "WAREHOUSE_NAME", "SEVERITY", "SIGNAL",
                        "METERED_CREDITS", "ROUTE_READINESS",
                        "AUDIT_READINESS", "AUDIT_BLOCKERS", "CLOSURE_READINESS",
                        "AUDIT_ROWS", "SUCCESSFUL_CHANGES", "FAILED_CHANGES",
                        "LAST_EXECUTION_STATUS", "APPROVAL_REQUIRED", "ROLLBACK_REQUIRED",
                        "IMPACT_TELEMETRY_REQUIRED", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["CONTROL_RANK", "METERED_CREDITS"],
                    ascending=[True, False],
                    raw_label="All warehouse setting control rows",
                    height=300,
                    max_rows=12,
                )
        st.divider()

        if exceptions is not None and not exceptions.empty:
            render_priority_dataframe(
                exceptions,
                title="Warehouse capacity exceptions to work first",
                priority_columns=[
                    "SEVERITY", "SIGNAL", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                    "QUEUED_QUERIES", "SPILL_QUERIES", "HIGH_LATENCY_QUERIES",
                    "METERED_CREDITS", "ADMIN_READINESS", "SETTING_CHANGE_CANDIDATE",
                    "OWNER", "ESCALATION_TARGET", "APPROVER",
                    "APPROVAL_REQUIRED", "ROLLBACK_REQUIRED", "IMPACT_TELEMETRY_REQUIRED", "NEXT_ACTION",
                ],
                sort_by=["QUEUED_QUERIES", "SPILL_QUERIES", "HIGH_LATENCY_QUERIES", "METERED_CREDITS"],
                ascending=[False, False, False, False],
                raw_label="All warehouse capacity exceptions",
            )
            save_col, review_col = st.columns([1, 2])
            with save_col:
                if st.button("Save Setting Review Snapshot", key="wh_setting_review_snapshot", width="stretch"):
                    session = _warehouse_action_session("save a warehouse setting review snapshot")
                    if session is not None:
                        _save_warehouse_setting_review_snapshot(
                            session,
                            exceptions,
                            company=company,
                            environment=environment,
                            source="Warehouse Health Capacity Brief",
                        )
            with review_col:
                defer_source_note(
                    "Snapshot stores review path, rollback requirement, baseline pressure, and post-change telemetry."
                )
            with st.expander("Warehouse Setting Review Trend", expanded=False):
                trend_days = day_window_selectbox(
                    "Setting review trend window",
                    key="wh_setting_review_trend_days",
                    default=30,
                )
                if st.button("Load Setting Review Trend", key="wh_setting_review_trend_load"):
                    try:
                        trend_sql = _warehouse_setting_review_history_sql(trend_days, company, environment)
                        trend = run_query(
                            trend_sql,
                            ttl_key=f"wh_setting_review_trend_{company}_{environment}_{trend_days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_setting_review_trend"] = trend
                        st.session_state["wh_setting_review_trend_sql"] = trend_sql
                    except Exception as exc:
                        st.error(f"Unable to load warehouse setting review trend: {format_snowflake_error(exc)}")
                trend = st.session_state.get("wh_setting_review_trend")
                if trend is not None and not trend.empty:
                    render_priority_dataframe(
                        trend,
                        title="Persistent warehouse setting review backlog",
                        priority_columns=[
                            "WAREHOUSE_NAME", "OWNER", "ESCALATION_TARGET", "REVIEW_ROWS",
                            "APPROVAL_REQUIRED_ROWS", "ROLLBACK_REQUIRED_ROWS",
                            "IMPACT_TELEMETRY_ROWS", "WORST_BASELINE_CAPACITY_SCORE",
                            "MAX_BASELINE_QUEUED_QUERIES", "MAX_BASELINE_SPILL_QUERIES",
                            "LAST_SIGNAL", "LAST_SETTING_CHANGE_CANDIDATE",
                        ],
                        sort_by=["WORST_BASELINE_CAPACITY_SCORE", "APPROVAL_REQUIRED_ROWS", "LAST_SNAPSHOT_TS"],
                        ascending=[True, False, False],
                        raw_label="All persisted warehouse setting reviews",
                        height=260,
                    )
                defer_source_note(
                    "Warehouse setting-review history is owned by the DBA platform team for this environment."
                )
            with st.expander("Warehouse Action Closure Analytics", expanded=False):
                defer_source_note(
                    "Uses Cost & Contract warehouse action-queue rows to show which capacity or efficiency actions are open, "
                    "overdue, telemetry-pending, or recently closed."
                )
                closure_days = day_window_selectbox(
                    "Warehouse closure window",
                    key="wh_action_closure_days",
                    default=30,
                )
                if st.button("Load Warehouse Closure Analytics", key="wh_action_closure_load"):
                    try:
                        closure_sql = _warehouse_action_queue_closure_sql(closure_days, company, environment)
                        closure = run_query(
                            closure_sql,
                            ttl_key=f"wh_action_closure_{company}_{environment}_{closure_days}",
                            tier="standard",
                            section="Warehouse Health",
                        )
                        st.session_state["wh_action_closure"] = closure
                        st.session_state["wh_action_closure_sql"] = closure_sql
                        st.session_state["wh_action_closure_meta"] = _warehouse_scope_meta(
                            company, environment, closure_days
                        )
                    except Exception as exc:
                        st.session_state["wh_action_closure"] = pd.DataFrame()
                        st.warning(f"Warehouse closure analytics unavailable: {format_snowflake_error(exc)}")
                closure = st.session_state.get("wh_action_closure")
                closure_current = _warehouse_meta_matches(
                    st.session_state.get("wh_action_closure_meta"),
                    _warehouse_scope_meta(company, environment, closure_days),
                )
                if closure is not None and not closure.empty and closure_current:
                    render_priority_dataframe(
                        closure,
                        title="Warehouse closure status gaps",
                        priority_columns=[
                            "WAREHOUSE_NAME", "CLOSURE_READINESS", "OWNER", "APPROVER",
                            "TOTAL_ACTIONS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                            "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                            "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                            "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                            "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                        ],
                        sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                        ascending=[True, False, False, False],
                        raw_label="All warehouse closure rows",
                        height=300,
                    )
                    with st.expander("Warehouse Closure Status", expanded=False):
                        render_shell_snapshot((
                            ("Closure status", "Ready"),
                            ("Telemetry", "Review"),
                            ("Telemetry", "Required"),
                            ("Execution", "Runbook only"),
                        ))
                elif closure is not None and not closure.empty and not closure_current:
                    st.info("Loaded warehouse closure analytics are stale for the active scope. Reload closure analytics before acting.")
                elif closure is not None:
                    st.info("No warehouse capacity action-queue rows found for the selected scope.")
            with st.expander("Warehouse Execution Audit Detail", expanded=False):
                audit = st.session_state.get("wh_setting_execution_audit")
                audit_current = _warehouse_meta_matches(
                    st.session_state.get("wh_setting_execution_audit_meta"),
                    _warehouse_scope_meta(company, environment, 30),
                )
                if audit is not None and not audit.empty and audit_current:
                    render_priority_dataframe(
                        audit,
                        title="Warehouse setting execution audit",
                        priority_columns=[
                            "WAREHOUSE_NAME", "EXECUTION_AUDIT_READINESS", "OWNER", "APPROVER",
                            "APPROVAL_STATE", "CHANGE_TICKET_ID", "REVIEW_ROWS", "AUDIT_ROWS",
                            "SUCCESSFUL_CHANGES", "FAILED_CHANGES", "LAST_SQL_HASH",
                            "LAST_EXECUTED_BY", "LAST_EXECUTED_ROLE", "LAST_EXECUTION_STATUS",
                            "LAST_EXECUTED_AT", "POST_CHANGE_VERIFICATION_STATUS",
                            "NEXT_CONTROL_ACTION",
                        ],
                        sort_by=["FAILED_CHANGES", "AUDIT_ROWS", "LAST_EXECUTED_AT"],
                        ascending=[False, False, False],
                        raw_label="All warehouse execution audit rows",
                        height=300,
                    )
                elif audit is not None and not audit.empty and not audit_current:
                    st.info("Loaded warehouse execution audit is stale for the active scope. Reload execution audit before acting.")
                elif audit is not None:
                    st.info("No warehouse setting review or ALTER WAREHOUSE audit rows found for the selected scope.")
                defer_source_note("Warehouse execution audit detail is available through the reviewed runbook.")
            if st.button("Save Capacity Findings to Action Queue", key="wh_capacity_queue"):
                try:
                    session = _warehouse_action_session("save warehouse capacity findings to the action queue")
                    if session is not None:
                        saved = _queue_capacity_findings(session, exceptions)
                        st.success(f"Saved {saved} warehouse capacity findings to the action queue.")
                except Exception as e:
                    st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
                    st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")
        else:
            st.success("No warehouse capacity exceptions found for this scope.")

        st.download_button(
            "Download Capacity Brief",
            _build_warehouse_capacity_markdown(company, days, score, row, exceptions),
            file_name=f"overwatch_warehouse_capacity_{company.lower()}.md",
            mime="text/markdown",
            key="wh_capacity_download",
        )
        with st.expander("Data Health"):
            render_shell_snapshot((
                ("Summary telemetry", "Ready after refresh"),
                ("Exception telemetry", "Ready after refresh"),
                ("Route review", "Required"),
                ("Execution", "Runbook only"),
            ))


def _render_warehouse_source_health(company: str, environment: str) -> None:
    source_health = _warehouse_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Warehouse Telemetry Health", expanded=False):
        loaded = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        fast_summary = int(
            source_health[
            source_health["STATE"].isin(["Loaded", "No Rows"])
            & source_health["CONFIDENCE"].astype(str).str.contains("Fast summary", case=False, regex=False)
        ].shape[0]
        )
        render_shell_snapshot((
            ("Current Surfaces", f"{loaded}/{len(source_health)}"),
            ("Fast Summary", f"{fast_summary:,}"),
            ("Stale", f"{stale:,}"),
            ("Unavailable", f"{unavailable:,}"),
        ))
        defer_source_note(
            "Use this before acting on warehouse findings. Stale rows mean the data was loaded under a different "
            "company, environment, lookback, or triage filter."
        )
        render_priority_dataframe(
            source_health,
            title="Warehouse telemetry source and freshness",
            priority_columns=[
                "SURFACE", "STATE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All warehouse source-health rows",
            height=320,
        )


def _apply_warehouse_fast_entry_default() -> None:
    """Keep first Warehouse Health navigation from replaying heavy support panels."""
    if st.session_state.get("_warehouse_health_fast_entry_version") == WAREHOUSE_HEALTH_FAST_ENTRY_VERSION:
        return
    st.session_state.pop("warehouse_health_support_panels_open", None)
    st.session_state["_warehouse_health_fast_entry_version"] = WAREHOUSE_HEALTH_FAST_ENTRY_VERSION


def _render_warehouse_overview_exception_strip(df: pd.DataFrame | None) -> None:
    exceptions = _warehouse_overview_exceptions(df)
    st.markdown("**Exception Strip**")
    if not exceptions:
        st.success("No urgent warehouse queue, spill, latency, or credit movement exceptions in the loaded overview.")
        return
    for item in exceptions:
        message = (
            f"{item['severity']}: {item['warehouse']} - {item['signal']}. "
            f"{item['next_action']}"
        )
        if item["severity"] == "Critical":
            st.error(message)
        elif item["severity"] == "High":
            st.warning(message)
        else:
            st.info(message)
