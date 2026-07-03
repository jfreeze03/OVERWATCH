"""First-paint SLO gate for packet-backed Decision Workspace surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

FIRST_PAINT_SLO_RESULTS_REL = f"{FULL_APP_DIR}/first_paint_slo_results.json"
FIRST_PAINT_SLO_GATE_REL = f"{LAUNCH_READINESS_DIR}/first_paint_slo_gate_results.json"

COLD_FIRST_PAINT_SLO_MS = 1_500
WARM_SECTION_SWITCH_SLO_MS = 300
PACKET_SIZE_SLO_BYTES = 100_000

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


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("rows", "checks", "results", "sections"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value)))
    except Exception:
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _row_count(row: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        if key in row:
            return _as_int(row.get(key))
    return 0


def _section(row: Mapping[str, Any]) -> str:
    return str(row.get("section") or row.get("area") or "").strip()


def _packet_size_bytes(packet_payload: Any, rows: Iterable[Mapping[str, Any]]) -> int:
    if isinstance(packet_payload, Mapping):
        for key in ("max_packet_bytes", "packet_size_bytes", "packet_bytes"):
            if key in packet_payload:
                return _as_int(packet_payload.get(key))
    sizes: list[int] = []
    for row in rows:
        for key in ("packet_size_bytes", "packet_bytes", "max_packet_bytes"):
            if key in row:
                sizes.append(_as_int(row.get(key)))
                break
    return max(sizes or [0])


def evaluate_first_paint_slo(
    first_paint_payload: Any,
    *,
    packet_size_payload: Any | None = None,
) -> dict[str, Any]:
    """Evaluate SLO rows without treating missing telemetry as success."""

    source_rows = _rows(first_paint_payload)
    packet_size = _packet_size_bytes(packet_size_payload, source_rows)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_sections: set[str] = set()

    if not source_rows:
        for section in PRIMARY_SECTIONS:
            failures.append({"section": section, "workflow": "Overview", "failure_reason": "missing first-paint SLO telemetry"})
        return {
            "source": "first_paint_slo_gate",
            "generated_at": _now(),
            "passed": False,
            "failure_count": len(failures),
            "first_paint_slo_passed": False,
            "packet_size_bytes": packet_size,
            "packet_size_slo_bytes": PACKET_SIZE_SLO_BYTES,
            "rows": rows,
            "failures": failures,
            "raw_sql_included": False,
        }

    for source_row in source_rows:
        row = dict(source_row)
        section = _section(row)
        workflow = str(row.get("workflow") or "Overview")
        if section in PRIMARY_SECTIONS:
            seen_sections.add(section)
        cold_ms = _as_float(row.get("elapsed_ms"))
        warm_ms = _as_float(row.get("warm_elapsed_ms") or row.get("warm_section_switch_elapsed_ms") or 0)
        cold_packet = _row_count(row, "cold_first_paint_packet_query_count", "packet_query_count")
        warm_queries = _row_count(row, "warm_first_paint_query_count", "warm_query_count")
        evidence = _row_count(row, "evidence_query_count")
        account_usage = _row_count(row, "account_usage_count")
        detail = _row_count(row, "detail_query_count")
        workbench = _row_count(row, "cost_workbench_query_count", "chart_query_count")
        query_search = _row_count(row, "query_search_query_count")
        direct_sql = _row_count(row, "direct_sql_count", "direct_sql_event_count")
        reasons: list[str] = []
        if section in PRIMARY_SECTIONS and "elapsed_ms" not in row:
            reasons.append("missing cold first-paint elapsed_ms")
        if section in PRIMARY_SECTIONS and cold_ms > COLD_FIRST_PAINT_SLO_MS:
            reasons.append("cold first paint exceeded 1.5s SLO")
        if warm_ms and warm_ms > WARM_SECTION_SWITCH_SLO_MS:
            reasons.append("warm section switch exceeded 300ms SLO")
        if section in PRIMARY_SECTIONS and cold_packet > 1:
            reasons.append("cold first paint used more than one packet query")
        if warm_queries:
            reasons.append("warm first paint executed a query")
        if evidence:
            reasons.append("first paint loaded evidence")
        if account_usage:
            reasons.append("first paint crossed Account Usage/deep-history boundary")
        if detail:
            reasons.append("first paint loaded detail data")
        if workbench:
            reasons.append("Cost Workbench/chart loaded on first paint")
        if query_search:
            reasons.append("Query Search ran during first paint")
        if direct_sql:
            reasons.append("first paint emitted direct SQL")
        checked = {
            "section": section,
            "workflow": workflow,
            "cold_elapsed_ms": cold_ms,
            "warm_elapsed_ms": warm_ms,
            "cold_first_paint_packet_query_count": cold_packet,
            "warm_first_paint_query_count": warm_queries,
            "evidence_query_count": evidence,
            "account_usage_count": account_usage,
            "detail_query_count": detail,
            "cost_workbench_query_count": workbench,
            "query_search_query_count": query_search,
            "direct_sql_count": direct_sql,
            "passed": not reasons,
            "failure_reason": "; ".join(reasons),
            "raw_sql_included": False,
        }
        rows.append(checked)
        if reasons:
            failures.append({"section": section, "workflow": workflow, "failure_reason": checked["failure_reason"]})

    for section in PRIMARY_SECTIONS:
        if section not in seen_sections:
            failures.append({"section": section, "workflow": "Overview", "failure_reason": "missing primary first-paint SLO row"})

    if packet_size <= 0:
        failures.append({"section": "Decision packet", "workflow": "Packet budget", "failure_reason": "missing packet size proof"})
    elif packet_size > PACKET_SIZE_SLO_BYTES:
        failures.append({"section": "Decision packet", "workflow": "Packet budget", "failure_reason": "packet size exceeds 100 KB"})

    return {
        "source": "first_paint_slo_gate",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "first_paint_slo_passed": not failures,
        "cold_slo_ms": COLD_FIRST_PAINT_SLO_MS,
        "warm_slo_ms": WARM_SECTION_SWITCH_SLO_MS,
        "packet_size_bytes": packet_size,
        "packet_size_slo_bytes": PACKET_SIZE_SLO_BYTES,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_first_paint_slo_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    first_paint = _load_json(root_path / f"{FULL_APP_DIR}/first_paint_performance_results.json")
    packet_size = _load_json(root_path / "artifacts/snowflake_validation/packet_size_results.json")
    gate = evaluate_first_paint_slo(first_paint, packet_size_payload=packet_size)
    results = {
        "source": "first_paint_slo_results",
        "generated_at": _now(),
        "passed": bool(gate.get("passed")),
        "failure_count": int(gate.get("failure_count") or 0),
        "first_paint_slo_passed": bool(gate.get("first_paint_slo_passed")),
        "packet_size_bytes": int(gate.get("packet_size_bytes") or 0),
        "packet_size_slo_bytes": PACKET_SIZE_SLO_BYTES,
        "rows": gate.get("rows", []),
        "failures": gate.get("failures", []),
        "raw_sql_included": False,
    }
    _write_json(root_path / FIRST_PAINT_SLO_RESULTS_REL, results)
    _write_json(root_path / FIRST_PAINT_SLO_GATE_REL, gate)
    return {
        FIRST_PAINT_SLO_RESULTS_REL: results,
        FIRST_PAINT_SLO_GATE_REL: gate,
    }


if __name__ == "__main__":
    artifacts = write_first_paint_slo_artifacts(Path("."))
    if not bool(artifacts[FIRST_PAINT_SLO_GATE_REL].get("passed")):
        raise SystemExit(1)


__all__ = [
    "FIRST_PAINT_SLO_GATE_REL",
    "FIRST_PAINT_SLO_RESULTS_REL",
    "evaluate_first_paint_slo",
    "write_first_paint_slo_artifacts",
]
