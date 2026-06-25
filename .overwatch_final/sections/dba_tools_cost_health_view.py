# sections/dba_tools_cost_health_view.py - Read-only DBA cost and health render branches.

import pandas as pd
import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA
from sections.dba_tools_setup import _setup_status_df, _table_exists
from sections.shell_helpers import render_shell_snapshot
from utils import (
    build_cost_formula_audit,
    build_schema_migration_contract,
    build_schema_migration_status_sql,
    build_unclassified_assets_sql,
    day_window_selectbox,
    defer_source_note,
    download_csv,
    format_credits,
    format_snowflake_error,
    get_active_company,
    render_chart_with_data_toggle,
    run_compatibility_checks,
    run_query,
)
from sections.chart_helpers import render_area_time_series_chart
from utils.workflows import render_priority_dataframe



def render_summary_status_tool(session, company: str) -> None:
    st.subheader("Summary Status")
    st.caption(
        "Checks whether the Snowflake summary facts are available for fast dashboards."
    )
    mart_objects = [
        ("Control Room Snapshot", "MART_DBA_CONTROL_ROOM"),
        ("Query Detail", "FACT_QUERY_DETAIL"),
        ("Warehouse Daily", "FACT_WAREHOUSE_DAILY"),
        ("Task Runs", "FACT_TASK_RUN"),
        ("Login Daily", "FACT_LOGIN_DAILY"),
        ("Object Changes", "FACT_OBJECT_CHANGE"),
    ]
    rows = []
    for label, table_name in mart_objects:
        exists = _table_exists(session, ALERT_DB, ALERT_SCHEMA, table_name)
        rows.append({
            "FEATURE": label,
            "OBJECT_NAME": f"{ALERT_DB}.{ALERT_SCHEMA}.{table_name}",
            "STATUS": "Present" if exists is True else "Missing" if exists is False else "Unknown",
        })
    mart_df = pd.DataFrame(rows)
    present_count = int((mart_df["STATUS"] == "Present").sum())
    missing_count = int((mart_df["STATUS"] == "Missing").sum())
    render_shell_snapshot((
        ("Present", f"{present_count:,}"),
        ("Missing", f"{missing_count:,}"),
    ))
    summary_display = mart_df.drop(columns=["OBJECT_NAME"], errors="ignore")
    render_priority_dataframe(
        summary_display,
        title="Summary fact readiness",
        priority_columns=["FEATURE", "STATUS"],
        sort_by=["STATUS", "FEATURE"],
        ascending=[True, True],
        raw_label="All summary readiness rows",
    )
    if missing_count:
        st.info("Summary facts are not available yet. Ask the DBA team to refresh the Snowflake objects, then recheck.")


def render_serverless_costs_tool(session, company: str) -> None:
    st.subheader("Serverless Costs")
    if get_active_company() != "ALL":
        st.info(
            "Serverless metering is account-level in Snowflake and does not expose "
            "a reliable company, database, user, or warehouse dimension here. Switch "
            "Company View to ALL to review account-wide serverless costs."
        )
    else:
        sv_days = day_window_selectbox("Lookback", key="sv_days", default=30)
        if st.button("Load Serverless Costs", key="sv_load"):
            try:
                st.session_state["dba_df_serverless"] = run_query(f"""
                    SELECT service_type, DATE_TRUNC('day', start_time) AS usage_date,
                           SUM(credits_used) AS daily_credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
                    WHERE start_time >= DATEADD('day', -{sv_days}, CURRENT_TIMESTAMP())
                      AND service_type NOT IN ('WAREHOUSE_METERING','WAREHOUSE_METERING_READER')
                    GROUP BY service_type, usage_date ORDER BY daily_credits DESC
                """, ttl_key=f"dba_serverless_{company}_{sv_days}", tier="standard")
            except Exception as e:
                st.warning(f"Serverless costs unavailable: {format_snowflake_error(e)}")
        if st.session_state.get("dba_df_serverless") is not None and not st.session_state["dba_df_serverless"].empty:
            df_sv = st.session_state["dba_df_serverless"]
            svc   = df_sv.groupby("SERVICE_TYPE")["DAILY_CREDITS"].sum().reset_index().sort_values("DAILY_CREDITS", ascending=False)
            render_shell_snapshot((("Total Serverless Credits", format_credits(float(svc["DAILY_CREDITS"].sum()))),))
            render_priority_dataframe(
                svc,
                title="Serverless service cost drivers",
                priority_columns=["SERVICE_TYPE", "DAILY_CREDITS"],
                sort_by=["DAILY_CREDITS"],
                ascending=False,
                raw_label="All serverless service totals",
            )
            render_chart_with_data_toggle(
                "Serverless credits trend",
                "dba_serverless_credits_trend",
                lambda: render_area_time_series_chart(
                    df_sv,
                    "USAGE_DATE",
                    "DAILY_CREDITS",
                    series_column="SERVICE_TYPE",
                    title="Serverless credits trend",
                ),
                df_sv,
                priority_columns=["USAGE_DATE", "SERVICE_TYPE", "DAILY_CREDITS"],
                sort_by=["USAGE_DATE", "DAILY_CREDITS"],
                ascending=[False, False],
                raw_label="All serverless daily rows",
            )
            download_csv(df_sv, "serverless_costs.csv")


def render_cost_formula_audit_tool(session, company: str) -> None:
    st.subheader("Cost Formula Audit")
    st.caption(
        "Documents which OVERWATCH cost numbers reconcile to Snowflake billing "
        "sources and which are allocation or forecast estimates."
    )

    audit_df = build_cost_formula_audit()
    exact_count = int(audit_df["CONFIDENCE"].str.contains("Exact", case=False, na=False).sum())
    estimate_count = int(audit_df["CONFIDENCE"].str.contains("estimate|forecast|mixed|allocated", case=False, na=False).sum())
    rows_count = len(audit_df)
    render_shell_snapshot((
        ("Formula Checks", f"{rows_count:,}"),
        ("Source-of-Truth", f"{exact_count:,}"),
        ("Estimated / Allocated", f"{estimate_count:,}"),
    ))

    audit_view = audit_df.rename(columns={"CONFIDENCE": "MEASUREMENT_BASIS"})
    render_priority_dataframe(
        audit_view,
        title="Cost formula validation",
        priority_columns=[
            "METRIC",
            "PARITY_STATUS",
            "MEASUREMENT_BASIS",
            "SOURCE_DASHBOARD_FORMULA",
            "FORMULA",
            "NOTES",
            "NEXT_REVIEW",
        ],
        sort_by=["PARITY_STATUS", "METRIC"],
        ascending=[True, True],
        raw_label="All formula checks",
    )
    download_csv(audit_df, "overwatch_cost_formula_audit.csv")

    st.subheader("Reconciliation Checks")
    st.caption(
        "Use Snowflake billing, warehouse metering, and action-queue evidence when leadership asks why a number changed."
    )
    render_shell_snapshot((
        ("Warehouse metering", "Billing-aligned"),
        ("Account services", "Completed windows"),
        ("Currency view", "When billing access exists"),
        ("Chargeback", "Allocated / estimated"),
    ))


def render_data_health_tool(session, company: str) -> None:
    st.subheader("Data Health")
    st.caption("Release health checks for access, persistent objects, formulas, and operational coverage.")
    defer_source_note(
        "Run Data Health before release promotion to check Snowflake view access, optional account columns, "
        "persistent objects, formula validation, and operational coverage."
    )

    st.subheader("Snowflake Compatibility Check")
    defer_source_note(
        "Validates required ACCOUNT_USAGE views, optional columns that vary by account, "
        "and SHOW commands used by DBA operations."
    )
    if st.button("Run Compatibility Check", key="compatibility_check_load"):
        st.session_state["dba_compatibility_status"] = run_compatibility_checks(session)

    if st.session_state.get("dba_compatibility_status") is not None:
        compat_df = st.session_state["dba_compatibility_status"]
        if not compat_df.empty:
            ready_count = int((compat_df["STATUS"] == "Ready").sum())
            limited_count = int((compat_df["STATUS"] == "Limited").sum())
            blocked_count = int((~compat_df["STATUS"].isin(["Ready", "Limited"])).sum())
            render_shell_snapshot((
                ("Ready", f"{ready_count:,}"),
                ("Limited", f"{limited_count:,}"),
                ("Blocked", f"{blocked_count:,}"),
            ))
            render_priority_dataframe(
                compat_df,
                title="Compatibility checks needing attention",
                priority_columns=["CATEGORY", "CHECK", "STATUS", "USED_BY", "DETAIL", "IMPACT"],
                sort_by=["STATUS", "CATEGORY"],
                ascending=[True, True],
                raw_label="All compatibility checks",
            )
            download_csv(compat_df, "overwatch_compatibility_check.csv")

            blocked = compat_df[~compat_df["STATUS"].isin(["Ready", "Limited"])]
            if not blocked.empty:
                st.warning(
                    "Some checks are blocked. Affected sections should show graceful "
                    "limited-data messages instead of crashing."
                )

    st.divider()
    st.subheader("Company Scope Audit")
    defer_source_note(
        "Find warehouses and databases that are not matched to the ALFA or Trexis allowlists. "
        "Review this before widening company filters."
    )
    if st.button("Load Unclassified Assets", key="scope_audit_load"):
        st.session_state["dba_unclassified_assets"] = run_query(
            build_unclassified_assets_sql(30),
            ttl_key=f"dba_scope_audit_{company}",
            tier="standard",
            section="Change & Drift",
        )
    unclassified = st.session_state.get("dba_unclassified_assets")
    if unclassified is not None:
        if unclassified.empty:
            st.success("No unclassified warehouses or databases found in the last 30 days.")
        else:
            wh_count = int((unclassified["OBJECT_TYPE"] == "WAREHOUSE").sum()) if "OBJECT_TYPE" in unclassified.columns else 0
            db_count = int((unclassified["OBJECT_TYPE"] == "DATABASE").sum()) if "OBJECT_TYPE" in unclassified.columns else 0
            render_shell_snapshot((
                ("Unclassified Warehouses", f"{wh_count:,}"),
                ("Unclassified Databases", f"{db_count:,}"),
            ))
            render_priority_dataframe(
                unclassified,
                title="Unclassified scope assets",
                priority_columns=["OBJECT_TYPE", "OBJECT_NAME", "DATABASE_NAME", "WAREHOUSE_NAME", "LAST_SEEN"],
                sort_by=["OBJECT_TYPE", "OBJECT_NAME"],
                ascending=[True, True],
                raw_label="All unclassified assets",
            )
            download_csv(unclassified, "overwatch_unclassified_assets.csv")

    st.divider()
    st.subheader("Persistent Data Objects")

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("Check Data Health", key="setup_status_load"):
            st.session_state["dba_setup_status"] = _setup_status_df(session)
    with c2:
        st.info("Snowflake object status is owned by the DBA platform team for this environment.")
        defer_source_note(
            f"Review object availability in {ALERT_DB}.{ALERT_SCHEMA} and confirm alert task route context before enabling actions."
        )

    if st.session_state.get("dba_setup_status") is not None:
        status_df = st.session_state["dba_setup_status"]
        missing_count = int((status_df["STATUS"] == "Missing").sum())
        unknown_count = int((status_df["STATUS"] == "Unknown").sum())

        render_shell_snapshot((
            ("Objects Checked", f"{len(status_df):,}"),
            ("Missing", f"{missing_count:,}"),
            ("Unknown", f"{unknown_count:,}"),
        ))
        status_display = status_df.drop(columns=["OBJECT_NAME"], errors="ignore")
        render_priority_dataframe(
            status_display,
            title="Persistent data health",
            priority_columns=["FEATURE", "STATUS"],
            sort_by=["STATUS", "FEATURE"],
            ascending=[True, True],
            raw_label="All data-health objects",
        )

    st.divider()
    st.subheader("Persistent Data Refresh Status")
    defer_source_note(
        "The migration ledger compares expected status version to the deployed summary version."
    )
    c_mig_load, c_mig_hint = st.columns([1, 2])
    with c_mig_load:
        if st.button("Check Refresh Status", key="schema_migration_status_load", width="stretch"):
            try:
                st.session_state["dba_schema_migration_status"] = run_query(
                    build_schema_migration_status_sql(),
                    ttl_key="dba_schema_migration_status",
                    tier="recent",
                    section="Change & Drift",
                )
                st.session_state["dba_schema_migration_status_error"] = ""
            except Exception as exc:
                st.session_state["dba_schema_migration_status"] = pd.DataFrame()
                st.session_state["dba_schema_migration_status_error"] = format_snowflake_error(exc)
    with c_mig_hint:
        st.info("Use this before release promotion or after the DBA team refreshes status objects.")

    migration_status = st.session_state.get("dba_schema_migration_status")
    migration_error = st.session_state.get("dba_schema_migration_status_error", "")
    if migration_error:
        st.warning("Migration ledger is not available yet.")
        defer_source_note(migration_error)
    if isinstance(migration_status, pd.DataFrame) and not migration_status.empty:
        blockers = int(migration_status["MIGRATION_STATE"].astype(str).isin(["Blocked", "Version Drift"]).sum())
        render_shell_snapshot((
            ("Migration Rows", f"{len(migration_status):,}"),
            ("Blockers", f"{blockers:,}"),
        ))
        migration_display = migration_status.drop(
            columns=["OBJECT_NAME", "REQUIRED_VERSION", "DEPLOYED_VERSION"],
            errors="ignore",
        )
        render_priority_dataframe(
            migration_display,
            title="Deployed mart migration status",
            priority_columns=[
                "COMPONENT", "OBJECT_STATE", "LATEST_APPLIED_AT", "MIGRATION_STATE", "NEXT_ACTION",
            ],
            sort_by=["MIGRATION_STATE", "COMPONENT"],
            ascending=[True, True],
            raw_label="All migration status rows",
        )
    else:
        render_priority_dataframe(
            build_schema_migration_contract(),
            title="Expected readiness contract",
            priority_columns=[
                "COMPONENT", "WHY_IT_MATTERS", "READY_CRITERIA",
            ],
            raw_label="All expected readiness rows",
        )

    st.divider()
    st.subheader("Cost Formula Validation")
    cost_formula_df = build_cost_formula_audit()
    cost_formula_view = cost_formula_df.rename(columns={"CONFIDENCE": "MEASUREMENT_BASIS"})
    render_priority_dataframe(
        cost_formula_view,
        title="Cost formula validation",
        priority_columns=[
            "METRIC",
            "PARITY_STATUS",
            "MEASUREMENT_BASIS",
            "SOURCE_DASHBOARD_FORMULA",
            "FORMULA",
            "NOTES",
            "NEXT_REVIEW",
        ],
        sort_by=["PARITY_STATUS", "METRIC"],
        ascending=[True, True],
        raw_label="All formula checks",
    )

    st.info("Persistent object changes are owned by the DBA platform release process, outside the dashboard.")
