# sections/warehouse_health_actions.py - Warehouse Health action/control helpers.
from __future__ import annotations

from datetime import datetime

import pandas as pd

from config import THRESHOLDS
from sections.base import lazy_util as _lazy_util
from sections.warehouse_health_dataframes import (
    _warehouse_bool_setting,
    _warehouse_first_setting,
    _warehouse_row_by_name,
    _warehouse_setting_present,
    _warehouse_text,
    _warehouse_upper_frame,
)
from sections.warehouse_health_helpers import (
    _warehouse_capacity_action_for,
    _warehouse_capacity_workflow_for,
)
from sections.warehouse_health_sql import (
    _warehouse_capacity_verification_sql,
    _warehouse_cost_control_review_sql,
    _warehouse_setting_review_sql,
    warehouse_setting_review_fqn,
)
from utils.primitives import safe_float, safe_int


make_action_id = _lazy_util("make_action_id")
resolve_owner_context = _lazy_util("resolve_owner_context")
sql_literal = _lazy_util("sql_literal")


def _route_label(value: object, default: str = "Platform DBA") -> str:
    text = str(value or default).strip() or default
    text = text.replace("Owner", "Route").replace("owner", "route")
    for duplicate in ("Route Route", "Route route", "route Route", "route route"):
        while duplicate in text:
            text = text.replace(duplicate, "Route")
    return text.replace("Cost route", "Cost Route")


def _warehouse_owner_context(row: pd.Series | dict) -> dict:
    wh = str(row.get("WAREHOUSE_NAME") or "").upper()
    signal = str(row.get("SIGNAL") or "").upper()
    if "CREDIT" in signal:
        base = {
            "owner": "DBA / Cost owner Route",
            "escalation": "Cost owner / DBA Lead",
            "source": "Warehouse signal route map",
        }
    elif any(token in wh for token in ("ETL", "LOAD", "TASK", "PIPE", "AIRFLOW", "DBT")):
        base = {
            "owner": "Data Engineering Route",
            "escalation": "Pipeline Route / DBA On-Call",
            "source": "Warehouse name route hint",
        }
    elif any(token in wh for token in ("BI", "REPORT", "LOOKER", "POWERBI", "TABLEAU")):
        base = {
            "owner": "BI Platform Route",
            "escalation": "BI Product Route / DBA Lead",
            "source": "Warehouse name route hint",
        }
    elif any(token in wh for token in ("DEV", "SAN", "SIT", "PHX", "SEA")):
        base = {
            "owner": "Development Platform Route",
            "escalation": "DBA Lead",
            "source": "Warehouse name route hint",
        }
    else:
        base = {
            "owner": "Platform DBA",
            "escalation": "DBA Lead",
            "source": "Default warehouse route",
        }
    directory_context = resolve_owner_context(
        row,
        entity=wh,
        entity_type="WAREHOUSE",
        owner=base["owner"],
        category=signal or "Warehouse Capacity",
    )
    return {
        "owner": _route_label(directory_context.get("OWNER") or base["owner"]),
        "escalation": base["escalation"] or directory_context.get("ESCALATION_TARGET", ""),
        "source": _route_label(f"{base['source']}; {directory_context.get('OWNER_SOURCE', '')}".strip("; ")),
        "owner_email": directory_context.get("OWNER_EMAIL", ""),
        "oncall_primary": directory_context.get("ONCALL_PRIMARY", ""),
        "oncall_secondary": directory_context.get("ONCALL_SECONDARY", ""),
        "approval_group": base["escalation"] or directory_context.get("APPROVAL_GROUP", ""),
        "owner_evidence": _route_label(directory_context.get("OWNER_EVIDENCE", "")),
    }


def _warehouse_approval_for(row: pd.Series | dict) -> str:
    signal = str(row.get("SIGNAL") or "").upper()
    owner = _route_label(row.get("OWNER") or _warehouse_owner_context(row)["owner"])
    if "CREDIT" in signal:
        return "Cost owner / Warehouse Route"
    if "QUEUE" in signal:
        return f"{owner} / DBA Lead"
    if "SPILL" in signal:
        return f"{owner} / Query Route"
    return f"{owner} / DBA Lead"


def _warehouse_setting_candidate_for(row: pd.Series) -> dict:
    """Return the reviewed settings lane for a warehouse capacity exception."""
    signal = str(row.get("SIGNAL") or "").upper()
    queued = safe_int(row.get("QUEUED_QUERIES"))
    spill = safe_int(row.get("SPILL_QUERIES"))
    high_latency = safe_int(row.get("HIGH_LATENCY_QUERIES"))
    spike = safe_float(row.get("CREDIT_SPIKE_PCT"))
    p95 = safe_float(row.get("P95_ELAPSED_SEC"))

    if "QUEUE" in signal:
        candidate = "Review MAX_CLUSTER_COUNT, SCALING_POLICY, WAREHOUSE_SIZE, and workload routing."
        safe_path = (
            "Use Warehouse Settings Manager to load current settings, review any multi-cluster or size change, "
            "capture rollback SQL, then verify queue count and p95 latency."
        )
        risk = "Scaling can improve concurrency but may multiply credit burn or hide workload design problems."
    elif "SPILL" in signal:
        candidate = "Review WAREHOUSE_SIZE only after top spilling queries, clustering, and query shape are inspected."
        safe_path = (
            "Use Query Profile telemetry before resizing; if a size change is planned, capture rollback SQL and "
            "monitor spill count, p95 latency, and credits after the change."
        )
        risk = "Blind resizing can mask inefficient SQL and permanently raise run-rate cost."
    elif "CREDIT" in signal:
        candidate = "Review AUTO_SUSPEND, MIN_CLUSTER_COUNT, MAX_CLUSTER_COUNT, QAS, and workload schedule alignment."
        safe_path = (
            "Use Warehouse Settings Manager to compare current settings with burn drivers, require review status, "
            "save rollback SQL, then monitor credits and query volume after the change."
        )
        risk = "Cost controls can affect availability, queueing, or service-level expectations if applied broadly."
    else:
        candidate = "Review STATEMENT_TIMEOUT_IN_SECONDS, MAX_CONCURRENCY_LEVEL, WAREHOUSE_SIZE, and workload routing."
        safe_path = (
            "Use Warehouse Settings Manager for changed-only SQL, review status, rollback SQL, and post-change "
            "runtime telemetry."
        )
        risk = "Latency changes can shift failures, queueing, or user experience if applied without workload telemetry."

    readiness = "Ready for DBA review" if str(row.get("WAREHOUSE_NAME") or "").strip() else "Missing warehouse identity"
    owner_context = _warehouse_owner_context(row)
    return {
        "ADMIN_READINESS": readiness,
        "OWNER": owner_context["owner"],
        "ESCALATION_TARGET": owner_context["escalation"],
        "OWNER_SOURCE": owner_context["source"],
        "OWNER_EMAIL": owner_context.get("owner_email", ""),
        "ONCALL_PRIMARY": owner_context.get("oncall_primary", ""),
        "ONCALL_SECONDARY": owner_context.get("oncall_secondary", ""),
        "APPROVAL_GROUP": owner_context.get("approval_group", ""),
        "OWNER_EVIDENCE": owner_context.get("owner_evidence", ""),
        "APPROVER": _warehouse_approval_for({**row.to_dict(), **owner_context} if hasattr(row, "to_dict") else row),
        "SETTING_CHANGE_CANDIDATE": candidate,
        "APPROVAL_REQUIRED": "Yes",
        "ROLLBACK_REQUIRED": "Yes",
        "SAFE_CHANGE_PATH": safe_path,
        "CHANGE_RISK": risk,
        "POST_CHANGE_VERIFICATION": (
            "Compare queued queries, spill queries, p95 latency, and metered credits for the same warehouse/environment "
            "before closing the action."
        ),
        "IMPACT_TELEMETRY_REQUIRED": "Yes" if "CREDIT" in signal else "No",
        "PRESSURE_EVIDENCE": (
            f"queued={queued:,}; spill={spill:,}; high_latency={high_latency:,}; "
            f"credit_spike={spike:,.1f}%; p95={p95:,.2f}s"
        ),
    }


def _annotate_warehouse_admin_readiness(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame() if exceptions is None else exceptions
    rows = []
    for _, row in exceptions.iterrows():
        rows.append(_warehouse_setting_candidate_for(row))
    readiness = pd.DataFrame(rows, index=exceptions.index)
    annotated = exceptions.copy()
    for column in readiness.columns:
        annotated[column] = readiness[column]
    return annotated


def _warehouse_setting_audit_readiness_for_row(row: pd.Series | dict) -> dict:
    """Score whether a warehouse setting change has review, execution, and telemetry status."""
    owner = str(row.get("OWNER") or "").strip()
    owner_source = str(row.get("OWNER_SOURCE") or "").upper()
    approver = str(row.get("APPROVER") or row.get("APPROVAL_GROUP") or "").strip()
    approval_required = str(row.get("APPROVAL_REQUIRED") or "Yes").upper() == "YES"
    rollback_required = str(row.get("ROLLBACK_REQUIRED") or "Yes").upper() == "YES"
    savings_required = str(row.get("IMPACT_TELEMETRY_REQUIRED") or "No").upper() == "YES"
    approval_state = str(row.get("APPROVAL_STATE") or row.get("OWNER_APPROVAL_STATUS") or "").upper()
    ticket_id = str(row.get("CHANGE_TICKET_ID") or row.get("TICKET_ID") or "").strip()
    rollback_sql = str(row.get("ROLLBACK_SQL") or "").strip()
    execution_status = str(row.get("EXECUTION_STATUS") or "Not Executed").upper()
    sql_hash = str(row.get("EXECUTED_SQL_HASH") or row.get("SQL_HASH") or "").strip()
    verification_status = str(
        row.get("POST_CHANGE_VERIFICATION_STATUS")
        or row.get("VERIFICATION_STATUS")
        or ""
    ).upper()
    verification_result = str(
        row.get("POST_CHANGE_VERIFICATION_RESULT")
        or row.get("VERIFICATION_RESULT")
        or ""
    ).strip()
    verified_savings = safe_float(row.get("VERIFIED_MONTHLY_SAVINGS"))

    blockers: list[str] = []
    generic_owners = {"", "DBA", "UNKNOWN", "N/A"}
    owner_route_ready = bool(owner) and owner.upper() not in generic_owners and bool(owner_source or approver)
    if not owner_route_ready:
        blockers.append("escalation route")
    if approval_required and approval_state not in {"APPROVED", "APPROVAL NOT REQUIRED", "NOT REQUIRED"}:
        blockers.append("review status")
    if not ticket_id:
        blockers.append("change ticket")
    if rollback_required and not rollback_sql:
        blockers.append("rollback SQL")

    executed = execution_status in {"SUCCESS", "EXECUTED", "COMPLETED"}
    failed = execution_status in {"FAILED", "ERROR"}
    if executed and not sql_hash:
        blockers.append("admin execution hash")
    if executed and (verification_status != "VERIFIED" or len(verification_result) < 15):
        blockers.append("post-change telemetry")
    if executed and savings_required and verified_savings <= 0:
        blockers.append("impact telemetry")

    route_blockers = {"escalation route"}
    pre_change_blockers = {"review status", "change ticket", "rollback SQL"}
    verification_blockers = {"admin execution hash", "post-change telemetry", "impact telemetry"}

    if failed:
        readiness = "Execution Failed"
        rank = 0
    elif any(item in route_blockers for item in blockers):
        readiness = "Route Metadata Blocked"
        rank = 1
    elif any(item in pre_change_blockers for item in blockers):
        readiness = "Pre-Change Blocked"
        rank = 2
    elif any(item in verification_blockers for item in blockers):
        readiness = "Telemetry Pending"
        rank = 3
    elif executed:
        readiness = "Change Audit Linked"
        rank = 8
    else:
        readiness = "Ready for Controlled Change"
        rank = 6

    if failed:
        next_action = "Open the failed admin audit row, correct the setting plan, and keep rollback status with the ticket."
    elif "escalation route" in blockers:
        next_action = "Add DBA escalation context before executing warehouse setting changes."
    elif "review status" in blockers:
        next_action = "Capture review status before running ALTER WAREHOUSE."
    elif "change ticket" in blockers:
        next_action = "Add the change ticket to the warehouse setting review."
    elif "rollback SQL" in blockers:
        next_action = "Generate and retain rollback SQL from the guarded warehouse settings workflow before execution."
    elif "post-change telemetry" in blockers:
        next_action = "Refresh queue/spill/credit telemetry before closure."
    elif "impact telemetry" in blockers:
        next_action = "Wait for measured impact telemetry before closing the credit-control change."
    elif executed:
        next_action = "Keep execution, rollback, and post-change telemetry with the audit trail."
    else:
        next_action = "Route through the guarded warehouse settings workflow for changed-only SQL and audit logging."

    return {
        "AUDIT_READINESS": readiness,
        "AUDIT_RANK": rank,
        "AUDIT_BLOCKERS": "; ".join(blockers) if blockers else "None",
        "OWNER_ROUTE_READY": "Yes" if owner_route_ready else "No",
        "NEXT_CONTROL_ACTION": next_action,
    }


def _warehouse_capacity_priority_view(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()
    rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    view = _annotate_warehouse_admin_readiness(exceptions)
    view["_RANK"] = view.get("SEVERITY", pd.Series(dtype=str)).map(rank).fillna(4)
    view["NEXT_ACTION"] = view.get("SIGNAL", pd.Series(dtype=str)).apply(lambda value: _warehouse_capacity_action_for(value)[0])
    view["NEXT_WORKFLOW"] = view.get("SIGNAL", pd.Series(dtype=str)).apply(_warehouse_capacity_workflow_for)
    return view.sort_values(["_RANK", "CAPACITY_SCORE", "METERED_CREDITS"], ascending=[True, True, False]).drop(columns=["_RANK"], errors="ignore")


def _warehouse_setting_control_board(
    exceptions: pd.DataFrame,
    owner_inventory: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    execution_audit: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Combine capacity findings, closure, and execution audit into one DBA board."""
    if exceptions is None or exceptions.empty:
        return pd.DataFrame()

    findings = _warehouse_capacity_priority_view(exceptions)
    if findings.empty:
        return pd.DataFrame()

    owners = pd.DataFrame() if owner_inventory is None else owner_inventory.copy()
    if not owners.empty:
        owners.columns = [str(col).upper() for col in owners.columns]
    closure_view = pd.DataFrame() if closure is None else closure.copy()
    if not closure_view.empty:
        closure_view.columns = [str(col).upper() for col in closure_view.columns]
    audit_view = pd.DataFrame() if execution_audit is None else execution_audit.copy()
    if not audit_view.empty:
        audit_view.columns = [str(col).upper() for col in audit_view.columns]

    owner_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in owners.iterrows()
    } if not owners.empty else {}
    closure_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in closure_view.iterrows()
    } if not closure_view.empty else {}
    audit_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in audit_view.iterrows()
    } if not audit_view.empty else {}

    rows: list[dict] = []
    for _, row in findings.iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "")
        wh_key = wh.upper()
        owner_row = owner_by_wh.get(wh_key, {})
        closure_row = closure_by_wh.get(wh_key, {})
        audit_row = audit_by_wh.get(wh_key, {})

        audit_readiness = _warehouse_setting_audit_readiness_for_row({
            **row.to_dict(),
            "APPROVAL_STATE": audit_row.get("APPROVAL_STATE", "Requested") if len(audit_row) else "Requested",
            "CHANGE_TICKET_ID": audit_row.get("CHANGE_TICKET_ID", ""),
            "ROLLBACK_SQL": audit_row.get("ROLLBACK_SQL", ""),
            "EXECUTION_STATUS": audit_row.get("LAST_EXECUTION_STATUS", audit_row.get("EXECUTION_STATUS", "Not Executed")),
            "EXECUTED_SQL_HASH": audit_row.get("LAST_SQL_HASH", audit_row.get("EXECUTED_SQL_HASH", "")),
            "POST_CHANGE_VERIFICATION_STATUS": audit_row.get("POST_CHANGE_VERIFICATION_STATUS", ""),
            "POST_CHANGE_VERIFICATION_RESULT": audit_row.get("POST_CHANGE_VERIFICATION_RESULT", ""),
            "VERIFIED_MONTHLY_SAVINGS": audit_row.get("VERIFIED_MONTHLY_SAVINGS", 0),
        })

        route_readiness = str(owner_row.get("ROUTE_READINESS") or "Monitoring")
        closure_readiness = str(closure_row.get("CLOSURE_READINESS") or "Details available when needed")
        closure_rank = safe_int(closure_row.get("CLOSURE_RANK", 9))
        overdue = safe_int(closure_row.get("OVERDUE_OPEN", 0))
        fixed_without_verification = safe_int(closure_row.get("FIXED_WITHOUT_VERIFICATION", 0))
        failed_changes = safe_int(audit_row.get("FAILED_CHANGES", 0))
        audit_rows = safe_int(audit_row.get("AUDIT_ROWS", 0))

        if overdue:
            state, rank = "Closure Overdue", 0
            next_action = "Escalate overdue warehouse capacity action before planning more setting changes."
        elif fixed_without_verification or closure_rank in {1, 2}:
            state, rank = "Closure Status Pending", 1
            next_action = str(closure_row.get("NEXT_ACTION") or "Reopen warehouse work or wait for telemetry to confirm closure.")
        elif audit_readiness["AUDIT_READINESS"] == "Route Metadata Blocked":
            state, rank = "Route Metadata Blocked", 2
            next_action = audit_readiness["NEXT_CONTROL_ACTION"]
        elif failed_changes:
            state, rank = "Execution Failed", 3
            next_action = "Review failed ALTER WAREHOUSE audit rows and confirm rollback or no-op state."
        elif audit_readiness["AUDIT_READINESS"] in {"Pre-Change Blocked", "Telemetry Pending"}:
            state, rank = audit_readiness["AUDIT_READINESS"], audit_readiness["AUDIT_RANK"]
            next_action = audit_readiness["NEXT_CONTROL_ACTION"]
        elif audit_rows:
            state, rank = "Execution Audit Linked", 7
            next_action = "Confirm post-change queue, spill, credit, and impact telemetry remains current."
        else:
            state, rank = "Ready for Controlled Change", 6
            next_action = "Open the guarded warehouse settings workflow, generate changed-only SQL, and keep rollback status current."

        rows.append({
            "CONTROL_STATE": state,
            "CONTROL_RANK": rank,
            "WAREHOUSE_NAME": wh,
            "SEVERITY": row.get("SEVERITY", ""),
            "SIGNAL": row.get("SIGNAL", ""),
            "CAPACITY_SCORE": safe_float(row.get("CAPACITY_SCORE")),
            "METERED_CREDITS": safe_float(row.get("METERED_CREDITS")),
            "OWNER": row.get("OWNER", ""),
            "ROUTE_READINESS": route_readiness,
            "AUDIT_READINESS": audit_readiness["AUDIT_READINESS"],
            "AUDIT_BLOCKERS": audit_readiness["AUDIT_BLOCKERS"],
            "CLOSURE_READINESS": closure_readiness,
            "OVERDUE_OPEN": overdue,
            "FIXED_WITHOUT_VERIFICATION": fixed_without_verification,
            "AUDIT_ROWS": audit_rows,
            "SUCCESSFUL_CHANGES": safe_int(audit_row.get("SUCCESSFUL_CHANGES", 0)),
            "FAILED_CHANGES": failed_changes,
            "LAST_EXECUTION_STATUS": audit_row.get("LAST_EXECUTION_STATUS", "Details available when needed"),
            "LAST_EXECUTED_AT": audit_row.get("LAST_EXECUTED_AT", ""),
            "APPROVAL_REQUIRED": row.get("APPROVAL_REQUIRED", "No"),
            "ROLLBACK_REQUIRED": row.get("ROLLBACK_REQUIRED", "Yes"),
            "IMPACT_TELEMETRY_REQUIRED": row.get("IMPACT_TELEMETRY_REQUIRED", "No"),
            "SETTING_CHANGE_CANDIDATE": row.get("SETTING_CHANGE_CANDIDATE", ""),
            "NEXT_CONTROL_ACTION": next_action,
        })

    return pd.DataFrame(rows).sort_values(
        ["CONTROL_RANK", "OVERDUE_OPEN", "FAILED_CHANGES", "CAPACITY_SCORE", "METERED_CREDITS"],
        ascending=[True, False, False, True, False],
    ).reset_index(drop=True)


def _build_warehouse_cost_control_posture(
    settings_inventory: pd.DataFrame | None,
    overview: pd.DataFrame | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build current warehouse suspend/resume posture from SHOW WAREHOUSES metadata."""
    columns = [
        "WAREHOUSE_NAME", "COST_CONTROL_STATE", "IDLE_RISK", "AUTO_SUSPEND_SEC",
        "AUTO_RESUME", "WAREHOUSE_SIZE", "STATE", "METERED_CREDITS",
        "RECOMMENDED_AUTO_SUSPEND_SEC", "RECOMMENDED_ACTION", "REVIEW_SQL",
        "POSTURE_RANK",
    ]
    settings = _warehouse_upper_frame(settings_inventory)
    if settings.empty:
        return {
            "warehouses": 0,
            "blocked": 0,
            "review": 0,
            "ready": 0,
            "overwatch_candidates": 0,
        }, pd.DataFrame(columns=columns)

    overview_by_wh = _warehouse_row_by_name(_warehouse_upper_frame(overview))
    rows: list[dict[str, object]] = []
    for _, row in settings.iterrows():
        wh_name = _warehouse_text(row.get("NAME") or row.get("WAREHOUSE_NAME"))
        if not wh_name:
            continue
        wh_key = wh_name.upper()
        suspend_value = row.get("AUTO_SUSPEND")
        auto_suspend = safe_int(suspend_value, -1) if _warehouse_setting_present(suspend_value) else None
        auto_resume = _warehouse_bool_setting(row.get("AUTO_RESUME"))
        overview_row = overview_by_wh.get(wh_key, {})
        metered = safe_float(overview_row.get("METERED_CREDITS"))
        recommended_suspend = 60 if wh_key in {"WH_ALFA_OVERWATCH", "WH_ALFA_OVERWATCH"} or "OVERWATCH" in wh_key else 300

        reasons: list[str] = []
        rank = 8
        if auto_suspend is None:
            state = "Data Missing"
            idle_risk = "Unknown"
            reasons.append("AUTO_SUSPEND was not available from SHOW WAREHOUSES.")
            rank = 4
        elif auto_suspend == 0:
            state = "Blocked"
            idle_risk = "Never suspends"
            reasons.append("AUTO_SUSPEND is disabled, so idle compute can continue burning credits.")
            rank = 0
        elif auto_suspend > 1000:
            state = "Needs Review"
            idle_risk = "Longer than current 1000s session timeout"
            reasons.append("AUTO_SUSPEND exceeds the current WH_ALFA_OVERWATCH session-timeout context.")
            rank = 1
        elif auto_suspend > 600:
            state = "Needs Review"
            idle_risk = "Over 10 minutes"
            reasons.append("AUTO_SUSPEND is above ten minutes; verify the cache/performance tradeoff is intentional.")
            rank = 2
        elif auto_suspend > 300:
            state = "Watch"
            idle_risk = "Over 5 minutes"
            reasons.append("AUTO_SUSPEND is conservative but may be high for DBA monitoring workloads.")
            rank = 5
        else:
            state = "Ready"
            idle_risk = "Bounded"
            reasons.append("AUTO_SUSPEND is inside the recommended DBA monitoring range.")

        if auto_resume is False:
            state = "Blocked"
            rank = min(rank, 0)
            reasons.append("AUTO_RESUME is disabled; operators may hit avoidable startup failures.")
        elif auto_resume is None:
            if state == "Ready":
                state = "Data Missing"
            rank = min(rank, 4)
            reasons.append("AUTO_RESUME was not available from SHOW WAREHOUSES.")

        if wh_key == "WH_ALFA_OVERWATCH":
            if state == "Ready":
                state = "Watch"
                rank = min(rank, 5)
            reasons.append("This is the current shared OVERWATCH warehouse; prefer idle guard plus short auto-suspend.")
        elif "OVERWATCH" in wh_key:
            reasons.append("This appears to be an OVERWATCH-dedicated warehouse; keep it small, auto-resuming, and fast-suspending.")

        if state == "Blocked":
            action = f"Review and set AUTO_SUSPEND={recommended_suspend}, AUTO_RESUME=TRUE, then monitor the next complete window."
        elif state in {"Needs Review", "Watch"}:
            action = f"Validate workload impact, then consider AUTO_SUSPEND={recommended_suspend} with AUTO_RESUME=TRUE."
        elif state == "Data Missing":
            action = "Reload warehouse metadata or verify role can see SHOW WAREHOUSES settings."
        else:
            action = "Keep current suspend/resume policy visible in warehouse cost-control reviews."

        rows.append({
            "WAREHOUSE_NAME": wh_name,
            "COST_CONTROL_STATE": state,
            "IDLE_RISK": idle_risk,
            "AUTO_SUSPEND_SEC": auto_suspend,
            "AUTO_RESUME": auto_resume,
            "WAREHOUSE_SIZE": row.get("WAREHOUSE_SIZE", ""),
            "STATE": row.get("STATE", ""),
            "METERED_CREDITS": metered,
            "RECOMMENDED_AUTO_SUSPEND_SEC": recommended_suspend,
            "RECOMMENDED_ACTION": " ".join(reasons + [action]),
            "REVIEW_SQL": _warehouse_cost_control_review_sql(wh_name, recommended_suspend),
            "POSTURE_RANK": rank,
        })

    if not rows:
        return {
            "warehouses": 0,
            "blocked": 0,
            "review": 0,
            "ready": 0,
            "overwatch_candidates": 0,
        }, pd.DataFrame(columns=columns)
    posture = pd.DataFrame(rows).sort_values(
        ["POSTURE_RANK", "METERED_CREDITS", "WAREHOUSE_NAME"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
    state_series = posture["COST_CONTROL_STATE"].astype(str)
    summary = {
        "warehouses": int(len(posture)),
        "blocked": int(state_series.eq("Blocked").sum()),
        "review": int(state_series.isin(["Needs Review", "Watch", "Data Missing"]).sum()),
        "ready": int(state_series.eq("Ready").sum()),
        "overwatch_candidates": int(posture["WAREHOUSE_NAME"].astype(str).str.upper().str.contains("OVERWATCH|WH_ALFA_OVERWATCH").sum()),
    }
    return summary, posture[columns]


def _build_warehouse_guardrail_coverage(
    overview: pd.DataFrame | None,
    owner_inventory: pd.DataFrame | None = None,
    setting_control: pd.DataFrame | None = None,
    settings_inventory: pd.DataFrame | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build an auto-derived warehouse guardrail board from loaded telemetry."""
    _ = owner_inventory
    overview_view = _warehouse_upper_frame(overview)
    control_view = _warehouse_upper_frame(setting_control)
    settings_view = _warehouse_upper_frame(settings_inventory)

    overview_by_wh = _warehouse_row_by_name(overview_view)
    settings_by_wh = _warehouse_row_by_name(settings_view, preferred_name_col="NAME")
    control_by_wh = _warehouse_row_by_name(control_view)

    warehouses = sorted(set(overview_by_wh) | set(settings_by_wh) | set(control_by_wh))
    if not warehouses:
        return {
            "warehouses": 0,
            "blocked": 0,
            "review": 0,
            "unknown": 0,
            "ready": 0,
            "score": 100,
        }, pd.DataFrame()

    spill_threshold = safe_float(THRESHOLDS.get("spill_warning_gb", 10), 10.0)
    rows: list[dict] = []

    for wh_key in warehouses:
        overview_row = overview_by_wh.get(wh_key, {})
        settings_row = settings_by_wh.get(wh_key, {})
        control_row = control_by_wh.get(wh_key, {})
        wh_name = (
            _warehouse_text(overview_row.get("WAREHOUSE_NAME"))
            or _warehouse_text(settings_row.get("NAME"))
            or _warehouse_text(control_row.get("WAREHOUSE_NAME"))
            or wh_key
        )

        metered = safe_float(
            overview_row.get("METERED_CREDITS", control_row.get("METERED_CREDITS", 0))
        )
        credit_delta = safe_float(overview_row.get("CREDIT_DELTA"))
        credit_delta_pct = safe_float(overview_row.get("CREDIT_DELTA_PCT"))
        queued = safe_float(overview_row.get("AVG_QUEUED_SEC"))
        spill = safe_float(overview_row.get("TOTAL_REMOTE_SPILL_GB"))
        p95 = safe_float(overview_row.get("P95_ELAPSED_SEC"))
        total_queries = safe_int(overview_row.get("TOTAL_QUERIES"))

        monitor_value, monitor_known = _warehouse_first_setting(
            settings_row,
            ("RESOURCE_MONITOR", "RESOURCE_MONITOR_NAME", "MONITOR_NAME"),
        )
        if not monitor_known:
            monitor_state = "Unknown"
            monitor_action = "Load warehouse metadata to verify resource monitor coverage."
            monitor_deduction = 10
        elif _warehouse_setting_present(monitor_value):
            monitor_state = "Ready"
            monitor_action = "Keep resource monitor assignment with the warehouse review."
            monitor_deduction = 0
        elif "OVERWATCH" in wh_key or wh_key == "WH_ALFA_OVERWATCH":
            monitor_state = "Blocked"
            monitor_action = "Assign WH_ALFA_OVERWATCH to WH_ALFA_OVERWATCH_RM before declaring release compute guarded."
            monitor_deduction = 28
        elif metered >= 50 or credit_delta > 0:
            monitor_state = "Review"
            monitor_action = "Review resource monitor assignment for this active or rising-cost warehouse."
            monitor_deduction = 16
        else:
            monitor_state = "Review"
            monitor_action = "Confirm whether this low-volume warehouse should share or receive a resource monitor."
            monitor_deduction = 12

        suspend_value, suspend_known = _warehouse_first_setting(settings_row, ("AUTO_SUSPEND",))
        if not suspend_known or not _warehouse_setting_present(suspend_value):
            suspend_state = "Unknown"
            suspend_action = "Load warehouse metadata to verify AUTO_SUSPEND."
            suspend_deduction = 10
        else:
            auto_suspend = safe_int(suspend_value, -1)
            if auto_suspend == 0:
                suspend_state = "Blocked" if metered > 0 else "Review"
                suspend_action = "Route AUTO_SUSPEND=0 through review and rollback status."
                suspend_deduction = 24 if metered > 0 else 14
            elif auto_suspend > 3600:
                suspend_state = "Review"
                suspend_action = "Review long auto-suspend against idle burn and service-level needs."
                suspend_deduction = 16
            elif auto_suspend > 600 and metered > 0:
                suspend_state = "Review"
                suspend_action = "Validate whether auto-suspend above ten minutes is intentional for this workload."
                suspend_deduction = 12
            else:
                suspend_state = "Ready"
                suspend_action = "AUTO_SUSPEND is inside the normal guardrail range."
                suspend_deduction = 0

        statement_timeout_value, statement_timeout_known = _warehouse_first_setting(
            settings_row,
            ("STATEMENT_TIMEOUT_IN_SECONDS", "STATEMENT_TIMEOUT"),
        )
        queued_timeout_value, queued_timeout_known = _warehouse_first_setting(
            settings_row,
            ("STATEMENT_QUEUED_TIMEOUT_IN_SECONDS", "STATEMENT_QUEUED_TIMEOUT"),
        )
        statement_timeout = None
        queued_timeout = None
        if not statement_timeout_known and not queued_timeout_known:
            timeout_state = "Unknown"
            timeout_action = "Load warehouse metadata to verify statement and queued timeout guardrails."
            timeout_deduction = 8
        else:
            statement_timeout = safe_int(statement_timeout_value, -1) if statement_timeout_known else -1
            queued_timeout = safe_int(queued_timeout_value, -1) if queued_timeout_known else -1
            timeout_risks = []
            if statement_timeout_known and statement_timeout == 0:
                timeout_risks.append("statement timeout is disabled")
            elif statement_timeout_known and statement_timeout > 14400:
                timeout_risks.append("statement timeout exceeds four hours")
            if queued_timeout_known and queued_timeout == 0 and queued > 0:
                timeout_risks.append("queued timeout is disabled while queue pressure exists")
            elif queued_timeout_known and queued_timeout > 3600 and queued > 0:
                timeout_risks.append("queued timeout exceeds one hour with queue pressure")
            if timeout_risks:
                timeout_state = "Review"
                timeout_action = "Review timeout settings before workload growth or capacity changes: " + "; ".join(timeout_risks) + "."
                timeout_deduction = 12 if queued > 0 or p95 > 60 else 8
            else:
                timeout_state = "Ready"
                timeout_action = "Statement and queued timeout guardrails are present for loaded metadata."
                timeout_deduction = 0

        control_state = str(control_row.get("CONTROL_STATE") or "").strip()
        audit_state = str(control_row.get("AUDIT_READINESS") or "").strip()
        if "Route Metadata Blocked" in {control_state, audit_state}:
            route_state = "Review"
            route_action = str(control_row.get("NEXT_CONTROL_ACTION") or "Add DBA escalation context before execution.")
            route_deduction = 4
        else:
            route_state = "Ready"
            route_action = "Escalation uses the loaded warehouse signal and DBA on-call context."
            route_deduction = 0

        pressure_reasons: list[str] = []
        if queued > 2:
            pressure_reasons.append(f"avg queue {queued:.1f}s")
        if spill > spill_threshold:
            pressure_reasons.append(f"remote spill {spill:.1f} GB")
        if p95 > 60:
            pressure_reasons.append(f"p95 {p95:.1f}s")
        if pressure_reasons:
            capacity_state = "Review"
            capacity_action = "Verify queue, spill, latency, and settings before changing warehouse capacity."
            capacity_deduction = 15
        elif total_queries:
            capacity_state = "Ready"
            capacity_action = "No loaded pressure signal crosses the warehouse review threshold."
            capacity_deduction = 0
        else:
            capacity_state = "Unknown"
            capacity_action = "Load warehouse overview data to verify pressure coverage."
            capacity_deduction = 6

        if credit_delta_pct > 50 or credit_delta >= 25:
            cost_state = "Review"
            cost_action = "Review credit delta and impact telemetry before changing cost-related settings."
            cost_deduction = 12
        elif metered > 0:
            cost_state = "Ready"
            cost_action = "Metering telemetry is loaded for this warehouse."
            cost_deduction = 0
        else:
            cost_state = "Unknown"
            cost_action = "Load warehouse metering telemetry before declaring cost guardrails covered."
            cost_deduction = 6

        states = [monitor_state, suspend_state, timeout_state, route_state, capacity_state, cost_state]
        if "Blocked" in states:
            guardrail_state = "Blocked"
            severity = "High"
            rank = 0
        elif "Review" in states:
            guardrail_state = "Needs Review"
            severity = "Medium"
            rank = 2
        elif "Unknown" in states:
            guardrail_state = "Data Missing"
            severity = "Medium"
            rank = 4
        else:
            guardrail_state = "Ready"
            severity = "Low"
            rank = 8

        deduction = (
            monitor_deduction
            + suspend_deduction
            + timeout_deduction
            + route_deduction
            + capacity_deduction
            + cost_deduction
        )
        score = max(0, 100 - deduction)
        next_actions = [
            action
            for state, action in [
                (monitor_state, monitor_action),
                (suspend_state, suspend_action),
                (timeout_state, timeout_action),
                (route_state, route_action),
                (capacity_state, capacity_action),
                (cost_state, cost_action),
            ]
            if state in {"Blocked", "Review", "Unknown"}
        ]
        evidence_parts = [
            f"resource_monitor={monitor_value if monitor_known else 'as needed'}",
            f"auto_suspend={suspend_value if suspend_known else 'as needed'}",
            f"statement_timeout={statement_timeout_value if statement_timeout_known else 'as needed'}",
            f"queued_timeout={queued_timeout_value if queued_timeout_known else 'as needed'}",
            f"route={control_state or 'DBA on-call'}",
            f"queued={queued:.2f}s",
            f"spill={spill:.2f} GB",
            f"p95={p95:.2f}s",
            f"credits={metered:.2f}",
            f"credit_delta={credit_delta:.2f}",
        ]

        rows.append({
            "WAREHOUSE_NAME": wh_name,
            "GUARDRAIL_STATE": guardrail_state,
            "GUARDRAIL_SCORE": score,
            "SEVERITY": severity,
            "RESOURCE_MONITOR_STATE": monitor_state,
            "RESOURCE_MONITOR": str(monitor_value or "") if monitor_known else "",
            "AUTO_SUSPEND_STATE": suspend_state,
            "AUTO_SUSPEND_SEC": auto_suspend if suspend_known else None,
            "TIMEOUT_STATE": timeout_state,
            "STATEMENT_TIMEOUT_SEC": statement_timeout,
            "QUEUED_TIMEOUT_SEC": queued_timeout,
            "ESCALATION_ROUTE_STATE": route_state,
            "CAPACITY_STATE": capacity_state,
            "COST_STATE": cost_state,
            "METERED_CREDITS": metered,
            "CREDIT_DELTA": credit_delta,
            "CREDIT_DELTA_PCT": credit_delta_pct,
            "AVG_QUEUED_SEC": queued,
            "TOTAL_REMOTE_SPILL_GB": spill,
            "P95_ELAPSED_SEC": p95,
            "PROOF_REQUIRED": "SHOW WAREHOUSES metadata, timeout settings, resource monitor assignment, metering, queue, spill, p95, and escalation route",
            "EVIDENCE": "; ".join(evidence_parts),
            "NEXT_ACTION": next_actions[0] if next_actions else "Guardrail coverage is ready for this warehouse.",
            "GUARDRAIL_RANK": rank,
        })

    board = pd.DataFrame(rows).sort_values(
        ["GUARDRAIL_RANK", "GUARDRAIL_SCORE", "METERED_CREDITS", "WAREHOUSE_NAME"],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)
    summary = {
        "warehouses": int(len(board)),
        "blocked": int(board["GUARDRAIL_STATE"].eq("Blocked").sum()),
        "review": int(board["GUARDRAIL_STATE"].eq("Needs Review").sum()),
        "unknown": int(board["GUARDRAIL_STATE"].eq("Data Missing").sum()),
        "ready": int(board["GUARDRAIL_STATE"].eq("Ready").sum()),
        "score": int(round(float(pd.to_numeric(board["GUARDRAIL_SCORE"], errors="coerce").fillna(0).mean()))),
    }
    return summary, board


def _warehouse_setting_action_plan(guardrail_board: pd.DataFrame | None) -> pd.DataFrame:
    """Return advisory setting moves from loaded guardrail coverage."""
    columns = [
        "PRIORITY", "WAREHOUSE_NAME", "ACTION_TYPE", "CURRENT_STATE", "CURRENT_SETTING",
        "SAFE_SETTING_MOVE", "WHY", "PROOF_REQUIRED", "ROLLBACK_CHECK", "REVIEW_SQL",
    ]
    if guardrail_board is None or getattr(guardrail_board, "empty", True):
        return pd.DataFrame(columns=columns)
    view = guardrail_board.copy()
    rows: list[dict[str, object]] = []

    def add_row(
        source: pd.Series,
        *,
        action_type: str,
        state_col: str,
        current_setting: str,
        safe_move: str,
        why: str,
        rollback_check: str,
    ) -> None:
        state = str(source.get(state_col) or "Unknown")
        if state not in {"Blocked", "Review", "Unknown"} and state != "Data Missing":
            return
        priority = "High" if state == "Blocked" else "Medium" if state in {"Review", "Unknown", "Data Missing"} else "Low"
        rows.append({
            "PRIORITY": priority,
            "WAREHOUSE_NAME": source.get("WAREHOUSE_NAME", "Unknown warehouse"),
            "ACTION_TYPE": action_type,
            "CURRENT_STATE": state,
            "CURRENT_SETTING": current_setting,
            "SAFE_SETTING_MOVE": safe_move,
            "WHY": why,
            "PROOF_REQUIRED": source.get("PROOF_REQUIRED", ""),
            "ROLLBACK_CHECK": rollback_check,
            "REVIEW_SQL": _warehouse_setting_review_sql(source.get("WAREHOUSE_NAME", ""), action_type),
            "_SORT": {"High": 0, "Medium": 1, "Low": 2}.get(priority, 9),
            "_SCORE": safe_float(source.get("GUARDRAIL_SCORE")),
            "_CREDITS": safe_float(source.get("METERED_CREDITS")),
        })

    for _, row in view.iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        add_row(
            row,
            action_type="Resource monitor coverage",
            state_col="RESOURCE_MONITOR_STATE",
            current_setting=str(row.get("RESOURCE_MONITOR") or "not loaded / not set"),
            safe_move="Assign or confirm a resource monitor before treating the warehouse as guarded.",
            why=f"{wh} cannot be considered cost-guarded without monitor coverage for active or rising usage.",
            rollback_check="Confirm monitor assignment in SHOW WAREHOUSES and verify no unexpected suspension events.",
        )
        add_row(
            row,
            action_type="Auto-suspend review",
            state_col="AUTO_SUSPEND_STATE",
            current_setting=str(row.get("AUTO_SUSPEND_SEC") if row.get("AUTO_SUSPEND_SEC") is not None else "not loaded"),
            safe_move="Review idle burn and workload latency, then test one conservative AUTO_SUSPEND change.",
            why=f"{wh} has auto-suspend coverage that needs DBA review before cost tuning.",
            rollback_check="Compare idle credits, p95 runtime, queue seconds, and failed queries after the next complete window.",
        )
        add_row(
            row,
            action_type="Timeout guardrail review",
            state_col="TIMEOUT_STATE",
            current_setting=(
                f"statement={row.get('STATEMENT_TIMEOUT_SEC') if row.get('STATEMENT_TIMEOUT_SEC') is not None else 'not loaded'}, "
                f"queued={row.get('QUEUED_TIMEOUT_SEC') if row.get('QUEUED_TIMEOUT_SEC') is not None else 'not loaded'}"
            ),
            safe_move="Set or confirm statement and queued timeout guardrails before workload growth.",
            why=f"{wh} needs timeout context so capacity changes do not mask runaway or queued workloads.",
            rollback_check="Verify queue failures, p95 runtime, and timeout errors stay inside the expected range.",
        )
        add_row(
            row,
            action_type="Capacity change review",
            state_col="CAPACITY_STATE",
            current_setting=(
                f"queue={safe_float(row.get('AVG_QUEUED_SEC')):,.1f}s, "
                f"spill={safe_float(row.get('TOTAL_REMOTE_SPILL_GB')):,.1f} GB, "
                f"p95={safe_float(row.get('P95_ELAPSED_SEC')):,.1f}s"
            ),
            safe_move="Inspect top query profiles before resizing, changing clusters, or enabling acceleration.",
            why=f"{wh} has loaded queue, spill, or latency pressure that may be query shape rather than warehouse size.",
            rollback_check="After any setting change, confirm credits, queue, remote spill, p95, and failures in the same workload window.",
        )
        add_row(
            row,
            action_type="Cost movement review",
            state_col="COST_STATE",
            current_setting=(
                f"credits={safe_float(row.get('METERED_CREDITS')):,.1f}, "
                f"delta={safe_float(row.get('CREDIT_DELTA')):+,.1f}"
            ),
            safe_move="Explain credit movement before changing suspend, size, or routing policy.",
            why=f"{wh} has material spend movement that should be separated from performance pressure.",
            rollback_check="Confirm the next completed window shows lower burn without higher queue, spill, or failure rates.",
        )

    if not rows:
        return pd.DataFrame(columns=columns)
    plan = pd.DataFrame(rows).sort_values(
        ["_SORT", "_SCORE", "_CREDITS", "WAREHOUSE_NAME", "ACTION_TYPE"],
        ascending=[True, True, False, True, True],
    )
    return plan[columns].reset_index(drop=True)


def _warehouse_setting_route(action_type: str) -> str:
    action = str(action_type or "").lower()
    if "capacity" in action or "cost movement" in action:
        return "Efficiency"
    if "timeout" in action or "auto-suspend" in action or "resource monitor" in action:
        return "Optimization Advisor"
    return "Overview & Scaling"


def _warehouse_setting_detail_options(plan: pd.DataFrame | None) -> pd.DataFrame:
    if plan is None or getattr(plan, "empty", True):
        return pd.DataFrame()
    view = plan.copy().reset_index(drop=True)
    view["DETAIL_LABEL"] = view.apply(
        lambda row: (
            f"{row.get('PRIORITY', 'Review')} | "
            f"{row.get('ACTION_TYPE', 'Setting review')} | "
            f"{row.get('WAREHOUSE_NAME', 'Unknown warehouse')}"
        ),
        axis=1,
    )
    view["WORKFLOW_ROUTE"] = view["ACTION_TYPE"].apply(_warehouse_setting_route)
    return view


def _warehouse_capacity_review_sql(row: pd.Series) -> str:
    candidate = row.get("SETTING_CHANGE_CANDIDATE") or _warehouse_setting_candidate_for(row)["SETTING_CHANGE_CANDIDATE"]
    safe_path = row.get("SAFE_CHANGE_PATH") or _warehouse_setting_candidate_for(row)["SAFE_CHANGE_PATH"]
    verification = row.get("POST_CHANGE_VERIFICATION") or _warehouse_setting_candidate_for(row)["POST_CHANGE_VERIFICATION"]
    return "\n".join([
        "-- Reviewed warehouse setting plan required.",
        "-- Do not execute a warehouse change from this advisory row.",
        f"-- Candidate: {candidate}",
        f"-- Safe path: {safe_path}",
        "-- Route through the guarded warehouse settings workflow for changed-only SQL, review, and rollback.",
        f"-- Closure telemetry: {verification}",
    ])


def _warehouse_intervention_matrix(
    exceptions: pd.DataFrame,
    control_board: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rank warehouses by whether DBAs can safely intervene now or need telemetry first."""
    priority = _warehouse_capacity_priority_view(exceptions)
    if priority.empty:
        return pd.DataFrame()

    control = control_board if isinstance(control_board, pd.DataFrame) else pd.DataFrame()
    closure_df = closure if isinstance(closure, pd.DataFrame) else pd.DataFrame()
    control_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in control.iterrows()
    } if not control.empty else {}
    closure_by_wh = {
        str(row.get("WAREHOUSE_NAME") or "").upper(): row
        for _, row in closure_df.iterrows()
    } if not closure_df.empty else {}

    rows: list[dict] = []
    for _, item in priority.head(25).iterrows():
        wh = str(item.get("WAREHOUSE_NAME") or "Unknown warehouse")
        control_row = control_by_wh.get(wh.upper(), {})
        closure_row = closure_by_wh.get(wh.upper(), {})
        signal = str(item.get("SIGNAL") or "")
        severity = str(item.get("SEVERITY") or "Medium")
        score = safe_float(item.get("CAPACITY_SCORE"))
        credits = safe_float(item.get("METERED_CREDITS"))
        queued = safe_int(item.get("QUEUED_QUERIES"))
        spill = safe_int(item.get("SPILL_QUERIES"))
        high_latency = safe_int(item.get("HIGH_LATENCY_QUERIES"))
        readiness = str(control_row.get("CONTROL_STATE") or item.get("ADMIN_READINESS") or "Review")
        closure_state = str(closure_row.get("CLOSURE_READINESS") or control_row.get("CLOSURE_READINESS") or "No recent action")
        savings_required = str(
            control_row.get("IMPACT_TELEMETRY_REQUIRED")
            or item.get("IMPACT_TELEMETRY_REQUIRED")
            or ""
        ).upper() == "YES"
        approval_required = str(
            control_row.get("APPROVAL_REQUIRED")
            or item.get("APPROVAL_REQUIRED")
            or ""
        ).upper() == "YES"
        audit_bad = any(token in readiness.upper() for token in ("BLOCK", "FAILED", "PENDING", "NO SETTING"))
        closure_bad = any(token in closure_state.upper() for token in ("OVERDUE", "WITHOUT VERIFICATION", "GAP"))

        if audit_bad or closure_bad or approval_required:
            state = "Telemetry Blocked"
            rank = 0
            decision = "Hold setting change until review, audit, rollback, and closure status are current."
        elif score < 65 or severity.upper() == "CRITICAL":
            state = "Intervene"
            rank = 1
            decision = "Run DBA setting review and monitor queue, spill, latency, and credit impact after the change."
        elif savings_required or credits > 0:
            state = "Cost Review"
            rank = 2
            decision = "Quantify credit delta and savings hypothesis before claiming optimization value."
        else:
            state = "Watch"
            rank = 4
            decision = "Monitor pressure; avoid touching settings without a stronger service or cost signal."

        rows.append({
            "DBA_PRIORITY": f"P{rank}",
            "INTERVENTION_STATE": state,
            "WAREHOUSE_NAME": wh,
            "SEVERITY": severity,
            "SIGNAL": signal,
            "CAPACITY_SCORE": score,
            "METERED_CREDITS": credits,
            "PRESSURE_EVIDENCE": f"queued={queued:,}; spill={spill:,}; p95/latency rows={high_latency:,}",
            "CONTROL_STATE": readiness,
            "CLOSURE_READINESS": closure_state,
            "NEXT_DECISION": decision,
            "PROOF_REQUIRED": "review status, rollback SQL, execution audit, post-change service/cost telemetry",
            "NEXT_WORKFLOW": str(item.get("NEXT_WORKFLOW") or _warehouse_capacity_workflow_for(signal)),
            "_RANK": rank,
        })

    return pd.DataFrame(rows).sort_values(
        ["_RANK", "CAPACITY_SCORE", "METERED_CREDITS"],
        ascending=[True, True, False],
    ).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _warehouse_setting_review_insert_sql(
    findings: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
    snapshot_id: str = "",
) -> str:
    if findings is None or findings.empty:
        raise ValueError("Warehouse setting review snapshot has no rows to save.")
    view = _annotate_warehouse_admin_readiness(findings)
    fqn = warehouse_setting_review_fqn()
    env_value = str(environment or "").strip() or "ALL"
    snap = snapshot_id or make_action_id(
        "Warehouse Setting Review Snapshot",
        company,
        f"{env_value}|{datetime.now().strftime('%Y%m%d%H%M%S')}",
    )
    selects = []
    for _, row in view.head(200).iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "")
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        review_sql = _warehouse_capacity_review_sql(row)
        approval_required = str(row.get("APPROVAL_REQUIRED", "Yes")).upper() == "YES"
        approval_state = str(row.get("APPROVAL_STATE") or ("Requested" if approval_required else "Not Required"))
        audit_fields = _warehouse_setting_audit_readiness_for_row({
            **row.to_dict(),
            "APPROVAL_STATE": approval_state,
            "CHANGE_TICKET_ID": row.get("CHANGE_TICKET_ID", ""),
            "CURRENT_SETTINGS_JSON": row.get("CURRENT_SETTINGS_JSON", ""),
            "PROPOSED_SETTINGS_JSON": row.get("PROPOSED_SETTINGS_JSON", row.get("SETTING_CHANGE_CANDIDATE", "")),
            "ROLLBACK_SQL": row.get("ROLLBACK_SQL", ""),
            "EXECUTED_SQL_HASH": row.get("EXECUTED_SQL_HASH", ""),
            "EXECUTION_STATUS": row.get("EXECUTION_STATUS", "Not Executed"),
            "POST_CHANGE_VERIFICATION_STATUS": row.get("POST_CHANGE_VERIFICATION_STATUS", "Pending"),
            "POST_CHANGE_VERIFICATION_RESULT": row.get("POST_CHANGE_VERIFICATION_RESULT", ""),
            "VERIFIED_MONTHLY_SAVINGS": row.get("VERIFIED_MONTHLY_SAVINGS", 0),
        })
        selects.append(
            "SELECT "
            f"{sql_literal(snap, 64)} AS SNAPSHOT_ID, "
            "CURRENT_TIMESTAMP() AS SNAPSHOT_TS, "
            f"{sql_literal(company, 100)} AS COMPANY, "
            f"{sql_literal(env_value, 100)} AS ENVIRONMENT, "
            f"{sql_literal(wh, 300)} AS WAREHOUSE_NAME, "
            f"{sql_literal(row.get('SEVERITY', ''), 40)} AS SEVERITY, "
            f"{sql_literal(row.get('SIGNAL', ''), 120)} AS SIGNAL, "
            f"{sql_literal(row.get('OWNER', ''), 200)} AS OWNER, "
            f"{sql_literal(row.get('ESCALATION_TARGET', ''), 200)} AS ESCALATION_TARGET, "
            f"{sql_literal(row.get('OWNER_SOURCE', ''), 200)} AS OWNER_SOURCE, "
            f"{sql_literal(row.get('APPROVER', ''), 200)} AS APPROVER, "
            f"{sql_literal(row.get('APPROVAL_REQUIRED', ''), 20)} AS APPROVAL_REQUIRED, "
            f"{sql_literal(row.get('ROLLBACK_REQUIRED', ''), 20)} AS ROLLBACK_REQUIRED, "
            f"{sql_literal(row.get('SAFE_CHANGE_PATH', ''), 4000)} AS SAFE_CHANGE_PATH, "
            f"{sql_literal(row.get('SETTING_CHANGE_CANDIDATE', ''), 4000)} AS SETTING_CHANGE_CANDIDATE, "
            f"{sql_literal(row.get('CHANGE_RISK', ''), 2000)} AS CHANGE_RISK, "
            f"{sql_literal(row.get('POST_CHANGE_VERIFICATION', ''), 2000)} AS POST_CHANGE_VERIFICATION, "
            f"{sql_literal(row.get('PRESSURE_EVIDENCE', ''), 2000)} AS PRESSURE_EVIDENCE, "
            f"{safe_float(row.get('CAPACITY_SCORE'))}::FLOAT AS BASELINE_CAPACITY_SCORE, "
            f"{safe_int(row.get('QUEUED_QUERIES'))}::NUMBER AS BASELINE_QUEUED_QUERIES, "
            f"{safe_int(row.get('SPILL_QUERIES'))}::NUMBER AS BASELINE_SPILL_QUERIES, "
            f"{safe_int(row.get('HIGH_LATENCY_QUERIES'))}::NUMBER AS BASELINE_HIGH_LATENCY_QUERIES, "
            f"{safe_float(row.get('P95_ELAPSED_SEC'))}::FLOAT AS BASELINE_P95_ELAPSED_SEC, "
            f"{safe_float(row.get('METERED_CREDITS'))}::FLOAT AS BASELINE_METERED_CREDITS, "
            f"{sql_literal(verification_sql, 8000)} AS VERIFICATION_QUERY, "
            f"{sql_literal(review_sql, 8000)} AS GENERATED_REVIEW_SQL, "
            f"{sql_literal(row.get('IMPACT_TELEMETRY_REQUIRED', ''), 20)} AS IMPACT_TELEMETRY_REQUIRED, "
            f"{sql_literal(approval_state, 80)} AS APPROVAL_STATE, "
            f"{sql_literal(row.get('CHANGE_TICKET_ID', ''), 200)} AS CHANGE_TICKET_ID, "
            f"{sql_literal(row.get('CURRENT_SETTINGS_JSON', ''), 8000)} AS CURRENT_SETTINGS_JSON, "
            f"{sql_literal(row.get('PROPOSED_SETTINGS_JSON', row.get('SETTING_CHANGE_CANDIDATE', '')), 8000)} AS PROPOSED_SETTINGS_JSON, "
            f"{sql_literal(row.get('ROLLBACK_SQL', ''), 8000)} AS ROLLBACK_SQL, "
            f"{sql_literal(row.get('EXECUTED_SQL_HASH', ''), 80)} AS EXECUTED_SQL_HASH, "
            f"{sql_literal(row.get('EXECUTION_STATUS', 'Not Executed'), 80)} AS EXECUTION_STATUS, "
            f"{sql_literal(row.get('EXECUTED_BY', ''), 200)} AS EXECUTED_BY, "
            "NULL::TIMESTAMP_NTZ AS EXECUTED_AT, "
            f"{sql_literal(row.get('POST_CHANGE_VERIFICATION_STATUS', 'Pending'), 80)} AS POST_CHANGE_VERIFICATION_STATUS, "
            f"{sql_literal(row.get('POST_CHANGE_VERIFICATION_RESULT', ''), 4000)} AS POST_CHANGE_VERIFICATION_RESULT, "
            f"{safe_float(row.get('VERIFIED_MONTHLY_SAVINGS'))}::FLOAT AS VERIFIED_MONTHLY_SAVINGS, "
            f"{sql_literal(audit_fields.get('AUDIT_READINESS', ''), 100)} AS AUDIT_READINESS, "
            f"{sql_literal(audit_fields.get('AUDIT_BLOCKERS', ''), 2000)} AS AUDIT_BLOCKERS, "
            f"{sql_literal(audit_fields.get('NEXT_CONTROL_ACTION', ''), 4000)} AS NEXT_CONTROL_ACTION, "
            f"{sql_literal(source, 500)} AS SOURCE"
        )
    return f"""
INSERT INTO {fqn} (
    SNAPSHOT_ID, SNAPSHOT_TS, COMPANY, ENVIRONMENT, WAREHOUSE_NAME, SEVERITY,
    SIGNAL, OWNER, ESCALATION_TARGET, OWNER_SOURCE, APPROVER, APPROVAL_REQUIRED,
    ROLLBACK_REQUIRED, SAFE_CHANGE_PATH, SETTING_CHANGE_CANDIDATE, CHANGE_RISK,
    POST_CHANGE_VERIFICATION, PRESSURE_EVIDENCE, BASELINE_CAPACITY_SCORE,
    BASELINE_QUEUED_QUERIES, BASELINE_SPILL_QUERIES, BASELINE_HIGH_LATENCY_QUERIES,
    BASELINE_P95_ELAPSED_SEC, BASELINE_METERED_CREDITS, VERIFICATION_QUERY,
    GENERATED_REVIEW_SQL, IMPACT_TELEMETRY_REQUIRED, APPROVAL_STATE,
    CHANGE_TICKET_ID, CURRENT_SETTINGS_JSON, PROPOSED_SETTINGS_JSON, ROLLBACK_SQL,
    EXECUTED_SQL_HASH, EXECUTION_STATUS, EXECUTED_BY, EXECUTED_AT,
    POST_CHANGE_VERIFICATION_STATUS, POST_CHANGE_VERIFICATION_RESULT,
    VERIFIED_MONTHLY_SAVINGS, AUDIT_READINESS, AUDIT_BLOCKERS, NEXT_CONTROL_ACTION,
    SOURCE
)
{" UNION ALL ".join(selects)}""".strip()
