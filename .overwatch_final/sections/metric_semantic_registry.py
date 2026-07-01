"""Canonical summary metric semantics for Decision Workspace first paint.

The packet renderer must know whether a metric is a count, duration, USD
amount, credit amount, percent, or proxy/risk score before it formats the
value.  This registry keeps that contract close to the section view-model and
gives launch tests a raw-row proof surface for impossible formula regressions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class MetricSemantic:
    section: str
    metric_key: str
    label: str
    description: str
    source_family: str
    source_object: str
    packet_field: str
    aggregation: str
    value_unit: str
    metric_format: str
    expected_min: float | None = None
    expected_max: float | None = None
    expected_max_reason: str = ""
    missing_source_behavior: str = "unavailable"
    fallback_behavior: str = "compact unavailable state"
    owner: str = "OVERWATCH launch readiness"
    launch_validation_query_or_fixture: str = "summary_packet_fixture"
    proxy_metric: bool = False
    zero_policy: str = "zero is valid only when source confirms zero"
    unavailable_policy: str = "render compact unavailable state"
    live_validation_source: str = "fixture_static"
    cost_db_mapping: str = ""

    def to_artifact(self) -> dict[str, Any]:
        return asdict(self)

    def outlier_reason(self, value: float | None) -> str:
        if value is None:
            return ""
        if self.expected_min is not None and value < self.expected_min:
            return f"{self.metric_key} below expected minimum {self.expected_min:g}"
        if self.expected_max is not None and value > self.expected_max:
            return f"{self.metric_key} above expected maximum {self.expected_max:g}"
        return ""


PRIMARY_METRIC_KEYS: Mapping[str, tuple[str, ...]] = {
    "Executive Landing": ("total_spend", "critical_high_issues", "open_actions", "cortex_spend"),
    "DBA Control Room": ("failed_queries", "pipeline_failures", "queue_pressure", "cost_24h"),
    "Alert Center": ("active_alerts", "critical_high", "overdue_alerts", "cortex_predictive"),
    "Cost & Contract": ("total_spend", "spend_movement_pct", "cortex_spend", "forecast_run_rate"),
    "Workload Operations": ("failed_queries", "pipeline_failures", "queue_blocked_pressure", "sla_risk"),
    "Security Monitoring": ("failed_logins", "credential_expirations", "mfa_gaps", "risky_grants"),
}


def _sem(
    section: str,
    metric_key: str,
    label: str,
    *,
    description: str,
    source_family: str,
    source_object: str,
    aggregation: str,
    value_unit: str,
    metric_format: str,
    expected_min: float | None = 0,
    expected_max: float | None = None,
    expected_max_reason: str = "",
    packet_field: str = "",
    missing_source_behavior: str = "unavailable",
    fallback_behavior: str = "compact unavailable state",
    launch_validation_query_or_fixture: str = "summary_packet_fixture",
    proxy_metric: bool = False,
    zero_policy: str = "zero is valid only when source confirms zero",
    unavailable_policy: str = "render compact unavailable state",
    live_validation_source: str = "fixture_static",
    cost_db_mapping: str = "",
) -> MetricSemantic:
    return MetricSemantic(
        section=section,
        metric_key=metric_key,
        label=label,
        description=description,
        source_family=source_family,
        source_object=source_object,
        packet_field=packet_field or metric_key.upper(),
        aggregation=aggregation,
        value_unit=value_unit,
        metric_format=metric_format,
        expected_min=expected_min,
        expected_max=expected_max,
        expected_max_reason=expected_max_reason,
        missing_source_behavior=missing_source_behavior,
        fallback_behavior=fallback_behavior,
        launch_validation_query_or_fixture=launch_validation_query_or_fixture,
        proxy_metric=proxy_metric,
        zero_policy=zero_policy,
        unavailable_policy=unavailable_policy,
        live_validation_source=live_validation_source,
        cost_db_mapping=cost_db_mapping,
    )


_ROWS: tuple[MetricSemantic, ...] = (
    _sem(
        "Executive Landing",
        "total_spend",
        "Total Spend",
        description="Snowsight-style account billed cost for the completed billing window.",
        source_family="account_billing",
        source_object="completed account billing history",
        aggregation="sum account billed USD",
        value_unit="usd",
        metric_format="compact_currency",
        expected_max_reason="Account spend scales by customer and selected window.",
        packet_field="ACCOUNT_BILLED_COST_USD",
        zero_policy="zero requires completed account billing rows proving zero spend",
        unavailable_policy="Billing reconciliation pending",
        live_validation_source="billing_reconciliation_live_or_fixture",
        cost_db_mapping="account_billed_total",
    ),
    _sem(
        "Executive Landing",
        "critical_high_issues",
        "Critical / High",
        description="Open critical or high launch signals.",
        source_family="alerts_actions",
        source_object="alert/action summaries",
        aggregation="count open high-priority signals",
        value_unit="count",
        metric_format="integer",
        expected_max=100_000,
    ),
    _sem(
        "Executive Landing",
        "open_actions",
        "Open Actions",
        description="Open action queue items.",
        source_family="action_queue",
        source_object="action queue summary",
        aggregation="count open actions",
        value_unit="count",
        metric_format="integer",
        expected_max=100_000,
    ),
    _sem(
        "Executive Landing",
        "cortex_spend",
        "Cortex AI Spend",
        description="Canonical Cortex AI spend for the same completed billing window.",
        source_family="cortex_billing",
        source_object="completed account billing history",
        aggregation="sum Cortex service billed USD",
        value_unit="usd",
        metric_format="compact_currency",
        expected_max_reason="Cortex spend scales by account and selected window.",
        packet_field="CORTEX_AI_COST_USD",
        zero_policy="zero requires completed Cortex service rows proving zero spend",
        unavailable_policy="Cortex spend unavailable until billing reconciliation loads",
        live_validation_source="billing_reconciliation_live_or_fixture",
        cost_db_mapping="cortex_ai",
    ),
    _sem(
        "DBA Control Room",
        "failed_queries",
        "Failed SQL",
        description="Failed query executions in the selected summary window.",
        source_family="query_hourly",
        source_object="compact query summary",
        aggregation="sum failed query count",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "DBA Control Room",
        "pipeline_failures",
        "Pipeline Failures",
        description="Failed tasks, procedures, and copy/load events.",
        source_family="task_runs",
        source_object="task/procedure/copy summaries",
        aggregation="sum failed event count",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "DBA Control Room",
        "queue_pressure",
        "Queue Pressure",
        description="Queued execution pressure.",
        source_family="query_hourly",
        source_object="compact query summary",
        aggregation="sum queued seconds",
        value_unit="seconds",
        metric_format="duration",
        expected_max=90 * 24 * 3600,
    ),
    _sem(
        "DBA Control Room",
        "cost_24h",
        "Cost 24h",
        description="Recent DBA-owned cost pressure.",
        source_family="cost_daily",
        source_object="cost summary",
        aggregation="sum USD",
        value_unit="usd",
        metric_format="compact_currency",
        expected_max_reason="Cost scales by account and selected scope.",
        packet_field="WAREHOUSE_COST_USD",
        zero_policy="zero requires completed bridge rows proving zero cost",
        unavailable_policy="Cost bridge unavailable until billing reconciliation loads",
        live_validation_source="billing_reconciliation_live_or_fixture",
        cost_db_mapping="warehouse_bridge",
    ),
    _sem(
        "Alert Center",
        "active_alerts",
        "Active Alerts",
        description="Open active alert events.",
        source_family="alert_events",
        source_object="alert summaries",
        aggregation="count active alerts",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "Alert Center",
        "critical_high",
        "Critical / High",
        description="Open critical and high alert events.",
        source_family="alert_events",
        source_object="alert summaries",
        aggregation="count critical/high alerts",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "Alert Center",
        "overdue_alerts",
        "Overdue Alerts",
        description="Alerts past due SLA.",
        source_family="alert_events",
        source_object="alert summaries",
        aggregation="count overdue alerts",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "Alert Center",
        "cortex_predictive",
        "Cortex Predictive",
        description="Cortex forecast, anomaly, or run-rate alerts.",
        source_family="alert_events",
        source_object="alert summaries",
        aggregation="count predictive alerts",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "Cost & Contract",
        "total_spend",
        "Total Spend",
        description="Snowsight-style account billed cost for the completed billing window.",
        source_family="account_billing",
        source_object="completed account billing history",
        aggregation="sum account billed USD",
        value_unit="usd",
        metric_format="compact_currency",
        expected_max_reason="Account spend scales by customer and selected window.",
        packet_field="ACCOUNT_BILLED_COST_USD",
        zero_policy="zero requires completed account billing rows proving zero spend",
        unavailable_policy="Billing reconciliation pending",
        live_validation_source="billing_reconciliation_live_or_fixture",
        cost_db_mapping="account_billed_total",
    ),
    _sem(
        "Cost & Contract",
        "spend_movement_pct",
        "Spend Movement",
        description="Percent movement against the previous comparable window.",
        source_family="account_billing",
        source_object="completed account billing history",
        aggregation="percent change",
        value_unit="percent",
        metric_format="percentage",
        expected_min=-100,
        expected_max_reason="Percent changes can spike on small denominators.",
        packet_field="SPEND_MOVEMENT_PCT",
        zero_policy="zero requires comparable completed billing windows proving no movement",
        unavailable_policy="Spend movement pending until comparable billing windows are available",
        live_validation_source="billing_reconciliation_live_or_fixture",
        cost_db_mapping="monthly_mom",
    ),
    _sem(
        "Cost & Contract",
        "cortex_spend",
        "Cortex AI Spend",
        description="Canonical Cortex AI spend for the same completed billing window.",
        source_family="cortex_billing",
        source_object="completed account billing history",
        aggregation="sum Cortex service billed USD",
        value_unit="usd",
        metric_format="compact_currency",
        expected_max_reason="Cortex spend scales by account and selected window.",
        packet_field="CORTEX_AI_COST_USD",
        zero_policy="zero requires completed Cortex service rows proving zero spend",
        unavailable_policy="Cortex spend unavailable until billing reconciliation loads",
        live_validation_source="billing_reconciliation_live_or_fixture",
        cost_db_mapping="cortex_ai",
    ),
    _sem(
        "Cost & Contract",
        "forecast_run_rate",
        "Forecast / Run-rate",
        description="Projected month-end cost or run-rate forecast.",
        source_family="forecast",
        source_object="forecast summary",
        aggregation="forecast USD",
        value_unit="usd",
        metric_format="compact_currency",
        expected_max_reason="Forecast scales by account and selected window.",
        packet_field="FORECAST_RUN_RATE_USD",
        zero_policy="zero requires completed account billing rows and forecast input proving zero run-rate",
        unavailable_policy="Forecast pending until billing reconciliation and run-rate inputs load",
        live_validation_source="billing_reconciliation_live_or_fixture",
        cost_db_mapping="account_billed_total",
    ),
    _sem(
        "Workload Operations",
        "failed_queries",
        "Failed SQL",
        description="Failed query executions in the selected summary window.",
        source_family="query_hourly",
        source_object="compact query summary",
        aggregation="sum failed query count",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "Workload Operations",
        "pipeline_failures",
        "Pipeline / Task Failures",
        description="Failed task, procedure, copy, and load events.",
        source_family="task_runs",
        source_object="task/procedure/copy summaries",
        aggregation="sum failed event count",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "Workload Operations",
        "queue_blocked_pressure",
        "Queue / Blocked Pressure",
        description="Queued or blocked workload pressure.",
        source_family="query_hourly",
        source_object="compact query summary",
        aggregation="sum queued seconds",
        value_unit="seconds",
        metric_format="duration",
        expected_max=90 * 24 * 3600,
    ),
    _sem(
        "Workload Operations",
        "sla_risk",
        "Pipeline Failure Risk",
        description="Bounded proxy risk score from failed pipeline events and queue pressure.",
        source_family="task_runs",
        source_object="task/procedure/copy summaries",
        aggregation="bounded risk score",
        value_unit="risk_score",
        metric_format="percentage",
        expected_min=0,
        expected_max=100,
        fallback_behavior="show proxy label and risk-score unit",
        proxy_metric=True,
    ),
    _sem(
        "Security Monitoring",
        "failed_logins",
        "Failed Logins",
        description="Failed login signals.",
        source_family="login_daily",
        source_object="security summaries",
        aggregation="count failed logins",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "Security Monitoring",
        "credential_expirations",
        "Credential Expirations",
        description="Expired credentials and credentials due within 30 days from the compact credential mart.",
        source_family="credential_expiration",
        source_object="compact credential expiration summary",
        aggregation="expired count plus expiring-within-30-days count",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
        packet_field="SECURITY_CREDENTIALS_EXPIRING_30D_COUNT",
        zero_policy="zero requires credential source availability proving no due credentials",
        unavailable_policy="Credential expiration source pending",
        live_validation_source="credential_expiration_live_or_fixture",
    ),
    _sem(
        "Security Monitoring",
        "mfa_gaps",
        "MFA Gaps",
        description="Users or principals missing required MFA posture.",
        source_family="security_operability",
        source_object="security summaries",
        aggregation="count gaps",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "Security Monitoring",
        "risky_grants",
        "Risky Grants",
        description="Grant/access review blockers.",
        source_family="grant_daily",
        source_object="security summaries",
        aggregation="count risky grants",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
    _sem(
        "Security Monitoring",
        "sharing_exposure",
        "Sharing Exposure",
        description="Cross-account sharing exposure signals.",
        source_family="sharing",
        source_object="security summaries",
        aggregation="count exposures",
        value_unit="count",
        metric_format="integer",
        expected_max=1_000_000,
    ),
)

METRIC_SEMANTICS: Mapping[tuple[str, str], MetricSemantic] = {
    (row.section, row.metric_key): row for row in _ROWS
}


def get_metric_semantic(section: str, metric_key: str) -> MetricSemantic | None:
    return METRIC_SEMANTICS.get((str(section or ""), str(metric_key or "")))


def all_metric_semantics() -> tuple[MetricSemantic, ...]:
    return _ROWS


def _numeric_value(metric: object) -> float | None:
    value = metric.get("numeric_value") if isinstance(metric, Mapping) else getattr(metric, "numeric_value", None)
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _field(metric: object, name: str, default: object = "") -> object:
    return metric.get(name, default) if isinstance(metric, Mapping) else getattr(metric, name, default)


def validate_metric_semantics(section: str, metrics: Sequence[object]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for metric in tuple(metrics or ()):
        metric_key = str(_field(metric, "key") or _field(metric, "metric_key") or "")
        if not metric_key:
            continue
        seen.add(metric_key)
        semantic = get_metric_semantic(section, metric_key)
        numeric = _numeric_value(metric)
        fmt = str(_field(metric, "metric_format") or "").strip().lower()
        unit = str(_field(metric, "unit") or _field(metric, "value_unit") or "").strip().lower()
        available = bool(_field(metric, "available", True))
        failures: list[str] = []
        if semantic is None:
            failures.append("missing_metric_semantic")
        else:
            if fmt and fmt not in {semantic.metric_format, "count" if semantic.metric_format == "integer" else semantic.metric_format}:
                failures.append("metric_format_mismatch")
            if unit and unit.lower() not in {semantic.value_unit.lower(), "usd" if semantic.value_unit == "usd" else semantic.value_unit.lower()}:
                if not (semantic.value_unit == "count" and unit in {"events", "queries", "alerts", "actions", "findings", "signals", "warnings"}):
                    failures.append("value_unit_mismatch")
            outlier = semantic.outlier_reason(numeric)
            if outlier:
                failures.append("semantic_outlier")
            if not available and numeric == 0 and str(_field(metric, "availability_state") or "").lower() in {"", "available"}:
                failures.append("missing_source_silently_zero")
            if semantic.proxy_metric and "proxy" not in f"{semantic.label} {semantic.description}".lower():
                failures.append("proxy_metric_missing_label")
            if semantic.value_unit in {"usd", "credits"} and not semantic.cost_db_mapping:
                failures.append("cost_metric_missing_cost_db_mapping")
            if semantic.value_unit in {"usd", "credits"} and "unavailable" not in semantic.unavailable_policy.lower() and "pending" not in semantic.unavailable_policy.lower():
                failures.append("cost_metric_missing_unavailable_policy")
        rows.append(
            {
                "section": section,
                "metric_key": metric_key,
                "registered": semantic is not None,
                "packet_field": semantic.packet_field if semantic else "",
                "source_family": semantic.source_family if semantic else "",
                "source_object": semantic.source_object if semantic else "",
                "value_unit": semantic.value_unit if semantic else unit,
                "metric_format": semantic.metric_format if semantic else fmt,
                "observed_format": fmt,
                "observed_unit": unit,
                "numeric_value": numeric,
                "expected_min": semantic.expected_min if semantic else None,
                "expected_max": semantic.expected_max if semantic else None,
                "expected_max_reason": semantic.expected_max_reason if semantic else "",
                "zero_policy": semantic.zero_policy if semantic else "",
                "unavailable_policy": semantic.unavailable_policy if semantic else "",
                "live_validation_source": semantic.live_validation_source if semantic else "",
                "cost_db_mapping": semantic.cost_db_mapping if semantic else "",
                "passed": not failures,
                "failures": failures,
                "recommendation": "" if not failures else "Align packet metric formula, unit, and renderer semantics before launch.",
            }
        )
    for metric_key in PRIMARY_METRIC_KEYS.get(section, ()):
        if metric_key not in seen:
            semantic = get_metric_semantic(section, metric_key)
            rows.append(
                {
                    "section": section,
                    "metric_key": metric_key,
                    "registered": semantic is not None,
                    "packet_field": semantic.packet_field if semantic else "",
                    "source_family": semantic.source_family if semantic else "",
                    "source_object": semantic.source_object if semantic else "",
                    "value_unit": semantic.value_unit if semantic else "",
                    "metric_format": semantic.metric_format if semantic else "",
                    "observed_format": "",
                    "observed_unit": "",
                    "numeric_value": None,
                    "expected_min": semantic.expected_min if semantic else None,
                    "expected_max": semantic.expected_max if semantic else None,
                    "expected_max_reason": semantic.expected_max_reason if semantic else "",
                    "zero_policy": semantic.zero_policy if semantic else "",
                    "unavailable_policy": semantic.unavailable_policy if semantic else "",
                    "live_validation_source": semantic.live_validation_source if semantic else "",
                    "cost_db_mapping": semantic.cost_db_mapping if semantic else "",
                    "passed": False,
                    "failures": ["primary_metric_missing"],
                    "recommendation": "Packet must expose every primary metric or render an explicit unavailable state.",
                }
            )
    return rows


def build_metric_semantic_artifact(metrics_by_section: Mapping[str, Sequence[object]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for section, metrics in metrics_by_section.items():
        rows.extend(validate_metric_semantics(section, metrics))
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "metric_semantic_registry",
        "proof_source": "packet_formula_recompute",
        "passed": not failures,
        "section_count": len(metrics_by_section),
        "metric_row_count": len(rows),
        "failure_count": len(failures),
        "failures": failures,
        "registry": [row.to_artifact() for row in _ROWS],
        "raw_sql_included": False,
    }


__all__ = [
    "METRIC_SEMANTICS",
    "PRIMARY_METRIC_KEYS",
    "MetricSemantic",
    "all_metric_semantics",
    "build_metric_semantic_artifact",
    "get_metric_semantic",
    "validate_metric_semantics",
]
