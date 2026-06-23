"""Account Health access-hygiene SQL and annotation helpers."""
from __future__ import annotations

from sections.account_health_checklist import _account_health_recovery_target_hours
from sections.base import lazy_pandas, lazy_util as _lazy_util


pd = lazy_pandas()

build_shared_access_hygiene_sql = _lazy_util("build_shared_access_hygiene_sql")
filter_existing_columns = _lazy_util("filter_existing_columns")
resolve_owner_context = _lazy_util("resolve_owner_context")
sql_literal = _lazy_util("sql_literal")


def _account_health_access_hygiene_sql(session, days: int, company: str, environment: str = "ALL") -> str:
    """Compatibility wrapper for the shared account-level user/auth hygiene SQL."""
    user_cols = filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.USERS",
        ["HAS_MFA", "HAS_PASSWORD", "EXT_AUTHN_DUO", "LAST_SUCCESS_LOGIN"],
    )
    return build_shared_access_hygiene_sql(
        session,
        days,
        company,
        environment,
        user_columns=user_cols,
    )

def _annotate_account_health_access_hygiene(hygiene: pd.DataFrame) -> pd.DataFrame:
    """Add owner, queue, and scope readiness to account-level access hygiene rows."""
    if hygiene is None or hygiene.empty:
        return pd.DataFrame() if hygiene is None else hygiene
    view = hygiene.copy()
    view.columns = [str(col).upper() for col in view.columns]

    def _context(row: pd.Series) -> dict:
        return resolve_owner_context(
            {
                "ENTITY_NAME": row.get("USER_NAME", ""),
                "CATEGORY": "Account Health Access Hygiene",
                "OWNER": "DBA / Security",
            },
            entity=row.get("USER_NAME", ""),
            entity_type="SECURITY",
            owner="DBA / Security",
            category="Account Health Access Hygiene",
        )

    contexts = view.apply(_context, axis=1)
    view["OWNER"] = contexts.apply(lambda item: item.get("OWNER") or "DBA / Security")
    view["OWNER_EMAIL"] = contexts.apply(lambda item: item.get("OWNER_EMAIL", ""))
    view["ONCALL_PRIMARY"] = contexts.apply(lambda item: item.get("ONCALL_PRIMARY", ""))
    view["APPROVAL_GROUP"] = contexts.apply(lambda item: item.get("APPROVAL_GROUP", "Security Approver"))
    view["ESCALATION_TARGET"] = contexts.apply(lambda item: item.get("ESCALATION_TARGET", "Security Lead"))
    view["OWNER_SOURCE"] = contexts.apply(lambda item: item.get("OWNER_SOURCE", "Default security route"))
    view["OWNER_EVIDENCE"] = contexts.apply(lambda item: item.get("OWNER_EVIDENCE", ""))

    if "DATABASE_CONTEXT" not in view.columns:
        view["DATABASE_CONTEXT"] = "No Database Context"
    if "ENVIRONMENT_SCOPE" not in view.columns:
        view["ENVIRONMENT_SCOPE"] = "No Database Context"
    if "SCOPE_CONFIDENCE" not in view.columns:
        view["SCOPE_CONFIDENCE"] = "Account-Level Control"
    if "SCOPE_EVIDENCE" not in view.columns:
        view["SCOPE_EVIDENCE"] = (
            "USERS, LOGIN_HISTORY, and GRANTS_TO_USERS do not expose database context; "
            "company scope uses configured user patterns and active role membership where available."
        )

    severity = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    proof = view.get("PROOF_REQUIRED", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    owner = view["OWNER"].fillna("").astype(str).str.upper()
    approval_group = view["APPROVAL_GROUP"].fillna("").astype(str)
    route_ready = (~owner.isin({"", "DBA", "UNKNOWN", "N/A"})) | (approval_group.str.len() > 0)
    approval_required = severity.isin({"HIGH", "MEDIUM"})
    proof_ready = proof.str.len() > 0
    view["APPROVAL_REQUIRED"] = approval_required.map({True: "Yes", False: "No"})
    view["QUEUE_READINESS"] = (
        route_ready & proof_ready & (~approval_required | (approval_group.str.len() > 0))
    ).map({True: "Ready to Queue", False: "Needs Routing Data"})
    view["QUEUE_BLOCKERS"] = "None"
    view.loc[~route_ready, "QUEUE_BLOCKERS"] = "escalation route"
    view.loc[~proof_ready, "QUEUE_BLOCKERS"] = view.loc[~proof_ready, "QUEUE_BLOCKERS"].replace("None", "telemetry basis")
    view.loc[approval_required & (approval_group.str.len() == 0), "QUEUE_BLOCKERS"] = "review group"
    rank = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
    view["ACCESS_RISK_RANK"] = severity.map(rank).fillna(4).astype(int)
    view["RECOVERY_SLA_TARGET_HOURS"] = severity.apply(_account_health_recovery_target_hours)
    return view

def _account_health_access_hygiene_verification_sql(row: pd.Series | dict, days: int = 30) -> str:
    """Read-only verification for a user/auth hygiene action."""
    user_name = str(row.get("USER_NAME") or row.get("Entity") or "").strip()
    user_lit = sql_literal(user_name, 256)
    lookback = max(1, int(days or 30))
    return f"""
WITH selected_user AS (
    SELECT {user_lit} AS user_name
),
login_rollup AS (
    SELECT
        lh.user_name,
        COUNT_IF(lh.is_success = 'NO') AS failed_logins,
        COUNT(DISTINCT IFF(lh.is_success = 'NO', lh.client_ip, NULL)) AS failed_ips,
        MAX(IFF(lh.is_success = 'YES', lh.event_timestamp, NULL)) AS last_success_login
    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY lh
    JOIN selected_user su ON UPPER(lh.user_name) = UPPER(su.user_name)
    WHERE lh.event_timestamp >= DATEADD('day', -{lookback}, CURRENT_TIMESTAMP())
    GROUP BY lh.user_name
),
admin_grants AS (
    SELECT
        g.grantee_name AS user_name,
        LISTAGG(DISTINCT g.role, ', ') WITHIN GROUP (ORDER BY g.role) AS admin_roles,
        COUNT(DISTINCT g.role) AS admin_role_count
    FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS g
    JOIN selected_user su ON UPPER(g.grantee_name) = UPPER(su.user_name)
    WHERE g.deleted_on IS NULL
      AND (
          UPPER(g.role) IN ('ACCOUNTADMIN', 'ORGADMIN', 'SECURITYADMIN', 'SYSADMIN', 'USERADMIN')
          OR UPPER(g.role) LIKE '%ADMIN%'
          OR UPPER(g.role) LIKE '%SECURITY%'
      )
    GROUP BY g.grantee_name
)
SELECT
    su.user_name,
    COALESCE(TO_VARCHAR(u.disabled), 'unknown') AS disabled,
    COALESCE(TO_VARCHAR(u.has_password), 'unknown') AS has_password,
    COALESCE(TO_VARCHAR(u.ext_authn_duo), 'unknown') AS mfa_signal,
    COALESCE(lr.failed_logins, 0) AS failed_logins,
    COALESCE(lr.failed_ips, 0) AS failed_ips,
    COALESCE(ag.admin_role_count, 0) AS admin_role_count,
    COALESCE(ag.admin_roles, '') AS admin_roles,
    COALESCE(lr.last_success_login, u.last_success_login, u.created_on) AS last_seen,
    'No Database Context' AS environment_scope,
    'Account-Level Control' AS scope_confidence
FROM selected_user su
LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u ON UPPER(u.name) = UPPER(su.user_name)
LEFT JOIN login_rollup lr ON UPPER(lr.user_name) = UPPER(su.user_name)
LEFT JOIN admin_grants ag ON UPPER(ag.user_name) = UPPER(su.user_name)
""".strip()


__all__ = [
    '_account_health_access_hygiene_sql',
    '_annotate_account_health_access_hygiene',
    '_account_health_access_hygiene_verification_sql',
]
