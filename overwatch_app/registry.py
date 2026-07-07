"""Truthful v2 section and workflow registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Workflow:
    key: str
    title: str
    renderer: str
    visible: bool = True
    admin_only: bool = False


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    module: str
    workflows: tuple[Workflow, ...]


SECTIONS: tuple[Section, ...] = (
    Section(
        key="executive",
        title="Executive Landing",
        module="overwatch_app.sections.executive",
        workflows=(
            Workflow("overview", "Overview", "render_executive_overview"),
        ),
    ),
    Section(
        key="cost",
        title="Cost Intelligence",
        module="overwatch_app.sections.cost",
        workflows=(
            Workflow("overview", "Overview", "render_cost_overview"),
            Workflow("allocation", "Chargeback / Showback", "render_chargeback_showback"),
        ),
    ),
    Section(
        key="alerts",
        title="Alert Center",
        module="overwatch_app.sections.alerts",
        workflows=(
            Workflow("active", "Active Alerts", "render_alert_inbox"),
        ),
    ),
    Section(
        key="dba",
        title="DBA Control Room",
        module="overwatch_app.sections.dba",
        workflows=(
            Workflow("morning", "Morning Cockpit", "render_morning_cockpit"),
            Workflow("live", "Live Mode", "render_live_mode", admin_only=True),
        ),
    ),
    Section(
        key="workload",
        title="Workload Operations",
        module="overwatch_app.sections.workload",
        workflows=(
            Workflow("overview", "Overview", "render_workload_overview"),
        ),
    ),
    Section(
        key="security",
        title="Security Monitoring",
        module="overwatch_app.sections.security",
        workflows=(
            Workflow("overview", "Overview", "render_security_overview"),
        ),
    ),
)


def visible_sections() -> tuple[Section, ...]:
    return SECTIONS


def visible_workflows(section_key: str, *, include_admin: bool = True) -> tuple[Workflow, ...]:
    for section in SECTIONS:
        if section.key == section_key:
            return tuple(
                workflow
                for workflow in section.workflows
                if workflow.visible and (include_admin or not workflow.admin_only)
            )
    return ()


def workflow_renderer_names() -> tuple[str, ...]:
    return tuple(workflow.renderer for section in SECTIONS for workflow in section.workflows if workflow.visible)
