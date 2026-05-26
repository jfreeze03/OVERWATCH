# sections/platform_topology.py - relationship maps for teams, objects, and workloads
import altair as alt
import streamlit as st

from utils import (
    download_csv,
    get_db_filter_clause,
    get_global_filter_clause,
    get_session,
    get_wh_filter_clause,
    normalize_df,
    render_drillable_bar_chart,
)


def _load_topology(session, days: int) -> dict:
    filters = " ".join([
        get_wh_filter_clause("q.warehouse_name"),
        get_db_filter_clause("q.database_name"),
        get_global_filter_clause(
            date_col="q.start_time",
            wh_col="q.warehouse_name",
            user_col="q.user_name",
            role_col="q.role_name",
            db_col="q.database_name",
        ),
    ])

    warehouse_user = normalize_df(session.sql(f"""
        SELECT
            q.warehouse_name,
            q.user_name,
            COALESCE(q.role_name, 'UNKNOWN') AS role_name,
            COUNT(*) AS query_count,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            ROUND(SUM(q.bytes_scanned) / POWER(1024, 3), 2) AS gb_scanned,
            SUM(IFF(q.error_code IS NOT NULL, 1, 0)) AS failed_queries
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY q.warehouse_name, q.user_name, COALESCE(q.role_name, 'UNKNOWN')
        ORDER BY query_count DESC
        LIMIT 500
    """).to_pandas())

    db_schema = normalize_df(session.sql(f"""
        SELECT
            COALESCE(q.database_name, 'UNKNOWN') AS database_name,
            COALESCE(q.schema_name, 'UNKNOWN') AS schema_name,
            COUNT(DISTINCT q.user_name) AS users,
            COUNT(DISTINCT q.role_name) AS roles,
            COUNT(*) AS query_count,
            SUM(IFF(q.error_code IS NOT NULL, 1, 0)) AS failed_queries
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY database_name, schema_name
        ORDER BY query_count DESC
        LIMIT 500
    """).to_pandas())

    role_users = normalize_df(session.sql("""
        SELECT
            role,
            grantee_name AS user_name,
            granted_by,
            created_on,
            deleted_on
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
        WHERE deleted_on IS NULL
        ORDER BY role, user_name
        LIMIT 1000
    """).to_pandas())

    app_flow = normalize_df(session.sql(f"""
        SELECT
            COALESCE(q.query_tag, 'UNTAGGED') AS client_application,
            q.warehouse_name,
            COALESCE(q.database_name, 'UNKNOWN') AS database_name,
            COUNT(DISTINCT q.user_name) AS users,
            COUNT(*) AS query_count,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            SUM(IFF(q.error_code IS NOT NULL, 1, 0)) AS failed_queries
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY client_application, q.warehouse_name, database_name
        ORDER BY query_count DESC
        LIMIT 500
    """).to_pandas())

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

    days = st.slider("Lookback days", 1, 90, 30, key="topology_days")
    if st.button("Load Platform Topology", key="topology_load"):
        with st.spinner("Building topology views..."):
            try:
                st.session_state["topology_data"] = _load_topology(session, days)
            except Exception as e:
                st.error(f"Unable to load platform topology: {e}")

    data = st.session_state.get("topology_data")
    if not data:
        return

    wh_user = data["warehouse_user"]
    db_schema = data["db_schema"]
    role_users = data["role_users"]
    app_flow = data["app_flow"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Warehouse/User Links", f"{len(wh_user):,}")
    c2.metric("Database/Schema Links", f"{len(db_schema):,}")
    c3.metric("Active Role Grants", f"{len(role_users):,}")
    c4.metric("Application Flows", f"{len(app_flow):,}")

    tab_wh, tab_db, tab_roles, tab_apps, tab_report = st.tabs([
        "Warehouse To User", "Database To Schema", "Roles", "Application Flows", "Report Pack"
    ])

    with tab_wh:
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
            st.dataframe(wh_user, use_container_width=True, height=360)
            download_csv(wh_user, "platform_topology_warehouse_user.csv")
        else:
            st.info("No warehouse/user relationships found.")

    with tab_db:
        if not db_schema.empty:
            chart = alt.Chart(db_schema.head(50)).mark_rect().encode(
                x=alt.X("DATABASE_NAME:N", title=None),
                y=alt.Y("SCHEMA_NAME:N", title=None),
                color=alt.Color("QUERY_COUNT:Q", title="Queries"),
                tooltip=["DATABASE_NAME", "SCHEMA_NAME", "USERS", "ROLES", "QUERY_COUNT", "FAILED_QUERIES"],
            ).properties(height=420)
            st.altair_chart(chart, use_container_width=True)
            st.dataframe(db_schema, use_container_width=True, height=360)
            download_csv(db_schema, "platform_topology_database_schema.csv")
        else:
            st.info("No database/schema relationships found.")

    with tab_roles:
        if not role_users.empty:
            role_summary = role_users.groupby("ROLE", as_index=False)["USER_NAME"].nunique().rename(columns={"USER_NAME": "USERS"})
            role_summary = role_summary.sort_values("USERS", ascending=False)
            st.bar_chart(role_summary.set_index("ROLE")["USERS"])
            st.dataframe(role_users, use_container_width=True, height=360)
            download_csv(role_users, "platform_topology_role_users.csv")
        else:
            st.info("No active role grants found.")

    with tab_apps:
        if not app_flow.empty:
            app_summary = app_flow.groupby("CLIENT_APPLICATION", as_index=False).agg({
                "QUERY_COUNT": "sum",
                "USERS": "sum",
                "FAILED_QUERIES": "sum",
            }).sort_values("QUERY_COUNT", ascending=False)
            chart = alt.Chart(app_summary.head(25)).mark_bar(color="#38bdf8").encode(
                x=alt.X("QUERY_COUNT:Q", title="Queries"),
                y=alt.Y("CLIENT_APPLICATION:N", sort="-x", title=None),
                tooltip=["CLIENT_APPLICATION", "USERS", "QUERY_COUNT", "FAILED_QUERIES"],
            ).properties(height=420)
            st.altair_chart(chart, use_container_width=True)
            st.dataframe(app_flow, use_container_width=True, height=360)
            download_csv(app_flow, "platform_topology_application_flows.csv")
        else:
            st.info("No application flows found.")

    with tab_report:
        st.subheader("Topology Report Pack")
        st.caption("Use these exports for architecture reviews, access cleanups, and cost ownership conversations.")
        download_csv(wh_user, "topology_report_warehouse_user.csv", "Export Warehouse/User Map")
        download_csv(db_schema, "topology_report_database_schema.csv", "Export Database/Schema Map")
        download_csv(role_users, "topology_report_role_users.csv", "Export Role/User Map")
        download_csv(app_flow, "topology_report_application_flows.csv", "Export Application Flow Map")
