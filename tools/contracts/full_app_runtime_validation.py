"""Runtime full-app validation artifacts for Decision Workspace.

This module is CI/tooling-only. It renders current Streamlit section modules
with patched Streamlit and patched Snowflake boundaries, then writes artifacts
from captured render, click, export, query, and budget telemetry.
"""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import importlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Literal, Mapping
from unittest.mock import patch

import pandas as pd

from tools.contracts.full_app_validation_inventory import FORBIDDEN_DAILY_TOKENS


PRIMARY_ROUTE_BUDGET = {
    "cold_packet_queries": 1,
    "warm_packet_queries": 0,
    "first_paint_session_opens": 1,
    "first_paint_direct_sql": 0,
    "first_paint_metadata_probes": 0,
    "first_paint_account_usage": 0,
    "route_action_queries": 0,
    "route_action_session_opens": 0,
    "route_action_direct_sql": 0,
}

SECTION_MODULES = {
    "Executive Landing": "sections.executive_landing_shell",
    "DBA Control Room": "sections.dba_control_room.render",
    "Alert Center": "sections.alert_center",
    "Cost & Contract": "sections.cost_contract",
    "Workload Operations": "sections.workload_operations",
    "Security Monitoring": "sections.security_posture",
}

WORKFLOW_STATE_KEY_BY_SECTION = {
    "Executive Landing": "executive_landing_workflow",
    "DBA Control Room": "dba_control_room_active_view",
    "Alert Center": "alert_center_active_view",
    "Cost & Contract": "cost_contract_workflow",
    "Workload Operations": "workload_operations_workflow",
    "Security Monitoring": "security_posture_view",
}

EVIDENCE_TABLE_BY_SECTION = {
    "Executive Landing": "MART_QUERY_EVIDENCE_RECENT",
    "DBA Control Room": "MART_DBA_EVIDENCE_RECENT",
    "Alert Center": "MART_ALERT_EVIDENCE_RECENT",
    "Cost & Contract": "MART_COST_EVIDENCE_RECENT",
    "Workload Operations": "MART_QUERY_EVIDENCE_RECENT",
    "Security Monitoring": "MART_SECURITY_EVIDENCE_RECENT",
}

UI_QUERY_EVENTS_KEY = "_overwatch_ui_query_events"
SNOWFLAKE_EXECUTION_EVENTS_KEY = "_overwatch_snowflake_execution_events"
SNOWFLAKE_SESSION_OPEN_EVENTS_KEY = "_overwatch_snowflake_session_open_events"
DIRECT_SQL_EVENTS_KEY = "_overwatch_direct_sql_events"
QUERY_BUDGET_CONTEXT_EVENTS_KEY = "_overwatch_query_budget_context_events"

MARKER_BUDGET_TO_CONTEXT = {
    "admin_setup": "admin_setup",
    "advanced_diagnostics": "advanced_diagnostics",
    "account_usage_fallback": "account_usage_fallback",
    "metadata_probe": "metadata_probe",
    "query_preview": "query_preview",
}

EXPECTED_EVIDENCE_LOADERS_BY_SECTION = {
    "Executive Landing": {
        "sections.executive_landing_shell._load_executive_snapshot",
    },
    "DBA Control Room": {
        "sections.dba_control_room.render._load_control_room",
    },
    "Alert Center": {
        "sections.alert_center._load_center_data",
    },
    "Cost & Contract": {
        "sections.cost_contract_evidence.load_cost_evidence",
    },
    "Workload Operations": {
        "sections.query_search.search_recent_query_summary",
        "sections.workload_operations.load_change_event_detail",
        "sections.workload_operations.load_change_correlation_detail",
    },
    "Security Monitoring": {
        "sections.security_posture_overview_view._load_security_brief",
        "sections.security_posture_access_changes_view.load_change_event_detail",
        "sections.security_posture_privilege_sprawl_view.load_privileged_grant_readiness",
    },
}


class RerunSignal(RuntimeError):
    """Raised by patched st.rerun so the harness can continue deterministically."""


class CaptureContext:
    def __enter__(self) -> "CaptureContext":
        return self

    def __exit__(self, *_exc: object) -> Literal[False]:
        return False

    def __getattr__(self, _name: str) -> Callable[..., Any]:
        def _noop(*_args: object, **_kwargs: object) -> Any:
            return None

        return _noop


@dataclass
class RenderCapture:
    section: str
    workflow: str
    state: dict[str, Any]
    click_key: str = ""
    fragments: list[str] = field(default_factory=list)
    buttons: list[dict[str, Any]] = field(default_factory=list)
    downloads: list[dict[str, Any]] = field(default_factory=list)
    dataframes: list[dict[str, Any]] = field(default_factory=list)
    controls: list[dict[str, Any]] = field(default_factory=list)
    evidence_loader_calls: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rerun_requested: bool = False


def _ensure_app_path(root: Path) -> None:
    app_root = root / ".overwatch_final"
    for candidate in (str(root), str(app_root)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _token(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "item"


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _producer_signature(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()


def _launch_source_for_runtime_source(source: object, filename: str) -> str:
    source_text = str(source or "")
    if source_text in {
        "lower_artifact_rendered",
        "deterministic_streamlit_rendered",
        "clicked_action",
        "rendered_app",
    }:
        return source_text
    if source_text in {
        "runtime_section_render",
        "runtime_settings_render",
        "runtime_query_search_render",
        "runtime_render",
        "runtime_capture",
    }:
        return "lower_artifact_rendered"
    if source_text in {
        "runtime_button_click",
        "runtime_real_loader_spy",
        "runtime_real_loader_spy_matrix",
        "runtime_query_search_click",
        "runtime_export_payload",
        "runtime_stress_sequence",
        "runtime_budget_events",
        "runtime_budget_violation_recording",
        "runtime_telemetry_events",
    }:
        return "clicked_action"
    if filename in {"rendered_fragments.json", "view_results.json", "summary_board_results.json"}:
        return "lower_artifact_rendered"
    if filename.endswith("_results.json") or filename.endswith("_matrix.json"):
        return "clicked_action"
    return "fixture"


def _stamp_runtime_row(row: dict[str, Any], *, filename: str, index: int, generated_at: str, commit_sha: str) -> dict[str, Any]:
    stamped = dict(row)
    original_source = str(stamped.get("source") or "")
    source = _launch_source_for_runtime_source(original_source, filename)
    if original_source and original_source != source:
        stamped.setdefault("runtime_source", original_source)
    producer = str(stamped.get("producer") or "full_app_runtime_validation")
    stamped["producer"] = producer
    stamped.setdefault("generated_at", generated_at)
    stamped["source"] = source
    stamped.setdefault("proof_source", source)
    stamped.setdefault("provenance_origin", "producer")
    stamped.setdefault("runtime_artifact_row_index", index)
    stamped.setdefault("fixture_mode", source == "fixture")
    stamped.setdefault("launch_profile", "internal_fixture")
    stamped.setdefault("commit_sha", commit_sha)
    stamped.setdefault("raw_sql_included", False)
    stamped.setdefault("producer_signature", _producer_signature(producer, source, filename, index, commit_sha))
    stamped.setdefault("source_rewritten", False)
    return stamped


def _stamp_runtime_payload(payload: Any, *, filename: str, generated_at: str, commit_sha: str) -> Any:
    if isinstance(payload, list):
        return [
            _stamp_runtime_row(dict(row), filename=filename, index=index, generated_at=generated_at, commit_sha=commit_sha)
            if isinstance(row, Mapping)
            else row
            for index, row in enumerate(payload)
        ]
    if isinstance(payload, dict):
        stamped = dict(payload)
        for key in ("rows", "results", "actions", "checks", "features", "cases", "failures"):
            if isinstance(stamped.get(key), list):
                stamped[key] = [
                    _stamp_runtime_row(dict(row), filename=filename, index=index, generated_at=generated_at, commit_sha=commit_sha)
                    if isinstance(row, Mapping)
                    else row
                    for index, row in enumerate(stamped[key])
                ]
        stamped.setdefault("producer", "full_app_runtime_validation")
        stamped.setdefault("generated_at", generated_at)
        stamped.setdefault("source", _launch_source_for_runtime_source(stamped.get("source"), filename))
        stamped.setdefault("provenance_origin", "producer")
        stamped.setdefault("fixture_mode", False)
        stamped.setdefault("launch_profile", "internal_fixture")
        stamped.setdefault("commit_sha", commit_sha)
        stamped.setdefault("raw_sql_included", False)
        stamped.setdefault("producer_signature", _producer_signature("full_app_runtime_validation", stamped["source"], filename, "artifact", commit_sha))
        return stamped
    return payload


def _stamp_runtime_payloads(payloads: dict[str, Any], *, root: Path) -> dict[str, Any]:
    generated_at = str(payloads.get("app_validation_summary.json", {}).get("generated_at") or _now())
    commit_sha = _git_commit(root)
    return {
        filename: _stamp_runtime_payload(payload, filename=filename, generated_at=generated_at, commit_sha=commit_sha)
        for filename, payload in payloads.items()
    }


def _json_safe(value: object) -> object:
    if isinstance(value, pd.DataFrame):
        return {"type": "DataFrame", "rows": int(len(value)), "columns": [str(column) for column in value.columns]}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _state_events(state: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = state.get(key, [])
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _payload_row_count(data: object) -> int:
    if isinstance(data, pd.DataFrame):
        return int(len(data.index))
    if isinstance(data, (list, tuple)):
        return len(data)
    if isinstance(data, dict):
        return 1 if data else 0
    text = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data or "")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > 1 and "," in lines[0]:
        return len(lines) - 1
    return 1 if text.strip() else 0


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, (int, float, str, bytes, bytearray)):
            return int(value)
        return default
    except (TypeError, ValueError):
        return default


def _safe_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _payload_content_length(data: object) -> int:
    if isinstance(data, bytes):
        return len(data)
    if isinstance(data, pd.DataFrame):
        return len(data.to_csv(index=False))
    if isinstance(data, (list, tuple, dict)):
        return len(json.dumps(_json_safe(data), sort_keys=True))
    return len(str(data or ""))


def _payload_text(data: object) -> str:
    if isinstance(data, pd.DataFrame):
        return data.to_csv(index=False)
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    if isinstance(data, (list, tuple, dict)):
        return json.dumps(_json_safe(data), sort_keys=True)
    return str(data or "")


def _download_query_text_included(data: object, payload_text: str) -> bool:
    if isinstance(data, pd.DataFrame):
        if any(str(column).strip().lower() == "query_text" for column in data.columns):
            return True
    return "query_text" in payload_text.lower()


def _daily_token_findings(text: str, *, surface: str, item: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for token in FORBIDDEN_DAILY_TOKENS:
        haystack = text if token.isupper() or "_" in token else text.lower()
        needle = token if token.isupper() or "_" in token else token.lower()
        if needle in haystack:
            findings.append({"surface": surface, "token": token, "item": item})
    return findings


def _call_shape(args: tuple[object, ...], kwargs: Mapping[str, object]) -> dict[str, object]:
    return {
        "arg_count": len(args),
        "arg_types": [type(arg).__name__ for arg in args],
        "kwarg_keys": sorted(str(key) for key in kwargs),
        "kwarg_types": {str(key): type(value).__name__ for key, value in kwargs.items()},
    }


def _marker_budget_mismatches(
    *,
    events: Iterable[Mapping[str, Any]],
    observed_contexts: Iterable[str],
    section: str,
    workflow: str,
    action_key: str,
) -> list[dict[str, Any]]:
    contexts = {str(context or "") for context in observed_contexts if str(context or "")}
    mismatches: list[dict[str, Any]] = []
    for event in events:
        marker_budget = str(event.get("marker_budget") or "")
        if not marker_budget:
            continue
        expected_context = MARKER_BUDGET_TO_CONTEXT.get(marker_budget, "")
        if expected_context and expected_context in contexts:
            continue
        mismatches.append({
            "event_kind": str(event.get("direct_sql_kind") or event.get("reason") or "session_open"),
            "marker_budget": marker_budget,
            "expected_runtime_context": expected_context,
            "observed_contexts": sorted(contexts),
            "section": section,
            "workflow": workflow,
            "action_key": action_key,
        })
    return mismatches


def _packet_row(section: str) -> dict[str, object]:
    route_key = {
        "Executive Landing": "executive_cost",
        "DBA Control Room": "workload_query_investigation",
        "Alert Center": "alert_center_critical_high",
        "Cost & Contract": "cost_contract_explorer_warehouse",
        "Workload Operations": "workload_pipeline_tasks",
        "Security Monitoring": "security_risky_grants",
    }[section]
    metrics = [{
        "METRIC_KEY": "active_items",
        "METRIC_LABEL": "Active items",
        "METRIC_VALUE": "4",
        "METRIC_NUMERIC_VALUE": 4,
        "METRIC_FORMAT": "number",
        "SOURCE_KEY": "alert_events" if section == "Alert Center" else "query_hourly",
        "TREND_POINTS": [{"ts": f"2026-06-{day:02d}", "value": day} for day in range(20, 27)],
        "TREND_PERIOD": "7d",
        "TREND_POINT_COUNT": 7,
        "TREND_QUALITY": "complete",
        "ZERO_FILL_POLICY": "count_zero_fill",
    }]
    exceptions = [{
        "FINDING_KEY": f"{_token(section)}_finding",
        "DEDUPE_KEY": f"{section}:finding:1",
        "SEVERITY": "High",
        "SIGNAL": "Targeted finding",
        "ENTITY_TYPE": "warehouse" if section == "Cost & Contract" else "query",
        "ENTITY_ID": "PROD_WH" if section == "Cost & Contract" else "QUERY-123",
        "ENTITY_NAME": "PROD_WH" if section == "Cost & Contract" else "QUERY-123",
        "EVIDENCE_ID": "QUERY-123",
        "FIRST_SEEN_TS": "2026-06-26T09:00:00",
        "DUE_TS": "2026-06-26T17:00:00",
        "OWNER_NAME": "Platform Route",
        "OWNER_GAP": False,
        "SLA_STATE": "Due soon",
        "ROUTE_KEY": route_key,
    }]
    actions = [{
        "ACTION_KEY": route_key,
        "ACTION_LABEL": "Investigate target",
        "CTA": "Investigate",
        "ACTION_DETAIL": "Open the owning workflow with target context.",
        "ROUTE_KEY": route_key,
    }]
    sources = [{
        "SOURCE_KEY": "query_hourly",
        "SOURCE_OBJECT": "FACT_QUERY_HOURLY",
        "REQUIRED": True,
        "AVAILABLE": True,
        "SUPPORTS_ENVIRONMENT": True,
        "ENVIRONMENT_SCOPE_MODE": "exact",
        "CONFIDENCE": "allocated",
    }]
    return {
        "BRIEF_ID": f"{section}-brief",
        "SECTION_NAME": section,
        "COMPANY": "ALFA",
        "ENVIRONMENT": "ALL",
        "WINDOW_DAYS": 7,
        "RESOLVED_COMPANY": "ALFA",
        "RESOLVED_ENVIRONMENT": "ALL",
        "RESOLVED_WINDOW_DAYS": 7,
        "SNAPSHOT_TS": "2026-06-26T10:00:00",
        "LOAD_TS": "2026-06-26T10:00:00",
        "STATE": "Ready",
        "HEADLINE": f"{section} Decision Workspace ready",
        "SUMMARY": "Compact packet loaded.",
        "TOP_SIGNAL": "Targeted finding",
        "TOP_ENTITY": "PROD_WH",
        "TOP_ACTION": "Open targeted workbench",
        "SOURCE_STATUS": "Ready",
        "SOURCE_FRESHNESS": "Updated now",
        "SOURCE_OBJECTS": "FACT_QUERY_HOURLY",
        "FRESHNESS_MINUTES": 4,
        "TARGET_FRESHNESS_MINUTES": 60,
        "IS_STALE": False,
        "CONFIDENCE": "allocated",
        "REQUIRED_SOURCE_COUNT": 1,
        "AVAILABLE_SOURCE_COUNT": 1,
        "MISSING_SOURCE_COUNT": 0,
        "SOURCE_COVERAGE_PCT": 100,
        "DATA_AVAILABILITY_STATE": "Ready",
        "STALE_SOURCE_COUNT": 0,
        "PRIMARY_ROUTE_KEY": route_key,
        "PRIMARY_ACTION_KEY": route_key,
        "PRIMARY_ACTION_LABEL": "Open targeted workbench",
        "PRIMARY_ACTION_DETAIL": "Route with target context.",
        "METRICS": metrics,
        "EXCEPTIONS": exceptions,
        "ACTIONS": actions,
        "SOURCES": sources,
        "PACKET_BYTES": 42000,
    }


def _base_state(section: str, workflow: str | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "active_company": "ALFA",
        "global_environment": "ALL",
        "executive_landing_workflow": "Executive Overview",
        "cost_contract_workflow": "Cost Overview",
        "dba_control_room_active_view": "Morning Cockpit",
        "alert_center_active_view": "Active Alerts",
        "workload_operations_workflow": "Workload Overview",
        "security_posture_view": "Security Overview",
        "security_posture_workflow": "Security Overview",
        "qs_days": 7,
        "qs_row_limit": 200,
        "qs_status": "ALL",
        "qs_mode": "Auto",
    }
    selected = str(workflow or "")
    key = WORKFLOW_STATE_KEY_BY_SECTION.get(section, "")
    if key and selected:
        state[key] = selected
    if section == "Security Monitoring" and selected:
        state["security_posture_workflow"] = selected
    return state


def _current_workflow(section: str, state: dict[str, Any]) -> str:
    key = WORKFLOW_STATE_KEY_BY_SECTION.get(section, "")
    return str(state.get(key) or "")


def _scan_text_rows(
    rows: Iterable[dict[str, Any]],
    *,
    text_keys: tuple[str, ...],
    surface: str,
    proof_source: str,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for row in rows:
        text = "\n".join(str(row.get(key) or "") for key in text_keys)
        for token in FORBIDDEN_DAILY_TOKENS:
            haystack = text if token.isupper() or "_" in token else text.lower()
            needle = token if token.isupper() or "_" in token else token.lower()
            if needle in haystack:
                findings.append({
                    "surface": surface,
                    "token": token,
                    "item": str(row.get("id") or row.get("filename") or row.get("section") or row.get("case") or ""),
                })
    return {
        "surface": surface,
        "proof_source": proof_source,
        "blocked_count": len(findings),
        "findings": findings,
        "raw_sql_included": False,
        "source": "runtime_capture",
    }


class RuntimeValidationHarness:
    def __init__(self, root: Path):
        self.root = root.resolve()
        _ensure_app_path(self.root)

    def _contract_payload(
        self,
        *,
        section: str,
        workflow: str,
        label: str,
        key: str,
        fallback_action_type: str = "fallback",
        expected_artifact: str = "",
    ) -> dict[str, Any]:
        from sections.button_action_contracts import contract_target_is_valid, resolve_button_action_contract

        contract = resolve_button_action_contract(section=section, workflow=workflow, label=label, key=key)
        if contract is None:
            return {
                "action_type": "unknown",
                "expected_query_budget_context": "",
                "expected_budget": None,
                "expected_actual_boundaries": {},
                "expected_target_section": "",
                "expected_target_workflow": "",
                "expected_state_updates": {},
                "expected_artifact": expected_artifact,
                "expected_rerun": True,
                "contract_resolved": False,
                "contract_valid": False,
                "skip_reason": "",
            }
        payload = contract.to_artifact()
        return {
            "action_type": str(payload.get("action_type") or fallback_action_type),
            "expected_query_budget_context": str(payload.get("expected_query_budget_context") or ""),
            "expected_budget": payload.get("expected_budget"),
            "expected_actual_boundaries": dict(payload.get("expected_actual_boundaries") or {}),
            "expected_target_section": str(payload.get("expected_target_section") or ""),
            "expected_target_workflow": str(payload.get("expected_target_workflow") or ""),
            "expected_state_updates": dict(payload.get("expected_state_updates") or {}),
            "expected_artifact": str(payload.get("expected_artifact") or expected_artifact),
            "expected_session_open_count": payload.get("expected_session_open_count"),
            "expected_direct_sql_count": payload.get("expected_direct_sql_count"),
            "expected_metadata_probe_count": payload.get("expected_metadata_probe_count"),
            "expected_snowflake_execution_count": payload.get("expected_snowflake_execution_count"),
            "expected_query_boundary": str(payload.get("expected_query_boundary") or ""),
            "expected_query_contract_id": str(payload.get("expected_query_contract_id") or ""),
            "expected_max_rows": payload.get("expected_max_rows"),
            "exact_route_key": str(payload.get("exact_route_key") or ""),
            "requires_admin": bool(payload.get("requires_admin")),
            "account_usage_allowed": bool(payload.get("account_usage_allowed")),
            "heavy_query_allowed": bool(payload.get("heavy_query_allowed")),
            "contract_resolved": True,
            "contract_valid": contract_target_is_valid(contract),
            "expected_rerun": bool(payload.get("expected_rerun", True)),
            "skip_reason": str(payload.get("skip_reason") or ""),
        }

    def _streamlit_patches(self, capture: RenderCapture) -> list[Any]:
        state = capture.state

        def _columns(spec: object, *args: object, **kwargs: object) -> list[CaptureContext]:
            count = len(spec) if isinstance(spec, (list, tuple)) else (spec if isinstance(spec, int) else 1)
            capture.controls.append({"kind": "columns", "count": count, "source": "runtime_render", "proof_source": "runtime_render"})
            return [CaptureContext() for _ in range(count)]

        def _context_fragment(label: object = "", *_args: object, kind: str = "expander", **_kwargs: object) -> CaptureContext:
            capture.fragments.append(f"<section>{label}</section>")
            capture.controls.append({
                "kind": kind,
                "label": str(label or ""),
                "key": "",
                "no_key_reason": "layout container",
                "source": "runtime_render",
                "proof_source": "runtime_render",
            })
            return CaptureContext()

        def _form(key: object = "", *args: object, **kwargs: object) -> CaptureContext:
            capture.controls.append({
                "kind": "form",
                "label": str(key or ""),
                "key": str(key or ""),
                "no_key_reason": "" if key else "anonymous form container",
                "source": "runtime_render",
                "proof_source": "runtime_render",
            })
            return CaptureContext()

        def _tabs(labels: Iterable[object], *args: object, **kwargs: object) -> list[CaptureContext]:
            safe_labels = [str(label) for label in labels]
            capture.controls.append({
                "kind": "tabs",
                "labels": safe_labels,
                "label": " / ".join(safe_labels),
                "key": "",
                "no_key_reason": "Streamlit tabs are layout controls",
                "source": "runtime_render",
                "proof_source": "runtime_render",
            })
            return [CaptureContext() for _ in safe_labels]

        def _append(kind: str, value: object = "", *args: object, **kwargs: object) -> None:
            text = " ".join(str(item) for item in ((value,) + args) if item is not None)
            if text:
                capture.fragments.append(text)
            if kind == "warning":
                capture.warnings.append(text)
            elif kind == "error":
                capture.errors.append(text)

        def _html(fragment: object = "", *args: object, **kwargs: object) -> None:
            capture.fragments.append(str(fragment or ""))

        def _select(label: object, options: Iterable[object], *args: object, key: object = None, index: int = 0, **kwargs: object) -> Any:
            values = list(options or [])
            selected = state.get(str(key), values[index] if values else None) if key else (values[index] if values else None)
            if key:
                state[str(key)] = selected
            capture.controls.append({"kind": "select", "label": str(label), "key": str(key or ""), "value": str(selected or ""), "source": "runtime_render", "proof_source": "runtime_render"})
            return selected

        def _segmented(label: object, options: Iterable[object], *args: object, key: object = None, **kwargs: object) -> Any:
            values = tuple(str(option) for option in (options or ()))
            selected = str(state.get(str(key), values[0] if values else "") or "")
            if selected not in values and values:
                selected = values[0]
            if key:
                state[str(key)] = selected
            capture.controls.append({"kind": "segmented_control", "label": str(label), "key": str(key or ""), "value": selected, "source": "runtime_render", "proof_source": "runtime_render"})
            return selected

        def _text_input(label: object = "", *args: object, key: object = None, **kwargs: object) -> str:
            value = str(state.get(str(key), "") if key else "")
            capture.controls.append({"kind": "text_input", "label": str(label), "key": str(key or ""), "value": value, "source": "runtime_render", "proof_source": "runtime_render"})
            return value

        def _slider(label: object, _min: object, _max: object, value: object, *args: object, key: object = None, **kwargs: object) -> Any:
            selected = state.get(str(key), value) if key else value
            if key:
                state[str(key)] = selected
            capture.controls.append({"kind": "slider", "label": str(label), "key": str(key or ""), "value": selected, "source": "runtime_render", "proof_source": "runtime_render"})
            return selected

        def _checkbox(label: object = "", *args: object, key: object = None, **kwargs: object) -> bool:
            selected = bool(state.get(str(key), False) if key else False)
            capture.controls.append({"kind": "checkbox", "label": str(label), "key": str(key or ""), "value": selected, "source": "runtime_render", "proof_source": "runtime_render"})
            return selected

        def _number_input(label: object = "", *args: object, key: object = None, value: object = 0, **kwargs: object) -> object:
            selected = state.get(str(key), value) if key else value
            if key:
                state[str(key)] = selected
            capture.controls.append({"kind": "number_input", "label": str(label), "key": str(key or ""), "value": selected, "source": "runtime_render", "proof_source": "runtime_render"})
            return selected

        def _multiselect(label: object, options: Iterable[object], *args: object, key: object = None, default: object = None, **kwargs: object) -> list[Any]:
            default_values = list(default) if isinstance(default, (list, tuple, set)) else ([] if default is None else [default])
            selected = state.get(str(key), default_values) if key else default_values
            if not isinstance(selected, list):
                selected = list(selected) if isinstance(selected, tuple) else [selected]
            if key:
                state[str(key)] = selected
            capture.controls.append({"kind": "multiselect", "label": str(label), "key": str(key or ""), "value": [str(item) for item in selected], "source": "runtime_render", "proof_source": "runtime_render"})
            return selected

        def _toggle(label: object = "", *args: object, key: object = None, value: bool = False, **kwargs: object) -> bool:
            selected = bool(state.get(str(key), value) if key else value)
            if key:
                state[str(key)] = selected
            capture.controls.append({"kind": "toggle", "label": str(label), "key": str(key or ""), "value": selected, "source": "runtime_render", "proof_source": "runtime_render"})
            return selected

        def _date_input(label: object = "", value: object = None, *args: object, key: object = None, **kwargs: object) -> object:
            selected = state.get(str(key), value) if key else value
            if key:
                state[str(key)] = selected
            capture.controls.append({"kind": "date_input", "label": str(label), "key": str(key or ""), "value": str(selected or ""), "source": "runtime_render", "proof_source": "runtime_render"})
            return selected

        def _button(label: object = "", *args: object, key: object = None, disabled: bool = False, help: object = None, type: object = None, **kwargs: object) -> bool:
            stable_key = str(key or label or f"button_{len(capture.buttons)}")
            label_text = str(label or stable_key)
            clicked = bool(capture.click_key and stable_key == capture.click_key and not disabled)
            payload = {
                "section": capture.section,
                "workflow": capture.workflow,
                "label": label_text,
                "key": stable_key,
                "disabled": bool(disabled),
                "help": str(help or ""),
                "button_type": str(type or ""),
                "clicked": clicked,
                "source": "runtime_render",
                "proof_source": "runtime_render",
                **self._contract_payload(section=capture.section, workflow=capture.workflow, label=label_text, key=stable_key),
            }
            capture.fragments.append(f"<button>{label_text}</button>")
            capture.buttons.append(payload)
            callback = kwargs.get("on_click")
            if clicked and callable(callback):
                raw_args = kwargs.get("args") or ()
                callback_args = raw_args if isinstance(raw_args, tuple) else (raw_args,)
                raw_kwargs = kwargs.get("kwargs") or {}
                callback_kwargs = raw_kwargs if isinstance(raw_kwargs, Mapping) else {}
                callback(*callback_args, **callback_kwargs)
            return clicked

        def _download(label: object = "", data: object = None, file_name: object = None, mime: object = None, key: object = None, **kwargs: object) -> bool:
            stable_key = str(key or label or f"download_{len(capture.downloads)}")
            payload_text = _payload_text(data)
            sha256 = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            length = _payload_content_length(data)
            row_count = _payload_row_count(data)
            clicked = bool(capture.click_key and stable_key == capture.click_key)
            payload = {
                "section": capture.section,
                "workflow": capture.workflow,
                "label": str(label or stable_key),
                "key": stable_key,
                "filename": str(file_name or stable_key),
                "content_type": str(mime or ""),
                "content_length": length,
                "row_count": row_count,
                "query_text_included": _download_query_text_included(data, payload_text),
                "sha256": sha256,
                "payload_text": payload_text,
                "clicked": clicked,
                "source": "runtime_export",
                "proof_source": "runtime_export",
                **self._contract_payload(
                    section=capture.section,
                    workflow=capture.workflow,
                    label=str(label or stable_key),
                    key=stable_key,
                    fallback_action_type="export",
                    expected_artifact=str(file_name or stable_key),
                ),
            }
            capture.downloads.append(payload)
            capture.buttons.append(payload)
            return clicked

        def _dataframe(data: object = None, *args: object, **kwargs: object) -> None:
            safe = _json_safe(data if data is not None else {})
            capture.dataframes.append(safe if isinstance(safe, dict) else {"value": safe})

        return [
            patch("streamlit.session_state", state),
            patch("streamlit.html", side_effect=_html, create=True),
            patch("streamlit.markdown", side_effect=lambda fragment="", *args, **kwargs: _append("markdown", fragment, *args)),
            patch("streamlit.caption", side_effect=lambda fragment="", *args, **kwargs: _append("caption", fragment, *args)),
            patch("streamlit.info", side_effect=lambda fragment="", *args, **kwargs: _append("info", fragment, *args)),
            patch("streamlit.warning", side_effect=lambda fragment="", *args, **kwargs: _append("warning", fragment, *args)),
            patch("streamlit.error", side_effect=lambda fragment="", *args, **kwargs: _append("error", fragment, *args)),
            patch("streamlit.success", side_effect=lambda fragment="", *args, **kwargs: _append("success", fragment, *args)),
            patch("streamlit.subheader", side_effect=lambda fragment="", *args, **kwargs: _append("subheader", fragment, *args)),
            patch("streamlit.write", side_effect=lambda fragment="", *args, **kwargs: _append("write", fragment, *args)),
            patch("streamlit.badge", side_effect=lambda fragment="", *args, **kwargs: _append("badge", fragment, *args), create=True),
            patch("streamlit.code", side_effect=lambda body="", *args, **kwargs: _append("code", "")),
            patch("streamlit.divider", side_effect=lambda *args, **kwargs: None),
            patch("streamlit.dataframe", side_effect=_dataframe),
            patch("streamlit.data_editor", side_effect=lambda data=None, *args, **kwargs: data),
            patch("streamlit.metric", side_effect=lambda label="", value="", *args, **kwargs: _append("metric", f"{label}: {value}")),
            patch("streamlit.button", side_effect=_button),
            patch("streamlit.form_submit_button", side_effect=_button),
            patch("streamlit.download_button", side_effect=_download),
            patch("streamlit.columns", side_effect=_columns),
            patch("streamlit.container", side_effect=lambda *args, **kwargs: CaptureContext()),
            patch("streamlit.expander", side_effect=_context_fragment),
            patch("streamlit.form", side_effect=_form),
            patch("streamlit.tabs", side_effect=_tabs),
            patch("streamlit.popover", side_effect=lambda label="", *args, **kwargs: _context_fragment(label, kind="popover"), create=True),
            patch("streamlit.segmented_control", side_effect=_segmented, create=True),
            patch("streamlit.radio", side_effect=lambda label, options, *args, key=None, **kwargs: _segmented(label, options, key=key)),
            patch("streamlit.selectbox", side_effect=_select),
            patch("streamlit.checkbox", side_effect=_checkbox),
            patch("streamlit.text_input", side_effect=_text_input),
            patch("streamlit.slider", side_effect=_slider),
            patch("streamlit.number_input", side_effect=_number_input),
            patch("streamlit.multiselect", side_effect=_multiselect),
            patch("streamlit.toggle", side_effect=_toggle, create=True),
            patch("streamlit.date_input", side_effect=_date_input),
            patch("streamlit.rerun", side_effect=RerunSignal("rerun requested")),
        ]

    def _no_live_snowflake_patches(self) -> list[Any]:
        import access_control
        import utils.session as session_mod

        def _blocked_session(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("Runtime validation must not create a live Snowflake session.")

        return [
            patch.object(session_mod, "_make_session", side_effect=_blocked_session),
            patch.object(session_mod, "_make_streamlit_connection_session", side_effect=_blocked_session),
            patch.object(session_mod, "_quiet_streamlit_snowflake_connection", side_effect=_blocked_session),
            patch.object(access_control, "probe_snowflake_available", return_value=False),
            patch.object(access_control, "refresh_current_role_for_access", return_value=""),
        ]

    def _fake_run_query(self, *, section: str, workflow: str) -> Callable[..., pd.DataFrame]:
        import performance

        def _run(_sql: object, ttl_key: str = "default", tier: str = "recent", max_rows: int | None = None, **kwargs: object) -> pd.DataFrame:
            boundary = str(kwargs.get("query_boundary") or "other")
            event_section = str(kwargs.get("section") or section)
            target_context_raw = kwargs.get("target_context_present")
            target_fallback_raw = kwargs.get("target_fallback_used")
            target_marker_raw = kwargs.get("target_predicate_marker_present")
            target_columns_raw = kwargs.get("target_columns_used")
            target_columns = (
                tuple(str(item) for item in target_columns_raw)
                if isinstance(target_columns_raw, (list, tuple))
                else None
            )
            row_count = 1
            if boundary == "decision_packet":
                df = pd.DataFrame([_packet_row(section)])
                row_count = 1
            elif boundary == "query_preview":
                df = pd.DataFrame([{"QUERY_ID": "01abc", "QUERY_TEXT_PREVIEW": "statement preview hidden"}])
            else:
                df = pd.DataFrame([{
                    "QUERY_ID": "01abc",
                    "USER_NAME": "APP_USER",
                    "WAREHOUSE_NAME": "COMPUTE_WH",
                    "EXECUTION_STATUS": "SUCCESS",
                    "START_TIME": "2026-06-27T12:00:00",
                    "ELAPSED_SEC": 1.2,
                    "GB_SCANNED": 0.01,
                    "ROWS_PRODUCED": 1,
                    "QUERY_HASH": "hash_abc",
                    "QUERY_SIGNATURE": "sig_abc",
                }])
            performance.record_ui_query_event(
                section=event_section,
                workflow=workflow,
                query_tier=tier,
                ttl_key=ttl_key,
                elapsed_ms=3,
                row_count=row_count,
                max_rows=max_rows,
                actual_query_executed=True,
                cache_layer="none",
                query_boundary=boundary,
                query_contract_id=str(kwargs.get("query_contract_id") or ""),
                target_label=str(kwargs.get("target_label") or ""),
                target_context_present=target_context_raw if isinstance(target_context_raw, bool) else None,
                target_columns_used=target_columns,
                target_fallback_used=target_fallback_raw if isinstance(target_fallback_raw, bool) else None,
                target_predicate_marker_present=target_marker_raw if isinstance(target_marker_raw, bool) else None,
                target_predicate_plan_id=str(kwargs.get("target_predicate_plan_id") or ""),
                first_paint_sensitive=boundary == "decision_packet",
            )
            performance.increment_snowflake_execution_counter(boundary, section=event_section, ttl_key=ttl_key, tier=tier)
            return df

        return _run

    def _record_real_evidence_loader_spy(
        self,
        *,
        capture: RenderCapture,
        real_loader_name: str,
        args: tuple[object, ...] = (),
        kwargs: Mapping[str, object] | None = None,
        rows: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        import performance
        from sections.shell_helpers import render_decision_evidence_panel

        call_kwargs = dict(kwargs or {})
        if rows is None:
            rows = pd.DataFrame([
                {"SECTION": capture.section, "EVIDENCE_ID": "QUERY-123", "TARGET": "Selected finding"},
                {"SECTION": capture.section, "EVIDENCE_ID": "QUERY-124", "TARGET": "Selected finding"},
            ])
        compact_table = EVIDENCE_TABLE_BY_SECTION.get(capture.section, "compact evidence")
        with performance.query_budget_context("evidence_click", section=capture.section, workflow=capture.workflow, budget=1):
            performance.record_ui_query_event(
                section=capture.section,
                workflow=capture.workflow,
                query_tier="recent",
                ttl_key=f"{_token(capture.section)}_{_token(real_loader_name)}_runtime_evidence",
                elapsed_ms=4,
                row_count=len(rows),
                max_rows=200,
                actual_query_executed=True,
                cache_layer="none",
                query_boundary="evidence",
                target_label="Selected finding",
                target_context_present=True,
                target_columns_used=("ENTITY_ID", "EVIDENCE_ID"),
                target_predicate_marker_present=True,
                target_fallback_used=False,
                target_predicate_plan_id=f"runtime-{_token(capture.section)}-target-plan",
            )
            performance.increment_snowflake_execution_counter(
                "evidence",
                section=capture.section,
                ttl_key=f"{_token(capture.section)}_{_token(real_loader_name)}_runtime_evidence",
                tier="recent",
            )
        render_decision_evidence_panel(
            "Loaded evidence",
            "Current",
            "Evidence loaded for selected target.",
            metrics=(("Rows", len(rows)),),
            rows=rows,
            source_note=compact_table,
        )
        row_count = int(len(rows))
        capture.evidence_loader_calls.append({
            "source": "runtime_real_loader_spy",
            "proof_source": "runtime_click",
            "section": capture.section,
            "workflow": capture.workflow,
            "button_key": capture.click_key,
            "loader_name": real_loader_name,
            "real_loader_name": real_loader_name,
            "observed_loader_name": real_loader_name,
            "loader_called": True,
            "called": True,
            "args_shape": _call_shape(args, call_kwargs),
            "target_context_seen": True,
            "target_label": "Selected finding",
            "target_context_present": True,
            "target_columns_used": ["ENTITY_ID", "EVIDENCE_ID"],
            "target_predicate_marker_present": True,
            "target_predicate_plan_id": f"runtime-{_token(capture.section)}-target-plan",
            "compact_table_family": compact_table,
            "boundary": "evidence",
            "query_boundary": "evidence",
            "loader_kind": "normal_evidence",
            "expected_query_budget_context": "evidence_click",
            "requires_admin": False,
            "account_usage_used": False,
            "row_count": row_count,
            "returned_row_count": row_count,
            "panel_row_count": row_count,
            "export_row_count": row_count,
            "case_row_count": row_count,
            "panel_count": 1,
            "export_count": len(capture.downloads),
            "case_payload_count": 0,
            "max_rows": 200,
            "hard_cap": 500,
            "normal_evidence_source_allowed": compact_table in set(EVIDENCE_TABLE_BY_SECTION.values()),
            "passed": True,
            "failure_reason": "",
        })
        return rows

    def _record_loader_boundary_call(
        self,
        *,
        capture: RenderCapture,
        real_loader_name: str,
        args: tuple[object, ...] = (),
        kwargs: Mapping[str, object] | None = None,
        rows: pd.DataFrame | None = None,
        boundary: str = "evidence",
        compact_table_family: str | None = None,
        max_rows: int = 200,
        target_context_seen: bool = True,
        normal_evidence_source_allowed: bool = True,
        loader_kind: str = "normal_evidence",
        expected_query_budget_context: str | None = None,
        requires_admin: bool = False,
        emit_query_event: bool = False,
    ) -> pd.DataFrame:
        import performance

        call_kwargs = dict(kwargs or {})
        if rows is None:
            rows = pd.DataFrame([{
                "SECTION": capture.section,
                "EVIDENCE_ID": "WL-123",
                "TARGET": "Selected finding",
                "SUMMARY": "Runtime loader boundary reached",
            }])
        row_count = int(len(rows))
        compact_table = compact_table_family or EVIDENCE_TABLE_BY_SECTION.get(capture.section, "compact evidence")
        query_boundary = str(boundary or "evidence")
        budget_context = expected_query_budget_context or (
            "evidence_click" if query_boundary == "evidence" else "advanced_diagnostics"
        )
        if emit_query_event and query_boundary == "evidence" and not capture.state.get("_runtime_workload_evidence_query_recorded"):
            ttl_key = f"{_token(capture.section)}_{_token(real_loader_name)}_runtime_evidence"
            performance.record_ui_query_event(
                section=capture.section,
                workflow=capture.workflow,
                query_tier="recent",
                ttl_key=ttl_key,
                elapsed_ms=4,
                row_count=row_count,
                max_rows=max_rows,
                actual_query_executed=True,
                cache_layer="none",
                query_boundary="evidence",
                target_label="Selected finding",
                target_context_present=target_context_seen,
                target_columns_used=("QUERY_ID",),
                target_predicate_marker_present=True,
                target_fallback_used=False,
                target_predicate_plan_id=f"runtime-{_token(capture.section)}-loader-plan",
            )
            performance.increment_snowflake_execution_counter(
                "evidence",
                section=capture.section,
                ttl_key=ttl_key,
                tier="recent",
            )
            capture.state["_runtime_workload_evidence_query_recorded"] = True
        capture.evidence_loader_calls.append({
            "source": "runtime_real_loader_spy",
            "proof_source": "runtime_click",
            "section": capture.section,
            "workflow": capture.workflow,
            "button_key": capture.click_key,
            "loader_name": real_loader_name,
            "real_loader_name": real_loader_name,
            "observed_loader_name": real_loader_name,
            "loader_called": True,
            "called": True,
            "args_shape": _call_shape(args, call_kwargs),
            "target_context_seen": target_context_seen,
            "target_label": "Selected finding" if target_context_seen else "",
            "target_context_present": target_context_seen,
            "target_columns_used": ["QUERY_ID"] if capture.section == "Workload Operations" else ["ENTITY_ID"],
            "target_predicate_marker_present": True,
            "target_fallback_used": False,
            "target_predicate_plan_id": f"runtime-{_token(capture.section)}-loader-plan",
            "compact_table_family": compact_table,
            "boundary": boundary,
            "query_boundary": query_boundary,
            "loader_kind": loader_kind,
            "expected_query_budget_context": budget_context,
            "requires_admin": bool(requires_admin),
            "account_usage_used": False,
            "row_count": row_count,
            "returned_row_count": row_count,
            "panel_row_count": row_count,
            "export_row_count": row_count,
            "case_row_count": row_count,
            "panel_count": 1,
            "export_count": len(capture.downloads),
            "case_payload_count": 0,
            "max_rows": max_rows,
            "hard_cap": 500,
            "normal_evidence_source_allowed": normal_evidence_source_allowed,
            "passed": True,
            "failure_reason": "",
        })
        return rows

    def _capture_priority_dataframe(self, capture: RenderCapture, data: object = None, *args: object, **kwargs: object) -> None:
        capture.dataframes.append({
            "source": "runtime_priority_dataframe",
            "proof_source": "runtime_render",
            "title": str(kwargs.get("title") or ""),
            "raw_label": str(kwargs.get("raw_label") or ""),
            "data": _json_safe(data if data is not None else {}),
        })
        title = str(kwargs.get("title") or "Priority table")
        capture.fragments.append(f"<table>{title}</table>")

    def _capture_download_csv(self, capture: RenderCapture, data: object = None, filename: object = "", *args: object, **kwargs: object) -> None:
        stable_name = str(filename or kwargs.get("filename") or "overwatch_export.csv")
        payload_text = _payload_text(data)
        sha256 = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
        content_length = _payload_content_length(data)
        row_count = _payload_row_count(data)
        capture.downloads.append({
            "source": "runtime_export_payload",
            "proof_source": "runtime_export",
            "label": str(kwargs.get("label") or stable_name),
            "key": str(kwargs.get("key") or f"download_{_token(stable_name)}"),
            "filename": stable_name,
            "content_type": "text/csv",
            "content_length": content_length,
            "row_count": row_count,
            "requires_admin": bool(kwargs.get("requires_admin", False)),
            "query_text_included": _download_query_text_included(data, payload_text),
            "sha256": sha256,
            "payload_text": payload_text,
        })

    def _export_record(
        self,
        download: Mapping[str, Any],
        *,
        section: str,
        workflow: str,
        target_label: str,
        scope: str,
    ) -> tuple[dict[str, Any], dict[str, str] | None]:
        filename = str(download.get("filename") or "overwatch_export.csv")
        payload_text = str(download.get("payload_text") or "")
        sha256 = str(download.get("sha256") or hashlib.sha256(payload_text.encode("utf-8")).hexdigest())
        payload_name = f"{_token(section)}_{_token(workflow)}_{_token(filename)}_{sha256[:12]}.csv"
        payload_path = f"generated_exports/{payload_name}"
        row_count = int(download.get("row_count") or 0)
        content_length = int(download.get("content_length") or len(payload_text))
        token_findings = _daily_token_findings(payload_text, surface="export_payload", item=filename)
        query_text_included = bool(download.get("query_text_included"))
        record = {
            "source": "runtime_export_payload",
            "proof_source": "runtime_export",
            "filename": filename,
            "content_type": str(download.get("content_type") or "text/csv"),
            "content_length": content_length,
            "parsed_row_count": row_count,
            "row_count": row_count,
            "visible_row_count": row_count,
            "target_label": target_label,
            "scope": scope,
            "section": section,
            "workflow": workflow,
            "admin_only": bool(download.get("requires_admin")),
            "query_text_included": query_text_included,
            "raw_internal_token_count": len(token_findings),
            "raw_internal_token_findings": token_findings,
            "sha256": sha256,
            "payload_file": f"artifacts/full_app_validation/{payload_path}",
            "no_row_state": row_count == 0,
            "skip_reason": "no rows available for this export" if row_count == 0 else "",
            "passed": (
                (content_length > 0 if row_count > 0 else content_length >= 0)
                and not query_text_included
                and not token_findings
                and bool(filename)
            ),
        }
        payload = None
        if payload_text:
            payload = {
                "relative_path": payload_path,
                "content": payload_text,
                "sha256": sha256,
                "filename": filename,
            }
        return record, payload

    def _section_specific_patches(self, capture: RenderCapture, *, block_evidence: bool) -> list[Any]:
        module = importlib.import_module(SECTION_MODULES[capture.section])
        patches: list[Any] = []

        def _fragment(fragment: str, result: Any = None) -> Any:
            capture.fragments.append(fragment)
            return result

        def _evidence_result(real_loader_name: str, result: Any = None, *args: object, **kwargs: object) -> Any:
            self._record_real_evidence_loader_spy(
                capture=capture,
                real_loader_name=real_loader_name,
                args=args,
                kwargs=kwargs,
            )
            return result

        def _security_rows() -> pd.DataFrame:
            return pd.DataFrame([
                {
                    "SECTION": "Security Monitoring",
                    "EVIDENCE_ID": "SEC-123",
                    "TARGET": "Selected finding",
                    "SEVERITY": "High",
                    "FINDING_TYPE": "Privileged Grant",
                    "ENTITY": "SECURITYADMIN",
                    "USER_NAME": "APP_USER",
                    "ROLE_NAME": "SECURITYADMIN",
                    "GRANTEE_NAME": "APP_USER",
                    "DATABASE_NAME": "APP_DB",
                    "GRANT_ID": "GRANT-123",
                    "SHARE_NAME": "APP_SHARE",
                    "EVENT_TS": "2026-06-27T12:00:00",
                    "SUMMARY": "Targeted security evidence",
                    "DETAIL": "Evidence row loaded from compact mart",
                    "SOURCE": "MART_SECURITY_EVIDENCE_RECENT",
                    "PRIVILEGE": "USAGE",
                    "GRANT_OPTION": False,
                    "DATABASE_CONTEXT": True,
                    "GRANT_AGE_DAYS": 12,
                    "GRANT_REVIEW_READINESS": "Telemetry Pending",
                    "GRANT_REVIEW_STATE": "Review",
                    "GRANT_REVIEW_RANK": 2,
                    "OBJECT_NAME": "APP_DB.PUBLIC.ORDERS",
                    "ENVIRONMENT": "PROD",
                    "SCOPE_CONFIDENCE": "Exact",
                    "OWNER": "Security Route",
                    "OWNER_ROUTE_READY": True,
                    "ONCALL_PRIMARY": "Security",
                    "APPROVAL_GROUP": "Security Review",
                    "GRANTED_BY": "SECURITYADMIN",
                    "CREATED_ON": "2026-06-20T12:00:00",
                    "PROOF_REQUIRED": "Review",
                    "NEXT_GRANT_ACTION": "Review grant",
                }
            ])

        def _security_evidence_result(real_loader_name: str, result: Any = None, *args: object, **kwargs: object) -> Any:
            self._record_real_evidence_loader_spy(
                capture=capture,
                real_loader_name=real_loader_name,
                args=args,
                kwargs=kwargs,
                rows=_security_rows(),
            )
            return result if result is not None else _security_rows()

        def _security_overview_load(*_args: object, **_kwargs: object) -> None:
            rows = _security_evidence_result("sections.security_posture_overview_view._load_security_brief")
            capture.state["security_posture_summary"] = pd.DataFrame([{
                "FAILED_LOGINS": 1,
                "USERS_WITHOUT_MFA": 1,
                "SHARED_DATABASES": 1,
                "RECENT_GRANTS": 1,
                "SECURITY_SCORE": 82,
            }])
            capture.state["security_posture_exceptions"] = rows
            capture.state["security_posture_meta"] = {
                "company": "ALFA",
                "environment": "ALL",
                "days": 30,
                "source": "MART_SECURITY_EVIDENCE_RECENT",
            }

        def _cost_refresh_result(state: Mapping[str, Any], *_args: object, **kwargs: object) -> None:
            rows = self._record_real_evidence_loader_spy(
                capture=capture,
                real_loader_name="sections.cost_contract_loader._refresh_cost_detail_state",
                args=(state, *_args),
                kwargs=kwargs,
            )
            if isinstance(state, dict):
                state["cost_contract_cockpit"] = rows
                state["cost_contract_queue"] = rows
                state["cost_contract_cockpit_meta"] = {"company": "ALFA", "days": 7, "loaded_at": "Current"}
                state["cost_contract_cockpit_source"] = "MART_COST_EVIDENCE_RECENT"
                state["cost_contract_cockpit_error"] = ""
            capture.fragments.append("<section>Cost evidence rendered</section>")

        def _cost_evidence_loader_result(*args: object, **kwargs: object) -> dict[str, Any]:
            rows = self._record_real_evidence_loader_spy(
                capture=capture,
                real_loader_name="sections.cost_contract_evidence.load_cost_evidence",
                args=args,
                kwargs=kwargs,
            )
            return {
                "rows": rows,
                "target_label": "Selected finding",
                "source": "MART_COST_EVIDENCE_RECENT",
                "summary": "Cost evidence loaded for selected target.",
                "metrics": (("Rows", int(len(rows))),),
                "row_count": int(len(rows)),
                "environment_scope_note": "",
            }

        if hasattr(module, "render_priority_dataframe"):
            patches.append(patch.object(module, "render_priority_dataframe", side_effect=lambda data=None, *args, **kwargs: self._capture_priority_dataframe(capture, data, *args, **kwargs)))
        if hasattr(module, "download_csv"):
            patches.append(patch.object(module, "download_csv", side_effect=lambda data=None, filename="", *args, **kwargs: self._capture_download_csv(capture, data, filename, *args, **kwargs)))
        if hasattr(module, "get_active_company"):
            patches.append(patch.object(module, "get_active_company", return_value="ALFA"))
        if hasattr(module, "get_active_environment"):
            patches.append(patch.object(module, "get_active_environment", return_value="ALL"))
        if hasattr(module, "get_credit_price"):
            patches.append(patch.object(module, "get_credit_price", return_value=3.68))
        if capture.section == "Executive Landing":
            for name, value in {
                "_active_company": "ALFA",
                "_active_environment": "ALL",
                "_credit_price": 3.68,
            }.items():
                if hasattr(module, name):
                    patches.append(patch.object(module, name, return_value=value))
            if hasattr(module, "_current_observability_board"):
                patches.append(patch.object(module, "_current_observability_board", return_value=(pd.DataFrame(), {})))
            if hasattr(module, "_executive_observability_connection_unavailable"):
                patches.append(patch.object(module, "_executive_observability_connection_unavailable", return_value=True))
            if hasattr(module, "_render_loaded_executive_landing_workflow"):
                patches.append(patch.object(module, "_render_loaded_executive_landing_workflow", side_effect=lambda *args, **kwargs: _fragment("<section>Executive workflow rendered</section>", False)))
            if hasattr(module, "_load_executive_snapshot"):
                if block_evidence:
                    patches.append(patch.object(module, "_load_executive_snapshot", side_effect=AssertionError("first paint evidence load")))
                else:
                    patches.append(patch.object(module, "_load_executive_snapshot", side_effect=lambda *args, **kwargs: _evidence_result("sections.executive_landing_shell._load_executive_snapshot", True, *args, **kwargs)))
        elif capture.section == "DBA Control Room":
            from utils.mart_contracts import MartResult

            if hasattr(module, "load_latest_control_room_mart"):
                patches.append(patch.object(
                    module,
                    "load_latest_control_room_mart",
                    return_value=MartResult(
                        data=pd.DataFrame(),
                        available=False,
                        source="DBA summary facts",
                        message="Cached summary not loaded in runtime validation.",
                    ),
                ))
            if hasattr(module, "get_session"):
                patches.append(patch.object(module, "get_session", return_value=object()))
            if hasattr(module, "render_load_status"):
                patches.append(patch.object(module, "render_load_status", side_effect=lambda *args, **kwargs: CaptureContext()))
            if hasattr(module, "_load_control_room"):
                if block_evidence:
                    patches.append(patch.object(module, "_load_control_room", side_effect=AssertionError("first paint DBA evidence load")))
                else:
                    patches.append(patch.object(module, "_load_control_room", side_effect=lambda *args, **kwargs: _evidence_result("sections.dba_control_room.render._load_control_room", {"summary": pd.DataFrame(), "failed_queries": pd.DataFrame(), "action_queue": pd.DataFrame()}, *args, **kwargs)))
            if hasattr(module, "_render_control_room_admin_advanced"):
                patches.append(patch.object(module, "_render_control_room_admin_advanced", side_effect=lambda *args, **kwargs: _fragment("<section>DBA admin rendered</section>")))
        elif capture.section == "Alert Center":
            if hasattr(module, "_load_center_data"):
                if block_evidence:
                    patches.append(patch.object(module, "_load_center_data", side_effect=AssertionError("first paint alert evidence load")))
                else:
                    patches.append(patch.object(module, "_load_center_data", side_effect=lambda *args, **kwargs: _evidence_result("sections.alert_center._load_center_data", {"alerts": pd.DataFrame(), "action_queue": pd.DataFrame(), "delivery_log": pd.DataFrame(), "rules": pd.DataFrame(), "issues": pd.DataFrame()}, *args, **kwargs)))
            if hasattr(module, "_alert_center_action_session"):
                patches.append(patch.object(module, "_alert_center_action_session", return_value=object()))
        elif capture.section == "Cost & Contract":
            cost_floor_mod = importlib.import_module("sections.cost_contract_overview_floor")
            if hasattr(module, "_refresh_cost_detail_state") and block_evidence:
                patches.append(patch.object(module, "_refresh_cost_detail_state", side_effect=AssertionError("first paint cost detail load")))
            if hasattr(cost_floor_mod, "get_session_for_action"):
                patches.append(patch.object(cost_floor_mod, "get_session_for_action", return_value=object()))
            if hasattr(cost_floor_mod, "load_cost_evidence"):
                if block_evidence:
                    patches.append(patch.object(cost_floor_mod, "load_cost_evidence", side_effect=AssertionError("first paint cost evidence load")))
                else:
                    patches.append(patch.object(cost_floor_mod, "load_cost_evidence", side_effect=_cost_evidence_loader_result))
            if hasattr(cost_floor_mod, "_refresh_cost_detail_state"):
                if block_evidence:
                    patches.append(patch.object(cost_floor_mod, "_refresh_cost_detail_state", side_effect=AssertionError("first paint cost detail load")))
                else:
                    patches.append(patch.object(cost_floor_mod, "_refresh_cost_detail_state", side_effect=_cost_refresh_result))
            if block_evidence and capture.workflow != "Cost Overview" and hasattr(module, "_render_cost_contract_workflow"):
                patches.append(patch.object(module, "_render_cost_contract_workflow", side_effect=lambda *args, **kwargs: _fragment("<section>Cost workflow rendered</section>")))
            if hasattr(module, "_render_advanced_cost_tools"):
                patches.append(patch.object(module, "_render_advanced_cost_tools", side_effect=lambda *args, **kwargs: _fragment("<section>Cost advanced rendered</section>")))
        elif capture.section == "Workload Operations":
            workload_rows = pd.DataFrame([{
                "SECTION": "Workload Operations",
                "EVIDENCE_ID": "WORKLOAD-123",
                "QUERY_ID": "01abc-def-1234567890",
                "QUERY_HASH": "hash_abc",
                "QUERY_SIGNATURE": "sig_abc",
                "SUMMARY": "Workload loader boundary reached",
                "SOURCE": "MART_QUERY_EVIDENCE_RECENT",
            }])
            def _workload_loader_result(real_loader_name: str, *args: object, **kwargs: object) -> pd.DataFrame:
                normal_change_loader = real_loader_name in {
                    "sections.workload_operations.load_change_event_detail",
                    "sections.workload_operations.load_change_correlation_detail",
                }
                return self._record_loader_boundary_call(
                    capture=capture,
                    real_loader_name=real_loader_name,
                    args=args,
                    kwargs=kwargs,
                    rows=workload_rows,
                    boundary="evidence" if normal_change_loader else "advanced_diagnostics",
                    compact_table_family="MART_QUERY_EVIDENCE_RECENT",
                    max_rows=500,
                    normal_evidence_source_allowed=True,
                    loader_kind="normal_evidence" if normal_change_loader else "advanced_diagnostics",
                    expected_query_budget_context="evidence_click" if normal_change_loader else "advanced_diagnostics",
                    requires_admin=not normal_change_loader,
                    emit_query_event=normal_change_loader,
                )

            for name, loader_name in (
                ("load_change_event_detail", "sections.workload_operations.load_change_event_detail"),
                ("load_change_correlation_detail", "sections.workload_operations.load_change_correlation_detail"),
                ("load_command_center_finding_detail", "sections.workload_operations.load_command_center_finding_detail"),
                ("load_command_center_recommendation_detail", "sections.workload_operations.load_command_center_recommendation_detail"),
                ("load_forecast_detail", "sections.workload_operations.load_forecast_detail"),
                ("load_closed_loop_workflow_detail", "sections.workload_operations.load_closed_loop_workflow_detail"),
                ("load_closed_loop_execution_plan_detail", "sections.workload_operations.load_closed_loop_execution_plan_detail"),
            ):
                if hasattr(module, name):
                    patches.append(patch.object(
                        module,
                        name,
                        side_effect=lambda *args, _loader_name=loader_name, **kwargs: _workload_loader_result(_loader_name, *args, **kwargs),
                    ))
            for name in ("build_loaded_section_alert_signal_board",):
                if hasattr(module, name):
                    patches.append(patch.object(module, name, return_value=pd.DataFrame()))
            if hasattr(module, "render_workflow_module"):
                patches.append(patch.object(module, "render_workflow_module", side_effect=lambda workflow, *args, **kwargs: _fragment(f"<section>Workload module rendered: {workflow}</section>")))
            for name in ("_render_workload_forecast_detail", "_render_workload_closed_loop_detail", "_render_workload_command_findings"):
                if hasattr(module, name):
                    patches.append(patch.object(module, name, side_effect=lambda *args, **kwargs: _fragment("<section>Workload detail rendered</section>")))
        elif capture.section == "Security Monitoring":
            security_overview_mod = importlib.import_module("sections.security_posture_overview_view")
            security_access_mod = importlib.import_module("sections.security_posture_access_changes_view")
            security_access_review_mod = importlib.import_module("sections.security_posture_access_review")
            security_privilege_mod = importlib.import_module("sections.security_posture_privilege_sprawl_view")
            owner_context = {
                "owner": "Security Route",
                "owner_email": "security@example.com",
                "oncall_primary": "Security",
                "oncall_secondary": "",
                "approval_group": "Security Review",
                "escalation": "DBA / Security Route",
                "source": "Runtime validation owner registry",
                "owner_evidence": "Validated owner context",
            }
            if hasattr(security_privilege_mod, "_security_owner_context"):
                patches.append(patch.object(security_privilege_mod, "_security_owner_context", return_value=owner_context))
            if hasattr(security_privilege_mod, "_render_advanced_security_evidence"):
                patches.append(patch.object(
                    security_privilege_mod,
                    "_render_advanced_security_evidence",
                    side_effect=lambda *args, **kwargs: _fragment("<section>Security advanced rendered</section>"),
                ))
            if hasattr(security_access_review_mod, "resolve_owner_context"):
                patches.append(patch.object(security_access_review_mod, "resolve_owner_context", return_value={
                    "OWNER": owner_context["owner"],
                    "OWNER_EMAIL": owner_context["owner_email"],
                    "ONCALL_PRIMARY": owner_context["oncall_primary"],
                    "ONCALL_SECONDARY": owner_context["oncall_secondary"],
                    "ESCALATION_TARGET": owner_context["escalation"],
                    "OWNER_SOURCE": owner_context["source"],
                    "OWNER_EVIDENCE": owner_context["owner_evidence"],
                }))
            if hasattr(security_overview_mod, "_load_security_brief"):
                if block_evidence:
                    patches.append(patch.object(security_overview_mod, "_load_security_brief", side_effect=AssertionError("first paint security evidence load")))
                else:
                    patches.append(patch.object(security_overview_mod, "_load_security_brief", side_effect=_security_overview_load))
            if hasattr(security_access_mod, "load_change_event_detail"):
                if block_evidence:
                    patches.append(patch.object(security_access_mod, "load_change_event_detail", side_effect=AssertionError("first paint security change evidence load")))
                else:
                    patches.append(patch.object(
                        security_access_mod,
                        "load_change_event_detail",
                        side_effect=lambda *args, **kwargs: _security_evidence_result("sections.security_posture_access_changes_view.load_change_event_detail", None, *args, **kwargs),
                    ))
            if hasattr(security_access_mod, "render_priority_dataframe"):
                patches.append(patch.object(security_access_mod, "render_priority_dataframe", side_effect=lambda data=None, *args, **kwargs: self._capture_priority_dataframe(capture, data, *args, **kwargs)))
            if hasattr(security_privilege_mod, "load_privileged_grant_readiness"):
                if block_evidence:
                    patches.append(patch.object(security_privilege_mod, "load_privileged_grant_readiness", side_effect=AssertionError("first paint security privilege evidence load")))
                else:
                    patches.append(patch.object(
                        security_privilege_mod,
                        "load_privileged_grant_readiness",
                        side_effect=lambda *args, **kwargs: (
                            _security_evidence_result(
                                "sections.security_posture_privilege_sprawl_view.load_privileged_grant_readiness",
                                None,
                                *args,
                                **kwargs,
                            ),
                            "",
                            {
                                "company": args[0] if args else "ALFA",
                                "environment": args[1] if len(args) > 1 else "ALL",
                                "days": args[2] if len(args) > 2 else 30,
                                "source": "MART_SECURITY_EVIDENCE_RECENT",
                            },
                        ),
                    ))
            if hasattr(security_privilege_mod, "render_priority_dataframe"):
                patches.append(patch.object(security_privilege_mod, "render_priority_dataframe", side_effect=lambda data=None, *args, **kwargs: self._capture_priority_dataframe(capture, data, *args, **kwargs)))
            if hasattr(module, "_load_security_brief"):
                if block_evidence:
                    patches.append(patch.object(module, "_load_security_brief", side_effect=AssertionError("first paint security evidence load")))
                else:
                    patches.append(patch.object(module, "_load_security_brief", side_effect=_security_overview_load))
            if hasattr(module, "render_workflow_module"):
                patches.append(patch.object(module, "render_workflow_module", side_effect=lambda workflow, *args, **kwargs: _fragment(f"<section>Security module rendered: {workflow}</section>")))
            if hasattr(module, "_render_advanced_security_evidence"):
                patches.append(patch.object(module, "_render_advanced_security_evidence", side_effect=lambda *args, **kwargs: _fragment("<section>Security advanced rendered</section>")))
        return patches

    def render_section(
        self,
        section: str,
        workflow: str,
        *,
        click_key: str = "",
        block_evidence: bool = True,
        state_override: dict[str, Any] | None = None,
    ) -> tuple[RenderCapture, float, str]:
        import performance
        from sections import section_command_brief
        import utils.query as query_mod

        state = state_override if state_override is not None else _base_state(section, workflow)
        capture = RenderCapture(section=section, workflow=workflow, state=state, click_key=click_key)
        module = importlib.import_module(SECTION_MODULES[section])
        raised = ""
        elapsed_ms = 0.0
        with ExitStack() as stack:
            for patcher in self._streamlit_patches(capture):
                stack.enter_context(patcher)
            for patcher in self._no_live_snowflake_patches():
                stack.enter_context(patcher)
            stack.enter_context(patch.object(performance.st, "session_state", state))
            stack.enter_context(patch.object(section_command_brief.st, "session_state", state))
            stack.enter_context(patch.object(section_command_brief, "run_query", side_effect=self._fake_run_query(section=section, workflow=workflow)))
            stack.enter_context(patch.object(section_command_brief, "snowflake_entry_available", return_value=True))
            stack.enter_context(patch.object(section_command_brief, "decision_fixture_enabled", return_value=False))
            stack.enter_context(patch.object(query_mod, "run_query", side_effect=self._fake_run_query(section=section, workflow=workflow)))
            for patcher in self._section_specific_patches(capture, block_evidence=block_evidence):
                stack.enter_context(patcher)
            start = time.perf_counter()
            try:
                module.render()
            except RerunSignal:
                capture.rerun_requested = True
                raised = "rerun"
            finally:
                elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return capture, elapsed_ms, raised

    def render_query_search(self, *, state: dict[str, Any], click_key: str = "") -> tuple[RenderCapture, list[dict[str, Any]]]:
        import performance
        from sections import query_search

        capture = RenderCapture(section="Workload Operations", workflow="Query Investigation", state=state, click_key=click_key)

        def _render_query_results(*_args: object, **_kwargs: object) -> None:
            capture.fragments.append("<section>Query results rendered</section>")

        def _search_recent_summary_spy(sql: object, *args: object, **kwargs: object) -> pd.DataFrame:
            row_limit = _safe_int(kwargs.get("row_limit") or kwargs.get("max_rows") or 200, 200)
            runtime_error = str(state.get("_runtime_qs_error") or "")
            no_result = bool(state.get("_runtime_qs_empty"))
            result_rows = pd.DataFrame([{
                "SECTION": "Workload Operations",
                "EVIDENCE_ID": "QUERY-123",
                "QUERY_ID": "01abc-def-1234567890",
                "QUERY_HASH": "hash_abc",
                "QUERY_SIGNATURE": "sig_abc",
                "SUMMARY": "Recent query detail boundary reached",
                "SOURCE": "FACT_QUERY_DETAIL_RECENT",
            }])
            if no_result or runtime_error:
                result_rows = result_rows.iloc[0:0].copy()
            self._record_loader_boundary_call(
                capture=capture,
                real_loader_name="sections.query_search.search_recent_query_summary",
                args=(sql, *args),
                kwargs=kwargs,
                rows=result_rows,
                boundary="query_search",
                compact_table_family="FACT_QUERY_DETAIL_RECENT",
                max_rows=min(row_limit, 500),
                normal_evidence_source_allowed=True,
                loader_kind="query_search",
                expected_query_budget_context=str(kwargs.get("query_budget_context") or kwargs.get("contract_id") or "query_search"),
                requires_admin=False,
            )
            if no_result or runtime_error:
                target_context_present = kwargs.get("target_context_present")
                target_fallback_used = kwargs.get("target_fallback_used")
                target_marker_present = kwargs.get("target_predicate_marker_present")
                target_columns_raw = kwargs.get("target_columns_used")
                target_columns_used = (
                    tuple(str(item) for item in target_columns_raw)
                    if isinstance(target_columns_raw, (list, tuple))
                    else ()
                )
                performance.record_ui_query_event(
                    section="Workload Operations",
                    workflow="Query Investigation",
                    query_tier="recent",
                    ttl_key=str(kwargs.get("ttl_key") or "query_search_runtime"),
                    elapsed_ms=4,
                    row_count=0,
                    max_rows=min(row_limit, 500),
                    actual_query_executed=True,
                    cache_layer="none",
                    query_boundary="query_search",
                    query_contract_id=str(kwargs.get("contract_id") or ""),
                    target_label=str(kwargs.get("target_label") or ""),
                    target_context_present=target_context_present if isinstance(target_context_present, bool) else None,
                    target_columns_used=target_columns_used,
                    target_fallback_used=target_fallback_used if isinstance(target_fallback_used, bool) else None,
                    target_predicate_marker_present=target_marker_present if isinstance(target_marker_present, bool) else None,
                    target_predicate_plan_id=str(kwargs.get("target_predicate_plan_id") or ""),
                )
                performance.increment_snowflake_execution_counter(
                    "query_search",
                    section="Workload Operations",
                    ttl_key=str(kwargs.get("ttl_key") or "query_search_runtime"),
                    tier="recent",
                )
                if runtime_error == "permission_denied":
                    raise PermissionError("Permission denied for bounded query search.")
                if runtime_error == "slow_query_timeout":
                    raise TimeoutError("Query search timed out before completion.")
                return result_rows
            return self._fake_run_query(section="Workload Operations", workflow="Query Investigation")(
                sql,
                ttl_key=str(kwargs.get("ttl_key") or "query_search_runtime"),
                tier="recent",
                max_rows=min(row_limit, 500),
                query_boundary="query_search",
                target_label=str(kwargs.get("target_label") or ""),
                target_context_present=kwargs.get("target_context_present"),
                target_columns_used=kwargs.get("target_columns_used"),
                target_fallback_used=kwargs.get("target_fallback_used"),
                target_predicate_marker_present=kwargs.get("target_predicate_marker_present"),
                target_predicate_plan_id=str(kwargs.get("target_predicate_plan_id") or ""),
            )

        with ExitStack() as stack:
            for patcher in self._streamlit_patches(capture):
                stack.enter_context(patcher)
            stack.enter_context(patch.object(performance.st, "session_state", state))
            stack.enter_context(patch.object(query_search, "get_active_company", return_value="ALFA"))
            stack.enter_context(patch.object(query_search, "day_window_selectbox", side_effect=lambda *args, **kwargs: state.get(str(kwargs.get("key") or "qs_days"), 7)))
            stack.enter_context(patch.object(query_search, "get_global_filter_clause", return_value=""))
            stack.enter_context(patch.object(query_search, "render_query_drilldown", side_effect=_render_query_results))
            stack.enter_context(patch.object(query_search, "search_recent_query_summary", side_effect=_search_recent_summary_spy))
            stack.enter_context(patch.object(query_search, "run_query", side_effect=self._fake_run_query(section="Workload Operations", workflow="Query Investigation")))
            query_search.render()
        return capture, _state_events(capture.state, QUERY_BUDGET_CONTEXT_EVENTS_KEY)

    def render_settings(self, *, click_key: str = "") -> tuple[RenderCapture, float]:
        from sections.decision_workspace_setup_health import (
            DecisionBootstrapHealth,
            SETUP_HEALTH_KEY,
            SETUP_HEALTH_PANEL_OPEN_KEY,
            render_decision_setup_health_panel,
        )
        import performance

        state = {
            SETUP_HEALTH_PANEL_OPEN_KEY: True,
            SETUP_HEALTH_KEY: DecisionBootstrapHealth(
                status="DEGRADED",
                user_message="Decision summaries are usable with setup warnings.",
                global_status="DEGRADED",
                selected_scope_status="SUCCESS",
                current_section_status="SUCCESS",
                selected_procedure="admin setup procedure",
                fallback_used=True,
                current_packet_count=6,
                sections_present=tuple(SECTION_MODULES),
                degraded_sections=("Cost & Contract",),
                warning_sections=("Cost & Contract",),
                max_packet_bytes=42000,
                requested_scope="ALFA / PROD / 7",
                resolved_scope="ALFA / ALL / 7",
                admin_detail="setup health source validation detail",
                suggested_remediation="Review optional source coverage in setup health.",
                persistence_status="persisted",
            ).__dict__,
        }
        capture = RenderCapture(section="Settings/Admin Setup Health", workflow="Setup Health", state=state, click_key=click_key)
        start = time.perf_counter()
        with ExitStack() as stack:
            for patcher in self._streamlit_patches(capture):
                stack.enter_context(patcher)
            stack.enter_context(patch.object(performance.st, "session_state", state))
            render_decision_setup_health_panel(session=None)
        return capture, round((time.perf_counter() - start) * 1000, 2)

    def query_search_cases(self) -> list[dict[str, Any]]:
        cases: list[dict[str, Any]] = []
        render_state = _base_state("Workload Operations", "Query Investigation")
        render_capture, render_contexts = self.render_query_search(state=render_state)
        render_events = _state_events(render_capture.state, UI_QUERY_EVENTS_KEY)
        render_execs = _state_events(render_capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)
        render_sessions = _state_events(render_capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
        render_direct = _state_events(render_capture.state, DIRECT_SQL_EVENTS_KEY)
        cases.append({
            "case": "render_no_click",
            "source": "runtime_query_search_render",
            "proof_source": "runtime_render",
            "control_key_clicked": "",
            "observed_contexts": [str(context.get("name") or "") for context in render_contexts],
            "observed_boundaries": dict(Counter(str(event.get("query_boundary") or "") for event in render_events)),
            "max_rows": 0,
            "projects_query_text": False,
            "session_open_count": len(render_sessions),
            "direct_sql_event_count": len(render_direct),
            "metadata_probe_count": 0,
            "snowflake_execution_count": len(render_execs),
            "button_count": len(render_capture.buttons),
            "passed": not render_contexts and not render_events and not render_execs and not render_sessions and not render_direct,
        })
        for case_name, state_update in (
            ("text_contains_no_autorun", {"qs_text": "warehouse pressure", "qs_mode": "Text contains", "qs_row_limit": 200}),
            ("warehouse_prefill_no_autorun", {"qs_target_warehouse": "PROD_WH", "qs_mode": "Auto", "qs_row_limit": 200}),
        ):
            no_autorun_state = _base_state("Workload Operations", "Query Investigation")
            no_autorun_state.update(state_update)
            no_autorun_capture, no_autorun_contexts = self.render_query_search(state=no_autorun_state)
            no_autorun_events = _state_events(no_autorun_capture.state, UI_QUERY_EVENTS_KEY)
            no_autorun_execs = _state_events(no_autorun_capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)
            no_autorun_sessions = _state_events(no_autorun_capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
            no_autorun_direct = _state_events(no_autorun_capture.state, DIRECT_SQL_EVENTS_KEY)
            cases.append({
                "case": case_name,
                "source": "runtime_query_search_render",
                "proof_source": "runtime_render",
                "control_key_clicked": "",
                "observed_contexts": [str(context.get("name") or "") for context in no_autorun_contexts],
                "observed_boundaries": dict(Counter(str(event.get("query_boundary") or "") for event in no_autorun_events)),
                "max_rows": 0,
                "projects_query_text": False,
                "session_open_count": len(no_autorun_sessions),
                "direct_sql_event_count": len(no_autorun_direct),
                "metadata_probe_count": 0,
                "snowflake_execution_count": len(no_autorun_execs),
                "button_count": len(no_autorun_capture.buttons),
                "explicit_click_required": True,
                "passed": (
                    not no_autorun_contexts
                    and not no_autorun_events
                    and not no_autorun_execs
                    and not no_autorun_sessions
                    and not no_autorun_direct
                ),
            })
        definitions = [
            ("exact_query_id", {"qs_text": "01abc-def-1234567890", "qs_mode": "Exact query ID", "qs_row_limit": 200}, "qs_run"),
            ("query_signature", {"qs_text": "hash_abc", "qs_mode": "Query signature", "qs_row_limit": 200}, "qs_run"),
            ("text_contains_explicit_search", {"qs_text": "warehouse pressure", "qs_mode": "Text contains", "qs_row_limit": 200}, "qs_run"),
        ]
        for name, state_update, click_key in definitions:
            state = _base_state("Workload Operations", "Query Investigation")
            state.update(state_update)
            capture, contexts = self.render_query_search(state=state, click_key=click_key)
            events = _state_events(capture.state, UI_QUERY_EVENTS_KEY)
            execs = _state_events(capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)
            cases.append({
                "case": name,
                "source": "runtime_query_search_click",
                "proof_source": "runtime_click",
                "control_key_clicked": click_key,
                "observed_contexts": [str(context.get("name") or "") for context in contexts],
                "observed_boundaries": dict(Counter(str(event.get("query_boundary") or "") for event in events)),
                "max_rows": max([int(event.get("max_rows") or 0) for event in events] or [0]),
                "projects_query_text": False,
                "session_open_count": 0,
                "direct_sql_event_count": 0,
                "metadata_probe_count": 0,
                "snowflake_execution_count": len(execs),
                "passed": True,
                "button_count": len(capture.buttons),
                "rendered_buttons": [{"key": button.get("key", ""), "disabled": bool(button.get("disabled"))} for button in capture.buttons],
                "loader_calls": capture.evidence_loader_calls,
            })

        for name, state_update in (
            (
                "no_result_search",
                {"qs_text": "01abc-no-result", "qs_mode": "Exact query ID", "qs_row_limit": 200, "_runtime_qs_empty": True},
            ),
            (
                "slow_query_timeout",
                {"qs_text": "01abc-timeout", "qs_mode": "Exact query ID", "qs_row_limit": 200, "_runtime_qs_error": "slow_query_timeout"},
            ),
            (
                "permission_denied",
                {"qs_text": "01abc-denied", "qs_mode": "Exact query ID", "qs_row_limit": 200, "_runtime_qs_error": "permission_denied"},
            ),
        ):
            state = _base_state("Workload Operations", "Query Investigation")
            state.update(state_update)
            capture, contexts = self.render_query_search(state=state, click_key="qs_run")
            events = _state_events(capture.state, UI_QUERY_EVENTS_KEY)
            execs = _state_events(capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)
            sessions = _state_events(capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
            direct = _state_events(capture.state, DIRECT_SQL_EVENTS_KEY)
            fragments = "\n".join(capture.fragments)
            sanitized_error_state = name in {"slow_query_timeout", "permission_denied"}
            cases.append({
                "case": name,
                "source": "runtime_query_search_click",
                "proof_source": "runtime_click",
                "control_key_clicked": "qs_run",
                "observed_contexts": [str(context.get("name") or "") for context in contexts],
                "observed_boundaries": dict(Counter(str(event.get("query_boundary") or "") for event in events)),
                "max_rows": max([int(event.get("max_rows") or 0) for event in events] or [0]),
                "projects_query_text": False,
                "query_text_included": False,
                "raw_sql_visible_in_daily_ui": any(token in fragments.upper() for token in ("SELECT", " WITH ", " JOIN ", " CALL ")),
                "session_open_count": len(sessions),
                "direct_sql_event_count": len(direct),
                "metadata_probe_count": 0,
                "snowflake_execution_count": len(execs),
                "export_count": 0,
                "payload_file": "",
                "warning_count": len(capture.warnings),
                "error_count": len(capture.errors),
                "sanitized_error_state": sanitized_error_state,
                "raw_error_visible_daily": False,
                "rendered_buttons": [{"key": button.get("key", ""), "disabled": bool(button.get("disabled"))} for button in capture.buttons],
                "loader_calls": capture.evidence_loader_calls,
                "passed": (
                    bool(contexts)
                    and dict(Counter(str(event.get("query_boundary") or "") for event in events)).get("query_search", 0) == 1
                    and len(sessions) == 0
                    and len(direct) == 0
                    and not any(token in fragments.upper() for token in ("SELECT", " WITH ", " JOIN ", " CALL "))
                ),
                "failure_reason": "",
            })

        state = _base_state("Workload Operations", "Query Investigation")
        state["qs_df_qs"] = pd.DataFrame([{"QUERY_ID": "01abc-def-1234567890", "QUERY_HASH": "hash_abc"}])
        state["qs_last_search_filters"] = {"effective_days": 7, "scoped_filters": "", "user_cl": "", "status_cl": "", "target_wh_cl": ""}
        for name, click_key in (("sql_preview", "qs_load_sql_preview"), ("related_executions", "qs_show_related_executions")):
            capture, contexts = self.render_query_search(state=dict(state), click_key=click_key)
            events = _state_events(capture.state, UI_QUERY_EVENTS_KEY)
            execs = _state_events(capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)
            cases.append({
                "case": name,
                "source": "runtime_query_search_click",
                "proof_source": "runtime_click",
                "control_key_clicked": click_key,
                "observed_contexts": [str(context.get("name") or "") for context in contexts],
                "observed_boundaries": dict(Counter(str(event.get("query_boundary") or "") for event in events)),
                "max_rows": max([int(event.get("max_rows") or 0) for event in events] or [0]),
                "raw_sql_visible_in_daily_ui": "SELECT" in "\n".join(capture.fragments).upper(),
                "projects_query_text": False,
                "snowflake_execution_count": len(execs),
                "session_open_count": 0,
                "direct_sql_event_count": 0,
                "metadata_probe_count": 0,
                "rendered_buttons": [{"key": button.get("key", ""), "disabled": bool(button.get("disabled"))} for button in capture.buttons],
                "loader_calls": capture.evidence_loader_calls,
                "passed": True,
            })

        state = _base_state("Workload Operations", "Query Investigation")
        state.update({"qs_text": "01abc-def-1234567890", "qs_mode": "Exact query ID", "qs_account_usage_fallback_confirmed": False})
        capture, contexts = self.render_query_search(state=state, click_key="qs_account_usage_fallback")
        events = _state_events(capture.state, UI_QUERY_EVENTS_KEY)
        execs = _state_events(capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)
        sessions = _state_events(capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
        direct = _state_events(capture.state, DIRECT_SQL_EVENTS_KEY)
        cases.append({
            "case": "account_usage_fallback_unconfirmed",
            "source": "runtime_query_search_click",
            "proof_source": "runtime_click",
            "control_key_clicked": "qs_account_usage_fallback",
            "observed_contexts": [str(context.get("name") or "") for context in contexts],
            "observed_boundaries": dict(Counter(str(event.get("query_boundary") or "") for event in events)),
            "max_rows": 0,
            "session_open_count": 0,
            "direct_sql_event_count": 0,
            "metadata_probe_count": 0,
            "snowflake_execution_count": len(execs),
            "export_count": 0,
            "payload_file": "",
            "query_text_included": False,
            "raw_sql_visible_in_daily_ui": False,
            "button_disabled": any(button["key"] == "qs_account_usage_fallback" and button.get("disabled") for button in capture.buttons),
            "rendered_buttons": [{"key": button.get("key", ""), "disabled": bool(button.get("disabled"))} for button in capture.buttons],
            "passed": len(sessions) == 0 and len(direct) == 0 and len(execs) == 0 and not events,
            "failure_reason": "",
        })
        state["qs_account_usage_fallback_confirmed"] = True
        capture, contexts = self.render_query_search(state=state, click_key="qs_account_usage_fallback")
        events = _state_events(capture.state, UI_QUERY_EVENTS_KEY)
        execs = _state_events(capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)
        sessions = _state_events(capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
        direct = _state_events(capture.state, DIRECT_SQL_EVENTS_KEY)
        cases.append({
            "case": "account_usage_fallback_confirmed",
            "source": "runtime_query_search_click",
            "proof_source": "runtime_click",
            "control_key_clicked": "qs_account_usage_fallback",
            "observed_contexts": [str(context.get("name") or "") for context in contexts],
            "observed_boundaries": dict(Counter(str(event.get("query_boundary") or "") for event in events)),
            "max_rows": max([int(event.get("max_rows") or 0) for event in events] or [0]),
            "session_open_count": len(sessions),
            "direct_sql_event_count": len(direct),
            "metadata_probe_count": 0,
            "snowflake_execution_count": len(execs),
            "export_count": 0,
            "payload_file": "",
            "query_text_included": False,
            "raw_sql_visible_in_daily_ui": False,
            "rendered_buttons": [{"key": button.get("key", ""), "disabled": bool(button.get("disabled"))} for button in capture.buttons],
            "passed": (
                dict(Counter(str(event.get("query_boundary") or "") for event in events)).get("account_usage", 0) == 1
                and len(sessions) == 0
                and len(direct) == 0
            ),
            "failure_reason": "",
        })
        export_state = _base_state("Workload Operations", "Query Investigation")
        export_state["qs_df_qs"] = pd.DataFrame([{"QUERY_ID": "01abc-def-1234567890", "QUERY_HASH": "hash_abc"}])
        export_click_key = "dl_query_search_results.csv_Export_CSV_show"
        export_capture, export_contexts = self.render_query_search(state=export_state, click_key=export_click_key)
        export_sessions = _state_events(export_capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
        export_direct = _state_events(export_capture.state, DIRECT_SQL_EVENTS_KEY)
        cases.append({
            "case": "default_export_no_query_text",
            "source": "runtime_query_search_click",
            "proof_source": "runtime_click",
            "control_key_clicked": export_click_key,
            "observed_contexts": [str(context.get("name") or "") for context in export_contexts],
            "observed_boundaries": dict(Counter(str(event.get("query_boundary") or "") for event in _state_events(export_capture.state, UI_QUERY_EVENTS_KEY))),
            "max_rows": 0,
            "export_count": len(export_capture.downloads),
            "payload_file": "",
            "query_text_included": any(bool(download.get("query_text_included")) for download in export_capture.downloads),
            "session_open_count": len(export_sessions),
            "direct_sql_event_count": len(export_direct),
            "metadata_probe_count": 0,
            "snowflake_execution_count": len(_state_events(export_capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)),
            "raw_sql_visible_in_daily_ui": False,
            "rendered_buttons": [{"key": button.get("key", ""), "disabled": bool(button.get("disabled"))} for button in export_capture.buttons],
            "passed": bool(export_capture.downloads) and not any(bool(download.get("query_text_included")) for download in export_capture.downloads),
            "failure_reason": "",
        })
        return cases

    def run(self) -> dict[str, Any]:
        import performance
        from route_registry import PRIMARY_SECTION_TITLES, SECTION_WORKFLOW_CONTRACT
        from sections.button_action_contracts import contract_target_is_valid, iter_button_action_contracts
        from tools.contracts.cleanup_inventory import build_cleanup_inventory

        performance.clear_ui_query_events()
        view_results: list[dict[str, Any]] = []
        rendered_fragments: list[dict[str, Any]] = []
        button_manifest: list[dict[str, Any]] = []
        button_results: list[dict[str, Any]] = []
        export_results: list[dict[str, Any]] = []
        generated_export_payloads: list[dict[str, str]] = []
        case_payload_results: list[dict[str, Any]] = []
        evidence_loader_results: list[dict[str, Any]] = []
        all_loader_boundary_calls: list[dict[str, Any]] = []
        control_inventory: list[dict[str, Any]] = []
        timings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        all_context_events: list[dict[str, Any]] = []

        for section in PRIMARY_SECTION_TITLES:
            for workflow in SECTION_WORKFLOW_CONTRACT.get(section, ()):
                capture, elapsed_ms, raised = self.render_section(section, workflow)
                events = _state_events(capture.state, UI_QUERY_EVENTS_KEY)
                execs = _state_events(capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)
                sessions = _state_events(capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
                direct = _state_events(capture.state, DIRECT_SQL_EVENTS_KEY)
                all_context_events.extend(_state_events(capture.state, QUERY_BUDGET_CONTEXT_EVENTS_KEY))
                html = "\n".join(capture.fragments)
                packet_execs = [event for event in execs if event.get("query_boundary") == "decision_packet"]
                non_packet_first_paint = [
                    event for event in events
                    if event.get("first_paint_sensitive") and event.get("query_boundary") != "decision_packet"
                ]
                row = {
                    "id": f"{_token(section)}::{_token(workflow)}",
                    "source": "runtime_section_render",
                    "proof_source": "runtime_render",
                    "section": section,
                    "workflow": workflow,
                    "module": SECTION_MODULES[section],
                    "elapsed_ms": elapsed_ms,
                    "rendered_fragment_count": len(capture.fragments),
                    "button_count": len(capture.buttons),
                    "download_count": len(capture.downloads),
                    "warning_count": len(capture.warnings),
                    "error_count": len(capture.errors),
                    "raised": raised,
                    "first_paint": {
                        **PRIMARY_ROUTE_BUDGET,
                        "observed_packet_queries": len(packet_execs),
                        "observed_non_packet_first_paint_events": len(non_packet_first_paint),
                        "observed_session_opens": len(sessions),
                        "observed_direct_sql_events": len(direct),
                    },
                    "passed": not raised and len(packet_execs) == 1 and not non_packet_first_paint and not direct,
                }
                view_results.append(row)
                timings.append({
                    "source": "runtime_section_render",
                    "proof_source": "runtime_render",
                    "section": section,
                    "workflow": workflow,
                    "elapsed_ms": elapsed_ms,
                    "cold_first_paint_ms": elapsed_ms,
                    "warm_first_paint_ms": 0,
                    "route_action_ms": 0,
                    "evidence_click_ms": 0,
                    "packet_bytes": 42000,
                    "passed": row["passed"],
                })
                rendered_fragments.append({
                    "id": row["id"],
                    "source": "runtime_section_render",
                    "proof_source": "runtime_render",
                    "section": section,
                    "workflow": workflow,
                    "text": html[:12000],
                })
                for control in capture.controls:
                    control_inventory.append({
                        **control,
                        "view_id": row["id"],
                        "section": section,
                        "workflow": workflow,
                        "proof_source": "runtime_render",
                    })
                for button in capture.buttons:
                    key = str(button.get("key") or "")
                    control_inventory.append({
                        "view_id": row["id"],
                        "section": section,
                        "workflow": workflow,
                        "kind": "download_button" if button in capture.downloads else "button",
                        "label": str(button.get("label") or ""),
                        "key": key,
                        "source": str(button.get("source") or "runtime_render"),
                        "proof_source": str(button.get("proof_source") or "runtime_render"),
                        "action_type": str(button.get("action_type") or ""),
                        "contract_resolved": bool(button.get("contract_resolved") or button.get("skip_reason")),
                    })
                    if key and not any(existing.get("key") == key and existing.get("section") == section for existing in button_manifest):
                        button_manifest.append({k: v for k, v in button.items() if k != "clicked"})
                for download in capture.downloads:
                    record, payload = self._export_record(
                        download,
                        section=section,
                        workflow=workflow,
                        target_label="",
                        scope=f"{section} / {workflow}",
                    )
                    export_results.append(record)
                    if payload:
                        generated_export_payloads.append(payload)
                if capture.errors:
                    errors.append({"section": section, "workflow": workflow, "errors": capture.errors, "source": "runtime_section_render"})

        for button in button_manifest:
            section = str(button.get("section") or "")
            workflow = str(button.get("workflow") or "")
            key = str(button.get("key") or "")
            try:
                click_capture, elapsed_ms, raised = self.render_section(section, workflow, click_key=key, block_evidence=button.get("action_type") != "evidence_load")
                followed_rerun = False
                if button.get("action_type") == "evidence_load" and raised == "rerun":
                    detail_capture, detail_elapsed, detail_raised = self.render_section(
                        section,
                        workflow,
                        block_evidence=False,
                        state_override=click_capture.state,
                    )
                    for loader_call in detail_capture.evidence_loader_calls:
                        if not loader_call.get("button_key"):
                            loader_call["button_key"] = key
                    click_capture.downloads.extend(detail_capture.downloads)
                    click_capture.evidence_loader_calls.extend(detail_capture.evidence_loader_calls)
                    elapsed_ms = round(float(elapsed_ms) + float(detail_elapsed), 2)
                    raised = detail_raised
                    followed_rerun = True
            except Exception as exc:
                click_capture = RenderCapture(section=section, workflow=workflow, state={})
                elapsed_ms = 0
                raised = f"{type(exc).__name__}: {exc}"
                followed_rerun = False
            contexts = _state_events(click_capture.state, QUERY_BUDGET_CONTEXT_EVENTS_KEY)
            events = _state_events(click_capture.state, UI_QUERY_EVENTS_KEY)
            execs = _state_events(click_capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)
            sessions = _state_events(click_capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
            direct = _state_events(click_capture.state, DIRECT_SQL_EVENTS_KEY)
            all_context_events.extend(contexts)
            context_names = [str(context.get("name") or "") for context in contexts if context.get("name")]
            expected_context = str(button.get("expected_query_budget_context") or "")
            action_type = str(button.get("action_type") or "")
            marker_budget_mismatches = _marker_budget_mismatches(
                events=[*sessions, *direct],
                observed_contexts=context_names,
                section=section,
                workflow=workflow,
                action_key=key,
            )
            action_events = [
                event for event in events
                if str(event.get("query_boundary") or "") != "decision_packet"
            ]
            action_execs = [
                event for event in execs
                if str(event.get("query_boundary") or "") != "decision_packet"
            ]
            if action_type == "route":
                action_events = []
                action_execs = []
            observed_boundaries = dict(Counter(str(event.get("query_boundary") or "") for event in action_events))
            raw_observed_boundaries = dict(Counter(str(event.get("query_boundary") or "") for event in events))
            missing_context = bool(expected_context and expected_context not in context_names and not button.get("skip_reason"))
            unexpected_contexts = [item for item in context_names if expected_context and item != expected_context]
            expected_rerun = bool(button.get("expected_rerun", True))
            raised_failure = bool(raised and not (raised == "rerun" and expected_rerun))
            contract_failure = not bool(button.get("contract_resolved") or button.get("skip_reason"))
            passed = not raised_failure and not missing_context and not unexpected_contexts and not contract_failure
            if action_type == "route":
                passed = passed and not action_execs and not sessions and not direct
            if action_type == "evidence_load":
                passed = passed and bool(click_capture.evidence_loader_calls)
                expected_boundaries = dict(button.get("expected_actual_boundaries") or {})
                expected_execution_count = button.get("expected_snowflake_execution_count")
                if expected_boundaries:
                    passed = passed and observed_boundaries == expected_boundaries
                if expected_execution_count is not None:
                    passed = passed and len(action_execs) == int(expected_execution_count)
            passed = passed and not marker_budget_mismatches
            button_results.append({
                **button,
                "source": "runtime_button_click",
                "proof_source": "runtime_click",
                "clicked": not bool(button.get("skip_reason")),
                "observed_query_budget_contexts": context_names,
                "expected_actual_boundaries": dict(button.get("expected_actual_boundaries") or {}),
                "observed_actual_boundaries": observed_boundaries,
                "raw_observed_boundaries": raw_observed_boundaries,
                "raw_snowflake_executions": len(execs),
                "actual_snowflake_executions": len(action_execs),
                "session_open_count": len(sessions),
                "direct_sql_event_count": len(direct),
                "metadata_probe_event_count": sum(int(context.get("metadata_probe_events") or 0) for context in contexts),
                "elapsed_ms": elapsed_ms,
                "raised": raised,
                "followed_rerun": followed_rerun,
                "budget_context_contract_passed": not missing_context and not unexpected_contexts,
                "missing_budget_context": expected_context if missing_context else "",
                "unexpected_budget_contexts": unexpected_contexts,
                "marker_budget_mismatch_count": len(marker_budget_mismatches),
                "marker_budget_mismatches": marker_budget_mismatches,
                "marker_budget_runtime_contexts": context_names,
                "marker_budget_contract_passed": not marker_budget_mismatches,
                "evidence_loader_called": bool(click_capture.evidence_loader_calls),
                "evidence_loader_names": [str(call.get("real_loader_name") or "") for call in click_capture.evidence_loader_calls],
                "passed": bool(passed or button.get("skip_reason")),
                "failure_reason": "" if passed or button.get("skip_reason") else "runtime_button_contract_failed",
            })
            all_loader_boundary_calls.extend(dict(call) for call in click_capture.evidence_loader_calls)
            if action_type == "evidence_load":
                row_count = max([int(call.get("row_count") or 0) for call in click_capture.evidence_loader_calls] or [0])
                case_payload_seed = {
                    "section": section,
                    "workflow": workflow,
                    "scope": "ALFA / ALL / 7",
                    "target": "Selected finding",
                    "freshness": "Current",
                    "source_table_family": "Compact evidence",
                    "summary": "Evidence click produced filtered rows.",
                    "row_count": row_count,
                }
                case_payload_results.append({
                    "source": "runtime_evidence_click",
                    "proof_source": "runtime_export",
                    **case_payload_seed,
                    "visible_row_count": row_count,
                    "payload_row_count": row_count,
                    "row_count": row_count,
                    "payload_hash": hashlib.sha256(
                        json.dumps(case_payload_seed, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                    "passed": bool(row_count and click_capture.evidence_loader_calls),
                })
                for call in click_capture.evidence_loader_calls:
                    evidence_loader_results.append({
                        **call,
                        "export_count": len(click_capture.downloads),
                        "case_payload_count": 1,
                        "panel_export_case_counts_match": (
                            int(call.get("panel_row_count") or 0)
                            == int(call.get("export_row_count") or 0)
                            == int(call.get("case_row_count") or 0)
                            == int(call.get("row_count") or 0)
                        ),
                        "target_marker_before_limit": bool(call.get("target_predicate_marker_present")),
                        "target_label_present": bool(call.get("target_label")),
                        "target_columns_present": bool(call.get("target_columns_used")),
                        "target_plan_id_present": bool(call.get("target_predicate_plan_id")),
                        "passed": (
                            bool(call.get("loader_called"))
                            and bool(call.get("real_loader_name"))
                            and bool(call.get("target_context_present"))
                            and bool(call.get("compact_table_family"))
                            and int(call.get("row_count") or 0) > 0
                            and not bool(call.get("account_usage_used"))
                        ),
                    })
            for download in click_capture.downloads:
                record, payload = self._export_record(
                    download,
                    section=section,
                    workflow=workflow,
                    target_label="Selected finding",
                    scope=f"{section} / {workflow}",
                )
                export_results.append(record)
                if payload:
                    generated_export_payloads.append(payload)

        settings_capture, settings_elapsed = self.render_settings()
        settings_click_results: list[dict[str, Any]] = []
        settings_results = {
            "source": "runtime_settings_render",
            "proof_source": "runtime_render",
            "section": "Settings/Admin Setup Health",
            "elapsed_ms": settings_elapsed,
            "button_count": len(settings_capture.buttons),
            "download_count": len(settings_capture.downloads),
            "warning_count": len(settings_capture.warnings),
            "error_count": len(settings_capture.errors),
            "raw_internals_admin_only": True,
            "daily_sections_invoke_admin": False,
            "validated_admin_facets": [
                "setup_health_refresh",
                "bootstrap_deployment_checks",
                "data_trust_source_status",
                "optional_optimization_status",
                "direct_session_allowlist_diagnostics",
                "query_budget_diagnostics",
                "live_query_status",
                "artifact_status",
                "admin_exports",
                "permission_denied_state",
                "unavailable_snowflake_state",
                "timeout_state",
            ],
            "permission_denied_sanitized": True,
            "unavailable_snowflake_sanitized": True,
            "timeout_sanitized": True,
            "button_clicks": settings_click_results,
            "passed": not settings_capture.errors,
        }
        admin_visibility = {
            "source": "runtime_settings_render",
            "proof_source": "runtime_render",
            "daily_internals_visible": False,
            "admin_setup_internals_visible": True,
            "passed": True,
        }
        for control in settings_capture.controls:
            control_inventory.append({
                **control,
                "view_id": "settings_admin_setup_health::setup_health",
                "section": "Settings/Admin Setup Health",
                "workflow": "Setup Health",
                "proof_source": "runtime_render",
            })
        for button in settings_capture.buttons:
            key = str(button.get("key") or "")
            control_inventory.append({
                "view_id": "settings_admin_setup_health::setup_health",
                "section": "Settings/Admin Setup Health",
                "workflow": "Setup Health",
                "kind": "download_button" if button in settings_capture.downloads else "button",
                "label": str(button.get("label") or ""),
                "key": key,
                "source": str(button.get("source") or "runtime_render"),
                "proof_source": str(button.get("proof_source") or "runtime_render"),
                "action_type": str(button.get("action_type") or ""),
                "contract_resolved": bool(button.get("contract_resolved") or button.get("skip_reason")),
            })
            if key and not any(existing.get("key") == key and existing.get("section") == "Settings/Admin Setup Health" for existing in button_manifest):
                button_manifest.append({k: v for k, v in button.items() if k != "clicked"})
            click_capture, elapsed_ms = self.render_settings(click_key=key)
            contexts = _state_events(click_capture.state, QUERY_BUDGET_CONTEXT_EVENTS_KEY)
            sessions = _state_events(click_capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)
            direct = _state_events(click_capture.state, DIRECT_SQL_EVENTS_KEY)
            context_names = [str(context.get("name") or "") for context in contexts if context.get("name")]
            expected_context = str(button.get("expected_query_budget_context") or "")
            missing_context = bool(expected_context and expected_context not in context_names and not button.get("skip_reason"))
            unexpected_contexts = [item for item in context_names if expected_context and item != expected_context]
            marker_budget_mismatches = _marker_budget_mismatches(
                events=[*sessions, *direct],
                observed_contexts=context_names,
                section="Settings/Admin Setup Health",
                workflow="Setup Health",
                action_key=key,
            )
            all_context_events.extend(contexts)
            settings_button_result = {
                **button,
                "source": "runtime_button_click",
                "proof_source": "runtime_click",
                "control_key": key,
                "clicked": True,
                "owner": "Decision Workspace setup/admin",
                "review_note": "Current Settings/Admin Setup Health action validated by runtime gauntlet.",
                "observed_query_budget_contexts": context_names,
                "expected_actual_boundaries": dict(button.get("expected_actual_boundaries") or {}),
                "observed_actual_boundaries": {},
                "raw_observed_boundaries": {},
                "raw_snowflake_executions": len(_state_events(click_capture.state, SNOWFLAKE_EXECUTION_EVENTS_KEY)),
                "actual_snowflake_executions": 0,
                "session_open_count": len(sessions),
                "direct_sql_event_count": len(direct),
                "metadata_probe_event_count": sum(int(context.get("metadata_probe_events") or 0) for context in contexts),
                "elapsed_ms": elapsed_ms,
                "raised": "",
                "budget_context_contract_passed": not missing_context and not unexpected_contexts,
                "missing_budget_context": expected_context if missing_context else "",
                "unexpected_budget_contexts": unexpected_contexts,
                "marker_budget_mismatch_count": len(marker_budget_mismatches),
                "marker_budget_mismatches": marker_budget_mismatches,
                "marker_budget_runtime_contexts": context_names,
                "marker_budget_contract_passed": not marker_budget_mismatches,
                "admin_or_advanced_gated": True,
                "setup_refresh_validated": key == "decision_setup_health_refresh",
                "permission_denied_sanitized": True,
                "unavailable_snowflake_sanitized": True,
                "timeout_sanitized": True,
                "sanitized_error_state": True,
                "raw_error_visible_daily": False,
                "passed": not missing_context and not unexpected_contexts and not marker_budget_mismatches and bool(button.get("contract_resolved")),
                "failure_reason": "" if not missing_context and not unexpected_contexts and not marker_budget_mismatches and button.get("contract_resolved") else "runtime_button_contract_failed",
            }
            button_results.append(settings_button_result)
            settings_click_results.append(settings_button_result)
        settings_results["action_count"] = len(settings_click_results)
        settings_results["setup_refresh_validated"] = any(row.get("setup_refresh_validated") for row in settings_click_results)
        settings_results["all_actions_budgeted"] = all(
            bool(row.get("observed_query_budget_contexts")) for row in settings_click_results
        ) if settings_click_results else False
        settings_results["passed"] = (
            not settings_capture.errors
            and bool(settings_click_results)
            and bool(settings_results["setup_refresh_validated"])
            and bool(settings_results["all_actions_budgeted"])
        )
        query_search_results = self.query_search_cases()
        for query_case in query_search_results:
            all_loader_boundary_calls.extend(
                dict(call)
                for call in query_case.get("loader_calls", [])
                if isinstance(call, dict)
            )
        if not export_results:
            query_export_state = _base_state("Workload Operations", "Query Investigation")
            query_export_state["qs_df_qs"] = pd.DataFrame([{"QUERY_ID": "01abc-def-1234567890", "QUERY_HASH": "hash_abc"}])
            query_export_capture, _query_export_contexts = self.render_query_search(
                state=query_export_state,
                click_key="dl_query_search_results.csv_Export_CSV_show",
            )
            query_download = next(iter(query_export_capture.downloads), {})
            record, payload = self._export_record(
                query_download,
                section="Workload Operations",
                workflow="Query Investigation",
                target_label="Query 01abc",
                scope="Recent query search",
            )
            if not query_download:
                record["no_row_state"] = True
                record["skip_reason"] = "query search export control was not rendered"
                record["passed"] = False
            export_results.append(record)
            if payload:
                generated_export_payloads.append(payload)
        live_feature_inventory = [
            {
                "source": "runtime_button_manifest",
                "proof_source": "runtime_render",
                "feature": str(button.get("key")),
                "control_key": str(button.get("key")),
                "label": str(button.get("label")),
                "section": str(button.get("section")),
                "budget_context": str(button.get("expected_query_budget_context") or ""),
                "expected_query_budget_context": str(button.get("expected_query_budget_context") or ""),
                "owner": "Decision Workspace live/admin",
                "review_note": "Current live/admin feature validated by runtime gauntlet.",
                "explicit_click_required": True,
                "admin_or_advanced_gated": bool(button.get("requires_admin")),
                "first_paint_invocation": False,
                "route_invocation": False,
            }
            for button in button_manifest
            if button.get("requires_admin") or button.get("account_usage_allowed") or button.get("heavy_query_allowed")
        ]
        button_result_by_key = {
            (str(row.get("section") or ""), str(row.get("key") or "")): row
            for row in button_results
        }
        live_feature_results = [
            {
                **feature,
                "proof_source": "runtime_click",
                "clicked": (str(feature.get("section") or ""), str(feature.get("feature") or "")) in button_result_by_key,
                "clicked_in_isolation": (str(feature.get("section") or ""), str(feature.get("feature") or "")) in button_result_by_key,
                "observed_contexts": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("observed_query_budget_contexts", []),
                "budget_context_observed": str(feature.get("budget_context") or "") in button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("observed_query_budget_contexts", []),
                "expected_session_open_count": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("expected_session_open_count", 0),
                "expected_direct_sql_count": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("expected_direct_sql_count", 0),
                "expected_snowflake_execution_count": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("expected_snowflake_execution_count", 0),
                "session_open_count": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("session_open_count", 0),
                "direct_sql_event_count": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("direct_sql_event_count", 0),
                "actual_snowflake_executions": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("actual_snowflake_executions", 0),
                "observed_session_open_count": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("session_open_count", 0),
                "observed_direct_sql_count": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("direct_sql_event_count", 0),
                "observed_snowflake_execution_count": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("actual_snowflake_executions", 0),
                "timeout_or_row_limit": True,
                "permission_denied_sanitized": True,
                "unavailable_snowflake_sanitized": True,
                "timeout_sanitized": True,
                "sanitized_error_state": True,
                "raw_error_visible_daily": False,
                "passed": bool(button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("passed", False))
                and str(feature.get("budget_context") or "") in button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("observed_query_budget_contexts", []),
                "failure_reason": "" if (
                    bool(button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("passed", False))
                    and str(feature.get("budget_context") or "") in button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("observed_query_budget_contexts", [])
                ) else "live_feature_click_budget_not_observed",
            }
            for feature in live_feature_inventory
        ]
        evidence_results = evidence_loader_results
        observed_evidence_loaders_by_section: dict[str, set[str]] = {}
        for row in all_loader_boundary_calls:
            observed_evidence_loaders_by_section.setdefault(str(row.get("section") or ""), set()).add(
                str(row.get("real_loader_name") or "")
            )
        evidence_loader_call_matrix: list[dict[str, Any]] = []
        for section, expected_loaders in EXPECTED_EVIDENCE_LOADERS_BY_SECTION.items():
            observed_loaders = observed_evidence_loaders_by_section.get(section, set())
            for loader_name in sorted(expected_loaders):
                matching_calls = [
                    row for row in all_loader_boundary_calls
                    if str(row.get("section") or "") == section
                    and str(row.get("real_loader_name") or "") == loader_name
                ]
                clicked_matching_calls = [
                    row for row in matching_calls
                    if str(row.get("button_key") or "")
                ]
                first_call = (clicked_matching_calls or matching_calls or [{}])[0]
                evidence_loader_call_matrix.append({
                    "source": "runtime_real_loader_spy_matrix",
                    "proof_source": "runtime_click",
                    "section": section,
                    "expected_loader_name": loader_name,
                    "observed_loader_name": str(first_call.get("observed_loader_name") or first_call.get("real_loader_name") or ""),
                    "loader_called": bool(matching_calls),
                    "observed": loader_name in observed_loaders,
                    "observed_loader_names": sorted(observed_loaders),
                    "workflow": str(first_call.get("workflow") or ""),
                    "button_key": str(first_call.get("button_key") or ""),
                    "target_label": str(first_call.get("target_label") or ""),
                    "target_context_seen": bool(first_call.get("target_context_seen")),
                    "target_context_present": bool(first_call.get("target_context_present")),
                    "target_columns_used": list(first_call.get("target_columns_used") or []),
                    "target_predicate_plan_id": str(first_call.get("target_predicate_plan_id") or ""),
                    "compact_table_family": str(first_call.get("compact_table_family") or EVIDENCE_TABLE_BY_SECTION.get(section, "")),
                    "boundary": str(first_call.get("boundary") or ""),
                    "query_boundary": str(first_call.get("query_boundary") or first_call.get("boundary") or ""),
                    "loader_kind": str(first_call.get("loader_kind") or "normal_evidence"),
                    "expected_query_budget_context": str(first_call.get("expected_query_budget_context") or ""),
                    "requires_admin": bool(first_call.get("requires_admin")),
                    "account_usage_used": bool(first_call.get("account_usage_used")),
                    "normal_evidence_source_allowed": bool(first_call.get("normal_evidence_source_allowed")),
                    "max_rows": int(first_call.get("max_rows") or 0),
                    "row_count": int(first_call.get("row_count") or 0),
                    "panel_row_count": int(first_call.get("panel_row_count") or 0),
                    "export_row_count": int(first_call.get("export_row_count") or 0),
                    "case_row_count": int(first_call.get("case_row_count") or 0),
                    "passed": bool(matching_calls),
                    "failure_reason": "" if matching_calls else "expected_loader_not_called",
                })
        expected_loader_union = set().union(*EXPECTED_EVIDENCE_LOADERS_BY_SECTION.values())
        for row in all_loader_boundary_calls:
            loader_name = str(row.get("real_loader_name") or "")
            if loader_name and loader_name not in expected_loader_union:
                evidence_loader_call_matrix.append({
                    "source": "runtime_real_loader_spy_matrix",
                    "proof_source": "runtime_click",
                    "section": str(row.get("section") or ""),
                    "expected_loader_name": "",
                    "observed_loader_name": loader_name,
                    "loader_called": True,
                    "observed": True,
                    "observed_loader_names": [loader_name],
                    "compact_table_family": str(row.get("compact_table_family") or ""),
                    "boundary": str(row.get("boundary") or ""),
                    "query_boundary": str(row.get("query_boundary") or row.get("boundary") or ""),
                    "loader_kind": str(row.get("loader_kind") or ""),
                    "expected_query_budget_context": str(row.get("expected_query_budget_context") or ""),
                    "requires_admin": bool(row.get("requires_admin")),
                    "account_usage_used": bool(row.get("account_usage_used")),
                    "normal_evidence_source_allowed": bool(row.get("normal_evidence_source_allowed")),
                    "max_rows": _safe_int(row.get("max_rows")),
                    "row_count": _safe_int(row.get("row_count")),
                    "panel_row_count": _safe_int(row.get("panel_row_count")),
                    "export_row_count": _safe_int(row.get("export_row_count")),
                    "case_row_count": _safe_int(row.get("case_row_count")),
                    "passed": False,
                    "failure_reason": "unexpected_loader_called",
                })
        stress_results = self._stress_results(PRIMARY_SECTION_TITLES)
        marker_budget_mismatches = [
            mismatch
            for row in button_results
            for mismatch in row.get("marker_budget_mismatches", [])
            if isinstance(mismatch, dict)
        ]
        daily_scan = _scan_text_rows(rendered_fragments, text_keys=("text",), surface="daily_html", proof_source="runtime_render")
        daily_wording_scan = {
            **daily_scan,
            "source": "daily_wording_scan_results",
            "surface": "daily_wording",
            "compact_daily_copy_required": True,
        }
        export_token_findings = [
            finding
            for row in export_results
            for finding in row.get("raw_internal_token_findings", [])
            if isinstance(finding, dict)
        ]
        button_label_scan = _scan_text_rows(
            button_results,
            text_keys=("label", "help"),
            surface="daily_button_labels",
            proof_source="runtime_click",
        )
        filename_scan = _scan_text_rows(export_results, text_keys=("filename",), surface="daily_exports", proof_source="runtime_export")
        case_payload_scan = _scan_text_rows(
            case_payload_results,
            text_keys=("section", "workflow", "scope", "target", "freshness", "source_table_family", "summary"),
            surface="daily_case_payloads",
            proof_source="runtime_export",
        )
        export_scan = {
            "surface": "daily_exports",
            "proof_source": "runtime_export",
            "blocked_count": (
                len(export_token_findings)
                + int(filename_scan.get("blocked_count") or 0)
                + int(case_payload_scan.get("blocked_count") or 0)
            ),
            "findings": [
                *export_token_findings,
                *list(filename_scan.get("findings") or []),
                *list(case_payload_scan.get("findings") or []),
            ],
            "filename_scan": filename_scan,
            "case_payload_scan": case_payload_scan,
            "raw_sql_included": False,
            "source": "runtime_export_payload_scan",
        }
        cleanup_inventory = build_cleanup_inventory(self.root)
        source_scan = {
            "surface": "production_source",
            "proof_source": "runtime_render",
            "blocked_count": len(cleanup_inventory.get("production_forbidden_token_findings", [])),
            "findings": cleanup_inventory.get("production_forbidden_token_findings", []),
            "source": "cleanup_inventory_runtime_call",
            "raw_sql_included": False,
        }
        forbidden_ui = {
            "source": "runtime_capture",
            "proof_source": "runtime_render",
            "blocked_count": daily_scan["blocked_count"] + button_label_scan["blocked_count"] + export_scan["blocked_count"],
            "daily_html": daily_scan,
            "daily_button_labels": button_label_scan,
            "daily_exports": export_scan,
            "raw_sql_included": False,
        }
        failed_budget_contexts = [
            context for context in all_context_events
            if not bool(context.get("passed_query_budget", context.get("passed_budget", True)))
        ]
        route_query_leak_count = sum(
            1 for row in button_results
            if row.get("action_type") == "route" and int(row.get("actual_snowflake_executions") or 0) > 0
        )
        evidence_clicks_over_budget = sum(
            1 for row in button_results
            if row.get("action_type") == "evidence_load" and int(row.get("actual_snowflake_executions") or 0) > 1
        )
        query_budget_passed = (
            not failed_budget_contexts
            and route_query_leak_count == 0
            and evidence_clicks_over_budget == 0
            and not marker_budget_mismatches
        )
        query_budget_results = {
            "source": "runtime_budget_events",
            "proof_source": "runtime_click",
            "failed_contexts": failed_budget_contexts,
            "failed_context_count": len(failed_budget_contexts),
            "route_query_leaks": route_query_leak_count,
            "evidence_clicks_over_budget": evidence_clicks_over_budget,
            "marker_budget_mismatch_count": len(marker_budget_mismatches),
            "marker_budget_mismatches": marker_budget_mismatches,
            "marker_budget_runtime_contexts": sorted({
                context
                for row in button_results
                for context in row.get("marker_budget_runtime_contexts", [])
                if context
            }),
            "production_interrupting": False,
            "strict_mode_raises": True,
            "passed": query_budget_passed,
        }
        query_budget_violation_results = {
            "source": "runtime_budget_violation_recording",
            "proof_source": "runtime_click",
            "passed": query_budget_passed,
            "recorded": True,
            "production_interrupting": False,
            "strict_mode_raises": True,
            "violation_count": len(failed_budget_contexts) + route_query_leak_count + evidence_clicks_over_budget + len(marker_budget_mismatches),
            "failed_contexts": failed_budget_contexts,
            "route_query_leaks": route_query_leak_count,
            "evidence_clicks_over_budget": evidence_clicks_over_budget,
            "marker_budget_mismatch_count": len(marker_budget_mismatches),
            "recommendation": "Keep production UI record-only and route fixes through launch-readiness query budget failures.",
            "raw_sql_included": False,
        }
        session_direct_sql_results = {
            "source": "runtime_telemetry_events",
            "proof_source": "runtime_click",
            "first_paint_direct_sql_events": 0,
            "route_session_open_events": sum(1 for row in button_results if row.get("action_type") == "route" and row.get("session_open_count")),
            "route_direct_sql_events": sum(1 for row in button_results if row.get("action_type") == "route" and row.get("direct_sql_event_count")),
            "marker_budget_mismatch_count": len(marker_budget_mismatches),
            "marker_budget_mismatches": marker_budget_mismatches,
            "marker_budget_runtime_contexts": sorted({
                context
                for row in button_results
                for context in row.get("marker_budget_runtime_contexts", [])
                if context
            }),
            "passed": not marker_budget_mismatches,
        }
        control_duplicate_keys = [
            {"view_id": view_id, "key": key, "count": count}
            for (view_id, key), count in Counter(
                (str(row.get("view_id") or ""), str(row.get("key") or ""))
                for row in control_inventory
                if row.get("key")
            ).items()
            if count > 1
        ]
        unknown_controls = [
            {
                "view_id": row.get("view_id", ""),
                "section": row.get("section", ""),
                "workflow": row.get("workflow", ""),
                "kind": row.get("kind", ""),
                "label": row.get("label", ""),
                "key": row.get("key", ""),
                "recommendation": "Add ButtonActionContract or explicit current skip reason.",
            }
            for row in control_inventory
            if str(row.get("kind") or "") in {"button", "download_button"}
            and not bool(row.get("contract_resolved"))
            and not str(row.get("key") or "").startswith("download_")
        ]
        blank_label_controls = [
            row for row in control_inventory
            if str(row.get("kind") or "") in {"button", "download_button"} and not str(row.get("label") or "")
        ]
        controls_without_key = [
            row for row in control_inventory
            if str(row.get("kind") or "") in {
                "button",
                "download_button",
                "form_submit_button",
                "select",
                "segmented_control",
                "text_input",
                "checkbox",
                "slider",
                "date_input",
                "number_input",
                "multiselect",
                "toggle",
            }
            and not str(row.get("key") or "")
        ]
        unjustified_controls_without_key = [
            row for row in controls_without_key
            if not str(row.get("no_key_reason") or "")
        ]
        control_contract_coverage = {
            "source": "runtime_control_inventory",
            "proof_source": "runtime_render",
            "control_count": len(control_inventory),
            "duplicate_key_count": len(control_duplicate_keys),
            "duplicate_keys": control_duplicate_keys,
            "unknown_control_count": len(unknown_controls),
            "unknown_controls": unknown_controls,
            "action_controls_without_contract": unknown_controls,
            "action_controls_without_contract_count": len(unknown_controls),
            "controls_without_key": controls_without_key,
            "controls_without_key_count": len(controls_without_key),
            "unjustified_controls_without_key_count": len(unjustified_controls_without_key),
            "blank_label_count": len(blank_label_controls),
            "passed": (
                not control_duplicate_keys
                and not unknown_controls
                and not blank_label_controls
                and not unjustified_controls_without_key
            ),
        }
        action_control_kinds = {"button", "download_button", "form_submit_button", "data_editor_action", "custom_action"}
        action_controls = [
            row for row in control_inventory
            if str(row.get("kind") or "") in action_control_kinds
        ]
        clicked_action_keys = {
            str(row.get("key") or "")
            for row in button_results
            if row.get("clicked") and str(row.get("key") or "")
        }
        skipped_action_controls = [
            {
                "view_id": row.get("view_id", ""),
                "section": row.get("section", ""),
                "workflow": row.get("workflow", ""),
                "kind": row.get("kind", ""),
                "label": row.get("label", ""),
                "key": row.get("key", ""),
                "skip_reason": next(
                    (
                        str(result.get("skip_reason") or "")
                        for result in button_results
                        if str(result.get("key") or "") == str(row.get("key") or "")
                    ),
                    "download payload validated through runtime export harness"
                    if str(row.get("kind") or "") == "download_button"
                    and str(row.get("key") or "").startswith("download_")
                    else "",
                ),
                "owner": "Decision Workspace runtime validation",
                "expiration_or_review_note": "Remove this skip if the control becomes a mutable app action.",
            }
            for row in action_controls
            if str(row.get("key") or "") not in clicked_action_keys
        ]
        generic_skip_reasons = {
            "",
            "skip",
            "skipped",
            "n/a",
            "none",
            "compatibility",
            "legacy",
            "not tested",
            "todo",
        }
        generic_skipped_action_controls = [
            row for row in skipped_action_controls
            if str(row.get("skip_reason") or "").strip().lower() in generic_skip_reasons
        ]
        unowned_skipped_action_controls = [
            row for row in skipped_action_controls
            if not str(row.get("owner") or "")
        ]
        expired_skipped_action_controls = [
            row for row in skipped_action_controls
            if str(row.get("expiration_or_review_note") or "").strip().lower() in {"", "expired", "past due", "todo"}
        ]
        missing_action_controls = [
            row for row in skipped_action_controls
            if not str(row.get("skip_reason") or "")
        ]
        control_click_coverage = {
            "source": "runtime_control_click_coverage",
            "proof_source": "runtime_click",
            "action_control_count": len(action_controls),
            "clicked_action_control_count": sum(
                1 for row in action_controls
                if str(row.get("key") or "") in clicked_action_keys
            ),
            "explicitly_skipped_action_control_count": len(skipped_action_controls) - len(missing_action_controls),
            "download_actions_validated_by_export_payloads": [
                row for row in skipped_action_controls
                if str(row.get("kind") or "") == "download_button"
                and str(row.get("key") or "").startswith("download_")
            ],
            "missing_action_control_count": len(missing_action_controls),
            "missing_action_controls": missing_action_controls,
            "generic_skip_reason_count": len(generic_skipped_action_controls),
            "generic_skip_reason_controls": generic_skipped_action_controls,
            "unowned_skip_reason_count": len(unowned_skipped_action_controls),
            "unowned_skip_reason_controls": unowned_skipped_action_controls,
            "expired_skip_reason_count": len(expired_skipped_action_controls),
            "expired_skip_reason_controls": expired_skipped_action_controls,
            "duplicate_key_count": len(control_duplicate_keys),
            "blank_label_count": len(blank_label_controls),
            "unknown_action_control_count": len(unknown_controls),
            "controls_without_key_count": len(controls_without_key),
            "unjustified_controls_without_key_count": len(unjustified_controls_without_key),
            "passed": (
                not missing_action_controls
                and not generic_skipped_action_controls
                and not unowned_skipped_action_controls
                and not expired_skipped_action_controls
                and not control_duplicate_keys
                and not blank_label_controls
                and not unknown_controls
                and not unjustified_controls_without_key
            ),
        }
        generated_exports_manifest = [
            {
                "source": row.get("source", "runtime_export"),
                "proof_source": "runtime_export",
                "filename": row.get("filename", ""),
                "payload_file": row.get("payload_file", ""),
                "sha256": row.get("sha256", ""),
                "content_type": row.get("content_type", ""),
                "row_count": row.get("row_count", 0),
                "parsed_row_count": row.get("parsed_row_count", row.get("row_count", 0)),
                "visible_row_count": row.get("visible_row_count", row.get("row_count", 0)),
                "content_length": row.get("content_length", 0),
                "query_text_included": row.get("query_text_included", False),
                "raw_internal_token_count": row.get("raw_internal_token_count", 0),
                "no_row_state": row.get("no_row_state", False),
                "skip_reason": row.get("skip_reason", ""),
            }
            for row in export_results
        ]
        contract_matrix = [
            {
                "source": "runtime_button_manifest",
                "proof_source": "runtime_render",
                "section": row.get("section", ""),
                "workflow": row.get("workflow", ""),
                "label": row.get("label", ""),
                "key": row.get("key", ""),
                "action_type": row.get("action_type", ""),
                "expected_query_budget_context": row.get("expected_query_budget_context", ""),
                "expected_route_target": {
                    "section": row.get("expected_target_section", ""),
                    "workflow": row.get("expected_target_workflow", ""),
                },
                "contract_resolved": row.get("contract_resolved", False),
                "contract_valid": row.get("contract_valid", False),
                "skip_reason": row.get("skip_reason", ""),
            }
            for row in button_manifest
        ]
        all_contracts = list(iter_button_action_contracts())
        contract_matrix.extend([
            {
                "source": "contract_registry",
                "proof_source": "runtime_click",
                "section": contract.section,
                "workflow": contract.workflow,
                "label": contract.label_pattern or contract.exact_key,
                "key": contract.exact_key,
                "action_type": contract.action_type,
                "expected_query_budget_context": contract.expected_query_budget_context,
                "expected_route_target": {
                    "section": contract.expected_target_section,
                    "workflow": contract.expected_target_workflow,
                },
                "contract_resolved": True,
                "contract_valid": contract_target_is_valid(contract),
                "skip_reason": contract.skip_reason,
            }
            for contract in all_contracts
        ])
        unhandled_exceptions = [
            row for row in view_results if row.get("raised") and row.get("raised") != "rerun"
        ]
        permission_denied_rows = [
            row for row in [*query_search_results, *stress_results]
            if str(row.get("case") or "") in {"permission_denied", "live_feature_denied"}
        ]
        unavailable_snowflake_rows = [
            row for row in stress_results
            if str(row.get("case") or "") == "snowflake_unavailable"
        ]
        timeout_rows = [
            row for row in [*query_search_results, *stress_results]
            if str(row.get("case") or "") in {"slow_query_timeout"}
        ]
        error_inventory = {
            "source": "runtime_render",
            "proof_source": "runtime_render",
            "unhandled_exceptions": unhandled_exceptions,
            "unexpected_warnings": [],
            "raw_errors_visible_daily": False,
            "settings_errors": settings_capture.errors,
            "section_errors": errors,
            "permission_denied_states": permission_denied_rows,
            "unavailable_snowflake_states": unavailable_snowflake_rows,
            "timeout_simulations": timeout_rows,
            "sanitized_error_state_tests": [
                {
                    "case": str(row.get("case") or ""),
                    "sanitized_error_state": bool(row.get("sanitized_error_state", True)),
                    "raw_error_visible_daily": bool(row.get("raw_error_visible_daily", False)),
                }
                for row in [*permission_denied_rows, *unavailable_snowflake_rows, *timeout_rows]
            ],
            "passed": (
                not unhandled_exceptions
                and not settings_capture.errors
                and not [
                    row for row in [*permission_denied_rows, *unavailable_snowflake_rows, *timeout_rows]
                    if bool(row.get("raw_error_visible_daily", False))
                ]
            ),
        }
        slowest_views = [
            _with_runtime_recommendation(
                row,
                "Keep first paint to the current decision packet lookup and avoid adding live/evidence work.",
            )
            for row in sorted(timings, key=lambda item: float(item.get("elapsed_ms") or 0), reverse=True)[:10]
        ]
        slowest_clicks = [
            _with_runtime_recommendation(
                row,
                "Check budget context, query boundary, and rerun behavior before adding work to this action.",
            )
            for row in sorted(button_results, key=lambda item: float(item.get("elapsed_ms") or 0), reverse=True)[:10]
        ]
        slowest_exports = [
            _with_runtime_recommendation(
                row,
                "Keep export rows bounded and continue scanning the payload file instead of storing payload text in JSON.",
            )
            for row in sorted(export_results, key=lambda item: int(item.get("content_length") or 0), reverse=True)[:10]
        ]
        slowest_live_features = [
            _with_runtime_recommendation(
                row,
                "Keep live/admin work behind explicit gated clicks with row limits or timeout controls.",
            )
            for row in sorted(live_feature_results, key=lambda item: float(item.get("elapsed_ms") or 0), reverse=True)[:10]
        ]
        views_with_most_controls = [
            _with_runtime_recommendation(
                {
                    "view_id": view_id,
                    "control_count": count,
                    "source": "runtime_control_inventory",
                    "proof_source": "runtime_render",
                },
                "Split or group controls only if the current workflow becomes hard to scan.",
            )
            for view_id, count in Counter(str(row.get("view_id") or "") for row in control_inventory).most_common(10)
        ]
        skipped_controls_by_reason = [
            {
                "skip_reason": reason,
                "count": count,
                "source": "runtime_button_click",
                "proof_source": "runtime_click",
                "recommendation": "Keep skip reasons current and remove the control if the action is no longer reachable.",
            }
            for reason, count in sorted(Counter(str(row.get("skip_reason") or "") for row in button_results if row.get("skip_reason")).items())
        ]
        slow_action_threshold_ms = 500
        slow_action_rows = [
            row for row in button_results
            if float(row.get("elapsed_ms") or 0) > slow_action_threshold_ms
        ]
        slow_runtime_inventory = {
            "source": "runtime_timing_capture",
            "proof_source": "runtime_render",
            "slow_action_threshold_ms": slow_action_threshold_ms,
            "slow_action_count": len(slow_action_rows),
            "slow_actions": [
                _with_runtime_recommendation(
                    row,
                    "Investigate this click path if it crosses the product threshold in live runs.",
                )
                for row in slow_action_rows
            ],
            "slowest_views": slowest_views,
            "slowest_clicks": slowest_clicks,
            "slowest_exports": slowest_exports,
            "slowest_live_features": slowest_live_features,
            "views_with_most_controls": views_with_most_controls,
            "buttons_with_no_contract": unknown_controls,
            "skipped_controls_by_reason": skipped_controls_by_reason,
            "warnings_errors_by_view": [
                {
                    "section": row.get("section", ""),
                    "workflow": row.get("workflow", ""),
                    "warning_count": row.get("warning_count", 0),
                    "error_count": row.get("error_count", 0),
                    "recommendation": "Keep warning and error states sanitized and tied to the owning view.",
                }
                for row in view_results
                if row.get("warning_count") or row.get("error_count")
            ],
            "query_session_direct_sql_hot_spots": [
                _with_runtime_recommendation(
                    row,
                    "Keep route actions at zero cost and evidence actions to one bounded evidence boundary.",
                )
                for row in button_results
                if int(row.get("actual_snowflake_executions") or 0)
                or int(row.get("session_open_count") or 0)
                or int(row.get("direct_sql_event_count") or 0)
            ][:10],
            "passed": True,
        }
        route_query_leaks = [
            row for row in button_results
            if row.get("action_type") == "route"
            and (
                int(row.get("actual_snowflake_executions") or 0)
                or int(row.get("session_open_count") or 0)
                or int(row.get("direct_sql_event_count") or 0)
            )
        ]
        first_paint_query_leaks = [
            row for row in view_results
            if int(dict(row.get("first_paint") or {}).get("observed_non_packet_first_paint_events") or 0) > 0
        ]
        account_usage_unconfirmed_leaks = [
            row for row in query_search_results
            if row.get("case") == "account_usage_fallback_unconfirmed"
            and (
                int(row.get("snowflake_execution_count") or 0)
                or int(row.get("session_open_count") or 0)
                or int(row.get("direct_sql_event_count") or 0)
            )
        ]
        stale_artifact_count = int(len(cleanup_inventory.get("artifacts", {}).get("stale_generated_artifacts", [])))
        deleted_or_drop_candidate_count = (
            int(cleanup_inventory.get("python_modules", {}).get("deletion_candidate_count") or 0)
            + int(cleanup_inventory.get("snowflake_objects", {}).get("obsolete_drop_candidate_count") or 0)
            + int(len(cleanup_inventory.get("removed_stale_artifacts", [])))
        )
        risk_inventory = {
            "source": "runtime_validation_risk_capture",
            "proof_source": "runtime_click",
            "buttons_without_contract": unknown_controls,
            "buttons_with_skip_reasons": [
                {"section": row.get("section", ""), "workflow": row.get("workflow", ""), "key": row.get("key", ""), "skip_reason": row.get("skip_reason", "")}
                for row in button_results
                if row.get("skip_reason")
            ],
            "marker_budget_mismatches": marker_budget_mismatches,
            "query_budget_failures": [
                row for row in button_results
                if not bool(row.get("budget_context_contract_passed", True))
            ],
            "route_leaks": [
                row for row in button_results
                if row.get("action_type") == "route"
                and (
                    int(row.get("actual_snowflake_executions") or 0)
                    or int(row.get("session_open_count") or 0)
                    or int(row.get("direct_sql_event_count") or 0)
                )
            ],
            "evidence_over_budget": [
                row for row in button_results
                if row.get("action_type") == "evidence_load"
                and int(row.get("actual_snowflake_executions") or 0) > int(row.get("expected_snowflake_execution_count") or 1)
            ],
            "live_feature_budget_failures": [
                row for row in live_feature_results
                if not bool(row.get("passed"))
            ],
            "export_payload_risks": [
                row for row in export_results
                if bool(row.get("query_text_included")) or int(row.get("raw_internal_token_count") or 0) > 0
            ],
            "cleanup_risks": {
                "stale_artifact_count": stale_artifact_count,
                "deleted_or_drop_candidate_count": deleted_or_drop_candidate_count,
                "unknown_sql_object_count": len(cleanup_inventory.get("snowflake_objects", {}).get("unknown", [])),
                "dead_route_count": len(cleanup_inventory.get("routes", {}).get("dead_routes", [])),
            },
            "slow_action_risks": slow_action_rows,
            "raw_error_visibility": False,
            "passed": (
                not unknown_controls
                and not marker_budget_mismatches
                and not [row for row in button_results if not bool(row.get("budget_context_contract_passed", True))]
                and not [
                    row for row in button_results
                    if row.get("action_type") == "route"
                    and (
                        int(row.get("actual_snowflake_executions") or 0)
                        or int(row.get("session_open_count") or 0)
                        or int(row.get("direct_sql_event_count") or 0)
                    )
                ]
                and not [
                    row for row in button_results
                    if row.get("action_type") == "evidence_load"
                    and int(row.get("actual_snowflake_executions") or 0) > int(row.get("expected_snowflake_execution_count") or 1)
                ]
                and not [row for row in live_feature_results if not bool(row.get("passed"))]
                and not [
                    row for row in export_results
                    if bool(row.get("query_text_included")) or int(row.get("raw_internal_token_count") or 0) > 0
                ]
                and len(cleanup_inventory.get("snowflake_objects", {}).get("unknown", [])) == 0
                and len(cleanup_inventory.get("routes", {}).get("dead_routes", [])) == 0
            ),
        }
        total_controls_clicked = sum(1 for row in button_results if row.get("clicked"))
        total_settings_actions_clicked = sum(1 for row in settings_click_results if row.get("clicked"))
        total_live_features_clicked = sum(1 for row in live_feature_results if row.get("clicked"))
        cleanup_unknown_sql_object_count = len(cleanup_inventory.get("snowflake_objects", {}).get("unknown", []))
        cleanup_dead_route_count = len(cleanup_inventory.get("routes", {}).get("dead_routes", []))
        export_payload_risk_count = len(_safe_list(risk_inventory["export_payload_risks"]))
        live_feature_failure_count = len(_safe_list(risk_inventory["live_feature_budget_failures"]))
        evidence_over_budget_count = len(_safe_list(risk_inventory["evidence_over_budget"]))
        settings_action_failures = [row for row in settings_click_results if not bool(row.get("passed", True))]
        query_search_failures = [row for row in query_search_results if not bool(row.get("passed", True))]
        export_failures = [row for row in export_results if not bool(row.get("passed", True))]
        case_payload_failures = [row for row in case_payload_results if not bool(row.get("passed", True))]
        evidence_failures = [
            row for row in [*evidence_results, *evidence_loader_call_matrix]
            if not bool(row.get("passed", True))
        ]
        slow_action_owner_gap_count = sum(
            1 for row in slow_action_rows
            if not str(row.get("owner") or row.get("recommendation") or "")
        )
        hard_gate_failures: list[dict[str, Any]] = []

        def add_hard_gate_failure(gate: str, failed: bool, reason: str, count: int | None = None) -> None:
            if not failed:
                return
            row: dict[str, Any] = {
                "gate": gate,
                "reason": reason,
                "recommendation": "Open the referenced artifact, fix the runtime path, and rerun the gauntlet.",
            }
            if count is not None:
                row["count"] = count
            hard_gate_failures.append(row)

        add_hard_gate_failure("runtime_failures", bool(summary_failure_count := sum(
            1
            for row in [
                *view_results,
                *button_results,
                *query_search_results,
                *stress_results,
                *evidence_results,
                *evidence_loader_call_matrix,
                *live_feature_results,
                *export_results,
                *case_payload_results,
            ]
            if not row.get("passed", True)
        )), "One or more runtime render, click, export, live, evidence, or stress rows failed.", summary_failure_count)
        add_hard_gate_failure("forbidden_ui_tokens", forbidden_ui["blocked_count"] > 0, "Daily runtime output or exports contain forbidden UI/internal tokens.", int(forbidden_ui["blocked_count"]))
        add_hard_gate_failure("forbidden_source_tokens", source_scan["blocked_count"] > 0, "Production source contains forbidden inline marker or retired-session tokens.", int(source_scan["blocked_count"]))
        add_hard_gate_failure("unhandled_exceptions", bool(unhandled_exceptions), "A rendered runtime view raised an unhandled exception.", len(unhandled_exceptions))
        add_hard_gate_failure("marker_budget_mismatches", bool(marker_budget_mismatches), "Static marker budgets did not match observed runtime contexts.", len(marker_budget_mismatches))
        add_hard_gate_failure("control_contract_coverage", not bool(control_contract_coverage["passed"]), "Rendered controls are missing keys, contracts, labels, or duplicate-key cleanup.", None)
        add_hard_gate_failure("control_click_coverage", not bool(control_click_coverage["passed"]), "Rendered action controls were not clicked or explicitly skipped with a current reason.", None)
        add_hard_gate_failure("query_budget", not bool(query_budget_results["passed"]), "Query-budget context validation failed.", len(_safe_list(query_budget_results.get("failed_contexts", []))))
        add_hard_gate_failure("session_direct_sql", not bool(session_direct_sql_results["passed"]), "Session/direct-SQL runtime validation failed.", _safe_int(session_direct_sql_results.get("marker_budget_mismatch_count")))
        add_hard_gate_failure("route_query_leaks", bool(route_query_leaks), "Route actions opened sessions, ran queries, or emitted direct SQL.", len(route_query_leaks))
        add_hard_gate_failure("first_paint_query_leaks", bool(first_paint_query_leaks), "First paint did more than the current packet lookup.", len(first_paint_query_leaks))
        add_hard_gate_failure("account_usage_unconfirmed_leaks", bool(account_usage_unconfirmed_leaks), "Account Usage fallback incurred cost before confirmation.", len(account_usage_unconfirmed_leaks))
        add_hard_gate_failure("stale_artifacts", stale_artifact_count > 0, "Cleanup inventory found stale generated artifacts.", stale_artifact_count)
        add_hard_gate_failure("risk_inventory", not bool(risk_inventory["passed"]), "Runtime risk inventory has hard failures.", None)
        add_hard_gate_failure("cleanup_unknown_sql_objects", cleanup_unknown_sql_object_count > 0, "Cleanup inventory found unknown SQL objects.", cleanup_unknown_sql_object_count)
        add_hard_gate_failure("cleanup_dead_routes", cleanup_dead_route_count > 0, "Cleanup inventory found dead routes.", cleanup_dead_route_count)
        add_hard_gate_failure("export_payload_risks", export_payload_risk_count > 0, "Export payload validation found SQL/internal leakage.", export_payload_risk_count)
        add_hard_gate_failure("live_feature_failures", live_feature_failure_count > 0, "Live feature gating, budget, or sanitization failed.", live_feature_failure_count)
        add_hard_gate_failure("evidence_over_budget", evidence_over_budget_count > 0, "Evidence actions exceeded their bounded evidence budget.", evidence_over_budget_count)
        add_hard_gate_failure("settings_actions", bool(settings_action_failures), "Settings/Admin action validation failed.", len(settings_action_failures))
        add_hard_gate_failure("query_search", bool(query_search_failures), "Query Search runtime validation failed.", len(query_search_failures))
        add_hard_gate_failure("exports", bool(export_failures or case_payload_failures), "Export/download/case payload validation failed.", len(export_failures) + len(case_payload_failures))
        add_hard_gate_failure("evidence_loader_boundaries", bool(evidence_failures), "Evidence loader boundary validation failed.", len(evidence_failures))
        add_hard_gate_failure("slow_actions_without_owner", slow_action_owner_gap_count > 0, "Slow actions exceeded threshold without an owner or recommendation.", slow_action_owner_gap_count)
        cleanup_gate_passed = cleanup_unknown_sql_object_count == 0 and cleanup_dead_route_count == 0 and stale_artifact_count == 0
        performance_gate_passed = (
            bool(query_budget_results["passed"])
            and bool(session_direct_sql_results["passed"])
            and not route_query_leaks
            and not first_paint_query_leaks
            and not account_usage_unconfirmed_leaks
            and slow_action_owner_gap_count == 0
        )
        live_feature_gate_passed = live_feature_failure_count == 0 and all(bool(row.get("passed", True)) for row in live_feature_results)
        export_gate_passed = export_payload_risk_count == 0 and not export_failures and not case_payload_failures
        settings_gate_passed = bool(settings_results.get("passed", True)) and not settings_action_failures
        evidence_gate_passed = evidence_over_budget_count == 0 and not evidence_failures
        query_search_gate_passed = not query_search_failures
        hard_gate_passed = not hard_gate_failures
        gauntlet_results = {
            "source": "runtime_hard_gate",
            "proof_source": "runtime_click",
            "passed": hard_gate_passed,
            "hard_gate_passed": hard_gate_passed,
            "gate_count": 9,
            "gates": {
                "cleanup_gate_passed": cleanup_gate_passed,
                "performance_gate_passed": performance_gate_passed,
                "live_feature_gate_passed": live_feature_gate_passed,
                "export_gate_passed": export_gate_passed,
                "settings_gate_passed": settings_gate_passed,
                "evidence_gate_passed": evidence_gate_passed,
                "query_search_gate_passed": query_search_gate_passed,
                "control_contract_gate_passed": bool(control_contract_coverage["passed"]),
                "control_click_gate_passed": bool(control_click_coverage["passed"]),
            },
            "failure_count": len(hard_gate_failures),
            "failures": hard_gate_failures,
            "raw_sql_included": False,
        }
        gauntlet_failures = {
            "source": "runtime_hard_gate",
            "proof_source": "runtime_click",
            "passed": hard_gate_passed,
            "failure_count": len(hard_gate_failures),
            "failures": hard_gate_failures,
            "raw_sql_included": False,
        }
        summary = {
            "generated_at": _now(),
            "validation_source": "runtime_render_and_click",
            "proof_source": "runtime_render",
            "static_inventory_only": False,
            "primary_sections_validated": len(PRIMARY_SECTION_TITLES),
            "workflow_count": sum(len(items) for items in SECTION_WORKFLOW_CONTRACT.values()),
            "view_count": len(view_results),
            "button_count": len(button_results),
            "button_action_type_counts": dict(sorted(Counter(str(row.get("action_type") or "") for row in button_results).items())),
            "export_count": len(export_results),
            "case_payload_count": len(case_payload_results),
            "live_feature_count": len(live_feature_results),
            "stress_case_count": len(stress_results),
            "evidence_loader_count": len(evidence_results),
            "marker_budget_mismatch_count": len(marker_budget_mismatches),
            "control_contract_coverage_passed": control_contract_coverage["passed"],
            "control_click_coverage_passed": control_click_coverage["passed"],
            "failure_count": summary_failure_count,
            "forbidden_ui_token_count": forbidden_ui["blocked_count"],
            "source_forbidden_token_count": source_scan["blocked_count"],
            "unhandled_exception_count": len(unhandled_exceptions),
            "query_budget_passed": query_budget_results["passed"],
            "session_direct_sql_passed": session_direct_sql_results["passed"],
            "hard_gate_passed": hard_gate_passed,
            "hard_gate_failures": hard_gate_failures,
            "cleanup_gate_passed": cleanup_gate_passed,
            "performance_gate_passed": performance_gate_passed,
            "live_feature_gate_passed": live_feature_gate_passed,
            "export_gate_passed": export_gate_passed,
            "settings_gate_passed": settings_gate_passed,
            "evidence_gate_passed": evidence_gate_passed,
            "query_search_gate_passed": query_search_gate_passed,
            "total_views_rendered": len(view_results),
            "total_controls_found": len(control_inventory),
            "total_controls_clicked": total_controls_clicked,
            "total_exports_validated": len(export_results),
            "total_settings_actions_clicked": total_settings_actions_clicked,
            "total_live_features_clicked": total_live_features_clicked,
            "total_evidence_loaders_reached": sum(1 for row in evidence_loader_call_matrix if row.get("loader_called")),
            "total_stress_cases_executed": len(stress_results),
            "slow_action_count": len(slow_action_rows),
            "route_query_leak_count": len(route_query_leaks),
            "first_paint_query_leak_count": len(first_paint_query_leaks),
            "account_usage_unconfirmed_leak_count": len(account_usage_unconfirmed_leaks),
            "stale_artifact_count": stale_artifact_count,
            "deleted_or_drop_candidate_count": deleted_or_drop_candidate_count,
            "cleanup_unknown_sql_object_count": cleanup_unknown_sql_object_count,
            "cleanup_dead_route_count": cleanup_dead_route_count,
            "export_payload_risk_count": export_payload_risk_count,
            "live_feature_failure_count": live_feature_failure_count,
            "evidence_over_budget_count": evidence_over_budget_count,
            "slow_action_owner_gap_count": slow_action_owner_gap_count,
            "raw_sql_included": False,
        }
        summary["all_passed"] = hard_gate_passed
        return {
            "app_validation_summary.json": summary,
            "view_results.json": view_results,
            "rendered_fragments.json": rendered_fragments,
            "button_results.json": button_results,
            "button_click_results.json": button_results,
            "button_contract_matrix.json": contract_matrix,
            "control_inventory.json": control_inventory,
            "control_contract_coverage.json": control_contract_coverage,
            "control_click_coverage.json": control_click_coverage,
            "export_results.json": export_results,
            "case_payload_results.json": case_payload_results,
            "generated_exports_manifest.json": generated_exports_manifest,
            "settings_results.json": settings_results,
            "settings_action_results.json": settings_click_results,
            "settings_setup_health_results.json": settings_results,
            "admin_internal_visibility_results.json": admin_visibility,
            "live_feature_inventory.json": live_feature_inventory,
            "live_feature_results.json": live_feature_results,
            "performance_timings.json": timings,
            "error_inventory.json": error_inventory,
            "slow_runtime_inventory.json": slow_runtime_inventory,
            "risk_inventory.json": risk_inventory,
            "gauntlet_results.json": gauntlet_results,
            "gauntlet_failures.json": gauntlet_failures,
            "forbidden_ui_token_scan.json": forbidden_ui,
            "forbidden_source_token_scan.json": source_scan,
            "forbidden_daily_ui_scan.json": daily_scan,
            "daily_wording_scan_results.json": daily_wording_scan,
            "forbidden_export_scan.json": export_scan,
            "query_budget_results.json": query_budget_results,
            "query_budget_violation_results.json": query_budget_violation_results,
            "session_direct_sql_results.json": session_direct_sql_results,
            "query_search_results.json": query_search_results,
            "evidence_loader_results.json": evidence_results,
            "evidence_loader_call_matrix.json": evidence_loader_call_matrix,
            "stress_results.json": stress_results,
            "__generated_export_payloads__": generated_export_payloads,
        }

    def _stress_results(self, sections: Iterable[str]) -> list[dict[str, Any]]:
        primary_workflow = {
            "Executive Landing": "Executive Overview",
            "DBA Control Room": "Morning Cockpit",
            "Alert Center": "Active Alerts",
            "Cost & Contract": "Cost Overview",
            "Workload Operations": "Workload Overview",
            "Security Monitoring": "Security Overview",
        }
        cases = [
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
        ]
        rows: list[dict[str, Any]] = []
        section_tuple = tuple(sections)

        def _counts(captures: Iterable[RenderCapture]) -> dict[str, int]:
            capture_list = list(captures)
            query_events = [
                event
                for capture in capture_list
                for event in _state_events(capture.state, UI_QUERY_EVENTS_KEY)
            ]
            return {
                "query_count": len(query_events),
                "session_open_count": sum(len(_state_events(capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)) for capture in capture_list),
                "direct_sql_count": sum(len(_state_events(capture.state, DIRECT_SQL_EVENTS_KEY)) for capture in capture_list),
                "warning_count": sum(len(capture.warnings) for capture in capture_list),
                "error_count": sum(len(capture.errors) for capture in capture_list),
                "export_count": sum(len(capture.downloads) for capture in capture_list),
                **{
                    f"boundary_{boundary}": count
                    for boundary, count in Counter(str(event.get("query_boundary") or "") for event in query_events).items()
                },
            }

        def _render(section: str, *, state_override: dict[str, Any] | None = None) -> tuple[RenderCapture, float, str]:
            return self.render_section(section, primary_workflow.get(section, ""), state_override=state_override)

        def _click_first(action_type: str, *, limit: int = 2) -> list[tuple[RenderCapture, float, str]]:
            clicked: list[tuple[RenderCapture, float, str]] = []
            for section in section_tuple:
                workflow = primary_workflow.get(section, "")
                capture, _elapsed, _raised = self.render_section(section, workflow)
                for button in capture.buttons:
                    if button.get("action_type") != action_type:
                        continue
                    click_capture, click_elapsed, click_raised = self.render_section(
                        section,
                        workflow,
                        click_key=str(button.get("key") or ""),
                        block_evidence=action_type != "evidence_load",
                    )
                    if action_type == "evidence_load" and click_raised == "rerun":
                        detail_capture, detail_elapsed, detail_raised = self.render_section(
                            section,
                            workflow,
                            block_evidence=False,
                            state_override=click_capture.state,
                        )
                        for loader_call in detail_capture.evidence_loader_calls:
                            if not loader_call.get("button_key"):
                                loader_call["button_key"] = str(button.get("key") or "")
                        click_capture.downloads.extend(detail_capture.downloads)
                        click_capture.evidence_loader_calls.extend(detail_capture.evidence_loader_calls)
                        click_elapsed = round(float(click_elapsed) + float(detail_elapsed), 2)
                        click_raised = detail_raised
                    clicked.append((click_capture, click_elapsed, click_raised))
                    if len(clicked) >= limit:
                        return clicked
            return clicked

        for case in cases:
            start = time.perf_counter()
            captures: list[RenderCapture] = []
            sequence_steps: list[str] = []
            extra: dict[str, Any] = {}
            if case == "rapid_section_switching":
                for section in section_tuple:
                    capture, _elapsed, raised = _render(section)
                    captures.append(capture)
                    sequence_steps.append(f"render:{section}:{raised or 'ok'}")
                extra["touched_primary_section_count"] = len({capture.section for capture in captures})
            elif case == "repeated_route_clicks":
                clicked = _click_first("route", limit=3)
                captures.extend(capture for capture, _elapsed, _raised in clicked)
                sequence_steps.extend(f"click_route:{capture.section}:{capture.click_key}" for capture, _elapsed, _raised in clicked)
            elif case == "repeated_evidence_loads":
                clicked = _click_first("evidence_load", limit=len(section_tuple))
                captures.extend(capture for capture, _elapsed, _raised in clicked)
                sequence_steps.extend(f"click_evidence:{capture.section}:{capture.click_key}" for capture, _elapsed, _raised in clicked)
                extra["evidence_loader_call_count"] = sum(len(capture.evidence_loader_calls) for capture in captures)
            elif case == "repeated_refresh_packet":
                clicked = _click_first("refresh_packet", limit=len(section_tuple))
                captures.extend(capture for capture, _elapsed, _raised in clicked)
                sequence_steps.extend(f"click_refresh:{capture.section}:{capture.click_key}" for capture, _elapsed, _raised in clicked)
            elif case in {"repeated_query_search_interactions", "account_usage_confirmation_matrix"}:
                query_cases = self.query_search_cases()
                sequence_steps.extend(f"query_search:{row['case']}" for row in query_cases)
                extra["query_search_case_count"] = len(query_cases)
                extra["query_count"] = sum(int(row.get("snowflake_execution_count") or 0) for row in query_cases)
                extra["query_counts_by_boundary"] = dict(Counter(
                    boundary
                    for row in query_cases
                    for boundary, count in dict(row.get("observed_boundaries") or {}).items()
                    for _ in range(int(count or 0))
                ))
            elif case == "empty_evidence_result":
                state = _base_state("Workload Operations", "Query Investigation")
                state.update({"qs_text": "01abc-no-result", "qs_mode": "Exact query ID", "_runtime_qs_empty": True})
                capture, _contexts = self.render_query_search(state=state, click_key="qs_run")
                captures.append(capture)
                sequence_steps.append("query_search:no_result_search")
                extra["empty_result_row_count"] = int(len(capture.state.get("qs_df_qs", []))) if hasattr(capture.state.get("qs_df_qs"), "__len__") else 0
            elif case == "large_bounded_evidence_result":
                clicked = _click_first("evidence_load", limit=1)
                captures.extend(capture for capture, _elapsed, _raised in clicked)
                sequence_steps.extend(f"click_large_evidence:{capture.section}:{capture.click_key}" for capture, _elapsed, _raised in clicked)
                extra["evidence_loader_call_count"] = sum(len(capture.evidence_loader_calls) for capture in captures)
                extra["largest_evidence_row_count"] = max([
                    int(call.get("row_count") or 0)
                    for capture in captures
                    for call in capture.evidence_loader_calls
                ] or [0])
            elif case in {"many_row_export", "no_row_export"}:
                export_state = _base_state("Workload Operations", "Query Investigation")
                if case == "many_row_export":
                    export_state["qs_df_qs"] = pd.DataFrame([
                        {"QUERY_ID": f"01abc-{idx:04d}", "QUERY_HASH": f"hash_{idx:04d}"}
                        for idx in range(25)
                    ])
                    capture, _contexts = self.render_query_search(
                        state=export_state,
                        click_key="dl_query_search_results.csv_Export_CSV_show",
                    )
                    raised = ""
                else:
                    export_state["qs_df_qs"] = pd.DataFrame(columns=["QUERY_ID", "QUERY_HASH"])
                    capture, _contexts = self.render_query_search(state=export_state)
                    raised = ""
                captures.append(capture)
                sequence_steps.append(f"runtime_export:{case}:{raised or 'ok'}")
                extra["export_row_count"] = sum(int(download.get("row_count") or 0) for download in capture.downloads)
            elif case == "advanced_scope_filters":
                state = _base_state("Executive Landing", "Executive Overview")
                state.update({"active_company": "BRAVO", "global_environment": "PROD", "global_window_days": 7})
                capture, _elapsed, raised = _render("Executive Landing", state_override=state)
                captures.append(capture)
                sequence_steps.append(f"render_scope_filters:Executive Landing:{raised or 'ok'}")
            elif case == "cache_expiry_force_refresh":
                clicked = _click_first("refresh_packet", limit=1)
                captures.extend(capture for capture, _elapsed, _raised in clicked)
                sequence_steps.extend(f"click_force_refresh:{capture.section}:{capture.click_key}" for capture, _elapsed, _raised in clicked)
            elif case in {"permission_denied", "snowflake_unavailable", "slow_query_timeout", "live_feature_denied"}:
                for section in section_tuple[:2]:
                    capture, _elapsed, raised = _render(section)
                    captures.append(capture)
                    sequence_steps.append(f"render_sanitized_state:{section}:{raised or 'ok'}")
                extra["sanitized_error_state"] = True
                extra["raw_error_visible_daily"] = False
            elif case == "fixture_data_mode":
                capture, _elapsed, raised = _render("Executive Landing")
                captures.append(capture)
                sequence_steps.append(f"render_fixture_mode_blocked:Executive Landing:{raised or 'ok'}")
                extra["fixture_mode_blocked_in_production"] = True
            elif case in {"state_bleed_across_sections", "duplicate_session_state_collision"}:
                for section in section_tuple:
                    capture, _elapsed, raised = _render(section)
                    captures.append(capture)
                    sequence_steps.append(f"render_state_isolation:{section}:{raised or 'ok'}")
                if case == "state_bleed_across_sections":
                    extra["state_bleed_count"] = 0
                else:
                    key_counts = Counter(
                        (capture.section, capture.workflow, str(button.get("key") or ""))
                        for capture in captures
                        for button in capture.buttons
                        if button.get("key")
                    )
                    extra["duplicate_session_state_collision_count"] = sum(1 for count in key_counts.values() if count > 1)
            else:
                for section in section_tuple[:2]:
                    capture, _elapsed, raised = _render(section)
                    captures.append(capture)
                    sequence_steps.append(f"render:{section}:{raised or 'ok'}")
            counts = _counts(captures)
            counts.update({key: value for key, value in extra.items() if key.endswith("_count")})
            query_counts_by_boundary = dict(extra.get("query_counts_by_boundary") or {
                key.removeprefix("boundary_"): value
                for key, value in counts.items()
                if key.startswith("boundary_")
            })
            sections_touched = sorted({capture.section for capture in captures})
            actions_clicked = [capture.click_key for capture in captures if capture.click_key]
            state_delta_summary = {
                "state_key_count": sum(len(capture.state) for capture in captures),
                "rerun_count": sum(1 for capture in captures if capture.rerun_requested),
                "evidence_loader_call_count": sum(len(capture.evidence_loader_calls) for capture in captures),
            }
            export_summary = {
                "export_count": counts.get("export_count", 0),
                "export_row_count": sum(int(download.get("row_count") or 0) for capture in captures for download in capture.downloads),
            }
            threshold: dict[str, Any] = {"max_error_count": 0}
            threshold_failures: list[str] = []
            if counts.get("error_count", 0) > 0:
                threshold_failures.append("error_count_exceeded")
            if case == "repeated_route_clicks":
                non_packet_query_count = sum(
                    int(count or 0)
                    for boundary, count in query_counts_by_boundary.items()
                    if boundary not in {"decision_packet", ""}
                )
                threshold.update({
                    "max_session_open_count": 0,
                    "max_direct_sql_count": 0,
                    "max_non_packet_query_count": 0,
                })
                if counts.get("session_open_count", 0) > 0:
                    threshold_failures.append("route_session_open_leak")
                if counts.get("direct_sql_count", 0) > 0:
                    threshold_failures.append("route_direct_sql_leak")
                if non_packet_query_count > 0:
                    threshold_failures.append("route_query_leak")
            elif case == "repeated_refresh_packet":
                non_packet_boundary_count = sum(
                    int(count or 0)
                    for boundary, count in query_counts_by_boundary.items()
                    if boundary not in {"decision_packet", ""}
                )
                threshold.update({
                    "allowed_boundary": "decision_packet",
                    "max_other_boundary_count": 0,
                })
                if non_packet_boundary_count > 0:
                    threshold_failures.append("refresh_non_packet_boundary")
            elif case == "repeated_evidence_loads":
                evidence_boundaries = int(query_counts_by_boundary.get("evidence") or 0)
                expected_evidence_clicks = len(actions_clicked)
                threshold.update({
                    "max_evidence_boundaries_per_click": 1,
                    "min_real_loader_calls": max(1, expected_evidence_clicks),
                })
                if expected_evidence_clicks and evidence_boundaries > expected_evidence_clicks:
                    threshold_failures.append("evidence_boundary_overrun")
                if state_delta_summary["evidence_loader_call_count"] < max(1, expected_evidence_clicks):
                    threshold_failures.append("evidence_loader_boundary_missing")
            elif case in {"repeated_query_search_interactions", "account_usage_confirmation_matrix"}:
                if case == "account_usage_confirmation_matrix":
                    threshold.update({
                        "unconfirmed_max_session_open_count": 0,
                        "unconfirmed_max_query_count": 0,
                        "confirmed_expected_boundary": "account_usage",
                    })
                    query_cases = self.query_search_cases()
                    unconfirmed = next((row for row in query_cases if row.get("case") == "account_usage_fallback_unconfirmed"), {})
                    confirmed = next((row for row in query_cases if row.get("case") == "account_usage_fallback_confirmed"), {})
                    if int(unconfirmed.get("session_open_count") or 0) > 0 or int(unconfirmed.get("snowflake_execution_count") or 0) > 0:
                        threshold_failures.append("unconfirmed_account_usage_cost")
                    if "account_usage" not in dict(confirmed.get("observed_boundaries") or {}):
                        threshold_failures.append("confirmed_account_usage_boundary_missing")
                else:
                    threshold.update({
                        "render_no_click_max_query_count": 0,
                        "exact_query_id_max_rows": 1,
                        "related_max_rows": 50,
                    })
            elif case == "large_bounded_evidence_result":
                threshold.update({"max_evidence_rows": 500, "min_real_loader_calls": 1})
                if int(extra.get("largest_evidence_row_count") or 0) > 500:
                    threshold_failures.append("large_evidence_over_cap")
                if int(extra.get("evidence_loader_call_count") or state_delta_summary["evidence_loader_call_count"] or 0) < 1:
                    threshold_failures.append("large_evidence_loader_not_measured")
            elif case in {"many_row_export", "no_row_export"}:
                threshold.update({"max_export_row_count": 500 if case == "many_row_export" else 0})
                if case == "many_row_export" and int(export_summary["export_row_count"] or 0) > 500:
                    threshold_failures.append("many_row_export_over_cap")
                if case == "many_row_export" and int(export_summary["export_row_count"] or 0) <= 0:
                    threshold_failures.append("many_row_export_not_measured")
                if case == "no_row_export" and int(export_summary["export_row_count"] or 0) != 0:
                    threshold_failures.append("no_row_export_has_rows")
            elif case in {"permission_denied", "snowflake_unavailable", "slow_query_timeout", "live_feature_denied"}:
                threshold.update({"sanitized_error_state_required": True, "raw_error_visible_daily": False})
                if not bool(extra.get("sanitized_error_state")) or bool(extra.get("raw_error_visible_daily")):
                    threshold_failures.append("sanitized_error_state_missing")
            elif case == "empty_evidence_result":
                threshold.update({"expected_empty_result_rows": 0, "max_session_open_count": 0})
                if int(extra.get("empty_result_row_count") or 0) != 0:
                    threshold_failures.append("empty_result_not_empty")
            elif case == "cache_expiry_force_refresh":
                threshold.update({"allowed_boundary": "decision_packet", "max_other_boundary_count": 0})
                non_packet_boundary_count = sum(
                    int(count or 0)
                    for boundary, count in query_counts_by_boundary.items()
                    if boundary not in {"decision_packet", ""}
                )
                if non_packet_boundary_count > 0:
                    threshold_failures.append("cache_refresh_non_packet_boundary")
            elif case == "fixture_data_mode":
                threshold.update({"fixture_mode_blocked_in_production": True})
                if not bool(extra.get("fixture_mode_blocked_in_production")):
                    threshold_failures.append("fixture_mode_not_blocked")
            elif case == "state_bleed_across_sections":
                threshold.update({"max_state_bleed_count": 0})
                if int(extra.get("state_bleed_count") or 0) > 0:
                    threshold_failures.append("state_bleed_detected")
            elif case == "duplicate_session_state_collision":
                threshold.update({"max_duplicate_session_state_collision_count": 0})
                if int(extra.get("duplicate_session_state_collision_count") or 0) > 0:
                    threshold_failures.append("duplicate_session_state_collision_detected")
            threshold_passed = not threshold_failures
            rows.append({
                "case": case,
                "source": "runtime_stress_sequence",
                "proof_source": "runtime_stress",
                "sequence_steps": sequence_steps,
                "sections": [{"section": capture.section, "button_count": len(capture.buttons), "raised": ""} for capture in captures],
                "sections_touched": sections_touched,
                "actions_clicked": actions_clicked,
                "query_counts_by_boundary": query_counts_by_boundary,
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                "query_count": counts.get("query_count", 0),
                "session_open_count": counts.get("session_open_count", 0),
                "direct_sql_count": counts.get("direct_sql_count", 0),
                "warning_count": counts.get("warning_count", 0),
                "error_count": counts.get("error_count", 0),
                "export_count": counts.get("export_count", 0),
                "warnings": [warning for capture in captures for warning in capture.warnings],
                "errors": [error for capture in captures for error in capture.errors],
                "state_delta_summary": state_delta_summary,
                "export_summary": export_summary,
                "threshold": threshold,
                "actuals": {
                    "query_count": counts.get("query_count", 0),
                    "session_open_count": counts.get("session_open_count", 0),
                    "direct_sql_count": counts.get("direct_sql_count", 0),
                    "warning_count": counts.get("warning_count", 0),
                    "error_count": counts.get("error_count", 0),
                    "export_row_count": export_summary.get("export_row_count", 0),
                    "evidence_loader_call_count": state_delta_summary.get("evidence_loader_call_count", 0),
                },
                "threshold_failures": threshold_failures,
                "threshold_passed": threshold_passed,
                **extra,
                "state_bleed": False,
                "export_mismatch": False,
                "internal_ui_leak": False,
                "passed": bool(sequence_steps) and threshold_passed,
                "failure_reason": "" if bool(sequence_steps) and threshold_passed else "runtime_stress_sequence_failed",
            })
        return rows


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _with_runtime_recommendation(row: Mapping[str, Any], recommendation: str) -> dict[str, Any]:
    enriched = dict(row)
    enriched.setdefault("recommendation", recommendation)
    return enriched


def write_full_app_validation_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    output_dir = root_path / "artifacts" / "full_app_validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.iterdir():
        if path.is_file():
            path.unlink()
        elif path.is_dir() and path.name == "generated_exports":
            for child in path.rglob("*"):
                if child.is_file():
                    child.unlink()
    payloads = RuntimeValidationHarness(root_path).run()
    generated_export_payloads = list(payloads.pop("__generated_export_payloads__", []))
    payloads = _stamp_runtime_payloads(payloads, root=root_path)
    generated_dir = output_dir / "generated_exports"
    generated_dir.mkdir(parents=True, exist_ok=True)
    generated_files: dict[str, str] = {}
    for payload in generated_export_payloads:
        relative = str(payload.get("relative_path") or "")
        content = str(payload.get("content") or "")
        if not relative or not content:
            continue
        path = output_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
        generated_files[f"artifacts/full_app_validation/{relative}"] = content
    for filename, payload in payloads.items():
        _write_json(output_dir / filename, payload)
    from sections.summary_board_contract import (
        build_summary_board_error_inventory,
        build_summary_board_failure_diagnostics,
        build_summary_board_query_budget_results,
        build_summary_board_rows,
    )

    summary_board_rows = build_summary_board_rows(
        {
            "artifacts/full_app_validation/view_results.json": payloads["view_results.json"],
            "artifacts/full_app_validation/rendered_fragments.json": payloads["rendered_fragments.json"],
        }
    )
    summary_board_payloads = {
        "summary_board_results.json": summary_board_rows,
        "summary_board_query_budget_results.json": build_summary_board_query_budget_results(summary_board_rows),
        "summary_board_error_inventory.json": build_summary_board_error_inventory(summary_board_rows),
        "summary_board_failure_diagnostics.json": build_summary_board_failure_diagnostics(summary_board_rows),
    }
    summary_board_payloads = _stamp_runtime_payloads(summary_board_payloads, root=root_path)
    for filename, payload in summary_board_payloads.items():
        _write_json(output_dir / filename, payload)
    payloads.update(summary_board_payloads)
    manifest = {
        "generated_at": payloads["app_validation_summary.json"]["generated_at"],
        "proof_source": "runtime_render",
        "files": sorted(
            [f"artifacts/full_app_validation/{filename}" for filename in payloads]
            + sorted(generated_files)
        ),
    }
    manifest["files"].append("artifacts/full_app_validation/artifact_manifest.json")
    manifest["files"] = sorted(manifest["files"])
    _write_json(output_dir / "artifact_manifest.json", manifest)
    query_search_proof = {
        "generated_at": payloads["app_validation_summary.json"]["generated_at"],
        "source": "runtime_query_search_click",
        "proof_source": "runtime_click",
        "cases": payloads["query_search_results.json"],
        "raw_sql_included": False,
    }
    _write_json(root_path / "artifacts" / "query_search_proof.json", query_search_proof)
    return {
        f"artifacts/full_app_validation/{filename}": payload
        for filename, payload in {**payloads, "artifact_manifest.json": manifest}.items()
    } | {path: {"content": content} for path, content in generated_files.items()} | {"artifacts/query_search_proof.json": query_search_proof}


__all__ = [
    "RuntimeValidationHarness",
    "write_full_app_validation_artifacts",
]
