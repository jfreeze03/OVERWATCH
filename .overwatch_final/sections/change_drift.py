# sections/change_drift.py - Consolidated change, drift, and lineage workflow
from __future__ import annotations

from datetime import datetime
import re

import pandas as pd
import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA, ACTION_QUEUE_TABLE
from utils import (
    filter_existing_columns,
    format_snowflake_error,
    environment_label_for_database,
    get_active_company,
    get_active_environment,
    get_environment_case_expr,
    get_global_filter_clause,
    get_session,
    mart_object_name,
    make_action_id,
    resolve_owner_context,
    run_query,
    safe_identifier,
    safe_float,
    safe_int,
    sql_literal,
    action_queue_environment_clause,
    upsert_actions,
)
from utils.workflows import (
    render_operator_briefing,
    render_priority_dataframe,
    render_signal_confidence,
    render_workflow_module,
    render_workflow_guide,
    render_workflow_selector,
)

WORKFLOWS = (
    "Object and access changes",
    "Stored procedure lineage",
    "Schema and object drift",
    "Data movement and replication",
    "Controlled DBA actions",
)

WORKFLOW_DETAILS = {
    "Object and access changes": "Who changed what, access movement, destructive DDL, and policy changes.",
    "Stored procedure lineage": "Procedure ownership, child SQL, downstream objects, and runtime/cost drift.",
    "Schema and object drift": "Schema compare, object inventory, unused objects, and Terraform drift signals.",
    "Data movement and replication": "Replication, dynamic tables, Snowpipe, data loading, and freshness risk.",
    "Controlled DBA actions": "Guarded admin actions, generated SQL, and operational controls.",
}

WORKFLOW_MODULES = {
    "Object and access changes": "sections.object_change_monitor",
    "Stored procedure lineage": "sections.stored_proc_tracker",
    "Schema and object drift": "sections.dba_tools",
    "Data movement and replication": "sections.dba_tools",
    "Controlled DBA actions": "sections.dba_tools",
}

CHANGE_CONTROL_EVIDENCE_TABLE = "OVERWATCH_CHANGE_CONTROL_EVIDENCE"
CHANGE_CONTROL_OPERABILITY_FACT_TABLE = "FACT_CHANGE_CONTROL_OPERABILITY_DAILY"
CHANGE_SCOPE_FILTER_KEYS = (
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
    "global_start_date",
    "global_end_date",
)
CHANGE_TICKET_PATTERN = re.compile(
    r"\b(?:CHG|CHANGE|INC|REQ|RFC|JIRA)[-_]?\d+\b|\b[A-Z][A-Z0-9]+-\d+\b",
    re.IGNORECASE,
)


def change_control_evidence_fqn(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_CONTROL_EVIDENCE_TABLE,
) -> str:
    return f"{safe_identifier(db)}.{safe_identifier(schema)}.{safe_identifier(table)}"


def build_change_control_evidence_ddl(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_CONTROL_EVIDENCE_TABLE,
) -> str:
    fqn = change_control_evidence_fqn(db=db, schema=schema, table=table)
    return f"""CREATE TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_ID              VARCHAR(64),
    SNAPSHOT_TS              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    COMPANY                  VARCHAR(100),
    ENVIRONMENT              VARCHAR(100),
    FINDING_TYPE             VARCHAR(120),
    SEVERITY                 VARCHAR(40),
    ENTITY                   VARCHAR(500),
    USER_NAME                VARCHAR(300),
    ROLE_NAME                VARCHAR(300),
    QUERY_ID                 VARCHAR(200),
    QUERY_TAG                VARCHAR(1000),
    LAST_SEEN                VARCHAR(100),
    CHANGE_CONTROL_STATE     VARCHAR(120),
    CONTROL_GAP              VARCHAR(1000),
    CHANGE_TICKET_ID         VARCHAR(200),
    CHANGE_TICKET_STATE      VARCHAR(120),
    IAC_RECONCILIATION_STATE VARCHAR(160),
    EXECUTION_AUDIT_STATE    VARCHAR(160),
    OWNER                    VARCHAR(200),
    ESCALATION_TARGET        VARCHAR(200),
    OWNER_SOURCE             VARCHAR(200),
    APPROVER                 VARCHAR(200),
    OWNER_APPROVAL_STATUS    VARCHAR(40),
    APPROVAL_REQUIRED        VARCHAR(20),
    TICKET_REQUIRED          VARCHAR(20),
    BLAST_RADIUS_REQUIRED    VARCHAR(20),
    APPROVAL_ROUTE_READY     VARCHAR(20),
    CHANGE_EVIDENCE_READINESS VARCHAR(80),
    EVIDENCE_BLOCKERS        VARCHAR(2000),
    REVIEW_SLA_HOURS         NUMBER,
    NEXT_CONTROL_ACTION      VARCHAR(4000),
    PROOF_REQUIRED           VARCHAR(2000),
    VERIFICATION_QUERY       VARCHAR(8000),
    BLAST_RADIUS_QUERY       VARCHAR(8000),
    SOURCE                   VARCHAR(500)
);"""


def build_change_control_evidence_migration_sql(
    db: str = ALERT_DB,
    schema: str = ALERT_SCHEMA,
    table: str = CHANGE_CONTROL_EVIDENCE_TABLE,
) -> list[str]:
    """Return additive migrations for previously deployed evidence tables."""
    fqn = change_control_evidence_fqn(db=db, schema=schema, table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS APPROVAL_ROUTE_READY VARCHAR(20)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CHANGE_EVIDENCE_READINESS VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS EVIDENCE_BLOCKERS VARCHAR(2000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_SLA_HOURS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
    ]


def change_control_operability_fact_fqn(table: str = CHANGE_CONTROL_OPERABILITY_FACT_TABLE) -> str:
    return mart_object_name(table)


def build_change_control_operability_fact_ddl(table: str = CHANGE_CONTROL_OPERABILITY_FACT_TABLE) -> str:
    fqn = change_control_operability_fact_fqn(table=table)
    return f"""CREATE TRANSIENT TABLE IF NOT EXISTS {fqn} (
    SNAPSHOT_DATE              DATE,
    COMPANY                    VARCHAR(100),
    ENVIRONMENT                VARCHAR(100),
    CONTROL_SOURCE             VARCHAR(80),
    CONTROL_KEY                VARCHAR(500),
    FINDING_TYPE               VARCHAR(120),
    ENTITY                     VARCHAR(500),
    OWNER                      VARCHAR(200),
    ESCALATION_TARGET          VARCHAR(200),
    SEVERITY                   VARCHAR(40),
    EVIDENCE_ROWS              NUMBER,
    HIGH_RISK_CHANGES          NUMBER,
    ROUTE_BLOCKED              NUMBER,
    CLOSURE_BLOCKED            NUMBER,
    REVIEW_READY               NUMBER,
    MISSING_TICKET_ROWS        NUMBER,
    IAC_GAP_ROWS               NUMBER,
    MISSING_QUERY_ID_ROWS      NUMBER,
    OPEN_ACTIONS               NUMBER,
    OVERDUE_OPEN               NUMBER,
    FIXED_WITHOUT_VERIFICATION NUMBER,
    VERIFIED_CLOSURES          NUMBER,
    OWNER_APPROVAL_GAP_ROWS    NUMBER,
    CONTROL_STATE              VARCHAR(120),
    CONTROL_RANK               NUMBER,
    NEXT_CONTROL_ACTION        VARCHAR(4000),
    LAST_ACTIVITY_TS           TIMESTAMP_NTZ,
    LOAD_TS                    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);"""


def build_change_control_operability_fact_migration_sql(
    table: str = CHANGE_CONTROL_OPERABILITY_FACT_TABLE,
) -> list[str]:
    fqn = change_control_operability_fact_fqn(table=table)
    return [
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_SOURCE VARCHAR(80)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_KEY VARCHAR(500)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS HIGH_RISK_CHANGES NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS ROUTE_BLOCKED NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CLOSURE_BLOCKED NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS REVIEW_READY NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS OWNER_APPROVAL_GAP_ROWS NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_STATE VARCHAR(120)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS CONTROL_RANK NUMBER",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION VARCHAR(4000)",
        f"ALTER TABLE {fqn} ADD COLUMN IF NOT EXISTS LAST_ACTIVITY_TS TIMESTAMP_NTZ",
    ]


def _change_ticket_id(row: pd.Series | dict) -> str:
    haystack = " ".join([
        str(row.get("QUERY_TAG") or ""),
        str(row.get("QUERY_TEXT") or ""),
        str(row.get("PROOF_QUERY") or ""),
    ])
    match = CHANGE_TICKET_PATTERN.search(haystack)
    return match.group(0).upper() if match else ""


def _split_snowflake_qualified_name(value: object) -> list[str]:
    """Split a Snowflake qualified name while preserving dots inside quotes."""
    text = str(value or "").strip()
    if not text:
        return []
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    idx = 0
    while idx < len(text):
        char = text[idx]
        if char == '"':
            if in_quotes and idx + 1 < len(text) and text[idx + 1] == '"':
                current.append('"')
                idx += 2
                continue
            in_quotes = not in_quotes
            idx += 1
            continue
        if char == "." and not in_quotes:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)
        idx += 1
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _change_database_name(row: pd.Series | dict) -> str:
    for key in ("DATABASE_NAME", "OBJECT_DATABASE", "TABLE_CATALOG"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.strip('"')
    entity = str(row.get("ENTITY") or "").strip()
    if "." in entity:
        pieces = _split_snowflake_qualified_name(entity)
        return pieces[0] if pieces else ""
    if entity.upper().startswith(("ALFA_", "TRXS_")):
        return entity.strip('"')
    return ""


def _change_database_context(row: pd.Series | dict) -> bool:
    return bool(_change_database_name(row))


def _change_environment(row: pd.Series | dict, fallback: str = "ALL") -> str:
    database_name = _change_database_name(row)
    if database_name:
        return environment_label_for_database(database_name)
    return "No Database Context" if not str(row.get("DATABASE_NAME") or "").strip() else str(fallback or "ALL")


def _change_scope_clause(date_col: str, wh_col: str, user_col: str, role_col: str, db_col: str) -> str:
    """Apply company/global filters while keeping account-level changes under environment scopes."""
    return get_global_filter_clause(
        date_col=date_col,
        wh_col=wh_col,
        user_col=user_col,
        role_col=role_col,
        db_col=db_col,
        preserve_no_database_context=True,
    )


def _change_scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _change_scope_meta(
    company: str,
    environment: str,
    days: int | None = None,
    state: dict | None = None,
) -> dict:
    """Return the filter scope that loaded Change & Drift evidence must match."""
    state = state if state is not None else st.session_state
    meta = {
        "company": _change_scope_value(company),
        "environment": _change_scope_value(environment),
    }
    if days is not None:
        meta["days"] = int(days)
    for key in CHANGE_SCOPE_FILTER_KEYS:
        meta[key] = _change_scope_value(state.get(key))
    return meta


def _change_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        actual = meta.get(key)
        if key == "days":
            try:
                if int(actual) != int(expected_value):
                    return False
            except Exception:
                return False
        elif _change_scope_value(actual) != _change_scope_value(expected_value):
            return False
    return True


def _change_row_count(frame) -> int:
    return len(frame) if isinstance(frame, pd.DataFrame) else 0


def _change_source_confidence(source: str, default: str) -> str:
    source_lower = str(source or "").lower()
    if "mart" in source_lower or "fact_" in source_lower:
        return "Pre-aggregated"
    if "fallback" in source_lower:
        return "Live fallback"
    if "account_usage" in source_lower:
        return "Live ACCOUNT_USAGE"
    if "action queue" in source_lower or "workflow" in source_lower or "evidence" in source_lower:
        return "Workflow evidence"
    return default


def _change_source_next_action(state: str, source: str) -> str:
    source_lower = str(source or "").lower()
    if state == "Stale":
        return "Reload after changing company, environment, lookback, or global filters."
    if state == "Unavailable":
        return "Deploy or refresh the mart/evidence tables before relying on this surface."
    if state == "Not Loaded":
        return "Load only when this workflow is part of the current change investigation."
    if state == "No Rows":
        return "Confirm the selected scope has recent change events, evidence, or action rows."
    if "fallback" in source_lower:
        return "Use for investigation; prefer mart refresh for repeated daily change control."
    return "Current for the active DBA change scope."


def _change_source_health_rows(
    state: dict,
    company: str,
    environment: str,
) -> pd.DataFrame:
    """Summarize Change & Drift evidence freshness and source strategy."""
    definitions = [
        {
            "surface": "Change brief",
            "frame_key": "change_drift_summary",
            "source_key": "change_drift_source",
            "meta_key": "change_drift_meta",
            "days_key": "change_drift_brief_days",
            "default_days": 14,
            "source": "OVERWATCH mart or live QUERY_HISTORY change brief",
            "confidence": "Mixed",
            "error_key": "change_drift_error",
        },
        {
            "surface": "Change exceptions",
            "frame_key": "change_drift_exceptions",
            "source_key": "change_drift_source",
            "meta_key": "change_drift_meta",
            "days_key": "change_drift_brief_days",
            "default_days": 14,
            "source": "OVERWATCH mart or live QUERY_HISTORY exception set",
            "confidence": "Mixed",
            "error_key": "change_drift_error",
        },
        {
            "surface": "Operability fact",
            "frame_key": "change_control_operability_fact",
            "meta_key": "change_control_operability_fact_meta",
            "days_key": "change_drift_brief_days",
            "default_days": 14,
            "source": f"OVERWATCH mart: {CHANGE_CONTROL_OPERABILITY_FACT_TABLE}",
            "confidence": "Pre-aggregated",
            "error_key": "change_control_operability_fact_error",
        },
        {
            "surface": "Evidence trend",
            "frame_key": "change_drift_evidence_trend",
            "meta_key": "change_drift_evidence_trend_meta",
            "days_key": "change_drift_evidence_trend_days",
            "default_days": 30,
            "source": f"Workflow mart: {CHANGE_CONTROL_EVIDENCE_TABLE}",
            "confidence": "Workflow evidence",
            "error_key": "change_drift_evidence_trend_error",
        },
        {
            "surface": "Closure analytics",
            "frame_key": "change_action_closure",
            "meta_key": "change_action_closure_meta",
            "days_key": "change_action_closure_days",
            "default_days": 30,
            "source": "Action queue closure evidence",
            "confidence": "Workflow evidence",
            "error_key": "change_action_closure_error",
        },
    ]
    rows = []
    for item in definitions:
        source_key = item.get("source_key")
        source = str((state.get(source_key, item["source"]) if source_key else item["source"]) or item["source"])
        frame = state.get(item["frame_key"])
        error_key = item.get("error_key")
        error = state.get(error_key) if error_key else None
        days_key = item.get("days_key")
        days = state.get(days_key, item.get("default_days")) if days_key else item.get("default_days")
        expected_meta = _change_scope_meta(company, environment, days=days, state=state)
        loaded = isinstance(frame, pd.DataFrame)
        if error:
            status = "Unavailable"
        elif not loaded:
            status = "Not Loaded"
        elif not _change_meta_matches(state.get(item["meta_key"]), expected_meta):
            status = "Stale"
        elif frame.empty:
            status = "No Rows"
        else:
            status = "Loaded"
        rows.append({
            "SURFACE": item["surface"],
            "STATE": status,
            "STATE_RANK": {
                "Unavailable": 0,
                "Stale": 1,
                "Loaded": 2,
                "No Rows": 3,
                "Not Loaded": 4,
            }.get(status, 9),
            "SOURCE": source,
            "CONFIDENCE": _change_source_confidence(source, item["confidence"]),
            "ROWS": _change_row_count(frame),
            "SCOPE": f"{company} / {environment} / {int(days)}d",
            "NEXT_ACTION": _change_source_next_action(status, source),
        })
    return pd.DataFrame(rows)


def _change_owner_context(row: pd.Series | dict) -> dict:
    finding = str(row.get("FINDING_TYPE") or "").lower()
    entity = str(row.get("ENTITY") or "").upper()
    environment_label = environment_label_for_database(_change_database_name(row))
    if "policy" in finding or "tag" in finding or "masking" in finding:
        base = {
            "owner": "Security / Data Governance",
            "escalation": "Security Owner / Data Governance Lead",
            "source": "Change owner map",
        }
    elif "grant" in finding or "role" in finding or "owner" in finding:
        base = {
            "owner": "Security Owner",
            "escalation": "DBA Lead / Security Owner",
            "source": "Change owner map",
        }
    elif "drop" in finding or "destructive" in finding:
        base = {
            "owner": "DBA Change Owner",
            "escalation": "Data Owner / DBA Lead",
            "source": "Change owner map",
        }
    elif "drift" in finding:
        base = {
            "owner": "Platform Owner",
            "escalation": "DBA Lead / Platform Owner",
            "source": "Change owner map",
        }
    elif environment_label == "PROD":
        base = {
            "owner": "Production Data Owner",
            "escalation": "DBA Lead",
            "source": "Environment owner hint",
        }
    elif environment_label in {
        "ALFA_EDW_DEV",
        "ALFA_EDW_SAN",
        "ALFA_EDW_PHX",
        "ALFA_EDW_SEA",
        "ALFA_EDW_SIT",
        "Other ALFA Non-Prod",
    }:
        base = {
            "owner": "Development Data Owner",
            "escalation": "DBA Lead",
            "source": "Environment owner hint",
        }
    else:
        base = {
            "owner": "DBA Change Owner",
            "escalation": "DBA Lead",
            "source": "Default change owner",
        }
    directory_context = resolve_owner_context(
        row,
        entity=entity,
        entity_type="CHANGE_CONTROL",
        owner=base["owner"],
        category=finding or "Change Control",
    )
    return {
        "owner": directory_context.get("OWNER") or base["owner"],
        "escalation": base["escalation"] or directory_context.get("ESCALATION_TARGET", ""),
        "source": f"{base['source']}; {directory_context.get('OWNER_SOURCE', '')}".strip("; "),
        "owner_email": directory_context.get("OWNER_EMAIL", ""),
        "oncall_primary": directory_context.get("ONCALL_PRIMARY", ""),
        "oncall_secondary": directory_context.get("ONCALL_SECONDARY", ""),
        "approval_group": base["escalation"] or directory_context.get("APPROVAL_GROUP", ""),
        "owner_evidence": directory_context.get("OWNER_EVIDENCE", ""),
    }


def _change_iac_state(row: pd.Series | dict) -> str:
    query_tag = str(row.get("QUERY_TAG") or "").lower()
    finding = str(row.get("FINDING_TYPE") or "").lower()
    if any(token in query_tag for token in ("terraform", "iac", "liquibase", "flyway", "dbt", "deploy", "release")):
        return "Codified / deployment-tagged"
    if "drift" in finding:
        return "Reconcile IaC"
    severity = str(row.get("SEVERITY") or "").upper()
    if severity in {"CRITICAL", "HIGH"}:
        return "Manual change - IaC proof required"
    return "Review source-control state"


def _change_execution_audit_state(row: pd.Series | dict) -> str:
    query_id = str(row.get("QUERY_ID") or "").strip()
    last_seen = str(row.get("LAST_SEEN") or "").strip()
    if query_id and last_seen:
        return "Query ID and timestamp captured"
    if query_id:
        return "Query ID captured"
    return "Missing query_id proof"


def _change_review_sla_hours(severity: object, finding_type: object) -> int:
    severity_text = str(severity or "").upper()
    finding = str(finding_type or "").lower()
    if severity_text == "CRITICAL" or "destructive" in finding or "policy" in finding or "owner" in finding:
        return 24
    if severity_text == "HIGH":
        return 24
    if severity_text == "MEDIUM" or "grant" in finding or "role" in finding:
        return 72
    return 168


def _change_control_readiness_for_row(row: pd.Series | dict) -> dict:
    owner = str(row.get("OWNER") or "").strip()
    owner_source = str(row.get("OWNER_SOURCE") or "")
    approver = str(row.get("APPROVER") or row.get("APPROVAL_GROUP") or "").strip()
    severity = str(row.get("SEVERITY") or "").upper()
    ticket_state = str(row.get("CHANGE_TICKET_STATE") or "")
    iac_state = str(row.get("IAC_RECONCILIATION_STATE") or "")
    execution_state = str(row.get("EXECUTION_AUDIT_STATE") or "")
    approval_required = str(row.get("APPROVAL_REQUIRED") or "Yes").upper() == "YES" or severity in {"CRITICAL", "HIGH", "MEDIUM"}

    blockers = []
    generic_owners = {"", "DBA", "UNKNOWN", "N/A", "DBA CHANGE OWNER", "SECURITY OWNER"}
    owner_route_ready = bool(owner) and owner.upper() not in generic_owners and "OWNER_DIRECTORY" in owner_source.upper()
    if not owner_route_ready:
        blockers.append("owner directory evidence")
    if approval_required and not approver:
        blockers.append("approver")
    if ticket_state.lower().startswith("missing"):
        blockers.append("change ticket evidence")
    if "required" in iac_state.lower() or "reconcile" in iac_state.lower():
        blockers.append("source-control/IaC evidence")
    if execution_state.lower().startswith("missing"):
        blockers.append("query_id proof")

    route_blockers = {"owner directory evidence", "approver"}
    closure_blockers = [item for item in blockers if item not in route_blockers]
    if any(item in route_blockers for item in blockers):
        readiness = "Route Blocked"
    elif closure_blockers:
        readiness = "Closure Blocked"
    else:
        readiness = "Review Ready"

    if "change ticket evidence" in blockers:
        next_action = "Attach the approved change ticket or mark the row as unauthorized drift before closure."
    elif "source-control/IaC evidence" in blockers:
        next_action = "Attach deployment/source-control evidence, codify the drift, or revert through approved deployment."
    elif "query_id proof" in blockers:
        next_action = "Capture the Snowflake query_id and timestamp before accepting the change."
    elif readiness == "Route Blocked":
        next_action = "Assign a named owner and approver before queueing or closing the change."
    else:
        next_action = "Review blast radius, retain approval proof, and close only after verification evidence is attached."

    return {
        "APPROVAL_ROUTE_READY": "Yes" if owner_route_ready and (not approval_required or bool(approver)) else "No",
        "CHANGE_EVIDENCE_READINESS": readiness,
        "EVIDENCE_BLOCKERS": "; ".join(blockers) if blockers else "None",
        "REVIEW_SLA_HOURS": _change_review_sla_hours(severity, row.get("FINDING_TYPE")),
        "NEXT_CONTROL_ACTION": next_action,
    }


def _enrich_change_control_evidence(readiness: pd.DataFrame) -> pd.DataFrame:
    if readiness is None or readiness.empty:
        return readiness
    view = readiness.copy()
    contexts = view.apply(_change_owner_context, axis=1)
    view["OWNER"] = contexts.apply(lambda item: item["owner"])
    view["ESCALATION_TARGET"] = contexts.apply(lambda item: item["escalation"])
    view["OWNER_SOURCE"] = contexts.apply(lambda item: item["source"])
    view["OWNER_EMAIL"] = contexts.apply(lambda item: item.get("owner_email", ""))
    view["ONCALL_PRIMARY"] = contexts.apply(lambda item: item.get("oncall_primary", ""))
    view["ONCALL_SECONDARY"] = contexts.apply(lambda item: item.get("oncall_secondary", ""))
    view["APPROVAL_GROUP"] = contexts.apply(lambda item: item.get("approval_group", ""))
    view["OWNER_EVIDENCE"] = contexts.apply(lambda item: item.get("owner_evidence", ""))
    view["DATABASE_NAME"] = view.apply(_change_database_name, axis=1)
    view["DATABASE_CONTEXT"] = view.apply(_change_database_context, axis=1)
    view["ENVIRONMENT"] = view.apply(_change_environment, axis=1)
    view["SCOPE_CONFIDENCE"] = view["DATABASE_CONTEXT"].map({True: "Database Context", False: "Account/Role Context"})
    view["SCOPE_EVIDENCE"] = view.apply(
        lambda row: (
            f"Database={row.get('DATABASE_NAME')}; environment={row.get('ENVIRONMENT')}"
            if bool(row.get("DATABASE_CONTEXT"))
            else "No database context; environment filter retained account-level change"
        ),
        axis=1,
    )
    view["CHANGE_TICKET_ID"] = view.apply(_change_ticket_id, axis=1)
    view["CHANGE_TICKET_STATE"] = view["CHANGE_TICKET_ID"].apply(
        lambda value: "Ticket detected" if str(value or "").strip() else "Missing ticket evidence"
    )
    view["IAC_RECONCILIATION_STATE"] = view.apply(_change_iac_state, axis=1)
    view["EXECUTION_AUDIT_STATE"] = view.apply(_change_execution_audit_state, axis=1)

    missing_ticket = view["CHANGE_TICKET_ID"].fillna("").astype(str).str.strip().eq("")
    missing_iac = view["IAC_RECONCILIATION_STATE"].fillna("").astype(str).str.contains("required|reconcile", case=False, na=False)
    missing_query = view["EXECUTION_AUDIT_STATE"].fillna("").astype(str).str.contains("missing", case=False, na=False)
    view.loc[missing_ticket, "CONTROL_GAP"] = "Missing change ticket evidence"
    view.loc[missing_iac, "CONTROL_GAP"] = "Missing IaC reconciliation evidence"
    view.loc[missing_query, "CONTROL_GAP"] = "Missing query_id proof"
    readiness_rows = view.apply(_change_control_readiness_for_row, axis=1)
    for column in [
        "APPROVAL_ROUTE_READY",
        "CHANGE_EVIDENCE_READINESS",
        "EVIDENCE_BLOCKERS",
        "REVIEW_SLA_HOURS",
        "NEXT_CONTROL_ACTION",
    ]:
        view[column] = readiness_rows.apply(lambda item, col=column: item.get(col, ""))
    return view


def _change_control_readiness_summary(readiness: pd.DataFrame) -> pd.DataFrame:
    """Summarize change-control blockers by environment, finding, and owner route."""
    if readiness is None or readiness.empty:
        return pd.DataFrame()
    view = _enrich_change_control_evidence(readiness)
    if view.empty:
        return pd.DataFrame()
    severity = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    view["_HIGH_RISK"] = severity.isin(["CRITICAL", "HIGH"])
    view["_MISSING_TICKET"] = view.get("CHANGE_TICKET_STATE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.lower().str.startswith("missing")
    view["_IAC_GAP"] = view.get("IAC_RECONCILIATION_STATE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.contains("required|reconcile", case=False, na=False)
    view["_MISSING_QUERY"] = view.get("EXECUTION_AUDIT_STATE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.lower().str.startswith("missing")
    view["_ACCOUNT_SCOPE"] = ~view.get("DATABASE_CONTEXT", pd.Series([False] * len(view), index=view.index)).astype(bool)
    view["_ROUTE_BLOCKED"] = view.get("CHANGE_EVIDENCE_READINESS", pd.Series([""] * len(view), index=view.index)).eq("Route Blocked")
    view["_CLOSURE_BLOCKED"] = view.get("CHANGE_EVIDENCE_READINESS", pd.Series([""] * len(view), index=view.index)).eq("Closure Blocked")
    view["_READY"] = view.get("CHANGE_EVIDENCE_READINESS", pd.Series([""] * len(view), index=view.index)).eq("Review Ready")

    group_cols = ["ENVIRONMENT", "FINDING_TYPE", "OWNER", "APPROVER"]
    for column in group_cols:
        if column not in view.columns:
            view[column] = ""

    rows = []
    for keys, group in view.groupby(group_cols, dropna=False):
        env, finding, owner, approver = keys
        missing_ticket = int(group["_MISSING_TICKET"].sum())
        iac_gap = int(group["_IAC_GAP"].sum())
        missing_query = int(group["_MISSING_QUERY"].sum())
        route_blocked = int(group["_ROUTE_BLOCKED"].sum())
        closure_blocked = int(group["_CLOSURE_BLOCKED"].sum())
        ready = int(group["_READY"].sum())
        if route_blocked:
            next_action = "Complete named owner and approver routing before accepting change evidence."
            readiness_label = "Route Blocked"
            rank = 0
        elif closure_blocked:
            next_action = "Attach missing ticket, query, or source-control evidence before closure."
            readiness_label = "Closure Blocked"
            rank = 1
        elif ready:
            next_action = "Review blast radius and close only after verification evidence is retained."
            readiness_label = "Review Ready"
            rank = 8
        else:
            next_action = "Review change-control metadata."
            readiness_label = "Review Required"
            rank = 5
        rows.append({
            "ENVIRONMENT": env,
            "FINDING_TYPE": finding,
            "OWNER": owner,
            "APPROVER": approver,
            "READINESS": readiness_label,
            "READINESS_RANK": rank,
            "TOTAL_CHANGES": int(len(group)),
            "HIGH_RISK_CHANGES": int(group["_HIGH_RISK"].sum()),
            "ROUTE_BLOCKED": route_blocked,
            "CLOSURE_BLOCKED": closure_blocked,
            "REVIEW_READY": ready,
            "MISSING_TICKET_ROWS": missing_ticket,
            "IAC_GAP_ROWS": iac_gap,
            "MISSING_QUERY_ID_ROWS": missing_query,
            "ACCOUNT_SCOPE_ROWS": int(group["_ACCOUNT_SCOPE"].sum()),
            "OLDEST_LAST_SEEN": group.get("LAST_SEEN", pd.Series(dtype=str)).min() if "LAST_SEEN" in group.columns else "",
            "REVIEW_SLA_HOURS": int(pd.to_numeric(group.get("REVIEW_SLA_HOURS", pd.Series([168])), errors="coerce").fillna(168).min()),
            "NEXT_CONTROL_ACTION": next_action,
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        ["READINESS_RANK", "HIGH_RISK_CHANGES", "MISSING_TICKET_ROWS", "IAC_GAP_ROWS", "TOTAL_CHANGES"],
        ascending=[True, False, False, False, False],
    ).reset_index(drop=True)


def _change_frame_sum(frame: pd.DataFrame | None, column: str) -> int:
    if frame is None or frame.empty or column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _change_operator_next_moves(
    *,
    score: int | float,
    exceptions: pd.DataFrame | None,
    readiness_summary: pd.DataFrame | None = None,
    readiness: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    operability_fact: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a no-query decision gate for loaded change and drift evidence."""
    exception_count = 0 if exceptions is None or exceptions.empty else int(len(exceptions))
    summary = pd.DataFrame() if readiness_summary is None else readiness_summary.copy()
    detail = pd.DataFrame() if readiness is None else readiness.copy()
    close = pd.DataFrame() if closure is None else closure.copy()
    fact = pd.DataFrame() if operability_fact is None else operability_fact.copy()
    for frame in (summary, detail, close, fact):
        if not frame.empty:
            frame.columns = [str(col).upper() for col in frame.columns]

    route_blocked = max(
        _change_frame_sum(summary, "ROUTE_BLOCKED"),
        _change_frame_sum(fact, "ROUTE_BLOCKED"),
    )
    closure_blocked = max(
        _change_frame_sum(summary, "CLOSURE_BLOCKED"),
        _change_frame_sum(fact, "CLOSURE_BLOCKED"),
    )
    missing_ticket = max(
        _change_frame_sum(summary, "MISSING_TICKET_ROWS"),
        _change_frame_sum(fact, "MISSING_TICKET_ROWS"),
    )
    iac_gap = max(
        _change_frame_sum(summary, "IAC_GAP_ROWS"),
        _change_frame_sum(fact, "IAC_GAP_ROWS"),
    )
    missing_query = max(
        _change_frame_sum(summary, "MISSING_QUERY_ID_ROWS"),
        _change_frame_sum(fact, "MISSING_QUERY_ID_ROWS"),
    )
    account_scope = max(
        _change_frame_sum(summary, "ACCOUNT_SCOPE_ROWS"),
        int((~detail.get("DATABASE_CONTEXT", pd.Series(dtype=bool)).astype(bool)).sum()) if not detail.empty and "DATABASE_CONTEXT" in detail.columns else 0,
    )
    high_risk = max(
        _change_frame_sum(summary, "HIGH_RISK_CHANGES"),
        _change_frame_sum(fact, "HIGH_RISK_CHANGES"),
    )
    overdue = max(
        _change_frame_sum(close, "OVERDUE_OPEN"),
        _change_frame_sum(fact, "OVERDUE_OPEN"),
    )
    fixed_without_verification = max(
        _change_frame_sum(close, "FIXED_WITHOUT_VERIFICATION"),
        _change_frame_sum(fact, "FIXED_WITHOUT_VERIFICATION"),
    )
    recovery_risk = max(
        _change_frame_sum(close, "RECOVERY_RISK_ROWS"),
        _change_frame_sum(fact, "RECOVERY_RISK_ROWS"),
    )
    closure_proof_blocks = max(
        _change_frame_sum(close, "CLOSURE_BLOCKER_ROWS"),
        overdue + fixed_without_verification + recovery_risk,
    )
    evidence_gaps = closure_blocked + missing_ticket + iac_gap + missing_query

    rows: list[dict] = []
    if route_blocked:
        state = "Route Blocked"
        rank = 0
        next_action = "Assign named owners and approvers before accepting or queueing the change."
        count = route_blocked
    elif exception_count:
        state = "Route Ready"
        rank = 6
        next_action = "Use the readiness rows to confirm owner and approver evidence before closure."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "No change route needs owner intervention in the loaded scope."
        count = 0
    rows.append({
        "GATE": "Owner approval route",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "named owner, approver, approval group, owner evidence",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if evidence_gaps:
        state = "Evidence Blocked"
        rank = 1
        next_action = "Attach ticket, source-control/IaC, query_id, and blast-radius proof before closure."
        count = evidence_gaps
    elif exception_count:
        state = "Review Ready"
        rank = 6
        next_action = "Save the evidence snapshot, then queue only verified exceptions that still need DBA action."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "No ticket, IaC, or query proof gap crossed the current thresholds."
        count = 0
    rows.append({
        "GATE": "Change proof",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "change ticket, query_id, source-control/IaC note, blast-radius evidence",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if closure_proof_blocks:
        state = "Closure Blocked"
        rank = 2
        next_action = "Reopen or hold change actions until verification and recovery evidence is attached."
        count = closure_proof_blocks
    elif exception_count and close.empty:
        state = "Load Closure Analytics"
        rank = 4
        next_action = "Load closure analytics before claiming drift or change-control work is complete."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "Retain verified closure evidence for audit review."
        count = _change_frame_sum(close, "VERIFIED_CLOSURES") + _change_frame_sum(fact, "VERIFIED_CLOSURES")
    rows.append({
        "GATE": "Closure proof",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "verification result, recovery evidence, ticket closure, owner approval",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if account_scope:
        state = "Account-Scope Review"
        rank = 3
        next_action = "Validate account/role-only changes separately; database environment scope cannot prove ownership alone."
        count = account_scope
    else:
        state = "Database Scoped"
        rank = 8
        next_action = "Use the selected environment/database evidence for scoped change review."
        count = 0
    rows.append({
        "GATE": "Scope confidence",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "database context where present; explicit account-level approval where database context is absent",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    recovery_sensitive = 0
    if exceptions is not None and not exceptions.empty:
        finding_text = exceptions.get("FINDING_TYPE", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        recovery_sensitive = int(
            finding_text.str.contains("DESTRUCTIVE|DROP|POLICY|TAG|OWNER", regex=True, na=False).sum()
        )
    if recovery_risk or recovery_sensitive:
        state = "Recovery Proof Required"
        rank = 3
        next_action = "Attach restore, rollback, downstream dependency, and owner approval evidence before accepting this change."
        count = max(recovery_risk, recovery_sensitive)
    else:
        state = "Clear"
        rank = 8
        next_action = "No destructive, ownership, or policy/tag change currently requires extra recovery proof."
        count = 0
    rows.append({
        "GATE": "Recovery readiness",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "restore path, rollback plan, dependency impact, owner approval, post-change verification",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if high_risk or safe_float(score) < 95:
        state = "Review Required" if high_risk else "Watch"
        rank = 5
        next_action = "Work high-risk destructive, policy, owner, role, and manual drift rows before routine changes."
        count = high_risk or exception_count
    else:
        state = "Controlled"
        rank = 8
        next_action = "No high-risk change exceeded the current threshold."
        count = 0
    rows.append({
        "GATE": "Change pressure",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "severity, finding type, user, role, last seen, blast-radius review",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    return pd.DataFrame(rows).sort_values(["GATE_RANK", "COUNT"], ascending=[True, False]).reset_index(drop=True)


def _change_drift_score(
    *,
    object_changes: int,
    access_changes: int,
    policy_changes: int,
    owner_changes: int,
    destructive_changes: int,
    manual_drift: int,
) -> int:
    object_penalty = min(15, safe_float(object_changes) * 0.3)
    access_penalty = min(20, safe_float(access_changes) * 0.8)
    policy_penalty = min(25, safe_float(policy_changes) * 4)
    owner_penalty = min(20, safe_float(owner_changes) * 3)
    destructive_penalty = min(25, safe_float(destructive_changes) * 5)
    drift_penalty = min(20, safe_float(manual_drift) * 1.5)
    return max(0, min(100, int(round(
        100
        - object_penalty
        - access_penalty
        - policy_penalty
        - owner_penalty
        - destructive_penalty
        - drift_penalty
    ))))


def _change_drift_rating(score: int) -> str:
    if score >= 95:
        return "Controlled"
    if score >= 85:
        return "Watch"
    if score >= 70:
        return "Elevated"
    return "High Drift Risk"


def _change_action_for(finding_type: str) -> tuple[str, str, str]:
    value = str(finding_type or "").lower()
    if "drop" in value or "destructive" in value:
        return (
            "Object",
            "Confirm change approval, downstream dependencies, backup/recovery posture, and whether the object should be restored.",
            "-- Proof: QUERY_HISTORY destructive DDL query_id and query text.",
        )
    if "policy" in value or "tag" in value or "masking" in value:
        return (
            "Policy/Tag",
            "Validate policy owner, classification impact, and whether masking/tag changes match governance approval.",
            "-- Proof: QUERY_HISTORY masking/tag/row-access policy DDL.",
        )
    if "grant" in value or "role" in value or "owner" in value:
        return (
            "Grant/Role",
            "Confirm requester, approver, role hierarchy, and ownership transfer before accepting the access change.",
            "-- Proof: QUERY_HISTORY grant/revoke/ownership DDL.",
        )
    if "drift" in value:
        return (
            "Drift",
            "Compare the query with Terraform/IaC state; either codify the change or revert it through approved deployment.",
            "-- Proof: QUERY_HISTORY non-IaC DDL/DCL query text and query tag.",
        )
    return (
        "Object",
        "Review change for approval, ownership, dependency impact, and drift risk.",
        "-- Proof: QUERY_HISTORY change statement.",
    )


def _change_approval_for(finding_type: str) -> tuple[str, str, str]:
    value = str(finding_type or "").lower()
    if "drop" in value or "destructive" in value:
        return (
            "Requested",
            "DBA Lead / Data Owner",
            "Destructive DDL requires data-owner approval, dependency review, and recovery evidence.",
        )
    if "policy" in value or "tag" in value or "masking" in value:
        return (
            "Requested",
            "Security Owner / Data Governance",
            "Policy, tag, masking, and row-access changes require security/governance approval.",
        )
    if "grant" in value or "role" in value or "owner" in value:
        return (
            "Requested",
            "Security Owner",
            "Grant, revoke, role, and ownership changes require access-request approval evidence.",
        )
    if "drift" in value:
        return (
            "Requested",
            "DBA Lead / Platform Owner",
            "Manual drift must be tied to a change ticket, codified in IaC, or reverted through deployment.",
        )
    return (
        "Requested",
        "Data Owner",
        "Object changes require requester, approver, and change-ticket evidence before closure.",
    )


def _change_verification_sql(query_id: object) -> str:
    query_id_text = str(query_id or "").strip()
    if not query_id_text:
        return """
SELECT
    query_id,
    start_time,
    user_name,
    role_name,
    database_name,
    schema_name,
    query_type,
    query_tag,
    query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE 1 = 0
LIMIT 50""".strip()
    return f"""
SELECT
    query_id,
    start_time,
    user_name,
    role_name,
    database_name,
    schema_name,
    query_type,
    query_tag,
    query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_id = {sql_literal(query_id_text, 200)}
LIMIT 50""".strip()


def _change_blast_radius_sql(entity: object) -> str:
    """Build read-only object dependency evidence for a changed object or schema."""
    raw = str(entity or "").strip()
    pieces = _split_snowflake_qualified_name(raw)
    if not pieces or raw.lower() in {"unknown", "snowflake account"}:
        return """
SELECT
    referenced_database,
    referenced_schema,
    referenced_object_name,
    referencing_database,
    referencing_schema,
    referencing_object_name,
    dependency_type
FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
WHERE 1 = 0
LIMIT 100""".strip()

    predicates = []
    if len(pieces) >= 3:
        db_name, schema_name, object_name = pieces[0], pieces[1], pieces[2]
        predicates.append(
            "("
            f"UPPER(referenced_database) = UPPER({sql_literal(db_name, 300)}) "
            f"AND UPPER(referenced_schema) = UPPER({sql_literal(schema_name, 300)}) "
            f"AND UPPER(referenced_object_name) = UPPER({sql_literal(object_name, 500)})"
            ")"
        )
        predicates.append(
            "("
            f"UPPER(referencing_database) = UPPER({sql_literal(db_name, 300)}) "
            f"AND UPPER(referencing_schema) = UPPER({sql_literal(schema_name, 300)}) "
            f"AND UPPER(referencing_object_name) = UPPER({sql_literal(object_name, 500)})"
            ")"
        )
    elif len(pieces) == 2:
        db_name, schema_name = pieces[0], pieces[1]
        predicates.append(
            "("
            f"UPPER(referenced_database) = UPPER({sql_literal(db_name, 300)}) "
            f"AND UPPER(referenced_schema) = UPPER({sql_literal(schema_name, 300)})"
            ")"
        )
        predicates.append(
            "("
            f"UPPER(referencing_database) = UPPER({sql_literal(db_name, 300)}) "
            f"AND UPPER(referencing_schema) = UPPER({sql_literal(schema_name, 300)})"
            ")"
        )
    else:
        db_name = pieces[0]
        predicates.append(f"UPPER(referenced_database) = UPPER({sql_literal(db_name, 300)})")
        predicates.append(f"UPPER(referencing_database) = UPPER({sql_literal(db_name, 300)})")

    where_clause = " OR\n      ".join(predicates)
    return f"""
SELECT
    referenced_database,
    referenced_schema,
    referenced_object_name,
    referenced_object_domain,
    referencing_database,
    referencing_schema,
    referencing_object_name,
    referencing_object_domain,
    dependency_type
FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
WHERE {where_clause}
ORDER BY referenced_database, referenced_schema, referenced_object_name, referencing_database, referencing_schema, referencing_object_name
LIMIT 100""".strip()


def _build_change_control_readiness(exceptions: pd.DataFrame) -> pd.DataFrame:
    """Add ticket, approval, and proof requirements before queueing changes."""
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    view = _change_priority_view(exceptions).copy()
    approval_rows = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(_change_approval_for)
    view["APPROVAL_REQUIRED"] = "Yes"
    view["OWNER_APPROVAL_STATUS"] = approval_rows.apply(lambda item: item[0])
    view["APPROVER"] = approval_rows.apply(lambda item: item[1])
    view["OWNER_APPROVAL_NOTE"] = approval_rows.apply(lambda item: item[2])
    view["TICKET_REQUIRED"] = "Yes"
    view["VERIFICATION_QUERY"] = view.get("QUERY_ID", pd.Series([""] * len(view), index=view.index)).apply(_change_verification_sql)
    view["BLAST_RADIUS_QUERY"] = view.get("ENTITY", pd.Series([""] * len(view), index=view.index)).apply(_change_blast_radius_sql)
    view["BLAST_RADIUS_REQUIRED"] = "Yes"
    view["PROOF_REQUIRED"] = "query_id, approver, change ticket, dependency/blast-radius note"

    query_missing = view.get("QUERY_ID", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.strip().eq("")
    high_risk = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper().isin(["CRITICAL", "HIGH"])
    finding = view.get("FINDING_TYPE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.lower()

    view["CONTROL_GAP"] = "Needs approver, change ticket, and blast-radius note"
    view.loc[query_missing, "CONTROL_GAP"] = "Missing query_id proof"
    view["CHANGE_CONTROL_STATE"] = "Validate Approval"
    view.loc[finding.str.contains("drift", na=False), "CHANGE_CONTROL_STATE"] = "Reconcile IaC"
    view.loc[high_risk, "CHANGE_CONTROL_STATE"] = "Approval Required"
    view.loc[query_missing, "CHANGE_CONTROL_STATE"] = "Proof Missing"
    return _enrich_change_control_evidence(view)


def _change_action_payload(row: pd.Series | dict, company: str, environment: str = "") -> dict:
    finding_type = str(row.get("FINDING_TYPE") or "Change")
    entity = str(row.get("ENTITY") or row.get("QUERY_ID") or "Snowflake account")
    user_name = str(row.get("USER_NAME") or "unknown")
    severity = str(row.get("SEVERITY") or "Medium")
    query_id = str(row.get("QUERY_ID") or "").strip()
    entity_type, action, generated_sql = _change_action_for(finding_type)
    approval_status, approver, approval_note = _change_approval_for(finding_type)
    owner_context = _change_owner_context(row)
    ticket_id = _change_ticket_id(row)
    ticket_state = "ticket detected" if ticket_id else "missing ticket evidence"
    iac_state = _change_iac_state(row)
    audit_state = _change_execution_audit_state(row)
    env_value = str(row.get("ENVIRONMENT") or _change_environment(row, environment) or environment or "ALL")
    verification_query = _change_verification_sql(query_id)
    blast_radius_query = _change_blast_radius_sql(entity)
    finding = f"{finding_type} by {user_name} on {entity}"
    generated_review = "\n".join([
        "-- Review-only change-control record. Do not execute state-changing SQL from this queue row.",
        generated_sql,
        f"-- Required proof: query_id={query_id or 'missing'}, approver, change ticket, and dependency/blast-radius note.",
        f"-- Ticket evidence: {ticket_id or 'missing'} ({ticket_state}).",
        f"-- IaC/source-control state: {iac_state}.",
        f"-- Execution audit state: {audit_state}.",
        "-- Read-only blast-radius check to run before approval:",
        blast_radius_query,
    ])
    return {
        "Action ID": make_action_id("Change Drift", entity, f"{finding}|{query_id}"),
        "Source": "Change & Drift - Brief",
        "Severity": severity,
        "Category": "Change Control",
        "Entity Type": entity_type,
        "Entity": entity,
        "Owner": owner_context["owner"],
        "Owner Email": owner_context.get("owner_email", ""),
        "Oncall Primary": owner_context.get("oncall_primary", ""),
        "Oncall Secondary": owner_context.get("oncall_secondary", ""),
        "Approval Group": owner_context.get("approval_group", approver),
        "Escalation Target": owner_context.get("escalation", ""),
        "Owner Source": owner_context.get("source", ""),
        "Owner Evidence": owner_context.get("owner_evidence", ""),
        "Finding": finding,
        "Action": action,
        "Estimated Monthly Savings": 0.0,
        "Generated SQL Fix": generated_review,
        "Proof Query": verification_query,
        "Verification Query": verification_query,
        "Verification Status": "Pending",
        "Approver": approver,
        "Owner Approval Status": approval_status,
        "Owner Approval Note": (
            f"{approval_note} Ticket={ticket_id or 'missing'}; "
            f"IaC={iac_state}; escalation={owner_context['escalation']}."
        ),
        "Recovery Evidence": (
            f"Run blast-radius check before closure:\n{blast_radius_query}\n\n"
            f"Ticket evidence: {ticket_id or 'missing'}\n"
            f"IaC/source-control evidence: {iac_state}\n"
            f"Execution audit: {audit_state}"
        ),
        "Recovery Audit State": audit_state,
        "Recovery SLA Target Hours": 24 if severity.upper() in {"CRITICAL", "HIGH"} else 72,
        "Company": company,
        "Environment": env_value,
        "Ticket ID": ticket_id,
    }


def _change_workflow_for(row: pd.Series) -> str:
    finding_type = str(row.get("FINDING_TYPE") or "").lower()
    query_text = str(row.get("QUERY_TEXT") or "").lower()
    if "drift" in finding_type:
        return "Schema and object drift"
    if "procedure" in query_text:
        return "Stored procedure lineage"
    if "dynamic table" in query_text or "replication" in query_text or "pipe" in query_text:
        return "Data movement and replication"
    if "grant" in finding_type or "role" in finding_type or "owner" in finding_type or "policy" in finding_type or "tag" in finding_type:
        return "Object and access changes"
    return "Object and access changes"


def _change_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = exceptions.copy()
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(4)
    view["ENTITY_TYPE"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(lambda value: _change_action_for(value)[0])
    view["NEXT_ACTION"] = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(lambda value: _change_action_for(value)[1])
    view["NEXT_WORKFLOW"] = view.apply(_change_workflow_for, axis=1)
    sort_cols = ["_RANK"]
    ascending = [True]
    if "LAST_SEEN" in view.columns:
        sort_cols.append("LAST_SEEN")
        ascending.append(False)
    return view.sort_values(sort_cols, ascending=ascending).drop(columns=["_RANK"], errors="ignore")


def _change_intervention_matrix(
    exceptions: pd.DataFrame,
    readiness: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rank change/drift rows by whether the DBA can verify, reconcile, or must block closure."""
    priority = _change_priority_view(exceptions)
    if priority.empty:
        return pd.DataFrame()

    ready = readiness if isinstance(readiness, pd.DataFrame) else pd.DataFrame()
    closure_df = closure if isinstance(closure, pd.DataFrame) else pd.DataFrame()
    ready_by_key = {}
    if not ready.empty:
        for _, row in ready.iterrows():
            key = (
                str(row.get("FINDING_TYPE") or "").upper(),
                str(row.get("ENTITY") or "").upper(),
                str(row.get("QUERY_ID") or "").upper(),
            )
            ready_by_key[key] = row
    closure_by_entity = {
        str(row.get("CHANGE_ENTITY") or row.get("ENTITY") or row.get("CHECK_NAME") or "").upper(): row
        for _, row in closure_df.iterrows()
    } if not closure_df.empty else {}

    rows: list[dict] = []
    for _, item in priority.head(30).iterrows():
        finding = str(item.get("FINDING_TYPE") or "Change")
        entity = str(item.get("ENTITY") or "Snowflake account")
        query_id = str(item.get("QUERY_ID") or "").strip()
        ready_row = ready_by_key.get((finding.upper(), entity.upper(), query_id.upper()), {})
        closure_row = closure_by_entity.get(entity.upper(), {})
        severity = str(item.get("SEVERITY") or "Medium")
        control_state = str(ready_row.get("CHANGE_CONTROL_STATE") or item.get("CHANGE_CONTROL_STATE") or "Review")
        ticket_state = str(ready_row.get("CHANGE_TICKET_STATE") or "")
        iac_state = str(ready_row.get("IAC_RECONCILIATION_STATE") or "")
        closure_state = str(closure_row.get("CLOSURE_READINESS") or "No recent action")
        finding_upper = finding.upper()
        recovery_sensitive = any(token in finding_upper for token in ("DESTRUCTIVE", "DROP", "POLICY", "TAG", "OWNER"))
        missing_query = not query_id
        missing_ticket = "MISSING" in ticket_state.upper() or not str(ready_row.get("CHANGE_TICKET_ID") or "").strip()
        iac_gap = "GAP" in iac_state.upper() or "MISSING" in iac_state.upper()
        closure_bad = any(token in closure_state.upper() for token in ("OVERDUE", "WITHOUT VERIFICATION", "GAP"))

        if recovery_sensitive:
            state = "Recovery Block"
            rank = 0
            decision = "Block closure until restore path, dependency blast radius, owner approval, and rollback proof exist."
        elif missing_query or missing_ticket or iac_gap or closure_bad:
            state = "Evidence Block"
            rank = 1
            decision = "Attach query_id, ticket/source-control evidence, and verification proof before accepting the change."
        elif severity.upper() in {"CRITICAL", "HIGH"}:
            state = "Verify Now"
            rank = 2
            decision = "Review actor, role, blast radius, and approval path before queueing the action."
        else:
            state = "Watch"
            rank = 4
            decision = "Keep for trend review; no immediate high-risk intervention signal."

        rows.append({
            "DBA_PRIORITY": f"P{rank}",
            "INTERVENTION_STATE": state,
            "SEVERITY": severity,
            "FINDING_TYPE": finding,
            "ENTITY": entity,
            "USER_NAME": str(item.get("USER_NAME") or "unknown"),
            "ROLE_NAME": str(item.get("ROLE_NAME") or ""),
            "QUERY_ID": query_id,
            "CONTROL_STATE": control_state,
            "TICKET_STATE": ticket_state or "Missing",
            "IAC_STATE": iac_state or "Missing",
            "CLOSURE_READINESS": closure_state,
            "NEXT_DECISION": decision,
            "PROOF_REQUIRED": "query_id, change ticket, source-control/IaC note, blast-radius evidence, owner approval",
            "NEXT_WORKFLOW": str(item.get("NEXT_WORKFLOW") or _change_workflow_for(item)),
            "_RANK": rank,
        })

    return pd.DataFrame(rows).sort_values(
        ["_RANK", "SEVERITY", "FINDING_TYPE", "ENTITY"],
        ascending=[True, True, True, True],
    ).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _render_change_watch_floor(score: int, exceptions: pd.DataFrame, row) -> None:
    priority = _change_priority_view(exceptions).head(3)
    high_risk = 0
    if exceptions is not None and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())
    actors = safe_int(row.get("ACTORS", 0))
    affected_dbs = safe_int(row.get("AFFECTED_DATABASES", 0))

    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.1, 2.2])
    c1.metric("Change Readiness", f"{score}/100", _change_drift_rating(score))
    c2.metric("High-Risk Changes", f"{high_risk:,}", delta_color="inverse")
    c3.metric("Manual Drift", f"{safe_int(row.get('MANUAL_DRIFT', 0)):,}", delta_color="inverse")
    with c4:
        if priority.empty:
            st.success("No urgent change/drift exceptions crossed the brief thresholds.")
        else:
            first = priority.iloc[0]
            st.warning(
                f"First move: {first.get('FINDING_TYPE', 'Change')} by "
                f"{first.get('USER_NAME', 'unknown')} -> {first.get('NEXT_ACTION', 'Validate the change.')}"
            )

    st.markdown("**Change Watch Floor**")
    st.caption(f"Actors: {actors:,} | Affected databases: {affected_dbs:,}")
    if priority.empty:
        st.caption("No immediate change cards. Use Object and access changes for investigation or Schema and object drift for periodic control review.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = str(item.get("NEXT_WORKFLOW") or "Object and access changes")
        with cols[idx]:
            st.markdown(f"**{item.get('SEVERITY', 'Medium')}: {item.get('FINDING_TYPE', '')}**")
            st.caption(f"{item.get('ENTITY_TYPE', 'Object')}: {item.get('ENTITY', 'unknown')}")
            st.caption(f"Actor: {item.get('USER_NAME', 'unknown')} | Query: {item.get('QUERY_ID', '')}")
            st.write(str(item.get("NEXT_ACTION", "")))
            if st.button(f"Open {workflow}", key=f"change_watch_floor_{idx}_{workflow}", width="stretch"):
                entity = str(item.get("ENTITY") or "").strip()
                actor = str(item.get("USER_NAME") or "").strip()
                query_id = str(item.get("QUERY_ID") or "").strip()
                if actor and actor.lower() != "unknown":
                    st.session_state["global_user"] = actor
                if entity and entity.lower() != "unknown" and not entity.startswith("01"):
                    st.session_state["global_database"] = entity.split(".")[0]
                if query_id:
                    st.session_state["qs_text"] = query_id
                    st.session_state["qs_status"] = "ALL"
                    st.session_state["qs_autorun"] = True
                for stale_key in (
                    "ocm_df_object_changes",
                    "ocm_df_access_changes",
                    "ocm_df_policy_changes",
                    "ocm_df_drift",
                ):
                    st.session_state.pop(stale_key, None)
                st.session_state["change_drift_workflow"] = workflow
                st.rerun()


def _build_change_drift_markdown(
    *,
    company: str,
    days: int,
    score: int,
    summary_row,
    exceptions: pd.DataFrame,
) -> str:
    exception_lines = []
    if exceptions is not None and not exceptions.empty:
        for _, row in exceptions.head(10).iterrows():
            exception_lines.append(
                f"- {row.get('SEVERITY', 'Medium')}: {row.get('FINDING_TYPE', 'Change')} "
                f"by {row.get('USER_NAME', 'unknown')} on {row.get('ENTITY', 'unknown')}."
            )
    else:
        exception_lines.append("- No change/drift exceptions crossed the configured thresholds.")
    lines = [
        f"# OVERWATCH Change & Drift Brief - {company}",
        "",
        f"Lookback window: {days} day(s).",
        f"Control score: {score} ({_change_drift_rating(score)}).",
        "",
        "## Key Metrics",
        f"- Object changes: {safe_int(summary_row.get('OBJECT_CHANGES', 0)):,}",
        f"- Access changes: {safe_int(summary_row.get('ACCESS_CHANGES', 0)):,}",
        f"- Owner changes: {safe_int(summary_row.get('OWNER_CHANGES', 0)):,}",
        f"- Policy/tag changes: {safe_int(summary_row.get('POLICY_CHANGES', 0)):,}",
        f"- Destructive changes: {safe_int(summary_row.get('DESTRUCTIVE_CHANGES', 0)):,}",
        f"- Manual/non-IaC drift indicators: {safe_int(summary_row.get('MANUAL_DRIFT', 0)):,}",
        "",
        "## Exceptions",
        *exception_lines,
        "",
        "## DBA Follow-Up",
        "- Review destructive and policy changes first.",
        "- Validate grants, revokes, and ownership transfers against approved access requests.",
        "- Compare manual/non-IaC changes with Terraform or deployment records.",
        "- Save material exceptions to the OVERWATCH Action Queue for owner/status tracking.",
        "",
        "## Confidence",
        "Source: QUERY_HISTORY. DDL/DCL detection is text-pattern based, so it is strong for investigation but should be validated against source control and change tickets.",
    ]
    return "\n".join(lines)


def _build_change_drift_sql(session, days: int, company: str) -> tuple[str, str]:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["QUERY_TAG"],
    ))
    query_tag_expr = "query_tag" if "QUERY_TAG" in qh_cols else "NULL::VARCHAR"
    manual_drift_predicate = (
        "AND COALESCE(query_tag, '') NOT ILIKE '%terraform%'"
        if "QUERY_TAG" in qh_cols else ""
    )
    scope = _change_scope_clause(
        date_col="start_time",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    base_where = f"""
        start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        {scope}
    """
    summary_sql = f"""
    WITH changes AS (
        SELECT
            query_id,
            user_name,
            role_name,
            warehouse_name,
            database_name,
            schema_name,
            start_time,
            {query_tag_expr} AS query_tag,
            query_text,
            CASE
                WHEN query_text ILIKE 'DROP%' THEN 'DESTRUCTIVE'
                WHEN query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%' THEN 'POLICY'
                WHEN query_text ILIKE '%OWNERSHIP%' THEN 'OWNER'
                WHEN query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE 'CREATE%ROLE%' OR query_text ILIKE 'ALTER%ROLE%' OR query_text ILIKE 'DROP%ROLE%' THEN 'ACCESS'
                WHEN query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' THEN 'OBJECT'
                ELSE 'OTHER'
            END AS change_family
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE {base_where}
          AND (
            query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%'
            OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE '%OWNERSHIP%'
            OR query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%'
          )
    )
    SELECT
        '{company}' AS company,
        COUNT_IF(change_family IN ('OBJECT', 'DESTRUCTIVE')) AS object_changes,
        COUNT_IF(change_family IN ('ACCESS', 'OWNER')) AS access_changes,
        COUNT_IF(change_family = 'OWNER') AS owner_changes,
        COUNT_IF(change_family = 'POLICY') AS policy_changes,
        COUNT_IF(change_family = 'DESTRUCTIVE') AS destructive_changes,
        COUNT_IF(change_family <> 'OTHER' {manual_drift_predicate}) AS manual_drift,
        COUNT(DISTINCT user_name) AS actors,
        COUNT(DISTINCT database_name) AS affected_databases,
        COUNT_IF(database_name IS NULL) AS account_scope_changes
    FROM changes
    """
    exceptions_sql = f"""
    WITH changes AS (
        SELECT
            query_id,
            user_name,
            role_name,
            warehouse_name,
            database_name,
            schema_name,
            start_time,
            {query_tag_expr} AS query_tag,
            SUBSTR(query_text, 1, 1500) AS query_text,
            CASE
                WHEN query_text ILIKE 'DROP%' THEN 'Destructive DDL'
                WHEN query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%' THEN 'Policy or Tag Change'
                WHEN query_text ILIKE '%OWNERSHIP%' THEN 'Owner Change'
                WHEN query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE 'CREATE%ROLE%' OR query_text ILIKE 'ALTER%ROLE%' OR query_text ILIKE 'DROP%ROLE%' THEN 'Grant or Role Change'
                WHEN query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' THEN 'Object Change'
                ELSE 'Other Change'
            END AS finding_type
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE {base_where}
          AND (
            query_text ILIKE 'CREATE%' OR query_text ILIKE 'ALTER%' OR query_text ILIKE 'DROP%'
            OR query_text ILIKE 'GRANT%' OR query_text ILIKE 'REVOKE%' OR query_text ILIKE '%OWNERSHIP%'
            OR query_text ILIKE '%MASKING POLICY%' OR query_text ILIKE '%ROW ACCESS POLICY%' OR query_text ILIKE '%TAG%'
          )
          {manual_drift_predicate}
    )
    SELECT
        finding_type,
        CASE
            WHEN finding_type IN ('Destructive DDL', 'Policy or Tag Change', 'Owner Change') THEN 'High'
            WHEN finding_type = 'Grant or Role Change' THEN 'Medium'
            ELSE 'Low'
        END AS severity,
        COALESCE(database_name || '.' || schema_name, database_name, query_id) AS entity,
        user_name,
        role_name,
        query_id,
        start_time AS last_seen,
        1 AS event_count,
        'QUERY_HISTORY query_id = ' || query_id AS proof_query,
        database_name,
        IFF(database_name IS NULL, FALSE, TRUE) AS database_context,
        {get_environment_case_expr("database_name")} AS environment,
        IFF(database_name IS NULL, 'Account/Role Context', 'Database Context') AS scope_confidence,
        IFF(database_name IS NULL, 'No database context; retained under environment scope', 'Database=' || database_name) AS scope_evidence,
        query_text
    FROM changes
    WHERE finding_type <> 'Other Change'
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        start_time DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


def _build_mart_change_drift_sql(days: int, company: str) -> tuple[str, str]:
    """Build change/drift brief SQL from the OVERWATCH object-change fact."""
    table = mart_object_name("FACT_OBJECT_CHANGE")
    company_filter = "" if str(company or "").upper() == "ALL" else f"AND company = {sql_literal(company, 100)}"
    scope = _change_scope_clause(
        date_col="start_time",
        wh_col="",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    base_where = f"""
        start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
        {company_filter}
        {scope}
    """
    summary_sql = f"""
    SELECT
        '{company}' AS company,
        COUNT_IF(change_category IN ('CREATE', 'ALTER', 'DROP')) AS object_changes,
        COUNT_IF(change_category IN ('GRANT', 'OWNER')) AS access_changes,
        COUNT_IF(change_category = 'OWNER') AS owner_changes,
        COUNT_IF(change_category = 'POLICY') AS policy_changes,
        COUNT_IF(change_category = 'DROP') AS destructive_changes,
        COUNT_IF(COALESCE(query_tag, '') NOT ILIKE '%terraform%') AS manual_drift,
        COUNT(DISTINCT user_name) AS actors,
        COUNT(DISTINCT database_name) AS affected_databases,
        COUNT_IF(database_name IS NULL) AS account_scope_changes
    FROM {table}
    WHERE {base_where}
    """
    exceptions_sql = f"""
    SELECT
        CASE
            WHEN change_category = 'DROP' THEN 'Destructive DDL'
            WHEN change_category = 'POLICY' THEN 'Policy or Tag Change'
            WHEN change_category = 'OWNER' THEN 'Owner Change'
            WHEN change_category = 'GRANT' THEN 'Grant or Role Change'
            WHEN change_category IN ('CREATE', 'ALTER') THEN 'Object Change'
            ELSE 'Other Change'
        END AS finding_type,
        CASE
            WHEN change_category IN ('DROP', 'POLICY', 'OWNER') THEN 'High'
            WHEN change_category = 'GRANT' THEN 'Medium'
            ELSE 'Low'
        END AS severity,
        COALESCE(database_name || '.' || schema_name, database_name, query_id) AS entity,
        user_name,
        role_name,
        query_id,
        start_time AS last_seen,
        1 AS event_count,
        'FACT_OBJECT_CHANGE query_id = ' || query_id AS proof_query,
        database_name,
        IFF(database_name IS NULL, FALSE, TRUE) AS database_context,
        {get_environment_case_expr("database_name")} AS environment,
        IFF(database_name IS NULL, 'Account/Role Context', 'Database Context') AS scope_confidence,
        IFF(database_name IS NULL, 'No database context; retained under environment scope', 'Database=' || database_name) AS scope_evidence,
        query_tag,
        SUBSTR(query_text, 1, 1500) AS query_text
    FROM {table}
    WHERE {base_where}
      AND change_category <> 'OTHER'
      AND COALESCE(query_tag, '') NOT ILIKE '%terraform%'
    ORDER BY
        CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END,
        start_time DESC
    LIMIT 100
    """
    return summary_sql, exceptions_sql


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
        st.success(f"Saved {saved} change/drift exceptions to the action queue with approval and verification fields.")
    except Exception as e:
        st.error(f"Could not save change/drift exceptions: {format_snowflake_error(e)}")
        st.info("Deploy the Action Queue table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _change_control_evidence_insert_sql(
    readiness: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
    snapshot_id: str = "",
) -> str:
    if readiness is None or readiness.empty:
        raise ValueError("Change-control evidence snapshot has no rows to save.")
    view = _enrich_change_control_evidence(readiness)
    fqn = change_control_evidence_fqn()
    env_value = str(environment or "").strip() or "ALL"
    snap = snapshot_id or make_action_id(
        "Change Control Evidence Snapshot",
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


def _change_control_evidence_history_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = change_control_evidence_fqn()
    where = [f"SNAPSHOT_TS >= DATEADD('day', -{max(1, int(days or 14))}, CURRENT_TIMESTAMP())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_value = str(environment or "").strip()
    if env_value and env_value.upper() != "ALL":
        where.append(f"ENVIRONMENT = {sql_literal(env_value, 100)}")
    where_clause = " AND ".join(where)
    return f"""
SELECT
    FINDING_TYPE,
    SEVERITY,
    OWNER,
    ESCALATION_TARGET,
    COUNT(*) AS EVIDENCE_ROWS,
    COUNT_IF(CHANGE_TICKET_STATE ILIKE 'Missing%') AS MISSING_TICKET_ROWS,
    COUNT_IF(IAC_RECONCILIATION_STATE ILIKE '%required%' OR IAC_RECONCILIATION_STATE ILIKE '%Reconcile%') AS IAC_GAP_ROWS,
    COUNT_IF(EXECUTION_AUDIT_STATE ILIKE 'Missing%') AS MISSING_QUERY_ID_ROWS,
    MAX(SNAPSHOT_TS) AS LAST_SNAPSHOT_TS,
    MAX_BY(CHANGE_CONTROL_STATE, SNAPSHOT_TS) AS LAST_CONTROL_STATE,
    MAX_BY(CONTROL_GAP, SNAPSHOT_TS) AS LAST_CONTROL_GAP
FROM {fqn}
WHERE {where_clause}
GROUP BY FINDING_TYPE, SEVERITY, OWNER, ESCALATION_TARGET
ORDER BY
    MISSING_TICKET_ROWS DESC,
    IAC_GAP_ROWS DESC,
    MISSING_QUERY_ID_ROWS DESC,
    LAST_SNAPSHOT_TS DESC
LIMIT 100""".strip()


def _change_action_queue_closure_sql(days: int, company: str, environment: str = "ALL") -> str:
    fqn = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.{safe_identifier(ACTION_QUEUE_TABLE)}"
    where = [
        "SOURCE = 'Change & Drift - Brief'",
        f"COALESCE(UPDATED_AT, CREATED_AT) >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_TIMESTAMP())",
    ]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
WITH scoped_actions AS (
    SELECT
        COALESCE(CATEGORY, 'Change Control') AS CATEGORY,
        COALESCE(ENTITY_TYPE, 'Change') AS ENTITY_TYPE,
        COALESCE(ENTITY_NAME, 'Unknown') AS ENTITY,
        COALESCE(OWNER, '') AS OWNER,
        COALESCE(APPROVER, '') AS APPROVER,
        COALESCE(STATUS, 'New') AS STATUS,
        COALESCE(SEVERITY, 'Medium') AS SEVERITY,
        COALESCE(TICKET_ID, '') AS TICKET_ID,
        DUE_DATE,
        COALESCE(VERIFICATION_STATUS, '') AS VERIFICATION_STATUS,
        COALESCE(VERIFICATION_QUERY, PROOF_QUERY, '') AS VERIFICATION_QUERY,
        COALESCE(VERIFICATION_RESULT, '') AS VERIFICATION_RESULT,
        COALESCE(OWNER_APPROVAL_STATUS, '') AS OWNER_APPROVAL_STATUS,
        COALESCE(RECOVERY_SLA_STATE, '') AS RECOVERY_SLA_STATE,
        COALESCE(RECOVERY_EVIDENCE, '') AS RECOVERY_EVIDENCE,
        COALESCE(UPDATED_AT, CREATED_AT) AS LAST_ACTIVITY_TS
    FROM {fqn}
    WHERE {where_clause}
),
rollup AS (
    SELECT
        CATEGORY,
        ENTITY_TYPE,
        ENTITY,
        MAX_BY(OWNER, LAST_ACTIVITY_TS) AS OWNER,
        MAX_BY(APPROVER, LAST_ACTIVITY_TS) AS APPROVER,
        COUNT(*) AS TOTAL_ACTIONS,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED')) AS OPEN_ACTIONS,
        COUNT_IF(UPPER(STATUS) = 'FIXED') AS FIXED_ACTIONS,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND UPPER(VERIFICATION_STATUS) = 'VERIFIED'
            AND LENGTH(TRIM(VERIFICATION_RESULT)) >= 15
        ) AS VERIFIED_CLOSURES,
        COUNT_IF(
            UPPER(STATUS) = 'FIXED'
            AND (
                UPPER(VERIFICATION_STATUS) <> 'VERIFIED'
                OR LENGTH(TRIM(VERIFICATION_RESULT)) < 15
            )
        ) AS FIXED_WITHOUT_VERIFICATION,
        COUNT_IF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED') AND DUE_DATE < CURRENT_DATE()) AS OVERDUE_OPEN,
        COUNT_IF(UPPER(OWNER) IN ('', 'DBA', 'UNKNOWN', 'N/A', 'DBA CHANGE OWNER')) AS OWNER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(TICKET_ID)) = 0) AS TICKET_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(APPROVER)) = 0) AS APPROVER_GAP_ROWS,
        COUNT_IF(LENGTH(TRIM(VERIFICATION_QUERY)) = 0) AS VERIFICATION_QUERY_GAP_ROWS,
        COUNT_IF(UPPER(OWNER_APPROVAL_STATUS) IN ('', 'PENDING', 'REQUESTED', 'REQUIRED')) AS OWNER_APPROVAL_GAP_ROWS,
        COUNT_IF(
            UPPER(RECOVERY_SLA_STATE) ILIKE '%BREACH%'
            OR UPPER(RECOVERY_SLA_STATE) ILIKE '%LATE%'
            OR (
                UPPER(STATUS) = 'FIXED'
                AND LENGTH(TRIM(RECOVERY_EVIDENCE)) < 15
            )
        ) AS RECOVERY_RISK_ROWS,
        MIN(IFF(UPPER(STATUS) NOT IN ('FIXED', 'IGNORED'), DUE_DATE, NULL)) AS NEXT_DUE_DATE,
        MAX(LAST_ACTIVITY_TS) AS LAST_ACTIVITY_TS,
        MAX_BY(STATUS, LAST_ACTIVITY_TS) AS LAST_STATUS,
        MAX_BY(SEVERITY, LAST_ACTIVITY_TS) AS LAST_SEVERITY
    FROM scoped_actions
    GROUP BY CATEGORY, ENTITY_TYPE, ENTITY
)
SELECT
    CATEGORY,
    ENTITY_TYPE,
    ENTITY,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Overdue closure'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Fixed without verification'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Control metadata gap'
        WHEN OPEN_ACTIONS > 0 THEN 'Open'
        WHEN VERIFIED_CLOSURES > 0 THEN 'Verified closure'
        ELSE 'No recent action'
    END AS CLOSURE_READINESS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 0
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 1
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 2
        WHEN OPEN_ACTIONS > 0 THEN 3
        WHEN VERIFIED_CLOSURES > 0 THEN 8
        ELSE 9
    END AS CLOSURE_RANK,
    OWNER,
    APPROVER,
    TOTAL_ACTIONS,
    OPEN_ACTIONS,
    FIXED_ACTIONS,
    VERIFIED_CLOSURES,
    FIXED_WITHOUT_VERIFICATION,
    OVERDUE_OPEN,
    OWNER_GAP_ROWS,
    TICKET_GAP_ROWS,
    APPROVER_GAP_ROWS,
    VERIFICATION_QUERY_GAP_ROWS,
    OWNER_APPROVAL_GAP_ROWS,
    RECOVERY_RISK_ROWS,
    NEXT_DUE_DATE,
    LAST_STATUS,
    LAST_SEVERITY,
    LAST_ACTIVITY_TS,
    CASE
        WHEN OVERDUE_OPEN > 0 THEN 'Escalate the change owner and ticket before accepting more drift.'
        WHEN FIXED_WITHOUT_VERIFICATION > 0 THEN 'Attach query, ticket, IaC, and blast-radius evidence or reopen the action.'
        WHEN OWNER_GAP_ROWS + TICKET_GAP_ROWS + APPROVER_GAP_ROWS + VERIFICATION_QUERY_GAP_ROWS + OWNER_APPROVAL_GAP_ROWS > 0 THEN 'Complete owner, ticket, approver, and verification metadata.'
        WHEN OPEN_ACTIONS > 0 THEN 'Work the open change action and retain source-control or rollback proof.'
        ELSE 'Retain verified closure evidence for audit review.'
    END AS NEXT_ACTION
FROM rollup
ORDER BY CLOSURE_RANK, OVERDUE_OPEN DESC, FIXED_WITHOUT_VERIFICATION DESC, OPEN_ACTIONS DESC, LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _change_control_operability_fact_sql(days: int, company: str, environment: str = "ALL") -> str:
    """Read pre-aggregated change-control blockers from the mart fact."""
    table = change_control_operability_fact_fqn()
    where = [f"SNAPSHOT_DATE >= DATEADD('day', -{max(1, int(days or 30))}, CURRENT_DATE())"]
    if str(company or "").upper() != "ALL":
        where.append(f"COMPANY = {sql_literal(company, 100)}")
    env_clause = action_queue_environment_clause("ENVIRONMENT", environment)
    if env_clause:
        where.append(env_clause)
    where_clause = " AND ".join(where)
    return f"""
SELECT
    SNAPSHOT_DATE,
    COMPANY,
    ENVIRONMENT,
    CONTROL_SOURCE,
    CONTROL_KEY,
    FINDING_TYPE,
    ENTITY,
    OWNER,
    ESCALATION_TARGET,
    SEVERITY,
    EVIDENCE_ROWS,
    HIGH_RISK_CHANGES,
    ROUTE_BLOCKED,
    CLOSURE_BLOCKED,
    REVIEW_READY,
    MISSING_TICKET_ROWS,
    IAC_GAP_ROWS,
    MISSING_QUERY_ID_ROWS,
    OPEN_ACTIONS,
    OVERDUE_OPEN,
    FIXED_WITHOUT_VERIFICATION,
    VERIFIED_CLOSURES,
    OWNER_APPROVAL_GAP_ROWS,
    CONTROL_STATE,
    CONTROL_RANK,
    NEXT_CONTROL_ACTION,
    LAST_ACTIVITY_TS,
    LOAD_TS
FROM {table}
WHERE {where_clause}
ORDER BY
    CONTROL_RANK,
    OVERDUE_OPEN DESC,
    FIXED_WITHOUT_VERIFICATION DESC,
    ROUTE_BLOCKED DESC,
    CLOSURE_BLOCKED DESC,
    HIGH_RISK_CHANGES DESC,
    LAST_ACTIVITY_TS DESC
LIMIT 100""".strip()


def _save_change_control_evidence_snapshot(
    session,
    readiness: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
) -> None:
    try:
        session.sql(build_change_control_evidence_ddl()).collect()
        for migration_sql in build_change_control_evidence_migration_sql():
            session.sql(migration_sql).collect()
        session.sql(_change_control_evidence_insert_sql(
            readiness,
            company=company,
            environment=environment,
            source=source,
        )).collect()
        st.success("Saved the Change Control Evidence snapshot for audit and trend tracking.")
    except Exception as exc:
        st.error(f"Could not save Change Control Evidence snapshot: {format_snowflake_error(exc)}")
        st.info("Deploy the change-control evidence table from `snowflake/OVERWATCH_MART_SETUP.sql`, then retry this save.")


def _render_change_source_health(company: str, environment: str) -> None:
    source_health = _change_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Change Source Health", expanded=False):
        current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        mart_backed = int(
            source_health[
                source_health["STATE"].isin(["Loaded", "No Rows"])
                & source_health["SOURCE"].astype(str).str.contains("mart|FACT_", case=False, regex=True)
            ].shape[0]
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current Surfaces", f"{current}/{len(source_health)}")
        c2.metric("Mart-Backed", f"{mart_backed:,}")
        c3.metric("Stale", f"{stale:,}", delta_color="inverse")
        c4.metric("Unavailable", f"{unavailable:,}", delta_color="inverse")
        st.caption(
            "Use this before acting on change findings. DDL/DCL detection is text-pattern based, "
            "and account/role-only events are intentionally retained when no database context exists."
        )
        render_priority_dataframe(
            source_health,
            title="Change evidence freshness and source quality",
            priority_columns=[
                "STATE", "SURFACE", "CONFIDENCE", "ROWS", "SCOPE", "SOURCE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All change source health rows",
            height=260,
        )


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    if st.session_state.get("exceptions_only_mode") and "change_drift_workflow" not in st.session_state:
        st.session_state["change_drift_workflow"] = "Object and access changes"
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="estimated",
        scope_note="DDL/change detection is query-history based; SHOW commands fill live metadata gaps.",
    )
    render_operator_briefing(
        [
            ("First move", "Identify who changed what and whether it was approved."),
            ("Evidence", "Preserve query ID, actor, object, timestamp, and dependency context."),
            ("Control", "Route drift to source control, owner review, or a guarded DBA action."),
            ("Output", "Build an audit-ready change narrative with blast-radius notes."),
        ],
        columns=4,
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: prioritize recent DDL, grant, owner, policy, replication, and task-control issues.")
    render_workflow_guide(
        "Confirm who changed what, trace stored procedure blast radius, then use DBA toolkit checks "
        "for drift, replication, dynamic tables, and controlled actions.",
        [
            ("DDL, grant, owner, or policy changed", "Use Object and access changes."),
            ("A stored procedure drove unexpected cost or changes", "Use Stored procedure lineage."),
            ("Schemas, objects, or unused assets may have drifted", "Use Schema and object drift."),
            ("Loads, pipes, dynamic tables, or replication are suspect", "Use Data movement and replication."),
            ("A query, task, warehouse, or setup action is required", "Use Controlled DBA actions."),
        ],
    )

    days = st.slider("Change brief lookback (days)", 1, 90, 14, key="change_drift_brief_days")
    _render_change_source_health(company, environment)
    if st.button("Load Change & Drift Brief", key="change_drift_brief_load", type="primary"):
        try:
            summary_sql, exceptions_sql = _build_mart_change_drift_sql(days, company)
            source_label = "OVERWATCH mart: FACT_OBJECT_CHANGE"
            st.session_state["change_drift_summary"] = run_query(
                summary_sql,
                ttl_key=f"change_drift_summary_mart_{company}_{environment}_{days}",
                tier="standard",
            )
            st.session_state["change_drift_exceptions"] = run_query(
                exceptions_sql,
                ttl_key=f"change_drift_exceptions_mart_{company}_{environment}_{days}",
                tier="standard",
            )
            st.session_state["change_drift_proof_sql"] = {
                "summary": summary_sql,
                "exceptions": exceptions_sql,
            }
            st.session_state["change_drift_source"] = source_label
            st.session_state["change_drift_meta"] = {
                **_change_scope_meta(company, environment, days),
                "source": source_label,
            }
            st.session_state.pop("change_drift_error", None)
        except Exception as exc:
            try:
                session = get_session()
                summary_sql, exceptions_sql = _build_change_drift_sql(session, days, company)
                source_label = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
                st.session_state["change_drift_summary"] = run_query(
                    summary_sql,
                    ttl_key=f"change_drift_summary_live_{company}_{environment}_{days}",
                    tier="standard",
                )
                st.session_state["change_drift_exceptions"] = run_query(
                    exceptions_sql,
                    ttl_key=f"change_drift_exceptions_live_{company}_{environment}_{days}",
                    tier="standard",
                )
                st.session_state["change_drift_proof_sql"] = {
                    "summary": summary_sql,
                    "exceptions": exceptions_sql,
                }
                st.session_state["change_drift_source"] = source_label
                st.session_state["change_drift_meta"] = {
                    **_change_scope_meta(company, environment, days),
                    "source": source_label,
                }
                st.session_state.pop("change_drift_error", None)
                st.info(f"Change mart unavailable; used live QUERY_HISTORY fallback. {format_snowflake_error(exc)}")
            except Exception as live_exc:
                st.session_state["change_drift_summary"] = pd.DataFrame()
                st.session_state["change_drift_exceptions"] = pd.DataFrame()
                st.session_state["change_drift_source"] = "Unavailable: change brief"
                st.session_state["change_drift_meta"] = _change_scope_meta(company, environment, days)
                st.session_state["change_drift_error"] = format_snowflake_error(live_exc)
                st.error(f"Unable to load change brief: {format_snowflake_error(live_exc)}")
        try:
            operability_sql = _change_control_operability_fact_sql(days, company, environment)
            st.session_state["change_control_operability_fact_sql"] = operability_sql
            st.session_state["change_control_operability_fact"] = run_query(
                operability_sql,
                ttl_key=f"change_control_operability_fact_{company}_{environment}_{days}",
                tier="standard",
                section="Change & Drift",
            )
            st.session_state["change_control_operability_fact_meta"] = _change_scope_meta(company, environment, days)
            st.session_state.pop("change_control_operability_fact_error", None)
        except Exception as fact_exc:
            st.session_state["change_control_operability_fact"] = pd.DataFrame()
            st.session_state["change_control_operability_fact_error"] = format_snowflake_error(fact_exc)

    summary = st.session_state.get("change_drift_summary")
    exceptions = st.session_state.get("change_drift_exceptions")
    meta = st.session_state.get("change_drift_meta", {})
    expected_brief_meta = _change_scope_meta(company, environment, days)
    brief_is_current = _change_meta_matches(meta, expected_brief_meta)
    if summary is not None and not summary.empty and not brief_is_current:
        st.info("Loaded Change & Drift brief is stale for the active scope. Reload the brief before acting.")
    if (
        summary is not None
        and not summary.empty
        and brief_is_current
    ):
        row = summary.iloc[0]
        score = _change_drift_score(
            object_changes=safe_int(row.get("OBJECT_CHANGES", 0)),
            access_changes=safe_int(row.get("ACCESS_CHANGES", 0)),
            policy_changes=safe_int(row.get("POLICY_CHANGES", 0)),
            owner_changes=safe_int(row.get("OWNER_CHANGES", 0)),
            destructive_changes=safe_int(row.get("DESTRUCTIVE_CHANGES", 0)),
            manual_drift=safe_int(row.get("MANUAL_DRIFT", 0)),
        )
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Change Control Score", score, _change_drift_rating(score))
        c2.metric("Object Changes", f"{safe_int(row.get('OBJECT_CHANGES', 0)):,}")
        c3.metric("Access Changes", f"{safe_int(row.get('ACCESS_CHANGES', 0)):,}")
        c4.metric("Policy/Owner", f"{safe_int(row.get('POLICY_CHANGES', 0)) + safe_int(row.get('OWNER_CHANGES', 0)):,}", delta_color="inverse")
        c5.metric("Manual Drift", f"{safe_int(row.get('MANUAL_DRIFT', 0)):,}", delta_color="inverse")
        if score < 85:
            st.warning("Change control needs DBA review; high-risk changes or drift indicators are present.")
        elif score < 95:
            st.info("Change control is usable, but there are changes worth validating.")
        else:
            st.success("Change control looks clean for the selected window.")
        st.caption(meta.get("source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))

        operability_fact = st.session_state.get("change_control_operability_fact")
        operability_fact_current = _change_meta_matches(
            st.session_state.get("change_control_operability_fact_meta"),
            expected_brief_meta,
        )
        if operability_fact is not None and not operability_fact.empty and operability_fact_current:
            st.subheader("Change Control Operability Mart")
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("Fact Rows", f"{len(operability_fact):,}")
            f2.metric("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}", delta_color="inverse")
            f3.metric(
                "Route / Closure Blocks",
                f"{int(operability_fact.get('ROUTE_BLOCKED', pd.Series(dtype=int)).sum() + operability_fact.get('CLOSURE_BLOCKED', pd.Series(dtype=int)).sum()):,}",
                delta_color="inverse",
            )
            f4.metric("Verified Closures", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}")
            render_priority_dataframe(
                operability_fact,
                title="Pre-aggregated change-control blockers",
                priority_columns=[
                    "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "ENVIRONMENT",
                    "FINDING_TYPE", "ENTITY", "OWNER", "SEVERITY", "HIGH_RISK_CHANGES",
                    "ROUTE_BLOCKED", "CLOSURE_BLOCKED", "MISSING_TICKET_ROWS",
                    "IAC_GAP_ROWS", "MISSING_QUERY_ID_ROWS", "OPEN_ACTIONS",
                    "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "VERIFIED_CLOSURES",
                    "NEXT_CONTROL_ACTION",
                ],
                sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "HIGH_RISK_CHANGES"],
                ascending=[True, False, False, False],
                raw_label="All change-control operability facts",
                height=300,
            )
            with st.expander("Operability fact query", expanded=False):
                st.code(st.session_state.get("change_control_operability_fact_sql", ""), language="sql")
        elif operability_fact is not None and not operability_fact.empty and not operability_fact_current:
            st.info("Loaded change-control operability facts are stale for the active scope. Reload the brief before acting.")
        elif st.session_state.get("change_control_operability_fact_error"):
            st.caption(
                "Change-control operability mart not available yet; deploy or refresh "
                "`FACT_CHANGE_CONTROL_OPERABILITY_DAILY` to enable the fast blocker surface."
            )

        _render_change_watch_floor(score, exceptions, row)
        st.divider()

        if exceptions is not None and not exceptions.empty:
            st.subheader("Change & Drift Exceptions")
            priority_exceptions = _change_priority_view(exceptions)
            render_priority_dataframe(
                priority_exceptions,
                title="Change and drift exceptions to verify first",
                priority_columns=[
                    "SEVERITY", "FINDING_TYPE", "ENTITY", "USER_NAME",
                    "ROLE_NAME", "DATABASE_NAME", "ENVIRONMENT", "SCOPE_CONFIDENCE",
                    "QUERY_ID", "LAST_SEEN", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["SEVERITY", "LAST_SEEN", "ENTITY"],
                ascending=[True, False, True],
                raw_label="All change and drift exceptions",
            )
            readiness = _build_change_control_readiness(exceptions)
            readiness_summary = _change_control_readiness_summary(readiness)
            closure_days_for_gate = safe_int(st.session_state.get("change_action_closure_days", 30)) or 30
            closure_for_gate = st.session_state.get("change_action_closure")
            if not _change_meta_matches(
                st.session_state.get("change_action_closure_meta"),
                _change_scope_meta(company, environment, closure_days_for_gate),
            ):
                closure_for_gate = pd.DataFrame()
            operator_moves = _change_operator_next_moves(
                score=score,
                exceptions=exceptions,
                readiness_summary=readiness_summary,
                readiness=readiness,
                closure=closure_for_gate,
                operability_fact=operability_fact if operability_fact_current else pd.DataFrame(),
            )
            render_priority_dataframe(
                operator_moves,
                title="Change operator next-move gates",
                priority_columns=["GATE", "STATE", "COUNT", "PROOF_REQUIRED", "NEXT_ACTION"],
                sort_by=["GATE_RANK", "COUNT"],
                ascending=[True, False],
                raw_label="All change operator gates",
                height=240,
                max_rows=6,
            )
            intervention_matrix = _change_intervention_matrix(
                exceptions,
                readiness=readiness,
                closure=closure_for_gate,
            )
            if not intervention_matrix.empty:
                render_priority_dataframe(
                    intervention_matrix,
                    title="Change DBA intervention matrix",
                    priority_columns=[
                        "DBA_PRIORITY", "INTERVENTION_STATE", "SEVERITY", "FINDING_TYPE", "ENTITY",
                        "USER_NAME", "ROLE_NAME", "QUERY_ID", "CONTROL_STATE",
                        "TICKET_STATE", "IAC_STATE", "CLOSURE_READINESS",
                        "NEXT_DECISION", "PROOF_REQUIRED", "NEXT_WORKFLOW",
                    ],
                    sort_by=["DBA_PRIORITY", "SEVERITY", "FINDING_TYPE"],
                    ascending=[True, True, True],
                    raw_label="All change DBA intervention rows",
                    height=300,
                    max_rows=10,
                )
            if not readiness_summary.empty:
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Change Routes", f"{len(readiness_summary):,}")
                r2.metric(
                    "Closure Blocked",
                    f"{int(readiness_summary['CLOSURE_BLOCKED'].sum()):,}",
                    delta_color="inverse",
                )
                r3.metric(
                    "Route Blocked",
                    f"{int(readiness_summary['ROUTE_BLOCKED'].sum()):,}",
                    delta_color="inverse",
                )
                r4.metric(
                    "Account Scope",
                    f"{int(readiness_summary['ACCOUNT_SCOPE_ROWS'].sum()):,}",
                )
                render_priority_dataframe(
                    readiness_summary,
                    title="Change-control blocker board",
                    priority_columns=[
                        "READINESS", "ENVIRONMENT", "FINDING_TYPE", "OWNER", "APPROVER",
                        "TOTAL_CHANGES", "HIGH_RISK_CHANGES", "ROUTE_BLOCKED",
                        "CLOSURE_BLOCKED", "REVIEW_READY", "MISSING_TICKET_ROWS",
                        "IAC_GAP_ROWS", "MISSING_QUERY_ID_ROWS", "ACCOUNT_SCOPE_ROWS",
                        "REVIEW_SLA_HOURS", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["READINESS_RANK", "HIGH_RISK_CHANGES", "MISSING_TICKET_ROWS", "IAC_GAP_ROWS"],
                    ascending=[True, False, False, False],
                    raw_label="All change-control blocker routes",
                    height=260,
                )
            render_priority_dataframe(
                readiness,
                title="Change-control readiness before queueing",
                priority_columns=[
                    "SEVERITY", "CHANGE_CONTROL_STATE", "FINDING_TYPE", "ENTITY",
                    "USER_NAME", "QUERY_ID", "APPROVER", "OWNER_APPROVAL_STATUS",
                    "OWNER", "ESCALATION_TARGET", "DATABASE_CONTEXT", "DATABASE_NAME",
                    "ENVIRONMENT", "SCOPE_CONFIDENCE", "CHANGE_TICKET_ID", "CHANGE_TICKET_STATE",
                    "IAC_RECONCILIATION_STATE", "EXECUTION_AUDIT_STATE", "APPROVAL_ROUTE_READY",
                    "CHANGE_EVIDENCE_READINESS", "EVIDENCE_BLOCKERS", "REVIEW_SLA_HOURS",
                    "CONTROL_GAP", "NEXT_CONTROL_ACTION", "PROOF_REQUIRED",
                ],
                sort_by=["SEVERITY", "CHANGE_CONTROL_STATE", "ENTITY"],
                ascending=[True, True, True],
                raw_label="All change-control readiness rows",
                height=260,
            )
            save_col, setup_col = st.columns([1, 2])
            with save_col:
                if st.button("Save Change Evidence Snapshot", key="change_drift_evidence_snapshot", width="stretch"):
                    _save_change_control_evidence_snapshot(
                        get_session(),
                        readiness,
                        company=company,
                        environment=environment,
                        source=meta.get("source", ""),
                    )
            with setup_col:
                st.caption(
                    "Snapshot stores ticket, IaC, owner, approver, query-id, and blast-radius requirements for audit trend review."
                )
            with st.expander("Change Control Evidence Trend", expanded=False):
                trend_days = st.slider("Change evidence trend days", 7, 180, 30, key="change_drift_evidence_trend_days")
                if st.button("Load Change Evidence Trend", key="change_drift_evidence_trend_load"):
                    try:
                        trend_sql = _change_control_evidence_history_sql(trend_days, company, environment)
                        trend = run_query(
                            trend_sql,
                            ttl_key=f"change_drift_evidence_trend_{company}_{environment}_{trend_days}",
                            tier="standard",
                            section="Change & Drift",
                        )
                        st.session_state["change_drift_evidence_trend"] = trend
                        st.session_state["change_drift_evidence_trend_sql"] = trend_sql
                        st.session_state["change_drift_evidence_trend_meta"] = _change_scope_meta(
                            company, environment, trend_days
                        )
                        st.session_state.pop("change_drift_evidence_trend_error", None)
                    except Exception as exc:
                        st.session_state["change_drift_evidence_trend"] = pd.DataFrame()
                        st.session_state["change_drift_evidence_trend_error"] = format_snowflake_error(exc)
                        st.error(f"Unable to load change-control evidence trend: {format_snowflake_error(exc)}")
                trend = st.session_state.get("change_drift_evidence_trend")
                trend_current = _change_meta_matches(
                    st.session_state.get("change_drift_evidence_trend_meta"),
                    _change_scope_meta(company, environment, trend_days),
                )
                if trend is not None and not trend.empty and trend_current:
                    render_priority_dataframe(
                        trend,
                        title="Persistent change-control evidence gaps",
                        priority_columns=[
                            "FINDING_TYPE", "SEVERITY", "OWNER", "ESCALATION_TARGET",
                            "EVIDENCE_ROWS", "MISSING_TICKET_ROWS", "IAC_GAP_ROWS",
                            "MISSING_QUERY_ID_ROWS", "LAST_CONTROL_STATE", "LAST_CONTROL_GAP",
                        ],
                        sort_by=["MISSING_TICKET_ROWS", "IAC_GAP_ROWS", "LAST_SNAPSHOT_TS"],
                        ascending=[False, False, False],
                        raw_label="All persisted change-control evidence",
                        height=260,
                    )
                elif (
                    trend is not None
                    and not trend_current
                    and not st.session_state.get("change_drift_evidence_trend_error")
                ):
                    st.info("Loaded change-control evidence trend is stale for the active scope. Reload the trend before acting.")
                with st.expander("Change-control evidence setup SQL", expanded=False):
                    st.code(build_change_control_evidence_ddl(), language="sql")
            with st.expander("Change Action Closure Analytics", expanded=False):
                st.caption(
                    "Uses Change & Drift action-queue rows to show open, overdue, unapproved, "
                    "or closed-without-verification change-control work."
                )
                closure_days = st.slider("Change closure days", 7, 180, 30, key="change_action_closure_days")
                if st.button("Load Change Closure Analytics", key="change_action_closure_load"):
                    try:
                        closure_sql = _change_action_queue_closure_sql(closure_days, company, environment)
                        closure = run_query(
                            closure_sql,
                            ttl_key=f"change_action_closure_{company}_{environment}_{closure_days}",
                            tier="standard",
                            section="Change & Drift",
                        )
                        st.session_state["change_action_closure"] = closure
                        st.session_state["change_action_closure_sql"] = closure_sql
                        st.session_state["change_action_closure_meta"] = _change_scope_meta(
                            company, environment, closure_days
                        )
                        st.session_state.pop("change_action_closure_error", None)
                    except Exception as exc:
                        st.session_state["change_action_closure"] = pd.DataFrame()
                        st.session_state["change_action_closure_error"] = format_snowflake_error(exc)
                        st.warning(f"Change closure analytics unavailable: {format_snowflake_error(exc)}")
                closure = st.session_state.get("change_action_closure")
                closure_current = _change_meta_matches(
                    st.session_state.get("change_action_closure_meta"),
                    _change_scope_meta(company, environment, closure_days),
                )
                if closure is not None and not closure.empty and closure_current:
                    render_priority_dataframe(
                        closure,
                        title="Change closure evidence gaps",
                        priority_columns=[
                            "CATEGORY", "ENTITY_TYPE", "ENTITY", "CLOSURE_READINESS",
                            "OWNER", "APPROVER", "TOTAL_ACTIONS", "OPEN_ACTIONS",
                            "OVERDUE_OPEN", "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                            "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                            "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                            "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                        ],
                        sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                        ascending=[True, False, False, False],
                        raw_label="All change closure rows",
                        height=300,
                    )
                    with st.expander("Change Closure Query", expanded=False):
                        st.code(st.session_state.get("change_action_closure_sql", ""), language="sql")
                elif (
                    closure is not None
                    and not closure_current
                    and not st.session_state.get("change_action_closure_error")
                ):
                    st.info("Loaded change closure analytics are stale for the active scope. Reload closure analytics before acting.")
                elif closure is not None and closure_current:
                    st.info("No Change & Drift action-queue rows found for the selected scope.")
            if st.button("Save Change Exceptions to Action Queue", key="change_drift_queue"):
                _queue_change_exceptions(get_session(), exceptions)
        elif exceptions is not None:
            st.success("No change/drift exceptions crossed the default thresholds.")
        brief_md = _build_change_drift_markdown(
            company=company,
            days=days,
            score=score,
            summary_row=row,
            exceptions=exceptions,
        )
        dl1, dl2 = st.columns([1, 3])
        with dl1:
            st.download_button(
                "Download Change Brief",
                brief_md,
                file_name=f"overwatch_change_drift_brief_{company.lower()}.md",
                mime="text/markdown",
                key="change_drift_download",
            )
        with dl2:
            with st.expander("Proof SQL", expanded=False):
                proof_sql = st.session_state.get("change_drift_proof_sql", {})
                st.caption("Use these source queries to defend change counts and exception rows.")
                st.code(proof_sql.get("summary", "-- Load the change brief first."), language="sql")
                st.code(proof_sql.get("exceptions", "-- Load the change brief first."), language="sql")
        if st.session_state.get("exceptions_only_mode"):
            st.stop()

    workflow = render_workflow_selector(
        "Change workflow",
        "change_drift_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
        columns=5,
    )

    if workflow == "Object and access changes":
        render_workflow_module(workflow, WORKFLOW_MODULES)
    elif workflow == "Stored procedure lineage":
        render_workflow_module(workflow, WORKFLOW_MODULES)
    elif workflow == "Schema and object drift":
        st.session_state["dba_tools_focus"] = "Governance"
        st.info("Focused toolkit: schema compare, recent objects, unused objects, object inventory, and drift checks.")
        render_workflow_module(workflow, WORKFLOW_MODULES)
    elif workflow == "Data movement and replication":
        st.session_state["dba_tools_focus"] = "Data Movement"
        st.info("Focused toolkit: data loading, Snowpipe, dynamic tables, and replication checks.")
        render_workflow_module(workflow, WORKFLOW_MODULES)
    else:
        st.session_state["dba_tools_focus"] = "Controlled Actions"
        st.info("Focused toolkit: query cancellation, warehouse settings, task graph control, setup, and audit evidence.")
        render_workflow_module(workflow, WORKFLOW_MODULES)
