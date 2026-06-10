"""Small shared helpers for fast first-paint section shells."""

from __future__ import annotations

import html

import streamlit as st


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
            '<div class="ow-shell-snapshot-card">'
            f'<span>{html.escape(str(label))}</span>'
            f'<strong>{html.escape(str(value))}</strong>'
            "</div>"
        )
    column_count = max(1, min(4, len(cards)))
    st.markdown(
        (
            '<div class="ow-shell-snapshot-grid" '
            f'style="grid-template-columns: repeat({column_count}, minmax(0, 1fr));">'
            f'{"".join(cards)}</div>'
        ),
        unsafe_allow_html=True,
    )
