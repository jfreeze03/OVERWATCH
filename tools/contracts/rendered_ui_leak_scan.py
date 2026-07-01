"""Rendered daily UI leak scanner.

The scanner only inspects rendered/captured daily surfaces and export previews.
Technical diagnostics remain allowed in Settings/Admin Setup Health, where they
are explicitly admin-gated.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.contracts.full_app_validation_inventory import FORBIDDEN_DAILY_TOKENS


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

RENDERED_UI_LEAK_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/rendered_ui_leak_scan_results.json"
RENDERED_UI_LEAK_FAILURES_REL = f"{FULL_APP_VALIDATION_DIR}/rendered_ui_leak_failures.json"
DAILY_WORDING_SCAN_REL = f"{FULL_APP_VALIDATION_DIR}/daily_wording_scan_results.json"
RENDERED_UI_LEAK_GATE_REL = f"{LAUNCH_READINESS_DIR}/rendered_ui_leak_gate_results.json"
DAILY_WORDING_GATE_REL = f"{LAUNCH_READINESS_DIR}/daily_wording_gate_results.json"
RENDERED_UI_LEAK_ARTIFACTS = {
    RENDERED_UI_LEAK_RESULTS_REL,
    RENDERED_UI_LEAK_FAILURES_REL,
    DAILY_WORDING_SCAN_REL,
}

EXTRA_FORBIDDEN_TOKENS = (
    "INFORMATION_SCHEMA",
    "SNOWFLAKE.ACCOUNT_USAGE",
    "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS",
    "ACCOUNT_USAGE.CREDENTIALS",
    "CREDENTIAL_ID",
    "USER_ID",
    "RAW_USER_ID",
    "CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY",
    "CORTEX_CODE_CLI_USAGE_HISTORY",
    "QUERY_INSIGHTS",
    "QUERY_ATTRIBUTION_HISTORY",
    "TABLE_STORAGE_METRICS",
    "ACCESS_HISTORY",
    "TRUST_CENTER_FINDINGS",
    "DYNAMIC_TABLE_REFRESH_HISTORY",
    "CREATE OR REPLACE",
    "SELECT *",
    "CALL SP_",
    "StreamlitAPIException",
    "raw SQL",
    "diagnostic card",
    "setup validation row",
    "procedure name",
    "stack trace",
    "No Snowflake connection",
    "no Snowflake connection",
    "demo role",
    "RoleGate",
    "Lock button",
    "DATABASE, USER, ROLE, AND QUERY COST VIEWS ARE ALLOCATED ESTIMATES",
)

FORBIDDEN_TOKENS = tuple(dict.fromkeys((*FORBIDDEN_DAILY_TOKENS, *EXTRA_FORBIDDEN_TOKENS)))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_payloads(root: Path, rels: Iterable[str]) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for rel in rels:
        path = root / rel
        if path.exists():
            try:
                payloads[rel] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payloads[rel] = {"passed": False, "failure_reason": "malformed_json"}
    return payloads


def _is_admin_allowed(surface: str, row: Mapping[str, Any]) -> bool:
    if bool(row.get("admin_only")):
        return True
    haystack = " ".join(
        str(row.get(key) or "")
        for key in ("section", "workflow", "surface", "area", "filename")
    ).lower()
    return "admin setup health" in haystack or "settings/admin setup health" in haystack


def _scan_text(text: str, *, surface: str, item: str, admin_allowed: bool) -> list[dict[str, Any]]:
    if admin_allowed:
        return []
    findings: list[dict[str, Any]] = []
    for index, token in enumerate(FORBIDDEN_TOKENS, start=1):
        needle = token if token.isupper() or "_" in token else token.lower()
        haystack = text if token.isupper() or "_" in token else text.lower()
        if needle in haystack:
            findings.append(
                {
                    "surface": surface,
                    "item": item,
                    "token_id": f"blocked_token_{index}",
                    "recommendation": "Move this diagnostic/source wording to Settings/Admin Setup Health or sanitize the export.",
                }
            )
    return findings


def scan_rendered_ui(payloads: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for row in _as_list(payloads.get("artifacts/full_app_validation/view_results.json")):
        mapping = _as_mapping(row)
        text = "\n".join(
            str(mapping.get(key) or "")
            for key in ("html_fragment", "rendered_text", "headline", "summary", "fallback_text")
        )
        section = str(mapping.get("section") or "")
        workflow = str(mapping.get("workflow") or "")
        surface = f"{section} / {workflow}".strip(" /")
        row_findings = _scan_text(text, surface=surface, item="rendered_view", admin_allowed=_is_admin_allowed(surface, mapping))
        findings.extend(row_findings)
        rows.append(
            {
                "surface": surface,
                "item": "rendered_view",
                "finding_count": len(row_findings),
                "passed": not row_findings,
                "raw_sql_included": False,
            }
        )

    for row in _as_list(payloads.get("artifacts/full_app_validation/rendered_fragments.json")):
        mapping = _as_mapping(row)
        text = str(mapping.get("text") or mapping.get("html") or mapping.get("fragment") or "")
        surface = str(mapping.get("section") or mapping.get("surface") or "rendered_fragment")
        row_findings = _scan_text(text, surface=surface, item="rendered_fragment", admin_allowed=_is_admin_allowed(surface, mapping))
        findings.extend(row_findings)
        rows.append(
            {
                "surface": surface,
                "item": "rendered_fragment",
                "finding_count": len(row_findings),
                "passed": not row_findings,
                "raw_sql_included": False,
            }
        )

    for rel, item_name in (
        ("artifacts/full_app_validation/deterministic_streamlit_render_results.json", "deterministic_render"),
        ("artifacts/full_app_validation/browser_smoke_results.json", "browser_smoke"),
        ("artifacts/full_app_validation/browser_render_results.json", "browser_render"),
    ):
        for row in _as_list(_as_mapping(payloads.get(rel)).get("rows")):
            mapping = _as_mapping(row)
            text = "\n".join(str(mapping.get(key) or "") for key in ("first_viewport_text", "html_fragment", "text"))
            surface = str(mapping.get("section") or mapping.get("surface") or item_name)
            row_findings = _scan_text(
                text,
                surface=surface,
                item=item_name,
                admin_allowed=_is_admin_allowed(surface, mapping),
            )
            findings.extend(row_findings)
            rows.append(
                {
                    "surface": surface,
                    "item": item_name,
                    "finding_count": len(row_findings),
                    "passed": not row_findings,
                    "raw_sql_included": False,
                }
            )

    for row in _as_list(payloads.get("artifacts/full_app_validation/export_results.json")):
        mapping = _as_mapping(row)
        text = "\n".join(str(mapping.get(key) or "") for key in ("content", "preview", "filename"))
        surface = f"export::{mapping.get('section') or ''}::{mapping.get('filename') or ''}"
        row_findings = _scan_text(text, surface=surface, item=str(mapping.get("filename") or "export"), admin_allowed=_is_admin_allowed(surface, mapping))
        findings.extend(row_findings)
        rows.append(
            {
                "surface": surface,
                "item": "export_preview",
                "finding_count": len(row_findings),
                "passed": not row_findings,
                "raw_sql_included": False,
            }
        )

    passed = not findings
    results = {
        "source": "rendered_ui_leak_scan_results",
        "generated_at": _now(),
        "passed": passed,
        "blocked_count": len(findings),
        "failure_count": len(findings),
        "rows": rows,
        "findings": findings,
        "admin_setup_allowed": True,
        "raw_sql_included": False,
    }
    failures = {
        "source": "rendered_ui_leak_failures",
        "generated_at": results["generated_at"],
        "passed": passed,
        "failure_count": len(findings),
        "failures": findings,
        "raw_sql_included": False,
    }
    return results, failures


def evaluate_rendered_ui_leak_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    findings = _as_list(payload.get("findings") or payload.get("failures"))
    blocked_count = int(payload.get("blocked_count") or payload.get("failure_count") or len(findings))
    return {
        "source": "rendered_ui_leak_gate_results",
        "generated_at": _now(),
        "passed": bool(payload.get("passed", False)) and blocked_count == 0,
        "blocked_count": blocked_count,
        "failure_count": blocked_count,
        "failures": findings,
        "raw_sql_included": False,
    }


def write_rendered_ui_leak_scan_artifacts(root: Path | str = ".", payloads: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payloads is None:
        payloads = _load_payloads(
            root_path,
            (
                "artifacts/full_app_validation/view_results.json",
                "artifacts/full_app_validation/rendered_fragments.json",
                "artifacts/full_app_validation/deterministic_streamlit_render_results.json",
                "artifacts/full_app_validation/browser_smoke_results.json",
                "artifacts/full_app_validation/browser_render_results.json",
                "artifacts/full_app_validation/export_results.json",
            ),
        )
    results, failures = scan_rendered_ui(payloads)
    wording = dict(results)
    wording["source"] = "daily_wording_scan_results"
    artifacts = {
        RENDERED_UI_LEAK_RESULTS_REL: results,
        RENDERED_UI_LEAK_FAILURES_REL: failures,
        DAILY_WORDING_SCAN_REL: wording,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "DAILY_WORDING_GATE_REL",
    "DAILY_WORDING_SCAN_REL",
    "FORBIDDEN_TOKENS",
    "RENDERED_UI_LEAK_ARTIFACTS",
    "RENDERED_UI_LEAK_FAILURES_REL",
    "RENDERED_UI_LEAK_GATE_REL",
    "RENDERED_UI_LEAK_RESULTS_REL",
    "evaluate_rendered_ui_leak_gate",
    "scan_rendered_ui",
    "write_rendered_ui_leak_scan_artifacts",
]
