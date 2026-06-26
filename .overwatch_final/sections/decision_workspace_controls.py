"""Shared controls for Decision Workspace refresh and evidence actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import streamlit as st


DECISION_REFRESH_KEYS: dict[str, str] = {
    "Executive Landing": "_executive_landing_command_brief_force_refresh",
    "DBA Control Room": "dba_control_room_command_brief_force_refresh",
    "Alert Center": "alert_center_command_brief_force_refresh",
    "Cost & Contract": "cost_contract_command_brief_force_refresh",
    "Workload Operations": "workload_operations_command_brief_force_refresh",
    "Security Monitoring": "security_posture_command_brief_force_refresh",
}


@dataclass(frozen=True)
class CommandBriefDetailAction:
    label: str
    help_text: str
    callback: Callable[[], None]
    key: str | None = None
    settings_renderer: Callable[[], None] | None = None
    settings_label: str = "Evidence settings"


@dataclass(frozen=True)
class DecisionWorkspaceControls:
    section: str = ""
    current_workflow: str = ""
    refresh_packet: Callable[[], None] | None = None
    route_actions: tuple[Any, ...] = ()
    evidence_action: CommandBriefDetailAction | None = None
    evidence_settings: Callable[[], None] | None = None
    can_refresh: bool = True
    can_load_evidence: bool = False

    @property
    def load_evidence(self) -> Callable[[], None] | None:
        return self.evidence_action.callback if self.evidence_action is not None else None

    @property
    def evidence_label(self) -> str:
        return self.evidence_action.label if self.evidence_action is not None else ""

    @property
    def evidence_help(self) -> str:
        return self.evidence_action.help_text if self.evidence_action is not None else ""


def decision_refresh_key(section: str) -> str:
    return DECISION_REFRESH_KEYS[str(section)]


def make_decision_refresh_action(section: str) -> Callable[[], None]:
    """Return a callback that only requests a command-packet refresh."""

    refresh_key = decision_refresh_key(section)

    def _refresh() -> None:
        st.session_state[refresh_key] = True

    return _refresh


def make_evidence_action(
    section: str,
    workflow: str,
    *,
    label: str,
    help_text: str = "",
    callback: Callable[[], None] | None = None,
    state_key: str = "",
    key: str | None = None,
    settings_renderer: Callable[[], None] | None = None,
    settings_label: str = "Evidence settings",
) -> CommandBriefDetailAction | None:
    """Return a renderer-compatible evidence action when a real boundary exists."""
    if callback is None and not state_key:
        return None
    refresh_key = DECISION_REFRESH_KEYS.get(str(section))

    def _load() -> None:
        if callback is not None:
            callback()
            return
        if state_key:
            st.session_state[state_key] = True

    # Guard the contract: evidence must not be modeled as packet refresh.
    if state_key and refresh_key and state_key == refresh_key:
        return None

    action_key = key or f"{section}_{workflow}_{label}".lower().replace(" ", "_")
    return CommandBriefDetailAction(
        label,
        help_text,
        _load,
        key=action_key,
        settings_renderer=settings_renderer,
        settings_label=settings_label,
    )


def render_evidence_settings(label: str, render_body: Callable[[], None] | None, *, expanded: bool = False) -> None:
    """Render compact detail/evidence controls inside the evidence action panel."""
    if render_body is None:
        return
    with st.expander(label, expanded=expanded):
        render_body()


def _slug(value: object) -> str:
    return str(value or "").strip().lower().replace("&", "and").replace(" ", "_")


def _finding_field(finding: object, name: str) -> str:
    return str(getattr(finding, name, "") or "").strip()


SECTION_TARGET_KEYS: dict[str, str] = {
    "Alert Center": "alert_center_evidence_target",
    "Cost & Contract": "cost_contract_evidence_target",
    "DBA Control Room": "dba_control_room_evidence_target",
    "Workload Operations": "workload_operations_evidence_target",
    "Security Monitoring": "security_posture_evidence_target",
}


SECTION_TARGET_COLUMNS: dict[str, tuple[str, ...]] = {
    "Alert Center": (
        "EVENT_ID",
        "ALERT_ID",
        "ALERT_KEY",
        "ALERT_FAMILY",
        "ALERT_TYPE",
        "FAMILY",
        "CATEGORY",
        "ENTITY_NAME",
        "ENTITY_ID",
        "WAREHOUSE_NAME",
        "DATABASE_NAME",
        "USER_NAME",
        "ROLE_NAME",
        "ACTION_ID",
    ),
    "Cost & Contract": (
        "WAREHOUSE_NAME",
        "WAREHOUSE",
        "SERVICE_CATEGORY",
        "SERVICE_TYPE",
        "DATABASE_NAME",
        "USER_NAME",
        "ROLE_NAME",
        "TAG_VALUE",
        "DEPARTMENT",
        "APPLICATION",
        "DRIVER",
        "DIMENSION",
        "ENTITY_NAME",
        "ENTITY_ID",
    ),
    "DBA Control Room": (
        "QUERY_ID",
        "QUERY_HASH",
        "QUERY_SIGNATURE",
        "WAREHOUSE_NAME",
        "TASK_NAME",
        "ROOT_TASK_NAME",
        "PROCEDURE_NAME",
        "DATABASE_NAME",
        "ENTITY_NAME",
        "ENTITY_ID",
    ),
    "Workload Operations": (
        "QUERY_ID",
        "QUERY_HASH",
        "QUERY_SIGNATURE",
        "WAREHOUSE_NAME",
        "TASK_NAME",
        "ROOT_TASK_NAME",
        "PROCEDURE_NAME",
        "PIPELINE_NAME",
        "ENTITY_NAME",
        "ENTITY_ID",
    ),
    "Security Monitoring": (
        "USER_NAME",
        "LOGIN_NAME",
        "ROLE_NAME",
        "GRANTEE_NAME",
        "GRANTED_TO",
        "GRANTED_ON",
        "DATABASE_NAME",
        "SHARE_NAME",
        "OBJECT_NAME",
        "ENTITY_NAME",
        "ENTITY_ID",
        "GRANT_ID",
    ),
}


def current_finding_evidence_target(section: str) -> dict[str, str]:
    target = st.session_state.get(SECTION_TARGET_KEYS.get(str(section), ""))
    if not isinstance(target, dict):
        target = st.session_state.get("decision_workspace_evidence_target")
    if not isinstance(target, dict):
        return {}
    return {str(key): str(value) for key, value in target.items() if str(value or "").strip()}


def evidence_target_label(target: dict[str, str]) -> str:
    if not target:
        return ""
    entity_type = str(target.get("entity_type") or "target").strip()
    value = str(
        target.get("entity_name")
        or target.get("entity_id")
        or target.get("evidence_id")
        or target.get("dedupe_key")
        or ""
    ).strip()
    if not value:
        return ""
    return f"{entity_type}: {value}"


def _target_values(target: dict[str, str]) -> tuple[str, ...]:
    values = []
    for key in ("evidence_id", "entity_id", "entity_name", "dedupe_key", "finding_key"):
        value = str(target.get(key) or "").strip()
        if value and value.upper() not in {item.upper() for item in values}:
            values.append(value)
    return tuple(values)


def filter_evidence_rows_for_target(rows: object, section: str) -> tuple[object, str]:
    """Filter a dataframe-like evidence result to the selected finding target."""
    target = current_finding_evidence_target(section)
    label = evidence_target_label(target)
    values = _target_values(target)
    if not values or rows is None or not hasattr(rows, "empty") or getattr(rows, "empty", True):
        return rows, label
    try:
        columns = [str(column) for column in rows.columns]
    except Exception:
        return rows, label
    preferred = [column for column in SECTION_TARGET_COLUMNS.get(str(section), ()) if column in columns]
    if not preferred:
        preferred = [
            column
            for column in columns
            if any(token in column.upper() for token in ("ID", "KEY", "NAME", "ENTITY", "WAREHOUSE", "USER", "ROLE"))
        ]
    if not preferred:
        return rows, label

    mask = None
    for column in preferred:
        series = rows[column].fillna("").astype(str)
        column_mask = series.str.upper().apply(
            lambda text: any(value.upper() in text for value in values)
        )
        mask = column_mask if mask is None else (mask | column_mask)
    if mask is None:
        return rows, label
    return rows[mask].copy(), label


def apply_finding_evidence_target(finding: object | None, section: str, workflow: str = "") -> dict[str, str]:
    """Store allowlisted evidence target fields before a section loader runs.

    The database may provide an EVIDENCE_QUERY for admin diagnostics, but the app
    never executes it or turns it into session state. Only stable entity/evidence
    identifiers are copied into safe, section-owned keys.
    """
    if finding is None:
        return {}
    target = {
        "section": str(section or ""),
        "workflow": str(workflow or ""),
        "finding_key": _finding_field(finding, "finding_key"),
        "dedupe_key": _finding_field(finding, "dedupe_key"),
        "entity_type": _finding_field(finding, "entity_type"),
        "entity_id": _finding_field(finding, "entity_id"),
        "entity_name": _finding_field(finding, "entity_name") or _finding_field(finding, "entity"),
        "evidence_id": _finding_field(finding, "evidence_id"),
        "evidence_source": _finding_field(finding, "evidence_source"),
    }
    target = {key: value for key, value in target.items() if value}
    if not target:
        return {}

    section_name = str(section or "")
    slug = _slug(section_name)
    st.session_state["decision_workspace_evidence_target"] = target
    st.session_state[f"{slug}_evidence_target"] = target
    if target.get("evidence_id"):
        st.session_state[f"{slug}_evidence_id"] = target["evidence_id"]

    entity_type = target.get("entity_type", "").lower()
    entity_value = target.get("entity_id") or target.get("entity_name") or target.get("evidence_id") or ""
    if section_name == "Alert Center":
        st.session_state["alert_center_evidence_target"] = target
        if target.get("evidence_id"):
            st.session_state["alert_center_evidence_id"] = target["evidence_id"]
            st.session_state["alert_center_alert_key_filter"] = target["evidence_id"]
        if entity_value:
            st.session_state["alert_center_entity_filter"] = entity_value
    elif section_name == "Cost & Contract":
        st.session_state["cost_contract_evidence_target"] = target
        if entity_type in {"warehouse", "warehouse_name"}:
            st.session_state["cc_explorer_lens"] = "Warehouse"
        elif entity_type in {"user", "role", "user_role"}:
            st.session_state["cc_explorer_lens"] = "User / Role"
        elif entity_type in {"service", "cortex", "database"}:
            st.session_state["cc_explorer_lens"] = "Service" if entity_type in {"service", "cortex"} else "Database"
        if entity_value:
            st.session_state["cost_contract_evidence_entity_filter"] = entity_value
    elif section_name == "Workload Operations":
        st.session_state["workload_operations_evidence_target"] = target
        if entity_type in {"query", "query_signature", "query_id"} and entity_value:
            st.session_state["workload_operations_query_filter"] = entity_value
            st.session_state["workload_query_lens"] = "Detailed Diagnosis"
            st.session_state["query_analysis_active_view"] = "Detailed Diagnosis"
        if entity_type in {"task", "procedure", "pipeline"} and entity_value:
            st.session_state["workload_operations_pipeline_filter"] = entity_value
            st.session_state["workload_operations_pipeline_focus"] = (
                "Failed Procedures" if entity_type == "procedure" else "Failed Tasks"
            )
    elif section_name == "Security Monitoring":
        st.session_state["security_posture_evidence_target"] = target
        if entity_type in {"user", "role"}:
            st.session_state["security_posture_view"] = "Failed Logins" if entity_type == "user" else "Risky Grants"
        elif entity_type in {"database", "share", "grant"}:
            st.session_state["security_posture_view"] = "Data Sharing" if entity_type == "share" else "Risky Grants"
        if entity_value:
            st.session_state["security_posture_entity_filter"] = entity_value
    elif section_name == "DBA Control Room":
        st.session_state["dba_control_room_evidence_target"] = target
        if entity_type in {"query", "query_signature", "query_id"} and entity_value:
            st.session_state["dba_control_room_query_filter"] = entity_value
        if entity_type in {"warehouse", "task", "procedure"} and entity_value:
            st.session_state["dba_control_room_entity_filter"] = entity_value
    return target


def should_render_daily_diagnostics(section: str, workflow: str, decision_mode: str) -> bool:
    """Return whether raw setup diagnostics belong on the current user surface."""
    workflow_text = str(workflow or "").lower()
    mode = str(decision_mode or "").upper()
    if st.session_state.get("overwatch_debug_diagnostics") or st.session_state.get("show_internal_diagnostics"):
        return True
    if any(token in workflow_text for token in ("admin", "advanced", "evidence")):
        return True
    if mode in {"OFFLINE", "UNINITIALIZED"} and (
        workflow_text in {"", "overview", "active", "morning"} or workflow_text.startswith("active")
    ):
        return False
    if st.session_state.get(f"{str(section).lower().replace(' ', '_')}_evidence_loaded"):
        return True
    return False


__all__ = [
    "DECISION_REFRESH_KEYS",
    "CommandBriefDetailAction",
    "DecisionWorkspaceControls",
    "apply_finding_evidence_target",
    "decision_refresh_key",
    "current_finding_evidence_target",
    "evidence_target_label",
    "filter_evidence_rows_for_target",
    "make_decision_refresh_action",
    "make_evidence_action",
    "render_evidence_settings",
    "should_render_daily_diagnostics",
]
