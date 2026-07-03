"""Snowflake object drift validation for production release candidates.

This contract turns the token-backed setup/migration live artifact into an
object-level drift gate. It does not store SQL bodies, token paths, temp paths,
or raw Snowflake errors.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from tools.contracts.production_deployment_readiness import REQUIRED_SETUP_OBJECTS
from tools.contracts.snowflake_cli_live_validation import CLI_SETUP_MIGRATION_REL


SNOWFLAKE_VALIDATION_DIR = "artifacts/snowflake_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

SNOWFLAKE_OBJECT_DRIFT_RESULTS_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_object_drift_results.json"
SNOWFLAKE_OBJECT_DRIFT_GATE_REL = f"{LAUNCH_READINESS_DIR}/snowflake_object_drift_gate_results.json"

PRODUCER = "snowflake_object_drift_validation"
EXPECTED_OBJECTS: tuple[dict[str, str], ...] = (
    {"object_name": "OVERWATCH_SCHEMA_MIGRATION", "object_type": "TABLE", "source_file": "snowflake/OVERWATCH_MART_SETUP.sql", "owner": "Setup", "purpose": "Migration ledger"},
    {"object_name": "MART_SECTION_DECISION_CURRENT", "object_type": "TABLE", "source_file": "snowflake/OVERWATCH_MART_SETUP.sql", "owner": "Decision Workspace", "purpose": "Current packet source"},
    {"object_name": "MART_SECTION_DECISION_CURRENT_FLAT", "object_type": "TABLE", "source_file": "snowflake/OVERWATCH_MART_SETUP.sql", "owner": "Decision Workspace", "purpose": "Flat packet render source"},
    {"object_name": "MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT", "object_type": "TABLE", "source_file": "snowflake/OVERWATCH_MART_SETUP.sql", "owner": "Security Monitoring", "purpose": "Credential expiration compact mart"},
    {"object_name": "USER_DISPLAY_DIMENSION_COLUMNS", "object_type": "VIEW", "source_file": "snowflake/OVERWATCH_MART_SETUP.sql", "owner": "Shared labels", "purpose": "Daily-safe user display labels"},
    {"object_name": "OVERWATCH_DECISION_SETUP_HEALTH", "object_type": "TABLE", "source_file": "snowflake/OVERWATCH_MART_SETUP.sql", "owner": "Settings/Admin Setup Health", "purpose": "Admin setup health status"},
    {"object_name": "MART_CORTEX_DAILY", "object_type": "TABLE", "source_file": "snowflake/OVERWATCH_MART_SETUP.sql", "owner": "Cost & Contract", "purpose": "Cortex token and cost facts"},
    {"object_name": "FACT_COST_DAILY", "object_type": "TABLE", "source_file": "snowflake/OVERWATCH_MART_SETUP.sql", "owner": "Cost & Contract", "purpose": "Billing cost facts"},
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


def _load_json(root: Path, rel: str) -> Mapping[str, Any]:
    try:
        payload = json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _as_int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _signature(row: Mapping[str, Any]) -> str:
    payload = {
        "producer": PRODUCER,
        "object_name": row.get("object_name"),
        "object_type": row.get("object_type"),
        "passed": row.get("passed"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _setup_object_probe(setup_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = setup_payload.get("rows")
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, Mapping) and row.get("phase") == "setup_migration_object_probe":
            return row
    return {}


def _row_passed(row: Mapping[str, Any]) -> bool:
    status = str(row.get("status") or "").strip().lower()
    return bool(row.get("passed")) or status == "passed"


def build_snowflake_object_drift_results(
    root: Path | str = ".",
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    launch_profile = profile or os.environ.get("OVERWATCH_LAUNCH_PROFILE", "internal_fixture").strip() or "internal_fixture"
    live_required = launch_profile in {"internal_live", "prod_candidate"}
    commit_sha = _git_sha(root_path)
    setup_payload = _load_json(root_path, CLI_SETUP_MIGRATION_REL)
    setup_probe = _setup_object_probe(setup_payload)
    setup_present = bool(setup_payload)
    setup_passed = bool(setup_payload.get("passed")) and _row_passed(setup_probe)
    missing_required_count = _as_int(setup_probe.get("missing_required_object_count"))
    all_required_present = setup_passed and missing_required_count == 0
    allowed_names = {str(row.get("object_name") or "").upper() for row in EXPECTED_OBJECTS}
    allowed_names.update(name.upper() for name in REQUIRED_SETUP_OBJECTS)

    rows: list[dict[str, Any]] = []
    for expected in EXPECTED_OBJECTS:
        name = expected["object_name"].upper()
        skipped = not live_required and not all_required_present
        live_present = all_required_present if name in allowed_names and not skipped else False
        passed = True if skipped else live_present
        failure_reason = ""
        if not passed:
            if not setup_present:
                failure_reason = "Setup/migration live artifact is missing."
            elif not setup_passed:
                failure_reason = "Setup/migration live object probe failed."
            else:
                failure_reason = "Required Snowflake object is missing or drifted."
        row = {
            "producer": PRODUCER,
            "producer_signature": "",
            "provenance_origin": "producer",
            "generated_at": _utc_now(),
            "commit_sha": commit_sha,
            "source": "snowflake_object_drift_validation",
            "runtime_source": "setup_migration_live_object_probe",
            "launch_profile": launch_profile,
            "section": "Production Deployment",
            "workflow": "Object drift validation",
            "object_name": name,
            "object_type": expected["object_type"],
            "expected_source_file": expected["source_file"],
            "expected_present": True,
            "live_present": live_present,
            "column_check_required": False,
            "missing_columns": [],
            "extra_columns_allowed": True,
            "owner": expected["owner"],
            "purpose": expected["purpose"],
            "launch_required": True,
            "skipped": skipped,
            "passed": passed,
            "failure_reason": failure_reason,
            "raw_sql_included": False,
        }
        row["producer_signature"] = _signature(row)
        rows.append(row)

    failures = [row for row in rows if not bool(row.get("passed"))]
    if live_required and not setup_present:
        failures.append(
            {
                "code": "SNOWFLAKE_OBJECT_DRIFT_LIVE_ARTIFACT_MISSING",
                "failure_reason": "Snowflake object drift requires setup/migration live proof for this profile.",
            }
        )
    return {
        "source": "snowflake_object_drift_results",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": commit_sha,
        "launch_profile": launch_profile,
        "live_required": live_required,
        "skipped": not live_required and not all_required_present,
        "passed": not failures,
        "failure_count": len(failures),
        "object_count": len(rows),
        "missing_required_object_count": sum(1 for row in rows if not bool(row.get("live_present")) and live_required),
        "setup_migration_artifact_path": CLI_SETUP_MIGRATION_REL,
        "setup_migration_row_id": str(setup_probe.get("validation_id") or setup_probe.get("phase") or ""),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_snowflake_object_drift_gate(payload: object) -> dict[str, Any]:
    results = payload if isinstance(payload, Mapping) else {}
    failures = list(results.get("failures") or [])
    if not results:
        failures = [{"code": "SNOWFLAKE_OBJECT_DRIFT_RESULTS_MISSING"}]
    elif not bool(results.get("passed")) and not failures:
        failures = [{"code": "SNOWFLAKE_OBJECT_DRIFT_FAILED"}]
    return {
        "source": "snowflake_object_drift_gate_results",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "passed": not failures and bool(results.get("passed")),
        "object_drift_passed": not failures and bool(results.get("passed")),
        "failure_count": len(failures),
        "live_required": bool(results.get("live_required")),
        "skipped": bool(results.get("skipped")),
        "object_count": _as_int(results.get("object_count")),
        "missing_required_object_count": _as_int(results.get("missing_required_object_count")),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_snowflake_object_drift_validation_artifacts(
    root: Path | str = ".",
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_snowflake_object_drift_results(root_path, profile=profile)
    gate = evaluate_snowflake_object_drift_gate(results)
    artifacts = {
        SNOWFLAKE_OBJECT_DRIFT_RESULTS_REL: results,
        SNOWFLAKE_OBJECT_DRIFT_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        path = root_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifacts


if __name__ == "__main__":
    written = write_snowflake_object_drift_validation_artifacts(Path("."))
    gate = written[SNOWFLAKE_OBJECT_DRIFT_GATE_REL]
    print(json.dumps(gate, indent=2, sort_keys=True))
    raise SystemExit(0 if gate.get("passed") else 1)


__all__ = [
    "SNOWFLAKE_OBJECT_DRIFT_GATE_REL",
    "SNOWFLAKE_OBJECT_DRIFT_RESULTS_REL",
    "build_snowflake_object_drift_results",
    "evaluate_snowflake_object_drift_gate",
    "write_snowflake_object_drift_validation_artifacts",
]
