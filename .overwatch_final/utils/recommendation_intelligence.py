# utils/recommendation_intelligence.py - telemetry-backed recommendation wording
from __future__ import annotations

from collections.abc import Mapping
import re

import pandas as pd

from config import THRESHOLDS

from .helpers import safe_float, safe_int


AUTOMATION_LANE_ORDER = {
    "Ready": 0,
    "Telemetry Pending": 1,
    "Needs Data": 2,
    "Resolved Candidate": 3,
    "DBA Review": 4,
    "Monitor": 5,
}


def _row_value(row: Mapping | pd.Series | dict, *keys: str, default: object = "") -> object:
    if row is None:
        return default
    for key in keys:
        try:
            if isinstance(row, pd.Series):
                if key in row.index:
                    return row.get(key, default)
                upper = key.upper()
                if upper in row.index:
                    return row.get(upper, default)
                title = key.title()
                if title in row.index:
                    return row.get(title, default)
            elif isinstance(row, Mapping):
                if key in row:
                    return row.get(key, default)
                upper = key.upper()
                if upper in row:
                    return row.get(upper, default)
                title = key.title()
                if title in row:
                    return row.get(title, default)
        except Exception:
            continue
    return default


def _text(row: Mapping | pd.Series | dict, *keys: str, default: str = "") -> str:
    value = _row_value(row, *keys, default=default)
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return str(value).strip()


def _num(row: Mapping | pd.Series | dict, *keys: str, default: float = 0.0) -> float:
    return safe_float(_row_value(row, *keys, default=default), default)


def _entity(rec: Mapping | pd.Series | dict) -> str:
    return _text(rec, "Entity", "ENTITY", "ENTITY_NAME", "WAREHOUSE_NAME", "TASK_NAME", default="the affected object")


def _source_key(rec: Mapping | pd.Series | dict) -> str:
    return " ".join([
        _text(rec, "Source", "SOURCE"),
        _text(rec, "Category", "CATEGORY"),
        _text(rec, "Finding", "FINDING"),
        _text(rec, "Entity Type", "ENTITY_TYPE"),
    ]).upper()


def _money(value: float) -> str:
    return f"${value:,.0f}/mo" if abs(value) >= 1 else "$0/mo"


def recommendation_execution_contract(row: Mapping | pd.Series | dict) -> dict[str, str]:
    """Return the review and telemetry boundary for one advisory row."""
    source_key = _source_key(row)
    entity = _entity(row)
    route = _text(row, "Escalation Route", "Owner Route", "Route", "Owner", "OWNER", default="DBA route")
    proof = _text(row, "Proof Required", "PROOF_REQUIRED", default="Telemetry must show the condition cleared.")
    evidence = _text(row, "Evidence Packet", "EVIDENCE_PACKET", default="")
    generated_sql = _text(row, "Generated SQL Fix", "GENERATED_SQL_FIX")
    changes_state = _state_changing_sql(generated_sql)

    review_gate = f"{route} review before operational change; telemetry should confirm the condition clears."
    evidence_package = evidence or proof
    verify_next = proof
    execution_boundary = (
        "Recommendation is advisory only; execute reviewed changes through the guarded drilldown workflow."
    )

    if "IDLE" in source_key and "WAREHOUSE" in source_key:
        review_gate = "DBA capacity review and rollback boundary before AUTO_SUSPEND changes."
        evidence_package = (
            f"{entity} idle-hour metering, zero-query hours, estimated savings, and rollback setting."
        )
        verify_next = "Watch the next seven days of metering for idle credits/hours and workload failures."
        execution_boundary = "Do not disable, downsize, or suspend service warehouses from the recommendation row."
    elif "SPILL" in source_key:
        review_gate = "Workload review before resize or isolation."
        evidence_package = (
            f"{entity} remote-spill rows, top spilling query IDs, query profile/operator telemetry, queue trend, and cost impact."
        )
        verify_next = "Monitor remote spill, queue, elapsed time, and credits for the same workload after the fix."
        execution_boundary = "Do not upsize blindly; route through Query diagnosis or Cost & Contract capacity controls first."
    elif "TASK" in source_key and "FAIL" in source_key:
        review_gate = "Snowflake task operator review before retry, resume, or schedule change."
        evidence_package = f"{entity} TASK_HISTORY failure/recovery rows, latest error signature, and downstream impact."
        verify_next = "Monitor the next TASK_HISTORY run and downstream refresh state."
        execution_boundary = "Do not EXECUTE TASK from a recommendation; use Task graphs guarded controls and status prechecks."
    elif "QUERY FAILURE" in source_key or ("FAILED QUER" in source_key and "WAREHOUSE" in source_key):
        review_gate = "DBA reliability review before SQL, warehouse, or schedule changes."
        evidence_package = (
            f"{entity} error-code grouping, sample query IDs, escalation route, failure trend, and post-fix comparison."
        )
        verify_next = "Monitor whether the repeated error signature stops for the same query pattern."
        execution_boundary = "Do not change warehouse size for query failures without separate queue/spill/capacity telemetry."
    elif "DUPLICATE" in source_key or "REDUNDANT" in source_key:
        review_gate = "Workload review before materialization or cache changes."
        evidence_package = (
            f"{entity} repeated query signature, execution count, users, wasted seconds, result-reuse telemetry, and workload demand."
        )
        verify_next = "Monitor execution count, elapsed time, and cloud-services credits for the same query signature."
        execution_boundary = "Do not create materialized views, dynamic tables, or cache workarounds without stable semantics telemetry."
    elif "WAREHOUSE" in source_key and any(
        token in source_key
        for token in ("SIZING", "RIGHT-SIZING", "CAPACITY", "QUEUE", "DOWNSIZE", "OPTIMIZATION")
    ):
        review_gate = "DBA capacity review and rollback boundary before sizing, scaling, or isolation changes."
        evidence_package = (
            f"{entity} warehouse size, query count, credits, queue time, remote spill, cache, and rollback path."
        )
        verify_next = "Monitor queue, spill, runtime, failure rate, and credits against the same workload window after the change."
        execution_boundary = "Optimization Advisor is advisory; run warehouse changes only through Cost & Contract guarded controls."
    elif changes_state:
        review_gate = f"{route} and DBA review before running the proposed change."
        evidence_package = evidence or "Recommendation telemetry, proposed change, and rollback path."
        verify_next = proof
        execution_boundary = "The proposed change is advisory only; run it only from the guarded drilldown workflow after review."

    closure_rule = "Keep open until telemetry shows the condition is clear."
    return {
        "Review Gate": review_gate,
        "Evidence Package": evidence_package,
        "Verify Next": verify_next,
        "Execution Boundary": execution_boundary,
        "Closure Rule": closure_rule,
        "APPROVAL_GATE": review_gate,
        "REVIEW_GATE": review_gate,
        "EVIDENCE_PACKAGE": evidence_package,
        "VERIFY_NEXT": verify_next,
        "EXECUTION_BOUNDARY": execution_boundary,
        "CLOSURE_RULE": closure_rule,
    }


def harden_recommendation(rec: Mapping | pd.Series | dict) -> dict:
    """Return a recommendation with DBA decision fields and telemetry guardrails."""
    out = dict(rec)
    source_key = _source_key(out)
    entity = _entity(out)
    finding = _text(out, "Finding", "FINDING", default="Finding generated by OVERWATCH")
    savings = _num(out, "Estimated Monthly Savings", "EST_MONTHLY_SAVINGS")
    proof_query = _text(out, "Proof Query", "PROOF_QUERY", "Verification Query", "VERIFICATION_QUERY")

    decision = "Triage telemetry before changing settings"
    action = _text(out, "Action", "RECOMMENDED_ACTION", default="Open the routed OVERWATCH workflow and validate the finding.")
    evidence = f"{finding}; estimated value {_money(savings)}."
    safe_next = action
    proof = "Use before/after telemetry before closing the action."
    do_not = "Do not close the item from the recommendation text alone."
    escalation_route = _text(out, "Escalation Route", "Route", "Owner", "OWNER", default="DBA")
    confidence = "Medium - actionable finding with telemetry required"
    decision_gate = "Investigate"

    if "IDLE" in source_key and "WAREHOUSE" in source_key:
        idle_hours = safe_int(_row_value(out, "IDLE_HOURS", "Idle Hours", default=0))
        idle_credits = _num(out, "Baseline Value", "BASELINE_VALUE", "Current Value", "CURRENT_VALUE", default=0.0)
        suspend_minutes = safe_int(THRESHOLDS.get("idle_warehouse_minutes", 5), 5)
        decision = "Implement suspend control"
        action = (
            f"Set {entity} AUTO_SUSPEND to {suspend_minutes} minutes and keep AUTO_RESUME enabled after checking "
            "that it is not an approved always-on service warehouse."
        )
        evidence = (
            f"{entity}: {idle_hours:,} idle hour(s), {idle_credits:,.4f} idle credits, "
            f"{_money(savings)} estimated avoidable spend."
        )
        safe_next = (
            f"Use metering history to confirm zero-query hours, then apply AUTO_SUSPEND={suspend_minutes * 60} "
            "through DBA change control."
        )
        proof = "After 7 days, telemetry should show idle credits and idle hours dropped."
        do_not = "Do not disable the warehouse or downsize it based only on idle-hour telemetry."
        confidence = "High - direct warehouse metering joined to query activity"
        decision_gate = "Ready to change"

    elif "SPILL" in source_key:
        spill_gb = _num(out, "Current Value", "REMOTE_GB", "REMOTE_SPILL_GB")
        decision = "Investigate memory pressure before resizing"
        action = (
            f"For {entity}, pull the top spilling query profiles and tune repeated joins/sorts first; resize only "
            "if the same workload still spills after query-level review."
        )
        evidence = f"{entity}: {spill_gb:,.2f} GB remote spill in the recommendation window."
        safe_next = (
            "Open Cost & Contract > Recommendations, identify the query IDs causing spill, and decide between SQL tuning, "
            "workload isolation, or a one-step warehouse size validation."
        )
        proof = "Track remote spill GB and queue time trend after the change."
        do_not = "Do not upsize blindly; remote spill can be caused by SQL shape and may just multiply cost."
        confidence = "Medium - spill is real, but the correct fix depends on query profile telemetry"
        decision_gate = "Telemetry required before change"

    elif "TASK" in source_key and "FAIL" in source_key:
        failures = _num(out, "Current Value", "MEASURED_DELTA", "FAILURES")
        decision = "Open a reliability incident"
        action = (
            f"Treat {entity} as a task reliability incident: identify the latest failure signature, confirm the route, "
            "fix root cause, then retry only after the blocker is cleared."
        )
        evidence = f"{entity}: {failures:,.0f} failed run(s) in the loaded window."
        safe_next = "Open Workload Operations > Task graphs and inspect TASK_HISTORY plus downstream impact."
        proof = "Close only after TASK_HISTORY shows the next successful run."
        do_not = "Do not EXECUTE TASK repeatedly until the failure category and dependency blocker are understood."
        escalation_route = _text(out, "Escalation Route", "Route", "Owner", "OWNER", default="Data Engineering")
        confidence = "High - task failure count is direct operational telemetry"
        decision_gate = "Incident"

    elif "QUERY FAILURE" in source_key or ("FAILED QUER" in source_key and "WAREHOUSE" in source_key):
        failures = _num(out, "Current Value", "FAILURES")
        decision = "Route repeated error signatures"
        action = (
            f"For {entity}, group failed queries by error code and route, then send the top repeated signature to "
            "the responsible team with sample query IDs."
        )
        evidence = f"{entity}: {failures:,.0f} failed query event(s) in the loaded window."
        safe_next = "Open Workload Operations > Query diagnosis filtered to this warehouse and capture the top error code."
        proof = "Track before/after failure counts and sample query IDs; close only after the repeated signature stops."
        do_not = "Do not change warehouse size for failed queries unless queue/spill telemetry also points to capacity pressure."
        confidence = "Medium - failure count is specific, root cause requires error-code detail"
        decision_gate = "Route finding"

    elif "TIME TRAVEL" in source_key or "RETENTION" in source_key:
        time_travel_tb = _num(out, "Current Value", "TIME_TRAVEL_TB", "Time Travel TB")
        active_tb = _num(out, "ACTIVE_TB", "Active TB")
        decision = "Review retention bloat"
        action = (
            f"For {entity}, confirm recovery, cloning, and compliance requirements before lowering retention. "
            "If approved, change retention through a reviewed database/schema/table-level plan."
        )
        evidence = (
            f"{entity}: {time_travel_tb:,.2f} TB time-travel storage against {active_tb:,.2f} TB active storage; "
            f"{_money(savings)} estimated monthly exposure."
        )
        safe_next = "Open Cost & Contract > Advanced Cost Tools > Storage & Retention, confirm largest tables, and route only objects with approved retention changes."
        proof = "After the retention window ages out, time-travel TB and monthly storage estimate should decline."
        do_not = "Do not lower retention on regulated, clone-heavy, or recovery-sensitive databases from this finding alone."
        confidence = "Medium - storage bytes are direct telemetry, but the safe setting depends on retention policy."
        decision_gate = "DBA review"

    elif "CLUSTERING" in source_key:
        clustering_cost = _num(out, "Current Value", "CLUSTERING_COST_USD", "Clustering Cost USD")
        reclustered_tb = _num(out, "TB_RECLUSTERED", "TB Reclusterd")
        decision = "Review clustering churn"
        action = (
            f"For {entity}, inspect clustering depth, DML churn, pruning benefit, and query demand before changing clustering."
        )
        evidence = (
            f"{entity}: {_money(clustering_cost)} automatic clustering cost, "
            f"{reclustered_tb:,.2f} TB reclustered in the loaded window."
        )
        safe_next = "Open query profile/pruning evidence and verify whether the clustering key still pays for itself."
        proof = "Cost per TB reclustered should decline or query pruning/runtime must justify the clustering spend."
        do_not = "Do not suspend reclustering until query benefit and DML churn are reviewed."
        confidence = "Medium - clustering cost is direct telemetry, value requires workload proof."
        decision_gate = "DBA review"

    elif "REPEATED QUERY" in source_key or "DUPLICATE QUERY" in source_key:
        runs = safe_int(_row_value(out, "RUNS", "EXECUTION_COUNT", default=0))
        total_hours = _num(out, "TOTAL_EXEC_HOURS", "TOTAL_WASTED_HOURS", "Total Exec Hours")
        decision = "Review repeated query pattern"
        action = (
            "Confirm the repeated statement has stable semantics and reusable demand, then choose result cache hygiene, "
            "dynamic table, task materialization, or query rewrite."
        )
        evidence = f"{entity}: {runs:,} executions and {total_hours:,.2f} total execution hours in the loaded window."
        safe_next = "Inspect sample query text, users, tags, and schedule before recommending materialization."
        proof = "Execution count, total elapsed seconds, or scan volume must fall for the same query signature."
        do_not = "Do not create a materialized object until ownership, freshness, and reuse are proven."
        escalation_route = _text(out, "Escalation Route", "Route", "Owner", "OWNER", default="Query reviewer / DBA lead")
        confidence = "Medium - repeated query telemetry is directional until workload ownership is confirmed."
        decision_gate = "Review finding"

    out["Decision"] = decision
    out["Action"] = action
    out["Evidence Packet"] = evidence
    out["Telemetry Summary"] = evidence
    out["Safe Next Action"] = safe_next
    out["Proof Required"] = proof
    out["Telemetry Basis"] = proof
    out["Do Not Do"] = do_not
    out["Escalation Route"] = escalation_route
    out["Confidence"] = confidence
    out["Decision Gate"] = decision_gate
    if proof_query:
        out["Proof Required"] = f"{proof} Telemetry query is available."
        out["Telemetry Basis"] = out["Proof Required"]
    out.setdefault("Verification Status", "Pending")
    out.setdefault("Telemetry Status", out["Verification Status"])
    out.setdefault("Recovery Evidence", out["Proof Required"])
    out.setdefault("Recovery Status", out["Recovery Evidence"])
    out.setdefault("Route Basis", out["Evidence Packet"])
    out.update(recommendation_execution_contract(out))
    return out


def harden_recommendation_rows(recs: list[dict]) -> list[dict]:
    return [harden_recommendation(rec) for rec in recs or []]


def _truthy_text(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.upper() not in {"NAN", "NONE", "NULL", "N/A"}


def _upper_blob(*values: object) -> str:
    return " ".join(str(value or "") for value in values).upper()


def _state_changing_sql(sql: str) -> bool:
    return bool(re.search(
        r"\b(ALTER|CREATE|DROP|TRUNCATE|DELETE|UPDATE|MERGE|INSERT|GRANT|REVOKE|EXECUTE|CALL|UNDROP)\b",
        str(sql or ""),
        flags=re.IGNORECASE,
    ))


def _safe_guided_sql(sql: str) -> bool:
    text = str(sql or "").strip().upper()
    if not text or "NO SAFE AUTOMATIC SQL FIX" in text:
        return False
    if re.search(r"\b(DROP|TRUNCATE|DELETE|UPDATE|MERGE|INSERT|GRANT|REVOKE|CALL|UNDROP)\b", text):
        return False
    if re.search(r"\bALTER\s+WAREHOUSE\b", text) and re.search(r"\bSET\b", text):
        return True
    return False


def _state_is_closed(row: Mapping | pd.Series | dict) -> bool:
    return _text(row, "Status", "STATUS").upper() in {"FIXED", "RESOLVED", "CLOSED"}


def _verification_is_proved(row: Mapping | pd.Series | dict) -> bool:
    return _text(row, "Verification Status", "VERIFICATION_STATUS").upper() in {"VERIFIED", "PASSED", "PROVED"}


def _approval_state(row: Mapping | pd.Series | dict) -> str:
    return _text(row, "Verification Status", "OWNER_APPROVAL_STATUS", "APPROVAL_STATE").upper()


def _automation_blockers(row: Mapping | pd.Series | dict, hardened: Mapping | dict) -> list[str]:
    blockers = []
    proof_query = _text(row, "Proof Query", "PROOF_QUERY", "Verification Query", "VERIFICATION_QUERY") or _text(
        hardened, "Proof Query", "Verification Query"
    )
    generated_sql = _text(row, "Generated SQL Fix", "GENERATED_SQL_FIX") or _text(hardened, "Generated SQL Fix")
    owner = _text(row, "Owner", "OWNER") or _text(hardened, "Owner Route", "Owner")
    approver = _text(row, "Approver", "APPROVER", "Review Group", "APPROVAL_GROUP")
    approval = _approval_state(row)
    blob = _upper_blob(
        _text(row, "Category", "CATEGORY"),
        _text(row, "Entity Type", "ENTITY_TYPE"),
        _text(row, "Finding", "FINDING"),
        _text(hardened, "Decision"),
        generated_sql,
    )

    if not _truthy_text(proof_query):
        blockers.append("telemetry query")
    if not _truthy_text(owner) or str(owner).upper() in {"DBA", "UNKNOWN", "UNASSIGNED"}:
        blockers.append("named escalation route")
    if _state_changing_sql(generated_sql) and approval not in {"APPROVED", "VERIFIED", "NOT REQUIRED"}:
        blockers.append("telemetry status")
    if _state_changing_sql(generated_sql) and not _truthy_text(approver):
        blockers.append("review route")
    if any(token in blob for token in ("DROP ", "TRUNCATE", "GRANT", "REVOKE", "ALTER ROLE", "ALTER USER", "FAILOVER", "EXECUTE TASK", "CALL ")):
        blockers.append("DBA review")
    if "CLUSTERING_DEPTH" in blob or "CLUSTERING_INFORMATION" in blob:
        blockers.append("clustering telemetry")
    if "NO SAFE AUTOMATIC SQL FIX" in blob:
        blockers.append("no safe SQL fix")
    return sorted(set(blockers))


def automation_readiness_for_row(row: Mapping | pd.Series | dict, *, source_surface: str = "Recommendations") -> dict:
    """Classify one recommendation/action row into a DBA queue lane."""
    hardened = harden_recommendation(row)
    generated_sql = _text(row, "Generated SQL Fix", "GENERATED_SQL_FIX") or _text(hardened, "Generated SQL Fix")
    proof_query = _text(row, "Proof Query", "PROOF_QUERY", "Verification Query", "VERIFICATION_QUERY") or _text(
        hardened, "Proof Query", "Verification Query"
    )
    blockers = _automation_blockers(row, hardened)
    safe_guided = _safe_guided_sql(generated_sql)
    changes_state = _state_changing_sql(generated_sql)
    closed_verified = _state_is_closed(row) and _verification_is_proved(row)
    approval = _approval_state(row)
    severity = _text(row, "Severity", "SEVERITY", default=_text(hardened, "Severity", default="Medium"))
    entity = _text(row, "Entity", "ENTITY", "ENTITY_NAME", default=_entity(hardened))
    category = _text(row, "Category", "CATEGORY", default=_text(hardened, "Category"))
    decision = _text(hardened, "Decision", default=_text(row, "Decision", "DECISION", default="Review finding"))
    contract = recommendation_execution_contract(hardened)

    score = 55
    if _truthy_text(proof_query):
        score += 15
    if safe_guided:
        score += 15
    if approval in {"APPROVED", "VERIFIED", "NOT REQUIRED"}:
        score += 10
    if _truthy_text(_text(row, "Owner", "OWNER", "Owner Route")):
        score += 5
    score -= len(blockers) * 12

    if closed_verified:
        lane = "Resolved Candidate"
        next_step = "The condition is closed in telemetry; keep it out of active work."
        mode = "Workflow closure"
    elif safe_guided and not blockers:
        lane = "Ready"
        next_step = "Use the guarded drilldown workflow when action is still needed."
        mode = "Guided action"
    elif safe_guided and set(blockers) <= {"telemetry status", "review route"}:
        lane = "Telemetry Pending"
        next_step = "Wait for telemetry to refresh before acting."
        mode = "Telemetry-gated"
    elif "DBA review" in blockers or "clustering telemetry" in blockers or "no safe SQL fix" in blockers:
        lane = "DBA Review"
        next_step = _text(hardened, "Safe Next Action", default="Open the guarded drilldown workflow for DBA review.")
        mode = "Human-controlled"
    elif blockers:
        lane = "Needs Data"
        next_step = "Load the missing telemetry before routing this to action or closure."
        mode = "Data-gated"
    else:
        lane = "Monitor"
        next_step = "Keep monitoring; do not create a change until severity, telemetry, or escalation route changes."
        mode = "Observation"

    score = max(0, min(100, score))
    return {
        "SOURCE_SURFACE": source_surface,
        "SEVERITY": severity or "Medium",
        "CATEGORY": category or "Recommendation",
        "ENTITY": entity,
        "DECISION": decision,
        "AUTOMATION_LANE": lane,
        "AUTOMATION_MODE": mode,
        "AUTOMATION_SCORE": round(float(score), 1),
        "BLOCKERS": ", ".join(blockers) if blockers else "none",
        "SAFE_AUTOMATION_STEP": next_step,
        "PROOF_REQUIRED": _text(hardened, "Proof Required", default="Telemetry must show the condition cleared."),
        "DO_NOT_DO": _text(hardened, "Do Not Do", default="Do not package queue work without source telemetry."),
        "APPROVAL_GATE": contract["APPROVAL_GATE"],
        "REVIEW_GATE": contract["REVIEW_GATE"],
        "EVIDENCE_PACKAGE": contract["EVIDENCE_PACKAGE"],
        "VERIFY_NEXT": contract["VERIFY_NEXT"],
        "EXECUTION_BOUNDARY": contract["EXECUTION_BOUNDARY"],
        "CLOSURE_RULE": contract["CLOSURE_RULE"],
        "APPROVAL_STATE": approval or "Not Captured",
        "STATE_CHANGING_SQL": "Yes" if changes_state else "No",
        "SAFE_GUIDED_SQL": "Yes" if safe_guided else "No",
        "GENERATED_SQL_FIX": generated_sql,
        "VERIFICATION_QUERY": proof_query,
    }


def _records_from_frame(frame: pd.DataFrame, *, source_surface: str) -> list[tuple[dict, str]]:
    if frame is None or frame.empty:
        return []
    view = frame.copy()
    return [(row.to_dict(), source_surface) for _, row in view.iterrows()]


def build_automation_readiness_board(
    recommendations: list[dict] | pd.DataFrame | None = None,
    action_queue: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a deterministic automation readiness board from loaded telemetry."""
    records: list[tuple[dict, str]] = []
    if isinstance(recommendations, pd.DataFrame):
        records.extend(_records_from_frame(recommendations, source_surface="Recommendations"))
    else:
        records.extend((dict(rec), "Recommendations") for rec in (recommendations or []))
    records.extend(_records_from_frame(action_queue, source_surface="Action Queue"))

    rows = [automation_readiness_for_row(row, source_surface=surface) for row, surface in records]
    if not rows:
        return pd.DataFrame(columns=[
            "SOURCE_SURFACE", "SEVERITY", "CATEGORY", "ENTITY", "DECISION",
            "AUTOMATION_LANE", "AUTOMATION_MODE", "AUTOMATION_SCORE", "BLOCKERS",
            "SAFE_AUTOMATION_STEP", "PROOF_REQUIRED", "DO_NOT_DO",
            "APPROVAL_GATE", "EVIDENCE_PACKAGE", "VERIFY_NEXT",
            "EXECUTION_BOUNDARY", "CLOSURE_RULE",
            "APPROVAL_STATE", "STATE_CHANGING_SQL", "SAFE_GUIDED_SQL",
            "GENERATED_SQL_FIX", "VERIFICATION_QUERY",
        ])
    frame = pd.DataFrame(rows)
    frame["_LANE_RANK"] = frame["AUTOMATION_LANE"].map(AUTOMATION_LANE_ORDER).fillna(9)
    severity_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
    frame["_SEVERITY_RANK"] = frame["SEVERITY"].map(severity_rank).fillna(5)
    return frame.sort_values(
        ["_LANE_RANK", "_SEVERITY_RANK", "AUTOMATION_SCORE", "ENTITY"],
        ascending=[True, True, False, True],
    ).drop(columns=["_LANE_RANK", "_SEVERITY_RANK"])


def _state_frame(state: Mapping | dict | None, key: str) -> pd.DataFrame:
    value = state.get(key) if isinstance(state, Mapping) else None
    return value.copy() if isinstance(value, pd.DataFrame) and not value.empty else pd.DataFrame()


def _advisor_severity_rank(value: object) -> int:
    return {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
        "INFO": 4,
    }.get(str(value or "").strip().upper(), 5)


def _advisor_route_from_warehouse_action(action_type: object) -> str:
    action = str(action_type or "").lower()
    if "capacity" in action or "cost movement" in action:
        return "Warehouse Health > Efficiency"
    if "timeout" in action or "auto-suspend" in action or "resource monitor" in action:
        return "Warehouse Health > Optimization Advisor"
    return "Warehouse Health"


def _advisor_add_signal(
    rows: list[dict],
    *,
    source_surface: str,
    severity: object,
    signal: object,
    entity: object,
    route: object,
    next_action: object,
    telemetry_basis: object = "",
    estimated_savings_usd: object = 0,
    value_at_risk_usd: object = 0,
    detail: object = "",
) -> None:
    sev = str(severity or "Medium").strip().title() or "Medium"
    rows.append({
        "SOURCE_SURFACE": str(source_surface or "Loaded advisor"),
        "SEVERITY": sev,
        "SIGNAL": str(signal or "Advisor finding"),
        "ENTITY": str(entity or "Unknown"),
        "ROUTE": str(route or "DBA Control Room"),
        "NEXT_ACTION": str(next_action or "Open the owning monitoring section and review loaded telemetry."),
        "TELEMETRY_BASIS": str(telemetry_basis or detail or "Loaded advisor telemetry."),
        "EST_MONTHLY_SAVINGS_USD": safe_float(estimated_savings_usd),
        "VALUE_AT_RISK_USD": abs(safe_float(value_at_risk_usd)),
        "DETAIL": str(detail or ""),
    })


def build_loaded_advisor_signal_board(state: Mapping | dict | None = None, *, limit: int = 18) -> pd.DataFrame:
    """Return advisor rows already loaded in Streamlit session state.

    This deliberately reads only in-memory section outputs. It does not query
    Snowflake and can be used by summary surfaces without adding scan cost.
    """
    rows: list[dict] = []
    state_map = state if isinstance(state, Mapping) else {}

    cost_board = _state_frame(state_map, "cost_contract_cost_advisor_board")
    if not cost_board.empty:
        for _, row in cost_board.head(8).iterrows():
            _advisor_add_signal(
                rows,
                source_surface="Cost Advisor",
                severity=_text(row, "SEVERITY", "PRIORITY", default="Medium"),
                signal=_text(row, "FINDING", "CATEGORY", default="Cost advisor finding"),
                entity=_text(row, "ENTITY", default="Cost signal"),
                route=_text(row, "WORKFLOW_ROUTE", default="Cost & Contract"),
                next_action=_text(row, "SAFE_NEXT_ACTION", default="Open Cost & Contract advisor detail."),
                telemetry_basis=_text(row, "VALIDATION_NEEDED", "PROOF_REQUIRED", default="Cost advisor telemetry."),
                estimated_savings_usd=_row_value(row, "EST_MONTHLY_SAVINGS_USD", default=0),
                value_at_risk_usd=_row_value(row, "EST_MONTHLY_IMPACT_USD", default=0),
                detail=_text(row, "TELEMETRY_SUMMARY", "EVIDENCE", default=""),
            )

    warehouse_plan = _state_frame(state_map, "wh_settings_action_plan")
    if not warehouse_plan.empty:
        for _, row in warehouse_plan.head(8).iterrows():
            _advisor_add_signal(
                rows,
                source_surface="Warehouse Settings Advisor",
                severity=_text(row, "PRIORITY", default="Medium"),
                signal=_text(row, "ACTION_TYPE", default="Warehouse setting review"),
                entity=_text(row, "WAREHOUSE_NAME", default="Unknown warehouse"),
                route=_advisor_route_from_warehouse_action(_row_value(row, "ACTION_TYPE")),
                next_action=_text(row, "SAFE_SETTING_MOVE", default="Open Warehouse Health setting detail."),
                telemetry_basis=_text(row, "PROOF_REQUIRED", "ROLLBACK_CHECK", default="Warehouse setting telemetry."),
                detail=_text(row, "WHY", default=""),
            )

    procedure_board = _state_frame(state_map, "sp_analysis_board")
    if not procedure_board.empty:
        for _, row in procedure_board.head(8).iterrows():
            credits = safe_float(_row_value(row, "EST_TOTAL_CREDITS", default=0))
            _advisor_add_signal(
                rows,
                source_surface="Stored Procedure Analysis",
                severity=_text(row, "PRIORITY", default="Medium"),
                signal=_text(row, "SIGNAL", "OPTIMIZATION_ISSUE", default="Procedure advisor signal"),
                entity=_text(row, "PROCEDURE_CONTEXT", "PROCEDURE_NAME", default="Unknown procedure"),
                route="Workload Operations > Stored Procedures",
                next_action=_text(row, "SAFE_NEXT_ACTION", default="Open Stored Procedures and compare CALL telemetry."),
                telemetry_basis=_text(row, "PROOF_REQUIRED", default="Procedure run and child-query telemetry."),
                value_at_risk_usd=credits * 3.68,
                detail=_text(row, "OPTIMIZATION_ISSUE", default=""),
            )

    cost_alerts = _state_frame(state_map, "cost_contract_monitoring_alerts")
    if not cost_alerts.empty:
        for _, row in cost_alerts.head(6).iterrows():
            _advisor_add_signal(
                rows,
                source_surface="Cost Monitoring Alerts",
                severity=_text(row, "SEVERITY", default="Medium"),
                signal=_text(row, "ALERT_TYPE", "SIGNAL_TYPE", default="Cost monitoring signal"),
                entity=_text(row, "ENTITY_NAME", "ENTITY", default="Cost alert"),
                route=_text(row, "ROUTE", default="Alert Center"),
                next_action=_text(row, "SUGGESTED_ACTION", "NEXT_ACTION", default="Open Alert Center or Cost & Contract incident timeline."),
                telemetry_basis=_text(row, "PROOF_QUERY", "PROOF_REQUIRED", default="Cost monitoring alert telemetry."),
                value_at_risk_usd=_row_value(row, "VALUE_AT_RISK_USD", default=0),
                detail=_text(row, "MESSAGE", "DETAIL", default=""),
            )

    if not rows:
        return pd.DataFrame(columns=[
            "SOURCE_SURFACE", "SEVERITY", "SIGNAL", "ENTITY", "ROUTE",
            "NEXT_ACTION", "TELEMETRY_BASIS", "EST_MONTHLY_SAVINGS_USD",
            "VALUE_AT_RISK_USD", "DETAIL", "PRIORITY_RANK",
        ])
    frame = pd.DataFrame(rows)
    frame["PRIORITY_RANK"] = frame["SEVERITY"].apply(_advisor_severity_rank)
    frame["_VALUE_RANK"] = (
        pd.to_numeric(frame["VALUE_AT_RISK_USD"], errors="coerce").fillna(0)
        + pd.to_numeric(frame["EST_MONTHLY_SAVINGS_USD"], errors="coerce").fillna(0)
    )
    return frame.sort_values(
        ["PRIORITY_RANK", "_VALUE_RANK", "SOURCE_SURFACE", "ENTITY"],
        ascending=[True, False, True, True],
    ).drop(columns=["_VALUE_RANK"], errors="ignore").head(max(1, int(limit))).reset_index(drop=True)


def warehouse_sizing_decision(row: Mapping | pd.Series | dict) -> dict:
    """Classify warehouse sizing telemetry without generic upsize advice."""
    warehouse = _entity(row)
    size = _text(row, "WAREHOUSE_SIZE", "Warehouse Size", default="unknown size")
    spill = _num(row, "REMOTE_SPILL_GB", "Remote Spill GB")
    queue_sec = _num(row, "AVG_QUEUE_SEC", "Avg Queue Sec")
    credits = _num(row, "TOTAL_CREDITS", "Total Credits")
    queries = safe_int(_row_value(row, "TOTAL_QUERIES", default=0))
    cache_pct = _num(row, "AVG_CACHE_PCT", "Avg Cache Pct")
    spill_threshold = safe_float(THRESHOLDS.get("spill_warning_gb", 5), 5)

    evidence = (
        f"{warehouse} ({size}): {queries:,} queries, {credits:,.2f} credits, "
        f"{queue_sec:,.2f}s avg queue, {spill:,.2f} GB remote spill, {cache_pct:,.1f}% cache."
    )

    def with_contract(result: dict) -> dict:
        contract = recommendation_execution_contract({
            "Source": "Warehouse right-sizing advisor",
            "Category": "Warehouse Optimization",
            "Entity Type": "Warehouse",
            "Entity": warehouse,
            "Finding": result["DECISION"],
            "Route": "Warehouse route / DBA capacity reviewer",
            "Evidence Packet": result["EVIDENCE_PACKET"],
            "Proof Required": result["PROOF_REQUIRED"],
        })
        result.update({
            "APPROVAL_GATE": contract["APPROVAL_GATE"],
            "EVIDENCE_PACKAGE": contract["EVIDENCE_PACKAGE"],
            "VERIFY_NEXT": contract["VERIFY_NEXT"],
            "EXECUTION_BOUNDARY": contract["EXECUTION_BOUNDARY"],
            "CLOSURE_RULE": contract["CLOSURE_RULE"],
        })
        return result

    if spill > spill_threshold and queue_sec > 5:
        return with_contract({
            "DECISION": "Capacity incident: validate isolation or one-step scale-up",
            "EVIDENCE_PACKET": evidence,
            "SAFE_NEXT_ACTION": "Capture top spilling query IDs, then run a controlled one-size-up or multi-cluster validation for the same workload window.",
            "PROOF_REQUIRED": "Queue seconds and remote spill GB both decline for the same workload class after the change.",
            "DO_NOT_DO": "Do not leave the larger setting permanent without before/after telemetry.",
        })
    if spill > spill_threshold:
        return with_contract({
            "DECISION": "Memory pressure: tune query shape first",
            "EVIDENCE_PACKET": evidence,
            "SAFE_NEXT_ACTION": "Inspect query profiles for joins, sorts, and scans that repeatedly spill before changing WAREHOUSE_SIZE.",
            "PROOF_REQUIRED": "Top spilling query IDs show lower spill after SQL, clustering, or warehouse-isolation work.",
            "DO_NOT_DO": "Do not upsize blindly; spill alone is not proof of under-sized compute.",
        })
    if queue_sec > 5:
        return with_contract({
            "DECISION": "Concurrency pressure: adjust scaling, not memory",
            "EVIDENCE_PACKET": evidence,
            "SAFE_NEXT_ACTION": "Check burst windows and MAX_CLUSTER_COUNT; prefer multi-cluster for concurrency if spill is low.",
            "PROOF_REQUIRED": "Queued overload time drops without a matching credit spike outside the target window.",
            "DO_NOT_DO": "Do not upsize just to reduce queueing when the symptom is concurrent demand.",
        })
    if credits < 1 and size.upper() not in {"", "X-SMALL", "XSMALL", "UNKNOWN SIZE"}:
        return with_contract({
            "DECISION": "Downsize candidate",
            "EVIDENCE_PACKET": evidence,
            "SAFE_NEXT_ACTION": "Ask the owner whether the workload is latency-sensitive, then validate one size down during the same usage window.",
            "PROOF_REQUIRED": "Runtime and failure rate stay stable while credits drop after the validation.",
            "DO_NOT_DO": "Do not downsize shared or SLA-sensitive warehouses without telemetry.",
        })
    return with_contract({
        "DECISION": "No sizing change from this evidence",
        "EVIDENCE_PACKET": evidence,
        "SAFE_NEXT_ACTION": "Keep monitoring; route only if queue, spill, or cost deltas cross thresholds.",
    "PROOF_REQUIRED": "No telemetry action needed unless a future setting change is proposed.",
        "DO_NOT_DO": "Do not create a change ticket from a clean sizing row.",
    })


def duplicate_query_decision(row: Mapping | pd.Series | dict) -> dict:
    signature = _text(row, "QUERY_SIG", "Query Sig", default="query pattern")
    executions = safe_int(_row_value(row, "EXECUTION_COUNT", default=0))
    users = safe_int(_row_value(row, "USER_COUNT", default=0))
    wasted_sec = _num(row, "TOTAL_WASTED_SEC", "Total Wasted Sec")
    cloud_credits = _num(row, "CLOUD_CREDITS", "Cloud Credits")
    result = {
        "DECISION": "Materialize or cache only if the same result is reused",
        "EVIDENCE_PACKET": (
            f"{executions:,} executions across {users:,} user(s), {wasted_sec:,.0f}s repeated runtime, "
            f"{cloud_credits:,.4f} cloud-services credits; signature: {signature[:120]}"
        ),
        "SAFE_NEXT_ACTION": "Confirm literals and result reuse, then choose result cache hygiene, dynamic table, or materialized view.",
        "PROOF_REQUIRED": "Execution count and total elapsed seconds drop for the same query signature.",
        "DO_NOT_DO": "Do not create a materialized view until the repeated query has stable semantics and workload demand.",
    }
    contract = recommendation_execution_contract({
        "Source": "Duplicate query advisor",
        "Category": "Query Optimization",
        "Entity Type": "Query",
        "Entity": signature[:120] or "query signature",
        "Finding": result["DECISION"],
        "Owner": "Query reviewer / DBA lead",
        "Evidence Packet": result["EVIDENCE_PACKET"],
        "Proof Required": result["PROOF_REQUIRED"],
    })
    result.update({
        "APPROVAL_GATE": contract["APPROVAL_GATE"],
        "EVIDENCE_PACKAGE": contract["EVIDENCE_PACKAGE"],
        "VERIFY_NEXT": contract["VERIFY_NEXT"],
        "EXECUTION_BOUNDARY": contract["EXECUTION_BOUNDARY"],
        "CLOSURE_RULE": contract["CLOSURE_RULE"],
    })
    return result
