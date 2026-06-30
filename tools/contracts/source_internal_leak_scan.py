"""Production source and artifact leak scan for daily app surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.contracts.rendered_ui_leak_scan import (
    FORBIDDEN_TOKENS,
    scan_rendered_ui,
)


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

SOURCE_INTERNAL_LEAK_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/source_internal_leak_scan_results.json"
SOURCE_INTERNAL_LEAK_GATE_REL = f"{LAUNCH_READINESS_DIR}/source_internal_leak_scan_gate_results.json"

DAILY_SOURCE_FILES = (
    ".overwatch_final/layout.py",
    ".overwatch_final/filters.py",
    ".overwatch_final/section_dispatch.py",
    ".overwatch_final/navigation.py",
    ".overwatch_final/route_registry.py",
    ".overwatch_final/sections/section_command_rendering.py",
    ".overwatch_final/sections/decision_workspace_view_model.py",
)

SOURCE_BLOCKED_PHRASES = (
    "diagnostic card",
    "internal test",
    "TODO visible",
    "lorem",
    "StreamlitAPIException",
    "Traceback",
    "DATABASE, USER, ROLE, AND QUERY COST VIEWS ARE ALLOCATED ESTIMATES",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_payloads(root: Path, rels: Iterable[str]) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for rel in rels:
        path = root / rel
        if not path.exists():
            continue
        try:
            payloads[rel] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payloads[rel] = {"passed": False, "failure_reason": "malformed_json"}
    return payloads


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _scan_daily_source(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for rel in DAILY_SOURCE_FILES:
        path = root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for phrase in SOURCE_BLOCKED_PHRASES:
            if phrase in text:
                findings.append({"path": rel, "token": phrase, "scope": "daily_source"})
        # Raw object tokens are allowed in admin/setup tooling and SQL modules, but
        # daily render files should not include user-facing labels with them.
        for token in ("ACCOUNT_USAGE", "INFORMATION_SCHEMA", "CREATE OR REPLACE", "CALL SP_"):
            if token in text:
                findings.append({"path": rel, "token": token, "scope": "daily_source"})
    return findings


def build_source_internal_leak_scan(root: Path, payloads: Mapping[str, Any]) -> dict[str, Any]:
    rendered, rendered_failure_payload = scan_rendered_ui(payloads)
    rendered_failures = _as_list(rendered.get("failures"))
    if not rendered_failures:
        rendered_failures = _as_list(rendered_failure_payload.get("failures"))
    source_findings = _scan_daily_source(root)
    failures = [*rendered_failures]
    failures.extend(
        {
            "code": "SOURCE_DAILY_INTERNAL_TOKEN",
            "path": row["path"],
            "token_id": f"blocked_token_{index + 1}",
        }
        for index, row in enumerate(source_findings)
    )
    return {
        "source": "source_internal_leak_scan_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "rendered_daily_leak_count": int(rendered.get("failure_count") or 0),
        "source_internal_leak_count": len(source_findings),
        "blocked_token_count": len(set(FORBIDDEN_TOKENS) | set(SOURCE_BLOCKED_PHRASES)),
        "findings": [
            {"path": row["path"], "token_id": f"blocked_token_{index + 1}", "scope": row["scope"]}
            for index, row in enumerate(source_findings)
        ],
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_source_internal_leak_scan_gate(payload: object) -> dict[str, Any]:
    scan = _as_mapping(payload)
    failures = _as_list(scan.get("failures"))
    if not bool(scan.get("passed", False)) and not failures:
        failures = [{"code": "SOURCE_INTERNAL_LEAK_SCAN_FAILED"}]
    return {
        "source": "source_internal_leak_scan_gate_results",
        "generated_at": _now(),
        "passed": bool(scan.get("passed", False)) and not failures,
        "failure_count": len(failures),
        "internal_wording_leak_count": int(scan.get("source_internal_leak_count") or 0),
        "diagnostic_leak_count": int(scan.get("rendered_daily_leak_count") or 0),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_source_internal_leak_scan_artifacts(root: Path | str = ".", payloads: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payloads is None:
        payloads = _load_payloads(
            root_path,
            (
                "artifacts/full_app_validation/view_results.json",
                "artifacts/full_app_validation/export_results.json",
                "artifacts/full_app_validation/rendered_formula_results.json",
            ),
        )
    results = build_source_internal_leak_scan(root_path, payloads)
    _write_json(root_path / SOURCE_INTERNAL_LEAK_RESULTS_REL, results)
    return {SOURCE_INTERNAL_LEAK_RESULTS_REL: results}


__all__ = [
    "DAILY_SOURCE_FILES",
    "SOURCE_INTERNAL_LEAK_GATE_REL",
    "SOURCE_INTERNAL_LEAK_RESULTS_REL",
    "build_source_internal_leak_scan",
    "evaluate_source_internal_leak_scan_gate",
    "write_source_internal_leak_scan_artifacts",
]
