# sections/task_management_failure_console_view.py - Failure Console renderer
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

def render_task_failure_console(session) -> None:
        st.subheader("Failure Console & Runbook")
        st.caption(
            "Diagnose failed task graph runs, link failures to query history and stored procedures, "
            "classify probable cause, and export a DBA handoff runbook."
        )
        fc_days = day_window_selectbox("Failure lookback", key="tm_failure_days", default=7)
        if st.button("Load Failure Console", key="tm_failure_load"):
            try:
                inventory = _show_tasks(session, force_refresh=True)
            except Exception as e:
                st.info(f"Task inventory unavailable: {format_snowflake_error(e)}")
                inventory = pd.DataFrame()
            history_result = load_shared_task_history_detail(
                session,
                fc_days,
                get_active_company(),
                limit=1000,
                allow_live_fallback=True,
                force=True,
                section="Task Management",
            )
            if history_result.message and history_result.data.empty:
                st.info(f"Task failure history unavailable: {history_result.message}")
            history = history_result.data
            st.session_state["tm_failure_history_source"] = history_result.source

            failed_query_ids = []
            if not history.empty and "QUERY_ID" in history.columns:
                states = history.get("STATE", pd.Series([""] * len(history), index=history.index)).astype(str).str.upper()
                failed_query_ids = history.loc[states.eq("FAILED"), "QUERY_ID"].dropna().astype(str).tolist()

            query_details = pd.DataFrame()
            if failed_query_ids:
                try:
                    query_sql = _query_detail_sql(session, failed_query_ids)
                    if query_sql:
                        query_details = run_query(
                            query_sql,
                            ttl_key=f"task_failure_query_detail_{get_active_company()}_{fc_days}_{len(failed_query_ids)}",
                            tier="standard",
                        )
                except Exception as e:
                    st.info(f"Linked query detail unavailable: {format_snowflake_error(e)}")

            summary, failures, patterns = _build_failure_console_frames(history, inventory, query_details)
            st.session_state["tm_failure_summary"] = summary
            st.session_state["tm_failure_rows"] = failures
            st.session_state["tm_failure_patterns"] = patterns

        summary = st.session_state.get("tm_failure_summary")
        failures = st.session_state.get("tm_failure_rows", pd.DataFrame())
        patterns = st.session_state.get("tm_failure_patterns", pd.DataFrame())
        if summary:
            render_shell_snapshot((
                ("Failures", f"{safe_int(summary.get('FAILURES')):,}"),
                ("Affected Tasks", f"{safe_int(summary.get('TASKS')):,}"),
                ("Categories", f"{safe_int(summary.get('CATEGORIES')):,}"),
                ("High Priority", f"{safe_int(summary.get('CRITICAL')):,}"),
            ))

            if failures.empty:
                st.success("No failed task runs found for the selected scope.")
            else:
                st.warning("Failed task runs found. Review probable cause before using retry controls.")
                if safe_int(summary.get("P1_INCIDENTS")) or safe_int(summary.get("BLOCKED_RECOVERIES")):
                    st.caption(
                        f"P1 graph incidents: {safe_int(summary.get('P1_INCIDENTS')):,} | "
                        f"Blocked recoveries: {safe_int(summary.get('BLOCKED_RECOVERIES')):,} | "
                        f"Open recoveries: {safe_int(summary.get('OPEN_RECOVERIES')):,} | "
                        f"Recovery SLA breaches: {safe_int(summary.get('RECOVERY_SLA_BREACHES')):,}"
                    )
                if not patterns.empty:
                    st.subheader("Common Failure Patterns")
                    render_priority_dataframe(
                        patterns,
                        title="Most common failure patterns",
                        priority_columns=[
                            "INCIDENT_PRIORITY", "FAILURE_CATEGORY", "ERROR_SIGNATURE", "FAILURE_COUNT",
                            "TASK_COUNT", "DOWNSTREAM_TASK_COUNT", "RECOVERY_READINESS",
                            "LAST_SEEN", "RECOMMENDED_ACTION",
                        ],
                        sort_by=["INCIDENT_PRIORITY", "FAILURE_COUNT", "TASK_COUNT", "DOWNSTREAM_TASK_COUNT"],
                        ascending=[True, False, False, False],
                        raw_label="All failure patterns",
                    )

                category_options = ["All"] + sorted(failures["FAILURE_CATEGORY"].dropna().astype(str).unique().tolist())
                selected_category = st.selectbox("Filter by failure category", category_options, key="tm_failure_category")
                view = failures if selected_category == "All" else failures[failures["FAILURE_CATEGORY"] == selected_category]
                display_cols = [
                    col for col in [
                        "INCIDENT_PRIORITY", "SEVERITY", "TASK_NAME", "ROOT_TASK_NAME",
                        "GRAPH_ROLE", "DOWNSTREAM_TASK_COUNT", "BLAST_RADIUS",
                        "PROCEDURE_NAME", "QUERY_ID",
                        "FAILURE_CATEGORY", "PROBABLE_CAUSE", "RECOMMENDED_ACTION",
                        "RECOVERY_STATE", "RECOVERY_HOURS", "RECOVERY_SLA_TARGET_HOURS",
                        "REVIEW_STATE", "REVIEWED_BY", "REVIEW_STATUS",
                        "ALLOCATION_SOURCE", "RECOVERY_READINESS", "VERIFY_AFTER_FIX",
                        "STATE", "DURATION_SEC", "QUERY_ELAPSED_SEC", "WAREHOUSE_NAME",
                        "IMPACT_OBJECTS", "ERROR_SIGNATURE", "RETRY_SQL"
                    ] if col in view.columns
                ]
                st.subheader("Failure Drilldown")
                render_priority_dataframe(
                    view[display_cols],
                    title="Failure rows to resolve first",
                    priority_columns=[
                        "INCIDENT_PRIORITY", "TASK_NAME", "ROOT_TASK_NAME", "GRAPH_ROLE",
                        "DOWNSTREAM_TASK_COUNT", "PROCEDURE_NAME", "FAILURE_CATEGORY",
                        "RECOVERY_STATE", "REVIEW_STATE", "REVIEWED_BY",
                        "REVIEW_STATUS", "RECOVERY_READINESS",
                        "PROBABLE_CAUSE", "RECOMMENDED_ACTION", "QUERY_ID",
                        "DURATION_SEC", "QUERY_ELAPSED_SEC", "WAREHOUSE_NAME",
                    ],
                    sort_by=["INCIDENT_PRIORITY", "DOWNSTREAM_TASK_COUNT", "DURATION_SEC", "QUERY_ELAPSED_SEC"],
                    ascending=[True, False, False, False],
                    raw_label="All failure drilldown rows",
                )
                download_csv(view[display_cols], "task_failure_console.csv")

                task_options = view["TASK_NAME"].dropna().astype(str).unique().tolist() if "TASK_NAME" in view.columns else []
                if task_options:
                    selected_task = st.selectbox("Open failure runbook detail", task_options, key="tm_failure_task_detail")
                    detail = view[view["TASK_NAME"].astype(str) == selected_task].head(1)
                    if not detail.empty:
                        row = detail.iloc[0]
                        c1, c2 = st.columns([1, 1])
                        with c1:
                            st.markdown("**Probable Cause**")
                            st.write(row.get("PROBABLE_CAUSE", ""))
                            st.markdown("**Recommended Action**")
                            st.write(row.get("RECOMMENDED_ACTION", ""))
                            st.markdown("**Recovery Status**")
                            st.write(row.get("RECOVERY_READINESS", ""))
                            st.markdown("**Recovery SLA**")
                            st.write(row.get("RECOVERY_STATE", ""))
                            st.markdown("**Review Status**")
                            st.write(row.get("REVIEW_STATE", ""))
                        with c2:
                            st.markdown("**Retry Precheck After Fix**")
                            render_shell_snapshot((
                                ("Retry", "Review gated"),
                                ("Precheck", "Required"),
                                ("Status check", "Required"),
                                ("Execution", "Runbook only"),
                            ))
                            st.markdown("**Telemetry**")
                            st.caption(f"Priority: {row.get('INCIDENT_PRIORITY', '')}")
                            st.caption(f"Downstream tasks: {safe_int(row.get('DOWNSTREAM_TASK_COUNT')):,}")
                            st.caption(f"Query ID: {row.get('QUERY_ID', '')}")
                            st.caption(f"Procedure: {row.get('PROCEDURE_NAME', '')}")
                            st.caption(f"Impact hints: {row.get('IMPACT_OBJECTS', '')}")
                            st.caption(f"Signature: {row.get('ERROR_SIGNATURE', '')}")
                            st.caption(f"Verify after fix: {row.get('VERIFY_AFTER_FIX', '')}")
                        if "QUERY_TEXT" in row.index and str(row.get("QUERY_TEXT") or "").strip():
                            with st.expander("Linked Query Telemetry"):
                                st.caption("Query text is available through reviewed Snowflake history for the selected incident.")

                if st.button("Save Failures to Action Queue", key="tm_failure_queue"):
                    try:
                        saved = _queue_failure_findings(session, failures)
                        st.success(f"Saved {saved} failure findings to the action queue.")
                    except Exception as e:
                        st.error(f"Could not save failure findings: {format_snowflake_error(e)}")
                        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")
                st.download_button(
                    "Download Failure Runbook",
                    _build_failure_runbook_markdown(get_active_company(), fc_days, summary, failures, patterns),
                    file_name=f"overwatch_failure_runbook_{get_active_company().lower()}.md",
                    mime="text/markdown",
                    key="tm_failure_runbook_download",
                )

    # -- ETL AUDIT -------------------------------------------------------------


__all__ = ['render_task_failure_console']
