"""Shared evidence-mode semantics for the Streamlit shell and sections."""

from __future__ import annotations

TRIAGE_MODE_TRIAGE = "Triage"
TRIAGE_MODE_INVESTIGATE = "Investigate"
TRIAGE_MODE_ALL_EVIDENCE = "All Evidence"
TRIAGE_MODE_OPTIONS = (TRIAGE_MODE_TRIAGE, TRIAGE_MODE_INVESTIGATE, TRIAGE_MODE_ALL_EVIDENCE)
TRIAGE_MODE_LEGACY_ALIASES = {
    "Exceptions only": TRIAGE_MODE_TRIAGE,
    "All evidence": TRIAGE_MODE_ALL_EVIDENCE,
}


def normalize_evidence_mode(mode: object) -> str:
    value = str(mode or TRIAGE_MODE_TRIAGE)
    value = TRIAGE_MODE_LEGACY_ALIASES.get(value, value)
    if value not in TRIAGE_MODE_OPTIONS:
        return TRIAGE_MODE_TRIAGE
    return value


def evidence_mode_from_exceptions(enabled: bool) -> str:
    return TRIAGE_MODE_TRIAGE if enabled else TRIAGE_MODE_INVESTIGATE


def exceptions_enabled_from_evidence_mode(mode: object) -> bool:
    return normalize_evidence_mode(mode) == TRIAGE_MODE_TRIAGE


def current_evidence_mode(state: object) -> str:
    getter = getattr(state, "get", None)
    if not callable(getter):
        return TRIAGE_MODE_TRIAGE
    return normalize_evidence_mode(getter("triage_view_mode", TRIAGE_MODE_TRIAGE))


def evidence_mode_is_investigation(state: object) -> bool:
    return current_evidence_mode(state) in {TRIAGE_MODE_INVESTIGATE, TRIAGE_MODE_ALL_EVIDENCE}


def evidence_mode_is_all_evidence(state: object) -> bool:
    return current_evidence_mode(state) == TRIAGE_MODE_ALL_EVIDENCE
