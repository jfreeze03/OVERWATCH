# sections/cost_contract.py - Consolidated cost and contract workflow
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st
from importlib import import_module

from config import (
    DAY_WINDOW_OPTIONS,
    DEFAULT_ALERT_EMAIL,
    DEFAULT_COMPANY,
    DEFAULT_ENVIRONMENT,
    DEFAULTS,
    DEFAULT_DAY_WINDOW,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.shell_helpers import (
    _clean_display_text,
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
    render_escaped_labeled_text,
    render_shell_snapshot,
    with_loaded_at,
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
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note, defer_source_note


pd = lazy_pandas()

build_cost_reconciliation_sql = _lazy_util("build_cost_reconciliation_sql")
build_cost_efficiency_summary_sql = _lazy_util("build_cost_efficiency_summary_sql")
build_warehouse_efficiency_sql = _lazy_util("build_warehouse_efficiency_sql")
build_clustering_cost_sql = _lazy_util("build_clustering_cost_sql")
build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_mart_cost_run_rate_sql = _lazy_util("build_mart_cost_run_rate_sql")
build_mart_cost_service_lens_sql = _lazy_util("build_mart_cost_service_lens_sql")
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


def _render_cost_splash_narrative(summary: dict, *, days: int) -> None:
    state, headline, detail = _cost_splash_status(summary)
    top_wh_display = _short_label(summary.get("top_warehouse"), 24)
    top_user = str(summary.get("top_cortex_user") or "No Cortex user")
    top_user_display = _short_label(top_user, 26)
    render_escaped_bold_text(f"{state}: {headline}")
    st.caption(detail)
    metrics = [
        ("Spend", f"${safe_float(summary.get('spend')):,.0f} ({_slide_money(summary.get('spend_delta'), signed=True)})"),
        ("Change", f"{_slide_money(summary.get('spend_delta'), signed=True)} ({safe_float(summary.get('delta_pct')):+.1f}%)"),
        ("Driver", f"{top_wh_display} ({_slide_money(summary.get('top_warehouse_delta_spend'), signed=True)})"),
        ("30d Run", f"{_slide_money(summary.get('projected_30d_spend'))} {str(summary.get('run_rate_state') or '').strip()}".strip()),
    ]
    render_shell_snapshot(tuple(metrics))
    render_shell_snapshot((
        ("Avg / Day", f"${safe_float(summary.get('avg_daily')):,.0f}"),
        ("Peak Day", f"${safe_float(summary.get('peak_day')):,.0f}"),
        ("Cortex Spend", f"${safe_float(summary.get('cortex_spend')):,.0f} ({safe_int(summary.get('cortex_requests')):,} req)"),
        ("Top AI User", f"{top_user_display} (${safe_float(summary.get('top_cortex_user_spend')):,.0f})"),
    ))
    notes = [f"{int(days)}-day window", str(summary.get("cost_basis") or "Warehouse metering total")]
    if safe_int(summary.get("active_services")):
        notes.append(f"{safe_int(summary.get('active_services')):,} active service(s)")
    notes.append(f"{safe_int(summary.get('active_warehouses')):,} active warehouse(s)")
    if top_wh_display != str(summary.get("top_warehouse")):
        notes.append(f"Top warehouse: {summary.get('top_warehouse')}")
    if top_user_display != top_user:
        notes.append(f"Top Cortex user: {top_user}")
    st.caption(" | ".join(notes))


def _render_cost_splash_next_move(summary: dict) -> None:
    workflow, state, detail = _cost_splash_next_move(summary)
    with st.container(border=True):
        label_col, detail_col, action_col = st.columns([1.15, 4.2, 1.2])
        with label_col:
            st.markdown("**Next Cost Move**")
            st.caption(state)
        with detail_col:
            render_escaped_bold_text(workflow)
        with action_col:
            st.write("")
            if st.button(
                "Open workflow",
                key="cost_contract_splash_next_workflow",
                help=detail,
                width="stretch",
            ):
                st.session_state["cost_contract_workflow"] = workflow
                st.rerun()


def _render_cost_executive_decision_stack(summary: dict) -> None:
    action_summary = _cost_snapshot_action_summary(st.session_state.get("cost_contract_queue", pd.DataFrame()))
    render_priority_dataframe(
        _cost_executive_decision_stack(summary, action_summary),
        title="Cost executive decision stack",
        priority_columns=["DECISION", "SIGNAL", "FIRST_QUESTION", "OWNER", "ROUTE"],
        raw_label="All cost executive decision rows",
        height=230,
        max_rows=4,
    )


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


def _render_savings_closure_control(queue: pd.DataFrame, credit_price: float) -> None:
    summary, detail = _build_cost_closure_analytics(queue, credit_price)
    st.markdown("**Cost Action Closure**")
    defer_source_note(
        "Optimization impact remains estimated until the action is fixed and later telemetry shows the signal improved."
    )
    render_shell_snapshot((
        ("Cost Actions", f"{summary['cost_actions']:,}"),
        ("Open Est. Savings", f"${summary['open_estimated_monthly_savings']:,.0f}/mo"),
        ("Blocked Est. Savings", f"${summary['blocked_estimated_monthly_savings']:,.0f}/mo"),
        ("Measured Impact", f"${summary['verified_period_delta_dollars']:,.0f}"),
        ("Closed With Telemetry", f"{summary['audit_ready_pct']:,.1f}%"),
    ))

    if detail.empty:
        st.info("No cost-control or chargeback actions are currently visible in the loaded action queue scope.")
        return

    render_priority_dataframe(
        detail,
        title="Cost actions that still need review, telemetry, or closure status",
        priority_columns=[
            "SEVERITY", "CLOSURE_STATE", "CATEGORY", "ENTITY_NAME", "OWNER",
            "OWNER_EMAIL", "ONCALL_PRIMARY", "APPROVAL_GROUP", "OWNER_SOURCE",
            "STATUS", "OWNER_APPROVAL_STATUS", "TELEMETRY_STATUS",
            "BASELINE_VALUE", "CURRENT_VALUE", "MEASURED_DELTA",
            "MEASURED_IMPACT_DOLLARS", "RECOVERY_SLA_STATE",
            "IMPACT_EVIDENCE", "TICKET_ID", "APPROVER",
        ],
        sort_by=["QUEUE_PRIORITY", "SEVERITY"],
        ascending=[True, True],
        raw_label="All loaded cost closure rows",
        height=260,
        max_rows=10,
    )

def _nullable_float(row: pd.Series, column: str) -> float | None:
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return safe_float(value)


def _format_optional_pct(value: float | None, empty: str = "No baseline") -> str:
    if value is None:
        return empty
    return f"{value:+.1f}%"


def _render_metric_items(items: list[dict]) -> None:
    """Render a compact metric row from already-filtered headline items."""
    visible = [item for item in items if item]
    if not visible:
        return
    metrics = []
    for item in visible:
        value = str(item.get("value") or "")
        delta = item.get("delta")
        if delta:
            value = f"{value} ({delta})"
        metrics.append((str(item.get("label") or ""), value))
    render_shell_snapshot(tuple(metrics))


def _render_cost_run_rate_lens(run_rate: pd.DataFrame | None, credit_price: float, error: str = "") -> None:
    st.markdown("**Run-Rate and YOY**")
    if error:
        st.info("Run-rate trend unavailable.")
        defer_source_note(error)
        return
    if run_rate is None or getattr(run_rate, "empty", True):
        defer_source_note("Load the cockpit to show complete-day 7-day averages, 30-day context, and prior-year comparison.")
        return

    row = run_rate.iloc[0]
    avg_7d = safe_float(row.get("AVG_DAILY_7D"))
    avg_30d = safe_float(row.get("AVG_DAILY_30D"))
    credits_7d = safe_float(row.get("CREDITS_7D"))
    projected_30d = safe_float(row.get("PROJECTED_30D_FROM_7D"))
    pct_vs_30d = _nullable_float(row, "PCT_VS_30D_AVG")
    yoy_7d_pct = _nullable_float(row, "YOY_7D_PCT")
    yoy_30d_pct = _nullable_float(row, "YOY_30D_PCT")
    yoy_days_7d = safe_int(row.get("YOY_DAYS_7D"))
    yoy_days_30d = safe_int(row.get("YOY_DAYS_30D"))
    run_state = str(row.get("RUN_RATE_STATE") or "Unknown")
    yoy_state = str(row.get("YOY_STATE") or "Unknown")

    metrics = [
        {
            "label": "7d Avg",
            "value": f"{avg_7d:,.1f} cr/day",
            "delta": _format_optional_pct(pct_vs_30d, run_state) + " vs 30d",
            "delta_color": "inverse",
        },
        {
            "label": "7d Cost",
            "value": f"${credits_to_dollars(credits_7d, credit_price):,.0f}",
            "delta": f"${credits_to_dollars(avg_7d, credit_price):,.0f}/day",
        },
        {
            "label": "30d Run-Rate",
            "value": f"${credits_to_dollars(projected_30d, credit_price):,.0f}/30d",
            "delta": run_state,
        },
    ]
    if yoy_7d_pct is not None and yoy_days_7d > 0:
        metrics.append({
            "label": "7d YOY",
            "value": _format_optional_pct(yoy_7d_pct),
            "delta": f"{yoy_days_7d}/7 PY days",
            "delta_color": "inverse",
        })
    if yoy_30d_pct is not None and yoy_days_30d > 0:
        metrics.append({
            "label": "30d YOY",
            "value": _format_optional_pct(yoy_30d_pct),
            "delta": f"{yoy_days_30d}/30 PY days",
            "delta_color": "inverse",
        })
    _render_metric_items(metrics)

    top_wh = str(row.get("TOP_YOY_INCREASE_WAREHOUSE") or "No warehouse baseline")
    top_delta = safe_float(row.get("TOP_YOY_INCREASE_CREDITS"))
    defer_source_note(
        f"{yoy_state}. Top same-week YOY increase: {top_wh} "
        f"({top_delta:+,.2f} credits). Uses complete days only."
    )


def _build_cost_period_explanation(
    cockpit: pd.DataFrame | None,
    run_rate: pd.DataFrame | None,
    queue: pd.DataFrame | None,
    credit_price: float,
) -> pd.DataFrame:
    """Summarize cost movement, likely driver, and next workflow for executives."""
    rows: list[dict] = []
    cockpit_row = cockpit.iloc[0] if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else pd.Series(dtype=object)
    run_row = run_rate.iloc[0] if isinstance(run_rate, pd.DataFrame) and not run_rate.empty else pd.Series(dtype=object)
    current_credits = safe_float(cockpit_row.get("CURRENT_CREDITS"))
    prior_credits = safe_float(cockpit_row.get("PRIOR_CREDITS"))
    credit_delta = current_credits - prior_credits
    delta_pct = (credit_delta / prior_credits * 100) if prior_credits else None
    top_wh = str(cockpit_row.get("TOP_INCREASE_WAREHOUSE") or "No warehouse loaded")
    top_delta = safe_float(cockpit_row.get("TOP_INCREASE_CREDITS"))
    pct_vs_30d = _nullable_float(run_row, "PCT_VS_30D_AVG") if not run_row.empty else None
    yoy_7d = _nullable_float(run_row, "YOY_7D_PCT") if not run_row.empty else None
    yoy_state = str(run_row.get("YOY_STATE") or "No YOY baseline")
    open_savings = 0.0
    open_count = 0
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        status = queue.get("STATUS", pd.Series(dtype=str)).astype(str)
        open_mask = ~status.isin(["Fixed", "Ignored"])
        open_count = int(open_mask.sum())
        if "EST_MONTHLY_SAVINGS" in queue.columns:
            open_savings = safe_float(pd.to_numeric(queue.loc[open_mask, "EST_MONTHLY_SAVINGS"], errors="coerce").fillna(0).sum())

    rows.append({
        "QUESTION": "Did the bill move?",
        "ANSWER": f"{credit_delta:+,.2f} credits ({_format_optional_pct(delta_pct)}) vs prior window.",
        "DOLLAR_IMPACT": f"${credits_to_dollars(credit_delta, credit_price):+,.0f}",
        "EVIDENCE": f"Current {current_credits:,.2f} credits; prior {prior_credits:,.2f} credits.",
        "NEXT_ACTION": "If the move is above 10%, explain the bill before tuning warehouses or changing workload schedules.",
    })
    rows.append({
        "QUESTION": "What likely changed?",
        "ANSWER": f"{top_wh} is the largest loaded increase at {top_delta:+,.2f} credits.",
        "DOLLAR_IMPACT": f"${credits_to_dollars(top_delta, credit_price):+,.0f}",
        "EVIDENCE": "Cost cockpit current/prior warehouse movement.",
        "NEXT_ACTION": "Open Cost & Contract recommendations to confirm queue, spill, p95, settings, and dollar telemetry for that warehouse.",
    })
    rows.append({
        "QUESTION": "Is this a short spike or trend?",
        "ANSWER": f"7d vs 30d {_format_optional_pct(pct_vs_30d)}; YOY7 {_format_optional_pct(yoy_7d)}; {yoy_state}.",
        "DOLLAR_IMPACT": "Trend telemetry",
        "EVIDENCE": "Complete-day 7d, 30d, and prior-year metering.",
        "NEXT_ACTION": "Use the run-rate lens before calling same-day partial metering a real cost incident.",
    })
    rows.append({
        "QUESTION": "Is there already a fix path?",
        "ANSWER": f"{open_count:,} open action(s), ${open_savings:,.0f}/mo estimated savings.",
        "DOLLAR_IMPACT": f"${open_savings:,.0f}/mo",
        "EVIDENCE": "Open Cost & Contract action queue rows.",
        "NEXT_ACTION": "Work measured actions first and confirm savings with post-period metering.",
    })
    return pd.DataFrame(rows)


def _render_cost_period_explanation(
    cockpit: pd.DataFrame | None,
    run_rate: pd.DataFrame | None,
    queue: pd.DataFrame | None,
    credit_price: float,
) -> None:
    st.markdown("**Why Did Cost Change?**")
    render_priority_dataframe(
        _build_cost_period_explanation(cockpit, run_rate, queue, credit_price),
        title="Cost movement explanation",
        priority_columns=["QUESTION", "ANSWER", "DOLLAR_IMPACT", "EVIDENCE", "NEXT_ACTION"],
        raw_label="All cost movement explanation rows",
        height=260,
    )


def _render_cost_advisor_detail(board: pd.DataFrame | None) -> None:
    options = _cost_advisor_detail_options(board)
    if options.empty:
        return
    st.markdown("**Open Cost Advisor Finding**")
    selected_label = st.selectbox(
        "Advisor finding",
        options["DETAIL_LABEL"].tolist(),
        key="cost_advisor_detail_select",
    )
    selected = options[options["DETAIL_LABEL"].eq(selected_label)]
    if selected.empty:
        return
    row = selected.iloc[0]
    render_shell_snapshot((
        ("Priority", str(row.get("SEVERITY") or row.get("PRIORITY") or "Review")),
        ("Action", str(row.get("ACTION_TYPE") or "Investigate")),
        ("Route", LEGACY_COST_WORKFLOW_ALIASES.get(str(row.get("WORKFLOW_ROUTE") or ""), str(row.get("WORKFLOW_ROUTE") or "Cost Recommendations"))),
        ("Metric", str(row.get("PRIMARY_METRIC") or "")),
    ))
    st.caption(_clean_display_text(str(row.get("TELEMETRY_SUMMARY") or row.get("EVIDENCE") or "")))
    render_escaped_labeled_text("Next move", row.get("SAFE_NEXT_ACTION") or "Review the loaded telemetry.")
    render_escaped_labeled_text(
        "Proof",
        row.get("VALIDATION_NEEDED") or row.get("PROOF_REQUIRED") or "Confirm in the next completed telemetry window.",
    )
    do_not_do = str(row.get("DO_NOT_DO") or "").strip()
    if do_not_do:
        st.caption(f"Guardrail: {_clean_display_text(do_not_do)}")
    route = str(row.get("WORKFLOW_ROUTE") or "").strip()
    if route in WORKFLOWS and st.button(f"Open {route}", key="cost_advisor_detail_route", width="stretch"):
        st.session_state["cost_contract_workflow"] = route
        st.rerun()


def _render_cost_advisor_board(
    *,
    efficiency_summary: pd.DataFrame,
    warehouse_efficiency: pd.DataFrame,
    clustering_cost: pd.DataFrame,
    reconciliation: pd.DataFrame,
    service_lens: pd.DataFrame,
    credit_price: float,
    days: int,
    storage_table_metrics: pd.DataFrame | None = None,
    storage_db_detail: pd.DataFrame | None = None,
    storage_cost_per_tb: float | None = None,
) -> None:
    summary, board = _build_cost_advisor_board(
        efficiency_summary=efficiency_summary,
        warehouse_efficiency=warehouse_efficiency,
        clustering_cost=clustering_cost,
        reconciliation=reconciliation,
        service_lens=service_lens,
        credit_price=credit_price,
        days=days,
        storage_table_metrics=storage_table_metrics,
        storage_db_detail=storage_db_detail,
        storage_cost_per_tb=storage_cost_per_tb,
    )
    st.session_state["cost_contract_cost_advisor_summary"] = summary
    st.session_state["cost_contract_cost_advisor_board"] = board
    if board.empty:
        return
    st.markdown("**Cost Advisor**")
    render_shell_snapshot((
        ("Findings", f"{summary['findings']:,}"),
        ("High Priority", f"{summary['high']:,}"),
        ("Est. Savings / Mo", f"${safe_float(summary.get('estimated_monthly_savings')):,.0f}"),
        ("Value at Risk", f"${safe_float(summary.get('estimated_monthly_impact')):,.0f}"),
    ))
    st.caption(
        "Advisor findings are conservative and telemetry-backed. Savings are estimates; pressure and attribution rows are investigation/value-at-risk signals."
    )
    action_summary = _cost_advisor_action_summary(board)
    if not action_summary.empty:
        render_priority_dataframe(
            action_summary,
            title="Cost advisor action rollup",
            priority_columns=[
                "TOP_PRIORITY", "ACTION_TYPE", "WORKFLOW_ROUTE", "FINDINGS", "HIGH_FINDINGS",
                "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD", "NEXT_MOVE",
            ],
            sort_by=["TOP_PRIORITY", "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD"],
            ascending=[True, False, False],
            raw_label="All cost advisor action groups",
            height=260,
            max_rows=8,
        )
    _render_cost_advisor_category_chart(board)
    render_priority_dataframe(
        board,
        title="Ranked cost advisor findings",
        priority_columns=[
            "SEVERITY", "ACTION_TYPE", "WORKFLOW_ROUTE", "CATEGORY", "ENTITY", "EXECUTION_MODE", "PRIMARY_METRIC",
            "ESTIMATE_TYPE",
            "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD",
            "TELEMETRY_SUMMARY", "SAFE_NEXT_ACTION", "VALIDATION_NEEDED", "DO_NOT_DO", "CONFIDENCE",
        ],
        sort_by=["SEVERITY", "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD"],
        ascending=[True, False, False],
        raw_label="All cost advisor findings",
        height=340,
        max_rows=12,
    )
    _render_cost_advisor_detail(board)


def _render_account_service_cost_lens(service_lens: pd.DataFrame, credit_price: float, error: str = "") -> None:
    if error:
        st.caption(f"Account service-cost lens unavailable: {error}")
        return
    if service_lens is None or getattr(service_lens, "empty", True):
        return
    summary = _build_service_cost_lens_summary(service_lens)
    st.markdown("**Account Service Cost Lens**")
    metrics = [
        {"label": "Total Credits", "value": f"{summary['total_credits']:,.2f}"},
        {
            "label": "Non-Warehouse Credits",
            "value": f"{summary['non_warehouse_credits']:,.2f}",
            "delta_color": "inverse",
        },
    ]
    if safe_float(summary.get("ai_credits")) >= 0.005:
        metrics.append({
            "label": "AI / Cortex Credits",
            "value": f"{summary['ai_credits']:,.2f}",
            "delta_color": "inverse",
        })
    if safe_float(summary.get("serverless_credits")) >= 0.005:
        metrics.append({
            "label": "Serverless Credits",
            "value": f"{summary['serverless_credits']:,.2f}",
            "delta_color": "inverse",
        })
    if safe_float(summary.get("top_moving_delta")):
        mover = str(summary.get("top_moving_service") or "No movement")
        metrics.append({
            "label": "Top Service Move",
            "value": mover if len(mover) <= 24 else mover[:21] + "...",
            "delta": f"{safe_float(summary.get('top_moving_delta')):+,.2f} cr",
            "delta_color": "inverse",
        })
    _render_metric_items(metrics)
    st.caption(
        f"Top service: {summary['top_service']}. "
        f"Official Cost Monitor formula: METERING_HISTORY total credits through the completed 24-hour window, "
        f"with Snowflake services at ${credit_price:,.2f}/credit and Cortex/AI at ${get_current_ai_credit_price():,.2f}/AI credit."
    )
    _render_cost_chart_with_data_toggle(
        "Service Spend Movement",
        "cost_contract_service_movement",
        lambda: _render_service_cost_movement_chart(service_lens, credit_price),
        _service_lens_movement_rows(service_lens, credit_price, limit=16),
        priority_columns=[
            "SERVICE_CATEGORY", "SERVICE_TYPE", "CURRENT_SPEND_USD",
            "PRIOR_SPEND_USD", "COST_DELTA_USD", "CREDIT_DELTA",
        ],
        sort_by=["COST_DELTA_USD"],
        max_rows=16,
    )
    render_priority_dataframe(
        service_lens,
        title="Cost by Snowflake service type",
        priority_columns=[
            "SERVICE_CATEGORY", "SERVICE_TYPE", "CREDITS_BILLED", "ESTIMATED_COST_USD",
            "CREDITS_BILLED_PRIOR", "CREDIT_DELTA", "COST_DELTA_USD", "PCT_DELTA",
            "CREDITS_USED_COMPUTE", "CREDITS_USED_CLOUD_SERVICES", "OBSERVED_DAYS",
        ],
        sort_by=["CREDITS_BILLED"],
        ascending=[False],
        raw_label="All service-cost lens rows",
        height=280,
        max_rows=10,
    )


def _render_cost_efficiency_rca(
    efficiency_summary: pd.DataFrame,
    warehouse_efficiency: pd.DataFrame,
    clustering_cost: pd.DataFrame,
    credit_price: float,
    errors: dict | None = None,
) -> None:
    errors = errors or {}
    loaded_any = any(
        isinstance(frame, pd.DataFrame) and not frame.empty
        for frame in (efficiency_summary, warehouse_efficiency, clustering_cost)
    )
    if not loaded_any:
        for label, err in errors.items():
            if err:
                st.caption(f"{label} unavailable: {err}")
        return

    st.markdown("**Cost Efficiency RCA**")
    if isinstance(efficiency_summary, pd.DataFrame) and not efficiency_summary.empty:
        row = efficiency_summary.iloc[0]
        render_shell_snapshot((
            ("Cost / Query", f"${safe_float(row.get('COST_PER_QUERY_USD')):,.4f}"),
            ("Cost / TB", f"${safe_float(row.get('COST_PER_TB_USD')):,.2f}"),
            ("Failed Waste", f"${safe_float(row.get('FAILED_QUERY_WASTE_USD')):,.0f}"),
            ("Avg Cache", f"{safe_float(row.get('AVG_CACHE_PCT')):,.1f}%"),
        ))
        st.caption(
            f"{safe_int(row.get('QUERY_COUNT')):,} query rows, "
            f"{safe_float(row.get('TB_SCANNED')):,.2f} TB scanned, "
            f"{safe_int(row.get('FAILED_QUERIES')):,} failed query rows. "
            f"{str(row.get('ATTRIBUTION_SOURCE') or 'OVERWATCH allocated fallback')}"
        )

    if isinstance(warehouse_efficiency, pd.DataFrame) and not warehouse_efficiency.empty:
        render_priority_dataframe(
            warehouse_efficiency,
            title="Warehouse efficiency and pressure",
            priority_columns=[
                "WAREHOUSE_NAME", "COST_USD", "QUERY_COUNT", "COST_PER_QUERY_USD",
                "COST_PER_TB_USD", "CREDITS_PER_EXEC_HOUR", "QUEUE_SECONDS",
                "REMOTE_SPILL_GB", "FAILED_QUERIES", "FAILED_QUERY_WASTE_USD",
                "AVG_CACHE_PCT",
            ],
            sort_by=["FAILED_QUERY_WASTE_USD", "REMOTE_SPILL_GB", "COST_USD"],
            ascending=[False, False, False],
            raw_label="All warehouse efficiency rows",
            height=300,
            max_rows=12,
        )

    if isinstance(clustering_cost, pd.DataFrame) and not clustering_cost.empty:
        total_clustering = safe_float(clustering_cost.get("CLUSTERING_COST_USD", pd.Series(dtype=float)).sum())
        st.caption(f"Automatic clustering cost loaded: ${total_clustering:,.0f} in the selected window.")
        render_priority_dataframe(
            clustering_cost,
            title="Automatic clustering cost and churn",
            priority_columns=[
                "TABLE_NAME", "CLUSTERING_COST_USD", "CLUSTERING_CREDITS",
                "TB_RECLUSTERED", "ROWS_RECLUSTERED", "COST_PER_TB_RECLUSTERED",
            ],
            sort_by=["CLUSTERING_COST_USD", "COST_PER_TB_RECLUSTERED"],
            ascending=[False, False],
            raw_label="All clustering cost rows",
            height=260,
            max_rows=10,
        )

    for label, err in errors.items():
        if err:
            st.caption(f"{label} unavailable: {err}")
    defer_source_note(
        "Cost efficiency RCA uses completed ACCOUNT_USAGE windows and query-attribution fallback where official query attribution is unavailable."
    )


def _cost_alert_message(row: pd.Series, *keys: str, default: str = "") -> str:
    for key in keys:
        if key in row.index:
            value = row.get(key)
            try:
                if pd.isna(value):
                    continue
            except Exception:
                pass
            text = str(value or "").strip()
            if text:
                return text
    return default


def _build_cost_monitoring_alert_rows(
    *,
    root_cause: pd.DataFrame | None = None,
    correlation: pd.DataFrame | None = None,
    email_target: str = DEFAULT_ALERT_EMAIL,
) -> tuple[dict, pd.DataFrame]:
    """Create Alert Center-ready rows from loaded Cost & Contract monitoring telemetry."""
    email_target = str(email_target or DEFAULT_ALERT_EMAIL or "").strip()
    rows: list[dict] = []

    def add(
        *,
        severity: str,
        alert_type: str,
        entity: str,
        message: str,
        suggested_action: str,
        proof_query: str,
        route: str,
        owner: str,
        value_at_risk: float = 0.0,
        source_surface: str,
    ) -> None:
        severity = str(severity or "Medium").title()
        if severity not in {"Critical", "High", "Medium", "Watch", "Info"}:
            severity = "Medium"
        entity = str(entity or "Cost Monitoring").strip()
        rows.append({
            "SEVERITY": severity,
            "CATEGORY": "Cost Control",
            "ALERT_TYPE": alert_type,
            "ENTITY_NAME": entity,
            "MESSAGE": message,
            "SUGGESTED_ACTION": suggested_action,
            "PROOF_QUERY": proof_query,
            "ROUTE": route or "Cost & Contract",
            "OWNER": owner or "DBA / Cost owner",
            "EMAIL_TARGET": email_target,
            "DELIVERY_STATUS": alert_delivery_status_for_target(email_target),
            "STATUS": "New",
            "VALUE_AT_RISK_USD": round(safe_float(value_at_risk), 2),
            "SOURCE_SURFACE": source_surface,
        })

    if isinstance(root_cause, pd.DataFrame) and not root_cause.empty:
        view = root_cause.copy()
        view.columns = [str(col).upper() for col in view.columns]
        high = view[view.get("SEVERITY", pd.Series(index=view.index, dtype=str)).fillna("").astype(str).str.title().isin(["Critical", "High"])]
        if "VALUE_AT_RISK_USD" in high.columns:
            high = high.sort_values("VALUE_AT_RISK_USD", ascending=False)
        for _, row in high.head(6).iterrows():
            add(
                severity=_cost_alert_message(row, "SEVERITY", default="High"),
                alert_type="Cost Root Cause Candidate",
                entity=_cost_alert_message(row, "ENTITY", "DRIVER", default="Cost root cause"),
                message=_cost_alert_message(row, "EVIDENCE", default="Cost root-cause candidate requires review."),
                suggested_action=_cost_alert_message(row, "NEXT_ACTION", default="Open Cost & Contract root-cause drilldown."),
                proof_query=_cost_alert_message(row, "PROOF_REQUIRED", default="Record warehouse metering, run-rate, routing, and change telemetry."),
                route=_cost_alert_message(row, "ROUTE", default="Cost & Contract"),
                owner="DBA / Cost owner",
                value_at_risk=safe_float(row.get("VALUE_AT_RISK_USD", 0)),
                source_surface="Cost Spike Root Cause",
            )

    if isinstance(correlation, pd.DataFrame) and not correlation.empty:
        view = correlation.copy()
        view.columns = [str(col).upper() for col in view.columns]
        high = view[view.get("SEVERITY", pd.Series(index=view.index, dtype=str)).fillna("").astype(str).str.title().isin(["Critical", "High"])]
        for _, row in high.head(5).iterrows():
            add(
                severity=_cost_alert_message(row, "SEVERITY", default="High"),
                alert_type="Change Cost Correlation",
                entity=_cost_alert_message(row, "ENTITY", "CORRELATION", default="Change/cost correlation"),
                message=_cost_alert_message(row, "EVIDENCE", default="A recent change may explain cost movement."),
                suggested_action=_cost_alert_message(row, "NEXT_ACTION", default="Compare change telemetry to cost movement before tuning."),
                proof_query=_cost_alert_message(row, "PROOF_REQUIRED", default="Record change query_id, actor, ticket, and cost telemetry."),
                route=_cost_alert_message(row, "ROUTE", default="Security Monitoring"),
                owner="DBA / Cost owner",
                value_at_risk=0.0,
                source_surface="Change + Cost Correlation",
            )

    board = pd.DataFrame(rows)
    if board.empty:
        return {
            "alert_count": 0,
            "critical_high": 0,
            "email_target": email_target,
            "top_alert": "No loaded Cost & Contract alert candidates",
        }, board
    board["_SEVERITY_RANK"] = board["SEVERITY"].apply(_cost_command_severity_rank)
    board = board.sort_values(["_SEVERITY_RANK", "VALUE_AT_RISK_USD"], ascending=[True, False])
    board = board.drop_duplicates(subset=["ALERT_TYPE", "ENTITY_NAME", "MESSAGE"], keep="first")
    top = board.iloc[0]
    summary = {
        "alert_count": int(len(board)),
        "critical_high": int(board["SEVERITY"].isin(["Critical", "High"]).sum()),
        "email_target": email_target,
        "top_alert": f"{top.get('ALERT_TYPE')} - {top.get('ENTITY_NAME')}",
    }
    return summary, board.drop(columns=["_SEVERITY_RANK"], errors="ignore").reset_index(drop=True)


def _build_cost_incident_timeline(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    alert_rows: pd.DataFrame | None = None,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build a compact incident narrative from cost movement to alert/action status."""
    state = state or st.session_state
    root_cause = _state_frame(state, "cost_contract_spike_root_cause")
    correlation = _state_frame(state, "cost_contract_change_cost_correlation")
    current_credits = safe_float(_first_frame_value(cockpit, "CURRENT_CREDITS", 0))
    prior_credits = safe_float(_first_frame_value(cockpit, "PRIOR_CREDITS", 0))
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "Cost scope") or "Cost scope")
    top_delta = safe_float(_first_frame_value(cockpit, "TOP_INCREASE_CREDITS", 0))
    pct_vs_30d = _first_frame_value(run_rate, "PCT_VS_30D_AVG", None)
    pct_vs_30d_float = safe_float(pct_vs_30d) if pct_vs_30d is not None and not pd.isna(pct_vs_30d) else 0.0
    open_cost_queue = _open_cost_action_frame(queue)

    rows: list[dict] = []

    def add(order: int, severity: str, step: str, entity: str, evidence: str, next_action: str, proof: str, route: str) -> None:
        rows.append({
            "EVENT_ORDER": int(order),
            "SEVERITY": severity,
            "INCIDENT_STEP": step,
            "ENTITY": entity,
            "EVIDENCE": evidence,
            "NEXT_ACTION": next_action,
            "PROOF_REQUIRED": proof,
            "ROUTE": route,
        })

    movement_severity = "Critical" if top_delta > 0 and pct_vs_30d_float >= 25 else "High" if top_delta > 0 else "Info"
    add(
        1,
        movement_severity,
        "Cost movement detected",
        top_wh,
        f"{top_wh}: {top_delta:+,.2f} credit delta; current {current_credits:,.2f} vs prior {prior_credits:,.2f}; 7d vs 30d {pct_vs_30d_float:+.1f}%.",
        "Explain the top cost mover before changing warehouse settings or workload routing.",
        "Complete-day run-rate plus FACT_WAREHOUSE_HOURLY current/prior warehouse metering.",
        "Cost & Contract > Cost by Warehouse",
    )

    if isinstance(root_cause, pd.DataFrame) and not root_cause.empty:
        root_view = root_cause.copy()
        root_view["_RANK"] = root_view.get("SEVERITY", pd.Series(index=root_view.index, dtype=str)).apply(_cost_command_severity_rank)
        root_view = root_view.sort_values(["_RANK"], ascending=True)
        root = root_view.iloc[0]
        add(
            2,
            _cost_alert_message(root, "SEVERITY", default="Medium"),
            "Root cause candidate",
            _cost_alert_message(root, "ENTITY", "DRIVER", default=top_wh),
            _cost_alert_message(root, "EVIDENCE", default="Root cause candidate loaded."),
            _cost_alert_message(root, "NEXT_ACTION", default="Confirm workload demand, workload mix, and setting changes before tuning."),
            _cost_alert_message(root, "PROOF_REQUIRED", default="Record Cost & Contract root-cause telemetry."),
            _cost_alert_message(root, "ROUTE", default="Cost & Contract"),
        )
    else:
        add(
            2,
            "Medium",
            "Root cause candidate",
            top_wh,
            "Root-cause board has not been loaded for this incident window.",
            "Refresh cost detail telemetry before assigning savings or tuning work.",
            "Cost Spike Root Cause board.",
            "Cost & Contract",
        )

    if isinstance(correlation, pd.DataFrame) and not correlation.empty:
        corr_view = correlation.copy()
        corr_view["_RANK"] = corr_view.get("SEVERITY", pd.Series(index=corr_view.index, dtype=str)).apply(_cost_command_severity_rank)
        corr_view = corr_view.sort_values(["_RANK"], ascending=True)
        corr = corr_view.iloc[0]
        add(
            3,
            _cost_alert_message(corr, "SEVERITY", default="Medium"),
            "Change correlation checked",
            _cost_alert_message(corr, "ENTITY", "CORRELATION", default=top_wh),
            _cost_alert_message(corr, "EVIDENCE", default="Change/cost correlation telemetry loaded."),
            _cost_alert_message(corr, "NEXT_ACTION", default="Compare change telemetry to the cost window before closure."),
            _cost_alert_message(corr, "PROOF_REQUIRED", default="Record change query_id, actor, ticket, and cost telemetry."),
            _cost_alert_message(corr, "ROUTE", default="Security Monitoring"),
        )
    else:
        add(
            3,
            "Medium",
            "Change correlation checked",
            top_wh,
            "Security Monitoring telemetry is available after refresh for this cost movement.",
            "Review Security Monitoring for the same company/environment before closing the incident as workload-only.",
            "FACT_OBJECT_CHANGE or Security Monitoring exception rows.",
            "Security Monitoring",
        )

    if isinstance(alert_rows, pd.DataFrame) and not alert_rows.empty:
        alert_view = alert_rows.copy()
        alert_view["_RANK"] = alert_view.get("SEVERITY", pd.Series(index=alert_view.index, dtype=str)).apply(_cost_command_severity_rank)
        alert_view = alert_view.sort_values(["_RANK", "VALUE_AT_RISK_USD"], ascending=[True, False])
        alert = alert_view.iloc[0]
        add(
            4,
            _cost_alert_message(alert, "SEVERITY", default="High"),
            "Alert routed",
            _cost_alert_message(alert, "ENTITY_NAME", default=top_wh),
            _cost_alert_message(alert, "MESSAGE", default="Cost Monitoring alert candidate is ready for Alert Center."),
            _cost_alert_message(alert, "SUGGESTED_ACTION", default="Route the alert to DBA / Cost owner email triage."),
            _cost_alert_message(alert, "PROOF_QUERY", default="Record the alert telemetry query."),
            "Alert Center",
        )
    else:
        add(
            4,
            "Info",
            "Alert routed",
            top_wh,
            "No Critical/High Cost & Contract alert candidate is ready.",
            "Keep monitoring; only route actionable Cost & Contract rows with telemetry.",
            "Cost Monitoring alert board.",
            "Alert Center",
        )

    add(
        5,
        "High" if not open_cost_queue.empty else "Info",
        "DBA action and measurement",
        f"{len(open_cost_queue):,} open cost action(s)",
        f"{len(open_cost_queue):,} open Cost & Contract action queue row(s) need route, baseline/current values, and closure status.",
        "Work measured actions first; keep savings estimated until post-period telemetry confirms the change.",
        "OVERWATCH_ACTION_QUEUE telemetry status, baseline/current, measured delta, and closure status.",
        "Cost & Contract > Cost Recommendations",
    )

    board = pd.DataFrame(rows).sort_values("EVENT_ORDER").reset_index(drop=True)
    summary = {
        "event_count": int(len(board)),
        "critical_high": int(board["SEVERITY"].isin(["Critical", "High"]).sum()) if not board.empty else 0,
        "top_step": str(board.iloc[0].get("INCIDENT_STEP") if not board.empty else "No incident timeline"),
        "next_action": str(board.iloc[0].get("NEXT_ACTION") if not board.empty else "Refresh cost detail."),
    }
    return summary, board


def _build_cost_monitoring_mart_operability() -> tuple[dict, pd.DataFrame]:
    rows = [
        {
            "COMPONENT": "Cost Monitoring signals",
            "STATE": "Ready",
            "DBA_USE": "Persists cost movement, Cortex quota, and change/cost signals.",
            "PROOF": "Snowflake summary facts and refresh telemetry.",
        },
        {
            "COMPONENT": "Cost incident timeline",
            "STATE": "Ready",
            "DBA_USE": "Turns cost spikes into ordered incident events for root cause, alerting, and action status.",
            "PROOF": "Timeline built from Cost Monitoring signals.",
        },
        {
            "COMPONENT": "Cost Monitoring refresh",
            "STATE": "Scheduled",
            "DBA_USE": "Runs after the control room mart so Alert Center can consume compact facts.",
            "PROOF": "Refresh order is recorded by the DBA platform team.",
        },
        {
            "COMPONENT": "Alert Center handoff",
            "STATE": "Email Ready" if DEFAULT_ALERT_EMAIL else "Config Required",
            "DBA_USE": "Routes Critical/High Cost Monitoring signals to the consolidated Alert Center.",
            "PROOF": f"Default target {alert_recipient_label(DEFAULT_ALERT_EMAIL)}; dedupes open alerts for 24 hours.",
        },
    ]
    board = pd.DataFrame(rows)
    summary = {
        "components": int(len(board)),
        "scheduled_components": int(board["STATE"].isin(["Scheduled", "Email Ready"]).sum()),
        "top_component": "Cost Monitoring refresh",
    }
    return summary, board


def _render_cost_monitoring_mart_and_incident_timeline(
    *,
    company: str,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    root_cause = st.session_state.get("cost_contract_spike_root_cause", pd.DataFrame())
    correlation = st.session_state.get("cost_contract_change_cost_correlation", pd.DataFrame())
    alert_summary, alert_board = _build_cost_monitoring_alert_rows(
        root_cause=root_cause,
        correlation=correlation,
        email_target=DEFAULT_ALERT_EMAIL,
    )
    st.session_state["cost_contract_monitoring_alert_summary"] = alert_summary
    st.session_state["cost_contract_monitoring_alerts"] = alert_board
    timeline_summary, timeline = _build_cost_incident_timeline(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        alert_rows=alert_board,
    )
    st.session_state["cost_contract_incident_timeline_summary"] = timeline_summary
    st.session_state["cost_contract_incident_timeline"] = timeline
    mart_summary, mart_board = _build_cost_monitoring_mart_operability()
    st.session_state["cost_contract_mart_operability_summary"] = mart_summary
    st.session_state["cost_contract_mart_operability"] = mart_board

    st.markdown("**Cost Monitoring Alerts & Timeline**")
    render_shell_snapshot((
        ("Alert Candidates", f"{alert_summary['alert_count']:,}"),
        ("Critical/High", f"{alert_summary['critical_high']:,}"),
        ("Timeline Events", f"{timeline_summary['event_count']:,}"),
        ("Status Lanes", f"{mart_summary['components']:,}"),
    ))

    if not alert_board.empty:
        render_priority_dataframe(
            alert_board,
            title="Alert Center-ready cost issues",
            priority_columns=[
                "SEVERITY", "ALERT_TYPE", "ENTITY_NAME", "VALUE_AT_RISK_USD",
                "MESSAGE", "SUGGESTED_ACTION", "PROOF_QUERY", "ROUTE", "EMAIL_TARGET",
            ],
            sort_by=["SEVERITY", "VALUE_AT_RISK_USD"],
            ascending=[True, False],
            raw_label="All Cost & Contract alert candidates",
            height=280,
            max_rows=8,
        )

    render_priority_dataframe(
        timeline,
        title="Cost incident timeline",
        priority_columns=[
            "EVENT_ORDER", "SEVERITY", "INCIDENT_STEP", "ENTITY",
            "EVIDENCE", "NEXT_ACTION", "PROOF_REQUIRED", "ROUTE",
        ],
        sort_by=["EVENT_ORDER"],
        ascending=[True],
        raw_label="All cost incident timeline rows",
        height=280,
        max_rows=6,
    )


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


def _load_cost_splash_query(
    mart_sql: str,
    live_sql: str,
    ttl_key: str,
    *,
    section: str = "Cost & Contract",
    allow_live_fallback: bool = True,
) -> tuple[pd.DataFrame, str, str]:
    try:
        frame = run_query_or_raise(
            mart_sql,
            ttl_key=f"{ttl_key}_mart",
            tier="historical",
            section=section,
        )
        return frame, "Fast summary", ""
    except Exception as mart_exc:
        if not allow_live_fallback:
            return pd.DataFrame(), "", f"Fast summary unavailable: {format_snowflake_error(mart_exc)}"
        try:
            frame = run_query_or_raise(
                live_sql,
                ttl_key=f"{ttl_key}_live",
                tier="historical",
                section=section,
            )
            return frame, "Live fallback", ""
        except Exception as live_exc:
            return (
                pd.DataFrame(),
                "",
                f"Fast summary unavailable: {format_snowflake_error(mart_exc)}; live fallback failed: {format_snowflake_error(live_exc)}",
            )


def _load_cost_splash_live_query(sql: str, ttl_key: str, source_label: str, *, section: str = "Cost & Contract") -> tuple[pd.DataFrame, str, str]:
    try:
        frame = run_query_or_raise(
            sql,
            ttl_key=ttl_key,
            tier="historical",
            section=section,
        )
        return frame, source_label, ""
    except Exception as exc:
        return pd.DataFrame(), "", format_snowflake_error(exc)


def _cost_splash_meta(company: str, days: int, credit_price: float) -> dict:
    return {"company": company, "days": int(days), "credit_price": float(credit_price)}


def _empty_cost_splash(company: str, days: int, credit_price: float) -> dict:
    meta = _cost_splash_meta(company, days, credit_price)
    return {
        "meta": meta,
        "loaded": False,
        "errors": [],
        "source": "",
        "cockpit": None,
        "trend": None,
        "warehouse_delta": None,
        "service_costs": None,
        "cortex": None,
        "run_rate": None,
    }


def _cached_cost_splash(company: str, days: int, credit_price: float) -> dict:
    meta = _cost_splash_meta(company, days, credit_price)
    cached = st.session_state.get(_COST_SPLASH_KEY)
    if isinstance(cached, dict) and cached.get("meta") == meta and cached.get("loaded"):
        return cached
    return _empty_cost_splash(company, days, credit_price)


def _ensure_cost_splash(company: str, days: int, credit_price: float, *, full_proof: bool = True) -> dict:
    meta = _cost_splash_meta(company, days, credit_price)
    cached = st.session_state.get(_COST_SPLASH_KEY)
    if (
        isinstance(cached, dict)
        and cached.get("meta") == meta
        and cached.get("loaded")
        and (cached.get("full_proof") or not full_proof)
    ):
        return cached

    if get_session_for_action(
        "load the Cost & Contract splash",
        surface="Cost & Contract",
        offline_note="Cost workflow navigation remains available without a live Snowflake connection.",
    ) is None:
        splash = {"meta": meta, "loaded": False, "errors": ["Snowflake connection unavailable."], "source": ""}
        st.session_state[_COST_SPLASH_KEY] = splash
        return splash

    cockpit = pd.DataFrame()
    cockpit_source = cockpit_error = ""
    if full_proof:
        cockpit, cockpit_source, cockpit_error = _load_cost_splash_query(
            build_mart_cost_cockpit_sql(company, int(days)),
            _build_cost_cockpit_sql(company, int(days)),
            f"cost_splash_cockpit_{company}_{days}",
            allow_live_fallback=full_proof,
        )
    trend = pd.DataFrame()
    trend_source = trend_error = ""
    if full_proof:
        try:
            trend_result = load_shared_service_cost_trend(
                int(days),
                company,
                credit_price=credit_price,
                ai_credit_price=get_current_ai_credit_price(),
                section="Cost & Contract",
            )
            trend = trend_result.data
            trend_source = trend_result.source
            trend_error = trend_result.message
        except Exception as exc:
            trend = pd.DataFrame()
            trend_source = ""
            trend_error = format_snowflake_error(exc)
    warehouse_delta, delta_source, delta_error = _load_cost_splash_query(
        _build_cost_splash_warehouse_delta_sql(company, int(days), mart=True),
        _build_cost_splash_warehouse_delta_sql(company, int(days), mart=False),
        f"cost_splash_warehouse_delta_{company}_{days}",
        allow_live_fallback=full_proof,
    )
    cortex, cortex_source, cortex_error = _load_cost_splash_query(
        _build_cost_splash_cortex_sql(company, int(days), get_current_ai_credit_price(), mart=True),
        _build_cost_splash_cortex_sql(company, int(days), get_current_ai_credit_price(), mart=False),
        f"cost_splash_cortex_{company}_{days}",
        allow_live_fallback=full_proof,
    )
    service_costs = pd.DataFrame()
    service_source = service_error = ""
    if full_proof:
        try:
            service_result = load_shared_service_cost_lens(
                int(days),
                company,
                credit_price=credit_price,
                ai_credit_price=get_current_ai_credit_price(),
                section="Cost & Contract",
            )
            service_costs = service_result.data
            service_source = service_result.source
            service_error = service_result.message
        except Exception as exc:
            service_costs = pd.DataFrame()
            service_source = ""
            service_error = format_snowflake_error(exc)
    run_rate = pd.DataFrame()
    run_rate_source = run_rate_error = ""
    if full_proof:
        run_rate, run_rate_source, run_rate_error = _load_cost_splash_query(
            build_mart_cost_run_rate_sql(company),
            _build_cost_run_rate_sql(company),
            f"cost_splash_run_rate_{company}",
            allow_live_fallback=full_proof,
        )
    errors = [err for err in (cockpit_error, trend_error, delta_error, cortex_error, service_error, run_rate_error) if err]
    source_parts = [src for src in (service_source, trend_source, cockpit_source, delta_source, cortex_source, run_rate_source) if src]
    splash = {
        "meta": meta,
        "loaded": True,
        "full_proof": bool(full_proof),
        "cockpit": cockpit,
        "trend": trend,
        "warehouse_delta": warehouse_delta,
        "service_costs": service_costs,
        "cortex": cortex,
        "run_rate": run_rate,
        "source": " + ".join(dict.fromkeys(source_parts)),
        "errors": errors,
    }
    st.session_state[_COST_SPLASH_KEY] = splash
    return splash


def _maybe_autoload_cost_splash(company: str, days: int, credit_price: float) -> dict:
    """Load a lightweight cost landing once after navigation; keep full telemetry explicit."""
    meta = _cost_splash_meta(company, days, credit_price)
    cached = st.session_state.get(_COST_SPLASH_KEY)
    if isinstance(cached, dict) and cached.get("meta") == meta and cached.get("loaded"):
        return cached
    if consume_section_autoload_request("Cost & Contract"):
        st.session_state[_COST_SPLASH_AUTOLOAD_SCOPE_KEY] = meta
        st.caption(
            "Cost & Contract opened fast summary facts. Refresh Cost loads official spend, "
            "warehouse ranking, Cortex spend, and supporting telemetry."
        )
        return _ensure_cost_splash(company, days, credit_price, full_proof=False)
    return _cached_cost_splash(company, days, credit_price)


def _cost_splash_summary(splash: dict, credit_price: float, days: int) -> dict:
    cockpit = splash.get("cockpit", pd.DataFrame())
    trend = splash.get("trend", pd.DataFrame())
    warehouse_delta = splash.get("warehouse_delta", pd.DataFrame())
    service_costs = splash.get("service_costs", pd.DataFrame())
    cortex = splash.get("cortex", pd.DataFrame())
    run_rate = splash.get("run_rate", pd.DataFrame())
    row = cockpit.iloc[0] if _looks_like_frame(cockpit) and not cockpit.empty else {}
    cortex_row = cortex.iloc[0] if _looks_like_frame(cortex) and not cortex.empty else {}
    run_rate_row = run_rate.iloc[0] if _looks_like_frame(run_rate) and not run_rate.empty else {}
    service_current = service_prior = 0.0
    service_current_spend = service_prior_spend = 0.0
    service_compute = service_cloud = 0.0
    active_services = 0
    top_service = "No service"
    if _looks_like_frame(service_costs) and not service_costs.empty and "CREDITS_BILLED" in service_costs.columns:
        credits = pd.to_numeric(service_costs.get("CREDITS_BILLED", pd.Series(dtype=float)), errors="coerce").fillna(0)
        prior = pd.to_numeric(service_costs.get("CREDITS_BILLED_PRIOR", pd.Series(dtype=float)), errors="coerce").fillna(0)
        current_spend = pd.to_numeric(service_costs.get("ESTIMATED_COST_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        prior_spend = pd.to_numeric(service_costs.get("PRIOR_ESTIMATED_COST_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        service_current = safe_float(credits.sum())
        service_prior = safe_float(prior.sum())
        service_current_spend = safe_float(current_spend.sum())
        service_prior_spend = safe_float(prior_spend.sum())
        service_compute = safe_float(pd.to_numeric(service_costs.get("CREDITS_USED_COMPUTE", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        service_cloud = safe_float(pd.to_numeric(service_costs.get("CREDITS_USED_CLOUD_SERVICES", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        active_services = int((credits > 0).sum())
        if active_services:
            top_service = str(service_costs.assign(_CREDITS=credits).sort_values("_CREDITS", ascending=False).iloc[0].get("SERVICE_TYPE") or "Unknown")
    official_service_loaded = _looks_like_frame(service_costs) and not service_costs.empty
    warehouse_current = warehouse_prior = 0.0
    warehouse_active = 0
    if _looks_like_frame(warehouse_delta) and not warehouse_delta.empty:
        current_series = pd.to_numeric(
            warehouse_delta.get("CURRENT_CREDITS", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0)
        prior_series = pd.to_numeric(
            warehouse_delta.get("PRIOR_CREDITS", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0)
        warehouse_current = safe_float(current_series.sum())
        warehouse_prior = safe_float(prior_series.sum())
        warehouse_active = int((current_series > 0).sum())
    current_credits = (
        service_current
        if official_service_loaded
        else safe_float(row.get("CURRENT_CREDITS", 0)) or warehouse_current
    )
    prior_credits = (
        service_prior
        if official_service_loaded
        else safe_float(row.get("PRIOR_CREDITS", 0)) or warehouse_prior
    )
    spend_delta_credits = current_credits - prior_credits
    spend = service_current_spend if official_service_loaded else credits_to_dollars(current_credits, credit_price)
    prior_spend = service_prior_spend if official_service_loaded else credits_to_dollars(prior_credits, credit_price)
    spend_delta = spend - prior_spend if official_service_loaded else credits_to_dollars(spend_delta_credits, credit_price)
    delta_pct = (spend_delta_credits / prior_credits * 100) if prior_credits > 0 else 0.0
    active_warehouses = safe_int(row.get("ACTIVE_WAREHOUSES", 0)) or warehouse_active
    top_wh = str(row.get("TOP_INCREASE_WAREHOUSE") or "")
    top_wh_delta = safe_float(row.get("TOP_INCREASE_CREDITS", 0))
    top_wh_current_credits = 0.0
    if not top_wh and _looks_like_frame(warehouse_delta) and not warehouse_delta.empty:
        top_wh = str(warehouse_delta.iloc[0].get("WAREHOUSE_NAME") or "")
    if _looks_like_frame(warehouse_delta) and not warehouse_delta.empty:
        top_wh_delta = top_wh_delta or safe_float(warehouse_delta.iloc[0].get("CREDIT_DELTA", 0))
        top_wh_current_credits = safe_float(warehouse_delta.iloc[0].get("CURRENT_CREDITS", 0))
    peak_credits = 0.0
    if _looks_like_frame(trend) and not trend.empty and "DAILY_CREDITS" in trend.columns:
        peak_credits = safe_float(trend["DAILY_CREDITS"].max())
    peak_spend = 0.0
    if _looks_like_frame(trend) and not trend.empty and "DAILY_SPEND_USD" in trend.columns:
        peak_spend = safe_float(pd.to_numeric(trend["DAILY_SPEND_USD"], errors="coerce").fillna(0).max())
    cortex_spend = safe_float(cortex_row.get("CORTEX_SPEND_USD", 0))
    projected_30d_credits = safe_float(run_rate_row.get("PROJECTED_30D_FROM_7D", 0))
    avg_7d_credits = safe_float(run_rate_row.get("AVG_DAILY_7D", 0))
    projected_30d_spend = credits_to_dollars(projected_30d_credits, credit_price)
    avg_7d_spend = credits_to_dollars(avg_7d_credits, credit_price)
    run_rate_state = str(run_rate_row.get("RUN_RATE_STATE") or "On demand")
    if not projected_30d_spend and spend:
        projected_30d_spend = safe_float(spend) / max(int(days), 1) * 30
        avg_7d_spend = safe_float(spend) / max(int(days), 1)
        run_rate_state = "Projected from loaded window"
    return {
        "has_data": current_credits > 0 or (_looks_like_frame(trend) and not trend.empty) or cortex_spend > 0,
        "current_credits": current_credits,
        "prior_credits": prior_credits,
        "spend_delta_credits": spend_delta_credits,
        "spend": spend,
        "prior_spend": prior_spend,
        "spend_delta": spend_delta,
        "avg_daily": spend / max(int(days), 1),
        "peak_day": peak_spend if peak_spend else credits_to_dollars(peak_credits, credit_price),
        "delta_pct": delta_pct,
        "cost_basis": "Official account service total" if official_service_loaded else "Warehouse metering total",
        "active_services": active_services,
        "compute_credits": service_compute,
        "cloud_services_credits": service_cloud,
        "top_service": top_service,
        "active_warehouses": active_warehouses,
        "top_warehouse": top_wh or "No warehouse",
        "top_warehouse_delta_credits": top_wh_delta,
        "top_warehouse_delta_spend": credits_to_dollars(top_wh_delta, credit_price),
        "top_warehouse_current_spend": credits_to_dollars(top_wh_current_credits, credit_price),
        "cortex_spend": cortex_spend,
        "cortex_credits": safe_float(cortex_row.get("CORTEX_CREDITS", 0)),
        "cortex_requests": safe_int(cortex_row.get("CORTEX_REQUESTS", 0)),
        "top_cortex_user": str(cortex_row.get("TOP_CORTEX_USER") or "No Cortex user"),
        "top_cortex_user_spend": safe_float(cortex_row.get("TOP_CORTEX_USER_SPEND_USD", 0)),
        "projected_30d_spend": projected_30d_spend,
        "avg_7d_spend": avg_7d_spend,
        "run_rate_state": run_rate_state,
        "yoy_state": str(run_rate_row.get("YOY_STATE") or "On demand"),
        "yoy_7d_pct": _nullable_float(run_rate_row, "YOY_7D_PCT") if _looks_like_frame(run_rate) and not run_rate.empty else None,
    }


def _cost_command_lanes(splash: dict, *, credit_price: float, days: int) -> list[dict[str, str]]:
    """Return Cost & Contract first-paint lanes from loaded state or honest placeholders."""
    if not splash.get("loaded"):
        return [
            {
                "label": "Credits / dollars",
                "value": "On demand",
                "state": "Metering",
                "detail": "Refresh Cost loads official service spend or warehouse metering.",
            },
            {
                "label": "Spend movement",
                "value": "On demand",
                "state": "Delta",
                "detail": "Compares selected window to the prior window before tuning.",
            },
            {
                "label": "30d run rate",
                "value": "On demand",
                "state": "Forecast",
                "detail": "Projected burn appears after cost facts load.",
            },
            {
                "label": "Cortex dollars",
                "value": "On demand",
                "state": "AI",
                "detail": "AI usage uses the configured Cortex credit rate and fact rows.",
            },
            {
                "label": "Top warehouse",
                "value": "On demand",
                "state": "Driver",
                "detail": "Warehouse movement is ranked after metering telemetry loads.",
            },
            {
                "label": "Cloud services",
                "value": "On demand",
                "state": "Ratio",
                "detail": "Official service lens separates compute and cloud-services cost.",
            },
            {
                "label": "Action queue",
                "value": "On demand",
                "state": "Savings",
                "detail": "Measured fixes and measured value load from the queue.",
            },
            {
                "label": "Measurement basis",
                "value": "On demand",
                "state": "Trust",
                "detail": "Exact totals and allocated estimates stay labeled separately.",
            },
        ]

    summary = _cost_splash_summary(splash, credit_price, days)
    queue = splash.get("queue", pd.DataFrame())
    action_summary = _cost_snapshot_action_summary(queue if _looks_like_frame(queue) else pd.DataFrame())
    cloud_ratio = (
        safe_float(summary.get("cloud_services_credits")) / max(safe_float(summary.get("compute_credits")), 1.0) * 100
        if safe_float(summary.get("compute_credits")) or safe_float(summary.get("cloud_services_credits"))
        else 0.0
    )
    return [
        {
            "label": "Credits / dollars",
            "value": f"{safe_float(summary.get('current_credits')):,.1f} cr / ${safe_float(summary.get('spend')):,.0f}",
            "state": "Metering",
            "detail": str(summary.get("cost_basis") or "Warehouse metering total"),
        },
        {
            "label": "Spend movement",
            "value": f"{safe_float(summary.get('delta_pct')):+.1f}% / ${safe_float(summary.get('spend_delta')):+,.0f}",
            "state": "Delta",
            "detail": f"Prior spend: ${safe_float(summary.get('prior_spend')):,.0f}.",
        },
        {
            "label": "30d run rate",
            "value": f"${safe_float(summary.get('projected_30d_spend')):,.0f}",
            "state": str(summary.get("run_rate_state") or "Forecast"),
            "detail": f"Average/day: ${safe_float(summary.get('avg_daily')):,.0f}.",
        },
        {
            "label": "Cortex dollars",
            "value": f"${safe_float(summary.get('cortex_spend')):,.0f}",
            "state": "AI",
            "detail": f"Top user: {summary.get('top_cortex_user')}; {safe_int(summary.get('cortex_requests')):,} request(s).",
        },
        {
            "label": "Top warehouse",
            "value": str(summary.get("top_warehouse") or "No warehouse"),
            "state": "Driver",
            "detail": f"{safe_float(summary.get('top_warehouse_delta_credits')):+,.1f} cr / ${safe_float(summary.get('top_warehouse_delta_spend')):+,.0f}.",
        },
        {
            "label": "Cloud services",
            "value": f"{cloud_ratio:,.1f}%",
            "state": "Ratio",
            "detail": f"{safe_float(summary.get('cloud_services_credits')):,.1f} cloud-services credits.",
        },
        {
            "label": "Action queue",
            "value": f"{safe_int(action_summary.get('open_actions')):,} open / ${safe_float(action_summary.get('estimated_savings')):,.0f}",
            "state": "Savings",
            "detail": f"{safe_int(action_summary.get('high_actions')):,} critical/high action(s).",
        },
        {
            "label": "Measurement basis",
            "value": str(summary.get("cost_basis") or "Metering"),
            "state": "Trust",
            "detail": "Official totals, metered totals, and allocated attribution remain separate.",
        },
    ]


def _slide_number(value: float, suffix: str = "") -> str:
    return f"{safe_float(value):,.0f}{suffix}"


def _cost_snapshot_action_summary(queue: pd.DataFrame | None) -> dict:
    open_cost_queue = _open_cost_action_frame(queue)
    if open_cost_queue.empty:
        return {"open_actions": 0, "high_actions": 0, "estimated_savings": 0.0}
    severity = open_cost_queue.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.title()
    savings = pd.to_numeric(open_cost_queue.get("EST_MONTHLY_SAVINGS", pd.Series(dtype=float)), errors="coerce").fillna(0)
    return {
        "open_actions": int(len(open_cost_queue)),
        "high_actions": int(severity.isin(["Critical", "High"]).sum()),
        "estimated_savings": safe_float(savings.sum()),
    }


def _render_cost_load_contract(splash: dict, *, days: int) -> None:
    if splash.get("loaded"):
        defer_source_note(f"Cost overview window: {int(days)} days.")


def _render_cost_splash(splash: dict, *, company: str, days: int, credit_price: float) -> None:
    st.markdown("**Cost Overview**")
    _render_cost_load_contract(splash, days=int(days))
    if not splash.get("loaded"):
        if splash.get("errors"):
            for err in splash.get("errors", [])[:2]:
                defer_source_note(str(err))
        return

    summary = _cost_splash_summary(splash, credit_price, days)
    if splash.get("errors") and not summary["has_data"]:
        st.warning("Cost splash could not load from the fast summary or bounded fallback for this role.")
        for err in splash.get("errors", [])[:2]:
            defer_source_note(str(err))
        return

    _render_cost_splash_narrative(summary, days=int(days))
    _render_cost_splash_next_move(summary)
    _render_cost_executive_decision_stack(summary)

    if splash.get("source"):
        telemetry_note = (
            "Cost trend and forecast are loaded."
            if not splash.get("full_proof")
            else "Full overview is loaded."
        )
        defer_source_note(f"{telemetry_note}")

    trend = splash.get("trend", pd.DataFrame())
    warehouse_delta = splash.get("warehouse_delta", pd.DataFrame())
    st.caption("Use each chart's Data view to inspect exact rows, then return to the chart.")
    _render_cost_chart_with_data_toggle(
        "Spend Trend",
        "cost_contract_spend_trend",
        lambda: _render_spend_trend_chart(trend, credit_price),
        _cost_spend_trend_rows(trend, credit_price),
        priority_columns=["USAGE_DATE", "DAILY_CREDITS", "SPEND_USD", "ROLLING_SPEND_USD"],
        sort_by=["USAGE_DATE"],
        max_rows=30,
    )
    _render_cost_chart_with_data_toggle(
        "Warehouse Ranking",
        "cost_contract_warehouse_ranking",
        lambda: _render_warehouse_ranking_chart(warehouse_delta, credit_price),
        _cost_warehouse_ranking_rows(warehouse_delta, credit_price, limit=24),
        priority_columns=[
            "WAREHOUSE_NAME", "CURRENT_SPEND_USD", "PRIOR_SPEND_USD",
            "DELTA_SPEND_USD", "CURRENT_CREDITS", "PRIOR_CREDITS", "PCT_DELTA",
        ],
        sort_by=["CURRENT_SPEND_USD"],
        max_rows=24,
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
        try:
            st.session_state["cost_contract_cockpit"] = run_query(
                build_mart_cost_cockpit_sql(company, int(days)),
                ttl_key=f"cost_contract_cockpit_mart_{company}_{days}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_cockpit_source"] = "Fast warehouse cost summary"
            st.session_state["cost_contract_cockpit_meta"] = with_loaded_at(
                {"company": company, "days": int(days)},
                source="Fast warehouse cost summary",
            )
            st.session_state["cost_contract_cockpit_error"] = ""
        except Exception as mart_exc:
            try:
                st.session_state["cost_contract_cockpit"] = run_query(
                    _build_cost_cockpit_sql(company, int(days)),
                    ttl_key=f"cost_contract_cockpit_{company}_{days}",
                    tier="standard",
                    section="Cost & Contract",
                )
                st.session_state["cost_contract_cockpit_source"] = (
                    "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                )
                st.session_state["cost_contract_cockpit_meta"] = with_loaded_at(
                    {"company": company, "days": int(days)},
                    source="Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                )
                st.session_state["cost_contract_cockpit_error"] = ""
            except Exception as exc:
                st.session_state["cost_contract_cockpit_error"] = (
                    f"Fast summary unavailable: {format_snowflake_error(mart_exc)}; "
                    f"live fallback failed: {format_snowflake_error(exc)}"
                )
                st.session_state["cost_contract_cockpit"] = pd.DataFrame()
                st.session_state["cost_contract_queue"] = pd.DataFrame()
        try:
            st.session_state["cost_contract_run_rate"] = run_query(
                build_mart_cost_run_rate_sql(company),
                ttl_key=f"cost_contract_run_rate_mart_{company}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_run_rate_source"] = "Fast run-rate summary"
            st.session_state["cost_contract_run_rate_error"] = ""
        except Exception as mart_exc:
            try:
                st.session_state["cost_contract_run_rate"] = run_query(
                    _build_cost_run_rate_sql(company),
                    ttl_key=f"cost_contract_run_rate_live_{company}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["cost_contract_run_rate_source"] = (
                    "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                )
                st.session_state["cost_contract_run_rate_error"] = ""
            except Exception as exc:
                st.session_state["cost_contract_run_rate"] = pd.DataFrame()
                st.session_state["cost_contract_run_rate_source"] = ""
                st.session_state["cost_contract_run_rate_error"] = (
                    f"Fast summary unavailable: {format_snowflake_error(mart_exc)}; "
                    f"live fallback failed: {format_snowflake_error(exc)}"
                )
        try:
            st.session_state["cost_contract_queue"] = load_action_queue(session)
            st.session_state["cost_contract_queue_error"] = ""
        except Exception as exc:
            st.session_state["cost_contract_queue"] = pd.DataFrame()
            st.session_state["cost_contract_queue_error"] = format_snowflake_error(exc)
        try:
            st.session_state["cost_contract_attribution_reconciliation"] = run_query_or_raise(
                build_cost_reconciliation_sql(int(days), prefer_query_attribution=True),
                ttl_key=f"cost_contract_attribution_reconciliation_{company}_{days}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_attribution_error"] = ""
            st.session_state["cost_contract_attribution_source"] = (
                "SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY + WAREHOUSE_METERING_HISTORY"
            )
        except Exception as exc:
            st.session_state["cost_contract_attribution_reconciliation"] = pd.DataFrame()
            st.session_state["cost_contract_attribution_error"] = format_snowflake_error(exc)
            st.session_state["cost_contract_attribution_source"] = ""
        try:
            service_result = load_shared_service_cost_lens(
                int(days),
                company,
                credit_price=credit_price,
                ai_credit_price=get_current_ai_credit_price(),
                force=True,
                section="Cost & Contract",
            )
            st.session_state["cost_contract_service_lens"] = service_result.data
            st.session_state["cost_contract_service_lens_error"] = service_result.message
            st.session_state["cost_contract_service_lens_source"] = service_result.source
        except Exception as exc:
            st.session_state["cost_contract_service_lens"] = pd.DataFrame()
            st.session_state["cost_contract_service_lens_error"] = format_snowflake_error(exc)
            st.session_state["cost_contract_service_lens_source"] = ""
        try:
            st.session_state["cost_contract_efficiency_summary"] = run_query_or_raise(
                build_cost_efficiency_summary_sql(
                    int(days),
                    company=company,
                    credit_price=credit_price,
                    prefer_query_attribution=True,
                ),
                ttl_key=f"cost_contract_efficiency_summary_{company}_{days}_{credit_price}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_efficiency_summary_error"] = ""
        except Exception as exc:
            st.session_state["cost_contract_efficiency_summary"] = pd.DataFrame()
            st.session_state["cost_contract_efficiency_summary_error"] = format_snowflake_error(exc)
        try:
            st.session_state["cost_contract_warehouse_efficiency"] = run_query_or_raise(
                build_warehouse_efficiency_sql(
                    int(days),
                    company=company,
                    credit_price=credit_price,
                    top=50,
                    prefer_query_attribution=True,
                ),
                ttl_key=f"cost_contract_warehouse_efficiency_{company}_{days}_{credit_price}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_warehouse_efficiency_error"] = ""
        except Exception as exc:
            st.session_state["cost_contract_warehouse_efficiency"] = pd.DataFrame()
            st.session_state["cost_contract_warehouse_efficiency_error"] = format_snowflake_error(exc)
        try:
            st.session_state["cost_contract_clustering_cost"] = run_query_or_raise(
                build_clustering_cost_sql(
                    int(days),
                    company=company,
                    credit_price=credit_price,
                    top=50,
                ),
                ttl_key=f"cost_contract_clustering_cost_{company}_{days}_{credit_price}",
                tier="historical",
                section="Cost & Contract",
            )
            st.session_state["cost_contract_clustering_cost_error"] = ""
        except Exception as exc:
            st.session_state["cost_contract_clustering_cost"] = pd.DataFrame()
            st.session_state["cost_contract_clustering_cost_error"] = format_snowflake_error(exc)
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
