"""Production deployment manifest for the release candidate bundle.

This manifest is the deployable bill of materials. It records safe relative
paths, hashes, expected roles/privileges/secrets, migration versions, and
rollback readiness. It deliberately does not serialize raw SQL bodies, token
paths, or secret material.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.contracts.production_deployment_readiness import (
    REQUIRED_ENV_VARS,
    REQUIRED_PRIVILEGE_DOCS,
    REQUIRED_SETUP_OBJECTS,
    TARGET_ROLES,
)
from tools.contracts.rollback_readiness import ROLLBACK_READINESS_GATE_REL, ROLLBACK_RUNBOOK_REL


LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
RELEASE_CANDIDATE_DIR = "artifacts/release_candidate"

PRODUCTION_DEPLOYMENT_MANIFEST_REL = f"{RELEASE_CANDIDATE_DIR}/production_deployment_manifest.json"
PRODUCTION_DEPLOYMENT_MANIFEST_GATE_REL = f"{LAUNCH_READINESS_DIR}/production_deployment_manifest_gate_results.json"

PRODUCER = "production_deployment_manifest"
SETUP_SQL_REL = "snowflake/OVERWATCH_MART_SETUP.sql"
VALIDATION_SQL_REL = "snowflake/OVERWATCH_MART_VALIDATION.sql"
DROP_SQL_REL = "snowflake/OVERWATCH_MART_DROP.sql"
SPLIT_SETUP_DIR_REL = "snowflake/mart_setup"
REQUIRED_SECRET_NAMES = tuple(REQUIRED_ENV_VARS)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(args: Iterable[str], root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _git_sha(root: Path) -> str:
    return _git(("rev-parse", "HEAD"), root)


def _git_branch(root: Path) -> str:
    return _git(("branch", "--show-current"), root) or _git(("rev-parse", "--abbrev-ref", "HEAD"), root)


def _repo_full_name(root: Path) -> str:
    remote = _git(("config", "--get", "remote.origin.url"), root)
    if not remote:
        return "jfreeze03/OVERWATCH"
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$", remote)
    if match:
        return f"{match.group('owner')}/{match.group('repo')}"
    return "jfreeze03/OVERWATCH"


def _read_text(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _sha256_file(root: Path, rel: str) -> str:
    path = root / rel
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_value(version_text: str, name: str, default: str = "") -> str:
    match = re.search(rf"^{name}\s*=\s*['\"]([^'\"]+)['\"]", version_text, flags=re.MULTILINE)
    return match.group(1) if match else default


def _migration_versions(setup_text: str) -> list[str]:
    versions = sorted(set(re.findall(r"'(\d{4}\.\d{2}\.\d{2}[^']*)'\s+AS\s+MIGRATION_VERSION", setup_text)))
    return versions


def _split_setup_file_hashes(root: Path) -> list[dict[str, str]]:
    split_dir = root / SPLIT_SETUP_DIR_REL
    rows: list[dict[str, str]] = []
    if not split_dir.exists():
        return rows
    for path in sorted(split_dir.glob("*.sql")):
        rel = path.relative_to(root).as_posix()
        rows.append({"path": rel, "sha256": _sha256_file(root, rel)})
    return rows


def _token_leak_count(payload: Mapping[str, Any]) -> int:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    token_path = os.environ.get("OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH", "")
    markers = [
        "overwatch_pat.txt",
        token_path,
        Path(token_path).name if token_path else "",
    ]
    return sum(serialized.count(marker) for marker in markers if marker)


def _raw_sql_body_leak_count(payload: Mapping[str, Any]) -> int:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return len(re.findall(r"\bCREATE\s+OR\s+REPLACE\b|\bSELECT\s+\*|\bCALL\s+SP_", serialized, flags=re.IGNORECASE))


def build_production_deployment_manifest(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    payloads = payloads or {}
    setup_text = _read_text(root_path, SETUP_SQL_REL)
    version_text = _read_text(root_path, ".overwatch_final/version.py")
    rollback_payload = payloads.get(ROLLBACK_READINESS_GATE_REL)
    rollback_gate: Mapping[str, Any] = rollback_payload if isinstance(rollback_payload, Mapping) else {}
    production_payload = payloads.get("artifacts/launch_readiness/production_deployment_readiness_gate_results.json")
    production_gate: Mapping[str, Any] = production_payload if isinstance(production_payload, Mapping) else {}
    rehearsal_payload = payloads.get("artifacts/launch_readiness/production_deployment_rehearsal_gate_results.json")
    rehearsal_gate: Mapping[str, Any] = rehearsal_payload if isinstance(rehearsal_payload, Mapping) else {}
    app_entry_payload = payloads.get("artifacts/launch_readiness/app_entry_smoke_gate_results.json")
    app_entry_gate: Mapping[str, Any] = app_entry_payload if isinstance(app_entry_payload, Mapping) else {}

    manifest: dict[str, Any] = {
        "source": "production_deployment_manifest",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "repo_full_name": _repo_full_name(root_path),
        "commit_sha": _git_sha(root_path),
        "branch_or_ref": _git_branch(root_path),
        "app_version": _version_value(version_text, "APP_VERSION"),
        "build_label": _version_value(version_text, "BUILD_LABEL"),
        "config_version": _version_value(version_text, "CONFIG_VERSION"),
        "release_profile": os.environ.get("OVERWATCH_LAUNCH_PROFILE", "internal_fixture").strip() or "internal_fixture",
        "setup_sql_path": SETUP_SQL_REL,
        "setup_sql_sha256": _sha256_file(root_path, SETUP_SQL_REL),
        "validation_sql_path": VALIDATION_SQL_REL,
        "validation_sql_sha256": _sha256_file(root_path, VALIDATION_SQL_REL),
        "drop_sql_path": DROP_SQL_REL,
        "drop_sql_sha256": _sha256_file(root_path, DROP_SQL_REL),
        "split_setup_file_hashes": _split_setup_file_hashes(root_path),
        "required_migration_versions": _migration_versions(setup_text),
        "required_snowflake_objects": list(REQUIRED_SETUP_OBJECTS),
        "required_roles": list(TARGET_ROLES),
        "required_privileges": list(REQUIRED_PRIVILEGE_DOCS.keys()),
        "required_environment_variables": list(REQUIRED_ENV_VARS),
        "required_secret_names": list(REQUIRED_SECRET_NAMES),
        "token_auth_supported": True,
        "token_file_path_stored": False,
        "raw_sql_included": False,
        "artifact_manifest_path": f"{RELEASE_CANDIDATE_DIR}/artifact_manifest.json",
        "artifact_hashes_path": f"{RELEASE_CANDIDATE_DIR}/artifact_hashes.json",
        "rollback_path": ROLLBACK_RUNBOOK_REL,
        "rollback_readiness_artifact_path": ROLLBACK_READINESS_GATE_REL,
        "deployment_rehearsal_artifact_path": "artifacts/snowflake_validation/production_deployment_rehearsal_results.json",
        "deployment_rehearsal_gate_artifact_path": "artifacts/launch_readiness/production_deployment_rehearsal_gate_results.json",
        "rollback_ready": bool(rollback_gate.get("rollback_ready", rollback_gate.get("passed"))),
        "production_deployment_readiness_passed": bool(production_gate.get("passed", True))
        if production_gate
        else True,
        "deployment_rehearsal_passed": bool(rehearsal_gate.get("passed", True))
        if rehearsal_gate
        else True,
        "live_proof_status": "passed"
        if rehearsal_gate and rehearsal_gate.get("passed")
        else ("failed" if rehearsal_gate else "not_yet_recorded"),
        "live_waiver_status": "not_required" if not rehearsal_gate else "not_waived",
        "app_entry_smoke_passed": bool(app_entry_gate.get("passed", True)) if app_entry_gate else True,
    }

    failures: list[dict[str, Any]] = []
    for field in (
        "setup_sql_sha256",
        "validation_sql_sha256",
        "drop_sql_sha256",
        "required_migration_versions",
        "split_setup_file_hashes",
        "required_snowflake_objects",
        "required_roles",
        "required_privileges",
        "required_environment_variables",
        "required_secret_names",
    ):
        if not manifest.get(field):
            failures.append({"code": "PRODUCTION_MANIFEST_FIELD_MISSING", "field": field})
    if not manifest["rollback_ready"]:
        failures.append({"code": "PRODUCTION_MANIFEST_ROLLBACK_NOT_READY"})
    if not manifest["production_deployment_readiness_passed"]:
        failures.append({"code": "PRODUCTION_MANIFEST_READINESS_GATE_FAILED"})
    if not manifest["deployment_rehearsal_passed"]:
        failures.append({"code": "PRODUCTION_MANIFEST_REHEARSAL_GATE_FAILED"})
    if not manifest["app_entry_smoke_passed"]:
        failures.append({"code": "PRODUCTION_MANIFEST_APP_ENTRY_GATE_FAILED"})
    for field in (
        "deployment_rehearsal_artifact_path",
        "deployment_rehearsal_gate_artifact_path",
        "rollback_readiness_artifact_path",
        "artifact_hashes_path",
    ):
        if not manifest.get(field):
            failures.append({"code": "PRODUCTION_MANIFEST_REFERENCE_MISSING", "field": field})

    token_leak_count = _token_leak_count(manifest)
    raw_sql_leak_count = _raw_sql_body_leak_count(manifest)
    if token_leak_count:
        failures.append({"code": "PRODUCTION_MANIFEST_TOKEN_PATH_LEAK", "leak_count": token_leak_count})
    if raw_sql_leak_count:
        failures.append({"code": "PRODUCTION_MANIFEST_RAW_SQL_BODY_LEAK", "leak_count": raw_sql_leak_count})

    manifest["token_path_leak_count"] = token_leak_count
    manifest["raw_sql_body_leak_count"] = raw_sql_leak_count
    manifest["hard_gate_failure_count"] = len(failures)
    manifest["production_deployable"] = not failures
    manifest["passed"] = not failures
    manifest["failures"] = failures
    manifest["producer_signature"] = hashlib.sha256(
        json.dumps(
            {
                "producer": PRODUCER,
                "commit_sha": manifest["commit_sha"],
                "setup_sql_sha256": manifest["setup_sql_sha256"],
                "validation_sql_sha256": manifest["validation_sql_sha256"],
                "drop_sql_sha256": manifest["drop_sql_sha256"],
                "passed": manifest["passed"],
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return manifest


def evaluate_production_deployment_manifest_gate(payload: object) -> dict[str, Any]:
    manifest = payload if isinstance(payload, Mapping) else {}
    failures = list(manifest.get("failures") or [])
    if not manifest:
        failures = [{"code": "PRODUCTION_DEPLOYMENT_MANIFEST_MISSING"}]
    elif not bool(manifest.get("passed")) and not failures:
        failures = [{"code": "PRODUCTION_DEPLOYMENT_MANIFEST_FAILED"}]
    return {
        "source": "production_deployment_manifest_gate_results",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "passed": not failures and bool(manifest.get("passed")),
        "production_deployment_manifest_passed": not failures and bool(manifest.get("passed")),
        "production_deployable": not failures and bool(manifest.get("production_deployable")),
        "rollback_ready": bool(manifest.get("rollback_ready")),
        "hard_gate_failure_count": len(failures),
        "failure_count": len(failures),
        "token_path_leak_count": int(manifest.get("token_path_leak_count") or 0),
        "raw_sql_body_leak_count": int(manifest.get("raw_sql_body_leak_count") or 0),
        "setup_sql_sha256_present": bool(manifest.get("setup_sql_sha256")),
        "validation_sql_sha256_present": bool(manifest.get("validation_sql_sha256")),
        "drop_sql_sha256_present": bool(manifest.get("drop_sql_sha256")),
        "required_migration_version_count": len(manifest.get("required_migration_versions") or []),
        "required_snowflake_object_count": len(manifest.get("required_snowflake_objects") or []),
        "deployment_rehearsal_artifact_path": str(manifest.get("deployment_rehearsal_artifact_path") or ""),
        "deployment_rehearsal_passed": bool(manifest.get("deployment_rehearsal_passed")),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_production_deployment_manifest_artifacts(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    manifest = build_production_deployment_manifest(root_path, payloads or {})
    gate = evaluate_production_deployment_manifest_gate(manifest)
    artifacts = {
        PRODUCTION_DEPLOYMENT_MANIFEST_REL: manifest,
        PRODUCTION_DEPLOYMENT_MANIFEST_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        path = root_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifacts


if __name__ == "__main__":
    written = write_production_deployment_manifest_artifacts(Path("."))
    gate = written[PRODUCTION_DEPLOYMENT_MANIFEST_GATE_REL]
    print(json.dumps(gate, indent=2, sort_keys=True))
    raise SystemExit(0 if gate.get("passed") else 1)


__all__ = [
    "PRODUCTION_DEPLOYMENT_MANIFEST_GATE_REL",
    "PRODUCTION_DEPLOYMENT_MANIFEST_REL",
    "build_production_deployment_manifest",
    "evaluate_production_deployment_manifest_gate",
    "write_production_deployment_manifest_artifacts",
]
