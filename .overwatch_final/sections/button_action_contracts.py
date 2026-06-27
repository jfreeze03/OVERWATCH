"""Explicit button/action contracts for Decision Workspace proof artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Iterable, Pattern

from route_registry import PRIMARY_SECTION_TITLES, SECTION_WORKFLOW_CONTRACT
from sections.command_brief_routes import COMMAND_BRIEF_ROUTES


ACTION_TYPES = {
    "route",
    "refresh_packet",
    "evidence_load",
    "advanced_load",
    "admin_load",
    "export",
    "add_to_case",
    "setup_health",
    "account_usage_fallback",
    "fallback",
}


@dataclass(frozen=True)
class ButtonActionContract:
    section: str
    workflow: str = ""
    key_pattern: str = ""
    exact_key: str = ""
    label_pattern: str = ""
    action_type: str = "fallback"
    expected_target_section: str = ""
    expected_target_workflow: str = ""
    expected_lens_state: dict[str, Any] = field(default_factory=dict)
    expected_state_updates: dict[str, Any] = field(default_factory=dict)
    expected_artifact: str = ""
    exact_route_key: str = ""
    heavy_query_allowed: bool = False
    account_usage_allowed: bool = False
    requires_admin: bool = False
    expected_rerun: bool = True
    expected_query_boundary: str = ""
    expected_query_count: int | None = None
    expected_max_rows: int | None = None
    expected_query_contract_id: str = ""
    expected_session_open_count: int | None = None
    expected_snowflake_execution_count: int | None = None
    can_be_absent: bool = False
    skip_reason: str = ""

    def to_artifact(self) -> dict[str, Any]:
        return asdict(self)


def _rx(pattern: str) -> Pattern[str]:
    return re.compile(pattern, flags=re.IGNORECASE)


def _matches(pattern: str, value: str) -> bool:
    return bool(pattern and _rx(pattern).search(str(value or "")))


WORKFLOW_STATE_KEY_BY_SECTION: dict[str, str] = {
    "Executive Landing": "executive_landing_workflow",
    "DBA Control Room": "dba_control_room_active_view",
    "Alert Center": "alert_center_active_view",
    "Cost & Contract": "cost_contract_workflow",
    "Workload Operations": "workload_operations_workflow",
    "Security Monitoring": "security_posture_view",
}


def _key_token(value: object) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return token.strip("_") or "action"


SECTION_REFRESH_BUTTON_KEYS: dict[str, str] = {
    "Executive Landing": "executive_landing_command_brief_refresh_packet",
    "DBA Control Room": "dba_control_room_command_brief_refresh_packet",
    "Alert Center": "alert_center_command_brief_refresh_packet",
    "Cost & Contract": "cost_contract_command_brief_refresh_packet",
    "Workload Operations": "workload_operations_command_brief_refresh_packet",
    "Security Monitoring": "security_posture_command_brief_refresh_packet",
}

SECTION_REFRESH_STATE_KEYS: dict[str, str] = {
    "Executive Landing": "_executive_landing_command_brief_force_refresh",
    "DBA Control Room": "dba_control_room_command_brief_force_refresh",
    "Alert Center": "alert_center_command_brief_force_refresh",
    "Cost & Contract": "cost_contract_command_brief_force_refresh",
    "Workload Operations": "workload_operations_command_brief_force_refresh",
    "Security Monitoring": "security_posture_command_brief_force_refresh",
}


SECTION_EVIDENCE_CONTRACTS: dict[str, ButtonActionContract] = {
    "Executive Landing": ButtonActionContract(
        "Executive Landing",
        "Executive Overview",
        label_pattern=r"\bLoad Full Executive Snapshot\b",
        action_type="evidence_load",
        expected_target_section="Executive Landing",
        expected_target_workflow="Executive Overview",
        expected_state_updates={"_executive_landing_command_brief_load_detail": True},
        expected_artifact="executive_snapshot_state",
        expected_query_boundary="evidence",
        expected_query_count=1,
        expected_max_rows=500,
        expected_snowflake_execution_count=1,
    ),
    "DBA Control Room": ButtonActionContract(
        "DBA Control Room",
        "Morning Cockpit",
        label_pattern=r"\bLoad (Triage|Investigation Detail|Full Detail Packet)\b",
        action_type="evidence_load",
        expected_target_section="DBA Control Room",
        expected_target_workflow="Morning Cockpit",
        expected_state_updates={"dba_control_room_command_brief_load_detail": True},
        expected_artifact="dba_control_room_evidence_rows",
        expected_query_boundary="evidence",
        expected_query_count=1,
        expected_max_rows=500,
        expected_snowflake_execution_count=1,
    ),
    "Alert Center": ButtonActionContract(
        "Alert Center",
        "Active Alerts",
        label_pattern=r"\bLoad .+",
        action_type="evidence_load",
        expected_target_section="Alert Center",
        expected_target_workflow="Active Alerts",
        expected_artifact="alert_center_evidence_rows",
        expected_query_boundary="evidence",
        expected_query_count=1,
        expected_max_rows=500,
        expected_snowflake_execution_count=1,
    ),
    "Cost & Contract": ButtonActionContract(
        "Cost & Contract",
        "Cost Overview",
        label_pattern=r"\bLoad Cost Evidence\b",
        action_type="evidence_load",
        expected_target_section="Cost & Contract",
        expected_target_workflow="Cost Overview",
        expected_state_updates={"cost_contract_command_brief_load_evidence": True},
        expected_artifact="cost_contract_evidence_rows",
        expected_query_boundary="evidence",
        expected_query_count=1,
        expected_max_rows=500,
        expected_snowflake_execution_count=1,
    ),
    "Security Monitoring": ButtonActionContract(
        "Security Monitoring",
        "Security Overview",
        label_pattern=r"\bLoad Security Evidence\b",
        action_type="evidence_load",
        expected_target_section="Security Monitoring",
        expected_target_workflow="Security Overview",
        expected_state_updates={"security_posture_load_evidence": True},
        expected_artifact="security_evidence_rows",
        expected_query_boundary="evidence",
        expected_query_count=1,
        expected_max_rows=500,
        expected_snowflake_execution_count=1,
    ),
}


def _refresh_contract(section: str) -> ButtonActionContract:
    return ButtonActionContract(
        section=section,
        workflow=SECTION_WORKFLOW_CONTRACT.get(section, ("",))[0],
        exact_key=SECTION_REFRESH_BUTTON_KEYS.get(section, ""),
        label_pattern=r"^Refresh$",
        action_type="refresh_packet",
        expected_state_updates={SECTION_REFRESH_STATE_KEYS.get(section, ""): True},
        expected_artifact="command_packet_refresh_request",
        expected_query_boundary="decision_packet",
        expected_query_count=1,
        expected_max_rows=1,
        expected_snowflake_execution_count=1,
    )


def expected_route_state_for_contract(contract: ButtonActionContract) -> dict[str, Any]:
    updates = dict(contract.expected_state_updates or {})
    updates.update(dict(contract.expected_lens_state or {}))
    return updates


def _route_contracts_for_source_section(section: str) -> Iterable[ButtonActionContract]:
    source_workflow = SECTION_WORKFLOW_CONTRACT.get(section, ("",))[0]
    for route_key, route in COMMAND_BRIEF_ROUTES.items():
        if not route.workflow:
            continue
        target_section = route.section
        target_workflow = route.workflow
        workflow_key = WORKFLOW_STATE_KEY_BY_SECTION.get(target_section, "")
        route_updates: dict[str, Any] = {}
        if route.workflow_key and route.workflow:
            route_updates[route.workflow_key] = route.workflow
        if workflow_key and target_workflow:
            route_updates.setdefault(workflow_key, target_workflow)
        route_updates.update(dict(route.state_updates))
        if target_section == "Alert Center" and target_workflow:
            route_updates.setdefault("alert_center_requested_view", target_workflow)
        lens_state = {
            key: value
            for key, value in route_updates.items()
            if key
            and key
            not in {
                route.workflow_key,
                workflow_key,
                "nav_section",
                "decision_workspace_evidence_target",
                "alert_center_requested_view",
            }
        }
        yield ButtonActionContract(
            section=section,
            workflow=source_workflow,
            key_pattern=rf"_(?:primary|secondary)(?:_\d+)?_{re.escape(_key_token(route_key))}$",
            label_pattern=r"\b(Open|Review|Investigate|Route).*(->)?",
            action_type="route",
            expected_target_section=target_section,
            expected_target_workflow=target_workflow,
            expected_lens_state=lens_state,
            expected_state_updates={
                "nav_section": target_section,
                **route_updates,
                "decision_workspace_evidence_target": "present",
            },
            expected_artifact="navigation_state_delta",
            exact_route_key=route_key,
            expected_query_count=0,
            expected_session_open_count=0,
            expected_snowflake_execution_count=0,
        )


def _fallback_route_contract(section: str) -> ButtonActionContract:
    target_workflow = SECTION_WORKFLOW_CONTRACT.get(section, ("",))[0]
    updates: dict[str, Any] = {}
    workflow_key = WORKFLOW_STATE_KEY_BY_SECTION.get(section, "")
    if workflow_key and target_workflow:
        updates.setdefault(workflow_key, target_workflow)
    return ButtonActionContract(
        section=section,
        workflow=target_workflow,
        key_pattern=r"_fallback_(?:refresh|initialize|open_setup_health)$",
        label_pattern=r"\b(Refresh|Initialize|Open Setup Health)\b",
        action_type="route",
        expected_target_section=section,
        expected_target_workflow=target_workflow,
        expected_state_updates={
            "nav_section": section,
            **updates,
        },
        expected_artifact="fallback_action_state",
        expected_query_count=0,
        expected_session_open_count=0,
        expected_snowflake_execution_count=0,
        can_be_absent=True,
        skip_reason="Fallback actions only render for setup/packet recovery states.",
    )


def _advanced_contract(section: str) -> ButtonActionContract:
    return ButtonActionContract(
        section=section,
        workflow="",
        label_pattern=r"\b(Advanced|Diagnostics)\b",
        action_type="advanced_load",
        expected_artifact="explicit_advanced_control",
        heavy_query_allowed=True,
        requires_admin=True,
        expected_query_boundary="admin",
        expected_query_count=0,
        expected_session_open_count=0,
        expected_rerun=False,
    )


def _admin_contract(section: str) -> ButtonActionContract:
    return ButtonActionContract(
        section=section,
        workflow="",
        label_pattern=r"\b(Admin|Setup|Setup Health)\b",
        action_type="admin_load",
        expected_artifact="explicit_admin_control",
        heavy_query_allowed=True,
        requires_admin=True,
        expected_query_boundary="admin",
        expected_query_count=0,
        expected_session_open_count=0,
        expected_rerun=False,
    )


def _account_usage_fallback_contract(section: str) -> ButtonActionContract:
    return ButtonActionContract(
        section=section,
        workflow="",
        key_pattern=r"account_usage_fallback",
        label_pattern=r"\b(Search Account Usage fallback|Account Usage fallback)\b",
        action_type="account_usage_fallback",
        expected_artifact="explicit_account_usage_fallback_query",
        heavy_query_allowed=True,
        account_usage_allowed=True,
        requires_admin=True,
        expected_query_boundary="account_usage",
        expected_query_count=1,
        expected_max_rows=200,
        expected_session_open_count=1,
        expected_snowflake_execution_count=1,
        expected_rerun=False,
    )


def iter_button_action_contracts() -> Iterable[ButtonActionContract]:
    for section in PRIMARY_SECTION_TITLES:
        yield _refresh_contract(section)
        yield from _route_contracts_for_source_section(section)
        yield _fallback_route_contract(section)
        if section in SECTION_EVIDENCE_CONTRACTS:
            yield SECTION_EVIDENCE_CONTRACTS[section]
        yield _account_usage_fallback_contract(section)
        yield _admin_contract(section)
        yield _advanced_contract(section)
    yield ButtonActionContract(
        section="*",
        label_pattern=r"\b(Download|Export)\b",
        action_type="export",
        expected_artifact="download_file",
        expected_rerun=False,
    )
    yield ButtonActionContract(
        section="*",
        label_pattern=r"\b(Add|Save).*(Case|Snapshot|Action Queue)\b",
        action_type="add_to_case",
        expected_artifact="case_or_snapshot_payload",
        expected_rerun=False,
    )


def resolve_button_action_contract(
    *,
    section: str,
    workflow: str,
    label: str,
    key: str,
) -> ButtonActionContract | None:
    section = str(section or "")
    workflow = str(workflow or "")
    label = str(label or "")
    key = str(key or "")
    candidates = [
        contract for contract in iter_button_action_contracts()
        if contract.section in {section, "*"}
        and (not contract.workflow or contract.workflow == workflow or workflow in SECTION_WORKFLOW_CONTRACT.get(section, ()))
    ]
    for contract in candidates:
        if contract.exact_key and contract.exact_key == key:
            return contract
    for contract in candidates:
        key_match = _matches(contract.key_pattern, key)
        if key_match:
            return contract
    for contract in candidates:
        label_match = _matches(contract.label_pattern, label)
        if label_match and not contract.exact_route_key:
            return contract
    return None


def assert_button_contract_resolved(contract: ButtonActionContract | None) -> None:
    if contract is None:
        raise AssertionError("Button action did not resolve to an explicit contract")
    if contract.action_type == "route" and not contract.exact_route_key and not contract.skip_reason:
        raise AssertionError("Route button resolved to a non-exact route contract")


def contract_to_manifest_row(contract: ButtonActionContract) -> dict[str, Any]:
    return contract.to_artifact()


def contract_target_is_valid(contract: ButtonActionContract) -> bool:
    if contract.action_type != "route":
        return True
    if contract.expected_target_section not in PRIMARY_SECTION_TITLES:
        return False
    workflow = contract.expected_target_workflow
    return not workflow or workflow in SECTION_WORKFLOW_CONTRACT.get(contract.expected_target_section, ())


__all__ = [
    "ACTION_TYPES",
    "ButtonActionContract",
    "assert_button_contract_resolved",
    "contract_to_manifest_row",
    "contract_target_is_valid",
    "expected_route_state_for_contract",
    "iter_button_action_contracts",
    "resolve_button_action_contract",
]
