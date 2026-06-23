"""Account Health Morning Report renderer and packet builder."""
from __future__ import annotations

import streamlit as st

from sections.account_health_common import _account_health_action_session
from sections.account_health_models import _account_health_meta_matches, _account_health_scope_meta
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.shell_helpers import render_shell_snapshot
from utils.primitives import safe_float


pd = lazy_pandas()

render_load_status = _lazy_util("render_load_status")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
format_snowflake_error = _lazy_util("format_snowflake_error")


def _build_account_health_dba_morning_brief(
    action_session,
    *,
    company: str,
    environment: str,
    credit_price: float,
    lookback_hours: int,
    cortex_budget_usd: float,
    allow_live_fallback: bool = False,
) -> dict:
    """Build the DBA Daily Brief using the Control Room telemetry model."""
    from sections import dba_control_room as dba

    data = dba._load_control_room(
        action_session,
        company,
        credit_price,
        int(lookback_hours),
        safe_float(cortex_budget_usd),
        include_deep_evidence=False,
        allow_live_fallback=bool(allow_live_fallback),
    )
    exceptions = dba._severity_rows(data, credit_price)
    action_queue = data.get("action_queue", pd.DataFrame()) if isinstance(data, dict) else pd.DataFrame()
    command_queue = dba._build_command_queue(action_queue)
    closure_rollup = dba._command_queue_closure_readiness(action_queue)
    source_health = dba._dba_control_source_health_rows(
        data,
        st.session_state,
        company,
        environment,
        int(lookback_hours),
        safe_float(cortex_budget_usd),
        False,
        bool(allow_live_fallback),
    )
    incident_board = dba._dba_incident_board(
        exceptions,
        command_queue,
        closure_rollup,
        source_health,
    )
    section_board = dba._dba_section_operability_board(
        command_queue=command_queue,
        closure_rollup=closure_rollup,
        source_health=source_health,
    )
    operations_priority = dba._dba_operations_priority_index(
        section_board,
        incident_board,
        command_queue,
        source_health,
    )
    handoff_rows = dba._dba_handoff_rows(
        exceptions,
        command_queue,
        closure_rollup,
        source_health,
    )
    _release_gate_summary, release_gate_rows = dba._build_auto_release_readiness_gate(
        data,
        source_health,
    )
    escalation_packet = dba._dba_escalation_packet(
        operations_priority,
        incident_board,
        handoff_rows,
        release_gate_rows,
        company=company,
        environment=environment,
        lookback_hours=int(lookback_hours),
    )
    brief = dba._dba_morning_brief_rows(
        operations_priority,
        escalation_packet,
        handoff_rows,
    )
    markdown = dba._build_dba_morning_brief_markdown(
        brief,
        company=company,
        environment=environment,
        lookback_hours=int(lookback_hours),
    )
    return {
        "data": data,
        "exceptions": exceptions,
        "source_health": source_health,
        "operations_priority": operations_priority,
        "handoff": handoff_rows,
        "escalation_packet": escalation_packet,
        "brief": brief,
        "markdown": markdown,
    }


def render_account_health_morning_report(company: str, environment: str, credit_price: float) -> None:
    st.subheader("DBA Daily Brief")
    st.caption(
        "Telemetry-ranked DBA packet built from Control Room blockers, data readiness, handoff rows, "
        "deployment gates, and action-queue closure status."
    )

    brief_cols = st.columns([1, 1, 2])
    with brief_cols[0]:
        morning_lookback = st.selectbox(
            "Brief window",
            [12, 24, 48, 168],
            index=1,
            key="account_health_morning_lookback",
            format_func=lambda h: f"{h} hours",
        )
    with brief_cols[1]:
        allow_brief_live_fallback = st.toggle(
            "Bounded live fallback",
            key="account_health_morning_live_fallback",
            value=False,
            help=(
                "Use limited 24-hour ACCOUNT_USAGE checks when the fast summary is incomplete. "
                "Leave off for the cheapest morning packet."
            ),
        )
    with brief_cols[2]:
        render_shell_snapshot((("Scope", f"{company} / {environment}"),))

    if st.button("Refresh DBA Daily Brief", key="morning_gen", type="primary"):
        action_session = _account_health_action_session("refresh DBA Daily Brief")
        if action_session is None:
            return
        with render_load_status("Refreshing DBA Daily Brief", "DBA Daily Brief ready"):
            cortex_budget_usd = float(
                st.session_state.get(
                    "dba_control_room_cortex_budget_usd",
                    st.session_state.get("cortex_control_budget_usd", 5000.0),
                )
            )
            try:
                packet = _build_account_health_dba_morning_brief(
                    action_session,
                    company=company,
                    environment=environment,
                    credit_price=credit_price,
                    lookback_hours=int(morning_lookback),
                    cortex_budget_usd=safe_float(cortex_budget_usd),
                    allow_live_fallback=bool(allow_brief_live_fallback),
                )
            except Exception as exc:
                st.session_state["morning_data_error"] = format_snowflake_error(exc)
                st.warning(f"DBA Daily Brief unavailable: {st.session_state['morning_data_error']}")
                return
            packet["_source"] = (
                "DBA Control Room fast summary + bounded live fallback"
                if allow_brief_live_fallback
                else "DBA Control Room fast summary"
            )
            st.session_state.pop("morning_data_error", None)
            st.session_state["morning_data"] = packet
            st.session_state["morning_data_source"] = packet["_source"]
            st.session_state["morning_data_meta"] = _account_health_scope_meta(
                company, environment, window=f"{int(morning_lookback)}h"
            )
            st.session_state["dba_control_room_morning_brief"] = packet["brief"]
            st.session_state["dba_control_room_morning_brief_markdown"] = packet["markdown"]
            st.session_state["dba_operations_priority_index"] = packet["operations_priority"]
            st.session_state["dba_control_room_handoff"] = packet["handoff"]
            st.session_state["dba_control_room_escalation_packet"] = packet["escalation_packet"]

    morning_packet = st.session_state.get("morning_data")
    expected_meta = _account_health_scope_meta(company, environment, window=f"{int(morning_lookback)}h")
    if not morning_packet:
        st.info("Refresh the daily brief when the on-call DBA needs a ranked operating packet.")
    elif not _account_health_meta_matches(st.session_state.get("morning_data_meta"), expected_meta):
        st.warning("Loaded DBA Daily Brief is stale for the active scope. Refresh before using it.")
    else:
        from sections import dba_control_room as dba

        st.caption(f"Measurement: {morning_packet.get('_source', 'DBA Control Room telemetry')}")
        dba._render_dba_morning_brief(
            morning_packet.get("brief", pd.DataFrame()),
            str(morning_packet.get("markdown") or ""),
        )
        source_health = morning_packet.get("source_health", pd.DataFrame())
        if source_health is not None and not source_health.empty:
            with st.expander("Brief inputs", expanded=False):
                render_priority_dataframe(
                    source_health,
                    title="Morning brief input readiness",
                    priority_columns=[
                        "PRIORITY_RANK", "SURFACE", "STATE", "EVIDENCE",
                        "OWNER_OR_ROUTE", "NEXT_ACTION", "PROOF_REQUIRED", "SOURCE",
                    ],
                    sort_by=["PRIORITY_RANK", "SURFACE"],
                    ascending=[True, True],
                    raw_label="All morning brief input rows",
                    height=260,
                    max_rows=8,
                )


__all__ = [
    "_build_account_health_dba_morning_brief",
    "render_account_health_morning_report",
]
