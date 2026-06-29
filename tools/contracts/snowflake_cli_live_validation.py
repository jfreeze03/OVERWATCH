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
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from tools.contracts.formula_end_to_end_validation import REQUIRED_PACKET_FIELDS


SNOWFLAKE_VALIDATION_DIR = "artifacts/snowflake_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
RELEASE_CANDIDATE_DIR = "artifacts/release_candidate"

CLI_CAPABILITY_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_capability_results.json"
CLI_CONNECTION_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_connection_results.json"
CLI_MANIFEST_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_execution_manifest.json"
CLI_SETUP_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_setup_validation_results.json"
CLI_FORMULA_VALUE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_formula_value_results.json"
CLI_PACKET_VALUE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_packet_value_results.json"
CLI_SUMMARY_CARD_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_summary_card_value_results.json"
CLI_QUERY_BUDGET_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_query_budget_results.json"
CLI_LAUNCH_GATE_REL = f"{LAUNCH_READINESS_DIR}/snowflake_cli_live_gate_results.json"
CLI_RELEASE_REL = f"{RELEASE_CANDIDATE_DIR}/snowflake_cli_release_results.json"

REQUIRED_CLI_ARTIFACTS = {
    CLI_CAPABILITY_REL,
    CLI_CONNECTION_REL,
    CLI_MANIFEST_REL,
    CLI_SETUP_REL,
    CLI_FORMULA_VALUE_REL,
    CLI_PACKET_VALUE_REL,
    CLI_SUMMARY_CARD_REL,
    CLI_QUERY_BUDGET_REL,
    CLI_LAUNCH_GATE_REL,
    CLI_RELEASE_REL,
}

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

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class SnowflakeCliValidationOptions:
    connection: str = ""
    profile: str = "internal_fixture"
    database: str = ""
    schema: str = ""
    warehouse: str = ""
    role: str = ""
    company: str = "ALL"
    environment: str = "ALL"
    window_days: int = 8
    credit_price: float = 3.68
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
    text = re.sub(r"(?i)(https://)[A-Za-z0-9_.-]+\.snowflakecomputing\.com", r"\1[REDACTED_ACCOUNT].snowflakecomputing.com", text)
    text = re.sub(r'File "[^"]+", line \d+.*', "[STACK_FRAME_REDACTED]", text)
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
    if options.database:
        args.extend(["--database", options.database])
    if options.schema:
        args.extend(["--schema", options.schema])
    if options.warehouse:
        args.extend(["--warehouse", options.warehouse])
    if options.role:
        args.extend(["--role", options.role])
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
        "recommendation": recommendation,
    }


def _manifest_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        entry = {
            "validation_id": f"snowflake-cli-{index + 1:04d}",
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
        (CLI_PACKET_VALUE_REL, "packet_value_validation"),
        (CLI_FORMULA_VALUE_REL, "formula_value_validation"),
        (CLI_SUMMARY_CARD_REL, "summary_card_value_validation"),
        (CLI_QUERY_BUDGET_REL, "query_budget_validation"),
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
    manifest = _manifest_from_rows(row for rows in rows_by_rel.values() for row in rows)
    artifacts: dict[str, Any] = {
        rel: _payload(source=Path(rel).stem, rows=rows, skipped=True, skip_reason=reason)
        for rel, rows in rows_by_rel.items()
    }
    artifacts[CLI_MANIFEST_REL] = manifest
    gate = evaluate_snowflake_cli_live_gate(artifacts, options.profile, [])
    artifacts[CLI_LAUNCH_GATE_REL] = gate
    artifacts[CLI_RELEASE_REL] = {
        "source": "snowflake_cli_release_results",
        "generated_at": _utc_now(),
        "passed": bool(gate.get("passed")),
        "failure_count": int(gate.get("failure_count") or 0),
        "launch_profile": options.profile,
        "snowflake_cli_live_validation_passed": bool(gate.get("passed")),
        "snowflake_cli_live_validation_skipped": True,
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
    company_filter = "" if options.company.upper() == "ALL" else f"AND UPPER(COMPANY)=UPPER({_literal(options.company)})"
    env_filter = "" if options.environment.upper() == "ALL" else f"AND UPPER(ENVIRONMENT)=UPPER({_literal(options.environment)})"
    return f"""
WITH sections AS (
  SELECT column1::VARCHAR AS section_name FROM VALUES {_section_values_sql()}
),
packet AS (
  SELECT *
  FROM {command_table}
  WHERE WINDOW_DAYS = {int(options.window_days)}
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
  WHERE WINDOW_DAYS = {int(options.window_days)}
    {company_filter}
    {env_filter}
    AND COALESCE(IS_EXACT_SCOPE, TRUE)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY UPPER(SECTION_NAME)
    ORDER BY SNAPSHOT_TS DESC NULLS LAST
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


def _formula_expected_sql(options: SnowflakeCliValidationOptions) -> str:
    start_expr = f"DATEADD('day', -{int(options.window_days)}, CURRENT_DATE())"
    end_expr = "DATEADD('day', -1, CURRENT_DATE())"
    allowlist = ", ".join(_literal(value) for value in CORTEX_SERVICE_TYPES)
    return f"""
WITH account_billing AS (
  SELECT
    SUM(COALESCE(CREDITS_BILLED, CREDITS_USED, 0)) AS account_billed_credits,
    SUM(COALESCE(CREDITS_USED, 0)) AS account_used_credits
  FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
  WHERE USAGE_DATE BETWEEN {start_expr} AND {end_expr}
),
warehouse_bridge AS (
  SELECT
    SUM(COALESCE(CREDITS_USED_COMPUTE, 0) + COALESCE(CREDITS_USED_CLOUD_SERVICES, 0)) AS warehouse_credits,
    SUM(COALESCE(CREDITS_USED_COMPUTE, 0)) AS compute_credits,
    SUM(COALESCE(CREDITS_USED_CLOUD_SERVICES, 0)) AS cloud_services_credits
  FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
  WHERE START_TIME::DATE BETWEEN {start_expr} AND {end_expr}
    AND COALESCE(WAREHOUSE_ID, 0) > 0
    AND NULLIF(TRIM(WAREHOUSE_NAME), '') IS NOT NULL
),
cortex AS (
  SELECT SUM(COALESCE(CREDITS_USED, CREDITS_BILLED, 0)) AS cortex_ai_credits
  FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
  WHERE USAGE_DATE BETWEEN {start_expr} AND {end_expr}
    AND UPPER(SERVICE_TYPE) IN ({allowlist})
)
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
  'ACCOUNT_BILLED_CREDITS', a.account_billed_credits,
  'ACCOUNT_BILLED_COST_USD', a.account_billed_credits * {float(options.credit_price)},
  'ACCOUNT_USED_CREDITS', a.account_used_credits,
  'COMPUTE_CREDITS', w.compute_credits,
  'CLOUD_SERVICES_CREDITS', w.cloud_services_credits,
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
  'CORTEX_AI_COST_USD', c.cortex_ai_credits * {float(options.credit_price)}
) AS ROW_JSON
FROM account_billing a, warehouse_bridge w, cortex c
"""


def _query_history_sql(options: SnowflakeCliValidationOptions) -> str:
    prefix = options.query_tag_prefix or "OVERWATCH_VALIDATION"
    return f"""
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
  'query_count', COUNT(*),
  'bytes_scanned', SUM(COALESCE(BYTES_SCANNED, 0)),
  'max_elapsed_ms', MAX(TOTAL_ELAPSED_TIME),
  'query_tag_prefix', {_literal(prefix)}
) AS ROW_JSON
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(END_TIME_RANGE_START=>DATEADD('hour', -6, CURRENT_TIMESTAMP())))
WHERE QUERY_TAG ILIKE {_literal(prefix + '%')}
"""


def _parse_json_rows(stdout: str) -> list[dict[str, Any]]:
    text = stdout.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [row for row in parsed if isinstance(row, dict)]
        if isinstance(parsed, dict):
            data = parsed.get("data") if isinstance(parsed.get("data"), list) else parsed
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
            return [data] if isinstance(data, dict) else []
    except json.JSONDecodeError:
        pass
    objects: list[dict[str, Any]] = []
    for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, flags=re.DOTALL):
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            if "ROW_JSON" in value and isinstance(value["ROW_JSON"], dict):
                objects.append(value["ROW_JSON"])
            else:
                objects.append(value)
    return objects


def _run_snow_sql_query(
    snow: str,
    options: SnowflakeCliValidationOptions,
    query: str,
    *,
    runner: Runner,
    timeout_seconds: int = 180,
) -> tuple[list[dict[str, Any]], subprocess.CompletedProcess[str] | None, int]:
    args = [snow, "sql", *_command_scope(options), "-q", query]
    proc, elapsed = _run(args, runner=runner, timeout_seconds=timeout_seconds)
    rows = _parse_json_rows(proc.stdout if proc else "")
    return rows, proc, elapsed


def _run_snow_sql_file(
    snow: str,
    options: SnowflakeCliValidationOptions,
    filename: Path,
    *,
    runner: Runner,
    timeout_seconds: int = 300,
) -> tuple[subprocess.CompletedProcess[str] | None, int]:
    args = [snow, "sql", *_command_scope(options), "-f", str(filename)]
    return _run(args, runner=runner, timeout_seconds=timeout_seconds)


def _capability_results(
    snow: str,
    options: SnowflakeCliValidationOptions,
    *,
    runner: Runner,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for phase, args in (
        ("snowflake_cli_version", [snow, "--version"]),
        ("snowflake_cli_sql_help", [snow, "sql", "--help"]),
    ):
        proc, elapsed = _run(args, runner=runner, timeout_seconds=60)
        ok = proc is not None and proc.returncode == 0
        stdout = proc.stdout if proc else ""
        stderr = proc.stderr if proc else ""
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
    return _payload(source="snowflake_cli_capability_results", rows=rows, failures=failures)


def _connection_results(
    snow: str,
    options: SnowflakeCliValidationOptions,
    *,
    runner: Runner,
) -> dict[str, Any]:
    args = [snow, "connection", "test", "-c", options.connection]
    proc, elapsed = _run(args, runner=runner, timeout_seconds=120)
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
        rows2, proc2, elapsed2 = _run_snow_sql_query(
            snow,
            options,
            "CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEF('FAST', TRUE)",
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
        row2.update({"artifact": Path(CLI_SETUP_REL).name, "row_index": len(rows)})
        rows.append(row2)
        if refresh_status == "failed":
            failures.append({"code": "SNOWFLAKE_CLI_FAST_REFRESH_FAILED", "sanitized_error": row2["sanitized_error"]})
    if options.run_full_refresh_dry_run:
        rows3, proc3, elapsed3 = _run_snow_sql_query(
            snow,
            options,
            "CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEF('FULL', TRUE)",
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
        row3.update({"artifact": Path(CLI_SETUP_REL).name, "row_index": len(rows)})
        rows.append(row3)
        if status == "failed":
            failures.append({"code": "SNOWFLAKE_CLI_FULL_DRY_RUN_FAILED", "sanitized_error": row3["sanitized_error"]})
    extra = {"refresh_status": refresh_status, "refresh_skip_reason": refresh_reason}
    return _payload(source="snowflake_cli_setup_validation_results", rows=rows, failures=failures, extra=extra)


def _normalize_snow_row(row: Mapping[str, Any]) -> dict[str, Any]:
    if "ROW_JSON" in row and isinstance(row["ROW_JSON"], Mapping):
        return dict(row["ROW_JSON"])
    return dict(row)


def _packet_value_results(
    snow: str,
    options: SnowflakeCliValidationOptions,
    *,
    runner: Runner,
) -> dict[str, Any]:
    rows_raw, proc, elapsed = _run_snow_sql_query(snow, options, _packet_flat_sql(options), runner=runner)
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
        row.update({"artifact": Path(CLI_PACKET_VALUE_REL).name, "row_index": 0})
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


def _formula_value_results(
    snow: str,
    options: SnowflakeCliValidationOptions,
    packet_payload: Mapping[str, Any],
    *,
    runner: Runner,
) -> dict[str, Any]:
    rows_raw, proc, elapsed = _run_snow_sql_query(snow, options, _formula_expected_sql(options), runner=runner)
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
        row.update({"artifact": Path(CLI_FORMULA_VALUE_REL).name, "row_index": 0})
        return _payload(
            source="snowflake_cli_formula_value_results",
            rows=[row],
            failures=[{"code": "SNOWFLAKE_CLI_FORMULA_QUERY_FAILED", "sanitized_error": row["sanitized_error"]}],
        )
    expected = _normalize_snow_row(rows_raw[0]) if rows_raw else {}
    executive_total = _section_packet_value(packet_payload, "Executive Landing", "ACCOUNT_BILLED_COST_USD")
    cost_total = _section_packet_value(packet_payload, "Cost & Contract", "ACCOUNT_BILLED_COST_USD")
    executive_cortex = _section_packet_value(packet_payload, "Executive Landing", "CORTEX_AI_COST_USD")
    cost_cortex = _section_packet_value(packet_payload, "Cost & Contract", "CORTEX_AI_COST_USD")
    comparisons = [
        ("ACCOUNT_BILLED_COST_USD", cost_total, expected.get("ACCOUNT_BILLED_COST_USD")),
        ("CORTEX_AI_COST_USD", cost_cortex, expected.get("CORTEX_AI_COST_USD")),
        ("BILLING_BRIDGE_DELTA_CREDITS", _section_packet_value(packet_payload, "Cost & Contract", "BILLING_BRIDGE_DELTA_CREDITS"), expected.get("BILLING_BRIDGE_DELTA_CREDITS")),
        ("WAREHOUSE_CREDITS", _section_packet_value(packet_payload, "Cost & Contract", "WAREHOUSE_CREDITS"), expected.get("WAREHOUSE_CREDITS")),
    ]
    for index, (field, packet_value, live_expected) in enumerate(comparisons):
        packet_float = _as_float(packet_value)
        expected_float = _as_float(live_expected)
        tolerance = 0.05 if field.endswith("_USD") else 0.001
        passed = packet_float is not None and expected_float is not None and abs(packet_float - expected_float) <= tolerance
        row = _base_row(
            phase="formula_value_validation",
            command_kind="validation",
            options=options,
            elapsed_ms=elapsed,
            status="passed" if passed else "failed",
            row_count=1,
            sanitized_error="" if passed else "Live expected formula value differs from packet value.",
            recommendation="" if passed else "Refresh packet formulas or reconcile COST_DB-authority live formula calculations.",
        )
        row.update(
            {
                "artifact": Path(CLI_FORMULA_VALUE_REL).name,
                "row_index": index,
                "formula_field": field,
                "packet_value": packet_value,
                "live_expected_value": live_expected,
                "tolerance": tolerance,
            }
        )
        rows.append(row)
        if not passed:
            failures.append({"code": "SNOWFLAKE_CLI_FORMULA_VALUE_MISMATCH", "formula_field": field})
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
        "cost_db_formula_source": "https://github.com/jfreeze03/COST_DB/blob/main/streamlit_app.py",
    }
    return _payload(source="snowflake_cli_formula_value_results", rows=rows, failures=failures, extra=extra)


def _summary_card_results(packet_payload: Mapping[str, Any], options: SnowflakeCliValidationOptions) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, field in enumerate(("ACCOUNT_BILLED_COST_USD", "CORTEX_AI_COST_USD")):
        executive = _section_packet_value(packet_payload, "Executive Landing", field)
        cost = _section_packet_value(packet_payload, "Cost & Contract", field)
        passed = executive == cost
        row = _base_row(
            phase="summary_card_value_validation",
            command_kind="validation",
            options=options,
            status="passed" if passed else "failed",
            row_count=1,
            sanitized_error="" if passed else "Executive and Cost summary card packet values differ.",
            recommendation="" if passed else "Ensure both sections read the same flat packet field for summary cards.",
        )
        row.update(
            {
                "artifact": Path(CLI_SUMMARY_CARD_REL).name,
                "row_index": index,
                "formula_field": field,
                "executive_value": executive,
                "cost_value": cost,
            }
        )
        rows.append(row)
        if not passed:
            failures.append({"code": "SNOWFLAKE_CLI_SUMMARY_CARD_VALUE_MISMATCH", "formula_field": field})
    return _payload(source="snowflake_cli_summary_card_value_results", rows=rows, failures=failures)


def _query_budget_results(
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
    rows_raw, proc, elapsed = _run_snow_sql_query(snow, options, _query_history_sql(options), runner=runner)
    ok = proc is not None and proc.returncode == 0 and bool(rows_raw)
    row = _base_row(
        phase="query_budget_validation",
        command_kind="sql_query",
        options=options,
        elapsed_ms=elapsed,
        status="passed" if ok else "failed",
        row_count=len(rows_raw),
        sanitized_error="" if ok else sanitize_text((proc.stderr if proc else "") or (proc.stdout if proc else "")),
        recommendation="" if ok else "Grant query history access or provide a profile-aware waiver.",
    )
    row.update(
        {
            "artifact": Path(CLI_QUERY_BUDGET_REL).name,
            "row_index": 0,
            "query_history_rows": rows_raw,
            "raw_sql_included": False,
        }
    )
    failures = [] if ok else [{"code": "SNOWFLAKE_CLI_QUERY_HISTORY_PROOF_FAILED", "sanitized_error": row["sanitized_error"]}]
    return _payload(source="snowflake_cli_query_budget_results", rows=[row], failures=failures)


def _all_rows(artifacts: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel in (
        CLI_CAPABILITY_REL,
        CLI_CONNECTION_REL,
        CLI_SETUP_REL,
        CLI_PACKET_VALUE_REL,
        CLI_FORMULA_VALUE_REL,
        CLI_SUMMARY_CARD_REL,
        CLI_QUERY_BUDGET_REL,
    ):
        payload = artifacts.get(rel)
        if isinstance(payload, Mapping):
            for row in payload.get("rows", []):
                if isinstance(row, dict):
                    rows.append(row)
    return rows


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
    core_rels = (CLI_CONNECTION_REL, CLI_SETUP_REL, CLI_PACKET_VALUE_REL, CLI_FORMULA_VALUE_REL)
    skipped = all(bool((artifacts.get(rel) or {}).get("skipped")) for rel in core_rels if isinstance(artifacts.get(rel), Mapping))
    if skipped and live_required and not waived:
        failures.append(
            {
                "code": "SNOWFLAKE_CLI_LIVE_PROOF_MISSING",
                "profile": profile,
                "recommendation": "Run scripts/run_snowflake_cli_live_validation with a Snowflake CLI connection or provide a signed waiver.",
            }
        )
    for rel in core_rels + (CLI_SUMMARY_CARD_REL,):
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
    for row in _all_rows(artifacts):
        serialized = json.dumps(row, default=str)
        if bool(row.get("raw_sql_included")):
            failures.append({"code": "SNOWFLAKE_CLI_RAW_SQL_INCLUDED", "phase": row.get("phase")})
        if re.search(r"(?i)(password|token|private[_-]?key|connection[_-]?string)\s*[:=]", serialized):
            failures.append({"code": "SNOWFLAKE_CLI_SECRET_LIKE_TEXT", "phase": row.get("phase")})

    def passed_not_skipped(rel: str) -> bool:
        payload = artifacts.get(rel)
        return isinstance(payload, Mapping) and bool(payload.get("passed")) and not bool(payload.get("skipped"))

    return {
        "source": "snowflake_cli_live_gate_results",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "launch_profile": profile,
        "live_required": live_required,
        "skipped": skipped,
        "waived": waived,
        "connection_passed": passed_not_skipped(CLI_CONNECTION_REL),
        "setup_validation_passed": passed_not_skipped(CLI_SETUP_REL),
        "packet_value_passed": passed_not_skipped(CLI_PACKET_VALUE_REL),
        "formula_value_passed": passed_not_skipped(CLI_FORMULA_VALUE_REL),
        "summary_card_value_passed": passed_not_skipped(CLI_SUMMARY_CARD_REL),
        "query_budget_passed": passed_not_skipped(CLI_QUERY_BUDGET_REL),
        "raw_sql_included": False,
    }


def run_snowflake_cli_live_validation(
    root: Path | str = ".",
    *,
    options: SnowflakeCliValidationOptions,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
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
        for rel in (CLI_SETUP_REL, CLI_PACKET_VALUE_REL, CLI_FORMULA_VALUE_REL, CLI_SUMMARY_CARD_REL, CLI_QUERY_BUDGET_REL):
            artifacts[rel] = _payload(source=Path(rel).stem, rows=[], failures=[{"code": "SNOWFLAKE_CLI_NOT_AVAILABLE"}])
    else:
        artifacts[CLI_CONNECTION_REL] = _connection_results(snow, options, runner=runner)
        if bool(artifacts[CLI_CONNECTION_REL].get("passed")):
            artifacts[CLI_SETUP_REL] = _setup_validation_results(root_path, snow, options, runner=runner)
            artifacts[CLI_PACKET_VALUE_REL] = _packet_value_results(snow, options, runner=runner)
            artifacts[CLI_FORMULA_VALUE_REL] = _formula_value_results(snow, options, artifacts[CLI_PACKET_VALUE_REL], runner=runner)
            artifacts[CLI_SUMMARY_CARD_REL] = _summary_card_results(artifacts[CLI_PACKET_VALUE_REL], options)
            artifacts[CLI_QUERY_BUDGET_REL] = _query_budget_results(snow, options, runner=runner)
        else:
            for rel in (CLI_SETUP_REL, CLI_PACKET_VALUE_REL, CLI_FORMULA_VALUE_REL, CLI_SUMMARY_CARD_REL, CLI_QUERY_BUDGET_REL):
                artifacts[rel] = _payload(
                    source=Path(rel).stem,
                    rows=[],
                    failures=[{"code": "SNOWFLAKE_CLI_CONNECTION_REQUIRED"}],
                )
    artifacts[CLI_MANIFEST_REL] = _manifest_from_rows(_all_rows(artifacts))
    artifacts[CLI_LAUNCH_GATE_REL] = evaluate_snowflake_cli_live_gate(artifacts, options.profile, [])
    artifacts[CLI_RELEASE_REL] = {
        "source": "snowflake_cli_release_results",
        "generated_at": _utc_now(),
        "passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("passed")),
        "failure_count": int(artifacts[CLI_LAUNCH_GATE_REL].get("failure_count") or 0),
        "launch_profile": options.profile,
        "snowflake_cli_live_validation_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("passed")),
        "snowflake_cli_live_validation_skipped": bool(artifacts[CLI_LAUNCH_GATE_REL].get("skipped")),
        "connection_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("connection_passed")),
        "setup_validation_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("setup_validation_passed")),
        "packet_value_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("packet_value_passed")),
        "formula_value_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("formula_value_passed")),
        "query_budget_passed": bool(artifacts[CLI_LAUNCH_GATE_REL].get("query_budget_passed")),
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
        database=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE", "").strip(),
        schema=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA", "").strip(),
        warehouse=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE", "").strip(),
        role=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_ROLE", "").strip(),
        company=os.environ.get("OVERWATCH_COMPANY", "ALL").strip() or "ALL",
        environment=os.environ.get("OVERWATCH_ENVIRONMENT", "ALL").strip() or "ALL",
        window_days=int(os.environ.get("OVERWATCH_WINDOW_DAYS", "8") or "8"),
        credit_price=float(os.environ.get("OVERWATCH_CREDIT_PRICE", "3.68") or "3.68"),
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
    parser.add_argument("--database", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE", ""))
    parser.add_argument("--schema", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA", ""))
    parser.add_argument("--warehouse", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE", ""))
    parser.add_argument("--role", default=os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_ROLE", ""))
    parser.add_argument("--company", default=os.environ.get("OVERWATCH_COMPANY", "ALL"))
    parser.add_argument("--environment", default=os.environ.get("OVERWATCH_ENVIRONMENT", "ALL"))
    parser.add_argument("--window-days", type=int, default=int(os.environ.get("OVERWATCH_WINDOW_DAYS", "8") or "8"))
    parser.add_argument("--credit-price", type=float, default=float(os.environ.get("OVERWATCH_CREDIT_PRICE", "3.68") or "3.68"))
    parser.add_argument("--run-fast-refresh", action="store_true")
    parser.add_argument("--run-full-refresh-dry-run", action="store_true")
    parser.add_argument("--skip-refresh", action="store_true")
    parser.add_argument("--output-dir", default=SNOWFLAKE_VALIDATION_DIR)
    args = parser.parse_args(argv)
    return SnowflakeCliValidationOptions(
        connection=args.connection,
        profile=args.profile,
        database=args.database,
        schema=args.schema,
        warehouse=args.warehouse,
        role=args.role,
        company=args.company,
        environment=args.environment,
        window_days=args.window_days,
        credit_price=args.credit_price,
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
    "CLI_FORMULA_VALUE_REL",
    "CLI_LAUNCH_GATE_REL",
    "CLI_MANIFEST_REL",
    "CLI_PACKET_VALUE_REL",
    "CLI_QUERY_BUDGET_REL",
    "CLI_RELEASE_REL",
    "CLI_SETUP_REL",
    "CLI_SUMMARY_CARD_REL",
    "REQUIRED_CLI_ARTIFACTS",
    "SnowflakeCliValidationOptions",
    "evaluate_snowflake_cli_live_gate",
    "run_snowflake_cli_live_validation",
    "sanitize_text",
    "write_snowflake_cli_live_validation_artifacts",
]
