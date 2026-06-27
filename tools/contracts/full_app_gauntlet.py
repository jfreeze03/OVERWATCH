"""Hard product gate for the Decision Workspace runtime validation bundle.

The gauntlet runs the runtime harness plus supporting cleanup/static scans, then
evaluates the produced artifacts. A present JSON file is never enough: any
failed sub-artifact, leak counter, stale artifact, route/query leak, or static
scan block fails the gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.contracts.cleanup_inventory import write_cleanup_artifacts
from tools.contracts.direct_sql_contract import direct_sql_scan_artifact, scan_direct_sql_usage
from tools.contracts.full_app_runtime_validation import write_full_app_validation_artifacts
from tools.contracts.full_app_validation_inventory import write_full_app_contract_inventory_artifacts
from tools.contracts.session_open_contract import scan_session_open_usage, session_open_scan_artifact
from tools.contracts.sql_performance_lint import lint_sql_files


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
    "artifacts/full_app_validation/session_direct_sql_results.json",
    "artifacts/full_app_validation/forbidden_ui_token_scan.json",
    "artifacts/full_app_validation/forbidden_source_token_scan.json",
    "artifacts/full_app_validation/forbidden_daily_ui_scan.json",
    "artifacts/full_app_validation/forbidden_export_scan.json",
    "artifacts/full_app_validation/gauntlet_results.json",
    "artifacts/full_app_validation/gauntlet_failures.json",
    "artifacts/full_app_validation/artifact_manifest.json",
    "artifacts/full_app_inventory/artifact_manifest.json",
    "artifacts/cleanup/cleanup_summary.json",
    "artifacts/cleanup/route_state_inventory.json",
    "artifacts/cleanup/sql_object_inventory.json",
    "artifacts/cleanup/artifact_manifest.json",
    "artifacts/direct_sql_static_scan.json",
    "artifacts/session_open_static_scan.json",
    "artifacts/sql_performance_lint_findings.json",
    "artifacts/query_search_proof.json",
}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _scan_files(root: Path) -> tuple[list[Path], list[Path]]:
    python_files = sorted((root / ".overwatch_final").rglob("*.py"))
    sql_files = [
        *sorted((root / "snowflake" / "mart_setup").glob("*.sql")),
        root / "snowflake" / "OVERWATCH_MART_SETUP.sql",
    ]
    return python_files, sql_files


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

    return {
        "artifacts/direct_sql_static_scan.json": direct_artifact,
        "artifacts/session_open_static_scan.json": session_artifact,
        "artifacts/sql_performance_lint_findings.json": sql_findings,
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


def evaluate_full_app_gauntlet(
    payloads: Mapping[str, Any],
    *,
    missing_artifacts: Iterable[str] = (),
    manifest_missing_artifacts: Iterable[str] = (),
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
        "checked_artifact_count": len(payloads),
        "required_artifact_count": len(REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS),
        "failure_count": len(failures),
        "failures": failures,
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


def write_full_app_gauntlet_artifacts(root: Path | str = ".") -> dict[str, Any]:
    """Run the full app gauntlet and raise if any hard product gate fails."""

    root_path = Path(root).resolve()
    cleanup_artifacts = write_cleanup_artifacts(root_path)
    inventory_artifacts = write_full_app_contract_inventory_artifacts(root_path)
    validation_artifacts = write_full_app_validation_artifacts(root_path)
    static_artifacts = write_static_contract_artifacts(root_path)
    artifacts = {
        **cleanup_artifacts,
        **inventory_artifacts,
        **validation_artifacts,
        **static_artifacts,
    }
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
