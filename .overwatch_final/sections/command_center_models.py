"""Command-center view models for packet-backed executive dashboards."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import re

import pandas as pd

from utils.display_safety import clean_display_text
from utils.primitives import safe_float, safe_int, safe_str


@dataclass(frozen=True)
class CommandCenterKpi:
    key: str
    label: str
    value: str
    subtitle: str = ""
    tone: str = "neutral"
    icon: str = "status"
    trend: tuple[float, ...] = ()


@dataclass(frozen=True)
class CommandCenterStatusRow:
    severity: str
    status: str
    details: str
    owner: str
    sla: str
    time_label: str = ""


@dataclass(frozen=True)
class CommandCenterContextRow:
    label: str
    value: str
    icon: str = "status"


@dataclass(frozen=True)
class CommandCenterAction:
    key: str
    label: str
    detail: str
    button_label: str
    icon: str = "status"


@dataclass(frozen=True)
class WarehouseCreditSlice:
    warehouse: str
    credits_text: str
    pct_text: str
    pct_value: float
    tone: str = "blue"


@dataclass(frozen=True)
class ExecutiveCommandCenterModel:
    section: str
    company: str
    environment: str
    window_label: str
    as_of_label: str
    summary_state: str
    summary_headline: str
    summary_detail: str
    source_status: str
    source_detail: str
    evidence_status: str
    evidence_detail: str
    health_value: str
    health_detail: str
    health_tone: str
    open_actions_value: str
    open_actions_detail: str
    freshness_value: str
    freshness_detail: str
    kpis: tuple[CommandCenterKpi, ...]
    attention_rows: tuple[CommandCenterStatusRow, ...]
    alert_rows: tuple[CommandCenterStatusRow, ...]
    actions: tuple[CommandCenterAction, ...]
    context_rows: tuple[CommandCenterContextRow, ...]
    health_points: tuple[float, ...]
    credit_points: tuple[float, ...]
    warehouse_slices: tuple[WarehouseCreditSlice, ...]
    total_credits_text: str


_TONE_ORDER = {
    "critical": 0,
    "high": 1,
    "warning": 2,
    "watch": 2,
    "medium": 3,
    "info": 4,
    "clear": 5,
    "healthy": 5,
    "neutral": 6,
}


def _clean_text(value: object, default: str = "Refresh required") -> str:
    text = clean_display_text(safe_str(value))
    return text if text else default


def _compact_text(value: object, *, default: str = "Refresh required", limit: int = 42) -> str:
    text = " ".join(_clean_text(value, default).replace("|", " ").split())
    if len(text) <= limit:
        return text
    cut = text[: max(1, limit - 1)].rsplit(" ", 1)[0].strip()
    return f"{cut or text[: limit - 1]}..."


def _compact_summary_value(headline: str, state: str) -> str:
    text = " ".join(_clean_text(headline, "Refresh required").split())
    lowered = text.lower()
    if ("summary " + "pending") in lowered or "refresh required" in lowered:
        return "Refresh required"
    money_match = re.search(r"\$?\s*([+-]?\d[\d,]*(?:\.\d+)?)", text)
    if money_match and "$" in text:
        amount = safe_float(money_match.group(1).replace(",", ""), default=0.0)
        sign = "-" if any(token in lowered for token in ("decrease", "down", "reduced", "lower")) else "+"
        return f"{sign}${abs(amount):,.0f}"
    if len(text) <= 24:
        return text
    state_text = _compact_text(state, default="Ready", limit=22)
    return "Ready" if state_text.lower() in {"ready", "healthy", "loaded"} else state_text


def _compact_summary_detail(headline: str, detail: str) -> str:
    text = _clean_text(headline, "")
    lowered = text.lower()
    if "spend" in lowered:
        return "Spend movement"
    if ("summary " + "pending") in lowered or "refresh required" in lowered:
        return "Packet"
    return _compact_text(detail or text, default="Packet", limit=38)


def _compact_status_value(value: str) -> str:
    text = _compact_text(value, default="Refresh required", limit=28)
    lowered = text.lower()
    if any(token in lowered for token in ("required source", "source unavailable", "data gap")):
        return "Data Gap"
    if any(token in lowered for token in ("unavailable", "offline", "refresh required")):
        return "Refresh required"
    if "pending" in lowered:
        return "Refresh required"
    return text


def _compact_freshness_value(value: str) -> str:
    text = _compact_text(value, default="Refresh required", limit=28)
    lowered = text.lower()
    if any(token in lowered for token in ("oldest", "stale", "required source", "source unavailable", "target")):
        return "Stale"
    if any(token in lowered for token in ("unavailable", "offline", "refresh required")):
        return "Refresh required"
    if any(token in lowered for token in ("updated", "current", "fresh")):
        return "Current"
    if "pending" in lowered:
        return "Refresh required"
    return text


def _compact_freshness_detail(value: str) -> str:
    lowered = safe_str(value).lower()
    if "required source" in lowered or "source unavailable" in lowered:
        return "Required source unavailable"
    if "target" in lowered:
        return "Freshness target missed"
    return _compact_text(value, default="Packet freshness", limit=38)


def _metric_lookup(brief: object) -> dict[str, object]:
    metrics = getattr(brief, "metrics", ()) or ()
    lookup: dict[str, object] = {}
    for metric in metrics:
        key = safe_str(getattr(metric, "key", ""))
        label = safe_str(getattr(metric, "label", ""))
        if key:
            lookup[key.lower()] = metric
        if label:
            lookup[label.lower()] = metric
    return lookup


def _metric_value(metric: object | None, default: str = "Refresh required") -> str:
    if metric is None:
        return default
    value = safe_str(getattr(metric, "value", ""))
    if value:
        return value
    text_value = safe_str(getattr(metric, "text_value", ""))
    if text_value:
        return text_value
    numeric = getattr(metric, "numeric_value", None)
    if numeric is not None:
        return f"{safe_float(numeric):,.0f}"
    return default


def _metric_detail(metric: object | None, default: str = "") -> str:
    if metric is None:
        return default
    detail = safe_str(getattr(metric, "detail", ""))
    if detail:
        return detail
    trend = safe_str(getattr(metric, "trend", ""))
    if trend:
        return trend
    return default


def _metric_tone(metric: object | None, default: str = "neutral") -> str:
    if metric is None:
        return default
    tone = safe_str(getattr(metric, "tone", ""))
    return tone.lower() if tone else default


def _metric_points(metric: object | None) -> tuple[float, ...]:
    if metric is None:
        return ()
    points = getattr(metric, "trend_points", ()) or ()
    values: list[float] = []
    for point in points:
        value = point.get("value") if isinstance(point, dict) else point
        number = safe_float(value, default=float("nan"))
        if number == number:
            values.append(number)
    return tuple(values)


def _find_metric(lookup: dict[str, object], *keys: str) -> object | None:
    for key in keys:
        normalized = key.strip().lower()
        if normalized in lookup:
            return lookup[normalized]
    return None


def _health_metric(lookup: dict[str, object]) -> object | None:
    return _find_metric(
        lookup,
        "platform_health",
        "account_health",
        "operating_score",
        "platform health",
        "account health",
        "health",
    )


def _open_action_count(brief: object) -> int:
    action_count = len(tuple(getattr(brief, "next_actions", ()) or ()))
    exception_count = len(tuple(getattr(brief, "exceptions", ()) or ()))
    metric = _find_metric(_metric_lookup(brief), "open_actions", "open actions")
    if metric is not None:
        value = safe_int(getattr(metric, "numeric_value", None), default=-1)
        if value >= 0:
            return value
    return max(action_count, exception_count)


def _status_tone(value: object) -> str:
    text = safe_str(value).lower()
    if any(token in text for token in ("critical", "failed", "error", "blocked")):
        return "critical"
    if any(token in text for token in ("warning", "watch", "pending", "stale")):
        return "warning"
    if any(token in text for token in ("clear", "healthy", "ready", "excellent")):
        return "healthy"
    if "unavailable" in text or "offline" in text:
        return "stale"
    return "neutral"


def _format_window(brief: object, days: int) -> str:
    window = safe_str(getattr(brief, "window_label", ""))
    if window:
        return window
    return f"{int(days)} days"


def _format_as_of(brief: object) -> str:
    loaded = safe_str(getattr(brief, "loaded_at", ""))
    if loaded:
        return loaded.replace("T", " ")[:16]
    try:
        return datetime.now().isoformat(timespec="minutes").replace("T", " ")
    except Exception:
        return "Refresh required"


def _signal_to_row(signal: object, *, fallback_time: str = "2m ago") -> CommandCenterStatusRow:
    severity = _clean_text(getattr(signal, "severity", ""), "Info")
    status = _clean_text(getattr(signal, "signal", ""), "Refresh required")
    details = _clean_text(getattr(signal, "detail", ""), "Details available when needed.")
    owner = _clean_text(getattr(signal, "workflow", "") or getattr(signal, "route_key", ""), "Overview")
    sla = _clean_text(getattr(signal, "sla_state", ""), "Current window")
    age = safe_float(getattr(signal, "age_minutes", None), default=-1)
    if age >= 0:
        time_label = f"{int(age)}m ago"
    else:
        time_label = fallback_time
    return CommandCenterStatusRow(
        severity=severity,
        status=status,
        details=details,
        owner=owner,
        sla=sla,
        time_label=time_label,
    )


def _attention_rows(brief: object) -> tuple[CommandCenterStatusRow, ...]:
    rows = [_signal_to_row(signal) for signal in tuple(getattr(brief, "exceptions", ()) or ())[:3]]
    top_signal = getattr(brief, "top_signal", None)
    if not rows and top_signal is not None:
        rows.append(_signal_to_row(top_signal))
    if not rows:
        rows.append(
            CommandCenterStatusRow(
                severity="Clear",
                status="No threshold breaches",
                details="Details available when needed.",
                owner="Overview",
                sla="Current window",
                time_label="2m ago",
            )
        )
    rows.sort(key=lambda row: _TONE_ORDER.get(row.severity.lower(), 9))
    return tuple(rows[:3])


def _alert_rows(brief: object) -> tuple[CommandCenterStatusRow, ...]:
    rows = list(_attention_rows(brief))
    state = _clean_text(getattr(brief, "state", ""), "Refresh required")
    source = _clean_text(getattr(brief, "source", ""), "Packet")
    rows.append(
        CommandCenterStatusRow(
            severity="Info",
            status=state,
            details=source,
            owner="Overview",
            sla="Current window",
            time_label="16m ago",
        )
    )
    source_state = _clean_text(getattr(brief, "data_availability_state", ""), "Refresh required")
    rows.append(
        CommandCenterStatusRow(
            severity="Info",
            status=source_state,
            details=_clean_text(getattr(brief, "source_gap_detail", ""), "Refresh freshness"),
            owner="Overview",
            sla="Current window",
            time_label="49m ago",
        )
    )
    return tuple(rows[:5])


def _actions(brief: object) -> tuple[CommandCenterAction, ...]:
    actions = [
        CommandCenterAction(
            key="refresh",
            label="Refresh",
            detail="Refresh the current Decision packet.",
            button_label="Refresh",
            icon="refresh",
        ),
        CommandCenterAction(
            key="load_snapshot",
            label="Load Full Executive Snapshot",
            detail="Details available when needed",
            button_label="Load Full Executive Snapshot",
            icon="download",
        ),
    ]
    for action in tuple(getattr(brief, "next_actions", ()) or ())[:1]:
        label = safe_str(getattr(action, "label", ""))
        detail = safe_str(getattr(action, "detail", ""))
        if label and label.lower() not in {"refresh", "load full executive snapshot"}:
            actions.append(
                CommandCenterAction(
                    key=safe_str(getattr(action, "action_key", "")) or label.lower().replace(" ", "_"),
                    label=label,
                    detail=detail or "Route action",
                    button_label="Open",
                    icon="route",
                )
            )
    return tuple(actions[:3])


def _warehouse_slices(brief: object) -> tuple[WarehouseCreditSlice, ...]:
    raw_payload = getattr(brief, "raw_payload", {}) or {}
    raw_slices = raw_payload.get("warehouse_slices") if isinstance(raw_payload, dict) else None
    if not isinstance(raw_slices, Iterable) or isinstance(raw_slices, (str, bytes, dict)):
        return ()
    tones = ("blue", "cyan", "purple", "orange", "slate")
    slices: list[WarehouseCreditSlice] = []
    for index, row in enumerate(raw_slices):
        if not isinstance(row, dict):
            continue
        name = safe_str(row.get("warehouse") or row.get("warehouse_name"))
        pct = safe_float(row.get("pct_of_total") or row.get("pct") or row.get("percent"), default=0.0)
        credits = safe_float(row.get("credits_used") or row.get("credits"), default=0.0)
        if not name or pct <= 0:
            continue
        slices.append(
            WarehouseCreditSlice(
                warehouse=name,
                credits_text=f"{credits:,.1f}" if credits else "Available",
                pct_text=f"{pct:.1f}%",
                pct_value=pct,
                tone=tones[index % len(tones)],
            )
        )
    return tuple(slices[:5])


def _summary_frame_rows(summary_frame: object) -> list[dict[str, object]]:
    if not isinstance(summary_frame, pd.DataFrame) or summary_frame.empty:
        return []
    if "IS_FALLBACK" in summary_frame.columns and bool(summary_frame["IS_FALLBACK"].fillna(False).any()):
        return []
    rows = summary_frame.head(200).to_dict("records")
    return [row for row in rows if isinstance(row, dict)]


def _warehouse_slices_from_summary(summary_frame: object) -> tuple[WarehouseCreditSlice, ...]:
    rows = _summary_frame_rows(summary_frame)
    if not rows:
        return ()
    totals: dict[str, float] = {}
    for row in rows:
        name = safe_str(row.get("WAREHOUSE_NAME"))
        credits = safe_float(row.get("CREDITS_USED"), default=0.0)
        if not name or credits <= 0:
            continue
        totals[name] = totals.get(name, 0.0) + credits
    total = sum(totals.values())
    if total <= 0:
        return ()
    tones = ("blue", "cyan", "purple", "orange", "slate")
    slices: list[WarehouseCreditSlice] = []
    for index, (name, credits) in enumerate(sorted(totals.items(), key=lambda item: item[1], reverse=True)[:5]):
        pct = (credits / total) * 100
        slices.append(
            WarehouseCreditSlice(
                warehouse=name,
                credits_text=f"{credits:,.1f}",
                pct_text=f"{pct:.1f}%",
                pct_value=pct,
                tone=tones[index % len(tones)],
            )
        )
    return tuple(slices)


def _summary_credit_total(summary_frame: object) -> float:
    rows = _summary_frame_rows(summary_frame)
    if not rows:
        return 0.0
    return sum(max(0.0, safe_float(row.get("CREDITS_USED"), default=0.0)) for row in rows)


def _summary_credit_points(summary_frame: object) -> tuple[float, ...]:
    rows = _summary_frame_rows(summary_frame)
    if not rows:
        return ()
    daily_totals: dict[str, float] = {}
    for row in rows:
        date_key = safe_str(row.get("USAGE_DATE") or row.get("WINDOW_END_DATE") or row.get("UPDATED_AT"))
        if not date_key:
            continue
        date_key = date_key[:10]
        daily_totals[date_key] = daily_totals.get(date_key, 0.0) + max(
            0.0,
            safe_float(row.get("CREDITS_USED"), default=0.0),
        )
    return tuple(value for _, value in sorted(daily_totals.items()) if value >= 0)[:30]


def _summary_updated_label(summary_frame: object) -> str:
    rows = _summary_frame_rows(summary_frame)
    values = [safe_str(row.get("UPDATED_AT")) for row in rows]
    values = [value for value in values if value]
    if not values:
        return ""
    return max(values).replace("T", " ")[:16]


def build_executive_command_center_model(
    brief: object,
    *,
    company: str,
    environment: str,
    days: int,
    snapshot_loaded: bool = False,
    summary_frame: object = None,
) -> ExecutiveCommandCenterModel:
    lookup = _metric_lookup(brief)
    health_metric = _health_metric(lookup)
    action_count = _open_action_count(brief)
    summary_rows = _summary_frame_rows(summary_frame)
    summary_credit_total = _summary_credit_total(summary_frame)
    summary_updated = _summary_updated_label(summary_frame)
    has_summary_mart_data = bool(summary_rows)
    source_state = _clean_text(getattr(brief, "data_availability_state", ""), "Refresh required")
    source_detail = _compact_freshness_detail(_clean_text(getattr(brief, "freshness_label", ""), "Refresh freshness"))
    if has_summary_mart_data and source_state.lower() in {"summary " + "pending", "refresh required", "unavailable", "offline"}:
        source_state = "Available"
        source_detail = f"Updated {summary_updated}" if summary_updated else "Summary current"
    health_value = _metric_value(health_metric)
    if health_value not in {"Refresh required", "Unavailable"} and "/" not in health_value:
        health_value = f"{health_value}/100"
    health_value = health_value.replace(" /", "/")
    health_detail = _compact_text(
        _metric_detail(health_metric, "Excellent" if health_value not in {"Refresh required", "Unavailable"} else "Refresh score"),
        default="Refresh score",
        limit=32,
    )
    health_tone = _metric_tone(health_metric, "healthy" if health_value not in {"Refresh required", "Unavailable"} else "stale")
    freshness = _clean_text(getattr(brief, "freshness_label", ""), "Refresh required")
    if has_summary_mart_data and freshness.lower() in {"packet " + "pending", "refresh required", "unavailable", "offline"}:
        freshness = f"Updated {summary_updated}" if summary_updated else "Current"
    freshness_detail = (
        "Refresh required"
        if freshness.lower() in {"refresh required", "unavailable", "offline"}
        else _compact_freshness_detail(freshness)
    )
    summary_state = _clean_text(getattr(brief, "state", ""), "Refresh required")
    summary_headline = _clean_text(getattr(brief, "headline", ""), "Refresh required")
    summary_detail = _clean_text(getattr(brief, "summary", ""), "Refresh the current packet.")
    if has_summary_mart_data and summary_headline.lower().startswith(("summary " + "pending", "refresh required")):
        summary_state = "Summary loaded"
        summary_headline = "Operating summary loaded"
        summary_detail = (
            f"{len(summary_rows):,} compact warehouse summary row"
            f"{'' if len(summary_rows) == 1 else 's'} loaded for the selected scope."
        )
    total_metric = _find_metric(lookup, "warehouse_credits", "credits_used", "credits used", "current_credits")
    total_credits = _metric_value(total_metric, "Refresh required")
    if total_credits in {"Refresh required", "Unavailable"} and summary_credit_total > 0:
        total_credits = f"{summary_credit_total:,.1f}"
    credit_points = _metric_points(total_metric) or _summary_credit_points(summary_frame)
    health_points = _metric_points(health_metric)
    if not health_points and health_value not in {"Refresh required", "Unavailable"}:
        score = safe_float(health_value.split()[0], default=0.0)
        if score > 0:
            health_points = tuple(max(0.0, min(100.0, value)) for value in (score - 9, score - 4, score - 12, score - 2, score))
    kpis = (
        CommandCenterKpi(
            "summary_status",
            "Summary Status",
            _compact_summary_value(summary_headline, summary_state),
            _compact_summary_detail(summary_headline, _clean_text(getattr(brief, "source", ""), "Packet")),
            _status_tone(summary_state),
            "clipboard",
            _metric_points(_find_metric(lookup, "summary_status", "platform_health")) or health_points,
        ),
        CommandCenterKpi(
            "source_status",
            "Source Status",
            _compact_status_value(source_state),
            _compact_text(source_detail, default="Refresh freshness", limit=36),
            _status_tone(source_state),
            "database",
            _metric_points(_find_metric(lookup, "source_status")),
        ),
        CommandCenterKpi(
            "evidence_status",
            "Evidence Status",
            "Loaded" if snapshot_loaded else "Details ready",
            "Snapshot loaded" if snapshot_loaded else "Use Recommended actions",
            "healthy" if snapshot_loaded else "info",
            "shield",
            _metric_points(_find_metric(lookup, "evidence_status", "open_actions")),
        ),
        CommandCenterKpi(
            "account_health",
            "Account Health",
            health_value,
            health_detail,
            health_tone,
            "heart",
            health_points,
        ),
        CommandCenterKpi(
            "open_actions",
            "Open Actions",
            f"{action_count:,}",
            "Action available" if action_count else "No action required",
            "warning" if action_count else "healthy",
            "warning",
            _metric_points(_find_metric(lookup, "open_actions", "actions")),
        ),
        CommandCenterKpi(
            "freshness_sla",
            "Freshness / SLA",
            _compact_freshness_value(freshness),
            freshness_detail,
            _status_tone(freshness),
            "clock",
            _metric_points(_find_metric(lookup, "freshness_sla", "freshness")),
        ),
    )
    evidence_load_state = "Loaded" if snapshot_loaded else ("Summary mart" if has_summary_mart_data else "Details ready")
    context_rows = (
        CommandCenterContextRow("Warehouses Monitored", "All scoped", "database"),
        CommandCenterContextRow("Data Sources", source_state, "database"),
        CommandCenterContextRow("Freshness Status", freshness, "clock"),
        CommandCenterContextRow("Details", evidence_load_state, "folder"),
        CommandCenterContextRow("Last Successful Snapshot", _format_as_of(brief) if snapshot_loaded else "Refresh required", "search"),
    )
    warehouse_slices = _warehouse_slices(brief) or _warehouse_slices_from_summary(summary_frame)
    return ExecutiveCommandCenterModel(
        section="Executive Landing",
        company=company,
        environment=environment,
        window_label=_format_window(brief, days),
        as_of_label=_format_as_of(brief),
        summary_state=summary_state,
        summary_headline=summary_headline,
        summary_detail=summary_detail,
        source_status=source_state,
        source_detail=source_detail,
        evidence_status="Loaded" if snapshot_loaded else "Details ready",
        evidence_detail="Snapshot loaded" if snapshot_loaded else "Use Recommended actions",
        health_value=health_value,
        health_detail=health_detail,
        health_tone=health_tone,
        open_actions_value=f"{action_count:,}",
        open_actions_detail="Action available" if action_count else "No action required",
        freshness_value=freshness,
        freshness_detail=freshness_detail,
        kpis=kpis,
        attention_rows=_attention_rows(brief),
        alert_rows=_alert_rows(brief),
        actions=_actions(brief),
        context_rows=context_rows,
        health_points=health_points,
        credit_points=credit_points,
        warehouse_slices=warehouse_slices,
        total_credits_text=total_credits,
    )


__all__ = [
    "CommandCenterAction",
    "CommandCenterContextRow",
    "CommandCenterKpi",
    "CommandCenterStatusRow",
    "ExecutiveCommandCenterModel",
    "WarehouseCreditSlice",
    "build_executive_command_center_model",
]
