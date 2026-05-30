# sections/adoption_analytics.py - user and workload adoption analytics
import altair as alt
import streamlit as st

from utils import (
    build_mart_adoption_role_type_sql,
    build_mart_adoption_summary_sql,
    build_mart_adoption_trend_sql,
    build_mart_adoption_users_db_sql,
    build_mart_adoption_users_wh_sql,
    build_mart_adoption_warehouse_size_sql,
    download_csv,
    filter_existing_columns,
    get_active_company,
    get_global_filter_clause,
    get_session,
    format_snowflake_error,
    render_drillable_bar_chart,
    run_query,
    safe_float,
)


def _load_adoption_mart(days: int) -> dict:
    company = get_active_company()
    return {
        "summary": run_query(build_mart_adoption_summary_sql(days, company), ttl_key=f"aa_summary_mart_{company}_{days}", tier="historical"),
        "warehouse_size": run_query(build_mart_adoption_warehouse_size_sql(days, company), ttl_key=f"aa_warehouse_size_mart_{company}_{days}", tier="historical"),
        "trend": run_query(build_mart_adoption_trend_sql(days, company), ttl_key=f"aa_trend_mart_{company}_{days}", tier="historical"),
        "users_wh": run_query(build_mart_adoption_users_wh_sql(days, company), ttl_key=f"aa_users_wh_mart_{company}_{days}", tier="historical"),
        "users_db": run_query(build_mart_adoption_users_db_sql(days, company), ttl_key=f"aa_users_db_mart_{company}_{days}", tier="historical"),
        "by_role_type": run_query(build_mart_adoption_role_type_sql(days, company), ttl_key=f"aa_role_type_mart_{company}_{days}", tier="historical"),
        "applications": None,
        "source": "OVERWATCH mart: FACT_QUERY_HOURLY",
    }


def _load_adoption_live(session, days: int) -> dict:
    company = get_active_company()
    filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE", "ERROR_CODE", "QUERY_TAG"],
    ))
    warehouse_size_expr = (
        "COALESCE(q.warehouse_size, 'UNKNOWN')"
        if "WAREHOUSE_SIZE" in qh_cols else "'UNKNOWN'"
    )
    error_count_expr = (
        "SUM(IFF(q.error_code IS NOT NULL, 1, 0))"
        if "ERROR_CODE" in qh_cols
        else "SUM(IFF(UPPER(q.execution_status) = 'FAILED_WITH_ERROR', 1, 0))"
    )
    client_application_expr = (
        "COALESCE(q.query_tag, 'UNTAGGED')"
        if "QUERY_TAG" in qh_cols else "'UNTAGGED'"
    )

    summary = run_query(f"""
        SELECT
            COUNT(*) AS total_queries,
            COUNT(DISTINCT q.user_name) AS total_users,
            ROUND(COUNT(*) / NULLIF(COUNT(DISTINCT q.user_name), 0), 1) AS queries_per_user,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_time_per_query_sec,
            ROUND(100 * {error_count_expr} / NULLIF(COUNT(*), 0), 1) AS error_rate
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
    """, ttl_key=f"aa_summary_{company}_{days}", tier="historical")

    warehouse_size = run_query(f"""
        SELECT
            {warehouse_size_expr} AS warehouse_size,
            COUNT(*) AS query_count,
            COUNT(DISTINCT q.user_name) AS users,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY warehouse_size
        ORDER BY query_count DESC
    """, ttl_key=f"aa_warehouse_size_{company}_{days}", tier="historical")

    trend = run_query(f"""
        SELECT
            DATE_TRUNC('day', q.start_time) AS activity_day,
            COUNT(*) AS total_queries,
            COUNT(DISTINCT q.user_name) AS users,
            ROUND(COUNT(*) / NULLIF(COUNT(DISTINCT q.user_name), 0), 1) AS queries_per_user,
            ROUND(100 * {error_count_expr} / NULLIF(COUNT(*), 0), 1) AS error_rate
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY activity_day
        ORDER BY activity_day
    """, ttl_key=f"aa_trend_{company}_{days}", tier="historical")

    users_wh = run_query(f"""
        SELECT
            q.warehouse_name,
            COUNT(DISTINCT q.user_name) AS users,
            COUNT(*) AS query_count,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY q.warehouse_name
        ORDER BY users DESC, query_count DESC
        LIMIT 50
    """, ttl_key=f"aa_users_wh_{company}_{days}", tier="historical")

    users_db = run_query(f"""
        SELECT
            COALESCE(q.database_name, 'UNKNOWN') AS database_name,
            COUNT(DISTINCT q.user_name) AS users,
            COUNT(*) AS query_count,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY database_name
        ORDER BY users DESC, query_count DESC
        LIMIT 50
    """, ttl_key=f"aa_users_db_{company}_{days}", tier="historical")

    by_role_type = run_query(f"""
        SELECT
            COALESCE(q.role_name, 'UNKNOWN') AS role_name,
            COALESCE(q.query_type, 'UNKNOWN') AS query_type,
            COUNT(*) AS query_count,
            COUNT(DISTINCT q.user_name) AS users
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY role_name, query_type
        ORDER BY query_count DESC
        LIMIT 100
    """, ttl_key=f"aa_role_type_{company}_{days}", tier="historical")

    applications = run_query(f"""
        SELECT
            {client_application_expr} AS client_application,
            COUNT(*) AS query_count,
            COUNT(DISTINCT q.user_name) AS users,
            ROUND(100 * {error_count_expr} / NULLIF(COUNT(*), 0), 1) AS error_rate
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {filters}
        GROUP BY client_application
        ORDER BY query_count DESC
        LIMIT 30
    """, ttl_key=f"aa_applications_{company}_{days}", tier="historical")

    return {
        "summary": summary,
        "warehouse_size": warehouse_size,
        "trend": trend,
        "users_wh": users_wh,
        "users_db": users_db,
        "by_role_type": by_role_type,
        "applications": applications,
        "source": "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
    }


def _load_adoption(session, days: int) -> dict:
    try:
        data = _load_adoption_mart(days)
        summary = data.get("summary")
        if summary is not None and not summary.empty:
            return data
    except Exception:
        pass
    return _load_adoption_live(session, days)


def _metric(df, column: str) -> float:
    if df is None or df.empty or column not in df.columns:
        return 0.0
    return safe_float(df.iloc[0].get(column, 0))


def render():
    session = get_session()
    st.header("Adoption Analytics")
    st.caption("Track which teams, warehouses, databases, roles, and clients are actually using Snowflake.")

    days = st.slider("Lookback days", 7, 180, 30, key="aa_days")
    if st.button("Load Adoption Analytics", key="aa_load"):
        with st.spinner("Loading adoption analytics..."):
            try:
                st.session_state["aa_data"] = _load_adoption(session, days)
            except Exception as e:
                st.warning(f"Adoption analytics unavailable in this role/context: {format_snowflake_error(e)}")

    data = st.session_state.get("aa_data")
    if not data:
        return

    summary = data["summary"]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Queries", f"{_metric(summary, 'TOTAL_QUERIES'):,.0f}")
    m2.metric("Total Users", f"{_metric(summary, 'TOTAL_USERS'):,.0f}")
    m3.metric("Queries/User", f"{_metric(summary, 'QUERIES_PER_USER'):,.1f}")
    m4.metric("Time/Query", f"{_metric(summary, 'AVG_TIME_PER_QUERY_SEC'):,.2f}s")
    m5.metric("Error Rate", f"{_metric(summary, 'ERROR_RATE'):,.1f}%")
    st.caption(data.get("source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))

    tab_trend, tab_wh, tab_db, tab_role = st.tabs(["Trend", "Warehouse Adoption", "Database Adoption", "Role & Workload Mix"])

    with tab_trend:
        trend = data["trend"]
        if not trend.empty:
            chart = alt.Chart(trend).mark_bar().encode(
                x=alt.X("ACTIVITY_DAY:T", title=None),
                y=alt.Y("USERS:Q", title="Users"),
                tooltip=["ACTIVITY_DAY:T", "USERS", "TOTAL_QUERIES", "QUERIES_PER_USER", "ERROR_RATE"],
                color=alt.value("#38bdf8"),
            ).properties(height=260)
            line = alt.Chart(trend).mark_line(color="#f59e0b").encode(
                x="ACTIVITY_DAY:T",
                y=alt.Y("QUERIES_PER_USER:Q", title="Queries/User"),
                tooltip=["ACTIVITY_DAY:T", "QUERIES_PER_USER"],
            )
            st.altair_chart(alt.layer(chart, line).resolve_scale(y="independent"), use_container_width=True)
            download_csv(trend, "adoption_trend.csv")
        else:
            st.info("No adoption trend data found.")

        size_df = data["warehouse_size"]
        if not size_df.empty:
            st.subheader("Queries By Warehouse Size")
            st.bar_chart(size_df.set_index("WAREHOUSE_SIZE")["QUERY_COUNT"], use_container_width=True)

    with tab_wh:
        render_drillable_bar_chart(data["users_wh"], "WAREHOUSE_NAME", "USERS", "aa_users_wh", "Users Per Warehouse", "warehouse_name", 24 * min(days, 14), 20)
        download_csv(data["users_wh"], "adoption_users_per_warehouse.csv")

    with tab_db:
        render_drillable_bar_chart(data["users_db"], "DATABASE_NAME", "USERS", "aa_users_db", "Users Per Database", "database_name", 24 * min(days, 14), 20)
        download_csv(data["users_db"], "adoption_users_per_database.csv")

    with tab_role:
        role = data["by_role_type"]
        apps = data["applications"]
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Query Types By Role")
            st.dataframe(role, use_container_width=True, height=360)
            download_csv(role, "adoption_role_query_type.csv")
        with c2:
            st.subheader("Top Query Tags")
            if apps is None:
                st.info("Query-tag adoption is intentionally deferred in mart mode. Use History Search when you need exact query-tag evidence.")
            elif not apps.empty:
                chart = alt.Chart(apps).mark_bar().encode(
                    x=alt.X("QUERY_COUNT:Q", title="Queries"),
                    y=alt.Y("CLIENT_APPLICATION:N", sort="-x", title=None),
                    tooltip=["CLIENT_APPLICATION", "QUERY_COUNT", "USERS", "ERROR_RATE"],
                    color=alt.value("#c084fc"),
                ).properties(height=360)
                st.altair_chart(chart, use_container_width=True)
            if apps is not None:
                download_csv(apps, "adoption_query_tags.csv")
