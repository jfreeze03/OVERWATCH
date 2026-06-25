"""Import-safe command brief contracts for primary OVERWATCH sections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from sections.first_paint_contracts import get_first_paint_contract


@dataclass(frozen=True)
class SectionCommandContract:
    """Static copy and fallback shape for an auto-populated command brief."""

    section: str
    default_view: str
    detail_cta: str
    metric_labels: tuple[str, ...]
    expected_lanes: tuple[str, ...]
    source_table: str
    required_sources: tuple[str, ...]
    target_freshness_minutes: int
    unavailable_headline: str
    unavailable_summary: str
    top_signal_label: str
    top_signal_detail: str
    next_actions: tuple[tuple[str, str, str, str], ...]


def _contract(
    section: str,
    *,
    metric_labels: tuple[str, ...],
    source_table: str,
    required_sources: tuple[str, ...],
    target_freshness_minutes: int,
    unavailable_headline: str,
    unavailable_summary: str,
    top_signal_label: str,
    top_signal_detail: str,
    next_actions: tuple[tuple[str, str, str, str], ...],
) -> SectionCommandContract:
    first_paint = get_first_paint_contract(section)
    return SectionCommandContract(
        section=first_paint.section,
        default_view=first_paint.default_view,
        detail_cta=first_paint.explicit_load_cta,
        metric_labels=metric_labels,
        expected_lanes=first_paint.expected_lanes,
        source_table=source_table,
        required_sources=required_sources,
        target_freshness_minutes=int(target_freshness_minutes),
        unavailable_headline=unavailable_headline,
        unavailable_summary=unavailable_summary,
        top_signal_label=top_signal_label,
        top_signal_detail=top_signal_detail,
        next_actions=next_actions,
    )


SECTION_COMMAND_CONTRACTS: Mapping[str, SectionCommandContract] = {
    "Executive Landing": _contract(
        "Executive Landing",
        source_table="MART_SECTION_COMMAND_BRIEF",
        required_sources=("MART_EXECUTIVE_OBSERVABILITY", "MART_DBA_CONTROL_ROOM", "FACT_COST_DAILY", "ALERT_EVENTS"),
        target_freshness_minutes=60,
        metric_labels=(
            "Platform state",
            "Major issues",
            "Cost movement",
            "Cortex AI risk",
            "Operational risk",
            "Security risk",
            "Open actions",
            "Freshness",
        ),
        unavailable_headline="Executive command brief needs the summary mart.",
        unavailable_summary=(
            "Enable the executive observability mart to populate leadership status, cost movement, "
            "Cortex AI risk, and open actions automatically."
        ),
        top_signal_label="Top executive decision",
        top_signal_detail="Review cost, operational, and security signals before loading the full snapshot.",
        next_actions=(
            ("Review Cortex AI Cost & Predictive Alerts", "Open the Cortex AI financial-risk lane.", "Cost & Contract", "Cortex AI"),
            ("Investigate Active Alerts", "Open current alert families and route the highest-severity item.", "Alert Center", "Active Alerts"),
            ("Open DBA Cockpit", "Open DBA-owned failures, queue pressure, and action status.", "DBA Control Room", "Morning Cockpit"),
        ),
    ),
    "DBA Control Room": _contract(
        "DBA Control Room",
        source_table="MART_SECTION_COMMAND_BRIEF",
        required_sources=("MART_DBA_CONTROL_ROOM", "FACT_QUERY_HOURLY", "FACT_TASK_RUN", "OVERWATCH_ACTION_QUEUE"),
        target_freshness_minutes=30,
        metric_labels=(
            "Failed queries",
            "Failed tasks",
            "Failed procedures",
            "Queue pressure",
            "Credits / cost",
            "Cortex cost",
            "Security warnings",
            "Recent changes",
        ),
        unavailable_headline="DBA command brief needs the control-room mart.",
        unavailable_summary=(
            "Enable the latest control-room snapshot to populate failures, cost pressure, "
            "queue pressure, security warnings, and recent changes automatically."
        ),
        top_signal_label="Top DBA action",
        top_signal_detail="Start with the highest operational exception, then load investigation detail if proof is needed.",
        next_actions=(
            ("Failure Triage", "Review failed SQL, task, procedure, copy, and SLA signals.", "DBA Control Room", "Failure Triage"),
            ("Performance Watch", "Review queue, spilling, blocked, and long-running pressure.", "DBA Control Room", "Performance Watch"),
            ("Cost Watch", "Review spend pressure, Cortex cost, and largest drivers.", "DBA Control Room", "Cost Watch"),
        ),
    ),
    "Alert Center": _contract(
        "Alert Center",
        source_table="MART_SECTION_COMMAND_BRIEF",
        required_sources=("ALERT_EVENTS", "OVERWATCH_ACTION_QUEUE", "ALERT_NOTIFICATION_LOG"),
        target_freshness_minutes=15,
        metric_labels=(
            "Active alerts",
            "Critical / high",
            "Overdue",
            "Cortex predictive",
            "Cost alerts",
            "Reliability",
            "Security",
            "Notification failures",
        ),
        unavailable_headline="Alert command brief needs alert summary telemetry.",
        unavailable_summary=(
            "Enable alert summary marts to populate active, critical, Cortex predictive, cost, "
            "reliability, security, and delivery lanes automatically."
        ),
        top_signal_label="Top alert family",
        top_signal_detail="Work the highest severity family first; load alert rows only when row-level evidence is needed.",
        next_actions=(
            ("Load Alert Rows", "Load detailed rows for the selected alert family.", "Alert Center", "Active Alerts"),
            ("Open Cortex Predictive", "Review forecasted Cortex spend and anomaly alerts.", "Alert Center", "Cortex Predictive Alerts"),
            ("Review Security Alerts", "Open security alert family and access-risk routes.", "Alert Center", "Security Alerts"),
        ),
    ),
    "Cost & Contract": _contract(
        "Cost & Contract",
        source_table="MART_SECTION_COMMAND_BRIEF",
        required_sources=("FACT_COST_DAILY", "FACT_CORTEX_DAILY", "FACT_COST_MONITORING_SIGNAL"),
        target_freshness_minutes=60,
        metric_labels=(
            "Total spend",
            "Spend movement",
            "Forecast / run-rate",
            "Cortex AI spend",
            "Cortex predictive alerts",
            "Budget / contract risk",
            "Top driver",
            "Savings actions",
        ),
        unavailable_headline="Cost command brief needs cost summary telemetry.",
        unavailable_summary=(
            "Enable cost summary marts to populate spend, run-rate, Cortex AI cost, predictive alerts, "
            "budget risk, top driver, and savings actions automatically."
        ),
        top_signal_label="Top cost signal",
        top_signal_detail="Review the largest movement or Cortex risk before loading detailed cost explorer rows.",
        next_actions=(
            ("Review Cortex AI Costs", "Open Cortex spend, forecast, top drivers, and predictive alerts.", "Cost & Contract", "Cortex AI"),
            ("Open Warehouse Drivers", "Open Cost Explorer by warehouse without loading detail rows.", "Cost & Contract", "Cost Explorer"),
            ("Check Budget Risk", "Open budget, allocation, and contract posture.", "Cost & Contract", "Budget vs Actual"),
        ),
    ),
    "Workload Operations": _contract(
        "Workload Operations",
        source_table="MART_SECTION_COMMAND_BRIEF",
        required_sources=("FACT_QUERY_HOURLY", "FACT_TASK_RUN", "FACT_PROCEDURE_RUN", "FACT_COPY_LOAD_DAILY"),
        target_freshness_minutes=30,
        metric_labels=(
            "Active workload incidents",
            "Failed SQL",
            "Failed tasks",
            "Failed procedures",
            "Queue / blocked",
            "SLA risk",
            "Pipeline risk",
            "Recent changes",
        ),
        unavailable_headline="Workload command brief needs workload summary telemetry.",
        unavailable_summary=(
            "Enable workload/reliability summary marts to populate failed SQL, failed tasks, "
            "pipeline risk, queue pressure, and recent changes automatically."
        ),
        top_signal_label="Top workload action",
        top_signal_detail="Open the owning investigation workflow, then load detail only for the selected incident.",
        next_actions=(
            ("Query Investigation", "Open SQL history, diagnosis, and top SQL routes.", "Workload Operations", "Query Investigation"),
            ("Pipeline & Tasks", "Open failed tasks, procedures, copy/load, and SLA risk.", "Workload Operations", "Pipeline & Task Health"),
            ("Performance Pressure", "Open queue, blocked, spilling, and warehouse pressure lanes.", "Workload Operations", "Performance & Contention"),
        ),
    ),
    "Security Monitoring": _contract(
        "Security Monitoring",
        source_table="MART_SECTION_COMMAND_BRIEF",
        required_sources=("FACT_SECURITY_OPERABILITY_DAILY", "ALERT_EVENTS", "MART_OPERATIONAL_OWNER_COVERAGE"),
        target_freshness_minutes=60,
        metric_labels=(
            "Failed logins",
            "MFA signal",
            "Risky grants",
            "Privilege changes",
            "Shared databases",
            "Security alerts",
            "Top action",
            "Freshness",
        ),
        unavailable_headline="Security command brief needs security summary telemetry.",
        unavailable_summary=(
            "Enable security summary marts to populate failed logins, risky grants, sharing, "
            "access changes, alerts, and the top security action automatically."
        ),
        top_signal_label="Top security action",
        top_signal_detail="Review the most exposed identity, grant, sharing, or access-change signal before loading proof tables.",
        next_actions=(
            ("Refresh Security Summary", "Force-refresh compact security counts when needed.", "Security Monitoring", "Security Overview"),
            ("Review Risky Grants", "Open grants, role scope, and ownership exposure.", "Security Monitoring", "Risky Grants"),
            ("Review Access Changes", "Open recent grants, revokes, role changes, and admin changes.", "Security Monitoring", "Access Changes"),
        ),
    ),
}


CANONICAL_COMMAND_BRIEF_SECTIONS = tuple(SECTION_COMMAND_CONTRACTS)


def get_section_command_contract(section: str) -> SectionCommandContract:
    """Return the command brief contract for a primary section."""
    return SECTION_COMMAND_CONTRACTS[str(section)]


__all__ = [
    "CANONICAL_COMMAND_BRIEF_SECTIONS",
    "SECTION_COMMAND_CONTRACTS",
    "SectionCommandContract",
    "get_section_command_contract",
]
