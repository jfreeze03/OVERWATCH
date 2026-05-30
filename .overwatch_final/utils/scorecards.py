# utils/scorecards.py - shared executive and service scoring formulas
from __future__ import annotations


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
