"""Shared mart-backed first-paint data-state labels."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from utils.display_safety import clean_display_text


class DataState(str, Enum):
    LOADED_CURRENT = "LOADED_CURRENT"
    LOADED_STALE = "LOADED_STALE"
    NO_ROWS_FOR_SCOPE = "NO_ROWS_FOR_SCOPE"
    REFRESH_REQUIRED = "REFRESH_REQUIRED"
    SETUP_REQUIRED = "SETUP_REQUIRED"
    CONNECTION_UNAVAILABLE = "CONNECTION_UNAVAILABLE"
    QUERY_FAILED = "QUERY_FAILED"


@dataclass(frozen=True)
class DataStateSpec:
    short_label: str
    user_message: str
    tone: str
    recommended_action: str
    show_metric_cards: bool
    show_empty_table: bool
    allow_details_action: bool


DATA_STATE_SPECS: dict[DataState, DataStateSpec] = {
    DataState.LOADED_CURRENT: DataStateSpec(
        short_label="Current",
        user_message="Data loaded and current.",
        tone="healthy",
        recommended_action="Continue monitoring.",
        show_metric_cards=True,
        show_empty_table=True,
        allow_details_action=True,
    ),
    DataState.LOADED_STALE: DataStateSpec(
        short_label="Stale",
        user_message="Showing the latest available snapshot.",
        tone="warning",
        recommended_action="Refresh dashboard data.",
        show_metric_cards=True,
        show_empty_table=True,
        allow_details_action=True,
    ),
    DataState.NO_ROWS_FOR_SCOPE: DataStateSpec(
        short_label="No rows for selected scope",
        user_message="No mart rows match the selected filters.",
        tone="neutral",
        recommended_action="Broaden the scope or verify filters.",
        show_metric_cards=True,
        show_empty_table=True,
        allow_details_action=True,
    ),
    DataState.REFRESH_REQUIRED: DataStateSpec(
        short_label="Refresh required",
        user_message="Mart exists but has no current rows for this view.",
        tone="warning",
        recommended_action="Run the refresh task or open Setup Health.",
        show_metric_cards=True,
        show_empty_table=True,
        allow_details_action=True,
    ),
    DataState.SETUP_REQUIRED: DataStateSpec(
        short_label="Setup required",
        user_message="Required source object is missing or not configured.",
        tone="critical",
        recommended_action="Run mart setup or setup validation.",
        show_metric_cards=False,
        show_empty_table=True,
        allow_details_action=False,
    ),
    DataState.CONNECTION_UNAVAILABLE: DataStateSpec(
        short_label="Connection unavailable",
        user_message="Snowflake connection is unavailable.",
        tone="critical",
        recommended_action="Reconnect or retry from Setup Health.",
        show_metric_cards=False,
        show_empty_table=True,
        allow_details_action=False,
    ),
    DataState.QUERY_FAILED: DataStateSpec(
        short_label="Query failed",
        user_message="This summary query failed. Review Setup Health for safe details.",
        tone="critical",
        recommended_action="Review Setup Health.",
        show_metric_cards=False,
        show_empty_table=True,
        allow_details_action=False,
    ),
}


GENERIC_FINAL_PLACEHOLDERS = {
    "details load on request",
    "evidence loads " + "on request",
    "loading",
    "loading current packet",
    "loading current summary",
    "loading freshness",
    "loading packet",
    "loading packet trends",
    "loading source",
    "loading source data",
    "loading " + "summary",
    "on " + "demand",
    "on " + "request",
    "packet " + "pending",
    "pending",
    "source unavailable",
    "summary " + "pending",
    "summary " + "unavailable",
    "unavailable",
    "waiting for current summary packet",
}

EVIDENCE_LABEL_REPLACEMENTS = {
    "Open Details": "Open Details",
    "Load Full Evidence": "Open Full Details",
    "Open Cost Drivers": "Open Cost Drivers",
    "Open Security Details": "Open Security Details",
    "Details available when needed": "Details available when needed",
    "Details load on request": "Details available when needed",
}


def _normalize_state(state: DataState | str) -> DataState:
    if isinstance(state, DataState):
        return state
    raw = str(state or "").strip()
    key = raw.split(".")[-1].upper()
    aliases = {
        "CURRENT": DataState.LOADED_CURRENT,
        "LOADED": DataState.LOADED_CURRENT,
        "READY": DataState.LOADED_CURRENT,
        "STALE": DataState.LOADED_STALE,
        "OFFLINE": DataState.CONNECTION_UNAVAILABLE,
        "UNINITIALIZED": DataState.REFRESH_REQUIRED,
        "PENDING": DataState.REFRESH_REQUIRED,
        "REFRESH_NOT_RUN": DataState.REFRESH_REQUIRED,
        "SOURCE_NOT_CONFIGURED": DataState.SETUP_REQUIRED,
        "SUMMARY_MART_UNAVAILABLE": DataState.REFRESH_REQUIRED,
        "EMPTY_SCOPE": DataState.NO_ROWS_FOR_SCOPE,
    }
    if key in aliases:
        return aliases[key]
    try:
        return DataState[key]
    except Exception:
        try:
            return DataState(raw)
        except Exception:
            return DataState.REFRESH_REQUIRED


def data_state_spec(state: DataState | str) -> DataStateSpec:
    return DATA_STATE_SPECS[_normalize_state(state)]


def data_state_label(state: DataState | str) -> str:
    return data_state_spec(state).short_label


def data_state_message(state: DataState | str) -> str:
    return data_state_spec(state).user_message


def is_generic_placeholder(value: object) -> bool:
    text = clean_display_text(value).strip().lower()
    if not text:
        return True
    if text in GENERIC_FINAL_PLACEHOLDERS:
        return True
    return any(
        token in text
        for token in (
            "evidence loads " + "on request",
            "loading current summary",
            "loading the current",
            "packet " + "pending",
            "source unavailable",
            "summary " + "pending",
            "waiting for the current",
        )
    )


def classify_data_state(value: object, *, default: DataState = DataState.REFRESH_REQUIRED) -> DataState:
    text = clean_display_text(value).strip().lower()
    if not text:
        return default
    if "connection" in text and any(token in text for token in ("unavailable", "offline", "skipped")):
        return DataState.CONNECTION_UNAVAILABLE
    if "snowflake session" in text or text == "offline":
        return DataState.CONNECTION_UNAVAILABLE
    if "query failed" in text or "permission denied" in text or "could not finish" in text:
        return DataState.QUERY_FAILED
    if "no rows" in text or "empty scope" in text:
        return DataState.NO_ROWS_FOR_SCOPE
    if "missing source" in text or "source missing" in text or "not configured" in text:
        return DataState.SETUP_REQUIRED
    if "stale" in text or "last known good" in text or "last successful" in text:
        return DataState.LOADED_STALE
    if "loaded" in text or "available" in text or "ready" in text or "current" in text:
        return DataState.LOADED_CURRENT
    if is_generic_placeholder(text):
        return default
    return default


def final_state_text(value: object, *, default: DataState = DataState.REFRESH_REQUIRED) -> str:
    text = clean_display_text(value).strip()
    if not text or is_generic_placeholder(text):
        return data_state_label(classify_data_state(text, default=default))
    return text


def first_paint_text(value: object, *, default: DataState = DataState.REFRESH_REQUIRED) -> str:
    text = final_state_text(value, default=default)
    for old, new in EVIDENCE_LABEL_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def detail_available_text() -> str:
    return "Details available when needed"


__all__ = [
    "DATA_STATE_SPECS",
    "EVIDENCE_LABEL_REPLACEMENTS",
    "GENERIC_FINAL_PLACEHOLDERS",
    "DataState",
    "DataStateSpec",
    "classify_data_state",
    "data_state_label",
    "data_state_message",
    "data_state_spec",
    "detail_available_text",
    "final_state_text",
    "first_paint_text",
    "is_generic_placeholder",
]
