"""Production release-candidate orchestrator.

This is the one-command local/CI runner for deployment rehearsal proof. It
executes the release producers in order, writes a compact phase result, and
returns non-zero when any hard gate fails. It never serializes token paths,
token contents, temp SQL paths, or SQL bodies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tools.contracts.app_entry_smoke import APP_ENTRY_SMOKE_GATE_REL, write_app_entry_smoke_artifacts
from tools.contracts.a_grade_execution_matrix import (
    A_GRADE_EXECUTION_MATRIX_GATE_REL,
    A_GRADE_EXECUTION_MATRIX_SUMMARY_REL,
)
from tools.contracts.artifact_verifier import (
    ARTIFACT_INTEGRITY_GATE_REL,
    write_artifact_integrity_artifacts,
)
from tools.contracts.export_case_parity import EXPORT_CASE_PARITY_GATE_REL
from tools.contracts.release_evidence_registry import RELEASE_EVIDENCE_REGISTRY_GATE_REL
from tools.contracts.route_action_replay import ROUTE_ACTION_REPLAY_GATE_REL
from tools.contracts.runtime_event_ledger import RUNTIME_EVENT_LEDGER_GATE_REL
from tools.contracts.ci_artifact_reality import (
    CI_ARTIFACT_REALITY_GATE_REL,
    CI_ARTIFACT_REALITY_RESULTS_REL,
    evaluate_ci_artifact_reality_gate,
    write_local_artifact_proof,
)
from tools.contracts.full_app_release_sweep import (
    FULL_APP_RELEASE_SWEEP_GATE_REL,
    write_full_app_release_sweep_artifacts,
)
from tools.contracts.import_laziness import IMPORT_LAZINESS_GATE_REL, write_import_laziness_artifacts
from tools.contracts.post_deploy_smoke import POST_DEPLOY_SMOKE_GATE_REL, write_post_deploy_smoke_artifacts
from tools.contracts.plan_adherence_report import PLAN_ADHERENCE_REPORT_REL, write_plan_adherence_report
from tools.contracts.production_deployment_manifest import (
    PRODUCTION_DEPLOYMENT_MANIFEST_GATE_REL,
    write_production_deployment_manifest_artifacts,
)
from tools.contracts.production_deployment_readiness import (
    PRODUCTION_DEPLOYMENT_READINESS_GATE_REL,
    write_production_deployment_readiness_artifacts,
)
from tools.contracts.rollback_readiness import ROLLBACK_READINESS_GATE_REL, write_rollback_readiness_artifacts
from tools.contracts.snowflake_cli_live_validation import (
    CLI_LAUNCH_GATE_REL,
    CLI_PRODUCTION_REHEARSAL_GATE_REL,
    CLI_TEMP_FILE_HYGIENE_GATE_REL,
    DEFAULT_VALIDATION_DATABASE,
    DEFAULT_VALIDATION_SCHEMA,
    SnowflakeCliValidationOptions,
    write_snowflake_cli_live_validation_artifacts,
)
from tools.contracts.snowflake_object_drift_validation import (
    SNOWFLAKE_OBJECT_DRIFT_GATE_REL,
    write_snowflake_object_drift_validation_artifacts,
)


RELEASE_CANDIDATE_DIR = "artifacts/release_candidate"

PRODUCTION_RELEASE_CANDIDATE_RESULTS_REL = (
    f"{RELEASE_CANDIDATE_DIR}/production_release_candidate_results.json"
)
PRODUCTION_RELEASE_CANDIDATE_FAILURES_REL = (
    f"{RELEASE_CANDIDATE_DIR}/production_release_candidate_failures.json"
)
PRODUCTION_RELEASE_CANDIDATE_GATE_REL = "artifacts/launch_readiness/production_release_candidate_gate_results.json"
RELEASE_GATE_MATRIX_REL = f"{RELEASE_CANDIDATE_DIR}/release_gate_matrix.json"
ARTIFACT_MANIFEST_REL = f"{RELEASE_CANDIDATE_DIR}/artifact_manifest.json"
ARTIFACT_HASHES_REL = f"{RELEASE_CANDIDATE_DIR}/artifact_hashes.json"
RELEASE_CANDIDATE_SUMMARY_REL = f"{RELEASE_CANDIDATE_DIR}/release_candidate_summary.json"

PRODUCER = "production_release_candidate"
Runner = Callable[[Path], Mapping[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env_or_default(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


def _query_history_enabled_default(profile: str) -> bool:
    configured = os.environ.get("OVERWATCH_QUERY_PLAN_PROOF")
    if configured is not None:
        return configured == "1"
    return profile in {"internal_live", "prod_candidate"}


def _git_sha(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(root: Path, rel: str) -> Mapping[str, Any]:
    try:
        payload = json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _load_artifact_tree(root: Path) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    artifacts_root = root / "artifacts"
    if not artifacts_root.exists():
        return artifacts
    for path in sorted(artifacts_root.rglob("*.json")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            artifacts[rel] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return artifacts


def _fresh_passing_gate(root: Path, rel: str, *, max_age_minutes: int = 180) -> bool:
    path = root / rel
    if not path.exists() or not path.is_file():
        return False
    try:
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return False
    if age > timedelta(minutes=max_age_minutes):
        return False
    payload = _load_json(root, rel)
    return (
        bool(payload.get("passed"))
        and _as_int(payload.get("failure_count")) == 0
        and not bool(payload.get("raw_sql_included"))
    )


def _as_int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_manifest(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    artifacts_root = root / "artifacts"
    if artifacts_root.exists():
        for path in sorted(artifacts_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            files.append(
                {
                    "path": rel,
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return {
        "source": "production_release_candidate_artifact_manifest",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "artifact_count": len(files),
        "files": files,
        "raw_sql_included": False,
    }


def _artifact_hashes(manifest: Mapping[str, Any]) -> dict[str, Any]:
    files = manifest.get("files")
    rows = [
        {"path": str(row.get("path") or ""), "sha256": str(row.get("sha256") or "")}
        for row in files
        if isinstance(row, Mapping)
    ] if isinstance(files, list) else []
    return {
        "source": "production_release_candidate_artifact_hashes",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "artifact_count": len(rows),
        "hashes": rows,
        "raw_sql_included": False,
    }


def _phase_signature(row: Mapping[str, Any]) -> str:
    payload = {
        "producer": PRODUCER,
        "phase": row.get("phase"),
        "artifact_path": row.get("artifact_path"),
        "passed": row.get("passed"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _artifact_commit_sha(payload: Mapping[str, Any]) -> str:
    for key in ("commit_sha", "source_commit_sha", "current_commit_sha"):
        value = str(payload.get(key) or "")
        if value:
            return value
    rows = payload.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping):
                value = str(row.get("commit_sha") or "")
                if value:
                    return value
    return ""


def _artifact_row_count(payload: Mapping[str, Any]) -> int:
    for key in ("row_count", "artifact_count", "phase_count", "object_count"):
        if key in payload:
            return _as_int(payload.get(key))
    rows = payload.get("rows")
    if isinstance(rows, list):
        return len(rows)
    failures = payload.get("failures")
    if isinstance(failures, list):
        return len(failures)
    return 1 if payload else 0


def _phase_row(
    root: Path,
    *,
    phase: str,
    artifact_path: str,
    gate: Mapping[str, Any],
    release_blocking: bool = True,
) -> dict[str, Any]:
    passed = bool(gate.get("passed"))
    artifact_file = root / artifact_path
    artifact_exists = artifact_file.exists()
    artifact_sha = _sha256_file(artifact_file)
    artifact_commit = _artifact_commit_sha(gate)
    commit_sha = _git_sha(root)
    token_path_leak_count = max(
        _as_int(gate.get("token_path_leak_count")),
        _as_int(gate.get("snowflake_cli_token_path_leak_count")),
    )
    temp_sql_path_leak_count = max(
        _as_int(gate.get("temp_sql_path_leak_count")),
        _as_int(gate.get("temp_sql_file_leftover_count")),
    )
    row = {
        "producer": PRODUCER,
        "producer_signature": "",
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": commit_sha,
        "source": "production_release_candidate",
        "runtime_source": "producer_artifact_gate",
        "section": "Production Deployment",
        "workflow": "Release candidate",
        "phase": phase,
        "artifact_path": artifact_path,
        "artifact_exists": artifact_exists,
        "artifact_sha256": artifact_sha,
        "artifact_commit_sha": artifact_commit,
        "artifact_commit_sha_matches": not artifact_commit or artifact_commit == commit_sha,
        "phase_artifact_producer": str(gate.get("producer") or gate.get("source") or ""),
        "phase_artifact_producer_signature": str(gate.get("producer_signature") or ""),
        "phase_artifact_provenance_origin": str(gate.get("provenance_origin") or ""),
        "token_path_leak_count": token_path_leak_count,
        "temp_sql_path_leak_count": temp_sql_path_leak_count,
        "row_count": _artifact_row_count(gate),
        "referenced_row_ids": gate.get("referenced_row_ids") or gate.get("row_ids") or [],
        "release_blocking": release_blocking,
        "passed": passed
        and artifact_exists
        and not bool(gate.get("raw_sql_included"))
        and token_path_leak_count == 0
        and temp_sql_path_leak_count == 0
        and (not artifact_commit or artifact_commit == commit_sha),
        "failure_count": _as_int(gate.get("failure_count")),
        "failure_reason": ""
        if (
            passed
            and artifact_exists
            and not bool(gate.get("raw_sql_included"))
            and token_path_leak_count == 0
            and temp_sql_path_leak_count == 0
            and (not artifact_commit or artifact_commit == commit_sha)
        )
        else "production release candidate phase failed or artifact dereference failed",
        "raw_sql_included": False,
    }
    row["producer_signature"] = _phase_signature(row)
    return row


def _profile_policy_row(
    root: Path,
    options: SnowflakeCliValidationOptions,
    *,
    run_launch_readiness: bool,
) -> dict[str, Any]:
    profile = options.profile
    launch_required = profile in {"internal_live", "prod_candidate"}
    live_required = profile in {"internal_live", "prod_candidate"}
    browser_required = profile == "prod_candidate"
    waiver_required = False
    failures: list[str] = []
    if launch_required and not run_launch_readiness:
        failures.append("Launch readiness is required for internal_live and prod_candidate.")
    if profile == "prod_candidate" and not run_launch_readiness:
        failures.append("--no-launch-readiness is forbidden for prod_candidate.")
    row = {
        "producer": PRODUCER,
        "producer_signature": "",
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": _git_sha(root),
        "source": "production_release_candidate",
        "runtime_source": "profile_policy",
        "section": "Production Deployment",
        "workflow": "Release candidate",
        "phase": "profile_policy",
        "artifact_path": PRODUCTION_RELEASE_CANDIDATE_RESULTS_REL,
        "artifact_exists": True,
        "release_blocking": True,
        "launch_profile": profile,
        "launch_readiness_required": launch_required,
        "live_proof_required": live_required,
        "browser_proof_required": browser_required,
        "waiver_required": waiver_required,
        "waiver_present": False,
        "run_launch_readiness": run_launch_readiness,
        "passed": not failures,
        "failure_count": len(failures),
        "failure_reason": "; ".join(failures),
        "raw_sql_included": False,
    }
    row["producer_signature"] = _phase_signature(row)
    return row


def _apply_options_to_env(options: SnowflakeCliValidationOptions) -> None:
    assignments = {
        "OVERWATCH_LAUNCH_PROFILE": options.profile,
        "OVERWATCH_SNOWFLAKE_CLI_CONNECTION": options.connection,
        "OVERWATCH_SNOWFLAKE_CLI_AUTHENTICATOR": options.authenticator,
        "OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH": options.token_file_path,
        "OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE": options.database,
        "OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA": options.schema,
        "OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE": options.warehouse,
        "OVERWATCH_COMPANY": options.company,
        "OVERWATCH_ENVIRONMENT": options.environment,
        "OVERWATCH_WINDOW_DAYS": str(options.window_days),
        "OVERWATCH_SKIP_REFRESH_VALIDATION": "1" if options.skip_refresh else "0",
        "OVERWATCH_RUN_FAST_REFRESH_VALIDATION": "1" if options.run_fast_refresh else "0",
    }
    for key, value in assignments.items():
        if value:
            os.environ[key] = str(value)


def _run_phase(
    root: Path,
    phase: str,
    artifact_path: str,
    runner: Runner,
    *,
    gate_rel: str | None = None,
    release_blocking: bool = True,
) -> tuple[dict[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    artifacts = dict(runner(root))
    gate_key = gate_rel or artifact_path
    gate = artifacts.get(gate_key)
    if not isinstance(gate, Mapping):
        gate = _load_json(root, artifact_path)
    return (
        _phase_row(
            root,
            phase=phase,
            artifact_path=artifact_path,
            gate=gate,
            release_blocking=release_blocking,
        ),
        artifacts,
        gate,
    )


def _failed_gate(*, source: str, reason: str) -> dict[str, Any]:
    return {
        "source": source,
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "passed": False,
        "production_deployable": False,
        "failure_count": 1,
        "hard_gate_failure_count": 1,
        "failures": [
            {
                "code": "PRODUCTION_RELEASE_CANDIDATE_PHASE_FAILED",
                "failure_reason": reason,
            }
        ],
        "raw_sql_included": False,
    }


def _progress_payloads(root: Path, phase_rows: Sequence[Mapping[str, Any]], options: SnowflakeCliValidationOptions) -> dict[str, Any]:
    failures = [
        dict(row)
        for row in phase_rows
        if bool(row.get("release_blocking", True)) and not bool(row.get("passed"))
    ]
    generated_at = _utc_now()
    results = {
        "source": "production_release_candidate_results",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": generated_at,
        "commit_sha": _git_sha(root),
        "launch_profile": options.profile,
        "completed": False,
        "passed": False,
        "all_passed": False,
        "production_deployable": False,
        "failure_count": len(failures),
        "hard_gate_failure_count": len(failures),
        "phase_count": len(phase_rows),
        "token_auth_used": options.authenticator.upper() == "PROGRAMMATIC_ACCESS_TOKEN",
        "token_file_supplied": bool(options.token_file_path),
        "rows": [dict(row) for row in phase_rows],
        "failures": failures,
        "raw_sql_included": False,
    }
    failures_payload = {
        "source": "production_release_candidate_failures",
        "producer": PRODUCER,
        "generated_at": generated_at,
        "completed": False,
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }
    return {
        PRODUCTION_RELEASE_CANDIDATE_RESULTS_REL: results,
        PRODUCTION_RELEASE_CANDIDATE_FAILURES_REL: failures_payload,
    }


def _write_progress_artifacts(
    root: Path,
    phase_rows: Sequence[Mapping[str, Any]],
    options: SnowflakeCliValidationOptions,
) -> None:
    for rel, payload in _progress_payloads(root, phase_rows, options).items():
        _write_json(root / rel, payload)


def build_production_release_candidate_gate(payload: object) -> dict[str, Any]:
    results = payload if isinstance(payload, Mapping) else {}
    failures = list(results.get("failures") or [])
    if not results:
        failures = [{"phase": "production_release_candidate", "failure_reason": "Production release candidate results missing."}]
    elif not bool(results.get("passed")) and not failures:
        failures = [{"phase": "production_release_candidate", "failure_reason": "Production release candidate failed."}]
    return {
        "source": "production_release_candidate_gate_results",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "passed": not failures and bool(results.get("passed")),
        "production_deployable": not failures and bool(results.get("production_deployable")),
        "failure_count": len(failures),
        "hard_gate_failure_count": len(failures),
        "phase_count": _as_int(results.get("phase_count")),
        "token_path_leak_count": _as_int(results.get("token_path_leak_count")),
        "temp_sql_file_leftover_count": _as_int(results.get("temp_sql_file_leftover_count")),
        "failures": failures,
        "raw_sql_included": False,
    }


def _final_release_candidate_summary(root: Path, results: Mapping[str, Any]) -> dict[str, Any]:
    launch_summary = dict(_load_json(root, "artifacts/launch_readiness/launch_readiness_summary.json"))
    ci_gate = _load_json(root, CI_ARTIFACT_REALITY_GATE_REL)
    artifact_integrity_gate = _load_json(root, ARTIFACT_INTEGRITY_GATE_REL)
    release_registry_gate = _load_json(root, RELEASE_EVIDENCE_REGISTRY_GATE_REL)
    runtime_event_gate = _load_json(root, RUNTIME_EVENT_LEDGER_GATE_REL)
    route_replay_gate = _load_json(root, ROUTE_ACTION_REPLAY_GATE_REL)
    export_case_parity_gate = _load_json(root, EXPORT_CASE_PARITY_GATE_REL)
    first_paint_slo_gate = _load_json(root, "artifacts/launch_readiness/first_paint_slo_gate_results.json")
    action_click_gate = _load_json(root, "artifacts/launch_readiness/action_click_gate_results.json")
    export_download_gate = _load_json(root, "artifacts/launch_readiness/export_download_gate_results.json")
    plan_adherence_report = _load_json(root, PLAN_ADHERENCE_REPORT_REL)
    full_sweep = _load_json(root, FULL_APP_RELEASE_SWEEP_GATE_REL)
    a_grade_gate = _load_json(root, A_GRADE_EXECUTION_MATRIX_GATE_REL)
    a_grade_summary = _load_json(root, A_GRADE_EXECUTION_MATRIX_SUMMARY_REL)
    snowflake_cli = _load_json(root, CLI_LAUNCH_GATE_REL)
    rehearsal = _load_json(root, CLI_PRODUCTION_REHEARSAL_GATE_REL)
    current_failures = list(results.get("failures") or [])
    production_deployable = bool(results.get("production_deployable")) and bool(
        launch_summary.get("production_deployable", True)
    )
    passed = bool(results.get("passed")) and bool(launch_summary.get("passed", True))
    summary = {
        **launch_summary,
        "source": "release_candidate_summary",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": _git_sha(root),
        "passed": passed,
        "all_passed": passed,
        "production_deployable": production_deployable,
        "a_grade_ready": bool(a_grade_gate.get("a_grade_ready", a_grade_summary.get("a_grade_ready", False))),
        "a_grade_execution_matrix_passed": bool(a_grade_gate.get("passed")),
        "query_performance_grade": str(a_grade_gate.get("query_performance_grade") or launch_summary.get("query_performance_grade") or ""),
        "app_performance_grade": str(a_grade_gate.get("app_performance_grade") or launch_summary.get("app_performance_grade") or ""),
        "ui_grade": str(a_grade_gate.get("ui_grade") or launch_summary.get("ui_grade") or ""),
        "ux_grade": str(a_grade_gate.get("ux_grade") or launch_summary.get("ux_grade") or ""),
        "maintainability_grade": str(a_grade_gate.get("maintainability_grade") or launch_summary.get("maintainability_grade") or ""),
        "production_readiness_grade": str(
            a_grade_gate.get("production_readiness_grade") or launch_summary.get("production_readiness_grade") or ""
        ),
        "required_followups": list(a_grade_gate.get("required_followups") or launch_summary.get("required_followups") or []),
        "failure_count": len(current_failures),
        "hard_gate_failure_count": len(current_failures),
        "production_release_candidate_passed": bool(results.get("passed")),
        "production_release_candidate_phase_count": _as_int(results.get("phase_count")),
        "production_release_candidate_artifact": PRODUCTION_RELEASE_CANDIDATE_RESULTS_REL,
        "ci_artifact_reality_passed": bool(ci_gate.get("passed", launch_summary.get("ci_artifact_reality_passed"))),
        "artifact_integrity_passed": bool(
            artifact_integrity_gate.get("passed", launch_summary.get("artifact_integrity_passed"))
        ),
        "artifact_integrity_failure_count": _as_int(
            artifact_integrity_gate.get("failure_count", launch_summary.get("artifact_integrity_failure_count"))
        ),
        "artifact_integrity_verified_count": _as_int(
            artifact_integrity_gate.get("verified_artifact_count", launch_summary.get("artifact_integrity_verified_count"))
        ),
        "artifact_hash_mismatch_count": _as_int(
            artifact_integrity_gate.get("hash_mismatch_count", launch_summary.get("artifact_hash_mismatch_count"))
        ),
        "release_evidence_registry_passed": bool(
            release_registry_gate.get("passed", launch_summary.get("release_evidence_registry_passed"))
        ),
        "release_evidence_registry_failure_count": _as_int(
            release_registry_gate.get("failure_count", launch_summary.get("release_evidence_registry_failure_count"))
        ),
        "runtime_event_ledger_passed": bool(
            runtime_event_gate.get("passed", launch_summary.get("runtime_event_ledger_passed"))
        ),
        "runtime_event_ledger_failure_count": _as_int(
            runtime_event_gate.get("failure_count", launch_summary.get("runtime_event_ledger_failure_count"))
        ),
        "route_action_replay_passed": bool(
            route_replay_gate.get("passed", launch_summary.get("route_action_replay_passed"))
        ),
        "route_action_replay_failure_count": _as_int(
            route_replay_gate.get("failure_count", launch_summary.get("route_action_replay_failure_count"))
        ),
        "export_case_parity_passed": bool(
            export_case_parity_gate.get("passed", launch_summary.get("export_case_parity_passed"))
        ),
        "export_case_parity_failure_count": _as_int(
            export_case_parity_gate.get("failure_count", launch_summary.get("export_case_parity_failure_count"))
        ),
        "first_paint_passed": bool(
            first_paint_slo_gate.get("passed", launch_summary.get("first_paint_passed"))
        ),
        "exact_action_match_passed": bool(
            action_click_gate.get("passed", launch_summary.get("exact_action_match_passed"))
        ),
        "export_parse_passed": bool(
            export_download_gate.get("passed", launch_summary.get("export_parse_passed"))
        )
        and bool(export_case_parity_gate.get("passed", launch_summary.get("export_case_parity_passed"))),
        "plan_adherence_report_path": PLAN_ADHERENCE_REPORT_REL,
        "plan_adherence_report_passed": bool(
            plan_adherence_report.get("passed", launch_summary.get("plan_adherence_report_passed", False))
        ),
        "plan_adherence_failure_count": _as_int(
            plan_adherence_report.get("failure_count", launch_summary.get("plan_adherence_failure_count"))
        ),
        "plan_adherence_deviation_count": _as_int(
            plan_adherence_report.get("deviation_count", launch_summary.get("plan_adherence_deviation_count"))
        ),
        "local_artifact_signature": str(
            results.get("local_artifact_signature") or ci_gate.get("local_artifact_signature") or ""
        ),
        "snowflake_cli_gate_passed": bool(
            snowflake_cli.get("snowflake_cli_gate_passed", snowflake_cli.get("passed", launch_summary.get("snowflake_cli_gate_passed")))
        ),
        "snowflake_cli_live_passed": bool(snowflake_cli.get("snowflake_cli_live_passed", launch_summary.get("snowflake_cli_live_passed"))),
        "deployment_rehearsal_passed": bool(rehearsal.get("passed", launch_summary.get("deployment_rehearsal_passed"))),
        "full_app_release_sweep_passed": bool(full_sweep.get("passed", launch_summary.get("full_app_release_sweep_passed"))),
        "token_path_leak_count": max(
            _as_int(results.get("token_path_leak_count")),
            _as_int(ci_gate.get("token_path_leak_count")),
            _as_int(launch_summary.get("token_path_leak_count")),
        ),
        "temp_sql_file_leftover_count": max(
            _as_int(results.get("temp_sql_file_leftover_count")),
            _as_int(launch_summary.get("temp_sql_file_leftover_count")),
        ),
        "hard_gate_failures": current_failures,
        "failures": current_failures,
        "raw_sql_included": False,
    }
    if current_failures:
        summary["production_deployable"] = False
        summary["all_passed"] = False
        summary["passed"] = False
    if plan_adherence_report and not bool(plan_adherence_report.get("passed")):
        plan_failure = {
            "phase": "plan_adherence_report",
            "artifact_path": PLAN_ADHERENCE_REPORT_REL,
            "failure_reason": "Plan adherence report failed; production deployable and A-grade-ready status are blocked.",
        }
        summary["production_deployable"] = False
        summary["a_grade_ready"] = False
        summary["all_passed"] = False
        summary["passed"] = False
        summary["hard_gate_failures"] = [*list(summary.get("hard_gate_failures") or []), plan_failure]
        summary["failures"] = [*list(summary.get("failures") or []), plan_failure]
        summary["failure_count"] = _as_int(summary.get("failure_count")) + 1
        summary["hard_gate_failure_count"] = _as_int(summary.get("hard_gate_failure_count")) + 1
    return summary


def run_production_release_candidate(
    root: Path | str = ".",
    *,
    options: SnowflakeCliValidationOptions,
    run_launch_readiness: bool = True,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    _apply_options_to_env(options)
    payloads: dict[str, Any] = {}
    phase_rows: list[dict[str, Any]] = []
    phase_rows.append(_profile_policy_row(root_path, options, run_launch_readiness=run_launch_readiness))
    _write_progress_artifacts(root_path, phase_rows, options)

    def add(
        phase: str,
        artifact_path: str,
        runner: Runner,
        *,
        gate_rel: str | None = None,
        release_blocking: bool = True,
        reuse_fresh_gate: bool = False,
    ) -> None:
        reused = False
        effective_gate_rel = gate_rel or artifact_path
        effective_runner = runner
        if reuse_fresh_gate and _fresh_passing_gate(root_path, effective_gate_rel):
            reused = True
            effective_runner = _load_artifact_tree
        row, artifacts, _gate = _run_phase(
            root_path,
            phase,
            artifact_path,
            effective_runner,
            gate_rel=gate_rel,
            release_blocking=release_blocking,
        )
        if reused:
            row["consumed_existing_artifact"] = True
            row["runtime_source"] = "fresh_producer_artifact_gate"
        payloads.update(artifacts)
        phase_rows.append(row)
        _write_progress_artifacts(root_path, phase_rows, options)

    add("app_entry_smoke", APP_ENTRY_SMOKE_GATE_REL, write_app_entry_smoke_artifacts, gate_rel=APP_ENTRY_SMOKE_GATE_REL)
    add("import_laziness_runtime_graph", IMPORT_LAZINESS_GATE_REL, write_import_laziness_artifacts, gate_rel=IMPORT_LAZINESS_GATE_REL)
    add(
        "production_deployment_readiness",
        PRODUCTION_DEPLOYMENT_READINESS_GATE_REL,
        lambda r: write_production_deployment_readiness_artifacts(r, payloads),
        gate_rel=PRODUCTION_DEPLOYMENT_READINESS_GATE_REL,
        release_blocking=False,
    )
    add("rollback_readiness", ROLLBACK_READINESS_GATE_REL, write_rollback_readiness_artifacts, gate_rel=ROLLBACK_READINESS_GATE_REL)
    add(
        "production_deployment_manifest_initial",
        PRODUCTION_DEPLOYMENT_MANIFEST_GATE_REL,
        lambda r: write_production_deployment_manifest_artifacts(r, payloads),
        gate_rel=PRODUCTION_DEPLOYMENT_MANIFEST_GATE_REL,
        release_blocking=False,
    )
    add(
        "token_backed_snowflake_cli",
        CLI_LAUNCH_GATE_REL,
        lambda r: write_snowflake_cli_live_validation_artifacts(r, options=options),
        gate_rel=CLI_LAUNCH_GATE_REL,
        reuse_fresh_gate=True,
    )
    add("temp_sql_file_hygiene", CLI_TEMP_FILE_HYGIENE_GATE_REL, lambda _r: payloads, gate_rel=CLI_TEMP_FILE_HYGIENE_GATE_REL)
    add("setup_migration_live_validation", "artifacts/launch_readiness/setup_migration_live_gate_results.json", lambda _r: payloads)
    add(
        "snowflake_object_drift_validation",
        SNOWFLAKE_OBJECT_DRIFT_GATE_REL,
        lambda r: write_snowflake_object_drift_validation_artifacts(r, profile=options.profile),
        gate_rel=SNOWFLAKE_OBJECT_DRIFT_GATE_REL,
        reuse_fresh_gate=True,
    )
    add(
        "production_deployment_rehearsal",
        CLI_PRODUCTION_REHEARSAL_GATE_REL,
        lambda _r: payloads,
        gate_rel=CLI_PRODUCTION_REHEARSAL_GATE_REL,
        release_blocking=False,
    )
    preliminary_manifest = _artifact_manifest(root_path)
    preliminary_hashes = _artifact_hashes(preliminary_manifest)
    _write_json(root_path / ARTIFACT_MANIFEST_REL, preliminary_manifest)
    _write_json(root_path / ARTIFACT_HASHES_REL, preliminary_hashes)
    payloads[ARTIFACT_MANIFEST_REL] = preliminary_manifest
    payloads[ARTIFACT_HASHES_REL] = preliminary_hashes
    add(
        "post_deploy_smoke",
        POST_DEPLOY_SMOKE_GATE_REL,
        lambda r: write_post_deploy_smoke_artifacts(r, payloads),
        gate_rel=POST_DEPLOY_SMOKE_GATE_REL,
    )

    if run_launch_readiness:
        from tools.contracts.launch_readiness import write_launch_readiness_artifacts

        launch_ok = True
        try:
            launch_artifacts = write_launch_readiness_artifacts(root_path)
        except AssertionError:
            launch_ok = False
            launch_artifacts = {
                "launch_readiness_summary": _failed_gate(
                    source="launch_readiness_summary",
                    reason="Launch readiness failed; inspect artifacts/launch_readiness/launch_readiness_failures.json.",
                )
            }
        payloads.update(launch_artifacts)
        payloads.update(_load_artifact_tree(root_path))
        add(
            "ci_artifact_reality",
            CI_ARTIFACT_REALITY_GATE_REL,
            lambda _r: payloads,
            gate_rel=CI_ARTIFACT_REALITY_GATE_REL,
        )
        artifact_integrity_artifacts = write_artifact_integrity_artifacts(root_path)
        payloads.update(artifact_integrity_artifacts)
        add(
            "artifact_integrity",
            ARTIFACT_INTEGRITY_GATE_REL,
            lambda _r: payloads,
            gate_rel=ARTIFACT_INTEGRITY_GATE_REL,
        )
        add(
            "release_evidence_registry",
            RELEASE_EVIDENCE_REGISTRY_GATE_REL,
            lambda _r: payloads,
            gate_rel=RELEASE_EVIDENCE_REGISTRY_GATE_REL,
        )
        add(
            "runtime_event_ledger",
            RUNTIME_EVENT_LEDGER_GATE_REL,
            lambda _r: payloads,
            gate_rel=RUNTIME_EVENT_LEDGER_GATE_REL,
        )
        add(
            "route_action_replay",
            ROUTE_ACTION_REPLAY_GATE_REL,
            lambda _r: payloads,
            gate_rel=ROUTE_ACTION_REPLAY_GATE_REL,
        )
        add(
            "export_case_parity",
            EXPORT_CASE_PARITY_GATE_REL,
            lambda _r: payloads,
            gate_rel=EXPORT_CASE_PARITY_GATE_REL,
        )
        add(
            "a_grade_execution_matrix",
            A_GRADE_EXECUTION_MATRIX_GATE_REL,
            lambda _r: payloads,
            gate_rel=A_GRADE_EXECUTION_MATRIX_GATE_REL,
        )
        phase_rows.append(
            _phase_row(
                root_path,
                phase="launch_readiness_release_bundle",
                artifact_path="artifacts/launch_readiness/launch_readiness_summary.json",
                gate=_load_json(root_path, "artifacts/launch_readiness/launch_readiness_summary.json")
                if launch_ok
                else launch_artifacts["launch_readiness_summary"],
            )
        )
        payloads.update(_load_artifact_tree(root_path))
        add(
            "post_launch_production_deployment_readiness",
            PRODUCTION_DEPLOYMENT_READINESS_GATE_REL,
            lambda _r: payloads,
            gate_rel=PRODUCTION_DEPLOYMENT_READINESS_GATE_REL,
        )
        add(
            "post_launch_production_deployment_rehearsal",
            CLI_PRODUCTION_REHEARSAL_GATE_REL,
            lambda _r: payloads,
            gate_rel=CLI_PRODUCTION_REHEARSAL_GATE_REL,
        )
        add(
            "post_launch_object_drift_validation",
            SNOWFLAKE_OBJECT_DRIFT_GATE_REL,
            lambda r: write_snowflake_object_drift_validation_artifacts(r, profile=options.profile),
            gate_rel=SNOWFLAKE_OBJECT_DRIFT_GATE_REL,
            reuse_fresh_gate=True,
        )
        add(
            "post_launch_post_deploy_smoke",
            POST_DEPLOY_SMOKE_GATE_REL,
            lambda r: write_post_deploy_smoke_artifacts(r, payloads),
            gate_rel=POST_DEPLOY_SMOKE_GATE_REL,
        )
        add("post_launch_full_app_release_sweep", FULL_APP_RELEASE_SWEEP_GATE_REL, lambda r: write_full_app_release_sweep_artifacts(r, payloads), gate_rel=FULL_APP_RELEASE_SWEEP_GATE_REL)
    else:
        write_local_artifact_proof(
            root_path,
            profile=options.profile,
            allow_in_progress_launch_readiness=True,
        )

    add(
        "production_deployment_manifest_final",
        PRODUCTION_DEPLOYMENT_MANIFEST_GATE_REL,
        lambda r: write_production_deployment_manifest_artifacts(r, payloads),
        gate_rel=PRODUCTION_DEPLOYMENT_MANIFEST_GATE_REL,
    )

    failures = [
        row
        for row in phase_rows
        if bool(row.get("release_blocking", True)) and not bool(row.get("passed"))
    ]
    token_leak_count = max(
        _as_int(_load_json(root_path, "artifacts/launch_readiness/snowflake_cli_live_gate_results.json").get("snowflake_cli_token_path_leak_count")),
        _as_int(_load_json(root_path, PRODUCTION_DEPLOYMENT_MANIFEST_GATE_REL).get("token_path_leak_count")),
    )
    temp_leftover_count = _as_int(
        _load_json(root_path, "artifacts/launch_readiness/snowflake_cli_temp_file_hygiene_gate_results.json").get("temp_sql_file_leftover_count")
    )
    results = {
        "source": "production_release_candidate_results",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": _git_sha(root_path),
        "launch_profile": options.profile,
        "profile_policy": dict(phase_rows[0]) if phase_rows else {},
        "launch_readiness_required": options.profile in {"internal_live", "prod_candidate"},
        "live_proof_required": options.profile in {"internal_live", "prod_candidate"},
        "browser_proof_required": options.profile == "prod_candidate",
        "waiver_required": False,
        "waiver_present": False,
        "passed": not failures,
        "all_passed": not failures,
        "production_deployable": not failures,
        "failure_count": len(failures),
        "hard_gate_failure_count": len(failures),
        "phase_count": len(phase_rows),
        "token_auth_used": options.authenticator.upper() == "PROGRAMMATIC_ACCESS_TOKEN",
        "token_file_supplied": bool(options.token_file_path),
        "local_artifact_signature": str(
            _load_json(root_path, CI_ARTIFACT_REALITY_GATE_REL).get("local_artifact_signature") or ""
        ),
        "token_path_leak_count": token_leak_count,
        "temp_sql_file_leftover_count": temp_leftover_count,
        "rows": phase_rows,
        "failures": failures,
        "raw_sql_included": False,
    }
    failures_payload = {
        "source": "production_release_candidate_failures",
        "producer": PRODUCER,
        "generated_at": results["generated_at"],
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }
    gate = build_production_release_candidate_gate(results)
    gate_matrix = {
        "source": "production_release_candidate_gate_matrix",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "passed": not failures,
        "gate_count": len(phase_rows),
        "gates": [
            {
                "gate": row["phase"],
                "artifact_path": row["artifact_path"],
                "release_blocking": bool(row.get("release_blocking", True)),
                "passed": row["passed"],
                "failure_count": row["failure_count"],
            }
            for row in phase_rows
        ],
        "raw_sql_included": False,
    }
    final_summary = _final_release_candidate_summary(root_path, results)
    for rel, payload in {
        PRODUCTION_RELEASE_CANDIDATE_RESULTS_REL: results,
        PRODUCTION_RELEASE_CANDIDATE_FAILURES_REL: failures_payload,
        PRODUCTION_RELEASE_CANDIDATE_GATE_REL: gate,
        RELEASE_GATE_MATRIX_REL: gate_matrix,
        RELEASE_CANDIDATE_SUMMARY_REL: final_summary,
    }.items():
        _write_json(root_path / rel, payload)
    plan_artifacts = write_plan_adherence_report(root_path)
    plan_report = plan_artifacts[PLAN_ADHERENCE_REPORT_REL]
    final_summary["plan_adherence_report_path"] = PLAN_ADHERENCE_REPORT_REL
    final_summary["plan_adherence_report_passed"] = bool(plan_report.get("passed"))
    final_summary["plan_adherence_failure_count"] = _as_int(plan_report.get("failure_count"))
    final_summary["plan_adherence_deviation_count"] = _as_int(plan_report.get("deviation_count"))
    if not bool(plan_report.get("passed")) and bool(final_summary.get("production_deployable", True)):
        plan_failure = {
            "phase": "plan_adherence_report",
            "artifact_path": PLAN_ADHERENCE_REPORT_REL,
            "failure_reason": "Plan adherence report failed; production deployable and A-grade-ready status are blocked.",
        }
        final_summary["production_deployable"] = False
        final_summary["a_grade_ready"] = False
        final_summary["all_passed"] = False
        final_summary["passed"] = False
        final_summary["hard_gate_failures"] = [*list(final_summary.get("hard_gate_failures") or []), plan_failure]
        final_summary["failures"] = [*list(final_summary.get("failures") or []), plan_failure]
        final_summary["failure_count"] = _as_int(final_summary.get("failure_count")) + 1
        final_summary["hard_gate_failure_count"] = _as_int(final_summary.get("hard_gate_failure_count")) + 1
    _write_json(root_path / RELEASE_CANDIDATE_SUMMARY_REL, final_summary)
    artifact_manifest = _artifact_manifest(root_path)
    artifact_hashes = _artifact_hashes(artifact_manifest)
    artifacts = {
        PRODUCTION_RELEASE_CANDIDATE_RESULTS_REL: results,
        PRODUCTION_RELEASE_CANDIDATE_FAILURES_REL: failures_payload,
        PRODUCTION_RELEASE_CANDIDATE_GATE_REL: gate,
        RELEASE_GATE_MATRIX_REL: gate_matrix,
        RELEASE_CANDIDATE_SUMMARY_REL: final_summary,
        PLAN_ADHERENCE_REPORT_REL: plan_report,
        ARTIFACT_MANIFEST_REL: artifact_manifest,
        ARTIFACT_HASHES_REL: artifact_hashes,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return results


def options_from_args(argv: Sequence[str] | None = None) -> SnowflakeCliValidationOptions:
    parser = argparse.ArgumentParser(description="Run OVERWATCH production release candidate proof.")
    parser.add_argument("--profile", default=os.environ.get("OVERWATCH_LAUNCH_PROFILE", "internal_fixture"))
    parser.add_argument("--connection", default=os.environ.get("OVERWATCH_SNOWFLAKE_CLI_CONNECTION", ""))
    parser.add_argument("--authenticator", default=os.environ.get("OVERWATCH_SNOWFLAKE_CLI_AUTHENTICATOR", ""))
    parser.add_argument("--token-file-path", default=os.environ.get("OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH", ""))
    parser.add_argument("--database", default=_env_or_default("OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE", DEFAULT_VALIDATION_DATABASE))
    parser.add_argument("--schema", default=_env_or_default("OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA", DEFAULT_VALIDATION_SCHEMA))
    parser.add_argument("--warehouse", default=_env_or_default("OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE", ""))
    parser.add_argument("--company", default=os.environ.get("OVERWATCH_COMPANY", "ALFA"))
    parser.add_argument("--environment", default=os.environ.get("OVERWATCH_ENVIRONMENT", "ALL"))
    parser.add_argument("--window-days", type=int, default=int(os.environ.get("OVERWATCH_WINDOW_DAYS", "7") or "7"))
    parser.add_argument("--skip-refresh", action="store_true", default=os.environ.get("OVERWATCH_SKIP_REFRESH_VALIDATION", "1") == "1")
    parser.add_argument("--run-fast-refresh", action="store_true", default=os.environ.get("OVERWATCH_RUN_FAST_REFRESH_VALIDATION") == "1")
    parser.add_argument("--no-launch-readiness", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    profile = args.profile.strip() or "internal_fixture"
    return SnowflakeCliValidationOptions(
        connection=args.connection,
        profile=profile,
        authenticator=args.authenticator,
        token_file_path=args.token_file_path,
        database=args.database,
        schema=args.schema,
        warehouse=args.warehouse,
        company=args.company,
        environment=args.environment,
        window_days=args.window_days,
        skip_refresh=args.skip_refresh,
        run_fast_refresh=args.run_fast_refresh,
        query_history_enabled=_query_history_enabled_default(profile),
    )


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(argv or sys.argv[1:])
    run_launch_readiness = "--no-launch-readiness" not in raw_args
    options = options_from_args(raw_args)
    results = run_production_release_candidate(Path("."), options=options, run_launch_readiness=run_launch_readiness)
    failed = [
        f"{row.get('phase')} -> {row.get('artifact_path')}"
        for row in results.get("failures", [])
        if isinstance(row, Mapping)
    ]
    print(
        json.dumps(
            {
                "production_deployable": bool(results.get("production_deployable")),
                "all_passed": bool(results.get("all_passed")),
                "failure_count": _as_int(results.get("failure_count")),
                "failed_gates": failed[:20],
                "results_artifact": PRODUCTION_RELEASE_CANDIDATE_RESULTS_REL,
                "failures_artifact": PRODUCTION_RELEASE_CANDIDATE_FAILURES_REL,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if bool(results.get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_HASHES_REL",
    "ARTIFACT_MANIFEST_REL",
    "PRODUCTION_RELEASE_CANDIDATE_FAILURES_REL",
    "PRODUCTION_RELEASE_CANDIDATE_GATE_REL",
    "PRODUCTION_RELEASE_CANDIDATE_RESULTS_REL",
    "RELEASE_CANDIDATE_SUMMARY_REL",
    "RELEASE_GATE_MATRIX_REL",
    "build_production_release_candidate_gate",
    "options_from_args",
    "run_production_release_candidate",
]
