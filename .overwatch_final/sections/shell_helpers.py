"""Small shared helpers for fast first-paint section shells."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from html import escape as _escape_markup
from inspect import Parameter, signature
import re

import streamlit as st

from runtime_state import mark_widget_key_rendered, set_state
from utils.display_safety import clean_display_text

FRESHNESS_TARGET_MINUTES = {
    "live": 5,
    "pressure": 30,
    "cost": 60,
    "security": 60,
    "change": 60,
    "service": 120,
    "storage": 360,
    "historical": 360,
}


def _badge(label: object) -> None:
    """Render a status badge with a native fallback for older Streamlit builds."""
    text = clean_display_text(label or "Ready")
    badge = getattr(st, "badge", None)
    if callable(badge):
        badge(text)
    else:
        st.caption(text)


def _supported_widget_kwargs(widget: Callable[..., object], kwargs: Mapping[str, object]) -> dict[str, object]:
    """Drop widget kwargs that are unavailable in older Streamlit-in-Snowflake runtimes."""
    try:
        params = signature(widget).parameters
    except (TypeError, ValueError):
        return dict(kwargs)
    if any(param.kind == Parameter.VAR_KEYWORD for param in params.values()):
        return dict(kwargs)
    return {key: value for key, value in kwargs.items() if key in params}


def _display_html(value: object) -> str:
    """Escape generated display text for small HTML fragments."""
    return _escape_markup(clean_display_text(value))


def render_escaped_bold_text(value: object, *, margin: str = ".15rem 0") -> None:
    """Render generated text in bold without letting Markdown parse underscores."""
    text = _display_html(value)
    if not text:
        return
    st.html(f'<div style="line-height:1.45; margin:{_escape_markup(margin)};"><strong>{text}</strong></div>')


def render_escaped_labeled_text(label: object, detail: object, *, margin: str = ".15rem 0") -> None:
    """Render a bold label and escaped generated detail text."""
    label_text = _display_html(label)
    detail_text = _display_html(detail)
    if not label_text and not detail_text:
        return
    separator = ": " if label_text and detail_text else ""
    st.html(
        f'<div style="line-height:1.45; margin:{_escape_markup(margin)};">'
        f'<strong>{label_text}</strong>{separator}{detail_text}</div>'
    )


def evidence_loaded(state, keys: tuple[str, ...]) -> bool:
    return any(state.get(key) is not None for key in keys)


def evidence_label(state, keys: tuple[str, ...]) -> str:
    return "Loaded" if evidence_loaded(state, keys) else "On demand"


def action_state_label(state, keys: tuple[str, ...]) -> str:
    return "Loaded" if evidence_loaded(state, keys) else "Ready"


def full_workspace_requested(state, workspace_key: str, brief_key: str) -> bool:
    """Default section navigation to the real workspace unless brief mode is explicit."""
    if state.get(brief_key):
        return False
    if state.get(workspace_key):
        return True
    state[workspace_key] = True
    state[brief_key] = False
    return True


def consume_section_autoload_request(section: str) -> bool:
    """Return True once when navigation asks a section to hydrate its fast landing data."""
    requested = str(st.session_state.get("_overwatch_pending_autoload_section") or "").strip()
    if requested != str(section or "").strip():
        return False
    st.session_state.pop("_overwatch_pending_autoload_section", None)
    st.session_state.pop("_overwatch_pending_autoload_started_at", None)
    return True


def loaded_at_now() -> str:
    """Timestamp section evidence when a user explicitly loads or refreshes it."""
    return datetime.now().isoformat(timespec="seconds")


def with_loaded_at(meta: Mapping | None, *, source: str = "") -> dict:
    """Return a mutable metadata copy with a loaded-at timestamp."""
    enriched = dict(meta or {})
    enriched["loaded_at"] = loaded_at_now()
    if source:
        enriched["source"] = source
    return enriched


def _parse_loaded_at(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _format_age(minutes: float) -> str:
    if minutes < 1:
        return "just now"
    if minutes < 90:
        return f"{int(round(minutes))} min old"
    hours = minutes / 60.0
    if hours < 48:
        return f"{hours:.1f} hr old"
    return f"{hours / 24.0:.1f} days old"


def freshness_state(meta: Mapping | None, *, target_minutes: int = 60) -> tuple[str, str]:
    """Summarize telemetry status without starting a Snowflake query."""
    if not meta:
        return "", ""
    loaded_at = _parse_loaded_at((meta or {}).get("loaded_at"))
    source = str((meta or {}).get("source") or "Loaded telemetry").strip()
    if loaded_at is None:
        return "Loaded", f"{clean_display_text(source)}; age unavailable. Refresh before acting."
    age_minutes = max(0.0, (datetime.now() - loaded_at).total_seconds() / 60.0)
    if age_minutes <= max(1, int(target_minutes or 60)):
        return "Current", f"{clean_display_text(source)}; loaded {_format_age(age_minutes)}."
    return "Stale", f"{clean_display_text(source)}; loaded {_format_age(age_minutes)}. Refresh before acting."


def render_data_freshness(
    meta: Mapping | None,
    *,
    source: str,
    target_minutes: int = 60,
    delayed_note: str = "Account history can lag; use live tools for in-flight incidents.",
) -> None:
    """Render a compact telemetry status note for data-first sections."""
    has_meta = bool(meta)
    if not has_meta:
        return
    merged = dict(meta or {})
    if source and has_meta and "source" not in merged:
        merged["source"] = source
    state, detail = freshness_state(merged if has_meta else None, target_minutes=target_minutes)
    with st.container(border=True):
        detail_col, state_col = st.columns([4, 1])
        with detail_col:
            st.caption(f"Data status - {clean_display_text(source or merged.get('source') or 'Loaded data')}")
            render_escaped_bold_text(detail)
        with state_col:
            _badge(state)
    if delayed_note:
        st.caption(clean_display_text(delayed_note))


def render_refresh_contract(
    meta: Mapping | None,
    *,
    source: str,
    target_minutes: int = 60,
    refresh_method: str = "Scheduled Snowflake refresh",
    live_fallback: str = "No shell fallback",
) -> None:
    """Render the board refresh contract without starting a Snowflake query."""
    has_meta = bool(meta)
    if not has_meta:
        return
    merged = dict(meta or {})
    if source and has_meta and "source" not in merged:
        merged["source"] = source
    state, detail = freshness_state(merged if has_meta else None, target_minutes=target_minutes)
    render_shell_snapshot((
        ("Data", clean_display_text(source or merged.get("source") or "Summary facts")),
        ("Status", state),
    ))
    if detail:
        st.caption(clean_display_text(detail))


def render_setup_health_board(
    title: str,
    objects: Sequence[tuple[str, object]],
    *,
    cadence: str = "Scheduled",
    fallback: str = "Explicit only",
    owner: str = "DBA",
) -> None:
    """Render setup signals that support a data-first monitoring summary."""
    return


def evidence_caption(state, keys: tuple[str, ...], unloaded_caption: str) -> str:
    if evidence_loaded(state, keys):
        return "Loaded telemetry is available; open the workspace to continue from the saved status."
    return unloaded_caption


def compact_environment_label(environment: str | None) -> str:
    labels = {
        "ALL": "All env",
        "PROD": "Prod",
        "DEV_ALL": "All dev",
    }
    env_key = str(environment or "ALL")
    return labels.get(env_key, env_key)


def scope_label(company: str | None, environment: str | None) -> str:
    company_key = str(company or "ALL")
    return f"{company_key} / {compact_environment_label(environment)}"


@dataclass(frozen=True)
class FirstPaintSummarySpec:
    """Declarative first-paint shell contract for query-on-demand section entry."""

    section: str
    state: object
    headline: object
    view: object = ""
    detail: object = ""
    metrics: tuple[tuple[str, object], ...] = ()
    snapshot: tuple[tuple[str, object], ...] = ()
    expected_lanes: Sequence[object] | object = ()
    load_cta: object = ""
    no_query_note: object = ""


def build_first_paint_summary_spec(
    section: str,
    *,
    state: object,
    headline: object,
    detail: object = "",
    view: object | None = None,
    metrics: tuple[tuple[str, object], ...] = (),
    snapshot: tuple[tuple[str, object], ...] = (),
    expected_lanes: Sequence[object] | object | None = None,
    load_cta: object | None = None,
    no_query_note: object | None = None,
) -> FirstPaintSummarySpec:
    """Build a first-paint shell spec from the central section contract."""
    from sections.first_paint_contracts import get_first_paint_contract

    contract = get_first_paint_contract(section)
    return FirstPaintSummarySpec(
        section=contract.section,
        state=state,
        headline=headline,
        view=contract.default_view if view is None else view,
        detail=detail,
        metrics=tuple(metrics or ()),
        snapshot=tuple(snapshot or ()),
        expected_lanes=contract.expected_lanes if expected_lanes is None else expected_lanes,
        load_cta=contract.explicit_load_cta if load_cta is None else load_cta,
        no_query_note=contract.no_query_note if no_query_note is None else no_query_note,
    )


def _format_expected_lanes(lanes: Sequence[object] | object) -> str:
    if isinstance(lanes, str):
        return clean_display_text(lanes)
    try:
        values = [clean_display_text(item) for item in lanes or ()]
    except TypeError:
        values = [clean_display_text(lanes)]
    return ", ".join(value for value in values if value)


def render_shell_snapshot(metrics: tuple[tuple[str, object], ...]) -> None:
    """Render lightweight shell snapshot cards without the bulk of metric widgets."""
    visible_metrics = []
    empty_values = {"", "on demand", "not loaded", "board frame only", "no snowflake scan", "explicit only"}
    for label, value in metrics or ():
        clean_value = clean_display_text(value)
        if clean_value.strip().lower() in empty_values:
            continue
        visible_metrics.append((clean_display_text(label), clean_value))
    if not visible_metrics:
        return
    cards = "".join(
        f'<div class="ow-shell-snapshot-card"><span class="ow-shell-snapshot-label">{_escape_markup(label)}</span>'
        f'<strong class="ow-shell-snapshot-value">{_escape_markup(value)}</strong></div>'
        for label, value in visible_metrics
    )
    st.html(f'<div class="ow-shell-snapshot-grid">{cards}</div>')


def _panel_key_token(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return text.strip("_") or "evidence"


def render_decision_evidence_panel(
    title: str,
    freshness: str,
    summary: str,
    metrics: Sequence[tuple[str, object]] = (),
    rows: object | None = None,
    actions: Sequence[tuple[str, str, Callable[[], None]]] = (),
    source_note: str = "",
) -> None:
    """Render a single compact proof surface below the Decision Workspace."""
    safe_title = _escape_markup(clean_display_text(title) or "Evidence")
    safe_freshness = _escape_markup(clean_display_text(freshness) or "Loaded evidence")
    safe_summary = _escape_markup(clean_display_text(summary) or "Evidence loaded for the selected scope.")
    safe_source = _escape_markup(clean_display_text(source_note))
    metric_html = "".join(
        '<div class="ow-decision-evidence-metric">'
        f'<span>{_escape_markup(clean_display_text(label))}</span>'
        f'<strong>{_escape_markup(clean_display_text(value))}</strong>'
        '</div>'
        for label, value in tuple(metrics or ())[:6]
    )
    source_html = f'<small>{safe_source}</small>' if safe_source else ""
    st.html(
        '<section class="ow-decision-evidence-panel" role="region" aria-label="Decision evidence panel">'
        '<div class="ow-decision-evidence-header">'
        f'<div><strong>{safe_title}</strong><p>{safe_summary}</p></div>'
        f'<span>{safe_freshness}</span>'
        '</div>'
        f'<div class="ow-decision-evidence-metrics">{metric_html}</div>'
        f'{source_html}'
        '</section>'
    )
    for idx, action in enumerate(tuple(actions or ())[:3]):
        label, help_text, callback = action
        if st.button(
            str(label),
            key=f"decision_evidence_action_{_panel_key_token(title)}_{idx}",
            help=str(help_text or "") or None,
            width="stretch",
        ):
            callback()
            st.rerun()
    if rows is not None and hasattr(rows, "empty") and not getattr(rows, "empty", True):
        st.dataframe(rows, width="stretch", hide_index=True)


def render_shell_status_strip(
    *,
    state: object,
    headline: object,
    detail: object = "",
) -> None:
    """Render the immediate section state before any workflow actions."""
    with st.container(border=True):
        copy_col, state_col = st.columns([4, 1])
        with copy_col:
            render_escaped_bold_text(headline or "Ready")
            detail = clean_display_text(detail)
            if detail:
                st.caption(detail)
        with state_col:
            _badge(state or "Ready")


def render_shell_kpi_row(metrics: tuple[tuple[str, object], ...]) -> None:
    """Render the shell KPI row with the existing compact card treatment."""
    render_shell_snapshot(metrics)


def render_first_paint_summary_shell(
    *,
    state: object,
    headline: object,
    detail: object = "",
    metrics: tuple[tuple[str, object], ...] = (),
    snapshot: tuple[tuple[str, object], ...] = (),
) -> None:
    """Render the shared first-paint status, KPI, and snapshot shell."""
    render_shell_status_strip(state=state, headline=headline, detail=detail)
    if metrics:
        render_shell_kpi_row(metrics)
    if snapshot:
        render_shell_snapshot(snapshot)


def render_section_first_paint_shell(spec: FirstPaintSummarySpec) -> None:
    """Render a standardized first-paint shell without starting data work."""
    metrics = tuple(spec.metrics or ())
    if spec.view:
        metrics = (("Active view", spec.view),) + metrics
    expected_lanes = _format_expected_lanes(spec.expected_lanes)
    snapshot = tuple(spec.snapshot or ())
    if expected_lanes:
        snapshot = snapshot + (("Expected lanes", expected_lanes),)
    if spec.load_cta:
        snapshot = snapshot + (("Next safe action", spec.load_cta),)
    render_first_paint_summary_shell(
        state=spec.state,
        headline=spec.headline or f"{spec.section} is ready.",
        detail=spec.detail,
        metrics=metrics,
        snapshot=snapshot,
    )
    if spec.no_query_note:
        st.caption(clean_display_text(spec.no_query_note))


def render_breadcrumb(parts: Sequence[object]) -> None:
    """Render a compact section hierarchy breadcrumb."""
    visible = [clean_display_text(part) for part in parts or () if clean_display_text(part)]
    if not visible:
        return
    body = '<span class="ow-breadcrumb-separator">&rsaquo;</span>'.join(
        f'<span class="ow-breadcrumb-item">{_escape_markup(part)}</span>' for part in visible
    )
    st.html(f'<nav class="ow-breadcrumb" aria-label="Page location">{body}</nav>')


def render_kpi_hero_row(metrics: Sequence[Mapping[str, object] | tuple[object, object, object]]) -> None:
    """Render first-class KPI cards that tolerate unloaded/on-demand values."""
    cards: list[str] = []
    for raw_metric in metrics or ():
        if isinstance(raw_metric, Mapping):
            label = clean_display_text(raw_metric.get("label", ""))
            value = clean_display_text(raw_metric.get("value", "Summary unavailable"))
            detail = clean_display_text(raw_metric.get("detail", ""))
            tone = clean_display_text(raw_metric.get("tone", "neutral")).lower() or "neutral"
        else:
            values = tuple(raw_metric)
            label = clean_display_text(values[0] if len(values) > 0 else "")
            value = clean_display_text(values[1] if len(values) > 1 else "Summary unavailable")
            detail = clean_display_text(values[2] if len(values) > 2 else "")
            tone = "neutral"
        if not label:
            continue
        cards.append(
            '<article class="ow-kpi-hero-card" data-tone="'
            f'{_escape_markup(tone)}">'
            f'<span class="ow-kpi-hero-label">{_escape_markup(label)}</span>'
            f'<strong class="ow-kpi-hero-value">{_escape_markup(value or "Summary unavailable")}</strong>'
            f'<span class="ow-kpi-hero-detail">{_escape_markup(detail)}</span>'
            '</article>'
        )
    if cards:
        st.html(f'<section class="ow-kpi-hero-grid" aria-label="Key metrics">{"".join(cards)}</section>')


def render_single_choice_navigation(
    *,
    label: str,
    options: Sequence[object],
    active_value: object,
    key: str,
    class_name: str,
    label_class: str,
    format_func: Callable[[object], str] | None = None,
) -> str:
    """Render one real horizontal selection control for section navigation.

    This intentionally avoids the old decorative-card-plus-button pattern:
    the Streamlit segmented/radio widget is the single visible control.
    """
    values = tuple(str(option) for option in (options or ()))
    if not values:
        return str(active_value or "")
    active = str(active_value or values[0])
    if active not in values:
        active = values[0]
    if st.session_state.get(key) not in values:
        set_state(key, active)

    formatter = format_func or (lambda value: clean_display_text(value))
    st.html(
        f'<div class="{_escape_markup(class_name)}" data-active="{_escape_markup(active)}">'
        f'<span class="{_escape_markup(label_class)} ow-sr-only">{_escape_markup(clean_display_text(label))}</span>'
        '</div>'
    )
    segmented_control = getattr(st, "segmented_control", None)
    if callable(segmented_control):
        selected = segmented_control(
            label,
            values,
            **_supported_widget_kwargs(
                segmented_control,
                {
                    "selection_mode": "single",
                    "format_func": formatter,
                    "key": key,
                    "label_visibility": "collapsed",
                },
            ),
        )
    else:
        radio_kwargs = _supported_widget_kwargs(
            st.radio,
            {
                "index": values.index(active),
                "format_func": formatter,
                "key": key,
                "horizontal": True,
                "label_visibility": "collapsed",
            },
        )
        selected = st.radio(
            label,
            values,
            **radio_kwargs,
        )
    mark_widget_key_rendered(key)
    return str(selected or active)


def render_section_breadcrumb(parts: Sequence[object]) -> None:
    """Render the standard primary-section breadcrumb."""
    render_breadcrumb(parts)


def render_primary_section_tabs(
    *,
    label: str,
    options: Sequence[object],
    active_value: object,
    key: str,
    format_func: Callable[[object], str] | None = None,
) -> str:
    """Render app-wide primary section navigation as one horizontal control."""
    return render_single_choice_navigation(
        label=label,
        options=options,
        active_value=active_value,
        key=key,
        class_name="ow-section-tabs",
        label_class="ow-section-tabs-label",
        format_func=format_func,
    )


def render_secondary_lens_pills(
    *,
    label: str,
    options: Sequence[object],
    active_value: object,
    key: str,
    format_func: Callable[[object], str] | None = None,
) -> str:
    """Render app-wide secondary/lens navigation as one horizontal control."""
    return render_single_choice_navigation(
        label=label,
        options=options,
        active_value=active_value,
        key=key,
        class_name="ow-lens-pills",
        label_class="ow-lens-pills-label",
        format_func=format_func,
    )


def render_kpi_status_strip(metrics: Sequence[Mapping[str, object] | Sequence[object]]) -> None:
    """Render the standard first-paint KPI/status strip."""
    render_kpi_hero_row(metrics)


def render_content_header(title: object, detail: object = "") -> None:
    """Render the standard selected-content header."""
    render_content_panel(title, detail)


def render_recommended_action_strip(
    actions: Sequence[Mapping[str, object]],
    *,
    key_prefix: str,
    on_select: Callable[[Mapping[str, object]], None] | None = None,
) -> None:
    """Render recommended actions using the app-wide action card system."""
    st.html('<div class="ow-recommended-actions" aria-label="Recommended actions"></div>')
    render_action_cards(actions, key_prefix=key_prefix, on_select=on_select)


def render_advanced_evidence_area(label: str, *, expanded: bool = False):
    """Return a standard advanced/evidence expander context manager."""
    st.html('<div class="ow-advanced-evidence" aria-label="Advanced evidence"></div>')
    return st.expander(label, expanded=expanded)


def render_explore_lens_selector(
    *,
    label: str,
    lenses: Sequence[object],
    active_value: object,
    key_prefix: str,
    on_select: Callable[[str], None] | None = None,
) -> str:
    """Render tertiary explore lenses as one real control, not duplicate cards."""
    selected = render_single_choice_navigation(
        label=label,
        options=tuple(str(lens) for lens in (lenses or ())),
        active_value=active_value,
        key=key_prefix,
        class_name="ow-lens-pills",
        label_class="ow-lens-pills-label",
        format_func=lambda value: clean_display_text(
            "Department" if str(value) == "Department / Cost Center" else value
        ),
    )
    if selected != str(active_value or "") and on_select is not None:
        on_select(selected)
    return selected


def render_action_cards(
    actions: Sequence[Mapping[str, object]],
    *,
    key_prefix: str,
    on_select: Callable[[Mapping[str, object]], None] | None = None,
) -> None:
    """Render recommended next actions as cards, not another workflow nav row."""
    cards = tuple(actions or ())
    if not cards:
        return
    st.html('<div class="ow-action-card-heading">Recommended next actions</div>')
    cols = st.columns(min(3, len(cards)))
    for idx, action in enumerate(cards):
        label = clean_display_text(action.get("label", "Action"))
        reason = clean_display_text(action.get("reason", action.get("description", "")))
        cta = clean_display_text(action.get("cta", label))
        with cols[idx % len(cols)]:
            st.html(
                '<article class="ow-action-card">'
                f'<strong>{_escape_markup(label)}</strong>'
                f'<span>{_escape_markup(reason)}</span>'
                '</article>'
            )
            if st.button(cta, key=f"{key_prefix}_{idx}_{_key_fragment(label)}", width="stretch"):
                if on_select is not None:
                    on_select(action)


def render_content_panel(title: object, detail: object = "") -> None:
    """Render a minimal selected-content line without creating another card."""
    st.html(
        '<section class="ow-content-header-line" aria-label="Selected workflow context">'
        f'<div class="ow-content-panel-title">{_escape_markup(clean_display_text(title))}</div>'
        f'<div class="ow-content-panel-detail">{_escape_markup(clean_display_text(detail))}</div>'
        '</section>'
    )


def _key_fragment(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return text.strip("_") or "item"


def render_signal_lane_board(
    title: str,
    lanes: Sequence[Mapping[str, object]],
    *,
    max_lanes: int = 12,
) -> None:
    """Render a dense dashboard lane board without starting new data work."""
    rows = []
    empty_values = {"", "on demand", "not loaded", "board frame only", "no snowflake scan", "explicit only"}
    for raw_row in lanes or ():
        row = dict(raw_row)
        value = clean_display_text(row.get("value") or row.get("VALUE") or "")
        if value.strip().lower() in empty_values:
            continue
        rows.append(row)
        if len(rows) >= max(1, int(max_lanes or 12)):
            break
    if not rows:
        return
    cards: list[str] = []
    for row in rows:
        label = clean_display_text(row.get("label") or row.get("LANE") or "Signal")
        value = clean_display_text(row.get("value") or row.get("VALUE") or "Summary unavailable")
        state = clean_display_text(row.get("state") or row.get("STATE") or "Review")
        detail = clean_display_text(row.get("detail") or row.get("DETAIL") or row.get("next") or row.get("NEXT_ACTION") or "")
        show_detail = bool(row.get("show_detail") or row.get("SHOW_DETAIL"))
        detail_html = (
            f'<div class="ow-signal-detail">{_escape_markup(detail)}</div>'
            if detail and show_detail
            else ""
        )
        cards.append(
            f'<div class="ow-signal-card"><div class="ow-signal-card-top">'
            f'<span class="ow-signal-label">{_escape_markup(label)}</span>'
            f'<span class="ow-signal-pill">{_escape_markup(state)}</span></div>'
            f'<div class="ow-signal-value">{_escape_markup(value)}</div>{detail_html}</div>'
        )
    st.html(
        f'<section class="ow-signal-board"><div class="ow-signal-title">{_escape_markup(clean_display_text(title))}</div>'
        f'<div class="ow-signal-grid">{"".join(cards)}</div></section>'
    )


def _workflow_key_token(value: object, index: int) -> str:
    raw = str(value or index).strip()
    token = "".join(ch.lower() if ch.isalnum() else "_" for ch in raw)
    token = "_".join(part for part in token.split("_") if part)
    return f"{index}_{token[:48] or 'workflow'}"


def render_shell_workflows(
    title: str,
    workflows: Sequence[Mapping[str, object]],
    *,
    label_key: str,
    key_prefix: str,
    on_open: Callable[[Mapping[str, object]], None],
    title_key: str | None = None,
    caption_key: str = "MOVE",
) -> None:
    """Render all shell workflow launchers without a hidden expansion rerun."""
    rows = list(workflows or ())
    if not rows:
        return
    render_escaped_bold_text(title)
    for start in range(0, len(rows), 3):
        chunk = rows[start:start + 3]
        cols = st.columns(len(chunk))
        for offset, (col, row) in enumerate(zip(cols, chunk)):
            index = start + offset
            workflow_value = row.get(label_key, f"Workflow {index + 1}")
            heading = row.get(title_key or label_key, workflow_value)
            button_label = clean_display_text(row.get("BUTTON_LABEL") or f"Open {heading}")
            key_token = _workflow_key_token(workflow_value, index)
            with col:
                render_escaped_bold_text(heading)
                caption = clean_display_text(row.get(caption_key) or "").strip()
                if st.button(
                    button_label,
                    key=f"{key_prefix}_{key_token}",
                    width="stretch",
                ):
                    on_open(row)
