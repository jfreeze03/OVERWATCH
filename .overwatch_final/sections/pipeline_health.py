# sections/pipeline_health.py - table freshness, load health, and volume watchlists
import pandas as pd
import streamlit as st

from utils import (
    build_action_queue_ddl,
    download_csv,
    get_db_filter_clause,
    get_session,
    make_action_id,
    normalize_df,
    render_drillable_bar_chart,
    upsert_actions,
)


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
            severity = "High" if float(row.get("HOURS_SINCE_CHANGE", 0) or 0) >= 72 else "Medium"
            finding = f"{entity} has not changed for {int(row.get('HOURS_SINCE_CHANGE', 0) or 0)} hours"
            action = "Confirm upstream pipeline SLA, source feed health, and whether the table is still business critical."
            proof = "ACCOUNT_USAGE.TABLES last_altered freshness scan"
        elif finding_type == "Load Failure":
            severity = "High"
            finding = f"{entity} has {int(row.get('FILE_COUNT', 0) or 0)} failed load files with status {row.get('STATUS', '')}"
            action = "Review COPY_HISTORY error, repair source file/stage issue, and reload failed files."
            proof = "ACCOUNT_USAGE.COPY_HISTORY non-loaded status scan"
        else:
            severity = "Medium"
            finding = f"{entity} is on volume watch: {row.get('WATCH_REASON', '')}; {float(row.get('SIZE_GB', 0) or 0):,.1f} GB"
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
        st.error(f"Could not save to action queue: {e}")
        st.download_button(
            "Download Action Queue DDL",
            build_action_queue_ddl(),
            file_name="overwatch_action_queue_setup.sql",
            mime="text/plain",
            key=f"pipe_queue_ddl_{finding_type}",
        )


def render():
    session = get_session()
    company = st.session_state.get("active_company", "ALFA")
    tab_fresh, tab_loads, tab_volume = st.tabs([
        "Freshness SLA", "Load Failures", "Volume Watch"
    ])

    with tab_fresh:
        st.header("Pipeline Freshness SLA")
        stale_hours = st.slider("Stale threshold (hours)", 4, 168, 24, key="pipe_stale_hours")
        if st.button("Load Freshness Watchlist", key="pipe_fresh_load"):
            try:
                df_fresh = normalize_df(session.sql(f"""
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
                """).to_pandas())
                st.session_state["pipe_freshness"] = df_fresh
            except Exception as e:
                st.error(f"Freshness scan failed: {e}")

        df_fresh = st.session_state.get("pipe_freshness")
        if df_fresh is not None:
            if df_fresh.empty:
                st.success("No stale tables found for the selected threshold.")
            else:
                c1, c2, c3 = st.columns(3)
                c1.metric("Stale tables", len(df_fresh))
                c2.metric("Databases", df_fresh["DATABASE_NAME"].nunique())
                c3.metric("Largest stale table GB", f"{float(df_fresh['SIZE_GB'].max() or 0):,.1f}")
                st.dataframe(df_fresh, use_container_width=True)
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

    with tab_loads:
        st.header("Load Failure Monitor")
        load_days = st.slider("Lookback days", 1, 30, 7, key="pipe_load_days")
        if st.button("Load Copy History Failures", key="pipe_load_failures"):
            try:
                df_loads = normalize_df(session.sql(f"""
                    SELECT table_catalog AS database_name,
                           table_schema AS schema_name,
                           table_name,
                           status,
                           COUNT(*) AS file_count,
                           MAX(last_load_time) AS last_seen,
                           MAX(first_error_message) AS latest_error
                    FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
                    WHERE last_load_time >= DATEADD('day', -{load_days}, CURRENT_TIMESTAMP())
                      AND status <> 'LOADED'
                      {get_db_filter_clause("table_catalog", company)}
                    GROUP BY database_name, schema_name, table_name, status
                    ORDER BY file_count DESC, last_seen DESC
                    LIMIT 300
                """).to_pandas())
                st.session_state["pipe_load_failures"] = df_loads
            except Exception as e:
                st.error(f"Load failure scan failed: {e}")

        df_loads = st.session_state.get("pipe_load_failures")
        if df_loads is not None:
            if df_loads.empty:
                st.success("No copy/load failures found in the selected window.")
            else:
                st.metric("Failed load groups", len(df_loads))
                st.dataframe(df_loads, use_container_width=True)
                download_csv(df_loads, "pipeline_load_failures.csv")
                if st.button("Save load failures to Action Queue", key="pipe_load_queue"):
                    _queue_pipeline_findings(session, df_loads, "Load Failure")

    with tab_volume:
        st.header("Table Volume Watch")
        st.caption("Highlights large and fast-changing tables from ACCOUNT_USAGE.TABLES metadata.")
        min_gb = st.slider("Minimum table size (GB)", 1, 500, 25, key="pipe_min_gb")
        if st.button("Load Volume Watchlist", key="pipe_volume_load"):
            try:
                df_volume = normalize_df(session.sql(f"""
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
                """).to_pandas())
                st.session_state["pipe_volume"] = df_volume
            except Exception as e:
                st.error(f"Volume watch failed: {e}")

        df_volume = st.session_state.get("pipe_volume")
        if df_volume is not None:
            if df_volume.empty:
                st.success("No tables matched the volume threshold.")
            else:
                c1, c2 = st.columns(2)
                c1.metric("Watchlist tables", len(df_volume))
                c2.metric("Total watchlist GB", f"{float(df_volume['SIZE_GB'].sum() or 0):,.1f}")
                st.dataframe(df_volume, use_container_width=True)
                download_csv(df_volume, "pipeline_volume_watch.csv")
                if st.button("Save volume watch to Action Queue", key="pipe_volume_queue"):
                    _queue_pipeline_findings(session, df_volume, "Volume")
