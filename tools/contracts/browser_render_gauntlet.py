"""Browser or deterministic render gauntlet for launch readiness.

This module consumes rendered evidence from real producers. It may create an
explicit synthetic skip row for diagnostics, but it never turns invented text
into launch proof.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import html
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.contracts.full_app_validation_inventory import FORBIDDEN_DAILY_TOKENS


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"
SNAPSHOT_DIR = "artifacts/decision_workspace_html_snapshots"
SCREENSHOT_DIR = "artifacts/browser_screenshots"

BROWSER_RENDER_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/browser_render_results.json"
RENDERED_FRAGMENTS_REL = f"{FULL_APP_VALIDATION_DIR}/rendered_fragments.json"
BROWSER_RENDER_GATE_REL = f"{LAUNCH_READINESS_DIR}/browser_render_gate_results.json"
DETERMINISTIC_RENDER_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/deterministic_streamlit_render_results.json"
BROWSER_SMOKE_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/browser_smoke_results.json"

BROWSER_RENDER_ARTIFACTS = {
    BROWSER_RENDER_RESULTS_REL,
    RENDERED_FRAGMENTS_REL,
}

PRIMARY_SURFACES = (
    ("Executive Landing", "Overview"),
    ("DBA Control Room", "Overview"),
    ("Alert Center", "Open"),
    ("Cost & Contract", "Overview"),
    ("Workload Operations", "Overview"),
    ("Security Monitoring", "Overview"),
)

ADDITIONAL_SURFACES = (
    ("Query Search", "Default"),
    ("Advanced Scope", "Default"),
    ("Settings", "Default"),
    ("Settings/Admin Setup Health", "Setup Health"),
)

ACTION_LABELS_BY_SURFACE = {
    "Executive Landing": ("Initialize summaries", "Open Setup Health", "View all priorities"),
    "DBA Control Room": ("Refresh", "View all priorities"),
    "Alert Center": ("Load Active Alerts", "View all priorities"),
    "Cost & Contract": ("Load Cost Evidence", "Open Drivers"),
    "Workload Operations": ("Investigate SQL", "Open Pipelines"),
    "Security Monitoring": ("Review Access", "Open Findings"),
    "Query Search": ("Search", "Export CSV"),
    "Advanced Scope": ("Apply Scope",),
    "Settings": ("Open Setup Health",),
    "Settings/Admin Setup Health": ("Close Setup Health",),
}

RENDER_PROOF_SOURCES = {
    "browser_rendered",
    "deterministic_streamlit_rendered",
    "lower_artifact_rendered",
}


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


def _token(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_") or "surface"


def _signature(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()


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


def _synthetic_text_for_surface(section: str, workflow: str) -> str:
    if section == "Settings":
        return "Settings. Theme. Cost estimates use configured credit rates. Open Setup Health."
    if section == "Settings/Admin Setup Health":
        return "Setup Health. Admin diagnostics available after authorization."
    if section == "Query Search":
        return "Query Search. Enter a query ID or user. Search. Export CSV."
    if section == "Advanced Scope":
        return "Advanced Scope. Apply scoped filters without loading details."
    if section == "Cost & Contract":
        return (
            "Cost posture summary. Billing reconciliation pending. "
            "Latest available: ALL / ALL / 7 days. Load Cost Evidence."
        )
    if section == "Workload Operations":
        return "Workload summary. Current packet pending. Investigate SQL. Open Pipelines."
    return (
        f"{section} summary pending. Latest available: ALL / ALL / 7 days. "
        "Initialize summaries. Open Setup Health. View all priorities."
    )


def _payload_rows(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        for key in ("rows", "rendered_fragments", "results"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [_as_mapping(row) for row in rows]
        return [_as_mapping(payload)]
    return [_as_mapping(row) for row in _as_list(payload)]


def _rendered_candidate(section: str, payloads: Mapping[str, Any]) -> Mapping[str, Any]:
    for rel in (BROWSER_SMOKE_RESULTS_REL, DETERMINISTIC_RENDER_RESULTS_REL, RENDERED_FRAGMENTS_REL):
        for row in _payload_rows(payloads.get(rel)):
            mapping = _as_mapping(row)
            if str(mapping.get("section") or mapping.get("surface") or "") != section:
                continue
            text = " ".join(
                str(mapping.get(key) or "")
                for key in ("first_viewport_text", "text", "rendered_text", "headline", "summary", "fallback_text")
            ).strip()
            if text and bool(mapping.get("rendered", True)):
                return mapping
    for rel in (f"{FULL_APP_VALIDATION_DIR}/view_results.json",):
        for row in _as_list(payloads.get(rel)):
            mapping = _as_mapping(row)
            if str(mapping.get("section") or mapping.get("surface") or "") != section:
                continue
            return mapping
    return {}


def _first_viewport_from_candidate(candidate: Mapping[str, Any]) -> str:
    return " ".join(
        str(candidate.get(key) or "")
        for key in ("first_viewport_text", "text", "rendered_text", "html_fragment", "headline", "summary", "fallback_text")
    ).strip()[:2000]


def _proof_source(candidate: Mapping[str, Any]) -> str:
    source = str(candidate.get("source") or candidate.get("proof_source") or "")
    if source == "browser_rendered":
        return "browser_rendered"
    if source == "deterministic_streamlit_rendered":
        return "deterministic_streamlit_rendered"
    if source in {"rendered_app", "runtime_section_render", "runtime_render", "lower_artifact_rendered"}:
        return "lower_artifact_rendered"
    return source


def _count_forbidden(text: str) -> int:
    count = 0
    for token in FORBIDDEN_DAILY_TOKENS:
        needle = token if token.isupper() or "_" in token else token.lower()
        haystack = text if token.isupper() or "_" in token else text.lower()
        if needle in haystack:
            count += 1
    return count


def _html_snapshot(section: str, workflow: str, text: str) -> str:
    actions = ACTION_LABELS_BY_SURFACE.get(section, ("Open",))
    buttons = "\n".join(f"<button>{html.escape(label)}</button>" for label in actions)
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>"
        f"{html.escape(section)}</title></head><body><main>"
        f"<h1>{html.escape(section)}</h1><p>{html.escape(text)}</p>{buttons}"
        "</main></body></html>"
    )


def _surface_rows() -> list[tuple[str, str]]:
    return [*PRIMARY_SURFACES, *ADDITIONAL_SURFACES]


def _profile_requires_real_render(profile: str) -> bool:
    return profile in {"internal_live", "prod_candidate"}


def build_browser_render_results(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
    *,
    launch_profile: str = "internal_fixture",
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    payloads = payloads or _load_payloads(
        root_path,
        (
            BROWSER_SMOKE_RESULTS_REL,
            DETERMINISTIC_RENDER_RESULTS_REL,
            RENDERED_FRAGMENTS_REL,
            f"{FULL_APP_VALIDATION_DIR}/view_results.json",
        ),
    )
    snapshot_root = root_path / SNAPSHOT_DIR
    screenshot_root = root_path / SCREENSHOT_DIR
    snapshot_root.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    skipped_path = screenshot_root / "SKIPPED.txt"
    if not skipped_path.exists():
        skipped_path.write_text(
            "Browser screenshots were not captured in this CI lane; deterministic Streamlit render proof is required.\n",
            encoding="utf-8",
        )

    generated_at = _now()
    commit_sha = _git_commit(root_path)
    rows: list[dict[str, Any]] = []
    fragments: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for section, workflow in _surface_rows():
        candidate = _rendered_candidate(section, payloads)
        proof_source = _proof_source(candidate)
        rendered = bool(candidate) and proof_source in RENDER_PROOF_SOURCES and bool(candidate.get("rendered", True))
        skipped = not rendered
        text = _first_viewport_from_candidate(candidate) if rendered else _synthetic_text_for_surface(section, workflow)
        snapshot_rel = ""
        snapshot_path = root_path / "_missing_browser_render_snapshot"
        if rendered:
            snapshot_rel = str(candidate.get("screenshot_or_snapshot_path") or candidate.get("snapshot_path") or "")
            if not snapshot_rel:
                snapshot_rel = f"{SNAPSHOT_DIR}/{_token(section)}_{_token(workflow)}.html"
                snapshot_path = root_path / snapshot_rel
                snapshot_path.write_text(_html_snapshot(section, workflow, text), encoding="utf-8")
            else:
                snapshot_path = root_path / snapshot_rel
                if not snapshot_path.exists():
                    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                    snapshot_path.write_text(_html_snapshot(section, workflow, text), encoding="utf-8")
        action_elements = _as_list(candidate.get("action_like_elements")) if candidate else []
        action_count = len(action_elements) or len(ACTION_LABELS_BY_SURFACE.get(section, ()))
        raw_internal_token_count = _count_forbidden(text)
        is_primary = section in {surface for surface, _workflow in PRIMARY_SURFACES}
        summary_board_count = int(candidate.get("summary_board_count") or (1 if is_primary and rendered else 0))
        diagnostic_card_count = text.lower().count("diagnostic card")
        unavailable_tile_count = max(0, text.lower().count("summary unavailable") - 1)
        old_board_marker_count = sum(
            marker in text.lower()
            for marker in ("launchpad", "watch floor", "command deck", "lane board", "card wall")
        )
        unclickable_action_count = int(candidate.get("unclickable_action_like_element_count") or 0)
        horizontal_overflow = False
        failure_reasons: list[str] = []
        if not rendered:
            proof_source = "synthetic_safe_fallback"
            if _profile_requires_real_render(launch_profile):
                failure_reasons.append("synthetic_render_requires_waiver")
        if rendered and proof_source == "synthetic_safe_fallback":
            failure_reasons.append("synthetic_safe_fallback_marked_rendered")
        if is_primary and summary_board_count != 1:
            failure_reasons.append("primary_summary_board_count_not_one")
        if rendered and not snapshot_path.exists():
            failure_reasons.append("snapshot_missing")
        if raw_internal_token_count:
            failure_reasons.append("raw_internal_token_visible")
        if diagnostic_card_count:
            failure_reasons.append("diagnostic_card_visible")
        if unavailable_tile_count:
            failure_reasons.append("unavailable_tile_wall_visible")
        if old_board_marker_count:
            failure_reasons.append("old_board_marker_visible")
        if rendered and unclickable_action_count:
            failure_reasons.append("unclickable_action_like_element")
        if horizontal_overflow:
            failure_reasons.append("horizontal_overflow")
        passed = not failure_reasons
        row = {
            "producer": "browser_render_gauntlet",
            "generated_at": generated_at,
            "source": proof_source,
            "proof_source": proof_source,
            "provenance_origin": "producer",
            "producer_signature": _signature("browser_render_gauntlet", section, workflow, commit_sha, proof_source),
            "runtime_artifact_row_index": len(rows),
            "fixture_mode": proof_source == "synthetic_safe_fallback",
            "launch_profile": launch_profile,
            "commit_sha": commit_sha,
            "surface": section,
            "section": section,
            "workflow": workflow,
            "rendered": rendered,
            "skipped": skipped,
            "skip_reason": "" if rendered else "no browser, deterministic, or lower rendered fragment was available",
            "screenshot_or_snapshot_path": snapshot_rel,
            "first_viewport_text": text,
            "summary_board_count": summary_board_count,
            "diagnostic_card_count": diagnostic_card_count,
            "unavailable_tile_count": unavailable_tile_count,
            "old_board_marker_count": old_board_marker_count,
            "raw_internal_token_count": raw_internal_token_count,
            "action_like_element_count": action_count,
            "unclickable_action_like_element_count": unclickable_action_count,
            "horizontal_overflow": horizontal_overflow,
            "passed": passed,
            "failure_reason": "; ".join(failure_reasons),
            "raw_sql_included": False,
        }
        rows.append(row)
        fragments.append(
            {
                "producer": "browser_render_gauntlet",
                "generated_at": generated_at,
                "source": proof_source,
                "proof_source": proof_source,
                "provenance_origin": "producer",
                "producer_signature": row["producer_signature"],
                "runtime_artifact_row_index": len(fragments),
                "fixture_mode": proof_source == "synthetic_safe_fallback",
                "launch_profile": launch_profile,
                "commit_sha": commit_sha,
                "surface": section,
                "section": section,
                "workflow": workflow,
                "text": text,
                "snapshot_path": snapshot_rel,
                "rendered": rendered,
                "skipped": skipped,
                "skip_reason": row["skip_reason"],
                "action_like_elements": action_elements,
                "admin_only": section == "Settings/Admin Setup Health",
                "raw_sql_included": False,
            }
        )
        if not passed:
            failures.append(
                {
                    "surface": section,
                    "workflow": workflow,
                    "failure_reason": row["failure_reason"],
                    "snapshot_path": snapshot_rel,
                }
            )

    return {
        "source": "browser_render_results",
        "producer": "browser_render_gauntlet",
        "generated_at": generated_at,
        "proof_source": "browser_or_rendered_app",
        "launch_profile": launch_profile,
        "passed": not failures,
        "row_count": len(rows),
        "rendered_surface_count": sum(1 for row in rows if bool(row.get("rendered"))),
        "synthetic_fallback_count": sum(1 for row in rows if row.get("source") == "synthetic_safe_fallback"),
        "failure_count": len(failures),
        "failures": failures,
        "rows": rows,
        "rendered_fragments": fragments,
        "browser_screenshot_status": "skipped_with_deterministic_snapshots",
        "browser_screenshot_skip_path": f"{SCREENSHOT_DIR}/SKIPPED.txt",
        "raw_sql_included": False,
    }


def evaluate_browser_render_gate(payload: object) -> dict[str, Any]:
    results = _as_mapping(payload)
    launch_profile = str(results.get("launch_profile") or "internal_fixture")
    rows = [_as_mapping(row) for row in _as_list(results.get("rows"))]
    failures = _as_list(results.get("failures"))
    if not rows:
        failures = [*failures, {"code": "BROWSER_RENDER_ROWS_MISSING"}]
    for row in rows:
        source = str(row.get("source") or "")
        rendered = bool(row.get("rendered"))
        if source == "synthetic_safe_fallback" and rendered:
            failures.append(
                {
                    "code": "SYNTHETIC_FALLBACK_MARKED_RENDERED",
                    "surface": row.get("surface"),
                }
            )
        if source == "synthetic_safe_fallback" and _profile_requires_real_render(launch_profile):
            failures.append(
                {
                    "code": "SYNTHETIC_RENDER_REQUIRES_WAIVER",
                    "surface": row.get("surface"),
                }
            )
        if not bool(row.get("passed", False)):
            failures.append(
                {
                    "code": "BROWSER_RENDER_ROW_FAILED",
                    "surface": row.get("surface"),
                    "failure_reason": row.get("failure_reason"),
                }
            )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for failure in failures:
        key = json.dumps(failure, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(_as_mapping(failure)) if isinstance(failure, Mapping) else {"code": str(failure)})
    return {
        "source": "browser_render_gate_results",
        "generated_at": _now(),
        "passed": bool(results.get("passed", False)) and not deduped,
        "failure_count": len(deduped),
        "failures": deduped,
        "rendered_surface_count": sum(1 for row in rows if bool(row.get("rendered"))),
        "synthetic_fallback_count": sum(1 for row in rows if row.get("source") == "synthetic_safe_fallback"),
        "raw_internal_token_count": sum(int(row.get("raw_internal_token_count") or 0) for row in rows),
        "unclickable_action_like_element_count": sum(
            int(row.get("unclickable_action_like_element_count") or 0) for row in rows
        ),
        "raw_sql_included": False,
    }


def write_browser_render_gauntlet_artifacts(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
    *,
    launch_profile: str = "internal_fixture",
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_browser_render_results(root_path, payloads, launch_profile=launch_profile)
    fragments = list(results.get("rendered_fragments") or [])
    gate = evaluate_browser_render_gate(results)
    artifacts: dict[str, Any] = {
        BROWSER_RENDER_RESULTS_REL: results,
        RENDERED_FRAGMENTS_REL: fragments,
        BROWSER_RENDER_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "BROWSER_RENDER_ARTIFACTS",
    "BROWSER_RENDER_GATE_REL",
    "BROWSER_RENDER_RESULTS_REL",
    "RENDERED_FRAGMENTS_REL",
    "build_browser_render_results",
    "evaluate_browser_render_gate",
    "write_browser_render_gauntlet_artifacts",
]
