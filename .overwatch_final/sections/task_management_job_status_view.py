# sections/task_management_job_status_view.py - Job Status Brief renderer
import time

import pandas as pd
import streamlit as st

from sections.chart_helpers import render_ranked_bar_chart
from sections.shell_helpers import render_escaped_bold_text, render_shell_snapshot
from utils.workflows import render_priority_dataframe
from utils import (
    build_task_history_sql,
    day_window_selectbox,
    download_csv,
    format_snowflake_error,
    get_active_company,
    admin_button_disabled,
    build_mart_query_detail_recent_sql,
    build_mart_task_critical_path_sql,
    build_mart_task_inventory_sql,
    load_live_task_runs,
    load_shared_task_history_detail,
    run_query,
    run_query_or_raise,
    safe_int,
    safe_float,
    sql_literal,
)
from sections.task_management_action_queue import *
from sections.task_management_common import *
from sections.task_management_contracts import *
from sections.task_management_models import *
from sections.task_management_sql import *

def _load_task_ops_scope(
    session,
    days: int,
    ttl_prefix: str,
    force_inventory_refresh: bool = False,
    include_live_runs: bool = False,
    allow_live_fallback: bool = True,
) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    company = get_active_company()
    database_contains = str(st.session_state.get("global_database", "") or "").strip()
    inventory_source = "Live: SHOW TASKS IN ACCOUNT"
    history_source = "Live: SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY"
    query_detail_source = "Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
    critical_path_source = "Computed: task inventory + task history"
    inventory = pd.DataFrame()
    if include_live_runs:
        try:
            inventory = _show_tasks(session, force_refresh=True)
        except Exception:
            inventory = pd.DataFrame()
    if inventory.empty:
        try:
            inventory = run_query(
                build_mart_task_inventory_sql(company=company, database_contains=database_contains),
                ttl_key=f"{ttl_prefix}_inventory_mart_{company}",
                tier="metadata",
                section="Task Management",
            )
            if inventory.empty:
                if allow_live_fallback:
                    inventory = _show_tasks(session, force_refresh=force_inventory_refresh)
            else:
                inventory_source = "Fast task inventory"
        except Exception as e:
            if allow_live_fallback:
                try:
                    inventory = _show_tasks(session, force_refresh=force_inventory_refresh)
                except Exception:
                    st.info(f"Task inventory unavailable in this role/context: {format_snowflake_error(e)}")
                    inventory = pd.DataFrame()
            else:
                inventory_source = "Fast task inventory unavailable"
                inventory = pd.DataFrame()
    history_result = load_shared_task_history_detail(
        session,
        days,
        company,
        database_contains=database_contains,
        limit=1000,
        allow_live_fallback=allow_live_fallback,
        force=force_inventory_refresh,
        section="Task Management",
    )
    history = history_result.data
    history_source = history_result.source
    if history_result.message and allow_live_fallback and history.empty:
        st.info(f"Task history unavailable in this role/context: {history_result.message}")
    if include_live_runs and not inventory.empty:
        try:
            live_runs = load_live_task_runs(
                session,
                inventory,
                hours_back=6,
                result_limit_per_task=3,
                max_tasks=80,
            )
            if not live_runs.empty:
                history = pd.concat([live_runs, history], ignore_index=True)
                dedupe_cols = [
                    col for col in ["TASK_NAME", "QUERY_ID", "SCHEDULED_TIME"]
                    if col in history.columns
                ]
                if dedupe_cols:
                    history = history.drop_duplicates(dedupe_cols, keep="first")
                history_source = f"{history_source} + Live: INFORMATION_SCHEMA.TASK_HISTORY running jobs"
        except Exception as e:
            st.info(f"Live running task status unavailable: {format_snowflake_error(e)}")
    query_details = pd.DataFrame()
    if not history.empty and "QUERY_ID" in history.columns:
        qids = history["QUERY_ID"].dropna().astype(str).tolist()
        try:
            query_sql = build_mart_query_detail_recent_sql(qids)
            if query_sql:
                query_details = run_query(
                    query_sql,
                    ttl_key=f"{ttl_prefix}_query_detail_mart_{company}_{days}_{len(qids)}",
                    tier="standard",
                )
            if query_details.empty and (allow_live_fallback or include_live_runs):
                query_sql = _query_detail_sql(session, qids)
                if query_sql:
                    query_details = run_query(
                        query_sql,
                        ttl_key=f"{ttl_prefix}_query_detail_live_{company}_{days}_{len(qids)}",
                        tier="standard",
                    )
            else:
                query_detail_source = "Fast query detail summary"
        except Exception as e:
            st.info(f"Linked query cost/detail unavailable: {format_snowflake_error(e)}")
    summary, exceptions, latest = _build_task_ops_frames(inventory, history, query_details)
    try:
        critical_paths = run_query(
            build_mart_task_critical_path_sql(
                days,
                company=company,
                database_contains=database_contains,
                limit=200,
            ),
            ttl_key=f"{ttl_prefix}_critical_path_mart_{company}_{days}",
            tier="historical",
            section="Task Management",
        )
        critical_paths = _normalize_task_critical_path_mart(critical_paths)
        if critical_paths.empty:
            critical_paths = _build_task_critical_path_snapshot(inventory, history)
        else:
            critical_path_source = "Fast task critical-path summary"
    except Exception:
        critical_paths = _build_task_critical_path_snapshot(inventory, history)
    recovery_sla = _build_task_recovery_sla_frame(history, inventory)
    st.session_state[f"{ttl_prefix}_sources"] = {
        "inventory": inventory_source,
        "history": history_source,
        "query_detail": query_detail_source if not query_details.empty else "On demand",
        "critical_path": critical_path_source,
    }
    return summary, exceptions, latest, inventory, critical_paths, recovery_sla, not query_details.empty

def _cache_task_ops_scope(
    summary: dict,
    exceptions: pd.DataFrame,
    latest: pd.DataFrame,
    inventory: pd.DataFrame,
    critical_paths: pd.DataFrame,
    recovery_sla: pd.DataFrame,
    details_loaded: bool,
    *,
    days: int,
    refresh_mode: str,
) -> None:
    st.session_state["task_ops_summary"] = summary
    st.session_state["task_ops_exceptions"] = exceptions
    st.session_state["task_ops_latest"] = latest
    st.session_state["task_ops_inventory"] = inventory
    st.session_state["task_ops_critical_paths"] = critical_paths
    st.session_state["task_ops_recovery_sla"] = recovery_sla
    st.session_state["task_ops_query_details_loaded"] = details_loaded
    st.session_state["task_ops_loaded_days"] = int(days)
    st.session_state["task_ops_refresh_mode"] = refresh_mode
    st.session_state["task_ops_scope_loaded"] = True
    st.session_state["task_ops_loaded_at"] = time.time()

def _render_task_ops_brief(session) -> None:
    company = get_active_company()
    st.subheader("Task Graph Operations Cockpit")
    st.caption(
        "Snowflake task handoff view for Snowflake task graphs: live job status, performance indicators, "
        "errors, suspended tasks, recovery telemetry, and the next operational workflow."
    )
    with st.container():
        days = day_window_selectbox("Task graph lookback", key="task_ops_days", default=7)
        selected_days = int(days)
        if (
            not st.session_state.get("task_ops_scope_loaded")
            or st.session_state.get("task_ops_loaded_days") != selected_days
        ):
            with st.status("Loading latest task summary snapshot...", expanded=False) as status:
                summary, exceptions, latest, inventory, critical_paths, recovery_sla, details_loaded = _load_task_ops_scope(
                    session,
                    selected_days,
                    "task_ops",
                    force_inventory_refresh=False,
                    include_live_runs=False,
                    allow_live_fallback=False,
                )
                _cache_task_ops_scope(
                    summary,
                    exceptions,
                    latest,
                    inventory,
                    critical_paths,
                    recovery_sla,
                    details_loaded,
                    days=selected_days,
                    refresh_mode="summary snapshot",
                )
                status.update(label="Task summary snapshot loaded.", state="complete")
        if st.button("Refresh Live Task Job Status", key="task_ops_load"):
            summary, exceptions, latest, inventory, critical_paths, recovery_sla, details_loaded = _load_task_ops_scope(
                session, selected_days, "task_ops", force_inventory_refresh=True, include_live_runs=True
            )
            _cache_task_ops_scope(
                summary,
                exceptions,
                latest,
                inventory,
                critical_paths,
                recovery_sla,
                details_loaded,
                days=selected_days,
                refresh_mode="live",
            )

        summary = st.session_state.get("task_ops_summary")
        if not summary:
            if st.session_state.get("task_ops_refresh_mode") in {None, "summary snapshot"}:
                st.info(
                    "No task graph summary snapshot is available for this scope. "
                    "Refresh live task job status for current Snowflake task handoff, performance, and error telemetry."
                )
            else:
                st.info("Refresh live task job status to load Snowflake task handoff, performance, and error telemetry.")
            return
        exceptions = st.session_state.get("task_ops_exceptions", pd.DataFrame())
        latest = st.session_state.get("task_ops_latest", pd.DataFrame())
        inventory = st.session_state.get("task_ops_inventory", pd.DataFrame())
        critical_paths = st.session_state.get("task_ops_critical_paths", pd.DataFrame())
        recovery_sla = st.session_state.get("task_ops_recovery_sla", pd.DataFrame())
        score = _task_ops_score(
            failed_runs=safe_int(summary.get("FAILED_RUNS")),
            suspended_tasks=safe_int(summary.get("SUSPENDED_TASKS")),
            long_running_tasks=safe_int(summary.get("LONG_RUNNING_TASKS")),
            total_runs=safe_int(summary.get("TOTAL_RUNS")),
            total_tasks=safe_int(summary.get("TOTAL_TASKS")),
        )
        task_state = "Critical" if score < 65 else "Review" if score < 90 else "Stable"
        render_shell_snapshot((
            ("Tasks", f"{safe_int(summary.get('TOTAL_TASKS')):,}"),
            ("Runs", f"{safe_int(summary.get('TOTAL_RUNS')):,}"),
            ("Failures", f"{safe_int(summary.get('FAILED_RUNS')):,}"),
            ("Operating State", task_state),
        ))
        render_shell_snapshot((
            ("Suspended", f"{safe_int(summary.get('SUSPENDED_TASKS')):,}"),
            (
                "SLA / Cost Drift",
                f"{safe_int(summary.get('LONG_RUNNING_TASKS')) + safe_int(summary.get('COST_DRIFT_TASKS')):,}",
            ),
            ("Open Recovery", f"{safe_int(summary.get('OPEN_RECOVERIES')):,}"),
            ("Recovery SLA", f"{safe_int(summary.get('RECOVERY_SLA_BREACHES')):,}"),
        ))
        if safe_int(summary.get("P1_INCIDENTS")) or safe_int(summary.get("BLOCKED_RECOVERIES")):
            st.caption(
                f"P1 graph incidents: {safe_int(summary.get('P1_INCIDENTS')):,} | "
                f"Blocked recoveries: {safe_int(summary.get('BLOCKED_RECOVERIES')):,} | "
                f"Recovery target: {safe_int(summary.get('RECOVERY_SLA_TARGET_HOURS')):,}h"
            )
        task_ops_sources = st.session_state.get("task_ops_sources", {})
        if task_ops_sources:
            st.caption(
                " | ".join([
                    str(task_ops_sources.get("inventory", "")),
                    str(task_ops_sources.get("history", "")),
                    str(task_ops_sources.get("query_detail", "")),
                    str(task_ops_sources.get("critical_path", "")),
                ])
            )
        if not st.session_state.get("task_ops_query_details_loaded"):
            st.caption("Cost drift uses estimated query credits when linked QUERY_HISTORY detail is available.")
        if score < 65:
            st.error("Incident risk: task graph failures, suspensions, or SLA drift need immediate triage.")
        elif score < 78:
            st.warning("Degraded: review failed and long-running task graph runs before production handoff.")
        elif score < 90:
            st.info("Watch: task graph operations are mostly stable with exceptions to review.")
        else:
            st.success("Operational: no dominant task graph risk signal in this scope.")

        task_status_state, task_status_note = _task_task_status_handoff_state(summary)
        task_status_board = _build_task_status_job_status_board(summary, latest, exceptions)
        task_status_errors = _build_task_status_error_board(exceptions, latest)
        st.subheader("Snowflake task Job Status")
        render_shell_snapshot((
            ("Handoff State", task_status_state),
            ("Running", f"{safe_int(summary.get('RUNNING_TASKS')):,}"),
            ("Job Errors", f"{len(task_status_errors):,}"),
            (
                "Performance Indicators",
                f"{safe_int(summary.get('LONG_RUNNING_TASKS')) + safe_int(summary.get('COST_DRIFT_TASKS')):,}",
            ),
        ))
        loaded_at = safe_float(st.session_state.get("task_ops_loaded_at"))
        refresh_mode = str(st.session_state.get("task_ops_refresh_mode") or "snapshot")
        if loaded_at:
            st.caption(
                f"Last {refresh_mode} refresh: "
                f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(loaded_at))} | {task_status_note}"
            )
        else:
            st.caption(task_status_note)
        render_priority_dataframe(
            task_status_board,
            title="Snowflake task handoff status by operating lane",
            priority_columns=["STATE", "TASK_STATUS_VIEW", "INDICATOR", "COUNT", "EVIDENCE", "LAST_SEEN", "NEXT_ACTION"],
            raw_label="All Snowflake task handoff rows",
            height=220,
            max_rows=8,
        )
        if task_status_errors.empty:
            st.success("No recent task error signatures loaded for this scope.")
        else:
            render_priority_dataframe(
                task_status_errors,
                title="Recent task errors for Snowflake task",
                priority_columns=[
                    "INCIDENT_PRIORITY", "SEVERITY", "SOURCE", "TASK_NAME", "ROOT_TASK_NAME",
                    "STATE", "ERROR_SIGNATURE", "ERROR_MESSAGE", "QUERY_ID", "LAST_SEEN",
                    "EST_TOTAL_CREDITS", "NEXT_ACTION",
                ],
                sort_by=["INCIDENT_PRIORITY", "SEVERITY", "LAST_SEEN"],
                ascending=[True, True, False],
                raw_label="All Snowflake task task error rows",
                max_rows=20,
            )

        slo_summary, slo_board = _build_task_reliability_slo_board(summary, exceptions, recovery_sla)
        st.subheader("Task Reliability Detail")
        render_shell_snapshot((
            ("Ready", f"{slo_summary['ready']:,}"),
            ("Review", f"{slo_summary['review']:,}"),
            ("Checks", f"{len(slo_board):,}"),
        ))
        render_priority_dataframe(
            slo_board,
            title="Task reliability checks and next control step",
            priority_columns=["STATE", "SLO", "EVIDENCE", "NEXT_ACTION"],
            sort_by=["STATE", "SLO"],
            ascending=[True, True],
            raw_label="All task reliability detail rows",
            height=220,
            max_rows=10,
        )

        recovery_board = _task_recovery_command_board(exceptions, recovery_sla)
        if not recovery_board.empty:
            st.subheader("Recovery Detail Summary")
            blocked = int(recovery_board["COMMAND_STATE"].astype(str).eq("Blocked").sum())
            p1_p2 = int(recovery_board["INCIDENT_PRIORITY"].astype(str).str.startswith(("P1", "P2")).sum())
            owner_review = int(
                recovery_board["OWNER_APPROVAL_STATE"].fillna("").astype(str).str.upper().str.contains("REQUIRED|REQUESTED", na=False).sum()
            )
            render_shell_snapshot((
                ("Recovery Items", f"{len(recovery_board):,}"),
                ("Blocked", f"{blocked:,}"),
                ("P1 / P2", f"{p1_p2:,}"),
                ("Route Review", f"{owner_review:,}"),
            ))
            render_priority_dataframe(
                recovery_board,
                title="Retry and closure status",
                priority_columns=[
                    "COMMAND_STATE", "INCIDENT_PRIORITY", "SIGNAL", "TASK_NAME",
                    "ROOT_TASK_NAME", "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT",
                    "RECOVERY_STATE", "RECOVERY_READINESS", "OWNER_APPROVAL_STATE",
                    "ONCALL_PRIMARY", "APPROVAL_GROUP", "NEXT_WORKFLOW",
                    "NEXT_ACTION", "VERIFY_AFTER_FIX",
                ],
                sort_by=["COMMAND_STATE", "INCIDENT_PRIORITY", "DOWNSTREAM_TASK_COUNT"],
                ascending=[True, True, False],
                raw_label="All recovery command rows",
                max_rows=12,
            )

        priority = _task_ops_priority_view(exceptions).head(3)
        st.markdown("**Next DBA Moves**")
        if priority.empty:
            st.caption("No immediate task graph exceptions. Use Failure Console after an alert, or SLA & Cost Drift after a release.")
        else:
            move_cols = st.columns(len(priority))
            for idx, (_, item) in enumerate(priority.iterrows()):
                workflow = str(item.get("NEXT_WORKFLOW") or "Job Status Brief")
                task_name = str(item.get("TASK_NAME") or item.get("ROOT_TASK_NAME") or "Task graph")
                with move_cols[idx]:
                    render_escaped_bold_text(f"{item.get('SEVERITY', 'Signal')}: {task_name}")
                    signal = str(item.get("SIGNAL", "") or "")
                    st.caption(signal)
                    detail = str(item.get("DETAIL", "") or "")
                    next_action = str(item.get("NEXT_ACTION", "") or "")
                    help_text = " ".join(part for part in (signal, detail, next_action) if part).strip()
                    if st.button(
                        f"Open {workflow}",
                        key=f"task_ops_next_{idx}_{workflow}",
                        help=help_text or None,
                        width="stretch",
                    ):
                        st.session_state["task_management_view"] = workflow
                        st.rerun()

        if not critical_paths.empty:
            st.subheader("Critical Path Snapshot")
            render_priority_dataframe(
                critical_paths,
                title="Task graph paths ranked by blast radius, failures, suspension, and runtime",
                priority_columns=[
                    "CRITICAL_PATH_STATE", "ROOT_TASK_NAME", "CRITICAL_PATH_SCORE",
                    "TASK_COUNT", "DOWNSTREAM_TASK_COUNT", "SUSPENDED_TASKS",
                    "FAILURES", "RUNS", "MAX_DURATION_SEC", "LAST_RUN_AT",
                    "BLAST_RADIUS", "OWNER_ROLE", "APPROVAL_PATH", "WAREHOUSES", "PROCEDURES",
                ],
                sort_by=["CRITICAL_PATH_SCORE", "DOWNSTREAM_TASK_COUNT", "MAX_DURATION_SEC"],
                ascending=[False, False, False],
                raw_label="All critical path rows",
                max_rows=20,
            )

        if not recovery_sla.empty:
            st.subheader("Recovery SLA Status")
            render_priority_dataframe(
                recovery_sla,
                title="Failed task graph recovery telemetry",
                priority_columns=[
                    "INCIDENT_PRIORITY", "RECOVERY_STATE", "TASK_NAME", "ROOT_TASK_NAME",
                    "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT", "LAST_FAILURE_AT", "RECOVERY_AT",
                    "RECOVERY_HOURS", "RECOVERY_SLA_TARGET_HOURS", "OWNER", "OWNER_APPROVAL_STATE",
                    "ONCALL_PRIMARY", "APPROVAL_GROUP", "OWNER_SOURCE",
                    "ERROR_SIGNATURE", "VERIFY_AFTER_FIX",
                ],
                sort_by=["INCIDENT_PRIORITY", "DOWNSTREAM_TASK_COUNT", "LAST_FAILURE_AT"],
                ascending=[True, False, False],
                raw_label="All recovery SLA rows",
                max_rows=30,
            )

        if not exceptions.empty:
            st.subheader("Task Graph Exceptions")
            render_priority_dataframe(
                exceptions,
                title="Task graph exceptions to work first",
                priority_columns=[
                    "INCIDENT_PRIORITY", "SEVERITY", "SIGNAL", "TASK_NAME", "ROOT_TASK_NAME",
                    "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT", "BLAST_RADIUS",
                    "PROCEDURE_NAME", "RECOVERY_STATE", "RECOVERY_HOURS", "OWNER_APPROVAL_STATE",
                    "RECOVERY_READINESS", "DETAIL", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["INCIDENT_PRIORITY", "SEVERITY", "DOWNSTREAM_TASK_COUNT", "SIGNAL", "TASK_NAME"],
                ascending=[True, True, False, True, True],
                raw_label="All task graph exceptions",
            )
            if st.button("Save Task Graph Findings to Action Queue", key="task_ops_queue"):
                try:
                    saved = _queue_task_ops_findings(session, exceptions)
                    st.success(f"Saved {saved} task graph findings to the action queue.")
                except Exception as e:
                    st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
                    st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")

        if not inventory.empty:
            st.subheader("Task Graph / Procedure Map")
            with st.expander("Interactive DAG View", expanded=False):
                st.caption(
                    "Shows task predecessor edges from SHOW TASKS. Dashed nodes are predecessors outside the loaded scope."
                )
                max_nodes = st.slider("Max graph nodes", 10, 150, 80, key="task_ops_graph_nodes")
                st.graphviz_chart(_build_task_graph_dot(inventory, max_nodes=max_nodes), width="stretch")
            map_cols = [
                col for col in [
                    "DATABASE_NAME", "SCHEMA_NAME", "ROOT_TASK_NAME", "NAME", "STATE",
                    "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT", "BLAST_RADIUS",
                    "SCHEDULE", "WAREHOUSE", "PREDECESSORS", "PROCEDURE_NAME", "IMPACT_OBJECTS"
                ] if col in inventory.columns
            ]
            render_priority_dataframe(
                inventory[map_cols],
                title="Task graph and procedure map",
                priority_columns=[
                    "DATABASE_NAME", "SCHEMA_NAME", "ROOT_TASK_NAME", "NAME",
                    "STATE", "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT", "BLAST_RADIUS",
                    "WAREHOUSE", "PROCEDURE_NAME", "IMPACT_OBJECTS",
                ],
                sort_by=["DOWNSTREAM_TASK_COUNT", "STATE", "ROOT_TASK_NAME", "NAME"],
                ascending=[False, True, True, True],
                raw_label="Full task graph/procedure map",
                max_rows=50,
            )

        if not latest.empty:
            st.subheader("Latest Run vs Historical Average")
            latest_cols = [
                col for col in [
                    "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME", "STATE", "QUERY_ID",
                    "DURATION_SEC", "AVG_DURATION_SEC", "MAX_DURATION_SEC", "FAILURES",
                    "EST_TOTAL_CREDITS", "AVG_EST_CREDITS", "GRAPH_ROLE",
                    "DOWNSTREAM_TASK_COUNT", "IMPACT_OBJECTS"
                ] if col in latest.columns
            ]
            render_priority_dataframe(
                latest[latest_cols],
                title="Latest runs versus historical average",
                priority_columns=[
                    "TASK_NAME", "ROOT_TASK_NAME", "PROCEDURE_NAME", "STATE",
                    "DURATION_SEC", "AVG_DURATION_SEC", "FAILURES",
                    "EST_TOTAL_CREDITS", "AVG_EST_CREDITS", "GRAPH_ROLE",
                    "DOWNSTREAM_TASK_COUNT", "IMPACT_OBJECTS",
                ],
                sort_by=["FAILURES", "DOWNSTREAM_TASK_COUNT", "DURATION_SEC", "EST_TOTAL_CREDITS"],
                ascending=[False, False, False, False],
                raw_label="All latest task runs",
                max_rows=50,
            )

        st.download_button(
            "Download Task Graph Operations Brief",
            _build_task_ops_markdown(company, days, score, summary, exceptions),
            file_name=f"overwatch_task_graph_ops_{company.lower()}.md",
            mime="text/markdown",
            key="task_ops_download",
        )


def render_task_job_status_brief(session) -> None:
    _render_task_ops_brief(session)


__all__ = ['_load_task_ops_scope', '_cache_task_ops_scope', '_render_task_ops_brief', 'render_task_job_status_brief']
