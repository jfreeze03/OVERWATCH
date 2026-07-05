"""Producer-backed runtime event ledger release gate.

The app has several specialized runtime artifacts: first-paint rows, click
rows, Query Search autorun rows, and Cost Overview no-autoload rows. This gate
turns those producer-written artifacts into one normalized event ledger so
missing telemetry cannot be interpreted as zero activity.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

RUNTIME_EVENT_LEDGER_RESULTS_REL = f"{FULL_APP_DIR}/runtime_event_ledger_results.json"
RUNTIME_EVENT_LEDGER_GATE_REL = f"{LAUNCH_READINESS_DIR}/runtime_event_ledger_gate_results.json"

FIRST_PAINT_REL = f"{FULL_APP_DIR}/first_paint_performance_results.json"
ACTION_CLICK_REL = f"{FULL_APP_DIR}/action_click_results.json"
BUTTON_CLICK_REL = f"{FULL_APP_DIR}/button_click_results.json"
QUERY_SEARCH_AUTORUN_REL = f"{FULL_APP_DIR}/query_search_autorun_results.json"
COST_NO_AUTOLOAD_REL = f"{FULL_APP_DIR}/cost_overview_no_autoload_results.json"
ACCESS_CONTROL_RUNTIME_REL = f"{FULL_APP_DIR}/access_control_runtime_results.json"
SOURCE_RUNTIME_EVENT_LEDGER_REL = f"{FULL_APP_DIR}/source_runtime_event_ledger_results.json"
SOURCE_RUNTIME_EVENT_LEDGER_GATE_REL = f"{LAUNCH_READINESS_DIR}/source_runtime_event_ledger_gate_results.json"

PRODUCER = "runtime_event_ledger"
PRIMARY_SECTIONS = (
    "Executive Landing",
    "DBA Control Room",
    "Alert Center",
    "Cost & Contract",
    "Workload Operations",
    "Security Monitoring",
)

_FALLBACK_APPROVED_BOUNDARIES = {
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


def _runtime_boundary_helpers(root: Path) -> tuple[set[str], Any]:
    boundary_path = root / ".overwatch_final" / "runtime_boundaries.py"
    if boundary_path.exists():
        spec = importlib.util.spec_from_file_location("_overwatch_runtime_boundaries", boundary_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            approved = getattr(module, "APPROVED_RELEASE_EXECUTION_BOUNDARIES", None)
            normalizer = getattr(module, "normalize_release_boundary", None)
            if approved and callable(normalizer):
                return {str(item) for item in approved}, normalizer
    return set(_FALLBACK_APPROVED_BOUNDARIES), lambda value: str(value or "").strip().lower() if str(value or "").strip().lower() in _FALLBACK_APPROVED_BOUNDARIES else "metadata_bounded"


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


def _action_click_rows(root: Path) -> list[Mapping[str, Any]]:
    rows = _rows(_load_json(root, ACTION_CLICK_REL))
    if rows:
        return rows
    return _rows(_load_json(root, BUTTON_CLICK_REL))


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
    query_count_delta: int = 0,
    max_rows: int | None = None,
    session_open_count_delta: int = 0,
    active_session_probe_count_delta: int = 0,
    direct_sql_count_delta: int = 0,
    account_usage_count_delta: int = 0,
    metadata_probe_count_delta: int = 0,
    account_usage_marker_present: bool = False,
    evidence_loader_marker_present: bool = False,
    cost_evidence_marker_present: bool = False,
    query_search_broad_marker_present: bool = False,
    setup_live_validation_marker_present: bool = False,
    route_action_marker_present: bool = False,
    target_pushdown_violation: bool = False,
    broad_load_before_filter: bool = False,
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
        "query_count_delta": query_count_delta,
        "max_rows": None if max_rows is None else int(max_rows),
        "session_open_count_delta": session_open_count_delta,
        "active_session_probe_count_delta": active_session_probe_count_delta,
        "direct_sql_count_delta": direct_sql_count_delta,
        "account_usage_count_delta": account_usage_count_delta,
        "metadata_probe_count_delta": metadata_probe_count_delta,
        "account_usage_marker_present": account_usage_marker_present,
        "evidence_loader_marker_present": evidence_loader_marker_present,
        "cost_evidence_marker_present": cost_evidence_marker_present,
        "query_search_broad_marker_present": query_search_broad_marker_present,
        "setup_live_validation_marker_present": setup_live_validation_marker_present,
        "route_action_marker_present": route_action_marker_present,
        "target_pushdown_violation": target_pushdown_violation,
        "broad_load_before_filter": broad_load_before_filter,
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
        cold_packet_count = _as_int(first_paint_row.get("cold_first_paint_packet_query_count"))
        session_open_count = _as_int(first_paint_row.get("session_open_count"))
        allowed_packet_sessions = cold_packet_count if (
            cold_packet_count <= 1
            and str(first_paint_row.get("query_boundary") or first_paint_row.get("execution_boundary") or "") == "decision_packet"
        ) else 0
        first_paint_session_violation_count = max(0, session_open_count - allowed_packet_sessions)
        blocked_counts = {
            "evidence_query_count": first_paint_row.get("evidence_query_count"),
            "account_usage_count": first_paint_row.get("account_usage_count"),
            "detail_query_count": first_paint_row.get("detail_query_count"),
            "cost_workbench_query_count": first_paint_row.get("cost_workbench_query_count"),
            "query_search_query_count": first_paint_row.get("query_search_query_count"),
            "direct_sql_count": first_paint_row.get("direct_sql_count"),
            "session_open_count": first_paint_session_violation_count,
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
                session_open_count_delta=first_paint_session_violation_count,
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
    for index, row in enumerate(_action_click_rows(root)):
        area = str(row.get("action_area") or row.get("area") or "")
        clicked = bool(row.get("clicked"))
        if area != "route_action" or not clicked:
            continue
        rid = f"route_action::{_identity(row, index)}"
        reasons: list[str] = []
        query_count = _as_int(row.get("query_count") if row.get("query_count") is not None else row.get("actual_snowflake_executions"))
        if query_count > 0:
            reasons.append(f"query_count={query_count}")
        for key in ("session_open_count", "direct_sql_count", "account_usage_count"):
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
                route_action_marker_present=True,
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


def _source_runtime_events(root: Path, commit_sha: str) -> list[dict[str, Any]]:
    approved_boundaries, normalize_boundary = _runtime_boundary_helpers(root)
    payload = _load_json(root, SOURCE_RUNTIME_EVENT_LEDGER_REL)
    rows = _rows(payload)
    if not rows:
        return [
            _event_row(
                row_id="source_runtime_event_ledger::missing",
                commit_sha=commit_sha,
                event_type="source_runtime_event",
                passed=False,
                failure_reason="missing app-source runtime event ledger rows",
            )
        ]
    events: list[dict[str, Any]] = []
    summary_autoload_count = 0
    for index, row in enumerate(rows):
        reasons: list[str] = []
        if bool(row.get("raw_sql_included")):
            reasons.append("source runtime event includes raw SQL")
        row_commit = str(row.get("commit_sha") or "")
        if row_commit and row_commit != commit_sha:
            reasons.append("source runtime event commit_sha mismatch")
        event_type = str(row.get("event_type") or "source_runtime_event")
        raw_boundary = str(row.get("execution_boundary") or row.get("query_boundary") or row.get("boundary") or "")
        boundary = str(normalize_boundary(raw_boundary))
        if raw_boundary and raw_boundary.strip().lower() not in approved_boundaries:
            reasons.append(f"source runtime event used unapproved execution_boundary '{raw_boundary}'")
        query_count_delta = _as_int(row.get("query_count_delta"))
        session_open_count_delta = _as_int(row.get("session_open_count_delta"))
        direct_sql_count_delta = _as_int(row.get("direct_sql_count_delta"))
        account_usage_count_delta = _as_int(row.get("account_usage_count_delta"))
        metadata_probe_count_delta = _as_int(row.get("metadata_probe_count_delta"))
        max_rows_value = row.get("max_rows")
        before_first_paint = bool(row.get("before_first_paint") or row.get("first_paint_sensitive"))
        user_initiated = bool(row.get("user_initiated")) or event_type in {"action", "route_action", "evidence_action"}
        account_usage_marker_present = bool(row.get("account_usage_marker_present")) or account_usage_count_delta > 0
        marker_text = " ".join(
            str(row.get(key) or "")
            for key in ("ttl_key", "event_type", "source_module", "source_query_runner")
        ).lower()
        evidence_loader_marker_present = bool(row.get("evidence_loader_marker_present")) or boundary == "evidence_targeted"
        cost_evidence_marker_present = bool(row.get("cost_evidence_marker_present")) or (
            boundary == "evidence_targeted" and "cost" in marker_text
        )
        query_search_broad_marker_present = (
            bool(row.get("query_search_broad_marker_present"))
            or boundary == "query_search_broad_explicit"
            or "deep_history" in str(row.get("ttl_key") or "").lower()
        )
        setup_live_validation_marker_present = (
            bool(row.get("setup_live_validation_marker_present"))
            or boundary in {"admin_setup_health", "setup_admin", "live_validation", "explicit_connection_test"}
            or event_type in {"session_open", "role_capture", "explicit_admin_connection_test"}
        )
        route_action_marker_present = bool(row.get("route_action_marker_present")) or event_type == "route_action"
        source_object_marker_present = bool(row.get("source_object_marker_present"))
        summary_autoload_marker_present = event_type == "section_summary_autoload" or boundary == "section_summary_autoload"
        if summary_autoload_marker_present:
            summary_autoload_count += 1
        if before_first_paint and evidence_loader_marker_present:
            reasons.append("source runtime event loaded evidence before first paint completed")
        if before_first_paint and account_usage_marker_present:
            reasons.append("source runtime event crossed Account Usage before first paint completed")
        if before_first_paint and cost_evidence_marker_present:
            reasons.append("source runtime event loaded Cost evidence before explicit click")
        if route_action_marker_present and (query_count_delta or session_open_count_delta or direct_sql_count_delta or account_usage_count_delta):
            reasons.append("source runtime route action crossed query/session/direct-SQL boundary")
        if query_search_broad_marker_present and not user_initiated:
            reasons.append("source runtime Query Search broad path ran without explicit click")
        if summary_autoload_marker_present:
            max_rows = _as_int(max_rows_value)
            ttl_key = str(row.get("ttl_key") or "").lower()
            tier = str(row.get("query_tier") or "").lower()
            if before_first_paint:
                reasons.append("source runtime summary autoload ran before first paint completed")
            if not user_initiated:
                reasons.append("source runtime summary autoload missing user-initiated navigation context")
            if account_usage_marker_present or account_usage_count_delta:
                reasons.append("source runtime summary autoload crossed Account Usage")
            if evidence_loader_marker_present or cost_evidence_marker_present:
                reasons.append("source runtime summary autoload loaded deep evidence")
            if setup_live_validation_marker_present:
                reasons.append("source runtime summary autoload crossed setup/live validation")
            if source_object_marker_present:
                reasons.append("source runtime summary autoload leaked a source-object marker")
            if query_count_delta and max_rows_value is None:
                reasons.append("source runtime summary autoload missing max_rows")
            elif max_rows > 200:
                reasons.append(f"source runtime summary autoload max_rows={max_rows}")
            if not (
                "packet" in ttl_key
                or "summary" in ttl_key
                or "brief" in ttl_key
                or tier in {"command_summary", "section_summary", "standard"}
            ):
                reasons.append("source runtime summary autoload is not packet-backed or summary-mart-backed")
        events.append(
            _event_row(
                row_id=f"source_runtime_event::{_identity(row, index)}",
                commit_sha=commit_sha,
                event_type=event_type,
                section=str(row.get("section") or row.get("source_render_section") or ""),
                workflow=str(row.get("workflow") or row.get("source_render_workflow") or ""),
                action_id=str(row.get("action_id") or ""),
                query_boundary=boundary,
                before_first_paint=before_first_paint,
                after_first_paint=bool(row.get("after_first_paint")),
                user_initiated=user_initiated,
                source_module=str(row.get("source_module") or row.get("producer") or ""),
                query_count_delta=query_count_delta,
                max_rows=None if max_rows_value is None else _as_int(max_rows_value),
                session_open_count_delta=session_open_count_delta,
                active_session_probe_count_delta=_as_int(
                    row.get("active_session_probe_count_delta")
                    or row.get("metadata_probe_count_delta")
                ),
                direct_sql_count_delta=direct_sql_count_delta,
                account_usage_count_delta=account_usage_count_delta,
                metadata_probe_count_delta=metadata_probe_count_delta,
                account_usage_marker_present=account_usage_marker_present,
                evidence_loader_marker_present=evidence_loader_marker_present,
                cost_evidence_marker_present=cost_evidence_marker_present,
                query_search_broad_marker_present=query_search_broad_marker_present,
                setup_live_validation_marker_present=setup_live_validation_marker_present,
                route_action_marker_present=route_action_marker_present,
                target_pushdown_violation=bool(row.get("target_pushdown_violation")),
                broad_load_before_filter=bool(row.get("broad_load_before_filter")),
                passed=not reasons,
                failure_reason="; ".join(reasons),
            )
        )
    if summary_autoload_count <= 0:
        events.append(
            _event_row(
                row_id="source_runtime_event_ledger::missing_section_summary_autoload",
                commit_sha=commit_sha,
                event_type="section_summary_autoload",
                query_boundary="section_summary_autoload",
                passed=False,
                failure_reason="missing app-source section_summary_autoload runtime event row",
            )
        )
    return events


def normalize_source_runtime_event_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    commit_sha: str,
    root: Path | str = ".",
) -> list[dict[str, Any]]:
    """Return producer-ready source runtime event rows with release fields."""
    root_path = Path(root).resolve()
    _approved, normalize_boundary = _runtime_boundary_helpers(root_path)
    normalized_rows: list[dict[str, Any]] = []
    for index, source_row in enumerate(rows):
        row = dict(source_row)
        raw_boundary = str(row.get("execution_boundary") or row.get("query_boundary") or row.get("boundary") or "")
        boundary = str(normalize_boundary(raw_boundary))
        event_id = str(row.get("event_id") or f"source-runtime-{index}")
        row_commit = str(row.get("commit_sha") or commit_sha)
        section = str(row.get("source_render_section") or row.get("section") or "")
        workflow = str(row.get("source_render_workflow") or row.get("workflow") or "")
        query_count_delta = _as_int(row.get("query_count_delta"))
        session_open_count_delta = _as_int(row.get("session_open_count_delta"))
        active_session_probe_count_delta = _as_int(
            row.get("active_session_probe_count_delta")
            or row.get("metadata_probe_count_delta")
        )
        direct_sql_count_delta = _as_int(row.get("direct_sql_count_delta"))
        account_usage_count_delta = _as_int(row.get("account_usage_count_delta"))
        metadata_probe_count_delta = _as_int(row.get("metadata_probe_count_delta"))
        event_type = str(row.get("event_type") or "source_runtime_event")
        marker_text = " ".join(
            str(row.get(key) or "")
            for key in ("ttl_key", "event_type", "source_module", "source_query_runner")
        ).lower()
        before_first_paint = bool(row.get("before_first_paint") or row.get("first_paint_sensitive"))
        normalized_rows.append(
            {
                "event_id": event_id,
                "row_id": f"source_runtime_event::{event_id}",
                "event_type": event_type,
                "route": str(row.get("route") or section),
                "section": section,
                "workflow": workflow,
                "app_source_section": str(row.get("section") or ""),
                "app_source_workflow": str(row.get("workflow") or ""),
                "action_id": str(row.get("action_id") or ""),
                "stable_key": str(row.get("stable_key") or row.get("action_id") or ""),
                "rendered_action_id": str(row.get("rendered_action_id") or ""),
                "clicked_action_id": str(row.get("clicked_action_id") or row.get("rendered_action_id") or ""),
                "source_runtime_action_id_original": str(row.get("source_runtime_action_id_original") or ""),
                "boundary": boundary,
                "product_boundary": boundary,
                "execution_boundary": boundary,
                "query_tier": str(row.get("query_tier") or ""),
                "ttl_key": str(row.get("ttl_key") or "")[:160],
                "cache_hit": row.get("cache_hit"),
                "elapsed_ms": round(float(row.get("elapsed_ms") or 0), 2),
                "row_count": _as_int(row.get("row_count")),
                "max_rows": row.get("max_rows") if isinstance(row.get("max_rows"), int) else None,
                "error": str(row.get("error") or "")[:300],
                "source_module": str(row.get("source_module") or row.get("producer") or "runtime_state"),
                "before_first_paint": before_first_paint,
                "after_first_paint": bool(row.get("after_first_paint")) or not before_first_paint,
                "user_initiated": bool(row.get("user_initiated"))
                or event_type in {"action", "route_action", "evidence_action"},
                "query_count_delta": query_count_delta,
                "session_open_count_delta": session_open_count_delta,
                "active_session_probe_count_delta": active_session_probe_count_delta,
                "direct_sql_count_delta": direct_sql_count_delta,
                "account_usage_count_delta": account_usage_count_delta,
                "metadata_probe_count_delta": metadata_probe_count_delta,
                "account_usage_marker_present": bool(row.get("account_usage_marker_present"))
                or account_usage_count_delta > 0,
                "evidence_loader_marker_present": bool(row.get("evidence_loader_marker_present"))
                or boundary == "evidence_targeted",
                "cost_evidence_marker_present": bool(row.get("cost_evidence_marker_present"))
                or (boundary == "evidence_targeted" and "cost" in marker_text),
                "query_search_broad_marker_present": bool(row.get("query_search_broad_marker_present"))
                or boundary == "query_search_broad_explicit"
                or "deep_history" in marker_text,
                "setup_live_validation_marker_present": bool(row.get("setup_live_validation_marker_present"))
                or boundary in {"admin_setup_health", "setup_admin", "live_validation", "explicit_connection_test"},
                "route_action_marker_present": bool(row.get("route_action_marker_present"))
                or event_type == "route_action",
                "source_object_marker_present": bool(row.get("source_object_marker_present")),
                "target_pushdown_violation": bool(row.get("target_pushdown_violation")),
                "broad_load_before_filter": bool(row.get("broad_load_before_filter")),
                "producer": str(row.get("producer") or "runtime_state"),
                "producer_signature": str(row.get("producer_signature") or _row_signature(f"source::{event_id}", row_commit)),
                "provenance_origin": str(row.get("provenance_origin") or "producer"),
                "commit_sha": row_commit,
                "raw_sql_included": bool(row.get("raw_sql_included")),
            }
        )
    return normalized_rows


def build_source_runtime_event_ledger_payload(
    rows: Iterable[Mapping[str, Any]],
    *,
    commit_sha: str,
    root: Path | str = ".",
    producer: str = "full_app_runtime_validation",
) -> dict[str, Any]:
    normalized_rows = normalize_source_runtime_event_rows(rows, commit_sha=commit_sha, root=root)
    failures = [
        row for row in normalized_rows
        if bool(row.get("raw_sql_included")) or str(row.get("commit_sha") or "") != str(commit_sha or "")
    ]
    first_paint_source_count = sum(1 for row in normalized_rows if bool(row.get("before_first_paint")))
    decision_packet_source_count = sum(1 for row in normalized_rows if row.get("execution_boundary") == "decision_packet")
    section_summary_autoload_source_count = sum(
        1
        for row in normalized_rows
        if row.get("execution_boundary") == "section_summary_autoload"
        or row.get("event_type") == "section_summary_autoload"
    )
    if not normalized_rows:
        failures.append({"failure_reason": "missing app-source runtime event ledger rows"})
    if not first_paint_source_count:
        failures.append({"failure_reason": "missing app-source first-paint runtime event row"})
    if not decision_packet_source_count:
        failures.append({"failure_reason": "missing app-source decision_packet runtime event row"})
    if not section_summary_autoload_source_count:
        failures.append({"failure_reason": "missing app-source section_summary_autoload runtime event row"})
    return {
        "source": "source_runtime_event_ledger_results",
        "proof_source": "runtime_state",
        "runtime_source": "actual_app_runtime_state",
        "producer": producer,
        "producer_signature": _row_signature("source_runtime_event_ledger", commit_sha),
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha,
        "rows": normalized_rows,
        "event_count": len(normalized_rows),
        "first_paint_source_event_count": first_paint_source_count,
        "decision_packet_source_event_count": decision_packet_source_count,
        "section_summary_autoload_source_event_count": section_summary_autoload_source_count,
        "route_action_source_event_count": sum(1 for row in normalized_rows if bool(row.get("route_action_marker_present"))),
        "query_count": sum(_as_int(row.get("query_count_delta")) for row in normalized_rows),
        "session_open_count": sum(_as_int(row.get("session_open_count_delta")) for row in normalized_rows),
        "active_session_probe_count": sum(_as_int(row.get("active_session_probe_count_delta")) for row in normalized_rows),
        "direct_sql_count": sum(_as_int(row.get("direct_sql_count_delta")) for row in normalized_rows),
        "account_usage_count": sum(_as_int(row.get("account_usage_count_delta")) for row in normalized_rows),
        "metadata_probe_count": sum(_as_int(row.get("metadata_probe_count_delta")) for row in normalized_rows),
        "failure_count": len(failures),
        "passed": not failures,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_source_runtime_event_ledger_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    commit_sha = str(payload.get("commit_sha") or "")
    rows = _rows(payload)
    failures = [dict(row) for row in rows if bool(row.get("raw_sql_included"))]
    failures.extend(dict(row) for row in payload.get("failures", []) if isinstance(row, Mapping))
    failures.extend(
        {
            "row_id": str(row.get("row_id") or row.get("event_id") or ""),
            "failure_reason": "source runtime event commit_sha mismatch",
        }
        for row in rows
        if commit_sha and str(row.get("commit_sha") or commit_sha) != commit_sha
    )
    if _as_int(payload.get("event_count")) <= 0:
        failures.append({"failure_reason": "missing app-source runtime event ledger rows"})
    if _as_int(payload.get("first_paint_source_event_count")) <= 0:
        failures.append({"failure_reason": "missing app-source first-paint runtime event row"})
    if _as_int(payload.get("decision_packet_source_event_count")) <= 0:
        failures.append({"failure_reason": "missing app-source decision_packet runtime event row"})
    if _as_int(payload.get("section_summary_autoload_source_event_count")) <= 0:
        failures.append({"failure_reason": "missing app-source section_summary_autoload runtime event row"})
    return {
        "source": "source_runtime_event_ledger_gate_results",
        "gate": "source_runtime_event_ledger",
        "producer": PRODUCER,
        "producer_signature": _row_signature("source_runtime_event_ledger_gate", str(payload.get("commit_sha") or "")),
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha,
        "passed": bool(payload.get("passed")) and not failures,
        "failure_count": len(failures),
        "event_count": _as_int(payload.get("event_count")),
        "first_paint_source_event_count": _as_int(payload.get("first_paint_source_event_count")),
        "decision_packet_source_event_count": _as_int(payload.get("decision_packet_source_event_count")),
        "section_summary_autoload_source_event_count": _as_int(payload.get("section_summary_autoload_source_event_count")),
        "route_action_source_event_count": _as_int(payload.get("route_action_source_event_count")),
        "query_count": _as_int(payload.get("query_count")),
        "session_open_count": _as_int(payload.get("session_open_count")),
        "active_session_probe_count": _as_int(payload.get("active_session_probe_count")),
        "direct_sql_count": _as_int(payload.get("direct_sql_count")),
        "account_usage_count": _as_int(payload.get("account_usage_count")),
        "metadata_probe_count": _as_int(payload.get("metadata_probe_count")),
        "rows": [dict(row) for row in rows],
        "proof_rows": [dict(row) for row in rows],
        "failures": failures,
        "raw_sql_included": False,
    }


def build_runtime_event_ledger_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = _git_commit(root_path)
    events = [
        *_first_paint_events(root_path, commit_sha),
        *_route_action_events(root_path, commit_sha),
        *_query_search_events(root_path, commit_sha),
        *_cost_events(root_path, commit_sha),
        *_access_events(root_path, commit_sha),
        *_source_runtime_events(root_path, commit_sha),
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
        "source_runtime_event_count": sum(
            1 for row in events
            if str(row.get("row_id") or "").startswith("source_runtime_event::")
            and str(row.get("row_id") or "") != "source_runtime_event_ledger::missing"
        ),
        "admin_connection_test_count": sum(
            1 for row in events
            if row.get("setup_live_validation_marker_present")
            and row.get("event_type") in {"session_open", "role_capture", "explicit_admin_connection_test"}
        ),
        "explicit_connection_test_count": sum(
            1 for row in events
            if row.get("setup_live_validation_marker_present")
            and row.get("event_type") in {"session_open", "explicit_admin_connection_test"}
        ),
        "query_count_before_first_paint": sum(
            _as_int(row.get("query_count_delta"))
            for row in events
            if row.get("before_first_paint")
        ),
        "decision_packet_query_count": len([row for row in events if row.get("query_boundary") == "decision_packet"]),
        "section_summary_autoload_query_count": len([row for row in events if row.get("query_boundary") == "section_summary_autoload"]),
        "summary_autoload_violation_count": sum(
            1
            for row in events
            if row.get("query_boundary") == "section_summary_autoload"
            and not bool(row.get("passed"))
        ),
        "evidence_query_count_before_first_paint": sum(1 for row in events if row.get("evidence_loader_marker_present") and row.get("before_first_paint")),
        "account_usage_query_count_before_first_paint": sum(1 for row in events if row.get("account_usage_marker_present") and row.get("before_first_paint")),
        "cost_overview_autoload_violation_count": sum(1 for row in events if row.get("cost_evidence_marker_present") and row.get("event_type") == "cost_overview"),
        "query_search_broad_autorun_count": sum(1 for row in events if row.get("query_search_broad_marker_present")),
        "target_pushdown_violation_count": sum(
            1 for row in events
            if bool(row.get("target_pushdown_violation"))
            or bool(row.get("broad_load_before_filter"))
        ),
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
        "source_runtime_event_count": _as_int(results.get("source_runtime_event_count")),
        "section_summary_autoload_query_count": _as_int(results.get("section_summary_autoload_query_count")),
        "summary_autoload_violation_count": _as_int(results.get("summary_autoload_violation_count")),
        "admin_connection_test_count": _as_int(results.get("admin_connection_test_count")),
        "explicit_connection_test_count": _as_int(results.get("explicit_connection_test_count")),
        "rows": rows,
        "proof_rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_runtime_event_ledger_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_runtime_event_ledger_results(root_path)
    gate = build_runtime_event_ledger_gate(results)
    source_payload = _load_json(root_path, SOURCE_RUNTIME_EVENT_LEDGER_REL)
    if isinstance(source_payload, Mapping):
        source_gate = build_source_runtime_event_ledger_gate(source_payload)
    else:
        source_gate = build_source_runtime_event_ledger_gate(
            build_source_runtime_event_ledger_payload([], commit_sha=_git_commit(root_path), root=root_path)
        )
    _write_json(root_path / RUNTIME_EVENT_LEDGER_RESULTS_REL, results)
    _write_json(root_path / RUNTIME_EVENT_LEDGER_GATE_REL, gate)
    _write_json(root_path / SOURCE_RUNTIME_EVENT_LEDGER_GATE_REL, source_gate)
    return {
        RUNTIME_EVENT_LEDGER_RESULTS_REL: results,
        RUNTIME_EVENT_LEDGER_GATE_REL: gate,
        SOURCE_RUNTIME_EVENT_LEDGER_GATE_REL: source_gate,
    }


def main() -> int:
    artifacts = write_runtime_event_ledger_artifacts(Path.cwd())
    return 0 if bool(artifacts[RUNTIME_EVENT_LEDGER_GATE_REL].get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RUNTIME_EVENT_LEDGER_GATE_REL",
    "RUNTIME_EVENT_LEDGER_RESULTS_REL",
    "SOURCE_RUNTIME_EVENT_LEDGER_GATE_REL",
    "SOURCE_RUNTIME_EVENT_LEDGER_REL",
    "build_source_runtime_event_ledger_gate",
    "build_source_runtime_event_ledger_payload",
    "build_runtime_event_ledger_gate",
    "build_runtime_event_ledger_results",
    "write_runtime_event_ledger_artifacts",
]
