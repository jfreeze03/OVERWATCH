# sections/query_search.py — Query search & history browser
import streamlit as st
import pandas as pd
from utils import get_session, normalize_df, safe_sql, download_csv, render_query_drilldown


def render():
    session = get_session()

    st.header("🕰️ Query Search & History")
    st.caption("Full-text search over ACCOUNT_USAGE.QUERY_HISTORY (≤45 min latency)")

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1: search_text = st.text_input("Search query text (keyword)", key="qs_text")
    with c2: days_back   = st.slider("Days back", 1, 30, 7, key="qs_days")
    with c3:
        user_filter = st.text_input("User (optional)", key="qs_user")

    status_filter = st.selectbox(
        "Status filter",
        ["ALL", "SUCCESS", "FAILED_WITH_ERROR", "QUEUED", "BLOCKED"],
        key="qs_status"
    )

    if st.button("🔍 Search", key="qs_run") and search_text:
        kw_safe   = safe_sql(search_text)
        usr_safe  = safe_sql(user_filter)
        user_cl   = f"AND user_name ILIKE '%{usr_safe}%'" if usr_safe else ""
        status_cl = f"AND execution_status = '{status_filter}'" if status_filter != "ALL" else ""

        try:
            df_qs = normalize_df(session.sql(f"""
                SELECT query_id, user_name, warehouse_name, execution_status,
                       start_time, total_elapsed_time/1000 AS elapsed_sec,
                       bytes_scanned/POWER(1024,3) AS gb_scanned,
                       rows_produced,
                       credits_used_cloud_services AS cloud_credits,
                       SUBSTR(query_text,1,500) AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('days', -{days_back}, CURRENT_TIMESTAMP())
                  AND query_text ILIKE '%{kw_safe}%'
                  {user_cl} {status_cl}
                ORDER BY start_time DESC
                LIMIT 500
            """).to_pandas())
            st.session_state["qs_df_qs"] = df_qs
        except Exception as e:
            st.error(f"Search error: {e}")

    if st.session_state.get("qs_df_qs") is not None:
        df_q = st.session_state["qs_df_qs"]
        if not df_q.empty:
            st.success(f"Found {len(df_q):,} matching queries.")
            render_query_drilldown(df_q, key="qs_result")
            download_csv(df_q, "query_search_results.csv")
        else:
            st.info("No queries matched the search criteria.")
