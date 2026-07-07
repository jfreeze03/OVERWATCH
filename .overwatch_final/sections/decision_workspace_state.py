"""Shared Decision Workspace state resolution helpers.

This module is intentionally lightweight. It must never import section modules
or query helpers, because it is used to decide whether a section can safely try
to load its compact Decision packet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
import sys
from typing import Literal

import streamlit as st


DecisionMode = Literal["READY", "STALE", "OFFLINE", "UNINITIALIZED"]

OFFLINE_BANNER_KEY = "_overwatch_decision_workspace_offline_banner_shown"
FIXTURE_ENV_VAR = "OVERWATCH_UI_FIXTURE_MODE"
FIXTURE_ALLOW_ENV_VAR = "OVERWATCH_ALLOW_FIXTURE_MODE"


@dataclass(frozen=True)
class DecisionWorkspaceState:
    mode: DecisionMode
    brief: object | None = None
    message: str = ""
    last_successful_at: str = ""
    repair_available: bool = False
    evidence_available: bool = False
    technical_details: str = ""
    source: str = ""


@dataclass(frozen=True)
class SectionDataState:
    decision_mode: DecisionMode
    evidence_mode: str = "summary"
    data_age: str = ""
    source: str = ""
    scope: str = ""
    detail_loaded: bool = False


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _running_under_tests() -> bool:
    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("OVERWATCH_TEST_MODE")
        or "unittest" in sys.modules
        or "pytest" in sys.modules
    )


def snowflake_native_app_runtime() -> bool:
    """Return whether the app is running in a production Snowflake Native surface."""
    return any(
        _truthy_env(name)
        for name in (
            "SNOWFLAKE_NATIVE_APP",
            "SNOWFLAKE_STREAMLIT_RUNTIME",
            "SNOWFLAKE_SIS_RUNTIME",
            "OVERWATCH_SNOWFLAKE_NATIVE_RUNTIME",
        )
    )


def decision_fixture_enabled() -> bool:
    """Return whether deterministic visual Decision Briefs may be rendered.

    Fixture mode is deliberately harder to enable than the old session-state
    switch. A stale ``st.session_state`` value cannot activate fixture data in a
    normal app session, and production Snowflake Native runtime always wins.
    """
    if snowflake_native_app_runtime():
        return False
    if not _truthy_env(FIXTURE_ENV_VAR):
        return False
    return _truthy_env(FIXTURE_ALLOW_ENV_VAR) or _running_under_tests()


def snowflake_entry_available() -> bool:
    """Best-effort, non-stopping Snowflake availability preflight.

    The normal app session helper can call ``st.stop`` when local Snowflake
    credentials are missing. Entry command briefs need to fail softly instead,
    so this function checks only cheap signals and catches all errors.
    """
    try:
        if st.session_state.get("sf_session") is not None:
            return True
    except Exception:
        pass
    try:
        from snowflake.snowpark.context import get_active_session

        return get_active_session() is not None
    except Exception:
        return False


def _brief_raw_value(brief: object, key: str, default: object = "") -> object:
    raw = getattr(brief, "raw_payload", {}) or {}
    if isinstance(raw, dict):
        return raw.get(key, default)
    return default


def workspace_mode_for_brief(brief: object | None) -> DecisionMode:
    """Resolve the single page state for a Decision Brief."""
    if brief is None:
        return "UNINITIALIZED"
    raw_mode = str(_brief_raw_value(brief, "workspace_mode", "") or "").upper()
    if raw_mode in {"READY", "STALE", "OFFLINE", "UNINITIALIZED"}:
        return raw_mode  # type: ignore[return-value]
    if bool(getattr(brief, "fallback_reason", "")):
        return "STALE" if tuple(getattr(brief, "metrics", ()) or ()) else "UNINITIALIZED"
    if bool(getattr(brief, "stale", False)):
        return "STALE"
    if int(getattr(brief, "missing_source_count", 0) or 0) > 0:
        return "STALE"
    return "READY"


def section_state_from_brief(brief: object | None, *, detail_loaded: bool = False) -> SectionDataState:
    mode = workspace_mode_for_brief(brief)
    scope = ""
    if brief is not None:
        scope = (
            f"{getattr(brief, 'requested_company', '') or getattr(brief, 'company', '')} / "
            f"{getattr(brief, 'requested_environment', '') or getattr(brief, 'environment', '')} / "
            f"{getattr(brief, 'requested_window_days', '') or getattr(brief, 'window_label', '')}"
        )
    return SectionDataState(
        decision_mode=mode,
        evidence_mode="detail" if detail_loaded else "summary",
        data_age=str(getattr(brief, "freshness_label", "") or ""),
        source=str(getattr(brief, "source", "") or ""),
        scope=scope,
        detail_loaded=detail_loaded,
    )


def should_render_legacy_overview(state: DecisionWorkspaceState | SectionDataState | DecisionMode) -> bool:
    """Return whether old overview-only summary boards may render below the brief."""
    mode = state if isinstance(state, str) else state.decision_mode if isinstance(state, SectionDataState) else state.mode
    return mode == "READY" and False


def last_success_label(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    text = str(value or "").strip()
    return text or "not recorded"


__all__ = [
    "DecisionMode",
    "DecisionWorkspaceState",
    "FIXTURE_ENV_VAR",
    "FIXTURE_ALLOW_ENV_VAR",
    "OFFLINE_BANNER_KEY",
    "SectionDataState",
    "decision_fixture_enabled",
    "last_success_label",
    "section_state_from_brief",
    "should_render_legacy_overview",
    "snowflake_entry_available",
    "snowflake_native_app_runtime",
    "workspace_mode_for_brief",
]
