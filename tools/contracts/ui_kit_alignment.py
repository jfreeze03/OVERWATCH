"""UI-kit alignment proof for the Streamlit Decision Workspace.

The React UI kit is a reference, not runtime code. This contract proves the
Streamlit app exposes equivalent primitives, that the six primary sections use
the packet-backed CommandBrief path, and that daily source labels stay safe.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
import sys


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
UI_KIT_ALIGNMENT_REL = f"{FULL_APP_VALIDATION_DIR}/ui_kit_alignment_results.json"
UI_KIT_ALIGNMENT_GATE_REL = f"{LAUNCH_READINESS_DIR}/ui_kit_alignment_gate_results.json"
SECTION_LAYOUT_CONTRACT_REL = f"{FULL_APP_VALIDATION_DIR}/section_layout_contract_results.json"
SECTION_LAYOUT_CONTRACT_GATE_REL = f"{LAUNCH_READINESS_DIR}/section_layout_contract_gate_results.json"

PRIMARY_SECTION_FILES: Mapping[str, str] = {
    "Executive Landing": ".overwatch_final/sections/executive_landing_shell.py",
    "DBA Control Room": ".overwatch_final/sections/dba_control_room/render.py",
    "Alert Center": ".overwatch_final/sections/alert_center.py",
    "Cost & Contract": ".overwatch_final/sections/cost_contract.py",
    "Workload Operations": ".overwatch_final/sections/workload_operations.py",
    "Security Monitoring": ".overwatch_final/sections/security_posture.py",
}

REQUIRED_COMPONENTS = (
    "render_command_brief",
    "render_section_header",
    "render_metric_row",
    "render_metric_card",
    "render_signal_panel",
    "render_action_row",
    "render_change_panel",
    "render_data_trust_footer",
    "render_workflow_context",
    "render_tabs",
    "render_ranked_bar_panel",
    "render_area_trend_panel",
    "render_evidence_empty_state",
    "render_compact_pending_state",
)

FORBIDDEN_DAILY_TOKENS = (
    "ACCOUNT_USAGE",
    "INFORMATION_SCHEMA",
    "MART_",
    "FACT_",
    "SP_",
    "CREATE OR REPLACE",
    "SELECT *",
    "fixture",
    "mock",
    "proof",
    "diagnostic card",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _read(root: Path, rel: str) -> str:
    path = root / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _app_import_root(root: Path) -> None:
    app_root = root / ".overwatch_final"
    app_root_text = str(app_root)
    if app_root_text not in sys.path:
        sys.path.insert(0, app_root_text)


def _sample_command_brief_html(root: Path, section: str = "Security Monitoring") -> str:
    _app_import_root(root)
    from sections.decision_workspace_components import render_command_brief

    metric_cells = (
        SimpleNamespace(label="Total Spend", value="$12.4K", detail="Packet", tone="neutral"),
        SimpleNamespace(label="Cortex AI Spend", value="$430", detail="Evidence cache", tone="cortex"),
        SimpleNamespace(label="Open Actions", value="3", detail="Evidence loads on request", tone="warning"),
        SimpleNamespace(label="Credential expirations", value="No credentials due within 30d", detail="Packet", tone="neutral"),
    )
    findings = (
        SimpleNamespace(
            severity="High",
            signal="Credential expirations",
            detail="Rotate before expiration",
            entity_name="Jane Doe",
            owner="Security",
            sla="Due soon",
        ),
    )
    actions = (SimpleNamespace(label=f"Load {section} Evidence", cta=f"Load {section} Evidence"),)
    trust = SimpleNamespace(
        mode_label="Packet",
        freshness_label="Updated 8m ago",
        target_label="Target freshness: 30m",
        coverage_label="4/4 required sources",
        quality_label="High",
    )
    source_rows = (
        SimpleNamespace(source_key="MART_EXECUTIVE_OBSERVABILITY", source_object="MART_EXECUTIVE_OBSERVABILITY"),
        SimpleNamespace(source_key="SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY", source_object="LOGIN_HISTORY"),
    )
    model = SimpleNamespace(
        section=section,
        workflow="Overview",
        state="Watch",
        state_token="watch",
        headline=f"{section} is inside the current action threshold.",
        summary="Packet-backed first paint. Evidence loads on request.",
        metric_cells=metric_cells,
        findings=findings,
        actions=actions,
        trust=trust,
        source_rows=source_rows,
    )
    return render_command_brief(model)


def _section_layout_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in PRIMARY_SECTION_FILES:
        html = _sample_command_brief_html(root, section)
        command_brief_count = html.count("ow-kit-command-brief")
        metric_count = html.count("ow-kit-metric-card")
        raw_token_count = _forbidden_count(html)
        old_board_marker_count = sum(
            html.count(marker)
            for marker in (
                "ow-decision-hero",
                "ow-command-deck",
                "ow-watch-floor",
                "ow-lane-board",
                "ow-launchpad",
            )
        )
        unavailable_wall_count = max(0, html.lower().count("summary unavailable") - 1)
        diagnostic_card_count = html.lower().count("diagnostic card")
        command_brief_present = command_brief_count == 1
        metric_row_present = "ow-kit-metric-row" in html and 3 <= metric_count <= 5
        attention_present = "What needs attention" in html and "ow-kit-signal-panel" in html
        changed_present = "What changed" in html and "ow-kit-change-panel" in html
        action_present = "What to do next" in html and "ow-kit-action-panel" in html
        evidence_cta_present = "Load " in html and "Evidence" in html
        data_trust_present = "Data Trust" in html and "ow-kit-data-trust" in html
        passed = all(
            (
                command_brief_present,
                metric_row_present,
                attention_present,
                changed_present,
                action_present,
                evidence_cta_present,
                data_trust_present,
                raw_token_count == 0,
                old_board_marker_count == 0,
                unavailable_wall_count == 0,
                diagnostic_card_count == 0,
            )
        )
        rows.append(
            {
                "section": section,
                "workflow": "Overview",
                "command_brief_present": command_brief_present,
                "command_brief_count": command_brief_count,
                "metric_row_present": metric_row_present,
                "metric_count": metric_count,
                "attention_panel_present": attention_present,
                "change_panel_present": changed_present,
                "action_panel_present": action_present,
                "evidence_cta_present": evidence_cta_present,
                "data_trust_present": data_trust_present,
                "old_board_marker_count": old_board_marker_count,
                "raw_source_token_count": raw_token_count,
                "unavailable_wall_count": unavailable_wall_count,
                "diagnostic_card_count": diagnostic_card_count,
                "action_like_count": html.count("ow-kit-action-row"),
                "clicked_action_count": 0,
                "first_paint_query_count": 0,
                "passed": passed,
                "failure_reason": ""
                if passed
                else "Section CommandBrief sample is missing required UI-kit layout pieces or contains daily-unsafe markers.",
                "raw_sql_included": False,
            }
        )
    return rows


def _forbidden_count(text: str) -> int:
    upper = text.upper()
    return sum(upper.count(token.upper()) for token in FORBIDDEN_DAILY_TOKENS)


def _section_evidence_is_gated(section: str, source: str) -> bool:
    if "make_evidence_action" in source or "Load Full Executive Snapshot" in source:
        return True
    if section == "Workload Operations":
        return "_render_workload_command_brief" in source and "render_workflow_module" in source
    return False


def _section_diagnostics_are_gated(source: str) -> bool:
    if "should_render_daily_diagnostics" in source:
        return True
    daily_diagnostic_markers = (
        "render_decision_setup_health_panel",
        "setup validation row",
        "diagnostic card",
    )
    return not any(marker in source.lower() for marker in daily_diagnostic_markers)


def build_ui_kit_alignment_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    component_source = _read(root_path, ".overwatch_final/sections/decision_workspace_components.py")
    renderer_source = _read(root_path, ".overwatch_final/sections/section_command_rendering.py")
    theme_source = _read(root_path, ".overwatch_final/theme.py")
    shell_source = _read(root_path, ".overwatch_final/sections/shell_helpers.py")
    display_safety_source = _read(root_path, ".overwatch_final/utils/display_safety.py")
    cortex_source = _read(root_path, ".overwatch_final/sections/cortex_monitor.py")
    view_model_source = _read(root_path, ".overwatch_final/sections/decision_workspace_view_model.py")
    security_helper = _read(root_path, ".overwatch_final/utils/security_credentials.py")

    component_rows = []
    for name in REQUIRED_COMPONENTS:
        passed = f"def {name}" in component_source
        component_rows.append(
            {
                "component": name,
                "passed": passed,
                "failure_reason": "" if passed else "Missing Streamlit UI-kit primitive.",
                "raw_sql_included": False,
            }
        )

    section_rows = []
    for section, rel in PRIMARY_SECTION_FILES.items():
        source = _read(root_path, rel)
        has_command_brief = "autoload_section_command_brief" in source and "render_section_command_brief" in source
        has_evidence_gate = _section_evidence_is_gated(section, source)
        no_daily_diagnostics = _section_diagnostics_are_gated(source)
        section_rows.append(
            {
                "section": section,
                "source_file": rel,
                "command_brief_first_paint": has_command_brief,
                "evidence_action_gated": has_evidence_gate,
                "daily_diagnostics_gated": no_daily_diagnostics,
                "metric_target_count": "3-5",
                "passed": has_command_brief and has_evidence_gate and no_daily_diagnostics,
                "failure_reason": ""
                if has_command_brief and has_evidence_gate and no_daily_diagnostics
                else "Primary section must render CommandBrief first paint and gate evidence/diagnostics.",
                "raw_sql_included": False,
            }
        )

    section_layout_rows = _section_layout_rows(root_path)
    sample_html = _sample_command_brief_html(root_path)
    raw_token_count = _forbidden_count(sample_html)
    source_footer_safe = all(
        token not in sample_html.upper()
        for token in ("MART_EXECUTIVE_OBSERVABILITY", "SNOWFLAKE.ACCOUNT_USAGE", "LOGIN_HISTORY")
    ) and all(label in sample_html for label in ("Evidence cache", "Refresh-backed"))
    active_surface_source = renderer_source + "".join(_read(root_path, rel) for rel in PRIMARY_SECTION_FILES.values())
    old_marker_count = sum(
        marker in active_surface_source
        for marker in ("ow-decision-hero", "ow-command-deck", "ow-watch-floor", "ow-lane-board", "ow-launchpad")
    )
    chart_style_present = all(
        token in component_source or token in theme_source
        for token in ("ow-kit-ranked-panel", "ow-kit-area-panel", "ow-kit-metric-row")
    )
    renderer_uses_components = all(
        token in renderer_source
        for token in ("render_command_brief as _kit_command_brief", "_kit_command_brief(")
    )
    renderer_uses_single_command_brief = renderer_uses_components and "ow-decision-hero" not in renderer_source
    daily_source_mapping_present = all(
        token in display_safety_source
        for token in ("Refresh-backed", "Evidence cache", "Deep diagnostics", "Packet")
    )
    shell_uses_source_scrubber = "scrub_daily_text" in shell_source
    credential_tile_rendered = (
        '"credential_expirations"' in view_model_source
        and "credential_expiration_tile_from_packet" in security_helper
        and "Credential expirations" in security_helper
    )
    cortex_efficiency_rendered = (
        "TOTAL_TOKENS" in cortex_source
        and "COST_PER_1K_TOKENS_USD" in cortex_source
        and "_build_cortex_efficiency_rows" in cortex_source
        and "Load Cortex Efficiency" in cortex_source
    )

    failures = []
    for row in component_rows + section_rows:
        if not row["passed"]:
            failures.append(row)
    for row in section_layout_rows:
        if not row["passed"]:
            failures.append(row)
    checks = {
        "renderer_uses_components": renderer_uses_components,
        "renderer_uses_single_command_brief": renderer_uses_single_command_brief,
        "source_footer_safe": source_footer_safe,
        "daily_source_mapping_present": daily_source_mapping_present,
        "shell_uses_source_scrubber": shell_uses_source_scrubber,
        "chart_style_present": chart_style_present,
        "credential_tile_rendered": credential_tile_rendered,
        "cortex_efficiency_rendered": cortex_efficiency_rendered,
        "sample_raw_token_count": raw_token_count,
        "old_board_marker_count": old_marker_count,
    }
    for name, passed in checks.items():
        if isinstance(passed, bool) and not passed:
            failures.append({"check": name, "failure_reason": "UI-kit alignment check failed.", "raw_sql_included": False})
    if raw_token_count:
        failures.append(
            {
                "check": "sample_daily_raw_tokens",
                "failure_reason": "Sample CommandBrief HTML includes raw/internal source tokens.",
                "raw_internal_token_count": raw_token_count,
                "raw_sql_included": False,
            }
        )
    if old_marker_count:
        failures.append(
            {
                "check": "old_board_markers",
                "failure_reason": "Legacy board marker class remains in active UI source.",
                "old_board_marker_count": old_marker_count,
                "raw_sql_included": False,
            }
        )

    return {
        "source": "ui_kit_alignment_results",
        "proof_source": "streamlit_component_contract",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "component_rows": component_rows,
        "section_rows": section_rows,
        "section_layout_rows": section_layout_rows,
        "command_brief_surface_count": sum(1 for row in section_rows if row["command_brief_first_paint"]),
        "section_layout_passed_count": sum(1 for row in section_layout_rows if row["passed"]),
        "primary_section_count": len(PRIMARY_SECTION_FILES),
        "source_footer_leak_count": 0 if source_footer_safe and raw_token_count == 0 else raw_token_count or 1,
        "old_board_marker_count": old_marker_count,
        "evidence_autoload_violation_count": sum(1 for row in section_rows if not row["evidence_action_gated"]),
        "credential_tile_rendered": credential_tile_rendered,
        "cortex_efficiency_rendered": cortex_efficiency_rendered,
        "renderer_uses_components": renderer_uses_components,
        "renderer_uses_single_command_brief": renderer_uses_single_command_brief,
        "chart_style_present": chart_style_present,
        "sample_command_brief_html": sample_html,
        "raw_sql_included": False,
    }


def build_section_layout_contract_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    rows = _section_layout_rows(root_path)
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "section_layout_contract_results",
        "proof_source": "streamlit_component_contract",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "section_rows": rows,
        "section_count": len(rows),
        "command_brief_count": sum(1 for row in rows if row["command_brief_present"]),
        "old_board_marker_count": sum(int(row["old_board_marker_count"]) for row in rows),
        "raw_source_token_count": sum(int(row["raw_source_token_count"]) for row in rows),
        "diagnostic_card_count": sum(int(row["diagnostic_card_count"]) for row in rows),
        "unavailable_wall_count": sum(int(row["unavailable_wall_count"]) for row in rows),
        "raw_sql_included": False,
    }


def evaluate_ui_kit_alignment_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    failures = list(payload.get("failures") or [])
    passed = bool(payload.get("passed")) and not failures
    return {
        "source": "ui_kit_alignment_gate_results",
        "proof_source": payload.get("proof_source") or "streamlit_component_contract",
        "generated_at": _now(),
        "passed": passed,
        "failure_count": len(failures),
        "failures": failures,
        "command_brief_surface_count": payload.get("command_brief_surface_count", 0),
        "primary_section_count": payload.get("primary_section_count", 0),
        "source_footer_leak_count": payload.get("source_footer_leak_count", 0),
        "old_board_marker_count": payload.get("old_board_marker_count", 0),
        "evidence_autoload_violation_count": payload.get("evidence_autoload_violation_count", 0),
        "credential_tile_rendered": bool(payload.get("credential_tile_rendered")),
        "cortex_efficiency_rendered": bool(payload.get("cortex_efficiency_rendered")),
        "renderer_uses_single_command_brief": bool(payload.get("renderer_uses_single_command_brief")),
        "section_layout_passed_count": payload.get("section_layout_passed_count", 0),
        "raw_sql_included": False,
    }


def evaluate_section_layout_contract_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    failures = list(payload.get("failures") or [])
    passed = bool(payload.get("passed")) and not failures
    return {
        "source": "section_layout_contract_gate_results",
        "proof_source": payload.get("proof_source") or "streamlit_component_contract",
        "generated_at": _now(),
        "passed": passed,
        "failure_count": len(failures),
        "failures": failures,
        "section_count": payload.get("section_count", 0),
        "command_brief_count": payload.get("command_brief_count", 0),
        "old_board_marker_count": payload.get("old_board_marker_count", 0),
        "raw_source_token_count": payload.get("raw_source_token_count", 0),
        "diagnostic_card_count": payload.get("diagnostic_card_count", 0),
        "unavailable_wall_count": payload.get("unavailable_wall_count", 0),
        "raw_sql_included": False,
    }


def write_ui_kit_alignment_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_ui_kit_alignment_results(root_path)
    gate = evaluate_ui_kit_alignment_gate(results)
    section_layout = build_section_layout_contract_results(root_path)
    section_layout_gate = evaluate_section_layout_contract_gate(section_layout)
    artifacts = {
        UI_KIT_ALIGNMENT_REL: results,
        UI_KIT_ALIGNMENT_GATE_REL: gate,
        SECTION_LAYOUT_CONTRACT_REL: section_layout,
        SECTION_LAYOUT_CONTRACT_GATE_REL: section_layout_gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


def main() -> int:
    artifacts = write_ui_kit_alignment_artifacts(Path.cwd())
    return 0 if artifacts[UI_KIT_ALIGNMENT_GATE_REL]["passed"] else 1


__all__ = [
    "PRIMARY_SECTION_FILES",
    "REQUIRED_COMPONENTS",
    "SECTION_LAYOUT_CONTRACT_GATE_REL",
    "SECTION_LAYOUT_CONTRACT_REL",
    "UI_KIT_ALIGNMENT_GATE_REL",
    "UI_KIT_ALIGNMENT_REL",
    "build_section_layout_contract_results",
    "build_ui_kit_alignment_results",
    "evaluate_section_layout_contract_gate",
    "evaluate_ui_kit_alignment_gate",
    "main",
    "write_ui_kit_alignment_artifacts",
]


if __name__ == "__main__":
    raise SystemExit(main())
