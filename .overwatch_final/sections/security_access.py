# sections/security_access.py — Login audit, roles & privileges, data lineage, MFA, exfiltration
import streamlit as st
import pandas as pd
from utils import get_session, normalize_df, download_csv, get_wh_filter_clause
from config import THRESHOLDS


def render():
    session = get_session()

    tab_login, tab_roles, tab_mfa, tab_exfil, tab_lineage = st.tabs([
        "Login Audit", "Roles & Grants", "MFA Coverage", "Exfiltration Signals", "Data Lineage"
    ])

    # ── LOGIN AUDIT ───────────────────────────────────────────────────────────
    with tab_login:
        st.header("🔒 Login Audit")
        sec_days = st.slider("Lookback (days)", 1, 90, 30, key="sec_days")

        if st.button("Load Login Data", key="sec_load"):
            for key, sql in [
                ("df_login_sum", f"""
                    SELECT is_success, COUNT(*) AS event_count,
                           COUNT(DISTINCT user_name) AS distinct_users,
                           COUNT(DISTINCT client_ip) AS distinct_ips
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{sec_days}, CURRENT_TIMESTAMP())
                    GROUP BY is_success
                """),
                ("df_failed_logins", f"""
                    SELECT user_name, client_ip, reported_client_type, error_code,
                           COUNT(*) AS attempt_count,
                           MAX(event_timestamp) AS last_attempt
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{sec_days}, CURRENT_TIMESTAMP())
                      AND is_success = 'NO'
                    GROUP BY user_name, client_ip, reported_client_type, error_code
                    ORDER BY attempt_count DESC LIMIT 50
                """),
                ("df_login_trend", f"""
                    SELECT DATE_TRUNC('day', event_timestamp) AS day,
                           is_success, COUNT(*) AS event_count
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{sec_days}, CURRENT_TIMESTAMP())
                    GROUP BY day, is_success ORDER BY day
                """),
            ]:
                try:
                    st.session_state[key] = normalize_df(session.sql(sql).to_pandas())
                except Exception:
                    st.session_state[key] = pd.DataFrame()

        if st.session_state.get("sec_df_login_sum") is not None and not st.session_state["sec_df_login_sum"].empty:
            df_ls = st.session_state["sec_df_login_sum"]
            ok  = df_ls.loc[df_ls["IS_SUCCESS"] == "YES", "EVENT_COUNT"].sum() if "YES" in df_ls["IS_SUCCESS"].values else 0
            fail= df_ls.loc[df_ls["IS_SUCCESS"] == "NO",  "EVENT_COUNT"].sum() if "NO"  in df_ls["IS_SUCCESS"].values else 0
            tot = ok + fail
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Logins",    f"{int(tot):,}")
            c2.metric("Successful",      f"{int(ok):,}")
            c3.metric("Failed",          f"{int(fail):,}",   delta_color="inverse")
            c4.metric("Failure Rate",    f"{(fail/tot*100) if tot else 0:.2f}%")

        if st.session_state.get("sec_df_failed_logins") is not None and not st.session_state["sec_df_failed_logins"].empty:
            st.subheader("Failed Login Attempts")
            st.dataframe(st.session_state["sec_df_failed_logins"], use_container_width=True)
            download_csv(st.session_state["sec_df_failed_logins"], "failed_logins.csv")

        if st.session_state.get("sec_df_login_trend") is not None and not st.session_state["sec_df_login_trend"].empty:
            df_t = st.session_state["sec_df_login_trend"]
            pivot = df_t.pivot_table(index="DAY", columns="IS_SUCCESS", values="EVENT_COUNT", aggfunc="sum").fillna(0)
            st.subheader("Login Trend")
            st.line_chart(pivot)

    # ── ROLES & GRANTS ────────────────────────────────────────────────────────
    with tab_roles:
        st.header("🛡️ Roles & Privilege Grants")
        if st.button("Load Grants", key="grants_load"):
            try:
                df_grants = normalize_df(session.sql("""
                    SELECT grantee_name, role, privilege, granted_on,
                           name AS object_name, granted_by, created_on
                    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
                    ORDER BY created_on DESC LIMIT 500
                """).to_pandas())
                st.session_state["sec_df_grants"] = df_grants
            except Exception as e:
                st.error(f"Error: {e}")

        if st.session_state.get("sec_df_grants") is not None and not st.session_state["sec_df_grants"].empty:
            df_g = st.session_state["sec_df_grants"]
            st.metric("Total Grants", len(df_g))
            st.dataframe(df_g, use_container_width=True)
            download_csv(df_g, "grants_to_users.csv")

        # Dormant users
        st.divider()
        st.subheader("💤 Dormant User Detection")
        dormant_days = st.number_input("Inactive threshold (days)", 30, 365, THRESHOLDS["dormant_user_days"], key="dom_days")
        if st.button("Find Dormant Users", key="dom_find"):
            try:
                df_dom = normalize_df(session.sql(f"""
                WITH last_login AS (
                    SELECT user_name, MAX(event_timestamp) AS last_login_time
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -365, CURRENT_TIMESTAMP())
                    GROUP BY user_name
                ),
                last_query AS (
                    SELECT user_name, MAX(start_time) AS last_query_time
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -365, CURRENT_TIMESTAMP())
                    GROUP BY user_name
                )
                SELECT u.name AS user_name, u.created_on, u.disabled,
                       COALESCE(ll.last_login_time, u.last_success_login) AS last_login,
                       lq.last_query_time,
                       DATEDIFF('day', COALESCE(ll.last_login_time, u.created_on), CURRENT_TIMESTAMP()) AS days_since_login
                FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
                LEFT JOIN last_login ll ON u.name = ll.user_name
                LEFT JOIN last_query  lq ON u.name = lq.user_name
                WHERE u.deleted_on IS NULL
                  AND u.disabled = 'false'
                  AND DATEDIFF('day', COALESCE(ll.last_login_time, u.created_on), CURRENT_TIMESTAMP()) > {dormant_days}
                ORDER BY days_since_login DESC
                """).to_pandas())
                st.session_state["sec_df_dom"] = df_dom
            except Exception as e:
                st.error(f"Error: {e}")

        if st.session_state.get("sec_df_dom") is not None and not st.session_state["sec_df_dom"].empty:
            df_d = st.session_state["sec_df_dom"]
            st.warning(f"⚠️ {len(df_d)} users inactive > {dormant_days} days — review for deactivation.")
            st.dataframe(df_d, use_container_width=True)
            download_csv(df_d, "dormant_users.csv")

    # ── MFA COVERAGE ──────────────────────────────────────────────────────────
    with tab_mfa:
        st.header("🔐 MFA Coverage Report")
        if st.button("Check MFA", key="mfa_check"):
            try:
                df_mfa = normalize_df(session.sql("""
                    SELECT u.name AS user_name, u.has_password,
                           u.ext_authn_duo AS has_mfa, u.disabled,
                           MAX(l.event_timestamp) AS last_login
                    FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
                    LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY l ON u.name = l.user_name
                    WHERE u.deleted_on IS NULL AND u.disabled = 'false'
                    GROUP BY u.name, u.has_password, u.ext_authn_duo, u.disabled
                    ORDER BY has_mfa, user_name
                """).to_pandas())
                st.session_state["sec_df_mfa"] = df_mfa
            except Exception as e:
                st.warning(f"MFA check unavailable: {e}")

        if st.session_state.get("sec_df_mfa") is not None and not st.session_state["sec_df_mfa"].empty:
            df_m = st.session_state["sec_df_mfa"]
            mfa_col = "HAS_MFA" if "HAS_MFA" in df_m.columns else "EXT_AUTHN_DUO"
            no_mfa = df_m[df_m[mfa_col].astype(str).str.lower() != "true"] if mfa_col in df_m.columns else df_m
            c1, c2 = st.columns(2)
            c1.metric("Users Without MFA",  len(no_mfa),    delta_color="inverse")
            c2.metric("MFA Coverage",       f"{(1-len(no_mfa)/max(len(df_m),1))*100:.0f}%")
            if not no_mfa.empty:
                st.warning(f"⚠️ {len(no_mfa)} active user(s) without MFA enabled.")
                st.dataframe(no_mfa, use_container_width=True)
                download_csv(no_mfa, "users_without_mfa.csv")
            else:
                st.success("✅ All active users have MFA enabled.")

    # ── EXFILTRATION SIGNALS ──────────────────────────────────────────────────
    with tab_exfil:
        st.header("🚨 Data Exfiltration Signals")
        st.caption("Users with >2σ BYTES_WRITTEN_TO_RESULT vs their 30-day baseline.")
        if st.button("Check Exfiltration", key="exfil_load"):
            try:
                df_ex = normalize_df(session.sql(f"""
                WITH user_baseline AS (
                    SELECT user_name,
                           AVG(bytes_written_to_result) AS avg_bytes,
                           STDDEV(bytes_written_to_result) AS std_bytes
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
                      AND bytes_written_to_result > 0
                    GROUP BY user_name HAVING COUNT(*) >= 5
                ),
                recent AS (
                    SELECT user_name, query_id, warehouse_name, warehouse_size, start_time,
                           bytes_written_to_result/POWER(1024,3) AS gb_written,
                           rows_produced
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -3, CURRENT_TIMESTAMP())
                      AND bytes_written_to_result > 0
                      {get_wh_filter_clause("warehouse_name")}
                )
                SELECT r.user_name, r.query_id, r.warehouse_name, r.warehouse_size, r.start_time,
                       ROUND(r.gb_written, 3)                           AS gb_written,
                       r.rows_produced,
                       ROUND(b.avg_bytes/POWER(1024,3), 3)              AS avg_gb_baseline,
                       ROUND((r.gb_written - b.avg_bytes/POWER(1024,3))
                             / NULLIF(b.std_bytes/POWER(1024,3),0), 1)  AS zscore
                FROM recent r
                JOIN user_baseline b ON r.user_name = b.user_name
                WHERE r.gb_written > b.avg_bytes/POWER(1024,3) + 2*b.std_bytes/POWER(1024,3)
                ORDER BY r.gb_written DESC LIMIT 20
                """).to_pandas())
                st.session_state["sec_df_exfil"] = df_ex
            except Exception as e:
                st.warning(f"Exfiltration check unavailable: {e}")

        if st.session_state.get("sec_df_exfil") is not None:
            df_ex = st.session_state["sec_df_exfil"]
            if not df_ex.empty:
                st.error(f"⚠️ {len(df_ex)} queries with anomalously high data output (>2σ above user baseline).")
                st.dataframe(df_ex, use_container_width=True)
                download_csv(df_ex, "exfiltration_signals.csv")
            else:
                st.success("✅ No unusual data exfiltration patterns detected.")

    # ── DATA LINEAGE ──────────────────────────────────────────────────────────
    with tab_lineage:
        st.header("🔗 Data Lineage (ACCESS_HISTORY)")
        st.caption("Object-level access lineage from ACCOUNT_USAGE.ACCESS_HISTORY.")
        lin_days = st.slider("Lookback (days)", 1, 30, 7, key="lin_days")

        if st.button("Load Access History", key="lin_load"):
            try:
                df_lin = normalize_df(session.sql(f"""
                    SELECT user_name, query_id,
                           query_start_time,
                           objects_modified,
                           objects_modified_by_ddl,
                           base_objects_accessed,
                           direct_objects_accessed
                    FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY
                    WHERE query_start_time >= DATEADD('day', -{lin_days}, CURRENT_TIMESTAMP())
                    ORDER BY query_start_time DESC
                    LIMIT 500
                """).to_pandas())
                st.session_state["sec_df_lin"] = df_lin
            except Exception as e:
                st.error(f"Error: {e}")

        if st.session_state.get("sec_df_lin") is not None and not st.session_state["sec_df_lin"].empty:
            df_l = st.session_state["sec_df_lin"]
            st.metric("Access Events", len(df_l))
            st.dataframe(df_l, use_container_width=True)
            download_csv(df_l, "access_history.csv")
