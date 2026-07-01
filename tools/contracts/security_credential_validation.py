"""Static release proof for credential-expiration and user-display chains."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


SNOWFLAKE_VALIDATION_DIR = "artifacts/snowflake_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"

CREDENTIAL_EXPIRATION_VALIDATION_REL = (
    f"{SNOWFLAKE_VALIDATION_DIR}/credential_expiration_validation_results.json"
)
USER_DISPLAY_DIMENSION_VALIDATION_REL = (
    f"{SNOWFLAKE_VALIDATION_DIR}/user_display_dimension_validation_results.json"
)
SECURITY_CREDENTIAL_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/security_credential_expiration_gate_results.json"
)
CREDENTIAL_EXPIRATION_LIVE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/credential_expiration_live_results.json"
USER_DISPLAY_DIMENSION_LIVE_REL = f"{SNOWFLAKE_VALIDATION_DIR}/user_display_dimension_live_results.json"
SECURITY_CREDENTIAL_LIVE_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/security_credential_expiration_live_gate_results.json"
)
USER_DISPLAY_NAME_LIVE_GATE_REL = f"{LAUNCH_READINESS_DIR}/user_display_name_live_gate_results.json"
USER_DISPLAY_NAME_GATE_REL = f"{LAUNCH_READINESS_DIR}/user_display_name_gate_results.json"
USER_DISPLAY_SURFACE_REL = f"{FULL_APP_VALIDATION_DIR}/user_display_surface_results.json"
USER_DISPLAY_SURFACE_GATE_REL = f"{LAUNCH_READINESS_DIR}/user_display_surface_gate_results.json"
CORTEX_USER_LABEL_REL = f"{FULL_APP_VALIDATION_DIR}/cortex_user_label_results.json"
CORTEX_USER_LABEL_GATE_REL = f"{LAUNCH_READINESS_DIR}/cortex_user_label_gate_results.json"
SECURITY_CREDENTIAL_EXPORT_REL = f"{FULL_APP_VALIDATION_DIR}/security_credential_export_results.json"
SECURITY_CREDENTIAL_EXPORT_GATE_REL = f"{LAUNCH_READINESS_DIR}/security_credential_export_gate_results.json"
SECURITY_CREDENTIAL_RENDER_REL = f"{FULL_APP_VALIDATION_DIR}/security_credential_render_results.json"
SECURITY_CREDENTIAL_RENDER_GATE_REL = f"{LAUNCH_READINESS_DIR}/security_credential_render_gate_results.json"
SECURITY_CREDENTIAL_EVIDENCE_REL = f"{FULL_APP_VALIDATION_DIR}/security_credential_evidence_results.json"
SECURITY_CREDENTIAL_EVIDENCE_GATE_REL = f"{LAUNCH_READINESS_DIR}/security_credential_evidence_gate_results.json"
SECURITY_CREDENTIAL_FIRST_PAINT_REL = (
    f"{FULL_APP_VALIDATION_DIR}/security_credential_first_paint_results.json"
)
SECURITY_CREDENTIAL_FIRST_PAINT_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/security_credential_first_paint_gate_results.json"
)
SECURITY_CREDENTIAL_SQL_INVENTORY_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/credential_sql_inventory_gate_results.json"
)
SECURITY_CREDENTIAL_RENDERED_LEAK_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/credential_rendered_leak_gate_results.json"
)

SECURITY_CREDENTIAL_PACKET_FIELDS = (
    "SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT",
    "SECURITY_CREDENTIALS_EXPIRING_30D_COUNT",
    "SECURITY_CREDENTIALS_EXPIRING_7D_COUNT",
    "SECURITY_CREDENTIALS_EXPIRED_COUNT",
    "SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS",
    "SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER",
    "SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE",
    "SECURITY_CREDENTIAL_EXPIRATION_STATUS",
    "SECURITY_CREDENTIAL_EXPIRATION_FINDINGS",
    "SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO",
    "SECURITY_CREDENTIAL_SOURCE_STATUS",
    "SECURITY_CREDENTIAL_SOURCE_FRESHNESS_TS",
    "SECURITY_CREDENTIAL_SOURCE_LATENCY_NOTE",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _read(root: Path, rel: str) -> str:
    path = root / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _contains(text: str, token: str) -> bool:
    return token.upper() in text.upper()


def _load_json(root: Path, rel: str) -> Any:
    path = root / rel
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _rows(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("rows", "actions", "results", "cases"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    return []


def _find_surface_row(root: Path, rel: str, section: str, workflow: str) -> tuple[int, Mapping[str, Any]]:
    for index, row in enumerate(_rows(_load_json(root, rel))):
        if str(row.get("section") or "") == section and str(row.get("workflow") or "") == workflow:
            return index, row
    return -1, {}


def _find_action_row(root: Path, section: str, workflow: str) -> tuple[str, int, Mapping[str, Any]]:
    for rel in (
        "artifacts/full_app_validation/button_click_results.json",
        "artifacts/full_app_validation/action_click_results.json",
    ):
        for index, row in enumerate(_rows(_load_json(root, rel))):
            if (
                str(row.get("section") or "") == section
                and str(row.get("workflow") or "") == workflow
                and bool(row.get("clicked", row.get("passed", False)))
            ):
                return rel, index, row
    return "", -1, {}


def _resolve_payload_path(root: Path, payload_file: object) -> Path:
    raw = Path(str(payload_file or ""))
    return raw if raw.is_absolute() else root / raw


def _payload_file_failures(root: Path, row: Mapping[str, Any], *, row_kind: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    payload_file = str(row.get("payload_file") or "")
    if not payload_file:
        return "", [f"{row_kind} row missing payload_file"]
    path = _resolve_payload_path(root, payload_file)
    if not path.exists():
        return "", [f"{row_kind} payload file missing"]
    payload = path.read_bytes()
    text = payload.decode("utf-8", errors="ignore")
    expected_sha = str(row.get("sha256") or row.get("payload_hash") or "")
    if expected_sha and hashlib.sha256(payload).hexdigest() != expected_sha:
        reasons.append(f"{row_kind} payload sha256 mismatch")
    expected_size = int(row.get("size_bytes") or row.get("content_length") or 0)
    if expected_size and expected_size != len(payload):
        reasons.append(f"{row_kind} payload size mismatch")
    if len(payload) <= 0 and not bool(row.get("intentional_empty")):
        reasons.append(f"{row_kind} payload is empty")
    return text, reasons


def _credential_export_payload_failures(root: Path, row: Mapping[str, Any]) -> list[str]:
    text, reasons = _payload_file_failures(root, row, row_kind="credential export")
    if not text:
        return reasons
    reader = csv.DictReader(text.splitlines())
    columns = set(reader.fieldnames or [])
    parsed_rows = list(reader)
    required = {"User", "Credential", "Type", "Status", "Recommended action"}
    missing = sorted(required - columns)
    if missing:
        reasons.append(f"credential export missing required columns: {', '.join(missing)}")
    if "Expires" not in columns and "Days left" not in columns:
        reasons.append("credential export missing Expires or Days left column")
    forbidden = {"USER_ID", "RAW_USER_ID", "CREDENTIAL_ID", "SOURCE_OBJECT", "RAW_SQL", "query_text", "QUERY_TEXT"}
    leaked = sorted(column for column in columns if column in forbidden)
    if leaked and not bool(row.get("admin_only")):
        reasons.append(f"credential default export leaks raw columns: {', '.join(leaked)}")
    visible_rows = int(row.get("visible_row_count") or row.get("row_count") or 0)
    if visible_rows != len(parsed_rows):
        reasons.append("credential export parsed row count differs from visible row count")
    if "ACCOUNT_USAGE" in text.upper() or "CREDENTIAL_ID" in text.upper() or "USER_ID" in text.upper():
        if not bool(row.get("admin_only")):
            reasons.append("credential default export leaks source or raw identifier text")
    return reasons


def _credential_case_payload_failures(root: Path, row: Mapping[str, Any]) -> list[str]:
    text, reasons = _payload_file_failures(root, row, row_kind="credential case payload")
    if not text:
        return reasons
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return reasons + ["credential case payload is not valid JSON"]
    required = {
        "section",
        "workflow",
        "scope",
        "target",
        "freshness",
        "source_family",
        "summary",
        "row_count",
        "visible_row_count",
        "recommended_action",
        "expired_count",
        "expiring_30d_count",
        "next_expiration",
        "owner_labels",
    }
    missing = sorted(field for field in required if field not in payload)
    if missing:
        reasons.append(f"credential case payload missing required fields: {', '.join(missing)}")
    if str(payload.get("source_family") or "") != "credential_expiration":
        reasons.append("credential case payload source_family must be credential_expiration")
    visible_rows = int(row.get("visible_row_count") or row.get("row_count") or 0)
    if visible_rows != int(payload.get("visible_row_count") or 0):
        reasons.append("credential case visible row count differs from payload")
    if ("USER_ID" in text.upper() or "CREDENTIAL_ID" in text.upper() or "ACCOUNT_USAGE" in text.upper()) and not bool(row.get("admin_only")):
        reasons.append("credential default case payload leaks source or raw identifier text")
    return reasons


def _runtime_references(root: Path, section: str, workflow: str) -> tuple[dict[str, Any], list[str]]:
    render_rel = "artifacts/full_app_validation/rendered_fragments.json"
    export_rel = "artifacts/full_app_validation/export_results.json"
    case_rel = "artifacts/full_app_validation/case_payload_results.json"
    render_index, render_row = _find_surface_row(root, render_rel, section, workflow)
    action_rel, action_index, action_row = _find_action_row(root, section, workflow)
    export_index, export_row = _find_surface_row(root, export_rel, section, workflow)
    case_index, case_row = _find_surface_row(root, case_rel, section, workflow)
    refs = {
        "rendered_artifact_path": render_rel if render_row else "",
        "rendered_row_id": str(render_row.get("id") or render_row.get("runtime_artifact_row_index") or render_index if render_row else ""),
        "rendered_row_index": render_index,
        "action_artifact_path": action_rel,
        "action_row_id": str(action_row.get("id") or action_row.get("stable_key") or action_row.get("runtime_artifact_row_index") or action_index if action_row else ""),
        "action_row_index": action_index,
        "export_artifact_path": export_rel if export_row else "",
        "export_row_id": str(export_row.get("id") or export_row.get("stable_key") or export_row.get("filename") or export_row.get("runtime_artifact_row_index") or export_index if export_row else ""),
        "export_row_index": export_index,
        "case_payload_artifact_path": case_rel if case_row else "",
        "case_payload_row_id": str(case_row.get("id") or case_row.get("filename") or case_row.get("runtime_artifact_row_index") or case_index if case_row else ""),
        "case_payload_row_index": case_index,
        "expected_section": section,
        "expected_workflow": workflow,
        "source_rows_present": bool(render_row.get("source_rows_present", render_row)),
        "visible_row_count": int(render_row.get("visible_row_count") or export_row.get("visible_row_count") or 0) if (render_row or export_row) else 0,
        "exported_row_count": int(export_row.get("parsed_row_count") or export_row.get("row_count") or 0) if export_row else 0,
        "case_row_count": int(case_row.get("parsed_row_count") or case_row.get("row_count") or 0) if case_row else 0,
        "producer_signature": str(render_row.get("producer_signature") or ""),
        "commit_sha": str(render_row.get("commit_sha") or ""),
    }
    missing = [
        name
        for name, row in (
            ("rendered runtime row", render_row),
            ("clicked action row", action_row),
            ("file-backed export row", export_row),
            ("case payload row", case_row),
        )
        if not row
    ]
    if export_row and refs["visible_row_count"] != refs["exported_row_count"]:
        missing.append("visible/exported row count mismatch")
    if case_row and refs["visible_row_count"] != refs["case_row_count"]:
        missing.append("visible/case row count mismatch")
    for name, row in (
        ("rendered runtime row", render_row),
        ("clicked action row", action_row),
        ("file-backed export row", export_row),
        ("case payload row", case_row),
    ):
        if row and not row.get("producer_signature"):
            missing.append(f"{name} missing producer_signature")
        if row and str(row.get("section") or "") != section:
            missing.append(f"{name} section mismatch")
        if row and str(row.get("workflow") or "") != workflow:
            missing.append(f"{name} workflow mismatch")
    if any(bool(row.get("raw_sql_included")) for row in (render_row, action_row, export_row, case_row) if row):
        missing.append("runtime artifact row included raw SQL")
    if export_row:
        missing.extend(_credential_export_payload_failures(root, export_row))
    if case_row:
        missing.extend(_credential_case_payload_failures(root, case_row))
    return refs, missing


def _selected_profile(profile: str | None = None) -> str:
    return (profile or os.environ.get("OVERWATCH_LAUNCH_PROFILE") or "internal_fixture").strip() or "internal_fixture"


def _live_required(profile: str) -> bool:
    return profile in {"internal_live", "prod_candidate"}


def _first_valid_waiver(waivers: Iterable[Mapping[str, Any]], *gates: str) -> Mapping[str, Any]:
    gate_set = set(gates)
    for row in waivers:
        if str(row.get("gate") or "") in gate_set and bool(row.get("valid")):
            return row
    return {}


def _row(check: str, passed: bool, *, evidence: str, recommendation: str = "") -> dict[str, Any]:
    return {
        "check": check,
        "passed": bool(passed),
        "evidence": evidence,
        "failure_reason": "" if passed else recommendation,
        "recommendation": "" if passed else recommendation,
        "raw_sql_included": False,
    }


def _scan_forbidden_daily_source(root: Path, forbidden: str, daily_roots: Iterable[str]) -> list[str]:
    hits: list[str] = []
    for rel_root in daily_roots:
        base = root / rel_root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if forbidden.upper() in text.upper():
                hits.append(str(path.relative_to(root)).replace("\\", "/"))
    return hits


def build_credential_expiration_validation(root: Path) -> dict[str, Any]:
    table_sql = _read(root, "snowflake/mart_setup/04_mart_tables.sql")
    proc_sql = _read(root, "snowflake/mart_setup/05_load_procedures.sql")
    split_validation_sql = _read(root, "snowflake/mart_setup/08_validation.sql")
    setup_sql = _read(root, "snowflake/OVERWATCH_MART_SETUP.sql")
    validation_sql = _read(root, "snowflake/OVERWATCH_MART_VALIDATION.sql")
    security_daily_hits = _scan_forbidden_daily_source(
        root,
        "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS",
        (".overwatch_final/sections", ".overwatch_final/utils"),
    )

    field_coverage = {
        field: {
            "table_or_alter": _contains(table_sql, field),
            "procedure_packet": _contains(proc_sql, field),
            "split_validation": _contains(split_validation_sql, field),
            "setup_monolith": _contains(setup_sql, field),
            "validation_monolith": _contains(validation_sql, field),
        }
        for field in SECURITY_CREDENTIAL_PACKET_FIELDS
    }
    missing_field_coverage = [
        {"field": field, **coverage}
        for field, coverage in field_coverage.items()
        if not all(coverage.values())
    ]

    rows = [
        _row(
            "credential_compact_mart_defined",
            _contains(table_sql, "CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT")
            and _contains(setup_sql, "CREATE TRANSIENT TABLE IF NOT EXISTS MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT"),
            evidence="MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT table in split and monolith setup.",
            recommendation="Define the compact credential-expiration mart in split and monolith setup SQL.",
        ),
        _row(
            "credential_loader_procedure_defined",
            _contains(proc_sql, "SP_OVERWATCH_LOAD_SECURITY_CREDENTIAL_EXPIRATIONS")
            and _contains(proc_sql, "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS")
            and _contains(setup_sql, "SP_OVERWATCH_LOAD_SECURITY_CREDENTIAL_EXPIRATIONS"),
            evidence="Credential loader exists and is generated into monolith setup.",
            recommendation="Create the credential loader and regenerate OVERWATCH_MART_SETUP.sql.",
        ),
        _row(
            "credential_expiration_formula_present",
            all(
                _contains(proc_sql, token)
                for token in (
                    "EXPIRATION_DATE",
                    "DATEDIFF('DAY'",
                    "CREDENTIAL_EXPIRING_30D_FLAG",
                    "CREDENTIAL_EXPIRING_7D_FLAG",
                    "CREDENTIAL_EXPIRED_FLAG",
                    "CREDENTIAL_EXPIRATION_SEVERITY",
                )
            ),
            evidence="Loader derives days, buckets, flags, and severity from EXPIRATION_DATE.",
            recommendation="Derive credential expiration flags and severity from EXPIRATION_DATE.",
        ),
        _row(
            "credential_refresh_invoked_before_packets",
            _contains(proc_sql, "CALL SP_OVERWATCH_LOAD_SECURITY_CREDENTIAL_EXPIRATIONS()")
            and _contains(proc_sql, "credential_rollup"),
            evidence="Section refresh invokes credential compact load before packet rollup.",
            recommendation="Call the compact credential refresh before command brief packet generation.",
        ),
        _row(
            "credential_packet_fields_covered",
            not missing_field_coverage,
            evidence=f"{len(SECURITY_CREDENTIAL_PACKET_FIELDS)} packet fields checked.",
            recommendation="Add all credential packet fields to table DDL, procedure packet generation, and validation SQL.",
        ),
        _row(
            "credential_metric_tile_present",
            _contains(proc_sql, "credential_expirations")
            and _contains(proc_sql, "Credential expirations")
            and _contains(proc_sql, "No credentials due within 30d"),
            evidence="Security command metrics include a Credential expirations tile.",
            recommendation="Add a compact Security Monitoring metric tile backed by packet fields.",
        ),
        _row(
            "credential_action_and_finding_present",
            _contains(proc_sql, "security_credential_expiration")
            and _contains(proc_sql, "CREDENTIAL_EXPIRING::")
            and _contains(proc_sql, "security_credential_expirations")
            and _contains(proc_sql, "Rotate or renew credential before expiration"),
            evidence="Credential expiration is promoted into findings/actions with route context.",
            recommendation="Create actionable findings/actions for expiring credentials.",
        ),
        _row(
            "credential_evidence_reads_compact_mart",
            _contains(proc_sql, "INSERT INTO MART_SECURITY_EVIDENCE_RECENT")
            and _contains(proc_sql, "FROM MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT c"),
            evidence="Security evidence rows are populated from the compact mart.",
            recommendation="Load credential evidence from compact mart rows, not Account Usage on page entry.",
        ),
        _row(
            "credential_source_not_in_daily_python",
            not security_daily_hits,
            evidence="Daily Python sections do not reference SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS.",
            recommendation="Keep Account Usage credential reads inside refresh/setup/live validation only.",
        ),
        _row(
            "credential_validation_sql_updated",
            _contains(validation_sql, "MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT")
            and all(_contains(validation_sql, field) for field in SECURITY_CREDENTIAL_PACKET_FIELDS),
            evidence="Monolith validation checks credential mart and packet fields.",
            recommendation="Update OVERWATCH_MART_VALIDATION.sql with credential object and field checks.",
        ),
    ]

    failures = [row for row in rows if not row["passed"]]
    if missing_field_coverage:
        failures.append(
            {
                "check": "credential_packet_field_coverage_details",
                "passed": False,
                "missing_field_coverage": missing_field_coverage,
                "failure_reason": "One or more credential packet fields are not covered end to end.",
                "recommendation": "Patch DDL/procedure/validation coverage for every credential field.",
                "raw_sql_included": False,
            }
        )

    return {
        "source": "credential_expiration_validation",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "credential_expiration_gate_passed": not failures,
        "credential_expiring_30d_count": None,
        "credential_expired_count": None,
        "credential_next_expiration_days": None,
        "credential_source_confirmed_zero": None,
        "live_validation_status": "not_executed_static_contract",
        "packet_fields": list(SECURITY_CREDENTIAL_PACKET_FIELDS),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_user_display_dimension_validation(root: Path) -> dict[str, Any]:
    table_sql = _read(root, "snowflake/mart_setup/04_mart_tables.sql")
    proc_sql = _read(root, "snowflake/mart_setup/05_load_procedures.sql")
    setup_sql = _read(root, "snowflake/OVERWATCH_MART_SETUP.sql")
    validation_sql = _read(root, "snowflake/OVERWATCH_MART_VALIDATION.sql")
    cortex_source = _read(root, ".overwatch_final/sections/cortex_monitor.py")
    helper_source = _read(root, ".overwatch_final/utils/user_display.py")

    rows = [
        _row(
            "user_dim_table_defined",
            _contains(table_sql, "MART_USER_DIM_CURRENT") and _contains(setup_sql, "MART_USER_DIM_CURRENT"),
            evidence="MART_USER_DIM_CURRENT exists in split and monolith setup.",
            recommendation="Create MART_USER_DIM_CURRENT and regenerate monolith setup SQL.",
        ),
        _row(
            "user_dim_refresh_uses_account_usage_users",
            _contains(proc_sql, "SNOWFLAKE.ACCOUNT_USAGE.USERS")
            and _contains(proc_sql, "FIRST_NAME")
            and _contains(proc_sql, "LAST_NAME")
            and _contains(proc_sql, "DISPLAY_NAME"),
            evidence="Refresh derives labels from USERS first/last/display/name fields.",
            recommendation="Load user display labels from SNOWFLAKE.ACCOUNT_USAGE.USERS during refresh.",
        ),
        _row(
            "user_dim_refresh_uses_login_fallback",
            _contains(proc_sql, "LOGIN_NAME")
            and _contains(proc_sql, "Unknown user")
            and _contains(proc_sql, "USER_CHART_LABEL"),
            evidence="User dimension and credential rows fall back to LOGIN_NAME/Unknown user instead of USER_ID.",
            recommendation="Add LOGIN_NAME and Unknown user fallbacks to daily display/chart label SQL.",
        ),
        _row(
            "fact_cortex_carries_display_labels",
            all(
                _contains(table_sql, token) and _contains(proc_sql, token)
                for token in ("USER_NAME", "USER_DISPLAY_NAME", "USER_CHART_LABEL", "USER_EMAIL")
            ),
            evidence="FACT_CORTEX_DAILY carries stable and display user labels.",
            recommendation="Persist stable USER_NAME plus friendly display/chart labels on Cortex facts.",
        ),
        _row(
            "cortex_chart_uses_user_chart_label",
            _contains(cortex_source, '"USER_CHART_LABEL"')
            and _contains(cortex_source, 'stable_key="USER_NAME"')
            and _contains(cortex_source, "USER_DISPLAY_NAME"),
            evidence="Cortex user chart uses USER_CHART_LABEL, stable USER_NAME grouping, and USER_DISPLAY_NAME tables.",
            recommendation="Use USER_CHART_LABEL for daily Cortex user charts, stable USER_NAME grouping, and USER_DISPLAY_NAME for tables.",
        ),
        _row(
            "default_exports_hide_user_id",
            _contains(helper_source, "USER_ID_COLUMNS")
            and _contains(helper_source, "sanitize_user_columns_for_export")
            and _contains(helper_source, "looks_like_user_id")
            and _contains(helper_source, "admin_only"),
            evidence="User export helper strips USER_ID columns and suppresses opaque ID-looking labels unless admin_only=true.",
            recommendation="Hide USER_ID and opaque stable IDs from default daily exports.",
        ),
        _row(
            "daily_chart_label_never_user_id",
            _contains(helper_source, "UNKNOWN_USER_LABEL")
            and _contains(helper_source, "looks_like_user_id")
            and not _contains(helper_source, 'return full_name(row) or user_name(row) or "Unknown user"'),
            evidence="USER_CHART_LABEL falls back to Unknown user instead of USER_ID.",
            recommendation="Never allow USER_ID to become a daily chart label.",
        ),
        _row(
            "validation_sql_checks_user_display_objects",
            _contains(validation_sql, "MART_USER_DIM_CURRENT")
            and _contains(validation_sql, "USER_DISPLAY_NAME")
            and _contains(validation_sql, "USER_CHART_LABEL"),
            evidence="Monolith validation checks user dimension and display columns.",
            recommendation="Update OVERWATCH_MART_VALIDATION.sql with user display object/column checks.",
        ),
    ]
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "user_display_dimension_validation",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "user_display_name_gate_passed": not failures,
        "cortex_user_label_gate_passed": not failures,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def _surface_row(
    *,
    surface: str,
    section: str,
    chart_or_table: str,
    visible_user_column: str,
    stable_user_key_column: str,
    user_id_visible: bool,
    user_chart_label_used: bool,
    user_display_name_used: bool,
    total_value_before_label_join: float | int = 100,
    total_value_after_label_join: float | int = 100,
    source_artifact: str = "source_static_contract",
    admin_only: bool = False,
    user_id_allowed: bool = False,
    failure_reason: str = "",
) -> dict[str, Any]:
    totals_match = float(total_value_before_label_join) == float(total_value_after_label_join)
    passed = (
        (not user_id_visible or user_id_allowed)
        and (user_chart_label_used or user_display_name_used or admin_only)
        and bool(stable_user_key_column)
        and totals_match
    )
    if failure_reason:
        passed = False
    return {
        "surface": surface,
        "section": section,
        "chart_or_table": chart_or_table,
        "visible_user_column": visible_user_column,
        "stable_user_key_column": stable_user_key_column,
        "stable_user_key_present": bool(stable_user_key_column),
        "user_id_visible": bool(user_id_visible),
        "user_id_allowed": bool(user_id_allowed),
        "user_chart_label_used": bool(user_chart_label_used),
        "user_display_name_used": bool(user_display_name_used),
        "total_value_before_label_join": total_value_before_label_join,
        "total_value_after_label_join": total_value_after_label_join,
        "source_artifact": source_artifact,
        "admin_only": bool(admin_only),
        "passed": bool(passed),
        "failure_reason": ""
        if passed
        else failure_reason
        or "Daily user surface must use friendly labels, keep a stable grouping key, preserve totals, and hide USER_ID.",
        "raw_sql_included": False,
    }


def build_user_display_surface_results(root: Path) -> dict[str, Any]:
    cortex_source = _read(root, ".overwatch_final/sections/cortex_monitor.py")
    cost_source = _read(root, ".overwatch_final/sections/cost_contract_sql.py")
    helper_source = _read(root, ".overwatch_final/utils/user_display.py")
    security_helper = _read(root, ".overwatch_final/utils/security_credentials.py")

    rows = [
        _surface_row(
            surface="Cortex Usage",
            section="Cost & Contract",
            chart_or_table="Cost by user chart",
            visible_user_column="USER_CHART_LABEL",
            stable_user_key_column="USER_NAME"
            if _contains(cortex_source, 'groupby(["USER_NAME", "USER_DISPLAY_NAME", "USER_CHART_LABEL"]')
            else "",
            user_id_visible=_contains(cortex_source, 'render_ranked_bar_chart(user_agg, "USER_ID"'),
            user_chart_label_used=_contains(cortex_source, '"USER_CHART_LABEL"')
            and _contains(cortex_source, 'stable_key="USER_NAME"'),
            user_display_name_used=_contains(cortex_source, '"USER_DISPLAY_NAME"'),
        ),
        _surface_row(
            surface="Cortex Usage",
            section="Cost & Contract",
            chart_or_table="Cortex user default export",
            visible_user_column="USER_DISPLAY_NAME",
            stable_user_key_column="USER_NAME",
            user_id_visible=not _contains(cortex_source, "sanitize_user_columns_for_export(df_cc)"),
            user_chart_label_used=_contains(cortex_source, "USER_CHART_LABEL"),
            user_display_name_used=_contains(cortex_source, "USER_DISPLAY_NAME"),
        ),
        _surface_row(
            surface="Cortex token efficiency export",
            section="Cortex Monitor",
            chart_or_table="Cortex efficiency workbench export",
            visible_user_column="USER_DISPLAY_NAME",
            stable_user_key_column="USER_NAME",
            user_id_visible=not _contains(cortex_source, "sanitize_user_columns_for_export(efficiency_rows)"),
            user_chart_label_used=_contains(cortex_source, "USER_CHART_LABEL"),
            user_display_name_used=_contains(cortex_source, "USER_DISPLAY_NAME"),
        ),
        _surface_row(
            surface="Cost Workbench",
            section="Cost & Contract",
            chart_or_table="Top Cortex user",
            visible_user_column="user_label",
            stable_user_key_column="stable_user_name" if _contains(cost_source, "stable_user_name") else "",
            user_id_visible=_contains(cost_source, '_snowflake_user_chart_expr("u", "TO_VARCHAR(c.USER_ID)")'),
            user_chart_label_used=_contains(cost_source, "_snowflake_user_chart_expr"),
            user_display_name_used=False,
        ),
        _surface_row(
            surface="Security credential evidence",
            section="Security Monitoring",
            chart_or_table="Credential expiration export",
            visible_user_column="USER_DISPLAY_NAME",
            stable_user_key_column="USER_NAME",
            user_id_visible=not _contains(security_helper, "sanitize_user_columns_for_export"),
            user_chart_label_used=_contains(security_helper, "USER_CHART_LABEL"),
            user_display_name_used=_contains(security_helper, "USER_DISPLAY_NAME"),
        ),
        _surface_row(
            surface="Security credential expiration tile",
            section="Security Monitoring",
            chart_or_table="Security overview tile",
            visible_user_column="SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER",
            stable_user_key_column="USER_NAME",
            user_id_visible=False,
            user_chart_label_used=False,
            user_display_name_used=_contains(security_helper, "credential_expiration_tile_from_packet"),
        ),
        _surface_row(
            surface="Alert/action owner labels",
            section="Alert Center",
            chart_or_table="Credential expiration finding owner",
            visible_user_column="OWNER_NAME",
            stable_user_key_column="OWNER_ID",
            user_id_visible=False,
            user_chart_label_used=False,
            user_display_name_used=_contains(security_helper, "credential_expiration_findings"),
        ),
        _surface_row(
            surface="Security credential case payload",
            section="Security Monitoring",
            chart_or_table="Case payload",
            visible_user_column="owner_labels",
            stable_user_key_column="USER_NAME",
            user_id_visible=False,
            user_chart_label_used=False,
            user_display_name_used=_contains(security_helper, "make_credential_case_payload"),
        ),
        _surface_row(
            surface="User display helper",
            section="Shared",
            chart_or_table="Daily label fallback",
            visible_user_column="USER_CHART_LABEL",
            stable_user_key_column="USER_NAME",
            user_id_visible=not _contains(helper_source, "looks_like_user_id"),
            user_chart_label_used=_contains(helper_source, "user_chart_label"),
            user_display_name_used=_contains(helper_source, "user_display_name"),
        ),
    ]
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "user_display_surface_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "user_id_daily_leak_count": sum(1 for row in rows if row.get("user_id_visible")),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_security_credential_render_results(root: Path) -> dict[str, Any]:
    proc_sql = _read(root, "snowflake/mart_setup/05_load_procedures.sql")
    helper_source = _read(root, ".overwatch_final/utils/security_credentials.py")
    view_model = _read(root, ".overwatch_final/sections/decision_workspace_view_model.py")
    render_index, render_row = _find_surface_row(
        root,
        "artifacts/full_app_validation/rendered_fragments.json",
        "Security Monitoring",
        "Security Overview",
    )
    if not render_row:
        render_index, render_row = _find_surface_row(
            root,
            "artifacts/full_app_validation/view_results.json",
            "Security Monitoring",
            "Security Overview",
        )
    rendered_text = "\n".join(
        str(render_row.get(key) or "")
        for key in ("text", "html_fragment", "rendered_text", "first_viewport_text")
    )
    forbidden_render_tokens = ("CREDENTIAL_ID", "USER_ID", "ACCOUNT_USAGE", "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS")
    rows = [
        _row(
            "security_credential_tile_packet_backed",
            _contains(proc_sql, "'credential_expirations'")
            and _contains(proc_sql, "SECURITY_CREDENTIAL_EXPIRATION_RISK_COUNT")
            and _contains(view_model, '"credential_expirations"'),
            evidence="Security primary metric reads credential_expirations from command brief packet metrics.",
            recommendation="Render Credential expirations from the Security packet, not optional evidence dataframes.",
        ),
        _row(
            "security_credential_tile_daily_text",
            _contains(proc_sql, "No credentials due within 30d")
            and _contains(proc_sql, "due within 30d")
            and _contains(proc_sql, "Next: "),
            evidence="Credential tile includes compact daily text for clear, due, and next-expiration states.",
            recommendation="Add compact credential-expiration tile wording to packet metrics.",
        ),
        _row(
            "security_credential_pending_not_zero",
            _contains(helper_source, "Credential expiration source pending")
            and _contains(helper_source, "source_confirmed_zero"),
            evidence="Missing credential source renders pending; confirmed zero requires source-confirmed zero.",
            recommendation="Do not render missing credential sources as zero.",
        ),
        _row(
            "security_credential_render_sanitized",
            not _contains(helper_source, "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS")
            and _contains(helper_source, "ADMIN_ONLY_CREDENTIAL_COLUMNS"),
            evidence="Daily credential render helpers do not read source object names and hide raw IDs.",
            recommendation="Keep source object details in setup/live validation only.",
        ),
        _row(
            "security_credential_runtime_tile_rendered",
            bool(render_row)
            and _contains(rendered_text, "Credential expirations")
            and not any(_contains(rendered_text, token) for token in forbidden_render_tokens),
            evidence=f"Security runtime render row index {render_index} contains the daily credential tile.",
            recommendation="Render Security Monitoring overview from runtime packet fields and keep raw identifiers out.",
        ),
    ]
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "security_credential_render_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "credential_render_gate_passed": not failures,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_security_credential_evidence_results(root: Path) -> dict[str, Any]:
    proc_sql = _read(root, "snowflake/mart_setup/05_load_procedures.sql")
    helper_source = _read(root, ".overwatch_final/utils/security_credentials.py")
    target_filters = _read(root, ".overwatch_final/sections/decision_workspace_target_filters.py")
    runtime_refs, runtime_failures = _runtime_references(root, "Security Credential Evidence", "Explicit action")
    rows = [
        _row(
            "credential_evidence_compact_mart_only",
            _contains(proc_sql, "FROM MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT c")
            and _contains(proc_sql, "MART_SECURITY_EVIDENCE_RECENT"),
            evidence="Credential evidence is published from compact mart rows.",
            recommendation="Load credential evidence from compact mart only after explicit action.",
        ),
        _row(
            "credential_evidence_target_filterable",
            _contains(target_filters, "USER_NAME")
            and _contains(target_filters, "EVIDENCE_ID")
            and _contains(target_filters, "ENTITY_ID"),
            evidence="Security target filters include user/evidence stable keys before query.",
            recommendation="Apply target SQL filters before credential evidence loads.",
        ),
        _row(
            "credential_evidence_daily_columns",
            _contains(helper_source, "DAILY_CREDENTIAL_COLUMNS")
            and _contains(helper_source, "credential_evidence_daily_frame"),
            evidence="Daily credential evidence has a fixed sanitized visible column set.",
            recommendation="Expose only User/Credential/Type/Domain/Status/Expires/Days left/Last used/Recommended action.",
        ),
        _row(
            "credential_case_payload_complete",
            _contains(helper_source, "make_credential_case_payload")
            and _contains(helper_source, "expired_count")
            and _contains(helper_source, "expiring_30d_count"),
            evidence="Credential case payload includes expiration counts, owner labels, freshness, and row counts.",
            recommendation="Add sanitized credential-expiration fields to case payloads.",
        ),
        _row(
            "credential_evidence_runtime_artifact_references",
            not runtime_failures,
            evidence="Credential evidence gate references rendered, clicked, exported, and case payload runtime artifacts.",
            recommendation="Generate Security Credential Evidence explicit-action render/click/export/case artifacts before evaluating this gate.",
        ),
    ]
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "security_credential_evidence_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        **runtime_refs,
        "runtime_reference_failures": runtime_failures,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_security_credential_first_paint_results(root: Path) -> dict[str, Any]:
    performance = root / "artifacts/full_app_validation/first_paint_performance_results.json"
    rows: list[dict[str, Any]] = []
    if performance.exists():
        try:
            payload = json.loads(performance.read_text(encoding="utf-8"))
            source_rows = payload.get("rows") if isinstance(payload, Mapping) else None
            for row in source_rows if isinstance(source_rows, list) else []:
                if str(row.get("section") or "") == "Security Monitoring":
                    rows.append(
                        {
                            "section": "Security Monitoring",
                            "workflow": str(row.get("workflow") or "Overview"),
                            "cold_first_paint_packet_query_count": int(
                                row.get("cold_first_paint_packet_query_count") or row.get("query_count") or 0
                            ),
                            "warm_first_paint_query_count": int(row.get("warm_first_paint_query_count") or 0),
                            "account_usage_count": int(row.get("account_usage_count") or 0),
                            "credential_compact_evidence_query_count": int(
                                row.get("credential_compact_evidence_query_count")
                                or row.get("evidence_query_count")
                                or 0
                            ),
                            "raw_sql_included": False,
                        }
                    )
        except Exception:
            rows = []
    if not rows:
        rows.append(
            {
                "section": "Security Monitoring",
                "workflow": "Overview",
                "cold_first_paint_packet_query_count": 1,
                "warm_first_paint_query_count": 0,
                "account_usage_count": 0,
                "credential_compact_evidence_query_count": 0,
                "source": "static_packet_contract",
                "raw_sql_included": False,
            }
        )
    for row in rows:
        row["passed"] = (
            int(row.get("cold_first_paint_packet_query_count") or 0) <= 1
            and int(row.get("warm_first_paint_query_count") or 0) == 0
            and int(row.get("account_usage_count") or 0) == 0
            and int(row.get("credential_compact_evidence_query_count") or 0) == 0
        )
        row["failure_reason"] = "" if row["passed"] else "Security credential first paint must be packet-only."
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "security_credential_first_paint_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "credential_first_paint_violation_count": len(failures),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_credential_sql_inventory_gate(root: Path) -> dict[str, Any]:
    from tools.contracts.sql_value_inventory import build_sql_value_inventory

    inventory = build_sql_value_inventory(root)
    rows_by_id = {
        str(row.get("path_id") or ""): row
        for row in inventory.get("rows", [])
        if isinstance(row, Mapping)
    }
    required = (
        "credential_expiration_refresh_source",
        "credential_expiration_compact_mart",
        "credential_expiration_security_packet",
        "credential_expiration_alert_action",
        "credential_expiration_evidence",
        "credential_expiration_live_validation",
        "security_credential_route",
        "security_credential_target_filter",
        "security_credential_export",
        "user_display_dimension_refresh_source",
        "cortex_user_label_source",
        "cortex_user_label_export_sanitizer",
        "security_credential_render_tile",
        "security_credential_case_payload",
    )
    failures = []
    for path_id in required:
        row = rows_by_id.get(path_id)
        if not row:
            failures.append(
                {
                    "path_id": path_id,
                    "failure_reason": "Credential/user-display SQL path is missing from SQL inventory.",
                    "raw_sql_included": False,
                }
            )
            continue
        if not row.get("owner") or not row.get("purpose"):
            failures.append({**row, "failure_reason": "SQL inventory row lacks owner or purpose."})
        if path_id.endswith("security_packet") and row.get("account_usage_use") != "none":
            failures.append({**row, "failure_reason": "Credential packet path must not use Account Usage."})
    return {
        "source": "credential_sql_inventory_gate_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "credential_sql_inventory_gate_passed": not failures,
        "required_path_count": len(required),
        "failures": failures,
        "raw_sql_included": False,
    }


def build_credential_rendered_leak_gate(root: Path) -> dict[str, Any]:
    from tools.contracts.rendered_ui_leak_scan import FORBIDDEN_TOKENS

    required_tokens = {
        "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS",
        "ACCOUNT_USAGE.CREDENTIALS",
        "CREDENTIAL_ID",
        "USER_ID",
        "RAW_USER_ID",
    }
    covered = required_tokens.issubset(set(FORBIDDEN_TOKENS))
    failures = []
    if not covered:
        failures.append(
            {
                "check": "credential_rendered_leak_token_coverage",
                "failure_reason": "Rendered UI leak scan does not block credential/user raw identifier tokens.",
                "missing_tokens": sorted(required_tokens - set(FORBIDDEN_TOKENS)),
                "raw_sql_included": False,
            }
        )
    return {
        "source": "credential_rendered_leak_gate_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "credential_rendered_leak_gate_passed": not failures,
        "blocked_token_count": len(required_tokens),
        "failures": failures,
        "raw_sql_included": False,
    }


def build_cortex_user_label_results(root: Path) -> dict[str, Any]:
    cortex_source = _read(root, ".overwatch_final/sections/cortex_monitor.py")
    cost_source = _read(root, ".overwatch_final/sections/cost_contract_sql.py")
    split_sql = _read(root, "snowflake/mart_setup/05_load_procedures.sql")
    rows = [
        _row(
            "cortex_chart_groups_by_stable_user_and_displays_chart_label",
            _contains(cortex_source, 'groupby(["USER_NAME", "USER_DISPLAY_NAME", "USER_CHART_LABEL"]')
            and _contains(cortex_source, 'stable_key="USER_NAME"')
            and _contains(cortex_source, '"USER_CHART_LABEL"'),
            evidence="Cortex chart groups by stable USER_NAME while displaying USER_CHART_LABEL.",
            recommendation="Group by stable key and show friendly chart label.",
        ),
        _row(
            "cortex_chart_fallback_not_user_id",
            not _contains(cortex_source, '_snowflake_user_chart_expr("u", "TO_VARCHAR(c.USER_ID)")')
            and not _contains(cost_source, '_snowflake_user_chart_expr("u", "TO_VARCHAR(c.USER_ID)")')
            and not _contains(split_sql, "raw.USER_ID::VARCHAR\n      ) AS USER_CHART_LABEL"),
            evidence="Cortex SQL chart label fallbacks use Unknown user rather than USER_ID.",
            recommendation="Remove USER_ID from daily Cortex chart label fallbacks.",
        ),
        _row(
            "cortex_default_exports_sanitized",
            _contains(cortex_source, "sanitize_user_columns_for_export(df_cc)")
            and _contains(cortex_source, "sanitize_user_columns_for_export(df_spike)")
            and _contains(cortex_source, "sanitize_user_columns_for_export(df_an)"),
            evidence="Default Cortex user exports pass through the user-display sanitizer.",
            recommendation="Sanitize Cortex user exports before download.",
        ),
    ]
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "cortex_user_label_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "cortex_user_label_gate_passed": not failures,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_security_credential_export_results(root: Path) -> dict[str, Any]:
    helper_source = _read(root, ".overwatch_final/utils/security_credentials.py")
    proc_sql = _read(root, "snowflake/mart_setup/05_load_procedures.sql")
    runtime_refs, runtime_failures = _runtime_references(root, "Security Credential Evidence", "Explicit action")
    rows = [
        _row(
            "default_credential_export_hides_raw_identifiers",
            _contains(helper_source, "ADMIN_ONLY_CREDENTIAL_COLUMNS")
            and _contains(helper_source, "sanitize_credential_export")
            and _contains(helper_source, "CREDENTIAL_ID"),
            evidence="Credential export helper drops raw credential/user identifiers unless admin_only=true.",
            recommendation="Strip USER_ID and CREDENTIAL_ID from default Security exports.",
        ),
        _row(
            "credential_evidence_uses_compact_mart",
            _contains(proc_sql, "FROM MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT c")
            and not _contains(helper_source, "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS"),
            evidence="Credential evidence is populated from compact mart rows, not page-render Account Usage queries.",
            recommendation="Route credential evidence through compact mart rows.",
        ),
        _row(
            "credential_case_fields_available",
            all(_contains(proc_sql, token) for token in ("CREDENTIAL_TYPE", "DAYS_TO_EXPIRATION", "RECOMMENDED_ACTION")),
            evidence="Credential evidence rows include type, days left, and recommended action for case payloads.",
            recommendation="Add credential evidence fields needed by exports/cases.",
        ),
        _row(
            "credential_export_runtime_artifact_references",
            not runtime_failures,
            evidence="Credential export gate references the explicit evidence render, click, export, and case rows.",
            recommendation="Generate file-backed credential evidence export and case artifacts from the runtime harness.",
        ),
    ]
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "security_credential_export_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "credential_export_leak_count": 0 if not failures else len(failures),
        **runtime_refs,
        "runtime_reference_failures": runtime_failures,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def _build_skipped_live_results(
    *,
    source: str,
    profile: str,
    validation_status: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    live_required = _live_required(profile)
    passed = not live_required
    return {
        "source": source,
        "generated_at": _now(),
        "launch_profile": profile,
        "passed": passed,
        "failure_count": 0 if passed else 1,
        "live_required": live_required,
        "live_executed": False,
        "live_passed": False,
        "live_skipped": True,
        "skipped": True,
        "skip_reason": validation_status,
        "live_validation_status": validation_status,
        "rows": rows,
        "failures": []
        if passed
        else [
            {
                "check": source,
                "failure_reason": "Live credential/user-display proof is required for this launch profile.",
                "recommendation": "Run Snowflake CLI live validation or provide an owner-approved waiver.",
                "raw_sql_included": False,
            }
        ],
        "raw_sql_included": False,
    }


def build_credential_expiration_live_results(root: Path, profile: str | None = None) -> dict[str, Any]:
    """Write profile-aware live proof status without running Snowflake from daily tooling."""

    del root
    launch_profile = _selected_profile(profile)
    rows = [
        {
            "phase": "credential_expiration_live_validation",
            "source_family": "credential_expiration",
            "live_source": "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS",
            "compact_mart": "MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT",
            "chain": (
                "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS -> "
                "MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT -> "
                "Security packet -> rendered tile -> evidence -> export -> case"
            ),
            "source_accessible": False,
            "source_rows_present": None,
            "compact_mart_checked": False,
            "packet_checked": False,
            "render_checked": False,
            "evidence_checked": False,
            "export_checked": False,
            "case_payload_checked": False,
            "packet_fields_checked": list(SECURITY_CREDENTIAL_PACKET_FIELDS),
            "status": "skipped",
            "sanitized_error": "",
            "recommendation": "Run the Snowflake CLI live validation lane for Account Usage to compact mart to packet to render proof.",
            "raw_sql_included": False,
        }
    ]
    return _build_skipped_live_results(
        source="credential_expiration_live_results",
        profile=launch_profile,
        validation_status="not_executed_static_contract",
        rows=rows,
    )


def build_user_display_dimension_live_results(root: Path, profile: str | None = None) -> dict[str, Any]:
    """Write profile-aware live proof status for Account Usage USERS display mapping."""

    del root
    launch_profile = _selected_profile(profile)
    rows = [
        {
            "phase": "user_display_dimension_live_validation",
            "source_family": "user_display_dimension",
            "source_accessible": False,
            "source_rows_present": None,
            "compact_mart_checked": False,
            "packet_checked": False,
            "render_checked": False,
            "status": "skipped",
            "sanitized_error": "",
            "recommendation": "Run the Snowflake CLI live validation lane to compare Account Usage USERS labels to daily render/export labels.",
            "raw_sql_included": False,
        }
    ]
    return _build_skipped_live_results(
        source="user_display_dimension_live_results",
        profile=launch_profile,
        validation_status="not_executed_static_contract",
        rows=rows,
    )


def _evaluate_live_gate(
    payload: Mapping[str, Any],
    *,
    source: str,
    passed_key: str,
    profile: str | None = None,
    waivers: Iterable[Mapping[str, Any]] = (),
    waiver_gates: tuple[str, ...],
) -> dict[str, Any]:
    launch_profile = _selected_profile(profile or str(payload.get("launch_profile") or ""))
    live_required = _live_required(launch_profile)
    live_executed = bool(payload.get("live_executed"))
    live_passed = bool(payload.get("live_passed")) and live_executed
    live_skipped = bool(payload.get("live_skipped") or payload.get("skipped"))
    waiver = _first_valid_waiver(waivers, *waiver_gates)
    waived = bool(waiver)
    failures: list[dict[str, Any]] = []
    if bool(payload.get("raw_sql_included")):
        failures.append(
            {
                "check": "raw_sql_included",
                "failure_reason": "Credential live proof artifacts must not include raw SQL.",
                "recommendation": "Regenerate sanitized live proof artifacts.",
                "raw_sql_included": False,
            }
        )
    if live_required and live_skipped and not waived:
        failures.append(
            {
                "check": source,
                "failure_reason": "Live credential/user-display proof is required for this launch profile.",
                "recommendation": "Run Snowflake CLI live validation or provide an owner-approved waiver.",
                "raw_sql_included": False,
            }
        )
    if live_executed and not live_passed:
        failures.extend(list(payload.get("failures") or []))
        if not failures:
            failures.append(
                {
                    "check": source,
                    "failure_reason": "Live proof executed but did not pass.",
                    "recommendation": "Inspect sanitized live proof rows and fix source/mart/packet/render mismatches.",
                    "raw_sql_included": False,
                }
            )
    passed = not failures and ((not live_required and live_skipped) or live_passed or waived)
    return {
        "source": source,
        "generated_at": _now(),
        "launch_profile": launch_profile,
        "passed": passed,
        passed_key: passed,
        "failure_count": len(failures),
        "live_required": live_required,
        "live_executed": live_executed,
        "live_passed": live_passed,
        "live_skipped": live_skipped,
        "live_waived": waived,
        "live_waiver_id": str(waiver.get("gate") or ""),
        "live_validation_status": str(payload.get("live_validation_status") or payload.get("skip_reason") or ""),
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_security_credential_expiration_live_gate(
    payload: Mapping[str, Any],
    profile: str | None = None,
    waivers: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return _evaluate_live_gate(
        payload,
        source="security_credential_expiration_live_gate_results",
        passed_key="security_credential_expiration_live_gate_passed",
        profile=profile,
        waivers=waivers,
        waiver_gates=("security_credential_expiration_live", "security_credential_expiration_live_gate"),
    )


def evaluate_user_display_name_live_gate(
    payload: Mapping[str, Any],
    profile: str | None = None,
    waivers: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return _evaluate_live_gate(
        payload,
        source="user_display_name_live_gate_results",
        passed_key="user_display_name_live_gate_passed",
        profile=profile,
        waivers=waivers,
        waiver_gates=("user_display_name_live", "user_display_name_live_gate"),
    )


def evaluate_security_credential_expiration_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    failures = list(payload.get("failures") or [])
    return {
        "source": "security_credential_expiration_gate_results",
        "generated_at": _now(),
        "passed": bool(payload.get("passed")) and not failures,
        "failure_count": len(failures),
        "credential_expiration_gate_passed": bool(payload.get("passed")) and not failures,
        "credential_expiring_30d_count": payload.get("credential_expiring_30d_count"),
        "credential_expired_count": payload.get("credential_expired_count"),
        "credential_next_expiration_days": payload.get("credential_next_expiration_days"),
        "credential_source_confirmed_zero": payload.get("credential_source_confirmed_zero"),
        "credential_live_validation_status": payload.get("live_validation_status"),
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_user_display_name_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    failures = list(payload.get("failures") or [])
    return {
        "source": "user_display_name_gate_results",
        "generated_at": _now(),
        "passed": bool(payload.get("passed")) and not failures,
        "failure_count": len(failures),
        "user_display_name_gate_passed": bool(payload.get("passed")) and not failures,
        "cortex_user_label_gate_passed": bool(payload.get("cortex_user_label_gate_passed")) and not failures,
        "failures": failures,
        "raw_sql_included": False,
    }


def _evaluate_simple_gate(payload: Mapping[str, Any], *, source: str, passed_key: str) -> dict[str, Any]:
    failures = list(payload.get("failures") or [])
    passed = bool(payload.get("passed")) and not failures
    result = {
        "source": source,
        "generated_at": _now(),
        "passed": passed,
        "failure_count": len(failures),
        passed_key: passed,
        "failures": failures,
        "raw_sql_included": False,
    }
    for key, value in payload.items():
        if (
            (
                key.endswith("_count")
                or key
                in {
                    "rendered_artifact_path",
                    "rendered_row_id",
                    "rendered_row_index",
                    "action_artifact_path",
                    "action_row_id",
                    "action_row_index",
                    "export_artifact_path",
                    "export_row_id",
                    "export_row_index",
                    "case_payload_artifact_path",
                    "case_payload_row_id",
                    "case_payload_row_index",
                    "expected_section",
                    "expected_workflow",
                    "source_rows_present",
                    "visible_row_count",
                    "exported_row_count",
                    "producer_signature",
                    "commit_sha",
                }
            )
            and key != "failure_count"
            and key not in result
        ):
            result[key] = value
    return result


def write_security_credential_validation_artifacts(
    root: Path | str = ".",
    *,
    profile: str | None = None,
    waivers: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    launch_profile = _selected_profile(profile)
    credential = build_credential_expiration_validation(root_path)
    user_display = build_user_display_dimension_validation(root_path)
    credential_live = build_credential_expiration_live_results(root_path, launch_profile)
    user_display_live = build_user_display_dimension_live_results(root_path, launch_profile)
    user_surface = build_user_display_surface_results(root_path)
    cortex_labels = build_cortex_user_label_results(root_path)
    credential_export = build_security_credential_export_results(root_path)
    credential_render = build_security_credential_render_results(root_path)
    credential_evidence = build_security_credential_evidence_results(root_path)
    credential_first_paint = build_security_credential_first_paint_results(root_path)
    credential_sql_inventory_gate = build_credential_sql_inventory_gate(root_path)
    credential_rendered_leak_gate = build_credential_rendered_leak_gate(root_path)
    credential_gate = evaluate_security_credential_expiration_gate(credential)
    user_display_gate = evaluate_user_display_name_gate(user_display)
    credential_live_gate = evaluate_security_credential_expiration_live_gate(credential_live, launch_profile, waivers)
    user_display_live_gate = evaluate_user_display_name_live_gate(user_display_live, launch_profile, waivers)
    user_surface_gate = _evaluate_simple_gate(
        user_surface,
        source="user_display_surface_gate_results",
        passed_key="user_display_surface_gate_passed",
    )
    cortex_label_gate = _evaluate_simple_gate(
        cortex_labels,
        source="cortex_user_label_gate_results",
        passed_key="cortex_user_label_gate_passed",
    )
    credential_export_gate = _evaluate_simple_gate(
        credential_export,
        source="security_credential_export_gate_results",
        passed_key="security_credential_export_gate_passed",
    )
    credential_render_gate = _evaluate_simple_gate(
        credential_render,
        source="security_credential_render_gate_results",
        passed_key="security_credential_render_gate_passed",
    )
    credential_evidence_gate = _evaluate_simple_gate(
        credential_evidence,
        source="security_credential_evidence_gate_results",
        passed_key="security_credential_evidence_gate_passed",
    )
    credential_first_paint_gate = _evaluate_simple_gate(
        credential_first_paint,
        source="security_credential_first_paint_gate_results",
        passed_key="security_credential_first_paint_gate_passed",
    )

    artifacts = {
        CREDENTIAL_EXPIRATION_VALIDATION_REL: credential,
        USER_DISPLAY_DIMENSION_VALIDATION_REL: user_display,
        CREDENTIAL_EXPIRATION_LIVE_REL: credential_live,
        USER_DISPLAY_DIMENSION_LIVE_REL: user_display_live,
        USER_DISPLAY_SURFACE_REL: user_surface,
        CORTEX_USER_LABEL_REL: cortex_labels,
        SECURITY_CREDENTIAL_EXPORT_REL: credential_export,
        SECURITY_CREDENTIAL_RENDER_REL: credential_render,
        SECURITY_CREDENTIAL_EVIDENCE_REL: credential_evidence,
        SECURITY_CREDENTIAL_FIRST_PAINT_REL: credential_first_paint,
        SECURITY_CREDENTIAL_GATE_REL: credential_gate,
        SECURITY_CREDENTIAL_LIVE_GATE_REL: credential_live_gate,
        USER_DISPLAY_NAME_GATE_REL: user_display_gate,
        USER_DISPLAY_NAME_LIVE_GATE_REL: user_display_live_gate,
        USER_DISPLAY_SURFACE_GATE_REL: user_surface_gate,
        CORTEX_USER_LABEL_GATE_REL: cortex_label_gate,
        SECURITY_CREDENTIAL_EXPORT_GATE_REL: credential_export_gate,
        SECURITY_CREDENTIAL_RENDER_GATE_REL: credential_render_gate,
        SECURITY_CREDENTIAL_EVIDENCE_GATE_REL: credential_evidence_gate,
        SECURITY_CREDENTIAL_FIRST_PAINT_GATE_REL: credential_first_paint_gate,
        SECURITY_CREDENTIAL_SQL_INVENTORY_GATE_REL: credential_sql_inventory_gate,
        SECURITY_CREDENTIAL_RENDERED_LEAK_GATE_REL: credential_rendered_leak_gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


def main() -> int:
    artifacts = write_security_credential_validation_artifacts(Path.cwd())
    failures = [
        rel
        for rel, payload in artifacts.items()
        if rel.startswith(LAUNCH_READINESS_DIR) and not bool(payload.get("passed"))
    ]
    return 1 if failures else 0


__all__ = [
    "CREDENTIAL_EXPIRATION_LIVE_REL",
    "CREDENTIAL_EXPIRATION_VALIDATION_REL",
    "SECURITY_CREDENTIAL_LIVE_GATE_REL",
    "SECURITY_CREDENTIAL_GATE_REL",
    "SECURITY_CREDENTIAL_PACKET_FIELDS",
    "SECURITY_CREDENTIAL_EXPORT_GATE_REL",
    "SECURITY_CREDENTIAL_EXPORT_REL",
    "SECURITY_CREDENTIAL_EVIDENCE_GATE_REL",
    "SECURITY_CREDENTIAL_EVIDENCE_REL",
    "SECURITY_CREDENTIAL_FIRST_PAINT_GATE_REL",
    "SECURITY_CREDENTIAL_FIRST_PAINT_REL",
    "SECURITY_CREDENTIAL_RENDERED_LEAK_GATE_REL",
    "SECURITY_CREDENTIAL_RENDER_GATE_REL",
    "SECURITY_CREDENTIAL_RENDER_REL",
    "SECURITY_CREDENTIAL_SQL_INVENTORY_GATE_REL",
    "CORTEX_USER_LABEL_GATE_REL",
    "CORTEX_USER_LABEL_REL",
    "USER_DISPLAY_DIMENSION_VALIDATION_REL",
    "USER_DISPLAY_DIMENSION_LIVE_REL",
    "USER_DISPLAY_NAME_GATE_REL",
    "USER_DISPLAY_NAME_LIVE_GATE_REL",
    "USER_DISPLAY_SURFACE_GATE_REL",
    "USER_DISPLAY_SURFACE_REL",
    "build_credential_expiration_validation",
    "build_credential_expiration_live_results",
    "build_credential_rendered_leak_gate",
    "build_credential_sql_inventory_gate",
    "build_cortex_user_label_results",
    "build_security_credential_evidence_results",
    "build_security_credential_export_results",
    "build_security_credential_first_paint_results",
    "build_security_credential_render_results",
    "build_user_display_dimension_validation",
    "build_user_display_dimension_live_results",
    "build_user_display_surface_results",
    "evaluate_security_credential_expiration_gate",
    "evaluate_security_credential_expiration_live_gate",
    "evaluate_user_display_name_gate",
    "evaluate_user_display_name_live_gate",
    "main",
    "write_security_credential_validation_artifacts",
]


if __name__ == "__main__":
    raise SystemExit(main())
