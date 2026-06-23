# sections/dba_tools_object_monitoring_view.py - Read-only DBA object monitoring render branches.

import streamlit as st

from sections.dba_tools_common import _load_button
from utils import (
    company_value_allowed,
    day_window_selectbox,
    download_csv,
    format_snowflake_error,
    get_active_company,
    get_db_filter_clause,
    get_user_company_filter_clause,
    load_database_options,
    run_query,
    sql_literal,
)
from utils.workflows import render_priority_dataframe



def render_network_sessions_tool(session, company: str) -> None:
    st.subheader("Network & Sessions")
    if _load_button("Load Session Data", "net_load"):
        try:
            st.session_state["dba_df_long_sess"] = run_query(f"""
                SELECT session_id, user_name, created_on,
                       DATEDIFF('hour', created_on, CURRENT_TIMESTAMP()) AS session_hours
                FROM SNOWFLAKE.ACCOUNT_USAGE.SESSIONS
                WHERE created_on >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                  AND DATEDIFF('hour', created_on, CURRENT_TIMESTAMP()) > 8
                  {get_user_company_filter_clause("user_name", company)}
                ORDER BY session_hours DESC LIMIT 100
            """, ttl_key=f"dba_long_sessions_{company}", tier="standard")
        except Exception as e:
            st.info(f"Sessions unavailable: {format_snowflake_error(e)}")
    if st.session_state.get("dba_df_long_sess") is not None:
        render_priority_dataframe(
            st.session_state["dba_df_long_sess"],
            title="Long-running sessions",
            priority_columns=["SESSION_ID", "USER_NAME", "CREATED_ON", "SESSION_HOURS"],
            sort_by=["SESSION_HOURS"],
            ascending=False,
            raw_label="All long-session rows",
        )


def render_unused_objects_tool(session, company: str) -> None:
    st.subheader("Unused Objects")
    if _load_button("Find Unused Tables", "unused_load"):
        try:
            st.session_state["dba_df_unused"] = run_query(f"""
                SELECT table_catalog, table_schema, table_name, row_count,
                       bytes/POWER(1024,3) AS table_gb, created, last_altered
                FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                WHERE deleted IS NULL
                  AND last_altered < DATEADD('day', -90, CURRENT_TIMESTAMP())
                  {get_db_filter_clause("table_catalog")}
                ORDER BY bytes DESC NULLS LAST LIMIT 200
            """, ttl_key=f"dba_unused_tables_{company}", tier="standard")
        except Exception as e:
            st.warning(f"Unused table scan unavailable: {format_snowflake_error(e)}")
    if st.session_state.get("dba_df_unused") is not None:
        render_priority_dataframe(
            st.session_state["dba_df_unused"],
            title="Unused objects by size",
            priority_columns=[
                "TABLE_CATALOG", "TABLE_SCHEMA", "TABLE_NAME", "ROW_COUNT",
                "TABLE_GB", "CREATED", "LAST_ALTERED",
            ],
            sort_by=["TABLE_GB", "ROW_COUNT"],
            ascending=[False, False],
            raw_label="All unused object rows",
        )


def render_recent_objects_tool(session, company: str) -> None:
    st.subheader("Recent Objects")
    obj_days = day_window_selectbox("Created/altered within", key="obj_days", default=30)
    refresh_obj_meta = st.button("Refresh database choices", key="obj_refresh_metadata")
    if refresh_obj_meta or "obj_database_options" not in st.session_state:
        st.session_state["obj_database_options"] = load_database_options(
            session,
            company=get_active_company(),
            force_refresh=bool(refresh_obj_meta),
        )
    obj_database_options = list(st.session_state.get("obj_database_options") or [])
    if obj_database_options:
        obj_database_choices = ["All scoped databases"] + obj_database_options
        if st.session_state.get("obj_database_filter") not in obj_database_choices:
            st.session_state["obj_database_filter"] = "All scoped databases"
        obj_database = st.selectbox(
            "Database",
            obj_database_choices,
            key="obj_database_filter",
        )
        obj_db_clause = (
            f"AND table_catalog = {sql_literal(obj_database)}"
            if obj_database != "All scoped databases"
            else ""
        )
        obj_filter_key = obj_database
    else:
        obj_db_filter = st.text_input("Database contains", key="obj_db_filter")
        if obj_db_filter and not company_value_allowed(obj_db_filter, "database"):
            st.caption("Entered database text is outside the active company/environment scope and will only match if visible.")
        obj_db_clause = (
            f"AND table_catalog ILIKE {sql_literal('%' + obj_db_filter + '%')}"
            if obj_db_filter else ""
        )
        obj_filter_key = obj_db_filter
    if st.button("Load Recent Objects", key="obj_load"):
        try:
            st.session_state["dba_df_recent_objects"] = run_query(f"""
                SELECT table_catalog AS database_name, table_schema AS schema_name,
                       table_name AS object_name, table_type, created, last_altered, table_owner AS owner
                FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                WHERE deleted IS NULL
                  AND (created >= DATEADD('day', -{obj_days}, CURRENT_TIMESTAMP())
                       OR last_altered >= DATEADD('day', -{obj_days}, CURRENT_TIMESTAMP()))
                  {obj_db_clause}
                  {get_db_filter_clause("table_catalog")}
                ORDER BY GREATEST(created, last_altered) DESC LIMIT 500
            """, ttl_key=f"dba_recent_objects_{company}_{obj_days}_{obj_filter_key}", tier="metadata")
        except Exception as e:
            st.warning(f"Recent objects unavailable: {format_snowflake_error(e)}")
    if st.session_state.get("dba_df_recent_objects") is not None:
        df_recent = st.session_state["dba_df_recent_objects"]
        render_priority_dataframe(
            df_recent,
            title="Recent object changes",
            priority_columns=[
                "DATABASE_NAME", "SCHEMA_NAME", "OBJECT_NAME",
                "TABLE_TYPE", "OWNER", "CREATED", "LAST_ALTERED",
            ],
            sort_by=["CREATED", "LAST_ALTERED"],
            ascending=[False, False],
            raw_label="All recent object rows",
        )
        download_csv(df_recent, "recent_objects.csv")
