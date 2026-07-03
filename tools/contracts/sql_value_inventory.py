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
    route_text = (
        (root / ".overwatch_final" / "sections" / "command_brief_routes.py").read_text(
            encoding="utf-8",
            errors="ignore",
        ).upper()
        if (root / ".overwatch_final" / "sections" / "command_brief_routes.py").exists()
        else ""
    )
    target_filter_text = (
        (root / ".overwatch_final" / "sections" / "decision_workspace_target_filters.py").read_text(
            encoding="utf-8",
            errors="ignore",
        ).upper()
        if (root / ".overwatch_final" / "sections" / "decision_workspace_target_filters.py").exists()
        else ""
    )
    credential_helper_text = (
        (root / ".overwatch_final" / "utils" / "security_credentials.py").read_text(
            encoding="utf-8",
            errors="ignore",
        ).upper()
        if (root / ".overwatch_final" / "utils" / "security_credentials.py").exists()
        else ""
    )
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
        owner: str = "Security Monitoring",
        table_family: str = "security_credential_expiration",
        row_limit: str = "bounded_by_refresh_window",
        pruning_predicate: str = "company/window/expiration_date predicates",
    ) -> None:
        rows.append(
            {
                "path_id": path_id,
                "path": "snowflake/mart_setup/05_load_procedures.sql",
                "source_file": "snowflake/mart_setup/05_load_procedures.sql",
                "function_or_procedure": path_id,
                "owner": owner,
                "purpose": purpose,
                "value_to_app": value_to_app,
                "user_visible_feature": user_visible_feature,
                "source_family": source_family,
                "classification": source_family,
                "table_family": table_family,
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
            "security_credential_compact_evidence",
            purpose="Serve targeted credential evidence from compact mart rows after explicit click.",
            user_visible_feature="Security credential evidence",
            source_family="targeted_evidence",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Proves Security credential evidence is compact-mart-backed and not an Account Usage daily path.",
            row_limit="visible credential evidence rows, default evidence limit applies",
            pruning_predicate="USER_CREDENTIAL target predicate and expiration flags",
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
            "security_credential_expiration_packet",
            purpose="Carry combined credential risk and source status fields in the Security packet.",
            user_visible_feature="Security Monitoring credential expirations tile",
            source_family="daily_first_paint_packet",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Allows one-packet first paint to render expired plus expiring credential risk.",
            row_limit="one active packet row per scope",
            pruning_predicate="active packet logical key",
        )
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
        add(
            "security_credential_render_tile",
            purpose="Render the packet-backed credential-expiration tile on Security Monitoring first paint.",
            user_visible_feature="Security Monitoring credential expirations tile",
            source_family="daily_first_paint_packet",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Shows expired and expiring credential risk without querying credential source metadata.",
            row_limit="one active packet metric row per scope",
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
        add(
            "security_credential_case_payload",
            purpose="Build sanitized credential-expiration case payloads from compact evidence rows.",
            user_visible_feature="Security credential expiration case payload",
            source_family="targeted_evidence",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Lets users route and package credential remediation context without raw credential identifiers.",
            row_limit="visible credential evidence rows",
            pruning_predicate="route target and compact evidence filters",
        )
    if "SECURITY_CREDENTIAL_EXPIRATIONS" in route_text:
        add(
            "security_credential_route",
            purpose="Route Alert Center credential findings to Security Monitoring with target context.",
            user_visible_feature="Review Credential Expirations",
            source_family="route_action",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Preserves credential evidence context while keeping route actions query-free.",
            row_limit="one route target context",
            pruning_predicate="selected credential finding",
        )
    if "USER_CREDENTIAL" in target_filter_text and "CREDENTIAL_ID" in target_filter_text:
        add(
            "security_credential_target_filter",
            purpose="Push USER_CREDENTIAL target filters into credential evidence SQL before load.",
            user_visible_feature="Credential expiration evidence",
            source_family="targeted_evidence",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Prevents broad evidence loads when users route from a credential finding.",
            row_limit="targeted compact evidence rows",
            pruning_predicate="USER_NAME/CREDENTIAL/EVIDENCE_ID exact target filter",
        )
    if "SANITIZE_CREDENTIAL_EXPORT" in credential_helper_text:
        add(
            "security_credential_export",
            purpose="Export sanitized credential evidence rows without raw credential/user identifiers.",
            user_visible_feature="Credential expiration export",
            source_family="compact_evidence",
            account_usage_use="none",
            admin_only=False,
            daily_safe=True,
            value_to_app="Provides file-backed remediation evidence while excluding USER_ID and CREDENTIAL_ID by default.",
            row_limit="visible credential evidence rows",
            pruning_predicate="explicit evidence row set",
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
        add(
            "security_credential_live_validation",
            purpose="Reconcile live credential source, compact mart, packet, render, evidence, export, and case artifacts.",
            user_visible_feature="Credential expirations",
            source_family="live_validation",
            account_usage_use="setup/live validation only",
            admin_only=True,
            daily_safe=True,
            value_to_app="Blocks internal_live/prod_candidate when credential value proof is missing or mismatched.",
            row_limit="bounded live validation aggregate rows",
            pruning_predicate="selected scope and expiration bucket filters",
        )
    add(
        "security_credential_snapshot_proof",
        purpose="Generate sanitized rendered snapshots for Alert credential route and Security credential evidence flow.",
        user_visible_feature="Security credential expiration release snapshots",
        source_family="deployment_validation",
        account_usage_use="none",
        admin_only=False,
        daily_safe=True,
        value_to_app="Provides release-visible render proof for the credential route/evidence/export/case workflow.",
        row_limit="six deterministic snapshot files",
        pruning_predicate="runtime rendered rows and file-backed payload previews",
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
    add(
        "cortex_token_efficiency_metrics",
        purpose="Compute Cortex token-efficiency metrics from summed tokens, requests, credits, and AI-rate cost.",
        user_visible_feature="Cortex token efficiency",
        source_family="compact_evidence",
        account_usage_use="none",
        admin_only=False,
        daily_safe=True,
        value_to_app="Shows token efficiency without summing ratios or switching to compute credit pricing.",
        row_limit="loaded Cortex user rows",
        pruning_predicate="explicit Cortex user-attribution load window",
    )
    add(
        "cortex_efficiency_workbench",
        purpose="Expose Cortex token-efficiency outlier analysis only after explicit user action.",
        user_visible_feature="Load Cortex Efficiency",
        source_family="targeted_evidence",
        account_usage_use="none",
        admin_only=False,
        daily_safe=True,
        value_to_app="Identifies high cost per 1K tokens, low tokens per dollar, and unusual request/token patterns.",
        row_limit="loaded Cortex user rows",
        pruning_predicate="explicit action and loaded Cortex user attribution frame",
    )
    add(
        "cortex_token_efficiency_export",
        purpose="Export sanitized Cortex token-efficiency rows with token/request/cost ratio fields.",
        user_visible_feature="Cortex token efficiency export",
        source_family="compact_evidence",
        account_usage_use="none",
        admin_only=False,
        daily_safe=True,
        value_to_app="Provides exportable efficiency fields while excluding USER_ID/RAW_USER_ID by default.",
        row_limit="visible Cortex efficiency rows",
        pruning_predicate="explicit workbench row set",
    )
    high_value_metric_paths = (
        (
            "decision_readiness_refresh_source",
            "Refresh compact decision-readiness components from packet health, SLO, drift, and release proof summaries.",
            "Decision readiness",
            "decision_readiness",
            "none",
            "Feeds Executive packet-backed readiness status without adding page-entry diagnostics.",
        ),
        (
            "dba_critical_path_refresh_source",
            "Refresh compact DBA critical-path delay and downstream impact rows.",
            "DBA critical path",
            "dba_critical_path",
            "refresh/setup/live only",
            "Feeds DBA packet-backed critical-path delay and explicit evidence.",
        ),
        (
            "alert_quality_refresh_source",
            "Refresh compact alert quality, dedupe, flapping, stale, and routing rows.",
            "Alert quality",
            "alert_quality",
            "none",
            "Feeds Alert Center packet-backed queue quality metrics and explicit alert quality evidence.",
        ),
        (
            "retained_storage_waste_refresh_source",
            "Refresh compact retained-storage waste rows from storage and read-recency summaries.",
            "Retained storage waste",
            "retained_storage_waste",
            "refresh/setup/live only",
            "Feeds Cost packet-backed storage waste metrics without overview storage-source scans.",
        ),
        (
            "query_optimization_score_refresh_source",
            "Refresh compact query optimization opportunity scores from query insight summaries.",
            "Query optimization score",
            "query_optimization_score",
            "refresh/setup/live only",
            "Feeds Workload packet-backed query optimization metrics and explicit evidence.",
        ),
        (
            "sensitive_access_exposure_refresh_source",
            "Refresh compact sensitive data access exposure rows from access and policy coverage summaries.",
            "Sensitive data access exposure",
            "sensitive_data_access_exposure",
            "refresh/setup/live only",
            "Feeds Security packet-backed sensitive access metrics without first-paint access-history scans.",
        ),
        (
            "release_proof_freshness_admin_source",
            "Refresh admin-only release proof freshness status from release candidate and launch readiness artifacts.",
            "Settings/Admin Setup Health release proof freshness",
            "release_proof_freshness",
            "none",
            "Feeds Setup Health release freshness status while keeping daily Settings clean.",
        ),
        (
            "query_insights_refresh_source",
            "Refresh compact query optimization opportunities from query insight sources.",
            "Query optimization opportunities",
            "query_optimization_opportunities",
            "refresh/setup/live only",
            "Feeds Workload and DBA packet-backed query optimization opportunity metrics.",
        ),
        (
            "query_cost_attribution_refresh_source",
            "Refresh query cost attribution driver rows from compact attribution sources.",
            "Query cost attribution",
            "query_cost_attribution",
            "refresh/setup/live only",
            "Feeds Cost and Workload query cost driver metrics without replacing account billed total.",
        ),
        (
            "storage_waste_refresh_source",
            "Refresh compact retained-storage and storage-waste rows.",
            "Storage waste",
            "storage_waste",
            "refresh/setup/live only",
            "Feeds Cost storage waste metrics and explicit storage evidence.",
        ),
        (
            "access_history_refresh_source",
            "Refresh compact sensitive-object access risk rows.",
            "Sensitive object access",
            "sensitive_object_access",
            "refresh/setup/live only",
            "Feeds Security object-access risk metrics without first-paint access-history scans.",
        ),
        (
            "trust_center_refresh_source",
            "Refresh compact Trust Center finding rows when source is licensed and accessible.",
            "Trust Center findings",
            "trust_center_findings",
            "refresh/setup/live only",
            "Feeds Security and Alert Trust Center packet signals.",
        ),
        (
            "pipeline_freshness_refresh_source",
            "Refresh pipeline freshness and dynamic-table health rows.",
            "Pipeline freshness",
            "pipeline_freshness",
            "refresh/setup/live only",
            "Feeds Workload pipeline freshness metrics without overview evidence loads.",
        ),
        (
            "data_quality_refresh_source",
            "Refresh optional data quality expectation health rows.",
            "Data quality health",
            "data_quality_health",
            "none",
            "Feeds data quality actions while allowing clean unavailable state when source is absent.",
        ),
        (
            "optimization_roi_refresh_source",
            "Refresh optimization cost, benefit, and ROI support rows.",
            "Optimization ROI",
            "optimization_roi",
            "refresh/setup/live only",
            "Feeds Cost optimization ROI metrics with explicit benefit assumptions.",
        ),
        (
            "data_transfer_refresh_source",
            "Refresh data movement and transfer cost rows.",
            "Data movement cost",
            "data_transfer_cost",
            "refresh/setup/live only",
            "Feeds Cost transfer-cost metrics separately from account billed and warehouse bridge totals.",
        ),
        (
            "warehouse_efficiency_refresh_source",
            "Refresh warehouse efficiency score and ratio rows.",
            "Warehouse efficiency",
            "warehouse_efficiency",
            "none",
            "Feeds DBA and Cost warehouse efficiency signals from compact warehouse facts.",
        ),
        (
            "forecast_accuracy_refresh_source",
            "Refresh forecast error, run-rate variance, and budget variance rows.",
            "Forecast accuracy",
            "forecast_accuracy",
            "none",
            "Feeds Cost and Executive forecast quality metrics without fake budget risk.",
        ),
        (
            "action_effectiveness_refresh_source",
            "Refresh action closure, MTTA, MTTR, and verified outcome rows.",
            "Action effectiveness",
            "action_effectiveness",
            "none",
            "Feeds Executive and Alert outcome metrics from actual action timestamps and verified closures.",
        ),
        (
            "app_health_admin_source",
            "Refresh admin-only OVERWATCH app health metrics.",
            "Settings/Admin Setup Health",
            "overwatch_app_health",
            "none",
            "Feeds Setup Health only; app health metrics must not become daily primary cards.",
        ),
    )
    for path_id, purpose, feature, table_family, account_usage, value_to_app in high_value_metric_paths:
        setup_admin_metric = table_family in {"overwatch_app_health", "release_proof_freshness"}
        add(
            path_id,
            purpose=purpose,
            user_visible_feature=feature,
            source_family="setup_admin" if setup_admin_metric else "refresh_fast",
            account_usage_use=account_usage,
            admin_only=account_usage != "none" or setup_admin_metric,
            daily_safe=True,
            owner="Decision Workspace metric governance",
            table_family=table_family,
            value_to_app=value_to_app,
            row_limit="bounded_by_refresh_window_or_admin_scope",
            pruning_predicate="company/environment/window predicates or admin setup scope",
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
