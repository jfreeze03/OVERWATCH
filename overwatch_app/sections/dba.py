"""DBA Control Room v2."""

from __future__ import annotations

import pandas as pd

from overwatch_app.security.rbac import RbacContext, can_use_live_panic_mode
from overwatch_app.sections._shared import section_header


LIVE_MODE_METRICS = (
    "currently_running_queries_by_duration",
    "blocked_sessions_or_transactions",
    "warehouses_currently_queued_or_overloaded",
    "failed_tasks_last_hour_with_latency_caveat",
    "critical_high_active_alerts",
    "four_hour_burn_vs_baseline",
    "safe_query_kill_path",
    "query_profile_link",
    "live_current_state_badge",
)


def latency_label(source: str, *, truly_live: bool = False) -> str:
    if truly_live:
        return "Live current state"
    return f"{source} latency disclosed; do not treat as now."


def build_live_mode_model(frame: pd.DataFrame, context: RbacContext) -> dict:
    allowed = can_use_live_panic_mode(context)
    return {
        "allowed": allowed,
        "access_denied": not allowed,
        "metrics": LIVE_MODE_METRICS if allowed else (),
        "latency_caveat": latency_label("ACCOUNT_USAGE", truly_live=False),
        "kill_requires_confirmation": True,
        "kill_requires_audit": True,
        "data": frame if allowed and frame is not None else pd.DataFrame(),
    }


def render_morning_cockpit(frame: pd.DataFrame | None = None) -> None:
    import streamlit as st

    section_header(st, "DBA Control Room", "morning")
    st.dataframe(frame if frame is not None else pd.DataFrame(), hide_index=True)


def render_live_mode(model: dict | None = None) -> None:
    import streamlit as st

    section_header(st, "Live Mode", "live")
    model = model or {"access_denied": True, "data": pd.DataFrame()}
    if model.get("access_denied"):
        st.error("Access denied")
        return
    st.caption("Live current-state badge")
    st.dataframe(model.get("data", pd.DataFrame()), hide_index=True)
