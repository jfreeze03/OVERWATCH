"""Runtime artifact provenance gate for the full app launch bundle.

The lower runtime harness produces render/click/export rows. Producer-written
provenance is required for live/prod launch proof; annotation is kept only as
an internal-fixture repair path and is reported explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

RUNTIME_ARTIFACT_PROVENANCE_REL = f"{FULL_APP_VALIDATION_DIR}/runtime_artifact_provenance_results.json"
RUNTIME_ARTIFACT_PROVENANCE_GATE_REL = f"{LAUNCH_READINESS_DIR}/runtime_artifact_provenance_gate_results.json"

REQUIRED_RUNTIME_ARTIFACT_RELS = (
    f"{FULL_APP_VALIDATION_DIR}/view_results.json",
    f"{FULL_APP_VALIDATION_DIR}/rendered_fragments.json",
    f"{FULL_APP_VALIDATION_DIR}/deterministic_streamlit_render_results.json",
    f"{FULL_APP_VALIDATION_DIR}/browser_render_results.json",
    f"{FULL_APP_VALIDATION_DIR}/browser_smoke_results.json",
    f"{FULL_APP_VALIDATION_DIR}/rendered_ui_leak_scan_results.json",
    f"{FULL_APP_VALIDATION_DIR}/button_click_results.json",
    f"{FULL_APP_VALIDATION_DIR}/settings_action_results.json",
    f"{FULL_APP_VALIDATION_DIR}/live_feature_results.json",
    f"{FULL_APP_VALIDATION_DIR}/export_results.json",
    f"{FULL_APP_VALIDATION_DIR}/download_results.json",
    f"{FULL_APP_VALIDATION_DIR}/case_payload_results.json",
    f"{FULL_APP_VALIDATION_DIR}/query_search_results.json",
    f"{FULL_APP_VALIDATION_DIR}/evidence_loader_call_matrix.json",
    f"{FULL_APP_VALIDATION_DIR}/stress_results.json",
    f"{FULL_APP_VALIDATION_DIR}/summary_board_results.json",
)

ALLOWED_RUNTIME_SOURCES = {
    "rendered_app",
    "clicked_action",
    "browser_snapshot",
    "browser_rendered",
    "deterministic_streamlit_rendered",
    "lower_artifact_rendered",
    "synthetic_safe_fallback",
    "fixture",
}

SOURCE_BY_ARTIFACT = {
    f"{FULL_APP_VALIDATION_DIR}/view_results.json": "rendered_app",
    f"{FULL_APP_VALIDATION_DIR}/rendered_fragments.json": "rendered_app",
    f"{FULL_APP_VALIDATION_DIR}/deterministic_streamlit_render_results.json": "deterministic_streamlit_rendered",
    f"{FULL_APP_VALIDATION_DIR}/browser_render_results.json": "browser_rendered",
    f"{FULL_APP_VALIDATION_DIR}/browser_smoke_results.json": "browser_rendered",
    f"{FULL_APP_VALIDATION_DIR}/rendered_ui_leak_scan_results.json": "rendered_app",
    f"{FULL_APP_VALIDATION_DIR}/button_click_results.json": "clicked_action",
    f"{FULL_APP_VALIDATION_DIR}/settings_action_results.json": "clicked_action",
    f"{FULL_APP_VALIDATION_DIR}/live_feature_results.json": "clicked_action",
    f"{FULL_APP_VALIDATION_DIR}/export_results.json": "clicked_action",
    f"{FULL_APP_VALIDATION_DIR}/download_results.json": "clicked_action",
    f"{FULL_APP_VALIDATION_DIR}/case_payload_results.json": "clicked_action",
    f"{FULL_APP_VALIDATION_DIR}/query_search_results.json": "clicked_action",
    f"{FULL_APP_VALIDATION_DIR}/evidence_loader_call_matrix.json": "clicked_action",
    f"{FULL_APP_VALIDATION_DIR}/stress_results.json": "clicked_action",
    f"{FULL_APP_VALIDATION_DIR}/summary_board_results.json": "rendered_app",
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return {"passed": False, "failure_reason": "malformed_json"}


def _row_container(payload: Any) -> tuple[list[dict[str, Any]], str]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)], "list"
    if isinstance(payload, Mapping):
        for key in ("rows", "results", "actions", "checks", "features", "cases"):
            rows = payload.get(key)
            if isinstance(rows, list):
                machine_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
                if machine_rows:
                    return machine_rows, key
                if any(payload.get(field) is not None for field in ("producer", "source", "skipped", "passed")):
                    return [dict(payload)], "self"
                return [], key
        return [dict(payload)], "self"
    return [], "none"


def _replace_rows(payload: Any, rows: list[dict[str, Any]], container_key: str) -> Any:
    if container_key == "list":
        return rows
    if isinstance(payload, Mapping):
        updated = dict(payload)
        if container_key == "self":
            updated.update(rows[0] if rows else {})
        elif container_key != "none":
            updated[container_key] = rows
        return updated
    return payload


def _sanitize_source(value: object, rel: str) -> str:
    source = str(value or "").strip()
    if source in ALLOWED_RUNTIME_SOURCES:
        return source
    if source in {
        "runtime_section_render",
        "runtime_settings_render",
        "runtime_query_search_render",
        "runtime_render",
    }:
        return "rendered_app"
    if source in {
        "runtime_button_click",
        "runtime_real_loader_spy",
        "runtime_real_loader_spy_matrix",
        "runtime_query_search_click",
        "runtime_export_payload",
        "runtime_stress_sequence",
    }:
        return "clicked_action"
    return SOURCE_BY_ARTIFACT.get(rel, "fixture")


def _is_fixture_mode(source: str, row: Mapping[str, Any]) -> bool:
    return bool(row.get("fixture_mode")) or source == "fixture"


def _profile_requires_live(profile: str) -> bool:
    return profile in {"internal_live", "prod_candidate"}


def _has_profile_waiver() -> bool:
    return False


def _signature(*parts: object) -> str:
    import hashlib

    return hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()


def stamp_runtime_artifact_payload(
    payload: Any,
    *,
    rel: str,
    commit_sha: str,
    launch_profile: str,
    generated_at: str,
) -> Any:
    """Return payload with each row stamped with the release provenance fields."""

    rows, container_key = _row_container(payload)
    if not rows:
        return payload
    stamped: list[dict[str, Any]] = []
    default_source = SOURCE_BY_ARTIFACT.get(rel, "fixture")
    for index, row in enumerate(rows):
        next_row = dict(row)
        old_source = str(next_row.get("source") or "")
        source = _sanitize_source(old_source, rel)
        source_changed = bool(old_source and old_source != source)
        if old_source and old_source != source:
            next_row.setdefault("runtime_source", old_source)
        producer = str(next_row.get("producer") or "full_app_runtime_validation")
        final_source = source or default_source
        missing_fields = [
            field
            for field in ("producer", "generated_at", "source", "launch_profile", "commit_sha", "producer_signature")
            if not next_row.get(field)
        ]
        next_row["producer"] = producer
        next_row["generated_at"] = str(next_row.get("generated_at") or generated_at)
        next_row["source"] = final_source
        next_row["fixture_mode"] = _is_fixture_mode(final_source, next_row)
        next_row["launch_profile"] = str(next_row.get("launch_profile") or launch_profile)
        next_row["commit_sha"] = str(next_row.get("commit_sha") or commit_sha)
        next_row["raw_sql_included"] = bool(next_row.get("raw_sql_included", False))
        next_row.setdefault("runtime_artifact_row_index", index)
        next_row["provenance_origin"] = str(
            next_row.get("provenance_origin")
            or ("annotated" if missing_fields or source_changed else "producer")
        )
        next_row["producer_signature"] = str(
            next_row.get("producer_signature")
            or _signature(producer, final_source, rel, index, next_row.get("commit_sha"))
        )
        next_row["source_rewritten"] = source_changed
        stamped.append(next_row)
    return _replace_rows(payload, stamped, container_key)


def annotate_runtime_artifacts(root: Path | str = ".", *, launch_profile: str = "internal_fixture") -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = _git_commit(root_path)
    generated_at = _now()
    updated: dict[str, Any] = {}
    for rel in REQUIRED_RUNTIME_ARTIFACT_RELS:
        path = root_path / rel
        payload = _load_json(path)
        if payload is None:
            continue
        stamped = stamp_runtime_artifact_payload(
            payload,
            rel=rel,
            commit_sha=commit_sha,
            launch_profile=launch_profile,
            generated_at=generated_at,
        )
        _write_json(path, stamped)
        updated[rel] = stamped
    return updated


def build_runtime_artifact_provenance(
    root: Path | str = ".",
    *,
    launch_profile: str = "internal_fixture",
    required_rels: Iterable[str] = REQUIRED_RUNTIME_ARTIFACT_RELS,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    commit_sha = _git_commit(root_path)
    generated_at = _now()

    for rel in required_rels:
        path = root_path / rel
        payload = _load_json(path)
        if payload is None:
            failure = {
                "artifact": rel,
                "row_index": -1,
                "code": "MISSING_RUNTIME_ARTIFACT",
                "failure_reason": "required runtime artifact is missing",
            }
            failures.append(failure)
            rows.append(
                {
                    "artifact": rel,
                    "row_index": -1,
                    "producer": "",
                    "generated_at": generated_at,
                    "source": "",
                    "fixture_mode": False,
                    "launch_profile": launch_profile,
                    "commit_sha": commit_sha,
                    "raw_sql_included": False,
                    "passed": False,
                    "failure_reason": failure["failure_reason"],
                }
            )
            continue

        artifact_rows, _container_key = _row_container(payload)
        if not artifact_rows:
            failure = {
                "artifact": rel,
                "row_index": -1,
                "code": "EMPTY_RUNTIME_ARTIFACT",
                "failure_reason": "runtime artifact has no machine-readable rows",
            }
            failures.append(failure)
            continue

        for index, artifact_row in enumerate(artifact_rows):
            row = dict(artifact_row)
            producer = str(row.get("producer") or "")
            source = str(row.get("source") or "")
            row_commit = str(row.get("commit_sha") or "")
            raw_sql_included = bool(row.get("raw_sql_included", False))
            fixture_mode = bool(row.get("fixture_mode", False))
            provenance_origin = str(row.get("provenance_origin") or "missing")
            producer_signature = str(row.get("producer_signature") or "")
            source_rewritten = bool(row.get("source_rewritten"))
            row_failures: list[str] = []
            if not producer:
                row_failures.append("missing_producer")
            if source not in ALLOWED_RUNTIME_SOURCES:
                row_failures.append("invalid_source")
            if provenance_origin == "missing":
                row_failures.append("missing_provenance_origin")
            if _profile_requires_live(launch_profile) and provenance_origin != "producer":
                row_failures.append("provenance_annotation_requires_waiver")
            if source_rewritten and _profile_requires_live(launch_profile):
                row_failures.append("source_rewrite_requires_waiver")
            if _profile_requires_live(launch_profile) and fixture_mode and not _has_profile_waiver():
                row_failures.append("fixture_only_runtime_artifact_requires_waiver")
            if raw_sql_included:
                row_failures.append("raw_sql_included")
            if row_commit and commit_sha and row_commit != commit_sha:
                row_failures.append("commit_sha_mismatch")
            if not row_commit:
                row_failures.append("missing_commit_sha")
            if launch_profile == "prod_candidate" and not producer_signature:
                row_failures.append("missing_producer_signature")

            passed = not row_failures
            failure_reason = "; ".join(row_failures)
            provenance_row = {
                "artifact": rel,
                "row_index": index,
                "producer": producer,
                "generated_at": str(row.get("generated_at") or generated_at),
                "source": source,
                "section": str(row.get("section") or row.get("surface") or ""),
                "workflow": str(row.get("workflow") or row.get("item") or ""),
                "surface": str(row.get("surface") or row.get("section") or ""),
                "fixture_mode": fixture_mode,
                "launch_profile": str(row.get("launch_profile") or launch_profile),
                "commit_sha": row_commit,
                "raw_sql_included": raw_sql_included,
                "provenance_origin": provenance_origin,
                "producer_signature": producer_signature,
                "source_rewritten": source_rewritten,
                "runtime_artifact_row_index": row.get("runtime_artifact_row_index", index),
                "passed": passed,
                "failure_reason": failure_reason,
            }
            rows.append(provenance_row)
            if not passed:
                failures.append(
                    {
                        "artifact": rel,
                        "row_index": index,
                        "code": "RUNTIME_ARTIFACT_PROVENANCE_FAILED",
                        "failure_reason": failure_reason,
                    }
                )

    return {
        "source": "runtime_artifact_provenance_results",
        "generated_at": generated_at,
        "passed": not failures,
        "launch_profile": launch_profile,
        "artifact_count": len(tuple(required_rels)),
        "row_count": len(rows),
        "failure_count": len(failures),
        "failures": failures,
        "rows": rows,
        "raw_sql_included": False,
    }


def evaluate_runtime_artifact_provenance_gate(payload: object) -> dict[str, Any]:
    results = _as_mapping(payload)
    failures = _as_list(results.get("failures"))
    if not bool(results.get("passed", False)) and not failures:
        failures = [{"code": "RUNTIME_ARTIFACT_PROVENANCE_FAILED"}]
    return {
        "source": "runtime_artifact_provenance_gate_results",
        "generated_at": _now(),
        "passed": bool(results.get("passed", False)) and not failures,
        "failure_count": len(failures),
        "failures": failures,
        "row_count": int(results.get("row_count") or 0),
        "fixture_only_row_count": sum(
            1 for row in _as_list(results.get("rows")) if bool(_as_mapping(row).get("fixture_mode"))
        ),
        "annotated_row_count": sum(
            1 for row in _as_list(results.get("rows")) if _as_mapping(row).get("provenance_origin") == "annotated"
        ),
        "source_rewrite_count": sum(
            1 for row in _as_list(results.get("rows")) if bool(_as_mapping(row).get("source_rewritten"))
        ),
        "raw_sql_included": False,
    }


def write_runtime_artifact_provenance_artifacts(
    root: Path | str = ".",
    *,
    launch_profile: str = "internal_fixture",
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    annotate_runtime_artifacts(root_path, launch_profile=launch_profile)
    results = build_runtime_artifact_provenance(root_path, launch_profile=launch_profile)
    gate = evaluate_runtime_artifact_provenance_gate(results)
    artifacts = {
        RUNTIME_ARTIFACT_PROVENANCE_REL: results,
        RUNTIME_ARTIFACT_PROVENANCE_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "ALLOWED_RUNTIME_SOURCES",
    "REQUIRED_RUNTIME_ARTIFACT_RELS",
    "RUNTIME_ARTIFACT_PROVENANCE_GATE_REL",
    "RUNTIME_ARTIFACT_PROVENANCE_REL",
    "annotate_runtime_artifacts",
    "build_runtime_artifact_provenance",
    "evaluate_runtime_artifact_provenance_gate",
    "stamp_runtime_artifact_payload",
    "write_runtime_artifact_provenance_artifacts",
]
