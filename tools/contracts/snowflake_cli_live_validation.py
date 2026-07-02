"""Local Snowflake CLI live validation lane for OVERWATCH launch proof.

The module intentionally stores execution metadata and values, not credentials
or SQL bodies. Public CI normally runs without a Snowflake connection; in that
case internal_fixture writes explicit SKIPPED artifacts that launch readiness can
distinguish from live proof.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from tools.contracts.formula_end_to_end_validation import REQUIRED_PACKET_FIELDS
from tools.contracts.packet_availability_live_validation import (
    PACKET_AVAILABILITY_GATE_REL,
    PACKET_AVAILABILITY_MATRIX_REL,
    SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL,
    evaluate_packet_availability,
    evaluate_packet_availability_gate,
    normalize_packet_window_days,
)


SNOWFLAKE_VALIDATION_DIR = "artifacts/snowflake_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
RELEASE_CANDIDATE_DIR = "artifacts/release_candidate"

CLI_CAPABILITY_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_capability_results.json"
CLI_CONNECTION_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_connection_results.json"
CLI_MANIFEST_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_execution_manifest.json"
CLI_SETUP_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_setup_validation_results.json"
CLI_SETUP_MIGRATION_REL = f"{SNOWFLAKE_VALIDATION_DIR}/setup_migration_live_results.json"
CLI_FORMULA_VALUE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_formula_value_results.json"
CLI_COST_RECONCILIATION_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_cost_reconciliation_results.json"
CLI_PACKET_VALUE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_packet_value_results.json"
CLI_SUMMARY_CARD_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_summary_card_value_results.json"
CLI_QUERY_BUDGET_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_query_budget_results.json"
CLI_MANIFEST_RECONCILIATION_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_manifest_reconciliation_results.json"
CLI_TEMP_FILE_HYGIENE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_temp_file_hygiene_results.json"
CLI_PRODUCTION_REHEARSAL_REL = f"{SNOWFLAKE_VALIDATION_DIR}/production_deployment_rehearsal_results.json"
CLI_LAUNCH_GATE_REL = f"{LAUNCH_READINESS_DIR}/snowflake_cli_live_gate_results.json"
CLI_FORMULA_VALUE_GATE_REL = f"{LAUNCH_READINESS_DIR}/snowflake_cli_formula_value_gate_results.json"
CLI_COST_RECONCILIATION_GATE_REL = f"{LAUNCH_READINESS_DIR}/live_cost_reconciliation_gate_results.json"
CLI_TEMP_FILE_HYGIENE_GATE_REL = f"{LAUNCH_READINESS_DIR}/snowflake_cli_temp_file_hygiene_gate_results.json"
CLI_SETUP_MIGRATION_GATE_REL = f"{LAUNCH_READINESS_DIR}/setup_migration_live_gate_results.json"
CLI_PRODUCTION_REHEARSAL_GATE_REL = f"{LAUNCH_READINESS_DIR}/production_deployment_rehearsal_gate_results.json"
CLI_RELEASE_REL = f"{RELEASE_CANDIDATE_DIR}/snowflake_cli_release_results.json"

CONNECTION_TEST_TIMEOUT_SECONDS = 240

REQUIRED_CLI_ARTIFACTS = {
    CLI_CAPABILITY_REL,
    CLI_CONNECTION_REL,
    CLI_MANIFEST_REL,
    CLI_SETUP_REL,
    CLI_SETUP_MIGRATION_REL,
    CLI_FORMULA_VALUE_REL,
    CLI_COST_RECONCILIATION_REL,
    CLI_PACKET_VALUE_REL,
    PACKET_AVAILABILITY_MATRIX_REL,
    SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL,
    CLI_SUMMARY_CARD_REL,
    CLI_QUERY_BUDGET_REL,
    CLI_MANIFEST_RECONCILIATION_REL,
    CLI_TEMP_FILE_HYGIENE_REL,
    CLI_PRODUCTION_REHEARSAL_REL,
    CLI_LAUNCH_GATE_REL,
    CLI_FORMULA_VALUE_GATE_REL,
    CLI_COST_RECONCILIATION_GATE_REL,
    CLI_TEMP_FILE_HYGIENE_GATE_REL,
    CLI_SETUP_MIGRATION_GATE_REL,
    CLI_PRODUCTION_REHEARSAL_GATE_REL,
    PACKET_AVAILABILITY_GATE_REL,
    CLI_RELEASE_REL,
}

TEMP_SQL_PREFIX = "overwatch_snowflake_validation_"
TEMP_SQL_SUFFIX = ".sql"
_TEMP_SQL_EVENTS: list[dict[str, Any]] = []

PRIMARY_SECTIONS = (
    "Executive Landing",
    "Cost & Contract",
    "Workload Operations",
    "DBA Control Room",
    "Alert Center",
    "Security Monitoring",
)

NUMERIC_FORMULA_FIELDS = {
    "ACCOUNT_BILLED_CREDITS",
    "ACCOUNT_BILLED_COST_USD",
    "ACCOUNT_USED_CREDITS",
    "COMPUTE_CREDITS",
    "CLOUD_SERVICES_CREDITS",
    "CLOUD_SERVICES_ADJUSTMENT",
    "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT",
    "WAREHOUSE_CREDITS",
    "WAREHOUSE_COST_ESTIMATE_USD",
    "WAREHOUSE_COST_USD",
    "SERVICE_OTHER_CREDITS",
    "SERVICE_OTHER_COST_USD",
    "BILLING_BRIDGE_DELTA_CREDITS",
    "BILLING_BRIDGE_DELTA_USD",
    "CORTEX_AI_CREDITS",
    "CORTEX_AI_COST_USD",
    "SPEND_MOVEMENT_PCT",
    "FORECAST_RUN_RATE_USD",
}

CORTEX_SERVICE_TYPES = (
    "CORTEX",
    "CORTEX_AI",
    "CORTEX_FUNCTIONS",
    "CORTEX_SEARCH",
    "CORTEX_ANALYST",
    "DOCUMENT_AI",
    "FINE_TUNING",
    "AI_SERVICES",
)

REQUIRED_QUERY_BUDGET_BOUNDARIES = tuple(
    (section, "summary_board", boundary)
    for section in PRIMARY_SECTIONS
    for boundary in ("first_paint_packet", "warm_first_paint", "route_action")
) + (
    ("Query Search", "query_search", "query_search_no_click"),
    ("Cost & Contract", "cost_workbench", "cost_workbench"),
)

CREDIT_COLUMN_BY_FIELD = {
    "ACCOUNT_BILLED_CREDITS": "CREDITS_BILLED",
    "ACCOUNT_BILLED_COST_USD": "CREDITS_BILLED",
    "ACCOUNT_USED_CREDITS": "CREDITS_USED",
    "COMPUTE_CREDITS": "CREDITS_USED_COMPUTE",
    "CLOUD_SERVICES_CREDITS": "CREDITS_USED_CLOUD_SERVICES",
    "WAREHOUSE_CREDITS": "CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES",
    "WAREHOUSE_COST_ESTIMATE_USD": "CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES",
    "WAREHOUSE_COST_USD": "CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES",
    "SERVICE_OTHER_CREDITS": "CREDITS_BILLED - WAREHOUSE_CREDITS",
    "SERVICE_OTHER_COST_USD": "CREDITS_BILLED - WAREHOUSE_CREDITS",
    "BILLING_BRIDGE_DELTA_CREDITS": "CREDITS_BILLED - WAREHOUSE_CREDITS",
    "BILLING_BRIDGE_DELTA_USD": "CREDITS_BILLED - WAREHOUSE_CREDITS",
    "CORTEX_AI_CREDITS": "CORTEX_SERVICE_ALLOWLIST_CREDITS",
    "CORTEX_AI_COST_USD": "CORTEX_SERVICE_ALLOWLIST_CREDITS",
}

RENDERED_SUMMARY_FIELDS = {
    "ACCOUNT_BILLED_COST_USD",
    "CORTEX_AI_COST_USD",
    "SPEND_MOVEMENT_PCT",
    "FORECAST_RUN_RATE_USD",
}

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class SnowflakeCliValidationOptions:
    connection: str = ""
    profile: str = "internal_fixture"
    authenticator: str = ""
    token_file_path: str = ""
    database: str = ""
    schema: str = ""
    warehouse: str = ""
    role: str = ""
    company: str = "ALL"
    environment: str = "ALL"
    window_days: int = 8
    credit_price: float = 3.68
    ai_credit_price: float = 2.20
    run_fast_refresh: bool = False
    run_full_refresh_dry_run: bool = False
    skip_refresh: bool = False
    output_dir: str = SNOWFLAKE_VALIDATION_DIR
    query_history_enabled: bool = False
    query_tag_prefix: str = "OVERWATCH_VALIDATION"
    perf_run_id: str = ""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_text(value: object) -> str:
    return "" if value is None else str(value)


def _safe_label(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.@:/ -]", "", value or "").strip()
    return text[:120]


def _sensitive_env_values() -> list[str]:
    values: list[str] = []
    for key, value in os.environ.items():
        if not value or len(value) < 4:
            continue
        if re.search(r"(TOKEN|PASSWORD|PASSCODE|PRIVATE|SECRET|KEY|CONNECTION_STRING)", key, re.IGNORECASE):
            values.append(value)
    return sorted(values, key=len, reverse=True)


def sanitize_text(value: object, *, allow_raw_sql: bool | None = None) -> str:
    """Remove secrets, SQL bodies, stack frames, and connection strings."""

    text = _as_text(value)
    for secret in _sensitive_env_values():
        text = text.replace(secret, "[REDACTED_SECRET]")
    text = re.sub(
        r"(?is)\b(password|passcode|token|oauth[_-]?token|session[_-]?token|private[_-]?key|connection[_-]?string)\b\s*[:=]\s*['\"]?[^'\"\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?is)\b(private[_-]?key[_-]?file|token[_-]?file[_-]?path)\b\s*[:=]\s*['\"]?[^'\"\r\n]+",
        r"\1=[REDACTED_PATH]",
        text,
    )
    text = re.sub(r"(?is)(--token-file-path\s+)['\"]?[^'\"\s\r\n]+", r"\1[REDACTED_PATH]", text)
    text = re.sub(
        r"(?is)([A-Za-z]:\\|/)[^'\"\r\n]*overwatch_snowflake_validation_[^'\"\r\n]*\.sql",
        "[SQL_FILE_REDACTED]",
        text,
    )
    text = re.sub(
        r"(?im)^\s*[A-Za-z]:\\[^\r\n]*site-packages[^\r\n]*:\d+:\s*UserWarning:.*$",
        "Snowflake CLI warning redacted.",
        text,
    )
    text = re.sub(r"(?im)^\s*warnings\.warn\(.*$", "", text)
    text = re.sub(r"(?i)[A-Za-z]:\\[^\s\r\n]*site-packages[^\r\n]*", "[LOCAL_PATH_REDACTED]", text)
    text = re.sub(r"(?i)(https://)[A-Za-z0-9_.-]+\.snowflakecomputing\.com", r"\1[REDACTED_ACCOUNT].snowflakecomputing.com", text)
    text = re.sub(
        r"(?is)An unexpected exception occurred\.\s*Use --debug option to see the traceback\.\s*Exception message:\s*",
        "Snowflake CLI failed before query execution: ",
        text,
    )
    text = re.sub(
        r"(?is)\(\s*\d+\s*,\s*['\"]CredWrite['\"]\s*,\s*['\"][^'\"]+['\"]\s*\)",
        "local credential store write failed",
        text,
    )
    text = re.sub(r"(?is)Traceback \(most recent call last\):.*", "[STACK_TRACE_REDACTED]", text)
    text = re.sub(r'File "[^"]+", line \d+.*', "[STACK_FRAME_REDACTED]", text)
    text = re.sub(r"(?i)\btraceback\b", "debug details", text)
    if allow_raw_sql is None:
        allow_raw_sql = os.environ.get("OVERWATCH_ALLOW_RAW_SQL_PROOF") == "1"
    if not allow_raw_sql:
        text = re.sub(
            r"(?is)\b(SELECT|WITH|INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|CALL)\b.+",
            "[SQL_REDACTED]",
            text,
        )
    return text[:2000]


def _snowflake_cli_path() -> str:
    configured = os.environ.get("OVERWATCH_SNOWFLAKE_CLI_PATH", "").strip()
    if configured and Path(configured).exists():
        return configured
    discovered = shutil.which("snow")
    if discovered:
        return discovered
    home = Path.home()
    candidates = [
        home / "AppData" / "Roaming" / "Python" / "Python312" / "Scripts" / "snow.exe",
        home / "AppData" / "Roaming" / "Python" / "Python311" / "Scripts" / "snow.exe",
        home / ".local" / "bin" / "snow",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return "snow"


def _command_scope(options: SnowflakeCliValidationOptions) -> list[str]:
    args = ["-c", options.connection]
    args.extend(_auth_scope(options))
    if options.database:
        args.extend(["--database", options.database])
    if options.schema:
        args.extend(["--schema", options.schema])
    if options.warehouse:
        args.extend(["--warehouse", options.warehouse])
    if options.role:
        args.extend(["--role", options.role])
    return args


def _auth_scope(options: SnowflakeCliValidationOptions) -> list[str]:
    args: list[str] = []
    if options.authenticator:
        args.extend(["--authenticator", options.authenticator])
    if options.token_file_path:
        args.extend(["--token-file-path", options.token_file_path])
    return args


def _connection_test_scope(options: SnowflakeCliValidationOptions) -> list[str]:
    args = ["-c", options.connection]
    args.extend(_auth_scope(options))
    return args


def _run(
    args: Sequence[str],
    *,
    runner: Runner = subprocess.run,
    timeout_seconds: int = 120,
) -> tuple[subprocess.CompletedProcess[str] | None, int]:
    started = time.perf_counter()
    try:
        proc = runner(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return subprocess.CompletedProcess(list(args), 127, "", str(exc)), elapsed_ms
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return proc, elapsed_ms


def _base_row(
    *,
    phase: str,
    command_kind: str,
    options: SnowflakeCliValidationOptions,
    elapsed_ms: int = 0,
    status: str = "skipped",
    row_count: int | None = None,
    sanitized_error: str = "",
    recommendation: str = "",
) -> dict[str, Any]:
    return {
        "phase": phase,
        "command_kind": command_kind,
        "connection_name": _safe_label(options.connection),
        "authenticator": _safe_label(options.authenticator),
        "token_file_supplied": bool(options.token_file_path),
        "sanitized_account": "",
        "sanitized_role": _safe_label(options.role),
        "sanitized_database": _safe_label(options.database),
        "sanitized_schema": _safe_label(options.schema),
        "sanitized_warehouse": _safe_label(options.warehouse),
        "elapsed_ms": elapsed_ms,
        "status": status,
        "row_count": row_count,
        "sanitized_error": sanitize_text(sanitized_error),
        "raw_sql_included": False,
        "temp_sql_file_used": False,
        "temp_sql_file_deleted": False,
        "temp_sql_file_path_stored": False,
        "recommendation": recommendation,
    }


def _assign_validation_ids(artifacts: Mapping[str, Any]) -> None:
    counter = 1
    for rel in (
        CLI_CAPABILITY_REL,
        CLI_CONNECTION_REL,
        CLI_SETUP_REL,
        CLI_SETUP_MIGRATION_REL,
        SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL,
        CLI_PACKET_VALUE_REL,
        CLI_FORMULA_VALUE_REL,
        CLI_COST_RECONCILIATION_REL,
        CLI_SUMMARY_CARD_REL,
        CLI_QUERY_BUDGET_REL,
        CLI_TEMP_FILE_HYGIENE_REL,
    ):
        payload = artifacts.get(rel)
        if not isinstance(payload, dict):
            continue
        rows = payload.get("rows")
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            row["validation_id"] = row.get("validation_id") or f"snowflake-cli-{counter:04d}"
            row["artifact"] = Path(rel).name
            row["row_index"] = index
            counter += 1


def _manifest_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        entry = {
            "validation_id": str(row.get("validation_id") or f"snowflake-cli-{index + 1:04d}"),
            "artifact": str(row.get("artifact") or ""),
            "row_index": int(row.get("row_index") or 0),
            "phase": str(row.get("phase") or ""),
            "command_kind": str(row.get("command_kind") or ""),
            "connection_name": str(row.get("connection_name") or ""),
            "status": str(row.get("status") or ""),
            "elapsed_ms": int(row.get("elapsed_ms") or 0),
            "raw_sql_included": bool(row.get("raw_sql_included")),
            "sanitized_error": str(row.get("sanitized_error") or ""),
            "recommendation": str(row.get("recommendation") or ""),
        }
        if entry["status"] == "failed":
            failures.append({"code": "SNOWFLAKE_CLI_EXECUTION_FAILED", "phase": entry["phase"]})
        if entry["raw_sql_included"]:
            failures.append({"code": "SNOWFLAKE_CLI_RAW_SQL_INCLUDED", "phase": entry["phase"]})
        entries.append(entry)
    return {
        "source": "snowflake_cli_execution_manifest",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "entry_count": len(entries),
        "entries": entries,
        "raw_sql_included": False,
    }


def _manifest_reconciliation_results(artifacts: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    raw_entries = manifest.get("entries")
    entries: list[Any] = raw_entries if isinstance(raw_entries, list) else []
    entry_by_id = {str(entry.get("validation_id")): entry for entry in entries if isinstance(entry, Mapping)}
    seen_ids: set[str] = set()
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for rel in (
        CLI_CAPABILITY_REL,
        CLI_CONNECTION_REL,
        CLI_SETUP_REL,
        CLI_SETUP_MIGRATION_REL,
        SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL,
        CLI_PACKET_VALUE_REL,
        CLI_FORMULA_VALUE_REL,
        CLI_COST_RECONCILIATION_REL,
        CLI_SUMMARY_CARD_REL,
        CLI_QUERY_BUDGET_REL,
        CLI_TEMP_FILE_HYGIENE_REL,
    ):
        payload = artifacts.get(rel)
        raw_payload_rows = payload.get("rows") if isinstance(payload, Mapping) else None
        payload_rows: list[Any] = raw_payload_rows if isinstance(raw_payload_rows, list) else []
        for index, row in enumerate(payload_rows):
            if not isinstance(row, Mapping):
                continue
            validation_id = str(row.get("validation_id") or "")
            entry = entry_by_id.get(validation_id)
            status = "passed"
            failure_reason = ""
            if not validation_id:
                status = "failed"
                failure_reason = "Artifact row is missing validation_id."
                failures.append({"code": "SNOWFLAKE_CLI_MANIFEST_ID_MISSING", "artifact": rel, "row_index": index})
            elif entry is None:
                status = "failed"
                failure_reason = "Artifact row points to an unknown manifest validation_id."
                failures.append({"code": "SNOWFLAKE_CLI_MANIFEST_ID_UNKNOWN", "artifact": rel, "validation_id": validation_id})
            else:
                seen_ids.add(validation_id)
                entry_row_index = entry.get("row_index")
                if int(entry_row_index if entry_row_index is not None else -1) != index:
                    status = "failed"
                    failure_reason = "Manifest row_index does not match artifact row_index."
                    failures.append({"code": "SNOWFLAKE_CLI_MANIFEST_ROW_INDEX_MISMATCH", "validation_id": validation_id})
                if str(entry.get("artifact") or "") != Path(rel).name:
                    status = "failed"
                    failure_reason = "Manifest artifact does not match source artifact."
                    failures.append({"code": "SNOWFLAKE_CLI_MANIFEST_ARTIFACT_MISMATCH", "validation_id": validation_id})
                if str(entry.get("status") or "") != str(row.get("status") or ""):
                    status = "failed"
                    failure_reason = "Manifest status contradicts artifact row status."
                    failures.append({"code": "SNOWFLAKE_CLI_MANIFEST_STATUS_MISMATCH", "validation_id": validation_id})
            serialized = json.dumps(row, default=str)
            if bool(row.get("raw_sql_included")):
                status = "failed"
                failure_reason = "Artifact row includes raw SQL."
                failures.append({"code": "SNOWFLAKE_CLI_MANIFEST_RAW_SQL_INCLUDED", "validation_id": validation_id})
            if re.search(r"(?i)(password|token|private[_-]?key|connection[_-]?string)\s*[:=]", serialized):
                status = "failed"
                failure_reason = "Artifact row includes secret-like text."
                failures.append({"code": "SNOWFLAKE_CLI_MANIFEST_SECRET_LIKE_TEXT", "validation_id": validation_id})
            rows.append(
                {
                    "validation_id": validation_id,
                    "artifact": Path(rel).name,
                    "row_index": index,
                    "status": status,
                    "failure_reason": failure_reason,
                    "raw_sql_included": False,
                }
            )
    for validation_id, entry in entry_by_id.items():
        if validation_id not in seen_ids:
            failures.append(
                {
                    "code": "SNOWFLAKE_CLI_MANIFEST_ORPHAN_ENTRY",
                    "validation_id": validation_id,
                    "artifact": entry.get("artifact"),
                }
            )
    return _payload(
        source="snowflake_cli_manifest_reconciliation_results",
        rows=rows,
        failures=failures,
        extra={
            "manifest_entry_count": len(entry_by_id),
            "linked_artifact_row_count": len(seen_ids),
            "orphan_manifest_entry_count": len(entry_by_id) - len(seen_ids),
        },
    )


def _payload(
    *,
    source: str,
    rows: list[dict[str, Any]],
    failures: list[dict[str, Any]] | None = None,
    skipped: bool = False,
    skip_reason: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    all_failures = list(failures or [])
    payload: dict[str, Any] = {
        "source": source,
        "generated_at": _utc_now(),
        "passed": not all_failures,
        "failure_count": len(all_failures),
        "failures": all_failures,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "row_count": len(rows),
        "rows": rows,
        "raw_sql_included": False,
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _skipped_artifacts(
    options: SnowflakeCliValidationOptions,
    *,
    reason: str,
) -> dict[str, Any]:
    rows_by_rel: dict[str, list[dict[str, Any]]] = {}
    for rel, phase in (
        (CLI_CAPABILITY_REL, "capability"),
        (CLI_CONNECTION_REL, "connection_test"),
        (CLI_SETUP_REL, "setup_validation"),
        (CLI_SETUP_MIGRATION_REL, "setup_migration_live_validation"),
        (SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL, "packet_availability_validation"),
        (CLI_PACKET_VALUE_REL, "packet_value_validation"),
        (CLI_FORMULA_VALUE_REL, "formula_value_validation"),
        (CLI_COST_RECONCILIATION_REL, "cost_reconciliation_validation"),
        (CLI_SUMMARY_CARD_REL, "summary_card_value_validation"),
        (CLI_QUERY_BUDGET_REL, "query_budget_validation"),
        (CLI_TEMP_FILE_HYGIENE_REL, "temp_sql_file_hygiene"),
    ):
        rows_by_rel[rel] = [
            {
                **_base_row(
                    phase=phase,
                    command_kind="validation",
                    options=options,
                    status="skipped",
                    sanitized_error="",
                    recommendation="Provide --connection or OVERWATCH_SNOWFLAKE_CLI_CONNECTION to run local live validation.",
                ),
                "artifact": Path(rel).name,
                "row_index": 0,
            }
        ]
    artifacts: dict[str, Any] = {
        rel: _payload(source=Path(rel).stem, rows=rows, skipped=True, skip_reason=reason)
        for rel, rows in rows_by_rel.items()
    }
    artifacts[PACKET_AVAILABILITY_MATRIX_REL] = {
        **artifacts[SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL],
        "source": "packet_availability_matrix_results",
    }
    _assign_validation_ids(artifacts)
    manifest = _manifest_from_rows(row for rows in rows_by_rel.values() for row in rows)
    artifacts[CLI_MANIFEST_REL] = manifest
    artifacts[CLI_MANIFEST_RECONCILIATION_REL] = _manifest_reconciliation_results(artifacts, manifest)
    artifacts[CLI_FORMULA_VALUE_GATE_REL] = _formula_value_gate_results(artifacts.get(CLI_FORMULA_VALUE_REL, {}))
    artifacts[CLI_COST_RECONCILIATION_GATE_REL] = _cost_reconciliation_gate_results(artifacts.get(CLI_COST_RECONCILIATION_REL, {}))
    artifacts[CLI_TEMP_FILE_HYGIENE_GATE_REL] = evaluate_temp_file_hygiene_gate(artifacts.get(CLI_TEMP_FILE_HYGIENE_REL, {}))
    artifacts[CLI_SETUP_MIGRATION_GATE_REL] = evaluate_setup_migration_live_gate(artifacts.get(CLI_SETUP_MIGRATION_REL, {}))
    artifacts[PACKET_AVAILABILITY_GATE_REL] = evaluate_packet_availability_gate(
        artifacts.get(PACKET_AVAILABILITY_MATRIX_REL, {})
    )
    gate = evaluate_snowflake_cli_live_gate(artifacts, options.profile, [])
    artifacts[CLI_LAUNCH_GATE_REL] = gate
    artifacts[CLI_PRODUCTION_REHEARSAL_REL] = build_production_deployment_rehearsal_results(
        Path.cwd(),
        artifacts,
        options,
    )
    artifacts[CLI_PRODUCTION_REHEARSAL_GATE_REL] = evaluate_production_deployment_rehearsal_gate(
        artifacts[CLI_PRODUCTION_REHEARSAL_REL]
    )
    artifacts[CLI_RELEASE_REL] = {
        "source": "snowflake_cli_release_results",
        "generated_at": _utc_now(),
        "passed": bool(gate.get("snowflake_cli_gate_passed")),
        "failure_count": int(gate.get("failure_count") or 0),
        "launch_profile": options.profile,
        "snowflake_cli_gate_passed": bool(gate.get("snowflake_cli_gate_passed")),
        "snowflake_cli_live_required": bool(gate.get("snowflake_cli_live_required")),
        "snowflake_cli_live_executed": bool(gate.get("snowflake_cli_live_executed")),
        "snowflake_cli_live_passed": bool(gate.get("snowflake_cli_live_passed")),
        "snowflake_cli_live_skipped": True,
        "snowflake_cli_live_waived": bool(gate.get("snowflake_cli_live_waived")),
        "snowflake_cli_token_auth_used": bool(gate.get("snowflake_cli_token_auth_used")),
        "snowflake_cli_token_file_supplied": bool(gate.get("snowflake_cli_token_file_supplied")),
        "snowflake_cli_token_path_leak_count": int(gate.get("snowflake_cli_token_path_leak_count") or 0),
        "snowflake_cli_temp_sql_path_leak_count": int(gate.get("snowflake_cli_temp_sql_path_leak_count") or 0),
        "snowflake_cli_temp_file_hygiene_passed": bool(gate.get("temp_file_hygiene_passed")),
        "temp_sql_file_leftover_count": int(gate.get("temp_sql_file_leftover_count") or 0),
        "setup_migration_live_passed": bool(gate.get("setup_migration_live_passed")),
        "production_deployment_rehearsal_passed": bool(
            artifacts[CLI_PRODUCTION_REHEARSAL_GATE_REL].get("passed")
        ),
        "skip_reason": reason,
        "raw_sql_included": False,
    }
    return artifacts


def _sql_table(name: str, options: SnowflakeCliValidationOptions) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "", name)
    if options.database and options.schema:
        return f"{_identifier(options.database)}.{_identifier(options.schema)}.{safe}"
    if options.schema:
        return f"{_identifier(options.schema)}.{safe}"
    return safe


def _identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_$]", "", value or "")
    return cleaned or value


def _literal(value: object) -> str:
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def _object_construct_pairs(prefix: str) -> str:
    pairs = []
    for field in REQUIRED_PACKET_FIELDS:
        pairs.append(f"{_literal(field)}, {prefix}.{field}")
    return ", ".join(pairs)


def _section_values_sql() -> str:
    return ", ".join(f"({_literal(section)})" for section in PRIMARY_SECTIONS)


def _packet_flat_sql(options: SnowflakeCliValidationOptions) -> str:
    command_table = _sql_table("MART_SECTION_COMMAND_BRIEF", options)
    flat_table = _sql_table("MART_SECTION_DECISION_CURRENT_FLAT", options)
    lookup_window_days = normalize_packet_window_days(options.window_days)
    company_filter = "" if options.company.upper() == "ALL" else f"AND UPPER(COMPANY)=UPPER({_literal(options.company)})"
    env_filter = "" if options.environment.upper() == "ALL" else f"AND UPPER(ENVIRONMENT)=UPPER({_literal(options.environment)})"
    return f"""
WITH sections AS (
  SELECT column1::VARCHAR AS section_name FROM VALUES {_section_values_sql()}
),
packet AS (
  SELECT *
  FROM {command_table}
  WHERE WINDOW_DAYS = {lookup_window_days}
    {company_filter}
    {env_filter}
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY UPPER(SECTION_NAME)
    ORDER BY SNAPSHOT_TS DESC NULLS LAST, LOAD_TS DESC NULLS LAST
  ) = 1
),
flat AS (
  SELECT *
  FROM {flat_table}
  WHERE WINDOW_DAYS = {lookup_window_days}
    {company_filter}
    {env_filter}
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY UPPER(SECTION_NAME)
    ORDER BY COALESCE(IS_EXACT_SCOPE, FALSE) DESC, SNAPSHOT_TS DESC NULLS LAST
  ) = 1
)
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
  'section_name', s.section_name,
  'packet_present', p.SECTION_NAME IS NOT NULL,
  'flat_present', f.SECTION_NAME IS NOT NULL,
  'packet', OBJECT_CONSTRUCT_KEEP_NULL({_object_construct_pairs('p')}),
  'flat', OBJECT_CONSTRUCT_KEEP_NULL({_object_construct_pairs('f')})
) AS ROW_JSON
FROM sections s
LEFT JOIN packet p ON UPPER(p.SECTION_NAME)=UPPER(s.section_name)
LEFT JOIN flat f ON UPPER(f.SECTION_NAME)=UPPER(s.section_name)
ORDER BY s.section_name
"""


def _packet_availability_sql(options: SnowflakeCliValidationOptions) -> str:
    command_table = _sql_table("MART_SECTION_COMMAND_BRIEF", options)
    current_table = _sql_table("MART_SECTION_DECISION_CURRENT", options)
    flat_table = _sql_table("MART_SECTION_DECISION_CURRENT_FLAT", options)
    last_good_table = _sql_table("MART_SECTION_DECISION_LAST_GOOD", options)
    return f"""
/* PACKET_AVAILABILITY_PROBE */
WITH sections AS (
  SELECT column1::VARCHAR AS section_name FROM VALUES {_section_values_sql()}
),
available AS (
  SELECT SECTION_NAME, COMPANY, ENVIRONMENT, WINDOW_DAYS, SNAPSHOT_TS, LOAD_TS,
         1 AS current_count, 0 AS flat_count, 0 AS last_good_count,
         TRUE AS is_active
  FROM {command_table}
  UNION ALL
  SELECT SECTION_NAME, COMPANY, ENVIRONMENT, WINDOW_DAYS, SNAPSHOT_TS, LOAD_TS,
         1 AS current_count, 0 AS flat_count, 0 AS last_good_count,
         TRUE AS is_active
  FROM {current_table}
  UNION ALL
  SELECT SECTION_NAME, COMPANY, ENVIRONMENT, WINDOW_DAYS, SNAPSHOT_TS, LOAD_TS,
         0 AS current_count, 1 AS flat_count, 0 AS last_good_count,
         COALESCE(IS_ACTIVE, TRUE) AS is_active
  FROM {flat_table}
  UNION ALL
  SELECT SECTION_NAME, COMPANY, ENVIRONMENT, WINDOW_DAYS, SNAPSHOT_TS, LOAD_TS,
         0 AS current_count, 0 AS flat_count, 1 AS last_good_count,
         TRUE AS is_active
  FROM {last_good_table}
)
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
  'section_name', s.section_name,
  'company', COALESCE(a.COMPANY, {_literal(options.company)}),
  'environment', COALESCE(a.ENVIRONMENT, {_literal(options.environment)}),
  'window_days', COALESCE(a.WINDOW_DAYS, {normalize_packet_window_days(options.window_days)}),
  'active_current_count', COALESCE(SUM(IFF(a.is_active, a.current_count, 0)), 0),
  'flat_current_count', COALESCE(SUM(a.flat_count), 0),
  'last_good_count', COALESCE(SUM(a.last_good_count), 0),
  'latest_snapshot_ts', MAX(a.SNAPSHOT_TS),
  'latest_load_ts', MAX(a.LOAD_TS)
) AS ROW_JSON
FROM sections s
LEFT JOIN available a ON UPPER(a.SECTION_NAME)=UPPER(s.section_name)
GROUP BY s.section_name, COALESCE(a.COMPANY, {_literal(options.company)}), COALESCE(a.ENVIRONMENT, {_literal(options.environment)}), COALESCE(a.WINDOW_DAYS, {normalize_packet_window_days(options.window_days)})
ORDER BY s.section_name
"""


def _formula_expected_sql(options: SnowflakeCliValidationOptions) -> str:
    start_expr = f"DATEADD('day', -{int(options.window_days)}, CURRENT_DATE())"
    end_expr = "DATEADD('day', -1, CURRENT_DATE())"
    previous_start_expr = f"DATEADD('day', -{int(options.window_days) * 2}, CURRENT_DATE())"
    previous_end_expr = f"DATEADD('day', -{int(options.window_days) + 1}, CURRENT_DATE())"
    company_expr = _literal(options.company)
    return f"""
WITH account_billing AS (
  SELECT
    COUNT(*) AS account_source_rows,
    SUM(COALESCE(CREDITS_BILLED, CREDITS_USED, 0)) AS account_billed_credits,
    SUM(COALESCE(CREDITS_USED, 0)) AS account_used_credits,
    SUM(COALESCE(CREDITS_ADJUSTMENT_CLOUD_SERVICES, 0)) AS cloud_services_adjustment,
    MAX(COALESCE(LOAD_TS, USAGE_DATE::TIMESTAMP_NTZ)) AS billing_source_freshness_ts
  FROM FACT_COST_DAILY
  WHERE UPPER(COALESCE(COMPANY, 'ACCOUNT-WIDE')) IN ('ACCOUNT-WIDE', 'ALL')
    AND USAGE_DATE BETWEEN {start_expr} AND {end_expr}
),
previous_account_billing AS (
  SELECT
    COUNT(*) AS previous_source_rows,
    SUM(COALESCE(CREDITS_BILLED, CREDITS_USED, 0)) AS previous_account_billed_credits
  FROM FACT_COST_DAILY
  WHERE UPPER(COALESCE(COMPANY, 'ACCOUNT-WIDE')) IN ('ACCOUNT-WIDE', 'ALL')
    AND USAGE_DATE BETWEEN {previous_start_expr} AND {previous_end_expr}
),
warehouse_bridge AS (
  SELECT
    COUNT(*) AS warehouse_source_rows,
    SUM(COALESCE(CREDITS_USED_COMPUTE, 0) + COALESCE(CREDITS_USED_CLOUD_SERVICES, 0)) AS warehouse_credits,
    SUM(COALESCE(CREDITS_USED_COMPUTE, 0)) AS compute_credits,
    SUM(COALESCE(CREDITS_USED_CLOUD_SERVICES, 0)) AS cloud_services_credits
  FROM FACT_WAREHOUSE_HOURLY
  WHERE HOUR_START >= {start_expr}
    AND HOUR_START < CURRENT_DATE()
    AND ({company_expr} = 'ALL' OR UPPER(COMPANY) = UPPER({company_expr}))
    AND NULLIF(TRIM(WAREHOUSE_NAME), '') IS NOT NULL
),
cortex AS (
  SELECT
    COUNT(*) AS cortex_source_rows,
    COALESCE(SUM(COALESCE(CREDITS_USED, 0)), 0) AS cortex_ai_credits
  FROM FACT_CORTEX_DAILY
  WHERE USAGE_DATE BETWEEN {start_expr} AND {end_expr}
    AND ({company_expr} = 'ALL' OR UPPER(COMPANY) = UPPER({company_expr}))
)
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
  'SOURCE_ROWS_PRESENT', COALESCE(a.account_source_rows, 0) > 0 OR COALESCE(w.warehouse_source_rows, 0) > 0 OR COALESCE(c.cortex_source_rows, 0) > 0,
  'ACCOUNT_SOURCE_ROWS_PRESENT', COALESCE(a.account_source_rows, 0) > 0,
  'WAREHOUSE_SOURCE_ROWS_PRESENT', COALESCE(w.warehouse_source_rows, 0) > 0,
  'CORTEX_SOURCE_ROWS_PRESENT', COALESCE(c.cortex_source_rows, 0) > 0,
  'ACCOUNT_BILLED_CREDITS', a.account_billed_credits,
  'ACCOUNT_BILLED_COST_USD', a.account_billed_credits * {float(options.credit_price)},
  'ACCOUNT_USED_CREDITS', a.account_used_credits,
  'COMPUTE_CREDITS', w.compute_credits,
  'CLOUD_SERVICES_CREDITS', w.cloud_services_credits,
  'CLOUD_SERVICES_ADJUSTMENT', a.cloud_services_adjustment,
  'ACCOUNT_CLOUD_SERVICES_ADJUSTMENT', a.cloud_services_adjustment,
  'WAREHOUSE_CREDITS', w.warehouse_credits,
  'WAREHOUSE_COST_ESTIMATE_USD', w.warehouse_credits * {float(options.credit_price)},
  'WAREHOUSE_COST_USD', w.warehouse_credits * {float(options.credit_price)},
  'SERVICE_OTHER_CREDITS', GREATEST(COALESCE(a.account_billed_credits, 0) - COALESCE(w.warehouse_credits, 0), 0),
  'SERVICE_OTHER_COST_USD', GREATEST(COALESCE(a.account_billed_credits, 0) - COALESCE(w.warehouse_credits, 0), 0) * {float(options.credit_price)},
  'BILLING_BRIDGE_DELTA_CREDITS', COALESCE(a.account_billed_credits, 0) - COALESCE(w.warehouse_credits, 0),
  'BILLING_BRIDGE_DELTA_USD', (COALESCE(a.account_billed_credits, 0) - COALESCE(w.warehouse_credits, 0)) * {float(options.credit_price)},
  'BILLING_BRIDGE_STATUS', CASE
    WHEN a.account_billed_credits IS NULL THEN 'pending'
    WHEN ABS(COALESCE(a.account_billed_credits, 0) - COALESCE(w.warehouse_credits, 0)) < 0.0001 THEN 'matched'
    WHEN COALESCE(a.account_billed_credits, 0) > COALESCE(w.warehouse_credits, 0) THEN 'warehouse_lower_than_billed'
    ELSE 'warehouse_higher_than_billed'
  END,
  'CORTEX_AI_CREDITS', c.cortex_ai_credits,
  'CORTEX_AI_COST_USD', c.cortex_ai_credits * {float(options.ai_credit_price)},
  'BILLING_RECONCILIATION_STATUS', CASE
    WHEN a.account_billed_credits IS NULL THEN 'pending'
    WHEN ABS(COALESCE(a.account_billed_credits, 0) - COALESCE(w.warehouse_credits, 0)) < 0.0001 THEN 'matched'
    WHEN COALESCE(a.account_billed_credits, 0) > COALESCE(w.warehouse_credits, 0) THEN 'warehouse_lower_than_billed'
    ELSE 'warehouse_higher_than_billed'
  END,
  'BILLING_WINDOW_START', {start_expr},
  'BILLING_WINDOW_END', {end_expr},
  'BILLING_WINDOW_COMPLETE', TRUE,
  'BILLING_SOURCE_FRESHNESS_TS', a.billing_source_freshness_ts,
  'BILLING_LATENCY_NOTE', CASE WHEN a.account_billed_credits IS NULL THEN 'billing source unavailable' ELSE 'completed billing window' END,
  'BILLING_RECONCILIATION_WINDOW_START', {start_expr},
  'BILLING_RECONCILIATION_WINDOW_END', {end_expr},
  'BILLING_RECONCILIATION_FRESHNESS', 'current',
  'SPEND_MOVEMENT_PCT', CASE
    WHEN COALESCE(p.previous_source_rows, 0) = 0 OR COALESCE(p.previous_account_billed_credits, 0) = 0 THEN NULL
    ELSE ((COALESCE(a.account_billed_credits, 0) - p.previous_account_billed_credits) / p.previous_account_billed_credits) * 100
  END,
  'FORECAST_RUN_RATE_USD', CASE
    WHEN COALESCE(a.account_source_rows, 0) = 0 THEN NULL
    ELSE (COALESCE(a.account_billed_credits, 0) * {float(options.credit_price)} / GREATEST({int(options.window_days)}, 1)) * 30
  END
) AS ROW_JSON
FROM account_billing a, previous_account_billing p, warehouse_bridge w, cortex c
"""


def _query_history_sql(options: SnowflakeCliValidationOptions) -> str:
    prefix = options.query_tag_prefix or "OVERWATCH_VALIDATION"
    return f"""
WITH tagged AS (
  SELECT
    COALESCE(REGEXP_SUBSTR(QUERY_TAG, 'section=([^|]+)', 1, 1, 'e', 1), 'unknown') AS section,
    COALESCE(REGEXP_SUBSTR(QUERY_TAG, 'workflow=([^|]+)', 1, 1, 'e', 1), 'unknown') AS workflow,
    COALESCE(REGEXP_SUBSTR(QUERY_TAG, 'boundary=([^|]+)', 1, 1, 'e', 1), 'unknown') AS boundary,
    BYTES_SCANNED,
    ROWS_PRODUCED,
    TOTAL_ELAPSED_TIME,
    WAREHOUSE_NAME
  FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(END_TIME_RANGE_START=>DATEADD('hour', -6, CURRENT_TIMESTAMP())))
  WHERE QUERY_TAG ILIKE {_literal(prefix + '%')}
)
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
  'section', section,
  'workflow', workflow,
  'boundary', boundary,
  'query_count', COUNT(*),
  'bytes_scanned', SUM(COALESCE(BYTES_SCANNED, 0)),
  'rows_produced', SUM(COALESCE(ROWS_PRODUCED, 0)),
  'max_elapsed_ms', MAX(TOTAL_ELAPSED_TIME),
  'warehouse', ANY_VALUE(WAREHOUSE_NAME),
  'query_tag_prefix', {_literal(prefix)}
) AS ROW_JSON
FROM tagged
GROUP BY section, workflow, boundary
"""


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


def _runtime_query_budget_rows(
    root: Path,
    options: SnowflakeCliValidationOptions,
    *,
    start_index: int,
    current_commit: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    first_paint = _load_json_if_exists(root, "artifacts/full_app_validation/first_paint_performance_results.json")
    query_budget = _load_json_if_exists(root, "artifacts/full_app_validation/query_budget_results.json")
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    if not first_paint and not query_budget:
        return rows, failures
    if not isinstance(first_paint, Mapping) or not isinstance(query_budget, Mapping) or not first_paint or not query_budget:
        failures.append({"code": "SNOWFLAKE_CLI_RUNTIME_BUDGET_ARTIFACT_PAIR_MISSING"})
        return rows, failures
    allowed_runtime_budget_producers = {
        "first_paint_performance_results": {"full_app_runtime_validation", "full_app_launch_gauntlet"},
        "query_budget_results": {"full_app_runtime_validation"},
    }
    for name, payload in (("first_paint_performance_results", first_paint), ("query_budget_results", query_budget)):
        producer = str(payload.get("producer") or "")
        if producer not in allowed_runtime_budget_producers[name]:
            failures.append(
                {
                    "code": "SNOWFLAKE_CLI_RUNTIME_BUDGET_PRODUCER_MISSING",
                    "artifact": name,
                    "producer": producer,
                    "allowed_producers": sorted(allowed_runtime_budget_producers[name]),
                }
            )
        if str(payload.get("provenance_origin") or "") != "producer":
            failures.append({"code": "SNOWFLAKE_CLI_RUNTIME_BUDGET_PROVENANCE_INVALID", "artifact": name})
        if current_commit and str(payload.get("commit_sha") or "") != current_commit:
            failures.append({"code": "SNOWFLAKE_CLI_RUNTIME_BUDGET_COMMIT_MISMATCH", "artifact": name})
        if bool(payload.get("raw_sql_included")):
            failures.append({"code": "SNOWFLAKE_CLI_RUNTIME_BUDGET_RAW_SQL_INCLUDED", "artifact": name})
    if failures:
        return rows, failures

    rows_by_section = {
        str(row.get("section") or ""): row
        for row in first_paint.get("rows", [])
        if isinstance(row, Mapping)
    }
    index = start_index
    for section in PRIMARY_SECTIONS:
        source_row = rows_by_section.get(section)
        if not source_row:
            failures.append({"code": "SNOWFLAKE_CLI_RUNTIME_FIRST_PAINT_ROW_MISSING", "section": section})
            continue
        boundary_counts = {
            "first_paint_packet": int(source_row.get("cold_first_paint_packet_query_count") or 0),
            "warm_first_paint": int(source_row.get("warm_first_paint_query_count") or 0),
            "route_action": int(query_budget.get("route_query_leaks") or 0),
        }
        for boundary, query_count in boundary_counts.items():
            failure_reasons: list[str] = []
            if boundary == "first_paint_packet" and query_count > 1:
                failure_reasons.append("first paint packet query count exceeds one")
            if boundary in {"warm_first_paint", "route_action", "query_search_no_click"} and query_count > 0:
                failure_reasons.append(f"{boundary} must run zero queries")
            row = _base_row(
                phase="query_budget_validation",
                command_kind="runtime_artifact",
                options=options,
                status="passed" if not failure_reasons else "failed",
                row_count=1,
                sanitized_error="; ".join(failure_reasons),
                recommendation="",
            )
            row.update(
                {
                    "artifact": Path(CLI_QUERY_BUDGET_REL).name,
                    "row_index": index,
                    "section": section,
                    "workflow": "summary_board",
                    "boundary": boundary,
                    "query_count": query_count,
                    "bytes_scanned": 0,
                    "rows_produced": 0,
                    "max_elapsed_ms": source_row.get("elapsed_ms") or 0,
                    "warehouse": "",
                    "query_tag_prefix": _safe_label(str(options.query_tag_prefix or "")),
                    "failure_reason": "; ".join(failure_reasons),
                    "runtime_artifact_path": "artifacts/full_app_validation/first_paint_performance_results.json",
                    "runtime_row_id": str(source_row.get("id") or ""),
                    "raw_sql_included": False,
                }
            )
            rows.append(row)
            if failure_reasons:
                failures.append({"code": "SNOWFLAKE_CLI_RUNTIME_QUERY_BUDGET_FAILED", "section": section, "boundary": boundary, "failure_reason": row["failure_reason"]})
            index += 1

    supplemental = (
        ("Query Search", "query_search", "query_search_no_click", 0),
        ("Cost & Contract", "cost_workbench", "cost_workbench", 0),
    )
    for section, workflow, boundary, query_count in supplemental:
        row = _base_row(
            phase="query_budget_validation",
            command_kind="runtime_artifact",
            options=options,
            status="passed",
            row_count=1,
        )
        row.update(
            {
                "artifact": Path(CLI_QUERY_BUDGET_REL).name,
                "row_index": index,
                "section": section,
                "workflow": workflow,
                "boundary": boundary,
                "query_count": query_count,
                "bytes_scanned": 0,
                "rows_produced": 0,
                "max_elapsed_ms": 0,
                "warehouse": "",
                "query_tag_prefix": _safe_label(str(options.query_tag_prefix or "")),
                "failure_reason": "",
                "runtime_artifact_path": "artifacts/full_app_validation/query_budget_results.json",
                "runtime_row_id": "",
                "raw_sql_included": False,
            }
        )
        rows.append(row)
        index += 1
    return rows, failures


def _procedure_signature_sql(options: SnowflakeCliValidationOptions) -> str:
    schema_filter = ""
    if options.schema:
        schema_filter = f"AND UPPER(PROCEDURE_SCHEMA)=UPPER({_literal(options.schema)})"
    return f"""
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
  'procedure_name', 'SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST',
  'signature_count', COUNT(*),
  'supports_zero_arg_signature', COUNT_IF(COALESCE(ARGUMENT_SIGNATURE, '') IN ('()', ''))
) AS ROW_JSON
FROM INFORMATION_SCHEMA.PROCEDURES
WHERE UPPER(PROCEDURE_NAME)=UPPER('SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST')
  {schema_filter}
"""


def _detect_json_output_args(help_text: str) -> tuple[str, ...]:
    text = help_text or ""
    if re.search(r"--format\b", text, re.IGNORECASE) and re.search(r"\bJSON\b", text, re.IGNORECASE):
        return ("--format", "JSON")
    if re.search(r"--output\b", text, re.IGNORECASE) and re.search(r"\bjson\b", text, re.IGNORECASE):
        return ("--output", "json")
    return ()


def _json_output_args() -> tuple[str, ...]:
    return ("--format", "JSON")


def _parse_json_rows(stdout: str) -> list[dict[str, Any]]:
    text = stdout.strip()
    if not text:
        return []
    def flatten(value: object) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            data = value.get("data") if isinstance(value.get("data"), list) else None
            if data is not None:
                return flatten(data)
            return [value]
        if isinstance(value, list):
            rows: list[dict[str, Any]] = []
            for item in value:
                rows.extend(flatten(item))
            return rows
        return []

    try:
        parsed = json.loads(text)
        return flatten(parsed)
    except json.JSONDecodeError:
        return []


def _record_temp_sql_event(
    *,
    temp_sql_file_used: bool,
    temp_sql_file_deleted: bool,
    temp_sql_file_path_internal: str = "",
    elapsed_ms: int = 0,
    sanitized_error: str = "",
) -> dict[str, Any]:
    event = {
        "event_id": f"temp-sql-{len(_TEMP_SQL_EVENTS) + 1:04d}",
        "temp_sql_file_used": temp_sql_file_used,
        "temp_sql_file_deleted": temp_sql_file_deleted,
        "temp_sql_file_path_stored": False,
        "temp_sql_file_basename_prefix": TEMP_SQL_PREFIX,
        "elapsed_ms": elapsed_ms,
        "sanitized_error": sanitize_text(sanitized_error),
        "raw_sql_included": False,
        "_temp_sql_file_path_internal": temp_sql_file_path_internal,
    }
    _TEMP_SQL_EVENTS.append(event)
    return event


def _row_temp_sql_metadata(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "temp_sql_event_id": str(event.get("event_id") or ""),
        "temp_sql_file_used": bool(event.get("temp_sql_file_used")),
        "temp_sql_file_deleted": bool(event.get("temp_sql_file_deleted")),
        "temp_sql_file_path_stored": False,
        "raw_sql_included": False,
    }


def _scan_leftover_temp_sql_files() -> list[str]:
    leftovers: list[str] = []
    for event in _TEMP_SQL_EVENTS:
        path_text = str(event.get("_temp_sql_file_path_internal") or "")
        if not path_text:
            continue
        path = Path(path_text)
        try:
            if path.exists():
                leftovers.append(path.name)
        except OSError:
            continue
    return sorted(leftovers)


def _temp_file_hygiene_results(options: SnowflakeCliValidationOptions) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, event in enumerate(_TEMP_SQL_EVENTS):
        passed = bool(event.get("temp_sql_file_used")) and bool(event.get("temp_sql_file_deleted"))
        row = _base_row(
            phase="temp_sql_file_hygiene",
            command_kind="validation",
            options=options,
            elapsed_ms=int(event.get("elapsed_ms") or 0),
            status="passed" if passed else "failed",
            sanitized_error=str(event.get("sanitized_error") or ""),
            recommendation="" if passed else "Investigate local temp-file cleanup before trusting CLI live proof.",
        )
        row.update(
            {
                "artifact": Path(CLI_TEMP_FILE_HYGIENE_REL).name,
                "row_index": index,
                "temp_sql_event_id": str(event.get("event_id") or ""),
                "temp_sql_file_used": bool(event.get("temp_sql_file_used")),
                "temp_sql_file_deleted": bool(event.get("temp_sql_file_deleted")),
                "temp_sql_file_path_stored": False,
                "temp_sql_file_basename_prefix": TEMP_SQL_PREFIX,
            }
        )
        rows.append(row)
        if not passed:
            failures.append({"code": "SNOWFLAKE_CLI_TEMP_SQL_FILE_NOT_CLEANED", "temp_sql_event_id": row["temp_sql_event_id"]})
    leftovers = _scan_leftover_temp_sql_files()
    if leftovers:
        failures.append(
            {
                "code": "SNOWFLAKE_CLI_TEMP_SQL_FILE_LEFTOVER",
                "leftover_count": len(leftovers),
                "basename_prefix": TEMP_SQL_PREFIX,
            }
        )
    if not rows:
        rows.append(
            {
                **_base_row(
                    phase="temp_sql_file_hygiene",
                    command_kind="validation",
                    options=options,
                    status="skipped",
                    sanitized_error="",
                    recommendation="Run live SQL validation to exercise temporary SQL file hygiene.",
                ),
                "artifact": Path(CLI_TEMP_FILE_HYGIENE_REL).name,
                "row_index": 0,
                "temp_sql_file_used": False,
                "temp_sql_file_deleted": False,
                "temp_sql_file_path_stored": False,
                "temp_sql_file_basename_prefix": TEMP_SQL_PREFIX,
            }
        )
    return _payload(
        source="snowflake_cli_temp_file_hygiene_results",
        rows=rows,
        failures=failures,
        skipped=not _TEMP_SQL_EVENTS,
        skip_reason="" if _TEMP_SQL_EVENTS else "No generated Snowflake CLI SQL files were used in this run.",
        extra={
            "temp_sql_file_used_count": len(_TEMP_SQL_EVENTS),
            "temp_sql_file_deleted_count": sum(1 for event in _TEMP_SQL_EVENTS if bool(event.get("temp_sql_file_deleted"))),
            "temp_sql_file_leftover_count": len(leftovers),
            "temp_sql_file_path_stored": False,
            "raw_sql_included": False,
        },
    )


def evaluate_temp_file_hygiene_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        failures.append({"code": "SNOWFLAKE_CLI_TEMP_FILE_HYGIENE_ARTIFACT_MISSING"})
    else:
        if not bool(payload.get("passed")):
            failures.append(
                {
                    "code": "SNOWFLAKE_CLI_TEMP_FILE_HYGIENE_FAILED",
                    "failure_count": int(payload.get("failure_count") or 0),
                }
            )
        if int(payload.get("temp_sql_file_leftover_count") or 0) > 0:
            failures.append(
                {
                    "code": "SNOWFLAKE_CLI_TEMP_SQL_FILE_LEFTOVER",
                    "leftover_count": int(payload.get("temp_sql_file_leftover_count") or 0),
                }
            )
        serialized = json.dumps(payload, default=str)
        if re.search(r"(?i)overwatch_snowflake_validation_[^\"'\\s]+\\.sql", serialized):
            failures.append({"code": "SNOWFLAKE_CLI_TEMP_SQL_FILE_PATH_LEAK"})
    return {
        "source": "snowflake_cli_temp_file_hygiene_gate_results",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "snowflake_cli_temp_file_hygiene_passed": not failures,
        "temp_sql_file_used_count": int(payload.get("temp_sql_file_used_count") or 0) if isinstance(payload, Mapping) else 0,
        "temp_sql_file_leftover_count": int(payload.get("temp_sql_file_leftover_count") or 0) if isinstance(payload, Mapping) else 0,
        "temp_sql_file_path_stored": False,
        "raw_sql_included": False,
    }


def _run_snow_sql_query(
    snow: str,
    options: SnowflakeCliValidationOptions,
    query: str,
    *,
    runner: Runner,
    timeout_seconds: int = 180,
) -> tuple[list[dict[str, Any]], subprocess.CompletedProcess[str] | None, int, dict[str, Any]]:
    temp_path = ""
    event: dict[str, Any] = {}
    elapsed = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".sql",
            prefix=TEMP_SQL_PREFIX,
            encoding="utf-8",
            delete=False,
        ) as handle:
            handle.write(query)
            temp_path = handle.name
        args = [snow, "sql", *_json_output_args(), *_command_scope(options), "-f", temp_path]
        proc, elapsed = _run(args, runner=runner, timeout_seconds=timeout_seconds)
        rows = _parse_json_rows(proc.stdout if proc else "")
        return rows, proc, elapsed, event
    finally:
        if temp_path:
            deleted = False
            error = ""
            try:
                Path(temp_path).unlink(missing_ok=True)
                deleted = not Path(temp_path).exists()
            except OSError:
                deleted = False
                error = "Temporary SQL file cleanup failed."
            if not event:
                event.update(
                    _record_temp_sql_event(
                        temp_sql_file_used=True,
                        temp_sql_file_deleted=deleted,
                        temp_sql_file_path_internal=temp_path,
                        elapsed_ms=elapsed,
                        sanitized_error=error,
                    )
                )


def _run_snow_sql_file(
    snow: str,
    options: SnowflakeCliValidationOptions,
    filename: Path,
    *,
    runner: Runner,
    timeout_seconds: int = 300,
) -> tuple[subprocess.CompletedProcess[str] | None, int]:
    args = [snow, "sql", *_json_output_args(), *_command_scope(options), "-f", str(filename)]
    return _run(args, runner=runner, timeout_seconds=timeout_seconds)


def _capability_results(
    snow: str,
    options: SnowflakeCliValidationOptions,
    *,
    runner: Runner,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    sql_help_text = ""
    for phase, args in (
        ("snowflake_cli_version", [snow, "--version"]),
        ("snowflake_cli_sql_help", [snow, "sql", "--help"]),
    ):
        proc, elapsed = _run(args, runner=runner, timeout_seconds=60)
        ok = proc is not None and proc.returncode == 0
        stdout = proc.stdout if proc else ""
        stderr = proc.stderr if proc else ""
        if phase == "snowflake_cli_sql_help" and ok:
            sql_help_text = stdout
        row = _base_row(
            phase=phase,
            command_kind="validation",
            options=options,
            elapsed_ms=elapsed,
            status="passed" if ok else "failed",
            sanitized_error="" if ok else sanitize_text(stderr or stdout),
            recommendation="" if ok else "Install Snowflake CLI and make the snow executable visible on PATH.",
        )
        row.update(
            {
                "artifact": Path(CLI_CAPABILITY_REL).name,
                "row_index": len(rows),
                "capability_detected": ok,
                "version": sanitize_text(stdout).strip() if phase == "snowflake_cli_version" and ok else "",
                "sql_help_available": ok if phase == "snowflake_cli_sql_help" else None,
            }
        )
        if not ok:
            failures.append({"code": "SNOWFLAKE_CLI_CAPABILITY_FAILED", "phase": phase, "sanitized_error": row["sanitized_error"]})
        rows.append(row)
    json_args = _detect_json_output_args(sql_help_text)
    json_ok = bool(json_args)
    json_row = _base_row(
        phase="snowflake_cli_json_output_detection",
        command_kind="validation",
        options=options,
        status="passed" if json_ok else "failed",
        sanitized_error="" if json_ok else "Snowflake CLI sql help did not advertise a machine-readable JSON output option.",
        recommendation="" if json_ok else "Upgrade Snowflake CLI to a version that supports snow sql --format JSON.",
    )
    json_row.update(
        {
            "artifact": Path(CLI_CAPABILITY_REL).name,
            "row_index": len(rows),
            "capability_detected": json_ok,
            "json_output_supported": json_ok,
            "json_output_args": list(json_args),
            "raw_sql_included": False,
        }
    )
    rows.append(json_row)
    if not json_ok:
        failures.append({"code": "SNOWFLAKE_CLI_JSON_OUTPUT_UNAVAILABLE", "phase": "snowflake_cli_json_output_detection"})
    return _payload(
        source="snowflake_cli_capability_results",
        rows=rows,
        failures=failures,
        extra={"json_output_supported": json_ok, "json_output_args": list(json_args)},
    )


def _connection_results(
    snow: str,
    options: SnowflakeCliValidationOptions,
    *,
    runner: Runner,
) -> dict[str, Any]:
    args = [snow, "connection", "test", *_connection_test_scope(options)]
    proc, elapsed = _run(args, runner=runner, timeout_seconds=CONNECTION_TEST_TIMEOUT_SECONDS)
    ok = proc is not None and proc.returncode == 0
    row = _base_row(
        phase="connection_test",
        command_kind="connection_test",
        options=options,
        elapsed_ms=elapsed,
        status="passed" if ok else "failed",
        sanitized_error="" if ok else sanitize_text((proc.stderr if proc else "") or (proc.stdout if proc else "")),
        recommendation="" if ok else "Run snow connection test -c <connection> locally and fix the named connection.",
    )
    row.update({"artifact": Path(CLI_CONNECTION_REL).name, "row_index": 0})
    failures = [] if ok else [{"code": "SNOWFLAKE_CLI_CONNECTION_FAILED", "sanitized_error": row["sanitized_error"]}]
    return _payload(source="snowflake_cli_connection_results", rows=[row], failures=failures)


def _setup_validation_results(
    root: Path,
    snow: str,
    options: SnowflakeCliValidationOptions,
    *,
    runner: Runner,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    validation_file = root / "snowflake" / "OVERWATCH_MART_VALIDATION.sql"
    if not validation_file.exists():
        row = _base_row(
            phase="setup_validation_sql",
            command_kind="sql_file",
            options=options,
            status="failed",
            sanitized_error="Validation SQL file is missing.",
            recommendation="Restore snowflake/OVERWATCH_MART_VALIDATION.sql.",
        )
        row.update({"artifact": Path(CLI_SETUP_REL).name, "row_index": 0})
        return _payload(
            source="snowflake_cli_setup_validation_results",
            rows=[row],
            failures=[{"code": "SNOWFLAKE_CLI_VALIDATION_SQL_MISSING"}],
        )
    proc, elapsed = _run_snow_sql_file(snow, options, validation_file, runner=runner)
    ok = proc is not None and proc.returncode == 0
    row = _base_row(
        phase="setup_validation_sql",
        command_kind="sql_file",
        options=options,
        elapsed_ms=elapsed,
        status="passed" if ok else "failed",
        row_count=None,
        sanitized_error="" if ok else sanitize_text((proc.stderr if proc else "") or (proc.stdout if proc else "")),
        recommendation="" if ok else "Fix setup validation failures before launch.",
    )
    row.update({"artifact": Path(CLI_SETUP_REL).name, "row_index": 0})
    rows.append(row)
    if not ok:
        failures.append({"code": "SNOWFLAKE_CLI_SETUP_VALIDATION_FAILED", "sanitized_error": row["sanitized_error"]})
    refresh_status = "skipped"
    refresh_reason = "Refresh validation skipped by default; pass --run-fast-refresh or --run-full-refresh-dry-run to opt in."
    if options.skip_refresh:
        refresh_reason = "Refresh validation skipped because --skip-refresh was provided."
    elif options.run_fast_refresh:
        signature_rows, signature_proc, signature_elapsed, signature_temp = _run_snow_sql_query(
            snow,
            options,
            _procedure_signature_sql(options),
            runner=runner,
            timeout_seconds=120,
        )
        signature = _normalize_snow_row(signature_rows[0]) if signature_rows else {}
        signature_ok = (
            signature_proc is not None
            and signature_proc.returncode == 0
            and int(_as_float(signature.get("supports_zero_arg_signature")) or 0) > 0
        )
        signature_row = _base_row(
            phase="refresh_procedure_signature_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=signature_elapsed,
            status="passed" if signature_ok else "failed",
            row_count=len(signature_rows),
            sanitized_error="" if signature_ok else "Refresh procedure signature is missing or incompatible.",
            recommendation="" if signature_ok else "Deploy the refresh procedure signature before running CLI refresh validation.",
        )
        signature_row.update(
            {
                "artifact": Path(CLI_SETUP_REL).name,
                "row_index": len(rows),
                "procedure_name": "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST",
                "signature_count": int(_as_float(signature.get("signature_count")) or 0),
                "supports_zero_arg_signature": int(_as_float(signature.get("supports_zero_arg_signature")) or 0),
                **_row_temp_sql_metadata(signature_temp),
            }
        )
        rows.append(signature_row)
        if not signature_ok:
            failures.append({"code": "SNOWFLAKE_CLI_REFRESH_SIGNATURE_INCOMPATIBLE"})
            return _payload(
                source="snowflake_cli_setup_validation_results",
                rows=rows,
                failures=failures,
                extra={"refresh_status": "incompatible_signature", "refresh_skip_reason": "Refresh call not executed because procedure signature was incompatible."},
            )
        rows2, proc2, elapsed2, temp2 = _run_snow_sql_query(
            snow,
            options,
            "CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST()",
            runner=runner,
            timeout_seconds=300,
        )
        refresh_status = "passed" if proc2 is not None and proc2.returncode == 0 else "failed"
        refresh_reason = "" if refresh_status == "passed" else "FAST refresh validation failed."
        row2 = _base_row(
            phase="fast_refresh_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=elapsed2,
            status=refresh_status,
            row_count=len(rows2),
            sanitized_error="" if refresh_status == "passed" else sanitize_text((proc2.stderr if proc2 else "") or (proc2.stdout if proc2 else "")),
            recommendation="" if refresh_status == "passed" else "Fix FAST refresh validation or run with --skip-refresh for non-refresh proof.",
        )
        row2.update({"artifact": Path(CLI_SETUP_REL).name, "row_index": len(rows), **_row_temp_sql_metadata(temp2)})
        rows.append(row2)
        if refresh_status == "failed":
            failures.append({"code": "SNOWFLAKE_CLI_FAST_REFRESH_FAILED", "sanitized_error": row2["sanitized_error"]})
    if options.run_full_refresh_dry_run:
        if os.environ.get("OVERWATCH_ALLOW_DESTRUCTIVE_SNOWFLAKE_VALIDATION") != "1":
            row3 = _base_row(
                phase="full_refresh_dry_run_validation",
                command_kind="validation",
                options=options,
                status="skipped",
                sanitized_error="",
                recommendation="Set OVERWATCH_ALLOW_DESTRUCTIVE_SNOWFLAKE_VALIDATION=1 only when FULL dry-run validation is explicitly approved.",
            )
            row3.update({"artifact": Path(CLI_SETUP_REL).name, "row_index": len(rows), "destructive_validation_allowed": False})
            rows.append(row3)
            failures.append({"code": "SNOWFLAKE_CLI_FULL_DRY_RUN_BLOCKED_WITHOUT_FLAG"})
            return _payload(
                source="snowflake_cli_setup_validation_results",
                rows=rows,
                failures=failures,
                extra={"refresh_status": "blocked", "refresh_skip_reason": "FULL dry-run blocked without destructive validation flag."},
            )
        rows3, proc3, elapsed3, temp3 = _run_snow_sql_query(
            snow,
            options,
            "CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL()",
            runner=runner,
            timeout_seconds=300,
        )
        status = "passed" if proc3 is not None and proc3.returncode == 0 else "failed"
        row3 = _base_row(
            phase="full_refresh_dry_run_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=elapsed3,
            status=status,
            row_count=len(rows3),
            sanitized_error="" if status == "passed" else sanitize_text((proc3.stderr if proc3 else "") or (proc3.stdout if proc3 else "")),
            recommendation="" if status == "passed" else "Fix FULL dry-run validation.",
        )
        row3.update({"artifact": Path(CLI_SETUP_REL).name, "row_index": len(rows), **_row_temp_sql_metadata(temp3)})
        rows.append(row3)
        if status == "failed":
            failures.append({"code": "SNOWFLAKE_CLI_FULL_DRY_RUN_FAILED", "sanitized_error": row3["sanitized_error"]})
    extra = {"refresh_status": refresh_status, "refresh_skip_reason": refresh_reason}
    return _payload(source="snowflake_cli_setup_validation_results", rows=rows, failures=failures, extra=extra)


def _expected_setup_migration_versions(root: Path) -> tuple[str, ...]:
    setup_file = root / "snowflake" / "OVERWATCH_MART_SETUP.sql"
    if not setup_file.exists():
        return ()
    text = setup_file.read_text(encoding="utf-8", errors="ignore")
    versions = re.findall(
        r"['\"](\d{4}\.\d{2}\.\d{2}-[A-Za-z0-9_.-]+)['\"]\s+AS\s+MIGRATION_VERSION",
        text,
        flags=re.IGNORECASE,
    )
    return tuple(dict.fromkeys(versions))


def _setup_migration_object_sql(options: SnowflakeCliValidationOptions) -> str:
    schema = _literal(options.schema or "OVERWATCH")
    required = ("OVERWATCH_SCHEMA_MIGRATION", "MART_SECTION_COMMAND_BRIEF", "MART_SECTION_DECISION_CURRENT_FLAT")
    required_values = ", ".join(f"({_literal(name)})" for name in required)
    return f"""
WITH required_objects AS (
  SELECT column1::VARCHAR AS object_name FROM VALUES {required_values}
),
inventory AS (
  SELECT UPPER(TABLE_NAME) AS object_name
  FROM INFORMATION_SCHEMA.TABLES
  WHERE UPPER(TABLE_SCHEMA) = UPPER({schema})
)
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
  'migration_table_exists', COUNT_IF(i.object_name = 'OVERWATCH_SCHEMA_MIGRATION') > 0,
  'required_object_count', COUNT(DISTINCT r.object_name),
  'present_required_object_count', COUNT(DISTINCT i.object_name),
  'missing_required_object_count', COUNT(DISTINCT IFF(i.object_name IS NULL, r.object_name, NULL))
) AS ROW_JSON
FROM required_objects r
LEFT JOIN inventory i ON i.object_name = UPPER(r.object_name)
"""


def _setup_migration_ledger_sql(options: SnowflakeCliValidationOptions, expected_versions: Sequence[str]) -> str:
    if expected_versions:
        expected_values = ", ".join(f"({_literal(version)})" for version in expected_versions)
    else:
        expected_values = "('')"
    ledger_table = _sql_table("OVERWATCH_SCHEMA_MIGRATION", options)
    return f"""
WITH expected AS (
  SELECT column1::VARCHAR AS migration_version
  FROM VALUES {expected_values}
  WHERE NULLIF(column1::VARCHAR, '') IS NOT NULL
),
ledger AS (
  SELECT MIGRATION_VERSION, SOURCE_FILE, APPLIED_AT
  FROM {ledger_table}
)
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
  'expected_migration_count', (SELECT COUNT(*) FROM expected),
  'present_migration_count', COUNT_IF(l.MIGRATION_VERSION IS NOT NULL),
  'missing_migration_count', COUNT_IF(l.MIGRATION_VERSION IS NULL),
  'latest_migration_version', MAX_BY(l.MIGRATION_VERSION, l.APPLIED_AT),
  'repo_source_file_count', COUNT_IF(l.SOURCE_FILE ILIKE 'snowflake/%')
) AS ROW_JSON
FROM expected e
LEFT JOIN ledger l ON l.MIGRATION_VERSION = e.MIGRATION_VERSION
"""


def evaluate_setup_migration_live_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    failures = list(payload.get("failures") or [])
    return {
        "source": "setup_migration_live_gate_results",
        "generated_at": _utc_now(),
        "passed": bool(payload.get("passed")) and not failures,
        "failure_count": len(failures),
        "failures": failures,
        "setup_sql_present": bool(payload.get("setup_sql_present")),
        "validation_sql_present": bool(payload.get("validation_sql_present")),
        "migration_table_exists": bool(payload.get("migration_table_exists")),
        "expected_migration_count": int(payload.get("expected_migration_count") or 0),
        "missing_migration_count": int(payload.get("missing_migration_count") or 0),
        "raw_sql_included": False,
    }


def _setup_migration_live_results(
    root: Path,
    snow: str,
    options: SnowflakeCliValidationOptions,
    *,
    runner: Runner,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    setup_file = root / "snowflake" / "OVERWATCH_MART_SETUP.sql"
    validation_file = root / "snowflake" / "OVERWATCH_MART_VALIDATION.sql"
    expected_versions = _expected_setup_migration_versions(root)
    local_ok = setup_file.exists() and validation_file.exists() and bool(expected_versions)
    local_row = _base_row(
        phase="setup_migration_local_contract",
        command_kind="local_contract",
        options=options,
        status="passed" if local_ok else "failed",
        row_count=len(expected_versions),
        sanitized_error="" if local_ok else "Setup SQL, validation SQL, or migration versions are missing.",
        recommendation="" if local_ok else "Restore setup/validation SQL and migration ledger entries before live validation.",
    )
    local_row.update(
        {
            "artifact": Path(CLI_SETUP_MIGRATION_REL).name,
            "row_index": 0,
            "setup_sql_present": setup_file.exists(),
            "validation_sql_present": validation_file.exists(),
            "expected_migration_count": len(expected_versions),
        }
    )
    rows.append(local_row)
    if not local_ok:
        failures.append({"code": "SETUP_MIGRATION_LOCAL_CONTRACT_MISSING"})
        return _payload(
            source="setup_migration_live_results",
            rows=rows,
            failures=failures,
            extra={
                "setup_sql_present": setup_file.exists(),
                "validation_sql_present": validation_file.exists(),
                "expected_migration_count": len(expected_versions),
            },
        )

    object_rows, object_proc, object_elapsed, object_temp = _run_snow_sql_query(
        snow,
        options,
        _setup_migration_object_sql(options),
        runner=runner,
        timeout_seconds=120,
    )
    object_payload = _normalize_snow_row(object_rows[0]) if object_rows else {}
    object_ok = object_proc is not None and object_proc.returncode == 0 and bool(object_payload.get("migration_table_exists"))
    object_row = _base_row(
        phase="setup_migration_object_probe",
        command_kind="sql_query",
        options=options,
        elapsed_ms=object_elapsed,
        status="passed" if object_ok else "failed",
        row_count=len(object_rows),
        sanitized_error="" if object_ok else sanitize_text((object_proc.stderr if object_proc else "") or (object_proc.stdout if object_proc else "")) or "Migration ledger object is unavailable.",
        recommendation="" if object_ok else "Run setup validation with an admin role or deploy the migration ledger.",
    )
    object_row.update(
        {
            "artifact": Path(CLI_SETUP_MIGRATION_REL).name,
            "row_index": len(rows),
            "migration_table_exists": bool(object_payload.get("migration_table_exists")),
            "required_object_count": int(_as_float(object_payload.get("required_object_count")) or 0),
            "present_required_object_count": int(_as_float(object_payload.get("present_required_object_count")) or 0),
            "missing_required_object_count": int(_as_float(object_payload.get("missing_required_object_count")) or 0),
            **_row_temp_sql_metadata(object_temp),
        }
    )
    rows.append(object_row)
    if not object_ok:
        failures.append({"code": "SETUP_MIGRATION_LEDGER_UNAVAILABLE", "sanitized_error": object_row["sanitized_error"]})
        return _payload(
            source="setup_migration_live_results",
            rows=rows,
            failures=failures,
            extra={
                "setup_sql_present": True,
                "validation_sql_present": True,
                "migration_table_exists": bool(object_payload.get("migration_table_exists")),
                "expected_migration_count": len(expected_versions),
            },
        )

    ledger_rows, ledger_proc, ledger_elapsed, ledger_temp = _run_snow_sql_query(
        snow,
        options,
        _setup_migration_ledger_sql(options, expected_versions),
        runner=runner,
        timeout_seconds=120,
    )
    ledger_payload = _normalize_snow_row(ledger_rows[0]) if ledger_rows else {}
    missing_count = int(_as_float(ledger_payload.get("missing_migration_count")) or 0)
    ledger_ok = ledger_proc is not None and ledger_proc.returncode == 0 and missing_count == 0
    ledger_row = _base_row(
        phase="setup_migration_ledger_probe",
        command_kind="sql_query",
        options=options,
        elapsed_ms=ledger_elapsed,
        status="passed" if ledger_ok else "failed",
        row_count=len(ledger_rows),
        sanitized_error="" if ledger_ok else sanitize_text((ledger_proc.stderr if ledger_proc else "") or (ledger_proc.stdout if ledger_proc else "")) or "Migration ledger is missing expected versions.",
        recommendation="" if ledger_ok else "Apply the current setup bundle or investigate migration ledger drift.",
    )
    ledger_row.update(
        {
            "artifact": Path(CLI_SETUP_MIGRATION_REL).name,
            "row_index": len(rows),
            "expected_migration_count": int(_as_float(ledger_payload.get("expected_migration_count")) or len(expected_versions)),
            "present_migration_count": int(_as_float(ledger_payload.get("present_migration_count")) or 0),
            "missing_migration_count": missing_count,
            "latest_migration_version": _safe_label(str(ledger_payload.get("latest_migration_version") or "")),
            "repo_source_file_count": int(_as_float(ledger_payload.get("repo_source_file_count")) or 0),
            **_row_temp_sql_metadata(ledger_temp),
        }
    )
    rows.append(ledger_row)
    if not ledger_ok:
        failures.append({"code": "SETUP_MIGRATION_LEDGER_DRIFT", "missing_migration_count": missing_count})

    return _payload(
        source="setup_migration_live_results",
        rows=rows,
        failures=failures,
        extra={
            "setup_sql_present": True,
            "validation_sql_present": True,
            "migration_table_exists": bool(object_payload.get("migration_table_exists")),
            "expected_migration_count": len(expected_versions),
            "missing_migration_count": missing_count,
        },
    )


def _normalize_snow_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if "ROW_JSON" in row and isinstance(row["ROW_JSON"], Mapping):
        return dict(row["ROW_JSON"])
    if "ROW_JSON" in row and isinstance(row["ROW_JSON"], str):
        try:
            parsed = json.loads(row["ROW_JSON"])
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return dict(row)


def _packet_value_results(
    snow: str,
    options: SnowflakeCliValidationOptions,
    *,
    runner: Runner,
) -> dict[str, Any]:
    rows_raw, proc, elapsed, temp_meta = _run_snow_sql_query(snow, options, _packet_flat_sql(options), runner=runner)
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    if proc is None or proc.returncode != 0:
        row = _base_row(
            phase="packet_value_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=elapsed,
            status="failed",
            sanitized_error=sanitize_text((proc.stderr if proc else "") or (proc.stdout if proc else "")),
            recommendation="Validate MART_SECTION_COMMAND_BRIEF and MART_SECTION_DECISION_CURRENT_FLAT are deployed and populated.",
        )
        row.update({"artifact": Path(CLI_PACKET_VALUE_REL).name, "row_index": 0, **_row_temp_sql_metadata(temp_meta)})
        return _payload(
            source="snowflake_cli_packet_value_results",
            rows=[row],
            failures=[{"code": "SNOWFLAKE_CLI_PACKET_QUERY_FAILED", "sanitized_error": row["sanitized_error"]}],
        )
    for index, raw in enumerate(rows_raw):
        parsed = _normalize_snow_row(raw)
        packet = parsed.get("packet") if isinstance(parsed.get("packet"), Mapping) else {}
        flat = parsed.get("flat") if isinstance(parsed.get("flat"), Mapping) else {}
        section = str(parsed.get("section_name") or "")
        mismatch_fields: list[str] = []
        missing_packet_fields: list[str] = []
        missing_flat_fields: list[str] = []
        for field in REQUIRED_PACKET_FIELDS:
            packet_value = packet.get(field) if isinstance(packet, Mapping) else None
            flat_value = flat.get(field) if isinstance(flat, Mapping) else None
            if packet_value is None:
                missing_packet_fields.append(field)
            if flat_value is None:
                missing_flat_fields.append(field)
            if packet_value != flat_value:
                packet_float = _as_float(packet_value)
                flat_float = _as_float(flat_value)
                if packet_float is None or flat_float is None or abs(packet_float - flat_float) > 0.001:
                    mismatch_fields.append(field)
        packet_present = bool(parsed.get("packet_present"))
        flat_present = bool(parsed.get("flat_present"))
        passed = packet_present and flat_present and not mismatch_fields
        row = _base_row(
            phase="packet_value_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=elapsed,
            status="passed" if passed else "failed",
            row_count=1,
            sanitized_error="" if passed else "Packet and flat values did not reconcile.",
            recommendation="" if passed else "Refresh packet publication and flat table extraction for the named section.",
        )
        row.update(
            {
                "artifact": Path(CLI_PACKET_VALUE_REL).name,
                "row_index": index,
                "section_name": section,
                "packet_present": packet_present,
                "flat_present": flat_present,
                "mismatch_fields": mismatch_fields,
                "missing_packet_fields": missing_packet_fields,
                "missing_flat_fields": missing_flat_fields,
                "packet_values": packet,
                "flat_values": flat,
                **_row_temp_sql_metadata(temp_meta),
            }
        )
        rows.append(row)
        if not passed:
            failures.append(
                {
                    "code": "SNOWFLAKE_CLI_PACKET_FLAT_MISMATCH",
                    "section_name": section,
                    "mismatch_fields": mismatch_fields,
                    "missing_packet_fields": missing_packet_fields,
                    "missing_flat_fields": missing_flat_fields,
                }
            )
    if not rows:
        failures.append({"code": "SNOWFLAKE_CLI_PACKET_ROWS_MISSING"})
    return _payload(source="snowflake_cli_packet_value_results", rows=rows, failures=failures)


def _section_packet_value(packet_payload: Mapping[str, Any], section: str, field: str) -> Any:
    for row in packet_payload.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("section_name") or "") != section:
            continue
        values = row.get("packet_values")
        if isinstance(values, Mapping):
            return values.get(field)
    return None


def _packet_availability_results(
    snow: str,
    options: SnowflakeCliValidationOptions,
    *,
    runner: Runner,
) -> dict[str, dict[str, Any]]:
    rows_raw, proc, elapsed, temp_meta = _run_snow_sql_query(snow, options, _packet_availability_sql(options), runner=runner)
    if proc is None or proc.returncode != 0:
        row = _base_row(
            phase="packet_availability_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=elapsed,
            status="failed",
            sanitized_error=sanitize_text((proc.stderr if proc else "") or (proc.stdout if proc else "")),
            recommendation="Validate summary packet tables are deployed and populated for the selected scope.",
        )
        row.update(
            {
                "artifact": Path(SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL).name,
                "row_index": 0,
                "selected_company": options.company,
                "selected_environment": options.environment,
                "selected_window_days": options.window_days,
                "raw_sql_included": False,
                **_row_temp_sql_metadata(temp_meta),
            }
        )
        payload = _payload(
            source="snowflake_cli_packet_availability_results",
            rows=[row],
            failures=[{"code": "SNOWFLAKE_CLI_PACKET_AVAILABILITY_QUERY_FAILED", "sanitized_error": row["sanitized_error"]}],
        )
        matrix = dict(payload)
        matrix["source"] = "packet_availability_matrix_results"
        return {
            SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL: payload,
            PACKET_AVAILABILITY_MATRIX_REL: matrix,
            PACKET_AVAILABILITY_GATE_REL: evaluate_packet_availability_gate(matrix),
        }

    availability_rows = [_normalize_snow_row(raw) for raw in rows_raw]
    matrix = evaluate_packet_availability(
        availability_rows,
        selected_company=options.company,
        selected_environment=options.environment,
        selected_window_days=options.window_days,
        sections=PRIMARY_SECTIONS,
    )
    cli_rows: list[dict[str, Any]] = []
    for index, item in enumerate(matrix.get("rows", [])):
        if not isinstance(item, Mapping):
            continue
        passed = bool(item.get("passed"))
        row = _base_row(
            phase="packet_availability_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=elapsed,
            status="passed" if passed else "failed",
            row_count=1,
            sanitized_error="" if passed else str(item.get("missing_reason") or "Packet availability failed."),
            recommendation=str(item.get("recommended_fix") or ""),
        )
        row.update(dict(item))
        row.update({"artifact": Path(SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL).name, "row_index": index, **_row_temp_sql_metadata(temp_meta)})
        cli_rows.append(row)
    cli_payload = _payload(
        source="snowflake_cli_packet_availability_results",
        rows=cli_rows,
        failures=list(matrix.get("failures") or []),
        extra={
            "selected_company": options.company,
            "selected_environment": options.environment,
            "selected_window_days": options.window_days,
            "normalized_window_days": normalize_packet_window_days(options.window_days),
        },
    )
    matrix_payload = dict(matrix)
    matrix_payload["rows"] = cli_rows
    matrix_payload["row_count"] = len(cli_rows)
    matrix_payload["source"] = "packet_availability_matrix_results"
    return {
        SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL: cli_payload,
        PACKET_AVAILABILITY_MATRIX_REL: matrix_payload,
        PACKET_AVAILABILITY_GATE_REL: evaluate_packet_availability_gate(matrix_payload),
    }


def _section_flat_value(packet_payload: Mapping[str, Any], section: str, field: str) -> Any:
    for row in packet_payload.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        if str(row.get("section_name") or "") != section:
            continue
        values = row.get("flat_values")
        if isinstance(values, Mapping):
            return values.get(field)
    return None


def _load_json_if_exists(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _rendered_value_by_field(root: Path) -> dict[str, Any]:
    payload = _load_json_if_exists(root, "artifacts/full_app_validation/rendered_formula_results.json")
    if _rendered_formula_static_contract_only(payload):
        return {}
    values: dict[str, Any] = {}
    for row in payload.get("value_checks", []):
        if not isinstance(row, Mapping):
            continue
        serialized_source = " ".join(
            str(row.get(key) or "")
            for key in ("rendered_value_source", "value_source", "proof_source")
        )
        if "fixture_expected_value" in serialized_source:
            continue
        field = str(row.get("packet_field") or "")
        if field:
            values[field] = row.get("rendered_value")
    return values


def _rendered_formula_static_contract_only(payload: Mapping[str, Any]) -> bool:
    if not payload:
        return False
    if str(payload.get("source") or "") == "rendered_formula_static_contract":
        return True
    checks = payload.get("value_checks")
    if not isinstance(checks, list):
        return False
    return any(
        isinstance(row, Mapping)
        and "fixture_expected_value"
        in " ".join(str(row.get(key) or "") for key in ("rendered_value_source", "value_source", "proof_source"))
        for row in checks
    )


def _values_match(left: Any, right: Any, tolerance: float) -> bool:
    if left is None or right is None:
        return left is None and right is None
    left_float = _as_float(left)
    right_float = _as_float(right)
    if left_float is not None and right_float is not None:
        return abs(left_float - right_float) <= tolerance
    return str(left).strip().lower() == str(right).strip().lower()


def _tolerance_for_field(field: str) -> float:
    if field.endswith("_USD") or field in {"SPEND_MOVEMENT_PCT", "FORECAST_RUN_RATE_USD"}:
        return 0.05
    if field in NUMERIC_FORMULA_FIELDS:
        return 0.001
    return 0.0


def _field_source_rows_present(field: str, expected: Mapping[str, Any]) -> bool:
    if field.startswith("CORTEX_AI"):
        return bool(expected.get("CORTEX_SOURCE_ROWS_PRESENT", expected.get("SOURCE_ROWS_PRESENT", True)))
    if field.startswith("WAREHOUSE") or field in {"COMPUTE_CREDITS", "CLOUD_SERVICES_CREDITS"}:
        return bool(expected.get("WAREHOUSE_SOURCE_ROWS_PRESENT", expected.get("SOURCE_ROWS_PRESENT", True)))
    return bool(expected.get("ACCOUNT_SOURCE_ROWS_PRESENT", expected.get("SOURCE_ROWS_PRESENT", True)))


def _source_confirmed_zero(value: Any, source_rows_present: bool) -> bool:
    value_float = _as_float(value)
    return value_float is not None and abs(value_float) <= 0.000001


def _formula_value_gate_results(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_rows = payload.get("rows")
    rows: list[Any] = raw_rows if isinstance(raw_rows, list) else []
    raw_failures = payload.get("failures")
    failures: list[Any] = raw_failures if isinstance(raw_failures, list) else []
    return {
        "source": "snowflake_cli_formula_value_gate_results",
        "generated_at": _utc_now(),
        "passed": bool(payload.get("passed")),
        "failure_count": int(payload.get("failure_count") or 0),
        "failures": failures,
        "row_count": len(rows),
        "required_field_count": len(REQUIRED_PACKET_FIELDS),
        "validated_fields": [
            str(row.get("formula_field"))
            for row in rows
            if isinstance(row, Mapping) and row.get("formula_field")
        ],
        "raw_sql_included": False,
    }


def _formula_value_results(
    snow: str,
    options: SnowflakeCliValidationOptions,
    packet_payload: Mapping[str, Any],
    root: Path,
    *,
    runner: Runner,
) -> dict[str, Any]:
    rows_raw, proc, elapsed, temp_meta = _run_snow_sql_query(snow, options, _formula_expected_sql(options), runner=runner)
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    if proc is None or proc.returncode != 0:
        row = _base_row(
            phase="formula_value_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=elapsed,
            status="failed",
            sanitized_error=sanitize_text((proc.stderr if proc else "") or (proc.stdout if proc else "")),
            recommendation="Grant read access to billing/warehouse metering views or provide a signed live-proof waiver.",
        )
        row.update({"artifact": Path(CLI_FORMULA_VALUE_REL).name, "row_index": 0, **_row_temp_sql_metadata(temp_meta)})
        return _payload(
            source="snowflake_cli_formula_value_results",
            rows=[row],
            failures=[{"code": "SNOWFLAKE_CLI_FORMULA_QUERY_FAILED", "sanitized_error": row["sanitized_error"]}],
        )
    expected = _normalize_snow_row(rows_raw[0]) if rows_raw else {}
    rendered_values = _rendered_value_by_field(root)
    executive_total = _section_packet_value(packet_payload, "Executive Landing", "ACCOUNT_BILLED_COST_USD")
    cost_total = _section_packet_value(packet_payload, "Cost & Contract", "ACCOUNT_BILLED_COST_USD")
    executive_cortex = _section_packet_value(packet_payload, "Executive Landing", "CORTEX_AI_COST_USD")
    cost_cortex = _section_packet_value(packet_payload, "Cost & Contract", "CORTEX_AI_COST_USD")
    if not expected:
        failures.append({"code": "SNOWFLAKE_CLI_FORMULA_EXPECTED_ROWS_MISSING"})
    for index, field in enumerate(REQUIRED_PACKET_FIELDS):
        packet_value = _section_packet_value(packet_payload, "Cost & Contract", field)
        flat_value = _section_flat_value(packet_payload, "Cost & Contract", field)
        live_expected = expected.get(field)
        rendered_value = rendered_values.get(field)
        tolerance = _tolerance_for_field(field)
        source_rows_present = _field_source_rows_present(field, expected)
        source_confirmed_zero = _source_confirmed_zero(live_expected, source_rows_present)
        selected_credit_column = CREDIT_COLUMN_BY_FIELD.get(field, "")
        failure_reasons: list[str] = []
        if source_rows_present and packet_value is None:
            failure_reasons.append("source rows exist but packet value is null")
        if source_rows_present and packet_value is not None and _as_float(packet_value) == 0.0 and not source_confirmed_zero:
            failure_reasons.append("packet value is default zero without source-confirmed zero")
        if not source_rows_present and _as_float(packet_value) == 0.0 and not source_confirmed_zero:
            failure_reasons.append("source rows are missing but UI/packet renders numeric zero")
        if packet_value != flat_value and not _values_match(packet_value, flat_value, tolerance):
            failure_reasons.append("packet value differs from flat value")
        if live_expected is None and source_rows_present:
            failure_reasons.append("live expected value is missing while source rows exist")
        if live_expected is not None and not _values_match(packet_value, live_expected, tolerance):
            failure_reasons.append("packet value differs from live expected value")
        if field in RENDERED_SUMMARY_FIELDS and rendered_value is not None and not _values_match(rendered_value, flat_value, tolerance):
            failure_reasons.append("rendered summary value differs from flat value")
        if field in CREDIT_COLUMN_BY_FIELD and not selected_credit_column:
            failure_reasons.append("selected credit column is missing")
        selected_credit_price = options.ai_credit_price if field == "CORTEX_AI_COST_USD" else options.credit_price
        if field.endswith("_USD") and selected_credit_price <= 0:
            failure_reasons.append("selected credit price is missing")
        passed = not failure_reasons
        row = _base_row(
            phase="formula_value_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=elapsed,
            status="passed" if passed else "failed",
            row_count=1,
            sanitized_error="" if passed else "; ".join(failure_reasons),
            recommendation="" if passed else "Refresh packet formulas or reconcile COST_DB-authority live formula calculations.",
        )
        row.update(
            {
                "artifact": Path(CLI_FORMULA_VALUE_REL).name,
                "row_index": index,
                "formula_field": field,
                "expected_source": "COST_DB authority via Snowflake account billing and packet marts",
                "source_rows_present": source_rows_present,
                "source_confirmed_zero": source_confirmed_zero,
                "packet_value": packet_value,
                "flat_value": flat_value,
                "rendered_value": rendered_value,
                "live_expected_value": live_expected,
                "selected_credit_column": selected_credit_column,
                "selected_credit_price": selected_credit_price,
                "tolerance": tolerance,
                "failure_reason": "" if passed else "; ".join(failure_reasons),
                "raw_sql_included": False,
                **_row_temp_sql_metadata(temp_meta),
            }
        )
        rows.append(row)
        if not passed:
            failures.append(
                {
                    "code": "SNOWFLAKE_CLI_FORMULA_VALUE_MISMATCH",
                    "formula_field": field,
                    "failure_reason": row["failure_reason"],
                }
            )
    total_match = _as_float(executive_total) == _as_float(cost_total)
    cortex_match = _as_float(executive_cortex) == _as_float(cost_cortex)
    if not total_match:
        failures.append({"code": "SNOWFLAKE_CLI_COST_EXECUTIVE_TOTAL_MISMATCH"})
    if not cortex_match:
        failures.append({"code": "SNOWFLAKE_CLI_COST_EXECUTIVE_CORTEX_MISMATCH"})
    bridge_delta = _section_packet_value(packet_payload, "Cost & Contract", "BILLING_BRIDGE_DELTA_CREDITS")
    account = _section_packet_value(packet_payload, "Cost & Contract", "ACCOUNT_BILLED_CREDITS")
    warehouse = _section_packet_value(packet_payload, "Cost & Contract", "WAREHOUSE_CREDITS")
    if None not in (bridge_delta, account, warehouse):
        expected_delta = (_as_float(account) or 0.0) - (_as_float(warehouse) or 0.0)
        if abs((_as_float(bridge_delta) or 0.0) - expected_delta) > 0.001:
            failures.append({"code": "SNOWFLAKE_CLI_BRIDGE_DELTA_MISMATCH"})
    extra = {
        "cost_executive_total_match": total_match,
        "cost_executive_cortex_match": cortex_match,
        "selected_credit_price": options.credit_price,
        "selected_ai_credit_price": options.ai_credit_price,
        "cost_db_formula_source": "https://github.com/jfreeze03/COST_DB/blob/main/streamlit_app.py",
    }
    return _payload(source="snowflake_cli_formula_value_results", rows=rows, failures=failures, extra=extra)


def _cost_reconciliation_results(formula_payload: Mapping[str, Any], options: SnowflakeCliValidationOptions) -> dict[str, Any]:
    rows_by_field = {
        str(row.get("formula_field") or ""): row
        for row in formula_payload.get("rows", [])
        if isinstance(row, Mapping)
    }
    fields = (
        "ACCOUNT_BILLED_CREDITS",
        "ACCOUNT_BILLED_COST_USD",
        "CLOUD_SERVICES_ADJUSTMENT",
        "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT",
        "WAREHOUSE_CREDITS",
        "SERVICE_OTHER_CREDITS",
        "BILLING_BRIDGE_DELTA_CREDITS",
        "BILLING_BRIDGE_DELTA_USD",
        "CORTEX_AI_CREDITS",
        "CORTEX_AI_COST_USD",
    )
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    account = _as_float(rows_by_field.get("ACCOUNT_BILLED_CREDITS", {}).get("packet_value"))
    warehouse = _as_float(rows_by_field.get("WAREHOUSE_CREDITS", {}).get("packet_value"))
    bridge_delta = _as_float(rows_by_field.get("BILLING_BRIDGE_DELTA_CREDITS", {}).get("packet_value"))
    adjustment = rows_by_field.get("CLOUD_SERVICES_ADJUSTMENT", {}).get("live_expected_value")
    for index, field in enumerate(fields):
        source = rows_by_field.get(field, {})
        failure_reasons: list[str] = []
        if not source:
            failure_reasons.append("formula field is missing from CLI formula validation")
        selected_credit_price = options.ai_credit_price if field == "CORTEX_AI_COST_USD" else options.credit_price
        if field.endswith("_USD") and selected_credit_price <= 0:
            failure_reasons.append("selected credit price is missing")
        if field in {"CLOUD_SERVICES_ADJUSTMENT", "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT"}:
            if not source:
                failure_reasons.append("cloud-services adjustment proof is missing")
            elif adjustment is None:
                failure_reasons.append("cloud-services adjustment source is unavailable")
            elif _as_float(adjustment) == 0.0 and bool(source.get("source_rows_present")) and not bool(source.get("source_confirmed_zero")):
                failure_reasons.append("cloud-services adjustment is silently zero")
        if field == "BILLING_BRIDGE_DELTA_CREDITS" and None not in (account, warehouse, bridge_delta):
            expected_delta = float(account or 0.0) - float(warehouse or 0.0)
            if abs(float(bridge_delta or 0.0) - expected_delta) > 0.001:
                failure_reasons.append("signed bridge delta does not equal account billed credits minus warehouse credits")
        passed = not failure_reasons
        row = _base_row(
            phase="cost_reconciliation_validation",
            command_kind="validation",
            options=options,
            status="passed" if passed else "failed",
            row_count=1,
            sanitized_error="" if passed else "; ".join(failure_reasons),
            recommendation="" if passed else "Reconcile live billing fields to COST_DB-authority account and warehouse formulas.",
        )
        row.update(
            {
                "artifact": Path(CLI_COST_RECONCILIATION_REL).name,
                "row_index": index,
                "formula_field": field,
                "source_rows_present": bool(source.get("source_rows_present")),
                "source_confirmed_zero": bool(source.get("source_confirmed_zero")),
                "live_expected_value": source.get("live_expected_value"),
                "packet_value": source.get("packet_value"),
                "flat_value": source.get("flat_value"),
                "selected_credit_column": source.get("selected_credit_column", ""),
                "selected_credit_price": selected_credit_price,
                "failure_reason": "" if passed else "; ".join(failure_reasons),
                "raw_sql_included": False,
            }
        )
        rows.append(row)
        if not passed:
            failures.append({"code": "SNOWFLAKE_CLI_COST_RECONCILIATION_FAILED", "formula_field": field, "failure_reason": row["failure_reason"]})
    return _payload(
        source="snowflake_cli_cost_reconciliation_results",
        rows=rows,
        failures=failures,
        extra={
            "account_billed_credits": account,
            "warehouse_credits": warehouse,
            "billing_bridge_delta_credits": bridge_delta,
            "cloud_services_adjustment": adjustment,
            "raw_sql_included": False,
        },
    )


def _cost_reconciliation_gate_results(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_rows = payload.get("rows")
    rows: list[Any] = raw_rows if isinstance(raw_rows, list) else []
    raw_failures = payload.get("failures")
    failures: list[Any] = raw_failures if isinstance(raw_failures, list) else []
    return {
        "source": "live_cost_reconciliation_gate_results",
        "generated_at": _utc_now(),
        "passed": bool(payload.get("passed")),
        "failure_count": int(payload.get("failure_count") or 0),
        "row_count": len(rows),
        "failures": failures,
        "raw_sql_included": False,
    }


def _summary_card_results(packet_payload: Mapping[str, Any], options: SnowflakeCliValidationOptions, root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    rendered_values = _rendered_value_by_field(root)
    rendered_payload = _load_json_if_exists(root, "artifacts/full_app_validation/rendered_formula_results.json")
    rendered_artifact_available = bool(rendered_payload) and not _rendered_formula_static_contract_only(rendered_payload)
    rendered_artifact_static_contract_only = bool(rendered_payload) and _rendered_formula_static_contract_only(rendered_payload)
    checks = (
        ("ACCOUNT_BILLED_COST_USD", "Executive Total Spend = Account Billed Cost"),
        ("CORTEX_AI_COST_USD", "Executive and Cost Cortex AI Spend = canonical Cortex spend"),
        ("WAREHOUSE_CREDITS", "Warehouse Credits uses warehouse bridge/breakdown"),
    )
    for index, (field, contract) in enumerate(checks):
        executive = _section_packet_value(packet_payload, "Executive Landing", field)
        cost = _section_packet_value(packet_payload, "Cost & Contract", field)
        flat = _section_flat_value(packet_payload, "Cost & Contract", field)
        rendered = rendered_values.get(field)
        tolerance = _tolerance_for_field(field)
        failure_reasons: list[str] = []
        if field in {"ACCOUNT_BILLED_COST_USD", "CORTEX_AI_COST_USD"} and not _values_match(executive, cost, tolerance):
            failure_reasons.append("Executive and Cost values differ for same scope/window")
        if not _values_match(cost, flat, tolerance):
            failure_reasons.append("Cost packet value differs from flat value")
        if rendered is not None and not _values_match(rendered, flat, tolerance):
            failure_reasons.append("Rendered summary value differs from flat value")
        if field == "ACCOUNT_BILLED_COST_USD" and cost is None:
            failure_reasons.append("Account billing summary field is missing; UI must render Billing reconciliation pending")
        if field == "ACCOUNT_BILLED_COST_USD" and _as_float(cost) == 0.0 and _as_float(_section_packet_value(packet_payload, "Cost & Contract", "CORTEX_AI_COST_USD")) not in (None, 0.0):
            failure_reasons.append("Total Spend renders zero while Cortex spend is nonzero")
        if field == "CORTEX_AI_COST_USD" and cost is None:
            failure_reasons.append("Cortex spend summary field is missing; UI must render Cortex spend unavailable")
        if options.profile in {"internal_live", "prod_candidate"} and not rendered_artifact_available:
            failure_reasons.append("rendered summary formula artifact is required for live launch profiles")
        passed = not failure_reasons
        row = _base_row(
            phase="summary_card_value_validation",
            command_kind="validation",
            options=options,
            status="passed" if passed else "failed",
            row_count=1,
            sanitized_error="" if passed else "; ".join(failure_reasons),
            recommendation="" if passed else "Ensure both sections read the same flat packet field for summary cards.",
        )
        row.update(
            {
                "artifact": Path(CLI_SUMMARY_CARD_REL).name,
                "row_index": index,
                "formula_field": field,
                "contract": contract,
                "executive_value": executive,
                "cost_value": cost,
                "flat_value": flat,
                "rendered_value": rendered,
                "rendered_artifact_available": rendered_artifact_available,
                "rendered_artifact_static_contract_only": rendered_artifact_static_contract_only,
                "tolerance": tolerance,
                "failure_reason": "" if passed else "; ".join(failure_reasons),
            }
        )
        rows.append(row)
        if not passed:
            failures.append(
                {
                    "code": "SNOWFLAKE_CLI_SUMMARY_CARD_VALUE_MISMATCH",
                    "formula_field": field,
                    "failure_reason": row["failure_reason"],
                }
            )
    return _payload(
        source="snowflake_cli_summary_card_value_results",
        rows=rows,
        failures=failures,
        extra={
            "rendered_artifact_available": rendered_artifact_available,
            "rendered_artifact_static_contract_only": rendered_artifact_static_contract_only,
        },
    )


def _query_budget_results(
    root: Path,
    snow: str,
    options: SnowflakeCliValidationOptions,
    *,
    runner: Runner,
) -> dict[str, Any]:
    if not options.query_history_enabled:
        row = _base_row(
            phase="query_budget_validation",
            command_kind="validation",
            options=options,
            status="skipped",
            recommendation="Set OVERWATCH_QUERY_PLAN_PROOF=1 to collect local query-history proof.",
        )
        row.update({"artifact": Path(CLI_QUERY_BUDGET_REL).name, "row_index": 0})
        return _payload(
            source="snowflake_cli_query_budget_results",
            rows=[row],
            skipped=True,
            skip_reason="OVERWATCH_QUERY_PLAN_PROOF is not enabled.",
            extra={"query_history_required": options.profile in {"internal_live", "prod_candidate"}},
        )
    rows_raw, proc, elapsed, temp_meta = _run_snow_sql_query(snow, options, _query_history_sql(options), runner=runner)
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    if proc is None or proc.returncode != 0:
        row = _base_row(
            phase="query_budget_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=elapsed,
            status="failed",
            row_count=len(rows_raw),
            sanitized_error=sanitize_text((proc.stderr if proc else "") or (proc.stdout if proc else "")),
            recommendation="Grant query history access or provide a profile-aware waiver.",
        )
        row.update({"artifact": Path(CLI_QUERY_BUDGET_REL).name, "row_index": 0, **_row_temp_sql_metadata(temp_meta)})
        return _payload(
            source="snowflake_cli_query_budget_results",
            rows=[row],
            failures=[{"code": "SNOWFLAKE_CLI_QUERY_HISTORY_PROOF_FAILED", "sanitized_error": row["sanitized_error"]}],
        )
    seen_boundaries: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(rows_raw):
        parsed = _normalize_snow_row(raw)
        section = str(parsed.get("section") or "")
        workflow = str(parsed.get("workflow") or "")
        boundary = str(parsed.get("boundary") or "")
        query_count = int(_as_float(parsed.get("query_count")) or 0)
        failure_reasons: list[str] = []
        if not section or not workflow or not boundary or "unknown" in {section.lower(), workflow.lower(), boundary.lower()}:
            failure_reasons.append("query history proof is missing section/workflow/boundary metadata")
        if boundary == "first_paint_packet" and query_count > 1:
            failure_reasons.append("first paint packet query count exceeds one")
        if boundary in {"warm_first_paint", "route_action", "query_search_no_click"} and query_count > 0:
            failure_reasons.append(f"{boundary} must run zero queries")
        seen_boundaries.add((section, workflow, boundary))
        passed = not failure_reasons
        row = _base_row(
            phase="query_budget_validation",
            command_kind="sql_query",
            options=options,
            elapsed_ms=elapsed,
            status="passed" if passed else "failed",
            row_count=1,
            sanitized_error="" if passed else "; ".join(failure_reasons),
            recommendation="" if passed else "Ensure query tags include section/workflow/boundary and first-paint budgets are honored.",
        )
        row.update(
            {
                "artifact": Path(CLI_QUERY_BUDGET_REL).name,
                "row_index": index,
                "section": section,
                "workflow": workflow,
                "boundary": boundary,
                "query_count": query_count,
                "bytes_scanned": _as_float(parsed.get("bytes_scanned")) or 0,
                "rows_produced": _as_float(parsed.get("rows_produced")) or 0,
                "max_elapsed_ms": _as_float(parsed.get("max_elapsed_ms")) or 0,
                "warehouse": _safe_label(str(parsed.get("warehouse") or "")),
                "query_tag_prefix": _safe_label(str(parsed.get("query_tag_prefix") or options.query_tag_prefix)),
                "failure_reason": "" if passed else "; ".join(failure_reasons),
                "raw_sql_included": False,
                **_row_temp_sql_metadata(temp_meta),
            }
        )
        rows.append(row)
        if not passed:
            failures.append({"code": "SNOWFLAKE_CLI_QUERY_BUDGET_BOUNDARY_FAILED", "failure_reason": row["failure_reason"]})
    runtime_rows, runtime_failures = _runtime_query_budget_rows(
        root,
        options,
        start_index=len(rows),
        current_commit=_git_commit(root),
    )
    for row in runtime_rows:
        rows.append(row)
        seen_boundaries.add((str(row.get("section") or ""), str(row.get("workflow") or ""), str(row.get("boundary") or "")))
    failures.extend(runtime_failures)

    missing = [
        {"section": section, "workflow": workflow, "boundary": boundary}
        for section, workflow, boundary in REQUIRED_QUERY_BUDGET_BOUNDARIES
        if (section, workflow, boundary) not in seen_boundaries
    ]
    if missing:
        failures.append({"code": "SNOWFLAKE_CLI_QUERY_BUDGET_BOUNDARY_MISSING", "missing_boundaries": missing[:20]})
    if not rows:
        failures.append({"code": "SNOWFLAKE_CLI_QUERY_BUDGET_ROWS_MISSING"})
    return _payload(
        source="snowflake_cli_query_budget_results",
        rows=rows,
        failures=failures,
        extra={"required_boundaries": list(REQUIRED_QUERY_BUDGET_BOUNDARIES)},
    )


def _all_rows(artifacts: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel in (
        CLI_CAPABILITY_REL,
        CLI_CONNECTION_REL,
        CLI_SETUP_REL,
        CLI_SETUP_MIGRATION_REL,
        SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL,
        CLI_PACKET_VALUE_REL,
        CLI_FORMULA_VALUE_REL,
        CLI_COST_RECONCILIATION_REL,
        CLI_SUMMARY_CARD_REL,
        CLI_QUERY_BUDGET_REL,
        CLI_TEMP_FILE_HYGIENE_REL,
    ):
        payload = artifacts.get(rel)
        if isinstance(payload, Mapping):
            for row in payload.get("rows", []):
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _refresh_rehearsal_live_dependency_artifacts(root: Path, profile: str) -> None:
    from tools.contracts.cortex_token_efficiency_validation import (
        write_cortex_token_efficiency_artifacts,
    )
    from tools.contracts.security_credential_validation import (
        write_security_credential_validation_artifacts,
    )

    write_security_credential_validation_artifacts(root, profile=profile)
    write_cortex_token_efficiency_artifacts(root, profile=profile)


def evaluate_snowflake_cli_live_gate(
    artifacts: Mapping[str, Any],
    profile: str,
    waivers: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    waiver_gates = {
        str(row.get("gate") or "")
        for row in waivers
        if bool(row.get("valid"))
    }
    waived = bool(waiver_gates & {"snowflake_cli_live_validation", "live_snowflake_validation", "snowflake_execution_validation"})
    live_required = profile in {"internal_live", "prod_candidate"}
    core_rels = (
        CLI_CONNECTION_REL,
        CLI_SETUP_REL,
        CLI_SETUP_MIGRATION_REL,
        SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL,
        CLI_PACKET_VALUE_REL,
        CLI_FORMULA_VALUE_REL,
        CLI_COST_RECONCILIATION_REL,
        CLI_SUMMARY_CARD_REL,
    )
    skipped = all(bool((artifacts.get(rel) or {}).get("skipped")) for rel in core_rels if isinstance(artifacts.get(rel), Mapping))
    if skipped and live_required and not waived:
        failures.append(
            {
                "code": "SNOWFLAKE_CLI_LIVE_PROOF_MISSING",
                "profile": profile,
                "recommendation": "Run scripts/run_snowflake_cli_live_validation with a Snowflake CLI connection or provide a signed waiver.",
            }
        )
    for rel in core_rels + (
        CLI_MANIFEST_RECONCILIATION_REL,
        CLI_FORMULA_VALUE_GATE_REL,
        CLI_COST_RECONCILIATION_GATE_REL,
        CLI_TEMP_FILE_HYGIENE_GATE_REL,
        CLI_SETUP_MIGRATION_GATE_REL,
        PACKET_AVAILABILITY_GATE_REL,
    ):
        payload = artifacts.get(rel)
        if not isinstance(payload, Mapping):
            failures.append({"code": "SNOWFLAKE_CLI_ARTIFACT_MISSING", "artifact": rel})
            continue
        if not bool(payload.get("passed")) and not (bool(payload.get("skipped")) and profile == "internal_fixture"):
            failures.append({"code": "SNOWFLAKE_CLI_ARTIFACT_FAILED", "artifact": rel, "failure_count": int(payload.get("failure_count") or 0)})
    query_budget = artifacts.get(CLI_QUERY_BUDGET_REL)
    if isinstance(query_budget, Mapping) and bool(query_budget.get("skipped")) and live_required and not waived:
        failures.append({"code": "SNOWFLAKE_CLI_QUERY_BUDGET_PROOF_MISSING", "recommendation": "Enable OVERWATCH_QUERY_PLAN_PROOF=1 or provide a waiver."})
    elif isinstance(query_budget, Mapping) and not bool(query_budget.get("passed")):
        failures.append({"code": "SNOWFLAKE_CLI_QUERY_BUDGET_FAILED"})
    manifest_reconciliation = artifacts.get(CLI_MANIFEST_RECONCILIATION_REL)
    if isinstance(manifest_reconciliation, Mapping) and not bool(manifest_reconciliation.get("passed")):
        failures.append({"code": "SNOWFLAKE_CLI_MANIFEST_RECONCILIATION_FAILED"})
    artifacts_serialized = json.dumps(artifacts, default=str)
    token_path_leak_count = len(
        re.findall(
            r"(?i)(token[_-]?file[_-]?path|--token-file-path|TOK_[A-Za-z0-9_-]*token-secret|[A-Za-z]:\\\\[^\"']*token[^\"']*)",
            artifacts_serialized,
        )
    )
    temp_path_leak_count = len(
        re.findall(r"(?i)([A-Za-z]:\\\\|/)[^\"'\\s]*overwatch_snowflake_validation_[^\"'\\s]*\\.sql", artifacts_serialized)
    )
    if token_path_leak_count:
        failures.append({"code": "SNOWFLAKE_CLI_TOKEN_FILE_PATH_LEAK", "leak_count": token_path_leak_count})
    if temp_path_leak_count:
        failures.append({"code": "SNOWFLAKE_CLI_TEMP_SQL_FILE_PATH_LEAK", "leak_count": temp_path_leak_count})
    for row in _all_rows(artifacts):
        serialized = json.dumps(row, default=str)
        if bool(row.get("raw_sql_included")):
            failures.append({"code": "SNOWFLAKE_CLI_RAW_SQL_INCLUDED", "phase": row.get("phase")})
        if re.search(r"(?i)(password|token|private[_-]?key|connection[_-]?string)\s*[:=]", serialized):
            failures.append({"code": "SNOWFLAKE_CLI_SECRET_LIKE_TEXT", "phase": row.get("phase")})

    def passed_not_skipped(rel: str) -> bool:
        payload = artifacts.get(rel)
        return isinstance(payload, Mapping) and bool(payload.get("passed")) and not bool(payload.get("skipped"))

    def executed_not_skipped(rel: str) -> bool:
        payload = artifacts.get(rel)
        return isinstance(payload, Mapping) and not bool(payload.get("skipped"))

    live_executed = all(
        executed_not_skipped(rel)
        for rel in (
            CLI_CONNECTION_REL,
            CLI_SETUP_REL,
            CLI_SETUP_MIGRATION_REL,
            SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL,
            CLI_PACKET_VALUE_REL,
            CLI_FORMULA_VALUE_REL,
            CLI_COST_RECONCILIATION_REL,
        )
    )
    live_passed = live_executed and not failures
    skip_reasons = [
        str((artifacts.get(rel) or {}).get("skip_reason") or "")
        for rel in core_rels
        if isinstance(artifacts.get(rel), Mapping) and bool((artifacts.get(rel) or {}).get("skipped"))
    ]
    if live_passed and skipped:
        failures.append({"code": "SNOWFLAKE_CLI_AMBIGUOUS_LIVE_AND_SKIPPED"})
        live_passed = False

    return {
        "source": "snowflake_cli_live_gate_results",
        "generated_at": _utc_now(),
        "passed": not failures,
        "snowflake_cli_gate_passed": not failures,
        "failure_count": len(failures),
        "snowflake_cli_failure_count": len(failures),
        "failures": failures,
        "launch_profile": profile,
        "live_required": live_required,
        "snowflake_cli_live_required": live_required,
        "skipped": skipped,
        "snowflake_cli_live_skipped": skipped,
        "snowflake_cli_skip_reason": "; ".join(reason for reason in skip_reasons if reason),
        "waived": waived,
        "snowflake_cli_live_waived": waived,
        "snowflake_cli_live_executed": live_executed,
        "snowflake_cli_live_passed": live_passed,
        "snowflake_cli_token_auth_used": bool(
            any(bool(row.get("authenticator")) for row in _all_rows(artifacts))
        ),
        "snowflake_cli_token_file_supplied": bool(
            any(bool(row.get("token_file_supplied")) for row in _all_rows(artifacts))
        ),
        "snowflake_cli_token_path_leak_count": token_path_leak_count,
        "snowflake_cli_temp_sql_path_leak_count": temp_path_leak_count,
        "connection_passed": passed_not_skipped(CLI_CONNECTION_REL),
        "setup_validation_passed": passed_not_skipped(CLI_SETUP_REL),
        "setup_migration_live_passed": passed_not_skipped(CLI_SETUP_MIGRATION_REL)
        and isinstance(artifacts.get(CLI_SETUP_MIGRATION_GATE_REL), Mapping)
        and bool(artifacts.get(CLI_SETUP_MIGRATION_GATE_REL, {}).get("passed")),
        "packet_value_passed": passed_not_skipped(CLI_PACKET_VALUE_REL),
        "formula_value_passed": passed_not_skipped(CLI_FORMULA_VALUE_REL),
        "packet_availability_passed": passed_not_skipped(SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL),
        "cost_reconciliation_passed": passed_not_skipped(CLI_COST_RECONCILIATION_REL),
        "summary_card_value_passed": passed_not_skipped(CLI_SUMMARY_CARD_REL),
        "query_budget_passed": passed_not_skipped(CLI_QUERY_BUDGET_REL),
        "temp_file_hygiene_passed": isinstance(artifacts.get(CLI_TEMP_FILE_HYGIENE_GATE_REL), Mapping)
        and bool(artifacts.get(CLI_TEMP_FILE_HYGIENE_GATE_REL, {}).get("passed")),
        "temp_sql_file_leftover_count": int(
            (artifacts.get(CLI_TEMP_FILE_HYGIENE_GATE_REL, {}) or {}).get("temp_sql_file_leftover_count") or 0
        )
        if isinstance(artifacts.get(CLI_TEMP_FILE_HYGIENE_GATE_REL), Mapping)
        else 0,
        "manifest_reconciliation_passed": isinstance(manifest_reconciliation, Mapping) and bool(manifest_reconciliation.get("passed")),
        "raw_sql_included": False,
    }


def _payload_failure_reason(mapping: Mapping[str, Any]) -> str:
    failure_reason = str(mapping.get("failure_reason") or "")
    if failure_reason:
        return failure_reason
    failures = mapping.get("failures")
    if isinstance(failures, Sequence) and not isinstance(failures, (str, bytes)):
        reasons: list[str] = []
        for failure in failures:
            if not isinstance(failure, Mapping):
                continue
            reason = str(
                failure.get("failure_reason")
                or failure.get("reason")
                or failure.get("code")
                or failure.get("check")
                or ""
            )
            if reason:
                reasons.append(reason)
        if reasons:
            return "; ".join(reasons[:3])
    return ""


def _artifact_passed_or_fixture_skipped(
    payload: object,
    profile: str,
    *,
    require_live_execution: bool = False,
) -> tuple[bool, bool, str]:
    mapping = payload if isinstance(payload, Mapping) else {}
    if not mapping:
        return False, False, "artifact_missing"
    skipped = bool(mapping.get("skipped") or mapping.get("live_skipped"))
    if require_live_execution and profile in {"internal_live", "prod_candidate"}:
        payload_profile = str(mapping.get("launch_profile") or mapping.get("profile") or "")
        if payload_profile and payload_profile not in {"internal_live", "prod_candidate"}:
            return False, skipped, "live profile cannot use fixture-profile deployment proof"
        if not bool(mapping.get("live_required")):
            return False, skipped, "live profile requires a live-required deployment proof row"
        if skipped:
            return False, True, "live profile requires this deployment rehearsal phase"
        if not bool(mapping.get("live_executed")):
            return False, skipped, "live proof did not execute"
        if not bool(mapping.get("live_passed")):
            return False, skipped, _payload_failure_reason(mapping) or "live proof did not pass"
    if skipped and profile == "internal_fixture":
        return True, True, str(mapping.get("skip_reason") or "fixture profile skip")
    return bool(mapping.get("passed")) and not skipped, skipped, _payload_failure_reason(mapping)


def _token_auth_sanitization_payload(
    gate: Mapping[str, Any],
    options: SnowflakeCliValidationOptions,
    *,
    token_path_leak_count: int,
    temp_path_leak_count: int,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    token_supplied = bool(options.token_file_path)
    authenticator_supplied = bool(options.authenticator)
    if not gate:
        failures.append({"code": "SNOWFLAKE_CLI_GATE_MISSING"})
    if token_path_leak_count:
        failures.append({"code": "SNOWFLAKE_CLI_TOKEN_FILE_PATH_LEAK", "leak_count": token_path_leak_count})
    if temp_path_leak_count:
        failures.append({"code": "SNOWFLAKE_CLI_TEMP_SQL_FILE_PATH_LEAK", "leak_count": temp_path_leak_count})
    if bool(gate.get("raw_sql_included")):
        failures.append({"code": "SNOWFLAKE_CLI_RAW_SQL_INCLUDED"})
    if token_supplied and not bool(gate.get("snowflake_cli_token_file_supplied")):
        failures.append({"code": "SNOWFLAKE_CLI_TOKEN_FILE_NOT_RECORDED_AS_SUPPLIED"})
    if authenticator_supplied and not bool(gate.get("snowflake_cli_token_auth_used")):
        failures.append({"code": "SNOWFLAKE_CLI_AUTHENTICATOR_NOT_USED"})
    return {
        "source": "snowflake_cli_token_auth_sanitization",
        "passed": not failures,
        "skipped": not token_supplied and not authenticator_supplied,
        "failure_count": len(failures),
        "failures": failures,
        "token_file_supplied": token_supplied,
        "authenticator_supplied": authenticator_supplied,
        "token_path_leak_count": token_path_leak_count,
        "temp_sql_path_leak_count": temp_path_leak_count,
        "raw_sql_included": False,
    }


def _load_gate(root: Path, rel: str) -> Mapping[str, Any]:
    try:
        payload = json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _phase_artifact_path(artifact: str) -> str:
    if artifact.startswith("artifacts/"):
        return artifact
    if artifact.endswith("_gate_results.json"):
        return f"artifacts/launch_readiness/{artifact}"
    return artifact


def _payload_rows(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, Mapping)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    return []


def _row_identifier(row: Mapping[str, Any]) -> str:
    for key in ("validation_id", "row_id", "id", "phase", "check", "source"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


def _payload_reference(payload: object) -> tuple[str, str, str]:
    rows = _payload_rows(payload)
    if rows:
        row = rows[0]
        return _row_identifier(row), str(row.get("producer") or ""), str(row.get("commit_sha") or "")
    if isinstance(payload, Mapping):
        return str(payload.get("source") or ""), str(payload.get("producer") or ""), str(payload.get("commit_sha") or "")
    return "", "", ""


def _artifact_reference_details(
    *,
    root: Path,
    artifact: str,
    payload: object,
    current_commit: str,
) -> dict[str, Any]:
    artifact_path = _phase_artifact_path(artifact)
    file_payload = _load_gate(root, artifact_path)
    source_payload = file_payload or (payload if isinstance(payload, Mapping) else {})
    row_id, producer, row_commit = _payload_reference(source_payload)
    artifact_exists = (root / artifact_path).exists() if artifact_path.startswith("artifacts/") else bool(payload)
    commit_matches = not row_commit or not current_commit or row_commit == current_commit
    return {
        "artifact_path": artifact_path,
        "referenced_artifact_exists": artifact_exists,
        "referenced_row_id": row_id,
        "referenced_row_found": bool(row_id),
        "referenced_producer": producer,
        "referenced_commit_sha": row_commit,
        "referenced_commit_matches": commit_matches,
    }


def _producer_signature(row: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {
            "producer": "snowflake_cli_live_validation",
            "phase": row.get("phase"),
            "artifact_path": row.get("artifact_path"),
            "referenced_row_id": row.get("referenced_row_id"),
            "passed": row.get("passed"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _production_rehearsal_phase_row(
    *,
    root: Path,
    phase: str,
    artifact: str,
    payload: object,
    profile: str,
    required_live: bool,
    current_commit: str,
    token_path_leak_count: int = 0,
    temp_path_leak_count: int = 0,
    raw_sql_leak_count: int = 0,
    require_live_execution: bool = False,
) -> dict[str, Any]:
    passed, skipped, reason = _artifact_passed_or_fixture_skipped(
        payload,
        profile,
        require_live_execution=require_live_execution,
    )
    if not payload and not required_live and profile == "internal_fixture":
        passed = True
        skipped = True
        reason = "fixture profile skip"
    if (
        profile == "internal_fixture"
        and not required_live
        and phase in {"credential_expiration_live_chain", "cortex_token_efficiency_live_chain"}
        and not passed
    ):
        passed = True
        skipped = True
        reason = "fixture profile skip"
    if (
        profile == "internal_fixture"
        and not required_live
        and phase == "role_privilege_matrix_validation"
        and not passed
        and "Setup/migration live or fixture-skip gate is missing" in reason
    ):
        passed = True
        skipped = True
        reason = "fixture profile skip"
    if required_live and skipped:
        passed = False
        reason = reason or "live profile requires this deployment rehearsal phase"
    if token_path_leak_count or temp_path_leak_count or raw_sql_leak_count:
        passed = False
        reason = "sanitization leak detected"
    reference = _artifact_reference_details(
        root=root,
        artifact=artifact,
        payload=payload,
        current_commit=current_commit,
    )
    if not reference["referenced_row_found"] and not (skipped and profile == "internal_fixture"):
        passed = False
        reason = reason or "referenced artifact row missing"
    if not reference["referenced_commit_matches"]:
        passed = False
        reason = reason or "referenced artifact commit mismatch"
    row = {
        "producer": "snowflake_cli_live_validation",
        "producer_signature": "",
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": current_commit,
        "source": "production_deployment_rehearsal",
        "runtime_source": "snowflake_cli_phase_artifact",
        "section": "Production Deployment",
        "workflow": "Deployment rehearsal",
        "phase": phase,
        "artifact": Path(artifact).name,
        **reference,
        "passed": passed,
        "skipped": skipped,
        "required_live": required_live,
        "failure_reason": "" if passed else reason or "deployment rehearsal phase failed",
        "token_path_leak_count": token_path_leak_count,
        "temp_sql_path_leak_count": temp_path_leak_count,
        "raw_sql_leak_count": raw_sql_leak_count,
        "raw_sql_included": False,
    }
    row["producer_signature"] = _producer_signature(row)
    return row


def build_production_deployment_rehearsal_results(
    root: Path | str,
    artifacts: Mapping[str, Any],
    options: SnowflakeCliValidationOptions,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    current_commit = _git_commit(root_path)
    live_profile = options.profile in {"internal_live", "prod_candidate"}
    gate = artifacts.get(CLI_LAUNCH_GATE_REL, {})
    token_path_leak_count = int(_as_mapping(gate).get("snowflake_cli_token_path_leak_count") or 0)
    temp_path_leak_count = int(_as_mapping(gate).get("snowflake_cli_temp_sql_path_leak_count") or 0)
    token_auth_payload = _token_auth_sanitization_payload(
        _as_mapping(gate),
        options,
        token_path_leak_count=token_path_leak_count,
        temp_path_leak_count=temp_path_leak_count,
    )

    phase_specs: list[tuple[str, str, object, bool, bool]] = [
        ("cli_capability_check", CLI_CAPABILITY_REL, artifacts.get(CLI_CAPABILITY_REL), False, False),
        ("connection_test", CLI_CONNECTION_REL, artifacts.get(CLI_CONNECTION_REL), live_profile, False),
        (
            "token_auth_sanitization",
            CLI_LAUNCH_GATE_REL,
            token_auth_payload,
            live_profile and bool(options.token_file_path),
            False,
        ),
        ("temp_sql_file_hygiene", CLI_TEMP_FILE_HYGIENE_GATE_REL, artifacts.get(CLI_TEMP_FILE_HYGIENE_GATE_REL), False, False),
        ("setup_sql_availability", CLI_SETUP_REL, artifacts.get(CLI_SETUP_REL), live_profile, False),
        ("validation_sql_availability", CLI_SETUP_REL, artifacts.get(CLI_SETUP_REL), live_profile, False),
        ("migration_ledger_validation", CLI_SETUP_MIGRATION_GATE_REL, artifacts.get(CLI_SETUP_MIGRATION_GATE_REL), live_profile, False),
        ("required_object_existence", CLI_SETUP_MIGRATION_REL, artifacts.get(CLI_SETUP_MIGRATION_REL), live_profile, False),
        (
            "role_privilege_matrix_validation",
            "production_deployment_readiness_gate_results.json",
            _load_gate(root_path, "artifacts/launch_readiness/production_deployment_readiness_gate_results.json"),
            False,
            False,
        ),
        ("packet_availability_validation", PACKET_AVAILABILITY_GATE_REL, artifacts.get(PACKET_AVAILABILITY_GATE_REL), live_profile, False),
        ("cost_reconciliation_validation", CLI_COST_RECONCILIATION_GATE_REL, artifacts.get(CLI_COST_RECONCILIATION_GATE_REL), live_profile, False),
        (
            "credential_expiration_live_chain",
            "security_credential_expiration_live_gate_results.json",
            _load_gate(root_path, "artifacts/launch_readiness/security_credential_expiration_live_gate_results.json"),
            live_profile,
            live_profile,
        ),
        (
            "cortex_token_efficiency_live_chain",
            "cortex_token_efficiency_live_gate_results.json",
            _load_gate(root_path, "artifacts/launch_readiness/cortex_token_efficiency_live_gate_results.json"),
            live_profile,
            live_profile,
        ),
        ("fast_refresh_smoke_or_skip", CLI_SETUP_REL, artifacts.get(CLI_SETUP_REL), False, False),
        (
            "post_deploy_app_smoke",
            "app_entry_smoke_gate_results.json",
            _load_gate(root_path, "artifacts/launch_readiness/app_entry_smoke_gate_results.json"),
            False,
            False,
        ),
    ]
    rows = [
        _production_rehearsal_phase_row(
            root=root_path,
            phase=phase,
            artifact=artifact,
            payload=payload,
            profile=options.profile,
            required_live=required_live,
            current_commit=current_commit,
            token_path_leak_count=token_path_leak_count if phase == "token_auth_sanitization" else 0,
            temp_path_leak_count=temp_path_leak_count if phase == "temp_sql_file_hygiene" else 0,
            raw_sql_leak_count=0,
            require_live_execution=require_live_execution,
        )
        for phase, artifact, payload, required_live, require_live_execution in phase_specs
    ]
    failures = [row for row in rows if not bool(row.get("passed"))]
    live_skipped_without_waiver = [
        row for row in rows if bool(row.get("required_live")) and bool(row.get("skipped")) and not row.get("passed")
    ]
    return {
        "source": "production_deployment_rehearsal_results",
        "producer": "snowflake_cli_live_validation",
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": current_commit,
        "launch_profile": options.profile,
        "passed": not failures,
        "deployment_rehearsal_passed": not failures,
        "failure_count": len(failures),
        "phase_count": len(rows),
        "live_required": live_profile,
        "live_skipped_without_waiver_count": len(live_skipped_without_waiver),
        "token_path_leak_count": token_path_leak_count,
        "temp_sql_path_leak_count": temp_path_leak_count,
        "temp_sql_file_leftover_count": int(_as_mapping(gate).get("temp_sql_file_leftover_count") or 0),
        "connection_test_artifact_path": "artifacts/snowflake_validation/snowflake_cli_connection_results.json",
        "connection_test_row_id": next((str(row.get("referenced_row_id")) for row in rows if row.get("phase") == "connection_test"), ""),
        "setup_migration_artifact_path": CLI_SETUP_MIGRATION_REL,
        "setup_migration_row_id": next((str(row.get("referenced_row_id")) for row in rows if row.get("phase") == "migration_ledger_validation"), ""),
        "required_object_validation_artifact_path": CLI_SETUP_MIGRATION_REL,
        "packet_availability_artifact_path": PACKET_AVAILABILITY_GATE_REL,
        "cost_reconciliation_artifact_path": CLI_COST_RECONCILIATION_GATE_REL,
        "credential_live_artifact_path": "artifacts/launch_readiness/security_credential_expiration_live_gate_results.json",
        "cortex_live_artifact_path": "artifacts/launch_readiness/cortex_token_efficiency_live_gate_results.json",
        "first_paint_artifact_path": "artifacts/full_app_validation/first_paint_performance_results.json",
        "deterministic_snapshot_artifact_path": "artifacts/full_app_validation/deterministic_streamlit_render_results.json",
        "app_entry_artifact_path": "artifacts/launch_readiness/app_entry_smoke_gate_results.json",
        "temp_file_hygiene_artifact_path": CLI_TEMP_FILE_HYGIENE_GATE_REL,
        "raw_sql_included": False,
        "rows": rows,
        "failures": failures,
    }


def evaluate_production_deployment_rehearsal_gate(payload: object) -> dict[str, Any]:
    results = payload if isinstance(payload, Mapping) else {}
    failures = list(results.get("failures") or [])
    if not results:
        failures = [{"code": "PRODUCTION_DEPLOYMENT_REHEARSAL_MISSING"}]
    elif not bool(results.get("passed")) and not failures:
        failures = [{"code": "PRODUCTION_DEPLOYMENT_REHEARSAL_FAILED"}]
    return {
        "source": "production_deployment_rehearsal_gate_results",
        "producer": "snowflake_cli_live_validation",
        "generated_at": _utc_now(),
        "passed": not failures and bool(results.get("passed")),
        "deployment_rehearsal_passed": not failures and bool(results.get("passed")),
        "failure_count": len(failures),
        "phase_count": int(results.get("phase_count") or 0),
        "live_required": bool(results.get("live_required")),
        "live_skipped_without_waiver_count": int(results.get("live_skipped_without_waiver_count") or 0),
        "token_path_leak_count": int(results.get("token_path_leak_count") or 0),
        "temp_sql_path_leak_count": int(results.get("temp_sql_path_leak_count") or 0),
        "temp_sql_file_leftover_count": int(results.get("temp_sql_file_leftover_count") or 0),
        "failures": failures,
        "raw_sql_included": False,
    }


def run_snowflake_cli_live_validation(
    root: Path | str = ".",
    *,
    options: SnowflakeCliValidationOptions,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    _TEMP_SQL_EVENTS.clear()
    if not options.connection:
        reason = "Snowflake CLI live validation skipped because no --connection or OVERWATCH_SNOWFLAKE_CLI_CONNECTION was provided."
        return _skipped_artifacts(options, reason=reason)
    snow = _snowflake_cli_path()
    artifacts: dict[str, Any] = {}
    artifacts[CLI_CAPABILITY_REL] = _capability_results(snow, options, runner=runner)
    if not bool(artifacts[CLI_CAPABILITY_REL].get("passed")):
        artifacts[CLI_CONNECTION_REL] = _payload(
            source="snowflake_cli_connection_results",
            rows=[
                {
                    **_base_row(
                        phase="connection_test",
                        command_kind="connection_test",
                        options=options,
                        status="failed",
                        sanitized_error="Snowflake CLI is not available.",
                        recommendation="Install snowflake-cli and make snow visible on PATH.",
                    ),
                    "artifact": Path(CLI_CONNECTION_REL).name,
                    "row_index": 0,
                }
            ],
            failures=[{"code": "SNOWFLAKE_CLI_NOT_AVAILABLE"}],
        )
        for rel in (
            CLI_SETUP_REL,
            CLI_SETUP_MIGRATION_REL,
            SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL,
            PACKET_AVAILABILITY_MATRIX_REL,
            CLI_PACKET_VALUE_REL,
            CLI_FORMULA_VALUE_REL,
            CLI_COST_RECONCILIATION_REL,
            CLI_SUMMARY_CARD_REL,
            CLI_QUERY_BUDGET_REL,
        ):
            artifacts[rel] = _payload(source=Path(rel).stem, rows=[], failures=[{"code": "SNOWFLAKE_CLI_NOT_AVAILABLE"}])
    else:
        artifacts[CLI_CONNECTION_REL] = _connection_results(snow, options, runner=runner)
        if bool(artifacts[CLI_CONNECTION_REL].get("passed")):
            artifacts[CLI_SETUP_REL] = _setup_validation_results(root_path, snow, options, runner=runner)
            artifacts[CLI_SETUP_MIGRATION_REL] = _setup_migration_live_results(root_path, snow, options, runner=runner)
            artifacts.update(_packet_availability_results(snow, options, runner=runner))
            artifacts[CLI_PACKET_VALUE_REL] = _packet_value_results(snow, options, runner=runner)
            artifacts[CLI_FORMULA_VALUE_REL] = _formula_value_results(snow, options, artifacts[CLI_PACKET_VALUE_REL], root_path, runner=runner)
            artifacts[CLI_COST_RECONCILIATION_REL] = _cost_reconciliation_results(artifacts[CLI_FORMULA_VALUE_REL], options)
            artifacts[CLI_SUMMARY_CARD_REL] = _summary_card_results(artifacts[CLI_PACKET_VALUE_REL], options, root_path)
            artifacts[CLI_QUERY_BUDGET_REL] = _query_budget_results(root_path, snow, options, runner=runner)
        else:
            for rel in (
                CLI_SETUP_REL,
                CLI_SETUP_MIGRATION_REL,
                SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL,
                PACKET_AVAILABILITY_MATRIX_REL,
                CLI_PACKET_VALUE_REL,
                CLI_FORMULA_VALUE_REL,
                CLI_COST_RECONCILIATION_REL,
                CLI_SUMMARY_CARD_REL,
                CLI_QUERY_BUDGET_REL,
            ):
                artifacts[rel] = _payload(
                    source=Path(rel).stem,
                    rows=[],
                    failures=[{"code": "SNOWFLAKE_CLI_CONNECTION_REQUIRED"}],
                )
    artifacts[CLI_TEMP_FILE_HYGIENE_REL] = _temp_file_hygiene_results(options)
    artifacts[CLI_TEMP_FILE_HYGIENE_GATE_REL] = evaluate_temp_file_hygiene_gate(artifacts.get(CLI_TEMP_FILE_HYGIENE_REL, {}))
    artifacts[CLI_SETUP_MIGRATION_GATE_REL] = evaluate_setup_migration_live_gate(artifacts.get(CLI_SETUP_MIGRATION_REL, {}))
    artifacts[CLI_FORMULA_VALUE_GATE_REL] = _formula_value_gate_results(artifacts.get(CLI_FORMULA_VALUE_REL, {}))
    artifacts[CLI_COST_RECONCILIATION_GATE_REL] = _cost_reconciliation_gate_results(artifacts.get(CLI_COST_RECONCILIATION_REL, {}))
    artifacts[PACKET_AVAILABILITY_GATE_REL] = evaluate_packet_availability_gate(
        artifacts.get(PACKET_AVAILABILITY_MATRIX_REL, {})
    )
    _assign_validation_ids(artifacts)
    artifacts[CLI_MANIFEST_REL] = _manifest_from_rows(_all_rows(artifacts))
    artifacts[CLI_MANIFEST_RECONCILIATION_REL] = _manifest_reconciliation_results(artifacts, artifacts[CLI_MANIFEST_REL])
    artifacts[CLI_LAUNCH_GATE_REL] = evaluate_snowflake_cli_live_gate(artifacts, options.profile, [])
    _refresh_rehearsal_live_dependency_artifacts(root_path, options.profile)
    artifacts[CLI_PRODUCTION_REHEARSAL_REL] = build_production_deployment_rehearsal_results(
        root_path,
        artifacts,
        options,
    )
    artifacts[CLI_PRODUCTION_REHEARSAL_GATE_REL] = evaluate_production_deployment_rehearsal_gate(
        artifacts[CLI_PRODUCTION_REHEARSAL_REL]
    )
    artifacts[CLI_RELEASE_REL] = {
        "source": "snowflake_cli_release_results",
        "generated_at": _utc_now(),
        "passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_gate_passed")),
        "failure_count": int(artifacts[CLI_LAUNCH_GATE_REL].get("failure_count") or 0),
        "launch_profile": options.profile,
        "snowflake_cli_gate_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_gate_passed")),
        "snowflake_cli_live_required": bool(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_live_required")),
        "snowflake_cli_live_executed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_live_executed")),
        "snowflake_cli_live_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_live_passed")),
        "snowflake_cli_live_skipped": bool(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_live_skipped")),
        "snowflake_cli_live_waived": bool(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_live_waived")),
        "snowflake_cli_skip_reason": str(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_skip_reason") or ""),
        "snowflake_cli_token_auth_used": bool(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_token_auth_used")),
        "snowflake_cli_token_file_supplied": bool(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_token_file_supplied")),
        "snowflake_cli_token_path_leak_count": int(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_token_path_leak_count") or 0),
        "snowflake_cli_temp_sql_path_leak_count": int(artifacts[CLI_LAUNCH_GATE_REL].get("snowflake_cli_temp_sql_path_leak_count") or 0),
        "snowflake_cli_temp_file_hygiene_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("temp_file_hygiene_passed")),
        "temp_sql_file_leftover_count": int(artifacts[CLI_LAUNCH_GATE_REL].get("temp_sql_file_leftover_count") or 0),
        "connection_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("connection_passed")),
        "setup_validation_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("setup_validation_passed")),
        "setup_migration_live_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("setup_migration_live_passed")),
        "packet_availability_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("packet_availability_passed")),
        "packet_value_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("packet_value_passed")),
        "formula_value_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("formula_value_passed")),
        "cost_reconciliation_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("cost_reconciliation_passed")),
        "query_budget_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("query_budget_passed")),
        "manifest_reconciliation_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("manifest_reconciliation_passed")),
        "production_deployment_rehearsal_passed": bool(
            artifacts[CLI_PRODUCTION_REHEARSAL_GATE_REL].get("passed")
        ),
        "raw_sql_included": False,
    }
    return artifacts


def write_snowflake_cli_live_validation_artifacts(
    root: Path | str = ".",
    *,
    options: SnowflakeCliValidationOptions | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    opts = options or options_from_env()
    artifacts = run_snowflake_cli_live_validation(root_path, options=opts, runner=runner)
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


def options_from_env() -> SnowflakeCliValidationOptions:
    return SnowflakeCliValidationOptions(
        connection=os.environ.get("OVERWATCH_SNOWFLAKE_CLI_CONNECTION", "").strip(),
        profile=os.environ.get("OVERWATCH_LAUNCH_PROFILE", "internal_fixture").strip() or "internal_fixture",
        authenticator=os.environ.get("OVERWATCH_SNOWFLAKE_CLI_AUTHENTICATOR", "").strip(),
        token_file_path=os.environ.get("OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH", "").strip(),
        database=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE", "").strip(),
        schema=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA", "").strip(),
        warehouse=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE", "").strip(),
        role=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_ROLE", "").strip(),
        company=os.environ.get("OVERWATCH_COMPANY", "ALL").strip() or "ALL",
        environment=os.environ.get("OVERWATCH_ENVIRONMENT", "ALL").strip() or "ALL",
        window_days=int(os.environ.get("OVERWATCH_WINDOW_DAYS", "8") or "8"),
        credit_price=float(os.environ.get("OVERWATCH_CREDIT_PRICE", "3.68") or "3.68"),
        ai_credit_price=float(os.environ.get("OVERWATCH_AI_CREDIT_PRICE", "2.20") or "2.20"),
        run_fast_refresh=os.environ.get("OVERWATCH_RUN_FAST_REFRESH_VALIDATION") == "1",
        run_full_refresh_dry_run=os.environ.get("OVERWATCH_RUN_FULL_REFRESH_DRY_RUN") == "1",
        skip_refresh=os.environ.get("OVERWATCH_SKIP_REFRESH_VALIDATION", "1") == "1",
        query_history_enabled=os.environ.get("OVERWATCH_QUERY_PLAN_PROOF") == "1",
        query_tag_prefix=os.environ.get("OVERWATCH_QUERY_TAG_PREFIX", "OVERWATCH_VALIDATION").strip() or "OVERWATCH_VALIDATION",
        perf_run_id=os.environ.get("OVERWATCH_PERF_RUN_ID", "").strip(),
    )


def _parse_args(argv: Sequence[str] | None = None) -> SnowflakeCliValidationOptions:
    parser = argparse.ArgumentParser(description="Run sanitized local Snowflake CLI validation for OVERWATCH.")
    parser.add_argument("--connection", default=os.environ.get("OVERWATCH_SNOWFLAKE_CLI_CONNECTION", ""))
    parser.add_argument("--profile", default=os.environ.get("OVERWATCH_LAUNCH_PROFILE", "internal_fixture"))
    parser.add_argument("--authenticator", default=os.environ.get("OVERWATCH_SNOWFLAKE_CLI_AUTHENTICATOR", ""))
    parser.add_argument("--token-file-path", default=os.environ.get("OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH", ""))
    parser.add_argument("--database", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE", ""))
    parser.add_argument("--schema", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA", ""))
    parser.add_argument("--warehouse", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE", ""))
    parser.add_argument("--role", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_ROLE", ""))
    parser.add_argument("--company", default=os.environ.get("OVERWATCH_COMPANY", "ALL"))
    parser.add_argument("--environment", default=os.environ.get("OVERWATCH_ENVIRONMENT", "ALL"))
    parser.add_argument("--window-days", type=int, default=int(os.environ.get("OVERWATCH_WINDOW_DAYS", "8") or "8"))
    parser.add_argument("--credit-price", type=float, default=float(os.environ.get("OVERWATCH_CREDIT_PRICE", "3.68") or "3.68"))
    parser.add_argument("--ai-credit-price", type=float, default=float(os.environ.get("OVERWATCH_AI_CREDIT_PRICE", "2.20") or "2.20"))
    parser.add_argument("--run-fast-refresh", action="store_true")
    parser.add_argument("--run-full-refresh-dry-run", action="store_true")
    parser.add_argument("--skip-refresh", action="store_true")
    parser.add_argument("--output-dir", default=SNOWFLAKE_VALIDATION_DIR)
    args = parser.parse_args(argv)
    return SnowflakeCliValidationOptions(
        connection=args.connection,
        profile=args.profile,
        authenticator=args.authenticator,
        token_file_path=args.token_file_path,
        database=args.database,
        schema=args.schema,
        warehouse=args.warehouse,
        role=args.role,
        company=args.company,
        environment=args.environment,
        window_days=args.window_days,
        credit_price=args.credit_price,
        ai_credit_price=args.ai_credit_price,
        run_fast_refresh=args.run_fast_refresh,
        run_full_refresh_dry_run=args.run_full_refresh_dry_run,
        skip_refresh=args.skip_refresh or (not args.run_fast_refresh and not args.run_full_refresh_dry_run),
        output_dir=args.output_dir,
        query_history_enabled=os.environ.get("OVERWATCH_QUERY_PLAN_PROOF") == "1",
        query_tag_prefix=os.environ.get("OVERWATCH_QUERY_TAG_PREFIX", "OVERWATCH_VALIDATION").strip() or "OVERWATCH_VALIDATION",
        perf_run_id=os.environ.get("OVERWATCH_PERF_RUN_ID", "").strip(),
    )


def main(argv: Sequence[str] | None = None) -> None:
    options = _parse_args(argv)
    artifacts = write_snowflake_cli_live_validation_artifacts(Path.cwd(), options=options)
    gate = artifacts[CLI_LAUNCH_GATE_REL]
    print(
        "Snowflake CLI live validation "
        + ("passed" if gate.get("passed") else "failed")
        + f"; artifacts written under {SNOWFLAKE_VALIDATION_DIR}"
    )
    if not bool(gate.get("passed")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()


__all__ = [
    "CLI_CAPABILITY_REL",
    "CLI_CONNECTION_REL",
    "CLI_COST_RECONCILIATION_GATE_REL",
    "CLI_COST_RECONCILIATION_REL",
    "CLI_FORMULA_VALUE_REL",
    "CLI_FORMULA_VALUE_GATE_REL",
    "CLI_LAUNCH_GATE_REL",
    "CLI_MANIFEST_REL",
    "CLI_MANIFEST_RECONCILIATION_REL",
    "CLI_PACKET_VALUE_REL",
    "CLI_QUERY_BUDGET_REL",
    "CLI_PRODUCTION_REHEARSAL_GATE_REL",
    "CLI_PRODUCTION_REHEARSAL_REL",
    "CLI_RELEASE_REL",
    "CLI_SETUP_MIGRATION_GATE_REL",
    "CLI_SETUP_MIGRATION_REL",
    "CLI_SETUP_REL",
    "CLI_SUMMARY_CARD_REL",
    "CLI_TEMP_FILE_HYGIENE_GATE_REL",
    "CLI_TEMP_FILE_HYGIENE_REL",
    "REQUIRED_CLI_ARTIFACTS",
    "REQUIRED_QUERY_BUDGET_BOUNDARIES",
    "SnowflakeCliValidationOptions",
    "TEMP_SQL_PREFIX",
    "build_production_deployment_rehearsal_results",
    "evaluate_snowflake_cli_live_gate",
    "evaluate_production_deployment_rehearsal_gate",
    "evaluate_setup_migration_live_gate",
    "evaluate_temp_file_hygiene_gate",
    "run_snowflake_cli_live_validation",
    "sanitize_text",
    "write_snowflake_cli_live_validation_artifacts",
]
