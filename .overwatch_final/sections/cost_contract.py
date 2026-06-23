# sections/cost_contract.py - Consolidated cost and contract workflow
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from config import (
    DAY_WINDOW_OPTIONS,
    DEFAULT_COMPANY,
    DEFAULT_ENVIRONMENT,
    DEFAULTS,
    DEFAULT_DAY_WINDOW,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.shell_helpers import (
    _clean_display_text,
    render_data_freshness,
    render_escaped_bold_text,
)
from sections.navigation import apply_section_workflow_navigation
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
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note, defer_source_note


pd = lazy_pandas()

credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_active_environment = _lazy_util("get_active_environment")
get_environment_label = _lazy_util("get_environment_label")
get_session_for_action = _lazy_util("get_session_for_action")
load_shared_service_cost_lens = _lazy_util("load_shared_service_cost_lens")
load_shared_service_cost_trend = _lazy_util("load_shared_service_cost_trend")
render_workflow_selector = _lazy_util("render_workflow_selector")
run_query = _lazy_util("run_query")
run_query_or_raise = _lazy_util("run_query_or_raise")
add_cost_companion_columns = _lazy_util("add_cost_companion_columns")
apply_operator_status_labels = _lazy_util("apply_operator_status_labels")
prioritize_context_columns = _lazy_util("prioritize_context_columns")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _render_cost_watch_floor(company: str, credit_price: float) -> None:
    selected_days = safe_int(
        st.session_state.get("cost_contract_cockpit_window", DEFAULT_DAY_WINDOW),
        DEFAULT_DAY_WINDOW,
    )
    if selected_days not in DAY_WINDOW_OPTIONS:
        selected_days = DEFAULT_DAY_WINDOW

    controls = st.columns([1.0, 1.0, 2.6])
    with controls[0]:
        days = st.selectbox(
            "Cost window",
            DAY_WINDOW_OPTIONS,
            index=DAY_WINDOW_OPTIONS.index(selected_days),
            format_func=lambda d: f"{d} days",
            key="cost_contract_cockpit_window",
        )
    with controls[1]:
        refresh_cost = st.button("Refresh Cost", key="cost_contract_refresh", type="primary", width="stretch")

    if refresh_cost:
        st.session_state.pop(_COST_SPLASH_KEY, None)
        st.session_state.pop(_COST_SPLASH_AUTOLOAD_BLOCKED_SCOPE_KEY, None)
        splash = _ensure_cost_splash(company, int(days), credit_price)
    else:
        splash = _maybe_autoload_cost_splash(company, int(days), credit_price)
    _render_cost_splash(splash, company=company, days=int(days), credit_price=credit_price)

    proof_data = st.session_state.get("cost_contract_cockpit")
    proof_meta = st.session_state.get("cost_contract_cockpit_meta", {})
    proof_current = (
        _looks_like_frame(proof_data)
        and not proof_data.empty
        and proof_meta.get("company") == company
        and proof_meta.get("days") == int(days)
    )
    render_data_freshness(
        proof_meta if proof_current else {},
        source=st.session_state.get("cost_contract_cockpit_source", "Cost detail workspace"),
        target_minutes=60,
        delayed_note="Cost detail uses fast summaries first; full account-history refresh is explicit.",
    )
    if refresh_cost:
        session = get_session_for_action(
            "load the Cost Control Cockpit",
            surface="Cost & Contract",
            offline_note="Cost workflow navigation remains available without a live Snowflake connection.",
        )
        if session is None:
            return
        _refresh_cost_detail_state(st.session_state, session, company, int(days), credit_price)
    defer_section_note(
        "Cost detail telemetry is optional; refresh only when you need account-history rows behind the fast cost summary."
    )

    data = st.session_state.get("cost_contract_cockpit")
    meta = st.session_state.get("cost_contract_cockpit_meta", {})
    err = st.session_state.get("cost_contract_cockpit_error", "")
    if err:
        st.warning(f"Cost cockpit unavailable: {err}")
    loaded_days = meta.get("days")
    data_is_frame = _looks_like_frame(data)
    if (
        data_is_frame
        and not data.empty
        and meta.get("company") == company
        and loaded_days is not None
        and int(loaded_days) != int(days)
    ):
        st.info(
            f"Loaded cockpit data is for {int(loaded_days)} days; selected window is {int(days)} days. "
            "Refresh cost details before acting on detailed telemetry."
        )
    if (
        not data_is_frame
        or data.empty
        or meta.get("company") != company
        or meta.get("days") != int(days)
    ):
        defer_section_note("Specialist cost pages load their own detailed data after the cockpit first move.")
        return

    defer_source_note(st.session_state.get("cost_contract_cockpit_source", "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"))
    if not st.session_state.get(_ADVANCED_COST_DETAIL_VISIBLE_KEY):
        st.caption("Advanced cost detail boards are hidden by default. Open them only when you need reconciliation, source health, or proof detail.")
        if st.button("View Advanced Cost Details", key="cost_contract_view_advanced_details", width="stretch"):
            st.session_state[_ADVANCED_COST_DETAIL_VISIBLE_KEY] = True
            st.rerun()
        return

    row = data.iloc[0]
    queue = st.session_state.get("cost_contract_queue", pd.DataFrame())
    queue_err = st.session_state.get("cost_contract_queue_error", "")
    if queue_err:
        st.caption(f"Action queue unavailable for this role/context: {queue_err}")
    open_actions = high_actions = 0
    total_savings = 0.0
    if isinstance(queue, pd.DataFrame) and not queue.empty and "STATUS" in queue.columns:
        open_mask = ~queue["STATUS"].isin(["Fixed", "Ignored"])
        open_actions = int(open_mask.sum())
        high_actions = int((queue.get("SEVERITY", pd.Series(dtype=str)).isin(["Critical", "High"]) & open_mask).sum())
        if "EST_MONTHLY_SAVINGS" in queue.columns:
            total_savings = safe_float(pd.to_numeric(queue.loc[open_mask, "EST_MONTHLY_SAVINGS"], errors="coerce").fillna(0).sum())
    current_credits = safe_float(row.get("CURRENT_CREDITS", 0))
    prior_credits = safe_float(row.get("PRIOR_CREDITS", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    top_wh = str(row.get("TOP_INCREASE_WAREHOUSE") or "No increase")
    top_delta = safe_float(row.get("TOP_INCREASE_CREDITS", 0))
    top_delta_usd = credits_to_dollars(top_delta, credit_price)
    top_delta_usd_label = f"{'+' if top_delta_usd >= 0 else '-'}${abs(top_delta_usd):,.0f}"
    cortex_projected, cortex_exception_count = _loaded_cortex_state()
    secondary_metrics = []
    if total_savings > 0:
        secondary_metrics.append({"label": "Savings Queue", "value": f"${total_savings:,.0f}/mo"})
    if cortex_projected > 0 or cortex_exception_count > 0:
        secondary_metrics.append({
            "label": "Cortex Projection",
            "value": f"${cortex_projected:,.0f}/30d",
            "delta": f"{cortex_exception_count:,} exceptions",
            "delta_color": "inverse",
        })
    if secondary_metrics:
        with st.expander("Secondary cockpit metrics", expanded=False):
            _render_metric_items(secondary_metrics)
            if open_actions or high_actions:
                st.caption(f"{open_actions:,} open cost action(s), {high_actions:,} high priority.")
            st.caption(f"Top warehouse increase: {top_wh} ({top_delta:+,.2f} credits / {top_delta_usd_label}).")

    run_rate_source = st.session_state.get("cost_contract_run_rate_source", "")
    if run_rate_source:
        defer_source_note(run_rate_source)
    _render_cost_run_rate_lens(
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        credit_price,
        st.session_state.get("cost_contract_run_rate_error", ""),
    )
    _render_cost_period_explanation(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        credit_price,
    )
    _render_cost_source_health(
        cockpit=data,
        run_rate=st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue=queue,
        attribution=st.session_state.get("cost_contract_attribution_reconciliation", pd.DataFrame()),
        service_lens=st.session_state.get("cost_contract_service_lens", pd.DataFrame()),
    )
    _render_query_attribution_gap(
        st.session_state.get("cost_contract_attribution_reconciliation", pd.DataFrame()),
        credit_price,
        st.session_state.get("cost_contract_attribution_error", ""),
    )
    _render_account_service_cost_lens(
        st.session_state.get("cost_contract_service_lens", pd.DataFrame()),
        credit_price,
        st.session_state.get("cost_contract_service_lens_error", ""),
    )
    _render_cost_advisor_board(
        efficiency_summary=st.session_state.get("cost_contract_efficiency_summary", pd.DataFrame()),
        warehouse_efficiency=st.session_state.get("cost_contract_warehouse_efficiency", pd.DataFrame()),
        clustering_cost=st.session_state.get("cost_contract_clustering_cost", pd.DataFrame()),
        reconciliation=st.session_state.get("cost_contract_attribution_reconciliation", pd.DataFrame()),
        service_lens=st.session_state.get("cost_contract_service_lens", pd.DataFrame()),
        credit_price=credit_price,
        days=int(days),
        storage_table_metrics=st.session_state.get("stor_df_table_metrics", pd.DataFrame()),
        storage_db_detail=st.session_state.get("stor_df_db_detail", pd.DataFrame()),
        storage_cost_per_tb=st.session_state.get("storage_cost_per_tb", DEFAULTS.get("storage_cost_per_tb", 23.0)),
    )
    _render_cost_efficiency_rca(
        st.session_state.get("cost_contract_efficiency_summary", pd.DataFrame()),
        st.session_state.get("cost_contract_warehouse_efficiency", pd.DataFrame()),
        st.session_state.get("cost_contract_clustering_cost", pd.DataFrame()),
        credit_price,
        errors={
            "Efficiency summary": st.session_state.get("cost_contract_efficiency_summary_error", ""),
            "Warehouse efficiency": st.session_state.get("cost_contract_warehouse_efficiency_error", ""),
            "Clustering cost": st.session_state.get("cost_contract_clustering_cost_error", ""),
        },
    )
    _render_cost_spike_root_cause_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        credit_price,
    )
    _render_change_cost_correlation_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
    )
    _render_cost_monitoring_mart_and_incident_timeline(
        company=company,
        cockpit=data,
        run_rate=st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue=queue,
    )
    _render_savings_closure_control(queue, credit_price)
    _render_cost_control_coverage_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )
    _render_cost_allocation_trust_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )
    _render_cost_drilldown_command_map(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )
    _render_cost_decomposition_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )

    moves = []
    if delta_pct >= 20 or safe_float(row.get("TOP_INCREASE_CREDITS", 0)) > 0:
        moves.append((
            "Explain the usage movement",
            f"Top increase: {row.get('TOP_INCREASE_WAREHOUSE', 'unknown')} "
            f"({safe_float(row.get('TOP_INCREASE_CREDITS', 0)):,.2f} credits).",
            "Cost by Warehouse",
        ))
    if high_actions > 0 or total_savings > 0:
        moves.append((
            "Work the action queue",
            f"{high_actions:,} high-priority action(s), ${total_savings:,.0f}/month potential savings.",
            "Cost Recommendations",
        ))
    if cortex_exception_count > 0 or cortex_projected > 0:
        moves.append((
            "Inspect AI / Cortex spend",
            f"Projected Cortex spend ${cortex_projected:,.0f}/30d with {cortex_exception_count:,} exception(s).",
            "Cost by User / Role",
        ))
    if not moves:
        moves.append((
            "Review attribution and queue",
            "No dominant cost incident in this cockpit window. Review attribution or open recommendations.",
            "Cost Recommendations",
        ))

    st.markdown("**Next Cost Moves**")
    cols = st.columns(min(len(moves), 3))
    for idx, (title, evidence, workflow) in enumerate(moves[:3]):
        with cols[idx]:
            render_escaped_bold_text(title)
            st.caption(_clean_display_text(evidence))
            if st.button(f"Open {workflow}", key=f"cost_contract_next_{idx}_{workflow}", width="stretch"):
                st.session_state["cost_contract_workflow"] = workflow
                st.rerun()


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
        columns=5,
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
