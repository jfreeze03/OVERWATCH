"""Fast first-paint shell for the Cost & Contract route."""

from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT, DEFAULTS, DEFAULT_DAY_WINDOW, DAY_WINDOW_OPTIONS, ENVIRONMENT_CONFIG
from sections.shell_helpers import (
    action_state_label,
    evidence_caption,
    evidence_label,
    evidence_loaded,
    full_workspace_requested,
    render_refresh_contract,
    render_setup_health_board,
    render_shell_kpi_row,
    render_shell_status_strip,
    render_shell_workflows,
    render_signal_lane_board,
    scope_label,
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
    "cost_contract_verification_health",
    "cost_contract_attribution_reconciliation",
    "cost_contract_service_lens",
    "cost_contract_budget_command_center",
    "cost_contract_spike_root_cause",
    "cost_contract_change_cost_correlation",
)

_WORKFLOWS = (
    {
        "WORKFLOW": "Explain bill / attribution / contract",
        "BUTTON_LABEL": "Open Cost Overview",
        "MOVE": "Start with bill movement, warehouse ranking, service spend, Cortex, and contract pace.",
    },
    {
        "WORKFLOW": "Storage cost and retention",
        "BUTTON_LABEL": "Open Storage Cost",
        "MOVE": "Review database, failsafe, stage, and table storage cost evidence from Snowflake storage usage views.",
    },
    {
        "WORKFLOW": "FinOps Control Center",
        "BUTTON_LABEL": "Open FinOps",
        "MOVE": "Review governance, resource monitors, verified savings, and formula trust.",
    },
    {
        "WORKFLOW": "AI and Cortex spend",
        "BUTTON_LABEL": "Open Cortex Spend",
        "MOVE": "Review Cortex usage, model spend, users, and runaway AI cost signals.",
    },
    {
        "WORKFLOW": "Budget governance",
        "BUTTON_LABEL": "Open Budgets",
        "MOVE": "Check native Snowflake budgets, AI quota patterns, and budget actions.",
    },
    {
        "WORKFLOW": "Recommendations and action queue",
        "BUTTON_LABEL": "Open Recommendations",
        "MOVE": "Assign owned cost fixes with proof, savings, severity, and verification.",
    },
    {
        "WORKFLOW": "Snowflake value log",
        "BUTTON_LABEL": "Open Value Log",
        "MOVE": "Show DBA savings, avoided spend, and service-improvement evidence.",
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
    run_rate_state = str(_row_get(run_rate_row, "RUN_RATE_STATE", "") or "").strip() or "Not loaded"
    if command_summary.get("loaded") and not forecast:
        avg_daily_7d = spend / max(1, int(DEFAULT_DAY_WINDOW))
        forecast = avg_daily_7d * 30
        run_rate_state = "Mart forecast"
    top_driver = str(_row_get(cockpit_row, "TOP_INCREASE_WAREHOUSE", "Not loaded") or "Not loaded")
    top_delta = _float_value(_row_get(cockpit_row, "TOP_INCREASE_CREDITS")) * _credit_price()
    if not cockpit_loaded and command_summary.get("loaded"):
        top_driver = str(command_summary.get("top_cost_driver") or "Not loaded")
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
    return {
        "loaded": cockpit_loaded or bool(command_summary.get("loaded")),
        "source": "cost_cockpit" if cockpit_loaded else "MART_EXECUTIVE_OBSERVABILITY",
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
        "cortex": _money(command_summary.get("cortex_cost_usd")) if command_summary.get("loaded") else ("Loaded" if _is_loaded_frame(st.session_state.get("cortex_control_summary")) else "Not loaded"),
        "budget": "Loaded" if _is_loaded_frame(st.session_state.get("cost_contract_budget_command_center")) else "On demand",
        "freshness": "Loaded" if loaded_at or command_summary.get("loaded") else "Not loaded",
    }


def _cost_shell_lanes(board: dict | None = None) -> tuple[dict[str, str], ...]:
    board = board or _loaded_cost_board()
    if not board.get("loaded"):
        return (
            {
                "label": "Current spend",
                "value": "Not loaded",
                "state": "Refresh",
                "detail": "Official metering facts load the first-paint spend board.",
            },
            {
                "label": "Spend movement",
                "value": "Not loaded",
                "state": "Refresh",
                "detail": "Compare current window against the prior period before explaining burn.",
            },
            {
                "label": "30d run rate",
                "value": "Not loaded",
                "state": "Forecast",
                "detail": "Projected spend comes from the scheduled contract-burn mart.",
            },
            {
                "label": "Cortex dollars",
                "value": "Not loaded",
                "state": "AI",
                "detail": "Cortex usage is isolated from warehouse compute for cost truth.",
            },
            {
                "label": "Top driver",
                "value": "Not loaded",
                "state": "Attribution",
                "detail": "Warehouse, service, and user/role drivers explain movement.",
            },
            {
                "label": "Action queue",
                "value": "Not loaded",
                "state": "Owners",
                "detail": "Recommendations require owner, expected savings, and verification proof.",
            },
            {
                "label": "Budget risk",
                "value": "On demand",
                "state": "Governance",
                "detail": "Budgets and quota controls load with the FinOps workflow.",
            },
            {
                "label": "Value log",
                "value": "Automated",
                "state": "Proof",
                "detail": "Candidate savings are generated from metering and action evidence.",
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
            "value": _money(board.get("forecast")) if _float_value(board.get("forecast")) else str(board.get("run_rate_state") or "Not loaded"),
            "state": "Forecast",
            "detail": f"7d average daily spend: {_money(board.get('avg_daily_7d'))}.",
        },
        {
            "label": "Cortex dollars",
            "value": str(board.get("cortex") or "Not loaded"),
            "state": "AI",
            "detail": "Cortex spend uses the AI-specific metering rate and facts.",
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
            "label": "Budget risk",
            "value": str(board.get("budget") or "On demand"),
            "state": "Governance",
            "detail": "Budget and resource monitor controls are routed through FinOps.",
        },
        {
            "label": "Freshness",
            "value": str(board.get("freshness") or "Not loaded"),
            "state": "Source",
            "detail": "Shell uses mart/cache facts; live scans stay behind explicit proof.",
        },
    )


def _full_workspace_requested() -> bool:
    """Keep Cost navigation lightweight; open heavy proof only from a selected cost workflow."""
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


def _render_status_strip() -> None:
    detail = evidence_caption(
        st.session_state,
        _FULL_WORKSPACE_STATE_KEYS,
        "Cost, Cortex, budget, contract, and verification proof are loaded when a workflow is opened.",
    )
    render_shell_status_strip(
        state=action_state_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS),
        headline="Cost command view: bill movement, Cortex spend, budget risk, and contract burn.",
        detail=detail,
    )


def _render_kpi_row() -> None:
    render_shell_kpi_row((
        ("Scope", scope_label(_active_company(), _active_environment())),
        ("Window", _window_label()),
        ("Compute $/credit", f"{_credit_price():.2f}"),
        ("Evidence", evidence_label(st.session_state, _FULL_WORKSPACE_STATE_KEYS)),
    ))


def _render_metric_board() -> None:
    board = _loaded_cost_board()
    st.markdown("**Cost Metric Board**")
    render_refresh_contract(
        st.session_state.get("cost_contract_cockpit_meta") or st.session_state.get(_COMMAND_BOARD_META_KEY, {}),
        source=str(board.get("source") or "FACT_COST_DAILY / FACT_CORTEX_DAILY"),
        target_minutes=60,
        refresh_method="Scheduled cost and Cortex mart refresh",
        live_fallback="Explicit proof refresh",
    )
    render_signal_lane_board("Cost Command Board", _cost_shell_lanes(board), max_lanes=8)
    if not board["loaded"]:
        render_shell_kpi_row((
            ("Current Spend", "Not loaded"),
            ("Delta", "Not loaded"),
            ("30d Forecast", "Not loaded"),
            ("Contract Pace", "Not loaded"),
        ))
        render_shell_kpi_row((
            ("Cortex", "Not loaded"),
            ("Top Driver", "Not loaded"),
            ("Budget Risk", "On demand"),
            ("Cost Freshness", "Not loaded"),
        ))
        render_shell_kpi_row((
            ("Open Actions", "Not loaded"),
            ("High Priority", "Not loaded"),
            ("Open Est. Savings", "Not loaded"),
            ("Value Log", "Automated setup"),
        ))
        return

    render_shell_kpi_row((
        ("Current Spend", _money(board["spend"])),
        ("Delta", _money(board["delta_spend"], signed=True)),
        ("30d Forecast", _money(board["forecast"]) if board["forecast"] else "Not loaded"),
        ("Contract Pace", "Review" if board["forecast"] and board["forecast"] > board["spend"] else "Stable"),
    ))
    render_shell_kpi_row((
        ("Cortex", board["cortex"]),
        ("Top Driver", str(board["top_driver"])[:28]),
        ("Driver Delta", _money(board["top_delta"], signed=True)),
        ("Cost Freshness", board["freshness"]),
    ))
    render_shell_kpi_row((
        ("Open Actions", f"{_int_value(board['open_actions']):,}"),
        ("High Priority", f"{_int_value(board['high_actions']):,}"),
        ("Open Est. Savings", _money(board["est_savings"])),
        ("Budget Risk", board["budget"]),
    ))


def _render_executive_flow_board() -> None:
    board = _loaded_cost_board()
    st.markdown("**Cost Executive Flow**")
    if not board["loaded"]:
        render_shell_kpi_row((
            ("Burn", "Refresh cost board"),
            ("Run Rate", "Refresh cost board"),
            ("Driver", "Refresh cost board"),
            ("Action Queue", "Refresh cost board"),
        ))
    else:
        render_shell_kpi_row((
            ("Burn", _money(board["spend"])),
            ("Run Rate", _money(board["avg_daily_7d"]) if board["avg_daily_7d"] else board["run_rate_state"]),
            ("Driver", str(board["top_driver"])[:28]),
            ("Action Queue", f"{_int_value(board['open_actions']):,}"),
        ))
    render_setup_health_board(
        "Cost Mart Contract",
        (
            ("Official metering", "FACT_COST_DAILY"),
            ("AI spend", "FACT_CORTEX_DAILY"),
            ("Forecast", "OVERWATCH_CONTRACT_BURN_FORECAST_V"),
            ("Value", "OVERWATCH_VALUE_CANDIDATE_V"),
        ),
        cadence="60 min cost refresh",
        fallback="Explicit proof refresh",
        owner="FinOps / DBA",
    )


def _render_value_automation_board() -> None:
    st.markdown("**Snowflake Value Automation**")
    render_signal_lane_board(
        "No-Touch Value Capture",
        (
            {
                "label": "Candidate source",
                "value": "OVERWATCH_VALUE_CANDIDATE_V",
                "state": "Automated",
                "detail": "Finds fixed cost actions and resolved alert-prevention value without DBA typing.",
            },
            {
                "label": "Ledger target",
                "value": "OVERWATCH_ROI_LOG",
                "state": "Audited",
                "detail": "Automated entries keep evidence source, evidence id, owner, and value state.",
            },
            {
                "label": "Verifier",
                "value": "ESTIMATED -> VERIFIED",
                "state": "Guarded",
                "detail": "Value stays estimated until post-period proof or closure evidence is present.",
            },
            {
                "label": "Run control",
                "value": "SP_OVERWATCH_AUTOMATE_VALUE_LOG",
                "state": "Explicit",
                "detail": "Procedure logs candidates, inserted rows, verified rows, status, and message.",
            },
        ),
        max_lanes=4,
    )
    render_setup_health_board(
        "Value Log Contract",
        (
            ("Candidate view", "OVERWATCH_VALUE_CANDIDATE_V"),
            ("Health view", "OVERWATCH_VALUE_AUTOMATION_HEALTH_V"),
            ("Run log", "OVERWATCH_VALUE_AUTOMATION_RUN"),
            ("Ledger", "OVERWATCH_ROI_LOG"),
        ),
        cadence="60 min value candidate refresh",
        fallback="Manual value entry remains optional, not required",
        owner="DBA / FinOps",
    )


def _render_workflow_launchpad() -> None:
    def _open(row):
        _open_workspace(str(row["WORKFLOW"]))

    render_shell_workflows(
        "Cost Investigation Workflows",
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
    _render_status_strip()
    _render_kpi_row()
    _render_metric_board()
    _render_executive_flow_board()
    _render_value_automation_board()
    _render_workflow_launchpad()
