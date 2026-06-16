"""Executive Landing glance page.

Production contract: this route is a boardroom glance page, not a workflow hub.
It shows six leadership KPIs immediately, then one trend chart and one action
table. Deeper investigation starts from the owning sections.
"""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULTS, DEFAULT_COMPANY, DEFAULT_DAY_WINDOW, DEFAULT_ENVIRONMENT, DAY_WINDOW_OPTIONS, ENVIRONMENT_CONFIG
from sections.shell_helpers import render_signal_lane_board
from utils.command_board import board_rows, load_or_reuse_command_board


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
    return text or "On demand"


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
    failed_tasks = _safe_int(summary.get("failed_tasks"))
    risk_signals = critical_high + failed_tasks
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
            "value": f"{sla_pct:,.1f}%" if sla_pct else "On demand",
            "state": "SLA",
            "detail": "Percent of configured tables meeting the service target.",
        },
        {
            "label": "Platform risk signals",
            "value": f"{risk_signals:,}",
            "state": "Review" if risk_signals else "Stable",
            "detail": f"{critical_high:,} critical/high alert(s) and {failed_tasks:,} failed task(s).",
        },
        {
            "label": "Active issues in queue",
            "value": f"{open_actions:,}",
            "state": f"{high_actions:,} high",
            "detail": "Routed actions by severity; drill from DBA Control Room or Alert Center.",
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
            "Route": "DBA On-Call",
            "Due": "Today" if critical_high else "Watch",
            "Impact": f"{critical_high:,} critical/high open",
        },
        {
            "Priority": 2,
            "Action": "Work active action queue",
            "Route": "DBA Lead",
            "Due": "Today" if high_actions else "This week",
            "Impact": f"{open_actions:,} open / {high_actions:,} high",
        },
        {
            "Priority": 3,
            "Action": "Explain spend movement",
            "Route": "FinOps / DBA",
            "Due": "Today" if spend > prior and prior else "Weekly review",
            "Impact": f"{_money(spend - prior)} delta",
        },
        {
            "Priority": 4,
            "Action": "Review pipeline SLA",
            "Route": "Data Engineering",
            "Due": "Today",
            "Impact": f"{_pipeline_sla_pct(summary):,.1f}% compliance" if _pipeline_sla_pct(summary) else "SLA data on demand",
        },
        {
            "Priority": 5,
            "Action": "Review warehouse pressure",
            "Route": "DBA Lead",
            "Due": "Today" if _safe_float(summary.get("queue_seconds")) or _safe_float(summary.get("remote_spill_gb")) else "Watch",
            "Impact": f"{_safe_float(summary.get('queue_seconds')) / 60.0:,.1f}m queued / {_safe_float(summary.get('remote_spill_gb')):,.1f} GB spill",
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
    return (
        f"Snowflake spend is at {_money(spend)} of {_money(budget)} budget ({budget_pct:,.0f}%). "
        f"{critical_high:,} critical/high alerts are open, oldest is {_oldest_alert_age(summary)}. "
        f"Pipeline SLA compliance is {sla_pct:,.1f}%."
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


def _altair():
    import altair as alt

    return alt


def _chart_records(frame, value_name: str, fallback_points: list[float] | None = None) -> list[dict[str, object]]:
    if getattr(frame, "empty", True):
        points = fallback_points if fallback_points is not None else [0.0]
        if len(points) > 1:
            labels = [f"D-{len(points) - idx - 1}" if idx < len(points) - 1 else "Today" for idx in range(len(points))]
        else:
            labels = ["Current"]
        return [{"Label": label, value_name: _safe_float(value)} for label, value in zip(labels, points)]
    rows = frame.reset_index().copy()
    value_columns = [column for column in rows.columns if column != "Label"]
    source_value = value_columns[0] if value_columns else value_name
    if source_value not in rows.columns:
        rows[source_value] = 0.0
    rows[value_name] = rows[source_value].map(_safe_float)
    rows["Label"] = rows["Label"].astype(str)
    return rows[["Label", value_name]].to_dict("records")


def _configure_chart(chart):
    return (
        chart.configure_view(strokeWidth=0)
        .configure_axis(
            gridColor="rgba(0,104,183,0.10)",
            labelColor="#31566b",
            titleColor="#31566b",
            domainColor="rgba(0,104,183,0.22)",
            tickColor="rgba(0,104,183,0.22)",
            labelFontSize=10,
            titleFontSize=11,
        )
        .configure_legend(
            labelColor="#31566b",
            titleColor="#31566b",
            orient="bottom",
        )
    )


def _render_line_panel(title: str, frame, *, fallback_points: list[float] | None = None, value_name: str = "Value") -> None:
    alt = _altair()
    rows = _chart_records(frame, value_name, fallback_points)
    st.markdown(f'<div class="ow-chart-title">{title}</div>', unsafe_allow_html=True)
    base = alt.Chart(alt.Data(values=rows)).encode(
        x=alt.X(
            "Label:N",
            title=None,
            axis=alt.Axis(labelAngle=-35, labelLimit=92, labelOverlap=True),
        ),
        y=alt.Y(f"{value_name}:Q", title=None, scale=alt.Scale(zero=True)),
        tooltip=[
            alt.Tooltip("Label:N", title="Period"),
            alt.Tooltip(f"{value_name}:Q", title=value_name, format=",.2f"),
        ],
    )
    area = base.mark_area(
        color="#29B5E8",
        opacity=0.16,
        interpolate="monotone",
    )
    line = base.mark_line(
        color="#0068B7",
        strokeWidth=3,
        interpolate="monotone",
    )
    points = base.mark_point(
        color="#0068B7",
        filled=True,
        size=42,
    )
    st.altair_chart(_configure_chart((area + line + points).properties(height=170)), width="stretch")


def _render_bar_panel(title: str, frame, *, value_name: str = "Value", max_rows: int = 8) -> None:
    alt = _altair()
    rows = _chart_records(frame, value_name)[:max(1, int(max_rows or 8))]
    st.markdown(f'<div class="ow-chart-title">{title}</div>', unsafe_allow_html=True)
    height = max(138, min(224, 28 * len(rows) + 44))
    chart = (
        alt.Chart(alt.Data(values=rows))
        .mark_bar(color="#0068B7", cornerRadiusEnd=4, opacity=0.86)
        .encode(
            y=alt.Y(
                "Label:N",
                title=None,
                sort="-x",
                axis=alt.Axis(labelLimit=150),
            ),
            x=alt.X(f"{value_name}:Q", title=None, scale=alt.Scale(zero=True)),
            tooltip=[
                alt.Tooltip("Label:N", title="Dimension"),
                alt.Tooltip(f"{value_name}:Q", title=value_name, format=",.2f"),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(_configure_chart(chart), width="stretch")


def _render_kpis() -> None:
    render_signal_lane_board("Executive Glance KPIs", _executive_glance_kpis(), max_lanes=6)


def _render_spend_trend() -> None:
    daily = _chart_frame("DAILY_COST", "Daily Spend")
    _render_line_panel(
        "7-Day Spend Trend",
        daily,
        fallback_points=_spend_trend_points(),
        value_name="Daily spend",
    )


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

    render_signal_lane_board("Snowflake Observability Wall", _observability_wall_lanes(), max_lanes=12)

    left, right = st.columns(2)
    with left:
        _render_line_panel("Daily Spend", daily_spend, fallback_points=_spend_trend_points(), value_name="Daily spend")
    with right:
        _render_line_panel("Runtime Pressure", workload, fallback_points=[0.0], value_name="P95 runtime")

    c1, c2 = st.columns(2)
    with c1:
        _render_bar_panel("Monthly Spend", monthly, value_name="Monthly spend", max_rows=6)
    with c2:
        _render_bar_panel("Top Cost Drivers", drivers, value_name="Cost drivers", max_rows=6)

    c3, c4 = st.columns(2)
    with c3:
        _render_bar_panel("Query Mix", query_types, value_name="Queries", max_rows=8)
    with c4:
        _render_bar_panel("Database Mix", query_database, value_name="Queries", max_rows=8)

    p1, p2 = st.columns(2)
    with p1:
        _render_bar_panel("Execution Status", exec_status, value_name="Queries", max_rows=6)
    with p2:
        _render_bar_panel("Warehouse Queue", pressure, value_name="Queue seconds", max_rows=8)

    _render_bar_panel("Warehouse Spill", spill, value_name="Remote spill GB", max_rows=8)


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
            "detail": f"Top queued warehouse: {summary.get('top_queue_warehouse') or 'On demand'}.",
        },
        {
            "label": "Remote spill",
            "value": f"{_safe_float(summary.get('remote_spill_gb')):,.1f} GB",
            "state": "Memory",
            "detail": f"Top spill warehouse: {summary.get('top_spill_warehouse') or 'On demand'}.",
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
            "detail": "Routed queue items with current telemetry status.",
        },
        {
            "label": "Storage",
            "value": f"{_safe_float(summary.get('storage_tb')):,.1f} TB",
            "state": _money(summary.get("storage_cost_usd")),
            "detail": "Storage pressure is visible even when Cost & Contract is not opened.",
        },
        {
            "label": "Top cost driver",
            "value": str(summary.get("top_cost_driver") or "On demand")[:28],
            "state": _money(summary.get("top_cost_driver_usd")),
            "detail": "Largest current cost driver in the selected scope.",
        },
        {
            "label": "Elapsed time",
            "value": f"{_safe_float(summary.get('avg_runtime_sec')):,.1f}s",
            "state": "Avg runtime",
            "detail": "Average query elapsed time across the selected scope.",
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


def render() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.session_state.setdefault("executive_landing_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _load_command_board()
    _render_kpis()
    _render_spend_trend()
    _render_observability_summary()
    _render_top_actions()
    _render_copy_summary()
