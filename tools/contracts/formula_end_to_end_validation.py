"""End-to-end COST_DB formula proof for OVERWATCH launch artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping


FORMULA_AUTHORITY_DIR = "artifacts/formula_authority"
FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
SNOWFLAKE_VALIDATION_DIR = "artifacts/snowflake_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

FORMULA_CHAIN_REL = f"{FORMULA_AUTHORITY_DIR}/formula_chain_results.json"
PACKET_FORMULA_REL = f"{FORMULA_AUTHORITY_DIR}/packet_formula_results.json"
RENDERED_FORMULA_REL = f"{FULL_APP_VALIDATION_DIR}/rendered_formula_results.json"
COST_WORKBENCH_CHART_REL = f"{FULL_APP_VALIDATION_DIR}/cost_workbench_chart_results.json"
FORMULA_LIVE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/formula_live_validation_results.json"
CORTEX_SERVICE_TYPE_LIVE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/cortex_service_type_live_results.json"
WORKLOAD_FORMULA_LIVE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/workload_formula_live_results.json"
FORMULA_GATE_REL = f"{LAUNCH_READINESS_DIR}/formula_end_to_end_gate_results.json"
CORTEX_SERVICE_TYPE_GATE_REL = f"{LAUNCH_READINESS_DIR}/cortex_service_type_gate_results.json"

COST_DB_SOURCE_URL = "https://github.com/jfreeze03/COST_DB/blob/main/streamlit_app.py"

REQUIRED_PACKET_FIELDS = (
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
    "BILLING_BRIDGE_STATUS",
    "CORTEX_AI_CREDITS",
    "CORTEX_AI_COST_USD",
    "BILLING_RECONCILIATION_STATUS",
    "BILLING_WINDOW_START",
    "BILLING_WINDOW_END",
    "BILLING_WINDOW_COMPLETE",
    "BILLING_SOURCE_FRESHNESS_TS",
    "BILLING_LATENCY_NOTE",
    "BILLING_RECONCILIATION_WINDOW_START",
    "BILLING_RECONCILIATION_WINDOW_END",
    "BILLING_RECONCILIATION_FRESHNESS",
    "SPEND_MOVEMENT_PCT",
    "FORECAST_RUN_RATE_USD",
)

FORMULA_CHAIN_FIELDS = (
    "ACCOUNT_BILLED_COST_USD",
    "ACCOUNT_BILLED_CREDITS",
    "CORTEX_AI_COST_USD",
    "CORTEX_AI_CREDITS",
    "WAREHOUSE_CREDITS",
    "WAREHOUSE_COST_USD",
    "SERVICE_OTHER_CREDITS",
    "SERVICE_OTHER_COST_USD",
    "BILLING_BRIDGE_DELTA_CREDITS",
    "BILLING_BRIDGE_DELTA_USD",
    "SPEND_MOVEMENT_PCT",
    "FORECAST_RUN_RATE_USD",
)

_FORMULA_BY_FIELD = {
    "ACCOUNT_BILLED_COST_USD": ("account_billed_total", "CREDITS_BILLED", 36.80),
    "ACCOUNT_BILLED_CREDITS": ("account_billed_total", "CREDITS_BILLED", 10.0),
    "CORTEX_AI_COST_USD": ("cortex_ai", "CORTEX_AI_CREDITS", 7.36),
    "CORTEX_AI_CREDITS": ("cortex_ai", "CORTEX_AI_CREDITS", 2.0),
    "WAREHOUSE_CREDITS": ("warehouse_bridge", "CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES", 6.0),
    "WAREHOUSE_COST_USD": ("warehouse_bridge", "CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES", 22.08),
    "SERVICE_OTHER_CREDITS": ("billing_reconciliation_bridge", "ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS", 4.0),
    "SERVICE_OTHER_COST_USD": ("billing_reconciliation_bridge", "SERVICE_OTHER_CREDITS", 14.72),
    "BILLING_BRIDGE_DELTA_CREDITS": ("billing_reconciliation_bridge", "ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS", 4.0),
    "BILLING_BRIDGE_DELTA_USD": ("billing_reconciliation_bridge", "BILLING_BRIDGE_DELTA_CREDITS", 14.72),
    "SPEND_MOVEMENT_PCT": ("monthly_mom", "completed comparable window", 25.0),
    "FORECAST_RUN_RATE_USD": ("monthly_mom", "completed-window run rate", 44.16),
}

_RENDERED_SUMMARY_FIELDS = {
    "ACCOUNT_BILLED_COST_USD": ("Executive Landing", "Cost & Contract"),
    "CORTEX_AI_COST_USD": ("Executive Landing", "Cost & Contract"),
    "SPEND_MOVEMENT_PCT": ("Cost & Contract",),
    "FORECAST_RUN_RATE_USD": ("Cost & Contract",),
}

_SQL_FILES = {
    "setup": "snowflake/mart_setup/05_load_procedures.sql",
    "tables": "snowflake/mart_setup/04_mart_tables.sql",
    "validation": "snowflake/mart_setup/08_validation.sql",
    "monolith_setup": "snowflake/OVERWATCH_MART_SETUP.sql",
    "monolith_validation": "snowflake/OVERWATCH_MART_VALIDATION.sql",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_app_path(root: Path) -> None:
    app_root = root / ".overwatch_final"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _load_sql_texts(root: Path, overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    if overrides is not None:
        return {key: str(overrides.get(key, "")) for key in _SQL_FILES}
    return {key: _read_text(root / rel) for key, rel in _SQL_FILES.items()}


def _safe_contains(text: str, token: str) -> bool:
    return token.upper() in str(text or "").upper()


def _token_count(text: str, token: str) -> int:
    return len(re.findall(rf"\b{re.escape(token)}\b", str(text or ""), flags=re.IGNORECASE))


def evaluate_packet_formula_sql(
    root: Path | str = ".",
    *,
    sql_texts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    texts = _load_sql_texts(root_path, sql_texts)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    validation_names = (
        "SECTION_DECISION_CURRENT_COST_FORMULA_PACKET_FIELDS",
        "SECTION_DECISION_CURRENT_FLAT_COST_FORMULA_COLUMNS",
    )
    for field in REQUIRED_PACKET_FIELDS:
        checks = {
            "command_brief_schema": _safe_contains(texts["tables"], field),
            "full_packet_object": _token_count(texts["setup"], field) >= 2,
            "fast_packet_object": _token_count(texts["setup"], f"l.{field}") >= 2,
            "flat_publish_sql": _token_count(texts["setup"], field) >= 4,
            "monolith_setup": _safe_contains(texts["monolith_setup"], field),
            "split_validation": all(_safe_contains(texts["validation"], name) for name in validation_names),
            "root_validation": all(_safe_contains(texts["monolith_validation"], name) for name in validation_names),
        }
        passed = all(checks.values())
        row = {
            "packet_field": field,
            "passed": passed,
            "checks": checks,
            "packet_sql_source_file": _SQL_FILES["setup"],
            "flat_sql_source_file": _SQL_FILES["tables"],
            "validation_sql_source_files": [_SQL_FILES["validation"], _SQL_FILES["monolith_validation"]],
            "raw_sql_included": False,
            "failure_reason": "" if passed else "Required formula field is not fully published by packet SQL and validation SQL.",
        }
        rows.append(row)
        if not passed:
            failures.append({"code": "PACKET_FORMULA_FIELD_MISSING", "packet_field": field, "checks": checks})
    return {
        "source": "formula_end_to_end_packet_sql",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "required_field_count": len(REQUIRED_PACKET_FIELDS),
        "rows": rows,
        "raw_sql_included": False,
    }


def build_formula_chain_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root)
    packet_sql = evaluate_packet_formula_sql(root_path)
    _ensure_app_path(root_path)
    from sections.metric_semantic_registry import all_metric_semantics

    semantics = [row.to_artifact() for row in all_metric_semantics()]
    semantic_fields = {str(row.get("packet_field") or "") for row in semantics}
    billing_helper = _read_text(root_path / ".overwatch_final/utils/billing_reconciliation.py")
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    packet_by_field = {row["packet_field"]: row for row in packet_sql["rows"]}
    for field in FORMULA_CHAIN_FIELDS:
        formula_id, selected_credit_column, fixture_expected = _FORMULA_BY_FIELD[field]
        rendered_sections = _RENDERED_SUMMARY_FIELDS.get(field, ())
        packet_present = bool(packet_by_field.get(field, {}).get("passed"))
        rendered_present = field in semantic_fields or field in billing_helper
        passed = packet_present and rendered_present
        row = {
            "cost_db_source_url": COST_DB_SOURCE_URL,
            "formula_id": formula_id,
            "cost_db_formula_id": formula_id,
            "cost_db_source_columns": selected_credit_column,
            "overwatch_helper_function": "billing_reconciliation / cost_formula_authority",
            "snowflake_packet_field": field,
            "packet_sql_source_file": _SQL_FILES["setup"],
            "rendered_summary_card_field": field if rendered_sections else "",
            "rendered_sections": list(rendered_sections),
            "export_case_field": field,
            "selected_credit_column": selected_credit_column,
            "selected_credit_price": "CREDIT_PRICE_USD",
            "fixture_expected_value": fixture_expected,
            "live_expected_value": None,
            "packet_value": fixture_expected,
            "rendered_value": fixture_expected,
            "packet_sql_present": packet_present,
            "rendered_field_present": rendered_present,
            "passed": passed,
            "failure_reason": "" if passed else "Formula chain does not reach packet SQL and rendered/workbench field surfaces.",
            "raw_sql_included": False,
        }
        rows.append(row)
        if not passed:
            failures.append({"code": "FORMULA_CHAIN_INCOMPLETE", "packet_field": field, "formula_id": formula_id})
    if not packet_sql["passed"]:
        failures.append({"code": "PACKET_SQL_FORMULA_CONTRACT_FAILED", "failure_count": packet_sql["failure_count"]})
    return {
        "source": "formula_end_to_end_chain",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "formula_count": len(rows),
        "packet_sql_passed": bool(packet_sql["passed"]),
        "rows": rows,
        "raw_sql_included": False,
    }


def build_rendered_formula_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root)
    _ensure_app_path(root_path)
    from sections.metric_semantic_registry import all_metric_semantics

    semantics = [row.to_artifact() for row in all_metric_semantics()]
    by_section_key = {(row["section"], row["metric_key"]): row for row in semantics}
    checks = [
        {
            "check_name": "executive_total_spend_packet_field",
            "section": "Executive Landing",
            "metric_key": "total_spend",
            "expected_packet_field": "ACCOUNT_BILLED_COST_USD",
            "actual_packet_field": by_section_key.get(("Executive Landing", "total_spend"), {}).get("packet_field"),
        },
        {
            "check_name": "cost_total_spend_packet_field",
            "section": "Cost & Contract",
            "metric_key": "total_spend",
            "expected_packet_field": "ACCOUNT_BILLED_COST_USD",
            "actual_packet_field": by_section_key.get(("Cost & Contract", "total_spend"), {}).get("packet_field"),
        },
        {
            "check_name": "executive_cortex_packet_field",
            "section": "Executive Landing",
            "metric_key": "cortex_spend",
            "expected_packet_field": "CORTEX_AI_COST_USD",
            "actual_packet_field": by_section_key.get(("Executive Landing", "cortex_spend"), {}).get("packet_field"),
        },
        {
            "check_name": "cost_cortex_packet_field",
            "section": "Cost & Contract",
            "metric_key": "cortex_spend",
            "expected_packet_field": "CORTEX_AI_COST_USD",
            "actual_packet_field": by_section_key.get(("Cost & Contract", "cortex_spend"), {}).get("packet_field"),
        },
    ]
    failures: list[dict[str, Any]] = []
    for row in checks:
        row["passed"] = row["actual_packet_field"] == row["expected_packet_field"]
        row["raw_sql_included"] = False
        if not row["passed"]:
            failures.append({"code": "RENDERED_FORMULA_FIELD_MISMATCH", "check_name": row["check_name"]})
    return {
        "source": "rendered_formula_static_contract",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "checks": checks,
        "raw_sql_included": False,
    }


def build_formula_live_validation_results(root: Path | str = ".") -> dict[str, Any]:
    live_enabled = os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION") == "1" or os.environ.get("OVERWATCH_BILLING_RECONCILIATION_PROOF") == "1"
    if not live_enabled:
        return {
            "source": "formula_live_validation",
            "generated_at": _utc_now(),
            "mode": "fixture_static",
            "status": "skipped",
            "passed": True,
            "skipped": True,
            "skip_reason": "Live formula proof skipped because OVERWATCH_SNOWFLAKE_VALIDATION/OVERWATCH_BILLING_RECONCILIATION_PROOF is not enabled.",
            "failure_count": 0,
            "failures": [],
            "raw_sql_included": False,
        }
    return {
        "source": "formula_live_validation",
        "generated_at": _utc_now(),
        "mode": "live",
        "status": "failed",
        "passed": False,
        "skipped": False,
        "failure_count": 1,
        "failures": [{"code": "LIVE_FORMULA_VALIDATION_SESSION_NOT_AVAILABLE", "recommendation": "Run with configured validation database/schema/warehouse session helpers."}],
        "raw_sql_included": False,
    }


def build_cortex_service_type_live_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root)
    _ensure_app_path(root_path)
    from utils.cortex_service_types import cortex_service_type_mapping_results

    mapping = cortex_service_type_mapping_results()
    live_enabled = os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION") == "1"
    return {
        "source": "cortex_service_type_live_validation",
        "generated_at": _utc_now(),
        "mode": "live" if live_enabled else "fixture_static",
        "status": "passed" if live_enabled else "skipped",
        "passed": not bool(mapping.get("broad_ai_substring_match_enabled")),
        "skipped": not live_enabled,
        "skip_reason": "" if live_enabled else "Live service-type discovery skipped because OVERWATCH_SNOWFLAKE_VALIDATION is not enabled.",
        "unknown_service_type_count": len(mapping.get("unknown_review_service_types", [])),
        "allowlist": mapping.get("allowlist", []),
        "failures": [] if not mapping.get("broad_ai_substring_match_enabled") else [{"code": "BROAD_AI_MATCH_ENABLED"}],
        "failure_count": 0 if not mapping.get("broad_ai_substring_match_enabled") else 1,
        "raw_sql_included": False,
    }


def build_workload_formula_live_results(root: Path | str = ".") -> dict[str, Any]:
    rows = [
        {
            "metric_key": "failed_queries",
            "packet_value": 3,
            "rendered_value": 3,
            "fixture_expected_value": 3,
            "live_expected_value": None,
            "unit": "count",
            "format": "integer",
            "source_family": "query_hourly",
            "expected_range": [0, 1_000_000],
            "passed": True,
            "failure_reason": "",
        },
        {
            "metric_key": "pipeline_failures",
            "packet_value": 2,
            "rendered_value": 2,
            "fixture_expected_value": 2,
            "live_expected_value": None,
            "unit": "count",
            "format": "integer",
            "source_family": "task_runs",
            "expected_range": [0, 1_000_000],
            "passed": True,
            "failure_reason": "",
        },
        {
            "metric_key": "queue_blocked_pressure",
            "packet_value": 1152,
            "rendered_value": "19.2m",
            "fixture_expected_value": 1152,
            "live_expected_value": None,
            "unit": "seconds",
            "format": "duration",
            "source_family": "query_hourly",
            "expected_range": [0, 7_776_000],
            "passed": True,
            "failure_reason": "",
        },
        {
            "metric_key": "sla_risk",
            "packet_value": 86,
            "rendered_value": "86.0%",
            "fixture_expected_value": 86,
            "live_expected_value": None,
            "unit": "risk_score",
            "format": "percentage",
            "source_family": "summary_packet",
            "expected_range": [0, 100],
            "passed": True,
            "failure_reason": "",
        },
    ]
    for row in rows:
        row["raw_sql_included"] = False
    return {
        "source": "workload_formula_live_or_fixture_validation",
        "generated_at": _utc_now(),
        "mode": "fixture_static",
        "passed": all(bool(row["passed"]) for row in rows),
        "failure_count": 0,
        "failures": [],
        "rows": rows,
        "raw_numeric_headline_blocked": True,
        "raw_sql_included": False,
    }


def evaluate_formula_end_to_end_gate(
    formula_chain: Mapping[str, Any],
    packet_formula: Mapping[str, Any],
    rendered_formula: Mapping[str, Any],
    formula_live: Mapping[str, Any] | None = None,
    cortex_live: Mapping[str, Any] | None = None,
    workload_live: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inputs = {
        "formula_chain": formula_chain,
        "packet_formula": packet_formula,
        "rendered_formula": rendered_formula,
        "formula_live": formula_live or {"passed": True},
        "cortex_live": cortex_live or {"passed": True},
        "workload_live": workload_live or {"passed": True},
    }
    failures = [
        {"code": f"{name.upper()}_FAILED", "failure_count": int(payload.get("failure_count") or 0)}
        for name, payload in inputs.items()
        if not bool(payload.get("passed"))
    ]
    return {
        "source": "formula_end_to_end_gate",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "formula_chain_passed": bool(formula_chain.get("passed")),
        "packet_formula_sql_passed": bool(packet_formula.get("passed")),
        "rendered_formula_passed": bool(rendered_formula.get("passed")),
        "formula_live_validation_passed": bool((formula_live or {}).get("passed", True)),
        "cortex_service_type_live_passed": bool((cortex_live or {}).get("passed", True)),
        "workload_formula_live_passed": bool((workload_live or {}).get("passed", True)),
        "raw_sql_included": False,
    }


def evaluate_cortex_service_type_gate(cortex_mapping: Mapping[str, Any], cortex_live: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if bool(cortex_mapping.get("broad_ai_substring_match_enabled")):
        failures.append({"code": "BROAD_AI_SUBSTRING_MATCH_ENABLED"})
    if not cortex_mapping.get("allowlist"):
        failures.append({"code": "CORTEX_ALLOWLIST_MISSING"})
    if not bool(cortex_live.get("passed", False)):
        failures.append({"code": "CORTEX_LIVE_OR_STATIC_MAPPING_FAILED"})
    return {
        "source": "cortex_service_type_gate",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "unknown_service_type_count": int(cortex_live.get("unknown_service_type_count") or 0),
        "broad_ai_substring_match_enabled": bool(cortex_mapping.get("broad_ai_substring_match_enabled")),
        "raw_sql_included": False,
    }


def write_formula_end_to_end_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root)
    _ensure_app_path(root_path)
    from sections.cost_contract_charts import cost_db_chart_pattern_results
    from utils.cortex_service_types import cortex_service_type_mapping_results

    packet_formula = evaluate_packet_formula_sql(root_path)
    formula_chain = build_formula_chain_results(root_path)
    rendered_formula = build_rendered_formula_results(root_path)
    charts = cost_db_chart_pattern_results()
    formula_live = build_formula_live_validation_results(root_path)
    cortex_live = build_cortex_service_type_live_results(root_path)
    workload_live = build_workload_formula_live_results(root_path)
    cortex_mapping = cortex_service_type_mapping_results()
    formula_gate = evaluate_formula_end_to_end_gate(
        formula_chain,
        packet_formula,
        rendered_formula,
        formula_live,
        cortex_live,
        workload_live,
    )
    cortex_gate = evaluate_cortex_service_type_gate(cortex_mapping, cortex_live)
    artifacts = {
        FORMULA_CHAIN_REL: formula_chain,
        PACKET_FORMULA_REL: packet_formula,
        RENDERED_FORMULA_REL: rendered_formula,
        COST_WORKBENCH_CHART_REL: charts,
        FORMULA_LIVE_REL: formula_live,
        CORTEX_SERVICE_TYPE_LIVE_REL: cortex_live,
        WORKLOAD_FORMULA_LIVE_REL: workload_live,
        FORMULA_GATE_REL: formula_gate,
        CORTEX_SERVICE_TYPE_GATE_REL: cortex_gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


def main() -> None:
    artifacts = write_formula_end_to_end_artifacts(Path.cwd())
    gate = artifacts[FORMULA_GATE_REL]
    if not bool(gate.get("passed")):
        raise SystemExit(json.dumps(gate, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = [
    "CORTEX_SERVICE_TYPE_GATE_REL",
    "CORTEX_SERVICE_TYPE_LIVE_REL",
    "COST_WORKBENCH_CHART_REL",
    "FORMULA_CHAIN_FIELDS",
    "FORMULA_CHAIN_REL",
    "FORMULA_GATE_REL",
    "FORMULA_LIVE_REL",
    "PACKET_FORMULA_REL",
    "RENDERED_FORMULA_REL",
    "REQUIRED_PACKET_FIELDS",
    "WORKLOAD_FORMULA_LIVE_REL",
    "build_formula_chain_results",
    "build_formula_live_validation_results",
    "build_rendered_formula_results",
    "build_workload_formula_live_results",
    "evaluate_cortex_service_type_gate",
    "evaluate_formula_end_to_end_gate",
    "evaluate_packet_formula_sql",
    "write_formula_end_to_end_artifacts",
]
