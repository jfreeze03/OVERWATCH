"""Account Health checklist, routing, and operating-board helpers."""
from __future__ import annotations

import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA
from sections.account_health_common import _canonical_account_route
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.shell_helpers import render_shell_status_strip
from utils.primitives import safe_float, safe_int


pd = lazy_pandas()

resolve_owner_context = _lazy_util("resolve_owner_context")
safe_identifier = _lazy_util("safe_identifier")
sql_literal = _lazy_util("sql_literal")


def _mart_health_label(score: float) -> str:
    if score >= 90:
        return "Healthy"
    if score >= 75:
        return "Watch"
    if score >= 60:
        return "Degraded"
    return "Critical"

def _check_status(ok: bool, watch: bool = False) -> str:
    if ok:
        return "OK"
    if watch:
        return "Watch"
    return "Needs DBA"

def _account_health_owner_entity_type(check: object, route: object = "") -> str:
    text = f"{check or ''} {route or ''}".lower()
    if "cost" in text:
        return "COST_CONTROL"
    if "task" in text or "procedure" in text:
        return "TASK"
    if "warehouse" in text or "queue" in text:
        return "WAREHOUSE"
    if "change" in text or "drift" in text:
        return "CHANGE_CONTROL"
    if "security" in text or "grant" in text:
        return "SECURITY"
    return "ACCOUNT_HEALTH"

def _account_health_owner_context(check: object, route: object = "") -> dict:
    name = str(check or "").lower()
    route_text = str(route or "")
    if "query failure" in name:
        base = {
            "owner": "DBA Query Triage",
            "escalation": "Application Route / DBA On-Call",
            "source": "Checklist route map",
        }
    elif "queue pressure" in name:
        base = {
            "owner": "Platform DBA",
            "escalation": "Warehouse Route / DBA On-Call",
            "source": "Checklist route map",
        }
    elif "cost spike" in name:
        base = {
            "owner": "DBA / Cost owner Route",
            "escalation": "Cost owner",
            "source": "Checklist route map",
        }
    elif "task" in name or "procedure" in name:
        base = {
            "owner": "Data Engineering On-Call",
            "escalation": "Pipeline Route / DBA On-Call",
            "source": "Checklist route map",
        }
    elif "change" in name or "drift" in name:
        base = {
            "owner": "DBA Change Route",
            "escalation": "Security Route / Data Stewardship",
            "source": "Checklist route map",
        }
    elif "storage" in name or "monitor" in name:
        base = {
            "owner": "Platform DBA",
            "escalation": "DBA Lead",
            "source": "Checklist route map",
        }
    elif "source readiness" in name or "source confidence" in name:
        base = {
            "owner": "OVERWATCH Platform Route",
            "escalation": "DBA Lead",
            "source": "Checklist route map",
        }
    else:
        base = {
            "owner": "DBA Lead" if route_text == "DBA Control Room" else "DBA",
            "escalation": "DBA Lead",
            "source": "Default DBA team",
        }

    directory_context = resolve_owner_context(
        {
            "ENTITY_NAME": check,
            "CATEGORY": route_text or "Daily DBA Checklist",
            "OWNER": base["owner"],
        },
        entity=check,
        entity_type=_account_health_owner_entity_type(check, route),
        owner=base["owner"],
        category=route_text or "Daily DBA Checklist",
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

def _enrich_account_health_checklist_owners(checklist: pd.DataFrame) -> pd.DataFrame:
    if checklist is None or checklist.empty:
        return checklist
    view = checklist.copy()
    contexts = view.apply(lambda row: _account_health_owner_context(row.get("CHECK"), row.get("ROUTE")), axis=1)
    view["OWNER"] = contexts.apply(lambda item: item["owner"])
    view["ESCALATION_TARGET"] = contexts.apply(lambda item: item["escalation"])
    view["OWNER_SOURCE"] = contexts.apply(lambda item: item["source"])
    view["OWNER_EMAIL"] = contexts.apply(lambda item: item.get("owner_email", ""))
    view["ONCALL_PRIMARY"] = contexts.apply(lambda item: item.get("oncall_primary", ""))
    view["ONCALL_SECONDARY"] = contexts.apply(lambda item: item.get("oncall_secondary", ""))
    view["APPROVAL_GROUP"] = contexts.apply(lambda item: item.get("approval_group", ""))
    view["OWNER_EVIDENCE"] = contexts.apply(lambda item: item.get("owner_evidence", ""))
    return view

def _build_account_health_dba_checklist(
    *,
    health_score: float,
    score_label: str,
    err_count: int,
    queued: int,
    pct_delta: float,
    last24: float,
    stor_tb: float,
    failed_tasks: int = 0,
    object_changes: int = 0,
    control_mart_used: bool = False,
    detail_source: str = "",
) -> pd.DataFrame:
    """Convert the broad account snapshot into a daily DBA operating checklist."""
    score = safe_float(health_score)
    failures = safe_int(err_count)
    queued_count = safe_int(queued)
    failed_task_count = safe_int(failed_tasks)
    change_count = safe_int(object_changes)
    delta = safe_float(pct_delta)
    rows = [
        {
            "CHECK": "Refresh source readiness",
            "STATUS": "OK" if control_mart_used else "Verify source",
            "SEVERITY": "Low" if control_mart_used else "Medium",
            "EVIDENCE": detail_source or ("Fast summary" if control_mart_used else "Current account telemetry"),
            "OWNER": "DBA",
            "ROUTE": "DBA Control Room",
            "NEXT_ACTION": "Use the latest telemetry snapshot for morning control; document source state before acting.",
            "PROOF_REQUIRED": "Snapshot timestamp or source-state note",
        },
        {
            "CHECK": "Query failure review",
            "STATUS": _check_status(failures == 0, failures <= 10),
            "SEVERITY": "High" if failures > 10 else ("Medium" if failures > 0 else "Info"),
            "EVIDENCE": f"{failures:,} failed queries in last 24h",
            "OWNER": "DBA / App Owner",
            "ROUTE": "Workload Operations",
            "NEXT_ACTION": "Open Query Investigation, group repeat error signatures, and queue recurring failures.",
            "PROOF_REQUIRED": "query_id, error code/message, affected user/warehouse",
        },
        {
            "CHECK": "Queue pressure review",
            "STATUS": _check_status(queued_count == 0, queued_count <= 5),
            "SEVERITY": "High" if queued_count > 20 else ("Medium" if queued_count > 0 else "Info"),
            "EVIDENCE": f"{queued_count:,} queued/running pressure signals",
            "OWNER": "DBA / Platform",
            "ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Confirm whether pressure is sizing, concurrency, lock, or workload-shape driven before changing warehouses.",
            "PROOF_REQUIRED": "warehouse, queued time, query count, before/after setting",
        },
        {
            "CHECK": "Cost spike review",
            "STATUS": _check_status(delta <= 20, delta <= 40),
            "SEVERITY": "High" if delta > 60 else ("Medium" if delta > 20 else "Info"),
            "EVIDENCE": f"{last24:,.2f} credits in last 24h; {delta:+.1f}% vs prior window",
            "OWNER": "DBA / Cost owner",
            "ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Explain top drivers, classify allocated/estimated cost, and monitor any savings action later.",
            "PROOF_REQUIRED": "driver row, credit/cost formula, review for warehouse changes",
        },
        {
            "CHECK": "Task and procedure reliability",
            "STATUS": _check_status(failed_task_count == 0),
            "SEVERITY": "High" if failed_task_count > 0 else "Info",
            "EVIDENCE": f"{failed_task_count:,} failed task groups in last 24h",
            "OWNER": "DBA / Data Engineering",
            "ROUTE": "Workload Operations",
            "NEXT_ACTION": "Open task graphs and confirm recovery SLA, downstream impact, and retry review.",
            "PROOF_REQUIRED": "task history, root cause, telemetry status, recovery state",
        },
        {
            "CHECK": "Change and drift review",
            "STATUS": _check_status(change_count == 0, change_count <= 10),
            "SEVERITY": "Medium" if change_count > 0 else "Info",
            "EVIDENCE": f"{change_count:,} object/access change signals in last 24h",
            "OWNER": "DBA / Security Owner",
            "ROUTE": "Security Monitoring",
            "NEXT_ACTION": "Validate query IDs against change tickets, approvers, and release-note/rollback state.",
            "PROOF_REQUIRED": "query_id, approver, change ticket, dependency note",
        },
        {
            "CHECK": "Storage and monitor posture",
            "STATUS": _check_status(stor_tb > 0, stor_tb == 0),
            "SEVERITY": "Low" if stor_tb > 0 else "Medium",
            "EVIDENCE": f"{safe_float(stor_tb):.1f} TB latest storage reading",
            "OWNER": "DBA / Platform",
            "ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Review cost controls for quota, notification, suspend, and suspend-immediate coverage.",
            "PROOF_REQUIRED": "resource monitor thresholds and warehouse scope",
        },
    ]
    if score < 75:
        rows.insert(0, {
            "CHECK": "Overall health escalation",
            "STATUS": "Needs DBA",
            "SEVERITY": "High" if score < 60 else "Medium",
            "EVIDENCE": f"Health state {score_label}; account pressure crossed DBA threshold",
            "OWNER": "DBA Lead",
            "ROUTE": "DBA Control Room",
            "NEXT_ACTION": "Run DBA Control Room triage and convert active signals into owned action queue items.",
            "PROOF_REQUIRED": "control-room exception row and action queue ID",
        })
    rank = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}
    checklist = pd.DataFrame(rows)
    checklist = _enrich_account_health_checklist_owners(checklist)
    checklist["_RANK"] = checklist["SEVERITY"].map(rank).fillna(4)
    return checklist.sort_values(["_RANK", "CHECK"]).drop(columns=["_RANK"])

def _account_health_verification_sql(check: object, evidence: object = "") -> str:
    """Build a read-only source query for a daily DBA checklist action."""
    name = str(check or "").lower()
    if "refresh source readiness" in name or "refresh source confidence" in name:
        usage_fqn = f"{safe_identifier(ALERT_DB)}.{safe_identifier(ALERT_SCHEMA)}.OVERWATCH_USAGE_LOG"
        return f"""
SELECT
    LOG_TIME,
    COMPANY_VIEW,
    SECTION,
    EVENT_TYPE,
    QUERY_DURATION_MS,
    QUERY_HASH
FROM {usage_fqn}
WHERE SECTION = 'Account Health'
ORDER BY LOG_TIME DESC
LIMIT 50""".strip()
    if "query failure" in name:
        return """
SELECT
    query_id,
    start_time,
    user_name,
    role_name,
    warehouse_name,
    database_name,
    query_type,
    execution_status,
    error_code,
    error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
  AND (error_code IS NOT NULL OR UPPER(execution_status) = 'FAILED_WITH_ERROR')
ORDER BY start_time DESC
LIMIT 50""".strip()
    if "queue pressure" in name:
        return """
SELECT
    query_id,
    start_time,
    user_name,
    warehouse_name,
    execution_status,
    COALESCE(queued_overload_time, 0)
      + COALESCE(queued_provisioning_time, 0)
      + COALESCE(queued_repair_time, 0) AS queued_ms,
    total_elapsed_time
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
  AND (
      COALESCE(queued_overload_time, 0)
      + COALESCE(queued_provisioning_time, 0)
      + COALESCE(queued_repair_time, 0) > 0
      OR execution_status ILIKE '%QUEUED%'
  )
ORDER BY queued_ms DESC
LIMIT 50""".strip()
    if "cost spike" in name:
        return """
SELECT
    warehouse_name,
    DATE_TRUNC('hour', start_time) AS usage_hour,
    SUM(credits_used) AS credits_used
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
GROUP BY warehouse_name, DATE_TRUNC('hour', start_time)
ORDER BY credits_used DESC
LIMIT 50""".strip()
    if "task" in name or "procedure" in name:
        return """
SELECT
    database_name,
    schema_name,
    name AS task_name,
    state,
    scheduled_time,
    completed_time,
    query_id,
    error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
  AND UPPER(state) = 'FAILED'
ORDER BY scheduled_time DESC
LIMIT 50""".strip()
    if "change" in name or "drift" in name:
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
WHERE start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
  AND (
      query_text ILIKE 'CREATE%'
      OR query_text ILIKE 'ALTER%'
      OR query_text ILIKE 'DROP%'
      OR query_text ILIKE 'GRANT%'
      OR query_text ILIKE 'REVOKE%'
      OR query_text ILIKE '%OWNERSHIP%'
      OR query_text ILIKE '%MASKING POLICY%'
      OR query_text ILIKE '%ROW ACCESS POLICY%'
      OR query_text ILIKE '%TAG%'
  )
ORDER BY start_time DESC
LIMIT 50""".strip()
    if "storage" in name or "monitor" in name:
        return """
SELECT
    database_name,
    usage_date,
    ROUND((COALESCE(average_database_bytes, 0) + COALESCE(average_failsafe_bytes, 0)) / POWER(1024, 4), 4) AS storage_tb
FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
WHERE usage_date >= DATEADD('day', -7, CURRENT_DATE())
ORDER BY usage_date DESC, storage_tb DESC
LIMIT 50""".strip()
    return f"""
SELECT
    CURRENT_TIMESTAMP() AS verification_ts,
    {sql_literal(str(check or 'Account Health checklist'), 500)} AS check_name,
    {sql_literal(str(evidence or ''), 1000)} AS observed_evidence
LIMIT 50""".strip()

def _account_health_actionable_checklist(checklist: pd.DataFrame) -> pd.DataFrame:
    if checklist is None or checklist.empty:
        return pd.DataFrame()
    view = checklist.copy()
    status = view.get("STATUS", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    severity = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    return view[(status != "OK") & (severity != "INFO")].copy()

def _account_health_visible_checklist(
    checklist: pd.DataFrame,
    *,
    show_full: bool = False,
) -> tuple[pd.DataFrame, str, str]:
    """Return the default Account Health checklist view for DBA triage."""
    full = pd.DataFrame() if checklist is None else checklist.copy()
    if show_full:
        return full, "Daily DBA checklist", "All daily DBA checklist rows"
    actionable = _account_health_actionable_checklist(full)
    return actionable, "Daily DBA checklist exceptions", "Full daily DBA checklist rows"

def _account_health_scope_context(check: object, route: object = "", environment: str = "") -> dict:
    """Classify whether a checklist row has database context or account-only scope."""
    name = str(check or "").lower()
    route_text = str(route or "").lower()
    env_value = str(environment or "").strip() or "ALL"
    if env_value.upper() == "ALL":
        env_scope = "ALL"
    else:
        env_scope = env_value

    database_checks = (
        "query failure",
        "queue pressure",
        "task",
        "procedure",
        "change",
        "drift",
        "storage",
    )
    if any(token in name for token in database_checks):
        if env_scope == "ALL":
            confidence = "Database Context - All Environments"
            evidence = "Checklist source includes database-aware Snowflake facts and is not narrowed to a single environment."
        else:
            confidence = "Database Context"
            evidence = f"Checklist source can be checked against database-aware Snowflake facts scoped to {env_scope}."
        return {
            "ENVIRONMENT_SCOPE": env_scope,
            "DATABASE_CONTEXT": "Yes",
            "SCOPE_CONFIDENCE": confidence,
            "SCOPE_EVIDENCE": evidence,
        }

    if "cost" in name or "contract" in route_text:
        return {
            "ENVIRONMENT_SCOPE": env_scope,
            "DATABASE_CONTEXT": "Allocated / Estimated",
            "SCOPE_CONFIDENCE": "Allocated Estimate",
            "SCOPE_EVIDENCE": (
                "Warehouse metering is shared across database workloads; environment cost is DBA-attributed "
                "and must be treated as allocated/estimated."
            ),
        }

    return {
        "ENVIRONMENT_SCOPE": "No Database Context" if env_scope == "ALL" else env_scope,
        "DATABASE_CONTEXT": "No",
        "SCOPE_CONFIDENCE": "Account-Level Control",
        "SCOPE_EVIDENCE": "Checklist item is an account-level DBA control and should not be filtered as a database fact.",
    }

def _account_health_recovery_target_hours(severity: object) -> int:
    sev = str(severity or "").upper()
    if sev == "CRITICAL":
        return 12
    if sev == "HIGH":
        return 24
    if sev == "MEDIUM":
        return 72
    return 168

def _account_health_readiness_for_row(row: pd.Series | dict) -> dict:
    owner = str(row.get("OWNER") or "").strip()
    severity = str(row.get("SEVERITY") or "").upper()
    approval_group = str(row.get("APPROVAL_GROUP") or row.get("ESCALATION_TARGET") or "").strip()
    proof = str(row.get("PROOF_REQUIRED") or "").strip()
    scope_confidence = str(row.get("SCOPE_CONFIDENCE") or "").strip()
    verification = _account_health_verification_sql(row.get("CHECK"), row.get("EVIDENCE"))
    blockers = []

    generic_owners = {"", "DBA", "UNKNOWN", "N/A", "DBA / COST OWNER", "DBA / DATA ENGINEERING"}
    if owner.upper() in generic_owners and not approval_group:
        blockers.append("escalation route")
    approval_required = severity in {"CRITICAL", "HIGH", "MEDIUM"}
    if approval_required and not approval_group:
        blockers.append("review group")
    if not proof:
        blockers.append("telemetry basis")
    verification_upper = verification.upper()
    if not verification or not any(
        token in verification_upper
        for token in ("SNOWFLAKE.ACCOUNT_USAGE", "INFORMATION_SCHEMA", "OVERWATCH")
    ):
        blockers.append("source telemetry")
    if not scope_confidence:
        blockers.append("scope confidence")

    return {
        "APPROVAL_REQUIRED": "Yes" if approval_required else "No",
        "RECOVERY_SLA_TARGET_HOURS": _account_health_recovery_target_hours(severity),
        "VERIFICATION_QUERY": verification,
        "QUEUE_READINESS": "Ready to Queue" if not blockers else "Needs Routing Data",
        "QUEUE_BLOCKERS": "; ".join(blockers) if blockers else "None",
    }

def _annotate_account_health_checklist_readiness(
    checklist: pd.DataFrame,
    environment: str = "ALL",
) -> pd.DataFrame:
    """Add DBA routing, scope, and queue-readiness telemetry to checklist rows."""
    if checklist is None or checklist.empty:
        return pd.DataFrame() if checklist is None else checklist
    view = checklist.copy()
    if "OWNER_SOURCE" not in view.columns:
        view = _enrich_account_health_checklist_owners(view)
    scope_rows = view.apply(
        lambda row: _account_health_scope_context(row.get("CHECK"), row.get("ROUTE"), environment),
        axis=1,
    )
    for column in ["ENVIRONMENT_SCOPE", "DATABASE_CONTEXT", "SCOPE_CONFIDENCE", "SCOPE_EVIDENCE"]:
        view[column] = scope_rows.apply(lambda item, col=column: item.get(col, ""))
    readiness_rows = view.apply(_account_health_readiness_for_row, axis=1)
    for column in ["APPROVAL_REQUIRED", "RECOVERY_SLA_TARGET_HOURS", "VERIFICATION_QUERY", "QUEUE_READINESS", "QUEUE_BLOCKERS"]:
        view[column] = readiness_rows.apply(lambda item, col=column: item.get(col, ""))
    return view

def _account_health_control_board(
    checklist: pd.DataFrame,
    closure: pd.DataFrame | None = None,
    access_hygiene: pd.DataFrame | None = None,
    trend: pd.DataFrame | None = None,
    environment: str = "ALL",
) -> pd.DataFrame:
    """Combine checklist, account hygiene, history, and closure blockers into one DBA operating board."""
    if checklist is None or checklist.empty:
        base = pd.DataFrame()
    else:
        base = _annotate_account_health_checklist_readiness(checklist, environment=environment)

    closure_view = pd.DataFrame() if closure is None else closure.copy()
    if not closure_view.empty:
        closure_view.columns = [str(col).upper() for col in closure_view.columns]
    trend_view = pd.DataFrame() if trend is None else trend.copy()
    if not trend_view.empty:
        trend_view.columns = [str(col).upper() for col in trend_view.columns]

    closure_by_check = {
        str(row.get("CHECK_NAME") or "").upper(): row
        for _, row in closure_view.iterrows()
    } if not closure_view.empty else {}
    trend_by_check = {
        str(row.get("CHECK_NAME") or "").upper(): row
        for _, row in trend_view.iterrows()
    } if not trend_view.empty else {}

    rows: list[dict] = []
    if not base.empty:
        actionable_checks = set(_account_health_actionable_checklist(base).get("CHECK", pd.Series(dtype=str)).astype(str))
        for _, row in base.iterrows():
            check = str(row.get("CHECK") or "")
            check_key = check.upper()
            close = closure_by_check.get(check_key, {})
            trend_row = trend_by_check.get(check_key, {})
            status = str(row.get("STATUS") or "")
            queue_readiness = str(row.get("QUEUE_READINESS") or "")
            queue_blockers = str(row.get("QUEUE_BLOCKERS") or "")
            open_actions = safe_int(close.get("OPEN_ACTIONS", 0))
            overdue = safe_int(close.get("OVERDUE_OPEN", 0))
            fixed_without_verification = safe_int(close.get("FIXED_WITHOUT_VERIFICATION", 0))
            recovery_risk = safe_int(close.get("RECOVERY_RISK_ROWS", 0))
            verified = safe_int(close.get("VERIFIED_CLOSURES", 0))
            issue_snapshots = safe_int(trend_row.get("ISSUE_SNAPSHOTS", 0))
            closure_rank = safe_int(close.get("CLOSURE_RANK", 9))

            if overdue:
                state, rank = "Closure Overdue", 0
                next_action = "Escalate owner and due date before accepting the checklist control."
            elif fixed_without_verification or recovery_risk or closure_rank in {1, 2}:
                state, rank = "Closure Status Pending", 1
                next_action = str(close.get("NEXT_ACTION") or "Reopen the action for DBA review or wait for telemetry to confirm recovery.")
            elif queue_readiness != "Ready to Queue":
                state, rank = "Route Metadata Blocked", 2
                next_action = f"Complete checklist route metadata: {queue_blockers or 'route, ticket, or telemetry basis'}."
            elif check in actionable_checks and open_actions == 0:
                state, rank = "Queue Required", 3
                next_action = "Save this checklist issue to the action queue with route and telemetry context."
            elif open_actions > 0:
                state, rank = "Work Open Action", 4
                next_action = str(close.get("NEXT_ACTION") or row.get("NEXT_ACTION") or "Work open checklist action.")
            elif issue_snapshots > 1:
                state, rank = "Recurring Watch", 6
                next_action = "Review repeated checklist snapshots and create a durable control if the issue recurs."
            elif verified:
                state, rank = "Closed", 8
                next_action = "Keep closure status visible in the trend review."
            else:
                state, rank = "Controlled", 9
                next_action = str(row.get("NEXT_ACTION") or "No action needed for this snapshot.")

            rows.append({
                "CONTROL_STATE": state,
                "CONTROL_RANK": rank,
                "CHECK_NAME": check,
                "STATUS": status,
                "SEVERITY": row.get("SEVERITY", ""),
                "ROUTE": row.get("ROUTE", ""),
                "OWNER": row.get("OWNER", ""),
                "ESCALATION_TARGET": row.get("ESCALATION_TARGET", ""),
                "ENVIRONMENT_SCOPE": row.get("ENVIRONMENT_SCOPE", ""),
                "DATABASE_CONTEXT": row.get("DATABASE_CONTEXT", ""),
                "SCOPE_CONFIDENCE": row.get("SCOPE_CONFIDENCE", ""),
                "QUEUE_READINESS": queue_readiness,
                "QUEUE_BLOCKERS": queue_blockers,
                "APPROVAL_REQUIRED": row.get("APPROVAL_REQUIRED", ""),
                "RECOVERY_SLA_TARGET_HOURS": safe_float(row.get("RECOVERY_SLA_TARGET_HOURS")),
                "OPEN_ACTIONS": open_actions,
                "OVERDUE_OPEN": overdue,
                "FIXED_WITHOUT_VERIFICATION": fixed_without_verification,
                "RECOVERY_RISK_ROWS": recovery_risk,
                "VERIFIED_CLOSURES": verified,
                "ISSUE_SNAPSHOTS": issue_snapshots,
                "PROOF_REQUIRED": row.get("PROOF_REQUIRED", ""),
                "NEXT_CONTROL_ACTION": next_action,
            })

    hygiene = pd.DataFrame() if access_hygiene is None else access_hygiene.copy()
    if not hygiene.empty:
        from sections.account_health_access_hygiene import _annotate_account_health_access_hygiene

        hygiene = _annotate_account_health_access_hygiene(hygiene)
        severity = hygiene.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        high = int(severity.eq("HIGH").sum())
        medium = int(severity.eq("MEDIUM").sum())
        queue_blocks = int((hygiene.get("QUEUE_READINESS", pd.Series(dtype=str)).astype(str) != "Ready to Queue").sum())
        approval_blocks = int((hygiene.get("APPROVAL_REQUIRED", pd.Series(dtype=str)).astype(str) == "Yes").sum())
        if queue_blocks:
            state, rank = "Access Route Blocked", 1
            next_action = "Complete route, review, and telemetry metadata for account-level access hygiene rows."
        elif high:
            state, rank = "High-Risk Access Review", 2
            next_action = "Queue high-risk admin, MFA, stale, or failed-login user hygiene items for Security/DBA review."
        else:
            state, rank = "Access Hygiene Watch", 6
            next_action = "Review medium-risk account hygiene rows and keep account-level telemetry current."
        rows.append({
            "CONTROL_STATE": state,
            "CONTROL_RANK": rank,
            "CHECK_NAME": "Account access hygiene",
            "STATUS": "Needs DBA",
            "SEVERITY": "High" if high else "Medium",
            "ROUTE": "Security Monitoring",
            "OWNER": "DBA / Security",
            "ESCALATION_TARGET": "Security Lead",
            "ENVIRONMENT_SCOPE": "No Database Context",
            "DATABASE_CONTEXT": "No",
            "SCOPE_CONFIDENCE": "Account-Level Control",
            "QUEUE_READINESS": "Needs Routing Data" if queue_blocks else "Ready to Queue",
            "QUEUE_BLOCKERS": f"{queue_blocks:,} route blocker row(s)" if queue_blocks else "None",
            "APPROVAL_REQUIRED": "Yes" if approval_blocks else "No",
            "RECOVERY_SLA_TARGET_HOURS": 24 if high else 72,
            "OPEN_ACTIONS": 0,
            "OVERDUE_OPEN": 0,
            "FIXED_WITHOUT_VERIFICATION": 0,
            "RECOVERY_RISK_ROWS": 0,
            "VERIFIED_CLOSURES": 0,
            "ISSUE_SNAPSHOTS": 0,
            "PROOF_REQUIRED": "user, IAM ticket, admin-role/MFA posture, telemetry status",
            "NEXT_CONTROL_ACTION": (
                f"{len(hygiene):,} user hygiene row(s): {high:,} high, {medium:,} medium. {next_action}"
            ),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS", "SEVERITY", "CHECK_NAME"],
        ascending=[True, False, False, False, True, True],
    ).reset_index(drop=True)

def _account_health_frame_sum(frame: pd.DataFrame | None, column: str) -> int:
    if frame is None or frame.empty or column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())

def _account_health_operator_next_moves(
    *,
    health_score: int | float,
    checklist: pd.DataFrame | None,
    control_board: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    access_hygiene: pd.DataFrame | None = None,
    operability_fact: pd.DataFrame | None = None,
    source_health: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a no-query action gate for loaded Account Health telemetry."""
    checks = pd.DataFrame() if checklist is None else checklist.copy()
    control = pd.DataFrame() if control_board is None else control_board.copy()
    close = pd.DataFrame() if closure is None else closure.copy()
    hygiene = pd.DataFrame() if access_hygiene is None else access_hygiene.copy()
    fact = pd.DataFrame() if operability_fact is None else operability_fact.copy()
    sources = pd.DataFrame() if source_health is None else source_health.copy()
    for frame in (control, close, hygiene, fact, sources):
        if not frame.empty:
            frame.columns = [str(col).upper() for col in frame.columns]

    actionable = 0
    if not checks.empty:
        annotated = _annotate_account_health_checklist_readiness(checks)
        actionable = len(_account_health_actionable_checklist(annotated))
    issue_rows = max(actionable, _account_health_frame_sum(fact, "ISSUE_ROWS"))
    route_blocks = max(
        int((control.get("QUEUE_READINESS", pd.Series(dtype=str)).astype(str) != "Ready to Queue").sum()) if not control.empty and "QUEUE_READINESS" in control.columns else 0,
        _account_health_frame_sum(fact, "ROUTE_BLOCKER_ROWS"),
        _account_health_frame_sum(fact, "QUEUE_REQUIRED_ROWS"),
    )
    overdue = max(
        _account_health_frame_sum(control, "OVERDUE_OPEN"),
        _account_health_frame_sum(close, "OVERDUE_OPEN"),
        _account_health_frame_sum(fact, "OVERDUE_OPEN"),
    )
    fixed_without_verification = max(
        _account_health_frame_sum(control, "FIXED_WITHOUT_VERIFICATION"),
        _account_health_frame_sum(close, "FIXED_WITHOUT_VERIFICATION"),
        _account_health_frame_sum(fact, "FIXED_WITHOUT_VERIFICATION"),
    )
    recovery_risk = max(
        _account_health_frame_sum(control, "RECOVERY_RISK_ROWS"),
        _account_health_frame_sum(close, "RECOVERY_RISK_ROWS"),
        _account_health_frame_sum(fact, "RECOVERY_RISK_ROWS"),
    )
    verified = max(
        _account_health_frame_sum(control, "VERIFIED_CLOSURES"),
        _account_health_frame_sum(close, "VERIFIED_CLOSURES"),
        _account_health_frame_sum(fact, "VERIFIED_CLOSURES"),
    )
    access_rows = max(
        0 if hygiene.empty else int(len(hygiene)),
        _account_health_frame_sum(fact, "ACCESS_HYGIENE_ROWS"),
        _account_health_frame_sum(fact, "FAILED_LOGIN_ROWS"),
        _account_health_frame_sum(fact, "PRIVILEGED_GRANT_ROWS"),
    )
    access_route_blocks = 0
    if not hygiene.empty and "QUEUE_READINESS" in hygiene.columns:
        access_route_blocks = int(hygiene["QUEUE_READINESS"].astype(str).ne("Ready to Queue").sum())
    if not control.empty and "CHECK_NAME" in control.columns:
        access_route_blocks = max(
            access_route_blocks,
            int(
                (
                    control["CHECK_NAME"].astype(str).str.upper().eq("ACCOUNT ACCESS HYGIENE")
                    & control.get("QUEUE_READINESS", pd.Series(dtype=str)).astype(str).ne("Ready to Queue")
                ).sum()
            ),
        )
    high_access = 0
    if not hygiene.empty and "SEVERITY" in hygiene.columns:
        high_access = int(hygiene["SEVERITY"].fillna("").astype(str).str.upper().isin(["CRITICAL", "HIGH"]).sum())

    stale_sources = 0
    unavailable_sources = 0
    if not sources.empty and "STATE" in sources.columns:
        state = sources["STATE"].fillna("").astype(str).str.upper()
        stale_sources = int(state.eq("STALE").sum())
        unavailable_sources = int(state.eq("UNAVAILABLE").sum())

    rows: list[dict] = []
    closure_blocks = overdue + fixed_without_verification + recovery_risk
    if closure_blocks:
        state, rank, count = "Closure Blocked", 0, closure_blocks
        next_action = "Escalate overdue or telemetry-pending Account Health actions before claiming the account is controlled."
    elif issue_rows and close.empty and fact.empty:
        state, rank, count = "Load Closure Analytics", 4, issue_rows
        next_action = "Load closure analytics before accepting checklist or access-hygiene work as complete."
    else:
        state, rank, count = "Clear", 8, verified
        next_action = "Keep closure status visible in Account Health trends."
    rows.append({
        "GATE": "Closure status",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "telemetry status, ticket, recovery state, closure timestamp",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if route_blocks:
        state, rank, count = "Route Blocked", 1, route_blocks
        next_action = "Complete route, reviewer, scope basis, and telemetry query before queueing."
    elif issue_rows:
        state, rank, count = "Queue Ready", 6, issue_rows
        next_action = "Queue only actionable checklist rows with route and telemetry context attached."
    else:
        state, rank, count = "Clear", 8, 0
        next_action = "No checklist route currently needs DBA action."
    rows.append({
        "GATE": "Checklist route",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "route, reviewer, scope basis, source telemetry, recovery SLA",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if access_route_blocks:
        state, rank, count = "Access Route Blocked", 1, access_route_blocks
        next_action = "Complete IAM/security route, escalation, and review context before queueing account-level access work."
    elif high_access:
        state, rank, count = "High-Risk Access Review", 2, high_access
        next_action = "Prioritize admin-role, MFA, stale-login, and failed-login rows for DBA/Security review."
    elif access_rows:
        state, rank, count = "Access Hygiene Watch", 6, access_rows
        next_action = "Keep account-level telemetry current and queue only medium-or-higher rows."
    else:
        state, rank, count = "Clear", 8, 0
        next_action = "No account-level access hygiene rows are loaded for action."
    rows.append({
        "GATE": "Access hygiene",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "user, IAM ticket, admin-role/MFA posture, failed-login context, telemetry status",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if unavailable_sources:
        state, rank, count = "Source Unavailable", 2, unavailable_sources
        next_action = "Deploy or grant missing Account Health mart/source objects before relying on the board."
    elif stale_sources:
        state, rank, count = "Source Stale", 3, stale_sources
        next_action = "Reload stale Account Health telemetry before queueing or closing work."
    else:
        state, rank, count = "Current", 8, 0
        next_action = "Loaded sources are current for the active Account Health scope."
    rows.append({
        "GATE": "Source readiness",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "fresh source state, load timestamp, scope match, account-level disclosure where needed",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    if safe_float(health_score) < 75 or issue_rows:
        state = "Account Review Required" if safe_float(health_score) < 75 else "Checklist Review"
        rank = 5
        count = max(issue_rows, 1)
        next_action = "Work Account Health issues before lower-risk optimization work."
    else:
        state, rank, count = "Controlled", 8, 0
        next_action = "No account-level health pressure crossed the current action threshold."
    rows.append({
        "GATE": "Account pressure",
        "STATE": state,
        "COUNT": count,
        "PROOF_REQUIRED": "health state, failed queries/tasks, queue pressure, storage/cost/change signals",
        "NEXT_ACTION": next_action,
        "GATE_RANK": rank,
    })

    return pd.DataFrame(rows).sort_values(["GATE_RANK", "COUNT"], ascending=[True, False]).reset_index(drop=True)

def _account_health_morning_exception_rows(
    *,
    checklist: pd.DataFrame | None,
    gates: pd.DataFrame | None,
    interventions: pd.DataFrame | None,
    control_board: pd.DataFrame | None,
    health_score: float,
    err_count: int,
    queued: int,
    pct_delta: float,
    failed_tasks: int,
) -> pd.DataFrame:
    """Return the compact first-screen exceptions a DBA should triage first."""
    rows: list[dict] = []

    def _add(
        severity: str,
        signal: str,
        entity: str,
        evidence: str,
        next_action: str,
        route: str = "DBA Control Room",
        priority: int = 50,
    ) -> None:
        rows.append({
            "PRIORITY": priority,
            "SEVERITY": severity,
            "SIGNAL": signal,
            "ENTITY": entity,
            "EVIDENCE": evidence,
            "NEXT_ACTION": next_action,
            "ROUTE": _canonical_account_route(route),
        })

    if safe_float(health_score) < 75:
        _add(
            "High",
            "Account pressure",
            "Account",
            "Account pressure crossed the DBA threshold; review blockers before publishing a clean brief.",
            "Work the highest-ranked Account Health gate before lower-priority dashboard review.",
            priority=0,
        )
    if safe_int(err_count) > 0:
        _add(
            "High" if safe_int(err_count) >= 10 else "Medium",
            "Query failures",
            "Workload",
            f"{safe_int(err_count):,} failed query signal(s) in the loaded Account Health snapshot.",
            "Open Workload Operations query diagnosis and validate route, query text, and recovery status.",
            route="Workload Operations",
            priority=5 if safe_int(err_count) >= 10 else 18,
        )
    if safe_int(failed_tasks) > 0:
        _add(
            "High",
            "Task failures",
            "Task graph",
            f"{safe_int(failed_tasks):,} failed task signal(s) in the loaded Account Health snapshot.",
            "Open Workload Operations task graphs and capture Snowflake task/task recovery status.",
            route="Workload Operations",
            priority=6,
        )
    if safe_int(queued) > 0:
        _add(
            "Medium",
            "Queue pressure",
            "Warehouses",
            f"{safe_int(queued):,} queued workload signal(s) are visible in the loaded snapshot.",
            "Review warehouse pressure before resizing or changing workload routing.",
            route="Cost & Contract",
            priority=20,
        )
    if safe_float(pct_delta) > 30:
        _add(
            "Medium",
            "Credit spike",
            "Cost",
            f"24-hour credit movement is +{safe_float(pct_delta):.0f}%.",
            "Open Cost & Contract attribution before treating the account as cost-stable.",
            route="Cost & Contract",
            priority=22,
        )

    gate_view = pd.DataFrame() if gates is None else gates.copy()
    if not gate_view.empty:
        gate_view.columns = [str(col).upper() for col in gate_view.columns]
        if "GATE_RANK" in gate_view.columns:
            gate_view["_RANK"] = pd.to_numeric(gate_view["GATE_RANK"], errors="coerce").fillna(99)
        else:
            gate_view["_RANK"] = 99
        gate_state = gate_view.get("STATE", pd.Series([""] * len(gate_view), index=gate_view.index)).fillna("").astype(str)
        gate_focus = gate_view[
            ~gate_state.str.upper().isin(["CLEAR", "CURRENT", "CONTROLLED"])
        ].sort_values(["_RANK", "COUNT"], ascending=[True, False])
        for _, row in gate_focus.head(3).iterrows():
            rank = safe_int(row.get("_RANK", 9))
            _add(
                "High" if rank <= 1 else "Medium",
                str(row.get("STATE") or "Gate review"),
                str(row.get("GATE") or "Account Health gate"),
                f"{safe_int(row.get('COUNT', 0)):,} row(s) need attention. Telemetry basis: {row.get('PROOF_REQUIRED', '')}",
                str(row.get("NEXT_ACTION") or "Open the Account Health gate and validate telemetry."),
                route="DBA Control Room",
                priority=2 + rank,
            )

    intervention_view = pd.DataFrame() if interventions is None else interventions.copy()
    if not intervention_view.empty:
        intervention_view.columns = [str(col).upper() for col in intervention_view.columns]
        priority_series = intervention_view.get("DBA_PRIORITY", pd.Series([""] * len(intervention_view), index=intervention_view.index))
        focus = intervention_view[priority_series.fillna("").astype(str).str.upper().isin(["P0", "P1"])].copy()
        priority_rank = {"P0": 0, "P1": 1}
        if not focus.empty:
            focus["_RANK"] = focus["DBA_PRIORITY"].astype(str).str.upper().map(priority_rank).fillna(9)
            for _, row in focus.sort_values(["_RANK", "COUNT"], ascending=[True, False]).head(3).iterrows():
                _add(
                    "High" if str(row.get("DBA_PRIORITY", "")).upper() == "P0" else "Medium",
                    str(row.get("INTERVENTION_STATE") or "Intervention"),
                    str(row.get("SURFACE") or row.get("ROUTE") or "Account Health"),
                    str(row.get("NEXT_DECISION") or row.get("NEXT_CONTROL_ACTION") or "DBA intervention required."),
                    str(row.get("PROOF_REQUIRED") or "Route, ticket, review, and telemetry status needed."),
                    route=_canonical_account_route(row.get("ROUTE")),
                    priority=12 + safe_int(row.get("_RANK", 9)),
                )

    control_view = pd.DataFrame() if control_board is None else control_board.copy()
    if not control_view.empty:
        control_view.columns = [str(col).upper() for col in control_view.columns]
        if "CONTROL_RANK" in control_view.columns:
            control_view["_RANK"] = pd.to_numeric(control_view["CONTROL_RANK"], errors="coerce").fillna(99)
            focus = control_view[control_view["_RANK"] <= 3].copy()
        else:
            focus = pd.DataFrame()
        for _, row in focus.sort_values(["_RANK", "OVERDUE_OPEN", "OPEN_ACTIONS"], ascending=[True, False, False]).head(3).iterrows():
            _add(
                "High" if safe_int(row.get("_RANK", 9)) <= 1 else "Medium",
                str(row.get("CONTROL_STATE") or "Control review"),
                str(row.get("CHECK_NAME") or "Account Health control"),
                str(row.get("NEXT_CONTROL_ACTION") or row.get("QUEUE_BLOCKERS") or "Control board review required."),
                str(row.get("PROOF_REQUIRED") or "Source telemetry and closure status needed."),
                route=_canonical_account_route(row.get("ROUTE")),
                priority=16 + safe_int(row.get("_RANK", 9)),
            )

    checklist_view = _account_health_actionable_checklist(checklist)
    if not checklist_view.empty:
        checklist_view = checklist_view.copy()
        checklist_view.columns = [str(col).upper() for col in checklist_view.columns]
        severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        checklist_view["_RANK"] = checklist_view.get("SEVERITY", pd.Series([""] * len(checklist_view), index=checklist_view.index)).fillna("").astype(str).str.upper().map(severity_rank).fillna(9)
        for _, row in checklist_view.sort_values(["_RANK", "CHECK"], ascending=[True, True]).head(4).iterrows():
            severity = str(row.get("SEVERITY") or "Medium")
            _add(
                severity if severity.upper() in {"CRITICAL", "HIGH", "MEDIUM"} else "Medium",
                str(row.get("CHECK") or "Checklist issue"),
                str(row.get("ROUTE") or row.get("OWNER") or "Account Health"),
                str(row.get("EVIDENCE") or "Checklist exception needs review."),
                str(row.get("NEXT_ACTION") or "Queue or resolve the checklist exception with telemetry context."),
                route=_canonical_account_route(row.get("ROUTE")),
                priority=24 + safe_int(row.get("_RANK", 9)),
            )

    if not rows:
        return pd.DataFrame(columns=["PRIORITY", "SEVERITY", "SIGNAL", "ENTITY", "EVIDENCE", "NEXT_ACTION", "ROUTE"])

    frame = pd.DataFrame(rows)
    frame["_DEDUP"] = (
        frame["SIGNAL"].fillna("").astype(str).str.upper()
        + "|"
        + frame["ENTITY"].fillna("").astype(str).str.upper()
    )
    frame = frame.sort_values(["PRIORITY", "SEVERITY", "SIGNAL"], ascending=[True, True, True])
    frame = frame.drop_duplicates("_DEDUP", keep="first").drop(columns=["_DEDUP"])
    return frame.head(6).reset_index(drop=True)

def _render_account_health_exception_strip(rows: pd.DataFrame | None) -> None:
    st.markdown("**Morning Exceptions**")
    if rows is None or rows.empty:
        st.success("No immediate Account Health exceptions in the loaded snapshot.")
        return
    for _, row in rows.head(5).iterrows():
        severity = str(row.get("SEVERITY") or "Medium")
        signal = str(row.get("SIGNAL") or "Account Health signal")
        entity = str(row.get("ENTITY") or "Account")
        evidence = str(row.get("EVIDENCE") or "")
        next_action = str(row.get("NEXT_ACTION") or "")
        route = _canonical_account_route(row.get("ROUTE"))
        message = f"{severity}: {signal} - {entity}. {evidence} Next: {next_action} Route: {route}."
        if severity.upper() in {"CRITICAL", "HIGH"}:
            st.warning(message)
        else:
            st.info(message)

def _account_health_action_brief(checklist: pd.DataFrame | None) -> dict:
    """Choose the single Account Health move to show above detailed telemetry."""
    if checklist is None or checklist.empty:
        return {
            "state": "On demand",
            "headline": "Load health telemetry before acting.",
            "detail": "No Account Health checklist rows are loaded for this scope.",
            "primary_label": "Load Health",
            "target": "Overview",
            "workflow": "",
        }
    view = checklist.copy()
    view.columns = [str(col).upper() for col in view.columns]
    if "CHECK" not in view.columns:
        view["CHECK"] = "Account Health"
    severity_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}
    state_rank = {"NEEDS DBA": 0, "VERIFY SOURCE": 1, "WATCH": 2, "OK": 8, "HEALTHY": 8, "CLEAR": 8}
    status = view.get("STATUS", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    severity = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    view["_SEVERITY_RANK"] = severity.str.upper().map(severity_rank).fillna(4)
    view["_STATE_RANK"] = status.str.upper().map(state_rank).fillna(3)
    actionable = view[
        ~status.str.upper().isin(["OK", "HEALTHY", "CLEAR"])
    ].sort_values(["_SEVERITY_RANK", "_STATE_RANK", "CHECK"])
    if actionable.empty:
        return {
            "state": "Clear",
            "headline": "No immediate Account Health blocker.",
            "detail": "Use Morning Report when you need the brief.",
            "primary_label": "Morning Report",
            "target": "Morning Report",
            "workflow": "",
        }
    row = actionable.iloc[0]
    route = _canonical_account_route(row.get("ROUTE"))
    check = str(row.get("CHECK") or "Account Health")
    action = str(row.get("NEXT_ACTION") or "Review the guarded drilldown workflow.")
    evidence = str(row.get("EVIDENCE") or "")
    return {
        "state": str(row.get("STATUS") or row.get("SEVERITY") or "Review"),
        "headline": action,
        "detail": f"{check}: {evidence}".strip(": "),
        "primary_label": f"Open {route}",
        "target": route,
        "workflow": check,
    }

def _render_account_health_action_brief(checklist: pd.DataFrame | None) -> None:
    brief = _account_health_action_brief(checklist)
    render_shell_status_strip(
        state=brief["state"],
        headline=brief["headline"],
        detail=brief["detail"],
    )


__all__ = [
    '_mart_health_label',
    '_check_status',
    '_account_health_owner_entity_type',
    '_account_health_owner_context',
    '_enrich_account_health_checklist_owners',
    '_build_account_health_dba_checklist',
    '_account_health_verification_sql',
    '_account_health_actionable_checklist',
    '_account_health_visible_checklist',
    '_account_health_scope_context',
    '_account_health_recovery_target_hours',
    '_account_health_readiness_for_row',
    '_annotate_account_health_checklist_readiness',
    '_account_health_control_board',
    '_account_health_frame_sum',
    '_account_health_operator_next_moves',
    '_account_health_morning_exception_rows',
    '_render_account_health_exception_strip',
    '_account_health_action_brief',
    '_render_account_health_action_brief',
]
