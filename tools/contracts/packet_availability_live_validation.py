"""Packet availability diagnostics for live Decision Workspace validation.

The contract explains why a selected Decision packet is missing without storing
SQL text or Snowflake internals in daily-facing artifacts.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SNOWFLAKE_VALIDATION_DIR = "artifacts/snowflake_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

PACKET_AVAILABILITY_MATRIX_REL = f"{SNOWFLAKE_VALIDATION_DIR}/packet_availability_matrix_results.json"
SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL = f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_cli_packet_availability_results.json"
PACKET_AVAILABILITY_GATE_REL = f"{LAUNCH_READINESS_DIR}/packet_availability_gate_results.json"

PRIMARY_SECTIONS = (
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_int(value: object) -> int:
    try:
        return int(float(str(value or "0").strip() or "0"))
    except Exception:
        return 0


def _norm(value: object) -> str:
    return str(value or "").strip().upper()


def _safe_list(values: Iterable[object]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value or "").strip()})


def completed_window_days_from_range(start: object, end: object, *, default: int = 7) -> int:
    """Map a selected date range to completed packet days."""
    from datetime import date, datetime

    def coerce(value: object) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if not text:
            return None
        for parser in (date.fromisoformat, datetime.fromisoformat):
            try:
                parsed = parser(text)
                return parsed.date() if isinstance(parsed, datetime) else parsed
            except Exception:
                continue
        return None

    start_date = coerce(start)
    end_date = coerce(end)
    if start_date is None or end_date is None:
        return max(1, int(default or 7))
    return max(1, int((end_date - start_date).days))


def normalize_packet_window_days(window_days: object) -> int:
    """Normalize old inclusive 8-day UI input to the 7 completed-day packet."""
    days = _as_int(window_days)
    if days == 8:
        return 7
    return max(1, days or 7)


def evaluate_packet_availability(
    rows: Sequence[Mapping[str, Any]],
    *,
    selected_company: str,
    selected_environment: str,
    selected_window_days: int,
    sections: Sequence[str] = PRIMARY_SECTIONS,
) -> dict[str, Any]:
    selected_company_norm = _norm(selected_company)
    selected_environment_norm = _norm(selected_environment)
    selected_window = int(selected_window_days)
    normalized_window = normalize_packet_window_days(selected_window)
    result_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for index, section in enumerate(sections):
        section_rows = [row for row in rows if _norm(row.get("section_name") or row.get("SECTION_NAME")) == _norm(section)]
        active_count = sum(_as_int(row.get("active_current_count", row.get("current_count", row.get("active_count", 0)))) for row in section_rows)
        flat_count = sum(_as_int(row.get("flat_current_count", row.get("flat_count", 0))) for row in section_rows)
        last_good_count = sum(_as_int(row.get("last_good_count", row.get("last_good", 0))) for row in section_rows)
        windows = sorted({_as_int(row.get("window_days", row.get("WINDOW_DAYS", 0))) for row in section_rows if _as_int(row.get("window_days", row.get("WINDOW_DAYS", 0)))})
        companies = _safe_list(row.get("company", row.get("COMPANY", "")) for row in section_rows)
        environments = _safe_list(row.get("environment", row.get("ENVIRONMENT", "")) for row in section_rows)

        def row_matches(row: Mapping[str, Any], *, relaxed_company: bool = False, relaxed_environment: bool = False, relaxed_window: bool = False) -> bool:
            company = _norm(row.get("company", row.get("COMPANY", "")))
            environment = _norm(row.get("environment", row.get("ENVIRONMENT", "")))
            window = _as_int(row.get("window_days", row.get("WINDOW_DAYS", 0)))
            company_ok = relaxed_company or company in {selected_company_norm, "ALL", "GLOBAL"}
            environment_ok = relaxed_environment or environment in {selected_environment_norm, "ALL", "ALL ENVIRONMENTS", "GLOBAL"}
            window_ok = relaxed_window or window == normalized_window
            return company_ok and environment_ok and window_ok

        exact_rows = [
            row
            for row in section_rows
            if _norm(row.get("company", row.get("COMPANY", ""))) == selected_company_norm
            and _norm(row.get("environment", row.get("ENVIRONMENT", ""))) == selected_environment_norm
            and _as_int(row.get("window_days", row.get("WINDOW_DAYS", 0))) == normalized_window
        ]
        all_company_rows = [row for row in section_rows if row_matches(row, relaxed_company=True)]
        all_environment_rows = [row for row in section_rows if row_matches(row, relaxed_environment=True)]
        alternate_window_rows = [row for row in section_rows if row_matches(row, relaxed_window=True)]

        exact_packet_exists = any(_as_int(row.get("active_current_count", row.get("current_count", 1))) > 0 for row in exact_rows)
        flat_current_count = sum(_as_int(row.get("flat_current_count", row.get("flat_count", 0))) for row in exact_rows) or flat_count
        latest_snapshot = max((str(row.get("latest_snapshot_ts", row.get("snapshot_ts", row.get("SNAPSHOT_TS", ""))) or "") for row in section_rows), default="")
        latest_load = max((str(row.get("latest_load_ts", row.get("load_ts", row.get("LOAD_TS", ""))) or "") for row in section_rows), default="")
        closest = exact_rows or alternate_window_rows or all_company_rows or all_environment_rows or section_rows
        closest_row = closest[0] if closest else {}
        closest_scope = " / ".join(
            part
            for part in (
                str(closest_row.get("company", closest_row.get("COMPANY", "")) or "").strip(),
                str(closest_row.get("environment", closest_row.get("ENVIRONMENT", "")) or "").strip(),
            )
            if part
        )
        closest_window = _as_int(closest_row.get("window_days", closest_row.get("WINDOW_DAYS", 0))) if closest_row else 0

        missing_reason = ""
        recommended_fix = ""
        passed = True
        if not section_rows:
            passed = False
            missing_reason = "no packet row found for section"
            recommended_fix = "Run Initialize summaries or FAST refresh validation."
        elif not exact_packet_exists and last_good_count <= 0:
            passed = False
            if selected_window != normalized_window and normalized_window in windows:
                missing_reason = f"selected {selected_window}-day range maps to {normalized_window}-day packets"
                recommended_fix = "Use completed-day packet lookup or refresh the matching packet window."
            elif selected_company_norm != "ALL" and "ALL" in {_norm(value) for value in companies}:
                missing_reason = "selected company packet missing but ALL-company packet exists"
                recommended_fix = "Use closest packet fallback or refresh the selected company scope."
            elif selected_environment_norm != "ALL" and "ALL" in {_norm(value) for value in environments}:
                missing_reason = "selected environment packet missing but ALL-environment packet exists"
                recommended_fix = "Use closest packet fallback or refresh the selected environment scope."
            else:
                missing_reason = "selected scope has no current packet"
                recommended_fix = "Open Setup Health and initialize summaries."
        elif exact_packet_exists and flat_current_count <= 0:
            passed = False
            missing_reason = "current packet exists but flat packet is missing"
            recommended_fix = "Refresh flat packet publication."
        elif selected_window != normalized_window and normalized_window in windows:
            missing_reason = f"selected {selected_window}-day range normalized to {normalized_window}-day packet"
            recommended_fix = "No action needed; loader uses completed-day packet convention."

        row = {
            "source": "packet_availability_matrix",
            "row_index": index,
            "section_name": section,
            "selected_company": selected_company,
            "selected_environment": selected_environment,
            "selected_window_days": selected_window,
            "normalized_window_days": normalized_window,
            "exact_packet_exists": exact_packet_exists,
            "all_company_packet_exists": bool(all_company_rows),
            "all_environment_packet_exists": bool(all_environment_rows),
            "alternate_window_packets": len(alternate_window_rows),
            "available_windows": windows,
            "available_companies": companies,
            "available_environments": environments,
            "active_current_count": active_count,
            "flat_current_count": flat_current_count,
            "last_good_count": last_good_count,
            "latest_snapshot_ts": latest_snapshot,
            "latest_load_ts": latest_load,
            "is_active_count": active_count,
            "is_exact_scope_count": len(exact_rows),
            "closest_scope": closest_scope,
            "closest_window_days": closest_window,
            "closest_snapshot_ts": str(closest_row.get("latest_snapshot_ts", closest_row.get("snapshot_ts", "")) or ""),
            "missing_reason": missing_reason,
            "recommended_fix": recommended_fix,
            "passed": passed,
            "raw_sql_included": False,
        }
        result_rows.append(row)
        if not passed:
            failures.append(
                {
                    "section_name": section,
                    "missing_reason": missing_reason,
                    "recommended_fix": recommended_fix,
                }
            )

    return {
        "source": "packet_availability_matrix_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "rows": result_rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_packet_availability_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_rows = payload.get("rows")
    rows: list[Any] = raw_rows if isinstance(raw_rows, list) else []
    raw_failures = payload.get("failures")
    failures: list[Any] = raw_failures if isinstance(raw_failures, list) else []
    return {
        "source": "packet_availability_gate_results",
        "generated_at": _now(),
        "passed": bool(payload.get("passed")),
        "failure_count": int(payload.get("failure_count") or len(failures)),
        "row_count": len(rows),
        "failures": failures,
        "window_mismatch_count": sum(1 for row in rows if isinstance(row, Mapping) and "normalized" in str(row.get("missing_reason") or "")),
        "missing_packet_count": sum(1 for row in rows if isinstance(row, Mapping) and not bool(row.get("exact_packet_exists"))),
        "raw_sql_included": False,
    }


def write_packet_availability_artifacts(
    root: Path | str,
    rows: Sequence[Mapping[str, Any]],
    *,
    selected_company: str,
    selected_environment: str,
    selected_window_days: int,
) -> dict[str, Any]:
    root_path = Path(root)
    matrix = evaluate_packet_availability(
        rows,
        selected_company=selected_company,
        selected_environment=selected_environment,
        selected_window_days=selected_window_days,
    )
    cli_payload = dict(matrix)
    cli_payload["source"] = "snowflake_cli_packet_availability_results"
    gate = evaluate_packet_availability_gate(matrix)
    artifacts = {
        PACKET_AVAILABILITY_MATRIX_REL: matrix,
        SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL: cli_payload,
        PACKET_AVAILABILITY_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        path = root_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return artifacts


__all__ = [
    "PACKET_AVAILABILITY_GATE_REL",
    "PACKET_AVAILABILITY_MATRIX_REL",
    "PRIMARY_SECTIONS",
    "SNOWFLAKE_CLI_PACKET_AVAILABILITY_REL",
    "completed_window_days_from_range",
    "evaluate_packet_availability",
    "evaluate_packet_availability_gate",
    "normalize_packet_window_days",
    "write_packet_availability_artifacts",
]
