"""Rollback and drop safety proof for production release candidates.

The rollback gate validates the presence and scope of the reviewed drop script
and recovery runbook. It records object counts and safe relative paths, not SQL
bodies. The goal is to prove that rollback is intentional, scoped, and
documented before a release candidate can advertise deployment readiness.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

ROLLBACK_READINESS_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/rollback_readiness_results.json"
ROLLBACK_READINESS_GATE_REL = f"{LAUNCH_READINESS_DIR}/rollback_readiness_gate_results.json"

PRODUCER = "rollback_readiness"
DROP_SQL_REL = "snowflake/OVERWATCH_MART_DROP.sql"
ROLLBACK_RUNBOOK_REL = "docs/OVERWATCH_RECOVERY_RUNBOOK.md"
DESTRUCTIVE_MODE_MARKER = "OVERWATCH_DESTRUCTIVE_MODE=TRUE"
PROTECTED_HISTORY_MARKERS = ("AUDIT", "ACTION", "ALERT_REMEDIATION", "ALERT_ACK")


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


def _strip_line_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _sha256_file(root: Path, rel: str) -> str:
    path = root / rel
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _drop_targets(sql: str) -> list[dict[str, str]]:
    uncommented = _strip_line_comments(sql)
    pattern = re.compile(
        r"\bDROP\s+(?P<object_type>TABLE|VIEW|TASK|PROCEDURE|FUNCTION)\s+IF\s+EXISTS\s+(?P<object_name>[A-Z0-9_.$()]+)",
        flags=re.IGNORECASE,
    )
    targets: list[dict[str, str]] = []
    for match in pattern.finditer(uncommented):
        object_type = match.group("object_type").upper()
        object_name = match.group("object_name").upper().rstrip(";")
        targets.append({"object_type": object_type, "object_name": object_name})
    return targets


def _broad_drop_count(sql: str) -> int:
    uncommented = _strip_line_comments(sql)
    return len(
        re.findall(
            r"\bDROP\s+(DATABASE|SCHEMA|WAREHOUSE|ROLE|RESOURCE\s+MONITOR)\b",
            uncommented,
            flags=re.IGNORECASE,
        )
    )


def _broad_drop_type_counts(sql: str) -> dict[str, int]:
    uncommented = _strip_line_comments(sql)
    specs = {
        "database_drop_count": r"\bDROP\s+DATABASE\b",
        "schema_drop_count": r"\bDROP\s+SCHEMA\b",
        "warehouse_drop_count": r"\bDROP\s+WAREHOUSE\b",
        "resource_monitor_drop_count": r"\bDROP\s+RESOURCE\s+MONITOR\b",
        "role_drop_count": r"\bDROP\s+ROLE\b",
    }
    return {key: len(re.findall(pattern, uncommented, flags=re.IGNORECASE)) for key, pattern in specs.items()}


def _producer_signature(row: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {
            "producer": PRODUCER,
            "check": row.get("check"),
            "passed": row.get("passed"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row(
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
        "source": "rollback_readiness",
        "runtime_source": "sanitized_drop_inventory",
        "section": "Production Deployment",
        "workflow": "Rollback readiness",
        "check": check,
        "passed": passed,
        "failure_reason": "" if passed else failure_reason,
        "raw_sql_included": False,
    }
    if details:
        row.update(details)
    row["producer_signature"] = _producer_signature(row)
    return row


def build_rollback_readiness_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = _git_sha(root_path)
    drop_sql = _read_text(root_path, DROP_SQL_REL)
    runbook = _read_text(root_path, ROLLBACK_RUNBOOK_REL)
    targets = _drop_targets(drop_sql)
    broad_drop_count = _broad_drop_count(drop_sql)
    protected_targets = [
        target
        for target in targets
        if any(marker in target["object_name"] for marker in PROTECTED_HISTORY_MARKERS)
    ]
    permanent_audit_targets = [
        target
        for target in targets
        if any(marker in target["object_name"] for marker in ("AUDIT", "HISTORY", "REMEDIATION", "ACK"))
    ]
    destructive_marker_present = DESTRUCTIVE_MODE_MARKER in drop_sql
    scoped_targets = [
        target
        for target in targets
        if "." not in target["object_name"] or target["object_name"].startswith("DBA_MAINT_DB.OVERWATCH.")
    ]
    disallowed_targets = [target for target in targets if target not in scoped_targets]
    broad_counts = _broad_drop_type_counts(drop_sql)
    runbook_upper = runbook.upper()

    rows = [
        _row(
            check="drop_sql_exists",
            passed=bool(drop_sql),
            failure_reason=f"Rollback/drop SQL is missing: {DROP_SQL_REL}",
            details={"drop_sql_path": DROP_SQL_REL, "drop_sql_sha256": _sha256_file(root_path, DROP_SQL_REL)},
            commit_sha=commit_sha,
        ),
        _row(
            check="drop_targets_inventory_present",
            passed=bool(targets),
            failure_reason="Drop SQL does not inventory any OVERWATCH object targets.",
            details={
                "drop_target_count": len(targets),
                "allowed_drop_target_count": len(scoped_targets),
                "disallowed_drop_target_count": len(disallowed_targets),
            },
            commit_sha=commit_sha,
        ),
        _row(
            check="drop_scope_overwatch_owned",
            passed=bool(targets) and len(scoped_targets) == len(targets) and broad_drop_count == 0,
            failure_reason="Drop SQL includes unscoped or container-level drops.",
            details={
                "scoped_target_count": len(scoped_targets),
                "allowed_drop_target_count": len(scoped_targets),
                "disallowed_drop_target_count": len(disallowed_targets),
                "broad_drop_count": broad_drop_count,
                **broad_counts,
            },
            commit_sha=commit_sha,
        ),
        _row(
            check="destructive_mode_required",
            passed=destructive_marker_present,
            failure_reason="Drop script is missing the explicit destructive-mode marker.",
            details={"destructive_mode_required": destructive_marker_present},
            commit_sha=commit_sha,
        ),
        _row(
            check="protected_history_requires_destructive_mode",
            passed=not protected_targets or destructive_marker_present,
            failure_reason="Audit/action-history drops are present without destructive-mode protection.",
            details={
                "protected_history_target_count": len(protected_targets),
                "protected_history_drop_count": len(protected_targets),
                "permanent_audit_table_drop_count": len(permanent_audit_targets),
            },
            commit_sha=commit_sha,
        ),
        _row(
            check="rollback_runbook_exists",
            passed=bool(runbook),
            failure_reason=f"Rollback runbook is missing: {ROLLBACK_RUNBOOK_REL}",
            details={"rollback_runbook_path": ROLLBACK_RUNBOOK_REL},
            commit_sha=commit_sha,
        ),
        _row(
            check="setup_rerun_idempotency_documented",
            passed="IDEMPOTENT" in runbook_upper and "OVERWATCH_SCHEMA_MIGRATION" in runbook_upper,
            failure_reason="Rollback runbook does not document setup rerun idempotency and migration ledger behavior.",
            details={"migration_ledger_documented": "OVERWATCH_SCHEMA_MIGRATION" in runbook_upper},
            commit_sha=commit_sha,
        ),
    ]

    failures = [row for row in rows if not bool(row.get("passed"))]
    return {
        "source": "rollback_readiness_results",
        "producer": PRODUCER,
        "provenance_origin": "producer",
        "generated_at": _utc_now(),
        "commit_sha": commit_sha,
        "passed": not failures,
        "rollback_ready": not failures,
        "failure_count": len(failures),
        "drop_sql_path": DROP_SQL_REL,
        "drop_sql_sha256": _sha256_file(root_path, DROP_SQL_REL),
        "rollback_path": ROLLBACK_RUNBOOK_REL,
        "drop_target_count": len(targets),
        "allowed_drop_target_count": len(scoped_targets),
        "disallowed_drop_target_count": len(disallowed_targets),
        "protected_history_target_count": len(protected_targets),
        "protected_history_drop_count": len(protected_targets),
        "permanent_audit_table_drop_count": len(permanent_audit_targets),
        "broad_drop_count": broad_drop_count,
        **broad_counts,
        "destructive_mode_required": destructive_marker_present,
        "destructive_mode_marker_present": destructive_marker_present,
        "rollback_runbook_present": bool(runbook),
        "setup_rerun_documented": "IDEMPOTENT" in runbook_upper,
        "migration_ledger_rerun_documented": "OVERWATCH_SCHEMA_MIGRATION" in runbook_upper,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_rollback_readiness_gate(payload: object) -> dict[str, Any]:
    results = payload if isinstance(payload, Mapping) else {}
    failures = list(results.get("failures") or [])
    if not results:
        failures = [{"check": "rollback_readiness_missing", "failure_reason": "Rollback readiness artifact is missing."}]
    elif not bool(results.get("passed")) and not failures:
        failures = [{"check": "rollback_readiness_failed", "failure_reason": "Rollback readiness failed."}]
    return {
        "source": "rollback_readiness_gate_results",
        "producer": PRODUCER,
        "generated_at": _utc_now(),
        "passed": not failures and bool(results.get("passed")),
        "rollback_ready": not failures and bool(results.get("rollback_ready", results.get("passed"))),
        "failure_count": len(failures),
        "drop_target_count": int(results.get("drop_target_count") or 0),
        "allowed_drop_target_count": int(results.get("allowed_drop_target_count") or 0),
        "disallowed_drop_target_count": int(results.get("disallowed_drop_target_count") or 0),
        "protected_history_target_count": int(results.get("protected_history_target_count") or 0),
        "protected_history_drop_count": int(results.get("protected_history_drop_count") or 0),
        "permanent_audit_table_drop_count": int(results.get("permanent_audit_table_drop_count") or 0),
        "broad_drop_count": int(results.get("broad_drop_count") or 0),
        "database_drop_count": int(results.get("database_drop_count") or 0),
        "schema_drop_count": int(results.get("schema_drop_count") or 0),
        "warehouse_drop_count": int(results.get("warehouse_drop_count") or 0),
        "resource_monitor_drop_count": int(results.get("resource_monitor_drop_count") or 0),
        "role_drop_count": int(results.get("role_drop_count") or 0),
        "destructive_mode_required": bool(results.get("destructive_mode_required")),
        "destructive_mode_marker_present": bool(results.get("destructive_mode_marker_present")),
        "rollback_runbook_present": bool(results.get("rollback_runbook_present")),
        "setup_rerun_documented": bool(results.get("setup_rerun_documented")),
        "migration_ledger_rerun_documented": bool(results.get("migration_ledger_rerun_documented")),
        "rollback_path": str(results.get("rollback_path") or ""),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_rollback_readiness_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_rollback_readiness_results(root_path)
    gate = evaluate_rollback_readiness_gate(results)
    artifacts = {
        ROLLBACK_READINESS_RESULTS_REL: results,
        ROLLBACK_READINESS_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        path = root_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifacts


if __name__ == "__main__":
    written = write_rollback_readiness_artifacts(Path("."))
    gate = written[ROLLBACK_READINESS_GATE_REL]
    print(json.dumps(gate, indent=2, sort_keys=True))
    raise SystemExit(0 if gate.get("passed") else 1)


__all__ = [
    "ROLLBACK_READINESS_GATE_REL",
    "ROLLBACK_READINESS_RESULTS_REL",
    "build_rollback_readiness_results",
    "evaluate_rollback_readiness_gate",
    "write_rollback_readiness_artifacts",
]
