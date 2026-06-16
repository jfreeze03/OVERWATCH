"""Fast first-paint shell for the Cost & Contract route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, DEFAULT_DAY_WINDOW, DAY_WINDOW_OPTIONS, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    full_workspace_requested,
    render_shell_kpi_row,
    render_shell_workflows,
    render_signal_lane_board,
)
from utils.command_board import load_or_reuse_command_board


_FULL_WORKSPACE_KEY = "_cost_contract_full_workspace_requested"
_BRIEF_MODE_KEY = "_cost_contract_brief_mode"
_FAST_ENTRY_VERSION_KEY = "_cost_contract_shell_fast_entry_version"
_FAST_ENTRY_VERSION = 1
_COST_SPLASH_KEY = "cost_contract_splash"
_COMMAND_BOARD_DATA_KEY = "cost_contract_command_board_data"
_COMMAND_BOARD_SUMMARY_KEY = "cost_contract_command_board_summary"
_COMMAND_BOARD_META_KEY = "cost_contract_command_board_meta"
_COMMAND_BOARD_REFRESH_MARKER_KEY = "cost_contract_command_board_refresh_marker"
_FULL_WORKSPACE_STATE_KEYS = (
    _COST_SPLASH_KEY,
    "cost_contract_cockpit",
    "cost_contract_run_rate",
    "cost_contract_queue",
    "cost_contract_attribution_reconciliation",
    "cost_contract_service_lens",
    "cost_contract_spike_root_cause",
    "cost_contract_change_cost_correlation",
)

_WORKFLOWS = (
    {
        "WORKFLOW": "Usage attribution and run-rate",
        "BUTTON_LABEL": "Open Cost Overview",
        "MOVE": "Start with usage movement, warehouse ranking, service spend, Cortex, and run-rate pace.",
    },
    {
        "WORKFLOW": "Storage cost and retention",
        "BUTTON_LABEL": "Open Storage Cost",
        "MOVE": "Review database, failsafe, stage, and table storage cost telemetry from Snowflake storage usage views.",
    },
    {
        "WORKFLOW": "AI and Cortex spend",
        "BUTTON_LABEL": "Open Cortex Spend",
        "MOVE": "Review Cortex usage, model spend, users, and runaway AI cost signals.",
    },
    {
        "WORKFLOW": "SPCS spend",
        "BUTTON_LABEL": "Open SPCS Spend",
        "MOVE": "Review Snowpark Container Services usage, services, and cost exposure.",
    },
    {
        "WORKFLOW": "Recommendations and action queue",
        "BUTTON_LABEL": "Open Recommendations",
        "MOVE": "Route cost fixes with savings, severity, and telemetry status.",
    },
)


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


def _window_label() -> str:
    selected_days = st.session_state.get("cost_contract_cockpit_window", DEFAULT_DAY_WINDOW)
    try:
        days = int(selected_days)
    except (TypeError, ValueError):
        days = int(DEFAULT_DAY_WINDOW)
    if days in DAY_WINDOW_OPTIONS:
        return f"{days}d"
    start = st.session_state.get("global_start_date")
    end = st.session_state.get("global_end_date")
    if isinstance(start, date) and isinstance(end, date):
        return f"{max(1, (end - start).days + 1)}d"
    return f"{int(DEFAULT_DAY_WINDOW)}d"


def _window_days() -> int:
    selected_days = st.session_state.get("cost_contract_cockpit_window", DEFAULT_DAY_WINDOW)
    try:
        days = int(selected_days)
    except (TypeError, ValueError):
        days = int(DEFAULT_DAY_WINDOW)
    return max(1, days if days in DAY_WINDOW_OPTIONS else int(DEFAULT_DAY_WINDOW))


def _is_loaded_frame(value: object) -> bool:
    return bool(hasattr(value, "empty") and not getattr(value, "empty", True))


def _first_row(value: object) -> object | None:
    if not _is_loaded_frame(value):
        return None
    try:
        return value.iloc[0]
    except Exception:
        return None


def _float_value(value: object, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(float(value if value is not None else default))
    except (TypeError, ValueError):
        return default


def _row_get(row: object | None, key: str, default: object = None) -> object:
    if row is None:
        return default
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(key, default)
    try:
        return row[key]
    except Exception:
        return default


def _money(value: object, *, signed: bool = False) -> str:
    amount = _float_value(value)
    if signed:
        sign = "+" if amount >= 0 else "-"
        return f"{sign}${abs(amount):,.0f}"
    return f"${amount:,.0f}"


def _load_command_board() -> dict:
    payload = load_or_reuse_command_board(
        data_key=_COMMAND_BOARD_DATA_KEY,
        summary_key=_COMMAND_BOARD_SUMMARY_KEY,
        meta_key=_COMMAND_BOARD_META_KEY,
        refresh_marker_key=_COMMAND_BOARD_REFRESH_MARKER_KEY,
        company=_active_company(),
        environment=_active_environment(),
        days=_window_days(),
    )
    return payload.summary


def _loaded_cost_board() -> dict:
    command_summary = _load_command_board()
    cockpit = st.session_state.get("cost_contract_cockpit")
    cockpit_meta = st.session_state.get("cost_contract_cockpit_meta", {})
    cockpit_row = _first_row(cockpit)
    cockpit_loaded = (
        cockpit_row is not None
        and isinstance(cockpit_meta, dict)
        and cockpit_meta.get("company") == _active_company()
    )
    run_rate_row = _first_row(st.session_state.get("cost_contract_run_rate"))
    queue = st.session_state.get("cost_contract_queue")
    queue_loaded = _is_loaded_frame(queue)

    current_credits = _float_value(_row_get(cockpit_row, "CURRENT_CREDITS"))
    prior_credits = _float_value(_row_get(cockpit_row, "PRIOR_CREDITS"))
    spend = current_credits * _credit_price()
    delta_spend = (current_credits - prior_credits) * _credit_price()
    if not cockpit_loaded and command_summary.get("loaded"):
        current_credits = _float_value(command_summary.get("current_credits"))
        prior_credits = _float_value(command_summary.get("prior_credits"))
        spend = _float_value(command_summary.get("current_cost_usd")) or current_credits * _credit_price()
        delta_spend = _float_value(command_summary.get("spend_delta_cost_usd")) or (current_credits - prior_credits) * _credit_price()
    forecast_credits = _float_value(_row_get(run_rate_row, "PROJECTED_30D_FROM_7D"))
    forecast = forecast_credits * _credit_price() if run_rate_row is not None else 0.0
    avg_daily_7d = _float_value(_row_get(run_rate_row, "AVG_DAILY_7D")) * _credit_price()
    run_rate_state = str(_row_get(run_rate_row, "RUN_RATE_STATE", "") or "").strip() or "On demand"
    if command_summary.get("loaded") and not forecast:
        avg_daily_7d = spend / max(1, int(DEFAULT_DAY_WINDOW))
        forecast = avg_daily_7d * 30
        run_rate_state = "Forecast"
    top_driver = str(_row_get(cockpit_row, "TOP_INCREASE_WAREHOUSE", "On demand") or "On demand")
    top_delta = _float_value(_row_get(cockpit_row, "TOP_INCREASE_CREDITS")) * _credit_price()
    if not cockpit_loaded and command_summary.get("loaded"):
        top_driver = str(command_summary.get("top_cost_driver") or "On demand")
        top_delta = _float_value(command_summary.get("top_cost_driver_usd"))

    open_actions = high_actions = 0
    est_savings = 0.0
    if queue_loaded:
        try:
            status = queue["STATUS"].fillna("").astype(str).str.title() if "STATUS" in queue.columns else None
            open_mask = ~status.isin(["Fixed", "Ignored", "Closed"]) if status is not None else None
            open_actions = int(open_mask.sum()) if open_mask is not None else len(queue)
            if "SEVERITY" in queue.columns and open_mask is not None:
                severity = queue["SEVERITY"].fillna("").astype(str).str.title()
                high_actions = int((severity.isin(["Critical", "High"]) & open_mask).sum())
            if "EST_MONTHLY_SAVINGS" in queue.columns and open_mask is not None:
                est_savings = _float_value(queue.loc[open_mask, "EST_MONTHLY_SAVINGS"].fillna(0).sum())
        except Exception:
            open_actions = len(queue) if hasattr(queue, "__len__") else 0
    elif command_summary.get("loaded"):
        open_actions = _int_value(command_summary.get("open_actions"))
        high_actions = _int_value(command_summary.get("high_actions"))

    loaded_at = ""
    if isinstance(cockpit_meta, dict):
        loaded_at = str(cockpit_meta.get("loaded_at") or "").strip()
    storage_cost = _float_value(command_summary.get("storage_cost_usd")) if command_summary.get("loaded") else 0.0
    storage_tb = _float_value(command_summary.get("storage_tb")) if command_summary.get("loaded") else 0.0
    return {
        "loaded": cockpit_loaded or bool(command_summary.get("loaded")),
        "source": "Cost summary",
        "spend": spend,
        "delta_spend": delta_spend,
        "forecast": forecast,
        "avg_daily_7d": avg_daily_7d,
        "run_rate_state": run_rate_state,
        "top_driver": top_driver,
        "top_delta": top_delta,
        "open_actions": open_actions,
        "high_actions": high_actions,
        "est_savings": est_savings,
        "cortex": _money(command_summary.get("cortex_cost_usd")) if command_summary.get("loaded") else ("Loaded" if _is_loaded_frame(st.session_state.get("cortex_control_summary")) else "On demand"),
        "storage_cost": storage_cost,
        "storage_tb": storage_tb,
        "status": "Loaded" if loaded_at or command_summary.get("loaded") else "On demand",
    }


def _cost_shell_lanes(board: dict | None = None) -> tuple[dict[str, str], ...]:
    board = board or _loaded_cost_board()
    if not board.get("loaded"):
        return (
            {
                "label": "Current spend",
                "value": "On demand",
                "state": "Refresh",
                "detail": "Official metering facts load the first-paint spend board.",
            },
            {
                "label": "Spend movement",
                "value": "On demand",
                "state": "Refresh",
                "detail": "Compare current window against the prior period before explaining burn.",
            },
            {
                "label": "30d run rate",
                "value": "On demand",
                "state": "Forecast",
                "detail": "Projected spend comes from recent burn history.",
            },
            {
                "label": "Cortex dollars",
                "value": "On demand",
                "state": "AI",
                "detail": "Cortex usage is isolated from warehouse compute for cost truth.",
            },
            {
                "label": "Storage dollars",
                "value": "On demand",
                "state": "Storage",
                "detail": "Storage spend includes database, stage, and retention cost signals.",
            },
            {
                "label": "Top driver",
                "value": "On demand",
                "state": "Attribution",
                "detail": "Warehouse, service, and user/role drivers explain movement.",
            },
            {
                "label": "Action queue",
                "value": "On demand",
                "state": "Routes",
                "detail": "Recommendations require expected savings, action route, and telemetry status.",
            },
            {
                "label": "Run-rate pace",
                "value": "On demand",
                "state": "Forecast",
                "detail": "Forecasted burn is compared with current spend pace.",
            },
        )
    delta = _float_value(board.get("delta_spend"))
    driver = str(board.get("top_driver") or "No driver")
    return (
        {
            "label": "Current spend",
            "value": _money(board.get("spend")),
            "state": _window_label(),
            "detail": f"Compute credits at ${_credit_price():.2f}/credit.",
        },
        {
            "label": "Spend movement",
            "value": _money(delta, signed=True),
            "state": "Delta",
            "detail": "Movement versus prior comparison window.",
        },
        {
            "label": "30d run rate",
            "value": _money(board.get("forecast")) if board.get("loaded") else str(board.get("run_rate_state") or "On demand"),
            "state": "Forecast",
            "detail": f"7d average daily spend: {_money(board.get('avg_daily_7d'))}.",
        },
        {
            "label": "Cortex dollars",
            "value": str(board.get("cortex") or "On demand"),
            "state": "AI",
            "detail": "Cortex spend uses the AI-specific metering rate and facts.",
        },
        {
            "label": "Storage dollars",
            "value": _money(board.get("storage_cost")),
            "state": f"{_float_value(board.get('storage_tb')):,.1f} TB",
            "detail": "Database, stage, and retention cost from Snowflake storage telemetry.",
        },
        {
            "label": "Top driver",
            "value": driver[:32],
            "state": _money(board.get("top_delta"), signed=True),
            "detail": "Largest warehouse/service movement in the current scope.",
        },
        {
            "label": "Action queue",
            "value": f"{_int_value(board.get('open_actions')):,} open",
            "state": f"{_int_value(board.get('high_actions')):,} high",
            "detail": f"Open estimated savings: {_money(board.get('est_savings'))}.",
        },
        {
            "label": "Run-rate pace",
            "value": "Review" if _float_value(board.get("forecast")) and _float_value(board.get("forecast")) > _float_value(board.get("spend")) else "Stable",
            "state": "Forecast",
            "detail": "Forecasted burn compared with current spend pace.",
        },
    )


def _full_workspace_requested() -> bool:
    """Keep Cost navigation lightweight; open heavy detail only from a selected cost workflow."""
    _ = full_workspace_requested
    if st.session_state.get(_FULL_WORKSPACE_KEY):
        return True
    st.session_state.setdefault(_BRIEF_MODE_KEY, True)
    return False


def _apply_fast_entry_default() -> None:
    if st.session_state.get(_FAST_ENTRY_VERSION_KEY) == _FAST_ENTRY_VERSION:
        return
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FAST_ENTRY_VERSION_KEY] = _FAST_ENTRY_VERSION


def _open_workspace(workflow: str | None = None) -> None:
    st.session_state[_BRIEF_MODE_KEY] = False
    st.session_state[_FULL_WORKSPACE_KEY] = True
    if workflow:
        st.session_state["cost_contract_workflow"] = workflow
    st.rerun()


def _delegate_full_workspace() -> None:
    from sections import cost_contract

    cost_contract.render()


def _return_to_brief() -> None:
    st.session_state[_BRIEF_MODE_KEY] = True
    st.session_state[_FULL_WORKSPACE_KEY] = False
    st.rerun()


def _render_back_to_brief_control() -> None:
    control_col, _spacer = st.columns([1.0, 4.0])
    with control_col:
        if st.button("Back to Brief", key="cost_contract_shell_back_to_brief", width="stretch"):
            _return_to_brief()


def _render_metric_board() -> None:
    board = _loaded_cost_board()
    st.markdown("**Cost Command Board**")
    if not board["loaded"]:
        render_shell_kpi_row((
            ("Current Spend", "Awaiting data"),
            ("Delta", "Awaiting data"),
            ("30d Forecast", "Awaiting data"),
            ("Run-rate Pace", "Awaiting data"),
        ))
        render_shell_kpi_row((
            ("Cortex", "Awaiting data"),
            ("Top Driver", "Awaiting data"),
            ("Driver Delta", "Awaiting data"),
            ("Open Actions", "Awaiting data"),
        ))
    else:
        render_shell_kpi_row((
            ("Current Spend", _money(board["spend"])),
            ("Delta", _money(board["delta_spend"], signed=True)),
            ("30d Forecast", _money(board["forecast"])),
            ("Run-rate Pace", "Review" if board["forecast"] and board["forecast"] > board["spend"] else "Stable"),
        ))
        render_shell_kpi_row((
            ("Cortex", board["cortex"]),
            ("Storage", _money(board.get("storage_cost"))),
            ("Top Driver", str(board["top_driver"])[:28]),
            ("Driver Delta", _money(board["top_delta"], signed=True)),
        ))
    render_signal_lane_board("Cost Signals", _cost_shell_lanes(board), max_lanes=8)
    render_shell_kpi_row((
        ("Open Actions", f"{_int_value(board.get('open_actions')):,}" if board["loaded"] else "Awaiting data"),
        ("High Priority", f"{_int_value(board.get('high_actions')):,}" if board["loaded"] else "Awaiting data"),
        ("Open Est. Savings", _money(board.get("est_savings")) if board["loaded"] else "Awaiting data"),
        ("Cost Signals", "Compute, AI, storage, SPCS"),
    ))


def _render_executive_flow_board() -> None:
    board = _loaded_cost_board()
    st.markdown("**Cost Executive Flow**")
    if not board["loaded"]:
        render_shell_kpi_row((
            ("Burn", "Awaiting data"),
            ("Run Rate", "Awaiting data"),
            ("Driver", "Awaiting data"),
            ("Action Queue", "Awaiting data"),
        ))
    else:
        render_shell_kpi_row((
            ("Burn", _money(board["spend"])),
            ("Run Rate", _money(board["avg_daily_7d"])),
            ("Driver", str(board["top_driver"])[:28]),
            ("Action Queue", f"{_int_value(board['open_actions']):,}"),
        ))


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["WORKFLOW"]))

    render_shell_workflows(
        "Cost Operations Drilldowns",
        _WORKFLOWS,
        label_key="WORKFLOW",
        key_prefix="cost_contract_shell",
        on_open=_open,
    )


def render() -> None:
    _apply_fast_entry_default()
    if _full_workspace_requested():
        _render_back_to_brief_control()
        _delegate_full_workspace()
        return

    st.session_state.setdefault("cost_contract_shell_seen_at", datetime.now().isoformat(timespec="seconds"))
    _load_command_board()
    _render_metric_board()
    _render_executive_flow_board()
    _render_workflow_launchpad()
