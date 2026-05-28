# sections/query_search.py - Query search and history browser
import streamlit as st

from utils import (
    download_csv,
    format_snowflake_error,
    get_active_company,
    get_global_filter_clause,
    get_session,
    render_query_drilldown,
    run_query,
    sql_literal,
)


def render():
    get_session()
    company = get_active_company()

    st.header("Query Search & History")
    st.caption("Full-text search over company-scoped ACCOUNT_USAGE.QUERY_HISTORY.")

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        search_text = st.text_input("Search query text (keyword)", key="qs_text")
    with c2:
        days_back = st.slider("Days back", 1, 30, 7, key="qs_days")
    with c3:
        user_filter = st.text_input("User (optional)", key="qs_user")

    status_filter = st.selectbox(
        "Status filter",
        ["ALL", "SUCCESS", "FAILED_WITH_ERROR", "QUEUED", "BLOCKED"],
        key="qs_status",
    )

    if st.button("Search", key="qs_run") and search_text:
        if len(search_text.strip()) < 3:
            st.warning("Enter at least 3 characters to avoid an expensive full-account query-text scan.")
            return

        user_cl = f"AND user_name ILIKE '%' || {sql_literal(user_filter)} || '%'" if user_filter else ""
        status_cl = f"AND execution_status = {sql_literal(status_filter)}" if status_filter != "ALL" else ""
        scoped_filters = get_global_filter_clause(
            date_col="start_time",
            wh_col="warehouse_name",
            user_col="user_name",
            role_col="role_name",
            db_col="database_name",
        )

        try:
            df_qs = run_query(f"""
                SELECT query_id, user_name, warehouse_name, warehouse_size, execution_status,
                       start_time, total_elapsed_time/1000 AS elapsed_sec,
                       bytes_scanned/POWER(1024,3) AS gb_scanned,
                       rows_produced,
                       credits_used_cloud_services AS cloud_credits,
                       SUBSTR(query_text,1,500) AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('day', -{days_back}, CURRENT_TIMESTAMP())
                  AND query_text ILIKE '%' || {sql_literal(search_text)} || '%'
                  {scoped_filters}
                  {user_cl} {status_cl}
                ORDER BY start_time DESC
                LIMIT 500
            """, ttl_key=f"query_search_{company}_{search_text}_{user_filter}_{status_filter}_{days_back}", tier="historical")
            st.session_state["qs_df_qs"] = df_qs
        except Exception as e:
            st.warning(f"Query search unavailable: {format_snowflake_error(e)}")

    df_q = st.session_state.get("qs_df_qs")
    if df_q is not None:
        if not df_q.empty:
            st.success(f"Found {len(df_q):,} matching queries.")
            render_query_drilldown(df_q, key="qs_result")
            download_csv(df_q, "query_search_results.csv")
        else:
            st.info("No queries matched the search criteria.")
