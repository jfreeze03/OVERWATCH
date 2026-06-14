"""Small shared helpers for fast first-paint section shells."""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

import streamlit as st


_SNAPSHOT_GRID_STYLE = (
    "display:grid;"
    "gap:0.65rem;"
    "margin:0.35rem 0 0.85rem;"
)
_SNAPSHOT_CARD_STYLE = (
    "min-width:0;"
    "border:1px solid var(--border-subtle, rgba(41,181,232,0.18));"
    "border-radius:8px;"
    "background:rgba(var(--accent-rgb, 41,181,232),0.045);"
    "padding:0.68rem 0.78rem;"
)
_SNAPSHOT_LABEL_STYLE = (
    "display:block;"
    "color:var(--text-muted, #7b9cab);"
    "font-size:0.66rem;"
    "font-weight:850;"
    "letter-spacing:0.04em;"
    "line-height:1.22;"
    "text-transform:uppercase;"
    "overflow-wrap:anywhere;"
)
_SNAPSHOT_VALUE_STYLE = (
    "display:block;"
    "color:var(--text-primary, #eef8fb);"
    "font-size:0.96rem;"
    "font-weight:850;"
    "line-height:1.28;"
    "margin-top:0.26rem;"
    "overflow-wrap:anywhere;"
)
_LANE_GRID_STYLE = (
    "display:grid;"
    "grid-template-columns:repeat(auto-fit,minmax(11.5rem,1fr));"
    "gap:0.68rem;"
    "margin:0.35rem 0 0.9rem;"
)
_LANE_CARD_STYLE = (
    "min-width:0;"
    "border:1px solid var(--border-subtle, rgba(41,181,232,0.18));"
    "border-radius:8px;"
    "background:linear-gradient(180deg, rgba(var(--accent-rgb,41,181,232),0.06), rgba(var(--accent-rgb,41,181,232),0.025));"
    "padding:0.72rem 0.78rem;"
    "min-height:8.2rem;"
    "display:flex;"
    "flex-direction:column;"
    "gap:0.32rem;"
)
_LANE_TOP_STYLE = (
    "display:flex;"
    "align-items:flex-start;"
    "justify-content:space-between;"
    "gap:0.5rem;"
)
_LANE_TITLE_STYLE = (
    "color:var(--text-muted, #7b9cab);"
    "font-size:0.66rem;"
    "font-weight:850;"
    "letter-spacing:0.05em;"
    "line-height:1.22;"
    "text-transform:uppercase;"
    "overflow-wrap:anywhere;"
)
_LANE_STATE_STYLE = (
    "white-space:nowrap;"
    "border:1px solid var(--border-subtle, rgba(41,181,232,0.22));"
    "border-radius:999px;"
    "padding:0.14rem 0.4rem;"
    "color:var(--text-primary, #eef8fb);"
    "font-size:0.62rem;"
    "font-weight:850;"
    "line-height:1.2;"
    "text-transform:uppercase;"
)
_LANE_VALUE_STYLE = (
    "color:var(--text-primary, #eef8fb);"
    "font-size:1.05rem;"
    "font-weight:900;"
    "line-height:1.22;"
    "overflow-wrap:anywhere;"
)
_LANE_DETAIL_STYLE = (
    "color:var(--text-secondary, #b9d7e2);"
    "font-size:0.78rem;"
    "line-height:1.35;"
    "overflow-wrap:anywhere;"
)
_STATUS_STRIP_STYLE = (
    "display:flex;"
    "align-items:flex-start;"
    "justify-content:space-between;"
    "gap:0.75rem;"
    "border:1px solid var(--border-subtle, rgba(41,181,232,0.18));"
    "border-radius:8px;"
    "background:rgba(var(--accent-rgb, 41,181,232),0.055);"
    "padding:0.68rem 0.78rem;"
    "margin:0.2rem 0 0.7rem;"
)
_STATUS_COPY_STYLE = (
    "min-width:0;"
)
_STATUS_BADGE_STYLE = (
    "display:inline-flex;"
    "align-items:center;"
    "white-space:nowrap;"
    "border:1px solid var(--border-subtle, rgba(41,181,232,0.22));"
    "border-radius:999px;"
    "padding:0.22rem 0.5rem;"
    "color:var(--text-primary, #eef8fb);"
    "font-size:0.68rem;"
    "font-weight:850;"
    "text-transform:uppercase;"
)
_STATUS_HEADLINE_STYLE = (
    "color:var(--text-primary, #eef8fb);"
    "font-size:0.96rem;"
    "font-weight:850;"
    "line-height:1.28;"
    "margin:0 0 0.18rem;"
)
_STATUS_DETAIL_STYLE = (
    "color:var(--text-muted, #a8bdc8);"
    "font-size:0.82rem;"
    "line-height:1.42;"
    "margin:0;"
)
_FRESHNESS_STRIP_STYLE = (
    "display:flex;"
    "align-items:flex-start;"
    "justify-content:space-between;"
    "gap:0.7rem;"
    "border-top:1px solid var(--border-subtle, rgba(41,181,232,0.18));"
    "border-bottom:1px solid var(--border-subtle, rgba(41,181,232,0.12));"
    "padding:0.48rem 0.02rem;"
    "margin:0.25rem 0 0.65rem;"
)
_FRESHNESS_LABEL_STYLE = (
    "display:block;"
    "color:var(--text-muted, #7b9cab);"
    "font-size:0.62rem;"
    "font-weight:850;"
    "letter-spacing:0.06em;"
    "text-transform:uppercase;"
)
_FRESHNESS_DETAIL_STYLE = (
    "display:block;"
    "color:var(--text-secondary, #b9d7e2);"
    "font-size:0.78rem;"
    "line-height:1.34;"
    "margin-top:0.12rem;"
)

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
    """Summarize evidence freshness without starting a Snowflake query."""
    if not meta:
        return "On demand", "No evidence has been loaded for this scope."
    loaded_at = _parse_loaded_at((meta or {}).get("loaded_at"))
    source = str((meta or {}).get("source") or "Loaded evidence").strip()
    if loaded_at is None:
        return "Loaded", f"{source}; age unavailable. Refresh before acting."
    age_minutes = max(0.0, (datetime.now() - loaded_at).total_seconds() / 60.0)
    if age_minutes <= max(1, int(target_minutes or 60)):
        return "Current", f"{source}; loaded {_format_age(age_minutes)}."
    return "Stale", f"{source}; loaded {_format_age(age_minutes)}. Refresh before acting."


def render_data_freshness(
    meta: Mapping | None,
    *,
    source: str,
    target_minutes: int = 60,
    delayed_note: str = "ACCOUNT_USAGE and mart sources can lag; use live tools for in-flight incidents.",
) -> None:
    """Render a compact freshness/status note for data-first sections."""
    has_meta = bool(meta)
    merged = dict(meta or {})
    if source and has_meta and "source" not in merged:
        merged["source"] = source
    state, detail = freshness_state(merged if has_meta else None, target_minutes=target_minutes)
    safe_state = html.escape(state)
    safe_source = html.escape(str(source or merged.get("source") or "Evidence"))
    safe_detail = html.escape(detail)
    st.markdown(
        (
            f'<div class="ow-data-freshness" style="{_FRESHNESS_STRIP_STYLE}">'
            "<div>"
            f'<span style="{_FRESHNESS_LABEL_STYLE}">Data freshness - {safe_source}</span>'
            f'<span style="{_FRESHNESS_DETAIL_STYLE}">{safe_detail}</span>'
            "</div>"
            f'<span class="ow-shell-status-badge" style="{_STATUS_BADGE_STYLE}">{safe_state}</span>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    if delayed_note:
        st.caption(str(delayed_note))


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
    merged = dict(meta or {})
    if source and has_meta and "source" not in merged:
        merged["source"] = source
    state, detail = freshness_state(merged if has_meta else None, target_minutes=target_minutes)
    render_shell_snapshot((
        ("Source", source or merged.get("source") or "Precomputed facts"),
        ("Freshness", state),
        ("Target SLA", f"{max(1, int(target_minutes or 60))} min"),
        ("Live fallback", live_fallback),
    ))
    st.caption(f"{refresh_method}. {detail}")


def render_setup_health_board(
    title: str,
    objects: Sequence[tuple[str, object]],
    *,
    cadence: str = "Scheduled",
    fallback: str = "Explicit only",
    owner: str = "DBA",
) -> None:
    """Render the mart/object contract that supports a data-first command board."""
    if not objects:
        return
    st.markdown(f"**{html.escape(str(title))}**")
    rows = list(objects[:4])
    render_shell_snapshot(tuple(rows))
    details = []
    if cadence:
        details.append(f"cadence: {cadence}")
    if fallback:
        details.append(f"fallback: {fallback}")
    if owner:
        details.append(f"owner: {owner}")
    if details:
        st.caption("; ".join(details))


def evidence_caption(state, keys: tuple[str, ...], unloaded_caption: str) -> str:
    if evidence_loaded(state, keys):
        return "Loaded evidence is available; open the workspace to continue from the saved proof."
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


def render_shell_snapshot(metrics: tuple[tuple[str, object], ...]) -> None:
    """Render lightweight shell snapshot cards without the bulk of metric widgets."""
    if not metrics:
        return
    cards = []
    for label, value in metrics:
        cards.append(
            f'<div class="ow-shell-snapshot-card" style="{_SNAPSHOT_CARD_STYLE}">'
            f'<span class="ow-shell-snapshot-label" style="{_SNAPSHOT_LABEL_STYLE}">{html.escape(str(label))}</span>'
            f'<strong class="ow-shell-snapshot-value" style="{_SNAPSHOT_VALUE_STYLE}">{html.escape(str(value))}</strong>'
            "</div>"
        )
    column_count = max(1, min(4, len(cards)))
    st.markdown(
        (
            '<div class="ow-shell-snapshot-grid" '
            f'style="{_SNAPSHOT_GRID_STYLE}grid-template-columns: repeat({column_count}, minmax(0, 1fr));">'
            f'{"".join(cards)}</div>'
        ),
        unsafe_allow_html=True,
    )


def render_shell_status_strip(
    *,
    state: object,
    headline: object,
    detail: object = "",
) -> None:
    """Render the immediate section state before any workflow actions."""
    safe_state = html.escape(str(state or "Ready"))
    safe_headline = html.escape(str(headline or "Ready"))
    safe_detail = html.escape(str(detail or ""))
    st.markdown(
        (
            f'<div class="ow-shell-status-strip" style="{_STATUS_STRIP_STYLE}">'
            f'<div style="{_STATUS_COPY_STYLE}">'
            f'<p class="ow-shell-status-headline" style="{_STATUS_HEADLINE_STYLE}">{safe_headline}</p>'
            f'<p class="ow-shell-status-detail" style="{_STATUS_DETAIL_STYLE}">{safe_detail}</p>'
            "</div>"
            f'<span class="ow-shell-status-badge" style="{_STATUS_BADGE_STYLE}">{safe_state}</span>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_shell_kpi_row(metrics: tuple[tuple[str, object], ...]) -> None:
    """Render the shell KPI row with the existing compact card treatment."""
    render_shell_snapshot(metrics)


def render_signal_lane_board(
    title: str,
    lanes: Sequence[Mapping[str, object]],
    *,
    max_lanes: int = 12,
) -> None:
    """Render a dense dashboard lane board without starting new data work."""
    rows = [dict(row) for row in list(lanes or ())[: max(1, int(max_lanes or 12))]]
    if not rows:
        return
    st.markdown(f"**{html.escape(str(title))}**")
    cards = []
    for row in rows:
        label = html.escape(str(row.get("label") or row.get("LANE") or "Signal"))
        value = html.escape(str(row.get("value") or row.get("VALUE") or "Not loaded"))
        state = html.escape(str(row.get("state") or row.get("STATE") or "Review"))
        detail = html.escape(str(row.get("detail") or row.get("DETAIL") or row.get("next") or row.get("NEXT_ACTION") or ""))
        cards.append(
            f'<div class="ow-signal-lane-card" style="{_LANE_CARD_STYLE}">'
            f'<div style="{_LANE_TOP_STYLE}">'
            f'<span style="{_LANE_TITLE_STYLE}">{label}</span>'
            f'<span style="{_LANE_STATE_STYLE}">{state}</span>'
            "</div>"
            f'<strong style="{_LANE_VALUE_STYLE}">{value}</strong>'
            f'<span style="{_LANE_DETAIL_STYLE}">{detail}</span>'
            "</div>"
        )
    st.markdown(
        f'<div class="ow-signal-lane-grid" style="{_LANE_GRID_STYLE}">{"".join(cards)}</div>',
        unsafe_allow_html=True,
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
    """Render all shell workflow launchers without a hidden More/Hide rerun."""
    rows = list(workflows or ())
    if not rows:
        return
    st.markdown(f"**{html.escape(str(title))}**")
    for start in range(0, len(rows), 3):
        chunk = rows[start:start + 3]
        cols = st.columns(len(chunk))
        for offset, (col, row) in enumerate(zip(cols, chunk)):
            index = start + offset
            workflow_value = row.get(label_key, f"Workflow {index + 1}")
            heading = row.get(title_key or label_key, workflow_value)
            button_label = str(row.get("BUTTON_LABEL") or f"Open {heading}")
            key_token = _workflow_key_token(workflow_value, index)
            with col:
                st.markdown(f"**{html.escape(str(heading))}**")
                caption = str(row.get(caption_key) or "").strip()
                if st.button(
                    button_label,
                    key=f"{key_prefix}_{key_token}",
                    help=caption or None,
                    width="stretch",
                ):
                    on_open(row)
