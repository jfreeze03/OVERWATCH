# sections/snowflake_value.py - Snowflake optimization value scorecard
import streamlit as st

from config import ETL_AUDIT_DB, ETL_AUDIT_SCHEMA
from utils import (
    format_snowflake_error,
    get_active_company,
    get_session,
    credits_to_dollars,
    download_csv,
    run_query,
    safe_identifier,
    sql_literal,
)


VALUE_TABLE = (
    f"{safe_identifier(ETL_AUDIT_DB)}."
    f"{safe_identifier(ETL_AUDIT_SCHEMA)}."
    f"{safe_identifier('OVERWATCH_ROI_LOG')}"
)


def _value_table_has_company(session) -> bool:
    try:
        row = session.sql(f"""
            SELECT COUNT(*) AS CNT
            FROM {safe_identifier(ETL_AUDIT_DB)}.INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = {sql_literal(ETL_AUDIT_SCHEMA.upper())}
              AND TABLE_NAME = 'OVERWATCH_ROI_LOG'
              AND COLUMN_NAME = 'COMPANY'
        """).collect()[0]
        return int(row["CNT"]) > 0
    except Exception:
        return False


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)
    company = get_active_company()

    st.header("Snowflake Value")
    st.caption(
        "Track verified Snowflake optimization wins from warehouse tuning, query fixes, storage cleanup, "
        "task tuning, and other OVERWATCH recommendations."
    )

    ddl = f"""-- OVERWATCH Snowflake Value Log
CREATE TABLE IF NOT EXISTS {VALUE_TABLE} (
    ROI_ID           NUMBER AUTOINCREMENT PRIMARY KEY,
    LOGGED_DATE      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    LOGGED_BY        VARCHAR(200),
    CATEGORY         VARCHAR(100),
    DESCRIPTION      VARCHAR(1000),
    ENTITY           VARCHAR(500),
    BASELINE_CREDITS FLOAT,
    CURRENT_CREDITS  FLOAT,
    SAVINGS_CREDITS  FLOAT,
    SAVINGS_MONTHLY  FLOAT,
    VERIFIED         BOOLEAN DEFAULT FALSE,
    COMPANY          VARCHAR(50),
    NOTES            VARCHAR(2000)
);

ALTER TABLE {VALUE_TABLE} ADD COLUMN IF NOT EXISTS COMPANY VARCHAR(50);"""
    with st.expander("Setup DDL"):
        st.code(ddl, language="sql")
        st.download_button(
            "Download DDL",
            ddl,
            file_name="overwatch_snowflake_value_setup.sql",
            mime="text/plain",
            key="sf_value_ddl_download",
        )

    if st.button("Load Snowflake Value", key="sf_value_load"):
        try:
            has_company = _value_table_has_company(session)
            company_filter = ""
            company_select = "'ALFA' AS COMPANY,"
            if has_company:
                company_select = "COALESCE(COMPANY, 'ALFA') AS COMPANY,"
                if company != "ALL":
                    company_filter = f"WHERE COALESCE(COMPANY, 'ALFA') = {sql_literal(company)}"
            elif company == "Trexis":
                company_filter = "WHERE 1=0"
            df_summary = run_query(f"""
                SELECT CATEGORY,
                       COUNT(*) AS action_count,
                       ROUND(SUM(SAVINGS_CREDITS * 30), 2) AS monthly_credit_savings,
                       ROUND(SUM(SAVINGS_MONTHLY), 2) AS monthly_dollar_savings,
                       ROUND(SUM(SAVINGS_MONTHLY * 12), 2) AS projected_annual_savings,
                       SUM(CASE WHEN VERIFIED THEN 1 ELSE 0 END) AS verified_count
                FROM {VALUE_TABLE}
                {company_filter}
                GROUP BY CATEGORY
                ORDER BY monthly_dollar_savings DESC
            """, ttl_key=f"snowflake_value_summary_{company}", tier="historical")
            df_detail = run_query(f"""
                SELECT ROI_ID, LOGGED_DATE, {company_select} CATEGORY, DESCRIPTION, ENTITY,
                       BASELINE_CREDITS, CURRENT_CREDITS, SAVINGS_CREDITS,
                       SAVINGS_MONTHLY, VERIFIED, NOTES
                FROM {VALUE_TABLE}
                {company_filter}
                ORDER BY LOGGED_DATE DESC
                LIMIT 500
            """, ttl_key=f"snowflake_value_detail_{company}", tier="historical")
            st.session_state["sf_value_summary"] = df_summary
            st.session_state["sf_value_detail"] = df_detail
            st.session_state["sf_value_app_cost"] = None
        except Exception as e:
            st.info(f"Snowflake value table not found. Run the setup DDL first. ({format_snowflake_error(e)})")
            st.session_state["sf_value_summary"] = None
            st.session_state["sf_value_detail"] = None

    df_summary = st.session_state.get("sf_value_summary")
    if df_summary is not None:
        if df_summary.empty:
            st.info("No Snowflake optimization value has been logged yet.")
        else:
            total_monthly = float(df_summary["MONTHLY_DOLLAR_SAVINGS"].sum())
            total_annual = float(df_summary["PROJECTED_ANNUAL_SAVINGS"].sum())
            total_actions = int(df_summary["ACTION_COUNT"].sum())
            total_verified = int(df_summary["VERIFIED_COUNT"].sum())
            df_app_cost = st.session_state.get("sf_value_app_cost")
            app_credits = 0.0
            app_warehouse = "current app warehouse"
            if df_app_cost is not None and not df_app_cost.empty:
                app_credits = float(df_app_cost.iloc[0].get("APP_CREDITS_30D") or 0)
                app_warehouse = str(df_app_cost.iloc[0].get("APP_WAREHOUSE") or app_warehouse)
            monthly_app_cost = credits_to_dollars(app_credits, credit_price)
            if monthly_app_cost <= 0:
                monthly_app_cost = credits_to_dollars(30 * 24 * 1, credit_price)
                app_warehouse = "estimated 24x7 X-Small fallback"
            value_ratio = total_monthly / monthly_app_cost if monthly_app_cost > 0 else 0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Monthly Value", f"${total_monthly:,.2f}")
            c2.metric("Annualized Value", f"${total_annual:,.2f}")
            c3.metric("Actions Logged", f"{total_actions:,}")
            c4.metric("Verified Actions", f"{total_verified:,}")

            st.metric(
                "Snowflake Value Multiple",
                f"{value_ratio:.1f}x",
                help=f"Monthly logged value divided by measured 30-day OVERWATCH runtime cost for {app_warehouse}; uses a fallback estimate if unavailable.",
            )
            st.bar_chart(df_summary.set_index("CATEGORY")["MONTHLY_DOLLAR_SAVINGS"])
            st.dataframe(df_summary, use_container_width=True)
            download_csv(df_summary, "snowflake_value_summary.csv")

            df_detail = st.session_state.get("sf_value_detail")
            if df_detail is not None and not df_detail.empty:
                st.subheader("Value Log")
                st.dataframe(df_detail, use_container_width=True)
                download_csv(df_detail, "snowflake_value_log.csv")

    st.divider()
    st.subheader("Log Snowflake Optimization Value")
    with st.form("sf_value_form"):
        f1, f2 = st.columns(2)
        with f1:
            category = st.selectbox(
                "Category",
                [
                    "Warehouse right-sizing",
                    "Auto-suspend tuning",
                    "Query optimization",
                    "Task/serverless tuning",
                    "Storage cleanup",
                    "Data sharing/egress",
                    "Cortex/AI optimization",
                    "Other Snowflake optimization",
                ],
                key="sf_value_category",
            )
            entity = st.text_input("Snowflake object or owner", key="sf_value_entity")
            baseline = st.number_input("Baseline credits/day", min_value=0.0, value=0.0, step=0.1, key="sf_value_baseline")
            current = st.number_input("Current credits/day", min_value=0.0, value=0.0, step=0.1, key="sf_value_current")
        with f2:
            description = st.text_input(
                "Optimization made",
                placeholder="Example: reduced WH_ALFA_ETL auto-suspend from 600s to 60s",
                key="sf_value_description",
            )
            notes = st.text_area("Proof / notes", height=90, key="sf_value_notes")
            verified = st.checkbox("Verified in production", key="sf_value_verified")

        submitted = st.form_submit_button("Save Value", type="primary")

    if submitted and entity and description:
        savings_credits = max(float(baseline) - float(current), 0)
        savings_monthly = round(savings_credits * 30 * credit_price, 2)
        actor = str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")
        try:
            if _value_table_has_company(session):
                session.sql(f"""
                    INSERT INTO {VALUE_TABLE}
                        (LOGGED_BY, CATEGORY, DESCRIPTION, ENTITY, BASELINE_CREDITS,
                         CURRENT_CREDITS, SAVINGS_CREDITS, SAVINGS_MONTHLY, VERIFIED, COMPANY, NOTES)
                    VALUES (
                        {sql_literal(actor, 200)}, {sql_literal(category, 100)}, {sql_literal(description)}, {sql_literal(entity, 500)},
                        {float(baseline)}, {float(current)}, {savings_credits},
                        {savings_monthly}, {str(bool(verified)).upper()}, {sql_literal(company, 50)}, {sql_literal(notes, 2000)}
                    )
                """).collect()
            else:
                session.sql(f"""
                    INSERT INTO {VALUE_TABLE}
                        (LOGGED_BY, CATEGORY, DESCRIPTION, ENTITY, BASELINE_CREDITS,
                         CURRENT_CREDITS, SAVINGS_CREDITS, SAVINGS_MONTHLY, VERIFIED, NOTES)
                    VALUES (
                        {sql_literal(actor, 200)}, {sql_literal(category, 100)}, {sql_literal(description)}, {sql_literal(entity, 500)},
                        {float(baseline)}, {float(current)}, {savings_credits},
                        {savings_monthly}, {str(bool(verified)).upper()}, {sql_literal(notes, 2000)}
                    )
                """).collect()
            st.success(f"Saved ${savings_monthly:,.2f}/month in tracked Snowflake value.")
            st.session_state.pop("sf_value_summary", None)
            st.session_state.pop("sf_value_detail", None)
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save Snowflake value: {format_snowflake_error(e)}")
            st.info("Run the setup DDL above first.")
