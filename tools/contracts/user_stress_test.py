"""User stress-test consolidation for launch readiness."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

STRESS_SOURCE_REL = f"{FULL_APP_VALIDATION_DIR}/stress_results.json"
USER_STRESS_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/user_stress_results.json"
USER_STRESS_GATE_REL = f"{LAUNCH_READINESS_DIR}/user_stress_gate_results.json"

REQUIRED_STRESS_SCENARIOS = (
    "rapid_section_switching",
    "repeated_route_clicks",
    "repeated_evidence_loads",
    "repeated_refresh_packet",
    "advanced_scope_filters",
    "empty_evidence_result",
    "large_bounded_evidence_result",
    "snowflake_unavailable",
    "permission_denied",
    "slow_query_timeout",
    "stale_source_data",
    "fixture_data_mode",
    "live_feature_denied",
    "many_row_export",
    "no_row_export",
    "repeated_query_search_interactions",
    "account_usage_confirmation_matrix",
    "cache_expiry_force_refresh",
    "state_bleed_across_sections",
    "duplicate_session_state_collision",
)

OPTIONAL_STRESS_SCENARIOS = (
    "settings_open_close",
    "cost_workbench_load_once",
    "evidence_action_repeated",
    "export_download_repeated",
    "packet_missing",
    "live_feature_timeout",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_json(root: Path, rel: str) -> Any:
    path = root / rel
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"passed": False, "failure_reason": "malformed_json"}


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def build_user_stress_results(payload: object) -> dict[str, Any]:
    source = _as_mapping(payload)
    rows = [_as_mapping(row) for row in _as_list(source.get("rows") or source.get("scenarios") or payload)]
    scenario_names = {
        str(row.get("scenario") or row.get("case") or row.get("workflow") or row.get("name") or "").strip()
        for row in rows
        if str(row.get("scenario") or row.get("case") or row.get("workflow") or row.get("name") or "").strip()
    }
    failures: list[dict[str, Any]] = []
    if source and not bool(source.get("passed", True)):
        failures.append({"code": "SOURCE_STRESS_ARTIFACT_FAILED", "failure_reason": source.get("failure_reason", "")})
    for row in rows:
        if not bool(row.get("passed", True)):
            failures.append(
                {
                    "code": "STRESS_SCENARIO_FAILED",
                    "scenario": row.get("scenario") or row.get("case") or row.get("workflow") or row.get("name"),
                    "failure_reason": row.get("failure_reason", ""),
                }
            )
        for field, code in (
            ("duplicate_summary_board", "DUPLICATE_SUMMARY_BOARD"),
            ("diagnostic_leak", "DIAGNOSTIC_LEAK"),
            ("session_state_mutation_error", "SESSION_STATE_MUTATION"),
            ("raw_stack_trace_visible", "RAW_STACK_TRACE"),
            ("uncontrolled_query_growth", "UNCONTROLLED_QUERY_GROWTH"),
        ):
            if bool(row.get(field)):
                failures.append({"code": code, "scenario": row.get("scenario") or row.get("case") or row.get("workflow")})
    missing = sorted(set(REQUIRED_STRESS_SCENARIOS) - scenario_names)
    if not rows:
        failures.append({"code": "NO_STRESS_ROWS", "failure_reason": "stress_results.json did not contain scenario rows"})
    if missing and rows:
        failures.append({"code": "MISSING_STRESS_SCENARIOS", "missing_scenarios": missing})
    slow_count = sum(1 for row in rows if float(row.get("elapsed_ms") or 0) > float(row.get("elapsed_budget_ms") or 10000))
    if slow_count:
        failures.append({"code": "STRESS_RUNTIME_OVER_BUDGET", "slow_runtime_count": slow_count})
    return {
        "source": "user_stress_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "stress_scenario_count": len(rows),
        "required_scenarios": REQUIRED_STRESS_SCENARIOS,
        "optional_scenarios": OPTIONAL_STRESS_SCENARIOS,
        "missing_scenarios": missing,
        "slow_runtime_count": slow_count,
        "failures": failures,
        "rows": rows,
        "raw_sql_included": False,
    }


def evaluate_user_stress_gate(payload: object) -> dict[str, Any]:
    stress = _as_mapping(payload)
    failures = _as_list(stress.get("failures"))
    if not bool(stress.get("passed", False)) and not failures:
        failures = [{"code": "USER_STRESS_FAILED"}]
    return {
        "source": "user_stress_gate_results",
        "generated_at": _now(),
        "passed": bool(stress.get("passed", False)) and not failures,
        "failure_count": len(failures),
        "slow_runtime_count": int(stress.get("slow_runtime_count") or 0),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_user_stress_artifacts(root: Path | str = ".", payload: object | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payload is None:
        payload = _load_json(root_path, STRESS_SOURCE_REL)
    results = build_user_stress_results(payload)
    _write_json(root_path / USER_STRESS_RESULTS_REL, results)
    return {USER_STRESS_RESULTS_REL: results}


__all__ = [
    "OPTIONAL_STRESS_SCENARIOS",
    "REQUIRED_STRESS_SCENARIOS",
    "USER_STRESS_GATE_REL",
    "USER_STRESS_RESULTS_REL",
    "build_user_stress_results",
    "evaluate_user_stress_gate",
    "write_user_stress_artifacts",
]
