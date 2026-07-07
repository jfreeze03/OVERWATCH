"""Advanced Alert Center diagnostics renderer."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.shell_helpers import render_shell_snapshot
from utils.workflows import render_priority_dataframe


def _render_operational_ownership_coverage(company: str, environment: str) -> None:
    from utils import load_ownership_coverage_rollup

    coverage = load_ownership_coverage_rollup(
        company,
        environment,
        surface="Alert Center",
        days=35,
    )
    if coverage is None or getattr(coverage, "empty", True):
        st.caption("Operational workflow route coverage is pending. Refresh the enterprise operating model mart to show alert route gaps.")
        return
    total = int(pd.to_numeric(coverage.get("TOTAL_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    gaps = int(pd.to_numeric(coverage.get("GAP_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    routed = int(pd.to_numeric(coverage.get("ROUTED_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    st.markdown("**Operational Ownership Coverage**")
    render_shell_snapshot((
        ("Alert Items", f"{total:,}"),
        ("Routed", f"{routed:,}"),
        ("Gaps", f"{gaps:,}"),
    ))
    view = coverage[[
        column for column in [
            "ENTITY_TYPE", "TOTAL_ITEMS", "ROUTED_ITEMS", "GAP_ITEMS",
            "COVERAGE_PCT", "TRUST_LEVEL", "CONFIDENCE", "TOP_GAP_ENTITY",
            "ROUTE", "NEXT_ACTION",
        ]
        if column in coverage.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)


def _render_operational_risk_score_explanation(company: str, environment: str) -> None:
    """Expose Operational Risk Score drivers behind an explicit Load action."""
    from utils import load_executive_scorecard_detail

    st.markdown("**Operational Risk Score**")
    st.caption("Loads alert/action ownership risk drivers from the Executive Scorecard history.")
    if st.button("Load Operational Risk Score Drivers", key="alert_center_load_operational_score_drivers", width="stretch"):
        st.session_state["alert_center_operational_score_detail"] = load_executive_scorecard_detail(
            company,
            environment,
            score_key="OPERATIONAL_RISK",
            days=180,
        )
        st.session_state["alert_center_operational_score_scope"] = (company, environment)

    detail = st.session_state.get("alert_center_operational_score_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("alert_center_operational_score_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No Operational Risk Score driver rows are available for this scope yet.")
            return
        latest = detail.iloc[0]
        score = float(pd.to_numeric(pd.Series([latest.get("CURRENT_SCORE")]), errors="coerce").fillna(0).iloc[0])
        render_shell_snapshot((
            ("Score", f"{score:.0f}/100"),
            ("Status", str(latest.get("STATUS") or "Unknown")),
            ("Trend", str(latest.get("TREND") or "Stable")),
            ("Owner", str(latest.get("WORKFLOW_ROUTE") or "Owner gap")),
        ))
        render_priority_dataframe(
            detail,
            title="Operational Risk Score drivers",
            priority_columns=[
                "SNAPSHOT_TS", "CURRENT_SCORE", "STATUS", "TREND", "TOP_DRIVER",
                "RECOMMENDED_ACTION", "WORKFLOW_ROUTE", "WORKFLOW_GAP",
                "CONFIDENCE", "SOURCE_OBJECTS", "LAST_REFRESHED_TS",
            ],
            sort_by=["SNAPSHOT_TS"],
            ascending=False,
            raw_label="All operational risk score history rows",
            height=260,
            max_rows=8,
        )


def _render_alert_change_context(company: str, environment: str) -> None:
    """Show change correlations near Alert Center context without claiming causality."""
    from utils import load_change_correlation_detail

    st.markdown("**Related Changes**")
    st.caption("Loads possible change correlations for alert, cost, security, and workload signals.")
    if st.button("Load Related Changes", key="alert_center_load_related_changes", width="stretch"):
        st.session_state["alert_center_change_correlation_detail"] = load_change_correlation_detail(
            company,
            environment,
            correlation_types=("Alert", "Cost", "Security", "Workload"),
            days=180,
        )
        st.session_state["alert_center_change_scope"] = (company, environment)

    detail = st.session_state.get("alert_center_change_correlation_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("alert_center_change_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No related change correlations are available for this scope yet.")
            return
        render_shell_snapshot((
            ("Possible Links", f"{len(detail):,}"),
            ("High Risk", f"{int(pd.Series(detail.get('RISK_LEVEL', [])).astype(str).isin(['Critical', 'High']).sum()):,}"),
            ("Signals", f"{int(pd.Series(detail.get('RELATED_SIGNAL', [])).dropna().nunique()):,}"),
        ))
        render_priority_dataframe(
            detail,
            title="Related changes and possible correlations",
            priority_columns=[
                "RELATED_TS", "CORRELATION_TYPE", "CHANGE_TYPE", "OBJECT_TYPE",
                "OBJECT_NAME", "CHANGED_BY", "RELATED_SIGNAL", "RELATED_ENTITY",
                "CORRELATION_LABEL", "RISK_LEVEL", "BUSINESS_IMPACT",
                "WORKFLOW_ROUTE", "CONFIDENCE", "EVIDENCE",
            ],
            sort_by=["RELATED_TS", "CHANGE_TS"],
            ascending=False,
            raw_label="All related change correlation rows",
            height=320,
            max_rows=12,
        )
        st.caption("These rows are timing and entity matches only. Treat them as possible correlations until evidence proves causality.")


def _render_alert_action_workflows(company: str, environment: str) -> None:
    """Show alert/incident action workflows only after the operator loads them."""
    from utils import load_closed_loop_workflow_detail

    st.markdown("**Alert Action Workflows**")
    st.caption(
        "Loads action workflows tied to alert and incident context. "
        "Recommended SQL/action text remains review-gated and is not executed from Alert Center."
    )
    domains = ("Alert", "Cost", "Operations", "Security", "Workload")
    if st.button("Load Alert Action Workflows", key="alert_center_load_closed_loop_workflows", width="stretch"):
        st.session_state["alert_center_closed_loop_workflows"] = load_closed_loop_workflow_detail(
            company,
            environment,
            domains=domains,
            days=180,
        )
        st.session_state["alert_center_closed_loop_scope"] = (company, environment)

    detail = st.session_state.get("alert_center_closed_loop_workflows")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("alert_center_closed_loop_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No alert action workflows are available for this scope yet.")
            return
        status = detail.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str)
        approval = detail.get("APPROVAL_STATUS", pd.Series(dtype=str)).fillna("").astype(str)
        actual = pd.to_numeric(detail.get("ACTUAL_VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        render_shell_snapshot((
            ("Actions", f"{len(detail):,}"),
            ("Need Approval", f"{int((~approval.isin(['Approved', 'Not Required'])).sum()):,}"),
            ("Verify", f"{int((~status.isin(['Verified', 'Closed'])).sum()):,}"),
            ("Verified Value", f"${float(actual.sum()):,.0f}"),
        ))
        render_priority_dataframe(
            detail,
            title="Alert and incident action workflows",
            priority_columns=[
                "ACTION_DOMAIN", "FINDING", "SOURCE_TELEMETRY", "ENTITY_TYPE",
                "ENTITY_NAME", "RISK_LEVEL", "WORKFLOW_ROUTE", "APPROVAL_STATUS",
                "EXECUTION_MODE", "VERIFICATION_STATUS", "EXPECTED_SAVINGS_USD",
                "ACTUAL_VERIFIED_SAVINGS_USD", "RECOMMENDED_ACTION",
                "LAST_REFRESHED_TS",
            ],
            sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
            ascending=[True, False],
            raw_label="All alert closed-loop workflow rows",
            height=320,
            max_rows=12,
        )


def _render_alert_command_findings(company: str, environment: str) -> None:
    """Show related correlated findings for alert context."""
    from utils import load_command_center_finding_detail, load_command_center_recommendation_detail

    st.markdown("**Alert Investigation Findings**")
    st.caption(
        "Loads command findings tied to alerts, failures, cost, security, workload, and possible change correlations. "
        "Recommendations remain review-gated."
    )
    types = ("Failure / SLA", "Cost Spike", "Warehouse Slow", "Security Risk", "Recent Change")
    if st.button("Load Alert Investigation Findings", key="alert_center_load_command_findings", width="stretch"):
        st.session_state["alert_center_command_findings"] = load_command_center_finding_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["alert_center_command_recommendations"] = load_command_center_recommendation_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["alert_center_command_scope"] = (company, environment)

    if st.session_state.get("alert_center_command_scope") != (company, environment):
        return
    findings = st.session_state.get("alert_center_command_findings")
    recommendations = st.session_state.get("alert_center_command_recommendations")
    if isinstance(findings, pd.DataFrame):
        if findings.empty:
            st.info("No alert-related correlated investigation findings are available for this scope yet.")
        else:
            render_priority_dataframe(
                findings,
                title="Alert-related root-cause candidates",
                priority_columns=[
                    "INVESTIGATION_TYPE", "QUESTION_TEXT", "ROOT_CAUSE_CANDIDATE",
                    "CAUSALITY_LABEL", "EVIDENCE_SUMMARY", "CONFIDENCE",
                    "WORKFLOW_ROUTE", "RELATED_CHANGES", "RELATED_ALERTS",
                    "RELATED_SCORECARD_DRIVERS", "RELATED_FORECASTS",
                    "RECOMMENDED_ACTION", "RISK_LEVEL", "EXECUTION_PLAN_REF",
                    "VERIFICATION_PATH", "LAST_REFRESHED_TS",
                ],
                sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
                ascending=[True, False],
                raw_label="All alert investigation findings",
                height=320,
                max_rows=10,
            )
    if isinstance(recommendations, pd.DataFrame) and not recommendations.empty:
        render_priority_dataframe(
            recommendations,
            title="Alert investigation recommendations",
            priority_columns=[
                "INVESTIGATION_TYPE", "RECOMMENDED_ACTION", "RISK_LEVEL",
                "WORKFLOW_ROUTE", "EXECUTION_PLAN_REF", "REVIEW_REQUIRED",
                "VERIFICATION_PATH", "SAFETY_NOTE", "LAST_REFRESHED_TS",
            ],
            sort_by=["RISK_LEVEL", "LAST_REFRESHED_TS"],
            ascending=[True, False],
            raw_label="All alert investigation recommendations",
            height=260,
            max_rows=8,
        )


def _render_advanced_alert_diagnostics(company: str, environment: str) -> None:
    """Render alert diagnostics after the active alert workflow."""
    st.divider()
    if not st.session_state.get("alert_center_show_advanced_diagnostics"):
        if st.button("Show Advanced Alert Diagnostics", key="alert_center_show_advanced_diagnostics", width="stretch"):
            st.session_state["alert_center_show_advanced_diagnostics"] = True
        else:
            st.caption("Advanced alert diagnostics stay unloaded until requested.")
            return
    with st.expander("Advanced alert diagnostics and enterprise evidence", expanded=False):
        _render_operational_ownership_coverage(company, environment)
        _render_operational_risk_score_explanation(company, environment)
        _render_alert_change_context(company, environment)
        _render_alert_action_workflows(company, environment)
        _render_alert_command_findings(company, environment)


render_advanced_alert_diagnostics = _render_advanced_alert_diagnostics
