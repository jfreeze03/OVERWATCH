# sections/change_drift_models.py - Change Drift dataframe and readiness models
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.change_drift_contracts import (
    CHANGE_BRIEF_WORKFLOWS,
    CHANGE_SCOPE_FILTER_KEYS,
    CHANGE_TICKET_PATTERN,
    WORKFLOW_DETAILS,
)
from utils.primitives import safe_float, safe_int

pd = lazy_pandas()
environment_label_for_database = _lazy_util("environment_label_for_database")
resolve_owner_context = _lazy_util("resolve_owner_context")
sql_literal = _lazy_util("sql_literal")

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
    """Return the filter scope that loaded Change & Drift telemetry must match."""
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

def _change_looks_like_frame(value) -> bool:
    """Return True for dataframe-like values without forcing pandas import."""
    return hasattr(value, "empty") and hasattr(value, "iloc") and hasattr(value, "columns")

def _change_row_count(frame) -> int:
    return len(frame) if isinstance(frame, pd.DataFrame) else 0

def _change_source_confidence(source: str, default: str) -> str:
    source_lower = str(source or "").lower()
    if ("fast" in source_lower and "summary" in source_lower) or "mart" in source_lower or "fact_" in source_lower:
        return "Fast summary"
    if "fallback" in source_lower:
        return "Live fallback"
    if "account_usage" in source_lower:
        return "Live ACCOUNT_USAGE"
    if "action queue" in source_lower or "workflow" in source_lower or "evidence" in source_lower:
        return "Workflow telemetry"
    return default

def _change_source_next_action(state: str, source: str) -> str:
    source_lower = str(source or "").lower()
    if state == "Stale":
        return "Reload after changing company, environment, lookback, or triage filters."
    if state == "Unavailable":
        return "Deploy or refresh the summary/telemetry tables before relying on this surface."
    if state == "On demand":
        return "Refresh only when this workflow is part of the current change investigation."
    if state == "No Rows":
        return "Confirm the selected scope has recent change events, telemetry, or action rows."
    if "fallback" in source_lower:
        return "Use for investigation; prefer summary refresh for repeated object-change review."
    return "Current for the active DBA change scope."

def _change_has_source_state(state: dict) -> bool:
    """Return True once Change & Drift has telemetry or source errors to summarize."""
    for key in (
        "change_drift_summary",
        "change_drift_exceptions",
        "change_drift_error",
        "change_control_operability_fact",
        "change_control_operability_fact_error",
        "change_drift_evidence_trend",
        "change_drift_evidence_trend_error",
        "change_action_closure",
        "change_action_closure_error",
        "change_integration_deployment_status",
        "change_integration_deployment_error",
        "change_integration_owner_approval_status",
        "change_integration_owner_approval_error",
    ):
        value = state.get(key)
        if isinstance(value, str):
            if value.strip():
                return True
            continue
        if value is not None:
            return True
    return False

def _change_source_health_rows(
    state: dict,
    company: str,
    environment: str,
) -> pd.DataFrame:
    """Summarize Change & Drift telemetry freshness and source strategy."""
    definitions = [
        {
            "surface": "Change brief",
            "frame_key": "change_drift_summary",
            "source_key": "change_drift_source",
            "meta_key": "change_drift_meta",
            "days_key": "change_drift_brief_days",
            "default_days": 14,
            "source": "Fast change summary or live query history",
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
            "source": "Fast change summary or live query history",
            "confidence": "Mixed",
            "error_key": "change_drift_error",
        },
        {
            "surface": "Control summary",
            "frame_key": "change_control_operability_fact",
            "meta_key": "change_control_operability_fact_meta",
            "days_key": "change_drift_brief_days",
            "default_days": 14,
            "source": "Fast object-change summary",
            "confidence": "Fast summary",
            "error_key": "change_control_operability_fact_error",
        },
        {
            "surface": "Telemetry trend",
            "frame_key": "change_drift_evidence_trend",
            "meta_key": "change_drift_evidence_trend_meta",
            "days_key": "change_drift_evidence_trend_days",
            "default_days": 30,
            "source": "Workflow telemetry",
            "confidence": "Workflow telemetry",
            "error_key": "change_drift_evidence_trend_error",
        },
        {
            "surface": "Closure analytics",
            "frame_key": "change_action_closure",
            "meta_key": "change_action_closure_meta",
            "days_key": "change_action_closure_days",
            "default_days": 30,
            "source": "Action queue closure telemetry",
            "confidence": "Workflow telemetry",
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
            status = "On demand"
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
                "On demand": 4,
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
            "owner": "Security / Data Stewardship",
            "escalation": "Security / Data Stewardship Route",
            "source": "Change route map",
        }
    elif "grant" in finding or "role" in finding or "owner" in finding:
        base = {
            "owner": "Security Route",
            "escalation": "DBA Lead / Security Route",
            "source": "Change route map",
        }
    elif "drop" in finding or "destructive" in finding:
        base = {
            "owner": "DBA Change Route",
            "escalation": "Data Route / DBA Lead",
            "source": "Change route map",
        }
    elif "drift" in finding:
        base = {
            "owner": "Platform Route",
            "escalation": "DBA Lead / Platform Route",
            "source": "Change route map",
        }
    elif environment_label == "PROD":
        base = {
            "owner": "Production Data Route",
            "escalation": "DBA Lead",
            "source": "Environment route hint",
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
            "owner": "Development Data Route",
            "escalation": "DBA Lead",
            "source": "Environment route hint",
        }
    else:
        base = {
            "owner": "DBA Change Route",
            "escalation": "DBA Lead",
            "source": "Default change route",
        }
    directory_context = resolve_owner_context(
        row,
        entity=entity,
        entity_type="CHANGE_CONTROL",
        owner=base["owner"],
        category=finding or "Object Change Monitoring",
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
    if any(token in query_tag for token in ("approved", "rollback", "release")):
        return "Review status tagged"
    if "drift" in finding:
        return "Reconcile review status"
    severity = str(row.get("SEVERITY") or "").upper()
    if severity in {"CRITICAL", "HIGH"}:
        return "Untracked change - rollback status required"
    return "Review telemetry state"

def _change_execution_audit_state(row: pd.Series | dict) -> str:
    query_id = str(row.get("QUERY_ID") or "").strip()
    last_seen = str(row.get("LAST_SEEN") or "").strip()
    if query_id and last_seen:
        return "Query ID and timestamp captured"
    if query_id:
        return "Query ID captured"
    return "Missing query_id telemetry"

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
    approver = str(row.get("APPROVER") or row.get("APPROVAL_GROUP") or "").strip()
    severity = str(row.get("SEVERITY") or "").upper()
    ticket_state = str(row.get("CHANGE_TICKET_STATE") or "")
    iac_state = str(row.get("IAC_RECONCILIATION_STATE") or "")
    execution_state = str(row.get("EXECUTION_AUDIT_STATE") or "")
    approval_required = str(row.get("APPROVAL_REQUIRED") or "Yes").upper() == "YES" or severity in {"CRITICAL", "HIGH", "MEDIUM"}

    blockers = []
    generic_owners = {"", "DBA", "UNKNOWN", "N/A", "DBA CHANGE OWNER", "SECURITY OWNER"}
    owner_route_ready = bool(owner) and owner.upper() not in generic_owners
    if not owner_route_ready:
        blockers.append("escalation route")
    if approval_required and not approver:
        blockers.append("approver")
    if ticket_state.lower().startswith("missing"):
        blockers.append("change ticket")
    if "required" in iac_state.lower() or "reconcile" in iac_state.lower():
        blockers.append("review/rollback status")
    if execution_state.lower().startswith("missing"):
        blockers.append("query_id telemetry")

    route_blockers = {"escalation route", "approver"}
    closure_blockers = [item for item in blockers if item not in route_blockers]
    if any(item in route_blockers for item in blockers):
        readiness = "Route Blocked"
    elif closure_blockers:
        readiness = "Closure Blocked"
    else:
        readiness = "Review Ready"

    if "change ticket" in blockers:
        next_action = "Record the ticket or mark the row as unauthorized drift before closure."
    elif "review/rollback status" in blockers:
        next_action = "Record review notes, rollback status, or revert through the reviewed change path."
    elif "query_id telemetry" in blockers:
        next_action = "Capture the Snowflake query_id and timestamp before accepting the change."
    elif readiness == "Route Blocked":
        next_action = "Record an escalation route and reviewer before queueing or closing the change."
    else:
        next_action = "Review blast radius, retain review status, and close only after telemetry status is present."

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
        lambda value: "Ticket detected" if str(value or "").strip() else "Missing ticket status"
    )
    view["IAC_RECONCILIATION_STATE"] = view.apply(_change_iac_state, axis=1)
    view["EXECUTION_AUDIT_STATE"] = view.apply(_change_execution_audit_state, axis=1)

    missing_ticket = view["CHANGE_TICKET_ID"].fillna("").astype(str).str.strip().eq("")
    missing_iac = view["IAC_RECONCILIATION_STATE"].fillna("").astype(str).str.contains("required|reconcile", case=False, na=False)
    missing_query = view["EXECUTION_AUDIT_STATE"].fillna("").astype(str).str.contains("missing", case=False, na=False)
    view.loc[missing_ticket, "CONTROL_GAP"] = "Missing change ticket status"
    view.loc[missing_iac, "CONTROL_GAP"] = "Missing review or rollback status"
    view.loc[missing_query, "CONTROL_GAP"] = "Missing query_id telemetry"
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
    """Summarize object-change blockers by environment, finding, and escalation route."""
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
            next_action = "Complete named route and reviewer status before accepting change telemetry."
            readiness_label = "Route Blocked"
            rank = 0
        elif closure_blocked:
            next_action = "Record missing ticket, query, review, or rollback status before closure."
            readiness_label = "Closure Blocked"
            rank = 1
        elif ready:
            next_action = "Review blast radius and close only after telemetry status is retained."
            readiness_label = "Review Ready"
            rank = 8
        else:
            next_action = "Review object-change metadata."
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
    """Build a no-query decision gate for loaded change and drift telemetry."""
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
        next_action = "Assign named routes and reviewers before accepting or queueing the change."
        count = route_blocked
    elif exception_count:
        state = "Route Ready"
        rank = 6
        next_action = "Use the readiness rows to confirm route and reviewer status before closure."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "No change route needs escalation in the loaded scope."
        count = 0
    rows.append({
        "GATE": "Review route",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "named route, reviewer, review group, route basis",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if evidence_gaps:
        state = "Telemetry Blocked"
        rank = 1
        next_action = "Record ticket, review note, rollback status, query_id, and blast-radius context before closure."
        count = evidence_gaps
    elif exception_count:
        state = "Review Ready"
        rank = 6
        next_action = "Save the telemetry snapshot, then queue only confirmed exceptions that still need DBA action."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "No ticket, rollback, review, or query telemetry gap crossed the current thresholds."
        count = 0
    rows.append({
        "GATE": "Change status",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "change ticket, query_id, review note, rollback status, blast-radius context",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if closure_proof_blocks:
        state = "Closure Blocked"
        rank = 2
        next_action = "Reopen or hold change actions until telemetry and recovery status are present."
        count = closure_proof_blocks
    elif exception_count and close.empty:
        state = "Load Closure Analytics"
        rank = 4
        next_action = "Load closure analytics before claiming drift or object-change work is complete."
        count = exception_count
    else:
        state = "Clear"
        rank = 8
        next_action = "Retain closure telemetry for audit review."
        count = _change_frame_sum(close, "VERIFIED_CLOSURES") + _change_frame_sum(fact, "VERIFIED_CLOSURES")
    rows.append({
        "GATE": "Closure status",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "telemetry result, recovery status, ticket closure",
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
        next_action = "Use the selected environment/database telemetry for scoped change review."
        count = 0
    rows.append({
        "GATE": "Scope confidence",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "database context where present; explicit account-level review where database context is absent",
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
        state = "Recovery Status Required"
        rank = 3
        next_action = "Record restore, rollback, downstream dependency, and telemetry status before accepting this change."
        count = max(recovery_risk, recovery_sensitive)
    else:
        state = "Clear"
        rank = 8
        next_action = "No destructive, ownership, or policy/tag change currently requires extra recovery status."
        count = 0
    rows.append({
        "GATE": "Recovery readiness",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "restore path, rollback plan, dependency impact, telemetry status, post-change status",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if high_risk or safe_float(score) < 95:
        state = "Review Required" if high_risk else "Watch"
        rank = 5
        next_action = "Work high-risk destructive, policy, owner, role, and untracked drift rows before routine changes."
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
            "Confirm downstream dependencies, backup/recovery posture, and whether the object should be restored.",
            "Telemetry: query history destructive change query ID and query text.",
        )
    if "policy" in value or "tag" in value or "masking" in value:
        return (
            "Policy/Tag",
            "Validate policy owner, classification impact, and whether masking/tag changes match security review.",
            "Telemetry: query history masking/tag/row-access policy change.",
        )
    if "grant" in value or "role" in value or "owner" in value:
        return (
            "Grant/Role",
            "Confirm requester, approver, role hierarchy, and ownership transfer before accepting the access change.",
            "Telemetry: query history grant/revoke/ownership change.",
        )
    if "drift" in value:
        return (
            "Drift",
            "Compare the query with source telemetry; either retain status and rollback context or revert through the reviewed recovery path.",
            "Telemetry: query history change text, query tag, status, and rollback path.",
        )
    return (
        "Object",
        "Review change for dependency impact, access impact, and drift risk.",
        "-- Telemetry: QUERY_HISTORY change statement.",
    )

def _owner_approval_for(finding_type: str) -> tuple[str, str, str]:
    value = str(finding_type or "").lower()
    if "drop" in value or "destructive" in value:
        return (
            "Requested",
            "DBA Lead / Data Route",
            "Destructive object changes require data status, dependency review, and recovery telemetry.",
        )
    if "policy" in value or "tag" in value or "masking" in value:
        return (
            "Requested",
            "Security / Data Stewardship Route",
            "Policy, tag, masking, and row-access changes require security review.",
        )
    if "grant" in value or "role" in value or "owner" in value:
        return (
            "Requested",
            "Security Route",
            "Grant, revoke, role, and ownership changes require access-request review status.",
        )
    if "drift" in value:
        return (
            "Requested",
            "DBA Lead / Platform Route",
            "Untracked drift must be tied to telemetry status and rollback context, or reverted through the reviewed recovery path.",
        )
    return (
        "Requested",
        "Data Route",
        "Object changes require requester, reviewer, and change-ticket status before closure.",
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
    """Build read-only object dependency telemetry for a changed object or schema."""
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
    """Add ticket, review, and telemetry requirements before queueing changes."""
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    view = _change_priority_view(exceptions).copy()
    approval_rows = view.get("FINDING_TYPE", pd.Series(dtype=str)).apply(_owner_approval_for)
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

    view["CONTROL_GAP"] = "Needs reviewer, change ticket, and blast-radius note"
    view.loc[query_missing, "CONTROL_GAP"] = "Missing query_id telemetry"
    view["CHANGE_CONTROL_STATE"] = "Validate Review"
    view.loc[finding.str.contains("drift", na=False), "CHANGE_CONTROL_STATE"] = "Reconcile review status"
    view.loc[high_risk, "CHANGE_CONTROL_STATE"] = "Review Required"
    view.loc[query_missing, "CHANGE_CONTROL_STATE"] = "Telemetry Missing"
    return _enrich_change_control_evidence(view)

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
            decision = "Block closure until restore path, dependency blast radius, telemetry status, and rollback path exist."
        elif missing_query or missing_ticket or iac_gap or closure_bad:
            state = "Telemetry Block"
            rank = 1
            decision = "Record query_id, ticket, review, rollback, and telemetry status before accepting the change."
        elif severity.upper() in {"CRITICAL", "HIGH"}:
            state = "Review Now"
            rank = 2
            decision = "Review actor, role, blast radius, and escalation path before queueing the action."
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
            "PROOF_REQUIRED": "query_id, change ticket, release-note/rollback note, blast-radius context, telemetry status",
            "NEXT_WORKFLOW": str(item.get("NEXT_WORKFLOW") or _change_workflow_for(item)),
            "_RANK": rank,
        })

    return pd.DataFrame(rows).sort_values(
        ["_RANK", "SEVERITY", "FINDING_TYPE", "ENTITY"],
        ascending=[True, True, True, True],
    ).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)

def _change_action_brief(summary, exceptions, meta: dict, company: str, environment: str, days: int) -> dict:
    expected_meta = _change_scope_meta(company, environment, days)
    loaded = (
        _change_looks_like_frame(summary)
        and not summary.empty
        and _change_meta_matches(meta, expected_meta)
    )
    if not loaded:
        if _change_looks_like_frame(summary) and not summary.empty:
            return {
                "state": "Stale",
                "headline": "Reload the change brief before acting.",
                "detail": "Loaded change telemetry does not match the active company, environment, filters, or lookback.",
            }
        return {
            "state": "Ready",
            "headline": "Load recent object, grant, owner, policy, and drift telemetry.",
            "detail": "No Snowflake change telemetry loads until you request the selected scope.",
        }

    row = summary.iloc[0]
    object_changes = safe_int(row.get("OBJECT_CHANGES", 0))
    access_changes = safe_int(row.get("ACCESS_CHANGES", 0))
    policy_changes = safe_int(row.get("POLICY_CHANGES", 0))
    owner_changes = safe_int(row.get("OWNER_CHANGES", 0))
    destructive_changes = safe_int(row.get("DESTRUCTIVE_CHANGES", 0))
    manual_drift = safe_int(row.get("MANUAL_DRIFT", 0))
    score = _change_drift_score(
        object_changes=object_changes,
        access_changes=access_changes,
        policy_changes=policy_changes,
        owner_changes=owner_changes,
        destructive_changes=destructive_changes,
        manual_drift=manual_drift,
    )
    high_risk = 0
    if _change_looks_like_frame(exceptions) and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())

    if destructive_changes or policy_changes or owner_changes:
        return {
            "state": "Control Review",
            "headline": "Validate recovery-sensitive changes first.",
            "detail": f"{destructive_changes:,} destructive, {policy_changes:,} policy, and {owner_changes:,} ownership change(s) need review status.",
        }
    if high_risk:
        return {
            "state": "Review Now",
            "headline": "Review high-priority change exceptions.",
            "detail": f"{high_risk:,} Critical/High exception(s) across {object_changes + access_changes:,} object/access change(s).",
        }
    if manual_drift:
        return {
            "state": "Drift Watch",
            "headline": "Compare untracked changes against Snowflake telemetry.",
            "detail": f"{manual_drift:,} untracked drift indicator(s) need telemetry status, rollback path, or ticket reconciliation.",
        }
    if score < 95:
        return {
            "state": _change_drift_rating(score),
            "headline": "Review change volume before closing the window.",
            "detail": f"{object_changes + access_changes:,} object/access change(s) loaded for the selected scope.",
        }
    return {
        "state": "Controlled",
        "headline": "No immediate object-change blocker in the loaded brief.",
        "detail": f"{object_changes + access_changes:,} object/access change(s), {manual_drift:,} drift indicator(s).",
    }

def _change_operating_snapshot(summary, exceptions, meta: dict, company: str, environment: str, days: int) -> dict:
    loaded = (
        _change_looks_like_frame(summary)
        and not summary.empty
        and _change_meta_matches(meta, _change_scope_meta(company, environment, days))
    )
    if not loaded:
        return {
            "loaded": False,
            "scope": str(company or "All"),
            "window": f"{safe_int(days, 14):d}d",
            "evidence": "Fast facts pending",
            "risk": "On demand",
        }

    row = summary.iloc[0]
    policy_owner = safe_int(row.get("POLICY_CHANGES", 0)) + safe_int(row.get("OWNER_CHANGES", 0))
    high_risk = 0
    if _change_looks_like_frame(exceptions) and not exceptions.empty and "SEVERITY" in exceptions.columns:
        high_risk = int(exceptions["SEVERITY"].isin(["Critical", "High"]).sum())
    return {
        "loaded": True,
        "object_changes": safe_int(row.get("OBJECT_CHANGES", 0)),
        "access_changes": safe_int(row.get("ACCESS_CHANGES", 0)),
        "policy_owner": policy_owner,
        "high_risk": high_risk,
    }

def _change_brief_workflow_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in CHANGE_BRIEF_WORKFLOWS:
        workflow = str(item["WORKFLOW"])
        rows.append({
            "WORKFLOW": workflow,
            "BUTTON_LABEL": str(item["BUTTON_LABEL"]),
            "DBA_MOVE": str(item["DBA_MOVE"]),
            "WHEN": str(item["WHEN"]),
            "SOURCES": WORKFLOW_DETAILS.get(workflow, "Change workflow detail"),
        })
    return rows

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
        f"# OVERWATCH Object Change Brief - {company}",
        "",
        f"Lookback window: {days} day(s).",
        f"Control state: {_change_drift_rating(score)}.",
        "",
        "## Key Metrics",
        f"- Object changes: {safe_int(summary_row.get('OBJECT_CHANGES', 0)):,}",
        f"- Access changes: {safe_int(summary_row.get('ACCESS_CHANGES', 0)):,}",
        f"- Owner changes: {safe_int(summary_row.get('OWNER_CHANGES', 0)):,}",
        f"- Policy/tag changes: {safe_int(summary_row.get('POLICY_CHANGES', 0)):,}",
        f"- Destructive changes: {safe_int(summary_row.get('DESTRUCTIVE_CHANGES', 0)):,}",
        f"- Untracked drift indicators: {safe_int(summary_row.get('MANUAL_DRIFT', 0)):,}",
        "",
        "## Exceptions",
        *exception_lines,
        "",
        "## DBA Follow-Up",
        "- Review destructive and policy changes first.",
        "- Validate grants, revokes, and ownership transfers against reviewed access telemetry.",
        "- Compare untracked changes with source records and rollback status.",
        "- Save material exceptions to the OVERWATCH Action Queue for route/status tracking.",
        "",
        "## Data Notes",
        "Schema and access change detection should be validated against source records and telemetry status.",
    ]
    return "\n".join(lines)

__all__ = ['_change_ticket_id', '_split_snowflake_qualified_name', '_change_database_name', '_change_database_context', '_change_environment', '_change_scope_value', '_change_scope_meta', '_change_meta_matches', '_change_looks_like_frame', '_change_row_count', '_change_source_confidence', '_change_source_next_action', '_change_has_source_state', '_change_source_health_rows', '_change_owner_context', '_change_iac_state', '_change_execution_audit_state', '_change_review_sla_hours', '_change_control_readiness_for_row', '_enrich_change_control_evidence', '_change_control_readiness_summary', '_change_frame_sum', '_change_operator_next_moves', '_change_drift_score', '_change_drift_rating', '_change_action_for', '_owner_approval_for', '_change_verification_sql', '_change_blast_radius_sql', '_build_change_control_readiness', '_change_workflow_for', '_change_priority_view', '_change_intervention_matrix', '_change_action_brief', '_change_operating_snapshot', '_change_brief_workflow_rows', '_build_change_drift_markdown']
