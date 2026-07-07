"""Cost Center review-only action queue helpers."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.cost_center_models import (
    _annotate_allocation_quality,
    _row_text,
)
from sections.cost_center_sql import (
    _chargeback_cost_verification_sql,
    _warehouse_cost_verification_sql,
)
from utils import (
    credits_to_dollars,
    format_snowflake_error,
    get_active_environment,
    make_action_id,
    resolve_owner_context,
    safe_float,
    upsert_actions,
)


def _chargeback_action_owner(row: pd.Series) -> str:
    readiness = _row_text(row, "CHARGEBACK_READY").upper()
    route_source = _row_text(row, "ROUTE_SOURCE").upper()
    cost_attribution = _row_text(row, "COST_ATTRIBUTION")
    if "TAG" in route_source and cost_attribution:
        return cost_attribution
    user = _row_text(row, "USER_NAME")
    if readiness in {"NO", "REVIEW"}:
        return "DBA / Cost attribution"
    return user if user and user.upper() not in {"UNKNOWN USER", "UNKNOWN_USER"} else "DBA / Cost attribution"


def _chargeback_route_text(value: str, default: str = "") -> str:
    text = str(value or default or "").strip()
    replacements = {
        "MISSING_OWNER": "MISSING_ROUTE",
        "OWNER": "ROUTE",
        "Owner": "Route",
        "owner": "route",
        "evidence": "telemetry",
        "Evidence": "Telemetry",
        "proof": "telemetry",
        "Proof": "Telemetry",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _chargeback_action_sql_note(row: pd.Series, credits: float, est_cost: float) -> str:
    confidence = _row_text(row, "ALLOCATION_CONFIDENCE") or "Unknown"
    readiness = _row_text(row, "CHARGEBACK_READY") or "Unknown"
    basis = _row_text(row, "ALLOCATION_BASIS") or "Review allocation basis before chargeback."
    scope_review = _row_text(row, "SCOPE_REVIEW") or "None"
    database = _row_text(row, "DATABASE_NAME") or "NO_DATABASE_CONTEXT"
    env_rollup = _row_text(row, "ENVIRONMENT_ROLLUP") or _environment_rollup_for_cost(row)
    cost_attribution = _chargeback_route_text(_row_text(row, "COST_ATTRIBUTION") or "Missing")
    route_source = _chargeback_route_text(_row_text(row, "ROUTE_SOURCE") or "Missing")
    route_evidence = _chargeback_route_text(_row_text(row, "ROUTE_EVIDENCE"), "No route telemetry attached.")
    return "\n".join([
        "-- Chargeback review note, no state-changing SQL.",
        "-- Do not bill from this row until allocation measurement and route telemetry are attached.",
        f"-- Database: {database}",
        f"-- Environment rollup: {env_rollup}",
        f"-- Cost route: {cost_attribution}",
        f"-- Route basis: {route_source}",
        f"-- Route telemetry: {route_evidence}",
        f"-- Credits: {credits:,.4f}; estimated cost: ${est_cost:,.2f}",
        f"-- Allocation measurement: {confidence}",
        f"-- Chargeback status: {readiness}",
        f"-- Allocation basis: {basis}",
        f"-- Scope review: {scope_review}",
        "-- Required closure: attach route/tag telemetry or mark shared/unallocated with reason.",
    ])


def _queue_cost_outliers(session, df: pd.DataFrame, credit_price: float, source: str) -> None:
    if df is None or df.empty:
        st.info("No cost outliers to queue.")
        return
    if (
        "ALLOCATION_CONFIDENCE" not in df.columns
        or "CHARGEBACK_READY" not in df.columns
        or "ENVIRONMENT_ROLLUP" not in df.columns
    ):
        df = _annotate_allocation_quality(df)
    if "TOTAL_CREDITS" not in df.columns:
        if "ALLOCATED_CREDITS" in df.columns:
            df = df.copy()
            df["TOTAL_CREDITS"] = df["ALLOCATED_CREDITS"]
        else:
            st.info("No total-credit measure was available for cost outlier queueing.")
            return
    company = st.session_state.get("active_company", "ALFA")
    is_chargeback = "CHARGEBACK" in str(source or "").upper()
    actions = []
    baseline = safe_float(df["TOTAL_CREDITS"].median()) if "TOTAL_CREDITS" in df.columns else 0
    candidates = df.sort_values("TOTAL_CREDITS", ascending=False).head(20)
    for _, row in candidates.iterrows():
        active_env = get_active_environment()
        action_env = str(
            row.get("ENVIRONMENT_ROLLUP")
            or row.get("ENVIRONMENT")
            or (active_env if active_env != "ALL" else "")
            or ""
        )
        user = _row_text(row, "USER_NAME") or "Unknown user"
        wh = _row_text(row, "WAREHOUSE_NAME") or "Unknown warehouse"
        database = _row_text(row, "DATABASE_NAME")
        confidence = _row_text(row, "ALLOCATION_CONFIDENCE")
        readiness = _row_text(row, "CHARGEBACK_READY")
        scope_review = _row_text(row, "SCOPE_REVIEW")
        route_source = _row_text(row, "ROUTE_SOURCE")
        route_evidence = _row_text(row, "ROUTE_EVIDENCE")
        credits = safe_float(row.get("TOTAL_CREDITS", 0))
        est_cost = credits_to_dollars(credits, credit_price)
        if baseline > 0 and credits < baseline * 2 and est_cost < 500:
            continue
        if is_chargeback and database:
            entity = f"{database} / {user} on {wh}"
        else:
            entity = f"{user} on {wh}"
        monthly_savings = max(0.0, est_cost * 0.15)
        confidence_note = f" ({confidence})" if confidence else ""
        readiness_note = f"; chargeback status: {readiness}" if readiness else ""
        scope_note = f"; scope review: {scope_review}" if scope_review and scope_review != "None" else ""
        owner_note = f"; route telemetry: {route_source}" if route_source else ""
        finding = (
            f"{entity} consumed {credits:,.2f} credits (${est_cost:,.2f}) "
            f"in the selected window{confidence_note}{readiness_note}{scope_note}{owner_note}"
        )
        verification_sql = _chargeback_cost_verification_sql(
            row,
            lookback_days=30,
            company=str(row.get("COMPANY") or company),
        )
        action_text = (
            "Review route/tag telemetry, confirm whether this is billable or shared/unallocated, "
            "and rerun the telemetry query for the next complete period before closing."
            if is_chargeback
            else "Review query patterns, warehouse sizing, cache use, and whether the workload can be optimized or scheduled differently."
        )
        if readiness and readiness.upper() in {"NO", "REVIEW"}:
            action_text = (
                f"{action_text} This row is not cleanly chargeback-ready; resolve scope/route telemetry before billing."
            )
        if is_chargeback and "TAG" not in route_source.upper():
            action_text = (
                f"{action_text} Missing Snowflake route-tag telemetry; attach cost, data, or app allocation telemetry "
                "or classify this as shared/unallocated."
            )
        if route_evidence:
            action_text = f"{action_text} Route telemetry: {route_evidence[:300]}"
        action_owner = _chargeback_action_owner(row) if is_chargeback else (user if user != "Unknown user" else "DBA")
        owner_context = resolve_owner_context(
            row,
            entity=entity,
            entity_type="Cost Control" if is_chargeback else "Warehouse",
            owner=action_owner,
            category="Cost Control",
            alert_type="Chargeback Review" if is_chargeback else "Cost Outlier",
        )
        action_owner = owner_context.get("OWNER") or action_owner
        approver = (
            owner_context.get("REVIEW_GROUP")
            or ("Cost attribution / Cost Route" if is_chargeback else "Cost attribution / Workload Route")
        )
        review_note = (
            "Allocated/estimated chargeback requires route/tag telemetry review before billing. "
            "Close only after the next complete period measurement confirms the billable driver or documents shared/unallocated treatment."
            if is_chargeback
            else "Cost remediation requires workload review before scheduling or warehouse-setting changes. "
            "Close only after the next complete period measurement confirms the measured credit delta."
        )
        actions.append({
            "Action ID": make_action_id("Cost Outlier", entity, finding),
            "Source": source,
            "Severity": "Medium" if est_cost < 2500 else "High",
            "Category": "Chargeback Review" if is_chargeback else "Cost",
            "Entity Type": "Database/User/Warehouse" if is_chargeback else "User/Warehouse",
            "Entity": entity,
            "Owner": action_owner,
            "Approver": approver,
            "Route Email": owner_context.get("ROUTE_EMAIL", ""),
            "Review Primary": owner_context.get("REVIEW_PRIMARY", ""),
            "Review Secondary": owner_context.get("REVIEW_SECONDARY", ""),
            "Review Group": approver,
            "Review Target": owner_context.get("REVIEW_TARGET", ""),
            "Route Source": owner_context.get("ROUTE_SOURCE", route_source),
            "Route Evidence": owner_context.get("ROUTE_EVIDENCE", route_evidence),
            "Finding": finding,
            "Action": action_text,
            "Estimated Monthly Savings": round(monthly_savings, 2),
            "Generated SQL Fix": _chargeback_action_sql_note(row, credits, est_cost)[:8000],
            "Proof Query": verification_sql[:8000],
            "Company": company,
            "Environment": action_env,
            "Verification Status": "Pending",
            "Verification Query": verification_sql[:8000],
            "Baseline Value": 0,
            "Current Value": round(credits, 4),
            "Measured Delta": round(credits, 4),
            "Verification Status": "Requested",
            "Verification Note": review_note,
            "Recovery SLA State": "Chargeback Telemetry Pending" if is_chargeback else "Savings Measurement Pending",
            "Recovery SLA Target Hours": 168.0,
        })
    if not actions:
        st.success("No cost outliers crossed the queue threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} cost outliers to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")


def _warehouse_cost_control_action(
    row: pd.Series,
    *,
    credit_price: float,
    period_label: str,
    company: str,
) -> dict:
    wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
    delta = safe_float(row.get("CREDIT_DELTA", 0))
    current = safe_float(row.get("CURRENT_CREDITS", row.get("TOTAL_CREDITS", 0)))
    prior = safe_float(row.get("PRIOR_CREDITS", 0))
    est_delta_cost = credits_to_dollars(delta, credit_price)
    owner = _chargeback_route_text(str(
        row.get("OWNER")
        or row.get("WAREHOUSE_OWNER")
        or row.get("OWNER_ROLE")
        or "DBA / Cost attribution"
    ))
    base_owner = owner
    owner_context = resolve_owner_context(
        row,
        entity=wh,
        entity_type="Warehouse",
        owner=owner,
        category="Cost Control",
        alert_type="Bill Increase",
    )
    owner = owner_context.get("OWNER") or owner
    confidence = "Exact warehouse metering"
    if delta < 0:
        severity = "Low"
    elif est_delta_cost >= 5000 or delta >= 1000:
        severity = "Critical"
    elif est_delta_cost >= 1000 or delta >= 100:
        severity = "High"
    else:
        severity = "Medium"
    finding = (
        f"{wh} increased by {delta:,.2f} exact metered credits "
        f"(${est_delta_cost:,.2f}) during {period_label}."
    )
    action = (
        f"Route to {owner}, separate workload growth from idle/overhead, "
        "review top users/query types, and use the Warehouse Settings Manager for any ALTER WAREHOUSE change. "
        "Measure savings in the next complete period before marking fixed."
    )
    approver = (
        f"{owner} / Cost attribution"
        if base_owner and base_owner.upper() not in {"DBA", "DBA / COST ATTRIBUTION", "UNKNOWN"}
        else owner_context.get("REVIEW_GROUP") or "Cost attribution / Warehouse Route"
    )
    review_note = (
        f"Exact warehouse metering for {period_label}. Review is required before any warehouse "
        "setting change; close only after the next complete period measurement query shows the "
        "reviewed change reduced or justified the delta."
    )
    generated_sql = (
        "-- Cost-control plan, not an automatic fix.\n"
        f"-- Warehouse: {wh}\n"
        f"-- Current credits: {current:,.4f}; prior credits: {prior:,.4f}; delta credits: {delta:,.4f}\n"
        "-- If idle dominates: review auto-suspend and query schedule.\n"
        "-- If queue/spill dominates: use Cost & Contract warehouse capacity telemetry and the reviewed Warehouse Settings Manager before changing size/scaling.\n"
        "-- If workload growth dominates: route to query/procedure team for tuning."
    )
    proof = _warehouse_cost_verification_sql(wh)
    return {
        "Action ID": make_action_id("Bill Increase", wh, finding),
        "Source": "Cost & Contract - Explain This Bill",
        "Severity": severity,
        "Category": "Cost Control",
        "Entity Type": "Warehouse",
        "Entity": wh,
        "Owner": owner,
        "Approver": approver,
        "Route Email": owner_context.get("ROUTE_EMAIL", ""),
        "Review Primary": owner_context.get("REVIEW_PRIMARY", ""),
        "Review Secondary": owner_context.get("REVIEW_SECONDARY", ""),
        "Review Group": approver,
        "Review Target": owner_context.get("REVIEW_TARGET", ""),
        "Route Source": _chargeback_route_text(owner_context.get("ROUTE_SOURCE", "")),
        "Route Evidence": _chargeback_route_text(owner_context.get("ROUTE_EVIDENCE", "")),
        "Finding": finding,
        "Action": f"{confidence}. {action}",
        "Estimated Monthly Savings": round(max(0.0, est_delta_cost * 0.25), 2),
        "Generated SQL Fix": generated_sql[:8000],
        "Proof Query": proof[:8000],
        "Company": company,
        "Environment": str(row.get("ENVIRONMENT") or ""),
        "Verification Status": "Pending",
        "Verification Query": proof[:8000],
        "Baseline Value": round(prior, 4),
        "Current Value": round(current, 4),
        "Measured Delta": round(delta, 4),
        "Verification Status": "Requested",
        "Verification Note": review_note,
        "Recovery SLA State": "Savings Measurement Pending",
        "Recovery SLA Target Hours": 168.0,
    }


def _queue_bill_exceptions(
    session,
    warehouse_deltas: pd.DataFrame,
    credit_price: float,
    period_label: str,
) -> None:
    if warehouse_deltas is None or warehouse_deltas.empty:
        st.info("No bill exceptions to queue.")
        return
    company = st.session_state.get("active_company", "ALFA")
    actions = []
    for _, row in warehouse_deltas.sort_values("CREDIT_DELTA", ascending=False).head(10).iterrows():
        wh = str(row.get("WAREHOUSE_NAME") or "Unknown warehouse")
        delta = safe_float(row.get("CREDIT_DELTA", 0))
        if delta <= 0:
            continue
        est_delta_cost = credits_to_dollars(delta, credit_price)
        if delta < 5 and est_delta_cost < 100:
            continue
        actions.append(_warehouse_cost_control_action(
            row,
            credit_price=credit_price,
            period_label=period_label,
            company=company,
        ))
    if not actions:
        st.success("No warehouse increases crossed the exception threshold.")
        return
    try:
        saved = upsert_actions(session, actions)
        st.success(f"Saved {saved} bill exceptions to the action queue.")
    except Exception as e:
        st.error(f"Could not save bill exceptions: {format_snowflake_error(e)}")


__all__ = ['_chargeback_action_owner', '_chargeback_route_text', '_chargeback_action_sql_note', '_queue_cost_outliers', '_warehouse_cost_control_action', '_queue_bill_exceptions']
