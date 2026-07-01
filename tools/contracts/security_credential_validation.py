"""Static release proof for credential-expiration and user-display chains."""

from __future__ import annotations

from datetime import UTC, datetime
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

SECURITY_CREDENTIAL_PACKET_FIELDS = (
    "SECURITY_CREDENTIALS_EXPIRING_30D_COUNT",
    "SECURITY_CREDENTIALS_EXPIRING_7D_COUNT",
    "SECURITY_CREDENTIALS_EXPIRED_COUNT",
    "SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS",
    "SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER",
    "SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE",
    "SECURITY_CREDENTIAL_EXPIRATION_STATUS",
    "SECURITY_CREDENTIAL_EXPIRATION_FINDINGS",
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
            _contains(cortex_source, 'render_ranked_bar_chart(user_agg, "USER_CHART_LABEL"')
            and _contains(cortex_source, "USER_DISPLAY_NAME"),
            evidence="Cortex user chart uses USER_CHART_LABEL and tables use USER_DISPLAY_NAME.",
            recommendation="Use USER_CHART_LABEL for daily Cortex user charts and USER_DISPLAY_NAME for tables.",
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
    stable_user_key_present: bool,
    user_id_visible: bool,
    user_chart_label_used: bool,
    user_display_name_used: bool,
    admin_only: bool = False,
    failure_reason: str = "",
) -> dict[str, Any]:
    passed = not user_id_visible and (user_chart_label_used or user_display_name_used or admin_only)
    if failure_reason:
        passed = False
    return {
        "surface": surface,
        "section": section,
        "chart_or_table": chart_or_table,
        "visible_user_column": visible_user_column,
        "stable_user_key_present": bool(stable_user_key_present),
        "user_id_visible": bool(user_id_visible),
        "user_chart_label_used": bool(user_chart_label_used),
        "user_display_name_used": bool(user_display_name_used),
        "admin_only": bool(admin_only),
        "passed": bool(passed),
        "failure_reason": "" if passed else failure_reason or "Daily user surface must use friendly labels and hide USER_ID.",
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
            stable_user_key_present=_contains(cortex_source, 'groupby(["USER_NAME", "USER_DISPLAY_NAME", "USER_CHART_LABEL"]'),
            user_id_visible=_contains(cortex_source, 'render_ranked_bar_chart(user_agg, "USER_ID"'),
            user_chart_label_used=_contains(cortex_source, 'render_ranked_bar_chart(user_agg, "USER_CHART_LABEL"'),
            user_display_name_used=_contains(cortex_source, '"USER_DISPLAY_NAME"'),
        ),
        _surface_row(
            surface="Cortex Usage",
            section="Cost & Contract",
            chart_or_table="Cortex user default export",
            visible_user_column="USER_DISPLAY_NAME",
            stable_user_key_present=True,
            user_id_visible=not _contains(cortex_source, "sanitize_user_columns_for_export(df_cc)"),
            user_chart_label_used=_contains(cortex_source, "USER_CHART_LABEL"),
            user_display_name_used=_contains(cortex_source, "USER_DISPLAY_NAME"),
        ),
        _surface_row(
            surface="Cost Workbench",
            section="Cost & Contract",
            chart_or_table="Top Cortex user",
            visible_user_column="user_label",
            stable_user_key_present=_contains(cost_source, "stable_user_name"),
            user_id_visible=_contains(cost_source, '_snowflake_user_chart_expr("u", "TO_VARCHAR(c.USER_ID)")'),
            user_chart_label_used=_contains(cost_source, "_snowflake_user_chart_expr"),
            user_display_name_used=False,
        ),
        _surface_row(
            surface="Security credential evidence",
            section="Security Monitoring",
            chart_or_table="Credential expiration export",
            visible_user_column="USER_DISPLAY_NAME",
            stable_user_key_present=_contains(security_helper, "USER_ID"),
            user_id_visible=not _contains(security_helper, "sanitize_user_columns_for_export"),
            user_chart_label_used=_contains(security_helper, "USER_CHART_LABEL"),
            user_display_name_used=_contains(security_helper, "USER_DISPLAY_NAME"),
        ),
        _surface_row(
            surface="User display helper",
            section="Shared",
            chart_or_table="Daily label fallback",
            visible_user_column="USER_CHART_LABEL",
            stable_user_key_present=True,
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


def build_cortex_user_label_results(root: Path) -> dict[str, Any]:
    cortex_source = _read(root, ".overwatch_final/sections/cortex_monitor.py")
    cost_source = _read(root, ".overwatch_final/sections/cost_contract_sql.py")
    split_sql = _read(root, "snowflake/mart_setup/05_load_procedures.sql")
    rows = [
        _row(
            "cortex_chart_groups_by_stable_user_and_displays_chart_label",
            _contains(cortex_source, 'groupby(["USER_NAME", "USER_DISPLAY_NAME", "USER_CHART_LABEL"]')
            and _contains(cortex_source, 'render_ranked_bar_chart(user_agg, "USER_CHART_LABEL"'),
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
    ]
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "security_credential_export_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "credential_export_leak_count": 0 if not failures else len(failures),
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
            "source_accessible": False,
            "source_rows_present": None,
            "compact_mart_checked": False,
            "packet_checked": False,
            "render_checked": False,
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
        if key.endswith("_count") and key != "failure_count" and key not in result:
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

    artifacts = {
        CREDENTIAL_EXPIRATION_VALIDATION_REL: credential,
        USER_DISPLAY_DIMENSION_VALIDATION_REL: user_display,
        CREDENTIAL_EXPIRATION_LIVE_REL: credential_live,
        USER_DISPLAY_DIMENSION_LIVE_REL: user_display_live,
        USER_DISPLAY_SURFACE_REL: user_surface,
        CORTEX_USER_LABEL_REL: cortex_labels,
        SECURITY_CREDENTIAL_EXPORT_REL: credential_export,
        SECURITY_CREDENTIAL_GATE_REL: credential_gate,
        SECURITY_CREDENTIAL_LIVE_GATE_REL: credential_live_gate,
        USER_DISPLAY_NAME_GATE_REL: user_display_gate,
        USER_DISPLAY_NAME_LIVE_GATE_REL: user_display_live_gate,
        USER_DISPLAY_SURFACE_GATE_REL: user_surface_gate,
        CORTEX_USER_LABEL_GATE_REL: cortex_label_gate,
        SECURITY_CREDENTIAL_EXPORT_GATE_REL: credential_export_gate,
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
    "build_cortex_user_label_results",
    "build_security_credential_export_results",
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
