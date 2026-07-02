"""Delete-first cleanup inventory for launch-surface ownership."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


CLEANUP_DIR = "artifacts/cleanup"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

DELETE_FIRST_INVENTORY_REL = f"{CLEANUP_DIR}/delete_first_inventory.json"
DELETE_FIRST_RESULTS_REL = f"{CLEANUP_DIR}/delete_first_cleanup_results.json"
DELETE_FIRST_GATE_REL = f"{LAUNCH_READINESS_DIR}/delete_first_cleanup_gate_results.json"

OLD_SURFACE_MARKERS = (
    "splash",
    "launchpad",
    "watch floor",
    "command deck",
    "lane board",
)

CURRENT_RUNTIME_SECTIONS = {
    "executive_landing",
    "dba_control_room",
    "alert_center",
    "cost_contract",
    "workload_operations",
    "security_posture",
    "security_monitoring",
    "query_search",
    "advanced_scope",
    "settings",
    "setup_health",
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _slug(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()


def _contains_old_marker(path: Path) -> str:
    path_text = str(path).replace("\\", "/").lower()
    name_text = path.stem.lower()
    for marker in OLD_SURFACE_MARKERS:
        normalized = marker.replace(" ", "_")
        if marker == "splash" and marker in name_text:
            return marker
        if normalized in name_text or marker in name_text or f"/{normalized}" in path_text:
            return marker
    return ""


def _base_row(root: Path, path: Path, item_type: str) -> dict[str, Any]:
    rel = str(path.relative_to(root)).replace("\\", "/")
    return {
        "item_id": rel,
        "path": rel,
        "item_type": item_type,
        "owner": "",
        "purpose": "",
        "user_visible_feature": "",
        "launch_value": "",
        "runtime_path": "",
        "admin_only": False,
        "daily_safe": True,
        "classification": "unknown_blocker",
        "keep_reason": "",
        "replacement_if_deleted": "",
        "delete_plan": "",
        "raw_sql_included": False,
    }


def _classify_python(root: Path, path: Path) -> dict[str, Any]:
    row = _base_row(root, path, "python_module")
    rel = row["path"]
    slug = _slug(rel)
    marker = _contains_old_marker(path)
    if rel.startswith("tests/"):
        row.update(
            classification="keep_test",
            owner="QA/launch guardrails",
            purpose="Automated launch regression coverage.",
            user_visible_feature="release validation",
            launch_value="prevents regressions in retained runtime/admin paths",
            runtime_path="test_only",
            daily_safe=True,
            keep_reason="test module",
        )
    elif rel.startswith("tools/contracts/"):
        row.update(
            classification="keep_release_gate",
            owner="release readiness",
            purpose="Launch gate or artifact producer.",
            user_visible_feature="release validation",
            launch_value="blocks unsafe launch states",
            runtime_path="release_gate",
            admin_only=True,
            daily_safe=True,
            keep_reason="release gate",
        )
    elif rel.startswith(".overwatch_final/"):
        if marker and slug not in CURRENT_RUNTIME_SECTIONS:
            row.update(
                classification="delete_obsolete",
                owner="Decision Workspace cleanup",
                purpose="Legacy surface remnant.",
                user_visible_feature="none",
                launch_value="none",
                runtime_path="not_on_launch_surface",
                daily_safe=False,
                replacement_if_deleted=".overwatch_final/section_dispatch.py current launch routes",
                delete_plan="quarantine/remove after verifying no current route imports it",
            )
        else:
            classification = "keep_admin_setup" if slug in {"setup_health", "settings"} else "keep_runtime"
            row.update(
                classification=classification,
                owner="Decision Workspace runtime",
                purpose="Current Streamlit launch surface or shared runtime helper.",
                user_visible_feature=slug.replace("_", " "),
                launch_value="required by current packet-first app surface",
                runtime_path=rel,
                admin_only=classification == "keep_admin_setup",
                daily_safe=classification != "keep_admin_setup",
                keep_reason="current runtime path",
            )
    return row


def _classify_sql(root: Path, path: Path) -> dict[str, Any]:
    row = _base_row(root, path, "sql_object")
    rel_upper = row["path"].upper()
    if "DROP" in rel_upper:
        classification = "keep_admin_setup"
        purpose = "Rollback/drop support."
    elif "VALIDATION" in rel_upper:
        classification = "keep_live_validation"
        purpose = "Deployment/setup validation."
    elif (
        "SETUP" in rel_upper
        or "MART" in rel_upper
        or "PROCEDURE" in rel_upper
        or "/GENERATED/" in rel_upper
        or path.name.upper().startswith("OVERWATCH_")
    ):
        classification = "keep_admin_setup"
        purpose = "Admin setup and refresh object definition."
    else:
        classification = "unknown_blocker"
        purpose = ""
    row.update(
        classification=classification,
        owner="Snowflake setup owner" if classification != "unknown_blocker" else "",
        purpose=purpose,
        user_visible_feature="Settings/Admin Setup Health" if classification != "unknown_blocker" else "",
        launch_value="required for local/live setup validation" if classification != "unknown_blocker" else "",
        runtime_path="admin_setup" if classification != "unknown_blocker" else "",
        admin_only=True,
        daily_safe=True,
        keep_reason="admin/setup SQL" if classification != "unknown_blocker" else "",
        replacement_if_deleted="",
    )
    return row


def _inventory_paths(root: Path) -> Iterable[tuple[Path, str]]:
    for base, item_type in (
        (root / ".overwatch_final", "python_module"),
        (root / "tools" / "contracts", "python_module"),
        (root / "tests", "python_module"),
    ):
        if base.exists():
            yield from ((path, item_type) for path in sorted(base.rglob("*.py")) if "__pycache__" not in path.parts)
    snowflake = root / "snowflake"
    if snowflake.exists():
        yield from ((path, "sql_object") for path in sorted(snowflake.rglob("*.sql")))


def build_delete_first_inventory(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for path, item_type in _inventory_paths(root):
        row = _classify_sql(root, path) if item_type == "sql_object" else _classify_python(root, path)
        rows.append(row)
        if row["path"] == ".overwatch_final/sections/query_workbench.py":
            failures.append(
                {
                    "item_id": row["item_id"],
                    "reason": "retired query_workbench module returned to production source",
                }
            )
        classification = str(row.get("classification") or "")
        if classification == "unknown_blocker":
            failures.append({"item_id": row["item_id"], "reason": "retained item is unclassified"})
        if classification.startswith("keep") and not all(row.get(key) for key in ("owner", "purpose", "launch_value", "keep_reason")):
            failures.append({"item_id": row["item_id"], "reason": "kept item missing owner/purpose/launch value/keep reason"})
        if classification in {"delete_obsolete", "delete_duplicate", "merge_duplicate"} and not (
            row.get("delete_plan") or row.get("replacement_if_deleted")
        ):
            failures.append({"item_id": row["item_id"], "reason": "obsolete item missing delete or replacement plan"})
        if not bool(row.get("daily_safe")) and classification.startswith("keep") and not bool(row.get("admin_only")):
            failures.append({"item_id": row["item_id"], "reason": "kept runtime item is not daily safe"})
    return {
        "source": "delete_first_cleanup",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "item_count": len(rows),
        "delete_candidate_count": sum(1 for row in rows if str(row.get("classification") or "").startswith("delete")),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_delete_first_cleanup_gate(inventory: Mapping[str, Any]) -> dict[str, Any]:
    failures = list(inventory.get("failures") or [])
    return {
        "source": "delete_first_cleanup_gate_results",
        "generated_at": _now(),
        "passed": not failures and bool(inventory.get("passed", True)),
        "failure_count": len(failures),
        "item_count": int(inventory.get("item_count") or 0),
        "delete_candidate_count": int(inventory.get("delete_candidate_count") or 0),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_delete_first_cleanup_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    inventory = build_delete_first_inventory(root_path)
    results = {
        "source": "delete_first_cleanup_results",
        "generated_at": _now(),
        "passed": bool(inventory.get("passed")),
        "failure_count": int(inventory.get("failure_count") or 0),
        "item_count": int(inventory.get("item_count") or 0),
        "delete_candidate_count": int(inventory.get("delete_candidate_count") or 0),
        "failures": inventory.get("failures", []),
        "raw_sql_included": False,
    }
    gate = evaluate_delete_first_cleanup_gate(inventory)
    _write_json(root_path / DELETE_FIRST_INVENTORY_REL, inventory)
    _write_json(root_path / DELETE_FIRST_RESULTS_REL, results)
    _write_json(root_path / DELETE_FIRST_GATE_REL, gate)
    return {
        DELETE_FIRST_INVENTORY_REL: inventory,
        DELETE_FIRST_RESULTS_REL: results,
        DELETE_FIRST_GATE_REL: gate,
    }


if __name__ == "__main__":
    artifacts = write_delete_first_cleanup_artifacts(Path("."))
    gate = artifacts[DELETE_FIRST_GATE_REL]
    if not bool(gate.get("passed")):
        raise SystemExit(1)


__all__ = [
    "DELETE_FIRST_GATE_REL",
    "DELETE_FIRST_INVENTORY_REL",
    "DELETE_FIRST_RESULTS_REL",
    "OLD_SURFACE_MARKERS",
    "build_delete_first_inventory",
    "evaluate_delete_first_cleanup_gate",
    "write_delete_first_cleanup_artifacts",
]
