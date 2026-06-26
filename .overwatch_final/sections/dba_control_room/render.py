"""Streamlit render entrypoint for the DBA Control Room page."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import streamlit as st
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_decision_evidence_panel,
    render_data_freshness,
    render_content_header,
    render_primary_section_tabs,
    render_section_breadcrumb,
    render_shell_snapshot,
    with_loaded_at,
)
from sections.section_command_brief import autoload_section_command_brief
from sections.section_command_rendering import render_section_command_brief
from sections.decision_workspace_controls import (
    make_decision_refresh_action,
    make_evidence_action,
    should_render_daily_diagnostics,
)
from sections.decision_workspace_scope import active_decision_window_days
from sections.decision_workspace_state import section_state_from_brief
from utils.evidence_mode import (
    TRIAGE_MODE_ALL_EVIDENCE,
    TRIAGE_MODE_INVESTIGATE,
    TRIAGE_MODE_TRIAGE,
    current_evidence_mode,
    evidence_mode_is_all_evidence,
    evidence_mode_is_investigation,
)
from utils.primitives import (
    safe_float,
    safe_int,
)
from utils.downloads import (
    download_text,
)
from utils.section_guidance import (
    defer_section_note,
)
from .types import (
    ACTION_QUEUE_WORKFLOW,
    CHANGE_WATCH_WORKFLOW,
    CONTROL_ROOM_ADMIN_WORKFLOW,
    COST_WATCH_WORKFLOW,
    DBA_CONTROL_ROOM_DETAIL_PANES,
    DBA_CONTROL_ROOM_PANES,
    DBA_CONTROL_ROOM_PANE_DETAILS,
    DBA_CONTROL_ROOM_PANE_LABELS,
    FAILURE_TRIAGE_WORKFLOW,
    MORNING_COCKPIT_WORKFLOW,
    PERFORMANCE_WATCH_WORKFLOW,
    _clear_dba_control_room_derived_state,
    _empty_df,
    _jump,
    freshness_note,
    get_active_environment,
    get_credit_price,
    metric_confidence_label,
    normalize_dba_control_room_pane,
    pd,
    render_operator_briefing,
)
from .health import (
    _build_auto_release_readiness_gate,
    _control_room_snapshot_to_data,
    _dba_control_meta_matches,
    _dba_control_ops_scope_key,
    _dba_control_scope_meta,
    _dba_control_source_health_rows,
    _dba_snapshot_scope_compatible,
    _render_control_room_source_health,
)
from .queue import (
    _build_command_queue,
    _command_queue_closure_readiness,
    _dba_operations_priority_index,
    _dba_section_operability_board,
    _priority_exceptions,
    _render_command_queue_control,
    _render_dba_command_intelligence_contract,
    _render_loaded_advisor_signals,
    _render_operations_priority_index,
)
from .incidents import (
    _build_dba_escalation_packet_markdown,
    _build_dba_incident_markdown,
    _build_dba_operator_runbook_markdown,
    _dba_escalation_packet,
    _dba_incident_board,
    _dba_operator_runbook,
    _render_dba_action_brief,
    _render_dba_escalation_packet,
    _render_dba_operator_runbook,
    _render_incident_board_panel,
    _render_watch_floor,
)
from .data import (
    _build_release_compare_report,
    _load_control_room,
    _load_release_compare,
    _severity_rows,
)
from .handoff import (
    _build_dba_morning_brief_markdown,
    _build_dba_shift_handoff_markdown,
    _dba_handoff_rows,
    _dba_morning_brief_rows,
    _dba_workload_morning_lanes,
    _render_dba_morning_brief,
    _render_shift_handoff_panel,
)
from .types import (
    credits_to_dollars,
    download_csv,
    format_credits,
    format_snowflake_error,
    get_active_company,
    get_session,
    load_app_observability_detail,
    load_change_correlation_detail,
    load_change_event_detail,
    load_closed_loop_execution_plan_detail,
    load_closed_loop_verification_detail,
    load_closed_loop_workflow_detail,
    load_command_center_evidence_detail,
    load_command_center_finding_detail,
    load_command_center_recommendation_detail,
    load_data_trust_detail,
    load_executive_scorecard_detail,
    load_forecast_detail,
    load_latest_control_room_mart,
    load_production_validation_detail,
    render_load_status,
    render_priority_dataframe,
)


def _render_dba_control_room_workflow_selector() -> str:
    """Render DBA workflow navigation without hiding the selected deep-link target."""
    selected = render_primary_section_tabs(
        label="DBA Control Room primary navigation",
        options=DBA_CONTROL_ROOM_PANES,
        active_value=st.session_state.get("dba_control_room_active_view", MORNING_COCKPIT_WORKFLOW),
        key="dba_control_room_active_view",
        format_func=lambda value: DBA_CONTROL_ROOM_PANE_LABELS.get(str(value), str(value)),
    )
    selected = normalize_dba_control_room_pane(selected)
    if selected != MORNING_COCKPIT_WORKFLOW:
        render_content_header(
            DBA_CONTROL_ROOM_PANE_LABELS.get(selected, selected),
            DBA_CONTROL_ROOM_PANE_DETAILS.get(selected, "DBA evidence stays behind explicit load actions."),
        )
    return selected


def _render_consolidated_service_posture() -> None:
    """Render legacy Service Health inside the DBA Control Room workspace."""
    from sections import service_health

    service_health.render()


def _render_enterprise_diagnostics_gate(company: str, environment: str) -> None:
    """Expose enterprise trust/app detail only when the operator asks for it."""
    st.markdown("**Production Trust Diagnostics**")
    st.caption("Detail diagnostics read OVERWATCH marts and logs only. They stay unloaded until a DBA needs proof.")
    c1, c2 = st.columns([1.2, 1.2])
    with c1:
        if st.button("Load Data Trust Diagnostics", key="dba_enterprise_load_data_trust", width="stretch"):
            st.session_state["dba_enterprise_data_trust_detail"] = load_data_trust_detail(
                company,
                environment,
                days=35,
            )
            st.session_state["dba_enterprise_data_trust_scope"] = (company, environment)
    with c2:
        if st.button("Load App Observability Detail", key="dba_enterprise_load_app_observability", width="stretch"):
            st.session_state["dba_enterprise_app_observability_detail"] = load_app_observability_detail(
                company,
                environment,
                days=7,
            )
            st.session_state["dba_enterprise_app_observability_scope"] = (company, environment)

    trust = st.session_state.get("dba_enterprise_data_trust_detail")
    if (
        isinstance(trust, pd.DataFrame)
        and st.session_state.get("dba_enterprise_data_trust_scope") == (company, environment)
    ):
        if trust.empty:
            st.info("No data trust diagnostics are available for this scope yet.")
        else:
            render_shell_snapshot((
                ("Sources", f"{len(trust):,}"),
                ("Stale/Missing", f"{safe_int((~trust.get('STATUS', pd.Series(dtype=str)).fillna('').astype(str).eq('Ready')).sum()):,}"),
                ("Confidence", str(trust.get("CONFIDENCE", pd.Series(["fallback"])).fillna("fallback").astype(str).iloc[0])),
            ))
            st.dataframe(
                trust[[
                    column for column in [
                        "SOURCE_NAME", "SOURCE_OBJECT", "STATUS", "CONFIDENCE",
                        "LATEST_SOURCE_TS", "AGE_MINUTES", "TARGET_FRESHNESS_MIN",
                        "ROUTE", "BUSINESS_IMPACT", "NEXT_ACTION",
                    ]
                    if column in trust.columns
                ]],
                width="stretch",
                hide_index=True,
            )

    app_detail = st.session_state.get("dba_enterprise_app_observability_detail")
    if (
        isinstance(app_detail, pd.DataFrame)
        and st.session_state.get("dba_enterprise_app_observability_scope") == (company, environment)
    ):
        if app_detail.empty:
            st.info("No app observability detail is available for this scope yet.")
        else:
            failures = safe_int(pd.to_numeric(app_detail.get("QUERY_FAILURE_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
            slow = safe_int((pd.to_numeric(app_detail.get("RENDER_MS", pd.Series(dtype=float)), errors="coerce").fillna(0) >= 5000).sum())
            render_shell_snapshot((
                ("Events", f"{len(app_detail):,}"),
                ("Failures", f"{failures:,}"),
                ("Slow Events", f"{slow:,}"),
            ))
            st.dataframe(
                app_detail[[
                    column for column in [
                        "EVENT_TS", "SECTION_NAME", "EVENT_TYPE", "RENDER_MS",
                        "QUERY_COUNT", "QUERY_FAILURE_COUNT", "OVERWATCH_COST_USD",
                        "VALIDATION_STATUS", "DEPLOYMENT_VERSION", "LAST_DEPLOYMENT_TS",
                        "DETAIL",
                    ]
                    if column in app_detail.columns
                ]],
                width="stretch",
                hide_index=True,
            )


def _render_production_readiness_gate(company: str, environment: str) -> None:
    """Expose Phase 2A production readiness proof only behind Load buttons."""
    st.markdown("**Production Readiness Validation**")
    st.caption(
        "These panels read readiness marts and validation status rows. They do not probe live Snowflake during first paint."
    )
    panels = (
        ("Load Production Validation Checklist", "Production Validation Checklist", "", "dba_prod_load_checklist"),
        ("Load Role Readiness", "Role Readiness", "Role Readiness", "dba_prod_load_roles"),
        ("Load Privilege Readiness", "Privilege Readiness", "Privilege Readiness", "dba_prod_load_privileges"),
        ("Load Refresh Health", "Refresh Health", "Refresh Health", "dba_prod_load_refresh"),
    )
    cols = st.columns(4)
    for idx, (button_label, label, domain, key) in enumerate(panels):
        with cols[idx]:
            if st.button(button_label, key=key, width="stretch"):
                st.session_state["dba_production_readiness_detail"] = load_production_validation_detail(
                    company,
                    environment,
                    domain=domain,
                    days=35,
                )
                st.session_state["dba_production_readiness_scope"] = (company, environment, domain)
                st.session_state["dba_production_readiness_label"] = label

    detail = st.session_state.get("dba_production_readiness_detail")
    scope = st.session_state.get("dba_production_readiness_scope")
    label = str(st.session_state.get("dba_production_readiness_label") or "Production Validation Checklist")
    expected_domains = {"", "Role Readiness", "Privilege Readiness", "Refresh Health"}
    if (
        isinstance(detail, pd.DataFrame)
        and isinstance(scope, tuple)
        and len(scope) == 3
        and scope[0] == company
        and scope[1] == environment
        and scope[2] in expected_domains
    ):
        st.markdown(f"**{label}**")
        if detail.empty:
            st.info("No production readiness rows are available for this scope yet.")
            return
        blocked = safe_int(detail.get("VALIDATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str).eq("Blocked").sum())
        review = safe_int(detail.get("VALIDATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str).eq("Review").sum())
        render_shell_snapshot((
            ("Rows", f"{len(detail):,}"),
            ("Blocked", f"{blocked:,}"),
            ("Review", f"{review:,}"),
            ("Confidence", str(detail.get("CONFIDENCE", pd.Series(["fallback"])).fillna("fallback").astype(str).iloc[0])),
        ))
        st.dataframe(
            detail[[
                column for column in [
                    "CHECK_DOMAIN", "CHECK_NAME", "VALIDATION_STATUS", "RISK_LEVEL",
                    "VALUE", "VALUE_DETAIL", "SOURCE_OBJECT", "FRESHNESS_MINUTES",
                    "ROUTE", "RUNBOOK_STEP", "CONFIDENCE",
                ]
                if column in detail.columns
            ]],
            width="stretch",
            hide_index=True,
        )


def _render_executive_scorecard_driver_gate(company: str, environment: str) -> None:
    """Expose Phase 2B score drivers only behind an explicit Load action."""
    st.markdown("**Executive Scorecard Drivers**")
    st.caption(
        "Loads score history and top drivers from OVERWATCH_EXECUTIVE_SCORECARD_HISTORY. "
        "No live ACCOUNT_USAGE probe is performed."
    )
    if st.button("Load Executive Scorecard Drivers", key="dba_load_executive_scorecard_drivers", width="stretch"):
        st.session_state["dba_executive_scorecard_detail"] = load_executive_scorecard_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["dba_executive_scorecard_scope"] = (company, environment)

    detail = st.session_state.get("dba_executive_scorecard_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("dba_executive_scorecard_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No Executive Scorecard driver rows are available for this scope yet.")
            return
        red_yellow = safe_int(detail.get("STATUS", pd.Series(dtype=str)).fillna("").astype(str).isin(["Red", "Yellow"]).sum())
        owner_gaps = safe_int(pd.to_numeric(detail.get("OWNER_GAP", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        value_risk = safe_float(pd.to_numeric(detail.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        render_shell_snapshot((
            ("Rows", f"{len(detail):,}"),
            ("Red/Yellow", f"{red_yellow:,}"),
            ("Owner Gaps", f"{owner_gaps:,}"),
            ("Value/Risk", f"${value_risk:,.0f}"),
        ))
        render_priority_dataframe(
            detail,
            title="Executive score drivers and owner routes",
            priority_columns=[
                "SCORE_NAME", "CURRENT_SCORE", "STATUS", "TREND", "RISK_LEVEL",
                "TOP_DRIVER", "RECOMMENDED_ACTION", "OWNER_ROUTE", "OWNER_GAP",
                "VALUE_AT_RISK_USD", "CONFIDENCE", "LAST_REFRESHED_TS",
            ],
            sort_by=["STATUS", "CURRENT_SCORE", "SNAPSHOT_TS"],
            ascending=[True, True, False],
            raw_label="All executive scorecard driver rows",
            height=320,
            max_rows=12,
        )


def _render_forecast_exception_gate(company: str, environment: str) -> None:
    """Expose Phase 2C forecast exceptions only behind an explicit Load action."""
    st.markdown("**Forecast Exceptions**")
    st.caption(
        "Loads forecasting history from OVERWATCH_FORECAST_HISTORY. "
        "Forecasts are heuristic estimates and do not execute remediation."
    )
    if st.button("Load Forecast Exceptions", key="dba_load_forecast_exceptions", width="stretch"):
        st.session_state["dba_forecast_exception_detail"] = load_forecast_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["dba_forecast_exception_scope"] = (company, environment)

    detail = st.session_state.get("dba_forecast_exception_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("dba_forecast_exception_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No forecast exception rows are available for this scope yet.")
            return
        trend = detail.get("TREND_DIRECTION", pd.Series(dtype=str)).fillna("").astype(str)
        confidence = detail.get("CONFIDENCE", pd.Series(dtype=str)).fillna("").astype(str)
        risk = pd.to_numeric(detail.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        render_shell_snapshot((
            ("Rows", f"{len(detail):,}"),
            ("Trending Up", f"{safe_int(trend.eq('Up').sum()):,}"),
            ("Low Confidence", f"{safe_int(confidence.eq('Low').sum()):,}"),
            ("Value/Risk", f"${safe_float(risk.sum()):,.0f}"),
        ))
        render_priority_dataframe(
            detail,
            title="Forecast exceptions and driver history",
            priority_columns=[
                "FORECAST_NAME", "FORECAST_DOMAIN", "FORECAST_VALUE", "VALUE_UNIT",
                "CURRENT_ACTUAL", "PRIOR_PERIOD_VALUE", "TREND_DIRECTION",
                "CONFIDENCE", "MAIN_DRIVER", "RECOMMENDED_ACTION", "OWNER_ROUTE",
                "VALUE_AT_RISK_USD", "SOURCE_OBJECTS", "LAST_REFRESHED_TS",
            ],
            sort_by=["SNAPSHOT_TS", "FORECAST_KEY"],
            ascending=[False, True],
            raw_label="All forecast exception rows",
            height=300,
            max_rows=12,
        )


def _render_change_intelligence_gate(company: str, environment: str) -> None:
    """Expose Phase 2D high-risk changes and possible correlations behind Load."""
    st.markdown("**Change Intelligence**")
    st.caption(
        "Loads normalized change events and possible correlations from OVERWATCH change marts. "
        "Possible correlations are not root-cause claims and no remediation is executed."
    )
    if st.button("Load Change Intelligence", key="dba_load_change_intelligence", width="stretch"):
        st.session_state["dba_change_event_detail"] = load_change_event_detail(
            company,
            environment,
            risk_levels=("Critical", "High"),
            days=180,
        )
        st.session_state["dba_change_correlation_detail"] = load_change_correlation_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["dba_change_intelligence_scope"] = (company, environment)

    scope_ok = st.session_state.get("dba_change_intelligence_scope") == (company, environment)
    events = st.session_state.get("dba_change_event_detail")
    correlations = st.session_state.get("dba_change_correlation_detail")
    if not scope_ok:
        return
    if isinstance(events, pd.DataFrame):
        if events.empty:
            st.info("No high-risk change events are available for this scope yet.")
        else:
            risk = events.get("RISK_LEVEL", pd.Series(dtype=str)).fillna("").astype(str)
            owner_gaps = pd.to_numeric(events.get("OWNER_GAP", pd.Series(dtype=float)), errors="coerce").fillna(0)
            render_shell_snapshot((
                ("Events", f"{len(events):,}"),
                ("Critical", f"{safe_int(risk.eq('Critical').sum()):,}"),
                ("High", f"{safe_int(risk.eq('High').sum()):,}"),
                ("Owner Gaps", f"{safe_int(owner_gaps.sum()):,}"),
            ))
            render_priority_dataframe(
                events,
                title="High-risk recent changes",
                priority_columns=[
                    "CHANGE_TS", "CHANGE_TYPE", "OBJECT_TYPE", "OBJECT_NAME",
                    "CHANGED_BY", "RISK_LEVEL", "BUSINESS_IMPACT", "OWNER_ROUTE",
                    "RELATED_ALERT_COUNT", "RELATED_INCIDENTS", "CONFIDENCE",
                    "LAST_REFRESHED_TS",
                ],
                sort_by=["CHANGE_TS"],
                ascending=False,
                raw_label="All high-risk change events",
                height=300,
                max_rows=12,
            )
    if isinstance(correlations, pd.DataFrame):
        if correlations.empty:
            st.info("No possible change correlations are available for this scope yet.")
        else:
            render_priority_dataframe(
                correlations,
                title="Possible change correlations",
                priority_columns=[
                    "RELATED_TS", "CHANGE_TS", "CHANGE_TYPE", "OBJECT_NAME",
                    "CORRELATION_TYPE", "RELATED_SIGNAL", "RELATED_ENTITY",
                    "CORRELATION_STRENGTH", "CORRELATION_LABEL", "EVIDENCE",
                    "OWNER_ROUTE", "CONFIDENCE",
                ],
                sort_by=["RELATED_TS", "CHANGE_TS"],
                ascending=[False, False],
                raw_label="All possible change correlations",
                height=300,
                max_rows=12,
            )


def _render_closed_loop_operations_gate(company: str, environment: str) -> None:
    """Expose Phase 2E action, verification, and review plans behind Load."""
    st.markdown("**Closed Loop Operations**")
    st.caption(
        "Loads action workflow, review plans, and verification evidence from OVERWATCH closed-loop marts. "
        "Dangerous SQL is displayed for review only and is not executed in the app."
    )
    if st.button("Load Closed-Loop Actions", key="dba_load_closed_loop_operations", width="stretch"):
        st.session_state["dba_closed_loop_workflow_detail"] = load_closed_loop_workflow_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["dba_closed_loop_execution_plan_detail"] = load_closed_loop_execution_plan_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["dba_closed_loop_verification_detail"] = load_closed_loop_verification_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["dba_closed_loop_scope"] = (company, environment)

    if st.session_state.get("dba_closed_loop_scope") != (company, environment):
        return

    workflows = st.session_state.get("dba_closed_loop_workflow_detail")
    execution_plans = st.session_state.get("dba_closed_loop_execution_plan_detail")
    verification = st.session_state.get("dba_closed_loop_verification_detail")
    if isinstance(workflows, pd.DataFrame):
        if workflows.empty:
            st.info("No closed-loop action workflows are available for this scope yet.")
        else:
            approval = workflows.get("APPROVAL_STATUS", pd.Series(dtype=str)).fillna("").astype(str)
            verification_status = workflows.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str)
            verified = pd.to_numeric(
                workflows.get("ACTUAL_VERIFIED_SAVINGS_USD", pd.Series(dtype=float)),
                errors="coerce",
            ).fillna(0)
            need_approval = safe_int((~approval.isin(["Approved", "Not Required"])).sum())
            needs_verification = safe_int((~verification_status.isin(["Verified", "Closed"])).sum())
            render_shell_snapshot((
                ("Actions", f"{len(workflows):,}"),
                ("Need Approval", f"{need_approval:,}"),
                ("Verify", f"{needs_verification:,}"),
                ("Verified Value", f"${safe_float(verified.sum()):,.0f}"),
            ))
            render_priority_dataframe(
                workflows,
                title="Closed-loop action queue",
                priority_columns=[
                    "ACTION_DOMAIN", "FINDING", "RISK_LEVEL", "OWNER_ROUTE",
                    "BUSINESS_IMPACT", "APPROVAL_STATUS", "EXECUTION_MODE",
                    "VERIFICATION_STATUS", "EXPECTED_SAVINGS_USD",
                    "ACTUAL_VERIFIED_SAVINGS_USD", "RECOMMENDED_ACTION",
                    "LAST_REFRESHED_TS",
                ],
                sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
                ascending=[True, False],
                raw_label="All closed-loop workflow rows",
                height=320,
                max_rows=12,
            )
    if isinstance(execution_plans, pd.DataFrame):
        if execution_plans.empty:
            st.info("No reviewable execution plans are available for this scope yet.")
        else:
            st.caption("Execution plans are review-gated. OVERWATCH does not run ALTER/CREATE/DROP/GRANT/REVOKE/SUSPEND/RESUME actions from this panel.")
            render_priority_dataframe(
                execution_plans,
                title="Review-gated SQL and action plans",
                priority_columns=[
                    "ACTION_DOMAIN", "EXECUTION_MODE", "EXECUTION_STATUS",
                    "DANGEROUS_ACTION_FLAG", "EXECUTION_ALLOWED_IN_APP",
                    "REVIEW_SQL_TEXT", "REVIEW_ACTION_TEXT", "ROLLBACK_GUIDANCE",
                    "VERIFICATION_STEPS", "LAST_REFRESHED_TS",
                ],
                sort_by=["DANGEROUS_ACTION_FLAG", "LAST_REFRESHED_TS"],
                ascending=[False, False],
                raw_label="All closed-loop execution plan rows",
                height=300,
                max_rows=10,
            )
    if isinstance(verification, pd.DataFrame):
        if verification.empty:
            st.info("No verification rows are available for this scope yet.")
        else:
            render_priority_dataframe(
                verification,
                title="Verification and measured value queue",
                priority_columns=[
                    "ACTION_DOMAIN", "VERIFICATION_STATUS", "EXPECTED_SAVINGS_USD",
                    "ACTUAL_VERIFIED_SAVINGS_USD", "VERIFICATION_WINDOW_START",
                    "VERIFICATION_WINDOW_END", "VERIFICATION_STEPS", "VERIFIED_BY",
                    "VERIFIED_AT", "EVIDENCE", "LAST_REFRESHED_TS",
                ],
                sort_by=["ACTUAL_VERIFIED_SAVINGS_USD", "EXPECTED_SAVINGS_USD", "LAST_REFRESHED_TS"],
                ascending=[False, False, False],
                raw_label="All closed-loop verification rows",
                height=300,
                max_rows=10,
            )


def _render_command_center_investigation_gate(company: str, environment: str) -> None:
    """Expose Phase 2F correlated investigations only behind Load."""
    st.markdown("**Correlated Investigations**")
    st.caption(
        "Loads deterministic root-cause candidates, evidence, and review-gated recommendations from correlated investigation marts. "
        "Possible correlations are not causality claims and no remediation is executed."
    )
    if st.button("Load Correlated Investigations", key="dba_load_command_center_investigations", width="stretch"):
        st.session_state["dba_command_center_findings"] = load_command_center_finding_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["dba_command_center_evidence"] = load_command_center_evidence_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["dba_command_center_recommendations"] = load_command_center_recommendation_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["dba_command_center_scope"] = (company, environment)

    if st.session_state.get("dba_command_center_scope") != (company, environment):
        return

    findings = st.session_state.get("dba_command_center_findings")
    evidence = st.session_state.get("dba_command_center_evidence")
    recommendations = st.session_state.get("dba_command_center_recommendations")
    if isinstance(findings, pd.DataFrame):
        if findings.empty:
            st.info("No correlated investigation findings are available for this scope yet.")
        else:
            risk = findings.get("RISK_LEVEL", pd.Series(dtype=str)).fillna("").astype(str)
            owner_gap = pd.to_numeric(findings.get("OWNER_GAP", pd.Series(dtype=float)), errors="coerce").fillna(0)
            value = pd.to_numeric(
                findings.get("EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", pd.Series(dtype=float)),
                errors="coerce",
            ).fillna(0)
            render_shell_snapshot((
                ("Findings", f"{len(findings):,}"),
                ("High Risk", f"{safe_int(risk.isin(['Critical', 'High']).sum()):,}"),
                ("Owner Gaps", f"{safe_int(owner_gap.sum()):,}"),
                ("Value/Risk", f"${safe_float(value.sum()):,.0f}"),
            ))
            render_priority_dataframe(
                findings,
                title="Correlated root-cause candidates",
                priority_columns=[
                    "INVESTIGATION_TYPE", "QUESTION_TEXT", "ROOT_CAUSE_CANDIDATE",
                    "CAUSALITY_LABEL", "EVIDENCE_SUMMARY", "CONFIDENCE",
                    "BUSINESS_IMPACT", "TECHNICAL_IMPACT", "OWNER_ROUTE",
                    "OWNER_GAP", "RELATED_CHANGES", "RELATED_ALERTS",
                    "RELATED_SCORECARD_DRIVERS", "RELATED_FORECASTS",
                    "RECOMMENDED_ACTION", "RISK_LEVEL", "EXECUTION_PLAN_REF",
                    "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "VERIFICATION_PATH",
                    "LAST_REFRESHED_TS",
                ],
                sort_by=["RISK_LEVEL", "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "LAST_REFRESHED_TS"],
                ascending=[True, False, False],
                raw_label="All correlated investigation finding rows",
                height=340,
                max_rows=12,
            )
    if isinstance(evidence, pd.DataFrame):
        if evidence.empty:
            st.info("No correlated investigation evidence rows are available for this scope yet.")
        else:
            render_priority_dataframe(
                evidence,
                title="Correlated investigation evidence trail",
                priority_columns=[
                    "INVESTIGATION_TYPE", "EVIDENCE_TYPE", "SOURCE_OBJECT",
                    "RELATED_OBJECT", "EVIDENCE_SUMMARY", "CONFIDENCE",
                    "CAUSALITY_LABEL", "LAST_REFRESHED_TS",
                ],
                sort_by=["LAST_REFRESHED_TS"],
                ascending=False,
                raw_label="All correlated investigation evidence rows",
                height=300,
                max_rows=10,
            )
    if isinstance(recommendations, pd.DataFrame):
        if recommendations.empty:
            st.info("No correlated investigation recommendations are available for this scope yet.")
        else:
            render_priority_dataframe(
                recommendations,
                title="Review-gated correlated investigation recommendations",
                priority_columns=[
                    "INVESTIGATION_TYPE", "RECOMMENDED_ACTION", "RISK_LEVEL",
                    "OWNER_ROUTE", "EXECUTION_PLAN_REF", "REVIEW_REQUIRED",
                    "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "VERIFICATION_PATH",
                    "SAFETY_NOTE", "LAST_REFRESHED_TS",
                ],
                sort_by=["RISK_LEVEL", "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "LAST_REFRESHED_TS"],
                ascending=[True, False, False],
                raw_label="All correlated investigation recommendation rows",
                height=300,
                max_rows=10,
            )


def _render_advanced_diagnostics_expander(company: str, environment: str) -> None:
    """Render admin/trust diagnostics after the DBA operator workflow."""
    st.divider()
    if not st.session_state.get("dba_control_room_show_advanced_diagnostics"):
        if st.button("Show Advanced Diagnostics", key="dba_control_room_show_advanced_diagnostics", width="stretch"):
            st.session_state["dba_control_room_show_advanced_diagnostics"] = True
        else:
            st.caption("Advanced diagnostics stay unloaded until requested.")
            return
    with st.expander("Advanced diagnostics and enterprise evidence", expanded=False):
        _render_enterprise_diagnostics_gate(company, environment)
        _render_production_readiness_gate(company, environment)
        _render_executive_scorecard_driver_gate(company, environment)
        _render_forecast_exception_gate(company, environment)
        _render_change_intelligence_gate(company, environment)
        _render_closed_loop_operations_gate(company, environment)
        _render_command_center_investigation_gate(company, environment)


def _set_admin_tool_focus(tool: str, group: str, focus: str) -> None:
    st.session_state["dba_tools_focus"] = focus
    st.session_state["dba_tools_focus_tool"] = tool
    st.session_state["dba_tools_group_selector"] = group


def _render_admin_tools() -> None:
    """Render guarded Snowflake admin tools inside the DBA Control Room."""
    from sections import dba_tools

    st.subheader("Controlled Admin Tools")
    st.caption(
        "Use these guarded workflows for Snowflake-side changes such as warehouse timeout settings, "
        "AUTO_SUSPEND, task controls, query cancellation, and Cortex account limits."
    )
    quick_paths = (
        ("Warehouse Settings", "Warehouse Ops", "Controlled Actions"),
        ("Cortex AI Limits", "Cost & Health", "Cost"),
        ("Task Graph Control", "Warehouse Ops", "Controlled Actions"),
        ("Query Kill List", "Warehouse Ops", "Controlled Actions"),
    )
    cols = st.columns(len(quick_paths))
    for idx, (tool, group, focus) in enumerate(quick_paths):
        with cols[idx]:
            if st.button(tool, key=f"dba_admin_tool_{tool}", width="stretch"):
                _set_admin_tool_focus(tool, group, focus)
                st.rerun()
    if "dba_tools_focus_tool" not in st.session_state:
        _set_admin_tool_focus("Warehouse Settings", "Warehouse Ops", "Controlled Actions")
    dba_tools.render()


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
            if st.button(route, key=f"dba_control_route_{idx}_{route}_{workflow}", width="stretch"):
                _jump(route, workflow=workflow)


def _filter_exceptions(exceptions: pd.DataFrame, terms: tuple[str, ...]) -> pd.DataFrame:
    if exceptions.empty or "Signal" not in exceptions.columns:
        return _empty_df()
    return exceptions[
        exceptions["Signal"].fillna("").astype(str).str.contains("|".join(terms), case=False, regex=True)
    ].copy()


def _render_morning_cockpit_empty(load_callback) -> None:
    st.markdown("**Morning Cockpit**")
    render_shell_snapshot((
        ("Failures", "Pending"),
        ("Cost", "Pending"),
        ("Queue", "Pending"),
        ("Security", "Pending"),
        ("Changes", "Pending"),
    ))
    st.caption("Load the morning cockpit when you need current DBA-owned exceptions, owner routes, and action status.")
    c1, _spacer = st.columns(2)
    with c1:
        if st.button("Load Morning Cockpit", key="dba_morning_cockpit_load_empty", type="primary", width="stretch"):
            load_callback(status_label="Loading Morning Cockpit", auto_build_ops=True)
            st.rerun()


def _render_morning_cockpit(
    data: dict,
    exceptions: pd.DataFrame,
    row,
    period_credits: float,
    credit_delta: float,
    credit_price: float,
) -> None:
    failed_queries = safe_int(row.get("FAILED_QUERIES", 0))
    failed_tasks = safe_int(row.get("FAILED_TASKS", row.get("FAILED_TASK_RUNS", 0)))
    queued_queries = safe_int(row.get("QUEUED_QUERIES", 0))
    failed_procedures = len(data.get("procedure_sla_cost", _empty_df()))
    failed_logins = len(data.get("failed_logins", _empty_df()))
    changes = len(data.get("object_changes", _empty_df()))
    st.markdown("**Morning Cockpit**")
    render_shell_snapshot((
        ("Failed Queries", f"{failed_queries:,}"),
        ("Failed Tasks", f"{failed_tasks:,}"),
        ("Failed Procedures", f"{failed_procedures:,}"),
        ("Credits", format_credits(period_credits)),
        ("Credit Delta", f"{credit_delta:+.1f}%"),
        ("Queued", f"{queued_queries:,}"),
        ("Security Warnings", f"{failed_logins:,}"),
        ("Recent Changes", f"{changes:,}"),
    ))
    priority = _priority_exceptions(exceptions).head(5)
    if priority.empty:
        st.success("No major DBA-owned exceptions detected for the loaded scope.")
    else:
        render_priority_dataframe(
            priority,
            title="Top 5 DBA actions today",
            priority_columns=["Severity", "Signal", "Evidence", "Action", "Route", "Workflow"],
            sort_by=["Severity", "Signal"],
            ascending=[True, True],
            raw_label="All morning cockpit actions",
            height=240,
        )
        _render_route_buttons(priority)
    st.caption("Use the focused watches for failures, cost, performance, changes, or the DBA action queue.")


def _render_failure_triage(data: dict, exceptions: pd.DataFrame) -> None:
    st.markdown("**Failure Triage**")
    failure_rows = _filter_exceptions(exceptions, ("fail", "task", "procedure", "copy", "load", "sla"))
    if failure_rows.empty:
        st.success("No failed task, procedure, query, copy/load, or SLA signals crossed the Control Room thresholds.")
    else:
        render_priority_dataframe(
            failure_rows,
            title="Failure triage queue",
            priority_columns=["Severity", "Signal", "Evidence", "Action", "Route", "Workflow"],
            sort_by=["Severity", "Signal"],
            ascending=[True, True],
            raw_label="All failure triage rows",
            height=300,
        )
        _render_route_buttons(failure_rows)
    with st.expander("Failure detail tables", expanded=False):
        detail_map = {
            "Failed Queries": "failed_queries",
            "Task Failures": "task_failures",
            "Task SLA/Cost": "task_sla_cost",
            "Procedure SLA/Cost": "procedure_sla_cost",
        }
        detail_view = st.selectbox(
            "Failure detail",
            tuple(detail_map),
            label_visibility="collapsed",
            key="dba_failure_triage_detail_view",
        )
        df = data.get(detail_map[detail_view], _empty_df())
        if df.empty:
            st.info("No rows found for this failure detail.")
        else:
            render_priority_dataframe(
                df,
                title=f"{detail_view} detail",
                priority_columns=[
                    "SEVERITY", "SIGNAL", "ENTITY", "TASK_NAME", "PROCEDURE_NAME",
                    "QUERY_ID", "WAREHOUSE_NAME", "USER_NAME", "ERROR_MESSAGE",
                    "ALLOCATED_CREDITS", "EST_TOTAL_CREDITS", "DURATION_SEC",
                    "START_TIME", "SCHEDULED_TIME",
                ],
                sort_by=["ALLOCATED_CREDITS", "EST_TOTAL_CREDITS", "DURATION_SEC", "START_TIME", "SCHEDULED_TIME"],
                ascending=[False, False, False, False, False],
                raw_label=f"All {detail_view.lower()} rows",
                height=320,
            )


def _render_cost_watch(data: dict, credit_price: float) -> None:
    st.markdown("**Cost Watch**")
    cost_df = data.get("cost_drivers", _empty_df())
    cortex_df = data.get("cortex_exceptions", _empty_df())
    if cost_df.empty and cortex_df.empty:
        st.info("No cost-driver or Cortex anomaly rows found in the loaded lookback.")
    if not cost_df.empty:
        cost_df = cost_df.copy()
        cost_df["EST_COST"] = cost_df["ALLOCATED_CREDITS"].apply(lambda v: credits_to_dollars(v, credit_price))
        render_priority_dataframe(
            cost_df,
            title="Largest cost drivers",
            priority_columns=[
                "WAREHOUSE_NAME", "USER_NAME", "ROLE_NAME", "DATABASE_NAME",
                "ALLOCATED_CREDITS", "EST_COST", "QUERY_COUNT", "AVG_ELAPSED_SEC",
            ],
            sort_by=["ALLOCATED_CREDITS", "EST_COST"],
            ascending=[False, False],
            raw_label="All cost-driver rows",
            height=300,
        )
        download_csv(cost_df, "dba_control_room_cost_watch.csv")
    if not cortex_df.empty:
        render_priority_dataframe(
            cortex_df,
            title="Cortex and AI cost exceptions",
            priority_columns=["SEVERITY", "SIGNAL", "ENTITY", "ALLOCATED_CREDITS", "EST_COST", "ACTION"],
            sort_by=["ALLOCATED_CREDITS", "EST_COST"],
            ascending=[False, False],
            raw_label="All Cortex cost rows",
            height=220,
        )
    if st.button("Open Cost & Contract", key="dba_cost_watch_open_cost_contract", width="stretch"):
        _jump("Cost & Contract", workflow="Cost Overview")


def _render_performance_watch(data: dict, exceptions: pd.DataFrame) -> None:
    st.markdown("**Performance Watch**")
    performance_rows = _filter_exceptions(exceptions, ("queue", "saturat", "spill", "blocked", "long", "slow", "runtime", "pressure"))
    wh_df = data.get("warehouse_pressure", _empty_df())
    if performance_rows.empty and wh_df.empty:
        st.success("No queue, saturation, spill, blocked query, or pressure signals crossed the Control Room thresholds.")
    elif not performance_rows.empty:
        render_priority_dataframe(
            performance_rows,
            title="Performance actions",
            priority_columns=["Severity", "Signal", "Evidence", "Action", "Route", "Workflow"],
            sort_by=["Severity", "Signal"],
            ascending=[True, True],
            raw_label="All performance action rows",
            height=260,
        )
        _render_route_buttons(performance_rows)
    if not wh_df.empty:
        render_priority_dataframe(
            wh_df,
            title="Warehouse pressure",
            priority_columns=[
                "WAREHOUSE_NAME", "WAREHOUSE_SIZE", "QUEUED_QUERIES",
                "FAILED_QUERIES", "P95_ELAPSED_SEC", "REMOTE_SPILL_GB",
                "QUERY_COUNT", "ALLOCATED_CREDITS",
            ],
            sort_by=["QUEUED_QUERIES", "FAILED_QUERIES", "P95_ELAPSED_SEC"],
            ascending=[False, False, False],
            raw_label="All warehouse-pressure rows",
            height=300,
        )
    if st.button("Open Workload Performance", key="dba_performance_watch_open_workload", width="stretch"):
        _jump("Workload Operations", workflow="Performance & Contention")


def _render_change_watch(data: dict) -> None:
    st.markdown("**Change Watch**")
    changes = data.get("object_changes", _empty_df())
    if changes.empty:
        st.info("No object, task, procedure, access, or deployment-related change rows found in the loaded lookback.")
    else:
        render_priority_dataframe(
            changes,
            title="Recent workload and access changes",
            priority_columns=[
                "SEVERITY", "SIGNAL", "ENTITY", "OBJECT_NAME", "OBJECT_TYPE",
                "USER_NAME", "EVENT_TIMESTAMP", "ACTION",
            ],
            sort_by=["EVENT_TIMESTAMP", "SEVERITY"],
            ascending=[False, True],
            raw_label="All change rows",
            height=320,
        )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Open Workload Change Analysis", key="dba_change_watch_open_workload", width="stretch"):
            _jump("Workload Operations", workflow="Change Analysis")
    with c2:
        if st.button("Open Security Access Changes", key="dba_change_watch_open_security", width="stretch"):
            _jump("Security Monitoring", workflow="Access Changes")


def _render_action_queue_watch(data: dict, company: str, environment: str, lookback_hours: int, source_mode: str) -> None:
    st.markdown("**Action Queue**")
    action_queue = data.get("action_queue", _empty_df())
    command_queue = _build_command_queue(action_queue)
    if command_queue.empty:
        st.info("No DBA-owned action queue rows found for the loaded scope.")
        return
    closure_rollup = _command_queue_closure_readiness(action_queue)
    section_board = _dba_section_operability_board(
        command_queue=command_queue,
        closure_rollup=closure_rollup,
        source_health=_empty_df(),
    )
    _render_command_queue_control(command_queue, action_queue, closure_rollup=closure_rollup, section_board=section_board)
    handoff_rows = _dba_handoff_rows(_empty_df(), command_queue, closure_rollup, _empty_df(), _empty_df())
    handoff_md = _build_dba_shift_handoff_markdown(
        handoff_rows,
        company=company,
        environment=environment,
        lookback_hours=int(lookback_hours),
        source_mode=source_mode,
    )
    with st.expander("Shift handoff", expanded=False):
        _render_shift_handoff_panel(handoff_rows, handoff_md, company=company, environment=environment)


def _render_control_room_admin_advanced(company: str, environment: str) -> None:
    st.markdown("**Control Room Admin / Advanced**")
    st.caption("Advanced proofing, readiness, service posture, admin controls, raw evidence, and validation outputs stay here.")
    advanced_view = st.selectbox(
        "Advanced view",
        ("Service Posture", "Admin Tools", "Diagnostics"),
        label_visibility="collapsed",
        key="dba_control_room_advanced_view",
    )
    if advanced_view == "Service Posture":
        _render_consolidated_service_posture()
    elif advanced_view == "Admin Tools":
        _render_admin_tools()
    else:
        _render_advanced_diagnostics_expander(company, environment)


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    credit_price = safe_float(get_credit_price()) or 3.68
    evidence_mode = current_evidence_mode(st.session_state)
    investigation_mode = evidence_mode_is_investigation(st.session_state)
    all_evidence_mode = evidence_mode_is_all_evidence(st.session_state)
    normalized_view = normalize_dba_control_room_pane(st.session_state.get("dba_control_room_active_view"))
    st.session_state["dba_control_room_active_view"] = normalized_view
    load_label = (
        "Load Full Detail Packet"
        if all_evidence_mode
        else "Load Investigation Detail"
        if investigation_mode
        else "Load Triage"
    )

    if evidence_mode == TRIAGE_MODE_TRIAGE:
        defer_section_note("Start with Morning Cockpit or load triage when current DBA telemetry is needed.")
    elif evidence_mode == TRIAGE_MODE_INVESTIGATE:
        defer_section_note("Investigation mode loads deeper root-cause telemetry only after you ask for it.")
    elif evidence_mode == TRIAGE_MODE_ALL_EVIDENCE:
        defer_section_note("Full detail depth enables bounded live fallback only after explicit load.")

    cortex_budget_usd = float(
        st.session_state.get(
            "dba_control_room_cortex_budget_usd",
            st.session_state.get("cortex_control_budget_usd", 5000.0),
        )
    )
    lookback_hours = int(st.session_state.setdefault("dba_control_room_evidence_lookback_hours", 24) or 24)
    if normalized_view != MORNING_COCKPIT_WORKFLOW:
        render_section_breadcrumb([
            "DBA Control Room",
            DBA_CONTROL_ROOM_PANE_LABELS.get(normalized_view, normalized_view),
        ])
    active_view = _render_dba_control_room_workflow_selector()
    dba_brief = autoload_section_command_brief(
        "DBA Control Room",
        company,
        environment,
        active_decision_window_days(1),
        force=bool(st.session_state.pop("dba_control_room_command_brief_force_refresh", False)),
    )

    def _render_dba_evidence_settings() -> None:
        st.selectbox(
            "Lookback",
            [12, 24, 48, 168],
            index=[12, 24, 48, 168].index(lookback_hours if lookback_hours in [12, 24, 48, 168] else 24),
            format_func=lambda h: f"{h} hours",
            key="dba_control_room_evidence_lookback_hours",
        )

    render_section_command_brief(
        dba_brief,
        key_prefix="dba_control_room_command_brief",
        primary_action=make_decision_refresh_action("DBA Control Room"),
        detail_action=make_evidence_action(
            "DBA Control Room",
            active_view,
            label=load_label,
            help_text="Load the DBA investigation packet for this scope and evidence mode.",
            state_key="dba_control_room_command_brief_load_detail",
            settings_renderer=_render_dba_evidence_settings,
        )
        if active_view == MORNING_COCKPIT_WORKFLOW
        else None,
        current_workflow=DBA_CONTROL_ROOM_PANE_LABELS.get(active_view, active_view),
        compact=active_view != MORNING_COCKPIT_WORKFLOW,
    )
    lookback_hours = int(st.session_state.get("dba_control_room_evidence_lookback_hours", lookback_hours) or lookback_hours)
    dba_decision_state = section_state_from_brief(dba_brief)
    pending_detail_load = bool(st.session_state.get("dba_control_room_command_brief_load_detail"))
    if active_view == MORNING_COCKPIT_WORKFLOW and not pending_detail_load and not st.session_state.get("dba_control_room_data"):
        return
    if (
        dba_decision_state.decision_mode in {"OFFLINE", "UNINITIALIZED"}
        and not st.session_state.get("dba_control_room_data")
        and not pending_detail_load
    ):
        if should_render_daily_diagnostics("DBA Control Room", active_view, dba_decision_state.decision_mode):
            _render_advanced_diagnostics_expander(company, environment)
        return
    defer_section_note(
        f"{freshness_note('ACCOUNT_USAGE')} | "
        f"Cost basis: {metric_confidence_label('allocated')} | "
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

    auto_load_fast_snapshot = consume_section_autoload_request("DBA Control Room")
    if snapshot_scope_ok and snapshot_result is None:
        snapshot_result = load_latest_control_room_mart(company, max_age_hours=6)
        st.session_state["dba_control_room_snapshot_scope_key"] = snapshot_scope_key
        st.session_state["dba_control_room_snapshot_result"] = snapshot_result
    if snapshot_scope_ok and auto_load_fast_snapshot:
        defer_section_note("DBA Control Room opened with the latest compact mart snapshot when available.")
    if snapshot_result is not None and snapshot_result.available and not snapshot_result.data.empty:
        snapshot = snapshot_result.data.copy()
        snapshot_expected_meta = _dba_control_scope_meta(
            company,
            environment,
            int(lookback_hours),
            safe_float(cortex_budget_usd),
            False,
            False,
        )
        snapshot_meta = with_loaded_at(
            snapshot_expected_meta,
            source=getattr(snapshot_result, "source", "Fast summary snapshot"),
        )
        loaded_snapshot_meta = st.session_state.get("dba_control_room_meta", {})
        if (
            not st.session_state.get("dba_control_room_data")
            or not _dba_control_meta_matches(loaded_snapshot_meta, snapshot_expected_meta)
            or st.session_state.get("dba_control_room_source_mode") != "Fast summary snapshot"
        ):
            st.session_state["dba_control_room_data"] = _control_room_snapshot_to_data(snapshot)
            st.session_state["dba_control_room_company"] = company
            st.session_state["dba_control_room_lookback"] = int(lookback_hours)
            st.session_state["dba_control_room_source_mode"] = "Fast summary snapshot"
            st.session_state["dba_control_room_meta"] = snapshot_meta
            _clear_dba_control_room_derived_state()
    elif snapshot_result is not None and not snapshot_result.available:
        st.caption("Control-room summary mart unavailable. Load investigation detail only if row-level evidence is needed.")
    elif not snapshot_scope_ok:
        st.caption("Clear filters or refresh the operations detail for this scoped view.")

    mode_default_key = "_dba_control_room_detail_defaults"
    if st.session_state.get(mode_default_key) != evidence_mode:
        st.session_state["dba_control_room_include_deep_evidence"] = bool(investigation_mode)
        st.session_state["dba_control_room_allow_live_fallback"] = bool(all_evidence_mode)
        st.session_state[mode_default_key] = evidence_mode

    cortex_budget_usd = float(
        st.session_state.get(
            "dba_control_room_cortex_budget_usd",
            st.session_state.get("cortex_control_budget_usd", 5000.0),
        )
    )
    include_deep_evidence = bool(st.session_state.get("dba_control_room_include_deep_evidence", False))
    allow_live_fallback = bool(st.session_state.get("dba_control_room_allow_live_fallback", False))
    def _load_control_room_evidence(*, status_label: str = "Loading exception signals", auto_build_ops: bool = False) -> None:
        with render_load_status(status_label, "Control Room telemetry ready"):
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
                "Deep telemetry summary + limited live fallback"
                if include_deep_evidence and allow_live_fallback
                else "Deep telemetry summary-only"
                if include_deep_evidence
                else "Fast triage summary + limited live fallback"
                if allow_live_fallback
                else "Fast triage summary"
            )
            st.session_state["dba_control_room_live_fallback"] = bool(allow_live_fallback)
            st.session_state["dba_control_room_meta"] = with_loaded_at(
                _dba_control_scope_meta(
                    company,
                    environment,
                    int(lookback_hours),
                    safe_float(cortex_budget_usd),
                    bool(include_deep_evidence),
                    bool(allow_live_fallback),
                ),
                source=st.session_state["dba_control_room_source_mode"],
            )
            _clear_dba_control_room_derived_state()
            if auto_build_ops:
                st.session_state["_dba_control_room_auto_build_ops"] = True

    auto_load_meta = _dba_control_scope_meta(
        company,
        environment,
        int(lookback_hours),
        safe_float(cortex_budget_usd),
        bool(include_deep_evidence),
        bool(allow_live_fallback),
    )
    loaded_control_meta = st.session_state.get("dba_control_room_meta", {})
    control_current = bool(st.session_state.get("dba_control_room_data")) and all(
        loaded_control_meta.get(key) == value for key, value in auto_load_meta.items()
    )
    render_data_freshness(
        loaded_control_meta if control_current else {},
        source=st.session_state.get("dba_control_room_source_mode", "DBA Control Room triage"),
        target_minutes=30,
        delayed_note="DBA Control Room shows cached triage immediately; guarded live checks are reserved for explicit detail loads.",
    )

    load_requested = bool(st.session_state.pop("dba_control_room_command_brief_load_detail", False))
    if active_view != MORNING_COCKPIT_WORKFLOW:
        load_requested = st.button(load_label, key="dba_control_room_load", type="primary") or load_requested
    if load_requested:
        _load_control_room_evidence()

    data = st.session_state.get("dba_control_room_data", {})
    if st.session_state.get("dba_control_room_active_view") == CONTROL_ROOM_ADMIN_WORKFLOW:
        st.divider()
        if active_view == CONTROL_ROOM_ADMIN_WORKFLOW:
            _render_control_room_admin_advanced(company, environment)
            return
    if not data:
        st.divider()
        if active_view == MORNING_COCKPIT_WORKFLOW:
            _render_morning_cockpit_empty(_load_control_room_evidence)
            return
        if active_view == CONTROL_ROOM_ADMIN_WORKFLOW:
            _render_control_room_admin_advanced(company, environment)
            return
        if active_view == ACTION_QUEUE_WORKFLOW:
            st.warning("Load the Action Queue to see DBA-owned actions, status, owner, and closure detail.")
            st.caption("Workflow: triage refresh -> route priority -> routed action -> closure status.")
            if st.button("Load Action Queue", key="dba_control_room_build_ops_from_empty", type="primary"):
                _load_control_room_evidence(status_label="Loading Action Queue", auto_build_ops=True)
                st.rerun()
        else:
            st.warning(f"{load_label} to see this workflow's DBA telemetry.")
            st.caption("Workflow: load triage -> review action -> open owning section.")
        _render_advanced_diagnostics_expander(company, environment)
        return

    loaded_lookback = st.session_state.get("dba_control_room_lookback", lookback_hours)
    source_mode = st.session_state.get("dba_control_room_source_mode", "Fast triage summary")
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
            "Loaded DBA Control Room telemetry is stale for the active scope. Reload before taking action "
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
        _render_advanced_diagnostics_expander(company, environment)
        return
    if source_mode == "Fast summary snapshot":
        st.caption("Snapshot loaded. Load triage when you need full exception detail.")
    elif source_mode == "Fast triage summary":
        st.caption("Triage loaded. Specialist detail stays in the selected workflow panes.")
    elif "limited live fallback" in source_mode:
        st.caption("Triage loaded with bounded 24-hour live checks.")

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
    cortex_exceptions = data.get("cortex_exceptions", _empty_df())
    release_source_health = _dba_control_source_health_rows(
        data,
        st.session_state,
        company,
        environment,
        int(lookback_hours),
        safe_float(cortex_budget_usd),
        bool(include_deep_evidence),
        bool(allow_live_fallback),
    )
    release_gate_summary, release_gate_rows = _build_auto_release_readiness_gate(data, release_source_health)

    failed_queries = safe_int(row.get("FAILED_QUERIES", 0))
    queued_queries = safe_int(row.get("QUEUED_QUERIES", 0))
    failed_tasks = safe_int(row.get("FAILED_TASKS", row.get("FAILED_TASK_RUNS", 0)))
    source_issue_count = 0
    if not release_source_health.empty and "STATE" in release_source_health.columns:
        source_issue_count = int(
            release_source_health["STATE"].fillna("").astype(str).isin(["Unavailable", "Stale"]).sum()
        )
    render_decision_evidence_panel(
        "DBA Investigation Evidence",
        str(loaded_meta.get("loaded_at") or source_mode or "Loaded DBA evidence"),
        (
            f"{failed_queries:,} failed querie(s), {failed_tasks:,} failed task/procedure signal(s), "
            f"{queued_queries:,} queued query signal(s)."
        ),
        (
            ("Failed queries", f"{failed_queries:,}"),
            ("Queued queries", f"{queued_queries:,}"),
            ("Failed tasks", f"{failed_tasks:,}"),
            ("Source gaps", f"{source_issue_count:,}"),
            ("Credits delta", f"{credit_delta:+.1f}%"),
        ),
        rows=exceptions,
        source_note=str(source_mode),
    )
    _render_dba_action_brief(
        release_gate_summary,
        exceptions,
        queued_queries=queued_queries,
        failed_queries=failed_queries,
    )
    _render_dba_command_intelligence_contract()

    st.divider()

    if active_view == MORNING_COCKPIT_WORKFLOW:
        _render_morning_cockpit(data, exceptions, row, period_credits, credit_delta, credit_price)
        with st.expander("Live watch detail", expanded=False):
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

    elif active_view == FAILURE_TRIAGE_WORKFLOW:
        _render_failure_triage(data, exceptions)

    elif active_view == COST_WATCH_WORKFLOW:
        _render_cost_watch(data, credit_price)

    elif active_view == PERFORMANCE_WATCH_WORKFLOW:
        _render_performance_watch(data, exceptions)

    elif active_view == CHANGE_WATCH_WORKFLOW:
        _render_change_watch(data)

    elif active_view == CONTROL_ROOM_ADMIN_WORKFLOW:
        _render_control_room_admin_advanced(company, environment)

    elif active_view == ACTION_QUEUE_WORKFLOW:
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
        if st.session_state.pop("_dba_control_room_auto_build_ops", False):
            st.session_state["dba_control_room_ops_ready"] = True
        if not st.session_state.get("dba_control_room_ops_ready"):
            st.caption("Build the DBA action queue from route priority, morning brief, escalation, handoff, incident, and advisor telemetry.")
            load_label = "Load Action Queue"
            if st.button(load_label, key="dba_control_room_build_ops", type="primary"):
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
            section_board_for_priority = _dba_section_operability_board(
                command_queue=command_queue,
                closure_rollup=closure_rollup_for_handoff,
                source_health=source_health_for_handoff,
            )
            operations_priority = _dba_operations_priority_index(
                section_board_for_priority,
                incident_board,
                command_queue,
                source_health_for_handoff,
            )
            st.session_state["dba_operations_priority_index"] = operations_priority
            operator_runbook = _dba_operator_runbook(
                operations_priority,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
            )
            operator_runbook_md = _build_dba_operator_runbook_markdown(
                operator_runbook,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
            )
            st.session_state["dba_operator_runbook"] = operator_runbook
            st.session_state["dba_operator_runbook_markdown"] = operator_runbook_md
            incident_md = _build_dba_incident_markdown(
                incident_board,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
                source_mode=source_mode,
            )
            st.session_state["dba_control_room_incident_board"] = incident_board
            from utils import build_loaded_advisor_signal_board

            advisor_signal_board = build_loaded_advisor_signal_board(st.session_state)
            st.session_state["dba_loaded_advisor_signals"] = advisor_signal_board
            handoff_rows = _dba_handoff_rows(
                exceptions,
                command_queue,
                closure_rollup_for_handoff,
                source_health_for_handoff,
                advisor_signal_board,
            )
            handoff_md = _build_dba_shift_handoff_markdown(
                handoff_rows,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
                source_mode=source_mode,
            )
            st.session_state["dba_control_room_handoff"] = handoff_rows
            escalation_packet = _dba_escalation_packet(
                operations_priority,
                incident_board,
                handoff_rows,
                release_gate_rows,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
            )
            escalation_md = _build_dba_escalation_packet_markdown(
                escalation_packet,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
            )
            st.session_state["dba_control_room_escalation_packet"] = escalation_packet
            st.session_state["dba_control_room_escalation_packet_markdown"] = escalation_md
            workload_morning_lanes = _dba_workload_morning_lanes(data, exceptions)
            morning_brief = _dba_morning_brief_rows(
                operations_priority,
                escalation_packet,
                handoff_rows,
                workload_morning_lanes,
            )
            morning_brief_md = _build_dba_morning_brief_markdown(
                morning_brief,
                company=company,
                environment=environment,
                lookback_hours=int(lookback_hours),
            )
            st.session_state["dba_control_room_morning_brief"] = morning_brief
            st.session_state["dba_control_room_morning_brief_markdown"] = morning_brief_md

            ops_detail_options = ("Queue", "Daily Brief", "Priority", "Runbook", "Escalations", "Handoff", "Incident Board", "Advisors")
            if st.session_state.get("dba_operations_board_detail") not in ops_detail_options:
                st.session_state["dba_operations_board_detail"] = "Queue"
            ops_detail = st.selectbox(
                "Action Queue detail",
                ops_detail_options,
                label_visibility="collapsed",
                key="dba_operations_board_detail",
            )
            if ops_detail == "Daily Brief":
                _render_dba_morning_brief(morning_brief, morning_brief_md)
            elif ops_detail == "Priority":
                _render_operations_priority_index(operations_priority)
            elif ops_detail == "Runbook":
                _render_dba_operator_runbook(operator_runbook, operator_runbook_md)
            elif ops_detail == "Escalations":
                _render_dba_escalation_packet(escalation_packet, escalation_md)
            elif ops_detail == "Handoff":
                _render_shift_handoff_panel(
                    handoff_rows,
                    handoff_md,
                    company=company,
                    environment=environment,
                )
            elif ops_detail == "Incident Board":
                _render_incident_board_panel(
                    incident_board,
                    incident_md,
                    company=company,
                    environment=environment,
                )
            elif ops_detail == "Advisors":
                _render_loaded_advisor_signals(advisor_signal_board)
            elif ops_detail == "Queue":
                _render_command_queue_control(
                    command_queue,
                    action_queue,
                    closure_rollup=closure_rollup_for_handoff,
                    section_board=section_board_for_priority,
                )

    elif active_view == "Drill Routes":
        r1, r2, r3 = st.columns(3)
        with r1:
            st.subheader("Reliability")
            st.write("Failed queries, task failures, queued workload, and slow p95 runtime.")
            reliability_routes = [
                ("Query Investigation", "Query Investigation"),
                ("Pipeline & Task Health", "Pipeline & Task Health"),
                ("Load Issues & SLA", "Load Issues & SLA"),
            ]
            for label, workflow in reliability_routes:
                if st.button(label, key=f"dba_control_reliability_{label}", width="stretch"):
                    _jump("Workload Operations", workflow=workflow)
        with r2:
            st.subheader("Cost and Capacity")
            st.write("Bill explanations, run-rate pacing, warehouse pressure, rightsizing, recommendations, and action telemetry.")
            for label, title, workflow in [
                ("Cost & Contract", "Cost & Contract", "Cost Explorer"),
                ("AI / Cortex Spend", "Cost & Contract", "Cortex AI"),
                ("Warehouse Capacity", "Cost & Contract", "Cost Recommendations"),
            ]:
                if st.button(label, key=f"dba_control_cost_{label}", width="stretch"):
                    _jump(title, workflow=workflow)
        with r3:
            st.subheader("Security Monitoring")
            st.write("Login posture, grants, data sharing, object changes, procedure lineage, drift checks, and admin controls.")
            for title, workflow in [("Security Posture", "Security Posture"), ("Object Changes", "Object and access changes")]:
                if st.button(title, key=f"dba_control_security_{title}", width="stretch"):
                    _jump("Security Monitoring", workflow=workflow)

        st.divider()
        st.subheader("Exception Detail Samples")
        detail_view = st.selectbox(
            "Exception detail sample",
            DBA_CONTROL_ROOM_DETAIL_PANES,
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
                title=f"{key.replace('_', ' ').title()} detail",
                priority_columns=priority_columns,
                sort_by=sort_by,
                ascending=ascending,
                raw_label=f"All {key.replace('_', ' ')} detail rows",
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
            with render_load_status("Comparing task graphs and stored procedure runs", "Release comparison ready"):
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
            render_shell_snapshot((
                ("Task Regressions", f"{len(task_regressions):,}"),
                ("Procedure Regressions", f"{len(proc_regressions):,}"),
                ("Est. Credit Delta", format_credits(total_credit_delta)),
                ("Est. Cost Delta", f"${credits_to_dollars(total_credit_delta, credit_price):,.2f}"),
            ))

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
                download_text(
                    report,
                    f"overwatch_release_compare_{company}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                    label="Download Release Brief",
                    mime="text/markdown",
                    key="dba_release_compare_report_download",
                )
        else:
            st.info("Choose release windows and run the comparison when you need post-change status.")

    _render_advanced_diagnostics_expander(company, environment)

