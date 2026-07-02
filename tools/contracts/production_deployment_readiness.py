"""Production deployment readiness proof.

This contract is intentionally release-facing: it proves that setup, roles,
privileges, token-backed validation, alert routing, and rollback expectations
are documented and represented in sanitized launch artifacts. It records
requirement IDs and pass/fail proof, not raw SQL bodies or secret paths.
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


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

PRODUCTION_DEPLOYMENT_READINESS_RESULTS_REL = (
    f"{FULL_APP_VALIDATION_DIR}/production_deployment_readiness_results.json"
)
PRODUCTION_DEPLOYMENT_READINESS_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/production_deployment_readiness_gate_results.json"
)

PRODUCER = "production_deployment_readiness"
APPROVED_ALERT_EMAIL = "jdees@alfains.com"
TARGET_ROLES = ("OVERWATCH_VIEWER", "OVERWATCH_OPERATOR", "OVERWATCH_ADMIN")
REQUIRED_ENV_VARS = (
    "OVERWATCH_SNOWFLAKE_CLI_CONNECTION",
    "OVERWATCH_LAUNCH_PROFILE",
    "OVERWATCH_SNOWFLAKE_CLI_AUTHENTICATOR",
    "OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH",
    "OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE",
    "OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA",
    "OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE",
)
REQUIRED_PRIVILEGE_DOCS: Mapping[str, tuple[str, ...]] = {
    "create_database_schema_warehouse_task_procedure": (
        "CREATE DATABASE",
        "CREATE SCHEMA",
        "CREATE WAREHOUSE",
        "TASK",
        "PROCEDURE",
    ),
    "account_history_select": ("SELECT from SNOWFLAKE.ACCOUNT_USAGE views",),
    "monitor_account": ("MONITOR ACCOUNT",),
    "warehouse_usage": ("GRANT USAGE ON WAREHOUSE",),
    "database_schema_usage": ("GRANT USAGE ON DATABASE", "GRANT USAGE ON SCHEMA"),
    "notification_integration": ("NOTIFICATION INTEGRATION", "ALERT_EMAIL_NOTIFICATION_INTEGRATION"),
}
REQUIRED_SETUP_FILES = (
    "snowflake/OVERWATCH_MART_SETUP.sql",
    "snowflake/OVERWATCH_MART_VALIDATION.sql",
    "snowflake/OVERWATCH_MART_DROP.sql",
)
REQUIRED_SETUP_OBJECTS = (
    "OVERWATCH_SCHEMA_MIGRATION",
    "MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT",
    "USER_DISPLAY_DIMENSION_COLUMNS",
    "MART_SECTION_DECISION_CURRENT",
    "MART_SECTION_DECISION_CURRENT_FLAT",
    "OVERWATCH_DECISION_SETUP_HEALTH",
)
TOKEN_PATH_MARKERS = (
    "TOK_CJ-token-secret",
    "overwatch_pat.txt",
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


def _read_text(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _repo_text(root: Path, rels: Iterable[str]) -> str:
    return "\n".join(_read_text(root, rel) for rel in rels)


def _payload_text(payloads: Mapping[str, Any]) -> str:
    safe_payloads = {
        key: value
        for key, value in payloads.items()
        if isinstance(value, (dict, list, str, int, float, bool, type(None)))
    }
    try:
        return json.dumps(safe_payloads, sort_keys=True, default=str)
    except TypeError:
        return ""


def _load_json(root: Path, rel: str) -> Mapping[str, Any]:
    try:
        payload = json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _producer_signature(row: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {
            "producer": PRODUCER,
            "check": row.get("check"),
            "passed": row.get("passed"),
            "section": row.get("section", "Production Deployment"),
            "workflow": row.get("workflow", "Release candidate"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _make_row(
    *,
    check: str,
    passed: bool,
    failure_reason: str = "",
    details: Mapping[str, Any] | None = None,
    commit_sha: str = "",
) -> dict[str, Any]:
    row = {
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "commit_sha": commit_sha,
        "generated_at": _utc_now(),
        "source": "production_deployment_readiness",
        "runtime_source": "sanitized_release_inventory",
        "section": "Production Deployment",
        "workflow": "Release candidate",
        "check": check,
        "passed": passed,
        "failure_reason": "" if passed else failure_reason,
        "raw_sql_included": False,
    }
    if details:
        row.update(details)
    row["producer_signature"] = _producer_signature(row)
    return row


def _contains_all(text: str, terms: Iterable[str]) -> bool:
    upper = text.upper()
    return all(term.upper() in upper for term in terms)


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    upper = text.upper()
    return any(term.upper() in upper for term in terms)


def _token_path_leak_count(root: Path, payloads: Mapping[str, Any]) -> int:
    markers = [marker for marker in TOKEN_PATH_MARKERS]
    token_path = os.environ.get("OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH", "").strip()
    if token_path:
        markers.extend(
            marker
            for marker in (token_path, Path(token_path).name)
            if marker and marker not in markers
        )
    artifact_text_parts: list[str] = [_payload_text(payloads)]
    artifacts_dir = root / "artifacts"
    if artifacts_dir.exists():
        for path in artifacts_dir.rglob("*.json"):
            try:
                artifact_text_parts.append(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    artifact_text = "\n".join(artifact_text_parts)
    return sum(artifact_text.count(marker) for marker in markers if marker)


def _temp_path_leak_count(root: Path, payloads: Mapping[str, Any]) -> int:
    artifact_text = _payload_text(payloads)
    artifacts_dir = root / "artifacts"
    if artifacts_dir.exists():
        chunks = [artifact_text]
        for path in artifacts_dir.rglob("*.json"):
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
        artifact_text = "\n".join(chunks)
    return len(re.findall(r"overwatch_snowflake_validation_[^\\/\s\"']+\.sql", artifact_text, flags=re.IGNORECASE))


def build_production_deployment_readiness_results(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    payloads = payloads or {}
    commit_sha = _git_sha(root_path)
    setup_text = _read_text(root_path, "snowflake/OVERWATCH_MART_SETUP.sql")
    validation_text = _read_text(root_path, "snowflake/OVERWATCH_MART_VALIDATION.sql")
    cleanup_text = _read_text(root_path, "docs/PRODUCTION_READINESS_CLEANUP.md")
    cli_doc_text = _read_text(root_path, "docs/snowflake_cli_live_validation.md")
    script_text = _repo_text(
        root_path,
        (
            "scripts/run_snowflake_cli_live_validation.ps1",
            "scripts/run_snowflake_cli_live_validation.sh",
            "tools/contracts/snowflake_cli_live_validation.py",
        ),
    )
    combined_docs = "\n".join((setup_text, validation_text, cleanup_text, cli_doc_text, script_text))

    rows: list[dict[str, Any]] = []
    for rel in REQUIRED_SETUP_FILES:
        rows.append(
            _make_row(
                check=f"required_file::{rel}",
                passed=(root_path / rel).exists(),
                failure_reason=f"Required setup/release file is missing: {rel}",
                details={"artifact": rel},
                commit_sha=commit_sha,
            )
        )

    split_setup_files = sorted((root_path / "snowflake" / "mart_setup").glob("*.sql"))
    rows.append(
        _make_row(
            check="split_setup_files_present",
            passed=bool(split_setup_files),
            failure_reason="Split setup SQL files are missing.",
            details={"split_setup_file_count": len(split_setup_files)},
            commit_sha=commit_sha,
        )
    )

    for role in TARGET_ROLES:
        rows.append(
            _make_row(
                check=f"role_documented::{role}",
                passed=role in combined_docs,
                failure_reason=f"Required production role is not documented: {role}",
                details={"role_name": role},
                commit_sha=commit_sha,
            )
        )

    for privilege_id, terms in REQUIRED_PRIVILEGE_DOCS.items():
        rows.append(
            _make_row(
                check=f"privilege_documented::{privilege_id}",
                passed=_contains_any(combined_docs, terms) if privilege_id == "notification_integration" else _contains_all(combined_docs, terms),
                failure_reason=f"Required privilege mapping is not documented: {privilege_id}",
                details={"privilege_id": privilege_id},
                commit_sha=commit_sha,
            )
        )

    for env_var in REQUIRED_ENV_VARS:
        rows.append(
            _make_row(
                check=f"secret_env_documented::{env_var}",
                passed=env_var in combined_docs,
                failure_reason=f"Required secret/environment variable is not documented: {env_var}",
                details={"env_var": env_var},
                commit_sha=commit_sha,
            )
        )

    rows.append(
        _make_row(
            check="token_auth_supported",
            passed="PROGRAMMATIC_ACCESS_TOKEN" in combined_docs and "--token-file-path" in combined_docs,
            failure_reason="Token-backed Snowflake CLI validation is not documented or wired.",
            details={"token_file_supplied_only": True},
            commit_sha=commit_sha,
        )
    )

    token_leak_count = _token_path_leak_count(root_path, payloads)
    temp_path_leak_count = _temp_path_leak_count(root_path, payloads)
    rows.append(
        _make_row(
            check="token_path_not_serialized",
            passed=token_leak_count == 0,
            failure_reason="Token file path or token filename leaked into artifacts.",
            details={"token_path_leak_count": token_leak_count},
            commit_sha=commit_sha,
        )
    )
    rows.append(
        _make_row(
            check="temp_sql_path_not_serialized",
            passed=temp_path_leak_count == 0,
            failure_reason="Temporary Snowflake SQL file path leaked into artifacts.",
            details={"temp_sql_path_leak_count": temp_path_leak_count},
            commit_sha=commit_sha,
        )
    )

    config_text = _read_text(root_path, ".overwatch_final/config.py")
    setup_email_seed_ok = APPROVED_ALERT_EMAIL.upper() in setup_text.upper()
    config_email_ok = APPROVED_ALERT_EMAIL in config_text
    placeholder_default = "DBA-ALERTS@YOURCOMPANY.COM" in setup_text.upper() or "DBA-ALERTS@YOURCOMPANY.COM" in config_text.upper()
    rows.append(
        _make_row(
            check="alert_email_default_governed",
            passed=setup_email_seed_ok and config_email_ok and not placeholder_default,
            failure_reason="Production alert email default is missing or still uses a placeholder.",
            details={"approved_alert_email_configured": setup_email_seed_ok and config_email_ok},
            commit_sha=commit_sha,
        )
    )

    for object_name in REQUIRED_SETUP_OBJECTS:
        rows.append(
            _make_row(
                check=f"required_object_represented::{object_name.lower()}",
                passed=object_name in setup_text or object_name in validation_text,
                failure_reason=f"Required deployment object is not represented in setup/validation: {object_name}",
                details={"object_family": object_name.lower().replace("overwatch_", "").replace("mart_", "")},
                commit_sha=commit_sha,
            )
        )

    setup_gate = (
        payloads.get("artifacts/launch_readiness/setup_migration_live_gate_results.json")
        or payloads.get("setup_migration_live_gate_results")
        or _load_json(root_path, "artifacts/launch_readiness/setup_migration_live_gate_results.json")
        or {}
    )
    setup_gate_mapping = setup_gate if isinstance(setup_gate, Mapping) else {}
    setup_live_passed = bool(
        setup_gate_mapping.get("passed")
        or setup_gate_mapping.get("setup_migration_live_passed")
        or setup_gate_mapping.get("skipped")
    )
    rows.append(
        _make_row(
            check="setup_migration_live_status_present",
            passed=setup_live_passed,
            failure_reason="Setup/migration live or fixture-skip gate is missing.",
            details={
                "setup_migration_live_status": str(
                    setup_gate_mapping.get("live_validation_status")
                    or setup_gate_mapping.get("status")
                    or ("passed" if setup_live_passed else "missing")
                )
            },
            commit_sha=commit_sha,
        )
    )

    temp_gate = (
        payloads.get("artifacts/launch_readiness/snowflake_cli_temp_file_hygiene_gate_results.json")
        or payloads.get("snowflake_cli_temp_file_hygiene_gate_results")
        or _load_json(root_path, "artifacts/launch_readiness/snowflake_cli_temp_file_hygiene_gate_results.json")
        or {}
    )
    temp_gate_mapping = temp_gate if isinstance(temp_gate, Mapping) else {}
    rows.append(
        _make_row(
            check="temp_file_hygiene_gate_present",
            passed=bool(temp_gate_mapping.get("passed") or temp_gate_mapping.get("snowflake_cli_temp_file_hygiene_passed")),
            failure_reason="Snowflake CLI temp-file hygiene gate is missing or failed.",
            details={
                "temp_sql_file_leftover_count": int(temp_gate_mapping.get("temp_sql_file_leftover_count") or 0)
            },
            commit_sha=commit_sha,
        )
    )

    rows.append(
        _make_row(
            check="rollback_drop_ready",
            passed=(root_path / "snowflake" / "OVERWATCH_MART_DROP.sql").exists() and "Do not execute grants" in cleanup_text,
            failure_reason="Rollback/drop plan or reviewed-grant warning is missing.",
            details={"rollback_ready": True},
            commit_sha=commit_sha,
        )
    )

    failures = [row for row in rows if not bool(row.get("passed"))]
    results = {
        "source": "production_deployment_readiness_results",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": commit_sha,
        "passed": not failures,
        "production_deployable": not failures,
        "rollback_ready": any(row.get("check") == "rollback_drop_ready" and row.get("passed") for row in rows),
        "failure_count": len(failures),
        "role_count": len(TARGET_ROLES),
        "privilege_mapping_count": len(REQUIRED_PRIVILEGE_DOCS),
        "secret_env_var_count": len(REQUIRED_ENV_VARS),
        "token_path_leak_count": token_leak_count,
        "temp_sql_path_leak_count": temp_path_leak_count,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }
    return results


def evaluate_production_deployment_readiness_gate(payload: object) -> dict[str, Any]:
    results = payload if isinstance(payload, Mapping) else {}
    failures = list(results.get("failures") or [])
    if not results:
        failures = [
            {
                "check": "production_deployment_readiness_missing",
                "failure_reason": "Production deployment readiness artifact is missing.",
            }
        ]
    elif not bool(results.get("passed")) and not failures:
        failures = [
            {
                "check": "production_deployment_readiness_failed",
                "failure_reason": "Production deployment readiness failed.",
            }
        ]
    return {
        "source": "production_deployment_readiness_gate_results",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "passed": not failures and bool(results.get("passed")),
        "production_deployable": not failures and bool(results.get("production_deployable", results.get("passed"))),
        "production_deployment_readiness_passed": not failures and bool(results.get("passed")),
        "rollback_ready": bool(results.get("rollback_ready")),
        "failure_count": len(failures),
        "role_count": int(results.get("role_count") or 0),
        "privilege_mapping_count": int(results.get("privilege_mapping_count") or 0),
        "secret_env_var_count": int(results.get("secret_env_var_count") or 0),
        "token_path_leak_count": int(results.get("token_path_leak_count") or 0),
        "temp_sql_path_leak_count": int(results.get("temp_sql_path_leak_count") or 0),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_production_deployment_readiness_artifacts(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_production_deployment_readiness_results(root_path, payloads or {})
    gate = evaluate_production_deployment_readiness_gate(results)
    artifacts = {
        PRODUCTION_DEPLOYMENT_READINESS_RESULTS_REL: results,
        PRODUCTION_DEPLOYMENT_READINESS_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        path = root_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifacts


if __name__ == "__main__":
    written = write_production_deployment_readiness_artifacts(Path("."))
    gate = written[PRODUCTION_DEPLOYMENT_READINESS_GATE_REL]
    print(json.dumps(gate, indent=2, sort_keys=True))
    raise SystemExit(0 if gate.get("passed") else 1)


__all__ = [
    "PRODUCTION_DEPLOYMENT_READINESS_GATE_REL",
    "PRODUCTION_DEPLOYMENT_READINESS_RESULTS_REL",
    "build_production_deployment_readiness_results",
    "evaluate_production_deployment_readiness_gate",
    "write_production_deployment_readiness_artifacts",
]
