"""Export, download, and case-payload launch proof."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping

from tools.contracts.full_app_launch_gauntlet import (
    DOWNLOAD_RESULTS_REL,
    EXPORT_DOWNLOAD_GATE_REL,
    build_download_results,
)


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
CASE_PAYLOAD_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/case_payload_results.json"
EXPORT_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/export_results.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_json(root: Path, rel: str) -> Any:
    path = root / rel
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def evaluate_export_download_gate(
    export_payload: object,
    download_payload: object,
    case_rows: object,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    export_summary = _as_mapping(export_payload)
    export_rows = _as_list(export_payload)
    download_summary = _as_mapping(download_payload)
    case_payload_rows = _as_list(case_rows)
    if export_rows and not export_summary:
        export_summary = {
            "passed": all(bool(_as_mapping(row).get("passed", True)) for row in export_rows),
            "export_count": len(export_rows),
            "failure_count": sum(1 for row in export_rows if not bool(_as_mapping(row).get("passed", True))),
        }
    for artifact, payload in ((EXPORT_RESULTS_REL, export_summary), (DOWNLOAD_RESULTS_REL, download_summary)):
        if not bool(payload.get("passed", True)):
            failures.append(
                {
                    "code": "EXPORT_DOWNLOAD_ARTIFACT_FAILED",
                    "artifact": artifact,
                    "failure_count": int(payload.get("failure_count") or 1),
                }
            )
    for row in case_payload_rows:
        if not isinstance(row, Mapping):
            continue
        missing = [field for field in ("section", "workflow", "scope", "target", "freshness", "source", "summary", "row_count") if not row.get(field)]
        if missing or not bool(row.get("passed", True)):
            failures.append(
                {
                    "code": "CASE_PAYLOAD_FAILED",
                    "section": row.get("section"),
                    "missing_fields": missing,
                }
            )
    return {
        "source": "export_download_gate_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "export_count": int(export_summary.get("export_count") or len(export_rows)),
        "download_count": int(download_summary.get("download_count") or 0),
        "case_payload_count": len(case_payload_rows),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_export_download_artifacts(root: Path | str = ".", payloads: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payloads is None:
        payloads = {
            EXPORT_RESULTS_REL: _load_json(root_path, EXPORT_RESULTS_REL),
            CASE_PAYLOAD_RESULTS_REL: _load_json(root_path, CASE_PAYLOAD_RESULTS_REL),
        }
    download_payload = build_download_results(payloads, root_path)
    _write_json(root_path / DOWNLOAD_RESULTS_REL, download_payload)
    return {DOWNLOAD_RESULTS_REL: download_payload}


__all__ = [
    "CASE_PAYLOAD_RESULTS_REL",
    "DOWNLOAD_RESULTS_REL",
    "EXPORT_DOWNLOAD_GATE_REL",
    "EXPORT_RESULTS_REL",
    "evaluate_export_download_gate",
    "write_export_download_artifacts",
]
