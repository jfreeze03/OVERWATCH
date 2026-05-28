# sections/usage_overview.py - executive Snowflake usage overview
import altair as alt
import streamlit as st

from utils import (
    download_csv,
    format_credits,
    format_snowflake_error,
    get_active_company,
    get_db_filter_clause,
    get_global_filter_clause,
    get_session,
    get_wh_filter_clause,
    render_drillable_bar_chart,
    run_query,
    sql_literal,
    upsert_actions,
)


def _load_overview(session, days: int) -> dict:
    company = get_active_company()
    wh_filter = get_wh_filter_clause("warehouse_name")
    db_filter = get_db_filter_clause("database_name")
    q_filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )

    overview = run_query(f"""
        SELECT
            COUNT(*) AS total_queries,
            COUNT(DISTINCT q.user_name) AS total_users,
            COUNT(DISTINCT q.database_name) AS active_databases,
            ROUND(100 * SUM(IFF(q.error_code IS NULL, 1, 0)) / NULLIF(COUNT(*), 0), 1) AS query_success_rate,
            SUM(IFF(q.error_code IS NOT NULL, 1, 0)) AS failed_queries,
            SUM(IFF(q.queued_overload_time > 0 OR q.queued_provisioning_time > 0 OR q.queued_repair_time > 0, 1, 0)) AS queued_queries,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            ROUND(AVG(q.execution_time) / 1000, 2) AS avg_execution_sec,
            ROUND(SUM(COALESCE(q.credits_used_cloud_services, 0)), 4) AS cloud_service_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {q_filters}
    """, ttl_key=f"uo_overview_{company}_{days}", tier="historical")

    metering = run_query(f"""
        SELECT
            ROUND(SUM(credits_used), 4) AS total_credits,
            ROUND(SUM(credits_used_compute), 4) AS compute_credits,
            ROUND(SUM(credits_used_cloud_services), 4) AS warehouse_cloud_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {wh_filter}
    """, ttl_key=f"uo_metering_{company}_{days}", tier="historical")

    storage = run_query(f"""
        WITH latest AS (
            SELECT database_name, average_database_bytes, average_failsafe_bytes, usage_date,
                   ROW_NUMBER() OVER (PARTITION BY database_name ORDER BY usage_date DESC) AS rn
            FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
            WHERE usage_date >= DATEADD('day', -{max(days, 7)}, CURRENT_DATE())
              {db_filter}
        )
        SELECT
            ROUND(SUM(average_database_bytes) / POWER(1024, 4), 3) AS active_storage_tb,
            ROUND(SUM(average_failsafe_bytes) / POWER(1024, 4), 3) AS failsafe_storage_tb
        FROM latest
        WHERE rn = 1
    """, ttl_key=f"uo_storage_{company}_{days}", tier="historical")

    top_wh = run_query(f"""
        SELECT
            warehouse_name,
            ROUND(SUM(credits_used), 4) AS total_credits,
            ROUND(SUM(credits_used_compute), 4) AS compute_credits,
            ROUND(SUM(credits_used_cloud_services), 4) AS cloud_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {wh_filter}
        GROUP BY warehouse_name
        ORDER BY total_credits DESC
        LIMIT 20
    """, ttl_key=f"uo_top_wh_{company}_{days}", tier="historical")

    query_types = run_query(f"""
        SELECT
            COALESCE(q.query_type, 'UNKNOWN') AS query_type,
            COUNT(*) AS query_count,
            COUNT(DISTINCT q.user_name) AS users,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            SUM(IFF(q.error_code IS NOT NULL, 1, 0)) AS failed_queries
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {q_filters}
        GROUP BY query_type
        ORDER BY query_count DESC
        LIMIT 25
    """, ttl_key=f"uo_query_types_{company}_{days}", tier="historical")

    users_by_db = run_query(f"""
        SELECT
            COALESCE(q.database_name, 'UNKNOWN') AS database_name,
            COUNT(DISTINCT q.user_name) AS users,
            COUNT(*) AS query_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {q_filters}
        GROUP BY database_name
        ORDER BY users DESC, query_count DESC
        LIMIT 20
    """, ttl_key=f"uo_users_by_db_{company}_{days}", tier="historical")

    return {
        "overview": overview,
        "metering": metering,
        "storage": storage,
        "top_wh": top_wh,
        "query_types": query_types,
        "users_by_db": users_by_db,
    }


def _first_number(df, column: str) -> float:
    if df is None or df.empty or column not in df.columns:
        return 0.0
    return float(df.iloc[0].get(column, 0) or 0)


def _queue_top_warehouses(session, df):
    if df is None or df.empty:
        st.info("No warehouse cost drivers are loaded yet.")
        return
    company = get_active_company()
    actions = []
    for _, row in df.head(5).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", "UNKNOWN"))
        credits = float(row.get("TOTAL_CREDITS", 0) or 0)
        if credits <= 0:
            continue
        actions.append({
            "Source": "Usage Overview",
            "Category": "Cost Driver",
            "Severity": "High" if credits >= 100 else "Medium",
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Owner": "DBA",
            "Finding": f"{wh} is one of the top credit drivers in the selected usage window.",
            "Action": "Review workload mix, auto-suspend policy, and high-cost users before the next billing cycle.",
            "Estimated Monthly Savings": round(credits * st.session_state.get("credit_price", 3.0) * 0.15, 2),
            "Generated SQL Fix": f"-- Inspect warehouse settings\nSHOW WAREHOUSES LIKE {sql_literal(wh)};",
            "Proof Query": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY "
                           f"WHERE warehouse_name = {sql_literal(wh)} ORDER BY start_time DESC;",
            "Company": company,
        })
    created = upsert_actions(session, actions)
    st.success(f"Added or refreshed {created} warehouse cost actions.")


def render():
    session = get_session()
    st.header("Usage Overview")
    st.caption("Executive view of Snowflake activity, cost, storage, and top usage drivers.")

    c1, c2 = st.columns([1, 2])
    with c1:
        days = st.slider("Lookback days", 1, 90, 30, key="uo_days")
    with c2:
        st.info("Charts are sorted largest-to-smallest and drill into recent query detail where Snowflake query history is available.")

    if st.button("Load Usage Overview", key="uo_load"):
        with st.spinner("Loading usage overview..."):
            try:
                st.session_state["uo_data"] = _load_overview(session, days)
            except Exception as e:
                st.warning(f"Usage overview unavailable: {format_snowflake_error(e)}")

    data = st.session_state.get("uo_data")
    if not data:
        return

    overview = data["overview"]
    metering = data["metering"]
    storage = data["storage"]
    success_rate = _first_number(overview, "QUERY_SUCCESS_RATE")
    total_queries = _first_number(overview, "TOTAL_QUERIES")
    failure_penalty = 100 * (_first_number(overview, "FAILED_QUERIES") / max(total_queries, 1))
    queue_penalty = 35 * (_first_number(overview, "QUEUED_QUERIES") / max(total_queries, 1))
    latency_penalty = min(_first_number(overview, "AVG_ELAPSED_SEC") / 6, 12)
    health_score = round(max(0, min(100, 100 - failure_penalty - queue_penalty - latency_penalty)), 1)

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Health Score", f"{health_score:.1f}")
    k2.metric("Users", f"{_first_number(overview, 'TOTAL_USERS'):,.0f}")
    k3.metric("Databases", f"{_first_number(overview, 'ACTIVE_DATABASES'):,.0f}")
    k4.metric("Success Rate", f"{success_rate:.1f}%")
    k5.metric("Avg Elapsed", f"{_first_number(overview, 'AVG_ELAPSED_SEC'):,.2f}s")
    k6.metric("Total Credits", format_credits(_first_number(metering, "TOTAL_CREDITS")))

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Compute Credits", format_credits(_first_number(metering, "COMPUTE_CREDITS")))
    s2.metric("Cloud Credits", format_credits(_first_number(metering, "WAREHOUSE_CLOUD_CREDITS")))
    s3.metric("Active Storage", f"{_first_number(storage, 'ACTIVE_STORAGE_TB'):,.2f} TB")
    s4.metric("Failsafe Storage", f"{_first_number(storage, 'FAILSAFE_STORAGE_TB'):,.2f} TB")

    tab_wh, tab_query, tab_db = st.tabs(["Cost Drivers", "Query Mix", "Adoption By Database"])
    with tab_wh:
        top_wh = data["top_wh"]
        if not top_wh.empty:
            render_drillable_bar_chart(top_wh, "WAREHOUSE_NAME", "TOTAL_CREDITS", "uo_top_wh", "Top Warehouses By Credit Usage", "warehouse_name", 24 * min(days, 14), 15)
            if st.button("Send top warehouses to Action Queue", key="uo_queue_wh"):
                _queue_top_warehouses(session, top_wh)
            download_csv(top_wh, "usage_overview_top_warehouses.csv")
        else:
            st.info("No warehouse metering found for the selected filters.")

    with tab_query:
        qt = data["query_types"]
        if not qt.empty:
            chart = alt.Chart(qt.sort_values("QUERY_COUNT", ascending=False)).mark_bar().encode(
                x=alt.X("QUERY_COUNT:Q", title="Queries"),
                y=alt.Y("QUERY_TYPE:N", sort="-x", title=None),
                tooltip=["QUERY_TYPE", "QUERY_COUNT", "USERS", "AVG_ELAPSED_SEC", "FAILED_QUERIES"],
                color=alt.value("#38bdf8"),
            ).properties(height=420)
            st.altair_chart(chart, use_container_width=True)
            st.dataframe(qt, use_container_width=True, height=300)
            download_csv(qt, "usage_overview_query_types.csv")
        else:
            st.info("No query activity found for the selected filters.")

    with tab_db:
        db = data["users_by_db"]
        if not db.empty:
            render_drillable_bar_chart(db, "DATABASE_NAME", "USERS", "uo_users_db", "Users By Database", "database_name", 24 * min(days, 14), 15)
            download_csv(db, "usage_overview_users_by_database.csv")
        else:
            st.info("No database adoption detail found for the selected filters.")
