"""Plan adherence report for the release-proof hardening branch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


RELEASE_CANDIDATE_DIR = "artifacts/release_candidate"
PLAN_ADHERENCE_REPORT_REL = f"{RELEASE_CANDIDATE_DIR}/plan_adherence_report.json"
PRODUCER = "plan_adherence_report"


@dataclass(frozen=True)
class PhaseSpec:
    phase_id: str
    phase_name: str
    files_changed: tuple[str, ...]
    tests_added_or_updated: tuple[str, ...]
    artifacts: tuple[str, ...]
    deviations: tuple[str, ...] = ()


PHASES: tuple[PhaseSpec, ...] = (
    PhaseSpec(
        "phase_01",
        "Release evidence registry",
        (
            "tools/contracts/release_evidence_registry.py",
            "tools/contracts/launch_readiness.py",
            "tools/contracts/production_release_candidate.py",
            "tools/contracts/a_grade_execution_matrix.py",
            "tools/contracts/artifact_verifier.py",
        ),
        ("tests/test_release_evidence_registry.py",),
        (
            "artifacts/full_app_validation/release_evidence_registry_results.json",
            "artifacts/launch_readiness/release_evidence_registry_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_02",
        "Runtime event ledger",
        (
            "tools/contracts/runtime_event_ledger.py",
            "tools/contracts/full_app_runtime_validation.py",
            "tools/contracts/first_paint_slo.py",
            "tools/contracts/performance_budget_gate.py",
        ),
        ("tests/test_runtime_event_ledger.py", "tests/test_first_paint_slo.py", "tests/test_performance_budget_gate.py"),
        (
            "artifacts/full_app_validation/runtime_event_ledger_results.json",
            "artifacts/launch_readiness/runtime_event_ledger_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_03",
        "Access-control adversarial proof",
        ("tools/contracts/access_control_runtime.py", ".overwatch_final/access_control.py", ".overwatch_final/shell.py"),
        ("tests/test_access_control_probe.py", "tests/test_app_entry_smoke.py"),
        (
            "artifacts/full_app_validation/access_control_runtime_results.json",
            "artifacts/launch_readiness/access_control_runtime_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_04",
        "Shared query-boundary vocabulary",
        (".overwatch_final/performance.py", ".overwatch_final/utils/query.py", "tools/contracts/query_boundary_lint.py"),
        ("tests/test_query_boundary_lint.py",),
        (
            "artifacts/full_app_validation/query_boundary_lint_results.json",
            "artifacts/launch_readiness/query_boundary_lint_gate_results.json",
        ),
        ("Mechanical adaptation: boundary vocabulary is enforced through existing performance/query wrappers and lint rather than a duplicate query_boundaries.py module.",),
    ),
    PhaseSpec(
        "phase_05",
        "Query-boundary taint lint",
        ("tools/contracts/query_boundary_lint.py", ".github/workflows/validate.yml"),
        ("tests/test_query_boundary_lint.py",),
        (
            "artifacts/full_app_validation/query_boundary_lint_results.json",
            "artifacts/launch_readiness/query_boundary_lint_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_06",
        "Target SQL pushdown at real loader boundaries",
        (
            ".overwatch_final/sections/decision_workspace_target_filters.py",
            "tools/contracts/targeted_evidence_sql_pushdown.py",
        ),
        ("tests/test_decision_workspace_target_filters.py", "tests/test_full_app_release_sweep.py"),
        (
            "artifacts/full_app_validation/targeted_evidence_sql_pushdown_results.json",
            "artifacts/launch_readiness/targeted_evidence_sql_pushdown_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_07",
        "Cost Overview packet-only",
        ("tools/contracts/performance_budget_gate.py", ".overwatch_final/sections/cost_contract.py"),
        ("tests/test_cost_contract_evidence_load_monitoring_loader.py", "tests/test_performance_budget_gate.py"),
        ("artifacts/launch_readiness/cost_overview_no_autoload_gate_results.json",),
        ("Mechanical adaptation: cost no-autoload is emitted by performance_budget_gate.py instead of a parallel cost_overview_no_autoload.py producer.",),
    ),
    PhaseSpec(
        "phase_08",
        "Query Search no-broad-autorun",
        (".overwatch_final/sections/query_search.py", "tools/contracts/query_search_autorun.py"),
        ("tests/test_query_search.py", "tests/test_performance_budget_gate.py"),
        (
            "artifacts/full_app_validation/query_search_autorun_results.json",
            "artifacts/launch_readiness/query_search_autorun_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_09",
        "Route/action replay harness",
        ("tools/contracts/route_action_replay.py",),
        ("tests/test_route_action_replay.py",),
        (
            "artifacts/full_app_validation/route_action_replay_results.json",
            "artifacts/launch_readiness/route_action_replay_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_10",
        "Export/case/render parity",
        ("tools/contracts/export_case_parity.py",),
        ("tests/test_export_case_parity.py",),
        (
            "artifacts/full_app_validation/export_case_parity_results.json",
            "artifacts/launch_readiness/export_case_parity_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_11",
        "Artifact integrity and leak safety",
        ("tools/contracts/artifact_verifier.py", "tools/contracts/production_release_candidate.py"),
        ("tests/test_artifact_verifier.py",),
        (
            "artifacts/full_app_validation/artifact_integrity_results.json",
            "artifacts/launch_readiness/artifact_integrity_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_12",
        "Release-candidate manifest ordering",
        ("tools/contracts/production_release_candidate.py", "tools/contracts/launch_readiness.py"),
        ("tests/test_production_release_candidate.py", "tests/test_ci_artifact_reality.py"),
        (
            "artifacts/release_candidate/artifact_manifest.json",
            "artifacts/release_candidate/artifact_hashes.json",
            "artifacts/release_candidate/release_candidate_summary.json",
        ),
    ),
    PhaseSpec(
        "phase_13",
        "A-grade exact-artifact backing",
        ("tools/contracts/a_grade_execution_matrix.py",),
        ("tests/test_a_grade_execution_matrix.py",),
        (
            "artifacts/full_app_validation/a_grade_execution_matrix_results.json",
            "artifacts/launch_readiness/a_grade_execution_matrix_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_14",
        "Profile-correct live validation",
        ("tools/contracts/snowflake_cli_live_validation.py", "tools/contracts/snowflake_object_drift_validation.py"),
        ("tests/test_snowflake_cli_live_validation.py", "tests/test_snowflake_object_drift_validation.py"),
        (
            "artifacts/launch_readiness/snowflake_cli_live_gate_results.json",
            "artifacts/launch_readiness/snowflake_object_drift_gate_results.json",
        ),
    ),
    PhaseSpec(
        "phase_15",
        "CI/local artifact reality",
        ("tools/contracts/ci_artifact_reality.py", ".github/workflows/validate.yml"),
        ("tests/test_ci_artifact_reality.py",),
        ("artifacts/launch_readiness/ci_artifact_reality_gate_results.json",),
    ),
    PhaseSpec(
        "phase_16",
        "Final release summary",
        ("tools/contracts/production_release_candidate.py", "tools/contracts/launch_readiness.py"),
        ("tests/test_production_release_candidate.py",),
        (
            "artifacts/release_candidate/release_candidate_summary.json",
            "artifacts/launch_readiness/launch_readiness_summary.json",
        ),
    ),
    PhaseSpec(
        "phase_17",
        "CI workflow",
        (".github/workflows/validate.yml",),
        ("tests/test_ci_artifact_reality.py",),
        ("artifacts/launch_readiness/ci_artifact_reality_gate_results.json",),
    ),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _git_commit(root: Path) -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False, timeout=10)
    except OSError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _producer_signature() -> str:
    try:
        body = Path(__file__).read_bytes()
    except OSError:
        body = PRODUCER.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _phase_signature(phase_id: str, commit_sha: str) -> str:
    return hashlib.sha256(f"{PRODUCER}|{phase_id}|{commit_sha}".encode("utf-8")).hexdigest()


def _load_json(root: Path, rel: str) -> Mapping[str, Any]:
    try:
        payload = json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {"rows": payload if isinstance(payload, list) else []}


def _artifact_status(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    payload = _load_json(root, rel) if path.exists() else {}
    if "passed" in payload:
        passed = bool(payload.get("passed"))
    elif "all_passed" in payload:
        passed = bool(payload.get("all_passed"))
    else:
        passed = path.exists()
    failure_count = int(float(str(payload.get("failure_count") or payload.get("hard_gate_failure_count") or 0))) if payload else 0
    return {
        "path": rel,
        "exists": path.exists(),
        "passed": bool(path.exists() and passed and failure_count == 0 and not bool(payload.get("raw_sql_included"))),
        "failure_count": failure_count,
        "raw_sql_included": bool(payload.get("raw_sql_included")) if payload else False,
    }


def _phase_row(root: Path, spec: PhaseSpec, commit_sha: str) -> dict[str, Any]:
    artifact_rows = [_artifact_status(root, rel) for rel in spec.artifacts]
    blockers = [
        f"{row['path']}: missing or failed"
        for row in artifact_rows
        if not bool(row.get("passed"))
    ]
    passed = not blockers
    return {
        "phase_id": spec.phase_id,
        "phase_name": spec.phase_name,
        "planned_status": "required",
        "actual_status": "implemented" if passed else "blocked",
        "files_changed": list(spec.files_changed),
        "tests_added_or_updated": list(spec.tests_added_or_updated),
        "artifacts_produced": artifact_rows,
        "deviations": list(spec.deviations),
        "blockers": blockers,
        "acceptance_criteria_met": passed,
        "passed": passed,
        "producer": PRODUCER,
        "producer_signature": _phase_signature(spec.phase_id, commit_sha),
        "provenance_origin": "producer",
        "commit_sha": commit_sha,
        "raw_sql_included": False,
    }


def build_plan_adherence_report(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = _git_commit(root_path)
    rows = [_phase_row(root_path, spec, commit_sha) for spec in PHASES]
    failures = [row for row in rows if not bool(row.get("passed"))]
    return {
        "source": "plan_adherence_report",
        "producer": PRODUCER,
        "producer_signature": _producer_signature(),
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha,
        "passed": not failures,
        "failure_count": len(failures),
        "phase_count": len(rows),
        "deviation_count": sum(len(row.get("deviations") or []) for row in rows),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_plan_adherence_report(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    report = build_plan_adherence_report(root_path)
    _write_json(root_path / PLAN_ADHERENCE_REPORT_REL, report)
    return {PLAN_ADHERENCE_REPORT_REL: report}


def main() -> int:
    artifacts = write_plan_adherence_report(Path.cwd())
    return 0 if artifacts[PLAN_ADHERENCE_REPORT_REL]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PHASES",
    "PLAN_ADHERENCE_REPORT_REL",
    "build_plan_adherence_report",
    "write_plan_adherence_report",
]
