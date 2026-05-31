# sections/security_posture.py - Consolidated security and access workflow
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA
from sections import data_sharing, security_access
from utils import (
    filter_existing_columns,
    format_snowflake_error,
    get_active_company,
    get_active_environment,
    get_db_filter_clause,
    get_session,
    get_user_filter_clause,
    mart_object_name,
    make_action_id,
    run_query,
    safe_float,
    safe_identifier,
    safe_int,
    sql_literal,
    upsert_actions,
)
from utils.workflows import (
    render_operator_briefing,
    render_priority_dataframe,
    render_signal_confidence,
    render_workflow_guide,
    render_workflow_selector,
)

WORKFLOWS = ("Access posture", "Data sharing exposure")

WORKFLOW_DETAILS = {
    "Access posture": "Failed logins, MFA gaps, grants, role risk, and security exceptions.",
    "Data sharing exposure": "Shares, imported databases, exposed datasets, and owner follow-up.",
}

SECURITY_ACCESS_REVIEW_TABLE = "OVERWATCH_SECURITY_ACCESS_REVIEW"


def security_access_review_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = SECURITY_ACCESS_REVIEW_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def build_security_access_review_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = SECURITY_ACCESS_REVIEW_TABLE,
) -> str:
    fqn = security_access_review_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_ID             VARCHAR(64),
    SNAPSHOT_TS             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY                 VARCHAR(100),
    ENVIRONMENT             VARCHAR(100),
    DATABASE_CONTEXT        BOOLEAN,
    FINDING_TYPE            VARCHAR(120),
    SEVERITY                VARCHAR(40),
    ENTITY_TYPE             VARCHAR(120),
    ENTITY                  VARCHAR(500),
    EVENT_COUNT             NUMBER,
    DISTINCT_SOURCES        NUMBER,
    LAST_SEEN               VARCHAR(100),
    OWNER                   VARCHAR(200),
    ESCALATION_TARGET       VARCHAR(200),
    OWNER_SOURCE            VARCHAR(200),
    APPROVER                VARCHAR(200),
    OWNER_APPROVAL_STATUS   VARCHAR(40),
    ACCESS_REVIEW_STATE     VARCHAR(160),
    ROLE_CAPABILITY_STATE   VARCHAR(200),
    TICKET_REQUIRED         VARCHAR(20),
    REVIEW_BY_REQUIRED      VARCHAR(20),
    PROOF_REQUIRED          VARCHAR(2000),
    VERIFICATION_QUERY      VARCHAR(8000),
    NEXT_ACTION             VARCHAR(4000),
    PROOF_QUERY             VARCHAR(4000),
    SOURCE                  VARCHAR(500)
);"""


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


def _security_exception_has_database_context(row: pd.Series | dict) -> bool:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    return "shared" in finding_type or "database exposure" in finding_type


def _security_exception_environment(row: pd.Series | dict, environment: str = "ALL") -> str:
    if not _security_exception_has_database_context(row):
        return "No Database Context"
    return str(environment or "").strip() or "ALL"


def _security_owner_context(row: pd.Series | dict) -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    entity = str(row.get("ENTITY") or "").upper()
    if "failed login" in finding_type or "mfa" in finding_type:
        return {
            "owner": "IAM / Security Owner",
            "escalation": "Security Owner / DBA Lead",
            "source": "Security owner map",
        }
    if "grant" in finding_type:
        if any(token in entity for token in ("ADMIN", "SECURITY", "SYSADMIN", "ACCOUNTADMIN")):
            return {
                "owner": "Security Owner",
                "escalation": "DBA Lead / Security Owner",
                "source": "Admin-role owner hint",
            }
        return {
            "owner": "Access Owner / DBA Security",
            "escalation": "Data Owner / Security Owner",
            "source": "Security owner map",
        }
    if "shared" in finding_type or "exposure" in finding_type:
        return {
            "owner": "Data Owner / Security Owner",
            "escalation": "Data Governance / Legal",
            "source": "Shared-data owner map",
        }
    return {
        "owner": "Security/DBA",
        "escalation": "DBA Lead",
        "source": "Default security owner",
    }


def _security_approval_context(row: pd.Series | dict) -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    if "failed login" in finding_type:
        return {
            "approver": "IAM / Security Owner",
            "review_state": "Identity investigation required",
            "role_capability_state": "Not required",
            "proof_required": "user, source IP/client, error code, IAM corroboration, disposition",
        }
    if "mfa" in finding_type:
        return {
            "approver": "IAM / Security Owner",
            "review_state": "MFA enforcement approval required",
            "role_capability_state": "Not required",
            "proof_required": "user, auth path, MFA/SSO enforcement evidence, exception approval if any",
        }
    if "grant" in finding_type:
        return {
            "approver": "Access Owner / Security Owner",
            "review_state": "Access review required",
            "role_capability_state": "MANAGE GRANTS or role ownership proof required before change",
            "proof_required": "role, grantee, requester, approver, ticket, review/expiry date, rollback/verification",
        }
    if "shared" in finding_type or "exposure" in finding_type:
        return {
            "approver": "Data Owner / Data Governance",
            "review_state": "External sharing approval required",
            "role_capability_state": "OWNERSHIP / IMPORTED PRIVILEGES proof required for remediation",
            "proof_required": "consumer, provider, data classification, contract, owner approval, review date",
        }
    return {
        "approver": "Security Owner",
        "review_state": "Security review required",
        "role_capability_state": "Capability proof depends on remediation",
        "proof_required": "finding evidence, owner, approver, ticket, verification result",
    }


def _security_exception_verification_sql(row: pd.Series | dict) -> str:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    entity = str(row.get("ENTITY") or "").strip()
    entity_lit = sql_literal(entity, 500)
    if "failed login" in finding_type:
        return f"""
SELECT
    user_name,
    event_timestamp,
    client_ip,
    reported_client_type,
    error_code,
    error_message,
    is_success
FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
WHERE event_timestamp >= DATEADD('day', -14, CURRENT_TIMESTAMP())
  AND UPPER(user_name) = UPPER({entity_lit})
  AND is_success = 'NO'
ORDER BY event_timestamp DESC
LIMIT 100""".strip()
    if "mfa" in finding_type:
        return f"""
SELECT
    name AS user_name,
    disabled,
    has_password,
    ext_authn_duo,
    last_success_login,
    owner,
    created_on
FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
WHERE UPPER(name) = UPPER({entity_lit})
LIMIT 50""".strip()
    if "grant" in finding_type:
        return f"""
SELECT
    grantee_name,
    role,
    granted_to,
    granted_by,
    created_on,
    deleted_on
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
WHERE UPPER(grantee_name) = UPPER({entity_lit})
  AND deleted_on IS NULL
ORDER BY created_on DESC
LIMIT 100""".strip()
    if "shared" in finding_type or "exposure" in finding_type:
        return f"""
SELECT
    database_name,
    database_owner,
    type,
    origin,
    owner,
    comment,
    created
FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASES
WHERE UPPER(database_name) = UPPER({entity_lit})
  AND deleted IS NULL
LIMIT 50""".strip()
    return f"""
SELECT
    CURRENT_TIMESTAMP() AS verification_ts,
    {sql_literal(str(row.get('FINDING_TYPE') or 'Security Finding'), 200)} AS finding_type,
    {entity_lit} AS entity
LIMIT 50""".strip()


def _build_security_access_review(exceptions: pd.DataFrame, environment: str = "ALL") -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    view = _security_priority_view(exceptions).copy()
    owner_contexts = view.apply(_security_owner_context, axis=1)
    approval_contexts = view.apply(_security_approval_context, axis=1)
    view["OWNER"] = owner_contexts.apply(lambda item: item["owner"])
    view["ESCALATION_TARGET"] = owner_contexts.apply(lambda item: item["escalation"])
    view["OWNER_SOURCE"] = owner_contexts.apply(lambda item: item["source"])
    view["APPROVER"] = approval_contexts.apply(lambda item: item["approver"])
    view["OWNER_APPROVAL_STATUS"] = "Requested"
    view["ACCESS_REVIEW_STATE"] = approval_contexts.apply(lambda item: item["review_state"])
    view["ROLE_CAPABILITY_STATE"] = approval_contexts.apply(lambda item: item["role_capability_state"])
    view["TICKET_REQUIRED"] = "Yes"
    view["REVIEW_BY_REQUIRED"] = "Yes"
    view["PROOF_REQUIRED"] = approval_contexts.apply(lambda item: item["proof_required"])
    view["VERIFICATION_QUERY"] = view.apply(_security_exception_verification_sql, axis=1)
    view["DATABASE_CONTEXT"] = view.apply(_security_exception_has_database_context, axis=1)
    view["ENVIRONMENT"] = view.apply(lambda row: _security_exception_environment(row, environment), axis=1)
    return view


def _security_workflow_for(finding_type: str) -> str:
    value = str(finding_type or "").lower()
    if "shared" in value or "exposure" in value:
        return "Data sharing exposure"
    return "Access posture"


def _security_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = exceptions.copy()
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(4)
    view["NEXT_WORKFLOW"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(_security_workflow_for)
    view["ENTITY_TYPE"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(lambda value: _security_action_for(value)[0])
    view["NEXT_ACTION"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(lambda value: _security_action_for(value)[1])
    return view.sort_values(["_RANK", "EVENT_COUNT", "LAST_SEEN"], ascending=[True, False, False]).drop(columns=["_RANK"], errors="ignore")


def _render_security_watch_floor(score: int, exceptions: pd.DataFrame, row) -> None:
    priority = _security_priority_view(exceptions).head(3)
    failed_logins = safe_int(row.get("FAILED_LOGINS", 0))
    users_without_mfa = safe_int(row.get("USERS_WITHOUT_MFA", 0))
    shared_databases = safe_int(row.get("SHARED_DATABASES", 0))
    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.1, 2.2])
    c1.metric("Posture Readiness", f"{score}/100", _security_rating(score))
    c2.metric("Priority Findings", f"{len(priority):,}", delta_color="inverse")
    c3.metric("Identity Signals", f"{failed_logins + users_without_mfa:,}", delta_color="inverse")
    with c4:
        if priority.empty:
            st.success("No urgent security findings crossed the brief thresholds.")
        else:
            first = priority.iloc[0]
            st.warning(
                f"First move: {first.get('FINDING_TYPE', 'Security finding')} for "
                f"{first.get('ENTITY', 'unknown')} -> {first.get('NEXT_ACTION', 'Review access evidence.')}"
            )

    st.markdown("**Security Watch Floor**")
    if priority.empty:
        if shared_databases:
            st.caption("No urgent findings, but shared/imported database exposure exists. Validate owners and consumers periodically.")
        else:
            st.caption("No immediate security cards. Use Access posture for audit evidence or Data sharing exposure for external-consumer review.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Access posture")
        with cols[idx]:
            st.markdown(f"**{item.get('SEVERITY', 'Medium')}: {item.get('FINDING_TYPE', '')}**")
            st.caption(f"{item.get('ENTITY_TYPE', 'Access')}: {item.get('ENTITY', 'unknown')}")
            st.write(str(item.get("NEXT_ACTION", "")))
            st.caption(str(item.get("PROOF_QUERY", "")))
            if st.button(f"Open {workflow}", key=f"security_watch_floor_{idx}_{workflow}", use_container_width=True):
                entity = str(item.get("ENTITY") or "").strip()
                if workflow == "Data sharing exposure":
                    if entity and entity.lower() != "unknown":
                        st.session_state["global_database"] = entity.split(".")[0]
                    for stale_key in ("ds_df_dt", "ds_df_shared_db"):
                        st.session_state.pop(stale_key, None)
                else:
                    if entity and entity.lower() != "unknown":
                        st.session_state["global_user"] = entity
                    for stale_key in (
                        "sec_df_login_sum",
                        "sec_df_failed_logins",
                        "sec_df_login_trend",
                        "sec_df_grants",
                        "sec_df_dom",
                        "sec_df_mfa",
                        "sec_df_exfil",
                        "sec_df_lin",
                    ):
                        st.session_state.pop(stale_key, None)
                st.session_state["security_posture_workflow"] = workflow
                st.rerun()


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


def _build_security_mart_brief_sql(session, days: int, company: str) -> tuple[str, str]:
    """Build the security brief with mart-backed login aggregates and live governance metadata."""
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
    login_table = mart_object_name("FACT_LOGIN_DAILY")
    grant_table = mart_object_name("FACT_GRANT_DAILY")
    login_company_filter = "" if str(company or "").upper() == "ALL" else f"AND lh.company = {sql_literal(company, 100)}"
    grant_company_filter = "" if str(company or "").upper() == "ALL" else f"AND g.company = {sql_literal(company, 100)}"
    company_label = sql_literal(company, 100)
    summary_sql = f"""
    WITH login_events AS (
        SELECT
            COALESCE(SUM(success_count), 0) + COALESCE(SUM(failure_count), 0) AS login_events,
            COALESCE(SUM(failure_count), 0) AS failed_logins,
            COUNT(DISTINCT IFF(COALESCE(failure_count, 0) > 0, lh.user_name, NULL)) AS failed_users,
            COUNT(DISTINCT IFF(COALESCE(failure_count, 0) > 0, lh.client_ip, NULL)) AS failed_ips
        FROM {login_table} lh
        WHERE lh.login_date >= DATEADD('day', -{int(days)}, CURRENT_DATE())
          {login_company_filter}
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
        SELECT COALESCE(SUM(grant_count), 0) AS recent_grants
        FROM {grant_table} g
        WHERE 1 = 1
          {grant_company_filter}
          AND g.deleted_on IS NULL
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
        {company_label} AS company,
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
            IFF(SUM(failure_count) >= 25 OR COUNT(DISTINCT client_ip) >= 5, 'High', 'Medium') AS severity,
            user_name AS entity,
            COALESCE(SUM(failure_count), 0) AS event_count,
            COUNT(DISTINCT client_ip) AS distinct_sources,
            MAX(login_date)::TIMESTAMP_NTZ AS last_seen,
            'FACT_LOGIN_DAILY failed login attempts by user/IP' AS proof_query
        FROM {login_table} lh
        WHERE lh.login_date >= DATEADD('day', -{int(days)}, CURRENT_DATE())
          {login_company_filter}
          AND COALESCE(failure_count, 0) > 0
          {user_filter_lh}
        GROUP BY user_name
        HAVING COALESCE(SUM(failure_count), 0) >= 3
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
            IFF(SUM(grant_count) >= 10, 'Medium', 'Low') AS severity,
            g.grantee_name AS entity,
            COALESCE(SUM(grant_count), 0) AS event_count,
            COUNT(DISTINCT g.role_name) AS distinct_sources,
            MAX(g.created_on) AS last_seen,
            'FACT_GRANT_DAILY active grants created recently' AS proof_query
        FROM {grant_table} g
        WHERE 1 = 1
          {grant_company_filter}
          AND g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {user_filter_g}
        GROUP BY g.grantee_name
        HAVING COALESCE(SUM(grant_count), 0) >= 3
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


def _security_access_review_insert_sql(
    review: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
    snapshot_id: str = "",
) -> str:
    if review is None or review.empty:
        raise ValueError("Security access review snapshot has no rows to save.")
    view = _build_security_access_review(review, environment) if "ACCESS_REVIEW_STATE" not in review.columns else review.copy()
    fqn = security_access_review_fqn()
    snap = snapshot_id or make_action_id(
        "Security Access Review Snapshot",
        company,
        f"{environment or 'ALL'}|{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )
    selects = []
    for _, row in view.head(200).iterrows():
        selects.append(
            "SELECT "
            f"{sql_literal(snap, 64)} AS SNAPSHOT_ID, "
            "CURRENT_TIMESTAMP() AS SNAPSHOT_TS, "
            f"{sql_literal(company, 100)} AS COMPANY, "
            f"{sql_literal(row.get('ENVIRONMENT', _security_exception_environment(row, environment)), 100)} AS ENVIRONMENT, "
            f"{'TRUE' if bool(row.get('DATABASE_CONTEXT', _security_exception_has_database_context(row))) else 'FALSE'} AS DATABASE_CONTEXT, "
            f"{sql_literal(row.get('FINDING_TYPE', ''), 120)} AS FINDING_TYPE, "
            f"{sql_literal(row.get('SEVERITY', ''), 40)} AS SEVERITY, "
            f"{sql_literal(row.get('ENTITY_TYPE', ''), 120)} AS ENTITY_TYPE, "
            f"{sql_literal(row.get('ENTITY', ''), 500)} AS ENTITY, "
            f"{safe_int(row.get('EVENT_COUNT'))}::NUMBER AS EVENT_COUNT, "
            f"{safe_int(row.get('DISTINCT_SOURCES'))}::NUMBER AS DISTINCT_SOURCES, "
            f"{sql_literal(row.get('LAST_SEEN', ''), 100)} AS LAST_SEEN, "
            f"{sql_literal(row.get('OWNER', ''), 200)} AS OWNER, "
            f"{sql_literal(row.get('ESCALATION_TARGET', ''), 200)} AS ESCALATION_TARGET, "
            f"{sql_literal(row.get('OWNER_SOURCE', ''), 200)} AS OWNER_SOURCE, "
            f"{sql_literal(row.get('APPROVER', ''), 200)} AS APPROVER, "
            f"{sql_literal(row.get('OWNER_APPROVAL_STATUS', ''), 40)} AS OWNER_APPROVAL_STATUS, "
            f"{sql_literal(row.get('ACCESS_REVIEW_STATE', ''), 160)} AS ACCESS_REVIEW_STATE, "
            f"{sql_literal(row.get('ROLE_CAPABILITY_STATE', ''), 200)} AS ROLE_CAPABILITY_STATE, "
            f"{sql_literal(row.get('TICKET_REQUIRED', ''), 20)} AS TICKET_REQUIRED, "
            f"{sql_literal(row.get('REVIEW_BY_REQUIRED', ''), 20)} AS REVIEW_BY_REQUIRED, "
            f"{sql_literal(row.get('PROOF_REQUIRED', ''), 2000)} AS PROOF_REQUIRED, "
            f"{sql_literal(row.get('VERIFICATION_QUERY', ''), 8000)} AS VERIFICATION_QUERY, "
            f"{sql_literal(row.get('NEXT_ACTION', ''), 4000)} AS NEXT_ACTION, "
            f"{sql_literal(row.get('PROOF_QUERY', ''), 4000)} AS PROOF_QUERY, "
            f"{sql_literal(source, 500)} AS SOURCE"
        )
    return f"""
INSERT INTO {fqn} (
    SNAPSHOT_ID, SNAPSHOT_TS, COMPANY, ENVIRONMENT, DATABASE_CONTEXT,
    FINDING_TYPE, SEVERITY, ENTITY_TYPE, ENTITY, EVENT_COUNT, DISTINCT_SOURCES,
    LAST_SEEN, OWNER, ESCALATION_TARGET, OWNER_SOURCE, APPROVER,
    OWNER_APPROVAL_STATUS, ACCESS_REVIEW_STATE, ROLE_CAPABILITY_STATE,
    TICKET_REQUIRED, REVIEW_BY_REQUIRED, PROOF_REQUIRED, VERIFICATION_QUERY,
    NEXT_ACTION, PROOF_QUERY, SOURCE
)
{" UNION ALL ".join(selects)}""".strip()


def _security_access_review_history_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = security_access_review_fqn()
    where = [f"SNAPSHOT_TS >= DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_value = str(environment or "").strip()
    if env_value and env_value.upper() != "ALL":
        # Login-only and account-role rows have no database context; keep them visible under environment filters.
        where.append(f"(ENVIRONMENT = {sql_literal(env_value, 100)} OR DATABASE_CONTEXT = FALSE)")
    where_clause = " AND ".join(where)
    return f"""
SELECT
    FINDING_TYPE,
    SEVERITY,
    OWNER,
    ESCALATION_TARGET,
    COUNT(*) AS REVIEW_ROWS,
    SUM(EVENT_COUNT) AS TOTAL_EVENTS,
    COUNT_IF(TICKET_REQUIRED = 'Yes') AS TICKET_REQUIRED_ROWS,
    COUNT_IF(REVIEW_BY_REQUIRED = 'Yes') AS REVIEW_BY_REQUIRED_ROWS,
    COUNT_IF(ROLE_CAPABILITY_STATE ILIKE '%required%') AS CAPABILITY_PROOF_ROWS,
    COUNT_IF(DATABASE_CONTEXT = FALSE) AS NO_DATABASE_CONTEXT_ROWS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX_BY(ACCESS_REVIEW_STATE, SNAPSHOT_TS) AS LAST_ACCESS_REVIEW_STATE,
    MAX_BY(ROLE_CAPABILITY_STATE, SNAPSHOT_TS) AS LAST_ROLE_CAPABILITY_STATE,
    MAX_BY(PROOF_REQUIRED, SNAPSHOT_TS) AS LAST_PROOF_REQUIRED
FROM {fqn}
WHERE {where_clause}
GROUP BY FINDING_TYPE, SEVERITY, OWNER, ESCALATION_TARGET
ORDER BY
    TICKET_REQUIRED_ROWS DESC,
    CAPABILITY_PROOF_ROWS DESC,
    TOTAL_EVENTS DESC,
    LAST_SNAPSHOT_TS DESC
LIMIT 100""".strip()


def _save_security_access_review_snapshot(
    session,
    review: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
) -> None:
    try:
        session.sql(build_security_access_review_ddl()).collect()
        session.sql(_security_access_review_insert_sql(
            review,
            company=company,
            environment=environment,
            source=source,
        )).collect()
        st.success("Saved the Security Access Review snapshot for owner, ticket, and verification tracking.")
    except Exception as exc:
        st.error(f"Could not save Security Access Review snapshot: {format_snowflake_error(exc)}")
        st.info("Deploy the security access review table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _queue_security_exceptions(session, exceptions: pd.DataFrame) -> None:
    if exceptions is None or exceptions.empty:
        st.info("No security exceptions to queue.")
        return
    company = get_active_company()
    environment = get_active_environment()
    review = _build_security_access_review(exceptions, environment)
    actions = []
    for _, row in review.head(100).iterrows():
        finding_type = str(row.get("FINDING_TYPE") or "Security Finding")
        entity = str(row.get("ENTITY") or "Unknown")
        severity = str(row.get("SEVERITY") or "Medium")
        event_count = safe_int(row.get("EVENT_COUNT", 0))
        finding = f"{finding_type}: {entity} has {event_count} event(s) requiring review"
        entity_type, action, generated_sql = _security_action_for(finding_type)
        verification_query = str(row.get("VERIFICATION_QUERY") or _security_exception_verification_sql(row))
        actions.append({
            "Action ID": make_action_id("Security Posture", entity, finding),
            "Source": "Security Posture - Security Brief",
            "Severity": severity,
            "Category": "Security",
            "Entity Type": entity_type,
            "Entity": entity,
            "Owner": row.get("OWNER", "Security/DBA"),
            "Finding": finding,
            "Action": (
                f"{action} Owner approval from {row.get('APPROVER', 'Security Owner')} is required; "
                f"proof required: {row.get('PROOF_REQUIRED', 'security evidence and verification result')}."
            ),
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": "\n".join([
                "-- Review-only security/access record. Do not revoke, disable, or grant access from this row.",
                generated_sql,
                f"-- Access review state: {row.get('ACCESS_REVIEW_STATE', '')}.",
                f"-- Role/capability state: {row.get('ROLE_CAPABILITY_STATE', '')}.",
                f"-- Environment context: {row.get('ENVIRONMENT', _security_exception_environment(row, environment))}.",
            ]),
            "Proof Query": verification_query,
            "Verification Query": verification_query,
            "Verification Status": "Pending",
            "Approver": row.get("APPROVER", "Security Owner"),
            "Owner Approval Status": row.get("OWNER_APPROVAL_STATUS", "Requested"),
            "Owner Approval Note": (
                f"{row.get('ACCESS_REVIEW_STATE', '')}; escalation={row.get('ESCALATION_TARGET', 'DBA Lead')}; "
                f"ticket required={row.get('TICKET_REQUIRED', 'Yes')}; review-by required={row.get('REVIEW_BY_REQUIRED', 'Yes')}."
            ),
            "Recovery Evidence": (
                f"Proof required: {row.get('PROOF_REQUIRED', '')}. "
                f"Role capability: {row.get('ROLE_CAPABILITY_STATE', '')}."
            ),
            "Company": company,
            "Environment": row.get("ENVIRONMENT", _security_exception_environment(row, environment)),
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} security exceptions to the action queue.")
    except Exception as e:
        st.error(f"Could not save security exceptions: {format_snowflake_error(e)}")
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def render() -> None:
    session = get_session()
    company = get_active_company()
    environment = get_active_environment()
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
    render_operator_briefing(
        [
            ("First move", "Separate noisy login volume from real identity or access risk."),
            ("Evidence", "Tie users, IPs, grants, MFA posture, and shared data to a proof trail."),
            ("Control", "Escalate to IAM, revoke/narrow access, or validate business ownership."),
            ("Output", "Produce an audit posture brief with owners and remediation status."),
        ],
        columns=4,
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
        try:
            summary_sql, exceptions_sql = _build_security_mart_brief_sql(session, days, company)
            st.session_state["security_posture_summary"] = run_query(
                summary_sql,
                ttl_key=f"security_posture_summary_mart_{company}_{environment}_{days}",
                tier="standard",
            )
            st.session_state["security_posture_exceptions"] = run_query(
                exceptions_sql,
                ttl_key=f"security_posture_exceptions_mart_{company}_{environment}_{days}",
                tier="standard",
            )
            st.session_state["security_posture_meta"] = {
                "company": company,
                "environment": environment,
                "days": days,
                "source": "OVERWATCH mart: FACT_LOGIN_DAILY + FACT_GRANT_DAILY; MFA/sharing: ACCOUNT_USAGE",
            }
            st.session_state["security_posture_proof_sql"] = {
                "summary": summary_sql,
                "exceptions": exceptions_sql,
            }
        except Exception as exc:
            try:
                summary_sql, exceptions_sql = _build_security_summary_sql(session, days, company)
                st.session_state["security_posture_summary"] = run_query(
                    summary_sql,
                    ttl_key=f"security_posture_summary_live_{company}_{environment}_{days}",
                    tier="standard",
                )
                st.session_state["security_posture_exceptions"] = run_query(
                    exceptions_sql,
                    ttl_key=f"security_posture_exceptions_live_{company}_{environment}_{days}",
                    tier="standard",
                )
                st.session_state["security_posture_meta"] = {
                    "company": company,
                    "environment": environment,
                    "days": days,
                    "source": "Live fallback: SNOWFLAKE.ACCOUNT_USAGE",
                }
                st.session_state["security_posture_proof_sql"] = {
                    "summary": summary_sql,
                    "exceptions": exceptions_sql,
                }
                st.info(f"Security mart unavailable; used live ACCOUNT_USAGE fallback. {format_snowflake_error(exc)}")
            except Exception as live_exc:
                st.session_state["security_posture_summary"] = pd.DataFrame()
                st.session_state["security_posture_exceptions"] = pd.DataFrame()
                st.error(f"Unable to load security brief: {format_snowflake_error(live_exc)}")

    summary = st.session_state.get("security_posture_summary")
    exceptions = st.session_state.get("security_posture_exceptions")
    meta = st.session_state.get("security_posture_meta", {})
    if (
        summary is not None
        and not summary.empty
        and meta.get("company") == company
        and meta.get("environment") == environment
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
        st.caption(meta.get("source", "SNOWFLAKE.ACCOUNT_USAGE"))
        _render_security_watch_floor(score, exceptions, row)
        st.divider()
        if exceptions is not None and not exceptions.empty:
            st.subheader("Security Exceptions")
            priority_exceptions = _security_priority_view(exceptions)
            render_priority_dataframe(
                priority_exceptions,
                title="Security exceptions to validate first",
                priority_columns=[
                    "SEVERITY", "FINDING_TYPE", "ENTITY", "EVENT_COUNT",
                    "DISTINCT_SOURCES", "LAST_SEEN", "ENTITY_TYPE",
                    "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["SEVERITY", "EVENT_COUNT", "LAST_SEEN"],
                ascending=[True, False, False],
                raw_label="All security exceptions",
            )

            access_review = _build_security_access_review(exceptions, environment)
            render_priority_dataframe(
                access_review,
                title="Security access-review readiness before queueing",
                priority_columns=[
                    "SEVERITY", "ACCESS_REVIEW_STATE", "FINDING_TYPE", "ENTITY",
                    "OWNER", "ESCALATION_TARGET", "APPROVER", "ROLE_CAPABILITY_STATE",
                    "TICKET_REQUIRED", "REVIEW_BY_REQUIRED", "DATABASE_CONTEXT",
                    "ENVIRONMENT", "PROOF_REQUIRED",
                ],
                sort_by=["SEVERITY", "TICKET_REQUIRED", "REVIEW_BY_REQUIRED", "ENTITY"],
                ascending=[True, False, False, True],
                raw_label="Full security access review",
            )

            review_col, queue_col = st.columns(2)
            with review_col:
                if st.button("Save Access Review Snapshot", key="security_posture_access_review_snapshot"):
                    _save_security_access_review_snapshot(
                        session,
                        access_review,
                        company=company,
                        environment=environment,
                        source=meta.get("source", ""),
                    )
            with queue_col:
                if st.button("Save Security Exceptions to Action Queue", key="security_posture_queue"):
                    _queue_security_exceptions(session, exceptions)

            with st.expander("Security Access Review Trend", expanded=False):
                trend_days = st.slider(
                    "Access review history lookback (days)",
                    7,
                    120,
                    30,
                    key="security_access_review_trend_days",
                )
                if st.button("Load Access Review Trend", key="security_access_review_trend_load"):
                    try:
                        trend_sql = _security_access_review_history_sql(trend_days, company, environment)
                        st.session_state["security_access_review_trend_sql"] = trend_sql
                        st.session_state["security_access_review_trend"] = run_query(
                            trend_sql,
                            ttl_key=f"security_access_review_trend_{company}_{environment}_{trend_days}",
                            tier="standard",
                            section="Security Posture",
                        )
                    except Exception as exc:
                        st.session_state["security_access_review_trend"] = pd.DataFrame()
                        st.error(f"Could not load security access-review history: {format_snowflake_error(exc)}")
                        st.info("Deploy the access-review table from `snowflake/OVERWATCH_MART_SETUP.sql`, then reload.")
                trend = st.session_state.get("security_access_review_trend")
                if trend is not None and not trend.empty:
                    render_priority_dataframe(
                        trend,
                        title="Security review findings still needing DBA evidence",
                        priority_columns=[
                            "FINDING_TYPE", "SEVERITY", "OWNER", "ESCALATION_TARGET",
                            "REVIEW_ROWS", "TOTAL_EVENTS", "TICKET_REQUIRED_ROWS",
                            "REVIEW_BY_REQUIRED_ROWS", "CAPABILITY_PROOF_ROWS",
                            "NO_DATABASE_CONTEXT_ROWS", "LAST_ACCESS_REVIEW_STATE",
                            "LAST_ROLE_CAPABILITY_STATE",
                        ],
                        sort_by=["TICKET_REQUIRED_ROWS", "CAPABILITY_PROOF_ROWS", "TOTAL_EVENTS"],
                        ascending=[False, False, False],
                        raw_label="Access review history",
                    )
                    with st.expander("Trend Query", expanded=False):
                        st.code(st.session_state.get("security_access_review_trend_sql", ""), language="sql")
                elif trend is not None:
                    st.info("No saved security access-review snapshots found for the selected scope.")
                with st.expander("Access Review Setup SQL", expanded=False):
                    st.code(build_security_access_review_ddl(), language="sql")
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
        WORKFLOW_DETAILS,
        columns=2,
    )

    if workflow == "Access posture":
        security_access.render()
    else:
        data_sharing.render()
