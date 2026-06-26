"""One-shot bootstrap flow for Decision Workspace command summaries."""

from __future__ import annotations

from collections.abc import Mapping

import streamlit as st

from sections.base import lazy_util


BOOTSTRAP_REQUEST_KEY = "_overwatch_decision_bootstrap_requested"
BOOTSTRAP_SUCCESS_KEY = "_overwatch_decision_bootstrap_success"
BOOTSTRAP_FAILURE_KEY = "_overwatch_decision_bootstrap_failure"
BOOTSTRAP_PROCEDURE = "SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS"
BOOTSTRAP_PROCEDURE_FALLBACKS = (
    BOOTSTRAP_PROCEDURE,
    "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL",
    "SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS",
)
BOOTSTRAP_SETUP_MESSAGE = (
    "Decision summaries are not initialized. Ask an administrator to deploy the latest "
    "OVERWATCH mart setup and initialize the Decision summary marts."
)


SECTION_FORCE_REFRESH_KEYS = {
    "Executive Landing": "_executive_landing_command_brief_force_refresh",
    "DBA Control Room": "dba_control_room_command_brief_force_refresh",
    "Alert Center": "alert_center_command_brief_force_refresh",
    "Cost & Contract": "cost_contract_command_brief_force_refresh",
    "Workload Operations": "workload_operations_command_brief_force_refresh",
    "Security Monitoring": "security_posture_command_brief_force_refresh",
}


def _is_fixture_or_invalid_last_good(value: object) -> bool:
    raw = getattr(value, "raw_payload", None)
    return not hasattr(value, "section") or (isinstance(raw, Mapping) and raw.get("fixture_mode") is True)


def _clear_command_brief_caches(*, clear_last_good: bool = False) -> None:
    for key in list(st.session_state.keys()):
        text = str(key)
        if not text.startswith("section_command_brief::"):
            continue
        if text.endswith("::last_good"):
            value = st.session_state.get(key)
            if clear_last_good or _is_fixture_or_invalid_last_good(value):
                st.session_state.pop(key, None)
            continue
        st.session_state.pop(key, None)
    st.session_state.pop("section_command_brief_last_telemetry", None)
    st.session_state.pop("section_command_brief_telemetry", None)


def _force_current_section_refresh(current_section: str | None) -> None:
    key = SECTION_FORCE_REFRESH_KEYS.get(str(current_section or ""))
    if key:
        st.session_state[key] = True


def _clean_bootstrap_failure_message(exc: object | None = None) -> str:
    """Return a daily-UI-safe bootstrap failure message without raw SQL details."""
    if exc is None:
        return BOOTSTRAP_SETUP_MESSAGE
    text = str(exc or "")
    lowered = text.lower()
    if any(
        token in lowered
        for token in (
            "unknown function",
            "does not exist",
            "not authorized",
            "insufficient privileges",
            "sql compilation error",
        )
    ):
        return BOOTSTRAP_SETUP_MESSAGE
    return "Decision summaries could not be initialized. Ask an administrator to review Decision summary setup health."


def _candidate_procedure_available(session: object, procedure_name: str) -> bool:
    """Return True when a bootstrap/refresh procedure is visible in the current schema."""
    rows = session.sql(f"SHOW PROCEDURES LIKE '{procedure_name}'").collect()
    return bool(rows)


def _resolve_bootstrap_procedure(session: object) -> str | None:
    """Find the best installed Decision summary refresh procedure for this app version."""
    try:
        for procedure_name in BOOTSTRAP_PROCEDURE_FALLBACKS:
            if _candidate_procedure_available(session, procedure_name):
                return procedure_name
        return None
    except Exception:
        # Some runtimes restrict SHOW PROCEDURES even when CALL is allowed. In that case,
        # try the current bootstrap procedure and let the sanitized failure path handle it.
        return BOOTSTRAP_PROCEDURE


def maybe_run_decision_workspace_bootstrap(current_section: str | None = None) -> None:
    """Consume the bootstrap request flag and run the setup procedure once."""
    success = st.session_state.pop(BOOTSTRAP_SUCCESS_KEY, "")
    if success:
        st.success(success)
    failure = st.session_state.pop(BOOTSTRAP_FAILURE_KEY, "")
    if failure:
        st.warning(_clean_bootstrap_failure_message(failure))
    if not bool(st.session_state.pop(BOOTSTRAP_REQUEST_KEY, False)):
        return
    get_session_for_action = lazy_util("get_session_for_action")
    session = get_session_for_action(
        "initialize decision summaries",
        surface="Decision Workspace",
        offline_note=BOOTSTRAP_SETUP_MESSAGE,
    )
    if session is None:
        st.warning(BOOTSTRAP_SETUP_MESSAGE)
        return
    procedure_name = _resolve_bootstrap_procedure(session)
    if not procedure_name:
        st.session_state[BOOTSTRAP_FAILURE_KEY] = BOOTSTRAP_SETUP_MESSAGE
        st.warning(st.session_state[BOOTSTRAP_FAILURE_KEY])
        return
    try:
        session.sql(f"CALL {procedure_name}();").collect()
        _clear_command_brief_caches(clear_last_good=True)
        _force_current_section_refresh(current_section)
        st.session_state[BOOTSTRAP_SUCCESS_KEY] = "Decision summaries initialized. Refreshing the current command brief."
    except Exception as exc:
        _clear_command_brief_caches(clear_last_good=False)
        st.session_state[BOOTSTRAP_FAILURE_KEY] = _clean_bootstrap_failure_message(exc)
        st.warning(st.session_state[BOOTSTRAP_FAILURE_KEY])
    else:
        st.rerun()


__all__ = [
    "BOOTSTRAP_FAILURE_KEY",
    "BOOTSTRAP_PROCEDURE",
    "BOOTSTRAP_PROCEDURE_FALLBACKS",
    "BOOTSTRAP_REQUEST_KEY",
    "BOOTSTRAP_SETUP_MESSAGE",
    "BOOTSTRAP_SUCCESS_KEY",
    "SECTION_FORCE_REFRESH_KEYS",
    "maybe_run_decision_workspace_bootstrap",
]
