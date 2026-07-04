"""Query Search autorun contract for no-click and broad-search safety."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

QUERY_SEARCH_AUTORUN_RESULTS_REL = f"{FULL_APP_DIR}/query_search_autorun_results.json"
QUERY_SEARCH_AUTORUN_GATE_REL = f"{LAUNCH_READINESS_DIR}/query_search_autorun_gate_results.json"

NO_AUTORUN_CASES = {
    "render_no_click",
    "text_contains_no_autorun",
    "warehouse_prefill_no_autorun",
    "account_usage_fallback_unconfirmed",
}
EXACT_AUTORUN_CASES = {"exact_query_id", "query_signature"}
BROAD_EXPLICIT_CASES = {"account_usage_fallback_confirmed", "text_contains_explicit_search"}
REQUIRED_CASES = NO_AUTORUN_CASES | EXACT_AUTORUN_CASES | BROAD_EXPLICIT_CASES


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
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
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, Mapping):
        for key in ("rows", "results", "cases"):
            rows = value.get(key)
            if isinstance(rows, list):
                return list(rows)
    return []


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _boundaries(row: Mapping[str, Any]) -> set[str]:
    raw = row.get("observed_boundaries") or row.get("query_boundaries") or row.get("observed_actual_boundaries")
    if isinstance(raw, Mapping):
        return {str(key) for key in raw if _as_int(raw.get(key)) >= 0}
    if isinstance(raw, list):
        return {str(value) for value in raw}
    value = str(row.get("query_boundary") or "").strip()
    return {value} if value else set()


def evaluate_query_search_autorun(payload: Any, *, root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    source_rows = [dict(row) for row in _as_list(payload) if isinstance(row, Mapping)]
    rows: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    commit = _git_commit(root_path)
    for source_row in source_rows:
        case = str(source_row.get("case") or "").strip()
        if not case:
            continue
        if case in REQUIRED_CASES:
            seen_cases.add(case)
        executions = _as_int(source_row.get("snowflake_execution_count") or source_row.get("query_count"))
        session_open = _as_int(source_row.get("session_open_count"))
        direct_sql = _as_int(source_row.get("direct_sql_count") or source_row.get("direct_sql_event_count"))
        account_usage = _as_int(source_row.get("account_usage_count") or source_row.get("account_usage_event_count"))
        max_rows = _as_int(source_row.get("max_rows"))
        boundaries = _boundaries(source_row)
        projects_query_text = bool(source_row.get("projects_query_text"))
        reasons: list[str] = []
        if case in NO_AUTORUN_CASES and (executions or session_open or direct_sql or account_usage):
            reasons.append("Query Search no-click/prefill path executed query/session/direct SQL")
        if case in EXACT_AUTORUN_CASES:
            if case == "exact_query_id" and max_rows and max_rows > 1:
                reasons.append("exact query ID autorun was not row-limited to one")
            if "query_search_broad_explicit" in boundaries:
                reasons.append("exact/signature autorun used broad explicit boundary")
            if executions and not (boundaries & {"query_search_exact"}):
                reasons.append("exact/signature autorun did not prove query_search_exact boundary")
        if case in BROAD_EXPLICIT_CASES:
            if executions and "query_search_broad_explicit" not in boundaries:
                reasons.append("broad search execution missing query_search_broad_explicit boundary")
        if projects_query_text and case != "sql_preview":
            reasons.append("default Query Search path projected query_text")
        rows.append(
            {
                "id": f"query_search_autorun::{case}",
                "case": case,
                "section": "Query Search",
                "workflow": str(source_row.get("workflow") or "Query Investigation"),
                "producer": "query_search_autorun",
                "producer_signature": "query_search_autorun::v1",
                "provenance_origin": "producer",
                "runtime_source": str(source_row.get("runtime_source") or "query_search_results"),
                "proof_source": "runtime_query_search_results",
                "source": "query_search_autorun",
                "generated_at": _now(),
                "commit_sha": str(source_row.get("commit_sha") or commit),
                "snowflake_execution_count": executions,
                "session_open_count": session_open,
                "direct_sql_count": direct_sql,
                "account_usage_count": account_usage,
                "max_rows": max_rows,
                "observed_boundaries": sorted(boundaries),
                "projects_query_text": projects_query_text,
                "passed": not reasons,
                "failure_reason": "; ".join(reasons),
                "raw_sql_included": False,
            }
        )
    missing_cases = sorted(REQUIRED_CASES - seen_cases)
    for case in missing_cases:
        rows.append(
            {
                "id": f"query_search_autorun::{case}",
                "case": case,
                "section": "Query Search",
                "workflow": "Query Investigation",
                "producer": "query_search_autorun",
                "producer_signature": "query_search_autorun::v1",
                "provenance_origin": "producer",
                "runtime_source": "query_search_results",
                "proof_source": "runtime_query_search_results",
                "source": "query_search_autorun",
                "generated_at": _now(),
                "commit_sha": commit,
                "passed": False,
                "failure_reason": "required Query Search autorun proof case missing",
                "raw_sql_included": False,
            }
        )
    failures = [row for row in rows if not bool(row.get("passed"))]
    query_search_broad_autorun_count = sum(
        1
        for row in rows
        if row.get("case") in NO_AUTORUN_CASES and _as_int(row.get("snowflake_execution_count"))
    )
    return {
        "source": "query_search_autorun_results",
        "producer": "query_search_autorun",
        "producer_signature": "query_search_autorun::v1",
        "provenance_origin": "producer",
        "runtime_source": "query_search_results",
        "proof_source": "runtime_query_search_results",
        "generated_at": _now(),
        "commit_sha": commit,
        "passed": not failures,
        "failure_count": len(failures),
        "query_search_broad_autorun_count": query_search_broad_autorun_count,
        "required_case_count": len(REQUIRED_CASES),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_query_search_autorun_gate(payload: Any) -> dict[str, Any]:
    results = payload if isinstance(payload, Mapping) else {}
    failures = results.get("failures") if isinstance(results.get("failures"), list) else []
    rows = results.get("rows") if isinstance(results.get("rows"), list) else []
    return {
        "source": "query_search_autorun_gate_results",
        "producer": "query_search_autorun",
        "producer_signature": "query_search_autorun_gate::v1",
        "provenance_origin": "producer",
        "commit_sha": str(results.get("commit_sha") or ""),
        "generated_at": _now(),
        "passed": bool(results.get("passed")) and not failures,
        "failure_count": len(failures) if failures else _as_int(results.get("failure_count")),
        "query_search_broad_autorun_count": _as_int(results.get("query_search_broad_autorun_count")),
        "required_case_count": _as_int(results.get("required_case_count")),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_query_search_autorun_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    query_search = _load_json(root_path / f"{FULL_APP_DIR}/query_search_results.json")
    results = evaluate_query_search_autorun(query_search, root=root_path)
    gate = evaluate_query_search_autorun_gate(results)
    _write_json(root_path / QUERY_SEARCH_AUTORUN_RESULTS_REL, results)
    _write_json(root_path / QUERY_SEARCH_AUTORUN_GATE_REL, gate)
    return {
        QUERY_SEARCH_AUTORUN_RESULTS_REL: results,
        QUERY_SEARCH_AUTORUN_GATE_REL: gate,
    }


if __name__ == "__main__":
    artifacts = write_query_search_autorun_artifacts(Path("."))
    if not bool(artifacts[QUERY_SEARCH_AUTORUN_GATE_REL].get("passed")):
        raise SystemExit(1)


__all__ = [
    "QUERY_SEARCH_AUTORUN_GATE_REL",
    "QUERY_SEARCH_AUTORUN_RESULTS_REL",
    "evaluate_query_search_autorun",
    "evaluate_query_search_autorun_gate",
    "write_query_search_autorun_artifacts",
]
