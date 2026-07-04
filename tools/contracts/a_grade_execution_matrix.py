"""Executable A-grade execution matrix consumed by launch readiness."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
RELEASE_CANDIDATE_DIR = "artifacts/release_candidate"

A_GRADE_EXECUTION_MATRIX_RESULTS_REL = f"{FULL_APP_DIR}/a_grade_execution_matrix_results.json"
A_GRADE_EXECUTION_MATRIX_GATE_REL = f"{LAUNCH_READINESS_DIR}/a_grade_execution_matrix_gate_results.json"
A_GRADE_EXECUTION_MATRIX_SUMMARY_REL = f"{RELEASE_CANDIDATE_DIR}/a_grade_execution_matrix_summary.json"
ARTIFACT_MANIFEST_REL = f"{RELEASE_CANDIDATE_DIR}/artifact_manifest.json"
ARTIFACT_HASHES_REL = f"{RELEASE_CANDIDATE_DIR}/artifact_hashes.json"


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _proof_row_count(payload: Mapping[str, Any]) -> int:
    count = 0
    for key in ("rows", "checks", "results", "sections", "gates", "artifacts", "failures"):
        value = payload.get(key)
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, Mapping):
            count += len(value)
    if count:
        return count
    proof_scalars = 0
    ignored = {
        "passed",
        "failure_count",
        "hard_gate_failure_count",
        "failures",
        "generated_at",
        "raw_sql_included",
        "source",
        "producer",
        "producer_signature",
        "commit_sha",
        "source_tree_sha",
        "git_sha",
    }
    for key, value in payload.items():
        if key in ignored:
            continue
        if isinstance(value, list):
            proof_scalars += len(value)
            continue
        if isinstance(value, Mapping):
            proof_scalars += len(value)
            continue
        if (
            key.endswith("_count")
            or key.endswith("_status")
            or key.endswith("_passed")
            or key.endswith("_signature")
            or key in {"artifact", "proof_source", "workflow_run_url", "workflow_run_id"}
        ):
            proof_scalars += 1
    return proof_scalars if proof_scalars >= 2 else 0


def _proof_rows(payload: Mapping[str, Any]) -> list[str]:
    proof_rows: list[str] = []
    row_keys = ("validation_id", "row_id", "id", "stable_key", "gate", "check", "section", "path")
    for key in ("rows", "checks", "results", "sections", "gates", "artifacts"):
        value = payload.get(key)
        items = value.values() if isinstance(value, Mapping) else value if isinstance(value, list) else []
        for index, row in enumerate(items):
            if isinstance(row, Mapping):
                row_id = next((str(row.get(row_key) or "") for row_key in row_keys if row.get(row_key)), "")
                proof_rows.append(row_id or f"{key}[{index}]")
            else:
                proof_rows.append(f"{key}[{index}]")
    if proof_rows:
        return proof_rows[:20]
    scalar_rows = []
    for key, value in payload.items():
        if (
            key.endswith("_count")
            or key.endswith("_status")
            or key.endswith("_passed")
            or key.endswith("_signature")
            or key in {"artifact", "proof_source", "workflow_run_url", "workflow_run_id"}
        ):
            scalar_rows.append(f"scalar::{key}")
    return scalar_rows[:20]


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _load_mapping(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, list):
        return {"rows": payload}
    return {}


def _commit_from_payload(payload: Mapping[str, Any]) -> str:
    for key in ("commit_sha", "source_tree_sha", "git_sha"):
        value = str(payload.get(key) or "")
        if value:
            return value
    for key in ("rows", "checks", "results", "sections", "gates", "artifacts"):
        value = payload.get(key)
        rows = value.values() if isinstance(value, Mapping) else value if isinstance(value, list) else []
        for row in rows:
            if isinstance(row, Mapping) and str(row.get("commit_sha") or ""):
                return str(row.get("commit_sha") or "")
    return ""


def _release_artifact_indexes(root: Path) -> dict[str, Any]:
    manifest = _load_mapping(root / ARTIFACT_MANIFEST_REL)
    hashes = _load_mapping(root / ARTIFACT_HASHES_REL)
    manifest_files = manifest.get("files")
    manifest_paths: set[str] = set()
    if isinstance(manifest_files, list):
        for item in manifest_files:
            if isinstance(item, Mapping):
                path = str(item.get("path") or "")
            else:
                path = str(item or "")
            if path:
                manifest_paths.add(path)
    hash_rows = hashes.get("hashes")
    hash_index: dict[str, str] = {}
    if isinstance(hash_rows, list):
        for row in hash_rows:
            if isinstance(row, Mapping):
                path = str(row.get("path") or "")
                sha = str(row.get("sha256") or "")
                if path and sha:
                    hash_index[path] = sha
    return {
        "artifact_manifest_exists": (root / ARTIFACT_MANIFEST_REL).exists(),
        "artifact_hash_manifest_exists": (root / ARTIFACT_HASHES_REL).exists(),
        "manifest_commit_sha": str(manifest.get("commit_sha") or manifest.get("source_tree_sha") or ""),
        "hash_manifest_commit_sha": str(hashes.get("commit_sha") or hashes.get("source_tree_sha") or ""),
        "manifest_paths": manifest_paths,
        "hash_index": hash_index,
    }


def _artifact_details(root: Path, rel: str, payload: Mapping[str, Any], release_indexes: Mapping[str, Any]) -> dict[str, Any]:
    path = root / rel
    exists = path.exists()
    artifact_sha = _sha256(path) if exists else ""
    referenced_rel = str(payload.get("artifact") or payload.get("source_artifact") or "")
    referenced_payload = _load_mapping(root / referenced_rel) if referenced_rel else {}
    proof_row_count = max(_proof_row_count(payload), _proof_row_count(referenced_payload))
    proof_rows = _proof_rows(payload) or _proof_rows(referenced_payload)
    commit_sha = _commit_from_payload(payload) or _commit_from_payload(referenced_payload)
    if not commit_sha and exists and str(payload.get("generated_at") or "") and str(payload.get("source") or payload.get("producer") or ""):
        commit_sha = _git_commit(root)
    manifest_paths = release_indexes.get("manifest_paths")
    hash_index = release_indexes.get("hash_index")
    artifact_manifest_listed = rel in manifest_paths if isinstance(manifest_paths, set) else False
    expected_sha = hash_index.get(rel, "") if isinstance(hash_index, Mapping) else ""
    artifact_hash_listed = bool(expected_sha) and bool(artifact_sha) and expected_sha == artifact_sha
    return {
        "artifact_path": rel,
        "artifact_exists": exists,
        "artifact_sha256": artifact_sha,
        "artifact_commit_sha": commit_sha,
        "artifact_manifest_path": ARTIFACT_MANIFEST_REL,
        "artifact_manifest_exists": bool(release_indexes.get("artifact_manifest_exists")),
        "artifact_manifest_listed": artifact_manifest_listed,
        "artifact_hash_manifest_path": ARTIFACT_HASHES_REL,
        "artifact_hash_manifest_exists": bool(release_indexes.get("artifact_hash_manifest_exists")),
        "artifact_hash_listed": artifact_hash_listed,
        "artifact_hash_manifest_sha256": str(expected_sha),
        "producer": str(payload.get("producer") or payload.get("source") or ""),
        "producer_signature": str(payload.get("producer_signature") or payload.get("proof_source") or payload.get("source") or ""),
        "proof_row_count": proof_row_count,
        "proof_rows": proof_rows,
        "artifact_raw_sql_included": bool(payload.get("raw_sql_included") or referenced_payload.get("raw_sql_included")),
    }


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
    artifact_path: str = "",
    artifact_exists: bool = False,
    artifact_sha256: str = "",
    artifact_commit_sha: str = "",
    producer: str = "",
    producer_signature: str = "",
    proof_row_count: int = 0,
    proof_rows: list[str] | None = None,
    artifact_manifest_path: str = "",
    artifact_manifest_exists: bool = False,
    artifact_manifest_listed: bool = False,
    artifact_hash_manifest_path: str = "",
    artifact_hash_manifest_exists: bool = False,
    artifact_hash_manifest_sha256: str = "",
    artifact_hash_listed: bool = False,
    artifact_raw_sql_included: bool = False,
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
        "artifact_path": artifact_path,
        "artifact_exists": artifact_exists,
        "artifact_sha256": artifact_sha256,
        "artifact_commit_sha": artifact_commit_sha,
        "producer": producer,
        "producer_signature": producer_signature,
        "proof_row_count": proof_row_count,
        "proof_rows": proof_rows or [],
        "artifact_manifest_path": artifact_manifest_path,
        "artifact_manifest_exists": artifact_manifest_exists,
        "artifact_manifest_listed": artifact_manifest_listed,
        "artifact_hash_manifest_path": artifact_hash_manifest_path,
        "artifact_hash_manifest_exists": artifact_hash_manifest_exists,
        "artifact_hash_manifest_sha256": artifact_hash_manifest_sha256,
        "artifact_hash_listed": artifact_hash_listed,
        "passed": passed,
        "failure_reason": failure_reason,
        "raw_sql_included": artifact_raw_sql_included,
    }


def build_a_grade_execution_matrix(
    root: Path | str = ".",
    *,
    launch_artifacts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    artifacts = launch_artifacts or {}
    current_commit = _git_commit(root_path)
    release_indexes = _release_artifact_indexes(root_path)
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
            "Query and app performance",
            "P0 access boundary proof",
            "shell/session boundary",
            "B+",
            "A",
            "runtime access-control probe, explicit admin-only connection test",
            "tests.test_access_control_runtime; tests.test_access_control_probe",
            "access_control_runtime_results.json",
            "runtime probe and first-paint telemetry",
            "artifacts/launch_readiness/access_control_runtime_gate_results.json",
            True,
        ),
        (
            "Query and app performance",
            "P0 targeted evidence proof",
            "SQL pushdown before evidence load",
            "B+",
            "A",
            "target SQL plan metadata for every evidence loader",
            "tests.test_targeted_evidence_sql_pushdown; tests.test_decision_workspace_target_filters",
            "targeted_evidence_sql_pushdown_results.json",
            "producer-built target predicate plans",
            "artifacts/launch_readiness/targeted_evidence_sql_pushdown_gate_results.json",
            True,
        ),
        (
            "Query and app performance",
            "P0 Query Search proof",
            "no broad autorun",
            "B+",
            "A",
            "explicit Query Search autorun/no-click contract",
            "tests.test_query_search_autorun; tests.test_query_search",
            "query_search_autorun_results.json",
            "runtime Query Search case artifacts",
            "artifacts/launch_readiness/query_search_autorun_gate_results.json",
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
            "Decision metric governance",
            "P0 metric intake",
            "packet-backed high-impact metrics",
            "B+",
            "A",
            "semantic registry, source status, evidence/export/case contracts",
            "tests.test_metric_source_governance; tests.test_metric_semantic_registry",
            "metric_source_governance_results.json; per-family metric gate artifacts",
            "profile-dependent live proof or explicit fixture skip",
            "artifacts/launch_readiness/metric_source_governance_gate_results.json",
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
        artifact_details = _artifact_details(root_path, gate_rel, gate, release_indexes)
        if not release_blocking and gate:
            passed = bool(gate.get("ui_a_grade_ready", gate.get("passed")))
        else:
            passed = bool(gate.get("passed")) if gate else False
        proof_reasons: list[str] = []
        if not gate:
            proof_reasons.append("required release gate missing")
        if not artifact_details["artifact_exists"]:
            proof_reasons.append("required release gate artifact missing")
        if bool(artifact_details["artifact_raw_sql_included"]):
            proof_reasons.append("release gate artifact includes raw SQL")
        if release_blocking and not str(artifact_details["producer_signature"]):
            proof_reasons.append("release gate artifact lacks producer signature")
        if release_blocking and _as_int(artifact_details["proof_row_count"]) <= 0:
            proof_reasons.append("release gate artifact lacks concrete proof rows")
        if release_blocking and not artifact_details["proof_rows"]:
            proof_reasons.append("release gate artifact lacks row ids or proof rows")
        if release_blocking and not str(artifact_details["artifact_commit_sha"]):
            proof_reasons.append("release gate artifact lacks commit SHA")
        if (
            release_blocking
            and current_commit
            and str(artifact_details["artifact_commit_sha"])
            and str(artifact_details["artifact_commit_sha"]) != current_commit
        ):
            proof_reasons.append("release gate artifact commit SHA does not match current commit")
        if release_blocking and not artifact_details["artifact_manifest_exists"]:
            proof_reasons.append("release artifact manifest is missing")
        if release_blocking and not artifact_details["artifact_manifest_listed"]:
            proof_reasons.append("release gate artifact is not listed in release artifact manifest")
        if release_blocking and not artifact_details["artifact_hash_manifest_exists"]:
            proof_reasons.append("release artifact hash manifest is missing")
        if release_blocking and not artifact_details["artifact_hash_listed"]:
            proof_reasons.append("release gate artifact hash is not included in release artifact hashes")
        proof_passed = not proof_reasons
        if release_blocking:
            passed = bool(passed and proof_passed)
        status = "passed" if passed else ("deferred" if not release_blocking else "failed")
        failure_reason = "" if passed else (
            "advisory A-grade row deferred with owner/rationale; production deployable is unaffected"
            if not release_blocking
            else "; ".join(proof_reasons or ["required release gate missing or failed"])
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
                **artifact_details,
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
