# sections/cost_contract_evidence_panels.py - Advanced Cost & Contract evidence panels.
from __future__ import annotations

import streamlit as st

from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.cost_contract_intelligence import (
    _build_change_cost_correlation_board,
    _build_cost_spike_root_cause_board,
)
from sections.shell_helpers import render_shell_snapshot
from utils.primitives import safe_float, safe_int


pd = lazy_pandas()

load_change_correlation_detail = _lazy_util("load_change_correlation_detail")
load_closed_loop_verification_detail = _lazy_util("load_closed_loop_verification_detail")
load_command_center_finding_detail = _lazy_util("load_command_center_finding_detail")
load_command_center_recommendation_detail = _lazy_util("load_command_center_recommendation_detail")
load_executive_scorecard_detail = _lazy_util("load_executive_scorecard_detail")
load_forecast_detail = _lazy_util("load_forecast_detail")
load_value_ledger_detail = _lazy_util("load_value_ledger_detail")
load_value_ledger_rollup = _lazy_util("load_value_ledger_rollup")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _render_cost_spike_root_cause_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    credit_price: float,
) -> None:
    summary, board = _build_cost_spike_root_cause_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        credit_price=credit_price,
    )
    st.session_state["cost_contract_spike_root_cause_summary"] = summary
    st.session_state["cost_contract_spike_root_cause"] = board
    if board.empty:
        return
    st.markdown("**Cost Spike Root Cause Drilldown**")
    value_at_risk = safe_float(pd.to_numeric(board.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    render_shell_snapshot((
        ("Critical/High", f"{summary['critical_high']:,}"),
        ("Value at Risk", f"${value_at_risk:,.0f}"),
        ("Top Driver", summary["top_driver"]),
    ))
    render_priority_dataframe(
        board.rename(columns={"CONFIDENCE": "MEASUREMENT_BASIS"}),
        title="Cost root-cause candidates ranked by risk and value",
        priority_columns=[
            "SEVERITY", "DRIVER", "ENTITY", "ROOT_CAUSE_SIGNAL", "VALUE_AT_RISK_USD",
            "MEASUREMENT_BASIS", "TRUST", "EVIDENCE", "NEXT_ACTION", "PROOF_REQUIRED", "ROUTE",
        ],
        sort_by=["SEVERITY", "VALUE_AT_RISK_USD"],
        ascending=[True, False],
        raw_label="All cost root-cause candidate rows",
        height=340,
        max_rows=8,
    )


def _render_change_cost_correlation_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
) -> None:
    summary, board = _build_change_cost_correlation_board(
        cockpit=cockpit,
        run_rate=run_rate,
    )
    st.session_state["cost_contract_change_cost_summary"] = summary
    st.session_state["cost_contract_change_cost_correlation"] = board
    if board.empty:
        return
    st.markdown("**Change + Cost Correlation**")
    render_shell_snapshot((
        ("High", f"{summary['high']:,}"),
        ("Medium", f"{summary['medium']:,}"),
        ("Top Correlation", summary["top_correlation"]),
    ))
    render_priority_dataframe(
        board,
        title="Recent changes that may explain cost movement",
        priority_columns=[
            "SEVERITY", "CORRELATION", "ENTITY", "COST_SIGNAL", "CHANGE_SIGNAL",
            "EVIDENCE", "NEXT_ACTION", "PROOF_REQUIRED", "ROUTE",
        ],
        sort_by=["SEVERITY", "CORRELATION"],
        ascending=[True, True],
        raw_label="All change and cost correlation rows",
        height=300,
        max_rows=8,
    )


def _render_executive_value_ledger(company: str, environment: str) -> None:
    rollup = load_value_ledger_rollup(company, environment, days=35)
    if rollup is None or getattr(rollup, "empty", True):
        st.caption("Executive Value Ledger is pending. Refresh the enterprise operating model mart to separate verified value from estimates.")
    else:
        expected = safe_float(pd.to_numeric(rollup.get("EXPECTED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        verified = safe_float(pd.to_numeric(rollup.get("VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        unverified = safe_float(pd.to_numeric(rollup.get("UNVERIFIED_ESTIMATE_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        open_items = safe_int(pd.to_numeric(rollup.get("OPEN_ITEMS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        st.markdown("**Executive Value Ledger**")
        render_shell_snapshot((
            ("Verified Savings", f"${verified:,.0f}"),
            ("Expected Savings", f"${expected:,.0f}"),
            ("Unverified", f"${unverified:,.0f}"),
            ("Open Items", f"{open_items:,}"),
        ))
        st.caption("Only verified telemetry is counted as realized savings; estimates remain open value until the verification window closes.")
        st.dataframe(
            rollup[[
                column for column in [
                    "STATUS", "WORKFLOW_ROUTE", "EXPECTED_SAVINGS_USD",
                    "VERIFIED_SAVINGS_USD", "UNVERIFIED_ESTIMATE_USD",
                    "CONFIDENCE", "VALUE_STATE", "OPEN_ITEMS",
                    "VERIFIED_ITEMS", "NEXT_ACTION",
                ]
                if column in rollup.columns
            ]],
            width="stretch",
            hide_index=True,
        )

    if st.button("Load Value Ledger Detail", key="cost_contract_load_value_ledger_detail", width="stretch"):
        st.session_state["cost_contract_value_ledger_detail"] = load_value_ledger_detail(
            company,
            environment,
            days=180,
        )
        st.session_state["cost_contract_value_ledger_scope"] = (company, environment)

    detail = st.session_state.get("cost_contract_value_ledger_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("cost_contract_value_ledger_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No detailed value-ledger rows are available for this scope yet.")
        else:
            st.dataframe(
                detail[[
                    column for column in [
                        "SOURCE", "ITEM_ID", "FINDING", "ENTITY_TYPE", "ENTITY_NAME",
                        "ROUTE", "STATUS", "EXPECTED_SAVINGS_USD",
                        "ACTUAL_VERIFIED_SAVINGS_USD", "UNVERIFIED_ESTIMATE_USD",
                        "CONFIDENCE", "TRUST_LEVEL", "BUSINESS_IMPACT",
                        "ACTION_TAKEN", "SUPPORTING_SIGNAL",
                        "VERIFICATION_WINDOW_START", "VERIFICATION_WINDOW_END",
                        "VERIFIED_BY", "VERIFIED_AT", "ROLLBACK_NOTES",
                    ]
                    if column in detail.columns
                ]],
                width="stretch",
                hide_index=True,
            )


def _render_cost_efficiency_score_explanation(company: str, environment: str) -> None:
    """Expose Cost Efficiency Score drivers behind an explicit Load action."""
    st.markdown("**Cost Efficiency Score**")
    st.caption("Loads score drivers from the Executive Scorecard history. Estimates do not count as realized savings.")
    if st.button("Load Cost Efficiency Score Drivers", key="cost_contract_load_cost_score_drivers", width="stretch"):
        st.session_state["cost_contract_cost_score_detail"] = load_executive_scorecard_detail(
            company,
            environment,
            score_key="COST_EFFICIENCY",
            days=180,
        )
        st.session_state["cost_contract_cost_score_scope"] = (company, environment)

    detail = st.session_state.get("cost_contract_cost_score_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("cost_contract_cost_score_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No Cost Efficiency Score driver rows are available for this scope yet.")
            return
        latest = detail.iloc[0]
        render_shell_snapshot((
            ("Score", f"{safe_float(latest.get('CURRENT_SCORE')):.0f}/100"),
            ("Status", str(latest.get("STATUS") or "Unknown")),
            ("Trend", str(latest.get("TREND") or "Stable")),
            ("Value/Risk", f"${safe_float(latest.get('VALUE_AT_RISK_USD')):,.0f}"),
        ))
        render_priority_dataframe(
            detail,
            title="Cost Efficiency Score drivers",
            priority_columns=[
                "SNAPSHOT_TS", "CURRENT_SCORE", "STATUS", "TREND", "TOP_DRIVER",
                "RECOMMENDED_ACTION", "WORKFLOW_ROUTE", "VALUE_AT_RISK_USD",
                "CONFIDENCE", "SOURCE_OBJECTS", "LAST_REFRESHED_TS",
            ],
            sort_by=["SNAPSHOT_TS"],
            ascending=False,
            raw_label="All cost efficiency score history rows",
            height=260,
            max_rows=8,
        )


def _render_cost_forecast_detail(company: str, environment: str) -> None:
    """Expose Phase 2C cost forecasting evidence only behind Load."""
    st.markdown("**Cost Forecast Drivers**")
    st.caption("Loads forecast history from OVERWATCH_FORECAST_HISTORY. Forecasts are estimates and do not count as verified savings.")
    if st.button("Load Cost Forecast Drivers", key="cost_contract_load_forecast_drivers", width="stretch"):
        st.session_state["cost_contract_forecast_detail"] = load_forecast_detail(
            company,
            environment,
            forecast_keys=("EOM_SPEND", "EOQ_SPEND", "CONTRACT_BURN", "CREDIT_ANOMALY"),
            days=180,
        )
        st.session_state["cost_contract_forecast_scope"] = (company, environment)

    detail = st.session_state.get("cost_contract_forecast_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("cost_contract_forecast_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No cost forecast rows are available for this scope yet.")
            return
        upward = safe_int(detail.get("TREND_DIRECTION", pd.Series(dtype=str)).fillna("").astype(str).eq("Up").sum())
        low_confidence = safe_int(detail.get("CONFIDENCE", pd.Series(dtype=str)).fillna("").astype(str).eq("Low").sum())
        value_risk = safe_float(pd.to_numeric(detail.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        render_shell_snapshot((
            ("Rows", f"{len(detail):,}"),
            ("Trending Up", f"{upward:,}"),
            ("Low Confidence", f"{low_confidence:,}"),
            ("Value/Risk", f"${value_risk:,.0f}"),
        ))
        render_priority_dataframe(
            detail,
            title="Cost forecast drivers and methodology",
            priority_columns=[
                "SNAPSHOT_TS", "FORECAST_NAME", "FORECAST_VALUE", "VALUE_UNIT",
                "CURRENT_ACTUAL", "PRIOR_PERIOD_VALUE", "TREND_DIRECTION",
                "CONFIDENCE", "METHODOLOGY", "MAIN_DRIVER", "RECOMMENDED_ACTION",
                "WORKFLOW_ROUTE", "VALUE_AT_RISK_USD", "LAST_REFRESHED_TS",
            ],
            sort_by=["SNAPSHOT_TS", "FORECAST_KEY"],
            ascending=[False, True],
            raw_label="All cost forecast history rows",
            height=300,
            max_rows=12,
        )


def _render_cost_change_correlation(company: str, environment: str) -> None:
    """Expose cost-related possible change correlations behind Load."""
    st.markdown("**Cost Change Intelligence**")
    st.caption("Loads possible correlations between recent changes and cost/warehouse signals. This is timing evidence, not root cause.")
    if st.button("Load Cost-Related Changes", key="cost_contract_load_change_correlations", width="stretch"):
        st.session_state["cost_contract_change_correlation_detail"] = load_change_correlation_detail(
            company,
            environment,
            change_types=("WAREHOUSE_CHANGE", "OBJECT_CHANGE", "SECURITY_SENSITIVE_CHANGE"),
            correlation_types=("Cost",),
            days=180,
        )
        st.session_state["cost_contract_change_correlation_scope"] = (company, environment)

    detail = st.session_state.get("cost_contract_change_correlation_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("cost_contract_change_correlation_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No cost-related change correlations are available for this scope yet.")
            return
        render_priority_dataframe(
            detail,
            title="Possible cost correlations after changes",
            priority_columns=[
                "RELATED_TS", "CHANGE_TS", "CHANGE_TYPE", "OBJECT_NAME",
                "CHANGED_BY", "RELATED_SIGNAL", "RELATED_ENTITY",
                "CORRELATION_STRENGTH", "CORRELATION_LABEL", "EVIDENCE",
                "RISK_LEVEL", "WORKFLOW_ROUTE", "CONFIDENCE",
            ],
            sort_by=["RELATED_TS", "CHANGE_TS"],
            ascending=[False, False],
            raw_label="All cost-related change correlations",
            height=300,
            max_rows=10,
        )


def _render_savings_verification_workflow(company: str, environment: str) -> None:
    """Expose Phase 2E cost savings verification behind an explicit Load action."""
    st.markdown("**Savings Verification Workflow**")
    st.caption(
        "Loads post-action verification rows from closed-loop marts. "
        "Forecasted and expected savings remain separate from actual verified savings."
    )
    if st.button("Load Savings Verification", key="cost_contract_load_savings_verification", width="stretch"):
        st.session_state["cost_contract_savings_verification_detail"] = load_closed_loop_verification_detail(
            company,
            environment,
            domains=("Cost",),
            days=180,
        )
        st.session_state["cost_contract_savings_verification_scope"] = (company, environment)

    detail = st.session_state.get("cost_contract_savings_verification_detail")
    if (
        isinstance(detail, pd.DataFrame)
        and st.session_state.get("cost_contract_savings_verification_scope") == (company, environment)
    ):
        if detail.empty:
            st.info("No cost savings verification rows are available for this scope yet.")
            return
        expected = pd.to_numeric(detail.get("EXPECTED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        actual = pd.to_numeric(detail.get("ACTUAL_VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
        status = detail.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str)
        render_shell_snapshot((
            ("Expected", f"${safe_float(expected.sum()):,.0f}"),
            ("Verified", f"${safe_float(actual.sum()):,.0f}"),
            ("Unverified", f"${safe_float((expected - actual).clip(lower=0).sum()):,.0f}"),
            ("Pending", f"{safe_int((~status.isin(['Verified', 'Closed'])).sum()):,}"),
        ))
        render_priority_dataframe(
            detail,
            title="Savings verification workflow",
            priority_columns=[
                "ACTION_DOMAIN", "VERIFICATION_STATUS", "EXPECTED_SAVINGS_USD",
                "ACTUAL_VERIFIED_SAVINGS_USD", "VERIFICATION_WINDOW_START",
                "VERIFICATION_WINDOW_END", "VERIFICATION_STEPS", "VERIFIED_BY",
                "VERIFIED_AT", "EVIDENCE", "LAST_REFRESHED_TS",
            ],
            sort_by=["ACTUAL_VERIFIED_SAVINGS_USD", "EXPECTED_SAVINGS_USD", "LAST_REFRESHED_TS"],
            ascending=[False, False, False],
            raw_label="All savings verification rows",
            height=300,
            max_rows=10,
        )


def _render_cost_command_findings(company: str, environment: str) -> None:
    """Expose cost-spike correlated findings behind an explicit Load action."""
    st.markdown("**Cost Investigation Findings**")
    st.caption("Loads deterministic cost-spike root-cause candidates, evidence summaries, and review-gated recommendations.")
    types = ("Cost Spike",)
    if st.button("Load Cost Investigation Findings", key="cost_contract_load_command_center", width="stretch"):
        st.session_state["cost_contract_command_findings"] = load_command_center_finding_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["cost_contract_command_recommendations"] = load_command_center_recommendation_detail(
            company,
            environment,
            investigation_types=types,
            days=180,
        )
        st.session_state["cost_contract_command_scope"] = (company, environment)

    if st.session_state.get("cost_contract_command_scope") != (company, environment):
        return
    findings = st.session_state.get("cost_contract_command_findings")
    recommendations = st.session_state.get("cost_contract_command_recommendations")
    if isinstance(findings, pd.DataFrame):
        if findings.empty:
            st.info("No cost investigation findings are available for this scope yet.")
        else:
            render_priority_dataframe(
                findings,
                title="Cost-spike root-cause candidates",
                priority_columns=[
                    "QUESTION_TEXT", "ROOT_CAUSE_CANDIDATE", "CAUSALITY_LABEL",
                    "EVIDENCE_SUMMARY", "CONFIDENCE", "BUSINESS_IMPACT",
                    "WORKFLOW_ROUTE", "RELATED_CHANGES", "RELATED_ALERTS",
                    "RELATED_SCORECARD_DRIVERS", "RELATED_FORECASTS",
                    "RECOMMENDED_ACTION", "RISK_LEVEL", "EXECUTION_PLAN_REF",
                    "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "VERIFICATION_PATH",
                ],
                sort_by=["RISK_LEVEL", "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "LAST_REFRESHED_TS"],
                ascending=[True, False, False],
                raw_label="All cost investigation findings",
                height=300,
                max_rows=8,
            )
    if isinstance(recommendations, pd.DataFrame):
        if not recommendations.empty:
            render_priority_dataframe(
                recommendations,
                title="Cost investigation recommendations",
                priority_columns=[
                    "RECOMMENDED_ACTION", "RISK_LEVEL", "WORKFLOW_ROUTE",
                    "EXECUTION_PLAN_REF", "REVIEW_REQUIRED",
                    "EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "VERIFICATION_PATH",
                    "SAFETY_NOTE", "LAST_REFRESHED_TS",
                ],
                sort_by=["EXPECTED_SAVINGS_OR_RISK_AVOIDED_USD", "LAST_REFRESHED_TS"],
                ascending=[False, False],
                raw_label="All cost investigation recommendations",
                height=260,
                max_rows=6,
            )
