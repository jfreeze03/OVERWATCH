"""Small shared helpers for fast first-paint section shells."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

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
    text = str(label or "Ready")
    badge = getattr(st, "badge", None)
    if callable(badge):
        badge(text)
    else:
        st.caption(text)


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
    with st.container(border=True):
        detail_col, state_col = st.columns([4, 1])
        with detail_col:
            st.caption(f"Data freshness - {source or merged.get('source') or 'Evidence'}")
            st.markdown(f"**{detail}**")
        with state_col:
            _badge(state)
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
    st.markdown(f"**{title}**")
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
    column_count = max(1, min(4, len(metrics)))
    cols = st.columns(column_count)
    for idx, (label, value) in enumerate(metrics):
        with cols[idx % column_count]:
            with st.container(border=True):
                st.caption(str(label))
                st.markdown(f"**{value}**")


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
            st.markdown(f"**{headline or 'Ready'}**")
            if detail:
                st.caption(str(detail))
        with state_col:
            _badge(state or "Ready")


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
    st.markdown(f"**{title}**")
    column_count = max(1, min(4, len(rows)))
    cols = st.columns(column_count)
    for idx, row in enumerate(rows):
        label = str(row.get("label") or row.get("LANE") or "Signal")
        value = str(row.get("value") or row.get("VALUE") or "Not loaded")
        state = str(row.get("state") or row.get("STATE") or "Review")
        detail = str(row.get("detail") or row.get("DETAIL") or row.get("next") or row.get("NEXT_ACTION") or "")
        show_detail = bool(row.get("show_detail") or row.get("SHOW_DETAIL"))
        with cols[idx % column_count]:
            with st.container(border=True):
                st.caption(label)
                _badge(state)
                st.markdown(f"**{value}**")
                if detail and show_detail:
                    st.caption(detail)


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
    st.markdown(f"**{title}**")
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
                st.markdown(f"**{heading}**")
                caption = str(row.get(caption_key) or "").strip()
                if st.button(
                    button_label,
                    key=f"{key_prefix}_{key_token}",
                    help=caption or None,
                    width="stretch",
                ):
                    on_open(row)
