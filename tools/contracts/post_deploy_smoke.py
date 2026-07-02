"""Post-deploy smoke checks for the production release candidate.

The smoke check consumes already-produced runtime artifacts and gates. It is a
release closure check, not a UI renderer, and therefore never stores raw SQL,
token paths, temp SQL paths, or source-object internals.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from tools.contracts.full_app_launch_gauntlet import PRIMARY_SECTIONS


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

POST_DEPLOY_SMOKE_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/post_deploy_smoke_results.json"
POST_DEPLOY_SMOKE_GATE_REL = f"{LAUNCH_READINESS_DIR}/post_deploy_smoke_gate_results.json"

PRODUCER = "post_deploy_smoke"


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


def _load_json(root: Path, rel: str) -> Any:
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        raw_rows = value.get("rows")
        if isinstance(raw_rows, list):
            return [row for row in raw_rows if isinstance(row, Mapping)]
    return []


def _as_int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _has_command_brief(row: Mapping[str, Any]) -> bool:
    if _as_int(row.get("command_brief_count")) == 1:
        return True
    for field in ("html_fragment", "rendered_text", "first_viewport_text"):
        value = row.get(field)
        if isinstance(value, str) and "ow-kit-command-brief" in value:
            return True
    return False


def _signature(row: Mapping[str, Any]) -> str:
    payload = {
        "producer": PRODUCER,
        "check": row.get("check"),
        "passed": row.get("passed"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _row(root: Path, *, check: str, passed: bool, failure_reason: str = "", **details: Any) -> dict[str, Any]:
    row = {
        "producer": PRODUCER,
        "producer_signature": "",
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": _git_sha(root),
        "source": "post_deploy_smoke",
        "runtime_source": "release_artifact_gate",
        "section": "Production Deployment",
        "workflow": "Post-deploy smoke",
        "check": check,
        "passed": passed,
        "failure_reason": "" if passed else failure_reason,
        "raw_sql_included": False,
        **details,
    }
    row["producer_signature"] = _signature(row)
    return row


def _gate(root: Path, rel: str) -> Mapping[str, Any]:
    return _mapping(_load_json(root, rel))


def _payload_or_file(root: Path, payloads: Mapping[str, Any], rel: str) -> Any:
    if rel in payloads:
        return payloads[rel]
    basename = Path(rel).stem
    if basename in payloads:
        return payloads[basename]
    return _load_json(root, rel)


def build_post_deploy_smoke_results(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    payload_map = payloads or {}
    view_rows = _rows(_payload_or_file(root_path, payload_map, f"{FULL_APP_VALIDATION_DIR}/view_results.json"))
    first_paint = _mapping(
        _payload_or_file(root_path, payload_map, f"{FULL_APP_VALIDATION_DIR}/first_paint_performance_results.json")
    )
    first_paint_rows = _rows(first_paint)
    rendered_leak_gate = _mapping(
        _payload_or_file(root_path, payload_map, f"{LAUNCH_READINESS_DIR}/rendered_ui_leak_gate_results.json")
    )
    app_entry_gate = _mapping(
        _payload_or_file(root_path, payload_map, f"{LAUNCH_READINESS_DIR}/app_entry_smoke_gate_results.json")
    )
    settings_gate = _mapping(
        _payload_or_file(root_path, payload_map, f"{LAUNCH_READINESS_DIR}/settings_live_feature_gate_results.json")
    )
    export_gate = _mapping(
        _payload_or_file(root_path, payload_map, f"{LAUNCH_READINESS_DIR}/export_download_gate_results.json")
    )
    action_gate = _mapping(
        _payload_or_file(root_path, payload_map, f"{LAUNCH_READINESS_DIR}/action_click_gate_results.json")
    )

    rows: list[dict[str, Any]] = []
    for section in PRIMARY_SECTIONS:
        section_views = [row for row in view_rows if row.get("section") == section]
        command_brief_present = any(_has_command_brief(row) for row in section_views)
        first_paint_row = next((row for row in first_paint_rows if row.get("section") == section), {})
        budget_ok = bool(first_paint_row) and bool(first_paint_row.get("passed"))
        rows.append(
            _row(
                root_path,
                check=f"primary_section::{section}",
                passed=command_brief_present and budget_ok,
                failure_reason="Primary section CommandBrief or first-paint budget proof is missing.",
                section_name=section,
                command_brief_present=command_brief_present,
                first_paint_row_present=bool(first_paint_row),
                first_paint_passed=budget_ok,
            )
        )

    smoke_checks = (
        ("app_entry_smoke", app_entry_gate, "App entry smoke gate failed or is missing."),
        ("settings_setup_health", settings_gate, "Settings/Admin Setup Health gate failed or is missing."),
        ("export_case_files", export_gate, "Export/download/case gate failed or is missing."),
        ("exact_action_clicks", action_gate, "Action click gate failed or is missing."),
        ("daily_rendered_leaks", rendered_leak_gate, "Rendered leak gate failed or is missing."),
    )
    for check, gate, failure_reason in smoke_checks:
        rows.append(
            _row(
                root_path,
                check=check,
                passed=bool(gate.get("passed")),
                failure_reason=failure_reason,
                gate_failure_count=_as_int(gate.get("failure_count")),
            )
        )

    rows.append(
        _row(
            root_path,
            check="release_artifact_hash_stability",
            passed=(root_path / "artifacts" / "release_candidate" / "artifact_hashes.json").exists(),
            failure_reason="Release artifact hash manifest is missing.",
            artifact_path="artifacts/release_candidate/artifact_hashes.json",
        )
    )
    failures = [row for row in rows if not bool(row.get("passed"))]
    return {
        "source": "post_deploy_smoke_results",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": _git_sha(root_path),
        "passed": not failures,
        "failure_count": len(failures),
        "row_count": len(rows),
        "primary_section_count": len(PRIMARY_SECTIONS),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_post_deploy_smoke_gate(payload: object) -> dict[str, Any]:
    results = payload if isinstance(payload, Mapping) else {}
    failures = list(results.get("failures") or [])
    if not results:
        failures = [{"code": "POST_DEPLOY_SMOKE_RESULTS_MISSING"}]
    elif not bool(results.get("passed")) and not failures:
        failures = [{"code": "POST_DEPLOY_SMOKE_FAILED"}]
    return {
        "source": "post_deploy_smoke_gate_results",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "passed": not failures and bool(results.get("passed")),
        "post_deploy_smoke_passed": not failures and bool(results.get("passed")),
        "failure_count": len(failures),
        "row_count": _as_int(results.get("row_count")),
        "primary_section_count": _as_int(results.get("primary_section_count")),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_post_deploy_smoke_artifacts(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_post_deploy_smoke_results(root_path, payloads=payloads)
    gate = evaluate_post_deploy_smoke_gate(results)
    artifacts = {
        POST_DEPLOY_SMOKE_RESULTS_REL: results,
        POST_DEPLOY_SMOKE_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        path = root_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifacts


if __name__ == "__main__":
    written = write_post_deploy_smoke_artifacts(Path("."))
    gate = written[POST_DEPLOY_SMOKE_GATE_REL]
    print(json.dumps(gate, indent=2, sort_keys=True))
    raise SystemExit(0 if gate.get("passed") else 1)


__all__ = [
    "POST_DEPLOY_SMOKE_GATE_REL",
    "POST_DEPLOY_SMOKE_RESULTS_REL",
    "build_post_deploy_smoke_results",
    "evaluate_post_deploy_smoke_gate",
    "write_post_deploy_smoke_artifacts",
]
