# sections/security_posture_access_review.py - Security access-review SQL and models
from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE
from sections.base import lazy_pandas, lazy_util as _lazy_util
from utils.primitives import safe_int


pd = lazy_pandas()

action_queue_environment_clause = _lazy_util("action_queue_environment_clause")
environment_label_for_database = _lazy_util("environment_label_for_database")
format_snowflake_error = _lazy_util("format_snowflake_error")
make_action_id = _lazy_util("make_action_id")
mart_object_name = _lazy_util("mart_object_name")
resolve_owner_context = _lazy_util("resolve_owner_context")
safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")

SECURITY_ACCESS_REVIEW_TABLE = "OVERWATCH_SECURITY_ACCESS_REVIEW"
SECURITY_OPERABILITY_FACT_TABLE = "FACT_SECURITY_OPERABILITY_DAILY"
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
    REVIEW_TARGET       VARCHAR(200),
    ROUTE_SOURCE            VARCHAR(200),
    APPROVER                VARCHAR(200),
    REVIEW_STATUS   VARCHAR(40),
    ACCESS_REVIEW_STATE     VARCHAR(160),
    ROLE_CAPABILITY_STATE   VARCHAR(200),
    TICKET_REQUIRED         VARCHAR(20),
    REVIEW_BY_REQUIRED      VARCHAR(20),
    PROOF_REQUIRED          VARCHAR(2000),
    VERIFICATION_QUERY      VARCHAR(8000),
    ACCESS_TICKET_ID        VARCHAR(200),
    REVIEW_BY_DATE          VARCHAR(100),
    IAM_APPROVAL_STATE      VARCHAR(120),
    REVIEW_READINESS        VARCHAR(100),
    REVIEW_BLOCKERS         VARCHAR(2000),
    REVIEW_SLA_HOURS        NUMBER,
    VERIFICATION_STATUS     VARCHAR(80),
    VERIFICATION_RESULT     VARCHAR(4000),
    CONTROL_READINESS       VARCHAR(100),
    CONTROL_BLOCKERS        VARCHAR(2000),
    NEXT_CONTROL_ACTION     VARCHAR(4000),
    NEXT_ACTION             VARCHAR(4000),
    PROOF_QUERY             VARCHAR(4000),
    SOURCE                  VARCHAR(500)
);"""

def build_security_access_review_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = SECURITY_ACCESS_REVIEW_TABLE,
) -> list[str]:
    fqn = security_access_review_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ACCESS_TICKET_ID VARCHAR(200)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_BY_DATE VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS IAM_APPROVAL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_READINESS VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_SLA_HOURS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS VERIFICATION_STATUS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS VERIFICATION_RESULT VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_READINESS VARCHAR(100)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
    ]

def security_operability_fact_fqn(table: str = SECURITY_OPERABILITY_FACT_TABLE) -> str:
    return mart_object_name(table)

def build_security_operability_fact_ddl(table: str = SECURITY_OPERABILITY_FACT_TABLE) -> str:
    fqn = security_operability_fact_fqn(table=table)
    return f"""CREATE TRANSIENT TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_DATE                   DATE,
    COMPANY                         VARCHAR(100),
    ENVIRONMENT                     VARCHAR(100),
    CONTROL_SOURCE                  VARCHAR(80),
    FINDING_TYPE                    VARCHAR(120),
    ENTITY                          VARCHAR(500),
    ENTITY_TYPE                     VARCHAR(120),
    SEVERITY                        VARCHAR(40),
    CONTROL_STATE                   VARCHAR(120),
    CONTROL_RANK                    NUMBER,
    EVENT_ROWS                      NUMBER,
    REVIEW_ROWS                     NUMBER,
    REVIEW_BLOCKER_ROWS             NUMBER,
    TICKET_REQUIRED_ROWS            NUMBER,
    REVIEW_BY_REQUIRED_ROWS         NUMBER,
    CAPABILITY_PROOF_ROWS           NUMBER,
    NO_DATABASE_CONTEXT_ROWS        NUMBER,
    OPEN_ACTIONS                    NUMBER,
    OVERDUE_OPEN                    NUMBER,
    FIXED_WITHOUT_VERIFICATION      NUMBER,
    VERIFIED_CLOSURES               NUMBER,
    REVIEW_GAP_ROWS         NUMBER,
    NEXT_CONTROL_ACTION             VARCHAR(4000),
    LAST_ACTIVITY_TS                TIMESTAMP_NTZ,
    LOAD_TS                         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);"""

def build_security_operability_fact_migration_sql(
    table: str = SECURITY_OPERABILITY_FACT_TABLE,
) -> list[str]:
    fqn = security_operability_fact_fqn(table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_SOURCE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_RANK NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EVENT_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_BLOCKER_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS TICKET_REQUIRED_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_BY_REQUIRED_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CAPABILITY_PROOF_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NO_DATABASE_CONTEXT_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_GAP_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LAST_ACTIVITY_TS TIMESTAMP_NTZ",
    ]

def _security_action_for(finding_type: str) -> tuple[str, str, str]:
    value = str(finding_type or "").lower()
    if "failed login" in value:
        return (
            "User/Auth",
            "Validate whether attempts are expected; compare with IAM logs, source IP, and recent changes before locking or disabling the user.",
            "-- Detail: LOGIN_HISTORY grouped by user, source IP, client, and error code.",
        )
    if "mfa" in value:
        return (
            "User/Auth",
            "Confirm the user authentication path, then enforce MFA through Snowflake or the identity provider.",
            "-- Detail: ACCOUNT_USAGE.USERS MFA/ext_authn_duo signal.",
        )
    if "grant" in value:
        return (
            "Grant/Role",
            "Confirm the grant route, business justification, and role hierarchy before revoking or narrowing access.",
            "-- Detail: ACCOUNT_USAGE.GRANTS_TO_USERS active grants created in the selected window.",
        )
    if "shared" in value or "database exposure" in value:
        return (
            "Shared Data",
            "Validate the consumer, route, contract, and data classification before leaving the share active.",
            "-- Detail: ACCOUNT_USAGE.DATABASES imported/share metadata.",
        )
    return (
        "User/Access",
        "Validate with IAM/Snowflake history, confirm the route, then remediate access or authentication configuration.",
        "-- Review telemetry query and route before revoking grants, disabling users, or enforcing MFA.",
    )

def _security_exception_has_database_context(row: pd.Series | dict) -> bool:
    if _security_exception_database(row):
        return True
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    return "shared" in finding_type or "database exposure" in finding_type or "object grant" in finding_type

def _security_exception_database(row: pd.Series | dict) -> str:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    if "failed login" in finding_type or "mfa" in finding_type or finding_type == "recent grant":
        return ""
    for key in ("DATABASE_NAME", "OBJECT_DATABASE", "TABLE_CATALOG"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    entity = str(row.get("ENTITY") or "").strip()
    if "." in entity:
        return entity.split(".", 1)[0].strip('"')
    if entity.upper().startswith(("ALFA_", "TRXS_")):
        return entity.strip('"')
    return ""

def _security_exception_environment(row: pd.Series | dict, environment: str = "ALL") -> str:
    if not _security_exception_has_database_context(row):
        return "No Database Context"
    database_name = _security_exception_database(row)
    if database_name:
        return environment_label_for_database(database_name)
    return str(environment or "").strip() or "ALL"

def _security_owner_context(row: pd.Series | dict) -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    entity = str(row.get("ENTITY") or "").upper()
    if "failed login" in finding_type or "mfa" in finding_type:
        base = {
            "owner": "IAM / Security Route",
            "escalation": "Security / DBA Route",
            "source": "Security route map",
        }
    elif "grant" in finding_type:
        if any(token in entity for token in ("ADMIN", "SECURITY", "SYSADMIN", "ACCOUNTADMIN")):
            base = {
                "owner": "Security Route",
                "escalation": "DBA / Security Route",
                "source": "Admin-role route hint",
            }
        else:
            base = {
                "owner": "Access Route / DBA Security",
                "escalation": "Data / Security Route",
                "source": "Security route map",
            }
    elif "shared" in finding_type or "exposure" in finding_type:
        base = {
            "owner": "Data / Security Route",
                "escalation": "Data Steward / Legal",
            "source": "Shared-data route map",
        }
    else:
        base = {
            "owner": "Security/DBA",
            "escalation": "DBA Lead",
            "source": "Default security route",
        }
    directory_context = resolve_owner_context(
        row,
        entity=entity,
        entity_type="SECURITY",
        owner=base["owner"],
        category=finding_type or "Security",
    )
    return {
        "owner": directory_context.get("OWNER") or base["owner"],
        "escalation": base["escalation"] or directory_context.get("REVIEW_TARGET", ""),
        "source": f"{base['source']}; {directory_context.get('ROUTE_SOURCE', '')}".strip("; "),
        "route_email": directory_context.get("ROUTE_EMAIL", ""),
        "review_primary": directory_context.get("REVIEW_PRIMARY", ""),
        "review_secondary": directory_context.get("REVIEW_SECONDARY", ""),
        "review_group": "",
        "route_evidence": directory_context.get("ROUTE_EVIDENCE", ""),
    }

def _security_review_context(row: pd.Series | dict) -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    if "failed login" in finding_type:
        return {
            "reviewer": "IAM / Security",
            "review_state": "Identity investigation required",
            "role_capability_state": "Not required",
            "proof_required": "user, source IP/client, error code, IAM corroboration, disposition",
        }
    if "mfa" in finding_type:
        return {
            "reviewer": "IAM / Security",
            "review_state": "MFA enforcement review required",
            "role_capability_state": "Not required",
            "proof_required": "user, auth path, MFA/SSO posture, exception note if any",
        }
    if "grant" in finding_type:
        return {
            "reviewer": "Access / Security",
            "review_state": "Access review required",
            "role_capability_state": "MANAGE GRANTS or role capability check required before change",
            "proof_required": "role, grantee, requester, ticket/reference, review/expiry date, telemetry status",
        }
    if "shared" in finding_type or "exposure" in finding_type:
        return {
            "reviewer": "Data Steward / Security",
            "review_state": "External sharing review required",
            "role_capability_state": "OWNERSHIP / IMPORTED PRIVILEGES capability check required for remediation",
            "proof_required": "consumer, provider, data classification, contract, review date",
        }
    return {
        "reviewer": "Security",
        "review_state": "Security review required",
        "role_capability_state": "Capability check depends on remediation",
        "proof_required": "finding telemetry, reviewer, ticket/reference, status",
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
        database_name = _security_exception_database(row)
        if database_name:
            db_lit = sql_literal(database_name, 300)
            return f"""
SELECT
    created_on,
    privilege,
    granted_on,
    name,
    table_catalog AS database_name,
    table_schema AS schema_name,
    granted_to,
    grantee_name,
    grant_option,
    granted_by,
    deleted_on
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES
WHERE deleted_on IS NULL
  AND UPPER(table_catalog) = UPPER({db_lit})
ORDER BY created_on DESC
LIMIT 100""".strip()
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

def _security_access_review_sla_hours(severity: str) -> int:
    value = str(severity or "").upper()
    if value == "CRITICAL":
        return 8
    if value == "HIGH":
        return 24
    if value == "MEDIUM":
        return 72
    return 168

def _security_access_review_readiness_for_row(row: pd.Series | dict) -> dict:
    """Return ticket/reference, telemetry, and blocker state for a security finding."""
    owner = str(row.get("OWNER") or "").strip()
    route_source = str(row.get("ROUTE_SOURCE") or "").strip()
    route_email = str(row.get("ROUTE_EMAIL") or "").strip()
    review = str(row.get("REVIEW_PRIMARY") or "").strip()
    escalation = str(row.get("REVIEW_TARGET") or "").strip()
    owner_upper = owner.upper()
    route_ready = bool(owner) and owner_upper not in {"UNKNOWN", "N/A", "NONE"} and bool(
        route_email
        or review
        or escalation
        or "SECURITY" in owner_upper
        or "IAM" in owner_upper
    )

    ticket_id = str(row.get("ACCESS_TICKET_ID") or row.get("TICKET_ID") or "").strip()
    review_by = str(row.get("REVIEW_BY_DATE") or row.get("REVIEW_BY") or row.get("REVIEW_DATE") or "").strip()
    verification_status = str(row.get("VERIFICATION_STATUS") or "Pending").strip()
    verification_result = str(row.get("VERIFICATION_RESULT") or "").strip()
    verification_query = str(row.get("VERIFICATION_QUERY") or "").strip()
    ticket_required = str(row.get("TICKET_REQUIRED") or "Yes").strip().upper() == "YES"
    review_required = str(row.get("REVIEW_BY_REQUIRED") or "Yes").strip().upper() == "YES"

    blockers: list[str] = []
    if not route_ready:
        blockers.append("route/review context")
    if ticket_required and not ticket_id:
        blockers.append("access ticket")
    if review_required and not review_by:
        blockers.append("review/expiry date")
    if not verification_query:
        blockers.append("telemetry query")

    verified = (
        verification_status.upper() == "VERIFIED"
        and len(verification_result) >= 15
    )
    if verified and not blockers:
        readiness = "Verified"
        rank = 8
        next_action = "Keep IAM/Snowflake telemetry with the access-review snapshot."
    elif "route/review context" in blockers:
        readiness = "Assignment Blocked"
        rank = 0
        next_action = "Assign this finding before queueing closure."
    elif "access ticket" in blockers or "review/expiry date" in blockers:
        readiness = "Ticket / Review Date Blocked"
        rank = 1
        next_action = "Add the access ticket and review/expiry date before treating this finding as controlled."
    elif "telemetry query" in blockers:
        readiness = "Telemetry Pending"
        rank = 3
        next_action = "Load the read-only Snowflake telemetry query before queueing the action."
    else:
        readiness = "Ready for Action Queue"
        rank = 4
        next_action = "Queue or work the security action, then monitor the resulting telemetry."

    return {
        "ACCESS_TICKET_ID": ticket_id,
        "REVIEW_BY_DATE": review_by,
        "IAM_REVIEW_STATE": "Review Required",
        "REVIEW_READINESS": readiness,
        "REVIEW_RANK": rank,
        "REVIEW_BLOCKERS": "; ".join(blockers) if blockers else "None",
        "REVIEW_SLA_HOURS": _security_access_review_sla_hours(str(row.get("SEVERITY") or "")),
        "VERIFICATION_STATUS": verification_status or "Pending",
        "VERIFICATION_RESULT": verification_result,
        "CONTROL_READINESS": readiness,
        "CONTROL_BLOCKERS": "; ".join(blockers) if blockers else "None",
        "NEXT_CONTROL_ACTION": next_action,
    }

def _build_security_access_review(exceptions: pd.DataFrame, environment: str = "ALL") -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    view = _security_priority_view(exceptions).copy()
    owner_contexts = view.apply(_security_owner_context, axis=1)
    review_contexts = view.apply(_security_review_context, axis=1)
    view["OWNER"] = owner_contexts.apply(lambda item: item["owner"])
    view["REVIEW_TARGET"] = owner_contexts.apply(lambda item: item["escalation"])
    view["ROUTE_SOURCE"] = owner_contexts.apply(lambda item: item["source"])
    view["ROUTE_EMAIL"] = owner_contexts.apply(lambda item: item.get("route_email", ""))
    view["REVIEW_PRIMARY"] = owner_contexts.apply(lambda item: item.get("review_primary", ""))
    view["REVIEW_SECONDARY"] = owner_contexts.apply(lambda item: item.get("review_secondary", ""))
    view["REVIEW_GROUP"] = ""
    view["ROUTE_EVIDENCE"] = owner_contexts.apply(lambda item: item.get("route_evidence", ""))
    view["APPROVER"] = review_contexts.apply(lambda item: item["reviewer"])
    view["REVIEW_STATUS"] = ""
    view["ACCESS_REVIEW_STATE"] = review_contexts.apply(lambda item: item["review_state"])
    view["ROLE_CAPABILITY_STATE"] = review_contexts.apply(lambda item: item["role_capability_state"])
    view["TICKET_REQUIRED"] = "Yes"
    view["REVIEW_BY_REQUIRED"] = "Yes"
    view["PROOF_REQUIRED"] = review_contexts.apply(lambda item: item["proof_required"])
    view["VERIFICATION_QUERY"] = view.apply(_security_exception_verification_sql, axis=1)
    view["DATABASE_CONTEXT"] = view.apply(_security_exception_has_database_context, axis=1)
    view["DATABASE_NAME"] = view.apply(_security_exception_database, axis=1)
    view["ENVIRONMENT"] = view.apply(lambda row: _security_exception_environment(row, environment), axis=1)
    view["SCOPE_CONFIDENCE"] = view["DATABASE_CONTEXT"].map({True: "Database Context", False: "Account/User Context"})
    view["SCOPE_EVIDENCE"] = view.apply(
        lambda row: (
            f"Database={row.get('DATABASE_NAME')}; environment={row.get('ENVIRONMENT')}"
            if bool(row.get("DATABASE_CONTEXT"))
            else "No database context; company/user scope only"
        ),
        axis=1,
    )
    readiness_contexts = view.apply(_security_access_review_readiness_for_row, axis=1)
    for column in [
        "ACCESS_TICKET_ID",
        "REVIEW_BY_DATE",
        "IAM_APPROVAL_STATE",
        "REVIEW_READINESS",
        "REVIEW_RANK",
        "REVIEW_BLOCKERS",
        "REVIEW_SLA_HOURS",
        "VERIFICATION_STATUS",
        "VERIFICATION_RESULT",
        "CONTROL_READINESS",
        "CONTROL_BLOCKERS",
        "NEXT_CONTROL_ACTION",
    ]:
        view[column] = readiness_contexts.apply(lambda item, col=column: item.get(col, ""))
    return view

def _security_workflow_for(finding_type: str) -> str:
    value = str(finding_type or "").lower()
    if "shared" in value or "exposure" in value:
        return "Data Sharing Exposure"
    if "privileged" in value or "grant" in value:
        return "Privilege Sprawl"
    return "Failed Logins"

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
    view = (
        _build_security_access_review(review, environment)
        if "ACCESS_REVIEW_STATE" not in review.columns or "REVIEW_READINESS" not in review.columns
        else review.copy()
    )
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
            f"{sql_literal(row.get('REVIEW_TARGET', ''), 200)} AS REVIEW_TARGET, "
            f"{sql_literal(row.get('ROUTE_SOURCE', ''), 200)} AS ROUTE_SOURCE, "
            f"{sql_literal(row.get('APPROVER', ''), 200)} AS APPROVER, "
            f"{sql_literal(row.get('REVIEW_STATUS', ''), 40)} AS REVIEW_STATUS, "
            f"{sql_literal(row.get('ACCESS_REVIEW_STATE', ''), 160)} AS ACCESS_REVIEW_STATE, "
            f"{sql_literal(row.get('ROLE_CAPABILITY_STATE', ''), 200)} AS ROLE_CAPABILITY_STATE, "
            f"{sql_literal(row.get('TICKET_REQUIRED', ''), 20)} AS TICKET_REQUIRED, "
            f"{sql_literal(row.get('REVIEW_BY_REQUIRED', ''), 20)} AS REVIEW_BY_REQUIRED, "
            f"{sql_literal(row.get('PROOF_REQUIRED', ''), 2000)} AS PROOF_REQUIRED, "
            f"{sql_literal(row.get('VERIFICATION_QUERY', ''), 8000)} AS VERIFICATION_QUERY, "
            f"{sql_literal(row.get('ACCESS_TICKET_ID', ''), 200)} AS ACCESS_TICKET_ID, "
            f"{sql_literal(row.get('REVIEW_BY_DATE', ''), 100)} AS REVIEW_BY_DATE, "
            f"{sql_literal(row.get('IAM_APPROVAL_STATE', row.get('REVIEW_STATUS', 'Requested')), 120)} AS IAM_APPROVAL_STATE, "
            f"{sql_literal(row.get('REVIEW_READINESS', ''), 100)} AS REVIEW_READINESS, "
            f"{sql_literal(row.get('REVIEW_BLOCKERS', ''), 2000)} AS REVIEW_BLOCKERS, "
            f"{safe_int(row.get('REVIEW_SLA_HOURS'))}::NUMBER AS REVIEW_SLA_HOURS, "
            f"{sql_literal(row.get('VERIFICATION_STATUS', 'Pending'), 80)} AS VERIFICATION_STATUS, "
            f"{sql_literal(row.get('VERIFICATION_RESULT', ''), 4000)} AS VERIFICATION_RESULT, "
            f"{sql_literal(row.get('CONTROL_READINESS', row.get('REVIEW_READINESS', '')), 100)} AS CONTROL_READINESS, "
            f"{sql_literal(row.get('CONTROL_BLOCKERS', row.get('REVIEW_BLOCKERS', '')), 2000)} AS CONTROL_BLOCKERS, "
            f"{sql_literal(row.get('NEXT_CONTROL_ACTION', ''), 4000)} AS NEXT_CONTROL_ACTION, "
            f"{sql_literal(row.get('NEXT_ACTION', ''), 4000)} AS NEXT_ACTION, "
            f"{sql_literal(row.get('PROOF_QUERY', ''), 4000)} AS PROOF_QUERY, "
            f"{sql_literal(source, 500)} AS SOURCE"
        )
    return f"""
INSERT INTO {fqn} (
    SNAPSHOT_ID, SNAPSHOT_TS, COMPANY, ENVIRONMENT, DATABASE_CONTEXT,
    FINDING_TYPE, SEVERITY, ENTITY_TYPE, ENTITY, EVENT_COUNT, DISTINCT_SOURCES,
    LAST_SEEN, OWNER, REVIEW_TARGET, ROUTE_SOURCE, APPROVER,
    REVIEW_STATUS, ACCESS_REVIEW_STATE, ROLE_CAPABILITY_STATE,
    TICKET_REQUIRED, REVIEW_BY_REQUIRED, PROOF_REQUIRED, VERIFICATION_QUERY,
    ACCESS_TICKET_ID, REVIEW_BY_DATE, IAM_APPROVAL_STATE, REVIEW_READINESS,
    REVIEW_BLOCKERS, REVIEW_SLA_HOURS, VERIFICATION_STATUS, VERIFICATION_RESULT,
    CONTROL_READINESS, CONTROL_BLOCKERS, NEXT_CONTROL_ACTION,
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
    REVIEW_TARGET,
    COUNT(*) AS REVIEW_ROWS,
    SUM(EVENT_COUNT) AS TOTAL_EVENTS,
    COUNT_IF(TICKET_REQUIRED = 'Yes') AS TICKET_REQUIRED_ROWS,
    COUNT_IF(REVIEW_BY_REQUIRED = 'Yes') AS REVIEW_BY_REQUIRED_ROWS,
    COUNT_IF(ROLE_CAPABILITY_STATE ILIKE '%required%') AS CAPABILITY_PROOF_ROWS,
    COUNT_IF(DATABASE_CONTEXT = FALSE) AS NO_DATABASE_CONTEXT_ROWS,
    COUNT_IF(REVIEW_READINESS ILIKE '%Blocked%') AS REVIEW_BLOCKER_ROWS,
    COUNT_IF(VERIFICATION_STATUS = 'Verified' AND LENGTH(TRIM(VERIFICATION_RESULT)) >= 15) AS VERIFIED_REVIEW_ROWS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX_BY(ACCESS_REVIEW_STATE, SNAPSHOT_TS) AS LAST_ACCESS_REVIEW_STATE,
    MAX_BY(REVIEW_READINESS, SNAPSHOT_TS) AS LAST_REVIEW_READINESS,
    MAX_BY(CONTROL_READINESS, SNAPSHOT_TS) AS LAST_CONTROL_READINESS,
    MAX_BY(ROLE_CAPABILITY_STATE, SNAPSHOT_TS) AS LAST_ROLE_CAPABILITY_STATE,
    MAX_BY(PROOF_REQUIRED, SNAPSHOT_TS) AS LAST_PROOF_REQUIRED,
    MAX_BY(NEXT_CONTROL_ACTION, SNAPSHOT_TS) AS NEXT_CONTROL_ACTION
FROM {fqn}
WHERE {where_clause}
GROUP BY FINDING_TYPE, SEVERITY, OWNER, REVIEW_TARGET
ORDER BY
    REVIEW_BLOCKER_ROWS DESC,
    TICKET_REQUIRED_ROWS DESC,
    CAPABILITY_PROOF_ROWS DESC,
    TOTAL_EVENTS DESC,
    LAST_SNAPSHOT_TS DESC
LIMIT 100""".strip()

def _security_action_queue_closure_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier(ACTION_QUEUE_TABLE)}"
    where = [
        "SOURCE IN ('Security Posture - Security Summary', 'Security Posture - Privileged Grant Status')",
        f"COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_TIMESTAMP())",
    ]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
WITH scoped_actions AS (
    SELECT
        COALESCE(CATEGORY, 'Security') AS CATEGORY,
        COALESCE(ENTITY_TYPE, 'Security Finding') AS ENTITY_TYPE,
        COALESCE(ENTITY_NAME, 'Unknown') AS ENTITY,
        COALESCE(OWNER, '') AS OWNER,
        COALESCE(APPROVER, '') AS APPROVER,
        COALESCE(STATUS, 'New') AS STATUS,
        COALESCE(SEVERITY, 'Medium') AS SEVERITY,
        COALESCE(TICKET_ID, '') AS TICKET_ID,
        DUE_DATE,
        COALESCE(VERIFICATION_STATUS, '') AS VERIFICATION_STATUS,
        COALESCE(VERIFICATION_QUERY, PROOF_QUERY, '') AS VERIFICATION_QUERY,
        COALESCE(VERIFICATION_RESULT, '') AS VERIFICATION_RESULT,
        COALESCE(REVIEW_STATUS, '') AS REVIEW_STATUS,
        COALESCE(RECOVERY_SLA_STATE, '') AS RECOVERY_SLA_STATE,
        COALESCE(RECOVERY_EVIDENCE, '') AS RECOVERY_EVIDENCE,
        COALESCE(UPDATED_AT, CREATED_AT) AS LAST_ACTIVITY_TS
    FROM {fqn}
    WHERE {where_clause}
),
rollup AS (
    SELECT
        CATEGORY,
        ENTITY_TYPE,
        ENTITY,
        MAX_BY(OWNER, LAST_ACTIVITY_TS) AS OWNER,
        MAX_BY(APPROVER, LAST_ACTIVITY_TS) AS APPROVER,
        COUNT(*) AS TOTAL_ACTIONS,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
        COUNT_IF(UPPER(STATUS) = 'FIXED') AS FIXED_ACTIONS,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND UPPER(VERIFICATION_STATUS) = 'VERIFIED'
            AND LENGTH(TRIM(VERIFICATION_RESULT)) >= 15
        ) AS VERIFIED_CLOSURES,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND (
                UPPER(VERIFICATION_STATUS) <> 'VERIFIED'
                OR LENGTH(TRIM(VERIFICATION_RESULT)) < 15
            )
        ) AS FIXED_WITHOUT_VERIFICATION,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
        COUNT_IF(UPPER(OWNER) IN ('', 'SECURITY/DBA', 'DBA', 'UNKNOWN', 'N/A')) AS WORKFLOW_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(TICKET_ID)) = 0) AS TICKET_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(APPROVER)) = 0) AS APPROVER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(VERIFICATION_QUERY)) = 0) AS VERIFICATION_QUERY_GAP_ROWS,
        COUNT_IF(UPPER(REVIEW_STATUS) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS REVIEW_GAP_ROWS,
        COUNT_IF(
            UPPER(RECOVERY_SLA_STATE) ILIKE '%BREACH%'
            OR UPPER(RECOVERY_SLA_STATE) ILIKE '%LATE%'
            OR (
                UPPER(STATUS) = 'FIXED'
                AND LENGTH(TRIM(RECOVERY_EVIDENCE)) < 15
            )
        ) AS RECOVERY_RISK_ROWS,
        MIN(IFF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED'), DUE_DATE, NULL)) AS NEXT_DUE_DATE,
        MAX(LAST_ACTIVITY_TS) AS LAST_ACTIVITY_TS,
        MAX_BY(STATUS, LAST_ACTIVITY_TS) AS LAST_STATUS,
        MAX_BY(SEVERITY, LAST_ACTIVITY_TS) AS LAST_SEVERITY
    FROM scoped_actions
    GROUP BY CATEGORY, ENTITY_TYPE, ENTITY
)
SELECT
    CATEGORY,
    ENTITY_TYPE,
    ENTITY,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Overdue closure'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Status needs telemetry'
        WHEN WORKFLOW_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + REVIEW_GAP_ROWS > 0 THEN 'Control metadata gap'
        WHEN OPEN_ACTIONS > 0 THEN 'Open'
        WHEN VERIFIED_CLOSURES > 0 THEN 'Telemetry closure'
        ELSE 'No recent action'
    END AS CLOSURE_READINESS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 0
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 1
        WHEN WORKFLOW_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + REVIEW_GAP_ROWS > 0 THEN 2
        WHEN OPEN_ACTIONS > 0 THEN 3
        WHEN VERIFIED_CLOSURES > 0 THEN 8
        ELSE 9
    END AS CLOSURE_RANK,
    OWNER,
    APPROVER,
    TOTAL_ACTIONS,
    OPEN_ACTIONS,
    FIXED_ACTIONS,
    VERIFIED_CLOSURES,
    FIXED_WITHOUT_VERIFICATION,
    OVERDUE_OPEN,
    WORKFLOW_GAP_ROWS,
    TICKET_GAP_ROWS,
    APPROVER_GAP_ROWS,
    VERIFICATION_QUERY_GAP_ROWS,
    REVIEW_GAP_ROWS,
    RECOVERY_RISK_ROWS,
    NEXT_DUE_DATE,
    LAST_STATUS,
    LAST_SEVERITY,
    LAST_ACTIVITY_TS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Escalate the security route and ticket before lower-risk access cleanup.'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Reopen the security action or wait for telemetry to confirm closure.'
        WHEN WORKFLOW_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + REVIEW_GAP_ROWS > 0 THEN 'Complete route, ticket, reviewer, and telemetry metadata.'
        WHEN OPEN_ACTIONS > 0 THEN 'Work the open security action and retain IAM/Snowflake telemetry.'
        ELSE 'Keep closure status visible for audit review.'
    END AS NEXT_ACTION
FROM rollup
ORDER BY CLOSURE_RANK, OVERDUE_OPEN DESC, FIXED_WITHOUT_VERIFICATION DESC, OPEN_ACTIONS DESC, LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()

def _security_operability_fact_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Read security review and action-queue control blockers from the fast summary."""
    table = security_operability_fact_fqn()
    where = [f"SNAPSHOT_DATE >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_DATE())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
SELECT
    SNAPSHOT_DATE,
    COMPANY,
    ENVIRONMENT,
    CONTROL_SOURCE,
    FINDING_TYPE,
    ENTITY,
    ENTITY_TYPE,
    SEVERITY,
    CONTROL_STATE,
    CONTROL_RANK,
    EVENT_ROWS,
    REVIEW_ROWS,
    REVIEW_BLOCKER_ROWS,
    TICKET_REQUIRED_ROWS,
    REVIEW_BY_REQUIRED_ROWS,
    CAPABILITY_PROOF_ROWS,
    NO_DATABASE_CONTEXT_ROWS,
    OPEN_ACTIONS,
    OVERDUE_OPEN,
    FIXED_WITHOUT_VERIFICATION,
    VERIFIED_CLOSURES,
    REVIEW_GAP_ROWS,
    NEXT_CONTROL_ACTION,
    LAST_ACTIVITY_TS,
    LOAD_TS
FROM {table}
WHERE {where_clause}
ORDER BY
    CONTROL_RANK,
    OVERDUE_OPEN DESC,
    FIXED_WITHOUT_VERIFICATION DESC,
    REVIEW_BLOCKER_ROWS DESC,
    EVENT_ROWS DESC,
    LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()

def _security_control_board(
    access_review: pd.DataFrame,
    closure: pd.DataFrame | None = None,
    trend: pd.DataFrame | None = None,
    environment: str = "ALL",
) -> pd.DataFrame:
    """Combine current findings, closure state, and snapshot trend into one DBA control board."""
    if access_review is None or access_review.empty:
        return pd.DataFrame()

    base = (
        _build_security_access_review(access_review, environment)
        if "REVIEW_READINESS" not in access_review.columns
        else access_review.copy()
    )
    base.columns = [str(col).upper() for col in base.columns]

    closure_view = pd.DataFrame() if closure is None else closure.copy()
    if not closure_view.empty:
        closure_view.columns = [str(col).upper() for col in closure_view.columns]
    trend_view = pd.DataFrame() if trend is None else trend.copy()
    if not trend_view.empty:
        trend_view.columns = [str(col).upper() for col in trend_view.columns]

    closure_by_entity = {
        str(row.get("ENTITY") or "").upper(): row
        for _, row in closure_view.iterrows()
    } if not closure_view.empty else {}
    trend_by_finding = {
        str(row.get("FINDING_TYPE") or "").upper(): row
        for _, row in trend_view.iterrows()
    } if not trend_view.empty else {}

    rows: list[dict] = []
    for _, row in base.iterrows():
        entity = str(row.get("ENTITY") or "")
        finding_type = str(row.get("FINDING_TYPE") or "")
        close = closure_by_entity.get(entity.upper(), {})
        trend_row = trend_by_finding.get(finding_type.upper(), {})
        review_readiness = str(row.get("REVIEW_READINESS") or row.get("CONTROL_READINESS") or "")
        review_rank = safe_int(row.get("REVIEW_RANK", 4))
        open_actions = safe_int(close.get("OPEN_ACTIONS", 0))
        overdue = safe_int(close.get("OVERDUE_OPEN", 0))
        fixed_without_verification = safe_int(close.get("FIXED_WITHOUT_VERIFICATION", 0))
        recovery_risk = safe_int(close.get("RECOVERY_RISK_ROWS", 0))
        verified = safe_int(close.get("VERIFIED_CLOSURES", 0))
        closure_rank = safe_int(close.get("CLOSURE_RANK", 9))
        review_rows = safe_int(trend_row.get("REVIEW_ROWS", 0))
        blocker_rows = safe_int(trend_row.get("REVIEW_BLOCKER_ROWS", 0))
        severity = str(row.get("SEVERITY") or "Medium")

        if overdue:
            state, rank = "Closure Overdue", 0
            blockers = str(close.get("CLOSURE_READINESS") or "overdue action")
            next_action = str(close.get("NEXT_ACTION") or "Escalate route and ticket before accepting the security control.")
        elif fixed_without_verification or recovery_risk or closure_rank in {1, 2}:
            state, rank = "Closure Status Pending", 1
            blockers = str(close.get("CLOSURE_READINESS") or "closure status gap")
            next_action = str(close.get("NEXT_ACTION") or "Reopen the security action or wait for telemetry to confirm closure.")
        elif "BLOCKED" in review_readiness.upper():
            state, rank = review_readiness, min(review_rank, 3)
            blockers = str(row.get("REVIEW_BLOCKERS") or row.get("CONTROL_BLOCKERS") or "review metadata gap")
            next_action = str(row.get("NEXT_CONTROL_ACTION") or "Complete review metadata before queueing closure.")
        elif open_actions > 0:
            state, rank = "Work Open Action", 4
            blockers = "Open action queue item"
            next_action = str(close.get("NEXT_ACTION") or "Work open security action and retain IAM/Snowflake telemetry.")
        elif severity.upper() in {"CRITICAL", "HIGH"} and not open_actions and not verified:
            state, rank = "Queue Required", 5
            blockers = "High-risk finding is not represented by an open action"
            next_action = "Save this security finding to the Action Queue with assignment, ticket/reference, and verification context."
        elif blocker_rows or review_rows > 1:
            state, rank = "Recurring Access Watch", 6
            blockers = f"{review_rows:,} snapshot row(s), {blocker_rows:,} blocker row(s)"
            next_action = "Review repeated security snapshots and convert recurring access risk into a durable control."
        elif verified:
            state, rank = "Telemetry Confirmed", 8
            blockers = "None"
            next_action = "Keep closure telemetry visible for security trend review."
        else:
            state, rank = "Controlled", 9
            blockers = str(row.get("CONTROL_BLOCKERS") or "None")
            next_action = str(row.get("NEXT_CONTROL_ACTION") or "No immediate DBA action for this finding.")

        rows.append({
            "CONTROL_STATE": state,
            "CONTROL_RANK": rank,
            "SEVERITY": severity,
            "FINDING_TYPE": finding_type,
            "ENTITY": entity,
            "ENTITY_TYPE": row.get("ENTITY_TYPE", ""),
            "ENVIRONMENT": row.get("ENVIRONMENT", ""),
            "DATABASE_CONTEXT": bool(row.get("DATABASE_CONTEXT")),
            "SCOPE_CONFIDENCE": row.get("SCOPE_CONFIDENCE", ""),
            "OWNER": row.get("OWNER", close.get("OWNER", "")),
            "REVIEW_TARGET": row.get("REVIEW_TARGET", ""),
            "APPROVER": row.get("APPROVER", close.get("APPROVER", "")),
            "REVIEW_READINESS": review_readiness,
            "REVIEW_BLOCKERS": row.get("REVIEW_BLOCKERS", ""),
            "ACCESS_TICKET_ID": row.get("ACCESS_TICKET_ID", ""),
            "REVIEW_BY_DATE": row.get("REVIEW_BY_DATE", ""),
            "IAM_APPROVAL_STATE": row.get("IAM_APPROVAL_STATE", ""),
            "REVIEW_SLA_HOURS": safe_int(row.get("REVIEW_SLA_HOURS", 0)),
            "OPEN_ACTIONS": open_actions,
            "OVERDUE_OPEN": overdue,
            "FIXED_WITHOUT_VERIFICATION": fixed_without_verification,
            "VERIFIED_CLOSURES": verified,
            "REVIEW_SNAPSHOTS": review_rows,
            "CONTROL_BLOCKERS": blockers,
            "NEXT_CONTROL_ACTION": next_action,
        })

    return pd.DataFrame(rows).sort_values(
        [
            "CONTROL_RANK",
            "OVERDUE_OPEN",
            "FIXED_WITHOUT_VERIFICATION",
            "OPEN_ACTIONS",
            "SEVERITY",
            "FINDING_TYPE",
            "ENTITY",
        ],
        ascending=[True, False, False, False, True, True, True],
    ).reset_index(drop=True)

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
        for migration_sql in build_security_access_review_migration_sql():
            session.sql(migration_sql).collect()
        session.sql(_security_access_review_insert_sql(
            review,
            company=company,
            environment=environment,
            source=source,
        )).collect()
        st.success("Saved the Security Access Review snapshot for route, ticket, and telemetry tracking.")
    except Exception as exc:
        st.error(f"Could not save Security Access Review snapshot: {format_snowflake_error(exc)}")
        st.info("Security access review history is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")

__all__ = [
    'SECURITY_ACCESS_REVIEW_TABLE',
    'SECURITY_OPERABILITY_FACT_TABLE',
    'security_access_review_fqn',
    'build_security_access_review_ddl',
    'build_security_access_review_migration_sql',
    'security_operability_fact_fqn',
    'build_security_operability_fact_ddl',
    'build_security_operability_fact_migration_sql',
    '_security_action_for',
    '_security_exception_has_database_context',
    '_security_exception_database',
    '_security_exception_environment',
    '_security_owner_context',
    '_security_review_context',
    '_security_exception_verification_sql',
    '_security_access_review_sla_hours',
    '_security_access_review_readiness_for_row',
    '_build_security_access_review',
    '_security_workflow_for',
    '_security_priority_view',
    '_security_access_review_insert_sql',
    '_security_access_review_history_sql',
    '_security_action_queue_closure_sql',
    '_security_operability_fact_sql',
    '_security_control_board',
    '_save_security_access_review_snapshot',
]
