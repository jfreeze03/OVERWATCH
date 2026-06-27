# sections/live_monitor.py - Real-time query history, timeline, sessions
# -----------------------------------------------------------------------------
# FIXES vs previous version:
#   1. time.sleep() blocking REMOVED - replaced with @st.fragment(run_every=N)
#      The entire active queries panel is now a fragment that refreshes
#      independently without blocking the app thread or forcing a full rerun.
#      Users on other tabs (Timeline, Sessions) are unaffected.
#   2. Bare session.sql() on line 76 (ACCOUNT_USAGE fallback) already had
#      an inner try/except - confirmed clean in this version.
#   3. Lock Wait History added to Sessions tab.
# -----------------------------------------------------------------------------
import streamlit as st
import pandas as pd
from datetime import datetime
from sections.chart_helpers import render_time_series_chart
from sections.shell_helpers import render_shell_snapshot
from utils import (
    get_session,
    credits_to_dollars, estimate_live_credits, download_csv,
    render_query_drilldown, get_active_company, get_user_company_filter_clause,
    get_global_filter_clause, get_wh_filter_clause, run_query, run_query_or_raise, sql_literal,
    safe_identifier, format_snowflake_error, filter_existing_columns,
    admin_button_disabled, log_admin_action, require_admin_enabled,
    load_warehouse_options,
    render_chart_with_data_toggle,
    queries_paused, query_pause_message,
)
from utils.workflows import render_priority_dataframe, render_workflow_selector
from config import DEFAULTS, THRESHOLDS


LIVE_MONITOR_PANES = (
    "Active Queries",
    "Timeline",
    "Sessions",
)

QUERY_HISTORY_OPTIONAL_COLUMNS = (
    "WAREHOUSE_SIZE",
    "BYTES_SCANNED",
    "ROWS_PRODUCED",
    "CREDITS_USED_CLOUD_SERVICES",
)


def _query_context_expr() -> str:
    return """
        CASE
            WHEN database_name IS NULL OR TRIM(database_name) = '' THEN 'NO DATABASE CONTEXT'
            WHEN schema_name IS NULL OR TRIM(schema_name) = '' THEN database_name
            ELSE database_name || '.' || schema_name
        END AS query_context
    """


def _prioritize_query_context(df: pd.DataFrame) -> pd.DataFrame:
    """Keep query database/schema context visible near the row identity."""
    if df is None or df.empty:
        return df
    frame = df.copy()
    if "QUERY_CONTEXT" not in frame.columns and "DATABASE_NAME" in frame.columns:
        db = frame["DATABASE_NAME"].fillna("").astype(str).str.strip()
        schema = (
            frame["SCHEMA_NAME"].fillna("").astype(str).str.strip()
            if "SCHEMA_NAME" in frame.columns else pd.Series([""] * len(frame), index=frame.index)
        )
        frame["QUERY_CONTEXT"] = db.where(db != "", "NO DATABASE CONTEXT")
        both = (db != "") & (schema != "")
        frame.loc[both, "QUERY_CONTEXT"] = db[both] + "." + schema[both]
    first_cols = [
        "QUERY_ID", "QUERY_CONTEXT", "DATABASE_NAME", "SCHEMA_NAME",
        "EXECUTION_STATUS", "USER_NAME", "WAREHOUSE_NAME", "WAREHOUSE_SIZE",
    ]
    ordered = [col for col in first_cols if col in frame.columns]
    ordered.extend([col for col in frame.columns if col not in ordered])
    return frame[ordered]


def _live_query_history_function(warehouse_filter: str = "") -> str:
    """Return the most selective INFORMATION_SCHEMA query history function."""
    warehouse = str(warehouse_filter or "").strip()
    if warehouse:
        try:
            safe_identifier(warehouse)
            return (
                "INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE("
                f"WAREHOUSE_NAME=>{sql_literal(warehouse.upper())}, "
                "END_TIME_RANGE_START=>DATEADD('hours',-1,CURRENT_TIMESTAMP()), "
                "RESULT_LIMIT=>100)"
            )
        except ValueError:
            pass
    return (
        "INFORMATION_SCHEMA.QUERY_HISTORY("
        "END_TIME_RANGE_START=>DATEADD('hours',-1,CURRENT_TIMESTAMP()), "
        "RESULT_LIMIT=>100)"
    )


def render():
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])
    rt_interval  = st.session_state.get("rt_interval", 30)
    company      = get_active_company()

    active_view = render_workflow_selector(
        "Live monitor view",
        "live_monitor_active_view",
        LIVE_MONITOR_PANES,
        columns=3,
        show_label=True,
    )

    # -- ACTIVE QUERIES --------------------------------------------------------
    if active_view == "Active Queries":
        st.subheader("Live & Recent Queries")
        st.caption(
            "Uses `ACCOUNT_USAGE.QUERY_HISTORY` by default for Streamlit-in-Snowflake compatibility. "
            "Zero-latency metadata can be tried when the active role/context allows it."
        )

        c1, c2, c3, c4, c5 = st.columns([1, 1, 1.4, 2, 2])
        with c1:
            refresh_live = st.button("Load / Refresh", key="lm_refresh")
        with c2:
            auto_refresh = st.checkbox(
                "Auto-refresh", key="lm_auto",
                help=f"Refreshes every {rt_interval}s via st.fragment - non-blocking."
            )
        if queries_paused():
            st.session_state["lm_auto"] = False
            auto_refresh = False
            refresh_live = False
            st.info(query_pause_message())
        with c3:
            try_info_schema = st.checkbox(
                "Try live metadata",
                key="lm_try_info_schema",
                help="Off by default because Snowflake can block INFORMATION_SCHEMA table functions in hosted Streamlit.",
            )
        with c4:
            if "lm_warehouse_options" not in st.session_state:
                try:
                    st.session_state["lm_warehouse_options"] = load_warehouse_options(
                        get_session(),
                        company=company,
                    )
                except Exception:
                    st.session_state["lm_warehouse_options"] = []
            warehouse_options = list(st.session_state.get("lm_warehouse_options") or [])
            if warehouse_options:
                warehouse_choices = ["All scoped warehouses"] + warehouse_options
                if st.session_state.get("lm_wh_select") not in warehouse_choices:
                    st.session_state["lm_wh_select"] = "All scoped warehouses"
                selected_warehouse = st.selectbox(
                    "Warehouse",
                    warehouse_choices,
                    key="lm_wh_select",
                )
                wh_filter = "" if selected_warehouse == "All scoped warehouses" else selected_warehouse
            else:
                wh_filter = st.text_input("Warehouse contains", key="lm_wh")
        with c5:
            status_filter = st.selectbox(
                "Status",
                ["ALL", "RUNNING", "QUEUED", "BLOCKED", "SUCCESS", "FAILED_WITH_ERROR"],
                key="lm_status",
            )

        # -- @st.fragment refreshes this panel independently on a timer.
        # run_every=N means Streamlit re-executes just this function every N
        # seconds without triggering a full app rerun. No time.sleep() needed.
        # When auto_refresh is unchecked, run_every=None means the fragment renders
        # once and waits for a manual interaction.
        _run_every = rt_interval if auto_refresh else None
        query_history_optional = set()
        if refresh_live or auto_refresh:
            try:
                query_history_optional = set(filter_existing_columns(
                    get_session(),
                    "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                    QUERY_HISTORY_OPTIONAL_COLUMNS,
                ))
            except Exception as exc:
                st.caption(f"Query-history optional columns unavailable: {format_snowflake_error(exc)}")
        fallback_wh_size_expr = (
            "warehouse_size"
            if "WAREHOUSE_SIZE" in query_history_optional
            else "NULL::VARCHAR AS warehouse_size"
        )
        fallback_mb_scanned_expr = (
            "bytes_scanned/POWER(1024,2) AS mb_scanned"
            if "BYTES_SCANNED" in query_history_optional
            else "0::FLOAT AS mb_scanned"
        )
        fallback_rows_expr = (
            "rows_produced"
            if "ROWS_PRODUCED" in query_history_optional
            else "0::NUMBER AS rows_produced"
        )
        warehouse_size_expr = (
            "warehouse_size"
            if "WAREHOUSE_SIZE" in query_history_optional
            else "NULL::VARCHAR AS warehouse_size"
        )
        bytes_scanned_expr = (
            "bytes_scanned/POWER(1024,3) AS gb_scanned"
            if "BYTES_SCANNED" in query_history_optional
            else "NULL::FLOAT AS gb_scanned"
        )
        rows_produced_expr = (
            "rows_produced"
            if "ROWS_PRODUCED" in query_history_optional
            else "NULL::NUMBER AS rows_produced"
        )
        cloud_credits_expr = (
            "credits_used_cloud_services AS cloud_credits"
            if "CREDITS_USED_CLOUD_SERVICES" in query_history_optional
            else "NULL::FLOAT AS cloud_credits"
        )

        @st.fragment(run_every=_run_every)
        def _live_panel():
            if queries_paused():
                st.session_state["lm_auto"] = False
                st.info(query_pause_message())
                return
            wh_filter_clean = (wh_filter or "").strip()
            wh_clause = f"AND warehouse_name ILIKE {sql_literal('%' + wh_filter_clean + '%')}" if wh_filter_clean else ""
            company_wh_clause = get_wh_filter_clause("warehouse_name")
            st_clause = f"AND execution_status = {sql_literal(status_filter, 40)}" if status_filter != "ALL" else ""

            if auto_refresh:
                st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')} - auto-refresh {rt_interval}s")

            # -- Live - INFORMATION_SCHEMA (0-latency) ------------------------
            st.subheader("Currently Running")
            live_history_fn = _live_query_history_function(wh_filter_clean)
            query_context_expr = _query_context_expr()
            live_sql = f"""
            SELECT query_id, SUBSTR(query_text,1,300) AS query_text,
                   database_name, schema_name, {query_context_expr},
                   user_name, warehouse_name, warehouse_size, execution_status, start_time,
                   DATEDIFF('second',start_time,CURRENT_TIMESTAMP()) AS elapsed_sec,
                   bytes_scanned/POWER(1024,2) AS mb_scanned, rows_produced
            FROM TABLE({live_history_fn})
            WHERE UPPER(execution_status) IN ('RUNNING','QUEUED','BLOCKED','RESUMING_WAREHOUSE')
              {wh_clause}
              {company_wh_clause}
            ORDER BY elapsed_sec DESC
            """
            df_live = pd.DataFrame()
            try:
                if not try_info_schema:
                    raise RuntimeError("Using ACCOUNT_USAGE compatibility mode")
                if st.session_state.get("_overwatch_disable_info_schema_qh"):
                    raise RuntimeError("INFORMATION_SCHEMA query history disabled after prior failure")
                df_live = run_query_or_raise(live_sql)
            except Exception as live_err:
                if try_info_schema:
                    st.session_state["_overwatch_disable_info_schema_qh"] = True
                    # IS unavailable (e.g. serverless context) - fall back to AU.
                    st.info("Live metadata unavailable - using ACCOUNT_USAGE fallback.")
                try:
                    df_live = run_query(f"""
                        SELECT query_id, SUBSTR(query_text,1,300) AS query_text,
                               database_name, schema_name, {query_context_expr},
                               user_name, warehouse_name, {fallback_wh_size_expr},
                               execution_status, start_time,
                               total_elapsed_time/1000 AS elapsed_sec,
                               {fallback_mb_scanned_expr}, {fallback_rows_expr}
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('minutes',-10,CURRENT_TIMESTAMP())
                          AND UPPER(execution_status) IN ('RUNNING','QUEUED','BLOCKED','RESUMING_WAREHOUSE')
                          {wh_clause}
                          {company_wh_clause}
                        ORDER BY start_time DESC LIMIT 100
                    """, ttl_key=f"live_active_fallback_{company}_{wh_filter_clean}_{status_filter}", tier="live")
                except Exception as fallback_err:
                    st.warning(f"Live query data unavailable: {format_snowflake_error(fallback_err)}")

            if not df_live.empty:
                df_live = _prioritize_query_context(df_live)
                df_live["EST_COMPUTE_CREDITS"] = df_live.apply(estimate_live_credits, axis=1)
                df_live["EST_DOLLARS"]          = df_live["EST_COMPUTE_CREDITS"].apply(credits_to_dollars)
                queued = int((df_live["EXECUTION_STATUS"] == "QUEUED").sum()) \
                         if "EXECUTION_STATUS" in df_live.columns else 0
                render_shell_snapshot((
                    ("Active Queries", f"{len(df_live):,}"),
                    ("Queued", f"{queued:,}"),
                    ("Est. Live Cost", f"${df_live['EST_DOLLARS'].sum():,.4f}"),
                ))
                render_query_drilldown(df_live, key="lm_live")

                # Kill query
                st.divider()
                st.subheader("Kill Query")
                kill_qid = st.text_input("Query ID to cancel", key="lm_kill_id")
                confirm_cancel = st.text_input(
                    "Type CANCEL to confirm",
                    key="lm_kill_confirm",
                    placeholder="CANCEL",
                )
                confirm_cancel = str(st.session_state.get("lm_kill_confirm") or confirm_cancel or "").strip()
                kill_qid = str(st.session_state.get("lm_kill_id") or kill_qid or "").strip()
                if st.button(
                    "Cancel Query",
                    type="primary",
                    key="lm_kill_btn",
                    disabled=admin_button_disabled(),
                ):
                    if not kill_qid:
                        st.warning("Enter a query ID before cancelling.")
                    elif confirm_cancel != "CANCEL":
                        st.warning("Type `CANCEL` exactly before cancelling this query.")
                    else:
                        cancel_sql = f"SELECT SYSTEM$CANCEL_QUERY({sql_literal(kill_qid)})"
                        try:
                            if not require_admin_enabled("query cancellation"):
                                return
                            action_session = get_session()
                            # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
                            action_session.sql(cancel_sql).collect()
                            log_admin_action(
                                action_session,
                                action_type="CANCEL QUERY",
                                target_object=str(kill_qid),
                                sql_text=cancel_sql,
                                confirmation_text=confirm_cancel,
                                control_context=(
                                    "Live Monitor manual cancellation. Operator typed CANCEL and used the "
                                    "admin confirmation flow before sending SYSTEM$CANCEL_QUERY."
                                ),
                                result_status="SUCCESS",
                                result_message=f"Cancel sent for {kill_qid}",
                            )
                            st.success(f"Cancel sent for `{kill_qid}`")
                        except Exception as e:
                            log_admin_action(
                                get_session(),
                                action_type="CANCEL QUERY",
                                target_object=str(kill_qid),
                                sql_text=cancel_sql,
                                confirmation_text=confirm_cancel,
                                control_context="Live Monitor manual cancellation failed after operator confirmation.",
                                result_status="ERROR",
                                result_message=format_snowflake_error(e),
                            )
                            st.error(f"Cancel failed: {format_snowflake_error(e)}")
            else:
                st.success("No active queries right now.")

            # -- Recent - ACCOUNT_USAGE (45 min lag or less) ------------------
            st.divider()
            st.subheader("Recent (last 4h, ACCOUNT_USAGE)")
            try:
                df_recent = run_query(f"""
                    SELECT query_id, database_name, schema_name, {query_context_expr},
                           user_name, warehouse_name, {warehouse_size_expr}, execution_status,
                           start_time, total_elapsed_time/1000 AS elapsed_sec,
                           {bytes_scanned_expr},
                           {rows_produced_expr}, {cloud_credits_expr},
                           SUBSTR(query_text,1,300) AS query_text
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('hours',-4,CURRENT_TIMESTAMP())
                      {wh_clause} {company_wh_clause} {st_clause}
                    ORDER BY start_time DESC LIMIT 500
                """, ttl_key=f"live_recent_{company}_{wh_filter}_{status_filter}", tier="live")
                if not df_recent.empty:
                    df_recent = _prioritize_query_context(df_recent)
                    render_priority_dataframe(
                        df_recent,
                        title="Recent queries to inspect first",
                        priority_columns=[
                            "QUERY_ID",
                            "QUERY_CONTEXT",
                            "DATABASE_NAME",
                            "SCHEMA_NAME",
                            "EXECUTION_STATUS",
                            "USER_NAME",
                            "WAREHOUSE_NAME",
                            "WAREHOUSE_SIZE",
                            "START_TIME",
                            "ELAPSED_SEC",
                            "GB_SCANNED",
                            "QUERY_TEXT",
                        ],
                        sort_by=["ELAPSED_SEC", "GB_SCANNED", "START_TIME"],
                        ascending=[False, False, False],
                        raw_label="All recent query rows",
                        height=350,
                    )
                    download_csv(df_recent, "recent_queries.csv")
            except Exception as e:
                st.caption(f"Recent query data unavailable: {format_snowflake_error(e)}")

        if refresh_live or auto_refresh:
            _live_panel()
        else:
            st.info("Live query polling is paused. Refresh once or enable auto-refresh when you need active query telemetry.")

    # -- TIMELINE --------------------------------------------------------------
    elif active_view == "Timeline":
        st.subheader("Query Timeline")
        tl_hours = st.slider("Lookback (hours)", 1, 24, 6, key="lm_tl_hours")
        if st.button("Load Timeline", key="lm_tl_load"):
            try:
                df_tl = run_query(f"""
                    SELECT DATE_TRUNC('hour', start_time) AS time_bucket,
                           execution_status,
                           COUNT(*)                       AS query_count,
                           AVG(total_elapsed_time)/1000   AS avg_elapsed_sec
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('hours', -{tl_hours}, CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY time_bucket, execution_status
                    ORDER BY time_bucket
                """, ttl_key=f"live_timeline_{company}_{tl_hours}", tier="standard")
                st.session_state["lm_df_tl"] = df_tl
            except Exception as e:
                st.warning(f"Timeline data unavailable in this role/context: {format_snowflake_error(e)}")

        if st.session_state.get("lm_df_tl") is not None and not st.session_state["lm_df_tl"].empty:
            df_t = st.session_state["lm_df_tl"]
            try:
                render_chart_with_data_toggle(
                    "Query timeline by status",
                    "live_query_timeline",
                    lambda: render_time_series_chart(
                        df_t,
                        "TIME_BUCKET",
                        "QUERY_COUNT",
                        series_column="EXECUTION_STATUS",
                        title="Query timeline by status",
                    ),
                    df_t,
                    priority_columns=["TIME_BUCKET", "EXECUTION_STATUS", "QUERY_COUNT", "AVG_ELAPSED_SEC"],
                    sort_by=["TIME_BUCKET", "QUERY_COUNT"],
                    ascending=[False, False],
                    raw_label="All timeline rows",
                )
            except Exception:
                render_priority_dataframe(
                    df_t,
                    title="Timeline fallback detail",
                    priority_columns=["TIME_BUCKET", "EXECUTION_STATUS", "QUERY_COUNT", "AVG_ELAPSED_SEC"],
                    sort_by=["TIME_BUCKET", "QUERY_COUNT"],
                    ascending=[False, False],
                    raw_label="All timeline rows",
                )
            download_csv(df_t, "query_timeline.csv")

    # -- SESSIONS --------------------------------------------------------------
    elif active_view == "Sessions":
        st.subheader("Active Sessions")
        s1, s2 = st.columns(2)

        with s1:
            if st.button("Load Sessions", key="lm_sess_load"):
                try:
                    df_sess = run_query("""
                        SELECT session_id, user_name, created_on,
                               DATEDIFF('minute', created_on, CURRENT_TIMESTAMP()) AS session_min,
                               authentication_method
                        FROM SNOWFLAKE.ACCOUNT_USAGE.SESSIONS
                        WHERE created_on >= DATEADD('day', -1, CURRENT_TIMESTAMP())
                        {user_filter}
                        ORDER BY session_min DESC LIMIT 200
                    """.format(user_filter=get_user_company_filter_clause("user_name", company)), ttl_key=f"live_sessions_{company}", tier="standard")
                    st.session_state["lm_df_sessions"] = df_sess
                except Exception as e:
                    st.warning(f"Sessions view unavailable: {format_snowflake_error(e)}")

        with s2:
            if st.button("Load Lock Waits", key="lm_lock_load"):
                try:
                    lock_cols = set(filter_existing_columns(
                        get_session(),
                        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                        ["WAREHOUSE_SIZE", "TRANSACTION_BLOCKED_TIME"],
                    ))
                    if "TRANSACTION_BLOCKED_TIME" not in lock_cols:
                        st.info("Lock-wait timing is not exposed in QUERY_HISTORY for this role/account.")
                        st.session_state["lm_df_lock"] = pd.DataFrame()
                    else:
                        lock_wh_size_expr = (
                            "warehouse_size AS warehouse_size"
                            if "WAREHOUSE_SIZE" in lock_cols else "NULL::VARCHAR AS warehouse_size"
                        )
                        df_lock = run_query(f"""
                            SELECT query_id, database_name, schema_name, {_query_context_expr()},
                                   user_name, warehouse_name, {lock_wh_size_expr},
                                   start_time,
                                   transaction_blocked_time / 1000  AS blocked_sec,
                                   SUBSTR(query_text, 1, 300)       AS query_text
                            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                            WHERE start_time >= DATEADD('day', -1, CURRENT_TIMESTAMP())
                              AND transaction_blocked_time > 5000
                              {get_global_filter_clause("", "warehouse_name", "user_name", "role_name", "database_name")}
                            ORDER BY transaction_blocked_time DESC LIMIT 100
                        """, ttl_key=f"live_lock_waits_{company}", tier="standard")
                        st.session_state["lm_df_lock"] = df_lock
                except Exception as e:
                    st.warning(f"Lock wait history unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("lm_df_sessions") is not None and not st.session_state["lm_df_sessions"].empty:
            df_s = st.session_state["lm_df_sessions"]
            threshold_min = THRESHOLDS.get("long_session_hours", 8) * 60
            long_s = df_s[df_s["SESSION_MIN"] > threshold_min] if "SESSION_MIN" in df_s.columns else pd.DataFrame()
            render_shell_snapshot((
                ("Total Sessions", f"{len(df_s):,}"),
                ("Long Sessions (>8h)", f"{len(long_s):,}"),
            ))
            if not long_s.empty:
                st.warning(f"{len(long_s)} session(s) active > 8 hours.")
                render_priority_dataframe(
                    long_s,
                    title="Long sessions to review first",
                    priority_columns=[
                        "SESSION_ID",
                        "USER_NAME",
                        "CREATED_ON",
                        "SESSION_MIN",
                        "AUTHENTICATION_METHOD",
                    ],
                    sort_by=["SESSION_MIN"],
                    ascending=False,
                    raw_label="All long sessions",
                )
            st.subheader("All Sessions")
            render_priority_dataframe(
                df_s,
                title="Active sessions",
                priority_columns=[
                    "SESSION_ID",
                    "USER_NAME",
                    "CREATED_ON",
                    "SESSION_MIN",
                    "AUTHENTICATION_METHOD",
                ],
                sort_by=["SESSION_MIN"],
                ascending=False,
                raw_label="All session rows",
                height=300,
            )
            download_csv(df_s, "sessions.csv")

        if st.session_state.get("lm_df_lock") is not None:
            df_lk = st.session_state["lm_df_lock"]
            st.divider()
            st.subheader("Lock Wait History (last 24h, >5s blocked)")
            if not df_lk.empty:
                df_lk = _prioritize_query_context(df_lk)
                st.warning(f"{len(df_lk)} queries were blocked by lock contention.")
                render_priority_dataframe(
                    df_lk,
                    title="Lock waits to investigate first",
                    priority_columns=[
                        "QUERY_ID",
                        "QUERY_CONTEXT",
                        "DATABASE_NAME",
                        "SCHEMA_NAME",
                        "USER_NAME",
                        "WAREHOUSE_NAME",
                        "WAREHOUSE_SIZE",
                        "START_TIME",
                        "BLOCKED_SEC",
                        "QUERY_TEXT",
                    ],
                    sort_by=["BLOCKED_SEC", "START_TIME"],
                    ascending=[False, False],
                    raw_label="All lock-wait rows",
                )
                download_csv(df_lk, "lock_wait_history.csv")
            else:
                st.success("No significant lock waits in the last 24h.")
