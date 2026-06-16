# utils/scorecards.py - shared service and control-plane scoring formulas
from __future__ import annotations


DBA_CONTROL_PLANE_RUBRIC = (
    {
        "key": "domain_coverage",
        "label": "DBA Domain Coverage",
        "weight": 20,
        "definition": "Covers the section's assigned DBA work: cost, access, task/procedure reliability, or warehouse administration.",
    },
    {
        "key": "data_correctness",
        "label": "Data Correctness & Scope",
        "weight": 15,
        "definition": "Uses the right Snowflake sources, company/environment scope, freshness/source-basis labels, and defensible formulas.",
    },
    {
        "key": "actionability",
        "label": "Actionability",
        "weight": 15,
        "definition": "Turns findings into clear DBA next actions with severity, owner path, proof, and generated or suggested remediation.",
    },
    {
        "key": "admin_safety_audit",
        "label": "Admin Safety & Audit",
        "weight": 15,
        "definition": "State-changing actions require guardrails, confirmation, before/after context, immutable audit, and rollback guidance.",
    },
    {
        "key": "performance_mart",
        "label": "Performance & Mart Strategy",
        "weight": 10,
        "definition": "Prefers compact fast summaries, avoids surprise live scans, caches appropriately, and exposes data readiness.",
    },
    {
        "key": "workflow_ux",
        "label": "DBA Workflow UX",
        "weight": 10,
        "definition": "Organizes dense DBA evidence around observe, diagnose, act, audit, and verify without burying the first move.",
    },
    {
        "key": "tests_operability",
        "label": "Tests & Operability",
        "weight": 15,
        "definition": "Has regression coverage, deployment checks, role capability checks, and clear fallback behavior.",
    },
)

DBA_CONTROL_PLANE_COMPONENTS = tuple(item["key"] for item in DBA_CONTROL_PLANE_RUBRIC)

DBA_CONTROL_PLANE_SECTION_READINESS_INPUTS = {
    "Executive Landing": {
        "domain_coverage": 86,
        "data_correctness": 80,
        "actionability": 82,
        "admin_safety_audit": 72,
        "performance_mart": 84,
        "workflow_ux": 84,
        "tests_operability": 82,
    },
    "DBA Control Room": {
        "domain_coverage": 82,
        "data_correctness": 78,
        "actionability": 85,
        "admin_safety_audit": 74,
        "performance_mart": 78,
        "workflow_ux": 76,
        "tests_operability": 82,
    },
    "Alert Center": {
        "domain_coverage": 82,
        "data_correctness": 80,
        "actionability": 84,
        "admin_safety_audit": 76,
        "performance_mart": 82,
        "workflow_ux": 80,
        "tests_operability": 84,
    },
    "Workload Operations": {
        "domain_coverage": 84,
        "data_correctness": 78,
        "actionability": 86,
        "admin_safety_audit": 74,
        "performance_mart": 78,
        "workflow_ux": 76,
        "tests_operability": 82,
    },
    "Cost & Contract": {
        "domain_coverage": 86,
        "data_correctness": 84,
        "actionability": 86,
        "admin_safety_audit": 78,
        "performance_mart": 82,
        "workflow_ux": 80,
        "tests_operability": 84,
    },
    "Security Monitoring": {
        "domain_coverage": 80,
        "data_correctness": 78,
        "actionability": 80,
        "admin_safety_audit": 76,
        "performance_mart": 76,
        "workflow_ux": 74,
        "tests_operability": 82,
    },
}

DBA_CONTROL_PLANE_SECTION_BASELINE = DBA_CONTROL_PLANE_SECTION_READINESS_INPUTS

DBA_CONTROL_PLANE_SECTION_NEXT_MOVES = {
    "Executive Landing": "Connect executive decisions to live monitoring status and measured closure back on the landing page.",
    "DBA Control Room": "Connect the operating board to status writes for measured auto-close.",
    "Alert Center": "Replace placeholder notification rows with production distribution lists and sync alert lifecycle to closure telemetry.",
    "Workload Operations": "Wire recovery command-board rows to successful rerun telemetry.",
    "Cost & Contract": "Replace placeholder email routes with production cost distribution lists and measured savings auto-close.",
    "Security Monitoring": "Keep security posture focused on login risk, grant exposure, public access, data sharing, and alert telemetry.",
}


def clamp_score(value: float) -> float:
    """Return a score bounded to 0..100."""
    try:
        return round(max(0.0, min(100.0, float(value))), 1)
    except Exception:
        return 0.0


def score_label(score: float) -> str:
    """Standard score band used across executive metrics."""
    score = float(score or 0)
    if score >= 90:
        return "Healthy"
    if score >= 75:
        return "Watch"
    if score >= 60:
        return "At Risk"
    return "Critical"


def dba_readiness_label(score: float) -> str:
    """Strict readiness band for DBA control-plane section scoring."""
    score = float(score or 0)
    if score >= 95:
        return "95 Target"
    if score >= 90:
        return "Near Target"
    if score >= 80:
        return "Operational"
    if score >= 70:
        return "Pilot"
    return "Not Ready"


def dba_deployment_label(score: float) -> str:
    """Deployment-facing readiness band after live gates are applied."""
    score = float(score or 0)
    if score >= 95:
        return "Ready"
    if score >= 90:
        return "Ready With Watch"
    if score >= 80:
        return "Action Required"
    return "Blocked"


def platform_operating_score_from_signals(metrics: dict) -> dict:
    """Evidence-based executive platform score from current command-board signals."""
    current_cost = float(metrics.get("current_cost_usd", 0) or 0)
    prior_cost = float(metrics.get("prior_cost_usd", 0) or 0)
    spend_delta = float(metrics.get("spend_delta_cost_usd", current_cost - prior_cost) or 0)
    critical_high = float(metrics.get("critical_high_alerts", 0) or 0)
    open_actions = float(metrics.get("open_actions", 0) or 0)
    failed_tasks = float(metrics.get("failed_tasks", 0) or 0)
    failed_queries = float(metrics.get("failed_queries", 0) or 0)
    queue_seconds = float(metrics.get("queue_seconds", 0) or 0)
    remote_spill_gb = float(metrics.get("remote_spill_gb", 0) or 0)
    stale_sources = float(metrics.get("stale_sources", 0) or 0)
    freshness_sources = float(metrics.get("freshness_sources", 0) or 0)

    spend_pct = spend_delta / max(abs(prior_cost), 1.0) if spend_delta > 0 else 0.0
    penalties = {
        "Cost movement": min(18.0, spend_pct * 35.0),
        "Critical/high alerts": min(24.0, critical_high * 8.0),
        "Open owner actions": min(18.0, open_actions * 1.2),
        "Task failures": min(18.0, failed_tasks * 4.0),
        "Query failures": min(14.0, failed_queries * 0.8),
        "Queue pressure": min(10.0, queue_seconds / 600.0),
        "Remote spill": min(8.0, remote_spill_gb / 25.0),
        "Stale sources": min(18.0, stale_sources * 6.0),
    }
    raw_score = clamp_score(100.0 - sum(penalties.values()))

    caps: list[tuple[float, str]] = []
    if stale_sources:
        caps.append((82.0, f"{int(stale_sources)} stale source(s) in the command mart."))
    if critical_high:
        caps.append((85.0, f"{int(critical_high)} critical/high alert(s) are open."))
    if failed_tasks:
        caps.append((88.0, f"{int(failed_tasks)} failed task run(s) in scope."))
    if open_actions >= 10:
        caps.append((90.0, f"{int(open_actions)} owner action(s) remain open."))
    if freshness_sources <= 0:
        caps.append((78.0, "No freshness proof rows were available for the monitoring summary."))

    score_cap = min((cap for cap, _reason in caps), default=100.0)
    cap_reason = next((reason for cap, reason in sorted(caps, key=lambda item: item[0]) if cap == score_cap), "")
    final_score = clamp_score(min(raw_score, score_cap))
    drivers = [
        {
            "DRIVER": name,
            "STATE": "Ready" if penalty <= 0 else "Review",
            "SCORE_IMPACT": round(-penalty, 1),
            "EVIDENCE": _platform_driver_evidence(name, metrics),
            "NEXT_ACTION": _platform_driver_action(name),
        }
        for name, penalty in penalties.items()
        if penalty > 0
    ]
    drivers.sort(key=lambda row: (row["SCORE_IMPACT"], row["DRIVER"]))
    return {
        "score": int(round(final_score)),
        "raw_score": raw_score,
        "state": score_label(final_score),
        "score_cap": int(round(score_cap)),
        "cap_reason": cap_reason or "No hard cap applied.",
        "platform_score_drivers": drivers,
    }


def _platform_driver_evidence(driver: str, metrics: dict) -> str:
    if driver == "Cost movement":
        return f"${float(metrics.get('spend_delta_cost_usd', 0) or 0):,.0f} spend movement."
    if driver == "Critical/high alerts":
        return f"{int(float(metrics.get('critical_high_alerts', 0) or 0)):,} critical/high alert(s)."
    if driver == "Open owner actions":
        return f"{int(float(metrics.get('open_actions', 0) or 0)):,} open owner action(s)."
    if driver == "Task failures":
        return f"{int(float(metrics.get('failed_tasks', 0) or 0)):,} failed task run(s)."
    if driver == "Query failures":
        return f"{int(float(metrics.get('failed_queries', 0) or 0)):,} failed query signal(s)."
    if driver == "Queue pressure":
        return f"{float(metrics.get('queue_seconds', 0) or 0) / 60.0:,.1f} queued minute(s)."
    if driver == "Remote spill":
        return f"{float(metrics.get('remote_spill_gb', 0) or 0):,.1f} GB remote spill."
    if driver == "Stale sources":
        return f"{int(float(metrics.get('stale_sources', 0) or 0)):,} stale source(s)."
    return "Evidence available in monitoring summary."


def _platform_driver_action(driver: str) -> str:
    actions = {
        "Cost movement": "Open Cost & Contract and prove the top cost driver before changing cost controls.",
        "Critical/high alerts": "Open Alert Center and assign owner, SLA, and remediation state.",
        "Open owner actions": "Open DBA Control Room and work the owner action queue.",
        "Task failures": "Open Workload Operations task graphs and inspect failed root/child task evidence.",
        "Query failures": "Open Query Diagnosis with failed query evidence and owner route.",
        "Queue pressure": "Open Workload Operations and separate capacity queueing from lock contention.",
        "Remote spill": "Open Query Diagnosis and inspect joins, scans, and warehouse memory pressure.",
        "Stale sources": "Refresh or repair the scheduled mart task before acting on stale evidence.",
    }
    return actions.get(driver, "Open the owning command surface and attach proof.")


def bad_ratio_score(total: float, bad: float, penalty: float = 100.0) -> float:
    """Score a bad-event ratio with a category-specific penalty weight."""
    total = float(total or 0)
    bad = max(float(bad or 0), 0.0)
    if total <= 0:
        return 100.0
    return clamp_score(100.0 - ((bad / total) * float(penalty or 100.0)))


def trend_score(current: float, prior: float, warning_pct: float, critical_pct: float, no_prior_score: float = 90.0) -> float:
    """Score an upward trend. Flat or lower is healthy; large increases are risky."""
    current = float(current or 0)
    prior = float(prior or 0)
    if prior <= 0:
        return 100.0 if current <= 0 else clamp_score(no_prior_score)
    delta_pct = ((current - prior) / prior) * 100.0
    if delta_pct <= 0:
        return 100.0
    if delta_pct <= warning_pct:
        return 100.0
    if delta_pct <= critical_pct:
        span = max(critical_pct - warning_pct, 1.0)
        return clamp_score(100.0 - ((delta_pct - warning_pct) / span) * 40.0)
    return clamp_score(60.0 - min(60.0, ((delta_pct - critical_pct) / max(critical_pct, 1.0)) * 60.0))


def weighted_score(components: list[dict]) -> float:
    """Weighted average for component rows with SCORE and WEIGHT keys."""
    total_weight = sum(float(c.get("WEIGHT", 0) or 0) for c in components)
    if total_weight <= 0:
        return 100.0
    score = sum(float(c.get("SCORE", 100) or 0) * float(c.get("WEIGHT", 0) or 0) for c in components)
    return clamp_score(score / total_weight)


def dba_control_plane_readiness_score(component_scores: dict) -> dict:
    """Score a DBA section against the fixed control-plane rubric.

    This is intentionally stricter than a feature-completeness score. A section
    cannot reach 95 if critical control-plane dimensions are weak, even when the
    weighted average looks high.
    """
    components = []
    by_key = {}
    for item in DBA_CONTROL_PLANE_RUBRIC:
        key = item["key"]
        score = clamp_score(component_scores.get(key, 0))
        row = {
            "COMPONENT": item["label"],
            "KEY": key,
            "SCORE": score,
            "WEIGHT": item["weight"],
            "DEFINITION": item["definition"],
        }
        components.append(row)
        by_key[key] = score

    raw_score = weighted_score(components)
    caps = []
    if any(by_key[key] < 70 for key in DBA_CONTROL_PLANE_COMPONENTS):
        caps.append({
            "CAP": 84.0,
            "REASON": "At least one rubric component is below 70; the section is not a reliable DBA operating surface.",
        })
    if by_key["data_correctness"] < 85:
        caps.append({
            "CAP": 89.0,
            "REASON": "Data correctness/scope is below 85; the section cannot be scored as production-ready.",
        })
    if by_key["admin_safety_audit"] < 85:
        caps.append({
            "CAP": 89.0,
            "REASON": "Admin safety/audit is below 85; the section cannot be trusted as a control plane.",
        })
    if raw_score >= 95 and any(by_key[key] < 90 for key in DBA_CONTROL_PLANE_COMPONENTS):
        caps.append({
            "CAP": 94.0,
            "REASON": "A 95+ score requires every rubric component to be at least 90.",
        })
    if raw_score >= 95 and any(
        by_key[key] < 95 for key in ("data_correctness", "admin_safety_audit", "tests_operability")
    ):
        caps.append({
            "CAP": 94.0,
            "REASON": "A 95+ score requires data correctness, admin safety/audit, and tests/operability to be at least 95.",
        })

    cap_value = min((cap["CAP"] for cap in caps), default=100.0)
    final_score = clamp_score(min(raw_score, cap_value))
    return {
        "score": final_score,
        "raw_score": raw_score,
        "label": dba_readiness_label(final_score),
        "components": components,
        "caps": caps,
    }


def dba_effective_readiness_score(readiness_score: float, gates: dict | None = None) -> dict:
    """Apply live deployment gates to a section's built-readiness score.

    The base score answers whether the section is built as a DBA control plane.
    This effective score answers whether the currently loaded deployment state
    is safe enough to rely on.
    """
    base_score = clamp_score(readiness_score)
    gate_rows = []
    for key, gate in (gates or {}).items():
        if isinstance(gate, dict):
            gate_score = clamp_score(gate.get("score", 100))
            label = str(gate.get("label") or key).strip()
            state = str(gate.get("state") or dba_deployment_label(gate_score)).strip()
            reason = str(gate.get("reason") or "").strip()
        else:
            gate_score = clamp_score(gate)
            label = str(key).replace("_", " ").title()
            state = dba_deployment_label(gate_score)
            reason = ""
        gate_rows.append({
            "KEY": str(key),
            "GATE": label,
            "SCORE": gate_score,
            "STATE": state,
            "REASON": reason,
        })

    gate_floor = min((row["SCORE"] for row in gate_rows), default=100.0)
    effective_score = clamp_score(min(base_score, gate_floor))
    blocking = [
        row for row in gate_rows
        if row["SCORE"] <= effective_score or row["SCORE"] < base_score
    ]
    blocking.sort(key=lambda row: row["SCORE"])
    return {
        "score": effective_score,
        "base_score": base_score,
        "label": dba_deployment_label(effective_score),
        "gates": gate_rows,
        "gate_drivers": blocking,
    }


def _cap_driver_label(reason: str) -> str:
    reason_lower = str(reason or "").lower()
    if "below 70" in reason_lower:
        return "weak component"
    if "data correctness" in reason_lower:
        return "data correctness/scope"
    if "admin safety" in reason_lower:
        return "admin safety/audit"
    if "ownership" in reason_lower:
        return "ownership/routing"
    if "every rubric component" in reason_lower:
        return "all components >=90"
    if "critical control-plane" in reason_lower:
        return "critical controls >=95"
    return str(reason or "score cap")


def dba_control_plane_section_scorecards(
    section_scores: dict | None = None,
    deployment_gates: dict | None = None,
) -> list[dict]:
    """Return strict readiness rows for the DBA workflow sections."""
    section_scores = section_scores or DBA_CONTROL_PLANE_SECTION_READINESS_INPUTS
    deployment_gates = deployment_gates or {}
    rows = []
    for section, scores in section_scores.items():
        result = dba_control_plane_readiness_score(scores)
        effective = dba_effective_readiness_score(
            result["score"],
            deployment_gates.get(section, {}),
        )
        lowest = min(result["components"], key=lambda row: row["SCORE"])
        cap_drivers = []
        for cap in result["caps"]:
            label = _cap_driver_label(cap.get("REASON", ""))
            if label not in cap_drivers:
                cap_drivers.append(label)
        gate_drivers = []
        for gate in effective["gate_drivers"]:
            label = str(gate.get("GATE") or gate.get("KEY") or "").strip()
            if label and label not in gate_drivers:
                gate_drivers.append(label)
        rows.append({
            "SECTION": section,
            "SCORE": result["score"],
            "EFFECTIVE_SCORE": effective["score"],
            "RAW_SCORE": result["raw_score"],
            "LABEL": result["label"],
            "DEPLOYMENT_LABEL": effective["label"],
            "LOWEST_COMPONENT": lowest["COMPONENT"],
            "LOWEST_SCORE": lowest["SCORE"],
            "CAP_DRIVERS": ", ".join(cap_drivers) if cap_drivers else "none",
            "GATE_DRIVERS": ", ".join(gate_drivers) if gate_drivers else "none",
            "NEXT_95_MOVE": DBA_CONTROL_PLANE_SECTION_NEXT_MOVES.get(section, "Raise weak control-plane components."),
        })
    return rows


def dba_control_plane_component_rows(section_scores: dict | None = None) -> list[dict]:
    """Return component-level readiness rows for section diagnostics."""
    section_scores = section_scores or DBA_CONTROL_PLANE_SECTION_READINESS_INPUTS
    rows = []
    for section, scores in section_scores.items():
        result = dba_control_plane_readiness_score(scores)
        for component in result["components"]:
            rows.append({
                "SECTION": section,
                "COMPONENT": component["COMPONENT"],
                "SCORE": component["SCORE"],
                "WEIGHT": component["WEIGHT"],
                "DEFINITION": component["DEFINITION"],
            })
    return rows


def burn_trend_label(short_avg: float, long_avg: float, tolerance: float = 0.15) -> str:
    """Compare short and long burn rates."""
    short_avg = float(short_avg or 0)
    long_avg = float(long_avg or 0)
    if long_avg <= 0 and short_avg <= 0:
        return "No data"
    if long_avg <= 0:
        return "Accelerating"
    delta = (short_avg - long_avg) / long_avg
    if delta > tolerance:
        return "Accelerating"
    if delta < -tolerance:
        return "Cooling"
    return "Stable"


def executive_health_score(metrics: dict) -> dict:
    """Composite executive health score for Usage Overview and Account Health."""
    total_queries = float(metrics.get("total_queries", 0) or 0)
    components = [
        {
            "COMPONENT": "Query failures",
            "SCORE": bad_ratio_score(total_queries, metrics.get("failed_queries", 0), 160),
            "WEIGHT": 25,
            "SIGNAL": f"{float(metrics.get('failed_queries', 0) or 0):,.0f} failed of {total_queries:,.0f} queries",
        },
        {
            "COMPONENT": "Queue pressure",
            "SCORE": bad_ratio_score(total_queries, metrics.get("queued_queries", 0), 90),
            "WEIGHT": 15,
            "SIGNAL": f"{float(metrics.get('queued_queries', 0) or 0):,.0f} queued queries",
        },
        {
            "COMPONENT": "Latency",
            "SCORE": clamp_score(100 - min(45, max(float(metrics.get("avg_elapsed_sec", 0) or 0) - 2, 0) * 4)),
            "WEIGHT": 10,
            "SIGNAL": f"{float(metrics.get('avg_elapsed_sec', 0) or 0):,.2f}s average elapsed",
        },
        {
            "COMPONENT": "Task reliability",
            "SCORE": bad_ratio_score(metrics.get("task_runs", 0), metrics.get("failed_tasks", 0), 225),
            "WEIGHT": 15,
            "SIGNAL": f"{float(metrics.get('failed_tasks', 0) or 0):,.0f} failed task runs",
        },
        {
            "COMPONENT": "Warehouse pressure",
            "SCORE": bad_ratio_score(metrics.get("active_warehouses", 0), metrics.get("pressure_warehouses", 0), 160),
            "WEIGHT": 15,
            "SIGNAL": f"{float(metrics.get('pressure_warehouses', 0) or 0):,.0f} pressured warehouses",
        },
        {
            "COMPONENT": "Credit spike",
            "SCORE": trend_score(metrics.get("current_credits", 0), metrics.get("prior_credits", 0), 20, 60),
            "WEIGHT": 12,
            "SIGNAL": f"{float(metrics.get('current_credits', 0) or 0):,.1f} vs {float(metrics.get('prior_credits', 0) or 0):,.1f} prior credits",
        },
        {
            "COMPONENT": "Storage growth",
            "SCORE": trend_score(metrics.get("current_storage_tb", 0), metrics.get("prior_storage_tb", 0), 5, 25, no_prior_score=95),
            "WEIGHT": 8,
            "SIGNAL": f"{float(metrics.get('current_storage_tb', 0) or 0):,.2f} TB active storage",
        },
    ]
    score = weighted_score(components)
    return {"score": score, "label": score_label(score), "components": components}


def service_health_scorecard(metrics: dict) -> dict:
    """Weighted service scorecard where service classes carry different severity."""
    query_total = float(metrics.get("total_queries", 0) or 0)
    query_bad = (
        float(metrics.get("failed_queries", 0) or 0)
        + float(metrics.get("queued_queries", 0) or 0) * 0.35
        + float(metrics.get("blocked_queries", 0) or 0) * 1.25
    )
    query_score = bad_ratio_score(query_total, query_bad, 140)
    query_score = clamp_score(query_score - min(20, max(float(metrics.get("p95_elapsed_sec", 0) or 0) - 60, 0) / 12))

    components = [
        {
            "SERVICE": "Query Processor",
            "SCORE": query_score,
            "WEIGHT": 30,
            "SIGNAL": (
                f"{float(metrics.get('failed_queries', 0) or 0):,.0f} failed, "
                f"{float(metrics.get('queued_queries', 0) or 0):,.0f} queued, "
                f"{float(metrics.get('blocked_queries', 0) or 0):,.0f} blocked."
            ),
        },
        {
            "SERVICE": "Warehouse Availability",
            "SCORE": bad_ratio_score(metrics.get("warehouse_count", 0), metrics.get("pressured_warehouses", 0), 180),
            "WEIGHT": 25,
            "SIGNAL": f"{float(metrics.get('pressured_warehouses', 0) or 0):,.0f} warehouses have queue, spill, or failures.",
        },
        {
            "SERVICE": "Task Service",
            "SCORE": bad_ratio_score(metrics.get("task_runs", 0), metrics.get("failed_tasks", 0), 240),
            "WEIGHT": 20,
            "SIGNAL": f"{float(metrics.get('failed_tasks', 0) or 0):,.0f} failed task runs.",
        },
        {
            "SERVICE": "Login/Auth",
            "SCORE": bad_ratio_score(metrics.get("login_events", 0), metrics.get("failed_logins", 0), 45),
            "WEIGHT": 15,
            "SIGNAL": f"{float(metrics.get('failed_logins', 0) or 0):,.0f} failed login events.",
        },
        {
            "SERVICE": "Data Load",
            "SCORE": bad_ratio_score(metrics.get("load_events", 0), metrics.get("failed_loads", 0), 160),
            "WEIGHT": 10,
            "SIGNAL": f"{float(metrics.get('failed_loads', 0) or 0):,.0f} failed load events.",
        },
    ]
    score = weighted_score(components)
    return {"score": score, "label": score_label(score), "components": components}
