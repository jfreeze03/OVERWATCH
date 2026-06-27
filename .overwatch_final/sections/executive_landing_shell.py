"""Lightweight Executive Landing route renderer.

The compatibility facade in ``sections.executive_landing`` still re-exports
the historical public surface. This route module keeps app first paint cheaper
by importing only the active workflow renderer after the shell state is ready.
"""
from __future__ import annotations

import importlib

import streamlit as st

from config import DEFAULT_DAY_WINDOW
from performance import EVIDENCE_CLICK_QUERY_BUDGET, query_budget_context
from runtime_state import EXECUTIVE_LANDING_WORKFLOW, GLOBAL_END_DATE, GLOBAL_START_DATE, get_state
from sections.base import lazy_util as _lazy_util
from sections.triage_queue import render_mission_control_queue
from sections.executive_landing_common import (
    _active_company,
    _active_environment,
    _credit_price,
    _ensure_executive_landing_workflow_state,
    normalize_executive_landing_workflow,
)
from sections.executive_landing_contracts import (
    EXECUTIVE_ACTIONS_WORKFLOW,
    EXECUTIVE_ADMIN_WORKFLOW,
    EXECUTIVE_CHANGE_SUMMARY_WORKFLOW,
    EXECUTIVE_COST_MOVEMENT_WORKFLOW,
    EXECUTIVE_LANDING_WORKFLOW_DETAILS,
    EXECUTIVE_LANDING_WORKFLOWS,
    EXECUTIVE_OPERATIONAL_RISK_WORKFLOW,
    EXECUTIVE_OVERVIEW_WORKFLOW,
    EXECUTIVE_SECURITY_RISK_WORKFLOW,
    PLATFORM_SUMMARY_STATE_KEY,
)
from sections.executive_landing_data import (
    _current_observability_board,
    _executive_observability_board_empty,
    _executive_observability_connection_unavailable,
    _load_executive_observability,
    _load_executive_snapshot,
    _observability_payload_is_offline,
    _store_connection_unavailable_observability,
)
from sections.executive_landing_models import (
    _default_platform_summary,
    _executive_snapshot_scope,
    _persist_platform_summary,
    _snapshot_matches_scope,
    _snapshot_state,
    _source_health_rows,
    _summary_from_observability,
    _with_platform_operating_score,
)
from sections.shell_helpers import render_content_header, render_primary_section_tabs, render_section_breadcrumb
from sections.section_command_brief import autoload_section_command_brief
from sections.section_command_rendering import render_section_command_brief
from sections.decision_workspace_controls import make_decision_refresh_action, make_evidence_action
from sections.decision_workspace_performance import with_section_first_paint_entry
from sections.decision_workspace_scope import active_decision_window_days
from sections.decision_workspace_state import section_state_from_brief
from perf_trace import trace
from utils.section_guidance import defer_source_note


get_session_for_action = _lazy_util("get_session_for_action")


def _active_window_days() -> int:
    """Return the command-bar window in days without rendering a second section widget."""
    start_date = get_state(GLOBAL_START_DATE)
    end_date = get_state(GLOBAL_END_DATE)
    if start_date and end_date:
        try:
            return max(1, int((end_date - start_date).days))
        except Exception:
            return int(DEFAULT_DAY_WINDOW)
    return int(DEFAULT_DAY_WINDOW)

EXECUTIVE_LANDING_RENDERER_PATHS = {
    EXECUTIVE_OVERVIEW_WORKFLOW: (
        "sections.executive_landing_overview_view",
        "render_executive_overview",
    ),
    EXECUTIVE_COST_MOVEMENT_WORKFLOW: (
        "sections.executive_landing_cost_view",
        "render_executive_cost_movement",
    ),
    EXECUTIVE_OPERATIONAL_RISK_WORKFLOW: (
        "sections.executive_landing_operational_view",
        "render_executive_operational_risk",
    ),
    EXECUTIVE_SECURITY_RISK_WORKFLOW: (
        "sections.executive_landing_security_view",
        "render_executive_security_risk",
    ),
    EXECUTIVE_CHANGE_SUMMARY_WORKFLOW: (
        "sections.executive_landing_change_view",
        "render_executive_change_summary",
    ),
    EXECUTIVE_ACTIONS_WORKFLOW: (
        "sections.executive_landing_actions_view",
        "render_executive_actions",
    ),
    EXECUTIVE_ADMIN_WORKFLOW: (
        "sections.executive_landing_admin_view",
        "render_executive_admin_advanced",
    ),
}


def _workflow_renderer(active_workflow: str):
    module_path, function_name = EXECUTIVE_LANDING_RENDERER_PATHS[active_workflow]
    with trace(f"executive_shell:workflow_renderer_import:{module_path}", active_section="Executive Landing"):
        module = importlib.import_module(module_path)
    return getattr(module, function_name)


def _render_loaded_executive_landing_workflow(
    active_workflow: str,
    *,
    summary: dict,
    company: str,
    environment: str,
    days: int,
    credit_price: float,
    board,
    board_payload: dict,
    snapshot: dict | None,
    source_health,
) -> bool:
    renderer = _workflow_renderer(active_workflow)
    with trace(
        f"executive_shell:workflow_renderer_render:{active_workflow}",
        active_section="Executive Landing",
    ):
        return bool(
            renderer(
                summary=summary,
                company=company,
                environment=environment,
                days=int(days),
                credit_price=credit_price,
                board=board,
                board_payload=board_payload,
                snapshot=snapshot,
                source_health=source_health,
            )
        )


def _render_executive_landing_workflow_controls(active_workflow: str) -> str:
    labels = {
        EXECUTIVE_OVERVIEW_WORKFLOW: "Overview",
        EXECUTIVE_COST_MOVEMENT_WORKFLOW: "Cost",
        EXECUTIVE_OPERATIONAL_RISK_WORKFLOW: "Operations",
        EXECUTIVE_SECURITY_RISK_WORKFLOW: "Security",
        EXECUTIVE_CHANGE_SUMMARY_WORKFLOW: "Changes",
        EXECUTIVE_ACTIONS_WORKFLOW: "Actions",
        EXECUTIVE_ADMIN_WORKFLOW: "Evidence",
    }
    selected = render_primary_section_tabs(
        label="Executive Landing primary navigation",
        options=EXECUTIVE_LANDING_WORKFLOWS,
        active_value=active_workflow,
        key=EXECUTIVE_LANDING_WORKFLOW,
        format_func=lambda value: labels.get(str(value), str(value)),
    )
    active_workflow = normalize_executive_landing_workflow(selected)
    if active_workflow != EXECUTIVE_OVERVIEW_WORKFLOW:
        render_section_breadcrumb(["Executive Landing", labels.get(active_workflow, active_workflow)])
        render_content_header(
            labels.get(active_workflow, active_workflow),
            EXECUTIVE_LANDING_WORKFLOW_DETAILS.get(active_workflow, "Executive evidence stays behind explicit load actions."),
        )
    return active_workflow


def render() -> None:
    with with_section_first_paint_entry("Executive Landing", "Entry"):
        with trace("executive_shell:state_helpers", active_section="Executive Landing"):
            company = _active_company()
            environment = _active_environment()
            credit_price = _credit_price()
            defer_source_note(
                "Executive Landing opens with precomputed observability facts; workflow detail and exports stay action-gated."
            )
            _ensure_executive_landing_workflow_state()

        with trace("executive_shell:scope_controls", active_section="Executive Landing"):
            days = active_decision_window_days(_active_window_days())
            active_workflow = normalize_executive_landing_workflow(
                st.session_state.get(EXECUTIVE_LANDING_WORKFLOW, EXECUTIVE_OVERVIEW_WORKFLOW)
            )

        with trace("executive_shell:workflow_selector", active_section="Executive Landing"):
            active_workflow = _render_executive_landing_workflow_controls(active_workflow)

        current_workflow_label = "Overview" if active_workflow == EXECUTIVE_OVERVIEW_WORKFLOW else active_workflow
        executive_brief = autoload_section_command_brief(
            "Executive Landing",
            company,
            environment,
            int(days),
            force=bool(st.session_state.pop("_executive_landing_command_brief_force_refresh", False)),
        )
        render_section_command_brief(
            executive_brief,
            key_prefix="executive_landing_command_brief",
            primary_action=make_decision_refresh_action("Executive Landing"),
            detail_action=make_evidence_action(
                "Executive Landing",
                active_workflow,
                label="Load Full Executive Snapshot",
                help_text="Load the heavier Executive Landing detail packet for the selected scope.",
                state_key="_executive_landing_command_brief_load_detail",
            )
            if active_workflow == EXECUTIVE_OVERVIEW_WORKFLOW
            else None,
            current_workflow=current_workflow_label,
            compact=active_workflow != EXECUTIVE_OVERVIEW_WORKFLOW,
        )

    if active_workflow == EXECUTIVE_OVERVIEW_WORKFLOW:
        command_brief_load = bool(st.session_state.pop("_executive_landing_command_brief_load_detail", False))
        if command_brief_load:
            with query_budget_context(
                "evidence_click",
                section="Executive Landing",
                workflow=EXECUTIVE_OVERVIEW_WORKFLOW,
                budget=EVIDENCE_CLICK_QUERY_BUDGET,
            ):
                if _load_executive_snapshot(company, environment, int(days)):
                    st.rerun()
        snapshot = st.session_state.get("executive_landing_snapshot")
        if isinstance(snapshot, dict) and _snapshot_matches_scope(snapshot, company, environment, int(days)):
            render_mission_control_queue(
                st.session_state,
                company=company,
                environment=environment,
            )
        return

    with trace("executive_shell:observability_board_state", active_section="Executive Landing"):
        expected_scope = _executive_snapshot_scope(company, environment, int(days))
        board, board_payload = _current_observability_board(company, environment, int(days))
        board_empty = _executive_observability_board_empty(board)
        needs_first_load = board_empty or _observability_payload_is_offline(board_payload)
        if needs_first_load:
            if board_empty and _executive_observability_connection_unavailable():
                _store_connection_unavailable_observability(company, environment, int(days))
            st.session_state["_executive_landing_observability_autoload_scope"] = expected_scope
            board, board_payload = _current_observability_board(company, environment, int(days))
    with trace("executive_shell:summary_build", active_section="Executive Landing"):
        snapshot = st.session_state.get("executive_landing_snapshot")
        if isinstance(snapshot, dict) and not _snapshot_matches_scope(snapshot, company, environment, int(days)):
            defer_source_note(
                "Loaded Executive Landing snapshot is for another scope. Reload the snapshot for the selected company, environment, and window."
            )
            st.session_state.pop(PLATFORM_SUMMARY_STATE_KEY, None)
            snapshot = None
        summary = _summary_from_observability(board, credit_price=credit_price, state=st.session_state)
        source_health = None
        if isinstance(snapshot, dict):
            source_health = _source_health_rows(snapshot)
            summary = _snapshot_state(snapshot.get("cost"), snapshot.get("alerts"), snapshot.get("queue"), snapshot.get("migration"))
            summary = _with_platform_operating_score(summary, source_health)
            _persist_platform_summary(summary)
        elif summary:
            _persist_platform_summary(summary)
        else:
            summary = _default_platform_summary()
            _persist_platform_summary(summary)

        snapshot = st.session_state.get("executive_landing_snapshot")
        has_loaded_snapshot = isinstance(snapshot, dict) and _snapshot_matches_scope(snapshot, company, environment, int(days))
        loaded_snapshot = snapshot if has_loaded_snapshot else None

        if isinstance(loaded_snapshot, dict):
            for err in loaded_snapshot.get("errors", []):
                defer_source_note(err)

        if isinstance(loaded_snapshot, dict) and source_health is None:
            source_health = _source_health_rows(loaded_snapshot)
            summary = _with_platform_operating_score(summary, source_health)
            _persist_platform_summary(summary)

    decision_state = section_state_from_brief(executive_brief, detail_loaded=bool(loaded_snapshot))
    load = False
    if active_workflow != EXECUTIVE_OVERVIEW_WORKFLOW:
        load = _render_loaded_executive_landing_workflow(
            active_workflow,
            summary=summary,
            company=company,
            environment=environment,
            days=int(days),
            credit_price=credit_price,
            board=board,
            board_payload=board_payload,
            snapshot=loaded_snapshot,
            source_health=source_health,
        )
    elif decision_state.decision_mode == "READY" and loaded_snapshot:
        render_mission_control_queue(
            st.session_state,
            company=company,
            environment=environment,
        )

    if load and _load_executive_snapshot(company, environment, int(days)):
        st.rerun()


__all__ = [
    "EXECUTIVE_LANDING_RENDERER_PATHS",
    "render",
    "_render_loaded_executive_landing_workflow",
]
