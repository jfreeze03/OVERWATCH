# sections/change_drift.py - Consolidated change, drift, and lineage workflow
from __future__ import annotations

from datetime import datetime
import re

import pandas as pd
import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA
from sections import dba_tools, object_change_monitor, stored_proc_tracker
from utils import (
    filter_existing_columns,
    format_snowflake_error,
    get_active_company,
    get_active_environment,
    get_global_filter_clause,
    get_session,
    mart_object_name,
    make_action_id,
    run_query,
    safe_identifier,
    safe_float,
    safe_int,
    sql_literal,
    upsert_actions,
)
from utils.workflows import (
    render_operator_briefing,
    render_priority_dataframe,
    render_signal_confidence,
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

CHANGE_CONTROL_EVIDENCE_TABLE = "OVERWATCH_CHANGE_CONTROL_EVIDENCE"
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
    PROOF_REQUIRED           VARCHAR(2000),
    VERIFICATION_QUERY       VARCHAR(8000),
    BLAST_RADIUS_QUERY       VARCHAR(8000),
    SOURCE                   VARCHAR(500)
);"""


def _change_ticket_id(row: pd.Series | dict) -> str:
    haystack = " ".join([
        str(row.get("QUERY_TAG") or ""),
        str(row.get("QUERY_TEXT") or ""),
        str(row.get("PROOF_QUERY") or ""),
    ])
    match = CHANGE_TICKET_PATTERN.search(haystack)
    return match.group(0).upper() if match else ""


def _change_owner_context(row: pd.Series | dict) -> dict:
    finding = str(row.get("FINDING_TYPE") or "").lower()
    entity = str(row.get("ENTITY") or "").upper()
    if "policy" in finding or "tag" in finding or "masking" in finding:
        return {
            "owner": "Security / Data Governance",
            "escalation": "Security Owner / Data Governance Lead",
            "source": "Change owner map",
        }
    if "grant" in finding or "role" in finding or "owner" in finding:
        return {
            "owner": "Security Owner",
            "escalation": "DBA Lead / Security Owner",
            "source": "Change owner map",
        }
    if "drop" in finding or "destructive" in finding:
        return {
            "owner": "DBA Change Owner",
            "escalation": "Data Owner / DBA Lead",
            "source": "Change owner map",
        }
    if "drift" in finding:
        return {
            "owner": "Platform Owner",
            "escalation": "DBA Lead / Platform Owner",
            "source": "Change owner map",
        }
    if entity.startswith("ALFA_EDW_PROD"):
        return {
            "owner": "Production Data Owner",
            "escalation": "DBA Lead",
            "source": "Environment owner hint",
        }
    if entity.startswith("ALFA_EDW_"):
        return {
            "owner": "Development Data Owner",
            "escalation": "DBA Lead",
            "source": "Environment owner hint",
        }
    return {
        "owner": "DBA Change Owner",
        "escalation": "DBA Lead",
        "source": "Default change owner",
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


def _enrich_change_control_evidence(readiness: pd.DataFrame) -> pd.DataFrame:
    if readiness is None or readiness.empty:
        return readiness
    view = readiness.copy()
    contexts = view.apply(_change_owner_context, axis=1)
    view["OWNER"] = contexts.apply(lambda item: item["owner"])
    view["ESCALATION_TARGET"] = contexts.apply(lambda item: item["escalation"])
    view["OWNER_SOURCE"] = contexts.apply(lambda item: item["source"])
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
    return view


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
    raw = str(entity or "").strip().strip('"')
    pieces = [piece.strip().strip('"') for piece in raw.split(".") if piece.strip()]
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
        "Company": company,
        "Environment": environment,
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
            if st.button(f"Open {workflow}", key=f"change_watch_floor_{idx}_{workflow}", use_container_width=True):
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
    scope = get_global_filter_clause(
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
        COUNT(DISTINCT database_name) AS affected_databases
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
    scope = get_global_filter_clause(
        date_col="start_time",
        wh_col="warehouse_name",
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
        COUNT(DISTINCT database_name) AS affected_databases
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
        selects.append(
            "SELECT "
            f"{sql_literal(snap, 64)} AS SNAPSHOT_ID, "
            "CURRENT_TIMESTAMP() AS SNAPSHOT_TS, "
            f"{sql_literal(company, 100)} AS COMPANY, "
            f"{sql_literal(env_value, 100)} AS ENVIRONMENT, "
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
    TICKET_REQUIRED, BLAST_RADIUS_REQUIRED, PROOF_REQUIRED, VERIFICATION_QUERY,
    BLAST_RADIUS_QUERY, SOURCE
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


def render() -> None:
    session = get_session()
    company = get_active_company()
    environment = get_active_environment()
    if st.session_state.get("exceptions_only_mode") and "change_drift_workflow" not in st.session_state:
        st.session_state["change_drift_workflow"] = "Object and access changes"
    st.header("Change & Drift")
    st.caption(
        "One workflow for who-changed-what investigations, stored procedure lineage, "
        "schema/object drift, dynamic tables, replication, and controlled DBA maintenance."
    )
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
    if st.button("Load Change & Drift Brief", key="change_drift_brief_load", type="primary"):
        try:
            summary_sql, exceptions_sql = _build_mart_change_drift_sql(days, company)
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
            st.session_state["change_drift_meta"] = {
                "company": company,
                "environment": environment,
                "days": days,
                "source": "OVERWATCH mart: FACT_OBJECT_CHANGE",
            }
        except Exception as exc:
            try:
                summary_sql, exceptions_sql = _build_change_drift_sql(session, days, company)
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
                st.session_state["change_drift_meta"] = {
                    "company": company,
                    "environment": environment,
                    "days": days,
                    "source": "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
                }
                st.info(f"Change mart unavailable; used live QUERY_HISTORY fallback. {format_snowflake_error(exc)}")
            except Exception as live_exc:
                st.session_state["change_drift_summary"] = pd.DataFrame()
                st.session_state["change_drift_exceptions"] = pd.DataFrame()
                st.error(f"Unable to load change brief: {format_snowflake_error(live_exc)}")

    summary = st.session_state.get("change_drift_summary")
    exceptions = st.session_state.get("change_drift_exceptions")
    meta = st.session_state.get("change_drift_meta", {})
    if (
        summary is not None
        and not summary.empty
        and meta.get("company") == company
        and meta.get("environment") == environment
        and meta.get("days") == days
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
                    "ROLE_NAME", "QUERY_ID", "LAST_SEEN", "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["SEVERITY", "LAST_SEEN", "ENTITY"],
                ascending=[True, False, True],
                raw_label="All change and drift exceptions",
            )
            readiness = _build_change_control_readiness(exceptions)
            render_priority_dataframe(
                readiness,
                title="Change-control readiness before queueing",
                priority_columns=[
                    "SEVERITY", "CHANGE_CONTROL_STATE", "FINDING_TYPE", "ENTITY",
                    "USER_NAME", "QUERY_ID", "APPROVER", "OWNER_APPROVAL_STATUS",
                    "OWNER", "ESCALATION_TARGET", "CHANGE_TICKET_ID", "CHANGE_TICKET_STATE",
                    "IAC_RECONCILIATION_STATE", "EXECUTION_AUDIT_STATE", "CONTROL_GAP", "PROOF_REQUIRED",
                ],
                sort_by=["SEVERITY", "CHANGE_CONTROL_STATE", "ENTITY"],
                ascending=[True, True, True],
                raw_label="All change-control readiness rows",
                height=260,
            )
            save_col, setup_col = st.columns([1, 2])
            with save_col:
                if st.button("Save Change Evidence Snapshot", key="change_drift_evidence_snapshot", use_container_width=True):
                    _save_change_control_evidence_snapshot(
                        session,
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
                    except Exception as exc:
                        st.error(f"Unable to load change-control evidence trend: {format_snowflake_error(exc)}")
                trend = st.session_state.get("change_drift_evidence_trend")
                if trend is not None and not trend.empty:
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
                with st.expander("Change-control evidence setup SQL", expanded=False):
                    st.code(build_change_control_evidence_ddl(), language="sql")
            if st.button("Save Change Exceptions to Action Queue", key="change_drift_queue"):
                _queue_change_exceptions(session, exceptions)
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
    )

    if workflow == "Object and access changes":
        object_change_monitor.render()
    elif workflow == "Stored procedure lineage":
        stored_proc_tracker.render()
    elif workflow == "Schema and object drift":
        st.session_state["dba_tools_focus"] = "Governance"
        st.info("Focused toolkit: schema compare, recent objects, unused objects, object inventory, and drift checks.")
        dba_tools.render()
    elif workflow == "Data movement and replication":
        st.session_state["dba_tools_focus"] = "Data Movement"
        st.info("Focused toolkit: data loading, Snowpipe, dynamic tables, and replication checks.")
        dba_tools.render()
    else:
        st.session_state["dba_tools_focus"] = "Controlled Actions"
        st.info("Focused toolkit: query cancellation, warehouse settings, task graph control, setup, and audit evidence.")
        dba_tools.render()
