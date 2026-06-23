# sections/cost_contract.py - Consolidated cost and contract workflow
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st
from importlib import import_module

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
    render_escaped_labeled_text,
    render_shell_snapshot,
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
    _COST_SPLASH_AUTOLOAD_SCOPE_KEY,
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
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note, defer_source_note


pd = lazy_pandas()

credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_active_environment = _lazy_util("get_active_environment")
get_environment_label = _lazy_util("get_environment_label")
get_session_for_action = _lazy_util("get_session_for_action")
load_action_queue = _lazy_util("load_action_queue")
load_change_correlation_detail = _lazy_util("load_change_correlation_detail")
load_closed_loop_verification_detail = _lazy_util("load_closed_loop_verification_detail")
load_command_center_finding_detail = _lazy_util("load_command_center_finding_detail")
load_command_center_recommendation_detail = _lazy_util("load_command_center_recommendation_detail")
load_executive_scorecard_detail = _lazy_util("load_executive_scorecard_detail")
load_forecast_detail = _lazy_util("load_forecast_detail")
load_value_ledger_detail = _lazy_util("load_value_ledger_detail")
load_value_ledger_rollup = _lazy_util("load_value_ledger_rollup")
load_shared_service_cost_lens = _lazy_util("load_shared_service_cost_lens")
load_shared_service_cost_trend = _lazy_util("load_shared_service_cost_trend")
render_workflow_selector = _lazy_util("render_workflow_selector")
run_query = _lazy_util("run_query")
run_query_or_raise = _lazy_util("run_query_or_raise")
add_cost_companion_columns = _lazy_util("add_cost_companion_columns")
apply_operator_status_labels = _lazy_util("apply_operator_status_labels")
prioritize_context_columns = _lazy_util("prioritize_context_columns")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
build_loaded_section_alert_signal_board = _lazy_util("build_loaded_section_alert_signal_board")
build_cost_cortex_alert_drilldown = _lazy_util("build_cost_cortex_alert_drilldown")
alert_delivery_status_for_target = _lazy_util("alert_delivery_status_for_target")
alert_recipient_label = _lazy_util("alert_recipient_label")


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _freshness_note(source: str) -> str:
    source_key = str(source or "").lower()
    if "information_schema" in source_key or source_key in {"live", "is"}:
        return "Freshness: live INFORMATION_SCHEMA view"
    if "organization_usage" in source_key:
        return "Freshness: ORGANIZATION_USAGE can lag several hours"
    if "account_usage" in source_key or "warehouse_metering_history" in source_key:
        return "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes"
    if "mart" in source_key or "overwatch" in source_key:
        return "Freshness: fast summary refresh cadence"
    return "Freshness: depends on source view availability"


def _metric_confidence_label(kind: str) -> str:
    labels = {
        "exact": "Measurement: Exact",
        "allocated": "Measurement: Allocated from warehouse metering",
        "estimated": "Measurement: Estimated",
        "forecast": "Measurement: Forecast from recent observed burn",
        "projection": "Measurement: Projection from recent observed burn",
    }
    return labels.get(str(kind or "").lower(), "Measurement depends on available account metadata")


def render_signal_confidence(*, source: str = "ACCOUNT_USAGE", confidence: str = "allocated", scope_note: str = "") -> None:
    parts = [_freshness_note(source), _metric_confidence_label(confidence)]
    if scope_note:
        parts.append(scope_note)
    defer_source_note(*parts)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


def render_workflow_module(workflow: str, workflow_modules: dict[str, str]) -> None:
    module_name = workflow_modules.get(str(workflow))
    if not module_name:
        st.warning(f"No module registered for workflow: {workflow}")
        return
    module = import_module(module_name)
    render = getattr(module, "render", None)
    if not callable(render):
        st.warning(f"Workflow module has no render() function: {module_name}")
        return
    render()

def _compact_time(value: object, default: str = "Not seen") -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"NAT", "NAN", "NONE", "NULL", "<NA>"}:
        return default
    return text[:19]


def _render_cost_spike_root_cause_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    credit_price: float,
) -> None:
    summary, board = _build_cost_spike_root_cause_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        credit_price=credit_price,
    )
    st.session_state["cost_contract_spike_root_cause_summary"] = summary
    st.session_state["cost_contract_spike_root_cause"] = board
    if board.empty:
        return
    st.markdown("**Cost Spike Root Cause Drilldown**")
    value_at_risk = safe_float(pd.to_numeric(board.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    render_shell_snapshot((
        ("Critical/High", f"{summary['critical_high']:,}"),
        ("Value at Risk", f"${value_at_risk:,.0f}"),
        ("Top Driver", summary["top_driver"]),
    ))
    render_priority_dataframe(
        board.rename(columns={"CONFIDENCE": "MEASUREMENT_BASIS"}),
        title="Cost root-cause candidates ranked by risk and value",
        priority_columns=[
            "SEVERITY", "DRIVER", "ENTITY", "ROOT_CAUSE_SIGNAL", "VALUE_AT_RISK_USD",
            "MEASUREMENT_BASIS", "TRUST", "EVIDENCE", "NEXT_ACTION", "PROOF_REQUIRED", "ROUTE",
        ],
        sort_by=["SEVERITY", "VALUE_AT_RISK_USD"],
        ascending=[True, False],
        raw_label="All cost root-cause candidate rows",
        height=340,
        max_rows=8,
    )


def _render_change_cost_correlation_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
) -> None:
    summary, board = _build_change_cost_correlation_board(
        cockpit=cockpit,
        run_rate=run_rate,
    )
    st.session_state["cost_contract_change_cost_summary"] = summary
    st.session_state["cost_contract_change_cost_correlation"] = board
    if board.empty:
        return
    st.markdown("**Change + Cost Correlation**")
    render_shell_snapshot((
        ("High", f"{summary['high']:,}"),
        ("Medium", f"{summary['medium']:,}"),
        ("Top Correlation", summary["top_correlation"]),
    ))
    render_priority_dataframe(
        board,
        title="Recent changes that may explain cost movement",
        priority_columns=[
            "SEVERITY", "CORRELATION", "ENTITY", "COST_SIGNAL", "CHANGE_SIGNAL",
            "EVIDENCE", "NEXT_ACTION", "PROOF_REQUIRED", "ROUTE",
        ],
        sort_by=["SEVERITY", "CORRELATION"],
        ascending=[True, True],
        raw_label="All change and cost correlation rows",
        height=300,
        max_rows=8,
    )


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


def _render_loaded_cost_alert_context() -> None:
    board = build_loaded_section_alert_signal_board(st.session_state, section="Cost & Contract", limit=8)
    if board.empty:
        return
    alert_data = st.session_state.get("alert_center_data", {}) if isinstance(st.session_state.get("alert_center_data"), dict) else {}
    drilldown = build_cost_cortex_alert_drilldown(
        alert_data.get("alerts", pd.DataFrame()),
        alert_data.get("action_queue", pd.DataFrame()),
        limit=8,
    )
    focus = board.get("SECTION_FOCUS", pd.Series(dtype=str)).fillna("").astype(str)
    severity = board.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str)
    sla = board.get("SLA_STATE", pd.Series(dtype=str)).fillna("").astype(str)
    st.markdown("**Loaded Cost and Cortex Alerts**")
    render_shell_snapshot((
        ("Signals", f"{len(board):,}"),
        ("Cortex / Spend", f"{int(focus.isin(['Cortex spend', 'Spend spike', 'Cost movement']).sum()):,}"),
        ("Critical / High", f"{int(severity.isin(['Critical', 'High']).sum()):,}"),
        ("Breached", f"{int(sla.isin(['Breached', 'Overdue']).sum()):,}"),
    ))
    render_priority_dataframe(
        board,
        title="Loaded cost and Cortex alert context",
        priority_columns=[
            "SECTION_FOCUS", "SEVERITY", "SLA_STATE", "CATEGORY", "SIGNAL",
            "ENTITY", "OWNER", "FIRST_RESPONSE", "RECOMMENDED_ACTION",
            "IMPACT_ESTIMATE", "OPEN_PATH", "DRILLDOWN_HINT",
            "AUTOMATION_READINESS", "QUEUE_STATE", "TICKET_ID",
        ],
        sort_by=["PRIORITY"],
        ascending=True,
        raw_label="All loaded cost/Cortex alert rows",
        height=260,
        max_rows=6,
    )
    if not drilldown.empty:
        render_priority_dataframe(
            drilldown,
            title="Cost and Cortex alert drilldown",
            priority_columns=[
                "FOCUS", "SEVERITY", "ENTITY", "WHY_THIS_FIRED",
                "WHERE_TO_OPEN", "SAFE_ACTION", "AUTOMATION_BOUNDARY",
            ],
            raw_label="All cost and Cortex alert drilldown rows",
            height=260,
            max_rows=6,
        )
    top = board.iloc[0]
    button_cols = st.columns(2)
    with button_cols[0]:
        if st.button("Open Alert Lane", key="cost_alert_open_alert_lane", width="stretch"):
            apply_section_workflow_navigation(
                "Alert Center",
                alert_center_view=str(top.get("ALERT_CENTER_VIEW") or "Cost Alerts"),
            )
            st.rerun()
    with button_cols[1]:
        if st.button("Open Cost Drilldown", key="cost_alert_open_cost_drilldown", width="stretch"):
            apply_section_workflow_navigation(
                str(top.get("DESTINATION_SECTION") or "Cost & Contract"),
                workflow=str(top.get("DESTINATION_WORKFLOW") or "Cost by Warehouse"),
            )
            st.rerun()
    defer_source_note("Loaded Cost and Cortex Alerts reuse Alert Center data and do not run a separate Snowflake query.")


def _render_executive_value_ledger(company: str, environment: str) -> None:
    rollup = load_value_ledger_rollup(company, environment, days=35)
    if rollup is None or getattr(rollup, "empty", True):
        st.caption("Executive Value Ledger is pending. Refresh the enterprise operating model mart to separate verified value from estimates.")
    else:
        expected = safe_float(pd.to_numeric(rollup.get("EXPECTED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        verified = safe_float(pd.to_numeric(rollup.get("VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        unverified = safe_float(pd.to_numeric(rollup.get("UNVERIFIED_ESTIMATE_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        open_items = safe_int(pd.to_numeric(rollup.get("OPEN_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        st.markdown("**Executive Value Ledger**")
        render_shell_snapshot((
            ("Verified Savings", f"${verified:,.0f}"),
            ("Expected Savings", f"${expected:,.0f}"),
            ("Unverified", f"${unverified:,.0f}"),
            ("Open Items", f"{open_items:,}"),
        ))
        st.caption("Only verified telemetry is counted as realized savings; estimates remain open value until the verification window closes.")
        st.dataframe(
            rollup[[
                column for column in [
                    "STATUS", "OWNER_ROUTE", "EXPECTED_SAVINGS_USD",
                    "VERIFIED_SAVINGS_USD", "UNVERIFIED_ESTIMATE_USD",
                    "CONFIDENCE", "VALUE_STATE", "OPEN_ITEMS",
                    "VERIFIED_ITEMS", "NEXT_ACTION",
                ]
                if column in rollup.columns
            ]],
            width="stretch",
            hide_index=True,
        )

    if st.button("Load Value Ledger Detail", key="cost_contract_load_value_ledger_detail", width="stretch"):
        st.session_state["cost_contract_value_ledger_detail"] = load_value_ledger_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["cost_contract_value_ledger_scope"] = (company, environment)

    detail = st.session_state.get("cost_contract_value_ledger_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("cost_contract_value_ledger_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No detailed value-ledger rows are available for this scope yet.")
        else:
            st.dataframe(
                detail[[
                    column for column in [
                        "SOURCE", "ITEM_ID", "FINDING", "ENTITY_TYPE", "ENTITY_NAME",
                        "ROUTE", "STATUS", "EXPECTED_SAVINGS_USD",
                        "ACTUAL_VERIFIED_SAVINGS_USD", "UNVERIFIED_ESTIMATE_USD",
                        "CONFIDENCE", "TRUST_LEVEL", "BUSINESS_IMPACT",
                        "ACTION_TAKEN", "SUPPORTING_SIGNAL",
                        "VERIFICATION_WINDOW_START", "VERIFICATION_WINDOW_END",
                        "VERIFIED_BY", "VERIFIED_AT", "ROLLBACK_NOTES",
                    ]
                    if column in detail.columns
                ]],
                width="stretch",
                hide_index=True,
            )


def _render_cost_efficiency_score_explanation(company: str, environment: str) -> None:
    """Expose Cost Efficiency Score drivers behind an explicit Load action."""
    st.markdown("**Cost Efficiency Score**")
    st.caption("Loads score drivers from the Executive Scorecard history. Estimates do not count as realized savings.")
    if st.button("Load Cost Efficiency Score Drivers", key="cost_contract_load_cost_score_drivers", width="stretch"):
        st.session_state["cost_contract_cost_score_detail"] = load_executive_scorecard_detail(
            company,
            environment,
            score_key="COST_EFFICIENCY",
            days=180,
        )
        st.session_state["cost_contract_cost_score_scope"] = (company, environment)

    detail = st.session_state.get("cost_contract_cost_score_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("cost_contract_cost_score_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No Cost Efficiency Score driver rows are available for this scope yet.")
            return
        latest = detail.iloc[0]
        render_shell_snapshot((
            ("Score", f"{safe_float(latest.get('CURRENT_SCORE')):.0f}/100"),
            ("Status", str(latest.get("STATUS") or "Unknown")),
            ("Trend", str(latest.get("TREND") or "Stable")),
            ("Value/Risk", f"${safe_float(latest.get('VALUE_AT_RISK_USD')):,.0f}"),
        ))
        render_priority_dataframe(
            detail,
            title="Cost Efficiency Score drivers",
            priority_columns=[
                "SNAPSHOT_TS", "CURRENT_SCORE", "STATUS", "TREND", "TOP_DRIVER",
                "RECOMMENDED_ACTION", "OWNER_ROUTE", "VALUE_AT_RISK_USD",
                "CONFIDENCE", "SOURCE_OBJECTS", "LAST_REFRESHED_TS",
            ],
            sort_by=["SNAPSHOT_TS"],
            ascending=False,
            raw_label="All cost efficiency score history rows",
            height=260,
            max_rows=8,
        )


def _render_cost_forecast_detail(company: str, environment: str) -> None:
    """Expose Phase 2C cost forecasting evidence only behind Load."""
    st.markdown("**Cost Forecast Drivers**")
    st.caption("Loads forecast history from OVERWATCH_FORECAST_HISTORY. Forecasts are estimates and do not count as verified savings.")
    if st.button("Load Cost Forecast Drivers", key="cost_contract_load_forecast_drivers", width="stretch"):
        st.session_state["cost_contract_forecast_detail"] = load_forecast_detail(
            company,
            environment,
            forecast_keys=("EOM_SPEND", "EOQ_SPEND", "CONTRACT_BURN", "CREDIT_ANOMALY"),
            days=180,
        )
        st.session_state["cost_contract_forecast_scope"] = (company, environment)

    detail = st.session_state.get("cost_contract_forecast_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("cost_contract_forecast_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No cost forecast rows are available for this scope yet.")
            return
        upward = safe_int(detail.get("TREND_DIRECTION", pd.Series(dtype=str)).fillna("").astype(str).eq("Up").sum())
        low_confidence = safe_int(detail.get("CONFIDENCE", pd.Series(dtype=str)).fillna("").astype(str).eq("Low").sum())
        value_risk = safe_float(pd.to_numeric(detail.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        render_shell_snapshot((
            ("Rows", f"{len(detail):,}"),
            ("Trending Up", f"{upward:,}"),
            ("Low Confidence", f"{low_confidence:,}"),
            ("Value/Risk", f"${value_risk:,.0f}"),
        ))
        render_priority_dataframe(
            detail,
            title="Cost forecast drivers and methodology",
            priority_columns=[
                "SNAPSHOT_TS", "FORECAST_NAME", "FORECAST_VALUE", "VALUE_UNIT",
                "CURRENT_ACTUAL", "PRIOR_PERIOD_VALUE", "TREND_DIRECTION",
                "CONFIDENCE", "METHODOLOGY", "MAIN_DRIVER", "RECOMMENDED_ACTION",
                "OWNER_ROUTE", "VALUE_AT_RISK_USD", "LAST_REFRESHED_TS",
            ],
            sort_by=["SNAPSHOT_TS", "FORECAST_KEY"],
            ascending=[False, True],
            raw_label="All cost forecast history rows",
            height=300,
            max_rows=12,
        )


def _render_cost_change_correlation(company: str, environment: str) -> None:
    """Expose cost-related possible change correlations behind Load."""
    st.markdown("**Cost Change Intelligence**")
    st.caption("Loads possible correlations between recent changes and cost/warehouse signals. This is timing evidence, not root cause.")
    if st.button("Load Cost-Related Changes", key="cost_contract_load_change_correlations", width="stretch"):
        st.session_state["cost_contract_change_correlation_detail"] = load_change_correlation_detail(
            company,
            environment,
            change_types=("WAREHOUSE_CHANGE", "OBJECT_CHANGE", "SECURITY_SENSITIVE_CHANGE"),
            correlation_types=("Cost",),
            days=180,
        )
        st.session_state["cost_contract_change_correlation_scope"] = (company, environment)

    detail = st.session_state.get("cost_contract_change_correlation_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("cost_contract_change_correlation_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No cost-related change correlations are available for this scope yet.")
            return
        render_priority_dataframe(
            detail,
            title="Possible cost correlations after changes",
            priority_columns=[
                "RELATED_TS", "CHANGE_TS", "CHANGE_TYPE", "OBJECT_NAME",
                "CHANGED_BY", "RELATED_SIGNAL", "RELATED_ENTITY",
                "CORRELATION_STRENGTH", "CORRELATION_LABEL", "EVIDENCE",
                "RISK_LEVEL", "OWNER_ROUTE", "CONFIDENCE",
            ],
            sort_by=["RELATED_TS", "CHANGE_TS"],
            ascending=[False, False],
            raw_label="All cost-related change correlations",
            height=300,
            max_rows=10,
        )


def _render_savings_verification_workflow(company: str, environment: str) -> None:
    """Expose Phase 2E cost savings verification behind an explicit Load action."""
    st.markdown("**Savings Verification Workflow**")
    st.caption(
        "Loads post-action verification rows from closed-loop marts. "
        "Forecasted and expected savings remain separate from actual verified savings."
    )
    if st.button("Load Savings Verification", key="cost_contract_load_savings_verification", width="stretch"):
        st.session_state["cost_contract_savings_verification_detail"] = load_closed_loop_verification_detail(
            company,
            environment,
            domains=("Cost",),
            days=180,
        )
        st.session_state["cost_contract_savings_verification_scope"] = (company, environment)

    detail = st.session_state.get("cost_contract_savings_verification_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("cost_contract_savings_verification_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No cost savings verification rows are available for this scope yet.")
            return
        expected = pd.to_numeric(detail.get("EXPECTED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        actual = pd.to_numeric(detail.get("ACTUAL_VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        status = detail.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str)
        render_shell_snapshot((
            ("Expected", f"${safe_float(expected.sum()):,.0f}"),
            ("Verified", f"${safe_float(actual.sum()):,.0f}"),
            ("Unverified", f"${safe_float((expected - actual).clip(lower=0).sum()):,.0f}"),
            ("Pending", f"{safe_int((~status.isin(['Verified', 'Closed'])).sum()):,}"),
        ))
        render_priority_dataframe(
            detail,
            title="Savings verification workflow",
            priority_columns=[
                "ACTION_DOMAIN", "VERIFICATION_STATUS", "EXPECTED_SAVINGS_USD",
                "ACTUAL_VERIFIED_SAVINGS_USD", "VERIFICATION_WINDOW_START",
                "VERIFICATION_WINDOW_END", "VERIFICATION_STEPS", "VERIFIED_BY",
                "VERIFIED_AT", "EVIDENCE", "LAST_REFRESHED_TS",
            ],
            sort_by=["ACTUAL_VERIFIED_SAVINGS_USD", "EXPECTED_SAVINGS_USD", "LAST_REFRESHED_TS"],
            ascending=[False, False, False],
            raw_label="All savings verification rows",
            height=300,
            max_rows=10,
        )


def _render_cost_command_findings(company: str, environment: str) -> None:
    """Expose cost-spike correlated findings behind an explicit Load action."""
    st.markdown("**Cost Investigation Findings**")
    st.caption("Loads deterministic cost-spike root-cause candidates, evidence summaries, and review-gated recommendations.")
    types = ("Cost Spike",)
    if st.button("Load Cost Investigation Findings", key="cost_contract_load_command_center", width="stretch"):
        st.session_state["cost_contract_command_findings"] = load_command_center_finding_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["cost_contract_command_recommendations"] = load_command_center_recommendation_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["cost_contract_command_scope"] = (company, environment)

    if st.session_state.get("cost_contract_command_scope") != (company, environment):
        return
    findings = st.session_state.get("cost_contract_command_findings")
    recommendations = st.session_state.get("cost_contract_command_recommendations")
    if isinstance(findings, pd.DataFrame):
        if findings.empty:
            st.info("No cost investigation findings are available for this scope yet.")
        else:
            render_priority_dataframe(
                findings,
                title="Cost-spike root-cause candidates",
                priority_columns=[
                    "QUESTION_TEXT", "ROOT_CAUSE_CANDIDATE", "CAUSALITY_LABEL",
                    "EVIDENCE_SUMMARY", "CONFIDENCE", "BUSINESS_IMPACT",
                    "OWNER_ROUTE", "RELATED_CHANGES", "RELATED_ALERTS",
                    "RELATED_SCORECARD_DRIVERS", "RELATED_FORECASTS",
                    "RECOMMENDED_ACTION", "RISK_LEVEL", "EXECUTION_PLAN_REF",
                    "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "VERIFICATION_PATH",
                ],
                sort_by=["RISK_LEVEL", "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "LAST_REFRESHED_TS"],
                ascending=[True, False, False],
                raw_label="All cost investigation findings",
                height=300,
                max_rows=8,
            )
    if isinstance(recommendations, pd.DataFrame):
        if not recommendations.empty:
            render_priority_dataframe(
                recommendations,
                title="Cost investigation recommendations",
                priority_columns=[
                    "RECOMMENDED_ACTION", "RISK_LEVEL", "OWNER_ROUTE",
                    "EXECUTION_PLAN_REF", "REVIEW_REQUIRED",
                    "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "VERIFICATION_PATH",
                    "SAFETY_NOTE", "LAST_REFRESHED_TS",
                ],
                sort_by=["EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "LAST_REFRESHED_TS"],
                ascending=[False, False],
                raw_label="All cost investigation recommendations",
                height=260,
                max_rows=6,
            )


def _normalize_cost_contract_workflow_state() -> None:
    current = str(st.session_state.get("cost_contract_workflow") or "")
    advanced_tool = LEGACY_COST_ADVANCED_TOOL_ALIASES.get(current)
    if advanced_tool:
        st.session_state["cost_contract_advanced_tool"] = advanced_tool
        st.session_state[_ADVANCED_COST_TOOLS_VISIBLE_KEY] = True
    inner_aliases = LEGACY_COST_INNER_VIEW_ALIASES.get(current, {})
    for key, value in inner_aliases.items():
        st.session_state[key] = value
    if "cost_center_view" in inner_aliases:
        st.session_state[_PRESERVE_COST_CENTER_VIEW_KEY] = True
    mapped = LEGACY_COST_WORKFLOW_ALIASES.get(current)
    if mapped:
        st.session_state["cost_contract_workflow"] = mapped


def _apply_cost_workflow_preset(workflow: str) -> None:
    workflow_name = str(workflow)
    presets = COST_WORKFLOW_PRESETS.get(workflow_name, {})
    workflow_changed = st.session_state.get(_LAST_COST_WORKFLOW_KEY) != workflow_name
    preserve_cost_center_view = bool(st.session_state.pop(_PRESERVE_COST_CENTER_VIEW_KEY, False))
    for key, value in presets.items():
        if key == "cost_center_view" and preserve_cost_center_view and st.session_state.get(key):
            continue
        if workflow_changed or not st.session_state.get(key):
            st.session_state[key] = value
    st.session_state[_LAST_COST_WORKFLOW_KEY] = workflow_name


def _render_advanced_cost_tools(company: str, environment: str) -> None:
    tool = render_workflow_selector(
        "Advanced cost tool",
        "cost_contract_advanced_tool",
        tuple(ADVANCED_COST_TOOL_DETAILS),
        ADVANCED_COST_TOOL_DETAILS,
        columns=2,
    )
    render_workflow_module(tool, ADVANCED_COST_TOOL_MODULES)


def _render_cost_contract_workflow(workflow: str, company: str, environment: str) -> None:
    if workflow == "Cost Overview":
        _render_cost_watch_floor(company, safe_float(get_credit_price()) or 3.68)
        return
    _apply_cost_workflow_preset(workflow)
    render_workflow_module(workflow, WORKFLOW_MODULES)


def _render_cost_filter_indicator() -> None:
    filters: list[str] = []
    environment = str(get_active_environment() or DEFAULT_ENVIRONMENT)
    if environment and environment != DEFAULT_ENVIRONMENT:
        filters.append(f"Environment: {environment}")
    for label, key in (
        ("Warehouse", "global_warehouse"),
        ("User", "global_user"),
        ("Role", "global_role"),
        ("Database", "global_database"),
    ):
        value = str(st.session_state.get(key) or "").strip()
        if value:
            filters.append(f"{label}: {value}")
    selected_days = safe_int(
        st.session_state.get("cost_contract_cockpit_window", DEFAULT_DAY_WINDOW),
        DEFAULT_DAY_WINDOW,
    )
    if selected_days != DEFAULT_DAY_WINDOW:
        filters.append(f"Cost window: {selected_days}d")
    if filters:
        st.caption("Filters active: " + " | ".join(filters))
    else:
        st.caption("Filters active: company and date window only.")


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
