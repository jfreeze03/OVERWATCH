# sections/dba_tools_data_movement_view.py - Read-only DBA data movement render branches.

import streamlit as st

from sections.dba_tools_common import _ensure_column_alias, _load_button, _scope_metadata_df, _show_to_df
from utils import (
    day_window_selectbox,
    download_csv,
    filter_existing_columns,
    format_credits,
    format_snowflake_error,
    get_db_filter_clause,
    run_query,
    run_query_or_raise,
)
from utils.workflows import render_priority_dataframe
from sections.shell_helpers import render_shell_snapshot



def render_data_loading_tool(session, company: str) -> None:
    st.subheader("Data Loading Monitor")
    load_days = day_window_selectbox("Lookback", key="dl_days", default=7)
    if _load_button("Load Copy History", "dl_load"):
        try:
            st.session_state["dba_df_copy"] = run_query(f"""
                SELECT table_name, file_name, status, row_count,
                       first_error_message, last_load_time
                FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
                WHERE last_load_time >= DATEADD('day', -{load_days}, CURRENT_TIMESTAMP())
                  {get_db_filter_clause("table_catalog_name")}
                ORDER BY last_load_time DESC LIMIT 500
            """, ttl_key=f"dba_copy_{company}_{load_days}", tier="standard")
        except Exception as e:
            st.warning(f"Copy history unavailable: {format_snowflake_error(e)}")
    if st.session_state.get("dba_df_copy") is not None and not st.session_state["dba_df_copy"].empty:
        df_copy = st.session_state["dba_df_copy"]
        render_priority_dataframe(
            df_copy,
            title="Copy history rows to review",
            priority_columns=[
                "TABLE_NAME", "FILE_NAME", "STATUS", "ROW_COUNT",
                "FIRST_ERROR_MESSAGE", "LAST_LOAD_TIME",
            ],
            sort_by=["STATUS", "LAST_LOAD_TIME", "ROW_COUNT"],
            ascending=[True, False, False],
            raw_label="All copy history rows",
        )
        download_csv(df_copy, "copy_history.csv")


def render_snowpipe_monitor_tool(session, company: str) -> None:
    st.subheader("Snowpipe Monitor")
    sp_days = day_window_selectbox("Lookback", key="spipe_days", default=7)
    if _load_button("Load Pipe Usage", "spipe_load"):
        try:
            st.session_state["dba_df_pipe"] = run_query(f"""
                SELECT pipe_name, DATE_TRUNC('day', start_time) AS day,
                       SUM(credits_used) AS daily_credits,
                       SUM(bytes_inserted)/POWER(1024,3) AS gb_inserted,
                       SUM(files_inserted) AS files_inserted
                FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
                WHERE start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                GROUP BY pipe_name, day ORDER BY daily_credits DESC
            """, ttl_key=f"dba_pipe_{company}_{sp_days}", tier="standard")
        except Exception as e:
            st.warning(f"Snowpipe usage unavailable: {format_snowflake_error(e)}")
    if st.session_state.get("dba_df_pipe") is not None:
        render_priority_dataframe(
            st.session_state["dba_df_pipe"],
            title="Snowpipe cost and volume",
            priority_columns=["PIPE_NAME", "DAY", "DAILY_CREDITS", "GB_INSERTED", "FILES_INSERTED"],
            sort_by=["DAILY_CREDITS", "GB_INSERTED", "FILES_INSERTED"],
            ascending=[False, False, False],
            raw_label="All Snowpipe rows",
        )


def render_dynamic_tables_tool(session, company: str) -> None:
    st.subheader("Dynamic Tables")
    if st.button("Load Dynamic Tables", key="dyn_load"):
        try:
            df_dyn = _show_to_df(session, "SHOW DYNAMIC TABLES IN ACCOUNT")
            df_dyn = _ensure_column_alias(df_dyn, "NAME", ["NAME", "DYNAMIC_TABLE_NAME"])
            df_dyn = _ensure_column_alias(df_dyn, "DATABASE_NAME", ["DATABASE_NAME", "DATABASE"])
            df_dyn = _ensure_column_alias(df_dyn, "SCHEMA_NAME", ["SCHEMA_NAME", "SCHEMA"])
            df_dyn = _scope_metadata_df(df_dyn)
            if not df_dyn.empty:
                try:
                    refresh_object = "SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY"
                    requested_cols = [
                        "DATABASE_NAME", "SCHEMA_NAME", "NAME", "DYNAMIC_TABLE_NAME", "STATE_CODE",
                        "STATE_MESSAGE", "REFRESH_ACTION", "REFRESH_TRIGGER",
                        "REFRESH_START_TIME", "REFRESH_END_TIME", "TARGET_LAG_SEC", "QUERY_ID",
                    ]
                    available_cols = filter_existing_columns(session, refresh_object, requested_cols)
                    if "REFRESH_START_TIME" not in available_cols:
                        raise ValueError("Dynamic table refresh history does not expose REFRESH_START_TIME.")
                    name_expr = (
                        "NAME AS NAME"
                        if "NAME" in available_cols
                        else "DYNAMIC_TABLE_NAME AS NAME"
                        if "DYNAMIC_TABLE_NAME" in available_cols
                        else "'UNKNOWN' AS NAME"
                    )
                    select_cols = [
                        "DATABASE_NAME" if "DATABASE_NAME" in available_cols else "NULL::VARCHAR AS DATABASE_NAME",
                        "SCHEMA_NAME" if "SCHEMA_NAME" in available_cols else "NULL::VARCHAR AS SCHEMA_NAME",
                        name_expr,
                    ]
                    select_cols.extend([
                        col for col in available_cols
                        if col not in {"DATABASE_NAME", "SCHEMA_NAME", "NAME", "DYNAMIC_TABLE_NAME"}
                    ])
                    db_filter = get_db_filter_clause("database_name") if "DATABASE_NAME" in available_cols else ""
                    df_refresh = run_query_or_raise(f"""
                        SELECT {", ".join(select_cols)}
                        FROM {refresh_object}
                        WHERE refresh_start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                          {db_filter}
                        ORDER BY refresh_start_time DESC
                        LIMIT 5000
                    """)
                    if not df_refresh.empty and all(c in df_dyn.columns for c in ["DATABASE_NAME", "SCHEMA_NAME", "NAME"]):
                        refresh_cols = {
                            "STATE_CODE": "LAST_REFRESH_STATE_CODE",
                            "STATE_MESSAGE": "LAST_REFRESH_MESSAGE",
                            "REFRESH_START_TIME": "LAST_REFRESH_START_TIME",
                            "REFRESH_END_TIME": "LAST_REFRESH_END_TIME",
                            "QUERY_ID": "LAST_REFRESH_QUERY_ID",
                        }
                        df_refresh = df_refresh.rename(
                            columns={src: dst for src, dst in refresh_cols.items() if src in df_refresh.columns}
                        )
                        if "LAST_REFRESH_START_TIME" in df_refresh.columns:
                            df_refresh = df_refresh.sort_values("LAST_REFRESH_START_TIME", ascending=False)
                        keep_cols = [
                            c for c in [
                                "DATABASE_NAME", "SCHEMA_NAME", "NAME",
                                "LAST_REFRESH_STATE", "LAST_REFRESH_STATE_CODE", "LAST_REFRESH_MESSAGE",
                                "REFRESH_ACTION", "REFRESH_TRIGGER",
                                "LAST_REFRESH_START_TIME", "LAST_REFRESH_END_TIME",
                                "TARGET_LAG_SEC", "LAST_REFRESH_QUERY_ID",
                            ]
                            if c in df_refresh.columns
                        ]
                        df_refresh = df_refresh[keep_cols].drop_duplicates(["DATABASE_NAME", "SCHEMA_NAME", "NAME"])
                        df_dyn = df_dyn.merge(
                            df_refresh,
                            how="left",
                            on=["DATABASE_NAME", "SCHEMA_NAME", "NAME"],
                        )
                except Exception:
                    pass
            st.session_state["dba_df_dyn"] = df_dyn
        except Exception as e:
            st.info(f"Dynamic table data unavailable: {format_snowflake_error(e)}")
    if st.session_state.get("dba_df_dyn") is not None:
        df_dyn = st.session_state["dba_df_dyn"]
        render_priority_dataframe(
            df_dyn,
            title="Dynamic tables needing attention",
            priority_columns=[
                "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                "LAST_REFRESH_STATE_CODE", "LAST_REFRESH_MESSAGE",
                "REFRESH_ACTION", "LAST_REFRESH_START_TIME", "TARGET_LAG_SEC",
            ],
            sort_by=["LAST_REFRESH_STATE_CODE", "LAST_REFRESH_START_TIME", "TARGET_LAG_SEC"],
            ascending=[True, False, False],
            raw_label="All dynamic table rows",
        )
        download_csv(df_dyn, "dynamic_tables.csv")


def render_replication_tool(session, company: str) -> None:
    st.subheader("Replication")
    repl_days = day_window_selectbox("Lookback", key="repl_days", default=30)
    if st.button("Load Replication History", key="repl_load"):
        repl_sql_primary = f"""
            SELECT database_name,
                   replication_group_name,
                   phase_name,
                   start_time,
                   end_time,
                   DATEDIFF('minute', start_time, end_time) AS duration_min,
                   credits_used,
                   bytes_transferred/POWER(1024,3) AS gb_transferred
            FROM SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_GROUP_USAGE_HISTORY
            WHERE start_time >= DATEADD('day', -{repl_days}, CURRENT_TIMESTAMP())
              {get_db_filter_clause("database_name")}
            ORDER BY start_time DESC
            LIMIT 500
        """
        repl_sql_fallback = f"""
            SELECT database_name,
                   replication_group_name,
                   phase_name,
                   start_time,
                   end_time,
                   DATEDIFF('minute', start_time, end_time) AS duration_min,
                   credits_used,
                   bytes_transferred/POWER(1024,3) AS gb_transferred
            FROM SNOWFLAKE.ACCOUNT_USAGE.REPLICATION_USAGE_HISTORY
            WHERE start_time >= DATEADD('day', -{repl_days}, CURRENT_TIMESTAMP())
              {get_db_filter_clause("database_name")}
            ORDER BY start_time DESC
            LIMIT 500
        """
        try:
            st.session_state["dba_df_repl"] = run_query_or_raise(repl_sql_primary)
            st.session_state["dba_repl_source"] = "REPLICATION_GROUP_USAGE_HISTORY"
        except Exception as primary_error:
            try:
                st.session_state["dba_df_repl"] = run_query_or_raise(repl_sql_fallback)
                st.session_state["dba_repl_source"] = "REPLICATION_USAGE_HISTORY"
            except Exception as fallback_error:
                st.info(f"Replication data unavailable: {format_snowflake_error(fallback_error)}")
                st.caption(f"Primary view also failed: {format_snowflake_error(primary_error)}")
    if st.session_state.get("dba_df_repl") is not None and not st.session_state["dba_df_repl"].empty:
        df_repl = st.session_state["dba_df_repl"]
        st.caption(f"Measurement: {st.session_state.get('dba_repl_source', 'replication usage history')}")
        render_shell_snapshot((("Replication Credits", format_credits(df_repl["CREDITS_USED"].sum())),))
        render_priority_dataframe(
            df_repl,
            title="Replication cost and lag candidates",
            priority_columns=[
                "DATABASE_NAME", "REPLICATION_GROUP_NAME", "PHASE_NAME",
                "START_TIME", "END_TIME", "DURATION_MIN", "CREDITS_USED",
                "GB_TRANSFERRED",
            ],
            sort_by=["CREDITS_USED", "DURATION_MIN", "START_TIME"],
            ascending=[False, False, False],
            raw_label="All replication history rows",
        )
        download_csv(df_repl, "replication_history.csv")
