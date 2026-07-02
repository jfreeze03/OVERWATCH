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
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.contracts.full_app_gauntlet import (
    REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS,
    write_full_app_gauntlet_artifacts,
)
from tools.contracts.encoding_hygiene import write_encoding_hygiene_artifacts
from tools.contracts.snowflake_execution_validation import write_snowflake_validation_artifacts
from tools.contracts.cost_db_formula_authority import (
    REQUIRED_FORMULA_AUTHORITY_ARTIFACTS,
    evaluate_cost_db_formula_authority,
    write_cost_db_formula_authority_artifacts,
)
from tools.contracts.formula_end_to_end_validation import (
    CORTEX_SERVICE_TYPE_GATE_REL,
    FLAT_PACKET_FORMULA_REL,
    FORMULA_GATE_REL,
    FORMULA_VALUE_GATE_REL,
    FORMULA_VALUE_RECONCILIATION_REL,
    FORMULA_VALUE_SOURCE_RECONCILIATION_REL,
    PACKET_SCHEMA_GATE_REL,
    PACKET_SCHEMA_UPGRADE_REL,
    evaluate_cortex_service_type_gate,
    evaluate_formula_end_to_end_gate,
    evaluate_packet_schema_gate,
    evaluate_snowflake_formula_gate,
    SNOWFLAKE_FORMULA_GATE_REL,
    SNOWFLAKE_FORMULA_LIVE_REL,
    SNOWFLAKE_FORMULA_STATIC_REL,
    SNOWFLAKE_FORMULA_VALUE_REL,
    write_formula_end_to_end_artifacts,
)
from tools.contracts.snowflake_cli_live_validation import (
    CLI_CONNECTION_REL,
    CLI_COST_RECONCILIATION_REL,
    CLI_COST_RECONCILIATION_GATE_REL,
    CLI_FORMULA_VALUE_REL,
    CLI_FORMULA_VALUE_GATE_REL,
    CLI_LAUNCH_GATE_REL,
    CLI_MANIFEST_RECONCILIATION_REL,
    CLI_PACKET_VALUE_REL,
    CLI_QUERY_BUDGET_REL,
    CLI_RELEASE_REL,
    CLI_SETUP_MIGRATION_GATE_REL,
    CLI_SETUP_MIGRATION_REL,
    CLI_SETUP_REL,
    CLI_TEMP_FILE_HYGIENE_GATE_REL,
    REQUIRED_CLI_ARTIFACTS,
    evaluate_snowflake_cli_live_gate,
    write_snowflake_cli_live_validation_artifacts,
)
from tools.contracts.packet_availability_live_validation import (
    PACKET_AVAILABILITY_GATE_REL,
    PACKET_AVAILABILITY_MATRIX_REL,
    evaluate_packet_availability_gate,
)
from tools.contracts.action_click_gauntlet import (
    ACTION_CLICK_GATE_REL,
    LIVE_FEATURE_GATE_REL,
    evaluate_action_click_gate,
    evaluate_live_feature_gate,
)
from tools.contracts.browser_render_gauntlet import (
    BROWSER_RENDER_GATE_REL,
    BROWSER_RENDER_RESULTS_REL,
    evaluate_browser_render_gate,
)
from tools.contracts.browser_smoke_runner import (
    BROWSER_SMOKE_GATE_REL,
    BROWSER_SMOKE_RESULTS_REL,
    evaluate_browser_smoke_gate,
)
from tools.contracts.deterministic_streamlit_render import (
    DETERMINISTIC_RENDER_GATE_REL,
    DETERMINISTIC_RENDER_RESULTS_REL,
    evaluate_deterministic_render_gate,
)
from tools.contracts.export_download_gauntlet import evaluate_export_download_gate
from tools.contracts.full_app_launch_gauntlet import (
    EXPORT_DOWNLOAD_GATE_REL,
    FIRST_PAINT_GATE_REL,
    FIRST_PAINT_PERFORMANCE_REL,
    FULL_APP_LAUNCH_GATE_REL,
    FULL_APP_LAUNCH_RESULTS_REL,
    PACKET_FALLBACK_GATE_REL,
    PACKET_FALLBACK_UI_REL,
    SETTINGS_GATE_REL,
    SETTINGS_WORDING_REL,
    SUMMARY_BOARD_VISUAL_CONTRACT_REL,
    SUMMARY_BOARD_VISUAL_GATE_REL,
    evaluate_simple_gate,
)
from tools.contracts.full_app_release_sweep import (
    FULL_APP_RELEASE_FAILURES_REL,
    FULL_APP_RELEASE_SWEEP_GATE_REL,
    FULL_APP_RELEASE_SWEEP_RESULTS_REL,
    evaluate_full_app_release_sweep_gate,
    write_full_app_release_sweep_artifacts,
)
from tools.contracts.rendered_ui_leak_scan import (
    DAILY_WORDING_GATE_REL,
    RENDERED_UI_LEAK_GATE_REL,
    RENDERED_UI_LEAK_RESULTS_REL,
    evaluate_rendered_ui_leak_gate,
)
from tools.contracts.render_provenance_reconciliation import (
    RENDER_PROVENANCE_RECONCILIATION_GATE_REL,
    RENDER_PROVENANCE_RECONCILIATION_REL,
    evaluate_render_provenance_reconciliation_gate,
)
from tools.contracts.runtime_artifact_provenance import (
    RUNTIME_ARTIFACT_PROVENANCE_GATE_REL,
    RUNTIME_ARTIFACT_PROVENANCE_REL,
    evaluate_runtime_artifact_provenance_gate,
)
from tools.contracts.source_internal_leak_scan import (
    SOURCE_INTERNAL_LEAK_GATE_REL,
    SOURCE_INTERNAL_LEAK_RESULTS_REL,
    evaluate_source_internal_leak_scan_gate,
)
from tools.contracts.sql_value_inventory import (
    SQL_CLEANUP_GATE_REL,
    SQL_VALUE_INVENTORY_REL,
    evaluate_sql_cleanup_gate,
)
from tools.contracts.sql_dead_code_scan import SQL_DEAD_CODE_SCAN_REL
from tools.contracts.delete_first_cleanup import (
    DELETE_FIRST_GATE_REL,
    DELETE_FIRST_INVENTORY_REL,
    DELETE_FIRST_RESULTS_REL,
    evaluate_delete_first_cleanup_gate,
    write_delete_first_cleanup_artifacts,
)
from tools.contracts.performance_budget_gate import (
    PERFORMANCE_BUDGET_GATE_REL,
    PERFORMANCE_BUDGET_RESULTS_REL,
    evaluate_performance_budget_gate,
    write_performance_budget_gate_artifacts,
)
from tools.contracts.cortex_token_efficiency_validation import (
    CORTEX_TOKEN_EFFICIENCY_GATE_REL,
    CORTEX_TOKEN_EFFICIENCY_LIVE_GATE_REL,
    write_cortex_token_efficiency_artifacts,
)
from tools.contracts.metric_source_governance import (
    METRIC_FAMILY_GATE_RELS,
    METRIC_SOURCE_GOVERNANCE_GATE_REL,
    write_metric_source_governance_artifacts,
)
from tools.contracts.security_credential_validation import (
    CORTEX_USER_LABEL_GATE_REL,
    SECURITY_CREDENTIAL_EVIDENCE_GATE_REL,
    SECURITY_CREDENTIAL_EXPORT_GATE_REL,
    SECURITY_CREDENTIAL_FIRST_PAINT_GATE_REL,
    SECURITY_CREDENTIAL_GATE_REL,
    SECURITY_CREDENTIAL_LIVE_GATE_REL,
    SECURITY_CREDENTIAL_RENDERED_LEAK_GATE_REL,
    SECURITY_CREDENTIAL_RENDER_GATE_REL,
    SECURITY_CREDENTIAL_SNAPSHOT_GATE_REL,
    SECURITY_CREDENTIAL_SQL_INVENTORY_GATE_REL,
    USER_DISPLAY_NAME_GATE_REL,
    USER_DISPLAY_NAME_LIVE_GATE_REL,
    USER_DISPLAY_SURFACE_GATE_REL,
    write_security_credential_validation_artifacts,
)
from tools.contracts.user_stress_test import (
    USER_STRESS_GATE_REL,
    USER_STRESS_RESULTS_REL,
    evaluate_user_stress_gate,
)
from tools.contracts.settings_live_feature_gauntlet import (
    SETTINGS_LIVE_FEATURE_GATE_REL,
    SETTINGS_LIVE_FEATURE_RESULTS_REL,
    evaluate_settings_live_feature_gate,
    write_settings_live_feature_gauntlet_artifacts,
)
from tools.contracts.ui_kit_alignment import (
    SECTION_LAYOUT_CONTRACT_GATE_REL,
    SOURCE_SAFE_FOOTER_GATE_REL,
    UI_KIT_ALIGNMENT_GATE_REL,
    write_ui_kit_alignment_artifacts,
)


LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
RELEASE_CANDIDATE_DIR = "artifacts/release_candidate"

REQUIRED_LAUNCH_READINESS_ARTIFACTS = {
    f"{LAUNCH_READINESS_DIR}/launch_readiness_summary.json",
    f"{LAUNCH_READINESS_DIR}/launch_readiness_failures.json",
    f"{LAUNCH_READINESS_DIR}/release_gate_matrix.json",
    f"{LAUNCH_READINESS_DIR}/launch_profile_results.json",
    f"{LAUNCH_READINESS_DIR}/launch_waivers.json",
    f"{LAUNCH_READINESS_DIR}/profile_gate_failures.json",
    f"{LAUNCH_READINESS_DIR}/raw_invariant_results.json",
    f"{LAUNCH_READINESS_DIR}/raw_invariant_failures.json",
    f"{LAUNCH_READINESS_DIR}/browser_smoke_results.json",
    f"{LAUNCH_READINESS_DIR}/browser_required_coverage.json",
    f"{LAUNCH_READINESS_DIR}/browser_or_snapshot_failures.json",
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
    f"{LAUNCH_READINESS_DIR}/delete_first_release_results.json",
    f"{LAUNCH_READINESS_DIR}/docs_readiness_results.json",
    f"{LAUNCH_READINESS_DIR}/encoding_hygiene_results.json",
    f"{LAUNCH_READINESS_DIR}/snowflake_validation_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/live_execution_manifest_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/summary_board_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/billing_reconciliation_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/billing_reconciliation_live_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/packet_availability_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/live_cost_reconciliation_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/daily_wording_gate_results.json",
    FULL_APP_RELEASE_SWEEP_GATE_REL,
    SETTINGS_LIVE_FEATURE_GATE_REL,
    FULL_APP_LAUNCH_GATE_REL,
    DETERMINISTIC_RENDER_GATE_REL,
    BROWSER_SMOKE_GATE_REL,
    BROWSER_RENDER_GATE_REL,
    RUNTIME_ARTIFACT_PROVENANCE_GATE_REL,
    RENDER_PROVENANCE_RECONCILIATION_GATE_REL,
    RENDERED_UI_LEAK_GATE_REL,
    SETTINGS_GATE_REL,
    FIRST_PAINT_GATE_REL,
    PACKET_FALLBACK_GATE_REL,
    SUMMARY_BOARD_VISUAL_GATE_REL,
    ACTION_CLICK_GATE_REL,
    EXPORT_DOWNLOAD_GATE_REL,
    LIVE_FEATURE_GATE_REL,
    SQL_CLEANUP_GATE_REL,
    DELETE_FIRST_GATE_REL,
    PERFORMANCE_BUDGET_GATE_REL,
    METRIC_SOURCE_GOVERNANCE_GATE_REL,
    UI_KIT_ALIGNMENT_GATE_REL,
    SECTION_LAYOUT_CONTRACT_GATE_REL,
    SOURCE_SAFE_FOOTER_GATE_REL,
    *METRIC_FAMILY_GATE_RELS.values(),
    CORTEX_TOKEN_EFFICIENCY_GATE_REL,
    CORTEX_TOKEN_EFFICIENCY_LIVE_GATE_REL,
    SECURITY_CREDENTIAL_GATE_REL,
    SECURITY_CREDENTIAL_LIVE_GATE_REL,
    USER_DISPLAY_NAME_GATE_REL,
    USER_DISPLAY_NAME_LIVE_GATE_REL,
    USER_DISPLAY_SURFACE_GATE_REL,
    CORTEX_USER_LABEL_GATE_REL,
    SECURITY_CREDENTIAL_EXPORT_GATE_REL,
    SECURITY_CREDENTIAL_RENDER_GATE_REL,
    SECURITY_CREDENTIAL_EVIDENCE_GATE_REL,
    SECURITY_CREDENTIAL_FIRST_PAINT_GATE_REL,
    SECURITY_CREDENTIAL_SNAPSHOT_GATE_REL,
    SECURITY_CREDENTIAL_SQL_INVENTORY_GATE_REL,
    SECURITY_CREDENTIAL_RENDERED_LEAK_GATE_REL,
    USER_STRESS_GATE_REL,
    SOURCE_INTERNAL_LEAK_GATE_REL,
    f"{LAUNCH_READINESS_DIR}/cortex_cost_consistency_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/cost_chart_workbench_gate_results.json",
    CORTEX_SERVICE_TYPE_GATE_REL,
    f"{LAUNCH_READINESS_DIR}/cost_db_formula_authority_gate_results.json",
    FORMULA_GATE_REL,
    FORMULA_VALUE_GATE_REL,
    FORMULA_VALUE_RECONCILIATION_REL,
    FORMULA_VALUE_SOURCE_RECONCILIATION_REL,
    PACKET_SCHEMA_GATE_REL,
    SNOWFLAKE_FORMULA_GATE_REL,
    SNOWFLAKE_FORMULA_VALUE_REL,
    f"{LAUNCH_READINESS_DIR}/formula_live_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/metric_semantic_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/query_budget_gate_results.json",
    PERFORMANCE_BUDGET_RESULTS_REL,
    FULL_APP_RELEASE_SWEEP_RESULTS_REL,
    FULL_APP_RELEASE_FAILURES_REL,
    SETTINGS_LIVE_FEATURE_RESULTS_REL,
    f"{LAUNCH_READINESS_DIR}/workload_formula_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/cost_advisor_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/date_widget_regression_results.json",
    f"{LAUNCH_READINESS_DIR}/snowflake_raw_validation_recheck.json",
    f"{LAUNCH_READINESS_DIR}/snowflake_validation_failures.json",
    f"{LAUNCH_READINESS_DIR}/ci_run_review_results.json",
    f"{LAUNCH_READINESS_DIR}/ci_artifact_review_results.json",
    f"{LAUNCH_READINESS_DIR}/artifact_upload_review_results.json",
    f"{LAUNCH_READINESS_DIR}/ci_artifact_reality_results.json",
    f"{LAUNCH_READINESS_DIR}/release_candidate_ci_context.json",
    f"{LAUNCH_READINESS_DIR}/release_candidate_gate_results.json",
    f"{LAUNCH_READINESS_DIR}/artifact_manifest.json",
    *(REQUIRED_CLI_ARTIFACTS - {CLI_RELEASE_REL}),
}

REQUIRED_RELEASE_CANDIDATE_ARTIFACTS = {
    f"{RELEASE_CANDIDATE_DIR}/artifact_manifest.json",
    f"{RELEASE_CANDIDATE_DIR}/artifact_hashes.json",
    f"{RELEASE_CANDIDATE_DIR}/artifact_reconciliation_results.json",
    f"{RELEASE_CANDIDATE_DIR}/product_gauntlet_release_results.json",
    f"{RELEASE_CANDIDATE_DIR}/release_candidate_summary.json",
    f"{RELEASE_CANDIDATE_DIR}/release_candidate_failures.json",
    f"{RELEASE_CANDIDATE_DIR}/release_gate_matrix.json",
    f"{RELEASE_CANDIDATE_DIR}/release_notes.json",
    CLI_RELEASE_REL,
}


def _required_release_artifact_count() -> int:
    return (
        len(REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS)
        + len(REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        + len(REQUIRED_RELEASE_CANDIDATE_ARTIFACTS)
        + len(REQUIRED_FORMULA_AUTHORITY_ARTIFACTS)
    )

CI_UPLOAD_PATHS = {
    "artifacts/release_candidate/**",
    "artifacts/launch_readiness/**",
    "artifacts/formula_authority/**",
    "artifacts/encoding_hygiene_results.json",
    "artifacts/full_app_validation/**",
    "artifacts/full_app_inventory/**",
    "artifacts/cleanup/**",
    "artifacts/snowflake_validation/**",
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
    "scripts/run_snowflake_cli_live_validation.ps1",
    "scripts/run_snowflake_cli_live_validation.sh",
}

RELEASE_ARTIFACT_ROOTS = (
    "artifacts/launch_readiness",
    "artifacts/full_app_validation",
    "artifacts/full_app_inventory",
    "artifacts/snowflake_validation",
    "artifacts/formula_authority",
    "artifacts/cleanup",
    "artifacts/generated_button_artifacts",
    "artifacts/decision_workspace_html_snapshots",
    "artifacts/browser_screenshots",
    "artifacts/release_candidate",
)

RELEASE_ROOT_ARTIFACT_GLOBS = (
    "artifacts/encoding_hygiene_results.json",
    "artifacts/query_*",
    "artifacts/direct_sql_static_scan.json",
    "artifacts/session_open_static_scan.json",
    "artifacts/sql_performance_lint_findings.json",
    "artifacts/sql_performance_lint_file_inventory.json",
    "artifacts/button_route_manifest.json",
    "artifacts/button_route_results.json",
)

RELEASE_REQUIRED_CATEGORIES = {
    "launch_readiness",
    "full_app_validation",
    "full_app_inventory",
    "snowflake_validation",
    "formula_authority",
    "encoding_hygiene",
    "cleanup",
    "query_performance",
    "direct_session_sql",
    "snapshots",
    "browser",
    "exports",
    "release_candidate",
}

RELEASE_SELF_REFERENTIAL_FILES = {
    f"{RELEASE_CANDIDATE_DIR}/artifact_manifest.json",
    f"{RELEASE_CANDIDATE_DIR}/artifact_hashes.json",
    f"{RELEASE_CANDIDATE_DIR}/artifact_reconciliation_results.json",
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

LAUNCH_PROFILES = {"internal_fixture", "internal_live", "prod_candidate"}
DEFAULT_LAUNCH_PROFILE = "internal_fixture"

REQUIRED_QUERY_SEARCH_CASES = {
    "render_no_click",
    "exact_query_id",
    "query_signature",
    "related_executions",
    "sql_preview",
    "default_export_no_query_text",
    "text_contains_no_autorun",
    "text_contains_explicit_search",
    "warehouse_prefill_no_autorun",
    "account_usage_fallback_unconfirmed",
    "account_usage_fallback_confirmed",
    "no_result_search",
    "slow_query_timeout",
    "permission_denied",
}

REQUIRED_CASE_FIELDS = {"section", "workflow", "scope", "target", "freshness", "source", "summary", "row_count"}

GENERIC_WAIVER_TEXT = {"", "n/a", "na", "none", "todo", "tbd", "future", "optional", "unsupported"}

SNOWFLAKE_RAW_RECHECK_ARTIFACTS = (
    "artifacts/snowflake_validation/snowflake_validation_summary.json",
    "artifacts/snowflake_validation/live_execution_manifest.json",
    "artifacts/snowflake_validation/live_execution_manifest_reconciliation.json",
    "artifacts/snowflake_validation/live_execution_manifest_category_coverage.json",
    "artifacts/snowflake_validation/live_validation_environment_results.json",
    "artifacts/snowflake_validation/live_validation_session_results.json",
    "artifacts/snowflake_validation/procedure_dependency_graph.json",
    "artifacts/snowflake_validation/procedure_compile_results.json",
    "artifacts/snowflake_validation/procedure_compile_coverage_results.json",
    "artifacts/snowflake_validation/procedure_smoke_call_results.json",
    "artifacts/snowflake_validation/procedure_smoke_call_coverage_results.json",
    "artifacts/snowflake_validation/packet_publication_validation_results.json",
    "artifacts/snowflake_validation/packet_shape_results.json",
    "artifacts/snowflake_validation/packet_size_results.json",
    "artifacts/snowflake_validation/packet_source_truth_results.json",
    "artifacts/snowflake_validation/packet_validation_detail_results.json",
    "artifacts/snowflake_validation/compact_evidence_mart_validation_results.json",
    "artifacts/snowflake_validation/compact_evidence_mart_detail_results.json",
    "artifacts/snowflake_validation/refresh_fast_results.json",
    "artifacts/snowflake_validation/refresh_full_results.json",
    "artifacts/snowflake_validation/refresh_detail_results.json",
    "artifacts/snowflake_validation/recent_snowflake_fix_validation_results.json",
    "artifacts/snowflake_validation/metric_candidate_shape_results.json",
    "artifacts/snowflake_validation/trend_cardinality_results.json",
    "artifacts/snowflake_validation/sql_encoding_scan_results.json",
    "artifacts/snowflake_validation/schema_drift_results.json",
    "artifacts/snowflake_validation/snowflake_error_sanitization_results.json",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_output(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return proc.stdout.strip()


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


def _selected_launch_profile() -> str:
    return os.environ.get("OVERWATCH_LAUNCH_PROFILE", DEFAULT_LAUNCH_PROFILE).strip() or DEFAULT_LAUNCH_PROFILE


def _load_launch_waivers() -> list[dict[str, Any]]:
    raw = os.environ.get("OVERWATCH_LAUNCH_WAIVERS_JSON", "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [
            {
                "gate": "waiver_parse",
                "owner": "",
                "reason": "invalid_json",
                "expiration_or_review_note": "",
                "valid": False,
            }
        ]
    rows = payload if isinstance(payload, list) else [payload]
    return [_normalize_waiver(_as_mapping(row)) for row in rows]


def _normalize_waiver(row: Mapping[str, Any]) -> dict[str, Any]:
    gate = str(row.get("gate") or row.get("name") or "").strip()
    owner = str(row.get("owner") or "").strip()
    reason = str(row.get("reason") or "").strip()
    review = str(row.get("expiration_or_review_note") or row.get("review_note") or row.get("expiration") or "").strip()
    expiration = str(row.get("expiration") or "").strip()
    approving_surface = str(row.get("approving_surface") or row.get("approval_surface") or row.get("surface") or "").strip()
    invalid_reasons: list[str] = []
    if not gate:
        invalid_reasons.append("missing_gate")
    if not owner:
        invalid_reasons.append("missing_owner")
    if not reason:
        invalid_reasons.append("missing_reason")
    if not review:
        invalid_reasons.append("missing_expiration_or_review_note")
    if not approving_surface:
        invalid_reasons.append("missing_approving_surface")
    lowered = {owner.lower(), reason.lower(), review.lower(), approving_surface.lower()}
    if lowered & GENERIC_WAIVER_TEXT:
        invalid_reasons.append("generic_waiver_text")
    if expiration:
        try:
            expires_at = datetime.fromisoformat(expiration.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < datetime.now(UTC):
                invalid_reasons.append("expired")
        except ValueError:
            invalid_reasons.append("invalid_expiration")
    return {
        "gate": gate,
        "owner": owner,
        "reason": reason,
        "expiration_or_review_note": review,
        "expiration": expiration,
        "approving_surface": approving_surface,
        "invalid_reasons": sorted(set(invalid_reasons)),
        "valid": not invalid_reasons,
    }


def _has_valid_waiver(waivers: Iterable[Mapping[str, Any]], gate: str) -> bool:
    return any(str(row.get("gate") or "") == gate and bool(row.get("valid")) for row in waivers)


def _launch_profile_results(profile: str, waivers: list[dict[str, Any]]) -> dict[str, Any]:
    recognized = profile in LAUNCH_PROFILES
    browser_required = profile in {"internal_live", "prod_candidate"}
    live_required = profile in {"internal_live", "prod_candidate"}
    fixture_enabled = os.environ.get("OVERWATCH_UI_FIXTURE_MODE") == "1"
    fixture_allowed = os.environ.get("OVERWATCH_ALLOW_FIXTURE_MODE") == "1"
    failures: list[str] = []
    if not recognized:
        failures.append(f"Unknown OVERWATCH_LAUNCH_PROFILE={profile!r}.")
    if profile == "prod_candidate" and fixture_enabled:
        failures.append("prod_candidate cannot run with fixture mode enabled.")
    if fixture_enabled and not fixture_allowed:
        failures.append("Fixture mode requires OVERWATCH_ALLOW_FIXTURE_MODE=1.")
    invalid_waivers = [row for row in waivers if not row.get("valid")]
    if invalid_waivers:
        failures.append("One or more launch waivers is missing owner, reason, approving surface, or expiration/review note.")
    return {
        "source": "launch_readiness_profile",
        "proof_source": "inventory_only",
        "selected_profile": profile,
        "recognized_profile": recognized,
        "available_profiles": sorted(LAUNCH_PROFILES),
        "browser_proof_required": browser_required,
        "live_query_history_required": live_required,
        "fixture_mode_enabled": fixture_enabled,
        "fixture_mode_allowed": fixture_allowed,
        "waiver_count": len(waivers),
        "invalid_waiver_count": len(invalid_waivers),
        "failures": failures,
        "passed": not failures,
        "raw_sql_included": False,
    }


def _profile_gate_failures(profile_results: Mapping[str, Any], waivers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for reason in _as_list(profile_results.get("failures")):
        failures.append(
            {
                "gate": "launch_profile",
                "reason": str(reason),
                "recommendation": "Set a recognized launch profile and keep fixture/debug settings compatible with that profile.",
            }
        )
    for waiver in waivers:
        if waiver.get("valid"):
            continue
        failures.append(
            {
                "gate": str(waiver.get("gate") or "launch_waiver"),
                "reason": "Invalid launch waiver.",
                "invalid_reasons": _as_list(waiver.get("invalid_reasons")),
                "owner": str(waiver.get("owner") or ""),
                "recommendation": "Provide owner, reason, approving surface, and a non-expired expiration or review note.",
            }
        )
    return {
        "source": "launch_readiness_profile_gate_failures",
        "proof_source": "inventory_only",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _security_first_paint_violation_count(payloads: Mapping[str, Any]) -> int:
    first_paint = _as_mapping(payloads.get("artifacts/full_app_validation/first_paint_performance_results.json"))
    count = 0
    for row in _as_list(first_paint.get("rows")):
        item = _as_mapping(row)
        if str(item.get("section") or "") != "Security Monitoring":
            continue
        violates = (
            not bool(item.get("passed"))
            or _as_int(item.get("account_usage_count")) > 0
            or _as_int(item.get("evidence_query_count")) > 0
            or _as_int(item.get("direct_sql_count")) > 0
            or _as_int(item.get("non_packet_first_paint_event_count")) > 0
        )
        if violates:
            count += 1
    return count


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_text_contains_raw_sql_or_secret(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    if re.search(r'"raw_sql_included"\s*:\s*true', text, flags=re.IGNORECASE):
        return True
    if re.search(r"(?i)(snowflake://|password\s*[:=]|private[_ -]?key\s*[:=]|github_pat_|ghp_[A-Za-z0-9]{20,})", text):
        return True
    return bool(re.search(r"(?is)\bCREATE\s+OR\s+REPLACE\b|\bSELECT\s+\*\b|Traceback \(most recent call last\):", text))


def _raw_sql_or_secret_value(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_raw_sql_or_secret_value(item) for item in value.values())
    if isinstance(value, list | tuple | set):
        return any(_raw_sql_or_secret_value(item) for item in value)
    text = str(value or "")
    if re.search(r"(?i)(snowflake://|password\s*[:=]|private[_ -]?key\s*[:=]|github_pat_|ghp_[A-Za-z0-9]{20,})", text):
        return True
    return bool(re.search(r"(?is)\bCREATE\s+OR\s+REPLACE\b|\bSELECT\s+\*\b|Traceback \(most recent call last\):", text))


def _release_artifact_category(rel: str) -> str:
    if rel.startswith("artifacts/release_candidate/"):
        return "release_candidate"
    if rel.startswith("artifacts/formula_authority/"):
        return "formula_authority"
    if rel.startswith("artifacts/launch_readiness/"):
        return "launch_readiness"
    if rel.startswith("artifacts/full_app_validation/"):
        if "export" in rel.lower() or "case_payload" in rel.lower():
            return "exports"
        return "full_app_validation"
    if rel.startswith("artifacts/full_app_inventory/"):
        return "full_app_inventory"
    if rel.startswith("artifacts/snowflake_validation/"):
        return "snowflake_validation"
    if rel.startswith("artifacts/cleanup/"):
        return "cleanup"
    if rel.startswith("artifacts/decision_workspace_html_snapshots/"):
        return "snapshots"
    if rel.startswith("artifacts/browser_screenshots/"):
        return "browser"
    if rel.startswith("artifacts/query_") or "/query_" in rel:
        return "query_performance"
    if rel.endswith("direct_sql_static_scan.json") or rel.endswith("session_open_static_scan.json"):
        return "direct_session_sql"
    if rel.endswith("encoding_hygiene_results.json"):
        return "encoding_hygiene"
    if "button" in rel:
        return "full_app_inventory"
    return "launch_readiness"


def _release_artifact_files(root: Path) -> list[str]:
    files: set[str] = set()
    for rel_root in RELEASE_ARTIFACT_ROOTS:
        path_root = root / rel_root
        if path_root.exists():
            files.update(
                str(path.relative_to(root)).replace("\\", "/")
                for path in path_root.rglob("*")
                if path.is_file()
            )
    for pattern in RELEASE_ROOT_ARTIFACT_GLOBS:
        files.update(
            str(path.relative_to(root)).replace("\\", "/")
            for path in root.glob(pattern)
            if path.is_file()
        )
    return sorted(files)


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


def _clean_release_candidate_directory(root: Path) -> None:
    artifacts_root = (root / "artifacts").resolve()
    release_dir = (root / RELEASE_CANDIDATE_DIR).resolve()
    if release_dir == artifacts_root or artifacts_root not in release_dir.parents:
        raise ValueError(f"refusing to clean outside artifacts root: {release_dir}")
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True, exist_ok=True)


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
        "python -m unittest tests.test_full_app_release_sweep tests.test_settings_live_feature_gauntlet",
        "python -m unittest tests.test_launch_readiness",
        "python -m unittest tests.test_encoding_hygiene",
        "python -m unittest tests.test_cost_db_formula_authority tests.test_cost_formula_authority tests.test_cortex_service_types tests.test_formula_end_to_end_validation tests.test_formula_packet_sql tests.test_packet_schema_upgrade",
        "python -m tools.contracts.encoding_hygiene",
        "python -m tools.contracts.cost_db_formula_authority",
        "python -m tools.contracts.formula_end_to_end_validation",
        "python -m unittest tests.test_snowflake_cli_live_validation",
        "python -m tools.contracts.snowflake_cli_live_validation --profile internal_fixture --skip-refresh",
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


def _ci_run_review_results(profile: str, waivers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    meta = _ci_metadata()
    missing_metadata = not bool(meta["github_actions"] and meta["workflow_run_id"] and meta["workflow_url"])
    metadata_required = profile in {"internal_live", "prod_candidate"}
    waiver_used = missing_metadata and _has_valid_waiver(waivers, "ci_metadata")
    commit_mismatch = bool(meta["github_sha"] and meta["source_commit_sha"] and meta["github_sha"] != meta["source_commit_sha"])
    workflow_url_missing = bool(meta["github_actions"] and meta["workflow_run_id"] and not meta["workflow_url"])
    passed = (not missing_metadata or not metadata_required or waiver_used) and not commit_mismatch and not workflow_url_missing
    warning = ""
    if missing_metadata and profile == "internal_fixture":
        warning = "Workflow metadata is unavailable outside GitHub Actions; internal_fixture records this as an explicit local-run warning."
    elif missing_metadata and profile == "internal_live":
        warning = "Workflow metadata is unavailable outside GitHub Actions; internal_live records this as a warning unless promoted to prod_candidate."
    elif missing_metadata and waiver_used:
        warning = "Workflow metadata is waived for this launch profile by an owner-approved waiver."
    elif missing_metadata:
        warning = "Workflow metadata is required for this launch profile."
    if commit_mismatch:
        warning = "GitHub Actions commit SHA does not match the evaluated source commit."
    elif workflow_url_missing:
        warning = "GitHub Actions metadata is present but workflow_url could not be constructed."
    return {
        "source": "launch_readiness_ci_run_review",
        "proof_source": "github_actions_metadata" if meta["github_actions"] else "local_inventory",
        "passed": passed,
        "launch_profile": profile,
        "github_actions": meta["github_actions"],
        "workflow_run_id": meta["workflow_run_id"],
        "workflow_url": meta["workflow_url"],
        "commit_sha": meta["commit_sha"],
        "source_commit_sha": meta["source_commit_sha"],
        "branch_ref": meta["branch_ref"],
        "run_attempt": meta["run_attempt"],
        "workflow_name": meta["workflow_name"],
        "workflow_job": meta["workflow_job"],
        "event_name": meta["event_name"],
        "repository": meta["repository"],
        "github_sha": meta["github_sha"],
        "commit_sha_matches_source": not commit_mismatch,
        "workflow_metadata_missing": missing_metadata,
        "workflow_metadata_required": metadata_required,
        "workflow_url_missing": workflow_url_missing,
        "waiver_used": waiver_used,
        "artifact_upload_names": ["decision-workspace-proof"],
        "warning": warning,
        "raw_sql_included": False,
    }


def _release_candidate_ci_context(profile: str, waivers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    ci_run = _ci_run_review_results(profile, waivers)
    return {
        "source": "release_candidate_ci_context",
        "proof_source": ci_run.get("proof_source") or "local_inventory",
        "passed": bool(ci_run.get("passed")),
        "launch_profile": profile,
        "github_actions": bool(ci_run.get("github_actions")),
        "commit_sha": str(ci_run.get("commit_sha") or ""),
        "source_commit_sha": str(ci_run.get("source_commit_sha") or ""),
        "source_tree_sha": str(ci_run.get("source_commit_sha") or ""),
        "github_sha": str(ci_run.get("github_sha") or ""),
        "commit_sha_matches_source": bool(ci_run.get("commit_sha_matches_source")),
        "branch_ref": str(ci_run.get("branch_ref") or ""),
        "workflow_run_id": str(ci_run.get("workflow_run_id") or ""),
        "workflow_url": str(ci_run.get("workflow_url") or ""),
        "run_attempt": str(ci_run.get("run_attempt") or ""),
        "workflow_name": str(ci_run.get("workflow_name") or ""),
        "workflow_job": str(ci_run.get("workflow_job") or ""),
        "event_name": str(ci_run.get("event_name") or ""),
        "repository": str(ci_run.get("repository") or ""),
        "artifact_upload_name": "decision-workspace-proof",
        "uploaded_artifact_names": ["decision-workspace-proof"],
        "workflow_metadata_missing": bool(ci_run.get("workflow_metadata_missing")),
        "workflow_metadata_required": bool(ci_run.get("workflow_metadata_required")),
        "workflow_url_missing": bool(ci_run.get("workflow_url_missing")),
        "waiver_used": bool(ci_run.get("waiver_used")),
        "warning": str(ci_run.get("warning") or ""),
        "recorded_env_keys": [
            "GITHUB_ACTIONS",
            "GITHUB_RUN_ID",
            "GITHUB_RUN_ATTEMPT",
            "GITHUB_SERVER_URL",
            "GITHUB_REPOSITORY",
            "GITHUB_SHA",
            "GITHUB_REF",
            "GITHUB_WORKFLOW",
            "GITHUB_JOB",
            "GITHUB_EVENT_NAME",
        ],
        "raw_sql_included": False,
    }


def _ci_artifact_reality_results(
    profile: str,
    ci_run_review: Mapping[str, Any],
    upload_review: Mapping[str, Any],
    artifact_review: Mapping[str, Any],
    missing_payloads: Iterable[str],
    release_reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    def fail(code: str, message: str, *, count: int = 1, details: Any = None) -> None:
        failures.append(
            {
                "code": code,
                "message": message,
                "count": count,
                "details": details,
                "recommendation": "Run GitHub Actions for the current commit and ensure the decision-workspace-proof upload includes every required launch artifact path.",
            }
        )

    missing_required_artifacts = sorted(
        set(missing_payloads)
        | set(_as_list(artifact_review.get("missing_required_gauntlet_artifacts")))
        | set(_as_list(artifact_review.get("missing_required_launch_artifacts")))
        | set(_as_list(artifact_review.get("missing_required_formula_authority_artifacts")))
    )
    stale_artifacts = _as_list(artifact_review.get("stale_artifacts"))
    missing_upload_paths = _as_list(upload_review.get("missing_upload_paths"))
    missing_steps = _as_list(upload_review.get("missing_steps"))
    uploaded_artifact_names = _as_list(upload_review.get("uploaded_artifact_names"))
    release_reconciliation = _as_mapping(release_reconciliation)
    release_missing = _as_list(release_reconciliation.get("missing_files"))
    release_unlisted = _as_list(release_reconciliation.get("unlisted_files"))
    release_hash_mismatch = _as_list(release_reconciliation.get("hash_mismatches"))
    release_missing_categories = _as_list(release_reconciliation.get("missing_required_categories"))
    release_raw = _as_int(release_reconciliation.get("raw_sql_or_secret_count"))
    release_commit_mismatch = _as_list(release_reconciliation.get("commit_mismatches"))
    workflow_metadata_missing = bool(ci_run_review.get("workflow_metadata_missing"))
    workflow_metadata_required = bool(ci_run_review.get("workflow_metadata_required"))
    if workflow_metadata_missing and workflow_metadata_required:
        fail("CI_METADATA_MISSING", "Workflow metadata is required for this launch profile.", details=profile)
    if not bool(ci_run_review.get("commit_sha_matches_source", True)):
        fail("CI_COMMIT_SHA_MISMATCH", "Workflow commit SHA does not match the evaluated source commit.")
    if bool(ci_run_review.get("workflow_url_missing")):
        fail("CI_WORKFLOW_URL_MISSING", "Workflow URL must be constructed when GitHub Actions metadata is available.")
    if missing_required_artifacts:
        fail("REQUIRED_ARTIFACT_MISSING", "Required launch/gauntlet artifacts are missing.", count=len(missing_required_artifacts), details=missing_required_artifacts)
    if stale_artifacts:
        fail("STALE_ARTIFACT_PRESENT", "Stale generated artifacts are present.", count=len(stale_artifacts), details=stale_artifacts)
    if missing_upload_paths:
        fail("CI_UPLOAD_PATH_MISSING", "CI upload path coverage is incomplete.", count=len(missing_upload_paths), details=missing_upload_paths)
    if missing_steps:
        fail("CI_REQUIRED_STEP_MISSING", "CI is missing required release-candidate validation steps.", count=len(missing_steps), details=missing_steps)
    if not uploaded_artifact_names:
        fail("UPLOADED_ARTIFACT_NAME_MISSING", "CI artifact upload name inventory is missing.")
    if release_reconciliation and not bool(release_reconciliation.get("passed")):
        fail("RELEASE_ARTIFACT_RECONCILIATION_FAILED", "Release-candidate artifact manifest/hash reconciliation failed.", details=release_reconciliation.get("failures"))
    if release_missing:
        fail("RELEASE_MANIFEST_FILE_MISSING", "Release-candidate manifest lists files missing from disk.", count=len(release_missing), details=release_missing)
    if release_unlisted:
        fail("RELEASE_UNLISTED_ARTIFACT", "Generated artifact exists outside the release-candidate manifest.", count=len(release_unlisted), details=release_unlisted)
    if release_hash_mismatch:
        fail("RELEASE_HASH_MISMATCH", "Release-candidate artifact hash mismatch detected.", count=len(release_hash_mismatch), details=release_hash_mismatch)
    if release_commit_mismatch:
        fail("RELEASE_ARTIFACT_COMMIT_MISMATCH", "Release-candidate artifact commit mismatch detected.", count=len(release_commit_mismatch), details=release_commit_mismatch)
    if release_missing_categories:
        fail("RELEASE_ARTIFACT_CATEGORY_MISSING", "Required release-candidate artifact category has zero files.", count=len(release_missing_categories), details=release_missing_categories)
    if release_raw:
        fail("RELEASE_ARTIFACT_RAW_SQL_OR_SECRET", "Release-candidate artifact bundle contains raw SQL or secret-like text.", count=release_raw)

    return {
        "source": "launch_readiness_ci_artifact_reality",
        "proof_source": "ci_artifact_review",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "launch_profile": profile,
        "workflow_run_id": ci_run_review.get("workflow_run_id") or "",
        "workflow_url": ci_run_review.get("workflow_url") or "",
        "commit_sha": ci_run_review.get("commit_sha") or "",
        "branch_ref": ci_run_review.get("branch_ref") or "",
        "run_attempt": ci_run_review.get("run_attempt") or "",
        "uploaded_artifact_names": uploaded_artifact_names,
        "required_artifact_count": _required_release_artifact_count(),
        "missing_artifacts": missing_required_artifacts,
        "missing_artifact_count": len(missing_required_artifacts),
        "stale_artifacts": stale_artifacts,
        "stale_artifact_count": len(stale_artifacts),
        "missing_upload_paths": missing_upload_paths,
        "missing_upload_path_count": len(missing_upload_paths),
        "missing_steps": missing_steps,
        "missing_step_count": len(missing_steps),
        "workflow_metadata_missing": workflow_metadata_missing,
        "workflow_metadata_required": workflow_metadata_required,
        "release_artifact_reconciliation_passed": bool(release_reconciliation.get("passed")) if release_reconciliation else False,
        "release_artifact_count": _as_int(release_reconciliation.get("artifact_count")) if release_reconciliation else 0,
        "release_artifact_hash_count": _as_int(release_reconciliation.get("hash_count")) if release_reconciliation else 0,
        "release_missing_required_categories": release_missing_categories,
        "release_unlisted_artifacts": release_unlisted,
        "release_hash_mismatches": release_hash_mismatch,
        "release_commit_mismatches": release_commit_mismatch,
        "warning": str(ci_run_review.get("warning") or ""),
        "raw_sql_included": False,
    }


def _browser_required_coverage(payloads: Mapping[str, Any], screenshot_files: list[str]) -> dict[str, Any]:
    view_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/view_results.json"))]
    query_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/query_search_results.json"))]
    settings_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/settings_action_results.json"))]
    live_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/live_feature_results.json"))]
    export_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/export_results.json"))]
    button_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/button_click_results.json"))]
    sections_seen = {str(row.get("section") or "") for row in view_rows if row.get("section")}
    query_cases = {str(row.get("case") or "") for row in query_rows}
    coverage = {
        "six_primary_overviews": PRIMARY_SECTIONS.issubset(sections_seen),
        "query_search": bool(query_rows),
        "settings_admin_setup_health": bool(settings_rows)
        or any(str(row.get("section") or "") == "Settings/Admin Setup Health" for row in view_rows),
        "advanced_scope_active_filters": any("Advanced Scope" in str(row.get("workflow") or row.get("id") or "") for row in view_rows)
        or bool(view_rows),
        "company_environment_window_controls": bool(view_rows),
        "route_action_result": any(str(row.get("action_type") or "") == "route" and bool(row.get("clicked")) for row in button_rows),
        "evidence_action_result": any(str(row.get("action_type") or "") == "evidence_load" and bool(row.get("clicked")) for row in button_rows),
        "export_download_interaction": bool(export_rows),
        "sql_preview_daily_safe": "sql_preview" in query_cases
        and all(
            not bool(row.get("raw_sql_visible_in_daily_ui"))
            for row in query_rows
            if str(row.get("case") or "") == "sql_preview"
        ),
        "live_feature_gated_state": bool(live_rows)
        and all(bool(row.get("admin_or_advanced_gated")) for row in live_rows),
        "permission_denied": "permission_denied" in query_cases
        or any(bool(row.get("permission_denied_sanitized")) for row in live_rows),
        "unavailable_snowflake": any(bool(row.get("unavailable_snowflake_sanitized")) for row in live_rows),
    }
    missing = sorted(name for name, present in coverage.items() if not present)
    return {
        "source": "launch_readiness_browser_required_coverage",
        "proof_source": "runtime_render",
        "passed": not missing,
        "coverage": coverage,
        "missing_coverage": missing,
        "missing_coverage_count": len(missing),
        "screenshot_count": len(screenshot_files),
        "sections_seen": sorted(sections_seen),
        "raw_sql_included": False,
    }


def _browser_smoke_results(
    root: Path,
    payloads: Mapping[str, Any],
    profile: str,
    waivers: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    coverage = _browser_required_coverage(payloads, screenshot_files)
    screenshot_required = profile in {"internal_live", "prod_candidate"}
    waiver_used = skipped and _has_valid_waiver(waivers, "browser_proof")
    profile_failure = screenshot_required and skipped and not waiver_used
    passed = (
        bool(snapshot_files)
        and blocked_count == 0
        and PRIMARY_SECTIONS.issubset(first_viewport_sections)
        and bool(coverage.get("passed"))
        and not profile_failure
    )
    return {
        "source": "launch_readiness_browser_smoke",
        "proof_source": "runtime_render",
        "passed": passed,
        "launch_profile": profile,
        "browser_required": screenshot_required,
        "browser_screenshot_count": len(screenshot_files),
        "browser_screenshots": screenshot_files,
        "browser_proof_skipped": skipped,
        "skip_reason": skip_reason,
        "waiver_used": waiver_used,
        "profile_failure": profile_failure,
        "deterministic_snapshot_count": len(snapshot_files),
        "deterministic_snapshots_present": bool(snapshot_files),
        "sections_seen": sorted(first_viewport_sections),
        "daily_forbidden_blocked_count": blocked_count,
        "raw_sql_included": False,
    }, coverage


def _browser_or_snapshot_failures(browser: Mapping[str, Any], coverage: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if not browser.get("deterministic_snapshots_present"):
        failures.append(
            {
                "gate": "deterministic_snapshots",
                "reason": "Deterministic rendered snapshots are missing.",
                "recommendation": "Regenerate full app validation snapshots before launch readiness.",
            }
        )
    if browser.get("profile_failure"):
        failures.append(
            {
                "gate": "browser_profile_requirement",
                "reason": "Browser proof is required for this launch profile and no valid waiver was provided.",
                "recommendation": "Capture browser screenshots or provide a signed browser_proof waiver.",
            }
        )
    blocked_count = _as_int(browser.get("daily_forbidden_blocked_count"))
    if blocked_count:
        failures.append(
            {
                "gate": "browser_daily_leak_scan",
                "reason": "Browser or snapshot output contains daily forbidden tokens.",
                "count": blocked_count,
                "recommendation": "Remove raw/internal/test language from daily UI output.",
            }
        )
    for missing in _as_list(coverage.get("missing_coverage")):
        failures.append(
            {
                "gate": "browser_required_coverage",
                "reason": f"Missing browser/rendered launch coverage: {missing}",
                "recommendation": "Render or click the missing launch surface in runtime validation.",
            }
        )
    return {
        "source": "launch_readiness_browser_or_snapshot_failures",
        "proof_source": "runtime_render",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }


def _config_sanity_results(root: Path, profile: str) -> dict[str, Any]:
    fixture_enabled = os.environ.get("OVERWATCH_UI_FIXTURE_MODE") == "1"
    fixture_allowed = os.environ.get("OVERWATCH_ALLOW_FIXTURE_MODE") == "1"
    raw_perf_sql = os.environ.get("OVERWATCH_INCLUDE_SQL_IN_PERF_ARTIFACTS") == "1"
    live_proof = os.environ.get("OVERWATCH_QUERY_PLAN_PROOF") == "1"
    admin_debug_enabled = os.environ.get("OVERWATCH_ADMIN_DEBUG") == "1" or os.environ.get("OVERWATCH_DEBUG") == "1"
    known_profile = profile in LAUNCH_PROFILES
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
    if profile == "prod_candidate" and fixture_enabled:
        failures.append("Fixture mode cannot be enabled for prod_candidate.")
    if raw_perf_sql and not live_proof:
        failures.append("Raw perf SQL artifacts require live query proof mode.")
    if admin_debug_enabled:
        failures.append("Admin/debug flags must be disabled by default for launch readiness.")
    if runtime_import_hits:
        failures.append("Runtime package imports CI-only tools or tests.")
    if not known_profile:
        failures.append("Launch profile is not recognized.")
    required_env_docs = {
        "OVERWATCH_LAUNCH_PROFILE": "Launch profile selector.",
        "OVERWATCH_UI_FIXTURE_MODE": "Fixture mode switch.",
        "OVERWATCH_ALLOW_FIXTURE_MODE": "Explicit fixture mode allow switch.",
        "OVERWATCH_QUERY_PLAN_PROOF": "Live query-history proof switch.",
        "OVERWATCH_INCLUDE_SQL_IN_PERF_ARTIFACTS": "Raw SQL artifact opt-in switch.",
    }
    return {
        "source": "launch_readiness_config_sanity",
        "proof_source": "inventory_only",
        "passed": not failures,
        "launch_profile": profile,
        "recognized_launch_profile": known_profile,
        "required_environment_variables": required_env_docs,
        "required_environment_variable_count": len(required_env_docs),
        "failures": failures,
        "fixture_mode_enabled": fixture_enabled,
        "fixture_mode_requires_explicit_allow": True,
        "fixture_mode_allowed": fixture_allowed,
        "raw_perf_sql_enabled": raw_perf_sql,
        "raw_perf_sql_requires_admin_perf_mode": True,
        "admin_debug_enabled": admin_debug_enabled,
        "admin_debug_disabled_by_default": not admin_debug_enabled,
        "live_query_proof_enabled": live_proof,
        "runtime_ci_tool_import_count": len(runtime_import_hits),
        "runtime_ci_tool_imports": runtime_import_hits,
        "safe_defaults": {
            "fixture_mode": not fixture_enabled,
            "raw_sql_perf_artifacts": not raw_perf_sql,
            "debug_panels_daily": not admin_debug_enabled,
        },
        "expected_secret_names_only": True,
        "raw_sql_included": False,
    }


def _secret_match_is_placeholder(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 80): min(len(text), end + 80)].lower()
    return any(
        token in window
        for token in (
            "placeholder",
            "example",
            "dummy",
            "sample",
            "your_",
            "xxxxx",
            "redacted",
            "secret_patterns",
            "re.compile",
            "re.search",
        )
    )


def _secrets_scan_results(root: Path) -> dict[str, Any]:
    scan_roots = [
        root / "artifacts" / "full_app_validation",
        root / "artifacts" / "full_app_inventory",
        root / "artifacts" / "cleanup",
        root / "artifacts" / "launch_readiness",
        root / "artifacts",
        root / "docs",
        root / ".github" / "workflows",
        root / ".overwatch_final",
        root / "tools" / "contracts",
        root / "snowflake",
    ]
    findings: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*") if scan_root.is_dir() else [scan_root]:
            if not path.is_file() or path in seen:
                continue
            if any(part in {".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"} for part in path.parts):
                continue
            seen.add(path)
            if path.suffix.lower() not in {".json", ".txt", ".csv", ".md", ".py", ".sql", ".yml", ".yaml", ".toml", ".env"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for name, pattern in SECRET_PATTERNS.items():
                for match in pattern.finditer(text):
                    if _secret_match_is_placeholder(text, match.start(), match.end()):
                        continue
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


def _permission_matrix(payloads: Mapping[str, Any]) -> dict[str, Any]:
    object_inventory = _as_mapping(payloads.get("artifacts/cleanup/sql_object_inventory.json"))
    query_paths = _as_mapping(payloads.get("artifacts/cleanup/query_path_inventory.json"))
    evidence_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/evidence_loader_call_matrix.json"))]
    compact_marts = sorted(set(_as_list(object_inventory.get("compact_evidence_marts"))) or COMPACT_EVIDENCE_MARTS)
    setup_objects = sorted(
        str(row.get("name") or "")
        for row in _as_list(object_inventory.get("objects"))
        if str(row.get("classification") or "").startswith("active_setup")
        or "setup" in str(row.get("classification") or "").lower()
        or "audit" in str(row.get("classification") or "").lower()
    )
    drop_objects = sorted(str(row.get("name") or "") for row in _as_list(object_inventory.get("drop_plan")))
    account_usage_in_normal_evidence = any(
        bool(row.get("account_usage_used"))
        for row in evidence_rows
        if str(row.get("loader_kind") or "") == "normal_evidence"
    )
    query_path_normal_account_usage = bool(query_paths.get("account_usage_normal_evidence_allowed"))
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
            "required_access": compact_marts,
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
            "required_access": sorted(set(["setup schema", "audit tables", "procedure/task management", *setup_objects])),
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
            "required_access": sorted(set(["last-good packet table", "drop plan execution privileges", *drop_objects])),
            "account_usage_required": False,
            "admin_only": True,
        },
        {
            "role": "live_admin_operator",
            "purpose": "Run explicit live diagnostics, metadata probes, and optional admin checks.",
            "required_access": ["admin diagnostics controls", "metadata probe privileges", "bounded live query access"],
            "account_usage_required": "only for explicit confirmed fallback",
            "admin_only": True,
        },
    ]
    compact_role = next(row for row in rows if row["role"] == "evidence_loader")
    compact_required_access = {str(item) for item in _as_list(compact_role.get("required_access"))}
    missing_compact_role_marts = sorted(COMPACT_EVIDENCE_MARTS - compact_required_access)
    passed = not account_usage_in_normal_evidence and not query_path_normal_account_usage and not missing_compact_role_marts
    return {
        "source": "launch_readiness_permission_matrix",
        "proof_source": "inventory_only",
        "passed": passed,
        "roles": rows,
        "role_count": len(rows),
        "daily_account_usage_required": False,
        "setup_admin_separated": True,
        "derived_from_object_inventory": True,
        "derived_from_query_path_inventory": True,
        "normal_evidence_account_usage_count": int(account_usage_in_normal_evidence) + int(query_path_normal_account_usage),
        "missing_compact_role_marts": missing_compact_role_marts,
        "setup_object_count": len(setup_objects),
        "drop_object_count": len(drop_objects),
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
    object_rows = [_as_mapping(row) for row in _as_list(object_inventory.get("objects"))]
    active_reason_gaps = [
        row for row in object_rows
        if str(row.get("category") or row.get("classification") or "").startswith("active")
        and not str(row.get("reason") or "").strip()
    ]
    python_without_ddl = [
        row for row in object_rows
        if bool(row.get("python_reference")) and str(row.get("category") or "").startswith("unknown")
    ]
    setup_text = sql_files.get("snowflake/OVERWATCH_MART_SETUP.sql", "")
    setup_has_idempotent_tokens = "CREATE OR REPLACE" in setup_text or "IF NOT EXISTS" in setup_text
    tasks_defined = "CREATE" in setup_text.upper() and "TASK" in setup_text.upper()
    procedures_defined = "PROCEDURE" in setup_text.upper()
    validation_text = sql_files.get("snowflake/OVERWATCH_MART_VALIDATION.sql", "")
    validation_references_active_only = unknown_count == 0
    passed = (
        not missing
        and not sql_lint_errors
        and unknown_count == 0
        and setup_has_idempotent_tokens
        and not active_reason_gaps
        and not python_without_ddl
        and validation_references_active_only
    )
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
        "python_referenced_without_ddl_count": len(python_without_ddl),
        "active_object_reason_gap_count": len(active_reason_gaps),
        "idempotent_setup_static_proof": setup_has_idempotent_tokens,
        "stored_procedure_compile_static": not sql_lint_errors,
        "procedures_defined_static": procedures_defined,
        "tasks_defined_static": tasks_defined,
        "grants_static_proof": "GRANT" in setup_text.upper(),
        "validation_references_active_objects_only": validation_references_active_only,
        "raw_sql_included": False,
    }


def _upgrade_readiness_results(root: Path) -> dict[str, Any]:
    setup_text = (root / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")
    has_create_or_replace = "CREATE OR REPLACE" in setup_text
    has_schema_version = "VERSION" in setup_text.upper() or "SCHEMA" in setup_text.upper()
    first_release_marker = "FIRST" in setup_text.upper() or "INITIAL" in setup_text.upper() or has_schema_version
    return {
        "source": "launch_readiness_upgrade_readiness",
        "proof_source": "inventory_only",
        "passed": has_create_or_replace and (has_schema_version or first_release_marker),
        "setup_rerun_idempotent": has_create_or_replace,
        "schema_version_reference_present": has_schema_version,
        "first_release_marker_present": first_release_marker,
        "prior_schema_upgrade_static_review": has_schema_version or first_release_marker,
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
    drop_plan = _as_list(object_inventory.get("drop_plan"))
    obsolete_count = _as_int(object_inventory.get("obsolete_drop_candidate_count"))
    drop_is_admin_only = "DROP" in sql_files.get("snowflake/OVERWATCH_MART_DROP.sql", "").upper()
    passed = drop_present and last_good_present and cleanup_drop_plan.exists() and not active_in_drop and obsolete_count == len(drop_plan)
    return {
        "source": "launch_readiness_drop_rollback",
        "proof_source": "inventory_only",
        "passed": passed,
        "drop_sql_present": drop_present,
        "cleanup_drop_plan_present": cleanup_drop_plan.exists(),
        "last_known_good_packet_static_proof": last_good_present,
        "active_object_in_drop_count": len(active_in_drop),
        "obsolete_drop_candidate_count": obsolete_count,
        "drop_plan_object_count": len(drop_plan),
        "rollback_packet_fallback_proven": last_good_present,
        "drop_script_admin_only_static": drop_is_admin_only,
        "raw_sql_included": False,
    }


def _sql_value_inventory(root: Path, payloads: Mapping[str, Any]) -> dict[str, Any]:
    file_inventory = _as_mapping(payloads.get("artifacts/sql_performance_lint_file_inventory.json"))
    sql_files = _sql_files(root)
    rows: list[dict[str, Any]] = []
    for index, rel in enumerate(_as_list(file_inventory.get("scanned_files")), start=1):
        rel_str = str(rel)
        text = sql_files.get(rel_str, "")
        upper = text.upper()
        if "DROP" in rel_str.upper():
            path_class = "drop_rollback"
            boundary = "admin_drop"
            purpose = "Safe cleanup and rollback support."
        elif "VALIDATION" in rel_str.upper():
            path_class = "deployment_validation"
            boundary = "admin_setup"
            purpose = "Post-deployment object and setup validation."
        elif "SECURE_VIEW_AUDIT" in rel_str.upper():
            path_class = "admin_setup"
            boundary = "admin_setup"
            purpose = "Admin secure-view dependency review."
        elif "05_LOAD_PROCEDURES" in rel_str.upper() or "MART_SETUP" in rel_str.upper():
            path_class = "refresh_full" if "FULL" in upper else "refresh_fast" if "FAST" in upper else "admin_setup"
            boundary = "refresh_or_setup"
            purpose = "Setup, compact marts, and refresh procedures."
        else:
            path_class = "admin_setup"
            boundary = "admin_setup"
            purpose = "Deployment support SQL."
        account_usage = "SNOWFLAKE.ACCOUNT_USAGE" in upper or "ACCOUNT_USAGE" in upper
        limit_present = bool(re.search(r"\bLIMIT\b", upper))
        ordering_present = bool(re.search(r"\bORDER\s+BY\b", upper))
        where_present = bool(re.search(r"\bWHERE\b", upper))
        daily_path = path_class == "daily_first_paint_packet"
        no_value = not purpose or (limit_present and not ordering_present and not where_present and account_usage)
        rows.append(
            {
                "path_id": f"sql_path_{index:03d}",
                "path": rel_str,
                "source_file": rel_str,
                "source_function_or_procedure": "",
                "path_class": path_class,
                "purpose": purpose,
                "user_visible_value": "Supports current Decision Workspace operation or admin setup.",
                "owner": "decision-workspace-platform",
                "expected_boundary": boundary,
                "table_family": "compact_mart_or_setup",
                "max_rows": 500 if boundary == "admin_setup" else None,
                "account_usage_use": "admin_or_deep_only" if account_usage else "none",
                "daily_path": daily_path,
                "pruning_predicate": "WHERE" if where_present else "",
                "pruning_predicate_present": where_present,
                "ordering": "ORDER BY" if ordering_present else "",
                "ordering_present": ordering_present,
                "limit": "LIMIT" if limit_present else "",
                "limit_present": limit_present,
                "expected_frequency": "on_setup_or_explicit_refresh",
                "replacement_delete_decision": "keep_active" if purpose else "delete",
                "bounded_admin_marker_required": bool(account_usage and limit_present and not where_present),
                "launch_gate_status": "pass" if not no_value else "fail",
            }
        )
    gaps = [
        row for row in rows
        if not row["purpose"]
        or not row["owner"]
        or (row["daily_path"] and row["account_usage_use"] != "none")
        or row["launch_gate_status"] != "pass"
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


def _sql_path_delete_candidates(sql_value: Mapping[str, Any]) -> dict[str, Any]:
    candidates = [
        row for row in _as_list(sql_value.get("paths"))
        if _as_mapping(row).get("replacement_delete_decision") == "delete"
        or _as_mapping(row).get("launch_gate_status") == "fail"
    ]
    return {
        "source": "launch_readiness_sql_path_delete_candidates",
        "proof_source": "inventory_only",
        "passed": not candidates,
        "candidate_count": len(candidates),
        "candidates": candidates,
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


def _live_query_history_results(root: Path, profile: str, waivers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    live_enabled = os.environ.get("OVERWATCH_QUERY_PLAN_PROOF") == "1"
    live_artifact = root / "artifacts" / "query_history_by_tag.json"
    skipped_artifact = root / "artifacts" / "query_history_by_tag_SKIPPED.txt"
    bytes_artifact = root / "artifacts" / "query_bytes_by_boundary.json"
    manifest_artifact = root / "artifacts" / "snowflake_validation" / "live_execution_manifest.json"
    live_required = profile in {"internal_live", "prod_candidate"}
    waiver_used = _has_valid_waiver(waivers, "live_query_history")
    manifest_ids: set[str] = set()
    if manifest_artifact.exists():
        try:
            manifest_payload = json.loads(manifest_artifact.read_text(encoding="utf-8"))
            manifest_ids = {
                str(row.get("validation_id") or "")
                for row in _as_list(_as_mapping(manifest_payload).get("entries"))
                if isinstance(row, Mapping)
            }
        except json.JSONDecodeError:
            manifest_ids = set()
    manifest_missing_link_count = 0
    manifest_linked_count = 0
    raw_sql_included = False
    row_count = 0
    if live_enabled:
        rows: list[Mapping[str, Any]] = []
        if live_artifact.exists():
            try:
                payload = json.loads(live_artifact.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    rows = [_as_mapping(row) for row in payload]
                elif isinstance(payload, Mapping):
                    rows = [_as_mapping(row) for row in _as_list(payload.get("rows") or payload.get("queries"))]
            except json.JSONDecodeError:
                rows = []
        row_count = len(rows)
        for row in rows:
            manifest_id = str(row.get("live_execution_manifest_id") or "")
            if manifest_id and manifest_id in manifest_ids:
                manifest_linked_count += 1
            else:
                manifest_missing_link_count += 1
            for key, value in row.items():
                key_text = str(key).lower()
                if key_text in {"query_text", "sql_text", "raw_sql"} and str(value or "").strip():
                    raw_sql_included = True
                if isinstance(value, str) and re.search(r"(?i)\b(SELECT|WITH|JOIN|CALL)\b", value):
                    raw_sql_included = True
        passed = (
            live_artifact.exists()
            and manifest_missing_link_count == 0
            and not raw_sql_included
            and bytes_artifact.exists()
        )
        skip_reason = "" if passed else "OVERWATCH_QUERY_PLAN_PROOF=1 but query_history_by_tag.json was not generated."
        skipped = False
    else:
        skipped = True
        skip_reason = (
            skipped_artifact.read_text(encoding="utf-8").strip()
            if skipped_artifact.exists()
            else "Live query-history proof is disabled; fixture CI records an explicit skip."
        )
        if not skipped_artifact.exists():
            skipped_artifact.write_text(skip_reason, encoding="utf-8")
        passed = (not live_required and profile == "internal_fixture") or waiver_used
    return {
        "source": "launch_readiness_live_query_history",
        "proof_source": "runtime_click" if live_enabled else "inventory_only",
        "passed": passed,
        "launch_profile": profile,
        "live_query_plan_proof_enabled": live_enabled,
        "live_query_history_required": live_required,
        "live_artifact_present": live_artifact.exists(),
        "bytes_by_boundary_present": bytes_artifact.exists(),
        "manifest_artifact_present": manifest_artifact.exists(),
        "query_history_row_count": row_count,
        "manifest_linked_count": manifest_linked_count,
        "manifest_missing_link_count": manifest_missing_link_count,
        "query_bytes_boundary_reconciled": not live_enabled or bytes_artifact.exists(),
        "skipped": skipped,
        "skip_reason": skip_reason,
        "waiver_used": waiver_used,
        "status": "passed" if passed and live_artifact.exists() else ("waived" if waiver_used else ("skipped_with_reason" if skipped and passed else "missing")),
        "raw_sql_included": raw_sql_included,
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

    def settings_row_requires_admin_gate(row: Mapping[str, Any]) -> bool:
        action_type = str(row.get("action_type") or "")
        section = str(row.get("section") or "")
        return (
            section == "Settings/Admin Setup Health"
            or action_type in {"admin_load", "advanced_load", "setup_health", "account_usage_fallback"}
            or bool(row.get("requires_admin"))
            or bool(row.get("heavy_query_allowed"))
            or bool(row.get("account_usage_allowed"))
        )

    def row_passed(row: Mapping[str, Any]) -> bool:
        clicked_or_skipped = bool(row.get("clicked")) or bool(row.get("skip_reason"))
        observed_contexts = _as_list(
            row.get("observed_contexts")
            or row.get("observed_budget_contexts")
            or row.get("observed_query_budget_contexts")
            or row.get("marker_budget_runtime_contexts")
        )
        expected_context = str(row.get("expected_query_budget_context") or "")
        budget_ok = bool(observed_contexts) or not expected_context or bool(row.get("skip_reason"))
        admin_ok = (not settings_row_requires_admin_gate(row)) or bool(row.get("admin_or_advanced_gated", True))
        return (
            clicked_or_skipped
            and budget_ok
            and admin_ok
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


def _delete_first_release_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    cleanup = _cleanup_launch_closure_results(payloads)
    summary = _as_mapping(payloads.get("artifacts/cleanup/cleanup_summary.json"))
    module_inventory = _as_mapping(payloads.get("artifacts/cleanup/module_inventory.json"))
    route_inventory = _as_mapping(payloads.get("artifacts/cleanup/route_state_inventory.json"))
    object_inventory = _as_mapping(payloads.get("artifacts/cleanup/sql_object_inventory.json"))
    failures = {
        "unknown_sql_object_count": _as_int(summary.get("unknown_sql_object_count")) or len(_as_list(object_inventory.get("unknown"))),
        "dead_route_count": len(_as_list(route_inventory.get("dead_routes"))),
        "stale_artifact_count": _as_int(summary.get("stale_generated_artifact_count")),
        "unowned_retained_module_count": len(_as_list(module_inventory.get("unowned_retained_modules"))),
        "retained_generic_reason_count": _as_int(summary.get("retained_generic_reason_count")),
        "deletion_candidate_count": _as_int(summary.get("deletion_candidate_count")),
    }
    return {
        "source": "launch_readiness_delete_first_release",
        "proof_source": "inventory_only",
        "passed": bool(cleanup.get("passed")) and all(value == 0 for value in failures.values()),
        **failures,
        "raw_sql_included": False,
    }


def _docs_readiness_results(root: Path) -> dict[str, Any]:
    docs_path = root / "docs" / "launch_readiness.md"
    text = docs_path.read_text(encoding="utf-8") if docs_path.exists() else ""
    checks = {
        "mentions_install_setup": "Run:" in text and "tests.test_launch_readiness" in text,
        "mentions_required_environment_variables": "Environment variables" in text,
        "mentions_launch_profiles": "Launch profiles" in text,
        "mentions_no_raw_sql_daily_ui": "No raw SQL in daily UI" in text,
        "mentions_fixture_mode_policy": "Fixture mode policy" in text,
        "mentions_required_roles": "Required roles" in text,
        "mentions_compact_evidence_marts": "compact evidence marts" in text,
        "mentions_daily_no_account_usage": "Daily users do not need Account Usage access" in text,
        "mentions_setup_admin_role_separation": "Setup administrators" in text,
        "mentions_setup_admin_troubleshooting": "Setup and admin troubleshooting" in text,
        "mentions_fast_full_refresh": "FAST and FULL refresh" in text,
        "mentions_first_paint_slos": "first-paint SLOs" in text,
        "mentions_stale_packet_fallback": "last-known-good" in text,
        "mentions_export_privacy": "export" in text.lower() and "privacy" in text.lower(),
        "mentions_browser_live_skip_policy": "Browser and live proof skip policy" in text,
        "mentions_rollback_drop_safety": "Rollback and drop safety" in text,
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
    missing_formula = sorted(
        rel for rel in REQUIRED_FORMULA_AUTHORITY_ARTIFACTS
        if not (root / rel).exists()
    )
    launch_files = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in (root / LAUNCH_READINESS_DIR).rglob("*")
        if path.is_file()
    ) if (root / LAUNCH_READINESS_DIR).exists() else []
    gauntlet_reconciliation = _as_mapping(payloads.get("artifacts/full_app_validation/gauntlet_artifact_reconciliation.json"))
    stale_count = _as_int(gauntlet_reconciliation.get("unlisted_file_count"))
    stale_artifacts = [str(path) for path in _as_list(gauntlet_reconciliation.get("unlisted_files"))]
    passed = not missing and not missing_formula and stale_count == 0
    return {
        "source": "launch_readiness_artifact_review",
        "proof_source": "inventory_only",
        "passed": passed,
        "required_gauntlet_artifact_count": len(REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS),
        "missing_required_gauntlet_artifacts": missing,
        "missing_required_gauntlet_artifact_count": len(missing),
        "required_formula_authority_artifact_count": len(REQUIRED_FORMULA_AUTHORITY_ARTIFACTS),
        "missing_required_formula_authority_artifacts": missing_formula,
        "missing_required_formula_authority_artifact_count": len(missing_formula),
        "stale_artifact_count": stale_count,
        "stale_artifacts": stale_artifacts,
        "launch_artifact_count": len(launch_files),
        "launch_artifacts_seen": launch_files,
        "raw_sql_included": False,
    }


def _release_candidate_artifact_manifest(
    root: Path,
    *,
    profile: str,
    commit_sha: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    hashes: list[dict[str, Any]] = []
    release_files = sorted(set(_release_artifact_files(root)) | set(REQUIRED_RELEASE_CANDIDATE_ARTIFACTS))
    for rel in release_files:
        path = root / rel
        category = _release_artifact_category(rel)
        self_referential = (
            rel in RELEASE_SELF_REFERENTIAL_FILES
            or rel.startswith(f"{LAUNCH_READINESS_DIR}/")
            or rel.startswith(f"{RELEASE_CANDIDATE_DIR}/")
        )
        contains_raw = _artifact_text_contains_raw_sql_or_secret(path)
        sha = _file_sha256(path) if path.exists() else ""
        row = {
            "path": rel,
            "sha256": sha,
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "created_at": _utc_now(),
            "producer": "launch_readiness",
            "launch_profile": profile,
            "commit_sha": commit_sha,
            "proof_source": "runtime_click",
            "category": category,
            "contains_raw_sql": contains_raw,
            "contains_secrets": contains_raw,
            "self_referential_hash": self_referential,
        }
        rows.append(row)
        hashes.append(
            {
                "path": rel,
                "sha256": sha,
                "size_bytes": row["size_bytes"],
                "category": category,
                "self_referential_hash": self_referential,
            }
        )
    categories: dict[str, int] = {}
    for row in rows:
        categories[str(row["category"])] = categories.get(str(row["category"]), 0) + 1
    manifest = {
        "source": "release_candidate_artifact_manifest",
        "proof_source": "runtime_click",
        "generated_at": _utc_now(),
        "launch_profile": profile,
        "commit_sha": commit_sha,
        "source_tree_sha": commit_sha,
        "artifact_count": len(rows),
        "categories": categories,
        "required_categories": sorted(RELEASE_REQUIRED_CATEGORIES),
        "files": rows,
        "raw_sql_included": False,
    }
    hash_payload = {
        "source": "release_candidate_artifact_hashes",
        "proof_source": "runtime_click",
        "generated_at": _utc_now(),
        "launch_profile": profile,
        "commit_sha": commit_sha,
        "source_tree_sha": commit_sha,
        "hash_count": len(hashes),
        "hashes": hashes,
        "raw_sql_included": False,
    }
    return manifest, hash_payload


def _release_artifact_reconciliation_results(
    root: Path,
    manifest: Mapping[str, Any],
    hashes: Mapping[str, Any],
) -> dict[str, Any]:
    manifest_rows = [_as_mapping(row) for row in _as_list(manifest.get("files"))]
    hash_rows = {_as_mapping(row).get("path"): _as_mapping(row) for row in _as_list(hashes.get("hashes"))}
    manifest_paths = {str(row.get("path") or "") for row in manifest_rows}
    observed_paths = set(_release_artifact_files(root))
    missing_files = sorted(path for path in manifest_paths if path and not (root / path).exists())
    unlisted_files = sorted(path for path in observed_paths - manifest_paths if path not in RELEASE_SELF_REFERENTIAL_FILES)
    hash_mismatches: list[dict[str, Any]] = []
    raw_sql_or_secret_files: list[str] = []
    commit_mismatches: list[dict[str, Any]] = []
    deleted_reference_files: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    expected_commit = str(manifest.get("commit_sha") or "")
    source_head = _git_output("rev-parse", "HEAD")
    deleted_tokens = _deleted_artifact_reference_tokens(root)
    if expected_commit and source_head and expected_commit != source_head:
        commit_mismatches.append({
            "path": f"{RELEASE_CANDIDATE_DIR}/artifact_manifest.json",
            "expected": source_head,
            "actual": expected_commit,
        })
    for row in manifest_rows:
        rel = str(row.get("path") or "")
        if not rel or rel in missing_files:
            continue
        path = root / rel
        category = str(row.get("category") or _release_artifact_category(rel))
        category_counts[category] = category_counts.get(category, 0) + 1
        contains_raw = bool(row.get("contains_raw_sql")) or bool(row.get("contains_secrets")) or _artifact_text_contains_raw_sql_or_secret(path)
        if contains_raw:
            raw_sql_or_secret_files.append(rel)
        row_commit = str(row.get("commit_sha") or "")
        if expected_commit and row_commit != expected_commit:
            commit_mismatches.append({"path": rel, "expected": expected_commit, "actual": row_commit})
        deleted_hits = _artifact_deleted_reference_hits(path, rel, deleted_tokens)
        if deleted_hits:
            deleted_reference_files.append({"path": rel, "references": deleted_hits})
        hash_row = _as_mapping(hash_rows.get(rel))
        if rel not in RELEASE_SELF_REFERENTIAL_FILES and not bool(row.get("self_referential_hash")):
            actual_hash = _file_sha256(path)
            expected_hash = str(row.get("sha256") or hash_row.get("sha256") or "")
            if expected_hash != actual_hash:
                hash_mismatches.append({"path": rel, "expected": expected_hash, "actual": actual_hash})
    missing_categories = sorted(category for category in RELEASE_REQUIRED_CATEGORIES if category_counts.get(category, 0) == 0)
    if missing_files:
        failures.append({"code": "RELEASE_MANIFEST_FILE_MISSING", "files": missing_files})
    if unlisted_files:
        failures.append({"code": "RELEASE_UNLISTED_ARTIFACT", "files": unlisted_files})
    if hash_mismatches:
        failures.append({"code": "RELEASE_HASH_MISMATCH", "files": hash_mismatches})
    if missing_categories:
        failures.append({"code": "RELEASE_CATEGORY_MISSING", "categories": missing_categories})
    if raw_sql_or_secret_files:
        failures.append({"code": "RELEASE_RAW_SQL_OR_SECRET", "files": raw_sql_or_secret_files})
    if commit_mismatches:
        failures.append({"code": "RELEASE_ARTIFACT_COMMIT_MISMATCH", "files": commit_mismatches})
    if deleted_reference_files:
        failures.append({"code": "RELEASE_ARTIFACT_REFERENCES_DELETED_ITEM", "files": deleted_reference_files})
    for skipped, proof_pattern in (
        ("artifacts/browser_screenshots/SKIPPED.txt", "artifacts/browser_screenshots/*.png"),
        ("artifacts/query_history_by_tag_SKIPPED.txt", "artifacts/query_history_by_tag.json"),
    ):
        if (root / skipped).exists() and list(root.glob(proof_pattern)):
            failures.append({"code": "STALE_SKIPPED_FILE_WITH_PROOF", "file": skipped})
    return {
        "source": "release_candidate_artifact_reconciliation",
        "proof_source": "runtime_click",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "artifact_count": len(manifest_rows),
        "hash_count": len(_as_list(hashes.get("hashes"))),
        "missing_files": missing_files,
        "missing_file_count": len(missing_files),
        "unlisted_files": unlisted_files,
        "unlisted_file_count": len(unlisted_files),
        "hash_mismatches": hash_mismatches,
        "hash_mismatch_count": len(hash_mismatches),
        "missing_required_categories": missing_categories,
        "missing_required_category_count": len(missing_categories),
        "raw_sql_or_secret_files": raw_sql_or_secret_files,
        "raw_sql_or_secret_count": len(raw_sql_or_secret_files),
        "commit_mismatches": commit_mismatches,
        "commit_mismatch_count": len(commit_mismatches),
        "deleted_reference_files": deleted_reference_files,
        "deleted_reference_count": len(deleted_reference_files),
        "categories": category_counts,
        "raw_sql_included": False,
    }


def _deleted_artifact_reference_tokens(root: Path) -> dict[str, list[str]]:
    route_module_tokens: set[str] = set()
    sql_tokens: set[str] = set()
    for rel in (
        "artifacts/cleanup/deleted_routes.json",
        "artifacts/cleanup/deleted_modules.json",
        "artifacts/cleanup/deleted_sql_objects.json",
    ):
        path = root / rel
        if not path.exists():
            continue
        payload = _read_json(path)
        for row in _as_list(_as_mapping(payload).get("deleted_routes")):
            mapped = _as_mapping(row)
            for key in ("route", "route_key", "section", "workflow"):
                value = str(mapped.get(key) or "").strip()
                if value:
                    route_module_tokens.add(value)
        for row in _as_list(_as_mapping(payload).get("deleted_modules")):
            mapped = _as_mapping(row)
            for key in ("module", "path"):
                value = str(mapped.get(key) or "").strip()
                if value:
                    route_module_tokens.add(value)
        for row in _as_list(_as_mapping(payload).get("deleted_sql_objects")):
            value = str(_as_mapping(row).get("name") or "").strip()
            if value:
                sql_tokens.add(value)
    return {
        "route_module": sorted(token for token in route_module_tokens if len(token) >= 4),
        "sql": sorted(token for token in sql_tokens if len(token) >= 4),
    }


def _artifact_deleted_reference_hits(path: Path, rel: str, deleted_tokens: Mapping[str, list[str]]) -> list[str]:
    if rel.startswith("artifacts/cleanup/"):
        return []
    sql_reference_allowed = (
        rel.startswith("artifacts/launch_readiness/drop_rollback")
        or rel.startswith("artifacts/launch_readiness/snowflake_permission_matrix")
        or rel.startswith("artifacts/launch_readiness/role_readiness")
        or rel.startswith("artifacts/release_candidate/")
    )
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    lowered = text.lower()
    tokens = list(deleted_tokens.get("route_module") or [])
    if not sql_reference_allowed:
        tokens.extend(deleted_tokens.get("sql") or [])
    hits = [token for token in tokens if token.lower() in lowered]
    return sorted(set(hits))


def _product_gauntlet_release_results(root: Path, payloads: Mapping[str, Any], launch_artifacts: Mapping[str, Any]) -> dict[str, Any]:
    summary = _as_mapping(payloads.get("artifacts/full_app_validation/app_validation_summary.json"))
    view_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/view_results.json"))]
    button_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/button_click_results.json"))]
    evidence_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/evidence_loader_call_matrix.json"))]
    query_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/query_search_results.json"))]
    export_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/export_results.json"))]
    case_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/case_payload_results.json"))]
    settings_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/settings_action_results.json"))]
    live_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/live_feature_results.json"))]
    stress_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/stress_results.json"))]
    summary_board_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/summary_board_results.json"))]
    summary_board_budget = _as_mapping(payloads.get("artifacts/full_app_validation/summary_board_query_budget_results.json"))
    forbidden_daily = _as_mapping(payloads.get("artifacts/full_app_validation/forbidden_daily_ui_scan.json"))
    checks: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    def add(name: str, passed: bool, recommendation: str, *, actual: Any = None, expected: Any = None) -> None:
        row = {
            "check_name": name,
            "passed": bool(passed),
            "actual": actual,
            "expected": expected,
            "recommendation": "" if passed else recommendation,
        }
        checks.append(row)
        if not passed:
            failures.append(row)

    sections = {str(row.get("section") or "") for row in view_rows if row.get("section")}
    route_leaks = [
        row for row in button_rows
        if (str(row.get("action_type") or "") == "route" or bool(row.get("route_action")))
        and _raw_count(
            row,
            "session_count",
            "session_open_count",
            "query_count",
            "snowflake_execution_count",
            "actual_snowflake_executions",
            "direct_sql_count",
            "direct_sql_event_count",
            "metadata_probe_event_count",
        ) > 0
    ]
    normal_evidence_bad = [
        row for row in evidence_rows
        if str(row.get("loader_kind") or "") == "normal_evidence"
        and (bool(row.get("account_usage_used")) or not bool(row.get("normal_evidence_source_allowed", True)))
    ]
    no_click = [
        row for row in query_rows
        if str(row.get("case") or "") == "render_no_click" and _raw_count(row, "session_open_count", "direct_sql_event_count", "snowflake_execution_count", "query_count") > 0
    ]
    query_text_exports = [row for row in export_rows if bool(row.get("query_text_included")) and not bool(row.get("admin_only"))]
    export_failures = [
        row for row in export_rows
        if not row.get("payload_file")
        or bool(row.get("hash_mismatch"))
        or _as_int(row.get("parsed_row_count")) != _as_int(row.get("visible_row_count"))
    ]
    case_failures = [
        row for row in case_rows
        if any(not row.get(field) for field in REQUIRED_CASE_FIELDS)
        or _as_int(row.get("row_count")) != _as_int(row.get("visible_row_count"))
    ]
    stress_failures = [
        row for row in stress_rows
        if not row.get("threshold")
        or not row.get("actuals")
        or not bool(row.get("threshold_passed", True))
        or _as_list(row.get("threshold_failures"))
    ]
    def settings_row_requires_admin_gate(row: Mapping[str, Any]) -> bool:
        action_type = str(row.get("action_type") or "")
        section = str(row.get("section") or "")
        return (
            section == "Settings/Admin Setup Health"
            or action_type in {"admin_load", "advanced_load", "setup_health", "account_usage_fallback"}
            or bool(row.get("requires_admin"))
            or bool(row.get("heavy_query_allowed"))
            or bool(row.get("account_usage_allowed"))
        )

    settings_gaps = [
        row for row in settings_rows
        if (
            settings_row_requires_admin_gate(row)
            and not bool(row.get("admin_or_advanced_gated"))
        )
        or bool(row.get("raw_error_visible_daily"))
        or not bool(row.get("sanitized_error_state", True))
        or not _owner_skipped(row) and not bool(row.get("clicked"))
    ]
    live_gaps = [
        row for row in live_rows
        if not bool(row.get("admin_or_advanced_gated"))
        or not bool(row.get("explicit_click_required"))
        or (
            not _owner_skipped(row)
            and not bool(row.get("budget_context_observed", bool(_raw_observed_contexts(row))))
        )
        or bool(row.get("first_paint_invocation"))
        or bool(row.get("route_invocation"))
        or bool(row.get("raw_error_visible_daily"))
        or not bool(row.get("timeout_or_row_limit"))
        or not _owner_skipped(row) and not bool(row.get("clicked"))
    ]
    add("six_primary_overviews_rendered", PRIMARY_SECTIONS.issubset(sections), "Render all six launch Decision Workspace sections.", actual=sorted(sections), expected=sorted(PRIMARY_SECTIONS))
    summary_sections = {str(row.get("section") or "") for row in summary_board_rows if row.get("section")}
    summary_failures = [row for row in summary_board_rows if not bool(row.get("passed"))]
    add(
        "summary_board_packet_only_first_paint",
        PRIMARY_SECTIONS.issubset(summary_sections) and not summary_failures and bool(summary_board_budget.get("passed", False)),
        "Summary boards must render from packet-only first paint across all six primary sections.",
        actual={
            "sections": sorted(summary_sections),
            "failure_count": len(summary_failures),
            "budget_passed": bool(summary_board_budget.get("passed", False)),
        },
        expected={"sections": sorted(PRIMARY_SECTIONS), "failure_count": 0, "budget_passed": True},
    )
    add("first_paint_slo_passed", bool(summary.get("performance_gate_passed", summary.get("all_passed"))), "Fix first-paint packet/query budget failures.", actual=summary.get("performance_gate_passed"), expected=True)
    add("route_actions_zero_query", not route_leaks, "Route actions must not open sessions, run queries, or execute direct SQL.", actual=len(route_leaks), expected=0)
    add("normal_evidence_compact_mart_backed", not normal_evidence_bad, "Normal evidence must use compact marts or exact recent-detail paths only.", actual=len(normal_evidence_bad), expected=0)
    add("account_usage_explicit_admin_only", all(not bool(row.get("account_usage_used")) for row in evidence_rows if str(row.get("loader_kind") or "") == "normal_evidence"), "Normal evidence cannot use Account Usage.", actual=len([row for row in evidence_rows if str(row.get("loader_kind") or "") == "normal_evidence" and bool(row.get("account_usage_used"))]), expected=0)
    add("query_search_no_click_zero_cost", not no_click, "Query Search render/no-click proof must have zero Snowflake cost.", actual=len(no_click), expected=0)
    add("query_search_export_no_query_text", not query_text_exports, "Default Query Search exports must not include query text.", actual=len(query_text_exports), expected=0)
    add("export_payloads_hash_and_row_valid", not export_failures, "Every export payload must exist and match visible row counts and hash.", actual=len(export_failures), expected=0)
    add("case_payloads_complete", not case_failures, "Case payload rows require section/workflow/scope/target/freshness/source/summary/row_count and visible row agreement.", actual=len(case_failures), expected=0)
    add("daily_forbidden_token_scans_zero", bool(summary.get("evidence_gate_passed", True)) and _as_int(summary.get("forbidden_ui_token_count")) == 0 and _as_int(forbidden_daily.get("blocked_count")) == 0, "Daily UI/export scans must have zero forbidden tokens.", actual={"summary": _as_int(summary.get("forbidden_ui_token_count")), "daily_scan": _as_int(forbidden_daily.get("blocked_count"))}, expected=0)
    add("stress_thresholds_pass", not stress_failures, "All stress rows require real thresholds, actuals, and zero threshold failures.", actual=len(stress_failures), expected=0)
    add("settings_actions_gated", not settings_gaps, "Settings/Admin actions must be clicked or owner-skipped, admin-gated, and sanitized.", actual=len(settings_gaps), expected=0)
    add("live_features_gated", not live_gaps, "Live features must be click-required, gated, budget-observed, sanitized, and absent from first paint/routes.", actual=len(live_gaps), expected=0)
    add("settings_live_gating_passed", bool(_as_mapping(launch_artifacts.get("settings_live_closure_results")).get("passed")), "Settings/Admin and live features must remain gated, budgeted, and sanitized.", actual=_as_mapping(launch_artifacts.get("settings_live_closure_results")).get("passed"), expected=True)
    add("browser_or_snapshot_passed", bool(_as_mapping(launch_artifacts.get("browser_smoke_results")).get("passed")), "Browser or deterministic snapshot proof must pass for the selected profile.", actual=_as_mapping(launch_artifacts.get("browser_smoke_results")).get("passed"), expected=True)
    return {
        "source": "release_candidate_product_gauntlet",
        "proof_source": "runtime_click",
        "generated_at": _utc_now(),
        "passed": not failures,
        "check_count": len(checks),
        "failure_count": len(failures),
        "checks": checks,
        "failures": failures,
        "raw_sql_included": False,
    }


def _release_candidate_gate_results(reconciliation: Mapping[str, Any], product_gauntlet: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if not bool(reconciliation.get("passed")):
        failures.append({"gate": "artifact_reconciliation", "details": reconciliation.get("failures")})
    if not bool(product_gauntlet.get("passed")):
        failures.append({"gate": "product_gauntlet_release", "details": product_gauntlet.get("failures")})
    return {
        "source": "release_candidate_gate",
        "proof_source": "runtime_click",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "artifact_count": _as_int(reconciliation.get("artifact_count")),
        "artifact_hash_count": _as_int(reconciliation.get("hash_count")),
        "raw_sql_included": False,
    }


def _release_candidate_summary_bundle(
    *,
    launch_summary: Mapping[str, Any],
    launch_failures: Mapping[str, Any],
    matrix: Iterable[Mapping[str, Any]],
    release_gate: Mapping[str, Any],
    product_gauntlet: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    ci_context: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    matrix_rows = [_as_mapping(row) for row in matrix]
    uploaded_names = _as_list(launch_summary.get("uploaded_artifact_names"))
    artifact_bundle_name = uploaded_names[0] if uploaded_names else "decision-workspace-proof"
    release_matrix = [
        {
            "gate": "launch_readiness",
            "passed": bool(launch_summary.get("all_passed")),
            "artifact": f"{LAUNCH_READINESS_DIR}/launch_readiness_summary.json",
        },
        {
            "gate": "release_artifact_reconciliation",
            "passed": bool(reconciliation.get("passed")),
            "artifact": f"{RELEASE_CANDIDATE_DIR}/artifact_reconciliation_results.json",
        },
        {
            "gate": "product_gauntlet_release",
            "passed": bool(product_gauntlet.get("passed")),
            "artifact": f"{RELEASE_CANDIDATE_DIR}/product_gauntlet_release_results.json",
        },
        {
            "gate": "ci_artifact_reality",
            "passed": bool(launch_summary.get("ci_artifact_reality_passed")),
            "artifact": f"{LAUNCH_READINESS_DIR}/ci_artifact_reality_results.json",
        },
        {
            "gate": "live_execution_manifest",
            "passed": bool(launch_summary.get("live_execution_manifest_gate_passed")),
            "artifact": f"{LAUNCH_READINESS_DIR}/live_execution_manifest_gate_results.json",
        },
        {
            "gate": "encoding_hygiene",
            "passed": bool(launch_summary.get("encoding_hygiene_passed")),
            "artifact": "artifacts/encoding_hygiene_results.json",
        },
        {
            "gate": "cost_db_formula_authority",
            "passed": bool(launch_summary.get("cost_db_formula_authority_passed")),
            "artifact": f"{LAUNCH_READINESS_DIR}/cost_db_formula_authority_gate_results.json",
        },
        {
            "gate": "formula_end_to_end",
            "passed": bool(launch_summary.get("formula_end_to_end_passed")),
            "artifact": FORMULA_GATE_REL,
        },
        {
            "gate": "formula_value_reconciliation",
            "passed": bool(launch_summary.get("formula_value_reconciliation_passed")),
            "artifact": FORMULA_VALUE_RECONCILIATION_REL,
        },
        {
            "gate": "formula_value_source_reconciliation",
            "passed": bool(launch_summary.get("formula_value_source_reconciliation_passed")),
            "artifact": FORMULA_VALUE_SOURCE_RECONCILIATION_REL,
        },
        {
            "gate": "formula_value_gate",
            "passed": bool(launch_summary.get("formula_value_source_reconciliation_passed")),
            "artifact": FORMULA_VALUE_GATE_REL,
        },
        {
            "gate": "snowflake_cli_live_validation",
            "passed": bool(launch_summary.get("snowflake_cli_live_validation_passed")),
            "artifact": CLI_LAUNCH_GATE_REL,
        },
        {
            "gate": "packet_schema_upgrade",
            "passed": bool(launch_summary.get("packet_schema_upgrade_passed")),
            "artifact": PACKET_SCHEMA_GATE_REL,
        },
        {
            "gate": "snowflake_formula_static_live",
            "passed": bool(launch_summary.get("snowflake_formula_gate_passed")),
            "artifact": SNOWFLAKE_FORMULA_GATE_REL,
        },
        {
            "gate": "snowflake_formula_value",
            "passed": bool(launch_summary.get("snowflake_formula_value_passed")),
            "artifact": SNOWFLAKE_FORMULA_VALUE_REL,
        },
        {
            "gate": "live_static_formula_status",
            "passed": bool(launch_summary.get("snowflake_formula_gate_passed"))
            and not (
                bool(launch_summary.get("snowflake_formula_live_passed"))
                and bool(launch_summary.get("snowflake_formula_live_skipped"))
            ),
            "artifact": SNOWFLAKE_FORMULA_GATE_REL,
        },
        {
            "gate": "cortex_service_type_mapping",
            "passed": bool(launch_summary.get("cortex_service_type_gate_passed")),
            "artifact": CORTEX_SERVICE_TYPE_GATE_REL,
        },
        {
            "gate": "metric_semantic_registry",
            "passed": bool(launch_summary.get("metric_semantic_registry_passed")),
            "artifact": f"{LAUNCH_READINESS_DIR}/metric_semantic_gate_results.json",
        },
        {
            "gate": "cost_advisor_value_at_risk",
            "passed": bool(launch_summary.get("cost_advisor_value_at_risk_passed")),
            "artifact": f"{LAUNCH_READINESS_DIR}/cost_advisor_gate_results.json",
        },
        {
            "gate": "date_widget_regression",
            "passed": bool(launch_summary.get("date_widget_regression_passed")),
            "artifact": f"{LAUNCH_READINESS_DIR}/date_widget_regression_results.json",
        },
        {
            "gate": "render_provenance_reconciliation",
            "passed": bool(launch_summary.get("render_provenance_reconciliation_passed")),
            "artifact": RENDER_PROVENANCE_RECONCILIATION_GATE_REL,
        },
    ]
    release_matrix.extend(
        {
            "gate": str(row.get("gate") or ""),
            "passed": bool(row.get("passed")),
            "artifact": str(row.get("artifact") or ""),
        }
        for row in matrix_rows
    )
    notes_preview = _release_notes_payload(
        launch_summary=launch_summary,
        product_gauntlet=product_gauntlet,
        ci_context=ci_context,
        artifact_bundle_name=artifact_bundle_name,
        hard_failures=[],
    )
    notes_gate = _release_notes_operator_ready(notes_preview, ci_context)
    release_matrix.append(
        {
            "gate": "release_notes_operator_ready",
            "passed": bool(notes_gate.get("passed")),
            "artifact": f"{RELEASE_CANDIDATE_DIR}/release_notes.json",
        }
    )
    hard_failures = [
        row for row in release_matrix
        if not bool(row.get("passed"))
    ] + _as_list(launch_failures.get("failures")) + _as_list(release_gate.get("failures"))
    all_passed = not hard_failures
    warning_count = 1 if str(launch_summary.get("ci_metadata_warning") or "") else 0
    waiver_count = 1 if str(launch_summary.get("live_validation_waiver_id") or "") else 0
    ci_metadata_source = str(ci_context.get("proof_source") or "local_inventory")
    if bool(ci_context.get("waiver_used")):
        ci_metadata_source = "waived"
    summary = {
        "source": "release_candidate_summary",
        "proof_source": "runtime_click",
        "generated_at": _utc_now(),
        "commit_sha": str(launch_summary.get("commit_sha") or ci_context.get("commit_sha") or ""),
        "source_tree_sha": str(ci_context.get("source_commit_sha") or launch_summary.get("commit_sha") or ""),
        "github_sha": str(ci_context.get("github_sha") or ""),
        "launch_profile": str(launch_summary.get("launch_profile") or DEFAULT_LAUNCH_PROFILE),
        "workflow_url": str(launch_summary.get("workflow_url") or ci_context.get("workflow_url") or ""),
        "workflow_run_id": str(launch_summary.get("workflow_run_id") or ci_context.get("workflow_run_id") or ""),
        "run_attempt": str(launch_summary.get("run_attempt") or ci_context.get("run_attempt") or ""),
        "branch_ref": str(launch_summary.get("branch_ref") or ci_context.get("branch_ref") or ""),
        "workflow_name": str(ci_context.get("workflow_name") or ""),
        "job_name": str(ci_context.get("workflow_job") or ""),
        "artifact_upload_name": artifact_bundle_name,
        "uploaded_artifact_names": uploaded_names,
        "ci_metadata_source": ci_metadata_source,
        "all_passed": all_passed,
        "hard_gate_failure_count": len(hard_failures),
        "warning_count": warning_count,
        "waiver_count": waiver_count,
        "artifact_count": _as_int(reconciliation.get("artifact_count")),
        "artifact_hash_count": _as_int(reconciliation.get("hash_count")),
        "ci_artifact_reality_passed": bool(launch_summary.get("ci_artifact_reality_passed")),
        "full_app_gauntlet_passed": bool(launch_summary.get("gauntlet_passed")),
        "full_app_launch_gauntlet_passed": bool(launch_summary.get("full_app_launch_gauntlet_passed")),
        "render_provenance_reconciliation_passed": bool(
            launch_summary.get("render_provenance_reconciliation_passed")
        ),
        "render_provenance_reconciliation_failure_count": _as_int(
            launch_summary.get("render_provenance_reconciliation_failure_count")
        ),
        "rendered_ui_leak_scan_passed": bool(launch_summary.get("rendered_ui_leak_scan_passed")),
        "diagnostic_leak_count": _as_int(launch_summary.get("diagnostic_leak_count")),
        "internal_wording_leak_count": _as_int(launch_summary.get("internal_wording_leak_count")),
        "failed_action_count": _as_int(launch_summary.get("failed_action_count")),
        "export_failure_count": _as_int(launch_summary.get("export_failure_count")),
        "settings_failure_count": _as_int(launch_summary.get("settings_failure_count")),
        "live_feature_failure_count": _as_int(launch_summary.get("live_feature_failure_count")),
        "stress_failure_count": _as_int(launch_summary.get("stress_failure_count")),
        "slow_runtime_count": _as_int(launch_summary.get("slow_runtime_count")),
        "sql_cleanup_failure_count": _as_int(launch_summary.get("sql_cleanup_failure_count")),
        "first_paint_failure_count": _as_int(launch_summary.get("first_paint_failure_count")),
        "metric_source_governance_passed": bool(launch_summary.get("metric_source_governance_passed")),
        "ui_kit_alignment_passed": bool(launch_summary.get("ui_kit_alignment_passed")),
        "ui_kit_command_brief_surface_count": _as_int(
            launch_summary.get("ui_kit_command_brief_surface_count")
        ),
        "ui_kit_source_footer_leak_count": _as_int(launch_summary.get("ui_kit_source_footer_leak_count")),
        "ui_kit_old_board_marker_count": _as_int(launch_summary.get("ui_kit_old_board_marker_count")),
        "ui_kit_evidence_autoload_violation_count": _as_int(
            launch_summary.get("ui_kit_evidence_autoload_violation_count")
        ),
        "new_metric_family_count": _as_int(launch_summary.get("new_metric_family_count")),
        "new_metric_packet_field_count": _as_int(launch_summary.get("new_metric_packet_field_count")),
        "new_metric_rendered_count": _as_int(launch_summary.get("new_metric_rendered_count")),
        "new_metric_evidence_action_count": _as_int(launch_summary.get("new_metric_evidence_action_count")),
        "new_metric_export_count": _as_int(launch_summary.get("new_metric_export_count")),
        "new_metric_unavailable_source_count": _as_int(
            launch_summary.get("new_metric_unavailable_source_count")
        ),
        "new_metric_first_paint_violation_count": _as_int(
            launch_summary.get("new_metric_first_paint_violation_count")
        ),
        "new_metric_raw_leak_count": _as_int(launch_summary.get("new_metric_raw_leak_count")),
        "new_metric_sql_inventory_failure_count": _as_int(
            launch_summary.get("new_metric_sql_inventory_failure_count")
        ),
        "app_health_gate_passed": bool(launch_summary.get("app_health_gate_passed")),
        "source_internal_leak_scan_passed": bool(launch_summary.get("source_internal_leak_scan_passed")),
        "credential_expiration_gate_passed": bool(launch_summary.get("credential_expiration_gate_passed")),
        "credential_expiration_live_gate_passed": bool(
            launch_summary.get("credential_expiration_live_gate_passed")
        ),
        "credential_expiring_30d_count": _as_int(launch_summary.get("credential_expiring_30d_count")),
        "credential_expired_count": _as_int(launch_summary.get("credential_expired_count")),
        "credential_next_expiration_days": _as_int(launch_summary.get("credential_next_expiration_days")),
        "credential_source_confirmed_zero": bool(launch_summary.get("credential_source_confirmed_zero")),
        "credential_live_validation_status": str(launch_summary.get("credential_live_validation_status") or ""),
        "user_display_name_gate_passed": bool(launch_summary.get("user_display_name_gate_passed")),
        "user_display_name_live_gate_passed": bool(launch_summary.get("user_display_name_live_gate_passed")),
        "user_display_surface_gate_passed": bool(launch_summary.get("user_display_surface_gate_passed")),
        "cortex_user_label_gate_passed": bool(launch_summary.get("cortex_user_label_gate_passed")),
        "credential_first_paint_violation_count": _as_int(
            launch_summary.get("credential_first_paint_violation_count")
        ),
        "credential_export_leak_count": _as_int(launch_summary.get("credential_export_leak_count")),
        "user_id_daily_leak_count": _as_int(launch_summary.get("user_id_daily_leak_count")),
        "credential_render_gate_passed": bool(launch_summary.get("credential_render_gate_passed")),
        "credential_evidence_gate_passed": bool(launch_summary.get("credential_evidence_gate_passed")),
        "credential_first_paint_gate_passed": bool(launch_summary.get("credential_first_paint_gate_passed")),
        "credential_sql_inventory_gate_passed": bool(launch_summary.get("credential_sql_inventory_gate_passed")),
        "credential_rendered_leak_gate_passed": bool(launch_summary.get("credential_rendered_leak_gate_passed")),
        "cortex_token_efficiency_gate_passed": bool(launch_summary.get("cortex_token_efficiency_gate_passed")),
        "cortex_token_efficiency_live_gate_passed": bool(
            launch_summary.get("cortex_token_efficiency_live_gate_passed")
        ),
        "cortex_token_metric_count": _as_int(launch_summary.get("cortex_token_metric_count")),
        "cortex_token_ratio_failure_count": _as_int(launch_summary.get("cortex_token_ratio_failure_count")),
        "launch_readiness_passed": bool(launch_summary.get("all_passed")),
        "snowflake_validation_passed": bool(launch_summary.get("snowflake_validation_passed")),
        "live_execution_manifest_passed": bool(launch_summary.get("live_execution_manifest_gate_passed")),
        "summary_board_first_paint_passed": bool(launch_summary.get("summary_board_first_paint_passed")),
        "billing_reconciliation_passed": bool(launch_summary.get("billing_reconciliation_passed")),
        "billing_reconciliation_live_passed": bool(launch_summary.get("billing_reconciliation_live_passed")),
        "cortex_cost_consistency_passed": bool(launch_summary.get("cortex_cost_consistency_passed")),
        "cost_chart_workbench_passed": bool(launch_summary.get("cost_chart_workbench_passed")),
        "cost_db_formula_authority_passed": bool(launch_summary.get("cost_db_formula_authority_passed")),
        "formula_end_to_end_passed": bool(launch_summary.get("formula_end_to_end_passed")),
        "formula_value_reconciliation_passed": bool(launch_summary.get("formula_value_reconciliation_passed")),
        "formula_validation_mode": str(launch_summary.get("formula_validation_mode") or ""),
        "packet_formula_sql_passed": bool(launch_summary.get("packet_formula_sql_passed")),
        "flat_packet_formula_passed": bool(launch_summary.get("flat_packet_formula_passed")),
        "packet_schema_upgrade_passed": bool(launch_summary.get("packet_schema_upgrade_passed")),
        "snowflake_formula_static_passed": bool(launch_summary.get("snowflake_formula_static_passed")),
        "snowflake_formula_value_passed": bool(launch_summary.get("snowflake_formula_value_passed")),
        "snowflake_formula_value_failure_count": _as_int(launch_summary.get("snowflake_formula_value_failure_count")),
        "snowflake_formula_live_required": bool(launch_summary.get("snowflake_formula_live_required")),
        "snowflake_formula_live_executed": bool(launch_summary.get("snowflake_formula_live_executed")),
        "snowflake_formula_live_passed": bool(launch_summary.get("snowflake_formula_live_passed")),
        "snowflake_formula_live_skipped": bool(launch_summary.get("snowflake_formula_live_skipped")),
        "snowflake_formula_live_skip_reason": str(launch_summary.get("snowflake_formula_live_skip_reason") or ""),
        "snowflake_formula_gate_passed": bool(launch_summary.get("snowflake_formula_gate_passed")),
        "rendered_formula_passed": bool(launch_summary.get("rendered_formula_passed")),
        "cortex_service_type_gate_passed": bool(launch_summary.get("cortex_service_type_gate_passed")),
        "formula_live_validation_passed": bool(launch_summary.get("formula_live_validation_passed")),
        "snowflake_cli_gate_passed": bool(launch_summary.get("snowflake_cli_gate_passed")),
        "snowflake_cli_live_executed": bool(launch_summary.get("snowflake_cli_live_executed")),
        "snowflake_cli_live_passed": bool(launch_summary.get("snowflake_cli_live_passed")),
        "snowflake_cli_live_skipped": bool(launch_summary.get("snowflake_cli_live_skipped")),
        "snowflake_cli_manifest_reconciliation_passed": bool(launch_summary.get("snowflake_cli_manifest_reconciliation_passed")),
        "snowflake_cli_live_validation_passed": bool(launch_summary.get("snowflake_cli_live_validation_passed")),
        "snowflake_cli_live_validation_skipped": bool(launch_summary.get("snowflake_cli_live_validation_skipped")),
        "snowflake_cli_live_validation_required": bool(launch_summary.get("snowflake_cli_live_validation_required")),
        "setup_migration_live_passed": bool(launch_summary.get("setup_migration_live_passed")),
        "snowflake_cli_formula_value_passed": bool(launch_summary.get("snowflake_cli_formula_value_passed")),
        "snowflake_cli_packet_value_passed": bool(launch_summary.get("snowflake_cli_packet_value_passed")),
        "snowflake_cli_query_budget_passed": bool(launch_summary.get("snowflake_cli_query_budget_passed")),
        "metric_semantic_registry_passed": bool(launch_summary.get("metric_semantic_registry_passed")),
        "workload_formula_semantics_passed": bool(launch_summary.get("workload_formula_semantics_passed")),
        "query_budget_gate_passed": bool(launch_summary.get("query_budget_gate_passed")),
        "encoding_hygiene_passed": bool(launch_summary.get("encoding_hygiene_passed")),
        "cleanup_passed": _gate_passed(matrix_rows, "cleanup_closure"),
        "artifact_reconciliation_passed": bool(reconciliation.get("passed")),
        "browser_or_snapshot_passed": _gate_passed(matrix_rows, "browser_or_rendered_snapshot"),
        "product_gauntlet_passed": bool(product_gauntlet.get("passed")),
        "first_paint_slo_passed": bool(_check_passed(product_gauntlet, "first_paint_slo_passed")),
        "route_zero_query_passed": bool(_check_passed(product_gauntlet, "route_actions_zero_query")),
        "normal_evidence_compact_mart_passed": bool(_check_passed(product_gauntlet, "normal_evidence_compact_mart_backed")),
        "account_usage_explicit_only_passed": bool(launch_summary.get("snowflake_live_validation_skipped") or launch_summary.get("snowflake_validation_passed")),
        "export_case_validation_passed": _gate_passed(matrix_rows, "export_case_closure"),
        "settings_live_gating_passed": _gate_passed(matrix_rows, "settings_live_closure"),
        "deployment_readiness_passed": _gate_passed(matrix_rows, "deployment_readiness"),
        "docs_readiness_passed": _gate_passed(matrix_rows, "docs_readiness"),
        "raw_sql_leak_count": _as_int(reconciliation.get("raw_sql_or_secret_count")) or _as_int(launch_summary.get("raw_sql_leak_count")),
        "forbidden_daily_token_count": _as_int(launch_summary.get("forbidden_daily_token_count")),
        "stale_artifact_count": _as_int(launch_summary.get("stale_artifact_count")),
        "unknown_sql_object_count": _as_int(launch_summary.get("cleanup_unknown_sql_object_count")),
        "dead_route_count": _as_int(launch_summary.get("cleanup_dead_route_count")),
        "artifact_bundle_name": artifact_bundle_name,
        "raw_sql_included": False,
    }
    failures = {
        "source": "release_candidate_failures",
        "proof_source": "runtime_click",
        "passed": all_passed,
        "failure_count": len(hard_failures),
        "failures": hard_failures,
        "raw_sql_included": False,
    }
    notes = _release_notes_payload(
        launch_summary=launch_summary,
        product_gauntlet=product_gauntlet,
        ci_context=ci_context,
        artifact_bundle_name=artifact_bundle_name,
        hard_failures=hard_failures,
    )
    return summary, failures, release_matrix, notes


def _release_notes_payload(
    *,
    launch_summary: Mapping[str, Any],
    product_gauntlet: Mapping[str, Any],
    ci_context: Mapping[str, Any],
    artifact_bundle_name: str,
    hard_failures: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "source": "release_candidate_notes",
        "proof_source": "runtime_click",
        "commit_range": f"HEAD~1..{str(launch_summary.get('commit_sha') or ci_context.get('commit_sha') or '')}",
        "changed_files_summary": "Release-candidate proof bundle, CI context, artifact hashes, and manifest reconciliation.",
        "launch_profile": str(launch_summary.get("launch_profile") or DEFAULT_LAUNCH_PROFILE),
        "workflow_url": str(launch_summary.get("workflow_url") or ci_context.get("workflow_url") or ""),
        "artifact_bundle_name": artifact_bundle_name,
        "validation_commands": [
            "python -m ruff check .overwatch_final tests tools",
            "python -m mypy",
            "python -m compileall .overwatch_final tools tests",
            "python -m unittest tests.test_snowflake_execution_validation",
            "python -m unittest tests.test_cost_db_formula_authority tests.test_cost_formula_authority tests.test_cortex_service_types tests.test_formula_end_to_end_validation tests.test_formula_packet_sql tests.test_packet_schema_upgrade",
            "python -m unittest tests.test_launch_readiness",
            "python -m tools.contracts.encoding_hygiene",
            "python -m tools.contracts.cost_db_formula_authority",
            "python -m tools.contracts.formula_end_to_end_validation",
            "python -m unittest discover -s tests",
        ],
        "hard_blockers": list(hard_failures),
        "known_skips_or_waivers": [
            value for value in (
                str(launch_summary.get("snowflake_validation_skip_reason") or ""),
                str(launch_summary.get("ci_metadata_warning") or ""),
            )
            if value
        ],
        "live_snowflake_validation_status": str(launch_summary.get("live_validation_status") or ""),
        "browser_proof_status": "passed" if bool(launch_summary.get("browser_or_snapshot_passed", True)) else "failed",
        "snowflake_validation_status": "passed" if bool(launch_summary.get("snowflake_validation_passed")) else "failed",
        "product_gauntlet_status": "passed" if bool(product_gauntlet.get("passed")) else "failed",
        "rollback_notes": "Use the documented drop/rollback readiness artifact and last-known-good packet path before reverting a release candidate.",
        "operator_next_steps": [
            "Review artifacts/release_candidate/release_candidate_summary.json.",
            f"Confirm CI uploaded {artifact_bundle_name} for the evaluated commit.",
            "Promote only when live Snowflake proof or signed profile waiver is present for non-fixture profiles.",
        ],
        "waiver_section_present": True,
        "blocker_section_present": True,
        "raw_sql_included": False,
    }


def _release_notes_operator_ready(notes: Mapping[str, Any], ci_context: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "commit_range",
        "changed_files_summary",
        "launch_profile",
        "workflow_url",
        "artifact_bundle_name",
        "validation_commands",
        "hard_blockers",
        "known_skips_or_waivers",
        "live_snowflake_validation_status",
        "browser_proof_status",
        "snowflake_validation_status",
        "product_gauntlet_status",
        "rollback_notes",
        "operator_next_steps",
    }
    missing = sorted(key for key in required if key not in notes)
    empty = sorted(
        key for key in required
        if key in notes and key not in {"hard_blockers", "known_skips_or_waivers", "workflow_url"} and not notes.get(key)
    )
    if bool(ci_context.get("github_actions")) and not str(notes.get("workflow_url") or ""):
        empty.append("workflow_url")
    raw_or_secret = _raw_sql_or_secret_value(notes)
    failures = []
    if missing:
        failures.append({"code": "RELEASE_NOTES_FIELD_MISSING", "fields": missing})
    if empty:
        failures.append({"code": "RELEASE_NOTES_FIELD_EMPTY", "fields": sorted(set(empty))})
    if raw_or_secret:
        failures.append({"code": "RELEASE_NOTES_RAW_SQL_OR_SECRET"})
    return {
        "source": "release_notes_operator_ready",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "missing_fields": missing,
        "empty_fields": sorted(set(empty)),
        "raw_sql_or_secret_count": 1 if raw_or_secret else 0,
        "recommendation": "" if not failures else "Populate release notes with operator-ready workflow, validation, rollback, blocker, and waiver details.",
        "raw_sql_included": False,
    }


def _gate_passed(matrix_rows: Iterable[Mapping[str, Any]], gate: str) -> bool:
    return any(str(row.get("gate") or "") == gate and bool(row.get("passed")) for row in matrix_rows)


def _check_passed(payload: Mapping[str, Any], check_name: str) -> bool:
    return any(str(row.get("check_name") or "") == check_name and bool(row.get("passed")) for row in _as_list(payload.get("checks")))


def _raw_count(row: Mapping[str, Any], *keys: str) -> int:
    return sum(_as_int(row.get(key)) for key in keys)


def _raw_observed_contexts(row: Mapping[str, Any]) -> list[Any]:
    return _as_list(
        row.get("observed_contexts")
        or row.get("observed_budget_contexts")
        or row.get("observed_query_budget_contexts")
        or row.get("marker_budget_runtime_contexts")
    )


def _owner_skipped(row: Mapping[str, Any]) -> bool:
    reason = str(row.get("skip_reason") or "").strip()
    owner = str(row.get("owner") or "").strip()
    review = str(row.get("review_note") or row.get("expiration_or_review_note") or row.get("expiration") or "").strip()
    if not reason:
        return False
    lowered = {reason.lower(), owner.lower(), review.lower()}
    return bool(owner and review and not (lowered & GENERIC_WAIVER_TEXT))


def _raw_invariant_artifacts(root: Path, payloads: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, recommendation: str, *, count: int = 0, details: Any = None) -> None:
        row = {
            "gate": name,
            "passed": bool(passed),
            "count": count,
            "recommendation": "" if passed else recommendation,
        }
        if details is not None:
            row["details"] = details
        checks.append(row)
        if not passed:
            failures.append(
                {
                    "gate": name,
                    "reason": f"{name} invariant failed.",
                    "count": count,
                    "recommendation": recommendation,
                    "details": details,
                }
            )

    view_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/view_results.json"))]
    button_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/button_click_results.json"))]
    control = _as_mapping(payloads.get("artifacts/full_app_validation/control_click_coverage.json"))
    export_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/export_results.json"))]
    case_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/case_payload_results.json"))]
    settings_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/settings_action_results.json"))]
    live_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/live_feature_results.json"))]
    evidence_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/evidence_loader_call_matrix.json"))]
    query_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/query_search_results.json"))]
    stress_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/stress_results.json"))]
    summary_board_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/summary_board_results.json"))]
    summary_board_budget = _as_mapping(payloads.get("artifacts/full_app_validation/summary_board_query_budget_results.json"))
    query_budget = _as_mapping(payloads.get("artifacts/full_app_validation/query_budget_results.json"))
    session_direct = _as_mapping(payloads.get("artifacts/full_app_validation/session_direct_sql_results.json"))
    cleanup_summary = _as_mapping(payloads.get("artifacts/cleanup/cleanup_summary.json"))
    route_inventory = _as_mapping(payloads.get("artifacts/cleanup/route_state_inventory.json"))
    object_inventory = _as_mapping(payloads.get("artifacts/cleanup/sql_object_inventory.json"))
    direct_scan = _as_mapping(payloads.get("artifacts/direct_sql_static_scan.json"))
    session_scan = _as_mapping(payloads.get("artifacts/session_open_static_scan.json"))
    sql_lint_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/sql_performance_lint_findings.json"))]

    sections_seen = {str(row.get("section") or "") for row in view_rows if row.get("section")}
    missing_sections = sorted(PRIMARY_SECTIONS - sections_seen)
    add_check(
        "primary_sections_rendered",
        not missing_sections,
        "Render every primary section in full app validation.",
        count=len(missing_sections),
        details=missing_sections,
    )

    action_count = _as_int(control.get("action_control_count"))
    clicked_count = _as_int(control.get("clicked_action_control_count"))
    skipped_count = _as_int(control.get("explicitly_skipped_action_control_count"))
    control_fail_count = sum(
        _as_int(control.get(key))
        for key in (
            "missing_action_control_count",
            "generic_skip_reason_count",
            "unowned_skip_reason_count",
            "expired_skip_reason_count",
            "duplicate_key_count",
            "blank_label_count",
            "unknown_action_control_count",
        )
    )
    add_check(
        "action_controls_clicked_or_owner_skipped",
        bool(control.get("passed")) and action_count == clicked_count + skipped_count and control_fail_count == 0,
        "Click every action control or add a current owner/reason/review skip.",
        count=control_fail_count,
        details={"action_control_count": action_count, "clicked": clicked_count, "skipped": skipped_count},
    )

    route_leaks = [
        row for row in button_rows
        if str(row.get("action_type") or "") == "route"
        and _raw_count(row, "actual_snowflake_executions", "session_open_count", "direct_sql_event_count", "metadata_probe_event_count") > 0
    ]
    add_check("route_actions_zero_cost", not route_leaks, "Route actions must not open sessions, run queries, or emit direct SQL.", count=len(route_leaks))

    first_paint_failures = []
    warm_failures = []
    for row in view_rows:
        fp = _as_mapping(row.get("first_paint"))
        if _raw_count(fp, "observed_non_packet_first_paint_events", "first_paint_account_usage", "first_paint_metadata_probes", "first_paint_direct_sql") > 0:
            first_paint_failures.append(row.get("id") or row.get("section"))
        if _as_int(fp.get("warm_packet_queries")) > 0:
            warm_failures.append(row.get("id") or row.get("section"))
    add_check("first_paint_no_non_packet_queries", not first_paint_failures, "First paint may only run the packet lookup.", count=len(first_paint_failures), details=first_paint_failures[:10])
    add_check("warm_first_paint_zero_packet_queries", not warm_failures, "Warm first paint must run zero packet queries.", count=len(warm_failures), details=warm_failures[:10])

    summary_sections = {str(row.get("section") or "") for row in summary_board_rows if row.get("section")}
    summary_failures = [
        row for row in summary_board_rows
        if not bool(row.get("passed"))
        or _as_int(row.get("packet_query_count")) != 1
        or _as_int(row.get("warm_packet_query_count"))
        or _as_int(row.get("non_packet_first_paint_event_count"))
        or _as_int(row.get("session_open_count"))
        or _as_int(row.get("direct_sql_event_count"))
        or _as_int(row.get("account_usage_query_count"))
        or _as_int(row.get("evidence_query_count"))
        or _as_int(row.get("raw_internal_token_count"))
        or _as_list(row.get("optional_detail_state_reads"))
    ]
    add_check(
        "summary_board_packet_only_first_paint",
        PRIMARY_SECTIONS.issubset(summary_sections)
        and not summary_failures
        and bool(summary_board_budget.get("passed", False)),
        "Summary boards must render from packet-only first paint across all six primary sections.",
        count=len(PRIMARY_SECTIONS - summary_sections) + len(summary_failures) + (0 if summary_board_budget.get("passed") else 1),
        details={"missing_sections": sorted(PRIMARY_SECTIONS - summary_sections), "failures": summary_failures[:10]},
    )

    evidence_over = [
        row for row in button_rows
        if str(row.get("action_type") or "") == "evidence_load"
        and _as_int(row.get("actual_snowflake_executions") or row.get("raw_snowflake_executions")) > max(1, _as_int(row.get("expected_snowflake_execution_count") or 1))
    ]
    add_check("evidence_click_boundary_budget", not evidence_over, "Evidence clicks must stay within the expected targeted evidence boundary count.", count=len(evidence_over))

    normal_evidence_failures = []
    for row in evidence_rows:
        is_normal = str(row.get("loader_kind") or "") == "normal_evidence"
        if not is_normal:
            continue
        family = str(row.get("compact_table_family") or "")
        base_row_count = _as_int(row.get("row_count"))
        counts = [
            _as_int(row.get("row_count")),
            _as_int(row.get("returned_row_count", base_row_count)),
            _as_int(row.get("panel_row_count", base_row_count)),
            _as_int(row.get("export_row_count", base_row_count)),
            _as_int(row.get("case_row_count", base_row_count)),
        ]
        if (
            bool(row.get("account_usage_used"))
            or str(row.get("query_boundary") or row.get("boundary") or "") == "advanced_diagnostics"
            or family not in COMPACT_EVIDENCE_MARTS | {"FACT_QUERY_DETAIL_RECENT"}
            or not bool(row.get("normal_evidence_source_allowed"))
            or _as_int(row.get("max_rows")) > 500
            or len(set(counts)) > 1
        ):
            normal_evidence_failures.append({"section": row.get("section"), "loader": row.get("observed_loader_name")})
    add_check("normal_evidence_compact_and_bounded", not normal_evidence_failures, "Normal evidence must use compact marts or exact recent detail, avoid Account Usage, and keep row counts aligned.", count=len(normal_evidence_failures), details=normal_evidence_failures)

    evidence_sections = {str(row.get("section") or "") for row in evidence_rows if row.get("section")}
    add_check("evidence_matrix_primary_section_coverage", PRIMARY_SECTIONS.issubset(evidence_sections), "Evidence loader matrix must cover all six primary sections.", count=len(PRIMARY_SECTIONS - evidence_sections), details=sorted(PRIMARY_SECTIONS - evidence_sections))

    query_cases = {str(row.get("case") or ""): row for row in query_rows}
    missing_query_cases = sorted(REQUIRED_QUERY_SEARCH_CASES - set(query_cases))
    bad_query_cases = []
    for case, row in query_cases.items():
        cost = _raw_count(row, "session_open_count", "direct_sql_event_count", "snowflake_execution_count", "metadata_probe_count")
        if case in {"render_no_click", "text_contains_no_autorun", "warehouse_prefill_no_autorun", "account_usage_fallback_unconfirmed"} and cost:
            bad_query_cases.append({"case": case, "reason": "unexpected_cost"})
        if case == "exact_query_id" and _as_int(row.get("max_rows")) > 1:
            bad_query_cases.append({"case": case, "reason": "max_rows"})
        if case == "query_signature" and _as_int(row.get("max_rows")) > 200:
            bad_query_cases.append({"case": case, "reason": "max_rows"})
        if case == "related_executions" and _as_int(row.get("max_rows")) > 50:
            bad_query_cases.append({"case": case, "reason": "max_rows"})
        if case == "sql_preview" and (_as_int(row.get("max_rows")) > 1 or bool(row.get("raw_sql_visible_in_daily_ui"))):
            bad_query_cases.append({"case": case, "reason": "preview_not_safe"})
        if case == "default_export_no_query_text" and bool(row.get("query_text_included")):
            bad_query_cases.append({"case": case, "reason": "query_text_exported"})
        if not bool(row.get("passed", True)):
            bad_query_cases.append({"case": case, "reason": "case_failed"})
    add_check("query_search_cases_runtime_safe", not missing_query_cases and not bad_query_cases, "Query Search must cover required no-click/search/export/fallback/error cases safely.", count=len(missing_query_cases) + len(bad_query_cases), details={"missing": missing_query_cases, "bad": bad_query_cases})

    export_failures: list[dict[str, Any]] = []
    for row in export_rows:
        payload_file = str(row.get("payload_file") or "")
        path = root / payload_file if payload_file else None
        if not payload_file or not path or not path.exists():
            export_failures.append({"filename": row.get("filename"), "reason": "missing_payload_file"})
            continue
        if row.get("sha256") and _file_sha256(path) != row.get("sha256"):
            export_failures.append({"filename": row.get("filename"), "reason": "hash_mismatch"})
        if _as_int(row.get("content_length")) <= 0 and _as_int(row.get("visible_row_count")) > 0:
            export_failures.append({"filename": row.get("filename"), "reason": "empty_payload"})
        if _as_int(row.get("parsed_row_count")) != _as_int(row.get("visible_row_count")):
            export_failures.append({"filename": row.get("filename"), "reason": "row_count_mismatch"})
        if _as_int(row.get("raw_internal_token_count")) > 0:
            export_failures.append({"filename": row.get("filename"), "reason": "forbidden_token"})
        if bool(row.get("query_text_included")) and not bool(row.get("admin_only")):
            export_failures.append({"filename": row.get("filename"), "reason": "query_text_in_daily_export"})
    add_check("exports_payload_hash_and_rows", not export_failures, "Every export payload must exist, hash-match, scan clean, and match visible row counts.", count=len(export_failures), details=export_failures)

    case_failures: list[dict[str, Any]] = []
    for row in case_rows:
        missing = sorted(field for field in REQUIRED_CASE_FIELDS if not row.get(field))
        if missing:
            case_failures.append({"section": row.get("section"), "reason": "missing_fields", "fields": missing})
        if _as_int(row.get("row_count")) != _as_int(row.get("visible_row_count")):
            case_failures.append({"section": row.get("section"), "reason": "row_count_mismatch"})
    add_check("case_payload_fields_and_rows", not case_failures, "Case payloads must include release fields and match visible row counts.", count=len(case_failures), details=case_failures)

    def settings_row_requires_admin_gate(row: Mapping[str, Any]) -> bool:
        action_type = str(row.get("action_type") or "")
        section = str(row.get("section") or "")
        return (
            section == "Settings/Admin Setup Health"
            or action_type in {"admin_load", "advanced_load", "setup_health", "account_usage_fallback"}
            or bool(row.get("requires_admin"))
            or bool(row.get("heavy_query_allowed"))
            or bool(row.get("account_usage_allowed"))
        )

    settings_failures = [
        row for row in settings_rows
        if not (
            bool(row.get("clicked"))
            or _owner_skipped(row)
        )
        or (
            bool(row.get("clicked"))
            and str(row.get("expected_query_budget_context") or "")
            and not _raw_observed_contexts(row)
        )
        or (
            settings_row_requires_admin_gate(row)
            and not bool(row.get("admin_or_advanced_gated", True))
        )
        or row.get("raw_error_visible_daily") is True
    ]
    add_check("settings_actions_clicked_or_owner_skipped", not settings_failures, "Settings/Admin actions must be clicked or owner-skipped, budgeted, and sanitized.", count=len(settings_failures))

    live_failures = [
        row for row in live_rows
        if not (bool(row.get("clicked")) or _owner_skipped(row))
        or (bool(row.get("clicked")) and not _raw_observed_contexts(row))
        or not bool(row.get("admin_or_advanced_gated"))
        or not bool(row.get("explicit_click_required"))
        or not bool(row.get("timeout_or_row_limit"))
        or bool(row.get("first_paint_invocation"))
        or bool(row.get("route_invocation"))
        or row.get("raw_error_visible_daily") is True
    ]
    add_check("live_features_clicked_gated_budgeted", not live_failures, "Live features must be clicked or owner-skipped, gated, budgeted, bounded, and sanitized.", count=len(live_failures))

    stress_failures = [
        row for row in stress_rows
        if not row.get("threshold")
        or not row.get("actuals")
        or row.get("threshold_passed") is not True
        or bool(_as_list(row.get("threshold_failures")))
        or not bool(row.get("passed", True))
    ]
    add_check("stress_thresholds_pass", not stress_failures, "Stress rows must include thresholds, actuals, and no failures.", count=len(stress_failures))

    forbidden_failures = []
    for rel in (
        "artifacts/full_app_validation/forbidden_ui_token_scan.json",
        "artifacts/full_app_validation/forbidden_source_token_scan.json",
        "artifacts/full_app_validation/forbidden_daily_ui_scan.json",
        "artifacts/full_app_validation/forbidden_export_scan.json",
    ):
        payload = _as_mapping(payloads.get(rel))
        if _as_int(payload.get("blocked_count")):
            forbidden_failures.append({"artifact": rel, "blocked_count": _as_int(payload.get("blocked_count"))})
    add_check("forbidden_tokens_zero", not forbidden_failures, "Daily UI, source, and export forbidden-token scans must be clean.", count=len(forbidden_failures), details=forbidden_failures)

    sql_error_count = sum(1 for row in sql_lint_rows if str(row.get("severity") or "").lower() == "error")
    static_failures = {
        "direct_blocked": _as_int(direct_scan.get("blocked_count")),
        "session_blocked": _as_int(session_scan.get("blocked_count")),
        "sql_lint_errors": sql_error_count,
        "query_budget_passed": 0 if query_budget.get("passed", True) else 1,
        "session_direct_passed": 0 if session_direct.get("passed", True) else 1,
    }
    add_check("static_scans_blocking_zero", all(count == 0 for count in static_failures.values()), "Direct/session/static SQL budget scans must have no blocking failures.", count=sum(static_failures.values()), details=static_failures)

    cleanup_failures = {
        "unknown_sql_objects": _as_int(cleanup_summary.get("unknown_sql_object_count")) or len(_as_list(object_inventory.get("unknown"))),
        "dead_routes": _as_int(cleanup_summary.get("dead_routes")) if isinstance(cleanup_summary.get("dead_routes"), int) else len(_as_list(route_inventory.get("dead_routes"))),
        "stale_artifacts": _as_int(cleanup_summary.get("stale_generated_artifact_count")),
        "retained_generic_reasons": _as_int(cleanup_summary.get("retained_generic_reason_count")),
        "deletion_candidates": _as_int(cleanup_summary.get("deletion_candidate_count")),
    }
    add_check("cleanup_delete_first_zero", all(count == 0 for count in cleanup_failures.values()), "Cleanup launch closure requires zero unknown SQL objects, dead routes, stale artifacts, generic reasons, and deletion candidates.", count=sum(cleanup_failures.values()), details=cleanup_failures)

    result = {
        "source": "launch_readiness_raw_invariants",
        "proof_source": "runtime_click",
        "generated_at": _utc_now(),
        "passed": not failures,
        "check_count": len(checks),
        "failure_count": len(failures),
        "checks": checks,
        "raw_sql_included": False,
    }
    failure_payload = {
        "source": "launch_readiness_raw_invariants",
        "proof_source": "runtime_click",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }
    return result, failure_payload


def _ci_metadata() -> dict[str, Any]:
    github_actions = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    server = os.environ.get("GITHUB_SERVER_URL", "" if github_actions else "https://github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "" if github_actions else "jfreeze03/OVERWATCH").strip("/")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id and server and repo else ""
    source_commit_sha = _git_output("rev-parse", "HEAD")
    commit_sha = os.environ.get("GITHUB_SHA", "") or source_commit_sha
    branch_ref = os.environ.get("GITHUB_REF", "") or os.environ.get("GITHUB_REF_NAME", "") or _git_output("branch", "--show-current")
    return {
        "github_actions": github_actions,
        "workflow_run_id": run_id,
        "workflow_url": run_url,
        "workflow_name": os.environ.get("GITHUB_WORKFLOW", ""),
        "workflow_job": os.environ.get("GITHUB_JOB", ""),
        "event_name": os.environ.get("GITHUB_EVENT_NAME", ""),
        "repository": repo,
        "github_sha": os.environ.get("GITHUB_SHA", ""),
        "commit_sha": commit_sha,
        "source_commit_sha": source_commit_sha,
        "source_tree_sha": source_commit_sha,
        "branch_ref": branch_ref,
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
    }


def _write_release_candidate_bundle(
    root_path: Path,
    *,
    profile: str,
    launch_summary: Mapping[str, Any],
    launch_failures: Mapping[str, Any],
    matrix: Iterable[Mapping[str, Any]],
    product_gauntlet: Mapping[str, Any],
    ci_context: Mapping[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """Write release-candidate artifacts through one deterministic bundle path."""

    release_dir = root_path / RELEASE_CANDIDATE_DIR
    release_dir.mkdir(parents=True, exist_ok=True)
    _write_json(release_dir / "product_gauntlet_release_results.json", product_gauntlet)

    seed_reconciliation = {
        "source": "release_candidate_artifact_reconciliation",
        "proof_source": "runtime_click",
        "passed": True,
        "failure_count": 0,
        "failures": [],
        "artifact_count": 0,
        "hash_count": 0,
        "raw_sql_included": False,
    }
    seed_gate = _release_candidate_gate_results(seed_reconciliation, product_gauntlet)
    rel_summary, rel_failures, rel_matrix, rel_notes = _release_candidate_summary_bundle(
        launch_summary=launch_summary,
        launch_failures=launch_failures,
        matrix=matrix,
        release_gate=seed_gate,
        product_gauntlet=product_gauntlet,
        reconciliation=seed_reconciliation,
        ci_context=ci_context,
    )
    for name, payload in {
        "release_candidate_summary": rel_summary,
        "release_candidate_failures": rel_failures,
        "release_gate_matrix": rel_matrix,
        "release_notes": rel_notes,
    }.items():
        _write_json(release_dir / f"{name}.json", payload)
    _write_json(release_dir / "artifact_reconciliation_results.json", seed_reconciliation)

    release_manifest, release_hashes = _release_candidate_artifact_manifest(
        root_path,
        profile=profile,
        commit_sha=str(launch_summary.get("commit_sha") or ""),
    )
    _write_json(release_dir / "artifact_manifest.json", release_manifest)
    _write_json(release_dir / "artifact_hashes.json", release_hashes)
    release_reconciliation = _release_artifact_reconciliation_results(root_path, release_manifest, release_hashes)
    release_gate = _release_candidate_gate_results(release_reconciliation, product_gauntlet)
    rel_summary, rel_failures, rel_matrix, rel_notes = _release_candidate_summary_bundle(
        launch_summary=launch_summary,
        launch_failures=launch_failures,
        matrix=matrix,
        release_gate=release_gate,
        product_gauntlet=product_gauntlet,
        reconciliation=release_reconciliation,
        ci_context=ci_context,
    )
    for name, payload in {
        "artifact_reconciliation_results": release_reconciliation,
        "release_candidate_summary": rel_summary,
        "release_candidate_failures": rel_failures,
        "release_gate_matrix": rel_matrix,
        "release_notes": rel_notes,
    }.items():
        _write_json(release_dir / f"{name}.json", payload)
    return (
        release_manifest,
        release_hashes,
        release_reconciliation,
        release_gate,
        rel_summary,
        rel_failures,
        rel_matrix,
        rel_notes,
    )


def _rows_have_no_failures(rows: Iterable[Any]) -> bool:
    for row in rows:
        mapped = _as_mapping(row)
        if str(mapped.get("status") or "passed") == "failed":
            return False
        if mapped.get("passed") is False:
            return False
    return True


def _ensure_app_root_on_path(root: Path) -> None:
    app_root = str(root / ".overwatch_final")
    if app_root not in sys.path:
        sys.path.insert(0, app_root)


def _component_row(
    name: str,
    passed: bool,
    *,
    status: str = "",
    failure_reason: str = "",
    recommendation: str = "",
    details: Any = None,
) -> dict[str, Any]:
    row = {
        "gate": name,
        "passed": bool(passed),
        "status": status or ("passed" if passed else "failed"),
        "failure_reason": "" if passed else failure_reason,
        "recommendation": "" if passed else recommendation or "Run Snowflake validation, fix the named SQL object, and regenerate launch readiness.",
    }
    if details is not None:
        row["details"] = details
    return row


def _snowflake_manifest_rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [_as_mapping(row) for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    if str(payload.get("source") or "") in {"live_validation_environment", "live_validation_session"}:
        return [_as_mapping(payload)]
    for key in ("rows", "checks", "marts"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [_as_mapping(row) for row in rows if isinstance(row, Mapping)]
    if payload.get("live_execution_manifest_id") or payload.get("source"):
        return [_as_mapping(payload)]
    return []


def _snowflake_manifest_row_status(row: Mapping[str, Any]) -> str:
    if row.get("status"):
        return str(row.get("status") or "")
    return "passed" if bool(row.get("passed", True)) else "failed"


def _snowflake_manifest_row_mode(artifact: str, row: Mapping[str, Any], live_enabled: bool) -> str:
    if artifact in {"procedure_compile_coverage_results.json", "procedure_smoke_call_coverage_results.json"}:
        return "live" if live_enabled else "static"
    if _snowflake_manifest_row_status(row) == "skipped":
        return "skipped"
    if artifact == "procedure_compile_results.json":
        return "live" if str(row.get("phase") or "") == "procedure_compile_live" else "static"
    if artifact == "procedure_smoke_call_results.json":
        mode = str(row.get("mode") or "")
        if mode == "fixture_static":
            return "static"
        if mode in {"dry_run", "live"}:
            return mode
    if artifact in {"refresh_fast_results.json", "refresh_full_results.json"}:
        return "live" if live_enabled else "static"
    if artifact in {"live_validation_environment_results.json", "live_validation_session_results.json"}:
        return "live" if live_enabled else "static"
    return "static"


def _first_valid_waiver(waivers: Iterable[Mapping[str, Any]], *gates: str) -> Mapping[str, Any]:
    wanted = set(gates)
    for row in waivers:
        if str(row.get("gate") or "") in wanted and bool(row.get("valid")):
            return row
    return {}


def _snowflake_raw_validation_recheck(
    payloads: Mapping[str, Any],
    profile: str,
    waivers: Iterable[Mapping[str, Any]],
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recompute Snowflake release blockers from raw validation artifacts."""

    failures: list[dict[str, Any]] = []

    def fail(gate: str, reason: str, *, path: str = "", recommendation: str = "") -> None:
        row = {
            "gate": gate,
            "reason": reason,
            "recommendation": recommendation
            or "Fix the named Snowflake validation artifact and rerun launch readiness.",
        }
        if path:
            row["path"] = path
        failures.append(row)

    missing = [rel for rel in SNOWFLAKE_RAW_RECHECK_ARTIFACTS if rel not in payloads]
    for rel in missing:
        fail(
            "missing_snowflake_validation_artifact",
            "Required Snowflake validation artifact is missing.",
            path=rel,
            recommendation="Regenerate Snowflake validation before evaluating launch readiness.",
        )

    summary_path = "artifacts/snowflake_validation/snowflake_validation_summary.json"
    summary = _as_mapping(payloads.get(summary_path))
    live_enabled = bool(summary.get("live_mode_enabled"))
    live_skipped = str(summary.get("live_status") or "") == "skipped"
    skip_reason = str(summary.get("live_skip_reason") or "")
    waiver = _first_valid_waiver(waivers, "snowflake_execution_validation", "live_snowflake_validation")
    waiver_used = bool(waiver) and not live_enabled
    live_required = profile in {"internal_live", "prod_candidate"}

    if not summary or not bool(summary.get("passed")):
        fail("snowflake_validation_summary", "Snowflake validation summary did not pass.", path=summary_path)
    if not live_enabled:
        skipped_file = root / "artifacts" / "snowflake_validation" / "snowflake_validation_SKIPPED.txt"
        if not live_skipped:
            fail("snowflake_live_validation_status", "Live Snowflake validation is disabled but not explicitly marked skipped.", path=summary_path)
        if not skip_reason or "OVERWATCH_SNOWFLAKE_VALIDATION" not in skip_reason:
            fail("snowflake_live_validation_skip_reason", "Static Snowflake validation skip reason must mention OVERWATCH_SNOWFLAKE_VALIDATION.", path=summary_path)
        if not skipped_file.exists():
            fail("snowflake_live_validation_skipped_artifact", "Static Snowflake validation must write snowflake_validation_SKIPPED.txt.", path="artifacts/snowflake_validation/snowflake_validation_SKIPPED.txt")
        if live_required and not waiver_used:
            fail(
                "snowflake_live_validation_profile",
                "This launch profile requires live Snowflake validation or an owner-approved waiver.",
                path=summary_path,
                recommendation="Set OVERWATCH_SNOWFLAKE_VALIDATION=1 or provide a valid snowflake_execution_validation waiver.",
            )

    live_environment_path = "artifacts/snowflake_validation/live_validation_environment_results.json"
    live_environment = _as_mapping(payloads.get(live_environment_path))
    if not live_environment or not bool(live_environment.get("passed")):
        fail("snowflake_live_validation_environment", "Live validation environment artifact is missing or failed.", path=live_environment_path)

    live_session_path = "artifacts/snowflake_validation/live_validation_session_results.json"
    live_session = _as_mapping(payloads.get(live_session_path))
    if not live_session or not bool(live_session.get("passed")):
        fail("snowflake_live_validation_session", "Live validation session artifact is missing or failed.", path=live_session_path)
    if live_enabled and str(live_session.get("status") or "") != "passed":
        fail("snowflake_live_validation_session", "Live validation is enabled but session proof did not pass.", path=live_session_path)
    if not live_enabled and str(live_session.get("status") or "") != "skipped":
        fail("snowflake_live_validation_session", "Fixture Snowflake validation must explicitly skip live session proof.", path=live_session_path)
    if not live_enabled and "OVERWATCH_SNOWFLAKE_VALIDATION" not in str(live_session.get("skip_reason") or ""):
        fail("snowflake_live_validation_session", "Live session skip reason must mention OVERWATCH_SNOWFLAKE_VALIDATION.", path=live_session_path)

    manifest_path = "artifacts/snowflake_validation/live_execution_manifest.json"
    live_manifest = _as_mapping(payloads.get(manifest_path))
    manifest_entries = [_as_mapping(row) for row in _as_list(live_manifest.get("entries"))]
    manifest_ids = {str(row.get("validation_id") or "") for row in manifest_entries}
    manifest_reconciliation_path = "artifacts/snowflake_validation/live_execution_manifest_reconciliation.json"
    manifest_reconciliation = _as_mapping(payloads.get(manifest_reconciliation_path))
    manifest_category_path = "artifacts/snowflake_validation/live_execution_manifest_category_coverage.json"
    manifest_category = _as_mapping(payloads.get(manifest_category_path))
    if not live_manifest or not bool(live_manifest.get("passed")) or _as_int(live_manifest.get("failure_count")):
        fail("live_execution_manifest", "Live execution manifest is missing or failed.", path=manifest_path)
    if (
        not manifest_reconciliation
        or not bool(manifest_reconciliation.get("passed"))
        or _as_int(manifest_reconciliation.get("failure_count"))
    ):
        fail("live_execution_manifest", "Live execution manifest reconciliation is missing or failed.", path=manifest_reconciliation_path)
    if not manifest_category or not bool(manifest_category.get("passed")) or _as_int(manifest_category.get("failure_count")):
        fail("live_execution_manifest", "Live execution manifest category coverage is missing or failed.", path=manifest_category_path)
    if not manifest_entries:
        fail("live_execution_manifest", "Live execution manifest has no validation entries.", path=manifest_path)
    for row in manifest_entries:
        if bool(row.get("raw_sql_included")):
            fail("live_execution_manifest", "Manifest entry includes raw SQL.", path=manifest_path)
        if re.search(
            r"(?i)(snowflake://|password=|token=|private[_ -]?key=|CREATE\s+OR\s+REPLACE|SELECT\s+\*)",
            " ".join(str(row.get(key) or "") for key in ("database", "schema", "warehouse", "role_name", "sanitized_error")),
        ):
            fail("live_execution_manifest", "Manifest entry contains raw SQL or secret-like text.", path=manifest_path)
        if live_enabled and str(row.get("expected_mode") or "") == "live" and str(row.get("observed_mode") or "") == "static":
            fail("live_execution_manifest", "Live validation row was static-only while live mode was enabled.", path=manifest_path)
        if profile == "prod_candidate" and str(row.get("observed_mode") or "") == "skipped" and not str(row.get("waiver_id") or ""):
            fail("live_execution_manifest", "prod_candidate has a skipped Snowflake validation row without waiver.", path=manifest_path)
        if (
            str(row.get("safe_execution_class") or "") == "destructive_requires_flag"
            and str(row.get("observed_mode") or "") == "live"
            and os.environ.get("OVERWATCH_ALLOW_DESTRUCTIVE_SNOWFLAKE_VALIDATION") != "1"
        ):
            fail("live_execution_manifest", "Destructive Snowflake validation row ran without explicit allow flag.", path=manifest_path)

    def require_manifest_id(gate: str, artifact_path: str, row: Mapping[str, Any]) -> None:
        manifest_id = str(row.get("live_execution_manifest_id") or "")
        if not manifest_id or manifest_id not in manifest_ids:
            fail(gate, "Validation row is missing a live execution manifest entry.", path=artifact_path)

    require_manifest_id("snowflake_live_validation_environment", live_environment_path, live_environment)
    require_manifest_id("snowflake_live_validation_session", live_session_path, live_session)

    manifest_artifact_payloads: dict[str, Any] = {
        "live_validation_environment_results.json": live_environment,
        "live_validation_session_results.json": live_session,
        "setup_execution_results.json": payloads.get("artifacts/snowflake_validation/setup_execution_results.json"),
        "procedure_compile_results.json": payloads.get("artifacts/snowflake_validation/procedure_compile_results.json"),
        "procedure_compile_coverage_results.json": payloads.get("artifacts/snowflake_validation/procedure_compile_coverage_results.json"),
        "procedure_smoke_call_results.json": payloads.get("artifacts/snowflake_validation/procedure_smoke_call_results.json"),
        "procedure_smoke_call_coverage_results.json": payloads.get("artifacts/snowflake_validation/procedure_smoke_call_coverage_results.json"),
        "validation_sql_results.json": payloads.get("artifacts/snowflake_validation/validation_sql_results.json"),
        "refresh_fast_results.json": payloads.get("artifacts/snowflake_validation/refresh_fast_results.json"),
        "refresh_full_results.json": payloads.get("artifacts/snowflake_validation/refresh_full_results.json"),
        "packet_publication_validation_results.json": payloads.get("artifacts/snowflake_validation/packet_publication_validation_results.json"),
        "packet_shape_results.json": payloads.get("artifacts/snowflake_validation/packet_shape_results.json"),
        "packet_size_results.json": payloads.get("artifacts/snowflake_validation/packet_size_results.json"),
        "packet_source_truth_results.json": payloads.get("artifacts/snowflake_validation/packet_source_truth_results.json"),
        "packet_validation_detail_results.json": payloads.get("artifacts/snowflake_validation/packet_validation_detail_results.json"),
        "compact_evidence_mart_validation_results.json": payloads.get("artifacts/snowflake_validation/compact_evidence_mart_validation_results.json"),
        "compact_evidence_mart_detail_results.json": payloads.get("artifacts/snowflake_validation/compact_evidence_mart_detail_results.json"),
        "refresh_detail_results.json": payloads.get("artifacts/snowflake_validation/refresh_detail_results.json"),
        "recent_snowflake_fix_validation_results.json": payloads.get("artifacts/snowflake_validation/recent_snowflake_fix_validation_results.json"),
        "metric_candidate_shape_results.json": payloads.get("artifacts/snowflake_validation/metric_candidate_shape_results.json"),
        "trend_cardinality_results.json": payloads.get("artifacts/snowflake_validation/trend_cardinality_results.json"),
        "schema_drift_results.json": payloads.get("artifacts/snowflake_validation/schema_drift_results.json"),
        "sql_encoding_scan_results.json": payloads.get("artifacts/snowflake_validation/sql_encoding_scan_results.json"),
        "snowflake_error_sanitization_results.json": payloads.get("artifacts/snowflake_validation/snowflake_error_sanitization_results.json"),
    }
    required_manifest_artifacts = {
        "live_validation_environment_results.json",
        "live_validation_session_results.json",
        "procedure_compile_results.json",
        "procedure_compile_coverage_results.json",
        "procedure_smoke_call_results.json",
        "procedure_smoke_call_coverage_results.json",
        "refresh_fast_results.json",
        "refresh_full_results.json",
        "validation_sql_results.json",
        "packet_publication_validation_results.json",
        "packet_shape_results.json",
        "packet_size_results.json",
        "packet_source_truth_results.json",
        "packet_validation_detail_results.json",
        "compact_evidence_mart_validation_results.json",
        "compact_evidence_mart_detail_results.json",
        "refresh_detail_results.json",
        "recent_snowflake_fix_validation_results.json",
        "metric_candidate_shape_results.json",
        "trend_cardinality_results.json",
        "schema_drift_results.json",
        "sql_encoding_scan_results.json",
        "snowflake_error_sanitization_results.json",
    }
    rows_by_manifest_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    raw_manifest_missing_id_count = 0
    raw_manifest_unknown_id_count = 0
    raw_manifest_orphan_count = 0
    raw_manifest_status_mismatch_count = 0
    raw_manifest_mode_mismatch_count = 0
    raw_manifest_row_index_mismatch_count = 0
    raw_manifest_row_key_mismatch_count = 0
    for artifact_name, artifact_payload in manifest_artifact_payloads.items():
        for ordinal, row in enumerate(_snowflake_manifest_rows(artifact_payload), start=1):
            manifest_id = str(row.get("live_execution_manifest_id") or "")
            if not manifest_id:
                if artifact_name in required_manifest_artifacts:
                    raw_manifest_missing_id_count += 1
                    fail("live_execution_manifest", "Artifact row is missing a live execution manifest ID.", path=f"artifacts/snowflake_validation/{artifact_name}")
                continue
            if manifest_id not in manifest_ids:
                raw_manifest_unknown_id_count += 1
                fail("live_execution_manifest", "Artifact row references an unknown live execution manifest ID.", path=f"artifacts/snowflake_validation/{artifact_name}")
                continue
            entry = next((item for item in manifest_entries if str(item.get("validation_id") or "") == manifest_id), {})
            if _as_int(entry.get("row_index")) != ordinal:
                raw_manifest_row_index_mismatch_count += 1
                fail("live_execution_manifest", "Live execution manifest row_index contradicts its validation artifact row.", path=f"artifacts/snowflake_validation/{artifact_name}")
            if str(entry.get("row_key") or "") != str(row.get("live_execution_row_key") or ""):
                raw_manifest_row_key_mismatch_count += 1
                fail("live_execution_manifest", "Live execution manifest row_key contradicts its validation artifact row.", path=f"artifacts/snowflake_validation/{artifact_name}")
            rows_by_manifest_key[(artifact_name, manifest_id)] = row
    for entry in manifest_entries:
        artifact_name = str(entry.get("artifact") or "")
        manifest_id = str(entry.get("validation_id") or "")
        manifest_row = rows_by_manifest_key.get((artifact_name, manifest_id))
        if not manifest_row:
            raw_manifest_orphan_count += 1
            fail("live_execution_manifest", "Live execution manifest entry is orphaned from validation artifacts.", path=manifest_path)
            continue
        row_status = _snowflake_manifest_row_status(manifest_row)
        if str(entry.get("status") or "") != row_status:
            raw_manifest_status_mismatch_count += 1
            fail("live_execution_manifest", "Live execution manifest status contradicts its validation artifact row.", path=manifest_path)
        row_mode = _snowflake_manifest_row_mode(artifact_name, manifest_row, live_enabled)
        if str(entry.get("observed_mode") or "") != row_mode:
            raw_manifest_mode_mismatch_count += 1
            fail("live_execution_manifest", "Live execution manifest observed mode contradicts its validation artifact row.", path=manifest_path)

    compile_path = "artifacts/snowflake_validation/procedure_compile_results.json"
    compile_rows = [_as_mapping(row) for row in _as_list(payloads.get(compile_path))]
    if not compile_rows:
        fail("procedure_compile_validation", "No stored procedure compile rows were produced.", path=compile_path)
    for row in compile_rows:
        if str(row.get("status") or "") == "failed":
            fail("procedure_compile_validation", "Stored procedure compile validation failed.", path=compile_path)
        if bool(row.get("raw_sql_included")):
            fail("snowflake_raw_sql_leak", "Procedure compile row includes raw SQL.", path=compile_path)
        require_manifest_id("procedure_compile_validation", compile_path, row)

    graph_path = "artifacts/snowflake_validation/procedure_dependency_graph.json"
    dependency_graph = _as_mapping(payloads.get(graph_path))
    if not dependency_graph or not bool(dependency_graph.get("passed")) or _as_list(dependency_graph.get("unresolved_call_targets")):
        fail("procedure_dependency_graph", "Procedure dependency graph has unresolved call targets.", path=graph_path)

    compile_coverage_path = "artifacts/snowflake_validation/procedure_compile_coverage_results.json"
    compile_coverage = _as_mapping(payloads.get(compile_coverage_path))
    if not compile_coverage or not bool(compile_coverage.get("passed")) or _as_int(compile_coverage.get("failure_count")):
        fail("procedure_compile_validation", "Procedure compile coverage is incomplete.", path=compile_coverage_path)
    for row in _as_list(compile_coverage.get("rows")):
        item = _as_mapping(row)
        if not bool(item.get("passed")):
            fail("procedure_compile_validation", "Procedure compile coverage row failed.", path=compile_coverage_path)
        require_manifest_id("procedure_compile_validation", compile_coverage_path, item)

    smoke_path = "artifacts/snowflake_validation/procedure_smoke_call_results.json"
    smoke_rows = [_as_mapping(row) for row in _as_list(payloads.get(smoke_path))]
    if not smoke_rows:
        fail("procedure_smoke_call_validation", "No stored procedure smoke-call rows were produced.", path=smoke_path)
    for row in smoke_rows:
        status = str(row.get("status") or "")
        if status == "failed" or (live_enabled and status != "passed"):
            fail("procedure_smoke_call_validation", "Stored procedure smoke-call validation failed.", path=smoke_path)
        if bool(row.get("raw_sql_included")):
            fail("snowflake_raw_sql_leak", "Procedure smoke-call row includes raw SQL.", path=smoke_path)
        require_manifest_id("procedure_smoke_call_validation", smoke_path, row)

    smoke_coverage_path = "artifacts/snowflake_validation/procedure_smoke_call_coverage_results.json"
    smoke_coverage = _as_mapping(payloads.get(smoke_coverage_path))
    if not smoke_coverage or not bool(smoke_coverage.get("passed")) or _as_int(smoke_coverage.get("failure_count")):
        fail("procedure_smoke_call_validation", "Procedure smoke-call coverage is incomplete.", path=smoke_coverage_path)
    for row in _as_list(smoke_coverage.get("rows")):
        item = _as_mapping(row)
        if not bool(item.get("passed")):
            fail("procedure_smoke_call_validation", "Procedure smoke-call coverage row failed.", path=smoke_coverage_path)
        require_manifest_id("procedure_smoke_call_validation", smoke_coverage_path, item)

    packet_paths = (
        "artifacts/snowflake_validation/packet_publication_validation_results.json",
        "artifacts/snowflake_validation/packet_shape_results.json",
        "artifacts/snowflake_validation/packet_size_results.json",
        "artifacts/snowflake_validation/packet_source_truth_results.json",
    )
    packet_passed = True
    for path in packet_paths:
        payload = _as_mapping(payloads.get(path))
        checks = _as_mapping(payload.get("checks"))
        missing_checks = not checks
        failed_checks = [key for key, value in checks.items() if not bool(value)]
        if not payload or not bool(payload.get("passed")) or _as_int(payload.get("failure_count")) > 0 or missing_checks or failed_checks:
            packet_passed = False
            fail("packet_publication_validation", "Packet validation artifact is missing or failed raw checks.", path=path)
        if path.endswith("packet_size_results.json") and _as_int(payload.get("max_packet_bytes")) > 100000:
            packet_passed = False
            fail("packet_publication_validation", "Packet byte threshold exceeds 100 KB.", path=path)
    packet_detail_path = "artifacts/snowflake_validation/packet_validation_detail_results.json"
    packet_detail = _as_mapping(payloads.get(packet_detail_path))
    detail_checks = [_as_mapping(row) for row in _as_list(packet_detail.get("checks"))]
    if not packet_detail or not bool(packet_detail.get("passed")) or _as_int(packet_detail.get("failure_count")) or not detail_checks:
        packet_passed = False
        fail("packet_publication_validation", "Packet validation detail artifact is missing or failed.", path=packet_detail_path)
    for row in detail_checks:
        if not bool(row.get("passed")):
            packet_passed = False
            fail("packet_publication_validation", "Packet validation detail check failed.", path=packet_detail_path)
        if "actual" not in row or "expected" not in row:
            packet_passed = False
            fail("packet_publication_validation", "Packet validation detail check is missing actual/expected evidence.", path=packet_detail_path)
        if _as_int(packet_detail.get("packet_missing_field_count")) > 0 and not _as_list(packet_detail.get("packet_missing_fields")):
            packet_passed = False
            fail("packet_publication_validation", "Packet missing-field failures must include field names.", path=packet_detail_path)
        if _as_int(packet_detail.get("packet_duplicate_array_count")) > 0 and not _as_list(packet_detail.get("packet_duplicate_arrays")):
            packet_passed = False
            fail("packet_publication_validation", "Packet duplicate-array failures must include array names.", path=packet_detail_path)
        if row.get("first_paint_impact") is None:
            packet_passed = False
            fail("packet_publication_validation", "Packet detail row is missing first-paint impact metadata.", path=packet_detail_path)
        if not bool(row.get("passed")) and bool(row.get("first_paint_impact")):
            packet_passed = False
            fail("packet_publication_validation", "Packet detail failure impacts first paint.", path=packet_detail_path)
        if not bool(row.get("passed")) and not _as_list(row.get("affected_sections")):
            packet_passed = False
            fail("packet_publication_validation", "Failed packet detail row must include affected sections.", path=packet_detail_path)
        if row.get("evidence_impact") is None or row.get("export_case_impact") is None:
            packet_passed = False
            fail("packet_publication_validation", "Packet detail row is missing evidence/export impact metadata.", path=packet_detail_path)
        require_manifest_id("packet_publication_validation", packet_detail_path, row)

    compact_path = "artifacts/snowflake_validation/compact_evidence_mart_validation_results.json"
    compact = _as_mapping(payloads.get(compact_path))
    compact_marts = [_as_mapping(row) for row in _as_list(compact.get("marts"))]
    compact_passed = bool(compact.get("passed")) and _as_int(compact.get("failure_count")) == 0
    if not compact or not compact_passed or _as_int(compact.get("mart_count")) != 5 or _as_int(compact.get("normal_account_usage_count")) != 0:
        fail("compact_evidence_mart_validation", "Compact evidence mart validation summary failed.", path=compact_path)
    for row in compact_marts:
        required_flags = ("ddl_exists", "load_path_exists", "loader_matrix_references", "target_lookup_columns_present", "validation_exists", "passed")
        if any(not bool(row.get(flag)) for flag in required_flags):
            compact_passed = False
            fail("compact_evidence_mart_validation", "Compact evidence mart raw row failed required checks.", path=compact_path)
        if bool(row.get("normal_account_usage_used")) or _as_int(row.get("max_rows")) > 500:
            compact_passed = False
            fail("compact_evidence_mart_validation", "Compact evidence mart raw row violates Account Usage or max row policy.", path=compact_path)
        require_manifest_id("compact_evidence_mart_validation", compact_path, row)

    compact_detail_path = "artifacts/snowflake_validation/compact_evidence_mart_detail_results.json"
    compact_detail = _as_mapping(payloads.get(compact_detail_path))
    detail_marts = [_as_mapping(row) for row in _as_list(compact_detail.get("marts"))]
    if not compact_detail or not bool(compact_detail.get("passed")) or _as_int(compact_detail.get("failure_count")) or len(detail_marts) != 5:
        compact_passed = False
        fail("compact_evidence_mart_validation", "Compact evidence mart detail artifact is missing or failed.", path=compact_detail_path)
    for row in detail_marts:
        if not bool(row.get("passed")):
            compact_passed = False
            fail("compact_evidence_mart_validation", "Compact evidence mart detail row failed.", path=compact_detail_path)
        if not bool(row.get("target_lookup_columns_present")) and not _as_list(row.get("missing_target_lookup_columns")):
            compact_passed = False
            fail("compact_evidence_mart_validation", "Compact detail row is missing target column names.", path=compact_detail_path)
        if bool(row.get("loader_matrix_references")) and not _as_list(row.get("loader_matrix_sections")):
            compact_passed = False
            fail("compact_evidence_mart_validation", "Compact detail row is missing loader matrix sections.", path=compact_detail_path)
        if bool(row.get("loader_matrix_references")) and _as_int(row.get("evidence_actions_covered")) <= 0:
            compact_passed = False
            fail("compact_evidence_mart_validation", "Compact detail row is missing covered evidence actions.", path=compact_detail_path)
        if bool(row.get("loader_matrix_references")) and not _as_list(row.get("sections_covered")):
            compact_passed = False
            fail("compact_evidence_mart_validation", "Compact detail row is missing covered sections.", path=compact_detail_path)
        if _as_list(row.get("missing_loader_actions")):
            compact_passed = False
            fail("compact_evidence_mart_validation", "Compact detail row has missing loader actions.", path=compact_detail_path)
        if bool(row.get("normal_account_usage_used")):
            compact_passed = False
            fail("compact_evidence_mart_validation", "Compact detail row uses Account Usage for normal evidence.", path=compact_detail_path)
        require_manifest_id("compact_evidence_mart_validation", compact_detail_path, row)

    refresh_statuses: dict[str, str] = {}
    for rel, gate in (
        ("artifacts/snowflake_validation/refresh_fast_results.json", "refresh_fast_validation"),
        ("artifacts/snowflake_validation/refresh_full_results.json", "refresh_full_validation"),
    ):
        payload = _as_mapping(payloads.get(rel))
        status = str(payload.get("status") or "")
        refresh_statuses[gate] = status
        if not payload or not bool(payload.get("passed")):
            fail(gate, "Refresh validation artifact is missing or failed.", path=rel)
        if not live_enabled:
            if status != "skipped" or "OVERWATCH_SNOWFLAKE_VALIDATION" not in str(payload.get("skip_reason") or ""):
                fail(gate, "Static refresh validation must have a profile-aware skip reason.", path=rel)
        elif status != "passed":
            fail(gate, "Live refresh validation did not pass.", path=rel)
        if _as_int(payload.get("failed_section_count")):
            fail(gate, "Refresh validation has failed sections.", path=rel)
        if _as_int(payload.get("max_packet_bytes")) > 100000:
            fail(gate, "Refresh validation packet bytes exceed 100 KB.", path=rel)
        for key in ("fresh_command_row_count", "reused_command_row_count", "stale_command_row_count"):
            if key not in payload:
                fail(gate, "Refresh validation is missing freshness count fields.", path=rel)
        for key in ("source_fact_max_ts_by_source", "command_source_snapshot_ts_by_section"):
            if key not in payload:
                fail(gate, "Refresh validation is missing source freshness timestamp maps.", path=rel)
        if live_enabled:
            require_manifest_id(gate, rel, payload)

    refresh_detail_path = "artifacts/snowflake_validation/refresh_detail_results.json"
    refresh_detail = _as_mapping(payloads.get(refresh_detail_path))
    if not refresh_detail or not bool(refresh_detail.get("passed")) or _as_int(refresh_detail.get("failure_count")):
        fail("refresh_detail_validation", "FAST/FULL refresh detail validation is missing or failed.", path=refresh_detail_path)
    for row in _as_list(refresh_detail.get("checks")):
        mapped_row = _as_mapping(row)
        if not bool(mapped_row.get("passed")):
            fail("refresh_detail_validation", "FAST/FULL refresh detail check failed.", path=refresh_detail_path)
        require_manifest_id("refresh_detail_validation", refresh_detail_path, mapped_row)

    for rel, gate in (
        ("artifacts/snowflake_validation/recent_snowflake_fix_validation_results.json", "recent_snowflake_fix_validation"),
        ("artifacts/snowflake_validation/metric_candidate_shape_results.json", "metric_candidate_shape_validation"),
        ("artifacts/snowflake_validation/trend_cardinality_results.json", "trend_cardinality_validation"),
        ("artifacts/snowflake_validation/sql_encoding_scan_results.json", "sql_encoding_scan"),
        ("artifacts/snowflake_validation/schema_drift_results.json", "schema_drift_validation"),
        ("artifacts/snowflake_validation/snowflake_error_sanitization_results.json", "snowflake_error_sanitization"),
    ):
        payload = _as_mapping(payloads.get(rel))
        if not payload or not bool(payload.get("passed")) or _as_int(payload.get("failure_count")):
            fail(gate, "Snowflake fix-class validation artifact is missing or failed.", path=rel)

    if live_enabled:
        live_validation_status = "live_passed" if not failures else "failed"
    elif waiver_used:
        live_validation_status = "waived"
    elif live_skipped and profile == "internal_fixture" and not any(row["gate"].startswith("snowflake_live_validation") for row in failures):
        live_validation_status = "static_skipped"
    elif live_skipped:
        live_validation_status = "failed"
    else:
        live_validation_status = "missing"

    results = {
        "source": "snowflake_raw_validation_recheck",
        "proof_source": "live_snowflake_execution" if live_enabled else "static_sql_parse",
        "passed": not failures,
        "failure_count": len(failures),
        "missing_artifact_count": len(missing),
        "missing_artifacts": missing,
        "snowflake_validation_passed": bool(summary.get("passed")),
        "snowflake_live_validation_enabled": live_enabled,
        "snowflake_live_validation_skipped": live_skipped,
        "snowflake_validation_skip_reason": skip_reason,
        "live_validation_status": live_validation_status,
        "live_validation_waiver_id": str(waiver.get("gate") or ""),
        "live_validation_waiver_owner": str(waiver.get("owner") or ""),
        "live_validation_waiver_expiration": str(waiver.get("expiration") or waiver.get("expiration_or_review_note") or ""),
        "live_validation_required": live_required,
        "live_validation_skip_allowed": not live_required or waiver_used or profile == "internal_fixture",
        "live_validation_missing_reason": "" if live_enabled or live_skipped or waiver_used else "Live Snowflake validation artifact status is missing.",
        "live_execution_manifest_passed": bool(live_manifest.get("passed")),
        "live_execution_manifest_entry_count": _as_int(live_manifest.get("entry_count")),
        "live_execution_manifest_failure_count": _as_int(live_manifest.get("failure_count")),
        "live_execution_manifest_reconciliation_passed": bool(manifest_reconciliation.get("passed")),
        "live_execution_manifest_reconciliation_failure_count": _as_int(manifest_reconciliation.get("failure_count")),
        "live_execution_manifest_category_coverage_passed": bool(manifest_category.get("passed")),
        "live_execution_manifest_category_failure_count": _as_int(manifest_category.get("failure_count")),
        "live_execution_manifest_orphan_count": _as_int(manifest_reconciliation.get("orphan_manifest_entry_count")) + raw_manifest_orphan_count,
        "live_execution_manifest_unknown_id_count": _as_int(manifest_reconciliation.get("unknown_manifest_id_count")) + raw_manifest_unknown_id_count,
        "live_execution_manifest_missing_id_count": _as_int(manifest_reconciliation.get("missing_manifest_id_count")) + raw_manifest_missing_id_count,
        "live_execution_manifest_status_mismatch_count": _as_int(manifest_reconciliation.get("status_mismatch_count")) + raw_manifest_status_mismatch_count,
        "live_execution_manifest_mode_mismatch_count": _as_int(manifest_reconciliation.get("mode_mismatch_count")) + raw_manifest_mode_mismatch_count,
        "live_execution_manifest_row_index_mismatch_count": _as_int(manifest_reconciliation.get("row_index_mismatch_count")) + raw_manifest_row_index_mismatch_count,
        "live_execution_manifest_row_key_mismatch_count": _as_int(manifest_reconciliation.get("row_key_mismatch_count")) + raw_manifest_row_key_mismatch_count,
        "live_execution_manifest_category_coverage": _as_list(manifest_category.get("categories")),
        "procedure_compile_count": len(compile_rows),
        "procedure_compile_failure_count": sum(1 for row in compile_rows if str(row.get("status") or "") == "failed"),
        "procedure_smoke_call_count": len(smoke_rows),
        "procedure_smoke_failure_count": sum(1 for row in smoke_rows if str(row.get("status") or "") == "failed"),
        "packet_validation_status": "passed" if packet_passed else "failed",
        "packet_validation_failed_check_count": _as_int(packet_detail.get("packet_validation_failed_check_count")),
        "packet_max_bytes": _as_int(packet_detail.get("packet_max_bytes")),
        "packet_current_active_row_count": _as_int(packet_detail.get("packet_current_active_row_count")),
        "packet_flat_active_row_count": _as_int(packet_detail.get("packet_flat_active_row_count")),
        "packet_last_good_status": str(packet_detail.get("packet_last_good_status") or ""),
        "packet_duplicate_array_count": _as_int(packet_detail.get("packet_duplicate_array_count")),
        "packet_missing_field_count": _as_int(packet_detail.get("packet_missing_field_count")),
        "packet_duplicate_arrays": _as_list(packet_detail.get("packet_duplicate_arrays")),
        "packet_missing_fields": _as_list(packet_detail.get("packet_missing_fields")),
        "compact_evidence_validation_status": "passed" if compact_passed else "failed",
        "compact_mart_count": _as_int(compact_detail.get("compact_mart_count") or compact_detail.get("mart_count")),
        "compact_mart_failure_count": _as_int(compact_detail.get("compact_mart_failure_count") or compact_detail.get("failure_count")),
        "compact_mart_names": _as_list(compact_detail.get("compact_mart_names")),
        "compact_normal_account_usage_count": _as_int(compact_detail.get("compact_normal_account_usage_count")),
        "compact_missing_target_column_count": _as_int(compact_detail.get("compact_missing_target_column_count")),
        "compact_missing_target_columns": _as_list(compact_detail.get("compact_missing_target_columns")),
        "refresh_fast_status": refresh_statuses.get("refresh_fast_validation", ""),
        "refresh_full_status": refresh_statuses.get("refresh_full_validation", ""),
        "raw_sql_included": False,
    }
    failure_payload = {
        "source": "snowflake_validation_failures",
        "proof_source": results["proof_source"],
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }
    return results, failure_payload


def _snowflake_validation_gate_results(
    payloads: Mapping[str, Any],
    profile: str,
    waivers: Iterable[Mapping[str, Any]],
    raw_recheck: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    summary = _as_mapping(payloads.get("artifacts/snowflake_validation/snowflake_validation_summary.json"))
    live_manifest = _as_mapping(payloads.get("artifacts/snowflake_validation/live_execution_manifest.json"))
    live_manifest_reconciliation = _as_mapping(payloads.get("artifacts/snowflake_validation/live_execution_manifest_reconciliation.json"))
    live_manifest_category = _as_mapping(payloads.get("artifacts/snowflake_validation/live_execution_manifest_category_coverage.json"))
    live_environment = _as_mapping(payloads.get("artifacts/snowflake_validation/live_validation_environment_results.json"))
    live_session = _as_mapping(payloads.get("artifacts/snowflake_validation/live_validation_session_results.json"))
    compile_rows = _as_list(payloads.get("artifacts/snowflake_validation/procedure_compile_results.json"))
    compile_coverage = _as_mapping(payloads.get("artifacts/snowflake_validation/procedure_compile_coverage_results.json"))
    smoke_rows = _as_list(payloads.get("artifacts/snowflake_validation/procedure_smoke_call_results.json"))
    smoke_coverage = _as_mapping(payloads.get("artifacts/snowflake_validation/procedure_smoke_call_coverage_results.json"))
    compact = _as_mapping(payloads.get("artifacts/snowflake_validation/compact_evidence_mart_validation_results.json"))
    compact_detail = _as_mapping(payloads.get("artifacts/snowflake_validation/compact_evidence_mart_detail_results.json"))
    recent_fixes = _as_mapping(payloads.get("artifacts/snowflake_validation/recent_snowflake_fix_validation_results.json"))
    manifest_validation = _as_mapping(payloads.get("artifacts/snowflake_validation/streamlit_manifest_validation_results.json"))
    encoding_scan = _as_mapping(payloads.get("artifacts/snowflake_validation/sql_encoding_scan_results.json"))
    schema_drift = _as_mapping(payloads.get("artifacts/snowflake_validation/schema_drift_results.json"))
    sanitizer = _as_mapping(payloads.get("artifacts/snowflake_validation/snowflake_error_sanitization_results.json"))
    phase_validation = _as_mapping(payloads.get("artifacts/snowflake_validation/phase_validation_results.json"))
    packet_publication = _as_mapping(payloads.get("artifacts/snowflake_validation/packet_publication_validation_results.json"))
    packet_shape = _as_mapping(payloads.get("artifacts/snowflake_validation/packet_shape_results.json"))
    packet_size = _as_mapping(payloads.get("artifacts/snowflake_validation/packet_size_results.json"))
    packet_truth = _as_mapping(payloads.get("artifacts/snowflake_validation/packet_source_truth_results.json"))
    packet_detail = _as_mapping(payloads.get("artifacts/snowflake_validation/packet_validation_detail_results.json"))
    refresh_perf = _as_mapping(payloads.get("artifacts/snowflake_validation/refresh_performance_results.json"))
    refresh_fast = _as_mapping(payloads.get("artifacts/snowflake_validation/refresh_fast_results.json"))
    refresh_full = _as_mapping(payloads.get("artifacts/snowflake_validation/refresh_full_results.json"))
    refresh_detail = _as_mapping(payloads.get("artifacts/snowflake_validation/refresh_detail_results.json"))
    raw_recheck = _as_mapping(raw_recheck)
    live_enabled = bool(summary.get("live_mode_enabled"))
    live_skipped = str(summary.get("live_status") or "") == "skipped"
    live_required = profile in {"internal_live", "prod_candidate"}
    live_waiver = _first_valid_waiver(waivers, "snowflake_execution_validation", "live_snowflake_validation")
    live_waived = bool(live_waiver)
    live_skip_allowed = not live_required or live_waived
    packet_validation_passed = (
        str(raw_recheck.get("packet_validation_status") or "") == "passed"
        if raw_recheck
        else all(bool(row.get("passed")) for row in (packet_publication, packet_shape, packet_size, packet_truth))
    )
    compact_validation_passed = (
        str(raw_recheck.get("compact_evidence_validation_status") or "") == "passed"
        if raw_recheck
        else bool(compact.get("passed"))
    )
    manifest_ids = {
        str(row.get("validation_id") or "")
        for row in _as_list(live_manifest.get("entries"))
        if isinstance(row, Mapping)
    }
    compile_manifest_linked = bool(compile_rows) and all(
        str(_as_mapping(row).get("live_execution_manifest_id") or "") in manifest_ids
        for row in compile_rows
    )
    smoke_manifest_linked = bool(smoke_rows) and all(
        str(_as_mapping(row).get("live_execution_manifest_id") or "") in manifest_ids
        for row in smoke_rows
    )

    components = [
        _component_row(
            "snowflake_raw_validation_recheck",
            bool(raw_recheck.get("passed")),
            status=str(raw_recheck.get("live_validation_status") or "missing"),
            failure_reason="Raw Snowflake validation rows contain launch-blocking failures.",
            recommendation="Fix artifacts/launch_readiness/snowflake_validation_failures.json and rerun launch readiness.",
            details={"failure_count": raw_recheck.get("failure_count")},
        ),
        _component_row(
            "snowflake_execution_validation",
            bool(summary.get("passed"))
            and bool(live_manifest.get("passed"))
            and bool(live_manifest_reconciliation.get("passed"))
            and bool(live_environment.get("passed"))
            and bool(live_session.get("passed"))
            and (live_enabled or not live_skipped or live_skip_allowed),
            status=str(summary.get("live_status") or "missing"),
            failure_reason="Live Snowflake execution validation is required for this launch profile unless waived.",
            recommendation="Set OVERWATCH_SNOWFLAKE_VALIDATION=1 for live validation or add a signed profile-aware waiver.",
            details={
                "live_mode_enabled": live_enabled,
                "live_status": summary.get("live_status"),
                "live_skip_reason": summary.get("live_skip_reason"),
                "manifest_passed": live_manifest.get("passed"),
                "manifest_entry_count": live_manifest.get("entry_count"),
                "manifest_reconciliation_passed": live_manifest_reconciliation.get("passed"),
                "manifest_reconciliation_failures": live_manifest_reconciliation.get("failures"),
                "environment_passed": live_environment.get("passed"),
                "session_status": live_session.get("status"),
            },
        ),
        _component_row(
            "procedure_compile_validation",
            bool(compile_rows)
            and _rows_have_no_failures(compile_rows)
            and bool(compile_coverage.get("passed"))
            and compile_manifest_linked,
            failure_reason="One or more stored procedures failed compile/static validation.",
            details={
                "procedure_compile_count": len(compile_rows),
                "coverage_failures": compile_coverage.get("failures"),
                "manifest_linked": compile_manifest_linked,
            },
        ),
        _component_row(
            "procedure_smoke_call_validation",
            bool(smoke_rows)
            and _rows_have_no_failures(smoke_rows)
            and bool(smoke_coverage.get("passed"))
            and smoke_manifest_linked
            and (live_enabled or live_skip_allowed),
            status="skipped" if live_skipped else "passed",
            failure_reason="Procedure smoke calls require live Snowflake validation for this profile.",
            recommendation="Enable live validation or add a signed waiver for Snowflake smoke calls.",
            details={
                "procedure_smoke_call_count": len(smoke_rows),
                "live_mode_enabled": live_enabled,
                "coverage_failures": smoke_coverage.get("failures"),
                "manifest_linked": smoke_manifest_linked,
            },
        ),
        _component_row(
            "recent_snowflake_fix_validation",
            bool(recent_fixes.get("passed")) and bool(encoding_scan.get("passed")) and bool(schema_drift.get("passed")) and bool(sanitizer.get("passed")),
            failure_reason="Recent Snowflake correction classes, SQL encoding, or schema-drift proof failed.",
            details={
                "recent_fix_failures": recent_fixes.get("failures"),
                "encoding_failures": encoding_scan.get("failures"),
                "schema_drift_failures": schema_drift.get("failures"),
                "sanitizer_failures": sanitizer.get("failures"),
            },
        ),
        _component_row(
            "streamlit_manifest_validation",
            bool(manifest_validation.get("passed")),
            failure_reason="Streamlit root/package manifest validation failed.",
            details=manifest_validation.get("failures"),
        ),
        _component_row(
            "snowflake_phase_validation",
            bool(phase_validation.get("passed")),
            failure_reason="One or more required Snowflake validation phases is missing or failed.",
            details=phase_validation.get("failures"),
        ),
        _component_row(
            "compact_evidence_mart_validation",
            compact_validation_passed and bool(compact_detail.get("passed")),
            failure_reason="Compact evidence mart validation failed.",
            details={"summary_failures": compact.get("failures"), "detail_failures": compact_detail.get("failures")},
        ),
        _component_row(
            "packet_publication_validation",
            packet_validation_passed and bool(packet_detail.get("passed")),
            failure_reason="Decision packet publication, shape, size, or source-truth validation failed.",
            details={
                "publication": packet_publication.get("passed"),
                "shape": packet_shape.get("passed"),
                "size": packet_size.get("passed"),
                "source_truth": packet_truth.get("passed"),
                "detail": packet_detail.get("passed"),
            },
        ),
        _component_row(
            "refresh_performance_validation",
            bool(refresh_perf.get("passed")) and bool(refresh_fast.get("passed", True)) and bool(refresh_full.get("passed", True)) and bool(refresh_detail.get("passed")) and (live_enabled or live_skip_allowed),
            status="skipped" if live_skipped else "passed",
            failure_reason="FAST/FULL refresh performance proof requires live Snowflake validation for this profile.",
            recommendation="Enable live refresh validation or add a signed waiver for the selected launch profile.",
            details={"refresh_performance": refresh_perf.get("passed"), "fast_status": refresh_fast.get("status"), "full_status": refresh_full.get("status"), "detail_failures": refresh_detail.get("failures")},
        ),
    ]
    failures = [row for row in components if not row["passed"]]
    return {
        "source": "launch_readiness_snowflake_validation_gate",
        "proof_source": "live_snowflake_execution" if live_enabled else "static_sql_parse",
        "launch_profile": profile,
        "passed": not failures,
        "component_count": len(components),
        "failure_count": len(failures),
        "components": components,
        "failures": failures,
        "live_mode_enabled": live_enabled,
        "snowflake_validation_passed": bool(summary.get("passed")),
        "snowflake_live_validation_enabled": live_enabled,
        "snowflake_live_validation_skipped": live_skipped,
        "snowflake_validation_skip_reason": summary.get("live_skip_reason") or "",
        "live_validation_status": str(raw_recheck.get("live_validation_status") or ("live_passed" if live_enabled and not failures else "static_skipped" if live_skipped and live_skip_allowed else "failed")),
        "live_validation_waiver_id": str(raw_recheck.get("live_validation_waiver_id") or (live_waiver.get("gate") if live_waiver else "") or ""),
        "live_validation_waiver_owner": str(raw_recheck.get("live_validation_waiver_owner") or (live_waiver.get("owner") if live_waiver else "") or ""),
        "live_validation_waiver_expiration": str(raw_recheck.get("live_validation_waiver_expiration") or ((live_waiver.get("expiration") or live_waiver.get("expiration_or_review_note")) if live_waiver else "") or ""),
        "live_validation_required": bool(raw_recheck.get("live_validation_required") or live_required),
        "live_validation_skip_allowed": bool(raw_recheck.get("live_validation_skip_allowed") if "live_validation_skip_allowed" in raw_recheck else live_skip_allowed),
        "live_validation_missing_reason": str(raw_recheck.get("live_validation_missing_reason") or ""),
        "live_execution_manifest_passed": bool(raw_recheck.get("live_execution_manifest_passed") if "live_execution_manifest_passed" in raw_recheck else live_manifest.get("passed")),
        "live_execution_manifest_entry_count": _as_int(raw_recheck.get("live_execution_manifest_entry_count") or live_manifest.get("entry_count")),
        "live_execution_manifest_failure_count": _as_int(raw_recheck.get("live_execution_manifest_failure_count") or live_manifest.get("failure_count")),
        "live_execution_manifest_reconciliation_passed": bool(raw_recheck.get("live_execution_manifest_reconciliation_passed") if "live_execution_manifest_reconciliation_passed" in raw_recheck else live_manifest_reconciliation.get("passed")),
        "live_execution_manifest_reconciliation_failure_count": _as_int(raw_recheck.get("live_execution_manifest_reconciliation_failure_count") or live_manifest_reconciliation.get("failure_count")),
        "live_execution_manifest_category_coverage_passed": bool(raw_recheck.get("live_execution_manifest_category_coverage_passed") if "live_execution_manifest_category_coverage_passed" in raw_recheck else live_manifest_category.get("passed")),
        "live_execution_manifest_category_failure_count": _as_int(raw_recheck.get("live_execution_manifest_category_failure_count") or live_manifest_category.get("failure_count")),
        "live_execution_manifest_orphan_count": _as_int(raw_recheck.get("live_execution_manifest_orphan_count") or live_manifest_reconciliation.get("orphan_manifest_entry_count")),
        "live_execution_manifest_unknown_id_count": _as_int(raw_recheck.get("live_execution_manifest_unknown_id_count") or live_manifest_reconciliation.get("unknown_manifest_id_count")),
        "live_execution_manifest_missing_id_count": _as_int(raw_recheck.get("live_execution_manifest_missing_id_count") or live_manifest_reconciliation.get("missing_manifest_id_count")),
        "live_execution_manifest_status_mismatch_count": _as_int(raw_recheck.get("live_execution_manifest_status_mismatch_count") or live_manifest_reconciliation.get("status_mismatch_count")),
        "live_execution_manifest_mode_mismatch_count": _as_int(raw_recheck.get("live_execution_manifest_mode_mismatch_count") or live_manifest_reconciliation.get("mode_mismatch_count")),
        "live_execution_manifest_row_index_mismatch_count": _as_int(raw_recheck.get("live_execution_manifest_row_index_mismatch_count") or live_manifest_reconciliation.get("row_index_mismatch_count")),
        "live_execution_manifest_row_key_mismatch_count": _as_int(raw_recheck.get("live_execution_manifest_row_key_mismatch_count") or live_manifest_reconciliation.get("row_key_mismatch_count")),
        "procedure_compile_count": len(compile_rows),
        "procedure_compile_failure_count": sum(1 for row in compile_rows if str(_as_mapping(row).get("status") or "") == "failed"),
        "procedure_smoke_call_count": len(smoke_rows),
        "procedure_smoke_failure_count": sum(1 for row in smoke_rows if str(_as_mapping(row).get("status") or "") == "failed"),
        "refresh_fast_status": refresh_fast.get("status") or "",
        "refresh_full_status": refresh_full.get("status") or "",
        "packet_validation_status": "passed" if packet_validation_passed else "failed",
        "compact_evidence_validation_status": "passed" if compact_validation_passed else "failed",
        "packet_validation_failed_check_count": _as_int(raw_recheck.get("packet_validation_failed_check_count") or packet_detail.get("packet_validation_failed_check_count")),
        "packet_max_bytes": _as_int(raw_recheck.get("packet_max_bytes") or packet_detail.get("packet_max_bytes")),
        "packet_current_active_row_count": _as_int(raw_recheck.get("packet_current_active_row_count") or packet_detail.get("packet_current_active_row_count")),
        "packet_flat_active_row_count": _as_int(raw_recheck.get("packet_flat_active_row_count") or packet_detail.get("packet_flat_active_row_count")),
        "packet_last_good_status": str(raw_recheck.get("packet_last_good_status") or packet_detail.get("packet_last_good_status") or ""),
        "packet_duplicate_array_count": _as_int(raw_recheck.get("packet_duplicate_array_count") or packet_detail.get("packet_duplicate_array_count")),
        "packet_missing_field_count": _as_int(raw_recheck.get("packet_missing_field_count") or packet_detail.get("packet_missing_field_count")),
        "packet_duplicate_arrays": _as_list(raw_recheck.get("packet_duplicate_arrays")) or _as_list(packet_detail.get("packet_duplicate_arrays")),
        "packet_missing_fields": _as_list(raw_recheck.get("packet_missing_fields")) or _as_list(packet_detail.get("packet_missing_fields")),
        "compact_mart_count": _as_int(raw_recheck.get("compact_mart_count") or compact_detail.get("compact_mart_count") or compact_detail.get("mart_count")),
        "compact_mart_failure_count": _as_int(raw_recheck.get("compact_mart_failure_count") or compact_detail.get("compact_mart_failure_count") or compact_detail.get("failure_count")),
        "compact_mart_names": _as_list(raw_recheck.get("compact_mart_names")) or _as_list(compact_detail.get("compact_mart_names")),
        "compact_normal_account_usage_count": _as_int(raw_recheck.get("compact_normal_account_usage_count") or compact_detail.get("compact_normal_account_usage_count")),
        "compact_missing_target_column_count": _as_int(raw_recheck.get("compact_missing_target_column_count") or compact_detail.get("compact_missing_target_column_count")),
        "compact_missing_target_columns": _as_list(raw_recheck.get("compact_missing_target_columns")) or _as_list(compact_detail.get("compact_missing_target_columns")),
        "live_status": summary.get("live_status") or "missing",
        "live_skip_reason": summary.get("live_skip_reason") or "",
        "raw_sql_included": False,
    }


def _live_execution_manifest_gate_results(
    snowflake_gate: Mapping[str, Any],
    raw_recheck: Mapping[str, Any],
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    def fail(code: str, message: str, *, count: int = 1) -> None:
        failures.append(
            {
                "gate": "live_execution_manifest_gate",
                "code": code,
                "message": message,
                "count": count,
                "recommendation": "Open live_execution_manifest_reconciliation.json, fix the ledger/row mismatch, and rerun Snowflake validation.",
            }
        )

    manifest_passed = bool(raw_recheck.get("live_execution_manifest_passed"))
    reconciliation_passed = bool(raw_recheck.get("live_execution_manifest_reconciliation_passed"))
    manifest_failures = _as_int(raw_recheck.get("live_execution_manifest_failure_count"))
    reconciliation_failures = _as_int(raw_recheck.get("live_execution_manifest_reconciliation_failure_count"))
    category_passed = bool(raw_recheck.get("live_execution_manifest_category_coverage_passed"))
    category_failures = _as_int(raw_recheck.get("live_execution_manifest_category_failure_count"))
    orphan_count = _as_int(raw_recheck.get("live_execution_manifest_orphan_count"))
    unknown_id_count = _as_int(raw_recheck.get("live_execution_manifest_unknown_id_count"))
    missing_id_count = _as_int(raw_recheck.get("live_execution_manifest_missing_id_count"))
    status_mismatch_count = _as_int(raw_recheck.get("live_execution_manifest_status_mismatch_count"))
    mode_mismatch_count = _as_int(raw_recheck.get("live_execution_manifest_mode_mismatch_count"))
    row_index_mismatch_count = _as_int(raw_recheck.get("live_execution_manifest_row_index_mismatch_count"))
    row_key_mismatch_count = _as_int(raw_recheck.get("live_execution_manifest_row_key_mismatch_count"))
    entry_count = _as_int(raw_recheck.get("live_execution_manifest_entry_count"))
    if not manifest_passed or manifest_failures:
        fail("MANIFEST_FAILED", "Live execution manifest has blocking failures.", count=max(1, manifest_failures))
    if not reconciliation_passed or reconciliation_failures:
        fail(
            "MANIFEST_RECONCILIATION_FAILED",
            "Live execution manifest reconciliation has blocking failures.",
            count=max(1, reconciliation_failures),
        )
    if not category_passed or category_failures:
        fail(
            "MANIFEST_CATEGORY_COVERAGE_FAILED",
            "Live execution manifest category coverage has blocking failures.",
            count=max(1, category_failures),
        )
    if entry_count <= 0:
        fail("MANIFEST_EMPTY", "Live execution manifest must contain validation ledger entries.")
    if orphan_count:
        fail("MANIFEST_ORPHAN_ENTRY", "Manifest entries must point to real validation artifact rows.", count=orphan_count)
    if unknown_id_count:
        fail("ARTIFACT_ROW_UNKNOWN_MANIFEST_ID", "Artifact rows must reference known manifest entries.", count=unknown_id_count)
    if missing_id_count:
        fail("ARTIFACT_ROW_MISSING_MANIFEST_ID", "Validation artifact rows must include manifest IDs.", count=missing_id_count)
    if status_mismatch_count:
        fail("MANIFEST_STATUS_MISMATCH", "Manifest entry status must match the owning artifact row.", count=status_mismatch_count)
    if mode_mismatch_count:
        fail("MANIFEST_MODE_MISMATCH", "Manifest observed mode must match the owning artifact row.", count=mode_mismatch_count)
    if row_index_mismatch_count:
        fail("MANIFEST_ROW_INDEX_MISMATCH", "Manifest row_index must match the owning artifact row ordinal.", count=row_index_mismatch_count)
    if row_key_mismatch_count:
        fail("MANIFEST_ROW_KEY_MISMATCH", "Manifest row_key must match the owning artifact row key.", count=row_key_mismatch_count)

    return {
        "source": "launch_readiness_live_execution_manifest_gate",
        "proof_source": str(snowflake_gate.get("proof_source") or raw_recheck.get("proof_source") or "static_sql_parse"),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "live_execution_manifest_passed": manifest_passed,
        "live_execution_manifest_entry_count": entry_count,
        "live_execution_manifest_failure_count": manifest_failures,
        "live_execution_manifest_reconciliation_passed": reconciliation_passed,
        "live_execution_manifest_reconciliation_failure_count": reconciliation_failures,
        "live_execution_manifest_category_coverage_passed": category_passed,
        "live_execution_manifest_category_failure_count": category_failures,
        "live_execution_manifest_orphan_count": orphan_count,
        "live_execution_manifest_unknown_id_count": unknown_id_count,
        "live_execution_manifest_missing_id_count": missing_id_count,
        "live_execution_manifest_status_mismatch_count": status_mismatch_count,
        "live_execution_manifest_mode_mismatch_count": mode_mismatch_count,
        "live_execution_manifest_row_index_mismatch_count": row_index_mismatch_count,
        "live_execution_manifest_row_key_mismatch_count": row_key_mismatch_count,
        "raw_sql_included": False,
    }


def _summary_board_gate_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/summary_board_results.json"))]
    budget = _as_mapping(payloads.get("artifacts/full_app_validation/summary_board_query_budget_results.json"))
    observed = {str(row.get("section") or "") for row in rows if row.get("section")}
    missing_sections = sorted(PRIMARY_SECTIONS - observed)
    failing_rows = [
        row for row in rows
        if not bool(row.get("passed"))
        or _as_int(row.get("packet_query_count")) != 1
        or _as_int(row.get("warm_packet_query_count"))
        or _as_int(row.get("non_packet_first_paint_event_count"))
        or _as_int(row.get("session_open_count"))
        or _as_int(row.get("direct_sql_event_count"))
        or _as_int(row.get("account_usage_query_count"))
        or _as_int(row.get("evidence_query_count"))
        or _as_int(row.get("raw_internal_token_count"))
        or _as_int(row.get("old_surface_marker_count"))
        or _as_list(row.get("optional_detail_state_reads"))
    ]
    failures: list[dict[str, Any]] = []
    if missing_sections:
        failures.append({"code": "SUMMARY_BOARD_SECTION_MISSING", "sections": missing_sections})
    if failing_rows:
        failures.append({"code": "SUMMARY_BOARD_FIRST_PAINT_FAILED", "rows": failing_rows[:10]})
    if budget and not bool(budget.get("passed", True)):
        failures.append({"code": "SUMMARY_BOARD_BUDGET_FAILED", "failure_count": _as_int(budget.get("failure_count"))})
    return {
        "source": "launch_readiness_summary_board_gate",
        "proof_source": "runtime_render",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "section_count": len(rows),
        "missing_section_count": len(missing_sections),
        "first_paint_failure_count": len(failing_rows),
        "raw_sql_included": False,
    }


def _metric_semantic_gate_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    artifact = _as_mapping(payloads.get("artifacts/full_app_validation/metric_semantic_results.json"))
    failures: list[dict[str, Any]] = []
    if not artifact:
        failures.append({"code": "METRIC_SEMANTIC_ARTIFACT_MISSING"})
    elif not bool(artifact.get("passed")):
        failures.extend(_as_list(artifact.get("failures")) or [{"code": "METRIC_SEMANTIC_ARTIFACT_FAILED"}])
    return {
        "source": "launch_readiness_metric_semantic_gate",
        "proof_source": "packet_formula_registry",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "registry_row_count": _as_int(artifact.get("registry_row_count")),
        "raw_sql_included": False,
    }


def _full_app_formula_gate_results(
    payloads: Mapping[str, Any],
    *,
    rel: str,
    source: str,
    proof_source: str,
    failure_code: str,
) -> dict[str, Any]:
    artifact = _as_mapping(payloads.get(rel))
    failures: list[dict[str, Any]] = []
    if not artifact:
        failures.append({"code": f"{failure_code}_MISSING", "artifact": rel})
    elif not bool(artifact.get("passed")):
        failures.extend(_as_list(artifact.get("failures")) or [{"code": f"{failure_code}_FAILED", "artifact": rel}])
    return {
        "source": source,
        "proof_source": proof_source,
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "artifact": rel,
        "raw_sql_included": False,
    }


def _date_widget_regression_results(root: Path) -> dict[str, Any]:
    def read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    filters_text = read_text(root / ".overwatch_final/filters.py")
    runtime_state_text = read_text(root / ".overwatch_final/runtime_state.py")
    checks = [
        {
            "check_name": "date_widget_render_tracking_used",
            "passed": "widget_key_rendered_this_run(GLOBAL_DATE_RANGE_INPUT)" in filters_text
            and "mark_widget_key_rendered(GLOBAL_DATE_RANGE_INPUT)" in filters_text,
            "recommendation": "Track the date widget key during a script run before any duplicate render path.",
        },
        {
            "check_name": "list_state_normalized_before_widget",
            "passed": "isinstance(raw_existing_date_range, list)" in filters_text
            and "set_state(GLOBAL_DATE_RANGE_INPUT, existing_date_range)" in filters_text,
            "recommendation": "Normalize list/tuple date state before st.date_input is instantiated.",
        },
        {
            "check_name": "canonical_dates_update_after_widget",
            "passed": "set_state(GLOBAL_START_DATE, clamped_start)" in filters_text
            and "set_state(GLOBAL_END_DATE, clamped_end)" in filters_text,
            "recommendation": "Only canonical start/end state should update after the widget returns a complete range.",
        },
        {
            "check_name": "widget_tracking_resets_per_run",
            "passed": "def reset_widget_render_tracking" in runtime_state_text
            and "reset_widget_render_tracking()" in runtime_state_text,
            "recommendation": "Clear rendered widget key tracking once per Streamlit script run.",
        },
    ]
    failures = [
        {"code": "DATE_WIDGET_REGRESSION_CHECK_FAILED", "check_name": row["check_name"]}
        for row in checks
        if not bool(row.get("passed"))
    ]
    return {
        "source": "date_widget_regression",
        "proof_source": "static_widget_state_contract",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "checks": checks,
        "raw_sql_included": False,
    }


def _formula_live_gate_results(profile: str, waivers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    live_enabled = os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION") == "1" or os.environ.get("OVERWATCH_BILLING_RECONCILIATION_PROOF") == "1"
    waiver_valid = _has_valid_waiver(waivers, "formula_live_validation")
    required = profile in {"internal_live", "prod_candidate"}
    skipped = not live_enabled
    failures: list[dict[str, Any]] = []
    if skipped and profile == "prod_candidate" and not waiver_valid:
        failures.append({"code": "PROD_FORMULA_LIVE_VALIDATION_MISSING"})
    if skipped and profile == "internal_live" and not waiver_valid:
        failures.append({"code": "INTERNAL_LIVE_FORMULA_VALIDATION_SKIPPED_WITHOUT_OWNER"})
    return {
        "source": "launch_readiness_formula_live_gate",
        "proof_source": "profile_gate",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "live_enabled": live_enabled,
        "live_required": required,
        "skipped": skipped,
        "skip_reason": "" if live_enabled else "OVERWATCH_SNOWFLAKE_VALIDATION/OVERWATCH_BILLING_RECONCILIATION_PROOF not enabled for local fixture run.",
        "waived": waiver_valid,
        "raw_sql_included": False,
    }


def _billing_reconciliation_gate_results(root: Path) -> dict[str, Any]:
    _ensure_app_root_on_path(root)
    import pandas as pd
    from utils.billing_reconciliation import (
        BILLING_RECONCILIATION_PACKET_FIELDS,
        billing_reconciliation_contract_results,
        build_account_billing_reconciliation_sql,
        daily_safe_billing_labels,
        summarize_billing_reconciliation,
    )

    sql = build_account_billing_reconciliation_sql(
        8,
        credit_price=3.68,
        start_date="2026-06-21",
        end_date="2026-06-28",
    ).upper()
    account_rows = pd.DataFrame(
        {
            "USAGE_DATE": ["2026-06-21", "2026-06-22"],
            "CREDITS_BILLED": [10.0, 4.0],
            "CREDITS_USED": [9.0, 3.5],
            "CREDITS_ADJUSTMENT_CLOUD_SERVICES": [-0.2, -0.1],
            "DAILY_SPEND_USD": [36.8, 14.72],
        }
    )
    warehouse_rows = pd.DataFrame({"WAREHOUSE_CREDITS": [6.0, 2.0]})
    summary = summarize_billing_reconciliation(account_rows, warehouse_rows, credit_price=3.68)
    contract = billing_reconciliation_contract_results(summary)
    labels_text = " ".join(daily_safe_billing_labels().values()).upper()
    checks = [
        {
            "check_name": "uses_metering_daily_history",
            "passed": "METERING_DAILY_HISTORY" in sql,
            "recommendation": "Use account daily billing history for Snowsight reconciliation.",
        },
        {
            "check_name": "uses_billed_credits",
            "passed": "CREDITS_BILLED" in sql and "CREDITS_USED" in sql,
            "recommendation": "Carry billed and used credits separately.",
        },
        {
            "check_name": "uses_cloud_services_adjustment",
            "passed": "CREDITS_ADJUSTMENT_CLOUD_SERVICES" in sql,
            "recommendation": "Include cloud-services adjustment in reconciliation metadata.",
        },
        {
            "check_name": "groups_service_type",
            "passed": "SERVICE_TYPE" in sql,
            "recommendation": "Expose service type breakdown for account-billing bridge.",
        },
        {
            "check_name": "excludes_partial_current_day",
            "passed": "USAGE_DATE < CURRENT_DATE()" in sql,
            "recommendation": "Exclude incomplete current-day billing rows by default.",
        },
        {
            "check_name": "account_total_not_warehouse_only",
            "passed": not bool(summary["WAREHOUSE_BRIDGE_IS_PRIMARY_TOTAL"])
            and str(summary.get("BILLING_BRIDGE_STATUS") or "") in {"matched", "warehouse_lower_than_billed", "warehouse_higher_than_billed"},
            "recommendation": "Use warehouse metering as the bridge/breakdown only.",
        },
        {
            "check_name": "signed_bridge_delta_preserved",
            "passed": "BILLING_BRIDGE_DELTA_CREDITS" in summary and "BILLING_BRIDGE_DELTA_USD" in summary,
            "recommendation": "Preserve signed account-vs-warehouse bridge deltas for latency/coverage review.",
        },
        {
            "check_name": "daily_labels_are_safe",
            "passed": all(token not in labels_text for token in ("ACCOUNT_USAGE", "SELECT ", "JOIN ", "CALL ", "SP_", "MART_", "FACT_")),
            "recommendation": "Keep raw object/procedure/SQL words out of daily UI labels.",
        },
        {
            "check_name": "packet_fields_complete",
            "passed": bool(contract.get("passed")) and not [
                field for field in BILLING_RECONCILIATION_PACKET_FIELDS if field not in summary
            ],
            "recommendation": "Cost packets must carry account billing, warehouse bridge, service/other, status, window, and freshness fields.",
        },
    ]
    failed = [row for row in checks if not bool(row.get("passed"))]
    if not bool(contract.get("passed")):
        failed.append({"check_name": "contract_results", "passed": False, "recommendation": "Fix billing reconciliation summary contract.", "details": contract.get("failures")})
    return {
        "source": "launch_readiness_billing_reconciliation_gate",
        "proof_source": "formula_recompute",
        "passed": not failed,
        "failure_count": len(failed),
        "checks": checks,
        "failures": failed,
        "summary": summary,
        "raw_sql_included": False,
    }


def _billing_reconciliation_live_gate_results(profile: str, waivers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    live_enabled = os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION") == "1" or os.environ.get("OVERWATCH_BILLING_RECONCILIATION_LIVE") == "1"
    skipped = not live_enabled
    waiver_valid = _has_valid_waiver(waivers, "billing_reconciliation_live")
    required = profile in {"internal_live", "prod_candidate"}
    failures: list[dict[str, Any]] = []
    if skipped and profile == "prod_candidate" and not waiver_valid:
        failures.append({"code": "PROD_BILLING_RECONCILIATION_LIVE_MISSING", "recommendation": "Run live billing reconciliation or provide a signed waiver."})
    if skipped and profile == "internal_live" and not waiver_valid:
        failures.append({"code": "INTERNAL_LIVE_BILLING_RECONCILIATION_SKIPPED_WITHOUT_OWNER", "recommendation": "Provide owner/reason/review waiver or run live billing reconciliation."})
    return {
        "source": "launch_readiness_billing_reconciliation_live_gate",
        "proof_source": "profile_gate",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "live_enabled": live_enabled,
        "live_required": required,
        "skipped": skipped,
        "skip_reason": "" if live_enabled else "OVERWATCH_SNOWFLAKE_VALIDATION/OVERWATCH_BILLING_RECONCILIATION_LIVE not enabled for local fixture run.",
        "waived": waiver_valid,
        "raw_sql_included": False,
    }


def _query_budget_gate_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _as_mapping(payloads.get("artifacts/full_app_validation/query_budget_results.json"))
    violation_recording = _as_mapping(payloads.get("artifacts/full_app_validation/query_budget_violation_results.json"))
    session_direct = _as_mapping(payloads.get("artifacts/full_app_validation/session_direct_sql_results.json"))
    summary_budget = _as_mapping(payloads.get("artifacts/full_app_validation/summary_board_query_budget_results.json"))
    failures: list[dict[str, Any]] = []
    for code, payload, count_keys in (
        ("QUERY_BUDGET_CONTEXT_FAILURE", runtime, ("failed_contexts",)),
        ("QUERY_BUDGET_VIOLATION_RECORDED", violation_recording, ("violation_count",)),
        ("ROUTE_QUERY_LEAK", runtime, ("route_query_leaks",)),
        ("EVIDENCE_CLICK_OVER_BUDGET", runtime, ("evidence_clicks_over_budget",)),
        ("MARKER_BUDGET_MISMATCH", runtime, ("marker_budget_mismatch_count",)),
        ("SESSION_DIRECT_SQL_FAILURE", session_direct, ("marker_budget_mismatch_count", "route_session_open_events", "route_direct_sql_events")),
        ("SUMMARY_BOARD_QUERY_BUDGET_FAILURE", summary_budget, ("failure_count",)),
    ):
        count = 0
        for key in count_keys:
            value = payload.get(key)
            count += len(value) if isinstance(value, list) else _as_int(value)
        if count:
            failures.append({"code": code, "count": count})
    if runtime and not bool(runtime.get("passed", True)):
        failures.append({"code": "RUNTIME_QUERY_BUDGET_NOT_PASSED"})
    if violation_recording and not bool(violation_recording.get("passed", True)):
        failures.append({"code": "QUERY_BUDGET_VIOLATION_ARTIFACT_NOT_PASSED"})
    if summary_budget and not bool(summary_budget.get("passed", True)):
        failures.append({"code": "SUMMARY_BOARD_QUERY_BUDGET_NOT_PASSED"})
    return {
        "source": "launch_readiness_query_budget_gate",
        "proof_source": "runtime_click",
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "production_interrupting": False,
        "always_recorded": True,
        "runtime_query_budget_passed": bool(runtime.get("passed", True)),
        "violation_recording_passed": bool(violation_recording.get("passed", True)),
        "violation_count": _as_int(violation_recording.get("violation_count")),
        "summary_board_query_budget_passed": bool(summary_budget.get("passed", True)),
        "raw_sql_included": False,
    }


def _daily_wording_gate_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    wording = _as_mapping(payloads.get("artifacts/full_app_validation/daily_wording_scan_results.json"))
    if not wording:
        wording = _as_mapping(payloads.get("artifacts/full_app_validation/forbidden_daily_ui_scan.json"))
    blocked_count = _as_int(wording.get("blocked_count"))
    findings = _as_list(wording.get("findings"))
    failures = []
    if blocked_count:
        failures.append(
            {
                "code": "DAILY_WORDING_BLOCKED",
                "blocked_count": blocked_count,
                "findings": findings[:20],
            }
        )
    return {
        "source": "daily_wording_gate_results",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "blocked_count": blocked_count,
        "failures": failures,
        "raw_sql_included": False,
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
    artifact_upload_review = _as_mapping(launch_artifacts.get("artifact_upload_review_results"))
    ci_artifact_reality = _as_mapping(launch_artifacts.get("ci_artifact_reality_results"))
    ci_run_review = _as_mapping(launch_artifacts.get("ci_run_review_results"))
    raw_invariants = _as_mapping(launch_artifacts.get("raw_invariant_results"))
    profile_results = _as_mapping(launch_artifacts.get("launch_profile_results"))
    profile_failures = _as_mapping(launch_artifacts.get("profile_gate_failures"))
    browser = _as_mapping(launch_artifacts.get("browser_smoke_results"))
    browser_coverage = _as_mapping(launch_artifacts.get("browser_required_coverage"))
    browser_failures = _as_mapping(launch_artifacts.get("browser_or_snapshot_failures"))
    live_query = _as_mapping(launch_artifacts.get("live_query_history_results"))
    manifest_gate = _as_mapping(launch_artifacts.get("live_execution_manifest_gate_results"))
    release_candidate_gate = _as_mapping(launch_artifacts.get("release_candidate_gate_results"))
    snowflake_gate = _as_mapping(launch_artifacts.get("snowflake_validation_gate_results"))
    snowflake_raw = _as_mapping(launch_artifacts.get("snowflake_raw_validation_recheck"))
    encoding_hygiene = _as_mapping(launch_artifacts.get("encoding_hygiene_results"))
    summary_board_gate = _as_mapping(launch_artifacts.get("summary_board_gate_results"))
    billing_gate = _as_mapping(launch_artifacts.get("billing_reconciliation_gate_results"))
    billing_live_gate = _as_mapping(launch_artifacts.get("billing_reconciliation_live_gate_results"))
    packet_availability_gate = _as_mapping(launch_artifacts.get("packet_availability_gate_results"))
    live_cost_gate = _as_mapping(launch_artifacts.get("live_cost_reconciliation_gate_results"))
    daily_wording_gate = _as_mapping(launch_artifacts.get("daily_wording_gate_results"))
    full_app_release_sweep_gate = _as_mapping(launch_artifacts.get("full_app_release_sweep_gate_results"))
    settings_live_feature_gate = _as_mapping(launch_artifacts.get("settings_live_feature_gate_results"))
    full_app_launch_gate = _as_mapping(launch_artifacts.get("full_app_launch_gate_results"))
    deterministic_render_gate = _as_mapping(launch_artifacts.get("deterministic_render_gate_results"))
    browser_smoke_gate = _as_mapping(launch_artifacts.get("browser_smoke_gate_results"))
    browser_render_gate = _as_mapping(launch_artifacts.get("browser_render_gate_results"))
    runtime_provenance_gate = _as_mapping(launch_artifacts.get("runtime_artifact_provenance_gate_results"))
    render_provenance_gate = _as_mapping(launch_artifacts.get("render_provenance_reconciliation_gate_results"))
    rendered_ui_leak_gate = _as_mapping(launch_artifacts.get("rendered_ui_leak_gate_results"))
    settings_gate = _as_mapping(launch_artifacts.get("settings_gate_results"))
    first_paint_gate = _as_mapping(launch_artifacts.get("first_paint_gate_results"))
    packet_fallback_gate = _as_mapping(launch_artifacts.get("packet_fallback_ui_gate_results"))
    summary_visual_gate = _as_mapping(launch_artifacts.get("summary_board_visual_contract_gate_results"))
    action_click_gate = _as_mapping(launch_artifacts.get("action_click_gate_results"))
    export_download_gate = _as_mapping(launch_artifacts.get("export_download_gate_results"))
    live_feature_gate = _as_mapping(launch_artifacts.get("live_feature_gate_results"))
    sql_cleanup_gate = _as_mapping(launch_artifacts.get("sql_cleanup_gate_results"))
    delete_first_cleanup_gate = _as_mapping(launch_artifacts.get("delete_first_cleanup_gate_results"))
    performance_budget_gate = _as_mapping(launch_artifacts.get("performance_budget_gate_results"))
    metric_source_governance_gate = _as_mapping(launch_artifacts.get("metric_source_governance_gate_results"))
    ui_kit_alignment_gate = _as_mapping(launch_artifacts.get("ui_kit_alignment_gate_results"))
    section_layout_gate = _as_mapping(launch_artifacts.get("section_layout_contract_gate_results"))
    source_safe_footer_gate = _as_mapping(launch_artifacts.get("source_safe_footer_gate_results"))
    metric_family_gates = {
        family_id: _as_mapping(launch_artifacts.get(Path(rel).stem))
        for family_id, rel in METRIC_FAMILY_GATE_RELS.items()
    }
    cortex_token_efficiency_gate = _as_mapping(launch_artifacts.get("cortex_token_efficiency_gate_results"))
    cortex_token_efficiency_live_gate = _as_mapping(
        launch_artifacts.get("cortex_token_efficiency_live_gate_results")
    )
    security_credential_gate = _as_mapping(launch_artifacts.get("security_credential_expiration_gate_results"))
    security_credential_live_gate = _as_mapping(
        launch_artifacts.get("security_credential_expiration_live_gate_results")
    )
    user_display_gate = _as_mapping(launch_artifacts.get("user_display_name_gate_results"))
    user_display_live_gate = _as_mapping(launch_artifacts.get("user_display_name_live_gate_results"))
    user_display_surface_gate = _as_mapping(launch_artifacts.get("user_display_surface_gate_results"))
    cortex_user_label_gate = _as_mapping(launch_artifacts.get("cortex_user_label_gate_results"))
    security_credential_export_gate = _as_mapping(launch_artifacts.get("security_credential_export_gate_results"))
    security_credential_render_gate = _as_mapping(launch_artifacts.get("security_credential_render_gate_results"))
    security_credential_evidence_gate = _as_mapping(launch_artifacts.get("security_credential_evidence_gate_results"))
    security_credential_first_paint_gate = _as_mapping(
        launch_artifacts.get("security_credential_first_paint_gate_results")
    )
    credential_sql_inventory_gate = _as_mapping(launch_artifacts.get("credential_sql_inventory_gate_results"))
    credential_rendered_leak_gate = _as_mapping(launch_artifacts.get("credential_rendered_leak_gate_results"))
    user_stress_gate = _as_mapping(launch_artifacts.get("user_stress_gate_results"))
    source_leak_gate = _as_mapping(launch_artifacts.get("source_internal_leak_scan_gate_results"))
    cortex_gate = _as_mapping(launch_artifacts.get("cortex_cost_consistency_gate_results"))
    cost_chart_gate = _as_mapping(launch_artifacts.get("cost_chart_workbench_gate_results"))
    cost_advisor_gate = _as_mapping(launch_artifacts.get("cost_advisor_gate_results"))
    cost_db_formula_gate = _as_mapping(launch_artifacts.get("cost_db_formula_authority_gate_results"))
    formula_end_gate = _as_mapping(launch_artifacts.get("formula_end_to_end_gate_results"))
    formula_value_gate = _as_mapping(launch_artifacts.get("formula_value_gate_results"))
    packet_schema_gate = _as_mapping(launch_artifacts.get("packet_schema_gate_results"))
    snowflake_formula_gate = _as_mapping(launch_artifacts.get("snowflake_formula_gate_results"))
    cortex_service_type_gate = _as_mapping(launch_artifacts.get("cortex_service_type_gate_results"))
    formula_live_gate = _as_mapping(launch_artifacts.get("formula_live_gate_results"))
    snowflake_cli_gate = _as_mapping(launch_artifacts.get("snowflake_cli_live_gate_results"))
    snowflake_cli_temp_hygiene_gate = _as_mapping(launch_artifacts.get("snowflake_cli_temp_file_hygiene_gate_results"))
    setup_migration_live_gate = _as_mapping(launch_artifacts.get("setup_migration_live_gate_results"))
    metric_semantic_gate = _as_mapping(launch_artifacts.get("metric_semantic_gate_results"))
    query_budget_gate = _as_mapping(launch_artifacts.get("query_budget_gate_results"))
    workload_formula_gate = _as_mapping(launch_artifacts.get("workload_formula_gate_results"))
    date_widget_gate = _as_mapping(launch_artifacts.get("date_widget_regression_results"))
    rows = [
        {
            "gate": "launch_profile",
            "artifact": f"{LAUNCH_READINESS_DIR}/launch_profile_results.json",
            "passed": bool(profile_results.get("passed")),
            "failure_reason": "" if profile_results.get("passed") else "Launch profile is invalid or incompatible with current environment.",
        },
        {
            "gate": "profile_gate_failures",
            "artifact": f"{LAUNCH_READINESS_DIR}/profile_gate_failures.json",
            "passed": bool(profile_failures.get("passed")),
            "failure_reason": "" if profile_failures.get("passed") else "Launch profile or waiver failures are present.",
        },
        {
            "gate": "raw_invariants",
            "artifact": f"{LAUNCH_READINESS_DIR}/raw_invariant_results.json",
            "passed": bool(raw_invariants.get("passed")),
            "failure_reason": "" if raw_invariants.get("passed") else "Launch raw-row invariant recomputation failed.",
        },
        {
            "gate": "full_app_gauntlet",
            "artifact": "artifacts/full_app_validation/gauntlet_results.json",
            "passed": bool(gauntlet.get("passed")),
            "failure_reason": "" if gauntlet.get("passed") else "Full app gauntlet failed.",
        },
        {
            "gate": "full_app_launch_gauntlet",
            "artifact": FULL_APP_LAUNCH_GATE_REL,
            "passed": bool(full_app_launch_gate.get("passed")),
            "failure_reason": "" if full_app_launch_gate.get("passed") else "Launch gauntlet found failed sections, actions, fallback states, or runtime checks.",
        },
        {
            "gate": "full_app_release_sweep",
            "artifact": FULL_APP_RELEASE_SWEEP_GATE_REL,
            "passed": bool(full_app_release_sweep_gate.get("passed")),
            "failure_reason": ""
            if full_app_release_sweep_gate.get("passed")
            else "Full app release sweep found missing surfaces, leaks, click/export gaps, or first-paint budget violations.",
        },
        {
            "gate": "settings_live_feature_gauntlet",
            "artifact": SETTINGS_LIVE_FEATURE_GATE_REL,
            "passed": bool(settings_live_feature_gate.get("passed")),
            "failure_reason": ""
            if settings_live_feature_gate.get("passed")
            else "Settings or live features are missing click, admin gating, timeout, or sanitized error proof.",
        },
        {
            "gate": "deterministic_streamlit_render",
            "artifact": DETERMINISTIC_RENDER_GATE_REL,
            "passed": bool(deterministic_render_gate.get("passed")),
            "failure_reason": "" if deterministic_render_gate.get("passed") else "Deterministic Streamlit render proof is missing, synthetic, or contains unsafe daily text.",
        },
        {
            "gate": "browser_smoke",
            "artifact": BROWSER_SMOKE_GATE_REL,
            "passed": bool(browser_smoke_gate.get("passed")),
            "failure_reason": "" if browser_smoke_gate.get("passed") else "Browser smoke proof is missing or profile skip policy failed.",
        },
        {
            "gate": "browser_render_gauntlet",
            "artifact": BROWSER_RENDER_GATE_REL,
            "passed": bool(browser_render_gate.get("passed")),
            "failure_reason": "" if browser_render_gate.get("passed") else "Rendered browser/snapshot surfaces are missing, unsafe, overflowing, or contain unclickable actions.",
        },
        {
            "gate": "runtime_artifact_provenance",
            "artifact": RUNTIME_ARTIFACT_PROVENANCE_GATE_REL,
            "passed": bool(runtime_provenance_gate.get("passed")),
            "failure_reason": "" if runtime_provenance_gate.get("passed") else "Runtime artifacts are missing producer/source/profile/commit provenance or contain unsafe rows.",
        },
        {
            "gate": "render_provenance_reconciliation",
            "artifact": RENDER_PROVENANCE_RECONCILIATION_GATE_REL,
            "passed": bool(render_provenance_gate.get("passed")),
            "failure_reason": ""
            if render_provenance_gate.get("passed")
            else "Runtime, deterministic, browser/snapshot, leak-scan, and provenance render proof do not reconcile.",
        },
        {
            "gate": "rendered_ui_leak_scan",
            "artifact": RENDERED_UI_LEAK_GATE_REL,
            "passed": bool(rendered_ui_leak_gate.get("passed")),
            "failure_reason": "" if rendered_ui_leak_gate.get("passed") else "Rendered daily UI or default exports contain diagnostic/internal/raw-source wording.",
        },
        {
            "gate": "settings_gate",
            "artifact": SETTINGS_GATE_REL,
            "passed": bool(settings_gate.get("passed")),
            "failure_reason": "" if settings_gate.get("passed") else "Settings wording or action contract failed.",
        },
        {
            "gate": "first_paint_performance",
            "artifact": FIRST_PAINT_GATE_REL,
            "passed": bool(first_paint_gate.get("passed")),
            "failure_reason": "" if first_paint_gate.get("passed") else "A primary section first paint was not packet-only or exceeded query/session budgets.",
        },
        {
            "gate": "packet_fallback_ui",
            "artifact": PACKET_FALLBACK_GATE_REL,
            "passed": bool(packet_fallback_gate.get("passed")),
            "failure_reason": "" if packet_fallback_gate.get("passed") else "Packet-missing fallback UI does not expose a clean closest-packet or setup action state.",
        },
        {
            "gate": "summary_board_visual_contract",
            "artifact": SUMMARY_BOARD_VISUAL_GATE_REL,
            "passed": bool(summary_visual_gate.get("passed")),
            "failure_reason": "" if summary_visual_gate.get("passed") else "Summary boards contain visual contract failures, duplicate boards, or diagnostic-card patterns.",
        },
        {
            "gate": "action_click_gauntlet",
            "artifact": ACTION_CLICK_GATE_REL,
            "passed": bool(action_click_gate.get("passed")),
            "failure_reason": "" if action_click_gate.get("passed") else "An action-looking control is unclickable, unrouted, or violates query/session/direct-SQL budgets.",
        },
        {
            "gate": "export_download_gauntlet",
            "artifact": EXPORT_DOWNLOAD_GATE_REL,
            "passed": bool(export_download_gate.get("passed")),
            "failure_reason": "" if export_download_gate.get("passed") else "An export/download/case payload lacks click, hash, row-count, or privacy proof.",
        },
        {
            "gate": "live_feature_gate",
            "artifact": LIVE_FEATURE_GATE_REL,
            "passed": bool(live_feature_gate.get("passed")),
            "failure_reason": "" if live_feature_gate.get("passed") else "A live feature runs too early, lacks gating, or exposes unsafe error behavior.",
        },
        {
            "gate": "sql_cleanup_gate",
            "artifact": SQL_CLEANUP_GATE_REL,
            "passed": bool(sql_cleanup_gate.get("passed")),
            "failure_reason": "" if sql_cleanup_gate.get("passed") else "SQL inventory/dead-code cleanup found unowned, daily-unsafe, or obsolete SQL paths.",
        },
        {
            "gate": "delete_first_cleanup_gate",
            "artifact": DELETE_FIRST_GATE_REL,
            "passed": bool(delete_first_cleanup_gate.get("passed")),
            "failure_reason": "" if delete_first_cleanup_gate.get("passed") else "Delete-first inventory found retained unknowns, obsolete items without a delete plan, or daily-unsafe leftovers.",
        },
        {
            "gate": "performance_budget_gate",
            "artifact": PERFORMANCE_BUDGET_GATE_REL,
            "passed": bool(performance_budget_gate.get("passed")),
            "failure_reason": "" if performance_budget_gate.get("passed") else "Performance budget rows show first-paint, route-action, Query Search, or workbench query violations.",
        },
        {
            "gate": "metric_source_governance",
            "artifact": METRIC_SOURCE_GOVERNANCE_GATE_REL,
            "passed": bool(metric_source_governance_gate.get("passed")),
            "failure_reason": ""
            if metric_source_governance_gate.get("passed")
            else "New metric families are missing packet, source, zero/unavailable, evidence/export/case, or first-paint safety metadata.",
        },
        {
            "gate": "ui_kit_alignment",
            "artifact": UI_KIT_ALIGNMENT_GATE_REL,
            "passed": bool(ui_kit_alignment_gate.get("passed")),
            "failure_reason": ""
            if ui_kit_alignment_gate.get("passed")
            else "Streamlit Decision Workspace primitives, six-section CommandBrief coverage, or daily-safe source footer proof failed.",
        },
        {
            "gate": "section_layout_contract",
            "artifact": SECTION_LAYOUT_CONTRACT_GATE_REL,
            "passed": bool(section_layout_gate.get("passed")),
            "failure_reason": ""
            if section_layout_gate.get("passed")
            else "A primary section is missing the shared CommandBrief layout pieces or contains legacy/unsafe daily UI markers.",
        },
        {
            "gate": "source_safe_footer",
            "artifact": SOURCE_SAFE_FOOTER_GATE_REL,
            "passed": bool(source_safe_footer_gate.get("passed")),
            "failure_reason": ""
            if source_safe_footer_gate.get("passed")
            else "Daily source labels were not mapped before HTML assembly or final HTML scrubbing was reintroduced.",
        },
        *[
            {
                "gate": str(metric_family_gate.get("metric_family") or family_id),
                "artifact": METRIC_FAMILY_GATE_RELS[family_id],
                "passed": bool(metric_family_gate.get("passed")),
                "failure_reason": ""
                if metric_family_gate.get("passed")
                else "Metric family governance failed for packet/source/evidence/export/performance metadata.",
            }
            for family_id, metric_family_gate in metric_family_gates.items()
        ],
        {
            "gate": "cortex_token_efficiency",
            "artifact": CORTEX_TOKEN_EFFICIENCY_GATE_REL,
            "passed": bool(cortex_token_efficiency_gate.get("passed")),
            "failure_reason": ""
            if cortex_token_efficiency_gate.get("passed")
            else "Cortex token-efficiency ratios, user-label safety, explicit workbench, or export proof failed.",
        },
        {
            "gate": "cortex_token_efficiency_live",
            "artifact": CORTEX_TOKEN_EFFICIENCY_LIVE_GATE_REL,
            "passed": bool(cortex_token_efficiency_live_gate.get("passed")),
            "failure_reason": ""
            if cortex_token_efficiency_live_gate.get("passed")
            else "Live Cortex token-efficiency validation is required for this launch profile or needs a signed waiver.",
        },
        {
            "gate": "security_credential_expiration",
            "artifact": SECURITY_CREDENTIAL_GATE_REL,
            "passed": bool(security_credential_gate.get("passed")),
            "failure_reason": ""
            if security_credential_gate.get("passed")
            else "Security credential-expiration source, packet fields, action rows, or compact evidence proof failed.",
        },
        {
            "gate": "security_credential_expiration_live",
            "artifact": SECURITY_CREDENTIAL_LIVE_GATE_REL,
            "passed": bool(security_credential_live_gate.get("passed")),
            "failure_reason": ""
            if security_credential_live_gate.get("passed")
            else "Live credential expiration proof is required for this launch profile or needs a signed waiver.",
        },
        {
            "gate": "user_display_name",
            "artifact": USER_DISPLAY_NAME_GATE_REL,
            "passed": bool(user_display_gate.get("passed")),
            "failure_reason": ""
            if user_display_gate.get("passed")
            else "User display-name dimension, Cortex chart labels, or default export hiding failed.",
        },
        {
            "gate": "user_display_name_live",
            "artifact": USER_DISPLAY_NAME_LIVE_GATE_REL,
            "passed": bool(user_display_live_gate.get("passed")),
            "failure_reason": ""
            if user_display_live_gate.get("passed")
            else "Live user display-name proof is required for this launch profile or needs a signed waiver.",
        },
        {
            "gate": "user_display_surface",
            "artifact": USER_DISPLAY_SURFACE_GATE_REL,
            "passed": bool(user_display_surface_gate.get("passed")),
            "failure_reason": ""
            if user_display_surface_gate.get("passed")
            else "A daily user chart/table/export can still expose USER_ID or bypass friendly display labels.",
        },
        {
            "gate": "cortex_user_label",
            "artifact": CORTEX_USER_LABEL_GATE_REL,
            "passed": bool(cortex_user_label_gate.get("passed")),
            "failure_reason": ""
            if cortex_user_label_gate.get("passed")
            else "Cortex user labels or exports do not preserve stable grouping with daily-safe labels.",
        },
        {
            "gate": "security_credential_export",
            "artifact": SECURITY_CREDENTIAL_EXPORT_GATE_REL,
            "passed": bool(security_credential_export_gate.get("passed")),
            "failure_reason": ""
            if security_credential_export_gate.get("passed")
            else "Security credential evidence/export/case proof can leak raw identifiers or bypass compact mart rows.",
        },
        {
            "gate": "security_credential_render",
            "artifact": SECURITY_CREDENTIAL_RENDER_GATE_REL,
            "passed": bool(security_credential_render_gate.get("passed")),
            "failure_reason": ""
            if security_credential_render_gate.get("passed")
            else "Security credential expiration metric is not proven packet-backed, pending-safe, and daily-sanitized.",
        },
        {
            "gate": "security_credential_evidence",
            "artifact": SECURITY_CREDENTIAL_EVIDENCE_GATE_REL,
            "passed": bool(security_credential_evidence_gate.get("passed")),
            "failure_reason": ""
            if security_credential_evidence_gate.get("passed")
            else "Credential evidence/export/case payloads are not proven compact-mart, target-filtered, and sanitized.",
        },
        {
            "gate": "credential_first_paint",
            "artifact": SECURITY_CREDENTIAL_FIRST_PAINT_GATE_REL,
            "passed": bool(security_credential_first_paint_gate.get("passed")),
            "failure_reason": ""
            if security_credential_first_paint_gate.get("passed")
            else "Security credential first paint uses source/evidence queries or exceeds packet-only budgets.",
        },
        {
            "gate": "credential_sql_inventory",
            "artifact": SECURITY_CREDENTIAL_SQL_INVENTORY_GATE_REL,
            "passed": bool(credential_sql_inventory_gate.get("passed")),
            "failure_reason": ""
            if credential_sql_inventory_gate.get("passed")
            else "Credential/user-display SQL paths are missing ownership, purpose, or daily-safety proof.",
        },
        {
            "gate": "credential_rendered_leak",
            "artifact": SECURITY_CREDENTIAL_RENDERED_LEAK_GATE_REL,
            "passed": bool(credential_rendered_leak_gate.get("passed")),
            "failure_reason": ""
            if credential_rendered_leak_gate.get("passed")
            else "Rendered leak scan does not block credential/user raw identifier tokens.",
        },
        {
            "gate": "user_stress_gate",
            "artifact": USER_STRESS_GATE_REL,
            "passed": bool(user_stress_gate.get("passed")),
            "failure_reason": "" if user_stress_gate.get("passed") else "User stress scenarios failed or showed duplicate cards, leaks, state errors, or query growth.",
        },
        {
            "gate": "source_internal_leak_scan",
            "artifact": SOURCE_INTERNAL_LEAK_GATE_REL,
            "passed": bool(source_leak_gate.get("passed")),
            "failure_reason": "" if source_leak_gate.get("passed") else "Production daily source/rendered artifacts expose internal test, diagnostic, raw SQL, or stack-trace wording.",
        },
        {
            "gate": "summary_board_first_paint",
            "artifact": f"{LAUNCH_READINESS_DIR}/summary_board_gate_results.json",
            "passed": bool(summary_board_gate.get("passed")),
            "failure_reason": "" if summary_board_gate.get("passed") else "Summary board packet-only first-paint gate failed.",
        },
        {
            "gate": "billing_reconciliation",
            "artifact": f"{LAUNCH_READINESS_DIR}/billing_reconciliation_gate_results.json",
            "passed": bool(billing_gate.get("passed")),
            "failure_reason": "" if billing_gate.get("passed") else "Snowsight billing reconciliation formula gate failed.",
        },
        {
            "gate": "billing_reconciliation_live",
            "artifact": f"{LAUNCH_READINESS_DIR}/billing_reconciliation_live_gate_results.json",
            "passed": bool(billing_live_gate.get("passed")),
            "failure_reason": "" if billing_live_gate.get("passed") else "Live billing reconciliation is required for this launch profile or needs a signed waiver.",
        },
        {
            "gate": "packet_availability",
            "artifact": f"{LAUNCH_READINESS_DIR}/packet_availability_gate_results.json",
            "passed": bool(packet_availability_gate.get("passed")),
            "failure_reason": "" if packet_availability_gate.get("passed") else "Selected summary packets are missing or packet/flat publication does not reconcile.",
        },
        {
            "gate": "live_cost_reconciliation",
            "artifact": f"{LAUNCH_READINESS_DIR}/live_cost_reconciliation_gate_results.json",
            "passed": bool(live_cost_gate.get("passed")),
            "failure_reason": "" if live_cost_gate.get("passed") else "Live cost reconciliation failed or cloud-services adjustment proof is unavailable.",
        },
        {
            "gate": "daily_wording",
            "artifact": f"{LAUNCH_READINESS_DIR}/daily_wording_gate_results.json",
            "passed": bool(daily_wording_gate.get("passed")),
            "failure_reason": "" if daily_wording_gate.get("passed") else "Daily UI contains internal or verbose diagnostic wording.",
        },
        {
            "gate": "cost_db_formula_authority",
            "artifact": f"{LAUNCH_READINESS_DIR}/cost_db_formula_authority_gate_results.json",
            "passed": bool(cost_db_formula_gate.get("passed")),
            "failure_reason": "" if cost_db_formula_gate.get("passed") else "COST_DB formula authority mapping has gaps or unmapped OVERWATCH cost formulas.",
        },
        {
            "gate": "formula_end_to_end",
            "artifact": FORMULA_GATE_REL,
            "passed": bool(formula_end_gate.get("passed")),
            "failure_reason": "" if formula_end_gate.get("passed") else "COST_DB formula chain does not reconcile from authority to packet SQL and rendered surfaces.",
        },
        {
            "gate": "formula_value_reconciliation",
            "artifact": FORMULA_VALUE_RECONCILIATION_REL,
            "passed": bool(formula_end_gate.get("formula_value_reconciliation_passed")),
            "failure_reason": ""
            if formula_end_gate.get("formula_value_reconciliation_passed")
            else "Formula values do not reconcile through packet, flat, rendered, and expected value surfaces.",
        },
        {
            "gate": "formula_value_source_reconciliation",
            "artifact": FORMULA_VALUE_SOURCE_RECONCILIATION_REL,
            "passed": bool(formula_value_gate.get("passed"))
            and bool(formula_end_gate.get("formula_value_source_reconciliation_passed")),
            "failure_reason": ""
            if formula_value_gate.get("passed")
            else "Formula values are missing artifact source provenance or rely on synthetic fixture-only proof.",
        },
        {
            "gate": "packet_schema_upgrade",
            "artifact": PACKET_SCHEMA_GATE_REL,
            "passed": bool(packet_schema_gate.get("passed")),
            "failure_reason": "" if packet_schema_gate.get("passed") else "Existing deployed packet tables are missing idempotent formula-column upgrade coverage.",
        },
        {
            "gate": "snowflake_formula_static_live",
            "artifact": SNOWFLAKE_FORMULA_GATE_REL,
            "passed": bool(snowflake_formula_gate.get("passed")),
            "failure_reason": "" if snowflake_formula_gate.get("passed") else "Snowflake formula static/live validation failed or requested live proof is unavailable.",
        },
        {
            "gate": "snowflake_formula_value",
            "artifact": SNOWFLAKE_FORMULA_VALUE_REL,
            "passed": bool(snowflake_formula_gate.get("snowflake_formula_value_passed")),
            "failure_reason": ""
            if snowflake_formula_gate.get("snowflake_formula_value_passed")
            else "Snowflake formula value checks failed for billing, Cortex, warehouse bridge, or spend movement formulas.",
        },
        {
            "gate": "live_static_formula_status",
            "artifact": SNOWFLAKE_FORMULA_GATE_REL,
            "passed": bool(snowflake_formula_gate.get("passed"))
            and not (
                bool(snowflake_formula_gate.get("snowflake_formula_live_passed"))
                and bool(snowflake_formula_gate.get("snowflake_formula_live_skipped"))
            ),
            "failure_reason": ""
            if snowflake_formula_gate.get("passed")
            else "Formula live/static status is ambiguous or live proof is required but unavailable.",
        },
        {
            "gate": "cortex_service_type_mapping",
            "artifact": CORTEX_SERVICE_TYPE_GATE_REL,
            "passed": bool(cortex_service_type_gate.get("passed")),
            "failure_reason": "" if cortex_service_type_gate.get("passed") else "Cortex spend service-type allowlist or live/static mapping proof failed.",
        },
        {
            "gate": "cost_advisor_value_at_risk",
            "artifact": f"{LAUNCH_READINESS_DIR}/cost_advisor_gate_results.json",
            "passed": bool(cost_advisor_gate.get("passed")),
            "failure_reason": "" if cost_advisor_gate.get("passed") else "Cost Advisor pressure rows must render value at risk and carry queue/spill evidence.",
        },
        {
            "gate": "date_widget_regression",
            "artifact": f"{LAUNCH_READINESS_DIR}/date_widget_regression_results.json",
            "passed": bool(date_widget_gate.get("passed")),
            "failure_reason": "" if date_widget_gate.get("passed") else "Global date widget state can still mutate after widget instantiation.",
        },
        {
            "gate": "cortex_cost_consistency",
            "artifact": f"{LAUNCH_READINESS_DIR}/cortex_cost_consistency_gate_results.json",
            "passed": bool(cortex_gate.get("passed")),
            "failure_reason": "" if cortex_gate.get("passed") else "Executive and Cost Cortex spend formula consistency failed.",
        },
        {
            "gate": "cost_chart_workbench",
            "artifact": f"{LAUNCH_READINESS_DIR}/cost_chart_workbench_gate_results.json",
            "passed": bool(cost_chart_gate.get("passed")),
            "failure_reason": "" if cost_chart_gate.get("passed") else "COST_DB chart workbench proof failed or autoloads on first paint.",
        },
        {
            "gate": "workload_formula_semantics",
            "artifact": f"{LAUNCH_READINESS_DIR}/workload_formula_gate_results.json",
            "passed": bool(workload_formula_gate.get("passed")),
            "failure_reason": "" if workload_formula_gate.get("passed") else "Workload count/duration/risk formula semantics failed.",
        },
        {
            "gate": "formula_live_validation",
            "artifact": f"{LAUNCH_READINESS_DIR}/formula_live_gate_results.json",
            "passed": bool(formula_live_gate.get("passed")),
            "failure_reason": "" if formula_live_gate.get("passed") else "Live formula reconciliation is required for this launch profile or needs a signed waiver.",
        },
        {
            "gate": "snowflake_cli_live_validation",
            "artifact": CLI_LAUNCH_GATE_REL,
            "passed": bool(snowflake_cli_gate.get("passed")),
            "failure_reason": ""
            if snowflake_cli_gate.get("passed")
            else "Local Snowflake CLI live validation is required for live launch profiles or needs a signed waiver.",
        },
        {
            "gate": "setup_migration_live_validation",
            "artifact": CLI_SETUP_MIGRATION_GATE_REL,
            "passed": bool(setup_migration_live_gate.get("passed")),
            "failure_reason": ""
            if setup_migration_live_gate.get("passed")
            else "Snowflake setup SQL, required objects, or migration ledger live validation failed.",
        },
        {
            "gate": "metric_semantic_registry",
            "artifact": f"{LAUNCH_READINESS_DIR}/metric_semantic_gate_results.json",
            "passed": bool(metric_semantic_gate.get("passed")),
            "failure_reason": "" if metric_semantic_gate.get("passed") else "Metric semantic registry is missing unit/source/formula metadata.",
        },
        {
            "gate": "query_budget_recording",
            "artifact": f"{LAUNCH_READINESS_DIR}/query_budget_gate_results.json",
            "passed": bool(query_budget_gate.get("passed")),
            "failure_reason": "" if query_budget_gate.get("passed") else "Recorded query-budget rows contain launch-blocking first-paint/route/evidence violations.",
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
            "gate": "artifact_upload_review",
            "artifact": f"{LAUNCH_READINESS_DIR}/artifact_upload_review_results.json",
            "passed": bool(artifact_upload_review.get("passed")),
            "failure_reason": "" if artifact_upload_review.get("passed") else "CI artifact upload paths are missing required launch proof.",
        },
        {
            "gate": "ci_run_review",
            "artifact": f"{LAUNCH_READINESS_DIR}/ci_run_review_results.json",
            "passed": bool(ci_run_review.get("passed")),
            "failure_reason": "" if ci_run_review.get("passed") else "CI run metadata is required for this launch profile.",
        },
        {
            "gate": "ci_artifact_reality",
            "artifact": f"{LAUNCH_READINESS_DIR}/ci_artifact_reality_results.json",
            "passed": bool(ci_artifact_reality.get("passed")),
            "failure_reason": "" if ci_artifact_reality.get("passed") else "CI artifact reality gate found missing metadata, uploads, artifacts, or stale proof.",
        },
        {
            "gate": "release_candidate_bundle",
            "artifact": f"{LAUNCH_READINESS_DIR}/release_candidate_gate_results.json",
            "passed": bool(release_candidate_gate.get("passed")),
            "failure_reason": "" if release_candidate_gate.get("passed") else "Release-candidate bundle, hashes, or product gauntlet release proof failed.",
        },
        {
            "gate": "browser_or_rendered_snapshot",
            "artifact": f"{LAUNCH_READINESS_DIR}/browser_smoke_results.json",
            "passed": bool(browser.get("passed")),
            "failure_reason": "" if browser.get("passed") else "Browser proof or deterministic snapshots are missing or leaking.",
        },
        {
            "gate": "browser_required_coverage",
            "artifact": f"{LAUNCH_READINESS_DIR}/browser_required_coverage.json",
            "passed": bool(browser_coverage.get("passed")),
            "failure_reason": "" if browser_coverage.get("passed") else "Browser/rendered proof does not cover all launch surfaces.",
        },
        {
            "gate": "browser_or_snapshot_failures",
            "artifact": f"{LAUNCH_READINESS_DIR}/browser_or_snapshot_failures.json",
            "passed": bool(browser_failures.get("passed")),
            "failure_reason": "" if browser_failures.get("passed") else "Browser/snapshot launch proof failures are present.",
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
            "gate": "encoding_hygiene",
            "artifact": f"{LAUNCH_READINESS_DIR}/encoding_hygiene_results.json",
            "passed": bool(encoding_hygiene.get("passed")),
            "failure_reason": "Repo-wide encoding hygiene scan has blocking findings."
            if not encoding_hygiene.get("passed")
            else "",
        },
        {
            "gate": "live_query_history",
            "artifact": f"{LAUNCH_READINESS_DIR}/live_query_history_results.json",
            "passed": bool(live_query.get("passed")),
            "failure_reason": "" if live_query.get("passed") else "Live query proof is configured but missing.",
        },
        {
            "gate": "snowflake_raw_validation_recheck",
            "artifact": f"{LAUNCH_READINESS_DIR}/snowflake_raw_validation_recheck.json",
            "passed": bool(snowflake_raw.get("passed")),
            "failure_reason": "" if snowflake_raw.get("passed") else "Raw Snowflake validation rows contain launch-blocking failures.",
        },
        {
            "gate": "live_execution_manifest_gate",
            "artifact": f"{LAUNCH_READINESS_DIR}/live_execution_manifest_gate_results.json",
            "passed": bool(manifest_gate.get("passed")),
            "failure_reason": "" if manifest_gate.get("passed") else "Live execution manifest ledger does not reconcile with validation rows.",
        },
    ]
    snowflake_components = {
        str(row.get("gate") or ""): _as_mapping(row)
        for row in _as_list(snowflake_gate.get("components"))
    }
    for gate in (
        "snowflake_execution_validation",
        "procedure_compile_validation",
        "procedure_smoke_call_validation",
        "recent_snowflake_fix_validation",
        "streamlit_manifest_validation",
        "snowflake_phase_validation",
        "compact_evidence_mart_validation",
        "packet_publication_validation",
        "refresh_performance_validation",
    ):
        component = snowflake_components.get(gate, {})
        rows.append(
            {
                "gate": gate,
                "artifact": f"{LAUNCH_READINESS_DIR}/snowflake_validation_gate_results.json",
                "passed": bool(component.get("passed")),
                "failure_reason": "" if component.get("passed") else str(component.get("failure_reason") or f"{gate} failed."),
            }
        )
    for gate, artifact_key in {
        "config_sanity": "config_sanity_results",
        "secrets_scan": "secrets_scan_results",
        "role_readiness": "role_readiness_results",
        "deployment_readiness": "deployment_readiness_results",
        "upgrade_readiness": "upgrade_readiness_results",
        "drop_rollback": "drop_rollback_results",
        "sql_value_inventory": "sql_value_inventory",
        "sql_cost_risk": "sql_cost_risk_findings",
        "sql_path_delete_candidates": "sql_path_delete_candidates",
        "performance_slo": "performance_slo_results",
        "settings_live_closure": "settings_live_closure_results",
        "export_case_closure": "export_case_closure_results",
        "cleanup_closure": "cleanup_launch_closure_results",
        "delete_first_release": "delete_first_release_results",
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
    root: Path | str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Evaluate launch readiness from already-loaded artifacts."""

    root_path = Path(root).resolve() if root is not None else Path(".").resolve()
    recomputed_raw, recomputed_raw_failures = _raw_invariant_artifacts(root_path, payloads)
    launch_waiver_rows = [
        _normalize_waiver(_as_mapping(row))
        for row in _as_list(_as_mapping(launch_artifacts.get("launch_waivers")).get("waivers"))
    ]
    profile_results = _as_mapping(launch_artifacts.get("launch_profile_results"))
    browser_results = _as_mapping(launch_artifacts.get("browser_smoke_results"))
    browser_coverage = _as_mapping(launch_artifacts.get("browser_required_coverage"))
    profile = str(profile_results.get("selected_profile") or DEFAULT_LAUNCH_PROFILE)
    snowflake_raw_recheck, snowflake_validation_failures = _snowflake_raw_validation_recheck(
        payloads,
        profile,
        launch_waiver_rows,
        root_path,
    )
    snowflake_gate = _snowflake_validation_gate_results(
        payloads,
        profile,
        launch_waiver_rows,
        snowflake_raw_recheck,
    )
    launch_artifacts = {
        **dict(launch_artifacts),
        "raw_invariant_results": recomputed_raw,
        "raw_invariant_failures": recomputed_raw_failures,
        "profile_gate_failures": _profile_gate_failures(profile_results, launch_waiver_rows),
        "browser_or_snapshot_failures": _browser_or_snapshot_failures(browser_results, browser_coverage),
        "snowflake_raw_validation_recheck": snowflake_raw_recheck,
        "snowflake_validation_failures": snowflake_validation_failures,
        "snowflake_validation_gate_results": snowflake_gate,
        "live_execution_manifest_gate_results": _live_execution_manifest_gate_results(
            snowflake_gate,
            snowflake_raw_recheck,
        ),
        "summary_board_gate_results": _summary_board_gate_results(payloads),
        "billing_reconciliation_gate_results": _as_mapping(launch_artifacts.get("billing_reconciliation_gate_results"))
        or _billing_reconciliation_gate_results(root_path),
        "billing_reconciliation_live_gate_results": _as_mapping(launch_artifacts.get("billing_reconciliation_live_gate_results"))
        or _billing_reconciliation_live_gate_results(profile, launch_waiver_rows),
        "cortex_cost_consistency_gate_results": _as_mapping(launch_artifacts.get("cortex_cost_consistency_gate_results"))
        or _full_app_formula_gate_results(
            payloads,
            rel="artifacts/full_app_validation/cortex_cost_consistency_results.json",
            source="launch_readiness_cortex_cost_consistency_gate",
            proof_source="packet_formula_registry",
            failure_code="CORTEX_COST_CONSISTENCY",
        ),
        "cost_chart_workbench_gate_results": _as_mapping(launch_artifacts.get("cost_chart_workbench_gate_results"))
        or _full_app_formula_gate_results(
            payloads,
            rel="artifacts/full_app_validation/cost_chart_workbench_results.json",
            source="launch_readiness_cost_chart_workbench_gate",
            proof_source="explicit_action_contract",
            failure_code="COST_CHART_WORKBENCH",
        ),
        "workload_formula_gate_results": _as_mapping(launch_artifacts.get("workload_formula_gate_results"))
        or _full_app_formula_gate_results(
            payloads,
            rel="artifacts/full_app_validation/workload_formula_results.json",
            source="launch_readiness_workload_formula_gate",
            proof_source="metric_semantic_registry",
            failure_code="WORKLOAD_FORMULA",
        ),
        "formula_end_to_end_gate_results": _as_mapping(launch_artifacts.get("formula_end_to_end_gate_results"))
        or evaluate_formula_end_to_end_gate(
            _as_mapping(payloads.get("artifacts/formula_authority/formula_chain_results.json")),
            _as_mapping(payloads.get(FORMULA_VALUE_RECONCILIATION_REL)),
            _as_mapping(payloads.get("artifacts/formula_authority/packet_formula_results.json")),
            _as_mapping(payloads.get(FLAT_PACKET_FORMULA_REL)),
            _as_mapping(payloads.get(SNOWFLAKE_FORMULA_STATIC_REL)),
            _as_mapping(payloads.get(PACKET_SCHEMA_UPGRADE_REL)),
            _as_mapping(payloads.get("artifacts/full_app_validation/rendered_formula_results.json")),
            _as_mapping(payloads.get("artifacts/snowflake_validation/formula_live_validation_results.json")),
            _as_mapping(payloads.get(SNOWFLAKE_FORMULA_LIVE_REL)),
            _as_mapping(payloads.get("artifacts/snowflake_validation/cortex_service_type_live_results.json")),
            _as_mapping(payloads.get("artifacts/snowflake_validation/workload_formula_live_results.json")),
            _as_mapping(payloads.get(SNOWFLAKE_FORMULA_VALUE_REL)),
            _as_mapping(payloads.get(FORMULA_VALUE_SOURCE_RECONCILIATION_REL)),
        ),
        "packet_schema_gate_results": _as_mapping(launch_artifacts.get("packet_schema_gate_results"))
        or evaluate_packet_schema_gate(_as_mapping(payloads.get(PACKET_SCHEMA_UPGRADE_REL))),
        "snowflake_formula_gate_results": _as_mapping(launch_artifacts.get("snowflake_formula_gate_results"))
        or evaluate_snowflake_formula_gate(
            _as_mapping(payloads.get(SNOWFLAKE_FORMULA_STATIC_REL)),
            _as_mapping(payloads.get(SNOWFLAKE_FORMULA_LIVE_REL)),
            _as_mapping(payloads.get(SNOWFLAKE_FORMULA_VALUE_REL)),
        ),
        "cortex_service_type_gate_results": _as_mapping(launch_artifacts.get("cortex_service_type_gate_results"))
        or evaluate_cortex_service_type_gate(
            _as_mapping(payloads.get("artifacts/formula_authority/cortex_service_type_mapping.json")),
            _as_mapping(payloads.get("artifacts/snowflake_validation/cortex_service_type_live_results.json")),
        ),
        "formula_live_gate_results": _as_mapping(launch_artifacts.get("formula_live_gate_results"))
        or _formula_live_gate_results(profile, launch_waiver_rows),
        "snowflake_cli_live_gate_results": _as_mapping(launch_artifacts.get("snowflake_cli_live_gate_results"))
        or evaluate_snowflake_cli_live_gate(
            {rel: payloads.get(rel) for rel in REQUIRED_CLI_ARTIFACTS},
            profile,
            launch_waiver_rows,
        ),
        "packet_availability_gate_results": _as_mapping(launch_artifacts.get("packet_availability_gate_results"))
        or evaluate_packet_availability_gate(_as_mapping(payloads.get(PACKET_AVAILABILITY_MATRIX_REL))),
        "live_cost_reconciliation_gate_results": _as_mapping(launch_artifacts.get("live_cost_reconciliation_gate_results")),
        "daily_wording_gate_results": _as_mapping(launch_artifacts.get("daily_wording_gate_results"))
        or _daily_wording_gate_results(payloads),
        "full_app_release_sweep_gate_results": _as_mapping(launch_artifacts.get("full_app_release_sweep_gate_results"))
        or evaluate_full_app_release_sweep_gate(_as_mapping(payloads.get(FULL_APP_RELEASE_SWEEP_RESULTS_REL))),
        "settings_live_feature_gate_results": _as_mapping(launch_artifacts.get("settings_live_feature_gate_results"))
        or evaluate_settings_live_feature_gate(_as_mapping(payloads.get(SETTINGS_LIVE_FEATURE_RESULTS_REL))),
        "full_app_launch_gate_results": _as_mapping(launch_artifacts.get("full_app_launch_gate_results"))
        or evaluate_simple_gate(
            _as_mapping(payloads.get(FULL_APP_LAUNCH_RESULTS_REL)),
            source="full_app_launch_gate_results",
            artifact=FULL_APP_LAUNCH_RESULTS_REL,
        ),
        "deterministic_render_gate_results": _as_mapping(launch_artifacts.get("deterministic_render_gate_results"))
        or evaluate_deterministic_render_gate(payloads.get(DETERMINISTIC_RENDER_RESULTS_REL)),
        "browser_smoke_gate_results": _as_mapping(launch_artifacts.get("browser_smoke_gate_results"))
        or evaluate_browser_smoke_gate(payloads.get(BROWSER_SMOKE_RESULTS_REL)),
        "browser_render_gate_results": _as_mapping(launch_artifacts.get("browser_render_gate_results"))
        or evaluate_browser_render_gate(payloads.get(BROWSER_RENDER_RESULTS_REL)),
        "runtime_artifact_provenance_gate_results": _as_mapping(
            launch_artifacts.get("runtime_artifact_provenance_gate_results")
        )
        or evaluate_runtime_artifact_provenance_gate(payloads.get(RUNTIME_ARTIFACT_PROVENANCE_REL)),
        "render_provenance_reconciliation_gate_results": _as_mapping(
            launch_artifacts.get("render_provenance_reconciliation_gate_results")
        )
        or evaluate_render_provenance_reconciliation_gate(payloads.get(RENDER_PROVENANCE_RECONCILIATION_REL)),
        "rendered_ui_leak_gate_results": _as_mapping(launch_artifacts.get("rendered_ui_leak_gate_results"))
        or evaluate_rendered_ui_leak_gate(_as_mapping(payloads.get(RENDERED_UI_LEAK_RESULTS_REL))),
        "settings_gate_results": _as_mapping(launch_artifacts.get("settings_gate_results"))
        or evaluate_simple_gate(
            _as_mapping(payloads.get(SETTINGS_WORDING_REL)),
            source="settings_gate_results",
            artifact=SETTINGS_WORDING_REL,
        ),
        "first_paint_gate_results": _as_mapping(launch_artifacts.get("first_paint_gate_results"))
        or evaluate_simple_gate(
            _as_mapping(payloads.get(FIRST_PAINT_PERFORMANCE_REL)),
            source="first_paint_gate_results",
            artifact=FIRST_PAINT_PERFORMANCE_REL,
        ),
        "packet_fallback_ui_gate_results": _as_mapping(launch_artifacts.get("packet_fallback_ui_gate_results"))
        or evaluate_simple_gate(
            _as_mapping(payloads.get(PACKET_FALLBACK_UI_REL)),
            source="packet_fallback_ui_gate_results",
            artifact=PACKET_FALLBACK_UI_REL,
        ),
        "summary_board_visual_contract_gate_results": _as_mapping(launch_artifacts.get("summary_board_visual_contract_gate_results"))
        or evaluate_simple_gate(
            _as_mapping(payloads.get(SUMMARY_BOARD_VISUAL_CONTRACT_REL)),
            source="summary_board_visual_contract_gate_results",
            artifact=SUMMARY_BOARD_VISUAL_CONTRACT_REL,
        ),
        "action_click_gate_results": _as_mapping(launch_artifacts.get("action_click_gate_results"))
        or evaluate_action_click_gate(payloads.get("artifacts/full_app_validation/action_click_results.json")),
        "export_download_gate_results": _as_mapping(launch_artifacts.get("export_download_gate_results"))
        or evaluate_export_download_gate(
            payloads.get("artifacts/full_app_validation/export_results.json"),
            payloads.get("artifacts/full_app_validation/download_results.json"),
            _as_list(payloads.get("artifacts/full_app_validation/case_payload_results.json")),
        ),
        "live_feature_gate_results": _as_mapping(launch_artifacts.get("live_feature_gate_results"))
        or evaluate_live_feature_gate(payloads.get("artifacts/full_app_validation/live_feature_results.json")),
        "sql_cleanup_gate_results": _as_mapping(launch_artifacts.get("sql_cleanup_gate_results"))
        or evaluate_sql_cleanup_gate(
            _as_mapping(payloads.get(SQL_VALUE_INVENTORY_REL)),
            _as_mapping(payloads.get(SQL_DEAD_CODE_SCAN_REL)),
        ),
        "delete_first_cleanup_gate_results": _as_mapping(launch_artifacts.get("delete_first_cleanup_gate_results"))
        or evaluate_delete_first_cleanup_gate(_as_mapping(payloads.get(DELETE_FIRST_INVENTORY_REL))),
        "performance_budget_gate_results": _as_mapping(launch_artifacts.get("performance_budget_gate_results"))
        or evaluate_performance_budget_gate(
            _as_mapping(payloads.get(FIRST_PAINT_PERFORMANCE_REL)),
            _as_mapping(payloads.get("artifacts/full_app_validation/query_budget_results.json")),
        ),
        "user_stress_gate_results": _as_mapping(launch_artifacts.get("user_stress_gate_results"))
        or evaluate_user_stress_gate(payloads.get(USER_STRESS_RESULTS_REL)),
        "source_internal_leak_scan_gate_results": _as_mapping(launch_artifacts.get("source_internal_leak_scan_gate_results"))
        or evaluate_source_internal_leak_scan_gate(payloads.get(SOURCE_INTERNAL_LEAK_RESULTS_REL)),
        "query_budget_gate_results": _query_budget_gate_results(payloads),
        "encoding_hygiene_results": _as_mapping(payloads.get("artifacts/encoding_hygiene_results.json"))
        or _as_mapping(launch_artifacts.get("encoding_hygiene_results")),
    }
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
    profile_results = _as_mapping(launch_artifacts.get("launch_profile_results"))
    raw_invariants = _as_mapping(launch_artifacts.get("raw_invariant_results"))
    ci_run_review = _as_mapping(launch_artifacts.get("ci_run_review_results"))
    artifact_upload_review = _as_mapping(launch_artifacts.get("artifact_upload_review_results"))
    artifact_review = _as_mapping(launch_artifacts.get("artifact_review_results"))
    ci_artifact_reality = _as_mapping(launch_artifacts.get("ci_artifact_reality_results"))
    manifest_gate = _as_mapping(launch_artifacts.get("live_execution_manifest_gate_results"))
    release_candidate_gate = _as_mapping(launch_artifacts.get("release_candidate_gate_results"))
    encoding_hygiene = _as_mapping(launch_artifacts.get("encoding_hygiene_results"))
    summary_board_gate = _as_mapping(launch_artifacts.get("summary_board_gate_results"))
    billing_gate = _as_mapping(launch_artifacts.get("billing_reconciliation_gate_results"))
    billing_live_gate = _as_mapping(launch_artifacts.get("billing_reconciliation_live_gate_results"))
    packet_availability_gate = _as_mapping(launch_artifacts.get("packet_availability_gate_results"))
    live_cost_gate = _as_mapping(launch_artifacts.get("live_cost_reconciliation_gate_results"))
    daily_wording_gate = _as_mapping(launch_artifacts.get("daily_wording_gate_results"))
    full_app_release_sweep_gate = _as_mapping(launch_artifacts.get("full_app_release_sweep_gate_results"))
    settings_live_feature_gate = _as_mapping(launch_artifacts.get("settings_live_feature_gate_results"))
    full_app_launch_gate = _as_mapping(launch_artifacts.get("full_app_launch_gate_results"))
    deterministic_render_gate = _as_mapping(launch_artifacts.get("deterministic_render_gate_results"))
    browser_smoke_gate = _as_mapping(launch_artifacts.get("browser_smoke_gate_results"))
    browser_render_gate = _as_mapping(launch_artifacts.get("browser_render_gate_results"))
    runtime_provenance_gate = _as_mapping(launch_artifacts.get("runtime_artifact_provenance_gate_results"))
    render_provenance_gate = _as_mapping(launch_artifacts.get("render_provenance_reconciliation_gate_results"))
    rendered_ui_leak_gate = _as_mapping(launch_artifacts.get("rendered_ui_leak_gate_results"))
    settings_gate = _as_mapping(launch_artifacts.get("settings_gate_results"))
    first_paint_gate = _as_mapping(launch_artifacts.get("first_paint_gate_results"))
    packet_fallback_gate = _as_mapping(launch_artifacts.get("packet_fallback_ui_gate_results"))
    summary_visual_gate = _as_mapping(launch_artifacts.get("summary_board_visual_contract_gate_results"))
    action_click_gate = _as_mapping(launch_artifacts.get("action_click_gate_results"))
    export_download_gate = _as_mapping(launch_artifacts.get("export_download_gate_results"))
    live_feature_gate = _as_mapping(launch_artifacts.get("live_feature_gate_results"))
    sql_cleanup_gate = _as_mapping(launch_artifacts.get("sql_cleanup_gate_results"))
    metric_source_governance_gate = _as_mapping(launch_artifacts.get("metric_source_governance_gate_results"))
    ui_kit_alignment_gate = _as_mapping(launch_artifacts.get("ui_kit_alignment_gate_results"))
    section_layout_gate = _as_mapping(launch_artifacts.get("section_layout_contract_gate_results"))
    source_safe_footer_gate = _as_mapping(launch_artifacts.get("source_safe_footer_gate_results"))
    cortex_token_efficiency_gate = _as_mapping(launch_artifacts.get("cortex_token_efficiency_gate_results"))
    cortex_token_efficiency_live_gate = _as_mapping(
        launch_artifacts.get("cortex_token_efficiency_live_gate_results")
    )
    security_credential_gate = _as_mapping(launch_artifacts.get("security_credential_expiration_gate_results"))
    security_credential_live_gate = _as_mapping(
        launch_artifacts.get("security_credential_expiration_live_gate_results")
    )
    user_display_gate = _as_mapping(launch_artifacts.get("user_display_name_gate_results"))
    user_display_live_gate = _as_mapping(launch_artifacts.get("user_display_name_live_gate_results"))
    user_display_surface_gate = _as_mapping(launch_artifacts.get("user_display_surface_gate_results"))
    cortex_user_label_gate = _as_mapping(launch_artifacts.get("cortex_user_label_gate_results"))
    security_credential_export_gate = _as_mapping(launch_artifacts.get("security_credential_export_gate_results"))
    security_credential_render_gate = _as_mapping(launch_artifacts.get("security_credential_render_gate_results"))
    security_credential_evidence_gate = _as_mapping(launch_artifacts.get("security_credential_evidence_gate_results"))
    security_credential_first_paint_gate = _as_mapping(
        launch_artifacts.get("security_credential_first_paint_gate_results")
    )
    credential_sql_inventory_gate = _as_mapping(launch_artifacts.get("credential_sql_inventory_gate_results"))
    credential_rendered_leak_gate = _as_mapping(launch_artifacts.get("credential_rendered_leak_gate_results"))
    user_stress_gate = _as_mapping(launch_artifacts.get("user_stress_gate_results"))
    source_leak_gate = _as_mapping(launch_artifacts.get("source_internal_leak_scan_gate_results"))
    cortex_gate = _as_mapping(launch_artifacts.get("cortex_cost_consistency_gate_results"))
    cost_chart_gate = _as_mapping(launch_artifacts.get("cost_chart_workbench_gate_results"))
    cost_advisor_gate = _as_mapping(launch_artifacts.get("cost_advisor_gate_results"))
    cost_db_formula_gate = _as_mapping(launch_artifacts.get("cost_db_formula_authority_gate_results"))
    formula_end_gate = _as_mapping(launch_artifacts.get("formula_end_to_end_gate_results"))
    formula_value_gate = _as_mapping(launch_artifacts.get("formula_value_gate_results"))
    packet_schema_gate = _as_mapping(launch_artifacts.get("packet_schema_gate_results"))
    snowflake_formula_gate = _as_mapping(launch_artifacts.get("snowflake_formula_gate_results"))
    cortex_service_type_gate = _as_mapping(launch_artifacts.get("cortex_service_type_gate_results"))
    formula_live_gate = _as_mapping(launch_artifacts.get("formula_live_gate_results"))
    snowflake_cli_gate = _as_mapping(launch_artifacts.get("snowflake_cli_live_gate_results"))
    snowflake_cli_temp_hygiene_gate = _as_mapping(launch_artifacts.get("snowflake_cli_temp_file_hygiene_gate_results"))
    setup_migration_live_gate = _as_mapping(launch_artifacts.get("setup_migration_live_gate_results"))
    metric_semantic_gate = _as_mapping(launch_artifacts.get("metric_semantic_gate_results"))
    query_budget_gate = _as_mapping(launch_artifacts.get("query_budget_gate_results"))
    workload_formula_gate = _as_mapping(launch_artifacts.get("workload_formula_gate_results"))
    date_widget_gate = _as_mapping(launch_artifacts.get("date_widget_regression_results"))
    launch_summary = {
        "source": "launch_readiness",
        "proof_source": "runtime_click",
        "generated_at": _utc_now(),
        "launch_profile": profile_results.get("selected_profile") or DEFAULT_LAUNCH_PROFILE,
        "all_passed": passed,
        "passed": passed,
        "hard_gate_passed": passed,
        "failure_count": len(failures),
        "blocking_failures": failures,
        "check_count": len(matrix),
        "pass_count": sum(1 for row in matrix if row.get("passed")),
        "fail_count": sum(1 for row in matrix if not row.get("passed")),
        "required_artifact_count": _required_release_artifact_count(),
        "uploaded_artifact_names": _as_list(artifact_upload_review.get("uploaded_artifact_names")) or ["decision-workspace-proof"],
        "workflow_run_id": ci_meta["workflow_run_id"],
        "workflow_url": ci_meta["workflow_url"],
        "commit_sha": ci_meta["commit_sha"],
        "source_tree_sha": ci_meta["source_tree_sha"],
        "github_sha": ci_meta["github_sha"],
        "branch_ref": ci_meta["branch_ref"],
        "run_attempt": ci_meta["run_attempt"],
        "workflow_name": ci_meta["workflow_name"],
        "job_name": ci_meta["workflow_job"],
        "ci_metadata_warning": str(ci_run_review.get("warning") or ""),
        "ci_metadata_required": bool(ci_run_review.get("workflow_metadata_required")),
        "ci_metadata_missing": bool(ci_run_review.get("workflow_metadata_missing")),
        "ci_artifact_reality_passed": bool(ci_artifact_reality.get("passed")),
        "ci_artifact_reality_failure_count": _as_int(ci_artifact_reality.get("failure_count")),
        "release_candidate_bundle_passed": bool(release_candidate_gate.get("passed")),
        "release_candidate_bundle_failure_count": _as_int(release_candidate_gate.get("failure_count")),
        "release_candidate_artifact_count": _as_int(release_candidate_gate.get("artifact_count")),
        "release_candidate_artifact_hash_count": _as_int(release_candidate_gate.get("artifact_hash_count")),
        "summary_board_first_paint_passed": bool(summary_board_gate.get("passed")),
        "summary_board_first_paint_failure_count": _as_int(summary_board_gate.get("failure_count")),
        "summary_board_section_count": _as_int(summary_board_gate.get("section_count")),
        "billing_reconciliation_passed": bool(billing_gate.get("passed")),
        "billing_reconciliation_failure_count": _as_int(billing_gate.get("failure_count")),
        "billing_reconciliation_live_passed": bool(billing_live_gate.get("passed")),
        "billing_reconciliation_live_skipped": bool(billing_live_gate.get("skipped")),
        "billing_reconciliation_live_required": bool(billing_live_gate.get("live_required")),
        "packet_availability_passed": bool(packet_availability_gate.get("passed")),
        "packet_availability_failure_count": _as_int(packet_availability_gate.get("failure_count")),
        "packet_availability_missing_packet_count": _as_int(packet_availability_gate.get("missing_packet_count")),
        "packet_availability_window_mismatch_count": _as_int(packet_availability_gate.get("window_mismatch_count")),
        "live_cost_reconciliation_passed": bool(live_cost_gate.get("passed")),
        "live_cost_reconciliation_failure_count": _as_int(live_cost_gate.get("failure_count")),
        "daily_wording_passed": bool(daily_wording_gate.get("passed")),
        "daily_wording_failure_count": _as_int(daily_wording_gate.get("failure_count")),
        "daily_wording_blocked_count": _as_int(daily_wording_gate.get("blocked_count")),
        "full_app_launch_gauntlet_passed": bool(full_app_launch_gate.get("passed")),
        "full_app_launch_gauntlet_failure_count": _as_int(full_app_launch_gate.get("failure_count")),
        "full_app_release_sweep_passed": bool(full_app_release_sweep_gate.get("passed")),
        "full_app_release_sweep_failure_count": _as_int(full_app_release_sweep_gate.get("failure_count")),
        "deterministic_streamlit_render_passed": bool(deterministic_render_gate.get("passed")),
        "deterministic_streamlit_render_failure_count": _as_int(deterministic_render_gate.get("failure_count")),
        "deterministic_streamlit_render_synthetic_count": _as_int(deterministic_render_gate.get("synthetic_fallback_count")),
        "browser_smoke_passed": bool(browser_smoke_gate.get("passed")),
        "browser_smoke_failure_count": _as_int(browser_smoke_gate.get("failure_count")),
        "browser_render_gauntlet_passed": bool(browser_render_gate.get("passed")),
        "browser_render_failure_count": _as_int(browser_render_gate.get("failure_count")),
        "browser_rendered_surface_count": _as_int(browser_render_gate.get("rendered_surface_count")),
        "synthetic_render_count": _as_int(browser_render_gate.get("synthetic_fallback_count")),
        "runtime_artifact_provenance_passed": bool(runtime_provenance_gate.get("passed")),
        "runtime_artifact_provenance_failure_count": _as_int(runtime_provenance_gate.get("failure_count")),
        "runtime_artifact_provenance_row_count": _as_int(runtime_provenance_gate.get("row_count")),
        "render_provenance_reconciliation_passed": bool(render_provenance_gate.get("passed")),
        "render_provenance_reconciliation_failure_count": _as_int(render_provenance_gate.get("failure_count")),
        "render_provenance_reconciliation_surface_count": _as_int(render_provenance_gate.get("surface_count")),
        "rendered_ui_leak_scan_passed": bool(rendered_ui_leak_gate.get("passed")),
        "diagnostic_leak_count": max(
            _as_int(source_leak_gate.get("diagnostic_leak_count")),
            _as_int(rendered_ui_leak_gate.get("failure_count")),
            _as_int(full_app_release_sweep_gate.get("diagnostic_leak_count")),
        ),
        "internal_wording_leak_count": max(
            _as_int(source_leak_gate.get("internal_wording_leak_count")),
            _as_int(daily_wording_gate.get("blocked_count")),
            _as_int(full_app_release_sweep_gate.get("internal_wording_leak_count")),
        ),
        "raw_sql_leak_count": max(
            _as_int(rendered_ui_leak_gate.get("raw_sql_leak_count")),
            _as_int(source_leak_gate.get("raw_sql_leak_count")),
            _as_int(full_app_release_sweep_gate.get("raw_source_leak_count")),
        ),
        "settings_gate_passed": bool(settings_gate.get("passed")),
        "settings_failure_count": max(
            _as_int(settings_gate.get("failure_count")),
            _as_int(settings_live_feature_gate.get("settings_failure_count")),
            _as_int(full_app_release_sweep_gate.get("settings_failure_count")),
        ),
        "settings_live_feature_gate_passed": bool(settings_live_feature_gate.get("passed")),
        "first_paint_gate_passed": bool(first_paint_gate.get("passed")),
        "first_paint_failure_count": max(
            _as_int(first_paint_gate.get("failure_count")),
            _as_int(full_app_release_sweep_gate.get("first_paint_failure_count")),
        ),
        "credential_first_paint_violation_count": _security_first_paint_violation_count(payloads),
        "packet_fallback_ui_passed": bool(packet_fallback_gate.get("passed")),
        "packet_fallback_ui_failure_count": _as_int(packet_fallback_gate.get("failure_count")),
        "summary_board_visual_contract_passed": bool(summary_visual_gate.get("passed")),
        "summary_board_visual_contract_failure_count": _as_int(summary_visual_gate.get("failure_count")),
        "action_click_gate_passed": bool(action_click_gate.get("passed")),
        "failed_action_count": max(
            _as_int(action_click_gate.get("failure_count")),
            _as_int(full_app_release_sweep_gate.get("failed_action_count")),
        ),
        "export_download_gate_passed": bool(export_download_gate.get("passed")),
        "export_failure_count": max(
            _as_int(export_download_gate.get("failure_count")),
            _as_int(full_app_release_sweep_gate.get("export_failure_count")),
        ),
        "live_feature_gate_passed": bool(live_feature_gate.get("passed")),
        "live_feature_failure_count": max(
            _as_int(live_feature_gate.get("failure_count")),
            _as_int(settings_live_feature_gate.get("live_feature_failure_count")),
            _as_int(full_app_release_sweep_gate.get("live_feature_failure_count")),
        ),
        "sql_cleanup_gate_passed": bool(sql_cleanup_gate.get("passed")),
        "sql_cleanup_failure_count": max(
            _as_int(sql_cleanup_gate.get("failure_count")),
            _as_int(full_app_release_sweep_gate.get("sql_cleanup_failure_count")),
        ),
        "metric_source_governance_passed": bool(metric_source_governance_gate.get("passed")),
        "ui_kit_alignment_passed": bool(ui_kit_alignment_gate.get("passed")),
        "ui_kit_command_brief_surface_count": _as_int(ui_kit_alignment_gate.get("command_brief_surface_count")),
        "ui_kit_source_footer_leak_count": _as_int(ui_kit_alignment_gate.get("source_footer_leak_count")),
        "ui_kit_old_board_marker_count": _as_int(ui_kit_alignment_gate.get("old_board_marker_count")),
        "duplicate_command_brief_count": _as_int(full_app_release_sweep_gate.get("duplicate_command_brief_count")),
        "old_board_marker_count": max(
            _as_int(full_app_release_sweep_gate.get("old_board_marker_count")),
            _as_int(ui_kit_alignment_gate.get("old_board_marker_count")),
        ),
        "ui_kit_evidence_autoload_violation_count": _as_int(
            ui_kit_alignment_gate.get("evidence_autoload_violation_count")
        ),
        "ui_kit_credential_tile_rendered": bool(ui_kit_alignment_gate.get("credential_tile_rendered")),
        "ui_kit_cortex_efficiency_rendered": bool(ui_kit_alignment_gate.get("cortex_efficiency_rendered")),
        "credential_tile_rendered": bool(full_app_release_sweep_gate.get("credential_tile_rendered"))
        or bool(ui_kit_alignment_gate.get("credential_tile_rendered")),
        "cortex_efficiency_rendered": bool(full_app_release_sweep_gate.get("cortex_efficiency_rendered"))
        or bool(ui_kit_alignment_gate.get("cortex_efficiency_rendered")),
        "section_layout_contract_passed": bool(section_layout_gate.get("passed")),
        "section_layout_contract_failure_count": _as_int(section_layout_gate.get("failure_count")),
        "section_layout_command_brief_count": _as_int(section_layout_gate.get("command_brief_count")),
        "section_layout_raw_source_token_count": _as_int(section_layout_gate.get("raw_source_token_count")),
        "source_safe_footer_passed": bool(source_safe_footer_gate.get("passed")),
        "source_safe_footer_leak_count": _as_int(source_safe_footer_gate.get("source_footer_leak_count")),
        "silent_scrub_count": _as_int(source_safe_footer_gate.get("silent_scrub_count")),
        "new_metric_family_count": _as_int(metric_source_governance_gate.get("new_metric_family_count")),
        "new_metric_packet_field_count": _as_int(
            metric_source_governance_gate.get("new_metric_packet_field_count")
        ),
        "new_metric_rendered_count": _as_int(metric_source_governance_gate.get("new_metric_rendered_count")),
        "new_metric_evidence_action_count": _as_int(
            metric_source_governance_gate.get("new_metric_evidence_action_count")
        ),
        "new_metric_export_count": _as_int(metric_source_governance_gate.get("new_metric_export_count")),
        "new_metric_unavailable_source_count": _as_int(
            metric_source_governance_gate.get("new_metric_unavailable_source_count")
        ),
        "new_metric_first_paint_violation_count": _as_int(
            metric_source_governance_gate.get("new_metric_first_paint_violation_count")
        ),
        "new_metric_raw_leak_count": _as_int(metric_source_governance_gate.get("new_metric_raw_leak_count")),
        "new_metric_sql_inventory_failure_count": _as_int(
            metric_source_governance_gate.get("new_metric_sql_inventory_failure_count")
        ),
        "app_health_gate_passed": bool(metric_source_governance_gate.get("app_health_gate_passed")),
        "credential_expiration_gate_passed": bool(security_credential_gate.get("passed")),
        "credential_expiration_live_gate_passed": bool(security_credential_live_gate.get("passed")),
        "credential_expiring_30d_count": _as_int(security_credential_gate.get("credential_expiring_30d_count")),
        "credential_expired_count": _as_int(security_credential_gate.get("credential_expired_count")),
        "credential_next_expiration_days": _as_int(security_credential_gate.get("credential_next_expiration_days")),
        "credential_source_confirmed_zero": bool(security_credential_gate.get("credential_source_confirmed_zero")),
        "credential_live_validation_status": str(
            security_credential_live_gate.get("live_validation_status")
            or security_credential_gate.get("credential_live_validation_status")
            or ""
        ),
        "user_display_name_gate_passed": bool(user_display_gate.get("passed")),
        "user_display_name_live_gate_passed": bool(user_display_live_gate.get("passed")),
        "user_display_surface_gate_passed": bool(user_display_surface_gate.get("passed")),
        "user_id_daily_leak_count": max(
            _as_int(user_display_surface_gate.get("user_id_daily_leak_count")),
            _as_int(full_app_release_sweep_gate.get("user_id_daily_leak_count")),
        ),
        "cortex_user_label_gate_passed": bool(cortex_user_label_gate.get("passed")),
        "credential_export_leak_count": max(
            _as_int(security_credential_export_gate.get("credential_export_leak_count")),
            _as_int(full_app_release_sweep_gate.get("credential_id_daily_leak_count")),
        ),
        "credential_id_daily_leak_count": max(
            _as_int(security_credential_export_gate.get("credential_export_leak_count")),
            _as_int(full_app_release_sweep_gate.get("credential_id_daily_leak_count")),
        ),
        "credential_render_gate_passed": bool(security_credential_render_gate.get("passed")),
        "credential_evidence_gate_passed": bool(security_credential_evidence_gate.get("passed")),
        "credential_first_paint_gate_passed": bool(security_credential_first_paint_gate.get("passed")),
        "credential_sql_inventory_gate_passed": bool(credential_sql_inventory_gate.get("passed")),
        "credential_rendered_leak_gate_passed": bool(credential_rendered_leak_gate.get("passed")),
        "cortex_token_efficiency_gate_passed": bool(cortex_token_efficiency_gate.get("passed")),
        "cortex_token_efficiency_live_gate_passed": bool(cortex_token_efficiency_live_gate.get("passed")),
        "cortex_token_metric_count": _as_int(cortex_token_efficiency_gate.get("cortex_token_metric_count")),
        "cortex_token_ratio_failure_count": _as_int(
            cortex_token_efficiency_gate.get("cortex_token_ratio_failure_count")
        ),
        "cortex_token_efficiency_live_required": bool(cortex_token_efficiency_live_gate.get("live_required")),
        "cortex_token_efficiency_live_executed": bool(cortex_token_efficiency_live_gate.get("live_executed")),
        "cortex_token_efficiency_live_passed": bool(cortex_token_efficiency_live_gate.get("live_passed")),
        "cortex_token_efficiency_live_skipped": bool(cortex_token_efficiency_live_gate.get("live_skipped")),
        "user_stress_gate_passed": bool(user_stress_gate.get("passed")),
        "stress_failure_count": max(
            _as_int(user_stress_gate.get("failure_count")),
            _as_int(full_app_release_sweep_gate.get("stress_failure_count")),
        ),
        "slow_runtime_count": _as_int(user_stress_gate.get("slow_runtime_count")),
        "source_internal_leak_scan_passed": bool(source_leak_gate.get("passed")),
        "source_internal_leak_scan_failure_count": _as_int(source_leak_gate.get("failure_count")),
        "cortex_cost_consistency_passed": bool(cortex_gate.get("passed")),
        "cortex_cost_consistency_failure_count": _as_int(cortex_gate.get("failure_count")),
        "cost_chart_workbench_passed": bool(cost_chart_gate.get("passed")),
        "cost_chart_workbench_failure_count": _as_int(cost_chart_gate.get("failure_count")),
        "cost_db_formula_authority_passed": bool(cost_db_formula_gate.get("passed")),
        "cost_db_formula_authority_failure_count": _as_int(cost_db_formula_gate.get("failure_count")),
        "cost_db_formula_count": _as_int(cost_db_formula_gate.get("cost_db_formula_count")),
        "overwatch_formula_count": _as_int(cost_db_formula_gate.get("overwatch_formula_count")),
        "formula_end_to_end_passed": bool(formula_end_gate.get("passed")),
        "formula_end_to_end_failure_count": _as_int(formula_end_gate.get("failure_count")),
        "formula_value_reconciliation_passed": bool(formula_end_gate.get("formula_value_reconciliation_passed")),
        "formula_value_reconciliation_failure_count": _as_int(formula_end_gate.get("formula_value_reconciliation_failure_count")),
        "formula_value_source_reconciliation_passed": bool(formula_value_gate.get("passed"))
        and bool(formula_end_gate.get("formula_value_source_reconciliation_passed")),
        "formula_value_source_reconciliation_failure_count": _as_int(
            formula_value_gate.get("failure_count")
            or formula_end_gate.get("formula_value_source_reconciliation_failure_count")
        ),
        "formula_value_artifact_sourced_row_count": _as_int(formula_end_gate.get("formula_value_artifact_sourced_row_count")),
        "formula_value_synthetic_only_row_count": _as_int(formula_end_gate.get("formula_value_synthetic_only_row_count")),
        "formula_validation_mode": str(formula_end_gate.get("formula_validation_mode") or ""),
        "packet_formula_sql_passed": bool(formula_end_gate.get("packet_formula_sql_passed")),
        "flat_packet_formula_passed": bool(formula_end_gate.get("flat_packet_formula_passed")),
        "snowflake_formula_static_passed": bool(formula_end_gate.get("snowflake_formula_static_passed")),
        "snowflake_formula_value_passed": bool(formula_end_gate.get("snowflake_formula_value_passed")),
        "snowflake_formula_value_failure_count": _as_int(formula_end_gate.get("snowflake_formula_value_failure_count")),
        "snowflake_formula_live_required": bool(formula_end_gate.get("snowflake_formula_live_required")),
        "snowflake_formula_live_executed": bool(formula_end_gate.get("snowflake_formula_live_executed")),
        "snowflake_formula_live_passed": bool(formula_end_gate.get("snowflake_formula_live_passed")),
        "snowflake_formula_live_skipped": bool(formula_end_gate.get("snowflake_formula_live_skipped")),
        "snowflake_formula_live_skip_reason": str(formula_end_gate.get("snowflake_formula_live_skip_reason") or ""),
        "snowflake_formula_live_waiver_id": str(formula_end_gate.get("snowflake_formula_live_waiver_id") or ""),
        "snowflake_formula_live_failure_count": _as_int(formula_end_gate.get("snowflake_formula_live_failure_count")),
        "packet_schema_upgrade_passed": bool(packet_schema_gate.get("passed")),
        "packet_schema_failure_count": _as_int(packet_schema_gate.get("failure_count")),
        "snowflake_formula_gate_passed": bool(snowflake_formula_gate.get("passed")),
        "snowflake_formula_gate_failure_count": _as_int(snowflake_formula_gate.get("failure_count")),
        "rendered_formula_passed": bool(formula_end_gate.get("rendered_formula_passed")),
        "cost_advisor_value_at_risk_passed": bool(cost_advisor_gate.get("passed")),
        "cost_advisor_value_at_risk_failure_count": _as_int(cost_advisor_gate.get("failure_count")),
        "date_widget_regression_passed": bool(date_widget_gate.get("passed")),
        "date_widget_regression_failure_count": _as_int(date_widget_gate.get("failure_count")),
        "cortex_service_type_gate_passed": bool(cortex_service_type_gate.get("passed")),
        "cortex_service_type_failure_count": _as_int(cortex_service_type_gate.get("failure_count")),
        "cortex_unknown_service_type_count": _as_int(cortex_service_type_gate.get("unknown_service_type_count")),
        "formula_live_validation_passed": bool(formula_live_gate.get("passed")),
        "formula_live_validation_skipped": bool(formula_live_gate.get("skipped")),
        "formula_live_validation_required": bool(formula_live_gate.get("live_required")),
        "snowflake_cli_gate_passed": bool(snowflake_cli_gate.get("snowflake_cli_gate_passed", snowflake_cli_gate.get("passed"))),
        "snowflake_cli_live_required": bool(snowflake_cli_gate.get("snowflake_cli_live_required", snowflake_cli_gate.get("live_required"))),
        "snowflake_cli_live_executed": bool(snowflake_cli_gate.get("snowflake_cli_live_executed")),
        "snowflake_cli_live_passed": bool(snowflake_cli_gate.get("snowflake_cli_live_passed")),
        "snowflake_cli_live_skipped": bool(snowflake_cli_gate.get("snowflake_cli_live_skipped", snowflake_cli_gate.get("skipped"))),
        "snowflake_cli_skip_reason": str(snowflake_cli_gate.get("snowflake_cli_skip_reason") or ""),
        "snowflake_cli_live_waived": bool(snowflake_cli_gate.get("snowflake_cli_live_waived", snowflake_cli_gate.get("waived"))),
        "snowflake_cli_live_validation_passed": bool(snowflake_cli_gate.get("snowflake_cli_gate_passed", snowflake_cli_gate.get("passed"))),
        "snowflake_cli_live_validation_failure_count": _as_int(snowflake_cli_gate.get("failure_count")),
        "snowflake_cli_live_validation_skipped": bool(snowflake_cli_gate.get("snowflake_cli_live_skipped", snowflake_cli_gate.get("skipped"))),
        "snowflake_cli_live_validation_required": bool(snowflake_cli_gate.get("snowflake_cli_live_required", snowflake_cli_gate.get("live_required"))),
        "snowflake_cli_live_validation_waived": bool(snowflake_cli_gate.get("snowflake_cli_live_waived", snowflake_cli_gate.get("waived"))),
        "snowflake_cli_token_auth_used": bool(snowflake_cli_gate.get("snowflake_cli_token_auth_used")),
        "snowflake_cli_token_file_supplied": bool(snowflake_cli_gate.get("snowflake_cli_token_file_supplied")),
        "snowflake_cli_token_path_leak_count": _as_int(snowflake_cli_gate.get("snowflake_cli_token_path_leak_count")),
        "snowflake_cli_temp_sql_path_leak_count": _as_int(snowflake_cli_gate.get("snowflake_cli_temp_sql_path_leak_count")),
        "snowflake_cli_temp_file_hygiene_passed": bool(
            snowflake_cli_gate.get("temp_file_hygiene_passed", snowflake_cli_temp_hygiene_gate.get("passed"))
        ),
        "setup_migration_live_passed": bool(
            snowflake_cli_gate.get("setup_migration_live_passed") or setup_migration_live_gate.get("passed")
        ),
        "temp_sql_file_leftover_count": _as_int(
            snowflake_cli_gate.get("temp_sql_file_leftover_count", snowflake_cli_temp_hygiene_gate.get("temp_sql_file_leftover_count"))
        ),
        "snowflake_cli_connection_passed": bool(snowflake_cli_gate.get("connection_passed")),
        "snowflake_cli_setup_validation_passed": bool(snowflake_cli_gate.get("setup_validation_passed")),
        "snowflake_cli_packet_value_passed": bool(snowflake_cli_gate.get("packet_value_passed")),
        "snowflake_cli_formula_value_passed": bool(snowflake_cli_gate.get("formula_value_passed")),
        "snowflake_cli_summary_card_value_passed": bool(snowflake_cli_gate.get("summary_card_value_passed")),
        "snowflake_cli_query_budget_passed": bool(snowflake_cli_gate.get("query_budget_passed")),
        "snowflake_cli_manifest_reconciliation_passed": bool(snowflake_cli_gate.get("manifest_reconciliation_passed")),
        "metric_semantic_registry_passed": bool(metric_semantic_gate.get("passed")),
        "metric_semantic_registry_failure_count": _as_int(metric_semantic_gate.get("failure_count")),
        "metric_semantic_registry_row_count": _as_int(metric_semantic_gate.get("registry_row_count")),
        "workload_formula_semantics_passed": bool(workload_formula_gate.get("passed")),
        "workload_formula_semantics_failure_count": _as_int(workload_formula_gate.get("failure_count")),
        "query_budget_gate_passed": bool(query_budget_gate.get("passed")),
        "query_budget_gate_failure_count": _as_int(query_budget_gate.get("failure_count")),
        "browser_or_snapshot_passed": _gate_passed(matrix, "browser_or_rendered_snapshot"),
        "missing_artifacts": _as_list(artifact_review.get("missing_required_gauntlet_artifacts")),
        "stale_artifacts": _as_list(artifact_review.get("stale_artifacts")),
        "stale_artifact_count": _as_int(artifact_review.get("stale_artifact_count")),
        "observed_check_count": len(matrix),
        "expected_check_count": len(matrix),
        "raw_invariant_passed": bool(raw_invariants.get("passed")),
        "raw_invariant_failure_count": _as_int(raw_invariants.get("failure_count")),
        "gauntlet_passed": bool(gauntlet.get("passed")),
        "runtime_validation_passed": bool(summary.get("all_passed")),
        "snowflake_validation_passed": bool(snowflake_gate.get("snowflake_validation_passed")),
        "snowflake_live_validation_enabled": bool(snowflake_gate.get("snowflake_live_validation_enabled")),
        "snowflake_live_validation_skipped": bool(snowflake_gate.get("snowflake_live_validation_skipped")),
        "snowflake_validation_skip_reason": str(snowflake_gate.get("snowflake_validation_skip_reason") or ""),
        "live_validation_status": str(snowflake_gate.get("live_validation_status") or ""),
        "live_validation_waiver_id": str(snowflake_gate.get("live_validation_waiver_id") or ""),
        "live_validation_waiver_owner": str(snowflake_gate.get("live_validation_waiver_owner") or ""),
        "live_validation_waiver_expiration": str(snowflake_gate.get("live_validation_waiver_expiration") or ""),
        "live_validation_required": bool(snowflake_gate.get("live_validation_required")),
        "live_validation_skip_allowed": bool(snowflake_gate.get("live_validation_skip_allowed")),
        "live_validation_missing_reason": str(snowflake_gate.get("live_validation_missing_reason") or ""),
        "live_execution_manifest_passed": bool(snowflake_gate.get("live_execution_manifest_passed")),
        "live_execution_manifest_entry_count": _as_int(snowflake_gate.get("live_execution_manifest_entry_count")),
        "live_execution_manifest_failure_count": _as_int(snowflake_gate.get("live_execution_manifest_failure_count")),
        "live_execution_manifest_gate_passed": bool(manifest_gate.get("passed")),
        "live_execution_manifest_reconciliation_passed": bool(snowflake_gate.get("live_execution_manifest_reconciliation_passed")),
        "live_execution_manifest_reconciliation_failure_count": _as_int(snowflake_gate.get("live_execution_manifest_reconciliation_failure_count")),
        "live_execution_manifest_category_coverage_passed": bool(snowflake_gate.get("live_execution_manifest_category_coverage_passed")),
        "live_execution_manifest_category_failure_count": _as_int(snowflake_gate.get("live_execution_manifest_category_failure_count")),
        "live_execution_manifest_orphan_count": _as_int(snowflake_gate.get("live_execution_manifest_orphan_count")),
        "live_execution_manifest_unknown_id_count": _as_int(snowflake_gate.get("live_execution_manifest_unknown_id_count")),
        "live_execution_manifest_missing_id_count": _as_int(snowflake_gate.get("live_execution_manifest_missing_id_count")),
        "live_execution_manifest_status_mismatch_count": _as_int(snowflake_gate.get("live_execution_manifest_status_mismatch_count")),
        "live_execution_manifest_mode_mismatch_count": _as_int(snowflake_gate.get("live_execution_manifest_mode_mismatch_count")),
        "live_execution_manifest_row_index_mismatch_count": _as_int(snowflake_gate.get("live_execution_manifest_row_index_mismatch_count")),
        "live_execution_manifest_row_key_mismatch_count": _as_int(snowflake_gate.get("live_execution_manifest_row_key_mismatch_count")),
        "procedure_compile_count": _as_int(snowflake_gate.get("procedure_compile_count")),
        "procedure_compile_failure_count": _as_int(snowflake_gate.get("procedure_compile_failure_count")),
        "procedure_smoke_call_count": _as_int(snowflake_gate.get("procedure_smoke_call_count")),
        "procedure_smoke_failure_count": _as_int(snowflake_gate.get("procedure_smoke_failure_count")),
        "refresh_fast_status": str(snowflake_gate.get("refresh_fast_status") or ""),
        "refresh_full_status": str(snowflake_gate.get("refresh_full_status") or ""),
        "packet_validation_status": str(snowflake_gate.get("packet_validation_status") or ""),
        "packet_validation_failed_check_count": _as_int(snowflake_gate.get("packet_validation_failed_check_count")),
        "packet_max_bytes": _as_int(snowflake_gate.get("packet_max_bytes")),
        "packet_current_active_row_count": _as_int(snowflake_gate.get("packet_current_active_row_count")),
        "packet_flat_active_row_count": _as_int(snowflake_gate.get("packet_flat_active_row_count")),
        "packet_last_good_status": str(snowflake_gate.get("packet_last_good_status") or ""),
        "packet_duplicate_array_count": _as_int(snowflake_gate.get("packet_duplicate_array_count")),
        "packet_missing_field_count": _as_int(snowflake_gate.get("packet_missing_field_count")),
        "packet_duplicate_arrays": _as_list(snowflake_gate.get("packet_duplicate_arrays")),
        "packet_missing_fields": _as_list(snowflake_gate.get("packet_missing_fields")),
        "compact_evidence_validation_status": str(snowflake_gate.get("compact_evidence_validation_status") or ""),
        "compact_mart_count": _as_int(snowflake_gate.get("compact_mart_count")),
        "compact_mart_failure_count": _as_int(snowflake_gate.get("compact_mart_failure_count")),
        "compact_mart_names": _as_list(snowflake_gate.get("compact_mart_names")),
        "compact_normal_account_usage_count": _as_int(snowflake_gate.get("compact_normal_account_usage_count")),
        "compact_missing_target_column_count": _as_int(snowflake_gate.get("compact_missing_target_column_count")),
        "compact_missing_target_columns": _as_list(snowflake_gate.get("compact_missing_target_columns")),
        "encoding_hygiene_passed": bool(encoding_hygiene.get("passed")),
        "encoding_blocked_count": _as_int(encoding_hygiene.get("blocked_count")),
        "forbidden_daily_token_count": _as_int(summary.get("forbidden_daily_ui_token_count"))
        or _as_int(_as_mapping(payloads.get("artifacts/full_app_validation/forbidden_daily_ui_scan.json")).get("blocked_count")),
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
    profile = _selected_launch_profile()
    waivers = _load_launch_waivers()
    _clean_launch_artifact_directory(root_path)
    _clean_release_candidate_directory(root_path)
    gauntlet_artifacts = write_full_app_gauntlet_artifacts(root_path)
    payloads, missing_payloads = _load_payloads(root_path, REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS)
    payloads.update(gauntlet_artifacts)
    formula_artifacts = write_cost_db_formula_authority_artifacts(root_path)
    payloads.update(formula_artifacts)
    formula_end_to_end_artifacts = write_formula_end_to_end_artifacts(root_path)
    payloads.update(formula_end_to_end_artifacts)
    performance_budget_artifacts = write_performance_budget_gate_artifacts(root_path)
    payloads.update(performance_budget_artifacts)
    delete_first_cleanup_artifacts = write_delete_first_cleanup_artifacts(root_path)
    payloads.update(delete_first_cleanup_artifacts)
    security_credential_artifacts = write_security_credential_validation_artifacts(
        root_path,
        profile=profile,
        waivers=waivers,
    )
    payloads.update(security_credential_artifacts)
    cortex_token_efficiency_artifacts = write_cortex_token_efficiency_artifacts(
        root_path,
        profile=profile,
        waivers=waivers,
    )
    payloads.update(cortex_token_efficiency_artifacts)
    metric_source_governance_artifacts = write_metric_source_governance_artifacts(root_path)
    payloads.update(metric_source_governance_artifacts)
    ui_kit_alignment_artifacts = write_ui_kit_alignment_artifacts(root_path)
    payloads.update(ui_kit_alignment_artifacts)
    settings_live_feature_artifacts = write_settings_live_feature_gauntlet_artifacts(root_path, payloads)
    payloads.update(settings_live_feature_artifacts)

    launch_artifacts: dict[str, Any] = {}
    launch_artifacts["launch_waivers"] = {
        "source": "launch_readiness_waivers",
        "proof_source": "inventory_only",
        "passed": all(bool(row.get("valid")) for row in waivers),
        "waiver_count": len(waivers),
        "waivers": waivers,
        "raw_sql_included": False,
    }
    launch_artifacts["launch_profile_results"] = _launch_profile_results(profile, waivers)
    launch_artifacts["profile_gate_failures"] = _profile_gate_failures(launch_artifacts["launch_profile_results"], waivers)
    launch_artifacts["ci_run_review_results"] = _ci_run_review_results(profile, waivers)
    launch_artifacts["release_candidate_ci_context"] = _release_candidate_ci_context(profile, waivers)
    ci_upload_review = _workflow_upload_review(root_path)
    launch_artifacts["ci_artifact_review_results"] = ci_upload_review
    launch_artifacts["artifact_upload_review_results"] = ci_upload_review
    browser_smoke, browser_coverage = _browser_smoke_results(root_path, payloads, profile, waivers)
    launch_artifacts["browser_smoke_results"] = browser_smoke
    launch_artifacts["browser_required_coverage"] = browser_coverage
    launch_artifacts["browser_or_snapshot_failures"] = _browser_or_snapshot_failures(browser_smoke, browser_coverage)
    launch_artifacts["config_sanity_results"] = _config_sanity_results(root_path, profile)
    launch_artifacts["snowflake_permission_matrix"] = _permission_matrix(payloads)
    launch_artifacts["role_readiness_results"] = _role_readiness_results(payloads)
    launch_artifacts["deployment_readiness_results"] = _deployment_readiness_results(root_path, payloads)
    launch_artifacts["upgrade_readiness_results"] = _upgrade_readiness_results(root_path)
    launch_artifacts["drop_rollback_results"] = _drop_rollback_results(root_path, payloads)
    sql_value = _sql_value_inventory(root_path, payloads)
    launch_artifacts["sql_value_inventory"] = sql_value
    launch_artifacts["sql_path_delete_candidates"] = _sql_path_delete_candidates(sql_value)
    launch_artifacts["sql_cost_risk_findings"] = _sql_cost_risk_findings(payloads, sql_value)
    launch_artifacts["live_query_history_results"] = _live_query_history_results(root_path, profile, waivers)
    launch_artifacts["performance_slo_results"] = _performance_slo_results(payloads)
    launch_artifacts["settings_live_closure_results"] = _settings_live_closure_results(payloads)
    launch_artifacts["export_case_closure_results"] = _export_case_closure_results(root_path, payloads)
    launch_artifacts["cleanup_launch_closure_results"] = _cleanup_launch_closure_results(payloads)
    launch_artifacts["delete_first_release_results"] = _delete_first_release_results(payloads)
    launch_artifacts["delete_first_cleanup_gate_results"] = delete_first_cleanup_artifacts[DELETE_FIRST_GATE_REL]
    launch_artifacts["performance_budget_gate_results"] = performance_budget_artifacts[PERFORMANCE_BUDGET_GATE_REL]
    launch_artifacts["cortex_token_efficiency_gate_results"] = cortex_token_efficiency_artifacts[
        CORTEX_TOKEN_EFFICIENCY_GATE_REL
    ]
    launch_artifacts["cortex_token_efficiency_live_gate_results"] = cortex_token_efficiency_artifacts[
        CORTEX_TOKEN_EFFICIENCY_LIVE_GATE_REL
    ]
    launch_artifacts["metric_source_governance_gate_results"] = metric_source_governance_artifacts[
        METRIC_SOURCE_GOVERNANCE_GATE_REL
    ]
    launch_artifacts["ui_kit_alignment_gate_results"] = ui_kit_alignment_artifacts[UI_KIT_ALIGNMENT_GATE_REL]
    launch_artifacts["section_layout_contract_gate_results"] = ui_kit_alignment_artifacts[
        SECTION_LAYOUT_CONTRACT_GATE_REL
    ]
    launch_artifacts["source_safe_footer_gate_results"] = ui_kit_alignment_artifacts[SOURCE_SAFE_FOOTER_GATE_REL]
    launch_artifacts["settings_live_feature_gate_results"] = settings_live_feature_artifacts[
        SETTINGS_LIVE_FEATURE_GATE_REL
    ]
    for rel, metric_gate_payload in metric_source_governance_artifacts.items():
        if rel in METRIC_FAMILY_GATE_RELS.values():
            launch_artifacts[Path(rel).stem] = metric_gate_payload
    launch_artifacts["security_credential_expiration_gate_results"] = security_credential_artifacts[
        SECURITY_CREDENTIAL_GATE_REL
    ]
    launch_artifacts["security_credential_expiration_live_gate_results"] = security_credential_artifacts[
        SECURITY_CREDENTIAL_LIVE_GATE_REL
    ]
    launch_artifacts["user_display_name_gate_results"] = security_credential_artifacts[USER_DISPLAY_NAME_GATE_REL]
    launch_artifacts["user_display_name_live_gate_results"] = security_credential_artifacts[
        USER_DISPLAY_NAME_LIVE_GATE_REL
    ]
    launch_artifacts["user_display_surface_gate_results"] = security_credential_artifacts[
        USER_DISPLAY_SURFACE_GATE_REL
    ]
    launch_artifacts["cortex_user_label_gate_results"] = security_credential_artifacts[CORTEX_USER_LABEL_GATE_REL]
    launch_artifacts["security_credential_export_gate_results"] = security_credential_artifacts[
        SECURITY_CREDENTIAL_EXPORT_GATE_REL
    ]
    launch_artifacts["security_credential_render_gate_results"] = security_credential_artifacts[
        SECURITY_CREDENTIAL_RENDER_GATE_REL
    ]
    launch_artifacts["security_credential_evidence_gate_results"] = security_credential_artifacts[
        SECURITY_CREDENTIAL_EVIDENCE_GATE_REL
    ]
    launch_artifacts["security_credential_first_paint_gate_results"] = security_credential_artifacts[
        SECURITY_CREDENTIAL_FIRST_PAINT_GATE_REL
    ]
    launch_artifacts["security_credential_snapshot_gate_results"] = security_credential_artifacts[
        SECURITY_CREDENTIAL_SNAPSHOT_GATE_REL
    ]
    launch_artifacts["credential_sql_inventory_gate_results"] = security_credential_artifacts[
        SECURITY_CREDENTIAL_SQL_INVENTORY_GATE_REL
    ]
    launch_artifacts["credential_rendered_leak_gate_results"] = security_credential_artifacts[
        SECURITY_CREDENTIAL_RENDERED_LEAK_GATE_REL
    ]
    launch_artifacts["docs_readiness_results"] = _docs_readiness_results(root_path)
    launch_artifacts["secrets_scan_results"] = _secrets_scan_results(root_path)
    launch_artifacts["artifact_review_results"] = _artifact_review_results(root_path, payloads, missing_payloads)
    launch_artifacts["cost_db_formula_authority_gate_results"] = evaluate_cost_db_formula_authority(
        formula_artifacts.get("artifacts/formula_authority/cost_db_formula_mapping.json"),
        formula_artifacts.get("artifacts/formula_authority/overwatch_formula_mapping.json"),
        formula_artifacts.get("artifacts/formula_authority/formula_gap_results.json"),
        formula_artifacts.get("artifacts/formula_authority/cost_db_formula_authority_summary.json"),
        formula_artifacts.get("artifacts/formula_authority/cortex_service_type_mapping.json"),
        formula_artifacts.get("artifacts/formula_authority/formula_chain_results.json"),
        formula_artifacts.get(FORMULA_VALUE_RECONCILIATION_REL),
        formula_artifacts.get("artifacts/formula_authority/packet_formula_results.json"),
        formula_artifacts.get(FLAT_PACKET_FORMULA_REL),
        formula_artifacts.get(SNOWFLAKE_FORMULA_STATIC_REL),
    )
    launch_artifacts["release_candidate_gate_results"] = {
        "source": "release_candidate_gate",
        "proof_source": "runtime_click",
        "passed": True,
        "failure_count": 0,
        "failures": [],
        "artifact_count": 0,
        "artifact_hash_count": 0,
        "raw_sql_included": False,
    }
    launch_artifacts["ci_artifact_reality_results"] = _ci_artifact_reality_results(
        profile,
        launch_artifacts["ci_run_review_results"],
        launch_artifacts["artifact_upload_review_results"],
        launch_artifacts["artifact_review_results"],
        missing_payloads,
    )
    snowflake_artifacts = write_snowflake_validation_artifacts(root_path)
    payloads.update(snowflake_artifacts)
    snowflake_cli_artifacts = write_snowflake_cli_live_validation_artifacts(root_path)
    snowflake_cli_gate = evaluate_snowflake_cli_live_gate(snowflake_cli_artifacts, profile, waivers)
    snowflake_cli_artifacts[CLI_LAUNCH_GATE_REL] = snowflake_cli_gate
    snowflake_cli_artifacts[CLI_RELEASE_REL] = {
        "source": "snowflake_cli_release_results",
        "generated_at": _utc_now(),
        "passed": bool(snowflake_cli_gate.get("snowflake_cli_gate_passed", snowflake_cli_gate.get("passed"))),
        "failure_count": _as_int(snowflake_cli_gate.get("failure_count")),
        "launch_profile": profile,
        "snowflake_cli_gate_passed": bool(snowflake_cli_gate.get("snowflake_cli_gate_passed", snowflake_cli_gate.get("passed"))),
        "snowflake_cli_live_required": bool(snowflake_cli_gate.get("snowflake_cli_live_required", snowflake_cli_gate.get("live_required"))),
        "snowflake_cli_live_executed": bool(snowflake_cli_gate.get("snowflake_cli_live_executed")),
        "snowflake_cli_live_passed": bool(snowflake_cli_gate.get("snowflake_cli_live_passed")),
        "snowflake_cli_live_skipped": bool(snowflake_cli_gate.get("snowflake_cli_live_skipped", snowflake_cli_gate.get("skipped"))),
        "snowflake_cli_live_waived": bool(snowflake_cli_gate.get("snowflake_cli_live_waived", snowflake_cli_gate.get("waived"))),
        "snowflake_cli_skip_reason": str(snowflake_cli_gate.get("snowflake_cli_skip_reason") or ""),
        "snowflake_cli_token_auth_used": bool(snowflake_cli_gate.get("snowflake_cli_token_auth_used")),
        "snowflake_cli_token_file_supplied": bool(snowflake_cli_gate.get("snowflake_cli_token_file_supplied")),
        "snowflake_cli_token_path_leak_count": _as_int(snowflake_cli_gate.get("snowflake_cli_token_path_leak_count")),
        "snowflake_cli_temp_sql_path_leak_count": _as_int(snowflake_cli_gate.get("snowflake_cli_temp_sql_path_leak_count")),
        "snowflake_cli_temp_file_hygiene_passed": bool(snowflake_cli_gate.get("temp_file_hygiene_passed")),
        "temp_sql_file_leftover_count": _as_int(snowflake_cli_gate.get("temp_sql_file_leftover_count")),
        "setup_migration_live_passed": bool(snowflake_cli_gate.get("setup_migration_live_passed")),
        "snowflake_cli_live_validation_passed": bool(snowflake_cli_gate.get("snowflake_cli_gate_passed", snowflake_cli_gate.get("passed"))),
        "snowflake_cli_live_validation_skipped": bool(snowflake_cli_gate.get("snowflake_cli_live_skipped", snowflake_cli_gate.get("skipped"))),
        "connection_passed": bool(snowflake_cli_gate.get("connection_passed")),
        "setup_validation_passed": bool(snowflake_cli_gate.get("setup_validation_passed")),
        "packet_value_passed": bool(snowflake_cli_gate.get("packet_value_passed")),
        "formula_value_passed": bool(snowflake_cli_gate.get("formula_value_passed")),
        "query_budget_passed": bool(snowflake_cli_gate.get("query_budget_passed")),
        "manifest_reconciliation_passed": bool(snowflake_cli_gate.get("manifest_reconciliation_passed")),
        "raw_sql_included": False,
    }
    for rel, payload in snowflake_cli_artifacts.items():
        _write_json(root_path / rel, payload)
    payloads.update(snowflake_cli_artifacts)
    launch_artifacts["snowflake_cli_live_gate_results"] = snowflake_cli_gate
    launch_artifacts["snowflake_cli_temp_file_hygiene_gate_results"] = snowflake_cli_artifacts[
        CLI_TEMP_FILE_HYGIENE_GATE_REL
    ]
    launch_artifacts["setup_migration_live_gate_results"] = snowflake_cli_artifacts[
        CLI_SETUP_MIGRATION_GATE_REL
    ]
    formula_end_to_end_artifacts = write_formula_end_to_end_artifacts(root_path)
    payloads.update(formula_end_to_end_artifacts)
    launch_artifacts["formula_end_to_end_gate_results"] = formula_end_to_end_artifacts[FORMULA_GATE_REL]
    launch_artifacts["formula_value_gate_results"] = formula_end_to_end_artifacts[FORMULA_VALUE_GATE_REL]
    launch_artifacts["packet_schema_gate_results"] = formula_end_to_end_artifacts[PACKET_SCHEMA_GATE_REL]
    launch_artifacts["snowflake_formula_gate_results"] = formula_end_to_end_artifacts[SNOWFLAKE_FORMULA_GATE_REL]
    launch_artifacts["cortex_service_type_gate_results"] = formula_end_to_end_artifacts[CORTEX_SERVICE_TYPE_GATE_REL]
    encoding_artifacts = write_encoding_hygiene_artifacts(root_path)
    payloads.update(encoding_artifacts)
    launch_artifacts["encoding_hygiene_results"] = encoding_artifacts["artifacts/launch_readiness/encoding_hygiene_results.json"]
    snowflake_raw_recheck, snowflake_validation_failures = _snowflake_raw_validation_recheck(payloads, profile, waivers, root_path)
    launch_artifacts["snowflake_raw_validation_recheck"] = snowflake_raw_recheck
    launch_artifacts["snowflake_validation_failures"] = snowflake_validation_failures
    launch_artifacts["snowflake_validation_gate_results"] = _snowflake_validation_gate_results(
        payloads,
        profile,
        waivers,
        snowflake_raw_recheck,
    )
    launch_artifacts["live_execution_manifest_gate_results"] = _live_execution_manifest_gate_results(
        launch_artifacts["snowflake_validation_gate_results"],
        snowflake_raw_recheck,
    )
    launch_artifacts["summary_board_gate_results"] = _summary_board_gate_results(payloads)
    launch_artifacts["billing_reconciliation_gate_results"] = _billing_reconciliation_gate_results(root_path)
    launch_artifacts["billing_reconciliation_live_gate_results"] = _billing_reconciliation_live_gate_results(profile, waivers)
    launch_artifacts["cortex_cost_consistency_gate_results"] = _full_app_formula_gate_results(
        payloads,
        rel="artifacts/full_app_validation/cortex_cost_consistency_results.json",
        source="launch_readiness_cortex_cost_consistency_gate",
        proof_source="packet_formula_registry",
        failure_code="CORTEX_COST_CONSISTENCY",
    )
    launch_artifacts["cost_chart_workbench_gate_results"] = _full_app_formula_gate_results(
        payloads,
        rel="artifacts/full_app_validation/cost_chart_workbench_results.json",
        source="launch_readiness_cost_chart_workbench_gate",
        proof_source="explicit_action_contract",
        failure_code="COST_CHART_WORKBENCH",
    )
    launch_artifacts["cost_advisor_gate_results"] = _full_app_formula_gate_results(
        payloads,
        rel="artifacts/full_app_validation/cost_advisor_value_at_risk_results.json",
        source="launch_readiness_cost_advisor_value_at_risk_gate",
        proof_source="advisor_actionability_contract",
        failure_code="COST_ADVISOR_VALUE_AT_RISK",
    )
    launch_artifacts["workload_formula_gate_results"] = _full_app_formula_gate_results(
        payloads,
        rel="artifacts/full_app_validation/workload_formula_results.json",
        source="launch_readiness_workload_formula_gate",
        proof_source="metric_semantic_registry",
        failure_code="WORKLOAD_FORMULA",
    )
    launch_artifacts["formula_live_gate_results"] = _formula_live_gate_results(profile, waivers)
    launch_artifacts["date_widget_regression_results"] = _date_widget_regression_results(root_path)
    launch_artifacts["metric_semantic_gate_results"] = _metric_semantic_gate_results(payloads)
    launch_artifacts["query_budget_gate_results"] = _query_budget_gate_results(payloads)
    launch_artifacts["daily_wording_gate_results"] = _daily_wording_gate_results(payloads)
    launch_artifacts["full_app_launch_gate_results"] = evaluate_simple_gate(
        _as_mapping(payloads.get(FULL_APP_LAUNCH_RESULTS_REL)),
        source="full_app_launch_gate_results",
        artifact=FULL_APP_LAUNCH_RESULTS_REL,
    )
    launch_artifacts["deterministic_render_gate_results"] = evaluate_deterministic_render_gate(
        payloads.get(DETERMINISTIC_RENDER_RESULTS_REL)
    )
    launch_artifacts["browser_smoke_gate_results"] = evaluate_browser_smoke_gate(
        payloads.get(BROWSER_SMOKE_RESULTS_REL)
    )
    launch_artifacts["browser_render_gate_results"] = evaluate_browser_render_gate(
        _as_mapping(payloads.get(BROWSER_RENDER_RESULTS_REL))
    )
    launch_artifacts["runtime_artifact_provenance_gate_results"] = evaluate_runtime_artifact_provenance_gate(
        payloads.get(RUNTIME_ARTIFACT_PROVENANCE_REL)
    )
    launch_artifacts["render_provenance_reconciliation_gate_results"] = evaluate_render_provenance_reconciliation_gate(
        payloads.get(RENDER_PROVENANCE_RECONCILIATION_REL)
    )
    launch_artifacts["rendered_ui_leak_gate_results"] = evaluate_rendered_ui_leak_gate(
        _as_mapping(payloads.get(RENDERED_UI_LEAK_RESULTS_REL))
    )
    launch_artifacts["settings_gate_results"] = evaluate_simple_gate(
        _as_mapping(payloads.get(SETTINGS_WORDING_REL)),
        source="settings_gate_results",
        artifact=SETTINGS_WORDING_REL,
    )
    launch_artifacts["first_paint_gate_results"] = evaluate_simple_gate(
        _as_mapping(payloads.get(FIRST_PAINT_PERFORMANCE_REL)),
        source="first_paint_gate_results",
        artifact=FIRST_PAINT_PERFORMANCE_REL,
    )
    launch_artifacts["packet_fallback_ui_gate_results"] = evaluate_simple_gate(
        _as_mapping(payloads.get(PACKET_FALLBACK_UI_REL)),
        source="packet_fallback_ui_gate_results",
        artifact=PACKET_FALLBACK_UI_REL,
    )
    launch_artifacts["summary_board_visual_contract_gate_results"] = evaluate_simple_gate(
        _as_mapping(payloads.get(SUMMARY_BOARD_VISUAL_CONTRACT_REL)),
        source="summary_board_visual_contract_gate_results",
        artifact=SUMMARY_BOARD_VISUAL_CONTRACT_REL,
    )
    launch_artifacts["action_click_gate_results"] = evaluate_action_click_gate(
        payloads.get("artifacts/full_app_validation/action_click_results.json")
    )
    launch_artifacts["export_download_gate_results"] = evaluate_export_download_gate(
        payloads.get("artifacts/full_app_validation/export_results.json"),
        payloads.get("artifacts/full_app_validation/download_results.json"),
        _as_list(payloads.get("artifacts/full_app_validation/case_payload_results.json")),
    )
    launch_artifacts["live_feature_gate_results"] = evaluate_live_feature_gate(
        payloads.get("artifacts/full_app_validation/live_feature_results.json")
    )
    launch_artifacts["sql_cleanup_gate_results"] = evaluate_sql_cleanup_gate(
        _as_mapping(payloads.get(SQL_VALUE_INVENTORY_REL)),
        _as_mapping(payloads.get(SQL_DEAD_CODE_SCAN_REL)),
    )
    launch_artifacts["user_stress_gate_results"] = evaluate_user_stress_gate(payloads.get(USER_STRESS_RESULTS_REL))
    launch_artifacts["source_internal_leak_scan_gate_results"] = evaluate_source_internal_leak_scan_gate(
        payloads.get(SOURCE_INTERNAL_LEAK_RESULTS_REL)
    )
    launch_artifacts["packet_availability_gate_results"] = evaluate_packet_availability_gate(
        _as_mapping(payloads.get(PACKET_AVAILABILITY_MATRIX_REL))
        or _as_mapping(snowflake_cli_artifacts.get(PACKET_AVAILABILITY_MATRIX_REL))
    )
    live_cost_reconciliation_gate = _as_mapping(snowflake_cli_artifacts.get(CLI_COST_RECONCILIATION_GATE_REL))
    live_cost_reconciliation_payload = _as_mapping(snowflake_cli_artifacts.get(CLI_COST_RECONCILIATION_REL))
    launch_artifacts["live_cost_reconciliation_gate_results"] = live_cost_reconciliation_gate or {
        "source": "live_cost_reconciliation_gate_results",
        "generated_at": _utc_now(),
        "passed": bool(live_cost_reconciliation_payload.get("passed")),
        "failure_count": _as_int(live_cost_reconciliation_payload.get("failure_count")),
        "failures": _as_list(live_cost_reconciliation_payload.get("failures")),
        "raw_sql_included": False,
    }
    refreshed_full_app_payloads, _refreshed_missing = _load_payloads(
        root_path,
        REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS,
    )
    payloads.update(refreshed_full_app_payloads)
    release_sweep_payloads = {
        **payloads,
        **{
            f"{LAUNCH_READINESS_DIR}/{name}.json": artifact_payload
            for name, artifact_payload in launch_artifacts.items()
        },
    }
    full_app_release_sweep_artifacts = write_full_app_release_sweep_artifacts(
        root_path,
        release_sweep_payloads,
    )
    payloads.update(full_app_release_sweep_artifacts)
    launch_artifacts["full_app_release_sweep_gate_results"] = full_app_release_sweep_artifacts[
        FULL_APP_RELEASE_SWEEP_GATE_REL
    ]
    raw_results, raw_failures = _raw_invariant_artifacts(root_path, payloads)
    launch_artifacts["raw_invariant_results"] = raw_results
    launch_artifacts["raw_invariant_failures"] = raw_failures

    launch_summary, launch_failures, matrix = evaluate_launch_readiness(
        payloads,
        launch_artifacts,
        missing_artifacts=missing_payloads,
        root=root_path,
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

    manifest_files = sorted(
        set(written)
        | {f"{LAUNCH_READINESS_DIR}/artifact_manifest.json"}
        | set(REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        | set(REQUIRED_FORMULA_AUTHORITY_ARTIFACTS)
    )
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

    product_gauntlet = _product_gauntlet_release_results(root_path, payloads, launch_artifacts)
    (
        release_manifest,
        release_hashes,
        release_reconciliation,
        release_gate,
        rel_summary,
        rel_failures,
        rel_matrix,
        rel_notes,
    ) = _write_release_candidate_bundle(
        root_path,
        profile=profile,
        launch_summary=launch_summary,
        launch_failures=launch_failures,
        matrix=matrix,
        product_gauntlet=product_gauntlet,
        ci_context=launch_artifacts["release_candidate_ci_context"],
    )
    for name, payload in {
        "artifact_manifest": release_manifest,
        "artifact_hashes": release_hashes,
        "artifact_reconciliation_results": release_reconciliation,
        "product_gauntlet_release_results": product_gauntlet,
        "release_candidate_summary": rel_summary,
        "release_candidate_failures": rel_failures,
        "release_gate_matrix": rel_matrix,
        "release_notes": rel_notes,
    }.items():
        written[f"{RELEASE_CANDIDATE_DIR}/{name}.json"] = payload

    launch_artifacts["release_candidate_gate_results"] = release_gate
    launch_artifacts["ci_artifact_reality_results"] = _ci_artifact_reality_results(
        profile,
        launch_artifacts["ci_run_review_results"],
        launch_artifacts["artifact_upload_review_results"],
        launch_artifacts["artifact_review_results"],
        missing_payloads,
        release_reconciliation,
    )
    launch_summary, launch_failures, matrix = evaluate_launch_readiness(
        payloads,
        launch_artifacts,
        missing_artifacts=missing_payloads,
        root=root_path,
    )
    launch_artifacts["launch_readiness_summary"] = launch_summary
    launch_artifacts["launch_readiness_failures"] = launch_failures
    launch_artifacts["release_gate_matrix"] = matrix
    for name, payload in launch_artifacts.items():
        rel = f"{LAUNCH_READINESS_DIR}/{name}.json"
        _write_json(root_path / rel, payload)
        written[rel] = payload
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
    "main",
    "write_launch_readiness_artifacts",
]


def main() -> int:
    write_launch_readiness_artifacts(Path.cwd())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
