"""Active-alert routing helpers for the DBA action queue.

This module owns the narrow path that converts active alert rows into action
queue records and marks alert rows as routed. Catalog, delivery, native alert,
and UI board logic live in focused sibling modules while ``utils.alerts`` stays
as the compatibility facade.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from config import ALERT_DB, ALERT_SCHEMA, ALERT_TABLE

from .compatibility import filter_existing_columns
from .monitor_context import resolve_owner_context
from .query import safe_identifier
from .sql_safe import sql_literal
from .alert_status import (
    ALERT_CLOSED_STATUSES,
    ALERT_SLA_HOURS,
    normalize_alert_severity as _normalize_alert_severity,
    normalize_alert_status as _normalize_alert_status,
)


def _alert_table_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"
    return f"{db}.{schema}.{table}"


def _row_value(row: Any, *names: str, default: str = "") -> str:
    for name in names:
        try:
            value = row.get(name)
        except AttributeError:
            value = None
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        text = str(value).strip()
        if text:
            return text
    return default


def _normalize_alert_frame_for_actions(df: pd.DataFrame, *, company: str = "ALFA") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.copy()
    defaults = {
        "COMPANY": company,
        "ENVIRONMENT": "No Database Context",
        "CATEGORY": "Alert",
        "SEVERITY": "Medium",
        "ENTITY_NAME": "Snowflake account",
        "MESSAGE": "",
        "SUGGESTED_ACTION": "Review the Alert Center issue and route it through the DBA action queue.",
        "OWNER": "DBA",
        "STATUS": "New",
        "PROOF_QUERY": "",
    }
    for column, default in defaults.items():
        if column not in view.columns:
            view[column] = default
        else:
            view[column] = view[column].fillna(default)
    view["SEVERITY"] = view["SEVERITY"].apply(_normalize_alert_severity)
    view["STATUS"] = view["STATUS"].apply(_normalize_alert_status)
    return view


def _alert_reliability_kind(row: pd.Series | dict) -> str:
    signal = " ".join([
        _row_value(row, "CATEGORY", default=""),
        _row_value(row, "ALERT_TYPE", default=""),
        _row_value(row, "SUGGESTED_ACTION", default=""),
        _row_value(row, "ALERT_RUNBOOK", default=""),
    ]).upper()
    if "TASK" in signal:
        return "task"
    if "STORED PROCEDURE" in signal or "PROCEDURE" in signal or "PROC_" in signal:
        return "procedure"
    return ""


def _object_leaf_name(value: object) -> str:
    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    parts = [part.strip().strip('"') for part in text.split(".") if part.strip()]
    return parts[-1] if parts else text


def _safe_alert_row_query(row: pd.Series | dict) -> str:
    alert_id = _row_value(row, "ALERT_ID", default="")
    columns = "ALERT_ID, ALERT_TS, STATUS, SEVERITY, CATEGORY, ALERT_TYPE, ENTITY_NAME, MESSAGE"
    if str(alert_id).strip().isdigit():
        return f"""
SELECT {columns}
FROM {_alert_table_fqn(quoted=True)}
WHERE ALERT_ID = {int(alert_id)}
LIMIT 50
""".strip()
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake account")
    return f"""
SELECT {columns}
FROM {_alert_table_fqn(quoted=True)}
WHERE ENTITY_NAME = {sql_literal(entity, 500)}
ORDER BY ALERT_TS DESC
LIMIT 50
""".strip()


def _safe_alert_proof_query(row: pd.Series | dict) -> str:
    from .action_queue import verification_query_safety_issues

    proof = _row_value(row, "PROOF_QUERY", default="")
    if proof and not verification_query_safety_issues(proof):
        return proof
    return _safe_alert_row_query(row)


def _task_recovery_verification_query(row: pd.Series | dict) -> str:
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="")
    task_name = _object_leaf_name(entity) or entity or "UNKNOWN_TASK"
    database = _row_value(row, "DATABASE_NAME", default="")
    schema = _row_value(row, "SCHEMA_NAME", default="")
    filters = [f"UPPER(NAME) = UPPER({sql_literal(task_name, 500)})"]
    if database:
        filters.append(f"UPPER(DATABASE_NAME) = UPPER({sql_literal(database, 500)})")
    if schema:
        filters.append(f"UPPER(SCHEMA_NAME) = UPPER({sql_literal(schema, 500)})")
    where_clause = " AND ".join(filters)
    return f"""
SELECT DATABASE_NAME, SCHEMA_NAME, NAME, STATE, SCHEDULED_TIME, COMPLETED_TIME, QUERY_ID, ERROR_MESSAGE
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE {where_clause}
ORDER BY SCHEDULED_TIME DESC
LIMIT 50
""".strip()


def _procedure_recovery_verification_query(row: pd.Series | dict) -> str:
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="")
    proc_name = _object_leaf_name(entity) or entity or "UNKNOWN_PROCEDURE"
    database = _row_value(row, "DATABASE_NAME", default="")
    schema = _row_value(row, "SCHEMA_NAME", default="")
    filters = ["QUERY_TYPE = 'CALL'"]
    if database:
        filters.append(f"UPPER(DATABASE_NAME) = UPPER({sql_literal(database, 500)})")
    if schema:
        filters.append(f"UPPER(SCHEMA_NAME) = UPPER({sql_literal(schema, 500)})")
    if proc_name:
        filters.append(f"QUERY_TEXT ILIKE {sql_literal('%' + proc_name + '%', 500)}")
    where_clause = " AND ".join(filters)
    return f"""
SELECT QUERY_ID, START_TIME, USER_NAME, ROLE_NAME, WAREHOUSE_NAME, DATABASE_NAME, SCHEMA_NAME,
       EXECUTION_STATUS, TOTAL_ELAPSED_TIME, ERROR_CODE, ERROR_MESSAGE
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE {where_clause}
ORDER BY START_TIME DESC
LIMIT 50
""".strip()


def _alert_recovery_verification_query(row: pd.Series | dict, reliability_kind: str) -> str:
    from .action_queue import verification_query_safety_issues

    proof = _row_value(row, "PROOF_QUERY", default="")
    if proof and not verification_query_safety_issues(proof):
        return proof
    if reliability_kind == "task":
        return _task_recovery_verification_query(row)
    if reliability_kind == "procedure":
        return _procedure_recovery_verification_query(row)
    return _safe_alert_row_query(row)


def _alert_numeric_value(row: pd.Series | dict, *columns: str) -> float | None:
    for column in columns:
        value = _row_value(row, column, default="")
        try:
            if value not in ("", None):
                return float(value)
        except Exception:
            continue
    return None


def _alert_recovery_metrics(row: pd.Series | dict, reliability_kind: str) -> dict[str, float]:
    text = " ".join([
        _row_value(row, "ALERT_TYPE", default=""),
        _row_value(row, "MESSAGE", "DETAIL", default=""),
    ])
    upper_text = text.upper()
    metrics: dict[str, float] = {}
    if "RUNTIME" in upper_text or "DURATION" in upper_text:
        current_match = re.search(r"(?:DURATION|CALL DURATION)\s+([0-9]+(?:\.[0-9]+)?)\s*S", text, flags=re.IGNORECASE)
        baseline_match = re.search(r"BASELINE\s+([0-9]+(?:\.[0-9]+)?)\s*S", text, flags=re.IGNORECASE)
        if current_match:
            metrics["Baseline Value"] = float(baseline_match.group(1)) if baseline_match else 0.0
            metrics["Current Value"] = float(current_match.group(1))
            metrics["Measured Delta"] = metrics["Current Value"] - metrics["Baseline Value"]
            return metrics

    failure_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s+FAILED", text, flags=re.IGNORECASE)
    if failure_match or reliability_kind in {"task", "procedure"}:
        current = float(failure_match.group(1)) if failure_match else 1.0
        metrics["Baseline Value"] = 0.0
        metrics["Current Value"] = current
        metrics["Measured Delta"] = current
    return metrics


def _alert_recovery_sla_state(row: pd.Series | dict) -> str:
    status = _normalize_alert_status(_row_value(row, "STATUS", default="New")).upper()
    if status in ALERT_CLOSED_STATUSES:
        return ""
    sla_state = str(_row_value(row, "SLA_STATE", default="")).strip().upper()
    if sla_state == "OVERDUE":
        return "Recovery SLA Breach"
    return "Open Failure"


def _alert_recovery_sql_guidance(row: pd.Series | dict, reliability_kind: str) -> str:
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake object")
    owner = _row_value(row, "OWNER", "ESCALATION_TARGET", default="DBA / owner")
    noun = "task" if reliability_kind == "task" else "stored procedure"
    return "\n".join([
        f"-- reviewed {noun} recovery for {entity}",
        "-- Do not perform retry from Alert Center.",
        f"-- Assign DBA route/reviewer: {owner}",
        "-- Required order: confirm root cause, document ticket, complete review, then recover from Workload Operations.",
        "-- After recovery, run the read-only status query attached to this action and record the result in closure status.",
    ])


def alert_history_to_actions(df_alerts: pd.DataFrame, company: str = "ALFA") -> list[dict]:
    if df_alerts is None or df_alerts.empty:
        return []
    from .action_queue import make_action_id

    actions = []
    alerts = _normalize_alert_frame_for_actions(df_alerts, company=company)
    for _, row in alerts.head(500).iterrows():
        alert_id = _row_value(row, "ALERT_ID", "ALERT_TS")
        category = _row_value(row, "CATEGORY", "ALERT_TYPE", default="Alert")
        alert_type = _row_value(row, "ALERT_TYPE", "CATEGORY", default=category)
        entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake account")
        message = _row_value(row, "MESSAGE", "DETAIL")
        reliability_kind = _alert_reliability_kind(row)
        is_recovery = reliability_kind in {"task", "procedure"}
        reviewed_recovery = is_recovery
        action_category = "Task & Procedure Reliability" if is_recovery else category
        entity_type = {
            "task": "Task",
            "procedure": "Stored Procedure",
        }.get(reliability_kind, "Alert Entity")
        proof_query = _safe_alert_proof_query(row)
        if is_recovery:
            verification_query = _alert_recovery_verification_query(row, reliability_kind)
        else:
            verification_query = proof_query
        owner = _row_value(row, "OWNER", default="DBA")
        owner_context = resolve_owner_context(
            row,
            entity=entity,
            entity_type=entity_type,
            owner=owner,
            category=action_category,
            alert_type=alert_type,
        )
        owner = owner_context.get("OWNER") or owner
        escalation_target = _row_value(row, "ESCALATION_TARGET", default="") or owner_context.get("ESCALATION_TARGET", "")
        approval_group = owner_context.get("APPROVAL_GROUP") or escalation_target or owner
        sla_target_hours = _alert_numeric_value(row, "SLA_TARGET_HOURS")
        if sla_target_hours is None:
            sla_target_hours = float(ALERT_SLA_HOURS.get(_normalize_alert_severity(_row_value(row, "SEVERITY", default="Medium")), 24))
        alert_age_hours = _alert_numeric_value(row, "ALERT_AGE_HOURS")
        suggested_action = _row_value(row, "SUGGESTED_ACTION", default="Review the Alert Center issue and route it through the DBA action queue.")
        if is_recovery:
            suggested_action = (
                f"{suggested_action} Track recovery through the action queue: assign route/ticket, confirm root cause, "
                "complete review before recovery, and confirm the next run."
            )
            sql_fix = _alert_recovery_sql_guidance(row, reliability_kind)
            recovery_evidence = (
                "Required closure status: root cause, recovery timestamp, and a successful next-run "
                f"status check for {entity}. Alert detail: {message}"
            )
        else:
            sql_fix = "-- Review alert telemetry before applying a fix."
            recovery_evidence = ""
        action = {
            "Action ID": make_action_id(action_category if reviewed_recovery else "Alert", entity, f"{alert_type}|{message}|{alert_id}"),
            "Source": "Alert Center",
            "Severity": _normalize_alert_severity(_row_value(row, "SEVERITY", default="Medium")),
            "Category": action_category,
            "Entity Type": entity_type,
            "Entity": entity,
            "Owner": owner,
            "Finding": f"{alert_type}: {message}",
            "Action": suggested_action,
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": sql_fix,
            "Proof Query": proof_query,
            "Verification Status": "Pending",
            "Verification Query": verification_query,
            "Company": _row_value(row, "COMPANY", default=company),
            "Environment": _row_value(row, "ENVIRONMENT", default="No Database Context"),
            "Owner Email": owner_context.get("OWNER_EMAIL", ""),
            "Oncall Primary": owner_context.get("ONCALL_PRIMARY", ""),
            "Oncall Secondary": owner_context.get("ONCALL_SECONDARY", ""),
            "Review Group": approval_group,
            "Escalation Target": escalation_target,
            "Owner Source": owner_context.get("OWNER_SOURCE", ""),
            "Owner Evidence": owner_context.get("OWNER_EVIDENCE", ""),
        }
        if reviewed_recovery:
            action.update({
                "Verification Status": "Requested",
                "Verification Note": (
                    "Alert routed from Alert Center; retry or recovery requires root-cause "
                    "status and post-recovery telemetry."
                ),
                "Recovery SLA State": _alert_recovery_sla_state(row),
                "Recovery SLA Target Hours": float(sla_target_hours),
                "Recovery Evidence": recovery_evidence,
                "Recovery Audit State": "Audit Required",
            })
            if alert_age_hours is not None:
                action["Recovery SLA Hours"] = float(alert_age_hours)
            action.update(_alert_recovery_metrics(row, reliability_kind))
        actions.append(action)
    return actions


def mark_alerts_routed(
    session,
    alert_ids: list[int | str],
    *,
    action_count: int = 0,
    actor: str = "OVERWATCH",
) -> None:
    clean_ids = [int(value) for value in alert_ids if str(value).strip().isdigit()]
    if not clean_ids:
        return
    columns = set(filter_existing_columns(
        session,
        _alert_table_fqn(),
        ["STATUS", "ROUTED_TO_ACTION_QUEUE_AT", "ROUTED_ACTION_COUNT", "LAST_STATUS_BY", "LAST_STATUS_AT"],
    ))
    set_parts = []
    if "STATUS" in columns:
        set_parts.append("STATUS = CASE WHEN STATUS IS NULL OR STATUS = 'New' THEN 'In Progress' ELSE STATUS END")
    if "ROUTED_TO_ACTION_QUEUE_AT" in columns:
        set_parts.append("ROUTED_TO_ACTION_QUEUE_AT = CURRENT_TIMESTAMP()")
    if "ROUTED_ACTION_COUNT" in columns:
        set_parts.append(f"ROUTED_ACTION_COUNT = COALESCE(ROUTED_ACTION_COUNT, 0) + {int(action_count)}")
    if "LAST_STATUS_BY" in columns:
        set_parts.append(f"LAST_STATUS_BY = {sql_literal(actor, 200)}")
    if "LAST_STATUS_AT" in columns:
        set_parts.append("LAST_STATUS_AT = CURRENT_TIMESTAMP()")
    if not set_parts:
        return
    # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
    session.sql(f"""
        UPDATE {_alert_table_fqn(quoted=True)}
        SET {", ".join(set_parts)}
        WHERE ALERT_ID IN ({", ".join(str(value) for value in clean_ids)})
    """).collect()
