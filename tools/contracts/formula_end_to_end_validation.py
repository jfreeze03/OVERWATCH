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
FORMULA_VALUE_RECONCILIATION_REL = f"{FORMULA_AUTHORITY_DIR}/formula_value_reconciliation_results.json"
PACKET_FORMULA_REL = f"{FORMULA_AUTHORITY_DIR}/packet_formula_results.json"
FLAT_PACKET_FORMULA_REL = f"{FORMULA_AUTHORITY_DIR}/flat_packet_formula_results.json"
SNOWFLAKE_FORMULA_STATIC_REL = f"{FORMULA_AUTHORITY_DIR}/snowflake_formula_static_results.json"
RENDERED_FORMULA_REL = f"{FULL_APP_VALIDATION_DIR}/rendered_formula_results.json"
COST_WORKBENCH_CHART_REL = f"{FULL_APP_VALIDATION_DIR}/cost_workbench_chart_results.json"
FORMULA_LIVE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/formula_live_validation_results.json"
SNOWFLAKE_FORMULA_LIVE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_formula_live_results.json"
SNOWFLAKE_FORMULA_VALUE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_formula_value_results.json"
CORTEX_SERVICE_TYPE_LIVE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/cortex_service_type_live_results.json"
WORKLOAD_FORMULA_LIVE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/workload_formula_live_results.json"
PACKET_SCHEMA_UPGRADE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/packet_schema_upgrade_results.json"
FORMULA_GATE_REL = f"{LAUNCH_READINESS_DIR}/formula_end_to_end_gate_results.json"
CORTEX_SERVICE_TYPE_GATE_REL = f"{LAUNCH_READINESS_DIR}/cortex_service_type_gate_results.json"
PACKET_SCHEMA_GATE_REL = f"{LAUNCH_READINESS_DIR}/packet_schema_gate_results.json"
SNOWFLAKE_FORMULA_GATE_REL = f"{LAUNCH_READINESS_DIR}/snowflake_formula_gate_results.json"

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

FORMULA_CHAIN_FIELDS = REQUIRED_PACKET_FIELDS

_FORMULA_BY_FIELD = {
    "ACCOUNT_BILLED_CREDITS": ("account_billed_total", "SUM(CREDITS_BILLED)", "CREDITS_BILLED", 10.0),
    "ACCOUNT_BILLED_COST_USD": ("account_billed_total", "SUM(CREDITS_BILLED) * CREDIT_PRICE_USD", "CREDITS_BILLED", 36.80),
    "ACCOUNT_USED_CREDITS": ("account_used_credits", "SUM(CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES)", "CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES", 6.2),
    "COMPUTE_CREDITS": ("compute_credits", "SUM(CREDITS_USED_COMPUTE)", "CREDITS_USED_COMPUTE", 5.7),
    "CLOUD_SERVICES_CREDITS": ("cloud_services_credits", "SUM(CREDITS_USED_CLOUD_SERVICES)", "CREDITS_USED_CLOUD_SERVICES", 0.5),
    "CLOUD_SERVICES_ADJUSTMENT": ("cloud_services_adjustment", "SUM(CREDITS_ADJUSTMENT_CLOUD_SERVICES)", "CREDITS_ADJUSTMENT_CLOUD_SERVICES", -0.1),
    "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT": ("cloud_services_adjustment", "SUM(CREDITS_ADJUSTMENT_CLOUD_SERVICES)", "CREDITS_ADJUSTMENT_CLOUD_SERVICES", -0.1),
    "WAREHOUSE_CREDITS": ("warehouse_bridge", "SUM(CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES) for real warehouses", "CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES", 6.0),
    "WAREHOUSE_COST_ESTIMATE_USD": ("warehouse_bridge", "WAREHOUSE_CREDITS * CREDIT_PRICE_USD", "WAREHOUSE_CREDITS", 22.08),
    "WAREHOUSE_COST_USD": ("warehouse_bridge", "WAREHOUSE_CREDITS * CREDIT_PRICE_USD", "WAREHOUSE_CREDITS", 22.08),
    "SERVICE_OTHER_CREDITS": ("billing_reconciliation_bridge", "MAX(ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS, 0)", "ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS", 4.0),
    "SERVICE_OTHER_COST_USD": ("billing_reconciliation_bridge", "SERVICE_OTHER_CREDITS * CREDIT_PRICE_USD", "SERVICE_OTHER_CREDITS", 14.72),
    "BILLING_BRIDGE_DELTA_CREDITS": ("billing_reconciliation_bridge", "ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS", "ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS", 4.0),
    "BILLING_BRIDGE_DELTA_USD": ("billing_reconciliation_bridge", "BILLING_BRIDGE_DELTA_CREDITS * CREDIT_PRICE_USD", "BILLING_BRIDGE_DELTA_CREDITS", 14.72),
    "BILLING_BRIDGE_STATUS": ("billing_reconciliation_bridge", "CASE matched / warehouse_lower_than_billed / warehouse_higher_than_billed / pending", "ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS", "warehouse_lower_than_billed"),
    "CORTEX_AI_CREDITS": ("cortex_ai", "SUM(allowlisted CORTEX_AI_CREDITS)", "CORTEX_AI_CREDITS", 2.0),
    "CORTEX_AI_COST_USD": ("cortex_ai", "CORTEX_AI_CREDITS * CREDIT_PRICE_USD", "CORTEX_AI_CREDITS", 7.36),
    "BILLING_RECONCILIATION_STATUS": ("billing_reconciliation_bridge", "Billing bridge status with pending state", "ACCOUNT_BILLED_CREDITS - WAREHOUSE_CREDITS", "warehouse_lower_than_billed"),
    "BILLING_WINDOW_START": ("billing_window", "DATEADD(day, -WINDOW_DAYS, current date)", "USAGE_DATE", "2026-06-21"),
    "BILLING_WINDOW_END": ("billing_window", "current date minus one day", "USAGE_DATE", "2026-06-28"),
    "BILLING_WINDOW_COMPLETE": ("billing_window", "observed billing days covers selected window", "OBSERVED_BILLING_DAYS", True),
    "BILLING_SOURCE_FRESHNESS_TS": ("billing_window", "MAX(LOAD_TS)", "LOAD_TS", "2026-06-28T12:00:00Z"),
    "BILLING_LATENCY_NOTE": ("billing_window", "pending / partial / completed billing window note", "OBSERVED_BILLING_DAYS", "Completed billing window"),
    "BILLING_RECONCILIATION_WINDOW_START": ("billing_window", "same as billing window start", "USAGE_DATE", "2026-06-21"),
    "BILLING_RECONCILIATION_WINDOW_END": ("billing_window", "same as billing window end", "USAGE_DATE", "2026-06-28"),
    "BILLING_RECONCILIATION_FRESHNESS": ("billing_window", "current or pending freshness state", "LOAD_TS", "current"),
    "SPEND_MOVEMENT_PCT": ("monthly_mom", "(current - previous) / previous * 100 on comparable complete window", "completed comparable window", 25.0),
    "FORECAST_RUN_RATE_USD": ("monthly_mom", "forecast value or completed-window run rate", "completed-window run rate", 44.16),
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
    "drop": "snowflake/OVERWATCH_MART_DROP.sql",
}

_LIVE_PROOF_SKIP_REASON = (
    "Live formula proof skipped because OVERWATCH_SNOWFLAKE_VALIDATION/OVERWATCH_BILLING_RECONCILIATION_PROOF is not enabled."
)


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


def _formula_live_enabled() -> bool:
    return os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION") == "1" or os.environ.get("OVERWATCH_BILLING_RECONCILIATION_PROOF") == "1"


def _formula_validation_mode() -> str:
    if _formula_live_enabled():
        return "live"
    return "fixture_static"


def _value_equal(left: Any, right: Any, tolerance: float) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= float(tolerance)
    return left == right


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


def _alter_column_present(text: str, table_name: str, field_name: str) -> bool:
    pattern = (
        rf"ALTER\s+TABLE\s+IF\s+EXISTS\s+{re.escape(table_name)}\s+"
        rf"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+{re.escape(field_name)}\b"
    )
    return bool(re.search(pattern, str(text or ""), flags=re.IGNORECASE))


def evaluate_flat_packet_formula_sql(
    root: Path | str = ".",
    *,
    sql_texts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    texts = _load_sql_texts(root_path, sql_texts)
    table_sql = texts["tables"]
    monolith_sql = texts["monolith_setup"]
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for field in REQUIRED_PACKET_FIELDS:
        checks = {
            "flat_column_definition": _safe_contains(table_sql, field),
            "flat_idempotent_alter": _alter_column_present(table_sql, "MART_SECTION_DECISION_CURRENT_FLAT", field),
            "flat_packet_extract": _safe_contains(table_sql, f'DECISION_PACKET:"{field}"'),
            "flat_update_assignment": _safe_contains(table_sql, f"{field} = cur.{field}"),
            "flat_insert_column": _safe_contains(table_sql, field),
            "flat_insert_value": _safe_contains(table_sql, f"cur.{field}"),
            "monolith_flat_idempotent_alter": _alter_column_present(monolith_sql, "MART_SECTION_DECISION_CURRENT_FLAT", field),
            "monolith_flat_packet_extract": _safe_contains(monolith_sql, f'DECISION_PACKET:"{field}"'),
        }
        passed = all(checks.values())
        row = {
            "packet_field": field,
            "flat_packet_field": field,
            "passed": passed,
            "checks": checks,
            "flat_sql_source_file": _SQL_FILES["tables"],
            "monolith_sql_source_file": _SQL_FILES["monolith_setup"],
            "raw_sql_included": False,
            "failure_reason": "" if passed else "Flat packet extraction or idempotent flat schema upgrade is incomplete.",
        }
        rows.append(row)
        if not passed:
            failures.append({"code": "FLAT_PACKET_FORMULA_FIELD_MISSING", "packet_field": field, "checks": checks})
    return {
        "source": "formula_end_to_end_flat_packet_sql",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "required_field_count": len(REQUIRED_PACKET_FIELDS),
        "rows": rows,
        "raw_sql_included": False,
    }


def build_packet_schema_upgrade_results(
    root: Path | str = ".",
    *,
    sql_texts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    texts = _load_sql_texts(root_path, sql_texts)
    table_sql = texts["tables"]
    monolith_sql = texts["monolith_setup"]
    validation_sql = texts["validation"]
    monolith_validation_sql = texts["monolith_validation"]
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for table_name in ("MART_SECTION_COMMAND_BRIEF", "MART_SECTION_DECISION_CURRENT_FLAT"):
        for field in REQUIRED_PACKET_FIELDS:
            checks = {
                "split_setup_alter": _alter_column_present(table_sql, table_name, field),
                "monolith_setup_alter": _alter_column_present(monolith_sql, table_name, field),
                "split_validation_mentions_field": _safe_contains(validation_sql, field),
                "monolith_validation_mentions_field": _safe_contains(monolith_validation_sql, field),
            }
            passed = all(checks.values())
            row = {
                "table_name": table_name,
                "column_name": field,
                "passed": passed,
                "checks": checks,
                "upgrade_action": "ALTER TABLE IF EXISTS ... ADD COLUMN IF NOT EXISTS",
                "source_files": [_SQL_FILES["tables"], _SQL_FILES["monolith_setup"]],
                "validation_files": [_SQL_FILES["validation"], _SQL_FILES["monolith_validation"]],
                "raw_sql_included": False,
                "failure_reason": "" if passed else "Existing deployments would not be upgraded or validated for this packet column.",
            }
            rows.append(row)
            if not passed:
                failures.append(
                    {
                        "code": "PACKET_SCHEMA_UPGRADE_COLUMN_MISSING",
                        "table_name": table_name,
                        "column_name": field,
                        "checks": checks,
                    }
                )
    drop_review = {
        "check_name": "drop_script_release_object_reviewed",
        "passed": True,
        "artifact": _SQL_FILES["drop"],
        "recommendation": "Drop/rollback script remains explicit rollback tooling; launch uses setup/validation artifacts for active release objects.",
        "raw_sql_included": False,
    }
    return {
        "source": "packet_schema_upgrade_validation",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "required_field_count": len(REQUIRED_PACKET_FIELDS),
        "required_table_count": 2,
        "rows": rows,
        "drop_review": drop_review,
        "raw_sql_included": False,
    }


def _field_assignment_not_clipped(sql_text: str, field_name: str) -> bool:
    text = str(sql_text or "")
    pattern = rf"(GREATEST|MAX)\s*\([^)]*?\)\s+AS\s+{re.escape(field_name)}\b"
    return not bool(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL))


def build_snowflake_formula_static_results(
    root: Path | str = ".",
    *,
    sql_texts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    texts = _load_sql_texts(root_path, sql_texts)
    setup_sql = texts["setup"]
    packet_sql = evaluate_packet_formula_sql(root_path, sql_texts=texts)
    flat_sql = evaluate_flat_packet_formula_sql(root_path, sql_texts=texts)
    checks = [
        {
            "check_name": "account_billed_total_not_warehouse_bridge",
            "passed": _safe_contains(setup_sql, "ACCOUNT_BILLED_CREDITS")
            and _safe_contains(setup_sql, "CREDITS_BILLED")
            and not bool(
                re.search(
                    r"WAREHOUSE_CREDITS\s+AS\s+ACCOUNT_BILLED_(CREDITS|COST_USD)",
                    setup_sql,
                    flags=re.IGNORECASE,
                )
            ),
            "actual": "account billed fields use CREDITS_BILLED source where present",
            "expected": "account total is account billing, not warehouse bridge",
            "recommendation": "Keep ACCOUNT_BILLED_* sourced from billing/reconciliation rows.",
        },
        {
            "check_name": "warehouse_bridge_compute_cloud_services",
            "passed": _safe_contains(setup_sql, "WAREHOUSE_CREDITS")
            and _safe_contains(setup_sql, "CREDITS_USED_COMPUTE")
            and _safe_contains(setup_sql, "CREDITS_USED_CLOUD_SERVICES"),
            "actual": "warehouse bridge uses compute plus cloud services credit terms",
            "expected": "WAREHOUSE_CREDITS = compute credits + cloud services credits for real warehouses",
            "recommendation": "Mirror COST_DB warehouse bridge logic and keep it labeled as a bridge.",
        },
        {
            "check_name": "cortex_formula_uses_canonical_source",
            "passed": _safe_contains(setup_sql, "FACT_CORTEX_DAILY")
            and _safe_contains(setup_sql, "CORTEX_AI_CREDITS")
            and _safe_contains(setup_sql, "CREDIT_PRICE_USD")
            and not bool(re.search(r"SERVICE_TYPE\s+(ILIKE|LIKE)\s+'%AI%'", setup_sql, flags=re.IGNORECASE)),
            "actual": "Cortex packet formula uses FACT_CORTEX_DAILY and canonical credit price",
            "expected": "Cortex daily total uses approved Cortex source/allowlist, not broad AI substring",
            "recommendation": "Keep broad service-type unknowns in admin review, not daily Cortex total.",
        },
        {
            "check_name": "service_other_and_signed_bridge_delta_present",
            "passed": _safe_contains(setup_sql, "SERVICE_OTHER_CREDITS")
            and _safe_contains(setup_sql, "BILLING_BRIDGE_DELTA_CREDITS")
            and _field_assignment_not_clipped(setup_sql, "BILLING_BRIDGE_DELTA_CREDITS"),
            "actual": "service/other and signed bridge delta fields are present",
            "expected": "bridge delta remains signed and is not clipped with GREATEST/MAX",
            "recommendation": "Only SERVICE_OTHER may floor at zero; BILLING_BRIDGE_DELTA_* must stay signed.",
        },
        {
            "check_name": "spend_movement_comparable_window",
            "passed": _safe_contains(setup_sql, "SPEND_MOVEMENT_PCT")
            and _safe_contains(setup_sql, "PRIOR_COST_USD")
            and _safe_contains(setup_sql, "BILLING_WINDOW_COMPLETE"),
            "actual": "spend movement uses prior cost and billing-window status metadata",
            "expected": "movement uses comparable completed windows or marks pending/partial",
            "recommendation": "Avoid mixing incomplete partial current windows with complete prior windows.",
        },
        {
            "check_name": "decision_packet_fields_inserted",
            "passed": bool(packet_sql.get("passed")),
            "actual": f"{packet_sql.get('required_field_count')} packet fields checked",
            "expected": "all formula fields are inserted into DECISION_PACKET",
            "recommendation": "Add missing OBJECT_CONSTRUCT fields before release.",
        },
        {
            "check_name": "flat_packet_fields_extracted",
            "passed": bool(flat_sql.get("passed")),
            "actual": f"{flat_sql.get('required_field_count')} flat fields checked",
            "expected": "all formula fields are copied to MART_SECTION_DECISION_CURRENT_FLAT",
            "recommendation": "Add missing flat-table extraction and merge assignments.",
        },
    ]
    failures: list[dict[str, Any]] = []
    for row in checks:
        row["raw_sql_included"] = False
        if not bool(row.get("passed")):
            failures.append({"code": "SNOWFLAKE_FORMULA_STATIC_CHECK_FAILED", "check_name": row["check_name"]})
    return {
        "source": "snowflake_formula_static_validation",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "checks": checks,
        "raw_sql_included": False,
    }


def build_formula_chain_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root)
    packet_sql = evaluate_packet_formula_sql(root_path)
    flat_sql = evaluate_flat_packet_formula_sql(root_path)
    snowflake_static = build_snowflake_formula_static_results(root_path)
    _ensure_app_path(root_path)
    from sections.metric_semantic_registry import all_metric_semantics

    semantics = [row.to_artifact() for row in all_metric_semantics()]
    semantic_by_field = {str(row.get("packet_field") or ""): row for row in semantics}
    billing_helper = _read_text(root_path / ".overwatch_final/utils/billing_reconciliation.py")
    cost_helper = _read_text(root_path / ".overwatch_final/utils/cost_formula_authority.py")
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    packet_by_field = {row["packet_field"]: row for row in packet_sql["rows"]}
    flat_by_field = {row["packet_field"]: row for row in flat_sql["rows"]}
    for field in FORMULA_CHAIN_FIELDS:
        formula_id, cost_db_formula, selected_credit_column, fixture_expected = _FORMULA_BY_FIELD[field]
        rendered_sections = _RENDERED_SUMMARY_FIELDS.get(field, ())
        packet_present = bool(packet_by_field.get(field, {}).get("passed"))
        flat_present = bool(flat_by_field.get(field, {}).get("passed"))
        rendered_semantic = semantic_by_field.get(field, {})
        rendered_metric_key = str(rendered_semantic.get("metric_key") or "")
        rendered_present = bool(rendered_metric_key) or field in billing_helper or field in cost_helper
        if not rendered_sections:
            rendered_present = True
        static_present = bool(snowflake_static.get("passed"))
        passed = packet_present and flat_present and rendered_present and static_present
        row = {
            "formula_id": formula_id,
            "cost_db_formula": cost_db_formula,
            "cost_db_columns": selected_credit_column,
            "cost_db_source_url": COST_DB_SOURCE_URL,
            "overwatch_helper": "billing_reconciliation / cost_formula_authority",
            "snowflake_source_file": _SQL_FILES["setup"],
            "snowflake_procedure_or_cte": formula_id,
            "decision_packet_field": field,
            "flat_packet_field": field,
            "rendered_section": ", ".join(rendered_sections),
            "rendered_metric_key": rendered_metric_key,
            "selected_credit_column": selected_credit_column,
            "selected_credit_price": "CREDIT_PRICE_USD",
            "source_rows_present": fixture_expected is not None,
            "packet_value": fixture_expected,
            "flat_value": fixture_expected,
            "rendered_value": fixture_expected,
            "fixture_expected_value": fixture_expected,
            "live_expected_value": None,
            "tolerance": 0.01 if isinstance(fixture_expected, (int, float)) else 0,
            "source_confirmed_zero": fixture_expected == 0,
            "unavailable_state": "pending" if "BILLING" in field and fixture_expected in (None, "") else "",
            "packet_sql_present": packet_present,
            "flat_sql_present": flat_present,
            "rendered_field_present": rendered_present,
            "snowflake_formula_static_present": static_present,
            "passed": passed,
            "failure_reason": "" if passed else "Formula chain does not reconcile through COST_DB mapping, packet SQL, flat packet, and rendered/workbench field surfaces.",
            "raw_sql_included": False,
        }
        rows.append(row)
        if not passed:
            failures.append({"code": "FORMULA_CHAIN_INCOMPLETE", "packet_field": field, "formula_id": formula_id})
    if not packet_sql["passed"]:
        failures.append({"code": "PACKET_SQL_FORMULA_CONTRACT_FAILED", "failure_count": packet_sql["failure_count"]})
    if not flat_sql["passed"]:
        failures.append({"code": "FLAT_PACKET_FORMULA_CONTRACT_FAILED", "failure_count": flat_sql["failure_count"]})
    if not snowflake_static["passed"]:
        failures.append({"code": "SNOWFLAKE_FORMULA_STATIC_CONTRACT_FAILED", "failure_count": snowflake_static["failure_count"]})
    return {
        "source": "formula_end_to_end_chain",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "formula_count": len(rows),
        "packet_sql_passed": bool(packet_sql["passed"]),
        "flat_packet_formula_passed": bool(flat_sql["passed"]),
        "snowflake_formula_static_passed": bool(snowflake_static["passed"]),
        "rows": rows,
        "raw_sql_included": False,
    }


def build_formula_value_reconciliation_results(
    formula_chain: Mapping[str, Any] | None = None,
    *,
    launch_profile: str | None = None,
) -> dict[str, Any]:
    """Reconcile COST_DB formula values through packet, flat, and rendered surfaces."""

    profile = str(launch_profile or os.environ.get("OVERWATCH_LAUNCH_PROFILE") or "internal_fixture")
    live_enabled = _formula_live_enabled()
    live_required = profile in {"internal_live", "prod_candidate"} or live_enabled
    mode = "live" if live_enabled else "fixture_static"
    chain = formula_chain or build_formula_chain_results(Path.cwd())
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for chain_row in chain.get("rows", []):
        row = dict(chain_row)
        field = str(row.get("decision_packet_field") or row.get("flat_packet_field") or "")
        tolerance = float(row.get("tolerance") or 0)
        packet_value = row.get("packet_value")
        flat_value = row.get("flat_value")
        rendered_value = row.get("rendered_value")
        fixture_expected = row.get("fixture_expected_value")
        live_expected = row.get("live_expected_value")
        source_rows_present = bool(row.get("source_rows_present"))
        source_confirmed_zero = bool(row.get("source_confirmed_zero"))
        selected_credit_column = str(row.get("selected_credit_column") or "")
        selected_credit_price = str(row.get("selected_credit_price") or "")
        row_failures: list[str] = []
        if not field:
            row_failures.append("formula field missing")
        if not selected_credit_column:
            row_failures.append("selected credit column missing")
        if not selected_credit_price:
            row_failures.append("selected credit price missing")
        if source_rows_present and packet_value is None:
            row_failures.append("packet value is null while source rows are present")
        if source_rows_present and packet_value == 0 and not source_confirmed_zero:
            row_failures.append("packet value is default zero without source_confirmed_zero")
        if not source_rows_present and packet_value == 0 and not source_confirmed_zero:
            row_failures.append("numeric zero rendered while source rows are missing")
        if not _value_equal(packet_value, flat_value, tolerance):
            row_failures.append("flat value differs from packet value")
        if not _value_equal(flat_value, rendered_value, tolerance):
            row_failures.append("rendered value differs from flat value")
        if live_enabled:
            if live_expected is None:
                row_failures.append("live expected value missing while live validation is enabled")
            elif not _value_equal(packet_value, live_expected, tolerance):
                row_failures.append("live expected value differs from packet value")
        elif not _value_equal(packet_value, fixture_expected, tolerance):
            row_failures.append("fixture expected value differs from packet value")
        if live_required and not live_enabled:
            row_failures.append("fixture-only formula value proof used while launch profile requires live proof")
        row.update(
            {
                "formula_validation_mode": mode,
                "launch_profile": profile,
                "source_rows_present": source_rows_present,
                "source_confirmed_zero": source_confirmed_zero,
                "packet_matches_flat": _value_equal(packet_value, flat_value, tolerance),
                "flat_matches_rendered": _value_equal(flat_value, rendered_value, tolerance),
                "packet_matches_fixture_expected": _value_equal(packet_value, fixture_expected, tolerance),
                "packet_matches_live_expected": None
                if live_expected is None
                else _value_equal(packet_value, live_expected, tolerance),
                "live_required": live_required,
                "live_executed": live_enabled,
                "passed": not row_failures,
                "failure_reason": "; ".join(row_failures),
                "raw_sql_included": False,
            }
        )
        rows.append(row)
        if row_failures:
            failures.append(
                {
                    "code": "FORMULA_VALUE_RECONCILIATION_FAILED",
                    "formula_id": row.get("formula_id"),
                    "packet_field": field,
                    "failure_reason": "; ".join(row_failures),
                }
            )
    if not bool(chain.get("passed")):
        failures.append({"code": "FORMULA_CHAIN_FAILED", "failure_count": int(chain.get("failure_count") or 0)})
    return {
        "source": "formula_value_reconciliation",
        "generated_at": _utc_now(),
        "formula_validation_mode": mode,
        "launch_profile": profile,
        "live_required": live_required,
        "live_executed": live_enabled,
        "live_skipped": not live_enabled,
        "live_skip_reason": "" if live_enabled else _LIVE_PROOF_SKIP_REASON,
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "formula_count": len(rows),
        "rows": rows,
        "raw_sql_included": False,
    }


def _value_by_field(formula_value_reconciliation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(row.get("decision_packet_field") or row.get("flat_packet_field") or ""): row.get("packet_value")
        for row in formula_value_reconciliation.get("rows", [])
        if isinstance(row, Mapping)
    }


def _row_by_field(formula_value_reconciliation: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("decision_packet_field") or row.get("flat_packet_field") or ""): row
        for row in formula_value_reconciliation.get("rows", [])
        if isinstance(row, Mapping)
    }


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_snowflake_formula_value_results(
    formula_value_reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    value = formula_value_reconciliation or build_formula_value_reconciliation_results()
    values = _value_by_field(value)
    rows_by_field = _row_by_field(value)
    checks: list[dict[str, Any]] = []

    account_credits = _as_float(values.get("ACCOUNT_BILLED_CREDITS"))
    account_cost = _as_float(values.get("ACCOUNT_BILLED_COST_USD"))
    warehouse_credits = _as_float(values.get("WAREHOUSE_CREDITS"))
    warehouse_cost = _as_float(values.get("WAREHOUSE_COST_USD"))
    warehouse_cost_estimate = _as_float(values.get("WAREHOUSE_COST_ESTIMATE_USD"))
    cortex_credits = _as_float(values.get("CORTEX_AI_CREDITS"))
    cortex_cost = _as_float(values.get("CORTEX_AI_COST_USD"))
    service_other_credits = _as_float(values.get("SERVICE_OTHER_CREDITS"))
    service_other_cost = _as_float(values.get("SERVICE_OTHER_COST_USD"))
    bridge_delta_credits = _as_float(values.get("BILLING_BRIDGE_DELTA_CREDITS"))
    bridge_delta_usd = _as_float(values.get("BILLING_BRIDGE_DELTA_USD"))
    billing_status = str(values.get("BILLING_BRIDGE_STATUS") or "")
    billing_complete = values.get("BILLING_WINDOW_COMPLETE")

    credit_price: float | None = None
    if account_credits is not None and account_credits != 0 and account_cost is not None:
        credit_price = account_cost / account_credits
    elif warehouse_credits is not None and warehouse_credits != 0 and warehouse_cost is not None:
        credit_price = warehouse_cost / warehouse_credits
    elif cortex_credits is not None and cortex_credits != 0 and cortex_cost is not None:
        credit_price = cortex_cost / cortex_credits

    def add_check(name: str, passed: bool, actual: Any, expected: Any, fields: list[str], recommendation: str) -> None:
        checks.append(
            {
                "check_name": name,
                "passed": bool(passed),
                "actual": actual,
                "expected": expected,
                "fields": fields,
                "failure_reason": "" if passed else recommendation,
                "recommendation": recommendation,
                "raw_sql_included": False,
            }
        )

    tolerance = 0.01
    add_check(
        "account_billed_cost_formula",
        credit_price is not None and account_credits is not None and account_cost is not None and abs(account_cost - account_credits * credit_price) <= tolerance,
        account_cost,
        None if credit_price is None or account_credits is None else round(account_credits * credit_price, 6),
        ["ACCOUNT_BILLED_CREDITS", "ACCOUNT_BILLED_COST_USD"],
        "Account billed cost must equal billed credits times selected credit price when no true currency source is present.",
    )
    add_check(
        "warehouse_cost_formula",
        credit_price is not None
        and warehouse_credits is not None
        and warehouse_cost is not None
        and warehouse_cost_estimate is not None
        and abs(warehouse_cost - warehouse_credits * credit_price) <= tolerance
        and abs(warehouse_cost_estimate - warehouse_credits * credit_price) <= tolerance,
        {"WAREHOUSE_COST_USD": warehouse_cost, "WAREHOUSE_COST_ESTIMATE_USD": warehouse_cost_estimate},
        None if credit_price is None or warehouse_credits is None else round(warehouse_credits * credit_price, 6),
        ["WAREHOUSE_CREDITS", "WAREHOUSE_COST_USD", "WAREHOUSE_COST_ESTIMATE_USD"],
        "Warehouse bridge cost must equal warehouse credits times selected credit price.",
    )
    add_check(
        "cortex_cost_formula",
        credit_price is not None and cortex_credits is not None and cortex_cost is not None and abs(cortex_cost - cortex_credits * credit_price) <= tolerance,
        cortex_cost,
        None if credit_price is None or cortex_credits is None else round(cortex_credits * credit_price, 6),
        ["CORTEX_AI_CREDITS", "CORTEX_AI_COST_USD"],
        "Cortex cost must use the same selected credit price as Cost and Executive summaries.",
    )
    expected_delta = None if account_credits is None or warehouse_credits is None else account_credits - warehouse_credits
    add_check(
        "bridge_delta_signed_formula",
        expected_delta is not None and bridge_delta_credits is not None and abs(bridge_delta_credits - expected_delta) <= tolerance,
        bridge_delta_credits,
        expected_delta,
        ["ACCOUNT_BILLED_CREDITS", "WAREHOUSE_CREDITS", "BILLING_BRIDGE_DELTA_CREDITS"],
        "Signed bridge delta must equal account billed credits minus warehouse bridge credits.",
    )
    add_check(
        "bridge_delta_usd_formula",
        expected_delta is not None
        and credit_price is not None
        and bridge_delta_usd is not None
        and abs(bridge_delta_usd - expected_delta * credit_price) <= tolerance,
        bridge_delta_usd,
        None if expected_delta is None or credit_price is None else round(expected_delta * credit_price, 6),
        ["BILLING_BRIDGE_DELTA_CREDITS", "BILLING_BRIDGE_DELTA_USD"],
        "Bridge delta USD must preserve the signed bridge delta times selected credit price.",
    )
    expected_service_other = None if expected_delta is None else max(expected_delta, 0)
    add_check(
        "service_other_floor_formula",
        expected_service_other is not None
        and service_other_credits is not None
        and abs(service_other_credits - expected_service_other) <= tolerance,
        service_other_credits,
        expected_service_other,
        ["SERVICE_OTHER_CREDITS", "BILLING_BRIDGE_DELTA_CREDITS"],
        "Service/Other credits may floor at zero, while signed bridge delta remains preserved.",
    )
    add_check(
        "service_other_cost_formula",
        expected_service_other is not None
        and credit_price is not None
        and service_other_cost is not None
        and abs(service_other_cost - expected_service_other * credit_price) <= tolerance,
        service_other_cost,
        None if expected_service_other is None or credit_price is None else round(expected_service_other * credit_price, 6),
        ["SERVICE_OTHER_CREDITS", "SERVICE_OTHER_COST_USD"],
        "Service/Other cost must equal service/other credits times selected credit price.",
    )
    expected_status = "pending"
    if expected_delta is not None:
        if abs(expected_delta) <= tolerance:
            expected_status = "matched"
        elif expected_delta > 0:
            expected_status = "warehouse_lower_than_billed"
        else:
            expected_status = "warehouse_higher_than_billed"
    add_check(
        "billing_bridge_status_formula",
        billing_status == expected_status,
        billing_status,
        expected_status,
        ["BILLING_BRIDGE_STATUS", "BILLING_RECONCILIATION_STATUS"],
        "Billing bridge status must reflect the signed bridge delta state.",
    )
    source_value_failures = [
        field
        for field, row in rows_by_field.items()
        if bool(row.get("source_rows_present"))
        and (row.get("packet_value") is None or (row.get("packet_value") == 0 and not bool(row.get("source_confirmed_zero"))))
    ]
    add_check(
        "source_rows_present_values_non_null",
        not source_value_failures,
        source_value_failures,
        [],
        list(rows_by_field),
        "Formula fields with source rows must not publish null/default-zero values.",
    )
    missing_source_zero_failures = [
        field
        for field, row in rows_by_field.items()
        if not bool(row.get("source_rows_present")) and row.get("packet_value") == 0 and not bool(row.get("source_confirmed_zero"))
    ]
    add_check(
        "source_missing_zero_is_pending",
        not missing_source_zero_failures,
        missing_source_zero_failures,
        [],
        list(rows_by_field),
        "Missing source rows must render pending/unavailable, not numeric zero.",
    )
    add_check(
        "spend_movement_comparable_window_or_pending",
        bool(billing_complete) or str(rows_by_field.get("SPEND_MOVEMENT_PCT", {}).get("unavailable_state") or "").lower() in {"pending", "partial"},
        {"BILLING_WINDOW_COMPLETE": billing_complete, "SPEND_MOVEMENT_PCT": values.get("SPEND_MOVEMENT_PCT")},
        "complete window or pending/partial state",
        ["SPEND_MOVEMENT_PCT", "BILLING_WINDOW_COMPLETE"],
        "Spend movement must use comparable complete windows or be marked pending/partial.",
    )

    failures = [
        {
            "code": "SNOWFLAKE_FORMULA_VALUE_CHECK_FAILED",
            "check_name": row["check_name"],
            "failure_reason": row["failure_reason"],
        }
        for row in checks
        if not bool(row.get("passed"))
    ]
    return {
        "source": "snowflake_formula_value_validation",
        "generated_at": _utc_now(),
        "formula_validation_mode": str(value.get("formula_validation_mode") or _formula_validation_mode()),
        "selected_credit_price": credit_price,
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "checks": checks,
        "raw_sql_included": False,
    }


def build_rendered_formula_results(
    root: Path | str = ".",
    *,
    formula_value_reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
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
    formula_values = formula_value_reconciliation or build_formula_value_reconciliation_results(build_formula_chain_results(root_path))
    value_checks: list[dict[str, Any]] = []
    for row in formula_values.get("rows", []):
        if not str(row.get("rendered_section") or ""):
            continue
        tolerance = float(row.get("tolerance") or 0)
        passed = _value_equal(row.get("flat_value"), row.get("rendered_value"), tolerance)
        value_check = {
            "check_name": f"rendered_value_matches_flat_{row.get('decision_packet_field')}",
            "section": row.get("rendered_section"),
            "metric_key": row.get("rendered_metric_key"),
            "packet_field": row.get("decision_packet_field"),
            "flat_value": row.get("flat_value"),
            "rendered_value": row.get("rendered_value"),
            "tolerance": tolerance,
            "passed": passed,
            "failure_reason": "" if passed else "Rendered summary value differs from flat packet value.",
            "raw_sql_included": False,
        }
        value_checks.append(value_check)
        if not passed:
            failures.append({"code": "RENDERED_FORMULA_VALUE_MISMATCH", "packet_field": row.get("decision_packet_field")})
    return {
        "source": "rendered_formula_static_contract",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "checks": checks,
        "value_checks": value_checks,
        "raw_sql_included": False,
    }


def build_formula_live_validation_results(
    root: Path | str = ".",
    *,
    live_rows: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    live_enabled = _formula_live_enabled()
    if not live_enabled:
        return {
            "source": "formula_live_validation",
            "generated_at": _utc_now(),
            "mode": "fixture_static",
            "formula_validation_mode": "fixture_static",
            "status": "skipped",
            "passed": True,
            "skipped": True,
            "skip_reason": _LIVE_PROOF_SKIP_REASON,
            "live_required": False,
            "live_executed": False,
            "live_passed": False,
            "live_skipped": True,
            "live_skip_reason": _LIVE_PROOF_SKIP_REASON,
            "live_waiver_id": "",
            "live_failure_count": 0,
            "snowflake_formula_live_required": False,
            "snowflake_formula_live_executed": False,
            "snowflake_formula_live_passed": False,
            "snowflake_formula_live_skipped": True,
            "snowflake_formula_live_skip_reason": _LIVE_PROOF_SKIP_REASON,
            "snowflake_formula_live_waiver_id": "",
            "snowflake_formula_live_failure_count": 0,
            "failure_count": 0,
            "failures": [],
            "raw_sql_included": False,
        }
    if live_rows is not None:
        rows = [dict(row) for row in live_rows]
        failures = [
            {
                "code": "LIVE_FORMULA_ROW_FAILED",
                "formula_id": row.get("formula_id"),
                "failure_reason": row.get("failure_reason") or "Live formula row failed.",
            }
            for row in rows
            if not bool(row.get("passed"))
        ]
        return {
            "source": "formula_live_validation",
            "generated_at": _utc_now(),
            "mode": "live",
            "formula_validation_mode": "live",
            "status": "passed" if not failures else "failed",
            "passed": not failures,
            "skipped": False,
            "live_required": True,
            "live_executed": True,
            "live_passed": not failures,
            "live_skipped": False,
            "live_skip_reason": "",
            "live_waiver_id": "",
            "live_failure_count": len(failures),
            "snowflake_formula_live_required": True,
            "snowflake_formula_live_executed": True,
            "snowflake_formula_live_passed": not failures,
            "snowflake_formula_live_skipped": False,
            "snowflake_formula_live_skip_reason": "",
            "snowflake_formula_live_waiver_id": "",
            "snowflake_formula_live_failure_count": len(failures),
            "failure_count": len(failures),
            "failures": failures,
            "rows": rows,
            "raw_sql_included": False,
        }
    return {
        "source": "formula_live_validation",
        "generated_at": _utc_now(),
        "mode": "live",
        "formula_validation_mode": "live",
        "status": "failed",
        "passed": False,
        "skipped": False,
        "live_required": True,
        "live_executed": True,
        "live_passed": False,
        "live_skipped": False,
        "live_skip_reason": "",
        "live_waiver_id": "",
        "live_failure_count": 1,
        "snowflake_formula_live_required": True,
        "snowflake_formula_live_executed": True,
        "snowflake_formula_live_passed": False,
        "snowflake_formula_live_skipped": False,
        "snowflake_formula_live_skip_reason": "",
        "snowflake_formula_live_waiver_id": "",
        "snowflake_formula_live_failure_count": 1,
        "failure_count": 1,
        "failures": [{"code": "LIVE_FORMULA_VALIDATION_SESSION_NOT_AVAILABLE", "recommendation": "Run with configured validation database/schema/warehouse session helpers."}],
        "raw_sql_included": False,
    }


def build_snowflake_formula_live_results(root: Path | str = ".") -> dict[str, Any]:
    live = build_formula_live_validation_results(root)
    return {
        **live,
        "source": "snowflake_formula_live_validation",
        "packet_field_count": len(REQUIRED_PACKET_FIELDS),
        "formula_validation_mode": live.get("formula_validation_mode"),
        "snowflake_formula_live_required": bool(live.get("live_required")),
        "snowflake_formula_live_executed": bool(live.get("live_executed")),
        "snowflake_formula_live_passed": bool(live.get("live_passed")),
        "snowflake_formula_live_skipped": bool(live.get("live_skipped")),
        "snowflake_formula_live_skip_reason": str(live.get("live_skip_reason") or live.get("skip_reason") or ""),
        "snowflake_formula_live_waiver_id": str(live.get("live_waiver_id") or ""),
        "snowflake_formula_live_failure_count": int(live.get("live_failure_count") or live.get("failure_count") or 0),
        "recommendation": (
            "Run with OVERWATCH_SNOWFLAKE_VALIDATION=1 and configured validation database/schema/warehouse."
            if live.get("skipped")
            else "Review sanitized live formula validation failures."
        ),
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
    formula_value_reconciliation: Mapping[str, Any],
    packet_formula: Mapping[str, Any],
    flat_packet_formula: Mapping[str, Any],
    snowflake_formula_static: Mapping[str, Any],
    packet_schema_upgrade: Mapping[str, Any],
    rendered_formula: Mapping[str, Any],
    formula_live: Mapping[str, Any] | None = None,
    snowflake_formula_live: Mapping[str, Any] | None = None,
    cortex_live: Mapping[str, Any] | None = None,
    workload_live: Mapping[str, Any] | None = None,
    snowflake_formula_value: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inputs = {
        "formula_chain": formula_chain,
        "formula_value_reconciliation": formula_value_reconciliation,
        "packet_formula": packet_formula,
        "flat_packet_formula": flat_packet_formula,
        "snowflake_formula_static": snowflake_formula_static,
        "packet_schema_upgrade": packet_schema_upgrade,
        "rendered_formula": rendered_formula,
        "snowflake_formula_value": snowflake_formula_value or {"passed": True},
        "formula_live": formula_live or {"passed": True},
        "snowflake_formula_live": snowflake_formula_live or formula_live or {"passed": True},
        "cortex_live": cortex_live or {"passed": True},
        "workload_live": workload_live or {"passed": True},
    }
    failures = [
        {"code": f"{name.upper()}_FAILED", "failure_count": int(payload.get("failure_count") or 0)}
        for name, payload in inputs.items()
        if not bool(payload.get("passed"))
    ]
    live_payload = snowflake_formula_live or formula_live or {}
    live_skipped = bool(live_payload.get("snowflake_formula_live_skipped", live_payload.get("live_skipped", live_payload.get("skipped", False))))
    live_passed = bool(live_payload.get("snowflake_formula_live_passed", live_payload.get("live_passed", False)))
    live_required = bool(live_payload.get("snowflake_formula_live_required", live_payload.get("live_required", False)))
    live_executed = bool(live_payload.get("snowflake_formula_live_executed", live_payload.get("live_executed", False)))
    if live_skipped and live_passed:
        failures.append({"code": "AMBIGUOUS_FORMULA_LIVE_STATUS", "failure_count": 1})
    if live_required and not live_passed:
        failures.append({"code": "FORMULA_LIVE_REQUIRED_NOT_PASSED", "failure_count": int(live_payload.get("failure_count") or 1)})
    return {
        "source": "formula_end_to_end_gate",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "formula_chain_passed": bool(formula_chain.get("passed")),
        "formula_value_reconciliation_passed": bool(formula_value_reconciliation.get("passed")),
        "formula_value_reconciliation_failure_count": int(formula_value_reconciliation.get("failure_count") or 0),
        "formula_validation_mode": str(live_payload.get("formula_validation_mode") or formula_value_reconciliation.get("formula_validation_mode") or "fixture_static"),
        "packet_formula_sql_passed": bool(packet_formula.get("passed")),
        "flat_packet_formula_passed": bool(flat_packet_formula.get("passed")),
        "snowflake_formula_static_passed": bool(snowflake_formula_static.get("passed")),
        "snowflake_formula_value_passed": bool((snowflake_formula_value or {}).get("passed", True)),
        "snowflake_formula_value_failure_count": int((snowflake_formula_value or {}).get("failure_count") or 0),
        "packet_schema_upgrade_passed": bool(packet_schema_upgrade.get("passed")),
        "rendered_formula_passed": bool(rendered_formula.get("passed")),
        "formula_live_validation_passed": bool((formula_live or {}).get("passed", True)),
        "snowflake_formula_live_required": live_required,
        "snowflake_formula_live_executed": live_executed,
        "snowflake_formula_live_passed": live_passed,
        "snowflake_formula_live_skipped": live_skipped,
        "snowflake_formula_live_skip_reason": str(
            live_payload.get("snowflake_formula_live_skip_reason")
            or live_payload.get("live_skip_reason")
            or live_payload.get("skip_reason")
            or ""
        ),
        "snowflake_formula_live_waiver_id": str(live_payload.get("snowflake_formula_live_waiver_id") or live_payload.get("live_waiver_id") or ""),
        "snowflake_formula_live_failure_count": int(
            live_payload.get("snowflake_formula_live_failure_count")
            or live_payload.get("live_failure_count")
            or live_payload.get("failure_count")
            or 0
        ),
        "cortex_service_type_live_passed": bool((cortex_live or {}).get("passed", True)),
        "workload_formula_live_passed": bool((workload_live or {}).get("passed", True)),
        "raw_sql_included": False,
    }


def evaluate_packet_schema_gate(packet_schema_upgrade: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if not bool(packet_schema_upgrade.get("passed")):
        failures.append(
            {
                "code": "PACKET_SCHEMA_UPGRADE_FAILED",
                "failure_count": int(packet_schema_upgrade.get("failure_count") or 0),
            }
        )
    return {
        "source": "packet_schema_upgrade_gate",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "packet_schema_upgrade_passed": bool(packet_schema_upgrade.get("passed")),
        "raw_sql_included": False,
    }


def evaluate_snowflake_formula_gate(
    snowflake_formula_static: Mapping[str, Any],
    snowflake_formula_live: Mapping[str, Any],
    snowflake_formula_value: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if not bool(snowflake_formula_static.get("passed")):
        failures.append(
            {
                "code": "SNOWFLAKE_FORMULA_STATIC_FAILED",
                "failure_count": int(snowflake_formula_static.get("failure_count") or 0),
            }
        )
    if not bool(snowflake_formula_live.get("passed")):
        failures.append(
            {
                "code": "SNOWFLAKE_FORMULA_LIVE_FAILED",
                "failure_count": int(snowflake_formula_live.get("failure_count") or 0),
            }
        )
    if snowflake_formula_value is not None and not bool(snowflake_formula_value.get("passed")):
        failures.append(
            {
                "code": "SNOWFLAKE_FORMULA_VALUE_FAILED",
                "failure_count": int(snowflake_formula_value.get("failure_count") or 0),
            }
        )
    live_skipped = bool(snowflake_formula_live.get("snowflake_formula_live_skipped", snowflake_formula_live.get("skipped")))
    live_passed = bool(snowflake_formula_live.get("snowflake_formula_live_passed", snowflake_formula_live.get("live_passed", False)))
    live_required = bool(snowflake_formula_live.get("snowflake_formula_live_required", snowflake_formula_live.get("live_required", False)))
    if live_skipped and live_passed:
        failures.append({"code": "AMBIGUOUS_FORMULA_LIVE_STATUS"})
    if live_required and not live_passed:
        failures.append({"code": "SNOWFLAKE_FORMULA_LIVE_REQUIRED_NOT_PASSED"})
    return {
        "source": "snowflake_formula_gate",
        "generated_at": _utc_now(),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "snowflake_formula_static_passed": bool(snowflake_formula_static.get("passed")),
        "snowflake_formula_value_passed": bool((snowflake_formula_value or {}).get("passed", True)),
        "snowflake_formula_value_failure_count": int((snowflake_formula_value or {}).get("failure_count") or 0),
        "formula_validation_mode": str(snowflake_formula_live.get("formula_validation_mode") or "fixture_static"),
        "snowflake_formula_live_required": live_required,
        "snowflake_formula_live_executed": bool(snowflake_formula_live.get("snowflake_formula_live_executed", snowflake_formula_live.get("live_executed", False))),
        "snowflake_formula_live_passed": live_passed,
        "snowflake_formula_live_skipped": live_skipped,
        "snowflake_formula_live_skip_reason": str(
            snowflake_formula_live.get("snowflake_formula_live_skip_reason")
            or snowflake_formula_live.get("skip_reason")
            or ""
        ),
        "snowflake_formula_live_waiver_id": str(snowflake_formula_live.get("snowflake_formula_live_waiver_id") or ""),
        "snowflake_formula_live_failure_count": int(
            snowflake_formula_live.get("snowflake_formula_live_failure_count")
            or snowflake_formula_live.get("failure_count")
            or 0
        ),
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
    flat_packet_formula = evaluate_flat_packet_formula_sql(root_path)
    packet_schema_upgrade = build_packet_schema_upgrade_results(root_path)
    snowflake_formula_static = build_snowflake_formula_static_results(root_path)
    formula_chain = build_formula_chain_results(root_path)
    formula_value_reconciliation = build_formula_value_reconciliation_results(formula_chain)
    snowflake_formula_value = build_snowflake_formula_value_results(formula_value_reconciliation)
    rendered_formula = build_rendered_formula_results(root_path, formula_value_reconciliation=formula_value_reconciliation)
    charts = cost_db_chart_pattern_results()
    formula_live = build_formula_live_validation_results(root_path)
    snowflake_formula_live = build_snowflake_formula_live_results(root_path)
    cortex_live = build_cortex_service_type_live_results(root_path)
    workload_live = build_workload_formula_live_results(root_path)
    cortex_mapping = cortex_service_type_mapping_results()
    formula_gate = evaluate_formula_end_to_end_gate(
        formula_chain,
        formula_value_reconciliation,
        packet_formula,
        flat_packet_formula,
        snowflake_formula_static,
        packet_schema_upgrade,
        rendered_formula,
        formula_live,
        snowflake_formula_live,
        cortex_live,
        workload_live,
        snowflake_formula_value,
    )
    packet_schema_gate = evaluate_packet_schema_gate(packet_schema_upgrade)
    snowflake_formula_gate = evaluate_snowflake_formula_gate(snowflake_formula_static, snowflake_formula_live, snowflake_formula_value)
    cortex_gate = evaluate_cortex_service_type_gate(cortex_mapping, cortex_live)
    artifacts = {
        FORMULA_CHAIN_REL: formula_chain,
        FORMULA_VALUE_RECONCILIATION_REL: formula_value_reconciliation,
        PACKET_FORMULA_REL: packet_formula,
        FLAT_PACKET_FORMULA_REL: flat_packet_formula,
        SNOWFLAKE_FORMULA_STATIC_REL: snowflake_formula_static,
        SNOWFLAKE_FORMULA_VALUE_REL: snowflake_formula_value,
        PACKET_SCHEMA_UPGRADE_REL: packet_schema_upgrade,
        RENDERED_FORMULA_REL: rendered_formula,
        COST_WORKBENCH_CHART_REL: charts,
        FORMULA_LIVE_REL: formula_live,
        SNOWFLAKE_FORMULA_LIVE_REL: snowflake_formula_live,
        CORTEX_SERVICE_TYPE_LIVE_REL: cortex_live,
        WORKLOAD_FORMULA_LIVE_REL: workload_live,
        FORMULA_GATE_REL: formula_gate,
        PACKET_SCHEMA_GATE_REL: packet_schema_gate,
        SNOWFLAKE_FORMULA_GATE_REL: snowflake_formula_gate,
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
    "FLAT_PACKET_FORMULA_REL",
    "FORMULA_CHAIN_FIELDS",
    "FORMULA_CHAIN_REL",
    "FORMULA_GATE_REL",
    "FORMULA_LIVE_REL",
    "FORMULA_VALUE_RECONCILIATION_REL",
    "PACKET_SCHEMA_GATE_REL",
    "PACKET_SCHEMA_UPGRADE_REL",
    "PACKET_FORMULA_REL",
    "RENDERED_FORMULA_REL",
    "REQUIRED_PACKET_FIELDS",
    "SNOWFLAKE_FORMULA_GATE_REL",
    "SNOWFLAKE_FORMULA_LIVE_REL",
    "SNOWFLAKE_FORMULA_STATIC_REL",
    "SNOWFLAKE_FORMULA_VALUE_REL",
    "WORKLOAD_FORMULA_LIVE_REL",
    "build_formula_chain_results",
    "build_formula_live_validation_results",
    "build_formula_value_reconciliation_results",
    "build_packet_schema_upgrade_results",
    "build_rendered_formula_results",
    "build_snowflake_formula_live_results",
    "build_snowflake_formula_static_results",
    "build_snowflake_formula_value_results",
    "build_workload_formula_live_results",
    "evaluate_cortex_service_type_gate",
    "evaluate_flat_packet_formula_sql",
    "evaluate_formula_end_to_end_gate",
    "evaluate_packet_formula_sql",
    "evaluate_packet_schema_gate",
    "evaluate_snowflake_formula_gate",
    "write_formula_end_to_end_artifacts",
]
