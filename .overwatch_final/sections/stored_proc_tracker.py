# sections/stored_proc_tracker.py - Stored procedure and UDF cost tracking
import streamlit as st
from utils import (
    get_session,
    filter_existing_columns,
    run_query,
    format_snowflake_error,
    format_credits,
    credits_to_dollars,
    metric_confidence_label,
    freshness_note,
    download_csv,
    build_metered_credit_cte,
    render_query_drilldown,
    sql_literal,
    get_global_filter_clause,
    get_active_company,
)


def _query_history_has_root_query_id(session) -> bool:
    return bool(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["ROOT_QUERY_ID"],
    ))


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    company = get_active_company()

    st.header("Stored Proc & UDF Cost Tracker")
    st.caption("CALL queries plus downstream child SQL where ROOT_QUERY_ID is populated.")

    sp_days = st.slider("Lookback (days)", 1, 30, 7, key="sp_tracker_days")
    proc_filters_plain = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    proc_filters_q = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )

    if st.button("Load Stored Proc Usage", key="sp_load"):
        try:
            has_root_query_id = _query_history_has_root_query_id(session)
            qh_cols = set(filter_existing_columns(
                session,
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["WAREHOUSE_SIZE", "BYTES_SCANNED", "CREDITS_USED_CLOUD_SERVICES"],
            ))
            root_expr = "COALESCE(q.root_query_id, q.query_id)" if has_root_query_id else "q.query_id"
            call_wh_size_expr = (
                "warehouse_size"
                if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
            )
            child_bytes_expr = (
                "q.bytes_scanned AS bytes_scanned"
                if "BYTES_SCANNED" in qh_cols else "0::NUMBER AS bytes_scanned"
            )
            child_cloud_expr = (
                "q.credits_used_cloud_services AS credits_used_cloud_services"
                if "CREDITS_USED_CLOUD_SERVICES" in qh_cols else "0::FLOAT AS credits_used_cloud_services"
            )
            df_sp = run_query(f"""
                WITH {build_metered_credit_cte(days_back=sp_days, include_recent=True)},
                calls AS (
                    SELECT query_id AS root_query_id,
                           user_name,
                           role_name,
                           warehouse_name,
                           {call_wh_size_expr},
                           start_time,
                           REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1) AS procedure_name,
                           SUBSTR(query_text, 1, 500) AS call_text
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE query_type = 'CALL'
                      AND start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                      {proc_filters_plain}
                ),
                children AS (
                    SELECT {root_expr} AS root_query_id,
                           q.query_id,
                           q.query_type,
                           q.total_elapsed_time,
                           {child_bytes_expr},
                           {child_cloud_expr},
                           pqc.metered_credits,
                           SUBSTR(q.query_text, 1, 500) AS child_query_text
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                    WHERE q.start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                      {proc_filters_q}
                )
                SELECT c.procedure_name,
                       c.user_name,
                       c.role_name,
                       c.warehouse_name,
                       MAX(c.warehouse_size) AS warehouse_size,
                       c.call_text AS query_text,
                       COUNT(DISTINCT c.root_query_id) AS call_count,
                       COUNT(DISTINCT ch.query_id) AS downstream_query_count,
                       AVG(ch.total_elapsed_time)/1000 AS avg_elapsed_sec,
                       SUM(ch.total_elapsed_time)/1000 AS total_elapsed_sec,
                       ROUND(SUM(COALESCE(ch.metered_credits,0)), 4) AS metered_credits,
                       ROUND(SUM(ch.credits_used_cloud_services), 4) AS cloud_credits,
                       ROUND(SUM(ch.bytes_scanned)/POWER(1024,3), 2) AS gb_scanned,
                       MAX(c.start_time) AS last_call
                FROM calls c
                LEFT JOIN children ch ON c.root_query_id = ch.root_query_id
                GROUP BY c.procedure_name, c.user_name, c.role_name, c.warehouse_name,
                         c.call_text
                ORDER BY metered_credits DESC, total_elapsed_sec DESC
                LIMIT 200
            """, ttl_key=f"stored_proc_usage_{company}_{sp_days}_{has_root_query_id}", tier="standard")
            st.session_state["spt_df_sp_tracker"] = df_sp
            st.session_state["spt_has_root_query_id"] = has_root_query_id
        except Exception as e:
            st.warning(f"Stored procedure cost data unavailable: {format_snowflake_error(e)}")

    if st.session_state.get("spt_df_sp_tracker") is not None and not st.session_state["spt_df_sp_tracker"].empty:
        df_sp = st.session_state["spt_df_sp_tracker"]
        if not st.session_state.get("spt_has_root_query_id", False):
            st.info("ROOT_QUERY_ID is not available in this Snowflake account. Showing outer CALL cost only.")
        total_credits = df_sp["METERED_CREDITS"].sum() + df_sp["CLOUD_CREDITS"].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Unique Proc Signatures", df_sp["QUERY_TEXT"].nunique())
        c2.metric("Total Calls", f"{int(df_sp['CALL_COUNT'].sum()):,}")
        c3.metric("Downstream Queries", f"{int(df_sp['DOWNSTREAM_QUERY_COUNT'].sum()):,}")
        c4.metric("Total Credits", format_credits(total_credits))
        lineage_confidence = "allocated" if st.session_state.get("spt_has_root_query_id", False) else "estimated"
        st.caption(
            f"{metric_confidence_label(lineage_confidence)} | "
            f"{freshness_note('QUERY_HISTORY')} | child-query coverage depends on ROOT_QUERY_ID availability."
        )
        df_sp["EST_COST"] = (df_sp["METERED_CREDITS"] + df_sp["CLOUD_CREDITS"]).apply(
            lambda x: credits_to_dollars(x, credit_price)
        )
        st.dataframe(df_sp, use_container_width=True)
        download_csv(df_sp, "stored_proc_usage.csv")

        st.divider()
        proc_options = df_sp["PROCEDURE_NAME"].fillna(df_sp["QUERY_TEXT"]).astype(str).tolist()
        selected_proc = st.selectbox("Open downstream query detail", proc_options, key="sp_downstream_select")
        if selected_proc and st.button("Load Downstream Queries", key="sp_downstream_load"):
            try:
                has_root_query_id = st.session_state.get("spt_has_root_query_id")
                if has_root_query_id is None:
                    has_root_query_id = _query_history_has_root_query_id(session)
                qh_cols = set(filter_existing_columns(
                    session,
                    "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                    ["WAREHOUSE_SIZE", "BYTES_SCANNED"],
                ))
                root_expr = "COALESCE(q.root_query_id, q.query_id)" if has_root_query_id else "q.query_id"
                child_wh_size_expr = (
                    "q.warehouse_size AS warehouse_size"
                    if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
                )
                child_gb_expr = (
                    "q.bytes_scanned/POWER(1024,3) AS gb_scanned"
                    if "BYTES_SCANNED" in qh_cols else "0::FLOAT AS gb_scanned"
                )
                proc_exact = sql_literal(selected_proc)
                proc_like = sql_literal('%' + selected_proc + '%')
                df_child = run_query(f"""
                WITH roots AS (
                    SELECT query_id AS root_query_id
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE query_type = 'CALL'
                      AND start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                      {proc_filters_plain}
                      AND (REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1) = {proc_exact}
                           OR query_text ILIKE {proc_like})
                )
                SELECT q.query_id, q.user_name, q.warehouse_name, {child_wh_size_expr}, q.execution_status,
                       q.query_type, q.start_time,
                       q.total_elapsed_time/1000 AS elapsed_sec,
                       {child_gb_expr},
                       SUBSTR(q.query_text,1,4000) AS query_text
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                JOIN roots r ON {root_expr} = r.root_query_id
                WHERE 1=1
                  {proc_filters_q}
                ORDER BY q.start_time
                LIMIT 500
                """, ttl_key=f"stored_proc_child_{company}_{sp_days}_{selected_proc}", tier="standard")
                render_query_drilldown(df_child, key="sp_child_queries", title="Stored procedure child-query drill-down")
            except Exception as e:
                st.info(f"Downstream detail unavailable: {format_snowflake_error(e)}")
