# sections/cost_contract.py - Cost & Contract public workflow entrypoint.
from __future__ import annotations

import streamlit as st

from config import DEFAULT_COMPANY
from sections.base import lazy_util as _lazy_util
from sections.cost_contract_contracts import (
    ADVANCED_COST_TOOL_DETAILS,
    ADVANCED_COST_TOOL_MODULES,
    COST_WORKFLOW_PRESETS,
    LEGACY_COST_ADVANCED_TOOL_ALIASES,
    LEGACY_COST_INNER_VIEW_ALIASES,
    LEGACY_COST_WORKFLOW_ALIASES,
    WORKFLOW_DETAILS,
    WORKFLOW_MODULES,
    WORKFLOWS,
    _ADVANCED_COST_DETAIL_VISIBLE_KEY,
    _ADVANCED_COST_TOOLS_VISIBLE_KEY,
    _COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY,
    _COST_SPLASH_KEY,
    _DETAIL_WORKFLOW_KEY,
    _LAST_COST_WORKFLOW_KEY,
    _PENDING_DETAIL_WORKFLOW_KEY,
    _PRESERVE_COST_CENTER_VIEW_KEY,
    build_cost_monitoring_mart_sql,
)
from sections.cost_contract_dataframes import (
    _cost_column,
    _cost_metric_column,
    _cost_metric_to_usd,
    _cost_spend_trend_rows,
    _cost_warehouse_ranking_rows,
    _has_columns,
    _loaded_rows,
    _looks_like_frame,
    _service_lens_movement_rows,
    _short_label,
    _slide_money,
    _top_loaded_cost_driver,
)
from sections.cost_contract_advisor import (
    _COST_ADVISOR_ACTION_MAP,
    _build_attribution_gap_summary,
    _build_cost_advisor_board,
    _build_cost_closure_analytics,
    _cost_action_mask,
    _cost_advisor_action_for,
    _cost_advisor_action_summary,
    _cost_advisor_add_row,
    _cost_advisor_category_summary,
    _cost_advisor_detail_options,
    _cost_advisor_priority,
    _decorate_cost_advisor_board,
    _open_cost_action_frame,
    _queue_series,
    _text_present,
)
from sections.cost_contract_helpers import get_credit_price, get_current_ai_credit_price
from sections.cost_contract_charts import (
    _altair,
    _cost_chart_palette,
    _finalize_cost_chart,
    _render_cost_advisor_category_chart,
    _render_cost_chart_with_data_toggle,
    _render_service_cost_movement_chart,
    _render_spend_trend_chart,
    _render_warehouse_ranking_chart,
)
from sections.cost_contract_overview import (
    _cost_executive_decision_stack,
    _cost_splash_next_move,
    _cost_splash_status,
)
from sections.cost_contract_overview_panels import (
    _build_cost_period_explanation,
    _cost_snapshot_action_summary,
    _format_optional_pct,
    _nullable_float,
    _render_cost_executive_decision_stack,
    _render_cost_period_explanation,
    _render_cost_run_rate_lens,
    _render_cost_splash_narrative,
    _render_cost_splash_next_move,
    _render_metric_items,
)
from sections.cost_contract_advisor_panels import (
    _render_account_service_cost_lens,
    _render_cost_advisor_board,
    _render_cost_advisor_detail,
    _render_cost_efficiency_rca,
    _render_savings_closure_control,
)
from sections.cost_contract_alert_context import _render_loaded_cost_alert_context
from sections.cost_contract_evidence_panels import (
    _render_change_cost_correlation_board,
    _render_cost_change_correlation,
    _render_cost_command_findings,
    _render_cost_efficiency_score_explanation,
    _render_cost_forecast_detail,
    _render_cost_spike_root_cause_board,
    _render_executive_value_ledger,
    _render_savings_verification_workflow,
)
from sections.cost_contract_loader import _refresh_cost_detail_state
from sections.cost_contract_monitoring import (
    _build_cost_incident_timeline,
    _build_cost_monitoring_alert_rows,
    _build_cost_monitoring_mart_operability,
    _cost_alert_message,
    _render_cost_monitoring_mart_and_incident_timeline,
)
from sections.cost_contract_intelligence import (
    _add_coverage_row,
    _add_source_health_row,
    _build_change_cost_correlation_board,
    _build_cost_allocation_trust_board,
    _build_cost_control_coverage_board,
    _build_cost_decomposition_board,
    _build_cost_drilldown_command_map,
    _build_cost_source_health_board,
    _build_cost_spike_root_cause_board,
    _build_service_cost_lens_summary,
    _cost_command_severity_rank,
    _first_frame_value,
    _loaded_cortex_state,
    _source_state,
    _state_frame,
)
from sections.cost_contract_panels import (
    _render_cost_allocation_trust_board,
    _render_cost_control_coverage_board,
    _render_cost_decomposition_board,
    _render_cost_drilldown_command_map,
    _render_cost_source_health,
    _render_query_attribution_gap,
)
from sections.cost_contract_sql import (
    _build_cost_cockpit_sql,
    _build_cost_monitor_service_trend_sql,
    _build_cost_run_rate_sql,
    _build_cost_splash_cortex_sql,
    _build_cost_splash_daily_trend_sql,
    _build_cost_splash_warehouse_delta_sql,
    _build_resource_monitor_guardrail_sql,
    _cortex_daily_table,
    _warehouse_hourly_table,
)
from sections.cost_contract_splash import (
    _cached_cost_splash,
    _cost_command_lanes,
    _cost_splash_meta,
    _cost_splash_summary,
    _empty_cost_splash,
    _ensure_cost_splash,
    _load_cost_splash_live_query,
    _load_cost_splash_query,
    _maybe_autoload_cost_splash,
    _render_cost_load_contract,
    _render_cost_splash,
    _slide_number,
)
from sections.cost_contract_rendering import (
    _compact_time,
    _freshness_note,
    _metric_confidence_label,
    render_operator_briefing,
    render_signal_confidence,
    render_workflow_module,
)
from sections.cost_contract_workflow import (
    _apply_cost_workflow_preset,
    _normalize_cost_contract_workflow_state,
    _render_advanced_cost_tools,
    _render_cost_contract_workflow,
    _render_cost_filter_indicator,
    set_cost_overview_renderer,
)
from sections.cost_contract_overview_floor import _render_cost_watch_floor


get_active_environment = _lazy_util("get_active_environment")
render_workflow_selector = _lazy_util("render_workflow_selector")


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


set_cost_overview_renderer(_render_cost_watch_floor)


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    _normalize_cost_contract_workflow_state()
    if st.session_state.get("cost_contract_workflow") not in WORKFLOWS:
        st.session_state["cost_contract_workflow"] = "Cost Overview"
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="allocated",
        scope_note="Warehouse totals are exact; user/query chargeback is allocated unless noted.",
    )
    _render_cost_filter_indicator()

    workflow = render_workflow_selector(
        "Cost workflow",
        "cost_contract_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
        columns=3,
        compact_details=True,
        collapse_after=3,
        collapsed_label="More cost workflows",
    )

    routed_workflow = st.session_state.pop(_PENDING_DETAIL_WORKFLOW_KEY, None)
    legacy_detail_workflow = st.session_state.pop(_DETAIL_WORKFLOW_KEY, None)
    for raw_workflow in (routed_workflow, legacy_detail_workflow):
        advanced_tool = LEGACY_COST_ADVANCED_TOOL_ALIASES.get(str(raw_workflow or ""))
        if advanced_tool:
            st.session_state["cost_contract_advanced_tool"] = advanced_tool
            st.session_state[_ADVANCED_COST_TOOLS_VISIBLE_KEY] = True
        inner_aliases = LEGACY_COST_INNER_VIEW_ALIASES.get(str(raw_workflow or ""), {})
        for key, value in inner_aliases.items():
            st.session_state[key] = value
        if "cost_center_view" in inner_aliases:
            st.session_state[_PRESERVE_COST_CENTER_VIEW_KEY] = True
    routed_workflow = LEGACY_COST_WORKFLOW_ALIASES.get(str(routed_workflow or ""), routed_workflow)
    legacy_detail_workflow = LEGACY_COST_WORKFLOW_ALIASES.get(str(legacy_detail_workflow or ""), legacy_detail_workflow)
    routed_workflow = routed_workflow if routed_workflow in WORKFLOWS else legacy_detail_workflow
    if routed_workflow in WORKFLOWS and routed_workflow != workflow:
        st.session_state["cost_contract_workflow"] = routed_workflow
        st.rerun()

    _render_cost_contract_workflow(workflow, company, environment)

    advanced_open = bool(st.session_state.get(_ADVANCED_COST_TOOLS_VISIBLE_KEY))
    with st.expander("Advanced cost tools and evidence", expanded=advanced_open):
        if st.button("Open Advanced Cost Tools", key="cost_contract_open_advanced_tools", width="stretch"):
            st.session_state[_ADVANCED_COST_TOOLS_VISIBLE_KEY] = True
            st.rerun()
        if st.session_state.get(_ADVANCED_COST_TOOLS_VISIBLE_KEY):
            _render_advanced_cost_tools(company, environment)
        _render_loaded_cost_alert_context()
        render_operator_briefing(
            [
                ("First move", "Explain why spend changed before tuning anything."),
                ("Telemetry", "Reconcile warehouse metering, chargeback allocation, Cortex, and run-rate pace."),
                ("Control", "Convert findings into routed actions with savings and status."),
                ("Output", "Produce a DBA-ready usage narrative with the source and action route attached."),
            ],
            columns=4,
        )
        _render_executive_value_ledger(company, environment)
        _render_cost_efficiency_score_explanation(company, environment)
        _render_cost_forecast_detail(company, environment)
        _render_cost_change_correlation(company, environment)
        _render_savings_verification_workflow(company, environment)
        _render_cost_command_findings(company, environment)
