# sections/task_management_etl_audit_view.py - ETL Audit renderer
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

def render_task_etl_audit(session) -> None:
    st.subheader("ETL Audit Framework")
    st.caption("Custom ETL run tracking is optional and owned by the DBA team.")

    if st.button("Load ETL Audit Log", key="etl_load"):
        try:
            df_etl = run_query(f"""
                SELECT
                    RUN_ID,
                    PIPELINE_NAME,
                    TASK_NAME,
                    STATUS,
                    RUN_START,
                    RUN_END,
                    ERROR_MESSAGE
                FROM {ETL_AUDIT_FQN}
                WHERE RUN_START >= DATEADD('day', -30, CURRENT_TIMESTAMP())
                ORDER BY RUN_START DESC
                LIMIT 500
            """, ttl_key="task_management_etl_audit", tier="recent", section="Task Management")
            st.session_state["tm_df_etl"] = df_etl
        except Exception as e:
            st.info(f"Audit history is not available in this environment yet. {format_snowflake_error(e)}")

    if st.session_state.get("tm_df_etl") is not None and not st.session_state["tm_df_etl"].empty:
        df_e = st.session_state["tm_df_etl"]
        ok  = df_e[df_e["STATUS"] == "SUCCESS"] if "STATUS" in df_e.columns else pd.DataFrame()
        err = df_e[df_e["STATUS"] == "FAILED"]  if "STATUS" in df_e.columns else pd.DataFrame()
        render_shell_snapshot((
            ("Total Runs", f"{len(df_e):,}"),
            ("Success", f"{len(ok):,}"),
            ("Failed", f"{len(err):,}"),
        ))
        render_priority_dataframe(
            df_e,
            title="ETL audit runs to review first",
            priority_columns=[
                "RUN_ID", "PIPELINE_NAME", "TASK_NAME", "STATUS",
                "RUN_START", "RUN_END", "ERROR_MESSAGE",
            ],
            sort_by=["STATUS", "RUN_START"],
            ascending=[True, False],
            raw_label="All ETL audit rows",
            max_rows=100,
        )
        download_csv(df_e, "etl_audit.csv")
        if not err.empty and st.button("Save failed ETL runs to Action Queue", key="tm_etl_queue"):
            _queue_task_findings(session, err, "Task Management - ETL Audit")


__all__ = ['render_task_etl_audit']
