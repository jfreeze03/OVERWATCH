"""DBA Control Room - operational landing page for OVERWATCH.

This page is intentionally workflow-first. It summarizes exceptions that a DBA
must triage, routes each signal to the right specialist tool, and creates
report-ready notes for leadership without making executives use the app.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from config import DEFAULT_ENVIRONMENT, DEFAULTS, SECTION_BY_TITLE, normalize_section_name
from sections.base import lazy_pandas, lazy_util as _lazy_util, lazy_util_attr
from sections.navigation import apply_navigation_state
from sections.shell_helpers import (
    _clean_display_text,
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
    render_shell_snapshot,
    render_shell_status_strip,
    with_loaded_at,
)
from utils.evidence_mode import (
    TRIAGE_MODE_ALL_EVIDENCE,
    TRIAGE_MODE_INVESTIGATE,
    TRIAGE_MODE_TRIAGE,
    current_evidence_mode,
    evidence_mode_is_all_evidence,
    evidence_mode_is_investigation,
)
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note


pd = lazy_pandas()

from .types import *
from .health import (
    _build_auto_release_readiness_gate,
    _build_evidence_freshness_gate,
    _build_release_compare_report,
    _build_task_failure_root_cause_timeline,
    _compare_release_windows,
    _cortex_helpers,
    _dba_control_meta_matches,
    _dba_control_scope_meta,
    _dba_control_source_health_rows,
    _dba_snapshot_scope_compatible,
    _dba_task_status_task_summary,
    _frame_or_empty,
    _load_release_compare,
    _procedure_helpers,
    _row_value,
    _task_management_helpers,
)
from .queue import (
    _build_command_queue,
    _canonical_dba_route,
    _command_queue_closure_readiness,
    _command_queue_route,
    _command_queue_route_readiness,
    _command_queue_summary,
    _priority_exceptions,
)
from .incidents import (
    _build_dba_incident_markdown,
    _dba_incident_board,
    _dba_operations_priority_index,
    _dba_section_operability_board,
    _dba_section_proof_required,
)
from .handoff import (
    _build_dba_escalation_packet_markdown,
    _build_dba_morning_brief_markdown,
    _build_dba_operator_runbook_markdown,
    _build_dba_shift_handoff_markdown,
    _dba_action_brief,
    _dba_command_lanes,
    _dba_escalation_packet,
    _dba_handoff_rows,
    _dba_morning_brief_detail_view,
    _dba_morning_brief_rows,
    _dba_morning_command_queue,
    _dba_morning_decision_contract,
    _dba_operator_runbook,
    _dba_workload_morning_lanes,
    _render_dba_action_brief,
    _render_dba_escalation_packet,
    _render_dba_morning_brief,
    _render_dba_operator_runbook,
    _render_shift_handoff_panel,
    _seed_dba_morning_route_context,
)


def _clear_dba_control_room_derived_state() -> None:
    """Clear derived boards when the loaded telemetry scope changes."""
    for key in DBA_CONTROL_ROOM_DERIVED_STATE_KEYS:
        st.session_state.pop(key, None)


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
    st.markdown("**Command Center Investigations**")
    st.caption(
        "Loads deterministic root-cause candidates, evidence, and review-gated recommendations from Command Center marts. "
        "Possible correlations are not causality claims and no remediation is executed."
    )
    if st.button("Load Command Center Investigations", key="dba_load_command_center_investigations", width="stretch"):
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
            st.info("No Command Center findings are available for this scope yet.")
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
                title="Command Center root-cause candidates",
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
                raw_label="All Command Center finding rows",
                height=340,
                max_rows=12,
            )
    if isinstance(evidence, pd.DataFrame):
        if evidence.empty:
            st.info("No Command Center evidence rows are available for this scope yet.")
        else:
            render_priority_dataframe(
                evidence,
                title="Command Center evidence trail",
                priority_columns=[
                    "INVESTIGATION_TYPE", "EVIDENCE_TYPE", "SOURCE_OBJECT",
                    "RELATED_OBJECT", "EVIDENCE_SUMMARY", "CONFIDENCE",
                    "CAUSALITY_LABEL", "LAST_REFRESHED_TS",
                ],
                sort_by=["LAST_REFRESHED_TS"],
                ascending=False,
                raw_label="All Command Center evidence rows",
                height=300,
                max_rows=10,
            )
    if isinstance(recommendations, pd.DataFrame):
        if recommendations.empty:
            st.info("No Command Center recommendations are available for this scope yet.")
        else:
            render_priority_dataframe(
                recommendations,
                title="Review-gated Command Center recommendations",
                priority_columns=[
                    "INVESTIGATION_TYPE", "RECOMMENDED_ACTION", "RISK_LEVEL",
                    "OWNER_ROUTE", "EXECUTION_PLAN_REF", "REVIEW_REQUIRED",
                    "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "VERIFICATION_PATH",
                    "SAFETY_NOTE", "LAST_REFRESHED_TS",
                ],
                sort_by=["RISK_LEVEL", "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "LAST_REFRESHED_TS"],
                ascending=[True, False, False],
                raw_label="All Command Center recommendation rows",
                height=300,
                max_rows=10,
            )


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








def _jump(title: str, *, warehouse: str = "", user: str = "", workflow: str = "") -> None:
    """Navigate to a registered section and carry useful filter context."""
    raw_target = SECTION_BY_TITLE.get(title, title)
    target = normalize_section_name(raw_target)
    if target not in set(SECTION_BY_TITLE.values()):
        return
    apply_navigation_state(raw_target)
    if workflow:
        if title in {"Query Workbench", "Workload Operations"}:
            st.session_state["_workload_operations_explicit_workflow_request"] = True
            if workflow == "Diagnosis":
                st.session_state["workload_operations_workflow"] = "Query diagnosis"
            elif workflow == "History Search":
                st.session_state["workload_operations_workflow"] = "Query diagnosis"
                st.session_state["query_analysis_active_view"] = "History Search"
            else:
                st.session_state["workload_operations_workflow"] = workflow
        elif title == "DBA Control Room" and workflow in DBA_CONTROL_ROOM_PANES:
            st.session_state["dba_control_room_active_view"] = workflow
        elif title == "Cost & Contract":
            st.session_state["cost_contract_workflow"] = workflow
        elif title == "Security Monitoring":
            st.session_state["security_posture_view"] = workflow if workflow in {"Access posture", "Privilege sprawl", "Data sharing exposure"} else "Access posture"
            st.session_state["security_posture_workflow"] = workflow or "Access posture"
        elif title == "Security Posture":
            st.session_state["security_posture_workflow"] = workflow
    if warehouse:
        st.session_state["global_warehouse"] = warehouse
        st.session_state["wh_filter"] = warehouse
    if user:
        st.session_state["global_user"] = user
    st.rerun()










































def _snapshot_metric(df: pd.DataFrame, column: str) -> float:
    if df is None or df.empty or column not in df.columns:
        return 0.0
    return safe_float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _control_room_snapshot_to_data(snapshot: pd.DataFrame) -> dict:
    """Convert the lightweight summary snapshot into the data shape used by the page.

    The summary snapshot is intentionally small: it supports the watch floor and
    morning triage metrics, while deep telemetry tables still load on demand.
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
                "Mode": "Fast summary snapshot",
                "Message": "Company-level snapshot; use scoped detail load when environment or triage filters are active.",
            },
            {"Source": "summary", "Mode": "Fast summary snapshot"},
            {"Source": "credits", "Mode": "Fast summary snapshot"},
            {"Source": "task_failures", "Mode": "Fast summary snapshot"},
            {"Source": "failed_logins", "Mode": "Fast summary snapshot"},
            {"Source": "object_changes", "Mode": "Fast summary snapshot"},
            {"Source": "cortex_cost", "Mode": "Fast summary snapshot"},
        ]),
    }


def _scalar_frame_value(data: dict, key: str, column: str, default=0):
    df = data.get(key, _empty_df())
    if df is None or df.empty or column not in df.columns:
        return default
    return df.iloc[0].get(column, default)
























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
    global_q = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name", "q.schema_name"
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
              {global_q}
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
              {global_q}
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
              {global_q}
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
              {get_user_company_filter_clause("user_name", company)}
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
                source_rows.append({"Source": key, "Mode": "Fast summary"})
            except Exception as mart_exc:
                if not allow_live_fallback:
                    data[key] = _empty_df()
                    data[f"{key}_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                    source_rows.append({
                        "Source": key,
                        "Mode": "Fast summary unavailable",
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
                        f"Fast summary unavailable; ran a bounded ACCOUNT_USAGE probe capped at "
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
            source_rows.append({"Source": "task_failures", "Mode": "Fast summary"})
        except Exception as mart_exc:
            if not allow_live_fallback:
                data["task_failures"] = _empty_df()
                data["task_failures_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                source_rows.append({
                    "Source": "task_failures",
                    "Mode": "Fast summary unavailable",
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

    if include_deep_evidence and allow_live_fallback:
        try:
            from sections.workload_operations import _build_workload_task_status_sql

            environment = get_active_environment()
            data["workload_task_status"] = run_query(
                _build_workload_task_status_sql(company, environment, hours=min(int(lookback_hours), 24)),
                ttl_key=f"dba_control_room_{company}_{environment}_{lookback_hours}_workload_task_status",
                tier="metadata",
                section="DBA Control Room",
            )
            source_rows.append({"Source": "workload_task_status", "Mode": "Snowflake task metadata"})
        except Exception as exc:
            data["workload_task_status"] = _empty_df()
            data["workload_task_status_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})
            source_rows.append({
                "Source": "workload_task_status",
                "Mode": "Metadata unavailable",
                "Message": "Snowflake TASK_HISTORY summary unavailable; verify ACCOUNT_USAGE access or refresh later.",
            })
    else:
        data["workload_task_status"] = _empty_df()
        source_rows.append({
            "Source": "workload_task_status",
            "Mode": "Live fallback deferred" if allow_live_fallback else "Fast summary unavailable",
            "Message": "Snowflake TASK_HISTORY summary runs only when deep telemetry and live fallback are both enabled.",
        })

    try:
        data["schema_migration_status"] = run_query(
            build_schema_migration_status_sql(),
            ttl_key="dba_control_room_schema_migration_status",
            tier="metadata",
            section="DBA Control Room",
        )
        source_rows.append({"Source": "schema_migration_status", "Mode": "Snowflake metadata"})
    except Exception as exc:
        data["schema_migration_status"] = _empty_df()
        data["schema_migration_status_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})
        source_rows.append({
            "Source": "schema_migration_status",
            "Mode": "Metadata unavailable",
            "Message": "Release migration status unavailable; complete status or remediation review before release review.",
        })

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
                "Message": "Skipped for fast DBA Control Room triage. Use Workload Operations for task run telemetry.",
            },
            {
                "Source": "procedure_sla",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Workload Operations for procedure SLA/cost telemetry.",
            },
            {
                "Source": "cortex_cost",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Cost & Contract for Cortex cost telemetry.",
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
        task_history_source = "Fast summary"
        try:
            task_history = run_query(
                build_mart_task_history_sql(max(1, int((lookback_hours + 23) / 24)), company=company, limit=1000),
                ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_task_sla_history",
                tier="historical",
                section="DBA Control Room",
            )
        except Exception as mart_exc:
            if not allow_live_fallback:
                task_history_source = "Fast summary unavailable"
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
        if task_history_source == "Fast summary":
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
                    source_rows.append({"Source": "task_query_detail", "Mode": "Fast summary"})
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
            source_rows.append({"Source": "procedure_sla", "Mode": "Fast summary"})
        except Exception as mart_exc:
            proc_runs = _empty_df()
            source_rows.append({
                "Source": "procedure_sla",
                "Mode": "Live fallback deferred" if allow_live_fallback else "Fast summary unavailable",
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
    release_summary, _release_gate = _build_auto_release_readiness_gate(data)
    if safe_int(release_summary.get("blocked")):
        rows.append({
            "Severity": "High",
            "Signal": "Operational status blocked",
            "Evidence": (
                f"{safe_int(release_summary.get('blocked')):,} blocked status item(s); "
                f"{safe_int(release_summary.get('review')):,} review item(s)"
            ),
            "Action": "Open Operations Detail and clear task recovery blockers before production change.",
            "Route": "DBA Control Room",
            "Workflow": "Operations Detail",
        })
    elif safe_int(release_summary.get("review")):
        rows.append({
            "Severity": "Medium",
            "Signal": "Operational status needs review",
            "Evidence": f"{safe_int(release_summary.get('review')):,} operational status review item(s)",
            "Action": "Review task timeline, telemetry status, and rollback path before production change.",
            "Route": "DBA Control Room",
            "Workflow": "Operations Detail",
        })
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
            "Route": "Cost & Contract",
            "Workflow": "Recommendations and action queue",
        })
    if spill_queries:
        rows.append({
            "Severity": "High" if spill_queries >= 10 else "Medium",
            "Signal": "Remote spill",
            "Evidence": f"{spill_queries:,} queries spilled to remote storage",
            "Action": "Inspect spilling queries before resizing.",
            "Route": "Cost & Contract",
            "Workflow": "Recommendations and action queue",
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
            "Workflow": "Usage attribution and run-rate",
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
                    f"Projected 30-day Cortex cost ${projected_cost:,.0f} vs ${cortex_budget:,.0f} spend threshold; "
                    f"{len(cortex_exceptions):,} user/source exception(s); state {_cortex_cost_rating(score)}"
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
            "Route": "Security Monitoring",
            "Workflow": "Security Posture",
        })
    if not changes.empty:
        rows.append({
            "Severity": "Medium",
            "Signal": "Object or grant changes",
            "Evidence": f"{len(changes):,} recent object/access changes",
            "Action": "Validate expected change windows and route context.",
            "Route": "Security Monitoring",
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
            "Action": "Assign routes and move items toward fixed/ignored.",
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
                    "Signal": "Closure status blockers",
                    "Evidence": (
                        f"{len(closure_blockers):,} route(s) blocked; {overdue:,} overdue, "
                        f"{unverified:,} closed pending telemetry, {recovery:,} recovery status risk."
                    ),
                    "Action": "Use DBA Action Queue Control to close telemetry, ticket, review, and recovery gaps.",
                    "Route": "DBA Control Room",
                    "Workflow": "Action Queue",
                })

    return pd.DataFrame(rows)


























































def _render_operations_priority_index(priority_index: pd.DataFrame) -> None:
    if priority_index is None or priority_index.empty:
        return
    hot = priority_index.iloc[0]
    st.markdown("**Operations Priority**")
    first_move = str(hot.get("FIRST_MOVE") or "Review the top routed workflow.").strip()
    top_route = str(hot.get("SECTION") or "DBA Control Room").strip()
    st.info(f"{top_route}: {first_move}")
    open_blocks = (
        safe_int(hot.get("PROOF_BLOCKS"))
        + safe_int(hot.get("METADATA_BLOCKS"))
        + safe_int(hot.get("APPROVAL_BLOCKS"))
        + safe_int(hot.get("SOURCE_ISSUES"))
    )
    render_shell_snapshot((
        ("Top Route", top_route),
        ("Open Blocks", f"{open_blocks:,}"),
        ("Routes Reviewed", f"{len(priority_index):,}"),
    ))
    view = priority_index.rename(columns={
        "OPERATIONS_PRIORITY_STATE": "State",
        "SECTION": "Route",
        "WORST_SIGNAL": "Signal",
        "OVERDUE": "Overdue",
        "PROOF_BLOCKS": "Telemetry Blocks",
        "METADATA_BLOCKS": "Metadata Blocks",
        "APPROVAL_BLOCKS": "Review Blocks",
        "SOURCE_ISSUES": "Input Issues",
        "WHY_NOW": "Why Now",
        "FIRST_MOVE": "First Move",
        "PROOF_REQUIRED": "Telemetry Basis",
        "PRIORITY_SCORE": "Sort Priority",
    })
    render_priority_dataframe(
        view,
        title="Operations priority board",
        priority_columns=[
            "Route", "State", "Signal", "Overdue", "Telemetry Blocks", "Metadata Blocks",
            "Review Blocks", "Input Issues", "Why Now", "First Move", "Telemetry Basis",
        ],
        sort_by=["Sort Priority", "Overdue", "Telemetry Blocks"],
        ascending=[False, False, False],
        raw_label="All operations priority rows",
        height=260,
        max_rows=9,
    )
    download_csv(view, "dba_operations_priority.csv")












































def _render_command_queue_control(
    queue: pd.DataFrame,
    raw_queue: pd.DataFrame | None = None,
    closure_rollup: pd.DataFrame | None = None,
    section_board: pd.DataFrame | None = None,
) -> None:
    summary = _command_queue_summary(queue)
    if closure_rollup is None:
        closure_rollup = _command_queue_closure_readiness(raw_queue if raw_queue is not None else queue)
    if queue.empty and closure_rollup.empty:
        st.success("No open action queue items or closure status blockers for the current company/environment scope.")
        return
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
    st.markdown("**DBA Action Queue Control**")
    total_blocks = summary["approval_blocks"] + summary["metadata_blocks"] + closure_blockers
    render_shell_snapshot((
        ("Open Actions", f"{summary['open']:,}"),
        ("Overdue", f"{summary['overdue']:,}"),
        ("Ready", f"{summary['execution_ready']:,}"),
        ("Blocked", f"{total_blocks:,}"),
    ))

    if section_board is None:
        section_board = _dba_section_operability_board(
            command_queue=queue,
            closure_rollup=closure_rollup,
        )
    if not section_board.empty:
        render_priority_dataframe(
            section_board,
            title="DBA operating detail",
            priority_columns=[
                "OPERABILITY_STATE", "SECTION", "DEPLOYMENT_LABEL", "GATE_DRIVERS", "OPEN_ACTIONS",
                "OVERDUE", "EXECUTION_READY", "METADATA_BLOCKS", "APPROVAL_BLOCKS",
                "CLOSURE_READINESS", "CLOSURE_BLOCKERS", "FIXED_WITHOUT_VERIFICATION",
                "RECOVERY_RISK_ROWS", "LOWEST_COMPONENT",
                "PROOF_REQUIRED", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["OPERABILITY_RANK", "OVERDUE"],
            ascending=[True, False],
            raw_label="All DBA operating rows",
            height=280,
            max_rows=12,
        )

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
            raw_label="All closure status rows",
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
            title="Action status by DBA route",
            priority_columns=[
                "ROUTE", "OPEN_ACTIONS", "OVERDUE", "EXECUTION_READY", "AUDIT_READY",
                "ROUTE_READY", "OWNER_GAPS", "APPROVAL_BLOCKS", "METADATA_BLOCKS",
                "CONTROL_READY_PCT", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["OVERDUE", "METADATA_BLOCKS", "APPROVAL_BLOCKS", "OPEN_ACTIONS"],
            ascending=[False, False, False, False],
            raw_label="All action route status rows",
            height=220,
            max_rows=10,
        )

    render_priority_dataframe(
        queue,
        title="Open queue items to route, monitor, or escalate",
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


def _render_dba_command_intelligence_contract() -> None:
    """Show the command intelligence layer that DBA Control Room owns."""
    from utils.operational_intelligence import build_capability_register_rows

    focus = {
        "Detection and Root-Cause Engine",
        "Task/Pipeline Critical Path Brain",
        "Alert Lifecycle 2.0",
        "Bounded Refresh Guardrails",
        "Scheduled Mart Layer With Fallback",
        "Monitoring Docs and Runbooks",
    }
    rows = pd.DataFrame(
        [row for row in build_capability_register_rows() if row["CAPABILITY"] in focus]
    )
    render_priority_dataframe(
        rows,
        title="DBA command intelligence foundation",
        priority_columns=[
            "RANK", "CAPABILITY", "STATUS", "WHY_IT_MATTERS",
            "NEXT_ACTION", "PRODUCTION_GUARDRAIL",
        ],
        sort_by=["RANK"],
        ascending=True,
        raw_label="All DBA command intelligence rows",
        height=240,
        max_rows=6,
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
    priority = _priority_exceptions(exceptions).head(3)
    st.markdown("**DBA Watch Floor**")
    if priority.empty:
        st.success("Watch floor is clear. Use Release Compare or Data Health if you are checking a recent release.")
        return

    first = priority.iloc[0]
    st.warning(
        f"First move: {first.get('Signal', 'Exception')} -> {first.get('Action', 'Review the routed workflow.')}"
    )
    cols = st.columns(len(priority))
    for idx, (_, item) in enumerate(priority.iterrows()):
        route = str(item.get("Route", "") or "")
        workflow = str(item.get("Workflow", "") or "")
        with cols[idx]:
            render_escaped_bold_text(f"{item.get('Severity', 'Signal')}: {item.get('Signal', '')}")
            st.caption(_clean_display_text(str(item.get("Telemetry", item.get("Evidence", "")))))
            st.write(str(item.get("Action", "")))
            if route and st.button(f"Open {route}", key=f"dba_watch_floor_{idx}_{route}", width="stretch"):
                _jump(route, workflow=workflow)














def _render_loaded_advisor_signals(advisor_rows: pd.DataFrame | None) -> None:
    if advisor_rows is None or advisor_rows.empty:
        st.info("No loaded advisor signals are available yet. Open Cost & Contract, Warehouse Health, or Stored Procedures and load advisor telemetry.")
        return
    rows = advisor_rows.copy()
    high = int(rows["SEVERITY"].astype(str).str.title().isin(["Critical", "High"]).sum()) if "SEVERITY" in rows.columns else 0
    savings = safe_float(pd.to_numeric(rows.get("EST_MONTHLY_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    risk = safe_float(pd.to_numeric(rows.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    st.markdown("**Loaded Advisor Signals**")
    render_shell_snapshot((
        ("Signals", f"{len(rows):,}"),
        ("High Priority", f"{high:,}"),
        ("Est. Savings / Mo", f"${savings:,.0f}"),
        ("Value At Risk", f"${risk:,.0f}"),
    ))
    render_priority_dataframe(
        rows,
        title="Loaded advisor queue",
        priority_columns=[
            "SOURCE_SURFACE", "SEVERITY", "SIGNAL", "ENTITY", "ROUTE",
            "NEXT_ACTION", "TELEMETRY_BASIS", "EST_MONTHLY_SAVINGS_USD", "VALUE_AT_RISK_USD",
        ],
        sort_by=["PRIORITY_RANK", "VALUE_AT_RISK_USD", "EST_MONTHLY_SAVINGS_USD"],
        ascending=[True, False, False],
        raw_label="All loaded advisor signals",
        height=320,
        max_rows=14,
    )




def _render_incident_board_panel(
    incident_board: pd.DataFrame,
    incident_md: str,
    *,
    company: str,
    environment: str,
) -> None:
    if incident_board is None or incident_board.empty:
        return
    st.markdown("**DBA Incident Detail**")
    render_shell_snapshot((
        ("Incidents", f"{len(incident_board):,}"),
        ("Containment", f"{int(incident_board['STATUS'].astype(str).eq('Containment Required').sum()):,}"),
        ("Overdue", f"{int(pd.to_numeric(incident_board['OVERDUE'], errors='coerce').fillna(0).sum()):,}"),
        ("Telemetry Issues", f"{int(pd.to_numeric(incident_board['SOURCE_ISSUES'], errors='coerce').fillna(0).sum()):,}"),
    ))
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
        "Download DBA Incident Detail",
        incident_md,
        file_name=f"overwatch_dba_incident_detail_{company.lower()}_{environment.lower()}.md",
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
        st.info("No data health rows are available yet.")
        return source_health
    current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
    stale = int(source_health["STATE"].eq("Stale").sum())
    unavailable = int(source_health["STATE"].eq("Unavailable").sum())
    fast_summary = int(
        source_health[
            source_health["STATE"].isin(["Loaded", "No Rows"])
            & source_health["MODE"].astype(str).str.contains("fast summary", case=False, regex=False)
        ].shape[0]
    )
    render_shell_snapshot((
        ("Current Surfaces", f"{current}/{len(source_health)}"),
        ("Fast Summary", f"{fast_summary:,}"),
        ("Stale", f"{stale:,}"),
        ("Unavailable", f"{unavailable:,}"),
    ))
    st.caption(
        "Use this before acting from the Control Room. Stale rows mean telemetry was loaded under a different "
        "company, environment, lookback, spend threshold, fallback mode, or triage filter scope."
    )
    render_priority_dataframe(
        source_health,
        title="Control-room telemetry freshness and data mode",
        priority_columns=["STATE", "SURFACE", "MODE", "ROWS", "SCOPE", "MESSAGE", "NEXT_ACTION"],
        sort_by=["STATE_RANK", "SURFACE"],
        ascending=[True, True],
        raw_label="All control-room data-health rows",
        height=360,
    )
    return source_health


def _render_release_readiness_gate(
    data: dict,
    source_health: pd.DataFrame | None,
    *,
    company: str,
    environment: str,
    lookback_hours: int,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    summary, gate = _build_auto_release_readiness_gate(data, source_health)
    timeline = _build_task_failure_root_cause_timeline(
        data,
        company=company,
        environment=environment,
        lookback_hours=lookback_hours,
    )
    render_shell_snapshot((
        ("Gate State", _gate_state_from_counts(safe_int(summary.get("blocked")), safe_int(summary.get("review")))),
        ("Blocked", f"{safe_int(summary.get('blocked')):,}"),
        ("Review", f"{safe_int(summary.get('review')):,}"),
        ("Ready", f"{safe_int(summary.get('ready')):,}"),
        ("Timeline Events", f"{len(timeline):,}"),
    ))
    if safe_int(summary.get("blocked")):
        st.error("Change path is blocked by release or task recovery telemetry.")
    elif safe_int(summary.get("review")) or safe_int(summary.get("not_loaded")):
        st.warning("Change review needs status confirmation before production change.")
    else:
        st.success("Loaded operational telemetry is clear.")

    render_priority_dataframe(
        gate,
        title="Operational status gate",
        priority_columns=["GATE", "STATE", "SEVERITY", "EVIDENCE", "NEXT_ACTION", "ROUTE", "PROOF_REQUIRED"],
        sort_by=["STATE", "SEVERITY", "GATE"],
        ascending=[True, True, True],
        raw_label="All operational status rows",
        height=300,
    )
    download_csv(gate, "overwatch_auto_release_gate.csv")

    source_gate_summary, source_gate = _build_evidence_freshness_gate(source_health)
    if not source_gate.empty:
        st.markdown("**Telemetry Status Gate**")
        render_shell_snapshot((
            ("Telemetry State", _gate_state_from_counts(safe_int(source_gate_summary.get("blocked")), safe_int(source_gate_summary.get("review")))),
            ("Blocked Inputs", f"{safe_int(source_gate_summary.get('blocked')):,}"),
            ("Review Inputs", f"{safe_int(source_gate_summary.get('review')):,}"),
            ("Deferred Inputs", f"{safe_int(source_gate_summary.get('deferred')):,}"),
        ))
        render_priority_dataframe(
            source_gate,
            title="Operational telemetry status by input",
            priority_columns=[
                "SURFACE", "GATE_STATE", "SEVERITY", "SOURCE_STATE", "MODE", "ROWS",
                "RELEASE_IMPACT", "ROUTE", "WORKFLOW", "NEXT_ACTION",
            ],
            sort_by=["GATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All operational telemetry status rows",
            height=300,
            max_rows=12,
        )
        download_csv(source_gate, "overwatch_release_evidence_freshness.csv")

    st.markdown("**Task Failure Root-Cause Timeline**")
    render_priority_dataframe(
        timeline,
        title="Task failure root-cause timeline",
        priority_columns=[
            "EVENT_ORDER", "TIMELINE_STAGE", "EVENT_TS", "TASK_NAME", "ROOT_TASK_NAME",
            "ROOT_CAUSE_SIGNAL", "EVIDENCE", "NEXT_ACTION", "SOURCE", "BLOCKS_RELEASE",
        ],
        sort_by=["EVENT_ORDER"],
        ascending=[True],
        raw_label="All task failure timeline rows",
        height=340,
    )
    download_csv(timeline, "overwatch_task_failure_root_cause_timeline.csv")
    r1, r2, r3 = st.columns(3)
    with r1:
        if st.button("Open Workload Operations", key="dba_release_gate_open_workload", width="stretch"):
            _jump("Workload Operations", workflow="Task graphs")
            st.rerun()
    with r2:
        if st.button("Open Security Monitoring", key="dba_release_gate_open_change", width="stretch"):
            _jump("Security Monitoring", workflow="Object and access changes")
            st.rerun()
    with r3:
        if st.button("Open Operations Detail", key="dba_release_gate_open_operations", width="stretch"):
            st.session_state["dba_control_room_active_view"] = "Operations Detail"
            st.rerun()
    return summary, gate, timeline


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


def render() -> None:
    company = get_active_company()
    environment = get_active_environment()
    credit_price = safe_float(get_credit_price()) or 3.68
    evidence_mode = current_evidence_mode(st.session_state)
    investigation_mode = evidence_mode_is_investigation(st.session_state)
    all_evidence_mode = evidence_mode_is_all_evidence(st.session_state)

    render_operator_briefing(
        [
            ("First move", "Use the fast snapshot for cheap triage."),
            ("Telemetry", "Load details only when a signal needs source detail."),
            ("Control", "Route to the specialist workflow before taking action."),
            ("Output", "Export the Morning Brief for DBA handoff."),
        ],
        columns=4,
    )
    if evidence_mode == TRIAGE_MODE_TRIAGE:
        defer_section_note("Landing default keeps this page on actionable issues and DBA handoff telemetry.")
    elif evidence_mode == TRIAGE_MODE_INVESTIGATE:
        defer_section_note("Investigation detail opens deeper root-cause telemetry defaults.")
    elif evidence_mode == TRIAGE_MODE_ALL_EVIDENCE:
        defer_section_note("Full detail depth opens bounded live fallback defaults.")

    cortex_budget_usd = float(
        st.session_state.get(
            "dba_control_room_cortex_budget_usd",
            st.session_state.get("cortex_control_budget_usd", 5000.0),
        )
    )
    c1, c2 = st.columns([1, 1])
    with c1:
        lookback_hours = st.selectbox("Lookback", [12, 24, 48, 168], index=1, format_func=lambda h: f"{h} hours")
    with c2:
        render_shell_snapshot((("Scope", f"{company} / {environment}"),))
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
    if snapshot_scope_ok and auto_load_fast_snapshot and snapshot_result is None:
        with render_load_status("Checking latest control-room summary snapshot", "Fast snapshot check ready"):
            snapshot_result = load_latest_control_room_mart(company, max_age_hours=6)
            st.session_state["dba_control_room_snapshot_scope_key"] = snapshot_scope_key
            st.session_state["dba_control_room_snapshot_result"] = snapshot_result
        if snapshot_result is not None and snapshot_result.available and not snapshot_result.data.empty:
            snapshot = snapshot_result.data.copy()
            st.session_state["dba_control_room_data"] = _control_room_snapshot_to_data(snapshot)
            st.session_state["dba_control_room_company"] = company
            st.session_state["dba_control_room_lookback"] = 24
            st.session_state["dba_control_room_source_mode"] = "Fast summary snapshot"
            st.session_state["dba_control_room_meta"] = with_loaded_at(
                _dba_control_scope_meta(
                    company,
                    environment,
                    24,
                    safe_float(cortex_budget_usd),
                    False,
                    False,
                ),
                source=getattr(snapshot_result, "source", "Fast summary snapshot"),
            )
            _clear_dba_control_room_derived_state()

    if snapshot_scope_ok:
        st.caption("Fast snapshot loads automatically on section navigation; use refresh when current telemetry matters.")
        if st.button("Check Fast Snapshot", key="dba_control_room_check_snapshot"):
            with render_load_status("Checking latest control-room summary snapshot", "Fast snapshot check ready"):
                snapshot_result = load_latest_control_room_mart(company, max_age_hours=6)
                st.session_state["dba_control_room_snapshot_scope_key"] = snapshot_scope_key
                st.session_state["dba_control_room_snapshot_result"] = snapshot_result
    if snapshot_result is not None and snapshot_result.available and not snapshot_result.data.empty:
        snapshot = snapshot_result.data.copy()
        st.caption("Fast snapshot is ready. Use it for cheap triage; load detail only for investigation.")
        render_shell_snapshot(
            (
                ("Failed Queries", f"{safe_int(snapshot['FAILED_QUERIES_24H'].sum()):,}"),
                ("Failed Tasks", f"{safe_int(snapshot['FAILED_TASKS_24H'].sum()):,}"),
                ("Credits 24h", format_credits(snapshot["CREDITS_24H"].sum())),
                ("Cortex 7d", f"${safe_float(snapshot['CORTEX_COST_7D_USD'].sum()):,.0f}"),
            )
        )
        if st.button("Use Fast Snapshot", key="dba_control_room_use_snapshot"):
            st.session_state["dba_control_room_data"] = _control_room_snapshot_to_data(snapshot)
            st.session_state["dba_control_room_company"] = company
            st.session_state["dba_control_room_lookback"] = 24
            st.session_state["dba_control_room_source_mode"] = "Fast summary snapshot"
            st.session_state["dba_control_room_meta"] = with_loaded_at(
                _dba_control_scope_meta(
                    company,
                    environment,
                    24,
                    safe_float(cortex_budget_usd),
                    False,
                    False,
                ),
                source=getattr(snapshot_result, "source", "Fast summary snapshot"),
            )
            _clear_dba_control_room_derived_state()
            st.rerun()
    elif snapshot_result is not None and not snapshot_result.available:
        st.caption("Fast snapshot unavailable. Ask the DBA team to enable the summary facts for cheap control-room triage.")
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

    load_label = (
        "Load Full Detail Packet"
        if all_evidence_mode
        else "Load Investigation Detail"
        if investigation_mode
        else "Load Triage"
    )
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
    _render_enterprise_diagnostics_gate(company, environment)
    _render_production_readiness_gate(company, environment)
    _render_executive_scorecard_driver_gate(company, environment)
    _render_forecast_exception_gate(company, environment)
    _render_change_intelligence_gate(company, environment)
    _render_closed_loop_operations_gate(company, environment)
    _render_command_center_investigation_gate(company, environment)

    if st.button(load_label, key="dba_control_room_load", type="primary"):
        _load_control_room_evidence()

    data = st.session_state.get("dba_control_room_data", {})
    if st.session_state.get("dba_control_room_active_view") in {"Service Posture", "Admin Tools"}:
        st.divider()
        active_view = render_workflow_selector(
            "DBA Control Room view",
            "dba_control_room_active_view",
            DBA_CONTROL_ROOM_PANES,
            labels=DBA_CONTROL_ROOM_PANE_LABELS,
            columns=4,
        )
        if active_view == "Service Posture":
            _render_consolidated_service_posture()
            return
        if active_view == "Admin Tools":
            _render_admin_tools()
            return
    if not data:
        st.divider()
        active_view = render_workflow_selector(
            "DBA Control Room view",
            "dba_control_room_active_view",
            DBA_CONTROL_ROOM_PANES,
            labels=DBA_CONTROL_ROOM_PANE_LABELS,
            columns=4,
        )
        if active_view == "Service Posture":
            _render_consolidated_service_posture()
            return
        if active_view == "Admin Tools":
            _render_admin_tools()
            return
        if active_view == "Morning Brief":
            st.warning("Refresh the DBA Morning Brief to rank today's route priority and route handoff.")
            st.caption("Workflow: triage refresh -> route priority -> escalation status -> route handoff.")
            if st.button("Refresh DBA Morning Brief", key="dba_control_room_build_morning_from_empty", type="primary"):
                _load_control_room_evidence(status_label="Refreshing DBA Morning Brief", auto_build_ops=True)
                st.rerun()
        elif active_view == "Operations Detail":
            st.warning("Refresh the Operations Detail to see route priority, runbook, handoff, incident, and action queue detail.")
            st.caption("Workflow: triage refresh -> route priority -> routed action -> closure status.")
            if st.button("Refresh Operations Detail", key="dba_control_room_build_ops_from_empty", type="primary"):
                _load_control_room_evidence(status_label="Refreshing Operations Detail", auto_build_ops=True)
                st.rerun()
        else:
            st.warning(f"{load_label} to see today's DBA exceptions and exportable telemetry.")
            st.caption("Workflow: snapshot -> exception -> routed action -> telemetry export.")
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
    _render_dba_action_brief(
        release_gate_summary,
        exceptions,
        queued_queries=queued_queries,
        failed_queries=failed_queries,
    )
    _render_dba_command_intelligence_contract()

    st.divider()

    active_view = render_workflow_selector(
        "DBA Control Room view",
        "dba_control_room_active_view",
        DBA_CONTROL_ROOM_PANES,
        labels=DBA_CONTROL_ROOM_PANE_LABELS,
        columns=4,
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
            "Use Operations Detail when you need route priority, runbook, escalation, handoff, incident, or queue detail."
        )

    elif active_view == "Service Posture":
        _render_consolidated_service_posture()

    elif active_view == "Admin Tools":
        _render_admin_tools()

    elif active_view in {"Operations Detail", "Morning Brief"}:
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
            if active_view == "Morning Brief":
                st.caption("Refresh the DBA Morning Brief from route priority, escalation, handoff, incident, and action queue telemetry.")
                load_label = "Refresh DBA Morning Brief"
            else:
                st.caption("Refresh route priority, runbook, escalation, handoff, incident, and queue detail for the current scope.")
                load_label = "Refresh Operations Detail"
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

            if active_view == "Morning Brief":
                ops_detail = "Morning Brief"
                st.session_state["dba_operations_board_detail"] = ops_detail
            else:
                ops_detail = st.selectbox(
                    "Operations Detail",
                    ("Morning Brief", "Priority", "Runbook", "Escalations", "Handoff", "Incidents", "Advisors", "Queue"),
                    label_visibility="collapsed",
                    key="dba_operations_board_detail",
                )
            if ops_detail == "Morning Brief":
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
            elif ops_detail == "Incidents":
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
                if sel_wh and st.button("Open Cost & Contract", key="dba_control_room_open_wh"):
                    _jump("Cost & Contract", workflow="Recommendations and action queue", warehouse=sel_wh)
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
            st.write("Bill explanations, run-rate pacing, warehouse pressure, rightsizing, recommendations, and action telemetry.")
            for label, title, workflow in [
                ("Cost & Contract", "Cost & Contract", "Usage attribution and run-rate"),
                ("AI / Cortex Spend", "Cost & Contract", "AI and Cortex spend"),
                ("Warehouse Capacity", "Cost & Contract", "Recommendations and action queue"),
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
                st.download_button(
                    "Download Release Brief",
                    report,
                    file_name=f"overwatch_release_compare_{company}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                    mime="text/markdown",
                    key="dba_release_compare_report_download",
                )
        else:
            st.info("Choose release windows and run the comparison when you need post-change status.")
