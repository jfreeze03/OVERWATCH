# sections/cost_contract_rendering.py - Shared Cost & Contract render helpers.
from __future__ import annotations

from importlib import import_module

import streamlit as st

from utils.section_guidance import defer_section_note, defer_source_note


def _freshness_note(source: str) -> str:
    source_key = str(source or "").lower()
    if "information_schema" in source_key or source_key in {"live", "is"}:
        return "Freshness: live INFORMATION_SCHEMA view"
    if "organization_usage" in source_key:
        return "Freshness: ORGANIZATION_USAGE can lag several hours"
    if "account_usage" in source_key or "warehouse_metering_history" in source_key:
        return "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes"
    if "mart" in source_key or "overwatch" in source_key:
        return "Freshness: fast summary refresh cadence"
    return "Freshness: depends on source view availability"


def _metric_confidence_label(kind: str) -> str:
    labels = {
        "exact": "Measurement: Exact",
        "allocated": "Measurement: Allocated from warehouse metering",
        "estimated": "Measurement: Estimated",
        "forecast": "Measurement: Forecast from recent observed burn",
        "projection": "Measurement: Projection from recent observed burn",
    }
    return labels.get(str(kind or "").lower(), "Measurement depends on available account metadata")


def render_signal_confidence(*, source: str = "ACCOUNT_USAGE", confidence: str = "allocated", scope_note: str = "") -> None:
    parts = [_freshness_note(source), _metric_confidence_label(confidence)]
    if scope_note:
        parts.append(scope_note)
    defer_source_note(*parts)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


def render_workflow_module(workflow: str, workflow_modules: dict[str, str]) -> None:
    module_name = workflow_modules.get(str(workflow))
    if not module_name:
        st.warning(f"No module registered for workflow: {workflow}")
        return
    module = import_module(module_name)
    render = getattr(module, "render", None)
    if not callable(render):
        st.warning(f"Workflow module has no render() function: {module_name}")
        return
    render()


def _compact_time(value: object, default: str = "Not seen") -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"NAT", "NAN", "NONE", "NULL", "<NA>"}:
        return default
    return text[:19]
