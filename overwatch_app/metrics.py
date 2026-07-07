"""Rendered v2 metric registry."""

from __future__ import annotations

RENDERED_METRICS: dict[str, tuple[str, ...]] = {
    "Executive Landing": (
        "executive_narrative",
        "platform_score_decomposition",
        "contract_burn_down",
        "forecast_budget_variance_usd",
        "critical_high_issues",
        "open_work_items",
        "source_freshness",
        "top_cost_driver",
        "overwatch_self_cost",
    ),
    "Cost Intelligence": (
        "cost_narrative",
        "contract_burn_down_chart",
        "forecast_budget_bounds_chart",
        "top_cost_drivers",
        "cost_kpis",
        "tag_free_chargeback",
    ),
    "Alert Center": (
        "alert_kpis",
        "alert_lifecycle_filters",
        "alert_inbox",
        "alert_intelligence",
        "alert_detail_panel",
    ),
    "DBA Control Room": (
        "morning_cockpit",
        "live_running_queries",
        "blocked_sessions",
        "warehouse_queue_pressure",
        "failed_tasks_last_hour",
        "query_kill_audit",
    ),
    "Workload Operations": (
        "query_failure_rate",
        "error_code_frequency",
        "top_error_code",
        "failed_query_trend",
        "p95_query_duration",
        "remote_spill_gb",
        "queries_waiting",
        "blocked_time",
        "task_success_rate",
        "sla_attainment",
        "query_anomaly_detection",
    ),
    "Security Monitoring": (
        "failed_login_spike",
        "same_ip_multiple_users",
        "same_user_multiple_ips",
        "failures_followed_by_success",
        "unusual_client_type",
        "privileged_user_involvement",
        "off_hours_signal",
        "security_confidence",
    ),
}


REGISTERED_METRICS = RENDERED_METRICS


def unrendered_metrics() -> dict[str, tuple[str, ...]]:
    return {}
