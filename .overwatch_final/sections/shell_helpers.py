"""Small shared helpers for fast first-paint section shells."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from html import escape as _escape_markup
import re

import streamlit as st

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
    text = _clean_display_text(label or "Ready")
    badge = getattr(st, "badge", None)
    if callable(badge):
        badge(text)
    else:
        st.caption(text)


_INTERNAL_OBJECT_RE = re.compile(
    r"\b(?:MART|FACT|DIM|DT|TMP|SP)_OVERWATCH_[A-Z0-9_]*\b|"
    r"\b(?:MART|FACT|DIM)_[A-Z0-9_]+\b|"
    r"\bOVERWATCH_[A-Z0-9_]+(?:\.sql)?\b|"
    r"\bSP_OVERWATCH_[A-Z0-9_]+\b"
)


def _clean_display_text(value: object) -> str:
    """Keep implementation object names and empty loader states out of the app chrome."""
    text = str(value or "").strip()
    if not text:
        return ""
    replacements = {
        "Not loaded": "On demand",
        "Awaiting mart": "Awaiting data",
        "MART_EXECUTIVE_OBSERVABILITY": "fast summary facts",
        "MART_DBA_CONTROL_ROOM": "DBA summary facts",
        "FACT_COST_DAILY": "cost facts",
        "FACT_CORTEX_DAILY": "AI spend facts",
        "snowflake/OVERWATCH_MART_SETUP.sql": "Snowflake status",
        "`snowflake/OVERWATCH_MART_SETUP.sql`": "Snowflake status",
        "setup SQL": "reviewed status",
        "Setup SQL": "reviewed status",
        "SQL Contracts": "Status",
        "SQL Contract": "Status",
        "Mart Contract": "Data Health",
        "mart contract": "data health",
        "DDL generation": "missing-object review",
        "generated DDL": "missing-object review",
        "generate missing DDL": "review missing objects",
        "missing-object DDL": "missing-object review",
        "DDL": "object change",
        "DBA release reviewer": "DBA change reviewer",
        "Release " "gate": "Operational status",
        "release " "gate": "operational status",
        "release remediation": "change remediation",
        "Approval Required": "Review",
        "Approval Needed": "Review",
        "Verification Required": "Telemetry pending",
        "Verification Needed": "Telemetry pending",
        "verification required": "telemetry pending",
        "verification needed": "telemetry pending",
        "approval required": "review pending",
        "approval needed": "review pending",
        "approval proof": "telemetry",
        "Approval proof": "Telemetry",
        "approval evidence": "telemetry",
        "Approval evidence": "Telemetry",
        "verification proof": "telemetry",
        "Verification proof": "Telemetry",
        "verification evidence": "telemetry",
        "Verification evidence": "Telemetry",
        "Closure Evidence": "Closure Status",
        "closure evidence": "closure status",
        "Evidence Blocked": "Telemetry Pending",
        "evidence blocked": "telemetry pending",
        "Evidence Missing": "Data Missing",
        "evidence missing": "data missing",
        "Proof Required": "Telemetry Basis",
        "proof required": "telemetry basis",
        "Proof": "Telemetry",
        "proof": "telemetry",
        "approval,": "review,",
        "approval and": "review and",
        "after approval": "after review",
        "before approval": "before review",
        "approved changes": "reviewed changes",
        "approved readiness": "reviewed status",
        "approved task": "reviewed task",
        "approved Workload": "reviewed Workload",
        "approved DBA": "reviewed DBA",
        "approved safe actions": "reviewed safe actions",
        "IAM / Security Owner": "IAM / Security Route",
        "Security Owner / Data Stewardship Lead": "Security / Data Stewardship Route",
        "Security Owner / Data Stewardship": "Security / Data Stewardship Route",
        "Security Owner / DBA Lead": "Security / DBA Route",
        "DBA Lead / Security Owner": "DBA / Security Route",
        "Data Owner / Security Owner": "Data / Security Route",
        "Data Owner / DBA Lead": "Data Route / DBA Lead",
        "DBA / Data Owner": "DBA / Data Route",
        "DBA Change Owner": "DBA Change Route",
        "Security Owner": "Security Route",
        "Data Owner": "Data Route",
        "Platform Owner": "Platform Route",
        "OVERWATCH Platform Owner": "OVERWATCH Platform Route",
        "BI Platform Owner": "BI Platform Route",
        "Development Platform Owner": "Development Platform Route",
        "Governance": "Monitoring",
        "governance": "monitoring",
        "Owner actions": "Routed actions",
        "Owner Route": "Escalation Route",
        "Owner route": "Escalation route",
        "owner route": "escalation route",
        "owner-routed": "route-backed",
        "owning workflow": "drilldown workflow",
        "owning admin workflow": "guarded admin workflow",
        "Needs Owner": "Needs route",
        "Owners": "Routes",
        "Owner": "Route",
        "owner": "route",
        "Source basis": "Basis",
        "Source " "Health": "Data Health",
        "source " "health": "data health",
        "source status": "data status",
        "source evidence": "data telemetry",
        "source proof": "input basis",
        "Data Readiness": "Data Health",
        "data readiness": "data health",
        "Readiness": "Status",
        "readiness": "status",
        "Architecture Review": "Monitoring Review",
        "architecture review": "monitoring review",
        "Architecture": "Monitoring",
        "architecture": "monitoring",
        "Closure proof": "Closure status",
        "closure proof": "closure status",
        "Proof query": "Telemetry query",
        "proof query": "telemetry query",
        "Evidence": "Telemetry",
        "evidence": "telemetry",
        "source-specific": "input-specific",
        "source surfaces": "data inputs",
        "source(s)": "input(s)",
        "sources": "inputs",
        "Sources": "Inputs",
        "ACCOUNT_USAGE": "account history",
        "mart sources": "fast summaries",
        "mart": "fast summary",
        "Mart": "Fast Summary",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = _INTERNAL_OBJECT_RE.sub("managed Snowflake object", text)
    return text


def _display_html(value: object) -> str:
    """Escape generated display text for small HTML fragments."""
    return _escape_markup(_clean_display_text(value))


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
        return "Loaded", f"{_clean_display_text(source)}; age unavailable. Refresh before acting."
    age_minutes = max(0.0, (datetime.now() - loaded_at).total_seconds() / 60.0)
    if age_minutes <= max(1, int(target_minutes or 60)):
        return "Current", f"{_clean_display_text(source)}; loaded {_format_age(age_minutes)}."
    return "Stale", f"{_clean_display_text(source)}; loaded {_format_age(age_minutes)}. Refresh before acting."


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
            st.caption(f"Data status - {_clean_display_text(source or merged.get('source') or 'Loaded data')}")
            render_escaped_bold_text(detail)
        with state_col:
            _badge(state)
    if delayed_note:
        st.caption(_clean_display_text(delayed_note))


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
        ("Data", _clean_display_text(source or merged.get("source") or "Summary facts")),
        ("Status", state),
    ))
    if detail:
        st.caption(_clean_display_text(detail))


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
        return _clean_display_text(lanes)
    try:
        values = [_clean_display_text(item) for item in lanes or ()]
    except TypeError:
        values = [_clean_display_text(lanes)]
    return ", ".join(value for value in values if value)


def render_shell_snapshot(metrics: tuple[tuple[str, object], ...]) -> None:
    """Render lightweight shell snapshot cards without the bulk of metric widgets."""
    visible_metrics = []
    empty_values = {"", "on demand", "not loaded", "board frame only", "no snowflake scan", "explicit only"}
    for label, value in metrics or ():
        clean_value = _clean_display_text(value)
        if clean_value.strip().lower() in empty_values:
            continue
        visible_metrics.append((_clean_display_text(label), clean_value))
    if not visible_metrics:
        return
    cards = "".join(
        f'<div class="ow-shell-snapshot-card"><span class="ow-shell-snapshot-label">{_escape_markup(label)}</span>'
        f'<strong class="ow-shell-snapshot-value">{_escape_markup(value)}</strong></div>'
        for label, value in visible_metrics
    )
    st.html(f'<div class="ow-shell-snapshot-grid">{cards}</div>')


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
            detail = _clean_display_text(detail)
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
        st.caption(_clean_display_text(spec.no_query_note))


def render_breadcrumb(parts: Sequence[object]) -> None:
    """Render a compact section hierarchy breadcrumb."""
    visible = [_clean_display_text(part) for part in parts or () if _clean_display_text(part)]
    if not visible:
        return
    body = '<span class="ow-breadcrumb-separator">›</span>'.join(
        f'<span class="ow-breadcrumb-item">{_escape_markup(part)}</span>' for part in visible
    )
    st.html(f'<nav class="ow-breadcrumb" aria-label="Page location">{body}</nav>')


def render_kpi_hero_row(metrics: Sequence[Mapping[str, object] | tuple[object, object, object]]) -> None:
    """Render first-class KPI cards that tolerate unloaded/on-demand values."""
    cards: list[str] = []
    for raw_metric in metrics or ():
        if isinstance(raw_metric, Mapping):
            label = _clean_display_text(raw_metric.get("label", ""))
            value = _clean_display_text(raw_metric.get("value", "On demand"))
            detail = _clean_display_text(raw_metric.get("detail", ""))
            tone = _clean_display_text(raw_metric.get("tone", "neutral")).lower() or "neutral"
        else:
            values = tuple(raw_metric)
            label = _clean_display_text(values[0] if len(values) > 0 else "")
            value = _clean_display_text(values[1] if len(values) > 1 else "On demand")
            detail = _clean_display_text(values[2] if len(values) > 2 else "")
            tone = "neutral"
        if not label:
            continue
        cards.append(
            '<article class="ow-kpi-hero-card" data-tone="'
            f'{_escape_markup(tone)}">'
            f'<span class="ow-kpi-hero-label">{_escape_markup(label)}</span>'
            f'<strong class="ow-kpi-hero-value">{_escape_markup(value or "On demand")}</strong>'
            f'<span class="ow-kpi-hero-detail">{_escape_markup(detail)}</span>'
            '</article>'
        )
    if cards:
        st.html(f'<section class="ow-kpi-hero-grid" aria-label="Key metrics">{"".join(cards)}</section>')


def render_local_section_menu(
    *,
    title: str,
    items: Sequence[Mapping[str, object]],
    active_value: object,
    key_prefix: str,
    on_select: Callable[[str], None] | None = None,
) -> str:
    """Render a section-local menu that is visually distinct from workflow button grids."""
    st.html(
        '<aside class="ow-local-nav" aria-label="Local section navigation">'
        f'<div class="ow-local-nav-title">{_escape_markup(_clean_display_text(title))}</div>'
        '</aside>'
    )
    active = str(active_value or "")
    selected = active
    for idx, item in enumerate(items or ()):
        label = _clean_display_text(item.get("label", ""))
        value = str(item.get("value", label))
        detail = _clean_display_text(item.get("detail", ""))
        group = _clean_display_text(item.get("group", ""))
        if group:
            st.html(f'<div class="ow-local-nav-group">{_escape_markup(group)}</div>')
        active_class = " ow-local-nav-item-active" if value == active else ""
        st.html(
            f'<div class="ow-local-nav-item{active_class}">'
            f'<strong>{_escape_markup(label)}</strong>'
            f'<span>{_escape_markup(detail)}</span>'
            '</div>'
        )
        if value != active and st.button(label, key=f"{key_prefix}_{idx}_{_key_fragment(value)}", width="stretch"):
            selected = value
            if on_select is not None:
                on_select(value)
    return selected


def render_explore_lens_selector(
    *,
    label: str,
    lenses: Sequence[object],
    active_value: object,
    key_prefix: str,
    on_select: Callable[[str], None] | None = None,
) -> str:
    """Render tertiary explore lenses without using eager Streamlit tabs."""
    active = str(active_value or "")
    st.html(f'<div class="ow-explore-tabs-label">{_escape_markup(_clean_display_text(label))}</div>')
    selected = active
    cols = st.columns(min(max(len(tuple(lenses or ())), 1), 4))
    for idx, lens in enumerate(lenses or ()):
        value = str(lens)
        with cols[idx % len(cols)]:
            active_class = " ow-explore-tab-active" if value == active else ""
            st.html(f'<div class="ow-explore-tab{active_class}">{_escape_markup(_clean_display_text(value))}</div>')
            if value != active and st.button(
                value,
                key=f"{key_prefix}_{idx}_{_key_fragment(value)}",
                width="stretch",
            ):
                selected = value
                if on_select is not None:
                    on_select(value)
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
        label = _clean_display_text(action.get("label", "Action"))
        reason = _clean_display_text(action.get("reason", action.get("description", "")))
        cta = _clean_display_text(action.get("cta", label))
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
    """Render the selected content panel header."""
    st.html(
        '<section class="ow-content-panel">'
        f'<div class="ow-content-panel-title">{_escape_markup(_clean_display_text(title))}</div>'
        f'<div class="ow-content-panel-detail">{_escape_markup(_clean_display_text(detail))}</div>'
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
        value = _clean_display_text(row.get("value") or row.get("VALUE") or "")
        if value.strip().lower() in empty_values:
            continue
        rows.append(row)
        if len(rows) >= max(1, int(max_lanes or 12)):
            break
    if not rows:
        return
    cards: list[str] = []
    for row in rows:
        label = _clean_display_text(row.get("label") or row.get("LANE") or "Signal")
        value = _clean_display_text(row.get("value") or row.get("VALUE") or "On demand")
        state = _clean_display_text(row.get("state") or row.get("STATE") or "Review")
        detail = _clean_display_text(row.get("detail") or row.get("DETAIL") or row.get("next") or row.get("NEXT_ACTION") or "")
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
        f'<section class="ow-signal-board"><div class="ow-signal-title">{_escape_markup(_clean_display_text(title))}</div>'
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
            button_label = _clean_display_text(row.get("BUTTON_LABEL") or f"Open {heading}")
            key_token = _workflow_key_token(workflow_value, index)
            with col:
                render_escaped_bold_text(heading)
                caption = _clean_display_text(row.get(caption_key) or "").strip()
                if st.button(
                    button_label,
                    key=f"{key_prefix}_{key_token}",
                    width="stretch",
                ):
                    on_open(row)
