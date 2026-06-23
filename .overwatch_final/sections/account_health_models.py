"""Account Health source-state and scope model helpers."""
from __future__ import annotations

import streamlit as st

from sections.account_health_contracts import ACCOUNT_HEALTH_SCOPE_FILTER_KEYS
from sections.base import lazy_pandas


pd = lazy_pandas()


def _account_health_scope_value(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _account_health_scope_meta(
    company: str,
    environment: str,
    window: str = "",
    state: dict | None = None,
    ignore_environment: bool = False,
    filter_keys: tuple[str, ...] | None = None,
) -> dict:
    """Return the filter scope that loaded Account Health telemetry must match."""
    state = state if state is not None else st.session_state
    meta = {
        "company": _account_health_scope_value(company),
        "environment": "No Database Context" if ignore_environment else _account_health_scope_value(environment),
    }
    if window:
        meta["window"] = _account_health_scope_value(window)
    for key in (ACCOUNT_HEALTH_SCOPE_FILTER_KEYS if filter_keys is None else filter_keys):
        meta[key] = _account_health_scope_value(state.get(key))
    return meta


def _account_health_meta_matches(meta: dict | None, expected: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(expected, dict):
        return False
    for key, expected_value in expected.items():
        if _account_health_scope_value(meta.get(key)) != _account_health_scope_value(expected_value):
            return False
    return True


def _account_health_row_count(value) -> int:
    if isinstance(value, pd.DataFrame):
        return len(value)
    if isinstance(value, dict):
        return sum(len(frame) for frame in value.values() if isinstance(frame, pd.DataFrame))
    if isinstance(value, str):
        return 1 if value.strip() else 0
    return 0


def _account_health_loaded(value) -> bool:
    return isinstance(value, (pd.DataFrame, dict, str))


def _account_health_is_empty(value) -> bool:
    if isinstance(value, pd.DataFrame):
        return value.empty
    if isinstance(value, dict):
        frames = [frame for frame in value.values() if isinstance(frame, pd.DataFrame)]
        return not frames or all(frame.empty for frame in frames)
    if isinstance(value, str):
        return not value.strip()
    return True


def _account_health_source_confidence(source: str, default: str) -> str:
    source_lower = str(source or "").lower()
    if ("fast" in source_lower and "summary" in source_lower) or "mart" in source_lower or "fact_" in source_lower:
        return "Fast summary"
    if "fallback" in source_lower:
        return "Live fallback"
    if "account_usage" in source_lower or "information_schema" in source_lower:
        return "Live Snowflake metadata"
    return default


def _account_health_source_next_action(state: str, source: str) -> str:
    source_lower = str(source or "").lower()
    if state == "Stale":
        return "Reload after changing company, environment, lookback, or triage filters."
    if state == "Unavailable":
        return "Deploy or refresh the summary/grants before relying on this surface."
    if state == "On demand":
        return "Refresh only when this workflow is part of the current DBA investigation."
    if state == "No Rows":
        return "Confirm the selected scope has recent account activity or persisted telemetry."
    if "fallback" in source_lower:
        return "Use for investigation; prefer summary refresh for repeated morning control."
    return "Current for the active Account Health scope."


def _account_health_has_source_state(state: dict) -> bool:
    """Return True once Account Health has telemetry or source errors to summarize."""
    health_data = state.get("health_data")
    if isinstance(health_data, dict) and bool(health_data):
        return True
    for key in (
        "account_health_operability_fact",
        "account_health_operability_fact_error",
        "account_health_access_hygiene",
        "account_health_access_hygiene_error",
        "account_health_checklist_trend",
        "account_health_checklist_trend_error",
        "account_health_closure_analytics",
        "account_health_closure_analytics_error",
        "morning_data",
        "morning_data_error",
    ):
        value = state.get(key)
        if isinstance(value, str):
            if value.strip():
                return True
            continue
        if value is not None:
            return True
    return False


def _account_health_source_health_rows(
    state: dict,
    company: str,
    environment: str,
) -> pd.DataFrame:
    """Summarize Account Health telemetry freshness and source strategy."""
    health_data = state.get("health_data", {})
    if not isinstance(health_data, dict):
        health_data = {}
    definitions = [
        {
            "surface": "Overview snapshot",
            "value": health_data,
            "source": health_data.get("_account_health_detail_source", "Fast summary or live account history"),
            "meta_key": "account_health_overview_meta",
            "window": "24h",
            "confidence": "Mixed",
        },
        {
            "surface": "Control-room summary",
            "value": health_data.get("_control_mart"),
            "source": health_data.get("_control_mart_source", "Fast control-room summary"),
            "meta_key": "account_health_overview_meta",
            "window": "24h",
            "confidence": "Fast summary",
        },
        {
            "surface": "Live status probe",
            "value": health_data.get("live"),
            "source": health_data.get("_live_source", "ACCOUNT_USAGE"),
            "meta_key": "account_health_live_status_meta",
            "window": "1h",
            "confidence": "Live Snowflake metadata",
        },
        {
            "surface": "Control summary",
            "value": state.get("account_health_operability_fact"),
            "source": "Fast Account Health control summary",
            "meta_key": "account_health_operability_fact_meta",
            "window": "30d",
            "confidence": "Fast summary",
            "error_key": "account_health_operability_fact_error",
        },
        {
            "surface": "Access hygiene",
            "value": state.get("account_health_access_hygiene"),
            "source": "Live ACCOUNT_USAGE users, logins, and grants",
            "meta_key": "account_health_access_hygiene_meta",
            "window_key": "account_health_access_hygiene_days",
            "default_window": "30d",
            "confidence": "Account-level control",
            "ignore_environment": True,
            "filter_keys": ("global_user",),
        },
        {
            "surface": "Checklist trend",
            "value": state.get("account_health_checklist_trend"),
            "source": "Workflow telemetry",
            "meta_key": "account_health_checklist_trend_meta",
            "window_key": "account_health_checklist_trend_days",
            "default_window": "30d",
            "confidence": "Workflow telemetry",
        },
        {
            "surface": "Closure analytics",
            "value": state.get("account_health_closure_analytics"),
            "source": "Action queue closure status",
            "meta_key": "account_health_closure_analytics_meta",
            "window_key": "account_health_closure_days",
            "default_window": "30d",
            "confidence": "Workflow telemetry",
        },
        {
            "surface": "DBA Daily Brief",
            "value": state.get("morning_data"),
            "source": state.get("morning_data_source", "DBA Control Room telemetry"),
            "meta_key": "morning_data_meta",
            "window_key": "account_health_morning_lookback",
            "default_window": "24h",
            "window_unit": "h",
            "confidence": "Control Room telemetry",
        },
    ]
    rows = []
    for item in definitions:
        raw_window = item.get("window")
        if raw_window is None:
            window_key = item.get("window_key")
            raw_window = state.get(window_key, item.get("default_window", "")) if window_key else item.get("default_window", "")
            raw_window_text = _account_health_scope_value(raw_window)
            if window_key and raw_window_text.isdigit():
                raw_window = f"{int(raw_window_text)}{item.get('window_unit', 'd')}"
        window = _account_health_scope_value(raw_window)
        expected_meta = _account_health_scope_meta(company, environment, window=window, state=state)
        if item.get("ignore_environment"):
            expected_meta = _account_health_scope_meta(
                company,
                environment,
                window=window,
                state=state,
                ignore_environment=True,
                filter_keys=item.get("filter_keys"),
            )
        value = item.get("value")
        error_key = item.get("error_key")
        error = state.get(error_key) if error_key else None
        if error:
            status = "Unavailable"
        elif not _account_health_loaded(value):
            status = "On demand"
        elif not _account_health_meta_matches(state.get(item["meta_key"]), expected_meta):
            status = "Stale"
        elif _account_health_is_empty(value):
            status = "No Rows"
        else:
            status = "Loaded"
        scope_environment = "No Database Context" if item.get("ignore_environment") else environment
        rows.append({
            "SURFACE": item["surface"],
            "STATE": status,
            "STATE_RANK": {
                "Unavailable": 0,
                "Stale": 1,
                "Loaded": 2,
                "No Rows": 3,
                "On demand": 4,
            }.get(status, 9),
            "SOURCE": item["source"],
            "CONFIDENCE": _account_health_source_confidence(item["source"], item["confidence"]),
            "ROWS": _account_health_row_count(value),
            "SCOPE": f"{company} / {scope_environment} / {window}",
            "NEXT_ACTION": _account_health_source_next_action(status, item["source"]),
        })
    return pd.DataFrame(rows)


__all__ = [
    "_account_health_has_source_state",
    "_account_health_is_empty",
    "_account_health_loaded",
    "_account_health_meta_matches",
    "_account_health_row_count",
    "_account_health_scope_meta",
    "_account_health_scope_value",
    "_account_health_source_confidence",
    "_account_health_source_health_rows",
    "_account_health_source_next_action",
]
