"""Full app release sweep.

This umbrella gate consumes the runtime/render/click/export/stress artifacts
and converts them into a single launch-blocking release sweep. It deliberately
does not synthesize UI text; every passing surface must be backed by a lower
runtime artifact or a feature-specific launch gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, cast

from tools.contracts.full_app_launch_gauntlet import PRIMARY_SECTIONS
from tools.contracts.rendered_ui_leak_scan import FORBIDDEN_TOKENS


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

FULL_APP_RELEASE_SWEEP_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/full_app_release_sweep_results.json"
FULL_APP_RELEASE_FAILURES_REL = f"{FULL_APP_VALIDATION_DIR}/full_app_release_failures.json"
FULL_APP_RELEASE_SWEEP_GATE_REL = f"{LAUNCH_READINESS_DIR}/full_app_release_sweep_gate_results.json"

PRIMARY_OVERVIEW_ALIASES: Mapping[str, Sequence[str]] = {
    "Executive Landing": ("Executive Overview", "Overview"),
    "DBA Control Room": ("Morning Cockpit", "Overview"),
    "Alert Center": ("Active Alerts", "Overview", "Open"),
    "Cost & Contract": ("Cost Overview", "Overview"),
    "Workload Operations": ("Workload Overview", "Overview"),
    "Security Monitoring": ("Security Overview", "Overview"),
}

REQUIRED_RELEASE_SURFACES: tuple[dict[str, Any], ...] = (
    *(
        {
            "area": "primary_overview",
            "section": section,
            "workflow": "Overview",
            "aliases": aliases,
            "require_command_brief": True,
        }
        for section, aliases in PRIMARY_OVERVIEW_ALIASES.items()
    ),
    {"area": "query_search", "section": "Query Search", "workflow": "No click", "aliases": ("No click",)},
    {"area": "query_search", "section": "Query Search", "workflow": "Explicit search", "aliases": ("Explicit search",)},
    {"area": "advanced_scope", "section": "Advanced Scope", "workflow": "Default", "aliases": ("Default", "Active filters")},
    {"area": "advanced_scope", "section": "Advanced Scope", "workflow": "Active filters", "aliases": ("Active filters",)},
    {"area": "settings", "section": "Settings", "workflow": "Default", "aliases": ("Default",)},
    {"area": "settings_admin", "section": "Settings/Admin Setup Health", "workflow": "Setup Health", "aliases": ("Setup Health",)},
    {"area": "fallback", "section": "Packet Missing", "workflow": "Fallback", "aliases": ("Fallback",)},
    {"area": "fallback", "section": "Packet Closest Fallback", "workflow": "Fallback", "aliases": ("Fallback",)},
    {"area": "fallback", "section": "Snowflake Unavailable", "workflow": "Fallback", "aliases": ("Fallback",)},
    {"area": "fallback", "section": "Permission Denied", "workflow": "Fallback", "aliases": ("Fallback",)},
    {"area": "targeted_evidence", "section": "Targeted Evidence", "workflow": "Route action", "aliases": ("Route action",)},
    {"area": "targeted_evidence", "section": "Targeted Evidence", "workflow": "Evidence action", "aliases": ("Evidence action",)},
    {"area": "cost_workbench", "section": "Cost Workbench", "workflow": "Explicit action", "aliases": ("Explicit action",)},
    {"area": "cortex_efficiency", "section": "Cortex Efficiency", "workflow": "Explicit action", "feature_gate": "cortex_token_efficiency_gate_results"},
    {"area": "security_credential", "section": "Security Credential Evidence", "workflow": "Explicit action", "feature_gate": "security_credential_evidence_gate_results"},
)

RAW_SOURCE_TOKENS = tuple(
    token
    for token in FORBIDDEN_TOKENS
    if token not in {"SELECT", "WITH", "JOIN", "CALL"}
    if token.isupper()
    or "_" in token
    or token
    in {
        "raw SQL",
        "procedure name",
        "stack trace",
        "no Snowflake connection",
        "No Snowflake connection",
        "RoleGate",
        "Lock button",
    }
)
INTERNAL_WORDING_TOKENS = (
    "fixture",
    "mock",
    "proof",
    "internal test",
    "test mode",
    "synthetic",
    "deterministic",
    "no Snowflake connection",
    "demo role",
    "RoleGate",
    "Lock button",
)
DIAGNOSTIC_TOKENS = (
    "diagnostic card",
    "setup validation row",
    "Traceback",
    "StreamlitAPIException",
    "SnowflakeSQLException",
    "stack trace",
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


def _as_float(value: object) -> float:
    try:
        return float(cast(Any, value) or 0)
    except (TypeError, ValueError):
        return 0.0


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_payloads(root: Path, rels: Iterable[str]) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for rel in sorted(set(rels)):
        path = root / rel
        if not path.exists():
            continue
        try:
            payloads[rel] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payloads[rel] = {"passed": False, "failure_reason": "malformed_json"}
    return payloads


def _text_from(row: Mapping[str, Any]) -> str:
    return "\n".join(
        str(row.get(key) or "")
        for key in (
            "html_fragment",
            "rendered_text",
            "first_viewport_text",
            "text",
            "fragment",
            "headline",
            "summary",
            "fallback_text",
        )
    )[:20000]


def _markup_from(row: Mapping[str, Any]) -> str:
    return str(row.get("html_fragment") or row.get("text") or row.get("rendered_text") or "")


def _token_count(text: str, tokens: Sequence[str]) -> int:
    lower = text.lower()
    upper = text.upper()
    count = 0
    for token in tokens:
        haystack = upper if token.isupper() or "_" in token else lower
        needle = token if token.isupper() or "_" in token else token.lower()
        if needle in haystack:
            count += 1
    return count


def _is_admin_allowed(section: str, workflow: str, row: Mapping[str, Any]) -> bool:
    return (
        bool(row.get("admin_only"))
        or section == "Settings/Admin Setup Health"
        or "setup health" in workflow.lower()
    )


def _render_sources(payloads: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    sources: list[tuple[str, Mapping[str, Any]]] = []
    for rel in (
        "artifacts/full_app_validation/view_results.json",
        "artifacts/full_app_validation/rendered_fragments.json",
    ):
        for row in _as_list(payloads.get(rel)):
            mapping = _as_mapping(row)
            if mapping:
                sources.append((rel, mapping))
    for row in _as_list(payloads.get("artifacts/full_app_validation/query_search_results.json")):
        mapping = _as_mapping(row)
        case = str(mapping.get("case") or "")
        if case == "render_no_click":
            mapping = {**mapping, "section": "Query Search", "workflow": "No click"}
        elif case in {"exact_query_id", "query_signature", "text_contains_explicit_search"}:
            mapping = {**mapping, "section": "Query Search", "workflow": "Explicit search"}
        else:
            continue
        sources.append(("artifacts/full_app_validation/query_search_results.json", mapping))
    return sources


def _find_render_row(
    payloads: Mapping[str, Any],
    section: str,
    aliases: Sequence[str],
) -> tuple[str, Mapping[str, Any]]:
    for rel, row in _render_sources(payloads):
        if str(row.get("section") or "") != section:
            continue
        workflow = str(row.get("workflow") or "")
        if not aliases or workflow in aliases:
            return rel, row
    return "", {}


def _first_paint_row(payloads: Mapping[str, Any], section: str, aliases: Sequence[str]) -> Mapping[str, Any]:
    perf = _as_mapping(payloads.get("artifacts/full_app_validation/first_paint_performance_results.json"))
    for row in _as_list(perf.get("rows")):
        mapping = _as_mapping(row)
        if str(mapping.get("section") or "") != section:
            continue
        if str(mapping.get("workflow") or "") in aliases or section not in PRIMARY_SECTIONS:
            return mapping
    for row in _as_list(perf.get("rows")):
        mapping = _as_mapping(row)
        if str(mapping.get("section") or "") == section:
            return mapping
    return {}


def _gate(payloads: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _as_mapping(payloads.get(f"artifacts/launch_readiness/{key}.json")) or _as_mapping(
        payloads.get(key)
    )


def _action_failure_count(payloads: Mapping[str, Any]) -> int:
    gate = _gate(payloads, "action_click_gate_results")
    results = _as_mapping(payloads.get("artifacts/full_app_validation/action_click_results.json"))
    return _as_int(gate.get("failure_count")) or _as_int(results.get("failure_count"))


def _export_failure_count(payloads: Mapping[str, Any]) -> int:
    gate = _gate(payloads, "export_download_gate_results")
    return _as_int(gate.get("failure_count"))


def _global_gate_failed(payloads: Mapping[str, Any], key: str) -> bool:
    gate = _gate(payloads, key)
    return bool(gate) and not bool(gate.get("passed", False))


def _surface_row(surface: Mapping[str, Any], payloads: Mapping[str, Any]) -> dict[str, Any]:
    section = str(surface["section"])
    workflow = str(surface["workflow"])
    aliases = tuple(str(item) for item in surface.get("aliases") or (workflow,))
    feature_gate_key = str(surface.get("feature_gate") or "")
    source_artifact = ""
    render_row: Mapping[str, Any] = {}
    rendered = False

    if feature_gate_key:
        feature_gate = _gate(payloads, feature_gate_key)
        source_artifact = f"artifacts/launch_readiness/{feature_gate_key}.json"
        rendered = bool(feature_gate.get("passed"))
        render_row = feature_gate
    else:
        source_artifact, render_row = _find_render_row(payloads, section, aliases)
        rendered = bool(render_row.get("rendered", True)) if render_row else False

    text = _text_from(render_row)
    admin_allowed = _is_admin_allowed(section, workflow, render_row)
    diagnostic_leak_count = 0 if admin_allowed else _token_count(text, DIAGNOSTIC_TOKENS)
    internal_wording_leak_count = 0 if admin_allowed else _token_count(text, INTERNAL_WORDING_TOKENS)
    raw_source_leak_count = 0 if admin_allowed else _token_count(text, RAW_SOURCE_TOKENS)
    old_board_marker_count = _as_int(render_row.get("old_board_marker_count"))
    if text:
        old_board_marker_count += sum(
            text.lower().count(marker)
            for marker in ("card wall", "launchpad", "watch floor", "command deck", "lane board")
        )
    diagnostic_card_count = _as_int(render_row.get("diagnostic_card_count")) + diagnostic_leak_count
    synthetic = str(render_row.get("proof_source") or render_row.get("source") or "").lower() in {
        "synthetic_safe_fallback",
        "manual_safe_text",
    }
    fp = _first_paint_row(payloads, section, aliases)
    first_paint_query_count = _as_int(
        fp.get("cold_first_paint_packet_query_count")
        or fp.get("packet_query_count")
        or _as_mapping(render_row.get("first_paint")).get("observed_packet_queries")
    )
    warm_query_count = _as_int(fp.get("warm_first_paint_query_count") or _as_mapping(render_row.get("first_paint")).get("warm_packet_queries"))
    evidence_query_count = _as_int(fp.get("evidence_query_count"))
    account_usage_count = _as_int(fp.get("account_usage_count"))
    direct_sql_count = _as_int(fp.get("direct_sql_count"))
    session_open_count = _as_int(fp.get("session_open_count"))
    elapsed_ms = _as_float(fp.get("elapsed_ms") or render_row.get("elapsed_ms"))
    markup = _markup_from(render_row)
    command_brief_count = _as_int(render_row.get("summary_board_count")) or markup.count("ow-kit-command-brief")
    marker_count = markup.count("ow-decision-workspace-marker")
    require_command_brief = bool(surface.get("require_command_brief"))

    action_failure_count = _action_failure_count(payloads) if surface["area"] in {"targeted_evidence", "cost_workbench", "settings", "settings_admin"} else 0
    export_failure_count = _export_failure_count(payloads) if surface["area"] in {"security_credential", "cortex_efficiency"} else 0
    clicked = surface["area"] not in {"primary_overview", "fallback", "advanced_scope"} and (
        not feature_gate_key or bool(_gate(payloads, feature_gate_key).get("passed"))
    )
    exported = surface["area"] in {"security_credential", "cortex_efficiency"} and export_failure_count == 0

    reasons: list[str] = []
    if not source_artifact or not render_row:
        reasons.append("required surface missing")
    if not rendered:
        reasons.append("rendered proof missing")
    if synthetic:
        reasons.append("synthetic fallback cannot pass release sweep")
    if require_command_brief and command_brief_count != 1:
        reasons.append("primary overview must render exactly one CommandBrief")
    if require_command_brief and marker_count != 1:
        reasons.append("primary overview must render exactly one Decision Workspace marker")
    if old_board_marker_count:
        reasons.append("old board marker appears")
    if diagnostic_card_count:
        reasons.append("diagnostic/internal card leak appears")
    if internal_wording_leak_count:
        reasons.append("internal wording leak appears")
    if raw_source_leak_count:
        reasons.append("raw source token leak appears")
    if section in PRIMARY_SECTIONS:
        if first_paint_query_count > 1:
            reasons.append("cold first paint exceeded one packet query")
        if warm_query_count:
            reasons.append("warm first paint ran queries")
        if evidence_query_count or account_usage_count or direct_sql_count:
            reasons.append("first paint crossed evidence/Account Usage/direct SQL boundary")
    if action_failure_count:
        reasons.append("visible action/click proof failed")
    if export_failure_count:
        reasons.append("export/download/case proof failed")

    return {
        "area": str(surface["area"]),
        "section": section,
        "workflow": workflow,
        "source_artifact": source_artifact,
        "rendered": rendered,
        "clicked": clicked,
        "exported": exported,
        "first_paint_query_count": first_paint_query_count,
        "warm_query_count": warm_query_count,
        "evidence_query_count": evidence_query_count,
        "account_usage_count": account_usage_count,
        "direct_sql_count": direct_sql_count,
        "session_open_count": session_open_count,
        "elapsed_ms": elapsed_ms,
        "diagnostic_leak_count": diagnostic_card_count,
        "internal_wording_leak_count": internal_wording_leak_count,
        "raw_source_leak_count": raw_source_leak_count,
        "old_board_marker_count": old_board_marker_count,
        "command_brief_count": command_brief_count,
        "decision_workspace_marker_count": marker_count,
        "action_failure_count": action_failure_count,
        "export_failure_count": export_failure_count,
        "passed": not reasons,
        "failure_reason": "; ".join(dict.fromkeys(reasons)),
        "raw_sql_included": False,
    }


def build_full_app_release_sweep(payloads: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = [_surface_row(surface, payloads) for surface in REQUIRED_RELEASE_SURFACES]
    gate_checks = (
        ("rendered_ui_leak_scan", "rendered_ui_leak_gate_results"),
        ("action_click_gauntlet", "action_click_gate_results"),
        ("export_download_gauntlet", "export_download_gate_results"),
        ("settings_live_feature_gauntlet", "settings_live_feature_gate_results"),
        ("performance_budget_gate", "performance_budget_gate_results"),
        ("user_stress_test", "user_stress_gate_results"),
        ("sql_cleanup_gate", "sql_cleanup_gate_results"),
        ("delete_first_cleanup_gate", "delete_first_cleanup_gate_results"),
        ("security_credential_evidence", "security_credential_evidence_gate_results"),
        ("cortex_token_efficiency", "cortex_token_efficiency_gate_results"),
    )
    gate_rows: list[dict[str, Any]] = []
    for area, key in gate_checks:
        gate = _gate(payloads, key)
        if not gate:
            gate_rows.append(
                {
                    "area": area,
                    "section": area,
                    "workflow": "gate",
                    "source_artifact": f"artifacts/launch_readiness/{key}.json",
                    "rendered": False,
                    "clicked": False,
                    "exported": False,
                    "first_paint_query_count": 0,
                    "warm_query_count": 0,
                    "evidence_query_count": 0,
                    "account_usage_count": 0,
                    "direct_sql_count": 0,
                    "session_open_count": 0,
                    "elapsed_ms": 0,
                    "diagnostic_leak_count": 0,
                    "internal_wording_leak_count": 0,
                    "raw_source_leak_count": 0,
                    "old_board_marker_count": 0,
                    "action_failure_count": 0,
                    "export_failure_count": 0,
                    "passed": False,
                    "failure_reason": "required release gate artifact missing",
                    "raw_sql_included": False,
                }
            )
            continue
        gate_rows.append(
            {
                "area": area,
                "section": area,
                "workflow": "gate",
                "source_artifact": f"artifacts/launch_readiness/{key}.json",
                "rendered": True,
                "clicked": True,
                "exported": key == "export_download_gate_results",
                "first_paint_query_count": 0,
                "warm_query_count": 0,
                "evidence_query_count": 0,
                "account_usage_count": 0,
                "direct_sql_count": 0,
                "session_open_count": 0,
                "elapsed_ms": 0,
                "diagnostic_leak_count": _as_int(gate.get("diagnostic_leak_count")),
                "internal_wording_leak_count": _as_int(gate.get("internal_wording_leak_count")),
                "raw_source_leak_count": _as_int(gate.get("raw_sql_leak_count")),
                "old_board_marker_count": _as_int(gate.get("old_board_marker_count")),
                "action_failure_count": _as_int(gate.get("failed_action_count") or gate.get("failure_count"))
                if key == "action_click_gate_results"
                else 0,
                "export_failure_count": _as_int(gate.get("failure_count"))
                if key == "export_download_gate_results"
                else 0,
                "passed": bool(gate.get("passed")),
                "failure_reason": "" if gate.get("passed") else "required release gate failed",
                "raw_sql_included": False,
            }
        )
    rows.extend(gate_rows)

    failures = [row for row in rows if not bool(row.get("passed"))]
    diagnostic_leak_count = sum(_as_int(row.get("diagnostic_leak_count")) for row in rows)
    internal_wording_leak_count = sum(_as_int(row.get("internal_wording_leak_count")) for row in rows)
    raw_source_leak_count = sum(_as_int(row.get("raw_source_leak_count")) for row in rows)
    duplicate_command_brief_count = sum(
        max(0, _as_int(row.get("command_brief_count")) - 1)
        for row in rows
        if row.get("area") == "primary_overview"
    )
    first_paint_failure_count = sum(
        1
        for row in rows
        if row.get("section") in PRIMARY_SECTIONS
        and (
            _as_int(row.get("first_paint_query_count")) > 1
            or _as_int(row.get("warm_query_count"))
            or _as_int(row.get("evidence_query_count"))
            or _as_int(row.get("account_usage_count"))
            or _as_int(row.get("direct_sql_count"))
        )
    )
    results = {
        "source": "full_app_release_sweep_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "surface_count": len(rows),
        "required_surface_count": len(REQUIRED_RELEASE_SURFACES),
        "diagnostic_leak_count": diagnostic_leak_count,
        "internal_wording_leak_count": internal_wording_leak_count,
        "raw_source_leak_count": raw_source_leak_count,
        "failed_action_count": sum(_as_int(row.get("action_failure_count")) for row in rows),
        "export_failure_count": sum(_as_int(row.get("export_failure_count")) for row in rows),
        "settings_failure_count": _as_int(_gate(payloads, "settings_live_feature_gate_results").get("settings_failure_count")),
        "live_feature_failure_count": _as_int(_gate(payloads, "settings_live_feature_gate_results").get("live_feature_failure_count")),
        "stress_failure_count": _as_int(_gate(payloads, "user_stress_gate_results").get("failure_count")),
        "sql_cleanup_failure_count": _as_int(_gate(payloads, "sql_cleanup_gate_results").get("failure_count")),
        "first_paint_failure_count": first_paint_failure_count,
        "duplicate_command_brief_count": duplicate_command_brief_count,
        "old_board_marker_count": sum(_as_int(row.get("old_board_marker_count")) for row in rows),
        "credential_tile_rendered": bool(_gate(payloads, "security_credential_render_gate_results").get("passed")),
        "cortex_efficiency_rendered": bool(_gate(payloads, "cortex_token_efficiency_gate_results").get("passed")),
        "user_id_daily_leak_count": _as_int(_gate(payloads, "user_display_surface_gate_results").get("user_id_daily_leak_count")),
        "credential_id_daily_leak_count": _as_int(_gate(payloads, "security_credential_export_gate_results").get("credential_export_leak_count")),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }
    failure_payload = {
        "source": "full_app_release_failures",
        "generated_at": results["generated_at"],
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }
    return results, failure_payload


def evaluate_full_app_release_sweep_gate(payload: object) -> dict[str, Any]:
    results = _as_mapping(payload)
    failures = _as_list(results.get("failures"))
    if not bool(results.get("passed", False)) and not failures:
        failures = [{"code": "FULL_APP_RELEASE_SWEEP_FAILED"}]
    return {
        "source": "full_app_release_sweep_gate_results",
        "generated_at": _now(),
        "passed": bool(results.get("passed", False)) and not failures,
        "failure_count": len(failures),
        "diagnostic_leak_count": _as_int(results.get("diagnostic_leak_count")),
        "internal_wording_leak_count": _as_int(results.get("internal_wording_leak_count")),
        "raw_source_leak_count": _as_int(results.get("raw_source_leak_count")),
        "failed_action_count": _as_int(results.get("failed_action_count")),
        "export_failure_count": _as_int(results.get("export_failure_count")),
        "settings_failure_count": _as_int(results.get("settings_failure_count")),
        "live_feature_failure_count": _as_int(results.get("live_feature_failure_count")),
        "stress_failure_count": _as_int(results.get("stress_failure_count")),
        "sql_cleanup_failure_count": _as_int(results.get("sql_cleanup_failure_count")),
        "first_paint_failure_count": _as_int(results.get("first_paint_failure_count")),
        "duplicate_command_brief_count": _as_int(results.get("duplicate_command_brief_count")),
        "old_board_marker_count": _as_int(results.get("old_board_marker_count")),
        "credential_tile_rendered": bool(results.get("credential_tile_rendered")),
        "cortex_efficiency_rendered": bool(results.get("cortex_efficiency_rendered")),
        "user_id_daily_leak_count": _as_int(results.get("user_id_daily_leak_count")),
        "credential_id_daily_leak_count": _as_int(results.get("credential_id_daily_leak_count")),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_full_app_release_sweep_artifacts(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payloads is None:
        payloads = _load_payloads(
            root_path,
            (
                "artifacts/full_app_validation/view_results.json",
                "artifacts/full_app_validation/rendered_fragments.json",
                "artifacts/full_app_validation/query_search_results.json",
                "artifacts/full_app_validation/first_paint_performance_results.json",
                "artifacts/full_app_validation/action_click_results.json",
                "artifacts/full_app_validation/export_results.json",
                "artifacts/full_app_validation/download_results.json",
                "artifacts/full_app_validation/case_payload_results.json",
                "artifacts/full_app_validation/user_stress_results.json",
                "artifacts/launch_readiness/action_click_gate_results.json",
                "artifacts/launch_readiness/export_download_gate_results.json",
                "artifacts/launch_readiness/settings_live_feature_gate_results.json",
                "artifacts/launch_readiness/performance_budget_gate_results.json",
                "artifacts/launch_readiness/user_stress_gate_results.json",
                "artifacts/launch_readiness/sql_cleanup_gate_results.json",
                "artifacts/launch_readiness/delete_first_cleanup_gate_results.json",
                "artifacts/launch_readiness/rendered_ui_leak_gate_results.json",
                "artifacts/launch_readiness/security_credential_render_gate_results.json",
                "artifacts/launch_readiness/security_credential_evidence_gate_results.json",
                "artifacts/launch_readiness/security_credential_export_gate_results.json",
                "artifacts/launch_readiness/user_display_surface_gate_results.json",
                "artifacts/launch_readiness/cortex_token_efficiency_gate_results.json",
            ),
        )
    results, failures = build_full_app_release_sweep(payloads)
    gate = evaluate_full_app_release_sweep_gate(results)
    artifacts = {
        FULL_APP_RELEASE_SWEEP_RESULTS_REL: results,
        FULL_APP_RELEASE_FAILURES_REL: failures,
        FULL_APP_RELEASE_SWEEP_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "FULL_APP_RELEASE_FAILURES_REL",
    "FULL_APP_RELEASE_SWEEP_GATE_REL",
    "FULL_APP_RELEASE_SWEEP_RESULTS_REL",
    "REQUIRED_RELEASE_SURFACES",
    "build_full_app_release_sweep",
    "evaluate_full_app_release_sweep_gate",
    "write_full_app_release_sweep_artifacts",
]


if __name__ == "__main__":
    write_full_app_release_sweep_artifacts()
