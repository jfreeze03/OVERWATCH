"""Import-safe Command Deck contracts for primary OVERWATCH sections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from sections.first_paint_contracts import get_first_paint_contract


@dataclass(frozen=True)
class CommandDeckAction:
    """A first-paint route action that must not load telemetry on render."""

    label: str
    description: str
    target_section: str = ""
    target_workflow: str = ""
    session_state_updates: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class SectionCommandDeckContract:
    """Static Command Deck contract for a canonical section."""

    section: str
    primary_cta: str
    primary_cta_key: str
    route_actions: tuple[CommandDeckAction, ...]
    advanced_label: str
    evidence_boundary: str
    no_query_note: str
    primary_cta_behavior: str = "existing_button"
    primary_cta_description: str = ""
    primary_cta_preserve_existing: bool = True


def _deck(
    section: str,
    *,
    primary_cta_key: str,
    route_actions: tuple[CommandDeckAction, ...],
    advanced_label: str = "Advanced / diagnostics",
    primary_cta_behavior: str = "existing_button",
    primary_cta_description: str = "",
    primary_cta_preserve_existing: bool = True,
) -> SectionCommandDeckContract:
    first_paint = get_first_paint_contract(section)
    description = primary_cta_description or (
        f"Use {first_paint.explicit_load_cta} when current evidence is needed."
    )
    return SectionCommandDeckContract(
        section=first_paint.section,
        primary_cta=first_paint.explicit_load_cta,
        primary_cta_key=primary_cta_key,
        route_actions=route_actions,
        advanced_label=advanced_label,
        evidence_boundary=f"{first_paint.explicit_load_cta} is the explicit evidence boundary.",
        no_query_note=first_paint.no_query_note,
        primary_cta_behavior=primary_cta_behavior,
        primary_cta_description=description,
        primary_cta_preserve_existing=primary_cta_preserve_existing,
    )


COMMAND_DECK_CONTRACTS: Mapping[str, SectionCommandDeckContract] = {
    "Executive Landing": _deck(
        "Executive Landing",
        primary_cta_key="executive_landing_observability_refresh",
        route_actions=(
            CommandDeckAction(
                "Cost Movement",
                "Review spend movement and contract-facing finance context.",
                target_workflow="Cost Movement",
                session_state_updates=(("executive_landing_workflow", "Cost Movement"),),
            ),
            CommandDeckAction(
                "Cortex AI Cost",
                "Review Cortex spend, forecast, and predictive cost alerts.",
                target_section="Cost & Contract",
                target_workflow="Cost Overview",
                session_state_updates=(
                    ("cost_contract_workflow", "Cost Overview"),
                    ("cost_contract_advanced_tool", "Cortex Spend"),
                    ("_cost_contract_show_advanced_tools", True),
                ),
            ),
            CommandDeckAction(
                "Operational Risk",
                "Open failures, workload, and action risk context.",
                target_workflow="Operational Risk",
                session_state_updates=(("executive_landing_workflow", "Operational Risk"),),
            ),
            CommandDeckAction(
                "Security Risk",
                "Open security posture and access-risk context.",
                target_workflow="Security Risk",
                session_state_updates=(("executive_landing_workflow", "Security Risk"),),
            ),
            CommandDeckAction(
                "Executive Actions",
                "Open route-backed executive action status.",
                target_workflow="Executive Actions",
                session_state_updates=(("executive_landing_workflow", "Executive Actions"),),
            ),
        ),
    ),
    "DBA Control Room": _deck(
        "DBA Control Room",
        primary_cta_key="dba_morning_cockpit_load_empty",
        route_actions=(
            CommandDeckAction(
                "Failure Triage",
                "Open failed SQL, task, and procedure triage.",
                target_workflow="Failure Triage",
                session_state_updates=(("dba_control_room_active_view", "Failure Triage"),),
            ),
            CommandDeckAction(
                "Cost Watch",
                "Open cost pressure and spend movement watch.",
                target_workflow="Cost Watch",
                session_state_updates=(("dba_control_room_active_view", "Cost Watch"),),
            ),
            CommandDeckAction(
                "Performance Watch",
                "Open queue, contention, and slow-query watch.",
                target_workflow="Performance Watch",
                session_state_updates=(("dba_control_room_active_view", "Performance Watch"),),
            ),
            CommandDeckAction(
                "Action Queue",
                "Open review-only action queue posture.",
                target_workflow="Action Queue",
                session_state_updates=(("dba_control_room_active_view", "Action Queue"),),
            ),
        ),
    ),
    "Alert Center": _deck(
        "Alert Center",
        primary_cta_key="alert_center_load",
        route_actions=(
            CommandDeckAction(
                "Active Alerts",
                "Open currently active issue lanes.",
                target_workflow="Active Alerts",
                session_state_updates=(("alert_center_requested_view", "Active Alerts"),),
            ),
            CommandDeckAction(
                "Cost Alerts",
                "Open spend, Cortex, service-cost, and waste alerts.",
                target_workflow="Cost Alerts",
                session_state_updates=(("alert_center_requested_view", "Cost Alerts"),),
            ),
            CommandDeckAction(
                "Cortex Predictive Alerts",
                "Open Cortex forecast, anomaly, and cost-exposure alert lanes.",
                target_section="Cost & Contract",
                target_workflow="Cost Overview",
                session_state_updates=(
                    ("alert_center_requested_view", "Cost Alerts"),
                    ("cost_contract_workflow", "Cost Overview"),
                    ("cost_contract_advanced_tool", "Cortex Spend"),
                    ("_cost_contract_show_advanced_tools", True),
                ),
            ),
            CommandDeckAction(
                "Reliability Alerts",
                "Open workload, task, and SLA alerts.",
                target_workflow="Reliability Alerts",
                session_state_updates=(("alert_center_requested_view", "Reliability Alerts"),),
            ),
            CommandDeckAction(
                "Security Alerts",
                "Open security risk and access alerts.",
                target_workflow="Security Alerts",
                session_state_updates=(("alert_center_requested_view", "Security Alerts"),),
            ),
        ),
    ),
    "Cost & Contract": _deck(
        "Cost & Contract",
        primary_cta_key="cost_contract_refresh",
        route_actions=(
            CommandDeckAction(
                "Cost by Warehouse",
                "Open warehouse spend drivers and movement.",
                target_workflow="Cost by Warehouse",
                session_state_updates=(("cost_contract_workflow", "Cost by Warehouse"),),
            ),
            CommandDeckAction(
                "Burn Rate & Forecast",
                "Open daily spend trend and run-rate forecast.",
                target_workflow="Burn Rate & Forecast",
                session_state_updates=(("cost_contract_workflow", "Burn Rate & Forecast"),),
            ),
            CommandDeckAction(
                "Cortex Cost Drivers",
                "Open Cortex spend, top users, forecast, and predictive alert context.",
                target_workflow="Cost Overview",
                session_state_updates=(
                    ("cost_contract_workflow", "Cost Overview"),
                    ("cost_contract_advanced_tool", "Cortex Spend"),
                    ("_cost_contract_show_advanced_tools", True),
                ),
            ),
            CommandDeckAction(
                "Budget vs Actual",
                "Open account total, allocation, and reconciliation review.",
                target_workflow="Budget vs Actual",
                session_state_updates=(("cost_contract_workflow", "Budget vs Actual"),),
            ),
            CommandDeckAction(
                "Cost Recommendations",
                "Open savings and optimization recommendations.",
                target_workflow="Cost Recommendations",
                session_state_updates=(("cost_contract_workflow", "Cost Recommendations"),),
            ),
        ),
    ),
    "Workload Operations": _deck(
        "Workload Operations",
        primary_cta_key="workload_command_deck_primary_open",
        route_actions=(
            CommandDeckAction(
                "Slow or failed SQL",
                "Open query diagnosis, history, and operator detail.",
                target_workflow="Query Investigation",
                session_state_updates=(("workload_operations_workflow", "Query Investigation"),),
            ),
            CommandDeckAction(
                "Task or load failure",
                "Open pipeline, task, procedure, and load failure triage.",
                target_workflow="Pipeline & Task Health",
                session_state_updates=(
                    ("workload_operations_workflow", "Pipeline & Task Health"),
                    ("workload_pipeline_focus", "Failed Tasks"),
                ),
            ),
            CommandDeckAction(
                "Performance issue",
                "Open queue pressure, contention, and warehouse saturation.",
                target_workflow="Performance & Contention",
                session_state_updates=(("workload_operations_workflow", "Performance & Contention"),),
            ),
            CommandDeckAction(
                "What changed?",
                "Open workload change and drift analysis.",
                target_workflow="Change Analysis",
                session_state_updates=(("workload_operations_workflow", "Change Analysis"),),
            ),
            CommandDeckAction(
                "Compare / admin",
                "Open advanced comparison and DBA tools.",
                target_workflow="Advanced DBA Tools",
                session_state_updates=(("workload_operations_workflow", "Advanced DBA Tools"),),
            ),
        ),
    ),
    "Security Monitoring": _deck(
        "Security Monitoring",
        primary_cta_key="security_posture_brief_load",
        route_actions=(
            CommandDeckAction(
                "Failed Logins",
                "Open login risk and MFA posture.",
                target_workflow="Failed Logins",
                session_state_updates=(("security_posture_view", "Failed Logins"),),
            ),
            CommandDeckAction(
                "Risky Grants",
                "Open elevated access and grants review.",
                target_workflow="Risky Grants",
                session_state_updates=(("security_posture_view", "Risky Grants"),),
            ),
            CommandDeckAction(
                "Access Changes",
                "Open security-sensitive access drift.",
                target_workflow="Access Changes",
                session_state_updates=(("security_posture_view", "Access Changes"),),
            ),
            CommandDeckAction(
                "Data Sharing Exposure",
                "Open sharing and external exposure review.",
                target_workflow="Data Sharing Exposure",
                session_state_updates=(("security_posture_view", "Data Sharing Exposure"),),
            ),
        ),
    ),
}


CANONICAL_COMMAND_DECK_SECTIONS = tuple(COMMAND_DECK_CONTRACTS)


def get_command_deck_contract(section: str) -> SectionCommandDeckContract:
    """Return the command deck contract for a canonical section."""
    return COMMAND_DECK_CONTRACTS[str(section)]


__all__ = [
    "CANONICAL_COMMAND_DECK_SECTIONS",
    "COMMAND_DECK_CONTRACTS",
    "CommandDeckAction",
    "SectionCommandDeckContract",
    "get_command_deck_contract",
]
