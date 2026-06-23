"""Shared security and access hygiene metric loaders."""

from __future__ import annotations

from .company_filter import (
    get_active_company,
    get_company_scope_key,
    get_db_filter_clause,
    get_environment_case_expr,
    get_environment_filter_clause,
    get_user_company_filter_clause,
)
from .compatibility import filter_existing_columns
from .mart import mart_object_name
from .query import run_query, sql_literal
from .shared_metrics_cache import _load_or_reuse
from .shared_metrics_contracts import SharedMetricResult

def shared_mfa_count_expr(user_cols: set[str]) -> str:
    """Return a compatible aggregate expression for active users missing MFA."""
    normalized = {str(col or "").upper() for col in user_cols}
    if "HAS_MFA" in normalized:
        return "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_mfa)), FALSE) = FALSE)"
    if "EXT_AUTHN_DUO" in normalized:
        return "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(ext_authn_duo)), FALSE) = FALSE)"
    return "NULL::NUMBER"


def shared_mfa_gap_predicate(user_cols: set[str], alias: str = "u") -> str:
    """Return a compatible row predicate for active users missing MFA."""
    normalized = {str(col or "").upper() for col in user_cols}
    prefix = f"{alias}." if alias else ""
    if "HAS_MFA" in normalized:
        return f"AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR({prefix}has_mfa)), FALSE) = FALSE"
    if "EXT_AUTHN_DUO" in normalized:
        return f"AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR({prefix}ext_authn_duo)), FALSE) = FALSE"
    return "AND 1 = 0"


def shared_mfa_proof_label(user_cols: set[str]) -> str:
    """Return the source label used for MFA exception proof rows."""
    normalized = {str(col or "").upper() for col in user_cols}
    if "HAS_MFA" in normalized:
        return "ACCOUNT_USAGE.USERS HAS_MFA signal"
    if "EXT_AUTHN_DUO" in normalized:
        return "ACCOUNT_USAGE.USERS EXT_AUTHN_DUO signal"
    return "ACCOUNT_USAGE.USERS MFA signal unavailable"


def _shared_user_exprs_from_columns(user_cols: set[str] | list[str] | tuple[str, ...]) -> dict[str, str]:
    """Return USERS projections for MFA/password signals from discovered columns."""
    user_cols = {str(col or "").upper() for col in user_cols}
    if "HAS_MFA" in user_cols:
        mfa_bool_expr = "COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.has_mfa)), FALSE)"
        mfa_source_expr = "'HAS_MFA'"
        mfa_signal_expr = "COALESCE(TO_VARCHAR(u.has_mfa), 'unknown')"
    elif "EXT_AUTHN_DUO" in user_cols:
        mfa_bool_expr = "COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.ext_authn_duo)), FALSE)"
        mfa_source_expr = "'EXT_AUTHN_DUO'"
        mfa_signal_expr = "COALESCE(TO_VARCHAR(u.ext_authn_duo), 'unknown')"
    else:
        mfa_bool_expr = "NULL::BOOLEAN"
        mfa_source_expr = "'UNAVAILABLE'"
        mfa_signal_expr = "'unknown'"
    return {
        "has_password_expr": (
            "COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.has_password)), FALSE)"
            if "HAS_PASSWORD" in user_cols else "NULL::BOOLEAN"
        ),
        "has_password_signal": (
            "COALESCE(TO_VARCHAR(u.has_password), 'false')"
            if "HAS_PASSWORD" in user_cols else "'unknown'"
        ),
        "mfa_bool_expr": mfa_bool_expr,
        "mfa_source_expr": mfa_source_expr,
        "mfa_signal_expr": mfa_signal_expr,
        "last_success_expr": (
            "u.last_success_login"
            if "LAST_SUCCESS_LOGIN" in user_cols else "NULL::TIMESTAMP_NTZ"
        ),
    }


def _shared_user_exprs(session: object) -> dict[str, str]:
    """Return USERS projections for MFA/password signals across Snowflake versions."""
    from .compatibility import filter_existing_columns

    user_cols = filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.USERS",
        ["HAS_MFA", "EXT_AUTHN_DUO", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
    )
    return _shared_user_exprs_from_columns(user_cols)


def _shared_security_user_columns(session: object) -> set[str]:
    return set(
        filter_existing_columns(
            session,
            "SNOWFLAKE.ACCOUNT_USAGE.USERS",
            ["HAS_MFA", "EXT_AUTHN_DUO", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"],
        )
    )


def build_shared_security_summary_sql(session: object, days: int, company: str) -> tuple[str, str]:
    """Build live ACCOUNT_USAGE security summary and exception SQL."""
    days = max(1, int(days or 30))
    user_cols = _shared_security_user_columns(session)
    mfa_count_expr = shared_mfa_count_expr(user_cols)
    mfa_gap_predicate = shared_mfa_gap_predicate(user_cols)
    mfa_proof = shared_mfa_proof_label(user_cols)
    password_count_expr = (
        "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_password)), FALSE) = TRUE)"
        if "HAS_PASSWORD" in user_cols else "NULL::NUMBER"
    )
    last_seen_expr = "u.last_success_login" if "LAST_SUCCESS_LOGIN" in user_cols else "u.created_on"
    user_filter_lh = get_user_company_filter_clause("lh.user_name", company)
    user_filter_u = get_user_company_filter_clause("u.name", company)
    user_filter_g = get_user_company_filter_clause("g.grantee_name", company)
    db_filter = get_db_filter_clause("d.database_name")
    object_grant_db_filter = get_db_filter_clause("gor.table_catalog")
    company_label = sql_literal(company, 100)

    summary_sql = f"""
    WITH login_events AS (
        SELECT
            COUNT(*) AS login_events,
            COUNT_IF(lh.is_success = 'NO') AS failed_logins,
            COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.user_name, NULL)) AS failed_users,
            COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.client_ip, NULL)) AS failed_ips
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
        WHERE lh.event_timestamp >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {user_filter_lh}
    ),
    users AS (
        SELECT
            COUNT(*) AS active_users,
            {mfa_count_expr} AS users_without_mfa,
            {password_count_expr} AS password_users
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
    ),
    recent_grants AS (
        SELECT COUNT(*) AS recent_grants
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
        WHERE g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
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
        recent_grants.recent_grants AS recent_grants,
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
            'LOGIN_HISTORY failed login attempts by user/IP' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
        WHERE lh.event_timestamp >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
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
            '{mfa_proof}' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
          {mfa_gap_predicate}
    ),
    recent_grants AS (
        SELECT
            'Recent Grant' AS finding_type,
            IFF(COUNT(*) >= 10, 'Medium', 'Low') AS severity,
            g.grantee_name AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT g.role) AS distinct_sources,
            MAX(g.created_on) AS last_seen,
            'ACCOUNT_USAGE.GRANTS_TO_USERS active grants created recently' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
        WHERE g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {user_filter_g}
        GROUP BY g.grantee_name
        HAVING COUNT(*) >= 3
    ),
    object_grants AS (
        SELECT
            'Object Grant' AS finding_type,
            IFF(COUNT(*) >= 10 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0, 'High', 'Medium') AS severity,
            COALESCE(gor.table_catalog || '.' || gor.table_schema || '.' || gor.name, gor.table_catalog, gor.name) AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT gor.grantee_name) AS distinct_sources,
            MAX(gor.created_on) AS last_seen,
            'ACCOUNT_USAGE.GRANTS_TO_ROLES object grants by database/schema/object' AS proof_query,
            gor.table_catalog AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES gor
        WHERE gor.deleted_on IS NULL
          AND gor.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND gor.table_catalog IS NOT NULL
          {object_grant_db_filter}
        GROUP BY gor.table_catalog, gor.table_schema, gor.name
        HAVING COUNT(*) >= 3 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0
    ),
    shared_exposure AS (
        SELECT
            'Shared Database Exposure' AS finding_type,
            'Medium' AS severity,
            d.database_name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            d.created AS last_seen,
            'ACCOUNT_USAGE.DATABASES imported database/share metadata' AS proof_query,
            d.database_name AS database_name
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
    SELECT * FROM object_grants
    UNION ALL
    SELECT * FROM shared_exposure
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        event_count DESC,
        last_seen DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def build_shared_security_mart_brief_sql(session: object, days: int, company: str) -> tuple[str, str]:
    """Build mart-backed security summary SQL with bounded live metadata."""
    days = max(1, int(days or 30))
    user_cols = _shared_security_user_columns(session)
    mfa_count_expr = shared_mfa_count_expr(user_cols)
    mfa_gap_predicate = shared_mfa_gap_predicate(user_cols)
    mfa_proof = shared_mfa_proof_label(user_cols)
    password_count_expr = (
        "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_password)), FALSE) = TRUE)"
        if "HAS_PASSWORD" in user_cols else "NULL::NUMBER"
    )
    last_seen_expr = "u.last_success_login" if "LAST_SUCCESS_LOGIN" in user_cols else "u.created_on"
    user_filter_lh = get_user_company_filter_clause("lh.user_name", company)
    user_filter_u = get_user_company_filter_clause("u.name", company)
    user_filter_g = get_user_company_filter_clause("g.grantee_name", company)
    db_filter = get_db_filter_clause("d.database_name")
    object_grant_db_filter = get_db_filter_clause("gor.table_catalog")
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
        WHERE lh.login_date >= DATEADD('day', -{days}, CURRENT_DATE())
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
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
    ),
    recent_grants AS (
        SELECT COALESCE(SUM(grant_count), 0) AS recent_grants
        FROM {grant_table} g
        WHERE 1 = 1
          {grant_company_filter}
          AND g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
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
        recent_grants.recent_grants AS recent_grants,
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
            'FACT_LOGIN_DAILY failed login attempts by user/IP' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM {login_table} lh
        WHERE lh.login_date >= DATEADD('day', -{days}, CURRENT_DATE())
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
            '{mfa_proof}' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
        WHERE u.deleted_on IS NULL
          AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
          {user_filter_u}
          {mfa_gap_predicate}
    ),
    recent_grants AS (
        SELECT
            'Recent Grant' AS finding_type,
            IFF(SUM(grant_count) >= 10, 'Medium', 'Low') AS severity,
            g.grantee_name AS entity,
            COALESCE(SUM(grant_count), 0) AS event_count,
            COUNT(DISTINCT g.role_name) AS distinct_sources,
            MAX(g.created_on) AS last_seen,
            'FACT_GRANT_DAILY active grants created recently' AS proof_query,
            NULL::VARCHAR AS database_name
        FROM {grant_table} g
        WHERE 1 = 1
          {grant_company_filter}
          AND g.deleted_on IS NULL
          AND g.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          {user_filter_g}
        GROUP BY g.grantee_name
        HAVING COALESCE(SUM(grant_count), 0) >= 3
    ),
    object_grants AS (
        SELECT
            'Object Grant' AS finding_type,
            IFF(COUNT(*) >= 10 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0, 'High', 'Medium') AS severity,
            COALESCE(gor.table_catalog || '.' || gor.table_schema || '.' || gor.name, gor.table_catalog, gor.name) AS entity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT gor.grantee_name) AS distinct_sources,
            MAX(gor.created_on) AS last_seen,
            'ACCOUNT_USAGE.GRANTS_TO_ROLES object grants by database/schema/object' AS proof_query,
            gor.table_catalog AS database_name
        FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES gor
        WHERE gor.deleted_on IS NULL
          AND gor.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND gor.table_catalog IS NOT NULL
          {object_grant_db_filter}
        GROUP BY gor.table_catalog, gor.table_schema, gor.name
        HAVING COUNT(*) >= 3 OR COUNT_IF(COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true') > 0
    ),
    shared_exposure AS (
        SELECT
            'Shared Database Exposure' AS finding_type,
            'Medium' AS severity,
            d.database_name AS entity,
            1 AS event_count,
            0 AS distinct_sources,
            d.created AS last_seen,
            'ACCOUNT_USAGE.DATABASES imported database/share metadata' AS proof_query,
            d.database_name AS database_name
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
    SELECT * FROM object_grants
    UNION ALL
    SELECT * FROM shared_exposure
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        event_count DESC,
        last_seen DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def build_shared_security_privileged_grant_review_sql(
    days: int,
    company: str,
    environment: str = "ALL",
) -> str:
    """Return high-risk account-role and object grants with environment-aware object scope."""

    days = max(1, min(int(days or 30), 90))
    user_filter = get_user_company_filter_clause("gtu.grantee_name", company)
    object_env_filter = get_environment_filter_clause(
        "gor.table_catalog",
        environment=environment,
        company=company,
    )
    object_env_expr = get_environment_case_expr("gor.table_catalog")
    return f"""WITH privileged_role_grants AS (
    SELECT
        'Privileged Role Grant' AS finding_type,
        IFF(UPPER(gtu.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN'), 'Critical', 'High') AS severity,
        gtu.grantee_name AS entity,
        gtu.role AS role_name,
        NULL::VARCHAR AS privilege,
        FALSE AS grant_option,
        NULL::VARCHAR AS object_name,
        NULL::VARCHAR AS database_name,
        FALSE AS database_context,
        'No Database Context' AS environment,
        'ACCOUNT_USAGE.GRANTS_TO_USERS privileged role grants' AS proof_query,
        gtu.granted_by,
        gtu.created_on,
        DATEDIFF('day', gtu.created_on, CURRENT_TIMESTAMP()) AS grant_age_days,
        'Business justification, ticket/reference, review-by date, and telemetry status required.' AS proof_required,
        'Review account-level privileged role grant; do not hide this row behind a database environment filter.' AS next_action
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS gtu
    WHERE gtu.deleted_on IS NULL
      AND (
          UPPER(gtu.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN')
          OR UPPER(gtu.role) ILIKE '%ADMIN%'
          OR UPPER(gtu.role) ILIKE '%SECURITY%'
      )
      {user_filter}
),
object_privilege_grants AS (
    SELECT
        'Privileged Object Grant' AS finding_type,
        IFF(
            UPPER(gor.privilege) IN ('OWNERSHIP', 'APPLY MASKING POLICY', 'APPLY ROW ACCESS POLICY')
            OR COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true',
            'High',
            'Medium'
        ) AS severity,
        gor.grantee_name AS entity,
        NULL::VARCHAR AS role_name,
        gor.privilege AS privilege,
        COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true' AS grant_option,
        gor.name AS object_name,
        gor.table_catalog AS database_name,
        TRUE AS database_context,
        {object_env_expr} AS environment,
        'ACCOUNT_USAGE.GRANTS_TO_ROLES privileged object grants' AS proof_query,
        gor.granted_by,
        gor.created_on,
        DATEDIFF('day', gor.created_on, CURRENT_TIMESTAMP()) AS grant_age_days,
        'Privilege justification, ticket/reference, review-by date, and rollback status required.' AS proof_required,
        'Review database-scoped object privilege before revoke/narrowing action.' AS next_action
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES gor
    WHERE gor.deleted_on IS NULL
      AND gor.created_on >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
      AND gor.table_catalog IS NOT NULL
      AND (
          UPPER(gor.privilege) IN (
              'OWNERSHIP',
              'MANAGE GRANTS',
              'APPLY MASKING POLICY',
              'APPLY ROW ACCESS POLICY',
              'CREATE DATABASE ROLE',
              'CREATE SCHEMA',
              'CREATE TABLE',
              'CREATE VIEW'
          )
          OR COALESCE(TO_VARCHAR(gor.grant_option), 'false') = 'true'
      )
      {object_env_filter}
)
SELECT
    finding_type,
    severity,
    entity,
    role_name,
    privilege,
    grant_option,
    object_name,
    database_name,
    database_context,
    environment,
    proof_query,
    granted_by,
    created_on,
    grant_age_days,
    proof_required,
    next_action
FROM privileged_role_grants
UNION ALL
SELECT
    finding_type,
    severity,
    entity,
    role_name,
    privilege,
    grant_option,
    object_name,
    database_name,
    database_context,
    environment,
    proof_query,
    granted_by,
    created_on,
    grant_age_days,
    proof_required,
    next_action
FROM object_privilege_grants
ORDER BY
    CASE severity WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
    created_on DESC
LIMIT 200""".strip()


def load_shared_mfa_coverage(
    session: object,
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load active-user MFA posture once for security surfaces."""

    company = company or get_active_company()

    def _loader() -> SharedMetricResult:
        exprs = _shared_user_exprs(session)
        df = run_query(
            f"""
            SELECT
                u.name AS user_name,
                {exprs["has_password_expr"]} AS has_password,
                {exprs["mfa_bool_expr"]} AS has_mfa,
                {exprs["mfa_source_expr"]} AS mfa_source,
                u.disabled,
                COALESCE({exprs["last_success_expr"]}, u.created_on) AS last_login
            FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
            WHERE u.deleted_on IS NULL
              AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.disabled)), FALSE) = FALSE
              {get_user_company_filter_clause("u.name", company)}
            ORDER BY has_mfa, user_name
            """,
            ttl_key=get_company_scope_key("shared_mfa_coverage"),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.USERS",
            available=not df.empty,
        )

    return _load_or_reuse("shared_mfa_coverage", (company,), _loader, force=force)


def load_shared_grants_to_users(
    company: str | None = None,
    *,
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load active user-role grants once for security/access review surfaces."""

    company = company or get_active_company()

    def _loader() -> SharedMetricResult:
        try:
            company_filter = ""
            if str(company or "ALL").upper() != "ALL":
                company_filter = f"AND g.company = {sql_literal(company, 100)}"
            table = mart_object_name("FACT_GRANT_DAILY")
            mart_df = run_query(
                f"""
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
                  {get_user_company_filter_clause("g.grantee_name", company)}
                GROUP BY g.grantee_name, g.role_name, g.granted_to
                ORDER BY created_on DESC
                LIMIT 500
                """,
                ttl_key=get_company_scope_key("shared_grants_to_users_mart"),
                tier="standard",
                section=section,
            )
            if not mart_df.empty:
                return SharedMetricResult(data=mart_df, source="Fast grant summary", available=True)
        except Exception:
            pass

        live_df = run_query(
            f"""
            SELECT grantee_name,
                   role,
                   granted_to,
                   granted_by,
                   created_on,
                   deleted_on
            FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
            WHERE deleted_on IS NULL
              {get_user_company_filter_clause("grantee_name", company)}
            ORDER BY created_on DESC
            LIMIT 500
            """,
            ttl_key=get_company_scope_key("shared_grants_to_users_live"),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=live_df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS",
            available=not live_df.empty,
        )

    return _load_or_reuse("shared_grants_to_users", (company,), _loader, force=force)


def build_shared_access_hygiene_sql(
    session: object,
    days: int,
    company: str | None = None,
    environment: str = "ALL",
    *,
    user_columns: set[str] | list[str] | tuple[str, ...] | None = None,
) -> str:
    """Build account-level user/login/grant hygiene SQL for shared security surfaces."""
    company = company or get_active_company()
    days = max(1, int(days or 30))
    env_label = sql_literal(str(environment or "ALL"), 100)
    exprs = (
        _shared_user_exprs_from_columns(user_columns)
        if user_columns is not None
        else _shared_user_exprs(session)
    )
    return f"""
            WITH login_rollup AS (
                SELECT
                    lh.user_name,
                    COUNT_IF(lh.is_success = 'NO') AS failed_logins,
                    COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.client_ip, NULL)) AS failed_ips,
                    MAX(IFF(lh.is_success = 'YES', lh.event_timestamp, NULL)) AS last_login_from_history
                FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
                WHERE lh.event_timestamp >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  {get_user_company_filter_clause("lh.user_name", company)}
                GROUP BY lh.user_name
            ),
            admin_grants AS (
                SELECT
                    g.grantee_name AS user_name,
                    COUNT(DISTINCT g.role) AS admin_role_count,
                    LISTAGG(DISTINCT g.role, ', ') WITHIN GROUP (ORDER BY g.role) AS admin_roles
                FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
                WHERE g.deleted_on IS NULL
                  {get_user_company_filter_clause("g.grantee_name", company)}
                  AND (
                      UPPER(g.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN')
                      OR UPPER(g.role) LIKE '%ADMIN%'
                      OR UPPER(g.role) LIKE '%SECURITY%'
                  )
                GROUP BY g.grantee_name
            ),
            user_posture AS (
                SELECT
                    u.name AS user_name,
                    COALESCE(TO_VARCHAR(u.disabled), 'false') AS disabled,
                    {exprs["has_password_signal"]} AS has_password,
                    {exprs["mfa_signal_expr"]} AS mfa_signal,
                    COALESCE(lr.last_login_from_history, {exprs["last_success_expr"]}, u.created_on) AS last_seen,
                    COALESCE(lr.failed_logins, 0) AS failed_logins,
                    COALESCE(lr.failed_ips, 0) AS failed_ips,
                    COALESCE(ag.admin_role_count, 0) AS admin_role_count,
                    COALESCE(ag.admin_roles, '') AS admin_roles
                FROM SNOWFLAKE.ACCOUNT_USAGE.USERS u
                LEFT JOIN login_rollup lr ON UPPER(u.name) = UPPER(lr.user_name)
                LEFT JOIN admin_grants ag ON UPPER(u.name) = UPPER(ag.user_name)
                WHERE u.deleted_on IS NULL
                  {get_user_company_filter_clause("u.name", company)}
            )
            SELECT
                user_name,
                disabled,
                has_password,
                mfa_signal,
                last_seen,
                failed_logins,
                failed_ips,
                admin_role_count,
                admin_roles,
                DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) AS days_since_seen,
                CASE
                    WHEN failed_logins >= 25 OR failed_ips >= 5 THEN 'High'
                    WHEN admin_role_count > 0 AND (mfa_signal = 'unknown' OR LOWER(mfa_signal) <> 'true') THEN 'High'
                    WHEN DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) >= 90 THEN 'Medium'
                    WHEN failed_logins > 0 OR admin_role_count > 0 OR (mfa_signal <> 'unknown' AND LOWER(mfa_signal) <> 'true') THEN 'Medium'
                    ELSE 'Low'
                END AS severity,
                CONCAT_WS('; ',
                    IFF(disabled = 'true', 'disabled user retained in account', NULL),
                    IFF(failed_logins > 0, failed_logins || ' failed login(s)', NULL),
                    IFF(failed_ips >= 5, failed_ips || ' failed login source IP(s)', NULL),
                    IFF(admin_role_count > 0, admin_role_count || ' privileged role grant(s)', NULL),
                    IFF(mfa_signal <> 'unknown' AND LOWER(mfa_signal) <> 'true', 'MFA signal missing', NULL),
                    IFF(DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) >= 90, 'dormant >= 90 days', NULL)
                ) AS posture_findings,
                'No Database Context' AS database_context,
                'No Database Context' AS environment_scope,
                {env_label} AS selected_environment,
                'Account-Level Control' AS scope_confidence,
                'USERS, LOGIN_HISTORY, and GRANTS_TO_USERS do not expose database context; company scope uses configured user patterns and active role membership where available.' AS scope_evidence,
                'Confirm IAM route, admin-role business need, MFA posture, and recent login telemetry before disabling users or changing grants.' AS next_action,
                'user, IAM ticket, failed login context, MFA/admin-role telemetry' AS proof_required
            FROM user_posture
            WHERE
                failed_logins > 0
                OR admin_role_count > 0
                OR (mfa_signal <> 'unknown' AND LOWER(mfa_signal) <> 'true')
                OR DATEDIFF('day', last_seen, CURRENT_TIMESTAMP()) >= 90
            ORDER BY
                CASE severity WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
                failed_logins DESC,
                admin_role_count DESC,
                days_since_seen DESC
            LIMIT 100
            """.strip()


def load_shared_access_hygiene_snapshot(
    session: object,
    days: int,
    company: str | None = None,
    *,
    environment: str = "ALL",
    force: bool = False,
    section: str = "Shared Metrics",
) -> SharedMetricResult:
    """Load account-level user/login/grant hygiene once for Account Health/Security."""

    company = company or get_active_company()
    days = max(1, int(days or 30))

    def _loader() -> SharedMetricResult:
        df = run_query(
            build_shared_access_hygiene_sql(session, days, company, environment),
            ttl_key=get_company_scope_key("shared_access_hygiene", days, environment),
            tier="standard",
            section=section,
        )
        return SharedMetricResult(
            data=df,
            source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.USERS + LOGIN_HISTORY + GRANTS_TO_USERS",
            available=not df.empty,
            effective_days=days,
        )

    return _load_or_reuse("shared_access_hygiene", (company, days, environment), _loader, force=force)


