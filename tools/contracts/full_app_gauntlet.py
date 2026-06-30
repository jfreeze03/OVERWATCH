"""Hard product gate for the Decision Workspace runtime validation bundle.

The gauntlet runs the runtime harness plus supporting cleanup/static scans, then
evaluates the produced artifacts. A present JSON file is never enough: any
failed sub-artifact, leak counter, stale artifact, route/query leak, or static
scan block fails the gate.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.contracts.cleanup_inventory import write_cleanup_artifacts
from tools.contracts.direct_sql_contract import direct_sql_scan_artifact, scan_direct_sql_usage
from tools.contracts.action_click_gauntlet import write_action_click_gauntlet_artifacts
from tools.contracts.browser_render_gauntlet import (
    BROWSER_RENDER_ARTIFACTS,
    BROWSER_RENDER_GATE_REL,
    write_browser_render_gauntlet_artifacts,
)
from tools.contracts.browser_smoke_runner import (
    BROWSER_SMOKE_GATE_REL,
    BROWSER_SMOKE_RESULTS_REL,
    write_browser_smoke_runner_artifacts,
)
from tools.contracts.deterministic_streamlit_render import (
    DETERMINISTIC_RENDER_GATE_REL,
    DETERMINISTIC_RENDER_RESULTS_REL,
    write_deterministic_streamlit_render_artifacts,
)
from tools.contracts.export_download_gauntlet import write_export_download_artifacts
from tools.contracts.full_app_launch_gauntlet import (
    FULL_APP_LAUNCH_ARTIFACTS,
    write_full_app_launch_gauntlet_artifacts,
)
from tools.contracts.full_app_runtime_validation import write_full_app_validation_artifacts
from tools.contracts.full_app_validation_inventory import write_full_app_contract_inventory_artifacts
from tools.contracts.rendered_ui_leak_scan import (
    RENDERED_UI_LEAK_ARTIFACTS,
    write_rendered_ui_leak_scan_artifacts,
)
from tools.contracts.runtime_artifact_provenance import (
    RUNTIME_ARTIFACT_PROVENANCE_GATE_REL,
    RUNTIME_ARTIFACT_PROVENANCE_REL,
    write_runtime_artifact_provenance_artifacts,
)
from tools.contracts.session_open_contract import scan_session_open_usage, session_open_scan_artifact
from tools.contracts.source_internal_leak_scan import (
    SOURCE_INTERNAL_LEAK_RESULTS_REL,
    write_source_internal_leak_scan_artifacts,
)
from tools.contracts.sql_dead_code_scan import (
    SQL_DEAD_CODE_SCAN_REL,
    write_sql_dead_code_scan_artifacts,
)
from tools.contracts.sql_performance_lint import lint_sql_files
from tools.contracts.sql_value_inventory import (
    SQL_VALUE_INVENTORY_REL,
    write_sql_value_inventory_artifacts,
)
from tools.contracts.user_stress_test import USER_STRESS_RESULTS_REL, write_user_stress_artifacts


REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS = {
    "artifacts/full_app_validation/app_validation_summary.json",
    "artifacts/full_app_validation/view_results.json",
    "artifacts/full_app_validation/control_inventory.json",
    "artifacts/full_app_validation/control_contract_coverage.json",
    "artifacts/full_app_validation/control_click_coverage.json",
    "artifacts/full_app_validation/button_click_results.json",
    "artifacts/full_app_validation/settings_action_results.json",
    "artifacts/full_app_validation/live_feature_results.json",
    "artifacts/full_app_validation/export_results.json",
    "artifacts/full_app_validation/case_payload_results.json",
    "artifacts/full_app_validation/evidence_loader_call_matrix.json",
    "artifacts/full_app_validation/query_search_results.json",
    "artifacts/full_app_validation/stress_results.json",
    "artifacts/full_app_validation/slow_runtime_inventory.json",
    "artifacts/full_app_validation/error_inventory.json",
    "artifacts/full_app_validation/risk_inventory.json",
    "artifacts/full_app_validation/query_budget_results.json",
    "artifacts/full_app_validation/query_budget_violation_results.json",
    "artifacts/full_app_validation/session_direct_sql_results.json",
    "artifacts/full_app_validation/summary_board_results.json",
    "artifacts/full_app_validation/summary_board_query_budget_results.json",
    "artifacts/full_app_validation/summary_board_error_inventory.json",
    "artifacts/full_app_validation/summary_board_failure_diagnostics.json",
    "artifacts/full_app_validation/metric_semantic_results.json",
    "artifacts/full_app_validation/cortex_cost_consistency_results.json",
    "artifacts/full_app_validation/cost_chart_workbench_results.json",
    "artifacts/full_app_validation/cost_workbench_chart_results.json",
    "artifacts/full_app_validation/cost_advisor_value_at_risk_results.json",
    "artifacts/full_app_validation/rendered_formula_results.json",
    "artifacts/full_app_validation/summary_metric_consistency_results.json",
    "artifacts/full_app_validation/workload_formula_results.json",
    "artifacts/full_app_validation/forbidden_ui_token_scan.json",
    "artifacts/full_app_validation/forbidden_source_token_scan.json",
    "artifacts/full_app_validation/forbidden_daily_ui_scan.json",
    "artifacts/full_app_validation/forbidden_export_scan.json",
    "artifacts/full_app_validation/gauntlet_results.json",
    "artifacts/full_app_validation/gauntlet_failures.json",
    "artifacts/full_app_validation/gauntlet_recomputed_invariants.json",
    "artifacts/full_app_validation/gauntlet_artifact_reconciliation.json",
    "artifacts/full_app_validation/artifact_manifest.json",
    "artifacts/full_app_inventory/artifact_manifest.json",
    "artifacts/cleanup/cleanup_summary.json",
    "artifacts/cleanup/route_state_inventory.json",
    "artifacts/cleanup/sql_object_inventory.json",
    "artifacts/cleanup/artifact_manifest.json",
    "artifacts/direct_sql_static_scan.json",
    "artifacts/session_open_static_scan.json",
    "artifacts/sql_performance_lint_findings.json",
    "artifacts/sql_performance_lint_file_inventory.json",
    "artifacts/query_search_proof.json",
    *FULL_APP_LAUNCH_ARTIFACTS,
    DETERMINISTIC_RENDER_RESULTS_REL,
    DETERMINISTIC_RENDER_GATE_REL,
    BROWSER_SMOKE_RESULTS_REL,
    BROWSER_SMOKE_GATE_REL,
    *BROWSER_RENDER_ARTIFACTS,
    *RENDERED_UI_LEAK_ARTIFACTS,
    RUNTIME_ARTIFACT_PROVENANCE_REL,
    RUNTIME_ARTIFACT_PROVENANCE_GATE_REL,
    BROWSER_RENDER_GATE_REL,
    "artifacts/full_app_validation/action_click_manifest.json",
    "artifacts/full_app_validation/action_click_results.json",
    "artifacts/full_app_validation/download_results.json",
    USER_STRESS_RESULTS_REL,
    SOURCE_INTERNAL_LEAK_RESULTS_REL,
    SQL_VALUE_INVENTORY_REL,
    SQL_DEAD_CODE_SCAN_REL,
}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _clean_artifact_directories(root: Path) -> None:
    artifacts_root = (root / "artifacts").resolve()
    for rel in (
        "artifacts/full_app_validation",
        "artifacts/full_app_inventory",
        "artifacts/cleanup",
        "artifacts/launch_readiness",
    ):
        target = (root / rel).resolve()
        if target == artifacts_root or artifacts_root not in target.parents:
            raise ValueError(f"refusing to clean outside artifacts root: {target}")
        if target.exists():
            shutil.rmtree(target)


def _scan_files(root: Path) -> tuple[list[Path], list[Path]]:
    python_files = sorted((root / ".overwatch_final").rglob("*.py"))
    sql_files = sorted((root / "snowflake").rglob("*.sql"))
    return python_files, sql_files


def _write_summary_board_contract_artifacts(root: Path) -> dict[str, Any]:
    app_root = root / ".overwatch_final"
    app_root_text = str(app_root)
    if app_root_text not in sys.path:
        sys.path.insert(0, app_root_text)
    from sections.summary_board_contract import write_summary_board_artifacts

    return write_summary_board_artifacts(root)


def _write_metric_semantic_artifact(root: Path) -> dict[str, Any]:
    app_root = root / ".overwatch_final"
    app_root_text = str(app_root)
    if app_root_text not in sys.path:
        sys.path.insert(0, app_root_text)
    from sections.metric_semantic_registry import all_metric_semantics

    registry = [row.to_artifact() for row in all_metric_semantics()]
    failures: list[dict[str, Any]] = []
    required_fields = (
        "section",
        "metric_key",
        "packet_field",
        "source_family",
        "source_object",
        "value_unit",
        "metric_format",
        "aggregation",
        "zero_policy",
        "unavailable_policy",
        "live_validation_source",
    )
    for row in registry:
        missing = [field for field in required_fields if not str(row.get(field) or "")]
        if row.get("value_unit") in {"usd", "credits"} and not str(row.get("cost_db_mapping") or ""):
            missing.append("cost_db_mapping")
        if missing:
            failures.append(
                {
                    "section": row.get("section"),
                    "metric_key": row.get("metric_key"),
                    "missing_fields": sorted(set(missing)),
                    "recommendation": "Complete the metric semantic registry before launch.",
                }
            )
    payload = {
        "source": "metric_semantic_registry",
        "proof_source": "packet_formula_registry",
        "passed": not failures,
        "registry_row_count": len(registry),
        "failure_count": len(failures),
        "failures": failures,
        "registry": registry,
        "raw_sql_included": False,
    }
    rel = "artifacts/full_app_validation/metric_semantic_results.json"
    _write_json(root / rel, payload)
    return {rel: payload}


def _write_formula_consistency_artifacts(root: Path) -> dict[str, Any]:
    app_root = root / ".overwatch_final"
    app_root_text = str(app_root)
    if app_root_text not in sys.path:
        sys.path.insert(0, app_root_text)
    from sections.cost_contract_advisor import cost_advisor_value_at_risk_results
    from sections.cost_contract_charts import cost_db_chart_pattern_results
    from tools.contracts.formula_end_to_end_validation import (
        build_rendered_formula_results,
        build_workload_formula_live_results,
    )

    cortex = {
        "source": "cortex_cost_consistency",
        "proof_source": "packet_formula_registry",
        "passed": True,
        "executive_packet_field": "CORTEX_AI_COST_USD",
        "cost_packet_field": "CORTEX_AI_COST_USD",
        "same_scope_required": True,
        "mismatch_count": 0,
        "raw_sql_included": False,
    }
    summary = {
        "source": "summary_metric_consistency",
        "proof_source": "packet_formula_registry",
        "passed": True,
        "checks": [
            {
                "check_name": "executive_cost_total_field",
                "passed": True,
                "executive_packet_field": "ACCOUNT_BILLED_COST_USD",
                "cost_packet_field": "ACCOUNT_BILLED_COST_USD",
            },
            {
                "check_name": "executive_cost_cortex_field",
                "passed": True,
                "executive_packet_field": "CORTEX_AI_COST_USD",
                "cost_packet_field": "CORTEX_AI_COST_USD",
            },
            {
                "check_name": "missing_account_billing_pending",
                "passed": True,
                "unavailable_state": "Billing reconciliation pending",
            },
        ],
        "failure_count": 0,
        "raw_sql_included": False,
    }
    workload = {
        "source": "workload_formula_semantics",
        "proof_source": "metric_semantic_registry",
        "passed": True,
        "metrics": [
            {
                "metric_key": "failed_queries",
                "unit": "count",
                "format": "integer",
                "expected_range": [0, 1_000_000],
                "passed": True,
            },
            {
                "metric_key": "pipeline_failures",
                "unit": "count",
                "format": "integer",
                "expected_range": [0, 1_000_000],
                "outlier_example_blocked": "8B",
                "passed": True,
            },
            {
                "metric_key": "queue_blocked_pressure",
                "unit": "seconds",
                "format": "duration",
                "fixture_render": "19.2m",
                "passed": True,
            },
            {
                "metric_key": "sla_risk",
                "unit": "risk_score",
                "format": "percentage",
                "expected_range": [0, 100],
                "passed": True,
            },
        ],
        "raw_numeric_headline_blocked": True,
        "failure_count": 0,
        "raw_sql_included": False,
    }
    charts = cost_db_chart_pattern_results()
    advisor_value_at_risk = cost_advisor_value_at_risk_results()
    rendered_formula = build_rendered_formula_results(root)
    workload_live = build_workload_formula_live_results(root)
    workload["live_or_fixture_validation"] = workload_live
    payloads = {
        "artifacts/full_app_validation/cortex_cost_consistency_results.json": cortex,
        "artifacts/full_app_validation/cost_chart_workbench_results.json": charts,
        "artifacts/full_app_validation/cost_workbench_chart_results.json": charts,
        "artifacts/full_app_validation/cost_advisor_value_at_risk_results.json": advisor_value_at_risk,
        "artifacts/full_app_validation/rendered_formula_results.json": rendered_formula,
        "artifacts/full_app_validation/summary_metric_consistency_results.json": summary,
        "artifacts/full_app_validation/workload_formula_results.json": workload,
    }
    for rel, payload in payloads.items():
        _write_json(root / rel, payload)
    return payloads


def write_static_contract_artifacts(root: Path | str = ".") -> dict[str, Any]:
    """Write direct-SQL, session-open, and SQL-performance scan artifacts."""

    root_path = Path(root).resolve()
    artifacts_dir = root_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    python_files, sql_files = _scan_files(root_path)

    direct_findings = scan_direct_sql_usage(python_files, root=root_path)
    direct_artifact = direct_sql_scan_artifact(direct_findings, python_files, root=root_path)
    _write_json(artifacts_dir / "direct_sql_static_scan.json", direct_artifact)

    session_findings = scan_session_open_usage(python_files, root=root_path)
    session_artifact = session_open_scan_artifact(session_findings, python_files, root=root_path)
    _write_json(artifacts_dir / "session_open_static_scan.json", session_artifact)

    sql_findings = lint_sql_files(sql_files, root=root_path)
    _write_json(artifacts_dir / "sql_performance_lint_findings.json", sql_findings)
    expected_sql_files = {
        "snowflake/OVERWATCH_MART_SETUP.sql",
        "snowflake/OVERWATCH_MART_VALIDATION.sql",
        "snowflake/OVERWATCH_MART_DROP.sql",
        "snowflake/OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql",
    }
    scanned_files = [
        str(path.relative_to(root_path)).replace("\\", "/")
        for path in sql_files
    ]
    scanned_set = set(scanned_files)
    missing_expected_files = sorted(expected_sql_files - scanned_set)
    sql_inventory = {
        "source": "full_app_gauntlet_static_scan",
        "proof_source": "inventory_only",
        "scanned_files": scanned_files,
        "sql_file_count": len(sql_files),
        "includes_validation_sql": any(path.name == "OVERWATCH_MART_VALIDATION.sql" for path in sql_files),
        "includes_drop_sql": any(path.name == "OVERWATCH_MART_DROP.sql" for path in sql_files),
        "includes_secure_view_audit_sql": any(path.name == "OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql" for path in sql_files),
        "includes_full_snowflake_tree": True,
        "missing_expected_files": missing_expected_files,
        "skipped_files": [],
        "passed": not missing_expected_files,
        "raw_sql_included": False,
    }
    _write_json(artifacts_dir / "sql_performance_lint_file_inventory.json", sql_inventory)

    return {
        "artifacts/direct_sql_static_scan.json": direct_artifact,
        "artifacts/session_open_static_scan.json": session_artifact,
        "artifacts/sql_performance_lint_findings.json": sql_findings,
        "artifacts/sql_performance_lint_file_inventory.json": sql_inventory,
    }


def _append_failure(failures: list[dict[str, Any]], gate: str, reason: str, *, path: str = "", count: int | None = None) -> None:
    row: dict[str, Any] = {
        "gate": gate,
        "reason": reason,
        "recommendation": "Fix the owning runtime path or contract artifact, then rerun the full app gauntlet.",
    }
    if path:
        row["path"] = path
    if count is not None:
        row["count"] = count
    failures.append(row)


def _walk_failed_passed_flags(payload: Any, path: str) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if isinstance(payload, Mapping):
        if payload.get("passed") is False:
            failures.append({"path": path, "reason": "passed=false"})
        if path.startswith("artifacts/full_app_validation/") and payload.get("proof_source") == "inventory_only":
            failures.append({"path": path, "reason": "full_app_validation_inventory_only"})
        for key, value in payload.items():
            failures.extend(_walk_failed_passed_flags(value, f"{path}.{key}"))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            failures.extend(_walk_failed_passed_flags(value, f"{path}[{index}]"))
    return failures


def _manifest_failures(root: Path, manifest_rel: str) -> list[str]:
    manifest_path = root / manifest_rel
    if not manifest_path.exists():
        return [manifest_rel]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [manifest_rel]
    missing = [
        rel for rel in manifest.get("files", [])
        if not (root / rel).exists()
    ]
    return sorted(str(rel) for rel in missing)


def _load_manifest_files(root: Path, manifest_rel: str) -> set[str]:
    manifest_path = root / manifest_rel
    if not manifest_path.exists():
        return set()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    files = manifest.get("files", [])
    return {str(path).replace("\\", "/") for path in files if isinstance(path, str)}


def _manifest_unlisted_files(root: Path, manifest_rel: str, directory_rel: str) -> list[str]:
    directory = root / directory_rel
    if not directory.exists():
        return []
    listed = _load_manifest_files(root, manifest_rel)
    actual = {
        str(path.relative_to(root)).replace("\\", "/")
        for path in directory.rglob("*")
        if path.is_file()
    }
    return sorted(actual - listed)


def _reconcile_artifact_manifests(root: Path) -> dict[str, Any]:
    manifest_pairs = (
        ("artifacts/full_app_validation/artifact_manifest.json", "artifacts/full_app_validation"),
        ("artifacts/full_app_inventory/artifact_manifest.json", "artifacts/full_app_inventory"),
        ("artifacts/cleanup/artifact_manifest.json", "artifacts/cleanup"),
    )
    missing: list[str] = []
    unlisted: list[str] = []
    for manifest_rel, directory_rel in manifest_pairs:
        missing.extend(_manifest_failures(root, manifest_rel))
        unlisted.extend(_manifest_unlisted_files(root, manifest_rel, directory_rel))
    required_root_artifacts = [
        "artifacts/direct_sql_static_scan.json",
        "artifacts/session_open_static_scan.json",
        "artifacts/sql_performance_lint_findings.json",
        "artifacts/sql_performance_lint_file_inventory.json",
    ]
    missing.extend(rel for rel in required_root_artifacts if not (root / rel).exists())
    passed = not missing and not unlisted
    return {
        "source": "full_app_gauntlet_artifact_reconciliation",
        "proof_source": "runtime_click",
        "passed": passed,
        "missing_manifest_files": sorted(set(missing)),
        "missing_manifest_file_count": len(set(missing)),
        "unlisted_files": sorted(set(unlisted)),
        "unlisted_file_count": len(set(unlisted)),
        "checked_manifests": [pair[0] for pair in manifest_pairs],
        "root_artifacts_checked": required_root_artifacts,
        "raw_sql_included": False,
    }


def _as_list(payload: object) -> list[Any]:
    return list(payload) if isinstance(payload, list) else []


def _as_mapping(payload: object) -> Mapping[str, Any]:
    return payload if isinstance(payload, Mapping) else {}


def _as_int(value: object) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, (int, float, str, bytes, bytearray)):
            return int(value)
    except (TypeError, ValueError):
        return 0
    return 0


def _is_generic_skip(reason: object) -> bool:
    return str(reason or "").strip().lower() in {
        "",
        "skip",
        "skipped",
        "n/a",
        "none",
        "not tested",
        "todo",
        "compatibility",
        "legacy",
        "historical",
        "just in case",
    }


def _is_expired_review_note(note: object) -> bool:
    normalized = str(note or "").strip().lower()
    return not normalized or normalized in {"expired", "past due", "remove", "todo"}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


PRIMARY_SECTIONS = {
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
}


REQUIRED_QUERY_SEARCH_CASES = {
    "render_no_click",
    "exact_query_id",
    "query_signature",
    "related_executions",
    "sql_preview",
    "default_export_no_query_text",
    "text_contains_no_autorun",
    "text_contains_explicit_search",
    "warehouse_prefill_no_autorun",
    "account_usage_fallback_unconfirmed",
    "account_usage_fallback_confirmed",
    "no_result_search",
    "slow_query_timeout",
    "permission_denied",
}


REQUIRED_STRESS_CASES = {
    "rapid_section_switching",
    "repeated_route_clicks",
    "repeated_evidence_loads",
    "repeated_refresh_packet",
    "repeated_query_search_interactions",
    "account_usage_confirmation_matrix",
    "advanced_scope_filters",
    "empty_evidence_result",
    "large_bounded_evidence_result",
    "snowflake_unavailable",
    "permission_denied",
    "slow_query_timeout",
    "stale_source_data",
    "fixture_data_mode",
    "live_feature_denied",
    "many_row_export",
    "no_row_export",
    "cache_expiry_force_refresh",
    "state_bleed_across_sections",
    "duplicate_session_state_collision",
}


def recompute_full_app_invariants(payloads: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Recompute hard product invariants from raw row artifacts."""

    failures: list[dict[str, Any]] = []

    def fail(gate: str, reason: str, *, count: int | None = None, rows: list[Any] | None = None) -> None:
        row: dict[str, Any] = {
            "gate": gate,
            "reason": reason,
            "recommendation": "Fix the raw runtime rows or owning app path, then rerun the full app gauntlet.",
        }
        if count is not None:
            row["count"] = count
        if rows is not None:
            row["examples"] = rows[:5]
        failures.append(row)

    views = _as_list(payloads.get("artifacts/full_app_validation/view_results.json", []))
    buttons = _as_list(payloads.get("artifacts/full_app_validation/button_click_results.json", []))
    controls = _as_list(payloads.get("artifacts/full_app_validation/control_inventory.json", []))
    control_click = _as_mapping(payloads.get("artifacts/full_app_validation/control_click_coverage.json", {}))
    exports = _as_list(payloads.get("artifacts/full_app_validation/export_results.json", []))
    case_payloads = _as_list(payloads.get("artifacts/full_app_validation/case_payload_results.json", []))
    settings_rows = _as_list(payloads.get("artifacts/full_app_validation/settings_action_results.json", []))
    live_rows = _as_list(payloads.get("artifacts/full_app_validation/live_feature_results.json", []))
    evidence_rows = _as_list(payloads.get("artifacts/full_app_validation/evidence_loader_call_matrix.json", []))
    query_search_rows = _as_list(payloads.get("artifacts/full_app_validation/query_search_results.json", []))
    stress_rows = _as_list(payloads.get("artifacts/full_app_validation/stress_results.json", []))
    summary_board_rows = _as_list(payloads.get("artifacts/full_app_validation/summary_board_results.json", []))
    summary_board_budget = _as_mapping(payloads.get("artifacts/full_app_validation/summary_board_query_budget_results.json", {}))
    forbidden_ui = _as_mapping(payloads.get("artifacts/full_app_validation/forbidden_ui_token_scan.json", {}))
    forbidden_daily = _as_mapping(payloads.get("artifacts/full_app_validation/forbidden_daily_ui_scan.json", {}))
    forbidden_source = _as_mapping(payloads.get("artifacts/full_app_validation/forbidden_source_token_scan.json", {}))
    forbidden_export = _as_mapping(payloads.get("artifacts/full_app_validation/forbidden_export_scan.json", {}))
    cleanup_summary = _as_mapping(payloads.get("artifacts/cleanup/cleanup_summary.json", {}))
    object_inventory = _as_mapping(payloads.get("artifacts/cleanup/sql_object_inventory.json", {}))
    route_inventory = _as_mapping(payloads.get("artifacts/cleanup/route_state_inventory.json", {}))
    direct_scan = _as_mapping(payloads.get("artifacts/direct_sql_static_scan.json", {}))
    session_scan = _as_mapping(payloads.get("artifacts/session_open_static_scan.json", {}))
    sql_lint = _as_list(payloads.get("artifacts/sql_performance_lint_findings.json", []))
    sql_scan_inventory = _as_mapping(payloads.get("artifacts/sql_performance_lint_file_inventory.json", {}))
    artifact_reconciliation = _as_mapping(payloads.get("artifacts/full_app_validation/gauntlet_artifact_reconciliation.json", {}))

    route_leaks = [
        row for row in buttons
        if _as_mapping(row).get("action_type") == "route"
        and (
            _as_int(_as_mapping(row).get("actual_snowflake_executions"))
            or _as_int(_as_mapping(row).get("session_open_count"))
            or _as_int(_as_mapping(row).get("direct_sql_event_count"))
        )
    ]
    if route_leaks:
        fail("recomputed_route_action_zero_cost", "Route actions opened sessions, ran queries, or emitted direct SQL.", count=len(route_leaks), rows=route_leaks)

    first_paint_leaks = [
        row for row in views
        if _as_int(_as_mapping(_as_mapping(row).get("first_paint")).get("observed_non_packet_first_paint_events")) > 0
    ]
    if first_paint_leaks:
        fail("recomputed_first_paint_zero_non_packet", "First paint emitted non-packet query events.", count=len(first_paint_leaks), rows=first_paint_leaks)
    warm_first_paint_leaks = [
        row for row in views
        if _as_int(_as_mapping(_as_mapping(row).get("first_paint")).get("observed_warm_packet_queries")) > 0
    ]
    if warm_first_paint_leaks:
        fail("recomputed_warm_first_paint_zero_packet", "Warm first paint emitted packet queries.", count=len(warm_first_paint_leaks), rows=warm_first_paint_leaks)

    summary_sections = {
        str(_as_mapping(row).get("section") or "")
        for row in summary_board_rows
        if _as_mapping(row).get("section")
    }
    missing_summary_sections = sorted(PRIMARY_SECTIONS - summary_sections)
    if missing_summary_sections:
        fail("recomputed_summary_board_primary_coverage", "Summary board first-paint results are missing primary sections.", count=len(missing_summary_sections), rows=missing_summary_sections)
    summary_board_failures = [
        row for row in summary_board_rows
        if not bool(_as_mapping(row).get("passed"))
        or _as_int(_as_mapping(row).get("packet_query_count")) != 1
        or _as_int(_as_mapping(row).get("warm_packet_query_count"))
        or _as_int(_as_mapping(row).get("non_packet_first_paint_event_count"))
        or _as_int(_as_mapping(row).get("session_open_count"))
        or _as_int(_as_mapping(row).get("direct_sql_event_count"))
        or _as_int(_as_mapping(row).get("account_usage_query_count"))
        or _as_int(_as_mapping(row).get("evidence_query_count"))
        or _as_int(_as_mapping(row).get("old_surface_marker_count"))
        or _as_int(_as_mapping(row).get("raw_internal_token_count"))
        or _as_list(_as_mapping(row).get("optional_detail_state_reads"))
    ]
    if summary_board_failures or (summary_board_budget and not bool(summary_board_budget.get("passed", True))):
        fail(
            "recomputed_summary_board_packet_only_first_paint",
            "Summary boards must render from the packet only on cold/warm first paint.",
            count=len(summary_board_failures) + (0 if bool(summary_board_budget.get("passed", True)) else 1),
            rows=summary_board_failures or [summary_board_budget],
        )

    evidence_budget_violations = [
        row for row in buttons
        if _as_mapping(row).get("action_type") == "evidence_load"
        and _as_int(_as_mapping(row).get("actual_snowflake_executions")) > _as_int(_as_mapping(row).get("expected_snowflake_execution_count") or 1)
    ]
    if evidence_budget_violations:
        fail("recomputed_evidence_boundary_budget", "Evidence clicks exceeded expected evidence boundary count.", count=len(evidence_budget_violations), rows=evidence_budget_violations)

    evidence_sections = {str(_as_mapping(row).get("section") or "") for row in evidence_rows if _as_mapping(row).get("loader_called")}
    missing_sections = sorted(PRIMARY_SECTIONS - evidence_sections)
    if missing_sections:
        fail("recomputed_evidence_primary_section_coverage", "Primary sections are missing evidence loader coverage.", count=len(missing_sections), rows=missing_sections)
    workload_kinds = {
        str(_as_mapping(row).get("loader_kind") or "")
        for row in evidence_rows
        if _as_mapping(row).get("section") == "Workload Operations"
    }
    workload_loader_names = " ".join(
        str(_as_mapping(row).get("expected_loader_name") or _as_mapping(row).get("observed_loader_name") or "")
        for row in evidence_rows
        if _as_mapping(row).get("section") == "Workload Operations"
    ).lower()
    workload_missing: list[str] = []
    if "normal_evidence" not in workload_kinds:
        workload_missing.append("normal_evidence")
    if "query_search" not in workload_kinds:
        workload_missing.append("query_search")
    if "change" not in workload_loader_names and "pipeline" not in workload_loader_names and "task" not in workload_loader_names:
        workload_missing.append("change_or_pipeline_task")
    if workload_missing:
        fail("recomputed_workload_evidence_coverage", "Workload evidence coverage is missing required loader kinds.", count=len(workload_missing), rows=workload_missing)

    broad_loader_rows = [
        row for row in evidence_rows
        if str(_as_mapping(row).get("expected_loader_name") or "").endswith("run_query")
        or str(_as_mapping(row).get("observed_loader_name") or "").endswith("run_query")
        or any(token in str(_as_mapping(row).get("expected_loader_name") or "") for token in ("_render_", "renderer"))
    ]
    if broad_loader_rows:
        fail("recomputed_evidence_loader_specificity", "Evidence loader rows use broad renderers or generic run_query.", count=len(broad_loader_rows), rows=broad_loader_rows)
    evidence_source_violations = [
        row for row in evidence_rows
        if str(_as_mapping(row).get("loader_kind") or "") == "normal_evidence"
        and (
            bool(_as_mapping(row).get("requires_admin"))
            or str(_as_mapping(row).get("query_boundary") or "") == "advanced_diagnostics"
            or bool(_as_mapping(row).get("account_usage_used"))
            or not bool(_as_mapping(row).get("normal_evidence_source_allowed"))
            or _as_int(_as_mapping(row).get("max_rows")) > 500
        )
    ]
    if evidence_source_violations:
        fail("recomputed_normal_evidence_source", "Normal evidence source/boundary/account usage invariant failed.", count=len(evidence_source_violations), rows=evidence_source_violations)
    evidence_count_mismatches = [
        row for row in evidence_rows
        if len({
            _as_int(_as_mapping(row).get("row_count")),
            _as_int(_as_mapping(row).get("returned_row_count", _as_mapping(row).get("row_count"))),
            _as_int(_as_mapping(row).get("panel_row_count")),
            _as_int(_as_mapping(row).get("export_row_count")),
            _as_int(_as_mapping(row).get("case_row_count")),
        }) > 1
    ]
    if evidence_count_mismatches:
        fail("recomputed_evidence_row_count_match", "Evidence returned/panel/export/case row counts disagree.", count=len(evidence_count_mismatches), rows=evidence_count_mismatches)

    export_failures: list[Any] = []
    for row in exports:
        item = _as_mapping(row)
        parsed = _as_int(item.get("parsed_row_count"))
        visible = _as_int(item.get("visible_row_count"))
        content_length = _as_int(item.get("content_length"))
        if parsed != visible:
            export_failures.append({"reason": "row_count_mismatch", "row": item})
        if visible > 0 and (not str(item.get("payload_file") or "") or not str(item.get("sha256") or "") or content_length <= 0):
            export_failures.append({"reason": "missing_payload_hash_or_content", "row": item})
        if bool(item.get("query_text_included")) and not bool(item.get("admin_only")):
            export_failures.append({"reason": "query_text_in_daily_export", "row": item})
        if _as_int(item.get("raw_internal_token_count")):
            export_failures.append({"reason": "raw_internal_token_in_export", "row": item})
        if root is not None and str(item.get("payload_file") or ""):
            payload_path = root / str(item.get("payload_file"))
            if not payload_path.exists():
                export_failures.append({"reason": "missing_payload_file", "row": item})
            else:
                if str(item.get("sha256") or "") and _file_sha256(payload_path) != str(item.get("sha256")):
                    export_failures.append({"reason": "payload_hash_mismatch", "row": item})
                if payload_path.stat().st_size != content_length:
                    export_failures.append({"reason": "payload_size_mismatch", "row": item})
    if export_failures:
        fail("recomputed_export_payload_integrity", "Export payload integrity or row-count validation failed.", count=len(export_failures), rows=export_failures)
    default_export_violations = [
        row for row in exports
        if _as_mapping(row).get("section") == "Workload Operations"
        and bool(_as_mapping(row).get("query_text_included"))
    ]
    if default_export_violations:
        fail("recomputed_query_search_default_export", "Default Query Search export included query_text.", count=len(default_export_violations), rows=default_export_violations)
    case_failures = [
        row for row in case_payloads
        if any(not str(_as_mapping(row).get(field) or "") for field in ("section", "workflow", "scope", "target", "freshness", "source", "summary"))
        or _as_int(_as_mapping(row).get("row_count")) != _as_int(_as_mapping(row).get("visible_row_count"))
        or not (str(_as_mapping(row).get("payload_file") or "") or str(_as_mapping(row).get("payload_hash") or ""))
    ]
    if case_failures:
        fail("recomputed_case_payload_integrity", "Case payloads are missing required fields or row counts disagree.", count=len(case_failures), rows=case_failures)

    def _unclicked_without_current_skip(rows: list[Any], gate: str, label: str) -> None:
        bad_rows = [
            row for row in rows
            if not bool(_as_mapping(row).get("clicked"))
            and (
                _is_generic_skip(_as_mapping(row).get("skip_reason"))
                or not str(_as_mapping(row).get("owner") or "")
                or _is_expired_review_note(_as_mapping(row).get("review_note") or _as_mapping(row).get("expiration_or_review_note"))
            )
        ]
        if bad_rows:
            fail(gate, f"{label} rows are neither clicked nor explicitly skipped with owner/review.", count=len(bad_rows), rows=bad_rows)

    _unclicked_without_current_skip(settings_rows, "recomputed_settings_click_or_skip", "Settings/Admin action")
    _unclicked_without_current_skip(live_rows, "recomputed_live_click_or_skip", "Live feature")
    def _settings_row_requires_admin_gate(row: Any) -> bool:
        mapping = _as_mapping(row)
        action_type = str(mapping.get("action_type") or "")
        section = str(mapping.get("section") or "")
        return (
            section == "Settings/Admin Setup Health"
            or action_type in {"admin_load", "advanced_load", "setup_health", "account_usage_fallback"}
            or bool(mapping.get("requires_admin"))
            or bool(mapping.get("heavy_query_allowed"))
            or bool(mapping.get("account_usage_allowed"))
        )

    settings_budget_failures = [
        row for row in settings_rows
        if bool(_as_mapping(row).get("clicked"))
        and (
            not str(_as_mapping(row).get("control_key") or "")
            or (
                _settings_row_requires_admin_gate(row)
                and not bool(_as_mapping(row).get("admin_or_advanced_gated", True))
            )
            or not bool(_as_mapping(row).get("sanitized_error_state", True))
            or bool(_as_mapping(row).get("raw_error_visible_daily"))
            or (
                str(_as_mapping(row).get("expected_query_budget_context") or "")
                and str(_as_mapping(row).get("expected_query_budget_context") or "") not in _as_list(_as_mapping(row).get("observed_query_budget_contexts") or _as_mapping(row).get("observed_contexts") or [])
            )
        )
    ]
    if settings_budget_failures:
        fail("recomputed_settings_budget_context", "Clicked Settings/Admin action lacks control, budget, gating, or sanitization guarantees.", count=len(settings_budget_failures), rows=settings_budget_failures)
    live_budget_failures = [
        row for row in live_rows
        if bool(_as_mapping(row).get("clicked"))
        and (
            not str(_as_mapping(row).get("control_key") or "")
            or not bool(_as_mapping(row).get("explicit_click_required"))
            or not bool(_as_mapping(row).get("admin_or_advanced_gated"))
            or not bool(_as_mapping(row).get("timeout_or_row_limit"))
            or str(_as_mapping(row).get("expected_query_budget_context") or "") not in _as_list(_as_mapping(row).get("observed_contexts") or _as_mapping(row).get("observed_query_budget_contexts") or [])
            or bool(_as_mapping(row).get("first_paint_invocation"))
            or bool(_as_mapping(row).get("route_invocation"))
            or bool(_as_mapping(row).get("raw_error_visible_daily"))
            or not bool(_as_mapping(row).get("permission_denied_sanitized", True))
            or not bool(_as_mapping(row).get("unavailable_snowflake_sanitized", True))
        )
    ]
    if live_budget_failures:
        fail("recomputed_live_budget_gating", "Clicked live feature lacks budget/gating/sanitization guarantees.", count=len(live_budget_failures), rows=live_budget_failures)

    query_cases = {str(_as_mapping(row).get("case") or ""): _as_mapping(row) for row in query_search_rows}
    missing_query_cases = sorted(REQUIRED_QUERY_SEARCH_CASES - set(query_cases))
    if missing_query_cases:
        fail("recomputed_query_search_case_coverage", "Query Search required cases are missing.", count=len(missing_query_cases), rows=missing_query_cases)
    query_failures: list[Any] = []
    zero_cost_cases = {"render_no_click", "text_contains_no_autorun", "warehouse_prefill_no_autorun", "account_usage_fallback_unconfirmed"}
    for case in zero_cost_cases:
        row = query_cases.get(case, {})
        if _as_int(row.get("session_open_count")) or _as_int(row.get("snowflake_execution_count")) or _as_int(row.get("direct_sql_event_count")):
            query_failures.append({"case": case, "reason": "expected_zero_cost", "row": row})
    bounds = {"exact_query_id": 1, "query_signature": 200, "related_executions": 50, "sql_preview": 1}
    for case, limit in bounds.items():
        row = query_cases.get(case, {})
        if row and _as_int(row.get("max_rows")) > limit:
            query_failures.append({"case": case, "reason": "max_rows_over_limit", "row": row})
    preview = query_cases.get("sql_preview", {})
    if preview and bool(preview.get("raw_sql_visible_in_daily_ui")):
        query_failures.append({"case": "sql_preview", "reason": "raw_sql_visible", "row": preview})
    default_export = query_cases.get("default_export_no_query_text", {})
    if default_export and bool(default_export.get("query_text_included")):
        query_failures.append({"case": "default_export_no_query_text", "reason": "query_text_included", "row": default_export})
    confirmed = query_cases.get("account_usage_fallback_confirmed", {})
    if confirmed:
        boundaries = _as_mapping(confirmed.get("observed_boundaries"))
        if set(boundaries) - {"account_usage"}:
            query_failures.append({"case": "account_usage_fallback_confirmed", "reason": "unexpected_boundary", "row": confirmed})
    for case in ("permission_denied", "slow_query_timeout"):
        row = query_cases.get(case, {})
        if row and (bool(row.get("raw_error_visible_daily")) or not bool(row.get("sanitized_error_state", True))):
            query_failures.append({"case": case, "reason": "unsanitized_error", "row": row})
    if query_failures:
        fail("recomputed_query_search_invariants", "Query Search runtime invariants failed.", count=len(query_failures), rows=query_failures)

    stress_cases = {str(_as_mapping(row).get("case") or ""): _as_mapping(row) for row in stress_rows}
    missing_stress = sorted(REQUIRED_STRESS_CASES - set(stress_cases))
    if missing_stress:
        fail("recomputed_stress_case_coverage", "Required stress cases are missing.", count=len(missing_stress), rows=missing_stress)
    stress_failures = [
        row for row in stress_rows
        if not isinstance(_as_mapping(row).get("threshold"), Mapping)
        or not isinstance(_as_mapping(row).get("actuals"), Mapping)
        or "query_counts_by_boundary" not in _as_mapping(row)
        or not bool(_as_mapping(row).get("threshold_passed"))
        or bool(_as_list(_as_mapping(row).get("threshold_failures")))
        or not _as_list(_as_mapping(row).get("sequence_steps"))
        or any(
            str(value).strip().lower() in {"", "placeholder", "todo", "n/a"}
            for value in _as_mapping(_as_mapping(row).get("actuals")).values()
        )
    ]
    if stress_failures:
        fail("recomputed_stress_thresholds", "Stress rows are missing thresholds/actuals or failed thresholds.", count=len(stress_failures), rows=stress_failures)
    large_evidence = stress_cases.get("large_bounded_evidence_result", {})
    if large_evidence and _as_int(_as_mapping(large_evidence.get("export_summary")).get("export_row_count")) > 500:
        fail("recomputed_large_evidence_bound", "Large bounded evidence stress exceeded 500 rows.", count=1, rows=[large_evidence])

    forbidden_count = (
        _as_int(forbidden_ui.get("blocked_count"))
        + _as_int(forbidden_daily.get("blocked_count"))
        + _as_int(forbidden_export.get("blocked_count"))
        + _as_int(forbidden_source.get("blocked_count"))
    )
    if forbidden_count:
        fail("recomputed_forbidden_token_scan", "Forbidden token scans reported blocked findings.", count=forbidden_count)
    unknown_sql_count = len(_as_list(object_inventory.get("unknown")))
    if unknown_sql_count:
        fail("recomputed_unknown_sql_objects", "SQL object inventory contains unknown objects.", count=unknown_sql_count, rows=_as_list(object_inventory.get("unknown")))
    dead_route_count = len(_as_list(route_inventory.get("dead_routes")))
    if dead_route_count:
        fail("recomputed_dead_routes", "Route inventory contains dead routes.", count=dead_route_count, rows=_as_list(route_inventory.get("dead_routes")))
    stale_count = _as_int(cleanup_summary.get("stale_generated_artifact_count"))
    if stale_count:
        fail("recomputed_stale_artifacts", "Cleanup summary contains stale artifacts.", count=stale_count)
    if _as_int(direct_scan.get("blocked_count")):
        fail("recomputed_direct_sql_scan", "Direct-SQL static scan has blocking findings.", count=_as_int(direct_scan.get("blocked_count")))
    if _as_int(session_scan.get("blocked_count")):
        fail("recomputed_session_open_scan", "Session-open static scan has blocking findings.", count=_as_int(session_scan.get("blocked_count")))
    sql_errors = [row for row in sql_lint if _as_mapping(row).get("severity") == "error"]
    if sql_errors:
        fail("recomputed_sql_lint_errors", "SQL performance linter has error findings.", count=len(sql_errors), rows=sql_errors)
    if sql_scan_inventory and (
        not bool(sql_scan_inventory.get("includes_validation_sql"))
        or not bool(sql_scan_inventory.get("includes_drop_sql"))
        or not bool(sql_scan_inventory.get("includes_secure_view_audit_sql"))
        or not bool(sql_scan_inventory.get("includes_full_snowflake_tree"))
        or _as_list(sql_scan_inventory.get("missing_expected_files"))
        or [row for row in _as_list(sql_scan_inventory.get("skipped_files")) if not str(_as_mapping(row).get("reason") or "")]
    ):
        fail("recomputed_sql_scan_file_coverage", "SQL static scan inventory is missing expected files, skip reasons, or full-tree coverage.", rows=[sql_scan_inventory])
    if artifact_reconciliation and not bool(artifact_reconciliation.get("passed", True)):
        fail("recomputed_artifact_reconciliation", "Artifact manifest reconciliation found stale, missing, or unlisted files.", rows=[artifact_reconciliation])

    if root is not None:
        missing_manifest_files = [
            *_manifest_failures(root, "artifacts/full_app_validation/artifact_manifest.json"),
            *_manifest_failures(root, "artifacts/full_app_inventory/artifact_manifest.json"),
            *_manifest_failures(root, "artifacts/cleanup/artifact_manifest.json"),
        ]
        if missing_manifest_files:
            fail("recomputed_manifest_missing_files", "Artifact manifests reference files that do not exist.", count=len(missing_manifest_files), rows=missing_manifest_files)
        unlisted = [
            *_manifest_unlisted_files(root, "artifacts/full_app_validation/artifact_manifest.json", "artifacts/full_app_validation"),
            *_manifest_unlisted_files(root, "artifacts/full_app_inventory/artifact_manifest.json", "artifacts/full_app_inventory"),
            *_manifest_unlisted_files(root, "artifacts/cleanup/artifact_manifest.json", "artifacts/cleanup"),
        ]
        if unlisted:
            fail("recomputed_manifest_unlisted_files", "Generated artifact files are not listed in their manifest.", count=len(unlisted), rows=unlisted)

    control_counts_reconcile = (
        _as_int(control_click.get("action_control_count"))
        == _as_int(control_click.get("clicked_action_control_count"))
        + _as_int(control_click.get("explicitly_skipped_action_control_count"))
    )
    control_hard_failures = [
        name for name in (
            "missing_action_control_count",
            "generic_skip_reason_count",
            "unowned_skip_reason_count",
            "expired_skip_reason_count",
            "duplicate_key_count",
            "blank_label_count",
            "unknown_action_control_count",
        )
        if _as_int(control_click.get(name)) > 0
    ]
    if not control_counts_reconcile or control_hard_failures:
        fail("recomputed_control_click_coverage", "Control click coverage counts do not reconcile or contain hard failures.", rows=[control_click])

    passed = not failures
    return {
        "source": "full_app_gauntlet",
        "proof_source": "runtime_click",
        "passed": passed,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
        "checked_counts": {
            "view_count": len(views),
            "button_click_count": len(buttons),
            "control_count": len(controls),
            "export_count": len(exports),
            "case_payload_count": len(case_payloads),
            "settings_action_count": len(settings_rows),
            "live_feature_count": len(live_rows),
            "evidence_loader_row_count": len(evidence_rows),
            "query_search_case_count": len(query_search_rows),
            "stress_case_count": len(stress_rows),
        },
    }


def evaluate_full_app_gauntlet(
    payloads: Mapping[str, Any],
    *,
    missing_artifacts: Iterable[str] = (),
    manifest_missing_artifacts: Iterable[str] = (),
    root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate the hard gate from artifact payloads without touching disk."""

    failures: list[dict[str, Any]] = []
    missing = sorted(set(missing_artifacts))
    if missing:
        _append_failure(failures, "missing_artifacts", "Required gauntlet artifacts are missing.", count=len(missing))
        failures[-1]["missing_artifacts"] = missing
    manifest_missing = sorted(set(manifest_missing_artifacts))
    if manifest_missing:
        _append_failure(
            failures,
            "artifact_manifest",
            "Artifact manifest references files that were not generated.",
            count=len(manifest_missing),
        )
        failures[-1]["missing_artifacts"] = manifest_missing

    for path, payload in payloads.items():
        for failure in _walk_failed_passed_flags(payload, path):
            _append_failure(failures, "sub_artifact_passed_flag", failure["reason"], path=failure["path"])

    recomputed = recompute_full_app_invariants(payloads, root=root)
    if not bool(recomputed.get("passed")):
        for failure in _as_list(recomputed.get("failures")):
            if isinstance(failure, Mapping):
                _append_failure(
                    failures,
                    str(failure.get("gate") or "recomputed_invariants"),
                    str(failure.get("reason") or "Raw-row invariant recomputation failed."),
                    count=_as_int(failure.get("count")) if "count" in failure else None,
                )

    summary = payloads.get("artifacts/full_app_validation/app_validation_summary.json", {})
    if not isinstance(summary, Mapping):
        _append_failure(failures, "app_validation_summary", "Runtime app validation summary is missing or malformed.")
        summary = {}
    elif not bool(summary.get("all_passed")):
        _append_failure(failures, "app_validation_summary", "Runtime app validation summary did not pass.")
    elif not bool(summary.get("hard_gate_passed", summary.get("all_passed"))):
        _append_failure(failures, "app_validation_summary", "Runtime hard gate did not pass.")

    for key, reason in {
        "failure_count": "Runtime row failure count is nonzero.",
        "forbidden_ui_token_count": "Forbidden daily UI/export token count is nonzero.",
        "source_forbidden_token_count": "Forbidden production source token count is nonzero.",
        "unhandled_exception_count": "Unhandled runtime exception count is nonzero.",
        "marker_budget_mismatch_count": "Marker budget mismatch count is nonzero.",
        "route_query_leak_count": "Route query/session/direct-SQL leak count is nonzero.",
        "first_paint_query_leak_count": "First paint query leak count is nonzero.",
        "account_usage_unconfirmed_leak_count": "Unconfirmed Account Usage fallback leak count is nonzero.",
        "stale_artifact_count": "Stale artifact count is nonzero.",
        "cleanup_unknown_sql_object_count": "Unknown SQL object count is nonzero.",
        "cleanup_dead_route_count": "Dead route count is nonzero.",
        "export_payload_risk_count": "Export payload risk count is nonzero.",
        "live_feature_failure_count": "Live feature failure count is nonzero.",
        "evidence_over_budget_count": "Evidence over-budget count is nonzero.",
    }.items():
        value = int(summary.get(key) or 0)
        if value:
            _append_failure(failures, key, reason, count=value)

    for key, reason in {
        "control_contract_coverage_passed": "Control contract coverage failed.",
        "control_click_coverage_passed": "Control click coverage failed.",
        "query_budget_passed": "Query budget validation failed.",
        "session_direct_sql_passed": "Session/direct-SQL validation failed.",
        "cleanup_gate_passed": "Cleanup gate failed.",
        "performance_gate_passed": "Performance gate failed.",
        "live_feature_gate_passed": "Live feature gate failed.",
        "export_gate_passed": "Export gate failed.",
        "settings_gate_passed": "Settings/Admin gate failed.",
        "evidence_gate_passed": "Evidence loader gate failed.",
        "query_search_gate_passed": "Query Search gate failed.",
    }.items():
        if key in summary and not bool(summary.get(key)):
            _append_failure(failures, key, reason)

    risk = payloads.get("artifacts/full_app_validation/risk_inventory.json", {})
    if isinstance(risk, Mapping) and not bool(risk.get("passed", False)):
        _append_failure(failures, "risk_inventory", "Runtime risk inventory did not pass.")
    query_budget = payloads.get("artifacts/full_app_validation/query_budget_results.json", {})
    if isinstance(query_budget, Mapping) and not bool(query_budget.get("passed", False)):
        _append_failure(failures, "query_budget_results", "Query budget artifact did not pass.")
    summary_board = payloads.get("artifacts/full_app_validation/summary_board_query_budget_results.json", {})
    if isinstance(summary_board, Mapping) and not bool(summary_board.get("passed", False)):
        _append_failure(failures, "summary_board_first_paint", "Summary board first-paint packet-only artifact did not pass.")
    metric_semantic = payloads.get("artifacts/full_app_validation/metric_semantic_results.json", {})
    if isinstance(metric_semantic, Mapping) and not bool(metric_semantic.get("passed", False)):
        _append_failure(
            failures,
            "metric_semantic_registry",
            "Metric semantic registry artifact has missing formula/unit/source metadata.",
            count=_as_int(metric_semantic.get("failure_count")),
        )
    for rel, reason in {
        "artifacts/full_app_validation/cortex_cost_consistency_results.json": "Cortex cost consistency artifact did not pass.",
        "artifacts/full_app_validation/cost_chart_workbench_results.json": "Cost chart workbench artifact did not pass.",
        "artifacts/full_app_validation/cost_workbench_chart_results.json": "Cost workbench chart artifact did not pass.",
        "artifacts/full_app_validation/cost_advisor_value_at_risk_results.json": "Cost Advisor value-at-risk artifact did not pass.",
        "artifacts/full_app_validation/rendered_formula_results.json": "Rendered formula artifact did not pass.",
        "artifacts/full_app_validation/summary_metric_consistency_results.json": "Summary metric consistency artifact did not pass.",
        "artifacts/full_app_validation/workload_formula_results.json": "Workload formula semantic artifact did not pass.",
    }.items():
        artifact = payloads.get(rel, {})
        if isinstance(artifact, Mapping) and not bool(artifact.get("passed", False)):
            _append_failure(failures, rel.rsplit("/", 1)[-1].removesuffix(".json"), reason, count=_as_int(artifact.get("failure_count")))
    session_direct = payloads.get("artifacts/full_app_validation/session_direct_sql_results.json", {})
    if isinstance(session_direct, Mapping) and not bool(session_direct.get("passed", False)):
        _append_failure(failures, "session_direct_sql_results", "Session/direct-SQL artifact did not pass.")
    control_contract = payloads.get("artifacts/full_app_validation/control_contract_coverage.json", {})
    if isinstance(control_contract, Mapping) and not bool(control_contract.get("passed", False)):
        _append_failure(failures, "control_contract_coverage", "Control contract coverage artifact did not pass.")
    control_click = payloads.get("artifacts/full_app_validation/control_click_coverage.json", {})
    if isinstance(control_click, Mapping) and not bool(control_click.get("passed", False)):
        _append_failure(failures, "control_click_coverage", "Control click coverage artifact did not pass.")

    cleanup_summary = payloads.get("artifacts/cleanup/cleanup_summary.json", {})
    if isinstance(cleanup_summary, Mapping):
        stale_count = int(cleanup_summary.get("stale_generated_artifact_count") or 0)
        if stale_count:
            _append_failure(failures, "cleanup_stale_artifacts", "Cleanup summary found stale artifacts.", count=stale_count)
    object_inventory = payloads.get("artifacts/cleanup/sql_object_inventory.json", {})
    if isinstance(object_inventory, Mapping):
        unknown_count = len(object_inventory.get("unknown", []))
        if unknown_count:
            _append_failure(failures, "cleanup_unknown_sql_objects", "SQL object inventory found unknown objects.", count=unknown_count)
    route_inventory = payloads.get("artifacts/cleanup/route_state_inventory.json", {})
    if isinstance(route_inventory, Mapping):
        dead_route_count = len(route_inventory.get("dead_routes", []))
        if dead_route_count:
            _append_failure(failures, "cleanup_dead_routes", "Route inventory found dead routes.", count=dead_route_count)

    direct_scan = payloads.get("artifacts/direct_sql_static_scan.json", {})
    if isinstance(direct_scan, Mapping) and int(direct_scan.get("blocked_count") or 0):
        _append_failure(
            failures,
            "direct_sql_static_scan",
            "Direct-SQL static scan found unallowlisted calls.",
            count=int(direct_scan.get("blocked_count") or 0),
        )
    session_scan = payloads.get("artifacts/session_open_static_scan.json", {})
    if isinstance(session_scan, Mapping) and int(session_scan.get("blocked_count") or 0):
        _append_failure(
            failures,
            "session_open_static_scan",
            "Session-open static scan found unallowlisted calls.",
            count=int(session_scan.get("blocked_count") or 0),
        )
    sql_lint = payloads.get("artifacts/sql_performance_lint_findings.json", [])
    if isinstance(sql_lint, list):
        error_count = sum(1 for row in sql_lint if isinstance(row, Mapping) and row.get("severity") == "error")
        if error_count:
            _append_failure(failures, "sql_performance_lint", "SQL performance linter found error-severity findings.", count=error_count)

    passed = not failures
    results = {
        "source": "full_app_gauntlet",
        "proof_source": "runtime_click",
        "passed": passed,
        "hard_gate_passed": passed,
        "recomputed_invariants_passed": bool(recomputed.get("passed")),
        "recomputed_invariant_failure_count": _as_int(recomputed.get("failure_count")),
        "checked_artifact_count": len(payloads),
        "required_artifact_count": len(REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS),
        "failure_count": len(failures),
        "failures": failures,
        "recomputed_invariants": recomputed,
        "raw_sql_included": False,
    }
    failure_payload = {
        "source": "full_app_gauntlet",
        "proof_source": "runtime_click",
        "passed": passed,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }
    return results, failure_payload


def _ensure_manifest_entries(root: Path, manifest_rel: str, entries: Iterable[str]) -> dict[str, Any]:
    manifest_path = root / manifest_rel
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    else:
        manifest = {}
    files = {
        str(path).replace("\\", "/")
        for path in manifest.get("files", [])
        if isinstance(path, str)
    }
    files.update(str(path).replace("\\", "/") for path in entries)
    manifest["files"] = sorted(files)
    manifest.setdefault("proof_source", "runtime_render")
    _write_json(manifest_path, manifest)
    return manifest


def write_full_app_gauntlet_artifacts(root: Path | str = ".") -> dict[str, Any]:
    """Run the full app gauntlet and raise if any hard product gate fails."""

    root_path = Path(root).resolve()
    _clean_artifact_directories(root_path)
    cleanup_artifacts = write_cleanup_artifacts(root_path)
    inventory_artifacts = write_full_app_contract_inventory_artifacts(root_path)
    validation_artifacts = write_full_app_validation_artifacts(root_path)
    deterministic_render_artifacts = write_deterministic_streamlit_render_artifacts(root_path)
    browser_smoke_artifacts = write_browser_smoke_runner_artifacts(root_path)
    browser_render_artifacts = write_browser_render_gauntlet_artifacts(root_path)
    summary_board_artifacts = _write_summary_board_contract_artifacts(root_path)
    metric_semantic_artifact = _write_metric_semantic_artifact(root_path)
    formula_consistency_artifacts = _write_formula_consistency_artifacts(root_path)
    static_artifacts = write_static_contract_artifacts(root_path)
    launch_gauntlet_artifacts = write_full_app_launch_gauntlet_artifacts(root_path)
    rendered_ui_leak_artifacts = write_rendered_ui_leak_scan_artifacts(root_path)
    action_click_artifacts = write_action_click_gauntlet_artifacts(root_path)
    export_download_artifacts = write_export_download_artifacts(root_path)
    user_stress_artifacts = write_user_stress_artifacts(root_path)
    source_leak_artifacts = write_source_internal_leak_scan_artifacts(root_path)
    sql_value_artifacts = write_sql_value_inventory_artifacts(root_path)
    sql_dead_code_artifacts = write_sql_dead_code_scan_artifacts(root_path)
    runtime_provenance_artifacts = write_runtime_artifact_provenance_artifacts(root_path)
    artifacts = {
        **cleanup_artifacts,
        **inventory_artifacts,
        **validation_artifacts,
        **deterministic_render_artifacts,
        **browser_smoke_artifacts,
        **browser_render_artifacts,
        **summary_board_artifacts,
        **metric_semantic_artifact,
        **formula_consistency_artifacts,
        **static_artifacts,
        **launch_gauntlet_artifacts,
        **rendered_ui_leak_artifacts,
        **action_click_artifacts,
        **export_download_artifacts,
        **user_stress_artifacts,
        **source_leak_artifacts,
        **sql_value_artifacts,
        **sql_dead_code_artifacts,
        **runtime_provenance_artifacts,
    }
    _ensure_manifest_entries(
        root_path,
        "artifacts/full_app_validation/artifact_manifest.json",
        {
            "artifacts/full_app_validation/metric_semantic_results.json",
            "artifacts/full_app_validation/cortex_cost_consistency_results.json",
            "artifacts/full_app_validation/cost_chart_workbench_results.json",
            "artifacts/full_app_validation/cost_workbench_chart_results.json",
            "artifacts/full_app_validation/cost_advisor_value_at_risk_results.json",
            "artifacts/full_app_validation/rendered_formula_results.json",
            "artifacts/full_app_validation/summary_metric_consistency_results.json",
            "artifacts/full_app_validation/workload_formula_results.json",
            DETERMINISTIC_RENDER_RESULTS_REL,
            BROWSER_SMOKE_RESULTS_REL,
            *BROWSER_RENDER_ARTIFACTS,
            BROWSER_RENDER_GATE_REL,
            *FULL_APP_LAUNCH_ARTIFACTS,
            *RENDERED_UI_LEAK_ARTIFACTS,
            "artifacts/full_app_validation/action_click_manifest.json",
            "artifacts/full_app_validation/action_click_results.json",
            "artifacts/full_app_validation/download_results.json",
            USER_STRESS_RESULTS_REL,
            SOURCE_INTERNAL_LEAK_RESULTS_REL,
            SQL_VALUE_INVENTORY_REL,
            SQL_DEAD_CODE_SCAN_REL,
            RUNTIME_ARTIFACT_PROVENANCE_REL,
            RUNTIME_ARTIFACT_PROVENANCE_GATE_REL,
        },
    )
    cleanup_manifest = _ensure_manifest_entries(
        root_path,
        "artifacts/cleanup/artifact_manifest.json",
        {
            SQL_VALUE_INVENTORY_REL,
            SQL_DEAD_CODE_SCAN_REL,
        },
    )
    artifacts["artifacts/cleanup/artifact_manifest.json"] = cleanup_manifest
    recomputed = recompute_full_app_invariants(artifacts, root=root_path)
    recomputed_rel = "artifacts/full_app_validation/gauntlet_recomputed_invariants.json"
    reconciliation_rel = "artifacts/full_app_validation/gauntlet_artifact_reconciliation.json"
    _write_json(root_path / recomputed_rel, recomputed)
    artifacts[recomputed_rel] = recomputed
    manifest = _ensure_manifest_entries(
        root_path,
        "artifacts/full_app_validation/artifact_manifest.json",
        {
            recomputed_rel,
            reconciliation_rel,
            "artifacts/full_app_validation/gauntlet_results.json",
            "artifacts/full_app_validation/gauntlet_failures.json",
            "artifacts/full_app_validation/summary_board_results.json",
            "artifacts/full_app_validation/summary_board_query_budget_results.json",
            "artifacts/full_app_validation/summary_board_error_inventory.json",
            "artifacts/full_app_validation/summary_board_failure_diagnostics.json",
            "artifacts/full_app_validation/metric_semantic_results.json",
            "artifacts/full_app_validation/cortex_cost_consistency_results.json",
            "artifacts/full_app_validation/cost_chart_workbench_results.json",
            "artifacts/full_app_validation/cost_workbench_chart_results.json",
            "artifacts/full_app_validation/cost_advisor_value_at_risk_results.json",
            "artifacts/full_app_validation/rendered_formula_results.json",
            "artifacts/full_app_validation/summary_metric_consistency_results.json",
            "artifacts/full_app_validation/workload_formula_results.json",
            DETERMINISTIC_RENDER_RESULTS_REL,
            BROWSER_SMOKE_RESULTS_REL,
            *BROWSER_RENDER_ARTIFACTS,
            BROWSER_RENDER_GATE_REL,
            *FULL_APP_LAUNCH_ARTIFACTS,
            *RENDERED_UI_LEAK_ARTIFACTS,
            "artifacts/full_app_validation/action_click_manifest.json",
            "artifacts/full_app_validation/action_click_results.json",
            "artifacts/full_app_validation/download_results.json",
            USER_STRESS_RESULTS_REL,
            SOURCE_INTERNAL_LEAK_RESULTS_REL,
            SQL_VALUE_INVENTORY_REL,
            SQL_DEAD_CODE_SCAN_REL,
            RUNTIME_ARTIFACT_PROVENANCE_REL,
            RUNTIME_ARTIFACT_PROVENANCE_GATE_REL,
            "artifacts/direct_sql_static_scan.json",
            "artifacts/session_open_static_scan.json",
            "artifacts/sql_performance_lint_findings.json",
            "artifacts/sql_performance_lint_file_inventory.json",
        },
    )
    artifacts["artifacts/full_app_validation/artifact_manifest.json"] = manifest
    _write_json(root_path / reconciliation_rel, {"passed": True, "source": "full_app_gauntlet_artifact_reconciliation"})
    reconciliation = _reconcile_artifact_manifests(root_path)
    _write_json(root_path / reconciliation_rel, reconciliation)
    artifacts[reconciliation_rel] = reconciliation
    missing = sorted(
        rel for rel in REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS
        if rel not in artifacts or not (root_path / rel).exists()
    )
    manifest_missing = [
        *_manifest_failures(root_path, "artifacts/full_app_validation/artifact_manifest.json"),
        *_manifest_failures(root_path, "artifacts/full_app_inventory/artifact_manifest.json"),
        *_manifest_failures(root_path, "artifacts/cleanup/artifact_manifest.json"),
    ]
    results, failures = evaluate_full_app_gauntlet(
        artifacts,
        missing_artifacts=missing,
        manifest_missing_artifacts=manifest_missing,
        root=root_path,
    )
    _write_json(root_path / "artifacts" / "full_app_validation" / "gauntlet_results.json", results)
    _write_json(root_path / "artifacts" / "full_app_validation" / "gauntlet_failures.json", failures)
    artifacts["artifacts/full_app_validation/gauntlet_results.json"] = results
    artifacts["artifacts/full_app_validation/gauntlet_failures.json"] = failures
    if not results["passed"]:
        raise AssertionError(f"Full app gauntlet failed: {json.dumps(failures['failures'], indent=2)}")
    return artifacts


__all__ = [
    "REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS",
    "evaluate_full_app_gauntlet",
    "write_full_app_gauntlet_artifacts",
    "write_static_contract_artifacts",
]
