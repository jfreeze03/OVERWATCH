"""Launch-blocking performance budget gate for Decision Workspace surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

PERFORMANCE_BUDGET_RESULTS_REL = f"{FULL_APP_DIR}/performance_budget_results.json"
PERFORMANCE_BUDGET_GATE_REL = f"{LAUNCH_READINESS_DIR}/performance_budget_gate_results.json"

PRIMARY_SECTIONS = (
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
)

REQUIRED_FIRST_PAINT_FIELDS = (
    "section",
    "workflow",
    "cold_first_paint_packet_query_count",
    "warm_first_paint_query_count",
    "evidence_query_count",
    "account_usage_count",
    "detail_query_count",
    "cost_workbench_query_count",
    "query_search_query_count",
    "direct_sql_count",
    "session_open_count",
    "elapsed_ms",
    "product_boundary",
    "execution_boundary",
    "passed",
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
        return int(value or 0)
    except Exception:
        return 0


def _row_count(row: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        if key in row:
            return _as_int(row.get(key))
    return 0


def _boundary(row: Mapping[str, Any]) -> str:
    return str(row.get("boundary") or row.get("query_boundary") or row.get("workflow") or "").strip()


def _section(row: Mapping[str, Any]) -> str:
    return str(row.get("section") or row.get("area") or "").strip()


def _evaluate_first_paint_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checked: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    source_rows = [dict(row) for row in rows]
    if not source_rows:
        for section in PRIMARY_SECTIONS:
            failures.append({"section": section, "workflow": "Overview", "failure_reason": "missing primary first-paint row"})
        return checked, failures
    for source_row in source_rows:
        row = dict(source_row)
        section = _section(row)
        workflow = str(row.get("workflow") or "Overview")
        if section in PRIMARY_SECTIONS:
            seen_sections.add(section)
        missing_fields = [field for field in REQUIRED_FIRST_PAINT_FIELDS if field not in row]
        product_boundary = str(row.get("product_boundary") or "").strip()
        execution_boundary = str(row.get("execution_boundary") or "").strip()
        cold_packet = _row_count(row, "cold_first_paint_packet_query_count", "cold_packet_query_count", "packet_query_count")
        warm_queries = _row_count(row, "warm_first_paint_query_count", "warm_query_count")
        non_packet = _row_count(row, "non_packet_first_paint_event_count", "non_packet_query_count")
        evidence = _row_count(row, "evidence_query_count", "evidence_queries_first_paint")
        account_usage = _row_count(row, "account_usage_count", "account_usage_queries_first_paint")
        detail = _row_count(row, "detail_query_count", "detail_queries_first_paint")
        workbench = _row_count(row, "cost_workbench_query_count", "chart_query_count")
        query_search = _row_count(row, "query_search_query_count")
        direct_sql = _row_count(row, "direct_sql_count", "direct_sql_event_count")
        session_open = _row_count(row, "session_open_count")
        reasons: list[str] = []
        if missing_fields:
            reasons.append(f"first-paint telemetry missing required fields: {', '.join(missing_fields)}")
        if section in PRIMARY_SECTIONS and not product_boundary:
            reasons.append("first-paint telemetry missing product boundary")
        if section in PRIMARY_SECTIONS and not execution_boundary:
            reasons.append("first-paint telemetry missing execution boundary")
        if bool(row.get("raw_sql_included")):
            reasons.append("first-paint telemetry included raw SQL")
        if str(row.get("source") or "").lower() in {"synthetic_safe_fallback", "manual_safe_text", "static_contract_only", "test_constructed_payload"}:
            reasons.append("first-paint telemetry is synthetic/static-only")
        if section in PRIMARY_SECTIONS and cold_packet > 1:
            reasons.append("cold first paint used more than one packet query")
        if warm_queries:
            reasons.append("warm first paint executed a query")
        if non_packet:
            reasons.append("first paint emitted non-packet work")
        if evidence:
            reasons.append("first paint loaded evidence")
        if account_usage:
            reasons.append("first paint crossed Account Usage/deep-history boundary")
        if detail:
            reasons.append("first paint loaded detail data")
        if workbench:
            reasons.append("Cost Workbench/chart work appeared on first paint")
        if query_search:
            reasons.append("Query Search ran during first paint")
        if direct_sql:
            reasons.append("first paint emitted direct SQL")
        if session_open and section in PRIMARY_SECTIONS and cold_packet == 0:
            reasons.append("first paint opened a session outside the packet lookup")
        checked.append(
            {
                "section": section,
                "workflow": workflow,
                "boundary": "first_paint_packet",
                "product_boundary": product_boundary,
                "execution_boundary": execution_boundary,
                "cold_first_paint_packet_query_count": cold_packet,
                "warm_first_paint_query_count": warm_queries,
                "non_packet_first_paint_event_count": non_packet,
                "evidence_query_count": evidence,
                "account_usage_count": account_usage,
                "detail_query_count": detail,
                "cost_workbench_query_count": workbench,
                "query_search_query_count": query_search,
                "direct_sql_count": direct_sql,
                "session_open_count": session_open,
                "passed": not reasons,
                "failure_reason": "; ".join(reasons),
                "raw_sql_included": False,
            }
        )
        if reasons:
            failures.append({"section": section, "workflow": workflow, "failure_reason": "; ".join(reasons)})
    for section in PRIMARY_SECTIONS:
        if section not in seen_sections:
            failures.append({"section": section, "workflow": "Overview", "failure_reason": "missing primary first-paint row"})
    return checked, failures


def _evaluate_budget_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checked: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        section = _section(row)
        boundary = _boundary(row)
        query_count = _row_count(row, "query_count", "actual_snowflake_executions", "actual_query_count")
        session_open = _row_count(row, "session_open_count")
        direct_sql = _row_count(row, "direct_sql_count", "direct_sql_events")
        account_usage = _row_count(row, "account_usage_count", "account_usage_events")
        reasons: list[str] = []
        if not section:
            reasons.append("telemetry row missing section")
        if not boundary:
            reasons.append("telemetry row missing boundary")
        if boundary == "route_action" and (query_count or session_open or direct_sql):
            reasons.append("route action crossed query/session/direct-SQL boundary")
        if boundary == "query_search_no_click" and query_count:
            reasons.append("Query Search no-click executed a query")
        if boundary in {"first_paint_packet", "warm_first_paint"} and account_usage:
            reasons.append("first paint crossed Account Usage/deep-history boundary")
        if boundary == "warm_first_paint" and query_count:
            reasons.append("warm first paint executed a query")
        checked.append(
            {
                "section": section,
                "workflow": str(row.get("workflow") or ""),
                "boundary": boundary,
                "query_count": query_count,
                "session_open_count": session_open,
                "direct_sql_count": direct_sql,
                "account_usage_count": account_usage,
                "passed": not reasons,
                "failure_reason": "; ".join(reasons),
                "raw_sql_included": False,
            }
        )
        if reasons:
            failures.append({"section": section, "boundary": boundary, "failure_reason": "; ".join(reasons)})
    return checked, failures


def evaluate_performance_budget_gate(
    first_paint_payload: Any = None,
    query_budget_payload: Any = None,
    telemetry_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    first_paint_rows, first_paint_failures = _evaluate_first_paint_rows(_rows(first_paint_payload))
    budget_rows = _rows(query_budget_payload)
    if telemetry_rows is not None:
        budget_rows.extend(dict(row) for row in telemetry_rows if isinstance(row, Mapping))
    budget_checks, budget_failures = _evaluate_budget_rows(budget_rows)
    failures = first_paint_failures + budget_failures
    return {
        "source": "performance_budget_gate",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "first_paint_rows": first_paint_rows,
        "query_budget_rows": budget_checks,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_performance_budget_gate_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    first_paint = _load_json(root_path / f"{FULL_APP_DIR}/first_paint_performance_results.json")
    query_budget = _load_json(root_path / f"{FULL_APP_DIR}/query_budget_results.json")
    gate = evaluate_performance_budget_gate(first_paint, query_budget)
    results = {
        "source": "performance_budget_results",
        "generated_at": _now(),
        "passed": bool(gate.get("passed")),
        "failure_count": int(gate.get("failure_count") or 0),
        "first_paint_rows": gate.get("first_paint_rows", []),
        "query_budget_rows": gate.get("query_budget_rows", []),
        "raw_sql_included": False,
    }
    _write_json(root_path / PERFORMANCE_BUDGET_RESULTS_REL, results)
    _write_json(root_path / PERFORMANCE_BUDGET_GATE_REL, gate)
    return {
        PERFORMANCE_BUDGET_RESULTS_REL: results,
        PERFORMANCE_BUDGET_GATE_REL: gate,
    }


if __name__ == "__main__":
    artifacts = write_performance_budget_gate_artifacts(Path("."))
    gate = artifacts[PERFORMANCE_BUDGET_GATE_REL]
    if not bool(gate.get("passed")):
        raise SystemExit(1)


__all__ = [
    "PERFORMANCE_BUDGET_GATE_REL",
    "PERFORMANCE_BUDGET_RESULTS_REL",
    "PRIMARY_SECTIONS",
    "evaluate_performance_budget_gate",
    "write_performance_budget_gate_artifacts",
]
