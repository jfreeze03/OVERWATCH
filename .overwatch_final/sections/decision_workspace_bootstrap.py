"""One-shot bootstrap flow for Decision Workspace command summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import streamlit as st

from sections.base import lazy_util
from sections.decision_workspace_scope import active_decision_window_days
from sections.decision_workspace_setup_health import record_decision_bootstrap_health
from sections.section_command_contracts import CANONICAL_COMMAND_BRIEF_SECTIONS
from utils.performance import DECISION_BOOTSTRAP_QUERY_BUDGET, query_budget_context
from runtime_state import ACTIVE_COMPANY, GLOBAL_ENVIRONMENT


BOOTSTRAP_REQUEST_KEY = "_overwatch_decision_bootstrap_requested"
BOOTSTRAP_SUCCESS_KEY = "_overwatch_decision_bootstrap_success"
BOOTSTRAP_FAILURE_KEY = "_overwatch_decision_bootstrap_failure"
BOOTSTRAP_PROCEDURE = "SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS"
BOOTSTRAP_PROCEDURE_FALLBACKS = (
    BOOTSTRAP_PROCEDURE,
    "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL",
    "SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS",
)
BOOTSTRAP_SETUP_MESSAGE = (
    "Decision summaries are not initialized. Ask an administrator to deploy the complete "
    "OVERWATCH mart setup and initialize the Decision summary marts."
)
BOOTSTRAP_SUCCESS_MESSAGE = "Decision summaries initialized. Refreshing the current command brief."
BOOTSTRAP_DEGRADED_MESSAGE = (
    "Decision summaries initialized for this section with setup warnings. Review Setup Health in Settings."
)
DECISION_CURRENT_TABLE = "MART_SECTION_DECISION_CURRENT"
DEFAULT_PACKET_BYTE_LIMIT = 100_000


SECTION_FORCE_REFRESH_KEYS = {
    "Executive Landing": "_executive_landing_command_brief_force_refresh",
    "DBA Control Room": "dba_control_room_command_brief_force_refresh",
    "Alert Center": "alert_center_command_brief_force_refresh",
    "Cost & Contract": "cost_contract_command_brief_force_refresh",
    "Workload Operations": "workload_operations_command_brief_force_refresh",
    "Security Monitoring": "security_posture_command_brief_force_refresh",
}


@dataclass(frozen=True)
class DecisionBootstrapValidation:
    ok: bool
    status: str = "FAILED"
    global_status: str = "FAILED"
    selected_scope_status: str = "FAILED"
    current_section_status: str = "FAILED"
    global_ok: bool = False
    selected_scope_ok: bool = False
    current_section_ok: bool = False
    requested_company: str = ""
    requested_environment: str = ""
    requested_window_days: int = 0
    resolved_company: str = ""
    resolved_environment: str = ""
    resolved_window_days: int = 0
    current_section: str = ""
    current_section_state: str = ""
    current_section_missing_metrics: bool = False
    current_section_missing_sources: int = 0
    current_section_stale: bool = False
    current_section_packet_bytes: int | None = None
    current_section_packet_id: str = ""
    current_packet_count: int = 0
    sections_present: tuple[str, ...] = ()
    missing_sections: tuple[str, ...] = ()
    duplicate_current_keys: int = 0
    stale_sections: tuple[str, ...] = ()
    data_gap_sections: tuple[str, ...] = ()
    missing_metric_sections: tuple[str, ...] = ()
    degraded_sections: tuple[str, ...] = ()
    invalid_sections: tuple[str, ...] = ()
    warning_sections: tuple[str, ...] = ()
    max_packet_bytes: int | None = None
    message: str = ""
    admin_detail: str = ""
    validated_sections: tuple[str, ...] = ()
    validated_packet_keys: tuple[tuple[str, str, str, int], ...] = ()


@dataclass(frozen=True)
class BootstrapProcedureResult:
    procedure_name: str
    fallback_used: bool = False
    admin_detail: str = ""


class BootstrapProcedureFailure(RuntimeError):
    def __init__(self, admin_detail: str):
        super().__init__(admin_detail)
        self.admin_detail = admin_detail


def _is_fixture_or_invalid_last_good(value: object) -> bool:
    raw = getattr(value, "raw_payload", None)
    return not hasattr(value, "section") or (isinstance(raw, Mapping) and raw.get("fixture_mode") is True)


def _norm_token(value: object, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _norm_scope(value: object, default: str = "ALL") -> str:
    text = _norm_token(value, default)
    upper = text.upper()
    if upper in {"", "ALL ENVIRONMENTS", "GLOBAL"}:
        return "ALL"
    return text


def _packet_key_tuple(section: object, company: object, environment: object, window_days: object) -> tuple[str, str, str, int]:
    return (
        _norm_token(section),
        _norm_scope(company),
        _norm_scope(environment),
        _int_value(window_days, 0),
    )


def _parse_last_good_cache_key(key: str) -> tuple[str, str, str, int] | None:
    parts = str(key or "").split("::")
    if len(parts) != 6:
        return None
    prefix, section, company, environment, window_days, suffix = parts
    if prefix != "section_command_brief" or suffix != "last_good":
        return None
    return _packet_key_tuple(section, company, environment, window_days)


def _last_good_matches_validated_packet_key(
    cache_key: str,
    validated_packet_keys: tuple[tuple[str, str, str, int], ...],
) -> bool:
    parsed = _parse_last_good_cache_key(cache_key)
    if parsed is None or not validated_packet_keys:
        return False
    normalized = {
        (section.lower(), company.upper(), environment.upper(), int(window_days))
        for section, company, environment, window_days in validated_packet_keys
    }
    return (parsed[0].lower(), parsed[1].upper(), parsed[2].upper(), int(parsed[3])) in normalized


def _clear_command_brief_caches(
    *,
    clear_last_good: bool = False,
    validated_packet_keys: tuple[tuple[str, str, str, int], ...] = (),
) -> None:
    for key in list(st.session_state.keys()):
        text = str(key)
        if not text.startswith("section_command_brief::"):
            continue
        if text.endswith("::last_good"):
            value = st.session_state.get(key)
            if _is_fixture_or_invalid_last_good(value) or (
                clear_last_good and _last_good_matches_validated_packet_key(text, validated_packet_keys)
            ):
                st.session_state.pop(key, None)
            continue
        st.session_state.pop(key, None)
    st.session_state.pop("section_command_brief_last_telemetry", None)
    st.session_state.pop("section_command_brief_telemetry", None)


def _force_current_section_refresh(current_section: str | None) -> None:
    key = SECTION_FORCE_REFRESH_KEYS.get(str(current_section or ""))
    if key:
        st.session_state[key] = True


def _active_validation_scope() -> tuple[str, str, int]:
    company = _norm_scope(st.session_state.get(ACTIVE_COMPANY, "ALL"))
    environment = _norm_scope(st.session_state.get(GLOBAL_ENVIRONMENT, "ALL"))
    try:
        window_days = int(active_decision_window_days(default=7))
    except Exception:
        window_days = 7
    return company, environment, max(int(window_days or 7), 1)


def _clean_bootstrap_failure_message(exc: object | None = None) -> str:
    """Return a daily-UI-safe bootstrap failure message without raw SQL details."""
    if exc is None:
        return BOOTSTRAP_SETUP_MESSAGE
    text = str(exc or "")
    lowered = text.lower()
    if any(
        token in lowered
        for token in (
            "unknown function",
            "does not exist",
            "not authorized",
            "insufficient privileges",
            "sql compilation error",
            "no visible decision summary",
            "no candidate bootstrap procedure",
        )
    ):
        return BOOTSTRAP_SETUP_MESSAGE
    return "Decision summaries could not be initialized. Ask an administrator to review Decision summary setup health."


def _candidate_procedure_available(session: object, procedure_name: str) -> bool:
    """Return True when a bootstrap/refresh procedure is visible in the current schema."""
    rows = session.sql(f"SHOW PROCEDURES LIKE '{procedure_name}'").collect()
    return bool(rows)


def _row_to_dict(row: object) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {str(key).upper(): value for key, value in row.items()}
    if hasattr(row, "as_dict"):
        try:
            return {str(key).upper(): value for key, value in row.as_dict().items()}
        except Exception:
            pass
    if hasattr(row, "_asdict"):
        try:
            return {str(key).upper(): value for key, value in row._asdict().items()}
        except Exception:
            pass
    return {}


def _int_value(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def _float_value(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _run_call(session: object, procedure_name: str) -> None:
    session.sql(f"CALL {procedure_name}();").collect()


def detect_decision_setup_version(session: object) -> str | None:
    """Return the configured Decision setup procedure when the marker is visible."""
    try:
        rows = session.sql(
            """
SELECT MAX(NULLIF(TRIM(SETTING_VALUE), '')) AS PROCEDURE_NAME
FROM OVERWATCH_SETTINGS
WHERE UPPER(SETTING_NAME) IN (
  'DECISION_BRIEF_BOOTSTRAP_PROCEDURE',
  'DECISION_BRIEF_REFRESH_PROCEDURE'
)
"""
        ).collect()
    except Exception:
        return None
    if not rows:
        return None
    row = _row_to_dict(rows[0])
    candidate = str(row.get("PROCEDURE_NAME", "") or "").strip().upper()
    if candidate in {name.upper() for name in BOOTSTRAP_PROCEDURE_FALLBACKS}:
        return candidate
    return None


def _run_bootstrap_procedure(session: object) -> BootstrapProcedureResult:
    """Run the best available bootstrap procedure without leaking discovery failures."""
    setup_errors: list[str] = []
    marker_candidate = detect_decision_setup_version(session)
    if marker_candidate:
        try:
            _run_call(session, marker_candidate)
            return BootstrapProcedureResult(
                procedure_name=marker_candidate,
                fallback_used=marker_candidate != BOOTSTRAP_PROCEDURE,
                admin_detail=f"Setup marker selected {marker_candidate}.",
            )
        except Exception as exc:
            setup_errors.append(f"Setup marker procedure {marker_candidate} failed: {exc}")

    show_errors: list[str] = []
    try:
        for procedure_name in BOOTSTRAP_PROCEDURE_FALLBACKS:
            if _candidate_procedure_available(session, procedure_name):
                _run_call(session, procedure_name)
                return BootstrapProcedureResult(
                    procedure_name=procedure_name,
                    fallback_used=procedure_name != BOOTSTRAP_PROCEDURE,
                )
        raise BootstrapProcedureFailure(
            "No visible Decision summary bootstrap procedure was found with SHOW PROCEDURES."
        )
    except BootstrapProcedureFailure:
        raise
    except Exception as exc:
        show_errors.append(f"SHOW PROCEDURES unavailable or incomplete: {exc}")

    call_errors: list[str] = []
    for procedure_name in BOOTSTRAP_PROCEDURE_FALLBACKS:
        try:
            _run_call(session, procedure_name)
            return BootstrapProcedureResult(
                procedure_name=procedure_name,
                fallback_used=procedure_name != BOOTSTRAP_PROCEDURE,
                admin_detail="; ".join(setup_errors + show_errors),
            )
        except Exception as exc:
            call_errors.append(f"{procedure_name}: {exc}")
    raise BootstrapProcedureFailure("; ".join(setup_errors + show_errors + call_errors))


def _validation_sql(packet_byte_limit: int) -> str:
    return f"""
WITH current_packets AS (
    SELECT
        SECTION_NAME,
        COMPANY,
        ENVIRONMENT,
        WINDOW_DAYS,
        BRIEF_ID,
        DECISION_PACKET,
        SNAPSHOT_TS,
        SOURCE_SNAPSHOT_TS,
        FRESHNESS_MINUTES,
        PACKET_BYTES
    FROM {DECISION_CURRENT_TABLE}
),
source_rows AS (
    SELECT
        SECTION_NAME,
        COMPANY,
        ENVIRONMENT,
        WINDOW_DAYS,
        BRIEF_ID,
        src.value:"SOURCE_KEY"::VARCHAR AS SOURCE_KEY,
        src.value:"SOURCE_OBJECT"::VARCHAR AS SOURCE_OBJECT,
        COALESCE(src.value:"REQUIRED"::BOOLEAN, FALSE) AS REQUIRED,
        COALESCE(src.value:"AVAILABLE"::BOOLEAN, FALSE) AS AVAILABLE,
        COALESCE(src.value:"IS_STALE"::BOOLEAN, FALSE) AS IS_STALE,
        src.value:"CONFIDENCE"::VARCHAR AS CONFIDENCE,
        src.value:"GAP_REASON"::VARCHAR AS GAP_REASON
    FROM current_packets,
    LATERAL FLATTEN(INPUT => DECISION_PACKET:"SOURCES") src
),
flattened_sources AS (
    SELECT
        SECTION_NAME,
        COMPANY,
        ENVIRONMENT,
        WINDOW_DAYS,
        BRIEF_ID,
        COUNT(*) AS FLATTENED_SOURCE_ROW_COUNT,
        COUNT_IF(REQUIRED) AS FLATTENED_REQUIRED_SOURCE_COUNT,
        COUNT_IF(REQUIRED AND AVAILABLE) AS FLATTENED_AVAILABLE_REQUIRED_SOURCE_COUNT,
        COUNT_IF(REQUIRED AND NOT AVAILABLE) AS FLATTENED_REQUIRED_MISSING_SOURCE_COUNT,
        COUNT_IF(REQUIRED AND IS_STALE) AS FLATTENED_REQUIRED_STALE_SOURCE_COUNT,
        COUNT_IF(NOT REQUIRED) AS FLATTENED_OPTIONAL_SOURCE_COUNT,
        COUNT_IF(NOT REQUIRED AND AVAILABLE) AS FLATTENED_AVAILABLE_OPTIONAL_SOURCE_COUNT,
        COUNT_IF(NOT REQUIRED AND NOT AVAILABLE) AS FLATTENED_OPTIONAL_MISSING_SOURCE_COUNT,
        COUNT_IF(NOT REQUIRED AND IS_STALE) AS FLATTENED_OPTIONAL_STALE_SOURCE_COUNT,
        COUNT(*) - COUNT(DISTINCT SOURCE_KEY) AS FLATTENED_DUPLICATE_SOURCE_KEY_COUNT
    FROM source_rows
    GROUP BY SECTION_NAME, COMPANY, ENVIRONMENT, WINDOW_DAYS, BRIEF_ID
),
parent_rollup AS (
SELECT
    SECTION_NAME,
    COMPANY,
    ENVIRONMENT,
    WINDOW_DAYS,
    COUNT(*) AS CURRENT_KEY_COUNT,
    MAX(BRIEF_ID) AS BRIEF_ID,
    MAX(COALESCE(PACKET_BYTES, 0)) AS MAX_PACKET_BYTES,
    MAX(IFF(ARRAY_SIZE(DECISION_PACKET:"METRICS") > 0, 1, 0)) AS HAS_METRICS,
    MAX(ARRAY_SIZE(COALESCE(DECISION_PACKET:"SOURCES", ARRAY_CONSTRUCT()))) AS SOURCE_ROW_COUNT,
    MAX(TRY_TO_NUMBER(DECISION_PACKET:"REQUIRED_SOURCE_COUNT")) AS REQUIRED_SOURCE_COUNT,
    MAX(COALESCE(
        TRY_TO_NUMBER(DECISION_PACKET:"AVAILABLE_REQUIRED_SOURCE_COUNT"),
        TRY_TO_NUMBER(DECISION_PACKET:"AVAILABLE_SOURCE_COUNT")
    )) AS AVAILABLE_REQUIRED_SOURCE_COUNT,
    MAX(COALESCE(
        TRY_TO_NUMBER(DECISION_PACKET:"REQUIRED_MISSING_SOURCE_COUNT"),
        TRY_TO_NUMBER(DECISION_PACKET:"MISSING_SOURCE_COUNT")
    )) AS REQUIRED_MISSING_SOURCE_COUNT,
    MAX(COALESCE(
        TRY_TO_NUMBER(DECISION_PACKET:"REQUIRED_STALE_SOURCE_COUNT"),
        TRY_TO_NUMBER(DECISION_PACKET:"STALE_REQUIRED_SOURCE_COUNT"),
        TRY_TO_NUMBER(DECISION_PACKET:"STALE_SOURCE_COUNT")
    )) AS REQUIRED_STALE_SOURCE_COUNT,
    MAX(COALESCE(
        TRY_TO_NUMBER(DECISION_PACKET:"OPTIONAL_SOURCE_COUNT"),
        0
    )) AS OPTIONAL_SOURCE_COUNT,
    MAX(COALESCE(
        TRY_TO_NUMBER(DECISION_PACKET:"AVAILABLE_OPTIONAL_SOURCE_COUNT"),
        0
    )) AS AVAILABLE_OPTIONAL_SOURCE_COUNT,
    MAX(COALESCE(
        TRY_TO_NUMBER(DECISION_PACKET:"OPTIONAL_MISSING_SOURCE_COUNT"),
        TRY_TO_NUMBER(DECISION_PACKET:"MISSING_OPTIONAL_SOURCE_COUNT"),
        0
    )) AS OPTIONAL_MISSING_SOURCE_COUNT,
    MAX(COALESCE(
        TRY_TO_NUMBER(DECISION_PACKET:"REQUIRED_MISSING_SOURCE_COUNT"),
        TRY_TO_NUMBER(DECISION_PACKET:"MISSING_SOURCE_COUNT"),
        0
    )) AS MISSING_SOURCE_COUNT,
    MAX(COALESCE(
        TRY_TO_NUMBER(DECISION_PACKET:"OPTIONAL_STALE_SOURCE_COUNT"),
        TRY_TO_NUMBER(DECISION_PACKET:"STALE_OPTIONAL_SOURCE_COUNT"),
        0
    )) AS OPTIONAL_STALE_SOURCE_COUNT,
    MAX(COALESCE(
        TRY_TO_NUMBER(DECISION_PACKET:"STALE_SOURCE_COUNT"),
        TRY_TO_NUMBER(DECISION_PACKET:"REQUIRED_STALE_SOURCE_COUNT"),
        0
    )) AS STALE_SOURCE_COUNT,
    MAX(TRY_TO_NUMBER(DECISION_PACKET:"SOURCE_COVERAGE_PCT")) AS SOURCE_COVERAGE_PCT,
    MAX(UPPER(COALESCE(
        DECISION_PACKET:"DATA_AVAILABILITY_STATE"::VARCHAR,
        DECISION_PACKET:"STATE"::VARCHAR,
        ''
    ))) AS DATA_AVAILABILITY_STATE,
    MAX(TRY_TO_NUMBER(DECISION_PACKET:"FRESHNESS_MINUTES")) AS FRESHNESS_MINUTES,
    MAX(TRY_TO_NUMBER(DECISION_PACKET:"TARGET_FRESHNESS_MINUTES")) AS TARGET_FRESHNESS_MINUTES,
    MAX(COALESCE(DECISION_PACKET:"RESOLVED_COMPANY"::VARCHAR, COMPANY)) AS RESOLVED_COMPANY,
    MAX(COALESCE(DECISION_PACKET:"RESOLVED_ENVIRONMENT"::VARCHAR, ENVIRONMENT)) AS RESOLVED_ENVIRONMENT,
    MAX(COALESCE(TRY_TO_NUMBER(DECISION_PACKET:"RESOLVED_WINDOW_DAYS"), WINDOW_DAYS)) AS RESOLVED_WINDOW_DAYS,
    MAX(IFF(COALESCE(PACKET_BYTES, 0) > {int(packet_byte_limit)}, 1, 0)) AS PACKET_TOO_LARGE
FROM current_packets
GROUP BY SECTION_NAME, COMPANY, ENVIRONMENT, WINDOW_DAYS
)
SELECT
    p.*,
    COALESCE(MAX(f.FLATTENED_SOURCE_ROW_COUNT), 0) AS FLATTENED_SOURCE_ROW_COUNT,
    COALESCE(MAX(f.FLATTENED_REQUIRED_SOURCE_COUNT), 0) AS FLATTENED_REQUIRED_SOURCE_COUNT,
    COALESCE(MAX(f.FLATTENED_AVAILABLE_REQUIRED_SOURCE_COUNT), 0) AS FLATTENED_AVAILABLE_REQUIRED_SOURCE_COUNT,
    COALESCE(MAX(f.FLATTENED_REQUIRED_MISSING_SOURCE_COUNT), 0) AS FLATTENED_REQUIRED_MISSING_SOURCE_COUNT,
    COALESCE(MAX(f.FLATTENED_REQUIRED_STALE_SOURCE_COUNT), 0) AS FLATTENED_REQUIRED_STALE_SOURCE_COUNT,
    COALESCE(MAX(f.FLATTENED_OPTIONAL_SOURCE_COUNT), 0) AS FLATTENED_OPTIONAL_SOURCE_COUNT,
    COALESCE(MAX(f.FLATTENED_AVAILABLE_OPTIONAL_SOURCE_COUNT), 0) AS FLATTENED_AVAILABLE_OPTIONAL_SOURCE_COUNT,
    COALESCE(MAX(f.FLATTENED_OPTIONAL_MISSING_SOURCE_COUNT), 0) AS FLATTENED_OPTIONAL_MISSING_SOURCE_COUNT,
    COALESCE(MAX(f.FLATTENED_OPTIONAL_STALE_SOURCE_COUNT), 0) AS FLATTENED_OPTIONAL_STALE_SOURCE_COUNT,
    COALESCE(MAX(f.FLATTENED_DUPLICATE_SOURCE_KEY_COUNT), 0) AS DUPLICATE_SOURCE_KEY_COUNT,
    MAX(
        IFF(COALESCE(p.SOURCE_ROW_COUNT, -1) <> COALESCE(f.FLATTENED_SOURCE_ROW_COUNT, -2), 1, 0)
        + IFF(COALESCE(p.REQUIRED_SOURCE_COUNT, -1) <> COALESCE(f.FLATTENED_REQUIRED_SOURCE_COUNT, -2), 1, 0)
        + IFF(COALESCE(p.AVAILABLE_REQUIRED_SOURCE_COUNT, -1) <> COALESCE(f.FLATTENED_AVAILABLE_REQUIRED_SOURCE_COUNT, -2), 1, 0)
        + IFF(COALESCE(p.REQUIRED_MISSING_SOURCE_COUNT, -1) <> COALESCE(f.FLATTENED_REQUIRED_MISSING_SOURCE_COUNT, -2), 1, 0)
        + IFF(COALESCE(p.REQUIRED_STALE_SOURCE_COUNT, -1) <> COALESCE(f.FLATTENED_REQUIRED_STALE_SOURCE_COUNT, -2), 1, 0)
        + IFF(COALESCE(p.OPTIONAL_SOURCE_COUNT, -1) <> COALESCE(f.FLATTENED_OPTIONAL_SOURCE_COUNT, -2), 1, 0)
        + IFF(COALESCE(p.AVAILABLE_OPTIONAL_SOURCE_COUNT, -1) <> COALESCE(f.FLATTENED_AVAILABLE_OPTIONAL_SOURCE_COUNT, -2), 1, 0)
        + IFF(COALESCE(p.OPTIONAL_MISSING_SOURCE_COUNT, -1) <> COALESCE(f.FLATTENED_OPTIONAL_MISSING_SOURCE_COUNT, -2), 1, 0)
        + IFF(COALESCE(p.OPTIONAL_STALE_SOURCE_COUNT, -1) <> COALESCE(f.FLATTENED_OPTIONAL_STALE_SOURCE_COUNT, -2), 1, 0)
    ) AS SOURCE_COUNTER_MISMATCH_COUNT
FROM parent_rollup p
LEFT JOIN flattened_sources f
  ON f.SECTION_NAME = p.SECTION_NAME
 AND f.COMPANY = p.COMPANY
 AND f.ENVIRONMENT = p.ENVIRONMENT
 AND f.WINDOW_DAYS = p.WINDOW_DAYS
 AND f.BRIEF_ID = p.BRIEF_ID
GROUP BY
    p.SECTION_NAME, p.COMPANY, p.ENVIRONMENT, p.WINDOW_DAYS, p.CURRENT_KEY_COUNT,
    p.BRIEF_ID, p.MAX_PACKET_BYTES, p.HAS_METRICS, p.SOURCE_ROW_COUNT,
    p.REQUIRED_SOURCE_COUNT, p.AVAILABLE_REQUIRED_SOURCE_COUNT,
    p.REQUIRED_MISSING_SOURCE_COUNT, p.REQUIRED_STALE_SOURCE_COUNT,
    p.OPTIONAL_SOURCE_COUNT, p.AVAILABLE_OPTIONAL_SOURCE_COUNT,
    p.OPTIONAL_MISSING_SOURCE_COUNT, p.MISSING_SOURCE_COUNT,
    p.OPTIONAL_STALE_SOURCE_COUNT, p.STALE_SOURCE_COUNT, p.SOURCE_COVERAGE_PCT,
    p.DATA_AVAILABILITY_STATE, p.FRESHNESS_MINUTES, p.TARGET_FRESHNESS_MINUTES,
    p.RESOLVED_COMPANY, p.RESOLVED_ENVIRONMENT, p.RESOLVED_WINDOW_DAYS,
    p.PACKET_TOO_LARGE
"""


def validate_decision_bootstrap_output(
    session: object,
    *,
    current_section: str | None,
    company: str | None = None,
    environment: str | None = None,
    window_days: int | None = None,
    packet_byte_limit: int = DEFAULT_PACKET_BYTE_LIMIT,
) -> DecisionBootstrapValidation:
    """Validate that bootstrap produced usable current Decision packets before cache clearing."""
    requested_company = _norm_scope(company)
    requested_environment = _norm_scope(environment)
    requested_window_days = _int_value(window_days, 7) or 7
    try:
        rows = [_row_to_dict(row) for row in session.sql(_validation_sql(packet_byte_limit)).collect()]
    except Exception as exc:
        return DecisionBootstrapValidation(
            ok=False,
            global_ok=False,
            selected_scope_ok=False,
            current_section_ok=False,
            requested_company=requested_company,
            requested_environment=requested_environment,
            requested_window_days=requested_window_days,
            current_section=str(current_section or ""),
            message=BOOTSTRAP_SETUP_MESSAGE,
            admin_detail=f"{DECISION_CURRENT_TABLE} is not queryable: {exc}",
        )

    canonical = tuple(CANONICAL_COMMAND_BRIEF_SECTIONS)
    present = tuple(
        section for section in canonical
        if any(str(row.get("SECTION_NAME", "")).upper() == section.upper() for row in rows)
    )
    missing = tuple(section for section in canonical if section not in present)
    current_packet_count = sum(_int_value(row.get("CURRENT_KEY_COUNT"), 0) for row in rows)
    duplicate_current_keys = sum(
        max(_int_value(row.get("CURRENT_KEY_COUNT"), 0) - 1, 0)
        for row in rows
    )
    def _source_counter(row: Mapping[str, Any] | None, parent_field: str, flattened_field: str, default: int = 0) -> int:
        if row is None:
            return default
        if flattened_field in row and row.get(flattened_field) is not None:
            return _int_value(row.get(flattened_field), default)
        return _int_value(row.get(parent_field), default)

    def _source_counter_mismatch_count(row: Mapping[str, Any] | None) -> int:
        if row is None:
            return 0
        mismatch_count = _int_value(row.get("SOURCE_COUNTER_MISMATCH_COUNT"), 0)
        counter_pairs = (
            ("SOURCE_ROW_COUNT", "FLATTENED_SOURCE_ROW_COUNT"),
            ("REQUIRED_SOURCE_COUNT", "FLATTENED_REQUIRED_SOURCE_COUNT"),
            ("AVAILABLE_REQUIRED_SOURCE_COUNT", "FLATTENED_AVAILABLE_REQUIRED_SOURCE_COUNT"),
            ("REQUIRED_MISSING_SOURCE_COUNT", "FLATTENED_REQUIRED_MISSING_SOURCE_COUNT"),
            ("REQUIRED_STALE_SOURCE_COUNT", "FLATTENED_REQUIRED_STALE_SOURCE_COUNT"),
            ("OPTIONAL_SOURCE_COUNT", "FLATTENED_OPTIONAL_SOURCE_COUNT"),
            ("AVAILABLE_OPTIONAL_SOURCE_COUNT", "FLATTENED_AVAILABLE_OPTIONAL_SOURCE_COUNT"),
            ("OPTIONAL_MISSING_SOURCE_COUNT", "FLATTENED_OPTIONAL_MISSING_SOURCE_COUNT"),
            ("OPTIONAL_STALE_SOURCE_COUNT", "FLATTENED_OPTIONAL_STALE_SOURCE_COUNT"),
        )
        for parent_field, flattened_field in counter_pairs:
            if (
                parent_field in row
                and flattened_field in row
                and row.get(parent_field) is not None
                and row.get(flattened_field) is not None
                and _int_value(row.get(parent_field), 0) != _int_value(row.get(flattened_field), 0)
            ):
                mismatch_count += 1
        return mismatch_count

    def _duplicate_source_key_count(row: Mapping[str, Any] | None) -> int:
        if row is None:
            return 0
        return _int_value(row.get("DUPLICATE_SOURCE_KEY_COUNT"), 0)

    stale_sections = tuple(sorted({
        str(row.get("SECTION_NAME", ""))
        for row in rows
        if (
            (_float_value(row.get("FRESHNESS_MINUTES")) is not None)
            and (_float_value(row.get("TARGET_FRESHNESS_MINUTES")) is not None)
            and float(row.get("FRESHNESS_MINUTES")) > float(row.get("TARGET_FRESHNESS_MINUTES"))
        )
        or _int_value(row.get("STALE_SOURCE_COUNT"), 0) > 0
    }))
    data_gap_sections = tuple(sorted({
        str(row.get("SECTION_NAME", ""))
        for row in rows
        if "DATA GAP" in str(row.get("DATA_AVAILABILITY_STATE", "")).upper()
        or "UNAVAILABLE" in str(row.get("DATA_AVAILABILITY_STATE", "")).upper()
    }))
    missing_metric_sections = tuple(sorted({
        str(row.get("SECTION_NAME", ""))
        for row in rows
        if _int_value(row.get("HAS_METRICS"), 0) <= 0
    }))
    missing_source_sections = tuple(sorted({
        str(row.get("SECTION_NAME", ""))
        for row in rows
        if (
            _source_counter(row, "SOURCE_ROW_COUNT", "FLATTENED_SOURCE_ROW_COUNT") <= 0
            or _source_counter(row, "REQUIRED_SOURCE_COUNT", "FLATTENED_REQUIRED_SOURCE_COUNT") <= 0
            or row.get("REQUIRED_SOURCE_COUNT") is None
            or row.get("AVAILABLE_REQUIRED_SOURCE_COUNT") is None
            or row.get("REQUIRED_MISSING_SOURCE_COUNT") is None
            or row.get("SOURCE_COVERAGE_PCT") is None
            or _source_counter(row, "AVAILABLE_REQUIRED_SOURCE_COUNT", "FLATTENED_AVAILABLE_REQUIRED_SOURCE_COUNT") < _source_counter(row, "REQUIRED_SOURCE_COUNT", "FLATTENED_REQUIRED_SOURCE_COUNT")
            or _source_counter(row, "REQUIRED_MISSING_SOURCE_COUNT", "FLATTENED_REQUIRED_MISSING_SOURCE_COUNT") > 0
            or float(_float_value(row.get("SOURCE_COVERAGE_PCT")) or 0.0) < 100.0
            or _source_counter(row, "REQUIRED_STALE_SOURCE_COUNT", "FLATTENED_REQUIRED_STALE_SOURCE_COUNT") > 0
            or _source_counter_mismatch_count(row) > 0
            or _duplicate_source_key_count(row) > 0
        )
    }))
    optional_warning_sections = tuple(sorted({
        str(row.get("SECTION_NAME", ""))
        for row in rows
        if _source_counter(row, "OPTIONAL_MISSING_SOURCE_COUNT", "FLATTENED_OPTIONAL_MISSING_SOURCE_COUNT") > 0
        or _source_counter(row, "OPTIONAL_STALE_SOURCE_COUNT", "FLATTENED_OPTIONAL_STALE_SOURCE_COUNT") > 0
    }))
    oversized_sections = tuple(sorted({
        str(row.get("SECTION_NAME", ""))
        for row in rows
        if _int_value(row.get("PACKET_TOO_LARGE"), 0) > 0
    }))
    max_packet_bytes = max((_int_value(row.get("MAX_PACKET_BYTES"), 0) for row in rows), default=0)
    packet_too_large = any(_int_value(row.get("PACKET_TOO_LARGE"), 0) > 0 for row in rows)

    def _matches_section(row: Mapping[str, Any]) -> bool:
        return str(row.get("SECTION_NAME", "")).upper() == str(current_section or "").upper()

    def _scope_priority(row: Mapping[str, Any]) -> tuple[int, int, int] | None:
        row_company = _norm_scope(row.get("COMPANY")).upper()
        row_environment = _norm_scope(row.get("ENVIRONMENT")).upper()
        row_window = _int_value(row.get("WINDOW_DAYS"), 0)
        requested_company_upper = requested_company.upper()
        requested_environment_upper = requested_environment.upper()
        company_score: int
        environment_score: int
        if row_company == requested_company_upper:
            company_score = 0
        elif row_company in {"ALL", "GLOBAL"}:
            company_score = 2
        else:
            return None
        if row_environment == requested_environment_upper:
            environment_score = 0
        elif row_environment in {"ALL", "GLOBAL", "ALL ENVIRONMENTS"}:
            environment_score = 1 if company_score == 0 else 2
        else:
            return None
        fallback_windows = (requested_window_days, 7, 14, 30, 60, 90, 1)
        try:
            window_score = fallback_windows.index(row_window)
        except ValueError:
            return None
        return (window_score, company_score, environment_score)

    selected_row: Mapping[str, Any] | None = None
    selected_score: tuple[int, int, int] | None = None
    if current_section:
        for row in rows:
            if not _matches_section(row):
                continue
            score = _scope_priority(row)
            if score is None:
                continue
            if selected_score is None or score < selected_score:
                selected_row = row
                selected_score = score

    def _row_missing_sources(row: Mapping[str, Any] | None) -> int:
        if row is None:
            return 1
        if _source_counter(row, "SOURCE_ROW_COUNT", "FLATTENED_SOURCE_ROW_COUNT") <= 0:
            return max(_source_counter(row, "REQUIRED_SOURCE_COUNT", "FLATTENED_REQUIRED_SOURCE_COUNT"), 1)
        for field in (
            "REQUIRED_SOURCE_COUNT",
            "AVAILABLE_REQUIRED_SOURCE_COUNT",
            "REQUIRED_MISSING_SOURCE_COUNT",
            "SOURCE_COVERAGE_PCT",
        ):
            if row.get(field) is None:
                return max(_int_value(row.get("REQUIRED_SOURCE_COUNT"), 0), 1)
        if _source_counter_mismatch_count(row) > 0:
            return 1
        if _duplicate_source_key_count(row) > 0:
            return 1
        required = _source_counter(row, "REQUIRED_SOURCE_COUNT", "FLATTENED_REQUIRED_SOURCE_COUNT")
        available = _source_counter(row, "AVAILABLE_REQUIRED_SOURCE_COUNT", "FLATTENED_AVAILABLE_REQUIRED_SOURCE_COUNT")
        missing = _source_counter(row, "REQUIRED_MISSING_SOURCE_COUNT", "FLATTENED_REQUIRED_MISSING_SOURCE_COUNT")
        coverage = _float_value(row.get("SOURCE_COVERAGE_PCT")) or 0.0
        stale_required = _source_counter(row, "REQUIRED_STALE_SOURCE_COUNT", "FLATTENED_REQUIRED_STALE_SOURCE_COUNT")
        if required <= 0:
            return 1
        if available < required:
            return max(required - available, 1)
        if missing > 0:
            return missing
        if coverage < 100.0:
            return 1
        if stale_required > 0:
            return stale_required
        return 0

    def _row_is_data_gap(row: Mapping[str, Any] | None) -> bool:
        if row is None:
            return True
        state = str(row.get("DATA_AVAILABILITY_STATE", "")).upper()
        return "DATA GAP" in state or "UNAVAILABLE" in state

    def _row_is_stale(row: Mapping[str, Any] | None) -> bool:
        if row is None:
            return False
        freshness = _float_value(row.get("FRESHNESS_MINUTES"))
        target = _float_value(row.get("TARGET_FRESHNESS_MINUTES"))
        if freshness is not None and target is not None and freshness > target:
            return True
        return _source_counter(row, "REQUIRED_STALE_SOURCE_COUNT", "FLATTENED_REQUIRED_STALE_SOURCE_COUNT") > 0

    selected_has_metrics = selected_row is not None and _int_value(selected_row.get("HAS_METRICS"), 0) > 0
    selected_missing_sources = _row_missing_sources(selected_row)
    selected_packet_too_large = selected_row is None or _int_value(selected_row.get("PACKET_TOO_LARGE"), 0) > 0
    selected_stale = _row_is_stale(selected_row)
    selected_data_gap = _row_is_data_gap(selected_row)
    selected_duplicate = selected_row is None or _int_value(selected_row.get("CURRENT_KEY_COUNT"), 0) > 1
    current_section_ok = selected_row is not None and str(current_section or "").upper() in {
        str(section).upper() for section in present
    }
    selected_scope_ok = (
        current_section_ok
        and selected_has_metrics
        and selected_missing_sources == 0
        and not selected_packet_too_large
        and not selected_stale
        and not selected_data_gap
        and not selected_duplicate
    )
    global_success = (
        current_packet_count > 0
        and not missing
        and duplicate_current_keys == 0
        and not missing_metric_sections
        and not missing_source_sections
        and not stale_sections
        and not data_gap_sections
        and not optional_warning_sections
        and not packet_too_large
    )
    degraded_sections = tuple(sorted({
        *(section for section in missing),
        *(section for section in stale_sections),
        *(section for section in data_gap_sections),
        *(section for section in missing_metric_sections),
        *(section for section in missing_source_sections),
        *(section for section in optional_warning_sections),
        *(section for section in oversized_sections),
    }))
    duplicate_sections = tuple(sorted({
        str(row.get("SECTION_NAME", ""))
        for row in rows
        if _int_value(row.get("CURRENT_KEY_COUNT"), 0) > 1
    }))
    warning_sections = tuple(sorted({*(section for section in optional_warning_sections), *(section for section in stale_sections)}))
    invalid_sections = tuple(sorted({
        *(section for section in data_gap_sections),
        *(section for section in missing_metric_sections),
        *(section for section in missing_source_sections),
        *(section for section in oversized_sections),
        *(section for section in duplicate_sections),
    }))
    if not rows:
        global_status = "FAILED"
    elif global_success:
        global_status = "SUCCESS"
    else:
        global_status = "DEGRADED"
    selected_scope_status = "SUCCESS" if selected_scope_ok else "FAILED"
    current_section_status = "SUCCESS" if current_section_ok and selected_scope_ok else "FAILED"
    if not selected_scope_ok:
        status = "FAILED"
    elif global_success:
        status = "SUCCESS"
    else:
        status = "DEGRADED"
    global_ok = global_success
    ok = status in {"SUCCESS", "DEGRADED"}
    resolved_company = _norm_scope(selected_row.get("RESOLVED_COMPANY") if selected_row else "")
    resolved_environment = _norm_scope(selected_row.get("RESOLVED_ENVIRONMENT") if selected_row else "")
    resolved_window_days = _int_value(selected_row.get("RESOLVED_WINDOW_DAYS") if selected_row else 0, 0)
    if selected_row is not None:
        selected_packet_key = _packet_key_tuple(
            selected_row.get("SECTION_NAME"),
            selected_row.get("COMPANY"),
            selected_row.get("ENVIRONMENT"),
            selected_row.get("WINDOW_DAYS"),
        )
        validated_packet_keys = (selected_packet_key,) if selected_scope_ok else ()
    else:
        validated_packet_keys = ()
    admin_parts = [
        f"Table: {DECISION_CURRENT_TABLE}",
        f"Current packet count: {current_packet_count}",
        f"Sections present: {', '.join(present) or 'none'}",
        f"Missing sections: {', '.join(missing) or 'none'}",
        f"Missing source metadata: {', '.join(missing_source_sections) or 'none'}",
        f"Optional source warnings: {', '.join(optional_warning_sections) or 'none'}",
        "Source counter mismatches: "
        + (
            ", ".join(
                str(row.get("SECTION_NAME", ""))
                for row in rows
                if _source_counter_mismatch_count(row) > 0
            )
            or "none"
        ),
        "Duplicate source keys: "
        + (
            ", ".join(
                str(row.get("SECTION_NAME", ""))
                for row in rows
                if _duplicate_source_key_count(row) > 0
            )
            or "none"
        ),
        f"Duplicate current keys: {duplicate_current_keys}",
        f"Max packet bytes: {max_packet_bytes}",
        f"Requested scope: {requested_company} / {requested_environment} / {requested_window_days} days",
        (
            f"Resolved scope: {resolved_company or 'none'} / {resolved_environment or 'none'} / "
            f"{resolved_window_days or 0} days"
        ),
        f"Selected packet: {str(selected_row.get('BRIEF_ID', 'none')) if selected_row else 'none'}",
        f"Validation status: {status}",
        f"Selected scope ok: {selected_scope_ok}",
    ]
    return DecisionBootstrapValidation(
        ok=ok,
        status=status,
        global_status=global_status,
        selected_scope_status=selected_scope_status,
        current_section_status=current_section_status,
        global_ok=global_ok,
        selected_scope_ok=selected_scope_ok,
        current_section_ok=current_section_ok,
        requested_company=requested_company,
        requested_environment=requested_environment,
        requested_window_days=requested_window_days,
        resolved_company=resolved_company,
        resolved_environment=resolved_environment,
        resolved_window_days=resolved_window_days,
        current_section=str(current_section or ""),
        current_section_state=str(selected_row.get("DATA_AVAILABILITY_STATE", "") if selected_row else ""),
        current_section_missing_metrics=not selected_has_metrics,
        current_section_missing_sources=selected_missing_sources,
        current_section_stale=selected_stale,
        current_section_packet_bytes=_int_value(selected_row.get("MAX_PACKET_BYTES"), 0) if selected_row else None,
        current_section_packet_id=str(selected_row.get("BRIEF_ID", "") if selected_row else ""),
        current_packet_count=current_packet_count,
        sections_present=present,
        missing_sections=missing,
        duplicate_current_keys=duplicate_current_keys,
        stale_sections=stale_sections,
        data_gap_sections=data_gap_sections,
        missing_metric_sections=missing_metric_sections,
        degraded_sections=degraded_sections,
        invalid_sections=invalid_sections,
        warning_sections=warning_sections,
        max_packet_bytes=max_packet_bytes,
        message=(
            BOOTSTRAP_SUCCESS_MESSAGE if status == "SUCCESS"
            else BOOTSTRAP_DEGRADED_MESSAGE if status == "DEGRADED"
            else BOOTSTRAP_SETUP_MESSAGE
        ),
        admin_detail="; ".join(admin_parts),
        validated_sections=present if ok else (),
        validated_packet_keys=validated_packet_keys,
    )


def maybe_run_decision_workspace_bootstrap(current_section: str | None = None) -> None:
    """Consume the bootstrap request flag and run the setup procedure once."""
    success = st.session_state.pop(BOOTSTRAP_SUCCESS_KEY, "")
    if success:
        if "warning" in str(success).lower():
            st.warning(success)
        else:
            st.success(success)
    failure = st.session_state.pop(BOOTSTRAP_FAILURE_KEY, "")
    if failure:
        st.warning(_clean_bootstrap_failure_message(failure))
    if not bool(st.session_state.pop(BOOTSTRAP_REQUEST_KEY, False)):
        return
    with query_budget_context(
        "admin_setup",
        section=current_section or "Decision Workspace",
        workflow="Decision Summary Initialization",
        budget=DECISION_BOOTSTRAP_QUERY_BUDGET,
    ):
        get_session_for_action = lazy_util("get_session_for_action")
        session = get_session_for_action(
            "initialize decision summaries",
            surface="Decision Workspace",
            offline_note=BOOTSTRAP_SETUP_MESSAGE,
        )
        if session is None:
            st.session_state[BOOTSTRAP_FAILURE_KEY] = BOOTSTRAP_SETUP_MESSAGE
            record_decision_bootstrap_health(
                status="failed",
                user_message=st.session_state[BOOTSTRAP_FAILURE_KEY],
                admin_detail="No Snowflake session was available for Decision summary initialization.",
            )
            st.warning(st.session_state[BOOTSTRAP_FAILURE_KEY])
            return
        try:
            company, environment, window_days = _active_validation_scope()
            procedure_result = _run_bootstrap_procedure(session)
            validation = validate_decision_bootstrap_output(
                session,
                current_section=current_section,
                company=company,
                environment=environment,
                window_days=window_days,
            )
            if not validation.ok:
                _clear_command_brief_caches(clear_last_good=False)
                st.session_state[BOOTSTRAP_FAILURE_KEY] = validation.message or BOOTSTRAP_SETUP_MESSAGE
                record_decision_bootstrap_health(
                    status=validation.status.lower(),
                    user_message=st.session_state[BOOTSTRAP_FAILURE_KEY],
                    selected_procedure=procedure_result.procedure_name,
                    fallback_used=procedure_result.fallback_used,
                    validation=validation,
                    admin_detail="; ".join(
                        part for part in (procedure_result.admin_detail, validation.admin_detail) if part
                    ),
                    session=session,
                )
                st.warning(st.session_state[BOOTSTRAP_FAILURE_KEY])
                return
            _clear_command_brief_caches(
                clear_last_good=True,
                validated_packet_keys=validation.validated_packet_keys,
            )
            _force_current_section_refresh(current_section)
            st.session_state[BOOTSTRAP_SUCCESS_KEY] = validation.message or BOOTSTRAP_SUCCESS_MESSAGE
            record_decision_bootstrap_health(
                status=validation.status.lower(),
                user_message=st.session_state[BOOTSTRAP_SUCCESS_KEY],
                selected_procedure=procedure_result.procedure_name,
                fallback_used=procedure_result.fallback_used,
                validation=validation,
                admin_detail="; ".join(part for part in (procedure_result.admin_detail, validation.admin_detail) if part),
                session=session,
            )
        except Exception as exc:
            _clear_command_brief_caches(clear_last_good=False)
            st.session_state[BOOTSTRAP_FAILURE_KEY] = _clean_bootstrap_failure_message(exc)
            record_decision_bootstrap_health(
                status="failed",
                user_message=st.session_state[BOOTSTRAP_FAILURE_KEY],
                admin_detail=getattr(exc, "admin_detail", str(exc)),
                session=session,
            )
            st.warning(st.session_state[BOOTSTRAP_FAILURE_KEY])
        else:
            st.rerun()


__all__ = [
    "BOOTSTRAP_FAILURE_KEY",
    "BOOTSTRAP_PROCEDURE",
    "BOOTSTRAP_PROCEDURE_FALLBACKS",
    "BOOTSTRAP_REQUEST_KEY",
    "BOOTSTRAP_SETUP_MESSAGE",
    "BOOTSTRAP_SUCCESS_KEY",
    "BootstrapProcedureResult",
    "DecisionBootstrapValidation",
    "SECTION_FORCE_REFRESH_KEYS",
    "detect_decision_setup_version",
    "validate_decision_bootstrap_output",
    "maybe_run_decision_workspace_bootstrap",
]
