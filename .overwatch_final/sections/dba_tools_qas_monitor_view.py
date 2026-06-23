# sections/dba_tools_qas_monitor_view.py - Query Acceleration Service render branch.

import streamlit as st

from sections.dba_tools_common import _load_button
from utils import (
    day_window_selectbox,
    filter_existing_columns,
    format_snowflake_error,
    get_wh_filter_clause,
    run_query,
)
from utils.workflows import render_priority_dataframe


def _query_history_warehouse_size_expr(session) -> str:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE"],
    ))
    return "warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"


def render_qas_monitor_tool(session, company: str) -> None:
    st.subheader("QAS Monitor")
    qas_days = day_window_selectbox("Lookback", key="qas_days", default=7)
    if _load_button("Load QAS Data", "qas_load"):
        try:
            qh_plain_size_expr = _query_history_warehouse_size_expr(session)
            st.session_state["dba_df_qas"] = run_query(f"""
                WITH latest_size AS (
                    SELECT warehouse_name, warehouse_size
                    FROM (
                        SELECT warehouse_name, {qh_plain_size_expr},
                               ROW_NUMBER() OVER (PARTITION BY warehouse_name ORDER BY start_time DESC) AS rn
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('day', -{qas_days}, CURRENT_TIMESTAMP())
                          AND warehouse_name IS NOT NULL
                    )
                    WHERE rn = 1
                )
                SELECT q.warehouse_name, ls.warehouse_size, DATE_TRUNC('day', q.start_time) AS day,
                       SUM(q.credits_used) AS daily_credits, COUNT(*) AS query_count
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ACCELERATION_HISTORY q
                LEFT JOIN latest_size ls ON q.warehouse_name = ls.warehouse_name
                WHERE q.start_time >= DATEADD('day', -{qas_days}, CURRENT_TIMESTAMP())
                  {get_wh_filter_clause("q.warehouse_name")}
                GROUP BY q.warehouse_name, ls.warehouse_size, day ORDER BY daily_credits DESC
            """, ttl_key=f"dba_qas_{company}_{qas_days}", tier="standard")
        except Exception as e:
            st.info(f"QAS data unavailable: {format_snowflake_error(e)}")
    if st.session_state.get("dba_df_qas") is not None:
        render_priority_dataframe(
            st.session_state["dba_df_qas"],
            title="Query Acceleration usage",
            priority_columns=["WAREHOUSE_NAME", "WAREHOUSE_SIZE", "DAY", "DAILY_CREDITS", "QUERY_COUNT"],
            sort_by=["DAILY_CREDITS", "QUERY_COUNT"],
            ascending=[False, False],
            raw_label="All QAS usage rows",
        )
