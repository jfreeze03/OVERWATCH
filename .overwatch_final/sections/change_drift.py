# sections/change_drift.py - Change Drift compatibility facade/route
from __future__ import annotations

import streamlit as st

from sections.base import lazy_util as _lazy_util
from sections.change_drift_action_queue import *
from sections.change_drift_action_queue import __all__ as _action_queue_all
from sections.change_drift_brief_view import *
from sections.change_drift_brief_view import __all__ as _brief_view_all
from sections.change_drift_common import *
from sections.change_drift_common import __all__ as _common_all
from sections.change_drift_contracts import *
from sections.change_drift_contracts import __all__ as _contracts_all
from sections.change_drift_models import *
from sections.change_drift_models import __all__ as _models_all
from sections.change_drift_sql import *
from sections.change_drift_sql import __all__ as _sql_all
from sections.change_drift_workflows_view import *
from sections.change_drift_workflows_view import __all__ as _workflows_view_all
from utils.primitives import safe_int


day_window_selectbox = _lazy_util("day_window_selectbox")
render_mode_selector = _lazy_util("render_mode_selector")


CHANGE_DRIFT_RENDERERS = {
    "Change Brief": render_change_brief,
    "Change Workflows": render_change_workflows,
}


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    if st.session_state.get("exceptions_only_mode") and "change_drift_workflow" not in st.session_state:
        st.session_state["change_drift_workflow"] = "Object and access changes"
    if st.session_state.get("exceptions_only_mode") and "change_drift_view" not in st.session_state:
        st.session_state["change_drift_view"] = "Change Brief"
    if st.session_state.get("change_drift_view") not in CHANGE_DRIFT_VIEWS:
        st.session_state["change_drift_view"] = CHANGE_DRIFT_VIEWS[0]
    _apply_change_brief_first_default()
    _apply_queued_change_workflow()
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="estimated",
        scope_note="Object/change detection is query-history based; SHOW commands fill live metadata gaps.",
    )
    render_operator_briefing(
        [
            ("First move", "Identify who changed what and whether Snowflake telemetry exists."),
            ("Telemetry", "Preserve query ID, actor, object, timestamp, and dependency context."),
            ("Control", "Route drift to reviewer context, rollback status, or a guarded DBA action."),
            ("Output", "Build an audit-ready change narrative with blast-radius notes."),
        ],
        columns=4,
    )
    days = safe_int(st.session_state.get("change_drift_brief_days", 14), 14)
    if days < 1 or days > 90:
        days = 14
    summary = st.session_state.get("change_drift_summary")
    exceptions = st.session_state.get("change_drift_exceptions")
    meta = st.session_state.get("change_drift_meta", {})
    _render_change_action_brief(
        _change_action_brief(summary, exceptions, meta, company, environment, days)
    )
    _render_change_operating_snapshot(
        _change_operating_snapshot(summary, exceptions, meta, company, environment, days)
    )

    days = day_window_selectbox(
        "Change brief lookback",
        key="change_drift_brief_days",
        default=14,
    )
    active_view = render_mode_selector(
        "Object-change view",
        "change_drift_view",
        CHANGE_DRIFT_VIEWS,
        default=CHANGE_DRIFT_VIEWS[0],
        details=CHANGE_DRIFT_VIEW_DETAILS,
        columns=2,
    )
    CHANGE_DRIFT_RENDERERS.get(active_view, render_change_brief)(company, environment, days)


__all__ = sorted(set(
    list(_contracts_all)
    + list(_common_all)
    + list(_sql_all)
    + list(_models_all)
    + list(_action_queue_all)
    + list(_brief_view_all)
    + list(_workflows_view_all)
    + ["CHANGE_DRIFT_RENDERERS", "render"]
))
