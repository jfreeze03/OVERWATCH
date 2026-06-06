# sections/security_access.py - Login audit, roles & privileges, data lineage, MFA, exfiltration
import streamlit as st
import pandas as pd
from utils import (
    admin_button_disabled,
    defer_source_note,
    download_csv,
    filter_existing_columns,
    get_active_company,
    get_active_environment,
    get_db_filter_clause,
    get_global_filter_clause,
    get_session,
    get_user_filter_clause,
    get_wh_filter_clause,
    make_action_id,
    mart_object_name,
    format_snowflake_error,
    log_admin_action,
    render_priority_dataframe,
    render_ranked_bar_chart,
    run_query,
    run_query_or_raise,
    safe_int,
    sql_literal,
    upsert_actions,
)
from config import THRESHOLDS


SECURITY_ACCESS_PANES = (
    "Login Audit",
    "Login Posture",
    "Connected Programs",
    "Roles & Grants",
    "MFA Coverage",
    "Exfiltration Signals",
    "Data Lineage",
)


def _user_mfa_column_exprs(user_cols: set[str]) -> dict[str, str]:
    """Return USERS projections that work across old and new Snowflake accounts."""
    normalized = {str(col or "").upper() for col in user_cols}
    if "HAS_MFA" in normalized:
        mfa_expr = "COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.has_mfa)), FALSE) AS has_mfa"
        mfa_source_expr = "'HAS_MFA' AS mfa_source"
    elif "EXT_AUTHN_DUO" in normalized:
        mfa_expr = "COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.ext_authn_duo)), FALSE) AS has_mfa"
        mfa_source_expr = "'EXT_AUTHN_DUO' AS mfa_source"
    else:
        mfa_expr = "NULL::BOOLEAN AS has_mfa"
        mfa_source_expr = "'UNAVAILABLE' AS mfa_source"
    return {
        "last_success_login_expr": (
            "u.last_success_login"
            if "LAST_SUCCESS_LOGIN" in normalized else "NULL::TIMESTAMP_NTZ"
        ),
        "has_password_expr": (
            "COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.has_password)), FALSE) AS has_password"
            if "HAS_PASSWORD" in normalized else "NULL::BOOLEAN AS has_password"
        ),
        "mfa_expr": mfa_expr,
        "mfa_source_expr": mfa_source_expr,
    }


def _build_mfa_coverage_sql(user_exprs: dict[str, str], user_filter_u: str = "") -> str:
    return f"""
        SELECT
            u.name AS user_name,
            {user_exprs["has_password_expr"]},
            {user_exprs["mfa_expr"]},
            {user_exprs["mfa_source_expr"]},
            u.disabled,
            COALESCE({user_exprs["last_success_login_expr"]}, u.created_on) AS last_login
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
        ORDER BY has_mfa, user_name
    """


def _mart_company_filter(alias: str, company: str) -> str:
    if str(company or "ALL").upper() == "ALL":
        return ""
    return f"AND {alias}.company = {sql_literal(company, 100)}"


def _load_login_audit_mart(company: str, days: int) -> dict[str, pd.DataFrame]:
    """Load login audit data from the daily mart when the requested window fits retention."""
    if days > 35:
        raise ValueError("Login mart keeps the most recent 35 days; using live login history for this wider lookback.")
    table = mart_object_name("FACT_LOGIN_DAILY")
    company_filter = _mart_company_filter("l", company)
    user_filter = get_user_filter_clause("l.user_name")
    base_where = f"""
        WHERE l.login_date >= DATEADD('DAY', -{int(days)}, CURRENT_DATE())
          {company_filter}
          {user_filter}
    """
    return {
        "sec_df_login_sum": run_query(f"""
            SELECT 'YES' AS is_success,
                   COALESCE(SUM(l.success_count), 0) AS event_count,
                   COUNT(DISTINCT IFF(COALESCE(l.success_count, 0) > 0, l.user_name, NULL)) AS distinct_users,
                   COUNT(DISTINCT IFF(COALESCE(l.success_count, 0) > 0, l.client_ip, NULL)) AS distinct_ips
            FROM {table} l
            {base_where}
            UNION ALL
            SELECT 'NO' AS is_success,
                   COALESCE(SUM(l.failure_count), 0) AS event_count,
                   COUNT(DISTINCT IFF(COALESCE(l.failure_count, 0) > 0, l.user_name, NULL)) AS distinct_users,
                   COUNT(DISTINCT IFF(COALESCE(l.failure_count, 0) > 0, l.client_ip, NULL)) AS distinct_ips
            FROM {table} l
            {base_where}
        """, ttl_key=f"security_mart_login_sum_{company}_{days}", tier="standard", section="Security Access"),
        "sec_df_failed_logins": run_query(f"""
            SELECT
                l.user_name,
                l.client_ip,
                l.reported_client_type,
                NULL::VARCHAR AS error_code,
                COALESCE(SUM(l.failure_count), 0) AS attempt_count,
                MAX(l.login_date)::TIMESTAMP_NTZ AS last_attempt
            FROM {table} l
            {base_where}
              AND COALESCE(l.failure_count, 0) > 0
            GROUP BY l.user_name, l.client_ip, l.reported_client_type
            ORDER BY attempt_count DESC, last_attempt DESC
            LIMIT 50
        """, ttl_key=f"security_mart_failed_logins_{company}_{days}", tier="standard", section="Security Access"),
        "sec_df_login_trend": run_query(f"""
            SELECT l.login_date AS day, 'YES' AS is_success, COALESCE(SUM(l.success_count), 0) AS event_count
            FROM {table} l
            {base_where}
            GROUP BY l.login_date
            UNION ALL
            SELECT l.login_date AS day, 'NO' AS is_success, COALESCE(SUM(l.failure_count), 0) AS event_count
            FROM {table} l
            {base_where}
            GROUP BY l.login_date
            ORDER BY day, is_success
        """, ttl_key=f"security_mart_login_trend_{company}_{days}", tier="standard", section="Security Access"),
    }


def _load_login_posture_mart(company: str, days: int) -> dict[str, pd.DataFrame]:
    """Load login posture summaries from FACT_LOGIN_DAILY."""
    if days > 35:
        raise ValueError("Login mart keeps the most recent 35 days; using live login history for this wider lookback.")
    table = mart_object_name("FACT_LOGIN_DAILY")
    company_filter = _mart_company_filter("l", company)
    user_filter = get_user_filter_clause("l.user_name")
    where = f"""
        WHERE l.login_date >= DATEADD('DAY', -{int(days)}, CURRENT_DATE())
          {company_filter}
          {user_filter}
    """
    return {
        "sec_login_ips": run_query(f"""
            SELECT
                l.client_ip,
                COALESCE(SUM(COALESCE(l.success_count, 0) + COALESCE(l.failure_count, 0)), 0) AS login_events,
                COUNT(DISTINCT l.user_name) AS users,
                COALESCE(SUM(l.success_count), 0) AS success_events,
                COALESCE(SUM(l.failure_count), 0) AS failed_events,
                MAX(l.login_date)::TIMESTAMP_NTZ AS last_seen
            FROM {table} l
            {where}
            GROUP BY l.client_ip
            ORDER BY login_events DESC
            LIMIT 50
        """, ttl_key=f"security_mart_login_ips_{company}_{days}", tier="standard", section="Security Access"),
        "sec_login_clients": run_query(f"""
            SELECT
                COALESCE(l.reported_client_type, 'UNKNOWN') AS reported_client_type,
                COALESCE(l.reported_client_version, 'UNKNOWN') AS reported_client_version,
                COALESCE(SUM(COALESCE(l.success_count, 0) + COALESCE(l.failure_count, 0)), 0) AS login_events,
                COUNT(DISTINCT l.user_name) AS users,
                COALESCE(SUM(l.failure_count), 0) AS failed_events
            FROM {table} l
            {where}
            GROUP BY 1, 2
            ORDER BY login_events DESC
            LIMIT 50
        """, ttl_key=f"security_mart_login_clients_{company}_{days}", tier="standard", section="Security Access"),
    }


def _connected_program_next_action(row: pd.Series) -> str:
    program = str(row.get("PROGRAM_NAME", "") or "").upper()
    source = str(row.get("SOURCE_CONFIDENCE", "") or "").upper()
    failures = safe_int(row.get("FAILED_QUERIES", row.get("FAILED_EVENTS", 0)))
    users = safe_int(row.get("USERS", 0))
    if program in {"", "UNKNOWN", "UNTAGGED"} or "FALLBACK" in source:
        return "Map this connection to an owner and require query tagging or a registered service account standard."
    if failures > 0:
        return "Review failure pattern, driver version, credential health, and recent grants before changing access."
    if users >= 10:
        return "Treat as shared tooling: confirm owner, support path, approved roles, and expected warehouse/database scope."
    return "Register owner, purpose, expected warehouses/databases, and approved role pattern."


def _annotate_connected_programs(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    annotated = df.copy()
    annotated["CONTROL_STATUS"] = annotated.apply(
        lambda row: (
            "Needs owner"
            if str(row.get("PROGRAM_NAME", "") or "").upper() in {"", "UNKNOWN", "UNTAGGED"}
            or "FALLBACK" in str(row.get("SOURCE_CONFIDENCE", "") or "").upper()
            else "Review failures"
            if safe_int(row.get("FAILED_QUERIES", row.get("FAILED_EVENTS", 0))) > 0
            else "Registered candidate"
        ),
        axis=1,
    )
    annotated["NEXT_ACTION"] = annotated.apply(_connected_program_next_action, axis=1)
    return annotated


def _load_connected_programs(session, company: str, days: int) -> dict[str, pd.DataFrame]:
    """Track Snowflake client programs from login events and query-linked authentication events."""
    days = max(1, min(90, int(days)))
    query_join_days = min(365, days + 14)
    user_filter = get_user_filter_clause("l.user_name")
    query_filters = get_global_filter_clause(
        date_col="q.start_time",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["SESSION_ID", "AUTHN_EVENT_ID", "ERROR_CODE", "QUERY_TAG", "IS_CLIENT_GENERATED_STATEMENT"],
    ))
    login_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY",
        ["EVENT_ID", "CLIENT_IP", "REPORTED_CLIENT_TYPE", "REPORTED_CLIENT_VERSION"],
    ))
    session_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.SESSIONS",
        [
            "SESSION_ID", "CREATED_ON", "USER_NAME", "LOGIN_EVENT_ID", "AUTHENTICATION_METHOD",
            "CLIENT_APPLICATION_ID", "CLIENT_APPLICATION_VERSION", "CLIENT_ENVIRONMENT",
            "CLIENT_BUILD_ID", "CLIENT_VERSION", "ACCESS_TIME", "IS_OPEN", "CLOSED_REASON",
        ],
    ))
    login_program_expr = (
        "COALESCE(TO_VARCHAR(l.reported_client_type), 'UNKNOWN')"
        if "REPORTED_CLIENT_TYPE" in login_cols else "'UNKNOWN'"
    )
    login_version_expr = (
        "COALESCE(TO_VARCHAR(l.reported_client_version), 'UNKNOWN')"
        if "REPORTED_CLIENT_VERSION" in login_cols else "'UNKNOWN'"
    )
    login_ip_count_expr = (
        "COUNT(DISTINCT l.client_ip)"
        if "CLIENT_IP" in login_cols else "0::NUMBER"
    )
    failed_query_expr = (
        "SUM(IFF(q.error_code IS NOT NULL, 1, 0))"
        if "ERROR_CODE" in qh_cols
        else "SUM(IFF(UPPER(q.execution_status) = 'FAILED_WITH_ERROR', 1, 0))"
    )
    client_generated_expr = (
        "SUM(IFF(q.is_client_generated_statement, 1, 0))"
        if "IS_CLIENT_GENERATED_STATEMENT" in qh_cols else "NULL::NUMBER"
    )
    query_tag_count_expr = (
        "COUNT(DISTINCT NULLIF(q.query_tag, ''))"
        if "QUERY_TAG" in qh_cols else "0::NUMBER"
    )
    session_program_expr = (
        "COALESCE(TO_VARCHAR(s.client_application_id), 'UNKNOWN')"
        if "CLIENT_APPLICATION_ID" in session_cols else "'UNKNOWN'"
    )
    session_version_candidates = []
    if "CLIENT_APPLICATION_VERSION" in session_cols:
        session_version_candidates.append("TO_VARCHAR(s.client_application_version)")
    if "CLIENT_VERSION" in session_cols:
        session_version_candidates.append("TO_VARCHAR(s.client_version)")
    session_version_expr = (
        f"COALESCE({', '.join(session_version_candidates)}, 'UNKNOWN')"
        if session_version_candidates else "'UNKNOWN'"
    )
    session_build_expr = (
        "COALESCE(TO_VARCHAR(s.client_build_id), 'UNKNOWN')"
        if "CLIENT_BUILD_ID" in session_cols else "'UNKNOWN'"
    )
    session_env_count_expr = (
        "COUNT(DISTINCT s.client_environment)"
        if "CLIENT_ENVIRONMENT" in session_cols else "0::NUMBER"
    )
    open_sessions_expr = (
        "SUM(IFF(s.is_open, 1, 0))"
        if "IS_OPEN" in session_cols else "NULL::NUMBER"
    )
    access_time_expr = (
        "MAX(s.access_time)"
        if "ACCESS_TIME" in session_cols else "MAX(s.created_on)"
    )
    auth_method_count_expr = (
        "COUNT(DISTINCT s.authentication_method)"
        if "AUTHENTICATION_METHOD" in session_cols else "0::NUMBER"
    )
    can_join_sessions = "SESSION_ID" in qh_cols and "SESSION_ID" in session_cols
    can_join_login = "AUTHN_EVENT_ID" in qh_cols and "EVENT_ID" in login_cols
    if can_join_sessions:
        program_expr = session_program_expr
        version_expr = session_version_expr
        source_expr = "'QUERY_HISTORY session_id to SESSIONS client metadata'"
        join_sql = f"""
            LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.SESSIONS s
              ON q.session_id = s.session_id
             AND s.created_on >= DATEADD('day', -{query_join_days}, CURRENT_TIMESTAMP())
        """
    elif can_join_login:
        program_expr = login_program_expr
        version_expr = login_version_expr
        source_expr = "'AUTHN_EVENT_ID to LOGIN_HISTORY reported client; client value is reported, not authenticated'"
        join_sql = f"""
            LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY l
              ON q.authn_event_id = l.event_id
             AND l.event_timestamp >= DATEADD('day', -{query_join_days}, CURRENT_TIMESTAMP())
        """
    else:
        program_expr = (
            "COALESCE(NULLIF(TO_VARCHAR(q.query_tag), ''), 'UNTAGGED')"
            if "QUERY_TAG" in qh_cols else "'UNKNOWN'"
        )
        version_expr = "'UNKNOWN'"
        source_expr = "'QUERY_TAG fallback; not exact connected-program identity'"
        join_sql = ""

    session_inventory = pd.DataFrame()
    if "CREATED_ON" in session_cols and "USER_NAME" in session_cols:
        session_user_filter = get_user_filter_clause("s.user_name")
        session_inventory = run_query(f"""
            SELECT
                {session_program_expr} AS program_name,
                {session_version_expr} AS program_version,
                {session_build_expr} AS client_build,
                COUNT(*) AS sessions,
                {open_sessions_expr} AS open_sessions,
                COUNT(DISTINCT s.user_name) AS users,
                {auth_method_count_expr} AS authentication_methods,
                {session_env_count_expr} AS client_environments,
                MIN(s.created_on) AS first_seen,
                {access_time_expr} AS last_seen,
                'SESSIONS client metadata; open-session status can lag up to 3 hours' AS source_confidence
            FROM SNOWFLAKE.ACCOUNT_USAGE.SESSIONS s
            WHERE s.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              {session_user_filter}
            GROUP BY program_name, program_version, client_build
            ORDER BY sessions DESC
            LIMIT 100
        """, ttl_key=f"security_connected_sessions_{company}_{days}", tier="standard", section="Security Access")

    login_inventory = run_query(f"""
        SELECT
            {login_program_expr} AS program_name,
            {login_version_expr} AS program_version,
            COUNT(*) AS login_events,
            COUNT(DISTINCT l.user_name) AS users,
            {login_ip_count_expr} AS ips,
            SUM(IFF(l.is_success = 'YES', 1, 0)) AS success_events,
            SUM(IFF(l.is_success = 'NO', 1, 0)) AS failed_events,
            MAX(l.event_timestamp) AS last_seen,
            'Login-only reported client; no database context' AS source_confidence
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY l
        WHERE l.event_timestamp >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {user_filter}
        GROUP BY program_name, program_version
        ORDER BY login_events DESC
        LIMIT 100
    """, ttl_key=f"security_connected_login_programs_{company}_{days}", tier="standard", section="Security Access")

    query_programs = run_query(f"""
        SELECT
            {program_expr} AS program_name,
            {version_expr} AS program_version,
            q.warehouse_name,
            COALESCE(q.database_name, 'UNKNOWN') AS database_name,
            COUNT(*) AS query_count,
            COUNT(DISTINCT q.user_name) AS users,
            COUNT(DISTINCT q.role_name) AS roles,
            {failed_query_expr} AS failed_queries,
            ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
            {client_generated_expr} AS client_generated_queries,
            {query_tag_count_expr} AS query_tags,
            MAX(q.start_time) AS last_query_time,
            {source_expr} AS source_confidence
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
        {join_sql}
        WHERE q.start_time >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND q.warehouse_name IS NOT NULL
          {query_filters}
        GROUP BY program_name, program_version, q.warehouse_name, database_name, source_confidence
        ORDER BY query_count DESC
        LIMIT 200
    """, ttl_key=f"security_connected_query_programs_{company}_{days}", tier="standard", section="Security Access")

    return {
        "sec_connected_session_programs": _annotate_connected_programs(session_inventory),
        "sec_connected_login_programs": _annotate_connected_programs(login_inventory),
        "sec_connected_query_programs": _annotate_connected_programs(query_programs),
    }


def _load_grants_mart(company: str) -> pd.DataFrame:
    """Load active role grants from the grant snapshot mart."""
    table = mart_object_name("FACT_GRANT_DAILY")
    company_filter = _mart_company_filter("g", company)
    user_filter = get_user_filter_clause("g.grantee_name")
    return run_query(f"""
        WITH latest AS (
            SELECT MAX(snapshot_date) AS snapshot_date
            FROM {table}
        )
        SELECT
            g.grantee_name,
            g.role_name AS role,
            g.granted_to,
            NULL::VARCHAR AS granted_by,
            MIN(g.created_on) AS created_on,
            NULL::TIMESTAMP_NTZ AS deleted_on
        FROM {table} g
        JOIN latest l ON g.snapshot_date = l.snapshot_date
        WHERE g.deleted_on IS NULL
          {company_filter}
          {user_filter}
        GROUP BY g.grantee_name, g.role_name, g.granted_to
        ORDER BY created_on DESC
        LIMIT 500
    """, ttl_key=f"security_mart_grants_to_users_{company}", tier="standard", section="Security Access")


_SENSITIVE_ACCOUNT_ROLES = {
    "ACCOUNTADMIN",
    "ORGADMIN",
    "SECURITYADMIN",
    "SYSADMIN",
    "USERADMIN",
}


def _normalize_access_identifier(name: str, object_type: str) -> str:
    """Normalize account role/user input while rejecting ambiguous identifiers."""
    value = str(name or "").strip()
    if not value:
        raise ValueError(f"{object_type} is required.")
    if any(ch in value for ch in [";", "\n", "\r", "\x00"]):
        raise ValueError(f"{object_type} contains unsupported control characters.")
    if "." in value:
        raise ValueError(
            f"{object_type} must be an account-level identifier. Database roles are not supported by this control yet."
        )
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1].replace('""', '"')
    else:
        value = value.upper()
    if not value:
        raise ValueError(f"{object_type} is required.")
    return value


def _quote_access_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _role_grant_risk_notes(action: str, role_name: str, grantee_type: str, grantee_name: str) -> list[str]:
    action = str(action or "").upper()
    role_name = str(role_name or "").upper()
    grantee_type = str(grantee_type or "").upper()
    grantee_name = str(grantee_name or "").upper()
    notes = [
        "Account-role grants are account-wide; company and environment are audit scope, not enforcement boundaries.",
        "Confirm requester, approver, owner, ticket, and least-privilege justification before applying.",
    ]
    if role_name in _SENSITIVE_ACCOUNT_ROLES or role_name.endswith("ADMIN"):
        notes.append("High risk: this role can materially change account administration or broad object access.")
    if grantee_name in _SENSITIVE_ACCOUNT_ROLES or grantee_name.endswith("ADMIN"):
        notes.append("High risk: the grantee is an administrative role; inherited blast radius may be broad.")
    if grantee_type == "ROLE":
        notes.append("Inheritance risk: role-to-role grants can expand access for many users indirectly.")
    if action == "REVOKE":
        notes.append("Availability risk: revoking a role can break jobs, procedures, tasks, or service users.")
    else:
        notes.append("Access expansion risk: granting a role may expose data, warehouses, or administrative actions.")
    return notes


def _role_grant_risk_level(notes: list[str]) -> str:
    text = " ".join(notes).lower()
    if text.count("high risk") >= 2:
        return "Critical"
    if "high risk" in text and "inheritance risk" in text:
        return "Critical"
    if "high risk" in text or "inheritance risk" in text:
        return "High"
    if "availability risk" in text or "access expansion risk" in text:
        return "Medium"
    return "Low"


def _role_grant_usage_check_sql(role_name: str, grantee_type: str, grantee_name: str) -> str:
    role_like = sql_literal(role_name, 300)
    grantee_like = sql_literal(grantee_name, 300)
    if grantee_type == "USER":
        return f"""SELECT grantee_name,
       role,
       granted_to,
       granted_by,
       created_on,
       deleted_on
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
WHERE role = {role_like}
  AND grantee_name = {grantee_like}
  AND deleted_on IS NULL
ORDER BY created_on DESC;"""
    return f"""SELECT grantee_name,
       name AS role,
       granted_on,
       granted_by,
       created_on,
       deleted_on
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
WHERE granted_on = 'ROLE'
  AND name = {role_like}
  AND grantee_name = {grantee_like}
  AND deleted_on IS NULL
ORDER BY created_on DESC;"""


def _role_grant_capability_check_sql() -> str:
    return """SELECT CURRENT_ROLE() AS active_role,
       COUNT_IF(privilege = 'MANAGE GRANTS' AND granted_on = 'ACCOUNT') AS direct_manage_grants_privileges
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
WHERE grantee_name = CURRENT_ROLE()
  AND deleted_on IS NULL;

-- If DIRECT_MANAGE_GRANTS_PRIVILEGES is 0, confirm inherited role hierarchy or role ownership before applying.
"""


def _role_grant_blast_radius_sql(grantee_type: str, grantee_name: str) -> str:
    if grantee_type != "ROLE":
        return "-- Direct user grant/revoke: blast radius is the named user only."
    grantee_like = sql_literal(grantee_name, 300)
    return f"""SELECT role AS impacted_role,
       COUNT(DISTINCT grantee_name) AS direct_users_with_impacted_role,
       LISTAGG(DISTINCT grantee_name, ', ') WITHIN GROUP (ORDER BY grantee_name) AS sample_direct_users
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
WHERE role = {grantee_like}
  AND deleted_on IS NULL
GROUP BY role;

SELECT grantee_name AS parent_role,
       name AS granted_role,
       granted_by,
       created_on
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
WHERE grantee_name = {grantee_like}
  AND granted_on = 'ROLE'
  AND deleted_on IS NULL
ORDER BY created_on DESC;
"""


def _role_grant_plan_signature(
    action: str,
    role_name: str,
    grantee_type: str,
    grantee_name: str,
    justification: str,
    access_owner: str = "",
    approver: str = "",
    ticket_id: str = "",
    review_by: str = "",
) -> str:
    action = str(action or "").upper().strip()
    grantee_type = str(grantee_type or "").upper().strip()
    role = _normalize_access_identifier(role_name, "Role")
    grantee = _normalize_access_identifier(grantee_name, grantee_type.title() if grantee_type else "Grantee")
    return "|".join([
        action,
        role,
        grantee_type,
        grantee,
        str(justification or "").strip(),
        str(access_owner or "").strip(),
        str(approver or "").strip(),
        str(ticket_id or "").strip(),
        str(review_by or "").strip(),
    ])


def _access_control_metadata(
    *,
    access_owner: str = "",
    approver: str = "",
    ticket_id: str = "",
    review_by: str = "",
) -> dict:
    owner = str(access_owner or "").strip()
    approver = str(approver or "").strip()
    ticket = str(ticket_id or "").strip()
    review = str(review_by or "").strip()
    missing = []
    if not owner:
        missing.append("access owner")
    if not approver:
        missing.append("approver")
    if not ticket:
        missing.append("ticket")
    if not review:
        missing.append("review/expiry date")
    return {
        "access_owner": owner,
        "approver": approver,
        "ticket_id": ticket,
        "review_by": review,
        "missing": missing,
        "complete": not missing,
    }


def _role_grant_preflight_sql(role_name: str, grantee_type: str, grantee_name: str) -> str:
    role_ident = _quote_access_identifier(role_name)
    grantee_ident = _quote_access_identifier(grantee_name)
    role_like = sql_literal(role_name, 300)
    grantee_like = sql_literal(grantee_name, 300)
    target_show = (
        f"SHOW GRANTS TO USER {grantee_ident};"
        if grantee_type == "USER"
        else f"SHOW GRANTS TO ROLE {grantee_ident};"
    )
    target_exists = (
        f"SHOW USERS LIKE {grantee_like};"
        if grantee_type == "USER"
        else f"SHOW ROLES LIKE {grantee_like};"
    )
    usage_check = _role_grant_usage_check_sql(role_name, grantee_type, grantee_name)
    return f"""-- Read-only pre-flight before account-role grant change
SELECT CURRENT_USER() AS current_user,
       CURRENT_ROLE() AS current_role,
       CURRENT_WAREHOUSE() AS current_warehouse;

SHOW ROLES LIKE {role_like};
{target_exists}

SHOW GRANTS OF ROLE {role_ident};
{target_show}

-- Active-role capability check
{_role_grant_capability_check_sql()}

-- Blast-radius evidence
{_role_grant_blast_radius_sql(grantee_type, grantee_name)}

{usage_check}

-- Confirm owner approval, change ticket, least privilege, and rollback before applying.
"""


def _role_grant_verification_sql(role_name: str, grantee_type: str, grantee_name: str) -> str:
    grantee_ident = _quote_access_identifier(grantee_name)
    target_show = (
        f"SHOW GRANTS TO USER {grantee_ident};"
        if grantee_type == "USER"
        else f"SHOW GRANTS TO ROLE {grantee_ident};"
    )
    return f"""-- Post-change verification
{target_show}

{_role_grant_usage_check_sql(role_name, grantee_type, grantee_name)}

-- Attach this evidence to the access ticket and the OVERWATCH admin audit row.
"""


def _build_role_grant_change_plan(
    action: str,
    role_name: str,
    grantee_type: str,
    grantee_name: str,
    justification: str = "",
    access_owner: str = "",
    approver: str = "",
    ticket_id: str = "",
    review_by: str = "",
) -> dict:
    """Build a guarded account-role GRANT/REVOKE plan with rollback context."""
    action = str(action or "").upper().strip()
    grantee_type = str(grantee_type or "").upper().strip()
    if action not in {"GRANT", "REVOKE"}:
        raise ValueError("Action must be GRANT or REVOKE.")
    if grantee_type not in {"USER", "ROLE"}:
        raise ValueError("Grantee type must be USER or ROLE.")

    role = _normalize_access_identifier(role_name, "Role")
    grantee = _normalize_access_identifier(grantee_name, grantee_type.title())
    role_ident = _quote_access_identifier(role)
    grantee_ident = _quote_access_identifier(grantee)

    forward_join = "TO" if action == "GRANT" else "FROM"
    inverse_action = "REVOKE" if action == "GRANT" else "GRANT"
    inverse_join = "FROM" if action == "GRANT" else "TO"
    change_sql = f"{action} ROLE {role_ident} {forward_join} {grantee_type} {grantee_ident};"
    rollback_sql = f"{inverse_action} ROLE {role_ident} {inverse_join} {grantee_type} {grantee_ident};"

    clean_justification = str(justification or "").strip()
    metadata = _access_control_metadata(
        access_owner=access_owner,
        approver=approver,
        ticket_id=ticket_id,
        review_by=review_by,
    )
    risk_notes = _role_grant_risk_notes(action, role, grantee_type, grantee)
    if not clean_justification:
        risk_notes.append("Missing business justification: do not apply without a ticket or approver record.")
    if metadata["missing"]:
        risk_notes.append(
            "Missing accountability metadata: " + ", ".join(metadata["missing"]) + "."
        )
    risk_level = _role_grant_risk_level(risk_notes)
    confirmation_text = f"{action} {role} {forward_join} {grantee_type} {grantee}"
    control_context_lines = [
        f"Action: {confirmation_text}",
        f"Risk level: {risk_level}",
        f"Access owner: {metadata['access_owner']}",
        f"Approver: {metadata['approver']}",
        f"Ticket: {metadata['ticket_id']}",
        f"Review by: {metadata['review_by']}",
        f"Justification: {clean_justification[:800]}",
        "Rollback SQL: " + rollback_sql,
    ]
    control_context_lines.extend(f"Risk: {note}" for note in risk_notes)

    return {
        "action": action,
        "role": role,
        "grantee_type": grantee_type,
        "grantee": grantee,
        "target_object": f"ROLE {role} {forward_join} {grantee_type} {grantee}",
        "change_sql": change_sql,
        "rollback_sql": rollback_sql,
        "preflight_sql": _role_grant_preflight_sql(role, grantee_type, grantee),
        "verification_sql": _role_grant_verification_sql(role, grantee_type, grantee),
        "risk_level": risk_level,
        "risk_notes": risk_notes,
        "risk_df": pd.DataFrame({"RISK_LEVEL": [risk_level] * len(risk_notes), "RISK_NOTE": risk_notes}),
        "justification": clean_justification,
        "access_owner": metadata["access_owner"],
        "approver": metadata["approver"],
        "ticket_id": metadata["ticket_id"],
        "review_by": metadata["review_by"],
        "metadata_complete": metadata["complete"],
        "missing_metadata": metadata["missing"],
        "input_signature": _role_grant_plan_signature(
            action,
            role,
            grantee_type,
            grantee,
            clean_justification,
            metadata["access_owner"],
            metadata["approver"],
            metadata["ticket_id"],
            metadata["review_by"],
        ),
        "confirmation_text": confirmation_text,
        "control_context": "\n".join(control_context_lines)[:4000],
    }


def _build_access_action_queue_record(plan: dict, company: str) -> dict:
    ticket = str(plan.get("ticket_id") or "NO_TICKET")
    entity = str(plan.get("target_object") or plan.get("confirmation_text") or "")
    finding = f"{plan.get('confirmation_text', 'Access change')} awaiting DBA approval/execution ({ticket})."
    recommended = (
        f"Validate requester, owner {plan.get('access_owner') or 'UNKNOWN'}, approver "
        f"{plan.get('approver') or 'UNKNOWN'}, least privilege, and review date "
        f"{plan.get('review_by') or 'UNKNOWN'} before applying. After execution, run the verification SQL "
        "and attach the evidence to the ticket."
    )
    proof = (
        "-- Pre-flight SQL\n"
        + str(plan.get("preflight_sql") or "")
        + "\n-- Post-change verification SQL\n"
        + str(plan.get("verification_sql") or "")
    )
    return {
        "Action ID": make_action_id("Access Control", entity, ticket + "|" + finding),
        "Source": "Security Posture - Role & Grant Change Control",
        "Severity": plan.get("risk_level", "Medium"),
        "Category": "Security",
        "Entity Type": "Role Grant",
        "Entity": entity,
        "Owner": plan.get("access_owner") or "Security/DBA",
        "Finding": finding,
        "Action": recommended,
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": plan.get("change_sql", ""),
        "Proof Query": proof[:8000],
        "Company": company,
    }


def _build_role_grant_control_board(plan: dict) -> tuple[dict, pd.DataFrame]:
    """Summarize the current role-grant plan as a compact DBA control plane."""
    rows = [
        {
            "CONTROL": "Risk notes",
            "STATE": "Ready" if plan.get("risk_notes") else "Review",
            "EVIDENCE": f"{len(plan.get('risk_notes') or []):,} note(s) flagged for DBA review.",
            "NEXT_ACTION": "Read the notes before queueing or applying the access change.",
        },
        {
            "CONTROL": "Metadata completeness",
            "STATE": "Ready" if plan.get("metadata_complete") else "Blocked",
            "EVIDENCE": "Owner, approver, ticket, and review/expiry date are present." if plan.get("metadata_complete") else "Owner accountability fields are missing.",
            "NEXT_ACTION": "Fill all required accountability fields before queueing.",
        },
        {
            "CONTROL": "Pre-flight SQL",
            "STATE": "Ready" if plan.get("preflight_sql") else "Blocked",
            "EVIDENCE": "Read-only pre-flight evidence is attached." if plan.get("preflight_sql") else "No pre-flight query generated.",
            "NEXT_ACTION": "Run the pre-flight SQL and attach the proof.",
        },
        {
            "CONTROL": "Change SQL",
            "STATE": "Ready" if plan.get("change_sql") else "Blocked",
            "EVIDENCE": "Forward GRANT/REVOKE SQL is prepared." if plan.get("change_sql") else "No change SQL generated.",
            "NEXT_ACTION": "Apply only after owner approval and typed confirmation.",
        },
        {
            "CONTROL": "Rollback SQL",
            "STATE": "Ready" if plan.get("rollback_sql") else "Blocked",
            "EVIDENCE": "Rollback SQL is attached." if plan.get("rollback_sql") else "No rollback SQL generated.",
            "NEXT_ACTION": "Keep rollback visible before executing the access change.",
        },
        {
            "CONTROL": "Verification SQL",
            "STATE": "Ready" if plan.get("verification_sql") else "Blocked",
            "EVIDENCE": "Post-change verification SQL is attached." if plan.get("verification_sql") else "No verification SQL generated.",
            "NEXT_ACTION": "Run verification after execution and attach the result to the ticket.",
        },
        {
            "CONTROL": "Audit trail",
            "STATE": "Ready" if plan.get("control_context") else "Review",
            "EVIDENCE": "Admin audit metadata is prepared for the change." if plan.get("control_context") else "No admin audit context prepared.",
            "NEXT_ACTION": "Log STARTED, SUCCESS, and VERIFY_REQUIRED states with the admin audit table.",
        },
    ]
    board = pd.DataFrame(rows)
    state_rank = {"Blocked": 0, "Review": 1, "Ready": 2}
    board["_RANK"] = board["STATE"].map(state_rank).fillna(9)
    score = max(0, min(100, 100 - int((board["STATE"] == "Blocked").sum()) * 24 - int((board["STATE"] == "Review").sum()) * 10))
    return {
        "score": score,
        "blocked": int((board["STATE"] == "Blocked").sum()),
        "review": int((board["STATE"] == "Review").sum()),
        "ready": int((board["STATE"] == "Ready").sum()),
    }, board.sort_values(["_RANK", "CONTROL"]).drop(columns=["_RANK"], errors="ignore")


def _render_role_grant_change_control(session, company: str) -> None:
    st.divider()
    st.subheader("Role & Grant Change Control")
    st.caption(
        "Account roles only. This prepares DBA-reviewed GRANT/REVOKE SQL with pre-flight evidence, rollback SQL, "
        "typed confirmation, and admin audit logging."
    )

    plan_key = "sec_role_grant_plan"
    c1, c2 = st.columns(2)
    with c1:
        action = st.selectbox("Action", ["GRANT", "REVOKE"], key="sec_rg_action")
        role_name = st.text_input("Account role", key="sec_rg_role", placeholder="APP_READONLY")
    with c2:
        grantee_type = st.selectbox("Grantee type", ["USER", "ROLE"], key="sec_rg_grantee_type")
        grantee_name = st.text_input("Grantee", key="sec_rg_grantee", placeholder="USER_OR_ROLE_NAME")
    justification = st.text_area(
        "Business justification / ticket",
        key="sec_rg_justification",
        placeholder="INC12345 approved by data owner for read-only ALFA support access.",
        height=90,
    )
    m1, m2 = st.columns(2)
    with m1:
        access_owner = st.text_input("Access owner", key="sec_rg_owner", placeholder="Data owner or accountable team")
        ticket_id = st.text_input("Ticket / request ID", key="sec_rg_ticket", placeholder="INC12345")
    with m2:
        approver = st.text_input("Approver", key="sec_rg_approver", placeholder="Approver name or role")
        review_by = st.text_input("Review / expiry date", key="sec_rg_review_by", placeholder="YYYY-MM-DD")

    if st.button("Build Role Grant Plan", key="sec_rg_build_plan"):
        try:
            st.session_state[plan_key] = _build_role_grant_change_plan(
                action,
                role_name,
                grantee_type,
                grantee_name,
                justification,
                access_owner,
                approver,
                ticket_id,
                review_by,
            )
        except Exception as e:
            st.session_state.pop(plan_key, None)
            st.error(format_snowflake_error(e))

    plan = st.session_state.get(plan_key)
    if not plan:
        return

    st.markdown(f"**Reviewed Access Change Plan: {plan['risk_level']} Risk**")
    board_summary, board = _build_role_grant_control_board(plan)
    c1, c2, c3 = st.columns(3)
    c1.metric("Ready", f"{board_summary['ready']:,}")
    c2.metric("Review", f"{board_summary['review']:,}", delta_color="inverse")
    c3.metric("Blocked", f"{board_summary['blocked']:,}", delta_color="inverse")
    render_priority_dataframe(
        board,
        title="Role grant control plane",
        priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION"],
        sort_by=["STATE", "CONTROL"],
        ascending=[True, True],
        raw_label="All role grant control rows",
        height=240,
    )
    render_priority_dataframe(
        plan["risk_df"],
        title="Risk notes requiring DBA review",
        priority_columns=["RISK_LEVEL", "RISK_NOTE"],
        sort_by=["RISK_NOTE"],
        ascending=True,
        raw_label="All access-control risk notes",
        height=220,
    )
    with st.expander("Read-only pre-flight SQL", expanded=True):
        st.code(plan["preflight_sql"], language="sql")
    with st.expander("SQL to apply", expanded=True):
        st.code(plan["change_sql"], language="sql")
    with st.expander("Rollback SQL", expanded=False):
        st.code(plan["rollback_sql"], language="sql")
    with st.expander("Post-change verification SQL", expanded=False):
        st.code(plan["verification_sql"], language="sql")

    try:
        current_signature = _role_grant_plan_signature(
            action,
            role_name,
            grantee_type,
            grantee_name,
            justification,
            access_owner,
            approver,
            ticket_id,
            review_by,
        )
    except Exception:
        current_signature = ""
    plan_is_current = current_signature == plan.get("input_signature")
    if not plan_is_current:
        st.warning("The form changed after this plan was built. Rebuild the plan before applying.")
    if not plan.get("metadata_complete"):
        st.warning("Owner, approver, ticket, and review/expiry date are required before queueing or applying.")

    q1, q2 = st.columns([1, 3])
    with q1:
        if st.button(
            "Queue Access Request",
            key="sec_rg_queue_request",
            disabled=not plan_is_current or not plan.get("metadata_complete") or bool(plan.get("queued")),
        ):
            try:
                saved = upsert_actions(session, [_build_access_action_queue_record(plan, company)])
                st.session_state[plan_key]["queued"] = True
                st.success(f"Queued {saved} access request for review.")
            except Exception as e:
                st.error(f"Could not queue access request: {format_snowflake_error(e)}")
    with q2:
        st.caption(
            "Queueing creates an OVERWATCH_ACTION_QUEUE item with owner, approver, ticket, SQL, "
            "pre-flight proof, rollback, and verification instructions."
        )

    confirmed = st.text_input(
        f"Type {plan['confirmation_text']} to apply this access change",
        key="sec_rg_confirm",
        placeholder=plan["confirmation_text"],
    ).strip() == plan["confirmation_text"]
    has_justification = bool(str(plan.get("justification", "") or "").strip())
    if not has_justification:
        st.warning("A business justification or ticket is required before applying the access change.")

    apply_disabled = (
        not confirmed
        or not has_justification
        or not plan_is_current
        or not plan.get("metadata_complete")
        or bool(plan.get("applied"))
    )
    if st.button(
        "Apply Access Change",
        type="primary",
        key="sec_rg_apply",
        disabled=admin_button_disabled(apply_disabled),
    ):
        environment = get_active_environment()
        try:
            log_admin_action(
                session,
                action_type=f"{plan['action']} ROLE",
                target_object=plan["target_object"],
                sql_text=plan["change_sql"],
                result_status="STARTED",
                result_message="Role grant change submitted from OVERWATCH.",
                confirmation_text=plan["confirmation_text"],
                control_context=plan["control_context"],
                company=company,
                environment=environment,
            )
            session.sql(plan["change_sql"]).collect()
            audited = log_admin_action(
                session,
                action_type=f"{plan['action']} ROLE",
                target_object=plan["target_object"],
                sql_text=plan["change_sql"],
                result_status="SUCCESS",
                result_message="Role grant change completed.",
                confirmation_text=plan["confirmation_text"],
                control_context=plan["control_context"],
                company=company,
                environment=environment,
            )
            log_admin_action(
                session,
                action_type=f"VERIFY {plan['action']} ROLE",
                target_object=plan["target_object"],
                sql_text=plan["verification_sql"],
                result_status="VERIFY_REQUIRED",
                result_message=(
                    "Run post-change verification SQL and attach the result to "
                    f"{plan.get('ticket_id') or 'the access ticket'}."
                ),
                confirmation_text=plan["confirmation_text"],
                control_context=plan["control_context"],
                company=company,
                environment=environment,
            )
            st.session_state[plan_key]["applied"] = True
            st.success("Access change completed.")
            if not audited:
                st.warning("The access change completed, but the admin audit table was unavailable or not writable.")
            st.session_state.pop("sec_df_grants", None)
        except Exception as e:
            err = format_snowflake_error(e)
            log_admin_action(
                session,
                action_type=f"{plan['action']} ROLE",
                target_object=plan["target_object"],
                sql_text=plan["change_sql"],
                result_status="FAILED",
                result_message=err,
                confirmation_text=plan["confirmation_text"],
                control_context=plan["control_context"],
                company=company,
                environment=environment,
            )
            err_text = str(e).lower()
            if "insufficient privilege" in err_text or "not authorized" in err_text:
                st.error("Permission denied. Role changes require an active Snowflake role with role-management privileges.")
            else:
                st.error(f"Access change failed: {err}")


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
            finding = f"{user} had {safe_int(row.get('ATTEMPT_COUNT', 0))} failed login attempts from {row.get('CLIENT_IP', 'unknown IP')}"
            action = "Validate whether attempts are expected; review identity provider logs and lock/disable user if suspicious."
            proof = "LOGIN_HISTORY failed login attempts."
        elif finding_type == "Dormant User":
            entity = user
            finding = f"{user} is active but has been dormant for {safe_int(row.get('DAYS_SINCE_LOGIN', 0))} days"
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
            "Source": f"Security Posture - {finding_type}",
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
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _annotate_security_routes(df: pd.DataFrame, finding_type: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    routed = df.copy()
    if finding_type == "Failed Login":
        routed["NEXT_WORKFLOW"] = "Security Posture"
        routed["NEXT_ACTION"] = "Compare source IP, client, error code, and IAM logs; disable or escalate only after confirming suspicious activity."
    elif finding_type == "Grant Review":
        routed["NEXT_WORKFLOW"] = "Security Posture"
        routed["NEXT_ACTION"] = "Validate requester, approver, role hierarchy, and business justification before revoking or narrowing access."
    elif finding_type == "Dormant User":
        routed["NEXT_WORKFLOW"] = "Security Posture"
        routed["NEXT_ACTION"] = "Confirm owner and service-account status, then disable or remove roles through approved access process."
    elif finding_type == "No MFA":
        routed["NEXT_WORKFLOW"] = "Security Posture"
        routed["NEXT_ACTION"] = "Confirm authentication path and enforce MFA through Snowflake or the identity provider."
    elif finding_type == "Exfiltration":
        routed["NEXT_WORKFLOW"] = "Query workbench"
        routed["NEXT_ACTION"] = "Open query text and result output context, confirm business purpose, and escalate to security if unexplained."
    else:
        routed["NEXT_WORKFLOW"] = "Security Posture"
        routed["NEXT_ACTION"] = "Validate owner, evidence, and risk before changing grants, authentication, or user status."
    return routed


def render():
    company = get_active_company()
    user_filter = get_user_filter_clause("user_name")
    user_filter_u = get_user_filter_clause("u.name")
    user_filter_g = get_user_filter_clause("grantee_name")
    query_scope = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    query_history_cols = None
    user_cols = None

    def _query_history_columns() -> set[str]:
        nonlocal query_history_cols
        if query_history_cols is None:
            query_history_cols = set(filter_existing_columns(
                get_session(),
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                ["WAREHOUSE_SIZE", "ROWS_PRODUCED", "BYTES_WRITTEN_TO_RESULT"],
            ))
        return query_history_cols

    def _user_column_exprs() -> dict[str, str]:
        nonlocal user_cols
        if user_cols is None:
            user_cols = set(filter_existing_columns(
                get_session(),
                "SNOWFLAKE.ACCOUNT_USAGE.USERS",
                ["LAST_SUCCESS_LOGIN", "HAS_PASSWORD", "HAS_MFA", "EXT_AUTHN_DUO"],
            ))
        return _user_mfa_column_exprs(user_cols)

    active_view = st.radio(
        "Security Access view",
        SECURITY_ACCESS_PANES,
        horizontal=True,
        label_visibility="collapsed",
        key="security_access_active_view",
    )

    # -- LOGIN AUDIT -----------------------------------------------------------
    if active_view == "Login Audit":
        st.header("Login Audit")
        sec_days = st.slider("Lookback (days)", 1, 90, 30, key="sec_days")

        if st.button("Load Login Data", key="sec_load"):
            try:
                for key, df in _load_login_audit_mart(company, sec_days).items():
                    st.session_state[key] = df
                st.session_state["sec_login_source"] = "OVERWATCH mart: FACT_LOGIN_DAILY"
            except Exception as mart_exc:
                st.session_state["sec_login_source"] = "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY"
                defer_source_note(f"Mart path skipped: {format_snowflake_error(mart_exc)}")
            if st.session_state.get("sec_login_source") != "OVERWATCH mart: FACT_LOGIN_DAILY":
                for key, sql in [
                    ("sec_df_login_sum", f"""
                        SELECT is_success, COUNT(*) AS event_count,
                               COUNT(DISTINCT user_name) AS distinct_users,
                               COUNT(DISTINCT client_ip) AS distinct_ips
                        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                        WHERE event_timestamp >= DATEADD('day', -{sec_days}, CURRENT_TIMESTAMP())
                          {user_filter}
                        GROUP BY is_success
                    """),
                    ("sec_df_failed_logins", f"""
                        SELECT user_name, client_ip, reported_client_type, error_code,
                               COUNT(*) AS attempt_count,
                               MAX(event_timestamp) AS last_attempt
                        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                        WHERE event_timestamp >= DATEADD('day', -{sec_days}, CURRENT_TIMESTAMP())
                          AND is_success = 'NO'
                          {user_filter}
                        GROUP BY user_name, client_ip, reported_client_type, error_code
                        ORDER BY attempt_count DESC LIMIT 50
                    """),
                    ("sec_df_login_trend", f"""
                        SELECT DATE_TRUNC('day', event_timestamp) AS day,
                               is_success, COUNT(*) AS event_count
                        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                        WHERE event_timestamp >= DATEADD('day', -{sec_days}, CURRENT_TIMESTAMP())
                          {user_filter}
                        GROUP BY day, is_success ORDER BY day
                    """),
                ]:
                    try:
                        st.session_state[key] = run_query(sql, ttl_key=f"security_{company}_{key}_{sec_days}", tier="standard")
                    except Exception:
                        st.session_state[key] = pd.DataFrame()

        if st.session_state.get("sec_df_login_sum") is not None and not st.session_state["sec_df_login_sum"].empty:
            df_ls = st.session_state["sec_df_login_sum"]
            defer_source_note(st.session_state.get("sec_login_source", "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY"))
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
            failed_logins = _annotate_security_routes(st.session_state["sec_df_failed_logins"], "Failed Login")
            render_priority_dataframe(
                failed_logins,
                title="Failed-login exceptions to review first",
                priority_columns=[
                    "USER_NAME", "CLIENT_IP", "REPORTED_CLIENT_TYPE", "ERROR_CODE",
                    "ATTEMPT_COUNT", "LAST_ATTEMPT", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["ATTEMPT_COUNT", "LAST_ATTEMPT"],
                ascending=[False, False],
                raw_label="All failed-login rows",
            )
            download_csv(failed_logins, "failed_logins.csv")
            if st.button("Save failed-login findings to Action Queue", key="sec_failed_login_queue"):
                _queue_security_findings(get_session(), failed_logins, "Failed Login", "Medium")

        if st.session_state.get("sec_df_login_trend") is not None and not st.session_state["sec_df_login_trend"].empty:
            df_t = st.session_state["sec_df_login_trend"]
            pivot = df_t.pivot_table(index="DAY", columns="IS_SUCCESS", values="EVENT_COUNT", aggfunc="sum").fillna(0)
            st.subheader("Login Trend")
            st.line_chart(pivot)

    elif active_view == "Login Posture":
        st.header("Login Posture")
        posture_days = st.slider("Posture lookback (days)", 1, 90, 30, key="sec_posture_days")
        if st.button("Load Login Posture", key="sec_posture_load"):
            try:
                for key, df in _load_login_posture_mart(company, posture_days).items():
                    st.session_state[key] = df
                st.session_state["sec_login_posture_source"] = "OVERWATCH mart: FACT_LOGIN_DAILY"
            except Exception as mart_exc:
                st.session_state["sec_login_posture_source"] = "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY"
                defer_source_note(f"Mart path skipped: {format_snowflake_error(mart_exc)}")
                for key in ("sec_login_ips", "sec_login_clients"):
                    st.session_state[key] = pd.DataFrame()
            for key, sql in [
                *([] if st.session_state.get("sec_login_posture_source") == "OVERWATCH mart: FACT_LOGIN_DAILY" else [("sec_login_ips", f"""
                    SELECT client_ip, COUNT(*) AS login_events,
                           COUNT(DISTINCT user_name) AS users,
                           SUM(IFF(is_success = 'YES', 1, 0)) AS success_events,
                           SUM(IFF(is_success = 'NO', 1, 0)) AS failed_events,
                           MAX(event_timestamp) AS last_seen
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{posture_days}, CURRENT_TIMESTAMP())
                      {user_filter}
                    GROUP BY client_ip
                    ORDER BY login_events DESC
                    LIMIT 50
                """),
                ("sec_login_clients", f"""
                    WITH base AS (
                        SELECT TO_VARCHAR(reported_client_type) AS reported_client_type,
                               TO_VARCHAR(reported_client_version) AS reported_client_version,
                               user_name,
                               is_success
                        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                        WHERE event_timestamp >= DATEADD('day', -{posture_days}, CURRENT_TIMESTAMP())
                          {user_filter}
                    )
                    SELECT COALESCE(reported_client_type, 'UNKNOWN') AS reported_client_type,
                           COALESCE(reported_client_version, 'UNKNOWN') AS reported_client_version,
                           COUNT(*) AS login_events,
                           COUNT(DISTINCT user_name) AS users,
                           SUM(IFF(is_success = 'NO', 1, 0)) AS failed_events
                    FROM base
                    GROUP BY 1, 2
                    ORDER BY login_events DESC
                    LIMIT 50
                """)]),
                ("sec_login_factors", f"""
                    SELECT COALESCE(TO_VARCHAR(first_authentication_factor), 'UNKNOWN') AS first_factor,
                           COALESCE(TO_VARCHAR(second_authentication_factor), 'NONE') AS second_factor,
                           COUNT(*) AS login_events,
                           COUNT(DISTINCT user_name) AS users,
                           SUM(IFF(is_success = 'NO', 1, 0)) AS failed_events
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{posture_days}, CURRENT_TIMESTAMP())
                      {user_filter}
                    GROUP BY 1, 2
                    ORDER BY login_events DESC
                    LIMIT 50
                """),
                ("sec_login_errors", f"""
                    SELECT COALESCE(TO_VARCHAR(error_code), 'NONE') AS error_code,
                           COUNT(*) AS event_count,
                           COUNT(DISTINCT user_name) AS users,
                           COUNT(DISTINCT client_ip) AS ips
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{posture_days}, CURRENT_TIMESTAMP())
                      {user_filter}
                    GROUP BY 1
                    ORDER BY event_count DESC
                    LIMIT 50
                """),
            ]:
                try:
                    st.session_state[key] = run_query_or_raise(sql)
                except Exception:
                    st.session_state[key] = pd.DataFrame()

        c1, c2 = st.columns(2)
        with c1:
            ips = st.session_state.get("sec_login_ips")
            if ips is not None and not ips.empty:
                defer_source_note(st.session_state.get("sec_login_posture_source", "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY"))
                render_ranked_bar_chart(ips, "CLIENT_IP", "LOGIN_EVENTS", title="Top IPs", top_n=20)
                render_priority_dataframe(
                    ips,
                    title="Login IPs to review first",
                    priority_columns=["CLIENT_IP", "LOGIN_EVENTS", "USERS", "SUCCESS_EVENTS", "FAILED_EVENTS"],
                    sort_by=["FAILED_EVENTS", "LOGIN_EVENTS", "USERS"],
                    ascending=[False, False, False],
                    raw_label="All login IP rows",
                    height=300,
                )
                download_csv(ips, "login_posture_ips.csv")
        with c2:
            clients = st.session_state.get("sec_login_clients")
            if clients is not None and not clients.empty:
                defer_source_note(st.session_state.get("sec_login_posture_source", "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY"))
                render_ranked_bar_chart(
                    clients,
                    "REPORTED_CLIENT_TYPE",
                    "LOGIN_EVENTS",
                    title="Client Types / Versions",
                    top_n=20,
                )
                render_priority_dataframe(
                    clients,
                    title="Client types and versions to review",
                    priority_columns=[
                        "REPORTED_CLIENT_TYPE",
                        "REPORTED_CLIENT_VERSION",
                        "LOGIN_EVENTS",
                        "USERS",
                    ],
                    sort_by=["LOGIN_EVENTS", "USERS"],
                    ascending=[False, False],
                    raw_label="All client type/version rows",
                    height=300,
                )
                download_csv(clients, "login_posture_clients.csv")

        c3, c4 = st.columns(2)
        with c3:
            factors = st.session_state.get("sec_login_factors")
            st.subheader("Authentication Factors")
            if factors is not None and not factors.empty:
                render_priority_dataframe(
                    factors,
                    title="Authentication factor combinations",
                    priority_columns=[
                        "FIRST_FACTOR",
                        "SECOND_FACTOR",
                        "LOGIN_EVENTS",
                        "USERS",
                        "FAILED_EVENTS",
                    ],
                    sort_by=["FAILED_EVENTS", "LOGIN_EVENTS", "USERS"],
                    ascending=[False, False, False],
                    raw_label="All authentication factor rows",
                    height=300,
                )
                download_csv(factors, "login_posture_auth_factors.csv")
        with c4:
            errors = st.session_state.get("sec_login_errors")
            if errors is not None and not errors.empty:
                render_ranked_bar_chart(errors, "ERROR_CODE", "EVENT_COUNT", title="Login Error Codes", top_n=20)
                render_priority_dataframe(
                    errors,
                    title="Login error codes to investigate",
                    priority_columns=["ERROR_CODE", "EVENT_COUNT", "USERS", "IPS"],
                    sort_by=["EVENT_COUNT", "USERS", "IPS"],
                    ascending=[False, False, False],
                    raw_label="All login error rows",
                    height=300,
                )
                download_csv(errors, "login_posture_error_codes.csv")

    # Connected programs
    elif active_view == "Connected Programs":
        st.header("Connected Programs")
        program_days = st.slider("Program lookback (days)", 1, 90, 30, key="sec_connected_program_days")
        if st.button("Load Connected Programs", key="sec_connected_programs_load"):
            with st.spinner("Tracing connected programs..."):
                try:
                    for key, df in _load_connected_programs(get_session(), company, program_days).items():
                        st.session_state[key] = df
                    st.session_state["sec_connected_program_source"] = "SESSIONS, LOGIN_HISTORY, and QUERY_HISTORY linkage"
                except Exception as exc:
                    st.session_state["sec_connected_program_source"] = "Unavailable"
                    st.warning(f"Connected-program tracking unavailable: {format_snowflake_error(exc)}")
                    st.session_state["sec_connected_session_programs"] = pd.DataFrame()
                    st.session_state["sec_connected_login_programs"] = pd.DataFrame()
                    st.session_state["sec_connected_query_programs"] = pd.DataFrame()

        session_programs = st.session_state.get("sec_connected_session_programs")
        query_programs = st.session_state.get("sec_connected_query_programs")
        login_programs = st.session_state.get("sec_connected_login_programs")
        if session_programs is not None or query_programs is not None or login_programs is not None:
            defer_source_note(st.session_state.get("sec_connected_program_source", "SESSIONS, LOGIN_HISTORY, and QUERY_HISTORY linkage"))
            combined_programs = []
            if session_programs is not None and not session_programs.empty and "PROGRAM_NAME" in session_programs.columns:
                combined_programs.append(session_programs[["PROGRAM_NAME"]])
            if query_programs is not None and not query_programs.empty and "PROGRAM_NAME" in query_programs.columns:
                combined_programs.append(query_programs[["PROGRAM_NAME"]])
            if login_programs is not None and not login_programs.empty and "PROGRAM_NAME" in login_programs.columns:
                combined_programs.append(login_programs[["PROGRAM_NAME"]])
            distinct_programs = (
                pd.concat(combined_programs, ignore_index=True)["PROGRAM_NAME"].nunique()
                if combined_programs else 0
            )
            total_queries = (
                safe_int(query_programs["QUERY_COUNT"].sum())
                if query_programs is not None and not query_programs.empty and "QUERY_COUNT" in query_programs.columns else 0
            )
            failed_queries = (
                safe_int(query_programs["FAILED_QUERIES"].sum())
                if query_programs is not None and not query_programs.empty and "FAILED_QUERIES" in query_programs.columns else 0
            )
            total_logins = (
                safe_int(login_programs["LOGIN_EVENTS"].sum())
                if login_programs is not None and not login_programs.empty and "LOGIN_EVENTS" in login_programs.columns else 0
            )
            open_sessions = (
                safe_int(session_programs["OPEN_SESSIONS"].sum())
                if session_programs is not None and not session_programs.empty and "OPEN_SESSIONS" in session_programs.columns else 0
            )
            unknown_rows = 0
            for df in (session_programs, query_programs, login_programs):
                if df is not None and not df.empty and "CONTROL_STATUS" in df.columns:
                    unknown_rows += safe_int((df["CONTROL_STATUS"] == "Needs owner").sum())
            governed_pct = (
                max(0, (distinct_programs - unknown_rows)) / max(distinct_programs, 1) * 100
                if distinct_programs else 0
            )
            failure_rate = failed_queries / max(total_queries, 1) * 100
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Programs Seen", f"{distinct_programs:,}")
            c2.metric("Open Sessions", f"{open_sessions:,}")
            c3.metric("Query/Login Events", f"{total_queries:,} / {total_logins:,}")
            c4.metric("Need Owner", f"{unknown_rows:,}", delta=f"{governed_pct:.0f}% governed", delta_color="inverse")
            c5.metric("Program Failure Rate", f"{failure_rate:.1f}%", delta=f"{failed_queries:,} failed", delta_color="inverse")

        if session_programs is not None and not session_programs.empty:
            st.subheader("Session Program Inventory")
            render_priority_dataframe(
                session_programs,
                title="Connected session programs to govern first",
                priority_columns=[
                    "PROGRAM_NAME",
                    "PROGRAM_VERSION",
                    "CLIENT_BUILD",
                    "SESSIONS",
                    "OPEN_SESSIONS",
                    "USERS",
                    "AUTHENTICATION_METHODS",
                    "CLIENT_ENVIRONMENTS",
                    "LAST_SEEN",
                    "CONTROL_STATUS",
                    "NEXT_ACTION",
                    "SOURCE_CONFIDENCE",
                ],
                sort_by=["OPEN_SESSIONS", "SESSIONS", "USERS"],
                ascending=[False, False, False],
                raw_label="All session program rows",
                height=340,
            )
            download_csv(session_programs, "connected_program_sessions.csv")
        elif session_programs is not None:
            st.info("No session program inventory found for this scope.")

        if query_programs is not None and not query_programs.empty:
            st.subheader("Program Usage With Warehouse/Database Context")
            render_priority_dataframe(
                query_programs,
                title="Connected programs to govern first",
                priority_columns=[
                    "PROGRAM_NAME",
                    "PROGRAM_VERSION",
                    "WAREHOUSE_NAME",
                    "DATABASE_NAME",
                    "QUERY_COUNT",
                    "USERS",
                    "ROLES",
                    "FAILED_QUERIES",
                    "CLIENT_GENERATED_QUERIES",
                    "QUERY_TAGS",
                    "CONTROL_STATUS",
                    "NEXT_ACTION",
                    "SOURCE_CONFIDENCE",
                ],
                sort_by=["QUERY_COUNT", "FAILED_QUERIES", "USERS"],
                ascending=[False, False, False],
                raw_label="All connected program usage rows",
                height=360,
            )
            download_csv(query_programs, "connected_program_usage.csv")
        elif query_programs is not None:
            st.info("No query-linked connected programs found for this scope.")

        if login_programs is not None and not login_programs.empty:
            st.subheader("Login Client Inventory")
            render_priority_dataframe(
                login_programs,
                title="Login clients to register or review",
                priority_columns=[
                    "PROGRAM_NAME",
                    "PROGRAM_VERSION",
                    "LOGIN_EVENTS",
                    "USERS",
                    "IPS",
                    "FAILED_EVENTS",
                    "LAST_SEEN",
                    "CONTROL_STATUS",
                    "NEXT_ACTION",
                    "SOURCE_CONFIDENCE",
                ],
                sort_by=["LOGIN_EVENTS", "FAILED_EVENTS", "USERS"],
                ascending=[False, False, False],
                raw_label="All login client rows",
                height=320,
            )
            download_csv(login_programs, "connected_program_login_clients.csv")
        elif login_programs is not None:
            st.info("No login client inventory found for this scope.")

    # Roles & grants
    elif active_view == "Roles & Grants":
        st.header("Roles & Grants")
        if st.button("Load Grants", key="grants_load"):
            try:
                st.session_state["sec_df_grants"] = _load_grants_mart(company)
                st.session_state["sec_grants_source"] = "OVERWATCH mart: FACT_GRANT_DAILY"
            except Exception as mart_exc:
                st.session_state["sec_grants_source"] = "SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS"
                defer_source_note(f"Mart path skipped: {format_snowflake_error(mart_exc)}")
                try:
                    df_grants = run_query(f"""
                        SELECT grantee_name, role, granted_to, granted_by,
                               created_on, deleted_on
                        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
                        WHERE deleted_on IS NULL
                          {user_filter_g}
                        ORDER BY created_on DESC LIMIT 500
                    """, ttl_key=f"security_grants_to_users_{company}", tier="standard")
                    st.session_state["sec_df_grants"] = df_grants
                except Exception as e:
                    st.warning(f"Grants unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("sec_df_grants") is not None and not st.session_state["sec_df_grants"].empty:
            df_g = st.session_state["sec_df_grants"]
            defer_source_note(st.session_state.get("sec_grants_source", "SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS"))
            st.metric("Total Grants", len(df_g))
            df_g = _annotate_security_routes(df_g, "Grant Review")
            render_priority_dataframe(
                df_g,
                title="Grant rows to review first",
                priority_columns=[
                    "GRANTEE_NAME", "ROLE", "GRANTED_TO", "GRANTED_BY",
                    "CREATED_ON", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["CREATED_ON"],
                ascending=False,
                raw_label="All grant rows",
            )
            download_csv(df_g, "grants_to_users.csv")

        _render_role_grant_change_control(get_session(), company)

        # Dormant users
        st.divider()
        st.subheader("Dormant User Detection")
        dormant_days = st.number_input("Inactive threshold (days)", 30, 365, THRESHOLDS["dormant_user_days"], key="dom_days")
        dormant_lookback = min(365, int(dormant_days) + 30)
        if st.button("Find Dormant Users", key="dom_find"):
            try:
                user_exprs = _user_column_exprs()
                last_success_login_expr = user_exprs["last_success_login_expr"]
                df_dom = run_query(f"""
                WITH last_login AS (
                    SELECT user_name, MAX(event_timestamp) AS last_login_time
                    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
                    WHERE event_timestamp >= DATEADD('day', -{dormant_lookback}, CURRENT_TIMESTAMP())
                      {user_filter}
                    GROUP BY user_name
                ),
                last_query AS (
                    SELECT user_name, MAX(start_time) AS last_query_time
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -{dormant_lookback}, CURRENT_TIMESTAMP())
                      {user_filter}
                      {query_scope}
                    GROUP BY user_name
                )
                SELECT u.name AS user_name, u.created_on, u.disabled,
                       COALESCE(ll.last_login_time, {last_success_login_expr}) AS last_login,
                       lq.last_query_time,
                       DATEDIFF('day', COALESCE(ll.last_login_time, u.created_on), CURRENT_TIMESTAMP()) AS days_since_login
                FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
                LEFT JOIN last_login ll ON u.name = ll.user_name
                LEFT JOIN last_query  lq ON u.name = lq.user_name
                WHERE u.deleted_on IS NULL
                  AND u.disabled = 'false'
                  {user_filter_u}
                  AND DATEDIFF('day', COALESCE(ll.last_login_time, u.created_on), CURRENT_TIMESTAMP()) > {dormant_days}
                ORDER BY days_since_login DESC
                """, ttl_key=f"security_dormant_{company}_{dormant_days}_{dormant_lookback}", tier="standard")
                st.session_state["sec_df_dom"] = df_dom
            except Exception as e:
                st.warning(f"Dormant-user scan unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("sec_df_dom") is not None and not st.session_state["sec_df_dom"].empty:
            df_d = st.session_state["sec_df_dom"]
            st.warning(f"{len(df_d)} users inactive > {dormant_days} days - review for deactivation.")
            df_d = _annotate_security_routes(df_d, "Dormant User")
            render_priority_dataframe(
                df_d,
                title="Dormant users to review first",
                priority_columns=[
                    "USER_NAME", "DAYS_SINCE_LOGIN", "LAST_LOGIN", "LAST_QUERY_TIME",
                    "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["DAYS_SINCE_LOGIN"],
                ascending=False,
                raw_label="All dormant users",
            )
            download_csv(df_d, "dormant_users.csv")
            if st.button("Save dormant users to Action Queue", key="sec_dormant_queue"):
                _queue_security_findings(get_session(), df_d, "Dormant User", "Medium")

    # -- MFA COVERAGE ----------------------------------------------------------
    elif active_view == "MFA Coverage":
        st.header("MFA Coverage Report")
        if st.button("Check MFA", key="mfa_check"):
            try:
                user_exprs = _user_column_exprs()
                df_mfa = run_query(
                    _build_mfa_coverage_sql(user_exprs, user_filter_u),
                    ttl_key=f"security_mfa_{company}",
                    tier="standard",
                )
                st.session_state["sec_df_mfa"] = df_mfa
            except Exception as e:
                st.warning(f"MFA check unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("sec_df_mfa") is not None and not st.session_state["sec_df_mfa"].empty:
            df_m = st.session_state["sec_df_mfa"]
            if "HAS_MFA" not in df_m.columns:
                st.info("Snowflake did not expose an MFA signal column to this role. Active users are listed for IAM follow-up.")
                render_priority_dataframe(
                    df_m,
                    title="Active users without an exposed MFA signal",
                    priority_columns=["USER_NAME", "HAS_PASSWORD", "MFA_SOURCE", "LAST_LOGIN"],
                    sort_by=["LAST_LOGIN"],
                    ascending=True,
                    raw_label="All active user rows",
                )
                return
            mfa_source = df_m.get("MFA_SOURCE")
            if mfa_source is not None and mfa_source.astype(str).str.upper().eq("UNAVAILABLE").all():
                st.info("Snowflake did not expose HAS_MFA or EXT_AUTHN_DUO to this role. Confirm MFA posture in IAM.")
                render_priority_dataframe(
                    df_m,
                    title="Active users without an exposed MFA signal",
                    priority_columns=["USER_NAME", "HAS_PASSWORD", "MFA_SOURCE", "LAST_LOGIN"],
                    sort_by=["LAST_LOGIN"],
                    ascending=True,
                    raw_label="All active user rows",
                )
                return
            no_mfa = df_m[df_m["HAS_MFA"].astype(str).str.lower() != "true"]
            c1, c2 = st.columns(2)
            c1.metric("Users Without MFA",  len(no_mfa),    delta_color="inverse")
            c2.metric("MFA Coverage",       f"{(1-len(no_mfa)/max(len(df_m),1))*100:.0f}%")
            if not no_mfa.empty:
                st.warning(f"{len(no_mfa)} active user(s) without MFA enabled.")
                no_mfa = _annotate_security_routes(no_mfa, "No MFA")
                render_priority_dataframe(
                    no_mfa,
                    title="MFA gaps to close first",
                    priority_columns=[
                        "USER_NAME", "HAS_PASSWORD", "HAS_MFA", "LAST_LOGIN",
                        "NEXT_WORKFLOW", "NEXT_ACTION",
                    ],
                    sort_by=["LAST_LOGIN"],
                    ascending=True,
                    raw_label="All MFA gap rows",
                )
                download_csv(no_mfa, "users_without_mfa.csv")
                if st.button("Save MFA findings to Action Queue", key="sec_mfa_queue"):
                    _queue_security_findings(get_session(), no_mfa, "No MFA", "High")
            else:
                st.success("All active users have MFA enabled.")

    # -- EXFILTRATION SIGNALS --------------------------------------------------
    elif active_view == "Exfiltration Signals":
        st.header("Data Exfiltration Signals")
        st.caption("Users with >2 sigma BYTES_WRITTEN_TO_RESULT vs their 30-day baseline.")
        if st.button("Check Exfiltration", key="exfil_load"):
            qh_cols = _query_history_columns()
            if "BYTES_WRITTEN_TO_RESULT" not in qh_cols:
                st.info("Exfiltration byte metrics are not exposed in QUERY_HISTORY for this role/account.")
                st.session_state["sec_df_exfil"] = pd.DataFrame()
            else:
                try:
                    exfil_wh_size_expr = (
                        "warehouse_size AS warehouse_size"
                        if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
                    )
                    exfil_rows_expr = (
                        "rows_produced AS rows_produced"
                        if "ROWS_PRODUCED" in qh_cols else "0::NUMBER AS rows_produced"
                    )
                    df_ex = run_query(f"""
                WITH user_baseline AS (
                    SELECT user_name,
                           AVG(bytes_written_to_result) AS avg_bytes,
                           STDDEV(bytes_written_to_result) AS std_bytes
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
                      AND bytes_written_to_result > 0
                      {query_scope}
                    GROUP BY user_name HAVING COUNT(*) >= 5
                ),
                recent AS (
                    SELECT user_name, query_id, warehouse_name, {exfil_wh_size_expr}, start_time,
                           bytes_written_to_result/POWER(1024,3) AS gb_written,
                           {exfil_rows_expr}
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                    WHERE start_time >= DATEADD('day', -3, CURRENT_TIMESTAMP())
                      AND bytes_written_to_result > 0
                      {query_scope}
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
                """, ttl_key=f"security_exfil_{company}", tier="standard")
                    st.session_state["sec_df_exfil"] = df_ex
                except Exception as e:
                    st.warning(f"Exfiltration check unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("sec_df_exfil") is not None:
            df_ex = st.session_state["sec_df_exfil"]
            if not df_ex.empty:
                st.error(f"{len(df_ex)} queries with anomalously high data output (>2 sigma above user baseline).")
                df_ex = _annotate_security_routes(df_ex, "Exfiltration")
                render_priority_dataframe(
                    df_ex,
                    title="Potential exfiltration rows to review first",
                    priority_columns=[
                        "USER_NAME", "QUERY_ID", "WAREHOUSE_NAME", "GB_WRITTEN",
                        "AVG_GB_BASELINE", "ZSCORE", "NEXT_WORKFLOW", "NEXT_ACTION",
                    ],
                    sort_by=["ZSCORE", "GB_WRITTEN"],
                    ascending=[False, False],
                    raw_label="All exfiltration rows",
                )
                download_csv(df_ex, "exfiltration_signals.csv")
                if st.button("Save exfiltration signals to Action Queue", key="sec_exfil_queue"):
                    _queue_security_findings(get_session(), df_ex, "Exfiltration", "Critical")
            else:
                st.success("No unusual data exfiltration patterns detected.")

    # -- DATA LINEAGE ----------------------------------------------------------
    elif active_view == "Data Lineage":
        st.header("Data Lineage (ACCESS_HISTORY)")
        defer_source_note("Object-level access lineage from ACCOUNT_USAGE.ACCESS_HISTORY.")
        lin_days = st.slider("Lookback (days)", 1, 30, 7, key="lin_days")

        if st.button("Load Access History", key="lin_load"):
            try:
                df_lin = run_query(f"""
                    WITH scoped_queries AS (
                        SELECT query_id
                        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                        WHERE q.start_time >= DATEADD('day', -{lin_days}, CURRENT_TIMESTAMP())
                          {get_wh_filter_clause("q.warehouse_name")}
                          {get_db_filter_clause("q.database_name")}
                          {get_user_filter_clause("q.user_name")}
                    )
                    SELECT ah.user_name, ah.query_id,
                           ah.query_start_time,
                           ah.objects_modified,
                           ah.objects_modified_by_ddl,
                           ah.base_objects_accessed,
                           ah.direct_objects_accessed
                    FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah
                    JOIN scoped_queries sq ON ah.query_id = sq.query_id
                    WHERE ah.query_start_time >= DATEADD('day', -{lin_days}, CURRENT_TIMESTAMP())
                      {get_user_filter_clause("ah.user_name")}
                    ORDER BY ah.query_start_time DESC
                    LIMIT 500
                """, ttl_key=f"security_lineage_{company}_{lin_days}", tier="standard")
                st.session_state["sec_df_lin"] = df_lin
            except Exception as e:
                st.warning(f"Access history unavailable: {format_snowflake_error(e)}")

        if st.session_state.get("sec_df_lin") is not None and not st.session_state["sec_df_lin"].empty:
            df_l = st.session_state["sec_df_lin"]
            st.metric("Access Events", len(df_l))
            render_priority_dataframe(
                df_l,
                title="Recent access lineage events",
                priority_columns=[
                    "USER_NAME",
                    "QUERY_ID",
                    "QUERY_START_TIME",
                    "OBJECTS_MODIFIED",
                    "OBJECTS_MODIFIED_BY_DDL",
                    "BASE_OBJECTS_ACCESSED",
                    "DIRECT_OBJECTS_ACCESSED",
                ],
                sort_by=["QUERY_START_TIME"],
                ascending=False,
                raw_label="All access history rows",
            )
            download_csv(df_l, "access_history.csv")
