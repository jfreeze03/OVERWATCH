"""Lightweight Executive Landing route renderer.

The compatibility facade in ``sections.executive_landing`` still re-exports
the historical public surface. This route module keeps app first paint cheaper
by importing only the active workflow renderer after the shell state is ready.
"""
from __future__ import annotations

import importlib

import streamlit as st

from config import DAY_WINDOW_OPTIONS, DEFAULT_DAY_WINDOW
from runtime_state import EXECUTIVE_LANDING_WORKFLOW
from sections.base import lazy_util as _lazy_util
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
from perf_trace import trace
from utils.section_guidance import defer_source_note


get_session_for_action = _lazy_util("get_session_for_action")
render_workflow_selector = _lazy_util("render_workflow_selector")

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


def render() -> None:
    with trace("executive_shell:state_helpers", active_section="Executive Landing"):
        company = _active_company()
        environment = _active_environment()
        credit_price = _credit_price()
        defer_source_note(
            "Executive Landing opens with precomputed observability facts; workflow detail and exports stay action-gated."
        )
        _ensure_executive_landing_workflow_state()

    with trace("executive_shell:workflow_selector", active_section="Executive Landing"):
        window_col, refresh_col, _window_spacer = st.columns([1.2, 1.0, 2.2])
        with window_col:
            days = st.selectbox(
                "Executive window",
                DAY_WINDOW_OPTIONS,
                index=DAY_WINDOW_OPTIONS.index(DEFAULT_DAY_WINDOW),
                format_func=lambda value: f"{value} days",
            )
        with refresh_col:
            refresh_board = st.button(
                "Refresh Summary",
                key="executive_landing_observability_refresh",
                type="primary",
                width="stretch",
            )
        active_workflow = render_workflow_selector(
            "Executive Landing workflow",
            EXECUTIVE_LANDING_WORKFLOW,
            EXECUTIVE_LANDING_WORKFLOWS,
            columns=4,
        )
        active_workflow = normalize_executive_landing_workflow(active_workflow)
        st.session_state[EXECUTIVE_LANDING_WORKFLOW] = active_workflow

    with trace("executive_shell:observability_board_state", active_section="Executive Landing"):
        expected_scope = _executive_snapshot_scope(company, environment, int(days))
        board, board_payload = _current_observability_board(company, environment, int(days))
        board_empty = _executive_observability_board_empty(board)
        needs_first_load = board_empty or _observability_payload_is_offline(board_payload)
        if needs_first_load:
            if board_empty and _executive_observability_connection_unavailable():
                _store_connection_unavailable_observability(company, environment, int(days))
            elif board_empty:
                defer_source_note(
                    "Executive Landing first paint is using the local summary frame. Use Refresh Summary to read the compact observability mart."
                )
            st.session_state["_executive_landing_observability_autoload_scope"] = expected_scope
            board, board_payload = _current_observability_board(company, environment, int(days))
    if refresh_board:
        refresh_session = get_session_for_action(
            "refresh executive summaries",
            surface="Executive Landing",
            offline_note="Executive Landing will keep showing the local shell state until Snowflake is configured.",
        )
        if refresh_session is None:
            _store_connection_unavailable_observability(company, environment, int(days))
        else:
            _load_executive_observability(company, environment, int(days), credit_price=credit_price)
        st.session_state["_executive_landing_observability_scope"] = expected_scope
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

    if load and _load_executive_snapshot(company, environment, int(days)):
        st.rerun()


__all__ = [
    "EXECUTIVE_LANDING_RENDERER_PATHS",
    "render",
    "_render_loaded_executive_landing_workflow",
]
