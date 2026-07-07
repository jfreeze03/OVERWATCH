"""Validate section-summary autoload runtime events.

This gate allows a section to load a useful packet/summary-mart summary after
the user has navigated into the section, while keeping shell first-paint and
route-click handlers query-free.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

SOURCE_RUNTIME_EVENT_LEDGER_REL = f"{FULL_APP_DIR}/source_runtime_event_ledger_results.json"
SUMMARY_AUTOLOAD_CONTRACT_RESULTS_REL = f"{FULL_APP_DIR}/summary_autoload_contract_results.json"
SUMMARY_AUTOLOAD_CONTRACT_GATE_REL = f"{LAUNCH_READINESS_DIR}/summary_autoload_contract_gate_results.json"

SUMMARY_AUTOLOAD_MAX_ROWS = 200


def _now() -> str:
    return datetime.now(UTC).isoformat()


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


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        raw_rows = payload.get("rows")
        if isinstance(raw_rows, list):
            return [dict(row) for row in raw_rows if isinstance(row, Mapping)]
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    return []


def _boundary(row: Mapping[str, Any]) -> str:
    return str(row.get("execution_boundary") or row.get("boundary") or row.get("query_boundary") or "").strip()


def _is_summary_autoload(row: Mapping[str, Any]) -> bool:
    return str(row.get("event_type") or "") == "section_summary_autoload"


def _summary_source_ok(row: Mapping[str, Any]) -> bool:
    ttl_key = str(row.get("ttl_key") or "").lower()
    query_tier = str(row.get("query_tier") or "").lower()
    return (
        "packet" in ttl_key
        or "summary" in ttl_key
        or "brief" in ttl_key
        or query_tier in {"command_summary", "section_summary", "standard"}
    )


def evaluate_summary_autoload_contract(
    source_runtime_event_ledger_payload: Any,
    *,
    commit_sha: str = "",
) -> dict[str, Any]:
    """Return a producer-backed gate over source runtime summary autoload rows."""

    rows = [row for row in _rows(source_runtime_event_ledger_payload) if _is_summary_autoload(row)]
    checked: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    if not isinstance(source_runtime_event_ledger_payload, Mapping) or not source_runtime_event_ledger_payload:
        failures.append({"failure_reason": "missing source runtime event ledger artifact"})
    if not rows:
        failures.append({"failure_reason": "missing section_summary_autoload runtime event rows"})

    for index, row in enumerate(rows):
        row_id = str(row.get("id") or row.get("row_id") or row.get("event_id") or f"summary_autoload::{index}")
        row_commit = str(row.get("commit_sha") or "")
        query_count = _as_int(row.get("query_count_delta") if "query_count_delta" in row else row.get("query_count"))
        max_rows = _as_int(row.get("max_rows"))
        reasons: list[str] = []
        if not row.get("producer"):
            reasons.append("missing producer")
        if not row.get("producer_signature"):
            reasons.append("missing producer_signature")
        if "passed" in row and not bool(row.get("passed")):
            reasons.append(str(row.get("failure_reason") or "source runtime row did not pass"))
        if commit_sha and row_commit and row_commit != commit_sha:
            reasons.append(f"commit_sha mismatch: {row_commit}")
        if bool(row.get("raw_sql_included")):
            reasons.append("raw_sql_included=true")
        if _boundary(row) != "section_summary_autoload":
            reasons.append("wrong execution boundary")
        if not bool(row.get("user_initiated")):
            reasons.append("missing user-initiated navigation context")
        if bool(row.get("before_first_paint")) or bool(row.get("first_paint_sensitive")):
            reasons.append("ran before first paint completed")
        if bool(row.get("account_usage_marker_present")) or _as_int(row.get("account_usage_count_delta")):
            reasons.append("crossed Account Usage")
        if bool(row.get("evidence_loader_marker_present")) or bool(row.get("cost_evidence_marker_present")):
            reasons.append("loaded deep evidence/workbench data")
        if bool(row.get("setup_live_validation_marker_present")):
            reasons.append("crossed setup/live validation")
        if bool(row.get("source_object_marker_present")):
            reasons.append("leaked a source-object marker")
        if query_count and "max_rows" not in row:
            reasons.append("missing max_rows")
        elif max_rows > SUMMARY_AUTOLOAD_MAX_ROWS:
            reasons.append(f"max_rows={max_rows}")
        if not _summary_source_ok(row):
            reasons.append("not packet-backed or summary-mart-backed")

        checked_row = {
            "row_id": row_id,
            "producer": "summary_autoload_contract",
            "producer_signature": "summary_autoload_contract::row_v1",
            "provenance_origin": "producer",
            "source_runtime_row_id": row_id,
            "commit_sha": row_commit,
            "section": str(row.get("section") or ""),
            "workflow": str(row.get("workflow") or ""),
            "query_boundary": "section_summary_autoload",
            "query_count": query_count,
            "max_rows": max_rows,
            "user_initiated": bool(row.get("user_initiated")),
            "packet_or_summary_backed": _summary_source_ok(row),
            "raw_sql_included": False,
            "passed": not reasons,
            "failure_reason": "; ".join(reasons),
        }
        checked.append(checked_row)
        if reasons:
            failures.append(
                {
                    "row_id": row_id,
                    "section": checked_row["section"],
                    "workflow": checked_row["workflow"],
                    "failure_reason": checked_row["failure_reason"],
                }
            )

    return {
        "source": "summary_autoload_contract_results",
        "producer": "summary_autoload_contract",
        "producer_signature": "summary_autoload_contract::v1",
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha or str(
            source_runtime_event_ledger_payload.get("commit_sha") if isinstance(source_runtime_event_ledger_payload, Mapping) else ""
        ),
        "passed": not failures,
        "failure_count": len(failures),
        "summary_autoload_row_count": len(rows),
        "summary_autoload_violation_count": sum(1 for row in checked if not bool(row.get("passed"))),
        "rows": checked,
        "failures": failures,
        "raw_sql_included": False,
    }


def evaluate_summary_autoload_contract_gate(results: Mapping[str, Any]) -> dict[str, Any]:
    failures = [dict(row) for row in results.get("failures", []) if isinstance(row, Mapping)]
    proof_rows = [
        {
            "row_id": str(row.get("row_id") or ""),
            "source_runtime_row_id": str(row.get("source_runtime_row_id") or row.get("row_id") or ""),
            "section": str(row.get("section") or ""),
            "workflow": str(row.get("workflow") or ""),
            "query_boundary": str(row.get("query_boundary") or "section_summary_autoload"),
            "query_count": _as_int(row.get("query_count")),
            "max_rows": _as_int(row.get("max_rows")),
            "user_initiated": bool(row.get("user_initiated")),
            "packet_or_summary_backed": bool(row.get("packet_or_summary_backed")),
            "producer": str(row.get("producer") or "summary_autoload_contract"),
            "producer_signature": str(row.get("producer_signature") or "summary_autoload_contract::row_v1"),
            "commit_sha": str(row.get("commit_sha") or results.get("commit_sha") or ""),
            "raw_sql_included": False,
            "passed": bool(row.get("passed")),
        }
        for row in results.get("rows", [])
        if isinstance(row, Mapping)
    ]
    if _as_int(results.get("summary_autoload_row_count")) <= 0:
        failures.append({"failure_reason": "missing section_summary_autoload runtime event rows"})
    if bool(results.get("raw_sql_included")):
        failures.append({"failure_reason": "raw_sql_included=true"})
    if not bool(results.get("passed")) and not failures:
        failures.append({"failure_reason": "summary autoload contract did not pass"})
    return {
        "source": "summary_autoload_contract_gate_results",
        "gate": "summary_autoload_contract",
        "producer": "summary_autoload_contract",
        "producer_signature": "summary_autoload_contract_gate::v1",
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": str(results.get("commit_sha") or ""),
        "passed": not failures,
        "failure_count": len(failures),
        "summary_autoload_row_count": _as_int(results.get("summary_autoload_row_count")),
        "summary_autoload_violation_count": _as_int(results.get("summary_autoload_violation_count")),
        "proof_rows": proof_rows,
        "proof_row_count": len(proof_rows),
        "referenced_row_ids": [str(row.get("row_id") or "") for row in proof_rows if row.get("row_id")],
        "failures": failures,
        "raw_sql_included": False,
    }


def write_summary_autoload_contract_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    payload = _load_json(root_path / SOURCE_RUNTIME_EVENT_LEDGER_REL)
    results = evaluate_summary_autoload_contract(payload, commit_sha=_git_commit(root_path))
    gate = evaluate_summary_autoload_contract_gate(results)
    for rel, data in {
        SUMMARY_AUTOLOAD_CONTRACT_RESULTS_REL: results,
        SUMMARY_AUTOLOAD_CONTRACT_GATE_REL: gate,
    }.items():
        path = root_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return {
        SUMMARY_AUTOLOAD_CONTRACT_RESULTS_REL: results,
        SUMMARY_AUTOLOAD_CONTRACT_GATE_REL: gate,
    }


def main() -> int:
    artifacts = write_summary_autoload_contract_artifacts(Path("."))
    gate = artifacts[SUMMARY_AUTOLOAD_CONTRACT_GATE_REL]
    print(json.dumps(gate, indent=2, sort_keys=True))
    return 0 if gate.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SUMMARY_AUTOLOAD_CONTRACT_GATE_REL",
    "SUMMARY_AUTOLOAD_CONTRACT_RESULTS_REL",
    "evaluate_summary_autoload_contract",
    "evaluate_summary_autoload_contract_gate",
    "write_summary_autoload_contract_artifacts",
]
