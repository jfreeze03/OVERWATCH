"""Mart-backed command brief packet loader for primary OVERWATCH sections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import json
import time

import pandas as pd
import streamlit as st

from sections.section_command_contracts import SectionCommandContract, get_section_command_contract
from utils.mart_names import mart_object_name
from utils.query import run_query, sql_literal


SESSION_CACHE_SECONDS = 300
NEGATIVE_CACHE_SECONDS = 45


@dataclass(frozen=True)
class SectionCommandMetric:
    label: str
    value: str
    key: str = ""
    detail: str = ""
    tone: str = "neutral"
    trend: str = ""
    unit: str = ""
    sort_order: int = 100
    numeric_value: float | None = None
    text_value: str = ""
    metric_format: str = ""
    trend_points: tuple[object, ...] = ()
    prior_value: float | None = None
    delta_numeric_value: float | None = None
    delta_percent: float | None = None
    trend_direction: str = ""
    directionality: str = "higher_is_worse"


@dataclass(frozen=True)
class SectionCommandSignal:
    severity: str
    signal: str
    entity: str = ""
    detail: str = ""
    route_section: str = ""
    route_workflow: str = ""
    priority_score: float | None = None
    impact_value: float | None = None
    impact_unit: str = ""
    owner_route: str = ""
    owner_gap: bool = False
    age_minutes: float | None = None
    sla_state: str = ""
    route_key: str = ""
    evidence_source: str = ""
    confidence: str = ""


@dataclass(frozen=True)
class SectionCommandAction:
    label: str
    detail: str
    target_section: str = ""
    target_workflow: str = ""
    session_state_updates: tuple[tuple[str, object], ...] = ()
    cta: str = ""
    action_key: str = ""
    route_key: str = ""


@dataclass(frozen=True)
class SectionCommandBrief:
    section: str
    company: str
    environment: str
    window_label: str
    state: str
    headline: str
    summary: str
    source: str
    freshness_label: str
    loaded_at: str
    metrics: tuple[SectionCommandMetric, ...] = ()
    top_signal: SectionCommandSignal | None = None
    exceptions: tuple[SectionCommandSignal, ...] = ()
    next_actions: tuple[SectionCommandAction, ...] = ()
    fallback_reason: str = ""
    detail_cta: str = ""
    detail_available: bool = False
    requested_company: str = ""
    requested_environment: str = ""
    requested_window_days: int = 0
    resolved_company: str = ""
    resolved_environment: str = ""
    resolved_window_days: int = 0
    source_objects: str = ""
    source_snapshot_ts: str = ""
    freshness_minutes: float | None = None
    target_freshness_minutes: int = 0
    stale: bool = False
    confidence: str = ""
    required_source_count: int = 0
    available_source_count: int = 0
    missing_source_count: int = 0
    source_coverage_pct: float | None = None
    data_availability_state: str = ""
    stale_source_count: int = 0
    source_gap_detail: str = ""
    cache_expires_at: str = ""
    app_query_loaded_at: str = ""
    command_brief_query_count: int = 0
    command_brief_elapsed_ms: float = 0.0
    command_brief_cache_hit: bool = False
    command_brief_session_cache_hit: bool = False
    command_brief_fallback_used: bool = False
    command_brief_packet_result_bytes: int = 0
    raw_payload: Mapping[str, object] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now()


def _now_label() -> str:
    return _now().isoformat(timespec="seconds")


def _expiry_label(seconds: int = SESSION_CACHE_SECONDS) -> str:
    return (_now() + timedelta(seconds=max(int(seconds), 1))).isoformat(timespec="seconds")


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _cache_key(section: str, company: str, environment: str, window_days: int) -> str:
    token = "::".join((str(section), str(company), str(environment), str(int(window_days))))
    return f"section_command_brief::{token}"


def _negative_key(key: str) -> str:
    return f"{key}::negative_until"


def _last_good_key(key: str) -> str:
    return f"{key}::last_good"


def _column(row: Mapping[str, object], *names: str, default: object = "") -> object:
    if not row:
        return default
    upper = {str(key).upper(): value for key, value in row.items()}
    for name in names:
        key = str(name).upper()
        if key in upper and upper[key] not in (None, ""):
            return upper[key]
    return default


def _string(value: object, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _float_or_none(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _bool_value(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return bool(default)


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _variant_records(value: object) -> list[Mapping[str, object]]:
    if value is None:
        return []
    if isinstance(value, str) and not value.strip():
        return []
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return []
    if isinstance(parsed, pd.Series):
        parsed = parsed.tolist()
    if isinstance(parsed, tuple):
        parsed = list(parsed)
    if not isinstance(parsed, list):
        return []
    records: list[Mapping[str, object]] = []
    for item in parsed:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except Exception:
                continue
        if isinstance(item, Mapping):
            records.append(item)
    return records


def _trend_points(value: object) -> tuple[object, ...]:
    points: list[object] = []
    if isinstance(value, str) and value.strip():
        try:
            value = json.loads(value)
        except Exception:
            value = []
    if isinstance(value, Mapping):
        value = value.get("points") or value.get("values") or []
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        return ()
    for item in value[:14]:
        if isinstance(item, Mapping):
            ts = item.get("ts", item.get("TS", item.get("date", item.get("DATE", ""))))
            numeric = _float_or_none(item.get("value", item.get("VALUE")))
            if numeric is not None:
                points.append({"ts": str(ts or ""), "value": numeric})
            continue
        numeric = _float_or_none(item)
        if numeric is not None:
            points.append(numeric)
    return tuple(points)


def _metric_from_row(row: Mapping[str, object]) -> SectionCommandMetric:
    numeric_value = _float_or_none(_column(row, "METRIC_NUMERIC_VALUE", "NUMERIC_VALUE"))
    text_value = _string(_column(row, "METRIC_TEXT_VALUE", "TEXT_VALUE"))
    value = _string(_column(row, "METRIC_VALUE", "VALUE"), text_value or "Unavailable")
    return SectionCommandMetric(
        key=_string(_column(row, "METRIC_KEY", "KEY")),
        label=_string(_column(row, "METRIC_LABEL", "LABEL"), "Metric"),
        value=value,
        detail=_string(_column(row, "METRIC_DETAIL", "DETAIL")),
        tone=_string(_column(row, "METRIC_TONE", "TONE"), "neutral").lower(),
        trend=_string(_column(row, "TREND_LABEL", "TREND")),
        unit=_string(_column(row, "METRIC_UNIT", "UNIT")),
        sort_order=_int_value(_column(row, "SORT_ORDER", default=100), 100),
        numeric_value=numeric_value,
        text_value=text_value,
        metric_format=_string(_column(row, "METRIC_FORMAT", "FORMAT")),
        trend_points=_trend_points(_column(row, "TREND_POINTS")),
        prior_value=_float_or_none(_column(row, "PRIOR_VALUE")),
        delta_numeric_value=_float_or_none(_column(row, "DELTA_NUMERIC_VALUE")),
        delta_percent=_float_or_none(_column(row, "DELTA_PERCENT")),
        trend_direction=_string(_column(row, "TREND_DIRECTION")),
        directionality=_string(_column(row, "DIRECTIONALITY"), "higher_is_worse"),
    )


def _signal_from_row(row: Mapping[str, object]) -> SectionCommandSignal:
    return SectionCommandSignal(
        severity=_string(_column(row, "SEVERITY", default="Info"), "Info"),
        signal=_string(_column(row, "SIGNAL", "TOP_SIGNAL"), "Review summary"),
        entity=_string(_column(row, "ENTITY_NAME", "TOP_ENTITY", "ENTITY")),
        detail=_string(_column(row, "DETAIL", "TOP_ACTION")),
        route_section=_string(_column(row, "ROUTE_SECTION")),
        route_workflow=_string(_column(row, "ROUTE_WORKFLOW")),
        priority_score=_float_or_none(_column(row, "PRIORITY_SCORE")),
        impact_value=_float_or_none(_column(row, "IMPACT_VALUE")),
        impact_unit=_string(_column(row, "IMPACT_UNIT")),
        owner_route=_string(_column(row, "OWNER_ROUTE")),
        owner_gap=_bool_value(_column(row, "OWNER_GAP", default=False)),
        age_minutes=_float_or_none(_column(row, "AGE_MINUTES")),
        sla_state=_string(_column(row, "SLA_STATE")),
        route_key=_string(_column(row, "ROUTE_KEY")),
        evidence_source=_string(_column(row, "EVIDENCE_SOURCE")),
        confidence=_string(_column(row, "CONFIDENCE")),
    )


def _action_from_row(row: Mapping[str, object]) -> SectionCommandAction:
    return SectionCommandAction(
        label=_string(_column(row, "ACTION_LABEL", "LABEL"), "Open workflow"),
        detail=_string(_column(row, "ACTION_DETAIL", "DETAIL"), "Route to the next workflow."),
        target_section=_string(_column(row, "TARGET_SECTION", "ROUTE_SECTION")),
        target_workflow=_string(_column(row, "TARGET_WORKFLOW", "ROUTE_WORKFLOW")),
        cta=_string(_column(row, "CTA_LABEL", "CTA"), "Open"),
        action_key=_string(_column(row, "ACTION_KEY")),
        route_key=_string(_column(row, "ROUTE_KEY")),
    )


def _default_actions(contract: SectionCommandContract) -> tuple[SectionCommandAction, ...]:
    return tuple(
        SectionCommandAction(
            label=label,
            detail=detail,
            target_section=target_section or contract.section,
            target_workflow=target_workflow,
            cta=label,
            action_key=label.lower().replace(" ", "_"),
            route_key=contract.fallback_route_keys[index] if index < len(contract.fallback_route_keys) else "",
        )
        for index, (label, detail, target_section, target_workflow) in enumerate(contract.next_actions[:3])
    )


def _fallback_brief(
    contract: SectionCommandContract,
    *,
    company: str,
    environment: str,
    window_days: int,
    reason: str,
    last_known_good: SectionCommandBrief | None = None,
) -> SectionCommandBrief:
    if isinstance(last_known_good, SectionCommandBrief) and not last_known_good.fallback_reason:
        return replace(
            last_known_good,
            stale=True,
            state="Stale",
            freshness_label=f"Last known good retained. {reason}",
            fallback_reason=reason,
            command_brief_cache_hit=False,
            command_brief_session_cache_hit=False,
            command_brief_fallback_used=True,
        )
    loaded_at = _now_label()
    return SectionCommandBrief(
        section=contract.section,
        company=str(company),
        environment=str(environment),
        window_label=f"{int(window_days)} days",
        state="Summary unavailable",
        headline=contract.unavailable_headline,
        summary=contract.unavailable_summary,
        source=contract.source_table,
        freshness_label="Mart summary unavailable",
        loaded_at=loaded_at,
        metrics=(),
        top_signal=SectionCommandSignal(
            severity="Setup",
            signal=contract.top_signal_label,
            entity=contract.source_table,
            detail=contract.top_signal_detail,
            route_section=contract.section,
            route_workflow=contract.default_view,
        ),
        exceptions=(),
        next_actions=_default_actions(contract),
        fallback_reason=reason or "Mart summary unavailable; live fallback disabled for speed.",
        detail_cta=contract.detail_cta,
        detail_available=False,
        requested_company=str(company),
        requested_environment=str(environment),
        requested_window_days=int(window_days),
        resolved_company="",
        resolved_environment="",
        resolved_window_days=int(window_days),
        source_objects=contract.source_table,
        target_freshness_minutes=int(contract.target_freshness_minutes),
        stale=True,
        confidence="unavailable",
        required_source_count=len(contract.required_sources),
        available_source_count=0,
        missing_source_count=len(contract.required_sources),
        source_coverage_pct=0.0,
        data_availability_state="Data Gap",
        stale_source_count=0,
        source_gap_detail="; ".join(contract.required_sources),
        cache_expires_at=_expiry_label(NEGATIVE_CACHE_SECONDS),
        app_query_loaded_at=loaded_at,
        command_brief_query_count=0,
        command_brief_fallback_used=True,
        raw_payload={},
    )


def _scoped_where(section: str, company: str, environment: str, window_days: int) -> str:
    return f"""
        UPPER(SECTION_NAME) = UPPER({sql_literal(section, 120)})
        AND (UPPER(COMPANY) = UPPER({sql_literal(company, 100)}) OR UPPER(COMPANY) IN ('ALL', 'GLOBAL'))
        AND (
            UPPER(ENVIRONMENT) = UPPER({sql_literal(environment, 100)})
            OR UPPER(ENVIRONMENT) IN ('ALL', 'ALL ENVIRONMENTS', 'GLOBAL')
        )
        AND (WINDOW_DAYS = {int(window_days)} OR WINDOW_DAYS IS NULL)
    """


def _packet_sql(section: str, company: str, environment: str, window_days: int) -> str:
    current_table = mart_object_name("MART_SECTION_DECISION_CURRENT")
    where = _scoped_where(section, company, environment, window_days)
    return f"""
SELECT
    DECISION_PACKET:"BRIEF_ID"::VARCHAR AS BRIEF_ID,
    DECISION_PACKET:"SECTION_NAME"::VARCHAR AS SECTION_NAME,
    DECISION_PACKET:"COMPANY"::VARCHAR AS COMPANY,
    DECISION_PACKET:"ENVIRONMENT"::VARCHAR AS ENVIRONMENT,
    DECISION_PACKET:"WINDOW_DAYS"::NUMBER AS WINDOW_DAYS,
    DECISION_PACKET:"SNAPSHOT_TS"::TIMESTAMP_NTZ AS SNAPSHOT_TS,
    DECISION_PACKET:"STATE"::VARCHAR AS STATE,
    DECISION_PACKET:"HEADLINE"::VARCHAR AS HEADLINE,
    DECISION_PACKET:"SUMMARY"::VARCHAR AS SUMMARY,
    DECISION_PACKET:"TOP_SIGNAL"::VARCHAR AS TOP_SIGNAL,
    DECISION_PACKET:"TOP_ENTITY"::VARCHAR AS TOP_ENTITY,
    DECISION_PACKET:"TOP_ACTION"::VARCHAR AS TOP_ACTION,
    DECISION_PACKET:"SOURCE_STATUS"::VARCHAR AS SOURCE_STATUS,
    DECISION_PACKET:"SOURCE_FRESHNESS"::VARCHAR AS SOURCE_FRESHNESS,
    DECISION_PACKET:"SOURCE_OBJECTS"::VARCHAR AS SOURCE_OBJECTS,
    DECISION_PACKET:"SOURCE_SNAPSHOT_TS"::TIMESTAMP_NTZ AS SOURCE_SNAPSHOT_TS,
    DECISION_PACKET:"FRESHNESS_MINUTES"::NUMBER AS FRESHNESS_MINUTES,
    DECISION_PACKET:"TARGET_FRESHNESS_MINUTES"::NUMBER AS TARGET_FRESHNESS_MINUTES,
    DECISION_PACKET:"IS_STALE"::BOOLEAN AS IS_STALE,
    DECISION_PACKET:"RESOLVED_COMPANY"::VARCHAR AS RESOLVED_COMPANY,
    DECISION_PACKET:"RESOLVED_ENVIRONMENT"::VARCHAR AS RESOLVED_ENVIRONMENT,
    DECISION_PACKET:"RESOLVED_WINDOW_DAYS"::NUMBER AS RESOLVED_WINDOW_DAYS,
    DECISION_PACKET:"CONFIDENCE"::VARCHAR AS CONFIDENCE,
    DECISION_PACKET:"REQUIRED_SOURCE_COUNT"::NUMBER AS REQUIRED_SOURCE_COUNT,
    DECISION_PACKET:"AVAILABLE_SOURCE_COUNT"::NUMBER AS AVAILABLE_SOURCE_COUNT,
    DECISION_PACKET:"MISSING_SOURCE_COUNT"::NUMBER AS MISSING_SOURCE_COUNT,
    DECISION_PACKET:"SOURCE_COVERAGE_PCT"::NUMBER AS SOURCE_COVERAGE_PCT,
    DECISION_PACKET:"DATA_AVAILABILITY_STATE"::VARCHAR AS DATA_AVAILABILITY_STATE,
    DECISION_PACKET:"STALE_SOURCE_COUNT"::NUMBER AS STALE_SOURCE_COUNT,
    DECISION_PACKET:"SOURCE_GAP_DETAIL"::VARCHAR AS SOURCE_GAP_DETAIL,
    DECISION_PACKET:"PRIMARY_ACTION_KEY"::VARCHAR AS PRIMARY_ACTION_KEY,
    DECISION_PACKET:"PRIMARY_ROUTE_KEY"::VARCHAR AS PRIMARY_ROUTE_KEY,
    DECISION_PACKET:"PRIMARY_ACTION_LABEL"::VARCHAR AS PRIMARY_ACTION_LABEL,
    DECISION_PACKET:"PRIMARY_ACTION_DETAIL"::VARCHAR AS PRIMARY_ACTION_DETAIL,
    DECISION_PACKET:"LOAD_TS"::TIMESTAMP_NTZ AS LOAD_TS,
    DECISION_PACKET:"METRICS" AS METRICS,
    DECISION_PACKET:"EXCEPTIONS" AS EXCEPTIONS,
    DECISION_PACKET:"ACTIONS" AS ACTIONS
    FROM {current_table}
    WHERE {where}
    ORDER BY
        IFF(UPPER(COMPANY) = UPPER({sql_literal(company, 100)}), 1, 0) DESC,
        IFF(UPPER(ENVIRONMENT) = UPPER({sql_literal(environment, 100)}), 1, 0) DESC,
        IFF(WINDOW_DAYS = {int(window_days)}, 1, 0) DESC,
        SNAPSHOT_TS DESC,
        LOAD_TS DESC
LIMIT 1
"""


def _load_packet(
    section: str,
    company: str,
    environment: str,
    window_days: int,
    *,
    force: bool = False,
) -> tuple[pd.DataFrame, float]:
    sql = _packet_sql(section, company, environment, window_days)
    started = time.perf_counter()
    df = run_query(
        sql,
        ttl_key=f"section_command_packet_{section}_{company}_{environment}_{int(window_days)}",
        tier="command_summary",
        section="Command Brief",
        use_cache=not bool(force),
        max_rows=1,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    return df, elapsed_ms


def _brief_from_packet(
    contract: SectionCommandContract,
    *,
    company: str,
    environment: str,
    window_days: int,
    packet: pd.DataFrame,
    elapsed_ms: float,
    cache_hit: bool,
) -> SectionCommandBrief:
    row = packet.iloc[0].to_dict()
    metrics = tuple(_metric_from_row(item) for item in _variant_records(_column(row, "METRICS")))
    exceptions = tuple(_signal_from_row(item) for item in _variant_records(_column(row, "EXCEPTIONS")))
    top_signal = exceptions[0] if exceptions else SectionCommandSignal(
        severity=_string(_column(row, "STATE"), "Clear"),
        signal=_string(_column(row, "TOP_SIGNAL"), contract.top_signal_label),
        entity=_string(_column(row, "TOP_ENTITY")),
        detail=_string(_column(row, "TOP_ACTION"), contract.top_signal_detail),
    )
    packet_actions = tuple(_action_from_row(item) for item in _variant_records(_column(row, "ACTIONS")))
    primary_route_key = _string(_column(row, "PRIMARY_ROUTE_KEY"))
    primary_label = _string(_column(row, "PRIMARY_ACTION_LABEL"))
    primary_detail = _string(_column(row, "PRIMARY_ACTION_DETAIL"))
    primary_action = (
        SectionCommandAction(
            label=primary_label or _string(_column(row, "TOP_SIGNAL"), "Open top route"),
            detail=primary_detail or _string(_column(row, "TOP_ACTION"), "Open the highest-priority route."),
            cta=primary_label or "Open top route",
            action_key=_string(_column(row, "PRIMARY_ACTION_KEY"), "primary_action"),
            route_key=primary_route_key,
        )
        if primary_route_key
        else None
    )
    actions = ((primary_action,) if primary_action else ()) + packet_actions
    actions = actions or _default_actions(contract)
    loaded_at = _string(_column(row, "LOAD_TS", "SNAPSHOT_TS"), _now_label())
    source_status = _string(_column(row, "SOURCE_STATUS"), "Summary loaded from mart")
    source_freshness = _string(_column(row, "SOURCE_FRESHNESS"), loaded_at)
    resolved_company = _string(_column(row, "RESOLVED_COMPANY", "COMPANY"), str(company))
    resolved_environment = _string(_column(row, "RESOLVED_ENVIRONMENT", "ENVIRONMENT"), str(environment))
    resolved_window = _int_value(_column(row, "RESOLVED_WINDOW_DAYS", "WINDOW_DAYS", default=window_days), int(window_days))
    freshness_minutes = _float_or_none(_column(row, "FRESHNESS_MINUTES"))
    target_freshness = _int_value(_column(row, "TARGET_FRESHNESS_MINUTES", default=contract.target_freshness_minutes), contract.target_freshness_minutes)
    stale = _bool_value(_column(row, "IS_STALE", default=False)) or (
        freshness_minutes is not None and target_freshness > 0 and freshness_minutes > target_freshness
    )
    required_source_count = _int_value(_column(row, "REQUIRED_SOURCE_COUNT"), 0)
    available_source_count = _int_value(_column(row, "AVAILABLE_SOURCE_COUNT"), 0)
    missing_source_count = _int_value(_column(row, "MISSING_SOURCE_COUNT"), 0)
    stale_source_count = _int_value(_column(row, "STALE_SOURCE_COUNT"), 0)
    source_coverage_pct = _float_or_none(_column(row, "SOURCE_COVERAGE_PCT"))
    data_availability_state = _string(_column(row, "DATA_AVAILABILITY_STATE"))
    source_gap_detail = _string(_column(row, "SOURCE_GAP_DETAIL"))
    scope_note = f"Requested: {company} / {environment} / {int(window_days)} days"
    if (
        resolved_company.upper() != str(company).upper()
        or resolved_environment.upper() != str(environment).upper()
        or resolved_window != int(window_days)
    ):
        scope_note += f" | Resolved: {resolved_company} / {resolved_environment} / {resolved_window} days"
    return SectionCommandBrief(
        section=contract.section,
        company=str(company),
        environment=str(environment),
        window_label=f"{int(window_days)} days",
        state=_string(_column(row, "STATE"), "Summary loaded"),
        headline=_string(_column(row, "HEADLINE"), f"{contract.section} command brief is loaded."),
        summary=_string(_column(row, "SUMMARY"), "Review the top signal and next action."),
        source="MART_SECTION_COMMAND_BRIEF",
        freshness_label=f"{source_status} | {source_freshness} | {scope_note}",
        loaded_at=loaded_at,
        metrics=metrics,
        top_signal=top_signal,
        exceptions=exceptions,
        next_actions=actions[:3],
        fallback_reason="",
        detail_cta=contract.detail_cta,
        detail_available=True,
        requested_company=str(company),
        requested_environment=str(environment),
        requested_window_days=int(window_days),
        resolved_company=resolved_company,
        resolved_environment=resolved_environment,
        resolved_window_days=resolved_window,
        source_objects=_string(_column(row, "SOURCE_OBJECTS"), contract.source_table),
        source_snapshot_ts=_string(_column(row, "SOURCE_SNAPSHOT_TS", "SNAPSHOT_TS")),
        freshness_minutes=freshness_minutes,
        target_freshness_minutes=target_freshness,
        stale=stale,
        confidence=_string(_column(row, "CONFIDENCE"), "unknown"),
        required_source_count=required_source_count,
        available_source_count=available_source_count,
        missing_source_count=missing_source_count,
        source_coverage_pct=source_coverage_pct,
        data_availability_state=data_availability_state,
        stale_source_count=stale_source_count,
        source_gap_detail=source_gap_detail,
        cache_expires_at=_expiry_label(),
        app_query_loaded_at=_now_label(),
        command_brief_query_count=0 if cache_hit else 1,
        command_brief_elapsed_ms=round(float(elapsed_ms or 0), 2),
        command_brief_cache_hit=bool(cache_hit),
        command_brief_session_cache_hit=bool(cache_hit),
        command_brief_fallback_used=False,
        command_brief_packet_result_bytes=len(str(row).encode("utf-8", errors="ignore")),
        raw_payload=row,
    )


def _session_brief_is_current(brief: object) -> bool:
    if not isinstance(brief, SectionCommandBrief):
        return False
    expires_at = _parse_dt(brief.cache_expires_at)
    return expires_at is not None and expires_at > _now()


def _record_telemetry(brief: SectionCommandBrief) -> None:
    telemetry = {
        "command_brief_query_count": int(brief.command_brief_query_count or 0),
        "command_brief_elapsed_ms": float(brief.command_brief_elapsed_ms or 0),
        "command_brief_cache_hit": bool(brief.command_brief_cache_hit),
        "command_brief_session_cache_hit": bool(brief.command_brief_session_cache_hit),
        "command_brief_source_age_minutes": brief.freshness_minutes,
        "command_brief_source_coverage_pct": brief.source_coverage_pct,
        "command_brief_fallback_used": bool(brief.command_brief_fallback_used),
        "command_brief_stale_used": bool(brief.stale),
        "command_brief_packet_result_bytes": int(brief.command_brief_packet_result_bytes or 0),
        "command_brief_section": brief.section,
        "command_brief_requested_scope": f"{brief.requested_company}/{brief.requested_environment}/{brief.requested_window_days}",
        "command_brief_resolved_scope": f"{brief.resolved_company}/{brief.resolved_environment}/{brief.resolved_window_days}",
    }
    try:
        st.session_state["section_command_brief_last_telemetry"] = telemetry
        entries = st.session_state.setdefault("section_command_brief_telemetry", [])
        entries.append({**telemetry, "timestamp": _now_label()})
        if len(entries) > 100:
            del entries[:-100]
    except Exception:
        pass


def autoload_section_command_brief(
    section: str,
    company: str,
    environment: str,
    window_days: int,
    *,
    force: bool = False,
) -> SectionCommandBrief:
    """Return a session-cached or mart-backed command brief without loading detail rows."""
    contract = get_section_command_contract(section)
    key = _cache_key(contract.section, company, environment, int(window_days))
    cached = st.session_state.get(key)
    if not force and _session_brief_is_current(cached):
        brief = replace(
            cached,
            command_brief_cache_hit=True,
            command_brief_session_cache_hit=True,
            command_brief_query_count=0,
        )
        _record_telemetry(brief)
        return brief

    negative_until = _parse_dt(st.session_state.get(_negative_key(key)))
    last_good = st.session_state.get(_last_good_key(key))
    if not force and negative_until is not None and negative_until > _now():
        brief = _fallback_brief(
            contract,
            company=company,
            environment=environment,
            window_days=int(window_days),
            reason="Command brief summary unavailable; retry window is still open.",
            last_known_good=last_good if isinstance(last_good, SectionCommandBrief) else None,
        )
        _record_telemetry(brief)
        return brief

    try:
        packet, elapsed_ms = _load_packet(
            contract.section,
            str(company),
            str(environment),
            int(window_days),
            force=force,
        )
        if packet.empty:
            st.session_state[_negative_key(key)] = _expiry_label(NEGATIVE_CACHE_SECONDS)
            brief = _fallback_brief(
                contract,
                company=company,
                environment=environment,
                window_days=int(window_days),
                reason=f"The command brief mart has no current row for {company} / {environment} / {int(window_days)} days.",
                last_known_good=last_good if isinstance(last_good, SectionCommandBrief) else None,
            )
        else:
            brief = _brief_from_packet(
                contract,
                company=company,
                environment=environment,
                window_days=int(window_days),
                packet=packet,
                elapsed_ms=elapsed_ms,
                cache_hit=False,
            )
            st.session_state[key] = brief
            st.session_state[_last_good_key(key)] = brief
            st.session_state.pop(_negative_key(key), None)
    except Exception as exc:
        st.session_state[_negative_key(key)] = _expiry_label(NEGATIVE_CACHE_SECONDS)
        brief = _fallback_brief(
            contract,
            company=company,
            environment=environment,
            window_days=int(window_days),
            reason=f"Mart summary unavailable; live fallback disabled for speed. {exc}",
            last_known_good=last_good if isinstance(last_good, SectionCommandBrief) else None,
        )
    _record_telemetry(brief)
    return brief


__all__ = [
    "SectionCommandAction",
    "SectionCommandBrief",
    "SectionCommandMetric",
    "SectionCommandSignal",
    "autoload_section_command_brief",
]
