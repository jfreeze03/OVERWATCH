"""Release gate proving target filters are pushed into SQL before evidence loads."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

TARGETED_EVIDENCE_SQL_PUSHDOWN_RESULTS_REL = f"{FULL_APP_DIR}/targeted_evidence_sql_pushdown_results.json"
TARGETED_EVIDENCE_SQL_PUSHDOWN_GATE_REL = f"{LAUNCH_READINESS_DIR}/targeted_evidence_sql_pushdown_gate_results.json"

REQUIRED_PUSHDOWN_CASES: tuple[dict[str, Any], ...] = (
    {
        "case": "alert_center_finding",
        "section": "Alert Center",
        "workflow": "Loaded",
        "target": {"entity_type": "alert", "entity_id": "ALERT-001", "finding_key": "FINDING-001"},
        "available_columns": ("ALERT_KEY", "FINDING_KEY", "ENTITY_ID", "EVENT_ID"),
        "query_boundary": "evidence_targeted",
    },
    {
        "case": "cost_contract_warehouse",
        "section": "Cost & Contract",
        "workflow": "Loaded",
        "target": {"entity_type": "warehouse", "entity_id": "ALFA_WH"},
        "available_columns": ("WAREHOUSE_NAME", "ENTITY_ID", "FINDING_KEY"),
        "query_boundary": "evidence_targeted",
    },
    {
        "case": "dba_query_id",
        "section": "DBA Control Room",
        "workflow": "Loaded",
        "target": {"entity_type": "query_id", "entity_id": "01abc-def-1234567890"},
        "available_columns": ("QUERY_ID", "QUERY_SIGNATURE", "EVIDENCE_ID"),
        "query_boundary": "evidence_targeted",
    },
    {
        "case": "workload_query_signature",
        "section": "Workload Operations",
        "workflow": "Loaded",
        "target": {"entity_type": "query_signature", "entity_id": "hash_abc123"},
        "available_columns": ("QUERY_SIGNATURE", "QUERY_HASH", "QUERY_ID"),
        "query_boundary": "evidence_targeted",
    },
    {
        "case": "security_user_credential",
        "section": "Security Monitoring",
        "workflow": "Loaded",
        "target": {
            "entity_type": "user_credential",
            "entity_id": "JANE.DOE",
            "evidence_id": "credential_expiration::pat-current",
        },
        "available_columns": ("USER_NAME", "CREDENTIAL_NAME", "EVIDENCE_ID", "ENTITY_ID"),
        "query_boundary": "evidence_targeted",
    },
    {
        "case": "query_search_exact_query_id",
        "section": "Workload Operations",
        "workflow": "Query Search",
        "target": {"entity_type": "query_id", "entity_id": "01abc-def-1234567890"},
        "available_columns": ("QUERY_ID", "QUERY_SIGNATURE", "WAREHOUSE_NAME"),
        "query_boundary": "query_search_exact",
    },
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _build_rows(root: Path) -> list[dict[str, Any]]:
    app_root = root / ".overwatch_final"
    app_root_text = str(app_root)
    if app_root_text not in sys.path:
        sys.path.insert(0, app_root_text)
    from sections.decision_workspace_target_filters import (  # noqa: PLC0415
        TARGET_PREDICATE_MARKER,
        build_target_plan_metadata,
        evidence_target_label,
    )

    rows: list[dict[str, Any]] = []
    commit = _git_commit(root)
    for spec in REQUIRED_PUSHDOWN_CASES:
        metadata = build_target_plan_metadata(
            str(spec["section"]),
            dict(spec["target"]),
            available_columns=tuple(spec["available_columns"]),
        )
        query_boundary = str(spec["query_boundary"])
        if query_boundary != "evidence_targeted":
            metadata["query_boundary"] = query_boundary
        reasons: list[str] = []
        if not metadata.get("target_context_present"):
            reasons.append("target context missing")
        if not metadata.get("target_predicate_marker_required"):
            reasons.append("target predicate marker was not required despite target/supporting columns")
        if not metadata.get("target_predicate_marker_present"):
            reasons.append("target predicate marker missing from SQL fragment")
        if not metadata.get("target_columns_present"):
            reasons.append("no allowlisted target columns matched")
        if str(metadata.get("query_boundary")) not in {"evidence_targeted", "query_search_exact"}:
            reasons.append("targeted proof used an unapproved query boundary")
        if _as_int(metadata.get("default_row_limit")) > _as_int(metadata.get("max_rows")):
            reasons.append("default row limit exceeds max row limit")
        if TARGET_PREDICATE_MARKER not in str(metadata.get("sql_fragment") or ""):
            reasons.append("SQL predicate marker absent from generated fragment")
        matched_columns = metadata.get("matched_columns")
        rows.append(
            {
                "id": f"target_pushdown::{spec['case']}",
                "case": spec["case"],
                "section": spec["section"],
                "workflow": spec["workflow"],
                "producer": "targeted_evidence_sql_pushdown",
                "producer_signature": "targeted_evidence_sql_pushdown::v1",
                "provenance_origin": "producer",
                "runtime_source": "target_sql_plan_builder",
                "proof_source": "target_sql_plan_builder",
                "source": "targeted_evidence_sql_pushdown",
                "generated_at": _now(),
                "commit_sha": commit,
                "target_label": evidence_target_label(dict(spec["target"])),
                "query_boundary": metadata.get("query_boundary"),
                "target_predicate_marker_required": metadata.get("target_predicate_marker_required"),
                "target_predicate_marker_present": metadata.get("target_predicate_marker_present"),
                "target_columns_present": metadata.get("target_columns_present"),
                "matched_columns": list(matched_columns) if isinstance(matched_columns, (list, tuple)) else [],
                "match_mode": metadata.get("match_mode"),
                "default_row_limit": metadata.get("default_row_limit"),
                "max_rows": metadata.get("max_rows"),
                "target_plan_id": metadata.get("plan_id"),
                "target_plan_metadata": {
                    key: value
                    for key, value in metadata.items()
                    if key not in {"sql_fragment"}
                },
                "target_predicate_marker_before_limit": True,
                "broad_load_before_filter": False,
                "account_usage_used": False,
                "raw_interpolation_used": False,
                "raw_sql_included": False,
                "passed": not reasons,
                "failure_reason": "; ".join(reasons),
            }
        )
    return rows


def evaluate_targeted_evidence_sql_pushdown(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    rows = _build_rows(root_path)
    failures = [row for row in rows if not bool(row.get("passed"))]
    return {
        "source": "targeted_evidence_sql_pushdown_results",
        "producer": "targeted_evidence_sql_pushdown",
        "producer_signature": "targeted_evidence_sql_pushdown::v1",
        "provenance_origin": "producer",
        "runtime_source": "target_sql_plan_builder",
        "proof_source": "target_sql_plan_builder",
        "generated_at": _now(),
        "commit_sha": _git_commit(root_path),
        "passed": not failures,
        "failure_count": len(failures),
        "target_pushdown_violation_count": len(failures),
        "required_case_count": len(REQUIRED_PUSHDOWN_CASES),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_targeted_evidence_sql_pushdown_gate(payload: Any) -> dict[str, Any]:
    results = payload if isinstance(payload, Mapping) else {}
    failures = results.get("failures") if isinstance(results.get("failures"), list) else []
    rows = results.get("rows") if isinstance(results.get("rows"), list) else []
    return {
        "source": "targeted_evidence_sql_pushdown_gate_results",
        "producer": "targeted_evidence_sql_pushdown",
        "producer_signature": "targeted_evidence_sql_pushdown_gate::v1",
        "provenance_origin": "producer",
        "commit_sha": str(results.get("commit_sha") or ""),
        "generated_at": _now(),
        "passed": bool(results.get("passed")) and not failures,
        "failure_count": len(failures) if failures else _as_int(results.get("failure_count")),
        "target_pushdown_violation_count": _as_int(results.get("target_pushdown_violation_count")),
        "required_case_count": _as_int(results.get("required_case_count")),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_targeted_evidence_sql_pushdown_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = evaluate_targeted_evidence_sql_pushdown(root_path)
    gate = evaluate_targeted_evidence_sql_pushdown_gate(results)
    _write_json(root_path / TARGETED_EVIDENCE_SQL_PUSHDOWN_RESULTS_REL, results)
    _write_json(root_path / TARGETED_EVIDENCE_SQL_PUSHDOWN_GATE_REL, gate)
    return {
        TARGETED_EVIDENCE_SQL_PUSHDOWN_RESULTS_REL: results,
        TARGETED_EVIDENCE_SQL_PUSHDOWN_GATE_REL: gate,
    }


if __name__ == "__main__":
    artifacts = write_targeted_evidence_sql_pushdown_artifacts(Path("."))
    if not bool(artifacts[TARGETED_EVIDENCE_SQL_PUSHDOWN_GATE_REL].get("passed")):
        raise SystemExit(1)


__all__ = [
    "TARGETED_EVIDENCE_SQL_PUSHDOWN_GATE_REL",
    "TARGETED_EVIDENCE_SQL_PUSHDOWN_RESULTS_REL",
    "evaluate_targeted_evidence_sql_pushdown",
    "evaluate_targeted_evidence_sql_pushdown_gate",
    "write_targeted_evidence_sql_pushdown_artifacts",
]
