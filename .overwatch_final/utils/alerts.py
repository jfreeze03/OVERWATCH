# utils/alerts.py - email-first alert framework, alert table DDL, and annotations
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

import pandas as pd
import streamlit as st

from config import (
    ALERT_DB,
    ALERT_DELIVERY_METHOD,
    ALERT_SCHEMA,
    ALERT_TABLE,
    DEFAULT_ALERT_EMAIL,
    THRESHOLDS,
)
from .compatibility import filter_existing_columns
from .company_filter import (
    company_value_allowed,
    environment_value_allowed,
    get_active_environment,
)
from .owner_directory import (
    OWNER_DIRECTORY_VIEW,
    build_owner_directory_ddl,
    default_owner_directory,
    resolve_owner_context,
)
from .query import (
    format_snowflake_error,
    run_query,
    safe_identifier,
    safe_schedule,
    sql_literal,
)


ANNOTATION_TABLE = "OVERWATCH_ANNOTATIONS"
ALERT_DELIVERY_LOG_TABLE = "OVERWATCH_ALERT_DELIVERY_LOG"
ALERT_RULE_AUDIT_TABLE = "OVERWATCH_ALERT_RULE_AUDIT"
DEFAULT_ALERT_RECIPIENT = DEFAULT_ALERT_EMAIL
ALERT_OPEN_STATUSES = {
    "NEW",
    "OPEN",
    "ACTIVE",
    "ACKNOWLEDGED",
    "IN PROGRESS",
    "IN_PROGRESS",
    "EMAIL_READY",
    "EMAIL_QUEUED",
    "PENDING",
}
ALERT_CLOSED_STATUSES = {"FIXED", "IGNORED", "RESOLVED"}
ALERT_STATUS_CHOICES = ("Acknowledged", "In Progress", "Fixed", "Ignored")
ALERT_SLA_HOURS = {
    "Critical": 4,
    "High": 8,
    "Medium": 24,
    "Low": 72,
}
DEFAULT_ALERT_RULES = [
    {
        "RULE_ID": "COST_CREDIT_SPIKE",
        "CATEGORY": "Cost Control",
        "ALERT_TYPE": "Credit Spike",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA / FinOps",
        "ROUTE": "Cost & Contract",
        "RUNBOOK": "Explain the bill movement, identify owner-backed drivers, and route savings actions.",
    },
    {
        "RULE_ID": "COST_SAVINGS_VERIFIER_FAILURE",
        "CATEGORY": "Cost Control",
        "ALERT_TYPE": "Cost Savings Verification Failure",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "DBA / FinOps",
        "ROUTE": "Cost & Contract",
        "RUNBOOK": "Inspect the savings verifier task, keep savings estimated, and restore ledger-backed verification before claiming value.",
    },
    {
        "RULE_ID": "QUERY_HIGH_ERROR_RATE",
        "CATEGORY": "Reliability",
        "ALERT_TYPE": "High Query Error Rate",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "DBA / Workload Owner",
        "ROUTE": "Workload Operations",
        "RUNBOOK": "Group failures by error code/query text and assign the owning team.",
    },
    {
        "RULE_ID": "TASK_FAILURE",
        "CATEGORY": "Reliability",
        "ALERT_TYPE": "Task Failure",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "DBA / Pipeline Owner",
        "ROUTE": "Workload Operations",
        "RUNBOOK": "Review task graph impact, retry only after root cause, and verify the next run.",
    },
    {
        "RULE_ID": "PROCEDURE_FAILURE_OR_SPIKE",
        "CATEGORY": "Reliability",
        "ALERT_TYPE": "Stored Procedure Failure / Runtime Spike",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "DBA / Procedure Owner",
        "ROUTE": "Workload Operations",
        "RUNBOOK": "Compare release windows, inspect child queries, and verify runtime/cost return to baseline.",
    },
    {
        "RULE_ID": "WAREHOUSE_PRESSURE",
        "CATEGORY": "Capacity",
        "ALERT_TYPE": "Warehouse Pressure",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA / Platform",
        "ROUTE": "Warehouse Health",
        "RUNBOOK": "Inspect queue/spill evidence and route changed-only warehouse setting recommendations.",
    },
    {
        "RULE_ID": "GRANT_REVOKE_ACTIVITY",
        "CATEGORY": "Change Control",
        "ALERT_TYPE": "Grant/Revoke Activity",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA / Security",
        "ROUTE": "Security Posture",
        "RUNBOOK": "Verify least-privilege approval, owner, ticket, approver, and review date.",
    },
    {
        "RULE_ID": "WAREHOUSE_SETTING_CHANGE",
        "CATEGORY": "Change Control",
        "ALERT_TYPE": "Warehouse Setting Change",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA / Platform",
        "ROUTE": "Change & Drift",
        "RUNBOOK": "Verify changed-only SQL, approval, rollback SQL, and post-change evidence.",
    },
]
ISSUE_COLUMNS = [
    "ISSUE_SOURCE",
    "SEVERITY",
    "STATUS",
    "DOMAIN",
    "SIGNAL",
    "ENTITY",
    "DETAIL",
    "NEXT_ACTION",
    "OWNER",
    "EMAIL_TARGET",
    "DELIVERY_STATUS",
    "ROUTE",
    "WORKFLOW",
    "EVENT_TS",
]


def send_teams_alert(webhook_url: str, message: str, title: str = "OVERWATCH Alert") -> bool:
    """Send a Microsoft Teams message via incoming webhook.

    Kept for future Teams support, but the active framework is email-first.
    """
    if not webhook_url:
        return False
    payload = json.dumps({
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": title,
        "themeColor": "38BDF8",
        "title": title,
        "text": message,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        st.warning(f"Teams alert failed: {format_snowflake_error(e)}")
        return False


def alert_table_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"
    return f"{db}.{schema}.{table}"


def alert_triage_view_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    view: str = "OVERWATCH_ALERT_TRIAGE_V",
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(view)}"
    return f"{db}.{schema}.{view}"


def alert_delivery_log_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_DELIVERY_LOG_TABLE,
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"
    return f"{db}.{schema}.{table}"


def alert_rule_audit_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_RULE_AUDIT_TABLE,
    *,
    quoted: bool = False,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"
    return f"{db}.{schema}.{table}"


def alert_environment_values(environment: str | None) -> list[str]:
    env = str(environment or get_active_environment() or "ALL").upper()
    if env == "ALL":
        return []
    if env == "DEV_ALL":
        return [
            "DEV_ALL",
            "ALFA_EDW_DEV",
            "ALFA_EDW_SAN",
            "ALFA_EDW_PHX",
            "ALFA_EDW_SEA",
            "ALFA_EDW_SIT",
            "OTHER ALFA NON-PROD",
        ]
    return [str(environment or "").strip()]


def normalize_alert_severity(value: Any) -> str:
    severity = str(value or "Medium").strip().title()
    if severity.upper() == "CRITICAL":
        return "Critical"
    if severity.upper() == "HIGH":
        return "High"
    if severity.upper() == "LOW":
        return "Low"
    return "Medium"


def normalize_alert_status(value: Any) -> str:
    status = str(value or "New").strip().replace("_", " ").title()
    if status.upper() in {"EMAIL READY", "EMAIL_READY"}:
        return "Email Ready"
    if status.upper() in {"EMAIL QUEUED", "EMAIL_QUEUED"}:
        return "Email Queued"
    if status.upper() in {"IN PROGRESS", "IN_PROGRESS"}:
        return "In Progress"
    if status.upper() in {"RESOLVED", "FIXED"}:
        return "Fixed"
    if status.upper() == "IGNORED":
        return "Ignored"
    if not status:
        return "New"
    return status


def alert_severity_rank(value: Any) -> int:
    return {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}.get(
        normalize_alert_severity(value),
        4,
    )


def alert_rule_catalog() -> pd.DataFrame:
    return pd.DataFrame(DEFAULT_ALERT_RULES)


def normalize_alert_rule_frame(df: pd.DataFrame, *, source: str = "Static Default") -> pd.DataFrame:
    """Normalize alert rule rows from Snowflake or built-in defaults."""
    columns = [
        "RULE_ID",
        "CATEGORY",
        "ALERT_TYPE",
        "DEFAULT_SEVERITY",
        "SLA_HOURS",
        "OWNER",
        "ROUTE",
        "RUNBOOK",
        "IS_ACTIVE",
        "UPDATED_AT",
        "UPDATED_BY",
        "RULE_SOURCE",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)
    view = df.copy()
    defaults = {
        "RULE_ID": "",
        "CATEGORY": "Alert",
        "ALERT_TYPE": "Alert",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA",
        "ROUTE": "Alert Center",
        "RUNBOOK": "Review alert evidence and route confirmed findings to the DBA action queue.",
        "IS_ACTIVE": True,
        "UPDATED_AT": "",
        "UPDATED_BY": "",
        "RULE_SOURCE": source,
    }
    for column, default in defaults.items():
        if column not in view.columns:
            view[column] = default
        else:
            view[column] = view[column].fillna(default)
    view["DEFAULT_SEVERITY"] = view["DEFAULT_SEVERITY"].apply(normalize_alert_severity)
    view["SLA_HOURS"] = pd.to_numeric(view["SLA_HOURS"], errors="coerce").fillna(24).clip(lower=1, upper=168).astype(int)
    view["IS_ACTIVE"] = view["IS_ACTIVE"].apply(lambda value: str(value).strip().upper() not in {"FALSE", "0", "NO", "N"})
    return view[columns]


def load_alert_rule_catalog(section: str = "Alert Center") -> pd.DataFrame:
    """Load configurable alert rules, falling back to built-in defaults."""
    defaults = normalize_alert_rule_frame(alert_rule_catalog(), source="Static Default")
    table = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.OVERWATCH_ALERT_RULES"
    try:
        db_rules = run_query(f"""
            SELECT
                RULE_ID,
                CATEGORY,
                ALERT_TYPE,
                DEFAULT_SEVERITY,
                SLA_HOURS,
                OWNER,
                ROUTE,
                RUNBOOK,
                IS_ACTIVE,
                UPDATED_AT,
                UPDATED_BY,
                'Database' AS RULE_SOURCE
            FROM {table}
            ORDER BY IS_ACTIVE DESC, SLA_HOURS ASC, CATEGORY, ALERT_TYPE
        """, ttl_key="alert_rule_catalog", tier="recent", section=section)
    except Exception:
        db_rules = pd.DataFrame()

    configured = normalize_alert_rule_frame(db_rules, source="Database")
    if configured.empty:
        return defaults
    configured_ids = set(configured["RULE_ID"].fillna("").astype(str).str.upper())
    missing_defaults = defaults[~defaults["RULE_ID"].fillna("").astype(str).str.upper().isin(configured_ids)]
    return pd.concat([configured, missing_defaults], ignore_index=True).sort_values(
        ["IS_ACTIVE", "SLA_HOURS", "CATEGORY", "ALERT_TYPE"],
        ascending=[False, True, True, True],
    )


def build_alert_rule_audit_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    return f"""CREATE TABLE IF NOT EXISTS {alert_rule_audit_fqn(db=db, schema=schema, quoted=True)} (
    AUDIT_ID               NUMBER AUTOINCREMENT PRIMARY KEY,
    AUDIT_TS               TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    RULE_ID                VARCHAR(200),
    ACTION                 VARCHAR(40),
    PRIOR_DEFAULT_SEVERITY VARCHAR(20),
    NEW_DEFAULT_SEVERITY   VARCHAR(20),
    PRIOR_SLA_HOURS        NUMBER,
    NEW_SLA_HOURS          NUMBER,
    PRIOR_OWNER            VARCHAR(200),
    NEW_OWNER              VARCHAR(200),
    PRIOR_ROUTE            VARCHAR(200),
    NEW_ROUTE              VARCHAR(200),
    PRIOR_RUNBOOK          VARCHAR(2000),
    NEW_RUNBOOK            VARCHAR(2000),
    PRIOR_IS_ACTIVE        BOOLEAN,
    NEW_IS_ACTIVE          BOOLEAN,
    CHANGED_BY             VARCHAR(200),
    CHANGE_REASON          VARCHAR(2000)
);"""


def build_alert_rule_audit_insert_sql(
    *,
    rule_id: str,
    default_severity: str,
    sla_hours: int,
    owner: str,
    route: str,
    runbook: str,
    is_active: bool = True,
    actor: str = "OVERWATCH",
    reason: str = "Rule updated from Alert Center.",
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    rule = str(rule_id or "").strip().upper()
    return f"""
INSERT INTO {alert_rule_audit_fqn(db=db, schema=schema, quoted=True)}
    (RULE_ID, ACTION, PRIOR_DEFAULT_SEVERITY, NEW_DEFAULT_SEVERITY, PRIOR_SLA_HOURS, NEW_SLA_HOURS,
     PRIOR_OWNER, NEW_OWNER, PRIOR_ROUTE, NEW_ROUTE, PRIOR_RUNBOOK, NEW_RUNBOOK, PRIOR_IS_ACTIVE,
     NEW_IS_ACTIVE, CHANGED_BY, CHANGE_REASON)
SELECT
    RULE_ID,
    'UPDATE',
    DEFAULT_SEVERITY,
    {sql_literal(normalize_alert_severity(default_severity), 20)},
    SLA_HOURS,
    {int(sla_hours)},
    OWNER,
    {sql_literal(owner, 200)},
    ROUTE,
    {sql_literal(route, 200)},
    RUNBOOK,
    {sql_literal(runbook, 2000)},
    IS_ACTIVE,
    {'TRUE' if is_active else 'FALSE'},
    {sql_literal(actor, 200)},
    {sql_literal(reason, 2000)}
FROM {safe_identifier(db)}.{safe_identifier(schema)}.OVERWATCH_ALERT_RULES
WHERE RULE_ID = {sql_literal(rule, 200)}
""".strip()


def load_alert_rule_audit(section: str = "Alert Center", limit: int = 100) -> pd.DataFrame:
    """Load recent alert rule changes for DBA audit review."""
    limit = max(1, min(int(limit or 100), 1000))
    try:
        return run_query(f"""
            SELECT
                AUDIT_TS,
                RULE_ID,
                ACTION,
                PRIOR_DEFAULT_SEVERITY,
                NEW_DEFAULT_SEVERITY,
                PRIOR_SLA_HOURS,
                NEW_SLA_HOURS,
                PRIOR_OWNER,
                NEW_OWNER,
                PRIOR_ROUTE,
                NEW_ROUTE,
                CHANGED_BY,
                CHANGE_REASON
            FROM {alert_rule_audit_fqn(quoted=True)}
            ORDER BY AUDIT_TS DESC
            LIMIT {limit}
        """, ttl_key=f"alert_rule_audit_{limit}", tier="recent", section=section)
    except Exception:
        return pd.DataFrame()


def build_alert_rule_update_sql(
    *,
    rule_id: str,
    default_severity: str,
    sla_hours: int,
    owner: str,
    route: str,
    runbook: str,
    is_active: bool = True,
    actor: str = "OVERWATCH",
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    rule = str(rule_id or "").strip().upper()
    if not rule:
        raise ValueError("Alert rule id is required.")
    try:
        sla_int = int(sla_hours)
    except Exception as exc:
        raise ValueError("SLA hours must be a number.") from exc
    if sla_int < 1 or sla_int > 168:
        raise ValueError("SLA hours must be between 1 and 168.")
    if not str(owner or "").strip():
        raise ValueError("Owner is required.")
    if not str(route or "").strip():
        raise ValueError("Route is required.")
    if len(str(runbook or "").strip()) < 15:
        raise ValueError("Runbook must explain the operator handling path.")

    return f"""
UPDATE {safe_identifier(db)}.{safe_identifier(schema)}.OVERWATCH_ALERT_RULES
SET
    DEFAULT_SEVERITY = {sql_literal(normalize_alert_severity(default_severity), 20)},
    SLA_HOURS = {sla_int},
    OWNER = {sql_literal(owner, 200)},
    ROUTE = {sql_literal(route, 200)},
    RUNBOOK = {sql_literal(runbook, 2000)},
    IS_ACTIVE = {'TRUE' if is_active else 'FALSE'},
    UPDATED_AT = CURRENT_TIMESTAMP(),
    UPDATED_BY = {sql_literal(actor, 200)}
WHERE RULE_ID = {sql_literal(rule, 200)}
""".strip()


def update_alert_rule(
    session,
    *,
    rule_id: str,
    default_severity: str,
    sla_hours: int,
    owner: str,
    route: str,
    runbook: str,
    is_active: bool = True,
    actor: str = "OVERWATCH",
    reason: str = "Rule updated from Alert Center.",
) -> None:
    update_sql = build_alert_rule_update_sql(
        rule_id=rule_id,
        default_severity=default_severity,
        sla_hours=sla_hours,
        owner=owner,
        route=route,
        runbook=runbook,
        is_active=is_active,
        actor=actor,
    )
    session.sql(build_alert_rule_audit_ddl()).collect()
    session.sql(build_alert_rule_audit_insert_sql(
        rule_id=rule_id,
        default_severity=default_severity,
        sla_hours=sla_hours,
        owner=owner,
        route=route,
        runbook=runbook,
        is_active=is_active,
        actor=actor,
        reason=reason,
    )).collect()
    session.sql(update_sql).collect()


def _nonclosed_alerts(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if "STATUS" not in df.columns:
        return df.copy()
    return df[~df["STATUS"].apply(lambda value: _status_key(value) in ALERT_CLOSED_STATUSES)].copy()


def alert_sla_hours(severity: Any, alert_type: Any = "") -> int:
    severity_text = normalize_alert_severity(severity)
    catalog = alert_rule_catalog()
    type_text = str(alert_type or "").strip().upper()
    if type_text and not catalog.empty:
        match = catalog[catalog["ALERT_TYPE"].astype(str).str.upper() == type_text]
        if not match.empty:
            return int(match.iloc[0]["SLA_HOURS"])
    return int(ALERT_SLA_HOURS.get(severity_text, 24))


def annotate_alert_triage_frame(df: pd.DataFrame, *, now: Any | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.copy()
    if "ALERT_TS" not in view.columns:
        return view

    existing_age = pd.to_numeric(view["ALERT_AGE_HOURS"], errors="coerce") if "ALERT_AGE_HOURS" in view.columns else pd.Series(dtype=float)
    if "ALERT_AGE_HOURS" in view.columns and existing_age.notna().any():
        view["ALERT_AGE_HOURS"] = existing_age.fillna(0).clip(lower=0).round(1)
    else:
        now_ts = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
        alert_ts = pd.to_datetime(view["ALERT_TS"], errors="coerce")
        age_hours = (now_ts - alert_ts).dt.total_seconds() / 3600
        view["ALERT_AGE_HOURS"] = age_hours.fillna(0).clip(lower=0).round(1)
    if "SLA_TARGET_HOURS" in view.columns:
        fallback_sla = view.apply(
            lambda row: alert_sla_hours(row.get("SEVERITY"), row.get("ALERT_TYPE") or row.get("CATEGORY")),
            axis=1,
        )
        view["SLA_TARGET_HOURS"] = pd.to_numeric(view["SLA_TARGET_HOURS"], errors="coerce").fillna(fallback_sla).astype(int)
    else:
        view["SLA_TARGET_HOURS"] = view.apply(
            lambda row: alert_sla_hours(row.get("SEVERITY"), row.get("ALERT_TYPE") or row.get("CATEGORY")),
            axis=1,
        )
    status_key = view.get("STATUS", pd.Series(["New"] * len(view), index=view.index)).apply(_status_rank)
    closed_mask = view.get("STATUS", pd.Series(["New"] * len(view), index=view.index)).apply(
        lambda value: _status_key(value) in ALERT_CLOSED_STATUSES
    )
    existing_sla_state = (
        view["SLA_STATE"].fillna("").astype(str).str.strip()
        if "SLA_STATE" in view.columns
        else pd.Series(dtype=str)
    )
    if "SLA_STATE" not in view.columns or not existing_sla_state.ne("").any():
        overdue_mask = (view["ALERT_AGE_HOURS"] > view["SLA_TARGET_HOURS"]) & ~closed_mask
        due_soon_mask = (
            (view["ALERT_AGE_HOURS"] >= view["SLA_TARGET_HOURS"] * 0.75)
            & ~overdue_mask
            & ~closed_mask
        )
        view["SLA_STATE"] = "Within SLA"
        view.loc[due_soon_mask, "SLA_STATE"] = "Due Soon"
        view.loc[overdue_mask, "SLA_STATE"] = "Overdue"
        view.loc[closed_mask, "SLA_STATE"] = "Closed"
    else:
        view["SLA_STATE"] = view["SLA_STATE"].fillna("Within SLA")
    if "ESCALATION_TARGET" not in view.columns:
        view["ESCALATION_TARGET"] = view.apply(
            lambda row: (
                "DBA Lead"
                if row.get("SLA_STATE") == "Overdue" and normalize_alert_severity(row.get("SEVERITY")) in {"Critical", "High"}
                else str(row.get("OWNER") or "DBA")
            ),
            axis=1,
        )
    else:
        view["ESCALATION_TARGET"] = view["ESCALATION_TARGET"].fillna(view.get("OWNER", "DBA"))
    view["_SLA_RANK"] = view["SLA_STATE"].map({"Overdue": 0, "Due Soon": 1, "Within SLA": 2, "Closed": 9}).fillna(5)
    if "TRIAGE_PRIORITY" in view.columns:
        view["TRIAGE_PRIORITY"] = pd.to_numeric(view["TRIAGE_PRIORITY"], errors="coerce")
    else:
        view["TRIAGE_PRIORITY"] = pd.NA
    missing_priority = view["TRIAGE_PRIORITY"].isna()
    view.loc[missing_priority, "TRIAGE_PRIORITY"] = (
        view.loc[missing_priority, "SEVERITY"].apply(alert_severity_rank).astype(int) * 100
        + view.loc[missing_priority, "_SLA_RANK"].astype(int) * 10
        + status_key.loc[missing_priority].astype(int)
    )
    view["TRIAGE_PRIORITY"] = view["TRIAGE_PRIORITY"].astype(int)
    return view.drop(columns=["_SLA_RANK"], errors="ignore")


def alert_escalation_candidates(df: pd.DataFrame, *, limit: int = 10) -> pd.DataFrame:
    """Return the alert rows an operator should escalate first."""
    if df is None or df.empty:
        return pd.DataFrame()
    view = annotate_alert_triage_frame(normalize_alert_frame(df))
    view = _nonclosed_alerts(view)
    if view.empty:
        return view
    severity = view["SEVERITY"].apply(normalize_alert_severity).isin(["Critical", "High"])
    sla = view.get("SLA_STATE", pd.Series(["Within SLA"] * len(view), index=view.index)).isin(["Overdue", "Due Soon"])
    owner_gap = view.get("OWNER", pd.Series(["DBA"] * len(view), index=view.index)).fillna("").astype(str).str.upper().isin(
        ["", "DBA", "DBA / FINOPS", "DBA / PLATFORM", "DBA / SECURITY", "DBA / PIPELINE OWNER"]
    )
    candidates = view[severity | sla | owner_gap].copy()
    if candidates.empty:
        candidates = view.head(limit).copy()
    return candidates.sort_values(["TRIAGE_PRIORITY", "ALERT_TS"], ascending=[True, False]).head(limit)


def build_alert_digest_summary(df: pd.DataFrame) -> dict[str, int]:
    if df is None or df.empty:
        return {
            "total": 0,
            "open": 0,
            "critical_high": 0,
            "overdue": 0,
            "due_soon": 0,
            "email_ready": 0,
            "needs_owner": 0,
        }
    view = annotate_alert_triage_frame(normalize_alert_frame(df))
    active = _nonclosed_alerts(view)
    if active.empty:
        return {
            "total": int(len(view)),
            "open": 0,
            "critical_high": 0,
            "overdue": 0,
            "due_soon": 0,
            "email_ready": 0,
            "needs_owner": 0,
        }
    owners = active.get("OWNER", pd.Series(["DBA"] * len(active), index=active.index)).fillna("").astype(str).str.upper()
    delivery = active.get("DELIVERY_STATUS", pd.Series([""] * len(active), index=active.index)).fillna("").astype(str).str.upper()
    return {
        "total": int(len(view)),
        "open": int(len(active)),
        "critical_high": int(active["SEVERITY"].apply(normalize_alert_severity).isin(["Critical", "High"]).sum()),
        "overdue": int(active.get("SLA_STATE", pd.Series([""] * len(active), index=active.index)).eq("Overdue").sum()),
        "due_soon": int(active.get("SLA_STATE", pd.Series([""] * len(active), index=active.index)).eq("Due Soon").sum()),
        "email_ready": int(delivery.str.contains("EMAIL_READY").sum()),
        "needs_owner": int(owners.isin(["", "DBA", "DBA / FINOPS", "DBA / PLATFORM", "DBA / SECURITY", "DBA / PIPELINE OWNER"]).sum()),
    }


def build_alert_digest_subject(
    df: pd.DataFrame,
    *,
    company: str = "ALFA",
    environment: str = "ALL",
) -> str:
    summary = build_alert_digest_summary(df)
    return (
        f"OVERWATCH Alert Digest: {summary['open']} open, "
        f"{summary['overdue']} overdue, {summary['critical_high']} critical/high "
        f"({company} {environment})"
    )


def build_alert_digest_body(
    df: pd.DataFrame,
    *,
    company: str = "ALFA",
    environment: str = "ALL",
    recipient: str = DEFAULT_ALERT_RECIPIENT,
    limit: int = 10,
) -> str:
    summary = build_alert_digest_summary(df)
    candidates = alert_escalation_candidates(df, limit=limit)
    lines = [
        f"To: {recipient}",
        build_alert_digest_subject(df, company=company, environment=environment),
        "",
        "DBA triage summary:",
        f"- Open alerts: {summary['open']}",
        f"- Critical/high alerts: {summary['critical_high']}",
        f"- Overdue alerts: {summary['overdue']}",
        f"- Due soon alerts: {summary['due_soon']}",
        f"- Needs named owner: {summary['needs_owner']}",
        "",
        "Escalate first:",
    ]
    if candidates.empty:
        lines.append("- No open escalation candidates for this scope.")
    else:
        for _, row in candidates.iterrows():
            alert_type = _row_value(row, "ALERT_TYPE", "CATEGORY", default="Alert")
            entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake account")
            severity = normalize_alert_severity(_row_value(row, "SEVERITY", default="Medium"))
            sla_state = _row_value(row, "SLA_STATE", default="Within SLA")
            owner = _row_value(row, "OWNER", default="DBA")
            action = _row_value(row, "SUGGESTED_ACTION", default="Review alert evidence and route to action queue.")
            lines.append(f"- [{severity} / {sla_state}] {alert_type} on {entity}; owner={owner}; action={action}")
    lines.extend([
        "",
        "Required operator handling:",
        "- Route confirmed alerts to the Action Queue.",
        "- Add ticket, owner, approver, and verification evidence before closure.",
        "- Mark false positives Ignored with reason, not silently deleted.",
    ])
    return "\n".join(lines)


def _numeric_alert_ids(df_or_ids: Any) -> list[int]:
    if df_or_ids is None:
        return []
    if isinstance(df_or_ids, pd.DataFrame):
        if "ALERT_ID" not in df_or_ids.columns:
            return []
        values = df_or_ids["ALERT_ID"].dropna().astype(str).tolist()
    elif isinstance(df_or_ids, pd.Series):
        values = df_or_ids.dropna().astype(str).tolist()
    else:
        values = list(df_or_ids)
    clean: list[int] = []
    for value in values:
        text = str(value).strip()
        if text.isdigit():
            clean.append(int(text))
    return list(dict.fromkeys(clean))


def _status_rank(value: Any) -> int:
    status = str(value or "New").strip().upper().replace(" ", "_")
    if status in {"NEW", "EMAIL_READY", "EMAIL_QUEUED", "OPEN", "ACTIVE", "PENDING"}:
        return 0
    if status in {"ACKNOWLEDGED", "IN_PROGRESS"}:
        return 1
    if status in {"FIXED", "RESOLVED"}:
        return 3
    if status == "IGNORED":
        return 4
    return 2


def _status_key(value: Any) -> str:
    return str(value or "New").strip().upper().replace(" ", "_")


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


def _first_series(df: pd.DataFrame, *columns: str, default: Any = "") -> pd.Series:
    for column in columns:
        if column in df.columns:
            return df[column]
    return pd.Series([default] * len(df), index=df.index)


def _coalesce_sql(columns: set[str], *candidates: str, default: str = "''") -> str:
    exprs = [candidate.upper() for candidate in candidates if candidate.upper() in columns]
    if not exprs:
        return default
    exprs.append(default)
    return f"COALESCE({', '.join(exprs)})"


def _first_col(columns: set[str], *candidates: str) -> str | None:
    for col in candidates:
        col_upper = col.upper()
        if col_upper in columns:
            return col_upper
    return None


def _company_scope_alert_rows(df: pd.DataFrame, company: str) -> pd.DataFrame:
    if df.empty or company == "ALL":
        return df

    def allowed(row: pd.Series) -> bool:
        values = [
            _row_value(row, "WAREHOUSE_NAME"),
            _row_value(row, "DATABASE_NAME"),
            _row_value(row, "ENTITY_NAME", "ENTITY"),
        ]
        concrete = [value for value in values if value and value.upper() != "SNOWFLAKE ACCOUNT"]
        if not concrete:
            return True
        return any(
            company_value_allowed(value, "warehouse", company)
            or company_value_allowed(value, "database", company)
            or company_value_allowed(value, "user", company)
            for value in concrete
        )

    return df[df.apply(allowed, axis=1)]


def _environment_scope_alert_rows(df: pd.DataFrame, environment: str | None) -> pd.DataFrame:
    if df.empty:
        return df
    env = str(environment or get_active_environment() or "ALL")
    if env.upper() == "ALL" or "ENVIRONMENT" not in df.columns:
        return df

    def allowed(row: pd.Series) -> bool:
        row_env = _row_value(row, "ENVIRONMENT")
        database_name = _row_value(row, "DATABASE_NAME")
        if not database_name and row_env.upper() in {"", "NO DATABASE CONTEXT", "NO_DATABASE_CONTEXT"}:
            return True
        return environment_value_allowed(row_env, environment=env)

    return df[df.apply(allowed, axis=1)]


def build_alert_email_subject(row: pd.Series | dict, company: str = "ALFA") -> str:
    severity = normalize_alert_severity(_row_value(row, "SEVERITY", default="Medium"))
    category = _row_value(row, "CATEGORY", "ALERT_TYPE", "DOMAIN", "SIGNAL", default="Alert")
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake account")
    company_text = _row_value(row, "COMPANY", default=company)
    return f"OVERWATCH {severity}: {category} - {entity} ({company_text})"


def build_alert_email_body(row: pd.Series | dict, company: str = "ALFA") -> str:
    company_text = _row_value(row, "COMPANY", default=company)
    environment = _row_value(row, "ENVIRONMENT", default="No Database Context")
    category = _row_value(row, "CATEGORY", "ALERT_TYPE", "DOMAIN", "SIGNAL", default="Alert")
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake account")
    severity = normalize_alert_severity(_row_value(row, "SEVERITY", default="Medium"))
    message = _row_value(row, "MESSAGE", "DETAIL", default="No alert detail captured.")
    action = _row_value(row, "SUGGESTED_ACTION", "NEXT_ACTION", default="Review the Alert Center issue and route it through the DBA action queue.")
    proof = _row_value(row, "PROOF_QUERY", default="No proof query captured.")
    return "\n".join([
        f"Company: {company_text}",
        f"Environment: {environment}",
        f"Severity: {severity}",
        f"Alert: {category}",
        f"Entity: {entity}",
        "",
        "Detail:",
        message,
        "",
        "Next action:",
        action,
        "",
        "Proof query:",
        proof,
    ])


def normalize_alert_frame(
    df: pd.DataFrame,
    *,
    company: str = "ALFA",
    default_email: str = DEFAULT_ALERT_RECIPIENT,
) -> pd.DataFrame:
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
        "DELIVERY_METHOD": ALERT_DELIVERY_METHOD,
        "EMAIL_TARGET": default_email,
        "DELIVERY_TARGET": default_email,
        "DELIVERY_STATUS": "EMAIL_READY",
        "PROOF_QUERY": "",
    }
    for column, default in defaults.items():
        if column not in view.columns:
            view[column] = default
        else:
            view[column] = view[column].fillna(default)
    view["SEVERITY"] = view["SEVERITY"].apply(normalize_alert_severity)
    view["STATUS"] = view["STATUS"].apply(normalize_alert_status)
    view["EMAIL_TARGET"] = view["EMAIL_TARGET"].replace("", default_email).fillna(default_email)
    if "EMAIL_SUBJECT" not in view.columns:
        view["EMAIL_SUBJECT"] = view.apply(lambda row: build_alert_email_subject(row, company), axis=1)
    else:
        missing = view["EMAIL_SUBJECT"].fillna("").astype(str).str.strip() == ""
        view.loc[missing, "EMAIL_SUBJECT"] = view.loc[missing].apply(
            lambda row: build_alert_email_subject(row, company),
            axis=1,
        )
    if "EMAIL_BODY" not in view.columns:
        view["EMAIL_BODY"] = view.apply(lambda row: build_alert_email_body(row, company), axis=1)
    else:
        missing = view["EMAIL_BODY"].fillna("").astype(str).str.strip() == ""
        view.loc[missing, "EMAIL_BODY"] = view.loc[missing].apply(
            lambda row: build_alert_email_body(row, company),
            axis=1,
        )
    return view


def load_alert_history(
    session,
    *,
    company: str = "ALFA",
    environment: str | None = None,
    days: int = 7,
    limit: int = 200,
    section: str = "Alert Center",
) -> pd.DataFrame:
    """Load alert history from current or legacy OVERWATCH alert schemas."""
    requested = [
        "ALERT_ID",
        "ALERT_TS",
        "ALERT_DATE",
        "CREATED_AT",
        "COMPANY",
        "ENVIRONMENT",
        "DATABASE_NAME",
        "SCHEMA_NAME",
        "WAREHOUSE_NAME",
        "CATEGORY",
        "ALERT_TYPE",
        "SEVERITY",
        "ENTITY_NAME",
        "ENTITY",
        "MESSAGE",
        "DETAIL",
        "PROOF_QUERY",
        "SUGGESTED_ACTION",
        "OWNER",
        "STATUS",
        "ACKNOWLEDGED_BY",
        "ACKNOWLEDGED_AT",
        "DELIVERY_METHOD",
        "DELIVERY_TARGET",
        "EMAIL_TARGET",
        "EMAIL_SUBJECT",
        "EMAIL_BODY",
        "DELIVERY_STATUS",
        "RESOLVED",
        "LAST_DELIVERY_AT",
        "LAST_DELIVERY_BY",
        "DELIVERY_LOG_COUNT",
        "ESCALATED_TO",
        "ESCALATED_AT",
        "ESCALATION_ACK_BY",
        "ESCALATION_ACK_AT",
        "ESCALATION_ACK_NOTE",
        "SLA_TARGET_HOURS",
        "ALERT_AGE_HOURS",
        "ALERT_ROUTE",
        "ALERT_RUNBOOK",
        "SLA_STATE",
        "ESCALATION_TARGET",
        "TRIAGE_PRIORITY",
    ]
    probe_table = alert_triage_view_fqn()
    table = alert_triage_view_fqn(quoted=True)
    columns = set(filter_existing_columns(session, probe_table, requested))
    if not columns:
        probe_table = alert_table_fqn()
        table = alert_table_fqn(quoted=True)
        columns = set(filter_existing_columns(session, probe_table, requested))
    if not columns:
        raise ValueError(f"{probe_table} is unavailable or has no recognized alert columns.")

    limit = max(1, min(int(limit), 5000))
    days = max(1, min(int(days), 365))
    ts_col = _first_col(columns, "ALERT_TS", "ALERT_DATE", "CREATED_AT") or "CURRENT_TIMESTAMP()"
    alert_id_expr = "ALERT_ID" if "ALERT_ID" in columns else "UUID_STRING()"
    company_expr = "COMPANY" if "COMPANY" in columns else f"{sql_literal(company)} AS COMPANY"
    status_default = "'New'"
    if "ACKNOWLEDGED_AT" in columns:
        status_default = "CASE WHEN ACKNOWLEDGED_AT IS NOT NULL THEN 'Acknowledged' ELSE 'New' END"
    if "RESOLVED" in columns:
        ack_part = " WHEN ACKNOWLEDGED_AT IS NOT NULL THEN 'Acknowledged'" if "ACKNOWLEDGED_AT" in columns else ""
        status_default = f"CASE WHEN COALESCE(RESOLVED, FALSE) THEN 'Fixed'{ack_part} ELSE 'New' END"
    status_expr = f"COALESCE(STATUS, {status_default})" if "STATUS" in columns else status_default

    ts_filter = "" if ts_col == "CURRENT_TIMESTAMP()" else f"AND {ts_col} >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())"
    company_filter = "" if company == "ALL" or "COMPANY" not in columns else f"AND COMPANY = {sql_literal(company)}"
    environment_filter = ""
    env_values = alert_environment_values(environment)
    if env_values and "ENVIRONMENT" in columns:
        env_literals = ", ".join(sql_literal(value) for value in env_values)
        environment_filter = (
            f"AND (UPPER(ENVIRONMENT) IN ({env_literals.upper()}) "
            "OR ENVIRONMENT IS NULL "
            "OR UPPER(ENVIRONMENT) IN ('NO DATABASE CONTEXT', 'NO_DATABASE_CONTEXT'))"
        )

    df = run_query(f"""
        SELECT
            {alert_id_expr} AS ALERT_ID,
            {ts_col} AS ALERT_TS,
            {company_expr},
            {_coalesce_sql(columns, "ENVIRONMENT", default="'No Database Context'")} AS ENVIRONMENT,
            {_coalesce_sql(columns, "DATABASE_NAME", default="NULL")} AS DATABASE_NAME,
            {_coalesce_sql(columns, "SCHEMA_NAME", default="NULL")} AS SCHEMA_NAME,
            {_coalesce_sql(columns, "WAREHOUSE_NAME", default="NULL")} AS WAREHOUSE_NAME,
            {_coalesce_sql(columns, "CATEGORY", "ALERT_TYPE", default="'Alert'")} AS CATEGORY,
            {_coalesce_sql(columns, "ALERT_TYPE", "CATEGORY", default="'Alert'")} AS ALERT_TYPE,
            {_coalesce_sql(columns, "SEVERITY", default="'Medium'")} AS SEVERITY,
            {_coalesce_sql(columns, "ENTITY_NAME", "ENTITY", "WAREHOUSE_NAME", "DATABASE_NAME", default="'Snowflake account'")} AS ENTITY_NAME,
            {_coalesce_sql(columns, "ENTITY", "ENTITY_NAME", "WAREHOUSE_NAME", "DATABASE_NAME", default="'Snowflake account'")} AS ENTITY,
            {_coalesce_sql(columns, "MESSAGE", "DETAIL", default="''")} AS MESSAGE,
            {_coalesce_sql(columns, "DETAIL", "MESSAGE", default="''")} AS DETAIL,
            {_coalesce_sql(columns, "SUGGESTED_ACTION", default="'Review the Alert Center issue and route it through the DBA action queue.'")} AS SUGGESTED_ACTION,
            {_coalesce_sql(columns, "PROOF_QUERY", default="''")} AS PROOF_QUERY,
            {_coalesce_sql(columns, "OWNER", default="'DBA'")} AS OWNER,
            {status_expr} AS STATUS,
            {_coalesce_sql(columns, "DELIVERY_METHOD", default=sql_literal(ALERT_DELIVERY_METHOD))} AS DELIVERY_METHOD,
            {_coalesce_sql(columns, "DELIVERY_TARGET", "EMAIL_TARGET", default=sql_literal(DEFAULT_ALERT_RECIPIENT))} AS DELIVERY_TARGET,
            {_coalesce_sql(columns, "EMAIL_TARGET", "DELIVERY_TARGET", default=sql_literal(DEFAULT_ALERT_RECIPIENT))} AS EMAIL_TARGET,
            {_coalesce_sql(columns, "EMAIL_SUBJECT", default="''")} AS EMAIL_SUBJECT,
            {_coalesce_sql(columns, "EMAIL_BODY", default="''")} AS EMAIL_BODY,
            {_coalesce_sql(columns, "DELIVERY_STATUS", default="'EMAIL_READY'")} AS DELIVERY_STATUS,
            {_coalesce_sql(columns, "LAST_DELIVERY_AT", default="NULL")} AS LAST_DELIVERY_AT,
            {_coalesce_sql(columns, "LAST_DELIVERY_BY", default="''")} AS LAST_DELIVERY_BY,
            {_coalesce_sql(columns, "DELIVERY_LOG_COUNT", default="0")} AS DELIVERY_LOG_COUNT,
            {_coalesce_sql(columns, "ESCALATED_TO", default="NULL")} AS ESCALATED_TO,
            {_coalesce_sql(columns, "ESCALATED_AT", default="NULL")} AS ESCALATED_AT,
            {_coalesce_sql(columns, "ESCALATION_ACK_BY", default="''")} AS ESCALATION_ACK_BY,
            {_coalesce_sql(columns, "ESCALATION_ACK_AT", default="NULL")} AS ESCALATION_ACK_AT,
            {_coalesce_sql(columns, "ESCALATION_ACK_NOTE", default="''")} AS ESCALATION_ACK_NOTE,
            {_coalesce_sql(columns, "SLA_TARGET_HOURS", default="NULL")} AS SLA_TARGET_HOURS,
            {_coalesce_sql(columns, "ALERT_AGE_HOURS", default="NULL")} AS ALERT_AGE_HOURS,
            {_coalesce_sql(columns, "ALERT_ROUTE", default="''")} AS ALERT_ROUTE,
            {_coalesce_sql(columns, "ALERT_RUNBOOK", default="''")} AS ALERT_RUNBOOK,
            {_coalesce_sql(columns, "SLA_STATE", default="NULL")} AS SLA_STATE,
            {_coalesce_sql(columns, "ESCALATION_TARGET", default="NULL")} AS ESCALATION_TARGET,
            {_coalesce_sql(columns, "TRIAGE_PRIORITY", default="NULL")} AS TRIAGE_PRIORITY
        FROM {table}
        WHERE 1 = 1
          {ts_filter}
          {company_filter}
          {environment_filter}
        ORDER BY ALERT_TS DESC
        LIMIT {limit}
    """, ttl_key=f"alert_history_{company}_{environment or get_active_environment()}_{days}_{limit}", tier="recent", section=section)

    if company != "ALL" and "COMPANY" not in columns:
        df = _company_scope_alert_rows(df, company)
    df = _environment_scope_alert_rows(df, environment)
    return annotate_alert_triage_frame(normalize_alert_frame(df, company=company))


def normalize_alert_issue_rows(df_alerts: pd.DataFrame) -> pd.DataFrame:
    if df_alerts is None or df_alerts.empty:
        return pd.DataFrame(columns=ISSUE_COLUMNS)
    alerts = normalize_alert_frame(df_alerts)
    view = pd.DataFrame(index=alerts.index)
    view["ISSUE_SOURCE"] = "Alert History"
    view["SEVERITY"] = alerts["SEVERITY"].apply(normalize_alert_severity)
    view["STATUS"] = alerts["STATUS"].apply(normalize_alert_status)
    view["DOMAIN"] = alerts["CATEGORY"].fillna("Alert").astype(str)
    view["SIGNAL"] = alerts["ALERT_TYPE"].fillna(alerts["CATEGORY"]).astype(str)
    view["ENTITY"] = alerts["ENTITY_NAME"].fillna("Snowflake account").astype(str)
    view["DETAIL"] = alerts["MESSAGE"].fillna(alerts.get("DETAIL", "")).astype(str)
    view["NEXT_ACTION"] = alerts["SUGGESTED_ACTION"].fillna("").astype(str)
    view["OWNER"] = alerts["OWNER"].fillna("DBA").astype(str)
    view["EMAIL_TARGET"] = alerts["EMAIL_TARGET"].fillna(DEFAULT_ALERT_RECIPIENT).astype(str)
    view["DELIVERY_STATUS"] = alerts["DELIVERY_STATUS"].fillna("EMAIL_READY").astype(str)
    view["ROUTE"] = view["DOMAIN"].map({
        "Cost Control": "Cost & Contract",
        "Reliability": "Workload Operations",
        "Security": "Security Posture",
        "Change Control": "Change & Drift",
        "Capacity": "Warehouse Health",
    }).fillna("Alert Center")
    view["WORKFLOW"] = view["DOMAIN"]
    view["EVENT_TS"] = alerts.get("ALERT_TS", pd.Series([""] * len(alerts), index=alerts.index))
    return view[ISSUE_COLUMNS]


def normalize_action_issue_rows(df_queue: pd.DataFrame) -> pd.DataFrame:
    if df_queue is None or df_queue.empty:
        return pd.DataFrame(columns=ISSUE_COLUMNS)
    queue = df_queue.copy()
    status = _first_series(queue, "STATUS", default="New").fillna("New").astype(str)
    open_mask = ~status.str.title().isin(["Fixed", "Ignored"])
    queue = queue[open_mask]
    if queue.empty:
        return pd.DataFrame(columns=ISSUE_COLUMNS)

    view = pd.DataFrame(index=queue.index)
    view["ISSUE_SOURCE"] = "Action Queue"
    view["SEVERITY"] = _first_series(queue, "SEVERITY", default="Medium").apply(normalize_alert_severity)
    view["STATUS"] = _first_series(queue, "STATUS", default="New").apply(normalize_alert_status)
    view["DOMAIN"] = _first_series(queue, "CATEGORY", default="Action Queue").astype(str)
    view["SIGNAL"] = _first_series(queue, "CATEGORY", default="Queued DBA action").astype(str)
    view["ENTITY"] = _first_series(queue, "ENTITY_NAME", "ENTITY", default="Snowflake account").astype(str)
    view["DETAIL"] = _first_series(queue, "FINDING", default="").astype(str)
    view["NEXT_ACTION"] = _first_series(queue, "NEXT_ACTION", "RECOMMENDED_ACTION", default="Work this queued DBA action.").astype(str)
    view["OWNER"] = _first_series(queue, "OWNER", default="DBA").astype(str)
    view["EMAIL_TARGET"] = DEFAULT_ALERT_RECIPIENT
    view["DELIVERY_STATUS"] = "Queue Item"
    view["ROUTE"] = _first_series(queue, "SOURCE", default="Action Queue").astype(str)
    view["WORKFLOW"] = _first_series(queue, "CATEGORY", default="Action Queue").astype(str)
    view["EVENT_TS"] = _first_series(queue, "UPDATED_AT", "CREATED_AT", default="")
    return view[ISSUE_COLUMNS]


def normalize_control_room_issue_rows(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame(columns=ISSUE_COLUMNS)
    rows = exceptions.copy()
    view = pd.DataFrame(index=rows.index)
    view["ISSUE_SOURCE"] = "Control Room Signal"
    view["SEVERITY"] = _first_series(rows, "SEVERITY", "Severity", default="Medium").apply(normalize_alert_severity)
    view["STATUS"] = "Active"
    view["DOMAIN"] = _first_series(rows, "DOMAIN", "Route", default="DBA Control Room").astype(str)
    view["SIGNAL"] = _first_series(rows, "SIGNAL", "Signal", default="Control-room exception").astype(str)
    view["ENTITY"] = _first_series(rows, "ENTITY", "Entity", default="Snowflake account").astype(str)
    view["DETAIL"] = _first_series(rows, "DETAIL", "Evidence", default="").astype(str)
    view["NEXT_ACTION"] = _first_series(rows, "NEXT_ACTION", "Action", default="Review the control-room evidence.").astype(str)
    view["OWNER"] = "DBA"
    view["EMAIL_TARGET"] = DEFAULT_ALERT_RECIPIENT
    view["DELIVERY_STATUS"] = "Dashboard Signal"
    view["ROUTE"] = _first_series(rows, "ROUTE", "Route", default="DBA Control Room").astype(str)
    view["WORKFLOW"] = _first_series(rows, "WORKFLOW", "Workflow", default="").astype(str)
    view["EVENT_TS"] = ""
    return view[ISSUE_COLUMNS]


def build_dashboard_issue_rows(
    exceptions: pd.DataFrame | None = None,
    alerts: pd.DataFrame | None = None,
    queue: pd.DataFrame | None = None,
) -> pd.DataFrame:
    frames = [
        normalize_alert_issue_rows(alerts if alerts is not None else pd.DataFrame()),
        normalize_action_issue_rows(queue if queue is not None else pd.DataFrame()),
        normalize_control_room_issue_rows(exceptions if exceptions is not None else pd.DataFrame()),
    ]
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame(columns=ISSUE_COLUMNS)
    combined = pd.concat(frames, ignore_index=True)
    combined["_SEVERITY_RANK"] = combined["SEVERITY"].apply(alert_severity_rank)
    combined["_STATUS_RANK"] = combined["STATUS"].apply(_status_rank)
    combined["_EVENT_TS"] = pd.to_datetime(combined["EVENT_TS"], errors="coerce")
    combined = combined.sort_values(
        ["_SEVERITY_RANK", "_STATUS_RANK", "_EVENT_TS", "ISSUE_SOURCE", "SIGNAL"],
        ascending=[True, True, False, True, True],
    )
    return combined.drop(columns=["_SEVERITY_RANK", "_STATUS_RANK", "_EVENT_TS"], errors="ignore")


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


def _alert_is_cost_verifier(row: pd.Series | dict) -> bool:
    signal = " ".join([
        _row_value(row, "CATEGORY", default=""),
        _row_value(row, "ALERT_TYPE", default=""),
        _row_value(row, "ENTITY_NAME", "ENTITY", default=""),
        _row_value(row, "MESSAGE", "DETAIL", default=""),
    ]).upper()
    return "COST SAVINGS VERIFICATION" in signal or "OVERWATCH_COST_SAVINGS_VERIFY" in signal


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
FROM {alert_table_fqn(quoted=True)}
WHERE ALERT_ID = {int(alert_id)}
LIMIT 50
""".strip()
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake account")
    return f"""
SELECT {columns}
FROM {alert_table_fqn(quoted=True)}
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


def _cost_verifier_verification_query() -> str:
    return """
SELECT DATABASE_NAME, SCHEMA_NAME, NAME, STATE, SCHEDULED_TIME, COMPLETED_TIME, QUERY_ID, ERROR_MESSAGE
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE UPPER(NAME) = 'OVERWATCH_COST_SAVINGS_VERIFY'
ORDER BY SCHEDULED_TIME DESC
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
    status = normalize_alert_status(_row_value(row, "STATUS", default="New")).upper()
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
        f"-- Governed {noun} recovery for {entity}",
        "-- Do not perform manual retry from Alert Center.",
        f"-- Assign owner/approver: {owner}",
        "-- Required order: prove root cause, document ticket, obtain owner approval, then recover from Workload Operations.",
        "-- After recovery, run the read-only verification query attached to this action and paste the result into closure evidence.",
    ])


def _alert_cost_verifier_sql_guidance(row: pd.Series | dict) -> str:
    entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="OVERWATCH_COST_SAVINGS_VERIFY")
    owner = _row_value(row, "OWNER", "ESCALATION_TARGET", default="DBA / FinOps")
    return "\n".join([
        f"-- Governed cost savings verifier recovery for {entity}",
        "-- Do not claim cost savings while the verifier task is failing.",
        f"-- Assign owner/approver: {owner}",
        "-- Required order: inspect TASK_HISTORY, fix verifier privileges/schedule/procedure errors, document the ticket, then verify a clean ledger run.",
        "-- If task recovery requires schedule, resume, or procedure changes, execute from the approved Workload Operations/Admin workflow with audit evidence.",
    ])


def alert_history_to_actions(df_alerts: pd.DataFrame, company: str = "ALFA") -> list[dict]:
    if df_alerts is None or df_alerts.empty:
        return []
    from .action_queue import make_action_id

    actions = []
    alerts = normalize_alert_frame(df_alerts, company=company)
    owner_directory = default_owner_directory()
    for _, row in alerts.head(500).iterrows():
        alert_id = _row_value(row, "ALERT_ID", "ALERT_TS")
        category = _row_value(row, "CATEGORY", "ALERT_TYPE", default="Alert")
        alert_type = _row_value(row, "ALERT_TYPE", "CATEGORY", default=category)
        entity = _row_value(row, "ENTITY_NAME", "ENTITY", default="Snowflake account")
        message = _row_value(row, "MESSAGE", "DETAIL")
        reliability_kind = _alert_reliability_kind(row)
        is_cost_verifier = _alert_is_cost_verifier(row)
        is_recovery = reliability_kind in {"task", "procedure"}
        governed_recovery = is_recovery or is_cost_verifier
        action_category = "Task & Procedure Reliability" if is_recovery else "Cost Control" if is_cost_verifier else category
        entity_type = "Cost Verification Task" if is_cost_verifier else {
            "task": "Task",
            "procedure": "Stored Procedure",
        }.get(reliability_kind, "Alert Entity")
        proof_query = _safe_alert_proof_query(row)
        if is_cost_verifier:
            verification_query = _cost_verifier_verification_query()
        elif is_recovery:
            verification_query = _alert_recovery_verification_query(row, reliability_kind)
        else:
            verification_query = proof_query
        owner = _row_value(row, "OWNER", default="DBA")
        owner_context = resolve_owner_context(
            row,
            directory=owner_directory,
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
            sla_target_hours = float(ALERT_SLA_HOURS.get(normalize_alert_severity(_row_value(row, "SEVERITY", default="Medium")), 24))
        alert_age_hours = _alert_numeric_value(row, "ALERT_AGE_HOURS")
        suggested_action = _row_value(row, "SUGGESTED_ACTION", default="Review the Alert Center issue and route it through the DBA action queue.")
        if is_cost_verifier:
            suggested_action = (
                f"{suggested_action} Keep savings estimated until the verifier task has a clean run ledger, "
                "then re-run closure review in Cost & Contract."
            )
            sql_fix = _alert_cost_verifier_sql_guidance(row)
            recovery_evidence = (
                "Required closure evidence: TASK_HISTORY error/root cause, owner approval, successful verifier task run, "
                f"and refreshed savings verification ledger for {entity}. Alert detail: {message}"
            )
        elif is_recovery:
            suggested_action = (
                f"{suggested_action} Govern recovery through the action queue: assign owner/ticket, prove root cause, "
                "obtain owner approval before manual recovery, and verify the next run."
            )
            sql_fix = _alert_recovery_sql_guidance(row, reliability_kind)
            recovery_evidence = (
                "Required closure evidence: root cause, owner approval, recovery timestamp, and a successful next-run "
                f"verification for {entity}. Alert detail: {message}"
            )
        else:
            sql_fix = "-- Review alert evidence before applying a fix."
            recovery_evidence = ""
        action = {
            "Action ID": make_action_id(action_category if governed_recovery else "Alert", entity, f"{alert_type}|{message}|{alert_id}"),
            "Source": "Alert Center",
            "Severity": normalize_alert_severity(_row_value(row, "SEVERITY", default="Medium")),
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
            "Approval Group": approval_group,
            "Escalation Target": escalation_target,
            "Owner Source": owner_context.get("OWNER_SOURCE", ""),
            "Owner Evidence": owner_context.get("OWNER_EVIDENCE", ""),
        }
        if governed_recovery:
            action.update({
                "Approver": approval_group,
                "Owner Approval Status": "Requested",
                "Owner Approval Note": (
                    "Alert routed from Alert Center; retry, recovery, or claimed savings closure requires root-cause "
                    "owner approval and post-recovery verification."
                ),
                "Recovery SLA State": _alert_recovery_sla_state(row),
                "Recovery SLA Target Hours": float(sla_target_hours),
                "Recovery Evidence": recovery_evidence,
                "Recovery Audit State": "Audit Required",
            })
            if alert_age_hours is not None:
                action["Recovery SLA Hours"] = float(alert_age_hours)
            action.update(_alert_recovery_metrics(row, "task" if is_cost_verifier else reliability_kind))
        actions.append(action)
    return actions


def build_alert_insert_sql(
    *,
    company: str,
    category: str,
    severity: str,
    entity_name: str,
    message: str,
    suggested_action: str = "",
    proof_query: str = "",
    owner: str = "DBA",
    environment: str = "No Database Context",
    email_target: str = DEFAULT_ALERT_RECIPIENT,
) -> str:
    row = {
        "COMPANY": company,
        "ENVIRONMENT": environment,
        "CATEGORY": category,
        "SEVERITY": severity,
        "ENTITY_NAME": entity_name,
        "MESSAGE": message,
        "SUGGESTED_ACTION": suggested_action,
        "PROOF_QUERY": proof_query,
        "OWNER": owner,
        "EMAIL_TARGET": email_target,
    }
    return f"""
INSERT INTO {alert_table_fqn(quoted=True)}
    (COMPANY, ENVIRONMENT, CATEGORY, ALERT_TYPE, SEVERITY, ENTITY_NAME, ENTITY,
     MESSAGE, DETAIL, SUGGESTED_ACTION, PROOF_QUERY, OWNER, STATUS,
     DELIVERY_METHOD, DELIVERY_TARGET, EMAIL_TARGET, EMAIL_SUBJECT, EMAIL_BODY,
     DELIVERY_STATUS)
VALUES
    ({sql_literal(company)}, {sql_literal(environment)}, {sql_literal(category)}, {sql_literal(category)},
     {sql_literal(normalize_alert_severity(severity))}, {sql_literal(entity_name, 500)}, {sql_literal(entity_name, 500)},
     {sql_literal(message, 4000)}, {sql_literal(message, 4000)}, {sql_literal(suggested_action, 2000)},
     {sql_literal(proof_query, 8000)}, {sql_literal(owner, 200)}, 'New',
     {sql_literal(ALERT_DELIVERY_METHOD)}, {sql_literal(email_target, 500)}, {sql_literal(email_target, 500)},
     {sql_literal(build_alert_email_subject(row, company), 1000)},
     {sql_literal(build_alert_email_body(row, company), 16000)},
     'EMAIL_READY');
""".strip()


def build_alert_status_update_sql(
    *,
    alert_id: int | str,
    status: str,
    reason: str = "",
    actor: str = "OVERWATCH",
    columns: set[str] | None = None,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
) -> str:
    status_clean = normalize_alert_status(status)
    if status_clean not in ALERT_STATUS_CHOICES:
        raise ValueError(f"Unsupported alert status: {status}")
    alert_id_int = int(alert_id)
    available = {column.upper() for column in (columns or set())}
    set_parts = [f"STATUS = {sql_literal(status_clean, 40)}"]
    if "RESOLVED" in available:
        set_parts.append(f"RESOLVED = {'TRUE' if status_clean == 'Fixed' else 'FALSE'}")
    if "ACKNOWLEDGED_BY" in available and status_clean in {"Acknowledged", "In Progress", "Fixed", "Ignored"}:
        set_parts.append(f"ACKNOWLEDGED_BY = COALESCE(ACKNOWLEDGED_BY, {sql_literal(actor, 200)})")
    if "ACKNOWLEDGED_AT" in available and status_clean in {"Acknowledged", "In Progress", "Fixed", "Ignored"}:
        set_parts.append("ACKNOWLEDGED_AT = COALESCE(ACKNOWLEDGED_AT, CURRENT_TIMESTAMP())")
    if "STATUS_REASON" in available:
        set_parts.append(f"STATUS_REASON = {sql_literal(reason, 2000)}")
    if "LAST_STATUS_BY" in available:
        set_parts.append(f"LAST_STATUS_BY = {sql_literal(actor, 200)}")
    if "LAST_STATUS_AT" in available:
        set_parts.append("LAST_STATUS_AT = CURRENT_TIMESTAMP()")
    return f"""
UPDATE {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}
SET {", ".join(set_parts)}
WHERE ALERT_ID = {alert_id_int}
""".strip()


def update_alert_status(
    session,
    alert_id: int | str,
    status: str,
    *,
    reason: str = "",
    actor: str = "OVERWATCH",
) -> None:
    columns = set(filter_existing_columns(
        session,
        alert_table_fqn(),
        [
            "STATUS",
            "RESOLVED",
            "ACKNOWLEDGED_BY",
            "ACKNOWLEDGED_AT",
            "STATUS_REASON",
            "LAST_STATUS_BY",
            "LAST_STATUS_AT",
        ],
    ))
    if "STATUS" not in columns:
        raise ValueError("OVERWATCH_ALERTS does not expose STATUS for alert lifecycle updates.")
    session.sql(build_alert_status_update_sql(
        alert_id=alert_id,
        status=status,
        reason=reason,
        actor=actor,
        columns=columns,
    )).collect()


def build_alert_escalation_ack_sql(
    *,
    alert_id: int | str,
    actor: str,
    note: str,
    columns: set[str] | None = None,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
) -> str:
    if len(str(note or "").strip()) < 10:
        raise ValueError("Escalation acknowledgment requires a note with evidence or owner context.")
    alert_id_int = int(alert_id)
    available = {column.upper() for column in (columns or set())}
    set_parts = []
    if "STATUS" in available:
        set_parts.append(
            "STATUS = CASE "
            "WHEN STATUS IS NULL OR UPPER(REPLACE(STATUS, ' ', '_')) IN ('NEW', 'EMAIL_READY', 'EMAIL_QUEUED', 'OPEN', 'ACTIVE', 'PENDING') "
            "THEN 'Acknowledged' ELSE STATUS END"
        )
    if "ACKNOWLEDGED_BY" in available:
        set_parts.append(f"ACKNOWLEDGED_BY = COALESCE(ACKNOWLEDGED_BY, {sql_literal(actor, 200)})")
    if "ACKNOWLEDGED_AT" in available:
        set_parts.append("ACKNOWLEDGED_AT = COALESCE(ACKNOWLEDGED_AT, CURRENT_TIMESTAMP())")
    if "ESCALATION_ACK_BY" in available:
        set_parts.append(f"ESCALATION_ACK_BY = {sql_literal(actor, 200)}")
    if "ESCALATION_ACK_AT" in available:
        set_parts.append("ESCALATION_ACK_AT = CURRENT_TIMESTAMP()")
    if "ESCALATION_ACK_NOTE" in available:
        set_parts.append(f"ESCALATION_ACK_NOTE = {sql_literal(note, 2000)}")
    if "LAST_STATUS_BY" in available:
        set_parts.append(f"LAST_STATUS_BY = {sql_literal(actor, 200)}")
    if "LAST_STATUS_AT" in available:
        set_parts.append("LAST_STATUS_AT = CURRENT_TIMESTAMP()")
    if not set_parts:
        raise ValueError("OVERWATCH_ALERTS does not expose escalation acknowledgment columns.")
    return f"""
UPDATE {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}
SET {", ".join(set_parts)}
WHERE ALERT_ID = {alert_id_int}
""".strip()


def acknowledge_alert_escalation(
    session,
    alert_id: int | str,
    *,
    actor: str,
    note: str,
) -> None:
    columns = set(filter_existing_columns(
        session,
        alert_table_fqn(),
        [
            "STATUS",
            "ACKNOWLEDGED_BY",
            "ACKNOWLEDGED_AT",
            "ESCALATION_ACK_BY",
            "ESCALATION_ACK_AT",
            "ESCALATION_ACK_NOTE",
            "LAST_STATUS_BY",
            "LAST_STATUS_AT",
        ],
    ))
    session.sql(build_alert_escalation_ack_sql(
        alert_id=alert_id,
        actor=actor,
        note=note,
        columns=columns,
    )).collect()


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
        alert_table_fqn(),
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
    session.sql(f"""
        UPDATE {alert_table_fqn(quoted=True)}
        SET {", ".join(set_parts)}
        WHERE ALERT_ID IN ({", ".join(str(value) for value in clean_ids)})
    """).collect()


def build_alert_delivery_log_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    return f"""CREATE TABLE IF NOT EXISTS {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(ALERT_DELIVERY_LOG_TABLE)} (
    DELIVERY_ID      NUMBER AUTOINCREMENT PRIMARY KEY,
    DELIVERY_TS      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY          VARCHAR(100),
    ENVIRONMENT      VARCHAR(100),
    ALERT_IDS        VARIANT,
    ALERT_COUNT      NUMBER,
    DELIVERY_METHOD  VARCHAR(40) DEFAULT 'EMAIL',
    DELIVERY_TARGET  VARCHAR(500),
    EMAIL_SUBJECT    VARCHAR(1000),
    EMAIL_BODY       VARCHAR(16000),
    DELIVERY_STATUS  VARCHAR(100),
    DELIVERY_BY      VARCHAR(200),
    DELIVERY_NOTES   VARCHAR(4000)
);"""


def build_alert_delivery_log_insert_sql(
    *,
    alert_ids: list[int | str],
    company: str,
    environment: str,
    delivery_target: str,
    email_subject: str,
    email_body: str,
    actor: str,
    notes: str,
    delivery_status: str = "EMAIL_LOGGED",
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    clean_ids = _numeric_alert_ids(alert_ids)
    if not clean_ids:
        raise ValueError("At least one numeric alert id is required for delivery logging.")
    if not str(delivery_target or "").strip():
        raise ValueError("Delivery target is required.")
    if len(str(notes or "").strip()) < 10:
        raise ValueError("Delivery notes must explain where/how the email was handled.")
    alert_json = json.dumps(clean_ids)
    return f"""
INSERT INTO {alert_delivery_log_fqn(db=db, schema=schema, quoted=True)}
    (COMPANY, ENVIRONMENT, ALERT_IDS, ALERT_COUNT, DELIVERY_METHOD, DELIVERY_TARGET,
     EMAIL_SUBJECT, EMAIL_BODY, DELIVERY_STATUS, DELIVERY_BY, DELIVERY_NOTES)
VALUES
    ({sql_literal(company, 100)}, {sql_literal(environment, 100)}, PARSE_JSON({sql_literal(alert_json, 16000)}),
     {len(clean_ids)}, {sql_literal(ALERT_DELIVERY_METHOD, 40)}, {sql_literal(delivery_target, 500)},
     {sql_literal(email_subject, 1000)}, {sql_literal(email_body, 16000)}, {sql_literal(delivery_status, 100)},
     {sql_literal(actor, 200)}, {sql_literal(notes, 4000)})
""".strip()


def build_alert_delivery_mark_sql(
    *,
    alert_ids: list[int | str],
    delivery_target: str,
    actor: str,
    columns: set[str] | None = None,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
) -> str:
    clean_ids = _numeric_alert_ids(alert_ids)
    if not clean_ids:
        raise ValueError("At least one numeric alert id is required.")
    available = {column.upper() for column in (columns or set())}
    set_parts = []
    if "DELIVERY_STATUS" in available:
        set_parts.append("DELIVERY_STATUS = 'EMAIL_LOGGED'")
    if "DELIVERY_TARGET" in available:
        set_parts.append(f"DELIVERY_TARGET = {sql_literal(delivery_target, 500)}")
    if "EMAIL_TARGET" in available:
        set_parts.append(f"EMAIL_TARGET = COALESCE(NULLIF(EMAIL_TARGET, ''), {sql_literal(delivery_target, 500)})")
    if "LAST_DELIVERY_AT" in available:
        set_parts.append("LAST_DELIVERY_AT = CURRENT_TIMESTAMP()")
    if "LAST_DELIVERY_BY" in available:
        set_parts.append(f"LAST_DELIVERY_BY = {sql_literal(actor, 200)}")
    if "DELIVERY_LOG_COUNT" in available:
        set_parts.append("DELIVERY_LOG_COUNT = COALESCE(DELIVERY_LOG_COUNT, 0) + 1")
    if "ESCALATED_TO" in available:
        set_parts.append(
            "ESCALATED_TO = COALESCE(ESCALATED_TO, "
            "CASE WHEN UPPER(COALESCE(SEVERITY, 'Medium')) IN ('CRITICAL', 'HIGH') THEN 'DBA Lead' ELSE COALESCE(OWNER, 'DBA') END)"
        )
    if "ESCALATED_AT" in available:
        set_parts.append("ESCALATED_AT = COALESCE(ESCALATED_AT, CURRENT_TIMESTAMP())")
    if "LAST_STATUS_BY" in available:
        set_parts.append(f"LAST_STATUS_BY = {sql_literal(actor, 200)}")
    if "LAST_STATUS_AT" in available:
        set_parts.append("LAST_STATUS_AT = CURRENT_TIMESTAMP()")
    if not set_parts:
        raise ValueError("OVERWATCH_ALERTS does not expose delivery audit columns.")
    return f"""
UPDATE {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}
SET {", ".join(set_parts)}
WHERE ALERT_ID IN ({", ".join(str(value) for value in clean_ids)})
""".strip()


def log_alert_digest_delivery(
    session,
    df_alerts: pd.DataFrame,
    *,
    company: str,
    environment: str,
    delivery_target: str,
    email_subject: str,
    email_body: str,
    actor: str,
    notes: str,
) -> int:
    clean_ids = _numeric_alert_ids(df_alerts)
    if not clean_ids:
        raise ValueError("No alert rows with numeric ALERT_ID values are available to log.")
    columns = set(filter_existing_columns(
        session,
        alert_table_fqn(),
        [
            "DELIVERY_STATUS",
            "DELIVERY_TARGET",
            "EMAIL_TARGET",
            "LAST_DELIVERY_AT",
            "LAST_DELIVERY_BY",
            "DELIVERY_LOG_COUNT",
            "ESCALATED_TO",
            "ESCALATED_AT",
            "LAST_STATUS_BY",
            "LAST_STATUS_AT",
        ],
    ))
    session.sql(build_alert_delivery_log_insert_sql(
        alert_ids=clean_ids,
        company=company,
        environment=environment,
        delivery_target=delivery_target,
        email_subject=email_subject,
        email_body=email_body,
        actor=actor,
        notes=notes,
    )).collect()
    if columns:
        session.sql(build_alert_delivery_mark_sql(
            alert_ids=clean_ids,
            delivery_target=delivery_target,
            actor=actor,
            columns=columns,
        )).collect()
    return len(clean_ids)


def build_alert_email_delivery_procedure_sql(
    *,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
    notification_integration: str = "OVERWATCH_EMAIL_INT",
    email_target: str = DEFAULT_ALERT_RECIPIENT,
) -> str:
    """Return optional Snowflake email delivery procedure with replay audit."""
    db_safe = safe_identifier(db)
    schema_safe = safe_identifier(schema)
    table_safe = safe_identifier(table)
    proc_fqn = f"{db_safe}.{schema_safe}.SP_OVERWATCH_SEND_ALERT_DIGEST"
    integration = str(notification_integration or "OVERWATCH_EMAIL_INT").replace("'", "''")
    default_recipient = sql_literal(email_target, 500)
    return f"""-- Optional governed email sender for Alert Center.
-- Prerequisite: create and approve notification integration {integration} outside OVERWATCH.
-- Keep P_DRY_RUN => TRUE until the integration and recipient allow-list are verified.
CREATE OR REPLACE PROCEDURE {proc_fqn}(
    P_COMPANY VARCHAR DEFAULT 'ALFA',
    P_ENVIRONMENT VARCHAR DEFAULT 'ALL',
    P_RECIPIENT VARCHAR DEFAULT {default_recipient},
    P_DRY_RUN BOOLEAN DEFAULT TRUE
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    alert_count NUMBER DEFAULT 0;
    alert_ids VARIANT DEFAULT PARSE_JSON('[]');
    subject VARCHAR DEFAULT '';
    body VARCHAR DEFAULT '';
    delivery_status VARCHAR DEFAULT 'EMAIL_DRY_RUN';
BEGIN
    CREATE OR REPLACE TEMPORARY TABLE TMP_OVERWATCH_ALERT_DIGEST AS
    SELECT
        ALERT_ID,
        COMPANY,
        ENVIRONMENT,
        SEVERITY,
        CATEGORY,
        ALERT_TYPE,
        ENTITY_NAME,
        OWNER,
        COALESCE(EMAIL_SUBJECT, 'OVERWATCH ' || COALESCE(SEVERITY, 'Medium') || ' alert digest') AS EMAIL_SUBJECT,
        COALESCE(
            EMAIL_BODY,
            COALESCE(SEVERITY, 'Medium') || ' | ' || COALESCE(CATEGORY, 'Alert') || ' | ' ||
            COALESCE(ALERT_TYPE, CATEGORY, 'Alert') || ' | ' || COALESCE(ENTITY_NAME, ENTITY, 'Snowflake account') ||
            '\\nAction: ' || COALESCE(SUGGESTED_ACTION, 'Review in Alert Center.')
        ) AS EMAIL_BODY
    FROM {db_safe}.{schema_safe}.{table_safe}
    WHERE UPPER(REPLACE(COALESCE(STATUS, 'New'), ' ', '_')) IN ('NEW', 'OPEN', 'ACTIVE', 'EMAIL_READY', 'EMAIL_QUEUED', 'PENDING', 'ACKNOWLEDGED', 'IN_PROGRESS')
      AND (P_COMPANY = 'ALL' OR COMPANY = P_COMPANY)
      AND (
          P_ENVIRONMENT = 'ALL'
          OR COALESCE(ENVIRONMENT, 'No Database Context') = P_ENVIRONMENT
          OR (P_ENVIRONMENT = 'DEV_ALL' AND COALESCE(ENVIRONMENT, '') IN ('DEV_ALL', 'ALFA_EDW_DEV', 'ALFA_EDW_SAN', 'ALFA_EDW_PHX', 'ALFA_EDW_SEA', 'ALFA_EDW_SIT', 'OTHER ALFA NON-PROD'))
      )
    ORDER BY
        CASE UPPER(COALESCE(SEVERITY, 'Medium'))
            WHEN 'CRITICAL' THEN 0
            WHEN 'HIGH' THEN 1
            WHEN 'MEDIUM' THEN 2
            WHEN 'LOW' THEN 3
            ELSE 4
        END,
        ALERT_TS DESC
    LIMIT 25;

    SELECT
        COUNT(*),
        TO_VARIANT(ARRAY_AGG(ALERT_ID)),
        'OVERWATCH alert digest - ' || P_COMPANY || ' / ' || P_ENVIRONMENT || ' - ' || COUNT(*) || ' open issue(s)',
        LISTAGG(
            '[' || COALESCE(SEVERITY, 'Medium') || '] ' || COALESCE(ALERT_TYPE, CATEGORY, 'Alert') ||
            ' | ' || COALESCE(ENTITY_NAME, 'Snowflake account') ||
            ' | Owner: ' || COALESCE(OWNER, 'DBA') ||
            '\\n' || EMAIL_BODY,
            '\\n\\n---\\n\\n'
        ) WITHIN GROUP (ORDER BY ALERT_ID)
    INTO :alert_count, :alert_ids, :subject, :body
    FROM TMP_OVERWATCH_ALERT_DIGEST;

    IF (alert_count = 0) THEN
        RETURN 'No open OVERWATCH alerts matched the requested scope.';
    END IF;

    IF (P_DRY_RUN) THEN
        delivery_status := 'EMAIL_DRY_RUN';
    ELSE
        CALL SYSTEM$SEND_EMAIL('{integration}', :P_RECIPIENT, :subject, :body);
        delivery_status := 'EMAIL_SENT';
    END IF;

    INSERT INTO {alert_delivery_log_fqn(db=db, schema=schema, quoted=True)}
        (COMPANY, ENVIRONMENT, ALERT_IDS, ALERT_COUNT, DELIVERY_METHOD, DELIVERY_TARGET,
         EMAIL_SUBJECT, EMAIL_BODY, DELIVERY_STATUS, DELIVERY_BY, DELIVERY_NOTES)
    VALUES
        (P_COMPANY, P_ENVIRONMENT, alert_ids, alert_count, 'EMAIL', P_RECIPIENT,
         subject, body, delivery_status, CURRENT_USER(),
         IFF(P_DRY_RUN, 'Dry-run replay package prepared; SYSTEM$SEND_EMAIL was not called.',
                       'Delivered through approved Snowflake email notification integration {integration}.'));

    UPDATE {db_safe}.{schema_safe}.{table_safe}
    SET
        DELIVERY_STATUS = delivery_status,
        DELIVERY_TARGET = P_RECIPIENT,
        EMAIL_TARGET = COALESCE(NULLIF(EMAIL_TARGET, ''), P_RECIPIENT),
        LAST_DELIVERY_AT = CURRENT_TIMESTAMP(),
        LAST_DELIVERY_BY = CURRENT_USER(),
        DELIVERY_LOG_COUNT = COALESCE(DELIVERY_LOG_COUNT, 0) + 1,
        LAST_STATUS_BY = CURRENT_USER(),
        LAST_STATUS_AT = CURRENT_TIMESTAMP()
    WHERE ARRAY_CONTAINS(ALERT_ID::VARIANT, alert_ids);

    RETURN 'OVERWATCH alert digest ' || delivery_status || ': ' || alert_count || ' alert(s) for ' || P_RECIPIENT;
END;
$$;"""


def load_alert_delivery_log(
    *,
    days: int = 14,
    limit: int = 100,
    section: str = "Alert Center",
) -> pd.DataFrame:
    days = max(1, min(int(days), 365))
    limit = max(1, min(int(limit), 1000))
    return run_query(f"""
        SELECT
            DELIVERY_ID,
            DELIVERY_TS,
            COMPANY,
            ENVIRONMENT,
            ALERT_COUNT,
            DELIVERY_METHOD,
            DELIVERY_TARGET,
            EMAIL_SUBJECT,
            DELIVERY_STATUS,
            DELIVERY_BY,
            DELIVERY_NOTES
        FROM {alert_delivery_log_fqn(quoted=True)}
        WHERE DELIVERY_TS >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        ORDER BY DELIVERY_TS DESC
        LIMIT {limit}
    """, ttl_key=f"alert_delivery_log_{days}_{limit}", tier="recent", section=section)


def build_annotation_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Generate DDL for the OVERWATCH_ANNOTATIONS table."""
    return f"""-- OVERWATCH Annotation System
-- Prevents re-alerting on known events such as load tests, deployments, or planned maintenance.

CREATE TABLE IF NOT EXISTS {safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(ANNOTATION_TABLE)} (
    ANNOTATION_ID   NUMBER AUTOINCREMENT PRIMARY KEY,
    CREATED_BY      VARCHAR(200),
    CREATED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    ENTITY          VARCHAR(500),
    ENTITY_TYPE     VARCHAR(50),
    WINDOW_START    TIMESTAMP_NTZ NOT NULL,
    WINDOW_END      TIMESTAMP_NTZ NOT NULL,
    ANNOTATION_TYPE VARCHAR(100),
    DESCRIPTION     VARCHAR(2000),
    SUPPRESS_ALERTS BOOLEAN DEFAULT TRUE,
    ACTIVE          BOOLEAN DEFAULT TRUE
);
"""


def build_alert_triage_view_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
) -> str:
    db = safe_identifier(db)
    schema = safe_identifier(schema)
    table = safe_identifier(table)
    return f"""CREATE OR REPLACE VIEW {db}.{schema}.OVERWATCH_ALERT_TRIAGE_V AS
WITH base AS (
    SELECT
        a.*,
        COALESCE(od.OWNER_NAME, r.OWNER, a.OWNER, 'DBA') AS ROUTED_OWNER,
        od.OWNER_EMAIL,
        od.ONCALL_PRIMARY,
        od.ONCALL_SECONDARY,
        COALESCE(od.APPROVAL_GROUP, r.OWNER, a.OWNER, 'DBA Lead') AS APPROVAL_GROUP,
        COALESCE(od.ESCALATION_TARGET, od.APPROVAL_GROUP, r.OWNER, a.OWNER, 'DBA Lead') AS OWNER_ESCALATION_TARGET,
        CASE WHEN od.OWNER_KEY IS NOT NULL THEN 'OWNER_DIRECTORY:' || od.OWNER_KEY ELSE 'ALERT_RULE' END AS OWNER_SOURCE,
        CASE WHEN od.OWNER_KEY IS NOT NULL THEN 'Matched ' || od.ENTITY_TYPE || ' pattern ' || od.ENTITY_PATTERN ELSE 'Matched alert rule owner' END AS OWNER_EVIDENCE,
        COALESCE(
            r.SLA_HOURS,
            CASE UPPER(COALESCE(a.SEVERITY, 'Medium'))
                WHEN 'CRITICAL' THEN 4
                WHEN 'HIGH' THEN 8
                WHEN 'LOW' THEN 72
                ELSE 24
            END
        ) AS SLA_TARGET_HOURS,
        GREATEST(0, COALESCE(DATEDIFF('hour', a.ALERT_TS, CURRENT_TIMESTAMP()), 0)) AS ALERT_AGE_HOURS,
        COALESCE(r.ROUTE, 'Alert Center') AS ALERT_ROUTE,
        COALESCE(r.RUNBOOK, a.SUGGESTED_ACTION, 'Review the Alert Center issue and route it through the DBA action queue.') AS ALERT_RUNBOOK
    FROM {db}.{schema}.{table} a
    LEFT JOIN {db}.{schema}.OVERWATCH_ALERT_RULES r
      ON UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) = UPPER(COALESCE(r.ALERT_TYPE, r.CATEGORY, ''))
     AND COALESCE(r.IS_ACTIVE, TRUE)
    LEFT JOIN {db}.{schema}.{OWNER_DIRECTORY_VIEW} od
      ON (
          od.ENTITY_TYPE IN ('GLOBAL', 'ALERT')
          OR od.ENTITY_TYPE = UPPER(COALESCE(a.CATEGORY, r.CATEGORY, ''))
          OR (od.ENTITY_TYPE = 'COST_CONTROL' AND UPPER(COALESCE(a.CATEGORY, a.ALERT_TYPE, '')) LIKE '%COST%')
          OR (od.ENTITY_TYPE = 'TASK' AND UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, a.ENTITY_NAME, '')) LIKE '%TASK%')
          OR (od.ENTITY_TYPE = 'PROCEDURE' AND UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, a.ENTITY_NAME, '')) LIKE '%PROCEDURE%')
          OR (od.ENTITY_TYPE = 'WAREHOUSE' AND UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, a.ENTITY_NAME, '')) LIKE '%WAREHOUSE%')
          OR (od.ENTITY_TYPE = 'SECURITY' AND UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) REGEXP 'GRANT|REVOKE|ROLE|SECURITY')
      )
     AND (
          UPPER(COALESCE(a.ENTITY_NAME, a.ENTITY, '')) LIKE REPLACE(UPPER(od.ENTITY_PATTERN), '*', '%')
          OR UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) LIKE REPLACE(UPPER(od.ENTITY_PATTERN), '*', '%')
          OR od.ENTITY_PATTERN IN ('*', '%')
     )
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY COALESCE(TO_VARCHAR(a.ALERT_ID), TO_VARCHAR(a.ALERT_TS), COALESCE(a.ENTITY_NAME, a.ENTITY, 'UNKNOWN'))
        ORDER BY COALESCE(od.MATCH_PRIORITY, 0) DESC, od.OWNER_KEY
    ) = 1
),
sla AS (
    SELECT
        base.*,
        CASE
            WHEN UPPER(REPLACE(COALESCE(STATUS, 'New'), ' ', '_')) IN ('FIXED', 'IGNORED', 'RESOLVED') THEN 'Closed'
            WHEN ALERT_AGE_HOURS > SLA_TARGET_HOURS THEN 'Overdue'
            WHEN ALERT_AGE_HOURS >= (SLA_TARGET_HOURS * 0.75) THEN 'Due Soon'
            ELSE 'Within SLA'
        END AS SLA_STATE
    FROM base
)
SELECT
    sla.*,
    CASE
        WHEN SLA_STATE = 'Overdue' AND UPPER(COALESCE(SEVERITY, 'Medium')) IN ('CRITICAL', 'HIGH') THEN COALESCE(OWNER_ESCALATION_TARGET, ESCALATED_TO, 'DBA Lead')
        ELSE COALESCE(OWNER_ESCALATION_TARGET, ROUTED_OWNER, OWNER, 'DBA')
    END AS ESCALATION_TARGET,
    (
        CASE UPPER(COALESCE(SEVERITY, 'Medium'))
            WHEN 'CRITICAL' THEN 0
            WHEN 'HIGH' THEN 1
            WHEN 'MEDIUM' THEN 2
            WHEN 'LOW' THEN 3
            ELSE 4
        END * 100
        + CASE SLA_STATE
            WHEN 'Overdue' THEN 0
            WHEN 'Due Soon' THEN 1
            WHEN 'Within SLA' THEN 2
            WHEN 'Closed' THEN 9
            ELSE 5
          END * 10
        + CASE UPPER(REPLACE(COALESCE(STATUS, 'New'), ' ', '_'))
            WHEN 'NEW' THEN 0
            WHEN 'EMAIL_READY' THEN 0
            WHEN 'EMAIL_QUEUED' THEN 0
            WHEN 'OPEN' THEN 0
            WHEN 'ACTIVE' THEN 0
            WHEN 'PENDING' THEN 0
            WHEN 'ACKNOWLEDGED' THEN 1
            WHEN 'IN_PROGRESS' THEN 1
            WHEN 'FIXED' THEN 3
            WHEN 'RESOLVED' THEN 3
            WHEN 'IGNORED' THEN 4
            ELSE 2
          END
    ) AS TRIAGE_PRIORITY
FROM sla;"""


def build_alert_task_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = ALERT_TABLE,
    warehouse: str = "COMPUTE_WH",
    schedule: str = "USING CRON 5 * * * * America/Chicago",
    email_target: str = DEFAULT_ALERT_RECIPIENT,
) -> str:
    """Generate DDL + DML for the OVERWATCH anomaly alert Snowflake task.

    This queues email-ready rows and installs an optional dry-run guarded
    SYSTEM$SEND_EMAIL procedure for approved Snowflake notification integrations.
    """
    db = safe_identifier(db)
    schema = safe_identifier(schema)
    table = safe_identifier(table)
    annotation_table = safe_identifier(ANNOTATION_TABLE)
    warehouse = safe_identifier(warehouse)
    schedule = safe_schedule(schedule)
    email = sql_literal(email_target, 500)
    spike_pct = THRESHOLDS["credit_spike_pct"]
    error_threshold = THRESHOLDS["error_rate_high"]
    triage_view_sql = build_alert_triage_view_sql(db=db, schema=schema, table=table)

    return f"""-- OVERWATCH Automated Alert Framework
-- Email-first delivery target: {email_target}
-- Teams/webhook delivery is intentionally not used until a webhook exists.
-- SP_OVERWATCH_SEND_ALERT_DIGEST stays dry-run safe until an approved notification integration is available.

CREATE TABLE IF NOT EXISTS {db}.{schema}.{table} (
    ALERT_ID         NUMBER AUTOINCREMENT PRIMARY KEY,
    ALERT_TS         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY          VARCHAR(100),
    ENVIRONMENT      VARCHAR(100),
    DATABASE_NAME    VARCHAR(300),
    SCHEMA_NAME      VARCHAR(300),
    WAREHOUSE_NAME   VARCHAR(300),
    CATEGORY         VARCHAR(100),
    ALERT_TYPE       VARCHAR(100),
    SEVERITY         VARCHAR(20),
    ENTITY_NAME      VARCHAR(500),
    ENTITY           VARCHAR(500),
    MESSAGE          VARCHAR(4000),
    DETAIL           VARCHAR(4000),
    SUGGESTED_ACTION VARCHAR(2000),
    PROOF_QUERY      VARCHAR(8000),
    OWNER            VARCHAR(200),
    STATUS           VARCHAR(40) DEFAULT 'New',
    DELIVERY_METHOD  VARCHAR(40) DEFAULT 'EMAIL',
    DELIVERY_TARGET  VARCHAR(500),
    EMAIL_TARGET     VARCHAR(500),
    EMAIL_SUBJECT    VARCHAR(1000),
    EMAIL_BODY       VARCHAR(16000),
    DELIVERY_STATUS  VARCHAR(100),
    ACKNOWLEDGED_BY  VARCHAR(200),
    ACKNOWLEDGED_AT  TIMESTAMP_NTZ,
    RESOLVED         BOOLEAN DEFAULT FALSE,
    STATUS_REASON    VARCHAR(2000),
    LAST_STATUS_BY   VARCHAR(200),
    LAST_STATUS_AT   TIMESTAMP_NTZ,
    LAST_DELIVERY_AT TIMESTAMP_NTZ,
    LAST_DELIVERY_BY VARCHAR(200),
    DELIVERY_LOG_COUNT NUMBER DEFAULT 0,
    ESCALATED_TO     VARCHAR(200),
    ESCALATED_AT     TIMESTAMP_NTZ,
    ESCALATION_ACK_BY VARCHAR(200),
    ESCALATION_ACK_AT TIMESTAMP_NTZ,
    ESCALATION_ACK_NOTE VARCHAR(2000),
    ROUTED_TO_ACTION_QUEUE_AT TIMESTAMP_NTZ,
    ROUTED_ACTION_COUNT NUMBER DEFAULT 0
);

ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS DATABASE_NAME VARCHAR(300);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS SCHEMA_NAME VARCHAR(300);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS WAREHOUSE_NAME VARCHAR(300);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS ALERT_TYPE VARCHAR(100);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS ENTITY VARCHAR(500);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS DETAIL VARCHAR(4000);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS SUGGESTED_ACTION VARCHAR(2000);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS OWNER VARCHAR(200);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS STATUS VARCHAR(40) DEFAULT 'New';
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS DELIVERY_METHOD VARCHAR(40) DEFAULT 'EMAIL';
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS EMAIL_TARGET VARCHAR(500);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS EMAIL_SUBJECT VARCHAR(1000);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS EMAIL_BODY VARCHAR(16000);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS RESOLVED BOOLEAN DEFAULT FALSE;
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS STATUS_REASON VARCHAR(2000);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS LAST_STATUS_BY VARCHAR(200);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS LAST_STATUS_AT TIMESTAMP_NTZ;
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS LAST_DELIVERY_AT TIMESTAMP_NTZ;
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS LAST_DELIVERY_BY VARCHAR(200);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS DELIVERY_LOG_COUNT NUMBER DEFAULT 0;
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS ESCALATED_TO VARCHAR(200);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS ESCALATED_AT TIMESTAMP_NTZ;
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS ESCALATION_ACK_BY VARCHAR(200);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS ESCALATION_ACK_AT TIMESTAMP_NTZ;
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS ESCALATION_ACK_NOTE VARCHAR(2000);
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS ROUTED_TO_ACTION_QUEUE_AT TIMESTAMP_NTZ;
ALTER TABLE {db}.{schema}.{table} ADD COLUMN IF NOT EXISTS ROUTED_ACTION_COUNT NUMBER DEFAULT 0;

{build_alert_delivery_log_ddl(db=db, schema=schema)}

{build_alert_email_delivery_procedure_sql(db=db, schema=schema, table=table, email_target=email_target)}

{build_owner_directory_ddl(db=db, schema=schema)}

{build_alert_rule_audit_ddl(db=db, schema=schema)}

CREATE TABLE IF NOT EXISTS {db}.{schema}.OVERWATCH_ALERT_RULES (
    RULE_ID          VARCHAR(200) PRIMARY KEY,
    CATEGORY         VARCHAR(100),
    ALERT_TYPE       VARCHAR(100),
    DEFAULT_SEVERITY VARCHAR(20),
    SLA_HOURS        NUMBER,
    OWNER            VARCHAR(200),
    ROUTE            VARCHAR(200),
    RUNBOOK          VARCHAR(2000),
    IS_ACTIVE        BOOLEAN DEFAULT TRUE,
    UPDATED_AT       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_BY       VARCHAR(200) DEFAULT CURRENT_USER()
);

MERGE INTO {db}.{schema}.OVERWATCH_ALERT_RULES tgt
USING (
    SELECT * FROM VALUES
        ('COST_CREDIT_SPIKE', 'Cost Control', 'Credit Spike', 'Medium', 24, 'DBA / FinOps', 'Cost & Contract', 'Explain the bill movement, identify owner-backed drivers, and route savings actions.'),
        ('COST_SAVINGS_VERIFIER_FAILURE', 'Cost Control', 'Cost Savings Verification Failure', 'High', 8, 'DBA / FinOps', 'Cost & Contract', 'Inspect the savings verifier task, keep savings estimated, and restore ledger-backed verification before claiming value.'),
        ('QUERY_HIGH_ERROR_RATE', 'Reliability', 'High Query Error Rate', 'High', 8, 'DBA / Workload Owner', 'Workload Operations', 'Group failures by error code/query text and assign the owning team.'),
        ('TASK_FAILURE', 'Reliability', 'Task Failure', 'High', 8, 'DBA / Pipeline Owner', 'Workload Operations', 'Review task graph impact, retry only after root cause, and verify the next run.'),
        ('PROCEDURE_FAILURE_OR_SPIKE', 'Reliability', 'Stored Procedure Failure / Runtime Spike', 'High', 8, 'DBA / Procedure Owner', 'Workload Operations', 'Compare release windows, inspect child queries, and verify runtime/cost return to baseline.'),
        ('WAREHOUSE_PRESSURE', 'Capacity', 'Warehouse Pressure', 'Medium', 24, 'DBA / Platform', 'Warehouse Health', 'Inspect queue/spill evidence and route changed-only warehouse setting recommendations.'),
        ('GRANT_REVOKE_ACTIVITY', 'Change Control', 'Grant/Revoke Activity', 'Medium', 24, 'DBA / Security', 'Security Posture', 'Verify least-privilege approval, owner, ticket, approver, and review date.'),
        ('WAREHOUSE_SETTING_CHANGE', 'Change Control', 'Warehouse Setting Change', 'Medium', 24, 'DBA / Platform', 'Change & Drift', 'Verify changed-only SQL, approval, rollback SQL, and post-change evidence.')
) src(RULE_ID, CATEGORY, ALERT_TYPE, DEFAULT_SEVERITY, SLA_HOURS, OWNER, ROUTE, RUNBOOK)
ON tgt.RULE_ID = src.RULE_ID
WHEN MATCHED THEN UPDATE SET
    CATEGORY = src.CATEGORY,
    ALERT_TYPE = src.ALERT_TYPE,
    DEFAULT_SEVERITY = src.DEFAULT_SEVERITY,
    SLA_HOURS = src.SLA_HOURS,
    OWNER = src.OWNER,
    ROUTE = src.ROUTE,
    RUNBOOK = src.RUNBOOK,
    IS_ACTIVE = TRUE
WHEN NOT MATCHED THEN INSERT
    (RULE_ID, CATEGORY, ALERT_TYPE, DEFAULT_SEVERITY, SLA_HOURS, OWNER, ROUTE, RUNBOOK)
VALUES
    (src.RULE_ID, src.CATEGORY, src.ALERT_TYPE, src.DEFAULT_SEVERITY, src.SLA_HOURS, src.OWNER, src.ROUTE, src.RUNBOOK);

{triage_view_sql}

CREATE OR REPLACE FUNCTION {db}.{schema}.OVERWATCH_DATABASE_ENVIRONMENT(DATABASE_NAME VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
  CASE
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_PROD' THEN 'PROD'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_DEV' THEN 'ALFA_EDW_DEV'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_SAN' THEN 'ALFA_EDW_SAN'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_PHX' THEN 'ALFA_EDW_PHX'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_SEA' THEN 'ALFA_EDW_SEA'
    WHEN UPPER(DATABASE_NAME) = 'ALFA_EDW_SIT' THEN 'ALFA_EDW_SIT'
    WHEN DATABASE_NAME ILIKE 'ALFA_EDW_%' THEN 'Other ALFA Non-Prod'
    WHEN DATABASE_NAME IS NULL THEN 'No Database Context'
    ELSE 'Other / Shared'
  END
$$;

CREATE OR REPLACE TASK {db}.{schema}.OVERWATCH_ANOMALY_CHECK
    WAREHOUSE = {warehouse}
    SCHEDULE  = {sql_literal(schedule)}
AS
INSERT INTO {db}.{schema}.{table}
    (ALERT_TS, COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, WAREHOUSE_NAME,
     CATEGORY, ALERT_TYPE, SEVERITY, ENTITY_NAME, ENTITY, MESSAGE, DETAIL,
     SUGGESTED_ACTION, PROOF_QUERY, OWNER, STATUS, DELIVERY_METHOD,
     DELIVERY_TARGET, EMAIL_TARGET, EMAIL_SUBJECT, EMAIL_BODY, DELIVERY_STATUS)
WITH daily_credits AS (
    SELECT
        warehouse_name,
        DATE_TRUNC('day', start_time) AS day,
        SUM(COALESCE(credits_used, 0)) AS daily_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE start_time >= DATEADD('day', -15, CURRENT_TIMESTAMP())
    GROUP BY warehouse_name, day
),
credit_stats AS (
    SELECT
        warehouse_name,
        AVG(daily_credits) AS avg_credits,
        MAX(day) AS latest_day
    FROM daily_credits
    GROUP BY warehouse_name
),
credit_spikes AS (
    SELECT
        d.warehouse_name,
        d.daily_credits,
        s.avg_credits,
        ROUND(d.daily_credits / NULLIF(s.avg_credits, 0), 2) AS spike_ratio
    FROM daily_credits d
    JOIN credit_stats s ON d.warehouse_name = s.warehouse_name
    WHERE d.day = s.latest_day
      AND d.daily_credits > s.avg_credits * (1 + {spike_pct}/100.0)
      AND s.avg_credits > 0.1
),
query_error_rates AS (
    SELECT
        warehouse_name,
        database_name,
        schema_name,
        COUNT(*) AS failures,
        MAX(LEFT(error_message, 500)) AS sample_error
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND (error_code IS NOT NULL OR UPPER(execution_status) = 'FAILED_WITH_ERROR')
      AND warehouse_name IS NOT NULL
    GROUP BY warehouse_name, database_name, schema_name
    HAVING COUNT(*) > {error_threshold}
),
warehouse_pressure AS (
    SELECT
        warehouse_name,
        database_name,
        COUNT(*) AS query_count,
        SUM(CASE WHEN COALESCE(queued_overload_time, 0)
                    + COALESCE(queued_provisioning_time, 0)
                    + COALESCE(queued_repair_time, 0) > 0
                 THEN 1 ELSE 0 END) AS queued_queries,
        ROUND(APPROX_PERCENTILE(total_elapsed_time / 1000, 0.95), 2) AS p95_elapsed_sec
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND warehouse_name IS NOT NULL
    GROUP BY warehouse_name, database_name
    HAVING queued_queries >= 20 OR p95_elapsed_sec >= 120
),
task_failures AS (
    SELECT
        database_name,
        schema_name,
        name AS task_name,
        COUNT(*) AS failures,
        MAX(LEFT(error_message, 500)) AS sample_error
    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
    WHERE scheduled_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND UPPER(state) = 'FAILED'
      AND UPPER(name) <> 'OVERWATCH_COST_SAVINGS_VERIFY'
    GROUP BY database_name, schema_name, name
),
cost_savings_verifier_failures AS (
    SELECT
        database_name,
        schema_name,
        name AS task_name,
        COUNT(*) AS failures,
        MAX(state) AS latest_state,
        MAX(scheduled_time) AS latest_scheduled_time,
        MAX(LEFT(error_message, 500)) AS sample_error
    FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
    WHERE scheduled_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND UPPER(name) = 'OVERWATCH_COST_SAVINGS_VERIFY'
      AND UPPER(COALESCE(state, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'CANCELLED')
    GROUP BY database_name, schema_name, name
),
proc_recent AS (
    SELECT
        database_name,
        schema_name,
        COALESCE(REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1), 'UNKNOWN_PROCEDURE') AS procedure_name,
        COUNT(*) AS call_count,
        SUM(CASE WHEN error_code IS NOT NULL OR UPPER(execution_status) = 'FAILED_WITH_ERROR' THEN 1 ELSE 0 END) AS failures,
        AVG(total_elapsed_time / 1000) AS avg_duration_sec,
        MAX(LEFT(error_message, 500)) AS sample_error
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND query_type = 'CALL'
    GROUP BY database_name, schema_name, procedure_name
),
proc_baseline AS (
    SELECT
        database_name,
        schema_name,
        COALESCE(REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1), 'UNKNOWN_PROCEDURE') AS procedure_name,
        AVG(total_elapsed_time / 1000) AS baseline_duration_sec
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('day', -8, CURRENT_TIMESTAMP())
      AND start_time < DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND query_type = 'CALL'
    GROUP BY database_name, schema_name, procedure_name
),
procedure_risk AS (
    SELECT
        r.database_name,
        r.schema_name,
        r.procedure_name,
        r.call_count,
        r.failures,
        r.avg_duration_sec,
        b.baseline_duration_sec,
        r.sample_error
    FROM proc_recent r
    LEFT JOIN proc_baseline b
      ON COALESCE(r.database_name, '') = COALESCE(b.database_name, '')
     AND COALESCE(r.schema_name, '') = COALESCE(b.schema_name, '')
     AND r.procedure_name = b.procedure_name
    WHERE r.failures > 0
       OR (r.avg_duration_sec >= 60 AND b.baseline_duration_sec > 0 AND r.avg_duration_sec > b.baseline_duration_sec * 1.5)
),
privilege_changes AS (
    SELECT
        database_name,
        schema_name,
        user_name,
        role_name,
        query_type,
        COUNT(*) AS change_count,
        MAX(start_time) AS latest_change
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND (query_type ILIKE 'GRANT%' OR query_type ILIKE 'REVOKE%' OR query_text ILIKE 'GRANT %' OR query_text ILIKE 'REVOKE %')
    GROUP BY database_name, schema_name, user_name, role_name, query_type
),
warehouse_changes AS (
    SELECT
        warehouse_name,
        user_name,
        role_name,
        COUNT(*) AS change_count,
        MAX(start_time) AS latest_change
    FROM (
        SELECT
            COALESCE(warehouse_name, REGEXP_SUBSTR(query_text, 'ALTER\\\\s+WAREHOUSE\\\\s+([^\\\\s;]+)', 1, 1, 'i', 1)) AS warehouse_name,
            user_name,
            role_name,
            start_time
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
          AND (query_type ILIKE 'ALTER%WAREHOUSE%' OR query_text ILIKE 'ALTER WAREHOUSE %')
    )
    WHERE warehouse_name IS NOT NULL
    GROUP BY warehouse_name, user_name, role_name
),
candidates AS (
    SELECT
        CASE WHEN warehouse_name ILIKE 'WH_TRXS_%' THEN 'Trexis' ELSE 'ALFA' END AS company,
        'No Database Context' AS environment,
        NULL AS database_name,
        NULL AS schema_name,
        warehouse_name,
        'Cost Control' AS category,
        'Credit Spike' AS alert_type,
        CASE WHEN spike_ratio >= 3 THEN 'High' ELSE 'Medium' END AS severity,
        warehouse_name AS entity_name,
        warehouse_name AS entity,
        'Credits ' || ROUND(daily_credits, 2) || ' were ' || spike_ratio || 'x the rolling average of ' || ROUND(avg_credits, 2) AS message,
        'Credits ' || ROUND(daily_credits, 2) || ' were ' || spike_ratio || 'x the rolling average of ' || ROUND(avg_credits, 2) AS detail,
        'Open Cost & Contract, explain the bill movement, then route owner-backed savings actions.' AS suggested_action,
        'SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY WHERE WAREHOUSE_NAME = ''' || warehouse_name || ''' ORDER BY START_TIME DESC LIMIT 100;' AS proof_query,
        'DBA' AS owner
    FROM credit_spikes

    UNION ALL

    SELECT
        CASE WHEN warehouse_name ILIKE 'WH_TRXS_%' OR database_name ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END,
        {db}.{schema}.OVERWATCH_DATABASE_ENVIRONMENT(database_name),
        database_name,
        schema_name,
        warehouse_name,
        'Reliability',
        'High Query Error Rate',
        'High',
        COALESCE(database_name || '.' || schema_name, warehouse_name),
        COALESCE(database_name || '.' || schema_name, warehouse_name),
        failures || ' failed queries in the last 24 hours. Sample: ' || COALESCE(sample_error, 'No sample error captured.'),
        failures || ' failed queries in the last 24 hours. Sample: ' || COALESCE(sample_error, 'No sample error captured.'),
        'Open Workload Operations, group by error code/query text, and assign the owning team.',
        'SELECT QUERY_ID, USER_NAME, ROLE_NAME, WAREHOUSE_NAME, DATABASE_NAME, ERROR_CODE, ERROR_MESSAGE FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) AND WAREHOUSE_NAME = ''' || warehouse_name || ''' ORDER BY START_TIME DESC LIMIT 100;',
        'DBA'
    FROM query_error_rates

    UNION ALL

    SELECT
        CASE WHEN database_name ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END,
        {db}.{schema}.OVERWATCH_DATABASE_ENVIRONMENT(database_name),
        database_name,
        schema_name,
        NULL,
        'Reliability',
        'Task Failure',
        'High',
        database_name || '.' || schema_name || '.' || task_name,
        database_name || '.' || schema_name || '.' || task_name,
        failures || ' failed task run(s) in the last 24 hours. Sample: ' || COALESCE(sample_error, 'No sample error captured.'),
        failures || ' failed task run(s) in the last 24 hours. Sample: ' || COALESCE(sample_error, 'No sample error captured.'),
        'Open Workload Operations task graphs, review downstream impact, and decide retry/suspend/escalate.',
        'SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY WHERE DATABASE_NAME = ''' || database_name || ''' AND SCHEMA_NAME = ''' || schema_name || ''' AND NAME = ''' || task_name || ''' ORDER BY SCHEDULED_TIME DESC LIMIT 100;',
        'DBA'
    FROM task_failures

    UNION ALL

    SELECT
        'ALFA',
        'No Database Context',
        database_name,
        schema_name,
        NULL,
        'Cost Control',
        'Cost Savings Verification Failure',
        CASE WHEN failures >= 2 THEN 'Critical' ELSE 'High' END,
        COALESCE(database_name || '.' || schema_name || '.', '') || task_name,
        COALESCE(database_name || '.' || schema_name || '.', '') || task_name,
        failures || ' failed savings verification task run(s) in the last 24 hours. Latest state: ' || COALESCE(latest_state, 'unknown') || '. Sample: ' || COALESCE(sample_error, 'No sample error captured.'),
        failures || ' failed savings verification task run(s) in the last 24 hours. Latest state: ' || COALESCE(latest_state, 'unknown') || '. Sample: ' || COALESCE(sample_error, 'No sample error captured.'),
        'Open Cost & Contract verifier health, inspect TASK_HISTORY, keep savings estimated, and restore scheduled verification before claiming value.',
        'SELECT DATABASE_NAME, SCHEMA_NAME, NAME, STATE, SCHEDULED_TIME, COMPLETED_TIME, QUERY_ID, ERROR_MESSAGE FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY WHERE UPPER(NAME) = ''OVERWATCH_COST_SAVINGS_VERIFY'' ORDER BY SCHEDULED_TIME DESC LIMIT 100;',
        'DBA / FinOps'
    FROM cost_savings_verifier_failures

    UNION ALL

    SELECT
        CASE WHEN database_name ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END,
        {db}.{schema}.OVERWATCH_DATABASE_ENVIRONMENT(database_name),
        database_name,
        schema_name,
        NULL,
        'Reliability',
        CASE WHEN failures > 0 THEN 'Stored Procedure Failure' ELSE 'Stored Procedure Runtime Spike' END,
        CASE WHEN failures > 0 OR avg_duration_sec >= 300 THEN 'High' ELSE 'Medium' END,
        database_name || '.' || schema_name || '.' || procedure_name,
        database_name || '.' || schema_name || '.' || procedure_name,
        CASE
            WHEN failures > 0 THEN failures || ' failed CALL(s) in the last 24 hours. Sample: ' || COALESCE(sample_error, 'No sample error captured.')
            ELSE 'Average CALL duration ' || ROUND(avg_duration_sec, 1) || 's vs baseline ' || ROUND(baseline_duration_sec, 1) || 's.'
        END,
        CASE
            WHEN failures > 0 THEN failures || ' failed CALL(s) in the last 24 hours. Sample: ' || COALESCE(sample_error, 'No sample error captured.')
            ELSE 'Average CALL duration ' || ROUND(avg_duration_sec, 1) || 's vs baseline ' || ROUND(baseline_duration_sec, 1) || 's.'
        END,
        'Open Workload Operations stored procedures, compare release windows, and assign remediation.',
        'SELECT QUERY_ID, START_TIME, USER_NAME, DATABASE_NAME, SCHEMA_NAME, TOTAL_ELAPSED_TIME, ERROR_MESSAGE FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE QUERY_TYPE = ''CALL'' AND DATABASE_NAME = ''' || database_name || ''' ORDER BY START_TIME DESC LIMIT 100;',
        'DBA'
    FROM procedure_risk

    UNION ALL

    SELECT
        CASE WHEN warehouse_name ILIKE 'WH_TRXS_%' OR database_name ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END,
        {db}.{schema}.OVERWATCH_DATABASE_ENVIRONMENT(database_name),
        database_name,
        NULL,
        warehouse_name,
        'Capacity',
        'Warehouse Pressure',
        CASE WHEN queued_queries >= 50 OR p95_elapsed_sec >= 300 THEN 'High' ELSE 'Medium' END,
        warehouse_name,
        warehouse_name,
        queued_queries || ' queued queries; p95 runtime ' || p95_elapsed_sec || 's in the last 24 hours.',
        queued_queries || ' queued queries; p95 runtime ' || p95_elapsed_sec || 's in the last 24 hours.',
        'Open Warehouse Health, inspect pressure evidence, and route changed-only warehouse setting recommendations.',
        'SELECT QUERY_ID, START_TIME, USER_NAME, WAREHOUSE_NAME, DATABASE_NAME, TOTAL_ELAPSED_TIME, QUEUED_OVERLOAD_TIME FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) AND WAREHOUSE_NAME = ''' || warehouse_name || ''' ORDER BY START_TIME DESC LIMIT 100;',
        'DBA'
    FROM warehouse_pressure

    UNION ALL

    SELECT
        CASE WHEN database_name ILIKE 'TRXS_%' THEN 'Trexis' ELSE 'ALFA' END,
        {db}.{schema}.OVERWATCH_DATABASE_ENVIRONMENT(database_name),
        database_name,
        schema_name,
        NULL,
        'Change Control',
        'Grant/Revoke Activity',
        'Medium',
        COALESCE(database_name || '.' || schema_name, role_name, user_name, 'Account grant activity'),
        COALESCE(database_name || '.' || schema_name, role_name, user_name, 'Account grant activity'),
        change_count || ' grant/revoke statement(s) by ' || COALESCE(user_name, 'unknown user') || ' using role ' || COALESCE(role_name, 'unknown role') || '.',
        change_count || ' grant/revoke statement(s) by ' || COALESCE(user_name, 'unknown user') || ' using role ' || COALESCE(role_name, 'unknown role') || '.',
        'Open Security Posture, verify least-privilege approval, owner, ticket, and review date.',
        'SELECT QUERY_ID, START_TIME, USER_NAME, ROLE_NAME, DATABASE_NAME, QUERY_TYPE, QUERY_TEXT FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) AND (QUERY_TYPE ILIKE ''GRANT%'' OR QUERY_TYPE ILIKE ''REVOKE%'' OR QUERY_TEXT ILIKE ''GRANT %'' OR QUERY_TEXT ILIKE ''REVOKE %'') ORDER BY START_TIME DESC LIMIT 100;',
        'DBA'
    FROM privilege_changes

    UNION ALL

    SELECT
        CASE WHEN warehouse_name ILIKE 'WH_TRXS_%' THEN 'Trexis' ELSE 'ALFA' END,
        'No Database Context',
        NULL,
        NULL,
        warehouse_name,
        'Change Control',
        'Warehouse Setting Change',
        'Medium',
        warehouse_name,
        warehouse_name,
        change_count || ' ALTER WAREHOUSE statement(s) by ' || COALESCE(user_name, 'unknown user') || ' using role ' || COALESCE(role_name, 'unknown role') || '.',
        change_count || ' ALTER WAREHOUSE statement(s) by ' || COALESCE(user_name, 'unknown user') || ' using role ' || COALESCE(role_name, 'unknown role') || '.',
        'Open DBA Tools warehouse settings manager and verify changed-only SQL, approval, and rollback evidence.',
        'SELECT QUERY_ID, START_TIME, USER_NAME, ROLE_NAME, WAREHOUSE_NAME, QUERY_TEXT FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD(''hour'', -24, CURRENT_TIMESTAMP()) AND QUERY_TEXT ILIKE ''ALTER WAREHOUSE %'' ORDER BY START_TIME DESC LIMIT 100;',
        'DBA'
    FROM warehouse_changes
)
SELECT
    CURRENT_TIMESTAMP(),
    c.company,
    c.environment,
    c.database_name,
    c.schema_name,
    c.warehouse_name,
    c.category,
    c.alert_type,
    c.severity,
    c.entity_name,
    c.entity,
    c.message,
    c.detail,
    c.suggested_action,
    c.proof_query,
    c.owner,
    'New',
    'EMAIL',
    {email},
    {email},
    'OVERWATCH ' || c.severity || ': ' || c.alert_type || ' - ' || c.entity_name,
    'Company: ' || c.company || CHAR(10)
      || 'Environment: ' || c.environment || CHAR(10)
      || 'Severity: ' || c.severity || CHAR(10)
      || 'Alert: ' || c.alert_type || CHAR(10)
      || 'Entity: ' || c.entity_name || CHAR(10) || CHAR(10)
      || 'Detail:' || CHAR(10) || c.message || CHAR(10) || CHAR(10)
      || 'Next action:' || CHAR(10) || c.suggested_action || CHAR(10) || CHAR(10)
      || 'Proof query:' || CHAR(10) || c.proof_query,
    'EMAIL_READY'
FROM candidates c
WHERE NOT EXISTS (
    SELECT 1
    FROM {db}.{schema}.{annotation_table} ann
    WHERE ann.active = TRUE
      AND ann.suppress_alerts = TRUE
      AND (UPPER(ann.entity) = UPPER(c.entity_name)
           OR UPPER(ann.entity) = UPPER(COALESCE(c.warehouse_name, ''))
           OR UPPER(ann.entity_type) = 'GLOBAL')
      AND CURRENT_TIMESTAMP() BETWEEN ann.window_start AND ann.window_end
)
AND NOT EXISTS (
    SELECT 1
    FROM {db}.{schema}.{table} existing
    WHERE existing.alert_ts >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
      AND COALESCE(existing.category, existing.alert_type, '') = c.category
      AND COALESCE(existing.entity_name, existing.entity, '') = c.entity_name
      AND UPPER(COALESCE(existing.status, 'New')) NOT IN ('FIXED', 'IGNORED', 'RESOLVED')
);

ALTER TASK {db}.{schema}.OVERWATCH_ANOMALY_CHECK RESUME;

SHOW TASKS LIKE 'OVERWATCH_ANOMALY_CHECK' IN SCHEMA {db}.{schema};
"""
