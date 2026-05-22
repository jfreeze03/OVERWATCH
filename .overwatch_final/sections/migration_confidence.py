# sections/migration_confidence.py — Row count recon, validation, executive tracker, ROI scorecard
import streamlit as st
import pandas as pd
from datetime import datetime
from utils import (
    get_session, normalize_df, download_csv, safe_sql,
    format_credits, credits_to_dollars,
)
from config import ETL_AUDIT_DB, ETL_AUDIT_SCHEMA, DEFAULTS

RECON_TABLE    = f"{ETL_AUDIT_DB}.{ETL_AUDIT_SCHEMA}.MIGRATION_RECON"
DOMAINS_TABLE  = f"{ETL_AUDIT_DB}.{ETL_AUDIT_SCHEMA}.MIGRATION_DOMAINS"
ROI_TABLE      = f"{ETL_AUDIT_DB}.{ETL_AUDIT_SCHEMA}.OVERWATCH_ROI_LOG"


def render():
    session      = get_session()
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])

    tab_recon, tab_history, tab_dashboard, tab_deep, tab_executive, tab_roi = st.tabs([
        "Row Count Recon", "Validation History", "Recon Dashboard",
        "Deep Validation", "📊 Executive Progress", "💰 ROI Scorecard"
    ])

    # ── ROW COUNT RECON ───────────────────────────────────────────────────────
    with tab_recon:
        st.header("🔄 Migration Row Count Reconciliation")
        st.caption("Compare Snowflake table row counts to expected values from Teradata migration.")

        setup_ddl = f"""CREATE TABLE IF NOT EXISTS {RECON_TABLE} (
    RECON_ID        NUMBER AUTOINCREMENT PRIMARY KEY,
    RECON_DATE      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    TABLE_NAME      VARCHAR(500),
    SF_ROW_COUNT    NUMBER,
    EXPECTED_COUNT  NUMBER,
    DELTA           NUMBER,
    DELTA_PCT       FLOAT,
    STATUS          VARCHAR(20),
    NOTES           VARCHAR(1000)
);"""
        with st.expander("📋 Recon Table Setup DDL"):
            st.code(setup_ddl, language="sql")

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            sf_db  = st.text_input("Snowflake Database", value="PROD_DB",  key="rc_sfdb")
            sf_sch = st.text_input("Snowflake Schema",   value="PUBLIC",   key="rc_sfsch")
        with col2:
            tolerance_pct = st.number_input("Tolerance % (rows)", 0.0, 10.0, 0.5, step=0.1, key="rc_tol")

        uploaded = st.file_uploader(
            "Upload expected counts CSV (columns: table_name, expected_count)",
            type=["csv"], key="rc_upload"
        )
        if uploaded:
            import io
            expected_df = pd.read_csv(io.StringIO(uploaded.getvalue().decode("utf-8")))
            expected_df.columns = [c.upper().strip() for c in expected_df.columns]
            st.session_state["mc_recon_expected"] = expected_df
            st.success(f"Loaded {len(expected_df)} table definitions.")

        if st.session_state.get("mc_recon_expected") is not None and st.button("Run Recon", key="rc_run"):
            exp_df   = st.session_state["mc_recon_expected"]
            results  = []
            progress = st.progress(0)
            for i, row in exp_df.iterrows():
                tbl = safe_sql(str(row.get("TABLE_NAME", "")))
                exp = int(row.get("EXPECTED_COUNT", 0))
                progress.progress((i + 1) / max(len(exp_df), 1))
                try:
                    sf_count  = session.sql(f"SELECT COUNT(*) AS cnt FROM {sf_db}.{sf_sch}.{tbl}").collect()[0]["CNT"]
                    delta     = sf_count - exp
                    delta_pct = (delta / exp * 100) if exp > 0 else 0
                    status    = "PASS" if abs(delta_pct) <= tolerance_pct else ("WARNING" if abs(delta_pct) <= 5 else "FAIL")
                    results.append({"TABLE_NAME": tbl, "SF_ROW_COUNT": sf_count, "EXPECTED_COUNT": exp,
                                    "DELTA": delta, "DELTA_PCT": round(delta_pct, 4), "STATUS": status})
                except Exception as e:
                    results.append({"TABLE_NAME": tbl, "SF_ROW_COUNT": 0, "EXPECTED_COUNT": exp,
                                    "DELTA": -exp, "DELTA_PCT": -100, "STATUS": "FAIL", "NOTES": str(e)[:200]})
            progress.empty()
            df_results = pd.DataFrame(results)
            st.session_state["mc_recon_results"] = df_results
            try:
                session.create_dataframe(df_results).write.mode("append").save_as_table(RECON_TABLE)
                st.success(f"✅ Results written to `{RECON_TABLE}`")
            except Exception as e:
                st.warning(f"Could not write to recon table: {e}")

        if st.session_state.get("mc_recon_results") is not None:
            df_r    = st.session_state["mc_recon_results"]
            passed  = df_r[df_r["STATUS"] == "PASS"]
            failed  = df_r[df_r["STATUS"] == "FAIL"]
            warning = df_r[df_r["STATUS"] == "WARNING"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Tables", len(df_r))
            c2.metric("✅ Pass",       len(passed))
            c3.metric("⚠️ Warning",    len(warning))
            c4.metric("❌ Fail",       len(failed), delta_color="inverse")
            if not failed.empty:
                st.error(f"❌ {len(failed)} tables FAILED reconciliation")
                st.dataframe(failed, use_container_width=True)
            st.dataframe(df_r, use_container_width=True)
            download_csv(df_r, "migration_recon_results.csv")

    # ── VALIDATION HISTORY ────────────────────────────────────────────────────
    with tab_history:
        st.header("📅 Recon Run History")
        if st.button("Load History", key="rh_load"):
            try:
                df_rh = normalize_df(session.sql(f"""
                    SELECT RECON_DATE, TABLE_NAME, SF_ROW_COUNT, EXPECTED_COUNT,
                           DELTA, DELTA_PCT, STATUS
                    FROM {RECON_TABLE}
                    ORDER BY RECON_DATE DESC LIMIT 1000
                """).to_pandas())
                st.session_state["mc_recon_history"] = df_rh
            except Exception as e:
                st.info(f"Recon table not found — run setup DDL first. ({e})")
        if st.session_state.get("mc_recon_history") is not None and not st.session_state["mc_recon_history"].empty:
            st.dataframe(st.session_state["mc_recon_history"], use_container_width=True)
            download_csv(st.session_state["mc_recon_history"], "recon_history.csv")

    # ── RECON DASHBOARD ───────────────────────────────────────────────────────
    with tab_dashboard:
        st.header("📊 Recon Dashboard — Latest Run Summary")
        if st.button("Load Dashboard", key="rd_load"):
            try:
                df_dash = normalize_df(session.sql(f"""
                    WITH latest_run AS (SELECT MAX(RECON_DATE) AS latest FROM {RECON_TABLE})
                    SELECT r.TABLE_NAME, r.SF_ROW_COUNT, r.EXPECTED_COUNT,
                           r.DELTA, r.DELTA_PCT, r.STATUS
                    FROM {RECON_TABLE} r
                    JOIN latest_run lr ON r.RECON_DATE = lr.latest
                    ORDER BY ABS(r.DELTA_PCT) DESC
                """).to_pandas())
                st.session_state["mc_recon_dash"] = df_dash
            except Exception as e:
                st.info(f"No recon data available. ({e})")
        if st.session_state.get("mc_recon_dash") is not None and not st.session_state["mc_recon_dash"].empty:
            df_d = st.session_state["mc_recon_dash"]
            pass_r = len(df_d[df_d["STATUS"] == "PASS"])
            fail_r = len(df_d[df_d["STATUS"] == "FAIL"])
            c1, c2, c3 = st.columns(3)
            c1.metric("Tables Checked", len(df_d))
            c2.metric("Pass Rate",      f"{pass_r/max(len(df_d),1)*100:.0f}%")
            c3.metric("Failures",       fail_r, delta_color="inverse")
            st.bar_chart(df_d.set_index("TABLE_NAME")["DELTA_PCT"].head(30))
            st.dataframe(df_d, use_container_width=True)

    # ── DEEP VALIDATION ───────────────────────────────────────────────────────
    with tab_deep:
        st.header("Teradata vs Snowflake Deep Validation")
        c1, c2 = st.columns(2)
        with c1:
            sf_db_d   = st.text_input("Snowflake Database", value="PROD_DB", key="dv_sf_db")
            sf_sch_d  = st.text_input("Snowflake Schema",   value="PUBLIC",  key="dv_sf_sch")
            table_name = st.text_input("Table",                               key="dv_table")
        with c2:
            key_cols      = st.text_input("Duplicate key columns (comma separated)",              key="dv_keys")
            compare_cols  = st.text_input("Columns to hash/null-check (comma separated)",         key="dv_cols")
            expected_hash = st.text_input("Teradata expected hash total (optional)",               key="dv_expected_hash")
        if st.button("Generate / Run Deep Validation", key="dv_run") and table_name and compare_cols:
            cols = [safe_sql(c.strip()) for c in compare_cols.split(",") if c.strip()]
            keys = [safe_sql(c.strip()) for c in key_cols.split(",") if c.strip()]
            null_exprs = ",\n       ".join([f"SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) AS {c}_nulls" for c in cols])
            hash_expr  = " + ".join([f"HASH({c})" for c in cols])
            dup_sql    = ""
            if keys:
                key_list = ", ".join(keys)
                dup_sql  = f"\nSELECT COUNT(*) AS duplicate_key_count FROM (SELECT {key_list}, COUNT(*) AS cnt FROM {safe_sql(sf_db_d)}.{safe_sql(sf_sch_d)}.{safe_sql(table_name)} GROUP BY {key_list} HAVING COUNT(*) > 1);"
            validation_sql = f"SELECT COUNT(*) AS row_count, SUM({hash_expr}) AS hash_total, {null_exprs}\nFROM {safe_sql(sf_db_d)}.{safe_sql(sf_sch_d)}.{safe_sql(table_name)};\n{dup_sql}"
            st.code(validation_sql, language="sql")
            try:
                df_val = normalize_df(session.sql(validation_sql.split(";")[0]).to_pandas())
                if expected_hash and not df_val.empty:
                    df_val["HASH_STATUS"] = "PASS" if str(df_val["HASH_TOTAL"].iloc[0]) == expected_hash else "FAIL"
                st.dataframe(df_val, use_container_width=True)
                download_csv(df_val, "deep_validation.csv")
            except Exception as e:
                st.info(f"SQL generated but execution failed: {e}")

    # ── EXECUTIVE PROGRESS TRACKER (NEW) ─────────────────────────────────────
    with tab_executive:
        st.header("📊 Migration Progress — Executive View")
        st.caption(
            "Board-ready migration status by business domain. "
            "Requires MIGRATION_DOMAINS config table (setup DDL below) "
            "mapping table names to business areas."
        )

        # Domain config DDL
        domain_ddl = f"""-- Maps tables to business domains for the executive progress view.
-- Run once, then INSERT your table→domain mappings.
CREATE TABLE IF NOT EXISTS {DOMAINS_TABLE} (
    TABLE_NAME      VARCHAR(500) PRIMARY KEY,
    BUSINESS_DOMAIN VARCHAR(200),   -- e.g. 'Claims', 'Policy', 'Finance', 'Reference'
    PRIORITY        VARCHAR(20),    -- HIGH | MEDIUM | LOW
    OWNER           VARCHAR(200),   -- Team or person responsible
    TARGET_DATE     DATE
);

-- Example:
-- INSERT INTO {DOMAINS_TABLE} VALUES
--   ('CLAIM_HEADER',  'Claims',    'HIGH',   'Claims DBA team', '2025-08-01'),
--   ('POLICY_MASTER', 'Policy',    'HIGH',   'Policy team',     '2025-08-15'),
--   ('GL_ACCOUNT',    'Finance',   'MEDIUM', 'Finance DBA',     '2025-09-01'),
--   ('STATE_REF',     'Reference', 'LOW',    'DBA team',        '2025-07-01');"""
        with st.expander("📋 Domain Config Setup DDL"):
            st.code(domain_ddl, language="sql")
            st.download_button(
                "📥 Download DDL",
                domain_ddl,
                file_name="migration_domains_setup.sql",
                mime="text/plain",
                key="dom_ddl_dl",
            )

        st.divider()

        if st.button("Load Executive Progress", key="exec_prog_load"):
            with st.spinner("Loading migration status..."):
                # Overall summary from recon table
                try:
                    df_overall = normalize_df(session.sql(f"""
                        WITH latest AS (SELECT MAX(RECON_DATE) AS dt FROM {RECON_TABLE})
                        SELECT
                            COUNT(*)                                                   AS total_tables,
                            SUM(CASE WHEN r.STATUS='PASS'    THEN 1 ELSE 0 END)        AS passed,
                            SUM(CASE WHEN r.STATUS='WARNING' THEN 1 ELSE 0 END)        AS warning,
                            SUM(CASE WHEN r.STATUS='FAIL'    THEN 1 ELSE 0 END)        AS failed,
                            ROUND(SUM(CASE WHEN r.STATUS='PASS' THEN 1 ELSE 0 END)
                                  * 100.0 / NULLIF(COUNT(*),0), 1)                     AS pct_complete,
                            MAX(r.RECON_DATE)                                          AS last_run
                        FROM {RECON_TABLE} r, latest l
                        WHERE r.RECON_DATE = l.dt
                    """).to_pandas())
                    st.session_state["mc_exec_overall"] = df_overall
                except Exception as e:
                    st.session_state["mc_exec_overall"] = pd.DataFrame()
                    st.caption(f"Overall stats unavailable: {e}")

                # Domain breakdown (with graceful fallback if DOMAINS table missing)
                try:
                    df_domain = normalize_df(session.sql(f"""
                        WITH latest AS (SELECT MAX(RECON_DATE) AS dt FROM {RECON_TABLE}),
                        recon_latest AS (
                            SELECT r.TABLE_NAME, r.STATUS, r.DELTA_PCT
                            FROM {RECON_TABLE} r, latest l
                            WHERE r.RECON_DATE = l.dt
                        )
                        SELECT
                            d.BUSINESS_DOMAIN,
                            d.PRIORITY,
                            d.OWNER,
                            d.TARGET_DATE,
                            COUNT(*)                                                   AS total_tables,
                            SUM(CASE WHEN r.STATUS='PASS'    THEN 1 ELSE 0 END)        AS passed,
                            SUM(CASE WHEN r.STATUS='FAIL'    THEN 1 ELSE 0 END)        AS failed,
                            ROUND(SUM(CASE WHEN r.STATUS='PASS' THEN 1 ELSE 0 END)
                                  * 100.0 / NULLIF(COUNT(*),0), 1)                     AS pct_complete
                        FROM {DOMAINS_TABLE} d
                        LEFT JOIN recon_latest r ON d.TABLE_NAME = r.TABLE_NAME
                        GROUP BY d.BUSINESS_DOMAIN, d.PRIORITY, d.OWNER, d.TARGET_DATE
                        ORDER BY d.PRIORITY, pct_complete
                    """).to_pandas())
                    st.session_state["mc_exec_domain"] = df_domain
                except Exception:
                    # No domains table yet — show overall only with a prompt to configure
                    st.session_state["mc_exec_domain"] = pd.DataFrame()

                # Velocity — how many tables passing per day over last 14 days
                try:
                    df_velocity = normalize_df(session.sql(f"""
                        SELECT DATE_TRUNC('day', RECON_DATE) AS recon_day,
                               COUNT(DISTINCT TABLE_NAME) AS tables_checked,
                               SUM(CASE WHEN STATUS='PASS' THEN 1 ELSE 0 END) AS tables_passed
                        FROM {RECON_TABLE}
                        WHERE RECON_DATE >= DATEADD('day', -14, CURRENT_TIMESTAMP())
                        GROUP BY recon_day ORDER BY recon_day
                    """).to_pandas())
                    st.session_state["mc_exec_velocity"] = df_velocity
                except Exception:
                    st.session_state["mc_exec_velocity"] = pd.DataFrame()

        # ── Render executive view ──────────────────────────────────────────────
        if st.session_state.get("mc_exec_overall") is not None and not st.session_state["mc_exec_overall"].empty:
            df_o = st.session_state["mc_exec_overall"]
            row  = df_o.iloc[0]

            total    = int(row.get("TOTAL_TABLES", 0))
            passed   = int(row.get("PASSED",       0))
            failed   = int(row.get("FAILED",       0))
            pct      = float(row.get("PCT_COMPLETE", 0))
            last_run = str(row.get("LAST_RUN",""))[:10]

            # Hero metric bar
            st.markdown("### Overall Migration Status")
            bar_color = "#4ade80" if pct >= 90 else ("#fbbf24" if pct >= 70 else "#f87171")
            st.markdown(f"""
            <div style="background:rgba(15,23,42,0.5);border:1px solid rgba(56,189,248,0.15);
                        border-radius:12px;padding:24px;margin:8px 0;">
                <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px;">
                    <span style="font-size:1.1rem;font-weight:700;color:#e2e8f0;">
                        Teradata → Snowflake Migration
                    </span>
                    <span style="font-size:2rem;font-weight:800;color:{bar_color};">{pct:.1f}%</span>
                </div>
                <div style="background:#1e293b;border-radius:6px;height:12px;overflow:hidden;">
                    <div style="background:{bar_color};height:100%;width:{min(pct,100):.1f}%;
                                border-radius:6px;transition:width 0.5s;"></div>
                </div>
                <div style="display:flex;gap:24px;margin-top:12px;font-size:0.8rem;color:#94a3b8;">
                    <span>✅ {passed} tables passing</span>
                    <span>❌ {failed} failing</span>
                    <span>📋 {total} total</span>
                    <span>📅 Last run: {last_run}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Project completion forecast
            df_vel = st.session_state.get("mc_exec_velocity", pd.DataFrame())
            if not df_vel.empty and "TABLES_PASSED" in df_vel.columns:
                avg_daily = float(df_vel["TABLES_PASSED"].mean())
                remaining = total - passed
                if avg_daily > 0 and remaining > 0:
                    days_left = remaining / avg_daily
                    from datetime import timedelta
                    est_complete = (datetime.now() + timedelta(days=days_left)).strftime("%B %d, %Y")
                    st.info(
                        f"📅 At the current pace of **{avg_daily:.0f} tables/day**, "
                        f"migration is projected to complete on **{est_complete}** "
                        f"({days_left:.0f} days from today)."
                    )
                elif remaining == 0:
                    st.success("🎉 All tables have passed reconciliation!")

            # Domain breakdown
            df_dom = st.session_state.get("mc_exec_domain", pd.DataFrame())
            if not df_dom.empty:
                st.subheader("Progress by Business Domain")
                for _, drow in df_dom.iterrows():
                    domain  = drow.get("BUSINESS_DOMAIN", "Unknown")
                    dpct    = float(drow.get("PCT_COMPLETE", 0) or 0)
                    dtotal  = int(drow.get("TOTAL_TABLES", 0))
                    dpassed = int(drow.get("PASSED", 0))
                    dfailed = int(drow.get("FAILED", 0))
                    dtarget = str(drow.get("TARGET_DATE",""))[:10]
                    owner   = drow.get("OWNER","")
                    priority = drow.get("PRIORITY","")

                    dcolor = "#4ade80" if dpct >= 90 else ("#fbbf24" if dpct >= 70 else "#f87171")
                    priority_badge = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(str(priority).upper(), "")

                    st.markdown(f"""
                    <div style="background:rgba(15,23,42,0.4);border:1px solid rgba(56,189,248,0.1);
                                border-radius:8px;padding:16px;margin:6px 0;">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                            <span style="font-weight:700;color:#e2e8f0;">{priority_badge} {domain}</span>
                            <span style="font-size:1.1rem;font-weight:700;color:{dcolor};">{dpct:.0f}%</span>
                        </div>
                        <div style="background:#1e293b;border-radius:4px;height:6px;margin-bottom:8px;">
                            <div style="background:{dcolor};height:100%;width:{min(dpct,100):.0f}%;border-radius:4px;"></div>
                        </div>
                        <div style="font-size:0.75rem;color:#64748b;display:flex;gap:16px;">
                            <span>✅ {dpassed}/{dtotal} tables</span>
                            <span>❌ {dfailed} failing</span>
                            {"<span>🎯 Target: " + dtarget + "</span>" if dtarget and dtarget != "None" else ""}
                            {"<span>👤 " + owner + "</span>" if owner else ""}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                download_csv(df_dom, "migration_domain_progress.csv")
            else:
                st.info(
                    "💡 Domain-level breakdown is not configured yet. "
                    "Create the MIGRATION_DOMAINS table using the Setup DDL above, "
                    "then map your tables to business domains (Claims, Policy, Finance, etc.)."
                )

            # Velocity chart
            if not df_vel.empty:
                st.subheader("Daily Validation Velocity (last 14 days)")
                st.bar_chart(df_vel.set_index("RECON_DAY")["TABLES_PASSED"])

    # ── ROI SCORECARD (NEW) ───────────────────────────────────────────────────
    with tab_roi:
        st.header("💰 OVERWATCH ROI Scorecard")
        st.caption(
            "Tracks realized savings from recommendations that were acted on. "
            "Log a saving below when a recommendation is implemented — "
            "OVERWATCH verifies the before/after delta automatically where possible."
        )

        # Setup DDL
        roi_ddl = f"""-- OVERWATCH ROI Log — tracks cost savings from acted-on recommendations
CREATE TABLE IF NOT EXISTS {ROI_TABLE} (
    ROI_ID           NUMBER AUTOINCREMENT PRIMARY KEY,
    LOGGED_DATE      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    LOGGED_BY        VARCHAR(200) DEFAULT CURRENT_USER(),
    CATEGORY         VARCHAR(100),   -- Cost | Performance | Reliability | Storage
    DESCRIPTION      VARCHAR(1000),
    ENTITY           VARCHAR(500),   -- warehouse/user/table acted on
    BASELINE_CREDITS FLOAT,          -- credits/day before the change
    CURRENT_CREDITS  FLOAT,          -- credits/day after the change (auto-filled if available)
    SAVINGS_CREDITS  FLOAT,          -- GENERATED: baseline - current
    SAVINGS_MONTHLY  FLOAT,          -- GENERATED: savings * 30 * credit_price
    VERIFIED         BOOLEAN DEFAULT FALSE,
    NOTES            VARCHAR(2000)
);"""
        with st.expander("📋 ROI Table Setup DDL"):
            st.code(roi_ddl, language="sql")
            st.download_button(
                "📥 Download DDL", roi_ddl,
                file_name="overwatch_roi_setup.sql", mime="text/plain", key="roi_ddl_dl"
            )

        st.divider()

        # ── Aggregate scorecard ────────────────────────────────────────────────
        if st.button("Load ROI Scorecard", key="roi_load"):
            try:
                df_roi = normalize_df(session.sql(f"""
                    SELECT CATEGORY,
                           COUNT(*)                             AS action_count,
                           SUM(SAVINGS_CREDITS * 30)           AS monthly_credit_savings,
                           SUM(SAVINGS_MONTHLY)                AS monthly_dollar_savings,
                           SUM(SAVINGS_MONTHLY * 12)           AS projected_annual_savings,
                           SUM(CASE WHEN VERIFIED THEN 1 ELSE 0 END) AS verified_count
                    FROM {ROI_TABLE}
                    GROUP BY CATEGORY
                    ORDER BY monthly_dollar_savings DESC
                """).to_pandas())
                st.session_state["mc_roi_summary"] = df_roi

                df_roi_detail = normalize_df(session.sql(f"""
                    SELECT ROI_ID, LOGGED_DATE, CATEGORY, DESCRIPTION, ENTITY,
                           BASELINE_CREDITS, CURRENT_CREDITS, SAVINGS_CREDITS,
                           SAVINGS_MONTHLY, VERIFIED, NOTES
                    FROM {ROI_TABLE}
                    ORDER BY LOGGED_DATE DESC LIMIT 200
                """).to_pandas())
                st.session_state["mc_roi_detail"] = df_roi_detail

            except Exception as e:
                st.info(f"ROI table not found — run setup DDL first. ({e})")
                st.session_state["mc_roi_summary"] = pd.DataFrame()

        if st.session_state.get("mc_roi_summary") is not None:
            df_s = st.session_state["mc_roi_summary"]

            if not df_s.empty:
                total_monthly  = float(df_s["MONTHLY_DOLLAR_SAVINGS"].sum())
                total_annual   = float(df_s["PROJECTED_ANNUAL_SAVINGS"].sum())
                total_actions  = int(df_s["ACTION_COUNT"].sum())
                total_verified = int(df_s["VERIFIED_COUNT"].sum())

                # Hero metrics
                st.markdown("### Total Savings Attributed to OVERWATCH")
                h1, h2, h3, h4 = st.columns(4)
                h1.metric("Monthly Savings",          f"${total_monthly:,.2f}")
                h2.metric("Projected Annual Savings",  f"${total_annual:,.2f}")
                h3.metric("Actions Implemented",       f"{total_actions}")
                h4.metric("Verified Savings",          f"{total_verified}")

                # Savings gauge vs estimated OVERWATCH cost
                overwatch_monthly_cost = credits_to_dollars(
                    30 * 24 * 1,  # ~1 credit/hour for SYSTEM$STREAMLIT WH
                    credit_price
                )
                roi_ratio = total_monthly / overwatch_monthly_cost if overwatch_monthly_cost > 0 else 0
                st.markdown(f"""
                <div style="background:rgba(52,211,153,0.08);border:1px solid rgba(52,211,153,0.3);
                            border-radius:12px;padding:20px;margin:12px 0;text-align:center;">
                    <div style="font-size:0.75rem;color:#64748b;text-transform:uppercase;letter-spacing:1px;">
                        Return on Investment
                    </div>
                    <div style="font-size:2.5rem;font-weight:800;color:#4ade80;margin:8px 0;">
                        {roi_ratio:.1f}×
                    </div>
                    <div style="font-size:0.85rem;color:#94a3b8;">
                        OVERWATCH est. cost: ${overwatch_monthly_cost:,.2f}/month &nbsp;·&nbsp;
                        Savings: ${total_monthly:,.2f}/month
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Savings by category
                st.subheader("Savings by Category")
                st.bar_chart(df_s.set_index("CATEGORY")["MONTHLY_DOLLAR_SAVINGS"])
                st.dataframe(df_s, use_container_width=True)

                # Detail log
                if st.session_state.get("mc_roi_detail") is not None and not st.session_state["mc_roi_detail"].empty:
                    st.subheader("Savings Log")
                    st.dataframe(st.session_state["mc_roi_detail"], use_container_width=True)
                    download_csv(st.session_state["mc_roi_detail"], "overwatch_roi_log.csv")
            else:
                st.info("No ROI entries logged yet. Log your first saving below.")

        # ── Log a new saving ───────────────────────────────────────────────────
        st.divider()
        st.subheader("➕ Log a Realized Saving")
        st.caption(
            "Record a recommendation that was acted on. "
            "Enter the credit/day before and after — OVERWATCH calculates the monthly dollar saving."
        )

        with st.form("roi_form"):
            r1, r2 = st.columns(2)
            with r1:
                roi_category = st.selectbox(
                    "Category",
                    ["Cost", "Performance", "Reliability", "Storage", "Security"],
                    key="roi_cat"
                )
                roi_entity = st.text_input("Entity (warehouse/user/table name)", key="roi_entity")
                roi_baseline = st.number_input(
                    "Baseline credits/day (before)", min_value=0.0, value=0.0, step=0.1, key="roi_baseline"
                )
                roi_current  = st.number_input(
                    "Current credits/day (after)",  min_value=0.0, value=0.0, step=0.1, key="roi_current"
                )
            with r2:
                roi_desc  = st.text_input("Description of change", key="roi_desc",
                                           placeholder="e.g. Reduced AUTO_SUSPEND on WH_ALFA_LOAD from 600s to 60s")
                roi_notes = st.text_area("Notes (optional)", height=80, key="roi_notes")
                roi_verified = st.checkbox("Mark as verified (confirmed in production)", key="roi_verified")

            submitted = st.form_submit_button("💾 Save Saving", type="primary")

        if submitted and roi_entity and roi_desc:
            savings_cr  = max(roi_baseline - roi_current, 0)
            savings_mon = round(savings_cr * 30 * credit_price, 2)

            try:
                esc = lambda v: str(v or "").replace("'","''")[:500]
                session.sql(f"""
                    INSERT INTO {ROI_TABLE}
                        (CATEGORY, DESCRIPTION, ENTITY, BASELINE_CREDITS,
                         CURRENT_CREDITS, SAVINGS_CREDITS, SAVINGS_MONTHLY, VERIFIED, NOTES)
                    VALUES (
                        '{esc(roi_category)}', '{esc(roi_desc)}', '{esc(roi_entity)}',
                        {roi_baseline}, {roi_current}, {savings_cr},
                        {savings_mon}, {str(roi_verified).upper()}, '{esc(roi_notes)}'
                    )
                """).collect()
                st.success(
                    f"✅ Saved! This change saves **{savings_cr:.2f} credits/day** "
                    f"= **${savings_mon:,.2f}/month** (${savings_mon*12:,.0f}/year)."
                )
                # Clear cached summary so it reloads
                st.session_state.pop("mc_roi_summary", None)
                st.session_state.pop("mc_roi_detail",  None)
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")
                st.info("Run the setup DDL above first.")

        # ── Auto-verify from warehouse metering ────────────────────────────────
        st.divider()
        st.subheader("🔍 Auto-Verify Savings")
        st.caption(
            "Select a warehouse and a before/after date — OVERWATCH pulls actual metering "
            "data to verify the saving is real."
        )
        av1, av2, av3 = st.columns(3)
        with av1:
            verify_wh = st.text_input("Warehouse to verify", key="av_wh",
                                       placeholder="WH_ALFA_LOAD")
        with av2:
            verify_before = st.date_input("Baseline period end",   key="av_before")
        with av3:
            verify_after  = st.date_input("Current period start",  key="av_after")

        if verify_wh and st.button("Verify", key="av_run"):
            wh_safe = safe_sql(verify_wh)
            try:
                df_av = normalize_df(session.sql(f"""
                    SELECT
                        AVG(CASE WHEN DATE_TRUNC('day',start_time) <= '{verify_before}'
                                 THEN credits_used END) AS baseline_daily,
                        AVG(CASE WHEN DATE_TRUNC('day',start_time) >= '{verify_after}'
                                 THEN credits_used END) AS current_daily
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE warehouse_name = '{wh_safe}'
                      AND start_time >= DATEADD('day', -90, CURRENT_TIMESTAMP())
                """).to_pandas())
                if not df_av.empty:
                    bl  = float(df_av["BASELINE_DAILY"].iloc[0] or 0)
                    cur = float(df_av["CURRENT_DAILY"].iloc[0]  or 0)
                    sav = max(bl - cur, 0) * 30 * credit_price
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Baseline daily credits",  f"{bl:.2f}")
                    c2.metric("Current daily credits",   f"{cur:.2f}")
                    c3.metric("Verified monthly saving", f"${sav:,.2f}")
                    if sav > 0:
                        st.success(f"✅ Verified: **${sav:,.2f}/month** saving on {verify_wh}")
                    else:
                        st.info("No improvement detected between the two periods.")
            except Exception as e:
                st.error(f"Verification failed: {e}")
