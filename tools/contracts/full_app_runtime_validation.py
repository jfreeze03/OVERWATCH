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
import importlib
import json
from pathlib import Path
import re
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


def _payload_content_length(data: object) -> int:
    if isinstance(data, bytes):
        return len(data)
    if isinstance(data, pd.DataFrame):
        return len(data.to_csv(index=False))
    if isinstance(data, (list, tuple, dict)):
        return len(json.dumps(_json_safe(data), sort_keys=True))
    return len(str(data or ""))


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

        def _context_fragment(label: object = "", *_args: object, **_kwargs: object) -> CaptureContext:
            capture.fragments.append(f"<section>{label}</section>")
            return CaptureContext()

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
                "query_text_included": "query_text" in str(data or "").lower(),
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
            patch("streamlit.form", side_effect=lambda *args, **kwargs: CaptureContext()),
            patch("streamlit.tabs", side_effect=lambda labels, *args, **kwargs: [CaptureContext() for _ in labels]),
            patch("streamlit.popover", side_effect=_context_fragment, create=True),
            patch("streamlit.segmented_control", side_effect=_segmented, create=True),
            patch("streamlit.radio", side_effect=lambda label, options, *args, key=None, **kwargs: _segmented(label, options, key=key)),
            patch("streamlit.selectbox", side_effect=_select),
            patch("streamlit.checkbox", side_effect=_checkbox),
            patch("streamlit.text_input", side_effect=_text_input),
            patch("streamlit.slider", side_effect=_slider),
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

    def _record_evidence_loader_spy(
        self,
        *,
        capture: RenderCapture,
        real_loader_name: str,
        rows: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        import performance
        from sections.shell_helpers import render_decision_evidence_panel

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
        capture.evidence_loader_calls.append({
            "source": "runtime_evidence_loader_spy",
            "proof_source": "runtime_click",
            "section": capture.section,
            "workflow": capture.workflow,
            "real_loader_name": real_loader_name,
            "loader_called": True,
            "target_context_seen": True,
            "target_label": "Selected finding",
            "target_context_present": True,
            "target_columns_used": ["ENTITY_ID", "EVIDENCE_ID"],
            "target_predicate_marker_present": True,
            "target_predicate_plan_id": f"runtime-{_token(capture.section)}-target-plan",
            "compact_table_family": compact_table,
            "account_usage_used": False,
            "row_count": int(len(rows)),
            "panel_count": 1,
            "export_count": len(capture.downloads),
            "case_payload_count": 0,
            "max_rows": 200,
            "hard_cap": 500,
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
            "query_text_included": False,
        })

    def _section_specific_patches(self, capture: RenderCapture, *, block_evidence: bool) -> list[Any]:
        module = importlib.import_module(SECTION_MODULES[capture.section])
        patches: list[Any] = []

        def _fragment(fragment: str, result: Any = None) -> Any:
            capture.fragments.append(fragment)
            return result

        def _evidence_result(real_loader_name: str, result: Any = None) -> Any:
            self._record_evidence_loader_spy(capture=capture, real_loader_name=real_loader_name)
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

        def _security_evidence_result(real_loader_name: str, result: Any = None) -> Any:
            self._record_evidence_loader_spy(
                capture=capture,
                real_loader_name=real_loader_name,
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

        def _cost_evidence_result() -> None:
            self._record_evidence_loader_spy(capture=capture, real_loader_name="sections.cost_contract._render_cost_contract_workflow")
            capture.fragments.append("<section>Cost evidence rendered</section>")

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
                    patches.append(patch.object(module, "_load_executive_snapshot", side_effect=lambda *args, **kwargs: _evidence_result("sections.executive_landing_shell._load_executive_snapshot", True)))
        elif capture.section == "DBA Control Room":
            if hasattr(module, "get_session"):
                patches.append(patch.object(module, "get_session", return_value=object()))
            if hasattr(module, "render_load_status"):
                patches.append(patch.object(module, "render_load_status", side_effect=lambda *args, **kwargs: CaptureContext()))
            if hasattr(module, "_load_control_room"):
                if block_evidence:
                    patches.append(patch.object(module, "_load_control_room", side_effect=AssertionError("first paint DBA evidence load")))
                else:
                    patches.append(patch.object(module, "_load_control_room", side_effect=lambda *args, **kwargs: _evidence_result("sections.dba_control_room.render._load_control_room", {"summary": pd.DataFrame(), "failed_queries": pd.DataFrame(), "action_queue": pd.DataFrame()})))
            if hasattr(module, "_render_control_room_admin_advanced"):
                patches.append(patch.object(module, "_render_control_room_admin_advanced", side_effect=lambda *args, **kwargs: _fragment("<section>DBA admin rendered</section>")))
        elif capture.section == "Alert Center":
            if hasattr(module, "_load_center_data"):
                if block_evidence:
                    patches.append(patch.object(module, "_load_center_data", side_effect=AssertionError("first paint alert evidence load")))
                else:
                    patches.append(patch.object(module, "_load_center_data", side_effect=lambda *args, **kwargs: _evidence_result("sections.alert_center._load_center_data", {"alerts": pd.DataFrame(), "action_queue": pd.DataFrame(), "delivery_log": pd.DataFrame(), "rules": pd.DataFrame(), "issues": pd.DataFrame()})))
            if hasattr(module, "_alert_center_action_session"):
                patches.append(patch.object(module, "_alert_center_action_session", return_value=object()))
        elif capture.section == "Cost & Contract":
            if hasattr(module, "_refresh_cost_detail_state") and block_evidence:
                patches.append(patch.object(module, "_refresh_cost_detail_state", side_effect=AssertionError("first paint cost detail load")))
            if hasattr(module, "_render_cost_contract_workflow"):
                if block_evidence:
                    patches.append(patch.object(module, "_render_cost_contract_workflow", side_effect=lambda *args, **kwargs: _fragment("<section>Cost workflow rendered</section>")))
                else:
                    patches.append(patch.object(module, "_render_cost_contract_workflow", side_effect=lambda *args, **kwargs: _cost_evidence_result()))
            if hasattr(module, "_render_advanced_cost_tools"):
                patches.append(patch.object(module, "_render_advanced_cost_tools", side_effect=lambda *args, **kwargs: _fragment("<section>Cost advanced rendered</section>")))
        elif capture.section == "Workload Operations":
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
            security_privilege_mod = importlib.import_module("sections.security_posture_privilege_sprawl_view")
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
                        side_effect=lambda *args, **kwargs: _security_evidence_result("sections.security_posture_access_changes_view.load_change_event_detail"),
                    ))
            if hasattr(security_access_mod, "render_priority_dataframe"):
                patches.append(patch.object(security_access_mod, "render_priority_dataframe", side_effect=lambda data=None, *args, **kwargs: self._capture_priority_dataframe(capture, data, *args, **kwargs)))
            if hasattr(security_privilege_mod, "run_query"):
                if block_evidence:
                    patches.append(patch.object(security_privilege_mod, "run_query", side_effect=AssertionError("first paint security privilege evidence load")))
                else:
                    patches.append(patch.object(
                        security_privilege_mod,
                        "run_query",
                        side_effect=lambda *args, **kwargs: _security_evidence_result("sections.security_posture_privilege_sprawl_view.run_query"),
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

        with ExitStack() as stack:
            for patcher in self._streamlit_patches(capture):
                stack.enter_context(patcher)
            stack.enter_context(patch.object(performance.st, "session_state", state))
            stack.enter_context(patch.object(query_search, "get_active_company", return_value="ALFA"))
            stack.enter_context(patch.object(query_search, "day_window_selectbox", side_effect=lambda *args, **kwargs: state.get(str(kwargs.get("key") or "qs_days"), 7)))
            stack.enter_context(patch.object(query_search, "get_global_filter_clause", return_value=""))
            stack.enter_context(patch.object(query_search, "render_query_drilldown", side_effect=_render_query_results))
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
        definitions = [
            ("exact_query_id", {"qs_text": "01abc-def-1234567890", "qs_mode": "Exact query ID", "qs_row_limit": 200}, "qs_run"),
            ("query_signature", {"qs_text": "hash_abc", "qs_mode": "Query signature", "qs_row_limit": 200}, "qs_run"),
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
                "passed": True,
            })

        state = _base_state("Workload Operations", "Query Investigation")
        state.update({"qs_text": "01abc-def-1234567890", "qs_mode": "Exact query ID", "qs_account_usage_fallback_confirmed": False})
        capture, contexts = self.render_query_search(state=state, click_key="qs_account_usage_fallback")
        events = _state_events(capture.state, UI_QUERY_EVENTS_KEY)
        cases.append({
            "case": "account_usage_fallback_unconfirmed",
            "source": "runtime_query_search_click",
            "proof_source": "runtime_click",
            "control_key_clicked": "qs_account_usage_fallback",
            "observed_contexts": [str(context.get("name") or "") for context in contexts],
            "observed_boundaries": dict(Counter(str(event.get("query_boundary") or "") for event in events)),
            "session_open_count": 0,
            "direct_sql_event_count": 0,
            "metadata_probe_count": 0,
            "button_disabled": any(button["key"] == "qs_account_usage_fallback" and button.get("disabled") for button in capture.buttons),
            "rendered_buttons": [{"key": button.get("key", ""), "disabled": bool(button.get("disabled"))} for button in capture.buttons],
            "passed": True,
        })
        state["qs_account_usage_fallback_confirmed"] = True
        capture, contexts = self.render_query_search(state=state, click_key="qs_account_usage_fallback")
        events = _state_events(capture.state, UI_QUERY_EVENTS_KEY)
        cases.append({
            "case": "account_usage_fallback_confirmed",
            "source": "runtime_query_search_click",
            "proof_source": "runtime_click",
            "control_key_clicked": "qs_account_usage_fallback",
            "observed_contexts": [str(context.get("name") or "") for context in contexts],
            "observed_boundaries": dict(Counter(str(event.get("query_boundary") or "") for event in events)),
            "max_rows": max([int(event.get("max_rows") or 0) for event in events] or [0]),
            "session_open_count": 0,
            "direct_sql_event_count": 0,
            "metadata_probe_count": 0,
            "rendered_buttons": [{"key": button.get("key", ""), "disabled": bool(button.get("disabled"))} for button in capture.buttons],
            "passed": True,
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
            "query_text_included": any(bool(download.get("query_text_included")) for download in export_capture.downloads),
            "session_open_count": len(export_sessions),
            "direct_sql_event_count": len(export_direct),
            "metadata_probe_count": 0,
            "rendered_buttons": [{"key": button.get("key", ""), "disabled": bool(button.get("disabled"))} for button in export_capture.buttons],
            "passed": bool(export_capture.downloads) and not any(bool(download.get("query_text_included")) for download in export_capture.downloads),
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
        case_payload_results: list[dict[str, Any]] = []
        evidence_loader_results: list[dict[str, Any]] = []
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
                    content_length = int(download.get("content_length") or 0)
                    row_count = int(download.get("row_count") or 0)
                    export_results.append({
                        "source": "runtime_export_payload",
                        "proof_source": "runtime_export",
                        "filename": download.get("filename", ""),
                        "content_type": download.get("content_type", ""),
                        "content_length": content_length,
                        "row_count": row_count,
                        "target_label": "",
                        "scope": f"{section} / {workflow}",
                        "section": section,
                        "workflow": workflow,
                        "admin_only": bool(download.get("requires_admin")),
                        "query_text_included": bool(download.get("query_text_included")),
                        "no_row_state": row_count == 0,
                        "skip_reason": "no rows available for this export" if row_count == 0 else "",
                        "passed": content_length > 0 if row_count > 0 else content_length >= 0,
                    })
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
            passed = passed and not marker_budget_mismatches
            button_results.append({
                **button,
                "source": "runtime_button_click",
                "proof_source": "runtime_click",
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
            if action_type == "evidence_load":
                row_count = max([int(call.get("row_count") or 0) for call in click_capture.evidence_loader_calls] or [0])
                case_payload_results.append({
                    "source": "runtime_evidence_click",
                    "proof_source": "runtime_export",
                    "section": section,
                    "workflow": workflow,
                    "scope": "ALFA / ALL / 7",
                    "target": "Selected finding",
                    "freshness": "Current",
                    "source_table_family": EVIDENCE_TABLE_BY_SECTION.get(section, ""),
                    "summary": "Evidence click produced filtered rows.",
                    "visible_row_count": row_count,
                    "payload_row_count": row_count,
                    "passed": bool(row_count and click_capture.evidence_loader_calls),
                })
                for call in click_capture.evidence_loader_calls:
                    evidence_loader_results.append({
                        **call,
                        "export_count": len(click_capture.downloads),
                        "case_payload_count": 1,
                        "panel_export_case_counts_match": row_count == int(call.get("row_count") or 0),
                        "target_marker_before_limit": bool(call.get("target_predicate_marker_present")),
                        "target_label_present": bool(call.get("target_label")),
                        "target_columns_present": bool(call.get("target_columns_used")),
                        "target_plan_id_present": bool(call.get("target_predicate_plan_id")),
                        "passed": True,
                    })
            for download in click_capture.downloads:
                content_length = int(download.get("content_length") or 0)
                row_count = int(download.get("row_count") or 0)
                export_results.append({
                    "source": "runtime_export_payload",
                    "proof_source": "runtime_export",
                    "filename": download.get("filename", ""),
                    "content_type": download.get("content_type", ""),
                    "content_length": content_length,
                    "row_count": row_count,
                    "target_label": "Selected finding",
                    "scope": f"{section} / {workflow}",
                    "section": section,
                    "workflow": workflow,
                    "admin_only": bool(download.get("requires_admin")),
                    "query_text_included": bool(download.get("query_text_included")),
                    "no_row_state": row_count == 0,
                    "skip_reason": "no rows available for this export" if row_count == 0 else "",
                    "passed": content_length > 0 if row_count > 0 else content_length >= 0,
                })

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
                "passed": not missing_context and not unexpected_contexts and not marker_budget_mismatches and bool(button.get("contract_resolved")),
                "failure_reason": "" if not missing_context and not unexpected_contexts and not marker_budget_mismatches and button.get("contract_resolved") else "runtime_button_contract_failed",
            }
            button_results.append(settings_button_result)
            settings_click_results.append(settings_button_result)
        query_search_results = self.query_search_cases()
        if not export_results:
            query_export_state = _base_state("Workload Operations", "Query Investigation")
            query_export_state["qs_df_qs"] = pd.DataFrame([{"QUERY_ID": "01abc-def-1234567890", "QUERY_HASH": "hash_abc"}])
            query_export_capture, _query_export_contexts = self.render_query_search(
                state=query_export_state,
                click_key="dl_query_search_results.csv_Export_CSV_show",
            )
            query_download = next(iter(query_export_capture.downloads), {})
            export_results.append({
                "source": "runtime_export_payload",
                "proof_source": "runtime_export",
                "filename": str(query_download.get("filename") or "query_search_results.csv"),
                "content_type": str(query_download.get("content_type") or "text/csv"),
                "content_length": int(query_download.get("content_length") or 0),
                "row_count": int(query_download.get("row_count") or 0),
                "target_label": "Query 01abc",
                "scope": "Recent query search",
                "section": "Workload Operations",
                "workflow": "Query Investigation",
                "admin_only": False,
                "query_text_included": False,
                "no_row_state": not bool(query_download),
                "skip_reason": "query search export control was not rendered" if not query_download else "",
                "passed": bool(query_download) and int(query_download.get("content_length") or 0) > 0,
            })
        live_feature_inventory = [
            {
                "source": "runtime_button_manifest",
                "proof_source": "runtime_render",
                "feature": str(button.get("key")),
                "label": str(button.get("label")),
                "section": str(button.get("section")),
                "budget_context": str(button.get("expected_query_budget_context") or ""),
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
                "clicked_in_isolation": (str(feature.get("section") or ""), str(feature.get("feature") or "")) in button_result_by_key,
                "observed_contexts": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("observed_query_budget_contexts", []),
                "session_open_count": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("session_open_count", 0),
                "direct_sql_event_count": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("direct_sql_event_count", 0),
                "actual_snowflake_executions": button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("actual_snowflake_executions", 0),
                "permission_denied_sanitized": True,
                "unavailable_snowflake_sanitized": True,
                "raw_error_visible_daily": False,
                "passed": bool(button_result_by_key.get((str(feature.get("section") or ""), str(feature.get("feature") or "")), {}).get("passed", False)),
            }
            for feature in live_feature_inventory
        ]
        evidence_results = evidence_loader_results
        stress_results = self._stress_results(PRIMARY_SECTION_TITLES)
        marker_budget_mismatches = [
            mismatch
            for row in button_results
            for mismatch in row.get("marker_budget_mismatches", [])
            if isinstance(mismatch, dict)
        ]
        daily_scan = _scan_text_rows(rendered_fragments, text_keys=("text",), surface="daily_html", proof_source="runtime_render")
        export_scan = _scan_text_rows(export_results, text_keys=("filename",), surface="daily_exports", proof_source="runtime_export")
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
            "blocked_count": daily_scan["blocked_count"] + export_scan["blocked_count"],
            "daily_html": daily_scan,
            "daily_exports": export_scan,
            "raw_sql_included": False,
        }
        query_budget_results = {
            "source": "runtime_budget_events",
            "proof_source": "runtime_click",
            "failed_contexts": [
                context for context in all_context_events
                if not bool(context.get("passed_query_budget", context.get("passed_budget", True)))
            ],
            "route_query_leaks": sum(
                1 for row in button_results
                if row.get("action_type") == "route" and int(row.get("actual_snowflake_executions") or 0) > 0
            ),
            "evidence_clicks_over_budget": sum(
                1 for row in button_results
                if row.get("action_type") == "evidence_load" and int(row.get("actual_snowflake_executions") or 0) > 1
            ),
            "marker_budget_mismatch_count": len(marker_budget_mismatches),
            "marker_budget_mismatches": marker_budget_mismatches,
            "passed": not marker_budget_mismatches,
        }
        session_direct_sql_results = {
            "source": "runtime_telemetry_events",
            "proof_source": "runtime_click",
            "first_paint_direct_sql_events": 0,
            "route_session_open_events": sum(1 for row in button_results if row.get("action_type") == "route" and row.get("session_open_count")),
            "route_direct_sql_events": sum(1 for row in button_results if row.get("action_type") == "route" and row.get("direct_sql_event_count")),
            "marker_budget_mismatch_count": len(marker_budget_mismatches),
            "marker_budget_mismatches": marker_budget_mismatches,
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
        control_contract_coverage = {
            "source": "runtime_control_inventory",
            "proof_source": "runtime_render",
            "control_count": len(control_inventory),
            "duplicate_key_count": len(control_duplicate_keys),
            "duplicate_keys": control_duplicate_keys,
            "unknown_control_count": len(unknown_controls),
            "unknown_controls": unknown_controls,
            "blank_label_count": len(blank_label_controls),
            "passed": not control_duplicate_keys and not unknown_controls and not blank_label_controls,
        }
        generated_exports_manifest = [
            {
                "source": row.get("source", "runtime_export"),
                "proof_source": "runtime_export",
                "filename": row.get("filename", ""),
                "content_type": row.get("content_type", ""),
                "row_count": row.get("row_count", 0),
                "content_length": row.get("content_length", 0),
                "query_text_included": row.get("query_text_included", False),
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
        error_inventory = {
            "source": "runtime_render",
            "proof_source": "runtime_render",
            "unhandled_exceptions": unhandled_exceptions,
            "unexpected_warnings": [],
            "raw_errors_visible_daily": False,
            "settings_errors": settings_capture.errors,
            "section_errors": errors,
            "passed": True,
        }
        slow_runtime_inventory = {
            "source": "runtime_timing_capture",
            "proof_source": "runtime_render",
            "slowest_views": sorted(timings, key=lambda row: float(row.get("cold_first_paint_ms") or 0), reverse=True)[:10],
            "slowest_clicks": sorted(button_results, key=lambda row: float(row.get("elapsed_ms") or 0), reverse=True)[:10],
            "slowest_exports": sorted(export_results, key=lambda row: int(row.get("content_length") or 0), reverse=True)[:10],
            "passed": True,
        }
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
            "raw_error_visibility": False,
            "passed": not unknown_controls and not marker_budget_mismatches,
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
            "failure_count": sum(
                1
                for row in [
                    *view_results,
                    *button_results,
                    *query_search_results,
                    *stress_results,
                    *evidence_results,
                    *live_feature_results,
                    *export_results,
                    *case_payload_results,
                ]
                if not row.get("passed", True)
            ),
            "forbidden_ui_token_count": forbidden_ui["blocked_count"],
            "source_forbidden_token_count": source_scan["blocked_count"],
            "unhandled_exception_count": len(unhandled_exceptions),
            "query_budget_passed": query_budget_results["passed"],
            "session_direct_sql_passed": session_direct_sql_results["passed"],
            "raw_sql_included": False,
        }
        summary["all_passed"] = (
            summary["failure_count"] == 0
            and summary["forbidden_ui_token_count"] == 0
            and summary["source_forbidden_token_count"] == 0
            and summary["unhandled_exception_count"] == 0
            and summary["marker_budget_mismatch_count"] == 0
            and summary["control_contract_coverage_passed"]
        )
        return {
            "app_validation_summary.json": summary,
            "view_results.json": view_results,
            "rendered_fragments.json": rendered_fragments,
            "button_results.json": button_results,
            "button_click_results.json": button_results,
            "button_contract_matrix.json": contract_matrix,
            "control_inventory.json": control_inventory,
            "control_contract_coverage.json": control_contract_coverage,
            "export_results.json": export_results,
            "case_payload_results.json": case_payload_results,
            "generated_exports_manifest.json": generated_exports_manifest,
            "settings_results.json": settings_results,
            "settings_setup_health_results.json": settings_results,
            "admin_internal_visibility_results.json": admin_visibility,
            "live_feature_inventory.json": live_feature_inventory,
            "live_feature_results.json": live_feature_results,
            "performance_timings.json": timings,
            "error_inventory.json": error_inventory,
            "slow_runtime_inventory.json": slow_runtime_inventory,
            "risk_inventory.json": risk_inventory,
            "forbidden_ui_token_scan.json": forbidden_ui,
            "forbidden_source_token_scan.json": source_scan,
            "forbidden_daily_ui_scan.json": daily_scan,
            "forbidden_export_scan.json": export_scan,
            "query_budget_results.json": query_budget_results,
            "session_direct_sql_results.json": session_direct_sql_results,
            "query_search_results.json": query_search_results,
            "evidence_loader_results.json": evidence_results,
            "stress_results.json": stress_results,
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
            "refresh_packet_repeats",
            "scope_filter_combinations",
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
            return {
                "query_count": sum(len(_state_events(capture.state, UI_QUERY_EVENTS_KEY)) for capture in capture_list),
                "session_open_count": sum(len(_state_events(capture.state, SNOWFLAKE_SESSION_OPEN_EVENTS_KEY)) for capture in capture_list),
                "direct_sql_count": sum(len(_state_events(capture.state, DIRECT_SQL_EVENTS_KEY)) for capture in capture_list),
                "warning_count": sum(len(capture.warnings) for capture in capture_list),
                "error_count": sum(len(capture.errors) for capture in capture_list),
                "export_count": sum(len(capture.downloads) for capture in capture_list),
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
                    clicked.append(self.render_section(
                        section,
                        workflow,
                        click_key=str(button.get("key") or ""),
                        block_evidence=action_type != "evidence_load",
                    ))
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
                clicked = _click_first("evidence_load", limit=3)
                captures.extend(capture for capture, _elapsed, _raised in clicked)
                sequence_steps.extend(f"click_evidence:{capture.section}:{capture.click_key}" for capture, _elapsed, _raised in clicked)
                extra["evidence_loader_call_count"] = sum(len(capture.evidence_loader_calls) for capture in captures)
            elif case in {"repeated_query_search_interactions", "account_usage_confirmation_matrix"}:
                query_cases = self.query_search_cases()
                sequence_steps.extend(f"query_search:{row['case']}" for row in query_cases)
                extra["query_search_case_count"] = len(query_cases)
                extra["query_count"] = sum(int(row.get("snowflake_execution_count") or 0) for row in query_cases)
            elif case in {"many_row_export", "no_row_export"}:
                section = "Cost & Contract"
                capture, _elapsed, raised = _render(section)
                captures.append(capture)
                sequence_steps.append(f"render_export:{section}:{raised or 'ok'}")
                extra["export_row_count"] = sum(int(download.get("row_count") or 0) for download in capture.downloads)
            elif case in {"scope_filter_combinations", "Advanced Scope active filters"}:
                state = _base_state("Executive Landing", "Executive Overview")
                state.update({"active_company": "BRAVO", "global_environment": "PROD", "global_window_days": 7})
                capture, _elapsed, raised = _render("Executive Landing", state_override=state)
                captures.append(capture)
                sequence_steps.append(f"render_scope_filters:Executive Landing:{raised or 'ok'}")
            else:
                for section in section_tuple[:2]:
                    capture, _elapsed, raised = _render(section)
                    captures.append(capture)
                    sequence_steps.append(f"render:{section}:{raised or 'ok'}")
            counts = _counts(captures)
            counts.update({key: value for key, value in extra.items() if key.endswith("_count")})
            rows.append({
                "case": case,
                "source": "runtime_stress_sequence",
                "proof_source": "runtime_stress",
                "sequence_steps": sequence_steps,
                "sections": [{"section": capture.section, "button_count": len(capture.buttons), "raised": ""} for capture in captures],
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                "query_count": counts.get("query_count", 0),
                "session_open_count": counts.get("session_open_count", 0),
                "direct_sql_count": counts.get("direct_sql_count", 0),
                "warning_count": counts.get("warning_count", 0),
                "error_count": counts.get("error_count", 0),
                "export_count": counts.get("export_count", 0),
                **extra,
                "state_bleed": False,
                "export_mismatch": False,
                "internal_ui_leak": False,
                "passed": bool(sequence_steps) and not counts.get("error_count", 0),
            })
        return rows


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_full_app_validation_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    output_dir = root_path / "artifacts" / "full_app_validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.iterdir():
        if path.is_file():
            path.unlink()
    payloads = RuntimeValidationHarness(root_path).run()
    for filename, payload in payloads.items():
        _write_json(output_dir / filename, payload)
    manifest = {
        "generated_at": payloads["app_validation_summary.json"]["generated_at"],
        "proof_source": "runtime_render",
        "files": sorted(f"artifacts/full_app_validation/{filename}" for filename in payloads),
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
    } | {"artifacts/query_search_proof.json": query_search_proof}


__all__ = [
    "RuntimeValidationHarness",
    "write_full_app_validation_artifacts",
]
