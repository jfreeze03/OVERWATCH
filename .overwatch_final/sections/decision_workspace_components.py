"""Streamlit-native Decision Workspace component primitives.

The attached React UI kit is used as visual direction only. These helpers emit
safe HTML fragments that the Streamlit renderers can mount with ``st.html``.
They do not contain demo data or runtime queries.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from html import escape
import math

from utils.display_safety import contains_raw_source_token, safe_source_footer_items, scrub_daily_text


def _value(item: object, *names: str, default: object = "") -> object:
    if isinstance(item, Mapping):
        for name in names:
            if name in item and item[name] not in (None, ""):
                return item[name]
        return default
    for name in names:
        if hasattr(item, name):
            value = getattr(item, name)
            if value not in (None, ""):
                return value
    return default


def _safe(value: object) -> str:
    return escape(scrub_daily_text(value), quote=True)


def _tone(value: object) -> str:
    return escape(str(value or "neutral").strip().lower() or "neutral", quote=True)


def _as_number(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def render_section_header(
    section: object,
    workflow: object = "Overview",
    *,
    kicker: object = "Decision Workspace",
    detail: object = "",
) -> str:
    """Return the compact section header used before a CommandBrief."""

    detail_html = f'<p>{_safe(detail)}</p>' if str(detail or "").strip() else ""
    return (
        '<header class="ow-kit-section-header">'
        f'<span>{_safe(kicker)}</span>'
        f'<h1>{_safe(section)}</h1>'
        f'<strong>{_safe(workflow)}</strong>'
        f"{detail_html}"
        "</header>"
    )


def render_metric_card(metric: object) -> str:
    """Return a single compact metric card."""

    label = _value(metric, "label", "title", default="Metric")
    value = _value(metric, "value", "text_value", "availability_state", default="Unavailable")
    detail = _value(metric, "detail", "subtitle", "description", default="")
    tone = _tone(_value(metric, "tone", "severity", default="neutral"))
    return (
        f'<article class="ow-kit-metric-card ow-decision-metric-cell" data-tone="{tone}">'
        f'<div><span>{_safe(label)}</span><strong>{_safe(value)}</strong>'
        f'<small>{_safe(detail)}</small></div>'
        '<div class="ow-kit-metric-glyph" aria-hidden="true"></div>'
        "</article>"
    )


def render_metric_row(metrics: Sequence[object], *, min_count: int = 3, max_count: int = 5) -> str:
    """Return the 3-5 metric row contract for first-paint CommandBriefs."""

    selected = tuple(metrics or ())[:max_count]
    cells = [render_metric_card(metric) for metric in selected]
    return (
        f'<section class="ow-kit-metric-row ow-decision-metric-ribbon" '
        f'data-metric-count="{len(cells)}" data-min-count="{min_count}" data-max-count="{max_count}" '
        'aria-label="Command brief metrics">'
        + "".join(cells)
        + "</section>"
    )


def render_signal_panel(findings: Sequence[object], *, title: object = "What needs attention") -> str:
    """Return the compact signal/priority panel."""

    rows: list[str] = []
    for item in tuple(findings or ())[:3]:
        severity = _value(item, "severity", default="Info")
        signal = _value(item, "signal", "title", default="Review summary")
        entity = _value(item, "entity_name", "entity", "entity_id", default="Entity unavailable")
        owner = _value(item, "owner_name", "owner", default="Owner unavailable")
        sla = _value(item, "sla", "due_label", "sla_state", default="SLA unavailable")
        first_seen = _value(item, "first_seen_label", default="")
        due = _value(item, "due_label", default="")
        evidence_id = _value(item, "evidence_id", default="")
        detail = _value(item, "detail", "description", default="")
        supplemental = "".join(
            f'<small>{_safe(value)}</small>'
            for value in (
                first_seen,
                due if due and due != sla else "",
                f"Evidence {evidence_id}" if evidence_id else "",
            )
            if value
        )
        rows.append(
            '<div class="ow-kit-signal-row ow-decision-attention-row">'
            f'<span class="ow-attention-icon" data-severity="{_tone(severity)}"></span>'
            f'<strong>{_safe(severity)}</strong>'
            f'<div class="ow-attention-copy"><b>{_safe(signal)}</b><small>{_safe(detail)}</small>{supplemental}</div>'
            f'<div class="ow-attention-meta"><span>Entity</span><b>{_safe(entity)}</b></div>'
            f'<div class="ow-attention-meta"><span>Owner</span><b>{_safe(owner)}</b></div>'
            f'<div class="ow-attention-meta"><span>SLA</span><b>{_safe(sla)}</b></div>'
            "</div>"
        )
    if not rows:
        rows.append(
            '<div class="ow-kit-signal-row ow-decision-attention-row ow-decision-clear-row">'
            '<span class="ow-attention-icon" data-severity="clear"></span>'
            '<strong>CLEAR</strong>'
            '<div class="ow-attention-copy"><b>No threshold breach in the command brief</b>'
            '<small>Evidence loads on request.</small></div>'
            '<div class="ow-attention-meta"><span>Owner</span><b>Owner unavailable</b></div>'
            '<div class="ow-attention-meta"><span>SLA</span><b>SLA unavailable</b></div>'
            "</div>"
        )
    return '<section class="ow-kit-signal-panel ow-decision-attention-panel">' f"<h4>{_safe(title)}</h4>" + "".join(rows) + "</section>"


def render_action_row(actions: Sequence[object], *, title: object = "What to do next") -> str:
    """Return non-clicking action descriptions; Streamlit buttons remain separate."""

    rows = []
    for action in tuple(actions or ())[:3]:
        label = _value(action, "cta", "label", default="Open")
        detail = _value(action, "detail", "description", default="Evidence loads on request")
        rows.append(
            '<div class="ow-kit-action-row">'
            f'<strong>{_safe(label)}</strong><small>{_safe(detail)}</small>'
            "</div>"
        )
    if not rows:
        rows.append('<div class="ow-kit-action-row"><strong>Continue monitoring</strong><small>Evidence loads on request.</small></div>')
    return '<section class="ow-kit-action-panel"><h4>' + _safe(title) + "</h4>" + "".join(rows) + "</section>"


def render_data_trust_footer(
    *,
    mode: object = "Packet",
    freshness: object = "Freshness unavailable",
    target: object = "Target freshness set",
    coverage: object = "Sources tracked",
    quality: object = "Data quality unavailable",
    source_labels: Iterable[object] = (),
) -> str:
    """Return a source-safe Data Trust footer."""

    safe_sources = safe_source_footer_items(source_labels)
    return (
        '<footer class="ow-kit-data-trust ow-decision-trust-footer">'
        "<strong>Data Trust</strong>"
        f'<span>{_safe(mode)}</span>'
        f'<span>{_safe(freshness)}</span>'
        f'<span>{_safe(target)}</span>'
        f'<span>{_safe(coverage)}</span>'
        f'<span>Data quality <b>{_safe(quality)}</b></span>'
        f'<span>{_safe(" / ".join(safe_sources))}</span>'
        "</footer>"
    )


def render_workflow_context(title: object, detail: object = "", *, kicker: object = "Workflow") -> str:
    detail_html = f'<div class="ow-workflow-context-detail">{_safe(detail)}</div>' if str(detail or "").strip() else ""
    return (
        '<div class="ow-workflow-context">'
        f'<div class="ow-workflow-context-kicker">{_safe(kicker)}</div>'
        f'<div class="ow-workflow-context-title">{_safe(title)}</div>'
        f"{detail_html}</div>"
    )


def render_tabs(tabs: Sequence[object], *, active: object = "") -> str:
    active_text = str(active or "")
    items = []
    for tab in tuple(tabs or ()):
        text = str(_value(tab, "label", "name", default=tab)).strip()
        state = "active" if text == active_text else "idle"
        items.append(f'<span data-state="{state}">{_safe(text)}</span>')
    return '<nav class="ow-kit-tabs" aria-label="Workflow tabs">' + "".join(items) + "</nav>"


def render_ranked_bar_panel(
    title: object,
    rows: Sequence[Mapping[str, object]],
    *,
    label_key: str = "label",
    value_key: str = "value",
    subtitle: object = "",
) -> str:
    """Return a compact ranked-bar HTML panel for deterministic snapshots."""

    usable = []
    for row in tuple(rows or ())[:10]:
        numeric = _as_number(row.get(value_key))
        if numeric is None:
            continue
        usable.append((row, numeric))
    max_value = max((value for _, value in usable), default=0.0) or 1.0
    bars = []
    for row, numeric in usable:
        width = max(4.0, min(100.0, (numeric / max_value) * 100.0))
        bars.append(
            '<div class="ow-kit-ranked-row">'
            f'<span>{_safe(row.get(label_key))}</span>'
            f'<b>{_safe(row.get(value_key))}</b>'
            f'<i style="width:{width:.2f}%"></i>'
            "</div>"
        )
    if not bars:
        bars.append('<div class="ow-kit-ranked-empty">No ranked rows loaded for this scope.</div>')
    subtitle_html = f"<p>{_safe(subtitle)}</p>" if str(subtitle or "").strip() else ""
    return '<section class="ow-kit-ranked-panel">' f"<h4>{_safe(title)}</h4>{subtitle_html}" + "".join(bars) + "</section>"


def render_area_trend_panel(
    title: object,
    points: Sequence[object],
    *,
    subtitle: object = "",
    freshness_note: object = "",
) -> str:
    values = [_as_number(_value(point, "value", default=point)) for point in tuple(points or ())]
    finite = [value for value in values if value is not None]
    if len(finite) >= 2:
        low = min(finite)
        high = max(finite)
        span = high - low or 1.0
        coords = []
        for index, value in enumerate(finite[-24:]):
            x = round(index * (120 / max(len(finite[-24:]) - 1, 1)), 2)
            y = round(44 - ((value - low) / span * 38), 2)
            coords.append(f"{x},{y}")
        chart = (
            '<svg class="ow-kit-area-trend" viewBox="0 0 120 48" role="img" aria-label="Area trend">'
            f'<polyline points="{" ".join(coords)}" fill="none" stroke="currentColor" stroke-width="2"></polyline>'
            "</svg>"
        )
    else:
        chart = '<div class="ow-kit-trend-empty">Trend data not loaded.</div>'
    return (
        '<section class="ow-kit-area-panel">'
        f"<h4>{_safe(title)}</h4>"
        f"<p>{_safe(subtitle)}</p>"
        f"{chart}"
        f'<small>{_safe(freshness_note)}</small>'
        "</section>"
    )


def render_evidence_empty_state(
    *,
    title: object = "Evidence loads on request",
    detail: object = "Use the section evidence action to load compact rows for this scope.",
    cta: object = "Load evidence",
) -> str:
    return (
        '<section class="ow-kit-evidence-empty ow-decision-evidence-panel">'
        '<div class="ow-decision-evidence-header">'
        f'<div><strong>{_safe(title)}</strong><p>{_safe(detail)}</p></div>'
        f'<span>{_safe(cta)}</span>'
        "</div></section>"
    )


def render_compact_pending_state(
    *,
    title: object = "Summary pending",
    detail: object = "Waiting for the current summary packet.",
    latest_available: object = "",
) -> str:
    latest = f'<small>{_safe(latest_available)}</small>' if str(latest_available or "").strip() else ""
    return (
        '<section class="ow-kit-pending-state ow-decision-recovery ow-decision-operating-loop">'
        '<div class="ow-decision-loop-header" data-state="uninitialized">'
        f'<strong>{_safe(title)}</strong><span>Evidence loads on request</span></div>'
        f'<p class="ow-decision-loop-summary">{_safe(detail)}</p>{latest}</section>'
    )


def render_command_brief(model: object) -> str:
    """Return a full CommandBrief shell from a view model-like object."""

    source_labels = [_value(row, "source_object", "source_key") for row in tuple(_value(model, "source_rows", default=()) or ())]
    header = render_section_header(
        _value(model, "section", default="Decision Workspace"),
        _value(model, "workflow", default="Overview"),
        kicker=_value(model, "state", default="Watch"),
        detail=_value(model, "summary", default=""),
    )
    metrics = render_metric_row(tuple(_value(model, "metric_cells", default=()) or ()))
    signals = render_signal_panel(tuple(_value(model, "findings", default=()) or ()))
    actions = render_action_row(tuple(_value(model, "actions", default=()) or ()))
    trust = _value(model, "trust", default={})
    footer = render_data_trust_footer(
        mode=_value(trust, "mode_label", default="Packet"),
        freshness=_value(trust, "freshness_label", default="Freshness unavailable"),
        target=_value(trust, "target_label", default="Target freshness set"),
        coverage=_value(trust, "coverage_label", default="Sources tracked"),
        quality=_value(trust, "quality_label", default="Data quality unavailable"),
        source_labels=source_labels,
    )
    html = (
        '<section class="ow-kit-command-brief ow-decision-workspace" role="region" '
        'aria-label="CommandBrief">'
        + header
        + metrics
        + '<div class="ow-decision-main-grid">'
        + signals
        + actions
        + "</div>"
        + footer
        + "</section>"
    )
    if contains_raw_source_token(html):
        return scrub_daily_text(html)
    return html


__all__ = [
    "render_action_row",
    "render_area_trend_panel",
    "render_command_brief",
    "render_compact_pending_state",
    "render_data_trust_footer",
    "render_evidence_empty_state",
    "render_metric_card",
    "render_metric_row",
    "render_ranked_bar_panel",
    "render_section_header",
    "render_signal_panel",
    "render_tabs",
    "render_workflow_context",
]
