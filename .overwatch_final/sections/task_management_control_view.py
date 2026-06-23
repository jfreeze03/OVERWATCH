# sections/task_management_control_view.py - Control Center renderer
import pandas as pd
import streamlit as st

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
    render_ranked_bar_chart,
)
from sections.task_management_action_queue import *
from sections.task_management_common import *
from sections.task_management_contracts import *
from sections.task_management_models import *
from sections.task_management_sql import *

def render_task_control_center(session) -> None:
        st.subheader("Task Graph Control Center")
        st.caption(
            "Generate and run guarded task actions from the same place you diagnose graph health. "
            "Every action is written to the OVERWATCH admin audit table when that table exists."
        )
        st.caption("Admin action audit logging is optional and owned by the DBA team.")
        exec_context = _current_execution_context(session)
        st.caption(
            "Execution context: "
            f"user `{exec_context.get('snowflake_user') or 'unknown'}` | "
            f"role `{exec_context.get('snowflake_role') or 'unknown'}` | "
            f"warehouse `{exec_context.get('snowflake_warehouse') or 'none'}`"
        )

        if st.button("Refresh Task Inventory", key="tm_control_refresh"):
            try:
                st.session_state["tg_list"] = _show_tasks(session, force_refresh=True)
                st.success("Task inventory refreshed.")
            except Exception as e:
                st.warning(f"Task inventory unavailable: {format_snowflake_error(e)}")

        tl = st.session_state.get("tg_list", pd.DataFrame())
        if tl.empty:
            st.warning("Load task inventory from this tab or Task History before using controls.")
        else:
            pred_series = tl.get("PREDECESSORS", pd.Series([""] * len(tl), index=tl.index)).astype(str).str.strip().str.upper()
            root_candidates = tl[pred_series.isin(["", "[]", "NONE", "NAN", "NULL"])] if "NAME" in tl.columns else tl
            root_names = root_candidates["NAME"].astype(str).sort_values().unique().tolist() if "NAME" in root_candidates.columns else []
            all_names = tl["NAME"].astype(str).sort_values().unique().tolist() if "NAME" in tl.columns else []

            control_mode = st.selectbox(
                "Control target",
                ["Graph/root task", "Individual task", "Cancel running graph/query"],
                key="tm_control_mode",
            )

            if control_mode == "Graph/root task":
                root_name = st.selectbox("Root task", root_names or all_names, key="tm_control_root")
                root_row = tl[tl["NAME"].astype(str) == str(root_name)].iloc[0]
                graph_tasks = _collect_graph_tasks(tl, root_name)
                st.info(
                    f"Root: `{_task_full_name(root_row)}` | Tasks affected: {len(graph_tasks)} | "
                    f"Environment guard: {'PROD' if _is_prod_task(root_row) else 'Standard'}"
                )
                if _is_prod_task(root_row):
                    st.error("PROD-like task detected. Controls require the PROD confirmation phrase below.")
                with st.expander("Graph Preview", expanded=True):
                    st.graphviz_chart(_build_task_graph_dot(graph_tasks, max_nodes=120), width="stretch")
                    preview_cols = [
                        col for col in ["DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE", "SCHEDULE", "WAREHOUSE", "PROCEDURE_NAME"]
                        if col in graph_tasks.columns
                    ]
                    render_priority_dataframe(
                        graph_tasks[preview_cols],
                        title="Graph tasks affected",
                        priority_columns=preview_cols,
                        sort_by=["STATE", "DATABASE_NAME", "SCHEMA_NAME", "NAME"],
                        ascending=[True, True, True, True],
                        raw_label="All graph task rows",
                    )

                action = st.selectbox(
                    "Graph action",
                    ["EXECUTE", "RETRY", "SUSPEND", "RESUME"],
                    key="tm_graph_action",
                    help="Retry re-executes the root task. Snowflake does not expose a native retry-last-failed graph command.",
                )
                sql_list = _admin_sql_for_graph(graph_tasks, root_name, action)
                render_shell_snapshot((
                    ("Graph action", action),
                    ("Tasks affected", f"{len(graph_tasks):,}"),
                    ("Pre-flight", "Required"),
                    ("Execution", "Review gated"),
                ))
                phrase = _confirmation_phrase(root_row, action)
                confirmed = _typed_confirmation(
                    f"Type `{phrase}` to enable this graph action",
                    phrase,
                    f"tm_graph_confirm_{action}_{root_name}",
                )
                if st.button(
                    f"Run graph action: {action}",
                    type="primary",
                    key="tm_graph_run",
                    disabled=admin_button_disabled(not sql_list),
                ):
                    if _require_typed_confirmation(confirmed, phrase):
                        completed, errors = _run_admin_sql_list(
                            session,
                            sql_list,
                            f"TASK GRAPH {action}",
                            root_name,
                            confirmation_text=phrase,
                            control_context=(
                                f"mode=Graph/root task; tasks_affected={len(graph_tasks)}; "
                                f"prod_guard={_is_prod_task(root_row)}"
                            ),
                        )
                        if errors:
                            st.warning(f"Completed {completed} statement(s) with {len(errors)} error(s).")
                            for err in errors[:10]:
                                st.caption(err)
                        else:
                            st.success(f"Completed {completed} statement(s) for graph `{root_name}`.")
                        st.session_state.pop("tg_list", None)

            elif control_mode == "Individual task":
                task_name = st.selectbox("Task", all_names, key="tm_control_task")
                row = tl[tl["NAME"].astype(str) == str(task_name)].iloc[0]
                st.info(
                    f"Task: `{_task_full_name(row)}` | State: {row.get('STATE', 'N/A')} | "
                    f"Schedule: {row.get('SCHEDULE', 'N/A')}"
                )
                if _is_prod_task(row):
                    st.error("PROD-like task detected. Controls require the PROD confirmation phrase below.")
                action = st.selectbox("Task action", ["EXECUTE", "RETRY", "SUSPEND", "RESUME"], key="tm_task_action")
                sql_list = _admin_sql_for_task(row, action)
                render_shell_snapshot((
                    ("Task action", action),
                    ("Pre-flight", "Required"),
                    ("Confirmation", "Required"),
                    ("Execution", "Review gated"),
                ))
                phrase = _confirmation_phrase(row, action)
                confirmed = _typed_confirmation(
                    f"Type `{phrase}` to enable this task action",
                    phrase,
                    f"tm_task_confirm_{action}_{task_name}",
                )
                if st.button(
                    f"Run task action: {action}",
                    type="primary",
                    key="tm_task_run",
                    disabled=admin_button_disabled(),
                ):
                    if _require_typed_confirmation(confirmed, phrase):
                        completed, errors = _run_admin_sql_list(
                            session,
                            sql_list,
                            f"TASK {action}",
                            task_name,
                            confirmation_text=phrase,
                            control_context=f"mode=Individual task; prod_guard={_is_prod_task(row)}",
                        )
                        if errors:
                            st.warning(f"Completed {completed} statement(s) with {len(errors)} error(s).")
                            for err in errors[:10]:
                                st.caption(err)
                        else:
                            st.success(f"Completed task action `{action}` for `{task_name}`.")
                        st.session_state.pop("tg_list", None)

            else:
                st.subheader("Cancel Running Task Graph or Query")
                st.caption(
                    "Use this only for currently running task graph executions or their spawned queries. "
                    "Snowflake privileges still apply."
                )
                if st.button("Load Recent Running Task Runs", key="tm_cancel_load"):
                    try:
                        live_runs = load_live_task_runs(session, tl, hours_back=6)
                        if not live_runs.empty:
                            recent_runs = live_runs
                        else:
                            recent_runs = run_query_or_raise(build_task_history_sql(
                                session,
                                "scheduled_time >= DATEADD('hours', -6, CURRENT_TIMESTAMP())",
                                limit=300,
                                company=get_active_company(),
                            ))
                            if "STATE" in recent_runs.columns:
                                states = recent_runs["STATE"].astype(str).str.upper()
                                recent_runs = recent_runs[states.isin(["EXECUTING", "RUNNING"])]
                        st.session_state["tm_cancel_runs"] = recent_runs
                    except Exception as e:
                        st.warning(f"Recent task runs unavailable: {format_snowflake_error(e)}")
                        st.session_state["tm_cancel_runs"] = pd.DataFrame()
                cancel_runs = st.session_state.get("tm_cancel_runs", pd.DataFrame())
                if cancel_runs.empty:
                    st.success("No running task graph runs loaded for cancellation.")
                else:
                    render_priority_dataframe(
                        cancel_runs,
                        title="Running task graph runs",
                        priority_columns=[
                            "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                            "SCHEDULED_TIME", "QUERY_ID", "GRAPH_RUN_GROUP_ID",
                            "DURATION_SEC", "ERROR_MESSAGE",
                        ],
                        sort_by=["SCHEDULED_TIME", "DURATION_SEC"],
                        ascending=[False, False],
                        raw_label="All cancellable task run rows",
                    )
                    cancel_type = st.selectbox("Cancel target", ["Graph Run Group", "Query ID"], key="tm_cancel_type")
                    if cancel_type == "Graph Run Group" and "GRAPH_RUN_GROUP_ID" in cancel_runs.columns:
                        graph_ids = cancel_runs["GRAPH_RUN_GROUP_ID"].dropna().astype(str).unique().tolist()
                        selected_graph = st.selectbox("Graph run group", graph_ids, key="tm_cancel_graph")
                        sql_text = _cancel_task_graph_sql(selected_graph)
                        render_shell_snapshot((
                            ("Cancel target", "Graph run"),
                            ("Selected", selected_graph),
                            ("Confirmation", "Required"),
                            ("Execution", "Review gated"),
                        ))
                        with st.form(f"tm_cancel_graph_form_{selected_graph}"):
                            graph_confirm_text = st.text_input(
                                "Type CANCEL GRAPH to enable cancellation",
                                key="tm_cancel_graph_confirm",
                                placeholder="CANCEL GRAPH",
                            )
                            submitted = st.form_submit_button(
                                "Cancel graph run",
                                type="primary",
                                disabled=admin_button_disabled(),
                            )
                        if submitted:
                            confirmed = str(graph_confirm_text or st.session_state.get("tm_cancel_graph_confirm") or "").strip() == "CANCEL GRAPH"
                            if _require_typed_confirmation(confirmed, "CANCEL GRAPH"):
                                completed, errors = _run_admin_sql_list(
                                    session,
                                    [sql_text],
                                    "CANCEL TASK GRAPH",
                                    selected_graph,
                                    confirmation_text="CANCEL GRAPH",
                                    control_context="mode=Cancel running graph/query",
                                )
                                st.success("Cancel request sent.") if not errors else st.error(errors[0])
                    elif cancel_type == "Query ID" and "QUERY_ID" in cancel_runs.columns:
                        query_ids = cancel_runs["QUERY_ID"].dropna().astype(str).unique().tolist()
                        selected_query = st.selectbox("Query ID", query_ids, key="tm_cancel_query")
                        sql_text = _cancel_task_query_sql(selected_query)
                        render_shell_snapshot((
                            ("Cancel target", "Query"),
                            ("Selected", selected_query),
                            ("Confirmation", "Required"),
                            ("Execution", "Review gated"),
                        ))
                        with st.form(f"tm_cancel_query_form_{selected_query}"):
                            query_confirm_text = st.text_input(
                                "Type CANCEL QUERY to enable cancellation",
                                key="tm_cancel_query_confirm",
                                placeholder="CANCEL QUERY",
                            )
                            submitted = st.form_submit_button(
                                "Cancel query",
                                type="primary",
                                disabled=admin_button_disabled(),
                            )
                        if submitted:
                            confirmed = str(query_confirm_text or st.session_state.get("tm_cancel_query_confirm") or "").strip() == "CANCEL QUERY"
                            if _require_typed_confirmation(confirmed, "CANCEL QUERY"):
                                completed, errors = _run_admin_sql_list(
                                    session,
                                    [sql_text],
                                    "CANCEL QUERY",
                                    selected_query,
                                    confirmation_text="CANCEL QUERY",
                                    control_context="mode=Cancel running graph/query",
                                )
                                st.success("Cancel request sent.") if not errors else st.error(errors[0])
                    else:
                        st.info("The selected cancellation target is not available from this role/account metadata.")

    # -- EXECUTE TASK ----------------------------------------------------------


__all__ = ['render_task_control_center']
