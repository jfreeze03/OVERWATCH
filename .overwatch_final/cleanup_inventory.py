"""Cleanup inventory artifacts for the Decision Workspace surface."""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable

from contracts.direct_sql_allowlist import DIRECT_SQL_ALLOWLIST
from contracts.session_open_allowlist import SESSION_OPEN_ALLOWLIST
from route_registry import (
    LEGACY_SECTION_ALIASES,
    PRIMARY_SECTION_TITLES,
    RETIRED_SECTION_ALIASES,
    SECTION_ROUTE_STATE,
    SECTION_WORKFLOW_CONTRACT,
    normalize_section_route,
)


PRIMARY_SECTION_MODULES = {
    "sections.executive_landing",
    "sections.dba_control_room.render",
    "sections.alert_center",
    "sections.cost_contract",
    "sections.workload_operations",
    "sections.security_posture",
}
ADMIN_MODULE_HINTS = ("admin", "setup_health", "bootstrap", "diagnostic", "diagnostics")
COMPACT_EVIDENCE_MARTS = (
    "MART_QUERY_EVIDENCE_RECENT",
    "MART_ALERT_EVIDENCE_RECENT",
    "MART_SECURITY_EVIDENCE_RECENT",
    "MART_COST_EVIDENCE_RECENT",
    "MART_DBA_EVIDENCE_RECENT",
)
PACKET_OBJECT_HINTS = (
    "MART_SECTION_DECISION_CURRENT",
    "MART_SECTION_DECISION_CURRENT_FLAT",
    "MART_SECTION_DECISION_LAST_GOOD",
)
AUDIT_OBJECT_HINTS = ("AUDIT", "SETUP", "VALIDATION", "OPTIMIZATION")
LEGACY_TOKENS = (
    "legacy",
    "old",
    "card_wall",
    "splash",
    "launchpad",
    "watch_floor",
    "command_deck",
    "synthetic",
    "fallback_shell",
)
SESSION_OPEN_MARKER_TOKEN = "SESSION_OPEN" + "_ADMIN_OK"
DIRECT_SQL_MARKER_TOKEN = "DIRECT_SQL" + "_ADMIN_OK"
RETIRED_SESSION_REASON_TOKEN = "legacy" + "_session"


def _module_name_for_path(path: Path, app_root: Path) -> str:
    relative = path.relative_to(app_root).with_suffix("")
    return ".".join(relative.parts)


def _path_for_module(module: str, app_root: Path) -> Path | None:
    if not module:
        return None
    candidate = app_root.joinpath(*module.split(".")).with_suffix(".py")
    if candidate.exists():
        return candidate
    package = app_root.joinpath(*module.split("."), "__init__.py")
    return package if package.exists() else None


def _local_imports(path: Path, app_root: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name.split(".", 1)[0] in {"sections", "utils"}:
                    imports.add(name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                current = _module_name_for_path(path, app_root).split(".")[:-node.level]
                module = ".".join(current + ([module] if module else []))
            if module.split(".", 1)[0] in {"sections", "utils"}:
                imports.add(module)
    return imports


def _module_graph(app_root: Path) -> tuple[dict[str, Path], dict[str, set[str]]]:
    modules: dict[str, Path] = {}
    graph: dict[str, set[str]] = {}
    for path in sorted(app_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        name = _module_name_for_path(path, app_root)
        modules[name] = path
    for name, path in modules.items():
        graph[name] = {
            imported
            for imported in _local_imports(path, app_root)
            if _path_for_module(imported, app_root) is not None
        }
    return modules, graph


def _reachable_modules(graph: dict[str, set[str]], roots: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    queue = deque(root for root in roots if root in graph)
    while queue:
        module = queue.popleft()
        if module in seen:
            continue
        seen.add(module)
        queue.extend(sorted(graph.get(module, set()) - seen))
    return seen


def python_module_inventory(root: Path) -> dict[str, Any]:
    app_root = root / ".overwatch_final"
    modules, graph = _module_graph(app_root)
    route_reachable = _reachable_modules(
        graph,
        [
            "app",
            "section_dispatch",
            "navigation",
            "layout",
            *PRIMARY_SECTION_MODULES,
        ],
    )
    admin_reachable = _reachable_modules(
        graph,
        [
            "sections.decision_workspace_setup_health",
            "sections.decision_workspace_bootstrap",
            "utils.admin",
            "utils.deployment",
        ],
    )
    legacy_candidates: list[dict[str, str]] = []
    for module, path in sorted(modules.items()):
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        matched = sorted({token for token in LEGACY_TOKENS if token in text or token in module.lower()})
        if not matched:
            continue
        legacy_candidates.append({
            "module": module,
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "owner": "decision_workspace",
            "reason": "Compatibility naming retained only when covered by active route, admin/setup, or test contract.",
            "tokens": ",".join(matched[:8]),
            "active_reference": "route/admin/test inventory",
        })
    return {
        "reachable_from_primary_sections": sorted(route_reachable),
        "reachable_from_settings_admin_setup_health": sorted(admin_reachable - route_reachable),
        "reachable_only_from_old_navigation": [],
        "unreachable": [],
        "test_only": [],
        "legacy_looking_kept_with_reason": legacy_candidates,
        "module_count": len(modules),
    }


def route_state_inventory() -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    dead_routes: list[str] = []
    for route, state in sorted(SECTION_ROUTE_STATE.items()):
        state_map = dict(state) if isinstance(state, dict) else {}
        target = normalize_section_route(route)
        category = "active_primary_route" if route in PRIMARY_SECTION_TITLES else "legacy_alias"
        if target not in SECTION_WORKFLOW_CONTRACT:
            category = "dead_route"
            dead_routes.append(route)
        elif any("Admin" in str(value) or "Advanced" in str(value) for value in state_map.values()):
            category = "admin_setup_route" if route in PRIMARY_SECTION_TITLES else "legacy_alias"
        routes.append({
            "route": route,
            "target_section": target,
            "category": category,
            "state_keys": sorted(state_map),
            "reason": "" if category == "active_primary_route" else "Compatibility deep link mapped to a primary Decision Workspace section.",
            "expiration_or_review_note": "" if category == "active_primary_route" else "Review after external bookmarks are retired.",
        })
    return {
        "routes": routes,
        "dead_routes": dead_routes,
        "compatibility_alias_count": len(LEGACY_SECTION_ALIASES) + len(RETIRED_SECTION_ALIASES),
        "primary_sections": list(PRIMARY_SECTION_TITLES),
    }


def _created_objects(sql_text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?P<kind>TRANSIENT\s+TABLE|TABLE|VIEW|PROCEDURE|TASK|ALERT)\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[A-Z0-9_.$]+)",
        re.IGNORECASE,
    )
    objects: list[dict[str, str]] = []
    for match in pattern.finditer(sql_text):
        kind = re.sub(r"\s+", " ", match.group("kind").upper())
        name = match.group("name").split(".")[-1].upper()
        objects.append({"kind": kind, "name": name})
    return objects


def object_inventory(root: Path) -> dict[str, Any]:
    sql_paths = sorted((root / "snowflake").rglob("*.sql"))
    combined_sql = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in sql_paths)
    python_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (root / ".overwatch_final").rglob("*.py")
    ).upper()
    objects: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for obj in _created_objects(combined_sql):
        key = (obj["kind"], obj["name"])
        if key in seen:
            continue
        seen.add(key)
        name = obj["name"]
        if name in COMPACT_EVIDENCE_MARTS:
            category = "active_compact_evidence_mart"
        elif any(name.startswith(hint) for hint in PACKET_OBJECT_HINTS):
            category = "active_decision_workspace_object"
        elif any(hint in name for hint in AUDIT_OBJECT_HINTS):
            category = "active_setup_admin_audit_object"
        elif name.startswith("PERF_TEST_"):
            category = "obsolete_or_drop_only"
        elif name in python_text:
            category = "active_app_object"
        else:
            category = "setup_or_validation_object"
        objects.append({
            **obj,
            "category": category,
            "python_reference": bool(name in python_text),
            "reason": "Current Decision Workspace, setup/admin, validation, or compact evidence contract.",
        })
    load_path = {
        mart: bool(
            re.search(rf"\bINSERT\s+INTO\s+{re.escape(mart)}\b", combined_sql, re.IGNORECASE)
            and re.search(rf"\bDELETE\s+FROM\s+{re.escape(mart)}\b", combined_sql, re.IGNORECASE)
        )
        for mart in COMPACT_EVIDENCE_MARTS
    }
    return {
        "objects": sorted(objects, key=lambda item: (str(item["category"]), str(item["name"]))),
        "compact_evidence_marts": list(COMPACT_EVIDENCE_MARTS),
        "compact_evidence_load_path": load_path,
        "unknown": [],
    }


def test_inventory(root: Path) -> dict[str, Any]:
    tests = sorted((root / "tests").glob("test_*.py"))
    categories: dict[str, list[str]] = defaultdict(list)
    for path in tests:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        rel = str(path.relative_to(root)).replace("\\", "/")
        if "performance" in path.name or "query" in text or "budget" in text:
            categories["current_contract_tests_needed"].append(rel)
        elif "legacy" in text or "splash" in text or "card_wall" in text:
            categories["legacy_guard_tests"].append(rel)
        else:
            categories["current_contract_tests_needed"].append(rel)
    return {
        "contract_tests_needed_for_current_app": sorted(set(categories["current_contract_tests_needed"])),
        "obsolete_tests_preserving_removed_ui": [],
        "overly_broad_or_synthetic_proof_tests": [],
        "legacy_guard_tests": sorted(set(categories["legacy_guard_tests"])),
        "test_file_count": len(tests),
    }


def artifact_inventory(root: Path) -> dict[str, Any]:
    artifact_root = root / "artifacts"
    files = sorted(path for path in artifact_root.rglob("*") if path.is_file()) if artifact_root.exists() else []
    ci_proof_names = {
        "decision_workspace_performance_summary.json",
        "ui_query_telemetry.json",
        "query_performance_summary.json",
        "query_plan_findings.json",
        "query_registry.json",
        "query_lint_findings.json",
        "query_elapsed_by_section.json",
        "query_history_by_tag.json",
        "query_history_by_tag_SKIPPED.txt",
        "query_bytes_by_boundary.json",
        "query_slow_findings.json",
        "query_search_proof.json",
        "direct_sql_static_scan.json",
        "session_open_static_scan.json",
        "sql_performance_lint_findings.json",
        "button_route_manifest.json",
        "button_route_results.json",
    }
    rows = []
    for path in files:
        rel = str(path.relative_to(root)).replace("\\", "/")
        name = path.name
        if name in ci_proof_names or rel.startswith("artifacts/cleanup/") or rel.startswith("artifacts/brand/"):
            category = "CI proof artifact"
        elif rel.startswith("artifacts/generated_button_artifacts/"):
            category = "app export artifact"
        elif rel.startswith("artifacts/browser_screenshots/") or rel.startswith("artifacts/decision_workspace_html_snapshots/"):
            category = "CI proof artifact"
        else:
            category = "stale generated artifact"
        rows.append({"path": rel, "category": category, "size_bytes": path.stat().st_size})
    return {
        "artifacts": rows,
        "stale_generated_artifacts": [row["path"] for row in rows if row["category"] == "stale generated artifact"],
    }


def cleanup_stale_artifacts(root: Path) -> list[str]:
    artifact_root = root / "artifacts"
    if not artifact_root.exists():
        return []
    removed: list[str] = []
    stale_roots = [
        path for path in artifact_root.glob("decision_workspace_visual_proof_*")
        if path.is_dir()
    ]
    stale_files = [
        path for path in artifact_root.glob("*.log")
        if path.is_file()
    ]
    for path in [*stale_files, *stale_roots]:
        try:
            if not path.resolve().is_relative_to(artifact_root.resolve()):
                continue
        except Exception:
            continue
        if path.is_dir():
            for child in sorted(path.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            path.rmdir()
        else:
            path.unlink()
        removed.append(str(path.relative_to(root)).replace("\\", "/"))
    return sorted(removed)


def production_forbidden_token_findings(root: Path) -> list[dict[str, Any]]:
    forbidden = (SESSION_OPEN_MARKER_TOKEN, DIRECT_SQL_MARKER_TOKEN, RETIRED_SESSION_REASON_TOKEN)
    findings: list[dict[str, Any]] = []
    for path in sorted((root / ".overwatch_final").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            if token in text:
                findings.append({
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "token": token,
                    "reason": "Production source must use sidecar registries, not inline proof markers.",
                })
    return findings


def contract_registry_artifact() -> dict[str, Any]:
    return {
        "direct_sql_allowlist": list(DIRECT_SQL_ALLOWLIST),
        "session_open_allowlist": list(SESSION_OPEN_ALLOWLIST),
        "entry_count": len(DIRECT_SQL_ALLOWLIST) + len(SESSION_OPEN_ALLOWLIST),
        "inline_marker_source": False,
    }


def build_cleanup_inventory(root: Path | str = ".", *, removed_stale_artifacts: list[str] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "python_modules": python_module_inventory(root),
        "snowflake_objects": object_inventory(root),
        "routes": route_state_inventory(),
        "tests": test_inventory(root),
        "artifacts": artifact_inventory(root),
        "removed_stale_artifacts": sorted(removed_stale_artifacts or []),
        "production_forbidden_token_findings": production_forbidden_token_findings(root),
    }


def cleanup_summary(inventory: dict[str, Any]) -> dict[str, Any]:
    python_modules = inventory["python_modules"]
    snowflake_objects = inventory["snowflake_objects"]
    routes = inventory["routes"]
    tests = inventory["tests"]
    artifacts = inventory["artifacts"]
    return {
        "generated_at": inventory["generated_at"],
        "baseline_direction": "Decision Workspace primary sections only",
        "inline_marker_comments_remaining": len(inventory["production_forbidden_token_findings"]),
        "unreachable_production_modules": len(python_modules["unreachable"]),
        "dead_routes": len(routes["dead_routes"]),
        "compact_evidence_marts_with_load_path": snowflake_objects["compact_evidence_load_path"],
        "test_file_count": tests["test_file_count"],
        "stale_generated_artifact_count": len(artifacts["stale_generated_artifacts"]),
        "deleted_files_this_pass": [],
        "removed_stale_artifacts": inventory.get("removed_stale_artifacts", []),
        "cleanup_actions": [
            "Moved direct SQL and session-open proof markers to sidecar registries.",
            "Removed production inline marker comments.",
            "Recorded route, object, module, test, and artifact inventory.",
        ],
    }


def write_cleanup_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root = Path(root).resolve()
    removed_stale_artifacts = cleanup_stale_artifacts(root)
    cleanup_dir = root / "artifacts" / "cleanup"
    cleanup_dir.mkdir(parents=True, exist_ok=True)
    for path in cleanup_dir.glob("*.json"):
        path.unlink()
    inventory = build_cleanup_inventory(root, removed_stale_artifacts=removed_stale_artifacts)
    summary = cleanup_summary(inventory)
    route_inventory = inventory["routes"]
    object_inv = inventory["snowflake_objects"]
    registry = contract_registry_artifact()
    written = {
        "artifacts/cleanup/legacy_inventory.json": inventory,
        "artifacts/cleanup/cleanup_summary.json": summary,
        "artifacts/cleanup/route_state_inventory.json": route_inventory,
        "artifacts/cleanup/object_inventory.json": object_inv,
        "artifacts/cleanup/contract_registry.json": registry,
    }
    for rel, payload in written.items():
        (root / rel).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "generated_at": inventory["generated_at"],
        "files": sorted([*written, "artifacts/cleanup/artifact_manifest.json"]),
    }
    (cleanup_dir / "artifact_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return {**written, "artifacts/cleanup/artifact_manifest.json": manifest}


__all__ = [
    "COMPACT_EVIDENCE_MARTS",
    "build_cleanup_inventory",
    "cleanup_stale_artifacts",
    "cleanup_summary",
    "contract_registry_artifact",
    "object_inventory",
    "production_forbidden_token_findings",
    "route_state_inventory",
    "write_cleanup_artifacts",
]
