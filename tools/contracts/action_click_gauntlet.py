"""Action-click gauntlet for launch-facing button and route proof."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from tools.contracts.full_app_launch_gauntlet import (
    build_action_manifest,
    evaluate_simple_gate,
)


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

ACTION_CLICK_MANIFEST_REL = f"{FULL_APP_VALIDATION_DIR}/action_click_manifest.json"
ACTION_CLICK_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/action_click_results.json"
LIVE_FEATURE_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/live_feature_results.json"
ACTION_CLICK_GATE_REL = f"{LAUNCH_READINESS_DIR}/action_click_gate_results.json"
LIVE_FEATURE_GATE_REL = f"{LAUNCH_READINESS_DIR}/live_feature_gate_results.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_commit(root: Path | None = None) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root or Path.cwd()),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _producer_signature(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_json(root: Path, rel: str) -> Any:
    path = root / rel
    if not path.exists():
        return [] if rel.endswith("_results.json") else {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_payloads(root: Path) -> dict[str, Any]:
    rels = (
        "artifacts/full_app_validation/view_results.json",
        "artifacts/full_app_validation/rendered_fragments.json",
        "artifacts/full_app_validation/button_click_results.json",
        "artifacts/full_app_validation/settings_action_results.json",
        "artifacts/full_app_validation/live_feature_results.json",
        "artifacts/full_app_validation/export_results.json",
        "artifacts/full_app_validation/case_payload_results.json",
        "artifacts/full_app_validation/query_search_results.json",
        "artifacts/full_app_validation/evidence_loader_call_matrix.json",
        "artifacts/full_app_validation/stress_results.json",
    )
    return {rel: _load_json(root, rel) for rel in rels}


def _truthy(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"false", "0", "no", "off"}:
        return False
    if text in {"true", "1", "yes", "on"}:
        return True
    return default


def _normalize_id(*parts: object) -> str:
    return "::".join(str(part or "").strip() for part in parts if str(part or "").strip())


def _row_key(row: Mapping[str, Any]) -> str:
    return str(row.get("stable_key") or row.get("control_key") or row.get("key") or row.get("action_key") or "").strip()


def _row_action_id(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("clicked_action_id") or row.get("rendered_action_id") or row.get("id") or "").strip()
    if explicit:
        return explicit
    key = _row_key(row)
    return _normalize_id(row.get("section"), row.get("workflow"), key) if key else ""


def _same_surface(rendered_action: Mapping[str, Any], click_row: Mapping[str, Any]) -> bool:
    return (
        str(rendered_action.get("section") or "") == str(click_row.get("section") or "")
        and str(rendered_action.get("workflow") or "") == str(click_row.get("workflow") or "")
    )


def _target_mismatch(click_row: Mapping[str, Any]) -> bool:
    expected = click_row.get("expected_target")
    observed = click_row.get("observed_target")
    if not expected or not observed:
        return False
    return str(expected) != str(observed)


def _count(row: Mapping[str, Any], key: str) -> int:
    try:
        return int(float(row.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _stamp_action_rows(rows: list[dict[str, Any]], *, generated_at: str, commit_sha: str) -> list[dict[str, Any]]:
    stamped: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        next_row = dict(row)
        next_row.setdefault("producer", "action_click_gauntlet")
        next_row.setdefault("generated_at", generated_at)
        next_row.setdefault("source", "clicked_action")
        next_row.setdefault("runtime_source", "action_click_gauntlet")
        next_row.setdefault("proof_source", "clicked_action")
        next_row.setdefault("provenance_origin", "producer")
        next_row.setdefault("commit_sha", commit_sha)
        next_row.setdefault("raw_sql_included", False)
        next_row.setdefault("runtime_artifact_row_index", index)
        next_row.setdefault(
            "producer_signature",
            _producer_signature(
                next_row.get("producer"),
                next_row.get("source"),
                ACTION_CLICK_RESULTS_REL,
                index,
                next_row.get("commit_sha"),
            ),
        )
        stamped.append(next_row)
    return stamped


def build_action_click_results(
    payloads: Mapping[str, Any],
    *,
    current_commit: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    actions = build_action_manifest(payloads)
    rendered_actions: list[Mapping[str, Any]] = []
    for row in payloads.get("artifacts/full_app_validation/rendered_fragments.json", []):
        if not isinstance(row, Mapping):
            continue
        for action in row.get("action_like_elements") or []:
            if isinstance(action, Mapping):
                stable_key = str(action.get("stable_key") or action.get("key") or "").strip()
                rendered_action_id = str(action.get("rendered_action_id") or "").strip()
                if not rendered_action_id and stable_key:
                    rendered_action_id = _normalize_id(row.get("section") or row.get("surface"), row.get("workflow"), stable_key)
                rendered_actions.append(
                    {
                        "rendered_action_id": rendered_action_id,
                        "source_render_row_id": str(action.get("source_render_row_id") or row.get("id") or row.get("runtime_artifact_row_index") or ""),
                        "section": row.get("section") or row.get("surface") or "",
                        "workflow": row.get("workflow") or "",
                        "label": action.get("label") or "",
                        "stable_key": stable_key,
                        "action_area": action.get("action_area") or "rendered_action",
                        "data_interactive": _truthy(action.get("data_interactive", action.get("interactive", action.get("data-interactive", True)))),
                        "expected_target": action.get("expected_target") or "",
                    }
                )
    click_by_key: dict[str, list[Mapping[str, Any]]] = {}
    click_by_action_id: dict[str, list[Mapping[str, Any]]] = {}
    for row in actions:
        if not bool(row.get("clicked")):
            continue
        key = _row_key(row)
        action_id = _row_action_id(row)
        if key:
            click_by_key.setdefault(key, []).append(row)
        if action_id:
            click_by_action_id.setdefault(action_id, []).append(row)

    for rendered_action in rendered_actions:
        if not _truthy(rendered_action.get("data_interactive"), True):
            continue
        rendered_action_id = str(rendered_action.get("rendered_action_id") or "").strip()
        stable_key = str(rendered_action.get("stable_key") or "").strip()
        label = str(rendered_action.get("label") or "").strip()
        rendered_area = str(rendered_action.get("action_area") or "").strip()
        if not stable_key and not rendered_action_id:
            actions.append(
                {
                    "area": "rendered_action",
                    "action_area": rendered_area or "rendered_action",
                    "section": rendered_action.get("section", ""),
                    "workflow": rendered_action.get("workflow", ""),
                    "action_key": label or "rendered_action",
                    "expected_behavior": "interactive rendered action declares stable_key or rendered_action_id",
                    "observed_behavior": "missing stable action identity",
                    "clicked": False,
                    "query_count": 0,
                    "session_open_count": 0,
                    "direct_sql_count": 0,
                    "account_usage_count": 0,
                    "passed": False,
                    "failure_reason": "rendered_action_missing_stable_key",
                    "raw_sql_included": False,
                }
            )
            continue
        candidates = list(click_by_action_id.get(rendered_action_id, [])) if rendered_action_id else []
        if not candidates and stable_key:
            candidates = list(click_by_key.get(stable_key, []))
        area_candidates = [
            row for row in candidates
            if not rendered_area or str(row.get("action_area") or "").strip() == rendered_area
        ]
        surface_candidates = [row for row in area_candidates if _same_surface(rendered_action, row)]
        matched_click = surface_candidates[0] if surface_candidates else None
        if not candidates:
            actions.append(
                {
                    "area": "rendered_action",
                    "action_area": str(rendered_action.get("action_area") or "rendered_action"),
                    "section": rendered_action.get("section", ""),
                    "workflow": rendered_action.get("workflow", ""),
                    "rendered_action_id": rendered_action_id,
                    "source_render_row_id": rendered_action.get("source_render_row_id", ""),
                    "action_key": stable_key or label or "rendered_action",
                    "expected_behavior": "visible action-like element has a matching click artifact",
                    "observed_behavior": "missing click result",
                    "clicked": False,
                    "query_count": 0,
                    "session_open_count": 0,
                    "direct_sql_count": 0,
                    "account_usage_count": 0,
                    "passed": False,
                    "failure_reason": "rendered_action_without_click_result",
                    "raw_sql_included": False,
                }
            )
            continue
        if not area_candidates:
            observed_area = ", ".join(sorted({str(row.get("action_area") or "") for row in candidates}))
            actions.append(
                {
                    "area": "rendered_action",
                    "action_area": rendered_area,
                    "section": rendered_action.get("section", ""),
                    "workflow": rendered_action.get("workflow", ""),
                    "rendered_action_id": rendered_action_id,
                    "source_render_row_id": rendered_action.get("source_render_row_id", ""),
                    "action_key": stable_key or label or "rendered_action",
                    "expected_behavior": "rendered action area matches click artifact area",
                    "observed_behavior": observed_area,
                    "clicked": True,
                    "query_count": 0,
                    "session_open_count": 0,
                    "direct_sql_count": 0,
                    "account_usage_count": 0,
                    "passed": False,
                    "failure_reason": "rendered_action_area_mismatch",
                    "raw_sql_included": False,
                }
            )
            continue
        if not matched_click:
            observed_surface = ", ".join(
                sorted(
                    {
                        f"{row.get('section') or ''} / {row.get('workflow') or ''}"
                        for row in area_candidates
                    }
                )
            )
            actions.append(
                {
                    "area": "rendered_action",
                    "action_area": rendered_area,
                    "section": rendered_action.get("section", ""),
                    "workflow": rendered_action.get("workflow", ""),
                    "rendered_action_id": rendered_action_id,
                    "source_render_row_id": rendered_action.get("source_render_row_id", ""),
                    "action_key": stable_key or label or "rendered_action",
                    "expected_behavior": "click artifact matches the rendered action section and workflow",
                    "observed_behavior": observed_surface,
                    "clicked": True,
                    "query_count": 0,
                    "session_open_count": 0,
                    "direct_sql_count": 0,
                    "account_usage_count": 0,
                    "passed": False,
                    "failure_reason": "rendered_action_surface_mismatch",
                    "raw_sql_included": False,
                }
            )
            continue
        if _target_mismatch(matched_click):
            actions.append(
                {
                    "area": "rendered_action",
                    "action_area": rendered_area,
                    "section": rendered_action.get("section", ""),
                    "workflow": rendered_action.get("workflow", ""),
                    "rendered_action_id": rendered_action_id,
                    "source_render_row_id": rendered_action.get("source_render_row_id", ""),
                    "action_key": stable_key or label or "rendered_action",
                    "expected_behavior": "click expected_target equals observed_target",
                    "observed_behavior": str(matched_click.get("observed_target") or ""),
                    "clicked": True,
                    "query_count": _count(matched_click, "query_count"),
                    "session_open_count": _count(matched_click, "session_open_count"),
                    "direct_sql_count": _count(matched_click, "direct_sql_count") + _count(matched_click, "direct_sql_event_count"),
                    "account_usage_count": _count(matched_click, "account_usage_count"),
                    "passed": False,
                    "failure_reason": "rendered_action_target_mismatch",
                    "raw_sql_included": False,
                }
            )
            continue
        if rendered_area == "route_action" and (
            _count(matched_click, "query_count")
            or _count(matched_click, "session_open_count")
            or _count(matched_click, "direct_sql_count")
            or _count(matched_click, "direct_sql_event_count")
            or _count(matched_click, "account_usage_count")
        ):
            actions.append(
                {
                    "area": "rendered_action",
                    "action_area": rendered_area,
                    "section": rendered_action.get("section", ""),
                    "workflow": rendered_action.get("workflow", ""),
                    "rendered_action_id": rendered_action_id,
                    "source_render_row_id": rendered_action.get("source_render_row_id", ""),
                    "action_key": stable_key or label or "rendered_action",
                    "expected_behavior": "route actions are query/session/direct-SQL free",
                    "observed_behavior": "route action crossed a query/session boundary",
                    "clicked": True,
                    "query_count": _count(matched_click, "query_count"),
                    "session_open_count": _count(matched_click, "session_open_count"),
                    "direct_sql_count": _count(matched_click, "direct_sql_count") + _count(matched_click, "direct_sql_event_count"),
                    "account_usage_count": _count(matched_click, "account_usage_count"),
                    "passed": False,
                    "failure_reason": "route_action_query_boundary_violation",
                    "raw_sql_included": False,
                }
            )
    generated_at = _now()
    commit_sha = current_commit if current_commit is not None else _git_commit()
    signed_actions = _stamp_action_rows([dict(row) for row in actions], generated_at=generated_at, commit_sha=commit_sha)
    failures = [
        row
        for row in signed_actions
        if not bool(row.get("passed"))
        or (str(row.get("area") or "") in {"button", "settings", "export", "case_payload"} and not bool(row.get("clicked")))
    ]
    manifest = {
        "source": "action_click_manifest",
        "producer": "action_click_gauntlet",
        "producer_signature": _producer_signature("action_click_gauntlet", "action_click_manifest", ACTION_CLICK_MANIFEST_REL, "artifact", commit_sha),
        "provenance_origin": "producer",
        "commit_sha": commit_sha,
        "generated_at": generated_at,
        "passed": not failures,
        "action_count": len(signed_actions),
        "actions": signed_actions,
        "raw_sql_included": False,
    }
    results = {
        "source": "action_click_results",
        "generated_at": manifest["generated_at"],
        "producer": "action_click_gauntlet",
        "producer_signature": _producer_signature("action_click_gauntlet", "action_click_results", ACTION_CLICK_RESULTS_REL, "artifact", commit_sha),
        "provenance_origin": "producer",
        "commit_sha": commit_sha,
        "passed": not failures,
        "failure_count": len(failures),
        "action_count": len(signed_actions),
        "clicked_count": sum(1 for row in signed_actions if bool(row.get("clicked"))),
        "failed_action_count": len(failures),
        "rows": signed_actions,
        "actions": signed_actions,
        "failures": failures,
        "raw_sql_included": False,
    }
    return manifest, results


def evaluate_action_click_gate(payload: object) -> dict[str, Any]:
    if isinstance(payload, tuple) and len(payload) == 2:
        payload = payload[1] if isinstance(payload[1], Mapping) else {}
    if not isinstance(payload, Mapping):
        payload = {}
    return evaluate_simple_gate(
        payload,
        source="action_click_gate_results",
        artifact=ACTION_CLICK_RESULTS_REL,
    )


def evaluate_live_feature_gate(payload: object) -> dict[str, Any]:
    rows: list[Any] = payload if isinstance(payload, list) else []
    failures = [
        row for row in rows
        if isinstance(row, Mapping)
        and (
            not bool(row.get("passed", True))
            or bool(row.get("first_paint_invocation"))
            or bool(row.get("route_invocation"))
            or not bool(row.get("explicit_click_required", True))
            or not bool(row.get("admin_or_advanced_gated", True))
        )
    ]
    return {
        "source": "live_feature_gate_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "live_feature_count": len(rows),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_action_click_gauntlet_artifacts(root: Path | str = ".", payloads: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payloads is None:
        payloads = _load_payloads(root_path)
    manifest, results = build_action_click_results(payloads, current_commit=_git_commit(root_path))
    artifacts: dict[str, Any] = {
        ACTION_CLICK_MANIFEST_REL: manifest,
        ACTION_CLICK_RESULTS_REL: results,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "ACTION_CLICK_GATE_REL",
    "ACTION_CLICK_MANIFEST_REL",
    "ACTION_CLICK_RESULTS_REL",
    "LIVE_FEATURE_GATE_REL",
    "LIVE_FEATURE_RESULTS_REL",
    "build_action_click_results",
    "evaluate_action_click_gate",
    "evaluate_live_feature_gate",
    "write_action_click_gauntlet_artifacts",
]


if __name__ == "__main__":
    write_action_click_gauntlet_artifacts()
