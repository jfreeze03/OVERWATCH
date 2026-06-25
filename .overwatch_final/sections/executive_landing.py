"""Executive Landing compatibility facade and renderer dispatch shell."""
from __future__ import annotations

import streamlit as st

import sections.executive_landing_actions_view as _actions_exports
import sections.executive_landing_admin_view as _admin_exports
import sections.executive_landing_charts as _charts_exports
import sections.executive_landing_common as _common_exports
import sections.executive_landing_contracts as _contracts_exports
import sections.executive_landing_cost_view as _cost_exports
import sections.executive_landing_data as _data_exports
import sections.executive_landing_data_health_view as _data_health_exports
import sections.executive_landing_models as _models_exports
import sections.executive_landing_operational_view as _operational_exports
import sections.executive_landing_overview_view as _overview_exports
import sections.executive_landing_security_view as _security_exports
import sections.executive_landing_change_view as _change_exports
from sections.executive_landing_actions_view import *  # noqa: F403
from sections.executive_landing_admin_view import *  # noqa: F403
from sections.executive_landing_charts import *  # noqa: F403
from sections.executive_landing_common import *  # noqa: F403
from sections.executive_landing_contracts import *  # noqa: F403
from sections.executive_landing_cost_view import *  # noqa: F403
from sections.executive_landing_data import *  # noqa: F403
from sections.executive_landing_data_health_view import *  # noqa: F403
from sections.executive_landing_models import *  # noqa: F403
from sections.executive_landing_operational_view import *  # noqa: F403
from sections.executive_landing_overview_view import *  # noqa: F403
from sections.executive_landing_security_view import *  # noqa: F403
from sections.executive_landing_change_view import *  # noqa: F403
from config import DAY_WINDOW_OPTIONS, DEFAULT_DAY_WINDOW
from runtime_state import EXECUTIVE_LANDING_WORKFLOW
from sections.base import lazy_util as _lazy_util
from sections.shell_helpers import render_content_header, render_primary_section_tabs, render_section_breadcrumb
from utils.section_guidance import defer_source_note


get_session_for_action = _lazy_util("get_session_for_action")

EXECUTIVE_LANDING_RENDERERS = {
    EXECUTIVE_OVERVIEW_WORKFLOW: render_executive_overview,
    EXECUTIVE_COST_MOVEMENT_WORKFLOW: render_executive_cost_movement,
    EXECUTIVE_OPERATIONAL_RISK_WORKFLOW: render_executive_operational_risk,
    EXECUTIVE_SECURITY_RISK_WORKFLOW: render_executive_security_risk,
    EXECUTIVE_CHANGE_SUMMARY_WORKFLOW: render_executive_change_summary,
    EXECUTIVE_ACTIONS_WORKFLOW: render_executive_actions,
    EXECUTIVE_ADMIN_WORKFLOW: render_executive_admin_advanced,
}


def _render_loaded_executive_landing_workflow(active_workflow: str, *, summary: dict, company: str, environment: str, days: int, credit_price: float, board, board_payload: dict, snapshot: dict | None, source_health) -> bool:
    renderer = EXECUTIVE_LANDING_RENDERERS.get(active_workflow)
    if renderer is None:
        st.session_state[EXECUTIVE_LANDING_WORKFLOW] = EXECUTIVE_OVERVIEW_WORKFLOW
        st.rerun()
    return bool(renderer(summary=summary, company=company, environment=environment, days=int(days), credit_price=credit_price, board=board, board_payload=board_payload, snapshot=snapshot, source_health=source_health))


def render() -> None:
    company = _active_company()
    environment = _active_environment()
    credit_price = _credit_price()
    defer_source_note("Executive Landing opens with precomputed observability facts; workflow detail and exports stay action-gated.")

    _ensure_executive_landing_workflow_state()
    window_col, refresh_col, _window_spacer = st.columns([1.2, 1.0, 2.2])
    with window_col:
        days = st.selectbox("Executive window", DAY_WINDOW_OPTIONS, index=DAY_WINDOW_OPTIONS.index(DEFAULT_DAY_WINDOW), format_func=lambda value: f"{value} days")
    with refresh_col:
        refresh_board = st.button("Refresh Summary", key="executive_landing_observability_refresh", type="primary", width="stretch")
    workflow_labels = {
        EXECUTIVE_OVERVIEW_WORKFLOW: "Overview",
        EXECUTIVE_COST_MOVEMENT_WORKFLOW: "Cost",
        EXECUTIVE_OPERATIONAL_RISK_WORKFLOW: "Operations",
        EXECUTIVE_SECURITY_RISK_WORKFLOW: "Security",
        EXECUTIVE_CHANGE_SUMMARY_WORKFLOW: "Changes",
        EXECUTIVE_ACTIONS_WORKFLOW: "Actions",
        EXECUTIVE_ADMIN_WORKFLOW: "Evidence",
    }
    render_section_breadcrumb(["Executive Landing", workflow_labels.get(str(st.session_state.get(EXECUTIVE_LANDING_WORKFLOW) or EXECUTIVE_OVERVIEW_WORKFLOW), "Overview")])
    active_workflow = render_primary_section_tabs(
        label="Executive Landing primary navigation",
        options=EXECUTIVE_LANDING_WORKFLOWS,
        active_value=st.session_state.get(EXECUTIVE_LANDING_WORKFLOW, EXECUTIVE_OVERVIEW_WORKFLOW),
        key=EXECUTIVE_LANDING_WORKFLOW,
        format_func=lambda value: workflow_labels.get(str(value), str(value)),
    )
    active_workflow = normalize_executive_landing_workflow(active_workflow)
    render_content_header(
        workflow_labels.get(active_workflow, active_workflow),
        EXECUTIVE_LANDING_WORKFLOW_DETAILS.get(active_workflow, "Executive evidence stays behind explicit load actions."),
    )

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
        refresh_session = get_session_for_action("refresh executive summaries", surface="Executive Landing", offline_note="Executive Landing will keep showing the local shell state until Snowflake is configured.")
        if refresh_session is None:
            _store_connection_unavailable_observability(company, environment, int(days))
        else:
            _load_executive_observability(company, environment, int(days), credit_price=credit_price)
        st.session_state["_executive_landing_observability_scope"] = expected_scope
        board, board_payload = _current_observability_board(company, environment, int(days))

    snapshot = st.session_state.get("executive_landing_snapshot")
    if isinstance(snapshot, dict) and not _snapshot_matches_scope(snapshot, company, environment, int(days)):
        defer_source_note("Loaded Executive Landing snapshot is for another scope. Reload the snapshot for the selected company, environment, and window.")
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

    load = _render_loaded_executive_landing_workflow(active_workflow, summary=summary, company=company, environment=environment, days=int(days), credit_price=credit_price, board=board, board_payload=board_payload, snapshot=loaded_snapshot, source_health=source_health)

    if load and _load_executive_snapshot(company, environment, int(days)):
        st.rerun()


__all__ = sorted(set(["EXECUTIVE_LANDING_RENDERERS", "render", "_render_loaded_executive_landing_workflow"] + _actions_exports.__all__ + _admin_exports.__all__ + _charts_exports.__all__ + _common_exports.__all__ + _contracts_exports.__all__ + _cost_exports.__all__ + _data_exports.__all__ + _data_health_exports.__all__ + _models_exports.__all__ + _operational_exports.__all__ + _overview_exports.__all__ + _security_exports.__all__ + _change_exports.__all__))
