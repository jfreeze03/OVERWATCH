# sections/dba_tools.py — DBA admin toolkit
# ─────────────────────────────────────────────────────────────────────────────
# NEW tabs vs prior version:
#   Tab 1  — Auto-Suspend Audit → FULL INTERACTIVE WAREHOUSE SETTINGS MANAGER
#             (all ALTER WAREHOUSE params: size, suspend, timeout, scaling, QAS)
#   Tab 14 — Warehouse Settings Manager (promoted from stub)
#   Tab 15 — ⚙️ Cortex AI Limits (SHOW AI SERVICES, ALTER ACCOUNT limits)
#   Tab 16 — 🔀 Task Graph Control (cancel running tasks, cancel task graphs,
#             suspend/resume task trees, restart failed tasks)
#   Tab 17 — 📊 Usage Log (carried forward)
# ─────────────────────────────────────────────────────────────────────────────
import streamlit as st
import pandas as pd
from utils import (
    get_session, normalize_df, safe_sql, format_credits, download_csv,
    get_wh_filter_clause, get_active_company,
    build_overwatch_setup_bundle, build_bookmark_ddl, build_annotation_ddl,
    build_action_queue_ddl, build_snowflake_value_ddl, build_usage_log_ddl,
    build_alert_task_sql,
)
from config import (
    ALERT_DB, ALERT_SCHEMA, ALERT_TABLE,
    ACTION_QUEUE_TABLE, ETL_AUDIT_DB, ETL_AUDIT_SCHEMA,
)

# ── Snowflake warehouse parameter documentation ──────────────────────────────
_WH_PARAM_HELP = {
    "WAREHOUSE_SIZE":           "Credit rate: X-Small=1, Small=2, Medium=4, Large=8, X-Large=16, 2X-Large=32...",
    "AUTO_SUSPEND":             "Seconds of inactivity before the warehouse suspends. 0 = never. Recommended: 60–300.",
    "AUTO_RESUME":              "Automatically resume when a query is submitted. Should almost always be TRUE.",
    "STATEMENT_TIMEOUT_IN_SECONDS": "Maximum seconds a single query can run before being cancelled. 0 = no limit. Recommended: 3600.",
    "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": "Max seconds a query waits in the queue. 0 = no limit. Recommended: 600.",
    "MAX_CONCURRENCY_LEVEL":    "Max concurrent SQL statements per cluster. Default: 8. Range: 1–10.",
    "MAX_CLUSTER_COUNT":        "Multi-cluster: max number of clusters. 1 = single cluster. Requires Enterprise.",
    "MIN_CLUSTER_COUNT":        "Multi-cluster: min clusters always running. Setting >1 incurs constant credit cost.",
    "SCALING_POLICY":           "STANDARD = scale up when queue builds. ECONOMY = scale only when full queue detected.",
    "ENABLE_QUERY_ACCELERATION": "Allow eligible queries to use the Query Acceleration Service. Requires Enterprise.",
    "QUERY_ACCELERATION_MAX_SCALE_FACTOR": "Max scale factor for QAS (0 = unlimited, 1–100). Each factor = 1 credit/hr.",
    "COMMENT":                  "Free-text label for this warehouse.",
}

_SIZE_OPTS = ["X-Small","Small","Medium","Large","X-Large","2X-Large","3X-Large","4X-Large","5X-Large","6X-Large"]
_SIZE_SQL = {
    "X-Small": "XSMALL",
    "Small": "SMALL",
    "Medium": "MEDIUM",
    "Large": "LARGE",
    "X-Large": "XLARGE",
    "2X-Large": "XXLARGE",
    "3X-Large": "XXXLARGE",
    "4X-Large": "X4LARGE",
    "5X-Large": "X5LARGE",
    "6X-Large": "X6LARGE",
}
_SCALE_OPTS = ["STANDARD","ECONOMY"]


def _load_button(label, key):
    return st.button(label, key=key)


def _scope_warehouse_names(df: pd.DataFrame, name_col: str = "name") -> pd.DataFrame:
    """Apply ALFA/Trexis warehouse visibility to SHOW-style result sets."""
    if df is None or df.empty or name_col not in df.columns:
        return df
    company = get_active_company()
    if company == "Trexis":
        return df[df[name_col].astype(str).str.upper().str.startswith("WH_TRXS_")]
    if company == "ALFA":
        return df[~df[name_col].astype(str).str.upper().str.startswith("WH_TRXS_")]
    return df


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _as_bool(value, default: bool = False) -> bool:
    if value is None or str(value).lower() in ("", "nan", "none"):
        return default
    return str(value).strip().lower() in ("true", "yes", "1", "on")


def _as_int(value, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _table_exists(session, db: str, schema: str, table: str):
    try:
        row = session.sql(f"""
            SELECT COUNT(*) AS CNT
            FROM {db}.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = '{safe_sql(schema.upper())}'
              AND TABLE_NAME = '{safe_sql(table.upper())}'
        """).collect()[0]
        return int(row["CNT"]) > 0
    except Exception:
        return None


def _task_exists(session, db: str, schema: str, task_name: str):
    try:
        rows = session.sql(
            f"SHOW TASKS LIKE '{safe_sql(task_name.upper())}' IN SCHEMA {db}.{schema}"
        ).collect()
        return len(rows) > 0
    except Exception:
        return None


def _setup_status_df(session) -> pd.DataFrame:
    checks = [
        ("Saved Views", "TABLE", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_BOOKMARKS", build_bookmark_ddl),
        ("Annotation Windows", "TABLE", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_ANNOTATIONS", build_annotation_ddl),
        ("Alert History", "TABLE", ALERT_DB, ALERT_SCHEMA, ALERT_TABLE, None),
        ("Action Queue", "TABLE", ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE, build_action_queue_ddl),
        ("Snowflake Value Log", "TABLE", ETL_AUDIT_DB, ETL_AUDIT_SCHEMA, "OVERWATCH_ROI_LOG", build_snowflake_value_ddl),
        ("Usage Log", "TABLE", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_USAGE_LOG", build_usage_log_ddl),
        ("Anomaly Alert Task", "TASK", ALERT_DB, ALERT_SCHEMA, "OVERWATCH_ANOMALY_CHECK", build_alert_task_sql),
    ]
    rows = []
    for feature, object_type, db, schema, object_name, ddl_builder in checks:
        exists = (
            _task_exists(session, db, schema, object_name)
            if object_type == "TASK"
            else _table_exists(session, db, schema, object_name)
        )
        if exists is True:
            status = "Present"
        elif exists is False:
            status = "Missing"
        else:
            status = "Unknown"
        rows.append({
            "FEATURE": feature,
            "OBJECT_TYPE": object_type,
            "OBJECT_NAME": f"{db}.{schema}.{object_name}",
            "STATUS": status,
            "SETUP_SQL_INCLUDED": "Yes" if ddl_builder else "Via alert task setup",
        })
    return pd.DataFrame(rows)


def render():
    session = get_session()

    tabs = st.tabs([
        "Query Kill List",
        "⚙️ Warehouse Settings",       # Tab 1 — REWRITTEN
        "Data Loading",
        "Network & Sessions",
        "Unused Objects",
        "Snowpipe Monitor",
        "QAS Monitor",
        "Schema Compare",
        "Recent Objects",
        "Pre-Aggregation",
        "Dynamic Tables",
        "Replication",
        "Serverless Costs",
        "🤖 Cortex AI Limits",         # Tab 14 — NEW
        "🔀 Task Graph Control",        # Tab 15 — NEW
        "📊 Usage Log",                 # Tab 16
        "🔧 First-Time Setup",
    ])

    # ── TAB 0: QUERY KILL LIST ────────────────────────────────────────────────
    with tabs[0]:
        st.header("⛔ Long-Running Query Kill List")
        kill_min = st.number_input("Flag queries running > (seconds)", 60, 3600, 300, key="kill_sec")
        if _load_button("Load Kill List", "kl_load"):
            try:
                df = normalize_df(session.sql(f"""
                    SELECT query_id, user_name, warehouse_name, warehouse_size, execution_status, start_time,
                           DATEDIFF('second', start_time, CURRENT_TIMESTAMP()) AS elapsed_sec,
                           SUBSTR(query_text,1,500) AS query_text
                    FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
                        END_TIME_RANGE_START=>DATEADD('hours',-2,CURRENT_TIMESTAMP()),
                        RESULT_LIMIT=>500))
                    WHERE execution_status IN ('RUNNING','QUEUED','BLOCKED')
                      AND DATEDIFF('second', start_time, CURRENT_TIMESTAMP()) > {kill_min}
                      {get_wh_filter_clause("warehouse_name")}
                    ORDER BY elapsed_sec DESC
                """).to_pandas())
                st.session_state["dba_df_kl"] = df
            except Exception as e:
                st.session_state["dba_df_kl"] = pd.DataFrame()
                st.caption(f"INFORMATION_SCHEMA unavailable: {e}")

        if st.session_state.get("dba_df_kl") is not None and not st.session_state["dba_df_kl"].empty:
            df = st.session_state["dba_df_kl"]
            st.warning(f"⚠️ {len(df)} queries running > {kill_min}s")
            st.dataframe(df, use_container_width=True)
            kill_id = st.selectbox("Kill query ID", df["QUERY_ID"].tolist(), key="kl_sel")
            if kill_id and st.button("⛔ Cancel Query", type="primary", key="kl_kill"):
                try:
                    session.sql(f"SELECT SYSTEM$CANCEL_QUERY('{safe_sql(kill_id)}')").collect()
                    st.success(f"✅ Cancel sent for `{kill_id}`")
                except Exception as e:
                    st.error(f"Cancel failed: {e}")
        elif st.session_state.get("dba_df_kl") is not None:
            st.success(f"✅ No queries running > {kill_min}s")

    # ── TAB 1: WAREHOUSE SETTINGS MANAGER ────────────────────────────────────
    with tabs[1]:
        st.header("⚙️ Warehouse Settings Manager")
        st.caption(
            "View and interactively change all warehouse parameters — "
            "size, timeouts, auto-suspend, multi-cluster, QAS, and scaling policy. "
            "Changes execute as `ALTER WAREHOUSE` statements in real time."
        )

        col_r1, col_r2 = st.columns([1, 1])
        with col_r1:
            if st.button("🔄 Load All Warehouses", key="wh_cfg_load"):
                try:
                    df_raw = session.sql("SHOW WAREHOUSES").to_pandas()
                    df_raw.columns = [c.lower() for c in df_raw.columns]
                    df_raw = _scope_warehouse_names(df_raw, "name")
                    st.session_state["dba_df_wh_cfg"] = df_raw
                except Exception as e:
                    st.error(f"SHOW WAREHOUSES failed: {e}")
        with col_r2:
            wh_filter_txt = st.text_input("Filter warehouse", key="wh_cfg_filter",
                                           placeholder="e.g. ALFA or leave blank for all")

        df_wh = st.session_state.get("dba_df_wh_cfg")
        if df_wh is not None and not df_wh.empty:
            # Apply filter
            if wh_filter_txt:
                mask   = df_wh["name"].astype(str).str.upper().str.contains(safe_sql(wh_filter_txt).upper(), na=False)
                df_wh  = df_wh[mask]

            # Summary table
            st.subheader(f"Warehouses ({len(df_wh)})")
            display_cols = [c for c in ["name","size","state","auto_suspend","auto_resume",
                                         "min_cluster_count","max_cluster_count","scaling_policy",
                                         "enable_query_acceleration","statement_timeout_in_seconds",
                                         "statement_queued_timeout_in_seconds"] if c in df_wh.columns]
            st.dataframe(df_wh[display_cols], use_container_width=True, height=220)

            # Flag issues
            issues = []
            for _, row in df_wh.iterrows():
                wn  = row.get("name","")
                sus = row.get("auto_suspend", 0)
                try:
                    if int(sus) > 600:
                        issues.append(f"🟡 **{wn}**: AUTO_SUSPEND={sus}s (>10 min) — wasting credits when idle")
                    if int(sus) == 0:
                        issues.append(f"🔴 **{wn}**: AUTO_SUSPEND=0 — warehouse NEVER suspends")
                except Exception:
                    pass
            if issues:
                with st.expander(f"⚠️ {len(issues)} configuration issue(s) detected"):
                    for i in issues:
                        st.markdown(i)

            st.divider()
            st.subheader("Edit Warehouse Settings")
            st.caption("Select a warehouse, adjust parameters, preview the ALTER SQL, then apply.")

            wh_names = df_wh["name"].tolist() if "name" in df_wh.columns else []
            sel_wh   = st.selectbox("Select warehouse to edit", wh_names, key="wh_edit_sel")

            if sel_wh:
                wh_row = df_wh[df_wh["name"] == sel_wh].iloc[0]

                def _get(col, default=""):
                    v = wh_row.get(col, default)
                    return "" if v is None or str(v).lower() in ("nan","none","") else str(v)

                st.markdown(f"**Editing: `{sel_wh}`**  ·  Current state: `{_get('state','unknown')}`")

                with st.form(f"wh_edit_form_{sel_wh}"):
                    c1, c2, c3 = st.columns(3)

                    with c1:
                        st.markdown("**Compute**")
                        curr_size = _get("size","X-Small")
                        new_size  = st.selectbox(
                            "Size", _SIZE_OPTS,
                            index=_SIZE_OPTS.index(curr_size) if curr_size in _SIZE_OPTS else 0,
                            key=f"wh_size_{sel_wh}",
                            help=_WH_PARAM_HELP["WAREHOUSE_SIZE"],
                        )
                        new_auto_resume = st.checkbox(
                            "Auto Resume",
                            value=_as_bool(_get("auto_resume","true"), True),
                            key=f"wh_ar_{sel_wh}",
                            help=_WH_PARAM_HELP["AUTO_RESUME"],
                        )
                        curr_sus = _as_int(_get("auto_suspend","600"), 600)
                        new_auto_suspend = st.number_input(
                            "AUTO_SUSPEND (seconds, 0=never)",
                            min_value=0, max_value=86400, value=curr_sus, step=60,
                            key=f"wh_sus_{sel_wh}",
                            help=_WH_PARAM_HELP["AUTO_SUSPEND"],
                        )

                    with c2:
                        st.markdown("**Timeouts**")
                        curr_stmt_to = _as_int(_get("statement_timeout_in_seconds","0"), 0)
                        new_stmt_timeout = st.number_input(
                            "STATEMENT_TIMEOUT (sec, 0=no limit)",
                            min_value=0, max_value=604800, value=curr_stmt_to, step=300,
                            key=f"wh_stmto_{sel_wh}",
                            help=_WH_PARAM_HELP["STATEMENT_TIMEOUT_IN_SECONDS"],
                        )
                        curr_q_to = _as_int(_get("statement_queued_timeout_in_seconds","0"), 0)
                        new_queue_timeout = st.number_input(
                            "QUEUE_TIMEOUT (sec, 0=no limit)",
                            min_value=0, max_value=86400, value=curr_q_to, step=60,
                            key=f"wh_qto_{sel_wh}",
                            help=_WH_PARAM_HELP["STATEMENT_QUEUED_TIMEOUT_IN_SECONDS"],
                        )
                        curr_concur = _as_int(_get("max_concurrency_level","8"), 8)
                        new_concurrency = st.number_input(
                            "MAX_CONCURRENCY_LEVEL",
                            min_value=1, max_value=10, value=min(max(curr_concur,1),10),
                            key=f"wh_concur_{sel_wh}",
                            help=_WH_PARAM_HELP["MAX_CONCURRENCY_LEVEL"],
                        )

                    with c3:
                        st.markdown("**Scaling & QAS**")
                        curr_scale = _get("scaling_policy","STANDARD").upper()
                        new_scaling = st.selectbox(
                            "SCALING_POLICY",
                            _SCALE_OPTS,
                            index=_SCALE_OPTS.index(curr_scale) if curr_scale in _SCALE_OPTS else 0,
                            key=f"wh_sp_{sel_wh}",
                            help=_WH_PARAM_HELP["SCALING_POLICY"],
                        )
                        curr_min = _as_int(_get("min_cluster_count","1"), 1)
                        curr_max = _as_int(_get("max_cluster_count","1"), 1)
                        new_min_clusters = st.number_input(
                            "MIN_CLUSTER_COUNT",
                            min_value=1, max_value=10, value=max(curr_min,1),
                            key=f"wh_minc_{sel_wh}",
                            help=_WH_PARAM_HELP["MIN_CLUSTER_COUNT"],
                        )
                        new_max_clusters = st.number_input(
                            "MAX_CLUSTER_COUNT",
                            min_value=1, max_value=10, value=max(curr_max,1),
                            key=f"wh_maxc_{sel_wh}",
                            help=_WH_PARAM_HELP["MAX_CLUSTER_COUNT"],
                        )
                        curr_qas = _as_bool(_get("enable_query_acceleration","false"), False)
                        new_qas  = st.checkbox(
                            "Enable QAS",
                            value=curr_qas,
                            key=f"wh_qas_{sel_wh}",
                            help=_WH_PARAM_HELP["ENABLE_QUERY_ACCELERATION"],
                        )
                        curr_qas_sf = _as_int(_get("query_acceleration_max_scale_factor","8"), 8)
                        new_qas_sf = st.number_input(
                            "QAS Max Scale Factor (0=unlimited)",
                            min_value=0, max_value=100, value=curr_qas_sf,
                            key=f"wh_qassf_{sel_wh}",
                            help=_WH_PARAM_HELP["QUERY_ACCELERATION_MAX_SCALE_FACTOR"],
                            disabled=not new_qas,
                        )

                    apply = st.form_submit_button("📋 Preview & Apply Changes", type="primary")

                if apply:
                    # Build ALTER WAREHOUSE statement from changed params
                    safe_wh = _quote_identifier(sel_wh)

                    params = [
                        f"WAREHOUSE_SIZE = {_SIZE_SQL.get(new_size, 'XSMALL')}",
                        f"AUTO_SUSPEND = {int(new_auto_suspend)}",
                        f"AUTO_RESUME = {'TRUE' if new_auto_resume else 'FALSE'}",
                        f"STATEMENT_TIMEOUT_IN_SECONDS = {int(new_stmt_timeout)}",
                        f"STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = {int(new_queue_timeout)}",
                        f"MAX_CONCURRENCY_LEVEL = {int(new_concurrency)}",
                        f"SCALING_POLICY = {new_scaling}",
                        f"MIN_CLUSTER_COUNT = {int(new_min_clusters)}",
                        f"MAX_CLUSTER_COUNT = {int(new_max_clusters)}",
                        f"ENABLE_QUERY_ACCELERATION = {'TRUE' if new_qas else 'FALSE'}",
                        f"QUERY_ACCELERATION_MAX_SCALE_FACTOR = {int(new_qas_sf)}",
                    ]
                    alter_sql = f"ALTER WAREHOUSE {safe_wh} SET\n    " + "\n    ".join(params) + ";"

                    st.subheader("📋 SQL Preview")
                    st.code(alter_sql, language="sql")

                    col_apply, col_cancel = st.columns([1, 3])
                    with col_apply:
                        if st.button("✅ Apply Now", type="primary", key=f"wh_apply_{sel_wh}"):
                            # CALLER MODE: ALTER WAREHOUSE needs MODIFY on the warehouse.
                            # SNOW_ACCOUNTADMIN and SNOW_SYSADMIN both have this.
                            # If a future role doesn't, this surfaces a clear error.
                            try:
                                session.sql(alter_sql).collect()
                                st.success(f"✅ Warehouse `{sel_wh}` updated successfully.")
                                st.session_state.pop("dba_df_wh_cfg", None)
                                st.rerun()
                            except Exception as e:
                                err_str = str(e).lower()
                                if "insufficient privilege" in err_str or "not authorized" in err_str:
                                    st.error(
                                        f"⛔ **Permission denied on `{sel_wh}`.** "
                                        f"ALTER WAREHOUSE requires MODIFY privilege. "
                                        f"Your current role may not have this on this warehouse."
                                    )
                                elif "enterprise" in err_str or "not supported" in err_str:
                                    st.error(
                                        f"⛔ **Feature not available in your Snowflake edition.** "
                                        f"Multi-cluster and QAS require Enterprise or higher."
                                    )
                                else:
                                    st.error(f"ALTER failed: {e}")

    # ── TAB 2: DATA LOADING ───────────────────────────────────────────────────
    with tabs[2]:
        st.header("📦 Data Loading Monitor")
        load_days = st.slider("Lookback (days)", 1, 30, 7, key="dl_days")
        if _load_button("Load Copy History", "dl_load"):
            try:
                st.session_state["dba_df_copy"] = normalize_df(session.sql(f"""
                    SELECT table_name, file_name, status, row_count,
                           first_error_message, last_load_time
                    FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
                    WHERE last_load_time >= DATEADD('day', -{load_days}, CURRENT_TIMESTAMP())
                    ORDER BY last_load_time DESC LIMIT 500
                """).to_pandas())
            except Exception as e:
                st.error(f"Error: {e}")
        if st.session_state.get("dba_df_copy") is not None and not st.session_state["dba_df_copy"].empty:
            st.dataframe(st.session_state["dba_df_copy"], use_container_width=True)
            download_csv(st.session_state["dba_df_copy"], "copy_history.csv")

    # ── TABS 3–13: CARRIED FORWARD (abbreviated for file size) ───────────────
    with tabs[3]:
        st.header("🌐 Network & Sessions")
        if _load_button("Load Session Data", "net_load"):
            try:
                st.session_state["dba_df_long_sess"] = normalize_df(session.sql("""
                    SELECT session_id, user_name, created_on,
                           DATEDIFF('hour', created_on, CURRENT_TIMESTAMP()) AS session_hours
                    FROM SNOWFLAKE.ACCOUNT_USAGE.SESSIONS
                    WHERE created_on >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                      AND DATEDIFF('hour', created_on, CURRENT_TIMESTAMP()) > 8
                    ORDER BY session_hours DESC LIMIT 100
                """).to_pandas())
            except Exception as e:
                st.info(f"Sessions unavailable: {e}")
        if st.session_state.get("dba_df_long_sess") is not None:
            st.dataframe(st.session_state["dba_df_long_sess"], use_container_width=True)

    with tabs[4]:
        st.header("🗑️ Unused Objects")
        if _load_button("Find Unused Tables", "unused_load"):
            try:
                st.session_state["dba_df_unused"] = normalize_df(session.sql("""
                    SELECT table_catalog, table_schema, table_name, row_count,
                           bytes/POWER(1024,3) AS table_gb, created, last_altered
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                    WHERE deleted IS NULL
                      AND last_altered < DATEADD('day', -90, CURRENT_TIMESTAMP())
                    ORDER BY bytes DESC NULLS LAST LIMIT 200
                """).to_pandas())
            except Exception as e:
                st.error(f"Error: {e}")
        if st.session_state.get("dba_df_unused") is not None:
            st.dataframe(st.session_state["dba_df_unused"], use_container_width=True)

    with tabs[5]:
        st.header("🔧 Snowpipe Monitor")
        sp_days = st.slider("Lookback (days)", 1, 14, 3, key="spipe_days")
        if _load_button("Load Pipe Usage", "spipe_load"):
            try:
                st.session_state["dba_df_pipe"] = normalize_df(session.sql(f"""
                    SELECT pipe_name, DATE_TRUNC('day', start_time) AS day,
                           SUM(credits_used) AS daily_credits,
                           SUM(bytes_inserted)/POWER(1024,3) AS gb_inserted,
                           SUM(files_inserted) AS files_inserted
                    FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
                    WHERE start_time >= DATEADD('day', -{sp_days}, CURRENT_TIMESTAMP())
                    GROUP BY pipe_name, day ORDER BY daily_credits DESC
                """).to_pandas())
            except Exception as e:
                st.error(f"Error: {e}")
        if st.session_state.get("dba_df_pipe") is not None:
            st.dataframe(st.session_state["dba_df_pipe"], use_container_width=True)

    with tabs[6]:
        st.header("⚡ QAS Monitor")
        qas_days = st.slider("Lookback (days)", 1, 30, 7, key="qas_days")
        if _load_button("Load QAS Data", "qas_load"):
            try:
                st.session_state["dba_df_qas"] = normalize_df(session.sql(f"""
                    WITH latest_size AS (
                        SELECT warehouse_name, warehouse_size
                        FROM (
                            SELECT warehouse_name, warehouse_size,
                                   ROW_NUMBER() OVER (PARTITION BY warehouse_name ORDER BY start_time DESC) AS rn
                            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                            WHERE start_time >= DATEADD('day', -{qas_days}, CURRENT_TIMESTAMP())
                              AND warehouse_name IS NOT NULL
                        )
                        WHERE rn = 1
                    )
                    SELECT q.warehouse_name, ls.warehouse_size, DATE_TRUNC('day', q.start_time) AS day,
                           SUM(q.credits_used) AS daily_credits, COUNT(*) AS query_count
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ACCELERATION_HISTORY q
                    LEFT JOIN latest_size ls ON q.warehouse_name = ls.warehouse_name
                    WHERE q.start_time >= DATEADD('day', -{qas_days}, CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("q.warehouse_name")}
                    GROUP BY q.warehouse_name, ls.warehouse_size, day ORDER BY daily_credits DESC
                """).to_pandas())
            except Exception as e:
                st.info(f"QAS data unavailable: {e}")
        if st.session_state.get("dba_df_qas") is not None:
            st.dataframe(st.session_state["dba_df_qas"], use_container_width=True)

    with tabs[7]:
        st.header("📐 Schema Compare")
        c1, c2 = st.columns(2)
        with c1:
            dev_db  = st.text_input("Dev Database",  value="DEV_DB",  key="sc_dev")
            dev_sch = st.text_input("Dev Schema",    value="PUBLIC",  key="sc_devsch")
        with c2:
            prod_db  = st.text_input("Prod Database", value="PROD_DB", key="sc_prod")
            prod_sch = st.text_input("Prod Schema",   value="PUBLIC",  key="sc_prodsch")
        if st.button("Compare Schemas", key="sc_run"):
            try:
                df_dev  = normalize_df(session.sql(f"SELECT table_name, row_count FROM {safe_sql(dev_db)}.INFORMATION_SCHEMA.TABLES WHERE table_schema='{safe_sql(dev_sch)}' AND table_type='BASE TABLE'").to_pandas())
                df_prod = normalize_df(session.sql(f"SELECT table_name, row_count FROM {safe_sql(prod_db)}.INFORMATION_SCHEMA.TABLES WHERE table_schema='{safe_sql(prod_sch)}' AND table_type='BASE TABLE'").to_pandas())
                df_cmp  = df_prod.merge(df_dev, on="TABLE_NAME", how="outer", suffixes=("_PROD","_DEV"))
                df_cmp["ROW_DIFF"] = df_cmp["ROW_COUNT_PROD"].fillna(0) - df_cmp["ROW_COUNT_DEV"].fillna(0)
                st.dataframe(df_cmp, use_container_width=True)
                download_csv(df_cmp, "schema_compare.csv")
            except Exception as e:
                st.error(f"Compare failed: {e}")

    with tabs[8]:
        st.header("🔎 Recent Objects")
        obj_days = st.slider("Created/altered within (days)", 1, 90, 30, key="obj_days")
        obj_db_clause = f"AND table_catalog ILIKE '%{safe_sql(st.text_input('Database filter', key='obj_db_filter'))}%'" if st.session_state.get("obj_db_filter") else ""
        if st.button("Load Recent Objects", key="obj_load"):
            try:
                st.session_state["dba_df_recent_objects"] = normalize_df(session.sql(f"""
                    SELECT table_catalog AS database_name, table_schema AS schema_name,
                           table_name AS object_name, table_type, created, last_altered, table_owner AS owner
                    FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
                    WHERE deleted IS NULL
                      AND (created >= DATEADD('day', -{obj_days}, CURRENT_TIMESTAMP())
                           OR last_altered >= DATEADD('day', -{obj_days}, CURRENT_TIMESTAMP()))
                      {obj_db_clause}
                    ORDER BY GREATEST(created, last_altered) DESC LIMIT 500
                """).to_pandas())
            except Exception as e:
                st.error(f"Error: {e}")
        if st.session_state.get("dba_df_recent_objects") is not None:
            st.dataframe(st.session_state["dba_df_recent_objects"], use_container_width=True)
            download_csv(st.session_state["dba_df_recent_objects"], "recent_objects.csv")

    with tabs[9]:
        st.header("Pre-Aggregation DDL")
        preagg_db = st.text_input("Target database", value="DBA_MAINT_DB", key="preagg_db")
        preagg_schema = st.text_input("Target schema", value="OVERWATCH",   key="preagg_schema")
        preagg_wh     = st.text_input("Warehouse",     value="COMPUTE_WH",  key="preagg_wh")
        preagg_sql = f"""CREATE OR REPLACE TABLE {preagg_db}.{preagg_schema}.HOURLY_WAREHOUSE_CREDITS AS
SELECT warehouse_name, DATE_TRUNC('hour', start_time) AS hour_bucket,
       SUM(credits_used_compute) AS compute_credits, SUM(credits_used) AS total_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('day', -90, CURRENT_TIMESTAMP())
GROUP BY warehouse_name, hour_bucket;"""
        st.code(preagg_sql, language="sql")
        st.download_button("Download Pre-Aggregation SQL", preagg_sql, file_name="overwatch_preagg.sql", mime="text/plain")

    with tabs[10]:
        st.header("🔄 Dynamic Tables")
        if st.button("Load Dynamic Tables", key="dyn_load"):
            try:
                st.session_state["dba_df_dyn"] = normalize_df(session.sql("""
                    WITH live_dt AS (
                        SELECT database_name, schema_name, name, state, target_lag_sec,
                               refresh_mode, last_completed_refresh_state,
                               last_completed_refresh_state_message,
                               maximum_lag_sec,
                               time_within_target_lag_ratio,
                               executing_refresh_query_id
                        FROM TABLE(INFORMATION_SCHEMA.DYNAMIC_TABLES(RESULT_LIMIT => 10000))
                    ),
                    recent_refresh AS (
                        SELECT database_name, schema_name, name,
                               state AS last_refresh_state,
                               completed_time AS last_refresh_completed_time,
                               credits_used,
                               ROW_NUMBER() OVER (
                                   PARTITION BY database_name, schema_name, name
                                   ORDER BY completed_time DESC
                               ) AS rn
                        FROM SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY
                        WHERE refresh_start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
                    )
                    SELECT l.*,
                           r.last_refresh_state,
                           r.last_refresh_completed_time,
                           r.credits_used AS last_refresh_credits
                    FROM live_dt l
                    LEFT JOIN recent_refresh r
                      ON l.database_name = r.database_name
                     AND l.schema_name = r.schema_name
                     AND l.name = r.name
                     AND r.rn = 1
                    ORDER BY l.maximum_lag_sec DESC NULLS LAST, l.name
                    LIMIT 500
                """).to_pandas())
            except Exception as e:
                st.info(f"Dynamic table data unavailable: {e}")
        if st.session_state.get("dba_df_dyn") is not None:
            st.dataframe(st.session_state["dba_df_dyn"], use_container_width=True)
            download_csv(st.session_state["dba_df_dyn"], "dynamic_tables.csv")

    with tabs[11]:
        st.header("🔁 Replication")
        repl_days = st.slider("Lookback (days)", 1, 90, 30, key="repl_days")
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
                ORDER BY start_time DESC
                LIMIT 500
            """
            try:
                st.session_state["dba_df_repl"] = normalize_df(session.sql(repl_sql_primary).to_pandas())
                st.session_state["dba_repl_source"] = "REPLICATION_GROUP_USAGE_HISTORY"
            except Exception as primary_error:
                try:
                    st.session_state["dba_df_repl"] = normalize_df(session.sql(repl_sql_fallback).to_pandas())
                    st.session_state["dba_repl_source"] = "REPLICATION_USAGE_HISTORY"
                except Exception as fallback_error:
                    st.info(f"Replication data unavailable: {fallback_error}")
                    st.caption(f"Primary view also failed: {primary_error}")
        if st.session_state.get("dba_df_repl") is not None and not st.session_state["dba_df_repl"].empty:
            st.caption(f"Source: {st.session_state.get('dba_repl_source', 'replication usage history')}")
            st.metric("Replication Credits", format_credits(st.session_state["dba_df_repl"]["CREDITS_USED"].sum()))
            st.dataframe(st.session_state["dba_df_repl"], use_container_width=True)
            download_csv(st.session_state["dba_df_repl"], "replication_history.csv")

    with tabs[12]:
        st.header("💻 Serverless Costs")
        sv_days = st.slider("Lookback (days)", 7, 90, 30, key="sv_days")
        if st.button("Load Serverless Costs", key="sv_load"):
            try:
                st.session_state["dba_df_serverless"] = normalize_df(session.sql(f"""
                    SELECT service_type, DATE_TRUNC('day', start_time) AS usage_date,
                           SUM(credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -{sv_days}, CURRENT_TIMESTAMP())
                      AND service_type NOT IN ('WAREHOUSE_METERING','WAREHOUSE_METERING_READER')
                    GROUP BY service_type, usage_date ORDER BY daily_credits DESC
                """).to_pandas())
            except Exception as e:
                st.error(f"Error: {e}")
        if st.session_state.get("dba_df_serverless") is not None and not st.session_state["dba_df_serverless"].empty:
            df_sv = st.session_state["dba_df_serverless"]
            svc   = df_sv.groupby("SERVICE_TYPE")["DAILY_CREDITS"].sum().reset_index().sort_values("DAILY_CREDITS", ascending=False)
            st.metric("Total Serverless Credits", format_credits(float(svc["DAILY_CREDITS"].sum())))
            st.dataframe(svc, use_container_width=True)
            st.area_chart(df_sv.pivot_table(index="USAGE_DATE", columns="SERVICE_TYPE", values="DAILY_CREDITS", aggfunc="sum").fillna(0))
            download_csv(df_sv, "serverless_costs.csv")

    # ── TAB 14: CORTEX AI LIMITS ──────────────────────────────────────────────
    with tabs[13]:
        st.header("🤖 Cortex AI Limits")
        st.caption(
            "View and modify Cortex AI service limits for your account. "
            "These control daily token budgets, inference rate limits, and Cortex Search/Analyst access. "
            "Requires ACCOUNTADMIN or SYSADMIN with MODIFY ACCOUNT privilege."
        )

        # ── Current parameters ────────────────────────────────────────────────
        if st.button("🔄 Load Current AI Parameters", key="cortex_params_load"):
            results = {}

            # SHOW PARAMETERS — account-level Cortex controls
            try:
                df_params = normalize_df(session.sql("SHOW PARAMETERS LIKE '%CORTEX%' IN ACCOUNT").to_pandas())
                results["cortex_params"] = df_params
            except Exception as e:
                results["cortex_params"] = pd.DataFrame()
                st.caption(f"Account parameters unavailable: {e}")

            # Also check AI_SERVICES parameters
            try:
                df_ai = normalize_df(session.sql("SHOW PARAMETERS LIKE '%AI%' IN ACCOUNT").to_pandas())
                results["ai_params"] = df_ai
            except Exception:
                results["ai_params"] = pd.DataFrame()

            # Cortex usage today
            try:
                df_usage = normalize_df(session.sql("""
                    WITH combined AS (
                        SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS
                        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY
                        WHERE USAGE_TIME >= CURRENT_DATE()
                        UNION ALL
                        SELECT USER_ID, USAGE_TIME, TOKEN_CREDITS, TOKENS
                        FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY
                        WHERE USAGE_TIME >= CURRENT_DATE()
                    )
                    SELECT COUNT(*) AS requests_today,
                           SUM(TOKEN_CREDITS) AS credits_today,
                           SUM(TOKENS)        AS tokens_today,
                           COUNT(DISTINCT USER_ID) AS active_users
                    FROM combined
                """).to_pandas())
                results["usage_today"] = df_usage
            except Exception:
                results["usage_today"] = pd.DataFrame()

            st.session_state["dba_cortex_results"] = results

        res = st.session_state.get("dba_cortex_results", {})

        # Today's usage summary
        df_u = res.get("usage_today", pd.DataFrame())
        if not df_u.empty:
            st.subheader("Today's Cortex Usage")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Requests Today",    f"{int(df_u['REQUESTS_TODAY'].iloc[0]):,}")
            c2.metric("AI Credits Today",  f"{float(df_u['CREDITS_TODAY'].iloc[0]):.4f}")
            c3.metric("Tokens Today",      f"{int(df_u['TOKENS_TODAY'].iloc[0]):,}")
            c4.metric("Active Users",      f"{int(df_u['ACTIVE_USERS'].iloc[0])}")

        # Current parameters
        df_cp = res.get("cortex_params", pd.DataFrame())
        df_ai = res.get("ai_params",     pd.DataFrame())

        combined_params = pd.concat([df_cp, df_ai], ignore_index=True) if not df_cp.empty or not df_ai.empty else pd.DataFrame()
        if not combined_params.empty:
            st.subheader("Current Cortex / AI Account Parameters")
            st.dataframe(combined_params, use_container_width=True)
            download_csv(combined_params, "cortex_account_params.csv")
        else:
            st.info(
                "No Cortex parameters returned from SHOW PARAMETERS. "
                "This usually means Cortex AI features are not yet enabled on this account, "
                "or the current role doesn't have SHOW PARAMETERS privilege on ACCOUNT."
            )

        st.divider()

        # ── Modify parameters ─────────────────────────────────────────────────
        st.subheader("Modify Cortex AI Account Parameters")
        st.caption(
            "These ALTER ACCOUNT SET commands control Cortex AI behaviour across the account. "
            "Requires ACCOUNTADMIN. Changes take effect immediately."
        )

        with st.expander("🔧 Set Cortex Parameters", expanded=True):
            st.markdown("**Cortex Code Inline (Snowsight / VS Code)**")
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                cortex_enabled = st.selectbox(
                    "ENABLE_CORTEX_CODE_INLINE",
                    ["TRUE","FALSE"],
                    key="cortex_enable_sel",
                    help="Enables/disables Cortex Code inline AI in Snowsight for all users.",
                )
            with col_c2:
                cortex_daily_limit = st.number_input(
                    "CORTEX_CODE_DAILY_CREDIT_LIMIT (0 = no limit)",
                    min_value=0, max_value=100000, value=0, step=100,
                    key="cortex_daily_limit",
                    help="Maximum AI credits per day across all users. 0 = unrestricted.",
                )

            st.markdown("**Cortex Search & Analyst**")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                search_enabled = st.selectbox(
                    "ENABLE_CORTEX_SEARCH",
                    ["TRUE","FALSE"],
                    key="cortex_search_sel",
                    help="Enables Cortex Search (semantic document search).",
                )
            with col_s2:
                analyst_enabled = st.selectbox(
                    "ENABLE_SNOWFLAKE_INTELLIGENCE",
                    ["TRUE","FALSE"],
                    key="cortex_analyst_sel",
                    help="Enables Snowflake Intelligence / Cortex Analyst (natural language to SQL).",
                )

            generated_sql = f"""-- Cortex AI parameter changes
-- Run as ACCOUNTADMIN
ALTER ACCOUNT SET ENABLE_CORTEX_CODE_INLINE = {cortex_enabled};
{f'ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = {cortex_daily_limit};' if cortex_daily_limit > 0 else '-- CORTEX_CODE_DAILY_CREDIT_LIMIT: no limit set'}
ALTER ACCOUNT SET ENABLE_CORTEX_SEARCH = {search_enabled};
ALTER ACCOUNT SET ENABLE_SNOWFLAKE_INTELLIGENCE = {analyst_enabled};"""

            st.code(generated_sql, language="sql")

            col_apply, col_dl = st.columns([1, 2])
            with col_apply:
                if st.button("✅ Apply Parameters", type="primary", key="cortex_apply"):
                    # CALLER MODE GUARD: ALTER ACCOUNT SET requires ACCOUNTADMIN.
                    # Since execute_as=CALLER, the caller's role must have this privilege.
                    # SNOW_SYSADMIN cannot run ALTER ACCOUNT — only ACCOUNTADMIN can.
                    try:
                        _caller_role = session.sql("SELECT CURRENT_ROLE()").collect()[0][0] or ""
                    except Exception:
                        _caller_role = ""
                    if "ACCOUNTADMIN" not in _caller_role.upper():
                        st.error(
                            f"⛔ **ALTER ACCOUNT requires ACCOUNTADMIN.** "
                            f"Your current role is `{_caller_role}`. "
                            f"Switch to ACCOUNTADMIN in Snowflake and reload OVERWATCH, "
                            f"or copy the generated SQL below and run it in a Worksheet."
                        )
                    else:
                        applied = []
                        failed  = []
                        for stmt in [
                            f"ALTER ACCOUNT SET ENABLE_CORTEX_CODE_INLINE = {cortex_enabled}",
                            f"ALTER ACCOUNT SET ENABLE_CORTEX_SEARCH = {search_enabled}",
                            f"ALTER ACCOUNT SET ENABLE_SNOWFLAKE_INTELLIGENCE = {analyst_enabled}",
                        ] + ([f"ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = {cortex_daily_limit}"] if cortex_daily_limit > 0 else []):
                            try:
                                session.sql(stmt).collect()
                                applied.append(stmt)
                            except Exception as e:
                                failed.append(f"{stmt} → {e}")

                        if applied:
                            st.success(f"✅ {len(applied)} parameter(s) updated successfully.")
                        if failed:
                            for f_msg in failed:
                                st.warning(f"⚠️ {f_msg}")
                            st.info("Some parameters may not exist in your Snowflake edition or region. Check with SHOW PARAMETERS IN ACCOUNT first.")
            with col_dl:
                st.download_button(
                    "📥 Download SQL",
                    generated_sql,
                    file_name="cortex_parameter_changes.sql",
                    mime="text/plain",
                    key="cortex_dl_sql",
                )

        # ── Per-user Cortex policy (Enterprise) ───────────────────────────────
        st.divider()
        st.subheader("Per-User / Per-Role Cortex Access (Network Policies / Object Tags)")
        st.caption(
            "Snowflake does not yet support per-user Cortex credit limits natively (as of 2025). "
            "The recommended pattern is to use OBJECT_TAGS or role-based feature flags in `config.py` "
            "to control Cortex exposure per team. "
            "Track per-user spend in OVERWATCH → AI & Cortex Monitor → Cortex Code Users."
        )
        st.info(
            "💡 **Tip:** To restrict Cortex to specific roles, use `GRANT SNOWFLAKE.CORTEX.USER` "
            "or revoke the `SNOWFLAKE` database usage from roles that shouldn't have access. "
            "See Snowflake docs: `GRANT USAGE ON DATABASE SNOWFLAKE TO ROLE <role>`."
        )
        with st.expander("📋 Cortex access control SQL snippets"):
            st.code("""
-- Grant Cortex access to a specific role
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE <your_role>;

-- Revoke Cortex access from a role
REVOKE DATABASE ROLE SNOWFLAKE.CORTEX_USER FROM ROLE <restricted_role>;

-- Check who has Cortex access
SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.CORTEX_USER;

-- Check current Cortex-related parameters
SHOW PARAMETERS LIKE '%CORTEX%' IN ACCOUNT;
SHOW PARAMETERS LIKE '%AI%'     IN ACCOUNT;
""", language="sql")

    # ── TAB 15: TASK GRAPH CONTROL ────────────────────────────────────────────
    with tabs[14]:
        st.header("🔀 Task Graph Control")
        st.caption(
            "Cancel running queries spawned by tasks, cancel task graphs mid-run, "
            "suspend/resume individual tasks or entire DAG trees, and restart failed tasks. "
            "Requires OPERATE privilege on tasks or ACCOUNTADMIN."
        )

        tg_tab_run, tg_tab_cancel, tg_tab_manage, tg_tab_graph = st.tabs([
            "Running Task Queries",
            "Cancel Graph / Task",
            "Suspend / Resume",
            "DAG Inspector",
        ])

        # ── Running task queries ───────────────────────────────────────────────
        with tg_tab_run:
            st.subheader("Queries Currently Running Under a Task")
            st.caption(
                "Shows INFORMATION_SCHEMA active queries where QUERY_TAG or SESSION context "
                "indicates task execution. You can cancel individual task-spawned queries here."
            )
            if st.button("Load Running Task Queries", key="tg_run_load"):
                try:
                    # IS gives live data; task queries have query_tag or client context
                    df_tq = normalize_df(session.sql(f"""
                        SELECT query_id, user_name, warehouse_name, warehouse_size, execution_status,
                               start_time,
                               DATEDIFF('second', start_time, CURRENT_TIMESTAMP()) AS elapsed_sec,
                               query_tag,
                               SUBSTR(query_text, 1, 400) AS query_text
                        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
                            END_TIME_RANGE_START=>DATEADD('hours',-2,CURRENT_TIMESTAMP()),
                            RESULT_LIMIT=>500))
                        WHERE execution_status IN ('RUNNING','QUEUED','BLOCKED')
                          {get_wh_filter_clause("warehouse_name")}
                          AND (
                              query_tag IS NOT NULL
                              OR LOWER(query_text) LIKE '%execute task%'
                          )
                        ORDER BY elapsed_sec DESC
                    """).to_pandas())
                    st.session_state["dba_df_tg_running"] = df_tq
                except Exception as e:
                    # Fallback: all running queries
                    try:
                        df_tq = normalize_df(session.sql(f"""
                            SELECT query_id, user_name, warehouse_name, warehouse_size, execution_status,
                                   start_time,
                                   DATEDIFF('second', start_time, CURRENT_TIMESTAMP()) AS elapsed_sec,
                                   query_tag,
                                   SUBSTR(query_text, 1, 400) AS query_text
                            FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
                                END_TIME_RANGE_START=>DATEADD('hours',-1,CURRENT_TIMESTAMP()),
                                RESULT_LIMIT=>200))
                            WHERE execution_status IN ('RUNNING','QUEUED','BLOCKED')
                              {get_wh_filter_clause("warehouse_name")}
                            ORDER BY elapsed_sec DESC
                        """).to_pandas())
                        st.session_state["dba_df_tg_running"] = df_tq
                        st.caption(f"Showing all running queries (task filter unavailable in this context: {e})")
                    except Exception as e2:
                        st.warning(f"INFORMATION_SCHEMA unavailable: {e2}")
                        st.session_state["dba_df_tg_running"] = pd.DataFrame()

            if st.session_state.get("dba_df_tg_running") is not None:
                df_tq = st.session_state["dba_df_tg_running"]
                if not df_tq.empty:
                    st.dataframe(df_tq, use_container_width=True)
                    cancel_qid = st.selectbox(
                        "Cancel query",
                        df_tq["QUERY_ID"].tolist(),
                        key="tg_cancel_qid_sel",
                    )
                    if cancel_qid and st.button("⛔ Cancel This Query", type="primary", key="tg_cancel_q"):
                        try:
                            session.sql(f"SELECT SYSTEM$CANCEL_QUERY('{safe_sql(cancel_qid)}')").collect()
                            st.success(f"✅ Cancel sent for `{cancel_qid}`")
                        except Exception as e:
                            st.error(f"Cancel failed: {e}")
                else:
                    st.success("No task-related queries currently running.")

        # ── Cancel graph / task ────────────────────────────────────────────────
        with tg_tab_cancel:
            st.subheader("Cancel a Running Task Graph or Individual Task Run")
            st.caption(
                "`SYSTEM$CANCEL_TASK_GRAPH(graph_run_id)` — cancels an entire DAG run in progress. "
                "`SYSTEM$CANCEL_QUERY(query_id)` — cancels the query spawned by a specific task run."
            )

            # Load recent task runs to get graph_run_id
            if st.button("Load Recent Task Runs", key="tg_runs_load"):
                try:
                    df_runs = normalize_df(session.sql("""
                        SELECT NAME, DATABASE_NAME, SCHEMA_NAME,
                               GRAPH_RUN_GROUP_ID,
                               SCHEDULED_TIME, QUERY_START_TIME, COMPLETED_TIME,
                               STATE, ERROR_CODE, ERROR_MESSAGE,
                               QUERY_ID,
                               DATEDIFF('second',
                                   COALESCE(QUERY_START_TIME, SCHEDULED_TIME),
                                   COALESCE(COMPLETED_TIME, CURRENT_TIMESTAMP())
                               ) AS duration_sec
                        FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
                        WHERE SCHEDULED_TIME >= DATEADD('hours', -6, CURRENT_TIMESTAMP())
                        ORDER BY SCHEDULED_TIME DESC
                        LIMIT 200
                    """).to_pandas())
                    st.session_state["dba_df_task_runs"] = df_runs
                except Exception as e:
                    st.error(f"Error loading task runs: {e}")

            if st.session_state.get("dba_df_task_runs") is not None and not st.session_state["dba_df_task_runs"].empty:
                df_r = st.session_state["dba_df_task_runs"]

                # Filter to running only
                running_runs = df_r[df_r["STATE"].isin(["EXECUTING","RUNNING","SCHEDULED"])] if "STATE" in df_r.columns else pd.DataFrame()

                if not running_runs.empty:
                    st.warning(f"⚠️ {len(running_runs)} task run(s) currently executing or scheduled.")
                    st.dataframe(running_runs, use_container_width=True)

                    # Cancel by graph run group
                    st.markdown("**Cancel by Graph Run Group ID** (cancels all tasks in that DAG run)")
                    if "GRAPH_RUN_GROUP_ID" in running_runs.columns:
                        graph_ids = running_runs["GRAPH_RUN_GROUP_ID"].dropna().unique().tolist()
                        if graph_ids:
                            sel_graph = st.selectbox(
                                "Select Graph Run Group ID to cancel",
                                graph_ids,
                                key="tg_cancel_graph_sel",
                            )
                            col_cg1, col_cg2 = st.columns([1,3])
                            with col_cg1:
                                if st.button("⛔ Cancel Graph Run", type="primary", key="tg_cancel_graph"):
                                    try:
                                        session.sql(
                                            f"SELECT SYSTEM$CANCEL_TASK_GRAPH('{safe_sql(str(sel_graph))}')"
                                        ).collect()
                                        st.success(f"✅ Graph run `{sel_graph}` cancelled.")
                                        st.session_state.pop("dba_df_task_runs", None)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Cancel graph failed: {e}")
                                        st.info(
                                            "SYSTEM$CANCEL_TASK_GRAPH requires the task to be running and the caller to have "
                                            "OPERATE privilege on the root task, or ACCOUNTADMIN."
                                        )

                    # Cancel individual query from a task run
                    st.markdown("**Cancel individual task run query**")
                    if "QUERY_ID" in running_runs.columns:
                        query_ids = running_runs["QUERY_ID"].dropna().unique().tolist()
                        if query_ids:
                            sel_qid = st.selectbox("Select Query ID", query_ids, key="tg_cancel_run_qid")
                            if sel_qid and st.button("⛔ Cancel Query", key="tg_cancel_run_q"):
                                try:
                                    session.sql(f"SELECT SYSTEM$CANCEL_QUERY('{safe_sql(str(sel_qid))}')").collect()
                                    st.success(f"✅ Cancel sent for `{sel_qid}`")
                                except Exception as e:
                                    st.error(f"Cancel failed: {e}")
                else:
                    st.success("No task runs currently executing.")
                    st.subheader("Recent History (last 6h)")
                    st.dataframe(df_r.head(50), use_container_width=True)

        # ── Suspend / Resume ──────────────────────────────────────────────────
        with tg_tab_manage:
            st.subheader("Suspend / Resume Tasks and DAG Trees")
            st.caption(
                "Suspend or resume individual tasks or entire DAG hierarchies. "
                "Suspending a root task stops the whole graph from scheduling. "
                "Suspending a child task pauses that branch only."
            )

            # Load task list for selection
            if st.button("Load Task List", key="tg_mgmt_load"):
                try:
                    df_tasks = normalize_df(session.sql("""
                        SELECT name, database_name, schema_name, state,
                               schedule, warehouse,
                               COALESCE(predecessors, '') AS predecessors,
                               definition
                        FROM SNOWFLAKE.ACCOUNT_USAGE.TASKS
                        ORDER BY database_name, schema_name, name
                    """).to_pandas())
                    st.session_state["dba_df_tg_tasks"] = df_tasks
                except Exception as e:
                    st.error(f"Error loading tasks: {e}")

            df_tasks = st.session_state.get("dba_df_tg_tasks", pd.DataFrame())
            if not df_tasks.empty:
                # Metrics
                started   = df_tasks[df_tasks["STATE"] == "started"]  if "STATE" in df_tasks.columns else pd.DataFrame()
                suspended = df_tasks[df_tasks["STATE"] == "suspended"] if "STATE" in df_tasks.columns else pd.DataFrame()
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Tasks",       len(df_tasks))
                c2.metric("▶ Active",           len(started))
                c3.metric("⏸ Suspended",        len(suspended))

                st.dataframe(df_tasks[["NAME","DATABASE_NAME","SCHEMA_NAME","STATE","SCHEDULE","WAREHOUSE"] if all(c in df_tasks.columns for c in ["NAME","DATABASE_NAME","SCHEMA_NAME","STATE","SCHEDULE","WAREHOUSE"]) else df_tasks.columns.tolist()],
                             use_container_width=True, height=250)

                st.divider()

                # Single task control
                st.subheader("Control Individual Task")
                task_names = df_tasks["NAME"].unique().tolist() if "NAME" in df_tasks.columns else []
                sel_task   = st.selectbox("Select task", task_names, key="tg_mgmt_sel")

                if sel_task:
                    task_row = df_tasks[df_tasks["NAME"] == sel_task].iloc[0]
                    db_n   = task_row.get("DATABASE_NAME","")
                    sch_n  = task_row.get("SCHEMA_NAME","")
                    state  = task_row.get("STATE","")
                    full_n = f"{db_n}.{sch_n}.{sel_task}"
                    preds  = task_row.get("PREDECESSORS","")

                    st.info(f"`{full_n}` · State: **{state}** · Predecessors: `{preds or 'none (root task)'}`")

                    col_s1, col_s2, col_s3, col_s4 = st.columns(4)

                    with col_s1:
                        if st.button("⏸ Suspend", key="tg_suspend", disabled=(state=="suspended")):
                            try:
                                session.sql(f"ALTER TASK {full_n} SUSPEND").collect()
                                st.success(f"✅ `{sel_task}` suspended.")
                                st.session_state.pop("dba_df_tg_tasks", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Suspend failed: {e}")

                    with col_s2:
                        if st.button("▶ Resume", key="tg_resume", disabled=(state=="started")):
                            try:
                                session.sql(f"ALTER TASK {full_n} RESUME").collect()
                                st.success(f"✅ `{sel_task}` resumed.")
                                st.session_state.pop("dba_df_tg_tasks", None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Resume failed: {e}")

                    with col_s3:
                        if st.button("▶▶ Execute Now", key="tg_execute"):
                            try:
                                session.sql(f"EXECUTE TASK {full_n}").collect()
                                st.success(f"✅ `{sel_task}` triggered.")
                            except Exception as e:
                                st.error(f"Execute failed: {e}")

                    with col_s4:
                        if st.button("🔁 Retry Last Failed", key="tg_retry"):
                            # EXECUTE TASK WITH LAST_ERROR retry pattern
                            try:
                                session.sql(f"EXECUTE TASK {full_n}").collect()
                                st.success(f"✅ Retry triggered for `{sel_task}`.")
                                st.caption(
                                    "Note: Snowflake does not have a native RETRY_LAST_FAILED command. "
                                    "This re-executes the task immediately. "
                                    "For DAG-level retry, use EXECUTE TASK on the root task."
                                )
                            except Exception as e:
                                st.error(f"Retry failed: {e}")

                st.divider()

                # Bulk suspend/resume entire DAG tree
                st.subheader("Bulk Suspend / Resume Entire DAG Tree")
                st.caption(
                    "Suspending the root task stops the entire graph from scheduling. "
                    "Select a root task (one with no predecessors) below."
                )
                root_tasks = df_tasks[
                    df_tasks.get("PREDECESSORS", pd.Series()).astype(str).str.strip().isin(["","[]","None","nan"])
                ] if "PREDECESSORS" in df_tasks.columns else df_tasks

                if not root_tasks.empty:
                    root_names = root_tasks["NAME"].unique().tolist() if "NAME" in root_tasks.columns else []
                    sel_root   = st.selectbox("Select root task (suspends entire graph)", root_names, key="tg_root_sel")

                    if sel_root:
                        root_row  = df_tasks[df_tasks["NAME"] == sel_root].iloc[0]
                        root_full = f"{root_row.get('DATABASE_NAME','')}.{root_row.get('SCHEMA_NAME','')}.{sel_root}"

                        # Find all children
                        children = df_tasks[
                            df_tasks.get("PREDECESSORS","").astype(str).str.contains(sel_root, na=False)
                        ] if "PREDECESSORS" in df_tasks.columns else pd.DataFrame()

                        st.info(
                            f"Root: `{root_full}` · "
                            f"Child tasks in this graph: {len(children)} · "
                            f"Total tasks affected: {len(children)+1}"
                        )

                        b1, b2 = st.columns(2)
                        with b1:
                            if st.button("⏸ Suspend Entire Graph", type="primary", key="tg_bulk_suspend"):
                                try:
                                    session.sql(f"ALTER TASK {root_full} SUSPEND").collect()
                                    st.success(f"✅ Root task `{sel_root}` suspended — entire graph will stop scheduling.")
                                    st.session_state.pop("dba_df_tg_tasks", None)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Suspend failed: {e}")
                        with b2:
                            if st.button("▶ Resume Entire Graph", type="primary", key="tg_bulk_resume"):
                                errors_seen = []
                                # Resume children first, then root
                                for _, child in children.iterrows():
                                    full_child = f"{child.get('DATABASE_NAME','')}.{child.get('SCHEMA_NAME','')}.{child.get('NAME','')}"
                                    try:
                                        session.sql(f"ALTER TASK {full_child} RESUME").collect()
                                    except Exception as e:
                                        errors_seen.append(f"{full_child}: {e}")
                                try:
                                    session.sql(f"ALTER TASK {root_full} RESUME").collect()
                                except Exception as e:
                                    errors_seen.append(f"{root_full}: {e}")

                                if errors_seen:
                                    st.warning(f"Resumed with {len(errors_seen)} error(s):")
                                    for err in errors_seen:
                                        st.caption(err)
                                else:
                                    st.success(f"✅ Entire graph resumed. {len(children)+1} task(s) active.")
                                st.session_state.pop("dba_df_tg_tasks", None)
                                st.rerun()

        # ── DAG Inspector ─────────────────────────────────────────────────────
        with tg_tab_graph:
            st.subheader("DAG Inspector")
            st.caption(
                "Visualise the task dependency tree for a selected root task. "
                "Shows each node's current state, last run result, and duration."
            )

            df_tasks = st.session_state.get("dba_df_tg_tasks", pd.DataFrame())
            if df_tasks.empty:
                st.info("Load the task list in the Suspend/Resume tab first.")
            else:
                root_tasks = df_tasks[
                    df_tasks.get("PREDECESSORS", pd.Series()).astype(str).str.strip().isin(["","[]","None","nan"])
                ] if "PREDECESSORS" in df_tasks.columns else df_tasks
                root_names = root_tasks["NAME"].unique().tolist() if not root_tasks.empty else df_tasks["NAME"].unique().tolist()
                sel_dag = st.selectbox("Select root task to inspect", root_names, key="tg_dag_sel")

                if sel_dag and st.button("Build DAG View", key="tg_dag_build"):
                    # Get full task graph via TASK_GRAPH_HISTORY or reconstruct from predecessors
                    try:
                        df_dag = normalize_df(session.sql(f"""
                            SELECT t.NAME, t.DATABASE_NAME, t.SCHEMA_NAME, t.STATE,
                                   t.PREDECESSORS,
                                   th.STATE      AS last_run_state,
                                   th.ERROR_MESSAGE AS last_error,
                                   DATEDIFF('second',
                                       COALESCE(th.QUERY_START_TIME, th.SCHEDULED_TIME),
                                       COALESCE(th.COMPLETED_TIME, CURRENT_TIMESTAMP())
                                   ) AS last_duration_sec,
                                   th.SCHEDULED_TIME AS last_run_time
                            FROM SNOWFLAKE.ACCOUNT_USAGE.TASKS t
                            LEFT JOIN LATERAL (
                                SELECT STATE, ERROR_MESSAGE, QUERY_START_TIME,
                                       COMPLETED_TIME, SCHEDULED_TIME
                                FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY th2
                                WHERE th2.NAME = t.NAME
                                ORDER BY th2.SCHEDULED_TIME DESC
                                LIMIT 1
                            ) th ON TRUE
                            WHERE t.DELETED IS NULL
                              AND (t.NAME = '{safe_sql(sel_dag)}'
                                   OR t.PREDECESSORS LIKE '%{safe_sql(sel_dag)}%')
                            ORDER BY t.PREDECESSORS NULLS FIRST, t.NAME
                        """).to_pandas())
                        st.session_state["dba_df_dag_view"] = df_dag
                    except Exception as e:
                        st.error(f"DAG build failed: {e}")

                if st.session_state.get("dba_df_dag_view") is not None and not st.session_state["dba_df_dag_view"].empty:
                    df_dag = st.session_state["dba_df_dag_view"]

                    # Visual tree using indented text
                    st.markdown("**Task Dependency Tree**")
                    for _, row in df_dag.iterrows():
                        name   = row.get("NAME","")
                        preds  = str(row.get("PREDECESSORS","") or "")
                        state  = str(row.get("STATE","")).lower()
                        lr_st  = str(row.get("LAST_RUN_STATE","") or "")
                        dur    = row.get("LAST_DURATION_SEC", 0) or 0
                        err    = str(row.get("LAST_ERROR","") or "")[:80]

                        is_root = preds.strip() in ("","[]","None","nan","")
                        indent  = "" if is_root else "↳ "

                        state_icon = "▶️" if state=="started" else "⏸" if state=="suspended" else "⚪"
                        lr_icon    = "✅" if lr_st=="SUCCEEDED" else ("❌" if lr_st=="FAILED" else "⏳")

                        st.markdown(
                            f"{'&nbsp;'*4 if indent else ''}{indent}"
                            f"{state_icon} **{name}** &nbsp; {lr_icon} last: {lr_st} "
                            f"({int(dur)}s)"
                            f"{' — ' + err if err and err != 'nan' else ''}",
                            unsafe_allow_html=True,
                        )

                    st.dataframe(df_dag, use_container_width=True)
                    download_csv(df_dag, f"dag_{sel_dag}.csv")

    # ── TAB 16: USAGE LOG (carried forward) ───────────────────────────────────
    with tabs[15]:
        st.header("📊 OVERWATCH Usage Log")
        st.caption("Tracks which sections are loaded, by whom, how often, and how fast.")
        from utils.logging import build_usage_log_ddl, set_logging_enabled, is_logging_enabled
        from utils import build_overwatch_setup_bundle
        from config import ALERT_DB, ALERT_SCHEMA
        log_tbl = f"{ALERT_DB}.{ALERT_SCHEMA}.OVERWATCH_USAGE_LOG"

        with st.expander("Full OVERWATCH persistent setup bundle"):
            setup_sql = build_overwatch_setup_bundle()
            preview = setup_sql[:5000]
            if len(setup_sql) > 5000:
                preview += "\n\n-- truncated in preview; download for full script"
            st.code(preview, language="sql")
            st.download_button(
                "Download Full Setup Bundle",
                setup_sql,
                file_name="overwatch_full_setup.sql",
                mime="text/plain",
                key="overwatch_full_setup_download",
            )

        with st.expander("📋 Setup DDL"):
            st.code(build_usage_log_ddl(), language="sql")

        logging_on = st.toggle("Enable logging", value=is_logging_enabled(), key="ul_toggle")
        set_logging_enabled(logging_on)

        ul_days  = st.slider("Report window (days)", 1, 90, 30, key="ul_days")
        ul_group = st.selectbox("Group by", ["Section","User","Role","Company","Day"], key="ul_group")
        if st.button("Load Usage Data", key="ul_load"):
            try:
                dim_map = {
                    "Section":"section","User":"sf_user","Role":"sf_role",
                    "Company":"company_view","Day":"DATE_TRUNC(\\'day\\', log_time)",
                }
                dim = dim_map[ul_group]
                lbl = "DAY" if ul_group=="Day" else ul_group.upper()
                df_ul = normalize_df(session.sql(f"""
                    SELECT {dim} AS {lbl}, COUNT(*) AS load_count,
                           COUNT(DISTINCT sf_user) AS distinct_users,
                           ROUND(AVG(query_duration_ms)) AS avg_ms
                    FROM {log_tbl}
                    WHERE log_time >= DATEADD('day', -{ul_days}, CURRENT_TIMESTAMP())
                    GROUP BY {dim} ORDER BY load_count DESC LIMIT 200
                """).to_pandas())
                st.session_state["dba_df_usage_log"] = df_ul
                st.session_state["dba_ul_group_label"] = lbl
            except Exception as e:
                st.info(f"Usage log unavailable: {e}")
        if st.session_state.get("dba_df_usage_log") is not None and not st.session_state["dba_df_usage_log"].empty:
            df_ul = st.session_state["dba_df_usage_log"]
            lbl   = st.session_state.get("dba_ul_group_label","SECTION")
            st.metric("Total Loads", f"{int(df_ul['LOAD_COUNT'].sum()):,}")
            st.bar_chart(df_ul.set_index(lbl)["LOAD_COUNT"])
            st.dataframe(df_ul, use_container_width=True)
            download_csv(df_ul, f"usage_log_{ul_group.lower()}.csv")

    # Setup bundle and install readiness
    with tabs[16]:
        st.header("🔧 First-Time Setup")
        st.caption(
            "Check the persistent OVERWATCH objects used by saved views, annotations, "
            "action queue, alert history, usage logging, and value tracking."
        )

        c1, c2 = st.columns([1, 2])
        with c1:
            if st.button("Check Setup Status", key="setup_status_load"):
                st.session_state["dba_setup_status"] = _setup_status_df(session)
        with c2:
            st.info(
                "Run the setup SQL with a role that can create tables and tasks in "
                f"{ALERT_DB}.{ALERT_SCHEMA}. Review the alert task warehouse and schedule "
                "before enabling it."
            )

        if st.session_state.get("dba_setup_status") is not None:
            status_df = st.session_state["dba_setup_status"]
            missing_count = int((status_df["STATUS"] == "Missing").sum())
            unknown_count = int((status_df["STATUS"] == "Unknown").sum())

            m1, m2, m3 = st.columns(3)
            m1.metric("Objects Checked", f"{len(status_df):,}")
            m2.metric("Missing", f"{missing_count:,}")
            m3.metric("Unknown", f"{unknown_count:,}")
            st.dataframe(status_df, use_container_width=True, hide_index=True)

        setup_sql = build_overwatch_setup_bundle()
        st.download_button(
            "Download Full Setup SQL",
            setup_sql,
            file_name="overwatch_first_time_setup.sql",
            mime="text/plain",
            key="first_time_setup_download",
        )

        with st.expander("Preview full setup SQL"):
            preview = setup_sql[:8000]
            if len(setup_sql) > 8000:
                preview += "\n\n-- Preview truncated. Download the full setup SQL above."
            st.code(preview, language="sql")

        st.subheader("Individual setup scripts")
        setup_parts = {
            "Saved Views": build_bookmark_ddl(),
            "Annotation Windows": build_annotation_ddl(),
            "Action Queue": build_action_queue_ddl(),
            "Snowflake Value Log": build_snowflake_value_ddl(),
            "Usage Log": build_usage_log_ddl(),
            "Alert History + Optional Task": build_alert_task_sql(),
        }
        selected_part = st.selectbox(
            "Script",
            list(setup_parts.keys()),
            key="first_time_setup_part",
        )
        st.code(setup_parts[selected_part], language="sql")
