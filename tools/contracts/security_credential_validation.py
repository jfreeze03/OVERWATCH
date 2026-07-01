"""Static release proof for credential-expiration and user-display chains."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


SNOWFLAKE_VALIDATION_DIR = "artifacts/snowflake_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

CREDENTIAL_EXPIRATION_VALIDATION_REL = (
    f"{SNOWFLAKE_VALIDATION_DIR}/credential_expiration_validation_results.json"
)
USER_DISPLAY_DIMENSION_VALIDATION_REL = (
    f"{SNOWFLAKE_VALIDATION_DIR}/user_display_dimension_validation_results.json"
)
SECURITY_CREDENTIAL_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/security_credential_expiration_gate_results.json"
)
USER_DISPLAY_NAME_GATE_REL = f"{LAUNCH_READINESS_DIR}/user_display_name_gate_results.json"

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
            and _contains(helper_source, "admin_only"),
            evidence="User export helper strips USER_ID columns unless admin_only=true.",
            recommendation="Hide USER_ID from default daily exports.",
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


def write_security_credential_validation_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    credential = build_credential_expiration_validation(root_path)
    user_display = build_user_display_dimension_validation(root_path)
    credential_gate = evaluate_security_credential_expiration_gate(credential)
    user_display_gate = evaluate_user_display_name_gate(user_display)

    artifacts = {
        CREDENTIAL_EXPIRATION_VALIDATION_REL: credential,
        USER_DISPLAY_DIMENSION_VALIDATION_REL: user_display,
        SECURITY_CREDENTIAL_GATE_REL: credential_gate,
        USER_DISPLAY_NAME_GATE_REL: user_display_gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "CREDENTIAL_EXPIRATION_VALIDATION_REL",
    "SECURITY_CREDENTIAL_GATE_REL",
    "SECURITY_CREDENTIAL_PACKET_FIELDS",
    "USER_DISPLAY_DIMENSION_VALIDATION_REL",
    "USER_DISPLAY_NAME_GATE_REL",
    "build_credential_expiration_validation",
    "build_user_display_dimension_validation",
    "evaluate_security_credential_expiration_gate",
    "evaluate_user_display_name_gate",
    "write_security_credential_validation_artifacts",
]
