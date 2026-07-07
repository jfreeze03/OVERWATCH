"""Settings and live-feature launch proof.

This contract is a release-facing consumer of runtime action artifacts. It
does not invent Settings or live-feature behavior; it verifies the rows emitted
by the runtime harness are clicked, gated, bounded, and daily-safe.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, cast

from tools.contracts.rendered_ui_leak_scan import FORBIDDEN_TOKENS


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

SETTINGS_LIVE_FEATURE_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/settings_live_feature_results.json"
SETTINGS_LIVE_FEATURE_GATE_REL = f"{LAUNCH_READINESS_DIR}/settings_live_feature_gate_results.json"

REQUIRED_SETTINGS_CONTROLS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("compute_credit_price", ("_credit_price_input", "credit_price"), ("$/credit (compute)", "compute credit")),
    ("ai_credit_price", ("_ai_credit_price_input", "ai_credit_price"), ("$/AI credit (Cortex)", "AI credit")),
    ("storage_cost", ("_storage_cost_input", "storage_cost"), ("$/TB/month (storage)", "storage")),
    ("alert_email_recipients", ("_alert_email_targets_input", "alert_email"), ("Alert email recipients",)),
    ("live_refresh_interval", ("rt_interval", "live_refresh_interval"), ("Live refresh interval",)),
    ("idle_query_pause", ("overwatch_idle_timeout_seconds", "idle_timeout"), ("Idle query pause",)),
    ("open_setup_health", ("settings_open_setup_health",), ("Open Setup Health",)),
)

REQUIRED_LIVE_FEATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("setup_validation", ("decision_setup_health_refresh", "setup validation")),
    ("fast_refresh_validation", ("fast_refresh", "FAST refresh")),
    ("full_dry_run_validation", ("full_refresh_dry_run", "FULL dry-run")),
    ("snowflake_cli_live_validation", ("snowflake_cli_live", "Snowflake CLI")),
    ("query_history_proof", ("query_history", "Query history")),
    ("live_diagnostics", ("advanced_diagnostics", "Live diagnostics")),
    ("account_usage_fallback", ("account_usage_fallback", "Account Usage fallback")),
    ("cost_workbench_live_load", ("cost_workbench", "Cost Workbench")),
    ("query_search_live_search", ("query_search", "Query Search live")),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_int(value: object) -> int:
    try:
        return int(cast(Any, value) or 0)
    except (TypeError, ValueError):
        return 0


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_payloads(root: Path, rels: Iterable[str]) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for rel in rels:
        path = root / rel
        if not path.exists():
            continue
        try:
            payloads[rel] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payloads[rel] = {"passed": False, "failure_reason": "malformed_json"}
    return payloads


def _stable_key(row: Mapping[str, Any]) -> str:
    return str(
        row.get("stable_key")
        or row.get("control_key")
        or row.get("key")
        or row.get("action_key")
        or ""
    ).strip()


def _label(row: Mapping[str, Any]) -> str:
    return str(row.get("label") or row.get("name") or row.get("feature") or _stable_key(row) or "").strip()


def _matches_need(row: Mapping[str, Any], key_needles: tuple[str, ...], label_needles: tuple[str, ...]) -> bool:
    haystack_key = _stable_key(row).lower()
    haystack_label = _label(row).lower()
    return any(needle.lower() in haystack_key for needle in key_needles) or any(
        needle.lower() in haystack_label for needle in label_needles
    )


def _query_count(row: Mapping[str, Any]) -> int:
    return _as_int(row.get("query_count")) + _as_int(row.get("actual_snowflake_executions"))


def _session_count(row: Mapping[str, Any]) -> int:
    return _as_int(row.get("session_open_count")) + _as_int(row.get("observed_session_opens"))


def _direct_sql_count(row: Mapping[str, Any]) -> int:
    return _as_int(row.get("direct_sql_count")) + _as_int(row.get("direct_sql_event_count"))


def _admin_required(row: Mapping[str, Any]) -> bool:
    action_type = str(row.get("action_type") or "")
    section = str(row.get("section") or "")
    key = _stable_key(row)
    return (
        section == "Settings/Admin Setup Health"
        or action_type in {"admin_load", "advanced_load", "setup_health", "account_usage_fallback"}
        or key == "settings_open_setup_health"
        or bool(row.get("requires_admin"))
        or bool(row.get("account_usage_allowed"))
        or bool(row.get("heavy_query_allowed"))
    )


def _text_has_forbidden_token(text: str) -> bool:
    lower = text.lower()
    upper = text.upper()
    for token in FORBIDDEN_TOKENS:
        haystack = upper if token.isupper() or "_" in token else lower
        needle = token if token.isupper() or "_" in token else token.lower()
        if needle in haystack:
            return True
    return False


def _settings_text_rows(payloads: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        _as_mapping(row)
        for row in _as_list(payloads.get("artifacts/full_app_validation/rendered_fragments.json"))
        if str(_as_mapping(row).get("section") or "") in {"Settings", "Settings/Admin Setup Health"}
    ]


def build_settings_live_feature_results(payloads: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    setting_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/settings_action_results.json"))]
    live_rows = [_as_mapping(row) for row in _as_list(payloads.get("artifacts/full_app_validation/live_feature_results.json"))]
    control_rows = [
        _as_mapping(row)
        for row in _as_list(payloads.get("artifacts/full_app_validation/control_inventory.json"))
        if str(_as_mapping(row).get("section") or "") in {"Settings", "Settings/Admin Setup Health"}
    ]
    rendered_settings = _settings_text_rows(payloads)

    for requirement, key_needles, label_needles in REQUIRED_SETTINGS_CONTROLS:
        matches = [row for row in control_rows if _matches_need(row, key_needles, label_needles)]
        control = matches[0] if matches else {}
        stable_key = _stable_key(control)
        passed = bool(control) and bool(stable_key)
        result = {
            "area": "settings_control_inventory",
            "section": str(control.get("section") or "Settings"),
            "workflow": str(control.get("workflow") or "Default"),
            "label": _label(control) or requirement,
            "stable_key": stable_key,
            "control_requirement": requirement,
            "rendered": bool(control),
            "clicked": False,
            "passed": passed,
            "failure_reason": "" if passed else f"required Settings control missing or lacks stable key: {requirement}",
            "raw_sql_included": False,
        }
        rows.append(result)
        if not passed:
            failures.append(result)

    for row in setting_rows:
        stable_key = _stable_key(row)
        clicked_or_skipped = bool(row.get("clicked")) or bool(row.get("owner_skipped")) or bool(row.get("skip_reason"))
        admin_ok = (not _admin_required(row)) or bool(row.get("admin_or_advanced_gated") or row.get("admin_gated"))
        no_runtime_cost = _query_count(row) == 0 and _session_count(row) == 0 and _direct_sql_count(row) == 0
        passed = (
            bool(row.get("passed", True))
            and bool(stable_key)
            and clicked_or_skipped
            and admin_ok
            and no_runtime_cost
            and not bool(row.get("raw_error_visible_daily"))
            and not bool(row.get("raw_sql_included"))
        )
        result = {
            "area": "settings",
            "section": str(row.get("section") or "Settings"),
            "workflow": str(row.get("workflow") or "Default"),
            "label": str(row.get("label") or stable_key),
            "stable_key": stable_key,
            "clicked": bool(row.get("clicked")),
            "owner_skipped": bool(row.get("owner_skipped") or row.get("skip_reason")),
            "admin_gated": admin_ok,
            "query_count": _query_count(row),
            "session_open_count": _session_count(row),
            "direct_sql_count": _direct_sql_count(row),
            "account_usage_count": 1 if bool(row.get("account_usage_used")) else 0,
            "raw_error_visible_daily": bool(row.get("raw_error_visible_daily")),
            "passed": passed,
            "failure_reason": "" if passed else "settings_action_contract_failed",
            "raw_sql_included": False,
        }
        rows.append(result)
        if not passed:
            failures.append(result)

    for row in live_rows:
        stable_key = _stable_key(row)
        passed = (
            bool(row.get("passed", True))
            and bool(stable_key)
            and (bool(row.get("clicked")) or bool(row.get("owner_skipped")) or bool(row.get("skip_reason")))
            and bool(row.get("explicit_click_required"))
            and bool(row.get("admin_or_advanced_gated"))
            and bool(row.get("timeout_or_row_limit"))
            and not bool(row.get("first_paint_invocation"))
            and not bool(row.get("route_invocation"))
            and not bool(row.get("raw_error_visible_daily"))
            and not bool(row.get("raw_sql_included"))
        )
        result = {
            "area": "live_feature",
            "section": str(row.get("section") or "Settings/Admin Setup Health"),
            "workflow": str(row.get("workflow") or row.get("feature") or "Live feature"),
            "label": str(row.get("label") or stable_key),
            "stable_key": stable_key,
            "clicked": bool(row.get("clicked")),
            "explicit_click_required": bool(row.get("explicit_click_required")),
            "admin_gated": bool(row.get("admin_or_advanced_gated")),
            "timeout_or_row_limit": bool(row.get("timeout_or_row_limit")),
            "first_paint_invocation": bool(row.get("first_paint_invocation")),
            "route_invocation": bool(row.get("route_invocation")),
            "query_count": _query_count(row),
            "session_open_count": _session_count(row),
            "direct_sql_count": _direct_sql_count(row),
            "passed": passed,
            "failure_reason": "" if passed else "live_feature_contract_failed",
            "raw_sql_included": False,
        }
        rows.append(result)
        if not passed:
            failures.append(result)

    for requirement, needles in REQUIRED_LIVE_FEATURES:
        matches = [
            row for row in live_rows
            if any(needle.lower() in (_stable_key(row) + " " + _label(row)).lower() for needle in needles)
        ]
        feature = matches[0] if matches else {}
        passed = bool(feature)
        result = {
            "area": "live_feature_inventory",
            "section": str(feature.get("section") or "Settings/Admin Setup Health"),
            "workflow": str(feature.get("workflow") or requirement),
            "label": _label(feature) or requirement,
            "stable_key": _stable_key(feature),
            "feature_requirement": requirement,
            "clicked": bool(feature.get("clicked")),
            "owner_skipped": bool(feature.get("owner_skipped") or feature.get("skip_reason")),
            "passed": passed,
            "failure_reason": "" if passed else f"required live feature inventory row missing: {requirement}",
            "raw_sql_included": False,
        }
        rows.append(result)
        if not passed:
            failures.append(result)

    default_rows = [row for row in rendered_settings if str(row.get("section") or "") == "Settings"]
    setup_health_rows = [
        row for row in rendered_settings
        if str(row.get("section") or "") == "Settings/Admin Setup Health"
        or "setup health" in str(row.get("workflow") or "").lower()
    ]
    for row in default_rows:
        text = str(row.get("text") or row.get("rendered_text") or row.get("html_fragment") or "")
        has_compact_note = "Cost estimates use configured credit rates." in text
        has_technical_leak = _text_has_forbidden_token(text)
        passed = has_compact_note and not has_technical_leak
        result = {
            "area": "settings_render",
            "section": "Settings",
            "workflow": str(row.get("workflow") or "Default"),
            "stable_key": "settings_default_render",
            "clicked": False,
            "compact_cost_note_present": has_compact_note,
            "setup_diagnostics_visible_default": has_technical_leak,
            "passed": passed,
            "failure_reason": "" if passed else "settings_default_render_not_daily_safe",
            "raw_sql_included": False,
        }
        rows.append(result)
        if not passed:
            failures.append(result)
    if not default_rows:
        result = {
            "area": "settings_render",
            "section": "Settings",
            "workflow": "Default",
            "stable_key": "settings_default_render",
            "clicked": False,
            "compact_cost_note_present": False,
            "setup_diagnostics_visible_default": False,
            "passed": False,
            "failure_reason": "settings_default_render_missing",
            "raw_sql_included": False,
        }
        rows.append(result)
        failures.append(result)

    setup_health_reachable = any(_stable_key(row) == "settings_open_setup_health" and bool(row.get("clicked")) for row in setting_rows)
    setup_health_admin_only = bool(setup_health_rows) and all(
        bool(row.get("admin_only")) or str(row.get("section") or "") == "Settings/Admin Setup Health"
        for row in setup_health_rows
    )
    setup_health_passed = setup_health_reachable and setup_health_admin_only
    if not setup_health_rows:
        rows.append(
            {
                "area": "setup_health_render",
                "section": "Settings/Admin Setup Health",
                "workflow": "Setup Health",
                "stable_key": "settings_setup_health_render",
                "clicked": False,
                "admin_gated": False,
                "passed": False,
                "failure_reason": "setup_health_render_missing",
                "raw_sql_included": False,
            }
        )
        failures.append(rows[-1])
    setup_health_result = {
        "area": "setup_health",
        "section": "Settings/Admin Setup Health",
        "workflow": "Setup Health",
        "stable_key": "settings_open_setup_health",
        "clicked": setup_health_reachable,
        "admin_gated": setup_health_admin_only,
        "passed": setup_health_passed,
        "failure_reason": "" if setup_health_passed else "setup_health_not_reachable_or_not_admin_gated",
        "raw_sql_included": False,
    }
    rows.append(setup_health_result)
    if not setup_health_passed:
        failures.append(setup_health_result)

    return {
        "source": "settings_live_feature_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "settings_action_count": len(setting_rows),
        "settings_control_count": len(control_rows),
        "live_feature_count": len(live_rows),
        "settings_failure_count": sum(1 for row in failures if str(row.get("area") or "").startswith("settings")),
        "live_feature_failure_count": sum(1 for row in failures if row.get("area") == "live_feature"),
        "setup_health_admin_gated": setup_health_admin_only,
        "setup_health_reachable": setup_health_reachable,
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_settings_live_feature_gate(payload: object) -> dict[str, Any]:
    results = _as_mapping(payload)
    failures = _as_list(results.get("failures"))
    if not bool(results.get("passed", False)) and not failures:
        failures = [{"code": "SETTINGS_LIVE_FEATURE_GAUNTLET_FAILED"}]
    return {
        "source": "settings_live_feature_gate_results",
        "generated_at": _now(),
        "passed": bool(results.get("passed", False)) and not failures,
        "failure_count": len(failures),
        "settings_failure_count": int(results.get("settings_failure_count") or 0),
        "live_feature_failure_count": int(results.get("live_feature_failure_count") or 0),
        "setup_health_admin_gated": bool(results.get("setup_health_admin_gated")),
        "setup_health_reachable": bool(results.get("setup_health_reachable")),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_settings_live_feature_gauntlet_artifacts(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payloads is None:
        payloads = _load_payloads(
            root_path,
            (
                "artifacts/full_app_validation/settings_action_results.json",
                "artifacts/full_app_validation/live_feature_results.json",
                "artifacts/full_app_validation/control_inventory.json",
                "artifacts/full_app_validation/rendered_fragments.json",
            ),
        )
    results = build_settings_live_feature_results(payloads)
    gate = evaluate_settings_live_feature_gate(results)
    artifacts = {
        SETTINGS_LIVE_FEATURE_RESULTS_REL: results,
        SETTINGS_LIVE_FEATURE_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "SETTINGS_LIVE_FEATURE_GATE_REL",
    "SETTINGS_LIVE_FEATURE_RESULTS_REL",
    "build_settings_live_feature_results",
    "evaluate_settings_live_feature_gate",
    "write_settings_live_feature_gauntlet_artifacts",
]


if __name__ == "__main__":
    write_settings_live_feature_gauntlet_artifacts()
