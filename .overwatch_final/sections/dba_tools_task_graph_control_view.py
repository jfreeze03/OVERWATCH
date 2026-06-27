# sections/dba_tools_task_graph_control_view.py - Task Graph Control render branch.

import pandas as pd
import streamlit as st

from sections.dba_tools_common import (
    _load_task_inventory,
    _prioritize_query_context,
    _require_typed_confirmation,
    _task_history_sql,
    _typed_confirmation,
)
from sections.dba_tools_task_graph_control import (
    _alter_task_resume_sql,
    _alter_task_suspend_sql,
    _build_dag_view_frame,
    _cancel_task_graph_sql,
    _cancel_task_query_sql,
    _child_tasks_for_root,
    _execute_task_sql,
    _resume_task_graph_sql,
    _root_tasks_frame,
    _task_fqn,
    _task_query_history_columns,
    _task_running_queries_sql,
)
from sections.shell_helpers import render_shell_snapshot
from utils import (
    admin_button_disabled,
    download_csv,
    format_snowflake_error,
    load_live_task_runs,
    run_query_or_raise,
)
from utils.dba_tool_catalog import TASK_GRAPH_CONTROL_PANES
from utils.workflows import render_priority_dataframe, render_workflow_selector


def render_task_graph_control_tool(session, company: str) -> None:
    st.subheader("Task Graph Control")
    st.caption(
        "Cancel running queries spawned by tasks, cancel task graphs mid-run, "
        "suspend/resume individual tasks or entire DAG trees, and restart failed tasks. "
        "Requires OPERATE privilege on tasks or ACCOUNTADMIN."
    )

    task_graph_view = render_workflow_selector(
        "Task graph control view",
        "dba_task_graph_control_view",
        TASK_GRAPH_CONTROL_PANES,
        columns=3,
        show_label=True,
    )

    if task_graph_view == "Running Task Queries":
        st.subheader("Queries Currently Running Under a Task")
        st.caption(
            "Shows recent ACCOUNT_USAGE query activity where QUERY_TAG or query text "
            "indicates task execution. You can cancel individual task-spawned queries here."
        )
        if st.button("Load Running Task Queries", key="tg_run_load"):
            try:
                qh = _task_query_history_columns(session)
                df_tq = run_query_or_raise(_task_running_queries_sql(
                    company,
                    qh["warehouse_size_expr"],
                    qh["query_tag_expr"],
                    qh["task_indicator"],
                ))
                df_tq = _prioritize_query_context(df_tq)
                st.session_state["dba_df_tg_running"] = df_tq
            except Exception as e:
                st.info(f"Task query activity is unavailable in this role/context: {format_snowflake_error(e)}")
                st.session_state["dba_df_tg_running"] = pd.DataFrame()

        if st.session_state.get("dba_df_tg_running") is not None:
            df_tq = st.session_state["dba_df_tg_running"]
            if not df_tq.empty:
                render_priority_dataframe(
                    df_tq,
                    title="Running task-spawned queries",
                    priority_columns=[
                        "QUERY_ID", "QUERY_CONTEXT", "DATABASE_NAME", "SCHEMA_NAME",
                        "USER_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                        "EXECUTION_STATUS", "START_TIME", "ELAPSED_SEC",
                        "QUERY_TAG", "QUERY_TEXT",
                    ],
                    sort_by=["ELAPSED_SEC", "START_TIME"],
                    ascending=[False, False],
                    raw_label="All running task query rows",
                )
                cancel_qid = st.selectbox(
                    "Cancel query",
                    df_tq["QUERY_ID"].tolist(),
                    key="tg_cancel_qid_sel",
                )
                cancel_confirmed = _typed_confirmation(
                    "Type CANCEL to enable task-query cancellation",
                    "CANCEL",
                    f"tg_cancel_confirm_{cancel_qid}",
                ) if cancel_qid else False
                if cancel_qid and st.button(
                    "Cancel This Query",
                    type="primary",
                    key="tg_cancel_q",
                    disabled=admin_button_disabled(),
                ):
                    if _require_typed_confirmation(cancel_confirmed, "CANCEL"):
                        try:
                            # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                            session.sql(_cancel_task_query_sql(cancel_qid)).collect()
                            st.success(f"Cancel sent for `{cancel_qid}`")
                        except Exception as e:
                            st.error(f"Cancel failed: {format_snowflake_error(e)}")
            else:
                st.success("No task-related queries currently running.")

    elif task_graph_view == "Cancel Graph / Task":
        st.subheader("Cancel a Running Task Graph or Individual Task Run")
        st.caption(
            "`SYSTEM$CANCEL_TASK_GRAPH(graph_run_id)` cancels an entire DAG run in progress. "
            "`SYSTEM$CANCEL_QUERY(query_id)` cancels the query spawned by a specific task run."
        )

        if st.button("Load Recent Task Runs", key="tg_runs_load"):
            try:
                df_tasks = _load_task_inventory(session, force_refresh=True)
                df_runs = load_live_task_runs(session, df_tasks, hours_back=6)
                if df_runs.empty:
                    df_runs = run_query_or_raise(_task_history_sql(
                        session,
                        "scheduled_time >= DATEADD('hours', -6, CURRENT_TIMESTAMP())",
                        limit=200,
                    ))
                st.session_state["dba_df_task_runs"] = df_runs
            except Exception as e:
                st.warning(f"Task run history unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("dba_df_task_runs") is not None and not st.session_state["dba_df_task_runs"].empty:
            df_r = st.session_state["dba_df_task_runs"]
            running_runs = df_r[df_r["STATE"].isin(["EXECUTING", "RUNNING"])] if "STATE" in df_r.columns else pd.DataFrame()

            if not running_runs.empty:
                st.warning(f"{len(running_runs)} task run(s) currently executing or scheduled.")
                render_priority_dataframe(
                    running_runs,
                    title="Running or scheduled task runs",
                    priority_columns=[
                        "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                        "SCHEDULED_TIME", "QUERY_ID", "GRAPH_RUN_GROUP_ID",
                        "DURATION_SEC", "ERROR_MESSAGE",
                    ],
                    sort_by=["SCHEDULED_TIME", "DURATION_SEC"],
                    ascending=[False, False],
                    raw_label="All active task run rows",
                )

                st.markdown("**Cancel by Graph Run Group ID** (cancels all tasks in that DAG run)")
                if "GRAPH_RUN_GROUP_ID" in running_runs.columns:
                    graph_ids = running_runs["GRAPH_RUN_GROUP_ID"].dropna().unique().tolist()
                    if graph_ids:
                        sel_graph = st.selectbox(
                            "Select Graph Run Group ID to cancel",
                            graph_ids,
                            key="tg_cancel_graph_sel",
                        )
                        col_cg1, col_cg2 = st.columns([1, 3])
                        with col_cg1:
                            with st.form(f"tg_cancel_graph_form_{sel_graph}"):
                                graph_confirm_text = st.text_input(
                                    "Type CANCEL to enable graph cancellation",
                                    key=f"tg_graph_confirm_{sel_graph}",
                                    placeholder="CANCEL",
                                )
                                submitted = st.form_submit_button(
                                    "Cancel Graph Run",
                                    type="primary",
                                    disabled=admin_button_disabled(),
                                )
                            if submitted:
                                graph_confirmed = str(graph_confirm_text or "").strip() == "CANCEL"
                                if _require_typed_confirmation(graph_confirmed, "CANCEL"):
                                    try:
                                        # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                                        session.sql(_cancel_task_graph_sql(str(sel_graph))).collect()
                                        st.success(f"Graph run `{sel_graph}` cancelled.")
                                        st.session_state.pop("dba_df_task_runs", None)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Cancel graph failed: {format_snowflake_error(e)}")
                                        st.info(
                                            "SYSTEM$CANCEL_TASK_GRAPH requires the task to be running and the caller to have "
                                            "OPERATE privilege on the root task, or ACCOUNTADMIN."
                                        )

                st.markdown("**Cancel individual task run query**")
                if "QUERY_ID" in running_runs.columns:
                    query_ids = running_runs["QUERY_ID"].dropna().unique().tolist()
                    if query_ids:
                        sel_qid = st.selectbox("Select Query ID", query_ids, key="tg_cancel_run_qid")
                        with st.form(f"tg_cancel_run_query_form_{sel_qid}"):
                            run_confirm_text = st.text_input(
                                "Type CANCEL to enable run-query cancellation",
                                key=f"tg_run_confirm_{sel_qid}",
                                placeholder="CANCEL",
                            )
                            submitted = st.form_submit_button(
                                "Cancel Query",
                                disabled=admin_button_disabled(),
                            )
                        if sel_qid and submitted:
                            run_confirmed = str(run_confirm_text or "").strip() == "CANCEL"
                            if _require_typed_confirmation(run_confirmed, "CANCEL"):
                                try:
                                    # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                                    session.sql(_cancel_task_query_sql(str(sel_qid))).collect()
                                    st.success(f"Cancel sent for `{sel_qid}`")
                                except Exception as e:
                                    st.error(f"Cancel failed: {format_snowflake_error(e)}")
            else:
                st.success("No task runs currently executing.")
                st.subheader("Recent History (last 6h)")
                render_priority_dataframe(
                    df_r,
                    title="Recent task run history",
                    priority_columns=[
                        "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                        "SCHEDULED_TIME", "COMPLETED_TIME", "DURATION_SEC",
                        "QUERY_ID", "ERROR_MESSAGE",
                    ],
                    sort_by=["SCHEDULED_TIME"],
                    ascending=False,
                    max_rows=50,
                    raw_label="All recent task run rows",
                )

    elif task_graph_view == "Suspend / Resume":
        st.subheader("Suspend / Resume Tasks and DAG Trees")
        st.caption(
            "Suspend or resume individual tasks or entire DAG hierarchies. "
            "Suspending a root task stops the whole graph from scheduling. "
            "Suspending a child task pauses that branch only."
        )

        if st.button("Load Task List", key="tg_mgmt_load"):
            try:
                df_tasks = _load_task_inventory(session, force_refresh=True)
                st.session_state["dba_df_tg_tasks"] = df_tasks
            except Exception as e:
                st.warning(f"Task inventory unavailable: {format_snowflake_error(e)}")

        df_tasks = st.session_state.get("dba_df_tg_tasks", pd.DataFrame())
        if not df_tasks.empty:
            started = df_tasks[df_tasks["STATE"] == "started"] if "STATE" in df_tasks.columns else pd.DataFrame()
            suspended = df_tasks[df_tasks["STATE"] == "suspended"] if "STATE" in df_tasks.columns else pd.DataFrame()
            render_shell_snapshot((
                ("Total Tasks", f"{len(df_tasks):,}"),
                ("Active", f"{len(started):,}"),
                ("Suspended", f"{len(suspended):,}"),
            ))

            task_display_cols = (
                ["NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "SCHEDULE", "WAREHOUSE"]
                if all(c in df_tasks.columns for c in ["NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "SCHEDULE", "WAREHOUSE"])
                else df_tasks.columns.tolist()
            )
            render_priority_dataframe(
                df_tasks[task_display_cols],
                title="Task inventory by operational state",
                priority_columns=task_display_cols,
                sort_by=["STATE", "DATABASE_NAME", "SCHEMA_NAME", "NAME"],
                ascending=[True, True, True, True],
                raw_label="All task inventory rows",
                height=250,
            )

            st.divider()
            st.subheader("Control Individual Task")
            task_names = df_tasks["NAME"].unique().tolist() if "NAME" in df_tasks.columns else []
            sel_task = st.selectbox("Select task", task_names, key="tg_mgmt_sel")

            if sel_task:
                task_row = df_tasks[df_tasks["NAME"] == sel_task].iloc[0]
                state = task_row.get("STATE", "")
                full_n = _task_fqn(task_row)
                preds = task_row.get("PREDECESSORS", "")

                st.info(f"`{full_n}` | State: **{state}** | Predecessors: `{preds or 'none (root task)'}`")
                task_confirmed = _typed_confirmation(
                    "Type the task name to enable task controls",
                    sel_task,
                    f"tg_confirm_{sel_task}",
                )

                col_s1, col_s2, col_s3, col_s4 = st.columns(4)

                with col_s1:
                    if st.button("Suspend", key="tg_suspend", disabled=admin_button_disabled(state == "suspended")):
                        if _require_typed_confirmation(task_confirmed, sel_task):
                            try:
                                # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                                session.sql(_alter_task_suspend_sql(full_n)).collect()
                                st.success(f"`{sel_task}` suspended.")
                                st.session_state.pop("dba_df_tg_tasks", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Suspend failed: {format_snowflake_error(e)}")

                with col_s2:
                    if st.button("Resume", key="tg_resume", disabled=admin_button_disabled(state == "started")):
                        if _require_typed_confirmation(task_confirmed, sel_task):
                            try:
                                # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                                session.sql(_alter_task_resume_sql(full_n)).collect()
                                st.success(f"`{sel_task}` resumed.")
                                st.session_state.pop("dba_df_tg_tasks", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Resume failed: {format_snowflake_error(e)}")

                with col_s3:
                    if st.button("Execute Now", key="tg_execute", disabled=admin_button_disabled()):
                        if _require_typed_confirmation(task_confirmed, sel_task):
                            try:
                                # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                                session.sql(_execute_task_sql(full_n)).collect()
                                st.success(f"`{sel_task}` triggered.")
                            except Exception as e:
                                st.error(f"Execute failed: {format_snowflake_error(e)}")

                with col_s4:
                    if st.button("Retry Last Failed", key="tg_retry", disabled=admin_button_disabled()):
                        if _require_typed_confirmation(task_confirmed, sel_task):
                            try:
                                # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                                session.sql(_execute_task_sql(full_n)).collect()
                                st.success(f"Retry triggered for `{sel_task}`.")
                                st.caption(
                                    "Note: Snowflake does not have a native RETRY_LAST_FAILED command. "
                                    "This re-executes the task immediately. "
                                    "For DAG-level retry, use EXECUTE TASK on the root task."
                                )
                            except Exception as e:
                                st.error(f"Retry failed: {format_snowflake_error(e)}")

            st.divider()
            st.subheader("Bulk Suspend / Resume Entire DAG Tree")
            st.caption(
                "Suspending the root task stops the entire graph from scheduling. "
                "Select a root task (one with no predecessors) below."
            )
            root_tasks = _root_tasks_frame(df_tasks)

            if not root_tasks.empty:
                root_names = root_tasks["NAME"].unique().tolist() if "NAME" in root_tasks.columns else []
                sel_root = st.selectbox("Select root task (suspends entire graph)", root_names, key="tg_root_sel")

                if sel_root:
                    root_row = df_tasks[df_tasks["NAME"] == sel_root].iloc[0]
                    root_full = _task_fqn(root_row)
                    children = _child_tasks_for_root(df_tasks, sel_root)

                    st.info(
                        f"Root: `{root_full}` | "
                        f"Child tasks in this graph: {len(children)} | "
                        f"Total tasks affected: {len(children) + 1}"
                    )
                    graph_confirmed = _typed_confirmation(
                        "Type the root task name to enable graph controls",
                        sel_root,
                        f"tg_graph_confirm_{sel_root}",
                    )

                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("Suspend Entire Graph", type="primary", key="tg_bulk_suspend", disabled=admin_button_disabled()):
                            if _require_typed_confirmation(graph_confirmed, sel_root):
                                try:
                                    # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                                    session.sql(_alter_task_suspend_sql(root_full)).collect()
                                    st.success(f"Root task `{sel_root}` suspended - entire graph will stop scheduling.")
                                    st.session_state.pop("dba_df_tg_tasks", None)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Suspend failed: {format_snowflake_error(e)}")
                    with b2:
                        if st.button("Resume Entire Graph", type="primary", key="tg_bulk_resume", disabled=admin_button_disabled()):
                            if _require_typed_confirmation(graph_confirmed, sel_root):
                                errors_seen = []
                                child_fqns = [_task_fqn(child) for _, child in children.iterrows()]
                                resume_targets = child_fqns + [root_full]
                                for task_fqn, stmt in zip(resume_targets, _resume_task_graph_sql(root_full, child_fqns)):
                                    try:
                                        # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                                        session.sql(stmt).collect()
                                    except Exception as e:
                                        errors_seen.append(f"{task_fqn}: {format_snowflake_error(e)}")

                                if errors_seen:
                                    st.warning(f"Resumed with {len(errors_seen)} error(s):")
                                    for err in errors_seen:
                                        st.caption(err)
                                else:
                                    st.success(f"Entire graph resumed. {len(children) + 1} task(s) active.")
                                st.session_state.pop("dba_df_tg_tasks", None)
                                st.rerun()

    elif task_graph_view == "DAG Inspector":
        st.subheader("DAG Inspector")
        st.caption(
            "Visualise the task dependency tree for a selected root task. "
            "Shows each node's current state, last run result, and duration."
        )

        df_tasks = st.session_state.get("dba_df_tg_tasks", pd.DataFrame())
        if df_tasks.empty:
            st.info("Load the task list in the Suspend/Resume tab first.")
        else:
            root_tasks = _root_tasks_frame(df_tasks)
            root_names = root_tasks["NAME"].unique().tolist() if not root_tasks.empty else df_tasks["NAME"].unique().tolist()
            sel_dag = st.selectbox("Select root task to inspect", root_names, key="tg_dag_sel")

            if sel_dag and st.button("Refresh DAG View", key="tg_dag_build"):
                try:
                    df_dag = _build_dag_view_frame(df_tasks, pd.DataFrame(), sel_dag)
                    if not df_dag.empty:
                        task_names = [str(v) for v in df_dag["NAME"].dropna().unique().tolist()]
                        try:
                            df_hist = run_query_or_raise(_task_history_sql(
                                session,
                                "scheduled_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())",
                                limit=500,
                            ))
                            df_dag = _build_dag_view_frame(df_tasks, df_hist, sel_dag)
                        except Exception:
                            _ = task_names
                    st.session_state["dba_df_dag_view"] = df_dag
                except Exception as e:
                    st.warning(f"DAG view unavailable in this role/context: {format_snowflake_error(e)}")

            if st.session_state.get("dba_df_dag_view") is not None and not st.session_state["dba_df_dag_view"].empty:
                df_dag = st.session_state["dba_df_dag_view"]

                st.markdown("**Task Dependency Tree**")
                for _, row in df_dag.iterrows():
                    name = row.get("NAME", "")
                    preds = str(row.get("PREDECESSORS", "") or "")
                    state = str(row.get("STATE", "")).lower()
                    lr_st = str(row.get("LAST_RUN_STATE", "") or "")
                    dur = row.get("LAST_DURATION_SEC", 0) or 0
                    err = str(row.get("LAST_ERROR", "") or "")[:80]

                    is_root = preds.strip() in ("", "[]", "None", "nan", "")
                    indent = "" if is_root else "- "

                    state_icon = "Started" if state == "started" else "Suspended" if state == "suspended" else "Unknown"
                    lr_icon = "Succeeded" if lr_st == "SUCCEEDED" else ("Failed" if lr_st == "FAILED" else "Pending")

                    prefix = "    " if indent else ""
                    suffix = f" - {err}" if err and err != "nan" else ""
                    st.markdown(
                        f"{prefix}{indent}{state_icon} **{name}** | {lr_icon} last: {lr_st} "
                        f"({int(dur)}s){suffix}"
                    )

                render_priority_dataframe(
                    df_dag,
                    title="DAG detail rows",
                    priority_columns=[
                        "NAME", "DATABASE_NAME", "SCHEMA_NAME", "STATE", "PREDECESSORS",
                        "LAST_RUN_STATE", "LAST_RUN_TIME", "LAST_DURATION_SEC", "LAST_ERROR",
                    ],
                    sort_by=["LAST_RUN_STATE", "LAST_DURATION_SEC", "LAST_RUN_TIME"],
                    ascending=[True, False, False],
                    raw_label="All DAG rows",
                )
                download_csv(df_dag, f"dag_{sel_dag}.csv")
