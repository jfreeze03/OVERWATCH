# sections/dba_tools_query_kill_view.py - Query Kill List render branch.

import pandas as pd
import streamlit as st

from sections.dba_tools_common import (
    _load_button,
    _require_typed_confirmation,
    _typed_confirmation,
)
from utils import (
    admin_button_disabled,
    filter_existing_columns,
    format_snowflake_error,
    get_wh_filter_clause,
    run_query_or_raise,
    sql_literal,
)
from utils.workflows import render_priority_dataframe


def _query_history_warehouse_size_expr(session) -> str:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE"],
    ))
    return "warehouse_size AS warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"


def _query_kill_list_sql(min_seconds: int, warehouse_size_expr: str) -> str:
    threshold = int(min_seconds)
    return f"""
        SELECT query_id, user_name, warehouse_name, {warehouse_size_expr}, execution_status, start_time,
               DATEDIFF('second', start_time, COALESCE(end_time, CURRENT_TIMESTAMP())) AS elapsed_sec,
               SUBSTR(query_text,1,500) AS query_text
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('hours', -2, CURRENT_TIMESTAMP())
          AND UPPER(execution_status) IN ('RUNNING','QUEUED','BLOCKED')
          AND DATEDIFF('second', start_time, COALESCE(end_time, CURRENT_TIMESTAMP())) > {threshold}
          {get_wh_filter_clause("warehouse_name")}
        ORDER BY elapsed_sec DESC
        LIMIT 500
    """


def _cancel_query_sql(query_id: str) -> str:
    return f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(query_id)})"


def render_query_kill_list_tool(session, company: str) -> None:
    st.subheader("Long-Running Query Kill List")
    kill_min = st.number_input("Flag queries running > (seconds)", 60, 3600, 300, key="kill_sec")
    if _load_button("Load Kill List", "kl_load"):
        try:
            qh_warehouse_size_expr = _query_history_warehouse_size_expr(session)
            df = run_query_or_raise(_query_kill_list_sql(kill_min, qh_warehouse_size_expr))
            st.session_state["dba_df_kl"] = df
        except Exception as e:
            st.session_state["dba_df_kl"] = pd.DataFrame()
            st.caption(f"Query activity unavailable: {format_snowflake_error(e)}")

    if st.session_state.get("dba_df_kl") is not None and not st.session_state["dba_df_kl"].empty:
        df = st.session_state["dba_df_kl"]
        st.warning(f"{len(df)} queries running > {kill_min}s")
        render_priority_dataframe(
            df,
            title="Queries eligible for cancellation",
            priority_columns=[
                "QUERY_ID", "USER_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
                "EXECUTION_STATUS", "START_TIME", "ELAPSED_SEC", "QUERY_TEXT",
            ],
            sort_by=["ELAPSED_SEC", "START_TIME"],
            ascending=[False, False],
            raw_label="All kill-list query rows",
        )
        kill_id = st.selectbox("Kill query ID", df["QUERY_ID"].tolist(), key="kl_sel")
        kill_confirmed = _typed_confirmation(
            "Type CANCEL to enable query cancellation",
            "CANCEL",
            f"kl_confirm_{kill_id}",
        ) if kill_id else False
        if kill_id and st.button(
            "Cancel Query",
            type="primary",
            key="kl_kill",
            disabled=admin_button_disabled(),
        ):
            if _require_typed_confirmation(kill_confirmed, "CANCEL"):
                try:
                    session.sql(_cancel_query_sql(kill_id)).collect()
                    st.success(f"Cancel sent for `{kill_id}`")
                except Exception as e:
                    st.error(f"Cancel failed: {format_snowflake_error(e)}")
    elif st.session_state.get("dba_df_kl") is not None:
        st.success(f"No queries running > {kill_min}s")
