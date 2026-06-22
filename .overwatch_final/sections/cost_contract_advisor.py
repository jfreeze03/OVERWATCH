"""Cost & Contract advisor and action-queue dataframe helpers.

This module owns non-render advisory logic.  It does not call Streamlit, run
SQL, or mutate session state; ``cost_contract.py`` remains the UI/workflow
shell and re-exports these helpers for compatibility.
"""

from __future__ import annotations

import pandas as pd

from config import DEFAULTS
from sections.cost_contract_dataframes import (
    _cost_column,
    _looks_like_frame,
    _service_lens_movement_rows,
)
from utils.cost import credits_to_dollars
from utils.primitives import safe_float, safe_int


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


def _open_cost_action_frame(queue: pd.DataFrame | None) -> pd.DataFrame:
    if queue is None or getattr(queue, "empty", True):
        return pd.DataFrame()
    view = queue.loc[_cost_action_mask(queue)].copy()
    if view.empty:
        return view
    status = _queue_series(view, "STATUS", "New").fillna("New").astype(str).str.upper()
    return view[~status.isin(["FIXED", "IGNORED"])].copy()


def _build_cost_closure_analytics(queue: pd.DataFrame, credit_price: float) -> tuple[dict, pd.DataFrame]:
    """Summarize whether queued cost actions have measured closure status."""
    empty_summary = {
        "cost_actions": 0,
        "open_actions": 0,
        "approval_pending_actions": 0,
        "post_period_pending_actions": 0,
        "fixed_without_verification": 0,
        "verified_savings_actions": 0,
        "verified_no_change_actions": 0,
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

    def telemetry_status_label(value: object) -> str:
        text = str(value or "").strip().upper()
        if text in {"VERIFIED", "VERIFIED_SAVED", "PASSED", "COMPLETE", "COMPLETED"}:
            return "Measured improvement"
        if text == "VERIFIED_NO_CHANGE":
            return "Measured no improvement"
        if text in {"EVIDENCE_REQUIRED", "PENDING", "REQUESTED"}:
            return "Telemetry pending"
        return str(value or "").strip() or "Telemetry pending"

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
    approved = approval.isin(["APPROVED", "VERIFIED", "NOT REQUIRED"])
    approval_pending = ~approved & ~ignored
    verified = verification.isin(["VERIFIED", "VERIFIED_SAVED"]) & verification_result
    verified_no_change = verification.eq("VERIFIED_NO_CHANGE") & verification_result & approved
    improved = measured_delta.lt(0) | (current.notna() & baseline.notna() & current.lt(baseline))
    verified_savings = fixed & approved & (
        (verification.eq("VERIFIED_SAVED") & verification_result)
        | (verification.eq("VERIFIED") & verification_result & improved)
    )
    verified_no_change_closure = fixed & verified_no_change & ~verified_savings
    fixed_without_verification = fixed & ~(verified_savings | verified_no_change_closure)
    post_period_pending = open_mask & recovery.str.contains("POST-PERIOD", na=False)
    chargeback_pending = open_mask & (
        category.str.contains("CHARGEBACK", na=False)
        | recovery.str.contains("CHARGEBACK EVIDENCE PENDING", na=False)
    )

    closure_states = []
    evidence_notes = []
    verified_period_values = []
    for idx in view.index:
        if bool(verified_savings.loc[idx]):
            closure_states.append("Measured improvement")
            evidence_notes.append("Fixed, reviewed, and measured lower than baseline.")
            verified_period_values.append(round(credits_to_dollars(abs(safe_float(measured_delta.loc[idx])), credit_price), 2))
        elif bool(verified_no_change_closure.loc[idx]):
            closure_states.append("Measured no improvement")
            evidence_notes.append("Post-change telemetry did not improve from the stored baseline.")
            verified_period_values.append(0.0)
        elif bool(fixed_without_verification.loc[idx]):
            closure_states.append("Fixed, awaiting measurement")
            evidence_notes.append("Keep impact directional until later telemetry shows the signal improved.")
            verified_period_values.append(0.0)
        elif bool(chargeback_pending.loc[idx]):
            closure_states.append("Chargeback telemetry pending")
            evidence_notes.append("Tag or shared-cost classification is still required before billing.")
            verified_period_values.append(0.0)
        elif bool(approval_pending.loc[idx]):
            closure_states.append("Review pending")
            evidence_notes.append("Telemetry review is required before action or impact closure.")
            verified_period_values.append(0.0)
        elif bool(post_period_pending.loc[idx]):
            closure_states.append("Post-period measurement pending")
            evidence_notes.append("Review the next complete usage period before closing impact.")
            verified_period_values.append(0.0)
        elif bool(open_mask.loc[idx]):
            closure_states.append("Open cost action")
            evidence_notes.append("Action is not closed; keep baseline/current values current.")
            verified_period_values.append(0.0)
        else:
            closure_states.append("Ignored / not claimed")
            evidence_notes.append("Ignored rows are excluded from action impact.")
            verified_period_values.append(0.0)

    view["CLOSURE_STATE"] = closure_states
    view["IMPACT_EVIDENCE"] = evidence_notes
    view["MEASURED_IMPACT_DOLLARS"] = verified_period_values
    view["TELEMETRY_STATUS"] = _queue_series(view, "VERIFICATION_STATUS").fillna("").astype(str).apply(telemetry_status_label)
    blocked = open_mask & (approval_pending | post_period_pending | chargeback_pending)
    fixed_count = int(fixed.sum())
    audit_ready = int(verified_savings.sum())
    no_change_count = int(verified_no_change_closure.sum())
    summary = {
        "cost_actions": int(len(view)),
        "open_actions": int(open_mask.sum()),
        "approval_pending_actions": int(approval_pending.sum()),
        "post_period_pending_actions": int(post_period_pending.sum()),
        "fixed_without_verification": int(fixed_without_verification.sum()),
        "verified_savings_actions": audit_ready,
        "verified_no_change_actions": no_change_count,
        "open_estimated_monthly_savings": round(safe_float(estimated_savings[open_mask].sum()), 2),
        "blocked_estimated_monthly_savings": round(safe_float(estimated_savings[blocked].sum()), 2),
        "verified_estimated_monthly_savings": round(safe_float(estimated_savings[verified_savings].sum()), 2),
        "verified_period_delta_dollars": round(safe_float(sum(verified_period_values)), 2),
        "audit_ready_pct": round(((audit_ready + no_change_count) / fixed_count) * 100, 1) if fixed_count else 0.0,
    }
    return summary, view


def _build_attribution_gap_summary(reconciliation: pd.DataFrame, credit_price: float) -> dict:
    if reconciliation is None or getattr(reconciliation, "empty", True):
        return {
            "exact_credits": 0.0,
            "query_credits": 0.0,
            "official_query_credits": 0.0,
            "gap_credits": 0.0,
            "gap_pct": 0.0,
            "gap_usd": 0.0,
            "official_queries": 0,
            "top_gap_warehouse": "No rows",
            "rows": 0,
        }
    exact = safe_float(pd.to_numeric(reconciliation.get("EXACT_METERED_CREDITS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    query = safe_float(pd.to_numeric(reconciliation.get("ALLOCATED_QUERY_CREDITS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    official = safe_float(pd.to_numeric(reconciliation.get("OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    official_queries = safe_int(pd.to_numeric(reconciliation.get("OFFICIAL_ATTRIBUTED_QUERIES", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    gap = exact - query
    gap_pct = (gap / exact * 100) if exact > 0 else 0.0
    top_gap = "No rows"
    if "VARIANCE_CREDITS" in reconciliation.columns and "WAREHOUSE_NAME" in reconciliation.columns:
        view = reconciliation.copy()
        view["_ABS_GAP"] = pd.to_numeric(view["VARIANCE_CREDITS"], errors="coerce").fillna(0).abs()
        if not view.empty:
            top_gap = str(view.sort_values("_ABS_GAP", ascending=False).iloc[0].get("WAREHOUSE_NAME") or "Unknown")
    return {
        "exact_credits": exact,
        "query_credits": query,
        "official_query_credits": official,
        "gap_credits": gap,
        "gap_pct": gap_pct,
        "gap_usd": credits_to_dollars(gap, credit_price),
        "official_queries": official_queries,
        "top_gap_warehouse": top_gap,
        "rows": len(reconciliation),
    }


def _cost_advisor_priority(impact_usd: float, *, finding_type: str = "") -> str:
    impact = abs(safe_float(impact_usd))
    finding = str(finding_type or "").upper()
    if impact >= 1000 or any(token in finding for token in ("SPILL", "FAILED", "ATTRIBUTION GAP")):
        return "High"
    if impact >= 250:
        return "Medium"
    return "Low"


def _cost_advisor_add_row(
    rows: list[dict],
    *,
    category: str,
    entity: str,
    finding: str,
    estimate_type: str,
    impact_usd: float,
    savings_usd: float,
    evidence: str,
    safe_next_action: str,
    proof_required: str,
    do_not_do: str,
    confidence: str,
    source: str,
) -> None:
    impact = round(safe_float(impact_usd), 2)
    savings = round(max(0.0, safe_float(savings_usd)), 2)
    priority = _cost_advisor_priority(max(impact, savings), finding_type=finding)
    rows.append({
        "PRIORITY": priority,
        "SEVERITY": priority,
        "CATEGORY": category,
        "ENTITY": str(entity or "Unknown"),
        "FINDING": finding,
        "ESTIMATE_TYPE": estimate_type,
        "EST_MONTHLY_IMPACT_USD": impact,
        "EST_MONTHLY_SAVINGS_USD": savings,
        "EVIDENCE": evidence,
        "TELEMETRY_SUMMARY": evidence,
        "SAFE_NEXT_ACTION": safe_next_action,
        "PROOF_REQUIRED": proof_required,
        "VALIDATION_NEEDED": proof_required,
        "DO_NOT_DO": do_not_do,
        "CONFIDENCE": confidence,
        "SOURCE": source,
    })


_COST_ADVISOR_ACTION_MAP = {
    "Failed query waste": ("Fix failed workload", "Waste Detection"),
    "Warehouse pressure": ("Investigate pressure before capacity change", "Cost by Warehouse"),
    "Warehouse right-size review": ("Review right-size or suspend policy", "Cost by Warehouse"),
    "Automatic clustering": ("Validate clustering value", "Waste Detection"),
    "Attribution gap": ("Reconcile spend attribution", "Budget vs Actual"),
    "Service spend movement": ("Map non-warehouse service spend", "Budget vs Actual"),
    "Storage retention": ("Review storage retention", "Waste Detection"),
    "Storage failsafe": ("Review storage lifecycle", "Waste Detection"),
}


def _cost_advisor_action_for(category: str) -> tuple[str, str]:
    return _COST_ADVISOR_ACTION_MAP.get(
        str(category or "").strip(),
        ("Investigate cost signal", "Cost Recommendations"),
    )


def _decorate_cost_advisor_board(board: pd.DataFrame) -> pd.DataFrame:
    """Add action-oriented columns to advisor rows without changing the telemetry source."""
    if board.empty:
        return board
    decorated = board.copy()
    actions = decorated.get("CATEGORY", pd.Series([""] * len(decorated), index=decorated.index)).apply(
        _cost_advisor_action_for
    )
    decorated["ACTION_TYPE"] = actions.apply(lambda item: item[0])
    decorated["WORKFLOW_ROUTE"] = actions.apply(lambda item: item[1])
    decorated["PRIMARY_METRIC"] = decorated.apply(
        lambda row: (
            f"${safe_float(row.get('EST_MONTHLY_SAVINGS_USD')):,.0f}/mo savings"
            if safe_float(row.get("EST_MONTHLY_SAVINGS_USD")) > 0
            else f"${abs(safe_float(row.get('EST_MONTHLY_IMPACT_USD'))):,.0f}/mo value at risk"
        ),
        axis=1,
    )
    decorated["EXECUTION_MODE"] = decorated["ESTIMATE_TYPE"].fillna("").astype(str).apply(
        lambda value: (
            "Savings candidate"
            if "saving" in value.lower() or "recoverable" in value.lower()
            else "Investigation"
        )
    )
    return decorated


def _build_cost_advisor_board(
    *,
    efficiency_summary: pd.DataFrame | None,
    warehouse_efficiency: pd.DataFrame | None,
    clustering_cost: pd.DataFrame | None,
    reconciliation: pd.DataFrame | None,
    service_lens: pd.DataFrame | None,
    credit_price: float,
    days: int,
    storage_table_metrics: pd.DataFrame | None = None,
    storage_db_detail: pd.DataFrame | None = None,
    storage_cost_per_tb: float | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build ranked cost-advisor findings from already loaded Cost & Contract frames."""
    rows: list[dict] = []
    days = max(1, safe_int(days, 7))
    window_factor = 30.0 / float(days)
    price = safe_float(credit_price, safe_float(DEFAULTS.get("credit_price"), 3.68))
    storage_rate = safe_float(storage_cost_per_tb, safe_float(DEFAULTS.get("storage_cost_per_tb"), 23.0))

    if _looks_like_frame(efficiency_summary) and not efficiency_summary.empty:
        row = efficiency_summary.iloc[0]
        failed_waste = safe_float(row.get("FAILED_QUERY_WASTE_USD"))
        failed_queries = safe_int(row.get("FAILED_QUERIES"))
        if failed_waste > 0 and failed_queries > 0:
            monthly = failed_waste * window_factor
            _cost_advisor_add_row(
                rows,
                category="Failed query waste",
                entity="Account workload",
                finding="Failed-query spend is measurable",
                estimate_type="Conservative recoverable waste",
                impact_usd=monthly,
                savings_usd=monthly * 0.6,
                evidence=(
                    f"{failed_queries:,} failed query row(s), ${failed_waste:,.0f} failed-query waste "
                    f"in the {days}-day window."
                ),
                safe_next_action="Group failed queries by error code, warehouse, user, and query signature before routing fixes.",
                proof_required="Failed query count and failed-query waste should fall in the next complete cost window.",
                do_not_do="Do not resize warehouses for failures unless queue or spill telemetry also points to capacity pressure.",
                confidence="Medium - waste is attributed from query cost telemetry; root cause still needs query evidence.",
                source="Cost efficiency summary",
            )

    if _looks_like_frame(warehouse_efficiency) and not warehouse_efficiency.empty:
        work = warehouse_efficiency.copy()
        wh_col = _cost_column(work, ["WAREHOUSE_NAME", "WAREHOUSE"])
        if wh_col:
            for col in (
                "COST_USD", "QUEUE_SECONDS", "REMOTE_SPILL_GB", "FAILED_QUERY_WASTE_USD",
                "QUERY_COUNT", "AVG_CACHE_PCT",
            ):
                if col not in work.columns:
                    work[col] = 0.0
            for _, row in work.iterrows():
                wh = str(row.get(wh_col) or "Unknown")
                window_cost = safe_float(row.get("COST_USD"))
                monthly_cost = window_cost * window_factor
                queue_seconds = safe_float(row.get("QUEUE_SECONDS"))
                remote_spill_gb = safe_float(row.get("REMOTE_SPILL_GB"))
                failed_waste = safe_float(row.get("FAILED_QUERY_WASTE_USD"))
                query_count = safe_int(row.get("QUERY_COUNT"))
                avg_cache = safe_float(row.get("AVG_CACHE_PCT"))
                if remote_spill_gb >= 10 or queue_seconds >= 600:
                    pressure = []
                    if remote_spill_gb >= 10:
                        pressure.append(f"{remote_spill_gb:,.1f} GB remote spill")
                    if queue_seconds >= 600:
                        pressure.append(f"{queue_seconds:,.0f}s queue time")
                    _cost_advisor_add_row(
                        rows,
                        category="Warehouse pressure",
                        entity=wh,
                        finding="Queue or spill pressure may be inflating cost",
                        estimate_type="Value at risk",
                        impact_usd=monthly_cost,
                        savings_usd=0.0,
                        evidence=(
                            f"{wh}: {', '.join(pressure)} with ${window_cost:,.0f} warehouse cost "
                            f"in the {days}-day window."
                        ),
                        safe_next_action="Inspect top query profiles and decide between SQL tuning, workload isolation, or reviewed capacity change.",
                        proof_required="Remote spill, queue seconds, p95 runtime, and credits must improve for the same workload.",
                        do_not_do="Do not blindly upsize; spill can come from SQL shape and may multiply cost.",
                        confidence="Medium - pressure is direct telemetry, but the correct fix depends on query profile evidence.",
                        source="Warehouse efficiency and pressure",
                    )
                elif monthly_cost >= 250 and query_count > 0 and queue_seconds < 30 and remote_spill_gb < 1:
                    _cost_advisor_add_row(
                        rows,
                        category="Warehouse right-size review",
                        entity=wh,
                        finding="Low-pressure warehouse may have savings opportunity",
                        estimate_type="Conservative savings candidate",
                        impact_usd=monthly_cost,
                        savings_usd=monthly_cost * 0.25,
                        evidence=(
                            f"{wh}: ${window_cost:,.0f} cost, {query_count:,} query row(s), "
                            f"{queue_seconds:,.0f}s queue, {remote_spill_gb:,.1f} GB remote spill, "
                            f"{avg_cache:,.1f}% average cache in the {days}-day window."
                        ),
                        safe_next_action="Review p95 runtime and workload schedule before testing a one-step downsize or tighter suspend policy.",
                        proof_required="Cost should decline while p95 runtime, queue, failures, and spill remain acceptable.",
                        do_not_do="Do not downsize always-on, latency-sensitive, or shared service warehouses from this row alone.",
                        confidence="Low - savings are directional until size, suspend, and SLA context are reviewed.",
                        source="Warehouse efficiency and pressure",
                    )
                if failed_waste >= 50:
                    monthly_failed = failed_waste * window_factor
                    _cost_advisor_add_row(
                        rows,
                        category="Failed query waste",
                        entity=wh,
                        finding="Warehouse has failed-query cost waste",
                        estimate_type="Conservative recoverable waste",
                        impact_usd=monthly_failed,
                        savings_usd=monthly_failed * 0.6,
                        evidence=f"{wh}: ${failed_waste:,.0f} failed-query waste in the loaded window.",
                        safe_next_action="Route the top failed query signatures and owners before changing warehouse settings.",
                        proof_required="Failed-query waste should drop in the next completed cost window.",
                        do_not_do="Do not treat failed-query waste as a warehouse-sizing fix without error-code evidence.",
                        confidence="Medium - warehouse failure waste is measurable, root cause requires query diagnostics.",
                        source="Warehouse efficiency and pressure",
                    )

    if _looks_like_frame(clustering_cost) and not clustering_cost.empty:
        work = clustering_cost.copy()
        table_col = _cost_column(work, ["TABLE_NAME", "TABLE"])
        cost_col = _cost_column(work, ["CLUSTERING_COST_USD", "COST_USD"])
        tb_col = _cost_column(work, ["TB_RECLUSTERED"])
        if table_col and cost_col:
            work["_COST"] = pd.to_numeric(work[cost_col], errors="coerce").fillna(0.0)
            for _, row in work.sort_values("_COST", ascending=False).head(8).iterrows():
                window_cost = safe_float(row.get("_COST"))
                monthly_cost = window_cost * window_factor
                if monthly_cost < 50:
                    continue
                table_name = str(row.get(table_col) or "Unknown")
                tb = safe_float(row.get(tb_col)) if tb_col else 0.0
                _cost_advisor_add_row(
                    rows,
                    category="Automatic clustering",
                    entity=table_name,
                    finding="Automatic clustering spend needs value proof",
                    estimate_type="Conservative savings candidate",
                    impact_usd=monthly_cost,
                    savings_usd=monthly_cost * 0.5,
                    evidence=(
                        f"{table_name}: ${window_cost:,.0f} clustering cost and {tb:,.2f} TB reclustered "
                        f"in the {days}-day window."
                    ),
                    safe_next_action="Review clustering depth, DML churn, pruning benefit, and top query demand before changing clustering.",
                    proof_required="Cost per TB reclustered should fall or query pruning/runtime must justify the clustering spend.",
                    do_not_do="Do not suspend reclustering until query benefit and recovery expectations are reviewed.",
                    confidence="Medium - clustering cost is direct telemetry, value requires workload proof.",
                    source="Automatic clustering cost",
                )

    if _looks_like_frame(reconciliation) and not reconciliation.empty:
        gap = _build_attribution_gap_summary(reconciliation, price)
        gap_usd = abs(safe_float(gap.get("gap_usd")))
        if gap_usd >= 100:
            _cost_advisor_add_row(
                rows,
                category="Attribution gap",
                entity=str(gap.get("top_gap_warehouse") or "Warehouse attribution"),
                finding="Query attribution gap does not reconcile to metered credits",
                estimate_type="Data quality / idle-cost exposure",
                impact_usd=gap_usd,
                savings_usd=0.0,
                evidence=(
                    f"{safe_float(gap.get('gap_credits')):+,.2f} credit gap "
                    f"({safe_float(gap.get('gap_pct')):+.1f}%), ${gap_usd:,.0f} equivalent."
                ),
                safe_next_action="Separate idle, cloud-services, serverless, AI, and execution-attributed spend before routing owners.",
                proof_required="Reconciliation gap should narrow or be explained by labeled non-query service spend.",
                do_not_do="Do not charge query owners for warehouse idle or service costs without explicit allocation evidence.",
                confidence="High - metering gap is direct math; ownership requires allocation policy.",
                source="Query attribution reconciliation",
            )

    if _looks_like_frame(service_lens) and not service_lens.empty:
        movement = _service_lens_movement_rows(service_lens, price, limit=12)
        if not movement.empty:
            category_series = movement.get("SERVICE_CATEGORY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
            non_wh = movement[~category_series.eq("WAREHOUSE")].copy()
            if not non_wh.empty:
                non_wh["_POS_DELTA"] = pd.to_numeric(non_wh.get("COST_DELTA_USD", 0), errors="coerce").fillna(0.0)
                non_wh = non_wh[non_wh["_POS_DELTA"] > 0].sort_values("_POS_DELTA", ascending=False)
                for _, row in non_wh.head(3).iterrows():
                    delta_usd = safe_float(row.get("_POS_DELTA"))
                    if delta_usd < 25:
                        continue
                    service = str(row.get("SERVICE_TYPE") or "Unknown service")
                    category = str(row.get("SERVICE_CATEGORY") or "Other")
                    _cost_advisor_add_row(
                        rows,
                        category="Service spend movement",
                        entity=service,
                        finding="Non-warehouse service spend increased",
                        estimate_type="Cost movement investigation",
                        impact_usd=delta_usd,
                        savings_usd=0.0,
                        evidence=f"{service}: +${delta_usd:,.0f} versus the prior completed window ({category}).",
                        safe_next_action="Open the service lens and map the service to its owning workload or Snowflake feature.",
                        proof_required="The next completed service-cost window should confirm whether the increase persists.",
                        do_not_do="Do not attribute account-level service spend to a warehouse or database without direct evidence.",
                        confidence="High - service cost comes from official account metering; owner route may need more telemetry.",
                        source="Account service cost lens",
                    )

    if _looks_like_frame(storage_table_metrics) and not storage_table_metrics.empty:
        work = storage_table_metrics.copy()
        active_col = _cost_column(work, ["ACTIVE_GB"])
        tt_col = _cost_column(work, ["TIME_TRAVEL_GB"])
        failsafe_col = _cost_column(work, ["FAILSAFE_GB"])
        clone_col = _cost_column(work, ["CLONE_GB"])
        if tt_col:
            for col in (active_col, tt_col, failsafe_col, clone_col):
                if col and col not in work.columns:
                    work[col] = 0.0
            for _, row in work.iterrows():
                catalog = str(row.get("TABLE_CATALOG") or "").strip()
                schema = str(row.get("TABLE_SCHEMA") or "").strip()
                table = str(row.get("TABLE_NAME") or "").strip()
                table_name = ".".join(part for part in (catalog, schema, table) if part) or "Unknown table"
                active_gb = safe_float(row.get(active_col)) if active_col else 0.0
                time_travel_gb = safe_float(row.get(tt_col))
                failsafe_gb = safe_float(row.get(failsafe_col)) if failsafe_col else 0.0
                clone_gb = safe_float(row.get(clone_col)) if clone_col else 0.0
                monthly_tt = (time_travel_gb / 1024.0) * storage_rate
                if time_travel_gb >= 100 or monthly_tt >= 25:
                    _cost_advisor_add_row(
                        rows,
                        category="Storage retention",
                        entity=table_name,
                        finding="Table time-travel storage needs retention review",
                        estimate_type="Conservative savings candidate",
                        impact_usd=monthly_tt,
                        savings_usd=monthly_tt * 0.5,
                        evidence=(
                            f"{table_name}: {time_travel_gb:,.1f} GB time-travel, {active_gb:,.1f} GB active, "
                            f"{failsafe_gb:,.1f} GB failsafe, {clone_gb:,.1f} GB retained for clone."
                        ),
                        safe_next_action="Confirm recovery, cloning, and compliance needs before lowering table/schema/database retention.",
                        proof_required="Time-travel GB and monthly storage estimate should decline after the approved retention window ages out.",
                        do_not_do="Do not lower retention on regulated, clone-heavy, or recovery-sensitive objects from this row alone.",
                        confidence="Medium - table storage bytes are direct telemetry, retention safety depends on policy.",
                        source="Storage table metrics",
                    )

    if _looks_like_frame(storage_db_detail) and not storage_db_detail.empty:
        work = storage_db_detail.copy()
        db_col = _cost_column(work, ["DATABASE_NAME", "DATABASE"])
        storage_col = _cost_column(work, ["DATABASE_GB", "STORAGE_GB"])
        failsafe_col = _cost_column(work, ["FAILSAFE_GB"])
        cost_col = _cost_column(work, ["EST_COST_USD", "EST_MONTHLY_COST", "MONTHLY_COST_USD"])
        if db_col and failsafe_col:
            for _, row in work.iterrows():
                db = str(row.get(db_col) or "Unknown database")
                storage_gb = safe_float(row.get(storage_col)) if storage_col else 0.0
                failsafe_gb = safe_float(row.get(failsafe_col))
                monthly_cost = safe_float(row.get(cost_col)) if cost_col else ((storage_gb + failsafe_gb) / 1024.0) * storage_rate
                failsafe_cost = (failsafe_gb / 1024.0) * storage_rate
                if failsafe_gb < 250 and failsafe_cost < 25:
                    continue
                _cost_advisor_add_row(
                    rows,
                    category="Storage failsafe",
                    entity=db,
                    finding="Database failsafe storage is material",
                    estimate_type="Retention and lifecycle investigation",
                    impact_usd=max(failsafe_cost, monthly_cost),
                    savings_usd=0.0,
                    evidence=(
                        f"{db}: {failsafe_gb:,.1f} GB failsafe, {storage_gb:,.1f} GB database storage, "
                        f"~${monthly_cost:,.0f}/mo total storage estimate."
                    ),
                    safe_next_action="Identify recent drops/deletes and retention settings before changing lifecycle or cleanup patterns.",
                    proof_required="Failsafe and total storage trend should decline only after Snowflake retention/failsafe windows age out.",
                    do_not_do="Do not promise immediate savings from failsafe; Snowflake failsafe is not directly purgeable.",
                    confidence="Medium - database storage bytes are direct telemetry, savings timing depends on retention windows.",
                    source="Storage database detail",
                )

    board = pd.DataFrame(rows)
    if board.empty:
        return {
            "findings": 0,
            "high": 0,
            "estimated_monthly_savings": 0.0,
            "estimated_monthly_impact": 0.0,
        }, board

    board = _decorate_cost_advisor_board(board)
    priority_rank = {"High": 0, "Medium": 1, "Low": 2}
    board["_PRIORITY_RANK"] = board["PRIORITY"].map(priority_rank).fillna(9)
    board["_IMPACT_SORT"] = pd.to_numeric(board["EST_MONTHLY_IMPACT_USD"], errors="coerce").fillna(0).abs()
    board = board.sort_values(
        ["_PRIORITY_RANK", "EST_MONTHLY_SAVINGS_USD", "_IMPACT_SORT"],
        ascending=[True, False, False],
    ).drop(columns=["_PRIORITY_RANK", "_IMPACT_SORT"], errors="ignore").reset_index(drop=True)
    priority = board["PRIORITY"].fillna("").astype(str)
    return {
        "findings": int(len(board)),
        "high": int(priority.eq("High").sum()),
        "estimated_monthly_savings": safe_float(
            pd.to_numeric(board["EST_MONTHLY_SAVINGS_USD"], errors="coerce").fillna(0).sum()
        ),
        "estimated_monthly_impact": safe_float(
            pd.to_numeric(board["EST_MONTHLY_IMPACT_USD"], errors="coerce").fillna(0).abs().sum()
        ),
    }, board


def _cost_advisor_category_summary(board: pd.DataFrame | None) -> pd.DataFrame:
    columns = [
        "CATEGORY", "TOP_PRIORITY", "FINDINGS", "HIGH_FINDINGS",
        "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD", "TOP_ENTITY",
    ]
    if not _looks_like_frame(board) or board.empty or "CATEGORY" not in board.columns:
        return pd.DataFrame(columns=columns)

    view = board.copy()
    view["CATEGORY"] = view["CATEGORY"].fillna("Other").astype(str).replace("", "Other")
    view["EST_MONTHLY_SAVINGS_USD"] = pd.to_numeric(
        view.get("EST_MONTHLY_SAVINGS_USD", pd.Series([0] * len(view), index=view.index)),
        errors="coerce",
    ).fillna(0).clip(lower=0)
    view["EST_MONTHLY_IMPACT_USD"] = pd.to_numeric(
        view.get("EST_MONTHLY_IMPACT_USD", pd.Series([0] * len(view), index=view.index)),
        errors="coerce",
    ).fillna(0).abs()
    severity = view.get("SEVERITY", view.get("PRIORITY", pd.Series(["Low"] * len(view), index=view.index)))
    view["_PRIORITY"] = severity.fillna("Low").astype(str).str.title()
    rank_map = {"High": 0, "Medium": 1, "Low": 2}
    view["_PRIORITY_RANK"] = view["_PRIORITY"].map(rank_map).fillna(9).astype(int)
    view["_HIGH"] = view["_PRIORITY"].eq("High").astype(int)
    if "ENTITY" not in view.columns:
        view["ENTITY"] = ""

    summary = (
        view.groupby("CATEGORY", dropna=False)
        .agg(
            FINDINGS=("CATEGORY", "size"),
            HIGH_FINDINGS=("_HIGH", "sum"),
            EST_MONTHLY_SAVINGS_USD=("EST_MONTHLY_SAVINGS_USD", "sum"),
            EST_MONTHLY_IMPACT_USD=("EST_MONTHLY_IMPACT_USD", "sum"),
            _PRIORITY_RANK=("_PRIORITY_RANK", "min"),
            TOP_ENTITY=("ENTITY", "first"),
        )
        .reset_index()
    )
    priority_labels = {0: "High", 1: "Medium", 2: "Low"}
    summary["TOP_PRIORITY"] = summary["_PRIORITY_RANK"].map(priority_labels).fillna("Low")
    summary["_SORT_VALUE"] = summary["EST_MONTHLY_SAVINGS_USD"].abs() + summary["EST_MONTHLY_IMPACT_USD"].abs()
    summary = summary.sort_values(
        ["_PRIORITY_RANK", "EST_MONTHLY_SAVINGS_USD", "_SORT_VALUE"],
        ascending=[True, False, False],
    )
    return summary[columns].reset_index(drop=True)


def _cost_advisor_action_summary(board: pd.DataFrame | None) -> pd.DataFrame:
    columns = [
        "ACTION_TYPE", "WORKFLOW_ROUTE", "TOP_PRIORITY", "FINDINGS", "HIGH_FINDINGS",
        "EST_MONTHLY_SAVINGS_USD", "EST_MONTHLY_IMPACT_USD", "NEXT_MOVE",
    ]
    if not _looks_like_frame(board) or board.empty:
        return pd.DataFrame(columns=columns)
    view = _decorate_cost_advisor_board(board)
    for column in ("ACTION_TYPE", "WORKFLOW_ROUTE", "SAFE_NEXT_ACTION"):
        if column not in view.columns:
            view[column] = ""
    view["EST_MONTHLY_SAVINGS_USD"] = pd.to_numeric(
        view.get("EST_MONTHLY_SAVINGS_USD", pd.Series([0] * len(view), index=view.index)),
        errors="coerce",
    ).fillna(0).clip(lower=0)
    view["EST_MONTHLY_IMPACT_USD"] = pd.to_numeric(
        view.get("EST_MONTHLY_IMPACT_USD", pd.Series([0] * len(view), index=view.index)),
        errors="coerce",
    ).fillna(0).abs()
    priority = view.get("SEVERITY", view.get("PRIORITY", pd.Series(["Low"] * len(view), index=view.index)))
    view["_PRIORITY"] = priority.fillna("Low").astype(str).str.title()
    rank_map = {"High": 0, "Medium": 1, "Low": 2}
    view["_PRIORITY_RANK"] = view["_PRIORITY"].map(rank_map).fillna(9).astype(int)
    view["_HIGH"] = view["_PRIORITY"].eq("High").astype(int)
    summary = (
        view.groupby(["ACTION_TYPE", "WORKFLOW_ROUTE"], dropna=False)
        .agg(
            FINDINGS=("ACTION_TYPE", "size"),
            HIGH_FINDINGS=("_HIGH", "sum"),
            EST_MONTHLY_SAVINGS_USD=("EST_MONTHLY_SAVINGS_USD", "sum"),
            EST_MONTHLY_IMPACT_USD=("EST_MONTHLY_IMPACT_USD", "sum"),
            _PRIORITY_RANK=("_PRIORITY_RANK", "min"),
            NEXT_MOVE=("SAFE_NEXT_ACTION", "first"),
        )
        .reset_index()
    )
    priority_labels = {0: "High", 1: "Medium", 2: "Low"}
    summary["TOP_PRIORITY"] = summary["_PRIORITY_RANK"].map(priority_labels).fillna("Low")
    summary["_SORT_VALUE"] = summary["EST_MONTHLY_SAVINGS_USD"] + summary["EST_MONTHLY_IMPACT_USD"]
    summary = summary.sort_values(
        ["_PRIORITY_RANK", "EST_MONTHLY_SAVINGS_USD", "_SORT_VALUE"],
        ascending=[True, False, False],
    )
    return summary[columns].reset_index(drop=True)


def _cost_advisor_detail_options(board: pd.DataFrame | None) -> pd.DataFrame:
    if not _looks_like_frame(board) or board.empty:
        return pd.DataFrame()
    view = _decorate_cost_advisor_board(board).reset_index(drop=True).copy()
    view["_DETAIL_ID"] = view.index.astype(int)
    view["DETAIL_LABEL"] = view.apply(
        lambda row: (
            f"{row.get('SEVERITY', row.get('PRIORITY', 'Review'))} | "
            f"{row.get('ACTION_TYPE', 'Investigate')} | "
            f"{row.get('ENTITY', 'Unknown')}"
        ),
        axis=1,
    )
    return view
