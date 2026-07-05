"""Shared release-facing runtime boundary vocabulary."""

from __future__ import annotations


APPROVED_RELEASE_EXECUTION_BOUNDARIES: frozenset[str] = frozenset(
    {
        "decision_packet",
        "section_summary_autoload",
        "evidence_targeted",
        "query_search_exact",
        "query_search_broad_explicit",
        "setup_admin",
        "live_validation",
        "refresh_fast",
        "refresh_full",
        "export_case",
        "admin_setup_health",
        "explicit_connection_test",
        "metadata_bounded",
    }
)

_RELEASE_BOUNDARY_ALIASES: dict[str, str] = {
    "first_paint_packet": "decision_packet",
    "warm_first_paint": "decision_packet",
    "decision_packet": "decision_packet",
    "section_summary_autoload": "section_summary_autoload",
    "summary_autoload": "section_summary_autoload",
    "summary_mart": "section_summary_autoload",
    "evidence": "evidence_targeted",
    "evidence_action": "evidence_targeted",
    "compact_evidence": "evidence_targeted",
    "detail_mart": "evidence_targeted",
    "cost_evidence": "evidence_targeted",
    "cost_workbench": "evidence_targeted",
    "query_search": "query_search_exact",
    "query_search_no_click": "metadata_bounded",
    "query_search_explicit": "query_search_exact",
    "query_search_related": "query_search_exact",
    "query_preview": "metadata_bounded",
    "deep_history_fallback": "query_search_broad_explicit",
    "account_usage": "query_search_broad_explicit",
    "metadata": "metadata_bounded",
    "metadata_probe": "metadata_bounded",
    "setup_health": "admin_setup_health",
    "setup_admin": "setup_admin",
    "admin": "setup_admin",
    "live_validation": "live_validation",
    "explicit_connection_test": "explicit_connection_test",
    "refresh_packet": "refresh_fast",
    "route_action": "metadata_bounded",
    "other": "metadata_bounded",
}


def normalize_release_boundary(boundary: object) -> str:
    """Return the approved release-facing execution boundary."""
    raw = str(boundary or "").strip().lower()
    if not raw:
        return "metadata_bounded"
    normalized = _RELEASE_BOUNDARY_ALIASES.get(raw, raw)
    return normalized if normalized in APPROVED_RELEASE_EXECUTION_BOUNDARIES else "metadata_bounded"


def is_approved_release_boundary(boundary: object) -> bool:
    """Return whether boundary is already in the approved release vocabulary."""
    return str(boundary or "").strip().lower() in APPROVED_RELEASE_EXECUTION_BOUNDARIES


__all__ = [
    "APPROVED_RELEASE_EXECUTION_BOUNDARIES",
    "is_approved_release_boundary",
    "normalize_release_boundary",
]
