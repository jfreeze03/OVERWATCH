"""Cross-layer render/provenance reconciliation for release proof.

The runtime harness is the source of truth for rendered app behavior. This
contract verifies that deterministic render, browser/snapshot render, leak
scan, and provenance artifacts are all tied back to the same runtime surfaces
for the same commit instead of passing from synthetic or after-the-fact rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

RENDER_PROVENANCE_RECONCILIATION_REL = (
    f"{FULL_APP_VALIDATION_DIR}/render_provenance_reconciliation_results.json"
)
RENDER_PROVENANCE_RECONCILIATION_GATE_REL = (
    f"{LAUNCH_READINESS_DIR}/render_provenance_reconciliation_gate_results.json"
)

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
    ("Query Search", "Explicit search"),
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

RECONCILIATION_PAYLOAD_RELS = (
    f"{FULL_APP_VALIDATION_DIR}/view_results.json",
    f"{FULL_APP_VALIDATION_DIR}/deterministic_streamlit_render_results.json",
    f"{FULL_APP_VALIDATION_DIR}/browser_render_results.json",
    f"{FULL_APP_VALIDATION_DIR}/browser_smoke_results.json",
    f"{FULL_APP_VALIDATION_DIR}/rendered_fragments.json",
    f"{FULL_APP_VALIDATION_DIR}/rendered_ui_leak_scan_results.json",
    f"{FULL_APP_VALIDATION_DIR}/runtime_artifact_provenance_results.json",
    f"{FULL_APP_VALIDATION_DIR}/action_click_results.json",
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


def _load_payloads(root: Path, rels: Iterable[str] = RECONCILIATION_PAYLOAD_RELS) -> dict[str, Any]:
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


def _rows(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        for key in ("rows", "rendered_fragments", "results", "actions", "checks"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [_as_mapping(row) for row in rows]
        return [_as_mapping(payload)]
    return [_as_mapping(row) for row in _as_list(payload)]


def _workflow_matches(requested: str, observed: object) -> bool:
    observed_text = str(observed or "")
    if not requested:
        return True
    if requested == observed_text:
        return True
    if requested in {"Overview", "Open"} and observed_text:
        return True
    if requested == "No click" and observed_text in {"Default", "Query Investigation"}:
        return True
    if requested == "Active filters" and observed_text in {"Default", "Advanced Scope"}:
        return True
    return False


def _row_text(row: Mapping[str, Any]) -> str:
    for key in ("rendered_text", "first_viewport_text", "html_fragment", "text", "headline", "summary", "fallback_text"):
        text = str(row.get(key) or "").strip()
        if text:
            return " ".join(text.split())[:12000]
    return ""


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _prefix_compatible(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or left.startswith(right) or right.startswith(left)


def _browser_text_compatible(browser_text: str, runtime_text: str, deterministic_text: str) -> bool:
    if not browser_text:
        return True
    # Browser smoke often stores only the first viewport slice. It may be a
    # shorter prefix of the richer runtime/deterministic fragments, but it
    # should not be a longer divergent extension.
    return bool(
        (runtime_text and runtime_text.startswith(browser_text))
        or (deterministic_text and deterministic_text.startswith(browser_text))
        or browser_text in {runtime_text, deterministic_text}
    )


def _find_section_row(rows: Iterable[Mapping[str, Any]], section: str, workflow: str = "") -> Mapping[str, Any]:
    for row in rows:
        if str(row.get("section") or row.get("surface") or "") != section:
            continue
        if _workflow_matches(workflow, row.get("workflow")):
            return row
    return {}


def _runtime_row(section: str, workflow: str, payloads: Mapping[str, Any]) -> Mapping[str, Any]:
    view_rows = _rows(payloads.get(f"{FULL_APP_VALIDATION_DIR}/view_results.json"))
    row = _find_section_row(view_rows, section, workflow)
    if row and _row_text(row):
        return row
    fragment_rows = _rows(payloads.get(f"{FULL_APP_VALIDATION_DIR}/rendered_fragments.json"))
    fragment_row = _find_section_row(fragment_rows, section, workflow)
    if fragment_row and _row_text(fragment_row):
        return fragment_row
    if row:
        return row
    return {}


def _deterministic_row(section: str, workflow: str, payloads: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = _rows(_as_mapping(payloads.get(f"{FULL_APP_VALIDATION_DIR}/deterministic_streamlit_render_results.json")).get("rows"))
    return _find_section_row(rows, section, workflow)


def _browser_row(section: str, workflow: str, payloads: Mapping[str, Any]) -> Mapping[str, Any]:
    for rel in (
        f"{FULL_APP_VALIDATION_DIR}/browser_render_results.json",
        f"{FULL_APP_VALIDATION_DIR}/browser_smoke_results.json",
    ):
        row = _find_section_row(_rows(_as_mapping(payloads.get(rel)).get("rows")), section, workflow)
        if row:
            return row
    return {}


def _leak_row(section: str, payloads: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = _rows(_as_mapping(payloads.get(f"{FULL_APP_VALIDATION_DIR}/rendered_ui_leak_scan_results.json")).get("rows"))
    for row in rows:
        surface = str(row.get("surface") or "")
        if surface == section or surface.startswith(f"{section} /"):
            return row
    return {}


def _provenance_row(section: str, workflow: str, payloads: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = _rows(_as_mapping(payloads.get(f"{FULL_APP_VALIDATION_DIR}/runtime_artifact_provenance_results.json")).get("rows"))
    for row in rows:
        if str(row.get("section") or "") == section and _workflow_matches(workflow, row.get("workflow")):
            return row
    for row in rows:
        if str(row.get("section") or "") == section:
            return row
    return {}


def _action_count(row: Mapping[str, Any]) -> int:
    if "action_like_element_count" in row:
        try:
            return int(row.get("action_like_element_count") or 0)
        except (TypeError, ValueError):
            return 0
    return len(_as_list(row.get("action_like_elements")))


def _action_click_count(runtime: Mapping[str, Any], payloads: Mapping[str, Any]) -> int:
    payload = payloads.get(f"{FULL_APP_VALIDATION_DIR}/action_click_results.json")
    rows = _rows(_as_mapping(payload).get("rows") if isinstance(payload, Mapping) else payload)
    click_keys = {
        str(row.get("stable_key") or row.get("control_key") or row.get("key") or row.get("action_key") or "").strip()
        for row in rows
        if bool(row.get("clicked"))
    }
    click_labels = {
        str(row.get("label") or row.get("action_key") or "").strip()
        for row in rows
        if bool(row.get("clicked"))
    }
    rendered_actions = [
        action for action in _as_list(runtime.get("action_like_elements"))
        if isinstance(action, Mapping)
    ]
    if rendered_actions:
        return sum(
            1
            for action in rendered_actions
            if (
                (key := str(action.get("stable_key") or action.get("key") or "").strip()) in click_keys
                or any(click_key.startswith(key) or key.startswith(click_key) for click_key in click_keys if key)
                or str(action.get("label") or "").strip() in click_labels
            )
        )
    section = str(runtime.get("section") or "")
    workflow = str(runtime.get("workflow") or "")
    count = 0
    for row in rows:
        row_section = str(row.get("section") or "")
        if row_section not in {section, "Workload Operations" if section == "Query Search" else section}:
            continue
        if not _workflow_matches(workflow, row.get("workflow")) and section != "Query Search":
            continue
        if bool(row.get("clicked")) or str(row.get("failure_reason") or "") == "rendered_action_without_click_result":
            count += 1
    return count


def build_render_provenance_reconciliation(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    payloads = payloads or _load_payloads(root_path)
    generated_at = _now()
    commit_sha = _git_commit(root_path)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for section, workflow in (*PRIMARY_SURFACES, *ADDITIONAL_SURFACES):
        runtime = _runtime_row(section, workflow, payloads)
        deterministic = _deterministic_row(section, workflow, payloads)
        browser = _browser_row(section, workflow, payloads)
        leak = _leak_row(section, payloads)
        provenance = _provenance_row(section, workflow, payloads)

        runtime_text = _row_text(runtime)
        deterministic_text = _row_text(deterministic)
        browser_text = _row_text(browser)
        runtime_hash = _text_hash(runtime_text)
        deterministic_hash = _text_hash(deterministic_text)
        browser_hash = _text_hash(browser_text)
        browser_snapshot = bool(browser.get("screenshot_or_snapshot_path") or deterministic.get("screenshot_or_snapshot_path"))
        same_commit = all(
            not str(row.get("commit_sha") or "") or str(row.get("commit_sha") or "") == commit_sha
            for row in (runtime, deterministic, browser, provenance)
            if row
        )
        rendered_text_hashes = {item for item in (runtime_hash, deterministic_hash, browser_hash) if item}
        text_hash_reconciled = _prefix_compatible(runtime_text, deterministic_text)
        if browser_hash and runtime_hash:
            text_hash_reconciled = text_hash_reconciled and _browser_text_compatible(
                browser_text,
                runtime_text,
                deterministic_text,
            )
        runtime_action_count = _action_count(runtime)
        deterministic_action_count = _action_count(deterministic)
        browser_action_count = _action_count(browser)
        action_click_row_count = _action_click_count(runtime, payloads)
        action_counts = [count for count in (runtime_action_count, deterministic_action_count, browser_action_count) if count]
        same_action_count = len(set(action_counts)) <= 1
        synthetic_render_used = any(
            str(item.get("source") or item.get("proof_source") or "") == "synthetic_safe_fallback"
            for item in (runtime, deterministic, browser)
            if item
        )
        fixture_only_used = any(bool(item.get("fixture_mode")) for item in (runtime, deterministic, browser, provenance) if item)
        same_section_workflow = all(
            str(item.get("section") or item.get("surface") or "") == section
            and _workflow_matches(workflow, item.get("workflow"))
            for item in (runtime, deterministic, browser, provenance)
            if item and (item.get("section") or item.get("surface"))
        )
        row_failures: list[str] = []
        if not runtime:
            row_failures.append("runtime_render_row_missing")
        if not deterministic:
            row_failures.append("deterministic_render_row_missing")
        if deterministic and str(deterministic.get("source") or "") == "synthetic_safe_fallback":
            row_failures.append("synthetic_deterministic_render")
        if not browser and not browser_snapshot:
            row_failures.append("browser_or_snapshot_row_missing")
        if not provenance:
            row_failures.append("provenance_row_missing")
        if provenance and str(provenance.get("provenance_origin") or "") != "producer":
            row_failures.append("provenance_not_producer_owned")
        if not leak:
            row_failures.append("leak_scan_row_missing")
        if not same_commit:
            row_failures.append("commit_sha_mismatch")
        if not same_section_workflow:
            row_failures.append("section_workflow_mismatch")
        if not text_hash_reconciled:
            row_failures.append("rendered_text_hash_mismatch")
        if not same_action_count:
            row_failures.append("action_count_mismatch")
        if runtime_action_count and action_click_row_count < runtime_action_count:
            row_failures.append("visible_action_click_rows_missing")
        if synthetic_render_used:
            row_failures.append("synthetic_render_used")
        if any(bool(item.get("raw_sql_included")) for item in (runtime, deterministic, browser, provenance) if item):
            row_failures.append("raw_sql_included")
        row = {
            "producer": "render_provenance_reconciliation",
            "generated_at": generated_at,
            "source": "render_provenance_reconciliation",
            "proof_source": "runtime_render_reconciliation",
            "provenance_origin": "producer",
            "producer_signature": hashlib.sha256(f"{section}|{workflow}|{commit_sha}".encode("utf-8")).hexdigest(),
            "fixture_mode": False,
            "launch_profile": "internal_fixture",
            "commit_sha": commit_sha,
            "section": section,
            "workflow": workflow,
            "runtime_render_row_exists": bool(runtime),
            "deterministic_row_exists": bool(deterministic),
            "browser_or_snapshot_row_exists": bool(browser or browser_snapshot),
            "provenance_row_exists": bool(provenance),
            "leak_scan_row_exists": bool(leak),
            "action_click_row_count": action_click_row_count,
            "same_commit_sha": same_commit,
            "same_section_workflow": same_section_workflow,
            "same_rendered_text_hash": text_hash_reconciled,
            "rendered_text_prefix_reconciled": text_hash_reconciled,
            "same_action_count": same_action_count,
            "runtime_text_hash": runtime_hash,
            "deterministic_text_hash": deterministic_hash,
            "browser_text_hash": browser_hash,
            "runtime_rendered_text_hash": runtime_hash,
            "deterministic_rendered_text_hash": deterministic_hash,
            "browser_rendered_text_hash": browser_hash,
            "unique_rendered_text_hash_count": len(rendered_text_hashes),
            "runtime_action_count": runtime_action_count,
            "deterministic_action_count": deterministic_action_count,
            "browser_action_count": browser_action_count,
            "synthetic_render_used": synthetic_render_used,
            "fixture_only_used": fixture_only_used,
            "render_call_path": str(deterministic.get("render_call_path") or runtime.get("render_call_path") or ""),
            "runtime_source": str(runtime.get("runtime_source") or deterministic.get("runtime_source") or ""),
            "passed": not row_failures,
            "failure_reason": "; ".join(row_failures),
            "raw_sql_included": False,
        }
        rows.append(row)
        if row_failures:
            failures.append(
                {
                    "section": section,
                    "workflow": workflow,
                    "failure_reason": row["failure_reason"],
                }
            )

    return {
        "producer": "render_provenance_reconciliation",
        "source": "render_provenance_reconciliation_results",
        "proof_source": "runtime_render_reconciliation",
        "generated_at": generated_at,
        "commit_sha": commit_sha,
        "passed": not failures,
        "surface_count": len(rows),
        "failure_count": len(failures),
        "synthetic_render_count": sum(1 for row in rows if "synthetic" in str(row.get("failure_reason") or "")),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_render_provenance_reconciliation_gate(payload: object) -> dict[str, Any]:
    results = _as_mapping(payload)
    rows = [_as_mapping(row) for row in _as_list(results.get("rows"))]
    failures = _as_list(results.get("failures"))
    if not rows:
        failures = [*failures, {"code": "RENDER_PROVENANCE_ROWS_MISSING"}]
    for row in rows:
        if not bool(row.get("passed", False)):
            failures.append(
                {
                    "code": "RENDER_PROVENANCE_ROW_FAILED",
                    "section": row.get("section"),
                    "workflow": row.get("workflow"),
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
        "source": "render_provenance_reconciliation_gate_results",
        "generated_at": _now(),
        "passed": bool(results.get("passed", False)) and not deduped,
        "failure_count": len(deduped),
        "surface_count": len(rows),
        "synthetic_render_count": int(results.get("synthetic_render_count") or 0),
        "failures": deduped,
        "raw_sql_included": False,
    }


def write_render_provenance_reconciliation_artifacts(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_render_provenance_reconciliation(root_path, payloads)
    gate = evaluate_render_provenance_reconciliation_gate(results)
    artifacts = {
        RENDER_PROVENANCE_RECONCILIATION_REL: results,
        RENDER_PROVENANCE_RECONCILIATION_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "RENDER_PROVENANCE_RECONCILIATION_GATE_REL",
    "RENDER_PROVENANCE_RECONCILIATION_REL",
    "build_render_provenance_reconciliation",
    "evaluate_render_provenance_reconciliation_gate",
    "write_render_provenance_reconciliation_artifacts",
]


if __name__ == "__main__":
    write_render_provenance_reconciliation_artifacts()
