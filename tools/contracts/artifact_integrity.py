"""Shared release artifact integrity helpers."""

from __future__ import annotations

from pathlib import Path
import json
import hashlib
from typing import Any, Mapping


ARTIFACT_HASHES_REL = "artifacts/release_candidate/artifact_hashes.json"


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except Exception:
        return 0


def _rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return list(payload)
    if not isinstance(payload, Mapping):
        return []
    for key in ("proof_rows", "rows", "checks", "results", "sections", "gates", "artifacts"):
        value = payload.get(key)
        if isinstance(value, list):
            return list(value)
        if isinstance(value, Mapping):
            return list(value.values())
    return []


def _commit_from_payload(payload: Mapping[str, Any]) -> str:
    for key in ("commit_sha", "source_tree_sha", "git_sha"):
        value = str(payload.get(key) or "")
        if value:
            return value
    for row in _rows(payload):
        if isinstance(row, Mapping):
            value = str(row.get("commit_sha") or row.get("source_tree_sha") or row.get("git_sha") or "")
            if value:
                return value
    return ""


def _hash_index(root: Path) -> dict[str, str]:
    try:
        payload = json.loads((root / ARTIFACT_HASHES_REL).read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = payload.get("hashes") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return {}
    index: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("path") or "")
        sha = str(row.get("sha256") or "")
        if path and sha:
            index[path] = sha
    return index


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_supporting_artifact(
    label: str,
    payload: Any,
    *,
    expected_commit_sha: str = "",
    zero_counter_keys: tuple[str, ...] = (),
    root: Path | str | None = None,
    artifact_rel: str = "",
    require_hash_manifest_entry: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate a producer-backed support artifact without trusting its boolean alone."""

    if not isinstance(payload, Mapping) or not payload:
        return (
            [{
                "section": label,
                "workflow": "Supporting artifact",
                "failure_reason": f"missing {label} proof artifact",
            }],
            {"provided": payload is not None, "passed": False, "row_count": 0},
        )

    rows = _rows(payload)
    reasons: list[str] = []
    artifact_commit_sha = _commit_from_payload(payload)
    failure_count = _as_int(payload.get("failure_count"))

    if not payload.get("producer"):
        reasons.append("missing producer")
    if not payload.get("producer_signature"):
        reasons.append("missing producer_signature")
    if bool(payload.get("raw_sql_included")):
        reasons.append("raw_sql_included=true")
    if not bool(payload.get("passed")):
        reasons.append(str(payload.get("failure_reason") or f"{label} proof did not pass"))
    if failure_count > 0:
        reasons.append(f"failure_count={failure_count}")
    if not rows:
        reasons.append("row-level proof missing")
    if expected_commit_sha:
        if not artifact_commit_sha:
            reasons.append("missing commit_sha")
        elif artifact_commit_sha != expected_commit_sha:
            reasons.append(f"commit_sha mismatch: {artifact_commit_sha}")
    for key in zero_counter_keys:
        if _as_int(payload.get(key)):
            reasons.append(f"{key}={_as_int(payload.get(key))}")
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            reasons.append(f"row {index} is not an object")
            continue
        row_id = str(row.get("id") or row.get("row_id") or index)
        if not row.get("producer"):
            reasons.append(f"row {row_id} missing producer")
        if not row.get("producer_signature"):
            reasons.append(f"row {row_id} missing producer_signature")
        if bool(row.get("raw_sql_included")):
            reasons.append(f"row {row_id} raw_sql_included=true")
        if "passed" in row and not bool(row.get("passed")):
            reasons.append(f"row {row_id} did not pass")
        if expected_commit_sha:
            row_commit = str(row.get("commit_sha") or row.get("source_tree_sha") or row.get("git_sha") or "")
            if not row_commit:
                reasons.append(f"row {row_id} missing commit_sha")
            elif row_commit != expected_commit_sha:
                reasons.append(f"row {row_id} commit_sha mismatch: {row_commit}")

    hash_listed = False
    if artifact_rel and root is not None:
        root_path = Path(root)
        artifact_path = root_path / artifact_rel
        expected_sha = _hash_index(root_path).get(artifact_rel, "")
        actual_sha = _sha256(artifact_path) if artifact_path.exists() else ""
        hash_listed = bool(expected_sha) and bool(actual_sha) and expected_sha == actual_sha
        if require_hash_manifest_entry and not hash_listed:
            reasons.append("artifact hash is missing from release hash manifest")

    summary = {
        "provided": True,
        "passed": not reasons,
        "row_count": len(rows),
        "failure_count": failure_count or len(reasons),
        "artifact_commit_sha": artifact_commit_sha,
        "artifact_hash_listed": hash_listed,
        **{key: _as_int(payload.get(key)) for key in zero_counter_keys},
    }
    if not reasons:
        return [], summary
    return (
        [{
            "section": label,
            "workflow": "Supporting artifact",
            "failure_reason": "; ".join(reasons),
        }],
        summary,
    )


__all__ = ["verify_supporting_artifact"]
