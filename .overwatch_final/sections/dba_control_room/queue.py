"""Command queue construction, owner enrichment, and operability scoring helpers."""
from __future__ import annotations

import streamlit as st
from sections.shell_helpers import (
    render_shell_snapshot,
)
from utils.primitives import (
    safe_float,
    safe_int,
)
from .types import (
    _canonical_dba_route,
    _command_named_owner,
    _command_queue_route,
    _command_requires_approval,
    _command_text_present,
    _command_value_present,
    _dba_operations_priority_state,
    _dba_section_proof_required,
    _empty_df,
    pd,
)
from .health import (
    _dba_source_health_deployment_gate,
)
from .types import (
    dba_control_plane_section_scorecards,
    dba_effective_readiness_score,
    download_csv,
    enrich_action_queue_view,
    get_owner_context_columns,
    render_priority_dataframe,
    resolve_owner_context,
)
from .types import pd

def _priority_exceptions(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return _empty_df()
    severity_rank = {"High": 0, "Medium": 1, "Low": 2}
    view = exceptions.copy()
    view["_RANK"] = view.get("Severity", pd.Series(dtype=str)).map(severity_rank).fillna(3)
    return view.sort_values(["_RANK", "Signal"]).drop(columns=["_RANK"], errors="ignore")


def _normalize_section_score_rows(sections: pd.DataFrame) -> pd.DataFrame:
    """Normalize legacy section score rows and keep the most conservative duplicate."""
    if sections is None or sections.empty or "SECTION" not in sections.columns:
        return sections
    normalized = sections.copy()
    normalized["SECTION"] = normalized["SECTION"].apply(_canonical_dba_route)
    normalized["_SECTION_SCORE"] = pd.to_numeric(normalized.get("SCORE", 0), errors="coerce").fillna(0)
    normalized = normalized.sort_values(["SECTION", "_SECTION_SCORE"], ascending=[True, True])
    normalized = normalized.drop_duplicates("SECTION", keep="first")
    return normalized.drop(columns=["_SECTION_SCORE"], errors="ignore")


def _command_owner_entity_type(row: pd.Series | dict) -> str:
    route = str(row.get("ROUTE") or _command_queue_route(row.get("CATEGORY"))).upper()
    category = str(row.get("CATEGORY") or "").upper()
    entity_type = str(row.get("ENTITY_TYPE") or "").upper()
    if entity_type:
        return entity_type
    if "COST" in route or "COST" in category:
        return "COST_CONTROL"
    if "WAREHOUSE" in route or "WAREHOUSE" in category:
        return "WAREHOUSE"
    if "SECURITY" in route or any(token in category for token in ("SECURITY", "ACCESS", "GRANT", "ROLE")):
        return "SECURITY"
    if "CHANGE" in route or "DRIFT" in route or any(token in category for token in ("CHANGE", "DRIFT", "DDL")):
        return "CHANGE_CONTROL"
    if any(token in category for token in ("PROCEDURE", "PROC")):
        return "PROCEDURE"
    if "WORKLOAD" in route or "TASK" in category:
        return "TASK"
    if "ACCOUNT" in route or "CHECKLIST" in category:
        return "ACCOUNT_HEALTH"
    return "ALERT"


def _enrich_command_owner_context(view: pd.DataFrame) -> pd.DataFrame:
    """Add shared monitoring route fields to command queue rows."""
    if view is None or view.empty:
        return view
    enriched = view.copy()
    contexts = enriched.apply(
        lambda row: resolve_owner_context(
            row,
            entity=row.get("ENTITY_NAME") or row.get("ENTITY") or row.get("TASK_NAME") or row.get("PROCEDURE_NAME"),
            entity_type=_command_owner_entity_type(row),
            owner=row.get("OWNER"),
            category=row.get("CATEGORY"),
            alert_type=row.get("SOURCE"),
        ),
        axis=1,
    )
    for column in get_owner_context_columns():
        enriched[column] = contexts.apply(lambda context: context.get(column, ""))
    return enriched


def _command_closure_issue_flags(row: pd.Series) -> dict:
    status = str(row.get("STATUS") or "").strip().upper()
    due_state = str(row.get("DUE_STATE") or "").strip()
    verification_status = str(row.get("VERIFICATION_STATUS") or "").strip().upper()
    owner_approval_status = str(row.get("OWNER_APPROVAL_STATUS") or "").strip().upper()
    recovery_state = str(row.get("RECOVERY_SLA_STATE") or "").strip().upper()
    is_open = status not in {"FIXED", "IGNORED"}
    is_fixed = status == "FIXED"
    verified = (
        is_fixed
        and verification_status == "VERIFIED"
        and _command_text_present(row.get("VERIFICATION_RESULT"), min_length=15)
    )
    fixed_without_verification = is_fixed and not verified
    metadata_gaps = {
        "OWNER_GAP_ROWS": 0 if _command_named_owner(row) else 1,
        "TICKET_GAP_ROWS": 0 if _command_value_present(row, "TICKET_ID") else 1,
        "APPROVER_GAP_ROWS": 0 if _command_value_present(row, "APPROVER") else 1,
        "VERIFICATION_QUERY_GAP_ROWS": 0 if _command_value_present(row, "VERIFICATION_QUERY", "PROOF_QUERY") else 1,
        "OWNER_APPROVAL_GAP_ROWS": 1 if owner_approval_status in {"", "PENDING", "REQUESTED", "REQUIRED"} else 0,
    }
    recovery_risk = (
        "BREACH" in recovery_state
        or "LATE" in recovery_state
        or (is_fixed and not _command_text_present(row.get("RECOVERY_EVIDENCE"), min_length=15))
    )
    blocker_count = (
        int(due_state == "Overdue")
        + int(fixed_without_verification)
        + sum(metadata_gaps.values())
        + int(recovery_risk)
    )
    return {
        "IS_OPEN": int(is_open),
        "IS_FIXED": int(is_fixed),
        "VERIFIED_CLOSURE": int(verified),
        "FIXED_WITHOUT_VERIFICATION": int(fixed_without_verification),
        "OVERDUE_OPEN": int(is_open and due_state == "Overdue"),
        "RECOVERY_RISK_ROWS": int(recovery_risk),
        "CLOSURE_BLOCKER_ROWS": int(blocker_count > 0),
        **metadata_gaps,
    }


def _command_closure_next_action(row: pd.Series | dict) -> str:
    if safe_int(row.get("OVERDUE_OPEN", 0)):
        return "Escalate overdue work, confirm the route, and add ticket plus telemetry status."
    if safe_int(row.get("FIXED_WITHOUT_VERIFICATION", 0)):
        return "Reopen fixed items or wait for telemetry to confirm closure."
    if safe_int(row.get("RECOVERY_RISK_ROWS", 0)):
        return "Track recovery status or reopen items with breached/late closure state."
    metadata_gaps = (
        safe_int(row.get("OWNER_GAP_ROWS", 0))
        + safe_int(row.get("TICKET_GAP_ROWS", 0))
        + safe_int(row.get("APPROVER_GAP_ROWS", 0))
        + safe_int(row.get("VERIFICATION_QUERY_GAP_ROWS", 0))
        + safe_int(row.get("OWNER_APPROVAL_GAP_ROWS", 0))
    )
    if metadata_gaps:
        return "Complete route, ticket, reviewer, and telemetry metadata."
    if safe_int(row.get("OPEN_ACTIONS", 0)):
        return "Work open actions and keep before/after telemetry ready for closure."
    return "Keep closure status visible for audit and trend review."


def _command_queue_closure_readiness(queue: pd.DataFrame, today: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Summarize closure blockers across all action queue rows by DBA route."""
    if queue is None or queue.empty:
        return _empty_df()

    view = enrich_action_queue_view(queue, today=today).copy()
    if view.empty:
        return _empty_df()
    view["ROUTE"] = view.get("CATEGORY", pd.Series([""] * len(view), index=view.index)).apply(_command_queue_route)
    view = _enrich_command_owner_context(view)
    flags = view.apply(_command_closure_issue_flags, axis=1, result_type="expand")
    for column in flags.columns:
        view[column] = flags[column]

    blocker_cols = [
        "FIXED_WITHOUT_VERIFICATION", "OVERDUE_OPEN", "OWNER_GAP_ROWS",
        "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
        "OWNER_APPROVAL_GAP_ROWS", "RECOVERY_RISK_ROWS", "CLOSURE_BLOCKER_ROWS",
    ]
    source_series = view.get("SOURCE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    category_series = view.get("CATEGORY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    owner_series = view.get("OWNER", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    updated_series = pd.to_datetime(
        view.get("UPDATED_AT", view.get("CREATED_AT", pd.Series([pd.NaT] * len(view), index=view.index))),
        errors="coerce",
    )
    view["_LAST_ACTIVITY_TS"] = updated_series
    rows: list[dict] = []
    for route, group in view.groupby(view["ROUTE"].fillna("Alert Center")):
        latest_idx = group["_LAST_ACTIVITY_TS"].idxmax() if group["_LAST_ACTIVITY_TS"].notna().any() else group.index[-1]
        totals = {
            "TOTAL_ACTIONS": int(len(group)),
            "OPEN_ACTIONS": int(group["IS_OPEN"].sum()),
            "FIXED_ACTIONS": int(group["IS_FIXED"].sum()),
            "VERIFIED_CLOSURES": int(group["VERIFIED_CLOSURE"].sum()),
        }
        for column in blocker_cols:
            totals[column] = int(group[column].sum())
        metadata_gaps = (
            totals["OWNER_GAP_ROWS"]
            + totals["TICKET_GAP_ROWS"]
            + totals["APPROVER_GAP_ROWS"]
            + totals["VERIFICATION_QUERY_GAP_ROWS"]
            + totals["OWNER_APPROVAL_GAP_ROWS"]
        )
        if totals["OVERDUE_OPEN"]:
            readiness, rank = "Overdue closure", 0
        elif totals["FIXED_WITHOUT_VERIFICATION"]:
            readiness, rank = "Closed pending telemetry", 1
        elif totals["RECOVERY_RISK_ROWS"]:
            readiness, rank = "Recovery status risk", 2
        elif metadata_gaps:
            readiness, rank = "Control metadata gap", 3
        elif totals["OPEN_ACTIONS"]:
            readiness, rank = "Open", 4
        elif totals["VERIFIED_CLOSURES"]:
            readiness, rank = "Closed", 8
        else:
            readiness, rank = "No recent action", 9
        latest = group.loc[latest_idx]
        row = {
            "ROUTE": route,
            "CLOSURE_READINESS": readiness,
            "CLOSURE_RANK": rank,
            "LAST_SOURCE": str(source_series.loc[latest_idx] or ""),
            "LAST_CATEGORY": str(category_series.loc[latest_idx] or ""),
            "OWNER": str(owner_series.loc[latest_idx] or latest.get("OWNER", "")),
            "LAST_STATUS": str(latest.get("STATUS") or ""),
            "LAST_SEVERITY": str(latest.get("SEVERITY") or ""),
            "LAST_ACTIVITY_TS": latest.get("_LAST_ACTIVITY_TS"),
            **totals,
        }
        row["NEXT_CONTROL_ACTION"] = _command_closure_next_action(row)
        rows.append(row)

    if not rows:
        return _empty_df()
    return pd.DataFrame(rows).sort_values(
        ["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "CLOSURE_BLOCKER_ROWS", "OPEN_ACTIONS"],
        ascending=[True, False, False, False, False],
    )


def _command_execution_metadata(row: pd.Series) -> dict:
    """Classify whether a queue row is safe to execute from the Control Room."""
    category = str(row.get("CATEGORY") or "").upper()
    severity = str(row.get("SEVERITY") or "").upper()
    due_state = str(row.get("DUE_STATE") or "")
    approval_status = str(row.get("OWNER_APPROVAL_STATUS") or "").strip().upper()
    requires_approval = _command_requires_approval(row)
    route_ready = _command_value_present(row, "OWNER_EMAIL") and (
        _command_value_present(row, "ONCALL_PRIMARY") or _command_value_present(row, "APPROVAL_GROUP")
    )

    gaps: list[str] = []
    if not _command_named_owner(row):
        gaps.append("Named route")
    if not route_ready:
        gaps.append("On-call route")
    if not _command_value_present(row, "TICKET_ID"):
        gaps.append("Ticket/change ID")
    if not _command_value_present(row, "APPROVER"):
        gaps.append("Reviewer")
    if not _command_value_present(row, "VERIFICATION_QUERY", "PROOF_QUERY"):
        gaps.append("Telemetry query")
    if ("COST" in category or "CHARGEBACK" in category or "TASK" in category or "PROCEDURE" in category) and (
        not _command_value_present(row, "BASELINE_VALUE")
        or not _command_value_present(row, "CURRENT_VALUE")
    ):
        gaps.append("Baseline/current values")

    approval_blocked = requires_approval and approval_status in {"", "PENDING", "REQUESTED", "REQUIRED"}
    if approval_blocked:
        gaps.append("Review status")

    metadata_missing = any(item != "Review status" for item in gaps)
    if due_state == "Overdue":
        gate = "Escalate - Overdue"
    elif metadata_missing:
        gate = "Blocked - Metadata"
    elif approval_blocked:
        gate = "Blocked - Review"
    elif severity in {"CRITICAL", "HIGH"}:
        gate = "Ready - High Risk"
    else:
        gate = "Ready - Standard"

    audit_ready = gate.startswith("Ready")
    return {
        "COMMAND_OWNER_READINESS": "Named Route" if _command_named_owner(row) else "Route Needed",
        "COMMAND_ROUTE_READINESS": "Route Ready" if route_ready else "Route Needed",
        "COMMAND_AUDIT_READINESS": "Audit Ready" if audit_ready else "Audit Gaps",
        "COMMAND_EXECUTION_GATE": gate,
        "COMMAND_EVIDENCE_REQUIRED": "; ".join(dict.fromkeys(gaps)) if gaps else "Ready for controlled execution",
    }


def _build_command_queue(queue: pd.DataFrame, today: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Return open action-queue rows as a DBA command queue with control gaps."""
    if queue is None or queue.empty:
        return _empty_df()

    view = enrich_action_queue_view(queue, today=today).copy()
    status = view.get("STATUS", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    view = view[~status.isin(["FIXED", "IGNORED"])].copy()
    if view.empty:
        return _empty_df()

    severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    due_rank = {"Overdue": 0, "Due today": 1, "Due soon": 2, "Unscheduled": 3, "Scheduled": 4}
    evidence = view.get("EVIDENCE_GAP", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    severity = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    due_state = view.get("DUE_STATE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)

    view["ROUTE"] = view.get("CATEGORY", pd.Series([""] * len(view), index=view.index)).apply(_command_queue_route)
    view = _enrich_command_owner_context(view)
    view["CONTROL_GAP"] = evidence.where(evidence.ne("Ready to work"), "")
    command_metadata = view.apply(_command_execution_metadata, axis=1, result_type="expand")
    for column in command_metadata.columns:
        view[column] = command_metadata[column]
    view["PROOF_READY"] = view["COMMAND_EXECUTION_GATE"].astype(str).str.startswith("Ready").map({True: "Yes", False: "No"})
    view["COMMAND_STATE"] = "Work Ready"
    view.loc[evidence.ne("Ready to work"), "COMMAND_STATE"] = "Complete Control Metadata"
    view.loc[due_state.eq("Overdue"), "COMMAND_STATE"] = "Escalate Overdue"
    view.loc[severity.isin(["CRITICAL", "HIGH"]) & evidence.eq("Ready to work"), "COMMAND_STATE"] = "Work Now"
    view["_COMMAND_SORT"] = (
        due_state.map(due_rank).fillna(5).astype(float) * 10
        + severity.map(severity_rank).fillna(4).astype(float)
        + evidence.ne("Ready to work").astype(int)
    )
    return view.sort_values(["_COMMAND_SORT", "QUEUE_PRIORITY"], ascending=[True, True]).drop(
        columns=["_COMMAND_SORT"],
        errors="ignore",
    )


def _command_queue_summary(queue: pd.DataFrame) -> dict:
    """Summarize command-queue readiness without changing stored queue data."""
    if queue is None or queue.empty:
        return {
            "open": 0,
            "overdue": 0,
            "ready": 0,
            "control_gaps": 0,
            "owner_gaps": 0,
            "approval_gaps": 0,
            "ticket_gaps": 0,
            "high_risk": 0,
            "execution_ready": 0,
            "audit_ready": 0,
            "route_ready": 0,
            "metadata_blocks": 0,
            "approval_blocks": 0,
            "control_ready_pct": 0.0,
        }
    evidence = queue.get("EVIDENCE_GAP", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
    command_evidence = queue.get(
        "COMMAND_EVIDENCE_REQUIRED",
        pd.Series([""] * len(queue), index=queue.index),
    ).fillna("").astype(str)
    evidence_rollup = evidence + " " + command_evidence
    severity = queue.get("SEVERITY", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str).str.upper()
    due_state = queue.get("DUE_STATE", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
    gate = queue.get("COMMAND_EXECUTION_GATE", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
    audit = queue.get("COMMAND_AUDIT_READINESS", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
    route = queue.get("COMMAND_ROUTE_READINESS", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
    ready = int(gate.str.startswith("Ready").sum())
    summary = {
        "open": int(len(queue)),
        "overdue": int(due_state.eq("Overdue").sum()),
        "ready": ready if "COMMAND_EXECUTION_GATE" in queue.columns else int(evidence.eq("Ready to work").sum()),
        "control_gaps": int(evidence.ne("Ready to work").sum()),
        "owner_gaps": int(evidence_rollup.str.contains("named owner", case=False, na=False).sum()),
        "approval_gaps": int(evidence_rollup.str.contains("reviewer|Review status", case=False, na=False).sum()),
        "ticket_gaps": int(evidence_rollup.str.contains("ticket|change ID", case=False, na=False).sum()),
        "high_risk": int(severity.isin(["CRITICAL", "HIGH"]).sum()),
        "execution_ready": ready,
        "audit_ready": int(audit.eq("Audit Ready").sum()),
        "route_ready": int(route.eq("Route Ready").sum()),
        "metadata_blocks": int(gate.eq("Blocked - Metadata").sum()),
        "approval_blocks": int(gate.eq("Blocked - Review").sum()),
    }
    summary["control_ready_pct"] = round((summary["execution_ready"] / summary["open"]) * 100, 1) if summary["open"] else 0.0
    return summary


def _command_queue_route_readiness(queue: pd.DataFrame) -> pd.DataFrame:
    """Summarize command readiness by routed DBA section."""
    if queue is None or queue.empty:
        return _empty_df()
    rows: list[dict] = []
    route_series = queue.get("ROUTE", pd.Series(["Unrouted"] * len(queue), index=queue.index)).fillna("Unrouted").apply(_canonical_dba_route)
    for route, group in queue.groupby(route_series):
        summary = _command_queue_summary(group)
        if summary["overdue"]:
            next_action = "Escalate overdue items and add route/ticket status."
        elif summary["metadata_blocks"]:
            next_action = "Complete route, ticket, reviewer, and telemetry metadata."
        elif summary["approval_blocks"]:
            next_action = "Collect review status before DBA execution."
        elif summary["execution_ready"]:
            next_action = "Work ready items, then monitor telemetry before closure."
        else:
            next_action = "Triage route and assign accountable DBA on-call."
        rows.append({
            "ROUTE": route,
            "OPEN_ACTIONS": summary["open"],
            "OVERDUE": summary["overdue"],
            "EXECUTION_READY": summary["execution_ready"],
            "AUDIT_READY": summary["audit_ready"],
            "ROUTE_READY": summary["route_ready"],
            "OWNER_GAPS": summary["owner_gaps"],
            "APPROVAL_BLOCKS": summary["approval_blocks"],
            "METADATA_BLOCKS": summary["metadata_blocks"],
            "CONTROL_READY_PCT": summary["control_ready_pct"],
            "NEXT_CONTROL_ACTION": next_action,
        })
    return pd.DataFrame(rows).sort_values(
        ["OVERDUE", "METADATA_BLOCKS", "APPROVAL_BLOCKS", "OPEN_ACTIONS"],
        ascending=[False, False, False, False],
    )


def _dba_section_operability_board(
    section_rows: pd.DataFrame | None = None,
    command_queue: pd.DataFrame | None = None,
    closure_rollup: pd.DataFrame | None = None,
    source_health: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join static 95-readiness with live command/closure blockers by DBA route."""
    sections = section_rows.copy() if section_rows is not None and not section_rows.empty else pd.DataFrame(dba_control_plane_section_scorecards())
    sections = _normalize_section_score_rows(sections)
    if sections.empty:
        return _empty_df()

    route_readiness = _command_queue_route_readiness(command_queue) if command_queue is not None and not command_queue.empty else _empty_df()
    closure = closure_rollup.copy() if closure_rollup is not None and not closure_rollup.empty else _empty_df()
    route_by_name = {
        _canonical_dba_route(row.get("ROUTE") or ""): row
        for _, row in route_readiness.iterrows()
    } if not route_readiness.empty else {}
    closure_by_name = {
        _canonical_dba_route(row.get("ROUTE") or ""): row
        for _, row in closure.iterrows()
    } if not closure.empty else {}
    source_gate = _dba_source_health_deployment_gate(source_health)

    rows: list[dict] = []
    for _, section in sections.iterrows():
        name = str(section.get("SECTION") or "")
        route = route_by_name.get(name, {})
        close = closure_by_name.get(name, {})
        score = safe_float(section.get("SCORE", 0))
        open_actions = safe_int(route.get("OPEN_ACTIONS", 0))
        overdue = max(safe_int(route.get("OVERDUE", 0)), safe_int(close.get("OVERDUE_OPEN", 0)))
        metadata_blocks = safe_int(route.get("METADATA_BLOCKS", 0))
        approval_blocks = safe_int(route.get("APPROVAL_BLOCKS", 0))
        execution_ready = safe_int(route.get("EXECUTION_READY", 0))
        closure_rank = safe_int(close.get("CLOSURE_RANK", 9))
        closure_blockers = safe_int(close.get("CLOSURE_BLOCKER_ROWS", 0))
        fixed_without_verification = safe_int(close.get("FIXED_WITHOUT_VERIFICATION", 0))
        recovery_risk = safe_int(close.get("RECOVERY_RISK_ROWS", 0))
        verified_closures = safe_int(close.get("VERIFIED_CLOSURES", 0))

        if overdue:
            state, rank = "Escalate Now", 0
            next_action = "Escalate overdue route work and add ticket plus telemetry status."
            closure_gate_score = 72
        elif fixed_without_verification or recovery_risk or closure_rank in {1, 2}:
            state, rank = "Closure Status Pending", 1
            next_action = "Wait for telemetry or recovery status before accepting the section as controlled."
            closure_gate_score = 82
        elif metadata_blocks:
            state, rank = "Route Metadata Blocked", 2
            next_action = "Complete route, ticket, reviewer, and telemetry metadata for open work."
            closure_gate_score = 88
        elif approval_blocks:
            state, rank = "Review Blocked", 3
            next_action = "Collect review status before DBA execution."
            closure_gate_score = 90
        elif open_actions:
            state, rank = "Work Open Actions", 4
            next_action = "Work ready actions, then retain telemetry for closure."
            closure_gate_score = 94
        elif score < 95:
            state, rank = "Build Toward 95", 6
            next_action = str(section.get("NEXT_95_MOVE") or "Raise weak control-plane components.")
            closure_gate_score = 100
        else:
            state, rank = "95 Target", 8
            next_action = "Maintain closure status and route coverage."
            closure_gate_score = 100

        gates = {
            "source_health": source_gate,
            "route_control": {
                "score": closure_gate_score,
                "label": "Route Control",
                "reason": next_action if closure_gate_score < 100 else "",
            },
        }
        effective = dba_effective_readiness_score(score, gates)
        effective_score = safe_float(effective.get("score", score))
        gate_drivers = ", ".join(
            str(gate.get("GATE") or gate.get("KEY") or "").strip()
            for gate in effective.get("gate_drivers", [])
            if str(gate.get("GATE") or gate.get("KEY") or "").strip()
        ) or "none"
        if effective_score < score and rank >= 6:
            state, rank = "Deployment Gate", 5
            gate_reason = str(source_gate.get("reason") or "").strip()
            next_action = gate_reason or "Resolve active deployment gate driver(s) before treating this section as ready."

        rows.append({
            "SECTION": name,
            "SCORE": score,
            "EFFECTIVE_SCORE": effective_score,
            "LABEL": section.get("LABEL", ""),
            "DEPLOYMENT_LABEL": effective.get("label", ""),
            "GATE_DRIVERS": gate_drivers,
            "OPERABILITY_STATE": state,
            "OPERABILITY_RANK": rank,
            "OPEN_ACTIONS": open_actions,
            "OVERDUE": overdue,
            "EXECUTION_READY": execution_ready,
            "METADATA_BLOCKS": metadata_blocks,
            "APPROVAL_BLOCKS": approval_blocks,
            "CLOSURE_READINESS": close.get("CLOSURE_READINESS", "No recent action"),
            "CLOSURE_BLOCKERS": closure_blockers,
            "FIXED_WITHOUT_VERIFICATION": fixed_without_verification,
            "RECOVERY_RISK_ROWS": recovery_risk,
            "VERIFIED_CLOSURES": verified_closures,
            "LOWEST_COMPONENT": section.get("LOWEST_COMPONENT", ""),
            "LOWEST_SCORE": safe_float(section.get("LOWEST_SCORE", 0)),
            "CAP_DRIVERS": section.get("CAP_DRIVERS", ""),
            "PROOF_REQUIRED": _dba_section_proof_required(name, section.get("LOWEST_COMPONENT", "")),
            "NEXT_CONTROL_ACTION": next_action,
            "NEXT_95_MOVE": section.get("NEXT_95_MOVE", ""),
        })

    if not rows:
        return _empty_df()
    return pd.DataFrame(rows).sort_values(
        [
            "OPERABILITY_RANK",
            "OVERDUE",
            "CLOSURE_BLOCKERS",
            "METADATA_BLOCKS",
            "APPROVAL_BLOCKS",
            "SCORE",
        ],
        ascending=[True, False, False, False, False, True],
    ).reset_index(drop=True)


def _dba_operations_priority_index(
    section_board: pd.DataFrame | None,
    incident_board: pd.DataFrame | None,
    command_queue: pd.DataFrame | None,
    source_health: pd.DataFrame | None,
    *,
    max_rows: int = 9,
) -> pd.DataFrame:
    """Rank DBA sections by live risk, command blockers, telemetry gaps, and 99-target drift."""
    board = section_board.copy() if section_board is not None and not section_board.empty else _dba_section_operability_board(
        command_queue=command_queue,
        closure_rollup=_command_queue_closure_readiness(command_queue),
        source_health=source_health,
    )
    if board is None or board.empty:
        return _empty_df()
    board.columns = [str(col).upper() for col in board.columns]

    incident = incident_board.copy() if incident_board is not None and not incident_board.empty else _empty_df()
    if not incident.empty:
        incident.columns = [str(col).upper() for col in incident.columns]
    source = source_health.copy() if source_health is not None and not source_health.empty else _empty_df()
    if not source.empty:
        source.columns = [str(col).upper() for col in source.columns]

    rows: list[dict] = []
    severity_points = {"CRITICAL": 35, "HIGH": 24, "MEDIUM": 12, "LOW": 4}
    status_points = {
        "CONTAINMENT REQUIRED": 18,
        "EVIDENCE REFRESH REQUIRED": 12,
        "INVESTIGATE NOW": 10,
        "TRIAGE": 5,
        "MONITOR": 0,
    }
    for _, item in board.iterrows():
        section = str(item.get("SECTION") or "DBA Control Room")
        score = safe_float(item.get("SCORE", 0))
        effective_score = safe_float(item.get("EFFECTIVE_SCORE", score))
        matched_incidents = _empty_df()
        if not incident.empty and "AFFECTED_ROUTES" in incident.columns:
            route_text = incident["AFFECTED_ROUTES"].fillna("").astype(str)
            matched_incidents = incident[route_text.eq(section) | route_text.str.contains(section, case=False, regex=False)].copy()
        source_issue_count = 0
        if section == "DBA Control Room" and not source.empty and "STATE" in source.columns:
            source_issue_count = int(source["STATE"].fillna("").astype(str).isin(["Unavailable", "Stale"]).sum())
        if not matched_incidents.empty:
            incident_points = int(
                matched_incidents.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
                .map(severity_points).fillna(0).sum()
            )
            incident_points += int(
                matched_incidents.get("STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
                .map(status_points).fillna(0).sum()
            )
            ordered_incidents = matched_incidents.copy()
            ordered_incidents["_SEVERITY_RANK"] = (
                ordered_incidents.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
                .map({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}).fillna(4)
            )
            ordered_incidents["_STATUS_RANK"] = (
                ordered_incidents.get("STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
                .map({"CONTAINMENT REQUIRED": 0, "EVIDENCE REFRESH REQUIRED": 1, "INVESTIGATE NOW": 2, "TRIAGE": 3, "MONITOR": 4})
                .fillna(5)
            )
            incident_text = (
                ordered_incidents.get("INCIDENT_TYPE", pd.Series(dtype=str)).fillna("").astype(str)
                + " "
                + ordered_incidents.get("SIGNALS", pd.Series(dtype=str)).fillna("").astype(str)
            ).str.upper()
            ordered_incidents["_LIVE_CAPACITY_RANK"] = incident_text.str.contains("QUEUE|WAREHOUSE|SPILL|CAPACITY", regex=True).map({True: 0, False: 1})
            ordered_incidents = ordered_incidents.sort_values(
                ["_SEVERITY_RANK", "_STATUS_RANK", "_LIVE_CAPACITY_RANK"],
                ascending=[True, True, True],
                kind="mergesort",
            )
            worst = ordered_incidents.iloc[0]
            signal_bits: list[str] = []
            for _, incident_row in ordered_incidents.head(3).iterrows():
                signal = str(incident_row.get("SIGNALS") or incident_row.get("SIGNAL") or "").strip()
                if signal and signal not in signal_bits:
                    signal_bits.append(signal)
            worst_signal = "; ".join(signal_bits)
            worst_status = str(worst.get("STATUS") or "")
            incident_containment = str(worst.get("CONTAINMENT_ACTION") or "")
        else:
            incident_points = 0
            worst_signal = ""
            worst_status = ""
            incident_containment = ""

        overdue = safe_int(item.get("OVERDUE"))
        closure_blockers = safe_int(item.get("CLOSURE_BLOCKERS"))
        metadata_blocks = safe_int(item.get("METADATA_BLOCKS"))
        approval_blocks = safe_int(item.get("APPROVAL_BLOCKS"))
        execution_ready = safe_int(item.get("EXECUTION_READY"))
        recovery_risk = safe_int(item.get("RECOVERY_RISK_ROWS"))
        fixed_without_verification = safe_int(item.get("FIXED_WITHOUT_VERIFICATION"))
        proof_blocks = closure_blockers + recovery_risk + fixed_without_verification
        target_gap = max(0.0, 99.0 - effective_score)
        deployment_gap = max(0.0, score - effective_score)
        priority_score = min(100, round(
            (target_gap * 1.7)
            + (deployment_gap * 1.4)
            + incident_points
            + overdue * 18
            + proof_blocks * 10
            + metadata_blocks * 7
            + approval_blocks * 8
            + source_issue_count * 8
            + execution_ready * 2,
            1,
        ))
        reason_bits = []
        if worst_signal:
            reason_bits.append(worst_signal)
        if overdue:
            reason_bits.append(f"{overdue:,} overdue")
        if proof_blocks:
            reason_bits.append(f"{proof_blocks:,} telemetry/recovery blocker(s)")
        if metadata_blocks:
            reason_bits.append(f"{metadata_blocks:,} metadata blocker(s)")
        if approval_blocks:
            reason_bits.append(f"{approval_blocks:,} review blocker(s)")
        if source_issue_count:
            reason_bits.append(f"{source_issue_count:,} stale/unavailable source(s)")
        if deployment_gap:
            reason_bits.append(f"{deployment_gap:.1f} effective-status gate")
        if not reason_bits and target_gap:
            reason_bits.append("route needs telemetry hardening")
        row = {
            "SECTION": section,
            "PRIORITY_SCORE": priority_score,
            "SCORE": score,
            "EFFECTIVE_SCORE": effective_score,
            "DEPLOYMENT_LABEL": str(item.get("DEPLOYMENT_LABEL") or ""),
            "GATE_DRIVERS": str(item.get("GATE_DRIVERS") or "none"),
            "TARGET_GAP_TO_99": round(target_gap, 1),
            "WORST_INCIDENT_STATUS": worst_status,
            "WORST_SIGNAL": worst_signal or str(item.get("OPERABILITY_STATE") or "No live incident"),
            "OVERDUE": overdue,
            "EXECUTION_READY": execution_ready,
            "METADATA_BLOCKS": metadata_blocks,
            "APPROVAL_BLOCKS": approval_blocks,
            "PROOF_BLOCKS": proof_blocks,
            "SOURCE_ISSUES": source_issue_count,
            "WHY_NOW": "; ".join(reason_bits) or "No active blocker; keep monitoring.",
            "INCIDENT_CONTAINMENT": incident_containment,
            "SECTION_NEXT_ACTION": str(item.get("NEXT_CONTROL_ACTION") or ""),
            "NEXT_99_MOVE": str(item.get("NEXT_95_MOVE") or item.get("NEXT_CONTROL_ACTION") or ""),
            "PROOF_REQUIRED": str(item.get("PROOF_REQUIRED") or _dba_section_proof_required(section)),
        }
        state, first_move = _dba_operations_priority_state(row)
        row["OPERATIONS_PRIORITY_STATE"] = state
        row["FIRST_MOVE"] = first_move
        rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        ["PRIORITY_SCORE", "OVERDUE", "PROOF_BLOCKS", "METADATA_BLOCKS", "APPROVAL_BLOCKS", "TARGET_GAP_TO_99"],
        ascending=[False, False, False, False, False, False],
    ).head(max_rows).reset_index(drop=True)


def _render_operations_priority_index(priority_index: pd.DataFrame) -> None:
    if priority_index is None or priority_index.empty:
        return
    hot = priority_index.iloc[0]
    st.markdown("**Operations Priority**")
    first_move = str(hot.get("FIRST_MOVE") or "Review the top routed workflow.").strip()
    top_route = str(hot.get("SECTION") or "DBA Control Room").strip()
    st.info(f"{top_route}: {first_move}")
    open_blocks = (
        safe_int(hot.get("PROOF_BLOCKS"))
        + safe_int(hot.get("METADATA_BLOCKS"))
        + safe_int(hot.get("APPROVAL_BLOCKS"))
        + safe_int(hot.get("SOURCE_ISSUES"))
    )
    render_shell_snapshot((
        ("Top Route", top_route),
        ("Open Blocks", f"{open_blocks:,}"),
        ("Routes Reviewed", f"{len(priority_index):,}"),
    ))
    view = priority_index.rename(columns={
        "OPERATIONS_PRIORITY_STATE": "State",
        "SECTION": "Route",
        "WORST_SIGNAL": "Signal",
        "OVERDUE": "Overdue",
        "PROOF_BLOCKS": "Telemetry Blocks",
        "METADATA_BLOCKS": "Metadata Blocks",
        "APPROVAL_BLOCKS": "Review Blocks",
        "SOURCE_ISSUES": "Input Issues",
        "WHY_NOW": "Why Now",
        "FIRST_MOVE": "First Move",
        "PROOF_REQUIRED": "Telemetry Basis",
        "PRIORITY_SCORE": "Sort Priority",
    })
    render_priority_dataframe(
        view,
        title="Operations priority board",
        priority_columns=[
            "Route", "State", "Signal", "Overdue", "Telemetry Blocks", "Metadata Blocks",
            "Review Blocks", "Input Issues", "Why Now", "First Move", "Telemetry Basis",
        ],
        sort_by=["Sort Priority", "Overdue", "Telemetry Blocks"],
        ascending=[False, False, False],
        raw_label="All operations priority rows",
        height=260,
        max_rows=9,
    )
    download_csv(view, "dba_operations_priority.csv")


def _render_command_queue_control(
    queue: pd.DataFrame,
    raw_queue: pd.DataFrame | None = None,
    closure_rollup: pd.DataFrame | None = None,
    section_board: pd.DataFrame | None = None,
) -> None:
    summary = _command_queue_summary(queue)
    if closure_rollup is None:
        closure_rollup = _command_queue_closure_readiness(raw_queue if raw_queue is not None else queue)
    if queue.empty and closure_rollup.empty:
        st.success("No open action queue items or closure status blockers for the current company/environment scope.")
        return
    closure_blockers = (
        0
        if closure_rollup.empty
        else int(
            closure_rollup[
                (closure_rollup["CLOSURE_RANK"] <= 3)
                | (closure_rollup["CLOSURE_BLOCKER_ROWS"] > 0)
            ]["CLOSURE_BLOCKER_ROWS"].sum()
        )
    )
    st.markdown("**DBA Action Queue Control**")
    total_blocks = summary["approval_blocks"] + summary["metadata_blocks"] + closure_blockers
    render_shell_snapshot((
        ("Open Actions", f"{summary['open']:,}"),
        ("Overdue", f"{summary['overdue']:,}"),
        ("Ready", f"{summary['execution_ready']:,}"),
        ("Blocked", f"{total_blocks:,}"),
    ))

    if section_board is None:
        section_board = _dba_section_operability_board(
            command_queue=queue,
            closure_rollup=closure_rollup,
        )
    if not section_board.empty:
        render_priority_dataframe(
            section_board,
            title="DBA operating detail",
            priority_columns=[
                "OPERABILITY_STATE", "SECTION", "DEPLOYMENT_LABEL", "GATE_DRIVERS", "OPEN_ACTIONS",
                "OVERDUE", "EXECUTION_READY", "METADATA_BLOCKS", "APPROVAL_BLOCKS",
                "CLOSURE_READINESS", "CLOSURE_BLOCKERS", "FIXED_WITHOUT_VERIFICATION",
                "RECOVERY_RISK_ROWS", "LOWEST_COMPONENT",
                "PROOF_REQUIRED", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["OPERABILITY_RANK", "OVERDUE"],
            ascending=[True, False],
            raw_label="All DBA operating rows",
            height=280,
            max_rows=12,
        )

    if not closure_rollup.empty:
        render_priority_dataframe(
            closure_rollup,
            title="Cross-section closure blockers",
            priority_columns=[
                "ROUTE", "CLOSURE_READINESS", "TOTAL_ACTIONS", "OPEN_ACTIONS",
                "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "RECOVERY_RISK_ROWS",
                "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                "LAST_STATUS", "LAST_SEVERITY", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "CLOSURE_BLOCKER_ROWS"],
            ascending=[True, False, False, False],
            raw_label="All closure status rows",
            height=240,
            max_rows=10,
        )

    if queue.empty:
        st.success("No open action queue items for the current company/environment scope.")
        return

    route_readiness = _command_queue_route_readiness(queue)
    if not route_readiness.empty:
        render_priority_dataframe(
            route_readiness,
            title="Action status by DBA route",
            priority_columns=[
                "ROUTE", "OPEN_ACTIONS", "OVERDUE", "EXECUTION_READY", "AUDIT_READY",
                "ROUTE_READY", "OWNER_GAPS", "APPROVAL_BLOCKS", "METADATA_BLOCKS",
                "CONTROL_READY_PCT", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["OVERDUE", "METADATA_BLOCKS", "APPROVAL_BLOCKS", "OPEN_ACTIONS"],
            ascending=[False, False, False, False],
            raw_label="All action route status rows",
            height=220,
            max_rows=10,
        )

    render_priority_dataframe(
        queue,
        title="Open queue items to route, monitor, or escalate",
        priority_columns=[
            "SEVERITY", "DUE_STATE", "COMMAND_STATE", "COMMAND_EXECUTION_GATE",
            "COMMAND_ROUTE_READINESS", "COMMAND_AUDIT_READINESS", "CATEGORY", "ENTITY_NAME",
            "OWNER", "OWNER_EMAIL", "ONCALL_PRIMARY", "APPROVAL_GROUP",
            "STATUS", "COMMAND_EVIDENCE_REQUIRED", "NEXT_ACTION", "TICKET_ID",
            "APPROVER", "OWNER_SOURCE", "ROUTE",
        ],
        sort_by=["QUEUE_PRIORITY", "SEVERITY"],
        ascending=[True, True],
        raw_label="All open DBA command queue rows",
        height=300,
        max_rows=15,
    )


def _render_dba_command_intelligence_contract() -> None:
    """Show the command intelligence layer that DBA Control Room owns."""
    from utils.operational_intelligence import build_capability_register_rows

    focus = {
        "Detection and Root-Cause Engine",
        "Task/Pipeline Critical Path Brain",
        "Alert Lifecycle 2.0",
        "Bounded Refresh Guardrails",
        "Scheduled Mart Layer With Fallback",
        "Monitoring Docs and Runbooks",
    }
    rows = pd.DataFrame(
        [row for row in build_capability_register_rows() if row["CAPABILITY"] in focus]
    )
    render_priority_dataframe(
        rows,
        title="DBA command intelligence foundation",
        priority_columns=[
            "RANK", "CAPABILITY", "STATUS", "WHY_IT_MATTERS",
            "NEXT_ACTION", "PRODUCTION_GUARDRAIL",
        ],
        sort_by=["RANK"],
        ascending=True,
        raw_label="All DBA command intelligence rows",
        height=240,
        max_rows=6,
    )


def _render_loaded_advisor_signals(advisor_rows: pd.DataFrame | None) -> None:
    if advisor_rows is None or advisor_rows.empty:
        st.info("No loaded advisor signals are available yet. Open Cost & Contract, Warehouse Health, or Stored Procedures and load advisor telemetry.")
        return
    rows = advisor_rows.copy()
    high = int(rows["SEVERITY"].astype(str).str.title().isin(["Critical", "High"]).sum()) if "SEVERITY" in rows.columns else 0
    savings = safe_float(pd.to_numeric(rows.get("EST_MONTHLY_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    risk = safe_float(pd.to_numeric(rows.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    st.markdown("**Loaded Advisor Signals**")
    render_shell_snapshot((
        ("Signals", f"{len(rows):,}"),
        ("High Priority", f"{high:,}"),
        ("Est. Savings / Mo", f"${savings:,.0f}"),
        ("Value At Risk", f"${risk:,.0f}"),
    ))
    render_priority_dataframe(
        rows,
        title="Loaded advisor queue",
        priority_columns=[
            "SOURCE_SURFACE", "SEVERITY", "SIGNAL", "ENTITY", "ROUTE",
            "NEXT_ACTION", "TELEMETRY_BASIS", "EST_MONTHLY_SAVINGS_USD", "VALUE_AT_RISK_USD",
        ],
        sort_by=["PRIORITY_RANK", "VALUE_AT_RISK_USD", "EST_MONTHLY_SAVINGS_USD"],
        ascending=[True, False, False],
        raw_label="All loaded advisor signals",
        height=320,
        max_rows=14,
    )

