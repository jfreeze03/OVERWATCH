"""Incident board, operator runbook, and escalation packet helpers."""
from __future__ import annotations

from datetime import datetime
from sections.shell_helpers import _clean_display_text
from utils.primitives import safe_float
from utils.primitives import safe_int
from .types import _empty_df, pd
from .queue import _canonical_dba_route, _command_queue_route_readiness, _dba_section_proof_required, _priority_exceptions




def _dba_incident_type(route: object, signal: object) -> str:
    route_text = str(route or "").upper()
    signal_text = str(signal or "").upper()
    text = f"{route_text} {signal_text}"
    if any(token in text for token in ("WAREHOUSE", "QUEUE", "SPILL", "CAPACITY", "LATENCY")):
        return "Warehouse Capacity"
    if any(token in text for token in ("CREDIT", "COST", "CORTEX", "AI")):
        return "Cost Runaway"
    if any(token in text for token in ("TASK", "PROCEDURE", "PIPELINE", "SLA", "REGRESSION")):
        return "Workload Reliability"
    if any(token in text for token in ("QUERY FAIL", "FAILED QUERY", "P95", "DURATION")):
        return "Query Reliability"
    if any(token in text for token in ("SECURITY", "LOGIN", "ACCESS", "GRANT", "ROLE")):
        return "Security / Access"
    if any(token in text for token in ("CHANGE", "DRIFT", "DDL", "OBJECT")):
        return "Change Control"
    if any(token in text for token in ("CLOSURE", "TELEMETRY", "STATUS")):
        return "Control Closure"
    if any(token in text for token in ("SOURCE", "STALE", "UNAVAILABLE", "MART")):
        return "Data Quality"
    return "DBA Operations"


def _dba_incident_rank(severity: object) -> int:
    return {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
        "INFO": 4,
    }.get(str(severity or "").upper(), 3)


def _dba_incident_sla_target(incident_type: object, severity: object) -> str:
    incident = str(incident_type or "").upper()
    rank = _dba_incident_rank(severity)
    if rank <= 0:
        return "Contain within 15 minutes; executive DBA update within 30 minutes."
    if rank == 1 and any(token in incident for token in ("SECURITY", "RELIABILITY", "CAPACITY")):
        return "Contain within 30 minutes; recovery or confirmed mitigation within 4 hours."
    if rank == 1:
        return "Contain same shift; current mitigation plan before handoff."
    if rank == 2:
        return "Triage same business day; queue action with route, due date, and telemetry."
    return "Monitor during next DBA review cycle."


def _dba_incident_containment_action(incident_type: object) -> str:
    incident = str(incident_type or "").upper()
    if "COST" in incident:
        return "Freeze broad scaling changes, identify top cost driver, and require review status before mitigation."
    if "WAREHOUSE" in incident:
        return "Stabilize queue/spill pressure first; route setting changes through Warehouse Settings Manager."
    if "WORKLOAD" in incident or "QUERY" in incident:
        return "Separate failing workload from platform issue, capture query/task telemetry, and protect downstream SLAs."
    if "SECURITY" in incident:
        return "Preserve telemetry, validate requester/reviewer, and avoid grant changes until escalation route is clear."
    if "CHANGE" in incident:
        return "Hold closure until ticket, query_id, review, rollback, and blast-radius status are current."
    if "CLOSURE" in incident:
        return "Reopen or block closure until telemetry, recovery, and review status are present."
    if "DATA" in incident or "TELEMETRY" in incident:
        return "Refresh summary/source telemetry before taking irreversible DBA action."
    return "Assign DBA on-call, capture telemetry, and route to the specialist workflow."


def _dba_incident_investigation_path(route: object, workflow: object = "") -> str:
    route_text = str(route or "DBA Control Room")
    workflow_text = str(workflow or "").strip()
    if workflow_text:
        return f"{route_text} -> {workflow_text}"
    return route_text


def _dba_incident_board(
    exceptions: pd.DataFrame | None,
    command_queue: pd.DataFrame | None,
    closure_rollup: pd.DataFrame | None,
    source_health: pd.DataFrame | None,
    *,
    max_rows: int = 10,
) -> pd.DataFrame:
    """Group loaded Control Room signals into incident-style operating lanes."""
    events: list[dict] = []

    source_exceptions = exceptions if exceptions is not None else _empty_df()
    if not source_exceptions.empty:
        for _, item in _priority_exceptions(source_exceptions).head(12).iterrows():
            route = _canonical_dba_route(item.get("Route") or item.get("ROUTE") or item.get("Domain") or "DBA Control Room")
            signal = str(item.get("Signal") or item.get("SIGNAL") or "Control-room signal")
            severity = str(item.get("Severity") or item.get("SEVERITY") or "Medium")
            incident_type = _dba_incident_type(route, signal)
            events.append({
                "INCIDENT_TYPE": incident_type,
                "ROUTE": route,
                "SEVERITY": severity,
                "SIGNAL": signal,
                "EVIDENCE": str(item.get("Evidence") or item.get("DETAIL") or signal),
                "WORKFLOW": str(item.get("Workflow") or ""),
                "OPEN_ACTIONS": 0,
                "OVERDUE": 0,
                "PROOF_BLOCKS": 0,
                "SOURCE_ISSUES": 0,
            })

    queue = command_queue if command_queue is not None else _empty_df()
    if not queue.empty:
        route_readiness = _command_queue_route_readiness(queue)
        for _, item in route_readiness.iterrows():
            route = str(item.get("ROUTE") or "DBA Control Room")
            open_actions = safe_int(item.get("OPEN_ACTIONS"))
            overdue = safe_int(item.get("OVERDUE"))
            proof_blocks = (
                safe_int(item.get("OWNER_GAPS"))
                + safe_int(item.get("APPROVAL_BLOCKS"))
                + safe_int(item.get("METADATA_BLOCKS"))
            )
            if not open_actions and not proof_blocks:
                continue
            severity = "High" if overdue or proof_blocks else "Medium"
            signal = "Action queue blockers" if proof_blocks else "Open action queue"
            events.append({
                "INCIDENT_TYPE": _dba_incident_type(route, signal),
                "ROUTE": route,
                "SEVERITY": severity,
                "SIGNAL": signal,
                "EVIDENCE": (
                    f"{open_actions:,} open; {overdue:,} overdue; "
                    f"{safe_int(item.get('EXECUTION_READY')):,} execution-ready; "
                    f"{proof_blocks:,} route/review/metadata blocks"
                ),
                "WORKFLOW": "",
                "OPEN_ACTIONS": open_actions,
                "OVERDUE": overdue,
                "PROOF_BLOCKS": proof_blocks,
                "SOURCE_ISSUES": 0,
            })

    closure = closure_rollup if closure_rollup is not None else _empty_df()
    if not closure.empty:
        closure_view = closure.copy()
        closure_view.columns = [str(col).upper() for col in closure_view.columns]
        blocked = closure_view[
            (pd.to_numeric(closure_view.get("CLOSURE_RANK", pd.Series([9] * len(closure_view))), errors="coerce").fillna(9) <= 3)
            | (pd.to_numeric(closure_view.get("CLOSURE_BLOCKER_ROWS", pd.Series([0] * len(closure_view))), errors="coerce").fillna(0) > 0)
        ]
        for _, item in blocked.iterrows():
            route = str(item.get("ROUTE") or "DBA Control Room")
            signal = str(item.get("CLOSURE_READINESS") or "Closure status blockers")
            overdue = safe_int(item.get("OVERDUE_OPEN"))
            proof_blocks = safe_int(item.get("CLOSURE_BLOCKER_ROWS"))
            events.append({
                "INCIDENT_TYPE": _dba_incident_type(route, signal),
                "ROUTE": route,
                "SEVERITY": "High" if overdue or safe_int(item.get("FIXED_WITHOUT_VERIFICATION")) else "Medium",
                "SIGNAL": signal,
                "EVIDENCE": (
                    f"{safe_int(item.get('OPEN_ACTIONS')):,} open; {overdue:,} overdue; "
                    f"{safe_int(item.get('FIXED_WITHOUT_VERIFICATION')):,} closed pending telemetry; "
                    f"{safe_int(item.get('RECOVERY_RISK_ROWS')):,} recovery-risk"
                ),
                "WORKFLOW": "Action Queue",
                "OPEN_ACTIONS": safe_int(item.get("OPEN_ACTIONS")),
                "OVERDUE": overdue,
                "PROOF_BLOCKS": proof_blocks,
                "SOURCE_ISSUES": 0,
            })

    sources = source_health if source_health is not None else _empty_df()
    if not sources.empty:
        source_view = sources.copy()
        source_view.columns = [str(col).upper() for col in source_view.columns]
        source_blocks = source_view[
            source_view.get("STATE", pd.Series([""] * len(source_view), index=source_view.index)).fillna("").astype(str).isin(["Unavailable", "Stale"])
        ]
        for _, item in source_blocks.iterrows():
            surface = str(item.get("SURFACE") or "Telemetry surface")
            state = str(item.get("STATE") or "Source issue")
            events.append({
                "INCIDENT_TYPE": "Data Quality",
                "ROUTE": "Data Health",
                "SEVERITY": "High" if state == "Unavailable" else "Medium",
                "SIGNAL": f"{surface} {state}",
                "EVIDENCE": f"{surface}; {state}; rows={safe_int(item.get('ROWS')):,}; scope={item.get('SCOPE', '')}",
                "WORKFLOW": "Data Health",
                "OPEN_ACTIONS": 0,
                "OVERDUE": 0,
                "PROOF_BLOCKS": 0,
                "SOURCE_ISSUES": 1,
            })

    if not events:
        return pd.DataFrame([{
            "INCIDENT_ID": "DBA-01",
            "INCIDENT_TYPE": "Routine Watch",
            "SEVERITY": "Low",
            "STATUS": "Monitor",
            "AFFECTED_ROUTES": "DBA Control Room",
            "SIGNALS": "No active incident signals",
            "EVIDENCE": "Loaded telemetry produced no exception, queue blocker, closure blocker, or stale data input.",
            "OPEN_ACTIONS": 0,
            "OVERDUE": 0,
            "PROOF_BLOCKS": 0,
            "SOURCE_ISSUES": 0,
            "CONTAINMENT_ACTION": "Keep fast snapshot current and monitor Alert Center.",
            "INVESTIGATION_PATH": "DBA Control Room",
            "SLA_TARGET": "Monitor during next DBA review cycle.",
            "PROOF_REQUIRED": "fresh Control Room load and Alert Center review",
        }])

    event_frame = pd.DataFrame(events)
    rows: list[dict] = []
    for (incident_type, route), group in event_frame.groupby(["INCIDENT_TYPE", "ROUTE"], dropna=False):
        severity_ranks = group["SEVERITY"].apply(_dba_incident_rank)
        worst_idx = severity_ranks.idxmin()
        severity = str(group.loc[worst_idx, "SEVERITY"])
        signals = "; ".join(dict.fromkeys(group["SIGNAL"].fillna("").astype(str).head(5)))
        evidence = " | ".join(dict.fromkeys(group["EVIDENCE"].fillna("").astype(str).head(4)))
        open_actions = int(pd.to_numeric(group["OPEN_ACTIONS"], errors="coerce").fillna(0).sum())
        overdue = int(pd.to_numeric(group["OVERDUE"], errors="coerce").fillna(0).sum())
        proof_blocks = int(pd.to_numeric(group["PROOF_BLOCKS"], errors="coerce").fillna(0).sum())
        source_issues = int(pd.to_numeric(group["SOURCE_ISSUES"], errors="coerce").fillna(0).sum())
        if overdue or proof_blocks:
            status = "Containment Required"
            rank = 0
        elif source_issues:
            status = "Telemetry Refresh Required"
            rank = 1
        elif _dba_incident_rank(severity) <= 1:
            status = "Investigate Now"
            rank = 2
        else:
            status = "Triage"
            rank = 4
        rows.append({
            "INCIDENT_TYPE": incident_type,
            "SEVERITY": severity,
            "STATUS": status,
            "STATUS_RANK": rank,
            "SEVERITY_RANK": _dba_incident_rank(severity),
            "AFFECTED_ROUTES": route,
            "SIGNALS": signals,
            "EVIDENCE": evidence,
            "OPEN_ACTIONS": open_actions,
            "OVERDUE": overdue,
            "PROOF_BLOCKS": proof_blocks,
            "SOURCE_ISSUES": source_issues,
            "CONTAINMENT_ACTION": _dba_incident_containment_action(incident_type),
            "INVESTIGATION_PATH": _dba_incident_investigation_path(route, group["WORKFLOW"].iloc[0]),
            "SLA_TARGET": _dba_incident_sla_target(incident_type, severity),
            "PROOF_REQUIRED": _dba_section_proof_required(route),
        })

    result = pd.DataFrame(rows).sort_values(
        ["STATUS_RANK", "SEVERITY_RANK", "OVERDUE", "PROOF_BLOCKS", "OPEN_ACTIONS", "INCIDENT_TYPE"],
        ascending=[True, True, False, False, False, True],
    ).head(max_rows).reset_index(drop=True)
    result.insert(0, "INCIDENT_ID", [f"DBA-{idx + 1:02d}" for idx in range(len(result))])
    return result.drop(columns=["STATUS_RANK", "SEVERITY_RANK"], errors="ignore")


def _dba_runbook_route_templates(section: object, lookback_hours: int) -> dict:
    """Return advisory-only route playbook templates for the top operations lane."""
    route = str(section or "").upper()
    hours = max(1, min(safe_int(lookback_hours, 24), 168))
    if "WAREHOUSE" in route:
        return {
            "owner_route": "Warehouse route / DBA capacity reviewer",
            "containment": "Use Cost & Contract to isolate the exact warehouse, workload, queue, spill, and dollar pattern before any setting change.",
            "candidate": "Use Warehouse Settings Manager only after review status is present; prefer the smallest targeted setting change with rollback SQL.",
            "preflight_sql": f"""SELECT warehouse_name, COUNT(*) AS queries,
       SUM(COALESCE(queued_overload_time, 0)) / 1000 AS queued_sec,
       SUM(COALESCE(bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3) AS remote_spill_gb,
       MAX(start_time) AS last_seen
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
GROUP BY warehouse_name
ORDER BY queued_sec DESC, remote_spill_gb DESC;""",
            "verification_sql": f"""SELECT warehouse_name, SUM(credits_used) AS credits_used,
       MAX(end_time) AS last_metered_hour
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
GROUP BY warehouse_name
ORDER BY credits_used DESC;""",
            "rollback_sql": "SHOW WAREHOUSES; -- Compare current settings to the reviewed before-change snapshot and rollback script.",
        }
    if "COST" in route:
        return {
            "owner_route": "Cost route / DBA cost reviewer",
            "containment": "Freeze savings claims; isolate top company, warehouse, database, role, user, and task driver before action.",
            "candidate": "Queue only the driver with route, baseline/current value, finance measurement basis, and telemetry query attached.",
            "preflight_sql": f"""SELECT warehouse_name, SUM(credits_used) AS credits_used,
       MAX(end_time) AS last_metered_hour
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
GROUP BY warehouse_name
ORDER BY credits_used DESC;""",
            "verification_sql": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY ORDER BY start_time DESC LIMIT 100;",
            "rollback_sql": "SELECT 'Rollback is business-process rollback: restore reviewed warehouse/task settings and keep finance status.' AS rollback_boundary;",
        }
    if "WORKLOAD" in route:
        return {
            "owner_route": "Workload route / DBA reliability reviewer",
            "containment": "Separate failing task, stored procedure, and query path from platform symptoms before retrying anything.",
            "candidate": "Retry or resume only after root cause, downstream blast radius, and last successful run are captured.",
            "preflight_sql": f"""SELECT name, state, scheduled_time, completed_time, error_code, error_message
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(SCHEDULED_TIME_RANGE_START=>DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())))
ORDER BY scheduled_time DESC
LIMIT 100;""",
            "verification_sql": f"""SELECT query_id, user_name, warehouse_name, execution_status, error_code,
       total_elapsed_time / 1000 AS elapsed_sec, start_time
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
ORDER BY start_time DESC
LIMIT 100;""",
            "rollback_sql": "SHOW TASKS IN ACCOUNT; -- Confirm suspended/resumed state against the reviewed recovery plan.",
        }
    if "SECURITY" in route:
        return {
            "owner_route": "Security reviewer / DBA access reviewer",
            "containment": "Preserve login/grant telemetry and avoid grant changes until requester, reviewer, and least-privilege status are clear.",
            "candidate": "Route grant/revoke work through Security Monitoring with ticket, reviewer, and before/after role telemetry.",
            "preflight_sql": f"""SELECT event_timestamp, user_name, client_ip, reported_client_type, error_code, error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
WHERE event_timestamp >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
ORDER BY event_timestamp DESC
LIMIT 100;""",
            "verification_sql": "SHOW GRANTS TO USERS; SHOW GRANTS TO ROLES;",
            "rollback_sql": "SELECT 'Rollback requires reviewed inverse GRANT/REVOKE script and post-change access telemetry.' AS rollback_boundary;",
        }
    if "CHANGE" in route:
        return {
            "owner_route": "Workload route / DBA operations reviewer",
            "containment": "Keep object remediation inside workload operations with source telemetry, impacted object context, and rollback boundary.",
            "candidate": "Queue the operational fix with dependency impact and rollback statement before marking it controlled.",
            "preflight_sql": f"""SELECT query_id, user_name, role_name, warehouse_name, database_name, schema_name,
       query_type, start_time, LEFT(query_text, 500) AS query_preview
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND (query_type ILIKE 'CREATE%' OR query_type ILIKE 'ALTER%' OR query_type ILIKE 'DROP%'
       OR query_type ILIKE 'GRANT%' OR query_type ILIKE 'REVOKE%')
ORDER BY start_time DESC
LIMIT 100;""",
            "verification_sql": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES LIMIT 100;",
            "rollback_sql": "SELECT 'Rollback must reference the reviewed operational recovery plan.' AS rollback_boundary;",
        }
    if "ALERT" in route:
        return {
            "owner_route": "Alert route / DBA on-call",
            "containment": "Confirm the alert source and route the issue to the action queue before suppressing or closing anything.",
            "candidate": "Suppress only with review status, expiry window, and a linked action queue item.",
            "preflight_sql": "SELECT CURRENT_TIMESTAMP() AS alert_review_started_at;",
            "verification_sql": "SELECT CURRENT_TIMESTAMP() AS alert_delivery_or_route_status_required;",
            "rollback_sql": "SELECT 'Rollback suppression by re-enabling the alert rule and documenting the reopened action.' AS rollback_boundary;",
        }
    if "ACCOUNT" in route:
        return {
            "owner_route": "Account hygiene route / DBA platform reviewer",
            "containment": "Prioritize hygiene gaps that affect authentication, ownership, recovery, or admin operability.",
            "candidate": "Queue account hygiene work with route, telemetry query, and closure status.",
            "preflight_sql": "SHOW USERS;",
            "verification_sql": "SHOW USERS; SHOW ROLES;",
            "rollback_sql": "SELECT 'Rollback account hygiene changes through reviewed identity/admin process.' AS rollback_boundary;",
        }
    return {
        "owner_route": "On-call DBA / platform route",
        "containment": "Assign DBA on-call, capture current telemetry, and route to the specialist workflow.",
        "candidate": "Work only the routed action with ticket, telemetry query, and closure status.",
        "preflight_sql": f"SELECT CURRENT_TIMESTAMP() AS preflight_started_at, {hours} AS lookback_hours;",
        "verification_sql": "SELECT CURRENT_TIMESTAMP() AS telemetry_required_at;",
        "rollback_sql": "SELECT 'Rollback boundary must be documented before execution.' AS rollback_boundary;",
    }


def _dba_template_route_for_signal(
    route: object,
    *,
    state: object = "",
    why_now: object = "",
    first_move: object = "",
    proof_required: object = "",
    source_signal: object = "",
    workflow: object = "",
) -> str:
    """Keep consolidated routes visible while preserving specialist ownership context."""
    route_text = _canonical_dba_route(route)
    context = " ".join(
        str(part or "")
        for part in (route, route_text, state, why_now, first_move, proof_required, source_signal, workflow)
    ).upper()
    if route_text == "Security Monitoring":
        if any(token in context for token in (
            "CHANGE",
            "DRIFT",
            "DDL",
            "DEPLOY",
            "RELEASE",
            "ROLLBACK",
            "MIGRATION",
            "OBJECT",
            "SCHEMA",
        )):
            return "Workload Operations"
        if any(token in context for token in (
            "PLATFORM",
            "TOPOLOGY",
            "ADOPTION",
            "CAPABILITY",
            "CLUSTERING",
            "CACHE",
            "DISASTER",
        )):
            return "Workload Operations"
        if any(token in context for token in (
            "SECURITY",
            "ACCESS",
            "GRANT",
            "ROLE",
            "LOGIN",
            "MFA",
            "PRIVILEGE",
            "MASKING",
            "ROW ACCESS",
            "SHARE",
        )):
            return "Security Posture"
    if route_text == "Cost & Contract" and any(token in context for token in (
        "WAREHOUSE",
        "CAPACITY",
        "QUEUE",
        "SPILL",
        "OVERLOAD",
        "SUSPEND",
        "RESIZE",
    )):
        return "Warehouse Health"
    return route_text


def _dba_operator_runbook(
    priority_index: pd.DataFrame | None,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
    generated_at: datetime | None = None,
) -> pd.DataFrame:
    """Build an advisory DBA runbook from the hottest operations route."""
    generated_at = generated_at or datetime.now()
    if priority_index is None or priority_index.empty:
        section = "DBA Control Room"
        hot = {
            "SECTION": section,
            "OPERATIONS_PRIORITY_STATE": "Monitor",
            "PRIORITY_SCORE": 0,
            "WHY_NOW": "No active operations priority row.",
            "FIRST_MOVE": "Keep fast snapshot current and review Alert Center.",
            "PROOF_REQUIRED": "fresh Control Room load and Alert Center review",
        }
    else:
        ordered = priority_index.sort_values("PRIORITY_SCORE", ascending=False) if "PRIORITY_SCORE" in priority_index.columns else priority_index
        hot = ordered.iloc[0].to_dict()
        section = str(hot.get("SECTION") or "DBA Control Room")
    templates = _dba_runbook_route_templates(section, lookback_hours)
    runbook_id = f"DBA-RUNBOOK-{generated_at.strftime('%Y%m%d%H%M')}"
    priority_score = safe_float(hot.get("PRIORITY_SCORE", 0))
    scope = f"{company} / {environment} / {safe_int(lookback_hours, 24)}h"
    stop_condition = (
        "Stop if telemetry is stale, route/ticket/status is missing, rollback is unclear, "
        "or telemetry cannot confirm before/after state."
    )
    stages = [
        (
            1,
            "Telemetry Check",
            "Telemetry current",
            f"Confirm operations route {section}, active scope, telemetry status, and impacted entity.",
            str(hot.get("WHY_NOW") or "Operations route selected."),
            templates["preflight_sql"],
        ),
        (
            2,
            "Containment",
            "No irreversible changes",
            str(hot.get("FIRST_MOVE") or templates["containment"]),
            templates["containment"],
            "",
        ),
        (
            3,
            "Review Gate",
            "Route and ticket present",
            "Add route, ticket/change ID, review group, and rollback boundary before controlled execution.",
            str(hot.get("PROOF_REQUIRED") or _dba_section_proof_required(section)),
            "",
        ),
        (
            4,
            "Execution Candidate",
            "Advisory only",
            templates["candidate"],
            "Baseline value, current value, telemetry status, and exact affected object or warehouse.",
            "SELECT 'Advisory only - execute through the guarded specialist workflow after review.' AS execution_boundary;",
        ),
        (
            5,
            "Telemetry Review",
            "Before/after telemetry required",
            "Refresh telemetry and record result text before closure or savings/recovery claim.",
            "Telemetry result, query_id, before/after metric, and route acknowledgement.",
            templates["verification_sql"],
        ),
        (
            6,
            "Rollback or Escalate",
            "Rollback path known",
            "If telemetry fails, rollback through reviewed path or escalate as an incident before handoff.",
            "Rollback statement/path, recovery status, reopened action queue item if needed.",
            templates["rollback_sql"],
        ),
    ]
    rows = []
    for rank, step, gate, move, evidence, proof_sql in stages:
        rows.append({
            "RUNBOOK_ID": runbook_id,
            "PHASE_RANK": rank,
            "RUNBOOK_STEP": step,
            "SECTION": section,
            "OPERATIONS_PRIORITY_STATE": str(hot.get("OPERATIONS_PRIORITY_STATE") or "Monitor"),
            "PRIORITY_SCORE": priority_score,
            "SCOPE": scope,
            "GO_NO_GO_GATE": gate,
            "DBA_MOVE": move,
            "EVIDENCE_REQUIRED": evidence,
            "PROOF_SQL": proof_sql,
            "STOP_CONDITION": stop_condition,
            "OWNER_ROUTE": templates["owner_route"],
            "RUNBOOK_MODE": "Advisory Only",
        })
    return pd.DataFrame(rows)


def _build_dba_operator_runbook_markdown(
    plan: pd.DataFrame,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
) -> str:
    """Create an exportable operator packet for the guided runbook."""
    rows = plan if plan is not None and not plan.empty else _empty_df()
    section = str(rows.iloc[0].get("SECTION")) if not rows.empty else "DBA Control Room"
    lines = [
        "# OVERWATCH DBA Operator Runbook",
        f"Route: {section}",
        f"Scope: {company} / {environment} / {safe_int(lookback_hours, 24)}h",
        "Mode: Review-only guidance",
        "",
    ]
    if rows.empty:
        lines.append("No runbook steps were available.")
    else:
        for _, row in rows.sort_values("PHASE_RANK").iterrows():
            proof = str(row.get("PROOF_SQL") or "").strip()
            lines.extend([
                f"## {safe_int(row.get('PHASE_RANK'))}. {row.get('RUNBOOK_STEP', '')}",
                f"Gate: {row.get('GO_NO_GO_GATE', '')}",
                f"Move: {row.get('DBA_MOVE', '')}",
                f"Telemetry: {row.get('EVIDENCE_REQUIRED', '')}",
                f"Escalation route: {_clean_display_text(row.get('OWNER_ROUTE', ''))}",
                f"Stop: {row.get('STOP_CONDITION', '')}",
            ])
            if proof:
                lines.extend(["", "```sql", proof, "```"])
            lines.append("")
    return "\n".join(lines).strip()


def _dba_escalation_priority_level(priority: float, state: object = "") -> str:
    text = str(state or "").upper()
    score = safe_float(priority)
    if score >= 90 or any(token in text for token in ("BLOCK", "CONTAIN", "OVERDUE")):
        return "Escalate Now"
    if score >= 70 or any(token in text for token in ("REFRESH", "INVESTIGATE", "HIGH")):
        return "Same Shift"
    if score >= 40 or any(token in text for token in ("REVIEW", "APPROVAL", "TRIAGE")):
        return "Route Review"
    return "Monitor"


def _dba_escalation_go_no_go(level: str, source_signals: list[str]) -> str:
    signal_text = " ".join(source_signals).upper()
    level_text = str(level or "").upper()
    if "ESCALATE" in level_text or "RELEASE GATE" in signal_text:
        return "No-Go until blocker telemetry is current."
    if "SOURCE HEALTH" in signal_text or "EVIDENCE" in signal_text:
        return "No-Go for irreversible action until telemetry is refreshed."
    if "SAME SHIFT" in level_text:
        return "Go only through the owning specialist workflow."
    return "Go for monitoring and normal DBA review."


def _dba_escalation_packet(
    priority_index: pd.DataFrame | None,
    incident_board: pd.DataFrame | None,
    handoff_rows: pd.DataFrame | None,
    release_gate: pd.DataFrame | None = None,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
    max_rows: int = 8,
) -> pd.DataFrame:
    """Merge loaded Control Room signals into owner-facing escalation rows."""
    rows_by_route: dict[str, dict] = {}
    hours = max(1, min(safe_int(lookback_hours, 24), 168))
    scope = f"{company} / {environment} / {hours}h"

    def upsert(
        route: object,
        *,
        priority: float,
        state: object,
        why_now: object,
        first_move: object,
        proof_required: object,
        source_signal: object,
        sla_target: object = "",
        workflow: object = "",
    ) -> None:
        route_text = _canonical_dba_route(route)
        key = route_text.upper()
        source_text = str(source_signal or "").strip()
        template_route = _dba_template_route_for_signal(
            route_text,
            state=state,
            why_now=why_now,
            first_move=first_move,
            proof_required=proof_required,
            source_signal=source_text,
            workflow=workflow,
        )
        templates = _dba_runbook_route_templates(template_route, hours)
        incoming_priority = safe_float(priority)
        current = rows_by_route.get(key)
        if current is None:
            rows_by_route[key] = {
                "ROUTE": route_text,
                "PRIORITY_SCORE": incoming_priority,
                "STATE": str(state or "Review"),
                "WHY_NOW": str(why_now or "Loaded Control Room telemetry requires DBA review."),
                "FIRST_MOVE": str(first_move or "Open the guarded drilldown workflow and validate telemetry."),
                "PROOF_REQUIRED": str(proof_required or _dba_section_proof_required(route_text)),
                "OWNER_ROUTE": templates["owner_route"],
                "SCOPE": scope,
                "SOURCE_SIGNALS_LIST": [source_text] if source_text else [],
                "SLA_TARGET": str(sla_target or _dba_incident_sla_target(_dba_incident_type(route_text, state), "Medium")),
                "WORKFLOW": str(workflow or route_text),
            }
            return

        if source_text and source_text not in current["SOURCE_SIGNALS_LIST"]:
            current["SOURCE_SIGNALS_LIST"].append(source_text)
        if incoming_priority > safe_float(current.get("PRIORITY_SCORE")):
            current["PRIORITY_SCORE"] = incoming_priority
            current["STATE"] = str(state or current.get("STATE") or "Review")
            current["WHY_NOW"] = str(why_now or current.get("WHY_NOW") or "")
            current["FIRST_MOVE"] = str(first_move or current.get("FIRST_MOVE") or "")
            current["PROOF_REQUIRED"] = str(proof_required or current.get("PROOF_REQUIRED") or _dba_section_proof_required(route_text))
            current["OWNER_ROUTE"] = templates["owner_route"]
            current["SLA_TARGET"] = str(sla_target or current.get("SLA_TARGET") or "")
            current["WORKFLOW"] = str(workflow or current.get("WORKFLOW") or route_text)

    priority = priority_index.copy() if priority_index is not None and not priority_index.empty else _empty_df()
    if not priority.empty:
        priority.columns = [str(col).upper() for col in priority.columns]
        for _, item in priority.iterrows():
            route = str(item.get("SECTION") or "DBA Control Room")
            upsert(
                route,
                priority=safe_float(item.get("PRIORITY_SCORE")),
                state=item.get("OPERATIONS_PRIORITY_STATE") or "Operations Priority",
                why_now=item.get("WHY_NOW") or item.get("WORST_SIGNAL"),
                first_move=item.get("FIRST_MOVE") or item.get("SECTION_NEXT_ACTION"),
                proof_required=item.get("PROOF_REQUIRED"),
                source_signal=f"Operations Priority: {item.get('WORST_SIGNAL') or item.get('WHY_NOW') or route}",
                workflow=route,
            )

    incidents = incident_board.copy() if incident_board is not None and not incident_board.empty else _empty_df()
    if not incidents.empty:
        incidents.columns = [str(col).upper() for col in incidents.columns]
        status_points = {
            "CONTAINMENT REQUIRED": 98,
            "EVIDENCE REFRESH REQUIRED": 86,
            "INVESTIGATE NOW": 78,
            "TRIAGE": 52,
            "MONITOR": 10,
        }
        for _, item in incidents.iterrows():
            route = str(item.get("AFFECTED_ROUTES") or item.get("ROUTE") or "DBA Control Room")
            status = str(item.get("STATUS") or "Incident Review")
            severity = str(item.get("SEVERITY") or "Medium")
            priority = max(
                safe_float(item.get("PRIORITY_SCORE")),
                status_points.get(status.upper(), 50),
                92 if severity.upper() == "CRITICAL" else 82 if severity.upper() == "HIGH" else 50,
            )
            upsert(
                route,
                priority=priority,
                state=status,
                why_now=item.get("SIGNALS") or item.get("INCIDENT_TYPE"),
                first_move=item.get("CONTAINMENT_ACTION"),
                proof_required=item.get("PROOF_REQUIRED"),
                source_signal=f"Incident Detail: {item.get('INCIDENT_ID', '')} {item.get('INCIDENT_TYPE', '')}".strip(),
                sla_target=item.get("SLA_TARGET"),
                workflow=item.get("INVESTIGATION_PATH") or route,
            )

    releases = release_gate.copy() if release_gate is not None and not release_gate.empty else _empty_df()
    if not releases.empty:
        releases.columns = [str(col).upper() for col in releases.columns]
        state_rank = {"BLOCKED": 99, "REVIEW": 74, "NOT LOADED": 58, "READY": 0, "DEFERRED": 35}
        gated = releases[
            releases.get("STATE", pd.Series([""] * len(releases), index=releases.index))
            .fillna("")
            .astype(str)
            .str.upper()
            .isin(["BLOCKED", "REVIEW", "NOT LOADED", "DEFERRED"])
        ]
        for _, item in gated.iterrows():
            route = _canonical_dba_route(item.get("ROUTE") or "DBA Control Room")
            state = str(item.get("STATE") or "Operations Review")
            upsert(
                route,
                priority=state_rank.get(state.upper(), 50),
                state=f"Operational Status {state}",
                why_now=item.get("EVIDENCE") or item.get("GATE"),
                first_move=item.get("NEXT_ACTION"),
                proof_required=item.get("PROOF_REQUIRED"),
                source_signal=f"Operational Status: {item.get('GATE', '')}".strip(),
                sla_target="Block production change until telemetry is current.",
                workflow=item.get("WORKFLOW") or route,
            )

    handoff = handoff_rows.copy() if handoff_rows is not None and not handoff_rows.empty else _empty_df()
    if not handoff.empty:
        handoff.columns = [str(col).upper() for col in handoff.columns]
        important = handoff[pd.to_numeric(handoff.get("PRIORITY_RANK", pd.Series([9] * len(handoff))), errors="coerce").fillna(9) <= 2]
        for _, item in important.iterrows():
            route = str(item.get("LANE") or "DBA Control Room")
            rank = safe_int(item.get("PRIORITY_RANK"), 3)
            upsert(
                route,
                priority=max(40, 84 - rank * 12),
                state=item.get("STATE") or "Shift Handoff",
                why_now=item.get("EVIDENCE"),
                first_move=item.get("NEXT_ACTION"),
                proof_required=item.get("PROOF_REQUIRED"),
                source_signal=f"Shift Handoff: {item.get('SOURCE', '')}".strip(),
                workflow=item.get("OWNER_OR_ROUTE") or route,
            )

    if not rows_by_route:
        upsert(
            "DBA Control Room",
            priority=0,
            state="Monitor",
            why_now="No loaded escalation signals.",
            first_move="Keep Fast Watch current and review Alert Center for newly routed issues.",
            proof_required="fresh Control Room load and current Alert Center review",
            source_signal="Escalation Packet: routine watch",
            workflow="DBA Control Room",
        )

    result_rows: list[dict] = []
    for row in rows_by_route.values():
        signals = row.pop("SOURCE_SIGNALS_LIST", [])
        level = _dba_escalation_priority_level(row.get("PRIORITY_SCORE"), row.get("STATE"))
        row["ESCALATION_LEVEL"] = level
        row["GO_NO_GO"] = _dba_escalation_go_no_go(level, signals)
        row["SOURCE_SIGNALS"] = "; ".join(signals) if signals else "Control Room"
        row["EVIDENCE_PACKET"] = (
            f"{row.get('WHY_NOW', '')} | First move: {row.get('FIRST_MOVE', '')} | "
            f"Telemetry basis: {row.get('PROOF_REQUIRED', '')}"
        )
        row["AUTO_GENERATED"] = "Yes"
        result_rows.append(row)

    result = pd.DataFrame(result_rows).sort_values(
        ["PRIORITY_SCORE", "ROUTE"],
        ascending=[False, True],
    ).head(max_rows).reset_index(drop=True)
    result.insert(0, "ESCALATION_ID", [f"ESC-{idx + 1:02d}" for idx in range(len(result))])
    return result[
        [
            "ESCALATION_ID", "ESCALATION_LEVEL", "ROUTE", "OWNER_ROUTE", "SCOPE",
            "PRIORITY_SCORE", "STATE", "WHY_NOW", "FIRST_MOVE", "PROOF_REQUIRED",
            "SLA_TARGET", "GO_NO_GO", "SOURCE_SIGNALS", "EVIDENCE_PACKET",
            "WORKFLOW", "AUTO_GENERATED",
        ]
    ]


def _build_dba_escalation_packet_markdown(
    packet: pd.DataFrame,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
) -> str:
    """Create an operator-facing escalation packet from generated escalation rows."""
    rows = packet if packet is not None and not packet.empty else _empty_df()
    lines = [
        "# OVERWATCH DBA Escalation Packet",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Scope: {company} / {environment} / {safe_int(lookback_hours, 24)}h",
        "Mode: Auto-generated from loaded OVERWATCH telemetry",
        "",
        "## Escalations",
    ]
    if rows.empty:
        lines.append("- No escalation rows were available.")
    else:
        for _, row in rows.iterrows():
            route = _clean_display_text(row.get("ROUTE", ""))
            owner_route = _clean_display_text(row.get("OWNER_ROUTE", ""))
            why_now = _clean_display_text(row.get("WHY_NOW", ""))
            first_move = _clean_display_text(row.get("FIRST_MOVE", ""))
            gate = _clean_display_text(row.get("GO_NO_GO", ""))
            telemetry_basis = _clean_display_text(row.get("PROOF_REQUIRED", ""))
            lines.append(
                f"- {row.get('ESCALATION_ID', '')} [{row.get('ESCALATION_LEVEL', '')}] "
                f"{route} -> {owner_route}. "
                f"Why: {why_now}. "
                f"Move: {first_move}. "
                f"Gate: {gate}. "
                f"Telemetry basis: {telemetry_basis}."
            )
    lines.extend([
        "",
        "## Escalation Rules",
        "- Do not execute state-changing DBA actions from this packet alone.",
        "- Use the guarded drilldown workflow for action, rollback, and telemetry review.",
        "- Treat deployment-review and telemetry-input blockers as No-Go until telemetry is refreshed.",
    ])
    return "\n".join(lines).strip()


def _build_dba_incident_markdown(
    incident_board: pd.DataFrame,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
    source_mode: str,
) -> str:
    rows = incident_board if incident_board is not None and not incident_board.empty else _empty_df()
    lines = [
        "# OVERWATCH DBA Incident Detail",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Scope: {company} / {environment}",
        f"Lookback: {int(lookback_hours)} hours",
        f"Source mode: {source_mode}",
        "",
        "## Active Incidents",
    ]
    if rows.empty:
        lines.append("- No incident rows were available.")
    else:
        for _, row in rows.iterrows():
            incident_type = _clean_display_text(row.get("INCIDENT_TYPE", ""))
            affected_routes = _clean_display_text(row.get("AFFECTED_ROUTES", ""))
            signals = _clean_display_text(row.get("SIGNALS", ""))
            telemetry = _clean_display_text(row.get("EVIDENCE", ""))
            containment = _clean_display_text(row.get("CONTAINMENT_ACTION", ""))
            sla_target = _clean_display_text(row.get("SLA_TARGET", ""))
            telemetry_basis = _clean_display_text(row.get("PROOF_REQUIRED", ""))
            lines.append(
                f"- {row.get('INCIDENT_ID', '')} [{row.get('SEVERITY', '')} / {row.get('STATUS', '')}] "
                f"{incident_type} on {affected_routes}: {signals}. "
                f"Telemetry: {telemetry}. "
                f"Containment: {containment}. "
                f"SLA: {sla_target}. "
                f"Telemetry basis: {telemetry_basis}."
            )
    lines.extend([
        "",
        "## Operating Rules",
        "- Containment comes before optimization or permanent configuration changes.",
        "- Do not close an incident until telemetry status is present in the action queue or change record.",
        "- Refresh stale or unavailable telemetry before taking irreversible DBA action.",
    ])
    return "\n".join(lines)
