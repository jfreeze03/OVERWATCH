"""Launch-blocking performance budget gate for Decision Workspace surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

PERFORMANCE_BUDGET_RESULTS_REL = f"{FULL_APP_DIR}/performance_budget_results.json"
PERFORMANCE_BUDGET_GATE_REL = f"{LAUNCH_READINESS_DIR}/performance_budget_gate_results.json"
COST_OVERVIEW_NO_AUTOLOAD_RESULTS_REL = f"{FULL_APP_DIR}/cost_overview_no_autoload_results.json"
COST_OVERVIEW_NO_AUTOLOAD_GATE_REL = f"{LAUNCH_READINESS_DIR}/cost_overview_no_autoload_gate_results.json"
TARGETED_EVIDENCE_SQL_PUSHDOWN_RESULTS_REL = f"{FULL_APP_DIR}/targeted_evidence_sql_pushdown_results.json"
QUERY_SEARCH_AUTORUN_RESULTS_REL = f"{FULL_APP_DIR}/query_search_autorun_results.json"

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
    "pre_first_paint_session_open_count",
    "shell_session_open_count",
    "active_session_probe_count",
    "admin_connection_test_count",
    "explicit_connection_test_count",
    "metadata_probe_count",
    "metadata_probe_violation_count",
    "cost_overview_autoload_violation_count",
    "query_search_broad_autorun_count",
    "target_pushdown_violation_count",
    "packet_cache_hit",
    "packet_size_bytes",
    "query_boundary",
    "elapsed_ms",
    "product_boundary",
    "execution_boundary",
    "passed",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_commit(root: Path | str = ".") -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(root),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


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
        query_boundary = str(row.get("query_boundary") or "").strip()
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
        pre_first_paint_session_open = _row_count(row, "pre_first_paint_session_open_count")
        shell_session_open = _row_count(row, "shell_session_open_count")
        active_session_probe = _row_count(row, "active_session_probe_count")
        admin_connection_test = _row_count(row, "admin_connection_test_count")
        explicit_connection_test = _row_count(row, "explicit_connection_test_count")
        metadata_probe_count = _row_count(row, "metadata_probe_count", "metadata_probe_events")
        metadata_probe_violation = _row_count(row, "metadata_probe_violation_count")
        cost_autoload_violation = _row_count(row, "cost_overview_autoload_violation_count")
        query_search_broad_autorun = _row_count(row, "query_search_broad_autorun_count")
        target_pushdown_violation = _row_count(row, "target_pushdown_violation_count")
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
        if section in PRIMARY_SECTIONS and cold_packet and query_boundary != "decision_packet":
            reasons.append("cold first-paint query boundary was not decision_packet")
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
        if pre_first_paint_session_open:
            reasons.append("session opened before first-paint boundary")
        if shell_session_open:
            reasons.append("shell opened a Snowflake session before section first paint")
        if active_session_probe:
            reasons.append("active session probe ran before section first paint")
        if admin_connection_test:
            reasons.append("admin connection test ran before section first paint")
        if explicit_connection_test:
            reasons.append("explicit connection test ran before section first paint")
        if metadata_probe_count > 1:
            reasons.append("metadata probing exceeded one probe for the object/session boundary")
        if metadata_probe_violation:
            reasons.append("metadata probe violation was recorded")
        if cost_autoload_violation:
            reasons.append("Cost Overview autoload violation was recorded")
        if query_search_broad_autorun:
            reasons.append("Query Search broad/deep autorun was recorded")
        if target_pushdown_violation:
            reasons.append("targeted evidence SQL pushdown violation was recorded")
        if session_open and section in PRIMARY_SECTIONS and cold_packet == 0:
            reasons.append("first paint opened a session outside the packet lookup")
        checked.append(
            {
                "section": section,
                "workflow": workflow,
                "boundary": "first_paint_packet",
                "product_boundary": product_boundary,
                "execution_boundary": execution_boundary,
                "query_boundary": query_boundary,
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
                "pre_first_paint_session_open_count": pre_first_paint_session_open,
                "shell_session_open_count": shell_session_open,
                "active_session_probe_count": active_session_probe,
                "admin_connection_test_count": admin_connection_test,
                "explicit_connection_test_count": explicit_connection_test,
                "metadata_probe_count": metadata_probe_count,
                "metadata_probe_violation_count": metadata_probe_violation,
                "cost_overview_autoload_violation_count": cost_autoload_violation,
                "query_search_broad_autorun_count": query_search_broad_autorun,
                "target_pushdown_violation_count": target_pushdown_violation,
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
        metadata_probe_count = _row_count(row, "metadata_probe_count", "metadata_probe_events")
        active_session_probe = _row_count(row, "active_session_probe_count")
        admin_connection_test = _row_count(row, "admin_connection_test_count")
        explicit_connection_test = _row_count(row, "explicit_connection_test_count")
        metadata_probe_violation = _row_count(row, "metadata_probe_violation_count")
        cost_autoload_violation = _row_count(row, "cost_overview_autoload_violation_count")
        query_search_broad_autorun = _row_count(row, "query_search_broad_autorun_count")
        target_pushdown_violation = _row_count(row, "target_pushdown_violation_count")
        pre_first_paint_session_open = _row_count(row, "pre_first_paint_session_open_count")
        shell_session_open = _row_count(row, "shell_session_open_count")
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
        if pre_first_paint_session_open:
            reasons.append("session opened before first-paint boundary")
        if shell_session_open:
            reasons.append("shell opened a Snowflake session before section first paint")
        if active_session_probe:
            reasons.append("active session probe ran before section first paint")
        if admin_connection_test:
            reasons.append("admin connection test ran before section first paint")
        if explicit_connection_test:
            reasons.append("explicit connection test ran before section first paint")
        if metadata_probe_count > 1:
            reasons.append("metadata probing exceeded one probe for the object/session boundary")
        if metadata_probe_violation:
            reasons.append("metadata probe violation was recorded")
        if cost_autoload_violation:
            reasons.append("Cost Overview autoload violation was recorded")
        if query_search_broad_autorun:
            reasons.append("Query Search broad/deep autorun was recorded")
        if target_pushdown_violation:
            reasons.append("targeted evidence SQL pushdown violation was recorded")
        checked.append(
            {
                "section": section,
                "workflow": str(row.get("workflow") or ""),
                "boundary": boundary,
                "query_count": query_count,
                "session_open_count": session_open,
                "direct_sql_count": direct_sql,
                "account_usage_count": account_usage,
                "metadata_probe_count": metadata_probe_count,
                "active_session_probe_count": active_session_probe,
                "admin_connection_test_count": admin_connection_test,
                "explicit_connection_test_count": explicit_connection_test,
                "metadata_probe_violation_count": metadata_probe_violation,
                "cost_overview_autoload_violation_count": cost_autoload_violation,
                "query_search_broad_autorun_count": query_search_broad_autorun,
                "target_pushdown_violation_count": target_pushdown_violation,
                "pre_first_paint_session_open_count": pre_first_paint_session_open,
                "shell_session_open_count": shell_session_open,
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
    cost_overview_payload: Any = None,
    target_pushdown_payload: Any = None,
    query_search_autorun_payload: Any = None,
    telemetry_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    first_paint_rows, first_paint_failures = _evaluate_first_paint_rows(_rows(first_paint_payload))
    budget_rows = _rows(query_budget_payload)
    if telemetry_rows is not None:
        budget_rows.extend(dict(row) for row in telemetry_rows if isinstance(row, Mapping))
    budget_checks, budget_failures = _evaluate_budget_rows(budget_rows)
    cost_payload = cost_overview_payload if isinstance(cost_overview_payload, Mapping) else {}
    cost_rows = _rows(cost_payload)
    cost_failures: list[dict[str, Any]] = []
    cost_violation_count = _as_int(cost_payload.get("cost_overview_autoload_violation_count"))
    if cost_overview_payload is not None:
        if not cost_payload:
            cost_failures.append({
                "section": "Cost & Contract",
                "workflow": "Cost Overview",
                "failure_reason": "missing Cost Overview no-autoload proof",
            })
        elif not bool(cost_payload.get("passed")):
            cost_failures.extend(
                {
                    "section": str(row.get("section") or "Cost & Contract"),
                    "workflow": str(row.get("workflow") or "Cost Overview"),
                    "failure_reason": str(row.get("failure_reason") or "Cost Overview autoload proof failed"),
                }
                for row in (cost_rows or [{"section": "Cost & Contract", "workflow": "Cost Overview"}])
            )
            if not cost_violation_count:
                cost_violation_count = max(1, len(cost_failures))
    target_pushdown_supplied = target_pushdown_payload is not None
    target_pushdown_payload = target_pushdown_payload if isinstance(target_pushdown_payload, Mapping) else {}
    target_pushdown_failures: list[dict[str, Any]] = []
    target_pushdown_violation_count = _as_int(target_pushdown_payload.get("target_pushdown_violation_count"))
    if target_pushdown_payload:
        if not bool(target_pushdown_payload.get("passed")):
            target_pushdown_failures.extend(
                {
                    "section": str(row.get("section") or "Targeted Evidence"),
                    "workflow": str(row.get("workflow") or "Evidence"),
                    "failure_reason": str(row.get("failure_reason") or "target SQL pushdown proof failed"),
                }
                for row in _rows(target_pushdown_payload)
                if not bool(row.get("passed"))
            )
            if not target_pushdown_violation_count:
                target_pushdown_violation_count = max(1, len(target_pushdown_failures))
    elif target_pushdown_supplied:
        target_pushdown_failures.append({
            "section": "Targeted Evidence",
            "workflow": "Evidence",
            "failure_reason": "missing target SQL pushdown proof",
        })
        target_pushdown_violation_count = 1

    query_search_autorun_supplied = query_search_autorun_payload is not None
    query_search_autorun_payload = query_search_autorun_payload if isinstance(query_search_autorun_payload, Mapping) else {}
    query_autorun_failures: list[dict[str, Any]] = []
    query_search_broad_autorun_count = _as_int(query_search_autorun_payload.get("query_search_broad_autorun_count"))
    if query_search_autorun_payload:
        if not bool(query_search_autorun_payload.get("passed")):
            query_autorun_failures.extend(
                {
                    "section": "Query Search",
                    "workflow": str(row.get("case") or row.get("workflow") or "Query Investigation"),
                    "failure_reason": str(row.get("failure_reason") or "Query Search autorun proof failed"),
                }
                for row in _rows(query_search_autorun_payload)
                if not bool(row.get("passed"))
            )
            if not query_search_broad_autorun_count:
                query_search_broad_autorun_count = max(1, len(query_autorun_failures))
    elif query_search_autorun_supplied:
        query_autorun_failures.append({
            "section": "Query Search",
            "workflow": "No click",
            "failure_reason": "missing Query Search autorun proof",
        })
        query_search_broad_autorun_count = 1

    failures = first_paint_failures + budget_failures + cost_failures + target_pushdown_failures + query_autorun_failures
    metadata_probe_violation_count = sum(
        1
        for row in [*first_paint_rows, *budget_checks]
        if _as_int(row.get("metadata_probe_count")) > 1
    )
    pre_first_paint_session_open_count = sum(
        _as_int(row.get("pre_first_paint_session_open_count")) for row in [*first_paint_rows, *budget_checks]
    )
    shell_session_open_count = sum(_as_int(row.get("shell_session_open_count")) for row in [*first_paint_rows, *budget_checks])
    return {
        "source": "performance_budget_gate",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "first_paint_rows": first_paint_rows,
        "query_budget_rows": budget_checks,
        "cost_overview_no_autoload_rows": cost_rows,
        "cost_overview_autoload_violation_count": cost_violation_count,
        "target_pushdown_violation_count": target_pushdown_violation_count,
        "query_search_broad_autorun_count": query_search_broad_autorun_count,
        "metadata_probe_violation_count": metadata_probe_violation_count,
        "pre_first_paint_session_open_count": pre_first_paint_session_open_count,
        "shell_session_open_count": shell_session_open_count,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_cost_overview_no_autoload_gate(payload: Any, *, commit_sha: str = "") -> dict[str, Any]:
    cost_payload = payload if isinstance(payload, Mapping) else {}
    rows = _rows(cost_payload)
    failures: list[dict[str, Any]] = []
    violation_count = _as_int(cost_payload.get("cost_overview_autoload_violation_count"))
    if not cost_payload:
        failures.append({
            "section": "Cost & Contract",
            "workflow": "Cost Overview",
            "failure_reason": "missing Cost Overview no-autoload runtime artifact",
        })
        violation_count = 1
    elif not bool(cost_payload.get("passed")):
        failures.extend(
            {
                "section": str(row.get("section") or "Cost & Contract"),
                "workflow": str(row.get("workflow") or "Cost Overview"),
                "failure_reason": str(row.get("failure_reason") or "Cost Overview no-autoload proof failed"),
            }
            for row in (rows or [{"section": "Cost & Contract", "workflow": "Cost Overview"}])
            if not bool(row.get("passed", cost_payload.get("passed")))
        )
        if not violation_count:
            violation_count = max(1, len(failures))
    return {
        "source": "cost_overview_no_autoload_gate_results",
        "producer": "performance_budget_gate",
        "producer_signature": "cost_overview_no_autoload_gate::v1",
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": str(commit_sha or cost_payload.get("commit_sha") or ""),
        "passed": not failures,
        "failure_count": len(failures),
        "cost_overview_autoload_violation_count": violation_count,
        "first_paint_packet_only": bool(cost_payload.get("first_paint_packet_only", True)) and not failures,
        "evidence_autoload_count": _as_int(cost_payload.get("evidence_autoload_count")),
        "cost_workbench_autoload_count": _as_int(cost_payload.get("cost_workbench_autoload_count")),
        "chart_detail_autoload_count": _as_int(cost_payload.get("chart_detail_autoload_count")),
        "account_usage_autoload_count": _as_int(cost_payload.get("account_usage_autoload_count")),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_performance_budget_gate_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    first_paint = _load_json(root_path / f"{FULL_APP_DIR}/first_paint_performance_results.json")
    query_budget = _load_json(root_path / f"{FULL_APP_DIR}/query_budget_results.json")
    cost_overview = _load_json(root_path / COST_OVERVIEW_NO_AUTOLOAD_RESULTS_REL)
    target_pushdown = _load_json(root_path / TARGETED_EVIDENCE_SQL_PUSHDOWN_RESULTS_REL)
    query_search_autorun = _load_json(root_path / QUERY_SEARCH_AUTORUN_RESULTS_REL)
    gate = evaluate_performance_budget_gate(first_paint, query_budget, cost_overview, target_pushdown, query_search_autorun)
    cost_gate = evaluate_cost_overview_no_autoload_gate(cost_overview, commit_sha=_git_commit(root_path))
    results = {
        "source": "performance_budget_results",
        "generated_at": _now(),
        "passed": bool(gate.get("passed")),
        "failure_count": int(gate.get("failure_count") or 0),
        "first_paint_rows": gate.get("first_paint_rows", []),
        "query_budget_rows": gate.get("query_budget_rows", []),
        "cost_overview_no_autoload_rows": gate.get("cost_overview_no_autoload_rows", []),
        "cost_overview_autoload_violation_count": int(gate.get("cost_overview_autoload_violation_count") or 0),
        "target_pushdown_violation_count": int(gate.get("target_pushdown_violation_count") or 0),
        "query_search_broad_autorun_count": int(gate.get("query_search_broad_autorun_count") or 0),
        "metadata_probe_violation_count": int(gate.get("metadata_probe_violation_count") or 0),
        "pre_first_paint_session_open_count": int(gate.get("pre_first_paint_session_open_count") or 0),
        "shell_session_open_count": int(gate.get("shell_session_open_count") or 0),
        "raw_sql_included": False,
    }
    _write_json(root_path / PERFORMANCE_BUDGET_RESULTS_REL, results)
    _write_json(root_path / PERFORMANCE_BUDGET_GATE_REL, gate)
    _write_json(root_path / COST_OVERVIEW_NO_AUTOLOAD_GATE_REL, cost_gate)
    return {
        PERFORMANCE_BUDGET_RESULTS_REL: results,
        PERFORMANCE_BUDGET_GATE_REL: gate,
        COST_OVERVIEW_NO_AUTOLOAD_GATE_REL: cost_gate,
    }


if __name__ == "__main__":
    artifacts = write_performance_budget_gate_artifacts(Path("."))
    gate = artifacts[PERFORMANCE_BUDGET_GATE_REL]
    if not bool(gate.get("passed")):
        raise SystemExit(1)


__all__ = [
    "COST_OVERVIEW_NO_AUTOLOAD_RESULTS_REL",
    "COST_OVERVIEW_NO_AUTOLOAD_GATE_REL",
    "QUERY_SEARCH_AUTORUN_RESULTS_REL",
    "TARGETED_EVIDENCE_SQL_PUSHDOWN_RESULTS_REL",
    "PERFORMANCE_BUDGET_GATE_REL",
    "PERFORMANCE_BUDGET_RESULTS_REL",
    "PRIMARY_SECTIONS",
    "evaluate_cost_overview_no_autoload_gate",
    "evaluate_performance_budget_gate",
    "write_performance_budget_gate_artifacts",
]
