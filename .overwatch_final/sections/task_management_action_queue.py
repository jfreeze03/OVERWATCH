# sections/task_management_action_queue.py - Task Management action queue writers
import pandas as pd
import streamlit as st

from sections.task_management_models import (
    _task_action_for,
    _task_environment,
    _task_metric,
    _task_owner,
    _task_review_status,
)
from sections.task_management_sql import (
    _task_reliability_generated_sql,
    _task_reliability_proof_sql,
    _task_reliability_verification_sql,
)
from utils import (
    format_snowflake_error,
    get_active_company,
    get_active_environment,
    make_action_id,
    resolve_owner_context,
    safe_identifier,
    safe_float,
    safe_int,
    upsert_actions,
)

def _queue_task_findings(session, df: pd.DataFrame, source: str) -> None:
    if df is None or df.empty:
        st.info("No task findings to queue.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    for _, row in df.head(200).iterrows():
        active_env = get_active_environment()
        action_env = str(row.get("ENVIRONMENT") or (active_env if active_env != "ALL" else "") or "")
        name = str(row.get("NAME") or row.get("PIPELINE_NAME") or "Unknown task")
        err = str(row.get("ERROR_MESSAGE") or "")[:1000]
        state = str(row.get("STATE") or row.get("STATUS") or "FAILED")
        finding = f"{name} finished with {state}"
        if err:
            finding += f": {err[:250]}"
        owner_context = resolve_owner_context(
            row,
            entity=name,
            entity_type="Task",
            owner="Data Engineering",
            category="Task & Procedure Reliability",
            alert_type="Task Failure",
        )
        actions.append({
            "Action ID": make_action_id("Task Reliability", name, finding),
            "Source": source,
            "Severity": "High",
            "Category": "Reliability",
            "Entity Type": "Task/Pipeline",
            "Entity": name,
            "Owner": owner_context.get("OWNER", "Data Engineering"),
            "Email Target": owner_context.get("EMAIL_TARGET", ""),
            "Reviewed By": owner_context.get("REVIEWED_BY", ""),
            "Reviewed By": owner_context.get("REVIEWED_BY", ""),
            "Review Status": owner_context.get("REVIEW_STATUS", ""),
            "Workflow Route": owner_context.get("WORKFLOW_ROUTE", ""),
            "Allocation Source": owner_context.get("ALLOCATION_SOURCE", ""),
            "Allocation Basis": owner_context.get("ALLOCATION_BASIS", ""),
            "Approver": owner_context.get("REVIEW_STATUS", ""),
            "Finding": finding,
            "Action": "Review error message, fix upstream dependency or SQL failure, then retry the task/pipeline.",
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": f"-- Review task or pipeline: {name}\n-- EXECUTE TASK <database>.<schema>.{safe_identifier(name)};",
            "Proof Query": "TASK_HISTORY or ETL audit failure row.",
            "Company": company,
            "Environment": action_env,
            "Verification Status": "Pending",
            "Verification Query": "TASK_HISTORY or ETL audit failure row.",
        })
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} task reliability findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")

def _queue_failure_findings(session, failures: pd.DataFrame) -> int:
    if failures is None or failures.empty:
        return 0
    company = get_active_company()
    actions = [
        _build_task_reliability_action(row, company, "Task Management - Failure Console")
        for _, row in failures.head(100).iterrows()
    ]
    return upsert_actions(session, actions)

def _build_task_reliability_action(row: pd.Series, company: str, source: str) -> dict:
    signal = str(row.get("SIGNAL") or row.get("FAILURE_CATEGORY") or row.get("BREACH_REASON") or "Task Reliability")
    task = str(row.get("TASK_FQN") or row.get("TASK_NAME") or row.get("NAME") or "Unknown task")
    category = str(row.get("FAILURE_CATEGORY") or signal)
    detail = str(row.get("DETAIL") or row.get("ERROR_SIGNATURE") or row.get("ERROR_MESSAGE") or "")[:700]
    action_text, _ = _task_action_for(signal)
    if row.get("RECOMMENDED_ACTION"):
        action_text = str(row.get("RECOMMENDED_ACTION"))
    if "verify" not in action_text.lower() and "confirm" not in action_text.lower():
        action_text += " Confirm the next successful run and record TASK_HISTORY telemetry before closing."
    severity = str(row.get("SEVERITY") or ("High" if category != "Unclassified Failure" else "Medium"))
    incident_priority = str(row.get("INCIDENT_PRIORITY") or "").strip()
    recovery_readiness = str(row.get("RECOVERY_READINESS") or "").strip()
    review_state = str(row.get("REVIEW_STATE") or "").strip()
    recovery_state = str(row.get("RECOVERY_STATE") or "").strip()
    recovery_evidence = str(row.get("VERIFY_AFTER_FIX") or "").strip()
    owner_context = resolve_owner_context(
        row,
        entity=task,
        entity_type="Task",
        owner=_task_owner(row),
        category="Task & Procedure Reliability",
        alert_type=signal,
    )
    if recovery_readiness and recovery_readiness.lower() not in action_text.lower():
        action_text += f" Recovery status: {recovery_readiness}."
    if review_state and review_state.lower() not in action_text.lower():
        action_text += f" Status: {review_state}."
    finding_prefix = f"{incident_priority}: " if incident_priority else ""
    finding = f"{finding_prefix}{signal}: {task}. {detail}".strip()
    if recovery_state:
        finding = f"{finding} Recovery SLA state: {recovery_state}."
    verification_query = _task_reliability_verification_sql(row)[:8000]
    proof_query = _task_reliability_proof_sql(row)[:8000]
    baseline_value = _task_metric(row, "AVG_DURATION_SEC", "AVG_EXECUTION_SECONDS", "BASELINE_SECONDS")
    current_value = _task_metric(row, "DURATION_SEC", "ELAPSED_SEC", "LATEST_DURATION_SEC", "EXECUTION_SECONDS")
    measured_delta = (
        round(current_value - baseline_value, 4)
        if current_value is not None and baseline_value is not None
        else None
    )
    return {
        "Action ID": make_action_id("Task Reliability", task, finding),
        "Source": source,
        "Severity": severity,
        "Category": "Task & Procedure Reliability",
        "Entity Type": "Task/Procedure",
        "Entity": task,
        "Owner": owner_context.get("OWNER") or _task_owner(row),
        "Email Target": owner_context.get("EMAIL_TARGET", ""),
        "Reviewed By": owner_context.get("REVIEWED_BY", ""),
        "Reviewed By": owner_context.get("REVIEWED_BY", ""),
        "Review Status": owner_context.get("REVIEW_STATUS", ""),
        "Workflow Route": owner_context.get("WORKFLOW_ROUTE", ""),
        "Allocation Source": owner_context.get("ALLOCATION_SOURCE", ""),
        "Allocation Basis": owner_context.get("ALLOCATION_BASIS", ""),
        "Approver": owner_context.get("REVIEW_STATUS") or row.get("APPROVER") or owner_context.get("WORKFLOW_ROUTE", ""),
        "Finding": finding,
        "Action": action_text,
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": _task_reliability_generated_sql(row)[:8000],
        "Proof Query": proof_query,
        "Company": company,
        "Environment": _task_environment(row),
        "Verification Status": "Pending",
        "Verification Query": verification_query,
        "Baseline Value": baseline_value,
        "Current Value": current_value,
        "Measured Delta": measured_delta,
        "Verification Status": _task_review_status(row),
        "Verification Note": review_state,
        "Recovery SLA State": recovery_state,
        "Recovery SLA Hours": _task_metric(row, "RECOVERY_HOURS", "RECOVERY_SLA_HOURS"),
        "Recovery SLA Target Hours": _task_metric(row, "RECOVERY_SLA_TARGET_HOURS"),
        "Recovery Evidence": recovery_evidence,
        "Recovery Audit State": "Audit Required" if recovery_state else "",
    }

def _queue_task_ops_findings(session, exceptions: pd.DataFrame) -> int:
    if exceptions is None or exceptions.empty:
        return 0
    company = get_active_company()
    actions = [
        _build_task_reliability_action(row, company, "Task Management - Operations Brief")
        for _, row in exceptions.head(100).iterrows()
    ]
    return upsert_actions(session, actions)

__all__ = ['_queue_task_findings', '_queue_failure_findings', '_build_task_reliability_action', '_queue_task_ops_findings']
