# utils/alerts.py - alert framework facade, catalog, triage, and annotations
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from config import (
    ALERT_DB,
    ALERT_DELIVERY_METHOD,
    ALERT_SCHEMA,
    ALERT_TABLE,
)
from .compatibility import filter_existing_columns
from .company_filter import (
    company_value_allowed,
    environment_value_allowed,
    get_active_environment,
    get_environment_db_patterns,
)
from .query import (
    run_query,
    safe_identifier,
    sql_literal,
)
from .alert_action_queue import alert_history_to_actions, mark_alerts_routed
from .alert_delivery import (
    ALERT_DELIVERY_LOG_TABLE,
    DEFAULT_ALERT_RECIPIENT,
    alert_delivery_log_fqn,
    alert_delivery_status_for_target,
    alert_recipient_label,
    build_alert_delivery_log_ddl,
    build_alert_delivery_log_insert_sql,
    build_alert_delivery_mark_sql,
    build_alert_email_body,
    build_alert_email_delivery_procedure_sql,
    build_alert_email_subject,
    current_alert_recipient,
    load_alert_delivery_log,
    log_alert_digest_delivery,
    send_teams_alert,
)
from .alert_native_catalog import (
    ALERT_DATA_QUALITY_CHECK_TABLE,
    ALERT_NATIVE_OBJECT_REGISTRY_TABLE,
    ALERT_REMEDIATION_DRY_RUN_TABLE,
    ALERT_REMEDIATION_POLICY_TABLE,
    _values_clause,
    build_alert_data_quality_check_seed_rows,
    build_alert_data_quality_checks_ddl,
    build_alert_native_deployment_review_rows,
    build_alert_native_deployment_review_sql,
    build_alert_native_object_registry_seed_rows,
    build_alert_native_registry_ddl,
    build_alert_remediation_policy_seed_rows,
    build_alert_remediation_policy_ddl,
    build_alert_threshold_seed_rows,
    load_alert_native_object_registry,
    load_alert_remediation_dry_runs,
    load_alert_remediation_policy,
)
from .alert_catalog import (
    ALERT_RULE_AUDIT_TABLE,
    alert_rule_audit_fqn,
    alert_rule_catalog,
    build_alert_rule_audit_ddl,
    build_alert_rule_audit_insert_sql,
    build_alert_rule_update_sql,
    load_alert_rule_audit,
    load_alert_rule_catalog,
    normalize_alert_rule_frame,
    update_alert_rule,
)


ANNOTATION_TABLE = "OVERWATCH_ANNOTATIONS"


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



def alert_environment_values(environment: str | None) -> list[str]:
    env = str(environment or get_active_environment() or "ALL").upper()
    if env == "ALL":
        return []
    values = [env]
    values.extend(str(value).upper() for value in get_environment_db_patterns(env))
    if env == "DEV_ALL":
        values.extend(["ALL DEV/SIT", "OTHER ALFA NON-PROD"])
    return list(dict.fromkeys(value for value in values if value))


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
    if status.upper() in {"CONFIG REQUIRED", "CONFIG_REQUIRED"}:
        return "Config Required"
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
        ["", "DBA", "DBA / COST OWNER", "DBA / PLATFORM", "DBA / SECURITY", "DBA / PIPELINE OWNER"]
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
        "needs_owner": int(owners.isin(["", "DBA", "DBA / COST OWNER", "DBA / PLATFORM", "DBA / SECURITY", "DBA / PIPELINE OWNER"]).sum()),
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
        f"- Needs route: {summary['needs_owner']}",
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
            action = _row_value(row, "SUGGESTED_ACTION", default="Review alert telemetry and route to action queue.")
            lines.append(f"- [{severity} / {sla_state}] {alert_type} on {entity}; route={owner}; action={action}")
    lines.extend([
        "",
        "Required operator handling:",
        "- Route confirmed alerts to the Action Queue.",
        "- Add ticket, route, reviewer, and telemetry status before closure.",
        "- Mark false positives Ignored with reason, not silently deleted.",
    ])
    return "\n".join(lines)


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
        "DELIVERY_STATUS": alert_delivery_status_for_target(default_email),
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
            {_coalesce_sql(columns, "DELIVERY_STATUS", default=sql_literal(alert_delivery_status_for_target(DEFAULT_ALERT_RECIPIENT)))} AS DELIVERY_STATUS,
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
    view["DELIVERY_STATUS"] = alerts["DELIVERY_STATUS"].fillna(alert_delivery_status_for_target(DEFAULT_ALERT_RECIPIENT)).astype(str)
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
    view["NEXT_ACTION"] = _first_series(rows, "NEXT_ACTION", "Action", default="Review the control-room telemetry.").astype(str)
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
     {sql_literal(alert_delivery_status_for_target(email_target))});
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
        raise ValueError("Escalation acknowledgment requires a note with telemetry or route context.")
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


def build_annotation_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Generate DDL for the OVERWATCH_ANNOTATIONS table."""
    return f"""-- OVERWATCH Annotation System
-- Prevents re-alerting on known events such as high-volume validation windows, deployments, or planned maintenance.

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
        COALESCE(r.OWNER, a.OWNER, 'DBA') AS ROUTED_OWNER,
        NULL AS OWNER_EMAIL,
        COALESCE(r.OWNER, a.OWNER, 'DBA On-Call') AS ONCALL_PRIMARY,
        NULL AS ONCALL_SECONDARY,
        NULL AS APPROVAL_GROUP,
        COALESCE(r.OWNER, a.ESCALATED_TO, a.OWNER, 'DBA Lead') AS OWNER_ESCALATION_TARGET,
        CASE WHEN r.OWNER IS NOT NULL THEN 'ALERT_RULE' ELSE 'ALERT_ROW' END AS OWNER_SOURCE,
        CASE WHEN r.OWNER IS NOT NULL THEN 'Matched alert rule owner' ELSE 'Using alert row owner or DBA fallback' END AS OWNER_EVIDENCE,
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
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY COALESCE(TO_VARCHAR(a.ALERT_ID), TO_VARCHAR(a.ALERT_TS), COALESCE(a.ENTITY_NAME, a.ENTITY, 'UNKNOWN'))
        ORDER BY COALESCE(r.SLA_HOURS, 0) DESC
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


ALERT_COMMAND_CENTER_TABLES = (
    "ALERT_CONFIG",
    "ALERT_EVENTS",
    "ALERT_RUN_HISTORY",
    "ALERT_ACKNOWLEDGEMENTS",
    "ALERT_REMEDIATION_LOG",
    "ALERT_NOTIFICATION_LOG",
    "ALERT_THRESHOLDS",
    "ALERT_OWNER_ROUTING",
)
ALERT_COMMAND_CENTER_CATEGORIES = (
    "Security",
    "Cost",
    "Performance",
    "Task / Pipeline",
    "Data Quality",
    "Optimization",
)


def _command_center_fqn(
    object_name: str,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    *,
    quoted: bool = True,
) -> str:
    if quoted:
        return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(object_name)}"
    return f"{db}.{schema}.{object_name}"


def _alert_event_id_expr(event_id: int | str) -> str:
    return f"TRY_TO_NUMBER({sql_literal(str(event_id or '').strip(), 100)})"


def build_alert_acknowledgement_insert_sql(
    *,
    event_id: int | str,
    alert_key: str = "",
    note: str,
    actor: str = "OVERWATCH",
    owner: str = "",
    status_after_ack: str = "Acknowledged",
    next_checkpoint_hours: int | None = None,
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Return an insert into ALERT_ACKNOWLEDGEMENTS for auditable alert lifecycle actions."""
    note_clean = str(note or "").strip()
    if len(note_clean) < 5:
        raise ValueError("Alert acknowledgement requires a note with route, ticket, or investigation context.")
    checkpoint_expr = "NULL"
    if next_checkpoint_hours is not None:
        checkpoint_expr = f"DATEADD('hour', {max(1, int(next_checkpoint_hours))}, CURRENT_TIMESTAMP())"
    return f"""
INSERT INTO {_command_center_fqn("ALERT_ACKNOWLEDGEMENTS", db, schema)}
    (EVENT_ID, ALERT_KEY, ACKNOWLEDGED_AT, ACKNOWLEDGED_BY, ACK_NOTE,
     STATUS_AFTER_ACK, OWNER_ASSIGNED, NEXT_CHECKPOINT_AT)
SELECT
    {_alert_event_id_expr(event_id)} AS EVENT_ID,
    {sql_literal(alert_key, 200)} AS ALERT_KEY,
    CURRENT_TIMESTAMP() AS ACKNOWLEDGED_AT,
    {sql_literal(actor, 200)} AS ACKNOWLEDGED_BY,
    {sql_literal(note_clean, 4000)} AS ACK_NOTE,
    {sql_literal(normalize_alert_status(status_after_ack), 40)} AS STATUS_AFTER_ACK,
    NULLIF({sql_literal(owner, 200)}, '') AS OWNER_ASSIGNED,
    {checkpoint_expr} AS NEXT_CHECKPOINT_AT;
""".strip()


def build_alert_remediation_log_insert_sql(
    *,
    event_id: int | str,
    alert_key: str = "",
    remediation_mode: str = "RECOMMEND",
    action_type: str,
    action_sql: str = "",
    before_state: str = "",
    after_state: str = "",
    execution_status: str = "REQUESTED",
    error_message: str = "",
    rollback_guidance: str = "",
    affected_user: str = "",
    affected_object: str = "",
    affected_warehouse: str = "",
    affected_task: str = "",
    verification_sql: str = "",
    verification_result: str = "",
    actor: str = "OVERWATCH",
    approved_by: str = "",
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """Return an insert into ALERT_REMEDIATION_LOG; callers still decide whether to execute."""
    action_type_clean = str(action_type or "").strip()
    if not action_type_clean:
        raise ValueError("Alert remediation log requires an action type.")
    mode = str(remediation_mode or "RECOMMEND").upper().replace(" ", "_")
    if mode in {"APPROVAL_REQUIRED", "VERIFICATION_REQUIRED"}:
        mode = "STATUS_REVIEW"
    if mode not in {"OFF", "RECOMMEND", "STATUS_REVIEW", "AUTO"}:
        mode = "RECOMMEND"
    approved_at_expr = "CURRENT_TIMESTAMP()" if str(approved_by or "").strip() else "NULL"
    approved_by_expr = f"NULLIF({sql_literal(approved_by, 200)}, '')"
    return f"""
INSERT INTO {_command_center_fqn("ALERT_REMEDIATION_LOG", db, schema)}
    (EVENT_ID, ALERT_KEY, REQUESTED_AT, REQUESTED_BY, APPROVED_AT, APPROVED_BY,
     REMEDIATION_MODE, ACTION_TYPE, ACTION_SQL, BEFORE_STATE, AFTER_STATE,
     EXECUTION_STATUS, ERROR_MESSAGE, ROLLBACK_GUIDANCE, AFFECTED_USER,
     AFFECTED_OBJECT, AFFECTED_WAREHOUSE, AFFECTED_TASK, VERIFICATION_SQL,
     VERIFICATION_RESULT)
SELECT
    {_alert_event_id_expr(event_id)} AS EVENT_ID,
    {sql_literal(alert_key, 200)} AS ALERT_KEY,
    CURRENT_TIMESTAMP() AS REQUESTED_AT,
    {sql_literal(actor, 200)} AS REQUESTED_BY,
    {approved_at_expr} AS APPROVED_AT,
    {approved_by_expr} AS APPROVED_BY,
    {sql_literal(mode, 40)} AS REMEDIATION_MODE,
    {sql_literal(action_type_clean, 100)} AS ACTION_TYPE,
    {sql_literal(action_sql, 16000)} AS ACTION_SQL,
    {sql_literal(before_state, 8000)} AS BEFORE_STATE,
    {sql_literal(after_state, 8000)} AS AFTER_STATE,
    {sql_literal(execution_status, 100)} AS EXECUTION_STATUS,
    {sql_literal(error_message, 4000)} AS ERROR_MESSAGE,
    {sql_literal(rollback_guidance, 4000)} AS ROLLBACK_GUIDANCE,
    NULLIF({sql_literal(affected_user, 300)}, '') AS AFFECTED_USER,
    NULLIF({sql_literal(affected_object, 500)}, '') AS AFFECTED_OBJECT,
    NULLIF({sql_literal(affected_warehouse, 300)}, '') AS AFFECTED_WAREHOUSE,
    NULLIF({sql_literal(affected_task, 500)}, '') AS AFFECTED_TASK,
    {sql_literal(verification_sql, 16000)} AS VERIFICATION_SQL,
    {sql_literal(verification_result, 8000)} AS VERIFICATION_RESULT;
""".strip()


def build_alert_event_materialization_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    *,
    days: int = 7,
) -> str:
    days = max(1, min(int(days or 7), 90))
    triage_view = alert_triage_view_fqn(db=db, schema=schema, quoted=True)
    events_table = _command_center_fqn("ALERT_EVENTS", db, schema)
    config_table = _command_center_fqn("ALERT_CONFIG", db, schema)
    run_table = _command_center_fqn("ALERT_RUN_HISTORY", db, schema)
    return f"""-- Materialize current Alert Center rows into durable alert lifecycle events.
-- Safe to schedule after OVERWATCH_ALERTS / OVERWATCH_ALERT_TRIAGE_V are populated.
SET OVERWATCH_ALERT_RUN_ID = 'ALERT_ENGINE_' || TO_VARCHAR(CURRENT_TIMESTAMP(), 'YYYYMMDDHH24MISS');

INSERT INTO {run_table}
  (RUN_ID, STARTED_AT, STATUS, DATA_WINDOW_START, DATA_WINDOW_END, TELEMETRY_LATENCY_NOTE)
VALUES
  ($OVERWATCH_ALERT_RUN_ID, CURRENT_TIMESTAMP(), 'RUNNING',
   DATEADD('day', -{days}, CURRENT_TIMESTAMP()), CURRENT_TIMESTAMP(),
   'ACCOUNT_USAGE-backed alerts may lag; near-real-time task/event-table checks should be configured separately.');

MERGE INTO {events_table} tgt
USING (
  SELECT
    COALESCE(NULLIF(a.ALERT_TYPE, ''), NULLIF(a.CATEGORY, ''), 'OVERWATCH_ALERT') AS ALERT_KEY,
    COALESCE(a.COMPANY, 'Shared/Unclassified') AS COMPANY,
    COALESCE(a.ENVIRONMENT, 'No Database Context') AS ENVIRONMENT,
    COALESCE(a.ALERT_TS, CURRENT_TIMESTAMP()) AS EVENT_TS,
    COALESCE(a.ALERT_TS, CURRENT_TIMESTAMP()) AS FIRST_SEEN_AT,
    CURRENT_TIMESTAMP() AS LAST_SEEN_AT,
    CURRENT_TIMESTAMP() AS DETECTED_AT,
    COALESCE(a.CATEGORY, 'Alert Center') AS CATEGORY,
    COALESCE(a.SEVERITY, cfg.DEFAULT_SEVERITY, 'Medium') AS SEVERITY,
    COALESCE(a.STATUS, 'New') AS STATUS,
    COALESCE(a.MESSAGE, a.DETAIL, a.ALERT_RUNBOOK, 'Alert Center event') AS BUSINESS_IMPACT,
    CASE
      WHEN UPPER(COALESCE(a.CATEGORY, '')) LIKE '%COST%' THEN 'Potential spend or contract burn impact'
      WHEN UPPER(COALESCE(a.CATEGORY, '')) LIKE '%SECURITY%' THEN 'Potential access, data exposure, or control-plane impact'
      WHEN UPPER(COALESCE(a.CATEGORY, a.ALERT_TYPE, '')) REGEXP 'TASK|PIPELINE|PROCEDURE' THEN 'Potential production pipeline SLA impact'
      ELSE 'Operational risk requires route triage'
    END AS IMPACT_ESTIMATE,
    COALESCE(a.ROUTED_OWNER, a.OWNER, cfg.OWNER, 'DBA') AS OWNER,
    COALESCE(a.SUGGESTED_ACTION, a.ALERT_RUNBOOK, 'Review alert telemetry and assign route.') AS RECOMMENDED_ACTION,
    CASE
      WHEN UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) LIKE '%TASK%' THEN 'TASK'
      WHEN UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) LIKE '%WAREHOUSE%' THEN 'WAREHOUSE'
      WHEN UPPER(COALESCE(a.ALERT_TYPE, a.CATEGORY, '')) LIKE '%USER%' THEN 'USER'
      ELSE 'ALERT'
    END AS ENTITY_TYPE,
    COALESCE(a.ENTITY_NAME, a.ENTITY, 'Snowflake account') AS ENTITY_NAME,
    a.WAREHOUSE_NAME,
    a.DATABASE_NAME,
    a.SCHEMA_NAME,
    a.PROOF_QUERY,
    COALESCE(cfg.REMEDIATION_MODE, 'RECOMMEND') AS REMEDIATION_MODE,
    COALESCE(a.MESSAGE, a.DETAIL, '') AS EVIDENCE,
    SHA2(
      COALESCE(NULLIF(a.ALERT_TYPE, ''), NULLIF(a.CATEGORY, ''), 'OVERWATCH_ALERT') || '|' ||
      COALESCE(a.ENTITY_NAME, a.ENTITY, 'Snowflake account') || '|' ||
      TO_VARCHAR(DATE_TRUNC('hour', COALESCE(a.ALERT_TS, CURRENT_TIMESTAMP()))) || '|' ||
      COALESCE(a.MESSAGE, a.DETAIL, ''),
      256
    ) AS DEDUPE_KEY,
    OBJECT_CONSTRUCT_KEEP_NULL(
      'ALERT_ID', a.ALERT_ID,
      'SLA_STATE', a.SLA_STATE,
      'ALERT_ROUTE', a.ALERT_ROUTE,
      'ESCALATION_TARGET', a.ESCALATION_TARGET
    ) AS RAW_EVENT
  FROM {triage_view} a
  LEFT JOIN {config_table} cfg
    ON UPPER(cfg.ALERT_KEY) = UPPER(COALESCE(NULLIF(a.ALERT_TYPE, ''), NULLIF(a.CATEGORY, ''), 'OVERWATCH_ALERT'))
  WHERE COALESCE(a.ALERT_TS, CURRENT_TIMESTAMP()) >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
) src
ON tgt.DEDUPE_KEY = src.DEDUPE_KEY
WHEN MATCHED THEN UPDATE SET
  LAST_SEEN_AT = src.LAST_SEEN_AT,
  COMPANY = src.COMPANY,
  ENVIRONMENT = src.ENVIRONMENT,
  STATUS = src.STATUS,
  SEVERITY = src.SEVERITY,
  OWNER = src.OWNER,
  RECOMMENDED_ACTION = src.RECOMMENDED_ACTION,
  EVIDENCE = src.EVIDENCE,
  RAW_EVENT = src.RAW_EVENT
WHEN NOT MATCHED THEN INSERT
  (ALERT_KEY, COMPANY, ENVIRONMENT, EVENT_TS, FIRST_SEEN_AT, LAST_SEEN_AT, DETECTED_AT, CATEGORY, SEVERITY, STATUS,
   BUSINESS_IMPACT, IMPACT_ESTIMATE, OWNER, RECOMMENDED_ACTION, ENTITY_TYPE, ENTITY_NAME,
   WAREHOUSE_NAME, DATABASE_NAME, SCHEMA_NAME, PROOF_QUERY, REMEDIATION_MODE, EVIDENCE, DEDUPE_KEY, RAW_EVENT)
VALUES
  (src.ALERT_KEY, src.COMPANY, src.ENVIRONMENT, src.EVENT_TS, src.FIRST_SEEN_AT, src.LAST_SEEN_AT, src.DETECTED_AT, src.CATEGORY, src.SEVERITY, src.STATUS,
   src.BUSINESS_IMPACT, src.IMPACT_ESTIMATE, src.OWNER, src.RECOMMENDED_ACTION, src.ENTITY_TYPE, src.ENTITY_NAME,
   src.WAREHOUSE_NAME, src.DATABASE_NAME, src.SCHEMA_NAME, src.PROOF_QUERY, src.REMEDIATION_MODE, src.EVIDENCE, src.DEDUPE_KEY, src.RAW_EVENT);

UPDATE {run_table}
SET COMPLETED_AT = CURRENT_TIMESTAMP(),
    STATUS = 'SUCCESS',
    ALERTS_EVALUATED = (SELECT COUNT(*) FROM {triage_view} WHERE COALESCE(ALERT_TS, CURRENT_TIMESTAMP()) >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())),
    ALERTS_CREATED = (SELECT COUNT(*) FROM {events_table} WHERE DETECTED_AT >= DATEADD('minute', -10, CURRENT_TIMESTAMP()))
WHERE RUN_ID = $OVERWATCH_ALERT_RUN_ID;
"""


def build_alert_command_center_setup_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
) -> str:
    """DDL for proactive alert monitoring configuration, event, and audit objects."""
    threshold_rows = build_alert_threshold_seed_rows()
    threshold_columns = [
        "THRESHOLD_KEY",
        "CATEGORY",
        "SIGNAL_NAME",
        "SEVERITY",
        "THRESHOLD_VALUE",
        "BASELINE_WINDOW_DAYS",
        "CURRENT_WINDOW_MINUTES",
        "OWNER",
        "NOTIFICATION_CHANNEL",
    ]
    threshold_values = _values_clause(threshold_rows, threshold_columns)
    config_values = _values_clause([
        {
            "ALERT_KEY": row["THRESHOLD_KEY"],
            "CATEGORY": row["CATEGORY"],
            "SIGNAL_NAME": row["SIGNAL_NAME"],
            "SEVERITY": row["SEVERITY"],
            "OWNER": row["OWNER"],
            "ROUTE": {
                "Security": "Security Posture",
                "Cost": "Cost & Contract",
                "Performance": "Workload Operations",
                "Task / Pipeline": "Workload Operations",
                "Data Quality": "Workload Operations",
                "Optimization": "Optimization Advisor",
            }.get(str(row["CATEGORY"]), "Alert Center"),
            "NOTIFICATION_CHANNEL": row["NOTIFICATION_CHANNEL"],
        }
        for row in threshold_rows
    ], [
        "ALERT_KEY",
        "CATEGORY",
        "SIGNAL_NAME",
        "SEVERITY",
        "OWNER",
        "ROUTE",
        "NOTIFICATION_CHANNEL",
    ])
    return f"""-- OVERWATCH Alert Monitoring
-- DBA-grade alert detection, acknowledgement, notification, and remediation audit contract.
-- ACCOUNT_USAGE views can lag; ALERT_CONFIG.TELEMETRY_LATENCY documents delayed vs near-real-time checks.

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_CONFIG", db, schema)} (
  ALERT_KEY                 VARCHAR(200) PRIMARY KEY,
  CATEGORY                  VARCHAR(100) NOT NULL,
  SIGNAL_NAME               VARCHAR(200) NOT NULL,
  DESCRIPTION               VARCHAR(4000),
  DEFAULT_SEVERITY          VARCHAR(20) DEFAULT 'Medium',
  ENABLED                   BOOLEAN DEFAULT TRUE,
  OWNER                     VARCHAR(200),
  ROUTE                     VARCHAR(200),
  BUSINESS_IMPACT_WEIGHT    NUMBER DEFAULT 50,
  DETECTION_SQL             VARCHAR(16000),
  TELEMETRY_SOURCE          VARCHAR(500),
  TELEMETRY_LATENCY         VARCHAR(200),
  NOTIFICATION_CHANNEL      VARCHAR(200),
  REMEDIATION_MODE          VARCHAR(40) DEFAULT 'RECOMMEND',
  DEDUPE_WINDOW_MINUTES     NUMBER DEFAULT 60,
  SUPPRESSION_WINDOW_MINUTES NUMBER DEFAULT 0,
  QUIET_HOURS_START         VARCHAR(20),
  QUIET_HOURS_END           VARCHAR(20),
  AUTO_RESOLVE_AFTER_HOURS  NUMBER DEFAULT 24,
  CREATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CREATED_BY                VARCHAR(200) DEFAULT CURRENT_USER(),
  UPDATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY                VARCHAR(200) DEFAULT CURRENT_USER()
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_THRESHOLDS", db, schema)} (
  THRESHOLD_KEY             VARCHAR(200) PRIMARY KEY,
  CATEGORY                  VARCHAR(100) NOT NULL,
  SIGNAL_NAME               VARCHAR(200) NOT NULL,
  SEVERITY                  VARCHAR(20) DEFAULT 'Medium',
  THRESHOLD_VALUE           FLOAT,
  BASELINE_WINDOW_DAYS      NUMBER DEFAULT 14,
  CURRENT_WINDOW_MINUTES    NUMBER DEFAULT 60,
  OWNER                     VARCHAR(200),
  NOTIFICATION_CHANNEL      VARCHAR(200),
  ENABLED                   BOOLEAN DEFAULT TRUE,
  UPDATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY                VARCHAR(200) DEFAULT CURRENT_USER()
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_EVENTS", db, schema)} (
  EVENT_ID                  NUMBER AUTOINCREMENT PRIMARY KEY,
  COMPANY                   VARCHAR(100),
  ENVIRONMENT               VARCHAR(100),
  ALERT_KEY                 VARCHAR(200),
  EVENT_TS                  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  FIRST_SEEN_AT             TIMESTAMP_NTZ,
  LAST_SEEN_AT              TIMESTAMP_NTZ,
  DETECTED_AT               TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  RESOLVED_AT               TIMESTAMP_NTZ,
  CATEGORY                  VARCHAR(100),
  SEVERITY                  VARCHAR(20),
  STATUS                    VARCHAR(40) DEFAULT 'New',
  BUSINESS_IMPACT           VARCHAR(4000),
  IMPACT_ESTIMATE           VARCHAR(1000),
  OWNER                     VARCHAR(200),
  RECOMMENDED_ACTION        VARCHAR(4000),
  ENTITY_TYPE               VARCHAR(100),
  ENTITY_NAME               VARCHAR(500),
  USER_NAME                 VARCHAR(300),
  ROLE_NAME                 VARCHAR(300),
  WAREHOUSE_NAME            VARCHAR(300),
  DATABASE_NAME             VARCHAR(300),
  SCHEMA_NAME               VARCHAR(300),
  OBJECT_NAME               VARCHAR(500),
  QUERY_ID                  VARCHAR(200),
  SOURCE_IP                 VARCHAR(200),
  BASELINE_VALUE            FLOAT,
  CURRENT_VALUE             FLOAT,
  THRESHOLD_VALUE           FLOAT,
  EVIDENCE                  VARCHAR(8000),
  PROOF_QUERY               VARCHAR(16000),
  REMEDIATION_MODE          VARCHAR(40) DEFAULT 'RECOMMEND',
  REMEDIATION_SQL           VARCHAR(16000),
  NOTIFICATION_STATUS       VARCHAR(100),
  DEDUPE_KEY                VARCHAR(500),
  RAW_EVENT                 VARIANT
);

ALTER TABLE IF EXISTS {_command_center_fqn("ALERT_EVENTS", db, schema)} ADD COLUMN IF NOT EXISTS COMPANY VARCHAR(100);
ALTER TABLE IF EXISTS {_command_center_fqn("ALERT_EVENTS", db, schema)} ADD COLUMN IF NOT EXISTS ENVIRONMENT VARCHAR(100);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_RUN_HISTORY", db, schema)} (
  RUN_ID                    VARCHAR(200) PRIMARY KEY,
  STARTED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  COMPLETED_AT              TIMESTAMP_NTZ,
  STATUS                    VARCHAR(40),
  ALERTS_EVALUATED          NUMBER DEFAULT 0,
  ALERTS_CREATED            NUMBER DEFAULT 0,
  ALERTS_RESOLVED           NUMBER DEFAULT 0,
  ERROR_MESSAGE             VARCHAR(4000),
  DATA_WINDOW_START         TIMESTAMP_NTZ,
  DATA_WINDOW_END           TIMESTAMP_NTZ,
  TELEMETRY_LATENCY_NOTE    VARCHAR(2000),
  RUN_BY                    VARCHAR(200) DEFAULT CURRENT_USER()
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_ACKNOWLEDGEMENTS", db, schema)} (
  ACK_ID                    NUMBER AUTOINCREMENT PRIMARY KEY,
  EVENT_ID                  NUMBER,
  ALERT_KEY                 VARCHAR(200),
  ACKNOWLEDGED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  ACKNOWLEDGED_BY           VARCHAR(200) DEFAULT CURRENT_USER(),
  ACK_NOTE                  VARCHAR(4000),
  STATUS_AFTER_ACK          VARCHAR(40) DEFAULT 'Acknowledged',
  OWNER_ASSIGNED            VARCHAR(200),
  NEXT_CHECKPOINT_AT        TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_NOTIFICATION_LOG", db, schema)} (
  NOTIFICATION_ID           NUMBER AUTOINCREMENT PRIMARY KEY,
  EVENT_ID                  NUMBER,
  ALERT_KEY                 VARCHAR(200),
  NOTIFICATION_TS           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CHANNEL                   VARCHAR(200),
  DESTINATION               VARCHAR(500),
  SEVERITY                  VARCHAR(20),
  STATUS                    VARCHAR(100),
  DEDUPE_KEY                VARCHAR(500),
  ESCALATION_LEVEL          NUMBER DEFAULT 0,
  ERROR_MESSAGE             VARCHAR(4000),
  PAYLOAD                   VARIANT,
  SENT_BY                   VARCHAR(200) DEFAULT CURRENT_USER()
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_REMEDIATION_LOG", db, schema)} (
  REMEDIATION_ID            NUMBER AUTOINCREMENT PRIMARY KEY,
  EVENT_ID                  NUMBER,
  ALERT_KEY                 VARCHAR(200),
  REQUESTED_AT              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  REQUESTED_BY              VARCHAR(200) DEFAULT CURRENT_USER(),
  APPROVED_AT               TIMESTAMP_NTZ,
  APPROVED_BY               VARCHAR(200),
  REMEDIATION_MODE          VARCHAR(40),
  ACTION_TYPE               VARCHAR(100),
  ACTION_SQL                VARCHAR(16000),
  BEFORE_STATE              VARCHAR(8000),
  AFTER_STATE               VARCHAR(8000),
  EXECUTION_STATUS          VARCHAR(100),
  ERROR_MESSAGE             VARCHAR(4000),
  ROLLBACK_GUIDANCE         VARCHAR(4000),
  AFFECTED_USER             VARCHAR(300),
  AFFECTED_OBJECT           VARCHAR(500),
  AFFECTED_WAREHOUSE        VARCHAR(300),
  AFFECTED_TASK             VARCHAR(500),
  VERIFICATION_SQL          VARCHAR(16000),
  VERIFICATION_RESULT       VARCHAR(8000)
);

CREATE TABLE IF NOT EXISTS {_command_center_fqn("ALERT_OWNER_ROUTING", db, schema)} (
  ROUTE_KEY                 VARCHAR(200) PRIMARY KEY,
  CATEGORY                  VARCHAR(100),
  ENTITY_TYPE               VARCHAR(100),
  ENTITY_PATTERN            VARCHAR(500),
  OWNER_NAME                VARCHAR(200),
  OWNER_EMAIL               VARCHAR(500),
  ONCALL_PRIMARY            VARCHAR(200),
  ONCALL_SECONDARY          VARCHAR(200),
  APPROVAL_GROUP            VARCHAR(200),
  ESCALATION_TARGET         VARCHAR(200),
  NOTIFICATION_CHANNEL      VARCHAR(200),
  SEVERITY_MIN              VARCHAR(20) DEFAULT 'Medium',
  SERVICE_TIER              VARCHAR(40) DEFAULT 'Tier 2',
  ACTIVE                    BOOLEAN DEFAULT TRUE,
  UPDATED_AT                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  UPDATED_BY                VARCHAR(200) DEFAULT CURRENT_USER()
);

{build_alert_data_quality_checks_ddl(db=db, schema=schema).strip()}

{build_alert_native_registry_ddl(db=db, schema=schema).strip()}

{build_alert_remediation_policy_ddl(db=db, schema=schema).strip()}

{build_alert_native_deployment_review_sql(db=db, schema=schema).strip()}

MERGE INTO {_command_center_fqn("ALERT_THRESHOLDS", db, schema)} tgt
USING (
  SELECT * FROM VALUES
    {threshold_values}
) src({", ".join(threshold_columns)})
ON tgt.THRESHOLD_KEY = src.THRESHOLD_KEY
WHEN MATCHED THEN UPDATE SET
  CATEGORY = src.CATEGORY,
  SIGNAL_NAME = src.SIGNAL_NAME,
  SEVERITY = src.SEVERITY,
  THRESHOLD_VALUE = src.THRESHOLD_VALUE,
  BASELINE_WINDOW_DAYS = src.BASELINE_WINDOW_DAYS,
  CURRENT_WINDOW_MINUTES = src.CURRENT_WINDOW_MINUTES,
  OWNER = src.OWNER,
  NOTIFICATION_CHANNEL = src.NOTIFICATION_CHANNEL,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  ({", ".join(threshold_columns)})
VALUES
  ({", ".join("src." + column for column in threshold_columns)});

MERGE INTO {_command_center_fqn("ALERT_CONFIG", db, schema)} tgt
USING (
  SELECT * FROM VALUES
    {config_values}
) src(ALERT_KEY, CATEGORY, SIGNAL_NAME, DEFAULT_SEVERITY, OWNER, ROUTE, NOTIFICATION_CHANNEL)
ON tgt.ALERT_KEY = src.ALERT_KEY
WHEN MATCHED THEN UPDATE SET
  CATEGORY = src.CATEGORY,
  SIGNAL_NAME = src.SIGNAL_NAME,
  DEFAULT_SEVERITY = src.DEFAULT_SEVERITY,
  OWNER = src.OWNER,
  ROUTE = src.ROUTE,
  NOTIFICATION_CHANNEL = src.NOTIFICATION_CHANNEL,
  UPDATED_AT = CURRENT_TIMESTAMP(),
  UPDATED_BY = CURRENT_USER()
WHEN NOT MATCHED THEN INSERT
  (ALERT_KEY, CATEGORY, SIGNAL_NAME, DEFAULT_SEVERITY, OWNER, ROUTE, NOTIFICATION_CHANNEL, TELEMETRY_LATENCY)
VALUES
  (src.ALERT_KEY, src.CATEGORY, src.SIGNAL_NAME, src.DEFAULT_SEVERITY, src.OWNER, src.ROUTE, src.NOTIFICATION_CHANNEL, 'ACCOUNT_USAGE delayed unless otherwise documented');
"""


def build_alert_signal_query_catalog(hours: int = 24) -> pd.DataFrame:
    """Return bounded, Snowflake-native detection query templates for the Alert Center."""
    hours = max(1, min(int(hours or 24), 168))
    rows = [
        {
            "CATEGORY": "Security",
            "SIGNAL": "Failed login spike",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY",
            "FRESHNESS": "Delayed ACCOUNT_USAGE telemetry",
            "OWNER": "DBA / Security",
            "WHY_THIS_MATTERS": "Password spray, stale automation secrets, or compromised users can show up before an incident ticket exists.",
            "RECOMMENDED_ACTION": "Group by user, source IP, client, error code, and country; lock down risky routes through IAM/security review.",
            "SQL": f"""
WITH recent AS (
  SELECT USER_NAME, CLIENT_IP, REPORTED_CLIENT_TYPE, ERROR_CODE, COUNT(*) AS FAILED_LOGINS
  FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
  WHERE EVENT_TIMESTAMP >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
    AND IS_SUCCESS = 'NO'
  GROUP BY 1,2,3,4
),
baseline AS (
  SELECT USER_NAME, AVG(DAILY_FAILS) AS AVG_DAILY_FAILS
  FROM (
    SELECT USER_NAME, DATE_TRUNC('day', EVENT_TIMESTAMP) AS EVENT_DAY, COUNT(*) AS DAILY_FAILS
    FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
    WHERE EVENT_TIMESTAMP >= DATEADD('day', -14, CURRENT_TIMESTAMP())
      AND EVENT_TIMESTAMP < DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
      AND IS_SUCCESS = 'NO'
    GROUP BY 1,2
  )
  GROUP BY 1
)
SELECT 'SECURITY_FAILED_LOGIN_SPIKE' AS ALERT_KEY, 'Security' AS CATEGORY, 'High' AS SEVERITY,
       recent.USER_NAME AS ENTITY_NAME, recent.CLIENT_IP AS SOURCE_IP,
       FAILED_LOGINS AS CURRENT_VALUE, COALESCE(AVG_DAILY_FAILS, 0) AS BASELINE_VALUE,
       'Investigate failed login spike for user/IP/client.' AS RECOMMENDED_ACTION
FROM recent
LEFT JOIN baseline USING (USER_NAME)
WHERE FAILED_LOGINS >= GREATEST(10, COALESCE(AVG_DAILY_FAILS, 0) * 3)
ORDER BY FAILED_LOGINS DESC
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Security",
            "SIGNAL": "Privileged role grant or escalation",
            "SEVERITY": "Critical",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS / GRANTS_TO_ROLES",
            "FRESHNESS": "Delayed ACCOUNT_USAGE telemetry",
            "OWNER": "Security Review",
            "WHY_THIS_MATTERS": "ACCOUNTADMIN, SECURITYADMIN, SYSADMIN, or ORGADMIN expansion is a control-plane event, not a routine alert.",
            "RECOMMENDED_ACTION": "Check ticket/reviewer, user purpose, MFA posture, and review date before accepting the grant.",
            "SQL": f"""
SELECT 'SECURITY_PRIVILEGE_ESCALATION' AS ALERT_KEY, 'Security' AS CATEGORY, 'Critical' AS SEVERITY,
       GRANTEE_NAME AS ENTITY_NAME, ROLE AS ROLE_NAME, CREATED_ON AS EVENT_TS,
       GRANTED_BY, 'Privileged role grant requires review status and access review date.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS
WHERE CREATED_ON >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND DELETED_ON IS NULL
  AND UPPER(ROLE) IN ('ACCOUNTADMIN', 'SECURITYADMIN', 'SYSADMIN', 'ORGADMIN')
ORDER BY CREATED_ON DESC
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Security",
            "SIGNAL": "Sensitive access or large unload",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY + QUERY_HISTORY",
            "FRESHNESS": "Delayed ACCOUNT_USAGE telemetry",
            "OWNER": "DBA / Security",
            "WHY_THIS_MATTERS": "Large exports and spikes against sensitive tables are early signs of data loss or security drift.",
            "RECOMMENDED_ACTION": "Confirm business purpose, destination stage, role used, masking policy coverage, and downstream status.",
            "SQL": f"""
SELECT 'SECURITY_SENSITIVE_EXPORT' AS ALERT_KEY, 'Security' AS CATEGORY, 'High' AS SEVERITY,
       q.USER_NAME AS ENTITY_NAME, q.ROLE_NAME, q.WAREHOUSE_NAME, q.QUERY_ID,
       q.START_TIME AS EVENT_TS, q.BYTES_SCANNED AS CURRENT_VALUE,
       LEFT(q.QUERY_TEXT, 500) AS EVIDENCE,
       'Review query text, destination stage, access history objects, and status.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
WHERE q.START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND (q.QUERY_TEXT ILIKE 'COPY INTO @%' OR q.QUERY_TEXT ILIKE '%COPY INTO @%')
ORDER BY q.BYTES_SCANNED DESC NULLS LAST
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Cost",
            "SIGNAL": "Warehouse credit spike vs baseline",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
            "FRESHNESS": "Finalized metering windows can lag",
            "OWNER": "DBA / Cost owner",
            "WHY_THIS_MATTERS": "Warehouse metering is the official compute source of truth; spikes need route, workload, and contract-burn context.",
            "RECOMMENDED_ACTION": "Compare current credits to 30-day baseline, then inspect query drivers and warehouse setting changes.",
            "SQL": f"""
WITH current_window AS (
  SELECT WAREHOUSE_NAME, SUM(CREDITS_USED) AS CURRENT_CREDITS
  FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
  WHERE START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  GROUP BY 1
),
baseline AS (
  SELECT WAREHOUSE_NAME, AVG(DAILY_CREDITS) AS BASELINE_DAILY_CREDITS
  FROM (
    SELECT WAREHOUSE_NAME, DATE_TRUNC('day', START_TIME) AS USAGE_DAY, SUM(CREDITS_USED) AS DAILY_CREDITS
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
      AND START_TIME < DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
    GROUP BY 1,2
  )
  GROUP BY 1
)
SELECT 'COST_WAREHOUSE_CREDIT_SPIKE' AS ALERT_KEY, 'Cost' AS CATEGORY, 'High' AS SEVERITY,
       current_window.WAREHOUSE_NAME AS ENTITY_NAME,
       CURRENT_CREDITS AS CURRENT_VALUE, COALESCE(BASELINE_DAILY_CREDITS, 0) AS BASELINE_VALUE,
       'Explain warehouse credit spike with official metering and top query drivers.' AS RECOMMENDED_ACTION
FROM current_window
LEFT JOIN baseline USING (WAREHOUSE_NAME)
WHERE CURRENT_CREDITS > GREATEST(10, COALESCE(BASELINE_DAILY_CREDITS, 0) * 1.5)
ORDER BY CURRENT_CREDITS DESC
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Cost",
            "SIGNAL": "Cortex spend spike and quota drift",
            "SEVERITY": "High",
            "TELEMETRY": "FACT_CORTEX_DAILY plus Cortex ACCOUNT_USAGE views",
            "FRESHNESS": "Cortex facts are task-loaded; raw Cortex ACCOUNT_USAGE views can lag or be unavailable by feature",
            "OWNER": "DBA / AI cost route",
            "WHY_THIS_MATTERS": "Cortex usage can grow from user behavior, shared advice, or new features before normal warehouse cost controls catch it.",
            "RECOMMENDED_ACTION": "Review top Cortex users, request sources, 7-day cost, quota settings, grants, and whether usage belongs to ALFA or Trexis.",
            "SQL": f"""
WITH recent AS (
  SELECT USER_ID, SOURCE, SUM(EST_COST_USD) AS CURRENT_VALUE, SUM(REQUEST_COUNT) AS REQUESTS
  FROM FACT_CORTEX_DAILY
  WHERE USAGE_DATE >= DATEADD('day', -7, CURRENT_DATE())
  GROUP BY 1,2
),
baseline AS (
  SELECT USER_ID, SOURCE, AVG(DAILY_COST_USD) AS BASELINE_VALUE
  FROM (
    SELECT USER_ID, SOURCE, USAGE_DATE, SUM(EST_COST_USD) AS DAILY_COST_USD
    FROM FACT_CORTEX_DAILY
    WHERE USAGE_DATE >= DATEADD('day', -37, CURRENT_DATE())
      AND USAGE_DATE < DATEADD('day', -7, CURRENT_DATE())
    GROUP BY 1,2,3
  )
  GROUP BY 1,2
)
SELECT 'CORTEX_SPEND_AND_QUOTA' AS ALERT_KEY, 'Cost' AS CATEGORY, 'High' AS SEVERITY,
       COALESCE(recent.USER_ID, 'CORTEX') AS ENTITY_NAME,
       recent.SOURCE, recent.CURRENT_VALUE, COALESCE(baseline.BASELINE_VALUE, 0) AS BASELINE_VALUE,
       recent.REQUESTS,
       'Review Cortex user/source spend, quota settings, grants, and route before enforcing controls.' AS RECOMMENDED_ACTION
FROM recent
LEFT JOIN baseline USING (USER_ID, SOURCE)
WHERE recent.CURRENT_VALUE > GREATEST(25, COALESCE(baseline.BASELINE_VALUE, 0) * 1.5)
ORDER BY recent.CURRENT_VALUE DESC
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Performance",
            "SIGNAL": "Queue, spill, blocking, and long-running query pressure",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY / INFORMATION_SCHEMA.QUERY_HISTORY",
            "FRESHNESS": "Use INFORMATION_SCHEMA for near-real-time triage; ACCOUNT_USAGE for historical baseline",
            "OWNER": "DBA / Platform",
            "WHY_THIS_MATTERS": "Queueing, remote spill, and lock waits are the difference between noisy SQL and production contention.",
            "RECOMMENDED_ACTION": "Open Query Investigation or Performance & Contention with the exact query_id and warehouse telemetry.",
            "SQL": f"""
SELECT 'PERF_QUERY_PRESSURE' AS ALERT_KEY, 'Performance' AS CATEGORY,
       CASE WHEN COALESCE(TRANSACTION_BLOCKED_TIME, 0) > 0 THEN 'Critical' ELSE 'High' END AS SEVERITY,
       QUERY_ID, USER_NAME, ROLE_NAME, WAREHOUSE_NAME, DATABASE_NAME, SCHEMA_NAME,
       TOTAL_ELAPSED_TIME AS CURRENT_VALUE,
       QUEUED_PROVISIONING_TIME + QUEUED_REPAIR_TIME + QUEUED_OVERLOAD_TIME AS QUEUE_MS,
       TRANSACTION_BLOCKED_TIME AS BLOCKED_MS,
       BYTES_SPILLED_TO_REMOTE_STORAGE,
       LEFT(QUERY_TEXT, 500) AS EVIDENCE,
       'Review warehouse pressure, query plan, lock route, pruning, spill, and status result.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND (
    TOTAL_ELAPSED_TIME > 1800000
    OR COALESCE(TRANSACTION_BLOCKED_TIME, 0) > 0
    OR COALESCE(BYTES_SPILLED_TO_REMOTE_STORAGE, 0) > 0
    OR (COALESCE(QUEUED_PROVISIONING_TIME, 0) + COALESCE(QUEUED_REPAIR_TIME, 0) + COALESCE(QUEUED_OVERLOAD_TIME, 0)) > 300000
  )
ORDER BY TOTAL_ELAPSED_TIME DESC
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Task / Pipeline",
            "SIGNAL": "Failed, skipped, late, or long-running task graph",
            "SEVERITY": "Critical",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY and event tables when configured",
            "FRESHNESS": "ACCOUNT_USAGE delayed; task graph error notifications can be near-real-time when configured",
            "OWNER": "DBA / Pipeline Route",
            "WHY_THIS_MATTERS": "Snowflake pipeline reliability depends on task graphs having SLA, failure, retry, and route telemetry.",
            "RECOMMENDED_ACTION": "Identify root task, failed child, error signature, retry count, last success, and downstream SLA risk before rerun.",
            "SQL": f"""
SELECT 'PIPELINE_TASK_FAILURE' AS ALERT_KEY, 'Task / Pipeline' AS CATEGORY, 'Critical' AS SEVERITY,
       DATABASE_NAME, SCHEMA_NAME, NAME AS ENTITY_NAME, ROOT_TASK_ID,
       STATE, SCHEDULED_TIME AS EVENT_TS, COMPLETED_TIME, QUERY_ID, ERROR_CODE, ERROR_MESSAGE,
       'Open task graph, isolate failed child/root task, confirm route and safe rerun conditions.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE SCHEDULED_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND UPPER(COALESCE(STATE, '')) IN ('FAILED', 'FAILED_WITH_ERROR', 'SKIPPED', 'CANCELLED')
ORDER BY SCHEDULED_TIME DESC
LIMIT 200;
""".strip(),
        },
        {
            "CATEGORY": "Task / Pipeline",
            "SIGNAL": "COPY load failures",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY",
            "FRESHNESS": "Optional ACCOUNT_USAGE view; depends on account edition and grants",
            "OWNER": "DBA / Data Engineering",
            "WHY_THIS_MATTERS": "Load failures and late data are often the earliest visible pipeline incident.",
            "RECOMMENDED_ACTION": "Group by table/stage/error and confirm whether the downstream task graph is stale or blocked.",
            "SQL": f"""
SELECT 'PIPELINE_COPY_FAILURE' AS ALERT_KEY, 'Task / Pipeline' AS CATEGORY, 'High' AS SEVERITY,
       TABLE_CATALOG || '.' || TABLE_SCHEMA || '.' || TABLE_NAME AS ENTITY_NAME,
       LAST_LOAD_TIME AS EVENT_TS, FILE_NAME, STATUS, ERROR_COUNT AS CURRENT_VALUE,
       FIRST_ERROR_MESSAGE AS EVIDENCE,
       'Fix load error, validate file format/stage permissions, and confirm downstream freshness SLA.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY
WHERE LAST_LOAD_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND UPPER(COALESCE(STATUS, '')) NOT IN ('LOADED')
ORDER BY LAST_LOAD_TIME DESC
LIMIT 200;
""".strip(),
        },
        {
            "CATEGORY": "Task / Pipeline",
            "SIGNAL": "Dynamic table refresh failure or lag",
            "SEVERITY": "High",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY",
            "FRESHNESS": "Optional ACCOUNT_USAGE view; use only when dynamic tables exist and grants expose it",
            "OWNER": "DBA / Data Engineering",
            "WHY_THIS_MATTERS": "Dynamic table lag can create freshness incidents without an obvious failed task row.",
            "RECOMMENDED_ACTION": "Compare target lag, refresh state, error text, upstream task/query pressure, and downstream SLA.",
            "SQL": f"""
SELECT 'PIPELINE_DYNAMIC_TABLE_REFRESH' AS ALERT_KEY, 'Task / Pipeline' AS CATEGORY, 'High' AS SEVERITY,
       DATABASE_NAME || '.' || SCHEMA_NAME || '.' || NAME AS ENTITY_NAME,
       REFRESH_START_TIME AS EVENT_TS, STATE, STATE_CODE, ERROR_MESSAGE,
       'Review dynamic table refresh history, target lag, upstream query pressure, and downstream SLA.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY
WHERE REFRESH_START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND UPPER(COALESCE(STATE, '')) NOT IN ('SUCCEEDED', 'SUCCESS')
ORDER BY REFRESH_START_TIME DESC
LIMIT 200;
""".strip(),
        },
        {
            "CATEGORY": "Data Quality",
            "SIGNAL": "Metadata-driven data quality check failed",
            "SEVERITY": "High",
            "TELEMETRY": "ALERT_CONFIG / ALERT_THRESHOLDS plus table metadata checks",
            "FRESHNESS": "Near-real-time if the configured query targets INFORMATION_SCHEMA or live table metadata",
            "OWNER": "Data Route",
            "WHY_THIS_MATTERS": "Freshness, volume, null, duplicate, and schema drift checks need route-tunable thresholds without code changes.",
            "RECOMMENDED_ACTION": "Configure table/column/check/threshold/route in ALERT_CONFIG or ALERT_THRESHOLDS, then route failures to the data route.",
            "SQL": f"""
SELECT 'DQ_CONFIG_REQUIRED' AS ALERT_KEY, 'Data Quality' AS CATEGORY, 'Medium' AS SEVERITY,
       ALERT_KEY AS ENTITY_NAME, CATEGORY || ': ' || SIGNAL_NAME AS EVIDENCE,
       'Define database/schema/table/column/check type/threshold/route before enabling data-quality alerts.' AS RECOMMENDED_ACTION
FROM {_command_center_fqn("ALERT_CONFIG")}
WHERE CATEGORY = 'Data Quality'
  AND ENABLED
  AND COALESCE(DETECTION_SQL, '') = ''
LIMIT 100;
""".strip(),
        },
        {
            "CATEGORY": "Optimization",
            "SIGNAL": "Warehouse sizing, auto-suspend, unused objects, and repeated expensive query candidates",
            "SEVERITY": "Medium",
            "TELEMETRY": "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES / QUERY_HISTORY / TABLES",
            "FRESHNESS": "Delayed ACCOUNT_USAGE telemetry",
            "OWNER": "DBA / Cost owner",
            "WHY_THIS_MATTERS": "Optimization alerts should be telemetry-ranked candidates, not generic tune-the-query advice.",
            "RECOMMENDED_ACTION": "Route only with before/after telemetry, review status, rollback path, and expected savings or reliability gain.",
            "SQL": f"""
SELECT 'OPT_WAREHOUSE_AUTOSUSPEND' AS ALERT_KEY, 'Optimization' AS CATEGORY, 'Medium' AS SEVERITY,
       WAREHOUSE_NAME AS ENTITY_NAME, AUTO_SUSPEND AS CURRENT_VALUE,
       'Warehouse auto-suspend setting may be too high or disabled.' AS EVIDENCE,
       'Validate workload class, route SLA, queue/spill baseline, and changed-only warehouse setting recommendation.' AS RECOMMENDED_ACTION
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES
WHERE DELETED IS NULL
  AND (AUTO_SUSPEND IS NULL OR AUTO_SUSPEND > 600)
ORDER BY AUTO_SUSPEND DESC NULLS FIRST
LIMIT 100;
""".strip(),
        },
    ]
    return pd.DataFrame(rows)


def build_alert_required_privileges() -> pd.DataFrame:
    rows = [
        ("Imported privileges on SNOWFLAKE database", "ACCOUNT_USAGE views: QUERY_HISTORY, WAREHOUSE_METERING_HISTORY, LOGIN_HISTORY, ACCESS_HISTORY, TASK_HISTORY, ALERT_HISTORY, GRANTS views"),
        ("USAGE on monitored databases/schemas", "INFORMATION_SCHEMA checks and task/pipe metadata where ACCOUNT_USAGE lag is too slow"),
        ("SELECT on OVERWATCH schema tables", "ALERT_CONFIG, ALERT_EVENTS, ALERT_THRESHOLDS, ALERT_OWNER_ROUTING, notification/remediation logs"),
        ("OPERATE for reviewed remediation", "Only needed for reviewed task/warehouse/query/user actions; detection works without it"),
        ("Notification integration usage", "Only needed when sending Snowflake email/webhook/cloud notifications from procedures or alerts"),
    ]
    return pd.DataFrame(rows, columns=["PRIVILEGE_ASSUMPTION", "WHY_REQUIRED"])


def build_alert_optional_integrations() -> pd.DataFrame:
    rows = [
        ("Snowflake ALERT objects", "Periodic condition evaluation and SQL action execution", "Recommended for reviewed scheduled detection"),
        ("Email notification integration", "SYSTEM$SEND_EMAIL alert digests and escalations", "Optional but useful for DBA on-call"),
        ("Webhook / Slack / Teams integration", "External routing when account and network policies allow it", "Optional; keep payloads logged"),
        ("Event tables with LOG_LEVEL >= ERROR", "Task graph and stored procedure error events", "Recommended for near-real-time pipeline failures"),
        ("Status/Snowflake task bridge", "Incident tickets, route assignment, workflow handoff", "Optional; use action queue until reviewed"),
    ]
    return pd.DataFrame(rows, columns=["INTEGRATION", "CAPABILITY", "STATUS_NOTE"])


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
                "LAST_CHECKED": "On demand",
                "FRESHNESS_STATE": "Load required",
                "NOTE": "Use explicit load to avoid hidden ACCOUNT_USAGE scans.",
            }]),
            "last_checked": "On demand",
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
    owner = _alert_col(df, "OWNER", "ROUTED_OWNER", "ESCALATION_TARGET", default="DBA").fillna("DBA").astype(str)
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
            "ONCALL_PRIMARY": _row_value(row, "ONCALL_PRIMARY", default=""),
            "APPROVAL_GROUP": _row_value(row, "APPROVAL_GROUP", default=""),
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
        "APPROVAL_GROUP",
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
    owner = _alert_col(work, "OWNER", "ROUTED_OWNER", "ESCALATION_TARGET", default="DBA").fillna("DBA").astype(str)
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
            "APPROVAL_GROUP": queue_context.get("APPROVAL_GROUP", _row_value(row, "APPROVAL_GROUP", default="DBA Review")),
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
            "Cost by User / Role",
            "Cost Alerts",
            "Open Cost & Contract > Cost by User / Role, then use Advanced Cost Tools for model-level Cortex evidence.",
            "Review Cortex user/source, baseline, quota, grants, and company scope before changing access.",
        )
    if "SPEND" in focus_key or "COST" in focus_key:
        return (
            "Cost & Contract",
            "Cost by Warehouse",
            "Cost Alerts",
            "Open Cost & Contract > Cost by Warehouse.",
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
            "Review query ID, warehouse pressure, queue/spill/lock evidence, and workload owner route.",
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
            safe_action = "Open Cost by User / Role; use Advanced Cost Tools for Cortex model evidence before changing access."
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
        "APPROVAL_GROUP",
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
            "APPROVAL_GROUP": next((str(value) for value in group["APPROVAL_GROUP"] if str(value).strip()), "DBA Review"),
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
    owner = _alert_col(work, "OWNER", "ESCALATION_TARGET", default="DBA").fillna("DBA").astype(str)
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


def build_alert_command_center_runbook_markdown() -> str:
    return """# OVERWATCH Alert Monitoring Runbook

## Operating Rule
The Alert Center is a triage and monitoring surface. It should detect, prioritize, route, notify, and audit. It should not silently mutate Snowflake objects.

## Severity
- CRITICAL: security breach risk, runaway spend, failed production pipeline, disabled controls, privilege escalation, repeated task failures.
- HIGH: major cost/performance anomaly, warehouse saturation, excessive queueing, blocked work, failed important job.
- MEDIUM: optimization opportunity, suspicious behavior, growing costs, route gaps.
- LOW: informational or early warning.

## Daily DBA Flow
1. Open DBA Daily Brief and work Critical/High rows first.
2. Check Security, Cost, Performance, and Pipeline categories before optimization work.
3. Use telemetry status and bounded detail before declaring an incident.
4. Acknowledge or suppress planned work with a telemetry note.
5. Route status-backed actions to the action queue with ticket, telemetry SQL, and closure status.

## Telemetry Status
ACCOUNT_USAGE views are authoritative for history but can lag. Use INFORMATION_SCHEMA table functions, task graph notifications, Snowflake ALERT objects, and event tables for near-real-time incident checks where available.

## Remediation Policy
Default mode is RECOMMEND. AUTO is allowed only for safe, explicitly reviewed actions. Dangerous operations such as cancel query, revoke grant, disable user, alter warehouse, resume task, or suspend warehouse require status review and ALERT_REMEDIATION_LOG telemetry.
"""
