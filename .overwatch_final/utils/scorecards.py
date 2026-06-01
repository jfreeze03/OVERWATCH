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
        "definition": "Uses the right Snowflake sources, company/environment scope, freshness/confidence labels, and defensible formulas.",
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
        "definition": "Prefers compact mart facts, avoids surprise live scans, caches appropriately, and exposes source health.",
    },
    {
        "key": "workflow_ux",
        "label": "DBA Workflow UX",
        "weight": 10,
        "definition": "Organizes dense DBA evidence around observe, diagnose, act, audit, and verify without burying the first move.",
    },
    {
        "key": "governance_ownership",
        "label": "Governance & Ownership",
        "weight": 10,
        "definition": "Connects objects, warehouses, roles, users, tasks, procedures, and findings to owners and approval context.",
    },
    {
        "key": "tests_operability",
        "label": "Tests & Operability",
        "weight": 5,
        "definition": "Has regression coverage, deployment checks, role capability checks, and clear fallback behavior.",
    },
)

DBA_CONTROL_PLANE_COMPONENTS = tuple(item["key"] for item in DBA_CONTROL_PLANE_RUBRIC)

DBA_CONTROL_PLANE_SECTION_BASELINE = {
    "DBA Control Room": {
        "domain_coverage": 95,
        "data_correctness": 95,
        "actionability": 96,
        "admin_safety_audit": 95,
        "performance_mart": 96,
        "workflow_ux": 95,
        "governance_ownership": 95,
        "tests_operability": 95,
    },
    "Alert Center": {
        "domain_coverage": 94,
        "data_correctness": 95,
        "actionability": 97,
        "admin_safety_audit": 96,
        "performance_mart": 96,
        "workflow_ux": 95,
        "governance_ownership": 96,
        "tests_operability": 98,
    },
    "Workload Operations": {
        "domain_coverage": 95,
        "data_correctness": 95,
        "actionability": 98,
        "admin_safety_audit": 96,
        "performance_mart": 96,
        "workflow_ux": 95,
        "governance_ownership": 96,
        "tests_operability": 98,
    },
    "Warehouse Health": {
        "domain_coverage": 95,
        "data_correctness": 95,
        "actionability": 96,
        "admin_safety_audit": 95,
        "performance_mart": 96,
        "workflow_ux": 94,
        "governance_ownership": 95,
        "tests_operability": 97,
    },
    "Architecture Readiness": {
        "domain_coverage": 96,
        "data_correctness": 95,
        "actionability": 98,
        "admin_safety_audit": 96,
        "performance_mart": 96,
        "workflow_ux": 95,
        "governance_ownership": 96,
        "tests_operability": 98,
    },
    "Cost & Contract": {
        "domain_coverage": 97,
        "data_correctness": 98,
        "actionability": 99,
        "admin_safety_audit": 97,
        "performance_mart": 97,
        "workflow_ux": 97,
        "governance_ownership": 97,
        "tests_operability": 100,
    },
    "Security Posture": {
        "domain_coverage": 95,
        "data_correctness": 95,
        "actionability": 97,
        "admin_safety_audit": 95,
        "performance_mart": 96,
        "workflow_ux": 95,
        "governance_ownership": 96,
        "tests_operability": 98,
    },
    "Change & Drift": {
        "domain_coverage": 95,
        "data_correctness": 95,
        "actionability": 96,
        "admin_safety_audit": 95,
        "performance_mart": 96,
        "workflow_ux": 94,
        "governance_ownership": 95,
        "tests_operability": 97,
    },
    "Account Health": {
        "domain_coverage": 95,
        "data_correctness": 96,
        "actionability": 97,
        "admin_safety_audit": 95,
        "performance_mart": 96,
        "workflow_ux": 95,
        "governance_ownership": 95,
        "tests_operability": 98,
    },
}

DBA_CONTROL_PLANE_SECTION_NEXT_MOVES = {
    "DBA Control Room": "Connect the operating board to live ITSM ticket state and execution audit writes for verified auto-close.",
    "Alert Center": "Replace placeholder owner rows with named ALFA on-call groups and enable the approved Snowflake notification integration.",
    "Workload Operations": "Replace placeholder owner rows with named pipeline/procedure owners and wire recovery audit rows to the ITSM ticket lifecycle.",
    "Warehouse Health": "Connect warehouse operability facts to live owner/ITSM approval and auto-close verified setting-change evidence.",
    "Architecture Readiness": "Persist architecture, AI/MCP, Openflow, Horizon, semantic-trust, and DR-drill evidence into mart facts with verified closure history.",
    "Cost & Contract": "Replace placeholder owner rows with named ALFA cost owners and connect owner approval to the ITSM closure workflow.",
    "Security Posture": "Connect IAM/ITSM approval state to verified auto-close for privileged grant and access-review actions.",
    "Change & Drift": "Ingest live change tickets/source-control state, then auto-close verified approval and closure evidence from ITSM/deployment systems.",
    "Account Health": "Connect queued checklist and access-hygiene actions to live IAM/ITSM approval state and verified auto-close.",
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
    if by_key["governance_ownership"] < 80:
        caps.append({
            "CAP": 92.0,
            "REASON": "Governance/ownership is below 80; findings are not consistently accountable.",
        })
    if raw_score >= 95 and any(by_key[key] < 90 for key in DBA_CONTROL_PLANE_COMPONENTS):
        caps.append({
            "CAP": 94.0,
            "REASON": "A 95+ score requires every rubric component to be at least 90.",
        })
    if raw_score >= 95 and any(
        by_key[key] < 95 for key in ("data_correctness", "admin_safety_audit", "governance_ownership")
    ):
        caps.append({
            "CAP": 94.0,
            "REASON": "A 95+ score requires data correctness, admin safety/audit, and governance/ownership to be at least 95.",
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


def _cap_driver_label(reason: str) -> str:
    reason_lower = str(reason or "").lower()
    if "below 70" in reason_lower:
        return "weak component"
    if "data correctness" in reason_lower:
        return "data correctness/scope"
    if "admin safety" in reason_lower:
        return "admin safety/audit"
    if "governance" in reason_lower:
        return "governance/ownership"
    if "every rubric component" in reason_lower:
        return "all components >=90"
    if "critical control-plane" in reason_lower:
        return "critical controls >=95"
    return str(reason or "score cap")


def dba_control_plane_section_scorecards(section_scores: dict | None = None) -> list[dict]:
    """Return strict readiness rows for the DBA workflow sections."""
    section_scores = section_scores or DBA_CONTROL_PLANE_SECTION_BASELINE
    rows = []
    for section, scores in section_scores.items():
        result = dba_control_plane_readiness_score(scores)
        lowest = min(result["components"], key=lambda row: row["SCORE"])
        cap_drivers = []
        for cap in result["caps"]:
            label = _cap_driver_label(cap.get("REASON", ""))
            if label not in cap_drivers:
                cap_drivers.append(label)
        rows.append({
            "SECTION": section,
            "SCORE": result["score"],
            "RAW_SCORE": result["raw_score"],
            "LABEL": result["label"],
            "LOWEST_COMPONENT": lowest["COMPONENT"],
            "LOWEST_SCORE": lowest["SCORE"],
            "CAP_DRIVERS": ", ".join(cap_drivers) if cap_drivers else "none",
            "NEXT_95_MOVE": DBA_CONTROL_PLANE_SECTION_NEXT_MOVES.get(section, "Raise weak control-plane components."),
        })
    return rows


def dba_control_plane_component_rows(section_scores: dict | None = None) -> list[dict]:
    """Return component-level readiness rows for section diagnostics."""
    section_scores = section_scores or DBA_CONTROL_PLANE_SECTION_BASELINE
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
