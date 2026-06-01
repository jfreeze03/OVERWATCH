# sections/pipeline_health.py - table freshness, load health, and volume watchlists
import pandas as pd
import streamlit as st

from utils import (
    build_mart_pipeline_freshness_sql,
    build_mart_pipeline_load_failures_sql,
    build_mart_pipeline_volume_sql,
    download_csv,
    get_db_filter_clause,
    get_session,
    format_snowflake_error,
    make_action_id,
    render_drillable_bar_chart,
    render_priority_dataframe,
    run_query,
    safe_float,
    safe_int,
    upsert_actions,
)


PIPELINE_HEALTH_PANES = (
    "Freshness SLA",
    "Load Failures",
    "Volume Watch",
)


def _annotate_pipeline_routes(df: pd.DataFrame, finding_type: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    routed = df.copy()
    if finding_type == "Freshness":
        routed["NEXT_WORKFLOW"] = "Pipeline health"
        routed["NEXT_ACTION"] = "Confirm upstream source, task graph status, and table SLA before marking the object inactive."
    elif finding_type == "Load Failure":
        routed["NEXT_WORKFLOW"] = "Workload operations"
        routed["NEXT_ACTION"] = "Open COPY/load history, inspect the latest error, repair the source file or stage, then reload failed files."
    else:
        routed["NEXT_WORKFLOW"] = "Change & drift"
        routed["NEXT_ACTION"] = "Review owner, retention, table growth, and lifecycle policy before archive/drop or clustering changes."
    return routed


def _queue_pipeline_findings(session, df: pd.DataFrame, finding_type: str) -> None:
    if df is None or df.empty:
        st.info("Nothing to queue from this result set.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    for _, row in df.head(200).iterrows():
        db = row.get("DATABASE_NAME", "")
        schema = row.get("SCHEMA_NAME", "")
        table = row.get("TABLE_NAME", "")
        entity = ".".join([str(v) for v in [db, schema, table] if v])
        if finding_type == "Freshness":
            severity = "High" if safe_float(row.get("HOURS_SINCE_CHANGE", 0)) >= 72 else "Medium"
            finding = f"{entity} has not changed for {safe_int(row.get('HOURS_SINCE_CHANGE', 0))} hours"
            action = "Confirm upstream pipeline SLA, source feed health, and whether the table is still business critical."
            proof = "ACCOUNT_USAGE.TABLES last_altered freshness scan"
        elif finding_type == "Load Failure":
            severity = "High"
            finding = f"{entity} has {safe_int(row.get('FILE_COUNT', 0))} failed load files with status {row.get('STATUS', '')}"
            action = "Review COPY_HISTORY error, repair source file/stage issue, and reload failed files."
            proof = "ACCOUNT_USAGE.COPY_HISTORY non-loaded status scan"
        else:
            severity = "Medium"
            finding = f"{entity} is on volume watch: {row.get('WATCH_REASON', '')}; {safe_float(row.get('SIZE_GB', 0)):,.1f} GB"
            action = "Review retention, clustering, time travel, and whether old data can be archived or dropped."
            proof = "ACCOUNT_USAGE.TABLES size and last_altered scan"
        actions.append({
            "Action ID": make_action_id("Pipeline", entity, finding),
            "Source": f"Pipeline Health - {finding_type}",
            "Severity": severity,
            "Category": "Pipeline",
            "Entity Type": "Table",
            "Entity": entity,
            "Owner": "Data Engineering",
            "Finding": finding,
            "Action": action,
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": "-- Review pipeline/table ownership before changing data or retention settings.",
            "Proof Query": proof,
            "Company": company,
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} pipeline findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def render():
    session = get_session()
    company = st.session_state.get("active_company", "ALFA")
    active_view = st.radio(
        "Pipeline health view",
        PIPELINE_HEALTH_PANES,
        horizontal=True,
        label_visibility="collapsed",
        key="pipeline_health_active_view",
    )

    if active_view == "Freshness SLA":
        st.header("Pipeline Freshness SLA")
        stale_hours = st.slider("Stale threshold (hours)", 4, 168, 24, key="pipe_stale_hours")
        if st.button("Load Freshness Watchlist", key="pipe_fresh_load"):
            try:
                df_fresh = run_query(
                    build_mart_pipeline_freshness_sql(stale_hours, company),
                    ttl_key=f"pipeline_fresh_mart_{company}_{stale_hours}",
                    tier="historical",
                    section="Pipeline Health",
                )
                st.session_state["pipe_freshness_source"] = "OVERWATCH mart: DIM_TABLE_SNAPSHOT"
            except Exception:
                try:
                    df_fresh = run_query(f"""
                        SELECT table_catalog AS database_name,
                               table_schema AS schema_name,
                               table_name,
                               table_type,
                               row_count,
                               bytes / POWER(1024,3) AS size_gb,
                               last_altered,
                               DATEDIFF('hour', last_altered, CURRENT_TIMESTAMP()) AS hours_since_change
                        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                        WHERE deleted IS NULL
                          AND table_schema NOT IN ('INFORMATION_SCHEMA')
                          AND DATEDIFF('hour', last_altered, CURRENT_TIMESTAMP()) >= {stale_hours}
                          {get_db_filter_clause("table_catalog", company)}
                        ORDER BY hours_since_change DESC, size_gb DESC
                        LIMIT 300
                    """, ttl_key=f"pipeline_fresh_{company}_{stale_hours}", tier="standard")
                    st.session_state["pipe_freshness_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TABLES"
                except Exception as e:
                    st.warning(f"Freshness scan unavailable in this role/context: {format_snowflake_error(e)}")
                    df_fresh = None
            if df_fresh is not None:
                st.session_state["pipe_freshness"] = _annotate_pipeline_routes(df_fresh, "Freshness")

        df_fresh = st.session_state.get("pipe_freshness")
        if df_fresh is not None:
            st.caption(st.session_state.get("pipe_freshness_source", "SNOWFLAKE.ACCOUNT_USAGE.TABLES"))
            if df_fresh.empty:
                st.success("No stale tables found for the selected threshold.")
            else:
                c1, c2, c3 = st.columns(3)
                c1.metric("Stale tables", len(df_fresh))
                c2.metric("Databases", df_fresh["DATABASE_NAME"].nunique())
                c3.metric("Largest stale table GB", f"{float(df_fresh['SIZE_GB'].max() or 0):,.1f}")
                render_priority_dataframe(
                    df_fresh,
                    title="Freshness exceptions to work first",
                    priority_columns=[
                        "DATABASE_NAME", "SCHEMA_NAME", "TABLE_NAME", "HOURS_SINCE_CHANGE",
                        "SIZE_GB", "NEXT_WORKFLOW", "NEXT_ACTION", "LAST_ALTERED",
                    ],
                    sort_by=["HOURS_SINCE_CHANGE", "SIZE_GB"],
                    ascending=[False, False],
                    raw_label="All freshness rows",
                )
                render_drillable_bar_chart(
                    df_fresh.groupby("DATABASE_NAME", as_index=False)["TABLE_NAME"].count().rename(columns={"TABLE_NAME": "STALE_TABLES"}),
                    dimension="DATABASE_NAME",
                    measure="STALE_TABLES",
                    key="pipe_stale_by_db",
                    drilldown_column="database_name",
                    lookback_hours=stale_hours,
                )
                download_csv(df_fresh, "pipeline_freshness_watchlist.csv")
                if st.button("Save freshness findings to Action Queue", key="pipe_fresh_queue"):
                    _queue_pipeline_findings(session, df_fresh, "Freshness")

    elif active_view == "Load Failures":
        st.header("Load Failure Monitor")
        load_days = st.slider("Lookback days", 1, 30, 7, key="pipe_load_days")
        if st.button("Load Copy History Failures", key="pipe_load_failures"):
            try:
                df_loads = run_query(
                    build_mart_pipeline_load_failures_sql(load_days, company),
                    ttl_key=f"pipeline_loads_mart_{company}_{load_days}",
                    tier="historical",
                    section="Pipeline Health",
                )
                st.session_state["pipe_load_failures_source"] = "OVERWATCH mart: FACT_COPY_LOAD_DAILY"
            except Exception:
                try:
                    df_loads = run_query(f"""
                        SELECT table_catalog_name AS database_name,
                               table_schema_name AS schema_name,
                               table_name,
                               status,
                               COUNT(*) AS file_count,
                               SUM(COALESCE(error_count, 0)) AS error_count,
                               MAX(last_load_time) AS last_seen,
                               MAX(first_error_message) AS latest_error
                        FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
                        WHERE last_load_time >= DATEADD('day', -{load_days}, CURRENT_TIMESTAMP())
                          AND UPPER(COALESCE(status, '')) <> 'LOADED'
                          {get_db_filter_clause("table_catalog_name", company)}
                        GROUP BY database_name, schema_name, table_name, status
                        ORDER BY file_count DESC, last_seen DESC
                        LIMIT 300
                    """, ttl_key=f"pipeline_loads_{company}_{load_days}", tier="standard")
                    st.session_state["pipe_load_failures_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY"
                except Exception as e:
                    st.warning(f"Load failure scan unavailable in this role/context: {format_snowflake_error(e)}")
                    df_loads = None
            if df_loads is not None:
                st.session_state["pipe_load_failures"] = _annotate_pipeline_routes(df_loads, "Load Failure")

        df_loads = st.session_state.get("pipe_load_failures")
        if df_loads is not None:
            st.caption(st.session_state.get("pipe_load_failures_source", "SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY"))
            if df_loads.empty:
                st.success("No copy/load failures found in the selected window.")
            else:
                st.metric("Failed load groups", len(df_loads))
                render_priority_dataframe(
                    df_loads,
                    title="Load failures to work first",
                    priority_columns=[
                        "DATABASE_NAME", "SCHEMA_NAME", "TABLE_NAME", "STATUS",
                        "FILE_COUNT", "ERROR_COUNT", "LAST_SEEN", "NEXT_WORKFLOW",
                        "NEXT_ACTION", "LATEST_ERROR",
                    ],
                    sort_by=["ERROR_COUNT", "FILE_COUNT", "LAST_SEEN"],
                    ascending=[False, False, False],
                    raw_label="All load failure rows",
                )
                download_csv(df_loads, "pipeline_load_failures.csv")
                if st.button("Save load failures to Action Queue", key="pipe_load_queue"):
                    _queue_pipeline_findings(session, df_loads, "Load Failure")

    elif active_view == "Volume Watch":
        st.header("Table Volume Watch")
        st.caption("Highlights large and fast-changing tables from ACCOUNT_USAGE.TABLES metadata.")
        min_gb = st.slider("Minimum table size (GB)", 1, 500, 25, key="pipe_min_gb")
        if st.button("Load Volume Watchlist", key="pipe_volume_load"):
            try:
                df_volume = run_query(
                    build_mart_pipeline_volume_sql(min_gb, company),
                    ttl_key=f"pipeline_volume_mart_{company}_{min_gb}",
                    tier="historical",
                    section="Pipeline Health",
                )
                st.session_state["pipe_volume_source"] = "OVERWATCH mart: DIM_TABLE_SNAPSHOT"
            except Exception:
                try:
                    df_volume = run_query(f"""
                        SELECT table_catalog AS database_name,
                               table_schema AS schema_name,
                               table_name,
                               row_count,
                               ROUND(bytes / POWER(1024,3), 2) AS size_gb,
                               last_altered,
                               CASE
                                   WHEN row_count = 0 AND bytes > 0 THEN 'Storage without rows'
                                   WHEN DATEDIFF('day', last_altered, CURRENT_TIMESTAMP()) > 90 THEN 'Large and quiet'
                                   ELSE 'Active large table'
                               END AS watch_reason
                        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                        WHERE deleted IS NULL
                          AND bytes / POWER(1024,3) >= {min_gb}
                          AND table_schema NOT IN ('INFORMATION_SCHEMA')
                          {get_db_filter_clause("table_catalog", company)}
                        ORDER BY size_gb DESC
                        LIMIT 300
                    """, ttl_key=f"pipeline_volume_{company}_{min_gb}", tier="standard")
                    st.session_state["pipe_volume_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.TABLES"
                except Exception as e:
                    st.warning(f"Volume watch unavailable in this role/context: {format_snowflake_error(e)}")
                    df_volume = None
            if df_volume is not None:
                st.session_state["pipe_volume"] = _annotate_pipeline_routes(df_volume, "Volume")

        df_volume = st.session_state.get("pipe_volume")
        if df_volume is not None:
            st.caption(st.session_state.get("pipe_volume_source", "SNOWFLAKE.ACCOUNT_USAGE.TABLES"))
            if df_volume.empty:
                st.success("No tables matched the volume threshold.")
            else:
                c1, c2 = st.columns(2)
                c1.metric("Watchlist tables", len(df_volume))
                c2.metric("Total watchlist GB", f"{float(df_volume['SIZE_GB'].sum() or 0):,.1f}")
                render_priority_dataframe(
                    df_volume,
                    title="Volume exceptions to review first",
                    priority_columns=[
                        "DATABASE_NAME", "SCHEMA_NAME", "TABLE_NAME", "WATCH_REASON",
                        "SIZE_GB", "ROW_COUNT", "NEXT_WORKFLOW", "NEXT_ACTION",
                        "LAST_ALTERED",
                    ],
                    sort_by=["SIZE_GB", "ROW_COUNT"],
                    ascending=[False, False],
                    raw_label="All volume watch rows",
                )
                download_csv(df_volume, "pipeline_volume_watch.csv")
                if st.button("Save volume watch to Action Queue", key="pipe_volume_queue"):
                    _queue_pipeline_findings(session, df_volume, "Volume")
