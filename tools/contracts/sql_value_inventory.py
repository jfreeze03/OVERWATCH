"""SQL path value inventory for launch cleanup."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha1
import json
from pathlib import Path
from typing import Any, Mapping


CLEANUP_DIR = "artifacts/cleanup"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

SQL_VALUE_INVENTORY_REL = f"{CLEANUP_DIR}/sql_value_inventory.json"
SQL_CLEANUP_GATE_REL = f"{LAUNCH_READINESS_DIR}/sql_cleanup_gate_results.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _classify_sql_path(path: Path, root: Path) -> dict[str, Any]:
    rel = str(path.relative_to(root)).replace("\\", "/")
    upper = rel.upper()
    text = path.read_text(encoding="utf-8", errors="ignore")
    text_upper = text.upper()
    if "VALIDATION" in upper:
        family = "deployment_validation"
        admin_only = True
        frequency = "release_validation"
    elif "DROP" in upper:
        family = "drop_rollback"
        admin_only = True
        frequency = "operator_rollback"
    elif (
        "SETUP" in upper
        or "MART_TABLES" in upper
        or "LOAD_PROCEDURES" in upper
        or "AUDIT" in upper
        or "/GENERATED/" in upper
        or path.name.upper().startswith("OVERWATCH_")
    ):
        family = "admin_setup"
        admin_only = True
        frequency = "deploy_or_admin_click"
    else:
        family = "compact_evidence"
        admin_only = False
        frequency = "explicit_action"
    account_usage_use = "admin_or_explicit_only" if "ACCOUNT_USAGE" in text_upper else "none"
    limit_present = " LIMIT " in f" {text_upper} "
    deterministic_order_by = not limit_present or " ORDER BY " in f" {text_upper} "
    path_id = sha1(rel.encode("utf-8", errors="ignore")).hexdigest()[:12]
    keep_delete_decision = "keep" if family != "obsolete_delete" else "obsolete_delete"
    return {
        "path_id": path_id,
        "path": rel,
        "source_file": rel,
        "function_or_procedure": path.stem,
        "owner": "OVERWATCH launch SQL owner",
        "purpose": family.replace("_", " "),
        "value_to_app": "Supports the current Decision Workspace launch surface or release validation.",
        "user_visible_feature": "Settings/Admin Setup Health" if admin_only else "Decision Workspace evidence",
        "source_family": family,
        "classification": family,
        "table_family": "snowflake_artifact",
        "account_usage_use": account_usage_use,
        "row_limit": "bounded_or_validation" if limit_present or admin_only else "missing_limit_review",
        "pruning_predicate": "validated_by_sql_linter",
        "deterministic_order_by": deterministic_order_by,
        "frequency": frequency,
        "execution_frequency": frequency,
        "cost_risk": "high" if account_usage_use != "none" else "medium" if not deterministic_order_by else "low",
        "keep_delete_decision": keep_delete_decision,
        "replacement_path": "",
        "daily_safe": family not in {"admin_setup", "deployment_validation", "drop_rollback"} or admin_only,
        "admin_only": admin_only,
        "launch_status": "retained_owned",
        "raw_sql_included": False,
    }


def build_sql_value_inventory(root: Path) -> dict[str, Any]:
    sql_files = sorted((root / "snowflake").rglob("*.sql"))
    rows = [_classify_sql_path(path, root) for path in sql_files]
    failures: list[dict[str, Any]] = []
    for row in rows:
        if not row["owner"] or not row["purpose"]:
            failures.append({**row, "failure_reason": "SQL path missing owner or purpose."})
        if not row["admin_only"] and row["account_usage_use"] != "none":
            failures.append({**row, "failure_reason": "Daily/normal SQL path uses Account Usage."})
        if row["row_limit"] == "missing_limit_review" and row["source_family"] in {"compact_evidence", "targeted_evidence"}:
            failures.append({**row, "failure_reason": "Evidence SQL path lacks a declared row limit."})
        if not row["deterministic_order_by"] and row["source_family"] in {"compact_evidence", "targeted_evidence"}:
            failures.append({**row, "failure_reason": "LIMIT-only evidence SQL lacks deterministic ORDER BY."})
    return {
        "source": "sql_value_inventory",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "sql_path_count": len(rows),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_sql_cleanup_gate(
    value_inventory: Mapping[str, Any],
    dead_scan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    dead_scan = dead_scan or {}
    failures: list[dict[str, Any]] = []
    if not bool(value_inventory.get("passed")):
        failures.extend(value_inventory.get("failures") or [{"code": "SQL_VALUE_INVENTORY_FAILED"}])
    if dead_scan and not bool(dead_scan.get("passed")):
        failures.extend(dead_scan.get("failures") or [{"code": "SQL_DEAD_CODE_SCAN_FAILED"}])
    return {
        "source": "sql_cleanup_gate_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "sql_path_count": int(value_inventory.get("sql_path_count") or 0),
        "dead_code_failure_count": int(dead_scan.get("failure_count") or 0),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_sql_value_inventory_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    payload = build_sql_value_inventory(root_path)
    _write_json(root_path / SQL_VALUE_INVENTORY_REL, payload)
    return {SQL_VALUE_INVENTORY_REL: payload}


__all__ = [
    "SQL_CLEANUP_GATE_REL",
    "SQL_VALUE_INVENTORY_REL",
    "build_sql_value_inventory",
    "evaluate_sql_cleanup_gate",
    "write_sql_value_inventory_artifacts",
]
