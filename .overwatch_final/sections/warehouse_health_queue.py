# sections/warehouse_health_queue.py - Warehouse Health action queue writers.
from __future__ import annotations

import pandas as pd
import streamlit as st
import sys

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT
from sections.base import lazy_util as _lazy_util
from sections.warehouse_health_actions import (
    _annotate_warehouse_admin_readiness,
    _route_label,
    _warehouse_approval_for,
    _warehouse_capacity_review_sql,
    _warehouse_owner_context,
)
from sections.warehouse_health_helpers import _warehouse_capacity_action_for
from sections.warehouse_health_sql import _warehouse_capacity_verification_sql
from utils.primitives import safe_float, safe_int


format_snowflake_error = _lazy_util("format_snowflake_error")
make_action_id = _lazy_util("make_action_id")
upsert_actions = _lazy_util("upsert_actions")
_DEFAULT_MAKE_ACTION_ID = make_action_id
_DEFAULT_UPSERT_ACTIONS = upsert_actions


def _facade_callable(name: str):
    facade = sys.modules.get("sections.warehouse_health")
    if facade is None:
        return None
    candidate = getattr(facade, name, None)
    return candidate if callable(candidate) else None


def _active_company() -> str:
    facade_getter = _facade_callable("get_active_company")
    if facade_getter is not None:
        return str(facade_getter() or DEFAULT_COMPANY)
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def _active_environment() -> str:
    facade_getter = _facade_callable("get_active_environment")
    if facade_getter is not None:
        return str(facade_getter() or DEFAULT_ENVIRONMENT)
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def _make_action_id(*args):
    if make_action_id is not _DEFAULT_MAKE_ACTION_ID:
        return make_action_id(*args)
    facade_make_action_id = _facade_callable("make_action_id")
    if facade_make_action_id is not None:
        return facade_make_action_id(*args)
    return make_action_id(*args)


def _upsert_actions(session, actions):
    if upsert_actions is not _DEFAULT_UPSERT_ACTIONS:
        return upsert_actions(session, actions)
    facade_upsert_actions = _facade_callable("upsert_actions")
    if facade_upsert_actions is not None:
        return facade_upsert_actions(session, actions)
    return upsert_actions(session, actions)


def _queue_capacity_findings(session, exceptions: pd.DataFrame) -> int:
    if exceptions is None or exceptions.empty:
        return 0
    company = _active_company()
    environment = _active_environment()
    exceptions = _annotate_warehouse_admin_readiness(exceptions)
    actions = []
    for _, row in exceptions.head(50).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        signal = str(row.get("SIGNAL", "Warehouse Pressure"))
        action_text, _ = _warehouse_capacity_action_for(signal)
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        finding = (
            f"{signal} on {wh}: "
            f"queued={safe_int(row.get('QUEUED_QUERIES')):,}, spill={safe_int(row.get('SPILL_QUERIES')):,}, "
            f"credits={safe_float(row.get('METERED_CREDITS')):,.2f}; "
            f"{row.get('PRESSURE_EVIDENCE', '')}."
        )
        actions.append({
            "Action ID": _make_action_id("Warehouse Capacity", wh, finding),
            "Source": "Warehouse Health - Capacity Brief",
            "Category": "Warehouse Capacity",
            "Severity": row.get("SEVERITY", "High"),
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Route": _route_label(row.get("OWNER", "Platform DBA")),
            "Email Target": row.get("EMAIL_TARGET", ""),
            "Reviewed By": row.get("REVIEWED_BY", ""),
            "Reviewed By": row.get("REVIEWED_BY", ""),
            "Escalation": _route_label(row.get("REVIEW_STATUS", row.get("APPROVER", "Warehouse Route / DBA Lead"))),
            "Workflow Route": row.get("WORKFLOW_ROUTE", "DBA Lead"),
            "Route Basis": _route_label(row.get("ALLOCATION_SOURCE", "")),
            "Route Detail": _route_label(row.get("ALLOCATION_BASIS", "")),
            "Finding": finding,
            "Action": (
                f"{action_text} {row.get('SAFE_CHANGE_PATH', '')} "
                f"Review from {_route_label(row.get('APPROVER', 'Warehouse DBA Lead'))} is required. "
                "Actual warehouse changes must be generated from the Warehouse Settings Manager."
            ),
            "Estimated Monthly Savings": 0,
            "Generated SQL Fix": _warehouse_capacity_review_sql(row),
            "Telemetry Query": verification_sql,
            "Reviewer": _route_label(row.get("APPROVER", "Warehouse Route / DBA Lead")),
            "Telemetry Status": "Requested",
            "Status Note": (
                f"{row.get('CHANGE_RISK', '')} "
                f"Escalation: {row.get('WORKFLOW_ROUTE', 'DBA Lead')}. "
                f"Rollback required: {row.get('ROLLBACK_REQUIRED', 'Yes')}; "
                f"impact telemetry required: {row.get('IMPACT_TELEMETRY_REQUIRED', 'No')}."
            ),
            "Recovery Status": (
                f"Baseline: {row.get('PRESSURE_EVIDENCE', '')}. "
                f"Closure uses post-change telemetry: {row.get('POST_CHANGE_VERIFICATION', '')}"
            ),
            "Recovery Audit State": "Warehouse Change Telemetry Pending",
            "Baseline Value": safe_float(row.get("CAPACITY_SCORE")),
            "Current Value": safe_float(row.get("CAPACITY_SCORE")),
            "Measured Delta": 0,
            "Company": company,
            "Environment": environment,
        })
    return _upsert_actions(session, actions)


def _queue_efficiency_findings(session, df_eff: pd.DataFrame) -> None:
    if df_eff is None or df_eff.empty:
        st.info("No efficiency findings to queue.")
        return
    company = _active_company()
    environment = _active_environment()
    actions = []
    for _, row in df_eff[df_eff["EFFICIENCY_SCORE"] < 70].head(100).iterrows():
        wh = str(row.get("WAREHOUSE_NAME", ""))
        score = safe_float(row.get("EFFICIENCY_SCORE", 0))
        queue = safe_float(row.get("QUEUE_SEC_PER_CREDIT", 0))
        spill = safe_float(row.get("REMOTE_SPILL_GB_PER_CREDIT", 0))
        credits = safe_float(row.get("METERED_CREDITS", 0))
        severity = "High" if score < 50 or queue > 10 or spill > 5 else "Medium"
        owner_context = _warehouse_owner_context({
            "WAREHOUSE_NAME": wh,
            "SIGNAL": "Efficiency",
            "METERED_CREDITS": credits,
        })
        verification_sql = _warehouse_capacity_verification_sql(
            wh,
            days=7,
            environment=environment,
            company=company,
        )
        approver = _warehouse_approval_for({
            "WAREHOUSE_NAME": wh,
            "SIGNAL": "Efficiency",
            "OWNER": owner_context.get("owner", ""),
        })
        finding = (
            f"{wh} efficiency review: queue sec/credit={queue:.2f}, "
            f"spill GB/credit={spill:.2f}; metered credits={credits:.2f}."
        )
        actions.append({
            "Action ID": _make_action_id("Warehouse Efficiency", wh, finding),
            "Source": "Warehouse Health - Efficiency",
            "Severity": severity,
            "Category": "Warehouse Efficiency",
            "Entity Type": "Warehouse",
            "Entity": wh,
            "Route": _route_label(owner_context.get("owner", "Platform DBA")),
            "Email Target": owner_context.get("route_email", ""),
            "Reviewed By": owner_context.get("review_primary", ""),
            "Reviewed By": owner_context.get("review_secondary", ""),
            "Escalation": _route_label(owner_context.get("review_group", approver)),
            "Workflow Route": owner_context.get("escalation", "DBA Lead"),
            "Route Basis": _route_label(owner_context.get("source", "")),
            "Route Detail": _route_label(owner_context.get("route_evidence", "")),
            "Finding": finding,
            "Action": (
                "Review queue, spill, cache, and credit/query patterns. Route setting changes through "
                "Warehouse Settings Manager so current values, review status, rollback plan, and post-change "
                "telemetry are captured."
            ),
            "Estimated Monthly Savings": 0.0,
            "Generated SQL Fix": "\n".join([
                f"-- Review {wh} efficiency before changing warehouse settings.",
                "-- If queue dominates, compare multi-cluster settings and workload routing.",
                "-- If spill dominates, inspect top spilling query profiles before considering size changes.",
                "-- Do not execute warehouse changes from this action; use Warehouse Settings Manager after review.",
            ]),
            "Telemetry Query": verification_sql,
            "Reviewer": _route_label(approver),
            "Telemetry Status": "Requested",
            "Status Note": (
                f"Efficiency review basis attached. Route basis: {owner_context.get('route_evidence', '')}. "
                "Setting changes require review status, rollback SQL, and post-change telemetry."
            ),
            "Recovery Status": (
                f"Baseline queue sec/credit={queue:.2f}; "
                f"remote spill GB/credit={spill:.2f}; metered credits={credits:.2f}. "
                "Closure uses queue/spill/credit telemetry for the same warehouse and environment."
            ),
            "Recovery Audit State": "Warehouse Efficiency Telemetry Pending",
            "Recovery SLA Target Hours": 24 if severity == "High" else 72,
            "Baseline Value": score,
            "Current Value": score,
            "Measured Delta": 0,
            "Company": company,
            "Environment": environment,
        })
    if not actions:
        st.success("No warehouses below the queue threshold.")
        return
    try:
        saved = _upsert_actions(session, actions)
        st.success(f"Saved {saved} warehouse efficiency findings to the action queue.")
    except Exception as e:
        st.error(f"Could not save to action queue: {format_snowflake_error(e)}")
        st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")
