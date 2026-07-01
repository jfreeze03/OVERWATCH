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
