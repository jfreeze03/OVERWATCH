"""Executive Landing admin and advanced rollup renderer."""
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from config import (
    ACTION_QUEUE_TABLE,
    ALERT_DB,
    ALERT_SCHEMA,
    DEFAULT_COMPANY,
    DEFAULT_DAY_WINDOW,
    DEFAULT_ENVIRONMENT,
    DEFAULTS,
    DAY_WINDOW_OPTIONS,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.navigation import apply_navigation_state, apply_section_workflow_navigation
from sections.shell_helpers import (
    render_escaped_bold_text,
    render_refresh_contract,
    render_shell_kpi_row,
    render_shell_snapshot,
    render_shell_status_strip,
)
from runtime_state import EXECUTIVE_LANDING_WORKFLOW
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_source_note


pd = lazy_pandas()

build_mart_cost_cockpit_sql = _lazy_util("build_mart_cost_cockpit_sql")
build_schema_migration_status_sql = _lazy_util("build_schema_migration_status_sql")
credits_to_dollars = _lazy_util("credits_to_dollars")
format_snowflake_error = _lazy_util("format_snowflake_error")
get_environment_label = _lazy_util("get_environment_label")
get_session_for_action = _lazy_util("get_session_for_action")
load_action_queue = _lazy_util("load_action_queue")
load_alert_history = _lazy_util("load_alert_history")
mart_object_name = _lazy_util("mart_object_name")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
build_loaded_section_alert_signal_board = _lazy_util("build_loaded_section_alert_signal_board")
load_enterprise_operating_rollups = _lazy_util("load_enterprise_operating_rollups")
load_change_intelligence_summary = _lazy_util("load_change_intelligence_summary")
load_closed_loop_summary = _lazy_util("load_closed_loop_summary")
load_command_center_summary = _lazy_util("load_command_center_summary")
load_executive_scorecard_summary = _lazy_util("load_executive_scorecard_summary")
load_executive_forecast_summary = _lazy_util("load_executive_forecast_summary")
load_production_readiness_summary = _lazy_util("load_production_readiness_summary")
render_workflow_selector = _lazy_util("render_workflow_selector")
run_query = _lazy_util("run_query")
safe_identifier = _lazy_util("safe_identifier")
snowflake_connection_known_unavailable = _lazy_util("snowflake_connection_known_unavailable")
sql_literal = _lazy_util("sql_literal")


from sections.executive_landing_contracts import *
from sections.executive_landing_charts import _render_executive_observability_board
from sections.executive_landing_data_health_view import _render_executive_data_health, _render_loaded_executive_alert_context
from sections.executive_landing_overview_view import _render_snapshot_prompt


def _render_executive_admin_advanced(
    company: str,
    environment: str,
    days: int,
    *,
    credit_price: float,
    board: pd.DataFrame,
    board_payload: dict,
    snapshot: dict | None,
    source_health: pd.DataFrame,
    summary: dict,
) -> bool:
    st.markdown("**Executive Admin / Advanced**")
    st.caption(
        "Scorecard formulas, value ledger, telemetry trust detail, production readiness, "
        "telemetry grids, and advanced validation live here instead of the default front door."
    )
    load = False
    if not isinstance(snapshot, dict):
        load = _render_snapshot_prompt(EXECUTIVE_ADMIN_WORKFLOW, summary, days)
    else:
        _render_executive_data_health(source_health)
        _render_loaded_executive_alert_context()
    with st.expander("Advanced observability charts and source grids", expanded=False):
        _render_executive_observability_board(
            board,
            board_payload,
            company=company,
            environment=environment,
            days=int(days),
            credit_price=credit_price,
        )
    _render_advanced_executive_rollups(company, environment, int(days))
    return load

def _render_enterprise_operating_model_summary(rollups: dict[str, pd.DataFrame]) -> None:
    """Render first-paint-safe leadership trust/value rollups."""
    trust = rollups.get("trust", pd.DataFrame())
    ownership = rollups.get("ownership", pd.DataFrame())
    value = rollups.get("value", pd.DataFrame())
    app = rollups.get("app", pd.DataFrame())

    trust_issues = 0
    trust_confidence = "fallback"
    if isinstance(trust, pd.DataFrame) and not trust.empty:
        status = trust.get("STATUS", pd.Series(dtype=str)).fillna("").astype(str)
        trust_issues = int((~status.eq("Ready")).sum())
        confidence = trust.get("CONFIDENCE", pd.Series(dtype=str)).dropna().astype(str).str.lower()
        trust_confidence = confidence.iloc[0] if not confidence.empty else "fallback"

    owner_gaps = 0
    if isinstance(ownership, pd.DataFrame) and not ownership.empty and "GAP_ITEMS" in ownership.columns:
        owner_gaps = safe_int(pd.to_numeric(ownership["GAP_ITEMS"], errors="coerce").fillna(0).sum())

    verified_savings = 0.0
    unverified_estimate = 0.0
    if isinstance(value, pd.DataFrame) and not value.empty:
        verified_savings = safe_float(pd.to_numeric(value.get("VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        unverified_estimate = safe_float(pd.to_numeric(value.get("UNVERIFIED_ESTIMATE_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())

    app_review = 0
    if isinstance(app, pd.DataFrame) and not app.empty:
        app_review = safe_int((~app.get("HEALTH_STATE", pd.Series(dtype=str)).fillna("").astype(str).eq("Ready")).sum())

    if all(
        not isinstance(frame, pd.DataFrame) or frame.empty
        for frame in (trust, ownership, value, app)
    ):
        st.caption("Enterprise operating model rollups are pending. Run the mart refresh to populate trust, ownership, value, and app health summaries.")
        return

    st.markdown("**Enterprise Operating Model**")
    render_shell_snapshot((
        ("Trust Issues", f"{trust_issues:,}"),
        ("Ownership Gaps", f"{owner_gaps:,}"),
        ("Verified Value", f"${verified_savings:,.0f}"),
        ("App Review", f"{app_review:,}"),
    ))
    st.caption(
        "Operating path: Finding -> Owner -> Trust Level -> Business Impact -> Action -> Value Verified. "
        f"Trust confidence: {trust_confidence}; unverified savings stay separate (${unverified_estimate:,.0f})."
    )
    with st.expander("Enterprise operating model rollups", expanded=trust_issues > 0 or owner_gaps > 0 or app_review > 0):
        if isinstance(trust, pd.DataFrame) and not trust.empty:
            trust_view = trust[[
                column for column in [
                    "SOURCE_NAME", "STATUS", "CONFIDENCE", "FRESHNESS_MINUTES",
                    "SOURCE_OBJECT", "OWNER_ROUTE", "BUSINESS_IMPACT", "NEXT_ACTION",
                ]
                if column in trust.columns
            ]].head(12)
            st.dataframe(trust_view, width="stretch", hide_index=True)
        if isinstance(ownership, pd.DataFrame) and not ownership.empty:
            ownership_view = ownership[[
                column for column in [
                    "SURFACE", "ENTITY_TYPE", "TOTAL_ITEMS", "ROUTED_ITEMS",
                    "GAP_ITEMS", "COVERAGE_PCT", "TRUST_LEVEL", "CONFIDENCE",
                    "OWNER_ROUTE", "NEXT_ACTION",
                ]
                if column in ownership.columns
            ]].head(12)
            st.dataframe(ownership_view, width="stretch", hide_index=True)
        if isinstance(value, pd.DataFrame) and not value.empty:
            value_view = value[[
                column for column in [
                    "STATUS", "OWNER_ROUTE", "EXPECTED_SAVINGS_USD",
                    "VERIFIED_SAVINGS_USD", "UNVERIFIED_ESTIMATE_USD",
                    "CONFIDENCE", "VALUE_STATE", "NEXT_ACTION",
                ]
                if column in value.columns
            ]].head(12)
            st.dataframe(value_view, width="stretch", hide_index=True)
        if isinstance(app, pd.DataFrame) and not app.empty:
            app_view = app[[
                column for column in [
                    "SECTION_NAME", "HEALTH_STATE", "P95_RENDER_MS",
                    "SLOW_SECTION_COUNT", "QUERY_FAILURE_COUNT",
                    "OVERWATCH_COST_USD", "VALIDATION_STATUS", "CONFIDENCE",
                    "NEXT_ACTION",
                ]
                if column in app.columns
            ]].head(12)
            st.dataframe(app_view, width="stretch", hide_index=True)

def _render_production_readiness_dashboard(readiness: pd.DataFrame) -> None:
    """Render Phase 2A compact production readiness from the summary mart."""
    if not isinstance(readiness, pd.DataFrame) or readiness.empty:
        st.caption("Production readiness summary is pending. Run the mart refresh to populate deployment, validation, privilege, refresh, config, and environment checks.")
        return

    row = readiness.iloc[0]
    status = str(row.get("VALIDATION_STATUS") or "Unknown")
    readiness_score = safe_int(row.get("READINESS_SCORE"), 0)
    missing_privileges = safe_int(row.get("MISSING_PRIVILEGES"), 0)
    failed_refreshes = safe_int(row.get("FAILED_MART_REFRESHES"), 0)
    missing_marts = safe_int(row.get("MISSING_SUMMARY_MARTS"), 0)
    stale_sources = safe_int(row.get("STALE_SOURCE_COUNT"), 0)
    config_drift = safe_int(row.get("CONFIG_DRIFT_COUNT"), 0)

    st.markdown("**Production Readiness**")
    render_shell_snapshot((
        ("Status", status),
        ("Score", f"{readiness_score}/100"),
        ("Missing Privileges", f"{missing_privileges:,}"),
        ("Failed Refreshes", f"{failed_refreshes:,}"),
        ("Missing Marts", f"{missing_marts:,}"),
    ))
    st.caption(
        f"Deployment {row.get('DEPLOYMENT_VERSION') or 'unknown'}; "
        f"last validation {row.get('LAST_VALIDATION_TS') or 'not recorded'}; "
        f"confidence {row.get('CONFIDENCE') or 'fallback'}."
    )
    with st.expander("Production readiness signals", expanded=status in {"Blocked", "Review"}):
        signal_rows = pd.DataFrame([
            {"SIGNAL": "Data freshness", "VALUE": stale_sources, "STATE": "Review" if stale_sources else "Ready"},
            {"SIGNAL": "Configuration drift", "VALUE": config_drift, "STATE": "Review" if config_drift else "Ready"},
            {"SIGNAL": "Environment readiness", "VALUE": row.get("ENVIRONMENT_READINESS") or "Unknown", "STATE": row.get("ENVIRONMENT_READINESS") or "Unknown"},
            {"SIGNAL": "Top risk", "VALUE": row.get("TOP_RISK") or "Production readiness checks are green.", "STATE": status},
            {"SIGNAL": "Next action", "VALUE": row.get("NEXT_ACTION") or "Keep validation current.", "STATE": status},
        ])
        st.dataframe(signal_rows, width="stretch", hide_index=True)

def _render_executive_scorecard_summary(scorecard: pd.DataFrame) -> None:
    """Render Phase 2B leadership scoring from the compact scorecard mart."""
    if not isinstance(scorecard, pd.DataFrame) or scorecard.empty:
        st.caption("Executive Scorecard is pending. Run the executive mart refresh to populate leadership health scores.")
        return

    work = scorecard.copy()
    status = work.get("STATUS", pd.Series(dtype=str)).fillna("Unknown").astype(str)
    trend = work.get("TREND", pd.Series(dtype=str)).fillna("Stable").astype(str)
    scores = pd.to_numeric(work.get("CURRENT_SCORE", pd.Series(dtype=float)), errors="coerce").fillna(0)
    risk_values = pd.to_numeric(work.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
    value_at_risk = safe_float(risk_values.sum())
    lowest_score = safe_float(scores.min()) if not scores.empty else 0.0
    red = safe_int(status.eq("Red").sum())
    yellow = safe_int(status.eq("Yellow").sum())
    worsening = safe_int(trend.str.contains("worsening", case=False, na=False).sum())
    work["_CURRENT_SCORE_SORT"] = scores
    work["_VALUE_RISK_SORT"] = risk_values
    top_row = work.sort_values(
        by=["_CURRENT_SCORE_SORT", "_VALUE_RISK_SORT"],
        ascending=[True, False],
        na_position="last",
    ).iloc[0]

    st.markdown("**Executive Scorecard**")
    render_shell_snapshot((
        ("Lowest Score", f"{lowest_score:.0f}/100"),
        ("Red", f"{red:,}"),
        ("Yellow", f"{yellow:,}"),
        ("Worsening", f"{worsening:,}"),
        ("Value/Risk", f"${value_at_risk:,.0f}"),
    ))
    st.caption(
        f"Top concern: {top_row.get('SCORE_NAME') or 'Executive score'} is "
        f"{top_row.get('STATUS') or 'Unknown'}; owner route "
        f"{top_row.get('OWNER_ROUTE') or 'Owner gap'}. "
        f"Action: {top_row.get('RECOMMENDED_ACTION') or 'Review score drivers'}."
    )
    view = work[[
        column for column in [
            "SCORE_NAME", "CURRENT_SCORE", "STATUS", "TREND", "TOP_DRIVER",
            "RECOMMENDED_ACTION", "OWNER_ROUTE", "OWNER_GAP", "VALUE_AT_RISK_USD",
            "CONFIDENCE", "LAST_REFRESHED_TS",
        ]
        if column in work.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)

def _format_forecast_value(value: object, unit: object) -> str:
    numeric = safe_float(value, 0.0)
    unit_label = str(unit or "").lower()
    if unit_label == "usd":
        return f"${numeric:,.0f}"
    if unit_label == "percent":
        return f"{numeric:,.1f}%"
    if unit_label == "tb":
        return f"{numeric:,.2f} TB"
    if unit_label == "seconds":
        return f"{numeric:,.0f}s"
    if unit_label == "count":
        return f"{numeric:,.0f}"
    return f"{numeric:,.2f}"

def _render_executive_forecast_summary(forecasts: pd.DataFrame) -> None:
    """Render Phase 2C compact forecasting from the summary mart."""
    if not isinstance(forecasts, pd.DataFrame) or forecasts.empty:
        st.caption("Executive Forecasting is pending. Run the executive mart refresh to populate leadership forecast rows.")
        return

    work = forecasts.copy()
    trend = work.get("TREND_DIRECTION", pd.Series(dtype=str)).fillna("Unknown").astype(str)
    confidence = work.get("CONFIDENCE", pd.Series(dtype=str)).fillna("Low").astype(str)
    risk_values = pd.to_numeric(work.get("VALUE_AT_RISK_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
    upward = safe_int(trend.eq("Up").sum())
    low_confidence = safe_int(confidence.eq("Low").sum())
    value_risk = safe_float(risk_values.sum())
    work["_RISK_SORT"] = risk_values
    work["_LOW_CONF_SORT"] = confidence.eq("Low").astype(int)
    top_row = work.sort_values(
        by=["_RISK_SORT", "_LOW_CONF_SORT"],
        ascending=[False, False],
        na_position="last",
    ).iloc[0]

    st.markdown("**Executive Forecasting**")
    render_shell_snapshot((
        ("Forecasts", f"{len(work):,}"),
        ("Trending Up", f"{upward:,}"),
        ("Low Confidence", f"{low_confidence:,}"),
        ("Value/Risk", f"${value_risk:,.0f}"),
    ))
    st.caption(
        f"Top forecast: {top_row.get('FORECAST_NAME') or 'Forecast'} "
        f"{_format_forecast_value(top_row.get('FORECAST_VALUE'), top_row.get('VALUE_UNIT'))}; "
        f"confidence {top_row.get('CONFIDENCE') or 'Low'}. "
        "Forecasts are heuristic estimates and are not counted as verified savings."
    )
    view = work[[
        column for column in [
            "FORECAST_NAME", "FORECAST_DOMAIN", "FORECAST_VALUE", "VALUE_UNIT",
            "CURRENT_ACTUAL", "PRIOR_PERIOD_VALUE", "TREND_DIRECTION",
            "CONFIDENCE", "MAIN_DRIVER", "RECOMMENDED_ACTION", "OWNER_ROUTE",
            "VALUE_AT_RISK_USD", "LAST_REFRESHED_TS",
        ]
        if column in work.columns
    ]].copy()
    if "FORECAST_VALUE" in view.columns and "VALUE_UNIT" in view.columns:
        view["FORECAST_DISPLAY"] = [
            _format_forecast_value(value, unit)
            for value, unit in zip(view["FORECAST_VALUE"], view["VALUE_UNIT"], strict=False)
        ]
    st.dataframe(view, width="stretch", hide_index=True)

def _render_change_intelligence_summary(changes: pd.DataFrame) -> None:
    """Render Phase 2D compact change-risk summary from the summary mart."""
    if not isinstance(changes, pd.DataFrame) or changes.empty:
        st.caption("Change Intelligence is pending. Run the executive mart refresh to populate recent change-risk rows.")
        return

    work = changes.copy()
    change_count = pd.to_numeric(work.get("CHANGE_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    high_risk = pd.to_numeric(work.get("HIGH_RISK_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    owner_gaps = pd.to_numeric(work.get("OWNER_GAP_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    correlations = pd.to_numeric(work.get("CORRELATION_CANDIDATE_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    work["_HIGH_RISK_SORT"] = high_risk
    work["_CHANGE_SORT"] = change_count
    top_row = work.sort_values(
        by=["_HIGH_RISK_SORT", "_CHANGE_SORT"],
        ascending=[False, False],
        na_position="last",
    ).iloc[0]

    st.markdown("**Change Intelligence**")
    render_shell_snapshot((
        ("Changes", f"{safe_int(change_count.sum()):,}"),
        ("High Risk", f"{safe_int(high_risk.sum()):,}"),
        ("Owner Gaps", f"{safe_int(owner_gaps.sum()):,}"),
        ("Possible Links", f"{safe_int(correlations.sum()):,}"),
    ))
    st.caption(
        f"Top change area: {top_row.get('CHANGE_CATEGORY') or top_row.get('CHANGE_TYPE') or 'Change'}; "
        f"latest object {top_row.get('TOP_OBJECT_NAME') or 'No recent changes'}. "
        "Related alerts are shown as possible correlations, not root-cause claims."
    )
    view = work[[
        column for column in [
            "CHANGE_CATEGORY", "CHANGE_TYPE", "CHANGE_COUNT", "HIGH_RISK_COUNT",
            "RELATED_ALERT_COUNT", "CORRELATION_CANDIDATE_COUNT", "LATEST_CHANGE_TS",
            "TOP_OBJECT_NAME", "TOP_CHANGED_BY", "RISK_LEVEL", "BUSINESS_IMPACT",
            "OWNER_ROUTE", "CONFIDENCE", "LAST_REFRESHED_TS",
        ]
        if column in work.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)

def _render_closed_loop_summary(actions: pd.DataFrame) -> None:
    """Render Phase 2E compact closed-loop action/value summary."""
    if not isinstance(actions, pd.DataFrame) or actions.empty:
        st.caption("Closed Loop Operations is pending. Run the executive mart refresh to populate action lifecycle rows.")
        return

    work = actions.copy()
    open_count = pd.to_numeric(work.get("OPEN_ACTION_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    approvals = pd.to_numeric(work.get("APPROVAL_REQUIRED_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    pending_verify = pd.to_numeric(work.get("VERIFICATION_PENDING_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0)
    verified_value = pd.to_numeric(work.get("ACTUAL_VERIFIED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
    expected_value = pd.to_numeric(work.get("EXPECTED_SAVINGS_USD", pd.Series(dtype=float)), errors="coerce").fillna(0)
    work["_ACTION_SORT"] = open_count + approvals + pending_verify
    work["_VALUE_SORT"] = expected_value
    top_row = work.sort_values(
        by=["_ACTION_SORT", "_VALUE_SORT"],
        ascending=[False, False],
        na_position="last",
    ).iloc[0]

    st.markdown("**Closed Loop Operations**")
    render_shell_snapshot((
        ("Open Actions", f"{safe_int(open_count.sum()):,}"),
        ("Need Approval", f"{safe_int(approvals.sum()):,}"),
        ("Verify", f"{safe_int(pending_verify.sum()):,}"),
        ("Verified Value", f"${safe_float(verified_value.sum()):,.0f}"),
    ))
    st.caption(
        f"Top action area: {top_row.get('ACTION_DOMAIN') or 'Actions'}; "
        f"{top_row.get('NEXT_ACTION') or 'Work actions through approval and verification.'} "
        "Expected savings stay separate from actual verified savings."
    )
    view = work[[
        column for column in [
            "ACTION_DOMAIN", "OPEN_ACTION_COUNT", "APPROVAL_REQUIRED_COUNT",
            "APPROVED_COUNT", "VERIFICATION_PENDING_COUNT", "VERIFIED_COUNT",
            "CLOSED_COUNT", "HIGH_RISK_COUNT", "OWNER_GAP_COUNT",
            "EXPECTED_SAVINGS_USD", "ACTUAL_VERIFIED_SAVINGS_USD",
            "UNVERIFIED_EXPECTED_USD", "TOP_FINDING", "NEXT_ACTION",
            "CONFIDENCE", "LAST_REFRESHED_TS",
        ]
        if column in work.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)

def _render_command_center_summary(findings: pd.DataFrame) -> None:
    """Render Phase 2F compact correlated-investigation summary from the summary mart."""
    if not isinstance(findings, pd.DataFrame) or findings.empty:
        st.caption("Correlated investigations are pending. Run the executive mart refresh to populate current findings.")
        return

    work = findings.copy()
    finding_count = pd.to_numeric(work.get("FINDING_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0).astype("float64")
    high_risk = pd.to_numeric(work.get("HIGH_RISK_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0).astype("float64")
    owner_gap = pd.to_numeric(work.get("OWNER_GAP_COUNT", pd.Series(dtype=float)), errors="coerce").fillna(0).astype("float64")
    expected_value = pd.to_numeric(work.get("EXPECTED_VALUE_USD", pd.Series(dtype=float)), errors="coerce").fillna(0).astype("float64")
    work["_SORT_VALUE"] = high_risk.mul(1_000_000.0).add(owner_gap.mul(10_000.0)).add(expected_value)
    top_row = work.sort_values("_SORT_VALUE", ascending=False, na_position="last").iloc[0]

    st.markdown("**Correlated Investigations**")
    render_shell_snapshot((
        ("Findings", f"{safe_int(finding_count.sum()):,}"),
        ("High Risk", f"{safe_int(high_risk.sum()):,}"),
        ("Owner Gaps", f"{safe_int(owner_gap.sum()):,}"),
        ("Value/Risk", f"${safe_float(expected_value.sum()):,.0f}"),
    ))
    st.caption(
        f"Top investigation: {top_row.get('INVESTIGATION_TYPE') or 'Correlated Investigation'}; "
        f"{top_row.get('TOP_RECOMMENDED_ACTION') or 'Load the DBA investigation workspace for evidence.'} "
        "Findings are deterministic root-cause candidates, not unverified causality claims."
    )
    view = work[[
        column for column in [
            "INVESTIGATION_TYPE", "QUESTION_TEXT", "FINDING_COUNT",
            "HIGH_RISK_COUNT", "OWNER_GAP_COUNT", "RELATED_CHANGE_COUNT",
            "RELATED_ALERT_COUNT", "RELATED_SCORECARD_COUNT",
            "RELATED_FORECAST_COUNT", "REVIEW_PLAN_COUNT",
            "EXPECTED_VALUE_USD", "TOP_ROOT_CAUSE_CANDIDATE",
            "TOP_EVIDENCE_SUMMARY", "TOP_RECOMMENDED_ACTION",
            "CONFIDENCE", "RISK_LEVEL", "LAST_REFRESHED_TS",
        ]
        if column in work.columns
    ]]
    st.dataframe(view, width="stretch", hide_index=True)

def _render_advanced_executive_rollups(company: str, environment: str, days: int) -> None:
    """Render enterprise rollups after the executive decision surface."""
    st.divider()
    with st.expander("Advanced executive rollups", expanded=False):
        _render_enterprise_operating_model_summary(
            load_enterprise_operating_rollups(company, environment, days=int(days))
        )
        _render_production_readiness_dashboard(
            load_production_readiness_summary(company, environment, days=int(days))
        )
        _render_executive_scorecard_summary(
            load_executive_scorecard_summary(company, environment, days=int(days))
        )
        _render_executive_forecast_summary(
            load_executive_forecast_summary(company, environment, days=int(days))
        )
        _render_change_intelligence_summary(
            load_change_intelligence_summary(company, environment, days=int(days))
        )
        _render_closed_loop_summary(
            load_closed_loop_summary(company, environment, days=int(days))
        )
        _render_command_center_summary(
            load_command_center_summary(company, environment, days=int(days))
        )

def render_executive_admin_advanced(*, summary: dict, company: str, environment: str, days: int, credit_price: float, board: pd.DataFrame, board_payload: dict, snapshot: dict | None, source_health: pd.DataFrame | None) -> bool:
    return _render_executive_admin_advanced(company, environment, int(days), credit_price=credit_price, board=board, board_payload=board_payload, snapshot=snapshot, source_health=source_health if isinstance(source_health, pd.DataFrame) else pd.DataFrame(), summary=summary)


__all__ = ['_render_executive_admin_advanced', '_render_enterprise_operating_model_summary', '_render_production_readiness_dashboard', '_render_executive_scorecard_summary', '_format_forecast_value', '_render_executive_forecast_summary', '_render_change_intelligence_summary', '_render_closed_loop_summary', '_render_command_center_summary', '_render_advanced_executive_rollups', 'render_executive_admin_advanced']
