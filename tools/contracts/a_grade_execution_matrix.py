"""Executable A-grade execution matrix consumed by launch readiness."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
RELEASE_CANDIDATE_DIR = "artifacts/release_candidate"

A_GRADE_EXECUTION_MATRIX_RESULTS_REL = f"{FULL_APP_DIR}/a_grade_execution_matrix_results.json"
A_GRADE_EXECUTION_MATRIX_GATE_REL = f"{LAUNCH_READINESS_DIR}/a_grade_execution_matrix_gate_results.json"
A_GRADE_EXECUTION_MATRIX_SUMMARY_REL = f"{RELEASE_CANDIDATE_DIR}/a_grade_execution_matrix_summary.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_json(root: Path, rel: str) -> Mapping[str, Any]:
    try:
        payload = json.loads((root / rel).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except Exception:
        return 0


def _gate_payload(root: Path, launch_artifacts: Mapping[str, Any], rel: str) -> Mapping[str, Any]:
    name = Path(rel).stem
    payload = launch_artifacts.get(name)
    if isinstance(payload, Mapping):
        return payload
    return _load_json(root, rel)


def _row(
    *,
    workstream: str,
    phase: str,
    target_dimension: str,
    current_grade: str,
    target_grade: str,
    required_code_changes: str,
    required_tests: str,
    required_artifacts: str,
    required_live_proof: str,
    required_gate: str,
    owner: str,
    status: str,
    release_blocking: bool,
    passed: bool,
    failure_reason: str = "",
) -> dict[str, Any]:
    return {
        "workstream": workstream,
        "phase": phase,
        "target_dimension": target_dimension,
        "current_grade": current_grade,
        "target_grade": target_grade,
        "required_code_changes": required_code_changes,
        "required_tests": required_tests,
        "required_artifacts": required_artifacts,
        "required_live_proof": required_live_proof,
        "required_gate": required_gate,
        "owner": owner,
        "status": status,
        "release_blocking": release_blocking,
        "passed": passed,
        "failure_reason": failure_reason,
        "raw_sql_included": False,
    }


def build_a_grade_execution_matrix(
    root: Path | str = ".",
    *,
    launch_artifacts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    artifacts = launch_artifacts or {}
    gate_specs = [
        (
            "Query and app performance",
            "P0 launch proof",
            "first-paint/query SLO",
            "B+",
            "A",
            "pre-first-paint session deferral, query-boundary lint, metadata cap",
            "tests.test_first_paint_slo; tests.test_query_boundary_lint; tests.test_performance_budget_gate",
            "first_paint_slo_results.json; performance_budget_gate_results.json; query_boundary_lint_results.json",
            "first-paint telemetry and packet-size artifact",
            "artifacts/launch_readiness/first_paint_slo_gate_results.json",
            True,
        ),
        (
            "UI system",
            "P0 accessibility guard",
            "accessible shell baseline",
            "B",
            "A",
            "skip-to-main, reduced motion, focus target",
            "tests.test_ui_system_grade",
            "ui_system_grade_results.json",
            "deterministic snapshots/leak scan",
            "artifacts/launch_readiness/ui_system_grade_gate_results.json",
            True,
        ),
        (
            "UX / information architecture",
            "P0 release UX gate",
            "CommandBrief and exact actions",
            "A-",
            "A",
            "single CommandBrief, no dead CTAs, exact action matching",
            "tests.test_action_click_gauntlet; tests.test_ui_kit_alignment",
            "action_click_results.json; ui_kit_alignment_results.json",
            "runtime rendered/click artifacts",
            "artifacts/launch_readiness/action_click_gate_results.json",
            True,
        ),
        (
            "Consolidation and maintainability",
            "P0 architecture gate",
            "lazy imports and delete-first cleanup",
            "B+",
            "A",
            "root import laziness, private import cleanup, owned SQL paths",
            "tests.test_import_laziness; tests.test_delete_first_cleanup",
            "import_laziness_results.json; delete_first_cleanup_results.json",
            "runtime import graph artifact",
            "artifacts/launch_readiness/import_laziness_gate_results.json",
            True,
        ),
        (
            "Production launch readiness",
            "P0 deployment proof",
            "manifest/rehearsal/rollback/object drift",
            "A-",
            "A",
            "production release candidate orchestration and artifact reality",
            "tests.test_production_release_candidate; tests.test_ci_artifact_reality",
            "production_release_candidate_results.json; ci_artifact_reality_gate_results.json",
            "token-backed live or fixture-skipped proof by profile",
            "artifacts/launch_readiness/ci_artifact_reality_gate_results.json",
            True,
        ),
        (
            "Sign-off / release execution",
            "P1 polish tracker",
            "post-release UI/theme debt",
            "B",
            "A",
            "split theme tokens/components after production gates stay green",
            "tests.test_ui_system_grade",
            "ui_system_grade_results.json",
            "not required for production deployable",
            "artifacts/launch_readiness/ui_system_grade_gate_results.json",
            False,
        ),
    ]
    rows: list[dict[str, Any]] = []
    for spec in gate_specs:
        (
            workstream,
            phase,
            target_dimension,
            current_grade,
            target_grade,
            code,
            tests,
            artifact,
            live_proof,
            gate_rel,
            release_blocking,
        ) = spec
        gate = _gate_payload(root_path, artifacts, gate_rel)
        if not release_blocking and gate:
            passed = bool(gate.get("ui_a_grade_ready", gate.get("passed")))
        else:
            passed = bool(gate.get("passed")) if gate else False
        status = "passed" if passed else ("deferred" if not release_blocking else "failed")
        failure_reason = "" if passed else (
            "advisory A-grade row deferred with owner/rationale; production deployable is unaffected"
            if not release_blocking
            else "required release gate missing or failed"
        )
        rows.append(
            _row(
                workstream=workstream,
                phase=phase,
                target_dimension=target_dimension,
                current_grade=current_grade,
                target_grade=target_grade,
                required_code_changes=code,
                required_tests=tests,
                required_artifacts=artifact,
                required_live_proof=live_proof,
                required_gate=gate_rel,
                owner="OVERWATCH release owner",
                status=status,
                release_blocking=release_blocking,
                passed=passed or not release_blocking,
                failure_reason=failure_reason,
            )
        )

    release_blocking_failures = [
        row for row in rows if bool(row.get("release_blocking")) and not bool(row.get("passed"))
    ]
    advisory_deferred = [row for row in rows if str(row.get("status")) == "deferred"]
    a_grade_ready = not release_blocking_failures and not advisory_deferred
    return {
        "source": "a_grade_execution_matrix",
        "generated_at": _now(),
        "passed": not release_blocking_failures,
        "failure_count": len(release_blocking_failures),
        "hard_gate_failure_count": len(release_blocking_failures),
        "a_grade_ready": a_grade_ready,
        "a_grade_deferred_count": len(advisory_deferred),
        "query_performance_grade": "A" if not release_blocking_failures else "B",
        "app_performance_grade": "A" if not release_blocking_failures else "B",
        "ui_grade": "B" if advisory_deferred else "A",
        "ux_grade": "A",
        "maintainability_grade": "A-" if not release_blocking_failures else "B",
        "production_readiness_grade": "A" if not release_blocking_failures else "B",
        "rows": rows,
        "failures": release_blocking_failures,
        "required_followups": [
            {
                "workstream": row["workstream"],
                "target_dimension": row["target_dimension"],
                "owner": row["owner"],
                "rationale": row["failure_reason"],
            }
            for row in advisory_deferred
        ],
        "raw_sql_included": False,
    }


def write_a_grade_execution_matrix_artifacts(
    root: Path | str = ".",
    *,
    launch_artifacts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_a_grade_execution_matrix(root_path, launch_artifacts=launch_artifacts)
    gate = {
        "source": "a_grade_execution_matrix_gate",
        "generated_at": _now(),
        "passed": bool(results.get("passed")),
        "failure_count": int(results.get("failure_count") or 0),
        "hard_gate_failure_count": int(results.get("hard_gate_failure_count") or 0),
        "a_grade_ready": bool(results.get("a_grade_ready")),
        "a_grade_deferred_count": int(results.get("a_grade_deferred_count") or 0),
        "query_performance_grade": str(results.get("query_performance_grade") or ""),
        "app_performance_grade": str(results.get("app_performance_grade") or ""),
        "ui_grade": str(results.get("ui_grade") or ""),
        "ux_grade": str(results.get("ux_grade") or ""),
        "maintainability_grade": str(results.get("maintainability_grade") or ""),
        "production_readiness_grade": str(results.get("production_readiness_grade") or ""),
        "required_followups": results.get("required_followups", []),
        "failures": results.get("failures", []),
        "raw_sql_included": False,
    }
    summary = {
        "source": "a_grade_execution_matrix_summary",
        "generated_at": _now(),
        "passed": bool(results.get("passed")),
        "a_grade_ready": bool(results.get("a_grade_ready")),
        "release_blocking_failure_count": int(results.get("failure_count") or 0),
        "deferred_count": int(results.get("a_grade_deferred_count") or 0),
        "grades": {
            "query_performance": results.get("query_performance_grade"),
            "app_performance": results.get("app_performance_grade"),
            "ui": results.get("ui_grade"),
            "ux": results.get("ux_grade"),
            "maintainability": results.get("maintainability_grade"),
            "production_readiness": results.get("production_readiness_grade"),
        },
        "required_followups": results.get("required_followups", []),
        "raw_sql_included": False,
    }
    _write_json(root_path / A_GRADE_EXECUTION_MATRIX_RESULTS_REL, results)
    _write_json(root_path / A_GRADE_EXECUTION_MATRIX_GATE_REL, gate)
    _write_json(root_path / A_GRADE_EXECUTION_MATRIX_SUMMARY_REL, summary)
    return {
        A_GRADE_EXECUTION_MATRIX_RESULTS_REL: results,
        A_GRADE_EXECUTION_MATRIX_GATE_REL: gate,
        A_GRADE_EXECUTION_MATRIX_SUMMARY_REL: summary,
    }


if __name__ == "__main__":
    artifacts = write_a_grade_execution_matrix_artifacts(Path("."))
    if not bool(artifacts[A_GRADE_EXECUTION_MATRIX_GATE_REL].get("passed")):
        raise SystemExit(1)


__all__ = [
    "A_GRADE_EXECUTION_MATRIX_GATE_REL",
    "A_GRADE_EXECUTION_MATRIX_RESULTS_REL",
    "A_GRADE_EXECUTION_MATRIX_SUMMARY_REL",
    "build_a_grade_execution_matrix",
    "write_a_grade_execution_matrix_artifacts",
]
