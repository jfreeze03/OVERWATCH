# sections/snowflake_value.py - Snowflake optimization value scorecard
import streamlit as st

from config import DEFAULTS, ETL_AUDIT_DB, ETL_AUDIT_SCHEMA
from sections.shell_helpers import render_shell_snapshot, with_loaded_at
from utils import (
    build_snowflake_value_automation_health_sql,
    build_snowflake_value_candidate_sql,
    format_snowflake_error,
    get_active_company,
    get_session,
    download_csv,
    render_ranked_bar_chart,
    run_query,
    safe_float,
    safe_identifier,
    sql_literal,
)
from utils.workflows import render_priority_dataframe


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


def _load_snowflake_value_state(session, company: str, *, show_errors: bool = True) -> bool:
    try:
        has_company = _value_table_has_company(session)
        company_filter = ""
        company_select = "NULL::VARCHAR AS COMPANY,"
        if has_company:
            company_select = "COMPANY,"
            if company != "ALL":
                company_filter = f"WHERE COMPANY = {sql_literal(company)}"
        elif company == "Trexis":
            company_filter = "WHERE 1=0"
        df_summary = run_query(f"""
            SELECT CATEGORY,
                   COUNT(*) AS action_count,
                   ROUND(SUM(SAVINGS_CREDITS * 30), 2) AS est_30_day_credit_savings,
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
        st.session_state["sf_value_meta"] = with_loaded_at({"company": company}, source="Value ledger")
        return True
    except Exception as e:
        st.session_state["sf_value_summary"] = None
        st.session_state["sf_value_detail"] = None
        if show_errors:
            st.info(f"Snowflake Value logging is not available in this environment yet. Ask the DBA team to enable it, then retry. ({format_snowflake_error(e)})")
        return False


def _load_snowflake_value_automation_state(company: str, *, show_errors: bool = True) -> bool:
    try:
        health = run_query(
            build_snowflake_value_automation_health_sql(),
            ttl_key=f"snowflake_value_automation_health_{company}",
            tier="recent",
            section="Snowflake Value",
        )
        candidates = run_query(
            build_snowflake_value_candidate_sql(limit=100),
            ttl_key=f"snowflake_value_candidates_{company}",
            tier="recent",
            section="Snowflake Value",
        )
        st.session_state["sf_value_automation_health"] = health
        st.session_state["sf_value_automation_candidates"] = candidates
        st.session_state["sf_value_automation_error"] = ""
        st.session_state["sf_value_automation_meta"] = with_loaded_at(
            {"company": company},
            source="Automated value capture",
        )
        return True
    except Exception as exc:
        st.session_state["sf_value_automation_health"] = None
        st.session_state["sf_value_automation_candidates"] = None
        st.session_state["sf_value_automation_error"] = format_snowflake_error(exc)
        if show_errors:
            st.info(
                "Automated value capture is not available in this environment yet. "
                f"Ask the DBA team to enable it, then retry. ({format_snowflake_error(exc)})"
            )
        return False


def _render_value_automation_contract() -> None:
    import pandas as pd

    st.markdown("**Automated Value Capture**")
    render_priority_dataframe(
        pd.DataFrame([
            {
                "VALUE_SIGNAL": "Verified cost action",
                "SIGNAL_SOURCE": "verified action queue",
                "VALUE_STATE": "Verified savings",
                "CAPTURE_RULE": "Closed actions with measured savings are eligible for value logging.",
                "WHY_IT_MATTERS": "Keeps monthly value reporting tied to completed DBA work.",
            },
            {
                "VALUE_SIGNAL": "Resolved alert with value at risk",
                "SIGNAL_SOURCE": "Alert remediation history",
                "VALUE_STATE": "Risk avoided",
                "CAPTURE_RULE": "Resolved critical cost, reliability, or security alerts can be valued when impact is known.",
                "WHY_IT_MATTERS": "Shows incident-prevention value, not just hard-dollar savings.",
            },
            {
                "VALUE_SIGNAL": "Workload recovery",
                "SIGNAL_SOURCE": "Recovery audit trail",
                "VALUE_STATE": "Reliability value",
                "CAPTURE_RULE": "Recovered task, procedure, and workload incidents can be logged after verification.",
                "WHY_IT_MATTERS": "Connects operator work to avoided business interruption.",
            },
            {
                "VALUE_SIGNAL": "Query optimization",
                "SIGNAL_SOURCE": "Query diagnosis and approved actions",
                "VALUE_STATE": "Candidate savings",
                "CAPTURE_RULE": "Before/after query telemetry remains candidate value until confirmed.",
                "WHY_IT_MATTERS": "Separates estimated opportunity from proven monthly value.",
            },
        ]),
        title="Value signals ready for DBA review",
        priority_columns=[
            "VALUE_SIGNAL", "SIGNAL_SOURCE", "VALUE_STATE",
            "CAPTURE_RULE", "WHY_IT_MATTERS",
        ],
        raw_label="All value capture signals",
        height=240,
        max_rows=4,
    )


def _render_value_automation_health(company: str) -> None:
    if st.button("Load Value Automation Telemetry", key="sf_value_automation_load", width="stretch"):
        _load_snowflake_value_automation_state(company, show_errors=True)

    health = st.session_state.get("sf_value_automation_health")
    candidates = st.session_state.get("sf_value_automation_candidates")
    err = st.session_state.get("sf_value_automation_error", "")
    if health is None:
        render_shell_snapshot((
            ("Candidates", "On demand"),
            ("Verified Candidates", "On demand"),
            ("Candidate Value", "On demand"),
            ("Ledger Rows", "On demand"),
        ))
        if err:
            st.caption(f"Automation telemetry unavailable for this role/context: {err}")
        else:
            st.caption("Value automation health loads only when requested; scheduled Snowflake capture owns recurring refresh.")
        return
    if health.empty:
        st.info("Value automation health view returned no rows.")
    else:
        row = health.iloc[0]
        render_shell_snapshot((
            ("Candidates", f"{int(row.get('CANDIDATE_COUNT', 0) or 0):,}"),
            ("Verified Candidates", f"{int(row.get('VERIFIED_CANDIDATE_COUNT', 0) or 0):,}"),
            ("Candidate Value", f"${safe_float(row.get('CANDIDATE_MONTHLY_VALUE')):,.0f}/mo"),
            ("Ledger Rows", f"{int(row.get('AUTOMATED_LEDGER_ROWS', 0) or 0):,}"),
        ))
        next_action = str(row.get("NEXT_ACTION") or "Review value automation health.")
        next_action = (
            next_action
            .replace("OVERWATCH_VALUE_AUTOMATION_RUN", "automation run history")
            .replace("OVERWATCH_VALUE_CANDIDATE_V", "value candidates")
            .replace("OVERWATCH_ROI_LOG", "value ledger")
            .replace("SP_OVERWATCH_AUTOMATE_VALUE_LOG", "the value capture job")
        )
        st.caption(next_action)
        health_display = health.copy()
        if "NEXT_ACTION" in health_display.columns:
            health_display["NEXT_ACTION"] = health_display["NEXT_ACTION"].astype(str).map(
                lambda value: value.replace("OVERWATCH_VALUE_AUTOMATION_RUN", "automation run history")
                .replace("OVERWATCH_VALUE_CANDIDATE_V", "value candidates")
                .replace("OVERWATCH_ROI_LOG", "value ledger")
                .replace("SP_OVERWATCH_AUTOMATE_VALUE_LOG", "the value capture job")
            )
        render_priority_dataframe(
            health_display,
            title="Value automation health",
            priority_columns=[
                "CANDIDATE_COUNT", "VERIFIED_CANDIDATE_COUNT",
                "CANDIDATE_MONTHLY_VALUE", "VERIFIED_CANDIDATE_MONTHLY_VALUE",
                "AUTOMATED_LEDGER_ROWS", "VERIFIED_LEDGER_ROWS",
                "LATEST_RUN_TS", "LATEST_RUN_STATUS", "NEXT_ACTION",
            ],
            raw_label="All value automation health fields",
            height=180,
            max_rows=1,
        )
    if candidates is not None and not candidates.empty:
        candidate_columns = [
            col for col in [
                "CATEGORY", "ENTITY", "OWNER", "SAVINGS_MONTHLY", "VALUE_STATE",
                "BUSINESS_IMPACT",
            ] if col in candidates.columns
        ]
        candidates_display = candidates[candidate_columns].copy()
        render_priority_dataframe(
            candidates_display,
            title="Current automated value candidates",
            priority_columns=candidate_columns,
            sort_by=["VALUE_STATE", "SAVINGS_MONTHLY"],
            ascending=[False, False],
            raw_label="All value automation candidates",
            height=260,
            max_rows=10,
        )
        download_csv(candidates, "snowflake_value_automation_candidates.csv")


def render():
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])
    company = get_active_company()

    st.subheader("Snowflake Value")
    st.caption(
        "Track confirmed Snowflake optimization, reliability, and incident-prevention wins from telemetry. "
        "Scheduled Snowflake capture is the preferred path for action and alert status."
    )

    _render_value_automation_contract()
    _render_value_automation_health(company)

    if st.button("Load Snowflake Value", key="sf_value_load"):
        session = get_session()
        _load_snowflake_value_state(session, company, show_errors=True)

    df_summary = st.session_state.get("sf_value_summary")
    if df_summary is None:
        render_shell_snapshot((
            ("Monthly Value", "On demand"),
            ("Annualized Value", "On demand"),
            ("Actions Logged", "On demand"),
            ("Verified Actions", "On demand"),
            ("Verified Rate", "On demand"),
            ("Value Capture", "On demand"),
        ))
        st.caption("Load Snowflake Value when ledger rows are needed. Automated capture should run in Snowflake so DBAs do not have to maintain recurring updates.")
    else:
        if df_summary.empty:
            st.info("No Snowflake optimization value has been logged yet.")
        else:
            total_monthly = float(df_summary["MONTHLY_DOLLAR_SAVINGS"].sum())
            total_annual = float(df_summary["PROJECTED_ANNUAL_SAVINGS"].sum())
            total_actions = int(df_summary["ACTION_COUNT"].sum())
            total_verified = int(df_summary["VERIFIED_COUNT"].sum())
            verified_rate = (total_verified / total_actions) if total_actions else 0

            render_shell_snapshot((
                ("Monthly Value", f"${total_monthly:,.2f}"),
                ("Annualized Value", f"${total_annual:,.2f}"),
                ("Actions Logged", f"{total_actions:,}"),
                ("Verified Actions", f"{total_verified:,}"),
                ("Verified Rate", f"{verified_rate:.0%}" if total_actions else "Not measured"),
                ("Value Capture", "Verified" if total_verified else "Needs review"),
            ))
            render_ranked_bar_chart(
                df_summary,
                "CATEGORY",
                "MONTHLY_DOLLAR_SAVINGS",
                title="Value By Category",
                top_n=20,
            )
            render_priority_dataframe(
                df_summary,
                title="Value categories by monthly savings",
                priority_columns=[
                    "CATEGORY", "ACTION_COUNT", "EST_30_DAY_CREDIT_SAVINGS",
                    "MONTHLY_DOLLAR_SAVINGS", "PROJECTED_ANNUAL_SAVINGS",
                    "VERIFIED_COUNT",
                ],
                sort_by=["MONTHLY_DOLLAR_SAVINGS", "PROJECTED_ANNUAL_SAVINGS"],
                ascending=[False, False],
                raw_label="All Snowflake value category rows",
            )
            download_csv(df_summary, "snowflake_value_summary.csv")

            df_detail = st.session_state.get("sf_value_detail")
            if df_detail is not None and not df_detail.empty:
                st.subheader("Value Log")
                render_priority_dataframe(
                    df_detail,
                    title="Logged optimizations",
                    priority_columns=[
                        "ROI_ID", "LOGGED_DATE", "COMPANY", "CATEGORY", "ENTITY",
                        "SAVINGS_CREDITS", "SAVINGS_MONTHLY", "VERIFIED", "DESCRIPTION",
                    ],
                    sort_by=["VERIFIED", "SAVINGS_MONTHLY", "LOGGED_DATE"],
                    ascending=[True, False, False],
                    raw_label="All Snowflake value log rows",
                )
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
            entity = st.text_input("Snowflake object or route", key="sf_value_entity")
            baseline = st.number_input("Baseline credits/day", min_value=0.0, value=0.0, step=0.1, key="sf_value_baseline")
            current = st.number_input("Current credits/day", min_value=0.0, value=0.0, step=0.1, key="sf_value_current")
        with f2:
            description = st.text_input(
                "Optimization made",
                placeholder="Example: reduced WH_ALFA_ETL auto-suspend from 600s to 60s",
                key="sf_value_description",
            )
            notes = st.text_area("Notes", height=90, key="sf_value_notes")
            verified = st.checkbox("Verified in production", key="sf_value_verified")

        submitted = st.form_submit_button("Save Value", type="primary")

    if submitted and entity and description:
        savings_credits = max(float(baseline) - float(current), 0)
        savings_monthly = round(savings_credits * 30 * credit_price, 2)
        actor = str(st.session_state.get("_overwatch_actor", "OVERWATCH") or "OVERWATCH")
        try:
            session = get_session()
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
            st.info("Snowflake Value logging is not available in this environment yet. Ask the DBA team to enable it, then retry.")
