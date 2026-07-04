"""Release artifact reality verifier.

This producer turns cross-artifact trust checks into a first-class release gate.
It opens artifact files from disk, verifies producer provenance, validates
commit/hash alignment, and rejects boolean-only or malformed proof.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
RELEASE_CANDIDATE_DIR = "artifacts/release_candidate"

ARTIFACT_INTEGRITY_RESULTS_REL = f"{FULL_APP_DIR}/artifact_integrity_results.json"
ARTIFACT_INTEGRITY_GATE_REL = f"{LAUNCH_READINESS_DIR}/artifact_integrity_gate_results.json"
ARTIFACT_HASHES_REL = f"{RELEASE_CANDIDATE_DIR}/artifact_hashes.json"

PRODUCER = "artifact_verifier"

FORBIDDEN_DEFAULT_TOKENS = (
    "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS",
    "ACCOUNT_USAGE.CREDENTIALS",
    "token_file_path",
    "token contents",
    "temp SQL path",
    "raw SQL body",
    "CREDENTIAL_ID",
    "RAW_USER_ID",
    "USER_ID",
    "Traceback (most recent call last)",
    "StreamlitAPIException",
    "SnowflakeSQLException",
)

DEFAULT_RELEASE_BLOCKING_ARTIFACTS = (
    "artifacts/full_app_validation/access_control_runtime_results.json",
    "artifacts/full_app_validation/cost_overview_no_autoload_results.json",
    "artifacts/full_app_validation/query_search_autorun_results.json",
    "artifacts/full_app_validation/targeted_evidence_sql_pushdown_results.json",
    "artifacts/full_app_validation/query_boundary_lint_results.json",
    "artifacts/full_app_validation/first_paint_slo_results.json",
    "artifacts/full_app_validation/performance_budget_results.json",
    "artifacts/full_app_validation/runtime_event_ledger_results.json",
    "artifacts/full_app_validation/route_action_replay_results.json",
    "artifacts/full_app_validation/export_case_parity_results.json",
    "artifacts/launch_readiness/access_control_runtime_gate_results.json",
    "artifacts/launch_readiness/cost_overview_no_autoload_gate_results.json",
    "artifacts/launch_readiness/query_search_autorun_gate_results.json",
    "artifacts/launch_readiness/targeted_evidence_sql_pushdown_gate_results.json",
    "artifacts/launch_readiness/query_boundary_lint_gate_results.json",
    "artifacts/launch_readiness/first_paint_slo_gate_results.json",
    "artifacts/launch_readiness/performance_budget_gate_results.json",
    "artifacts/launch_readiness/runtime_event_ledger_gate_results.json",
    "artifacts/launch_readiness/route_action_replay_gate_results.json",
    "artifacts/launch_readiness/export_case_parity_gate_results.json",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except Exception:
        return 0


def _git_commit(root: Path) -> str:
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


def _producer_signature() -> str:
    try:
        body = Path(__file__).read_bytes()
    except OSError:
        body = PRODUCER.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> tuple[Any, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except FileNotFoundError:
        return None, "artifact file missing"
    except json.JSONDecodeError as exc:
        return None, f"artifact JSON is malformed: {exc.msg}"
    except OSError as exc:
        return None, f"artifact could not be read: {exc.__class__.__name__}"


def _hash_index(root: Path) -> dict[str, str]:
    payload, _error = _load_json(root / ARTIFACT_HASHES_REL)
    rows = payload.get("hashes") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return {}
    index: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        rel = str(row.get("path") or "")
        sha = str(row.get("sha256") or "")
        if rel and sha:
            index[rel] = sha
    return index


def _proof_rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    row_keys = (
        "proof_rows",
        "rows",
        "checks",
        "results",
        "sections",
        "gates",
        "artifacts",
        "first_paint_rows",
        "query_budget_rows",
        "events",
        "surfaces",
        "actions",
    )
    rows: list[Mapping[str, Any]] = []
    for key in row_keys:
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, Mapping))
        elif isinstance(value, Mapping):
            rows.extend(row for row in value.values() if isinstance(row, Mapping))
    return rows


def _artifact_commit(payload: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    for key in ("commit_sha", "source_tree_sha", "git_sha", "current_commit_sha"):
        value = str(payload.get(key) or "")
        if value:
            return value
    for row in rows:
        for key in ("commit_sha", "source_tree_sha", "git_sha", "current_commit_sha"):
            value = str(row.get(key) or "")
            if value:
                return value
    return ""


def _row_id(row: Mapping[str, Any], index: int) -> str:
    for key in ("row_id", "id", "validation_id", "stable_key", "gate", "check", "section", "path"):
        value = str(row.get(key) or "")
        if value:
            return value
    return f"row[{index}]"


def _serialized(payload: Any) -> str:
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except TypeError:
        return str(payload)


def verify_artifact(
    root: Path | str,
    rel: str,
    *,
    expected_commit_sha: str = "",
    hash_index: Mapping[str, str] | None = None,
    require_hash_manifest_entry: bool = True,
    forbidden_tokens: Iterable[str] = FORBIDDEN_DEFAULT_TOKENS,
) -> dict[str, Any]:
    """Open and validate one release artifact from disk."""

    root_path = Path(root).resolve()
    artifact_path = root_path / rel
    payload, load_error = _load_json(artifact_path)
    expected_sha = str((hash_index or {}).get(rel) or "")
    actual_sha = _sha256(artifact_path) if artifact_path.exists() and artifact_path.is_file() else ""
    reasons: list[str] = []
    if load_error:
        reasons.append(load_error)
    if require_hash_manifest_entry:
        if not expected_sha:
            reasons.append("artifact hash is missing from release hash manifest")
        elif actual_sha != expected_sha:
            reasons.append("artifact hash mismatch")

    payload_mapping = payload if isinstance(payload, Mapping) else {}
    rows = _proof_rows(payload)
    artifact_commit = _artifact_commit(payload_mapping, rows) if payload_mapping else ""
    failure_count = _as_int(payload_mapping.get("failure_count")) if payload_mapping else 0
    forbidden_hits: list[str] = []
    if payload is not None:
        text = _serialized(payload)
        forbidden_hits = sorted({token for token in forbidden_tokens if token and token in text})

    if not isinstance(payload, Mapping):
        if payload is not None:
            reasons.append("artifact root is not an object")
    else:
        if not payload_mapping.get("producer"):
            reasons.append("missing producer")
        if not payload_mapping.get("producer_signature"):
            reasons.append("missing producer_signature")
        if not bool(payload_mapping.get("passed")):
            reasons.append(str(payload_mapping.get("failure_reason") or "artifact did not pass"))
        if failure_count > 0:
            reasons.append(f"failure_count={failure_count}")
        if bool(payload_mapping.get("raw_sql_included")):
            reasons.append("raw_sql_included=true")
        if not rows:
            reasons.append("row-level proof missing")
        if expected_commit_sha:
            if not artifact_commit:
                reasons.append("missing commit_sha")
            elif artifact_commit != expected_commit_sha:
                reasons.append(f"commit_sha mismatch: {artifact_commit}")
    if forbidden_hits:
        reasons.append(f"forbidden token(s) present: {', '.join(forbidden_hits[:5])}")

    row_failures: list[str] = []
    for index, row in enumerate(rows):
        rid = _row_id(row, index)
        if not row.get("producer"):
            row_failures.append(f"{rid} missing producer")
        if not row.get("producer_signature"):
            row_failures.append(f"{rid} missing producer_signature")
        if bool(row.get("raw_sql_included")):
            row_failures.append(f"{rid} raw_sql_included=true")
        if "passed" in row and not bool(row.get("passed")):
            row_failures.append(f"{rid} did not pass")
        if expected_commit_sha:
            row_commit = str(
                row.get("commit_sha")
                or row.get("source_tree_sha")
                or row.get("git_sha")
                or row.get("current_commit_sha")
                or ""
            )
            if not row_commit:
                row_failures.append(f"{rid} missing commit_sha")
            elif row_commit != expected_commit_sha:
                row_failures.append(f"{rid} commit_sha mismatch: {row_commit}")
    reasons.extend(row_failures[:20])

    return {
        "row_id": rel,
        "artifact_path": rel,
        "artifact_exists": artifact_path.exists(),
        "json_parsed": payload is not None and not load_error,
        "artifact_sha256": actual_sha,
        "expected_sha256": expected_sha,
        "artifact_hash_listed": bool(expected_sha),
        "artifact_hash_matched": bool(expected_sha and actual_sha == expected_sha),
        "artifact_commit_sha": artifact_commit,
        "expected_commit_sha": expected_commit_sha,
        "same_commit_sha": bool(expected_commit_sha and artifact_commit == expected_commit_sha),
        "producer": str(payload_mapping.get("producer") or ""),
        "producer_signature": str(payload_mapping.get("producer_signature") or ""),
        "artifact_passed": bool(payload_mapping.get("passed")),
        "artifact_failure_count": failure_count,
        "proof_row_count": len(rows),
        "raw_sql_included": bool(payload_mapping.get("raw_sql_included")),
        "forbidden_token_count": len(forbidden_hits),
        "forbidden_tokens": forbidden_hits,
        "passed": not reasons,
        "failure_reason": "; ".join(dict.fromkeys(reasons)),
    }


def build_artifact_integrity_results(
    root: Path | str = ".",
    *,
    required_artifacts: Sequence[str] = DEFAULT_RELEASE_BLOCKING_ARTIFACTS,
    expected_commit_sha: str = "",
    require_hash_manifest_entry: bool = True,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = expected_commit_sha or _git_commit(root_path)
    indexes = _hash_index(root_path)
    rows = [
        verify_artifact(
            root_path,
            rel,
            expected_commit_sha=commit_sha,
            hash_index=indexes,
            require_hash_manifest_entry=require_hash_manifest_entry,
        )
        for rel in required_artifacts
    ]
    failures = [row for row in rows if not bool(row.get("passed"))]
    signature = _producer_signature()
    return {
        "source": "artifact_integrity_results",
        "producer": PRODUCER,
        "producer_signature": signature,
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha,
        "passed": not failures,
        "failure_count": len(failures),
        "verified_artifact_count": len(rows),
        "missing_artifact_count": sum(1 for row in rows if not bool(row.get("artifact_exists"))),
        "hash_mismatch_count": sum(
            1 for row in rows
            if bool(row.get("artifact_hash_listed")) and not bool(row.get("artifact_hash_matched"))
        ),
        "forbidden_token_count": sum(_as_int(row.get("forbidden_token_count")) for row in rows),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_artifact_integrity_gate(results: Mapping[str, Any]) -> dict[str, Any]:
    signature = _producer_signature()
    rows = [
        {
            "row_id": str(row.get("row_id") or row.get("artifact_path") or ""),
            "artifact_path": str(row.get("artifact_path") or ""),
            "producer": PRODUCER,
            "producer_signature": signature,
            "commit_sha": str(results.get("commit_sha") or ""),
            "passed": bool(row.get("passed")),
            "failure_reason": str(row.get("failure_reason") or ""),
            "raw_sql_included": False,
        }
        for row in _proof_rows(results)
    ]
    failures = [row for row in rows if not bool(row.get("passed"))]
    return {
        "source": "artifact_integrity_gate_results",
        "producer": PRODUCER,
        "producer_signature": signature,
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": str(results.get("commit_sha") or ""),
        "passed": bool(results.get("passed")) and not failures,
        "failure_count": len(failures),
        "verified_artifact_count": _as_int(results.get("verified_artifact_count")),
        "missing_artifact_count": _as_int(results.get("missing_artifact_count")),
        "hash_mismatch_count": _as_int(results.get("hash_mismatch_count")),
        "forbidden_token_count": _as_int(results.get("forbidden_token_count")),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_artifact_integrity_artifacts(
    root: Path | str = ".",
    *,
    required_artifacts: Sequence[str] = DEFAULT_RELEASE_BLOCKING_ARTIFACTS,
    require_hash_manifest_entry: bool = True,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_artifact_integrity_results(
        root_path,
        required_artifacts=required_artifacts,
        require_hash_manifest_entry=require_hash_manifest_entry,
    )
    gate = build_artifact_integrity_gate(results)
    _write_json(root_path / ARTIFACT_INTEGRITY_RESULTS_REL, results)
    _write_json(root_path / ARTIFACT_INTEGRITY_GATE_REL, gate)
    return {
        ARTIFACT_INTEGRITY_RESULTS_REL: results,
        ARTIFACT_INTEGRITY_GATE_REL: gate,
    }


def main() -> int:
    artifacts = write_artifact_integrity_artifacts(Path.cwd())
    gate = artifacts[ARTIFACT_INTEGRITY_GATE_REL]
    return 0 if bool(gate.get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_INTEGRITY_GATE_REL",
    "ARTIFACT_INTEGRITY_RESULTS_REL",
    "DEFAULT_RELEASE_BLOCKING_ARTIFACTS",
    "build_artifact_integrity_gate",
    "build_artifact_integrity_results",
    "verify_artifact",
    "write_artifact_integrity_artifacts",
]
