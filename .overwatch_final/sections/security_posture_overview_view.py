# sections/security_posture_overview_view.py - Security Overview controller and renderer
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.security_posture_access_review import (
    _build_security_access_review,
    _security_action_for,
    _security_action_queue_closure_sql,
    _security_access_review_history_sql,
    _security_control_board,
    _security_operability_fact_sql,
    _security_priority_view,
    _security_workflow_for,
    _save_security_access_review_snapshot,
)
from sections.security_posture_action_queue import _queue_security_exceptions
from sections.security_posture_admin_view import _render_advanced_security_evidence
from sections.security_posture_contracts import (
    DATA_SHARING_EXPOSURE_WORKFLOW,
    FAILED_LOGINS_WORKFLOW,
    RISKY_GRANTS_WORKFLOW,
    SECURITY_BRIEF_WORKFLOWS,
    SECURITY_OVERVIEW_WORKFLOW,
    SECURITY_VIEW_ALIASES,
    WORKFLOW_DETAILS,
    WORKFLOWS,
)
from sections.security_posture_data import _build_security_mart_brief_sql, _build_security_summary_sql, _load_security_brief
from sections.security_posture_models import (
    _hide_security_proof_tables,
    _security_meta_matches,
    _security_proof_tables_visible,
    _security_rating,
    _security_scope_meta,
    _security_score,
    _show_security_proof_tables,
)
from sections.operator_case import make_case_evidence, render_add_to_case_button
from sections.decision_workspace_controls import should_render_daily_diagnostics
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_decision_evidence_panel,
    render_data_freshness,
    render_escaped_bold_text,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
)
from utils.downloads import download_text
from utils.primitives import safe_int
from utils.section_guidance import defer_source_note


pd = lazy_pandas()

day_window_selectbox = _lazy_util("day_window_selectbox")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_session = _lazy_util("get_session")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
run_query = _lazy_util("run_query")

def _render_security_watch_floor(score: int, exceptions: pd.DataFrame, row) -> None:
    priority = _security_priority_view(exceptions).head(3)
    failed_logins = safe_int(row.get("FAILED_LOGINS", 0))
    users_without_mfa = safe_int(row.get("USERS_WITHOUT_MFA", 0))
    shared_databases = safe_int(row.get("SHARED_DATABASES", 0))
    render_shell_snapshot((
        ("Priority Findings", f"{len(priority):,}"),
        ("Identity Signals", f"{failed_logins + users_without_mfa:,}"),
        ("Shared DBs", f"{shared_databases:,}"),
    ))
    if priority.empty:
        st.success("No urgent security findings crossed the brief thresholds.")
    else:
        first = priority.iloc[0]
        st.warning(
            f"First move: {first.get('FINDING_TYPE', 'Security finding')} for "
            f"{first.get('ENTITY', 'unknown')} -> {first.get('NEXT_ACTION', 'Review access telemetry.')}"
        )

    st.markdown("**Security Watch Floor**")
    if priority.empty:
        if shared_databases:
            st.caption("No urgent findings, but shared/imported database exposure exists. Review routes and consumers periodically.")
        else:
            st.caption("No immediate security cards. Use Failed Logins for audit telemetry or Data Sharing Exposure for external-consumer review.")
        return

    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        workflow = SECURITY_VIEW_ALIASES.get(str(item.get("NEXT_WORKFLOW") or ""), str(item.get("NEXT_WORKFLOW") or "Failed Logins"))
        with cols[idx]:
            render_escaped_bold_text(f"{item.get('SEVERITY', 'Medium')}: {item.get('FINDING_TYPE', '')}")
            st.caption(f"{item.get('ENTITY_TYPE', 'Access')}: {item.get('ENTITY', 'unknown')}")
            next_action = str(item.get("NEXT_ACTION", "") or "")
            proof_query = str(item.get("PROOF_QUERY", "") or "")
            help_text = " ".join(part for part in (next_action, proof_query) if part).strip()
            if st.button(
                f"Open {workflow}",
                key=f"security_watch_floor_{idx}_{workflow}",
                help=help_text or None,
                width="stretch",
            ):
                entity = str(item.get("ENTITY") or "").strip()
                if workflow == "Data Sharing Exposure":
                    if entity and entity.lower() != "unknown":
                        st.session_state["global_database"] = entity.split(".")[0]
                    for stale_key in ("ds_df_dt", "ds_df_shared_db"):
                        st.session_state.pop(stale_key, None)
                else:
                    if entity and entity.lower() != "unknown":
                        st.session_state["global_user"] = entity
                    for stale_key in (
                        "sec_df_login_sum",
                        "sec_df_failed_logins",
                        "sec_df_login_trend",
                        "sec_df_grants",
                        "sec_df_dom",
                        "sec_df_mfa",
                        "sec_df_exfil",
                        "sec_df_lin",
                        ):
                        st.session_state.pop(stale_key, None)
                _queue_security_workflow(workflow)

def _security_exception_strip_rows(summary, exceptions, meta: dict, company: str, environment: str, days: int) -> list[dict]:
    expected_meta = _security_scope_meta(company, environment, days)
    loaded = (
        summary is not None
        and not getattr(summary, "empty", True)
        and _security_meta_matches(meta, expected_meta)
    )
    if not loaded:
        return []
    priority = _security_priority_view(exceptions).head(4)
    if priority is not None and not priority.empty:
        rows = []
        for _, finding in priority.iterrows():
            rows.append({
                "severity": str(finding.get("SEVERITY") or "Medium"),
                "signal": str(finding.get("FINDING_TYPE") or "Security finding"),
                "entity": str(finding.get("ENTITY") or "unknown"),
                "detail": (
                    f"{safe_int(finding.get('EVENT_COUNT', 0)):,} event(s); "
                    f"{finding.get('NEXT_ACTION') or _security_action_for(finding.get('FINDING_TYPE', ''))[1]}"
                ),
                "route": str(finding.get("NEXT_WORKFLOW") or _security_workflow_for(finding.get("FINDING_TYPE", ""))),
            })
        return rows

    row = summary.iloc[0]
    failed_logins = safe_int(row.get("FAILED_LOGINS", 0))
    failed_users = safe_int(row.get("FAILED_USERS", 0))
    users_without_mfa = safe_int(row.get("USERS_WITHOUT_MFA", 0))
    recent_grants = safe_int(row.get("RECENT_GRANTS", 0))
    shared_databases = safe_int(row.get("SHARED_DATABASES", 0))
    rows: list[dict] = []
    if users_without_mfa:
        rows.append({
            "severity": "High",
            "signal": "MFA gaps",
            "entity": "Users",
            "detail": f"{users_without_mfa:,} user(s) missing MFA signal in the selected scope.",
            "route": "Failed Logins",
        })
    if failed_logins:
        rows.append({
            "severity": "High" if failed_logins >= 25 or failed_users >= 5 else "Medium",
            "signal": "Failed logins",
            "entity": "Identity",
            "detail": f"{failed_logins:,} failed login(s) across {failed_users:,} user(s).",
            "route": "Failed Logins",
        })
    if recent_grants >= 25:
        rows.append({
            "severity": "Medium",
            "signal": "Grant-change volume",
            "entity": "Roles",
            "detail": f"{recent_grants:,} grant change(s) in the lookback window.",
            "route": "Privilege Sprawl",
        })
    if shared_databases:
        rows.append({
            "severity": "Watch",
            "signal": "Shared data exposure",
            "entity": "Databases",
            "detail": f"{shared_databases:,} shared/imported database(s) need route and consumer validation.",
            "route": "Data Sharing Exposure",
        })
    return rows[:4]

def _render_security_exception_strip(rows: list[dict], *, loaded: bool = False) -> None:
    if not loaded:
        return
    st.markdown("**Exception Strip**")
    if not rows:
        st.success("No immediate security exceptions in the loaded summary.")
        return
    for row in rows[:4]:
        severity = str(row.get("severity") or "Watch")
        signal = str(row.get("signal") or "Security signal")
        entity = str(row.get("entity") or "Scope")
        detail = str(row.get("detail") or "")
        route = str(row.get("route") or "Security Monitoring / Access")
        if route == "Security Posture":
            route = "Security Monitoring / Access"
        if severity.lower() in {"critical", "high"}:
            st.warning(f"{severity}: {signal} - {entity}. {detail} Route: {route}.")
        else:
            st.info(f"{severity}: {signal} - {entity}. {detail} Route: {route}.")

def _security_action_brief(summary, exceptions, meta: dict, company: str, environment: str, days: int) -> dict:
    expected_meta = _security_scope_meta(company, environment, days)
    loaded = (
        summary is not None
        and not getattr(summary, "empty", True)
        and _security_meta_matches(meta, expected_meta)
    )
    if not loaded:
        if summary is not None and not getattr(summary, "empty", True):
            return {
                "state": "Stale",
                "headline": "Reload the security summary before acting.",
                "detail": "Loaded telemetry does not match the active company, environment, filters, or lookback.",
            }
        return {
            "state": "Summary unavailable",
            "headline": "Security command brief is the entry summary.",
            "detail": "Entry reads compact summary marts when available; load security evidence for current proof counts.",
        }

    row = summary.iloc[0]
    failed_logins = safe_int(row.get("FAILED_LOGINS", 0))
    users_without_mfa = safe_int(row.get("USERS_WITHOUT_MFA", 0))
    recent_grants = safe_int(row.get("RECENT_GRANTS", 0))
    shared_databases = safe_int(row.get("SHARED_DATABASES", 0))
    priority_count = len(_security_priority_view(exceptions).head(3))
    if users_without_mfa:
        return {
            "state": "MFA Watch",
            "headline": "Review users without MFA before calling posture clean.",
            "detail": f"{users_without_mfa:,} MFA gap(s), {failed_logins:,} failed login(s), and {recent_grants:,} recent grant change(s).",
        }
    if priority_count:
        return {
            "state": "Review",
            "headline": "Validate priority security exceptions.",
            "detail": f"{priority_count:,} priority finding(s) surfaced across access, login, grant, or sharing telemetry.",
        }
    if shared_databases:
        return {
            "state": "Exposure Check",
            "headline": "Validate shared database ownership and consumers.",
            "detail": f"{shared_databases:,} shared database(s) present in the selected window.",
        }
    return {
        "state": "Clear",
        "headline": "No immediate security blocker in the loaded brief.",
        "detail": f"{failed_logins:,} failed login(s) and {recent_grants:,} recent grant change(s) in scope.",
    }

def _render_security_action_brief(brief: dict) -> None:
    render_shell_status_strip(
        state=brief.get("state") or "Review",
        headline=brief.get("headline") or "Review security telemetry.",
        detail=brief.get("detail") or "",
    )

def _security_operating_snapshot(summary, meta: dict, company: str, environment: str, days: int) -> dict:
    loaded = (
        summary is not None
        and not getattr(summary, "empty", True)
        and _security_meta_matches(meta, _security_scope_meta(company, environment, days))
    )
    if not loaded:
        return {
            "loaded": False,
            "scope": str(company or "All"),
            "window": f"{safe_int(days, 30):d}d",
            "evidence": "Summary unavailable",
            "focus": "Access",
        }
    row = summary.iloc[0]
    return {
        "loaded": True,
        "failed": safe_int(row.get("FAILED_LOGINS", 0)),
        "mfa_gaps": safe_int(row.get("USERS_WITHOUT_MFA", 0)),
        "grant_changes": safe_int(row.get("RECENT_GRANTS", 0)),
        "shared_databases": safe_int(row.get("SHARED_DATABASES", 0)),
    }

def _render_security_operating_snapshot(snapshot: dict) -> None:
    loaded = bool(snapshot.get("loaded"))
    if not loaded:
        render_shell_kpi_row((
            ("Scope", str(snapshot.get("scope") or "All")),
            ("Window", str(snapshot.get("window") or "30d")),
            ("Telemetry", str(snapshot.get("evidence") or "Summary unavailable")),
        ))
        return
    render_shell_kpi_row((
        ("Failed", f"{safe_int(snapshot.get('failed')):,}"),
        ("MFA Gaps", f"{safe_int(snapshot.get('mfa_gaps')):,}"),
        ("Grant Changes", f"{safe_int(snapshot.get('grant_changes')):,}"),
        ("Shared DBs", f"{safe_int(snapshot.get('shared_databases')):,}"),
    ))

def _render_security_overview_entry(summary, exceptions, meta: dict, company: str, environment: str, days: int) -> None:
    """Render the default security triage surface without requiring live detail."""
    current = (
        summary is not None
        and not getattr(summary, "empty", True)
        and _security_meta_matches(meta, _security_scope_meta(company, environment, days))
    )
    st.markdown("**Security Overview**")
    if current:
        row = summary.iloc[0]
        render_shell_kpi_row((
            ("Failed Logins", f"{safe_int(row.get('FAILED_LOGINS', 0)):,}"),
            ("Risky Grants", f"{safe_int(row.get('RECENT_GRANTS', 0)):,}"),
            ("Privilege Changes", f"{safe_int(row.get('RECENT_GRANTS', 0)):,}"),
            ("Shared DBs", f"{safe_int(row.get('SHARED_DATABASES', 0)):,}"),
        ))
        action_rows = _security_exception_strip_rows(summary, exceptions, meta, company, environment, days)
    else:
        render_shell_kpi_row((
            ("Failed Logins", "Summary unavailable"),
            ("Risky Grants", "Summary unavailable"),
            ("Privilege Changes", "Summary unavailable"),
            ("Shared DBs", "Summary unavailable"),
        ))
        action_rows = [
            {
                "severity": "Info",
                "signal": "Review failed logins",
                "entity": "Identity",
                "detail": "Check repeated failures, MFA gaps, and source/client context.",
                "route": FAILED_LOGINS_WORKFLOW,
            },
            {
                "severity": "Info",
                "signal": "Review risky grants",
                "entity": "Access",
                "detail": "Check admin roles, grants to users, and grant-option exposure.",
                "route": RISKY_GRANTS_WORKFLOW,
            },
            {
                "severity": "Info",
                "signal": "Review sharing exposure",
                "entity": "Data sharing",
                "detail": "Validate inbound/outbound shares, consumers, and owner route.",
                "route": DATA_SHARING_EXPOSURE_WORKFLOW,
            },
        ]

    st.markdown("**Top Security Actions**")
    cols = st.columns(min(3, max(1, len(action_rows))))
    for idx, action in enumerate(action_rows[:3]):
        with cols[idx % len(cols)]:
            render_escaped_bold_text(f"{action.get('severity', 'Info')}: {action.get('signal', 'Security action')}")
            st.caption(f"{action.get('entity', 'Scope')}: {action.get('detail', '')}")
            route = SECURITY_VIEW_ALIASES.get(str(action.get("route") or ""), str(action.get("route") or FAILED_LOGINS_WORKFLOW))
            if st.button(f"Open {route}", key=f"security_overview_action_{idx}_{route}", width="stretch"):
                _queue_security_workflow(route)

def _security_command_lanes(snapshot: dict) -> list[dict[str, str]]:
    """Return Security Monitoring first-paint lanes."""
    if not snapshot.get("loaded"):
        return [
            {
                "label": "Failed logins",
                "value": "Summary unavailable",
                "state": "Identity",
                "detail": "Fast summary checks login spikes, unusual sources, and failed auth before live proof.",
            },
            {
                "label": "MFA gaps",
                "value": "Summary unavailable",
                "state": "Access",
                "detail": "Review active users without exposed MFA signal.",
            },
            {
                "label": "Grant changes",
                "value": "Summary unavailable",
                "state": "Privilege",
                "detail": "Admin grants, ownership, and future grants route here.",
            },
            {
                "label": "Shared data",
                "value": "Summary unavailable",
                "state": "Exposure",
                "detail": "Shares, external stages, and broad grants stay visible for review.",
            },
            {
                "label": "Policy posture",
                "value": "Detail explicit",
                "state": "Security",
                "detail": "Masking, row access, network policy, and integration drift.",
            },
            {
                "label": "Sensitive access",
                "value": "Detail explicit",
                "state": "Audit",
                "detail": "ACCESS_HISTORY and bytes-written signals identify risky access.",
            },
            {
                "label": "Access review",
                "value": "Detail explicit",
                "state": "Review",
                "detail": "Privileged grants need review context before action.",
            },
            {
                "label": "Closure status",
                "value": "Detail explicit",
                "state": "Audit",
                "detail": "Investigation notes, action status, and telemetry stay logged.",
            },
        ]
    return [
        {
            "label": "Failed logins",
            "value": f"{safe_int(snapshot.get('failed')):,}",
            "state": "Identity" if safe_int(snapshot.get("failed")) else "Clear",
            "detail": "Inspect spikes, service accounts, unusual sources, and business-hour drift.",
        },
        {
            "label": "MFA gaps",
            "value": f"{safe_int(snapshot.get('mfa_gaps')):,}",
            "state": "Access" if safe_int(snapshot.get("mfa_gaps")) else "Clear",
            "detail": "Prioritize active users and privileged roles.",
        },
        {
            "label": "Grant changes",
            "value": f"{safe_int(snapshot.get('grant_changes')):,}",
            "state": "Privilege" if safe_int(snapshot.get("grant_changes")) else "Clear",
            "detail": "Review ACCOUNTADMIN/SYSADMIN/SECURITYADMIN and ownership drift.",
        },
        {
            "label": "Shared data",
            "value": f"{safe_int(snapshot.get('shared_databases')):,}",
            "state": "Exposure" if safe_int(snapshot.get("shared_databases")) else "Clear",
            "detail": "Validate consumers, access purpose, and data classification.",
        },
        {
            "label": "Policy posture",
            "value": "Open workflow",
            "state": "Security",
            "detail": "Masking, row access, network policies, integrations, and shares.",
        },
        {
            "label": "Sensitive access",
            "value": "Open workflow",
            "state": "Audit",
            "detail": "ACCESS_HISTORY and output-volume anomalies need exact telemetry.",
        },
        {
            "label": "Access review",
            "value": "Open workflow",
            "state": "Review",
            "detail": "Use Privilege Sprawl before revoking or narrowing grants.",
        },
        {
            "label": "Closure status",
            "value": "Queue/audit",
            "state": "Audit",
            "detail": "Every fix needs action status, before/after state, and telemetry.",
        },
    ]

def _queue_security_workflow(workflow: str) -> None:
    workflow = SECURITY_VIEW_ALIASES.get(str(workflow or ""), str(workflow or ""))
    if workflow in WORKFLOWS:
        st.session_state["security_posture_requested_view"] = workflow
        st.session_state["security_posture_requested_workflow"] = workflow
        st.rerun()

def _security_brief_workflow_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in SECURITY_BRIEF_WORKFLOWS:
        workflow = str(item["WORKFLOW"])
        rows.append({
            "WORKFLOW": workflow,
            "BUTTON_LABEL": str(item["BUTTON_LABEL"]),
            "DBA_MOVE": str(item["DBA_MOVE"]),
            "WHEN": str(item["WHEN"]),
            "SOURCES": WORKFLOW_DETAILS.get(workflow, "Security workflow detail"),
        })
    return rows

def _render_security_brief_launchpad() -> None:
    with st.expander("Security drilldowns", expanded=False):
        rows = _security_brief_workflow_rows()
        cols = st.columns(4)
        for idx, row in enumerate(rows):
            with cols[idx % len(cols)]:
                render_escaped_bold_text(row["WORKFLOW"])
                help_text = f"{row['DBA_MOVE']} When: {row['WHEN']}"
                if st.button(
                    row["BUTTON_LABEL"],
                    key=f"security_brief_{row['WORKFLOW']}",
                    help=help_text,
                    width="stretch",
                ):
                    _queue_security_workflow(row["WORKFLOW"])

def _paint_security_brief_chrome(
    brief_slot,
    snapshot_slot,
    exception_slot,
    summary,
    exceptions,
    meta: dict,
    company: str,
    environment: str,
    days: int,
) -> None:
    with brief_slot.container():
        _render_security_action_brief(
            _security_action_brief(summary, exceptions, meta, company, environment, days)
        )
    with snapshot_slot.container():
        snapshot = _security_operating_snapshot(summary, meta, company, environment, days)
        _render_security_operating_snapshot(
            snapshot
        )
    if exception_slot is not None:
        loaded = (
            summary is not None
            and not getattr(summary, "empty", True)
            and _security_meta_matches(meta, _security_scope_meta(company, environment, days))
        )
        with exception_slot.container():
            _render_security_exception_strip(
                _security_exception_strip_rows(summary, exceptions, meta, company, environment, days),
                loaded=loaded,
            )

def _render_security_operability_fact_gate(company: str, environment: str, days: int) -> None:
    fact_meta_expected = _security_scope_meta(company, environment, days)
    fact_col, note_col = st.columns([1.3, 3.7])
    with fact_col:
        if st.button("Load Security Control Facts", key="security_operability_fact_load"):
            try:
                operability_sql = _security_operability_fact_sql(days, company, environment)
                st.session_state["security_operability_fact_sql"] = operability_sql
                st.session_state["security_operability_fact"] = run_query(
                    operability_sql,
                    ttl_key=f"security_operability_fact_{company}_{environment}_{days}",
                    tier="standard",
                    section="Security Posture",
                )
                st.session_state["security_operability_fact_meta"] = fact_meta_expected
                st.session_state.pop("security_operability_fact_error", None)
            except Exception as fact_exc:
                st.session_state["security_operability_fact"] = pd.DataFrame()
                st.session_state["security_operability_fact_error"] = format_snowflake_error(fact_exc)
    with note_col:
        st.caption(
            "Security control facts stay unloaded until you need blocker, closure, or telemetry detail."
        )

    operability_fact = st.session_state.get("security_operability_fact")
    if (
        operability_fact is not None
        and not _security_meta_matches(
            st.session_state.get("security_operability_fact_meta"),
            fact_meta_expected,
        )
    ):
        st.info("Loaded security control facts are stale for the active scope. Reload before acting.")
        return
    if operability_fact is not None and not operability_fact.empty:
        st.subheader("Security Control Summary")
        blocked_states = operability_fact["CONTROL_STATE"].astype(str).str.contains(
            "Blocked|Overdue|Required", case=False, na=False
        )
        render_shell_snapshot((
            ("Rows", f"{len(operability_fact):,}"),
            ("Blocked", f"{int(blocked_states.sum()):,}"),
            ("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
            ("Verified", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
        ))
        render_priority_dataframe(
            operability_fact,
            title="Security blockers",
            priority_columns=[
                "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "SEVERITY",
                "FINDING_TYPE", "ENTITY", "ENTITY_TYPE", "ENVIRONMENT",
                "EVENT_ROWS", "REVIEW_ROWS", "REVIEW_BLOCKER_ROWS",
                "TICKET_REQUIRED_ROWS", "REVIEW_BY_REQUIRED_ROWS",
                "CAPABILITY_PROOF_ROWS", "NO_DATABASE_CONTEXT_ROWS",
                "OPEN_ACTIONS", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION",
                "VERIFIED_CLOSURES", "OWNER_APPROVAL_GAP_ROWS", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "REVIEW_BLOCKER_ROWS"],
            ascending=[True, False, False, False],
            raw_label="All security control rows",
            height=320,
        )
        with st.expander("Security Control Status", expanded=False):
            render_shell_snapshot((
                ("Control summary", "Ready"),
                ("Escalation route", "Review"),
                ("Closure status", "Required"),
                ("Execution", "Runbook only"),
            ))
    elif st.session_state.get("security_operability_fact_error"):
        defer_source_note(
            "Security control summary is not available yet. Ask the DBA team to enable the fast blocker surface."
        )

def _render_security_exceptions_gate(company: str, environment: str, days: int) -> None:
    exceptions_loaded = "security_posture_exceptions" in st.session_state
    exceptions = st.session_state.get("security_posture_exceptions")
    if not exceptions_loaded:
        load_col, note_col = st.columns([1.2, 3.8])
        with load_col:
            if st.button("Load Security Exceptions", key="security_posture_load_exceptions"):
                session = None
                try:
                    session = get_session()
                    proof_sql = st.session_state.get("security_posture_proof_sql") or {}
                    exceptions_sql = str(proof_sql.get("exceptions") or "")
                    preferred_source = str(st.session_state.get("security_posture_source") or "")
                    if not exceptions_sql:
                        _, exceptions_sql = _build_security_mart_brief_sql(session, days, company)
                        preferred_source = "Fast security summary; MFA/sharing: account history"
                    source_kind = "live" if "live" in preferred_source.lower() else "mart"
                    st.session_state["security_posture_exceptions"] = run_query(
                        exceptions_sql,
                        ttl_key=f"security_posture_exceptions_{source_kind}_{company}_{environment}_{days}",
                        tier="standard",
                    )
                    st.session_state["security_posture_exception_source"] = preferred_source
                    st.session_state.pop("security_posture_exception_error", None)
                    proof_sql["exceptions"] = exceptions_sql
                    st.session_state["security_posture_proof_sql"] = proof_sql
                except Exception as exc:
                    try:
                        session = session or get_session()
                        _, exceptions_sql = _build_security_summary_sql(session, days, company)
                        st.session_state["security_posture_exceptions"] = run_query(
                            exceptions_sql,
                            ttl_key=f"security_posture_exceptions_live_{company}_{environment}_{days}",
                            tier="standard",
                        )
                        st.session_state["security_posture_exception_source"] = "Live fallback: SNOWFLAKE.ACCOUNT_USAGE"
                        st.session_state.pop("security_posture_exception_error", None)
                        proof_sql = st.session_state.get("security_posture_proof_sql") or {}
                        proof_sql["exceptions"] = exceptions_sql
                        st.session_state["security_posture_proof_sql"] = proof_sql
                        st.info(f"Security summary unavailable from the fast summary; used bounded live account history. {format_snowflake_error(exc)}")
                    except Exception as live_exc:
                        st.session_state.pop("security_posture_exceptions", None)
                        st.session_state["security_posture_exception_error"] = format_snowflake_error(live_exc)
        with note_col:
            st.caption("Security exceptions stay unloaded until you need user/IP, MFA, grant, or sharing detail rows.")
        if st.session_state.get("security_posture_exception_error"):
            st.warning(f"Unable to load security exceptions: {st.session_state['security_posture_exception_error']}")
        return

    if exceptions is not None and getattr(exceptions, "empty", True):
        st.success("No security exceptions crossed the loaded thresholds for this scope.")
    if st.session_state.get("security_posture_exception_source"):
        defer_source_note(str(st.session_state.get("security_posture_exception_source")))

def _build_security_brief_markdown(
    *,
    company: str,
    days: int,
    score: int,
    summary_row,
    exceptions: pd.DataFrame,
) -> str:
    failed_logins = safe_int(summary_row.get("FAILED_LOGINS", 0))
    failed_users = safe_int(summary_row.get("FAILED_USERS", 0))
    active_users = safe_int(summary_row.get("ACTIVE_USERS", 0))
    users_without_mfa = safe_int(summary_row.get("USERS_WITHOUT_MFA", 0))
    recent_grants = safe_int(summary_row.get("RECENT_GRANTS", 0))
    shared_databases = safe_int(summary_row.get("SHARED_DATABASES", 0))
    exception_lines = []
    if exceptions is not None and not exceptions.empty:
        for _, row in exceptions.head(10).iterrows():
            exception_lines.append(
                f"- {row.get('SEVERITY', 'Medium')}: {row.get('FINDING_TYPE', 'Security finding')} "
                f"for {row.get('ENTITY', 'Unknown')} ({safe_int(row.get('EVENT_COUNT', 0))} events)."
            )
    else:
        exception_lines.append("- No security exceptions crossed the configured thresholds.")
    lines = [
        f"# OVERWATCH Security Summary - {company}",
        "",
        f"Lookback window: {days} day(s).",
        f"Security state: {_security_rating(score)}.",
        "",
        "## Key Metrics",
        f"- Active users: {active_users:,}",
        f"- Failed logins: {failed_logins:,} across {failed_users:,} user(s)",
        f"- Users without MFA signal: {users_without_mfa:,}",
        f"- Recent active grants: {recent_grants:,}",
        f"- Shared/imported databases: {shared_databases:,}",
        "",
        "## Exceptions",
        *exception_lines,
        "",
        "## DBA Follow-Up",
        "- Validate failed-login spikes against IAM and network context.",
        "- Prioritize MFA gaps before lower-risk grant cleanup.",
        "- Review shared/imported databases with the data route and contract context.",
        "- Save material findings to the OVERWATCH Action Queue for status tracking.",
        "",
        "## Data Notes",
        "Company scope uses user/database naming where Snowflake does not expose direct company routing.",
    ]
    return "\n".join(lines)


def _refresh_security_summary(company: str, environment: str, days: int) -> None:
    _load_security_brief(
        days=days,
        company=company,
        environment=environment,
        allow_live_fallback=True,
        quiet=False,
    )


def render_security_overview(company: str, environment: str, days: int) -> None:
    summary = st.session_state.get("security_posture_summary")
    exceptions = st.session_state.get("security_posture_exceptions")
    meta = st.session_state.get("security_posture_meta", {})

    security_expected_meta = _security_scope_meta(company, environment, days)
    security_current = (
        summary is not None
        and not getattr(summary, "empty", True)
        and _security_meta_matches(meta, security_expected_meta)
    )
    if consume_section_autoload_request("Security Posture") and not security_current:
        defer_source_note("Security evidence remains behind the Decision Workspace evidence action.")

    summary_error = str(st.session_state.get("security_posture_summary_error", "") or "")
    if summary_error and not security_current:
        defer_source_note(f"Fast security summary unavailable: {summary_error}")

    refresh_security_summary = bool(st.session_state.pop("security_posture_load_evidence", False))
    if refresh_security_summary:
        _refresh_security_summary(company, environment, days)
        summary = st.session_state.get("security_posture_summary")
        exceptions = st.session_state.get("security_posture_exceptions")
        meta = st.session_state.get("security_posture_meta", {})
        security_current = (
            summary is not None
            and not getattr(summary, "empty", True)
            and _security_meta_matches(meta, _security_scope_meta(company, environment, days))
        )

    summary = st.session_state.get("security_posture_summary")
    exceptions = st.session_state.get("security_posture_exceptions")
    meta = st.session_state.get("security_posture_meta", {})
    if (
        summary is not None
        and not getattr(summary, "empty", True)
        and _security_meta_matches(meta, _security_scope_meta(company, environment, days))
    ):
        row = summary.iloc[0]
        failed_logins = safe_int(row.get("FAILED_LOGINS", 0))
        failed_users = safe_int(row.get("FAILED_USERS", 0))
        active_users = safe_int(row.get("ACTIVE_USERS", 0))
        users_without_mfa = safe_int(row.get("USERS_WITHOUT_MFA", 0))
        recent_grants = safe_int(row.get("RECENT_GRANTS", 0))
        shared_databases = safe_int(row.get("SHARED_DATABASES", 0))
        score = _security_score(
            failed_logins=failed_logins,
            failed_users=failed_users,
            users_without_mfa=users_without_mfa,
            active_users=active_users,
            recent_grants=recent_grants,
            shared_databases=shared_databases,
        )
        render_decision_evidence_panel(
            "Security Evidence",
            str(meta.get("loaded_at") or st.session_state.get("security_posture_source") or "Loaded security evidence"),
            (
                f"Security score {score}; {failed_logins:,} failed logins, "
                f"{users_without_mfa:,} MFA gap(s), {recent_grants:,} recent grant(s), "
                f"{shared_databases:,} shared database signal(s)."
            ),
            (
                ("Failed logins", f"{failed_logins:,}"),
                ("MFA gaps", f"{users_without_mfa:,}"),
                ("Risky grants", f"{recent_grants:,}"),
                ("Shared DBs", f"{shared_databases:,}"),
            ),
            rows=exceptions if exceptions is not None and not exceptions.empty else summary,
            source_note=str(st.session_state.get("security_posture_source") or meta.get("source") or "Security evidence"),
        )
        render_data_freshness(
            meta,
            source=st.session_state.get("security_posture_source", "Security evidence"),
            target_minutes=60,
            delayed_note="Security evidence uses fast rows first; row-level proof stays behind explicit controls.",
        )
        render_add_to_case_button(
            make_case_evidence(
                section="Security Monitoring",
                workflow="Security Overview",
                scope=f"{company} / {environment} / {int(days)} days",
                freshness=str(meta.get("loaded_at") or "Loaded security summary"),
                source=str(meta.get("source") or st.session_state.get("security_posture_source") or "Security summary"),
                summary=(
                    f"Security score {score}; {failed_logins:,} failed logins, "
                    f"{users_without_mfa:,} users without MFA, {recent_grants:,} recent grants, "
                    f"{shared_databases:,} shared databases."
                ),
                next_action="Review failed login, grant, and sharing exposure lanes before escalation.",
                evidence_rows_preview=exceptions if exceptions is not None and not exceptions.empty else summary,
            ),
            key="security_posture_add_to_case",
        )
        if score < 85:
            st.warning("Access & Security needs DBA review before this can be called clean.")
        elif score < 95:
            st.info("Access & Security is usable, but there are findings worth reviewing.")
        else:
            st.success("Access & Security is strong for the selected window.")
        _render_security_watch_floor(score, exceptions if exceptions is not None else pd.DataFrame(), row)
        defer_source_note(meta.get("source", "SNOWFLAKE.ACCOUNT_USAGE"))
        st.divider()
        with st.expander("Load Secondary Security Details", expanded=False):
            _render_security_operability_fact_gate(company, environment, days)
            _render_security_exceptions_gate(company, environment, days)
        exceptions = st.session_state.get("security_posture_exceptions")
        if exceptions is not None and not exceptions.empty:
            st.subheader("Security Exceptions")
            priority_exceptions = _security_priority_view(exceptions)
            render_priority_dataframe(
                priority_exceptions,
                title="Security exceptions to validate first",
                priority_columns=[
                    "SEVERITY", "FINDING_TYPE", "ENTITY", "EVENT_COUNT",
                    "DISTINCT_SOURCES", "DATABASE_NAME", "LAST_SEEN", "ENTITY_TYPE",
                    "NEXT_WORKFLOW", "NEXT_ACTION",
                ],
                sort_by=["SEVERITY", "EVENT_COUNT", "LAST_SEEN"],
                ascending=[True, False, False],
                raw_label="All security exceptions",
            )

            queue_col, proof_col, _spacer_col = st.columns([1.25, 1.25, 2.5])
            with queue_col:
                if st.button("Save Security Exceptions to Action Queue", key="security_posture_queue"):
                    _queue_security_exceptions(get_session(), exceptions)
            proof_tables_visible = _security_proof_tables_visible(company, environment, days)
            with proof_col:
                if proof_tables_visible:
                    if st.button("Hide Security Detail Tables", key="security_posture_hide_proof_tables"):
                        _hide_security_proof_tables()
                        st.rerun()
                elif st.button("Load Security Detail Tables", key="security_posture_load_proof_tables"):
                    _show_security_proof_tables(company, environment, days)
                    st.rerun()
            if not proof_tables_visible:
                st.caption("Security detail tables stay unloaded until row-level user, grant, or sharing context is needed.")
            else:
                access_review = _build_security_access_review(exceptions, environment)
                security_board = _security_control_board(
                    access_review,
                    closure=st.session_state.get("security_action_closure"),
                    trend=st.session_state.get("security_access_review_trend"),
                    environment=environment,
                )
                if not security_board.empty:
                    st.subheader("Security Control Detail")
                    blocked_states = security_board["CONTROL_STATE"].astype(str).str.contains("Blocked|Overdue|Required", case=False, na=False)
                    render_shell_snapshot((
                        ("Control Rows", f"{len(security_board):,}"),
                        ("Blocked", f"{int(blocked_states.sum()):,}"),
                        ("Overdue", f"{int(security_board.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
                        ("Verified", f"{int(security_board.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
                    ))
                    render_priority_dataframe(
                        security_board,
                        title="Security issues blocking DBA closure",
                        priority_columns=[
                            "CONTROL_STATE", "SEVERITY", "FINDING_TYPE", "ENTITY",
                            "ENVIRONMENT", "DATABASE_CONTEXT", "OWNER", "APPROVER",
                            "REVIEW_READINESS", "REVIEW_BLOCKERS", "ACCESS_TICKET_ID",
                            "REVIEW_BY_DATE", "IAM_APPROVAL_STATE", "REVIEW_SLA_HOURS",
                            "OPEN_ACTIONS", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION",
                            "VERIFIED_CLOSURES", "CONTROL_BLOCKERS", "NEXT_CONTROL_ACTION",
                        ],
                        sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                        ascending=[True, False, False, False],
                        raw_label="All security control rows",
                        height=340,
                    )
                render_priority_dataframe(
                    access_review,
                    title="Security access-review status before queueing",
                    priority_columns=[
                        "SEVERITY", "REVIEW_READINESS", "ACCESS_REVIEW_STATE", "FINDING_TYPE", "ENTITY",
                        "OWNER", "ESCALATION_TARGET", "APPROVER", "ROLE_CAPABILITY_STATE",
                        "ACCESS_TICKET_ID", "REVIEW_BY_DATE", "IAM_APPROVAL_STATE",
                        "REVIEW_BLOCKERS", "REVIEW_SLA_HOURS", "TICKET_REQUIRED", "REVIEW_BY_REQUIRED", "DATABASE_CONTEXT",
                        "DATABASE_NAME", "ENVIRONMENT", "SCOPE_CONFIDENCE", "SCOPE_EVIDENCE",
                        "PROOF_REQUIRED", "NEXT_CONTROL_ACTION",
                    ],
                    sort_by=["REVIEW_RANK", "SEVERITY", "ENTITY"],
                    ascending=[True, True, True],
                    raw_label="Full security access review",
                )

                if st.button("Save Access Review Snapshot", key="security_posture_access_review_snapshot"):
                    _save_security_access_review_snapshot(
                        get_session(),
                        access_review,
                        company=company,
                        environment=environment,
                        source=meta.get("source", ""),
                    )

                with st.expander("Security Access Review Trend", expanded=False):
                    trend_days = day_window_selectbox(
                        "Access review history lookback",
                        key="security_access_review_trend_days",
                        default=30,
                    )
                    if st.button("Load Access Review Trend", key="security_access_review_trend_load"):
                        try:
                            trend_sql = _security_access_review_history_sql(trend_days, company, environment)
                            st.session_state["security_access_review_trend_sql"] = trend_sql
                            st.session_state["security_access_review_trend"] = run_query(
                                trend_sql,
                                ttl_key=f"security_access_review_trend_{company}_{environment}_{trend_days}",
                                tier="standard",
                                section="Security Posture",
                            )
                            st.session_state["security_access_review_trend_meta"] = _security_scope_meta(
                                company, environment, trend_days
                            )
                        except Exception as exc:
                            st.session_state["security_access_review_trend"] = pd.DataFrame()
                            st.error(f"Could not load security access-review history: {format_snowflake_error(exc)}")
                            st.info("Security access review history is not available in this environment yet. Ask the DBA team to enable it, then reload.")
                    trend = st.session_state.get("security_access_review_trend")
                    if (
                        trend is not None
                        and not _security_meta_matches(
                            st.session_state.get("security_access_review_trend_meta"),
                            _security_scope_meta(company, environment, trend_days),
                        )
                    ):
                        st.info("Loaded security access-review trend is stale for the active scope. Reload before acting.")
                    elif trend is not None and not trend.empty:
                        render_priority_dataframe(
                            trend,
                            title="Security review findings still needing DBA status",
                            priority_columns=[
                                "FINDING_TYPE", "SEVERITY", "OWNER", "ESCALATION_TARGET",
                                "REVIEW_ROWS", "TOTAL_EVENTS", "TICKET_REQUIRED_ROWS",
                                "REVIEW_BY_REQUIRED_ROWS", "CAPABILITY_PROOF_ROWS",
                                "REVIEW_BLOCKER_ROWS", "VERIFIED_REVIEW_ROWS",
                                "NO_DATABASE_CONTEXT_ROWS", "LAST_ACCESS_REVIEW_STATE",
                                "LAST_REVIEW_READINESS", "LAST_CONTROL_READINESS",
                                "LAST_ROLE_CAPABILITY_STATE", "NEXT_CONTROL_ACTION",
                            ],
                            sort_by=["REVIEW_BLOCKER_ROWS", "TICKET_REQUIRED_ROWS", "CAPABILITY_PROOF_ROWS", "TOTAL_EVENTS"],
                            ascending=[False, False, False, False],
                            raw_label="Access review history",
                        )
                        with st.expander("Access Review Status", expanded=False):
                            render_shell_snapshot((
                                ("Trend status", "Ready"),
                                ("Owner review", "Required"),
                                ("Closure status", "Required"),
                                ("Execution", "Runbook only"),
                            ))
                    elif trend is not None:
                        st.info("No saved security access-review snapshots found for the selected scope.")
                with st.expander("Security Action Closure Analytics", expanded=False):
                    defer_source_note(
                        "Uses Access & Security action-queue rows to show open, overdue, telemetry-pending, "
                        "or recently closed security work."
                    )
                    closure_days = day_window_selectbox(
                        "Security closure window",
                        key="security_action_closure_days",
                        default=30,
                    )
                    if st.button("Load Security Closure Analytics", key="security_action_closure_load"):
                        try:
                            closure_sql = _security_action_queue_closure_sql(closure_days, company, environment)
                            st.session_state["security_action_closure_sql"] = closure_sql
                            st.session_state["security_action_closure"] = run_query(
                                closure_sql,
                                ttl_key=f"security_action_closure_{company}_{environment}_{closure_days}",
                                tier="standard",
                                section="Security Posture",
                            )
                            st.session_state["security_action_closure_meta"] = _security_scope_meta(
                                company, environment, closure_days
                            )
                        except Exception as exc:
                            st.session_state["security_action_closure"] = pd.DataFrame()
                            st.warning(f"Security closure analytics unavailable: {format_snowflake_error(exc)}")
                    closure = st.session_state.get("security_action_closure")
                    if (
                        closure is not None
                        and not _security_meta_matches(
                            st.session_state.get("security_action_closure_meta"),
                            _security_scope_meta(company, environment, closure_days),
                        )
                    ):
                        st.info("Loaded security closure analytics are stale for the active scope. Reload before acting.")
                    elif closure is not None and not closure.empty:
                        render_priority_dataframe(
                            closure,
                            title="Security closure status gaps",
                            priority_columns=[
                                "CATEGORY", "ENTITY_TYPE", "ENTITY", "CLOSURE_READINESS",
                                "OWNER", "APPROVER", "TOTAL_ACTIONS", "OPEN_ACTIONS",
                                "OVERDUE_OPEN", "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                                "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                                "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                                "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                            ],
                            sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                            ascending=[True, False, False, False],
                            raw_label="All security closure rows",
                            height=300,
                        )
                        with st.expander("Security Closure Status", expanded=False):
                            render_shell_snapshot((
                                ("Closure status", "Ready"),
                                ("Telemetry", "Review"),
                                ("Telemetry", "Required"),
                                ("Execution", "Runbook only"),
                            ))
                    elif closure is not None:
                        st.info("No Access & Security action-queue rows found for the selected scope.")
        elif exceptions is not None:
            st.success("No security exceptions crossed the default thresholds.")
        brief_md = _build_security_brief_markdown(
            company=company,
            days=days,
            score=score,
            summary_row=row,
            exceptions=exceptions,
        )
        dl1, dl2 = st.columns([1, 3])
        with dl1:
            download_text(
                brief_md,
                f"overwatch_security_brief_{company.lower()}.md",
                label="Download Security Summary",
                mime="text/markdown",
                key="security_posture_download",
            )
        with dl2:
            with st.expander("Data Health", expanded=False):
                defer_source_note("Use reviewed source telemetry when an auditor or security partner asks where a number came from.")
                render_shell_snapshot((
                    ("Summary telemetry", "Ready after refresh"),
                    ("Exception telemetry", "Ready after refresh"),
                    ("Route review", "Required"),
                    ("Execution", "Runbook only"),
                ))
        if st.session_state.get("exceptions_only_mode"):
            _render_advanced_security_evidence(company, environment)
            st.stop()
    elif summary is not None and not summary.empty:
        st.info("Loaded security summary is stale for the active scope. Load current security evidence before acting.")

    if should_render_daily_diagnostics(
        "Security Monitoring",
        SECURITY_OVERVIEW_WORKFLOW,
        "READY" if security_current else "UNINITIALIZED",
    ):
        _render_advanced_security_evidence(company, environment)

__all__ = [
    '_render_security_watch_floor',
    '_security_exception_strip_rows',
    '_render_security_exception_strip',
    '_security_action_brief',
    '_render_security_action_brief',
    '_security_operating_snapshot',
    '_render_security_operating_snapshot',
    '_render_security_overview_entry',
    '_security_command_lanes',
    '_queue_security_workflow',
    '_security_brief_workflow_rows',
    '_render_security_brief_launchpad',
    '_paint_security_brief_chrome',
    '_render_security_operability_fact_gate',
    '_render_security_exceptions_gate',
    '_build_security_brief_markdown',
    '_refresh_security_summary',
    'render_security_overview',
]
