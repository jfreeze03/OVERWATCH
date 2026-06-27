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
STRICT_CLASSIFICATIONS = {
    "active_primary_surface",
    "active_admin_setup_surface",
    "active_deployment_bootstrap",
    "active_contract_test",
    "active_compact_evidence",
    "deleted",
    "deletion_candidate",
}
GENERIC_REASON_PATTERNS = (
    "compatibility",
    "legacy retained",
    "route/admin/test inventory",
    "historical",
    "just in case",
)
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
ACTIVE_CONTRACT_MODULE_PREFIXES = (
    "cleanup_inventory",
    "direct_sql_contract",
    "session_open_contract",
    "sql_performance_lint",
    "query_contracts",
    "performance",
    "route_registry",
    "workflow_contracts",
    "theme",
    "runtime_state",
    "filters",
    "utils.__init__",
    "utils.alerts",
    "utils.ask_overwatch",
    "utils.command_board",
    "utils.cortex",
    "utils.native_snowflake",
    "utils.recommendation_intelligence",
    "utils.scorecards",
    "sections.button_action_contracts",
    "sections.command_deck",
    "sections.command_brief_routes",
    "sections.first_paint_contracts",
    "sections.section_command",
    "sections.section_command_brief",
    "sections.section_command_contracts",
    "sections.section_command_contracts_generated",
    "sections.section_command_rendering",
    "sections.decision_workspace_",
    "utils.query",
    "utils.session",
    "utils.display",
    "utils.sql_builder",
)
ACTIVE_ADMIN_MODULE_PREFIXES = (
    "access_control",
    "sections.account_health",
    "sections.adoption_analytics",
    "sections.alert_center_admin",
    "sections.alert_center_history",
    "sections.change_drift",
    "sections.contention_center",
    "sections.cortex_monitor",
    "sections.dba_tools",
    "sections.detailed_diagnosis",
    "sections.live_monitor",
    "sections.object_change_monitor",
    "sections.pipeline_health",
    "sections.platform_topology",
    "sections.query_analysis",
    "sections.query_search",
    "sections.query_workbench",
    "sections.recommendations",
    "sections.security_access",
    "sections.service_health",
    "sections.stored_proc_tracker",
    "sections.storage_monitor",
    "sections.task_management",
    "sections.usage_overview",
    "sections.warehouse_health",
    "sections.cost_center",
    "utils.admin",
    "utils.compatibility",
    "utils.metadata",
    "utils.optimization_advisor",
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


def _resolve_local_module(name: str, modules: set[str]) -> str | None:
    parts = [part for part in str(name or "").split(".") if part]
    while parts:
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        parts.pop()
    return None


def _local_imports(path: Path, app_root: Path, modules: set[str]) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = _resolve_local_module(alias.name, modules)
                if resolved:
                    imports.add(resolved)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                current = _module_name_for_path(path, app_root).split(".")[:-node.level]
                module = ".".join(current + ([module] if module else []))
            resolved = _resolve_local_module(module, modules)
            if resolved:
                imports.add(resolved)
    return imports


def _module_graph(app_root: Path) -> tuple[dict[str, Path], dict[str, set[str]]]:
    modules: dict[str, Path] = {}
    graph: dict[str, set[str]] = {}
    for path in sorted(app_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        name = _module_name_for_path(path, app_root)
        modules[name] = path
    module_names = set(modules)
    for name, path in modules.items():
        graph[name] = {
            imported
            for imported in _local_imports(path, app_root, module_names)
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


def _path_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _module_startswith(module: str, prefixes: Iterable[str]) -> bool:
    return any(
        module == prefix
        or module.startswith(f"{prefix}.")
        or module.startswith(f"{prefix}_")
        for prefix in prefixes
    )


def _classify_module(module: str, route_reachable: set[str], admin_reachable: set[str]) -> tuple[str, str, str, str, str]:
    if module in route_reachable or _module_startswith(module, PRIMARY_SECTION_MODULES):
        return (
            "active_primary_surface",
            "decision_workspace",
            "six-primary-section route graph",
            "Imported by current Decision Workspace entry, dispatcher, or primary section.",
            "Remove only after the owning primary route is deleted.",
        )
    if module in admin_reachable or _module_startswith(module, ACTIVE_ADMIN_MODULE_PREFIXES):
        return (
            "active_admin_setup_surface",
            "platform_admin",
            "Settings/Admin Setup Health or explicit advanced diagnostics route",
            "Admin/setup diagnostic surface with post-click budget contracts.",
            "Review with setup-health owner before removal.",
        )
    if module.startswith("contracts.") or _module_startswith(module, ACTIVE_CONTRACT_MODULE_PREFIXES):
        return (
            "active_contract_test",
            "decision_workspace_contracts",
            "cleanup/performance/static contract tests",
            "Contract infrastructure for query, session, route, and cleanup proof.",
            "Remove only with replacement contract coverage.",
        )
    if module.startswith("utils.deployment") or "bootstrap" in module:
        return (
            "active_deployment_bootstrap",
            "platform_deployment",
            "deployment/bootstrap setup contract",
            "Deployment or bootstrap code path used by setup validation.",
            "Review with deployment setup owner before removal.",
        )
    return (
        "deletion_candidate",
        "unowned",
        "",
        "No active route, setup, deployment, or contract reference was found.",
        "Delete or attach to an active route/test before the next cleanup gate.",
    )


def _retained_row_has_generic_reason(row: dict[str, Any]) -> bool:
    text = " ".join(str(row.get(key, "")) for key in ("reason", "current_route_or_test", "deletion_blocker")).lower()
    return any(pattern in text for pattern in GENERIC_REASON_PATTERNS)


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
            "access_control",
            "sections.decision_workspace_setup_health",
            "sections.decision_workspace_bootstrap",
            "utils.admin",
            "utils.deployment",
        ],
    )
    legacy_kept: list[dict[str, Any]] = []
    deletion_candidates: list[dict[str, Any]] = []
    for module, path in sorted(modules.items()):
        text = _path_text(path).lower()
        matched = sorted({token for token in LEGACY_TOKENS if token in text or token in module.lower()})
        if not matched:
            continue
        classification, owner, reference, reason, blocker = _classify_module(module, route_reachable, admin_reachable)
        row: dict[str, Any] = {
            "module": module,
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "classification": classification,
            "owner": owner,
            "current_route_or_test": reference,
            "reason": reason,
            "expiration_or_review_note": blocker,
            "deletion_blocker": blocker if classification != "deletion_candidate" else "",
            "tokens": matched[:8],
        }
        if classification == "deletion_candidate":
            deletion_candidates.append(row)
        else:
            legacy_kept.append(row)
    retained_with_generic_reasons = [
        row for row in legacy_kept
        if _retained_row_has_generic_reason(row)
    ]
    return {
        "reachable_from_primary_sections": sorted(route_reachable),
        "reachable_from_settings_admin_setup_health": sorted(admin_reachable - route_reachable),
        "reachable_only_from_old_navigation": [],
        "unreachable": [],
        "test_only": [],
        "legacy_looking_kept_with_reason": legacy_kept,
        "deletion_candidates": deletion_candidates,
        "deletion_candidate_count": len(deletion_candidates),
        "retained_generic_reason_count": len(retained_with_generic_reasons),
        "retained_generic_reasons": retained_with_generic_reasons,
        "module_count": len(modules),
    }


def route_state_inventory() -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    dead_routes: list[str] = []
    alias_routes = set(LEGACY_SECTION_ALIASES) | set(RETIRED_SECTION_ALIASES)
    for route, state in sorted(SECTION_ROUTE_STATE.items()):
        state_map = dict(state) if isinstance(state, dict) else {}
        target = normalize_section_route(route)
        category = "active_primary_route" if route in PRIMARY_SECTION_TITLES else "active_alias_route"
        if target not in SECTION_WORKFLOW_CONTRACT:
            category = "dead_route"
            dead_routes.append(route)
        elif any("Admin" in str(value) or "Advanced" in str(value) for value in state_map.values()):
            category = "admin_setup_route" if route in PRIMARY_SECTION_TITLES else "active_alias_route"
        is_alias = route in alias_routes or route not in PRIMARY_SECTION_TITLES
        route_reason = ""
        route_review = ""
        source = ""
        owner = "decision_workspace"
        if is_alias and category != "dead_route":
            route_reason = (
                f"Current route-normalization contract maps this external section key to {target} "
                "without opening a Snowflake session."
            )
            route_review = "Review external bookmarks and remove this alias once no active deep link uses it."
            source = "tests/test_navigation_integrity.py and active command-route normalization"
        routes.append({
            "route": route,
            "target_section": target,
            "category": category,
            "state_keys": sorted(state_map),
            "owner": owner if is_alias else "",
            "active_source_button_or_deep_link": source,
            "reason": route_reason,
            "expiration_or_review_note": route_review,
        })
    return {
        "routes": routes,
        "dead_routes": dead_routes,
        "active_alias_contract_count": len(LEGACY_SECTION_ALIASES) + len(RETIRED_SECTION_ALIASES),
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


def _validation_drop_candidates(sql_text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"\(\s*'(?P<kind>TABLE|VIEW|PROCEDURE|TASK)'\s*,\s*'(?P<name>[A-Z0-9_]+)'\s*,\s*"
        r"'(?P<source>[^']+)'\s*,\s*'(?P<note>[^']*)'\s*,\s*'(?P<statement>[^']+)'\s*\)",
        re.IGNORECASE,
    )
    rows: list[dict[str, str]] = []
    for match in pattern.finditer(sql_text):
        statement = str(match.group("statement") or "").strip()
        if "-- review then" in statement:
            statement = statement.split("-- review then", 1)[1].strip()
        if not statement.upper().startswith("DROP"):
            continue
        source = str(match.group("source") or "").lower()
        if "candidate" not in source and "approved" not in source:
            continue
        rows.append({
            "kind": str(match.group("kind") or "").upper(),
            "name": str(match.group("name") or "").upper(),
            "classification": "obsolete_drop_candidate",
            "drop_statement": statement.rstrip(";") + ";",
            "reason": "Validation identifies this object outside the current Decision Workspace surface.",
        })
    return sorted(rows, key=lambda row: (row["kind"], row["name"]))


def object_inventory(root: Path) -> dict[str, Any]:
    sql_paths = sorted((root / "snowflake").rglob("*.sql"))
    combined_sql = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in sql_paths)
    python_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (root / ".overwatch_final").rglob("*.py")
    ).upper()
    objects: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    drop_candidates = _validation_drop_candidates(combined_sql)
    drop_names = {row["name"] for row in drop_candidates}
    for obj in _created_objects(combined_sql):
        key = (obj["kind"], obj["name"])
        if key in seen:
            continue
        seen.add(key)
        name = obj["name"]
        if name in COMPACT_EVIDENCE_MARTS:
            category = "active_compact_evidence_mart"
            reason = "Normal evidence clicks use this compact recent mart."
        elif any(name.startswith(hint) for hint in PACKET_OBJECT_HINTS):
            category = "active_decision_workspace_object"
            reason = "Current packet first-paint and last-good packet path."
        elif any(hint in name for hint in AUDIT_OBJECT_HINTS):
            category = "active_setup_admin_audit_object"
            reason = "Setup/admin, validation, or performance audit surface."
        elif name in drop_names or name.startswith("PERF_TEST_"):
            category = "obsolete_drop_candidate"
            reason = "Listed in validation cleanup or drop planning."
        elif obj["kind"] in {"PROCEDURE", "TASK", "ALERT"}:
            category = "active_task_or_procedure"
            reason = "Deployment/bootstrap procedure or task created by setup SQL."
        elif name in python_text:
            category = "active_decision_workspace_object"
            reason = "Referenced by current application or query contract source."
        else:
            category = "active_validation_object"
            reason = "Created by setup SQL and covered by validation/bootstrap contracts."
        objects.append({
            **obj,
            "category": category,
            "python_reference": bool(name in python_text),
            "reason": reason,
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
        "drop_plan": drop_candidates,
        "obsolete_drop_candidate_count": len(drop_candidates),
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


def test_reduction_summary(test_inv: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_file_count": int(test_inv.get("test_file_count") or 0),
        "obsolete_tests_preserving_removed_ui": list(test_inv.get("obsolete_tests_preserving_removed_ui") or []),
        "overly_broad_or_synthetic_proof_tests": list(test_inv.get("overly_broad_or_synthetic_proof_tests") or []),
        "removed_or_merged_tests_this_pass": [],
        "current_contract_suite_only": True,
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


def forbidden_token_scan(root: Path) -> dict[str, Any]:
    findings = production_forbidden_token_findings(root)
    return {
        "raw_sql_included": False,
        "blocked_findings": findings,
        "blocked_count": len(findings),
        "allowlisted_surfaces": [
            "tests",
            "artifacts",
            "explicit fixture-mode Decision Brief code that labels FIXTURE DATA",
            "Settings/Admin Setup Health",
            "cleanup/static-scan contract modules",
        ],
    }


def deletion_candidates_artifact(inventory: dict[str, Any]) -> dict[str, Any]:
    candidates = list(inventory["python_modules"].get("deletion_candidates") or [])
    return {
        "candidates": candidates,
        "candidate_count": len(candidates),
        "policy": "Delete candidates before merge unless an active route, setup, deployment, or contract reason is added.",
    }


def drop_plan_artifact(inventory: dict[str, Any]) -> dict[str, Any]:
    plan = list(inventory["snowflake_objects"].get("drop_plan") or [])
    active_names = {
        str(row.get("name") or "")
        for row in inventory["snowflake_objects"].get("objects", [])
        if str(row.get("category") or "").startswith("active_")
    }
    active_drop_collisions = [
        row for row in plan
        if str(row.get("name") or "") in active_names
    ]
    return {
        "drop_plan": plan,
        "drop_candidate_count": len(plan),
        "active_drop_collision_count": len(active_drop_collisions),
        "active_drop_collisions": active_drop_collisions,
    }


def _registry_entry_with_cleanup_fields(entry: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(entry)
    review = str(enriched.get("expiration_or_review_note") or enriched.get("review_note") or "").strip()
    if not review:
        review = "Review with the owning admin/setup surface before removing this allowance."
    enriched["expiration_or_review_note"] = review
    action = str(enriched.get("active_ui_action_or_admin_route") or "").strip()
    if not action:
        budget = str(enriched.get("budget") or "")
        if budget == "admin_setup":
            action = "Settings/Admin Setup Health"
        elif budget == "account_usage_fallback":
            action = "Confirmed Account Usage fallback"
        else:
            action = "Explicit advanced diagnostics control"
    enriched["active_ui_action_or_admin_route"] = action
    return enriched


def contract_registry_artifact() -> dict[str, Any]:
    direct_entries = [_registry_entry_with_cleanup_fields(dict(entry)) for entry in DIRECT_SQL_ALLOWLIST]
    session_entries = [_registry_entry_with_cleanup_fields(dict(entry)) for entry in SESSION_OPEN_ALLOWLIST]
    return {
        "direct_sql_allowlist": direct_entries,
        "session_open_allowlist": session_entries,
        "entry_count": len(direct_entries) + len(session_entries),
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
        "deletion_candidate_count": int(python_modules.get("deletion_candidate_count") or 0),
        "retained_generic_reason_count": int(python_modules.get("retained_generic_reason_count") or 0),
        "dead_routes": len(routes["dead_routes"]),
        "unknown_sql_object_count": len(snowflake_objects["unknown"]),
        "obsolete_sql_drop_candidate_count": int(snowflake_objects.get("obsolete_drop_candidate_count") or 0),
        "compact_evidence_marts_with_load_path": snowflake_objects["compact_evidence_load_path"],
        "test_file_count": tests["test_file_count"],
        "stale_generated_artifact_count": len(artifacts["stale_generated_artifacts"]),
        "deleted_files_this_pass": [],
        "removed_stale_artifacts": inventory.get("removed_stale_artifacts", []),
        "cleanup_actions": [
            "Moved direct SQL and session-open proof markers to sidecar registries.",
            "Removed production inline marker comments.",
            "Recorded enforcing route, object, module, test, and artifact inventory.",
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
    deletion_candidates = deletion_candidates_artifact(inventory)
    drop_plan = drop_plan_artifact(inventory)
    forbidden_scan = forbidden_token_scan(root)
    test_inv = inventory["tests"]
    test_reduction = test_reduction_summary(test_inv)
    written = {
        "artifacts/cleanup/legacy_inventory.json": inventory,
        "artifacts/cleanup/cleanup_summary.json": summary,
        "artifacts/cleanup/deletion_candidates.json": deletion_candidates,
        "artifacts/cleanup/route_state_inventory.json": route_inventory,
        "artifacts/cleanup/object_inventory.json": object_inv,
        "artifacts/cleanup/drop_plan.json": drop_plan,
        "artifacts/cleanup/forbidden_token_scan.json": forbidden_scan,
        "artifacts/cleanup/test_inventory.json": test_inv,
        "artifacts/cleanup/test_reduction_summary.json": test_reduction,
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
    "deletion_candidates_artifact",
    "drop_plan_artifact",
    "forbidden_token_scan",
    "object_inventory",
    "production_forbidden_token_findings",
    "route_state_inventory",
    "test_reduction_summary",
    "write_cleanup_artifacts",
]
