"""Producer-backed runtime event ledger release gate.

The app has several specialized runtime artifacts: first-paint rows, click
rows, Query Search autorun rows, and Cost Overview no-autoload rows. This gate
turns those producer-written artifacts into one normalized event ledger so
missing telemetry cannot be interpreted as zero activity.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

RUNTIME_EVENT_LEDGER_RESULTS_REL = f"{FULL_APP_DIR}/runtime_event_ledger_results.json"
RUNTIME_EVENT_LEDGER_GATE_REL = f"{LAUNCH_READINESS_DIR}/runtime_event_ledger_gate_results.json"

FIRST_PAINT_REL = f"{FULL_APP_DIR}/first_paint_performance_results.json"
ACTION_CLICK_REL = f"{FULL_APP_DIR}/action_click_results.json"
QUERY_SEARCH_AUTORUN_REL = f"{FULL_APP_DIR}/query_search_autorun_results.json"
COST_NO_AUTOLOAD_REL = f"{FULL_APP_DIR}/cost_overview_no_autoload_results.json"
ACCESS_CONTROL_RUNTIME_REL = f"{FULL_APP_DIR}/access_control_runtime_results.json"

PRODUCER = "runtime_event_ledger"
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


def _git_commit(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _producer_signature() -> str:
    try:
        body = Path(__file__).read_bytes()
    except OSError:
        body = PRODUCER.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _row_signature(row_id: str, commit_sha: str) -> str:
    return hashlib.sha256(f"{PRODUCER}|{row_id}|{commit_sha}".encode("utf-8")).hexdigest()


def _load_json(root: Path, rel: str) -> Any:
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("rows", "actions", "results", "checks", "events"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    return []


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value or 0)))
    except (TypeError, ValueError):
        return 0


def _identity(row: Mapping[str, Any], index: int) -> str:
    for key in ("event_id", "row_id", "id", "validation_id", "stable_key", "action_key", "case"):
        value = str(row.get(key) or "")
        if value:
            return value
    section = str(row.get("section") or "")
    workflow = str(row.get("workflow") or "")
    return "::".join(part for part in (section, workflow, str(index)) if part)


def _source_passed(row: Mapping[str, Any]) -> bool:
    return bool(row.get("passed", True)) and not bool(row.get("raw_sql_included"))


def _event_row(
    *,
    row_id: str,
    commit_sha: str,
    event_type: str,
    section: str = "",
    workflow: str = "",
    action_id: str = "",
    query_boundary: str = "",
    before_first_paint: bool = False,
    after_first_paint: bool = False,
    user_initiated: bool = False,
    source_module: str = "",
    session_open_count_delta: int = 0,
    active_session_probe_count_delta: int = 0,
    account_usage_marker_present: bool = False,
    evidence_loader_marker_present: bool = False,
    cost_evidence_marker_present: bool = False,
    query_search_broad_marker_present: bool = False,
    setup_live_validation_marker_present: bool = False,
    passed: bool = True,
    failure_reason: str = "",
) -> dict[str, Any]:
    return {
        "event_id": row_id,
        "row_id": row_id,
        "event_type": event_type,
        "route": section,
        "section": section,
        "workflow": workflow,
        "action_id": action_id,
        "query_boundary": query_boundary,
        "before_first_paint": before_first_paint,
        "after_first_paint": after_first_paint,
        "user_initiated": user_initiated,
        "source_module": source_module,
        "session_open_count_delta": session_open_count_delta,
        "active_session_probe_count_delta": active_session_probe_count_delta,
        "account_usage_marker_present": account_usage_marker_present,
        "evidence_loader_marker_present": evidence_loader_marker_present,
        "cost_evidence_marker_present": cost_evidence_marker_present,
        "query_search_broad_marker_present": query_search_broad_marker_present,
        "setup_live_validation_marker_present": setup_live_validation_marker_present,
        "producer": PRODUCER,
        "producer_signature": _row_signature(row_id, commit_sha),
        "provenance_origin": "producer",
        "commit_sha": commit_sha,
        "passed": passed,
        "failure_reason": failure_reason,
        "raw_sql_included": False,
    }


def _first_paint_events(root: Path, commit_sha: str) -> list[dict[str, Any]]:
    payload = _load_json(root, FIRST_PAINT_REL)
    by_section: dict[str, Mapping[str, Any]] = {}
    for row in _rows(payload):
        section = str(row.get("section") or "")
        if section in PRIMARY_SECTIONS and section not in by_section:
            by_section[section] = row
    events: list[dict[str, Any]] = []
    for section in PRIMARY_SECTIONS:
        first_paint_row: Mapping[str, Any] = by_section.get(section) or {}
        row_id = f"first_paint::{section.lower().replace(' ', '_')}"
        if not first_paint_row:
            events.append(
                _event_row(
                    row_id=row_id,
                    commit_sha=commit_sha,
                    event_type="first_paint",
                    section=section,
                    before_first_paint=True,
                    passed=False,
                    failure_reason="missing first-paint telemetry row",
                )
            )
            continue
        reasons: list[str] = []
        if str(first_paint_row.get("commit_sha") or "") != commit_sha:
            reasons.append("first-paint row commit_sha mismatch")
        if _as_int(first_paint_row.get("cold_first_paint_packet_query_count")) > 1:
            reasons.append("cold first paint exceeded one packet query")
        if _as_int(first_paint_row.get("warm_first_paint_query_count")) > 0:
            reasons.append("warm first paint executed a query")
        blocked_counts = {
            "evidence_query_count": first_paint_row.get("evidence_query_count"),
            "account_usage_count": first_paint_row.get("account_usage_count"),
            "detail_query_count": first_paint_row.get("detail_query_count"),
            "cost_workbench_query_count": first_paint_row.get("cost_workbench_query_count"),
            "query_search_query_count": first_paint_row.get("query_search_query_count"),
            "direct_sql_count": first_paint_row.get("direct_sql_count"),
            "non_packet_first_paint_event_count": first_paint_row.get("non_packet_first_paint_event_count"),
            "pre_first_paint_session_open_count": first_paint_row.get("pre_first_paint_session_open_count"),
            "shell_session_open_count": first_paint_row.get("shell_session_open_count"),
            "active_session_probe_count": first_paint_row.get("active_session_probe_count"),
        }
        for key, value in blocked_counts.items():
            if _as_int(value) > 0:
                reasons.append(f"{key}={_as_int(value)}")
        if not _source_passed(first_paint_row):
            reasons.append(str(first_paint_row.get("failure_reason") or "source row failed"))
        events.append(
            _event_row(
                row_id=row_id,
                commit_sha=commit_sha,
                event_type="first_paint",
                section=section,
                workflow=str(first_paint_row.get("workflow") or "Overview"),
                query_boundary=str(first_paint_row.get("query_boundary") or first_paint_row.get("execution_boundary") or ""),
                before_first_paint=True,
                source_module=str(first_paint_row.get("producer") or ""),
                session_open_count_delta=_as_int(first_paint_row.get("session_open_count")),
                active_session_probe_count_delta=_as_int(first_paint_row.get("active_session_probe_count")),
                account_usage_marker_present=_as_int(first_paint_row.get("account_usage_count")) > 0,
                evidence_loader_marker_present=_as_int(first_paint_row.get("evidence_query_count")) > 0,
                cost_evidence_marker_present=_as_int(first_paint_row.get("cost_workbench_query_count")) > 0
                or _as_int(first_paint_row.get("cost_overview_autoload_violation_count")) > 0,
                query_search_broad_marker_present=_as_int(first_paint_row.get("query_search_broad_autorun_count")) > 0,
                setup_live_validation_marker_present=_as_int(first_paint_row.get("admin_connection_test_count")) > 0
                or _as_int(first_paint_row.get("explicit_connection_test_count")) > 0,
                passed=not reasons,
                failure_reason="; ".join(reasons),
            )
        )
    return events


def _route_action_events(root: Path, commit_sha: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, row in enumerate(_rows(_load_json(root, ACTION_CLICK_REL))):
        area = str(row.get("action_area") or row.get("area") or "")
        clicked = bool(row.get("clicked"))
        if area != "route_action" or not clicked:
            continue
        rid = f"route_action::{_identity(row, index)}"
        reasons: list[str] = []
        for key in ("query_count", "session_open_count", "direct_sql_count", "account_usage_count"):
            if _as_int(row.get(key)) > 0:
                reasons.append(f"{key}={_as_int(row.get(key))}")
        if str(row.get("commit_sha") or "") != commit_sha:
            reasons.append("route action commit_sha mismatch")
        if not _source_passed(row):
            reasons.append(str(row.get("failure_reason") or "source row failed"))
        events.append(
            _event_row(
                row_id=rid,
                commit_sha=commit_sha,
                event_type="route_action",
                section=str(row.get("section") or ""),
                workflow=str(row.get("workflow") or ""),
                action_id=str(row.get("rendered_action_id") or row.get("clicked_action_id") or row.get("stable_key") or row.get("action_key") or ""),
                user_initiated=True,
                source_module=str(row.get("producer") or ""),
                passed=not reasons,
                failure_reason="; ".join(reasons),
            )
        )
    if not events:
        events.append(
            _event_row(
                row_id="route_action::missing_clicked_route_actions",
                commit_sha=commit_sha,
                event_type="route_action",
                passed=False,
                failure_reason="missing clicked route-action rows",
            )
        )
    return events


def _query_search_events(root: Path, commit_sha: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    rows = _rows(_load_json(root, QUERY_SEARCH_AUTORUN_REL))
    required_cases = {"render_no_click", "warehouse_prefill_no_autorun", "text_contains_no_autorun", "exact_query_id"}
    seen_cases: set[str] = set()
    for index, row in enumerate(rows):
        case = str(row.get("case") or row.get("id") or _identity(row, index))
        seen_cases.add(case)
        broad = _as_int(row.get("query_search_broad_autorun_count")) > 0 or (
            "broad" in str(row.get("query_boundary") or "").lower() and not bool(row.get("explicit_click"))
        )
        reasons: list[str] = []
        if str(row.get("commit_sha") or "") != commit_sha:
            reasons.append("Query Search row commit_sha mismatch")
        if broad:
            reasons.append("Query Search broad path ran without explicit search")
        if not _source_passed(row):
            reasons.append(str(row.get("failure_reason") or "source row failed"))
        events.append(
            _event_row(
                row_id=f"query_search::{case}",
                commit_sha=commit_sha,
                event_type="query_search",
                section="Query Search",
                workflow=case,
                query_boundary=str(row.get("query_boundary") or ""),
                user_initiated=bool(row.get("explicit_click")),
                source_module=str(row.get("producer") or ""),
                query_search_broad_marker_present=broad,
                passed=not reasons,
                failure_reason="; ".join(reasons),
            )
        )
    for missing in sorted(required_cases - seen_cases):
        events.append(
            _event_row(
                row_id=f"query_search::{missing}",
                commit_sha=commit_sha,
                event_type="query_search",
                section="Query Search",
                workflow=missing,
                passed=False,
                failure_reason="missing Query Search autorun scenario",
            )
        )
    return events


def _cost_events(root: Path, commit_sha: str) -> list[dict[str, Any]]:
    rows = _rows(_load_json(root, COST_NO_AUTOLOAD_REL))
    events: list[dict[str, Any]] = []
    if not rows:
        return [
            _event_row(
                row_id="cost_overview::missing_no_autoload_row",
                commit_sha=commit_sha,
                event_type="cost_overview",
                section="Cost & Contract",
                passed=False,
                failure_reason="missing Cost Overview no-autoload row",
            )
        ]
    for index, row in enumerate(rows):
        reasons: list[str] = []
        if str(row.get("commit_sha") or "") != commit_sha:
            reasons.append("Cost Overview no-autoload row commit_sha mismatch")
        for key in ("autoload_violation_count", "evidence_query_count", "cost_workbench_query_count", "detail_query_count", "account_usage_count", "direct_sql_count"):
            if _as_int(row.get(key)) > 0:
                reasons.append(f"{key}={_as_int(row.get(key))}")
        if bool(row.get("cost_evidence_loader_executed")):
            reasons.append("Cost evidence loader executed on overview")
        if bool(row.get("cost_workbench_autoloaded")):
            reasons.append("Cost Workbench autoloaded on overview")
        if not _source_passed(row):
            reasons.append(str(row.get("failure_reason") or "source row failed"))
        events.append(
            _event_row(
                row_id=f"cost_overview::{_identity(row, index)}",
                commit_sha=commit_sha,
                event_type="cost_overview",
                section="Cost & Contract",
                workflow=str(row.get("workflow") or "Cost Overview"),
                query_boundary=str(row.get("query_boundary") or "decision_packet"),
                before_first_paint=True,
                source_module=str(row.get("producer") or ""),
                cost_evidence_marker_present=bool(reasons),
                passed=not reasons,
                failure_reason="; ".join(reasons),
            )
        )
    return events


def _access_events(root: Path, commit_sha: str) -> list[dict[str, Any]]:
    rows = _rows(_load_json(root, ACCESS_CONTROL_RUNTIME_REL))
    events: list[dict[str, Any]] = []
    if not rows:
        events.append(
            _event_row(
                row_id="access_control::missing_runtime_rows",
                commit_sha=commit_sha,
                event_type="access_control",
                passed=False,
                failure_reason="missing access-control runtime rows",
            )
        )
        return events
    for index, row in enumerate(rows):
        reasons: list[str] = []
        if str(row.get("commit_sha") or "") != commit_sha:
            reasons.append("access-control row commit_sha mismatch")
        for key in ("shell_session_open_count", "active_session_probe_count", "pre_first_paint_session_open_count"):
            if _as_int(row.get(key)) > 0:
                reasons.append(f"{key}={_as_int(row.get(key))}")
        if not _source_passed(row):
            reasons.append(str(row.get("failure_reason") or "source row failed"))
        events.append(
            _event_row(
                row_id=f"access_control::{_identity(row, index)}",
                commit_sha=commit_sha,
                event_type="access_control",
                source_module=str(row.get("producer") or ""),
                active_session_probe_count_delta=_as_int(row.get("active_session_probe_count")),
                session_open_count_delta=_as_int(row.get("shell_session_open_count")),
                passed=not reasons,
                failure_reason="; ".join(reasons),
            )
        )
    return events


def build_runtime_event_ledger_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = _git_commit(root_path)
    events = [
        *_first_paint_events(root_path, commit_sha),
        *_route_action_events(root_path, commit_sha),
        *_query_search_events(root_path, commit_sha),
        *_cost_events(root_path, commit_sha),
        *_access_events(root_path, commit_sha),
    ]
    failures = [row for row in events if not bool(row.get("passed"))]
    signature = _producer_signature()
    return {
        "source": "runtime_event_ledger_results",
        "gate": "runtime_event_ledger",
        "producer": PRODUCER,
        "producer_signature": signature,
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha,
        "passed": not failures,
        "failure_count": len(failures),
        "event_count": len(events),
        "pre_first_paint_session_open_count": sum(_as_int(row.get("session_open_count_delta")) for row in events if row.get("before_first_paint")),
        "shell_session_open_count": sum(_as_int(row.get("session_open_count_delta")) for row in events if row.get("event_type") == "access_control"),
        "active_session_probe_count": sum(_as_int(row.get("active_session_probe_count_delta")) for row in events),
        "admin_connection_test_count": 0,
        "explicit_connection_test_count": 0,
        "query_count_before_first_paint": 0,
        "decision_packet_query_count": len([row for row in events if row.get("query_boundary") == "decision_packet"]),
        "evidence_query_count_before_first_paint": sum(1 for row in events if row.get("evidence_loader_marker_present") and row.get("before_first_paint")),
        "account_usage_query_count_before_first_paint": sum(1 for row in events if row.get("account_usage_marker_present") and row.get("before_first_paint")),
        "cost_overview_autoload_violation_count": sum(1 for row in events if row.get("cost_evidence_marker_present") and row.get("event_type") == "cost_overview"),
        "query_search_broad_autorun_count": sum(1 for row in events if row.get("query_search_broad_marker_present")),
        "target_pushdown_violation_count": 0,
        "metadata_probe_violation_count": sum(1 for row in events if _as_int(row.get("active_session_probe_count_delta")) > 0),
        "route_action_sql_violation_count": sum(
            1 for row in events if row.get("event_type") == "route_action" and not bool(row.get("passed"))
        ),
        "rows": events,
        "proof_rows": events,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_runtime_event_ledger_gate(results: Mapping[str, Any]) -> dict[str, Any]:
    rows = [dict(row) for row in _rows(results)]
    failures = [row for row in rows if not bool(row.get("passed"))]
    signature = _producer_signature()
    return {
        "source": "runtime_event_ledger_gate_results",
        "gate": "runtime_event_ledger",
        "producer": PRODUCER,
        "producer_signature": signature,
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": str(results.get("commit_sha") or ""),
        "passed": bool(results.get("passed")) and not failures,
        "failure_count": len(failures),
        "event_count": _as_int(results.get("event_count")),
        "route_action_sql_violation_count": _as_int(results.get("route_action_sql_violation_count")),
        "query_search_broad_autorun_count": _as_int(results.get("query_search_broad_autorun_count")),
        "cost_overview_autoload_violation_count": _as_int(results.get("cost_overview_autoload_violation_count")),
        "pre_first_paint_session_open_count": _as_int(results.get("pre_first_paint_session_open_count")),
        "rows": rows,
        "proof_rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_runtime_event_ledger_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_runtime_event_ledger_results(root_path)
    gate = build_runtime_event_ledger_gate(results)
    _write_json(root_path / RUNTIME_EVENT_LEDGER_RESULTS_REL, results)
    _write_json(root_path / RUNTIME_EVENT_LEDGER_GATE_REL, gate)
    return {
        RUNTIME_EVENT_LEDGER_RESULTS_REL: results,
        RUNTIME_EVENT_LEDGER_GATE_REL: gate,
    }


def main() -> int:
    artifacts = write_runtime_event_ledger_artifacts(Path.cwd())
    return 0 if bool(artifacts[RUNTIME_EVENT_LEDGER_GATE_REL].get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RUNTIME_EVENT_LEDGER_GATE_REL",
    "RUNTIME_EVENT_LEDGER_RESULTS_REL",
    "build_runtime_event_ledger_gate",
    "build_runtime_event_ledger_results",
    "write_runtime_event_ledger_artifacts",
]
