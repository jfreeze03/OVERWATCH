"""CI/local artifact reality gate for production release candidates.

This contract separates "the workflow/config looks right" from "the current
release proof is backed by artifacts for this commit." GitHub Actions metadata
is preferred, but local internal-live rehearsals can pass with a signed local
artifact bundle marker. The marker stores hashes and booleans only; it never
stores token paths, temp SQL paths, or SQL bodies.
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


LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
RELEASE_CANDIDATE_DIR = "artifacts/release_candidate"

CI_ARTIFACT_REALITY_RESULTS_REL = f"{LAUNCH_READINESS_DIR}/ci_artifact_reality_results.json"
CI_ARTIFACT_REALITY_GATE_REL = f"{LAUNCH_READINESS_DIR}/ci_artifact_reality_gate_results.json"
LOCAL_ARTIFACT_PROOF_REL = f"{RELEASE_CANDIDATE_DIR}/local_artifact_proof.json"

PRODUCER = "ci_artifact_reality"

REQUIRED_LOCAL_ARTIFACTS = (
    f"{RELEASE_CANDIDATE_DIR}/release_candidate_summary.json",
    f"{RELEASE_CANDIDATE_DIR}/artifact_manifest.json",
    f"{RELEASE_CANDIDATE_DIR}/artifact_hashes.json",
    f"{LAUNCH_READINESS_DIR}/launch_readiness_summary.json",
)


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


def _file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(root: Path, rel: str) -> Mapping[str, Any]:
    try:
        payload = json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _as_int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _scan_text_counts(root: Path) -> tuple[int, int, int]:
    """Return token path, temp SQL path, and raw SQL body leak counts."""

    token_markers: list[str] = []
    token_path = os.environ.get("OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH", "").strip()
    if token_path:
        token_markers.extend([token_path, Path(token_path).name])
    token_path_leaks = 0
    temp_path_leaks = 0
    raw_sql_leaks = 0
    artifacts_root = root / "artifacts"
    if not artifacts_root.exists():
        return (0, 0, 0)
    for path in artifacts_root.rglob("*.json"):
        if path.as_posix().endswith(LOCAL_ARTIFACT_PROOF_REL):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        token_path_leaks += sum(text.count(marker) for marker in token_markers if marker)
        temp_path_leaks += len(
            re.findall(
                r"(?i)(?:[A-Za-z]:\\|/)[^\"'\s]*overwatch_snowflake_validation_[^\"'\s]*\.sql",
                text,
            )
        )
        raw_sql_leaks += len(
            re.findall(r"(?is)\bCREATE\s+OR\s+REPLACE\b|\bSELECT\s+\*\b|\bCALL\s+SP_", text)
        )
    return token_path_leaks, temp_path_leaks, raw_sql_leaks


def build_local_artifact_proof(
    root: Path | str = ".",
    *,
    profile: str = "",
    allow_in_progress_launch_readiness: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = _git_sha(root_path)
    artifact_hashes: list[dict[str, Any]] = []
    artifacts_root = root_path / "artifacts"
    if artifacts_root.exists():
        for path in sorted(artifacts_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root_path).as_posix()
            if rel == LOCAL_ARTIFACT_PROOF_REL:
                continue
            artifact_hashes.append(
                {
                    "path": rel,
                    "sha256": _file_sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    missing_required = [
        rel
        for rel in REQUIRED_LOCAL_ARTIFACTS
        if not (root_path / rel).exists()
        and not (allow_in_progress_launch_readiness and rel.endswith("launch_readiness_summary.json"))
    ]
    signature_payload = {
        "commit_sha": commit_sha,
        "profile": profile,
        "artifact_hashes": artifact_hashes,
        "missing_required_artifacts": missing_required,
    }
    signature = hashlib.sha256(json.dumps(signature_payload, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "source": "local_artifact_proof",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": commit_sha,
        "launch_profile": profile,
        "local_artifact_signature": signature,
        "artifact_count": len(artifact_hashes),
        "required_artifacts": list(REQUIRED_LOCAL_ARTIFACTS),
        "missing_required_artifacts": missing_required,
        "missing_required_artifact_count": len(missing_required),
        "passed": not missing_required and bool(artifact_hashes),
        "raw_sql_included": False,
        "token_file_path_stored": False,
        "temp_sql_file_path_stored": False,
    }


def write_local_artifact_proof(
    root: Path | str = ".",
    *,
    profile: str = "",
    allow_in_progress_launch_readiness: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    proof = build_local_artifact_proof(
        root_path,
        profile=profile,
        allow_in_progress_launch_readiness=allow_in_progress_launch_readiness,
    )
    _write_json(root_path / LOCAL_ARTIFACT_PROOF_REL, proof)
    return proof


def build_ci_artifact_reality_results(
    root: Path | str = ".",
    *,
    profile: str,
    ci_run_review: Mapping[str, Any] | None = None,
    upload_review: Mapping[str, Any] | None = None,
    artifact_review: Mapping[str, Any] | None = None,
    missing_payloads: Iterable[str] = (),
    release_reconciliation: Mapping[str, Any] | None = None,
    allow_in_progress_launch_readiness: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    ci_run_review = ci_run_review or {}
    upload_review = upload_review or {}
    artifact_review = artifact_review or {}
    release_reconciliation = release_reconciliation or {}
    commit_sha = _git_sha(root_path)
    github_actions = bool(ci_run_review.get("github_actions")) or os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    workflow_run_id = str(ci_run_review.get("workflow_run_id") or os.environ.get("GITHUB_RUN_ID") or "")
    workflow_run_url = str(ci_run_review.get("workflow_url") or "")
    uploaded_artifacts = _as_list(upload_review.get("uploaded_artifact_names")) or _as_list(
        ci_run_review.get("artifact_upload_names")
    )
    required_missing = sorted(set(str(item) for item in missing_payloads if item))
    required_missing.extend(
        rel for rel in REQUIRED_LOCAL_ARTIFACTS if not (root_path / rel).exists()
    )
    if allow_in_progress_launch_readiness:
        required_missing = [
            rel for rel in required_missing if not rel.endswith("launch_readiness_summary.json")
        ]
    required_missing = sorted(set(required_missing))
    local_proof = write_local_artifact_proof(
        root_path,
        profile=profile,
        allow_in_progress_launch_readiness=allow_in_progress_launch_readiness,
    )
    token_path_leaks, temp_path_leaks, raw_sql_leaks = _scan_text_counts(root_path)
    github_proof = github_actions and bool(workflow_run_id) and bool(workflow_run_url) and bool(uploaded_artifacts)
    local_proof_ok = bool(local_proof.get("passed")) and str(local_proof.get("commit_sha") or "") == commit_sha
    release_reconciliation_passed = True if not release_reconciliation else bool(release_reconciliation.get("passed"))
    release_hash_mismatches = _as_list(release_reconciliation.get("hash_mismatches"))
    release_commit_mismatches = _as_list(release_reconciliation.get("commit_mismatches"))
    stale_artifacts = _as_list(artifact_review.get("stale_artifacts"))
    missing_upload_paths = _as_list(upload_review.get("missing_upload_paths"))
    missing_steps = _as_list(upload_review.get("missing_steps"))

    failures: list[dict[str, Any]] = []

    def fail(code: str, message: str, *, details: Any = None) -> None:
        row: dict[str, Any] = {
            "code": code,
            "message": message,
            "recommendation": "Run GitHub Actions for this commit or regenerate the signed local release artifact bundle.",
        }
        if details is not None:
            row["details"] = details
        failures.append(row)

    if not github_proof and not local_proof_ok:
        fail("ARTIFACT_PROOF_MISSING", "No GitHub Actions artifact proof or signed local artifact proof is available.")
    if required_missing:
        fail("REQUIRED_ARTIFACT_MISSING", "Required release artifacts are missing.", details=required_missing)
    if github_actions and str(ci_run_review.get("commit_sha") or commit_sha) != commit_sha:
        fail("CI_COMMIT_SHA_MISMATCH", "GitHub Actions commit SHA does not match the current source commit.")
    if stale_artifacts:
        fail("STALE_ARTIFACT_PRESENT", "Stale generated artifacts are present.", details=stale_artifacts)
    if missing_upload_paths and github_actions:
        fail("CI_UPLOAD_PATH_MISSING", "CI upload path coverage is incomplete.", details=missing_upload_paths)
    if missing_steps and github_actions:
        fail("CI_REQUIRED_STEP_MISSING", "CI is missing required release validation steps.", details=missing_steps)
    if not release_reconciliation_passed:
        fail("RELEASE_ARTIFACT_RECONCILIATION_FAILED", "Release artifact manifest/hash reconciliation failed.")
    if release_hash_mismatches:
        fail("RELEASE_HASH_MISMATCH", "Release artifact hash mismatch detected.", details=release_hash_mismatches)
    if release_commit_mismatches:
        fail("RELEASE_ARTIFACT_COMMIT_MISMATCH", "Release artifact commit mismatch detected.", details=release_commit_mismatches)
    if token_path_leaks:
        fail("TOKEN_PATH_LEAK", "Token file path leaked into artifacts.")
    if temp_path_leaks:
        fail("TEMP_SQL_PATH_LEAK", "Temporary SQL file path leaked into artifacts.")
    if raw_sql_leaks:
        fail("RAW_SQL_BODY_LEAK", "Raw SQL body leaked into default artifacts.")

    return {
        "source": "ci_artifact_reality",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": commit_sha,
        "launch_profile": profile,
        "github_actions": github_actions,
        "workflow_run_id": workflow_run_id,
        "workflow_run_url": workflow_run_url,
        "local_artifact_signature": str(local_proof.get("local_artifact_signature") or ""),
        "local_artifact_proof_path": LOCAL_ARTIFACT_PROOF_REL,
        "artifact_upload_count": len(uploaded_artifacts) if github_proof else int(local_proof.get("artifact_count") or 0),
        "required_artifact_count": len(REQUIRED_LOCAL_ARTIFACTS),
        "missing_required_artifacts": required_missing,
        "release_candidate_summary_exists": (root_path / f"{RELEASE_CANDIDATE_DIR}/release_candidate_summary.json").exists(),
        "launch_readiness_summary_exists": (root_path / f"{LAUNCH_READINESS_DIR}/launch_readiness_summary.json").exists()
        or allow_in_progress_launch_readiness,
        "artifact_hashes_exists": (root_path / f"{RELEASE_CANDIDATE_DIR}/artifact_hashes.json").exists(),
        "artifact_manifest_exists": (root_path / f"{RELEASE_CANDIDATE_DIR}/artifact_manifest.json").exists(),
        "token_path_leak_count": token_path_leaks,
        "temp_sql_path_leak_count": temp_path_leaks,
        "raw_sql_leak_count": raw_sql_leaks,
        "release_artifact_reconciliation_passed": release_reconciliation_passed,
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "production_deployable": False,
        "raw_sql_included": False,
    }


def evaluate_ci_artifact_reality_gate(results: Mapping[str, Any] | None) -> dict[str, Any]:
    results = results or {}
    failures = _as_list(results.get("failures"))
    passed = bool(results.get("passed")) and not failures
    return {
        "source": "ci_artifact_reality_gate_results",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": str(results.get("commit_sha") or ""),
        "passed": passed,
        "failure_count": len(failures),
        "hard_gate_failure_count": len(failures),
        "local_artifact_signature": str(results.get("local_artifact_signature") or ""),
        "workflow_run_id": str(results.get("workflow_run_id") or ""),
        "workflow_run_url": str(results.get("workflow_run_url") or ""),
        "token_path_leak_count": _as_int(results.get("token_path_leak_count")),
        "temp_sql_path_leak_count": _as_int(results.get("temp_sql_path_leak_count")),
        "raw_sql_leak_count": _as_int(results.get("raw_sql_leak_count")),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_ci_artifact_reality_artifacts(
    root: Path | str = ".",
    *,
    profile: str,
    ci_run_review: Mapping[str, Any] | None = None,
    upload_review: Mapping[str, Any] | None = None,
    artifact_review: Mapping[str, Any] | None = None,
    missing_payloads: Iterable[str] = (),
    release_reconciliation: Mapping[str, Any] | None = None,
    allow_in_progress_launch_readiness: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_ci_artifact_reality_results(
        root_path,
        profile=profile,
        ci_run_review=ci_run_review,
        upload_review=upload_review,
        artifact_review=artifact_review,
        missing_payloads=missing_payloads,
        release_reconciliation=release_reconciliation,
        allow_in_progress_launch_readiness=allow_in_progress_launch_readiness,
    )
    gate = evaluate_ci_artifact_reality_gate(results)
    _write_json(root_path / CI_ARTIFACT_REALITY_RESULTS_REL, results)
    _write_json(root_path / CI_ARTIFACT_REALITY_GATE_REL, gate)
    return {
        CI_ARTIFACT_REALITY_RESULTS_REL: results,
        CI_ARTIFACT_REALITY_GATE_REL: gate,
        LOCAL_ARTIFACT_PROOF_REL: _load_json(root_path, LOCAL_ARTIFACT_PROOF_REL),
    }


__all__ = [
    "CI_ARTIFACT_REALITY_GATE_REL",
    "CI_ARTIFACT_REALITY_RESULTS_REL",
    "LOCAL_ARTIFACT_PROOF_REL",
    "build_ci_artifact_reality_results",
    "build_local_artifact_proof",
    "evaluate_ci_artifact_reality_gate",
    "write_ci_artifact_reality_artifacts",
    "write_local_artifact_proof",
]
