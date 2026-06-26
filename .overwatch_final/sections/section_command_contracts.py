"""Import-safe Decision Brief contract helpers.

The authoritative contract data lives in ``config/decision_brief_contracts.json``.
``scripts/generate_decision_brief_contracts.py`` turns that manifest into
``section_command_contracts_generated.py`` and SQL validation snippets. This
module intentionally keeps the historical public dataclasses and helper names so
existing app code and tests do not care whether contracts are hand-written or
generated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from sections.first_paint_contracts import get_first_paint_contract


@dataclass(frozen=True)
class SectionCommandSource:
    source_key: str
    source_object: str
    required: bool = True
    target_freshness_minutes: int = 60
    default_confidence: str = "allocated"


@dataclass(frozen=True)
class SectionCommandMetricContract:
    key: str
    label: str
    primary: bool = False
    metric_format: str = "integer"
    unit: str = ""
    directionality: str = "higher_is_worse"
    source_key: str = ""
    availability_policy: str = "optional"


@dataclass(frozen=True)
class SectionCommandContract:
    """Static copy and fallback shape for an auto-populated Decision Brief."""

    section: str
    default_view: str
    detail_cta: str
    metric_labels: tuple[str, ...]
    expected_lanes: tuple[str, ...]
    source_table: str
    required_sources: tuple[str, ...]
    source_configs: tuple[SectionCommandSource, ...]
    target_freshness_minutes: int
    metric_keys: tuple[str, ...]
    primary_metric_keys: tuple[str, ...]
    metric_contracts: tuple[SectionCommandMetricContract, ...]
    unavailable_headline: str
    unavailable_summary: str
    top_signal_label: str
    top_signal_detail: str
    next_actions: tuple[tuple[str, str, str, str], ...]
    fallback_route_keys: tuple[str, ...] = ()


def _contract(
    section: str,
    *,
    metric_labels: tuple[str, ...],
    source_table: str,
    source_configs: tuple[SectionCommandSource, ...],
    target_freshness_minutes: int,
    unavailable_headline: str,
    unavailable_summary: str,
    top_signal_label: str,
    top_signal_detail: str,
    next_actions: tuple[tuple[str, str, str, str], ...],
    metric_contracts: tuple[SectionCommandMetricContract, ...],
    fallback_route_keys: tuple[str, ...],
) -> SectionCommandContract:
    first_paint = get_first_paint_contract(section)
    required_sources = tuple(source.source_object for source in source_configs if source.required)
    return SectionCommandContract(
        section=first_paint.section,
        default_view=first_paint.default_view,
        detail_cta=first_paint.explicit_load_cta,
        metric_labels=metric_labels,
        expected_lanes=first_paint.expected_lanes,
        source_table=source_table,
        required_sources=required_sources,
        source_configs=source_configs,
        target_freshness_minutes=int(target_freshness_minutes),
        metric_keys=tuple(metric.key for metric in metric_contracts),
        primary_metric_keys=tuple(metric.key for metric in metric_contracts if metric.primary),
        metric_contracts=metric_contracts,
        unavailable_headline=unavailable_headline,
        unavailable_summary=unavailable_summary,
        top_signal_label=top_signal_label,
        top_signal_detail=top_signal_detail,
        next_actions=next_actions,
        fallback_route_keys=fallback_route_keys,
    )


def _sources(
    section_target: int,
    *sources: tuple[str, str, bool, str] | tuple[str, str, bool],
) -> tuple[SectionCommandSource, ...]:
    rows: list[SectionCommandSource] = []
    for item in sources:
        source_key, source_object, required, *rest = item
        rows.append(
            SectionCommandSource(
                source_key=source_key,
                source_object=source_object,
                required=bool(required),
                target_freshness_minutes=section_target,
                default_confidence=str(rest[0]) if rest else "allocated",
            )
        )
    return tuple(rows)


def _metrics(*items: tuple[str, ...]) -> tuple[SectionCommandMetricContract, ...]:
    metrics: list[SectionCommandMetricContract] = []
    for item in items:
        key, label, primary, metric_format, unit, directionality, *rest = item
        source_key = rest[0] if len(rest) >= 1 else ""
        availability_policy = rest[1] if len(rest) >= 2 else "optional"
        metrics.append(
            SectionCommandMetricContract(
                key=key,
                label=label,
                primary=bool(primary),
                metric_format=metric_format,
                unit=unit,
                directionality=directionality,
                source_key=source_key,
                availability_policy=availability_policy,
            )
        )
    return tuple(metrics)


from sections.section_command_contracts_generated import (  # noqa: E402
    CANONICAL_COMMAND_BRIEF_SECTIONS,
    SECTION_COMMAND_CONTRACTS,
)


def get_section_command_contract(section: str) -> SectionCommandContract:
    """Return the Decision Brief contract for a primary section."""
    return SECTION_COMMAND_CONTRACTS[str(section)]


__all__ = [
    "CANONICAL_COMMAND_BRIEF_SECTIONS",
    "SECTION_COMMAND_CONTRACTS",
    "SectionCommandMetricContract",
    "SectionCommandSource",
    "SectionCommandContract",
    "get_section_command_contract",
]
