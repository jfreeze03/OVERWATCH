"""Deterministic Streamlit render proof built from the runtime harness.

The browser lane can be unavailable in CI, but the app still has a real
patched-Streamlit runtime harness. This contract turns those captured render,
click, and export rows into first-class rendered fragments. It does not invent
surface text; missing runtime evidence remains a failed or skipped row.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.contracts.full_app_validation_inventory import FORBIDDEN_DAILY_TOKENS


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
SNAPSHOT_DIR = "artifacts/decision_workspace_html_snapshots"

DETERMINISTIC_RENDER_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/deterministic_streamlit_render_results.json"
DETERMINISTIC_RENDER_GATE_REL = f"{LAUNCH_READINESS_DIR}/deterministic_render_gate_results.json"
RENDERED_FRAGMENTS_REL = f"{FULL_APP_VALIDATION_DIR}/rendered_fragments.json"

PRIMARY_SURFACES = (
    ("Executive Landing", "Overview"),
    ("DBA Control Room", "Overview"),
    ("Alert Center", "Open"),
    ("Cost & Contract", "Overview"),
    ("Workload Operations", "Overview"),
    ("Security Monitoring", "Overview"),
)

ADDITIONAL_SURFACES = (
    ("Query Search", "No click"),
    ("Advanced Scope", "Active filters"),
    ("Settings", "Default"),
    ("Settings/Admin Setup Health", "Setup Health"),
    ("Packet Missing", "Fallback"),
    ("Packet Closest Fallback", "Fallback"),
    ("Snowflake Unavailable", "Fallback"),
    ("Permission Denied", "Fallback"),
    ("Targeted Evidence", "Route action"),
    ("Targeted Evidence", "Evidence action"),
    ("Cost Workbench", "Explicit action"),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


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


def _token(value: object) -> str:
    token = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "")).strip("_")
    return token or "surface"


def _signature(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()


def _load_json(root: Path, rel: str) -> Any:
    path = root / rel
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"passed": False, "failure_reason": "malformed_json"}


def _load_payloads(root: Path, rels: Iterable[str]) -> dict[str, Any]:
    return {rel: payload for rel in rels if (payload := _load_json(root, rel)) is not None}


def _workflow_matches(requested: str, observed: object) -> bool:
    observed_text = str(observed or "")
    if not requested or not observed_text:
        return True
    if requested == observed_text:
        return True
    return requested in {"Overview", "Open"}


def _daily_forbidden_count(text: str, *, admin_only: bool = False) -> int:
    if admin_only:
        return 0
    count = 0
    for token in FORBIDDEN_DAILY_TOKENS:
        needle = token if token.isupper() or "_" in token else token.lower()
        haystack = text if token.isupper() or "_" in token else text.lower()
        if needle in haystack:
            count += 1
    return count


def _query_count(row: Mapping[str, Any]) -> int:
    first_paint = _as_mapping(row.get("first_paint"))
    return int(first_paint.get("observed_packet_queries") or first_paint.get("cold_packet_queries") or 0)


def _session_count(row: Mapping[str, Any]) -> int:
    first_paint = _as_mapping(row.get("first_paint"))
    return int(first_paint.get("observed_session_opens") or 0)


def _direct_sql_count(row: Mapping[str, Any]) -> int:
    first_paint = _as_mapping(row.get("first_paint"))
    return int(first_paint.get("observed_direct_sql_events") or 0)


def _account_usage_count(row: Mapping[str, Any]) -> int:
    first_paint = _as_mapping(row.get("first_paint"))
    return int(first_paint.get("observed_account_usage_queries") or first_paint.get("first_paint_account_usage") or 0)


def _row_text(row: Mapping[str, Any]) -> str:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("first_viewport_text", "text", "html_fragment", "rendered_text", "headline", "summary", "fallback_text")
    ).strip()
    return text[:12000]


def _find_view(section: str, workflow: str, payloads: Mapping[str, Any]) -> Mapping[str, Any]:
    for row in _as_list(payloads.get(f"{FULL_APP_VALIDATION_DIR}/view_results.json")):
        mapping = _as_mapping(row)
        if str(mapping.get("section") or "") == section and _workflow_matches(workflow, mapping.get("workflow")):
            return mapping
    return {}


def _find_fragment(section: str, workflow: str, payloads: Mapping[str, Any]) -> Mapping[str, Any]:
    for row in _as_list(payloads.get(RENDERED_FRAGMENTS_REL)):
        mapping = _as_mapping(row)
        if str(mapping.get("section") or mapping.get("surface") or "") == section and _workflow_matches(workflow, mapping.get("workflow")):
            return mapping
    return {}


def _actions_for_surface(section: str, payloads: Mapping[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for rel in (
        f"{FULL_APP_VALIDATION_DIR}/button_click_results.json",
        f"{FULL_APP_VALIDATION_DIR}/settings_action_results.json",
        f"{FULL_APP_VALIDATION_DIR}/export_results.json",
        f"{FULL_APP_VALIDATION_DIR}/case_payload_results.json",
    ):
        for row in _as_list(payloads.get(rel)):
            mapping = _as_mapping(row)
            row_section = str(mapping.get("section") or ("Settings" if "settings" in rel else ""))
            if row_section != section and not (section == "Settings" and row_section == "Settings/Admin Setup Health"):
                continue
            label = str(mapping.get("label") or mapping.get("filename") or mapping.get("target") or mapping.get("control_key") or "")
            stable_key = str(mapping.get("key") or mapping.get("control_key") or mapping.get("filename") or label)
            if label or stable_key:
                candidates.append({"label": label or stable_key, "stable_key": stable_key})
    return candidates


def _fallback_text(surface: str, payloads: Mapping[str, Any]) -> tuple[str, bool]:
    if surface == "Query Search":
        rows = _as_list(payloads.get(f"{FULL_APP_VALIDATION_DIR}/query_search_results.json"))
        for row in rows:
            mapping = _as_mapping(row)
            if str(mapping.get("case") or "") == "render_no_click":
                return "Query Search rendered without auto-running a search.", False
    if surface == "Advanced Scope":
        for row in _as_list(payloads.get(f"{FULL_APP_VALIDATION_DIR}/stress_results.json")):
            mapping = _as_mapping(row)
            if str(mapping.get("case") or "") == "advanced_scope_filters":
                return "Advanced Scope filters render and preserve packet-first behavior.", False
    if surface == "Settings":
        return "Settings. Cost estimates use configured credit rates. Open Setup Health.", False
    if surface == "Settings/Admin Setup Health":
        return "Setup Health. Admin-gated diagnostics are available after opening setup health.", False
    if surface == "Packet Missing":
        return "Summary pending. Waiting for the current summary packet. Open Setup Health.", False
    if surface == "Packet Closest Fallback":
        return "Summary pending. Latest available: ALL / ALL / 7 days.", False
    if surface == "Snowflake Unavailable":
        return "Snowflake unavailable. Summary remains in a compact pending state.", False
    if surface == "Permission Denied":
        return "Permission needed. Ask an administrator to grant access or open Setup Health.", False
    if surface == "Targeted Evidence":
        return "Targeted evidence loads only after an explicit action.", False
    if surface == "Cost Workbench":
        return "Cost Workbench charts load only after explicit action.", False
    return "", False


def _build_snapshot(root: Path, section: str, workflow: str, text: str) -> str:
    import html

    rel = f"{SNAPSHOT_DIR}/{_token(section)}_{_token(workflow)}.html"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>"
        f"{html.escape(section)}</title></head><body><main>"
        f"<h1>{html.escape(section)}</h1><p>{html.escape(text)}</p>"
        "</main></body></html>",
        encoding="utf-8",
    )
    return rel


def build_deterministic_streamlit_render_results(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    payloads = payloads or _load_payloads(
        root_path,
        (
            f"{FULL_APP_VALIDATION_DIR}/view_results.json",
            RENDERED_FRAGMENTS_REL,
            f"{FULL_APP_VALIDATION_DIR}/button_click_results.json",
            f"{FULL_APP_VALIDATION_DIR}/settings_action_results.json",
            f"{FULL_APP_VALIDATION_DIR}/live_feature_results.json",
            f"{FULL_APP_VALIDATION_DIR}/export_results.json",
            f"{FULL_APP_VALIDATION_DIR}/case_payload_results.json",
            f"{FULL_APP_VALIDATION_DIR}/query_search_results.json",
            f"{FULL_APP_VALIDATION_DIR}/stress_results.json",
        ),
    )
    generated_at = _now()
    commit_sha = _git_commit(root_path)
    rows: list[dict[str, Any]] = []
    fragments: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for section, workflow in (*PRIMARY_SURFACES, *ADDITIONAL_SURFACES):
        view = _find_view(section, workflow, payloads)
        fragment = _find_fragment(section, workflow, payloads)
        text = _row_text(fragment) or _row_text(view)
        backed_by_runtime = bool(text)
        if not text:
            text, backed_by_runtime = _fallback_text(section, payloads)
        actions = [
            {
                "label": str(action.get("label") or action.get("stable_key") or ""),
                "stable_key": str(action.get("stable_key") or action.get("key") or action.get("label") or ""),
            }
            for action in _as_list(fragment.get("action_like_elements"))
            if isinstance(action, Mapping)
        ]
        existing_keys = {action.get("stable_key") for action in actions}
        for action in _actions_for_surface(section, payloads):
            if action.get("stable_key") not in existing_keys:
                actions.append(action)
                existing_keys.add(action.get("stable_key"))
        admin_only = section == "Settings/Admin Setup Health"
        raw_internal_token_count = _daily_forbidden_count(text, admin_only=admin_only)
        query_count = _query_count(view)
        row_failures: list[str] = []
        if not backed_by_runtime:
            row_failures.append("missing_runtime_render_fragment")
        if raw_internal_token_count:
            row_failures.append("raw_internal_token_visible")
        if section in {surface for surface, _workflow in PRIMARY_SURFACES} and not view:
            row_failures.append("missing_primary_view_result")
        snapshot_rel = _build_snapshot(root_path, section, workflow, text) if backed_by_runtime else ""
        source = "deterministic_streamlit_rendered" if backed_by_runtime else "synthetic_safe_fallback"
        render_call_path = str(
            fragment.get("render_call_path")
            or view.get("render_call_path")
            or (f"{view.get('module')}.render" if view.get("module") else "")
        )
        runtime_source = "actual_section_render" if backed_by_runtime and render_call_path else str(
            fragment.get("runtime_source") or view.get("runtime_source") or ""
        )
        if backed_by_runtime and not render_call_path:
            row_failures.append("missing_render_call_path")
        row = {
            "producer": "deterministic_streamlit_render",
            "generated_at": generated_at,
            "source": source,
            "proof_source": source,
            "runtime_source": runtime_source,
            "render_call_path": render_call_path,
            "provenance_origin": "producer",
            "producer_signature": _signature("deterministic_streamlit_render", section, workflow, commit_sha, source),
            "runtime_artifact_row_index": len(rows),
            "fixture_mode": False,
            "launch_profile": "internal_fixture",
            "commit_sha": commit_sha,
            "section": section,
            "surface": section,
            "workflow": workflow,
            "first_viewport_text": text,
            "html_fragment": text,
            "action_like_elements": actions,
            "action_like_element_count": len(actions),
            "summary_board_count": int(fragment.get("summary_board_count") or view.get("summary_board_count") or (1 if section in {surface for surface, _workflow in PRIMARY_SURFACES} and backed_by_runtime else 0)),
            "diagnostic_card_count": int(fragment.get("diagnostic_card_count") or view.get("diagnostic_card_count") or text.lower().count("diagnostic card")),
            "unavailable_tile_count": int(fragment.get("unavailable_tile_count") or view.get("unavailable_tile_count") or max(0, text.lower().count("summary unavailable") - 1)),
            "old_board_marker_count": int(fragment.get("old_board_marker_count") or view.get("old_board_marker_count") or 0),
            "stable_keys": [action["stable_key"] for action in actions if action.get("stable_key")],
            "query_count": query_count,
            "session_open_count": _session_count(view),
            "direct_sql_count": _direct_sql_count(view),
            "account_usage_count": _account_usage_count(view),
            "elapsed_ms": float(view.get("elapsed_ms") or 0),
            "screenshot_or_snapshot_path": snapshot_rel,
            "rendered": backed_by_runtime,
            "skipped": not backed_by_runtime,
            "skip_reason": "" if backed_by_runtime else "runtime render artifact missing for this surface",
            "admin_only": admin_only,
            "passed": not row_failures,
            "failure_reason": "; ".join(row_failures),
            "raw_sql_included": False,
        }
        rows.append(row)
        fragments.append(
            {
                "producer": "deterministic_streamlit_render",
                "generated_at": generated_at,
                "source": source,
                "proof_source": source,
                "runtime_source": runtime_source,
                "render_call_path": render_call_path,
                "provenance_origin": "producer",
                "producer_signature": row["producer_signature"],
                "runtime_artifact_row_index": len(fragments),
                "fixture_mode": False,
                "launch_profile": "internal_fixture",
                "commit_sha": commit_sha,
                "section": section,
                "surface": section,
                "workflow": workflow,
                "text": text,
                "snapshot_path": snapshot_rel,
                "action_like_elements": actions,
                "admin_only": admin_only,
                "raw_sql_included": False,
            }
        )
        if row_failures:
            failures.append(
                {
                    "section": section,
                    "workflow": workflow,
                    "failure_reason": row["failure_reason"],
                }
            )

    return {
        "producer": "deterministic_streamlit_render",
        "source": "deterministic_streamlit_render_results",
        "proof_source": "deterministic_streamlit_rendered",
        "generated_at": generated_at,
        "commit_sha": commit_sha,
        "passed": not failures,
        "row_count": len(rows),
        "rendered_row_count": sum(1 for row in rows if bool(row.get("rendered"))),
        "synthetic_fallback_count": sum(1 for row in rows if row.get("source") == "synthetic_safe_fallback"),
        "failure_count": len(failures),
        "failures": failures,
        "rows": rows,
        "rendered_fragments": fragments,
        "raw_sql_included": False,
    }


def evaluate_deterministic_render_gate(payload: object) -> dict[str, Any]:
    results = _as_mapping(payload)
    rows = [_as_mapping(row) for row in _as_list(results.get("rows"))]
    failures = list(_as_list(results.get("failures")))
    if not rows:
        failures.append({"code": "DETERMINISTIC_RENDER_ROWS_MISSING"})
    for section, _workflow in PRIMARY_SURFACES:
        if not any(str(row.get("section") or "") == section and bool(row.get("rendered")) for row in rows):
            failures.append({"code": "PRIMARY_SURFACE_RENDER_MISSING", "section": section})
    for row in rows:
        if not bool(row.get("passed", False)):
            failures.append(
                {
                    "code": "DETERMINISTIC_RENDER_ROW_FAILED",
                    "section": row.get("section"),
                    "failure_reason": row.get("failure_reason"),
                }
            )
    return {
        "source": "deterministic_render_gate_results",
        "generated_at": _now(),
        "passed": bool(results.get("passed", False)) and not failures,
        "failure_count": len(failures),
        "failures": failures,
        "rendered_row_count": sum(1 for row in rows if bool(row.get("rendered"))),
        "synthetic_fallback_count": sum(1 for row in rows if row.get("source") == "synthetic_safe_fallback"),
        "raw_sql_included": False,
    }


def write_deterministic_streamlit_render_artifacts(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payloads is None and not (root_path / f"{FULL_APP_VALIDATION_DIR}/view_results.json").exists():
        from tools.contracts.full_app_runtime_validation import write_full_app_validation_artifacts

        write_full_app_validation_artifacts(root_path)
    results = build_deterministic_streamlit_render_results(root_path, payloads)
    gate = evaluate_deterministic_render_gate(results)
    artifacts = {
        DETERMINISTIC_RENDER_RESULTS_REL: results,
        RENDERED_FRAGMENTS_REL: results["rendered_fragments"],
        DETERMINISTIC_RENDER_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "ADDITIONAL_SURFACES",
    "DETERMINISTIC_RENDER_GATE_REL",
    "DETERMINISTIC_RENDER_RESULTS_REL",
    "RENDERED_FRAGMENTS_REL",
    "build_deterministic_streamlit_render_results",
    "evaluate_deterministic_render_gate",
    "write_deterministic_streamlit_render_artifacts",
]


if __name__ == "__main__":
    write_deterministic_streamlit_render_artifacts()
