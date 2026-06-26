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
class CommandBriefDetailAction:
    label: str
    help_text: str
    callback: Callable[[], None]
    key: str | None = None
    settings_renderer: Callable[[], None] | None = None
    settings_label: str = "Evidence settings"


@dataclass(frozen=True)
class DecisionWorkspaceControls:
    section: str = ""
    current_workflow: str = ""
    refresh_packet: Callable[[], None] | None = None
    route_actions: tuple[Any, ...] = ()
    evidence_action: CommandBriefDetailAction | None = None
    evidence_settings: Callable[[], None] | None = None
    can_refresh: bool = True
    can_load_evidence: bool = False

    @property
    def load_evidence(self) -> Callable[[], None] | None:
        return self.evidence_action.callback if self.evidence_action is not None else None

    @property
    def evidence_label(self) -> str:
        return self.evidence_action.label if self.evidence_action is not None else ""

    @property
    def evidence_help(self) -> str:
        return self.evidence_action.help_text if self.evidence_action is not None else ""


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
    settings_renderer: Callable[[], None] | None = None,
    settings_label: str = "Evidence settings",
) -> CommandBriefDetailAction | None:
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

    action_key = key or f"{section}_{workflow}_{label}".lower().replace(" ", "_")
    return CommandBriefDetailAction(
        label,
        help_text,
        _load,
        key=action_key,
        settings_renderer=settings_renderer,
        settings_label=settings_label,
    )


def render_evidence_settings(label: str, render_body: Callable[[], None] | None, *, expanded: bool = False) -> None:
    """Render compact detail/evidence controls inside the evidence action panel."""
    if render_body is None:
        return
    with st.expander(label, expanded=expanded):
        render_body()


def should_render_daily_diagnostics(section: str, workflow: str, decision_mode: str) -> bool:
    """Return whether raw setup diagnostics belong on the current user surface."""
    workflow_text = str(workflow or "").lower()
    mode = str(decision_mode or "").upper()
    if st.session_state.get("overwatch_debug_diagnostics") or st.session_state.get("show_internal_diagnostics"):
        return True
    if any(token in workflow_text for token in ("admin", "advanced", "evidence")):
        return True
    if mode in {"OFFLINE", "UNINITIALIZED"} and (
        workflow_text in {"", "overview", "active", "morning"} or workflow_text.startswith("active")
    ):
        return False
    if st.session_state.get(f"{str(section).lower().replace(' ', '_')}_evidence_loaded"):
        return True
    return False


__all__ = [
    "DECISION_REFRESH_KEYS",
    "CommandBriefDetailAction",
    "DecisionWorkspaceControls",
    "decision_refresh_key",
    "make_decision_refresh_action",
    "make_evidence_action",
    "render_evidence_settings",
    "should_render_daily_diagnostics",
]
