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
    "local_state",
    "export",
    "add_to_case",
    "setup_health",
    "account_usage_fallback",
    "fallback",
}

ACTION_AREA_BY_TYPE = {
    "route": "route_action",
    "refresh_packet": "route_action",
    "evidence_load": "evidence_action",
    "advanced_load": "live_feature",
    "admin_load": "setup_health_admin",
    "local_state": "sidebar_panel_toggle",
    "export": "export_download",
    "add_to_case": "export_download",
    "setup_health": "setup_health_admin",
    "account_usage_fallback": "live_feature",
    "fallback": "route_action",
}

MARKER_BUDGET_RUNTIME_CONTEXTS: dict[str, str] = {
    "admin_setup": "admin_setup",
    "advanced_diagnostics": "advanced_diagnostics",
    "account_usage_fallback": "account_usage_fallback",
    "metadata_probe": "metadata_probe",
    "query_preview": "query_preview",
}


@dataclass(frozen=True)
class ButtonActionContract:
    section: str
    workflow: str = ""
    key_pattern: str = ""
    exact_key: str = ""
    label_pattern: str = ""
    action_type: str = "fallback"
    action_area: str = ""
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
    expected_query_budget_context: str = ""
    expected_budget: int | None = None
    expected_actual_boundaries: dict[str, int] = field(default_factory=dict)
    expected_session_open_count: int | None = None
    expected_direct_sql_count: int | None = None
    expected_metadata_probe_count: int | None = None
    expected_snowflake_execution_count: int | None = None
    can_be_absent: bool = False
    skip_reason: str = ""

    def to_artifact(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action_area"] = self.action_area or _default_action_area(self)
        return payload


def _default_action_area(contract: ButtonActionContract) -> str:
    if contract.exact_key.startswith("nav_btn_"):
        return "sidebar_navigation"
    if contract.exact_key.startswith("sidebar_panel_"):
        return "sidebar_panel_toggle"
    if contract.section == "Settings" and contract.action_type in {"local_state", "setup_health"}:
        return "settings_control" if contract.action_type == "local_state" else "setup_health_admin"
    if contract.section == "Settings/Admin Setup Health":
        return "setup_health_admin"
    if contract.section == "Cost & Contract" and contract.action_type == "evidence_load":
        return "cost_workbench"
    return ACTION_AREA_BY_TYPE.get(contract.action_type, "route_action")


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
        expected_query_boundary="evidence_targeted",
        expected_query_count=1,
        expected_max_rows=500,
        expected_query_contract_id="evidence_default_bounded",
        expected_query_budget_context="evidence_click",
        expected_budget=1,
        expected_actual_boundaries={"evidence_targeted": 1},
        expected_session_open_count=None,
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
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
        expected_query_boundary="evidence_targeted",
        expected_query_count=1,
        expected_max_rows=500,
        expected_query_contract_id="dba_control_room_targeted_evidence",
        expected_query_budget_context="evidence_click",
        expected_budget=1,
        expected_actual_boundaries={"evidence_targeted": 1},
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
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
        expected_query_boundary="evidence_targeted",
        expected_query_count=1,
        expected_max_rows=500,
        expected_query_contract_id="alert_center_targeted_evidence",
        expected_query_budget_context="evidence_click",
        expected_budget=1,
        expected_actual_boundaries={"evidence_targeted": 1},
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
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
        expected_query_boundary="evidence_targeted",
        expected_query_count=1,
        expected_max_rows=500,
        expected_query_contract_id="cost_and_contract_targeted_evidence",
        expected_query_budget_context="evidence_click",
        expected_budget=1,
        expected_actual_boundaries={"evidence_targeted": 1},
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
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
        expected_query_boundary="evidence_targeted",
        expected_query_count=1,
        expected_max_rows=500,
        expected_query_contract_id="security_monitoring_targeted_evidence",
        expected_query_budget_context="evidence_click",
        expected_budget=1,
        expected_actual_boundaries={"evidence_targeted": 1},
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
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
        expected_query_contract_id="decision_packet_current_flat",
        expected_query_budget_context="refresh_packet",
        expected_budget=1,
        # The click records the refresh request and reruns; the packet query
        # executes on the following render under the first-paint packet budget.
        expected_actual_boundaries={},
        expected_session_open_count=0,
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
        expected_snowflake_execution_count=0,
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
            expected_query_budget_context="route_action",
            expected_budget=0,
            expected_actual_boundaries={},
            expected_session_open_count=0,
            expected_direct_sql_count=0,
            expected_metadata_probe_count=0,
            expected_snowflake_execution_count=0,
        )


def _priority_route_contract(section: str) -> ButtonActionContract:
    source_workflow = SECTION_WORKFLOW_CONTRACT.get(section, ("",))[0]
    workflow_key = WORKFLOW_STATE_KEY_BY_SECTION.get(section, "")
    route_key = {
        "Executive Landing": "executive_overview",
        "DBA Control Room": "dba_failures",
        "Alert Center": "alert_center_active",
        "Cost & Contract": "cost_contract_overview",
        "Workload Operations": "workload_query_investigation",
        "Security Monitoring": "security_overview",
    }.get(section, "")
    route = COMMAND_BRIEF_ROUTES.get(route_key)
    route_updates: dict[str, Any] = {}
    if route is not None:
        if route.workflow_key and route.workflow:
            route_updates[route.workflow_key] = route.workflow
        route_updates.update(dict(route.state_updates))
    if route is not None and route.workflow_key and route.workflow == source_workflow:
        route_updates.pop(route.workflow_key, None)
    if workflow_key and source_workflow:
        route_updates.setdefault(workflow_key, source_workflow)
    if route is not None and route.workflow_key and route.workflow == source_workflow:
        route_updates.pop(route.workflow_key, None)
        route_updates = {key: value for key, value in route_updates.items() if value != source_workflow}
    return ButtonActionContract(
        section=section,
        workflow=source_workflow,
        key_pattern=r"_view_all_priorities$",
        label_pattern=r"^View all priorities$",
        action_type="route",
        expected_target_section=section,
        expected_target_workflow=route.workflow if route is not None else source_workflow,
        expected_lens_state={
            key: value
            for key, value in route_updates.items()
            if key and key not in {workflow_key, "nav_section", "decision_workspace_evidence_target"}
        },
        expected_state_updates={
            "nav_section": section,
            **route_updates,
            "decision_workspace_evidence_target": "present",
        },
        expected_artifact="priority_navigation_state_delta",
        exact_route_key=route_key,
        expected_query_count=0,
        expected_query_budget_context="route_action",
        expected_budget=0,
        expected_actual_boundaries={},
        expected_session_open_count=0,
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
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
        key_pattern=r"_fallback_open_setup_health$",
        label_pattern=r"\bOpen Setup Health\b",
        action_type="route",
        expected_target_section=section,
        expected_target_workflow=target_workflow,
        expected_state_updates={
            "nav_section": section,
            **updates,
        },
        expected_artifact="fallback_action_state",
        expected_query_count=0,
        expected_query_budget_context="route_action",
        expected_budget=0,
        expected_actual_boundaries={},
        expected_session_open_count=0,
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
        expected_snowflake_execution_count=0,
        can_be_absent=True,
        skip_reason="Fallback actions only render for setup/packet recovery states.",
    )


def _fallback_initialize_contract(section: str) -> ButtonActionContract:
    target_workflow = SECTION_WORKFLOW_CONTRACT.get(section, ("",))[0]
    return ButtonActionContract(
        section=section,
        workflow=target_workflow,
        key_pattern=r"_fallback_initialize_summaries$",
        label_pattern=r"\bInitialize summaries\b",
        action_type="setup_health",
        expected_target_section=section,
        expected_target_workflow=target_workflow,
        expected_state_updates={
            "nav_section": section,
            "_overwatch_decision_bootstrap_requested": True,
        },
        expected_artifact="decision_summary_bootstrap_request",
        heavy_query_allowed=True,
        requires_admin=True,
        expected_query_boundary="admin_setup_health",
        expected_query_count=0,
        expected_query_budget_context="admin_setup",
        expected_budget=3,
        expected_actual_boundaries={},
        expected_session_open_count=0,
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
        expected_snowflake_execution_count=0,
        can_be_absent=True,
        skip_reason="Initialize summaries only renders for setup/packet recovery states.",
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
        expected_query_boundary="setup_admin",
        expected_query_count=0,
        expected_query_budget_context="advanced_diagnostics",
        expected_budget=3,
        expected_session_open_count=0,
        expected_direct_sql_count=None,
        expected_metadata_probe_count=None,
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
        expected_query_boundary="setup_admin",
        expected_query_count=0,
        expected_query_budget_context="admin_setup",
        expected_budget=3,
        expected_session_open_count=0,
        expected_direct_sql_count=None,
        expected_metadata_probe_count=None,
        expected_rerun=False,
    )


def _account_usage_fallback_contract(section: str) -> ButtonActionContract:
    return ButtonActionContract(
        section=section,
        workflow="",
        key_pattern=r"account_usage_fallback",
        label_pattern=r"\b(Search Account Usage fallback|Account Usage fallback|Search deep history fallback|deep history fallback)\b",
        action_type="account_usage_fallback",
        expected_artifact="explicit_account_usage_fallback_query",
        heavy_query_allowed=True,
        account_usage_allowed=True,
        requires_admin=True,
        expected_query_boundary="query_search_broad_explicit",
        expected_query_count=1,
        expected_max_rows=200,
        expected_query_contract_id="account_usage_confirmed_fallback",
        expected_query_budget_context="account_usage_fallback",
        expected_budget=1,
        expected_actual_boundaries={"query_search_broad_explicit": 1},
        expected_session_open_count=1,
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
        expected_snowflake_execution_count=1,
        expected_rerun=False,
    )


def _active_detail_action_contracts() -> Iterable[ButtonActionContract]:
    route_specs = (
        (
            "DBA Control Room",
            "Cost Watch",
            "dba_cost_watch_open_cost_contract",
            "Cost & Contract",
            "Cost Overview",
            "cost_contract_overview",
        ),
        (
            "DBA Control Room",
            "Performance Watch",
            "dba_performance_watch_open_workload",
            "Workload Operations",
            "Performance & Contention",
            "workload_performance",
        ),
        (
            "DBA Control Room",
            "Change Watch",
            "dba_change_watch_open_workload",
            "Workload Operations",
            "Change Analysis",
            "workload_change_analysis",
        ),
        (
            "DBA Control Room",
            "Change Watch",
            "dba_change_watch_open_security",
            "Security Monitoring",
            "Access Changes",
            "security_access_changes",
        ),
    )
    for section, workflow, key, target_section, target_workflow, route_key in route_specs:
        yield ButtonActionContract(
            section=section,
            workflow=workflow,
            exact_key=key,
            action_type="route",
            expected_target_section=target_section,
            expected_target_workflow=target_workflow,
            expected_artifact="navigation_state_delta",
            exact_route_key=route_key,
            expected_query_budget_context="route_action",
            expected_query_count=0,
            expected_budget=0,
            expected_actual_boundaries={},
            expected_session_open_count=0,
            expected_direct_sql_count=0,
            expected_metadata_probe_count=0,
            expected_snowflake_execution_count=0,
        )
    yield ButtonActionContract(
        section="DBA Control Room",
        workflow="Action Queue",
        exact_key="dba_control_room_build_ops_from_empty",
        label_pattern=r"\bLoad Action Queue\b",
        action_type="evidence_load",
        expected_artifact="dba_action_queue_rows",
        expected_query_boundary="evidence_targeted",
        expected_query_count=1,
        expected_max_rows=500,
        expected_query_budget_context="evidence_click",
        expected_budget=1,
        expected_actual_boundaries={"evidence_targeted": 1},
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
        expected_snowflake_execution_count=1,
    )
    yield ButtonActionContract(
        section="DBA Control Room",
        workflow="Action Queue",
        exact_key="dba_control_room_build_ops",
        label_pattern=r"\bLoad Action Queue\b",
        action_type="local_state",
        expected_artifact="dba_action_queue_state_delta",
        expected_query_count=0,
        expected_query_budget_context="evidence_click",
        expected_budget=1,
        expected_actual_boundaries={},
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
        expected_snowflake_execution_count=0,
    )
    yield ButtonActionContract(
        section="Workload Operations",
        workflow="Change Analysis",
        exact_key="workload_load_change_intelligence",
        label_pattern=r"\bLoad Workload Changes\b",
        action_type="evidence_load",
        expected_artifact="workload_change_detail_rows",
        expected_query_boundary="evidence_targeted",
        expected_query_count=1,
        expected_max_rows=500,
        expected_query_contract_id="workload_change_targeted_evidence",
        expected_query_budget_context="evidence_click",
        expected_budget=1,
        expected_actual_boundaries={"evidence_targeted": 1},
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
        expected_snowflake_execution_count=1,
    )
    for key, label in (
        ("security_load_score_drivers", r"\bLoad Security Score Drivers\b"),
        ("security_load_closed_loop_approvals", r"\bLoad Security Approvals\b"),
        ("security_load_command_center", r"\bLoad Security Investigation Findings\b"),
    ):
        yield ButtonActionContract(
            section="Security Monitoring",
            workflow="Security Admin / Advanced",
            exact_key=key,
            label_pattern=label,
            action_type="advanced_load",
            expected_artifact="security_admin_detail_rows",
            heavy_query_allowed=True,
            requires_admin=True,
            expected_query_budget_context="advanced_diagnostics",
            expected_query_count=0,
            expected_budget=3,
            expected_actual_boundaries={},
            expected_direct_sql_count=0,
            expected_metadata_probe_count=0,
            expected_snowflake_execution_count=0,
        )
    for key, workflow, label in (
        ("security_privilege_sprawl_load", "Privilege Sprawl", r"\bLoad Privilege Sprawl\b"),
        ("security_priv_grant_load", "Security Admin / Advanced", r"\bLoad Privileged Grant Status\b"),
        ("security_load_access_changes_intelligence", "Access Changes", r"\bLoad Security-Sensitive Changes\b"),
    ):
        yield ButtonActionContract(
            section="Security Monitoring",
            workflow=workflow,
            exact_key=key,
            label_pattern=label,
            action_type="evidence_load",
            expected_artifact="security_evidence_rows",
            expected_query_boundary="evidence_targeted",
            expected_query_count=1,
            expected_max_rows=500,
            expected_query_budget_context="evidence_click",
            expected_budget=1,
            expected_actual_boundaries={"evidence_targeted": 1},
            expected_direct_sql_count=0,
            expected_metadata_probe_count=0,
            expected_snowflake_execution_count=1,
        )
    yield ButtonActionContract(
        section="Settings",
        workflow="Default",
        exact_key="settings_open_setup_health",
        label_pattern=r"\bOpen Setup Health\b",
        action_type="setup_health",
        expected_artifact="setup_health_panel_state",
        requires_admin=True,
        expected_rerun=False,
        expected_query_count=0,
        expected_session_open_count=0,
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
        expected_snowflake_execution_count=0,
    )
    yield ButtonActionContract(
        section="Settings/Admin Setup Health",
        workflow="Setup Health",
        exact_key="decision_setup_health_refresh",
        label_pattern=r"\bRefresh Setup Health\b",
        action_type="admin_load",
        expected_artifact="setup_health_refresh_state",
        heavy_query_allowed=True,
        requires_admin=True,
        expected_query_budget_context="admin_setup",
        expected_query_count=0,
        expected_budget=3,
        expected_actual_boundaries={},
        expected_session_open_count=0,
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
        expected_snowflake_execution_count=0,
        expected_rerun=False,
    )


def iter_button_action_contracts() -> Iterable[ButtonActionContract]:
    for section in PRIMARY_SECTION_TITLES:
        yield _refresh_contract(section)
        yield _priority_route_contract(section)
        yield from _route_contracts_for_source_section(section)
        yield _fallback_route_contract(section)
        yield _fallback_initialize_contract(section)
        if section in SECTION_EVIDENCE_CONTRACTS:
            yield SECTION_EVIDENCE_CONTRACTS[section]
        yield _account_usage_fallback_contract(section)
        yield _admin_contract(section)
        yield _advanced_contract(section)
    for group, section in (
        ("MONITORING CORE", "Executive Landing"),
        ("MONITORING CORE", "DBA Control Room"),
        ("MONITORING CORE", "Alert Center"),
        ("FINANCIAL CONTROL", "Cost & Contract"),
        ("OPERATIONS", "Workload Operations"),
        ("SECURITY", "Security Monitoring"),
    ):
        yield ButtonActionContract(
            section="*",
            exact_key=f"nav_btn_{group}_{section}",
            label_pattern=rf"\b{re.escape(section)}\b",
            action_type="route",
            expected_target_section=section,
            expected_state_updates={"nav_section": section},
            exact_route_key=_key_token(section),
            expected_query_budget_context="route_action",
            expected_budget=0,
            expected_actual_boundaries={},
            expected_query_count=0,
            expected_session_open_count=0,
            expected_direct_sql_count=0,
            expected_metadata_probe_count=0,
            expected_snowflake_execution_count=0,
            expected_rerun=False,
        )
    for panel_key, label in (
        ("sidebar_panel_advanced_scope", "Advanced Scope"),
        ("sidebar_panel_settings", "Settings"),
    ):
        yield ButtonActionContract(
            section="*",
            exact_key=panel_key,
            label_pattern=rf"\b{re.escape(label)}\b",
            action_type="local_state",
            expected_state_updates={"sidebar_panel": panel_key.removeprefix("sidebar_panel_")},
            expected_query_count=0,
            expected_session_open_count=0,
            expected_direct_sql_count=0,
            expected_metadata_probe_count=0,
            expected_snowflake_execution_count=0,
            expected_rerun=False,
        )
    yield ButtonActionContract(
        section="Advanced Scope",
        workflow="Active filters",
        exact_key="global_filters_clear",
        label_pattern=r"\bClear filters\b",
        action_type="local_state",
        action_area="settings_control",
        expected_state_updates={"advanced_scope_filters": "cleared"},
        expected_query_count=0,
        expected_session_open_count=0,
        expected_direct_sql_count=0,
        expected_metadata_probe_count=0,
        expected_snowflake_execution_count=0,
        expected_rerun=True,
    )
    yield from _active_detail_action_contracts()
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


def _observed_context_names(result: dict[str, Any]) -> list[str]:
    observed = result.get("observed_query_budget_contexts")
    if isinstance(observed, (list, tuple, set)):
        return [str(item) for item in observed if str(item or "")]
    if isinstance(observed, str):
        return [item.strip() for item in observed.split(",") if item.strip()]
    return []


def assert_button_budget_context(result: dict[str, Any], contract: ButtonActionContract) -> dict[str, Any]:
    """Validate that a clicked button observed the exact budget context promised by its contract."""
    expected = str(contract.expected_query_budget_context or "")
    observed = _observed_context_names(result)
    allow_missing = bool(contract.skip_reason) or contract.action_type in {"export", "add_to_case"}
    missing = bool(expected and expected not in observed and not allow_missing)
    unexpected = sorted(context for context in observed if expected and context != expected)
    passed = not missing and not unexpected
    diagnostics = {
        "budget_context_contract_passed": passed,
        "missing_budget_context": expected if missing else "",
        "unexpected_budget_contexts": unexpected,
        "expected_actual_boundaries": dict(contract.expected_actual_boundaries or {}),
        "observed_actual_boundaries": dict(result.get("actual_boundaries") or {}),
    }
    if not passed:
        raise AssertionError(f"Button budget context contract failed: {diagnostics}")
    return diagnostics


def marker_budget_mismatches(events: Iterable[dict[str, Any]], observed_contexts: Iterable[str]) -> list[dict[str, str]]:
    """Return marker-budget/runtime-context mismatches without exposing SQL text."""
    observed = {str(context or "") for context in observed_contexts if str(context or "")}
    mismatches: list[dict[str, str]] = []
    for event in events:
        marker_budget = str(event.get("marker_budget") or "")
        if not marker_budget:
            continue
        expected_context = MARKER_BUDGET_RUNTIME_CONTEXTS.get(marker_budget, marker_budget)
        if expected_context not in observed:
            mismatches.append({
                "event_id": str(event.get("event_id") or ""),
                "marker_budget": marker_budget,
                "expected_runtime_context": expected_context,
                "observed_runtime_contexts": ",".join(sorted(observed)),
            })
    return mismatches


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
    "MARKER_BUDGET_RUNTIME_CONTEXTS",
    "assert_button_budget_context",
    "assert_button_contract_resolved",
    "contract_to_manifest_row",
    "contract_target_is_valid",
    "expected_route_state_for_contract",
    "iter_button_action_contracts",
    "marker_budget_mismatches",
    "resolve_button_action_contract",
]
