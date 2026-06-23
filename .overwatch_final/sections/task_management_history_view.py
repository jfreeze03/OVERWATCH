# sections/task_management_history_view.py - Task History renderer
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

def render_task_history(session) -> None:
    st.subheader("Task Execution History")
    th_days = day_window_selectbox("Lookback", key="th_days", default=7)

    if st.button("Load Task Data", key="th_load"):
        # Task list
        try:
            df_tl = _show_tasks(session, force_refresh=True)
            st.session_state["tg_list"] = df_tl
        except Exception:
            st.session_state["tg_list"] = pd.DataFrame()

        history_result = load_shared_task_history_detail(
            session,
            th_days,
            get_active_company(),
            limit=500,
            allow_live_fallback=True,
            force=True,
            section="Task Management",
        )
        if history_result.message and history_result.data.empty:
            st.info(f"Task history unavailable in this role/context: {history_result.message}")
        st.session_state["tg_hist"] = history_result.data
        st.session_state["tg_hist_source"] = history_result.source

    tl = st.session_state.get("tg_list", pd.DataFrame())
    th = st.session_state.get("tg_hist", pd.DataFrame())

    if not tl.empty:
        active_tasks = tl[tl["STATE"] == "started"] if "STATE" in tl.columns else pd.DataFrame()
        render_shell_snapshot((
            ("Total Tasks", f"{len(tl):,}"),
            ("Active (started)", f"{len(active_tasks):,}"),
        ))

    if not th.empty:
        failed_tasks = th[th["STATE"] == "FAILED"] if "STATE" in th.columns else pd.DataFrame()
        succeeded    = th[th["STATE"] == "SUCCEEDED"] if "STATE" in th.columns else pd.DataFrame()
        render_shell_snapshot((
            ("Total Runs", f"{len(th):,}"),
            ("Succeeded", f"{len(succeeded):,}"),
            ("Failed", f"{len(failed_tasks):,}"),
        ))

        if not failed_tasks.empty:
            st.subheader("Failed Tasks")
            render_priority_dataframe(
                failed_tasks,
                title="Failed task runs to triage first",
                priority_columns=[
                    "NAME", "TASK_NAME", "ROOT_TASK_NAME", "STATE", "QUERY_ID",
                    "ERROR_MESSAGE", "SCHEDULED_TIME", "COMPLETED_TIME",
                ],
                sort_by=["SCHEDULED_TIME", "COMPLETED_TIME"],
                ascending=[False, False],
                raw_label="All failed task runs",
                max_rows=20,
            )
            if st.button("Save failed tasks to Action Queue", key="tm_failed_queue"):
                _queue_task_findings(session, failed_tasks, "Task Management - Task History")

        st.subheader("Full History")
        render_priority_dataframe(
            th,
            title="Recent task history",
            priority_columns=[
                "NAME", "TASK_NAME", "ROOT_TASK_NAME", "STATE", "QUERY_ID",
                "SCHEDULED_TIME", "COMPLETED_TIME", "DURATION_SEC", "ERROR_MESSAGE",
            ],
            sort_by=["SCHEDULED_TIME", "COMPLETED_TIME"],
            ascending=[False, False],
            raw_label="Full task history",
            max_rows=100,
            height=400,
        )
        download_csv(th, "task_history.csv")


__all__ = ['render_task_history']
