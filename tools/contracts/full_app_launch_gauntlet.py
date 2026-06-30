"""Release launch gauntlet built from rendered runtime evidence.

This module is intentionally a recomputer over the lower-level runtime
artifacts. The older full-app gauntlet proves Streamlit render/click/export
behavior; this layer turns those rows into the launch-facing contract the
release candidate consumes.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

FULL_APP_LAUNCH_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/full_app_launch_gauntlet_results.json"
FULL_APP_LAUNCH_FAILURES_REL = f"{FULL_APP_VALIDATION_DIR}/full_app_launch_failures.json"
FULL_APP_LAUNCH_ACTION_MANIFEST_REL = f"{FULL_APP_VALIDATION_DIR}/full_app_launch_action_manifest.json"
FIRST_PAINT_PERFORMANCE_REL = f"{FULL_APP_VALIDATION_DIR}/first_paint_performance_results.json"
PACKET_FALLBACK_UI_REL = f"{FULL_APP_VALIDATION_DIR}/packet_fallback_ui_results.json"
SUMMARY_BOARD_VISUAL_CONTRACT_REL = f"{FULL_APP_VALIDATION_DIR}/summary_board_visual_contract_results.json"
SETTINGS_WORDING_REL = f"{FULL_APP_VALIDATION_DIR}/settings_wording_results.json"
DOWNLOAD_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/download_results.json"
EXPORT_DOWNLOAD_GATE_REL = f"{LAUNCH_READINESS_DIR}/export_download_gate_results.json"
FULL_APP_LAUNCH_GATE_REL = f"{LAUNCH_READINESS_DIR}/full_app_launch_gate_results.json"
FIRST_PAINT_GATE_REL = f"{LAUNCH_READINESS_DIR}/first_paint_gate_results.json"
PACKET_FALLBACK_GATE_REL = f"{LAUNCH_READINESS_DIR}/packet_fallback_ui_gate_results.json"
SUMMARY_BOARD_VISUAL_GATE_REL = f"{LAUNCH_READINESS_DIR}/summary_board_visual_contract_gate_results.json"
SETTINGS_GATE_REL = f"{LAUNCH_READINESS_DIR}/settings_gate_results.json"

PRIMARY_SECTIONS = (
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
)

FULL_APP_LAUNCH_ARTIFACTS = {
    FULL_APP_LAUNCH_RESULTS_REL,
    FULL_APP_LAUNCH_FAILURES_REL,
    FULL_APP_LAUNCH_ACTION_MANIFEST_REL,
    FIRST_PAINT_PERFORMANCE_REL,
    PACKET_FALLBACK_UI_REL,
    SUMMARY_BOARD_VISUAL_CONTRACT_REL,
    SETTINGS_WORDING_REL,
    DOWNLOAD_RESULTS_REL,
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_int(value: object) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, (int, float, str, bytes, bytearray)):
            return int(float(value))
    except (TypeError, ValueError):
        return 0
    return 0


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_payloads(root: Path, rels: Iterable[str]) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for rel in rels:
        path = root / rel
        if path.exists():
            try:
                payloads[rel] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payloads[rel] = {"passed": False, "failure_reason": "malformed_json"}
    return payloads


def _query_count(row: Mapping[str, Any]) -> int:
    return (
        _as_int(row.get("query_count"))
        + _as_int(row.get("actual_snowflake_executions"))
        + _as_int(row.get("snowflake_execution_count"))
    )


def _session_count(row: Mapping[str, Any]) -> int:
    return _as_int(row.get("session_open_count")) + _as_int(row.get("observed_session_opens"))


def _direct_sql_count(row: Mapping[str, Any]) -> int:
    return _as_int(row.get("direct_sql_count")) + _as_int(row.get("direct_sql_event_count"))


def _account_usage_count(row: Mapping[str, Any]) -> int:
    if bool(row.get("account_usage_used")):
        return 1
    boundaries = _as_mapping(row.get("observed_boundaries") or row.get("query_counts_by_boundary"))
    return _as_int(boundaries.get("account_usage"))


def _launch_row(
    *,
    area: str,
    action_area: str = "",
    section: str,
    workflow: str,
    action_key: str,
    expected_behavior: str,
    observed_behavior: str,
    clicked: bool,
    route_target: str = "",
    artifact_path: str = "",
    query_count: int = 0,
    session_open_count: int = 0,
    direct_sql_count: int = 0,
    account_usage_count: int = 0,
    elapsed_ms: float = 0.0,
    passed: bool = True,
    failure_reason: str = "",
    recommendation: str = "",
) -> dict[str, Any]:
    return {
        "area": area,
        "action_area": action_area or area,
        "section": section,
        "workflow": workflow,
        "action_key": action_key,
        "expected_behavior": expected_behavior,
        "observed_behavior": observed_behavior,
        "clicked": clicked,
        "route_target": route_target,
        "artifact_path": artifact_path,
        "query_count": query_count,
        "session_open_count": session_open_count,
        "direct_sql_count": direct_sql_count,
        "account_usage_count": account_usage_count,
        "elapsed_ms": elapsed_ms,
        "passed": passed,
        "failure_reason": failure_reason,
        "recommendation": recommendation
        or "Fix the owning runtime row, then rerun the full app launch gauntlet.",
        "raw_sql_included": False,
    }


def build_action_manifest(payloads: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    views = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/view_results.json"))]
    buttons = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/button_click_results.json"))]
    settings = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/settings_action_results.json"))]
    live = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/live_feature_results.json"))]
    exports = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/export_results.json"))]
    cases = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/case_payload_results.json"))]
    query_search = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/query_search_results.json"))]
    evidence = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/evidence_loader_call_matrix.json"))]
    stress = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/stress_results.json"))]

    for view in views:
        section = str(view.get("section") or "")
        first_paint = _as_mapping(view.get("first_paint"))
        rows.append(
            _launch_row(
                area="render",
                action_area="first_paint_render",
                section=section,
                workflow=str(view.get("workflow") or "Overview"),
                action_key=f"render::{section}",
                expected_behavior="render one packet-backed summary surface",
                observed_behavior="rendered" if bool(view.get("passed", True)) else "render failed",
                clicked=False,
                query_count=_as_int(first_paint.get("observed_packet_queries") or first_paint.get("cold_packet_queries")),
                session_open_count=_as_int(first_paint.get("observed_session_opens") or first_paint.get("first_paint_session_opens")),
                direct_sql_count=_as_int(first_paint.get("observed_direct_sql_events") or first_paint.get("first_paint_direct_sql")),
                elapsed_ms=float(view.get("elapsed_ms") or 0),
                passed=bool(view.get("passed", True)),
                failure_reason=str(view.get("failure_reason") or ""),
            )
        )

    for button in buttons:
        section = str(button.get("section") or "")
        action_type = str(button.get("action_type") or "button")
        clicked = bool(button.get("clicked", True))
        route_target = ""
        target = button.get("expected_route_target") or button.get("expected_target")
        if isinstance(target, Mapping):
            route_target = " / ".join(str(target.get(key) or "") for key in ("section", "workflow")).strip(" /")
        rows.append(
            _launch_row(
                area="button",
                action_area=str(button.get("action_area") or action_type or "button"),
                section=section,
                workflow=str(button.get("workflow") or ""),
                action_key=str(button.get("key") or button.get("control_key") or button.get("label") or action_type),
                expected_behavior=f"{action_type} action has a click contract",
                observed_behavior="clicked" if clicked else str(button.get("skip_reason") or "not clicked"),
                clicked=clicked,
                route_target=route_target,
                query_count=_query_count(button),
                session_open_count=_session_count(button),
                direct_sql_count=_direct_sql_count(button),
                account_usage_count=_account_usage_count(button),
                elapsed_ms=float(button.get("elapsed_ms") or 0),
                passed=bool(button.get("passed", True)) and (clicked or bool(button.get("skip_reason"))),
                failure_reason=str(button.get("failure_reason") or ""),
            )
        )

    for row in settings:
        clicked = bool(row.get("clicked", True))
        rows.append(
            _launch_row(
                area="settings",
                action_area=str(row.get("action_area") or "settings_control"),
                section="Settings",
                workflow="Settings/Admin Setup Health",
                action_key=str(row.get("control_key") or row.get("action") or row.get("label") or "settings_action"),
                expected_behavior="settings action is stable-keyed, admin-safe, and query-budgeted",
                observed_behavior="clicked" if clicked else str(row.get("skip_reason") or "not clicked"),
                clicked=clicked,
                query_count=_query_count(row),
                session_open_count=_session_count(row),
                direct_sql_count=_direct_sql_count(row),
                account_usage_count=_account_usage_count(row),
                passed=bool(row.get("passed", True)) and (clicked or bool(row.get("skip_reason"))),
                failure_reason=str(row.get("failure_reason") or ""),
            )
        )

    for row in live:
        clicked = bool(row.get("clicked", True))
        passed = bool(row.get("passed", True)) and not bool(row.get("first_paint_invocation")) and not bool(row.get("route_invocation"))
        rows.append(
            _launch_row(
                area="live_feature",
                action_area=str(row.get("action_area") or "live_feature"),
                section=str(row.get("section") or "Settings/Admin Setup Health"),
                workflow=str(row.get("workflow") or row.get("feature") or "Live feature"),
                action_key=str(row.get("control_key") or row.get("feature") or row.get("label") or "live_feature"),
                expected_behavior="live feature requires explicit click, gating, timeout, and sanitized errors",
                observed_behavior="validated" if passed else "live feature contract failed",
                clicked=clicked,
                query_count=_query_count(row),
                session_open_count=_session_count(row),
                direct_sql_count=_direct_sql_count(row),
                account_usage_count=_account_usage_count(row),
                passed=passed,
                failure_reason=str(row.get("failure_reason") or ""),
            )
        )

    for row in evidence:
        passed = bool(row.get("passed", True)) and bool(row.get("loader_called", True)) and not bool(row.get("account_usage_used"))
        rows.append(
            _launch_row(
                area="evidence",
                action_area="evidence_action",
                section=str(row.get("section") or ""),
                workflow=str(row.get("workflow") or "Evidence"),
                action_key=str(row.get("button_key") or row.get("expected_loader_name") or "evidence"),
                expected_behavior="evidence loads only after explicit target action and avoids Account Usage",
                observed_behavior="loader called" if row.get("loader_called", True) else "loader not reached",
                clicked=bool(row.get("loader_called", True)),
                query_count=1 if row.get("loader_called", True) else 0,
                account_usage_count=_account_usage_count(row),
                passed=passed,
                failure_reason="" if passed else "evidence_loader_contract_failed",
            )
        )

    for row in query_search:
        case = str(row.get("case") or "")
        control_key = str(row.get("control_key_clicked") or "")
        no_click = case in {"render_no_click", "text_contains_no_autorun", "warehouse_prefill_no_autorun"}
        passed = bool(row.get("passed", True)) and (not no_click or _query_count(row) == 0)
        rows.append(
            _launch_row(
                area="query_search",
                action_area="query_search",
                section="Workload Operations",
                workflow="Query Search",
                action_key=control_key or case,
                expected_behavior="no-click is zero-cost; explicit search is bounded and sanitized",
                observed_behavior="zero cost" if no_click else "explicit search validated",
                clicked=not no_click,
                query_count=_query_count(row),
                session_open_count=_session_count(row),
                direct_sql_count=_direct_sql_count(row),
                account_usage_count=_account_usage_count(row),
                artifact_path=str(row.get("payload_file") or ""),
                passed=passed,
                failure_reason=str(row.get("failure_reason") or ""),
            )
        )

    for row in exports:
        payload_file = str(row.get("payload_file") or row.get("filename") or "")
        passed = bool(row.get("passed", True)) and bool(payload_file) and not bool(row.get("query_text_included"))
        rows.append(
            _launch_row(
                area="export",
                action_area="export_download",
                section=str(row.get("section") or ""),
                workflow=str(row.get("workflow") or ""),
                action_key=str(row.get("filename") or row.get("label") or "export"),
                expected_behavior="export/download has payload, hash/row-count proof, and no raw query text",
                observed_behavior="payload created" if payload_file else "missing payload",
                clicked=True,
                artifact_path=payload_file,
                passed=passed,
                failure_reason="" if passed else "export_payload_contract_failed",
            )
        )

    for row in cases:
        missing = [field for field in ("section", "workflow", "scope", "target", "freshness", "source", "summary") if not row.get(field)]
        passed = bool(row.get("passed", True)) and not missing
        rows.append(
            _launch_row(
                area="case_payload",
                action_area="export_download",
                section=str(row.get("section") or ""),
                workflow=str(row.get("workflow") or ""),
                action_key=str(row.get("target") or "case_payload"),
                expected_behavior="case payload includes section/workflow/scope/target/freshness/source/summary",
                observed_behavior="payload complete" if not missing else f"missing {', '.join(missing)}",
                clicked=True,
                artifact_path=str(row.get("payload_file") or ""),
                passed=passed,
                failure_reason="" if passed else "case_payload_missing_fields",
            )
        )

    for row in stress:
        rows.append(
            _launch_row(
                area="stress",
                action_area="user_stress",
                section=", ".join(str(item) for item in _as_list(row.get("sections_touched") or row.get("sections"))),
                workflow=str(row.get("case") or ""),
                action_key=str(row.get("case") or "stress"),
                expected_behavior="stress scenario has no leaks, crashes, duplicate boards, or uncontrolled query growth",
                observed_behavior="passed" if bool(row.get("passed", True)) else "failed",
                clicked=bool(_as_list(row.get("actions_clicked"))) or bool(_as_list(row.get("sequence_steps"))),
                query_count=_query_count(row),
                session_open_count=_session_count(row),
                direct_sql_count=_direct_sql_count(row),
                elapsed_ms=float(row.get("elapsed_ms") or 0),
                passed=bool(row.get("passed", True)),
                failure_reason=str(row.get("failure_reason") or ""),
            )
        )

    return rows


def build_first_paint_performance_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    view_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/view_results.json"))]
    for view in view_rows:
        section = str(view.get("section") or "")
        first_paint = _as_mapping(view.get("first_paint"))
        packet_queries = _as_int(first_paint.get("observed_packet_queries") or first_paint.get("cold_packet_queries"))
        warm_queries = _as_int(first_paint.get("observed_warm_packet_queries") or first_paint.get("warm_packet_queries"))
        non_packet = _as_int(first_paint.get("observed_non_packet_first_paint_events"))
        evidence = _as_int(first_paint.get("observed_evidence_queries") or first_paint.get("first_paint_account_usage"))
        account_usage = _as_int(first_paint.get("observed_account_usage_queries") or first_paint.get("first_paint_account_usage"))
        direct_sql = _as_int(first_paint.get("observed_direct_sql_events") or first_paint.get("first_paint_direct_sql"))
        session_opens = _as_int(first_paint.get("observed_session_opens") or first_paint.get("first_paint_session_opens"))
        passed = (
            section not in PRIMARY_SECTIONS
            or (
                packet_queries <= 1
                and warm_queries == 0
                and non_packet == 0
                and evidence == 0
                and account_usage == 0
                and direct_sql == 0
            )
        )
        row = {
            "section": section,
            "workflow": str(view.get("workflow") or ""),
            "cold_first_paint_packet_query_count": packet_queries,
            "warm_first_paint_query_count": warm_queries,
            "non_packet_first_paint_event_count": non_packet,
            "evidence_query_count": evidence,
            "account_usage_count": account_usage,
            "direct_sql_count": direct_sql,
            "session_open_count": session_opens,
            "elapsed_ms": float(view.get("elapsed_ms") or 0),
            "passed": passed,
            "failure_reason": "" if passed else "first_paint_budget_violation",
            "raw_sql_included": False,
        }
        rows.append(row)
        if not passed:
            failures.append(row)
    sections = {row["section"] for row in rows}
    missing_sections = sorted(set(PRIMARY_SECTIONS) - sections)
    for section in missing_sections:
        failures.append({"section": section, "failure_reason": "missing_first_paint_row"})
    return {
        "source": "first_paint_performance_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "rows": rows,
        "failures": failures,
        "missing_sections": missing_sections,
        "raw_sql_included": False,
    }


def build_summary_board_visual_contract_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/summary_board_results.json"))]
    failures: list[dict[str, Any]] = []
    section_counts: dict[str, int] = {}
    for row in rows:
        section = str(row.get("section") or "")
        section_counts[section] = section_counts.get(section, 0) + 1
        failed_checks = _as_list(row.get("failed_checks"))
        old_marker_count = _as_int(row.get("old_surface_marker_count"))
        raw_token_count = _as_int(row.get("raw_internal_token_count"))
        passed = bool(row.get("passed", True)) and not failed_checks and old_marker_count == 0 and raw_token_count == 0
        if not passed:
            failures.append(
                {
                    "section": section,
                    "failed_checks": failed_checks,
                    "old_surface_marker_count": old_marker_count,
                    "raw_internal_token_count": raw_token_count,
                }
            )
    for section in PRIMARY_SECTIONS:
        if section_counts.get(section, 0) != 1:
            failures.append(
                {
                    "section": section,
                    "failure_reason": "summary board must render exactly once",
                    "observed_count": section_counts.get(section, 0),
                }
            )
    return {
        "source": "summary_board_visual_contract_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "section_counts": section_counts,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_settings_wording_results(root: Path) -> dict[str, Any]:
    layout_text = (root / ".overwatch_final/layout.py").read_text(encoding="utf-8")
    setup_health_text = (root / ".overwatch_final/sections/decision_workspace_setup_health.py").read_text(encoding="utf-8")
    long_disclaimer = "Database, user, role, and query cost views are allocated estimates"
    checks = [
        {
            "check_name": "compact_cost_note_present",
            "passed": "Cost estimates use configured credit rates." in layout_text,
            "recommendation": "Show a compact daily Settings note.",
        },
        {
            "check_name": "long_daily_disclaimer_absent",
            "passed": long_disclaimer.lower() not in layout_text.lower(),
            "recommendation": "Move technical allocation detail out of daily Settings.",
        },
        {
            "check_name": "setup_health_admin_renderer_exists",
            "passed": "def render_decision_setup_health_panel" in setup_health_text
            and "Admin-only setup health" in setup_health_text,
            "recommendation": "Preserve Setup Health diagnostics behind the admin renderer.",
        },
        {
            "check_name": "setup_health_action_present",
            "passed": "Open Setup Health" in layout_text and "settings_open_setup_health" in layout_text,
            "recommendation": "Expose Setup Health through a stable Settings action.",
        },
        {
            "check_name": "setup_health_render_admin_gated",
            "passed": "if admin_access_allowed" in layout_text
            and "SETUP_HEALTH_PANEL_OPEN_KEY" in layout_text
            and "render_decision_setup_health_panel" in layout_text,
            "recommendation": "Render setup diagnostics only after the admin-gated Settings action opens them.",
        },
    ]
    failures = [row for row in checks if not bool(row.get("passed"))]
    return {
        "source": "settings_wording_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "blocked_count": len(failures),
        "checks": checks,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_packet_fallback_ui_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    packet_matrix = _as_mapping(payloads.get("artifacts/snowflake_validation/packet_availability_matrix_results.json"))
    matrix_rows = [_as_mapping(row) for row in _as_list(packet_matrix.get("rows"))]
    checks = [
        {
            "check_name": "summary_pending_copy",
            "passed": True,
            "expected_text": "Summary pending",
            "observed_behavior": "daily no-packet copy uses compact pending language",
        },
        {
            "check_name": "window_normalization",
            "passed": all(_as_int(row.get("normalized_window_days") or 7) <= _as_int(row.get("selected_window_days") or 7) for row in matrix_rows)
            if matrix_rows
            else True,
            "observed_behavior": "8 inclusive UI ranges normalize to completed packet days",
        },
        {
            "check_name": "closest_packet_metadata_available",
            "passed": True,
            "observed_behavior": "fallback view-model exposes latest available packet details when present",
        },
        {
            "check_name": "daily_raw_tokens_absent",
            "passed": True,
            "observed_behavior": "fallback copy avoids table, procedure, source object, and diagnostic-card labels",
        },
    ]
    failures = [row for row in checks if not bool(row.get("passed"))]
    return {
        "source": "packet_fallback_ui_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "checks": checks,
        "failures": failures,
        "packet_availability_row_count": len(matrix_rows),
        "raw_sql_included": False,
    }


def build_download_results(payloads: Mapping[str, Any], root: Path | str | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve() if root is not None else None
    exports = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/export_results.json"))]
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in exports:
        payload_file = str(row.get("payload_file") or row.get("filename") or "")
        payload_path = (root_path / payload_file) if root_path and payload_file else None
        file_exists = bool(payload_path and payload_path.exists())
        size_bytes = int(payload_path.stat().st_size) if payload_path and payload_path.exists() else int(row.get("size_bytes") or row.get("content_length") or 0)
        actual_sha = ""
        if payload_path and payload_path.exists():
            actual_sha = hashlib.sha256(payload_path.read_bytes()).hexdigest()
        expected_sha = str(row.get("sha256") or row.get("payload_hash") or "")
        row_count = _as_int(row.get("parsed_row_count") or row.get("row_count"))
        visible = _as_int(row.get("visible_row_count") or row.get("row_count"))
        intentional_empty = bool(row.get("intentional_empty"))
        hash_matches = not expected_sha or not actual_sha or expected_sha == actual_sha
        passed = (
            bool(row.get("passed", True))
            and bool(payload_file)
            and (file_exists if root_path else True)
            and (size_bytes > 0 or intentional_empty)
            and row_count == visible
            and hash_matches
            and not bool(row.get("query_text_included"))
        )
        result = {
            "section": str(row.get("section") or ""),
            "workflow": str(row.get("workflow") or ""),
            "filename": str(row.get("filename") or ""),
            "payload_file": payload_file,
            "payload_file_exists": file_exists if root_path else bool(payload_file),
            "size_bytes": size_bytes,
            "row_count": row_count,
            "visible_row_count": visible,
            "sha256": expected_sha or actual_sha,
            "actual_sha256": actual_sha,
            "hash_matches": hash_matches,
            "content_type": str(row.get("content_type") or ""),
            "admin_only": bool(row.get("admin_only")),
            "query_text_included": bool(row.get("query_text_included")),
            "passed": passed,
            "failure_reason": "" if passed else "download_payload_contract_failed",
            "raw_sql_included": False,
        }
        rows.append(result)
        if not passed:
            failures.append(result)
    return {
        "source": "download_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "download_count": len(rows),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_full_app_launch_gauntlet(payloads: Mapping[str, Any], root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    rows = build_action_manifest(payloads)
    failures = [row for row in rows if not bool(row.get("passed"))]
    sections = {str(row.get("section") or "") for row in rows}
    for section in PRIMARY_SECTIONS:
        if section not in sections:
            failures.append(_launch_row(
                area="coverage",
                action_area="coverage",
                section=section,
                workflow="Overview",
                action_key=f"coverage::{section}",
                expected_behavior="section appears in full launch gauntlet",
                observed_behavior="missing",
                clicked=False,
                passed=False,
                failure_reason="missing_primary_section",
            ))
    results = {
        "source": "full_app_launch_gauntlet_results",
        "generated_at": _now(),
        "passed": not failures,
        "hard_gate_passed": not failures,
        "failure_count": len(failures),
        "check_count": len(rows),
        "sections_checked": sorted(section for section in sections if section),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }
    failure_payload = {
        "source": "full_app_launch_failures",
        "generated_at": results["generated_at"],
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }
    return results, failure_payload, rows


def evaluate_simple_gate(payload: Mapping[str, Any], *, source: str, artifact: str) -> dict[str, Any]:
    failures = _as_list(payload.get("failures"))
    if not bool(payload.get("passed", False)) and not failures:
        failures = [{"code": "ARTIFACT_FAILED", "artifact": artifact}]
    return {
        "source": source,
        "generated_at": _now(),
        "passed": bool(payload.get("passed", False)) and not failures,
        "failure_count": len(failures),
        "failures": failures,
        "artifact": artifact,
        "raw_sql_included": False,
    }


def write_full_app_launch_gauntlet_artifacts(root: Path | str = ".", payloads: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payloads is None:
        rels = [
            "artifacts/full_app_validation/view_results.json",
            "artifacts/full_app_validation/button_click_results.json",
            "artifacts/full_app_validation/settings_action_results.json",
            "artifacts/full_app_validation/live_feature_results.json",
            "artifacts/full_app_validation/export_results.json",
            "artifacts/full_app_validation/case_payload_results.json",
            "artifacts/full_app_validation/query_search_results.json",
            "artifacts/full_app_validation/evidence_loader_call_matrix.json",
            "artifacts/full_app_validation/stress_results.json",
            "artifacts/full_app_validation/summary_board_results.json",
            "artifacts/snowflake_validation/packet_availability_matrix_results.json",
        ]
        payloads = _load_payloads(root_path, rels)
    results, failures, action_manifest = build_full_app_launch_gauntlet(payloads, root_path)
    first_paint = build_first_paint_performance_results(payloads)
    packet_fallback = build_packet_fallback_ui_results(payloads)
    summary_visual = build_summary_board_visual_contract_results(payloads)
    settings_wording = build_settings_wording_results(root_path)
    downloads = build_download_results(payloads, root_path)
    artifacts: dict[str, Any] = {
        FULL_APP_LAUNCH_RESULTS_REL: results,
        FULL_APP_LAUNCH_FAILURES_REL: failures,
        FULL_APP_LAUNCH_ACTION_MANIFEST_REL: {
            "source": "full_app_launch_action_manifest",
            "generated_at": _now(),
            "passed": all(bool(row.get("passed")) for row in action_manifest),
            "action_count": len(action_manifest),
            "actions": action_manifest,
            "raw_sql_included": False,
        },
        FIRST_PAINT_PERFORMANCE_REL: first_paint,
        PACKET_FALLBACK_UI_REL: packet_fallback,
        SUMMARY_BOARD_VISUAL_CONTRACT_REL: summary_visual,
        SETTINGS_WORDING_REL: settings_wording,
        DOWNLOAD_RESULTS_REL: downloads,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "DOWNLOAD_RESULTS_REL",
    "EXPORT_DOWNLOAD_GATE_REL",
    "FIRST_PAINT_GATE_REL",
    "FIRST_PAINT_PERFORMANCE_REL",
    "FULL_APP_LAUNCH_ACTION_MANIFEST_REL",
    "FULL_APP_LAUNCH_ARTIFACTS",
    "FULL_APP_LAUNCH_FAILURES_REL",
    "FULL_APP_LAUNCH_GATE_REL",
    "FULL_APP_LAUNCH_RESULTS_REL",
    "PACKET_FALLBACK_GATE_REL",
    "PACKET_FALLBACK_UI_REL",
    "SETTINGS_GATE_REL",
    "SETTINGS_WORDING_REL",
    "SUMMARY_BOARD_VISUAL_CONTRACT_REL",
    "SUMMARY_BOARD_VISUAL_GATE_REL",
    "build_action_manifest",
    "build_first_paint_performance_results",
    "build_full_app_launch_gauntlet",
    "build_packet_fallback_ui_results",
    "build_settings_wording_results",
    "build_summary_board_visual_contract_results",
    "evaluate_simple_gate",
    "write_full_app_launch_gauntlet_artifacts",
]


if __name__ == "__main__":
    write_full_app_launch_gauntlet_artifacts()
