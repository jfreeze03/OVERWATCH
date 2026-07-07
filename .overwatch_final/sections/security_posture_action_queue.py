# sections/security_posture_action_queue.py - Security action queue writers
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.security_posture_access_review import (
    _build_security_access_review,
    _security_action_for,
    _security_exception_environment,
    _security_exception_verification_sql,
)
from sections.security_posture_common import get_active_company, get_active_environment
from utils.primitives import safe_int


pd = lazy_pandas()

format_snowflake_error = _lazy_util("format_snowflake_error")
make_action_id = _lazy_util("make_action_id")
sql_literal = _lazy_util("sql_literal")
upsert_actions = _lazy_util("upsert_actions")

def _privileged_grant_verification_sql(row: pd.Series | dict) -> str:
    """Return read-only telemetry detail for a privileged grant review row."""
    entity = str(row.get("ENTITY") or "").strip()
    role_name = str(row.get("ROLE_NAME") or "").strip()
    object_name = str(row.get("OBJECT_NAME") or "").strip()
    database_name = str(row.get("DATABASE_NAME") or "").strip()
    entity_lit = sql_literal(entity, 500)
    if role_name:
        role_lit = sql_literal(role_name, 300)
        return f"""
SELECT
    grantee_name,
    role,
    granted_by,
    created_on,
    deleted_on
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
WHERE deleted_on IS NULL
  AND UPPER(grantee_name) = UPPER({entity_lit})
  AND UPPER(role) = UPPER({role_lit})
ORDER BY created_on DESC
LIMIT 100""".strip()
    if object_name:
        object_lit = sql_literal(object_name, 800)
        db_clause = ""
        if database_name:
            db_clause = f"\n  AND UPPER(table_catalog) = UPPER({sql_literal(database_name, 300)})"
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
  AND UPPER(grantee_name) = UPPER({entity_lit})
  AND UPPER(name) = UPPER({object_lit}){db_clause}
ORDER BY created_on DESC
LIMIT 100""".strip()
    return f"""
SELECT
    CURRENT_TIMESTAMP() AS verification_ts,
    {entity_lit} AS grantee_name,
    'Privileged grant review row did not include a role or object name.' AS review_note
LIMIT 50""".strip()

def _privileged_grant_action_payload(row: pd.Series | dict, *, company: str, environment: str) -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "Privileged Grant")
    entity = str(row.get("ENTITY") or "Unknown")
    role_name = str(row.get("ROLE_NAME") or "").strip()
    object_name = str(row.get("OBJECT_NAME") or "").strip()
    database_name = str(row.get("DATABASE_NAME") or "").strip()
    severity = str(row.get("SEVERITY") or "High")
    target = role_name or object_name or database_name or entity
    finding = f"{finding_type}: {entity} has privileged access to {target}"
    verification_query = _privileged_grant_verification_sql(row)
    row_environment = str(row.get("ENVIRONMENT") or environment or "ALL")
    return {
        "Action ID": make_action_id("Security Privileged Grant", entity, target),
        "Source": "Security Posture - Privileged Grant Status",
        "Severity": severity,
        "Category": "Security Access Review",
        "Entity Type": "Privileged Grant",
        "Entity": entity,
        "Owner": row.get("OWNER", "Security/DBA"),
        "Email Target": row.get("EMAIL_TARGET", ""),
        "Reviewed By": row.get("REVIEWED_BY", ""),
        "Reviewed By": row.get("REVIEWED_BY", ""),
        "Review Status": row.get("WORKFLOW_ROUTE", "Security"),
        "Workflow Route": row.get("WORKFLOW_ROUTE", "DBA / Security Route"),
        "Allocation Source": row.get("ALLOCATION_SOURCE", ""),
        "Allocation Basis": row.get("ALLOCATION_BASIS", ""),
        "Finding": finding,
        "Action": (
            "Review privileged grant before granting, revoking, or narrowing access. "
            f"Status={row.get('GRANT_REVIEW_READINESS', '')}; "
            f"state={row.get('GRANT_REVIEW_STATE', '')}; telemetry basis={row.get('PROOF_REQUIRED', '')}."
        ),
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": "\n".join([
            "-- Review-only privileged grant control row.",
            "-- Do not grant, revoke, or narrow access from OVERWATCH; use Snowflake/IAM operational change paths.",
            f"-- Role: {role_name or 'N/A'}",
            f"-- Object: {object_name or 'N/A'}",
            f"-- Database: {database_name or 'No database context'}",
            f"-- Environment: {row_environment}",
            "-- Use the telemetry query and ticket/reference before remediation.",
        ]),
        "Proof Query": verification_query,
        "Verification Query": verification_query,
        "Verification Status": "Pending",
        "Ticket ID": "",
        "Reviewer": row.get("WORKFLOW_ROUTE", "Security"),
        "Review Status": "Requested",
        "Review Note": (
            f"{row.get('GRANT_REVIEW_STATE', '')}; status {row.get('GRANT_REVIEW_READINESS', '')}; "
            f"assignment ready {row.get('WORKFLOW_ROUTE_READY', '')}; scope {row.get('SCOPE_CONFIDENCE', '')}."
        ),
        "Recovery Evidence": (
            f"Telemetry basis: {row.get('PROOF_REQUIRED', '')}. "
            "Track ticket/reference, rollback note, and post-change grant status."
        ),
        "Recovery Audit State": row.get("GRANT_REVIEW_READINESS", "Telemetry Pending"),
        "Recovery SLA Target Hours": 24 if str(severity).upper() in {"CRITICAL", "HIGH"} else 72,
        "Company": company,
        "Environment": row_environment,
    }

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
            "Source": "Security Posture - Security Summary",
            "Severity": severity,
            "Category": "Security",
            "Entity Type": entity_type,
            "Entity": entity,
            "Owner": row.get("OWNER", "Security/DBA"),
            "Email Target": row.get("EMAIL_TARGET", ""),
            "Reviewed By": row.get("REVIEWED_BY", ""),
            "Reviewed By": row.get("REVIEWED_BY", ""),
            "Review Status": row.get("WORKFLOW_ROUTE", row.get("APPROVER", "Security")),
            "Workflow Route": row.get("WORKFLOW_ROUTE", "DBA Lead"),
            "Allocation Source": row.get("ALLOCATION_SOURCE", ""),
            "Allocation Basis": row.get("ALLOCATION_BASIS", ""),
            "Finding": finding,
            "Action": (
                f"{action} Review with {row.get('APPROVER', 'Security')} is required; "
                f"telemetry basis: {row.get('PROOF_REQUIRED', 'security telemetry and status')}."
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
            "Verification Status": row.get("VERIFICATION_STATUS", "Pending"),
            "Ticket ID": row.get("ACCESS_TICKET_ID", ""),
            "Reviewer": row.get("APPROVER", "Security"),
            "Review Status": row.get("IAM_REVIEW_STATE", "Requested"),
            "Review Note": (
                f"{row.get('ACCESS_REVIEW_STATE', '')}; status {row.get('REVIEW_READINESS', '')}; "
                f"blockers {row.get('REVIEW_BLOCKERS', '')}; escalation {row.get('WORKFLOW_ROUTE', 'DBA Lead')}; "
                f"ticket required {row.get('TICKET_REQUIRED', 'Yes')}; review-by required {row.get('REVIEW_BY_REQUIRED', 'Yes')}."
            ),
            "Recovery Evidence": (
                f"Telemetry basis: {row.get('PROOF_REQUIRED', '')}. "
                f"Role capability: {row.get('ROLE_CAPABILITY_STATE', '')}. "
                f"Review SLA hours: {safe_int(row.get('REVIEW_SLA_HOURS', 0))}."
            ),
            "Recovery Audit State": row.get("CONTROL_READINESS", "Security Review Telemetry Pending"),
            "Recovery SLA Target Hours": safe_int(row.get("REVIEW_SLA_HOURS", 24 if severity.upper() in {"CRITICAL", "HIGH"} else 72)),
            "Company": company,
            "Environment": row.get("ENVIRONMENT", _security_exception_environment(row, environment)),
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} security exceptions to the action queue.")
    except Exception as e:
        st.error(f"Could not save security exceptions: {format_snowflake_error(e)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")

def _queue_privileged_grant_actions(
    session,
    grants: pd.DataFrame,
    *,
    company: str,
    environment: str,
) -> None:
    if grants is None or grants.empty:
        st.info("No privileged grant rows to queue.")
        return
    actionable = grants[
        grants.get("GRANT_REVIEW_READINESS", pd.Series(dtype=str)).astype(str).isin([
            "Assignment Blocked",
            "Telemetry Pending",
            "Review Ready",
        ])
    ].copy()
    if actionable.empty:
        st.info("No privileged grant rows need action-queue tracking for the selected scope.")
        return
    actions = [
        _privileged_grant_action_payload(row, company=company, environment=environment)
        for _, row in actionable.head(100).iterrows()
    ]
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} privileged grant review rows to the action queue.")
    except Exception as exc:
        st.error(f"Could not save privileged grant actions: {format_snowflake_error(exc)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")

__all__ = [
    '_privileged_grant_verification_sql',
    '_privileged_grant_action_payload',
    '_queue_security_exceptions',
    '_queue_privileged_grant_actions',
]
