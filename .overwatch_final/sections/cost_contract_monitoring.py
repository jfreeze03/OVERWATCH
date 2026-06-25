# sections/cost_contract_monitoring.py - Cost monitoring alert and incident helpers.
from __future__ import annotations

import streamlit as st

from config import DEFAULT_ALERT_EMAIL
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.cost_contract_advisor import _open_cost_action_frame
from sections.cost_contract_intelligence import (
    _cost_command_severity_rank,
    _first_frame_value,
    _state_frame,
)
from sections.shell_helpers import render_shell_snapshot
from utils.primitives import safe_float


pd = lazy_pandas()

alert_delivery_status_for_target = _lazy_util("alert_delivery_status_for_target")
alert_recipient_label = _lazy_util("alert_recipient_label")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _cost_alert_message(row: pd.Series, *keys: str, default: str = "") -> str:
    for key in keys:
        if key in row.index:
            value = row.get(key)
            try:
                if pd.isna(value):
                    continue
            except Exception:
                pass
            text = str(value or "").strip()
            if text:
                return text
    return default


def _build_cost_monitoring_alert_rows(
    *,
    root_cause: pd.DataFrame | None = None,
    correlation: pd.DataFrame | None = None,
    email_target: str = DEFAULT_ALERT_EMAIL,
) -> tuple[dict, pd.DataFrame]:
    """Create Alert Center-ready rows from loaded Cost & Contract monitoring telemetry."""
    email_target = str(email_target or DEFAULT_ALERT_EMAIL or "").strip()
    rows: list[dict] = []

    def add(
        *,
        severity: str,
        alert_type: str,
        entity: str,
        message: str,
        suggested_action: str,
        proof_query: str,
        route: str,
        owner: str,
        value_at_risk: float = 0.0,
        source_surface: str,
    ) -> None:
        severity = str(severity or "Medium").title()
        if severity not in {"Critical", "High", "Medium", "Watch", "Info"}:
            severity = "Medium"
        entity = str(entity or "Cost Monitoring").strip()
        rows.append({
            "SEVERITY": severity,
            "CATEGORY": "Cost Control",
            "ALERT_TYPE": alert_type,
            "ENTITY_NAME": entity,
            "MESSAGE": message,
            "SUGGESTED_ACTION": suggested_action,
            "PROOF_QUERY": proof_query,
            "ROUTE": route or "Cost & Contract",
            "OWNER": owner or "DBA / Cost owner",
            "EMAIL_TARGET": email_target,
            "DELIVERY_STATUS": alert_delivery_status_for_target(email_target),
            "STATUS": "New",
            "VALUE_AT_RISK_USD": round(safe_float(value_at_risk), 2),
            "SOURCE_SURFACE": source_surface,
        })

    if isinstance(root_cause, pd.DataFrame) and not root_cause.empty:
        view = root_cause.copy()
        view.columns = [str(col).upper() for col in view.columns]
        high = view[view.get("SEVERITY", pd.Series(index=view.index, dtype=str)).fillna("").astype(str).str.title().isin(["Critical", "High"])]
        if "VALUE_AT_RISK_USD" in high.columns:
            high = high.sort_values("VALUE_AT_RISK_USD", ascending=False)
        for _, row in high.head(6).iterrows():
            add(
                severity=_cost_alert_message(row, "SEVERITY", default="High"),
                alert_type="Cost Root Cause Candidate",
                entity=_cost_alert_message(row, "ENTITY", "DRIVER", default="Cost root cause"),
                message=_cost_alert_message(row, "EVIDENCE", default="Cost root-cause candidate requires review."),
                suggested_action=_cost_alert_message(row, "NEXT_ACTION", default="Open Cost & Contract root-cause drilldown."),
                proof_query=_cost_alert_message(row, "PROOF_REQUIRED", default="Record warehouse metering, run-rate, routing, and change telemetry."),
                route=_cost_alert_message(row, "ROUTE", default="Cost & Contract"),
                owner="DBA / Cost owner",
                value_at_risk=safe_float(row.get("VALUE_AT_RISK_USD", 0)),
                source_surface="Cost Spike Root Cause",
            )

    if isinstance(correlation, pd.DataFrame) and not correlation.empty:
        view = correlation.copy()
        view.columns = [str(col).upper() for col in view.columns]
        high = view[view.get("SEVERITY", pd.Series(index=view.index, dtype=str)).fillna("").astype(str).str.title().isin(["Critical", "High"])]
        for _, row in high.head(5).iterrows():
            add(
                severity=_cost_alert_message(row, "SEVERITY", default="High"),
                alert_type="Change Cost Correlation",
                entity=_cost_alert_message(row, "ENTITY", "CORRELATION", default="Change/cost correlation"),
                message=_cost_alert_message(row, "EVIDENCE", default="A recent change may explain cost movement."),
                suggested_action=_cost_alert_message(row, "NEXT_ACTION", default="Compare change telemetry to cost movement before tuning."),
                proof_query=_cost_alert_message(row, "PROOF_REQUIRED", default="Record change query_id, actor, ticket, and cost telemetry."),
                route=_cost_alert_message(row, "ROUTE", default="Security Monitoring"),
                owner="DBA / Cost owner",
                value_at_risk=0.0,
                source_surface="Change + Cost Correlation",
            )

    board = pd.DataFrame(rows)
    if board.empty:
        return {
            "alert_count": 0,
            "critical_high": 0,
            "email_target": email_target,
            "top_alert": "No loaded Cost & Contract alert candidates",
        }, board
    board["_SEVERITY_RANK"] = board["SEVERITY"].apply(_cost_command_severity_rank)
    board = board.sort_values(["_SEVERITY_RANK", "VALUE_AT_RISK_USD"], ascending=[True, False])
    board = board.drop_duplicates(subset=["ALERT_TYPE", "ENTITY_NAME", "MESSAGE"], keep="first")
    top = board.iloc[0]
    summary = {
        "alert_count": int(len(board)),
        "critical_high": int(board["SEVERITY"].isin(["Critical", "High"]).sum()),
        "email_target": email_target,
        "top_alert": f"{top.get('ALERT_TYPE')} - {top.get('ENTITY_NAME')}",
    }
    return summary, board.drop(columns=["_SEVERITY_RANK"], errors="ignore").reset_index(drop=True)


def _build_cost_incident_timeline(
    *,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
    alert_rows: pd.DataFrame | None = None,
    state: dict | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Build a compact incident narrative from cost movement to alert/action status."""
    state = state or st.session_state
    root_cause = _state_frame(state, "cost_contract_spike_root_cause")
    correlation = _state_frame(state, "cost_contract_change_cost_correlation")
    current_credits = safe_float(_first_frame_value(cockpit, "CURRENT_CREDITS", 0))
    prior_credits = safe_float(_first_frame_value(cockpit, "PRIOR_CREDITS", 0))
    top_wh = str(_first_frame_value(cockpit, "TOP_INCREASE_WAREHOUSE", "Cost scope") or "Cost scope")
    top_delta = safe_float(_first_frame_value(cockpit, "TOP_INCREASE_CREDITS", 0))
    pct_vs_30d = _first_frame_value(run_rate, "PCT_VS_30D_AVG", None)
    pct_vs_30d_float = safe_float(pct_vs_30d) if pct_vs_30d is not None and not pd.isna(pct_vs_30d) else 0.0
    open_cost_queue = _open_cost_action_frame(queue)

    rows: list[dict] = []

    def add(order: int, severity: str, step: str, entity: str, evidence: str, next_action: str, proof: str, route: str) -> None:
        rows.append({
            "EVENT_ORDER": int(order),
            "SEVERITY": severity,
            "INCIDENT_STEP": step,
            "ENTITY": entity,
            "EVIDENCE": evidence,
            "NEXT_ACTION": next_action,
            "PROOF_REQUIRED": proof,
            "ROUTE": route,
        })

    movement_severity = "Critical" if top_delta > 0 and pct_vs_30d_float >= 25 else "High" if top_delta > 0 else "Info"
    add(
        1,
        movement_severity,
        "Cost movement detected",
        top_wh,
        f"{top_wh}: {top_delta:+,.2f} credit delta; current {current_credits:,.2f} vs prior {prior_credits:,.2f}; 7d vs 30d {pct_vs_30d_float:+.1f}%.",
        "Explain the top cost mover before changing warehouse settings or workload routing.",
        "Complete-day run-rate plus FACT_WAREHOUSE_HOURLY current/prior warehouse metering.",
        "Cost & Contract > Cost Explorer > Warehouse",
    )

    if isinstance(root_cause, pd.DataFrame) and not root_cause.empty:
        root_view = root_cause.copy()
        root_view["_RANK"] = root_view.get("SEVERITY", pd.Series(index=root_view.index, dtype=str)).apply(_cost_command_severity_rank)
        root_view = root_view.sort_values(["_RANK"], ascending=True)
        root = root_view.iloc[0]
        add(
            2,
            _cost_alert_message(root, "SEVERITY", default="Medium"),
            "Root cause candidate",
            _cost_alert_message(root, "ENTITY", "DRIVER", default=top_wh),
            _cost_alert_message(root, "EVIDENCE", default="Root cause candidate loaded."),
            _cost_alert_message(root, "NEXT_ACTION", default="Confirm workload demand, workload mix, and setting changes before tuning."),
            _cost_alert_message(root, "PROOF_REQUIRED", default="Record Cost & Contract root-cause telemetry."),
            _cost_alert_message(root, "ROUTE", default="Cost & Contract"),
        )
    else:
        add(
            2,
            "Medium",
            "Root cause candidate",
            top_wh,
            "Root-cause board has not been loaded for this incident window.",
            "Refresh cost detail telemetry before assigning savings or tuning work.",
            "Cost Spike Root Cause board.",
            "Cost & Contract",
        )

    if isinstance(correlation, pd.DataFrame) and not correlation.empty:
        corr_view = correlation.copy()
        corr_view["_RANK"] = corr_view.get("SEVERITY", pd.Series(index=corr_view.index, dtype=str)).apply(_cost_command_severity_rank)
        corr_view = corr_view.sort_values(["_RANK"], ascending=True)
        corr = corr_view.iloc[0]
        add(
            3,
            _cost_alert_message(corr, "SEVERITY", default="Medium"),
            "Change correlation checked",
            _cost_alert_message(corr, "ENTITY", "CORRELATION", default=top_wh),
            _cost_alert_message(corr, "EVIDENCE", default="Change/cost correlation telemetry loaded."),
            _cost_alert_message(corr, "NEXT_ACTION", default="Compare change telemetry to the cost window before closure."),
            _cost_alert_message(corr, "PROOF_REQUIRED", default="Record change query_id, actor, ticket, and cost telemetry."),
            _cost_alert_message(corr, "ROUTE", default="Security Monitoring"),
        )
    else:
        add(
            3,
            "Medium",
            "Change correlation checked",
            top_wh,
            "Security Monitoring telemetry is available after refresh for this cost movement.",
            "Review Security Monitoring for the same company/environment before closing the incident as workload-only.",
            "FACT_OBJECT_CHANGE or Security Monitoring exception rows.",
            "Security Monitoring",
        )

    if isinstance(alert_rows, pd.DataFrame) and not alert_rows.empty:
        alert_view = alert_rows.copy()
        alert_view["_RANK"] = alert_view.get("SEVERITY", pd.Series(index=alert_view.index, dtype=str)).apply(_cost_command_severity_rank)
        alert_view = alert_view.sort_values(["_RANK", "VALUE_AT_RISK_USD"], ascending=[True, False])
        alert = alert_view.iloc[0]
        add(
            4,
            _cost_alert_message(alert, "SEVERITY", default="High"),
            "Alert routed",
            _cost_alert_message(alert, "ENTITY_NAME", default=top_wh),
            _cost_alert_message(alert, "MESSAGE", default="Cost Monitoring alert candidate is ready for Alert Center."),
            _cost_alert_message(alert, "SUGGESTED_ACTION", default="Route the alert to DBA / Cost owner email triage."),
            _cost_alert_message(alert, "PROOF_QUERY", default="Record the alert telemetry query."),
            "Alert Center",
        )
    else:
        add(
            4,
            "Info",
            "Alert routed",
            top_wh,
            "No Critical/High Cost & Contract alert candidate is ready.",
            "Keep monitoring; only route actionable Cost & Contract rows with telemetry.",
            "Cost Monitoring alert board.",
            "Alert Center",
        )

    add(
        5,
        "High" if not open_cost_queue.empty else "Info",
        "DBA action and measurement",
        f"{len(open_cost_queue):,} open cost action(s)",
        f"{len(open_cost_queue):,} open Cost & Contract action queue row(s) need route, baseline/current values, and closure status.",
        "Work measured actions first; keep savings estimated until post-period telemetry confirms the change.",
        "OVERWATCH_ACTION_QUEUE telemetry status, baseline/current, measured delta, and closure status.",
        "Cost & Contract > Cost Recommendations",
    )

    board = pd.DataFrame(rows).sort_values("EVENT_ORDER").reset_index(drop=True)
    summary = {
        "event_count": int(len(board)),
        "critical_high": int(board["SEVERITY"].isin(["Critical", "High"]).sum()) if not board.empty else 0,
        "top_step": str(board.iloc[0].get("INCIDENT_STEP") if not board.empty else "No incident timeline"),
        "next_action": str(board.iloc[0].get("NEXT_ACTION") if not board.empty else "Refresh cost detail."),
    }
    return summary, board


def _build_cost_monitoring_mart_operability() -> tuple[dict, pd.DataFrame]:
    rows = [
        {
            "COMPONENT": "Cost Monitoring signals",
            "STATE": "Ready",
            "DBA_USE": "Persists cost movement, Cortex quota, and change/cost signals.",
            "PROOF": "Snowflake summary facts and refresh telemetry.",
        },
        {
            "COMPONENT": "Cost incident timeline",
            "STATE": "Ready",
            "DBA_USE": "Turns cost spikes into ordered incident events for root cause, alerting, and action status.",
            "PROOF": "Timeline built from Cost Monitoring signals.",
        },
        {
            "COMPONENT": "Cost Monitoring refresh",
            "STATE": "Scheduled",
            "DBA_USE": "Runs after the control room mart so Alert Center can consume compact facts.",
            "PROOF": "Refresh order is recorded by the DBA platform team.",
        },
        {
            "COMPONENT": "Alert Center handoff",
            "STATE": "Email Ready" if DEFAULT_ALERT_EMAIL else "Config Required",
            "DBA_USE": "Routes Critical/High Cost Monitoring signals to the consolidated Alert Center.",
            "PROOF": f"Default target {alert_recipient_label(DEFAULT_ALERT_EMAIL)}; dedupes open alerts for 24 hours.",
        },
    ]
    board = pd.DataFrame(rows)
    summary = {
        "components": int(len(board)),
        "scheduled_components": int(board["STATE"].isin(["Scheduled", "Email Ready"]).sum()),
        "top_component": "Cost Monitoring refresh",
    }
    return summary, board


def _render_cost_monitoring_mart_and_incident_timeline(
    *,
    company: str,
    cockpit: pd.DataFrame,
    run_rate: pd.DataFrame,
    queue: pd.DataFrame,
) -> None:
    root_cause = st.session_state.get("cost_contract_spike_root_cause", pd.DataFrame())
    correlation = st.session_state.get("cost_contract_change_cost_correlation", pd.DataFrame())
    alert_summary, alert_board = _build_cost_monitoring_alert_rows(
        root_cause=root_cause,
        correlation=correlation,
        email_target=DEFAULT_ALERT_EMAIL,
    )
    st.session_state["cost_contract_monitoring_alert_summary"] = alert_summary
    st.session_state["cost_contract_monitoring_alerts"] = alert_board
    timeline_summary, timeline = _build_cost_incident_timeline(
        cockpit=cockpit,
        run_rate=run_rate,
        queue=queue,
        alert_rows=alert_board,
    )
    st.session_state["cost_contract_incident_timeline_summary"] = timeline_summary
    st.session_state["cost_contract_incident_timeline"] = timeline
    mart_summary, mart_board = _build_cost_monitoring_mart_operability()
    st.session_state["cost_contract_mart_operability_summary"] = mart_summary
    st.session_state["cost_contract_mart_operability"] = mart_board

    st.markdown("**Cost Monitoring Alerts & Timeline**")
    render_shell_snapshot((
        ("Alert Candidates", f"{alert_summary['alert_count']:,}"),
        ("Critical/High", f"{alert_summary['critical_high']:,}"),
        ("Timeline Events", f"{timeline_summary['event_count']:,}"),
        ("Status Lanes", f"{mart_summary['components']:,}"),
    ))

    if not alert_board.empty:
        render_priority_dataframe(
            alert_board,
            title="Alert Center-ready cost issues",
            priority_columns=[
                "SEVERITY", "ALERT_TYPE", "ENTITY_NAME", "VALUE_AT_RISK_USD",
                "MESSAGE", "SUGGESTED_ACTION", "PROOF_QUERY", "ROUTE", "EMAIL_TARGET",
            ],
            sort_by=["SEVERITY", "VALUE_AT_RISK_USD"],
            ascending=[True, False],
            raw_label="All Cost & Contract alert candidates",
            height=280,
            max_rows=8,
        )

    render_priority_dataframe(
        timeline,
        title="Cost incident timeline",
        priority_columns=[
            "EVENT_ORDER", "SEVERITY", "INCIDENT_STEP", "ENTITY",
            "EVIDENCE", "NEXT_ACTION", "PROOF_REQUIRED", "ROUTE",
        ],
        sort_by=["EVENT_ORDER"],
        ascending=[True],
        raw_label="All cost incident timeline rows",
        height=280,
        max_rows=6,
    )
