# sections/warehouse_health.py - Public Warehouse Health workflow shell.
from __future__ import annotations

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULTS, DEFAULT_ENVIRONMENT
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.warehouse_health_actions import (
    _annotate_warehouse_admin_readiness,
    _build_warehouse_cost_control_posture,
    _build_warehouse_guardrail_coverage,
    _route_label,
    _warehouse_approval_for,
    _warehouse_capacity_priority_view,
    _warehouse_capacity_review_sql,
    _warehouse_intervention_matrix,
    _warehouse_owner_context,
    _warehouse_setting_action_plan,
    _warehouse_setting_audit_readiness_for_row,
    _warehouse_setting_candidate_for,
    _warehouse_setting_control_board,
    _warehouse_setting_detail_options,
    _warehouse_setting_review_insert_sql,
    _warehouse_setting_route,
)
from sections.warehouse_health_capacity import (
    _build_warehouse_capacity_markdown,
    _build_warehouse_capacity_sql,
    _render_warehouse_watch_floor,
    _warehouse_sql_exprs,
)
from sections.warehouse_health_contracts import (
    WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION,
    WAREHOUSE_HEALTH_BRIEF_WORKFLOWS,
    WAREHOUSE_HEALTH_DETAILS,
    WAREHOUSE_HEALTH_FAST_ENTRY_VERSION,
    WAREHOUSE_HEALTH_VIEWS,
    WAREHOUSE_OPERABILITY_FACT_TABLE,
    WAREHOUSE_SCOPE_FILTER_KEYS,
    WAREHOUSE_SETTING_REVIEW_TABLE,
)
from sections.warehouse_health_dataframes import (
    _frame_row_count,
    _scope_value,
    _source_confidence,
    _source_next_action,
    _warehouse_column_sum,
    _warehouse_frame_has_rows,
    _warehouse_frame_sum,
    _warehouse_looks_like_frame,
    _warehouse_meta_matches,
    _warehouse_operator_next_moves,
    _warehouse_overview_exceptions,
    _warehouse_period_movement,
    _warehouse_scope_meta,
    _warehouse_state_count,
    _warehouse_source_health_rows,
)
from sections.warehouse_health_helpers import (
    _warehouse_capacity_action_for,
    _warehouse_capacity_score,
    _warehouse_capacity_workflow_for,
)
from sections.warehouse_health_loader import _warehouse_action_session
from sections.warehouse_health_overview_panels import (
    _apply_queued_warehouse_health_view,
    _apply_warehouse_brief_first_default,
    _queue_warehouse_health_view,
    _render_warehouse_action_brief,
    _render_warehouse_brief_launchpad,
    _render_warehouse_operating_snapshot,
    _warehouse_action_brief,
    _warehouse_brief_workflow_rows,
    _warehouse_operating_snapshot,
    _warehouse_support_panels_have_state,
)
from sections.warehouse_health_panels import (
    _apply_warehouse_fast_entry_default,
    _render_capacity_brief,
    _render_warehouse_overview_exception_strip,
    _render_warehouse_source_health,
)
from sections.warehouse_health_queue import (
    _queue_capacity_findings,
    _queue_efficiency_findings,
)
from sections.warehouse_health_rendering import render_operator_briefing
from sections.warehouse_health_setting_panels import (
    _render_warehouse_cost_control_posture,
    _render_warehouse_setting_action_detail,
    _save_warehouse_setting_review_snapshot,
)
from sections.warehouse_health_sql import (
    _admin_audit_fqn,
    _overwatch_dedicated_warehouse_setup_sql,
    _warehouse_action_queue_closure_sql,
    _warehouse_capacity_verification_sql,
    _warehouse_cost_control_review_sql,
    _warehouse_operability_fact_sql,
    _warehouse_setting_execution_audit_sql,
    _warehouse_setting_review_history_sql,
    _warehouse_setting_review_sql,
    _warehouse_sql_identifier,
    build_warehouse_operability_fact_ddl,
    build_warehouse_operability_fact_migration_sql,
    build_warehouse_setting_review_ddl,
    build_warehouse_setting_review_migration_sql,
    warehouse_operability_fact_fqn,
    warehouse_setting_review_fqn,
)
from sections.warehouse_health_view_advisor import _render_warehouse_advisor_view
from sections.warehouse_health_view_efficiency import _render_warehouse_efficiency_view
from sections.warehouse_health_view_heatmap import _render_warehouse_heatmap_view
from sections.warehouse_health_view_overview import _load_warehouse_overview, _render_warehouse_overview_view
from sections.warehouse_health_view_spill import _render_warehouse_spill_view
from utils.primitives import safe_int


pd = lazy_pandas()

get_session_for_action = _lazy_util("get_session_for_action")
make_action_id = _lazy_util("make_action_id")
upsert_actions = _lazy_util("upsert_actions")
render_workflow_selector = _lazy_util("render_workflow_selector")


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def _render_selected_warehouse_health_view(
    warehouse_view: str,
    company: str,
    environment: str,
    *,
    global_warehouse: str = "",
    global_user: str = "",
    global_role: str = "",
    global_database: str = "",
    global_start_date=None,
    global_end_date=None,
) -> None:
    if warehouse_view == "Overview & Scaling":
        _render_warehouse_overview_view(company, environment)
    elif warehouse_view == "Efficiency":
        _render_warehouse_efficiency_view(company, environment)
    elif warehouse_view == "Spill & Memory":
        _render_warehouse_spill_view(company, environment)
    elif warehouse_view == "Workload Heatmap":
        _render_warehouse_heatmap_view(
            company,
            environment,
            global_warehouse=global_warehouse,
            global_user=global_user,
            global_role=global_role,
            global_database=global_database,
            global_start_date=global_start_date,
            global_end_date=global_end_date,
        )
    elif warehouse_view == "Optimization Advisor":
        _render_warehouse_advisor_view()


def render():
    st.session_state.get("credit_price", DEFAULTS["credit_price"])
    company = get_active_company()
    environment = get_active_environment()
    _apply_warehouse_fast_entry_default()
    _apply_warehouse_brief_first_default()
    _apply_queued_warehouse_health_view()
    global_warehouse = str(st.session_state.get("global_warehouse", "") or "").strip()
    global_user = str(st.session_state.get("global_user", "") or "").strip()
    global_role = str(st.session_state.get("global_role", "") or "").strip()
    global_database = str(st.session_state.get("global_database", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")

    selected_days = safe_int(st.session_state.get("wh_days", 7), 7) or 7
    if selected_days < 1 or selected_days > 30:
        selected_days = 7
    _render_warehouse_action_brief(_warehouse_action_brief(company, environment, selected_days))
    _render_warehouse_operating_snapshot(_warehouse_operating_snapshot(company, environment, selected_days))

    render_operator_briefing(
        [
            ("First move", "Decide whether pressure is queue, spill, latency, or cost drift."),
            ("Telemetry", "Use metering plus query history before changing size or clusters."),
            ("Control", "Tune routing, auto-suspend, QAS, size, or multi-cluster with measured context."),
            ("Output", "Create a warehouse capacity brief for release or cost review."),
        ],
        columns=4,
    )
    warehouse_view = render_workflow_selector(
        "Warehouse capacity workflow",
        "warehouse_health_view",
        WAREHOUSE_HEALTH_VIEWS,
        WAREHOUSE_HEALTH_DETAILS,
        columns=3,
    )
    if warehouse_view == "Overview & Scaling" and not _warehouse_frame_has_rows(st.session_state.get("wh_df_wh")):
        _render_warehouse_brief_launchpad()
    show_support_panels = bool(st.session_state.get("warehouse_health_support_panels_open"))
    if show_support_panels:
        if st.button("Hide Detail Panels", key="warehouse_health_hide_support_panels"):
            st.session_state["warehouse_health_support_panels_open"] = False
            st.rerun()
        _render_capacity_brief(company, environment)
        _render_warehouse_source_health(company, environment)
    elif st.button("Detail Panels", key="warehouse_health_open_support_panels"):
        st.session_state["warehouse_health_support_panels_open"] = True
        st.rerun()
    if st.session_state.get("exceptions_only_mode") and warehouse_view != "Overview & Scaling":
        return

    _render_selected_warehouse_health_view(
        warehouse_view,
        company,
        environment,
        global_warehouse=global_warehouse,
        global_user=global_user,
        global_role=global_role,
        global_database=global_database,
        global_start_date=global_start_date,
        global_end_date=global_end_date,
    )
