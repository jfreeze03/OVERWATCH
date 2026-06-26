"""Shared controls for Decision Workspace refresh and evidence actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import streamlit as st


DECISION_REFRESH_KEYS: dict[str, str] = {
    "Executive Landing": "_executive_landing_command_brief_force_refresh",
    "DBA Control Room": "dba_control_room_command_brief_force_refresh",
    "Alert Center": "alert_center_command_brief_force_refresh",
    "Cost & Contract": "cost_contract_command_brief_force_refresh",
    "Workload Operations": "workload_operations_command_brief_force_refresh",
    "Security Monitoring": "security_posture_command_brief_force_refresh",
}


@dataclass(frozen=True)
class DecisionWorkspaceControls:
    refresh_packet: Callable[[], None] | None = None
    load_evidence: Callable[[], None] | None = None
    evidence_label: str = ""
    evidence_help: str = ""
    evidence_settings: Callable[[], None] | None = None
    current_workflow: str = ""
    section: str = ""


def decision_refresh_key(section: str) -> str:
    return DECISION_REFRESH_KEYS[str(section)]


def make_decision_refresh_action(section: str) -> Callable[[], None]:
    """Return a callback that only requests a command-packet refresh."""

    refresh_key = decision_refresh_key(section)

    def _refresh() -> None:
        st.session_state[refresh_key] = True

    return _refresh


def make_evidence_action(
    section: str,
    workflow: str,
    *,
    label: str,
    help_text: str = "",
    callback: Callable[[], None] | None = None,
    state_key: str = "",
    key: str | None = None,
) -> Any | None:
    """Return a renderer-compatible evidence action when a real boundary exists."""
    if callback is None and not state_key:
        return None
    refresh_key = DECISION_REFRESH_KEYS.get(str(section))

    def _load() -> None:
        if callback is not None:
            callback()
            return
        if state_key:
            st.session_state[state_key] = True

    # Guard the contract: evidence must not be modeled as packet refresh.
    if state_key and refresh_key and state_key == refresh_key:
        return None

    from sections.section_command_rendering import CommandBriefDetailAction

    action_key = key or f"{section}_{workflow}_{label}".lower().replace(" ", "_")
    return CommandBriefDetailAction(label, help_text, _load, key=action_key)


def render_evidence_settings(label: str, render_body: Callable[[], None] | None, *, expanded: bool = False) -> None:
    """Render compact detail/evidence controls outside the first viewport."""
    if render_body is None:
        return
    with st.expander(label, expanded=expanded):
        render_body()


__all__ = [
    "DECISION_REFRESH_KEYS",
    "DecisionWorkspaceControls",
    "decision_refresh_key",
    "make_decision_refresh_action",
    "make_evidence_action",
    "render_evidence_settings",
]
