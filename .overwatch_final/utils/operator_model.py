"""Simplified operator model for the four-area OVERWATCH product.

This module translates compact mart summaries into operator-facing health,
incident, and recommendation rows. It deliberately avoids exposing mart names,
score formulas, or release/proof workflow internals to normal users.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from config import DEFAULT_COMPANY, DEFAULT_DAY_WINDOW, DEFAULT_ENVIRONMENT
from runtime_state import ACTIVE_COMPANY, GLOBAL_ENVIRONMENT, get_state
from utils.command_board import (
    FIRST_PAINT_CACHE_KEY,
    CommandBoard,
    command_board_scope,
    empty_command_board,
)


SEVERITIES = ("Critical", "Warning", "Info")
CATEGORIES = ("Cost", "Performance", "Security", "Pipeline", "Change", "Data Freshness")


@dataclass(frozen=True)
class OperatorSnapshot:
    """Operator-facing summary derived from compact mart data."""

    board: CommandBoard
    incidents: pd.DataFrame
    recommendations: pd.DataFrame
    health: str
    health_reason: str
    loaded_at: str


def current_operator_scope() -> tuple[str, str, int]:
    """Return the active operator scope without reading Snowflake."""
    company = str(get_state(ACTIVE_COMPANY, DEFAULT_COMPANY) or DEFAULT_COMPANY)
    environment = str(get_state(GLOBAL_ENVIRONMENT, DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)
    return company, environment, DEFAULT_DAY_WINDOW


def load_operator_snapshot() -> OperatorSnapshot:
    """Load cached/local command summary state and convert it to operator rows.

    The simplified operator shell must not open a Snowflake session on first
    paint. Existing mart/cache refresh flows can hydrate FIRST_PAINT_CACHE_KEY;
    until then, normal users still get a fast, actionable fallback shell.
    """
    company, environment, days = current_operator_scope()
    scope = command_board_scope(company, environment, days)
    cached = get_state(FIRST_PAINT_CACHE_KEY)
    if (
        isinstance(cached, CommandBoard)
        and str(cached.meta.get("company") or "").upper() == scope[0]
        and str(cached.meta.get("environment") or "").upper() == scope[1]
        and int(cached.meta.get("days") or 0) == scope[2]
    ):
        board = cached
    else:
        board = empty_command_board(company=company, environment=environment, days=days, state="Awaiting refresh")
    summary = dict(board.summary or {})
    incidents = build_incident_queue(summary, company)
    recommendations = build_recommendations(summary, incidents, company)
    health, reason = operator_health(summary, incidents)
    loaded_at = str(board.meta.get("loaded_at") or datetime.now().isoformat(timespec="seconds"))
    if not bool(board.meta.get("available")):
        loaded_at = "Awaiting refresh"
    return OperatorSnapshot(
        board=board,
        incidents=incidents,
        recommendations=recommendations,
        health=health,
        health_reason=reason,
        loaded_at=loaded_at,
    )


def number(value: Any, default: float = 0.0) -> float:
    """Coerce numeric summary values safely."""
    try:
        result = float(value if value is not None else default)
        return default if result != result else result
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    """Coerce integer summary values safely."""
    try:
        return int(round(number(value, default)))
    except (TypeError, ValueError):
        return default


def money(value: Any) -> str:
    """Format a dollar value for compact operator tiles."""
    amount = number(value)
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if abs(amount) >= 1_000:
        return f"${amount / 1_000:.1f}K"
    return f"${amount:,.0f}"


def short_number(value: Any, suffix: str = "") -> str:
    """Format compact count/quantity values."""
    amount = number(value)
    if abs(amount) >= 1_000_000:
        base = f"{amount / 1_000_000:.1f}M"
    elif abs(amount) >= 1_000:
        base = f"{amount / 1_000:.1f}K"
    else:
        base = f"{amount:,.0f}"
    return f"{base}{suffix}"


def _incident(
    *,
    severity: str,
    category: str,
    company: str,
    owner: str,
    impact: str,
    action: str,
    details: str,
) -> dict[str, str]:
    return {
        "Severity": severity if severity in SEVERITIES else "Info",
        "Category": category if category in CATEGORIES else "Change",
        "Company": company,
        "Owner": owner or "Owner Gap",
        "Impact": impact,
        "Recommended Action": action,
        "Details": details,
    }


def build_incident_queue(summary: dict[str, Any], company: str) -> pd.DataFrame:
    """Return one simplified incident queue from compact summary signals."""
    rows: list[dict[str, str]] = []
    scope = str(company or DEFAULT_COMPANY).upper()
    failed_tasks = integer(summary.get("failed_tasks"))
    failed_queries = integer(summary.get("failed_queries"))
    queued_queries = integer(summary.get("queued_queries"))
    queue_seconds = number(summary.get("queue_seconds"))
    spill_gb = number(summary.get("remote_spill_gb"))
    failed_logins = integer(summary.get("failed_logins"))
    privileged_grants = integer(summary.get("privileged_grants"))
    critical_alerts = integer(summary.get("critical_high_alerts"))
    stale_sources = integer(summary.get("stale_sources"))
    spend_delta = number(summary.get("spend_delta_cost_usd"))
    cortex_cost = number(summary.get("cortex_cost_usd"))

    if critical_alerts > 0:
        rows.append(_incident(
            severity="Critical",
            category="Change",
            company=scope,
            owner="On-call DBA",
            impact=f"{critical_alerts} critical/high monitoring signals are open.",
            action="Open the incident details, assign an owner, and work the highest severity signal first.",
            details="Consolidated active monitoring signals from the latest summary refresh.",
        ))
    if failed_tasks > 0:
        rows.append(_incident(
            severity="Critical",
            category="Pipeline",
            company=scope,
            owner="Pipeline Owner or Owner Gap",
            impact=f"{failed_tasks} task or procedure runs failed in the active window.",
            action="Identify the failed root task/procedure, confirm downstream impact, then rerun only after review.",
            details="Pipeline failure summary; detailed task/procedure telemetry stays behind advanced diagnostics.",
        ))
    if failed_queries > 0:
        severity = "Critical" if failed_queries >= 10 else "Warning"
        rows.append(_incident(
            severity=severity,
            category="Performance",
            company=scope,
            owner="DBA / Workload Owner",
            impact=f"{failed_queries} failed queries are present in the active window.",
            action="Review failed query patterns before changing warehouse size or session settings.",
            details="Query failure summary from recent workload telemetry.",
        ))
    if queued_queries > 0 or queue_seconds > 0 or spill_gb > 0:
        rows.append(_incident(
            severity="Warning",
            category="Performance",
            company=scope,
            owner="DBA / Warehouse Owner",
            impact=(
                f"{queued_queries} queued queries, {short_number(queue_seconds, 's')} queue time, "
                f"{short_number(spill_gb, 'GB')} remote spill."
            ),
            action="Check warehouse pressure and the top driver before resizing or tuning SQL.",
            details="Performance pressure summary; detailed query evidence is available in advanced diagnostics.",
        ))
    if spend_delta > 0:
        rows.append(_incident(
            severity="Warning",
            category="Cost",
            company=scope,
            owner="Cost Owner or Owner Gap",
            impact=f"Spend is up {money(spend_delta)} versus the comparison window.",
            action="Review warehouse and Cortex drivers, then prioritize the top savings recommendation.",
            details="Cost risk is based on compact daily/run-rate summary telemetry.",
        ))
    if cortex_cost > 0:
        rows.append(_incident(
            severity="Info" if cortex_cost < 500 else "Warning",
            category="Cost",
            company=scope,
            owner="AI / Platform Owner",
            impact=f"Cortex spend is {money(cortex_cost)} in the selected window.",
            action="Watch user/source growth and set an owner before Cortex spend becomes material.",
            details="Cortex spend is retained as a cost-risk signal, not a separate primary dashboard.",
        ))
    if failed_logins > 0 or privileged_grants > 0:
        rows.append(_incident(
            severity="Critical" if privileged_grants > 0 else "Warning",
            category="Security",
            company=scope,
            owner="Security / IAM Owner",
            impact=f"{failed_logins} failed logins and {privileged_grants} privileged grants detected.",
            action="Validate the user, role, IP/source, and approval path before changing access.",
            details="Security risk summary from login and grant telemetry.",
        ))
    if stale_sources > 0:
        rows.append(_incident(
            severity="Warning",
            category="Data Freshness",
            company=scope,
            owner="OVERWATCH Admin",
            impact=f"{stale_sources} telemetry inputs look stale or missing.",
            action="Run refresh diagnostics in Settings before making decisions from stale data.",
            details="Freshness rollup from the compact command summary.",
        ))

    if not rows:
        rows.append(_incident(
            severity="Info",
            category="Change",
            company=scope,
            owner="On-call DBA",
            impact="No critical operator incidents are visible in the current summary.",
            action="Continue monitoring; use Settings only when diagnostics or configuration are needed.",
            details="No action is required from the compact summary.",
        ))
    return pd.DataFrame(rows)


def build_recommendations(
    summary: dict[str, Any],
    incidents: pd.DataFrame,
    company: str,
) -> pd.DataFrame:
    """Return the top operator recommendations without proof workflow ceremony."""
    rows: list[dict[str, str]] = []
    scope = str(company or DEFAULT_COMPANY).upper()
    if integer(summary.get("failed_tasks")) > 0:
        rows.append({
            "Priority": "1",
            "Recommendation": "Stabilize failed pipelines",
            "Owner": "Pipeline Owner or Owner Gap",
            "Value / Risk": "Protect downstream SLAs",
            "Next Action": "Open pipeline incident details and verify rerun safety.",
            "Company": scope,
        })
    if number(summary.get("spend_delta_cost_usd")) > 0:
        rows.append({
            "Priority": "2",
            "Recommendation": "Review cost spike drivers",
            "Owner": "Cost Owner or Owner Gap",
            "Value / Risk": f"{money(summary.get('spend_delta_cost_usd'))} spend movement",
            "Next Action": "Open Optimization and validate the highest-cost warehouse/user/source.",
            "Company": scope,
        })
    if integer(summary.get("queued_queries")) > 0 or number(summary.get("remote_spill_gb")) > 0:
        rows.append({
            "Priority": "3",
            "Recommendation": "Reduce warehouse pressure",
            "Owner": "DBA / Warehouse Owner",
            "Value / Risk": "Improve query reliability before resizing",
            "Next Action": "Separate capacity pressure from query design and lock contention.",
            "Company": scope,
        })
    if integer(summary.get("failed_logins")) > 0 or integer(summary.get("privileged_grants")) > 0:
        rows.append({
            "Priority": "4",
            "Recommendation": "Review security changes",
            "Owner": "Security / IAM Owner",
            "Value / Risk": "Reduce access drift risk",
            "Next Action": "Confirm role grants, login source, and approval path.",
            "Company": scope,
        })
    if integer(summary.get("stale_sources")) > 0:
        rows.append({
            "Priority": "5",
            "Recommendation": "Refresh stale telemetry",
            "Owner": "OVERWATCH Admin",
            "Value / Risk": "Protect decision quality",
            "Next Action": "Open Settings refresh diagnostics and validate source freshness.",
            "Company": scope,
        })
    if not rows and not incidents.empty:
        rows.append({
            "Priority": "1",
            "Recommendation": "No immediate operator action",
            "Owner": "On-call DBA",
            "Value / Risk": "Current state appears healthy",
            "Next Action": "Keep monitoring the command center summary.",
            "Company": scope,
        })
    return pd.DataFrame(rows[:5])


def operator_health(summary: dict[str, Any], incidents: pd.DataFrame) -> tuple[str, str]:
    """Return Critical/Warning/Healthy for the command center."""
    if isinstance(incidents, pd.DataFrame) and not incidents.empty:
        severities = set(incidents["Severity"].astype(str))
        if "Critical" in severities:
            return "Critical", "A critical incident needs owner review."
        if "Warning" in severities:
            return "Warning", "One or more warning conditions need attention."
    if not bool(summary.get("loaded")):
        return "Warning", "Summary data is not refreshed yet."
    return "Healthy", "No critical operator incident is visible."


def severity_counts(incidents: pd.DataFrame) -> dict[str, int]:
    """Count simplified incident severities."""
    counts = {severity: 0 for severity in SEVERITIES}
    if isinstance(incidents, pd.DataFrame) and "Severity" in incidents.columns:
        for severity, count in incidents["Severity"].value_counts().items():
            if str(severity) in counts:
                counts[str(severity)] = int(count)
    return counts
