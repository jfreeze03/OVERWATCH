# sections/cost_contract.py - Consolidated cost and contract workflow
from __future__ import annotations

import pandas as pd
import streamlit as st
from utils import (
    build_cost_savings_verification_health_sql,
    build_cost_savings_verification_sql,
    build_mart_cost_cockpit_sql,
    build_mart_cost_run_rate_sql,
    credits_to_dollars,
    format_snowflake_error,
    get_active_company,
    get_credit_price,
    get_session_for_action,
    get_wh_filter_clause,
    load_action_queue,
    run_query,
    safe_float,
    safe_int,
)
from utils.workflows import (
    render_operator_briefing,
    render_priority_dataframe,
    render_signal_confidence,
    render_workflow_module,
    render_workflow_guide,
    render_workflow_selector,
)

WORKFLOWS = (
    "Explain bill / attribution / contract",
    "Recommendations and action queue",
    "Snowflake value log",
    "AI and Cortex spend",
    "SPCS spend",
)

WORKFLOW_DETAILS = {
    "Explain bill / attribution / contract": "Start here: bill movement, chargeback, contract pacing, and cost drivers.",
    "Recommendations and action queue": "Owned fixes with severity, proof, savings, and status.",
    "Snowflake value log": "Evidence that DBA changes avoided spend or improved service.",
    "AI and Cortex spend": "Cortex usage, model spend, users, and runaway AI cost signals.",
    "SPCS spend": "Snowpark Container Services usage and service cost exposure.",
}

WORKFLOW_MODULES = {
    "Explain bill / attribution / contract": "sections.cost_center",
    "Recommendations and action queue": "sections.recommendations",
    "Snowflake value log": "sections.snowflake_value",
    "AI and Cortex spend": "sections.cortex_monitor",
    "SPCS spend": "sections.spcs_tracker",
}


def _cost_score(current_credits: float, prior_credits: float, open_actions: int, high_actions: int, cortex_exceptions: int) -> int:
    delta_pct = ((safe_float(current_credits) - safe_float(prior_credits)) / safe_float(prior_credits) * 100) if safe_float(prior_credits) > 0 else 0.0
    penalty = (
        min(max(delta_pct, 0) / 2, 24)
        + min(safe_int(open_actions) * 1.5, 18)
        + min(safe_int(high_actions) * 5, 28)
        + min(safe_int(cortex_exceptions) * 4, 22)
    )
    return max(0, min(100, int(round(100 - penalty))))


def _cost_rating(score: int) -> str:
    if score >= 92:
        return "Controlled"
    if score >= 82:
        return "Watch"
    if score >= 70:
        return "Pressure"
    return "Cost Incident"


def _build_cost_cockpit_sql(company: str, days: int) -> str:
    wh_filter = get_wh_filter_clause("warehouse_name", company)
    return f"""
    WITH current_period AS (
        SELECT
            warehouse_name,
            SUM(COALESCE(credits_used, 0)) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          AND start_time < CURRENT_TIMESTAMP()
          {wh_filter}
        GROUP BY warehouse_name
    ),
    prior_period AS (
        SELECT
            warehouse_name,
            SUM(COALESCE(credits_used, 0)) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE start_time >= DATEADD('day', -{int(days) * 2}, CURRENT_TIMESTAMP())
          AND start_time < DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())
          {wh_filter}
        GROUP BY warehouse_name
    ),
    deltas AS (
        SELECT
            COALESCE(c.warehouse_name, p.warehouse_name) AS warehouse_name,
            COALESCE(c.credits, 0) AS current_credits,
            COALESCE(p.credits, 0) AS prior_credits,
            COALESCE(c.credits, 0) - COALESCE(p.credits, 0) AS credit_delta
        FROM current_period c
        FULL OUTER JOIN prior_period p
            ON c.warehouse_name = p.warehouse_name
    )
    SELECT
        SUM(current_credits) AS current_credits,
        SUM(prior_credits) AS prior_credits,
        COUNT_IF(current_credits > 0) AS active_warehouses,
        MAX_BY(warehouse_name, credit_delta) AS top_increase_warehouse,
        MAX(credit_delta) AS top_increase_credits
    FROM deltas
    """


def _build_cost_run_rate_sql(company: str) -> str:
    """Build live fallback SQL for complete-day 7d/30d run-rate and YOY cost trend."""
    wh_filter = get_wh_filter_clause("warehouse_name", company)
    return f"""
    WITH bounds AS (
        SELECT
            DATE_TRUNC('DAY', CURRENT_TIMESTAMP()) AS today_start,
            DATEADD('DAY', -7, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS current_7d_start,
            DATEADD('DAY', -30, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS current_30d_start,
            DATEADD('YEAR', -1, DATEADD('DAY', -7, DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))) AS yoy_7d_start,
            DATEADD('YEAR', -1, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS yoy_7d_end,
            DATEADD('YEAR', -1, DATEADD('DAY', -30, DATE_TRUNC('DAY', CURRENT_TIMESTAMP()))) AS yoy_30d_start,
            DATEADD('YEAR', -1, DATE_TRUNC('DAY', CURRENT_TIMESTAMP())) AS yoy_30d_end
    ),
    metering AS (
        SELECT
            start_time AS usage_ts,
            warehouse_name,
            COALESCE(credits_used, 0) AS credits_used
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY, bounds
        WHERE start_time >= yoy_30d_start
          AND start_time < today_start
          {wh_filter}
    ),
    aggregate_trend AS (
        SELECT
            SUM(IFF(usage_ts >= current_7d_start AND usage_ts < today_start, credits_used, 0)) AS credits_7d,
            SUM(IFF(usage_ts >= current_30d_start AND usage_ts < today_start, credits_used, 0)) AS credits_30d,
            SUM(IFF(usage_ts >= yoy_7d_start AND usage_ts < yoy_7d_end, credits_used, 0)) AS yoy_7d_credits,
            SUM(IFF(usage_ts >= yoy_30d_start AND usage_ts < yoy_30d_end, credits_used, 0)) AS yoy_30d_credits,
            COUNT(DISTINCT IFF(usage_ts >= current_7d_start AND usage_ts < today_start, TO_DATE(usage_ts), NULL)) AS observed_days_7d,
            COUNT(DISTINCT IFF(usage_ts >= current_30d_start AND usage_ts < today_start, TO_DATE(usage_ts), NULL)) AS observed_days_30d,
            COUNT(DISTINCT IFF(usage_ts >= yoy_7d_start AND usage_ts < yoy_7d_end, TO_DATE(usage_ts), NULL)) AS yoy_days_7d,
            COUNT(DISTINCT IFF(usage_ts >= yoy_30d_start AND usage_ts < yoy_30d_end, TO_DATE(usage_ts), NULL)) AS yoy_days_30d
        FROM metering, bounds
    ),
    warehouse_yoy AS (
        SELECT
            warehouse_name,
            SUM(IFF(usage_ts >= current_7d_start AND usage_ts < today_start, credits_used, 0)) AS current_7d_credits,
            SUM(IFF(usage_ts >= yoy_7d_start AND usage_ts < yoy_7d_end, credits_used, 0)) AS yoy_7d_credits
        FROM metering, bounds
        GROUP BY warehouse_name
    ),
    top_yoy AS (
        SELECT
            warehouse_name AS top_yoy_increase_warehouse,
            current_7d_credits - yoy_7d_credits AS top_yoy_increase_credits
        FROM warehouse_yoy
        WHERE current_7d_credits > 0 OR yoy_7d_credits > 0
        QUALIFY ROW_NUMBER() OVER (
            ORDER BY current_7d_credits - yoy_7d_credits DESC, current_7d_credits DESC
        ) = 1
    )
    SELECT
        ROUND(COALESCE(a.credits_7d, 0), 4) AS credits_7d,
        ROUND(COALESCE(a.credits_7d, 0) / 7, 4) AS avg_daily_7d,
        ROUND(COALESCE(a.credits_30d, 0), 4) AS credits_30d,
        ROUND(COALESCE(a.credits_30d, 0) / 30, 4) AS avg_daily_30d,
        ROUND((COALESCE(a.credits_7d, 0) / 7) * 30, 4) AS projected_30d_from_7d,
        ROUND(COALESCE(a.yoy_7d_credits, 0), 4) AS yoy_7d_credits,
        ROUND(COALESCE(a.yoy_30d_credits, 0), 4) AS yoy_30d_credits,
        a.observed_days_7d,
        a.observed_days_30d,
        a.yoy_days_7d,
        a.yoy_days_30d,
        CASE
            WHEN COALESCE(a.credits_30d, 0) = 0 THEN NULL
            ELSE ROUND(((COALESCE(a.credits_7d, 0) / 7) - (a.credits_30d / 30)) / NULLIF(a.credits_30d / 30, 0) * 100, 2)
        END AS pct_vs_30d_avg,
        CASE
            WHEN a.yoy_days_7d < 5 OR COALESCE(a.yoy_7d_credits, 0) = 0 THEN NULL
            ELSE ROUND((COALESCE(a.credits_7d, 0) - a.yoy_7d_credits) / NULLIF(a.yoy_7d_credits, 0) * 100, 2)
        END AS yoy_7d_pct,
        CASE
            WHEN a.yoy_days_30d < 20 OR COALESCE(a.yoy_30d_credits, 0) = 0 THEN NULL
            ELSE ROUND((COALESCE(a.credits_30d, 0) - a.yoy_30d_credits) / NULLIF(a.yoy_30d_credits, 0) * 100, 2)
        END AS yoy_30d_pct,
        CASE
            WHEN COALESCE(a.credits_30d, 0) = 0 THEN 'No 30-day baseline'
            WHEN ((COALESCE(a.credits_7d, 0) / 7) - (a.credits_30d / 30)) / NULLIF(a.credits_30d / 30, 0) >= 0.15 THEN 'Accelerating'
            WHEN ((COALESCE(a.credits_7d, 0) / 7) - (a.credits_30d / 30)) / NULLIF(a.credits_30d / 30, 0) <= -0.15 THEN 'Cooling'
            ELSE 'Stable'
        END AS run_rate_state,
        CASE
            WHEN a.yoy_days_7d < 5 THEN 'No prior-year baseline'
            WHEN COALESCE(a.yoy_7d_credits, 0) = 0 THEN 'No prior-year spend'
            WHEN (COALESCE(a.credits_7d, 0) - a.yoy_7d_credits) / NULLIF(a.yoy_7d_credits, 0) >= 0.20 THEN 'Above prior year'
            WHEN (COALESCE(a.credits_7d, 0) - a.yoy_7d_credits) / NULLIF(a.yoy_7d_credits, 0) <= -0.20 THEN 'Below prior year'
            ELSE 'Near prior year'
        END AS yoy_state,
        COALESCE(t.top_yoy_increase_warehouse, 'No warehouse baseline') AS top_yoy_increase_warehouse,
        ROUND(COALESCE(t.top_yoy_increase_credits, 0), 4) AS top_yoy_increase_credits
    FROM aggregate_trend a
    LEFT JOIN top_yoy t ON TRUE
    """


def _loaded_cortex_state() -> tuple[float, int]:
    summary = st.session_state.get("cortex_control_summary")
    exceptions = st.session_state.get("cortex_control_exceptions")
    projected = 0.0
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        projected = safe_float(summary.iloc[0].get("PROJECTED_30D_COST", 0))
    exception_count = len(exceptions) if isinstance(exceptions, pd.DataFrame) and not exceptions.empty else 0
    return projected, exception_count


def _queue_series(df: pd.DataFrame, column: str, default: object = "") -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([default] * len(df), index=df.index)


def _text_present(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text and text.upper() not in {"N/A", "NONE", "NULL", "NAN", "<NA>"})


def _cost_action_mask(queue: pd.DataFrame) -> pd.Series:
    category = _queue_series(queue, "CATEGORY").fillna("").astype(str).str.upper()
    source = _queue_series(queue, "SOURCE").fillna("").astype(str).str.upper()
    return (
        category.str.contains("COST", na=False)
        | category.str.contains("CHARGEBACK", na=False)
        | source.str.contains("COST & CONTRACT", na=False)
    )


def _build_cost_closure_analytics(queue: pd.DataFrame, credit_price: float) -> tuple[dict, pd.DataFrame]:
    """Summarize whether queued cost actions have real closure evidence."""
    empty_summary = {
        "cost_actions": 0,
        "open_actions": 0,
        "approval_pending_actions": 0,
        "post_period_pending_actions": 0,
        "fixed_without_verification": 0,
        "verified_savings_actions": 0,
        "open_estimated_monthly_savings": 0.0,
        "blocked_estimated_monthly_savings": 0.0,
        "verified_estimated_monthly_savings": 0.0,
        "verified_period_delta_dollars": 0.0,
        "audit_ready_pct": 0.0,
    }
    if queue is None or queue.empty:
        return empty_summary, pd.DataFrame()

    view = queue.loc[_cost_action_mask(queue)].copy()
    if view.empty:
        return empty_summary, pd.DataFrame()

    status = _queue_series(view, "STATUS").fillna("").astype(str).str.upper()
    category = _queue_series(view, "CATEGORY").fillna("").astype(str).str.upper()
    approval = _queue_series(view, "OWNER_APPROVAL_STATUS").fillna("").astype(str).str.upper()
    verification = _queue_series(view, "VERIFICATION_STATUS").fillna("").astype(str).str.upper()
    recovery = _queue_series(view, "RECOVERY_SLA_STATE").fillna("").astype(str).str.upper()
    verification_result = _queue_series(view, "VERIFICATION_RESULT").apply(_text_present)
    baseline = pd.to_numeric(_queue_series(view, "BASELINE_VALUE", 0), errors="coerce")
    current = pd.to_numeric(_queue_series(view, "CURRENT_VALUE", 0), errors="coerce")
    measured_delta = pd.to_numeric(_queue_series(view, "MEASURED_DELTA", 0), errors="coerce")
    estimated_savings = pd.to_numeric(_queue_series(view, "EST_MONTHLY_SAVINGS", 0), errors="coerce").fillna(0)

    fixed = status.eq("FIXED")
    ignored = status.eq("IGNORED")
    open_mask = ~fixed & ~ignored
    approved = approval.isin(["APPROVED", "NOT REQUIRED"])
    approval_pending = ~approved & ~ignored
    verified = verification.eq("VERIFIED") & verification_result
    improved = measured_delta.lt(0) | (current.notna() & baseline.notna() & current.lt(baseline))
    verified_savings = fixed & verified & approved & improved
    fixed_without_verification = fixed & ~verified_savings
    post_period_pending = open_mask & recovery.str.contains("SAVINGS VERIFICATION PENDING|POST-PERIOD", na=False)
    chargeback_pending = open_mask & (
        category.str.contains("CHARGEBACK", na=False)
        | recovery.str.contains("CHARGEBACK EVIDENCE PENDING", na=False)
    )

    closure_states = []
    evidence_notes = []
    verified_period_values = []
    for idx in view.index:
        if bool(verified_savings.loc[idx]):
            closure_states.append("Verified savings")
            evidence_notes.append("Fixed, verified, approved, and measured lower than baseline.")
            verified_period_values.append(round(credits_to_dollars(abs(safe_float(measured_delta.loc[idx])), credit_price), 2))
        elif bool(fixed_without_verification.loc[idx]):
            closure_states.append("Fixed without verified savings")
            evidence_notes.append("Do not count savings until verification result, approval, and lower post-period usage are attached.")
            verified_period_values.append(0.0)
        elif bool(chargeback_pending.loc[idx]):
            closure_states.append("Chargeback evidence pending")
            evidence_notes.append("Owner/tag proof or shared-cost classification is still required before billing.")
            verified_period_values.append(0.0)
        elif bool(approval_pending.loc[idx]):
            closure_states.append("Approval pending")
            evidence_notes.append("Owner approval is required before action or savings closure.")
            verified_period_values.append(0.0)
        elif bool(post_period_pending.loc[idx]):
            closure_states.append("Post-period measurement pending")
            evidence_notes.append("Run the stored verification query after the next complete period.")
            verified_period_values.append(0.0)
        elif bool(open_mask.loc[idx]):
            closure_states.append("Open cost action")
            evidence_notes.append("Action is not closed; keep proof query and baseline/current values current.")
            verified_period_values.append(0.0)
        else:
            closure_states.append("Ignored / not claimed")
            evidence_notes.append("Ignored rows are excluded from savings claims.")
            verified_period_values.append(0.0)

    view["CLOSURE_STATE"] = closure_states
    view["SAVINGS_EVIDENCE"] = evidence_notes
    view["VERIFIED_PERIOD_DELTA_DOLLARS"] = verified_period_values
    blocked = open_mask & (approval_pending | post_period_pending | chargeback_pending)
    fixed_count = int(fixed.sum())
    audit_ready = int(verified_savings.sum())
    summary = {
        "cost_actions": int(len(view)),
        "open_actions": int(open_mask.sum()),
        "approval_pending_actions": int(approval_pending.sum()),
        "post_period_pending_actions": int(post_period_pending.sum()),
        "fixed_without_verification": int(fixed_without_verification.sum()),
        "verified_savings_actions": audit_ready,
        "open_estimated_monthly_savings": round(safe_float(estimated_savings[open_mask].sum()), 2),
        "blocked_estimated_monthly_savings": round(safe_float(estimated_savings[blocked].sum()), 2),
        "verified_estimated_monthly_savings": round(safe_float(estimated_savings[verified_savings].sum()), 2),
        "verified_period_delta_dollars": round(safe_float(sum(verified_period_values)), 2),
        "audit_ready_pct": round((audit_ready / fixed_count) * 100, 1) if fixed_count else 0.0,
    }
    return summary, view


def _compact_time(value: object, default: str = "Not seen") -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"NAT", "NAN", "NONE", "NULL", "<NA>"}:
        return default
    return text[:19]


def _build_savings_verification_task_summary(health: pd.DataFrame | None) -> tuple[dict, pd.DataFrame]:
    """Summarize the Snowflake task that verifies cost savings into closure evidence."""
    empty_summary = {
        "loaded": False,
        "health_state": "Not Loaded",
        "task_state": "Not seen",
        "last_run": "Not seen",
        "failed_runs_7d": 0,
        "ledger_rows_7d": 0,
        "candidates_last_run": 0,
        "verified_last_run": 0,
        "evidence_required_last_run": 0,
        "issue_count": 1,
        "issue_severity": "High",
        "next_action": "Deploy the latest OVERWATCH mart setup, then resume the savings verification task.",
    }
    if health is None or getattr(health, "empty", True):
        return empty_summary, pd.DataFrame()

    view = health.copy()
    expected_defaults = {
        "CONTROL_NAME": "Cost & Contract Savings Verification",
        "TASK_NAME": "OVERWATCH_COST_SAVINGS_VERIFY",
        "TASK_HEALTH_STATE": "Unknown",
        "LAST_TASK_STATE": "",
        "LAST_TASK_SCHEDULED_AT": "",
        "LAST_TASK_COMPLETED_AT": "",
        "LAST_TASK_ERROR": "",
        "FAILED_RUNS_7D": 0,
        "LAST_VERIFICATION_RUN_AT": "",
        "LEDGER_RUN_ROWS_7D": 0,
        "CANDIDATES_LAST_RUN": 0,
        "VERIFIED_LAST_RUN": 0,
        "EVIDENCE_REQUIRED_LAST_RUN": 0,
        "NEXT_ACTION": "Review the verifier health row and cost action evidence.",
    }
    for column, default in expected_defaults.items():
        if column not in view.columns:
            view[column] = default

    row = view.iloc[0]
    health_state = str(row.get("TASK_HEALTH_STATE") or "Unknown").strip() or "Unknown"
    task_state = str(row.get("LAST_TASK_STATE") or "Not seen").strip() or "Not seen"
    failed_runs = safe_int(row.get("FAILED_RUNS_7D"))
    ledger_rows = safe_int(row.get("LEDGER_RUN_ROWS_7D"))
    candidates = safe_int(row.get("CANDIDATES_LAST_RUN"))
    verified = safe_int(row.get("VERIFIED_LAST_RUN"))
    evidence_required = safe_int(row.get("EVIDENCE_REQUIRED_LAST_RUN"))
    next_action = str(row.get("NEXT_ACTION") or "Review the verifier health row and cost action evidence.").strip()

    issue_count = 0
    if health_state.upper() != "HEALTHY":
        issue_count += 1
    if failed_runs > 0:
        issue_count += failed_runs
    if evidence_required > 0:
        issue_count += evidence_required

    if health_state.upper() in {"TASK FAILED", "TASK STALE", "TASK NOT SEEN"} or failed_runs > 0:
        issue_severity = "Critical"
    elif health_state.upper() == "NO VERIFICATION LEDGER":
        issue_severity = "High"
    elif evidence_required > 0:
        issue_severity = "Medium"
    else:
        issue_severity = "Info"

    view["ISSUE_SEVERITY"] = issue_severity
    view["ISSUE_COUNT"] = issue_count
    view["ISSUE_DETAIL"] = next_action
    summary = {
        "loaded": True,
        "health_state": health_state,
        "task_state": task_state,
        "last_run": _compact_time(row.get("LAST_VERIFICATION_RUN_AT")),
        "failed_runs_7d": failed_runs,
        "ledger_rows_7d": ledger_rows,
        "candidates_last_run": candidates,
        "verified_last_run": verified,
        "evidence_required_last_run": evidence_required,
        "issue_count": issue_count,
        "issue_severity": issue_severity,
        "next_action": next_action,
    }
    return summary, view


def _render_savings_verification_task_health(health: pd.DataFrame | None, error: str = "") -> None:
    summary, detail = _build_savings_verification_task_summary(health)
    st.markdown("**Savings Verification Task Health**")
    st.caption(
        "Monitors the scheduled Snowflake verifier that converts estimated cost actions into ledger-backed savings evidence."
    )
    h1, h2, h3, h4, h5 = st.columns(5)
    h1.metric("Task Health", summary["health_state"])
    h2.metric("Failed Runs 7d", f"{summary['failed_runs_7d']:,}", delta_color="inverse")
    h3.metric("Evidence Required", f"{summary['evidence_required_last_run']:,}", delta_color="inverse")
    h4.metric("Ledger Rows 7d", f"{summary['ledger_rows_7d']:,}")
    h5.metric("Last Ledger Run", summary["last_run"])

    if error:
        st.warning(f"Verification task health view unavailable: {error}")
        st.caption("Deploy the latest OVERWATCH mart setup SQL to create OVERWATCH_COST_SAVINGS_VERIFICATION_HEALTH_V.")
        return
    if detail.empty:
        st.info("Load the cockpit after deploying the verifier health view to monitor savings task failures and stale runs.")
        return

    if summary["issue_severity"] in {"Critical", "High"}:
        st.warning(summary["next_action"])
    elif summary["issue_count"] > 0:
        st.info(summary["next_action"])

    render_priority_dataframe(
        detail,
        title="Verifier health evidence",
        priority_columns=[
            "ISSUE_SEVERITY", "TASK_HEALTH_STATE", "LAST_TASK_STATE",
            "LAST_TASK_SCHEDULED_AT", "LAST_TASK_COMPLETED_AT", "FAILED_RUNS_7D",
            "LAST_VERIFICATION_RUN_AT", "LEDGER_RUN_ROWS_7D",
            "CANDIDATES_LAST_RUN", "VERIFIED_LAST_RUN", "EVIDENCE_REQUIRED_LAST_RUN",
            "LAST_TASK_ERROR", "ISSUE_DETAIL",
        ],
        sort_by=["FAILED_RUNS_7D", "EVIDENCE_REQUIRED_LAST_RUN"],
        ascending=[False, False],
        raw_label="Full verifier health row",
        height=190,
        max_rows=5,
    )


def _render_savings_closure_control(queue: pd.DataFrame, credit_price: float) -> None:
    summary, detail = _build_cost_closure_analytics(queue, credit_price)
    st.markdown("**Savings Closure Control**")
    st.caption(
        "Potential savings stay estimated until the action is fixed, owner-approved, verified, "
        "and the measured post-period usage is lower than the stored baseline."
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cost Actions", f"{summary['cost_actions']:,}")
    c2.metric("Open Est. Savings", f"${summary['open_estimated_monthly_savings']:,.0f}/mo")
    c3.metric("Blocked Est. Savings", f"${summary['blocked_estimated_monthly_savings']:,.0f}/mo", delta_color="inverse")
    c4.metric("Verified Period Value", f"${summary['verified_period_delta_dollars']:,.0f}")
    c5.metric("Fixed Audit Ready", f"{summary['audit_ready_pct']:,.1f}%")

    if detail.empty:
        st.info("No cost-control or chargeback actions are currently visible in the loaded action queue scope.")
        with st.expander("Deploy scheduled savings verification", expanded=False):
            st.caption("Install this once in the OVERWATCH mart schema, review the task, then resume it.")
            st.code(build_cost_savings_verification_sql(), language="sql")
        return

    render_priority_dataframe(
        detail,
        title="Cost actions that still need approval, measurement, or closure evidence",
        priority_columns=[
            "SEVERITY", "CLOSURE_STATE", "CATEGORY", "ENTITY_NAME", "OWNER",
            "OWNER_EMAIL", "ONCALL_PRIMARY", "APPROVAL_GROUP", "OWNER_SOURCE",
            "STATUS", "OWNER_APPROVAL_STATUS", "VERIFICATION_STATUS",
            "BASELINE_VALUE", "CURRENT_VALUE", "MEASURED_DELTA",
            "VERIFIED_PERIOD_DELTA_DOLLARS", "RECOVERY_SLA_STATE",
            "SAVINGS_EVIDENCE", "TICKET_ID", "APPROVER",
        ],
        sort_by=["QUEUE_PRIORITY", "SEVERITY"],
        ascending=[True, True],
        raw_label="All loaded cost closure rows",
        height=260,
        max_rows=10,
    )
    with st.expander("Deploy scheduled savings verification", expanded=False):
        st.caption(
            "This Snowflake procedure/task verifies warehouse cost-control actions from exact metering. "
            "Chargeback and database/user allocations still require owner evidence."
        )
        st.code(build_cost_savings_verification_sql(), language="sql")


def _nullable_float(row: pd.Series, column: str) -> float | None:
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return safe_float(value)


def _format_optional_pct(value: float | None, empty: str = "No baseline") -> str:
    if value is None:
        return empty
    return f"{value:+.1f}%"


def _render_cost_run_rate_lens(run_rate: pd.DataFrame | None, credit_price: float, error: str = "") -> None:
    st.markdown("**Run-Rate and YOY**")
    if error:
        st.caption(f"Run-rate trend unavailable: {error}")
        return
    if run_rate is None or getattr(run_rate, "empty", True):
        st.caption("Load the cockpit to show complete-day 7-day averages, 30-day context, and prior-year comparison.")
        return

    row = run_rate.iloc[0]
    avg_7d = safe_float(row.get("AVG_DAILY_7D"))
    avg_30d = safe_float(row.get("AVG_DAILY_30D"))
    credits_7d = safe_float(row.get("CREDITS_7D"))
    projected_30d = safe_float(row.get("PROJECTED_30D_FROM_7D"))
    pct_vs_30d = _nullable_float(row, "PCT_VS_30D_AVG")
    yoy_7d_pct = _nullable_float(row, "YOY_7D_PCT")
    yoy_30d_pct = _nullable_float(row, "YOY_30D_PCT")
    yoy_days_7d = safe_int(row.get("YOY_DAYS_7D"))
    yoy_days_30d = safe_int(row.get("YOY_DAYS_30D"))
    run_state = str(row.get("RUN_RATE_STATE") or "Unknown")
    yoy_state = str(row.get("YOY_STATE") or "Unknown")

    r1, r2, r3, r4, r5 = st.columns(5)
    r1.metric(
        "7d Avg",
        f"{avg_7d:,.1f} cr/day",
        _format_optional_pct(pct_vs_30d, run_state) + " vs 30d",
        delta_color="inverse",
    )
    r2.metric("7d Cost", f"${credits_to_dollars(credits_7d, credit_price):,.0f}", f"${credits_to_dollars(avg_7d, credit_price):,.0f}/day")
    r3.metric("30d Run-Rate", f"${credits_to_dollars(projected_30d, credit_price):,.0f}/30d", run_state)
    r4.metric("7d YOY", _format_optional_pct(yoy_7d_pct), f"{yoy_days_7d}/7 PY days", delta_color="inverse")
    r5.metric("30d YOY", _format_optional_pct(yoy_30d_pct), f"{yoy_days_30d}/30 PY days", delta_color="inverse")

    top_wh = str(row.get("TOP_YOY_INCREASE_WAREHOUSE") or "No warehouse baseline")
    top_delta = safe_float(row.get("TOP_YOY_INCREASE_CREDITS"))
    st.caption(
        f"{yoy_state}. Top same-week YOY increase: {top_wh} "
        f"({top_delta:+,.2f} credits). Uses complete days only."
    )


def _state_frame(state: dict, key: str) -> pd.DataFrame:
    value = state.get(key)
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    return isinstance(df, pd.DataFrame) and not df.empty and all(col in df.columns for col in columns)


def _add_coverage_row(rows: list[dict], control: str, state: str, evidence: str, action: str, owner: str = "DBA / FinOps") -> None:
    rows.append({
        "CONTROL": control,
        "STATE": state,
        "EVIDENCE": evidence,
        "NEXT_ACTION": action,
        "OWNER": owner,
    })


def _build_cost_control_coverage_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    verification_health: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    state = state or st.session_state
    rows: list[dict] = []
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    cortex_projection, cortex_exceptions = _loaded_cortex_state()

    _add_coverage_row(
        rows,
        "Exact warehouse metering",
        "Ready" if _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"]) else "Load Needed",
        "Cockpit has exact WAREHOUSE_METERING_HISTORY current/prior credits." if _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"]) else "Cost cockpit has not loaded exact warehouse movement yet.",
        "Load Cost Cockpit before explaining any bill movement.",
    )
    _add_coverage_row(
        rows,
        "7-day average and YOY",
        "Ready" if _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"]) else "Load Needed",
        "Run-rate lens has complete-day 7d average and prior-year comparison." if _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"]) else "Run-rate/YOY evidence is not loaded.",
        "Load Cost Cockpit to populate complete-day run-rate and YOY proof.",
    )
    _add_coverage_row(
        rows,
        "Company and environment split",
        "Ready" if _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"]) else "Review",
        "Chargeback/Cost Explorer includes company and environment dimensions." if _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"]) else "Company/environment attribution is not loaded in this session.",
        "Load Cost Explorer or Chargeback before defending ALFA/Trexis or PROD/DEV allocation.",
    )
    _add_coverage_row(
        rows,
        "Database and DEV rollup",
        "Ready" if _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"]) else "Review",
        "Database-attributed cost is visible and labeled Allocated / Estimated." if _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"]) else "Database-level attribution has not been loaded.",
        "Use Chargeback for PROD, DEV_ALL, and individual DEV database cost views.",
    )
    _add_coverage_row(
        rows,
        "Role, user, and department drivers",
        "Ready" if _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"]) else "Review",
        "Cost Explorer detail includes role, user, and department dimensions." if _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"]) else "Role/user/department cost drivers are not loaded.",
        "Load Cost Explorer and sort by estimated cost before assigning optimization work.",
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        category = queue.get("CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        status = queue.get("STATUS", pd.Series(["New"] * len(queue), index=queue.index)).fillna("New").astype(str).str.title()
        open_cost_queue = queue[category.str.contains("COST|CHARGEBACK|FINOPS|CORTEX", na=False) & ~status.isin(["Fixed", "Ignored"])]
    owner_source = open_cost_queue.get("OWNER_SOURCE", pd.Series(dtype=str)).fillna("").astype(str).str.strip() if not open_cost_queue.empty else pd.Series(dtype=str)
    owner_ready = int(owner_source.ne("").sum()) if not owner_source.empty else 0
    _add_coverage_row(
        rows,
        "Owned cost action queue",
        "Ready" if not open_cost_queue.empty and owner_ready == len(open_cost_queue) else "Review" if not open_cost_queue.empty else "No Rows",
        f"{len(open_cost_queue):,} open cost action(s); {owner_ready:,} have owner-source evidence.",
        "Route cost findings through the action queue with owner, due date, approval, and verification proof.",
    )

    verification_summary, _ = _build_savings_verification_task_summary(verification_health)
    verifier_state = str(verification_summary.get("state") or "Unknown")
    _add_coverage_row(
        rows,
        "Verified savings ledger",
        "Ready" if verifier_state == "Ready" else "Review",
        str(verification_summary.get("evidence") or "Savings verifier health has not been loaded."),
        str(verification_summary.get("next_action") or "Deploy and monitor the scheduled savings verifier task."),
    )
    _add_coverage_row(
        rows,
        "Cortex cost guardrail",
        "Ready" if cortex_projection > 0 or cortex_exceptions > 0 else "No Rows",
        f"Projected Cortex spend ${cortex_projection:,.0f}/30d with {cortex_exceptions:,} exception(s).",
        "Open AI and Cortex spend when projection or exception count is non-zero.",
    )
    _add_coverage_row(
        rows,
        "Shared-cost disclosure",
        "Ready",
        "Warehouse totals are exact; user/query/database chargeback is explicitly labeled Allocated / Estimated.",
        "Keep shared warehouse and no-database-context costs out of exact PROD/DEV claims until owner/tag proof exists.",
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "ready": 0, "review": 0, "load_needed": 0}, board
    load_needed = int(board["STATE"].eq("Load Needed").sum())
    review = int(board["STATE"].eq("Review").sum())
    ready = int(board["STATE"].isin(["Ready", "No Rows"]).sum())
    score = max(0, min(100, 100 - load_needed * 12 - review * 6))
    board["_STATE_RANK"] = board["STATE"].map({"Load Needed": 0, "Review": 1, "No Rows": 2, "Ready": 3}).fillna(9)
    return {
        "score": int(score),
        "ready": ready,
        "review": review,
        "load_needed": load_needed,
    }, board.sort_values(["_STATE_RANK", "CONTROL"]).drop(columns=["_STATE_RANK"], errors="ignore")


def _build_cost_allocation_trust_board(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Classify cost evidence as exact, allocated/estimated, or not yet defensible."""
    state = state or st.session_state
    rows: list[dict] = []
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")

    def add(control: str, trust: str, evidence: str, action: str, owner: str = "DBA / FinOps") -> None:
        rows.append({
            "CONTROL": control,
            "TRUST_STATE": trust,
            "EVIDENCE": evidence,
            "NEXT_ACTION": action,
            "OWNER": owner,
        })

    exact_loaded = _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"])
    run_rate_loaded = _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"])
    add(
        "Contract and warehouse totals",
        "Exact" if exact_loaded and run_rate_loaded else "Load Needed",
        "Warehouse metering and complete-day run-rate/YOY are loaded." if exact_loaded and run_rate_loaded else "Exact warehouse totals or complete-day run-rate evidence is missing.",
        "Load Cost Cockpit before defending contract pace, 7-day average, or YOY movement.",
    )

    company_env_loaded = _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"])
    add(
        "Company and environment view",
        "Allocated/Estimated" if company_env_loaded else "Review",
        "Company/environment split is present; database-attributed cost remains allocated where warehouse usage is shared." if company_env_loaded else "Company/environment allocation is not loaded in this session.",
        "Load Cost Explorer or Chargeback before explaining ALFA/Trexis or PROD/DEV cost movement.",
    )

    db_loaded = _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"])
    allocation_confidence = pd.Series(dtype=str)
    if _has_columns(chargeback, ["ALLOCATION_CONFIDENCE"]):
        allocation_confidence = chargeback["ALLOCATION_CONFIDENCE"].fillna("").astype(str)
    elif _has_columns(explorer, ["ALLOCATION_CONFIDENCE"]):
        allocation_confidence = explorer["ALLOCATION_CONFIDENCE"].fillna("").astype(str)
    estimated_rows = int(allocation_confidence.str.contains("ESTIMATED|ALLOCATED|SHARED", case=False, regex=True).sum()) if len(allocation_confidence) else 0
    add(
        "Database attribution",
        "Allocated/Estimated" if db_loaded else "Review",
        (
            f"Database drilldown loaded; {estimated_rows:,} row(s) explicitly carry allocated/shared/estimated confidence."
            if db_loaded else "Database attribution is not loaded."
        ),
        "Use database views for chargeback directionally; do not present shared warehouse database spend as exact.",
    )

    human_driver_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])
    add(
        "Role, user, department drivers",
        "Allocated/Estimated" if human_driver_loaded else "Review",
        "Human and department cost drivers are available for prioritization." if human_driver_loaded else "Role/user/department drilldown is not loaded.",
        "Load Cost Explorer before assigning optimization work to teams or departments.",
    )

    no_database_rows = 0
    for frame in (chargeback, explorer):
        if _has_columns(frame, ["DATABASE_NAME"]):
            no_database_rows += int(frame["DATABASE_NAME"].fillna("").astype(str).str.strip().eq("").sum())
    add(
        "Shared and no-database spend",
        "Allocated/Estimated" if no_database_rows else "Ready" if db_loaded else "Review",
        (
            f"{no_database_rows:,} loaded row(s) have no database context and must stay outside exact PROD/DEV claims."
            if no_database_rows else "No loaded database-attribution rows are missing database context." if db_loaded else "No database-attribution rows loaded."
        ),
        "Keep no-database, login-only, and shared-service spend labeled allocated/estimated until owner/tag proof exists.",
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        category = queue.get("CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        status = queue.get("STATUS", pd.Series(["New"] * len(queue), index=queue.index)).fillna("New").astype(str).str.title()
        open_cost_queue = queue[category.str.contains("COST|CHARGEBACK|FINOPS|CORTEX", na=False) & ~status.isin(["Fixed", "Ignored"])].copy()
    owner_ready = 0
    verification_ready = 0
    if not open_cost_queue.empty:
        owner_ready = int(open_cost_queue.get("OWNER_SOURCE", pd.Series(dtype=str)).fillna("").astype(str).str.strip().ne("").sum())
        verification_ready = int(
            open_cost_queue.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.contains("VERIFIED|PASSED|COMPLETE", regex=True).sum()
        )
    add(
        "Optimization closure trust",
        "Ready" if not open_cost_queue.empty and owner_ready == len(open_cost_queue) and verification_ready > 0 else "Review" if not open_cost_queue.empty else "No Rows",
        f"{len(open_cost_queue):,} open cost action(s); {owner_ready:,} owner-routed; {verification_ready:,} verified/completed.",
        "Do not claim savings until owner approval, measurement period, verification result, and closure evidence are attached.",
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"score": 0, "exact": 0, "estimated": 0, "review": 0, "load_needed": 0}, board
    exact = int(board["TRUST_STATE"].isin(["Exact", "Ready", "No Rows"]).sum())
    estimated = int(board["TRUST_STATE"].eq("Allocated/Estimated").sum())
    review = int(board["TRUST_STATE"].eq("Review").sum())
    load_needed = int(board["TRUST_STATE"].eq("Load Needed").sum())
    score = max(0, min(100, 100 - load_needed * 14 - review * 7 - estimated * 2))
    board["_TRUST_RANK"] = board["TRUST_STATE"].map({
        "Load Needed": 0,
        "Review": 1,
        "Allocated/Estimated": 2,
        "No Rows": 3,
        "Ready": 4,
        "Exact": 5,
    }).fillna(9)
    return {
        "score": int(score),
        "exact": exact,
        "estimated": estimated,
        "review": review,
        "load_needed": load_needed,
    }, board.sort_values(["_TRUST_RANK", "CONTROL"]).drop(columns=["_TRUST_RANK"], errors="ignore").reset_index(drop=True)


def _build_cost_drilldown_command_map(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Expose which cost drilldowns are defensible from already-loaded data."""
    state = state or st.session_state
    explorer = _state_frame(state, "df_cost_explorer_detail")
    chargeback = _state_frame(state, "df_chargeback")
    cortex_projection, cortex_exceptions = _loaded_cortex_state()

    rows: list[dict] = []

    def loaded_rows(*frames: pd.DataFrame) -> int:
        return sum(len(frame) for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty)

    def add(
        grain: str,
        state_value: str,
        trust: str,
        rows_loaded: int,
        metric: str,
        next_action: str,
        workflow: str,
        rank: int,
    ) -> None:
        rows.append({
            "COMMAND_PRIORITY": f"P{rank}",
            "DRILLDOWN": grain,
            "STATE": state_value,
            "TRUST": trust,
            "ROWS_LOADED": rows_loaded,
            "PRIMARY_METRIC": metric,
            "NEXT_ACTION": next_action,
            "WORKFLOW": workflow,
            "_RANK": rank,
        })

    current_credits = safe_float(cockpit.iloc[0].get("CURRENT_CREDITS")) if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else 0.0
    prior_credits = safe_float(cockpit.iloc[0].get("PRIOR_CREDITS")) if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else 0.0
    top_wh = str(cockpit.iloc[0].get("TOP_INCREASE_WAREHOUSE") or "") if isinstance(cockpit, pd.DataFrame) and not cockpit.empty else ""
    exact_loaded = _has_columns(cockpit, ["CURRENT_CREDITS", "PRIOR_CREDITS"])
    add(
        "Warehouse bill movement",
        "Ready" if exact_loaded else "Load Needed",
        "Exact",
        loaded_rows(cockpit),
        f"{current_credits:,.2f} current credits; {prior_credits:,.2f} prior credits",
        f"Explain top warehouse movement first{f': {top_wh}' if top_wh else ''}.",
        "Explain bill / attribution / contract",
        0 if exact_loaded else 1,
    )

    run_loaded = _has_columns(run_rate, ["AVG_DAILY_7D", "YOY_7D_PCT", "YOY_30D_PCT"])
    add(
        "7-day average and YOY pace",
        "Ready" if run_loaded else "Load Needed",
        "Exact",
        loaded_rows(run_rate),
        (
            f"7d avg {safe_float(run_rate.iloc[0].get('AVG_DAILY_7D')):,.2f} credits; "
            f"YOY7 {safe_float(run_rate.iloc[0].get('YOY_7D_PCT')):+.1f}%"
            if run_loaded and not run_rate.empty else "No run-rate evidence loaded"
        ),
        "Use complete-day 7d average and YOY before calling a spike real.",
        "Explain bill / attribution / contract",
        0 if run_loaded else 1,
    )

    company_loaded = _has_columns(chargeback, ["COMPANY", "ENVIRONMENT"]) or _has_columns(explorer, ["COMPANY", "ENVIRONMENT_ROLLUP"])
    add(
        "Company and environment",
        "Ready" if company_loaded else "Review",
        "Allocated/Estimated",
        loaded_rows(chargeback, explorer),
        "ALFA/Trexis plus PROD/DEV split" if company_loaded else "No company/environment rows loaded",
        "Use this for chargeback direction; keep shared warehouse disclosure visible.",
        "Explain bill / attribution / contract",
        2 if company_loaded else 3,
    )

    db_loaded = _has_columns(chargeback, ["DATABASE_NAME"]) or _has_columns(explorer, ["DATABASE_NAME"])
    no_db_rows = 0
    for frame in (chargeback, explorer):
        if _has_columns(frame, ["DATABASE_NAME"]):
            no_db_rows += int(frame["DATABASE_NAME"].fillna("").astype(str).str.strip().eq("").sum())
    add(
        "Database, DEV rollup, no-database spend",
        "Ready" if db_loaded else "Review",
        "Allocated/Estimated",
        loaded_rows(chargeback, explorer),
        f"{no_db_rows:,} no-database row(s)" if db_loaded else "No database rows loaded",
        "Show PROD, DEV_ALL, individual DEV databases, and keep no-database spend out of exact claims.",
        "Explain bill / attribution / contract",
        2 if db_loaded else 3,
    )

    human_loaded = _has_columns(explorer, ["ROLE_NAME", "USER_NAME", "DEPARTMENT"])
    add(
        "Role, user, department",
        "Ready" if human_loaded else "Review",
        "Allocated/Estimated",
        loaded_rows(explorer),
        "Role/user/department drivers loaded" if human_loaded else "Human driver rows not loaded",
        "Sort by estimated dollars before assigning work to a department or user.",
        "Explain bill / attribution / contract",
        2 if human_loaded else 3,
    )

    open_cost_queue = pd.DataFrame()
    if isinstance(queue, pd.DataFrame) and not queue.empty:
        mask = _cost_action_mask(queue)
        open_cost_queue = queue[mask].copy()
    verified = 0
    if not open_cost_queue.empty:
        verified = int(
            open_cost_queue.get("VERIFICATION_STATUS", pd.Series(dtype=str)).fillna("").astype(str).str.upper().str.contains(
                "VERIFIED|PASSED|COMPLETE",
                regex=True,
            ).sum()
        )
    add(
        "Savings closure proof",
        "Ready" if not open_cost_queue.empty and verified else "Review" if not open_cost_queue.empty else "No Rows",
        "Exact after verification",
        len(open_cost_queue),
        f"{verified:,} verified/completed action(s)",
        "Do not count savings until measurement, owner approval, and verification result are attached.",
        "Recommendations and action queue",
        2 if verified else 3,
    )

    add(
        "AI and Cortex spend",
        "Ready" if cortex_projection > 0 or cortex_exceptions > 0 else "No Rows",
        "Allocated/Estimated",
        cortex_exceptions,
        f"${cortex_projection:,.0f}/30d projection; {cortex_exceptions:,} exception(s)",
        "Review first/last usage, user attribution, and projected token-credit spend.",
        "AI and Cortex spend",
        2 if cortex_projection > 0 or cortex_exceptions > 0 else 4,
    )

    board = pd.DataFrame(rows)
    if board.empty:
        return {"ready": 0, "review": 0, "load_needed": 0, "estimated": 0}, board
    ready = int(board["STATE"].isin(["Ready", "No Rows"]).sum())
    review = int(board["STATE"].eq("Review").sum())
    load_needed = int(board["STATE"].eq("Load Needed").sum())
    estimated = int(board["TRUST"].eq("Allocated/Estimated").sum())
    return {
        "ready": ready,
        "review": review,
        "load_needed": load_needed,
        "estimated": estimated,
    }, board.sort_values(["_RANK", "DRILLDOWN"]).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


def _render_cost_control_coverage_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    verification_health: pd.DataFrame,
) -> None:
    summary, board = _build_cost_control_coverage_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        verification_health=verification_health,
    )
    if board.empty:
        return
    st.markdown("**Cost Control Coverage**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Coverage", f"{summary['score']}/100")
    c2.metric("Ready", f"{summary['ready']:,}")
    c3.metric("Review", f"{summary['review']:,}", delta_color="inverse")
    c4.metric("Load Needed", f"{summary['load_needed']:,}", delta_color="inverse")
    render_priority_dataframe(
        board,
        title="Cost evidence coverage",
        priority_columns=["STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
        sort_by=["STATE", "CONTROL"],
        ascending=[True, True],
        raw_label="All cost control coverage rows",
        max_rows=12,
    )


def _render_cost_allocation_trust_board(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    summary, board = _build_cost_allocation_trust_board(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
    )
    if board.empty:
        return
    st.markdown("**Cost Allocation Trust**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trust", f"{summary['score']}/100")
    c2.metric("Exact / Ready", f"{summary['exact']:,}")
    c3.metric("Allocated / Estimated", f"{summary['estimated']:,}")
    c4.metric("Review / Load", f"{summary['review'] + summary['load_needed']:,}", delta_color="inverse")
    render_priority_dataframe(
        board,
        title="Cost attribution trust states",
        priority_columns=["TRUST_STATE", "CONTROL", "EVIDENCE", "NEXT_ACTION", "OWNER"],
        sort_by=["TRUST_STATE", "CONTROL"],
        ascending=[True, True],
        raw_label="All cost allocation trust rows",
        max_rows=10,
    )


def _render_cost_drilldown_command_map(
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    summary, board = _build_cost_drilldown_command_map(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
    )
    if board.empty:
        return
    st.markdown("**Cost Drilldown Command Map**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ready", f"{summary['ready']:,}")
    c2.metric("Review", f"{summary['review']:,}", delta_color="inverse")
    c3.metric("Load Needed", f"{summary['load_needed']:,}", delta_color="inverse")
    c4.metric("Allocated", f"{summary['estimated']:,}")
    render_priority_dataframe(
        board,
        title="Cost drilldowns to trust or load next",
        priority_columns=[
            "COMMAND_PRIORITY", "STATE", "DRILLDOWN", "TRUST", "ROWS_LOADED", "PRIMARY_METRIC",
            "NEXT_ACTION", "WORKFLOW",
        ],
        sort_by=["COMMAND_PRIORITY", "DRILLDOWN"],
        ascending=[True, True],
        raw_label="All cost drilldown command rows",
        height=280,
        max_rows=10,
    )


def _render_cost_watch_floor(company: str, credit_price: float) -> None:
    st.subheader("Cost Control Cockpit")
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        days = st.selectbox("Cost cockpit window", [7, 14, 30], index=0, format_func=lambda d: f"{d} days")
    with c2:
        if st.button("Load Cost Cockpit", key="cost_contract_cockpit_load", type="primary"):
            session = get_session_for_action(
                "load the Cost Control Cockpit",
                surface="Cost & Contract",
                offline_note="Cost workflow navigation remains available without a live Snowflake connection.",
            )
            if session is None:
                return
            try:
                st.session_state["cost_contract_cockpit"] = run_query(
                    build_mart_cost_cockpit_sql(company, int(days)),
                    ttl_key=f"cost_contract_cockpit_mart_{company}_{days}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["cost_contract_cockpit_source"] = "OVERWATCH mart: FACT_WAREHOUSE_HOURLY"
                st.session_state["cost_contract_cockpit_meta"] = {"company": company, "days": int(days)}
                st.session_state["cost_contract_cockpit_error"] = ""
            except Exception as mart_exc:
                try:
                    st.session_state["cost_contract_cockpit"] = run_query(
                        _build_cost_cockpit_sql(company, int(days)),
                        ttl_key=f"cost_contract_cockpit_{company}_{days}",
                        tier="standard",
                        section="Cost & Contract",
                    )
                    st.session_state["cost_contract_cockpit_source"] = (
                        "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                    )
                    st.session_state["cost_contract_cockpit_meta"] = {"company": company, "days": int(days)}
                    st.session_state["cost_contract_cockpit_error"] = ""
                except Exception as exc:
                    st.session_state["cost_contract_cockpit_error"] = (
                        f"Mart unavailable: {format_snowflake_error(mart_exc)}; "
                        f"live fallback failed: {format_snowflake_error(exc)}"
                    )
                    st.session_state["cost_contract_cockpit"] = pd.DataFrame()
                    st.session_state["cost_contract_queue"] = pd.DataFrame()
            try:
                st.session_state["cost_contract_run_rate"] = run_query(
                    build_mart_cost_run_rate_sql(company),
                    ttl_key=f"cost_contract_run_rate_mart_{company}",
                    tier="historical",
                    section="Cost & Contract",
                )
                st.session_state["cost_contract_run_rate_source"] = "OVERWATCH mart: FACT_WAREHOUSE_HOURLY"
                st.session_state["cost_contract_run_rate_error"] = ""
            except Exception as mart_exc:
                try:
                    st.session_state["cost_contract_run_rate"] = run_query(
                        _build_cost_run_rate_sql(company),
                        ttl_key=f"cost_contract_run_rate_live_{company}",
                        tier="historical",
                        section="Cost & Contract",
                    )
                    st.session_state["cost_contract_run_rate_source"] = (
                        "Live fallback: SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
                    )
                    st.session_state["cost_contract_run_rate_error"] = ""
                except Exception as exc:
                    st.session_state["cost_contract_run_rate"] = pd.DataFrame()
                    st.session_state["cost_contract_run_rate_source"] = ""
                    st.session_state["cost_contract_run_rate_error"] = (
                        f"Mart unavailable: {format_snowflake_error(mart_exc)}; "
                        f"live fallback failed: {format_snowflake_error(exc)}"
                    )
            try:
                st.session_state["cost_contract_queue"] = load_action_queue(session)
                st.session_state["cost_contract_queue_error"] = ""
            except Exception as exc:
                st.session_state["cost_contract_queue"] = pd.DataFrame()
                st.session_state["cost_contract_queue_error"] = format_snowflake_error(exc)
            try:
                st.session_state["cost_contract_verification_health"] = run_query(
                    build_cost_savings_verification_health_sql(),
                    ttl_key="cost_contract_verification_health",
                    tier="recent",
                    section="Cost & Contract",
                )
                st.session_state["cost_contract_verification_health_error"] = ""
            except Exception as exc:
                st.session_state["cost_contract_verification_health"] = pd.DataFrame()
                st.session_state["cost_contract_verification_health_error"] = format_snowflake_error(exc)
    with c3:
        st.info("Use this cockpit to decide whether to explain the bill, work the action queue, inspect Cortex spend, or log verified savings.")

    data = st.session_state.get("cost_contract_cockpit")
    meta = st.session_state.get("cost_contract_cockpit_meta", {})
    err = st.session_state.get("cost_contract_cockpit_error", "")
    if err:
        st.warning(f"Cost cockpit unavailable: {err}")
    loaded_days = meta.get("days")
    if (
        isinstance(data, pd.DataFrame)
        and not data.empty
        and meta.get("company") == company
        and loaded_days is not None
        and int(loaded_days) != int(days)
    ):
        st.info(
            f"Loaded cockpit data is for {int(loaded_days)} days; selected window is {int(days)} days. "
            "Click Load Cost Cockpit to refresh the watch floor."
        )
    if (
        not isinstance(data, pd.DataFrame)
        or data.empty
        or meta.get("company") != company
        or meta.get("days") != int(days)
    ):
        st.caption("Load the cost cockpit for a fast first move. Specialist pages still load their own detailed data.")
        return

    st.caption(st.session_state.get("cost_contract_cockpit_source", "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"))
    row = data.iloc[0]
    queue = st.session_state.get("cost_contract_queue", pd.DataFrame())
    queue_err = st.session_state.get("cost_contract_queue_error", "")
    if queue_err:
        st.caption(f"Action queue unavailable for this role/context: {queue_err}")
    open_actions = high_actions = 0
    total_savings = 0.0
    if isinstance(queue, pd.DataFrame) and not queue.empty and "STATUS" in queue.columns:
        open_mask = ~queue["STATUS"].isin(["Fixed", "Ignored"])
        open_actions = int(open_mask.sum())
        high_actions = int((queue.get("SEVERITY", pd.Series(dtype=str)).isin(["Critical", "High"]) & open_mask).sum())
        if "EST_MONTHLY_SAVINGS" in queue.columns:
            total_savings = safe_float(pd.to_numeric(queue.loc[open_mask, "EST_MONTHLY_SAVINGS"], errors="coerce").fillna(0).sum())
    current_credits = safe_float(row.get("CURRENT_CREDITS", 0))
    prior_credits = safe_float(row.get("PRIOR_CREDITS", 0))
    delta_pct = ((current_credits - prior_credits) / prior_credits * 100) if prior_credits > 0 else 0.0
    cortex_projected, cortex_exception_count = _loaded_cortex_state()
    score = _cost_score(current_credits, prior_credits, open_actions, high_actions, cortex_exception_count)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Cost Score", f"{score}/100", _cost_rating(score))
    k2.metric("Current Window", f"${credits_to_dollars(current_credits, credit_price):,.0f}", f"{delta_pct:+.1f}%", delta_color="inverse")
    k3.metric("Open Actions", f"{open_actions:,}", f"{high_actions:,} high", delta_color="inverse")
    k4.metric("Savings Queue", f"${total_savings:,.0f}/mo")
    k5.metric("Cortex Projection", f"${cortex_projected:,.0f}/30d", f"{cortex_exception_count:,} exceptions", delta_color="inverse")

    run_rate_source = st.session_state.get("cost_contract_run_rate_source", "")
    if run_rate_source:
        st.caption(run_rate_source)
    _render_cost_run_rate_lens(
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        credit_price,
        st.session_state.get("cost_contract_run_rate_error", ""),
    )

    _render_savings_verification_task_health(
        st.session_state.get("cost_contract_verification_health", pd.DataFrame()),
        st.session_state.get("cost_contract_verification_health_error", ""),
    )
    _render_savings_closure_control(queue, credit_price)
    _render_cost_control_coverage_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
        st.session_state.get("cost_contract_verification_health", pd.DataFrame()),
    )
    _render_cost_allocation_trust_board(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )
    _render_cost_drilldown_command_map(
        data,
        st.session_state.get("cost_contract_run_rate", pd.DataFrame()),
        queue,
    )

    moves = []
    if delta_pct >= 20 or safe_float(row.get("TOP_INCREASE_CREDITS", 0)) > 0:
        moves.append((
            "Explain the bill movement",
            f"Top increase: {row.get('TOP_INCREASE_WAREHOUSE', 'unknown')} "
            f"({safe_float(row.get('TOP_INCREASE_CREDITS', 0)):,.2f} credits).",
            "Explain bill / attribution / contract",
        ))
    if high_actions > 0 or total_savings > 0:
        moves.append((
            "Work the action queue",
            f"{high_actions:,} high-priority action(s), ${total_savings:,.0f}/month potential savings.",
            "Recommendations and action queue",
        ))
    if cortex_exception_count > 0 or cortex_projected > 0:
        moves.append((
            "Inspect AI / Cortex spend",
            f"Projected Cortex spend ${cortex_projected:,.0f}/30d with {cortex_exception_count:,} exception(s).",
            "AI and Cortex spend",
        ))
    if not moves:
        moves.append((
            "Log value or review attribution",
            "No dominant cost incident in this cockpit window. Use value log for verified DBA wins or attribution for chargeback.",
            "Snowflake value log",
        ))

    st.markdown("**Next Cost Moves**")
    cols = st.columns(min(len(moves), 3))
    for idx, (title, evidence, workflow) in enumerate(moves[:3]):
        with cols[idx]:
            st.markdown(f"**{title}**")
            st.caption(evidence)
            if st.button(f"Open {workflow}", key=f"cost_contract_next_{idx}_{workflow}", use_container_width=True):
                st.session_state["cost_contract_workflow"] = workflow
                st.rerun()


def render() -> None:
    company = get_active_company()
    credit_price = safe_float(get_credit_price()) or 3.68
    if st.session_state.get("exceptions_only_mode") and "cost_contract_workflow" not in st.session_state:
        st.session_state["cost_contract_workflow"] = "Explain bill / attribution / contract"
    render_signal_confidence(
        source="ACCOUNT_USAGE",
        confidence="allocated",
        scope_note="Warehouse totals are exact; user/query chargeback is allocated unless noted.",
    )
    render_operator_briefing(
        [
            ("First move", "Explain why spend changed before tuning anything."),
            ("Evidence", "Reconcile warehouse metering, chargeback allocation, Cortex, and contract pace."),
            ("Control", "Convert findings into owned actions with savings and proof."),
            ("Output", "Produce a bill narrative leadership can understand without opening the app."),
        ],
        columns=4,
    )
    if st.session_state.get("exceptions_only_mode"):
        st.warning("Exceptions-only mode: prioritize bill deltas, open action queue items, and contract risk.")
    render_workflow_guide(
        "Explain the bill first, convert findings into owned actions, log validated savings, "
        "then inspect special-cost surfaces like Cortex and SPCS.",
        [
            ("Why did the bill move?", "Use Explain bill / attribution / contract."),
            ("What should we fix first?", "Use Recommendations and action queue."),
            ("How do we prove savings?", "Use Snowflake value log."),
            ("Are AI costs controlled?", "Use AI and Cortex spend."),
            ("Are container services costing us?", "Use SPCS spend."),
        ],
    )
    _render_cost_watch_floor(company, credit_price)

    workflow = render_workflow_selector(
        "Cost workflow",
        "cost_contract_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
        columns=5,
    )

    render_workflow_module(workflow, WORKFLOW_MODULES)
