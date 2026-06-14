"""Executive Landing glance page.

COCO/Kiro contract: this route is a boardroom glance page, not a workflow hub.
It shows six leadership KPIs immediately, then one trend chart and one action
table. Deeper investigation starts from the owning sections.
"""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULTS, DEFAULT_COMPANY, DEFAULT_DAY_WINDOW, DEFAULT_ENVIRONMENT, DAY_WINDOW_OPTIONS, ENVIRONMENT_CONFIG
from sections.shell_helpers import render_shell_status_strip, render_signal_lane_board
from utils.command_board import board_rows, load_or_reuse_command_board, load_setup_readiness


_BRIEF_MODE_KEY = "_executive_landing_brief_mode"
_FULL_WORKSPACE_KEY = "_executive_landing_full_workspace_requested"
_FULL_WORKSPACE_STATE_KEYS = ("executive_landing_snapshot",)
_PLATFORM_SUMMARY_KEY = "executive_landing_platform_summary"
_COMMAND_BOARD_KEY = "executive_landing_command_board"
_COMMAND_BOARD_META_KEY = "executive_landing_command_board_meta"
_COMMAND_BOARD_REFRESH_MARKER_KEY = "executive_landing_command_board_refresh_marker"
_DEFAULT_MONTHLY_BUDGET_USD = 50_000.0


def _active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    env = str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return env if env in ENVIRONMENT_CONFIG else DEFAULT_ENVIRONMENT


def _credit_price() -> float:
    try:
        return float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)) or 3.68)
    except (TypeError, ValueError):
        return 3.68


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        number = float(value if value is not None else default)
        return default if number != number else number
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(round(float(value if value is not None else default)))
    except (TypeError, ValueError):
        return default


def _money(value: object) -> str:
    return f"${_safe_float(value):,.0f}"


def _window_days() -> int:
    selected_days = st.session_state.get("executive_landing_window", DEFAULT_DAY_WINDOW)
    try:
        days = int(selected_days)
    except (TypeError, ValueError):
        days = int(DEFAULT_DAY_WINDOW)
    if days in DAY_WINDOW_OPTIONS:
        return max(1, days)
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return max(1, (end - start).days + 1)
    return max(1, int(DEFAULT_DAY_WINDOW))


def _summary() -> dict:
    summary = st.session_state.get(_PLATFORM_SUMMARY_KEY)
    return dict(summary) if isinstance(summary, dict) else {}


def _board():
    board = st.session_state.get(_COMMAND_BOARD_KEY)
    return board


def _load_command_board() -> None:
    days = _window_days()
    company = _active_company()
    environment = _active_environment()
    load_or_reuse_command_board(
        data_key=_COMMAND_BOARD_KEY,
        summary_key=_PLATFORM_SUMMARY_KEY,
        meta_key=_COMMAND_BOARD_META_KEY,
        refresh_marker_key=_COMMAND_BOARD_REFRESH_MARKER_KEY,
        company=company,
        environment=environment,
        days=days,
    )


def _monthly_budget() -> float:
    return _safe_float(st.session_state.get("executive_monthly_budget_usd"), _DEFAULT_MONTHLY_BUDGET_USD)


def _current_spend(summary: dict) -> float:
    return _safe_float(summary.get("current_cost_usd")) or _safe_float(summary.get("current_credits")) * _credit_price()


def _prior_spend(summary: dict) -> float:
    return _safe_float(summary.get("prior_cost_usd")) or _safe_float(summary.get("prior_credits")) * _credit_price()


def _trend_symbol(current: float, prior: float, *, reverse_good: bool = True) -> str:
    if not prior:
        return "flat"
    pct = (current - prior) / abs(prior) * 100
    if abs(pct) < 3:
        return "flat"
    if pct > 0:
        return "up" if not reverse_good else "up risk"
    return "down" if reverse_good else "down risk"


def _pipeline_sla_pct(summary: dict) -> float:
    return _safe_float(
        summary.get("pipeline_sla_compliance_pct")
        or st.session_state.get("executive_pipeline_sla_pct"),
        0.0,
    )


def _oldest_alert_age(summary: dict) -> str:
    text = str(summary.get("oldest_alert_age") or st.session_state.get("executive_oldest_alert_age") or "").strip()
    return text or "Not loaded"


def _executive_glance_kpis() -> tuple[dict[str, str], ...]:
    summary = _summary()
    days = _window_days()
    spend = _current_spend(summary)
    prior = _prior_spend(summary)
    budget = _monthly_budget()
    budget_pct = (spend / budget * 100) if budget else 0.0
    daily_burn = spend / days if spend else 0.0
    prior_daily = prior / days if prior else 0.0
    critical_high = _safe_int(summary.get("critical_high_alerts"))
    health_score = _safe_int(summary.get("score"), 0)
    open_actions = _safe_int(summary.get("open_actions"))
    high_actions = _safe_int(summary.get("high_actions"))
    sla_pct = _pipeline_sla_pct(summary)
    spend_state = "Over budget" if budget and budget_pct >= 100 else _trend_symbol(spend, prior)
    burn_state = "Anomaly" if prior_daily and daily_burn > prior_daily * 1.25 else _trend_symbol(daily_burn, prior_daily)
    return (
        {
            "label": "Total spend vs budget",
            "value": f"{_money(spend)} / {_money(budget)}",
            "state": f"{budget_pct:,.0f}%",
            "detail": f"{spend_state}; compute rate ${_credit_price():.2f}/credit.",
        },
        {
            "label": "Daily burn rate",
            "value": _money(daily_burn),
            "state": burn_state,
            "detail": f"Today/current-window average vs 7d/prior average {_money(prior_daily)}.",
        },
        {
            "label": "Open critical/high alerts",
            "value": f"{critical_high:,}",
            "state": "Risk",
            "detail": f"Oldest age: {_oldest_alert_age(summary)}.",
        },
        {
            "label": "Pipeline SLA compliance",
            "value": f"{sla_pct:,.1f}%" if sla_pct else "Not loaded",
            "state": "SLA",
            "detail": "Percent of configured tables meeting freshness target.",
        },
        {
            "label": "Platform Operating Score",
            "value": f"{health_score}/100" if health_score else "Not loaded",
            "state": str(summary.get("state") or "Evidence"),
            "detail": str(summary.get("cap_reason") or "Weighted cost, alert, action, and freshness posture."),
        },
        {
            "label": "Active issues in queue",
            "value": f"{open_actions:,}",
            "state": f"{high_actions:,} high",
            "detail": "Owner-routed actions by severity; drill from DBA Control Room or Alert Center.",
        },
    )


def _spend_trend_points() -> list[float]:
    summary = _summary()
    spend = _current_spend(summary)
    prior = _prior_spend(summary)
    if not spend and not prior:
        return [0, 0, 0, 0, 0, 0, 0]
    start = prior / 7.0 if prior else spend / 8.0
    end = spend / 7.0 if spend else start
    step = (end - start) / 6.0
    return [round(max(0.0, start + step * idx), 2) for idx in range(7)]


def _top_action_rows() -> list[dict[str, object]]:
    summary = _summary()
    critical_high = _safe_int(summary.get("critical_high_alerts"))
    open_actions = _safe_int(summary.get("open_actions"))
    high_actions = _safe_int(summary.get("high_actions"))
    spend = _current_spend(summary)
    prior = _prior_spend(summary)
    rows = [
        {
            "Priority": 1,
            "Action": "Resolve critical/high alert backlog",
            "Owner": "DBA On-Call",
            "Due": "Today" if critical_high else "Watch",
            "Impact": f"{critical_high:,} critical/high open",
        },
        {
            "Priority": 2,
            "Action": "Work active owner action queue",
            "Owner": "DBA Lead",
            "Due": "Today" if high_actions else "This week",
            "Impact": f"{open_actions:,} open / {high_actions:,} high",
        },
        {
            "Priority": 3,
            "Action": "Explain spend movement",
            "Owner": "FinOps / DBA",
            "Due": "Today" if spend > prior and prior else "Weekly review",
            "Impact": f"{_money(spend - prior)} delta",
        },
        {
            "Priority": 4,
            "Action": "Verify pipeline freshness SLA",
            "Owner": "Data Engineering",
            "Due": "Today",
            "Impact": f"{_pipeline_sla_pct(summary):,.1f}% compliance" if _pipeline_sla_pct(summary) else "SLA mart not loaded",
        },
        {
            "Priority": 5,
            "Action": "Refresh executive observability mart",
            "Owner": "OVERWATCH Maintainer",
            "Due": "Next refresh",
            "Impact": "Keeps the glance page defensible",
        },
    ]
    return rows[:5]


def _executive_summary_text() -> str:
    summary = _summary()
    spend = _current_spend(summary)
    budget = _monthly_budget()
    budget_pct = (spend / budget * 100) if budget else 0.0
    critical_high = _safe_int(summary.get("critical_high_alerts"))
    sla_pct = _pipeline_sla_pct(summary)
    health_score = _safe_int(summary.get("score"), 0)
    return (
        f"Snowflake spend is at {_money(spend)} of {_money(budget)} budget ({budget_pct:,.0f}%). "
        f"{critical_high:,} critical/high alerts are open, oldest is {_oldest_alert_age(summary)}. "
        f"Pipeline SLA compliance is {sla_pct:,.1f}%; platform health score is {health_score}/100."
    )


def _chart_frame(panel: str, metric: str, value_column: str = "VALUE_USD"):
    rows = board_rows(_board(), panel, metric)
    if rows.empty:
        return rows
    value_col = value_column if value_column in rows.columns else "VALUE"
    label_col = "DIMENSION"
    view = rows[[label_col, value_col]].copy()
    view[value_col] = view[value_col].fillna(0)
    view = view.rename(columns={label_col: "Label", value_col: metric}).set_index("Label")
    return view


def _render_status_strip() -> None:
    render_shell_status_strip(
        state="Glance",
        headline="Executive command board",
        detail="Spend, burn, alerts, SLA, platform score, and owner queue.",
    )


def _render_kpis() -> None:
    render_signal_lane_board("Executive Glance KPIs", _executive_glance_kpis(), max_lanes=6)


def _render_spend_trend() -> None:
    st.markdown("**7-Day Spend Trend**")
    daily = _chart_frame("DAILY_COST", "Daily Spend")
    if getattr(daily, "empty", True):
        st.line_chart({"Daily spend": _spend_trend_points()})
        return
    st.line_chart(daily)


def _render_observability_summary() -> None:
    st.markdown("**Observability Summary**")
    monthly = _chart_frame("MONTHLY_COST", "Monthly Spend")
    daily_spend = _chart_frame("DAILY_COST", "Daily Spend")
    workload = _chart_frame("DAILY_WORKLOAD", "P95 Runtime", "VALUE")
    drivers = _chart_frame("COST_DRIVER", "Cost Drivers")
    query_types = _chart_frame("QUERY_TYPE", "Queries by Type", "VALUE")
    query_database = _chart_frame("QUERY_DATABASE", "Queries by Database", "VALUE")
    exec_status = _chart_frame("EXEC_STATUS", "Execution Status", "VALUE")
    pressure = _chart_frame("WAREHOUSE_PRESSURE", "Queue Seconds", "VALUE")
    spill = _chart_frame("WAREHOUSE_PRESSURE", "Remote Spill GB", "VALUE")

    st.caption("Credits, dollars, query health, failures, queueing, spill, and top workload mix in one executive view.")
    render_signal_lane_board("Snowflake Observability Wall", _observability_wall_lanes(), max_lanes=12)

    left, middle, right = st.columns(3)
    with left:
        st.caption("Daily spend")
        if getattr(daily_spend, "empty", True):
            st.line_chart({"Daily spend": _spend_trend_points()})
        else:
            st.line_chart(daily_spend)
    with middle:
        st.caption("Monthly spend")
        if getattr(monthly, "empty", True):
            st.info("Monthly spend waits on MART_EXECUTIVE_OBSERVABILITY.")
        else:
            st.bar_chart(monthly)
    with right:
        st.caption("Runtime pressure")
        if getattr(workload, "empty", True):
            st.info("Runtime trend waits on FACT_QUERY_HOURLY.")
        else:
            st.line_chart(workload)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.caption("Top cost drivers")
        if getattr(drivers, "empty", True):
            st.info("Driver ranking not loaded.")
        else:
            st.dataframe(drivers.reset_index().head(5), hide_index=True, width="stretch")
    with c2:
        st.caption("Query mix")
        if getattr(query_types, "empty", True):
            st.info("Query type mix not loaded.")
        else:
            st.bar_chart(query_types.head(8))
    with c3:
        st.caption("Database mix")
        if getattr(query_database, "empty", True):
            st.info("Database mix not loaded.")
        else:
            st.bar_chart(query_database.head(8))
    with c4:
        st.caption("Execution status")
        if getattr(exec_status, "empty", True):
            st.info("Execution status not loaded.")
        else:
            st.bar_chart(exec_status.head(8))

    p1, p2 = st.columns(2)
    with p1:
        st.caption("Warehouse queue")
        if getattr(pressure, "empty", True):
            st.info("Warehouse pressure not loaded.")
        else:
            st.bar_chart(pressure.head(8))
    with p2:
        st.caption("Warehouse spill")
        if getattr(spill, "empty", True):
            st.info("Spill pressure not loaded.")
        else:
            st.bar_chart(spill.head(8))


def _observability_wall_lanes() -> tuple[dict[str, str], ...]:
    summary = _summary()
    return (
        {
            "label": "Credits used",
            "value": f"{_safe_float(summary.get('current_credits')):,.1f}",
            "state": _money(summary.get("current_cost_usd")),
            "detail": "Official warehouse metering, dollarized at the configured compute rate.",
        },
        {
            "label": "Cortex dollars",
            "value": _money(summary.get("cortex_cost_usd")),
            "state": "AI",
            "detail": "Cortex spend is separated from warehouse compute.",
        },
        {
            "label": "Queries",
            "value": f"{_safe_int(summary.get('total_queries')):,}",
            "state": f"{_safe_int(summary.get('failed_queries')):,} failed",
            "detail": "Query count, failures, and status mix are all sourced from query facts.",
        },
        {
            "label": "P95 runtime",
            "value": f"{_safe_float(summary.get('p95_runtime_sec')):,.1f}s",
            "state": "Runtime",
            "detail": "High p95 points to degraded workloads before users complain.",
        },
        {
            "label": "Queue time",
            "value": f"{_safe_float(summary.get('queue_seconds')) / 60.0:,.1f}m",
            "state": "Capacity",
            "detail": f"Top queued warehouse: {summary.get('top_queue_warehouse') or 'Not loaded'}.",
        },
        {
            "label": "Remote spill",
            "value": f"{_safe_float(summary.get('remote_spill_gb')):,.1f} GB",
            "state": "Memory",
            "detail": f"Top spill warehouse: {summary.get('top_spill_warehouse') or 'Not loaded'}.",
        },
        {
            "label": "Task failures",
            "value": f"{_safe_int(summary.get('failed_tasks')):,}",
            "state": "Pipeline",
            "detail": "Failed task runs route into Workload Operations and DBA Control Room.",
        },
        {
            "label": "Open alerts",
            "value": f"{_safe_int(summary.get('critical_high_alerts')):,}",
            "state": "Critical/high",
            "detail": "Alert pressure is ranked before lower-value optimization work.",
        },
        {
            "label": "Open actions",
            "value": f"{_safe_int(summary.get('open_actions')):,}",
            "state": f"{_safe_int(summary.get('high_actions')):,} high",
            "detail": "Owner-routed queue items with evidence and verification.",
        },
        {
            "label": "Storage",
            "value": f"{_safe_float(summary.get('storage_tb')):,.1f} TB",
            "state": _money(summary.get("storage_cost_usd")),
            "detail": "Storage pressure is visible even when Cost & Contract is not opened.",
        },
        {
            "label": "Top cost driver",
            "value": str(summary.get("top_cost_driver") or "Not loaded")[:28],
            "state": _money(summary.get("top_cost_driver_usd")),
            "detail": "Largest current cost driver in the selected scope.",
        },
        {
            "label": "Freshness",
            "value": f"{_safe_int(summary.get('freshness_sources')):,}",
            "state": f"{_safe_int(summary.get('stale_sources')):,} stale",
            "detail": "Delayed telemetry is called out before action.",
        },
    )


def _render_top_actions() -> None:
    st.markdown("**Top 5 Action Items**")
    st.dataframe(_top_action_rows(), hide_index=True, width="stretch")


def _render_copy_summary() -> None:
    summary = _executive_summary_text()
    if st.button("Copy Executive Summary", key="executive_landing_copy_summary", width="stretch"):
        st.session_state["executive_landing_copied_summary"] = summary
    if st.session_state.get("executive_landing_copied_summary"):
        st.code(st.session_state["executive_landing_copied_summary"], language="text")


def _render_setup_readiness() -> None:
    readiness = load_setup_readiness(use_live=bool(st.session_state.get("_refresh_salt_global")))
    st.markdown("**Setup Readiness**")
    if getattr(readiness, "empty", True):
        st.info("Setup readiness contract is not loaded.")
        return
    state_col = "MIGRATION_STATE" if "MIGRATION_STATE" in readiness.columns else "STATE"
    blocked = 0
    drift = 0
    ready = 0
    try:
        states = readiness[state_col].fillna("").astype(str).str.upper()
        blocked = int(states.str.contains("BLOCK|MISSING|NOT CHECKED", regex=True).sum())
        drift = int(states.str.contains("DRIFT", regex=False).sum())
        ready = int(states.str.contains("READY", regex=False).sum())
    except Exception:
        pass
    render_signal_lane_board(
        "Snowflake Setup Health",
        (
            {
                "label": "Ready contracts",
                "value": f"{ready:,}",
                "state": "Ready",
                "detail": "Objects or setup contracts that match the current app expectation.",
            },
            {
                "label": "Blocked / unknown",
                "value": f"{blocked:,}",
                "state": "Setup",
                "detail": "Deploy or validate setup SQL before trusting production evidence.",
            },
            {
                "label": "Version drift",
                "value": f"{drift:,}",
                "state": "Migration",
                "detail": "Rerun matching migrations before presenting executive numbers.",
            },
        ),
        max_lanes=3,
    )
    priority = readiness.head(8)
    st.dataframe(priority, hide_index=True, width="stretch")


def render() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.session_state.setdefault("executive_landing_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _load_command_board()
    _render_status_strip()
    _render_kpis()
    _render_spend_trend()
    _render_observability_summary()
    _render_top_actions()
    _render_setup_readiness()
    _render_copy_summary()
