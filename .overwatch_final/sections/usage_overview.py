# sections/usage_overview.py - executive Snowflake usage overview
import pandas as pd
import streamlit as st

from utils import (
    build_task_health_sql,
    download_csv,
    executive_health_score,
    format_credits,
    format_snowflake_error,
    freshness_note,
    get_active_company,
    get_db_filter_clause,
    get_global_filter_clause,
    get_session,
    get_wh_filter_clause,
    company_scoped_query,
    filter_existing_columns,
    metric_confidence_label,
    render_drillable_bar_chart,
    build_mart_usage_overview_sql,
    build_mart_usage_metering_sql,
    build_mart_usage_pressure_sql,
    build_mart_usage_cost_drivers_sql,
    build_mart_usage_query_mix_sql,
    build_mart_usage_database_adoption_sql,
    run_query,
    safe_float,
    sql_literal,
    upsert_actions,
)
from utils.workflows import render_priority_dataframe


USAGE_OVERVIEW_PANES = ["Cost Drivers", "Query Mix", "Adoption By Database"]


def _altair():
    """Import Altair only after a chart panel is requested."""
    import altair as alt

    return alt


def _load_overview(session, days: int) -> dict:
    company = get_active_company()
    global_warehouse = str(st.session_state.get("global_warehouse", "") or "").strip()
    global_user = str(st.session_state.get("global_user", "") or "").strip()
    global_role = str(st.session_state.get("global_role", "") or "").strip()
    global_database = str(st.session_state.get("global_database", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")
    wh_filter = get_wh_filter_clause("warehouse_name")
    db_filter = get_db_filter_clause("database_name")
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        [
            "ERROR_CODE",
            "QUEUED_OVERLOAD_TIME",
            "QUEUED_PROVISIONING_TIME",
            "QUEUED_REPAIR_TIME",
            "CREDITS_USED_CLOUD_SERVICES",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
        ],
    ))
    wm_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
    ))
    success_expr = (
        "SUM(IFF(q.error_code IS NULL, 1, 0))"
        if "ERROR_CODE" in qh_cols
        else "SUM(IFF(UPPER(q.execution_status) = 'SUCCESS', 1, 0))"
    )
    failed_expr = (
        "SUM(IFF(q.error_code IS NOT NULL, 1, 0))"
        if "ERROR_CODE" in qh_cols
        else "SUM(IFF(UPPER(q.execution_status) = 'FAILED_WITH_ERROR', 1, 0))"
    )
    queue_terms = [
        f"q.{col.lower()} > 0"
        for col in ("QUEUED_OVERLOAD_TIME", "QUEUED_PROVISIONING_TIME", "QUEUED_REPAIR_TIME")
        if col in qh_cols
    ]
    queued_expr = (
        "SUM(IFF(" + " OR ".join(queue_terms) + ", 1, 0))"
        if queue_terms
        else "0"
    )
    qh_cloud_expr = (
        "ROUND(SUM(COALESCE(q.credits_used_cloud_services, 0)), 4)"
        if "CREDITS_USED_CLOUD_SERVICES" in qh_cols
        else "0"
    )
    remote_spill_expr = (
        "ROUND(SUM(COALESCE(q.bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2)"
        if "BYTES_SPILLED_TO_REMOTE_STORAGE" in qh_cols
        else "0"
    )
    wm_compute_expr = (
        f"ROUND(SUM(IFF(start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), credits_used_compute, 0)), 4)"
        if "CREDITS_USED_COMPUTE" in wm_cols
        else f"ROUND(SUM(IFF(start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), credits_used, 0)), 4)"
    )
    wm_cloud_expr = (
        f"ROUND(SUM(IFF(start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), credits_used_cloud_services, 0)), 4)"
        if "CREDITS_USED_CLOUD_SERVICES" in wm_cols
        else "0"
    )
    q_filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )

    live_overview_sql = f"""
        SELECT
            COUNT(*) AS total_queries,
            COUNT(DISTINCT q.user_name) AS total_users,
            COUNT(DISTINCT q.database_name) AS active_databases,
            ROUND(100 * {success_expr} / NULLIF(COUNT(*), 0), 1) AS query_success_rate,
            {failed_expr} AS failed_queries,
            {queued_expr} AS queued_queries,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            ROUND(AVG(q.execution_time) / 1000, 2) AS avg_execution_sec,
            {qh_cloud_expr} AS cloud_service_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {q_filters}
    """
    overview = run_query(
        build_mart_usage_overview_sql(
            days,
            company=company,
            warehouse_contains=global_warehouse,
            user_contains=global_user,
            role_contains=global_role,
            database_contains=global_database,
            start_date=global_start_date,
            end_date=global_end_date,
        ),
        ttl_key=f"uo_overview_mart_{company}_{days}",
        tier="historical",
    )
    overview_source = "OVERWATCH mart: FACT_QUERY_HOURLY"
    if overview.empty or _first_number(overview, "TOTAL_QUERIES") <= 0:
        overview = run_query(live_overview_sql, ttl_key=f"uo_overview_live_{company}_{days}", tier="historical")
        overview_source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"

    live_metering_sql = f"""
        SELECT
            ROUND(SUM(IFF(start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP()), credits_used, 0)), 4) AS total_credits,
            ROUND(SUM(IFF(start_time >= DATEADD('day', -{days * 2}, CURRENT_TIMESTAMP())
                          AND start_time < DATEADD('day', -{days}, CURRENT_TIMESTAMP()),
                          credits_used, 0)), 4) AS prior_credits,
            {wm_compute_expr} AS compute_credits,
            {wm_cloud_expr} AS warehouse_cloud_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days * 2}, CURRENT_TIMESTAMP())
          {wh_filter}
    """
    metering = run_query(
        build_mart_usage_metering_sql(
            days,
            company=company,
            warehouse_contains=global_warehouse,
            start_date=global_start_date,
            end_date=global_end_date,
        ),
        ttl_key=f"uo_metering_mart_{company}_{days}",
        tier="historical",
    )
    metering_source = "OVERWATCH mart: FACT_WAREHOUSE_HOURLY"
    if metering.empty:
        metering = run_query(live_metering_sql, ttl_key=f"uo_metering_live_{company}_{days}", tier="historical")
        metering_source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"

    storage = run_query(f"""
        WITH scoped AS (
            SELECT database_name, average_database_bytes, average_failsafe_bytes, usage_date
            FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
            WHERE usage_date >= DATEADD('day', -{max(days * 2, 14)}, CURRENT_DATE())
              {db_filter}
        ),
        current_latest AS (
            SELECT database_name, average_database_bytes, average_failsafe_bytes,
                   ROW_NUMBER() OVER (PARTITION BY database_name ORDER BY usage_date DESC) AS rn
            FROM scoped
        ),
        prior_latest AS (
            SELECT database_name, average_database_bytes,
                   ROW_NUMBER() OVER (PARTITION BY database_name ORDER BY usage_date DESC) AS rn
            FROM scoped
            WHERE usage_date <= DATEADD('day', -{days}, CURRENT_DATE())
        )
        SELECT
            ROUND(SUM(COALESCE(c.average_database_bytes, 0)) / POWER(1024, 4), 3) AS active_storage_tb,
            ROUND(SUM(COALESCE(c.average_failsafe_bytes, 0)) / POWER(1024, 4), 3) AS failsafe_storage_tb,
            ROUND(SUM(COALESCE(p.average_database_bytes, 0)) / POWER(1024, 4), 3) AS prior_active_storage_tb
        FROM current_latest c
        LEFT JOIN prior_latest p
          ON c.database_name = p.database_name
         AND p.rn = 1
        WHERE c.rn = 1
    """, ttl_key=f"uo_storage_{company}_{days}", tier="historical")

    try:
        task_health = run_query(
            build_task_health_sql(
                session,
                f"scheduled_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())",
                company=company,
            ),
            ttl_key=f"uo_task_health_{company}_{days}",
            tier="historical",
            section="Usage Overview",
        )
    except Exception:
        task_health = pd.DataFrame([{
            "TASK_RUNS": 0,
            "FAILED_TASKS": 0,
            "SUCCEEDED_TASKS": 0,
            "DISTINCT_TASKS": 0,
        }])

    live_pressure_sql = f"""
        WITH wh AS (
            SELECT
                q.warehouse_name,
                COUNT(*) AS total_queries,
                {failed_expr} AS failed_queries,
                {queued_expr} AS queued_queries,
                {remote_spill_expr} AS remote_spill_gb
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {q_filters}
            GROUP BY q.warehouse_name
        )
        SELECT
            COUNT(*) AS active_warehouses,
            SUM(IFF(queued_queries > 0 OR remote_spill_gb > 1 OR failed_queries > 0, 1, 0)) AS pressure_warehouses
        FROM wh
    """
    warehouse_pressure = run_query(
        build_mart_usage_pressure_sql(
            days,
            company=company,
            warehouse_contains=global_warehouse,
            user_contains=global_user,
            role_contains=global_role,
            database_contains=global_database,
            start_date=global_start_date,
            end_date=global_end_date,
        ),
        ttl_key=f"uo_wh_pressure_mart_{company}_{days}",
        tier="historical",
        section="Usage Overview",
    )
    pressure_source = "OVERWATCH mart: FACT_QUERY_HOURLY"
    if warehouse_pressure.empty:
        warehouse_pressure = run_query(
            live_pressure_sql,
            ttl_key=f"uo_wh_pressure_live_{company}_{days}",
            tier="historical",
            section="Usage Overview",
        )
        pressure_source = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"

    return {
        "overview": overview,
        "metering": metering,
        "storage": storage,
        "task_health": task_health,
        "warehouse_pressure": warehouse_pressure,
        "sources": {
            "overview": overview_source,
            "metering": metering_source,
            "warehouse_pressure": pressure_source,
            "storage": "Live: SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY",
            "task_health": "Live: task history metadata",
        },
    }


def _load_cost_drivers(session, days: int):
    company = get_active_company()
    warehouse_contains = str(st.session_state.get("global_warehouse", "") or "").strip()
    mart_df = run_query(
        build_mart_usage_cost_drivers_sql(
            days,
            company=company,
            warehouse_contains=warehouse_contains,
            start_date=st.session_state.get("global_start_date"),
            end_date=st.session_state.get("global_end_date"),
        ),
        ttl_key=f"uo_top_wh_mart_{company}_{days}",
        tier="historical",
        section="Usage Overview",
    )
    if not mart_df.empty:
        st.session_state["uo_top_wh_source"] = "OVERWATCH mart: FACT_WAREHOUSE_HOURLY"
        return mart_df

    wm_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
        ["CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES"],
    ))
    wm_compute_expr = (
        "ROUND(SUM(COALESCE(credits_used_compute, credits_used)), 4)"
        if "CREDITS_USED_COMPUTE" in wm_cols
        else "ROUND(SUM(credits_used), 4)"
    )
    wm_cloud_expr = (
        "ROUND(SUM(COALESCE(credits_used_cloud_services, 0)), 4)"
        if "CREDITS_USED_CLOUD_SERVICES" in wm_cols
        else "0"
    )
    live_df = company_scoped_query(
        f"""
        SELECT
            warehouse_name,
            ROUND(SUM(credits_used), 4) AS total_credits,
            {wm_compute_expr} AS compute_credits,
            {wm_cloud_expr} AS cloud_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {{company_scope}}
        GROUP BY warehouse_name
        ORDER BY total_credits DESC
        LIMIT 20
        """,
        "uo_top_wh",
        tier="historical",
        date_col="start_time",
        wh_col="warehouse_name",
        user_col=None,
        role_col=None,
        db_col=None,
        include_global_filters=False,
        section="Usage Overview",
        extra_cache_parts=(days,),
    )
    st.session_state["uo_top_wh_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
    return live_df


def _load_query_mix(session, days: int):
    company = get_active_company()
    mart_df = run_query(
        build_mart_usage_query_mix_sql(
            days,
            company=company,
            warehouse_contains=str(st.session_state.get("global_warehouse", "") or "").strip(),
            user_contains=str(st.session_state.get("global_user", "") or "").strip(),
            role_contains=str(st.session_state.get("global_role", "") or "").strip(),
            database_contains=str(st.session_state.get("global_database", "") or "").strip(),
            start_date=st.session_state.get("global_start_date"),
            end_date=st.session_state.get("global_end_date"),
        ),
        ttl_key=f"uo_query_types_mart_{company}_{days}",
        tier="historical",
        section="Usage Overview",
    )
    if not mart_df.empty:
        st.session_state["uo_query_types_source"] = "OVERWATCH mart: FACT_QUERY_HOURLY"
        return mart_df

    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["ERROR_CODE"],
    ))
    failed_count_expr = (
        "SUM(IFF(q.error_code IS NOT NULL, 1, 0))"
        if "ERROR_CODE" in qh_cols
        else "SUM(IFF(UPPER(q.execution_status) = 'FAILED_WITH_ERROR', 1, 0))"
    )
    live_df = company_scoped_query(
        f"""
        SELECT
            COALESCE(q.query_type, 'UNKNOWN') AS query_type,
            COUNT(*) AS query_count,
            COUNT(DISTINCT q.user_name) AS users,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            {failed_count_expr} AS failed_queries
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {{global_scope}}
        GROUP BY query_type
        ORDER BY query_count DESC
        LIMIT 25
        """,
        "uo_query_types",
        tier="historical",
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
        section="Usage Overview",
        extra_cache_parts=(days,),
    )
    st.session_state["uo_query_types_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
    return live_df


def _load_database_adoption(days: int):
    company = get_active_company()
    mart_df = run_query(
        build_mart_usage_database_adoption_sql(
            days,
            company=company,
            warehouse_contains=str(st.session_state.get("global_warehouse", "") or "").strip(),
            user_contains=str(st.session_state.get("global_user", "") or "").strip(),
            role_contains=str(st.session_state.get("global_role", "") or "").strip(),
            database_contains=str(st.session_state.get("global_database", "") or "").strip(),
            start_date=st.session_state.get("global_start_date"),
            end_date=st.session_state.get("global_end_date"),
        ),
        ttl_key=f"uo_users_by_db_mart_{company}_{days}",
        tier="historical",
        section="Usage Overview",
    )
    if not mart_df.empty:
        st.session_state["uo_users_by_db_source"] = "OVERWATCH mart: FACT_QUERY_HOURLY"
        return mart_df

    live_df = company_scoped_query(
        f"""
        SELECT
            COALESCE(q.database_name, 'UNKNOWN') AS database_name,
            COUNT(DISTINCT q.user_name) AS users,
            COUNT(*) AS query_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {{global_scope}}
        GROUP BY database_name
        ORDER BY users DESC, query_count DESC
        LIMIT 20
        """,
        "uo_users_by_db",
        tier="historical",
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
        section="Usage Overview",
        extra_cache_parts=(days,),
    )
    st.session_state["uo_users_by_db_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
    return live_df


def _first_number(df, column: str) -> float:
    if df is None or df.empty or column not in df.columns:
        return 0.0
    return safe_float(df.iloc[0].get(column, 0))


def _queue_top_warehouses(session, df):
    if df is None or df.empty:
        st.info("No warehouse cost drivers are loaded yet.")
        return
    company = get_active_company()
    actions = []
    for _, row in df.head(5).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", "UNKNOWN"))
        credits = safe_float(row.get("TOTAL_CREDITS", 0))
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
    task_health = data.get("task_health", pd.DataFrame())
    warehouse_pressure = data.get("warehouse_pressure", pd.DataFrame())
    sources = data.get("sources", {})
    success_rate = _first_number(overview, "QUERY_SUCCESS_RATE")
    total_queries = _first_number(overview, "TOTAL_QUERIES")
    health = executive_health_score({
        "total_queries": total_queries,
        "failed_queries": _first_number(overview, "FAILED_QUERIES"),
        "queued_queries": _first_number(overview, "QUEUED_QUERIES"),
        "avg_elapsed_sec": _first_number(overview, "AVG_ELAPSED_SEC"),
        "task_runs": _first_number(task_health, "TASK_RUNS"),
        "failed_tasks": _first_number(task_health, "FAILED_TASKS"),
        "active_warehouses": _first_number(warehouse_pressure, "ACTIVE_WAREHOUSES"),
        "pressure_warehouses": _first_number(warehouse_pressure, "PRESSURE_WAREHOUSES"),
        "current_credits": _first_number(metering, "TOTAL_CREDITS"),
        "prior_credits": _first_number(metering, "PRIOR_CREDITS"),
        "current_storage_tb": _first_number(storage, "ACTIVE_STORAGE_TB"),
        "prior_storage_tb": _first_number(storage, "PRIOR_ACTIVE_STORAGE_TB"),
    })
    health_score = health["score"]

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Health Score", f"{health_score:.1f}", health["label"])
    k2.metric("Users", f"{_first_number(overview, 'TOTAL_USERS'):,.0f}")
    k3.metric("Databases", f"{_first_number(overview, 'ACTIVE_DATABASES'):,.0f}")
    k4.metric("Success Rate", f"{success_rate:.1f}%")
    k5.metric("Avg Elapsed", f"{_first_number(overview, 'AVG_ELAPSED_SEC'):,.2f}s")
    k6.metric("Total Credits", format_credits(_first_number(metering, "TOTAL_CREDITS")))
    st.caption(
        " | ".join([
            metric_confidence_label("exact"),
            metric_confidence_label("composite"),
            sources.get("overview", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"),
            sources.get("metering", "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"),
            freshness_note("ACCOUNT_USAGE"),
            "Progressive load: KPI queries ran; charts below load only when requested.",
        ])
    )

    with st.expander("Health score contributors"):
        render_priority_dataframe(
            pd.DataFrame(health["components"]),
            title="Health score contributors",
            priority_columns=["COMPONENT", "SCORE", "WEIGHT", "DETAIL"],
            sort_by=["SCORE", "WEIGHT"],
            ascending=[True, False],
            raw_label="All health score components",
            height=280,
        )

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Compute Credits", format_credits(_first_number(metering, "COMPUTE_CREDITS")))
    s2.metric("Cloud Credits", format_credits(_first_number(metering, "WAREHOUSE_CLOUD_CREDITS")))
    s3.metric("Active Storage", f"{_first_number(storage, 'ACTIVE_STORAGE_TB'):,.2f} TB")
    s4.metric("Failsafe Storage", f"{_first_number(storage, 'FAILSAFE_STORAGE_TB'):,.2f} TB")

    active_pane = st.radio(
        "Usage detail view",
        USAGE_OVERVIEW_PANES,
        horizontal=True,
        label_visibility="collapsed",
        key="uo_active_pane",
    )
    if active_pane == "Cost Drivers":
        if st.button("Load Cost Driver Chart", key="uo_load_cost_drivers"):
            with st.spinner("Loading warehouse cost drivers..."):
                st.session_state["uo_top_wh"] = _load_cost_drivers(session, days)
        top_wh = st.session_state.get("uo_top_wh")
        if top_wh is None:
            st.info("Cost driver chart is deferred. Load it when you need warehouse detail.")
        elif not top_wh.empty:
            st.caption(st.session_state.get("uo_top_wh_source", "Source unavailable"))
            render_drillable_bar_chart(top_wh, "WAREHOUSE_NAME", "TOTAL_CREDITS", "uo_top_wh", "Top Warehouses By Credit Usage", "warehouse_name", 24 * min(days, 14), 15)
            if st.button("Send top warehouses to Action Queue", key="uo_queue_wh"):
                _queue_top_warehouses(session, top_wh)
            download_csv(top_wh, "usage_overview_top_warehouses.csv")
        else:
            st.info("No warehouse metering found for the selected filters.")

    elif active_pane == "Query Mix":
        if st.button("Load Query Mix", key="uo_load_query_mix"):
            with st.spinner("Loading query mix..."):
                st.session_state["uo_query_types"] = _load_query_mix(session, days)
        qt = st.session_state.get("uo_query_types")
        if qt is None:
            st.info("Query mix is deferred to keep Usage Overview lightweight.")
        elif not qt.empty:
            st.caption(st.session_state.get("uo_query_types_source", "Source unavailable"))
            alt = _altair()
            chart = alt.Chart(qt.sort_values("QUERY_COUNT", ascending=False)).mark_bar().encode(
                x=alt.X("QUERY_COUNT:Q", title="Queries"),
                y=alt.Y("QUERY_TYPE:N", sort="-x", title=None),
                tooltip=["QUERY_TYPE", "QUERY_COUNT", "USERS", "AVG_ELAPSED_SEC", "FAILED_QUERIES"],
                color=alt.value("#38bdf8"),
            ).properties(height=420)
            st.altair_chart(chart, use_container_width=True)
            render_priority_dataframe(
                qt,
                title="Query mix drivers",
                priority_columns=["QUERY_TYPE", "QUERY_COUNT", "USERS", "AVG_ELAPSED_SEC", "FAILED_QUERIES"],
                sort_by=["QUERY_COUNT", "FAILED_QUERIES", "AVG_ELAPSED_SEC"],
                ascending=[False, False, False],
                raw_label="All query mix rows",
                height=300,
            )
            download_csv(qt, "usage_overview_query_types.csv")
        else:
            st.info("No query activity found for the selected filters.")

    elif active_pane == "Adoption By Database":
        if st.button("Load Database Adoption", key="uo_load_database_adoption"):
            with st.spinner("Loading database adoption..."):
                st.session_state["uo_users_by_db"] = _load_database_adoption(days)
        db = st.session_state.get("uo_users_by_db")
        if db is None:
            st.info("Database adoption detail is deferred until requested.")
        elif not db.empty:
            st.caption(st.session_state.get("uo_users_by_db_source", "Source unavailable"))
            render_drillable_bar_chart(db, "DATABASE_NAME", "USERS", "uo_users_db", "Users By Database", "database_name", 24 * min(days, 14), 15)
            download_csv(db, "usage_overview_users_by_database.csv")
        else:
            st.info("No database adoption detail found for the selected filters.")
