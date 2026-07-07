"""Loaded alert board and section signal helpers.

This module owns dataframe shaping for visible alert boards. Alert lifecycle
SQL, delivery, catalog, native-alert setup, and history loading live in focused
sibling modules.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .alert_triage import (
    ALERT_CLOSED_STATUSES,
    ALERT_SLA_HOURS,
    _row_value,
    _status_key,
    alert_severity_rank,
    alert_sla_hours,
    normalize_alert_frame,
    normalize_alert_severity,
    normalize_alert_status,
)


def _alert_col(df: pd.DataFrame, *names: str, default: Any = "") -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=object)
    lookup = {str(column).upper(): column for column in df.columns}
    for name in names:
        column = lookup.get(str(name).upper())
        if column is not None:
            return df[column]
    return pd.Series([default] * len(df), index=df.index)


def build_alert_command_center_summary(
    alerts: pd.DataFrame,
    *,
    run_history: pd.DataFrame | None = None,
    now: Any | None = None,
) -> dict[str, object]:
    """Summarize loaded alert evidence into DBA monitoring metrics."""
    current_time = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
    if alerts is None or alerts.empty:
        return {
            "metrics": pd.DataFrame([
                {"METRIC": "Open critical", "VALUE": 0, "STATE": "Clear", "DETAIL": "No loaded alert rows."},
                {"METRIC": "Warning alerts", "VALUE": 0, "STATE": "Clear", "DETAIL": "No loaded alert rows."},
                {"METRIC": "Info alerts", "VALUE": 0, "STATE": "Clear", "DETAIL": "No loaded alert rows."},
                {"METRIC": "Resolved alerts", "VALUE": 0, "STATE": "Unknown", "DETAIL": "No loaded alert rows."},
            ]),
            "category_board": pd.DataFrame(columns=["CATEGORY", "OPEN", "CRITICAL_HIGH", "RESOLVED", "SEVERITY_SCORE", "BUSINESS_IMPACT", "RECOMMENDED_OWNER", "RECOMMENDED_ACTION"]),
            "trend": pd.DataFrame(columns=["ALERT_DAY", "SEVERITY", "ALERTS"]),
            "recurring": pd.DataFrame(columns=["CATEGORY", "SIGNAL", "ENTITY", "ALERTS", "SEVERITY", "OWNER", "RECOMMENDED_ACTION"]),
            "freshness": pd.DataFrame([{
                "SOURCE": "Loaded alert data",
                "LAST_CHECKED": "Details available when needed",
                "FRESHNESS_STATE": "Load required",
                "NOTE": "Use explicit load to avoid hidden ACCOUNT_USAGE scans.",
            }]),
            "last_checked": "Details available when needed",
            "severity_score": 0,
            "mttd_minutes": None,
            "mttr_hours": None,
        }

    df = normalize_alert_frame(alerts)
    severity = _alert_col(df, "SEVERITY", default="Medium").apply(normalize_alert_severity)
    status = _alert_col(df, "STATUS", default="New").apply(normalize_alert_status)
    category = _alert_col(df, "CATEGORY", "DOMAIN", default="Alert").fillna("Alert").astype(str)
    signal = _alert_col(df, "ALERT_TYPE", "SIGNAL", "MESSAGE", default="Alert").fillna("Alert").astype(str)
    entity = _alert_col(df, "ENTITY_NAME", "ENTITY", default="Snowflake account").fillna("Snowflake account").astype(str)
    owner = _alert_col(df, "OWNER", "ROUTED_OWNER", "WORKFLOW_ROUTE", default="DBA").fillna("DBA").astype(str)
    action = _alert_col(df, "SUGGESTED_ACTION", "NEXT_ACTION", "RECOMMENDED_ACTION", default="Review alert telemetry and assign route.").fillna("Review alert telemetry and assign route.").astype(str)
    event_ts = pd.to_datetime(_alert_col(df, "ALERT_TS", "EVENT_TS", "FIRST_SEEN_AT", default=current_time), errors="coerce").fillna(current_time)
    first_seen = pd.to_datetime(_alert_col(df, "FIRST_SEEN_AT", "ALERT_TS", "EVENT_TS", default=current_time), errors="coerce").fillna(event_ts)
    detected = pd.to_datetime(_alert_col(df, "DETECTED_AT", "ALERT_TS", "EVENT_TS", default=current_time), errors="coerce").fillna(event_ts)
    resolved = pd.to_datetime(_alert_col(df, "RESOLVED_AT", "LAST_STATUS_AT", default=pd.NaT), errors="coerce")

    open_mask = ~status.apply(lambda value: _status_key(value) in ALERT_CLOSED_STATUSES)
    critical_open = open_mask & severity.eq("Critical")
    warning_open = open_mask & severity.isin(["High", "Medium"])
    info_open = open_mask & severity.eq("Low")
    resolved_mask = ~open_mask
    score_map = {"Critical": 100, "High": 70, "Medium": 35, "Low": 10}
    severity_score = int(sum(severity[open_mask].map(score_map).fillna(15)))
    mttd = (detected - first_seen).dt.total_seconds().dropna() / 60.0
    mttr = (resolved - first_seen).dt.total_seconds().dropna() / 3600.0

    work = pd.DataFrame({
        "CATEGORY": category,
        "SEVERITY": severity,
        "STATUS": status,
        "SIGNAL": signal,
        "ENTITY": entity,
        "OWNER": owner,
        "RECOMMENDED_ACTION": action,
        "EVENT_TS": event_ts,
        "OPEN": open_mask,
        "RESOLVED": resolved_mask,
        "SCORE": severity.map(score_map).fillna(15).astype(int),
    })
    open_work = work[work["OPEN"]].copy()
    if open_work.empty:
        category_board = pd.DataFrame(columns=["CATEGORY", "OPEN", "CRITICAL_HIGH", "RESOLVED", "SEVERITY_SCORE", "BUSINESS_IMPACT", "RECOMMENDED_OWNER", "RECOMMENDED_ACTION"])
    else:
        category_board = (
            open_work.groupby("CATEGORY", dropna=False)
            .agg(
                OPEN=("OPEN", "sum"),
                CRITICAL_HIGH=("SEVERITY", lambda values: int(pd.Series(values).isin(["Critical", "High"]).sum())),
                SEVERITY_SCORE=("SCORE", "sum"),
                RECOMMENDED_OWNER=("OWNER", lambda values: next((str(value) for value in values if str(value).strip()), "DBA")),
                RECOMMENDED_ACTION=("RECOMMENDED_ACTION", lambda values: next((str(value) for value in values if str(value).strip()), "Review alert telemetry and assign route.")),
            )
            .reset_index()
        )
        resolved_by_category = work.groupby("CATEGORY")["RESOLVED"].sum().to_dict()
        category_board["RESOLVED"] = category_board["CATEGORY"].map(resolved_by_category).fillna(0).astype(int)
        category_board["BUSINESS_IMPACT"] = category_board.apply(
            lambda row: "Incident likely" if int(row["CRITICAL_HIGH"]) else "Early warning / optimization",
            axis=1,
        )
        category_board = category_board.sort_values(["SEVERITY_SCORE", "OPEN"], ascending=[False, False])

    trend = (
        work.assign(ALERT_DAY=work["EVENT_TS"].dt.date)
        .groupby(["ALERT_DAY", "SEVERITY"], dropna=False)
        .size()
        .reset_index(name="ALERTS")
        .sort_values(["ALERT_DAY", "SEVERITY"])
    )
    recurring = (
        open_work.groupby(["CATEGORY", "SIGNAL", "ENTITY"], dropna=False)
        .agg(
            ALERTS=("OPEN", "sum"),
            SEVERITY=("SEVERITY", lambda values: min(values, key=alert_severity_rank)),
            OWNER=("OWNER", lambda values: next((str(value) for value in values if str(value).strip()), "DBA")),
            RECOMMENDED_ACTION=("RECOMMENDED_ACTION", lambda values: next((str(value) for value in values if str(value).strip()), "Review alert telemetry and assign route.")),
        )
        .reset_index()
        .sort_values(["ALERTS", "SEVERITY"], ascending=[False, True])
        .head(15)
    ) if not open_work.empty else pd.DataFrame(columns=["CATEGORY", "SIGNAL", "ENTITY", "ALERTS", "SEVERITY", "OWNER", "RECOMMENDED_ACTION"])

    last_checked = current_time
    if run_history is not None and not run_history.empty:
        run_end = pd.to_datetime(_alert_col(run_history, "COMPLETED_AT", "END_TS", "RUN_TS", default=pd.NaT), errors="coerce").dropna()
        if not run_end.empty:
            last_checked = run_end.max()
    max_event = event_ts.max()
    lag_hours = max(0.0, (current_time - max_event).total_seconds() / 3600.0)
    freshness_state = "Fresh" if lag_hours <= 4 else "Delayed"
    freshness = pd.DataFrame([{
        "SOURCE": "Loaded alert data",
        "LAST_CHECKED": str(last_checked),
        "FRESHNESS_STATE": freshness_state,
        "NOTE": "ACCOUNT_USAGE telemetry can lag; use INFORMATION_SCHEMA/task notifications for near-real-time incident checks.",
    }])
    metrics = pd.DataFrame([
        {"METRIC": "Open critical", "VALUE": int(critical_open.sum()), "STATE": "Incident" if int(critical_open.sum()) else "Clear", "DETAIL": "Security breach risk, runaway spend, failed production pipeline, privilege escalation, or repeated failures."},
        {"METRIC": "Warning alerts", "VALUE": int(warning_open.sum()), "STATE": "Review" if int(warning_open.sum()) else "Clear", "DETAIL": "High/medium cost, performance, reliability, or optimization warnings."},
        {"METRIC": "Info alerts", "VALUE": int(info_open.sum()), "STATE": "Watch" if int(info_open.sum()) else "Clear", "DETAIL": "Low-severity early warnings and informational checks."},
        {"METRIC": "Resolved alerts", "VALUE": int(resolved_mask.sum()), "STATE": "Closed", "DETAIL": "Closed or ignored rows loaded in the selected window."},
    ])
    return {
        "metrics": metrics,
        "category_board": category_board,
        "trend": trend,
        "recurring": recurring,
        "freshness": freshness,
        "last_checked": str(last_checked),
        "severity_score": severity_score,
        "mttd_minutes": float(mttd.mean()) if not mttd.empty else None,
        "mttr_hours": float(mttr.mean()) if not mttr.empty else None,
    }


def _alert_business_impact(category: str, severity: str, provided: str = "") -> str:
    provided = str(provided or "").strip()
    if provided:
        return provided
    category_key = str(category or "").strip().upper()
    severity_key = normalize_alert_severity(severity)
    if category_key == "SECURITY":
        return "Breach, privilege escalation, data exposure, or control bypass risk."
    if category_key == "COST CONTROL":
        return "Spend run-rate or contract burn risk before finance sees the invoice."
    if category_key == "PERFORMANCE":
        return "Queue, spill, lock, or slow-query pressure can become a service incident."
    if category_key == "TASK / PIPELINE":
        return "Task graph or stored procedure issue can break production data freshness SLAs."
    if category_key == "DATA QUALITY":
        return "Freshness, schema, null, duplicate, or volume drift can corrupt downstream decisions."
    if category_key == "OPTIMIZATION":
        return "Avoidable compute, storage, or inefficient repeat work is accumulating."
    if severity_key in {"Critical", "High"}:
        return "Open high-impact alert needs route response and telemetry-backed triage."
    return "Early warning needs route review before it becomes operational noise."


def _alert_impact_estimate(row: pd.Series | dict, category: str, severity: str) -> str:
    for column in (
        "IMPACT_ESTIMATE",
        "BUSINESS_IMPACT_ESTIMATE",
        "ESTIMATED_BUSINESS_IMPACT",
        "COST_IMPACT",
        "ESTIMATED_COST_USD",
        "CREDIT_IMPACT",
    ):
        value = _row_value(row, column, default="")
        if value:
            return value
    category_key = str(category or "").strip().upper()
    severity_key = normalize_alert_severity(severity)
    if category_key == "SECURITY":
        return "Exposure risk - quantify users, roles, objects, and source IPs during triage."
    if category_key == "COST CONTROL":
        return "Cost risk - attach projected daily/month-end spend and top driver telemetry."
    if category_key == "PERFORMANCE":
        return "Service risk - attach queue time, blocked sessions, spill, and affected workload."
    if category_key == "TASK / PIPELINE":
        return "SLA risk - attach failed root/child task, late tables, and downstream consumers."
    if category_key == "DATA QUALITY":
        return "Data trust risk - attach impacted table, freshness/volume/null telemetry, and consumers."
    if severity_key == "Critical":
        return "Critical business impact - assign route immediately and capture containment telemetry."
    return "Impact estimate required before closure."


def _alert_first_response(status: str, severity: str, remediation_mode: str) -> str:
    status_key = _status_key(status)
    if status_key in ALERT_CLOSED_STATUSES:
        return "Confirm closure status and keep telemetry for trend review."
    if status_key in {"NEW", "OPEN", "ACTIVE", "EMAIL_READY", "EMAIL_QUEUED", "PENDING"}:
        if normalize_alert_severity(severity) in {"Critical", "High"}:
            return "Acknowledge, assign route, capture telemetry SQL, and start containment."
        return "Acknowledge or suppress if planned, then route the action."
    if status_key in {"ACKNOWLEDGED", "IN_PROGRESS"}:
        if str(remediation_mode or "").upper() in {"APPROVAL_REQUIRED", "VERIFICATION_REQUIRED", "STATUS_REVIEW"}:
            return "Collect ticket, status review, before state, rollback, and telemetry SQL."
        return "Drive recommended action to status review or documented suppression."
    return "Review status, route, telemetry, and next action before routing."


def _alert_sla_state(open_flag: bool, age_hours: float, sla_hours: float) -> str:
    if not open_flag:
        return "Closed"
    if age_hours >= sla_hours:
        return "Breached"
    if (sla_hours - age_hours) <= 2:
        return "Due <2h"
    return "On Track"


def _alert_source_freshness(category: str, provided: str = "") -> str:
    provided = str(provided or "").strip()
    if provided:
        return provided
    if str(category or "").strip() in {"Security", "Cost", "Performance", "Task / Pipeline", "Optimization"}:
        return "ACCOUNT_USAGE delayed; use INFORMATION_SCHEMA/event-table checks for urgent confirmation."
    return "Configured check; confirm collection schedule and latest run history."


def _queue_lookup(queue: pd.DataFrame | None) -> dict[tuple[str, str], dict[str, str]]:
    if queue is None or queue.empty:
        return {}
    view = queue.copy()
    category = _alert_col(view, "CATEGORY", "DOMAIN", default="").fillna("").astype(str)
    entity = _alert_col(view, "ENTITY_NAME", "ENTITY", default="").fillna("").astype(str)
    lookup: dict[tuple[str, str], dict[str, str]] = {}
    for idx, row in view.iterrows():
        key = (category.loc[idx].strip().upper(), entity.loc[idx].strip().upper())
        if not key[0] or not key[1] or key in lookup:
            continue
        lookup[key] = {
            "QUEUE_STATUS": _row_value(row, "STATUS", default=""),
            "TICKET_ID": _row_value(row, "TICKET_ID", default=""),
            "DUE_STATE": _row_value(row, "DUE_STATE", default=""),
            "EVIDENCE_GAP": _row_value(row, "EVIDENCE_GAP", default=""),
            "REVIEWED_BY": _row_value(row, "REVIEWED_BY", default=""),
            "REVIEW_STATUS": _row_value(row, "REVIEW_STATUS", default=""),
        }
    return lookup


def build_alert_incident_action_board(
    alerts: pd.DataFrame,
    queue: pd.DataFrame | None = None,
    *,
    now: Any | None = None,
    limit: int = 50,
) -> pd.DataFrame:
    """Build the prioritized operator queue for open alert events."""
    columns = [
        "PRIORITY",
        "INCIDENT_KEY",
        "SEVERITY",
        "STATUS",
        "SLA_STATE",
        "AGE_HOURS",
        "SLA_HOURS",
        "CATEGORY",
        "SIGNAL",
        "ENTITY",
        "OWNER",
        "BUSINESS_IMPACT",
        "IMPACT_ESTIMATE",
        "FIRST_RESPONSE",
        "RECOMMENDED_ACTION",
        "PROOF_QUERY",
        "SOURCE_FRESHNESS",
        "REMEDIATION_MODE",
        "TICKET_ID",
        "QUEUE_STATE",
        "EVIDENCE_GAP",
        "REVIEW_STATUS",
        "ROUTE",
    ]
    source = alerts
    if (source is None or source.empty) and queue is not None and not queue.empty:
        source = queue.copy()
        if "ALERT_TYPE" not in source.columns and "SIGNAL" not in source.columns:
            source["ALERT_TYPE"] = _alert_col(source, "ISSUE_SOURCE", "DOMAIN", default="Action Queue Row")
        if "ENTITY_NAME" not in source.columns and "ENTITY" not in source.columns:
            source["ENTITY_NAME"] = _alert_col(source, "OBJECT_NAME", "WAREHOUSE_NAME", "TASK_NAME", default="Queued action")
        if "SUGGESTED_ACTION" not in source.columns and "RECOMMENDED_ACTION" in source.columns:
            source["SUGGESTED_ACTION"] = source["RECOMMENDED_ACTION"]
        if "PROOF_QUERY" not in source.columns:
            source["PROOF_QUERY"] = _alert_col(source, "VERIFICATION_SQL", "VERIFY_SQL", default="Open the action queue row and record closure status.")
        if "REMEDIATION_MODE" not in source.columns:
            source["REMEDIATION_MODE"] = "RECOMMEND"
    if source is None or source.empty:
        return pd.DataFrame(columns=columns)

    current_time = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
    df = normalize_alert_frame(source)
    status = _alert_col(df, "STATUS", default="New").apply(normalize_alert_status)
    open_mask = ~status.apply(lambda value: _status_key(value) in ALERT_CLOSED_STATUSES)
    work = df[open_mask].copy()
    if work.empty:
        return pd.DataFrame(columns=columns)

    status = status.loc[work.index]
    category = _alert_col(work, "CATEGORY", "DOMAIN", default="Alert").fillna("Alert").astype(str)
    severity = _alert_col(work, "SEVERITY", default="Medium").apply(normalize_alert_severity)
    signal = _alert_col(work, "ALERT_TYPE", "SIGNAL", "MESSAGE", default="Alert").fillna("Alert").astype(str)
    entity = _alert_col(work, "ENTITY_NAME", "ENTITY", default="Snowflake account").fillna("Snowflake account").astype(str)
    owner = _alert_col(work, "OWNER", "ROUTED_OWNER", "WORKFLOW_ROUTE", default="DBA").fillna("DBA").astype(str)
    action = _alert_col(work, "SUGGESTED_ACTION", "NEXT_ACTION", "RECOMMENDED_ACTION", default="Review alert telemetry and assign route.").fillna("Review alert telemetry and assign route.").astype(str)
    proof = _alert_col(work, "PROOF_QUERY", default="Open source telemetry and record status.").fillna("Open source telemetry and record status.").astype(str)
    route = _alert_col(work, "ROUTE", "WORKFLOW", default="Alert Center").fillna("Alert Center").astype(str)
    remediation_mode = _alert_col(work, "REMEDIATION_MODE", default="RECOMMEND").fillna("RECOMMEND").astype(str).str.upper().str.replace(" ", "_")
    freshness = _alert_col(work, "SOURCE_FRESHNESS", "TELEMETRY_FRESHNESS", "FRESHNESS", default="").fillna("").astype(str)
    event_ts = pd.to_datetime(_alert_col(work, "FIRST_SEEN_AT", "ALERT_TS", "EVENT_TS", default=current_time), errors="coerce").fillna(current_time)
    sla_default = severity.map(ALERT_SLA_HOURS).fillna(24)
    if "SLA_HOURS" in work.columns:
        sla_hours = pd.to_numeric(work["SLA_HOURS"], errors="coerce").fillna(sla_default)
    else:
        sla_hours = sla_default
    sla_hours = sla_hours.astype(float).clip(lower=1)
    age_hours = ((current_time - event_ts).dt.total_seconds() / 3600.0).clip(lower=0).round(1)
    queue_by_entity = _queue_lookup(queue)

    rows: list[dict[str, object]] = []
    score_map = {"Critical": 100, "High": 70, "Medium": 35, "Low": 10}
    for idx, row in work.iterrows():
        row_category = str(category.loc[idx])
        row_severity = str(severity.loc[idx])
        row_status = str(status.loc[idx])
        row_entity = str(entity.loc[idx])
        row_mode = str(remediation_mode.loc[idx] or "RECOMMEND")
        queue_context = queue_by_entity.get((row_category.strip().upper(), row_entity.strip().upper()), {})
        row_age = float(age_hours.loc[idx])
        row_sla = float(sla_hours.loc[idx])
        breached = row_age >= row_sla
        impact = _alert_business_impact(row_category, row_severity, _row_value(row, "BUSINESS_IMPACT", default=""))
        rows.append({
            "INCIDENT_KEY": _row_value(row, "DEDUPE_KEY", "ALERT_ID", "EVENT_ID", default=f"{row_category}:{row_entity}:{signal.loc[idx]}"),
            "SEVERITY": row_severity,
            "STATUS": row_status,
            "SLA_STATE": _alert_sla_state(True, row_age, row_sla),
            "AGE_HOURS": row_age,
            "SLA_HOURS": row_sla,
            "CATEGORY": row_category,
            "SIGNAL": str(signal.loc[idx]),
            "ENTITY": row_entity,
            "OWNER": str(owner.loc[idx]) or "DBA",
            "BUSINESS_IMPACT": impact,
            "IMPACT_ESTIMATE": _alert_impact_estimate(row, row_category, row_severity),
            "FIRST_RESPONSE": _alert_first_response(row_status, row_severity, row_mode),
            "RECOMMENDED_ACTION": str(action.loc[idx]),
            "PROOF_QUERY": str(proof.loc[idx]) or "Open source telemetry and record status.",
            "SOURCE_FRESHNESS": _alert_source_freshness(row_category, str(freshness.loc[idx])),
            "REMEDIATION_MODE": row_mode if row_mode in {"OFF", "RECOMMEND", "STATUS_REVIEW", "AUTO"} else ("STATUS_REVIEW" if row_mode in {"APPROVAL_REQUIRED", "VERIFICATION_REQUIRED"} else "RECOMMEND"),
            "TICKET_ID": queue_context.get("TICKET_ID", _row_value(row, "TICKET_ID", default="")),
            "QUEUE_STATE": queue_context.get("QUEUE_STATUS", _row_value(row, "QUEUE_STATE", default="Route to action queue")),
            "EVIDENCE_GAP": queue_context.get("EVIDENCE_GAP", _row_value(row, "EVIDENCE_GAP", default="Telemetry, route, and closure status required.")),
            "REVIEW_STATUS": queue_context.get("REVIEW_STATUS", _row_value(row, "REVIEW_STATUS", default="DBA Review")),
            "ROUTE": str(route.loc[idx]),
            "_SORT_SCORE": int(score_map.get(row_severity, 15)) + (40 if breached else 0) + min(int(row_age), 24),
            "_SEVERITY_RANK": alert_severity_rank(row_severity),
            "_EVENT_TS": event_ts.loc[idx],
        })

    board = pd.DataFrame(rows)
    if board.empty:
        return pd.DataFrame(columns=columns)
    board = board.sort_values(["_SORT_SCORE", "_SEVERITY_RANK", "_EVENT_TS"], ascending=[False, True, False]).head(max(1, int(limit or 50))).copy()
    board.insert(0, "PRIORITY", range(1, len(board) + 1))
    return board[columns]


_SECTION_ALERT_TOKENS = {
    "COST": (
        "COST",
        "SPEND",
        "SPEND SPIKE",
        "CREDIT",
        "CORTEX",
        "WAREHOUSE",
        "METERING",
        "BUDGET",
        "CONTRACT",
        "CHARGEBACK",
        "FORECAST",
        "RUN RATE",
        "OPTIMIZATION",
        "STORAGE",
    ),
    "WORKLOAD": (
        "WORKLOAD",
        "QUERY",
        "PERFORMANCE",
        "QUEUE",
        "SPILL",
        "LOCK",
        "TASK",
        "PIPELINE",
        "PROCEDURE",
        "COPY",
        "LOAD",
        "SNOWPIPE",
        "DYNAMIC TABLE",
        "FAILURE",
        "SLA",
    ),
    "SECURITY": (
        "SECURITY",
        "LOGIN",
        "MFA",
        "GRANT",
        "PRIVILEGE",
        "ROLE",
        "EXPORT",
        "SHARE",
        "ACCESS",
        "EXFILTRATION",
        "POLICY",
        "USER",
    ),
}


def _section_alert_domain(section: str) -> str:
    text = str(section or "").strip().upper()
    if any(token in text for token in ("COST", "CONTRACT", "CORTEX", "SPEND", "BEHAVIOR", "FORECAST")):
        return "COST"
    if any(token in text for token in ("WORKLOAD", "QUERY", "TASK", "PROCEDURE", "PIPELINE", "RELIABILITY")):
        return "WORKLOAD"
    if any(token in text for token in ("SECURITY", "ACCESS", "PRIVILEGE", "SHARE")):
        return "SECURITY"
    if any(token in text for token in ("EXECUTIVE", "LEADERSHIP", "COMMAND")):
        return "EXECUTIVE"
    return "EXECUTIVE"


def _section_alert_focus(text: str) -> str:
    key = str(text or "").upper()
    if "CORTEX" in key or " AI " in f" {key} ":
        return "Cortex spend"
    if "SPEND SPIKE" in key or ("SPEND" in key and "SPIKE" in key):
        return "Spend spike"
    if any(token in key for token in ("COST", "CREDIT", "METERING", "CHARGEBACK", "CONTRACT", "BUDGET", "FORECAST")):
        return "Cost movement"
    if any(token in key for token in ("LOGIN", "MFA", "GRANT", "PRIVILEGE", "ACCESS", "SHARE", "EXPORT", "EXFILTRATION")):
        return "Security access"
    if any(token in key for token in ("TASK", "PIPELINE", "PROCEDURE", "COPY", "LOAD", "DYNAMIC TABLE", "SNOWPIPE")):
        return "Pipeline reliability"
    if any(token in key for token in ("QUERY", "QUEUE", "SPILL", "LOCK", "PERFORMANCE", "WAREHOUSE")):
        return "Query performance"
    return "Operational alert"


def _alert_route_for_focus(section: str, focus: str) -> tuple[str, str, str, str, str]:
    """Map loaded alert context to the section/workflow that should be opened next."""
    focus_key = str(focus or "").upper()
    section_key = str(section or "").upper()
    if "CORTEX" in focus_key:
        return (
            "Cost & Contract",
            "Cortex AI",
            "Cost Alerts",
            "Open Cost & Contract > Cortex AI for model-level Cortex evidence.",
            "Review Cortex user/source, baseline, quota, grants, and company scope before changing access.",
        )
    if "SPEND" in focus_key or "COST" in focus_key:
        return (
            "Cost & Contract",
            "Cost Explorer",
            "Cost Alerts",
            "Open Cost & Contract > Cost Explorer > Warehouse.",
            "Compare completed-window metering, run-rate baseline, chargeback, and open savings actions.",
        )
    if "SECURITY" in focus_key:
        return (
            "Security Monitoring",
            "Failed Logins",
            "Security Alerts",
            "Open Security Monitoring > Failed Logins.",
            "Confirm actor, role, MFA/login context, object scope, and reviewer status before closure.",
        )
    if "PIPELINE" in focus_key:
        return (
            "Workload Operations",
            "Pipeline & Task Health",
            "Reliability Alerts",
            "Open Workload Operations > Pipeline & Task Health.",
            "Check root task/procedure, failed child query, last success, retry safety, and downstream SLA.",
        )
    if "QUERY" in focus_key or "PERFORMANCE" in focus_key:
        return (
            "Workload Operations",
            "Query Investigation",
            "Reliability Alerts",
            "Open Workload Operations > Query Investigation.",
            "Review query ID, warehouse pressure, queue/spill/lock evidence, and workload workflow route.",
        )
    if "WORKLOAD" in section_key:
        return (
            "Workload Operations",
            "Pipeline & Task Health",
            "Reliability Alerts",
            "Open Workload Operations and choose the reliability workflow matching the signal.",
            "Use exact query/task/procedure telemetry before retrying, resizing, or cancelling anything.",
        )
    if "SECURITY" in section_key:
        return (
            "Security Monitoring",
            "Failed Logins",
            "Security Alerts",
            "Open Security Monitoring and validate the access posture route.",
            "Treat access/security signals as status-review until reviewer and evidence are attached.",
        )
    return (
        "Alert Center",
        "Active Alerts",
        "Active Alerts",
        "Open Alert Center > Active Alerts.",
        "Work route, SLA, delivery, action queue, and closure status from the alert command board.",
    )


def _alert_automation_readiness(focus: str, remediation_mode: str) -> str:
    mode = str(remediation_mode or "RECOMMEND").upper().replace(" ", "_")
    focus_key = str(focus or "").upper()
    if mode in {"OFF", "DISABLED"}:
        return "Detection only"
    if any(token in focus_key for token in ("SECURITY", "CORTEX", "SPEND", "COST")):
        return "Recommend only"
    if "PIPELINE" in focus_key:
        return "Dry-run candidate"
    if "QUERY" in focus_key or "PERFORMANCE" in focus_key:
        return "Status-review candidate"
    return "Recommend only"


def _alert_cortex_guardrail(row: pd.Series | dict[str, Any]) -> str:
    text = " ".join(
        _row_value(row, key, default="")
        for key in ("SECTION_FOCUS", "SIGNAL", "CATEGORY", "RECOMMENDED_ACTION", "ENTITY")
    ).upper()
    if "CORTEX" not in text and " AI " not in f" {text} ":
        return ""
    return (
        "Do not disable Cortex access from an alert alone; compare user/source baseline, "
        "company scope, grants, and quota settings first."
    )


def build_section_alert_signal_board(
    alerts: pd.DataFrame,
    queue: pd.DataFrame | None = None,
    *,
    section: str,
    limit: int = 8,
) -> pd.DataFrame:
    """Return loaded Alert Center rows relevant to a specific app section.

    This intentionally uses already-loaded alert/action data. Section pages should
    not trigger separate ACCOUNT_USAGE scans just to show alert context.
    """
    output_columns = [
        "SECTION_FOCUS",
        "PRIORITY",
        "SEVERITY",
        "SLA_STATE",
        "STATUS",
        "CATEGORY",
        "SIGNAL",
        "ENTITY",
        "OWNER",
        "ROUTE",
        "FIRST_RESPONSE",
        "RECOMMENDED_ACTION",
        "IMPACT_ESTIMATE",
        "PROOF_QUERY",
        "SOURCE_FRESHNESS",
        "REMEDIATION_MODE",
        "QUEUE_STATE",
        "TICKET_ID",
        "ALERT_CENTER_VIEW",
        "DESTINATION_SECTION",
        "DESTINATION_WORKFLOW",
        "OPEN_PATH",
        "DRILLDOWN_HINT",
        "AUTOMATION_READINESS",
        "CORTEX_GUARDRAIL",
    ]
    incident_board = build_alert_incident_action_board(alerts, queue, limit=500)
    if incident_board.empty:
        return pd.DataFrame(columns=output_columns)

    text_columns = [
        "CATEGORY",
        "SIGNAL",
        "ENTITY",
        "OWNER",
        "ROUTE",
        "FIRST_RESPONSE",
        "RECOMMENDED_ACTION",
        "IMPACT_ESTIMATE",
        "PROOF_QUERY",
        "BUSINESS_IMPACT",
    ]
    search_text = pd.Series([""] * len(incident_board), index=incident_board.index, dtype=str)
    for column in text_columns:
        if column in incident_board.columns:
            search_text = search_text + " " + incident_board[column].fillna("").astype(str).str.upper()

    domain = _section_alert_domain(section)
    if domain == "EXECUTIVE":
        severity = incident_board.get("SEVERITY", pd.Series(index=incident_board.index, dtype=str)).fillna("").astype(str)
        sla_state = incident_board.get("SLA_STATE", pd.Series(index=incident_board.index, dtype=str)).fillna("").astype(str).str.upper()
        mask = (
            severity.isin(["Critical", "High"])
            | sla_state.isin(["BREACHED", "DUE <2H", "OVERDUE", "DUE SOON"])
            | search_text.str.contains("COST|SPEND|CORTEX|SECURITY|PRIVILEGE|TASK|PIPELINE", regex=True)
        )
    else:
        tokens = _SECTION_ALERT_TOKENS.get(domain, ())
        mask = pd.Series(False, index=incident_board.index)
        for token in tokens:
            mask = mask | search_text.str.contains(re.escape(token), regex=True)

    visible = incident_board[mask].copy()
    if visible.empty:
        return pd.DataFrame(columns=output_columns)

    visible["SECTION_FOCUS"] = search_text.loc[visible.index].apply(_section_alert_focus)
    route_values = visible["SECTION_FOCUS"].apply(lambda focus: _alert_route_for_focus(section, focus))
    visible["DESTINATION_SECTION"] = route_values.apply(lambda value: value[0])
    visible["DESTINATION_WORKFLOW"] = route_values.apply(lambda value: value[1])
    visible["ALERT_CENTER_VIEW"] = route_values.apply(lambda value: value[2])
    visible["OPEN_PATH"] = route_values.apply(lambda value: value[3])
    visible["DRILLDOWN_HINT"] = route_values.apply(lambda value: value[4])
    visible["AUTOMATION_READINESS"] = visible.apply(
        lambda row: _alert_automation_readiness(
            str(row.get("SECTION_FOCUS") or ""),
            str(row.get("REMEDIATION_MODE") or "RECOMMEND"),
        ),
        axis=1,
    )
    visible["CORTEX_GUARDRAIL"] = visible.apply(_alert_cortex_guardrail, axis=1)
    priority = pd.to_numeric(visible.get("PRIORITY", pd.Series(range(1, len(visible) + 1), index=visible.index)), errors="coerce").fillna(999)
    focus_boost = visible["SECTION_FOCUS"].isin(["Cortex spend", "Spend spike"]).map({True: -0.25, False: 0.0})
    visible["_SECTION_SORT"] = priority + focus_boost
    visible = visible.sort_values(["_SECTION_SORT", "SEVERITY", "SLA_STATE"], ascending=[True, True, True]).head(max(1, int(limit or 8)))
    for column in output_columns:
        if column not in visible.columns:
            visible[column] = ""
    return visible[output_columns].reset_index(drop=True)


def build_loaded_section_alert_signal_board(
    state: Any,
    *,
    section: str,
    limit: int = 8,
) -> pd.DataFrame:
    """Build a section alert board from ``st.session_state`` without live reads."""
    try:
        data = state.get("alert_center_data")
    except AttributeError:
        data = None
    if not isinstance(data, dict):
        return pd.DataFrame()
    alerts = data.get("alerts")
    queue = data.get("action_queue")
    alerts_df = alerts if isinstance(alerts, pd.DataFrame) else pd.DataFrame()
    queue_df = queue if isinstance(queue, pd.DataFrame) else pd.DataFrame()
    return build_section_alert_signal_board(alerts_df, queue_df, section=section, limit=limit)


def build_cost_cortex_alert_drilldown(
    alerts: pd.DataFrame,
    queue: pd.DataFrame | None = None,
    *,
    limit: int = 10,
) -> pd.DataFrame:
    """Build a cost/Cortex alert explanation board from loaded alert context."""
    board = build_section_alert_signal_board(alerts, queue, section="Cost & Contract", limit=max(limit, 10))
    if board.empty:
        return pd.DataFrame(columns=[
            "FOCUS",
            "SEVERITY",
            "ENTITY",
            "WHY_THIS_FIRED",
            "BASELINE_CONTEXT",
            "CURRENT_CONTEXT",
            "THRESHOLD_CONTEXT",
            "WHERE_TO_OPEN",
            "SAFE_ACTION",
            "AUTOMATION_BOUNDARY",
        ])
    visible = board[
        board["SECTION_FOCUS"].isin(["Cortex spend", "Spend spike", "Cost movement"])
    ].copy()
    if visible.empty:
        return pd.DataFrame()

    def _context(row: pd.Series, key: str) -> str:
        raw = _row_value(row, key, default="")
        if not raw:
            return "Not loaded"
        return raw

    rows: list[dict[str, str]] = []
    for _, row in visible.head(max(1, int(limit or 10))).iterrows():
        focus = str(row.get("SECTION_FOCUS") or "Cost movement")
        signal = str(row.get("SIGNAL") or row.get("CATEGORY") or "Cost alert")
        entity = str(row.get("ENTITY") or "Snowflake account")
        if focus == "Cortex spend":
            why = (
                f"{signal} is active for {entity}; validate user/source usage, request count, "
                "baseline, company route, and quota settings."
            )
            safe_action = "Open Cost & Contract > Cortex AI for model-level evidence before changing access."
            boundary = "Recommend only until quota/grant changes have named DBA status review."
        elif focus == "Spend spike":
            why = f"{signal} indicates spend is above the loaded baseline for {entity}."
            safe_action = "Open usage attribution and run-rate; compare official metering to query and warehouse drivers."
            boundary = "No automatic warehouse changes from spend alone."
        else:
            why = f"{signal} needs cost movement review for {entity}."
            safe_action = "Open Cost & Contract and reconcile run-rate, chargeback, and action queue."
            boundary = "Recommend only unless a remediation policy explicitly allows dry-run."
        rows.append({
            "FOCUS": focus,
            "SEVERITY": str(row.get("SEVERITY") or ""),
            "ENTITY": entity,
            "WHY_THIS_FIRED": why,
            "BASELINE_CONTEXT": _context(row, "BASELINE_VALUE"),
            "CURRENT_CONTEXT": _context(row, "CURRENT_VALUE"),
            "THRESHOLD_CONTEXT": _context(row, "THRESHOLD_VALUE"),
            "WHERE_TO_OPEN": str(row.get("OPEN_PATH") or "Open Cost & Contract."),
            "SAFE_ACTION": safe_action,
            "AUTOMATION_BOUNDARY": boundary,
        })
    return pd.DataFrame(rows)


def build_alert_owner_workload_board(
    alerts: pd.DataFrame,
    queue: pd.DataFrame | None = None,
    *,
    now: Any | None = None,
) -> pd.DataFrame:
    """Summarize who owns the current alert workload and where evidence is missing."""
    incident_board = build_alert_incident_action_board(alerts, queue, now=now, limit=500)
    columns = [
        "OWNER",
        "OPEN_ALERTS",
        "CRITICAL_HIGH",
        "SLA_BREACHED",
        "TICKETS_ATTACHED",
        "TOP_CATEGORY",
        "NEXT_ACTION",
        "REVIEW_STATUS",
    ]
    if incident_board.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for owner, group in incident_board.groupby("OWNER", dropna=False):
        category_counts = group["CATEGORY"].value_counts()
        tickets = group["TICKET_ID"].fillna("").astype(str).str.strip()
        next_action = group.sort_values("PRIORITY").iloc[0]["FIRST_RESPONSE"]
        rows.append({
            "OWNER": str(owner or "DBA"),
            "OPEN_ALERTS": int(len(group)),
            "CRITICAL_HIGH": int(group["SEVERITY"].isin(["Critical", "High"]).sum()),
            "SLA_BREACHED": int(group["SLA_STATE"].eq("Breached").sum()),
            "TICKETS_ATTACHED": int(tickets.ne("").sum()),
            "TOP_CATEGORY": str(category_counts.index[0]) if not category_counts.empty else "Alert",
            "NEXT_ACTION": str(next_action),
            "REVIEW_STATUS": next((str(value) for value in group["REVIEW_STATUS"] if str(value).strip()), "DBA Review"),
        })
    return pd.DataFrame(rows).sort_values(["SLA_BREACHED", "CRITICAL_HIGH", "OPEN_ALERTS"], ascending=[False, False, False])[columns]


def build_alert_morning_brief_rows(alerts: pd.DataFrame, *, limit: int = 12) -> pd.DataFrame:
    """Return prioritized DBA Daily Brief rows from loaded alert evidence."""
    if alerts is None or alerts.empty:
        return pd.DataFrame(columns=[
            "PRIORITY",
            "CATEGORY",
            "SEVERITY",
            "ENTITY",
            "WHY_THIS_MATTERS",
            "RECOMMENDED_ACTION",
            "OWNER",
            "PROOF_QUERY",
        ])
    df = normalize_alert_frame(alerts)
    status = _alert_col(df, "STATUS", default="New").apply(normalize_alert_status)
    open_mask = ~status.apply(lambda value: _status_key(value) in ALERT_CLOSED_STATUSES)
    work = df[open_mask].copy()
    if work.empty:
        return pd.DataFrame(columns=[
            "PRIORITY",
            "CATEGORY",
            "SEVERITY",
            "ENTITY",
            "WHY_THIS_MATTERS",
            "RECOMMENDED_ACTION",
            "OWNER",
            "PROOF_QUERY",
        ])
    category = _alert_col(work, "CATEGORY", default="Alert").fillna("Alert").astype(str)
    severity = _alert_col(work, "SEVERITY", default="Medium").apply(normalize_alert_severity)
    entity = _alert_col(work, "ENTITY_NAME", "ENTITY", default="Snowflake account").fillna("Snowflake account").astype(str)
    signal = _alert_col(work, "ALERT_TYPE", "MESSAGE", default="Alert").fillna("Alert").astype(str)
    action = _alert_col(work, "SUGGESTED_ACTION", "NEXT_ACTION", default="Review alert telemetry and assign route.").fillna("Review alert telemetry and assign route.").astype(str)
    owner = _alert_col(work, "OWNER", "WORKFLOW_ROUTE", default="DBA").fillna("DBA").astype(str)
    proof = _alert_col(work, "PROOF_QUERY", default="Open the alert row and record source telemetry.").fillna("Open the alert row and record source telemetry.").astype(str)
    event_ts = pd.to_datetime(_alert_col(work, "ALERT_TS", "EVENT_TS", default=pd.Timestamp.now()), errors="coerce").fillna(pd.Timestamp.now())
    priority_frame = pd.DataFrame({
        "CATEGORY": category,
        "SEVERITY": severity,
        "SIGNAL": signal,
        "ENTITY": entity,
        "RECOMMENDED_ACTION": action,
        "OWNER": owner,
        "PROOF_QUERY": proof,
        "EVENT_TS": event_ts,
    })
    priority_frame["_RANK"] = priority_frame["SEVERITY"].apply(alert_severity_rank)
    priority_frame = priority_frame.sort_values(["_RANK", "EVENT_TS"], ascending=[True, False]).head(max(1, int(limit or 12))).copy()
    why_map = {
        "Security": "Possible breach, privilege escalation, data exposure, or control bypass.",
        "Cost": "Spend may exceed normal run-rate or contract burn before finance sees the invoice.",
        "Performance": "Queue, spill, long-running, or lock patterns can become an outage without intervention.",
        "Task / Pipeline": "Task graph or stored procedure failures can break downstream pipeline SLAs.",
        "Data Quality": "Freshness, volume, null, duplicate, or schema drift can corrupt downstream decisions.",
        "Optimization": "The account is paying for avoidable compute, storage, or repeated inefficient patterns.",
    }
    priority_frame["WHY_THIS_MATTERS"] = priority_frame["CATEGORY"].map(why_map).fillna("Open alert needs DBA triage and route telemetry.")
    priority_frame.insert(0, "PRIORITY", range(1, len(priority_frame) + 1))
    return priority_frame[[
        "PRIORITY",
        "CATEGORY",
        "SEVERITY",
        "SIGNAL",
        "ENTITY",
        "WHY_THIS_MATTERS",
        "RECOMMENDED_ACTION",
        "OWNER",
        "PROOF_QUERY",
    ]]


def build_alert_remediation_contract(row: pd.Series | dict | None = None) -> dict[str, str]:
    """Build a safe remediation contract for a single alert/action row."""
    if row is None:
        row = {}
    signal = " ".join([
        _row_value(row, "CATEGORY", default=""),
        _row_value(row, "ALERT_TYPE", "SIGNAL", default=""),
        _row_value(row, "SUGGESTED_ACTION", "RECOMMENDED_ACTION", default=""),
        _row_value(row, "REMEDIATION_SQL", "Generated SQL Fix", default=""),
    ]).upper()
    requested_mode = _row_value(row, "REMEDIATION_MODE", default="RECOMMEND").upper().replace(" ", "_")
    if requested_mode in {"APPROVAL_REQUIRED", "VERIFICATION_REQUIRED"}:
        requested_mode = "STATUS_REVIEW"
    if requested_mode not in {"OFF", "RECOMMEND", "STATUS_REVIEW", "AUTO"}:
        requested_mode = "RECOMMEND"
    sql_preview = _row_value(row, "REMEDIATION_SQL", "Generated SQL Fix", default="Review telemetry and route status first.")
    dangerous_terms = ("DROP ", "DELETE ", "TRUNCATE ", "REVOKE ", "DISABLE USER", "ALTER USER", "CANCEL QUERY", "SYSTEM$CANCEL_QUERY", "ALTER WAREHOUSE", "EXECUTE TASK", "RESUME TASK", "SUSPEND WAREHOUSE")
    dangerous = any(term in signal or term in str(sql_preview).upper() for term in dangerous_terms)
    if dangerous and requested_mode == "AUTO":
        mode = "STATUS_REVIEW"
    else:
        mode = requested_mode
    approval_gate = {
        "OFF": "Detection only. No remedial action can be executed from this alert.",
        "RECOMMEND": "Show recommendation and review guidance only; DBA executes elsewhere after status review.",
        "STATUS_REVIEW": "Named route, DBA reviewer, ticket, before state, rollback guidance, and telemetry status are required before execution.",
        "AUTO": "Allowed only for explicitly reviewed safe actions with audit logging and automatic status capture.",
    }[mode]
    if dangerous and mode != "STATUS_REVIEW":
        approval_gate += " Dangerous state-changing action detected; keep this out of AUTO mode."
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake object")
    verify = _row_value(row, "PROOF_QUERY", "Verification Query", default="SELECT current_timestamp() AS status_checkpoint;")
    return {
        "REMEDIATION_MODE": mode,
        "APPROVAL_GATE": approval_gate,
        "SQL_PREVIEW": sql_preview,
        "EXECUTION_BOUNDARY": "Alert Center prepares and logs the action contract. State-changing execution must go through the reviewed DBA workflow for the affected object.",
        "AUDIT_LOG_REQUIRED": "ALERT_REMEDIATION_LOG must capture trigger, actor, review, SQL/action, before state, after state, success/failure, rollback guidance, and status result.",
        "ROLLBACK_GUIDANCE": f"Capture current state for {entity} before action; document exact rollback SQL or operational recovery path before review.",
        "VERIFY_NEXT": verify,
        "DANGEROUS_ACTION": "Yes" if dangerous else "No",
    }
