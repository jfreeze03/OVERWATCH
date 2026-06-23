# sections/dba_tools_cortex_limits_view.py - Cortex AI account limit render branch.

import pandas as pd
import streamlit as st

from sections.dba_tools_common import (
    _current_role_allows_alter_account,
    _require_typed_confirmation,
    _typed_confirmation,
)
from sections.shell_helpers import render_shell_snapshot
from utils import (
    admin_button_disabled,
    download_csv,
    format_snowflake_error,
    run_query,
    run_query_or_raise,
    safe_float,
    safe_int,
)
from utils.workflows import render_priority_dataframe


def _cortex_parameter_queries() -> list[str]:
    return [
        "SHOW PARAMETERS LIKE '%CORTEX%' IN ACCOUNT",
        "SHOW PARAMETERS LIKE '%AI%' IN ACCOUNT",
    ]


def _cortex_usage_today_sql() -> str:
    return """
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
    """


def _cortex_code_quota_sql(limit: int) -> str:
    daily_limit = int(limit)
    if daily_limit <= 0:
        return (
            "-- Cortex Code quota\n"
            "-- No account-change statement generated. Set a positive daily limit to generate quota SQL."
        )
    return (
        "-- Cortex Code quota\n"
        "-- Run as ACCOUNTADMIN\n"
        f"ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = {daily_limit};"
    )


def _cortex_apply_statement(limit: int) -> str:
    return f"ALTER ACCOUNT SET CORTEX_CODE_DAILY_CREDIT_LIMIT = {int(limit)}"


def _cortex_readiness_rows() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "CAPABILITY": "Cortex Code",
            "DASHBOARD_ACTION": "Set daily account credit limit",
            "READINESS_PATH": "Account parameter when available in SHOW PARAMETERS",
        },
        {
            "CAPABILITY": "Cortex Search",
            "DASHBOARD_ACTION": "Review grants and service objects",
            "READINESS_PATH": "Create/search service readiness and role grants outside generic account parameters",
        },
        {
            "CAPABILITY": "Cortex Analyst / Intelligence",
            "DASHBOARD_ACTION": "Review semantic model, object grants, and approved roles",
            "READINESS_PATH": "Feature and object readiness outside generic account parameters",
        },
    ])


def _can_apply_cortex_limit(role: str, limit: int) -> tuple[bool, str]:
    if int(limit) <= 0:
        return False, "Set a positive Cortex Code daily credit limit before applying."
    current_role = str(role or "").strip()
    if not _current_role_allows_alter_account(current_role):
        return (
            False,
            f"ALTER ACCOUNT requires ACCOUNTADMIN. "
            f"Your current role is `{current_role or 'unknown'}`. "
            f"Switch to ACCOUNTADMIN in Snowflake and reload OVERWATCH, "
            f"or ask an ACCOUNTADMIN owner to apply the approved account parameter change.",
        )
    return True, ""


def render_cortex_ai_limits_tool(session, company: str) -> None:
    st.subheader("Cortex AI Limits")
    st.caption(
        "View and modify Cortex AI service limits for your account. "
        "These control daily token thresholds, inference rate limits, and Cortex Search/Analyst access. "
        "Requires ACCOUNTADMIN or SYSADMIN with MODIFY ACCOUNT privilege."
    )

    if st.button("Load Current AI Parameters", key="cortex_params_load"):
        results = {}
        param_queries = _cortex_parameter_queries()

        try:
            df_params = run_query_or_raise(param_queries[0])
            results["cortex_params"] = df_params
        except Exception as e:
            results["cortex_params"] = pd.DataFrame()
            st.caption(f"Account parameters unavailable: {format_snowflake_error(e)}")

        try:
            df_ai = run_query_or_raise(param_queries[1])
            results["ai_params"] = df_ai
        except Exception:
            results["ai_params"] = pd.DataFrame()

        try:
            df_usage = run_query(
                _cortex_usage_today_sql(),
                ttl_key=f"dba_cortex_usage_today_{company}",
                tier="live",
            )
            results["usage_today"] = df_usage
        except Exception:
            results["usage_today"] = pd.DataFrame()

        st.session_state["dba_cortex_results"] = results

    res = st.session_state.get("dba_cortex_results", {})

    df_u = res.get("usage_today", pd.DataFrame())
    if not df_u.empty:
        st.subheader("Today's Cortex Usage")
        render_shell_snapshot((
            ("Requests Today", f"{safe_int(df_u['REQUESTS_TODAY'].iloc[0]):,}"),
            ("AI Credits Today", f"{safe_float(df_u['CREDITS_TODAY'].iloc[0]):.4f}"),
            ("Tokens Today", f"{safe_int(df_u['TOKENS_TODAY'].iloc[0]):,}"),
            ("Active Users", f"{safe_int(df_u['ACTIVE_USERS'].iloc[0])}"),
        ))

    df_cp = res.get("cortex_params", pd.DataFrame())
    df_ai = res.get("ai_params", pd.DataFrame())

    combined_params = pd.concat([df_cp, df_ai], ignore_index=True) if not df_cp.empty or not df_ai.empty else pd.DataFrame()
    if not combined_params.empty:
        st.subheader("Current Cortex / AI Account Parameters")
        render_priority_dataframe(
            combined_params,
            title="Cortex / AI account parameters",
            priority_columns=[
                "key", "value", "default", "level", "description",
                "KEY", "VALUE", "DEFAULT", "LEVEL", "DESCRIPTION",
            ],
            sort_by=["KEY", "key"],
            ascending=True,
            raw_label="All Cortex account parameters",
        )
        download_csv(combined_params, "cortex_account_params.csv")
    else:
        st.info(
            "No Cortex parameters returned from SHOW PARAMETERS. "
            "This usually means Cortex AI features are not yet enabled on this account, "
            "or the current role doesn't have SHOW PARAMETERS privilege on ACCOUNT."
        )

    st.divider()
    st.subheader("Modify Cortex AI Account Parameters")
    st.caption(
        "Only account parameters returned by Snowflake can be applied here. "
        "Cortex Search, Analyst, and Intelligence access are managed through feature availability, "
        "roles, databases, services, and Snowflake readiness evidence rather than generic account toggles."
    )

    with st.expander("Set Cortex Code quota", expanded=True):
        cortex_daily_limit = st.number_input(
            "CORTEX_CODE_DAILY_CREDIT_LIMIT",
            min_value=0, max_value=100000, value=0, step=100,
            key="cortex_daily_limit",
            help="Maximum Cortex Code credits per day across all users. Use 0 to skip SQL generation.",
        )
        generated_sql = _cortex_code_quota_sql(cortex_daily_limit)
        st.code(generated_sql, language="sql")

        render_priority_dataframe(
            _cortex_readiness_rows(),
            title="Cortex feature readiness guidance",
            priority_columns=["CAPABILITY", "DASHBOARD_ACTION", "READINESS_PATH"],
            raw_label="All Cortex readiness guidance",
        )

        col_apply, col_dl = st.columns([1, 2])
        with col_apply:
            cortex_confirmed = _typed_confirmation(
                "Type APPLY to enable account parameter changes",
                "APPLY",
                "cortex_apply_confirm",
            )
            if st.button("Apply Limit", type="primary", key="cortex_apply", disabled=admin_button_disabled()):
                if _require_typed_confirmation(cortex_confirmed, "APPLY"):
                    _caller_role = str(st.session_state.get("_overwatch_current_role", "") or "").strip()
                    can_apply, blocker = _can_apply_cortex_limit(_caller_role, cortex_daily_limit)
                    if not can_apply:
                        if cortex_daily_limit <= 0:
                            st.info(blocker)
                            st.stop()
                        st.error(blocker)
                    else:
                        applied = []
                        failed = []
                        for stmt in [_cortex_apply_statement(cortex_daily_limit)]:
                            try:
                                session.sql(stmt).collect()
                                applied.append(stmt)
                            except Exception as e:
                                failed.append(f"{stmt} -> {format_snowflake_error(e)}")

                        if applied:
                            st.success(f"{len(applied)} parameter(s) updated successfully.")
                        if failed:
                            for f_msg in failed:
                                st.warning(f"{f_msg}")
                            st.info("Check SHOW PARAMETERS IN ACCOUNT and confirm the current role can modify account parameters.")
        with col_dl:
            render_shell_snapshot((
                ("Account limit", "Status review"),
                ("Apply path", "reviewed workflow"),
                ("Rollback", "Runbook only"),
                ("Telemetry", "Parameter review"),
            ))

    st.divider()
    st.subheader("Per-User / Per-Role Cortex Access and Quotas")
    st.caption(
        "Use shared AI spend thresholds and route Cortex access through a controlled role "
        "when per-user monthly quota enforcement is required."
    )
    st.info(
        "Tip: To enforce user quotas, revoke the blanket `SNOWFLAKE.CORTEX_USER` grant from PUBLIC, "
        "grant it only through an approved AI role, then use OVERWATCH to queue revoke/restore review."
    )
    with st.expander("Cortex access control status"):
        render_shell_snapshot((
            ("Approved AI role", "Required"),
            ("PUBLIC access", "Review"),
            ("Quota enforcement", "Dry-run first"),
            ("Parameter review", "On demand"),
        ))
