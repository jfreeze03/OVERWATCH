# sections/change_drift_action_queue.py - Change Drift action/evidence writers
from __future__ import annotations

from datetime import datetime

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.change_drift_common import get_active_company, get_active_environment
from sections.change_drift_models import (
    _change_action_for,
    _change_blast_radius_sql,
    _change_environment,
    _change_execution_audit_state,
    _change_iac_state,
    _change_owner_context,
    _change_ticket_id,
    _change_verification_sql,
    _enrich_change_control_evidence,
    _owner_approval_for,
)
from sections.change_drift_sql import (
    build_change_control_evidence_ddl,
    build_change_control_evidence_migration_sql,
    change_control_evidence_fqn,
)
from utils.primitives import safe_int

pd = lazy_pandas()
format_snowflake_error = _lazy_util("format_snowflake_error")
make_action_id = _lazy_util("make_action_id")
sql_literal = _lazy_util("sql_literal")
upsert_actions = _lazy_util("upsert_actions")

def _change_action_payload(row: pd.Series | dict, company: str, environment: str = "") -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "Change")
    entity = str(row.get("ENTITY") or row.get("QUERY_ID") or "Snowflake account")
    user_name = str(row.get("USER_NAME") or "unknown")
    severity = str(row.get("SEVERITY") or "Medium")
    query_id = str(row.get("QUERY_ID") or "").strip()
    entity_type, action, generated_sql = _change_action_for(finding_type)
    approval_status, approver, approval_note = _owner_approval_for(finding_type)
    owner_context = _change_owner_context(row)
    ticket_id = _change_ticket_id(row)
    ticket_state = "ticket detected" if ticket_id else "missing ticket status"
    iac_state = _change_iac_state(row)
    audit_state = _change_execution_audit_state(row)
    env_value = str(row.get("ENVIRONMENT") or _change_environment(row, environment) or environment or "ALL")
    verification_query = _change_verification_sql(query_id)
    blast_radius_query = _change_blast_radius_sql(entity)
    finding = f"{finding_type} by {user_name} on {entity}"
    verification_status = approval_status
    generated_review = "\n".join([
        "-- Review-only change-monitoring record. Do not execute state-changing SQL from this queue row.",
        generated_sql,
        f"-- Required telemetry: query_id={query_id or 'missing'}, reviewer, change ticket, and dependency/blast-radius note.",
        f"-- Ticket status: {ticket_id or 'missing'} ({ticket_state}).",
        f"-- review/rollback state: {iac_state}.",
        f"-- Execution audit state: {audit_state}.",
        "-- Read-only blast-radius check to run before action:",
        blast_radius_query,
    ])
    return {
        "Action ID": make_action_id("Change Drift", entity, f"{finding}|{query_id}"),
        "Source": "Change & Drift - Brief",
        "Severity": severity,
        "Category": "Object Change Monitoring",
        "Entity Type": entity_type,
        "Entity": entity,
        "Owner": owner_context["owner"],
        "Owner Email": owner_context.get("owner_email", ""),
        "Oncall Primary": owner_context.get("oncall_primary", ""),
        "Oncall Secondary": owner_context.get("oncall_secondary", ""),
        "Review Group": owner_context.get("approval_group", approver),
        "Escalation Target": owner_context.get("escalation", ""),
        "Owner Source": owner_context.get("source", ""),
        "Owner Evidence": owner_context.get("owner_evidence", ""),
        "Finding": finding,
        "Action": action,
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": generated_review,
        "Proof Query": verification_query,
        "Verification Query": verification_query,
        "Approver": approver,
        # Preserve the historical effective value: approval/review route status.
        "Verification Status": verification_status,
        "Verification Note": (
            f"{approval_note} Ticket={ticket_id or 'missing'}; "
            f"review_rollback={iac_state}; escalation={owner_context['escalation']}."
        ),
        "Recovery Evidence": (
            f"Run blast-radius check before closure:\n{blast_radius_query}\n\n"
            f"Ticket status: {ticket_id or 'missing'}\n"
            f"review/rollback status: {iac_state}\n"
            f"Execution audit: {audit_state}"
        ),
        "Recovery Audit State": audit_state,
        "Recovery SLA Target Hours": 24 if severity.upper() in {"CRITICAL", "HIGH"} else 72,
        "Company": company,
        "Environment": env_value,
        "Ticket ID": ticket_id,
    }

def _queue_change_exceptions(session, exceptions: pd.DataFrame) -> None:
    if exceptions is None or exceptions.empty:
        st.info("No change/drift exceptions to queue.")
        return
    company = get_active_company()
    environment = get_active_environment()
    actions = []
    for _, row in exceptions.head(100).iterrows():
        actions.append(_change_action_payload(row, company=company, environment=environment))
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} change/drift exceptions to the action queue with review and telemetry fields.")
    except Exception as e:
        st.error(f"Could not save change/drift exceptions: {format_snowflake_error(e)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")

def _change_control_evidence_insert_sql(
    readiness: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
    snapshot_id: str = "",
) -> str:
    if readiness is None or readiness.empty:
        raise ValueError("Object-change telemetry snapshot has no rows to save.")
    view = _enrich_change_control_evidence(readiness)
    fqn = change_control_evidence_fqn()
    env_value = str(environment or "").strip() or "ALL"
    snap = snapshot_id or make_action_id(
        "Object Change Telemetry Snapshot",
        company,
        f"{env_value}|{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )
    selects = []
    for _, row in view.head(200).iterrows():
        row_environment = str(row.get("ENVIRONMENT") or _change_environment(row, env_value) or env_value)
        selects.append(
            "SELECT "
            f"{sql_literal(snap, 64)} AS SNAPSHOT_ID, "
            "CURRENT_TIMESTAMP() AS SNAPSHOT_TS, "
            f"{sql_literal(company, 100)} AS COMPANY, "
            f"{sql_literal(row_environment, 100)} AS ENVIRONMENT, "
            f"{sql_literal(row.get('FINDING_TYPE', ''), 120)} AS FINDING_TYPE, "
            f"{sql_literal(row.get('SEVERITY', ''), 40)} AS SEVERITY, "
            f"{sql_literal(row.get('ENTITY', ''), 500)} AS ENTITY, "
            f"{sql_literal(row.get('USER_NAME', ''), 300)} AS USER_NAME, "
            f"{sql_literal(row.get('ROLE_NAME', ''), 300)} AS ROLE_NAME, "
            f"{sql_literal(row.get('QUERY_ID', ''), 200)} AS QUERY_ID, "
            f"{sql_literal(row.get('QUERY_TAG', ''), 1000)} AS QUERY_TAG, "
            f"{sql_literal(row.get('LAST_SEEN', ''), 100)} AS LAST_SEEN, "
            f"{sql_literal(row.get('CHANGE_CONTROL_STATE', ''), 120)} AS CHANGE_CONTROL_STATE, "
            f"{sql_literal(row.get('CONTROL_GAP', ''), 1000)} AS CONTROL_GAP, "
            f"{sql_literal(row.get('CHANGE_TICKET_ID', ''), 200)} AS CHANGE_TICKET_ID, "
            f"{sql_literal(row.get('CHANGE_TICKET_STATE', ''), 120)} AS CHANGE_TICKET_STATE, "
            f"{sql_literal(row.get('IAC_RECONCILIATION_STATE', ''), 160)} AS IAC_RECONCILIATION_STATE, "
            f"{sql_literal(row.get('EXECUTION_AUDIT_STATE', ''), 160)} AS EXECUTION_AUDIT_STATE, "
            f"{sql_literal(row.get('OWNER', ''), 200)} AS OWNER, "
            f"{sql_literal(row.get('ESCALATION_TARGET', ''), 200)} AS ESCALATION_TARGET, "
            f"{sql_literal(row.get('OWNER_SOURCE', ''), 200)} AS OWNER_SOURCE, "
            f"{sql_literal(row.get('APPROVER', ''), 200)} AS APPROVER, "
            f"{sql_literal(row.get('OWNER_APPROVAL_STATUS', ''), 40)} AS OWNER_APPROVAL_STATUS, "
            f"{sql_literal(row.get('APPROVAL_REQUIRED', ''), 20)} AS APPROVAL_REQUIRED, "
            f"{sql_literal(row.get('TICKET_REQUIRED', ''), 20)} AS TICKET_REQUIRED, "
            f"{sql_literal(row.get('BLAST_RADIUS_REQUIRED', ''), 20)} AS BLAST_RADIUS_REQUIRED, "
            f"{sql_literal(row.get('APPROVAL_ROUTE_READY', ''), 20)} AS APPROVAL_ROUTE_READY, "
            f"{sql_literal(row.get('CHANGE_EVIDENCE_READINESS', ''), 80)} AS CHANGE_EVIDENCE_READINESS, "
            f"{sql_literal(row.get('EVIDENCE_BLOCKERS', ''), 2000)} AS EVIDENCE_BLOCKERS, "
            f"{safe_int(row.get('REVIEW_SLA_HOURS', 168))}::NUMBER AS REVIEW_SLA_HOURS, "
            f"{sql_literal(row.get('NEXT_CONTROL_ACTION', ''), 4000)} AS NEXT_CONTROL_ACTION, "
            f"{sql_literal(row.get('PROOF_REQUIRED', ''), 2000)} AS PROOF_REQUIRED, "
            f"{sql_literal(row.get('VERIFICATION_QUERY', ''), 8000)} AS VERIFICATION_QUERY, "
            f"{sql_literal(row.get('BLAST_RADIUS_QUERY', ''), 8000)} AS BLAST_RADIUS_QUERY, "
            f"{sql_literal(source, 500)} AS SOURCE"
        )
    return f"""
INSERT INTO {fqn} (
    SNAPSHOT_ID, SNAPSHOT_TS, COMPANY, ENVIRONMENT, FINDING_TYPE, SEVERITY,
    ENTITY, USER_NAME, ROLE_NAME, QUERY_ID, QUERY_TAG, LAST_SEEN,
    CHANGE_CONTROL_STATE, CONTROL_GAP, CHANGE_TICKET_ID, CHANGE_TICKET_STATE,
    IAC_RECONCILIATION_STATE, EXECUTION_AUDIT_STATE, OWNER, ESCALATION_TARGET,
    OWNER_SOURCE, APPROVER, OWNER_APPROVAL_STATUS, APPROVAL_REQUIRED,
    TICKET_REQUIRED, BLAST_RADIUS_REQUIRED, APPROVAL_ROUTE_READY,
    CHANGE_EVIDENCE_READINESS, EVIDENCE_BLOCKERS, REVIEW_SLA_HOURS,
    NEXT_CONTROL_ACTION, PROOF_REQUIRED, VERIFICATION_QUERY, BLAST_RADIUS_QUERY, SOURCE
)
{" UNION ALL ".join(selects)}""".strip()

def _save_change_control_evidence_snapshot(
    session,
    readiness: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
) -> None:
    try:
        # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
        session.sql(build_change_control_evidence_ddl()).collect()
        for migration_sql in build_change_control_evidence_migration_sql():
            # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
            session.sql(migration_sql).collect()
        # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
        session.sql(_change_control_evidence_insert_sql(
            readiness,
            company=company,
            environment=environment,
            source=source,
        )).collect()
        st.success("Saved the object-change telemetry snapshot for audit and trend tracking.")
    except Exception as exc:
        st.error(f"Could not save object-change telemetry snapshot: {format_snowflake_error(exc)}")
        st.info("Object-change telemetry history is not available in this environment yet. Ask the DBA route to enable it, then retry this save.")

__all__ = ['_change_action_payload', '_queue_change_exceptions', '_change_control_evidence_insert_sql', '_save_change_control_evidence_snapshot']
