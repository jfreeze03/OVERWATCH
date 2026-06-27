# sections/change_drift_brief_view.py - Change Brief renderer
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
    with_loaded_at,
)
from sections.change_drift_action_queue import *
from sections.change_drift_common import *
from sections.change_drift_contracts import *
from sections.change_drift_models import *
from sections.change_drift_sql import *
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note

pd = lazy_pandas()
format_snowflake_error = _lazy_util("format_snowflake_error")
get_session = _lazy_util("get_session")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
run_query = _lazy_util("run_query")
day_window_selectbox = _lazy_util("day_window_selectbox")
render_workflow_selector = _lazy_util("render_workflow_selector")

def _render_change_watch_floor(score: int, exceptions: pd.DataFrame, row) -> None:
    priority = _change_priority_view(exceptions).head(3)
    high_risk = 0
    if exceptions is not None and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())
    actors = safe_int(row.get("ACTORS", 0))
    affected_dbs = safe_int(row.get("AFFECTED_DATABASES", 0))

    render_shell_snapshot((
        ("High-Risk Changes", f"{high_risk:,}"),
        ("Untracked Drift", f"{safe_int(row.get('MANUAL_DRIFT', 0)):,}"),
        ("Affected DBs", f"{affected_dbs:,}"),
    ))
    if priority.empty:
        st.success("No urgent change/drift exceptions crossed the brief thresholds.")
    else:
        first = priority.iloc[0]
        st.warning(
            f"First move: {first.get('FINDING_TYPE', 'Change')} by "
            f"{first.get('USER_NAME', 'unknown')} -> {first.get('NEXT_ACTION', 'Validate the change.')}"
        )

    st.markdown("**Change Watch Floor**")
    st.caption(f"Actors: {actors:,} | Affected databases: {affected_dbs:,}")
    if priority.empty:
        st.caption("No immediate change cards. Use Object and access changes for investigation or Schema and object drift for periodic control review.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Object and access changes")
        with cols[idx]:
            render_escaped_bold_text(f"{item.get('SEVERITY', 'Medium')}: {item.get('FINDING_TYPE', '')}")
            st.caption(f"{item.get('ENTITY_TYPE', 'Object')}: {item.get('ENTITY', 'unknown')}")
            st.caption(f"Actor: {item.get('USER_NAME', 'unknown')} | Query: {item.get('QUERY_ID', '')}")
            next_action = str(item.get("NEXT_ACTION", "") or "")
            if st.button(
                f"Open {workflow}",
                key=f"change_watch_floor_{idx}_{workflow}",
                help=next_action or None,
                width="stretch",
            ):
                entity = str(item.get("ENTITY") or "").strip()
                actor = str(item.get("USER_NAME") or "").strip()
                query_id = str(item.get("QUERY_ID") or "").strip()
                if actor and actor.lower() != "unknown":
                    st.session_state["global_user"] = actor
                if entity and entity.lower() != "unknown" and not entity.startswith("01"):
                    st.session_state["global_database"] = entity.split(".")[0]
                if query_id:
                    st.session_state["qs_text"] = query_id
                    st.session_state["qs_status"] = "ALL"
                    st.session_state["qs_autorun"] = True
                for stale_key in (
                    "ocm_df_object_changes",
                    "ocm_df_access_changes",
                    "ocm_df_policy_changes",
                    "ocm_df_drift",
                ):
                    st.session_state.pop(stale_key, None)
                _queue_change_workflow(workflow)

def _render_change_action_brief(brief: dict) -> None:
    render_shell_status_strip(
        state=brief.get("state") or "Review",
        headline=brief.get("headline") or "Review change telemetry.",
        detail=brief.get("detail") or "",
    )

def _render_change_operating_snapshot(snapshot: dict) -> None:
    loaded = bool(snapshot.get("loaded"))
    if not loaded:
        render_shell_kpi_row((
            ("Scope", str(snapshot.get("scope") or "All")),
            ("Window", str(snapshot.get("window") or "14d")),
            ("Telemetry", str(snapshot.get("evidence") or "Fast facts pending")),
            ("Risk", str(snapshot.get("risk") or "On demand")),
        ))
        return
    render_shell_kpi_row((
        ("Objects", f"{safe_int(snapshot.get('object_changes')):,}"),
        ("Access", f"{safe_int(snapshot.get('access_changes')):,}"),
        ("Policy", f"{safe_int(snapshot.get('policy_owner')):,}"),
        ("High Risk", f"{safe_int(snapshot.get('high_risk')):,}"),
    ))

def _queue_change_workflow(workflow: str) -> None:
    if workflow in WORKFLOWS:
        st.session_state["change_drift_requested_view"] = "Change Workflows"
        st.session_state["change_drift_requested_workflow"] = workflow
        st.rerun()

def _apply_queued_change_workflow() -> None:
    requested_view = st.session_state.pop("change_drift_requested_view", None)
    requested_workflow = st.session_state.pop("change_drift_requested_workflow", None)
    if requested_view in CHANGE_DRIFT_VIEWS:
        st.session_state["change_drift_view"] = requested_view
    if requested_workflow in WORKFLOWS:
        st.session_state["change_drift_workflow"] = requested_workflow

def _apply_change_brief_first_default() -> None:
    if st.session_state.get("_change_drift_brief_first_version") == CHANGE_DRIFT_BRIEF_FIRST_VERSION:
        return
    if (
        not _change_has_source_state(st.session_state)
        and st.session_state.get("change_drift_view") not in (None, "Change Brief")
    ):
        st.session_state["change_drift_view"] = "Change Brief"
    st.session_state["_change_drift_brief_first_version"] = CHANGE_DRIFT_BRIEF_FIRST_VERSION

def _render_change_brief_launchpad() -> None:
    st.markdown("**Change Investigation Workflows**")
    rows = _change_brief_workflow_rows()
    for offset in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, row in zip(cols, rows[offset:offset + 3]):
            with col:
                render_escaped_bold_text(row["WORKFLOW"])
                help_text = f"{row['DBA_MOVE']} When: {row['WHEN']}"
                if st.button(
                    row["BUTTON_LABEL"],
                    key=f"change_brief_{row['WORKFLOW']}",
                    help=help_text,
                    width="stretch",
                ):
                    _queue_change_workflow(row["WORKFLOW"])


def render_change_brief(company: str, environment: str, days: int) -> None:
    _render_change_brief_launchpad()

    def _load_change_drift_brief() -> None:
        try:
            summary_sql, exceptions_sql = _build_mart_change_drift_sql(days, company)
            source_label = "Fast change summary"
            st.session_state["change_drift_summary"] = run_query(
                summary_sql,
                ttl_key=f"change_drift_summary_mart_{company}_{environment}_{days}",
                tier="standard",
            )
            st.session_state["change_drift_exceptions"] = run_query(
                exceptions_sql,
                ttl_key=f"change_drift_exceptions_mart_{company}_{environment}_{days}",
                tier="standard",
            )
            st.session_state["change_drift_proof_sql"] = {
                "summary": summary_sql,
                "exceptions": exceptions_sql,
            }
            st.session_state["change_drift_source"] = source_label
            st.session_state["change_drift_meta"] = with_loaded_at(
                _change_scope_meta(company, environment, days),
                source=source_label,
            )
            st.session_state.pop("change_drift_error", None)
        except Exception as exc:
            try:
                # SESSION_OPEN_ADMIN_OK boundary=admin reason=legacy_session budget=advanced_diagnostics owner=platform
                session = get_session()
                summary_sql, exceptions_sql = _build_change_drift_sql(session, days, company)
                source_label = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                st.session_state["change_drift_summary"] = run_query(
                    summary_sql,
                    ttl_key=f"change_drift_summary_live_{company}_{environment}_{days}",
                    tier="standard",
                )
                st.session_state["change_drift_exceptions"] = run_query(
                    exceptions_sql,
                    ttl_key=f"change_drift_exceptions_live_{company}_{environment}_{days}",
                    tier="standard",
                )
                st.session_state["change_drift_proof_sql"] = {
                    "summary": summary_sql,
                    "exceptions": exceptions_sql,
                }
                st.session_state["change_drift_source"] = source_label
                st.session_state["change_drift_meta"] = with_loaded_at(
                    _change_scope_meta(company, environment, days),
                    source=source_label,
                )
                st.session_state.pop("change_drift_error", None)
                st.info(f"Change summary unavailable from the fast summary; used bounded live query history. {format_snowflake_error(exc)}")
            except Exception as live_exc:
                st.session_state["change_drift_summary"] = pd.DataFrame()
                st.session_state["change_drift_exceptions"] = pd.DataFrame()
                st.session_state["change_drift_source"] = "Unavailable: change brief"
                st.session_state["change_drift_meta"] = _change_scope_meta(company, environment, days)
                st.session_state["change_drift_error"] = format_snowflake_error(live_exc)
                st.error(f"Unable to load change brief: {format_snowflake_error(live_exc)}")
        try:
            operability_sql = _change_control_operability_fact_sql(days, company, environment)
            st.session_state["change_control_operability_fact_sql"] = operability_sql
            st.session_state["change_control_operability_fact"] = run_query(
                operability_sql,
                ttl_key=f"change_control_operability_fact_{company}_{environment}_{days}",
                tier="standard",
                section="Change & Drift",
            )
            st.session_state["change_control_operability_fact_meta"] = with_loaded_at(
                _change_scope_meta(company, environment, days),
                source="Change control operability fact",
            )
            st.session_state.pop("change_control_operability_fact_error", None)
        except Exception as fact_exc:
            st.session_state["change_control_operability_fact"] = pd.DataFrame()
            st.session_state["change_control_operability_fact_error"] = format_snowflake_error(fact_exc)

    expected_brief_meta = _change_scope_meta(company, environment, days)
    summary = st.session_state.get("change_drift_summary")
    meta = st.session_state.get("change_drift_meta", {})
    brief_is_current = _change_meta_matches(meta, expected_brief_meta)
    if consume_section_autoload_request("Change & Drift") and not (
        summary is not None and not summary.empty and brief_is_current
    ):
        st.caption("Object Change opened with a lightweight summary. Load the brief when current change-history telemetry is needed.")
    render_data_freshness(
        meta if brief_is_current and summary is not None and not summary.empty else {},
        source=st.session_state.get("change_drift_source", "Object-change brief"),
        target_minutes=60,
        delayed_note="Fast change telemetry uses fast summary rows when available; live QUERY_HISTORY refresh is explicit.",
    )

    if st.button("Load Object Change Brief", key="change_drift_brief_load", type="primary"):
        _load_change_drift_brief()

    summary = st.session_state.get("change_drift_summary")
    exceptions = st.session_state.get("change_drift_exceptions")
    meta = st.session_state.get("change_drift_meta", {})
    brief_is_current = _change_meta_matches(meta, expected_brief_meta)
    if summary is not None and not summary.empty and not brief_is_current:
        st.info("Loaded Object Change brief is stale for the active scope. Reload the brief before acting.")
    if (
        summary is not None
        and not summary.empty
        and brief_is_current
    ):
        row = summary.iloc[0]
        score = _change_drift_score(
            object_changes=safe_int(row.get("OBJECT_CHANGES", 0)),
            access_changes=safe_int(row.get("ACCESS_CHANGES", 0)),
            policy_changes=safe_int(row.get("POLICY_CHANGES", 0)),
            owner_changes=safe_int(row.get("OWNER_CHANGES", 0)),
            destructive_changes=safe_int(row.get("DESTRUCTIVE_CHANGES", 0)),
            manual_drift=safe_int(row.get("MANUAL_DRIFT", 0)),
        )
        if score < 85:
            st.warning("Change control needs DBA review; high-risk changes or drift indicators are present.")
        elif score < 95:
            st.info("Change control is usable, but there are changes worth validating.")
        else:
            st.success("Change control looks clean for the selected window.")
        defer_source_note(meta.get("source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))

        operability_fact = st.session_state.get("change_control_operability_fact")
        operability_fact_current = _change_meta_matches(
            st.session_state.get("change_control_operability_fact_meta"),
            expected_brief_meta,
        )
        if operability_fact is not None and not operability_fact.empty and operability_fact_current:
            st.subheader("Object Change Summary")
            render_shell_snapshot((
                ("Rows", f"{len(operability_fact):,}"),
                ("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
                (
                    "Route / Closure Blocks",
                    f"{int(operability_fact.get('ROUTE_BLOCKED', pd.Series(dtype=int)).sum() + operability_fact.get('CLOSURE_BLOCKED', pd.Series(dtype=int)).sum()):,}",
                ),
                ("Telemetry Confirmed", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
            ))
            render_priority_dataframe(
                operability_fact,
                title="Object-change blockers",
                priority_columns=[
                    "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "ENVIRONMENT",
                    "FINDING_TYPE", "ENTITY", "OWNER", "SEVERITY", "HIGH_RISK_CHANGES",
                    "ROUTE_BLOCKED", "CLOSURE_BLOCKED", "MISSING_TICKET_ROWS",
                    "IAC_GAP_ROWS", "MISSING_QUERY_ID_ROWS", "OPEN_ACTIONS",
                    "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "VERIFIED_CLOSURES",
                    "NEXT_CONTROL_ACTION",
                ],
                sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "HIGH_RISK_CHANGES"],
                ascending=[True, False, False, False],
                raw_label="All object-change summary rows",
                height=300,
            )
            with st.expander("Object Change Status", expanded=False):
                render_shell_snapshot((
                    ("Control summary", "Ready"),
                    ("Escalation route", "Review"),
                    ("Closure telemetry", "Required"),
                    ("Execution", "Runbook only"),
                ))
        elif operability_fact is not None and not operability_fact.empty and not operability_fact_current:
            st.info("Loaded object-change summary is stale for the active scope. Reload the brief before acting.")
        elif st.session_state.get("change_control_operability_fact_error"):
            defer_source_note(
                "Object-change summary is not available yet. Ask the DBA team to enable the fast blocker surface."
            )

        _render_change_watch_floor(score, exceptions, row)
        st.divider()

        if exceptions is not None and not exceptions.empty:
            st.subheader("Object Change Exceptions")
            priority_exceptions = _change_priority_view(exceptions)
            render_priority_dataframe(
                priority_exceptions,
                title="Change and drift exceptions to verify first",
                priority_columns=[
                    "SEVERITY", "FINDING_TYPE", "ENTITY", "USER_NAME",
                    "ROLE_NAME", "DATABASE_NAME", "ENVIRONMENT", "SCOPE_CONFIDENCE",
                    "QUERY_ID", "LAST_SEEN", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["SEVERITY", "LAST_SEEN", "ENTITY"],
                ascending=[True, False, True],
                raw_label="All change and drift exceptions",
            )
            readiness = _build_change_control_readiness(exceptions)
            readiness_summary = _change_control_readiness_summary(readiness)
            closure_days_for_gate = safe_int(st.session_state.get("change_action_closure_days", 30)) or 30
            closure_for_gate = st.session_state.get("change_action_closure")
            if not _change_meta_matches(
                st.session_state.get("change_action_closure_meta"),
                _change_scope_meta(company, environment, closure_days_for_gate),
            ):
                closure_for_gate = pd.DataFrame()
            operator_moves = _change_operator_next_moves(
                score=score,
                exceptions=exceptions,
                readiness_summary=readiness_summary,
                readiness=readiness,
                closure=closure_for_gate,
                operability_fact=operability_fact if operability_fact_current else pd.DataFrame(),
            )
            render_priority_dataframe(
                operator_moves,
                title="Object-change next-move gates",
                priority_columns=["GATE", "STATE", "COUNT", "PROOF_REQUIRED", "NEXT_ACTION"],
                sort_by=["GATE_RANK", "COUNT"],
                ascending=[True, False],
                raw_label="All object-change operator gates",
                height=240,
                max_rows=6,
            )
            intervention_matrix = _change_intervention_matrix(
                exceptions,
                readiness=readiness,
                closure=closure_for_gate,
            )
            if not intervention_matrix.empty:
                render_priority_dataframe(
                    intervention_matrix,
                    title="Object-change intervention matrix",
                    priority_columns=[
                        "DBA_PRIORITY", "INTERVENTION_STATE", "SEVERITY", "FINDING_TYPE", "ENTITY",
                        "USER_NAME", "ROLE_NAME", "QUERY_ID", "CONTROL_STATE",
                        "TICKET_STATE", "IAC_STATE", "CLOSURE_READINESS",
                        "NEXT_DECISION", "PROOF_REQUIRED", "NEXT_WORKFLOW",
                    ],
                    sort_by=["DBA_PRIORITY", "SEVERITY", "FINDING_TYPE"],
                    ascending=[True, True, True],
                    raw_label="All object-change intervention rows",
                    height=300,
                    max_rows=10,
                )
            if not readiness_summary.empty:
                render_shell_snapshot((
                    ("Change Routes", f"{len(readiness_summary):,}"),
                    ("Closure Blocked", f"{int(readiness_summary['CLOSURE_BLOCKED'].sum()):,}"),
                    ("Route Blocked", f"{int(readiness_summary['ROUTE_BLOCKED'].sum()):,}"),
                    ("Account Scope", f"{int(readiness_summary['ACCOUNT_SCOPE_ROWS'].sum()):,}"),
                ))
                render_priority_dataframe(
                    readiness_summary,
                    title="Object-change blocker board",
                    priority_columns=[
                        "READINESS", "ENVIRONMENT", "FINDING_TYPE", "OWNER", "APPROVER",
                        "TOTAL_CHANGES", "HIGH_RISK_CHANGES", "ROUTE_BLOCKED",
                        "CLOSURE_BLOCKED", "REVIEW_READY", "MISSING_TICKET_ROWS",
                        "IAC_GAP_ROWS", "MISSING_QUERY_ID_ROWS", "ACCOUNT_SCOPE_ROWS",
                        "REVIEW_SLA_HOURS", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["READINESS_RANK", "HIGH_RISK_CHANGES", "MISSING_TICKET_ROWS", "IAC_GAP_ROWS"],
                    ascending=[True, False, False, False],
                    raw_label="All object-change blocker routes",
                    height=260,
                )
            render_priority_dataframe(
                readiness,
                title="Object-change readiness before queueing",
                priority_columns=[
                    "SEVERITY", "CHANGE_CONTROL_STATE", "FINDING_TYPE", "ENTITY",
                    "USER_NAME", "QUERY_ID", "APPROVER", "OWNER_APPROVAL_STATUS",
                    "OWNER", "ESCALATION_TARGET", "DATABASE_CONTEXT", "DATABASE_NAME",
                    "ENVIRONMENT", "SCOPE_CONFIDENCE", "CHANGE_TICKET_ID", "CHANGE_TICKET_STATE",
                    "IAC_RECONCILIATION_STATE", "EXECUTION_AUDIT_STATE", "APPROVAL_ROUTE_READY",
                    "CHANGE_EVIDENCE_READINESS", "EVIDENCE_BLOCKERS", "REVIEW_SLA_HOURS",
                    "CONTROL_GAP", "NEXT_CONTROL_ACTION", "PROOF_REQUIRED",
                ],
                sort_by=["SEVERITY", "CHANGE_CONTROL_STATE", "ENTITY"],
                ascending=[True, True, True],
                raw_label="All object-change readiness rows",
                height=260,
            )
            save_col, setup_col = st.columns([1, 2])
            with save_col:
                if st.button("Save Change Telemetry Snapshot", key="change_drift_evidence_snapshot", width="stretch"):
                    _save_change_control_evidence_snapshot(
                        # SESSION_OPEN_ADMIN_OK boundary=admin reason=legacy_session budget=advanced_diagnostics owner=platform
                        get_session(),
                        readiness,
                        company=company,
                        environment=environment,
                        source=meta.get("source", ""),
                    )
            with setup_col:
                defer_source_note(
                        "Snapshot stores ticket, review, rollback, owner, reviewer, query-id, and blast-radius requirements for audit trend review."
                )
            with st.expander("Object Change Telemetry Trend", expanded=False):
                trend_days = day_window_selectbox(
                    "Change telemetry trend window",
                    key="change_drift_evidence_trend_days",
                    default=30,
                )
                if st.button("Load Change Telemetry Trend", key="change_drift_evidence_trend_load"):
                    try:
                        trend_sql = _change_control_evidence_history_sql(trend_days, company, environment)
                        trend = run_query(
                            trend_sql,
                            ttl_key=f"change_drift_evidence_trend_{company}_{environment}_{trend_days}",
                            tier="standard",
                            section="Change & Drift",
                        )
                        st.session_state["change_drift_evidence_trend"] = trend
                        st.session_state["change_drift_evidence_trend_sql"] = trend_sql
                        st.session_state["change_drift_evidence_trend_meta"] = _change_scope_meta(
                            company, environment, trend_days
                        )
                        st.session_state.pop("change_drift_evidence_trend_error", None)
                    except Exception as exc:
                        st.session_state["change_drift_evidence_trend"] = pd.DataFrame()
                        st.session_state["change_drift_evidence_trend_error"] = format_snowflake_error(exc)
                        st.error(f"Unable to load object-change telemetry trend: {format_snowflake_error(exc)}")
                trend = st.session_state.get("change_drift_evidence_trend")
                trend_current = _change_meta_matches(
                    st.session_state.get("change_drift_evidence_trend_meta"),
                    _change_scope_meta(company, environment, trend_days),
                )
                if trend is not None and not trend.empty and trend_current:
                    render_priority_dataframe(
                        trend,
                        title="Persistent object-change telemetry gaps",
                        priority_columns=[
                            "FINDING_TYPE", "SEVERITY", "OWNER", "ESCALATION_TARGET",
                            "EVIDENCE_ROWS", "MISSING_TICKET_ROWS", "IAC_GAP_ROWS",
                            "MISSING_QUERY_ID_ROWS", "LAST_CONTROL_STATE", "LAST_CONTROL_GAP",
                        ],
                        sort_by=["MISSING_TICKET_ROWS", "IAC_GAP_ROWS", "LAST_SNAPSHOT_TS"],
                        ascending=[False, False, False],
                        raw_label="All persisted object-change telemetry",
                        height=260,
                    )
                elif (
                    trend is not None
                    and not trend_current
                    and not st.session_state.get("change_drift_evidence_trend_error")
                ):
                    st.info("Loaded object-change telemetry trend is stale for the active scope. Reload the trend before acting.")
            with st.expander("Change Action Closure Analytics", expanded=False):
                defer_source_note(
                    "Uses change-monitoring action-queue rows to show open, overdue, telemetry-pending, "
                    "or closed-without-telemetry object-change work."
                )
                closure_days = day_window_selectbox(
                    "Change closure window",
                    key="change_action_closure_days",
                    default=30,
                )
                if st.button("Load Change Closure Analytics", key="change_action_closure_load"):
                    try:
                        closure_sql = _change_action_queue_closure_sql(closure_days, company, environment)
                        closure = run_query(
                            closure_sql,
                            ttl_key=f"change_action_closure_{company}_{environment}_{closure_days}",
                            tier="standard",
                            section="Change & Drift",
                        )
                        st.session_state["change_action_closure"] = closure
                        st.session_state["change_action_closure_sql"] = closure_sql
                        st.session_state["change_action_closure_meta"] = _change_scope_meta(
                            company, environment, closure_days
                        )
                        st.session_state.pop("change_action_closure_error", None)
                    except Exception as exc:
                        st.session_state["change_action_closure"] = pd.DataFrame()
                        st.session_state["change_action_closure_error"] = format_snowflake_error(exc)
                        st.warning(f"Change closure analytics unavailable: {format_snowflake_error(exc)}")
                closure = st.session_state.get("change_action_closure")
                closure_current = _change_meta_matches(
                    st.session_state.get("change_action_closure_meta"),
                    _change_scope_meta(company, environment, closure_days),
                )
                if closure is not None and not closure.empty and closure_current:
                    render_priority_dataframe(
                        closure,
                        title="Change closure telemetry gaps",
                        priority_columns=[
                            "CATEGORY", "ENTITY_TYPE", "ENTITY", "CLOSURE_READINESS",
                            "OWNER", "APPROVER", "TOTAL_ACTIONS", "OPEN_ACTIONS",
                            "OVERDUE_OPEN", "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                            "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                            "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                            "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                        ],
                        sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                        ascending=[True, False, False, False],
                        raw_label="All change closure rows",
                        height=300,
                    )
                    with st.expander("Change Closure Status", expanded=False):
                        render_shell_snapshot((
                            ("Closure status", "Ready"),
                            ("Telemetry", "Review"),
                            ("Telemetry", "Required"),
                            ("Execution", "Runbook only"),
                        ))
                elif (
                    closure is not None
                    and not closure_current
                    and not st.session_state.get("change_action_closure_error")
                ):
                    st.info("Loaded change closure analytics are stale for the active scope. Reload closure analytics before acting.")
                elif closure is not None and closure_current:
                    st.info("No object-change action-queue rows found for the selected scope.")
            if st.button("Save Change Exceptions to Action Queue", key="change_drift_queue"):
                # SESSION_OPEN_ADMIN_OK boundary=admin reason=legacy_session budget=advanced_diagnostics owner=platform
                _queue_change_exceptions(get_session(), exceptions)
        elif exceptions is not None:
            st.success("No change/drift exceptions crossed the default thresholds.")
        brief_md = _build_change_drift_markdown(
            company=company,
            days=days,
            score=score,
            summary_row=row,
            exceptions=exceptions,
        )
        dl1, dl2 = st.columns([1, 3])
        with dl1:
            st.download_button(
                "Download Change Brief",
                brief_md,
                file_name=f"overwatch_change_drift_brief_{company.lower()}.md",
                mime="text/markdown",
                key="change_drift_download",
            )
        with dl2:
            with st.expander("Telemetry Status", expanded=False):
                defer_source_note("Use reviewed source telemetry to defend change counts and exception rows.")
                render_shell_snapshot((
                    ("Summary telemetry", "Ready after refresh"),
                    ("Exception telemetry", "Ready after refresh"),
                    ("Route review", "Required"),
                    ("Execution", "Runbook only"),
                ))
        if st.session_state.get("exceptions_only_mode"):
            st.stop()


__all__ = ['_render_change_watch_floor', '_render_change_action_brief', '_render_change_operating_snapshot', '_queue_change_workflow', '_apply_queued_change_workflow', '_apply_change_brief_first_default', '_render_change_brief_launchpad', 'render_change_brief']
