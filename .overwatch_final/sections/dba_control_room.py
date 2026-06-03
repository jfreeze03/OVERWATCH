"""DBA Control Room - operational landing page for OVERWATCH.

This page is intentionally workflow-first. It summarizes exceptions that a DBA
must triage, routes each signal to the right specialist tool, and creates
report-ready notes for leadership without making executives use the app.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from config import DEFAULT_ENVIRONMENT, DEFAULTS, SECTION_BY_TITLE, normalize_section_name
import utils as _utils


class _LazyPandas:
    """Load pandas only when the Control Room actually needs dataframe work."""

    _module = None

    def _load(self):
        if self._module is None:
            import pandas as pandas_module

            self._module = pandas_module
        return self._module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


pd = _LazyPandas()


def _lazy_util(name: str):
    def _call(*args, **kwargs):
        return getattr(_utils, name)(*args, **kwargs)

    _call.__name__ = name
    return _call


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    try:
        if value is None or value != value:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def get_credit_price() -> float:
    return safe_float(st.session_state.get("credit_price", DEFAULTS.get("credit_price", 3.68)), 3.68)


def metric_confidence_label(kind: str) -> str:
    labels = {
        "exact": "Confidence: Exact",
        "allocated": "Confidence: Allocated / Estimated from exact warehouse metering",
        "estimated": "Confidence: Estimated",
        "forecast": "Confidence: Forecast based on recent observed burn",
        "projection": "Confidence: Projection based on recent observed burn",
        "composite": "Confidence: Composite score from weighted operational signals",
        "account": "Confidence: Account-wide",
        "account-wide": "Confidence: Account-wide",
    }
    return labels.get(str(kind or "").lower(), "Confidence: Calculation depends on available account metadata")


def freshness_note(source: str) -> str:
    source_key = str(source or "").lower()
    if "information_schema" in source_key or source_key in {"live", "is"}:
        return "Freshness: live INFORMATION_SCHEMA view"
    if "account_usage" in source_key or source_key in {"account", "query_history", "warehouse_metering_history"}:
        return "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes"
    if "organization_usage" in source_key:
        return "Freshness: ORGANIZATION_USAGE can lag several hours"
    if "session" in source_key:
        return "Freshness: current Streamlit session only"
    return "Freshness: depends on source view availability"


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    cols = st.columns(columns)
    for idx, (label, detail) in enumerate(items):
        with cols[idx % len(cols)]:
            st.caption(str(label))
            st.write(str(detail))


build_metered_credit_cte = _lazy_util("build_metered_credit_cte")
build_task_failure_summary_sql = _lazy_util("build_task_failure_summary_sql")
build_task_history_sql = _lazy_util("build_task_history_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
dba_control_plane_section_scorecards = _lazy_util("dba_control_plane_section_scorecards")
dba_effective_readiness_score = _lazy_util("dba_effective_readiness_score")
download_csv = _lazy_util("download_csv")
enrich_action_queue_view = _lazy_util("enrich_action_queue_view")
format_credits = _lazy_util("format_credits")
format_snowflake_error = _lazy_util("format_snowflake_error")
filter_existing_columns = _lazy_util("filter_existing_columns")
get_db_filter_clause = _lazy_util("get_db_filter_clause")
get_active_company = _lazy_util("get_active_company")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
get_query_telemetry = _lazy_util("get_query_telemetry")
get_query_budget_summary = _lazy_util("get_query_budget_summary")
get_session = _lazy_util("get_session")
get_user_filter_clause = _lazy_util("get_user_filter_clause")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")
build_mart_control_room_summary_sql = _lazy_util("build_mart_control_room_summary_sql")
build_mart_control_room_credits_sql = _lazy_util("build_mart_control_room_credits_sql")
build_mart_control_room_cost_drivers_sql = _lazy_util("build_mart_control_room_cost_drivers_sql")
build_mart_control_room_warehouse_pressure_sql = _lazy_util("build_mart_control_room_warehouse_pressure_sql")
build_mart_control_room_failed_queries_sql = _lazy_util("build_mart_control_room_failed_queries_sql")
build_mart_control_room_object_changes_sql = _lazy_util("build_mart_control_room_object_changes_sql")
build_mart_control_room_failed_logins_sql = _lazy_util("build_mart_control_room_failed_logins_sql")
build_mart_control_room_task_failures_sql = _lazy_util("build_mart_control_room_task_failures_sql")
build_mart_query_detail_recent_sql = _lazy_util("build_mart_query_detail_recent_sql")
build_mart_task_history_sql = _lazy_util("build_mart_task_history_sql")
build_mart_procedure_sla_sql = _lazy_util("build_mart_procedure_sla_sql")
load_latest_control_room_mart = _lazy_util("load_latest_control_room_mart")
load_task_inventory = _lazy_util("load_task_inventory")
load_action_queue = _lazy_util("load_action_queue")
run_query = _lazy_util("run_query")
sql_literal = _lazy_util("sql_literal")
resolve_owner_context = _lazy_util("resolve_owner_context")
render_priority_dataframe = _lazy_util("render_priority_dataframe")

DBA_CONTROL_SCOPE_FILTER_KEYS = (
    "global_warehouse",
    "global_user",
    "global_role",
    "global_database",
    "global_start_date",
    "global_end_date",
)
DBA_CONTROL_ROOM_PANES = (
    "Fast Watch",
    "Operations Tower",
    "Triage",
    "Drill Routes",
    "Release Compare",
    "Executive Evidence",
    "Source Health",
    "App Operations",
)
DBA_CONTROL_ROOM_DETAIL_PANES = (
    "Failed Queries",
    "Task Failures",
    "Task SLA/Cost",
    "Procedure SLA/Cost",
    "Cortex Cost",
    "Failed Logins",
    "Object Changes",
    "Action Queue",
)

DBA_CONTROL_ROOM_DERIVED_STATE_KEYS = (
    "dba_control_room_incident_board",
    "dba_control_room_handoff",
    "dba_control_tower_priority_index",
    "dba_autopilot_flight_plan",
    "dba_autopilot_flight_plan_markdown",
    "dba_control_room_ops_scope_key",
    "dba_control_room_ops_ready",
)
DBA_CONTROL_ROOM_LIVE_FALLBACK_CAP_HOURS = 24
DBA_CONTROL_ROOM_LIVE_FALLBACK_KEYS = {
    "credits",
    "failed_queries",
    "failed_logins",
}


def _live_fallback_deferred_message(source: str, mart_exc: Exception | None = None) -> str:
    detail = format_snowflake_error(mart_exc) if mart_exc is not None else ""
    suffix = f" Mart error: {detail}" if detail else ""
    return (
        f"{source} live fallback is deferred to avoid long account scans from the Control Room. "
        f"Use the specialist workflow or refresh the OVERWATCH mart for this surface.{suffix}"
    )


def _clear_dba_control_room_derived_state() -> None:
    """Clear derived boards when the loaded evidence scope changes."""
    for key in DBA_CONTROL_ROOM_DERIVED_STATE_KEYS:
        st.session_state.pop(key, None)


def _dba_control_ops_scope_key(
    company: str,
    environment: str,
    lookback_hours: int,
    cortex_budget_usd: float,
    include_deep_evidence: bool,
    allow_live_fallback: bool,
    loaded_meta: dict | None,
) -> tuple:
    meta_items = tuple(sorted((str(k), _dba_control_scope_value(v)) for k, v in (loaded_meta or {}).items()))
    return (
        str(company),
        str(environment),
        int(lookback_hours),
        round(safe_float(cortex_budget_usd), 2),
        bool(include_deep_evidence),
        bool(allow_live_fallback),
        meta_items,
    )


def _task_management_helpers():
    from sections.task_management import (
        _build_task_ops_frames,
        _extract_object_candidates,
        _normalize_query_details,
        _procedure_from_definition,
        _query_detail_sql,
    )

    return (
        _build_task_ops_frames,
        _extract_object_candidates,
        _normalize_query_details,
        _procedure_from_definition,
        _query_detail_sql,
    )


def _cortex_helpers():
    from sections.cortex_monitor import (
        _build_cortex_control_sql,
        _cortex_cost_rating,
        _cortex_cost_score,
    )

    return _build_cortex_control_sql, _cortex_cost_rating, _cortex_cost_score


def _procedure_helpers():
    from sections.stored_proc_tracker import (
        _build_procedure_sla_frames,
        _build_procedure_sla_sql,
        _procedure_run_estimated_credits,
        _query_history_has_root_query_id,
    )

    return (
        _build_procedure_sla_frames,
        _build_procedure_sla_sql,
        _procedure_run_estimated_credits,
        _query_history_has_root_query_id,
    )


def _jump(title: str, *, warehouse: str = "", user: str = "", workflow: str = "") -> None:
    """Navigate to a registered section and carry useful filter context."""
    target = normalize_section_name(SECTION_BY_TITLE.get(title, title))
    if target not in set(SECTION_BY_TITLE.values()):
        return
    st.session_state["nav_section"] = target
    if workflow:
        if title in {"Query Workbench", "Workload Operations"}:
            if workflow == "Diagnosis":
                st.session_state["workload_operations_workflow"] = "Query diagnosis"
            elif workflow == "History Search":
                st.session_state["workload_operations_workflow"] = "History search"
            else:
                st.session_state["workload_operations_workflow"] = workflow
        elif title == "Cost & Contract":
            st.session_state["cost_contract_workflow"] = workflow
        elif title == "Security Posture":
            st.session_state["security_posture_workflow"] = workflow
        elif title == "Change & Drift":
            st.session_state["change_drift_workflow"] = workflow
    if warehouse:
        st.session_state["global_warehouse"] = warehouse
        st.session_state["wh_filter"] = warehouse
    if user:
        st.session_state["global_user"] = user
    st.rerun()


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame()


def _dba_control_scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _dba_control_scope_meta(
    company: str,
    environment: str,
    lookback_hours: int | None = None,
    cortex_budget_usd: float | None = None,
    include_deep_evidence: bool | None = None,
    allow_live_fallback: bool | None = None,
    state: dict | None = None,
) -> dict:
    """Return the exact operator scope a loaded DBA Control Room surface must match."""
    state = state if state is not None else st.session_state
    meta = {
        "company": _dba_control_scope_value(company),
        "environment": _dba_control_scope_value(environment),
    }
    if lookback_hours is not None:
        meta["lookback_hours"] = int(lookback_hours)
    if cortex_budget_usd is not None:
        meta["cortex_budget_usd"] = round(safe_float(cortex_budget_usd), 2)
    if include_deep_evidence is not None:
        meta["include_deep_evidence"] = bool(include_deep_evidence)
    if allow_live_fallback is not None:
        meta["allow_live_fallback"] = bool(allow_live_fallback)
    for key in DBA_CONTROL_SCOPE_FILTER_KEYS:
        meta[key] = _dba_control_scope_value(state.get(key))
    return meta


def _dba_control_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        actual = meta.get(key)
        if key == "lookback_hours":
            try:
                if int(actual) != int(expected_value):
                    return False
            except Exception:
                return False
        elif key == "cortex_budget_usd":
            if round(safe_float(actual), 2) != round(safe_float(expected_value), 2):
                return False
        elif isinstance(expected_value, bool):
            if bool(actual) != expected_value:
                return False
        elif _dba_control_scope_value(actual) != _dba_control_scope_value(expected_value):
            return False
    return True


def _dba_snapshot_scope_compatible(environment: str, state: dict | None = None) -> bool:
    """Fast snapshot is company-level only; scoped DBA evidence needs detail load."""
    state = state if state is not None else st.session_state
    if str(environment or "ALL").upper() != "ALL":
        return False
    return not any(_dba_control_scope_value(state.get(key)) for key in DBA_CONTROL_SCOPE_FILTER_KEYS)


def _dba_control_source_health_rows(
    data: dict,
    state: dict,
    company: str,
    environment: str,
    lookback_hours: int,
    cortex_budget_usd: float,
    include_deep_evidence: bool,
    allow_live_fallback: bool,
) -> pd.DataFrame:
    """Summarize control-room evidence freshness, source mode, and actionability."""
    if not isinstance(data, dict) or not data:
        return _empty_df()
    expected_meta = _dba_control_scope_meta(
        company,
        environment,
        lookback_hours,
        cortex_budget_usd,
        include_deep_evidence,
        allow_live_fallback,
        state=state,
    )
    loaded_meta = state.get("dba_control_room_meta", {})
    source_modes = data.get("_source_modes", _empty_df())
    mode_map = {}
    if source_modes is not None and not source_modes.empty and "Source" in source_modes.columns:
        for _, source_row in source_modes.iterrows():
            mode_map[str(source_row.get("Source"))] = {
                "Mode": str(source_row.get("Mode", "")),
                "Mode Message": str(source_row.get("Message", "")),
            }
    source_aliases = {
        "task_sla_cost": "task_sla_history",
        "task_latest_runs": "task_sla_history",
        "procedure_sla_cost": "procedure_sla",
        "procedure_latest_runs": "procedure_sla",
        "cortex_summary": "cortex_cost",
        "cortex_exceptions": "cortex_cost",
    }
    rows = []
    for key, value in data.items():
        if key.startswith("_") or key.endswith("_error"):
            continue
        source_key = source_aliases.get(key, key)
        mode_info = mode_map.get(str(source_key), mode_map.get(str(key), {}))
        mode = mode_info.get("Mode", "Live or local")
        err = data.get(f"{key}_error", _empty_df())
        message = "" if err is None or err.empty else str(err["ERROR"].iloc[0])
        if not message and mode_info.get("Mode Message", "").lower() not in ("", "nan", "none"):
            message = mode_info["Mode Message"]
        loaded = isinstance(value, pd.DataFrame)
        mode_lower = str(mode).lower()
        if mode_lower == "deferred" or "deferred" in mode_lower:
            state_label = "Deferred"
        elif "unavailable" in mode_lower:
            state_label = "Unavailable"
        elif err is not None and not err.empty:
            state_label = "Unavailable"
        elif not loaded:
            state_label = "Not Loaded"
        elif not _dba_control_meta_matches(loaded_meta, expected_meta):
            state_label = "Stale"
        elif value.empty:
            state_label = "No Rows"
        else:
            state_label = "Loaded"
        if state_label == "Stale":
            next_action = "Reload DBA Control Room after changing company, environment, lookback, budget, or global filters."
        elif state_label == "Unavailable":
            next_action = "Deploy or refresh the mart/source before relying on this surface."
        elif state_label == "Deferred":
            next_action = "Load deep evidence only when this source is needed for the current investigation."
        elif state_label == "No Rows":
            next_action = "Confirm the selected scope has relevant events or mart rows."
        elif "fallback" in mode_lower:
            next_action = "Use for investigation; prefer mart refresh for repeated morning triage."
        else:
            next_action = "Current for the active DBA control-room scope."
        rows.append({
            "SURFACE": key,
            "STATE": state_label,
            "STATE_RANK": {
                "Unavailable": 0,
                "Stale": 1,
                "Loaded": 2,
                "No Rows": 3,
                "Deferred": 4,
                "Not Loaded": 5,
            }.get(state_label, 9),
            "MODE": mode,
            "ROWS": 0 if value is None or not hasattr(value, "empty") or value.empty else len(value),
            "SCOPE": f"{company} / {environment} / {int(lookback_hours)}h",
            "MESSAGE": message,
            "NEXT_ACTION": next_action,
        })
    return pd.DataFrame(rows)


def _snapshot_metric(df: pd.DataFrame, column: str) -> float:
    if df is None or df.empty or column not in df.columns:
        return 0.0
    return safe_float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _control_room_snapshot_to_data(snapshot: pd.DataFrame) -> dict:
    """Convert the lightweight mart snapshot into the data shape used by the page.

    The mart snapshot is intentionally small: it supports the watch floor and
    morning triage metrics, while deep evidence tables still load on demand.
    """
    if snapshot is None or snapshot.empty:
        return {}
    latest = snapshot.copy()
    latest.columns = [str(col).upper() for col in latest.columns]
    worst_score = safe_float(pd.to_numeric(latest.get("HEALTH_SCORE", pd.Series([100])), errors="coerce").min())
    failed_queries = _snapshot_metric(latest, "FAILED_QUERIES_24H")
    failed_tasks = _snapshot_metric(latest, "FAILED_TASKS_24H")
    queued_ms = _snapshot_metric(latest, "QUEUED_MS_24H")
    credits = _snapshot_metric(latest, "CREDITS_24H")
    cortex_cost = _snapshot_metric(latest, "CORTEX_COST_7D_USD")
    security_events = _snapshot_metric(latest, "SECURITY_EVENTS_24H")
    object_changes = _snapshot_metric(latest, "OBJECT_CHANGES_24H")

    top_risks = [
        str(value)
        for value in latest.get("TOP_RISK", pd.Series(dtype=str)).dropna().astype(str).tolist()
        if str(value).strip() and str(value).strip().lower() != "no immediate exception"
    ]
    summary = pd.DataFrame([{
        "TOTAL_QUERIES": 0,
        "FAILED_QUERIES": failed_queries,
        "QUEUED_QUERIES": 1 if queued_ms > 0 else 0,
        "REMOTE_SPILL_QUERIES": 0,
        "AVG_ELAPSED_SEC": 0,
        "P95_ELAPSED_SEC": 0,
        "ACTIVE_WAREHOUSES": 0,
        "ACTIVE_USERS": 0,
        "MART_HEALTH_SCORE": worst_score,
        "MART_TOP_RISK": ", ".join(dict.fromkeys(top_risks)) or "No immediate exception",
    }])
    credits_df = pd.DataFrame([{"PERIOD_CREDITS": credits, "PRIOR_CREDITS": 0}])
    task_failures = pd.DataFrame(
        [{"TASK_NAME": "Mart summary", "FAILURES": failed_tasks}]
    ) if failed_tasks > 0 else _empty_df()
    failed_logins = pd.DataFrame(
        [{"SIGNAL": "Failed login/security events", "EVENTS": security_events}]
    ) if security_events > 0 else _empty_df()
    object_df = pd.DataFrame(
        [{"SIGNAL": "Object or grant changes", "CHANGES": object_changes}]
    ) if object_changes > 0 else _empty_df()
    cortex_summary = pd.DataFrame([{
        "PROJECTED_30D_COST": cortex_cost / 7 * 30 if cortex_cost > 0 else 0,
        "TOTAL_COST": cortex_cost,
    }])
    return {
        "summary": summary,
        "credits": credits_df,
        "task_failures": task_failures,
        "failed_logins": failed_logins,
        "object_changes": object_df,
        "cortex_summary": cortex_summary,
        "_mart_snapshot": latest,
        "_source_modes": pd.DataFrame([
            {
                "Source": "mart_snapshot",
                "Mode": "OVERWATCH mart snapshot",
                "Message": "Company-level snapshot; use scoped detail load when environment or global filters are active.",
            },
            {"Source": "summary", "Mode": "OVERWATCH mart snapshot"},
            {"Source": "credits", "Mode": "OVERWATCH mart snapshot"},
            {"Source": "task_failures", "Mode": "OVERWATCH mart snapshot"},
            {"Source": "failed_logins", "Mode": "OVERWATCH mart snapshot"},
            {"Source": "object_changes", "Mode": "OVERWATCH mart snapshot"},
            {"Source": "cortex_cost", "Mode": "OVERWATCH mart snapshot"},
        ]),
    }


def _scalar_frame_value(data: dict, key: str, column: str, default=0):
    df = data.get(key, _empty_df())
    if df is None or df.empty or column not in df.columns:
        return default
    return df.iloc[0].get(column, default)


def _release_window_predicate(column: str, start: date, end: date) -> str:
    """Build an inclusive date-window predicate with an exclusive next-day bound."""
    start_ts = sql_literal(f"{start.isoformat()} 00:00:00")
    end_ts = sql_literal(f"{end.isoformat()} 00:00:00")
    return (
        f"{column} >= TO_TIMESTAMP_NTZ({start_ts}) "
        f"AND {column} < DATEADD('day', 1, TO_TIMESTAMP_NTZ({end_ts}))"
    )


def _clean_release_text(values: pd.Series, limit: int = 5) -> str:
    if values is None or values.empty:
        return ""
    seen: list[str] = []
    for raw in values.dropna().astype(str):
        for piece in raw.split(","):
            item = piece.strip()
            if item and item not in seen:
                seen.append(item)
            if len(seen) >= limit:
                return ", ".join(seen)
    return ", ".join(seen)


def _aggregate_release_window(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    """Normalize task/procedure run rows into comparable release-window metrics."""
    if df is None or df.empty:
        return pd.DataFrame()
    prepared = df.copy()
    prepared.columns = [str(col).upper() for col in prepared.columns]
    key_col = key_col.upper()
    if key_col not in prepared.columns:
        return pd.DataFrame()

    duration_col = "TOTAL_ELAPSED_SEC" if "TOTAL_ELAPSED_SEC" in prepared.columns else "DURATION_SEC"
    if duration_col not in prepared.columns:
        prepared[duration_col] = 0
    prepared[duration_col] = pd.to_numeric(prepared[duration_col], errors="coerce").fillna(0)
    if "EST_TOTAL_CREDITS" not in prepared.columns:
        prepared["EST_TOTAL_CREDITS"] = 0
    prepared["EST_TOTAL_CREDITS"] = pd.to_numeric(prepared["EST_TOTAL_CREDITS"], errors="coerce").fillna(0)
    if "STATE" not in prepared.columns:
        prepared["STATE"] = ""
    if "ERROR_CODE" not in prepared.columns:
        prepared["ERROR_CODE"] = ""
    if "PROCEDURE_NAME" not in prepared.columns:
        prepared["PROCEDURE_NAME"] = ""
    if "IMPACT_OBJECTS" not in prepared.columns:
        prepared["IMPACT_OBJECTS"] = ""

    prepared[key_col] = prepared[key_col].fillna("").astype(str).str.strip()
    prepared = prepared[prepared[key_col] != ""]
    if prepared.empty:
        return pd.DataFrame()

    failure_mask = (
        prepared["STATE"].fillna("").astype(str).str.upper().isin(["FAILED", "FAILED_WITH_ERROR"])
        | (prepared["ERROR_CODE"].fillna("").astype(str).str.strip() != "")
    )
    prepared["FAILED_RUN"] = failure_mask.astype(int)

    grouped = prepared.groupby(key_col, dropna=False).agg(
        RUNS=(key_col, "count"),
        FAILURES=("FAILED_RUN", "sum"),
        AVG_DURATION_SEC=(duration_col, "mean"),
        P95_DURATION_SEC=(duration_col, lambda s: float(s.quantile(0.95)) if len(s) else 0.0),
        MAX_DURATION_SEC=(duration_col, "max"),
        EST_CREDITS=("EST_TOTAL_CREDITS", "sum"),
    ).reset_index()
    grouped["PROCEDURE_NAME"] = prepared.groupby(key_col)["PROCEDURE_NAME"].apply(_clean_release_text).values
    grouped["IMPACT_OBJECTS"] = prepared.groupby(key_col)["IMPACT_OBJECTS"].apply(_clean_release_text).values
    grouped = grouped.rename(columns={key_col: "ENTITY"})
    return grouped


def _pct_change(before: float, after: float) -> float:
    before = safe_float(before)
    after = safe_float(after)
    if before == 0:
        return 100.0 if after > 0 else 0.0
    return round((after - before) / before * 100, 1)


def _release_signal(
    row: pd.Series,
    runtime_pct_threshold: float = 25,
    runtime_delta_sec_threshold: float = 30,
    credit_pct_threshold: float = 25,
    credit_delta_threshold: float = 0,
) -> tuple[str, str]:
    failure_delta = safe_int(row.get("FAILURES_DELTA"))
    runtime_pct = safe_float(row.get("AVG_DURATION_CHANGE_PCT"))
    credit_pct = safe_float(row.get("EST_CREDITS_CHANGE_PCT"))
    runtime_delta = safe_float(row.get("AVG_DURATION_DELTA_SEC"))
    credit_delta = safe_float(row.get("EST_CREDITS_DELTA"))

    signals = []
    if failure_delta > 0:
        signals.append(f"{failure_delta} more failures")
    if runtime_pct >= safe_float(runtime_pct_threshold) and runtime_delta >= safe_float(runtime_delta_sec_threshold):
        signals.append(f"runtime +{runtime_pct:.1f}%")
    if credit_pct >= safe_float(credit_pct_threshold) and credit_delta > safe_float(credit_delta_threshold):
        signals.append(f"credits +{credit_pct:.1f}%")
    if not signals:
        return "Stable", "No material release-window regression detected."

    severity = (
        "High"
        if failure_delta > 0
        or runtime_pct >= safe_float(runtime_pct_threshold) * 2
        or credit_pct >= safe_float(credit_pct_threshold) * 2
        else "Medium"
    )
    return severity, "; ".join(signals)


def _compare_release_windows(
    before: pd.DataFrame,
    after: pd.DataFrame,
    key_col: str,
    runtime_pct_threshold: float = 25,
    runtime_delta_sec_threshold: float = 30,
    credit_pct_threshold: float = 25,
    credit_delta_threshold: float = 0,
) -> pd.DataFrame:
    before_agg = _aggregate_release_window(before, key_col)
    after_agg = _aggregate_release_window(after, key_col)
    if before_agg.empty and after_agg.empty:
        return pd.DataFrame()

    merged = before_agg.merge(after_agg, on="ENTITY", how="outer", suffixes=("_BEFORE", "_AFTER")).fillna(0)
    for col in ["PROCEDURE_NAME", "IMPACT_OBJECTS"]:
        before_col = f"{col}_BEFORE"
        after_col = f"{col}_AFTER"
        if before_col not in merged.columns:
            merged[before_col] = ""
        if after_col not in merged.columns:
            merged[after_col] = ""
        merged[col] = [
            _clean_release_text(pd.Series([left, right]))
            for left, right in zip(merged[before_col], merged[after_col])
        ]

    for col in ["RUNS", "FAILURES", "AVG_DURATION_SEC", "P95_DURATION_SEC", "MAX_DURATION_SEC", "EST_CREDITS"]:
        before_col = f"{col}_BEFORE"
        after_col = f"{col}_AFTER"
        if before_col not in merged.columns:
            merged[before_col] = 0
        if after_col not in merged.columns:
            merged[after_col] = 0
        merged[f"{col}_DELTA"] = pd.to_numeric(merged[after_col], errors="coerce").fillna(0) - pd.to_numeric(
            merged[before_col], errors="coerce"
        ).fillna(0)

    merged["AVG_DURATION_CHANGE_PCT"] = [
        _pct_change(before, after)
        for before, after in zip(merged["AVG_DURATION_SEC_BEFORE"], merged["AVG_DURATION_SEC_AFTER"])
    ]
    merged["EST_CREDITS_CHANGE_PCT"] = [
        _pct_change(before, after)
        for before, after in zip(merged["EST_CREDITS_BEFORE"], merged["EST_CREDITS_AFTER"])
    ]
    signal_data = merged.apply(
        _release_signal,
        axis=1,
        runtime_pct_threshold=runtime_pct_threshold,
        runtime_delta_sec_threshold=runtime_delta_sec_threshold,
        credit_pct_threshold=credit_pct_threshold,
        credit_delta_threshold=credit_delta_threshold,
    )
    merged["SEVERITY"] = [item[0] for item in signal_data]
    merged["SIGNAL"] = [item[1] for item in signal_data]
    merged["RUNTIME_THRESHOLD_PCT"] = safe_float(runtime_pct_threshold)
    merged["RUNTIME_DELTA_THRESHOLD_SEC"] = safe_float(runtime_delta_sec_threshold)
    merged["CREDIT_THRESHOLD_PCT"] = safe_float(credit_pct_threshold)
    merged["CREDIT_DELTA_THRESHOLD"] = safe_float(credit_delta_threshold)
    return merged.sort_values(
        by=["SEVERITY", "FAILURES_DELTA", "AVG_DURATION_CHANGE_PCT", "EST_CREDITS_CHANGE_PCT"],
        ascending=[True, False, False, False],
    )


def _prepare_task_release_runs(inventory: pd.DataFrame, history: pd.DataFrame, query_details: pd.DataFrame) -> pd.DataFrame:
    _, _extract_object_candidates, _normalize_query_details, _procedure_from_definition, _ = _task_management_helpers()
    runs = history.copy() if history is not None else pd.DataFrame()
    if runs.empty:
        return runs
    runs.columns = [str(col).upper() for col in runs.columns]
    details = _normalize_query_details(query_details)
    if not details.empty and "QUERY_ID" in runs.columns and "QUERY_ID" in details.columns:
        keep = [
            col for col in [
                "QUERY_ID", "WAREHOUSE_NAME", "WAREHOUSE_SIZE", "DATABASE_NAME", "SCHEMA_NAME",
                "QUERY_ELAPSED_SEC", "CLOUD_CREDITS", "EST_TOTAL_CREDITS", "QUERY_TEXT"
            ] if col in details.columns
        ]
        runs = runs.merge(details[keep], on="QUERY_ID", how="left", suffixes=("", "_QUERY"))
    if "EST_TOTAL_CREDITS" not in runs.columns:
        runs["EST_TOTAL_CREDITS"] = 0.0
    if "QUERY_TEXT" in runs.columns:
        runs["IMPACT_OBJECTS"] = runs["QUERY_TEXT"].apply(_extract_object_candidates)
    else:
        runs["IMPACT_OBJECTS"] = ""

    inv = inventory.copy() if inventory is not None else pd.DataFrame()
    if not inv.empty:
        inv.columns = [str(col).upper() for col in inv.columns]
        name_col = "NAME" if "NAME" in inv.columns else "TASK_NAME" if "TASK_NAME" in inv.columns else ""
        if name_col:
            inv["PROCEDURE_NAME"] = inv.get("DEFINITION", pd.Series([""] * len(inv), index=inv.index)).apply(_procedure_from_definition)
            inv["TASK_IMPACT_OBJECTS"] = inv.get("DEFINITION", pd.Series([""] * len(inv), index=inv.index)).apply(_extract_object_candidates)
            runs = runs.merge(
                inv[[name_col, "PROCEDURE_NAME", "TASK_IMPACT_OBJECTS"]].rename(columns={name_col: "TASK_NAME"}),
                on="TASK_NAME",
                how="left",
            )
            runs["IMPACT_OBJECTS"] = [
                _clean_release_text(pd.Series([query_objects, task_objects]))
                for query_objects, task_objects in zip(runs.get("IMPACT_OBJECTS", ""), runs.get("TASK_IMPACT_OBJECTS", ""))
            ]
    return runs


def _build_procedure_release_sql(session, company: str, start: date, end: date, has_root_query_id: bool) -> str:
    qh_cols = set(filter_existing_columns(
        session,
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
        ["WAREHOUSE_SIZE", "CREDITS_USED_CLOUD_SERVICES"],
    ))
    root_expr = "COALESCE(q.root_query_id, q.query_id)" if has_root_query_id else "q.query_id"
    call_wh_size_expr = "warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    child_wh_size_expr = "q.warehouse_size AS warehouse_size" if "WAREHOUSE_SIZE" in qh_cols else "NULL::VARCHAR AS warehouse_size"
    child_cloud_expr = (
        "q.credits_used_cloud_services AS credits_used_cloud_services"
        if "CREDITS_USED_CLOUD_SERVICES" in qh_cols else "0::FLOAT AS credits_used_cloud_services"
    )
    call_filters = get_global_filter_clause(
        date_col="",
        wh_col="warehouse_name",
        user_col="user_name",
        role_col="role_name",
        db_col="database_name",
    )
    child_filters = get_global_filter_clause(
        date_col="",
        wh_col="q.warehouse_name",
        user_col="q.user_name",
        role_col="q.role_name",
        db_col="q.database_name",
    )
    call_window = _release_window_predicate("start_time", start, end)
    child_window = _release_window_predicate("q.start_time", start, end)
    return f"""
        WITH calls AS (
            SELECT query_id AS root_query_id,
                   REGEXP_SUBSTR(query_text, 'CALL\\\\s+([^\\\\(]+)', 1, 1, 'i', 1) AS procedure_name,
                   user_name,
                   role_name,
                   warehouse_name,
                   {call_wh_size_expr},
                   start_time,
                   SUBSTR(query_text, 1, 1000) AS call_text
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE query_type = 'CALL'
              AND {call_window}
              {call_filters}
        ),
        children AS (
            SELECT {root_expr} AS root_query_id,
                   q.query_id,
                   q.total_elapsed_time,
                   {child_cloud_expr},
                   {child_wh_size_expr}
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE {child_window}
              {child_filters}
        )
        SELECT c.procedure_name,
               c.root_query_id,
               c.user_name,
               c.role_name,
               c.warehouse_name,
               COALESCE(MAX(ch.warehouse_size), MAX(c.warehouse_size)) AS warehouse_size,
               c.start_time,
               c.call_text,
               COUNT(DISTINCT ch.query_id) AS downstream_query_count,
               SUM(COALESCE(ch.total_elapsed_time, 0)) / 1000 AS total_elapsed_sec,
               SUM(COALESCE(ch.credits_used_cloud_services, 0)) AS cloud_credits
        FROM calls c
        LEFT JOIN children ch ON c.root_query_id = ch.root_query_id
        GROUP BY c.procedure_name, c.root_query_id, c.user_name, c.role_name,
                 c.warehouse_name, c.start_time, c.call_text
        ORDER BY c.start_time DESC
        LIMIT 2000
    """


def _prepare_procedure_release_runs(runs: pd.DataFrame) -> pd.DataFrame:
    _, _extract_object_candidates, _, _, _ = _task_management_helpers()
    _, _, _procedure_run_estimated_credits, _ = _procedure_helpers()
    prepared = runs.copy() if runs is not None else pd.DataFrame()
    if prepared.empty:
        return prepared
    prepared.columns = [str(col).upper() for col in prepared.columns]
    prepared["TOTAL_ELAPSED_SEC"] = pd.to_numeric(prepared.get("TOTAL_ELAPSED_SEC", 0), errors="coerce").fillna(0)
    prepared["CLOUD_CREDITS"] = pd.to_numeric(prepared.get("CLOUD_CREDITS", 0), errors="coerce").fillna(0)
    prepared["EST_TOTAL_CREDITS"] = prepared.apply(_procedure_run_estimated_credits, axis=1)
    prepared["IMPACT_OBJECTS"] = prepared.get("CALL_TEXT", pd.Series([""] * len(prepared), index=prepared.index)).apply(
        _extract_object_candidates
    )
    return prepared


def _load_release_compare(
    session,
    company: str,
    before_start: date,
    before_end: date,
    after_start: date,
    after_end: date,
    runtime_pct_threshold: float,
    runtime_delta_sec_threshold: float,
    credit_pct_threshold: float,
    credit_delta_threshold: float,
) -> dict:
    _, _, _, _, _query_detail_sql = _task_management_helpers()
    _, _, _, _query_history_has_root_query_id = _procedure_helpers()
    task_inventory = load_task_inventory(session, company)

    def load_task_window(label: str, start: date, end: date) -> pd.DataFrame:
        history = run_query(
            build_task_history_sql(
                session,
                _release_window_predicate("scheduled_time", start, end),
                limit=2000,
                company=company,
            ),
            ttl_key=f"dba_release_{company}_{label}_{start}_{end}_task_history",
            tier="historical",
            section="DBA Control Room",
        )
        query_details = _empty_df()
        if not history.empty and "QUERY_ID" in history.columns:
            qids = history["QUERY_ID"].dropna().astype(str).tolist()
            query_sql = _query_detail_sql(session, qids)
            if query_sql:
                query_details = run_query(
                    query_sql,
                    ttl_key=f"dba_release_{company}_{label}_{start}_{end}_task_query_detail_{len(qids)}",
                    tier="historical",
                    section="DBA Control Room",
                )
        return _prepare_task_release_runs(task_inventory, history, query_details)

    has_root_query_id = _query_history_has_root_query_id(session)

    def load_proc_window(label: str, start: date, end: date) -> pd.DataFrame:
        runs = run_query(
            _build_procedure_release_sql(session, company, start, end, has_root_query_id),
            ttl_key=f"dba_release_{company}_{label}_{start}_{end}_procedure_runs_{has_root_query_id}",
            tier="historical",
            section="DBA Control Room",
        )
        return _prepare_procedure_release_runs(runs)

    task_before = load_task_window("before", before_start, before_end)
    task_after = load_task_window("after", after_start, after_end)
    proc_before = load_proc_window("before", before_start, before_end)
    proc_after = load_proc_window("after", after_start, after_end)

    return {
        "task_compare": _compare_release_windows(
            task_before,
            task_after,
            "TASK_NAME",
            runtime_pct_threshold=runtime_pct_threshold,
            runtime_delta_sec_threshold=runtime_delta_sec_threshold,
            credit_pct_threshold=credit_pct_threshold,
            credit_delta_threshold=credit_delta_threshold,
        ),
        "procedure_compare": _compare_release_windows(
            proc_before,
            proc_after,
            "PROCEDURE_NAME",
            runtime_pct_threshold=runtime_pct_threshold,
            runtime_delta_sec_threshold=runtime_delta_sec_threshold,
            credit_pct_threshold=credit_pct_threshold,
            credit_delta_threshold=credit_delta_threshold,
        ),
        "task_before": task_before,
        "task_after": task_after,
        "procedure_before": proc_before,
        "procedure_after": proc_after,
        "before_label": f"{before_start.isoformat()} to {before_end.isoformat()}",
        "after_label": f"{after_start.isoformat()} to {after_end.isoformat()}",
        "thresholds": {
            "runtime_pct_threshold": safe_float(runtime_pct_threshold),
            "runtime_delta_sec_threshold": safe_float(runtime_delta_sec_threshold),
            "credit_pct_threshold": safe_float(credit_pct_threshold),
            "credit_delta_threshold": safe_float(credit_delta_threshold),
        },
    }


def _build_release_compare_report(company: str, release_data: dict, credit_price: float) -> str:
    task_compare = release_data.get("task_compare", _empty_df())
    proc_compare = release_data.get("procedure_compare", _empty_df())
    before_label = release_data.get("before_label", "before")
    after_label = release_data.get("after_label", "after")
    thresholds = release_data.get("thresholds", {})

    task_regressions = task_compare[task_compare.get("SEVERITY", pd.Series(dtype=str)).isin(["High", "Medium"])] if not task_compare.empty else pd.DataFrame()
    proc_regressions = proc_compare[proc_compare.get("SEVERITY", pd.Series(dtype=str)).isin(["High", "Medium"])] if not proc_compare.empty else pd.DataFrame()
    total_credit_delta = (
        safe_float(task_compare.get("EST_CREDITS_DELTA", pd.Series(dtype=float)).sum() if not task_compare.empty else 0)
        + safe_float(proc_compare.get("EST_CREDITS_DELTA", pd.Series(dtype=float)).sum() if not proc_compare.empty else 0)
    )
    lines = [
        f"# OVERWATCH Release Compare - {company}",
        "",
        f"- Before window: {before_label}",
        f"- After window: {after_label}",
        (
            "- Thresholds: "
            f"runtime +{safe_float(thresholds.get('runtime_pct_threshold', 25)):,.0f}% "
            f"and +{safe_float(thresholds.get('runtime_delta_sec_threshold', 30)):,.0f}s; "
            f"credits +{safe_float(thresholds.get('credit_pct_threshold', 25)):,.0f}% "
            f"and +{safe_float(thresholds.get('credit_delta_threshold', 0)):,.4f} credits"
        ),
        f"- Task regressions: {len(task_regressions):,}",
        f"- Procedure regressions: {len(proc_regressions):,}",
        f"- Estimated credit delta: {format_credits(total_credit_delta)} (${credits_to_dollars(total_credit_delta, credit_price):,.2f})",
        "",
        "## Highest-Risk Task Changes",
    ]
    if task_regressions.empty:
        lines.append("- No material task runtime/cost/failure regressions detected.")
    else:
        for _, row in task_regressions.head(10).iterrows():
            lines.append(
                f"- {row.get('ENTITY', '')}: {row.get('SIGNAL', '')}; "
                f"after avg {safe_float(row.get('AVG_DURATION_SEC_AFTER')):,.1f}s; "
                f"procedure {row.get('PROCEDURE_NAME', '')}; impact {row.get('IMPACT_OBJECTS', '')}"
            )
    lines.extend(["", "## Highest-Risk Procedure Changes"])
    if proc_regressions.empty:
        lines.append("- No material stored procedure runtime/cost/failure regressions detected.")
    else:
        for _, row in proc_regressions.head(10).iterrows():
            lines.append(
                f"- {row.get('ENTITY', '')}: {row.get('SIGNAL', '')}; "
                f"after avg {safe_float(row.get('AVG_DURATION_SEC_AFTER')):,.1f}s; "
                f"credit delta {format_credits(row.get('EST_CREDITS_DELTA', 0))}"
            )
    return "\n".join(lines)


def _finalize_control_room_data(
    data: dict[str, pd.DataFrame],
    source_rows: list[dict],
    credit_price: float,
    cortex_budget_usd: float,
) -> dict[str, pd.DataFrame]:
    data["_loaded_at"] = pd.DataFrame({"LOADED_AT": [datetime.now().isoformat()]})
    data["_credit_price"] = pd.DataFrame({"CREDIT_PRICE": [credit_price]})
    data["_cortex_budget_usd"] = pd.DataFrame({"BUDGET_USD": [safe_float(cortex_budget_usd)]})
    data["_source_modes"] = pd.DataFrame(source_rows)
    return data


def _load_control_room(
    session,
    company: str,
    credit_price: float,
    lookback_hours: int,
    cortex_budget_usd: float,
    *,
    include_deep_evidence: bool = False,
    allow_live_fallback: bool = False,
) -> dict:
    _build_task_ops_frames, _, _, _, _query_detail_sql = _task_management_helpers()
    _build_procedure_sla_frames, _build_procedure_sla_sql, _, _query_history_has_root_query_id = _procedure_helpers()
    _build_cortex_control_sql, _, _ = _cortex_helpers()
    wh_q = get_wh_filter_clause("q.warehouse_name", company)
    wh_m = get_wh_filter_clause("warehouse_name", company)
    db_q = get_db_filter_clause("q.database_name", company)
    user_q = get_user_filter_clause("q.user_name", company)
    global_q = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
    )
    live_lookback_hours = min(int(lookback_hours), DBA_CONTROL_ROOM_LIVE_FALLBACK_CAP_HOURS)

    data: dict[str, pd.DataFrame] = {}
    queries = {
        "summary": f"""
            SELECT
                COUNT(*) AS total_queries,
                SUM(CASE WHEN error_code IS NOT NULL
                           OR UPPER(execution_status) = 'FAILED_WITH_ERROR'
                         THEN 1 ELSE 0 END) AS failed_queries,
                SUM(CASE WHEN COALESCE(queued_overload_time, 0)
                            + COALESCE(queued_provisioning_time, 0)
                            + COALESCE(queued_repair_time, 0) > 0
                         THEN 1 ELSE 0 END) AS queued_queries,
                SUM(CASE WHEN COALESCE(bytes_spilled_to_remote_storage, 0) > 0
                         THEN 1 ELSE 0 END) AS remote_spill_queries,
                ROUND(AVG(total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                ROUND(APPROX_PERCENTILE(total_elapsed_time / 1000, 0.95), 2) AS p95_elapsed_sec,
                COUNT(DISTINCT warehouse_name) AS active_warehouses,
                COUNT(DISTINCT user_name) AS active_users
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {global_q}
        """,
        "credits": f"""
            SELECT
                SUM(CASE WHEN start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
                         THEN credits_used ELSE 0 END) AS period_credits,
                SUM(CASE WHEN start_time >= DATEADD('hour', -{int(live_lookback_hours * 2)}, CURRENT_TIMESTAMP())
                          AND start_time < DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
                         THEN credits_used ELSE 0 END) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE start_time >= DATEADD('hour', -{int(live_lookback_hours * 2)}, CURRENT_TIMESTAMP())
              {wh_m}
        """,
        "cost_drivers": f"""
            WITH {build_metered_credit_cte(hours_back=live_lookback_hours, include_recent=True)}
            SELECT
                q.user_name,
                q.warehouse_name,
                COUNT(*) AS query_count,
                ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                ROUND(SUM(COALESCE(q.bytes_scanned, 0)) / POWER(1024, 3), 2) AS gb_scanned,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
            WHERE q.start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {global_q}
            GROUP BY q.user_name, q.warehouse_name
            HAVING SUM(COALESCE(pqc.metered_credits, 0)) > 0
            ORDER BY allocated_credits DESC
            LIMIT 10
        """,
        "warehouse_pressure": f"""
            SELECT
                q.warehouse_name,
                MAX(q.warehouse_size) AS warehouse_size,
                COUNT(*) AS total_queries,
                SUM(CASE WHEN COALESCE(q.queued_overload_time, 0)
                            + COALESCE(q.queued_provisioning_time, 0)
                            + COALESCE(q.queued_repair_time, 0) > 0
                         THEN 1 ELSE 0 END) AS queued_queries,
                SUM(CASE WHEN COALESCE(q.bytes_spilled_to_remote_storage, 0) > 0
                         THEN 1 ELSE 0 END) AS remote_spill_queries,
                ROUND(SUM(COALESCE(q.bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2) AS remote_spill_gb,
                ROUND(APPROX_PERCENTILE(q.total_elapsed_time / 1000, 0.95), 2) AS p95_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {wh_q} {db_q} {user_q}
            GROUP BY q.warehouse_name
            HAVING queued_queries > 0 OR remote_spill_queries > 0 OR p95_elapsed_sec >= 60
            ORDER BY queued_queries DESC, remote_spill_gb DESC, p95_elapsed_sec DESC
            LIMIT 10
        """,
        "failed_queries": f"""
            SELECT
                q.query_id,
                q.user_name,
                q.role_name,
                q.warehouse_name,
                q.database_name,
                q.query_type,
                q.error_code,
                LEFT(q.error_message, 240) AS error_message,
                q.start_time
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND (q.error_code IS NOT NULL OR UPPER(q.execution_status) = 'FAILED_WITH_ERROR')
              {wh_q} {db_q} {user_q}
            ORDER BY q.start_time DESC
            LIMIT 25
        """,
        "object_changes": f"""
            SELECT
                q.start_time,
                q.user_name,
                q.role_name,
                q.query_type,
                q.database_name,
                q.schema_name,
                q.warehouse_name,
                LEFT(q.query_text, 220) AS query_preview
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND (
                    q.query_type ILIKE 'CREATE%'
                 OR q.query_type ILIKE 'ALTER%'
                 OR q.query_type ILIKE 'DROP%'
                 OR q.query_type ILIKE 'GRANT%'
                 OR q.query_type ILIKE 'REVOKE%'
              )
              {wh_q} {db_q} {user_q}
            ORDER BY q.start_time DESC
            LIMIT 25
        """,
        "failed_logins": f"""
            SELECT
                event_timestamp,
                user_name,
                client_ip,
                reported_client_type,
                error_code,
                error_message
            FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
            WHERE event_timestamp >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND is_success = 'NO'
              {get_user_filter_clause("user_name", company)}
            ORDER BY event_timestamp DESC
            LIMIT 25
        """,
    }

    mart_queries = {
        "summary": build_mart_control_room_summary_sql(lookback_hours, company),
        "credits": build_mart_control_room_credits_sql(lookback_hours, company),
        "cost_drivers": build_mart_control_room_cost_drivers_sql(lookback_hours, company),
        "warehouse_pressure": build_mart_control_room_warehouse_pressure_sql(lookback_hours, company),
        "failed_queries": build_mart_control_room_failed_queries_sql(lookback_hours, company),
        "object_changes": build_mart_control_room_object_changes_sql(lookback_hours, company),
        "failed_logins": build_mart_control_room_failed_logins_sql(lookback_hours, company),
    }
    source_rows: list[dict] = []
    for key, sql in queries.items():
        try:
            try:
                data[key] = run_query(
                    mart_queries[key],
                    ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_{key}",
                    tier="historical",
                    section="DBA Control Room",
                )
                source_rows.append({"Source": key, "Mode": "OVERWATCH mart"})
            except Exception as mart_exc:
                if not allow_live_fallback:
                    data[key] = _empty_df()
                    data[f"{key}_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                    source_rows.append({
                        "Source": key,
                        "Mode": "Mart unavailable",
                        "Message": "Live fallback skipped to keep DBA Control Room responsive.",
                    })
                    continue
                if key not in DBA_CONTROL_ROOM_LIVE_FALLBACK_KEYS:
                    data[key] = _empty_df()
                    data[f"{key}_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                    source_rows.append({
                        "Source": key,
                        "Mode": "Live fallback deferred",
                        "Message": _live_fallback_deferred_message(key, mart_exc),
                    })
                    continue
                data[key] = run_query(
                    sql,
                    ttl_key=f"dba_control_room_live_{company}_{live_lookback_hours}_{key}",
                    tier="recent",
                    section="DBA Control Room",
                )
                source_rows.append({
                    "Source": key,
                    "Mode": "Limited live fallback",
                    "Message": (
                        f"Mart unavailable; ran a bounded ACCOUNT_USAGE probe capped at "
                        f"{live_lookback_hours}h. {format_snowflake_error(mart_exc)}"
                    ),
                })
        except Exception as exc:
            data[key] = _empty_df()
            data[f"{key}_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        try:
            data["task_failures"] = run_query(
                build_mart_control_room_task_failures_sql(lookback_hours, company),
                ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_task_failures",
                tier="historical",
                section="DBA Control Room",
            )
            source_rows.append({"Source": "task_failures", "Mode": "OVERWATCH mart"})
        except Exception as mart_exc:
            if not allow_live_fallback:
                data["task_failures"] = _empty_df()
                data["task_failures_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                source_rows.append({
                    "Source": "task_failures",
                    "Mode": "Mart unavailable",
                    "Message": "Live fallback skipped to keep DBA Control Room responsive.",
                })
            else:
                data["task_failures"] = _empty_df()
                data["task_failures_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                source_rows.append({
                    "Source": "task_failures",
                    "Mode": "Live fallback deferred",
                    "Message": _live_fallback_deferred_message("task_failures", mart_exc),
                })
    except Exception as exc:
        data["task_failures"] = _empty_df()
        data["task_failures_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    if not include_deep_evidence:
        data["task_sla_cost"] = _empty_df()
        data["task_latest_runs"] = _empty_df()
        data["procedure_sla_cost"] = _empty_df()
        data["procedure_latest_runs"] = _empty_df()
        data["cortex_summary"] = _empty_df()
        data["cortex_exceptions"] = _empty_df()
        source_rows.extend([
            {
                "Source": "task_sla_history",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Workload Operations for task run evidence.",
            },
            {
                "Source": "procedure_sla",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Workload Operations for procedure SLA/cost evidence.",
            },
            {
                "Source": "cortex_cost",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Cost & Contract for Cortex cost evidence.",
            },
        ])
        try:
            data["action_queue"] = load_action_queue(session, limit=25)
        except Exception as exc:
            data["action_queue"] = _empty_df()
            data["action_queue_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})
        return _finalize_control_room_data(data, source_rows, credit_price, cortex_budget_usd)

    try:
        task_inventory = load_task_inventory(session, company)
        task_history_source = "OVERWATCH mart"
        try:
            task_history = run_query(
                build_mart_task_history_sql(max(1, int((lookback_hours + 23) / 24)), company=company, limit=1000),
                ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_task_sla_history",
                tier="historical",
                section="DBA Control Room",
            )
        except Exception as mart_exc:
            if not allow_live_fallback:
                task_history_source = "Mart unavailable"
                task_history = _empty_df()
            else:
                task_history_source = "Live fallback deferred"
                task_history = _empty_df()
            source_rows.append({
                "Source": "task_sla_history",
                "Mode": task_history_source,
                "Message": (
                    "Live fallback skipped to keep DBA Control Room responsive."
                    if not allow_live_fallback
                    else _live_fallback_deferred_message("task_sla_history", mart_exc)
                ),
            })
        if task_history_source == "OVERWATCH mart":
            source_rows.append({"Source": "task_sla_history", "Mode": task_history_source})
        task_query_details = _empty_df()
        if not task_history.empty and "QUERY_ID" in task_history.columns:
            qids = task_history["QUERY_ID"].dropna().astype(str).tolist()
            try:
                query_sql = build_mart_query_detail_recent_sql(qids)
                if query_sql:
                    task_query_details = run_query(
                        query_sql,
                        ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_task_query_detail_{len(qids)}",
                        tier="historical",
                        section="DBA Control Room",
                    )
                    source_rows.append({"Source": "task_query_detail", "Mode": "OVERWATCH mart"})
            except Exception as mart_exc:
                source_rows.append({
                    "Source": "task_query_detail",
                    "Mode": "Live fallback deferred",
                    "Message": _live_fallback_deferred_message("task_query_detail", mart_exc),
                })
        _, task_ops_exceptions, task_latest = _build_task_ops_frames(task_inventory, task_history, task_query_details)
        data["task_sla_cost"] = task_ops_exceptions[
            task_ops_exceptions.get("SIGNAL", pd.Series(dtype=str)).isin([
                "Long Running / SLA Risk",
                "Cost Drift / Release Regression",
            ])
        ].copy() if not task_ops_exceptions.empty else _empty_df()
        data["task_latest_runs"] = task_latest
    except Exception as exc:
        data["task_sla_cost"] = _empty_df()
        data["task_latest_runs"] = _empty_df()
        data["task_sla_cost_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        try:
            proc_runs = run_query(
                build_mart_procedure_sla_sql(max(1, int((lookback_hours + 23) / 24)), company=company),
                ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_procedure_sla",
                tier="historical",
                section="DBA Control Room",
            )
            source_rows.append({"Source": "procedure_sla", "Mode": "OVERWATCH mart"})
        except Exception as mart_exc:
            proc_runs = _empty_df()
            source_rows.append({
                "Source": "procedure_sla",
                "Mode": "Live fallback deferred" if allow_live_fallback else "Mart unavailable",
                "Message": (
                    _live_fallback_deferred_message("procedure_sla", mart_exc)
                    if allow_live_fallback
                    else "Live fallback skipped to keep DBA Control Room responsive."
                ),
            })
        _, proc_exceptions, proc_latest = _build_procedure_sla_frames(proc_runs)
        data["procedure_sla_cost"] = proc_exceptions
        data["procedure_latest_runs"] = proc_latest
    except Exception as exc:
        data["procedure_sla_cost"] = _empty_df()
        data["procedure_latest_runs"] = _empty_df()
        data["procedure_sla_cost_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        data["action_queue"] = load_action_queue(session, limit=100)
    except Exception as exc:
        data["action_queue"] = _empty_df()
        data["action_queue_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        cortex_summary_sql, cortex_exceptions_sql = _build_cortex_control_sql(30, cortex_budget_usd)
        data["cortex_summary"] = run_query(
            cortex_summary_sql,
            ttl_key=f"dba_control_room_{company}_cortex_summary_{cortex_budget_usd}",
            tier="historical",
            section="DBA Control Room",
        )
        data["cortex_exceptions"] = run_query(
            cortex_exceptions_sql,
            ttl_key=f"dba_control_room_{company}_cortex_exceptions_{cortex_budget_usd}",
            tier="historical",
            section="DBA Control Room",
        )
    except Exception as exc:
        data["cortex_summary"] = _empty_df()
        data["cortex_exceptions"] = _empty_df()
        cortex_error = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})
        data["cortex_summary_error"] = cortex_error
        data["cortex_exceptions_error"] = cortex_error

    data["_loaded_at"] = pd.DataFrame({"LOADED_AT": [datetime.now().isoformat()]})
    data["_credit_price"] = pd.DataFrame({"CREDIT_PRICE": [credit_price]})
    data["_cortex_budget_usd"] = pd.DataFrame({"BUDGET_USD": [safe_float(cortex_budget_usd)]})
    data["_source_modes"] = pd.DataFrame(source_rows)
    return data


def _severity_rows(data: dict, credit_price: float) -> pd.DataFrame:
    _, _cortex_cost_rating, _cortex_cost_score = _cortex_helpers()
    summary = data.get("summary", _empty_df())
    credits = data.get("credits", _empty_df())
    wh = data.get("warehouse_pressure", _empty_df())
    failed = data.get("failed_queries", _empty_df())
    tasks = data.get("task_failures", _empty_df())
    task_sla_cost = data.get("task_sla_cost", _empty_df())
    procedure_sla_cost = data.get("procedure_sla_cost", _empty_df())
    cortex_summary = data.get("cortex_summary", _empty_df())
    cortex_exceptions = data.get("cortex_exceptions", _empty_df())
    logins = data.get("failed_logins", _empty_df())
    changes = data.get("object_changes", _empty_df())
    queue = data.get("action_queue", _empty_df())

    row = summary.iloc[0] if not summary.empty else {}
    cr = credits.iloc[0] if not credits.empty else {}
    period_credits = safe_float(cr.get("PERIOD_CREDITS", 0))
    prior_credits = safe_float(cr.get("PRIOR_CREDITS", 0))
    credit_delta = ((period_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0

    rows = []
    failed_queries = safe_int(row.get("FAILED_QUERIES", 0))
    queued_queries = safe_int(row.get("QUEUED_QUERIES", 0))
    spill_queries = safe_int(row.get("REMOTE_SPILL_QUERIES", 0))
    p95 = safe_float(row.get("P95_ELAPSED_SEC", 0))

    if failed_queries:
        rows.append({
            "Severity": "High" if failed_queries >= 10 else "Medium",
            "Signal": "Query failures",
            "Evidence": f"{failed_queries:,} failed queries in lookback",
            "Action": "Review failed SQL and recurring error patterns.",
            "Route": "Workload Operations",
            "Workflow": "Query diagnosis",
        })
    if queued_queries or not wh.empty:
        rows.append({
            "Severity": "High" if queued_queries >= 20 else "Medium",
            "Signal": "Queue or warehouse pressure",
            "Evidence": f"{queued_queries:,} queued queries; {len(wh):,} pressured warehouses",
            "Action": "Check warehouse sizing, clustering, and concurrency pressure.",
            "Route": "Warehouse Health",
            "Workflow": "",
        })
    if spill_queries:
        rows.append({
            "Severity": "High" if spill_queries >= 10 else "Medium",
            "Signal": "Remote spill",
            "Evidence": f"{spill_queries:,} queries spilled to remote storage",
            "Action": "Inspect spilling queries before resizing.",
            "Route": "Warehouse Health",
            "Workflow": "",
        })
    if p95 >= 120:
        rows.append({
            "Severity": "Medium",
            "Signal": "High p95 duration",
            "Evidence": f"p95 elapsed {p95:,.0f}s",
            "Action": "Investigate slow-query plan and operator stats.",
            "Route": "Workload Operations",
            "Workflow": "Query diagnosis",
        })
    if credit_delta >= 25:
        rows.append({
            "Severity": "High" if credit_delta >= 60 else "Medium",
            "Signal": "Credit spike",
            "Evidence": f"{credit_delta:+.1f}% vs prior window; est. ${credits_to_dollars(period_credits, credit_price):,.0f}",
            "Action": "Identify top users, warehouses, tasks, and query patterns.",
            "Route": "Cost & Contract",
            "Workflow": "Explain bill / attribution / contract",
        })
    if not tasks.empty:
        rows.append({
            "Severity": "High",
            "Signal": "Task failures",
            "Evidence": f"{len(tasks):,} failed task groups",
            "Action": "Review task history, retry logic, and downstream load impact.",
            "Route": "Workload Operations",
            "Workflow": "Task graphs",
        })
    if not task_sla_cost.empty:
        signals = task_sla_cost.get("SIGNAL", pd.Series(dtype=str)).astype(str)
        sla_count = int((signals == "Long Running / SLA Risk").sum())
        cost_count = int((signals == "Cost Drift / Release Regression").sum())
        rows.append({
            "Severity": "High" if cost_count or sla_count >= 3 else "Medium",
            "Signal": "Task SLA or cost regression",
            "Evidence": f"{sla_count:,} runtime breach(es); {cost_count:,} cost regression candidate(s)",
            "Action": "Compare current task graph runs to recent baseline and inspect release-related procedure/query changes.",
            "Route": "Workload Operations",
            "Workflow": "Task graphs",
        })
    if not procedure_sla_cost.empty:
        signals = procedure_sla_cost.get("SIGNAL", pd.Series(dtype=str)).astype(str)
        runtime_count = int((signals == "Procedure Runtime SLA Breach").sum())
        cost_count = int((signals == "Procedure Cost Regression").sum())
        rows.append({
            "Severity": "High" if cost_count or runtime_count >= 3 else "Medium",
            "Signal": "Stored procedure release regression",
            "Evidence": f"{runtime_count:,} runtime breach(es); {cost_count:,} cost regression candidate(s)",
            "Action": "Review procedures whose latest CALL duration or estimated credits jumped after the release.",
            "Route": "Workload Operations",
            "Workflow": "Stored procedures",
        })
    if not cortex_summary.empty:
        cortex_budget = safe_float(_scalar_frame_value(data, "_cortex_budget_usd", "BUDGET_USD", 0))
        cortex_row = cortex_summary.iloc[0]
        projected_cost = safe_float(cortex_row.get("PROJECTED_30D_COST", 0))
        score = _cortex_cost_score(
            projected_cost=projected_cost,
            budget_usd=cortex_budget,
            spike_users=safe_int(cortex_row.get("HEAVY_USERS", 0)),
            active_users=safe_int(cortex_row.get("ACTIVE_USERS", 0)),
        )
        if projected_cost > cortex_budget or score < 78 or not cortex_exceptions.empty:
            rows.append({
                "Severity": "High" if projected_cost > cortex_budget or score < 65 else "Medium",
                "Signal": "Cortex / AI cost risk",
                "Evidence": (
                    f"Projected 30-day Cortex cost ${projected_cost:,.0f} vs ${cortex_budget:,.0f} budget; "
                    f"{len(cortex_exceptions):,} user/source exception(s); score {score} ({_cortex_cost_rating(score)})"
                ),
                "Action": "Review Cortex users, source split, cost-per-request spikes, and daily credit guardrails.",
                "Route": "Cost & Contract",
                "Workflow": "AI and Cortex spend",
            })
    if not logins.empty:
        rows.append({
            "Severity": "Medium",
            "Signal": "Failed logins",
            "Evidence": f"{len(logins):,} recent failed login records",
            "Action": "Review source IPs, user posture, MFA, and client versions.",
            "Route": "Security Posture",
            "Workflow": "Access posture",
        })
    if not changes.empty:
        rows.append({
            "Severity": "Medium",
            "Signal": "Object or grant changes",
            "Evidence": f"{len(changes):,} recent DDL/access changes",
            "Action": "Validate expected change windows and ownership.",
            "Route": "Change & Drift",
            "Workflow": "Object and access changes",
        })
    if not queue.empty:
        status = queue.get("STATUS", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str).str.upper()
        open_queue = queue[~status.isin(["FIXED", "IGNORED"])] if "STATUS" in queue.columns else queue
        if not open_queue.empty:
            rows.append({
                "Severity": "Medium",
                "Signal": "Open action queue",
                "Evidence": f"{len(open_queue):,} open recommendations",
                "Action": "Assign owners and move items toward fixed/ignored.",
                "Route": "Cost & Contract",
                "Workflow": "Recommendations and action queue",
            })
        closure = _command_queue_closure_readiness(queue)
        if not closure.empty:
            closure_blockers = closure[
                (closure["CLOSURE_RANK"] <= 3)
                | (closure["CLOSURE_BLOCKER_ROWS"] > 0)
            ]
            if not closure_blockers.empty:
                overdue = int(closure_blockers.get("OVERDUE_OPEN", pd.Series(dtype=int)).sum())
                unverified = int(closure_blockers.get("FIXED_WITHOUT_VERIFICATION", pd.Series(dtype=int)).sum())
                recovery = int(closure_blockers.get("RECOVERY_RISK_ROWS", pd.Series(dtype=int)).sum())
                rows.append({
                    "Severity": "High" if overdue or unverified else "Medium",
                    "Signal": "Closure evidence blockers",
                    "Evidence": (
                        f"{len(closure_blockers):,} route(s) blocked; {overdue:,} overdue, "
                        f"{unverified:,} fixed without verification, {recovery:,} recovery evidence risk."
                    ),
                    "Action": "Use DBA Command Queue Control to close proof, approval, ticket, and recovery gaps.",
                    "Route": "DBA Control Room",
                    "Workflow": "Action Queue",
                })

    return pd.DataFrame(rows)


def _priority_exceptions(exceptions: pd.DataFrame) -> pd.DataFrame:
    if exceptions is None or exceptions.empty:
        return _empty_df()
    severity_rank = {"High": 0, "Medium": 1, "Low": 2}
    view = exceptions.copy()
    view["_RANK"] = view.get("Severity", pd.Series(dtype=str)).map(severity_rank).fillna(3)
    return view.sort_values(["_RANK", "Signal"]).drop(columns=["_RANK"], errors="ignore")


def _command_queue_route(category: object) -> str:
    value = str(category or "").upper()
    if "COST" in value:
        return "Cost & Contract"
    if "ACCOUNT" in value or "CHECKLIST" in value:
        return "Account Health"
    if "TASK" in value or "PROCEDURE" in value or "RELIABILITY" in value:
        return "Workload Operations"
    if "SECURITY" in value or "ACCESS" in value or "GRANT" in value:
        return "Security Posture"
    if "CHANGE" in value or "DRIFT" in value or "GOVERNANCE" in value:
        return "Change & Drift"
    if "WAREHOUSE" in value or "CAPACITY" in value:
        return "Warehouse Health"
    return "Alert Center"


def _command_owner_entity_type(row: pd.Series | dict) -> str:
    route = str(row.get("ROUTE") or _command_queue_route(row.get("CATEGORY"))).upper()
    category = str(row.get("CATEGORY") or "").upper()
    entity_type = str(row.get("ENTITY_TYPE") or "").upper()
    if entity_type:
        return entity_type
    if "COST" in route or "COST" in category:
        return "COST_CONTROL"
    if "WAREHOUSE" in route or "WAREHOUSE" in category:
        return "WAREHOUSE"
    if "SECURITY" in route or any(token in category for token in ("SECURITY", "ACCESS", "GRANT", "ROLE")):
        return "SECURITY"
    if "CHANGE" in route or "DRIFT" in route or any(token in category for token in ("CHANGE", "DRIFT", "DDL")):
        return "CHANGE_CONTROL"
    if any(token in category for token in ("PROCEDURE", "PROC")):
        return "PROCEDURE"
    if "WORKLOAD" in route or "TASK" in category:
        return "TASK"
    if "ACCOUNT" in route or "CHECKLIST" in category:
        return "ACCOUNT_HEALTH"
    return "ALERT"


def _command_value_present(row: pd.Series, *columns: str) -> bool:
    """Return whether any queue metadata column has a non-placeholder value."""
    for column in columns:
        value = row.get(column)
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        text = str(value).strip()
        if text and text.upper() not in {"N/A", "NONE", "NULL", "NAN", "<NA>", "UNKNOWN"}:
            return True
    return False


def _command_text_present(value: object, min_length: int = 1) -> bool:
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        if value is None:
            return False
    text = str(value).strip()
    return len(text) >= max(1, int(min_length))


def _command_named_owner(row: pd.Series) -> bool:
    owner = str(row.get("OWNER") or "").strip().upper()
    return bool(owner and owner not in {
        "N/A",
        "NONE",
        "NULL",
        "UNKNOWN",
        "UNKNOWN USER",
        "UNKNOWN WAREHOUSE",
        "DBA",
        "DBA LEAD",
        "DBA / FINOPS",
        "DBA / PLATFORM",
        "DBA / SECURITY",
        "DBA / WORKLOAD OWNER",
        "DBA / PIPELINE OWNER",
        "DBA / PROCEDURE OWNER",
        "DBA / DATA ENGINEERING",
        "DBA CHANGE OWNER",
        "DBA QUERY TRIAGE",
        "PLATFORM DBA",
        "SECURITY/DBA",
    })


def _enrich_command_owner_context(view: pd.DataFrame) -> pd.DataFrame:
    """Add shared owner-directory routing fields to command queue rows."""
    if view is None or view.empty:
        return view
    enriched = view.copy()
    contexts = enriched.apply(
        lambda row: resolve_owner_context(
            row,
            entity=row.get("ENTITY_NAME") or row.get("ENTITY") or row.get("TASK_NAME") or row.get("PROCEDURE_NAME"),
            entity_type=_command_owner_entity_type(row),
            owner=row.get("OWNER"),
            category=row.get("CATEGORY"),
            alert_type=row.get("SOURCE"),
        ),
        axis=1,
    )
    for column in _utils.OWNER_CONTEXT_COLUMNS:
        enriched[column] = contexts.apply(lambda context: context.get(column, ""))
    return enriched


def _command_requires_approval(row: pd.Series) -> bool:
    category = str(row.get("CATEGORY") or "").upper()
    severity = str(row.get("SEVERITY") or "").upper()
    source = str(row.get("SOURCE") or "").upper()
    controlled_domains = (
        "COST",
        "WAREHOUSE",
        "SECURITY",
        "ACCESS",
        "GRANT",
        "CHANGE",
        "DRIFT",
        "TASK",
        "PROCEDURE",
        "RELIABILITY",
    )
    return severity in {"CRITICAL", "HIGH"} or any(token in category or token in source for token in controlled_domains)


def _command_closure_issue_flags(row: pd.Series) -> dict:
    status = str(row.get("STATUS") or "").strip().upper()
    due_state = str(row.get("DUE_STATE") or "").strip()
    verification_status = str(row.get("VERIFICATION_STATUS") or "").strip().upper()
    owner_approval_status = str(row.get("OWNER_APPROVAL_STATUS") or "").strip().upper()
    recovery_state = str(row.get("RECOVERY_SLA_STATE") or "").strip().upper()
    is_open = status not in {"FIXED", "IGNORED"}
    is_fixed = status == "FIXED"
    verified = (
        is_fixed
        and verification_status == "VERIFIED"
        and _command_text_present(row.get("VERIFICATION_RESULT"), min_length=15)
    )
    fixed_without_verification = is_fixed and not verified
    metadata_gaps = {
        "OWNER_GAP_ROWS": 0 if _command_named_owner(row) else 1,
        "TICKET_GAP_ROWS": 0 if _command_value_present(row, "TICKET_ID") else 1,
        "APPROVER_GAP_ROWS": 0 if _command_value_present(row, "APPROVER") else 1,
        "VERIFICATION_QUERY_GAP_ROWS": 0 if _command_value_present(row, "VERIFICATION_QUERY", "PROOF_QUERY") else 1,
        "OWNER_APPROVAL_GAP_ROWS": 1 if owner_approval_status in {"", "PENDING", "REQUESTED", "REQUIRED"} else 0,
    }
    recovery_risk = (
        "BREACH" in recovery_state
        or "LATE" in recovery_state
        or (is_fixed and not _command_text_present(row.get("RECOVERY_EVIDENCE"), min_length=15))
    )
    blocker_count = (
        int(due_state == "Overdue")
        + int(fixed_without_verification)
        + sum(metadata_gaps.values())
        + int(recovery_risk)
    )
    return {
        "IS_OPEN": int(is_open),
        "IS_FIXED": int(is_fixed),
        "VERIFIED_CLOSURE": int(verified),
        "FIXED_WITHOUT_VERIFICATION": int(fixed_without_verification),
        "OVERDUE_OPEN": int(is_open and due_state == "Overdue"),
        "RECOVERY_RISK_ROWS": int(recovery_risk),
        "CLOSURE_BLOCKER_ROWS": int(blocker_count > 0),
        **metadata_gaps,
    }


def _command_closure_next_action(row: pd.Series | dict) -> str:
    if safe_int(row.get("OVERDUE_OPEN", 0)):
        return "Escalate overdue work, confirm the owner, and attach ticket plus verification evidence."
    if safe_int(row.get("FIXED_WITHOUT_VERIFICATION", 0)):
        return "Attach verification result/notes or reopen fixed items that lack proof."
    if safe_int(row.get("RECOVERY_RISK_ROWS", 0)):
        return "Attach recovery evidence or reopen items with breached/late closure state."
    metadata_gaps = (
        safe_int(row.get("OWNER_GAP_ROWS", 0))
        + safe_int(row.get("TICKET_GAP_ROWS", 0))
        + safe_int(row.get("APPROVER_GAP_ROWS", 0))
        + safe_int(row.get("VERIFICATION_QUERY_GAP_ROWS", 0))
        + safe_int(row.get("OWNER_APPROVAL_GAP_ROWS", 0))
    )
    if metadata_gaps:
        return "Complete owner, ticket, approver, approval, and verification metadata."
    if safe_int(row.get("OPEN_ACTIONS", 0)):
        return "Work open actions and keep before/after proof ready for closure."
    return "Retain verified closure evidence for audit and trend review."


def _command_queue_closure_readiness(queue: pd.DataFrame, today: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Summarize closure blockers across all action queue rows by DBA route."""
    if queue is None or queue.empty:
        return _empty_df()

    view = enrich_action_queue_view(queue, today=today).copy()
    if view.empty:
        return _empty_df()
    view["ROUTE"] = view.get("CATEGORY", pd.Series([""] * len(view), index=view.index)).apply(_command_queue_route)
    view = _enrich_command_owner_context(view)
    flags = view.apply(_command_closure_issue_flags, axis=1, result_type="expand")
    for column in flags.columns:
        view[column] = flags[column]

    blocker_cols = [
        "FIXED_WITHOUT_VERIFICATION", "OVERDUE_OPEN", "OWNER_GAP_ROWS",
        "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
        "OWNER_APPROVAL_GAP_ROWS", "RECOVERY_RISK_ROWS", "CLOSURE_BLOCKER_ROWS",
    ]
    source_series = view.get("SOURCE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    category_series = view.get("CATEGORY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    owner_series = view.get("OWNER", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    updated_series = pd.to_datetime(
        view.get("UPDATED_AT", view.get("CREATED_AT", pd.Series([pd.NaT] * len(view), index=view.index))),
        errors="coerce",
    )
    view["_LAST_ACTIVITY_TS"] = updated_series
    rows: list[dict] = []
    for route, group in view.groupby(view["ROUTE"].fillna("Alert Center")):
        latest_idx = group["_LAST_ACTIVITY_TS"].idxmax() if group["_LAST_ACTIVITY_TS"].notna().any() else group.index[-1]
        totals = {
            "TOTAL_ACTIONS": int(len(group)),
            "OPEN_ACTIONS": int(group["IS_OPEN"].sum()),
            "FIXED_ACTIONS": int(group["IS_FIXED"].sum()),
            "VERIFIED_CLOSURES": int(group["VERIFIED_CLOSURE"].sum()),
        }
        for column in blocker_cols:
            totals[column] = int(group[column].sum())
        metadata_gaps = (
            totals["OWNER_GAP_ROWS"]
            + totals["TICKET_GAP_ROWS"]
            + totals["APPROVER_GAP_ROWS"]
            + totals["VERIFICATION_QUERY_GAP_ROWS"]
            + totals["OWNER_APPROVAL_GAP_ROWS"]
        )
        if totals["OVERDUE_OPEN"]:
            readiness, rank = "Overdue closure", 0
        elif totals["FIXED_WITHOUT_VERIFICATION"]:
            readiness, rank = "Fixed without verification", 1
        elif totals["RECOVERY_RISK_ROWS"]:
            readiness, rank = "Recovery evidence risk", 2
        elif metadata_gaps:
            readiness, rank = "Control metadata gap", 3
        elif totals["OPEN_ACTIONS"]:
            readiness, rank = "Open", 4
        elif totals["VERIFIED_CLOSURES"]:
            readiness, rank = "Verified closure", 8
        else:
            readiness, rank = "No recent action", 9
        latest = group.loc[latest_idx]
        row = {
            "ROUTE": route,
            "CLOSURE_READINESS": readiness,
            "CLOSURE_RANK": rank,
            "LAST_SOURCE": str(source_series.loc[latest_idx] or ""),
            "LAST_CATEGORY": str(category_series.loc[latest_idx] or ""),
            "OWNER": str(owner_series.loc[latest_idx] or latest.get("OWNER", "")),
            "LAST_STATUS": str(latest.get("STATUS") or ""),
            "LAST_SEVERITY": str(latest.get("SEVERITY") or ""),
            "LAST_ACTIVITY_TS": latest.get("_LAST_ACTIVITY_TS"),
            **totals,
        }
        row["NEXT_CONTROL_ACTION"] = _command_closure_next_action(row)
        rows.append(row)

    if not rows:
        return _empty_df()
    return pd.DataFrame(rows).sort_values(
        ["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "CLOSURE_BLOCKER_ROWS", "OPEN_ACTIONS"],
        ascending=[True, False, False, False, False],
    )


def _command_execution_metadata(row: pd.Series) -> dict:
    """Classify whether a queue row is safe to execute from the Control Room."""
    category = str(row.get("CATEGORY") or "").upper()
    severity = str(row.get("SEVERITY") or "").upper()
    due_state = str(row.get("DUE_STATE") or "")
    approval_status = str(row.get("OWNER_APPROVAL_STATUS") or "").strip().upper()
    requires_approval = _command_requires_approval(row)
    route_ready = _command_value_present(row, "OWNER_EMAIL") and (
        _command_value_present(row, "ONCALL_PRIMARY") or _command_value_present(row, "APPROVAL_GROUP")
    )

    gaps: list[str] = []
    if not _command_named_owner(row):
        gaps.append("Named owner")
    if not route_ready:
        gaps.append("Owner/on-call route")
    if not _command_value_present(row, "TICKET_ID"):
        gaps.append("Ticket/change ID")
    if not _command_value_present(row, "APPROVER"):
        gaps.append("Approver")
    if not _command_value_present(row, "VERIFICATION_QUERY", "PROOF_QUERY"):
        gaps.append("Verification query")
    if ("COST" in category or "CHARGEBACK" in category or "TASK" in category or "PROCEDURE" in category) and (
        not _command_value_present(row, "BASELINE_VALUE")
        or not _command_value_present(row, "CURRENT_VALUE")
    ):
        gaps.append("Baseline/current values")

    approval_blocked = requires_approval and approval_status in {"", "PENDING", "REQUESTED", "REQUIRED"}
    if approval_blocked:
        gaps.append("Owner approval")

    metadata_missing = any(item != "Owner approval" for item in gaps)
    if due_state == "Overdue":
        gate = "Escalate - Overdue"
    elif metadata_missing:
        gate = "Blocked - Metadata"
    elif approval_blocked:
        gate = "Blocked - Owner Approval"
    elif severity in {"CRITICAL", "HIGH"}:
        gate = "Ready - High Risk"
    else:
        gate = "Ready - Standard"

    audit_ready = gate.startswith("Ready")
    return {
        "COMMAND_OWNER_READINESS": "Named Owner" if _command_named_owner(row) else "Owner Needed",
        "COMMAND_ROUTE_READINESS": "Route Ready" if route_ready else "Route Needed",
        "COMMAND_AUDIT_READINESS": "Audit Ready" if audit_ready else "Audit Gaps",
        "COMMAND_EXECUTION_GATE": gate,
        "COMMAND_EVIDENCE_REQUIRED": "; ".join(dict.fromkeys(gaps)) if gaps else "Ready for controlled execution",
    }


def _build_command_queue(queue: pd.DataFrame, today: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Return open action-queue rows as a DBA command queue with control gaps."""
    if queue is None or queue.empty:
        return _empty_df()

    view = enrich_action_queue_view(queue, today=today).copy()
    status = view.get("STATUS", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    view = view[~status.isin(["FIXED", "IGNORED"])].copy()
    if view.empty:
        return _empty_df()

    severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    due_rank = {"Overdue": 0, "Due today": 1, "Due soon": 2, "Unscheduled": 3, "Scheduled": 4}
    evidence = view.get("EVIDENCE_GAP", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)
    severity = view.get("SEVERITY", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str).str.upper()
    due_state = view.get("DUE_STATE", pd.Series([""] * len(view), index=view.index)).fillna("").astype(str)

    view["ROUTE"] = view.get("CATEGORY", pd.Series([""] * len(view), index=view.index)).apply(_command_queue_route)
    view = _enrich_command_owner_context(view)
    view["CONTROL_GAP"] = evidence.where(evidence.ne("Ready to work"), "")
    command_metadata = view.apply(_command_execution_metadata, axis=1, result_type="expand")
    for column in command_metadata.columns:
        view[column] = command_metadata[column]
    view["PROOF_READY"] = view["COMMAND_EXECUTION_GATE"].astype(str).str.startswith("Ready").map({True: "Yes", False: "No"})
    view["COMMAND_STATE"] = "Work Ready"
    view.loc[evidence.ne("Ready to work"), "COMMAND_STATE"] = "Complete Control Metadata"
    view.loc[due_state.eq("Overdue"), "COMMAND_STATE"] = "Escalate Overdue"
    view.loc[severity.isin(["CRITICAL", "HIGH"]) & evidence.eq("Ready to work"), "COMMAND_STATE"] = "Work Now"
    view["_COMMAND_SORT"] = (
        due_state.map(due_rank).fillna(5).astype(float) * 10
        + severity.map(severity_rank).fillna(4).astype(float)
        + evidence.ne("Ready to work").astype(int)
    )
    return view.sort_values(["_COMMAND_SORT", "QUEUE_PRIORITY"], ascending=[True, True]).drop(
        columns=["_COMMAND_SORT"],
        errors="ignore",
    )


def _command_queue_summary(queue: pd.DataFrame) -> dict:
    """Summarize command-queue readiness without changing stored queue data."""
    if queue is None or queue.empty:
        return {
            "open": 0,
            "overdue": 0,
            "ready": 0,
            "control_gaps": 0,
            "owner_gaps": 0,
            "approval_gaps": 0,
            "ticket_gaps": 0,
            "high_risk": 0,
            "execution_ready": 0,
            "audit_ready": 0,
            "route_ready": 0,
            "metadata_blocks": 0,
            "approval_blocks": 0,
            "control_ready_pct": 0.0,
        }
    evidence = queue.get("EVIDENCE_GAP", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
    command_evidence = queue.get(
        "COMMAND_EVIDENCE_REQUIRED",
        pd.Series([""] * len(queue), index=queue.index),
    ).fillna("").astype(str)
    evidence_rollup = evidence + " " + command_evidence
    severity = queue.get("SEVERITY", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str).str.upper()
    due_state = queue.get("DUE_STATE", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
    gate = queue.get("COMMAND_EXECUTION_GATE", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
    audit = queue.get("COMMAND_AUDIT_READINESS", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
    route = queue.get("COMMAND_ROUTE_READINESS", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
    ready = int(gate.str.startswith("Ready").sum())
    summary = {
        "open": int(len(queue)),
        "overdue": int(due_state.eq("Overdue").sum()),
        "ready": ready if "COMMAND_EXECUTION_GATE" in queue.columns else int(evidence.eq("Ready to work").sum()),
        "control_gaps": int(evidence.ne("Ready to work").sum()),
        "owner_gaps": int(evidence_rollup.str.contains("named owner", case=False, na=False).sum()),
        "approval_gaps": int(evidence_rollup.str.contains("approver|owner approval", case=False, na=False).sum()),
        "ticket_gaps": int(evidence_rollup.str.contains("ticket|change ID", case=False, na=False).sum()),
        "high_risk": int(severity.isin(["CRITICAL", "HIGH"]).sum()),
        "execution_ready": ready,
        "audit_ready": int(audit.eq("Audit Ready").sum()),
        "route_ready": int(route.eq("Route Ready").sum()),
        "metadata_blocks": int(gate.eq("Blocked - Metadata").sum()),
        "approval_blocks": int(gate.eq("Blocked - Owner Approval").sum()),
    }
    summary["control_ready_pct"] = round((summary["execution_ready"] / summary["open"]) * 100, 1) if summary["open"] else 0.0
    return summary


def _command_queue_route_readiness(queue: pd.DataFrame) -> pd.DataFrame:
    """Summarize command readiness by routed DBA section."""
    if queue is None or queue.empty:
        return _empty_df()
    rows: list[dict] = []
    for route, group in queue.groupby(queue.get("ROUTE", pd.Series(["Unrouted"] * len(queue), index=queue.index)).fillna("Unrouted")):
        summary = _command_queue_summary(group)
        if summary["overdue"]:
            next_action = "Escalate overdue items and attach owner/ticket evidence."
        elif summary["metadata_blocks"]:
            next_action = "Complete owner, ticket, approver, and verification metadata."
        elif summary["approval_blocks"]:
            next_action = "Collect owner approval before DBA execution."
        elif summary["execution_ready"]:
            next_action = "Work ready items, then attach verification proof before closure."
        else:
            next_action = "Triage route and assign accountable DBA owner."
        rows.append({
            "ROUTE": route,
            "OPEN_ACTIONS": summary["open"],
            "OVERDUE": summary["overdue"],
            "EXECUTION_READY": summary["execution_ready"],
            "AUDIT_READY": summary["audit_ready"],
            "ROUTE_READY": summary["route_ready"],
            "OWNER_GAPS": summary["owner_gaps"],
            "APPROVAL_BLOCKS": summary["approval_blocks"],
            "METADATA_BLOCKS": summary["metadata_blocks"],
            "CONTROL_READY_PCT": summary["control_ready_pct"],
            "NEXT_CONTROL_ACTION": next_action,
        })
    return pd.DataFrame(rows).sort_values(
        ["OVERDUE", "METADATA_BLOCKS", "APPROVAL_BLOCKS", "OPEN_ACTIONS"],
        ascending=[False, False, False, False],
    )


def _dba_section_proof_required(section: object, lowest_component: object = "") -> str:
    """Return the minimum proof contract for a section to remain credibly 95+."""
    name = str(section or "").upper()
    component = str(lowest_component or "").lower()
    if "WAREHOUSE" in name:
        return "capacity evidence, setting review snapshot, owner approval, rollback SQL, post-change verification"
    if "CHANGE" in name or "DRIFT" in name:
        return "change ticket, query_id, source-control/IaC proof, blast-radius review, closure verification"
    if "COST" in name:
        return "allocated cost basis, owner chargeback, savings verification, finance-ready closure evidence"
    if "SECURITY" in name:
        return "role/grant owner, approver, ticket, least-privilege verification, access closure proof"
    if "ACCOUNT" in name:
        return "checklist owner, hygiene evidence, approved remediation, verified closure notes"
    if "ALERT" in name:
        return "alert source health, routed owner, email evidence, suppression/acknowledgement history"
    if "WORKLOAD" in name:
        return "task/procedure failure proof, owner, runbook, recovery SLA, successful retry evidence"
    if "DBA CONTROL" in name or "operability" in component:
        return "current source health, command queue route, owner/ticket metadata, closure proof"
    return "owner, ticket, approver, verification query, closure evidence"


def _dba_incident_type(route: object, signal: object) -> str:
    route_text = str(route or "").upper()
    signal_text = str(signal or "").upper()
    text = f"{route_text} {signal_text}"
    if any(token in text for token in ("CREDIT", "COST", "CORTEX", "AI")):
        return "Cost Runaway"
    if any(token in text for token in ("WAREHOUSE", "QUEUE", "SPILL", "CAPACITY", "LATENCY")):
        return "Warehouse Capacity"
    if any(token in text for token in ("TASK", "PROCEDURE", "PIPELINE", "SLA", "REGRESSION")):
        return "Workload Reliability"
    if any(token in text for token in ("QUERY FAIL", "FAILED QUERY", "P95", "DURATION")):
        return "Query Reliability"
    if any(token in text for token in ("SECURITY", "LOGIN", "ACCESS", "GRANT", "ROLE")):
        return "Security / Access"
    if any(token in text for token in ("CHANGE", "DRIFT", "DDL", "OBJECT")):
        return "Change Control"
    if any(token in text for token in ("CLOSURE", "EVIDENCE", "PROOF")):
        return "Control Closure"
    if any(token in text for token in ("SOURCE", "STALE", "UNAVAILABLE", "MART")):
        return "Evidence Quality"
    return "DBA Operations"


def _dba_incident_rank(severity: object) -> int:
    return {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
        "INFO": 4,
    }.get(str(severity or "").upper(), 3)


def _dba_incident_sla_target(incident_type: object, severity: object) -> str:
    incident = str(incident_type or "").upper()
    rank = _dba_incident_rank(severity)
    if rank <= 0:
        return "Contain within 15 minutes; executive DBA update within 30 minutes."
    if rank == 1 and any(token in incident for token in ("SECURITY", "RELIABILITY", "CAPACITY")):
        return "Contain within 30 minutes; recovery or owner-approved mitigation within 4 hours."
    if rank == 1:
        return "Contain same shift; owner-approved mitigation plan before handoff."
    if rank == 2:
        return "Triage same business day; queue action with owner, due date, and proof."
    return "Monitor during next DBA review cycle."


def _dba_incident_containment_action(incident_type: object) -> str:
    incident = str(incident_type or "").upper()
    if "COST" in incident:
        return "Freeze broad scaling changes, identify top cost driver, and require owner approval before mitigation."
    if "WAREHOUSE" in incident:
        return "Stabilize queue/spill pressure first; route setting changes through Warehouse Settings Manager."
    if "WORKLOAD" in incident or "QUERY" in incident:
        return "Separate failing workload from platform issue, capture query/task evidence, and protect downstream SLAs."
    if "SECURITY" in incident:
        return "Preserve evidence, validate requester/approver, and avoid grant changes until owner route is clear."
    if "CHANGE" in incident:
        return "Hold closure until ticket, query_id, source-control, and blast-radius proof are attached."
    if "CLOSURE" in incident:
        return "Reopen or block closure until verification, recovery, and approval evidence are present."
    if "EVIDENCE" in incident:
        return "Refresh mart/source evidence before taking irreversible DBA action."
    return "Assign DBA owner, capture evidence, and route to the specialist workflow."


def _dba_incident_investigation_path(route: object, workflow: object = "") -> str:
    route_text = str(route or "DBA Control Room")
    workflow_text = str(workflow or "").strip()
    if workflow_text:
        return f"{route_text} -> {workflow_text}"
    return route_text


def _dba_incident_board(
    exceptions: pd.DataFrame | None,
    command_queue: pd.DataFrame | None,
    closure_rollup: pd.DataFrame | None,
    source_health: pd.DataFrame | None,
    *,
    max_rows: int = 10,
) -> pd.DataFrame:
    """Group loaded Control Room signals into incident-style operating lanes."""
    events: list[dict] = []

    source_exceptions = exceptions if exceptions is not None else _empty_df()
    if not source_exceptions.empty:
        for _, item in _priority_exceptions(source_exceptions).head(12).iterrows():
            route = str(item.get("Route") or item.get("ROUTE") or item.get("Domain") or "DBA Control Room")
            signal = str(item.get("Signal") or item.get("SIGNAL") or "Control-room signal")
            severity = str(item.get("Severity") or item.get("SEVERITY") or "Medium")
            incident_type = _dba_incident_type(route, signal)
            events.append({
                "INCIDENT_TYPE": incident_type,
                "ROUTE": route,
                "SEVERITY": severity,
                "SIGNAL": signal,
                "EVIDENCE": str(item.get("Evidence") or item.get("DETAIL") or signal),
                "WORKFLOW": str(item.get("Workflow") or ""),
                "OPEN_ACTIONS": 0,
                "OVERDUE": 0,
                "PROOF_BLOCKS": 0,
                "SOURCE_ISSUES": 0,
            })

    queue = command_queue if command_queue is not None else _empty_df()
    if not queue.empty:
        route_readiness = _command_queue_route_readiness(queue)
        for _, item in route_readiness.iterrows():
            route = str(item.get("ROUTE") or "DBA Control Room")
            open_actions = safe_int(item.get("OPEN_ACTIONS"))
            overdue = safe_int(item.get("OVERDUE"))
            proof_blocks = (
                safe_int(item.get("OWNER_GAPS"))
                + safe_int(item.get("APPROVAL_BLOCKS"))
                + safe_int(item.get("METADATA_BLOCKS"))
            )
            if not open_actions and not proof_blocks:
                continue
            severity = "High" if overdue or proof_blocks else "Medium"
            signal = "Action queue blockers" if proof_blocks else "Open action queue"
            events.append({
                "INCIDENT_TYPE": _dba_incident_type(route, signal),
                "ROUTE": route,
                "SEVERITY": severity,
                "SIGNAL": signal,
                "EVIDENCE": (
                    f"{open_actions:,} open; {overdue:,} overdue; "
                    f"{safe_int(item.get('EXECUTION_READY')):,} execution-ready; "
                    f"{proof_blocks:,} owner/approval/metadata blocks"
                ),
                "WORKFLOW": "",
                "OPEN_ACTIONS": open_actions,
                "OVERDUE": overdue,
                "PROOF_BLOCKS": proof_blocks,
                "SOURCE_ISSUES": 0,
            })

    closure = closure_rollup if closure_rollup is not None else _empty_df()
    if not closure.empty:
        closure_view = closure.copy()
        closure_view.columns = [str(col).upper() for col in closure_view.columns]
        blocked = closure_view[
            (pd.to_numeric(closure_view.get("CLOSURE_RANK", pd.Series([9] * len(closure_view))), errors="coerce").fillna(9) <= 3)
            | (pd.to_numeric(closure_view.get("CLOSURE_BLOCKER_ROWS", pd.Series([0] * len(closure_view))), errors="coerce").fillna(0) > 0)
        ]
        for _, item in blocked.iterrows():
            route = str(item.get("ROUTE") or "DBA Control Room")
            signal = str(item.get("CLOSURE_READINESS") or "Closure evidence blockers")
            overdue = safe_int(item.get("OVERDUE_OPEN"))
            proof_blocks = safe_int(item.get("CLOSURE_BLOCKER_ROWS"))
            events.append({
                "INCIDENT_TYPE": _dba_incident_type(route, signal),
                "ROUTE": route,
                "SEVERITY": "High" if overdue or safe_int(item.get("FIXED_WITHOUT_VERIFICATION")) else "Medium",
                "SIGNAL": signal,
                "EVIDENCE": (
                    f"{safe_int(item.get('OPEN_ACTIONS')):,} open; {overdue:,} overdue; "
                    f"{safe_int(item.get('FIXED_WITHOUT_VERIFICATION')):,} fixed without verification; "
                    f"{safe_int(item.get('RECOVERY_RISK_ROWS')):,} recovery-risk"
                ),
                "WORKFLOW": "Action Queue",
                "OPEN_ACTIONS": safe_int(item.get("OPEN_ACTIONS")),
                "OVERDUE": overdue,
                "PROOF_BLOCKS": proof_blocks,
                "SOURCE_ISSUES": 0,
            })

    sources = source_health if source_health is not None else _empty_df()
    if not sources.empty:
        source_view = sources.copy()
        source_view.columns = [str(col).upper() for col in source_view.columns]
        source_blocks = source_view[
            source_view.get("STATE", pd.Series([""] * len(source_view), index=source_view.index)).fillna("").astype(str).isin(["Unavailable", "Stale"])
        ]
        for _, item in source_blocks.iterrows():
            surface = str(item.get("SURFACE") or "Evidence surface")
            state = str(item.get("STATE") or "Source issue")
            events.append({
                "INCIDENT_TYPE": "Evidence Quality",
                "ROUTE": "Source Health",
                "SEVERITY": "High" if state == "Unavailable" else "Medium",
                "SIGNAL": f"{surface} {state}",
                "EVIDENCE": f"{surface}; {state}; rows={safe_int(item.get('ROWS')):,}; scope={item.get('SCOPE', '')}",
                "WORKFLOW": "Source Health",
                "OPEN_ACTIONS": 0,
                "OVERDUE": 0,
                "PROOF_BLOCKS": 0,
                "SOURCE_ISSUES": 1,
            })

    if not events:
        return pd.DataFrame([{
            "INCIDENT_ID": "DBA-01",
            "INCIDENT_TYPE": "Routine Watch",
            "SEVERITY": "Low",
            "STATUS": "Monitor",
            "AFFECTED_ROUTES": "DBA Control Room",
            "SIGNALS": "No active incident signals",
            "EVIDENCE": "Loaded evidence produced no exception, queue blocker, closure blocker, or stale source surface.",
            "OPEN_ACTIONS": 0,
            "OVERDUE": 0,
            "PROOF_BLOCKS": 0,
            "SOURCE_ISSUES": 0,
            "CONTAINMENT_ACTION": "Keep fast snapshot current and monitor Alert Center.",
            "INVESTIGATION_PATH": "DBA Control Room",
            "SLA_TARGET": "Monitor during next DBA review cycle.",
            "PROOF_REQUIRED": "fresh Control Room load and Alert Center review",
        }])

    event_frame = pd.DataFrame(events)
    rows: list[dict] = []
    for (incident_type, route), group in event_frame.groupby(["INCIDENT_TYPE", "ROUTE"], dropna=False):
        severity_ranks = group["SEVERITY"].apply(_dba_incident_rank)
        worst_idx = severity_ranks.idxmin()
        severity = str(group.loc[worst_idx, "SEVERITY"])
        signals = "; ".join(dict.fromkeys(group["SIGNAL"].fillna("").astype(str).head(5)))
        evidence = " | ".join(dict.fromkeys(group["EVIDENCE"].fillna("").astype(str).head(4)))
        open_actions = int(pd.to_numeric(group["OPEN_ACTIONS"], errors="coerce").fillna(0).sum())
        overdue = int(pd.to_numeric(group["OVERDUE"], errors="coerce").fillna(0).sum())
        proof_blocks = int(pd.to_numeric(group["PROOF_BLOCKS"], errors="coerce").fillna(0).sum())
        source_issues = int(pd.to_numeric(group["SOURCE_ISSUES"], errors="coerce").fillna(0).sum())
        if overdue or proof_blocks:
            status = "Containment Required"
            rank = 0
        elif source_issues:
            status = "Evidence Refresh Required"
            rank = 1
        elif _dba_incident_rank(severity) <= 1:
            status = "Investigate Now"
            rank = 2
        else:
            status = "Triage"
            rank = 4
        rows.append({
            "INCIDENT_TYPE": incident_type,
            "SEVERITY": severity,
            "STATUS": status,
            "STATUS_RANK": rank,
            "SEVERITY_RANK": _dba_incident_rank(severity),
            "AFFECTED_ROUTES": route,
            "SIGNALS": signals,
            "EVIDENCE": evidence,
            "OPEN_ACTIONS": open_actions,
            "OVERDUE": overdue,
            "PROOF_BLOCKS": proof_blocks,
            "SOURCE_ISSUES": source_issues,
            "CONTAINMENT_ACTION": _dba_incident_containment_action(incident_type),
            "INVESTIGATION_PATH": _dba_incident_investigation_path(route, group["WORKFLOW"].iloc[0]),
            "SLA_TARGET": _dba_incident_sla_target(incident_type, severity),
            "PROOF_REQUIRED": _dba_section_proof_required(route),
        })

    result = pd.DataFrame(rows).sort_values(
        ["STATUS_RANK", "SEVERITY_RANK", "OVERDUE", "PROOF_BLOCKS", "OPEN_ACTIONS", "INCIDENT_TYPE"],
        ascending=[True, True, False, False, False, True],
    ).head(max_rows).reset_index(drop=True)
    result.insert(0, "INCIDENT_ID", [f"DBA-{idx + 1:02d}" for idx in range(len(result))])
    return result.drop(columns=["STATUS_RANK", "SEVERITY_RANK"], errors="ignore")


def _dba_source_health_deployment_gate(source_health: pd.DataFrame | None) -> dict:
    """Return a global source-health gate for effective readiness."""
    if source_health is None or source_health.empty or "STATE" not in source_health.columns:
        return {
            "score": 100,
            "label": "Source Health",
            "reason": "",
        }
    states = source_health["STATE"].fillna("").astype(str)
    unavailable = int(states.isin(["Unavailable"]).sum())
    stale = int(states.isin(["Stale"]).sum())
    not_loaded = int(states.isin(["Not Loaded"]).sum())
    if unavailable:
        return {
            "score": 86,
            "label": "Source Health",
            "reason": f"{unavailable:,} required source surface(s) unavailable.",
        }
    if stale:
        return {
            "score": 90,
            "label": "Source Health",
            "reason": f"{stale:,} source surface(s) stale for the active scope.",
        }
    if not_loaded:
        return {
            "score": 94,
            "label": "Source Health",
            "reason": f"{not_loaded:,} source surface(s) not loaded in this session.",
        }
    return {
        "score": 100,
        "label": "Source Health",
        "reason": "",
    }


def _dba_section_operability_board(
    section_rows: pd.DataFrame | None = None,
    command_queue: pd.DataFrame | None = None,
    closure_rollup: pd.DataFrame | None = None,
    source_health: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join static 95-readiness with live command/closure blockers by DBA route."""
    sections = section_rows.copy() if section_rows is not None and not section_rows.empty else pd.DataFrame(dba_control_plane_section_scorecards())
    if sections.empty:
        return _empty_df()

    route_readiness = _command_queue_route_readiness(command_queue) if command_queue is not None and not command_queue.empty else _empty_df()
    closure = closure_rollup.copy() if closure_rollup is not None and not closure_rollup.empty else _empty_df()
    route_by_name = {
        str(row.get("ROUTE") or ""): row
        for _, row in route_readiness.iterrows()
    } if not route_readiness.empty else {}
    closure_by_name = {
        str(row.get("ROUTE") or ""): row
        for _, row in closure.iterrows()
    } if not closure.empty else {}
    source_gate = _dba_source_health_deployment_gate(source_health)

    rows: list[dict] = []
    for _, section in sections.iterrows():
        name = str(section.get("SECTION") or "")
        route = route_by_name.get(name, {})
        close = closure_by_name.get(name, {})
        score = safe_float(section.get("SCORE", 0))
        open_actions = safe_int(route.get("OPEN_ACTIONS", 0))
        overdue = max(safe_int(route.get("OVERDUE", 0)), safe_int(close.get("OVERDUE_OPEN", 0)))
        metadata_blocks = safe_int(route.get("METADATA_BLOCKS", 0))
        approval_blocks = safe_int(route.get("APPROVAL_BLOCKS", 0))
        execution_ready = safe_int(route.get("EXECUTION_READY", 0))
        closure_rank = safe_int(close.get("CLOSURE_RANK", 9))
        closure_blockers = safe_int(close.get("CLOSURE_BLOCKER_ROWS", 0))
        fixed_without_verification = safe_int(close.get("FIXED_WITHOUT_VERIFICATION", 0))
        recovery_risk = safe_int(close.get("RECOVERY_RISK_ROWS", 0))
        verified_closures = safe_int(close.get("VERIFIED_CLOSURES", 0))

        if overdue:
            state, rank = "Escalate Now", 0
            next_action = "Escalate overdue route work and attach owner, ticket, and verification evidence."
            closure_gate_score = 72
        elif fixed_without_verification or recovery_risk or closure_rank in {1, 2}:
            state, rank = "Closure Evidence Blocked", 1
            next_action = "Attach verification or recovery evidence before accepting the section as controlled."
            closure_gate_score = 82
        elif metadata_blocks:
            state, rank = "Route Metadata Blocked", 2
            next_action = "Complete owner, ticket, approver, and verification metadata for open work."
            closure_gate_score = 88
        elif approval_blocks:
            state, rank = "Approval Blocked", 3
            next_action = "Collect owner approval before DBA execution."
            closure_gate_score = 90
        elif open_actions:
            state, rank = "Work Open Actions", 4
            next_action = "Work ready actions, then retain proof for closure."
            closure_gate_score = 94
        elif score < 95:
            state, rank = "Build Toward 95", 6
            next_action = str(section.get("NEXT_95_MOVE") or "Raise weak control-plane components.")
            closure_gate_score = 100
        else:
            state, rank = "95 Target", 8
            next_action = "Maintain verified closure evidence and owner routing."
            closure_gate_score = 100

        gates = {
            "source_health": source_gate,
            "route_control": {
                "score": closure_gate_score,
                "label": "Route Control",
                "reason": next_action if closure_gate_score < 100 else "",
            },
        }
        effective = dba_effective_readiness_score(score, gates)
        effective_score = safe_float(effective.get("score", score))
        gate_drivers = ", ".join(
            str(gate.get("GATE") or gate.get("KEY") or "").strip()
            for gate in effective.get("gate_drivers", [])
            if str(gate.get("GATE") or gate.get("KEY") or "").strip()
        ) or "none"
        if effective_score < score and rank >= 6:
            state, rank = "Deployment Gate", 5
            gate_reason = str(source_gate.get("reason") or "").strip()
            next_action = gate_reason or "Resolve active deployment gate driver(s) before treating this section as ready."

        rows.append({
            "SECTION": name,
            "SCORE": score,
            "EFFECTIVE_SCORE": effective_score,
            "LABEL": section.get("LABEL", ""),
            "DEPLOYMENT_LABEL": effective.get("label", ""),
            "GATE_DRIVERS": gate_drivers,
            "OPERABILITY_STATE": state,
            "OPERABILITY_RANK": rank,
            "OPEN_ACTIONS": open_actions,
            "OVERDUE": overdue,
            "EXECUTION_READY": execution_ready,
            "METADATA_BLOCKS": metadata_blocks,
            "APPROVAL_BLOCKS": approval_blocks,
            "CLOSURE_READINESS": close.get("CLOSURE_READINESS", "No recent action"),
            "CLOSURE_BLOCKERS": closure_blockers,
            "FIXED_WITHOUT_VERIFICATION": fixed_without_verification,
            "RECOVERY_RISK_ROWS": recovery_risk,
            "VERIFIED_CLOSURES": verified_closures,
            "LOWEST_COMPONENT": section.get("LOWEST_COMPONENT", ""),
            "LOWEST_SCORE": safe_float(section.get("LOWEST_SCORE", 0)),
            "CAP_DRIVERS": section.get("CAP_DRIVERS", ""),
            "PROOF_REQUIRED": _dba_section_proof_required(name, section.get("LOWEST_COMPONENT", "")),
            "NEXT_CONTROL_ACTION": next_action,
            "NEXT_95_MOVE": section.get("NEXT_95_MOVE", ""),
        })

    if not rows:
        return _empty_df()
    return pd.DataFrame(rows).sort_values(
        [
            "OPERABILITY_RANK",
            "OVERDUE",
            "CLOSURE_BLOCKERS",
            "METADATA_BLOCKS",
            "APPROVAL_BLOCKS",
            "SCORE",
        ],
        ascending=[True, False, False, False, False, True],
    ).reset_index(drop=True)


def _dba_control_tower_state(row: pd.Series | dict) -> tuple[str, str]:
    """Return a concise operating state and first move for a section priority row."""
    overdue = safe_int(row.get("OVERDUE", 0))
    proof_blocks = safe_int(row.get("PROOF_BLOCKS", 0))
    metadata_blocks = safe_int(row.get("METADATA_BLOCKS", 0))
    approval_blocks = safe_int(row.get("APPROVAL_BLOCKS", 0))
    source_issues = safe_int(row.get("SOURCE_ISSUES", 0))
    execution_ready = safe_int(row.get("EXECUTION_READY", 0))
    section_score = safe_float(row.get("SCORE", 0))
    effective_score = safe_float(row.get("EFFECTIVE_SCORE", section_score))
    gate_drivers = str(row.get("GATE_DRIVERS") or "").strip()
    incident_status = str(row.get("WORST_INCIDENT_STATUS") or "")
    incident_action = str(row.get("INCIDENT_CONTAINMENT") or "").strip()
    section_action = str(row.get("SECTION_NEXT_ACTION") or "").strip()
    next_99 = str(row.get("NEXT_99_MOVE") or "").strip()
    if overdue or "Containment" in incident_status:
        return "Contain Now", incident_action or "Escalate overdue work and capture owner, ticket, approval, and verification evidence."
    if proof_blocks or source_issues:
        return "Restore Control Evidence", incident_action or "Refresh blocked evidence and attach proof before DBA execution."
    if metadata_blocks:
        return "Unblock Route Metadata", "Complete owner, ticket, approver, route, and verification metadata."
    if approval_blocks:
        return "Approval Required", "Collect owner approval before executing DBA-controlled action."
    if execution_ready:
        return "Execute Ready Work", "Work execution-ready items, then attach before/after verification proof."
    if effective_score < section_score:
        detail = f"Resolve gate driver(s): {gate_drivers}." if gate_drivers and gate_drivers != "none" else "Resolve active deployment gate driver(s)."
        return "Deployment Gate", detail
    if effective_score < 99:
        return "Raise Toward 99", next_99 or section_action or "Harden the lowest control component and preserve closure evidence."
    return "Monitor", "Maintain source health, owner route, and verified closure evidence."


def _dba_control_tower_priority_index(
    section_board: pd.DataFrame | None,
    incident_board: pd.DataFrame | None,
    command_queue: pd.DataFrame | None,
    source_health: pd.DataFrame | None,
    *,
    max_rows: int = 9,
) -> pd.DataFrame:
    """Rank DBA sections by live risk, command blockers, evidence gaps, and 99-target drift."""
    board = section_board.copy() if section_board is not None and not section_board.empty else _dba_section_operability_board(
        command_queue=command_queue,
        closure_rollup=_command_queue_closure_readiness(command_queue),
        source_health=source_health,
    )
    if board is None or board.empty:
        return _empty_df()
    board.columns = [str(col).upper() for col in board.columns]

    incident = incident_board.copy() if incident_board is not None and not incident_board.empty else _empty_df()
    if not incident.empty:
        incident.columns = [str(col).upper() for col in incident.columns]
    source = source_health.copy() if source_health is not None and not source_health.empty else _empty_df()
    if not source.empty:
        source.columns = [str(col).upper() for col in source.columns]

    rows: list[dict] = []
    severity_points = {"CRITICAL": 35, "HIGH": 24, "MEDIUM": 12, "LOW": 4}
    status_points = {
        "CONTAINMENT REQUIRED": 18,
        "EVIDENCE REFRESH REQUIRED": 12,
        "INVESTIGATE NOW": 10,
        "TRIAGE": 5,
        "MONITOR": 0,
    }
    for _, item in board.iterrows():
        section = str(item.get("SECTION") or "DBA Control Room")
        score = safe_float(item.get("SCORE", 0))
        effective_score = safe_float(item.get("EFFECTIVE_SCORE", score))
        matched_incidents = _empty_df()
        if not incident.empty and "AFFECTED_ROUTES" in incident.columns:
            route_text = incident["AFFECTED_ROUTES"].fillna("").astype(str)
            matched_incidents = incident[route_text.eq(section) | route_text.str.contains(section, case=False, regex=False)].copy()
        source_issue_count = 0
        if section == "DBA Control Room" and not source.empty and "STATE" in source.columns:
            source_issue_count = int(source["STATE"].fillna("").astype(str).isin(["Unavailable", "Stale"]).sum())
        if not matched_incidents.empty:
            incident_points = int(
                matched_incidents.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
                .map(severity_points).fillna(0).sum()
            )
            incident_points += int(
                matched_incidents.get("STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
                .map(status_points).fillna(0).sum()
            )
            worst = matched_incidents.sort_values(
                by=["SEVERITY"],
                key=lambda series: series.fillna("").astype(str).str.upper().map(
                    {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
                ).fillna(4),
            ).iloc[0]
            worst_signal = str(worst.get("SIGNALS") or worst.get("SIGNAL") or "")
            worst_status = str(worst.get("STATUS") or "")
            incident_containment = str(worst.get("CONTAINMENT_ACTION") or "")
        else:
            incident_points = 0
            worst_signal = ""
            worst_status = ""
            incident_containment = ""

        overdue = safe_int(item.get("OVERDUE"))
        closure_blockers = safe_int(item.get("CLOSURE_BLOCKERS"))
        metadata_blocks = safe_int(item.get("METADATA_BLOCKS"))
        approval_blocks = safe_int(item.get("APPROVAL_BLOCKS"))
        execution_ready = safe_int(item.get("EXECUTION_READY"))
        recovery_risk = safe_int(item.get("RECOVERY_RISK_ROWS"))
        fixed_without_verification = safe_int(item.get("FIXED_WITHOUT_VERIFICATION"))
        proof_blocks = closure_blockers + recovery_risk + fixed_without_verification
        target_gap = max(0.0, 99.0 - effective_score)
        deployment_gap = max(0.0, score - effective_score)
        priority_score = min(100, round(
            (target_gap * 1.7)
            + (deployment_gap * 1.4)
            + incident_points
            + overdue * 18
            + proof_blocks * 10
            + metadata_blocks * 7
            + approval_blocks * 8
            + source_issue_count * 8
            + execution_ready * 2,
            1,
        ))
        reason_bits = []
        if worst_signal:
            reason_bits.append(worst_signal)
        if overdue:
            reason_bits.append(f"{overdue:,} overdue")
        if proof_blocks:
            reason_bits.append(f"{proof_blocks:,} proof/recovery blocker(s)")
        if metadata_blocks:
            reason_bits.append(f"{metadata_blocks:,} metadata blocker(s)")
        if approval_blocks:
            reason_bits.append(f"{approval_blocks:,} approval blocker(s)")
        if source_issue_count:
            reason_bits.append(f"{source_issue_count:,} stale/unavailable source(s)")
        if deployment_gap:
            reason_bits.append(f"{deployment_gap:.1f} effective-readiness gate")
        if not reason_bits and target_gap:
            reason_bits.append(f"{target_gap:.1f} points from 99 target")
        row = {
            "SECTION": section,
            "PRIORITY_SCORE": priority_score,
            "SCORE": score,
            "EFFECTIVE_SCORE": effective_score,
            "DEPLOYMENT_LABEL": str(item.get("DEPLOYMENT_LABEL") or ""),
            "GATE_DRIVERS": str(item.get("GATE_DRIVERS") or "none"),
            "TARGET_GAP_TO_99": round(target_gap, 1),
            "WORST_INCIDENT_STATUS": worst_status,
            "WORST_SIGNAL": worst_signal or str(item.get("OPERABILITY_STATE") or "No live incident"),
            "OVERDUE": overdue,
            "EXECUTION_READY": execution_ready,
            "METADATA_BLOCKS": metadata_blocks,
            "APPROVAL_BLOCKS": approval_blocks,
            "PROOF_BLOCKS": proof_blocks,
            "SOURCE_ISSUES": source_issue_count,
            "WHY_NOW": "; ".join(reason_bits) or "No active blocker; keep monitoring.",
            "INCIDENT_CONTAINMENT": incident_containment,
            "SECTION_NEXT_ACTION": str(item.get("NEXT_CONTROL_ACTION") or ""),
            "NEXT_99_MOVE": str(item.get("NEXT_95_MOVE") or item.get("NEXT_CONTROL_ACTION") or ""),
            "PROOF_REQUIRED": str(item.get("PROOF_REQUIRED") or _dba_section_proof_required(section)),
        }
        state, first_move = _dba_control_tower_state(row)
        row["CONTROL_TOWER_STATE"] = state
        row["FIRST_MOVE"] = first_move
        rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        ["PRIORITY_SCORE", "OVERDUE", "PROOF_BLOCKS", "METADATA_BLOCKS", "APPROVAL_BLOCKS", "TARGET_GAP_TO_99"],
        ascending=[False, False, False, False, False, False],
    ).head(max_rows).reset_index(drop=True)


def _render_control_tower_priority_index(tower: pd.DataFrame) -> None:
    if tower is None or tower.empty:
        return
    hot = tower.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Control Tower", str(hot.get("CONTROL_TOWER_STATE") or "Monitor"))
    c2.metric("Top Route", str(hot.get("SECTION") or "DBA Control Room"))
    c3.metric("Priority", f"{safe_float(hot.get('PRIORITY_SCORE')):.1f}")
    c4.metric("Effective Readiness", f"{safe_float(hot.get('EFFECTIVE_SCORE', hot.get('SCORE'))):.1f}")
    render_priority_dataframe(
        tower,
        title="DBA Control Tower priority index",
        priority_columns=[
            "CONTROL_TOWER_STATE", "PRIORITY_SCORE", "SECTION", "EFFECTIVE_SCORE",
            "SCORE", "DEPLOYMENT_LABEL", "GATE_DRIVERS", "TARGET_GAP_TO_99",
            "WHY_NOW", "FIRST_MOVE", "PROOF_REQUIRED",
        ],
        sort_by=["PRIORITY_SCORE", "TARGET_GAP_TO_99"],
        ascending=[False, False],
        raw_label="All DBA Control Tower rows",
        height=260,
        max_rows=9,
        column_config={
            "PRIORITY_SCORE": st.column_config.ProgressColumn("Priority", min_value=0, max_value=100, format="%.1f"),
            "EFFECTIVE_SCORE": st.column_config.ProgressColumn("Effective", min_value=0, max_value=100, format="%.1f"),
            "SCORE": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
            "TARGET_GAP_TO_99": st.column_config.ProgressColumn("Gap to 99", min_value=0, max_value=10, format="%.1f"),
        },
    )
    download_csv(tower, "dba_control_tower_priority_index.csv")


def _dba_autopilot_route_templates(section: object, lookback_hours: int) -> dict:
    """Return advisory-only route playbook templates for the top Control Tower lane."""
    route = str(section or "").upper()
    hours = max(1, min(safe_int(lookback_hours, 24), 168))
    if "WAREHOUSE" in route:
        return {
            "owner_route": "Warehouse owner / DBA capacity reviewer",
            "containment": "Use Warehouse Health to isolate the exact warehouse, workload, queue, and spill pattern before any setting change.",
            "candidate": "Use Warehouse Settings Manager only after owner approval; prefer the smallest targeted setting change with rollback SQL.",
            "preflight_sql": f"""SELECT warehouse_name, COUNT(*) AS queries,
       SUM(COALESCE(queued_overload_time, 0)) / 1000 AS queued_sec,
       SUM(COALESCE(bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3) AS remote_spill_gb,
       MAX(start_time) AS last_seen
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
GROUP BY warehouse_name
ORDER BY queued_sec DESC, remote_spill_gb DESC;""",
            "verification_sql": f"""SELECT warehouse_name, SUM(credits_used) AS credits_used,
       MAX(end_time) AS last_metered_hour
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
GROUP BY warehouse_name
ORDER BY credits_used DESC;""",
            "rollback_sql": "SHOW WAREHOUSES; -- Compare current settings to the approved before-change snapshot and rollback script.",
        }
    if "COST" in route:
        return {
            "owner_route": "FinOps owner / DBA cost reviewer",
            "containment": "Freeze savings claims; isolate top company, warehouse, database, role, user, and task driver before action.",
            "candidate": "Queue only the driver with owner, baseline/current value, finance confidence, and verification query attached.",
            "preflight_sql": f"""SELECT warehouse_name, SUM(credits_used) AS credits_used,
       MAX(end_time) AS last_metered_hour
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
GROUP BY warehouse_name
ORDER BY credits_used DESC;""",
            "verification_sql": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY ORDER BY start_time DESC LIMIT 100;",
            "rollback_sql": "SELECT 'Rollback is business-process rollback: restore approved warehouse/task settings and keep finance evidence.' AS rollback_boundary;",
        }
    if "WORKLOAD" in route:
        return {
            "owner_route": "Workload owner / DBA reliability reviewer",
            "containment": "Separate failing task, stored procedure, and query path from platform symptoms before retrying anything.",
            "candidate": "Retry or resume only after root cause, downstream blast radius, and last successful run are captured.",
            "preflight_sql": f"""SELECT name, state, scheduled_time, completed_time, error_code, error_message
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY(SCHEDULED_TIME_RANGE_START=>DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())))
ORDER BY scheduled_time DESC
LIMIT 100;""",
            "verification_sql": f"""SELECT query_id, user_name, warehouse_name, execution_status, error_code,
       total_elapsed_time / 1000 AS elapsed_sec, start_time
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
ORDER BY start_time DESC
LIMIT 100;""",
            "rollback_sql": "SHOW TASKS IN ACCOUNT; -- Confirm suspended/resumed state against the approved recovery plan.",
        }
    if "SECURITY" in route:
        return {
            "owner_route": "Security approver / DBA access reviewer",
            "containment": "Preserve login/grant evidence and avoid grant changes until requester, approver, and least-privilege proof are clear.",
            "candidate": "Route grant/revoke work through Security Posture with ticket, owner, approver, and before/after role evidence.",
            "preflight_sql": f"""SELECT event_timestamp, user_name, client_ip, reported_client_type, error_code, error_message
FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
WHERE event_timestamp >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
ORDER BY event_timestamp DESC
LIMIT 100;""",
            "verification_sql": "SHOW GRANTS TO USERS; SHOW GRANTS TO ROLES;",
            "rollback_sql": "SELECT 'Rollback requires approved inverse GRANT/REVOKE script and post-change access verification.' AS rollback_boundary;",
        }
    if "CHANGE" in route:
        return {
            "owner_route": "Change owner / DBA release reviewer",
            "containment": "Hold closure until DDL query_id, ticket, source-control/IaC, blast radius, and owner approval are attached.",
            "candidate": "Queue the change with object dependency impact and rollback statement before marking it controlled.",
            "preflight_sql": f"""SELECT query_id, user_name, role_name, warehouse_name, database_name, schema_name,
       query_type, start_time, LEFT(query_text, 500) AS query_preview
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
  AND (query_type ILIKE 'CREATE%' OR query_type ILIKE 'ALTER%' OR query_type ILIKE 'DROP%'
       OR query_type ILIKE 'GRANT%' OR query_type ILIKE 'REVOKE%')
ORDER BY start_time DESC
LIMIT 100;""",
            "verification_sql": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES LIMIT 100;",
            "rollback_sql": "SELECT 'Rollback must reference the approved change ticket and inverse DDL/IaC patch.' AS rollback_boundary;",
        }
    if "ALERT" in route:
        return {
            "owner_route": "Alert owner / DBA on-call",
            "containment": "Confirm the alert source and route the issue to the action queue before suppressing or closing anything.",
            "candidate": "Suppress only with owner approval, expiry window, and a linked action queue item.",
            "preflight_sql": "SELECT CURRENT_TIMESTAMP() AS alert_review_started_at;",
            "verification_sql": "SELECT CURRENT_TIMESTAMP() AS alert_delivery_or_route_evidence_required;",
            "rollback_sql": "SELECT 'Rollback suppression by re-enabling the alert rule and documenting the reopened action.' AS rollback_boundary;",
        }
    if "ACCOUNT" in route:
        return {
            "owner_route": "Account hygiene owner / DBA platform reviewer",
            "containment": "Prioritize hygiene gaps that affect authentication, ownership, recovery, or admin operability.",
            "candidate": "Queue account hygiene work with owner, approval, proof query, and closure notes.",
            "preflight_sql": "SHOW USERS;",
            "verification_sql": "SHOW USERS; SHOW ROLES;",
            "rollback_sql": "SELECT 'Rollback account hygiene changes through approved identity/admin process.' AS rollback_boundary;",
        }
    if "ARCHITECTURE" in route:
        return {
            "owner_route": "Platform architecture owner / DBA lead",
            "containment": "Keep new platform capability adoption inside the expert adoption gate until evidence and owner approval are clean.",
            "candidate": "Advance only controlled pilots with source health, owner, approval, rollback boundary, and verification query.",
            "preflight_sql": "SHOW DATABASES; SHOW WAREHOUSES;",
            "verification_sql": "SELECT CURRENT_TIMESTAMP() AS architecture_evidence_reviewed_at;",
            "rollback_sql": "SELECT 'Rollback means revoke pilot expansion and return capability to evidence-gathering state.' AS rollback_boundary;",
        }
    return {
        "owner_route": "On-call DBA / platform owner",
        "containment": "Assign DBA owner, capture current evidence, and route to the specialist workflow.",
        "candidate": "Work only the routed action with owner, ticket, approval, verification query, and closure proof.",
        "preflight_sql": f"SELECT CURRENT_TIMESTAMP() AS preflight_started_at, {hours} AS lookback_hours;",
        "verification_sql": "SELECT CURRENT_TIMESTAMP() AS verification_required_at;",
        "rollback_sql": "SELECT 'Rollback boundary must be documented before execution.' AS rollback_boundary;",
    }


def _dba_autopilot_flight_plan(
    tower: pd.DataFrame | None,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
    generated_at: datetime | None = None,
) -> pd.DataFrame:
    """Build an advisory DBA flight plan from the hottest Control Tower route."""
    generated_at = generated_at or datetime.now()
    if tower is None or tower.empty:
        section = "DBA Control Room"
        hot = {
            "SECTION": section,
            "CONTROL_TOWER_STATE": "Monitor",
            "PRIORITY_SCORE": 0,
            "WHY_NOW": "No active Control Tower priority row.",
            "FIRST_MOVE": "Keep fast snapshot current and review Alert Center.",
            "PROOF_REQUIRED": "fresh Control Room load and Alert Center review",
        }
    else:
        ordered = tower.sort_values("PRIORITY_SCORE", ascending=False) if "PRIORITY_SCORE" in tower.columns else tower
        hot = ordered.iloc[0].to_dict()
        section = str(hot.get("SECTION") or "DBA Control Room")
    templates = _dba_autopilot_route_templates(section, lookback_hours)
    mission_id = f"DBA-AUTO-{generated_at.strftime('%Y%m%d%H%M')}"
    priority_score = safe_float(hot.get("PRIORITY_SCORE", 0))
    scope = f"{company} / {environment} / {safe_int(lookback_hours, 24)}h"
    stop_condition = (
        "Stop if source evidence is stale, owner/ticket/approval is missing, rollback is unclear, "
        "or verification cannot prove before/after state."
    )
    stages = [
        (
            1,
            "Preflight",
            "Evidence current",
            f"Confirm Control Tower route {section}, active scope, source freshness, and impacted entity.",
            str(hot.get("WHY_NOW") or "Control Tower route selected."),
            templates["preflight_sql"],
        ),
        (
            2,
            "Containment",
            "No irreversible changes",
            str(hot.get("FIRST_MOVE") or templates["containment"]),
            templates["containment"],
            "",
        ),
        (
            3,
            "Approval Gate",
            "Owner and ticket attached",
            "Attach owner, ticket/change ID, approval group, and rollback boundary before controlled execution.",
            str(hot.get("PROOF_REQUIRED") or _dba_section_proof_required(section)),
            "",
        ),
        (
            4,
            "Execution Candidate",
            "Advisory only",
            templates["candidate"],
            "Baseline value, current value, approval status, and exact affected object or warehouse.",
            "SELECT 'Advisory only - execute through the owning specialist workflow after approval.' AS execution_boundary;",
        ),
        (
            5,
            "Verification",
            "Before/after proof required",
            "Run verification and attach result text before closure or savings/recovery claim.",
            "Verification result, query_id, before/after metric, and owner acknowledgement.",
            templates["verification_sql"],
        ),
        (
            6,
            "Rollback or Escalate",
            "Rollback path known",
            "If verification fails, rollback through approved path or escalate as an incident before handoff.",
            "Rollback statement/path, recovery evidence, reopened action queue item if needed.",
            templates["rollback_sql"],
        ),
    ]
    rows = []
    for rank, phase, gate, move, evidence, proof_sql in stages:
        rows.append({
            "MISSION_ID": mission_id,
            "PHASE_RANK": rank,
            "FLIGHT_PHASE": phase,
            "SECTION": section,
            "CONTROL_TOWER_STATE": str(hot.get("CONTROL_TOWER_STATE") or "Monitor"),
            "PRIORITY_SCORE": priority_score,
            "SCOPE": scope,
            "GO_NO_GO_GATE": gate,
            "DBA_MOVE": move,
            "EVIDENCE_REQUIRED": evidence,
            "PROOF_SQL": proof_sql,
            "STOP_CONDITION": stop_condition,
            "OWNER_ROUTE": templates["owner_route"],
            "AUTOPILOT_MODE": "Advisory Only",
        })
    return pd.DataFrame(rows)


def _build_dba_autopilot_flight_plan_markdown(
    plan: pd.DataFrame,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
) -> str:
    """Create an exportable operator packet for the Autopilot flight plan."""
    rows = plan if plan is not None and not plan.empty else _empty_df()
    mission_id = str(rows.iloc[0].get("MISSION_ID")) if not rows.empty else "DBA-AUTO"
    section = str(rows.iloc[0].get("SECTION")) if not rows.empty else "DBA Control Room"
    lines = [
        "# OVERWATCH DBA Autopilot Flight Plan",
        f"Mission: {mission_id}",
        f"Route: {section}",
        f"Scope: {company} / {environment} / {safe_int(lookback_hours, 24)}h",
        "Mode: Advisory Only",
        "",
    ]
    if rows.empty:
        lines.append("No flight-plan stages were available.")
    else:
        for _, row in rows.sort_values("PHASE_RANK").iterrows():
            proof = str(row.get("PROOF_SQL") or "").strip()
            lines.extend([
                f"## {safe_int(row.get('PHASE_RANK'))}. {row.get('FLIGHT_PHASE', '')}",
                f"Gate: {row.get('GO_NO_GO_GATE', '')}",
                f"Move: {row.get('DBA_MOVE', '')}",
                f"Evidence: {row.get('EVIDENCE_REQUIRED', '')}",
                f"Owner route: {row.get('OWNER_ROUTE', '')}",
                f"Stop: {row.get('STOP_CONDITION', '')}",
            ])
            if proof:
                lines.extend(["", "```sql", proof, "```"])
            lines.append("")
    return "\n".join(lines).strip()


def _render_dba_autopilot_flight_plan(plan: pd.DataFrame, markdown: str) -> None:
    if plan is None or plan.empty:
        return
    hot = plan.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Autopilot", str(hot.get("AUTOPILOT_MODE") or "Advisory Only"))
    c2.metric("Mission", str(hot.get("MISSION_ID") or "DBA-AUTO"))
    c3.metric("Route", str(hot.get("SECTION") or "DBA Control Room"))
    c4.metric("Stages", f"{len(plan):,}")
    render_priority_dataframe(
        plan,
        title="DBA Autopilot flight plan",
        priority_columns=[
            "FLIGHT_PHASE", "GO_NO_GO_GATE", "DBA_MOVE",
            "EVIDENCE_REQUIRED", "OWNER_ROUTE", "STOP_CONDITION",
        ],
        sort_by=["PHASE_RANK"],
        ascending=[True],
        raw_label="All Autopilot flight-plan rows",
        height=300,
        max_rows=6,
    )
    with st.expander("Autopilot packet", expanded=False):
        st.code(markdown, language="markdown")
        st.download_button(
            "Download Autopilot Packet",
            data=markdown,
            file_name="dba_autopilot_flight_plan.md",
            mime="text/markdown",
            width="stretch",
        )
    download_csv(plan, "dba_autopilot_flight_plan.csv")


def _render_command_queue_control(
    queue: pd.DataFrame,
    raw_queue: pd.DataFrame | None = None,
    closure_rollup: pd.DataFrame | None = None,
    section_board: pd.DataFrame | None = None,
) -> None:
    summary = _command_queue_summary(queue)
    if closure_rollup is None:
        closure_rollup = _command_queue_closure_readiness(raw_queue if raw_queue is not None else queue)
    closure_blockers = (
        0
        if closure_rollup.empty
        else int(
            closure_rollup[
                (closure_rollup["CLOSURE_RANK"] <= 3)
                | (closure_rollup["CLOSURE_BLOCKER_ROWS"] > 0)
            ]["CLOSURE_BLOCKER_ROWS"].sum()
        )
    )
    st.markdown("**DBA Command Queue Control**")
    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
    c1.metric("Open DBA Actions", f"{summary['open']:,}", delta_color="inverse")
    c2.metric("Overdue", f"{summary['overdue']:,}", delta_color="inverse")
    c3.metric("Execution Ready", f"{summary['execution_ready']:,}")
    c4.metric("Audit Ready", f"{summary['audit_ready']:,}")
    c5.metric("Approval Blocks", f"{summary['approval_blocks']:,}", delta_color="inverse")
    c6.metric("Route Ready", f"{summary['route_ready']:,}")
    c7.metric("High Risk", f"{summary['high_risk']:,}", delta_color="inverse")
    c8.metric("Closure Blocks", f"{closure_blockers:,}", delta_color="inverse")

    if section_board is None:
        section_board = _dba_section_operability_board(
            command_queue=queue,
            closure_rollup=closure_rollup,
        )
    if not section_board.empty:
        render_priority_dataframe(
            section_board,
            title="DBA control-plane operating board",
            priority_columns=[
                "OPERABILITY_STATE", "SECTION", "EFFECTIVE_SCORE", "SCORE",
                "DEPLOYMENT_LABEL", "GATE_DRIVERS", "OPEN_ACTIONS",
                "OVERDUE", "EXECUTION_READY", "METADATA_BLOCKS", "APPROVAL_BLOCKS",
                "CLOSURE_READINESS", "CLOSURE_BLOCKERS", "FIXED_WITHOUT_VERIFICATION",
                "RECOVERY_RISK_ROWS", "LOWEST_COMPONENT", "LOWEST_SCORE",
                "PROOF_REQUIRED", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["OPERABILITY_RANK", "EFFECTIVE_SCORE"],
            ascending=[True, True],
            raw_label="All DBA control-plane operating rows",
            height=280,
            max_rows=12,
            column_config={
                "EFFECTIVE_SCORE": st.column_config.ProgressColumn("Effective", min_value=0, max_value=100, format="%.1f"),
                "SCORE": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
                "LOWEST_SCORE": st.column_config.ProgressColumn("Lowest", min_value=0, max_value=100, format="%.1f"),
            },
        )

    if queue.empty and closure_rollup.empty:
        st.success("No open action queue items or closure evidence blockers for the current company/environment scope.")
        return

    if not closure_rollup.empty:
        render_priority_dataframe(
            closure_rollup,
            title="Cross-section closure blockers",
            priority_columns=[
                "ROUTE", "CLOSURE_READINESS", "TOTAL_ACTIONS", "OPEN_ACTIONS",
                "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "RECOVERY_RISK_ROWS",
                "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                "LAST_STATUS", "LAST_SEVERITY", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "CLOSURE_BLOCKER_ROWS"],
            ascending=[True, False, False, False],
            raw_label="All command closure readiness rows",
            height=240,
            max_rows=10,
        )

    if queue.empty:
        st.success("No open action queue items for the current company/environment scope.")
        return

    route_readiness = _command_queue_route_readiness(queue)
    if not route_readiness.empty:
        render_priority_dataframe(
            route_readiness,
            title="Command readiness by DBA route",
            priority_columns=[
                "ROUTE", "OPEN_ACTIONS", "OVERDUE", "EXECUTION_READY", "AUDIT_READY",
                "ROUTE_READY", "OWNER_GAPS", "APPROVAL_BLOCKS", "METADATA_BLOCKS",
                "CONTROL_READY_PCT", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["OVERDUE", "METADATA_BLOCKS", "APPROVAL_BLOCKS", "OPEN_ACTIONS"],
            ascending=[False, False, False, False],
            raw_label="All command route readiness rows",
            height=220,
            max_rows=10,
        )

    render_priority_dataframe(
        queue,
        title="Open queue items to assign, approve, verify, or escalate",
        priority_columns=[
            "SEVERITY", "DUE_STATE", "COMMAND_STATE", "COMMAND_EXECUTION_GATE",
            "COMMAND_ROUTE_READINESS", "COMMAND_AUDIT_READINESS", "CATEGORY", "ENTITY_NAME",
            "OWNER", "OWNER_EMAIL", "ONCALL_PRIMARY", "APPROVAL_GROUP",
            "STATUS", "COMMAND_EVIDENCE_REQUIRED", "NEXT_ACTION", "TICKET_ID",
            "APPROVER", "OWNER_SOURCE", "ROUTE",
        ],
        sort_by=["QUEUE_PRIORITY", "SEVERITY"],
        ascending=[True, True],
        raw_label="All open DBA command queue rows",
        height=300,
        max_rows=15,
    )


def _control_room_score(
    exceptions: pd.DataFrame,
    row: pd.Series | dict,
    credit_delta: float,
    regression_count: int,
    cortex_exception_count: int,
) -> int:
    if exceptions is None or exceptions.empty:
        high_count = medium_count = 0
    else:
        severities = exceptions.get("Severity", pd.Series(dtype=str)).astype(str)
        high_count = int((severities == "High").sum())
        medium_count = int((severities == "Medium").sum())
    failed_queries = safe_int(row.get("FAILED_QUERIES", 0))
    queued_queries = safe_int(row.get("QUEUED_QUERIES", 0))
    remote_spill = safe_int(row.get("REMOTE_SPILL_QUERIES", 0))
    penalty = (
        high_count * 12
        + medium_count * 6
        + min(failed_queries / 10, 10)
        + min(queued_queries / 10, 8)
        + min(remote_spill / 20, 8)
        + min(max(credit_delta, 0) / 5, 10)
        + min(safe_int(regression_count) * 3, 12)
        + min(safe_int(cortex_exception_count) * 2, 10)
    )
    return max(0, min(100, int(round(100 - penalty))))


def _control_room_rating(score: int) -> str:
    if score >= 92:
        return "Clear"
    if score >= 82:
        return "Watch"
    if score >= 70:
        return "Degraded"
    return "War Room"


def _render_watch_floor(
    data: dict,
    exceptions: pd.DataFrame,
    row: pd.Series | dict,
    period_credits: float,
    credit_delta: float,
    credit_price: float,
    regression_count: int,
    cortex_exception_count: int,
) -> None:
    score = _control_room_score(exceptions, row, credit_delta, regression_count, cortex_exception_count)
    rating = _control_room_rating(score)
    priority = _priority_exceptions(exceptions).head(3)
    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.1, 2.2])
    c1.metric("Readiness", f"{score}/100", rating)
    c2.metric("Critical Moves", f"{len(priority):,}", delta_color="inverse")
    c3.metric("Cost Window", f"${credits_to_dollars(period_credits, credit_price):,.0f}", f"{credit_delta:+.1f}%", delta_color="inverse")
    with c4:
        if priority.empty:
            st.success("Watch floor is clear. Use Release Compare or Source Health if you are validating a recent deployment.")
        else:
            first = priority.iloc[0]
            st.warning(
                f"First move: {first.get('Signal', 'Exception')} -> {first.get('Action', 'Review the routed workflow.')}"
            )

    st.markdown("**DBA Watch Floor**")
    if priority.empty:
        st.caption("No immediate exception cards. Keep this page as the morning triage and evidence export point.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        route = str(item.get("Route", "") or "")
        workflow = str(item.get("Workflow", "") or "")
        with cols[idx]:
            st.markdown(f"**{item.get('Severity', 'Signal')}: {item.get('Signal', '')}**")
            st.caption(str(item.get("Evidence", "")))
            st.write(str(item.get("Action", "")))
            if route and st.button(f"Open {route}", key=f"dba_watch_floor_{idx}_{route}", width="stretch"):
                _jump(route, workflow=workflow)


def _dba_handoff_rows(
    exceptions: pd.DataFrame | None,
    command_queue: pd.DataFrame | None,
    closure_rollup: pd.DataFrame | None,
    source_health: pd.DataFrame | None,
    *,
    max_rows: int = 14,
) -> pd.DataFrame:
    """Build an operational shift handoff from already-loaded Control Room evidence."""
    rows: list[dict] = []

    priority_exceptions = _priority_exceptions(exceptions if exceptions is not None else _empty_df())
    for _, item in priority_exceptions.head(5).iterrows():
        severity = str(item.get("Severity") or item.get("SEVERITY") or "Medium")
        route = str(item.get("Route") or item.get("ROUTE") or item.get("Domain") or "DBA Control Room")
        signal = str(item.get("Signal") or item.get("SIGNAL") or "Control-room exception")
        workflow = str(item.get("Workflow") or "")
        rows.append({
            "PRIORITY_RANK": 0 if severity.upper() in {"CRITICAL", "HIGH"} else 3,
            "LANE": route,
            "STATE": f"{severity} Exception",
            "EVIDENCE": str(item.get("Evidence") or item.get("DETAIL") or signal),
            "OWNER_OR_ROUTE": f"{route}{' / ' + workflow if workflow else ''}",
            "NEXT_ACTION": str(item.get("Action") or item.get("NEXT_ACTION") or "Open the routed workflow and validate evidence."),
            "PROOF_REQUIRED": _dba_section_proof_required(route),
            "SOURCE": "Watch Floor",
        })

    queue = command_queue.copy() if command_queue is not None and not command_queue.empty else _empty_df()
    if not queue.empty:
        queue.columns = [str(col).upper() for col in queue.columns]
        due_state = queue.get("DUE_STATE", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
        gate = queue.get("COMMAND_EXECUTION_GATE", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str)
        severity = queue.get("SEVERITY", pd.Series([""] * len(queue), index=queue.index)).fillna("").astype(str).str.upper()
        important = queue[
            due_state.eq("Overdue")
            | gate.str.startswith("Blocked")
            | severity.isin(["CRITICAL", "HIGH"])
        ].head(5)
        for _, item in important.iterrows():
            route = str(item.get("ROUTE") or _command_queue_route(item.get("CATEGORY")) or "DBA Control Room")
            entity = str(item.get("ENTITY_NAME") or item.get("ENTITY") or item.get("CATEGORY") or "queued item")
            owner = str(item.get("OWNER") or item.get("OWNER_EMAIL") or item.get("APPROVAL_GROUP") or route)
            evidence_required = str(item.get("COMMAND_EVIDENCE_REQUIRED") or item.get("EVIDENCE_GAP") or "")
            rows.append({
                "PRIORITY_RANK": 0 if str(item.get("DUE_STATE")) == "Overdue" else 1 if str(item.get("COMMAND_EXECUTION_GATE", "")).startswith("Blocked") else 2,
                "LANE": route,
                "STATE": str(item.get("COMMAND_STATE") or item.get("COMMAND_EXECUTION_GATE") or "Queued Action"),
                "EVIDENCE": f"{entity}; due={item.get('DUE_STATE', '')}; gate={item.get('COMMAND_EXECUTION_GATE', '')}",
                "OWNER_OR_ROUTE": owner,
                "NEXT_ACTION": str(item.get("NEXT_ACTION") or "Complete the queue row, then attach verification before closure."),
                "PROOF_REQUIRED": evidence_required or _dba_section_proof_required(route),
                "SOURCE": "Action Queue",
            })

    closure = closure_rollup.copy() if closure_rollup is not None and not closure_rollup.empty else _empty_df()
    if not closure.empty:
        closure.columns = [str(col).upper() for col in closure.columns]
        blocked = closure[
            (pd.to_numeric(closure.get("CLOSURE_RANK", pd.Series([9] * len(closure))), errors="coerce").fillna(9) <= 3)
            | (pd.to_numeric(closure.get("CLOSURE_BLOCKER_ROWS", pd.Series([0] * len(closure))), errors="coerce").fillna(0) > 0)
        ].head(5)
        for _, item in blocked.iterrows():
            route = str(item.get("ROUTE") or "DBA Control Room")
            rows.append({
                "PRIORITY_RANK": safe_int(item.get("CLOSURE_RANK", 3)),
                "LANE": route,
                "STATE": str(item.get("CLOSURE_READINESS") or "Closure Blocked"),
                "EVIDENCE": (
                    f"{safe_int(item.get('OPEN_ACTIONS')):,} open; "
                    f"{safe_int(item.get('OVERDUE_OPEN')):,} overdue; "
                    f"{safe_int(item.get('FIXED_WITHOUT_VERIFICATION')):,} fixed without verification"
                ),
                "OWNER_OR_ROUTE": str(item.get("OWNER") or route),
                "NEXT_ACTION": str(item.get("NEXT_CONTROL_ACTION") or "Attach closure proof before accepting the work as done."),
                "PROOF_REQUIRED": _dba_section_proof_required(route),
                "SOURCE": "Closure Rollup",
            })

    sources = source_health.copy() if source_health is not None and not source_health.empty else _empty_df()
    if not sources.empty:
        sources.columns = [str(col).upper() for col in sources.columns]
        source_blocks = sources[
            sources.get("STATE", pd.Series([""] * len(sources), index=sources.index)).fillna("").astype(str).isin(["Unavailable", "Stale"])
        ].head(4)
        for _, item in source_blocks.iterrows():
            state = str(item.get("STATE") or "Source Check")
            surface = str(item.get("SURFACE") or "Evidence surface")
            rows.append({
                "PRIORITY_RANK": 1 if state == "Unavailable" else 2,
                "LANE": "Source Health",
                "STATE": state,
                "EVIDENCE": f"{surface}; rows={safe_int(item.get('ROWS')):,}; scope={item.get('SCOPE', '')}",
                "OWNER_OR_ROUTE": "DBA / Platform",
                "NEXT_ACTION": str(item.get("NEXT_ACTION") or "Reload or refresh this evidence before acting."),
                "PROOF_REQUIRED": "current source health for active company, environment, lookback, budget, and global filters",
                "SOURCE": "Source Health",
            })

    if not rows:
        rows.append({
            "PRIORITY_RANK": 8,
            "LANE": "DBA Control Room",
            "STATE": "Routine Watch",
            "EVIDENCE": "No loaded exceptions, open command blockers, closure blockers, or stale evidence surfaces.",
            "OWNER_OR_ROUTE": "On-call DBA",
            "NEXT_ACTION": "Keep the fast snapshot current and review Alert Center for new routed issues.",
            "PROOF_REQUIRED": "fresh Control Room load and current Alert Center review",
            "SOURCE": "Handoff",
        })

    return pd.DataFrame(rows).sort_values(
        ["PRIORITY_RANK", "LANE", "STATE"],
        ascending=[True, True, True],
    ).head(max_rows).reset_index(drop=True)


def _build_dba_shift_handoff_markdown(
    handoff_rows: pd.DataFrame,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
    source_mode: str,
) -> str:
    """Create an email-friendly DBA shift handoff packet."""
    rows = handoff_rows if handoff_rows is not None and not handoff_rows.empty else _empty_df()
    lines = [
        "# OVERWATCH DBA Shift Handoff",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Scope: {company} / {environment}",
        f"Lookback: {int(lookback_hours)} hours",
        f"Source mode: {source_mode}",
        "",
        "## Work First",
    ]
    if rows.empty:
        lines.append("- No handoff rows were available.")
    else:
        for _, row in rows.iterrows():
            lines.append(
                f"- [{row.get('STATE', '')}] {row.get('LANE', '')}: {row.get('EVIDENCE', '')}. "
                f"Owner/route: {row.get('OWNER_OR_ROUTE', '')}. "
                f"Next: {row.get('NEXT_ACTION', '')}. "
                f"Proof: {row.get('PROOF_REQUIRED', '')}."
            )
    lines.extend([
        "",
        "## Closure Standard",
        "- Do not mark work done unless owner, ticket/change ID, approval, verification result, and recovery evidence are present where applicable.",
        "- Treat shared warehouse cost attribution as allocated/estimated unless verified against billing or finance evidence.",
        "- Reload stale evidence after changing company, environment, lookback, budget, or global filters.",
    ])
    return "\n".join(lines)


def _render_shift_handoff_panel(
    handoff_rows: pd.DataFrame,
    handoff_md: str,
    *,
    company: str,
    environment: str,
) -> None:
    if handoff_rows is None or handoff_rows.empty:
        return
    st.markdown("**DBA Shift Handoff**")
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Handoff Items", f"{len(handoff_rows):,}", delta_color="inverse")
    h2.metric("Escalate", f"{int((handoff_rows['PRIORITY_RANK'] <= 1).sum()):,}", delta_color="inverse")
    h3.metric(
        "Proof Blocks",
        f"{int(handoff_rows['STATE'].astype(str).str.contains('Blocked|Overdue|Unavailable|Stale', case=False, regex=True).sum()):,}",
        delta_color="inverse",
    )
    h4.metric("Source Issues", f"{int(handoff_rows['SOURCE'].astype(str).eq('Source Health').sum()):,}", delta_color="inverse")
    render_priority_dataframe(
        handoff_rows,
        title="Incoming DBA handoff queue",
        priority_columns=[
            "LANE", "STATE", "EVIDENCE", "OWNER_OR_ROUTE",
            "NEXT_ACTION", "PROOF_REQUIRED", "SOURCE",
        ],
        sort_by=["PRIORITY_RANK", "LANE", "STATE"],
        ascending=[True, True, True],
        raw_label="All DBA handoff rows",
        height=300,
        max_rows=12,
    )
    st.download_button(
        "Download DBA Shift Handoff",
        handoff_md,
        file_name=f"overwatch_dba_shift_handoff_{company.lower()}_{environment.lower()}.md",
        mime="text/markdown",
        key="dba_shift_handoff_download",
    )


def _build_dba_incident_markdown(
    incident_board: pd.DataFrame,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
    source_mode: str,
) -> str:
    rows = incident_board if incident_board is not None and not incident_board.empty else _empty_df()
    lines = [
        "# OVERWATCH DBA Incident Board",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Scope: {company} / {environment}",
        f"Lookback: {int(lookback_hours)} hours",
        f"Source mode: {source_mode}",
        "",
        "## Active Incidents",
    ]
    if rows.empty:
        lines.append("- No incident rows were available.")
    else:
        for _, row in rows.iterrows():
            lines.append(
                f"- {row.get('INCIDENT_ID', '')} [{row.get('SEVERITY', '')} / {row.get('STATUS', '')}] "
                f"{row.get('INCIDENT_TYPE', '')} on {row.get('AFFECTED_ROUTES', '')}: {row.get('SIGNALS', '')}. "
                f"Evidence: {row.get('EVIDENCE', '')}. "
                f"Containment: {row.get('CONTAINMENT_ACTION', '')}. "
                f"SLA: {row.get('SLA_TARGET', '')}. "
                f"Proof: {row.get('PROOF_REQUIRED', '')}."
            )
    lines.extend([
        "",
        "## Operating Rules",
        "- Containment comes before optimization or permanent configuration changes.",
        "- Do not close an incident until the proof requirements are attached to the action queue or change record.",
        "- Refresh stale or unavailable evidence before taking irreversible DBA action.",
    ])
    return "\n".join(lines)


def _render_incident_board_panel(
    incident_board: pd.DataFrame,
    incident_md: str,
    *,
    company: str,
    environment: str,
) -> None:
    if incident_board is None or incident_board.empty:
        return
    st.markdown("**DBA Incident Board**")
    i1, i2, i3, i4 = st.columns(4)
    i1.metric("Incidents", f"{len(incident_board):,}", delta_color="inverse")
    i2.metric(
        "Containment",
        f"{int(incident_board['STATUS'].astype(str).eq('Containment Required').sum()):,}",
        delta_color="inverse",
    )
    i3.metric("Overdue", f"{int(pd.to_numeric(incident_board['OVERDUE'], errors='coerce').fillna(0).sum()):,}", delta_color="inverse")
    i4.metric(
        "Evidence Issues",
        f"{int(pd.to_numeric(incident_board['SOURCE_ISSUES'], errors='coerce').fillna(0).sum()):,}",
        delta_color="inverse",
    )
    render_priority_dataframe(
        incident_board,
        title="Grouped operational incidents",
        priority_columns=[
            "INCIDENT_ID", "INCIDENT_TYPE", "SEVERITY", "STATUS",
            "AFFECTED_ROUTES", "SIGNALS", "OPEN_ACTIONS", "OVERDUE",
            "PROOF_BLOCKS", "SOURCE_ISSUES", "CONTAINMENT_ACTION",
            "INVESTIGATION_PATH", "SLA_TARGET", "PROOF_REQUIRED",
        ],
        sort_by=["STATUS", "SEVERITY", "OVERDUE", "PROOF_BLOCKS", "OPEN_ACTIONS"],
        ascending=[True, True, False, False, False],
        raw_label="All DBA incident rows",
        height=320,
        max_rows=10,
    )
    st.download_button(
        "Download DBA Incident Board",
        incident_md,
        file_name=f"overwatch_dba_incident_board_{company.lower()}_{environment.lower()}.md",
        mime="text/markdown",
        key="dba_incident_board_download",
    )


def _render_control_room_source_health(
    data: dict,
    company: str,
    environment: str,
    lookback_hours: int,
    cortex_budget_usd: float,
    include_deep_evidence: bool,
    allow_live_fallback: bool,
) -> pd.DataFrame:
    source_health = _dba_control_source_health_rows(
        data,
        st.session_state,
        company,
        environment,
        lookback_hours,
        cortex_budget_usd,
        include_deep_evidence,
        allow_live_fallback,
    )
    if source_health.empty:
        st.info("No source health rows are available yet.")
        return source_health
    current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
    stale = int(source_health["STATE"].eq("Stale").sum())
    unavailable = int(source_health["STATE"].eq("Unavailable").sum())
    mart_backed = int(
        source_health[
            source_health["STATE"].isin(["Loaded", "No Rows"])
            & source_health["MODE"].astype(str).str.contains("mart", case=False, regex=True)
        ].shape[0]
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current Surfaces", f"{current}/{len(source_health)}")
    c2.metric("Mart-Backed", f"{mart_backed:,}")
    c3.metric("Stale", f"{stale:,}", delta_color="inverse")
    c4.metric("Unavailable", f"{unavailable:,}", delta_color="inverse")
    st.caption(
        "Use this before acting from the Control Room. Stale rows mean evidence was loaded under a different "
        "company, environment, lookback, budget, fallback mode, or global filter scope."
    )
    render_priority_dataframe(
        source_health,
        title="Control-room evidence freshness and source mode",
        priority_columns=["STATE", "SURFACE", "MODE", "ROWS", "SCOPE", "MESSAGE", "NEXT_ACTION"],
        sort_by=["STATE_RANK", "SURFACE"],
        ascending=[True, True],
        raw_label="All control-room source health rows",
        height=360,
    )
    return source_health


def _latest_local_perf_result(*, sections: bool = False) -> dict:
    """Read the latest local release-check JSON result when available."""
    try:
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        results_dir = root / "perf_tests" / "results"
        if not results_dir.exists():
            return {}
        pattern = "*_sections.json" if sections else "*.json"
        candidates = [
            path for path in results_dir.glob(pattern)
            if path.is_file() and (sections or not path.name.endswith("_sections.json"))
        ]
        if not candidates:
            return {}
        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        with latest.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["_report_path"] = str(latest)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _latest_local_snowflake_suite_result() -> dict:
    """Read the latest guarded Snowflake release-check JSON result when available."""
    try:
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        results_dir = root / "perf_tests" / "results"
        if not results_dir.exists():
            return {}
        candidates = [path for path in results_dir.glob("*_snowflake_safe_suite.json") if path.is_file()]
        if not candidates:
            return {}
        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        with latest.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["_report_path"] = str(latest)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _running_in_streamlit_in_snowflake() -> bool:
    """Return True when the app is using Snowflake's injected Streamlit session."""
    if "_overwatch_is_sis" in st.session_state:
        return bool(st.session_state.get("_overwatch_is_sis"))
    try:
        from snowflake.snowpark.context import get_active_session

        get_active_session()
        is_sis = True
    except Exception:
        is_sis = False
    st.session_state["_overwatch_is_sis"] = is_sis
    return is_sis


def _render_app_performance_guardrail() -> None:
    """Show app runtime health, query-budget pressure, and deployment gates."""
    telemetry = get_query_telemetry()
    budget_summary = get_query_budget_summary()
    is_sis = _running_in_streamlit_in_snowflake()
    http_result = {} if is_sis else _latest_local_perf_result(sections=False)
    section_result = {} if is_sis else _latest_local_perf_result(sections=True)
    snowflake_result = {} if is_sis else _latest_local_snowflake_suite_result()
    http_summary = http_result.get("summary", {}) if isinstance(http_result.get("summary"), dict) else http_result
    section_summary = section_result.get("summary", {}) if isinstance(section_result.get("summary"), dict) else section_result
    telemetry_count = 0 if telemetry is None or telemetry.empty else len(telemetry)
    budget_watch = 0
    budget_high = 0
    if budget_summary is not None and not budget_summary.empty and "budget_risk" in budget_summary.columns:
        risk = budget_summary["budget_risk"].fillna("").astype(str).str.upper()
        budget_watch = int(risk.isin(["WATCH", "HIGH"]).sum())
        budget_high = int(risk.eq("HIGH").sum())

    st.markdown("**OVERWATCH App Operations**")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Last Render", f"{safe_int(st.session_state.get('_overwatch_last_section_render_ms')):,} ms")
    c2.metric("Session Queries", f"{telemetry_count:,}")
    c3.metric("Budget Watch", f"{budget_watch:,}", f"{budget_high:,} High", delta_color="inverse")
    c4.metric("HTTP p95", f"{safe_float(http_summary.get('p95_ms')):,.0f} ms")
    c5.metric("Section p95", f"{safe_float(section_summary.get('p95_ms')):,.0f} ms")
    c6.metric("Slowest", str(section_summary.get("slowest_section") or "n/a"))
    if is_sis:
        st.info(
            "External release-check files are not available inside Streamlit-in-Snowflake. "
            "Use live render and query-budget signals here, and complete deployment validation from the release workstation."
        )

    readiness_rows = []
    for label, payload, summary in [
        ("App shell load", http_result, http_summary),
        ("Section render path", section_result, section_summary),
    ]:
        if not payload:
            readiness_rows.append({
                "GATE": label,
                "STATE": "External validation not loaded",
                "P95_MS": 0,
                "ERROR_RATE": 0,
                "NEXT_ACTION": "Complete release validation from the deployment workstation before changing production.",
            })
            continue
        state = str(summary.get("readiness_state") or payload.get("readiness_state") or "UNKNOWN")
        error_rate = safe_float(summary.get("error_rate", payload.get("error_rate", 0)))
        p95_ms = safe_float(summary.get("p95_ms", payload.get("p95_ms", 0)))
        if state.upper() != "PASS":
            next_action = "Block release until p95/error-rate regression is explained."
        elif p95_ms >= 5000 or error_rate > 0:
            next_action = "Investigate slow or failing paths before release."
        else:
            next_action = "Keep as baseline and compare next run before committing performance-sensitive changes."
        readiness_rows.append({
            "GATE": label,
            "STATE": state,
            "P95_MS": round(p95_ms, 2),
            "ERROR_RATE": round(error_rate, 4),
            "NEXT_ACTION": next_action,
        })

    snowflake_suite = snowflake_result or st.session_state.get("perf_sql_last_run", {})
    readiness_rows.append({
        "GATE": "Snowflake metadata safety",
        "STATE": str(snowflake_suite.get("state") or "Not run from this session"),
        "P95_MS": 0,
        "ERROR_RATE": 0,
        "NEXT_ACTION": str(
            snowflake_suite.get("next_action")
            or "Run the guarded Snowflake validation before approving warehouse-side release changes."
        ),
    })
    readiness = pd.DataFrame(readiness_rows)
    render_priority_dataframe(
        readiness,
        title="Deployment runtime gates",
        priority_columns=["GATE", "STATE", "P95_MS", "ERROR_RATE", "NEXT_ACTION"],
        sort_by=["STATE", "P95_MS"],
        ascending=[True, False],
        raw_label="All deployment runtime gate rows",
        height=220,
    )

    if budget_summary is None or budget_summary.empty:
        st.info("No query budget telemetry has been recorded in this Streamlit session yet.")
    else:
        render_priority_dataframe(
            budget_summary,
            title="Current session query-budget pressure",
            priority_columns=[
                "section", "budget_risk", "calls", "unique_queries",
                "expensive_calls", "elapsed_sec", "max_rows", "max_result_mb",
            ],
            sort_by=["budget_risk", "expensive_calls", "elapsed_sec"],
            ascending=[False, False, False],
            raw_label="All query budget rows",
            height=260,
        )
        download_csv(budget_summary, "overwatch_query_budget_summary.csv")

    if telemetry is not None and not telemetry.empty:
        tail = telemetry.tail(50)
        render_priority_dataframe(
            tail,
            title="Latest app query events",
            priority_columns=[
                "timestamp", "section", "tier", "elapsed_ms",
                "rows", "result_mb", "ttl_key", "query_hash",
            ],
            sort_by=["elapsed_ms", "rows", "result_mb"],
            ascending=[False, False, False],
            raw_label="All latest query events",
            height=260,
        )


def _render_route_buttons(exceptions: pd.DataFrame) -> None:
    if exceptions.empty or "Route" not in exceptions.columns:
        return
    route_rows = (
        exceptions[["Route", "Workflow"]]
        .dropna(subset=["Route"])
        .drop_duplicates()
        .head(5)
        .to_dict("records")
    )
    cols = st.columns(min(max(len(route_rows), 1), 5))
    for idx, item in enumerate(route_rows):
        route = str(item.get("Route", ""))
        workflow = str(item.get("Workflow", "") or "")
        with cols[idx % len(cols)]:
            if st.button(route, key=f"dba_control_route_{route}", width="stretch"):
                _jump(route, workflow=workflow)


def _build_report(data: dict, exceptions: pd.DataFrame, company: str, credit_price: float, lookback_hours: int) -> str:
    summary = data.get("summary", _empty_df())
    credits = data.get("credits", _empty_df())
    task_sla_cost = data.get("task_sla_cost", _empty_df())
    procedure_sla_cost = data.get("procedure_sla_cost", _empty_df())
    cortex_summary = data.get("cortex_summary", _empty_df())
    cortex_exceptions = data.get("cortex_exceptions", _empty_df())
    row = summary.iloc[0] if not summary.empty else {}
    cr = credits.iloc[0] if not credits.empty else {}
    period_credits = safe_float(cr.get("PERIOD_CREDITS", 0))
    prior_credits = safe_float(cr.get("PRIOR_CREDITS", 0))
    credit_delta = ((period_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0
    cortex_budget = safe_float(_scalar_frame_value(data, "_cortex_budget_usd", "BUDGET_USD", 0))
    cortex_projected = safe_float(cortex_summary.iloc[0].get("PROJECTED_30D_COST", 0)) if not cortex_summary.empty else 0

    lines = [
        "# OVERWATCH DBA Control Room Brief",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Company view: {company}",
        f"Lookback: {lookback_hours} hours",
        "",
        "## Operating Summary",
        f"- Queries reviewed: {safe_int(row.get('TOTAL_QUERIES', 0)):,}",
        f"- Failed queries: {safe_int(row.get('FAILED_QUERIES', 0)):,}",
        f"- Queued queries: {safe_int(row.get('QUEUED_QUERIES', 0)):,}",
        f"- Remote spill queries: {safe_int(row.get('REMOTE_SPILL_QUERIES', 0)):,}",
        f"- p95 elapsed seconds: {safe_float(row.get('P95_ELAPSED_SEC', 0)):,.2f}",
        f"- Task SLA/cost regression candidates: {0 if task_sla_cost.empty else len(task_sla_cost):,}",
        f"- Stored procedure release-regression candidates: {0 if procedure_sla_cost.empty else len(procedure_sla_cost):,}",
        f"- Cortex projected 30-day cost: ${cortex_projected:,.2f} vs ${cortex_budget:,.2f} budget",
        f"- Cortex user/source exceptions: {0 if cortex_exceptions.empty else len(cortex_exceptions):,}",
        f"- Credits: {format_credits(period_credits)} (${credits_to_dollars(period_credits, credit_price):,.2f})",
        f"- Credit change vs prior window: {credit_delta:+.1f}%",
        "",
        "## Exceptions",
    ]
    if exceptions.empty:
        lines.append("- No major exceptions detected by the control room rules.")
    else:
        for _, item in exceptions.iterrows():
            lines.append(
                f"- {item['Severity']}: {item['Signal']} - {item['Evidence']} "
                f"Action: {item['Action']} Route: {item['Route']}."
            )
    if not task_sla_cost.empty:
        lines.extend(["", "## Task SLA / Cost Regression Candidates"])
        for _, item in task_sla_cost.head(10).iterrows():
            lines.append(
                f"- {item.get('SEVERITY', 'Medium')}: {item.get('TASK_NAME', '')} "
                f"{item.get('SIGNAL', '')} - {item.get('DETAIL', '')} "
                f"Procedure: {item.get('PROCEDURE_NAME', '')}. Impact hints: {item.get('IMPACT_OBJECTS', '')}."
            )
    if not procedure_sla_cost.empty:
        lines.extend(["", "## Stored Procedure Release Regression Candidates"])
        for _, item in procedure_sla_cost.head(10).iterrows():
            lines.append(
                f"- {item.get('SEVERITY', 'Medium')}: {item.get('PROCEDURE_NAME', '')} "
                f"{item.get('SIGNAL', '')} - latest {safe_float(item.get('LATEST_ELAPSED_SEC')):,.0f}s "
                f"vs avg {safe_float(item.get('AVG_ELAPSED_SEC')):,.0f}s; "
                f"estimated credits {safe_float(item.get('EST_TOTAL_CREDITS')):,.4f}."
            )
    if not cortex_exceptions.empty:
        lines.extend(["", "## Cortex Cost Control Candidates"])
        for _, item in cortex_exceptions.head(10).iterrows():
            lines.append(
                f"- {item.get('SEVERITY', 'Medium')}: {item.get('USER_NAME', '')} "
                f"{item.get('SOURCE', '')} {item.get('SIGNAL', '')}; "
                f"projected ${safe_float(item.get('PROJECTED_30D_COST')):,.2f}; "
                f"credits/request {safe_float(item.get('CREDITS_PER_REQUEST')):,.6f}."
            )
    lines.extend([
        "",
        "## Metric Notes",
        "- Credit by query is allocated from warehouse-hour metering and should be treated as estimated.",
        "- ACCOUNT_USAGE metrics can lag up to roughly 45 minutes.",
        "- Security and grant signals are scoped by the selected company naming rules where Snowflake metadata allows it.",
    ])
    return "\n".join(lines)


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    credit_price = safe_float(get_credit_price()) or 3.68

    render_operator_briefing(
        [
            ("First move", "Use the fast snapshot for cheap triage."),
            ("Evidence", "Load details only when a signal needs proof."),
            ("Control", "Route to the specialist workflow before taking action."),
            ("Output", "Export a DBA brief for leaders without giving them the app."),
        ],
        columns=4,
    )
    if st.session_state.get("exceptions_only_mode"):
        st.info(
            "Exceptions-only mode is on. This page is prioritizing actionable issues and report-ready evidence "
            "over broad exploratory charts."
        )

    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    with c1:
        lookback_hours = st.selectbox("Lookback", [12, 24, 48, 168], index=1, format_func=lambda h: f"{h} hours")
    with c2:
        cortex_budget_usd = st.number_input(
            "Cortex monthly budget ($)",
            min_value=1.0,
            value=float(st.session_state.get("cortex_control_budget_usd", 5000.0)),
            step=250.0,
            key="dba_control_room_cortex_budget_usd",
        )
    with c3:
        st.metric("Scope", f"{company} / {environment}")
    with c4:
        st.info(
            f"{freshness_note('ACCOUNT_USAGE')} "
            f"Cost confidence: {metric_confidence_label('allocated')}. "
            "Use this as triage, then validate high-impact actions in the drilldown page."
        )

    snapshot_scope_ok = _dba_snapshot_scope_compatible(environment, st.session_state)
    snapshot_scope_key = (
        str(company),
        str(environment),
        str(st.session_state.get("global_warehouse", "")),
        str(st.session_state.get("global_user", "")),
        str(st.session_state.get("global_role", "")),
        str(st.session_state.get("global_database", "")),
    )
    snapshot_result = None
    if st.session_state.get("dba_control_room_snapshot_scope_key") == snapshot_scope_key:
        snapshot_result = st.session_state.get("dba_control_room_snapshot_result")
    else:
        st.session_state.pop("dba_control_room_snapshot_scope_key", None)
        st.session_state.pop("dba_control_room_snapshot_result", None)

    if snapshot_scope_ok:
        st.caption("Fast mart snapshot lookup is on demand to avoid startup Snowflake queries.")
        if st.button("Check Fast Snapshot", key="dba_control_room_check_snapshot"):
            with st.spinner("Checking latest control-room mart snapshot..."):
                snapshot_result = load_latest_control_room_mart(company, max_age_hours=6)
                st.session_state["dba_control_room_snapshot_scope_key"] = snapshot_scope_key
                st.session_state["dba_control_room_snapshot_result"] = snapshot_result
    if snapshot_result is not None and snapshot_result.available and not snapshot_result.data.empty:
        snapshot = snapshot_result.data.copy()
        st.caption(f"Fast snapshot available from {snapshot_result.source}. Use it for cheap triage; load detail only for investigation.")
        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("Snapshot Health", f"{safe_float(snapshot['HEALTH_SCORE'].min()):.0f}/100")
        s2.metric("Failed Queries 24h", f"{safe_int(snapshot['FAILED_QUERIES_24H'].sum()):,}", delta_color="inverse")
        s3.metric("Failed Tasks 24h", f"{safe_int(snapshot['FAILED_TASKS_24H'].sum()):,}", delta_color="inverse")
        s4.metric("Credits 24h", format_credits(snapshot["CREDITS_24H"].sum()))
        s5.metric("Cortex 7d", f"${safe_float(snapshot['CORTEX_COST_7D_USD'].sum()):,.0f}", delta_color="inverse")
        if st.button("Use Fast Snapshot", key="dba_control_room_use_snapshot"):
            st.session_state["dba_control_room_data"] = _control_room_snapshot_to_data(snapshot)
            st.session_state["dba_control_room_company"] = company
            st.session_state["dba_control_room_lookback"] = 24
            st.session_state["dba_control_room_source_mode"] = "OVERWATCH mart snapshot"
            st.session_state["dba_control_room_meta"] = _dba_control_scope_meta(
                company,
                environment,
                24,
                safe_float(cortex_budget_usd),
                False,
                False,
            )
            _clear_dba_control_room_derived_state()
            st.rerun()
    elif snapshot_result is not None and not snapshot_result.available:
        st.caption("Fast mart snapshot unavailable. Install/run OVERWATCH_MART_SETUP.sql to enable cheap control-room triage.")
    elif not snapshot_scope_ok:
        st.caption(
            "Fast mart snapshot is company-level only. Clear environment/global filters to use it, "
            "or load DBA Control Room triage for scoped evidence."
        )

    include_deep_evidence = st.checkbox(
        "Include deep task/procedure/Cortex evidence",
        value=False,
        key="dba_control_room_include_deep_evidence",
        help=(
            "Default off keeps this page fast. Turn on only when you need task run baselines, "
            "stored procedure SLA/cost evidence, and Cortex exception detail in this page."
        ),
    )
    allow_live_fallback = st.checkbox(
        "Allow limited live fallback (24h max)",
        value=False,
        key="dba_control_room_allow_live_fallback",
        help=(
            "Default off prevents surprise long compiles. When enabled, Control Room only runs bounded "
            "24h ACCOUNT_USAGE probes for credits, failed queries, and failed logins; heavy panels stay deferred."
        ),
    )
    if allow_live_fallback:
        st.caption(
            "Limited fallback is capped to 24h and only covers credits, failed queries, and failed logins. "
            "Refresh the OVERWATCH mart or use specialist workflows for deep live evidence."
        )
    load_label = "Load DBA Control Room Deep Evidence" if include_deep_evidence else "Load DBA Control Room Triage"
    if st.button(load_label, key="dba_control_room_load", type="primary"):
        with st.spinner("Loading exception signals..."):
            session = get_session()
            st.session_state["dba_control_room_data"] = _load_control_room(
                session,
                company,
                credit_price,
                int(lookback_hours),
                safe_float(cortex_budget_usd),
                include_deep_evidence=bool(include_deep_evidence),
                allow_live_fallback=bool(allow_live_fallback),
            )
            st.session_state["dba_control_room_company"] = company
            st.session_state["dba_control_room_lookback"] = int(lookback_hours)
            st.session_state["dba_control_room_source_mode"] = (
                "Deep evidence mart + limited live fallback"
                if include_deep_evidence and allow_live_fallback
                else "Deep evidence mart-only"
                if include_deep_evidence
                else "Fast triage mart + limited live fallback"
                if allow_live_fallback
                else "Fast triage mart queries"
            )
            st.session_state["dba_control_room_live_fallback"] = bool(allow_live_fallback)
            st.session_state["dba_control_room_meta"] = _dba_control_scope_meta(
                company,
                environment,
                int(lookback_hours),
                safe_float(cortex_budget_usd),
                bool(include_deep_evidence),
                bool(allow_live_fallback),
            )
            _clear_dba_control_room_derived_state()

    data = st.session_state.get("dba_control_room_data", {})
    if not data:
        st.warning("Use the fast mart snapshot or load detail to see today's DBA exceptions and report-ready evidence.")
        st.markdown("**Designed workflow**")
        st.write("Fast snapshot -> investigate exception -> assign action -> export leadership evidence.")
        return

    loaded_lookback = st.session_state.get("dba_control_room_lookback", lookback_hours)
    source_mode = st.session_state.get("dba_control_room_source_mode", "Fast triage mart queries")
    expected_meta = _dba_control_scope_meta(
        company,
        environment,
        int(lookback_hours),
        safe_float(cortex_budget_usd),
        bool(include_deep_evidence),
        bool(allow_live_fallback),
    )
    loaded_meta = st.session_state.get("dba_control_room_meta", {})
    data_current = _dba_control_meta_matches(loaded_meta, expected_meta)
    if not data_current:
        st.warning(
            "Loaded DBA Control Room evidence is stale for the active scope. Reload before taking action "
            "or exporting a brief."
        )
        _render_control_room_source_health(
            data,
            company,
            environment,
            int(lookback_hours),
            safe_float(cortex_budget_usd),
            bool(include_deep_evidence),
            bool(allow_live_fallback),
        )
        return
    if source_mode == "OVERWATCH mart snapshot":
        st.info("Showing fast mart snapshot. Deep evidence tabs may be sparse until you load detail.")
    elif source_mode == "Fast triage mart queries":
        st.info("Showing fast triage. Deep task, procedure, and Cortex evidence is deferred to keep this page responsive.")
        if not st.session_state.get("dba_control_room_live_fallback"):
            st.caption("Live ACCOUNT_USAGE fallbacks were skipped. Missing mart panels show as unavailable instead of running slow scans.")
    elif "limited live fallback" in source_mode:
        st.info("Showing mart-first evidence with limited 24h live probes only where they are cheap enough for Control Room.")
        st.caption("Heavy account scans remain deferred; refresh the OVERWATCH mart or use specialist workflows for deep evidence.")

    exceptions = _severity_rows(data, credit_price)
    summary = data.get("summary", _empty_df())
    credits = data.get("credits", _empty_df())
    row = summary.iloc[0] if not summary.empty else {}
    cr = credits.iloc[0] if not credits.empty else {}
    period_credits = safe_float(cr.get("PERIOD_CREDITS", 0))
    prior_credits = safe_float(cr.get("PRIOR_CREDITS", 0))
    credit_delta = ((period_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0

    task_sla_cost = data.get("task_sla_cost", _empty_df())
    procedure_sla_cost = data.get("procedure_sla_cost", _empty_df())
    regression_count = (0 if task_sla_cost.empty else len(task_sla_cost)) + (0 if procedure_sla_cost.empty else len(procedure_sla_cost))
    cortex_summary = data.get("cortex_summary", _empty_df())
    cortex_exceptions = data.get("cortex_exceptions", _empty_df())
    cortex_projected = safe_float(cortex_summary.iloc[0].get("PROJECTED_30D_COST", 0)) if not cortex_summary.empty else 0

    m1, m2, m3, m4, m5, m6, m7, m8 = st.columns(8)
    m1.metric("Open Exceptions", len(exceptions))
    m2.metric("Failed Queries", f"{safe_int(row.get('FAILED_QUERIES', 0)):,}", delta_color="inverse")
    m3.metric("Queued Queries", f"{safe_int(row.get('QUEUED_QUERIES', 0)):,}", delta_color="inverse")
    m4.metric("p95 Runtime", f"{safe_float(row.get('P95_ELAPSED_SEC', 0)):,.0f}s")
    m5.metric("Credits", format_credits(period_credits), f"{credit_delta:+.1f}%", delta_color="inverse")
    m6.metric("Est. Cost", f"${credits_to_dollars(period_credits, credit_price):,.0f}")
    m7.metric("SLA/Cost Drift", f"{regression_count:,}", delta_color="inverse")
    m8.metric("Cortex Risk", f"{0 if cortex_exceptions.empty else len(cortex_exceptions):,}", f"${cortex_projected:,.0f}/30d", delta_color="inverse")

    a1, a2 = st.columns([1, 5])
    with a1:
        if st.button("Alert Center", key="dba_control_room_open_alert_center", width="stretch"):
            _jump("Alert Center")
            st.rerun()
    with a2:
        st.caption("All alert history, email-ready messages, suppression windows, and action queue routing are consolidated in Alert Center.")

    st.divider()

    active_view = st.radio(
        "DBA Control Room view",
        DBA_CONTROL_ROOM_PANES,
        horizontal=True,
        label_visibility="collapsed",
        key="dba_control_room_active_view",
    )

    if active_view == "Fast Watch":
        _render_watch_floor(
            data,
            exceptions,
            row,
            period_credits,
            credit_delta,
            credit_price,
            regression_count,
            0 if cortex_exceptions.empty else len(cortex_exceptions),
        )
        priority = _priority_exceptions(exceptions).head(8)
        if priority.empty:
            st.success("Fast Watch is clear for the loaded scope.")
        else:
            render_priority_dataframe(
                priority,
                title="Fast Watch priority lanes",
                priority_columns=["Severity", "Signal", "Evidence", "Action", "Route", "Workflow"],
                sort_by=["Severity", "Signal"],
                ascending=[True, True],
                raw_label="All fast-watch exception rows",
                height=260,
            )
            _render_route_buttons(priority)
        st.caption(
            "Control Tower, Autopilot, Incident Board, and Shift Handoff are deferred to Operations Tower "
            "so section switching stays fast."
        )

    elif active_view == "Operations Tower":
        ops_scope_key = _dba_control_ops_scope_key(
            company,
            environment,
            int(lookback_hours),
            safe_float(cortex_budget_usd),
            bool(include_deep_evidence),
            bool(allow_live_fallback),
            loaded_meta,
        )
        if st.session_state.get("dba_control_room_ops_scope_key") != ops_scope_key:
            st.session_state.pop("dba_control_room_ops_ready", None)
            st.session_state["dba_control_room_ops_scope_key"] = ops_scope_key
        if not st.session_state.get("dba_control_room_ops_ready"):
            st.info(
                "Operations Tower builds the heavier control-board package only when requested. "
                "Use Fast Watch for normal section switching and morning triage."
            )
            if st.button("Build Operations Tower", key="dba_control_room_build_ops", type="primary"):
                st.session_state["dba_control_room_ops_ready"] = True
                st.rerun()
        else:
            action_queue = data.get("action_queue", _empty_df())
            command_queue = _build_command_queue(action_queue)
            source_health_for_handoff = _dba_control_source_health_rows(
                data,
                st.session_state,
                company,
                environment,
                int(lookback_hours),
                safe_float(cortex_budget_usd),
                bool(include_deep_evidence),
                bool(allow_live_fallback),
            )
            closure_rollup_for_handoff = _command_queue_closure_readiness(action_queue)
            incident_board = _dba_incident_board(
                exceptions,
                command_queue,
                closure_rollup_for_handoff,
                source_health_for_handoff,
            )
            section_board_for_tower = _dba_section_operability_board(
                command_queue=command_queue,
                closure_rollup=closure_rollup_for_handoff,
                source_health=source_health_for_handoff,
            )
            control_tower = _dba_control_tower_priority_index(
                section_board_for_tower,
                incident_board,
                command_queue,
                source_health_for_handoff,
            )
            st.session_state["dba_control_tower_priority_index"] = control_tower
            _render_control_tower_priority_index(control_tower)
            autopilot_plan = _dba_autopilot_flight_plan(
                control_tower,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
            )
            autopilot_md = _build_dba_autopilot_flight_plan_markdown(
                autopilot_plan,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
            )
            st.session_state["dba_autopilot_flight_plan"] = autopilot_plan
            st.session_state["dba_autopilot_flight_plan_markdown"] = autopilot_md
            _render_dba_autopilot_flight_plan(autopilot_plan, autopilot_md)
            _render_command_queue_control(
                command_queue,
                action_queue,
                closure_rollup=closure_rollup_for_handoff,
                section_board=section_board_for_tower,
            )
            incident_md = _build_dba_incident_markdown(
                incident_board,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
                source_mode=source_mode,
            )
            st.session_state["dba_control_room_incident_board"] = incident_board
            _render_incident_board_panel(
                incident_board,
                incident_md,
                company=company,
                environment=environment,
            )
            handoff_rows = _dba_handoff_rows(
                exceptions,
                command_queue,
                closure_rollup_for_handoff,
                source_health_for_handoff,
            )
            handoff_md = _build_dba_shift_handoff_markdown(
                handoff_rows,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
                source_mode=source_mode,
            )
            st.session_state["dba_control_room_handoff"] = handoff_rows
            _render_shift_handoff_panel(
                handoff_rows,
                handoff_md,
                company=company,
                environment=environment,
            )

    elif active_view == "Triage":
        if exceptions.empty:
            st.success("No major exceptions detected by the DBA Control Room rules.")
        else:
            st.subheader("Priority Exceptions")
            render_priority_dataframe(
                exceptions,
                title="Control-room exceptions to work first",
                priority_columns=[
                    "Severity", "Signal", "Evidence", "Action", "Route", "Workflow",
                ],
                sort_by=["Severity", "Signal"],
                ascending=[True, True],
                raw_label="All control-room exceptions",
                height=260,
            )
            _render_route_buttons(exceptions)

        st.divider()
        left, right = st.columns(2)
        with left:
            st.subheader("Top Cost Drivers")
            cost_df = data.get("cost_drivers", _empty_df())
            if not cost_df.empty:
                cost_df = cost_df.copy()
                cost_df["EST_COST"] = cost_df["ALLOCATED_CREDITS"].apply(
                    lambda v: credits_to_dollars(v, credit_price)
                )
                render_priority_dataframe(
                    cost_df,
                    title="Largest cost drivers",
                    priority_columns=[
                        "WAREHOUSE_NAME", "USER_NAME", "ROLE_NAME",
                        "DATABASE_NAME", "ALLOCATED_CREDITS", "EST_COST",
                        "QUERY_COUNT", "AVG_ELAPSED_SEC",
                    ],
                    sort_by=["ALLOCATED_CREDITS", "EST_COST"],
                    ascending=[False, False],
                    raw_label="All cost-driver rows",
                    height=280,
                )
                download_csv(cost_df, "dba_control_room_cost_drivers.csv")
            else:
                st.info("No cost-driver rows found in the loaded lookback.")
        with right:
            st.subheader("Warehouse Pressure")
            wh_df = data.get("warehouse_pressure", _empty_df())
            if not wh_df.empty:
                render_priority_dataframe(
                    wh_df,
                    title="Warehouses under pressure",
                    priority_columns=[
                        "WAREHOUSE_NAME", "WAREHOUSE_SIZE", "QUEUED_QUERIES",
                        "FAILED_QUERIES", "P95_ELAPSED_SEC", "REMOTE_SPILL_GB",
                        "QUERY_COUNT", "ALLOCATED_CREDITS",
                    ],
                    sort_by=["QUEUED_QUERIES", "FAILED_QUERIES", "P95_ELAPSED_SEC"],
                    ascending=[False, False, False],
                    raw_label="All warehouse-pressure rows",
                    height=280,
                )
                sel_wh = st.selectbox(
                    "Open warehouse",
                    [""] + wh_df["WAREHOUSE_NAME"].dropna().astype(str).tolist(),
                    key="dba_control_room_wh_select",
                )
                if sel_wh and st.button("Open Warehouse Health", key="dba_control_room_open_wh"):
                    _jump("Warehouse Health", warehouse=sel_wh)
            else:
                st.success("No warehouse pressure detected by the control-room thresholds.")

    elif active_view == "Drill Routes":
        r1, r2, r3 = st.columns(3)
        with r1:
            st.subheader("Reliability")
            st.write("Failed queries, task failures, queued workload, and slow p95 runtime.")
            reliability_routes = [
                ("Query Diagnosis", "Query diagnosis"),
                ("Task Graphs", "Task graphs"),
                ("Pipeline Health", "Pipeline health"),
            ]
            for label, workflow in reliability_routes:
                if st.button(label, key=f"dba_control_reliability_{label}", width="stretch"):
                    _jump("Workload Operations", workflow=workflow)
        with r2:
            st.subheader("Cost and Capacity")
            st.write("Bill explanations, contract pacing, warehouse pressure, rightsizing, recommendations, and value evidence.")
            for label, title, workflow in [
                ("Cost & Contract", "Cost & Contract", "Explain bill / attribution / contract"),
                ("AI / Cortex Spend", "Cost & Contract", "AI and Cortex spend"),
                ("Warehouse Health", "Warehouse Health", ""),
            ]:
                if st.button(label, key=f"dba_control_cost_{label}", width="stretch"):
                    _jump(title, workflow=workflow)
        with r3:
            st.subheader("Security and Governance")
            st.write("Login posture, grants, data sharing, object changes, procedure lineage, drift checks, and admin controls.")
            for title, workflow in [("Security Posture", "Access posture"), ("Change & Drift", "Object and access changes")]:
                if st.button(title, key=f"dba_control_security_{title}", width="stretch"):
                    _jump(title, workflow=workflow)

        st.divider()
        st.subheader("Exception Detail Samples")
        detail_view = st.radio(
            "Exception detail sample",
            DBA_CONTROL_ROOM_DETAIL_PANES,
            horizontal=True,
            label_visibility="collapsed",
            key="dba_control_room_detail_view",
        )
        detail_keys = {
            "Failed Queries": "failed_queries",
            "Task Failures": "task_failures",
            "Task SLA/Cost": "task_sla_cost",
            "Procedure SLA/Cost": "procedure_sla_cost",
            "Cortex Cost": "cortex_exceptions",
            "Failed Logins": "failed_logins",
            "Object Changes": "object_changes",
            "Action Queue": "action_queue",
        }
        key = detail_keys[detail_view]
        df = data.get(key, _empty_df())
        if not df.empty:
            display_df = _build_command_queue(df) if key == "action_queue" else df
            if key == "action_queue":
                priority_columns = [
                    "SEVERITY", "DUE_STATE", "COMMAND_STATE", "COMMAND_EXECUTION_GATE",
                    "COMMAND_ROUTE_READINESS", "CATEGORY", "ENTITY_NAME",
                    "OWNER", "OWNER_EMAIL", "ONCALL_PRIMARY", "APPROVAL_GROUP",
                    "STATUS", "CONTROL_GAP", "NEXT_ACTION", "TICKET_ID",
                    "APPROVER", "OWNER_SOURCE", "VERIFICATION_STATUS", "ROUTE",
                ]
                sort_by = ["QUEUE_PRIORITY", "SEVERITY"]
                ascending = [True, True]
            else:
                priority_columns = [
                    "SEVERITY", "SIGNAL", "ENTITY", "TASK_NAME", "PROCEDURE_NAME",
                    "QUERY_ID", "WAREHOUSE_NAME", "USER_NAME", "ERROR_MESSAGE",
                    "ALLOCATED_CREDITS", "EST_TOTAL_CREDITS", "DURATION_SEC",
                    "START_TIME", "SCHEDULED_TIME", "EVENT_TIMESTAMP",
                ]
                sort_by = [
                    "ALLOCATED_CREDITS", "EST_TOTAL_CREDITS", "DURATION_SEC",
                    "START_TIME", "SCHEDULED_TIME", "EVENT_TIMESTAMP",
                ]
                ascending = [False, False, False, False, False, False]
            render_priority_dataframe(
                display_df,
                title=f"{key.replace('_', ' ').title()} evidence",
                priority_columns=priority_columns,
                sort_by=sort_by,
                ascending=ascending,
                raw_label=f"All {key.replace('_', ' ')} evidence rows",
                height=320,
            )
        else:
            err = data.get(f"{key}_error", _empty_df())
            if not err.empty:
                st.warning(str(err["ERROR"].iloc[0]))
            else:
                st.info("No rows found.")

    elif active_view == "Release Compare":
        st.subheader("Release Compare")
        st.caption(
            "Compare before/after release windows for task graph duration, stored procedure runtime, "
            "estimated credits, failures, and impacted objects. Use this when a product release changes "
            "stored procedure or task-graph behavior."
        )
        today = date.today()
        default_after_end = today
        default_after_start = today - timedelta(days=7)
        default_before_end = default_after_start - timedelta(days=1)
        default_before_start = default_before_end - timedelta(days=7)

        w1, w2 = st.columns(2)
        with w1:
            before_range = st.date_input(
                "Before release window",
                value=(default_before_start, default_before_end),
                key="dba_release_before_window",
            )
        with w2:
            after_range = st.date_input(
                "After release window",
                value=(default_after_start, default_after_end),
                key="dba_release_after_window",
            )
        t1, t2, t3, t4 = st.columns(4)
        with t1:
            runtime_pct_threshold = st.number_input(
                "Runtime drift threshold (%)",
                min_value=1.0,
                value=25.0,
                step=5.0,
                key="dba_release_runtime_pct_threshold",
            )
        with t2:
            runtime_delta_sec_threshold = st.number_input(
                "Runtime delta threshold (sec)",
                min_value=0.0,
                value=30.0,
                step=30.0,
                key="dba_release_runtime_delta_sec_threshold",
            )
        with t3:
            credit_pct_threshold = st.number_input(
                "Credit drift threshold (%)",
                min_value=1.0,
                value=25.0,
                step=5.0,
                key="dba_release_credit_pct_threshold",
            )
        with t4:
            credit_delta_threshold = st.number_input(
                "Credit delta threshold",
                min_value=0.0,
                value=0.0,
                step=0.01,
                format="%.4f",
                key="dba_release_credit_delta_threshold",
            )
        st.caption(
            "Release compare flags failures, runtime drift above both runtime thresholds, "
            "or estimated-credit drift above both credit thresholds."
        )

        valid_ranges = (
            isinstance(before_range, (tuple, list)) and len(before_range) == 2
            and isinstance(after_range, (tuple, list)) and len(after_range) == 2
            and before_range[0] <= before_range[1]
            and after_range[0] <= after_range[1]
        )
        if not valid_ranges:
            st.warning("Choose valid before and after date ranges.")
        elif st.button("Compare Release Windows", key="dba_release_compare_load", type="primary"):
            with st.spinner("Comparing task graphs and stored procedure runs..."):
                try:
                    session = get_session()
                    st.session_state["dba_release_compare_data"] = _load_release_compare(
                        session,
                        company,
                        before_range[0],
                        before_range[1],
                        after_range[0],
                        after_range[1],
                        runtime_pct_threshold,
                        runtime_delta_sec_threshold,
                        credit_pct_threshold,
                        credit_delta_threshold,
                    )
                    st.session_state["dba_release_compare_company"] = company
                    st.session_state["dba_release_compare_credit_price"] = credit_price
                except Exception as exc:
                    st.session_state["dba_release_compare_data"] = {
                        "error": format_snowflake_error(exc),
                        "before_label": f"{before_range[0]} to {before_range[1]}",
                        "after_label": f"{after_range[0]} to {after_range[1]}",
                    }

        release_data = st.session_state.get("dba_release_compare_data", {})
        if release_data.get("error"):
            st.error(release_data["error"])
        elif release_data:
            task_compare = release_data.get("task_compare", _empty_df())
            proc_compare = release_data.get("procedure_compare", _empty_df())
            task_regressions = task_compare[
                task_compare.get("SEVERITY", pd.Series(dtype=str)).isin(["High", "Medium"])
            ] if not task_compare.empty else pd.DataFrame()
            proc_regressions = proc_compare[
                proc_compare.get("SEVERITY", pd.Series(dtype=str)).isin(["High", "Medium"])
            ] if not proc_compare.empty else pd.DataFrame()
            total_credit_delta = (
                safe_float(task_compare.get("EST_CREDITS_DELTA", pd.Series(dtype=float)).sum() if not task_compare.empty else 0)
                + safe_float(proc_compare.get("EST_CREDITS_DELTA", pd.Series(dtype=float)).sum() if not proc_compare.empty else 0)
            )
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Task Regressions", f"{len(task_regressions):,}", delta_color="inverse")
            k2.metric("Procedure Regressions", f"{len(proc_regressions):,}", delta_color="inverse")
            k3.metric("Est. Credit Delta", format_credits(total_credit_delta), delta_color="inverse")
            k4.metric("Est. Cost Delta", f"${credits_to_dollars(total_credit_delta, credit_price):,.2f}", delta_color="inverse")

            show_all = st.checkbox("Show stable rows too", value=False, key="dba_release_show_all")
            task_display = task_compare if show_all else task_regressions
            proc_display = proc_compare if show_all else proc_regressions

            st.markdown("**Task Graph / Task Changes**")
            if not task_display.empty:
                task_cols = [
                    col for col in [
                        "SEVERITY", "ENTITY", "SIGNAL", "RUNS_BEFORE", "RUNS_AFTER", "FAILURES_DELTA",
                        "AVG_DURATION_SEC_BEFORE", "AVG_DURATION_SEC_AFTER", "AVG_DURATION_CHANGE_PCT",
                        "EST_CREDITS_BEFORE", "EST_CREDITS_AFTER", "EST_CREDITS_CHANGE_PCT",
                        "PROCEDURE_NAME", "IMPACT_OBJECTS",
                    ] if col in task_display.columns
                ]
                render_priority_dataframe(
                    task_display[task_cols],
                    title="Task graph release regressions",
                    priority_columns=task_cols,
                    sort_by=[
                        "AVG_DURATION_CHANGE_PCT", "EST_CREDITS_CHANGE_PCT",
                        "FAILURES_DELTA", "EST_CREDITS_DELTA",
                    ],
                    ascending=[False, False, False, False],
                    raw_label="All task graph release comparison rows",
                    height=320,
                )
                download_csv(task_display, "overwatch_release_task_compare.csv")
            else:
                st.success("No material task graph regressions found for the selected windows.")

            st.markdown("**Stored Procedure Changes**")
            if not proc_display.empty:
                proc_cols = [
                    col for col in [
                        "SEVERITY", "ENTITY", "SIGNAL", "RUNS_BEFORE", "RUNS_AFTER", "FAILURES_DELTA",
                        "AVG_DURATION_SEC_BEFORE", "AVG_DURATION_SEC_AFTER", "AVG_DURATION_CHANGE_PCT",
                        "EST_CREDITS_BEFORE", "EST_CREDITS_AFTER", "EST_CREDITS_CHANGE_PCT",
                        "IMPACT_OBJECTS",
                    ] if col in proc_display.columns
                ]
                render_priority_dataframe(
                    proc_display[proc_cols],
                    title="Stored procedure release regressions",
                    priority_columns=proc_cols,
                    sort_by=[
                        "AVG_DURATION_CHANGE_PCT", "EST_CREDITS_CHANGE_PCT",
                        "FAILURES_DELTA", "EST_CREDITS_DELTA",
                    ],
                    ascending=[False, False, False, False],
                    raw_label="All stored procedure release comparison rows",
                    height=320,
                )
                download_csv(proc_display, "overwatch_release_procedure_compare.csv")
            else:
                st.success("No material stored procedure regressions found for the selected windows.")

            report = _build_release_compare_report(
                company,
                release_data,
                safe_float(st.session_state.get("dba_release_compare_credit_price", credit_price)) or credit_price,
            )
            with st.expander("Release comparison brief", expanded=False):
                st.text_area("Brief", report, height=320, key="dba_release_compare_report_text")
                st.download_button(
                    "Download Release Brief",
                    report,
                    file_name=f"overwatch_release_compare_{company}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                    mime="text/markdown",
                    key="dba_release_compare_report_download",
                )
        else:
            st.info("Choose release windows and run the comparison when you need post-release evidence.")

    elif active_view == "Executive Evidence":
        st.subheader("Report-Ready Brief")
        report = _build_report(data, exceptions, company, credit_price, int(loaded_lookback))
        st.text_area("Brief text", report, height=420)
        st.download_button(
            "Download DBA Brief",
            report,
            file_name=f"overwatch_dba_brief_{company}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
            mime="text/markdown",
            key="dba_control_room_brief_download",
        )

    elif active_view == "Source Health":
        st.subheader("Control Room Source Status")
        _render_control_room_source_health(
            data,
            company,
            environment,
            int(lookback_hours),
            safe_float(cortex_budget_usd),
            bool(include_deep_evidence),
            bool(allow_live_fallback),
        )
        snapshot_df = data.get("_mart_snapshot", _empty_df())
        if snapshot_df is not None and not snapshot_df.empty:
            st.subheader("Fast Snapshot Rows")
            render_priority_dataframe(
                snapshot_df,
                title="Latest fast snapshot",
                priority_columns=[
                    "SNAPSHOT_TS", "COMPANY", "HEALTH_SCORE", "FAILED_QUERIES_24H",
                    "FAILED_TASKS_24H", "CREDITS_24H", "CORTEX_COST_7D",
                ],
                sort_by=["SNAPSHOT_TS"],
                ascending=False,
                raw_label="All fast snapshot rows",
                height=180,
            )

    elif active_view == "App Operations":
        _render_app_performance_guardrail()
