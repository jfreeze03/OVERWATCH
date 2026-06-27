# sections/task_management_execute_view.py - Execute Task renderer
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

def render_task_execute_task(session) -> None:
    st.subheader("Execute Task On-Demand")
    st.caption("Select and run a task on demand. Ensure dependencies are met before running.")
    st.caption("Admin action audit logging is optional and owned by the DBA team.")
    exec_context = _current_execution_context(session)
    st.caption(
        "Execution context: "
        f"user `{exec_context.get('snowflake_user') or 'unknown'}` | "
        f"role `{exec_context.get('snowflake_role') or 'unknown'}` | "
        f"warehouse `{exec_context.get('snowflake_warehouse') or 'none'}`"
    )

    tl = st.session_state.get("tg_list", pd.DataFrame())
    if tl.empty:
        st.warning("Load task data from the Task History workflow first.")
    else:
        task_names = tl["NAME"].unique().tolist() if "NAME" in tl.columns else []
        selected   = st.selectbox("Select task", task_names, key="exec_task_sel")

        if selected:
            row = tl[tl["NAME"] == selected].iloc[0] if len(tl[tl["NAME"] == selected]) else None
            if row is not None:
                db   = row.get("DATABASE_NAME", "")
                sch  = row.get("SCHEMA_NAME", "")
                full = _qualified_name(db, sch, selected)
                st.info(f"Task: `{full}` | State: {row.get('STATE','N/A')} | Schedule: {row.get('SCHEDULE','N/A')}")
                with st.expander("Task Execution Precheck"):
                    render_shell_snapshot((
                        ("Pre-flight", "Required"),
                        ("Confirmation", "Required"),
                        ("Task run", "Immediate"),
                        ("Execution", "Review gated"),
                    ))
                st.warning("This runs the task immediately regardless of schedule.")

                exec_confirm_key = f"exec_task_confirm_{selected}"
                exec_confirmed_value = st.text_input(
                    "Type EXECUTE to enable task run",
                    key=exec_confirm_key,
                )
                exec_confirmed = str(
                    st.session_state.get(exec_confirm_key) or exec_confirmed_value or ""
                ).strip() == "EXECUTE"

                if st.button(
                    f"Execute {selected}",
                    type="primary",
                    key="exec_task_btn",
                    disabled=admin_button_disabled(),
                ):
                    if _require_typed_confirmation(exec_confirmed, "EXECUTE"):
                        sql_text = _execute_task_sql(full)
                        try:
                            # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
                            session.sql(sql_text).collect()
                            _log_admin_action(
                                session,
                                "EXECUTE TASK",
                                full,
                                sql_text,
                                "SUCCESS",
                                "Task triggered.",
                                confirmation_text="EXECUTE",
                                control_context="mode=Execute Task On-Demand",
                            )
                            st.success(f"Task `{full}` triggered.")
                        except Exception as e:
                            message = format_snowflake_error(e)
                            _log_admin_action(
                                session,
                                "EXECUTE TASK",
                                full,
                                sql_text,
                                "FAILED",
                                message,
                                confirmation_text="EXECUTE",
                                control_context="mode=Execute Task On-Demand",
                            )
                            st.error(f"Execution failed: {message}")


__all__ = ['render_task_execute_task']
