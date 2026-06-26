"""One-shot bootstrap flow for Decision Workspace command summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import streamlit as st

from sections.base import lazy_util
from sections.decision_workspace_setup_health import record_decision_bootstrap_health
from sections.section_command_contracts import CANONICAL_COMMAND_BRIEF_SECTIONS


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
    "Decision summaries are not initialized. Ask an administrator to deploy the latest "
    "OVERWATCH mart setup and initialize the Decision summary marts."
)
BOOTSTRAP_SUCCESS_MESSAGE = "Decision summaries initialized. Refreshing the current command brief."
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
    current_packet_count: int = 0
    sections_present: tuple[str, ...] = ()
    missing_sections: tuple[str, ...] = ()
    duplicate_current_keys: int = 0
    stale_sections: tuple[str, ...] = ()
    data_gap_sections: tuple[str, ...] = ()
    missing_metric_sections: tuple[str, ...] = ()
    max_packet_bytes: int | None = None
    message: str = ""
    admin_detail: str = ""
    validated_sections: tuple[str, ...] = ()


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


def _last_good_matches_validated_section(key: str, validated_sections: tuple[str, ...]) -> bool:
    if not validated_sections:
        return False
    normalized = {section.lower() for section in validated_sections}
    parts = key.split("::")
    return len(parts) >= 2 and parts[1].lower() in normalized


def _clear_command_brief_caches(
    *,
    clear_last_good: bool = False,
    validated_sections: tuple[str, ...] = (),
) -> None:
    for key in list(st.session_state.keys()):
        text = str(key)
        if not text.startswith("section_command_brief::"):
            continue
        if text.endswith("::last_good"):
            value = st.session_state.get(key)
            if _is_fixture_or_invalid_last_good(value) or (
                clear_last_good and _last_good_matches_validated_section(text, validated_sections)
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


def _run_bootstrap_procedure(session: object) -> BootstrapProcedureResult:
    """Run the best available bootstrap procedure without leaking discovery failures."""
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
                admin_detail="; ".join(show_errors),
            )
        except Exception as exc:
            call_errors.append(f"{procedure_name}: {exc}")
    raise BootstrapProcedureFailure("; ".join(show_errors + call_errors))


def _validation_sql(packet_byte_limit: int) -> str:
    return f"""
SELECT
    SECTION_NAME,
    COMPANY,
    ENVIRONMENT,
    WINDOW_DAYS,
    COUNT(*) AS CURRENT_KEY_COUNT,
    MAX(COALESCE(PACKET_BYTES, 0)) AS MAX_PACKET_BYTES,
    MAX(IFF(ARRAY_SIZE(DECISION_PACKET:"METRICS") > 0, 1, 0)) AS HAS_METRICS,
    MAX(IFF(
        DECISION_PACKET:"SOURCE_STATUS" IS NOT NULL
        OR DECISION_PACKET:"SOURCE_OBJECTS" IS NOT NULL
        OR ARRAY_SIZE(DECISION_PACKET:"SOURCES") > 0,
        1,
        0
    )) AS HAS_SOURCE_METADATA,
    MAX(UPPER(COALESCE(
        DECISION_PACKET:"DATA_AVAILABILITY_STATE"::VARCHAR,
        DECISION_PACKET:"STATE"::VARCHAR,
        ''
    ))) AS DATA_AVAILABILITY_STATE,
    MAX(TRY_TO_NUMBER(DECISION_PACKET:"FRESHNESS_MINUTES")) AS FRESHNESS_MINUTES,
    MAX(TRY_TO_NUMBER(DECISION_PACKET:"TARGET_FRESHNESS_MINUTES")) AS TARGET_FRESHNESS_MINUTES,
    MAX(IFF(COALESCE(PACKET_BYTES, 0) > {int(packet_byte_limit)}, 1, 0)) AS PACKET_TOO_LARGE
FROM {DECISION_CURRENT_TABLE}
GROUP BY SECTION_NAME, COMPANY, ENVIRONMENT, WINDOW_DAYS
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
    try:
        rows = [_row_to_dict(row) for row in session.sql(_validation_sql(packet_byte_limit)).collect()]
    except Exception as exc:
        return DecisionBootstrapValidation(
            ok=False,
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
    stale_sections = tuple(sorted({
        str(row.get("SECTION_NAME", ""))
        for row in rows
        if (
            (_float_value(row.get("FRESHNESS_MINUTES")) is not None)
            and (_float_value(row.get("TARGET_FRESHNESS_MINUTES")) is not None)
            and float(row.get("FRESHNESS_MINUTES")) > float(row.get("TARGET_FRESHNESS_MINUTES"))
        )
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
        if _int_value(row.get("HAS_SOURCE_METADATA"), 0) <= 0
    }))
    max_packet_bytes = max((_int_value(row.get("MAX_PACKET_BYTES"), 0) for row in rows), default=0)
    packet_too_large = any(_int_value(row.get("PACKET_TOO_LARGE"), 0) > 0 for row in rows)
    current_present = True
    if current_section:
        current_present = any(str(section).upper() == str(current_section).upper() for section in present)
    ok = (
        current_packet_count > 0
        and not missing
        and current_present
        and duplicate_current_keys == 0
        and not missing_metric_sections
        and not missing_source_sections
        and not packet_too_large
        and len(data_gap_sections) < len(canonical)
    )
    admin_parts = [
        f"Table: {DECISION_CURRENT_TABLE}",
        f"Current packet count: {current_packet_count}",
        f"Sections present: {', '.join(present) or 'none'}",
        f"Missing sections: {', '.join(missing) or 'none'}",
        f"Missing source metadata: {', '.join(missing_source_sections) or 'none'}",
        f"Duplicate current keys: {duplicate_current_keys}",
        f"Max packet bytes: {max_packet_bytes}",
    ]
    if company or environment or window_days:
        admin_parts.append(
            f"Requested scope: {company or 'any'} / {environment or 'any'} / {window_days or 'any'} days"
        )
    return DecisionBootstrapValidation(
        ok=ok,
        current_packet_count=current_packet_count,
        sections_present=present,
        missing_sections=missing,
        duplicate_current_keys=duplicate_current_keys,
        stale_sections=stale_sections,
        data_gap_sections=data_gap_sections,
        missing_metric_sections=missing_metric_sections,
        max_packet_bytes=max_packet_bytes,
        message=BOOTSTRAP_SUCCESS_MESSAGE if ok else BOOTSTRAP_SETUP_MESSAGE,
        admin_detail="; ".join(admin_parts),
        validated_sections=present if ok else (),
    )


def maybe_run_decision_workspace_bootstrap(current_section: str | None = None) -> None:
    """Consume the bootstrap request flag and run the setup procedure once."""
    success = st.session_state.pop(BOOTSTRAP_SUCCESS_KEY, "")
    if success:
        st.success(success)
    failure = st.session_state.pop(BOOTSTRAP_FAILURE_KEY, "")
    if failure:
        st.warning(_clean_bootstrap_failure_message(failure))
    if not bool(st.session_state.pop(BOOTSTRAP_REQUEST_KEY, False)):
        return
    get_session_for_action = lazy_util("get_session_for_action")
    session = get_session_for_action(
        "initialize decision summaries",
        surface="Decision Workspace",
        offline_note=BOOTSTRAP_SETUP_MESSAGE,
    )
    if session is None:
        st.warning(BOOTSTRAP_SETUP_MESSAGE)
        return
    try:
        procedure_result = _run_bootstrap_procedure(session)
        validation = validate_decision_bootstrap_output(
            session,
            current_section=current_section,
            company=None,
            environment=None,
            window_days=None,
        )
        if not validation.ok:
            _clear_command_brief_caches(clear_last_good=False)
            st.session_state[BOOTSTRAP_FAILURE_KEY] = validation.message or BOOTSTRAP_SETUP_MESSAGE
            record_decision_bootstrap_health(
                status="failed",
                user_message=st.session_state[BOOTSTRAP_FAILURE_KEY],
                selected_procedure=procedure_result.procedure_name,
                fallback_used=procedure_result.fallback_used,
                validation=validation,
                admin_detail="; ".join(
                    part for part in (procedure_result.admin_detail, validation.admin_detail) if part
                ),
            )
            st.warning(st.session_state[BOOTSTRAP_FAILURE_KEY])
            return
        _clear_command_brief_caches(
            clear_last_good=True,
            validated_sections=validation.validated_sections,
        )
        _force_current_section_refresh(current_section)
        st.session_state[BOOTSTRAP_SUCCESS_KEY] = validation.message or BOOTSTRAP_SUCCESS_MESSAGE
        record_decision_bootstrap_health(
            status="success",
            user_message=st.session_state[BOOTSTRAP_SUCCESS_KEY],
            selected_procedure=procedure_result.procedure_name,
            fallback_used=procedure_result.fallback_used,
            validation=validation,
            admin_detail="; ".join(part for part in (procedure_result.admin_detail, validation.admin_detail) if part),
        )
    except Exception as exc:
        _clear_command_brief_caches(clear_last_good=False)
        st.session_state[BOOTSTRAP_FAILURE_KEY] = _clean_bootstrap_failure_message(exc)
        record_decision_bootstrap_health(
            status="failed",
            user_message=st.session_state[BOOTSTRAP_FAILURE_KEY],
            admin_detail=getattr(exc, "admin_detail", str(exc)),
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
    "validate_decision_bootstrap_output",
    "maybe_run_decision_workspace_bootstrap",
]
