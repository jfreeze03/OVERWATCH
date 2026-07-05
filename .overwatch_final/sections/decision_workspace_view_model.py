"""Data-bound view model for the OVERWATCH Decision Workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Mapping, Sequence, cast

from sections.metric_semantic_registry import MetricSemantic, get_metric_semantic
from utils.display_safety import contains_raw_source_token, safe_source_label, scrub_daily_text


@dataclass(frozen=True)
class DecisionMetricCell:
    key: str
    label: str
    value: str
    detail: str = ""
    tone: str = "neutral"
    trend_points: tuple[object, ...] = ()
    available: bool = True
    availability_state: str = "Available"
    trend_period: str = ""
    trend_point_count: int = 0
    trend_quality: str = ""
    zero_fill_policy: str = ""


@dataclass(frozen=True)
class DecisionFinding:
    severity: str
    signal: str
    entity: str = ""
    detail: str = ""
    owner: str = ""
    sla: str = ""
    finding_key: str = ""
    dedupe_key: str = ""
    entity_type: str = ""
    entity_id: str = ""
    entity_name: str = ""
    evidence_id: str = ""
    owner_id: str = ""
    owner_name: str = ""
    first_seen_label: str = ""
    due_label: str = ""
    evidence_source: str = ""
    evidence_query: str = ""
    owner_gap: bool = False
    route_key: str = ""


@dataclass(frozen=True)
class DecisionActionView:
    label: str
    cta: str
    action_key: str = ""
    route_key: str = ""


@dataclass(frozen=True)
class DecisionTrustView:
    summary: str
    mode_label: str
    freshness_label: str
    target_label: str
    coverage_label: str
    quality_label: str
    fixture_badge: bool = False
    trend_quality_label: str = ""


@dataclass(frozen=True)
class DecisionSourceRow:
    source_key: str
    source_object: str
    status: str
    required: bool
    age_label: str
    target_label: str
    confidence: str
    supports_environment: bool = False
    environment_scope_label: str = ""
    gap_reason: str = ""
    source_label: str = ""


@dataclass(frozen=True)
class DecisionFallbackView:
    mode: str
    title: str
    message: str
    recovery_label: str
    technical_summary: str
    can_initialize: bool = False
    can_show_evidence: bool = False


@dataclass(frozen=True)
class DecisionWorkspaceViewModel:
    section: str
    workflow: str
    state: str
    state_token: str
    headline: str
    summary: str
    freshness_label: str
    metric_cells: tuple[DecisionMetricCell, ...]
    additional_metrics: tuple[DecisionMetricCell, ...]
    findings: tuple[DecisionFinding, ...]
    actions: tuple[DecisionActionView, ...]
    trends: tuple[DecisionMetricCell, ...]
    trust: DecisionTrustView
    source_rows: tuple[DecisionSourceRow, ...] = ()
    fallback: DecisionFallbackView | None = None
    has_sources: bool = False
    fixture_badge_label: str = ""
    can_refresh: bool = True
    can_load_evidence: bool = False
    fixture_mode: bool = False
    source_mode: str = "scheduled_mart"


def _compact_number(value: float, *, decimals: int = 1) -> str:
    numeric = _finite_float(value)
    if numeric is None:
        return "Unavailable"
    sign = "-" if numeric < 0 else ""
    value = abs(numeric)
    if value >= 1_000_000_000:
        return f"{sign}{value / 1_000_000_000:.{decimals}f}B"
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.{decimals}f}M"
    if value >= 1_000:
        return f"{sign}{value / 1_000:.{decimals}f}K"
    if value == int(value):
        return f"{sign}{int(value)}"
    return f"{sign}{value:.{decimals}f}"


def _finite_float(value: object) -> float | None:
    try:
        numeric = float(cast(Any, value))
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _finite_int(value: object, default: int = 0) -> int:
    numeric = _finite_float(value)
    return int(round(numeric)) if numeric is not None else int(default)


def format_metric_value(
    metric: object,
    *,
    metric_format: str | None = None,
    value_unit: str | None = None,
) -> str:
    numeric = _finite_float(getattr(metric, "numeric_value", None))
    fmt = str(metric_format if metric_format is not None else getattr(metric, "metric_format", "") or "").strip().lower()
    unit = str(value_unit if value_unit is not None else getattr(metric, "unit", "") or "").strip()
    if numeric is None:
        return (
            str(getattr(metric, "text_value", "") or "")
            or str(getattr(metric, "value", "") or "")
            or "Unavailable"
        )
    if fmt in {"currency", "compact_currency"}:
        return f"${_compact_number(numeric)}"
    if fmt in {"percentage", "percent"}:
        return f"{numeric:.1f}%"
    if fmt in {"integer", "count"}:
        return _compact_number(numeric, decimals=0)
    if fmt == "duration":
        if numeric >= 3600:
            return f"{numeric / 3600:.1f}h"
        if numeric >= 60:
            return f"{numeric / 60:.1f}m"
        return f"{numeric:.0f}s"
    if fmt == "credits":
        return f"{_compact_number(numeric)} credits"
    if unit:
        return f"{_compact_number(numeric)} {unit}"
    return _compact_number(numeric)


_SOURCE_LABEL_OVERRIDES: dict[str, str] = {
    "action_queue": "Action queue",
    "acknowledgements": "Acknowledgements",
    "alert_events": "Alert events",
    "app_observability": "App observability",
    "change_summary": "Change intelligence",
    "closed_loop": "Closed-loop operations",
    "copy_load": "Copy load history",
    "cortex_daily": "Cortex usage",
    "cost_daily": "Cost usage",
    "cost_signals": "Cost signals",
    "data_trust": "Data trust",
    "dba_control_room": "DBA control summary",
    "executive_forecast": "Executive forecast",
    "executive_observability": "Executive observability",
    "executive_scorecard": "Executive scorecard",
    "forecast": "Forecast",
    "grant_daily": "Access grants",
    "login_daily": "Login activity",
    "notification_log": "Notification delivery",
    "owner_coverage": "Owner coverage",
    "procedure_runs": "Procedure runs",
    "production_readiness": "Production readiness",
    "query_hourly": "Query history summary",
    "query_recent": "Recent query detail",
    "security_alerts": "Security alerts",
    "security_operability": "Security operability",
    "settings": "Settings",
    "task_runs": "Task runs",
    "value_ledger": "Value ledger",
}


def _friendly_source_label(source_key: str) -> str:
    cleaned = (source_key or "source").strip().lower()
    if contains_raw_source_token(source_key):
        return safe_source_label(source_key)
    return _SOURCE_LABEL_OVERRIDES.get(cleaned, cleaned.replace("_", " ").title())


def _environment_scope_label(scope_mode: str, supports_environment: bool) -> str:
    normalized = (scope_mode or "").strip().lower().replace("_", " ")
    if "exact" in normalized:
        return "Exact environment source"
    if "fallback" in normalized or normalized == "all":
        return "All-environment fallback source"
    if not supports_environment or "not applicable" in normalized:
        return "Not environment-scoped source"
    return normalized.title() if normalized else ""


def _friendly_gap_reason(gap_reason: str, *, required: bool) -> str:
    normalized = (gap_reason or "").strip()
    if not normalized:
        return "No source gap reported"
    if contains_raw_source_token(normalized):
        return "Source unavailable" if required else "Optional source missing"
    if "stale" in normalized.lower():
        return "Source stale"
    if "missing" in normalized.lower() or "unavailable" in normalized.lower():
        return "Source unavailable" if required else "Optional source missing"
    return scrub_daily_text(normalized)


def _delta_label(metric: object) -> str:
    delta_percent = _finite_float(getattr(metric, "delta_percent", None))
    if delta_percent is not None:
        sign = "+" if delta_percent >= 0 else ""
        return f"{sign}{delta_percent:.1f}%"
    delta_numeric = _finite_float(getattr(metric, "delta_numeric_value", None))
    if delta_numeric is not None:
        sign = "+" if delta_numeric >= 0 else ""
        return f"{sign}{_compact_number(delta_numeric)}"
    return str(getattr(metric, "trend", "") or getattr(metric, "detail", "") or "")


def _preferred_metrics(section: str) -> tuple[str, ...]:
    return {
        "Executive Landing": ("total_spend", "critical_high_issues", "open_actions", "cortex_spend"),
        "Cost & Contract": ("total_spend", "spend_movement_pct", "cortex_spend", "forecast_run_rate"),
        "Alert Center": ("active_alerts", "critical_high", "overdue_alerts", "cortex_predictive"),
        "DBA Control Room": ("failed_queries", "pipeline_failures", "queue_pressure", "cost_24h"),
        "Workload Operations": ("failed_queries", "pipeline_failures", "queue_blocked_pressure", "sla_risk"),
        "Security Monitoring": ("failed_logins", "credential_expirations", "mfa_gaps", "risky_grants"),
    }.get(str(section or ""), ())


def _metric_numeric(metric: object) -> float | None:
    return _finite_float(getattr(metric, "numeric_value", None))


def _metric_availability_state(metric: object, semantic: MetricSemantic | None, outlier_reason: str = "") -> str:
    if outlier_reason:
        return "Formula check required"
    state = str(getattr(metric, "availability_state", "") or "").strip()
    if state:
        return state
    if semantic is not None:
        return "Billing reconciliation pending" if semantic.source_family == "account_billing" else "Summary unavailable"
    return "Available"


def _to_metric_cell(section: str, metric: object) -> DecisionMetricCell:
    key = str(getattr(metric, "key", "") or "")
    semantic = get_metric_semantic(section, key)
    numeric = _metric_numeric(metric)
    outlier_reason = semantic.outlier_reason(numeric) if semantic is not None else ""
    metric_available = bool(getattr(metric, "available", True)) and not outlier_reason
    availability_state = _metric_availability_state(metric, semantic, outlier_reason)
    detail = outlier_reason or _delta_label(metric)
    if semantic is not None and semantic.proxy_metric:
        if detail:
            detail = f"{detail} - proxy" if "proxy" not in detail.lower() else detail
        else:
            detail = "proxy risk score"
    if metric_available:
        metric_format = semantic.metric_format if semantic is not None else None
        value_unit = semantic.value_unit if semantic is not None else None
        value = format_metric_value(metric, metric_format=metric_format, value_unit=value_unit)
    else:
        value = availability_state
    trend_points = tuple(getattr(metric, "trend_points", ()) or ())
    return DecisionMetricCell(
        key=key,
        label=semantic.label if semantic is not None else str(getattr(metric, "label", "") or "Metric"),
        value=value,
        detail=detail,
        tone=str(getattr(metric, "tone", "") or "neutral").lower(),
        trend_points=trend_points,
        available=metric_available,
        availability_state=availability_state,
        trend_period=str(getattr(metric, "trend_period", "") or ""),
        trend_point_count=_finite_int(getattr(metric, "trend_point_count", None), len(trend_points)),
        trend_quality=str(getattr(metric, "trend_quality", "") or ("complete" if len(trend_points) >= 7 else "")),
        zero_fill_policy=str(getattr(metric, "zero_fill_policy", "") or ""),
    )


def _metric_cells(section: str, metrics: Sequence[object]) -> tuple[tuple[DecisionMetricCell, ...], tuple[DecisionMetricCell, ...]]:
    all_metrics = tuple(metrics or ())
    available = tuple(metric for metric in all_metrics if bool(getattr(metric, "available", True)))
    by_key = {str(getattr(metric, "key", "") or ""): metric for metric in all_metrics}
    preferred = tuple(by_key[key] for key in _preferred_metrics(section) if key in by_key)
    selected = preferred or available[:4] or all_metrics[:4]
    if len(selected) < 4:
        fill_from = available or all_metrics
        selected = selected + tuple(metric for metric in fill_from if metric not in selected)[: 4 - len(selected)]
    primary = tuple(_to_metric_cell(section, metric) for metric in selected[:4])
    primary_keys = {cell.key for cell in primary}
    extra = tuple(
        _to_metric_cell(section, metric)
        for metric in all_metrics
        if str(getattr(metric, "key", "") or "") not in primary_keys
    )
    return primary, extra


def _state_token(brief: object, source_mode: str) -> str:
    if source_mode == "fixture":
        return "fixture"
    if bool(getattr(brief, "fallback_reason", "")) and not tuple(getattr(brief, "metrics", ()) or ()):
        raw = getattr(brief, "raw_payload", {}) or {}
        return "offline" if isinstance(raw, dict) and raw.get("offline") else "uninitialized"
    if _finite_int(getattr(brief, "missing_source_count", 0), 0):
        return "data-gap"
    if bool(getattr(brief, "stale", False)):
        return "stale"
    text = str(getattr(brief, "state", "") or "").lower()
    if any(word in text for word in ("critical", "fail", "blocked")):
        return "critical"
    if any(word in text for word in ("risk", "warning", "watch")):
        return "at-risk"
    if any(word in text for word in ("healthy", "clear", "ready", "loaded")):
        return "healthy"
    return "watch"


def _state_label(brief: object, source_mode: str) -> str:
    if source_mode == "fixture":
        return "FIXTURE DATA"
    if _finite_int(getattr(brief, "missing_source_count", 0), 0):
        return "DATA GAP"
    if bool(getattr(brief, "stale", False)):
        return "STALE"
    return str(getattr(brief, "state", "") or "Watch").upper()


def _source_mode(brief: object) -> str:
    raw = getattr(brief, "raw_payload", {}) or {}
    if isinstance(raw, dict) and raw.get("fixture_mode") is True:
        return "fixture"
    if isinstance(raw, dict) and raw.get("offline") is True:
        return "offline"
    if bool(getattr(brief, "fallback_reason", "")):
        return "uninitialized"
    if bool(getattr(brief, "stale", False)):
        return "last_known_good"
    return "scheduled_mart"


def _trend_quality_label(metrics: Sequence[object]) -> str:
    qualities = [str(getattr(metric, "trend_quality", "") or "").strip().lower() for metric in tuple(metrics or ())]
    partial = sum(1 for quality in qualities if quality == "partial")
    unavailable = sum(1 for quality in qualities if quality == "unavailable")
    complete = sum(1 for quality in qualities if quality == "complete")
    if partial:
        return f"Trend history: {partial} partial"
    if unavailable and not complete:
        return "Trend history unavailable"
    if complete:
        return f"Trend history: {complete} complete"
    return ""


def _trust_view(brief: object, source_mode: str) -> DecisionTrustView:
    freshness_minutes = getattr(brief, "freshness_minutes", None)
    freshness_numeric = _finite_float(freshness_minutes)
    if freshness_numeric is None:
        age = "Freshness unavailable"
    else:
        age = f"Updated {_finite_int(freshness_numeric)}m ago"
    target = _finite_float(getattr(brief, "target_freshness_minutes", 0))
    coverage = "Sources tracked"
    if getattr(brief, "required_source_count", 0):
        coverage = f"{getattr(brief, 'available_source_count', 0)}/{getattr(brief, 'required_source_count', 0)} required sources"
    quality = str(getattr(brief, "confidence", "") or getattr(brief, "data_availability_state", "") or "Allocated")
    mode_label = {
        "fixture": "FIXTURE DATA",
        "offline": "Offline",
        "uninitialized": "Setup required",
        "last_known_good": "Last successful summary",
        "scheduled_mart": "Scheduled mart",
    }.get(source_mode, "Scheduled mart")
    summary = " | ".join(part for part in (mode_label, age, coverage, quality) if part)
    return DecisionTrustView(
        summary=summary,
        mode_label=mode_label,
        freshness_label=age,
        target_label=f"Target freshness: {_finite_int(target)}m" if target else "Target freshness set",
        coverage_label=coverage,
        quality_label=quality,
        fixture_badge=source_mode == "fixture",
        trend_quality_label=_trend_quality_label(tuple(getattr(brief, "metrics", ()) or ())),
    )


def _source_rows(brief: object) -> tuple[DecisionSourceRow, ...]:
    rows: list[DecisionSourceRow] = []
    for source in tuple(getattr(brief, "sources", ()) or ()):
        available = bool(getattr(source, "available", False))
        stale = bool(getattr(source, "stale", False))
        if available and stale:
            status = "Stale"
        elif available:
            status = "Available"
        else:
            status = "Unavailable"
        age = getattr(source, "age_minutes", None)
        target = getattr(source, "target_freshness_minutes", None)
        age_numeric = _finite_float(age)
        target_numeric = _finite_float(target)
        source_key = str(getattr(source, "source_key", "") or "source")
        rows.append(
            DecisionSourceRow(
                source_key=source_key,
                source_object=_friendly_source_label(source_key),
                status=status,
                required=bool(getattr(source, "required", False)),
                age_label="unknown age" if age_numeric is None else f"{_finite_int(age_numeric)}m old",
                target_label="" if target_numeric is None else f"target {_finite_int(target_numeric)}m",
                confidence=str(getattr(source, "confidence", "") or getattr(brief, "confidence", "") or ""),
                supports_environment=bool(getattr(source, "supports_environment", False)),
                environment_scope_label=_environment_scope_label(
                    str(getattr(source, "environment_scope_mode", "") or ""),
                    bool(getattr(source, "supports_environment", False)),
                ),
                gap_reason=_friendly_gap_reason(str(getattr(source, "gap_reason", "") or ""), required=bool(getattr(source, "required", False))),
                source_label=_friendly_source_label(source_key),
            )
        )
    return tuple(rows)


def _source_technical_summary(brief: object) -> str:
    raw_payload = getattr(brief, "raw_payload", {}) if hasattr(brief, "raw_payload") else {}
    if isinstance(raw_payload, Mapping):
        closest = str(raw_payload.get("closest_packet_summary") or "").strip()
        if closest:
            return f"Latest available: {closest}. Setup Health can refresh summaries."
    requested = (
        f"{getattr(brief, 'requested_company', '') or getattr(brief, 'company', '')} / "
        f"{getattr(brief, 'requested_environment', '') or getattr(brief, 'environment', '')} / "
        f"{getattr(brief, 'requested_window_days', '') or getattr(brief, 'window_label', '')}"
    )
    resolved = (
        f"{getattr(brief, 'resolved_company', '') or getattr(brief, 'company', '')} / "
        f"{getattr(brief, 'resolved_environment', '') or getattr(brief, 'environment', '')} / "
        f"{getattr(brief, 'resolved_window_days', '') or getattr(brief, 'requested_window_days', '')} days"
    )
    return f"Requested {requested}; resolved {resolved}; Setup Health can refresh summaries."


def _fallback_view(brief: object, source_mode: str, *, evidence_action: object | None) -> DecisionFallbackView | None:
    if not bool(getattr(brief, "fallback_reason", "")):
        return None
    scope = f"{getattr(brief, 'company', '')} / {getattr(brief, 'environment', '')} / {getattr(brief, 'window_label', '')}"
    offline = source_mode == "offline"
    title = "Summary pending"
    message = (
        "Connection unavailable. Retry after the source is available or open Setup Health."
        if offline
        else f"Waiting for the current {getattr(brief, 'company', '')} / {getattr(brief, 'environment', '')} summary packet."
    )
    return DecisionFallbackView(
        mode=source_mode,
        title=title,
        message=message,
        recovery_label="Initialize summaries",
        technical_summary=_source_technical_summary(brief),
        can_initialize=not offline,
        can_show_evidence=evidence_action is not None,
    )


def _owner_label(signal: object) -> str:
    for attr in ("owner_name", "owner_id", "owner_route"):
        owner = str(getattr(signal, attr, "") or "").strip()
        if owner:
            if attr == "owner_route" and bool(getattr(signal, "owner_gap", False)):
                return "Owner gap"
            return owner
    if bool(getattr(signal, "owner_gap", False)):
        return "Owner gap"
    return "Owner unavailable"


def _sla_label(signal: object) -> str:
    sla = str(getattr(signal, "sla_state", "") or "").strip()
    if sla:
        return sla
    if getattr(signal, "age_minutes", None) is not None:
        return "No SLA"
    return "SLA unavailable"


def _format_ts_label(prefix: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        return f"{prefix} {parsed.strftime('%Y-%m-%d %H:%M')}"
    except Exception:
        return f"{prefix} {text}"


def _format_compact_ts_label(prefix: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        return f"{prefix} {parsed.strftime('%b')} {parsed.day}"
    except Exception:
        trimmed = text[:10]
        try:
            parsed = datetime.fromisoformat(trimmed)
            return f"{prefix} {parsed.strftime('%b')} {parsed.day}"
        except Exception:
            return f"{prefix} {trimmed or text}"


def _first_seen_label(signal: object) -> str:
    age = getattr(signal, "age_minutes", None)
    age_numeric = _finite_float(age)
    if age_numeric is not None:
        minutes = max(_finite_int(age_numeric), 0)
        if minutes >= 1440:
            return f"Seen {minutes // 1440}d ago"
        if minutes >= 60:
            return f"Seen {minutes // 60}h ago"
        return f"Seen {minutes}m ago"
    return _format_ts_label("First seen", getattr(signal, "first_seen_ts", ""))


def _due_label(signal: object) -> str:
    sla = str(getattr(signal, "sla_state", "") or "").strip()
    due = _format_compact_ts_label("Due", getattr(signal, "due_ts", ""))
    if sla and due:
        normalized = sla.lower()
        if (normalized.startswith("due") or normalized.startswith("overdue")) and "/" not in sla and len(sla) <= 24:
            return sla
        if normalized.startswith("due") or normalized in {"on track", "sla unavailable", "no sla"}:
            return due
        return sla
    return sla or due or _sla_label(signal)


def build_decision_workspace_view_model(
    brief: object,
    *,
    current_workflow: str,
    evidence_action: object | None = None,
) -> DecisionWorkspaceViewModel:
    """Build the data-bound workspace model from a command brief packet."""
    source_mode = _source_mode(brief)
    metrics, additional_metrics = _metric_cells(
        str(getattr(brief, "section", "") or ""),
        tuple(getattr(brief, "metrics", ()) or ()),
    )
    findings = tuple(
        DecisionFinding(
            severity=str(getattr(item, "severity", "") or "Info"),
            signal=str(getattr(item, "signal", "") or "Review summary"),
            entity=str(getattr(item, "entity", "") or ""),
            detail=str(getattr(item, "detail", "") or ""),
            owner=_owner_label(item),
            sla=_due_label(item),
            finding_key=str(getattr(item, "finding_key", "") or ""),
            dedupe_key=str(getattr(item, "dedupe_key", "") or ""),
            entity_type=str(getattr(item, "entity_type", "") or ""),
            entity_id=str(getattr(item, "entity_id", "") or ""),
            entity_name=str(getattr(item, "entity", "") or ""),
            evidence_id=str(getattr(item, "evidence_id", "") or ""),
            owner_id=str(getattr(item, "owner_id", "") or ""),
            owner_name=str(getattr(item, "owner_name", "") or ""),
            first_seen_label=_first_seen_label(item),
            due_label=_due_label(item),
            evidence_source=str(getattr(item, "evidence_source", "") or ""),
            evidence_query=str(getattr(item, "evidence_query", "") or ""),
            owner_gap=bool(getattr(item, "owner_gap", False)),
            route_key=str(getattr(item, "route_key", "") or ""),
        )
        for item in tuple(getattr(brief, "exceptions", ()) or ())[:3]
    )
    actions = tuple(
        DecisionActionView(
            label=str(getattr(action, "label", "") or ""),
            cta=str(getattr(action, "cta", "") or getattr(action, "label", "") or ""),
            action_key=str(getattr(action, "action_key", "") or ""),
            route_key=str(getattr(action, "route_key", "") or ""),
        )
        for action in tuple(getattr(brief, "next_actions", ()) or ())
    )
    trends = tuple(cell for cell in metrics if cell.trend_points)
    trust = _trust_view(brief, source_mode)
    source_rows = _source_rows(brief)
    fallback = _fallback_view(brief, source_mode, evidence_action=evidence_action)
    return DecisionWorkspaceViewModel(
        section=str(getattr(brief, "section", "") or ""),
        workflow=current_workflow or "Overview",
        state=_state_label(brief, source_mode),
        state_token=_state_token(brief, source_mode),
        headline=str(getattr(brief, "headline", "") or ""),
        summary=str(getattr(brief, "summary", "") or ""),
        freshness_label=trust.freshness_label,
        metric_cells=metrics,
        additional_metrics=additional_metrics,
        findings=findings,
        actions=actions,
        trends=trends,
        trust=trust,
        source_rows=source_rows,
        fallback=fallback,
        has_sources=bool(source_rows or getattr(brief, "source_objects", "") or source_mode == "fixture"),
        fixture_badge_label="FIXTURE DATA" if source_mode == "fixture" else "",
        can_refresh=True,
        can_load_evidence=evidence_action is not None,
        fixture_mode=source_mode == "fixture",
        source_mode=source_mode,
    )


__all__ = [
    "DecisionActionView",
    "DecisionFallbackView",
    "DecisionFinding",
    "DecisionMetricCell",
    "DecisionSourceRow",
    "DecisionTrustView",
    "DecisionWorkspaceViewModel",
    "build_decision_workspace_view_model",
    "format_metric_value",
]
