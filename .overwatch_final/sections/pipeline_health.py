# sections/pipeline_health.py - table freshness, load health, and volume watchlists
import pandas as pd
import streamlit as st

from utils import (
    build_mart_pipeline_freshness_sql,
    build_mart_pipeline_load_failures_sql,
    build_mart_pipeline_volume_sql,
    day_window_selectbox,
    defer_source_note,
    download_csv,
    ensure_column_alias,
    filter_existing_columns,
    get_db_filter_clause,
    get_session,
    format_snowflake_error,
    make_action_id,
    render_drillable_bar_chart,
    render_priority_dataframe,
    render_workflow_selector,
    run_query,
    safe_float,
    safe_int,
    scope_metadata_df,
    show_to_df,
    upsert_actions,
)
from sections.shell_helpers import render_shell_snapshot


PIPELINE_HEALTH_PANES = (
    "Freshness SLA",
    "Load Failures",
    "Volume Watch",
    "Snowpipe Usage",
    "Dynamic Tables",
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
    elif finding_type == "Snowpipe":
        routed["NEXT_WORKFLOW"] = "Pipeline health"
        routed["NEXT_ACTION"] = "Confirm pipe owner, file backlog, recent COPY errors, and whether ingestion credits match expected volume."
    elif finding_type == "Dynamic Table":
        routed["NEXT_WORKFLOW"] = "Change & drift"
        routed["NEXT_ACTION"] = "Review refresh state, target lag, upstream changes, and the latest refresh query before changing lag or warehouse settings."
    else:
        routed["NEXT_WORKFLOW"] = "Change & drift"
        routed["NEXT_ACTION"] = "Review route, retention, table growth, and lifecycle policy before archive/drop or clustering changes."
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
            entity_type = "Table"
            severity = "High" if safe_float(row.get("HOURS_SINCE_CHANGE", 0)) >= 72 else "Medium"
            finding = f"{entity} has not changed for {safe_int(row.get('HOURS_SINCE_CHANGE', 0))} hours"
            action = "Confirm upstream pipeline SLA, source feed health, and whether the table is still business critical."
            proof = "ACCOUNT_USAGE.TABLES last_altered freshness scan"
        elif finding_type == "Load Failure":
            entity_type = "Table"
            severity = "High"
            finding = f"{entity} has {safe_int(row.get('FILE_COUNT', 0))} failed load files with status {row.get('STATUS', '')}"
            action = "Review COPY_HISTORY error, repair source file/stage issue, and reload failed files."
            proof = "ACCOUNT_USAGE.COPY_HISTORY non-loaded status scan"
        elif finding_type == "Snowpipe":
            entity = str(row.get("PIPE_NAME") or "Unknown pipe")
            entity_type = "Pipe"
            credits = safe_float(row.get("DAILY_CREDITS", 0))
            files = safe_int(row.get("FILES_INSERTED", 0))
            severity = "High" if credits >= 10 else "Medium"
            finding = f"{entity} used {credits:,.2f} Snowpipe credits with {files:,} files inserted."
            action = "Confirm pipe owner, ingestion volume, failed files, and whether batching or source cadence changed."
            proof = "ACCOUNT_USAGE.PIPE_USAGE_HISTORY credit and file-volume scan"
        elif finding_type == "Dynamic Table":
            name = row.get("NAME", row.get("DYNAMIC_TABLE_NAME", ""))
            entity = ".".join([str(v) for v in [db, schema, name] if v])
            entity_type = "Dynamic Table"
            state = str(row.get("LAST_REFRESH_STATE_CODE") or row.get("STATE") or "UNKNOWN")
            severity = "High" if state.upper() not in {"", "SUCCESS", "SUCCEEDED", "ACTIVE"} else "Medium"
            finding = f"{entity} refresh state is {state}."
            action = "Review refresh state/message, target lag, upstream changes, and latest refresh query."
            proof = "SHOW DYNAMIC TABLES plus ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY"
        else:
            entity_type = "Table"
            severity = "Medium"
            finding = f"{entity} is on volume watch: {row.get('WATCH_REASON', '')}; {safe_float(row.get('SIZE_GB', 0)):,.1f} GB"
            action = "Review retention, clustering, time travel, and whether old data can be archived or dropped."
            proof = "ACCOUNT_USAGE.TABLES size and last_altered scan"
        actions.append({
            "Action ID": make_action_id("Pipeline", entity, finding),
            "Source": f"Pipeline Health - {finding_type}",
            "Severity": severity,
            "Category": "Pipeline",
            "Entity Type": entity_type,
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
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _pipe_company_filter(company: str) -> str:
    company_upper = str(company or "").upper()
    if company_upper == "TREXIS":
        return "AND pipe_name ILIKE '%TRXS%'"
    if company_upper == "ALFA":
        return "AND pipe_name NOT ILIKE '%TRXS%'"
    return ""


def _load_dynamic_table_inventory(session, company: str, days: int) -> pd.DataFrame:
    df_dyn = show_to_df(session, "SHOW DYNAMIC TABLES IN ACCOUNT")
    df_dyn = ensure_column_alias(df_dyn, "NAME", ["NAME", "DYNAMIC_TABLE_NAME"])
    df_dyn = ensure_column_alias(df_dyn, "DATABASE_NAME", ["DATABASE_NAME", "DATABASE"])
    df_dyn = ensure_column_alias(df_dyn, "SCHEMA_NAME", ["SCHEMA_NAME", "SCHEMA"])
    df_dyn = scope_metadata_df(df_dyn, company=company)
    if df_dyn.empty:
        return df_dyn

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
        db_filter = get_db_filter_clause("database_name", company) if "DATABASE_NAME" in available_cols else ""
        df_refresh = run_query(f"""
            SELECT {", ".join(select_cols)}
            FROM {refresh_object}
            WHERE refresh_start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
              {db_filter}
            ORDER BY refresh_start_time DESC
            LIMIT 5000
        """, ttl_key=f"pipeline_dynamic_refresh_{company}_{days}", tier="standard", section="Pipeline Health")
        if df_refresh.empty or not all(c in df_dyn.columns for c in ["DATABASE_NAME", "SCHEMA_NAME", "NAME"]):
            return df_dyn
        df_refresh = df_refresh.rename(columns={
            "STATE_CODE": "LAST_REFRESH_STATE_CODE",
            "STATE_MESSAGE": "LAST_REFRESH_MESSAGE",
            "REFRESH_START_TIME": "LAST_REFRESH_START_TIME",
            "REFRESH_END_TIME": "LAST_REFRESH_END_TIME",
            "QUERY_ID": "LAST_REFRESH_QUERY_ID",
        })
        if "LAST_REFRESH_START_TIME" in df_refresh.columns:
            df_refresh = df_refresh.sort_values("LAST_REFRESH_START_TIME", ascending=False)
        keep_cols = [
            c for c in [
                "DATABASE_NAME", "SCHEMA_NAME", "NAME",
                "LAST_REFRESH_STATE_CODE", "LAST_REFRESH_MESSAGE",
                "REFRESH_ACTION", "REFRESH_TRIGGER",
                "LAST_REFRESH_START_TIME", "LAST_REFRESH_END_TIME",
                "TARGET_LAG_SEC", "LAST_REFRESH_QUERY_ID",
            ]
            if c in df_refresh.columns
        ]
        df_refresh = df_refresh[keep_cols].drop_duplicates(["DATABASE_NAME", "SCHEMA_NAME", "NAME"])
        return df_dyn.merge(df_refresh, how="left", on=["DATABASE_NAME", "SCHEMA_NAME", "NAME"])
    except Exception:
        return df_dyn


def render():
    session = get_session()
    company = st.session_state.get("active_company", "ALFA")
    active_view = render_workflow_selector(
        "Pipeline health view",
        "pipeline_health_active_view",
        PIPELINE_HEALTH_PANES,
        columns=3,
        show_label=True,
    )

    if active_view == "Freshness SLA":
        st.subheader("Pipeline Freshness SLA")
        stale_hours = st.slider("Stale threshold (hours)", 4, 168, 24, key="pipe_stale_hours")
        if st.button("Load Freshness Watchlist", key="pipe_fresh_load"):
            try:
                df_fresh = run_query(
                    build_mart_pipeline_freshness_sql(stale_hours, company),
                    ttl_key=f"pipeline_fresh_mart_{company}_{stale_hours}",
                    tier="historical",
                    section="Pipeline Health",
                )
                st.session_state["pipe_freshness_source"] = "Fast table freshness summary"
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
            defer_source_note(st.session_state.get("pipe_freshness_source", "SNOWFLAKE.ACCOUNT_USAGE.TABLES"))
            if df_fresh.empty:
                st.success("No stale tables found for the selected threshold.")
            else:
                render_shell_snapshot((
                    ("Stale tables", f"{len(df_fresh):,}"),
                    ("Databases", f"{df_fresh['DATABASE_NAME'].nunique():,}"),
                    ("Largest stale table GB", f"{float(df_fresh['SIZE_GB'].max() or 0):,.1f}"),
                ))
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
        st.subheader("Load Failure Monitor")
        load_days = day_window_selectbox("Lookback", key="pipe_load_days", default=7)
        if st.button("Load Copy History Failures", key="pipe_load_failures"):
            try:
                df_loads = run_query(
                    build_mart_pipeline_load_failures_sql(load_days, company),
                    ttl_key=f"pipeline_loads_mart_{company}_{load_days}",
                    tier="historical",
                    section="Pipeline Health",
                )
                st.session_state["pipe_load_failures_source"] = "Fast load history summary"
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
            defer_source_note(st.session_state.get("pipe_load_failures_source", "SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY"))
            if df_loads.empty:
                st.success("No copy/load failures found in the selected window.")
            else:
                render_shell_snapshot((("Failed load groups", f"{len(df_loads):,}"),))
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
        st.subheader("Table Volume Watch")
        defer_source_note("Highlights large and fast-changing tables from ACCOUNT_USAGE.TABLES metadata.")
        min_gb = st.slider("Minimum table size (GB)", 1, 500, 25, key="pipe_min_gb")
        if st.button("Load Volume Watchlist", key="pipe_volume_load"):
            try:
                df_volume = run_query(
                    build_mart_pipeline_volume_sql(min_gb, company),
                    ttl_key=f"pipeline_volume_mart_{company}_{min_gb}",
                    tier="historical",
                    section="Pipeline Health",
                )
                st.session_state["pipe_volume_source"] = "Fast table volume summary"
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
            defer_source_note(st.session_state.get("pipe_volume_source", "SNOWFLAKE.ACCOUNT_USAGE.TABLES"))
            if df_volume.empty:
                st.success("No tables matched the volume threshold.")
            else:
                render_shell_snapshot((
                    ("Watchlist tables", f"{len(df_volume):,}"),
                    ("Total watchlist GB", f"{float(df_volume['SIZE_GB'].sum() or 0):,.1f}"),
                ))
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

    elif active_view == "Snowpipe Usage":
        st.subheader("Snowpipe Usage")
        defer_source_note("Snowpipe credit and file-volume monitoring from ACCOUNT_USAGE.PIPE_USAGE_HISTORY.")
        pipe_days = day_window_selectbox("Lookback", key="pipe_snowpipe_days", default=7)
        if st.button("Load Snowpipe Usage", key="pipe_snowpipe_load"):
            try:
                df_pipe = run_query(f"""
                    SELECT
                        pipe_name,
                        DATE_TRUNC('day', start_time) AS day,
                        ROUND(SUM(credits_used), 4) AS daily_credits,
                        ROUND(SUM(bytes_inserted) / POWER(1024, 3), 2) AS gb_inserted,
                        SUM(files_inserted) AS files_inserted
                    FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
                    WHERE start_time >= DATEADD('day', -{int(pipe_days)}, CURRENT_TIMESTAMP())
                      {_pipe_company_filter(company)}
                    GROUP BY pipe_name, day
                    ORDER BY daily_credits DESC, files_inserted DESC
                    LIMIT 300
                """, ttl_key=f"pipeline_snowpipe_{company}_{pipe_days}", tier="standard", section="Pipeline Health")
                st.session_state["pipe_snowpipe"] = _annotate_pipeline_routes(df_pipe, "Snowpipe")
                st.session_state["pipe_snowpipe_source"] = "Live: SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY"
            except Exception as e:
                st.warning(f"Snowpipe usage unavailable in this role/context: {format_snowflake_error(e)}")
                st.session_state["pipe_snowpipe"] = pd.DataFrame()

        df_pipe = st.session_state.get("pipe_snowpipe")
        if df_pipe is not None:
            defer_source_note(st.session_state.get("pipe_snowpipe_source", "SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY"))
            if df_pipe.empty:
                st.info("No Snowpipe usage found for the selected period and company scope.")
            else:
                render_shell_snapshot((
                    ("Pipes active", f"{df_pipe['PIPE_NAME'].nunique():,}"),
                    ("Credits", f"{safe_float(df_pipe['DAILY_CREDITS'].sum()):,.2f}"),
                    ("Files inserted", f"{safe_int(df_pipe['FILES_INSERTED'].sum()):,}"),
                ))
                render_priority_dataframe(
                    df_pipe,
                    title="Snowpipe cost and volume drivers",
                    priority_columns=[
                        "PIPE_NAME", "DAY", "DAILY_CREDITS", "GB_INSERTED",
                        "FILES_INSERTED", "NEXT_WORKFLOW", "NEXT_ACTION",
                    ],
                    sort_by=["DAILY_CREDITS", "FILES_INSERTED"],
                    ascending=[False, False],
                    raw_label="All Snowpipe usage rows",
                )
                download_csv(df_pipe, "pipeline_snowpipe_usage.csv")
                if st.button("Save Snowpipe findings to Action Queue", key="pipe_snowpipe_queue"):
                    _queue_pipeline_findings(session, df_pipe, "Snowpipe")

    elif active_view == "Dynamic Tables":
        st.subheader("Dynamic Table Refresh Health")
        st.caption("Inventory and latest refresh state for Snowflake dynamic tables.")
        dyn_days = day_window_selectbox("Refresh lookback", key="pipe_dynamic_days", default=7)
        if st.button("Load Dynamic Tables", key="pipe_dynamic_load"):
            try:
                df_dyn = _load_dynamic_table_inventory(session, company, dyn_days)
                st.session_state["pipe_dynamic_tables"] = _annotate_pipeline_routes(df_dyn, "Dynamic Table")
                st.session_state["pipe_dynamic_source"] = "SHOW DYNAMIC TABLES + ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY"
            except Exception as e:
                st.info(f"Dynamic table data unavailable in this role/context: {format_snowflake_error(e)}")
                st.session_state["pipe_dynamic_tables"] = pd.DataFrame()

        df_dyn = st.session_state.get("pipe_dynamic_tables")
        if df_dyn is not None:
            defer_source_note(st.session_state.get("pipe_dynamic_source", "SHOW DYNAMIC TABLES"))
            if df_dyn.empty:
                st.info("No dynamic tables found for the selected company scope.")
            else:
                state_col = "LAST_REFRESH_STATE_CODE" if "LAST_REFRESH_STATE_CODE" in df_dyn.columns else "STATE"
                bad_states = pd.Series([False] * len(df_dyn), index=df_dyn.index)
                if state_col in df_dyn.columns:
                    bad_states = ~df_dyn[state_col].fillna("").astype(str).str.upper().isin(["", "SUCCESS", "SUCCEEDED", "ACTIVE"])
                render_shell_snapshot((
                    ("Dynamic tables", f"{len(df_dyn):,}"),
                    ("Refresh alerts", f"{int(bad_states.sum()):,}"),
                    ("Databases", f"{df_dyn['DATABASE_NAME'].nunique() if 'DATABASE_NAME' in df_dyn.columns else 0:,}"),
                ))
                render_priority_dataframe(
                    df_dyn,
                    title="Dynamic tables needing attention",
                    priority_columns=[
                        "DATABASE_NAME", "SCHEMA_NAME", "NAME", "STATE",
                        "LAST_REFRESH_STATE_CODE", "LAST_REFRESH_MESSAGE",
                        "REFRESH_ACTION", "REFRESH_TRIGGER", "LAST_REFRESH_START_TIME",
                        "TARGET_LAG_SEC", "LAST_REFRESH_QUERY_ID", "NEXT_WORKFLOW", "NEXT_ACTION",
                    ],
                    sort_by=["LAST_REFRESH_STATE_CODE", "LAST_REFRESH_START_TIME", "TARGET_LAG_SEC"],
                    ascending=[True, False, False],
                    raw_label="All dynamic table rows",
                )
                download_csv(df_dyn, "pipeline_dynamic_tables.csv")
                if int(bad_states.sum()) and st.button("Save dynamic table findings to Action Queue", key="pipe_dynamic_queue"):
                    _queue_pipeline_findings(session, df_dyn[bad_states], "Dynamic Table")
