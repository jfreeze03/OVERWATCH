# sections/snowflake_value.py - Snowflake optimization value scorecard
import streamlit as st

from config import ETL_AUDIT_DB, ETL_AUDIT_SCHEMA
from utils import get_session, normalize_df, credits_to_dollars, download_csv


VALUE_TABLE = f"{ETL_AUDIT_DB}.{ETL_AUDIT_SCHEMA}.OVERWATCH_ROI_LOG"


def _esc(value: object, limit: int = 1000) -> str:
    return str(value or "").replace("'", "''")[:limit]


def render():
    session = get_session()
    credit_price = st.session_state.get("credit_price", 3.00)

    st.header("Snowflake Value")
    st.caption(
        "Track verified Snowflake optimization wins from warehouse tuning, query fixes, storage cleanup, "
        "task tuning, and other OVERWATCH recommendations."
    )

    ddl = f"""-- OVERWATCH Snowflake Value Log
CREATE TABLE IF NOT EXISTS {VALUE_TABLE} (
    ROI_ID           NUMBER AUTOINCREMENT PRIMARY KEY,
    LOGGED_DATE      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    LOGGED_BY        VARCHAR(200) DEFAULT CURRENT_USER(),
    CATEGORY         VARCHAR(100),
    DESCRIPTION      VARCHAR(1000),
    ENTITY           VARCHAR(500),
    BASELINE_CREDITS FLOAT,
    CURRENT_CREDITS  FLOAT,
    SAVINGS_CREDITS  FLOAT,
    SAVINGS_MONTHLY  FLOAT,
    VERIFIED         BOOLEAN DEFAULT FALSE,
    NOTES            VARCHAR(2000)
);"""
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
            df_summary = normalize_df(session.sql(f"""
                SELECT CATEGORY,
                       COUNT(*) AS action_count,
                       ROUND(SUM(SAVINGS_CREDITS * 30), 2) AS monthly_credit_savings,
                       ROUND(SUM(SAVINGS_MONTHLY), 2) AS monthly_dollar_savings,
                       ROUND(SUM(SAVINGS_MONTHLY * 12), 2) AS projected_annual_savings,
                       SUM(CASE WHEN VERIFIED THEN 1 ELSE 0 END) AS verified_count
                FROM {VALUE_TABLE}
                GROUP BY CATEGORY
                ORDER BY monthly_dollar_savings DESC
            """).to_pandas())
            df_detail = normalize_df(session.sql(f"""
                SELECT ROI_ID, LOGGED_DATE, CATEGORY, DESCRIPTION, ENTITY,
                       BASELINE_CREDITS, CURRENT_CREDITS, SAVINGS_CREDITS,
                       SAVINGS_MONTHLY, VERIFIED, NOTES
                FROM {VALUE_TABLE}
                ORDER BY LOGGED_DATE DESC
                LIMIT 500
            """).to_pandas())
            st.session_state["sf_value_summary"] = df_summary
            st.session_state["sf_value_detail"] = df_detail
        except Exception as e:
            st.info(f"Snowflake value table not found. Run the setup DDL first. ({e})")
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
            monthly_app_cost = credits_to_dollars(30 * 24 * 1, credit_price)
            value_ratio = total_monthly / monthly_app_cost if monthly_app_cost > 0 else 0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Monthly Value", f"${total_monthly:,.2f}")
            c2.metric("Annualized Value", f"${total_annual:,.2f}")
            c3.metric("Actions Logged", f"{total_actions:,}")
            c4.metric("Verified Actions", f"{total_verified:,}")

            st.metric("Snowflake Value Multiple", f"{value_ratio:.1f}x", help="Monthly logged value divided by estimated OVERWATCH runtime cost.")
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
        try:
            session.sql(f"""
                INSERT INTO {VALUE_TABLE}
                    (CATEGORY, DESCRIPTION, ENTITY, BASELINE_CREDITS,
                     CURRENT_CREDITS, SAVINGS_CREDITS, SAVINGS_MONTHLY, VERIFIED, NOTES)
                VALUES (
                    '{_esc(category, 100)}', '{_esc(description)}', '{_esc(entity, 500)}',
                    {float(baseline)}, {float(current)}, {savings_credits},
                    {savings_monthly}, {str(bool(verified)).upper()}, '{_esc(notes, 2000)}'
                )
            """).collect()
            st.success(f"Saved ${savings_monthly:,.2f}/month in tracked Snowflake value.")
            st.session_state.pop("sf_value_summary", None)
            st.session_state.pop("sf_value_detail", None)
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save Snowflake value: {e}")
            st.info("Run the setup DDL above first.")
