"""Account Health review-only action queue payloads and writers."""
from __future__ import annotations

import streamlit as st

from sections.account_health_access_hygiene import (
    _account_health_access_hygiene_verification_sql,
    _annotate_account_health_access_hygiene,
)
from sections.account_health_checklist import (
    _account_health_actionable_checklist,
    _account_health_recovery_target_hours,
    _account_health_verification_sql,
    _annotate_account_health_checklist_readiness,
)
from sections.account_health_contracts import (
    ACCOUNT_HEALTH_ACCESS_HYGIENE_SOURCE,
    ACCOUNT_HEALTH_ACTION_SOURCE,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util


pd = lazy_pandas()

format_snowflake_error = _lazy_util("format_snowflake_error")
make_action_id = _lazy_util("make_action_id")
upsert_actions = _lazy_util("upsert_actions")


def _account_health_checklist_action_payload(row: pd.Series | dict, company: str, environment: str = "") -> dict:
    if "QUEUE_READINESS" not in row or "SCOPE_CONFIDENCE" not in row:
        annotated = _annotate_account_health_checklist_readiness(pd.DataFrame([dict(row)]), environment=environment)
        if annotated is not None and not annotated.empty:
            row = annotated.iloc[0].to_dict()
    check = str(row.get("CHECK") or "Daily DBA checklist")
    evidence = str(row.get("EVIDENCE") or "")
    severity = str(row.get("SEVERITY") or "Medium")
    owner = str(row.get("OWNER") or "DBA")
    escalation = str(row.get("ESCALATION_TARGET") or "DBA Lead")
    route = str(row.get("ROUTE") or "DBA Control Room")
    approval_group = str(row.get("APPROVAL_GROUP") or escalation or owner)
    verification_query = _account_health_verification_sql(check, evidence)
    action = str(row.get("NEXT_ACTION") or "Review the failed Account Health checklist item and keep telemetry current.")
    approval_required = severity.upper() in {"CRITICAL", "HIGH", "MEDIUM"}
    env_value = str(environment or "").strip()
    if not env_value or env_value.upper() == "ALL":
        env_value = "No Database Context"
    return {
        "Action ID": make_action_id("Account Health Checklist", check, f"{company}|{evidence}"),
        "Source": ACCOUNT_HEALTH_ACTION_SOURCE,
        "Severity": "Low" if severity.upper() == "INFO" else severity,
        "Category": "Daily DBA Checklist",
        "Entity Type": "DBA Checklist",
        "Entity": check,
        "Owner": owner,
        "Owner Email": row.get("OWNER_EMAIL", ""),
        "Oncall Primary": row.get("ONCALL_PRIMARY", ""),
        "Oncall Secondary": row.get("ONCALL_SECONDARY", ""),
        "Review Group": approval_group,
        "Escalation Target": escalation,
        "Owner Source": row.get("OWNER_SOURCE", ""),
        "Owner Evidence": row.get("OWNER_EVIDENCE", ""),
        "Finding": f"{check}: {evidence}",
        "Action": action,
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": "\n".join([
            "-- Daily DBA checklist action. Do not execute state-changing SQL from this row.",
            f"-- Route: {route}",
            f"-- Telemetry basis: {row.get('PROOF_REQUIRED', 'telemetry status')}",
            f"-- Queue readiness: {row.get('QUEUE_READINESS', 'Ready to Queue')}",
            f"-- Scope basis: {row.get('SCOPE_CONFIDENCE', 'Account-Level Control')}",
        ]),
        "Proof Query": verification_query,
        "Verification Query": verification_query,
        "Verification Status": "Pending",
        "Approver": approval_group if approval_required else owner,
        "Verification Status": "Requested" if approval_required else "Not Required",
        "Verification Note": (
            f"Checklist status: {row.get('STATUS', '')}. Route: {route}. "
            f"Escalation: {escalation}. Route basis: {row.get('OWNER_EVIDENCE', '')}. "
            f"Queue readiness: {row.get('QUEUE_READINESS', '')}; blockers: {row.get('QUEUE_BLOCKERS', '')}. "
            f"Scope: {row.get('SCOPE_CONFIDENCE', '')}."
        ),
        "Recovery Evidence": (
            f"Telemetry basis: {row.get('PROOF_REQUIRED', 'telemetry status')}. Detail: {evidence}. "
            f"Scope basis: {row.get('SCOPE_EVIDENCE', '')}."
        ),
        "Recovery Audit State": "Checklist Telemetry Pending",
        "Recovery SLA Target Hours": row.get("RECOVERY_SLA_TARGET_HOURS", _account_health_recovery_target_hours(severity)),
        "Company": company,
        "Environment": env_value,
    }

def _queue_account_health_checklist(session, checklist: pd.DataFrame, company: str, environment: str) -> None:
    checklist = _annotate_account_health_checklist_readiness(checklist, environment=environment)
    actionable = _account_health_actionable_checklist(checklist)
    if actionable.empty:
        st.info("No Daily DBA Checklist issues need queueing for the current snapshot.")
        return
    actions = [
        _account_health_checklist_action_payload(row, company=company, environment=environment)
        for _, row in actionable.head(25).iterrows()
    ]
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} Daily DBA Checklist issue(s) to the action queue.")
    except Exception as exc:
        st.error(f"Could not save Daily DBA Checklist issues: {format_snowflake_error(exc)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")

def _account_health_access_hygiene_action_payload(
    row: pd.Series | dict,
    company: str,
    days: int = 30,
) -> dict:
    """Build a review-only action queue item for account-level user/auth hygiene."""
    if "QUEUE_READINESS" not in row:
        annotated = _annotate_account_health_access_hygiene(pd.DataFrame([dict(row)]))
        if annotated is not None and not annotated.empty:
            row = annotated.iloc[0].to_dict()
    user_name = str(row.get("USER_NAME") or "Unknown User")
    severity = str(row.get("SEVERITY") or "Medium")
    findings = str(row.get("POSTURE_FINDINGS") or "Account access hygiene review required.")
    owner = str(row.get("OWNER") or "DBA / Security")
    approval_group = str(row.get("APPROVAL_GROUP") or "Security Approver")
    verification_query = _account_health_access_hygiene_verification_sql(row, days=days)
    return {
        "Action ID": make_action_id("Account Health Access Hygiene", user_name, f"{company}|{findings}"),
        "Source": ACCOUNT_HEALTH_ACCESS_HYGIENE_SOURCE,
        "Severity": severity,
        "Category": "Account Access Hygiene",
        "Entity Type": "User",
        "Entity": user_name,
        "Owner": owner,
        "Owner Email": row.get("OWNER_EMAIL", ""),
        "Oncall Primary": row.get("ONCALL_PRIMARY", ""),
        "Oncall Secondary": row.get("ONCALL_SECONDARY", ""),
        "Review Group": approval_group,
        "Escalation Target": row.get("ESCALATION_TARGET", "Security Lead"),
        "Owner Source": row.get("OWNER_SOURCE", ""),
        "Owner Evidence": row.get("OWNER_EVIDENCE", ""),
        "Finding": f"{user_name}: {findings}",
        "Action": str(row.get("NEXT_ACTION") or "Confirm IAM route, MFA posture, privileged grants, and recent login telemetry."),
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": "\n".join([
            "-- Account access hygiene action. Review only; do not grant, revoke, disable, or alter users from this queue row.",
            f"-- User: {user_name}",
            f"-- Findings: {findings}",
            f"-- Queue readiness: {row.get('QUEUE_READINESS', 'Ready to Queue')}",
            f"-- Blockers: {row.get('QUEUE_BLOCKERS', 'None')}",
            "-- Use IAM/Snowflake review workflow before any access change.",
        ]),
        "Proof Query": verification_query,
        "Verification Query": verification_query,
        "Verification Status": "Pending",
        "Approver": approval_group,
        "Verification Status": "Requested" if severity.upper() in {"CRITICAL", "HIGH", "MEDIUM"} else "Not Required",
        "Verification Note": (
            f"Account-level user/auth hygiene review. Scope: {row.get('SCOPE_CONFIDENCE', 'Account-Level Control')}. "
            f"Scope basis: {row.get('SCOPE_EVIDENCE', '')}. Queue blockers: {row.get('QUEUE_BLOCKERS', '')}."
        ),
        "Recovery Evidence": (
            f"Telemetry basis: {row.get('PROOF_REQUIRED', 'user, IAM ticket, failed login context, MFA/admin-role telemetry')}. "
            f"Current findings: {findings}."
        ),
        "Recovery Audit State": "Access Hygiene Telemetry Pending",
        "Recovery SLA Target Hours": row.get("RECOVERY_SLA_TARGET_HOURS", _account_health_recovery_target_hours(severity)),
        "Company": company,
        "Environment": "No Database Context",
    }

def _queue_account_health_access_hygiene(
    session,
    hygiene: pd.DataFrame,
    company: str,
    days: int = 30,
) -> None:
    hygiene = _annotate_account_health_access_hygiene(hygiene)
    if hygiene is None or hygiene.empty:
        st.info("No Account Access Hygiene rows are loaded for queueing.")
        return
    severity = hygiene.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
    actionable = hygiene[severity.isin({"CRITICAL", "HIGH", "MEDIUM"})].copy()
    if actionable.empty:
        st.info("No medium-or-higher Account Access Hygiene issues need queueing.")
        return
    actions = [
        _account_health_access_hygiene_action_payload(row, company=company, days=days)
        for _, row in actionable.head(50).iterrows()
    ]
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} Account Access Hygiene review(s) to the action queue.")
    except Exception as exc:
        st.error(f"Could not save Account Access Hygiene reviews: {format_snowflake_error(exc)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


__all__ = [
    '_account_health_checklist_action_payload',
    '_queue_account_health_checklist',
    '_account_health_access_hygiene_action_payload',
    '_queue_account_health_access_hygiene',
]
