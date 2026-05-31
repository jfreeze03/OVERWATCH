# sections/cost_contract.py - Consolidated cost and contract workflow
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections import (
    cortex_monitor,
    cost_center,
    recommendations,
    snowflake_value,
    spcs_tracker,
)
from utils import (
    build_cost_savings_verification_health_sql,
    build_cost_savings_verification_sql,
    build_mart_cost_cockpit_sql,
    credits_to_dollars,
    format_snowflake_error,
    get_active_company,
    get_session,
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


def _render_cost_watch_floor(session, company: str, credit_price: float) -> None:
    st.subheader("Cost Control Cockpit")
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        days = st.selectbox("Cost cockpit window", [7, 14, 30], index=0, format_func=lambda d: f"{d} days")
    with c2:
        if st.button("Load Cost Cockpit", key="cost_contract_cockpit_load", type="primary"):
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

    _render_savings_verification_task_health(
        st.session_state.get("cost_contract_verification_health", pd.DataFrame()),
        st.session_state.get("cost_contract_verification_health_error", ""),
    )
    _render_savings_closure_control(queue, credit_price)

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
    session = get_session()
    company = get_active_company()
    credit_price = safe_float(st.session_state.get("credit_price", 3.0)) or 3.0
    if st.session_state.get("exceptions_only_mode") and "cost_contract_workflow" not in st.session_state:
        st.session_state["cost_contract_workflow"] = "Explain bill / attribution / contract"
    st.header("Cost & Contract")
    st.caption(
        "One operating workflow for bill explanation, cost attribution, contract pacing, "
        "optimization actions, AI/Cortex usage, and Snowpark Container Services spend."
    )
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
    _render_cost_watch_floor(session, company, credit_price)

    workflow = render_workflow_selector(
        "Cost workflow",
        "cost_contract_workflow",
        WORKFLOWS,
        WORKFLOW_DETAILS,
    )

    if workflow == "Explain bill / attribution / contract":
        cost_center.render()
    elif workflow == "Recommendations and action queue":
        recommendations.render()
    elif workflow == "Snowflake value log":
        snowflake_value.render()
    elif workflow == "AI and Cortex spend":
        cortex_monitor.render()
    else:
        spcs_tracker.render()
