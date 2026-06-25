# sections/security_posture.py - Security Monitoring compatibility facade and route shell
from __future__ import annotations

import streamlit as st

import sections.security_posture_access_changes_view as _access_changes_exports
import sections.security_posture_access_review as _access_review_exports
import sections.security_posture_action_queue as _action_queue_exports
import sections.security_posture_admin_view as _admin_exports
import sections.security_posture_alerts_view as _alerts_exports
import sections.security_posture_common as _common_exports
import sections.security_posture_contracts as _contracts_exports
import sections.security_posture_data as _data_exports
import sections.security_posture_models as _models_exports
import sections.security_posture_overview_view as _overview_exports
import sections.security_posture_privilege_sprawl_view as _privilege_exports
from sections.base import lazy_util as _lazy_util
from sections.security_posture_access_changes_view import _render_security_change_detail
from sections.security_posture_access_review import *  # noqa: F403
from sections.security_posture_action_queue import *  # noqa: F403
from sections.security_posture_admin_view import (
    _render_advanced_security_evidence,
    _render_security_action_approval,
    _render_security_command_findings,
    _render_security_ownership_coverage,
    _render_security_score_explanation,
    _render_security_source_health,
)
from sections.security_posture_alerts_view import _render_loaded_security_alert_context
from sections.security_posture_common import (
    _freshness_note,
    _metric_confidence_label,
    _mfa_count_expr,
    _mfa_gap_predicate,
    _mfa_proof_label,
    get_active_company,
    get_active_environment,
    render_operator_briefing,
    render_signal_confidence,
    render_workflow_guide,
    render_workflow_module,
)
from sections.security_posture_contracts import *  # noqa: F403
from sections.security_posture_data import (
    _build_security_mart_brief_sql,
    _build_security_summary_sql,
    _clear_security_exception_state,
    _load_security_brief,
    _store_security_summary,
)
from sections.security_posture_models import *  # noqa: F403
from sections.security_posture_overview_view import *  # noqa: F403
from sections.security_posture_privilege_sprawl_view import (
    _render_privileged_grant_readiness,
    render_security_privilege_sprawl,
)
from sections.security_posture_privilege_sprawl_view import *  # noqa: F403
from sections.command_deck import render_command_deck
from sections.command_deck_contracts import get_command_deck_contract
from sections.shell_helpers import (
    build_first_paint_summary_spec,
    render_content_header,
    render_primary_section_tabs,
    render_secondary_lens_pills,
    render_section_breadcrumb,
    render_section_first_paint_shell,
)
from sections.section_command_brief import autoload_section_command_brief
from sections.section_command_rendering import render_section_command_brief


day_window_selectbox = _lazy_util("day_window_selectbox")



def _apply_queued_security_workflow() -> None:
    requested_view = st.session_state.pop("security_posture_requested_view", None)
    requested_workflow = st.session_state.pop("security_posture_requested_workflow", None)
    requested_view = SECURITY_VIEW_ALIASES.get(str(requested_view or ""), requested_view)
    requested_workflow = SECURITY_VIEW_ALIASES.get(str(requested_workflow or ""), requested_workflow)
    if requested_view in SECURITY_POSTURE_VIEWS:
        st.session_state["security_posture_view"] = requested_view
    if requested_workflow in WORKFLOWS:
        st.session_state["security_posture_workflow"] = requested_workflow


def _render_security_first_paint_shell(active_view: str, company: str, environment: str, days: int) -> None:
    _ = active_view
    render_section_command_brief(
        autoload_section_command_brief("Security Monitoring", company, environment, int(days or 30)),
        key_prefix="security_monitoring_command_brief",
    )
    render_command_deck(
        get_command_deck_contract("Security Monitoring"),
        key_prefix="security_command_deck",
    )


def render_security_admin_advanced(company: str, environment: str, days: int) -> None:
    _render_security_source_health(company, environment)
    _render_privileged_grant_readiness(company, environment, days)
    _render_advanced_security_evidence(company, environment, skip_change_detail=False)


def render_security_alerts(company: str, environment: str, days: int) -> None:
    _ = days
    _render_loaded_security_alert_context()
    st.info(
        "Loaded security alerts appear here after an Alert Center route opens Security Monitoring. "
        "Use Failed Logins, Risky Grants, or Data Sharing Exposure for direct investigation."
    )
    _render_advanced_security_evidence(company, environment)


def render_security_access_changes(company: str, environment: str, days: int) -> None:
    _ = days
    _render_security_change_detail(
        company,
        environment,
        button_key="security_load_access_changes_intelligence",
    )
    _render_advanced_security_evidence(company, environment, skip_change_detail=True)


SECURITY_POSTURE_RENDERERS = {
    SECURITY_OVERVIEW_WORKFLOW: render_security_overview,
    PRIVILEGE_SPRAWL_WORKFLOW: render_security_privilege_sprawl,
    ACCESS_CHANGES_WORKFLOW: render_security_access_changes,
    SECURITY_ALERTS_WORKFLOW: render_security_alerts,
    SECURITY_ADMIN_ADVANCED_WORKFLOW: render_security_admin_advanced,
}


__all__ = sorted(set(
    [
        "SECURITY_POSTURE_RENDERERS",
        "_apply_queued_security_workflow",
        "render",
        "render_security_access_changes",
        "render_security_admin_advanced",
        "render_security_alerts",
    ]
    + _access_changes_exports.__all__
    + _access_review_exports.__all__
    + _action_queue_exports.__all__
    + _admin_exports.__all__
    + _alerts_exports.__all__
    + _common_exports.__all__
    + _contracts_exports.__all__
    + _data_exports.__all__
    + _models_exports.__all__
    + _overview_exports.__all__
    + _privilege_exports.__all__
))


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    if st.session_state.get("_security_posture_brief_first_version") != 1:
        st.session_state["_security_posture_brief_first_version"] = 1
    if st.session_state.get("exceptions_only_mode") and "security_posture_workflow" not in st.session_state:
        st.session_state["security_posture_workflow"] = SECURITY_OVERVIEW_WORKFLOW
    if st.session_state.get("exceptions_only_mode") and "security_posture_view" not in st.session_state:
        st.session_state["security_posture_view"] = SECURITY_OVERVIEW_WORKFLOW
    current_security_view = SECURITY_VIEW_ALIASES.get(
        str(st.session_state.get("security_posture_view") or ""),
        st.session_state.get("security_posture_view"),
    )
    if current_security_view in SECURITY_POSTURE_VIEWS:
        st.session_state["security_posture_view"] = current_security_view
    if st.session_state.get("security_posture_view") not in SECURITY_POSTURE_VIEWS:
        st.session_state["security_posture_view"] = SECURITY_POSTURE_VIEWS[0]
    _apply_queued_security_workflow()
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="exact",
        scope_note="Company scope uses user/database naming where Snowflake does not expose company routing.",
    )

    days = day_window_selectbox(
        "Security window",
        key="security_posture_brief_days",
        default=30,
    )
    security_labels = {
        SECURITY_OVERVIEW_WORKFLOW: "Overview",
        FAILED_LOGINS_WORKFLOW: "Failed Logins",
        RISKY_GRANTS_WORKFLOW: "Risky Grants",
        PRIVILEGE_SPRAWL_WORKFLOW: "Privilege Sprawl",
        ACCESS_CHANGES_WORKFLOW: "Access Changes",
        DATA_SHARING_EXPOSURE_WORKFLOW: "Data Sharing",
        SECURITY_ALERTS_WORKFLOW: "Security Alerts",
        SECURITY_ADMIN_ADVANCED_WORKFLOW: "Admin",
    }
    active_view = render_primary_section_tabs(
        label="Security Monitoring primary navigation",
        options=SECURITY_POSTURE_VIEWS,
        active_value=st.session_state.get("security_posture_view", SECURITY_OVERVIEW_WORKFLOW),
        key="security_posture_view",
        format_func=lambda value: security_labels.get(str(value), str(value)),
    )
    active_view = SECURITY_VIEW_ALIASES.get(str(active_view or ""), active_view)
    if active_view == RISKY_GRANTS_WORKFLOW:
        render_secondary_lens_pills(
            label="Risky Grants lens",
            options=("Users", "Roles", "Databases", "Schemas", "Future Grants", "Ownership"),
            active_value=st.session_state.get("security_risky_grants_lens", "Users"),
            key="security_risky_grants_lens",
        )
    elif active_view == ACCESS_CHANGES_WORKFLOW:
        render_secondary_lens_pills(
            label="Access Changes lens",
            options=("Recent Grants", "Revokes", "Role Changes", "Admin Changes"),
            active_value=st.session_state.get("security_access_changes_lens", "Recent Grants"),
            key="security_access_changes_lens",
        )
    render_section_breadcrumb(["Security Monitoring", security_labels.get(active_view, active_view)])
    render_content_header(
        security_labels.get(active_view, active_view),
        SECURITY_POSTURE_VIEW_DETAILS.get(active_view, "Security evidence stays behind explicit load actions."),
    )
    _render_security_first_paint_shell(active_view, company, environment, int(days or 30))
    renderer = SECURITY_POSTURE_RENDERERS.get(active_view)
    if renderer is not None:
        renderer(company, environment, days)
        return
    if active_view in WORKFLOW_MODULES:
        st.session_state["security_posture_workflow"] = active_view
        if active_view == FAILED_LOGINS_WORKFLOW:
            st.session_state["security_access_active_view"] = "Login Audit"
        elif active_view == RISKY_GRANTS_WORKFLOW:
            st.session_state["security_access_active_view"] = "Roles & Grants"
        render_workflow_module(active_view, WORKFLOW_MODULES)
        _render_advanced_security_evidence(company, environment)
        return
