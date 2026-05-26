# sections/security_access.py — Login audit, roles & privileges, data lineage, MFA, exfiltration
import streamlit as st
import pandas as pd
from utils import (
    build_action_queue_ddl,
    download_csv,
    get_session,
    get_wh_filter_clause,
    make_action_id,
    normalize_df,
    upsert_actions,
)
from config import THRESHOLDS


def _queue_security_findings(session, df: pd.DataFrame, finding_type: str, severity: str = "High") -> None:
    if df is None or df.empty:
        st.info("No security findings to queue.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    for _, row in df.head(200).iterrows():
        user = str(row.get("USER_NAME") or row.get("GRANTEE_NAME") or "Unknown user")
        if finding_type == "Failed Login":
            entity = user
            finding = f"{user} had {int(row.get('ATTEMPT_COUNT', 0) or 0)} failed login attempts from {row.get('CLIENT_IP', 'unknown IP')}"
            action = "Validate whether attempts are expected; review identity provider logs and lock/disable user if suspicious."
            proof = "LOGIN_HISTORY failed login attempts."
        elif finding_type == "Dormant User":
            entity = user
            finding = f"{user} is active but has been dormant for {int(row.get('DAYS_SINCE_LOGIN', 0) or 0)} days"
            action = "Confirm ownership and disable or remove roles if the account is no longer needed."
            proof = "USERS joined to LOGIN_HISTORY and QUERY_HISTORY."
        elif finding_type == "No MFA":
            entity = user
            finding = f"{user} is active without MFA coverage"
            action = "Enable MFA or move user to federated authentication with enforced MFA."
            proof = "ACCOUNT_USAGE.USERS ext_authn_duo / MFA signal."
        else:
            entity = str(row.get("QUERY_ID") or user)
            finding = f"{user} produced anomalously high result output: {row.get('GB_WRITTEN', '')} GB"
            action = "Review query text, business need, destination, and user activity before approving data movement."
            proof = "QUERY_HISTORY bytes_written_to_result compared with user baseline."
        actions.append({
            "Action ID": make_action_id("Security", entity, finding),
            "Source": f"Security & Access - {finding_type}",
            "Severity": severity,
            "Category": "Security",
            "Entity Type": "User" if finding_type != "Exfiltration" else "Query",
            "Entity": entity,
            "Owner": "Security/DBA",
            "Finding": finding,
            "Action": action,
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": "-- Review security context before disabling users, revoking access, or changing authentication controls.",
            "Proof Query": proof,
            "Company": company,
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} security findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {e}")
        st.download_button(
            "Download Action Queue DDL",
            build_action_queue_ddl(),
            file_name="overwatch_action_queue_setup.sql",
            mime="text/plain",
            key=f"sec_queue_ddl_{finding_type}",
        )


def render():
    session = get_session()

    tab_login, tab_posture, tab_roles, tab_mfa, tab_exfil, tab_lineage = st.tabs([
        "Login Audit", "Login Posture", "Roles & Grants", "MFA Coverage", "Exfiltration Signals", "Data Lineage"
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
            if st.button("Save failed-login findings to Action Queue", key="sec_failed_login_queue"):
                _queue_security_findings(session, st.session_state["sec_df_failed_logins"], "Failed Login", "Medium")

        if st.session_state.get("sec_df_login_trend") is not None and not st.session_state["sec_df_login_trend"].empty:
            df_t = st.session_state["sec_df_login_trend"]
            pivot = df_t.pivot_table(index="DAY", columns="IS_SUCCESS", values="EVENT_COUNT", aggfunc="sum").fillna(0)
            st.subheader("Login Trend")
            st.line_chart(pivot)

    with tab_posture:
        st.header("Login Posture")
        posture_days = st.slider("Posture lookback (days)", 1, 90, 30, key="sec_posture_days")
        if st.button("Load Login Posture", key="sec_posture_load"):
            for key, sql in [
                ("sec_login_ips", f"""
                    SELECT client_ip, COUNT(*) AS login_events,
                           COUNT(DISTINCT user_name) AS users,
                           SUM(IFF(is_success = 'NO', 1, 0)) AS failed_events,
                           MAX(event_timestamp) AS last_seen
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{posture_days}, CURRENT_TIMESTAMP())
                    GROUP BY client_ip
                    ORDER BY login_events DESC
                    LIMIT 50
                """),
                ("sec_login_clients", f"""
                    SELECT COALESCE(reported_client_type, 'UNKNOWN') AS reported_client_type,
                           COALESCE(reported_client_version, 'UNKNOWN') AS reported_client_version,
                           COUNT(*) AS login_events,
                           COUNT(DISTINCT user_name) AS users,
                           SUM(IFF(is_success = 'NO', 1, 0)) AS failed_events
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{posture_days}, CURRENT_TIMESTAMP())
                    GROUP BY reported_client_type, reported_client_version
                    ORDER BY login_events DESC
                    LIMIT 50
                """),
                ("sec_login_factors", f"""
                    SELECT COALESCE(first_authentication_factor, 'UNKNOWN') AS first_factor,
                           COALESCE(second_authentication_factor, 'NONE') AS second_factor,
                           COUNT(*) AS login_events,
                           SUM(IFF(is_success = 'NO', 1, 0)) AS failed_events
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{posture_days}, CURRENT_TIMESTAMP())
                    GROUP BY first_factor, second_factor
                    ORDER BY login_events DESC
                    LIMIT 50
                """),
                ("sec_login_errors", f"""
                    SELECT COALESCE(error_code, 'NONE') AS error_code,
                           COUNT(*) AS event_count,
                           COUNT(DISTINCT user_name) AS users,
                           COUNT(DISTINCT client_ip) AS ips
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{posture_days}, CURRENT_TIMESTAMP())
                    GROUP BY error_code
                    ORDER BY event_count DESC
                    LIMIT 50
                """),
            ]:
                try:
                    st.session_state[key] = normalize_df(session.sql(sql).to_pandas())
                except Exception:
                    st.session_state[key] = pd.DataFrame()

        c1, c2 = st.columns(2)
        with c1:
            ips = st.session_state.get("sec_login_ips")
            st.subheader("Top IPs")
            if ips is not None and not ips.empty:
                st.bar_chart(ips.set_index("CLIENT_IP")["LOGIN_EVENTS"])
                st.dataframe(ips, use_container_width=True, height=300)
                download_csv(ips, "login_posture_ips.csv")
        with c2:
            clients = st.session_state.get("sec_login_clients")
            st.subheader("Client Types / Versions")
            if clients is not None and not clients.empty:
                st.bar_chart(clients.set_index("REPORTED_CLIENT_TYPE")["LOGIN_EVENTS"])
                st.dataframe(clients, use_container_width=True, height=300)
                download_csv(clients, "login_posture_clients.csv")

        c3, c4 = st.columns(2)
        with c3:
            factors = st.session_state.get("sec_login_factors")
            st.subheader("Authentication Factors")
            if factors is not None and not factors.empty:
                st.dataframe(factors, use_container_width=True, height=300)
                download_csv(factors, "login_posture_auth_factors.csv")
        with c4:
            errors = st.session_state.get("sec_login_errors")
            st.subheader("Login Error Codes")
            if errors is not None and not errors.empty:
                st.bar_chart(errors.set_index("ERROR_CODE")["EVENT_COUNT"])
                st.dataframe(errors, use_container_width=True, height=300)
                download_csv(errors, "login_posture_error_codes.csv")

    # ── ROLES & GRANTS ────────────────────────────────────────────────────────
    with tab_roles:
        st.header("🛡️ Roles & Grants")
        if st.button("Load Grants", key="grants_load"):
            try:
                df_grants = normalize_df(session.sql("""
                    SELECT grantee_name, role, granted_to, granted_by,
                           created_on, deleted_on
                    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
                    WHERE deleted_on IS NULL
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
            if st.button("Save dormant users to Action Queue", key="sec_dormant_queue"):
                _queue_security_findings(session, df_d, "Dormant User", "Medium")

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
                if st.button("Save MFA findings to Action Queue", key="sec_mfa_queue"):
                    _queue_security_findings(session, no_mfa, "No MFA", "High")
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
                if st.button("Save exfiltration signals to Action Queue", key="sec_exfil_queue"):
                    _queue_security_findings(session, df_ex, "Exfiltration", "Critical")
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
