"""Alert Center first-paint and loaded operating lane summaries."""
from __future__ import annotations

from sections.base import lazy_pandas
from sections.alert_center_boards import _open_alert_mask


pd = lazy_pandas()


def _alert_command_lanes(
    *,
    active_view: str,
    required_sources: set[str],
    alerts: object | None = None,
    queue: object | None = None,
    issues: object | None = None,
    delivery_log: object | None = None,
    loaded: bool = False,
) -> list[dict[str, str]]:
    """Return alert monitoring lanes without loading new data."""
    if not loaded:
        source_text = ", ".join(sorted(required_sources)) if required_sources else "no source load required"
        return [
            {"label": "Critical / high", "value": "Summary unavailable", "state": "Severity", "detail": f"{active_view} will read: {source_text}."},
            {"label": "Overdue SLA", "value": "Summary unavailable", "state": "Aging", "detail": "Open alerts need route, acknowledgement, suppression, or resolution."},
            {"label": "Security risk", "value": "Summary unavailable", "state": "Security", "detail": "Failed logins, risky grants, exfiltration, and policy drift route here."},
            {"label": "Cost", "value": "Summary unavailable", "state": "Spend", "detail": "Runaway spend, warehouse spikes, Cortex spend, and spend risk."},
            {"label": "Cortex predictive alerts", "value": "Summary unavailable", "state": "AI cost", "detail": "Forecasted Cortex spend, usage anomalies, and contract/run-rate exposure."},
            {"label": "Performance", "value": "Summary unavailable", "state": "Queries", "detail": "Long, queued, failed, spilling, and blocked query signals."},
            {"label": "Pipeline reliability", "value": "Summary unavailable", "state": "Tasks", "detail": "Failed, skipped, late, or suspended task/procedure paths."},
            {"label": "Data quality", "value": "Configured", "state": "Rules", "detail": "Metadata-driven freshness, row count, null, duplicate, and schema checks."},
            {"label": "Notification route", "value": "Summary unavailable", "state": "Delivery", "detail": "Email/webhook/native-alert delivery remains audit-backed."},
        ]

    alerts = alerts if isinstance(alerts, pd.DataFrame) else pd.DataFrame()
    queue = queue if isinstance(queue, pd.DataFrame) else pd.DataFrame()
    issues = issues if isinstance(issues, pd.DataFrame) else pd.DataFrame()
    delivery_log = delivery_log if isinstance(delivery_log, pd.DataFrame) else pd.DataFrame()
    open_alerts = _open_alert_mask(alerts) if not alerts.empty else pd.Series(dtype=bool)
    severity = alerts.get("SEVERITY", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str) if not alerts.empty else pd.Series(dtype=str)
    category = alerts.get("CATEGORY", pd.Series(index=alerts.index, dtype=str)).fillna("").astype(str).str.upper() if not alerts.empty else pd.Series(dtype=str)
    critical_high = int((severity.isin(["Critical", "High"]) & open_alerts).sum()) if not alerts.empty else 0
    overdue = int((alerts["SLA_STATE"].fillna("").astype(str).eq("Overdue") & open_alerts).sum()) if not alerts.empty and "SLA_STATE" in alerts.columns else 0
    open_queue = int((~queue["STATUS"].fillna("New").astype(str).str.title().isin(["Fixed", "Ignored"])).sum()) if not queue.empty and "STATUS" in queue.columns else 0
    delivery_failures = int(delivery_log["DELIVERY_STATUS"].fillna("").astype(str).str.upper().str.contains("FAILED|ERROR|BOUNCED", regex=True).sum()) if not delivery_log.empty and "DELIVERY_STATUS" in delivery_log.columns else 0

    def cat_count(*needles: str) -> int:
        if category.empty:
            return 0
        mask = pd.Series(False, index=category.index)
        for needle in needles:
            mask = mask | category.str.contains(needle, regex=False)
        return int((mask & open_alerts).sum())

    def cortex_alert_count() -> int:
        if alerts.empty:
            return 0
        searchable = [
            column for column in (
                "CATEGORY", "ALERT_TYPE", "SIGNAL", "ENTITY_NAME",
                "SUGGESTED_ACTION", "DESCRIPTION", "DETAIL",
            )
            if column in alerts.columns
        ]
        if not searchable:
            return cat_count("CORTEX", "AI")
        text = alerts[searchable].fillna("").astype(str).agg(" ".join, axis=1).str.upper()
        cortex_mask = text.str.contains("CORTEX| AI |AI /|AI_", regex=True)
        predictive_mask = text.str.contains("PREDICT|FORECAST|ANOMAL|RUN[- ]?RATE|SPEND|COST", regex=True)
        return int((cortex_mask & predictive_mask & open_alerts).sum())

    cortex_predictive = cortex_alert_count()
    return [
        {"label": "Critical / high", "value": f"{critical_high:,}", "state": "Severity" if critical_high else "Clear", "detail": f"{int(open_alerts.sum()) if not open_alerts.empty else 0:,} open alert(s) in loaded scope."},
        {"label": "Overdue SLA", "value": f"{overdue:,}", "state": "Aging" if overdue else "Clear", "detail": "Overdue high-severity rows should be acknowledged or escalated first."},
        {"label": "Security risk", "value": f"{cat_count('SECURITY'):,}", "state": "Security", "detail": "Login, privilege, sharing, and access anomalies."},
        {"label": "Cost", "value": f"{cat_count('COST'):,}", "state": "Spend", "detail": "Warehouse, Cortex, service-cost, and spend risk signals."},
        {"label": "Cortex predictive alerts", "value": f"{cortex_predictive:,}", "state": "AI cost" if cortex_predictive else "Clear", "detail": "Forecasted Cortex spend, usage anomalies, and contract/run-rate exposure."},
        {"label": "Performance", "value": f"{cat_count('PERFORMANCE', 'QUERY', 'WAREHOUSE'):,}", "state": "Queries", "detail": "Long, queued, failed, spilling, and blocked queries."},
        {"label": "Pipeline reliability", "value": f"{cat_count('TASK', 'PIPELINE', 'PROCEDURE'):,}", "state": "Tasks", "detail": "Task/procedure failures, late runs, and recovery alerts."},
        {"label": "Action queue", "value": f"{open_queue:,}", "state": "Routes", "detail": f"{len(issues):,} unified issue row(s) loaded."},
        {"label": "Delivery failures", "value": f"{delivery_failures:,}", "state": "Delivery" if delivery_failures else "Ready", "detail": f"{len(delivery_log):,} notification audit row(s)."},
    ]


__all__ = ["_alert_command_lanes"]
