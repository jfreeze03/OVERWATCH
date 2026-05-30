# sections/security_posture.py - Consolidated security and access workflow
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections import data_sharing, security_access
from utils import (
    build_action_queue_ddl,
    filter_existing_columns,
    format_snowflake_error,
    get_active_company,
    get_db_filter_clause,
    get_session,
    get_user_filter_clause,
    make_action_id,
    run_query,
    safe_float,
    safe_int,
    upsert_actions,
)
from utils.workflows import render_signal_confidence, render_workflow_guide, render_workflow_selector

WORKFLOWS = ("Access posture", "Data sharing exposure")


def _security_score(
    *,
    failed_logins: int,
    failed_users: int,
    users_without_mfa: int,
    active_users: int,
    recent_grants: int,
    shared_databases: int,
) -> int:
    """Weighted DBA posture score; failures and MFA gaps matter more than volume."""
    active_users = max(safe_int(active_users), 1)
    failed_login_penalty = min(25, safe_float(failed_logins) * 0.25 + safe_float(failed_users) * 2)
    mfa_penalty = min(35, (safe_float(users_without_mfa) / active_users) * 100)
    grant_penalty = min(20, safe_float(recent_grants) * 1.5)
    exposure_penalty = min(20, safe_float(shared_databases) * 3)
    return max(0, min(100, int(round(100 - failed_login_penalty - mfa_penalty - grant_penalty - exposure_penalty))))


def _security_rating(score: int) -> str:
    if score >= 95:
        return "Strong"
    if score >= 85:
        return "Watch"
    if score >= 70:
        return "Elevated"
    return "High Risk"


def _security_action_for(finding_type: str) -> tuple[str, str, str]:
    value = str(finding_type or "").lower()
    if "failed login" in value:
        return (
            "User/Auth",
            "Validate whether attempts are expected; compare with IAM logs, source IP, and recent changes before locking or disabling the user.",
            "-- Proof: LOGIN_HISTORY grouped by user, source IP, client, and error code.",
        )
    if "mfa" in value:
        return (
            "User/Auth",
            "Confirm the user authentication path, then enforce MFA through Snowflake or the identity provider.",
            "-- Proof: ACCOUNT_USAGE.USERS MFA/ext_authn_duo signal.",
        )
    if "grant" in value:
        return (
            "Grant/Role",
            "Confirm the grant owner, business justification, and role hierarchy before revoking or narrowing access.",
            "-- Proof: ACCOUNT_USAGE.GRANTS_TO_USERS active grants created in the selected window.",
        )
    if "shared" in value or "database exposure" in value:
        return (
            "Shared Data",
            "Validate the consumer, owner, contract, and data classification before leaving the share active.",
            "-- Proof: ACCOUNT_USAGE.DATABASES imported/share metadata.",
        )
    return (
        "User/Access",
        "Validate with IAM/Snowflake history, confirm owner, then remediate access or authentication configuration.",
        "-- Review proof query and owner before revoking grants, disabling users, or enforcing MFA.",
    )


def _build_security_brief_markdown(
    *,
    company: str,
    days: int,
    score: int,
    summary_row,
    exceptions: pd.DataFrame,
) -> str:
    failed_logins = safe_int(summary_row.get("FAILED_LOGINS", 0))
    failed_users = safe_int(summary_row.get("FAILED_USERS", 0))
    active_users = safe_int(summary_row.get("ACTIVE_USERS", 0))
    users_without_mfa = safe_int(summary_row.get("USERS_WITHOUT_MFA", 0))
    recent_grants = safe_int(summary_row.get("RECENT_GRANTS", 0))
    shared_databases = safe_int(summary_row.get("SHARED_DATABASES", 0))
    exception_lines = []
    if exceptions is not None and not exceptions.empty:
        for _, row in exceptions.head(10).iterrows():
            exception_lines.append(
                f"- {row.get('SEVERITY', 'Medium')}: {row.get('FINDING_TYPE', 'Security finding')} "
                f"for {row.get('ENTITY', 'Unknown')} ({safe_int(row.get('EVENT_COUNT', 0))} events)."
            )
    else:
        exception_lines.append("- No security exceptions crossed the configured thresholds.")
    lines = [
        f"# OVERWATCH Security Brief - {company}",
        "",
        f"Lookback window: {days} day(s).",
        f"Security score: {score} ({_security_rating(score)}).",
        "",
        "## Key Metrics",
        f"- Active users: {active_users:,}",
        f"- Failed logins: {failed_logins:,} across {failed_users:,} user(s)",
        f"- Users without MFA signal: {users_without_mfa:,}",
        f"- Recent active grants: {recent_grants:,}",
        f"- Shared/imported databases: {shared_databases:,}",
        "",
        "## Exceptions",
        *exception_lines,
        "",
        "## DBA Follow-Up",
        "- Validate failed-login spikes against IAM and network context.",
        "- Prioritize MFA gaps before lower-risk grant cleanup.",
        "- Review shared/imported databases with the data owner and contract context.",
        "- Save material findings to the OVERWATCH Action Queue for status tracking.",
        "",
        "## Confidence",
        "Source: SNOWFLAKE.ACCOUNT_USAGE. Company scope uses user/database naming where Snowflake does not expose direct company ownership.",
    ]
    return "\n".join(lines)


def _build_security_summary_sql(session, days: int, company: str) -> tuple[str, str]:
    user_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.USERS",
        ["EXT_AUTHN_DUO", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
    ))
    mfa_count_expr = (
        "COUNT_IF(COALESCE(TO_VARCHAR(ext_authn_duo), 'false') <> 'true')"
        if "EXT_AUTHN_DUO" in user_cols else "NULL::NUMBER"
    )
    password_count_expr = (
        "COUNT_IF(COALESCE(TO_VARCHAR(has_password), 'false') = 'true')"
        if "HAS_PASSWORD" in user_cols else "NULL::NUMBER"
    )
    last_seen_expr = "u.last_success_login" if "LAST_SUCCESS_LOGIN" in user_cols else "u.created_on"
    user_filter_lh = get_user_filter_clause("lh.user_name")
    user_filter_u = get_user_filter_clause("u.name")
    user_filter_g = get_user_filter_clause("g.grantee_name")
    db_filter = get_db_filter_clause("d.database_name")
    summary_sql = f"""
    WITH login_events AS (
        SELECT
            COUNT(*) AS login_events,
            COUNT_IF(lh.is_success = 'NO') AS failed_logins,
            COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.user_name, NULL)) AS failed_users,
            COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.client_ip, NULL)) AS failed_ips
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
        WHERE lh.event_timestamp >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {user_filter_lh}
    ),
    users AS (
        SELECT
            COUNT(*) AS active_users,
            {mfa_count_expr} AS users_without_mfa,
            {password_count_expr} AS password_users
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TO_VARCHAR(u.disabled), 'false') = 'false'
          {user_filter_u}
    ),
    recent_grants AS (
        SELECT COUNT(*) AS recent_grants
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
        WHERE g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {user_filter_g}
    ),
    shared_dbs AS (
        SELECT COUNT(*) AS shared_databases
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES d
        WHERE d.deleted IS NULL
          AND d.type IN ('IMPORTED DATABASE', 'SHARE')
          {db_filter}
    )
    SELECT
        '{company}' AS company,
        login_events.login_events,
        login_events.failed_logins,
        login_events.failed_users,
        login_events.failed_ips,
        users.active_users,
        users.users_without_mfa,
        users.password_users,
        recent_grants.recent_grants,
        shared_dbs.shared_databases
    FROM login_events, users, recent_grants, shared_dbs
    """
    exceptions_sql = f"""
    WITH failed_logins AS (
        SELECT
            'Failed Login' AS finding_type,
            IFF(COUNT(*) >= 25 OR COUNT(DISTINCT client_ip) >= 5, 'High', 'Medium') AS severity,
            user_name AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT client_ip) AS distinct_sources,
            MAX(event_timestamp) AS last_seen,
            'LOGIN_HISTORY failed login attempts by user/IP' AS proof_query
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
        WHERE lh.event_timestamp >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND lh.is_success = 'NO'
          {user_filter_lh}
        GROUP BY user_name
        HAVING COUNT(*) >= 3
    ),
    mfa_gaps AS (
        SELECT
            'MFA Gap' AS finding_type,
            'High' AS severity,
            u.name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            COALESCE({last_seen_expr}, u.created_on) AS last_seen,
            'ACCOUNT_USAGE.USERS ext_authn_duo signal' AS proof_query
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TO_VARCHAR(u.disabled), 'false') = 'false'
          {user_filter_u}
          {"AND COALESCE(TO_VARCHAR(u.ext_authn_duo), 'false') <> 'true'" if "EXT_AUTHN_DUO" in user_cols else "AND 1 = 0"}
    ),
    recent_grants AS (
        SELECT
            'Recent Grant' AS finding_type,
            IFF(COUNT(*) >= 10, 'Medium', 'Low') AS severity,
            g.grantee_name AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT g.role) AS distinct_sources,
            MAX(g.created_on) AS last_seen,
            'ACCOUNT_USAGE.GRANTS_TO_USERS active grants created recently' AS proof_query
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
        WHERE g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {user_filter_g}
        GROUP BY g.grantee_name
        HAVING COUNT(*) >= 3
    ),
    shared_exposure AS (
        SELECT
            'Shared Database Exposure' AS finding_type,
            'Medium' AS severity,
            d.database_name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            d.created AS last_seen,
            'ACCOUNT_USAGE.DATABASES imported database/share metadata' AS proof_query
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES d
        WHERE d.deleted IS NULL
          AND d.type IN ('IMPORTED DATABASE', 'SHARE')
          {db_filter}
    )
    SELECT * FROM failed_logins
    UNION ALL
    SELECT * FROM mfa_gaps
    UNION ALL
    SELECT * FROM recent_grants
    UNION ALL
    SELECT * FROM shared_exposure
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        event_count DESC,
        last_seen DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def _queue_security_exceptions(session, exceptions: pd.DataFrame) -> None:
    if exceptions is None or exceptions.empty:
        st.info("No security exceptions to queue.")
        return
    company = get_active_company()
    actions = []
    for _, row in exceptions.head(100).iterrows():
        finding_type = str(row.get("FINDING_TYPE") or "Security Finding")
        entity = str(row.get("ENTITY") or "Unknown")
        severity = str(row.get("SEVERITY") or "Medium")
        event_count = safe_int(row.get("EVENT_COUNT", 0))
        finding = f"{finding_type}: {entity} has {event_count} event(s) requiring review"
        entity_type, action, generated_sql = _security_action_for(finding_type)
        actions.append({
            "Action ID": make_action_id("Security Posture", entity, finding),
            "Source": "Security Posture - Security Brief",
            "Severity": severity,
            "Category": "Security",
            "Entity Type": entity_type,
            "Entity": entity,
            "Owner": "Security/DBA",
            "Finding": finding,
            "Action": action,
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": generated_sql,
            "Proof Query": str(row.get("PROOF_QUERY") or "Security Posture proof query."),
            "Company": company,
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} security exceptions to the action queue.")
    except Exception as e:
        st.error(f"Could not save security exceptions: {format_snowflake_error(e)}")
        st.download_button(
            "Download Action Queue DDL",
            build_action_queue_ddl(),
            file_name="overwatch_action_queue_setup.sql",
            mime="text/plain",
            key="security_posture_action_queue_ddl",
        )


def render() -> None:
    session = get_session()
    company = get_active_company()
    if st.session_state.get("exceptions_only_mode") and "security_posture_workflow" not in st.session_state:
        st.session_state["security_posture_workflow"] = "Access posture"
    st.header("Security Posture")
    st.caption(
        "One DBA workflow for login posture, MFA, grants, exfiltration signals, "
        "data lineage, and shared-data exposure."
    )
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="exact",
        scope_note="Company scope uses user/database naming where Snowflake does not expose company ownership.",
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: prioritize failed logins, MFA gaps, risky grants, and external exposure.")
    render_workflow_guide(
        "Start with identity/access posture, then inspect data sharing when the question "
        "is exposure, external access, or audit evidence.",
        [
            ("Login failures, MFA, grants, or risky access", "Use Access posture."),
            ("External consumers or shared data exposure", "Use Data sharing exposure."),
        ],
    )

    days = st.slider("Security brief lookback (days)", 1, 90, 30, key="security_posture_brief_days")
    if st.button("Load Security Brief", key="security_posture_brief_load", type="primary"):
        summary_sql, exceptions_sql = _build_security_summary_sql(session, days, company)
        try:
            st.session_state["security_posture_summary"] = run_query(
                summary_sql,
                ttl_key=f"security_posture_summary_{company}_{days}",
                tier="standard",
            )
            st.session_state["security_posture_exceptions"] = run_query(
                exceptions_sql,
                ttl_key=f"security_posture_exceptions_{company}_{days}",
                tier="standard",
            )
            st.session_state["security_posture_meta"] = {"company": company, "days": days}
            st.session_state["security_posture_proof_sql"] = {
                "summary": summary_sql,
                "exceptions": exceptions_sql,
            }
        except Exception as exc:
            st.session_state["security_posture_summary"] = pd.DataFrame()
            st.session_state["security_posture_exceptions"] = pd.DataFrame()
            st.error(f"Unable to load security brief: {format_snowflake_error(exc)}")

    summary = st.session_state.get("security_posture_summary")
    exceptions = st.session_state.get("security_posture_exceptions")
    meta = st.session_state.get("security_posture_meta", {})
    if (
        summary is not None
        and not summary.empty
        and meta.get("company") == company
        and meta.get("days") == days
    ):
        row = summary.iloc[0]
        failed_logins = safe_int(row.get("FAILED_LOGINS", 0))
        failed_users = safe_int(row.get("FAILED_USERS", 0))
        active_users = safe_int(row.get("ACTIVE_USERS", 0))
        users_without_mfa = safe_int(row.get("USERS_WITHOUT_MFA", 0))
        recent_grants = safe_int(row.get("RECENT_GRANTS", 0))
        shared_databases = safe_int(row.get("SHARED_DATABASES", 0))
        score = _security_score(
            failed_logins=failed_logins,
            failed_users=failed_users,
            users_without_mfa=users_without_mfa,
            active_users=active_users,
            recent_grants=recent_grants,
            shared_databases=shared_databases,
        )
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Security Score", score, _security_rating(score))
        c2.metric("Failed Logins", f"{failed_logins:,}", delta_color="inverse")
        c3.metric("Users Without MFA", f"{users_without_mfa:,}", delta_color="inverse")
        c4.metric("Recent Grants", f"{recent_grants:,}")
        c5.metric("Shared DBs", f"{shared_databases:,}")
        if score < 85:
            st.warning("Security posture needs DBA review before this can be called clean.")
        elif score < 95:
            st.info("Security posture is usable, but there are findings worth reviewing.")
        else:
            st.success("Security posture is strong for the selected window.")
        if exceptions is not None and not exceptions.empty:
            st.subheader("Security Exceptions")
            st.dataframe(exceptions, use_container_width=True, hide_index=True)
            if st.button("Save Security Exceptions to Action Queue", key="security_posture_queue"):
                _queue_security_exceptions(session, exceptions)
        elif exceptions is not None:
            st.success("No security exceptions crossed the default thresholds.")
        brief_md = _build_security_brief_markdown(
            company=company,
            days=days,
            score=score,
            summary_row=row,
            exceptions=exceptions,
        )
        dl1, dl2 = st.columns([1, 3])
        with dl1:
            st.download_button(
                "Download Security Brief",
                brief_md,
                file_name=f"overwatch_security_brief_{company.lower()}.md",
                mime="text/markdown",
                key="security_posture_download",
            )
        with dl2:
            with st.expander("Proof SQL", expanded=False):
                proof_sql = st.session_state.get("security_posture_proof_sql", {})
                st.caption("Use these source queries when an auditor or security partner asks where a number came from.")
                st.code(proof_sql.get("summary", "-- Load the security brief first."), language="sql")
                st.code(proof_sql.get("exceptions", "-- Load the security brief first."), language="sql")
        if st.session_state.get("exceptions_only_mode"):
            st.stop()

    workflow = render_workflow_selector(
        "Security workflow",
        "security_posture_workflow",
        WORKFLOWS,
    )

    if workflow == "Access posture":
        security_access.render()
    else:
        data_sharing.render()
