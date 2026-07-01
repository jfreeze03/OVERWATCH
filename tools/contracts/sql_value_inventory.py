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


def _supplemental_overwatch_rows(root: Path) -> list[dict[str, Any]]:
    setup = root / "snowflake" / "mart_setup" / "05_load_procedures.sql"
    validation = root / "snowflake" / "OVERWATCH_MART_VALIDATION.sql"
    if not setup.exists():
        return []
    setup_text = setup.read_text(encoding="utf-8", errors="ignore").upper()
    validation_text = validation.read_text(encoding="utf-8", errors="ignore").upper() if validation.exists() else ""
    rows: list[dict[str, Any]] = []

    def add(
        path_id: str,
        *,
        purpose: str,
        user_visible_feature: str,
        source_family: str,
        account_usage_use: str,
        admin_only: bool,
        daily_safe: bool,
        value_to_app: str,
        row_limit: str = "bounded_by_refresh_window",
        pruning_predicate: str = "company/window/expiration_date predicates",
    ) -> None:
        rows.append(
            {
                "path_id": path_id,
                "path": "snowflake/mart_setup/05_load_procedures.sql",
                "source_file": "snowflake/mart_setup/05_load_procedures.sql",
                "function_or_procedure": path_id,
                "owner": "Security Monitoring",
                "purpose": purpose,
                "value_to_app": value_to_app,
                "user_visible_feature": user_visible_feature,
                "source_family": source_family,
                "classification": source_family,
                "table_family": "security_credential_expiration",
                "account_usage_use": account_usage_use,
                "row_limit": row_limit,
                "pruning_predicate": pruning_predicate,
                "deterministic_order_by": True,
                "frequency": "explicit_refresh_or_live_validation",
                "execution_frequency": "explicit_refresh_or_live_validation",
                "cost_risk": "medium" if account_usage_use != "none" else "low",
                "keep_delete_decision": "keep",
                "replacement_path": "",
                "daily_safe": daily_safe,
                "admin_only": admin_only,
                "launch_status": "retained_owned",
                "raw_sql_included": False,
            }
        )

    if "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS" in setup_text:
        add(
            "credential_expiration_refresh_source",
            purpose="Refresh compact credential-expiration rows from Snowflake credential metadata.",
            user_visible_feature="Credential expirations",
            source_family="refresh_fast",
            account_usage_use="refresh/setup/live only",
            admin_only=True,
            daily_safe=True,
            value_to_app="Feeds packet-backed Security Monitoring credential expiration metrics and actions.",
        )
    if "MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT" in setup_text:
        add(
            "credential_expiration_compact_mart",
            purpose="Store compact credential-expiration rows for Security packet, evidence, and actions.",
            user_visible_feature="Credential expirations",
            source_family="refresh_fast",
            account_usage_use="none",
            admin_only=True,
            daily_safe=True,
            value_to_app="Separates source credential metadata from daily first-paint Security Monitoring surfaces.",
            row_limit="current compact credential rows",
            pruning_predicate="expiration_date due/expired window",
        )
    if "SNOWFLAKE.ACCOUNT_USAGE.USERS" in setup_text and "MART_USER_DIM_CURRENT" in setup_text:
        add(
            "user_display_dimension_refresh_source",
            purpose="Refresh compact user display-name dimension.",
            user_visible_feature="User display names",
            source_family="refresh_fast",
            account_usage_use="refresh/setup/live only",
            admin_only=True,
            daily_safe=True,
            value_to_app="Allows daily charts and tables to show friendly user names without page-entry Account Usage queries.",
        )
    if "FROM MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT C" in setup_text:
        add(
            "credential_expiration_compact_evidence",
            purpose="Publish credential-expiration evidence from compact mart rows.",
            user_visible_feature="Credential expirations",
            source_family="compact_evidence",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Explicit evidence loads can show credential owner, type, status, and expiration without broad source scans.",
            row_limit="5000 max evidence publish rows",
            pruning_predicate="expiration due/expired flags",
        )
        add(
            "credential_expiration_evidence",
            purpose="Expose credential-expiration rows only through explicit Security evidence loads.",
            user_visible_feature="Credential expirations",
            source_family="targeted_evidence",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Allows sanitized credential evidence/export/case payloads without first-paint source scans.",
            row_limit="5000 max evidence publish rows; app default evidence limit applies",
            pruning_predicate="expiration due/expired flags plus target filters",
        )
    if "SECURITY_CREDENTIALS_EXPIRING_30D_COUNT" in setup_text:
        add(
            "credential_expiration_security_packet",
            purpose="Add credential-expiration fields to Security Monitoring decision packets.",
            user_visible_feature="Credential expirations",
            source_family="daily_first_paint_packet",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Security overview first paint can render the credential-expiration metric from the current packet.",
            row_limit="one active packet row per scope",
            pruning_predicate="active packet logical key",
        )
    if "SECURITY_CREDENTIAL_EXPIRATION" in setup_text and "CREDENTIAL_EXPIRING::" in setup_text:
        add(
            "credential_expiration_alert_action",
            purpose="Promote expired and expiring credentials into findings/actions.",
            user_visible_feature="Alert Center and View all priorities credential findings",
            source_family="daily_first_paint_packet",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Makes credential expiration actionable with route/evidence context.",
            row_limit="one finding/action per active packet candidate",
            pruning_predicate="expired or expiring credential counts > 0",
        )
    if "MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT" in validation_text:
        add(
            "credential_expiration_live_validation",
            purpose="Validate credential-expiration mart, packet fields, and user-display columns.",
            user_visible_feature="Credential expirations",
            source_family="deployment_validation",
            account_usage_use="setup/live validation only",
            admin_only=True,
            daily_safe=True,
            value_to_app="Blocks launch when credential/user-display schema proof is incomplete.",
            row_limit="validation metadata only",
            pruning_predicate="information_schema/object contract checks",
        )
    if "USER_CHART_LABEL" in setup_text and "FACT_CORTEX_DAILY" in setup_text:
        add(
            "cortex_user_label_source",
            purpose="Persist daily-safe Cortex user display/chart labels from the user dimension.",
            user_visible_feature="Cortex user charts and Cost Workbench Cortex rows",
            source_family="refresh_fast",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Keeps Cortex user labels friendly while preserving stable USER_NAME grouping.",
            row_limit="daily Cortex fact rows",
            pruning_predicate="Cortex usage window and service type filters",
        )
    add(
        "cortex_user_label_export_sanitizer",
        purpose="Sanitize user labels and raw IDs in default Cortex/Security exports.",
        user_visible_feature="Default user exports",
        source_family="compact_evidence",
        account_usage_use="none",
        admin_only=False,
        daily_safe=True,
        value_to_app="Prevents USER_ID from appearing in default daily exports while preserving totals.",
        row_limit="visible export rows",
        pruning_predicate="rendered/exported row set",
    )
    return rows


def build_sql_value_inventory(root: Path) -> dict[str, Any]:
    sql_files = sorted((root / "snowflake").rglob("*.sql"))
    rows = [_classify_sql_path(path, root) for path in sql_files]
    rows.extend(_supplemental_overwatch_rows(root))
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
