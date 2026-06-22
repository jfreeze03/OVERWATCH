"""Alert triage and history helpers for OVERWATCH.

This module owns alert status/severity normalization, alert history loading,
SLA annotation, digest summaries, and common issue-row shaping used by the
operator surfaces. Delivery, catalog management, action-queue routing, and
native alert setup remain in focused sibling modules.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from config import (
    ALERT_DB,
    ALERT_DELIVERY_METHOD,
    ALERT_SCHEMA,
    ALERT_TABLE,
)
from .alert_catalog import alert_rule_catalog
from .alert_delivery import (
    DEFAULT_ALERT_RECIPIENT,
    alert_delivery_status_for_target,
    build_alert_email_body,
    build_alert_email_subject,
)
from .compatibility import filter_existing_columns
from .company_filter import (
    company_value_allowed,
    environment_value_allowed,
    get_active_environment,
    get_environment_db_patterns,
)
from .query import run_query, safe_identifier, sql_literal
from .alert_status import (
    ALERT_CLOSED_STATUSES,
    ALERT_OPEN_STATUSES,
    ALERT_SLA_HOURS,
    ALERT_STATUS_CHOICES,
    alert_severity_rank,
    normalize_alert_severity,
    normalize_alert_status,
)

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

