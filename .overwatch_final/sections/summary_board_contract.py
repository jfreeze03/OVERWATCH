"""Summary board first-paint contract helpers.

The six primary Decision Workspace sections must render their summary board
from the current packet only. Evidence, Account Usage, session opens, direct
SQL, and optional drilldown datasets belong behind explicit user actions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence


PRIMARY_SUMMARY_SECTIONS = (
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
)

PRIMARY_SUMMARY_WORKFLOWS = {
    "Executive Landing": "Executive Overview",
    "DBA Control Room": "Morning Cockpit",
    "Alert Center": "Active Alerts",
    "Cost & Contract": "Cost Overview",
    "Workload Operations": "Workload Overview",
    "Security Monitoring": "Security Overview",
}

SUMMARY_BOARD_REGIONS = (
    "section_title_status",
    "data_trust",
    "packet_metrics",
    "what_changed",
    "what_matters",
    "what_next",
    "evidence_cta",
)

COST_PACKET_FIELDS = (
    "ACCOUNT_BILLED_CREDITS",
    "ACCOUNT_BILLED_COST_USD",
    "ACCOUNT_USED_CREDITS",
    "COMPUTE_CREDITS",
    "CLOUD_SERVICES_CREDITS",
    "CLOUD_SERVICES_ADJUSTMENT",
    "ACCOUNT_CLOUD_SERVICES_ADJUSTMENT",
    "WAREHOUSE_CREDITS",
    "WAREHOUSE_COST_ESTIMATE_USD",
    "WAREHOUSE_COST_USD",
    "SERVICE_OTHER_CREDITS",
    "SERVICE_OTHER_COST_USD",
    "BILLING_BRIDGE_DELTA_CREDITS",
    "BILLING_BRIDGE_DELTA_USD",
    "BILLING_BRIDGE_STATUS",
    "CORTEX_AI_CREDITS",
    "CORTEX_AI_COST_USD",
    "BILLING_RECONCILIATION_STATUS",
    "BILLING_WINDOW_START",
    "BILLING_WINDOW_END",
    "BILLING_WINDOW_COMPLETE",
    "BILLING_SOURCE_FRESHNESS_TS",
    "BILLING_LATENCY_NOTE",
    "BILLING_RECONCILIATION_WINDOW_START",
    "BILLING_RECONCILIATION_WINDOW_END",
    "BILLING_RECONCILIATION_FRESHNESS",
)

OPTIONAL_DETAIL_STATE_KEYS = (
    "df_br",
    "df_br_account_billing",
    "df_cortex_costs",
    "df_warehouse_recommendations",
    "query_history_detail",
)

OLD_SURFACE_MARKERS = (
    "card wall",
    "splash path",
    "launchpad",
    "watch floor",
    "command deck",
    "lane board",
    "duplicate overview stack",
)

RAW_DAILY_MARKERS = (
    "ACCOUNT_USAGE",
    "METERING_HISTORY",
    "WAREHOUSE_METERING_HISTORY",
    "QUERY_HISTORY",
    "SELECT ",
    " WITH ",
    " JOIN ",
    " CALL ",
    "SP_",
    "MART_",
    "FACT_",
)


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_int(value: object) -> int:
    try:
        if value is None:
            return 0
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _row_key(row: Mapping[str, Any]) -> tuple[int, str]:
    section = str(row.get("section") or "")
    workflow = str(row.get("workflow") or "")
    expected = PRIMARY_SUMMARY_WORKFLOWS.get(section, "")
    return (0 if workflow == expected else 1, workflow)


def _primary_view_rows(view_results: list[Any]) -> dict[str, Mapping[str, Any]]:
    rows_by_section: dict[str, list[Mapping[str, Any]]] = {section: [] for section in PRIMARY_SUMMARY_SECTIONS}
    for raw in view_results:
        row = _as_mapping(raw)
        section = str(row.get("section") or "")
        if section in rows_by_section:
            rows_by_section[section].append(row)
    return {
        section: sorted(rows, key=_row_key)[0] if rows else {}
        for section, rows in rows_by_section.items()
    }


def _count_rendered_markers(row: Mapping[str, Any], rendered_fragments: list[Any]) -> int:
    view_id = str(row.get("id") or "")
    texts = [
        str(_as_mapping(fragment).get("text") or "")
        for fragment in rendered_fragments
        if str(_as_mapping(fragment).get("id") or "") == view_id
    ]
    text = "\n".join(texts).lower()
    return sum(text.count(marker) for marker in OLD_SURFACE_MARKERS)


def _raw_daily_marker_count(row: Mapping[str, Any], rendered_fragments: list[Any]) -> int:
    view_id = str(row.get("id") or "")
    texts = [
        str(_as_mapping(fragment).get("text") or "")
        for fragment in rendered_fragments
        if str(_as_mapping(fragment).get("id") or "") == view_id
    ]
    text = "\n".join(texts).upper()
    return sum(text.count(marker) for marker in RAW_DAILY_MARKERS)


def build_summary_board_rows(payloads: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Recompute summary board first-paint rows from raw runtime artifacts."""

    views = _as_list(payloads.get("artifacts/full_app_validation/view_results.json"))
    rendered = _as_list(payloads.get("artifacts/full_app_validation/rendered_fragments.json"))
    section_rows = _primary_view_rows(views)
    rows: list[dict[str, Any]] = []

    for section in PRIMARY_SUMMARY_SECTIONS:
        view = section_rows.get(section, {})
        first_paint = _as_mapping(view.get("first_paint"))
        semantic_missing = [
            str(item)
            for item in _as_list(view.get("summary_board_missing_regions"))
            if str(item)
        ]
        if not semantic_missing and view.get("summary_board_regions_present") is False:
            semantic_missing = list(SUMMARY_BOARD_REGIONS)
        packet_fields_missing = [
            str(item)
            for item in _as_list(view.get("packet_fields_missing"))
            if str(item)
        ]
        if section == "Cost & Contract":
            packet_fields_missing.extend(
                str(field)
                for field in _as_list(view.get("cost_packet_fields_missing"))
                if str(field)
            )
        old_marker_count = _as_int(view.get("old_surface_marker_count")) + _count_rendered_markers(view, rendered)
        raw_marker_count = _as_int(view.get("raw_internal_token_count")) + _raw_daily_marker_count(view, rendered)
        packet_queries = _as_int(first_paint.get("observed_packet_queries"))
        non_packet_events = _as_int(first_paint.get("observed_non_packet_first_paint_events"))
        session_opens = _as_int(first_paint.get("observed_session_opens"))
        direct_sql_events = _as_int(first_paint.get("observed_direct_sql_events"))
        warm_packet_queries = _as_int(first_paint.get("observed_warm_packet_queries") or first_paint.get("warm_packet_queries"))
        account_usage_events = _as_int(first_paint.get("first_paint_account_usage") or view.get("account_usage_query_count"))
        evidence_events = _as_int(view.get("first_paint_evidence_query_count") or view.get("evidence_query_count"))
        optional_state_reads = [
            str(item)
            for item in _as_list(view.get("summary_board_optional_state_reads"))
            if str(item)
        ]
        failed_checks: list[str] = []
        if not view:
            failed_checks.append("missing_primary_view_row")
        if view and view.get("raised") not in ("", None, "rerun"):
            failed_checks.append("render_raised")
        if packet_queries != 1:
            failed_checks.append("cold_first_paint_packet_query_count")
        if non_packet_events:
            failed_checks.append("non_packet_first_paint_events")
        if warm_packet_queries:
            failed_checks.append("warm_first_paint_packet_queries")
        if session_opens:
            failed_checks.append("session_open_on_first_paint")
        if direct_sql_events:
            failed_checks.append("direct_sql_on_first_paint")
        if account_usage_events:
            failed_checks.append("account_usage_on_first_paint")
        if evidence_events:
            failed_checks.append("evidence_loader_on_first_paint")
        if semantic_missing:
            failed_checks.append("summary_board_regions_missing")
        if packet_fields_missing:
            failed_checks.append("packet_fields_missing")
        if old_marker_count:
            failed_checks.append("old_surface_marker_visible")
        if raw_marker_count:
            failed_checks.append("raw_internal_token_visible")
        if optional_state_reads:
            failed_checks.append("optional_detail_state_read_on_first_paint")

        rows.append(
            {
                "source": "summary_board_first_paint_contract",
                "proof_source": "runtime_render",
                "section": section,
                "workflow": str(view.get("workflow") or PRIMARY_SUMMARY_WORKFLOWS[section]),
                "view_id": str(view.get("id") or ""),
                "rendered": bool(view) and view.get("raised") in ("", None, "rerun"),
                "packet_only": not non_packet_events and not account_usage_events and not evidence_events,
                "packet_query_count": packet_queries,
                "warm_packet_query_count": warm_packet_queries,
                "non_packet_first_paint_event_count": non_packet_events,
                "session_open_count": session_opens,
                "direct_sql_event_count": direct_sql_events,
                "account_usage_query_count": account_usage_events,
                "evidence_query_count": evidence_events,
                "semantic_regions_required": list(SUMMARY_BOARD_REGIONS),
                "semantic_regions_missing": sorted(set(semantic_missing)),
                "cost_packet_fields_required": list(COST_PACKET_FIELDS) if section == "Cost & Contract" else [],
                "packet_fields_missing": sorted(set(packet_fields_missing)),
                "optional_detail_state_reads": sorted(set(optional_state_reads)),
                "old_surface_marker_count": old_marker_count,
                "raw_internal_token_count": raw_marker_count,
                "elapsed_ms": _as_int(view.get("elapsed_ms")),
                "passed": not failed_checks,
                "failed_checks": failed_checks,
                "recommendation": ""
                if not failed_checks
                else "Keep summary-board first paint on the current packet; move evidence/live/cost detail work behind explicit controls.",
                "raw_sql_included": False,
            }
        )
    return rows


def build_summary_board_query_budget_results(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures = [
        dict(row)
        for row in rows
        if _as_int(row.get("packet_query_count")) != 1
        or _as_int(row.get("warm_packet_query_count"))
        or _as_int(row.get("non_packet_first_paint_event_count"))
        or _as_int(row.get("session_open_count"))
        or _as_int(row.get("direct_sql_event_count"))
        or _as_int(row.get("account_usage_query_count"))
        or _as_int(row.get("evidence_query_count"))
    ]
    return {
        "source": "summary_board_query_budget",
        "proof_source": "runtime_render",
        "passed": not failures,
        "section_count": len(rows),
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }


def build_summary_board_error_inventory(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures = [dict(row) for row in rows if not bool(row.get("passed"))]
    by_section = {
        str(row.get("section") or ""): list(row.get("failed_checks") or [])
        for row in failures
    }
    return {
        "source": "summary_board_error_inventory",
        "proof_source": "runtime_render",
        "passed": not failures,
        "failure_count": len(failures),
        "failures_by_section": by_section,
        "raw_sql_included": False,
    }


def build_summary_board_failure_diagnostics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures = [dict(row) for row in rows if not bool(row.get("passed"))]
    return {
        "source": "summary_board_failure_diagnostics",
        "proof_source": "runtime_render",
        "passed": not failures,
        "failure_count": len(failures),
        "diagnostics": [
            {
                "section": row.get("section"),
                "failed_checks": row.get("failed_checks"),
                "recommendation": row.get("recommendation"),
                "first_paint_counts": {
                    "packet": row.get("packet_query_count"),
                    "warm_packet": row.get("warm_packet_query_count"),
                    "non_packet": row.get("non_packet_first_paint_event_count"),
                    "account_usage": row.get("account_usage_query_count"),
                    "evidence": row.get("evidence_query_count"),
                },
            }
            for row in failures
        ],
        "raw_sql_included": False,
    }


def write_summary_board_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    output_dir = root_path / "artifacts" / "full_app_validation"
    payloads = {
        "artifacts/full_app_validation/view_results.json": _read_json(output_dir / "view_results.json", []),
        "artifacts/full_app_validation/rendered_fragments.json": _read_json(output_dir / "rendered_fragments.json", []),
    }
    rows = build_summary_board_rows(payloads)
    query_budget = build_summary_board_query_budget_results(rows)
    error_inventory = build_summary_board_error_inventory(rows)
    diagnostics = build_summary_board_failure_diagnostics(rows)
    outputs = {
        "summary_board_results.json": rows,
        "summary_board_query_budget_results.json": query_budget,
        "summary_board_error_inventory.json": error_inventory,
        "summary_board_failure_diagnostics.json": diagnostics,
    }
    for filename, payload in outputs.items():
        (output_dir / filename).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return {f"artifacts/full_app_validation/{filename}": payload for filename, payload in outputs.items()}


__all__ = [
    "COST_PACKET_FIELDS",
    "OLD_SURFACE_MARKERS",
    "OPTIONAL_DETAIL_STATE_KEYS",
    "PRIMARY_SUMMARY_SECTIONS",
    "PRIMARY_SUMMARY_WORKFLOWS",
    "SUMMARY_BOARD_REGIONS",
    "build_summary_board_error_inventory",
    "build_summary_board_failure_diagnostics",
    "build_summary_board_query_budget_results",
    "build_summary_board_rows",
    "write_summary_board_artifacts",
]
