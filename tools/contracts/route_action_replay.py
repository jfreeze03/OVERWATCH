"""Runtime-artifact route/action replay gate.

This contract replays the release-critical action boundaries from producer
artifacts. It does not synthesize UI success: each scenario must be backed by
rendered/click/query telemetry written by the runtime harness.
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

ROUTE_ACTION_REPLAY_RESULTS_REL = f"{FULL_APP_DIR}/route_action_replay_results.json"
ROUTE_ACTION_REPLAY_GATE_REL = f"{LAUNCH_READINESS_DIR}/route_action_replay_gate_results.json"

FIRST_PAINT_REL = f"{FULL_APP_DIR}/first_paint_performance_results.json"
ACTION_CLICK_REL = f"{FULL_APP_DIR}/action_click_results.json"
QUERY_SEARCH_AUTORUN_REL = f"{FULL_APP_DIR}/query_search_autorun_results.json"
COST_NO_AUTOLOAD_REL = f"{FULL_APP_DIR}/cost_overview_no_autoload_results.json"
SETTINGS_ACTION_REL = f"{FULL_APP_DIR}/settings_action_results.json"

PRODUCER = "route_action_replay"
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
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False, timeout=10)
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
        for key in ("rows", "actions", "results", "checks"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    return []


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value or 0)))
    except (TypeError, ValueError):
        return 0


def _action_id(row: Mapping[str, Any], index: int) -> str:
    for key in ("rendered_action_id", "clicked_action_id", "stable_key", "action_key", "id"):
        value = str(row.get(key) or "")
        if value:
            return value
    return f"action[{index}]"


def _scenario(
    *,
    row_id: str,
    commit_sha: str,
    scenario: str,
    source_artifact: str,
    source_row_id: str = "",
    section: str = "",
    workflow: str = "",
    actions_clicked: int = 0,
    query_count: int = 0,
    session_open_count: int = 0,
    direct_sql_count: int = 0,
    account_usage_count: int = 0,
    explicit_click_required: bool = False,
    passed: bool = True,
    failure_reason: str = "",
) -> dict[str, Any]:
    return {
        "row_id": row_id,
        "scenario": scenario,
        "source_artifact": source_artifact,
        "source_row_id": source_row_id,
        "section": section,
        "workflow": workflow,
        "actions_clicked": actions_clicked,
        "query_count": query_count,
        "session_open_count": session_open_count,
        "direct_sql_count": direct_sql_count,
        "account_usage_count": account_usage_count,
        "explicit_click_required": explicit_click_required,
        "producer": PRODUCER,
        "producer_signature": _row_signature(row_id, commit_sha),
        "provenance_origin": "producer",
        "commit_sha": commit_sha,
        "passed": passed,
        "failure_reason": failure_reason,
        "raw_sql_included": False,
    }


def _first_paint_scenarios(root: Path, commit_sha: str) -> list[dict[str, Any]]:
    rows = _rows(_load_json(root, FIRST_PAINT_REL))
    by_section = {str(row.get("section") or ""): row for row in rows if str(row.get("section") or "") in PRIMARY_SECTIONS}
    scenarios: list[dict[str, Any]] = []
    for section in PRIMARY_SECTIONS:
        row = by_section.get(section)
        row_id = f"first_paint::{section.lower().replace(' ', '_')}"
        if not row:
            scenarios.append(
                _scenario(
                    row_id=row_id,
                    commit_sha=commit_sha,
                    scenario="primary overview first paint",
                    source_artifact=FIRST_PAINT_REL,
                    section=section,
                    passed=False,
                    failure_reason="missing first-paint telemetry row",
                )
            )
            continue
        reasons: list[str] = []
        if str(row.get("commit_sha") or "") != commit_sha:
            reasons.append("commit_sha mismatch")
        if _as_int(row.get("warm_first_paint_query_count")) > 0:
            reasons.append("warm first paint queried")
        if _as_int(row.get("cold_first_paint_packet_query_count")) > 1:
            reasons.append("cold first paint exceeded one packet query")
        for key in ("evidence_query_count", "account_usage_count", "detail_query_count", "cost_workbench_query_count", "query_search_query_count", "direct_sql_count"):
            if _as_int(row.get(key)) > 0:
                reasons.append(f"{key}={_as_int(row.get(key))}")
        scenarios.append(
            _scenario(
                row_id=row_id,
                commit_sha=commit_sha,
                scenario="primary overview first paint",
                source_artifact=FIRST_PAINT_REL,
                source_row_id=str(row.get("row_id") or row.get("id") or section),
                section=section,
                workflow=str(row.get("workflow") or "Overview"),
                query_count=_as_int(row.get("cold_first_paint_packet_query_count")),
                session_open_count=_as_int(row.get("session_open_count")),
                direct_sql_count=_as_int(row.get("direct_sql_count")),
                account_usage_count=_as_int(row.get("account_usage_count")),
                passed=not reasons and bool(row.get("passed", True)),
                failure_reason="; ".join(reasons or [str(row.get("failure_reason") or "")]).strip(),
            )
        )
    return scenarios


def _action_scenarios(root: Path, commit_sha: str) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    rows = _rows(_load_json(root, ACTION_CLICK_REL))
    route_rows = [
        row for row in rows
        if str(row.get("action_area") or row.get("area") or "") == "route_action" and bool(row.get("clicked"))
    ]
    evidence_rows = [
        row for row in rows
        if str(row.get("action_area") or row.get("area") or "") in {"evidence_action", "query_search", "cost_workbench", "live_feature"}
        and bool(row.get("clicked"))
    ]
    if not route_rows:
        scenarios.append(
            _scenario(
                row_id="route_actions::missing",
                commit_sha=commit_sha,
                scenario="daily route navigation actions",
                source_artifact=ACTION_CLICK_REL,
                passed=False,
                failure_reason="missing clicked route-action rows",
            )
        )
    for index, row in enumerate(route_rows):
        reasons: list[str] = []
        if str(row.get("commit_sha") or "") != commit_sha:
            reasons.append("commit_sha mismatch")
        for key in ("query_count", "session_open_count", "direct_sql_count", "account_usage_count"):
            if _as_int(row.get(key)) > 0:
                reasons.append(f"{key}={_as_int(row.get(key))}")
        if not bool(row.get("passed", True)):
            reasons.append(str(row.get("failure_reason") or "source row failed"))
        scenarios.append(
            _scenario(
                row_id=f"route_action::{_action_id(row, index)}",
                commit_sha=commit_sha,
                scenario="daily route navigation actions",
                source_artifact=ACTION_CLICK_REL,
                source_row_id=_action_id(row, index),
                section=str(row.get("section") or ""),
                workflow=str(row.get("workflow") or ""),
                actions_clicked=1,
                query_count=_as_int(row.get("query_count")),
                session_open_count=_as_int(row.get("session_open_count")),
                direct_sql_count=_as_int(row.get("direct_sql_count")),
                account_usage_count=_as_int(row.get("account_usage_count")),
                passed=not reasons,
                failure_reason="; ".join(reasons),
            )
        )
    if not evidence_rows:
        scenarios.append(
            _scenario(
                row_id="explicit_actions::missing",
                commit_sha=commit_sha,
                scenario="explicit evidence/search/workbench actions",
                source_artifact=ACTION_CLICK_REL,
                explicit_click_required=True,
                passed=False,
                failure_reason="missing clicked explicit action rows",
            )
        )
    for index, row in enumerate(evidence_rows):
        reasons: list[str] = []
        if str(row.get("commit_sha") or "") != commit_sha:
            reasons.append("commit_sha mismatch")
        if _as_int(row.get("account_usage_count")) > 0 and str(row.get("action_area")) != "live_feature":
            reasons.append("normal explicit action used Account Usage")
        if not bool(row.get("passed", True)):
            reasons.append(str(row.get("failure_reason") or "source row failed"))
        scenarios.append(
            _scenario(
                row_id=f"explicit_action::{_action_id(row, index)}",
                commit_sha=commit_sha,
                scenario="explicit evidence/search/workbench actions",
                source_artifact=ACTION_CLICK_REL,
                source_row_id=_action_id(row, index),
                section=str(row.get("section") or ""),
                workflow=str(row.get("workflow") or ""),
                actions_clicked=1,
                query_count=_as_int(row.get("query_count")),
                session_open_count=_as_int(row.get("session_open_count")),
                direct_sql_count=_as_int(row.get("direct_sql_count")),
                account_usage_count=_as_int(row.get("account_usage_count")),
                explicit_click_required=True,
                passed=not reasons,
                failure_reason="; ".join(reasons),
            )
        )
    return scenarios


def _query_search_scenarios(root: Path, commit_sha: str) -> list[dict[str, Any]]:
    rows = _rows(_load_json(root, QUERY_SEARCH_AUTORUN_REL))
    scenarios: list[dict[str, Any]] = []
    required = {"render_no_click", "exact_query_id", "warehouse_prefill_no_autorun", "text_contains_no_autorun"}
    seen: set[str] = set()
    for index, row in enumerate(rows):
        case = str(row.get("case") or row.get("id") or f"case-{index}")
        seen.add(case)
        reasons: list[str] = []
        if str(row.get("commit_sha") or "") != commit_sha:
            reasons.append("commit_sha mismatch")
        if _as_int(row.get("query_search_broad_autorun_count")) > 0:
            reasons.append("broad Query Search autoran")
        if not bool(row.get("passed", True)):
            reasons.append(str(row.get("failure_reason") or "source row failed"))
        scenarios.append(
            _scenario(
                row_id=f"query_search::{case}",
                commit_sha=commit_sha,
                scenario="Query Search no-click and explicit-search boundaries",
                source_artifact=QUERY_SEARCH_AUTORUN_REL,
                source_row_id=case,
                section="Query Search",
                workflow=case,
                query_count=_as_int(row.get("query_count")),
                account_usage_count=_as_int(row.get("account_usage_count")),
                passed=not reasons,
                failure_reason="; ".join(reasons),
            )
        )
    for case in sorted(required - seen):
        scenarios.append(
            _scenario(
                row_id=f"query_search::{case}",
                commit_sha=commit_sha,
                scenario="Query Search no-click and explicit-search boundaries",
                source_artifact=QUERY_SEARCH_AUTORUN_REL,
                source_row_id=case,
                section="Query Search",
                workflow=case,
                passed=False,
                failure_reason="missing Query Search replay row",
            )
        )
    return scenarios


def _cost_and_settings_scenarios(root: Path, commit_sha: str) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    cost_rows = _rows(_load_json(root, COST_NO_AUTOLOAD_REL))
    if not cost_rows:
        scenarios.append(
            _scenario(
                row_id="cost_overview::missing_no_autoload",
                commit_sha=commit_sha,
                scenario="Cost Overview before explicit evidence/workbench action",
                source_artifact=COST_NO_AUTOLOAD_REL,
                section="Cost & Contract",
                passed=False,
                failure_reason="missing Cost Overview no-autoload row",
            )
        )
    for index, row in enumerate(cost_rows):
        reasons: list[str] = []
        if str(row.get("commit_sha") or "") != commit_sha:
            reasons.append("commit_sha mismatch")
        for key in ("autoload_violation_count", "evidence_query_count", "cost_workbench_query_count", "detail_query_count", "account_usage_count", "direct_sql_count"):
            if _as_int(row.get(key)) > 0:
                reasons.append(f"{key}={_as_int(row.get(key))}")
        scenarios.append(
            _scenario(
                row_id=f"cost_overview::{index}",
                commit_sha=commit_sha,
                scenario="Cost Overview before explicit evidence/workbench action",
                source_artifact=COST_NO_AUTOLOAD_REL,
                source_row_id=str(row.get("id") or index),
                section="Cost & Contract",
                workflow=str(row.get("workflow") or "Cost Overview"),
                query_count=_as_int(row.get("cold_first_paint_packet_query_count")),
                direct_sql_count=_as_int(row.get("direct_sql_count")),
                account_usage_count=_as_int(row.get("account_usage_count")),
                passed=not reasons and bool(row.get("passed", True)),
                failure_reason="; ".join(reasons or [str(row.get("failure_reason") or "")]).strip(),
            )
        )
    settings_rows = _rows(_load_json(root, SETTINGS_ACTION_REL))
    settings_passed = bool(settings_rows)
    scenarios.append(
        _scenario(
            row_id="settings::default_and_setup_health_inventory",
            commit_sha=commit_sha,
            scenario="Settings default and admin Setup Health action inventory",
            source_artifact=SETTINGS_ACTION_REL,
            section="Settings",
            actions_clicked=sum(1 for row in settings_rows if bool(row.get("clicked"))),
            passed=settings_passed,
            failure_reason="" if settings_passed else "missing Settings action rows",
        )
    )
    return scenarios


def build_route_action_replay_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = _git_commit(root_path)
    rows = [
        *_first_paint_scenarios(root_path, commit_sha),
        *_action_scenarios(root_path, commit_sha),
        *_query_search_scenarios(root_path, commit_sha),
        *_cost_and_settings_scenarios(root_path, commit_sha),
    ]
    failures = [row for row in rows if not bool(row.get("passed"))]
    signature = _producer_signature()
    return {
        "source": "route_action_replay_results",
        "gate": "route_action_replay",
        "producer": PRODUCER,
        "producer_signature": signature,
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha,
        "passed": not failures,
        "failure_count": len(failures),
        "scenario_count": len(rows),
        "route_action_sql_violation_count": sum(
            1 for row in rows
            if row.get("scenario") == "daily route navigation actions"
            and (_as_int(row.get("query_count")) or _as_int(row.get("session_open_count")) or _as_int(row.get("direct_sql_count")) or _as_int(row.get("account_usage_count")))
        ),
        "pre_first_paint_session_open_count": sum(
            _as_int(row.get("session_open_count")) for row in rows if row.get("scenario") == "primary overview first paint"
        ),
        "query_search_broad_autorun_count": sum(1 for row in rows if "broad Query Search" in str(row.get("failure_reason") or "")),
        "cost_overview_autoload_violation_count": sum(1 for row in rows if "autoload" in str(row.get("failure_reason") or "")),
        "rows": rows,
        "proof_rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_route_action_replay_gate(results: Mapping[str, Any]) -> dict[str, Any]:
    rows = [dict(row) for row in _rows(results)]
    failures = [row for row in rows if not bool(row.get("passed"))]
    signature = _producer_signature()
    return {
        "source": "route_action_replay_gate_results",
        "gate": "route_action_replay",
        "producer": PRODUCER,
        "producer_signature": signature,
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": str(results.get("commit_sha") or ""),
        "passed": bool(results.get("passed")) and not failures,
        "failure_count": len(failures),
        "scenario_count": _as_int(results.get("scenario_count")),
        "route_action_sql_violation_count": _as_int(results.get("route_action_sql_violation_count")),
        "query_search_broad_autorun_count": _as_int(results.get("query_search_broad_autorun_count")),
        "cost_overview_autoload_violation_count": _as_int(results.get("cost_overview_autoload_violation_count")),
        "rows": rows,
        "proof_rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_route_action_replay_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_route_action_replay_results(root_path)
    gate = build_route_action_replay_gate(results)
    _write_json(root_path / ROUTE_ACTION_REPLAY_RESULTS_REL, results)
    _write_json(root_path / ROUTE_ACTION_REPLAY_GATE_REL, gate)
    return {
        ROUTE_ACTION_REPLAY_RESULTS_REL: results,
        ROUTE_ACTION_REPLAY_GATE_REL: gate,
    }


def main() -> int:
    artifacts = write_route_action_replay_artifacts(Path.cwd())
    return 0 if bool(artifacts[ROUTE_ACTION_REPLAY_GATE_REL].get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ROUTE_ACTION_REPLAY_GATE_REL",
    "ROUTE_ACTION_REPLAY_RESULTS_REL",
    "build_route_action_replay_gate",
    "build_route_action_replay_results",
    "write_route_action_replay_artifacts",
]
