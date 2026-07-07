"""Account for visible metric mappings across Decision Workspace surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any


RESULTS_REL = "artifacts/full_app_validation/metric_render_mapping_results.json"
GATE_REL = "artifacts/launch_readiness/metric_render_mapping_gate_results.json"


EXECUTIVE_COCO_PANEL_MAPPINGS: tuple[dict[str, str], ...] = (
    {
        "section": "Executive Landing",
        "surface": "Executive KPIs",
        "metric_key": "credits_used",
        "visible_label": "Credits Used",
        "source_key": "warehouse_credits",
        "source_fields": "SectionCommandMetric[warehouse_credits], summary CREDITS_USED",
        "render_path": "sections.command_center_components.render_coco_kpi_row",
    },
    {
        "section": "Executive Landing",
        "surface": "Executive KPIs",
        "metric_key": "active_warehouses",
        "visible_label": "Active Warehouses",
        "source_key": "warehouse_credits",
        "source_fields": "warehouse_slices, summary WAREHOUSE_NAME",
        "render_path": "sections.command_center_components.render_coco_kpi_row",
    },
    {
        "section": "Executive Landing",
        "surface": "Executive KPIs",
        "metric_key": "open_actions",
        "visible_label": "Open Actions",
        "source_key": "action_queue",
        "source_fields": "SectionCommandBrief.exceptions, next_actions",
        "render_path": "sections.command_center_components.render_coco_kpi_row",
    },
    {
        "section": "Executive Landing",
        "surface": "Executive KPIs",
        "metric_key": "account_health",
        "visible_label": "Account Health",
        "source_key": "executive_observability",
        "source_fields": "SectionCommandMetric[account_health|platform_health]",
        "render_path": "sections.command_center_components.render_coco_kpi_row",
    },
    {
        "section": "Executive Landing",
        "surface": "Daily Credit Consumption",
        "metric_key": "daily_credit_consumption",
        "visible_label": "Daily Credit Consumption",
        "source_key": "warehouse_credits",
        "source_fields": "SectionCommandMetric.trend_points, summary USAGE_DATE + CREDITS_USED",
        "render_path": "sections.command_center_components.render_coco_credit_consumption_panel",
    },
    {
        "section": "Executive Landing",
        "surface": "Top Warehouses by Credits",
        "metric_key": "top_warehouses_by_credits",
        "visible_label": "Top Warehouses by Credits",
        "source_key": "warehouse_credits",
        "source_fields": "raw_payload.warehouse_slices, summary WAREHOUSE_NAME + CREDITS_USED",
        "render_path": "sections.command_center_components.render_coco_warehouse_panel",
    },
)

SUMMARY_MART_MAPPINGS: tuple[dict[str, str], ...] = (
    {
        "section": "Workload Operations",
        "workflow": "Workload Overview",
        "surface": "Workload summary metrics",
        "metric_key": "query_daily_summary",
        "visible_label": "Query volume, failures, queue, elapsed, scanned bytes, credits",
        "source_key": "summary_mart_query_daily",
        "source_object": "V_QUERY_DAILY_SUMMARY",
        "source_fields": "QUERY_COUNT, FAILED_QUERY_COUNT, QUEUED_QUERY_COUNT, TOTAL_ELAPSED_MS, BYTES_SCANNED, CREDITS_ESTIMATE, TOP_WAREHOUSE_NAME, TOP_USER_NAME, UPDATED_AT",
        "render_path": "sections.summary_mart_loaders.load_query_daily_summary",
        "load_boundary": "section_summary_autoload",
    },
    {
        "section": "Executive Landing",
        "workflow": "Executive Overview",
        "surface": "Daily Credit Consumption / Top Warehouses by Credits",
        "metric_key": "warehouse_daily_credits",
        "visible_label": "Daily credit trend and warehouse credit ranking",
        "source_key": "summary_mart_warehouse_credits",
        "source_object": "V_WAREHOUSE_DAILY_CREDITS",
        "source_fields": "USAGE_DATE, WAREHOUSE_NAME, CREDITS_USED, COST_USD, QUERY_COUNT, QUEUED_SECONDS, SPILL_BYTES, UPDATED_AT",
        "render_path": "sections.summary_mart_loaders.load_warehouse_daily_credits",
        "load_boundary": "section_summary_autoload",
    },
    {
        "section": "Cost & Contract",
        "workflow": "Cortex AI",
        "surface": "Cortex token efficiency",
        "metric_key": "cortex_daily_usage",
        "visible_label": "Cortex tokens, requests, credits, cost, and efficiency ratios",
        "source_key": "summary_mart_cortex_daily",
        "source_object": "V_CORTEX_DAILY_USAGE",
        "source_fields": "USER_DISPLAY_NAME, USER_CHART_LABEL, SERVICE_TYPE, TOTAL_TOKENS, TOTAL_REQUESTS, TOTAL_CREDITS, COST_USD, TOKENS_PER_REQUEST, TOKENS_PER_DOLLAR, COST_PER_1K_TOKENS_USD, AI_CREDITS_PER_1K_TOKENS, UPDATED_AT",
        "render_path": "sections.summary_mart_loaders.load_cortex_daily_usage",
        "load_boundary": "explicit_action_or_section_summary",
    },
    {
        "section": "Security Monitoring",
        "workflow": "Security Overview",
        "surface": "Login security summary",
        "metric_key": "login_security_daily",
        "visible_label": "Failed logins, successful logins, affected users, MFA gaps, suspicious IPs",
        "source_key": "summary_mart_login_security",
        "source_object": "V_LOGIN_SECURITY_DAILY",
        "source_fields": "EVENT_DATE, FAILED_LOGIN_COUNT, SUCCESS_LOGIN_COUNT, AFFECTED_USER_COUNT, MFA_GAP_USER_COUNT, SUSPICIOUS_IP_COUNT, UPDATED_AT",
        "render_path": "sections.summary_mart_loaders.load_login_security_daily",
        "load_boundary": "section_summary_autoload",
    },
    {
        "section": "DBA Control Room",
        "workflow": "Morning Cockpit",
        "surface": "Task and procedure summary",
        "metric_key": "task_status_daily",
        "visible_label": "Failed tasks, failed procedures, SLA breaches, queued runs, recovery actions",
        "source_key": "summary_mart_task_status",
        "source_object": "V_TASK_STATUS_DAILY",
        "source_fields": "EVENT_DATE, FAILED_TASK_COUNT, FAILED_PROCEDURE_COUNT, SLA_BREACH_COUNT, QUEUED_RUN_COUNT, RECOVERY_ACTION_COUNT, UPDATED_AT",
        "render_path": "sections.summary_mart_loaders.load_task_status_daily",
        "load_boundary": "section_summary_autoload",
    },
    {
        "section": "Security Monitoring",
        "workflow": "Security Overview",
        "surface": "Security posture summary",
        "metric_key": "security_posture_daily",
        "visible_label": "Critical, high, medium, and credential-expiration security findings",
        "source_key": "summary_mart_security_posture",
        "source_object": "V_SECURITY_POSTURE_DAILY",
        "source_fields": "EVENT_DATE, CRITICAL_FINDING_COUNT, HIGH_FINDING_COUNT, MEDIUM_FINDING_COUNT, CREDENTIAL_EXPIRATION_RISK_COUNT, EXPIRED_CREDENTIAL_COUNT, EXPIRING_30D_CREDENTIAL_COUNT, UPDATED_AT",
        "render_path": "sections.summary_mart_loaders.load_security_posture_daily",
        "load_boundary": "section_summary_autoload",
    },
    {
        "section": "Executive Landing",
        "workflow": "Executive Overview",
        "surface": "Executive packet summary",
        "metric_key": "executive_packet_current",
        "visible_label": "Section summary, top findings, top actions",
        "source_key": "summary_mart_executive_packet",
        "source_object": "V_EXECUTIVE_PACKET_CURRENT",
        "source_fields": "SECTION, WINDOW_DAYS, SUMMARY_JSON, TOP_FINDINGS_JSON, TOP_ACTIONS_JSON, UPDATED_AT",
        "render_path": "sections.summary_mart_loaders.load_executive_packet_current",
        "load_boundary": "section_summary_autoload",
    },
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _prepare_imports(root: Path) -> None:
    app_root = root / ".overwatch_final"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def build_metric_render_mapping_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    _prepare_imports(root_path)
    from sections.metric_semantic_registry import all_metric_semantics
    from sections.section_command_contracts import SECTION_COMMAND_CONTRACTS

    semantic_rows = list(all_metric_semantics())
    semantic_keys = {(row.section, row.metric_key) for row in semantic_rows}
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for semantic in semantic_rows:
        failure_reasons: list[str] = []
        if not semantic.label:
            failure_reasons.append("missing_visible_label")
        if not semantic.source_family:
            failure_reasons.append("missing_source_family")
        if not semantic.source_view_or_mart:
            failure_reasons.append("missing_source_view_or_mart")
        if not semantic.render_surface:
            failure_reasons.append("missing_render_surface")
        if not semantic.metric_format:
            failure_reasons.append("missing_metric_format")
        source_fields = ", ".join(
            field
            for field in (
                semantic.packet_field,
                semantic.numerator_field,
                semantic.denominator_field,
                semantic.freshness_field,
                semantic.source_status_field,
                semantic.source_confirmed_zero_field,
            )
            if field
        ) or semantic.aggregation
        row = {
            "section": semantic.section,
            "workflow": "Governed metric catalog",
            "surface": semantic.render_surface,
            "metric_key": semantic.metric_key,
            "visible_label": semantic.label,
            "source_key": semantic.source_family,
            "source_family": semantic.source_family,
            "source_object": semantic.source_view_or_mart,
            "source_fields": source_fields,
            "render_path": "sections.metric_semantic_registry.all_metric_semantics",
            "metric_family": semantic.metric_family,
            "metric_format": semantic.metric_format,
            "unit": semantic.unit or semantic.value_unit,
            "packet_field": semantic.packet_field,
            "aggregation": semantic.aggregation,
            "export_surface": semantic.export_surface,
            "export_domain": semantic.export_domain,
            "launch_gate": semantic.launch_gate,
            "semantic_registered": True,
            "mapping_type": "semantic_catalog",
            "passed": not failure_reasons,
            "failure_reason": "; ".join(failure_reasons),
            "raw_sql_included": False,
        }
        rows.append(row)
        if failure_reasons:
            failures.append(row)

    for section, contract in SECTION_COMMAND_CONTRACTS.items():
        source_keys = {source.source_key for source in contract.source_configs}
        for metric in contract.metric_contracts:
            failure_reasons: list[str] = []
            if not metric.label:
                failure_reasons.append("missing_visible_label")
            if not metric.source_key:
                failure_reasons.append("missing_source_key")
            elif metric.source_key not in source_keys:
                failure_reasons.append("source_key_not_in_section_sources")
            if not metric.metric_format:
                failure_reasons.append("missing_metric_format")
            semantic_registered = (section, metric.key) in semantic_keys
            row = {
                "section": section,
                "workflow": contract.default_view,
                "surface": "CommandBrief metric row",
                "metric_key": metric.key,
                "visible_label": metric.label,
                "source_key": metric.source_key,
                "source_fields": f"packet metric key {metric.key}",
                "render_path": "sections.section_command_rendering.render_section_command_brief",
                "metric_format": metric.metric_format,
                "unit": metric.unit,
                "semantic_registered": semantic_registered,
                "mapping_type": "semantic_registry" if semantic_registered else "section_contract",
                "passed": not failure_reasons,
                "failure_reason": "; ".join(failure_reasons),
                "raw_sql_included": False,
            }
            rows.append(row)
            if failure_reasons:
                failures.append(row)

    for mapping in EXECUTIVE_COCO_PANEL_MAPPINGS:
        failure_reasons = []
        if not mapping.get("source_key"):
            failure_reasons.append("missing_source_key")
        if not mapping.get("source_fields"):
            failure_reasons.append("missing_source_fields")
        row = {
            **mapping,
            "workflow": "Executive Overview",
            "metric_format": "derived",
            "unit": "",
            "semantic_registered": False,
            "mapping_type": "runtime_model_mapping",
            "passed": not failure_reasons,
            "failure_reason": "; ".join(failure_reasons),
            "raw_sql_included": False,
        }
        rows.append(row)
        if failure_reasons:
            failures.append(row)

    for mapping in SUMMARY_MART_MAPPINGS:
        failure_reasons = []
        for required_key in ("section", "workflow", "surface", "metric_key", "visible_label", "source_object", "source_fields", "render_path"):
            if not mapping.get(required_key):
                failure_reasons.append(f"missing_{required_key}")
        row = {
            **mapping,
            "metric_format": "summary_mart",
            "unit": "",
            "semantic_registered": False,
            "mapping_type": "summary_mart_mapping",
            "passed": not failure_reasons,
            "failure_reason": "; ".join(failure_reasons),
            "raw_sql_included": False,
        }
        rows.append(row)
        if failure_reasons:
            failures.append(row)

    section_counts: dict[str, int] = {}
    for row in rows:
        section = str(row["section"])
        section_counts[section] = section_counts.get(section, 0) + 1

    return {
        "generated_at": _now(),
        "producer": "metric_render_mapping_audit",
        "source": "metric_render_mapping_results",
        "row_count": len(rows),
        "section_counts": section_counts,
        "semantic_catalog_count": sum(1 for row in rows if row["mapping_type"] == "semantic_catalog"),
        "semantic_registered_count": sum(
            1
            for row in rows
            if row["mapping_type"] == "section_contract" and row["semantic_registered"]
        ),
        "section_contract_count": sum(1 for row in rows if row["mapping_type"] == "section_contract"),
        "runtime_model_mapping_count": sum(1 for row in rows if row["mapping_type"] == "runtime_model_mapping"),
        "summary_mart_mapping_count": sum(1 for row in rows if row["mapping_type"] == "summary_mart_mapping"),
        "failure_count": len(failures),
        "passed": not failures,
        "failures": failures,
        "rows": rows,
        "raw_sql_included": False,
    }


def evaluate_metric_render_mapping_gate(payload: dict[str, Any]) -> dict[str, Any]:
    failures = list(payload.get("failures") or [])
    return {
        "generated_at": _now(),
        "producer": "metric_render_mapping_audit",
        "source": "metric_render_mapping_gate_results",
        "passed": bool(payload.get("passed")) and not failures,
        "metric_mapping_row_count": int(payload.get("row_count") or 0),
        "metric_mapping_failure_count": len(failures),
        "semantic_catalog_count": int(payload.get("semantic_catalog_count") or 0),
        "semantic_registered_count": int(payload.get("semantic_registered_count") or 0),
        "section_contract_count": int(payload.get("section_contract_count") or 0),
        "runtime_model_mapping_count": int(payload.get("runtime_model_mapping_count") or 0),
        "summary_mart_mapping_count": int(payload.get("summary_mart_mapping_count") or 0),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_metric_render_mapping_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_metric_render_mapping_results(root_path)
    gate = evaluate_metric_render_mapping_gate(results)
    _write_json(root_path / RESULTS_REL, results)
    _write_json(root_path / GATE_REL, gate)
    return {RESULTS_REL: results, GATE_REL: gate}


if __name__ == "__main__":
    artifacts = write_metric_render_mapping_artifacts(Path.cwd())
    gate = artifacts[GATE_REL]
    print(
        f"metric_render_mapping passed={gate['passed']} "
        f"rows={gate['metric_mapping_row_count']} failures={gate['metric_mapping_failure_count']}"
    )
    raise SystemExit(0 if gate["passed"] else 1)
