"""Action-click gauntlet for launch-facing button and route proof."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
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


def build_action_click_results(payloads: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    actions = build_action_manifest(payloads)
    rendered_actions: list[Mapping[str, Any]] = []
    for row in payloads.get("artifacts/full_app_validation/rendered_fragments.json", []):
        if not isinstance(row, Mapping):
            continue
        for action in row.get("action_like_elements") or []:
            if isinstance(action, Mapping):
                rendered_actions.append(
                    {
                        "section": row.get("section") or row.get("surface") or "",
                        "workflow": row.get("workflow") or "",
                        "label": action.get("label") or "",
                        "stable_key": action.get("stable_key") or action.get("key") or action.get("label") or "",
                        "action_area": action.get("action_area") or "rendered_action",
                    }
                )
    click_by_key: dict[str, list[Mapping[str, Any]]] = {}
    click_by_label: dict[str, list[Mapping[str, Any]]] = {}
    for row in actions:
        if not bool(row.get("clicked")):
            continue
        key = str(row.get("stable_key") or row.get("control_key") or row.get("key") or row.get("action_key") or "").strip()
        label = str(row.get("label") or row.get("action_key") or "").strip()
        if key:
            click_by_key.setdefault(key, []).append(row)
        if label:
            click_by_label.setdefault(label, []).append(row)

    def _select_click(candidates: list[Mapping[str, Any]], rendered_area: str) -> Mapping[str, Any] | None:
        if not candidates:
            return None
        for candidate in candidates:
            if str(candidate.get("action_area") or "").strip() == rendered_area:
                return candidate
        return candidates[0]
    for rendered_action in rendered_actions:
        stable_key = str(rendered_action.get("stable_key") or "").strip()
        label = str(rendered_action.get("label") or "").strip()
        rendered_area = str(rendered_action.get("action_area") or "").strip()
        candidates = list(click_by_key.get(stable_key, [])) if stable_key else []
        if not candidates and label:
            candidates = list(click_by_label.get(label, []))
        if not candidates and stable_key:
            candidates = [
                row
                for key, rows in click_by_key.items()
                if key.startswith(stable_key) or stable_key.startswith(key)
                for row in rows
            ]
        matched_click = _select_click(candidates, rendered_area)
        matched = bool(matched_click)
        area_matches = (
            not matched_click
            or not rendered_area
            or str(matched_click.get("action_area") or "").strip() == rendered_area
        )
        if not matched:
            actions.append(
                {
                    "area": "rendered_action",
                    "action_area": str(rendered_action.get("action_area") or "rendered_action"),
                    "section": rendered_action.get("section", ""),
                    "workflow": rendered_action.get("workflow", ""),
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
        elif not area_matches:
            observed_area = str(matched_click.get("action_area") or "") if matched_click is not None else ""
            actions.append(
                {
                    "area": "rendered_action",
                    "action_area": rendered_area,
                    "section": rendered_action.get("section", ""),
                    "workflow": rendered_action.get("workflow", ""),
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
    failures = [
        row
        for row in actions
        if not bool(row.get("passed"))
        or (str(row.get("area") or "") in {"button", "settings", "export", "case_payload"} and not bool(row.get("clicked")))
    ]
    manifest = {
        "source": "action_click_manifest",
        "generated_at": _now(),
        "passed": not failures,
        "action_count": len(actions),
        "actions": actions,
        "raw_sql_included": False,
    }
    results = {
        "source": "action_click_results",
        "generated_at": manifest["generated_at"],
        "passed": not failures,
        "failure_count": len(failures),
        "action_count": len(actions),
        "clicked_count": sum(1 for row in actions if bool(row.get("clicked"))),
        "failed_action_count": len(failures),
        "rows": actions,
        "actions": actions,
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
    manifest, results = build_action_click_results(payloads)
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
