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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tools.contracts.app_entry_smoke import APP_ENTRY_SMOKE_GATE_REL, write_app_entry_smoke_artifacts
from tools.contracts.full_app_release_sweep import (
    FULL_APP_RELEASE_SWEEP_GATE_REL,
    write_full_app_release_sweep_artifacts,
)
from tools.contracts.import_laziness import IMPORT_LAZINESS_GATE_REL, write_import_laziness_artifacts
from tools.contracts.post_deploy_smoke import POST_DEPLOY_SMOKE_GATE_REL, write_post_deploy_smoke_artifacts
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

PRODUCER = "production_release_candidate"
Runner = Callable[[Path], Mapping[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _phase_row(
    root: Path,
    *,
    phase: str,
    artifact_path: str,
    gate: Mapping[str, Any],
    release_blocking: bool = True,
) -> dict[str, Any]:
    passed = bool(gate.get("passed"))
    row = {
        "producer": PRODUCER,
        "producer_signature": "",
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": _git_sha(root),
        "source": "production_release_candidate",
        "runtime_source": "producer_artifact_gate",
        "section": "Production Deployment",
        "workflow": "Release candidate",
        "phase": phase,
        "artifact_path": artifact_path,
        "artifact_exists": (root / artifact_path).exists(),
        "release_blocking": release_blocking,
        "passed": passed,
        "failure_count": _as_int(gate.get("failure_count")),
        "failure_reason": "" if passed else "production release candidate phase failed",
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

    def add(
        phase: str,
        artifact_path: str,
        runner: Runner,
        *,
        gate_rel: str | None = None,
        release_blocking: bool = True,
    ) -> None:
        row, artifacts, _gate = _run_phase(
            root_path,
            phase,
            artifact_path,
            runner,
            gate_rel=gate_rel,
            release_blocking=release_blocking,
        )
        payloads.update(artifacts)
        phase_rows.append(row)

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
    )
    add("temp_sql_file_hygiene", CLI_TEMP_FILE_HYGIENE_GATE_REL, lambda _r: payloads, gate_rel=CLI_TEMP_FILE_HYGIENE_GATE_REL)
    add("setup_migration_live_validation", "artifacts/launch_readiness/setup_migration_live_gate_results.json", lambda _r: payloads)
    add("snowflake_object_drift_validation", SNOWFLAKE_OBJECT_DRIFT_GATE_REL, lambda r: write_snowflake_object_drift_validation_artifacts(r, profile=options.profile), gate_rel=SNOWFLAKE_OBJECT_DRIFT_GATE_REL)
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
        add("post_launch_object_drift_validation", SNOWFLAKE_OBJECT_DRIFT_GATE_REL, lambda r: write_snowflake_object_drift_validation_artifacts(r, profile=options.profile), gate_rel=SNOWFLAKE_OBJECT_DRIFT_GATE_REL)
        add(
            "post_launch_post_deploy_smoke",
            POST_DEPLOY_SMOKE_GATE_REL,
            lambda r: write_post_deploy_smoke_artifacts(r, payloads),
            gate_rel=POST_DEPLOY_SMOKE_GATE_REL,
        )
        add("post_launch_full_app_release_sweep", FULL_APP_RELEASE_SWEEP_GATE_REL, lambda r: write_full_app_release_sweep_artifacts(r, payloads), gate_rel=FULL_APP_RELEASE_SWEEP_GATE_REL)

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
        "passed": not failures,
        "all_passed": not failures,
        "production_deployable": not failures,
        "failure_count": len(failures),
        "hard_gate_failure_count": len(failures),
        "phase_count": len(phase_rows),
        "token_auth_used": options.authenticator.upper() == "PROGRAMMATIC_ACCESS_TOKEN",
        "token_file_supplied": bool(options.token_file_path),
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
    artifact_manifest = _artifact_manifest(root_path)
    artifact_hashes = _artifact_hashes(artifact_manifest)
    artifacts = {
        PRODUCTION_RELEASE_CANDIDATE_RESULTS_REL: results,
        PRODUCTION_RELEASE_CANDIDATE_FAILURES_REL: failures_payload,
        PRODUCTION_RELEASE_CANDIDATE_GATE_REL: gate,
        RELEASE_GATE_MATRIX_REL: gate_matrix,
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
    parser.add_argument("--database", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE", ""))
    parser.add_argument("--schema", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA", ""))
    parser.add_argument("--warehouse", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE", ""))
    parser.add_argument("--company", default=os.environ.get("OVERWATCH_COMPANY", "ALFA"))
    parser.add_argument("--environment", default=os.environ.get("OVERWATCH_ENVIRONMENT", "ALL"))
    parser.add_argument("--window-days", type=int, default=int(os.environ.get("OVERWATCH_WINDOW_DAYS", "7") or "7"))
    parser.add_argument("--skip-refresh", action="store_true", default=os.environ.get("OVERWATCH_SKIP_REFRESH_VALIDATION", "1") == "1")
    parser.add_argument("--run-fast-refresh", action="store_true", default=os.environ.get("OVERWATCH_RUN_FAST_REFRESH_VALIDATION") == "1")
    parser.add_argument("--no-launch-readiness", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    return SnowflakeCliValidationOptions(
        connection=args.connection,
        profile=args.profile,
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
        query_history_enabled=os.environ.get("OVERWATCH_QUERY_PLAN_PROOF") == "1",
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
    "RELEASE_GATE_MATRIX_REL",
    "build_production_release_candidate_gate",
    "options_from_args",
    "run_production_release_candidate",
]
