# sections/security_posture_common.py - Shared Security Monitoring helpers
from __future__ import annotations

from importlib import import_module

import streamlit as st

from config import DEFAULT_COMPANY, DEFAULT_ENVIRONMENT
from sections.base import lazy_util as _lazy_util
from utils.section_guidance import defer_section_note, defer_source_note


shared_mfa_count_expr = _lazy_util("shared_mfa_count_expr")
shared_mfa_gap_predicate = _lazy_util("shared_mfa_gap_predicate")
shared_mfa_proof_label = _lazy_util("shared_mfa_proof_label")


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def _mfa_count_expr(user_cols: set[str]) -> str:
    return shared_mfa_count_expr(user_cols)


def _mfa_gap_predicate(user_cols: set[str], alias: str = "u") -> str:
    return shared_mfa_gap_predicate(user_cols, alias)


def _mfa_proof_label(user_cols: set[str]) -> str:
    return shared_mfa_proof_label(user_cols)


def _freshness_note(source: str) -> str:
    source_key = str(source or "").lower()
    if "information_schema" in source_key or source_key in {"live", "is"}:
        return "Freshness: live INFORMATION_SCHEMA view"
    if "account_usage" in source_key:
        return "Freshness: ACCOUNT_USAGE can lag up to about 45-90 minutes"
    if "mart" in source_key or "overwatch" in source_key:
        return "Freshness: fast summary refresh cadence"
    return "Freshness: depends on source view availability"


def _metric_confidence_label(kind: str) -> str:
    labels = {
        "exact": "Measurement: Exact",
        "allocated": "Measurement: Allocated from source records",
        "estimated": "Measurement: Estimated",
    }
    return labels.get(str(kind or "").lower(), "Measurement depends on available account metadata")


def render_signal_confidence(*, source: str = "ACCOUNT_USAGE", confidence: str = "exact", scope_note: str = "") -> None:
    parts = [_freshness_note(source), _metric_confidence_label(confidence)]
    if scope_note:
        parts.append(scope_note)
    defer_source_note(*parts)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    _ = columns
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


def render_workflow_guide(summary: str, rows) -> None:
    defer_section_note(summary)
    for trigger, action in rows:
        defer_section_note(f"{trigger}: {action}")


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


__all__ = [
    "get_active_company",
    "get_active_environment",
    "_mfa_count_expr",
    "_mfa_gap_predicate",
    "_mfa_proof_label",
    "_freshness_note",
    "_metric_confidence_label",
    "render_signal_confidence",
    "render_operator_briefing",
    "render_workflow_guide",
    "render_workflow_module",
]
