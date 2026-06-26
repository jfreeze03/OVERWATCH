"""One-shot bootstrap flow for Decision Workspace command summaries."""

from __future__ import annotations

import streamlit as st

from sections.base import lazy_util


BOOTSTRAP_REQUEST_KEY = "_overwatch_decision_bootstrap_requested"


def _clear_command_brief_caches() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith("section_command_brief::"):
            st.session_state.pop(key, None)


def maybe_run_decision_workspace_bootstrap() -> None:
    """Consume the bootstrap request flag and run the setup procedure once."""
    if not bool(st.session_state.pop(BOOTSTRAP_REQUEST_KEY, False)):
        return
    get_session_for_action = lazy_util("get_session_for_action")
    session = get_session_for_action(
        "initialize decision summaries",
        surface="Decision Workspace",
        offline_note="Ask an administrator to run CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();",
    )
    if session is None:
        st.warning("Ask an administrator to run CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();")
        return
    try:
        session.sql("CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS();").collect()
        _clear_command_brief_caches()
        st.success("Decision summaries initialized. Refreshing the current command brief.")
    except Exception as exc:
        st.warning(
            "Decision summaries could not be initialized. Ask an administrator to run "
            f"CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS(); ({exc})"
        )


__all__ = ["BOOTSTRAP_REQUEST_KEY", "maybe_run_decision_workspace_bootstrap"]
