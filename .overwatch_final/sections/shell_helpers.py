"""Small shared helpers for fast first-paint section shells."""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping, Sequence

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


def evidence_loaded(state, keys: tuple[str, ...]) -> bool:
    return any(state.get(key) is not None for key in keys)


def evidence_label(state, keys: tuple[str, ...]) -> str:
    return "Loaded" if evidence_loaded(state, keys) else "On demand"


def action_state_label(state, keys: tuple[str, ...]) -> str:
    return "Loaded" if evidence_loaded(state, keys) else "Ready"


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
                if caption:
                    st.caption(caption)
                if st.button(button_label, key=f"{key_prefix}_{key_token}", width="stretch"):
                    on_open(row)
