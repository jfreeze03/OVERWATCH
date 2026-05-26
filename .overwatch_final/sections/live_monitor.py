# sections/live_monitor.py — Real-time query history, timeline, sessions
# ─────────────────────────────────────────────────────────────────────────────
# FIXES vs previous version:
#   1. time.sleep() blocking REMOVED — replaced with @st.fragment(run_every=N)
#      The entire active queries panel is now a fragment that refreshes
#      independently without blocking the app thread or forcing a full rerun.
#      Users on other tabs (Timeline, Sessions) are unaffected.
#   2. Bare session.sql() on line 76 (ACCOUNT_USAGE fallback) already had
#      an inner try/except — confirmed clean in this version.
#   3. Lock Wait History added to Sessions tab.
# ─────────────────────────────────────────────────────────────────────────────
import streamlit as st
import pandas as pd
from datetime import datetime
from utils import (
    get_session, normalize_df, safe_sql, format_credits,
    credits_to_dollars, estimate_live_credits, download_csv,
    render_query_drilldown, get_wh_filter_clause,
)
from config import THRESHOLDS


def render():
    session      = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    rt_interval  = st.session_state.get("rt_interval", 30)

    tab_active, tab_timeline, tab_sessions = st.tabs([
        "Active Queries", "Timeline", "Sessions"
    ])

    # ── ACTIVE QUERIES ─────────────────────────────────────────────────────────
    with tab_active:
        st.header("🔴 Live & Recent Queries")
        st.caption(
            "🟢 **LIVE** uses `INFORMATION_SCHEMA.QUERY_HISTORY` (0-latency). "
            "🟡 **RECENT** uses `ACCOUNT_USAGE.QUERY_HISTORY` (≤45 min latency)."
        )

        c1, c2, c3, c4 = st.columns([1, 1, 2, 2])
        with c1: st.button("🔄 Refresh", key="lm_refresh")
        with c2:
            auto_refresh = st.checkbox(
                "Auto-refresh", key="lm_auto",
                help=f"Refreshes every {rt_interval}s via st.fragment — non-blocking."
            )
        with c3: wh_filter = st.text_input("Warehouse filter", key="lm_wh")
        with c4:
            status_filter = st.selectbox(
                "Status",
                ["ALL", "RUNNING", "QUEUED", "BLOCKED", "SUCCESS", "FAILED_WITH_ERROR"],
                key="lm_status",
            )

        # ── @st.fragment — refreshes this panel independently on a timer ──────
        # run_every=N means Streamlit re-executes just this function every N
        # seconds without triggering a full app rerun. No time.sleep() needed.
        # When auto_refresh is unchecked, run_every=None → fragment renders
        # once and waits for a manual interaction.
        _run_every = rt_interval if auto_refresh else None

        @st.fragment(run_every=_run_every)
        def _live_panel():
            _session  = get_session()
            wh_safe   = safe_sql(wh_filter)
            wh_clause = f"AND warehouse_name ILIKE '%{wh_safe}%'" if wh_safe else ""
            company_wh_clause = get_wh_filter_clause("warehouse_name")
            st_clause = f"AND execution_status = '{status_filter}'" if status_filter != "ALL" else ""

            if auto_refresh:
                st.caption(f"⏱ Last updated: {datetime.now().strftime('%H:%M:%S')} · auto-refresh {rt_interval}s")

            # ── Live — INFORMATION_SCHEMA (0-latency) ─────────────────────────
            st.subheader("🟢 Currently Running")
            live_sql = f"""
            SELECT query_id, SUBSTR(query_text,1,300) AS query_text,
                   user_name, warehouse_name, warehouse_size, execution_status, start_time,
                   DATEDIFF('second',start_time,CURRENT_TIMESTAMP()) AS elapsed_sec,
                   bytes_scanned/POWER(1024,2) AS mb_scanned, rows_produced
            FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
                END_TIME_RANGE_START=>DATEADD('hours',-1,CURRENT_TIMESTAMP()),
                RESULT_LIMIT=>500))
            WHERE execution_status IN ('RUNNING','QUEUED','BLOCKED','RESUMING_WAREHOUSE')
              {wh_clause}
              {company_wh_clause}
            ORDER BY elapsed_sec DESC
            """
            df_live = pd.DataFrame()
            try:
                df_live = normalize_df(_session.sql(live_sql).to_pandas())
            except Exception:
                # IS unavailable (e.g. serverless context) — fall back to AU
                st.info("ℹ️ INFORMATION_SCHEMA unavailable — using ACCOUNT_USAGE fallback.")
                try:
                    df_live = normalize_df(_session.sql(f"""
                        SELECT query_id, SUBSTR(query_text,1,300) AS query_text,
                               user_name, warehouse_name, warehouse_size,
                               execution_status, start_time,
                               total_elapsed_time/1000 AS elapsed_sec,
                               bytes_scanned/POWER(1024,2) AS mb_scanned, rows_produced
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('minutes',-10,CURRENT_TIMESTAMP())
                          AND execution_status IN ('RUNNING','QUEUED','BLOCKED','RESUMING_WAREHOUSE')
                          {wh_clause}
                          {company_wh_clause}
                        ORDER BY start_time DESC LIMIT 100
                    """).to_pandas())
                except Exception as fallback_err:
                    st.warning(f"Live query data unavailable: {fallback_err}")

            if not df_live.empty:
                df_live["EST_COMPUTE_CREDITS"] = df_live.apply(estimate_live_credits, axis=1)
                df_live["EST_DOLLARS"]          = df_live["EST_COMPUTE_CREDITS"].apply(credits_to_dollars)
                c_a, c_b, c_c = st.columns(3)
                c_a.metric("Active Queries", len(df_live))
                queued = int((df_live["EXECUTION_STATUS"] == "QUEUED").sum()) \
                         if "EXECUTION_STATUS" in df_live.columns else 0
                c_b.metric("Queued",      queued)
                c_c.metric("Est. Live Cost", f"${df_live['EST_DOLLARS'].sum():,.4f}")
                render_query_drilldown(df_live, key="lm_live")

                # Kill query
                st.divider()
                st.subheader("⛔ Kill Query")
                kill_qid = st.text_input("Query ID to cancel", key="lm_kill_id")
                if kill_qid and st.button("Cancel Query", type="primary", key="lm_kill_btn"):
                    try:
                        _session.sql(f"SELECT SYSTEM$CANCEL_QUERY('{safe_sql(kill_qid)}')").collect()
                        st.success(f"✅ Cancel sent for `{kill_qid}`")
                    except Exception as e:
                        st.error(f"Cancel failed: {e}")
            else:
                st.success("✅ No active queries right now.")

            # ── Recent — ACCOUNT_USAGE (≤45 min lag) ──────────────────────────
            st.divider()
            st.subheader("🟡 Recent (last 4h, ACCOUNT_USAGE)")
            try:
                df_recent = normalize_df(_session.sql(f"""
                    SELECT query_id, user_name, warehouse_name, warehouse_size, execution_status,
                           start_time, total_elapsed_time/1000 AS elapsed_sec,
                           bytes_scanned/POWER(1024,3) AS gb_scanned,
                           rows_produced, credits_used_cloud_services AS cloud_credits,
                           SUBSTR(query_text,1,300) AS query_text
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('hours',-4,CURRENT_TIMESTAMP())
                      {wh_clause} {company_wh_clause} {st_clause}
                    ORDER BY start_time DESC LIMIT 500
                """).to_pandas())
                if not df_recent.empty:
                    st.dataframe(df_recent, use_container_width=True, height=350)
                    download_csv(df_recent, "recent_queries.csv")
            except Exception as e:
                st.caption(f"Recent query data unavailable: {e}")

        _live_panel()

    # ── TIMELINE ───────────────────────────────────────────────────────────────
    with tab_timeline:
        st.header("📈 Query Timeline")
        tl_hours = st.slider("Lookback (hours)", 1, 24, 6, key="lm_tl_hours")
        if st.button("Load Timeline", key="lm_tl_load"):
            try:
                df_tl = normalize_df(session.sql(f"""
                    SELECT DATE_TRUNC('hour', start_time) AS time_bucket,
                           execution_status,
                           COUNT(*)                       AS query_count,
                           AVG(total_elapsed_time)/1000   AS avg_elapsed_sec
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('hours', -{tl_hours}, CURRENT_TIMESTAMP())
                      {get_wh_filter_clause("warehouse_name")}
                    GROUP BY time_bucket, execution_status
                    ORDER BY time_bucket
                """).to_pandas())
                st.session_state["lm_df_tl"] = df_tl
            except Exception as e:
                st.error(f"Timeline load failed: {e}")

        if st.session_state.get("lm_df_tl") is not None and not st.session_state["lm_df_tl"].empty:
            df_t = st.session_state["lm_df_tl"]
            try:
                pivot = df_t.pivot_table(
                    index="TIME_BUCKET", columns="EXECUTION_STATUS",
                    values="QUERY_COUNT", aggfunc="sum"
                ).fillna(0)
                st.line_chart(pivot)
            except Exception:
                st.dataframe(df_t, use_container_width=True)
            download_csv(df_t, "query_timeline.csv")

    # ── SESSIONS ───────────────────────────────────────────────────────────────
    with tab_sessions:
        st.header("🖥️ Active Sessions")
        s1, s2 = st.columns(2)

        with s1:
            if st.button("Load Sessions", key="lm_sess_load"):
                try:
                    df_sess = normalize_df(session.sql("""
                        SELECT session_id, user_name, created_on,
                               DATEDIFF('minute', created_on, CURRENT_TIMESTAMP()) AS session_min,
                               authentication_method
                        FROM SNOWFLAKE.ACCOUNT_USAGE.SESSIONS
                        WHERE created_on >= DATEADD('day', -1, CURRENT_TIMESTAMP())
                        ORDER BY session_min DESC LIMIT 200
                    """).to_pandas())
                    st.session_state["lm_df_sessions"] = df_sess
                except Exception as e:
                    st.warning(f"Sessions view unavailable: {e}")

        with s2:
            if st.button("Load Lock Waits", key="lm_lock_load"):
                try:
                    df_lock = normalize_df(session.sql(f"""
                        SELECT query_id, user_name, warehouse_name, warehouse_size,
                               start_time,
                               transaction_blocked_time / 1000  AS blocked_sec,
                               SUBSTR(query_text, 1, 300)       AS query_text
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                        WHERE start_time >= DATEADD('day', -1, CURRENT_TIMESTAMP())
                          AND transaction_blocked_time > 5000
                          {get_wh_filter_clause("warehouse_name")}
                        ORDER BY transaction_blocked_time DESC LIMIT 100
                    """).to_pandas())
                    st.session_state["lm_df_lock"] = df_lock
                except Exception as e:
                    st.warning(f"Lock wait history unavailable: {e}")

        if st.session_state.get("lm_df_sessions") is not None and not st.session_state["lm_df_sessions"].empty:
            df_s = st.session_state["lm_df_sessions"]
            threshold_min = THRESHOLDS.get("long_session_hours", 8) * 60
            long_s = df_s[df_s["SESSION_MIN"] > threshold_min] if "SESSION_MIN" in df_s.columns else pd.DataFrame()
            c1, c2 = st.columns(2)
            c1.metric("Total Sessions",       len(df_s))
            c2.metric("Long Sessions (>8h)",  len(long_s), delta_color="inverse")
            if not long_s.empty:
                st.warning(f"⚠️ {len(long_s)} session(s) active > 8 hours.")
                st.dataframe(long_s, use_container_width=True)
            st.subheader("All Sessions")
            st.dataframe(df_s, use_container_width=True, height=300)
            download_csv(df_s, "sessions.csv")

        if st.session_state.get("lm_df_lock") is not None:
            df_lk = st.session_state["lm_df_lock"]
            st.divider()
            st.subheader("🔒 Lock Wait History (last 24h, >5s blocked)")
            if not df_lk.empty:
                st.warning(f"⚠️ {len(df_lk)} queries were blocked by lock contention.")
                st.dataframe(df_lk, use_container_width=True)
                download_csv(df_lk, "lock_wait_history.csv")
            else:
                st.success("✅ No significant lock waits in the last 24h.")
