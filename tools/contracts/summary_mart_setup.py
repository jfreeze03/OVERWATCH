"""Validate the COCO summary mart SQL foundation."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


SNOWFLAKE_DIR = "snowflake"
FULL_APP_DIR = "artifacts/full_app_validation"
SNOWFLAKE_VALIDATION_DIR = "artifacts/snowflake_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

SUMMARY_MART_SQL_REL = f"{SNOWFLAKE_DIR}/mart_setup/09_summary_marts.sql"
SUMMARY_MART_SETUP_RESULTS_REL = f"{SNOWFLAKE_VALIDATION_DIR}/summary_mart_setup_results.json"
SUMMARY_MART_SETUP_FULL_APP_REL = f"{FULL_APP_DIR}/summary_mart_setup_results.json"
SUMMARY_MART_SETUP_GATE_REL = f"{LAUNCH_READINESS_DIR}/summary_mart_setup_gate_results.json"

PRODUCER = "summary_mart_setup"

EXPECTED_SUMMARY_MARTS: tuple[dict[str, Any], ...] = (
    {
        "object_name": "OVERWATCH_QUERY_DAILY_SUMMARY",
        "view_name": "V_QUERY_DAILY_SUMMARY",
        "owner": "Workload Operations",
        "source_family": "query_history",
        "required_columns": ("COMPANY", "ENVIRONMENT", "WINDOW_START_DATE", "WINDOW_END_DATE", "QUERY_COUNT", "FAILED_QUERY_COUNT"),
    },
    {
        "object_name": "OVERWATCH_WAREHOUSE_DAILY_CREDITS",
        "view_name": "V_WAREHOUSE_DAILY_CREDITS",
        "owner": "Cost & Contract",
        "source_family": "warehouse_metering",
        "required_columns": ("COMPANY", "ENVIRONMENT", "USAGE_DATE", "WAREHOUSE_NAME", "CREDITS_USED", "COST_USD"),
    },
    {
        "object_name": "OVERWATCH_CORTEX_DAILY_USAGE",
        "view_name": "V_CORTEX_DAILY_USAGE",
        "owner": "Cost & Contract",
        "source_family": "cortex_usage",
        "required_columns": ("COMPANY", "ENVIRONMENT", "USAGE_DATE", "USER_NAME", "USER_CHART_LABEL", "TOTAL_TOKENS"),
    },
    {
        "object_name": "OVERWATCH_USER_DISPLAY_DIM",
        "view_name": "V_USER_DISPLAY_DIM",
        "owner": "Shared User Display",
        "source_family": "user_display",
        "required_columns": ("USER_NAME", "USER_DISPLAY_NAME", "USER_CHART_LABEL", "USER_ADMIN_LABEL"),
    },
    {
        "object_name": "OVERWATCH_LOGIN_SECURITY_DAILY",
        "view_name": "V_LOGIN_SECURITY_DAILY",
        "owner": "Security Monitoring",
        "source_family": "login_security",
        "required_columns": ("COMPANY", "ENVIRONMENT", "EVENT_DATE", "FAILED_LOGIN_COUNT", "AFFECTED_USER_COUNT"),
    },
    {
        "object_name": "OVERWATCH_TASK_STATUS_DAILY",
        "view_name": "V_TASK_STATUS_DAILY",
        "owner": "DBA Control Room",
        "source_family": "task_status",
        "required_columns": ("COMPANY", "ENVIRONMENT", "EVENT_DATE", "FAILED_TASK_COUNT", "SLA_BREACH_COUNT"),
    },
    {
        "object_name": "OVERWATCH_SECURITY_POSTURE_DAILY",
        "view_name": "V_SECURITY_POSTURE_DAILY",
        "owner": "Security Monitoring",
        "source_family": "security_posture",
        "required_columns": ("COMPANY", "ENVIRONMENT", "EVENT_DATE", "CRITICAL_FINDING_COUNT", "HIGH_FINDING_COUNT"),
    },
    {
        "object_name": "OVERWATCH_EXECUTIVE_PACKET_CURRENT",
        "view_name": "V_EXECUTIVE_PACKET_CURRENT",
        "owner": "Executive Landing",
        "source_family": "decision_packet",
        "required_columns": ("COMPANY", "ENVIRONMENT", "SECTION", "WINDOW_DAYS", "SUMMARY_JSON", "UPDATED_AT"),
    },
)

REQUIRED_SOURCE_FAMILIES = (
    "query_history",
    "warehouse_metering",
    "cortex_usage",
    "user_display",
    "login_security",
    "task_status",
    "security_posture",
    "decision_packet",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_commit(root: Path) -> str:
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


def _file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _object_block(sql: str, object_name: str) -> str:
    pattern = re.compile(
        rf"CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+IF\s+NOT\s+EXISTS\s+{re.escape(object_name)}\s*\((.*?)\);",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(sql)
    return match.group(1) if match else ""


def _view_block(sql: str, view_name: str) -> str:
    pattern = re.compile(
        rf"CREATE\s+OR\s+REPLACE\s+SECURE\s+VIEW\s+{re.escape(view_name)}\b(.*?);",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(sql)
    return match.group(1) if match else ""


def _source_family_present(sql: str, source_family: str) -> bool:
    return (
        re.search(
            rf"\bSOURCE_FAMILY\b[\s\S]{{0,80}}'{re.escape(source_family)}'",
            sql,
            flags=re.IGNORECASE,
        )
        is not None
    )


def build_summary_mart_setup_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    sql_path = root_path / SUMMARY_MART_SQL_REL
    sql = sql_path.read_text(encoding="utf-8") if sql_path.exists() else ""
    upper = sql.upper()
    commit_sha = _git_commit(root_path)
    generated_at = _now()
    producer_signature = "summary_mart_setup::row_v1"
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    if not sql_path.exists():
        failures.append({"failure_reason": f"missing {SUMMARY_MART_SQL_REL}"})

    for spec in EXPECTED_SUMMARY_MARTS:
        object_name = str(spec["object_name"])
        view_name = str(spec["view_name"])
        block = _object_block(sql, object_name)
        view_block = _view_block(sql, view_name)
        required_columns = tuple(str(col) for col in spec["required_columns"])
        missing_columns = [
            column
            for column in required_columns
            if not re.search(rf"\b{re.escape(column)}\b", block, flags=re.IGNORECASE)
        ]
        source_family = str(spec["source_family"])
        reasons: list[str] = []
        if not block:
            reasons.append("object DDL missing")
        if not view_block:
            reasons.append("app-facing secure view missing")
        elif object_name.upper() not in view_block.upper():
            reasons.append("app-facing secure view does not select from compact mart")
        if missing_columns:
            reasons.append("missing columns: " + ", ".join(missing_columns))
        if not _source_family_present(sql, source_family):
            reasons.append("source family marker missing")
        if "SELECT *" in upper:
            reasons.append("SELECT * is forbidden in summary mart setup")
        row = {
            "row_id": f"summary_mart::{object_name}",
            "producer": PRODUCER,
            "producer_signature": producer_signature,
            "provenance_origin": "producer",
            "generated_at": generated_at,
            "commit_sha": commit_sha,
            "object_name": object_name,
            "app_facing_view": view_name,
            "object_type": "TABLE",
            "owner": str(spec["owner"]),
            "purpose": "Task-built compact summary surface for section summaries and explicit evidence launch proof.",
            "source_family": source_family,
            "daily_safe": True,
            "admin_only": False,
            "refresh_boundary": "refresh_fast|refresh_full",
            "first_paint_source_allowed": False,
            "section_summary_autoload_allowed": True,
            "app_consumes_secure_view": bool(view_block),
            "required_columns": list(required_columns),
            "missing_columns": missing_columns,
            "sql_file": SUMMARY_MART_SQL_REL,
            "sql_file_sha256": _file_sha256(sql_path),
            "raw_sql_included": False,
            "passed": not reasons,
            "failure_reason": "; ".join(reasons),
        }
        rows.append(row)
        if reasons:
            failures.append(
                {
                    "row_id": row["row_id"],
                    "object_name": object_name,
                    "app_facing_view": view_name,
                    "failure_reason": row["failure_reason"],
                }
            )

    missing_source_families = [
        family
        for family in REQUIRED_SOURCE_FAMILIES
        if not _source_family_present(sql, family)
    ]
    if missing_source_families:
        failures.append(
            {
                "failure_reason": "missing source family markers: " + ", ".join(missing_source_families),
            }
        )

    select_star_count = len(re.findall(r"\bSELECT\s+\*", upper))
    if select_star_count:
        failures.append({"failure_reason": "summary mart setup contains SELECT *", "count": select_star_count})

    return {
        "source": "summary_mart_setup_results",
        "producer": PRODUCER,
        "producer_signature": "summary_mart_setup::v1",
        "provenance_origin": "producer",
        "generated_at": generated_at,
        "commit_sha": commit_sha,
        "setup_sql_path": SUMMARY_MART_SQL_REL,
        "setup_sql_sha256": _file_sha256(sql_path),
        "passed": not failures,
        "failure_count": len(failures),
        "summary_mart_count": len(rows),
        "required_source_family_count": len(REQUIRED_SOURCE_FAMILIES),
        "missing_source_family_count": len(missing_source_families),
        "select_star_count": select_star_count,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_summary_mart_setup_gate(results: Mapping[str, Any]) -> dict[str, Any]:
    failures = [
        dict(row)
        for row in results.get("failures", [])
        if isinstance(row, Mapping)
    ]
    if bool(results.get("raw_sql_included")):
        failures.append({"failure_reason": "raw_sql_included=true"})
    proof_rows = [
        {
            "row_id": str(row.get("row_id") or ""),
            "object_name": str(row.get("object_name") or ""),
            "app_facing_view": str(row.get("app_facing_view") or ""),
            "object_type": str(row.get("object_type") or "TABLE"),
            "owner": str(row.get("owner") or ""),
            "source_family": str(row.get("source_family") or ""),
            "daily_safe": bool(row.get("daily_safe")),
            "section_summary_autoload_allowed": bool(row.get("section_summary_autoload_allowed")),
            "app_consumes_secure_view": bool(row.get("app_consumes_secure_view")),
            "sql_file": str(row.get("sql_file") or ""),
            "producer": PRODUCER,
            "producer_signature": "summary_mart_setup::row_v1",
            "commit_sha": str(results.get("commit_sha") or ""),
            "raw_sql_included": False,
            "passed": bool(row.get("passed")),
        }
        for row in results.get("rows", [])
        if isinstance(row, Mapping)
    ]
    return {
        "source": "summary_mart_setup_gate_results",
        "gate": "summary_mart_setup",
        "producer": PRODUCER,
        "producer_signature": "summary_mart_setup_gate::v1",
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": str(results.get("commit_sha") or ""),
        "passed": not failures,
        "failure_count": len(failures),
        "summary_mart_count": int(results.get("summary_mart_count") or 0),
        "missing_source_family_count": int(results.get("missing_source_family_count") or 0),
        "select_star_count": int(results.get("select_star_count") or 0),
        "proof_rows": proof_rows,
        "proof_row_count": len(proof_rows),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_summary_mart_setup_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_summary_mart_setup_results(root_path)
    gate = evaluate_summary_mart_setup_gate(results)
    _write_json(root_path / SUMMARY_MART_SETUP_RESULTS_REL, results)
    _write_json(root_path / SUMMARY_MART_SETUP_FULL_APP_REL, results)
    _write_json(root_path / SUMMARY_MART_SETUP_GATE_REL, gate)
    return {
        SUMMARY_MART_SETUP_RESULTS_REL: results,
        SUMMARY_MART_SETUP_FULL_APP_REL: results,
        SUMMARY_MART_SETUP_GATE_REL: gate,
    }


def main() -> int:
    artifacts = write_summary_mart_setup_artifacts(Path("."))
    gate = artifacts[SUMMARY_MART_SETUP_GATE_REL]
    print(json.dumps(gate, indent=2, sort_keys=True))
    return 0 if gate.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXPECTED_SUMMARY_MARTS",
    "SUMMARY_MART_SETUP_FULL_APP_REL",
    "SUMMARY_MART_SETUP_GATE_REL",
    "SUMMARY_MART_SETUP_RESULTS_REL",
    "SUMMARY_MART_SQL_REL",
    "build_summary_mart_setup_results",
    "evaluate_summary_mart_setup_gate",
    "write_summary_mart_setup_artifacts",
]
