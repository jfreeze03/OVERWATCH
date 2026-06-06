# sections/platform_topology.py - relationship maps for teams, objects, and workloads
import streamlit as st

from utils import (
    day_window_selectbox,
    defer_source_note,
    download_csv,
    get_active_company,
    format_snowflake_error,
    get_global_filter_clause,
    get_session,
    get_user_filter_clause,
    filter_existing_columns,
    freshness_note,
    metric_confidence_label,
    render_drillable_bar_chart,
    render_ranked_bar_chart,
    run_query,
)
from utils.workflows import render_priority_dataframe


PLATFORM_TOPOLOGY_PANES = (
    "Warehouse To User",
    "Database To Schema",
    "Roles",
    "Application Flows",
    "Report Pack",
)


def _altair():
    """Import Altair only after topology chart data is loaded."""
    import altair as alt

    return alt


def _load_topology(session, days: int, row_limit: int) -> dict:
    company = get_active_company()
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["BYTES_SCANNED", "ERROR_CODE", "QUERY_TAG", "SESSION_ID", "AUTHN_EVENT_ID", "IS_CLIENT_GENERATED_STATEMENT"],
    ))
    session_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.SESSIONS",
        ["SESSION_ID", "CREATED_ON", "CLIENT_APPLICATION_ID", "CLIENT_APPLICATION_VERSION", "CLIENT_VERSION"],
    ))
    login_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY",
        ["EVENT_ID", "REPORTED_CLIENT_TYPE", "REPORTED_CLIENT_VERSION"],
    ))
    gb_scanned_expr = (
        "ROUND(SUM(q.bytes_scanned) / POWER(1024, 3), 2)"
        if "BYTES_SCANNED" in qh_cols else "0::FLOAT"
    )
    failed_expr = (
        "SUM(IFF(q.error_code IS NOT NULL, 1, 0))"
        if "ERROR_CODE" in qh_cols
        else "SUM(IFF(UPPER(q.execution_status) = 'FAILED_WITH_ERROR', 1, 0))"
    )
    session_version_candidates = []
    if "CLIENT_APPLICATION_VERSION" in session_cols:
        session_version_candidates.append("TO_VARCHAR(s.client_application_version)")
    if "CLIENT_VERSION" in session_cols:
        session_version_candidates.append("TO_VARCHAR(s.client_version)")
    session_version_expr = (
        f"COALESCE({', '.join(session_version_candidates)}, 'UNKNOWN')"
        if session_version_candidates else "'UNKNOWN'"
    )
    can_join_sessions = "SESSION_ID" in qh_cols and "SESSION_ID" in session_cols
    can_join_login = "AUTHN_EVENT_ID" in qh_cols and "EVENT_ID" in login_cols
    if can_join_sessions:
        client_expr = (
            "COALESCE(TO_VARCHAR(s.client_application_id), 'UNKNOWN')"
            if "CLIENT_APPLICATION_ID" in session_cols else "'UNKNOWN'"
        )
        client_version_expr = session_version_expr
        app_join = f"""
            LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.SESSIONS s
              ON q.session_id = s.session_id
             AND s.created_on >= DATEADD('day', -{min(365, int(days) + 14)}, CURRENT_TIMESTAMP())
        """
        app_source_expr = "'QUERY_HISTORY session_id to SESSIONS client metadata'"
    elif can_join_login:
        client_expr = (
            "COALESCE(TO_VARCHAR(l.reported_client_type), 'UNKNOWN')"
            if "REPORTED_CLIENT_TYPE" in login_cols else "'UNKNOWN'"
        )
        client_version_expr = (
            "COALESCE(TO_VARCHAR(l.reported_client_version), 'UNKNOWN')"
            if "REPORTED_CLIENT_VERSION" in login_cols else "'UNKNOWN'"
        )
        app_join = f"""
            LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY l
              ON q.authn_event_id = l.event_id
             AND l.event_timestamp >= DATEADD('day', -{min(365, int(days) + 14)}, CURRENT_TIMESTAMP())
        """
        app_source_expr = "'AUTHN_EVENT_ID to LOGIN_HISTORY reported client; client value is reported, not authenticated'"
    else:
        client_expr = (
            "COALESCE(NULLIF(TO_VARCHAR(q.query_tag), ''), 'UNTAGGED')"
            if "QUERY_TAG" in qh_cols else "'UNKNOWN'"
        )
        client_version_expr = "'UNKNOWN'"
        app_join = ""
        app_source_expr = "'QUERY_TAG fallback; not exact connected-program identity'"
    client_generated_expr = (
        "SUM(IFF(q.is_client_generated_statement, 1, 0))"
        if "IS_CLIENT_GENERATED_STATEMENT" in qh_cols else "NULL::NUMBER"
    )
    filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )

    warehouse_user = run_query(f"""
        SELECT
            q.warehouse_name,
            q.user_name,
            COALESCE(q.role_name, 'UNKNOWN') AS role_name,
            COUNT(*) AS query_count,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            {gb_scanned_expr} AS gb_scanned,
            {failed_expr} AS failed_queries
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY q.warehouse_name, q.user_name, COALESCE(q.role_name, 'UNKNOWN')
        ORDER BY query_count DESC
        LIMIT {row_limit}
    """, ttl_key=f"topology_wh_user_{company}_{days}_{row_limit}", tier="standard", section="Platform Topology")

    db_schema = run_query(f"""
        SELECT
            COALESCE(q.database_name, 'UNKNOWN') AS database_name,
            COALESCE(q.schema_name, 'UNKNOWN') AS schema_name,
            COUNT(DISTINCT q.user_name) AS users,
            COUNT(DISTINCT q.role_name) AS roles,
            COUNT(*) AS query_count,
            {failed_expr} AS failed_queries
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY database_name, schema_name
        ORDER BY query_count DESC
        LIMIT {row_limit}
    """, ttl_key=f"topology_db_schema_{company}_{days}_{row_limit}", tier="standard", section="Platform Topology")

    role_users = run_query(f"""
        SELECT
            role,
            grantee_name AS user_name,
            granted_by,
            created_on,
            deleted_on
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
        WHERE deleted_on IS NULL
          {get_user_filter_clause("grantee_name")}
        ORDER BY role, user_name
        LIMIT {row_limit}
    """, ttl_key=f"topology_role_users_{company}_{row_limit}", tier="standard", section="Platform Topology")

    app_flow = run_query(f"""
        SELECT
            {client_expr} AS client_application,
            {client_version_expr} AS client_version,
            q.warehouse_name,
            COALESCE(q.database_name, 'UNKNOWN') AS database_name,
            COUNT(DISTINCT q.user_name) AS users,
            COUNT(*) AS query_count,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            {failed_expr} AS failed_queries,
            {client_generated_expr} AS client_generated_queries,
            MAX(q.start_time) AS last_query_time,
            {app_source_expr} AS source_confidence
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        {app_join}
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY client_application, client_version, q.warehouse_name, database_name, source_confidence
        ORDER BY query_count DESC
        LIMIT {row_limit}
    """, ttl_key=f"topology_app_flow_{company}_{days}_{row_limit}", tier="standard", section="Platform Topology")

    return {
        "warehouse_user": warehouse_user,
        "db_schema": db_schema,
        "role_users": role_users,
        "app_flow": app_flow,
    }


def render():
    session = get_session()
    st.header("Platform Topology")
    st.caption("Relationship maps showing who uses which warehouses, databases, roles, and client applications.")

    days = day_window_selectbox("Lookback", key="topology_days", default=30)
    row_limit = st.slider("Max rows per topology query", 100, 1000, 250, step=50, key="topology_row_limit")
    if days > 30 and row_limit > 500:
        defer_source_note("Large topology windows can scan more ACCOUNT_USAGE history; start with KPIs and raise limits only for exports.")
    if st.button("Load Platform Topology", key="topology_load"):
        with st.spinner("Building topology views..."):
            try:
                st.session_state["topology_data"] = _load_topology(session, days, row_limit)
            except Exception as e:
                st.warning(f"Platform topology unavailable in this role/context: {format_snowflake_error(e)}")

    data = st.session_state.get("topology_data")
    if not data:
        return
    defer_source_note(
        metric_confidence_label("estimated"),
        freshness_note("ACCOUNT_USAGE"),
        "Role grants are scoped by user patterns when no warehouse/database signal exists.",
    )

    wh_user = data["warehouse_user"]
    db_schema = data["db_schema"]
    role_users = data["role_users"]
    app_flow = data["app_flow"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Warehouse/User Links", f"{len(wh_user):,}")
    c2.metric("Database/Schema Links", f"{len(db_schema):,}")
    c3.metric("Active Role Grants", f"{len(role_users):,}")
    c4.metric("Application Flows", f"{len(app_flow):,}")

    active_view = st.radio(
        "Platform topology view",
        PLATFORM_TOPOLOGY_PANES,
        horizontal=True,
        label_visibility="collapsed",
        key="platform_topology_active_view",
    )

    if active_view == "Warehouse To User":
        if not wh_user.empty:
            wh_summary = wh_user.groupby("WAREHOUSE_NAME", as_index=False).agg({
                "QUERY_COUNT": "sum",
                "USER_NAME": "nunique",
                "FAILED_QUERIES": "sum",
            }).rename(columns={"USER_NAME": "USERS"})
            render_drillable_bar_chart(
                wh_summary,
                dimension="WAREHOUSE_NAME",
                measure="QUERY_COUNT",
                key="topology_wh",
                title="Warehouse Workload Map",
                drilldown_column="warehouse_name",
                lookback_hours=24 * min(days, 14),
                top_n=20,
            )
            render_priority_dataframe(
                wh_user,
                title="Warehouse/user relationships to inspect",
                priority_columns=[
                    "WAREHOUSE_NAME", "USER_NAME", "ROLE_NAME", "QUERY_COUNT",
                    "FAILED_QUERIES", "GB_SCANNED", "LAST_QUERY_TIME",
                ],
                sort_by=["QUERY_COUNT", "FAILED_QUERIES", "GB_SCANNED"],
                ascending=[False, False, False],
                raw_label="All warehouse/user rows",
                height=360,
            )
            download_csv(wh_user, "platform_topology_warehouse_user.csv")
        else:
            st.info("No warehouse/user relationships found.")

    elif active_view == "Database To Schema":
        if not db_schema.empty:
            alt = _altair()
            chart = alt.Chart(db_schema.head(50)).mark_rect().encode(
                x=alt.X("DATABASE_NAME:N", title=None),
                y=alt.Y("SCHEMA_NAME:N", title=None),
                color=alt.Color("QUERY_COUNT:Q", title="Queries"),
                tooltip=["DATABASE_NAME", "SCHEMA_NAME", "USERS", "ROLES", "QUERY_COUNT", "FAILED_QUERIES"],
            ).properties(height=420)
            st.altair_chart(chart, width="stretch")
            render_priority_dataframe(
                db_schema,
                title="Database/schema workload relationships",
                priority_columns=[
                    "DATABASE_NAME", "SCHEMA_NAME", "USERS", "ROLES",
                    "QUERY_COUNT", "FAILED_QUERIES", "GB_SCANNED",
                ],
                sort_by=["QUERY_COUNT", "FAILED_QUERIES", "GB_SCANNED"],
                ascending=[False, False, False],
                raw_label="All database/schema rows",
                height=360,
            )
            download_csv(db_schema, "platform_topology_database_schema.csv")
        else:
            st.info("No database/schema relationships found.")

    elif active_view == "Roles":
        if not role_users.empty:
            role_summary = role_users.groupby("ROLE", as_index=False)["USER_NAME"].nunique().rename(columns={"USER_NAME": "USERS"})
            render_ranked_bar_chart(role_summary, "ROLE", "USERS", title="Users Per Role", top_n=25)
            render_priority_dataframe(
                role_users,
                title="Role/user assignments",
                priority_columns=["ROLE", "USER_NAME", "GRANTED_ON", "GRANTED_BY", "CREATED_ON"],
                sort_by=["ROLE", "USER_NAME"],
                ascending=[True, True],
                raw_label="All role/user rows",
                height=360,
            )
            download_csv(role_users, "platform_topology_role_users.csv")
        else:
            st.info("No active role grants found.")

    elif active_view == "Application Flows":
        if not app_flow.empty:
            app_summary = app_flow.groupby("CLIENT_APPLICATION", as_index=False).agg({
                "QUERY_COUNT": "sum",
                "USERS": "sum",
                "FAILED_QUERIES": "sum",
            }).sort_values("QUERY_COUNT", ascending=False)
            render_ranked_bar_chart(
                app_summary,
                "CLIENT_APPLICATION",
                "QUERY_COUNT",
                title="Top Connected Programs By Queries",
                top_n=25,
            )
            render_priority_dataframe(
                app_flow,
                title="Application flow drivers",
                priority_columns=[
                    "CLIENT_APPLICATION", "CLIENT_VERSION", "WAREHOUSE_NAME", "DATABASE_NAME",
                    "USERS", "QUERY_COUNT", "FAILED_QUERIES", "CLIENT_GENERATED_QUERIES",
                    "LAST_QUERY_TIME", "SOURCE_CONFIDENCE",
                ],
                sort_by=["QUERY_COUNT", "FAILED_QUERIES"],
                ascending=[False, False],
                raw_label="All application flow rows",
                height=360,
            )
            download_csv(app_flow, "platform_topology_application_flows.csv")
        else:
            st.info("No application flows found.")

    elif active_view == "Report Pack":
        st.subheader("Topology Report Pack")
        st.caption("Use these exports for architecture reviews, access cleanups, and cost ownership conversations.")
        download_csv(wh_user, "topology_report_warehouse_user.csv", "Export Warehouse/User Map")
        download_csv(db_schema, "topology_report_database_schema.csv", "Export Database/Schema Map")
        download_csv(role_users, "topology_report_role_users.csv", "Export Role/User Map")
        download_csv(app_flow, "topology_report_application_flows.csv", "Export Application Flow Map")
