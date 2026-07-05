"""Audit Account Usage access paths for summary/load-gate safety.

The audit is source-level by design: it blocks direct Account Usage references
from root, navigation, first-paint, and section summary paths while allowing
setup/refresh SQL, live validation, admin setup, and explicit deep-evidence
fallbacks. Rows never include raw SQL bodies.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

ACCOUNT_USAGE_QUERY_AUDIT_RESULTS_REL = f"{FULL_APP_DIR}/account_usage_query_audit_results.json"
ACCOUNT_USAGE_QUERY_AUDIT_GATE_REL = f"{LAUNCH_READINESS_DIR}/account_usage_query_audit_gate_results.json"

PRODUCER = "account_usage_query_audit"

SOURCE_ROOTS = (".overwatch_final", "tools/contracts", "snowflake")
SOURCE_SUFFIXES = {".py", ".sql", ".md"}

ACCOUNT_USAGE_MARKERS = (
    "SNOWFLAKE.ACCOUNT_USAGE",
    "ACCOUNT_USAGE",
    "QUERY_HISTORY",
    "WAREHOUSE_METERING_HISTORY",
    "METERING_HISTORY",
    "LOGIN_HISTORY",
    "TASK_HISTORY",
    "GRANTS_TO_USERS",
    "GRANTS_TO_ROLES",
    "CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY",
    "CORTEX_CODE_CLI_USAGE_HISTORY",
    "ACCOUNT_USAGE.USERS",
)

DIRECT_SOURCE_MARKERS = (
    "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
    "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
    "SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY",
    "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY",
    "SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
    "SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS",
    "SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES",
    "SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY",
    "SNOWFLAKE.ACCOUNT_USAGE.CORTEX_CODE_CLI_USAGE_HISTORY",
    "SNOWFLAKE.ACCOUNT_USAGE.USERS",
)

ROOT_OR_FIRST_PAINT_FILES = {
    ".overwatch_final/app.py",
    ".overwatch_final/shell.py",
    ".overwatch_final/navigation.py",
    ".overwatch_final/route_registry.py",
    ".overwatch_final/runtime_state.py",
    ".overwatch_final/section_dispatch.py",
    ".overwatch_final/access_control.py",
    ".overwatch_final/filters.py",
    ".overwatch_final/layout.py",
    ".overwatch_final/refresh.py",
    ".overwatch_final/perf_trace.py",
    ".overwatch_final/app_entry_timing.py",
    ".overwatch_final/workflow_contracts.py",
    ".overwatch_final/sections/section_command_rendering.py",
    ".overwatch_final/sections/decision_workspace_bootstrap.py",
    ".overwatch_final/sections/decision_workspace_view_model.py",
    ".overwatch_final/sections/decision_workspace_components.py",
}

SUMMARY_PATH_NAME_MARKERS = (
    "section_command",
    "command_brief",
    "decision_workspace_bootstrap",
    "decision_workspace_view_model",
    "summary_autoload",
    "summary_mart_loaders",
)

EXPLICIT_DEEP_EVIDENCE_NAME_MARKERS = (
    "query_search",
    "query_analysis",
    "query_investigation_root_cause",
    "cortex_monitor",
    "cost_contract_sql",
    "dba_tools_cortex_limits_view",
    "security_posture_access_review",
    "security_posture_action_queue",
    "security_access",
    "task_management",
    "warehouse_health",
    "stored_proc",
    "spcs_tracker",
    "storage_monitor",
    "service_health",
    "alert_action_queue",
    "shared_metrics",
    "command_board",
    "compatibility",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_commit(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _line_hash(line: str) -> str:
    normalized = re.sub(r"\s+", " ", str(line or "").strip().upper())
    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _as_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _iter_source_files(root: Path) -> Iterable[Path]:
    for source_root in SOURCE_ROOTS:
        base = root / source_root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
                yield path


def _reference_kind(line: str) -> str:
    upper = line.upper()
    for marker in (
        "CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY",
        "CORTEX_CODE_CLI_USAGE_HISTORY",
        "WAREHOUSE_METERING_HISTORY",
        "METERING_HISTORY",
        "QUERY_HISTORY",
        "LOGIN_HISTORY",
        "TASK_HISTORY",
        "GRANTS_TO_USERS",
        "GRANTS_TO_ROLES",
        "ACCOUNT_USAGE.USERS",
        "ACCOUNT_USAGE",
    ):
        if marker in upper:
            return marker.lower().replace(".", "_")
    return "account_usage_marker"


def _contains_direct_source(line: str) -> bool:
    upper = line.upper()
    return any(marker in upper for marker in DIRECT_SOURCE_MARKERS)


def _is_sql_builder_path(rel_path: str) -> bool:
    return rel_path.startswith("snowflake/")


def _is_contract_path(rel_path: str) -> bool:
    return rel_path.startswith("tools/contracts/")


def _is_summary_path(rel_path: str) -> bool:
    lowered = rel_path.lower()
    return rel_path in ROOT_OR_FIRST_PAINT_FILES or any(marker in lowered for marker in SUMMARY_PATH_NAME_MARKERS)


def _is_explicit_deep_path(rel_path: str) -> bool:
    lowered = rel_path.lower()
    return any(marker in lowered for marker in EXPLICIT_DEEP_EVIDENCE_NAME_MARKERS)


def classify_account_usage_reference(rel_path: str, line: str) -> tuple[str, bool, str]:
    """Return classification, blocking flag, and reason for one reference."""

    if _is_sql_builder_path(rel_path):
        return (
            "approved_mart_builder",
            False,
            "Account Usage is allowed in setup/refresh SQL that builds compact marts and packets.",
        )
    if _is_contract_path(rel_path):
        return (
            "approved_release_or_live_validation",
            False,
            "Release, setup, live-validation, and leak gates may inspect Account Usage tokens without running daily UI queries.",
        )
    if _is_summary_path(rel_path) and _contains_direct_source(line):
        return (
            "violation_summary_or_route_path",
            True,
            "Default summary, route, or CommandBrief path must not reference direct Account Usage sources.",
        )
    if _is_explicit_deep_path(rel_path):
        return (
            "approved_explicit_deep_or_admin_path",
            False,
            "Legacy/deep evidence path is allowed only behind explicit click/admin boundaries.",
        )
    if "account_usage_fallback" in line.lower() or "deep_history_fallback" in line.lower():
        return (
            "approved_query_search_broad_explicit",
            False,
            "Broad history fallback is approved only behind explicit confirmation and budget gates.",
        )
    if "ACCOUNT_USAGE_" in line.upper() and not _contains_direct_source(line):
        return (
            "approved_boundary_constant",
            False,
            "Boundary or budget constants do not execute Account Usage SQL.",
        )
    return (
        "review_required_non_blocking",
        False,
        "Reference is outside default summary/route paths; keep owned by existing SQL/leak cleanup gates.",
    )


def _scan_source_file(path: Path, root: Path) -> list[dict[str, Any]]:
    rel_path = _as_posix(path, root)
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(lines, start=1):
        upper = line.upper()
        if not any(marker in upper for marker in ACCOUNT_USAGE_MARKERS):
            continue
        classification, blocking, reason = classify_account_usage_reference(rel_path, line)
        rows.append(
            {
                "row_id": f"{rel_path}:{line_no}",
                "source_file": rel_path,
                "line_number": line_no,
                "reference_kind": _reference_kind(line),
                "classification": classification,
                "blocking": blocking,
                "reason": reason,
                "line_fingerprint": _line_hash(line),
                "raw_sql_included": False,
            }
        )
    return rows


def _find_cortex_union_duplicates(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _iter_source_files(root):
        rel_path = _as_posix(path, root)
        if _is_sql_builder_path(rel_path) or _is_contract_path(rel_path) or _is_explicit_deep_path(rel_path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        upper = text.upper()
        if "UNION ALL" not in upper:
            continue
        if "CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY" not in upper and "CORTEX_CODE_CLI_USAGE_HISTORY" not in upper:
            continue
        rows.append(
            {
                "row_id": f"{rel_path}:cortex_union",
                "source_file": rel_path,
                "classification": "violation_duplicate_cortex_union",
                "blocking": True,
                "reason": "App runtime must use shared Cortex summary marts/loaders instead of duplicating Cortex source unions.",
                "raw_sql_included": False,
            }
        )
    return rows


def _find_repeated_users_joins(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _iter_source_files(root):
        rel_path = _as_posix(path, root)
        if _is_sql_builder_path(rel_path) or _is_contract_path(rel_path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        upper = text.upper()
        count = upper.count("SNOWFLAKE.ACCOUNT_USAGE.USERS") + upper.count("ACCOUNT_USAGE.USERS")
        if count <= 1 or _is_explicit_deep_path(rel_path):
            continue
        rows.append(
            {
                "row_id": f"{rel_path}:account_usage_users_join",
                "source_file": rel_path,
                "classification": "violation_repeated_users_join",
                "blocking": True,
                "reference_count": count,
                "reason": "Daily app paths must use the shared user display dimension instead of repeated Account Usage USERS joins.",
                "raw_sql_included": False,
            }
        )
    return rows


def build_account_usage_query_audit_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = _git_commit(root_path)
    reference_rows: list[dict[str, Any]] = []
    for path in _iter_source_files(root_path):
        reference_rows.extend(_scan_source_file(path, root_path))

    cortex_rows = _find_cortex_union_duplicates(root_path)
    users_join_rows = _find_repeated_users_joins(root_path)
    all_rows = [*reference_rows, *cortex_rows, *users_join_rows]
    failures = [
        {
            "row_id": str(row.get("row_id") or ""),
            "source_file": str(row.get("source_file") or ""),
            "classification": str(row.get("classification") or ""),
            "failure_reason": str(row.get("reason") or "blocking Account Usage query audit finding"),
        }
        for row in all_rows
        if bool(row.get("blocking"))
    ]
    classifications: dict[str, int] = {}
    for row in all_rows:
        key = str(row.get("classification") or "unknown")
        classifications[key] = classifications.get(key, 0) + 1

    return {
        "source": "account_usage_query_audit_results",
        "producer": PRODUCER,
        "producer_signature": "account_usage_query_audit::v1",
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha,
        "passed": not failures,
        "failure_count": len(failures),
        "account_usage_reference_count": len(reference_rows),
        "summary_path_account_usage_violation_count": sum(
            1 for row in reference_rows if row.get("classification") == "violation_summary_or_route_path"
        ),
        "route_path_account_usage_violation_count": sum(
            1
            for row in reference_rows
            if row.get("classification") == "violation_summary_or_route_path"
            and "navigation" in str(row.get("source_file") or "").lower()
        ),
        "cortex_union_duplicate_count": len(cortex_rows),
        "repeated_users_join_count": len(users_join_rows),
        "classification_counts": classifications,
        "rows": all_rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_account_usage_query_audit_gate(results: Mapping[str, Any]) -> dict[str, Any]:
    failures = [
        dict(row)
        for row in results.get("failures", [])
        if isinstance(row, Mapping)
    ]
    if bool(results.get("raw_sql_included")):
        failures.append({"failure_reason": "raw_sql_included=true"})
    proof_rows = [
        {
            "row_id": str(row.get("row_id") or ""),
            "source_file": str(row.get("source_file") or ""),
            "classification": str(row.get("classification") or ""),
            "blocking": bool(row.get("blocking")),
            "reference_kind": str(row.get("reference_kind") or ""),
            "producer": PRODUCER,
            "producer_signature": "account_usage_query_audit::row_v1",
            "commit_sha": str(results.get("commit_sha") or ""),
            "raw_sql_included": False,
            "passed": not bool(row.get("blocking")),
        }
        for row in results.get("rows", [])
        if isinstance(row, Mapping)
    ]
    return {
        "source": "account_usage_query_audit_gate_results",
        "gate": "account_usage_query_audit",
        "producer": PRODUCER,
        "producer_signature": "account_usage_query_audit_gate::v1",
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": str(results.get("commit_sha") or ""),
        "passed": not failures,
        "failure_count": len(failures),
        "account_usage_reference_count": int(results.get("account_usage_reference_count") or 0),
        "summary_path_account_usage_violation_count": int(results.get("summary_path_account_usage_violation_count") or 0),
        "route_path_account_usage_violation_count": int(results.get("route_path_account_usage_violation_count") or 0),
        "cortex_union_duplicate_count": int(results.get("cortex_union_duplicate_count") or 0),
        "repeated_users_join_count": int(results.get("repeated_users_join_count") or 0),
        "proof_rows": proof_rows,
        "proof_row_count": len(proof_rows),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_account_usage_query_audit_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_account_usage_query_audit_results(root_path)
    gate = evaluate_account_usage_query_audit_gate(results)
    _write_json(root_path / ACCOUNT_USAGE_QUERY_AUDIT_RESULTS_REL, results)
    _write_json(root_path / ACCOUNT_USAGE_QUERY_AUDIT_GATE_REL, gate)
    return {
        ACCOUNT_USAGE_QUERY_AUDIT_RESULTS_REL: results,
        ACCOUNT_USAGE_QUERY_AUDIT_GATE_REL: gate,
    }


def main() -> int:
    artifacts = write_account_usage_query_audit_artifacts(Path("."))
    gate = artifacts[ACCOUNT_USAGE_QUERY_AUDIT_GATE_REL]
    terminal_gate = {
        key: value
        for key, value in gate.items()
        if key not in {"proof_rows"}
    }
    print(json.dumps(terminal_gate, indent=2, sort_keys=True))
    return 0 if gate.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACCOUNT_USAGE_QUERY_AUDIT_GATE_REL",
    "ACCOUNT_USAGE_QUERY_AUDIT_RESULTS_REL",
    "build_account_usage_query_audit_results",
    "classify_account_usage_reference",
    "evaluate_account_usage_query_audit_gate",
    "write_account_usage_query_audit_artifacts",
]
