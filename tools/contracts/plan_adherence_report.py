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
RECENT_CHANGE_WINDOW = "HEAD~30..HEAD"


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
            "artifacts/full_app_validation/source_runtime_event_ledger_results.json",
            "artifacts/launch_readiness/source_runtime_event_ledger_gate_results.json",
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


def _git_changed_files(root: Path) -> set[str]:
    """Return files changed in the release-hardening window and worktree."""
    commands = (
        ["git", "diff", "--name-only", RECENT_CHANGE_WINDOW],
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "show", "--name-only", "--format=", "HEAD"],
    )
    changed: set[str] = set()
    for command in commands:
        try:
            proc = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False, timeout=10)
        except OSError:
            continue
        if proc.returncode != 0:
            continue
        changed.update(
            line.strip().replace("\\", "/")
            for line in proc.stdout.splitlines()
            if line.strip()
        )
    return changed


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


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value or 0)))
    except (TypeError, ValueError):
        return 0


def _artifact_status(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    payload = _load_json(root, rel) if path.exists() else {}
    if "passed" in payload:
        passed = bool(payload.get("passed"))
    elif "all_passed" in payload:
        passed = bool(payload.get("all_passed"))
    else:
        passed = path.exists()
    failure_count = _as_int(payload.get("failure_count") or payload.get("hard_gate_failure_count")) if payload else 0
    return {
        "path": rel,
        "exists": path.exists(),
        "passed": bool(path.exists() and passed and failure_count == 0 and not bool(payload.get("raw_sql_included"))),
        "failure_count": failure_count,
        "raw_sql_included": bool(payload.get("raw_sql_included")) if payload else False,
    }


def _command_evidence(root: Path) -> list[dict[str, Any]]:
    """Return sanitized command evidence from release artifacts when present."""
    commands: list[dict[str, Any]] = []
    for rel in (
        "artifacts/release_candidate/release_notes.json",
        "artifacts/release_candidate/release_candidate_summary.json",
        "artifacts/launch_readiness/launch_readiness_summary.json",
    ):
        payload = _load_json(root, rel)
        values = payload.get("validation_commands") if isinstance(payload, Mapping) else None
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            command = str(value or "")
            if not command:
                continue
            if any(token in command.lower() for token in ("token-file-path", "password", "secret", "raw sql", ".sql")):
                command = "[redacted command with sensitive argument]"
            commands.append(
                {
                    "artifact_path": rel,
                    "command_index": index,
                    "command": command[:300],
                    "raw_sql_included": False,
                }
            )
    return commands


def _phase_row(
    root: Path,
    spec: PhaseSpec,
    commit_sha: str,
    changed_files: set[str],
    command_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_rows = [_artifact_status(root, rel) for rel in spec.artifacts]
    blockers = [
        f"{row['path']}: missing or failed"
        for row in artifact_rows
        if not bool(row.get("passed"))
    ]
    planned_files = [item.replace("\\", "/") for item in spec.files_changed]
    planned_tests = [item.replace("\\", "/") for item in spec.tests_added_or_updated]
    actual_changed_files = [item for item in planned_files if item in changed_files]
    actual_tests = [item for item in planned_tests if item in changed_files]
    deviations = list(spec.deviations)
    if planned_files and not actual_changed_files:
        deviations.append("No planned implementation files changed in the release evidence window.")
    if planned_tests and not actual_tests:
        deviations.append("No planned tests changed in the release evidence window.")
    if any(not bool(row.get("exists")) for row in artifact_rows):
        deviations.append("One or more planned artifacts were not produced.")
    if any(bool(row.get("exists")) and not bool(row.get("passed")) for row in artifact_rows):
        deviations.append("One or more planned artifacts were produced but failed.")
    passed = not blockers
    return {
        "phase_id": spec.phase_id,
        "phase_name": spec.phase_name,
        "planned_status": "required",
        "actual_status": "implemented" if passed else "blocked",
        "files_changed": list(spec.files_changed),
        "tests_added_or_updated": list(spec.tests_added_or_updated),
        "artifacts_produced": artifact_rows,
        "actual_changed_files": actual_changed_files,
        "actual_tests_added_or_updated": actual_tests,
        "actual_artifacts_produced": [row for row in artifact_rows if bool(row.get("exists"))],
        "commands_run": command_evidence,
        "deviations": deviations,
        "unrecorded_deviation_count": 0,
        "blockers": blockers,
        "acceptance_criteria_met": passed,
        "hard_gate_left_failing": bool(blockers),
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
    changed_files = _git_changed_files(root_path)
    command_evidence = _command_evidence(root_path)
    rows = [_phase_row(root_path, spec, commit_sha, changed_files, command_evidence) for spec in PHASES]
    failures = [row for row in rows if not bool(row.get("passed"))]
    summary = _load_json(root_path, f"{RELEASE_CANDIDATE_DIR}/release_candidate_summary.json")
    summary_failures: list[dict[str, Any]] = []
    if failures and bool(summary.get("production_deployable")):
        summary_failures.append(
            {
                "phase_id": "release_candidate_summary",
                "phase_name": "Release candidate summary",
                "blockers": ["production_deployable=true while plan adherence has failing phases"],
                "passed": False,
                "raw_sql_included": False,
            }
        )
    if failures and bool(summary.get("a_grade_ready")):
        summary_failures.append(
            {
                "phase_id": "release_candidate_summary",
                "phase_name": "Release candidate summary",
                "blockers": ["a_grade_ready=true while plan adherence has failing phases"],
                "passed": False,
                "raw_sql_included": False,
            }
        )
    if _as_int(summary.get("unrecorded_deviation_count")) > 0:
        summary_failures.append(
            {
                "phase_id": "release_candidate_summary",
                "phase_name": "Release candidate summary",
                "blockers": ["release summary reports unrecorded deviations"],
                "passed": False,
                "raw_sql_included": False,
            }
        )
    all_failures = [*failures, *summary_failures]
    return {
        "source": "plan_adherence_report",
        "producer": PRODUCER,
        "producer_signature": _producer_signature(),
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha,
        "passed": not all_failures,
        "failure_count": len(all_failures),
        "phase_count": len(rows),
        "deviation_count": sum(len(row.get("deviations") or []) for row in rows),
        "command_evidence_count": len(command_evidence),
        "actual_changed_file_count": len(changed_files),
        "production_deployable_blocked_by_plan": bool(summary_failures),
        "rows": rows,
        "failures": all_failures,
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
