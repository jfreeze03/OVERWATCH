# sections/security_posture_admin_view.py - Advanced Security Monitoring evidence panels
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.security_posture_access_changes_view import _render_security_change_detail
from sections.security_posture_common import render_operator_briefing, render_workflow_guide
from sections.security_posture_models import _security_source_health_rows
from sections.shell_helpers import render_shell_snapshot
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note


pd = lazy_pandas()

load_closed_loop_execution_plan_detail = _lazy_util("load_closed_loop_execution_plan_detail")
load_closed_loop_workflow_detail = _lazy_util("load_closed_loop_workflow_detail")
load_command_center_finding_detail = _lazy_util("load_command_center_finding_detail")
load_command_center_recommendation_detail = _lazy_util("load_command_center_recommendation_detail")
load_executive_scorecard_detail = _lazy_util("load_executive_scorecard_detail")
load_ownership_coverage_rollup = _lazy_util("load_ownership_coverage_rollup")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _render_security_ownership_coverage(company: str, environment: str) -> None:
    coverage = load_ownership_coverage_rollup(
        company,
        environment,
        surface="Security Monitoring",
        days=35,
    )
    if coverage is None or getattr(coverage, "empty", True):
        st.caption("Security ownership coverage is pending. Refresh the enterprise operating model mart to show access route gaps.")
        return
    gaps = safe_int(pd.to_numeric(coverage.get("GAP_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    routed = safe_int(pd.to_numeric(coverage.get("ROUTED_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    confidence = str(coverage.get("CONFIDENCE", pd.Series(["estimated"])).fillna("estimated").astype(str).iloc[0])
    st.markdown("**Security Ownership Coverage**")
    render_shell_snapshot((
        ("Routed", f"{routed:,}"),
        ("Gaps", f"{gaps:,}"),
        ("Confidence", confidence),
    ))
    st.dataframe(
        coverage[[
            column for column in [
                "ENTITY_TYPE", "TOTAL_ITEMS", "ROUTED_ITEMS", "GAP_ITEMS",
                "COVERAGE_PCT", "TRUST_LEVEL", "CONFIDENCE", "TOP_GAP_ENTITY",
                "ROUTE", "NEXT_ACTION",
            ]
            if column in coverage.columns
        ]],
        width="stretch",
        hide_index=True,
    )


def _render_security_score_explanation(company: str, environment: str) -> None:
    """Expose Security Score drivers without loading full security detail."""
    st.markdown("**Security Score**")
    st.caption("Loads security score drivers from the Executive Scorecard history.")
    if st.button("Load Security Score Drivers", key="security_load_score_drivers", width="stretch"):
        st.session_state["security_scorecard_detail"] = load_executive_scorecard_detail(
            company,
            environment,
            score_key="SECURITY",
            days=180,
        )
        st.session_state["security_scorecard_scope"] = (company, environment)

    detail = st.session_state.get("security_scorecard_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("security_scorecard_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No Security Score driver rows are available for this scope yet.")
            return
        latest = detail.iloc[0]
        owner_gap = str(latest.get("OWNER_GAP") or "").strip().lower() in {"true", "1", "yes", "y"}
        render_shell_snapshot((
            ("Score", f"{safe_float(latest.get('CURRENT_SCORE')):.0f}/100"),
            ("Status", str(latest.get("STATUS") or "Unknown")),
            ("Trend", str(latest.get("TREND") or "Stable")),
            ("Owner Gap", "Yes" if owner_gap else "No"),
        ))
        render_priority_dataframe(
            detail,
            title="Security Score drivers",
            priority_columns=[
                "SNAPSHOT_TS", "CURRENT_SCORE", "STATUS", "TREND",
                "TOP_DRIVER", "RECOMMENDED_ACTION", "OWNER_ROUTE",
                "OWNER_GAP", "CONFIDENCE", "SOURCE_OBJECTS", "LAST_REFRESHED_TS",
            ],
            sort_by=["SNAPSHOT_TS"],
            ascending=False,
            raw_label="All security score history rows",
            height=260,
            max_rows=8,
        )


def _render_security_action_approval(company: str, environment: str) -> None:
    """Expose security action approval and review plans behind Load."""
    st.markdown("**Security Action Approval Workflow**")
    st.caption(
        "Loads security action workflows and review-only plans. "
        "Access changes remain approval-gated and are not executed from this screen."
    )
    domains = ("Security",)
    if st.button("Load Security Approvals", key="security_load_closed_loop_approvals", width="stretch"):
        st.session_state["security_closed_loop_workflow_detail"] = load_closed_loop_workflow_detail(
            company,
            environment,
            domains=domains,
            days=180,
        )
        st.session_state["security_closed_loop_execution_plan_detail"] = load_closed_loop_execution_plan_detail(
            company,
            environment,
            domains=domains,
            days=180,
        )
        st.session_state["security_closed_loop_scope"] = (company, environment)

    if st.session_state.get("security_closed_loop_scope") != (company, environment):
        return
    workflows = st.session_state.get("security_closed_loop_workflow_detail")
    execution_plans = st.session_state.get("security_closed_loop_execution_plan_detail")
    if isinstance(workflows, pd.DataFrame):
        if workflows.empty:
            st.info("No security action workflows are available for this scope yet.")
        else:
            render_priority_dataframe(
                workflows,
                title="Security action approval workflow",
                priority_columns=[
                    "FINDING", "ENTITY_TYPE", "ENTITY_NAME", "RISK_LEVEL",
                    "OWNER_ROUTE", "OWNER_GAP", "APPROVAL_STATUS",
                    "APPROVED_BY", "APPROVAL_TS", "EXECUTION_MODE",
                    "VERIFICATION_STATUS", "RECOMMENDED_ACTION",
                    "LAST_REFRESHED_TS",
                ],
                sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
                ascending=[True, False],
                raw_label="All security closed-loop workflow rows",
                height=300,
                max_rows=10,
            )
    if isinstance(execution_plans, pd.DataFrame):
        if execution_plans.empty:
            st.info("No security review plans are available for this scope yet.")
        else:
            render_priority_dataframe(
                execution_plans,
                title="Review-gated security SQL and action plans",
                priority_columns=[
                    "EXECUTION_MODE", "EXECUTION_STATUS", "DANGEROUS_ACTION_FLAG",
                    "EXECUTION_ALLOWED_IN_APP", "REVIEW_SQL_TEXT",
                    "REVIEW_ACTION_TEXT", "ROLLBACK_GUIDANCE",
                    "VERIFICATION_STEPS", "LAST_REFRESHED_TS",
                ],
                sort_by=["DANGEROUS_ACTION_FLAG", "LAST_REFRESHED_TS"],
                ascending=[False, False],
                raw_label="All security closed-loop execution plans",
                height=280,
                max_rows=8,
            )


def _render_security_command_findings(company: str, environment: str) -> None:
    """Expose security-risk correlated findings behind an explicit Load."""
    st.markdown("**Security Investigation Findings**")
    st.caption("Loads security-risk root-cause candidates, owner gaps, related changes, and review-gated recommendations.")
    types = ("Security Risk",)
    if st.button("Load Security Investigation Findings", key="security_load_command_center", width="stretch"):
        st.session_state["security_command_findings"] = load_command_center_finding_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["security_command_recommendations"] = load_command_center_recommendation_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["security_command_scope"] = (company, environment)

    if st.session_state.get("security_command_scope") != (company, environment):
        return
    findings = st.session_state.get("security_command_findings")
    recommendations = st.session_state.get("security_command_recommendations")
    if isinstance(findings, pd.DataFrame):
        if findings.empty:
            st.info("No security investigation findings are available for this scope yet.")
        else:
            render_priority_dataframe(
                findings,
                title="Security root-cause candidates",
                priority_columns=[
                    "QUESTION_TEXT", "ROOT_CAUSE_CANDIDATE", "CAUSALITY_LABEL",
                    "EVIDENCE_SUMMARY", "CONFIDENCE", "BUSINESS_IMPACT",
                    "OWNER_ROUTE", "OWNER_GAP", "RELATED_CHANGES",
                    "RELATED_ALERTS", "RELATED_SCORECARD_DRIVERS",
                    "RECOMMENDED_ACTION", "RISK_LEVEL", "EXECUTION_PLAN_REF",
                    "VERIFICATION_PATH",
                ],
                sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
                ascending=[True, False],
                raw_label="All security investigation findings",
                height=300,
                max_rows=8,
            )
    if isinstance(recommendations, pd.DataFrame) and not recommendations.empty:
        render_priority_dataframe(
            recommendations,
            title="Security command recommendations",
            priority_columns=[
                "RECOMMENDED_ACTION", "RISK_LEVEL", "OWNER_ROUTE",
                "EXECUTION_PLAN_REF", "REVIEW_REQUIRED", "VERIFICATION_PATH",
                "SAFETY_NOTE", "LAST_REFRESHED_TS",
            ],
            sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
            ascending=[True, False],
            raw_label="All security command recommendations",
            height=260,
            max_rows=6,
        )


def _render_advanced_security_evidence(
    company: str,
    environment: str,
    *,
    skip_change_detail: bool = True,
) -> None:
    """Render security evidence after the active security workflow."""
    st.divider()
    with st.expander("Advanced security evidence and workflow guide", expanded=False):
        render_operator_briefing(
            [
                ("First move", "Separate noisy login volume from real identity or access risk."),
                ("Telemetry", "Tie users, IPs, grants, MFA posture, and shared data to source detail."),
                ("Control", "Escalate to IAM, revoke/narrow access, or validate business route."),
                ("Output", "Produce an audit posture brief with routes and remediation status."),
            ],
            columns=4,
        )
        render_workflow_guide(
            "Start with identity/access posture, open privilege sprawl for high-risk grants, "
            "then inspect data sharing when the question is external exposure or audit telemetry.",
            [
                ("Login failures, MFA, grants, or risky access", "Use Failed Logins."),
                ("Admin roles, ownership, grant option, or route blockers", "Use Privilege Sprawl."),
                ("External consumers or shared data exposure", "Use Data Sharing Exposure."),
            ],
        )
        _render_security_ownership_coverage(company, environment)
        _render_security_score_explanation(company, environment)
        if not skip_change_detail:
            _render_security_change_detail(company, environment)
        _render_security_action_approval(company, environment)
        _render_security_command_findings(company, environment)


def _render_security_source_health(company: str, environment: str) -> None:
    source_health = _security_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Security Data Health", expanded=False):
        current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        fast_summary = int(
            source_health[
                source_health["STATE"].isin(["Loaded", "No Rows"])
                & source_health["CONFIDENCE"].astype(str).str.contains("Fast summary", case=False, regex=False)
            ].shape[0]
        )
        render_shell_snapshot((
            ("Current Surfaces", f"{current}/{len(source_health)}"),
            ("Fast Summary", f"{fast_summary:,}"),
            ("Stale", f"{stale:,}"),
            ("Unavailable", f"{unavailable:,}"),
        ))
        defer_source_note(
            "Use this before acting on access findings. Login-only telemetry keeps account scope, while database-scoped "
            "telemetry follows the selected company and environment."
        )
        render_priority_dataframe(
            source_health,
            title="Security telemetry freshness",
            priority_columns=[
                "SURFACE", "STATE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All security data-health rows",
            height=300,
        )


__all__ = [
    "_render_security_ownership_coverage",
    "_render_security_score_explanation",
    "_render_security_action_approval",
    "_render_security_command_findings",
    "_render_advanced_security_evidence",
    "_render_security_source_health",
]
