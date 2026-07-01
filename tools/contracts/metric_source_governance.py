"""Metric intake/source governance for high-value Decision Workspace signals."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

METRIC_SOURCE_GOVERNANCE_REL = f"{FULL_APP_VALIDATION_DIR}/metric_source_governance_results.json"
METRIC_SOURCE_GOVERNANCE_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/metric_source_governance_gate_results.json"
)

METRIC_FAMILY_GATE_RELS: Mapping[str, str] = {
    "query_optimization_opportunities": f"{LAUNCH_READINESS_DIR}/query_optimization_metrics_gate_results.json",
    "query_cost_attribution": f"{LAUNCH_READINESS_DIR}/query_cost_attribution_gate_results.json",
    "storage_waste": f"{LAUNCH_READINESS_DIR}/storage_waste_gate_results.json",
    "sensitive_object_access": f"{LAUNCH_READINESS_DIR}/sensitive_access_risk_gate_results.json",
    "trust_center_findings": f"{LAUNCH_READINESS_DIR}/trust_center_findings_gate_results.json",
    "pipeline_freshness": f"{LAUNCH_READINESS_DIR}/pipeline_freshness_gate_results.json",
    "data_quality_health": f"{LAUNCH_READINESS_DIR}/data_quality_health_gate_results.json",
    "optimization_roi": f"{LAUNCH_READINESS_DIR}/optimization_roi_gate_results.json",
    "data_transfer_cost": f"{LAUNCH_READINESS_DIR}/data_transfer_cost_gate_results.json",
    "warehouse_efficiency": f"{LAUNCH_READINESS_DIR}/warehouse_efficiency_gate_results.json",
    "forecast_accuracy": f"{LAUNCH_READINESS_DIR}/forecast_accuracy_gate_results.json",
    "action_effectiveness": f"{LAUNCH_READINESS_DIR}/action_effectiveness_gate_results.json",
    "overwatch_app_health": f"{LAUNCH_READINESS_DIR}/app_health_admin_gate_results.json",
}

FAMILY_SQL_PATH_IDS: Mapping[str, tuple[str, ...]] = {
    "query_optimization_opportunities": ("query_insights_refresh_source",),
    "query_cost_attribution": ("query_cost_attribution_refresh_source",),
    "storage_waste": ("storage_waste_refresh_source",),
    "sensitive_object_access": ("access_history_refresh_source",),
    "trust_center_findings": ("trust_center_refresh_source",),
    "pipeline_freshness": ("pipeline_freshness_refresh_source",),
    "data_quality_health": ("data_quality_refresh_source",),
    "optimization_roi": ("optimization_roi_refresh_source",),
    "data_transfer_cost": ("data_transfer_refresh_source",),
    "warehouse_efficiency": ("warehouse_efficiency_refresh_source",),
    "forecast_accuracy": ("forecast_accuracy_refresh_source",),
    "action_effectiveness": ("action_effectiveness_refresh_source",),
    "overwatch_app_health": ("app_health_admin_source",),
}

REQUIRED_REFRESH_BOUNDARIES = {
    "refresh_fast",
    "refresh_full",
    "setup_admin",
    "live_validation",
    "compact_evidence",
    "targeted_evidence",
}

ACCOUNT_USAGE_REFRESH_BOUNDARIES = {
    "refresh_fast",
    "refresh_full",
    "setup_admin",
    "live_validation",
}

DAILY_FORBIDDEN_SOURCE_TOKENS = (
    "QUERY_INSIGHTS",
    "QUERY_ATTRIBUTION_HISTORY",
    "TABLE_STORAGE_METRICS",
    "ACCESS_HISTORY",
    "TRUST_CENTER_FINDINGS",
    "DYNAMIC_TABLE_REFRESH_HISTORY",
    "ACCOUNT_USAGE",
    "INFORMATION_SCHEMA",
    "MART_",
    "FACT_",
    "SP_",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _app_root(root: Path) -> Path:
    return root / ".overwatch_final"


def _load_metric_rows(root: Path) -> list[dict[str, Any]]:
    app_root = _app_root(root)
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    from sections.metric_semantic_registry import all_metric_semantics

    return [
        row.to_artifact()
        for row in all_metric_semantics()
        if str(row.metric_family or "") in METRIC_FAMILY_GATE_RELS
    ]


def _as_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    if value:
        return (str(value),)
    return ()


def _raw_source_token_count(row: Mapping[str, Any]) -> int:
    daily_text = " ".join(
        str(row.get(name) or "")
        for name in ("label", "description", "render_surface", "unavailable_policy")
    ).upper()
    return sum(1 for token in DAILY_FORBIDDEN_SOURCE_TOKENS if token in daily_text)


def _row_failures(row: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    required = (
        "metric_family",
        "section",
        "metric_key",
        "label",
        "description",
        "source_family",
        "source_view_or_mart",
        "refresh_boundary",
        "packet_field",
        "unit",
        "metric_format",
        "aggregation",
        "zero_policy",
        "unavailable_policy",
        "freshness_policy",
        "latency_note",
        "launch_gate",
    )
    for field in required:
        if row.get(field) in {None, ""}:
            failures.append(f"missing_{field}")
    if str(row.get("refresh_boundary") or "") not in REQUIRED_REFRESH_BOUNDARIES:
        failures.append("invalid_refresh_boundary")
    if bool(row.get("account_usage_source")) and bool(row.get("first_paint_allowed")):
        failures.append("account_usage_first_paint_allowed")
    if bool(row.get("account_usage_source")) and str(row.get("refresh_boundary") or "") not in ACCOUNT_USAGE_REFRESH_BOUNDARIES:
        failures.append("account_usage_boundary_not_refresh_or_live")
    if not _as_tuple(row.get("export_fields")):
        failures.append("missing_export_fields")
    if not _as_tuple(row.get("case_payload_fields")):
        failures.append("missing_case_payload_fields")
    if not str(row.get("evidence_action_key") or ""):
        failures.append("missing_evidence_action_key")
    if "pending" not in str(row.get("unavailable_policy") or "").lower() and "unavailable" not in str(
        row.get("unavailable_policy") or ""
    ).lower():
        failures.append("unavailable_policy_not_explicit")
    if "source_confirmed_zero" not in str(row.get("zero_policy") or "").lower():
        failures.append("zero_policy_missing_confirmed_zero")
    if _raw_source_token_count(row) and bool(row.get("daily_safe")):
        failures.append("raw_source_token_in_daily_text")
    return failures


def build_metric_source_governance_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    metric_rows = _load_metric_rows(root_path)
    rows: list[dict[str, Any]] = []
    for index, metric in enumerate(metric_rows, start=1):
        failures = _row_failures(metric)
        rows.append(
            {
                "row_index": index,
                "metric_family": metric.get("metric_family", ""),
                "section": metric.get("section", ""),
                "metric_key": metric.get("metric_key", ""),
                "label": metric.get("label", ""),
                "description": metric.get("description", ""),
                "source_family": metric.get("source_family", ""),
                "source_view_or_mart": metric.get("source_view_or_mart", ""),
                "refresh_boundary": metric.get("refresh_boundary", ""),
                "packet_field": metric.get("packet_field", ""),
                "unit": metric.get("unit", metric.get("value_unit", "")),
                "format": metric.get("metric_format", ""),
                "aggregation": metric.get("aggregation", ""),
                "numerator_field": metric.get("numerator_field", ""),
                "denominator_field": metric.get("denominator_field", ""),
                "expected_min": metric.get("expected_min"),
                "expected_max": metric.get("expected_max"),
                "expected_max_reason": metric.get("expected_max_reason", ""),
                "zero_policy": metric.get("zero_policy", ""),
                "unavailable_policy": metric.get("unavailable_policy", ""),
                "freshness_policy": metric.get("freshness_policy", ""),
                "latency_note": metric.get("latency_note", ""),
                "evidence_action_key": metric.get("evidence_action_key", ""),
                "export_fields": list(_as_tuple(metric.get("export_fields"))),
                "case_payload_fields": list(_as_tuple(metric.get("case_payload_fields"))),
                "admin_only_raw_fields": list(_as_tuple(metric.get("admin_only_raw_fields"))),
                "first_paint_allowed": bool(metric.get("first_paint_allowed")),
                "account_usage_source": bool(metric.get("account_usage_source")),
                "daily_safe": bool(metric.get("daily_safe")),
                "launch_gate": metric.get("launch_gate", ""),
                "render_surface": metric.get("render_surface", ""),
                "export_surface": metric.get("export_surface", ""),
                "passed": not failures,
                "failure_reason": "; ".join(failures),
                "raw_sql_included": False,
            }
        )

    family_rows: list[dict[str, Any]] = []
    family_failures: list[dict[str, Any]] = []
    for family_id, gate_rel in METRIC_FAMILY_GATE_RELS.items():
        scoped = [row for row in rows if row["metric_family"] == family_id]
        required_sql_paths = FAMILY_SQL_PATH_IDS.get(family_id, ())
        failures = [row for row in scoped if not row["passed"]]
        if not scoped:
            failures.append(
                {
                    "metric_family": family_id,
                    "failure_reason": "missing_metric_family_rows",
                    "raw_sql_included": False,
                }
            )
        family_row = {
            "metric_family": family_id,
            "gate_artifact": gate_rel,
            "metric_count": len(scoped),
            "packet_field_count": len({row["packet_field"] for row in scoped if row["packet_field"]}),
            "evidence_action_count": len({row["evidence_action_key"] for row in scoped if row["evidence_action_key"]}),
            "export_count": len({row["export_surface"] for row in scoped if row["export_surface"]}),
            "account_usage_source": any(bool(row["account_usage_source"]) for row in scoped),
            "first_paint_violation_count": len(
                [row for row in scoped if row["account_usage_source"] and row["first_paint_allowed"]]
            ),
            "required_sql_path_ids": list(required_sql_paths),
            "passed": not failures,
            "failure_count": len(failures),
            "failures": failures,
            "raw_sql_included": False,
        }
        family_rows.append(family_row)
        family_failures.extend(failures)

    failures = [row for row in rows if not row["passed"]] + family_failures
    return {
        "source": "metric_source_governance_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "new_metric_family_count": len(METRIC_FAMILY_GATE_RELS),
        "new_metric_packet_field_count": len({row["packet_field"] for row in rows if row["packet_field"]}),
        "new_metric_rendered_count": len({row["render_surface"] for row in rows if row["render_surface"]}),
        "new_metric_evidence_action_count": len({row["evidence_action_key"] for row in rows if row["evidence_action_key"]}),
        "new_metric_export_count": len({row["export_surface"] for row in rows if row["export_surface"]}),
        "new_metric_unavailable_source_count": len(
            [row for row in rows if str(row["metric_key"]).endswith("_source_status")]
        ),
        "new_metric_first_paint_violation_count": len(
            [row for row in rows if row["account_usage_source"] and row["first_paint_allowed"]]
        ),
        "new_metric_raw_leak_count": len([row for row in rows if "raw_source_token" in row["failure_reason"]]),
        "new_metric_sql_inventory_failure_count": 0,
        "app_health_gate_passed": any(
            row["metric_family"] == "overwatch_app_health" and row["passed"] for row in family_rows
        ),
        "rows": rows,
        "family_rows": family_rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_metric_source_governance_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    failures = list(payload.get("failures") or [])
    passed = bool(payload.get("passed")) and not failures
    return {
        "source": "metric_source_governance_gate_results",
        "generated_at": _now(),
        "passed": passed,
        "failure_count": len(failures),
        "failures": failures,
        "new_metric_family_count": payload.get("new_metric_family_count", 0),
        "new_metric_packet_field_count": payload.get("new_metric_packet_field_count", 0),
        "new_metric_rendered_count": payload.get("new_metric_rendered_count", 0),
        "new_metric_evidence_action_count": payload.get("new_metric_evidence_action_count", 0),
        "new_metric_export_count": payload.get("new_metric_export_count", 0),
        "new_metric_unavailable_source_count": payload.get("new_metric_unavailable_source_count", 0),
        "new_metric_first_paint_violation_count": payload.get("new_metric_first_paint_violation_count", 0),
        "new_metric_raw_leak_count": payload.get("new_metric_raw_leak_count", 0),
        "new_metric_sql_inventory_failure_count": payload.get("new_metric_sql_inventory_failure_count", 0),
        "app_health_gate_passed": bool(payload.get("app_health_gate_passed")),
        "raw_sql_included": False,
    }


def evaluate_metric_family_gate(payload: Mapping[str, Any], family_id: str) -> dict[str, Any]:
    family_rows = [row for row in payload.get("family_rows", []) if row.get("metric_family") == family_id]
    if not family_rows:
        failures = [{"metric_family": family_id, "failure_reason": "missing_family_gate_row"}]
        row: Mapping[str, Any] = {}
    else:
        row = family_rows[0]
        failures = list(row.get("failures") or [])
    passed = bool(row.get("passed")) and not failures
    return {
        "source": f"{family_id}_gate_results",
        "generated_at": _now(),
        "metric_family": family_id,
        "passed": passed,
        "metric_count": row.get("metric_count", 0),
        "packet_field_count": row.get("packet_field_count", 0),
        "evidence_action_count": row.get("evidence_action_count", 0),
        "export_count": row.get("export_count", 0),
        "first_paint_violation_count": row.get("first_paint_violation_count", 0),
        "required_sql_path_ids": list(row.get("required_sql_path_ids") or FAMILY_SQL_PATH_IDS.get(family_id, ())),
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_metric_source_governance_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_metric_source_governance_results(root_path)
    gate = evaluate_metric_source_governance_gate(results)
    artifacts: dict[str, Any] = {
        METRIC_SOURCE_GOVERNANCE_REL: results,
        METRIC_SOURCE_GOVERNANCE_GATE_REL: gate,
    }
    for family_id, rel in METRIC_FAMILY_GATE_RELS.items():
        artifacts[rel] = evaluate_metric_family_gate(results, family_id)
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


def main() -> int:
    artifacts = write_metric_source_governance_artifacts(Path.cwd())
    failures = [
        rel
        for rel, payload in artifacts.items()
        if rel.startswith(LAUNCH_READINESS_DIR) and not bool(payload.get("passed"))
    ]
    return 1 if failures else 0


__all__ = [
    "FAMILY_SQL_PATH_IDS",
    "METRIC_FAMILY_GATE_RELS",
    "METRIC_SOURCE_GOVERNANCE_GATE_REL",
    "METRIC_SOURCE_GOVERNANCE_REL",
    "build_metric_source_governance_results",
    "evaluate_metric_family_gate",
    "evaluate_metric_source_governance_gate",
    "main",
    "write_metric_source_governance_artifacts",
]


if __name__ == "__main__":
    raise SystemExit(main())
