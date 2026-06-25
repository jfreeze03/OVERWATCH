"""Mart-backed command brief loader for primary OVERWATCH sections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import json

import pandas as pd
import streamlit as st

from sections.command_deck_contracts import get_command_deck_contract
from sections.section_command_contracts import SectionCommandContract, get_section_command_contract
from utils.mart_names import mart_object_name
from utils.query import run_query, sql_literal


@dataclass(frozen=True)
class SectionCommandMetric:
    label: str
    value: str
    detail: str = ""
    tone: str = "neutral"
    trend: str = ""
    unit: str = ""
    sort_order: int = 100


@dataclass(frozen=True)
class SectionCommandSignal:
    severity: str
    signal: str
    entity: str = ""
    detail: str = ""
    route_section: str = ""
    route_workflow: str = ""


@dataclass(frozen=True)
class SectionCommandAction:
    label: str
    detail: str
    target_section: str = ""
    target_workflow: str = ""
    session_state_updates: tuple[tuple[str, object], ...] = ()
    cta: str = ""


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
    raw_payload: Mapping[str, object] = field(default_factory=dict)


def _now_label() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cache_key(section: str, company: str, environment: str, window_days: int) -> str:
    token = "::".join((str(section), str(company), str(environment), str(int(window_days))))
    return f"section_command_brief::{token}"


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


def _metric_from_row(row: Mapping[str, object]) -> SectionCommandMetric:
    return SectionCommandMetric(
        label=_string(_column(row, "METRIC_LABEL", "LABEL"), "Metric"),
        value=_string(_column(row, "METRIC_VALUE", "VALUE"), "Unavailable"),
        detail=_string(_column(row, "METRIC_DETAIL", "DETAIL")),
        tone=_string(_column(row, "METRIC_TONE", "TONE"), "neutral").lower(),
        trend=_string(_column(row, "TREND_LABEL", "TREND")),
        unit=_string(_column(row, "METRIC_UNIT", "UNIT")),
        sort_order=int(float(_column(row, "SORT_ORDER", default=100) or 100)),
    )


def _signal_from_row(row: Mapping[str, object]) -> SectionCommandSignal:
    return SectionCommandSignal(
        severity=_string(_column(row, "SEVERITY", default="Info"), "Info"),
        signal=_string(_column(row, "SIGNAL", "TOP_SIGNAL"), "Review summary"),
        entity=_string(_column(row, "ENTITY_NAME", "TOP_ENTITY", "ENTITY")),
        detail=_string(_column(row, "DETAIL", "TOP_ACTION")),
        route_section=_string(_column(row, "ROUTE_SECTION")),
        route_workflow=_string(_column(row, "ROUTE_WORKFLOW")),
    )


def _action_from_row(row: Mapping[str, object]) -> SectionCommandAction:
    updates: tuple[tuple[str, object], ...] = ()
    raw_updates = _string(_column(row, "SESSION_STATE_UPDATES_JSON"))
    if raw_updates:
        try:
            parsed = json.loads(raw_updates)
            if isinstance(parsed, dict):
                updates = tuple((str(key), value) for key, value in parsed.items())
        except Exception:
            updates = ()
    return SectionCommandAction(
        label=_string(_column(row, "ACTION_LABEL", "LABEL"), "Open workflow"),
        detail=_string(_column(row, "ACTION_DETAIL", "DETAIL"), "Route to the next workflow."),
        target_section=_string(_column(row, "TARGET_SECTION", "ROUTE_SECTION")),
        target_workflow=_string(_column(row, "TARGET_WORKFLOW", "ROUTE_WORKFLOW")),
        session_state_updates=updates,
        cta=_string(_column(row, "CTA"), "Open"),
    )


def _default_actions(contract: SectionCommandContract) -> tuple[SectionCommandAction, ...]:
    deck_actions = ()
    try:
        deck_actions = tuple(get_command_deck_contract(contract.section).route_actions or ())
    except Exception:
        deck_actions = ()
    if deck_actions:
        return tuple(
            SectionCommandAction(
                label=str(action.label),
                detail=str(action.description),
                target_section=str(action.target_section or contract.section),
                target_workflow=str(action.target_workflow or ""),
                session_state_updates=tuple(action.session_state_updates or ()),
                cta=str(action.label),
            )
            for action in deck_actions[:3]
        )
    return tuple(
        SectionCommandAction(
            label=label,
            detail=detail,
            target_section=target_section or contract.section,
            target_workflow=target_workflow,
            cta=label,
        )
        for label, detail, target_section, target_workflow in contract.next_actions[:3]
    )


def _fallback_metrics(contract: SectionCommandContract) -> tuple[SectionCommandMetric, ...]:
    return tuple(
        SectionCommandMetric(
            label=label,
            value="Summary unavailable" if idx == 0 else "Setup required",
            detail=(
                "Command brief mart is unavailable for this scope."
                if idx == 0
                else "Heavy detail remains behind explicit load."
            ),
            tone="warning" if idx == 0 else "neutral",
            sort_order=idx * 10,
        )
        for idx, label in enumerate(contract.metric_labels[:8])
    )


def _fallback_brief(
    contract: SectionCommandContract,
    *,
    company: str,
    environment: str,
    window_days: int,
    reason: str,
) -> SectionCommandBrief:
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
        freshness_label="Summary mart unavailable",
        loaded_at=loaded_at,
        metrics=_fallback_metrics(contract),
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


def _latest_brief_rows(section: str, company: str, environment: str, window_days: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    brief_table = mart_object_name("MART_SECTION_COMMAND_BRIEF")
    metric_table = mart_object_name("MART_SECTION_COMMAND_METRIC")
    exception_table = mart_object_name("MART_SECTION_COMMAND_EXCEPTION")
    action_table = mart_object_name("MART_SECTION_COMMAND_ACTION")
    where = _scoped_where(section, company, environment, window_days)
    common_order = f"""
        IFF(UPPER(COMPANY) = UPPER({sql_literal(company, 100)}), 1, 0) DESC,
        IFF(UPPER(ENVIRONMENT) = UPPER({sql_literal(environment, 100)}), 1, 0) DESC,
        IFF(WINDOW_DAYS = {int(window_days)}, 1, 0) DESC,
        SNAPSHOT_TS DESC,
        LOAD_TS DESC
    """
    brief_sql = f"""
        SELECT *
        FROM {brief_table}
        WHERE {where}
        ORDER BY {common_order}
        LIMIT 1
    """
    brief = run_query(brief_sql, ttl_key=f"section_command_brief_{section}", tier="historical", section="Command Brief")
    if brief.empty:
        return brief, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    row = brief.iloc[0].to_dict()
    snapshot_ts = _column(row, "SNAPSHOT_TS")
    snapshot_filter = ""
    if snapshot_ts not in (None, ""):
        snapshot_filter = f"AND SNAPSHOT_TS = TO_TIMESTAMP_NTZ({sql_literal(str(snapshot_ts), 80)})"
    metric_sql = f"""
        SELECT *
        FROM {metric_table}
        WHERE {where}
          {snapshot_filter}
        ORDER BY SORT_ORDER, METRIC_LABEL
        LIMIT 8
    """
    exception_sql = f"""
        SELECT *
        FROM {exception_table}
        WHERE {where}
          {snapshot_filter}
        ORDER BY SORT_ORDER, SEVERITY, SIGNAL
        LIMIT 5
    """
    action_sql = f"""
        SELECT *
        FROM {action_table}
        WHERE {where}
          {snapshot_filter}
        ORDER BY SORT_ORDER, ACTION_LABEL
        LIMIT 4
    """
    metrics = run_query(metric_sql, ttl_key=f"section_command_metric_{section}", tier="historical", section="Command Brief")
    exceptions = run_query(exception_sql, ttl_key=f"section_command_exception_{section}", tier="historical", section="Command Brief")
    actions = run_query(action_sql, ttl_key=f"section_command_action_{section}", tier="historical", section="Command Brief")
    return brief, metrics, exceptions, actions


def _brief_from_rows(
    contract: SectionCommandContract,
    *,
    company: str,
    environment: str,
    window_days: int,
    brief_rows: pd.DataFrame,
    metric_rows: pd.DataFrame,
    exception_rows: pd.DataFrame,
    action_rows: pd.DataFrame,
) -> SectionCommandBrief:
    row = brief_rows.iloc[0].to_dict()
    metrics = tuple(_metric_from_row(item) for item in metric_rows.to_dict("records"))
    if not metrics:
        metrics = _fallback_metrics(contract)
    exceptions = tuple(_signal_from_row(item) for item in exception_rows.to_dict("records"))
    top_signal = exceptions[0] if exceptions else SectionCommandSignal(
        severity=_string(_column(row, "STATE"), "Clear"),
        signal=_string(_column(row, "TOP_SIGNAL"), contract.top_signal_label),
        entity=_string(_column(row, "TOP_ENTITY")),
        detail=_string(_column(row, "TOP_ACTION"), contract.top_signal_detail),
    )
    actions = tuple(_action_from_row(item) for item in action_rows.to_dict("records")) or _default_actions(contract)
    loaded_at = _string(_column(row, "LOAD_TS", "SNAPSHOT_TS"), _now_label())
    source_status = _string(_column(row, "SOURCE_STATUS"), "Summary loaded from mart")
    source_freshness = _string(_column(row, "SOURCE_FRESHNESS"), loaded_at)
    return SectionCommandBrief(
        section=contract.section,
        company=str(company),
        environment=str(environment),
        window_label=f"{int(window_days)} days",
        state=_string(_column(row, "STATE"), "Summary loaded"),
        headline=_string(_column(row, "HEADLINE"), f"{contract.section} command brief is loaded."),
        summary=_string(_column(row, "SUMMARY"), "Review the top signal and next action."),
        source=contract.source_table,
        freshness_label=f"{source_status} | {source_freshness}",
        loaded_at=loaded_at,
        metrics=metrics,
        top_signal=top_signal,
        exceptions=exceptions,
        next_actions=actions[:4],
        fallback_reason="",
        detail_cta=contract.detail_cta,
        detail_available=True,
        raw_payload=row,
    )


def autoload_section_command_brief(
    section: str,
    company: str,
    environment: str,
    window_days: int,
    *,
    force: bool = False,
    allow_live_fallback: bool = False,
) -> SectionCommandBrief:
    """Return a cached or mart-backed section command brief without loading detail rows."""
    _ = allow_live_fallback
    contract = get_section_command_contract(section)
    key = _cache_key(contract.section, company, environment, int(window_days))
    cached = st.session_state.get(key)
    if isinstance(cached, SectionCommandBrief) and not force:
        return cached
    try:
        brief_rows, metric_rows, exception_rows, action_rows = _latest_brief_rows(
            contract.section,
            str(company),
            str(environment),
            int(window_days),
        )
        if brief_rows.empty:
            brief = _fallback_brief(
                contract,
                company=company,
                environment=environment,
                window_days=int(window_days),
                reason="No command brief rows matched the active scope.",
            )
        else:
            brief = _brief_from_rows(
                contract,
                company=company,
                environment=environment,
                window_days=int(window_days),
                brief_rows=brief_rows,
                metric_rows=metric_rows,
                exception_rows=exception_rows,
                action_rows=action_rows,
            )
    except Exception as exc:
        brief = _fallback_brief(
            contract,
            company=company,
            environment=environment,
            window_days=int(window_days),
            reason=f"Mart summary unavailable; live fallback disabled for speed. {exc}",
        )
    st.session_state[key] = brief
    st.session_state[f"{key}::loaded_at"] = brief.loaded_at
    return brief


__all__ = [
    "SectionCommandAction",
    "SectionCommandBrief",
    "SectionCommandMetric",
    "SectionCommandSignal",
    "autoload_section_command_brief",
]
