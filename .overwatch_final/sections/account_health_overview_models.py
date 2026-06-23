"""Account Health Overview operating snapshot and intervention models."""
from __future__ import annotations

import streamlit as st

from sections.account_health_checklist import (
    _account_health_actionable_checklist,
    _annotate_account_health_checklist_readiness,
)
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.shell_helpers import render_shell_kpi_row, render_shell_snapshot
from utils.primitives import safe_float, safe_int


pd = lazy_pandas()

format_credits = _lazy_util("format_credits")
metric_confidence_label = _lazy_util("metric_confidence_label")
freshness_note = _lazy_util("freshness_note")


def _render_account_health_operating_snapshot(
    *,
    health_score: float,
    score_label: str,
    live_val: int,
    queued: int,
    err_count: int,
    last24: float,
    pct_delta: float,
    cost24: float,
    stor_tb: float,
    failed_tasks: int,
    hd: dict,
    live_source: str,
    control_mart_used: bool,
    control_mart_row,
) -> None:
    """Render the Account Health first-screen metrics without crowding the page."""
    render_shell_kpi_row((
        ("Health", f"{health_score:.0f} {score_label}".strip()),
        ("Failures", f"{err_count:,}"),
        ("Queue", f"{queued:,}"),
        ("Cost 24h", f"${cost24:,.0f} ({pct_delta:+.1f}%)"),
    ))
    with st.expander("Secondary metrics", expanded=False):
        render_shell_snapshot((
            ("Active", f"{live_val:,}"),
            ("Credits 24h", format_credits(last24)),
            ("Storage", f"{stor_tb:.1f} TB"),
            ("Failed Tasks", f"{failed_tasks:,}"),
        ))
        st.caption(
            " | ".join([
                metric_confidence_label("composite"),
                metric_confidence_label("exact") + " for input counts",
                str(hd.get("_control_mart_source", "Live telemetry")).replace("OVERWATCH mart", "Fast summary").replace("mart", "summary").replace("source", "input"),
                freshness_note(live_source),
            ])
        )
        if control_mart_used:
            st.caption(f"Snapshot: {control_mart_row.get('SNAPSHOT_TS', '')}")
        st.caption(f"Measurement basis: {hd.get('_account_health_detail_source', 'Unknown')}")


def _account_health_intervention_matrix(
    *,
    checklist: pd.DataFrame | None,
    control_board: pd.DataFrame | None = None,
    closure: pd.DataFrame | None = None,
    access_hygiene: pd.DataFrame | None = None,
    operability_fact: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a compact Account Health worklist from already-loaded account telemetry."""
    control = control_board if isinstance(control_board, pd.DataFrame) else pd.DataFrame()
    hygiene = access_hygiene if isinstance(access_hygiene, pd.DataFrame) else pd.DataFrame()
    fact = operability_fact if isinstance(operability_fact, pd.DataFrame) else pd.DataFrame()
    checks = pd.DataFrame() if checklist is None else _annotate_account_health_checklist_readiness(checklist)

    rows: list[dict] = []
    if not control.empty:
        for _, row in control.head(25).iterrows():
            control_state = str(row.get("CONTROL_STATE") or "Review")
            check_name = str(row.get("CHECK_NAME") or row.get("CHECK") or "Account Health")
            severity = str(row.get("SEVERITY") or "Medium")
            route = str(row.get("ROUTE") or "Account Health")
            queue_readiness = str(row.get("QUEUE_READINESS") or "")
            closure_state = "Open"
            if safe_int(row.get("OVERDUE_OPEN")) > 0:
                closure_state = "Overdue"
            elif safe_int(row.get("FIXED_WITHOUT_VERIFICATION")) > 0:
                closure_state = "Closed pending telemetry"
            elif safe_int(row.get("VERIFIED_CLOSURES")) > 0:
                closure_state = "Verified"
            scope = str(row.get("SCOPE_CONFIDENCE") or row.get("DATABASE_CONTEXT") or "Account-Level Control")

            control_upper = control_state.upper()
            if "BLOCK" in control_upper or closure_state in {"Overdue", "Closed pending telemetry"}:
                state = "Closure Block"
                rank = 0
                decision = "Hold green account-health claims until ticket, route, telemetry, and recovery status are current."
            elif queue_readiness != "Ready to Queue" or "REQUIRED" in control_upper:
                state = "Route Block"
                rank = 1
                decision = "Complete route, reviewer, and telemetry basis before queueing this account-health issue."
            elif severity.upper() in {"CRITICAL", "HIGH"}:
                state = "Intervene"
                rank = 2
                decision = "Work this high-risk account-health issue before routine monitoring."
            else:
                state = "Watch"
                rank = 4
                decision = "Keep on the daily checklist and retain trend telemetry."

            rows.append({
                "DBA_PRIORITY": f"P{rank}",
                "INTERVENTION_STATE": state,
                "SURFACE": check_name,
                "SEVERITY": severity,
                "ROUTE": route,
                "OWNER": str(row.get("OWNER") or "DBA"),
                "CONTROL_STATE": control_state,
                "QUEUE_READINESS": queue_readiness or "Unknown",
                "CLOSURE_READINESS": closure_state,
                "SCOPE_CONFIDENCE": scope,
                "COUNT": max(
                    safe_int(row.get("OPEN_ACTIONS")),
                    safe_int(row.get("ISSUE_SNAPSHOTS")),
                    safe_int(row.get("OVERDUE_OPEN")),
                    1,
                ),
                "NEXT_DECISION": decision,
                "PROOF_REQUIRED": str(row.get("PROOF_REQUIRED") or "route, ticket, telemetry status, recovery state"),
                "_RANK": rank,
            })

    existing_surfaces = {str(row["SURFACE"]).upper() for row in rows}
    if not hygiene.empty and "ACCOUNT ACCESS HYGIENE" not in existing_surfaces:
        severity_series = hygiene.get("SEVERITY", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
        high_rows = int(severity_series.isin(["CRITICAL", "HIGH"]).sum())
        route_blocks = 0
        if "QUEUE_READINESS" in hygiene.columns:
            route_blocks = int(hygiene["QUEUE_READINESS"].fillna("").astype(str).ne("Ready to Queue").sum())
        state = "Route Block" if route_blocks else "Intervene" if high_rows else "Watch"
        rank = 1 if route_blocks else 2 if high_rows else 4
        rows.append({
            "DBA_PRIORITY": f"P{rank}",
            "INTERVENTION_STATE": state,
            "SURFACE": "Account Access Hygiene",
            "SEVERITY": "High" if high_rows else "Medium",
            "ROUTE": "Security Monitoring",
            "OWNER": "DBA / Security",
            "CONTROL_STATE": "High-risk access review" if high_rows else "Access hygiene review",
            "QUEUE_READINESS": "Needs Routing Data" if route_blocks else "Ready to Queue",
            "CLOSURE_READINESS": "No recent action",
            "SCOPE_CONFIDENCE": "Account-Level Control",
            "COUNT": len(hygiene),
            "NEXT_DECISION": "Review privileged grants, failed logins, MFA gaps, and service-user exposure at account scope.",
            "PROOF_REQUIRED": "user, role/grant, MFA/IAM posture, telemetry status",
            "_RANK": rank,
        })

    if not fact.empty and "CONTROL_STATE" in fact.columns:
        blocked = fact["CONTROL_STATE"].fillna("").astype(str).str.contains("Blocked|Overdue|Required|Review", case=False, na=False)
        if int(blocked.sum()) and not rows:
            rows.append({
                "DBA_PRIORITY": "P3",
                "INTERVENTION_STATE": "Fact Review",
                "SURFACE": "Account Health control summary",
                "SEVERITY": "Medium",
                "ROUTE": "DBA Control Room",
                "OWNER": "DBA",
                "CONTROL_STATE": "Summary blocker",
                "QUEUE_READINESS": "Review",
                "CLOSURE_READINESS": "Review",
                "SCOPE_CONFIDENCE": "Mixed",
                "COUNT": int(blocked.sum()),
                "NEXT_DECISION": "Load the matching detailed surface only for the blocked control rows.",
                "PROOF_REQUIRED": "fact row, source surface, escalation route, telemetry status",
                "_RANK": 3,
            })

    if not rows and not checks.empty:
        actionable = _account_health_actionable_checklist(checks)
        if not actionable.empty:
            rows.append({
                "DBA_PRIORITY": "P4",
                "INTERVENTION_STATE": "Checklist Review",
                "SURFACE": "Daily DBA checklist",
                "SEVERITY": "Medium",
                "ROUTE": "DBA Control Room",
                "OWNER": "DBA",
                "CONTROL_STATE": "Checklist issue",
                "QUEUE_READINESS": "Review",
                "CLOSURE_READINESS": "No recent action",
                "SCOPE_CONFIDENCE": "Mixed",
                "COUNT": len(actionable),
                "NEXT_DECISION": "Queue only checklist rows with route, telemetry, and recovery expectations.",
                "PROOF_REQUIRED": "check telemetry, route, telemetry query",
                "_RANK": 4,
            })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["_RANK", "COUNT", "SURFACE"],
        ascending=[True, False, True],
    ).drop(columns=["_RANK"], errors="ignore").reset_index(drop=True)


__all__ = [
    "_account_health_intervention_matrix",
    "_render_account_health_operating_snapshot",
]
