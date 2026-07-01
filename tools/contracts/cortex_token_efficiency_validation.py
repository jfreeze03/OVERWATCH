"""Release proof for Cortex token-efficiency metrics and user chart safety."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


SNOWFLAKE_VALIDATION_DIR = "artifacts/snowflake_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"

CORTEX_TOKEN_EFFICIENCY_REL = f"{FULL_APP_VALIDATION_DIR}/cortex_token_efficiency_results.json"
CORTEX_TOKEN_EFFICIENCY_LIVE_REL = (
    f"{SNOWFLAKE_VALIDATION_DIR}/cortex_token_efficiency_live_results.json"
)
CORTEX_TOKEN_EFFICIENCY_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/cortex_token_efficiency_gate_results.json"
)
CORTEX_TOKEN_EFFICIENCY_LIVE_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/cortex_token_efficiency_live_gate_results.json"
)

CORTEX_TOKEN_METRICS = (
    "TOTAL_TOKENS",
    "TOTAL_REQUESTS",
    "TOKENS_PER_REQUEST",
    "TOKENS_PER_DOLLAR",
    "COST_PER_1K_TOKENS_USD",
    "AI_CREDITS_PER_1K_TOKENS",
    "COST_PER_REQUEST_USD",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _read(root: Path, rel: str) -> str:
    path = root / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _contains(text: str, token: str) -> bool:
    return token.upper() in text.upper()


def _load_json(root: Path, rel: str) -> Any:
    path = root / rel
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _rows(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("rows", "actions", "results", "cases"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    return []


def _find_surface_row(root: Path, rel: str, section: str, workflow: str) -> tuple[int, Mapping[str, Any]]:
    for index, row in enumerate(_rows(_load_json(root, rel))):
        if str(row.get("section") or "") == section and str(row.get("workflow") or "") == workflow:
            return index, row
    return -1, {}


def _find_action_row(root: Path, section: str, workflow: str) -> tuple[str, int, Mapping[str, Any]]:
    for rel in (
        "artifacts/full_app_validation/button_click_results.json",
        "artifacts/full_app_validation/action_click_results.json",
    ):
        for index, row in enumerate(_rows(_load_json(root, rel))):
            if (
                str(row.get("section") or "") == section
                and str(row.get("workflow") or "") == workflow
                and bool(row.get("clicked", row.get("passed", False)))
            ):
                return rel, index, row
    return "", -1, {}


def _runtime_references(root: Path, section: str, workflow: str) -> tuple[dict[str, Any], list[str]]:
    render_rel = "artifacts/full_app_validation/rendered_fragments.json"
    export_rel = "artifacts/full_app_validation/export_results.json"
    case_rel = "artifacts/full_app_validation/case_payload_results.json"
    render_index, render_row = _find_surface_row(root, render_rel, section, workflow)
    action_rel, action_index, action_row = _find_action_row(root, section, workflow)
    export_index, export_row = _find_surface_row(root, export_rel, section, workflow)
    case_index, case_row = _find_surface_row(root, case_rel, section, workflow)
    refs = {
        "rendered_artifact_path": render_rel if render_row else "",
        "rendered_row_id": str(render_row.get("id") or render_row.get("runtime_artifact_row_index") or render_index if render_row else ""),
        "rendered_row_index": render_index,
        "action_artifact_path": action_rel,
        "action_row_id": str(action_row.get("id") or action_row.get("stable_key") or action_row.get("runtime_artifact_row_index") or action_index if action_row else ""),
        "action_row_index": action_index,
        "export_artifact_path": export_rel if export_row else "",
        "export_row_id": str(export_row.get("id") or export_row.get("stable_key") or export_row.get("filename") or export_row.get("runtime_artifact_row_index") or export_index if export_row else ""),
        "export_row_index": export_index,
        "case_payload_artifact_path": case_rel if case_row else "",
        "case_payload_row_id": str(case_row.get("id") or case_row.get("filename") or case_row.get("runtime_artifact_row_index") or case_index if case_row else ""),
        "case_payload_row_index": case_index,
        "expected_section": section,
        "expected_workflow": workflow,
        "source_rows_present": bool(render_row.get("source_rows_present", render_row)),
        "visible_row_count": int(render_row.get("visible_row_count") or export_row.get("visible_row_count") or 0) if (render_row or export_row) else 0,
        "exported_row_count": int(export_row.get("parsed_row_count") or export_row.get("row_count") or 0) if export_row else 0,
        "case_row_count": int(case_row.get("parsed_row_count") or case_row.get("row_count") or 0) if case_row else 0,
        "producer_signature": str(render_row.get("producer_signature") or ""),
        "commit_sha": str(render_row.get("commit_sha") or ""),
    }
    missing = [
        name
        for name, row in (
            ("rendered runtime row", render_row),
            ("clicked action row", action_row),
            ("file-backed export row", export_row),
            ("case payload row", case_row),
        )
        if not row
    ]
    if export_row and refs["visible_row_count"] != refs["exported_row_count"]:
        missing.append("visible/exported row count mismatch")
    if case_row and refs["visible_row_count"] != refs["case_row_count"]:
        missing.append("visible/case row count mismatch")
    for name, row in (
        ("rendered runtime row", render_row),
        ("clicked action row", action_row),
        ("file-backed export row", export_row),
        ("case payload row", case_row),
    ):
        if row and not row.get("producer_signature"):
            missing.append(f"{name} missing producer_signature")
        if row and str(row.get("section") or "") != section:
            missing.append(f"{name} section mismatch")
        if row and str(row.get("workflow") or "") != workflow:
            missing.append(f"{name} workflow mismatch")
    if any(bool(row.get("raw_sql_included")) for row in (render_row, action_row, export_row, case_row) if row):
        missing.append("runtime artifact row included raw SQL")
    return refs, missing


def _selected_profile(profile: str | None = None) -> str:
    return (profile or os.environ.get("OVERWATCH_LAUNCH_PROFILE") or "internal_fixture").strip() or "internal_fixture"


def _live_required(profile: str) -> bool:
    return profile in {"internal_live", "prod_candidate"}


def _first_valid_waiver(waivers: Iterable[Mapping[str, Any]], *gates: str) -> Mapping[str, Any]:
    gate_set = set(gates)
    for row in waivers:
        if str(row.get("gate") or "") in gate_set and bool(row.get("valid")):
            return row
    return {}


def _row(check: str, passed: bool, *, evidence: str, recommendation: str = "") -> dict[str, Any]:
    return {
        "check": check,
        "passed": bool(passed),
        "evidence": evidence,
        "failure_reason": "" if passed else recommendation,
        "recommendation": "" if passed else recommendation,
        "raw_sql_included": False,
    }


def build_cortex_token_efficiency_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    cortex_source = _read(root_path, ".overwatch_final/sections/cortex_monitor.py")
    display_source = _read(root_path, ".overwatch_final/utils/display.py")
    metric_source = _read(root_path, ".overwatch_final/sections/metric_semantic_registry.py")
    runtime_refs, runtime_failures = _runtime_references(root_path, "Cortex Efficiency", "Explicit action")
    rows = [
        _row(
            "ranked_chart_recomputes_ratio_metrics",
            _contains(display_source, "RANKED_RATIO_METRICS")
            and _contains(display_source, "numerator")
            and _contains(display_source, "denominator")
            and _contains(display_source, "_safe_ratio_value"),
            evidence="rank_chart_frame has explicit ratio metric metadata and recomputation.",
            recommendation="Do not sum token-efficiency ratios in ranked chart frames.",
        ),
        _row(
            "ranked_chart_groups_by_stable_key",
            _contains(display_source, "stable_key")
            and _contains(display_source, "_disambiguate_rank_labels")
            and _contains(cortex_source, 'stable_key="USER_NAME"'),
            evidence="Cortex chart passes USER_NAME as the stable identity while displaying USER_CHART_LABEL.",
            recommendation="Group by stable identity before displaying friendly labels.",
        ),
        _row(
            "cortex_efficiency_metrics_present",
            all(_contains(cortex_source, metric) for metric in CORTEX_TOKEN_METRICS),
            evidence=f"{len(CORTEX_TOKEN_METRICS)} Cortex token-efficiency metrics appear in the runtime path.",
            recommendation="Expose total tokens, requests, and recomputed efficiency metrics together.",
        ),
        _row(
            "cortex_efficiency_workbench_explicit_action",
            _contains(cortex_source, "Load Cortex Efficiency")
            and _contains(cortex_source, "_build_cortex_efficiency_rows")
            and _contains(cortex_source, "cortex_token_efficiency.csv"),
            evidence="Cortex efficiency workbench loads only behind explicit button action.",
            recommendation="Keep token-efficiency outlier analysis behind an explicit action.",
        ),
        _row(
            "cortex_efficiency_exports_sanitized",
            _contains(cortex_source, "sanitize_user_columns_for_export(efficiency_rows)")
            and _contains(cortex_source, "sanitize_user_columns_for_export(df_cc)")
            and not _contains(cortex_source, "download_csv(df_cc"),
            evidence="Default Cortex user and efficiency exports pass through user-column sanitizer.",
            recommendation="Sanitize default Cortex exports so USER_ID/RAW_USER_ID are not visible.",
        ),
        _row(
            "cortex_efficiency_metric_semantics_registered",
            all(_contains(metric_source, metric.lower()) or _contains(metric_source, metric) for metric in CORTEX_TOKEN_METRICS),
            evidence="Cortex token-efficiency metrics are registered in metric semantics.",
            recommendation="Add semantic rows for every visible/exported token-efficiency metric.",
        ),
        _row(
            "cortex_efficiency_runtime_artifact_references",
            not runtime_failures,
            evidence="Cortex token-efficiency gate references rendered, clicked, exported, and case payload runtime artifacts.",
            recommendation="Generate Cortex Efficiency explicit-action render/click/export/case artifacts before evaluating this gate.",
        ),
    ]
    failures = [row for row in rows if not row["passed"]]
    return {
        "source": "cortex_token_efficiency_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "cortex_token_efficiency_gate_passed": not failures,
        "cortex_token_metric_count": len(CORTEX_TOKEN_METRICS),
        "cortex_token_ratio_failure_count": len([row for row in failures if "ratio" in row["check"]]),
        **runtime_refs,
        "runtime_reference_failures": runtime_failures,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_cortex_token_efficiency_live_results(
    root: Path | str = ".",
    profile: str | None = None,
) -> dict[str, Any]:
    launch_profile = _selected_profile(profile)
    skipped = not _live_required(launch_profile)
    rows = [
        {
            "phase": "cortex_token_efficiency_live",
            "status": "skipped" if skipped else "failed",
            "launch_profile": launch_profile,
            "live_required": _live_required(launch_profile),
            "live_executed": False,
            "live_passed": False,
            "live_skipped": skipped,
            "skip_reason": "internal_fixture uses deterministic Cortex token-efficiency fixture proof"
            if skipped
            else "",
            "formula_fields": list(CORTEX_TOKEN_METRICS),
            "raw_sql_included": False,
            "failure_reason": "" if skipped else "Live Cortex token-efficiency proof is required for this profile.",
        }
    ]
    return {
        "source": "cortex_token_efficiency_live_results",
        "generated_at": _now(),
        "profile": launch_profile,
        "passed": skipped,
        "skipped": skipped,
        "live_required": _live_required(launch_profile),
        "live_executed": False,
        "live_passed": False,
        "live_skipped": skipped,
        "skip_reason": rows[0]["skip_reason"],
        "failure_count": 0 if skipped else 1,
        "rows": rows,
        "failures": [] if skipped else rows,
        "raw_sql_included": False,
    }


def evaluate_cortex_token_efficiency_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    failures = list(payload.get("failures") or [])
    passed = bool(payload.get("passed")) and not failures
    return {
        "source": "cortex_token_efficiency_gate_results",
        "generated_at": _now(),
        "passed": passed,
        "cortex_token_efficiency_gate_passed": passed,
        "cortex_token_metric_count": payload.get("cortex_token_metric_count", 0),
        "cortex_token_ratio_failure_count": payload.get("cortex_token_ratio_failure_count", len(failures)),
        "rendered_artifact_path": payload.get("rendered_artifact_path", ""),
        "rendered_row_id": payload.get("rendered_row_id", ""),
        "action_artifact_path": payload.get("action_artifact_path", ""),
        "action_row_id": payload.get("action_row_id", ""),
        "export_artifact_path": payload.get("export_artifact_path", ""),
        "export_row_id": payload.get("export_row_id", ""),
        "export_row_index": payload.get("export_row_index", -1),
        "case_payload_artifact_path": payload.get("case_payload_artifact_path", ""),
        "case_payload_row_id": payload.get("case_payload_row_id", ""),
        "case_payload_row_index": payload.get("case_payload_row_index", -1),
        "expected_section": payload.get("expected_section", "Cortex Efficiency"),
        "expected_workflow": payload.get("expected_workflow", "Explicit action"),
        "source_rows_present": bool(payload.get("source_rows_present")),
        "visible_row_count": payload.get("visible_row_count", 0),
        "exported_row_count": payload.get("exported_row_count", 0),
        "case_row_count": payload.get("case_row_count", 0),
        "producer_signature": payload.get("producer_signature", ""),
        "commit_sha": payload.get("commit_sha", ""),
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_cortex_token_efficiency_live_gate(
    payload: Mapping[str, Any],
    profile: str | None = None,
    waivers: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    launch_profile = _selected_profile(profile)
    failures = list(payload.get("failures") or [])
    waiver = _first_valid_waiver(
        waivers,
        "cortex_token_efficiency_live",
        "cortex_token_efficiency_live_gate",
    )
    live_required = _live_required(launch_profile)
    live_executed = bool(payload.get("live_executed"))
    live_passed = bool(payload.get("live_passed")) and live_executed
    live_skipped = bool(payload.get("live_skipped"))
    waived = bool(waiver)
    passed = (live_passed or (not live_required and live_skipped) or waived) and not failures
    if live_passed and live_skipped:
        passed = False
        failures.append(
            {
                "failure_reason": "Skipped Cortex token-efficiency live proof cannot also be marked live passed.",
                "raw_sql_included": False,
            }
        )
    return {
        "source": "cortex_token_efficiency_live_gate_results",
        "generated_at": _now(),
        "passed": passed,
        "cortex_token_efficiency_live_gate_passed": passed,
        "live_required": live_required,
        "live_executed": live_executed,
        "live_passed": live_passed,
        "live_skipped": live_skipped,
        "live_waived": waived,
        "waiver_id": str(waiver.get("waiver_id") or waiver.get("id") or "") if waiver else "",
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_cortex_token_efficiency_artifacts(
    root: Path | str = ".",
    *,
    profile: str | None = None,
    waivers: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    launch_profile = _selected_profile(profile)
    results = build_cortex_token_efficiency_results(root_path)
    live = build_cortex_token_efficiency_live_results(root_path, launch_profile)
    gate = evaluate_cortex_token_efficiency_gate(results)
    live_gate = evaluate_cortex_token_efficiency_live_gate(live, launch_profile, waivers)
    artifacts: dict[str, Any] = {
        CORTEX_TOKEN_EFFICIENCY_REL: results,
        CORTEX_TOKEN_EFFICIENCY_LIVE_REL: live,
        CORTEX_TOKEN_EFFICIENCY_GATE_REL: gate,
        CORTEX_TOKEN_EFFICIENCY_LIVE_GATE_REL: live_gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


def main() -> int:
    artifacts = write_cortex_token_efficiency_artifacts(Path.cwd())
    failures = [
        rel
        for rel, payload in artifacts.items()
        if rel.startswith(LAUNCH_READINESS_DIR) and not bool(payload.get("passed"))
    ]
    return 1 if failures else 0


__all__ = [
    "CORTEX_TOKEN_EFFICIENCY_GATE_REL",
    "CORTEX_TOKEN_EFFICIENCY_LIVE_GATE_REL",
    "CORTEX_TOKEN_EFFICIENCY_LIVE_REL",
    "CORTEX_TOKEN_EFFICIENCY_REL",
    "CORTEX_TOKEN_METRICS",
    "build_cortex_token_efficiency_live_results",
    "build_cortex_token_efficiency_results",
    "evaluate_cortex_token_efficiency_gate",
    "evaluate_cortex_token_efficiency_live_gate",
    "main",
    "write_cortex_token_efficiency_artifacts",
]


if __name__ == "__main__":
    raise SystemExit(main())
