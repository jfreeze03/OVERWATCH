"""Alert rule catalog and audit helpers for OVERWATCH.

This module owns DBA-managed alert rule defaults, rule normalization, rule
configuration reads, and review/audit SQL for rule updates. Runtime alert
triage, delivery, native alert deployment, and action-queue routing remain in
focused sibling modules.
"""
from __future__ import annotations

import pandas as pd

from config import ALERT_DB, ALERT_SCHEMA

from .alert_status import normalize_alert_severity
from .query import run_query, safe_identifier
from .sql_safe import sql_literal


ALERT_RULE_AUDIT_TABLE = "OVERWATCH_ALERT_RULE_AUDIT"


DEFAULT_ALERT_RULES = [
    {
        "RULE_ID": "COST_CREDIT_SPIKE",
        "CATEGORY": "Cost Control",
        "ALERT_TYPE": "Credit Spike",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA / Cost owner",
        "ROUTE": "Cost & Contract",
        "RUNBOOK": "Explain the usage movement, identify route-backed drivers, and route cost-control actions.",
    },
    {
        "RULE_ID": "CORTEX_SPEND_AND_QUOTA",
        "CATEGORY": "Cost Control",
        "ALERT_TYPE": "Cortex Spend And Quota",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA / AI cost route",
        "ROUTE": "Cost & Contract",
        "RUNBOOK": "Review shared AI spend threshold, per-user quota, first/last usage, and access expansion before enforcing controls.",
    },
    {
        "RULE_ID": "QUERY_HIGH_ERROR_RATE",
        "CATEGORY": "Reliability",
        "ALERT_TYPE": "High Query Error Rate",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "DBA / Workload Route",
        "ROUTE": "Workload Operations",
        "RUNBOOK": "Group failures by error code/query text and route the response.",
    },
    {
        "RULE_ID": "TASK_FAILURE",
        "CATEGORY": "Reliability",
        "ALERT_TYPE": "Task Failure",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "DBA / Pipeline Route",
        "ROUTE": "Workload Operations",
        "RUNBOOK": "Review task graph impact, retry only after root cause, and confirm the next run.",
    },
    {
        "RULE_ID": "PROCEDURE_FAILURE_OR_SPIKE",
        "CATEGORY": "Reliability",
        "ALERT_TYPE": "Stored Procedure Failure / Runtime Spike",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "DBA / Procedure Route",
        "ROUTE": "Workload Operations",
        "RUNBOOK": "Compare release windows, inspect child queries, and confirm runtime/cost return to baseline.",
    },
    {
        "RULE_ID": "WAREHOUSE_PRESSURE",
        "CATEGORY": "Capacity",
        "ALERT_TYPE": "Warehouse Pressure",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA / Platform",
        "ROUTE": "Warehouse Health",
        "RUNBOOK": "Inspect queue/spill telemetry and route changed-only warehouse setting recommendations.",
    },
    {
        "RULE_ID": "GRANT_REVOKE_ACTIVITY",
        "CATEGORY": "Change Monitoring",
        "ALERT_TYPE": "Grant/Revoke Activity",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA / Security",
        "ROUTE": "Security Posture",
        "RUNBOOK": "Check least-privilege telemetry, route, reviewer, and review date.",
    },
    {
        "RULE_ID": "WAREHOUSE_SETTING_CHANGE",
        "CATEGORY": "Change Monitoring",
        "ALERT_TYPE": "Warehouse Setting Change",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA / Platform",
        "ROUTE": "Change & Drift",
        "RUNBOOK": "Check changed-only action, rollback path, and post-change telemetry.",
    },
    {
        "RULE_ID": "SECURITY_PRIVILEGE_ESCALATION",
        "CATEGORY": "Security",
        "ALERT_TYPE": "Privileged Role Grant",
        "DEFAULT_SEVERITY": "Critical",
        "SLA_HOURS": 4,
        "OWNER": "Security Review",
        "ROUTE": "Security Posture",
        "RUNBOOK": "Check ticket, reviewer, MFA posture, service-account purpose, and review date before accepting privileged role expansion.",
    },
    {
        "RULE_ID": "SECURITY_SENSITIVE_EXPORT",
        "CATEGORY": "Security",
        "ALERT_TYPE": "Sensitive Access Or Export",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "DBA / Security",
        "ROUTE": "Security Posture",
        "RUNBOOK": "Inspect source IP, role, query_id, destination stage, object access, masking policy coverage, and review status.",
    },
    {
        "RULE_ID": "PERF_QUERY_PRESSURE",
        "CATEGORY": "Performance",
        "ALERT_TYPE": "Query Pressure",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "DBA / Platform",
        "ROUTE": "Workload Operations",
        "RUNBOOK": "Open Query Investigation or Performance & Contention with query_id, queue/spill/lock telemetry, route, and specific optimization path.",
    },
    {
        "RULE_ID": "PIPELINE_COPY_FAILURE",
        "CATEGORY": "Task / Pipeline",
        "ALERT_TYPE": "Copy Load Failure",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "DBA / Data Engineering",
        "ROUTE": "Workload Operations",
        "RUNBOOK": "Group by table/stage/error, fix load cause, confirm downstream task graph freshness, and document SLA recovery.",
    },
    {
        "RULE_ID": "DQ_FRESHNESS_SLA",
        "CATEGORY": "Data Quality",
        "ALERT_TYPE": "Freshness SLA Missed",
        "DEFAULT_SEVERITY": "High",
        "SLA_HOURS": 8,
        "OWNER": "Data Route",
        "ROUTE": "Workload Operations",
        "RUNBOOK": "Use configured database/schema/table/column/check threshold, confirm latest update/load volume, and route to the data team.",
    },
    {
        "RULE_ID": "OPT_UNUSED_OR_OVERSIZED_WAREHOUSE",
        "CATEGORY": "Optimization",
        "ALERT_TYPE": "Unused Or Oversized Warehouse",
        "DEFAULT_SEVERITY": "Medium",
        "SLA_HOURS": 24,
        "OWNER": "DBA / Cost owner",
        "ROUTE": "Optimization Advisor",
        "RUNBOOK": "Record metering/query telemetry, review status, rollback path, and expected savings before changing warehouse settings.",
    },
]


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
        "RUNBOOK": "Review alert telemetry and route confirmed findings to the DBA action queue.",
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
        raise ValueError("Route is required.")
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
