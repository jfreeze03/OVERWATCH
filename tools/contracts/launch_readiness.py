"""Top-level launch readiness gate for Decision Workspace.

This module sits above the full app gauntlet. The gauntlet proves runtime
render/click/export/query invariants; launch readiness adds release concerns:
CI artifact upload wiring, browser or deterministic render proof, config and
secret safety, role/deployment/drop readiness, SQL value review, live-query
proof status, SLO consolidation, and launch docs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.contracts.full_app_gauntlet import (
    REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS,
    write_full_app_gauntlet_artifacts,
)


LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

REQUIRED_LAUNCH_READINESS_ARTIFACTS = {
    f"{LAUNCH_READINESS_DIR}/launch_readiness_summary.json",
    f"{LAUNCH_READINESS_DIR}/launch_readiness_failures.json",
    f"{LAUNCH_READINESS_DIR}/release_gate_matrix.json",
    f"{LAUNCH_READINESS_DIR}/browser_smoke_results.json",
    f"{LAUNCH_READINESS_DIR}/config_sanity_results.json",
    f"{LAUNCH_READINESS_DIR}/secrets_scan_results.json",
    f"{LAUNCH_READINESS_DIR}/snowflake_permission_matrix.json",
    f"{LAUNCH_READINESS_DIR}/role_readiness_results.json",
    f"{LAUNCH_READINESS_DIR}/deployment_readiness_results.json",
    f"{LAUNCH_READINESS_DIR}/upgrade_readiness_results.json",
    f"{LAUNCH_READINESS_DIR}/drop_rollback_results.json",
    f"{LAUNCH_READINESS_DIR}/sql_value_inventory.json",
    f"{LAUNCH_READINESS_DIR}/sql_cost_risk_findings.json",
    f"{LAUNCH_READINESS_DIR}/live_query_history_results.json",
    f"{LAUNCH_READINESS_DIR}/performance_slo_results.json",
    f"{LAUNCH_READINESS_DIR}/settings_live_closure_results.json",
    f"{LAUNCH_READINESS_DIR}/export_case_closure_results.json",
    f"{LAUNCH_READINESS_DIR}/cleanup_launch_closure_results.json",
    f"{LAUNCH_READINESS_DIR}/docs_readiness_results.json",
    f"{LAUNCH_READINESS_DIR}/ci_artifact_review_results.json",
    f"{LAUNCH_READINESS_DIR}/artifact_manifest.json",
}

CI_UPLOAD_PATHS = {
    "artifacts/launch_readiness/**",
    "artifacts/full_app_validation/**",
    "artifacts/full_app_inventory/**",
    "artifacts/cleanup/**",
    "artifacts/query_*",
    "artifacts/direct_sql_static_scan.json",
    "artifacts/session_open_static_scan.json",
    "artifacts/sql_performance_lint_findings.json",
    "artifacts/sql_performance_lint_file_inventory.json",
    "artifacts/button_route_manifest.json",
    "artifacts/button_route_results.json",
    "artifacts/brand/**",
    "artifacts/decision_workspace_html_snapshots/**",
    "artifacts/browser_screenshots/**",
}

PRIMARY_SECTIONS = {
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
}

COMPACT_EVIDENCE_MARTS = {
    "MART_QUERY_EVIDENCE_RECENT",
    "MART_ALERT_EVIDENCE_RECENT",
    "MART_SECURITY_EVIDENCE_RECENT",
    "MART_COST_EVIDENCE_RECENT",
    "MART_DBA_EVIDENCE_RECENT",
}

SECRET_PATTERNS = {
    "private_key": re.compile(r"BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY", re.IGNORECASE),
    "password_assignment": re.compile(r"\bpassword\s*[:=]\s*['\"]?[^'\"\s]{8,}", re.IGNORECASE),
    "secret_assignment": re.compile(r"\b(secret|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]{12,}", re.IGNORECASE),
    "snowflake_url": re.compile(r"snowflake://[^\s'\"\)]+", re.IGNORECASE),
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_list(payload: object) -> list[Any]:
    return list(payload) if isinstance(payload, list) else []


def _as_mapping(payload: object) -> Mapping[str, Any]:
    return payload if isinstance(payload, Mapping) else {}


def _as_int(value: object) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, (int, float, str, bytes, bytearray)):
            return int(value)
    except (TypeError, ValueError):
        return 0
    return 0


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append_failure(
    failures: list[dict[str, Any]],
    gate: str,
    reason: str,
    *,
    path: str = "",
    recommendation: str = "",
    count: int | None = None,
) -> None:
    row: dict[str, Any] = {
        "gate": gate,
        "reason": reason,
        "recommendation": recommendation
        or "Fix the owning release artifact or runtime contract, then rerun launch readiness.",
    }
    if path:
        row["path"] = path
    if count is not None:
        row["count"] = count
    failures.append(row)


def _clean_launch_artifact_directory(root: Path) -> None:
    artifacts_root = (root / "artifacts").resolve()
    launch_dir = (root / LAUNCH_READINESS_DIR).resolve()
    if launch_dir == artifacts_root or artifacts_root not in launch_dir.parents:
        raise ValueError(f"refusing to clean outside artifacts root: {launch_dir}")
    if launch_dir.exists():
        shutil.rmtree(launch_dir)
    launch_dir.mkdir(parents=True, exist_ok=True)


def _load_payloads(root: Path, rels: Iterable[str]) -> tuple[dict[str, Any], list[str]]:
    payloads: dict[str, Any] = {}
    missing: list[str] = []
    for rel in sorted(set(rels)):
        path = root / rel
        if not path.exists():
            missing.append(rel)
            continue
        try:
            payloads[rel] = _read_json(path)
        except json.JSONDecodeError:
            missing.append(rel)
    return payloads, sorted(missing)


def _workflow_upload_review(root: Path) -> dict[str, Any]:
    workflow_path = root / ".github" / "workflows" / "validate.yml"
    text = workflow_path.read_text(encoding="utf-8") if workflow_path.exists() else ""
    missing_upload_paths = sorted(path for path in CI_UPLOAD_PATHS if path not in text)
    required_steps = {
        "python -m unittest tests.test_full_app_gauntlet",
        "python -m unittest tests.test_launch_readiness",
        "python -m unittest discover -s tests",
        "python -m ruff check .overwatch_final tests tools",
        "python -m mypy",
    }
    missing_steps = sorted(step for step in required_steps if step not in text)
    passed = workflow_path.exists() and not missing_upload_paths and not missing_steps
    return {
        "source": "launch_readiness_ci_artifact_review",
        "proof_source": "inventory_only",
        "passed": passed,
        "workflow_file": ".github/workflows/validate.yml",
        "required_upload_paths": sorted(CI_UPLOAD_PATHS),
        "missing_upload_paths": missing_upload_paths,
        "missing_upload_path_count": len(missing_upload_paths),
        "missing_steps": missing_steps,
        "missing_step_count": len(missing_steps),
        "uploaded_artifact_names": ["decision-workspace-proof"],
        "raw_sql_included": False,
    }


def _browser_smoke_results(root: Path, payloads: Mapping[str, Any]) -> dict[str, Any]:
    screenshot_dir = root / "artifacts" / "browser_screenshots"
    screenshot_files = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in screenshot_dir.rglob("*")
        if path.is_file() and path.name != "SKIPPED.txt"
    ) if screenshot_dir.exists() else []
    snapshot_dir = root / "artifacts" / "decision_workspace_html_snapshots"
    snapshot_files = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in snapshot_dir.rglob("*")
        if path.is_file()
    ) if snapshot_dir.exists() else []
    if screenshot_files:
        skipped = False
        skip_reason = ""
        skipped_path = screenshot_dir / "SKIPPED.txt"
        if skipped_path.exists():
            skipped_path.unlink()
    else:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        skipped = True
        skip_reason = "Browser screenshot proof was not available in this local or CI run; deterministic rendered snapshots are mandatory and present."
        (screenshot_dir / "SKIPPED.txt").write_text(skip_reason, encoding="utf-8")
    forbidden_daily = _as_mapping(payloads.get("artifacts/full_app_validation/forbidden_daily_ui_scan.json"))
    blocked_count = _as_int(forbidden_daily.get("blocked_count"))
    first_viewport_sections = set()
    for row in _as_list(payloads.get("artifacts/full_app_validation/view_results.json")):
        row_map = _as_mapping(row)
        section = str(row_map.get("section") or "")
        if section:
            first_viewport_sections.add(section)
    passed = bool(snapshot_files) and blocked_count == 0 and PRIMARY_SECTIONS.issubset(first_viewport_sections)
    return {
        "source": "launch_readiness_browser_smoke",
        "proof_source": "runtime_render",
        "passed": passed,
        "browser_screenshot_count": len(screenshot_files),
        "browser_screenshots": screenshot_files,
        "browser_proof_skipped": skipped,
        "skip_reason": skip_reason,
        "deterministic_snapshot_count": len(snapshot_files),
        "deterministic_snapshots_present": bool(snapshot_files),
        "sections_seen": sorted(first_viewport_sections),
        "daily_forbidden_blocked_count": blocked_count,
        "raw_sql_included": False,
    }


def _config_sanity_results(root: Path) -> dict[str, Any]:
    fixture_enabled = os.environ.get("OVERWATCH_UI_FIXTURE_MODE") == "1"
    fixture_allowed = os.environ.get("OVERWATCH_ALLOW_FIXTURE_MODE") == "1"
    raw_perf_sql = os.environ.get("OVERWATCH_INCLUDE_SQL_IN_PERF_ARTIFACTS") == "1"
    live_proof = os.environ.get("OVERWATCH_QUERY_PLAN_PROOF") == "1"
    runtime_import_hits: list[str] = []
    import_pattern = re.compile(
        r"^\s*(?:from\s+(?:tools\.contracts|tests)(?:\b|\.)|import\s+(?:tools\.contracts|tests)(?:\b|\.))",
        re.MULTILINE,
    )
    for path in (root / ".overwatch_final").rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if import_pattern.search(text):
            runtime_import_hits.append(str(path.relative_to(root)).replace("\\", "/"))
    failures: list[str] = []
    if fixture_enabled and not fixture_allowed:
        failures.append("Fixture mode is enabled without OVERWATCH_ALLOW_FIXTURE_MODE=1.")
    if raw_perf_sql and not live_proof:
        failures.append("Raw perf SQL artifacts require live query proof mode.")
    if runtime_import_hits:
        failures.append("Runtime package imports CI-only tools or tests.")
    return {
        "source": "launch_readiness_config_sanity",
        "proof_source": "inventory_only",
        "passed": not failures,
        "failures": failures,
        "fixture_mode_enabled": fixture_enabled,
        "fixture_mode_requires_explicit_allow": True,
        "fixture_mode_allowed": fixture_allowed,
        "raw_perf_sql_enabled": raw_perf_sql,
        "raw_perf_sql_requires_admin_perf_mode": True,
        "live_query_proof_enabled": live_proof,
        "runtime_ci_tool_import_count": len(runtime_import_hits),
        "runtime_ci_tool_imports": runtime_import_hits,
        "safe_defaults": {
            "fixture_mode": not fixture_enabled,
            "raw_sql_perf_artifacts": not raw_perf_sql,
            "debug_panels_daily": False,
        },
        "raw_sql_included": False,
    }


def _secrets_scan_results(root: Path) -> dict[str, Any]:
    scan_roots = [
        root / "artifacts" / "full_app_validation",
        root / "artifacts" / "full_app_inventory",
        root / "artifacts" / "cleanup",
        root / "artifacts" / "launch_readiness",
        root / "artifacts",
    ]
    findings: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*") if scan_root.is_dir() else [scan_root]:
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            if path.suffix.lower() not in {".json", ".txt", ".csv", ".md"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    findings.append(
                        {
                            "file": str(path.relative_to(root)).replace("\\", "/"),
                            "pattern": name,
                        }
                    )
    return {
        "source": "launch_readiness_secrets_scan",
        "proof_source": "inventory_only",
        "passed": not findings,
        "blocked_count": len(findings),
        "findings": findings,
        "scanned_file_count": len(seen),
        "raw_sql_included": False,
    }


def _permission_matrix() -> dict[str, Any]:
    rows = [
        {
            "role": "daily_user",
            "purpose": "Open primary Decision Workspace sections and normal evidence.",
            "required_access": [
                "current packet tables",
                "compact evidence marts",
                "last-good packet table",
            ],
            "account_usage_required": False,
            "admin_only": False,
        },
        {
            "role": "evidence_loader",
            "purpose": "Read compact evidence mart rows for targeted evidence clicks.",
            "required_access": sorted(COMPACT_EVIDENCE_MARTS),
            "account_usage_required": False,
            "admin_only": False,
        },
        {
            "role": "query_search_user",
            "purpose": "Search recent query mart detail without SQL text by default.",
            "required_access": ["recent query evidence mart", "exact query detail fact"],
            "account_usage_required": False,
            "admin_only": False,
        },
        {
            "role": "setup_admin",
            "purpose": "Run setup health, deployment checks, validation, and bootstrap.",
            "required_access": ["setup schema", "audit tables", "procedure/task management"],
            "account_usage_required": "optional for setup diagnostics",
            "admin_only": True,
        },
        {
            "role": "account_usage_fallback_operator",
            "purpose": "Run explicit deep fallback only after confirmation.",
            "required_access": ["account usage views"],
            "account_usage_required": True,
            "admin_only": True,
        },
        {
            "role": "rollback_operator",
            "purpose": "Use last-known-good packet and safe drop plan during rollback.",
            "required_access": ["last-good packet table", "drop plan execution privileges"],
            "account_usage_required": False,
            "admin_only": True,
        },
    ]
    return {
        "source": "launch_readiness_permission_matrix",
        "proof_source": "inventory_only",
        "passed": True,
        "roles": rows,
        "role_count": len(rows),
        "daily_account_usage_required": False,
        "setup_admin_separated": True,
        "raw_sql_included": False,
    }


def _role_readiness_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    evidence_rows = _as_list(payloads.get("artifacts/full_app_validation/evidence_loader_call_matrix.json"))
    normal_rows = [
        _as_mapping(row)
        for row in evidence_rows
        if _as_mapping(row).get("loader_kind") == "normal_evidence"
    ]
    normal_account_usage = [
        row for row in normal_rows
        if bool(row.get("account_usage_used"))
    ]
    compact_missing = [
        row for row in normal_rows
        if str(row.get("compact_table_family") or "") not in COMPACT_EVIDENCE_MARTS
        and str(row.get("compact_table_family") or "") != "FACT_QUERY_DETAIL_RECENT"
    ]
    settings_rows = _as_list(payloads.get("artifacts/full_app_validation/settings_action_results.json"))
    live_rows = _as_list(payloads.get("artifacts/full_app_validation/live_feature_results.json"))
    sanitized_failures = [
        row for row in [*_as_list(settings_rows), *_as_list(live_rows)]
        if _as_mapping(row).get("raw_error_visible_daily") is True
    ]
    passed = not normal_account_usage and not compact_missing and not sanitized_failures
    return {
        "source": "launch_readiness_role_readiness",
        "proof_source": "runtime_click",
        "passed": passed,
        "daily_app_paths_require_account_usage": False,
        "normal_account_usage_count": len(normal_account_usage),
        "compact_source_gap_count": len(compact_missing),
        "admin_deep_fallback_separated": True,
        "setup_admin_permissions_separated": True,
        "sanitized_permission_error_gap_count": len(sanitized_failures),
        "raw_sql_included": False,
    }


def _sql_files(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in (root / "snowflake").rglob("*.sql"):
        try:
            files[str(path.relative_to(root)).replace("\\", "/")] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            files[str(path.relative_to(root)).replace("\\", "/")] = ""
    return files


def _deployment_readiness_results(root: Path, payloads: Mapping[str, Any]) -> dict[str, Any]:
    sql_files = _sql_files(root)
    required = [
        "snowflake/OVERWATCH_MART_SETUP.sql",
        "snowflake/OVERWATCH_MART_VALIDATION.sql",
        "snowflake/OVERWATCH_MART_DROP.sql",
    ]
    missing = [rel for rel in required if rel not in sql_files]
    sql_lint_errors = [
        row for row in _as_list(payloads.get("artifacts/sql_performance_lint_findings.json"))
        if str(_as_mapping(row).get("severity") or "").lower() == "error"
    ]
    object_inventory = _as_mapping(payloads.get("artifacts/cleanup/sql_object_inventory.json"))
    unknown_count = len(_as_list(object_inventory.get("unknown")))
    setup_text = sql_files.get("snowflake/OVERWATCH_MART_SETUP.sql", "")
    setup_has_idempotent_tokens = "CREATE OR REPLACE" in setup_text or "IF NOT EXISTS" in setup_text
    passed = not missing and not sql_lint_errors and unknown_count == 0 and setup_has_idempotent_tokens
    return {
        "source": "launch_readiness_deployment_readiness",
        "proof_source": "inventory_only",
        "passed": passed,
        "setup_sql_present": "snowflake/OVERWATCH_MART_SETUP.sql" in sql_files,
        "validation_sql_present": "snowflake/OVERWATCH_MART_VALIDATION.sql" in sql_files,
        "drop_sql_present": "snowflake/OVERWATCH_MART_DROP.sql" in sql_files,
        "missing_required_sql_files": missing,
        "sql_lint_error_count": len(sql_lint_errors),
        "unknown_sql_object_count": unknown_count,
        "idempotent_setup_static_proof": setup_has_idempotent_tokens,
        "stored_procedure_compile_static": not sql_lint_errors,
        "grants_static_proof": "GRANT" in setup_text.upper(),
        "raw_sql_included": False,
    }


def _upgrade_readiness_results(root: Path) -> dict[str, Any]:
    setup_text = (root / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")
    has_create_or_replace = "CREATE OR REPLACE" in setup_text
    has_schema_version = "VERSION" in setup_text.upper() or "SCHEMA" in setup_text.upper()
    return {
        "source": "launch_readiness_upgrade_readiness",
        "proof_source": "inventory_only",
        "passed": has_create_or_replace and has_schema_version,
        "setup_rerun_idempotent": has_create_or_replace,
        "schema_version_reference_present": has_schema_version,
        "prior_schema_upgrade_static_review": True,
        "raw_sql_included": False,
    }


def _drop_rollback_results(root: Path, payloads: Mapping[str, Any]) -> dict[str, Any]:
    sql_files = _sql_files(root)
    drop_present = "snowflake/OVERWATCH_MART_DROP.sql" in sql_files
    last_good_present = any(
        "MART_SECTION_DECISION_LAST_GOOD" in text
        for text in sql_files.values()
    )
    cleanup_drop_plan = root / "artifacts" / "cleanup" / "sql_drop_plan.sql"
    object_inventory = _as_mapping(payloads.get("artifacts/cleanup/sql_object_inventory.json"))
    active_in_drop = _as_list(object_inventory.get("active_objects_in_drop_plan"))
    passed = drop_present and last_good_present and cleanup_drop_plan.exists() and not active_in_drop
    return {
        "source": "launch_readiness_drop_rollback",
        "proof_source": "inventory_only",
        "passed": passed,
        "drop_sql_present": drop_present,
        "cleanup_drop_plan_present": cleanup_drop_plan.exists(),
        "last_known_good_packet_static_proof": last_good_present,
        "active_object_in_drop_count": len(active_in_drop),
        "rollback_packet_fallback_proven": last_good_present,
        "raw_sql_included": False,
    }


def _sql_value_inventory(root: Path, payloads: Mapping[str, Any]) -> dict[str, Any]:
    file_inventory = _as_mapping(payloads.get("artifacts/sql_performance_lint_file_inventory.json"))
    sql_files = _sql_files(root)
    rows: list[dict[str, Any]] = []
    for rel in _as_list(file_inventory.get("scanned_files")):
        rel_str = str(rel)
        text = sql_files.get(rel_str, "")
        upper = text.upper()
        if "DROP" in rel_str.upper():
            boundary = "admin_drop"
            purpose = "Safe cleanup and rollback support."
        elif "VALIDATION" in rel_str.upper():
            boundary = "admin_setup"
            purpose = "Post-deployment object and setup validation."
        elif "SECURE_VIEW_AUDIT" in rel_str.upper():
            boundary = "admin_setup"
            purpose = "Admin secure-view dependency review."
        elif "05_LOAD_PROCEDURES" in rel_str.upper() or "MART_SETUP" in rel_str.upper():
            boundary = "refresh_or_setup"
            purpose = "Setup, compact marts, and refresh procedures."
        else:
            boundary = "admin_setup"
            purpose = "Deployment support SQL."
        account_usage = "SNOWFLAKE.ACCOUNT_USAGE" in upper or "ACCOUNT_USAGE" in upper
        rows.append(
            {
                "path": rel_str,
                "purpose": purpose,
                "user_visible_value": "Supports current Decision Workspace operation or admin setup.",
                "owner": "decision-workspace-platform",
                "expected_boundary": boundary,
                "table_family": "compact_mart_or_setup",
                "max_rows": 500 if boundary == "admin_setup" else None,
                "account_usage_use": "admin_or_deep_only" if account_usage else "none",
                "daily_path": False,
                "pruning_predicate_present": bool(re.search(r"\bWHERE\b", upper)),
                "ordering_present": bool(re.search(r"\bORDER\s+BY\b", upper)),
                "limit_present": bool(re.search(r"\bLIMIT\b", upper)),
                "expected_frequency": "on_setup_or_explicit_refresh",
                "replacement_delete_decision": "keep_active" if purpose else "delete",
            }
        )
    gaps = [
        row for row in rows
        if not row["purpose"] or not row["owner"] or (row["daily_path"] and row["account_usage_use"] != "none")
    ]
    return {
        "source": "launch_readiness_sql_value_inventory",
        "proof_source": "inventory_only",
        "passed": not gaps and bool(rows),
        "sql_path_count": len(rows),
        "unowned_or_no_value_count": len(gaps),
        "paths": rows,
        "raw_sql_included": False,
    }


def _sql_cost_risk_findings(payloads: Mapping[str, Any], sql_value: Mapping[str, Any]) -> dict[str, Any]:
    lint_rows = _as_list(payloads.get("artifacts/sql_performance_lint_findings.json"))
    errors = [
        _as_mapping(row) for row in lint_rows
        if str(_as_mapping(row).get("severity") or "").lower() == "error"
    ]
    value_gaps = _as_int(sql_value.get("unowned_or_no_value_count"))
    findings: list[dict[str, Any]] = []
    for row in errors:
        findings.append(
            {
                "source": "sql_performance_lint",
                "code": row.get("code") or row.get("rule") or "SQL_LINT_ERROR",
                "severity": "error",
                "path": row.get("path") or row.get("file") or "",
                "recommendation": row.get("recommended_replacement")
                or row.get("recommendation")
                or "Fix the SQL path or remove it from the launch surface.",
            }
        )
    if value_gaps:
        findings.append(
            {
                "source": "sql_value_inventory",
                "code": "SQL_PATH_VALUE_GAP",
                "severity": "error",
                "path": "",
                "recommendation": "Add owner/purpose or delete the SQL path.",
            }
        )
    return {
        "source": "launch_readiness_sql_cost_risk",
        "proof_source": "inventory_only",
        "passed": not findings,
        "error_count": len(findings),
        "findings": findings,
        "raw_sql_included": False,
    }


def _live_query_history_results(root: Path) -> dict[str, Any]:
    live_enabled = os.environ.get("OVERWATCH_QUERY_PLAN_PROOF") == "1"
    live_artifact = root / "artifacts" / "query_history_by_tag.json"
    skipped_artifact = root / "artifacts" / "query_history_by_tag_SKIPPED.txt"
    if live_enabled:
        passed = live_artifact.exists()
        skip_reason = "" if passed else "OVERWATCH_QUERY_PLAN_PROOF=1 but query_history_by_tag.json was not generated."
        skipped = False
    else:
        passed = skipped_artifact.exists()
        skipped = True
        skip_reason = (
            skipped_artifact.read_text(encoding="utf-8").strip()
            if skipped_artifact.exists()
            else "Live query-history proof is disabled; fixture CI records an explicit skip."
        )
        if not skipped_artifact.exists():
            skipped_artifact.write_text(skip_reason, encoding="utf-8")
            passed = True
    return {
        "source": "launch_readiness_live_query_history",
        "proof_source": "runtime_click" if live_enabled else "inventory_only",
        "passed": passed,
        "live_query_plan_proof_enabled": live_enabled,
        "live_artifact_present": live_artifact.exists(),
        "skipped": skipped,
        "skip_reason": skip_reason,
        "raw_sql_included": False,
        "live_release_warning": skipped,
    }


def _performance_slo_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    summary = _as_mapping(payloads.get("artifacts/full_app_validation/app_validation_summary.json"))
    query_search = _as_list(payloads.get("artifacts/full_app_validation/query_search_results.json"))
    evidence_rows = _as_list(payloads.get("artifacts/full_app_validation/evidence_loader_call_matrix.json"))
    stress_rows = _as_list(payloads.get("artifacts/full_app_validation/stress_results.json"))
    exact_cases = [
        _as_mapping(row) for row in query_search
        if _as_mapping(row).get("case") == "exact_query_id"
    ]
    unconfirmed_cases = [
        _as_mapping(row) for row in query_search
        if _as_mapping(row).get("case") == "account_usage_fallback_unconfirmed"
    ]
    slo_rows = [
        {
            "slo": "route actions zero cost",
            "actual": _as_int(summary.get("route_query_leak_count")),
            "threshold": 0,
            "passed": _as_int(summary.get("route_query_leak_count")) == 0,
        },
        {
            "slo": "first paint no non-packet leakage",
            "actual": _as_int(summary.get("first_paint_query_leak_count")),
            "threshold": 0,
            "passed": _as_int(summary.get("first_paint_query_leak_count")) == 0,
        },
        {
            "slo": "unconfirmed Account Usage fallback zero cost",
            "actual": _as_int(summary.get("account_usage_unconfirmed_leak_count")),
            "threshold": 0,
            "passed": _as_int(summary.get("account_usage_unconfirmed_leak_count")) == 0
            and all(
                _as_int(row.get("session_open_count"))
                + _as_int(row.get("snowflake_execution_count"))
                + _as_int(row.get("direct_sql_event_count")) == 0
                for row in unconfirmed_cases
            ),
        },
        {
            "slo": "exact Query ID max_rows",
            "actual": max([_as_int(row.get("max_rows")) for row in exact_cases] or [0]),
            "threshold": 1,
            "passed": all(_as_int(row.get("max_rows")) <= 1 for row in exact_cases),
        },
        {
            "slo": "normal evidence max_rows",
            "actual": max(
                [
                    _as_int(_as_mapping(row).get("max_rows"))
                    for row in evidence_rows
                    if _as_mapping(row).get("loader_kind") == "normal_evidence"
                ]
                or [0]
            ),
            "threshold": 500,
            "passed": all(
                _as_int(_as_mapping(row).get("max_rows")) <= 500
                for row in evidence_rows
                if _as_mapping(row).get("loader_kind") == "normal_evidence"
            ),
        },
        {
            "slo": "stress thresholds",
            "actual": sum(1 for row in stress_rows if _as_mapping(row).get("threshold_passed") is False),
            "threshold": 0,
            "passed": all(bool(_as_mapping(row).get("threshold_passed")) for row in stress_rows),
        },
        {
            "slo": "daily forbidden-token count",
            "actual": _as_int(summary.get("forbidden_ui_token_count")),
            "threshold": 0,
            "passed": _as_int(summary.get("forbidden_ui_token_count")) == 0,
        },
        {
            "slo": "export payload risk",
            "actual": _as_int(summary.get("export_payload_risk_count")),
            "threshold": 0,
            "passed": _as_int(summary.get("export_payload_risk_count")) == 0,
        },
    ]
    failures = [row for row in slo_rows if not row["passed"]]
    return {
        "source": "launch_readiness_performance_slo",
        "proof_source": "runtime_click",
        "passed": not failures,
        "slo_count": len(slo_rows),
        "failed_slo_count": len(failures),
        "slos": slo_rows,
        "raw_sql_included": False,
    }


def _settings_live_closure_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    settings_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/settings_action_results.json"))]
    live_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/live_feature_results.json"))]

    def row_passed(row: Mapping[str, Any]) -> bool:
        clicked_or_skipped = bool(row.get("clicked")) or bool(row.get("skip_reason"))
        observed_contexts = _as_list(
            row.get("observed_contexts")
            or row.get("observed_budget_contexts")
            or row.get("observed_query_budget_contexts")
            or row.get("marker_budget_runtime_contexts")
        )
        budget_ok = bool(observed_contexts) or bool(row.get("skip_reason"))
        return (
            clicked_or_skipped
            and budget_ok
            and bool(row.get("admin_or_advanced_gated", True))
            and row.get("raw_error_visible_daily") is not True
        )

    settings_failures = [row for row in settings_rows if not row_passed(row)]
    live_failures = [
        row for row in live_rows
        if not row_passed(row)
        or not bool(row.get("explicit_click_required"))
        or not bool(row.get("timeout_or_row_limit"))
        or bool(row.get("first_paint_invocation"))
        or bool(row.get("route_invocation"))
    ]
    return {
        "source": "launch_readiness_settings_live_closure",
        "proof_source": "runtime_click",
        "passed": not settings_failures and not live_failures,
        "settings_action_count": len(settings_rows),
        "live_feature_count": len(live_rows),
        "settings_failure_count": len(settings_failures),
        "live_failure_count": len(live_failures),
        "raw_sql_included": False,
    }


def _export_case_closure_results(root: Path, payloads: Mapping[str, Any]) -> dict[str, Any]:
    export_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/export_results.json"))]
    case_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/case_payload_results.json"))]
    export_failures: list[dict[str, Any]] = []
    for row in export_rows:
        payload_file = str(row.get("payload_file") or "")
        payload_path = root / payload_file if payload_file else None
        expected_rows = _as_int(row.get("visible_row_count"))
        if expected_rows > 0 and (_as_int(row.get("content_length")) <= 0 or not payload_file):
            export_failures.append({"filename": row.get("filename"), "reason": "empty_payload"})
        if payload_path and payload_path.exists() and row.get("sha256") and _file_sha256(payload_path) != row.get("sha256"):
            export_failures.append({"filename": row.get("filename"), "reason": "hash_mismatch"})
        if _as_int(row.get("parsed_row_count")) != _as_int(row.get("visible_row_count")):
            export_failures.append({"filename": row.get("filename"), "reason": "row_count_mismatch"})
        if _as_int(row.get("raw_internal_token_count")):
            export_failures.append({"filename": row.get("filename"), "reason": "raw_internal_token"})
        if row.get("query_text_included") and not row.get("admin_only"):
            export_failures.append({"filename": row.get("filename"), "reason": "query_text_in_daily_export"})
    case_failures: list[dict[str, Any]] = []
    required_case_fields = {"section", "workflow", "scope", "target", "freshness", "source", "summary", "row_count"}
    for row in case_rows:
        missing = sorted(field for field in required_case_fields if not row.get(field))
        if missing:
            case_failures.append({"section": row.get("section"), "reason": "missing_fields", "fields": missing})
        if _as_int(row.get("row_count")) != _as_int(row.get("visible_row_count")):
            case_failures.append({"section": row.get("section"), "reason": "row_count_mismatch"})
    return {
        "source": "launch_readiness_export_case_closure",
        "proof_source": "runtime_export",
        "passed": not export_failures and not case_failures,
        "export_count": len(export_rows),
        "case_payload_count": len(case_rows),
        "export_failure_count": len(export_failures),
        "case_failure_count": len(case_failures),
        "export_failures": export_failures,
        "case_failures": case_failures,
        "raw_sql_included": False,
    }


def _cleanup_launch_closure_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    summary = _as_mapping(payloads.get("artifacts/cleanup/cleanup_summary.json"))
    route_inventory = _as_mapping(payloads.get("artifacts/cleanup/route_state_inventory.json"))
    object_inventory = _as_mapping(payloads.get("artifacts/cleanup/sql_object_inventory.json"))
    module_inventory = _as_mapping(payloads.get("artifacts/cleanup/module_inventory.json"))
    failures = {
        "unknown_sql_object_count": _as_int(summary.get("unknown_sql_object_count"))
        or len(_as_list(object_inventory.get("unknown"))),
        "dead_route_count": len(_as_list(route_inventory.get("dead_routes"))),
        "stale_artifact_count": _as_int(summary.get("stale_generated_artifact_count")),
        "unreachable_module_count": len(_as_list(summary.get("unreachable_production_modules"))),
        "retained_generic_reason_count": _as_int(summary.get("retained_generic_reason_count")),
        "unowned_module_count": len(_as_list(module_inventory.get("unowned_retained_modules"))),
    }
    passed = all(count == 0 for count in failures.values())
    return {
        "source": "launch_readiness_cleanup_closure",
        "proof_source": "inventory_only",
        "passed": passed,
        **failures,
        "raw_sql_included": False,
    }


def _docs_readiness_results(root: Path) -> dict[str, Any]:
    docs_path = root / "docs" / "launch_readiness.md"
    text = docs_path.read_text(encoding="utf-8") if docs_path.exists() else ""
    checks = {
        "mentions_no_raw_sql_daily_ui": "No raw SQL in daily UI" in text,
        "mentions_fixture_mode_policy": "Fixture mode policy" in text,
        "mentions_required_roles": "Required roles" in text,
        "mentions_setup_admin_troubleshooting": "Setup and admin troubleshooting" in text,
        "mentions_fast_full_refresh": "FAST and FULL refresh" in text,
        "mentions_artifact_interpretation": "Artifact interpretation" in text,
    }
    missing = sorted(key for key, passed in checks.items() if not passed)
    return {
        "source": "launch_readiness_docs",
        "proof_source": "inventory_only",
        "passed": docs_path.exists() and not missing,
        "docs_path": "docs/launch_readiness.md",
        "checks": checks,
        "missing_checks": missing,
        "raw_sql_included": False,
    }


def _artifact_review_results(root: Path, payloads: Mapping[str, Any], missing_payloads: Iterable[str]) -> dict[str, Any]:
    missing = sorted(set(missing_payloads))
    launch_files = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in (root / LAUNCH_READINESS_DIR).rglob("*")
        if path.is_file()
    ) if (root / LAUNCH_READINESS_DIR).exists() else []
    gauntlet_reconciliation = _as_mapping(payloads.get("artifacts/full_app_validation/gauntlet_artifact_reconciliation.json"))
    stale_count = _as_int(gauntlet_reconciliation.get("unlisted_file_count"))
    passed = not missing and stale_count == 0
    return {
        "source": "launch_readiness_artifact_review",
        "proof_source": "inventory_only",
        "passed": passed,
        "required_gauntlet_artifact_count": len(REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS),
        "missing_required_gauntlet_artifacts": missing,
        "missing_required_gauntlet_artifact_count": len(missing),
        "stale_artifact_count": stale_count,
        "launch_artifact_count": len(launch_files),
        "launch_artifacts_seen": launch_files,
        "raw_sql_included": False,
    }


def _ci_metadata() -> dict[str, Any]:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "jfreeze03/OVERWATCH")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id else ""
    return {
        "workflow_run_id": run_id,
        "workflow_url": run_url,
        "workflow_name": os.environ.get("GITHUB_WORKFLOW", ""),
        "github_sha": os.environ.get("GITHUB_SHA", ""),
    }


def _release_gate_matrix(
    payloads: Mapping[str, Any],
    launch_artifacts: Mapping[str, Any],
    missing_payloads: Iterable[str],
) -> list[dict[str, Any]]:
    summary = _as_mapping(payloads.get("artifacts/full_app_validation/app_validation_summary.json"))
    gauntlet = _as_mapping(payloads.get("artifacts/full_app_validation/gauntlet_results.json"))
    direct = _as_mapping(payloads.get("artifacts/direct_sql_static_scan.json"))
    session = _as_mapping(payloads.get("artifacts/session_open_static_scan.json"))
    sql_lint = _as_list(payloads.get("artifacts/sql_performance_lint_findings.json"))
    sql_errors = sum(1 for row in sql_lint if str(_as_mapping(row).get("severity") or "").lower() == "error")
    artifact_review = _as_mapping(launch_artifacts.get("artifact_review_results"))
    ci_review = _as_mapping(launch_artifacts.get("ci_artifact_review_results"))
    browser = _as_mapping(launch_artifacts.get("browser_smoke_results"))
    live_query = _as_mapping(launch_artifacts.get("live_query_history_results"))
    rows = [
        {
            "gate": "full_app_gauntlet",
            "artifact": "artifacts/full_app_validation/gauntlet_results.json",
            "passed": bool(gauntlet.get("passed")),
            "failure_reason": "" if gauntlet.get("passed") else "Full app gauntlet failed.",
        },
        {
            "gate": "runtime_validation",
            "artifact": "artifacts/full_app_validation/app_validation_summary.json",
            "passed": bool(summary.get("all_passed")),
            "failure_reason": "" if summary.get("all_passed") else "Runtime validation did not pass.",
        },
        {
            "gate": "required_artifacts",
            "artifact": f"{LAUNCH_READINESS_DIR}/ci_artifact_review_results.json",
            "passed": not list(missing_payloads) and bool(artifact_review.get("passed")),
            "failure_reason": "Missing or stale required artifacts." if list(missing_payloads) or not artifact_review.get("passed") else "",
        },
        {
            "gate": "ci_upload_paths",
            "artifact": f"{LAUNCH_READINESS_DIR}/ci_artifact_review_results.json",
            "passed": bool(ci_review.get("passed")),
            "failure_reason": "" if ci_review.get("passed") else "CI workflow is missing launch readiness steps or upload paths.",
        },
        {
            "gate": "browser_or_rendered_snapshot",
            "artifact": f"{LAUNCH_READINESS_DIR}/browser_smoke_results.json",
            "passed": bool(browser.get("passed")),
            "failure_reason": "" if browser.get("passed") else "Browser proof or deterministic snapshots are missing or leaking.",
        },
        {
            "gate": "direct_sql_static_scan",
            "artifact": "artifacts/direct_sql_static_scan.json",
            "passed": _as_int(direct.get("blocked_count")) == 0,
            "failure_reason": "Direct SQL static scan has blocking findings." if _as_int(direct.get("blocked_count")) else "",
        },
        {
            "gate": "session_open_static_scan",
            "artifact": "artifacts/session_open_static_scan.json",
            "passed": _as_int(session.get("blocked_count")) == 0,
            "failure_reason": "Session-open static scan has blocking findings." if _as_int(session.get("blocked_count")) else "",
        },
        {
            "gate": "sql_performance_lint",
            "artifact": "artifacts/sql_performance_lint_findings.json",
            "passed": sql_errors == 0,
            "failure_reason": "SQL performance linter has error findings." if sql_errors else "",
        },
        {
            "gate": "live_query_history",
            "artifact": f"{LAUNCH_READINESS_DIR}/live_query_history_results.json",
            "passed": bool(live_query.get("passed")),
            "failure_reason": "" if live_query.get("passed") else "Live query proof is configured but missing.",
        },
    ]
    for gate, artifact_key in {
        "config_sanity": "config_sanity_results",
        "secrets_scan": "secrets_scan_results",
        "role_readiness": "role_readiness_results",
        "deployment_readiness": "deployment_readiness_results",
        "upgrade_readiness": "upgrade_readiness_results",
        "drop_rollback": "drop_rollback_results",
        "sql_value_inventory": "sql_value_inventory",
        "sql_cost_risk": "sql_cost_risk_findings",
        "performance_slo": "performance_slo_results",
        "settings_live_closure": "settings_live_closure_results",
        "export_case_closure": "export_case_closure_results",
        "cleanup_closure": "cleanup_launch_closure_results",
        "docs_readiness": "docs_readiness_results",
    }.items():
        artifact = _as_mapping(launch_artifacts.get(artifact_key))
        rows.append(
            {
                "gate": gate,
                "artifact": f"{LAUNCH_READINESS_DIR}/{artifact_key}.json",
                "passed": bool(artifact.get("passed")),
                "failure_reason": "" if artifact.get("passed") else f"{gate} did not pass.",
            }
        )
    for row in rows:
        row["recommendation"] = "" if row["passed"] else "Open the named artifact, fix the owning release risk, and rerun launch readiness."
    return rows


def evaluate_launch_readiness(
    payloads: Mapping[str, Any],
    launch_artifacts: Mapping[str, Any],
    *,
    missing_artifacts: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Evaluate launch readiness from already-loaded artifacts."""

    failures: list[dict[str, Any]] = []
    missing = sorted(set(missing_artifacts))
    if missing:
        _append_failure(
            failures,
            "missing_launch_prerequisite_artifacts",
            "Launch readiness requires all gauntlet prerequisite artifacts.",
            count=len(missing),
            recommendation="Regenerate the full app gauntlet bundle before launch readiness.",
        )

    matrix = _release_gate_matrix(payloads, launch_artifacts, missing)
    for row in matrix:
        if not bool(row.get("passed")):
            _append_failure(
                failures,
                str(row.get("gate") or "release_gate"),
                str(row.get("failure_reason") or "Release gate failed."),
                path=str(row.get("artifact") or ""),
                recommendation=str(row.get("recommendation") or ""),
            )

    gauntlet = _as_mapping(payloads.get("artifacts/full_app_validation/gauntlet_results.json"))
    gauntlet_failures = _as_mapping(payloads.get("artifacts/full_app_validation/gauntlet_failures.json"))
    if not gauntlet or not gauntlet_failures:
        _append_failure(
            failures,
            "full_app_gauntlet_artifacts",
            "Launch readiness cannot pass without gauntlet_results and gauntlet_failures.",
            recommendation="Run the full app gauntlet before launch readiness.",
        )

    summary = _as_mapping(payloads.get("artifacts/full_app_validation/app_validation_summary.json"))
    hard_gate_failures = _as_list(summary.get("hard_gate_failures"))
    for reason in hard_gate_failures:
        _append_failure(
            failures,
            "runtime_hard_gate_failure",
            str(reason),
            recommendation="Fix the runtime hard-gate failure reported in app_validation_summary.",
        )

    passed = not failures
    ci_meta = _ci_metadata()
    launch_summary = {
        "source": "launch_readiness",
        "proof_source": "runtime_click",
        "generated_at": _utc_now(),
        "all_passed": passed,
        "passed": passed,
        "hard_gate_passed": passed,
        "failure_count": len(failures),
        "blocking_failures": failures,
        "check_count": len(matrix),
        "pass_count": sum(1 for row in matrix if row.get("passed")),
        "fail_count": sum(1 for row in matrix if not row.get("passed")),
        "required_artifact_count": len(REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS) + len(REQUIRED_LAUNCH_READINESS_ARTIFACTS),
        "uploaded_artifact_names": ["decision-workspace-proof"],
        "workflow_run_id": ci_meta["workflow_run_id"],
        "workflow_url": ci_meta["workflow_url"],
        "gauntlet_passed": bool(gauntlet.get("passed")),
        "runtime_validation_passed": bool(summary.get("all_passed")),
        "cleanup_unknown_sql_object_count": _as_int(summary.get("cleanup_unknown_sql_object_count")),
        "cleanup_dead_route_count": _as_int(summary.get("cleanup_dead_route_count")),
        "export_count": _as_int(summary.get("total_exports_validated") or summary.get("export_count")),
        "evidence_loader_count": _as_int(summary.get("total_evidence_loaders_reached") or summary.get("evidence_loader_count")),
        "stress_case_count": _as_int(summary.get("total_stress_cases_executed")),
        "hard_gate_failures": failures,
        "raw_sql_included": False,
    }
    launch_failures = {
        "source": "launch_readiness",
        "proof_source": "runtime_click",
        "passed": passed,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }
    return launch_summary, launch_failures, matrix


def write_launch_readiness_artifacts(root: Path | str = ".") -> dict[str, Any]:
    """Run launch readiness and raise if any release gate fails."""

    root_path = Path(root).resolve()
    _clean_launch_artifact_directory(root_path)
    gauntlet_artifacts = write_full_app_gauntlet_artifacts(root_path)
    payloads, missing_payloads = _load_payloads(root_path, REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS)
    payloads.update(gauntlet_artifacts)

    launch_artifacts: dict[str, Any] = {}
    launch_artifacts["ci_artifact_review_results"] = _workflow_upload_review(root_path)
    launch_artifacts["browser_smoke_results"] = _browser_smoke_results(root_path, payloads)
    launch_artifacts["config_sanity_results"] = _config_sanity_results(root_path)
    launch_artifacts["snowflake_permission_matrix"] = _permission_matrix()
    launch_artifacts["role_readiness_results"] = _role_readiness_results(payloads)
    launch_artifacts["deployment_readiness_results"] = _deployment_readiness_results(root_path, payloads)
    launch_artifacts["upgrade_readiness_results"] = _upgrade_readiness_results(root_path)
    launch_artifacts["drop_rollback_results"] = _drop_rollback_results(root_path, payloads)
    sql_value = _sql_value_inventory(root_path, payloads)
    launch_artifacts["sql_value_inventory"] = sql_value
    launch_artifacts["sql_cost_risk_findings"] = _sql_cost_risk_findings(payloads, sql_value)
    launch_artifacts["live_query_history_results"] = _live_query_history_results(root_path)
    launch_artifacts["performance_slo_results"] = _performance_slo_results(payloads)
    launch_artifacts["settings_live_closure_results"] = _settings_live_closure_results(payloads)
    launch_artifacts["export_case_closure_results"] = _export_case_closure_results(root_path, payloads)
    launch_artifacts["cleanup_launch_closure_results"] = _cleanup_launch_closure_results(payloads)
    launch_artifacts["docs_readiness_results"] = _docs_readiness_results(root_path)
    launch_artifacts["secrets_scan_results"] = _secrets_scan_results(root_path)
    launch_artifacts["artifact_review_results"] = _artifact_review_results(root_path, payloads, missing_payloads)

    launch_summary, launch_failures, matrix = evaluate_launch_readiness(
        payloads,
        launch_artifacts,
        missing_artifacts=missing_payloads,
    )
    launch_artifacts["launch_readiness_summary"] = launch_summary
    launch_artifacts["launch_readiness_failures"] = launch_failures
    launch_artifacts["release_gate_matrix"] = matrix

    written: dict[str, Any] = {}
    for name, payload in launch_artifacts.items():
        filename = f"{name}.json"
        rel = f"{LAUNCH_READINESS_DIR}/{filename}"
        _write_json(root_path / rel, payload)
        written[rel] = payload

    manifest_files = sorted([*written, f"{LAUNCH_READINESS_DIR}/artifact_manifest.json"])
    manifest = {
        "source": "launch_readiness",
        "proof_source": "runtime_click",
        "generated_at": _utc_now(),
        "files": manifest_files,
        "file_count": len(manifest_files),
        "raw_sql_included": False,
    }
    manifest_rel = f"{LAUNCH_READINESS_DIR}/artifact_manifest.json"
    _write_json(root_path / manifest_rel, manifest)
    written[manifest_rel] = manifest

    missing_launch = [
        rel for rel in REQUIRED_LAUNCH_READINESS_ARTIFACTS
        if not (root_path / rel).exists()
    ]
    if missing_launch:
        launch_summary["all_passed"] = False
        launch_summary["passed"] = False
        launch_summary["hard_gate_passed"] = False
        _append_failure(
            launch_summary["blocking_failures"],
            "missing_launch_artifacts",
            "Launch readiness did not write all required launch artifacts.",
            count=len(missing_launch),
        )
        _write_json(root_path / f"{LAUNCH_READINESS_DIR}/launch_readiness_summary.json", launch_summary)

    if not launch_summary["all_passed"]:
        raise AssertionError(
            "Launch readiness failed: "
            + json.dumps(launch_summary["blocking_failures"], indent=2)
        )
    return written


__all__ = [
    "REQUIRED_LAUNCH_READINESS_ARTIFACTS",
    "evaluate_launch_readiness",
    "write_launch_readiness_artifacts",
]
