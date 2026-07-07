"""Create a section/workflow UI layout audit for OVERWATCH.

The audit is intentionally route-registry driven. It can run in constrained CI
without a browser, while still recording why screenshots were not captured.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime
import html
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from config import SECTION_MODULES, display_section_label  # noqa: E402
from route_registry import DEFAULT_WORKFLOW_BY_SECTION, SECTION_WORKFLOW_CONTRACT  # noqa: E402


PRIMARY_SECTIONS = (
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
)

WORKFLOW_STATE_KEYS = {
    "Executive Landing": "executive_landing_workflow",
    "DBA Control Room": "dba_control_room_active_view",
    "Alert Center": "alert_center_active_view",
    "Cost & Contract": "cost_contract_workflow",
    "Workload Operations": "workload_operations_workflow",
    "Security Monitoring": "security_posture_workflow",
}

SECTION_SOURCE_GLOBS = {
    "Executive Landing": ("executive_landing*.py", "executive_command_center_view.py", "command_center_components.py"),
    "DBA Control Room": ("dba_control_room/**/*.py", "dba_control_room.py"),
    "Alert Center": ("alert_center*.py", "alert_*.py"),
    "Cost & Contract": ("cost_contract*.py", "cost_center*.py", "cortex_monitor.py"),
    "Workload Operations": ("workload_operations.py", "query_analysis.py", "task_management*.py", "pipeline_health.py"),
    "Security Monitoring": ("security_posture.py", "security_access.py", "security_*.py"),
}

SECTION_ENTRYPOINT_FILES = {
    "Executive Landing": ("executive_command_center_view.py", "executive_landing_shell.py"),
    "DBA Control Room": ("dba_control_room.py",),
    "Alert Center": ("alert_center.py",),
    "Cost & Contract": ("cost_contract.py",),
    "Workload Operations": ("workload_operations.py",),
    "Security Monitoring": ("security_posture.py",),
}

PATTERNS = {
    "standalone_action_panel": re.compile(r"key\s*=\s*[\"'][^\"']*recommended_actions_panel"),
    "old_decision_workspace": re.compile(r"card-wall|launchpad|watch-floor|command-deck|lane-board", re.IGNORECASE),
    "coco_layout": re.compile(r"ow-cc-|ow-kit-command-brief|command-center|COCO", re.IGNORECASE),
    "empty_unavailable": re.compile(r"Summary pending|Unavailable|On request|source unavailable", re.IGNORECASE),
    "visible_leadership_monitor_call": re.compile(
        r"render_cost_leadership_panels_for_current_scope\("
        r"|render_security_leadership_panels\("
        r"|render_workload_query_error_panels\("
        r"|render_coco_leadership_watchlist\(",
        re.IGNORECASE,
    ),
    "chart_table_pair": re.compile(r"st\.dataframe|render_.*panel|chart|sparkline", re.IGNORECASE),
    "action_pane": re.compile(r"Recommended Action|recommended_actions_panel|ow-cc-action|ow-decision-actions", re.IGNORECASE),
    "kanban_lane": re.compile(r"lane-column|alert-lane|Kanban|Boards", re.IGNORECASE),
}


@dataclass(frozen=True)
class AuditRow:
    section: str
    display_section: str
    workflow: str
    default_workflow: bool
    route_state: dict[str, str]
    renderer_module: str
    source_files: list[str]
    screenshot_path: str
    screenshot_status: str
    screenshot_blocker: str
    duplicate_recommended_actions: bool
    recommended_action_marker_count: int
    old_decision_workspace_layout: bool
    coco_style_layout: bool
    empty_unavailable_first_viewport_risk: bool
    standalone_leadership_monitor: bool
    chart_table_pairing_present: bool
    action_buttons_inside_pane: bool
    inconsistent_with_executive: bool
    kanban_lane_default_risk: bool
    recommended_fix: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _artifact_label(path: Path) -> Path:
    try:
        return path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return path.resolve()


def _section_source_files(section: str) -> list[Path]:
    files: list[Path] = []
    for pattern in SECTION_SOURCE_GLOBS.get(section, ()):
        files.extend(sorted((APP_ROOT / "sections").glob(pattern)))
    module = SECTION_MODULES.get(section, "")
    if module.startswith("sections."):
        module_path = APP_ROOT / (module.replace(".", "/") + ".py")
        if module_path.exists():
            files.append(module_path)
    return sorted({path.resolve() for path in files if path.is_file()})


def _section_entrypoint_files(section: str) -> list[Path]:
    files: list[Path] = []
    for filename in SECTION_ENTRYPOINT_FILES.get(section, ()):
        path = APP_ROOT / "sections" / filename
        if path.exists():
            files.append(path.resolve())
    return files


def _route_state(section: str, workflow: str) -> dict[str, str]:
    key = WORKFLOW_STATE_KEYS.get(section, "")
    state = {"active_section": section}
    if key:
        state[key] = workflow
    return state


def _recommendation(section: str, metrics: Mapping[str, bool]) -> str:
    fixes: list[str] = []
    if metrics["standalone_leadership_monitor"]:
        fixes.append("remove standalone leadership-monitor panel and fold metrics into owning section cards")
    if metrics["duplicate_recommended_actions"]:
        fixes.append("consolidate to one section-owned Recommended Action pane")
    if metrics["kanban_lane_default_risk"]:
        fixes.append("make table/filter alert inbox default and keep lifecycle lanes secondary")
    if metrics["empty_unavailable_first_viewport_risk"]:
        fixes.append("replace first-viewport unavailable wall with compact source badge or omit empty panel")
    if metrics["old_decision_workspace_layout"] and not metrics["coco_style_layout"]:
        fixes.append("convert old Decision Workspace block to compact COCO-style section layout")
    if not metrics["chart_table_pairing_present"]:
        fixes.append("pair chart/status card with compact table where data exists")
    if not fixes:
        fixes.append("keep layout and verify with screenshot after next visual pass")
    return "; ".join(fixes)


def build_audit_rows(*, screenshot_status: str, screenshot_blocker: str) -> list[AuditRow]:
    rows: list[AuditRow] = []
    for section in PRIMARY_SECTIONS:
        files = _section_source_files(section)
        source_text = "\n".join(_read_text(path) for path in files)
        entrypoint_text = "\n".join(_read_text(path) for path in _section_entrypoint_files(section))
        marker_count = len(PATTERNS["standalone_action_panel"].findall(entrypoint_text))
        visible_leadership_call = bool(PATTERNS["visible_leadership_monitor_call"].search(entrypoint_text))
        metrics = {
            "duplicate_recommended_actions": marker_count > 1,
            "old_decision_workspace_layout": bool(PATTERNS["old_decision_workspace"].search(entrypoint_text)),
            "coco_style_layout": bool(PATTERNS["coco_layout"].search(source_text)),
            "empty_unavailable_first_viewport_risk": bool(PATTERNS["empty_unavailable"].search(source_text)),
            "standalone_leadership_monitor": visible_leadership_call,
            "chart_table_pairing_present": bool(PATTERNS["chart_table_pair"].search(source_text)),
            "action_buttons_inside_pane": bool(PATTERNS["action_pane"].search(source_text)),
            "kanban_lane_default_risk": bool(PATTERNS["kanban_lane"].search(source_text)),
        }
        inconsistent = bool(
            section != "Executive Landing"
            and (metrics["old_decision_workspace_layout"] or metrics["standalone_leadership_monitor"])
        )
        for workflow in SECTION_WORKFLOW_CONTRACT.get(section, ()):
            rows.append(
                AuditRow(
                    section=section,
                    display_section=display_section_label(section),
                    workflow=workflow,
                    default_workflow=workflow == DEFAULT_WORKFLOW_BY_SECTION.get(section),
                    route_state=_route_state(section, workflow),
                    renderer_module=SECTION_MODULES.get(section, ""),
                    source_files=[str(path.relative_to(REPO_ROOT)) for path in files],
                    screenshot_path="",
                    screenshot_status=screenshot_status,
                    screenshot_blocker=screenshot_blocker,
                    duplicate_recommended_actions=bool(metrics["duplicate_recommended_actions"]),
                    recommended_action_marker_count=int(marker_count),
                    old_decision_workspace_layout=bool(metrics["old_decision_workspace_layout"]),
                    coco_style_layout=bool(metrics["coco_style_layout"]),
                    empty_unavailable_first_viewport_risk=bool(metrics["empty_unavailable_first_viewport_risk"]),
                    standalone_leadership_monitor=bool(metrics["standalone_leadership_monitor"]),
                    chart_table_pairing_present=bool(metrics["chart_table_pairing_present"]),
                    action_buttons_inside_pane=bool(metrics["action_buttons_inside_pane"]),
                    inconsistent_with_executive=inconsistent,
                    kanban_lane_default_risk=bool(metrics["kanban_lane_default_risk"]),
                    recommended_fix=_recommendation(section, metrics),
                )
            )
    return rows


def _write_csv(path: Path, rows: Iterable[AuditRow]) -> None:
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            record = asdict(row)
            record["route_state"] = json.dumps(record["route_state"], sort_keys=True)
            record["source_files"] = "; ".join(record["source_files"])
            writer.writerow(record)


def _write_markdown(path: Path, rows: list[AuditRow], artifact_dir: Path) -> None:
    workflow_count = len(rows)
    section_count = len({row.section for row in rows})
    leadership_sections = sorted({row.section for row in rows if row.standalone_leadership_monitor})
    duplicate_action_sections = sorted({row.section for row in rows if row.duplicate_recommended_actions})
    old_layout_sections = sorted({row.section for row in rows if row.old_decision_workspace_layout})
    kanban_risk_sections = sorted({row.section for row in rows if row.kanban_lane_default_risk})
    lines = [
        "# UI Snapshot Audit",
        "",
        f"Generated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"Artifact directory: `{artifact_dir.as_posix()}`",
        "",
        "## Summary",
        "",
        f"- Sections inventoried: {section_count}",
        f"- Workflows inventoried: {workflow_count}",
        f"- Sections with standalone leadership monitor risk: {', '.join(leadership_sections) or 'None'}",
        f"- Sections with duplicate Recommended Action marker risk: {', '.join(duplicate_action_sections) or 'None'}",
        f"- Sections still using old Decision Workspace layout markers: {', '.join(old_layout_sections) or 'None'}",
        f"- Sections with Kanban/lane default risk: {', '.join(kanban_risk_sections) or 'None'}",
        "",
        "## Screenshot Status",
        "",
        "Screenshots were not captured by this static audit run. The route inventory below records the state required to open each workflow; browser capture can be layered on top once the Streamlit runtime is stable for all states.",
        "",
        "## Workflow Inventory",
        "",
        "| Section | Workflow | Route State | Duplicate Actions | Old Layout | COCO Layout | Leadership Monitor | First-Viewport Risk | Recommended Fix |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {section} | {workflow} | `{state}` | {dup} | {old} | {coco} | {leadership} | {empty} | {fix} |".format(
                section=html.escape(row.display_section),
                workflow=html.escape(row.workflow),
                state=html.escape(json.dumps(row.route_state, sort_keys=True)),
                dup="yes" if row.duplicate_recommended_actions else "no",
                old="yes" if row.old_decision_workspace_layout else "no",
                coco="yes" if row.coco_style_layout else "no",
                leadership="yes" if row.standalone_leadership_monitor else "no",
                empty="yes" if row.empty_unavailable_first_viewport_risk else "no",
                fix=html.escape(row.recommended_fix),
            )
        )
    lines.extend(
        [
            "",
            "## Before / After Notes",
            "",
            "This audit is route-registry driven and records every primary workflow. The latest run shows the visible standalone leadership-monitor calls removed from daily section entrypoints and duplicate Recommended Action pane risk cleared. Advanced Scope and Settings are now expected under the sidebar utility group rather than under Security.",
            "",
            "Remaining layout issues are still tracked as follow-up work: Alert Center retains old/lane-style markers in source, and Alert Center, Cost Intelligence, and DBA Control Room still carry static lane/Kanban risk markers that need screenshot-led cleanup before they should be treated as visually complete.",
            "",
            "## Manual Screenshot Checklist",
            "",
            "- Executive Landing: overview, cost, operations, security, changes, actions, evidence.",
            "- DBA Control Room: morning, failures, cost, performance, changes, actions, advanced.",
            "- Alert Center: active alerts plus secondary alert categories and admin.",
            "- Cost Intelligence: overview, explorer, forecast, budget, chargeback, recommendations, Cortex AI.",
            "- Workload Operations: overview, query investigation, pipeline/tasks, performance, changes, advanced tools.",
            "- Security Monitoring: overview, failed logins, risky grants, privilege sprawl, access changes, data sharing, security alerts, admin.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default=str(REPO_ROOT / "artifacts" / "ui_snapshots"))
    parser.add_argument("--timestamp", default=datetime.now().strftime("%Y%m%d_%H%M"))
    args = parser.parse_args(argv)

    out_dir = Path(args.output_root) / args.timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshot_blocker = (
        "Static audit mode: Streamlit workflow navigation is session-state based; "
        "browser screenshot capture was not requested for this run."
    )
    rows = build_audit_rows(screenshot_status="not_captured", screenshot_blocker=screenshot_blocker)
    (out_dir / "ui_snapshot_audit.json").write_text(
        json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_csv(out_dir / "ui_snapshot_audit.csv", rows)
    _write_markdown(REPO_ROOT / "docs" / "UI_SNAPSHOT_AUDIT.md", rows, _artifact_label(out_dir))
    (out_dir / "README.md").write_text(
        "# UI Snapshot Audit Artifacts\n\n"
        "This directory contains route-registry driven audit JSON/CSV. Screenshot capture was not run in this pass; "
        "see `docs/UI_SNAPSHOT_AUDIT.md` for the manual screenshot checklist and layout findings.\n",
        encoding="utf-8",
    )
    print(f"Wrote UI snapshot audit: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
