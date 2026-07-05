"""Single release evidence registry for hard launch gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

RELEASE_EVIDENCE_REGISTRY_RESULTS_REL = f"{FULL_APP_DIR}/release_evidence_registry_results.json"
RELEASE_EVIDENCE_REGISTRY_GATE_REL = f"{LAUNCH_READINESS_DIR}/release_evidence_registry_gate_results.json"

PRODUCER = "release_evidence_registry"


@dataclass(frozen=True)
class RegistryRow:
    gate_id: str
    required_for_production_deployable: bool
    required_for_a_grade_ready: bool
    artifact_path: str
    producer: str
    producer_file: str
    required_consumers: tuple[str, ...]
    owner: str = "OVERWATCH release owner"
    blocker_severity: str = "P0"
    waiver_policy: str = "profile-aware signed waiver only where supported"
    proof_rows_required: bool = True
    artifact_required: bool = True
    support_artifact_paths: tuple[str, ...] = ()
    launch_readiness_field: str = ""
    release_summary_field: str = ""
    blocking_reason: str = "release-blocking proof required"
    admin_only_allowed: bool = False
    daily_output_facing: bool = False
    allowed_profiles: tuple[str, ...] = ("internal_fixture", "internal_live", "prod_candidate")


REGISTRY_ROWS: tuple[RegistryRow, ...] = (
    RegistryRow("access_control_runtime", True, True, "artifacts/launch_readiness/access_control_runtime_gate_results.json", "access_control_runtime", "tools/contracts/access_control_runtime.py", ("launch_readiness.py", "a_grade_execution_matrix.py")),
    RegistryRow("runtime_event_ledger", True, True, "artifacts/launch_readiness/runtime_event_ledger_gate_results.json", "runtime_event_ledger", "tools/contracts/runtime_event_ledger.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py")),
    RegistryRow("source_runtime_event_ledger", True, True, "artifacts/launch_readiness/source_runtime_event_ledger_gate_results.json", "runtime_event_ledger", "tools/contracts/runtime_event_ledger.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py")),
    RegistryRow("summary_autoload_contract", True, True, "artifacts/launch_readiness/summary_autoload_contract_gate_results.json", "summary_autoload_contract", "tools/contracts/summary_autoload_contract.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py")),
    RegistryRow("account_usage_query_audit", True, True, "artifacts/launch_readiness/account_usage_query_audit_gate_results.json", "account_usage_query_audit", "tools/contracts/account_usage_query_audit.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py")),
    RegistryRow("summary_mart_setup", True, True, "artifacts/launch_readiness/summary_mart_setup_gate_results.json", "summary_mart_setup", "tools/contracts/summary_mart_setup.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py"), support_artifact_paths=("artifacts/snowflake_validation/summary_mart_setup_results.json",)),
    RegistryRow("first_paint_slo", True, True, "artifacts/launch_readiness/first_paint_slo_gate_results.json", "first_paint_slo", "tools/contracts/first_paint_slo.py", ("launch_readiness.py", "a_grade_execution_matrix.py")),
    RegistryRow("performance_budget", True, True, "artifacts/launch_readiness/performance_budget_gate_results.json", "performance_budget_gate", "tools/contracts/performance_budget_gate.py", ("launch_readiness.py", "a_grade_execution_matrix.py"), proof_rows_required=False),
    RegistryRow("artifact_integrity", True, True, "artifacts/launch_readiness/artifact_integrity_gate_results.json", "artifact_verifier", "tools/contracts/artifact_verifier.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py"), artifact_required=False),
    RegistryRow("release_evidence_registry", True, True, "artifacts/launch_readiness/release_evidence_registry_gate_results.json", "release_evidence_registry", "tools/contracts/release_evidence_registry.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py"), artifact_required=False),
    RegistryRow("targeted_evidence_sql_pushdown", True, True, "artifacts/launch_readiness/targeted_evidence_sql_pushdown_gate_results.json", "targeted_evidence_sql_pushdown", "tools/contracts/targeted_evidence_sql_pushdown.py", ("launch_readiness.py", "a_grade_execution_matrix.py")),
    RegistryRow("cost_overview_no_autoload", True, True, "artifacts/launch_readiness/cost_overview_no_autoload_gate_results.json", "performance_budget_gate", "tools/contracts/performance_budget_gate.py", ("launch_readiness.py",)),
    RegistryRow("query_search_autorun", True, True, "artifacts/launch_readiness/query_search_autorun_gate_results.json", "query_search_autorun", "tools/contracts/query_search_autorun.py", ("launch_readiness.py", "a_grade_execution_matrix.py")),
    RegistryRow("query_boundary_lint", True, True, "artifacts/launch_readiness/query_boundary_lint_gate_results.json", "query_boundary_lint", "tools/contracts/query_boundary_lint.py", ("launch_readiness.py",)),
    RegistryRow("export_case_parity", True, True, "artifacts/launch_readiness/export_case_parity_gate_results.json", "export_case_parity", "tools/contracts/export_case_parity.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py")),
    RegistryRow("daily_ui_export_snapshot_leak_safety", True, True, "artifacts/launch_readiness/rendered_ui_leak_gate_results.json", "rendered_ui_leak_scan", "tools/contracts/rendered_ui_leak_scan.py", ("launch_readiness.py",), proof_rows_required=False),
    RegistryRow("ci_artifact_reality", True, True, "artifacts/launch_readiness/ci_artifact_reality_gate_results.json", "ci_artifact_reality", "tools/contracts/ci_artifact_reality.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py"), proof_rows_required=False),
    RegistryRow("import_laziness", True, True, "artifacts/launch_readiness/import_laziness_gate_results.json", "import_laziness", "tools/contracts/import_laziness.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py"), proof_rows_required=False),
    RegistryRow("a_grade_execution_matrix", True, True, "artifacts/launch_readiness/a_grade_execution_matrix_gate_results.json", "a_grade_execution_matrix", "tools/contracts/a_grade_execution_matrix.py", ("launch_readiness.py", "production_release_candidate.py"), artifact_required=False),
    RegistryRow("launch_readiness", True, True, "artifacts/launch_readiness/launch_readiness_summary.json", "launch_readiness", "tools/contracts/launch_readiness.py", ("production_release_candidate.py",), proof_rows_required=False, artifact_required=False),
    RegistryRow("production_release_candidate", True, True, "artifacts/release_candidate/production_release_candidate_results.json", "production_release_candidate", "tools/contracts/production_release_candidate.py", ("production_release_candidate.py",), proof_rows_required=True, artifact_required=False),
    RegistryRow("ui_system_grade", True, True, "artifacts/launch_readiness/ui_system_grade_gate_results.json", "ui_system_grade", "tools/contracts/ui_system_grade.py", ("launch_readiness.py", "a_grade_execution_matrix.py"), proof_rows_required=False),
    RegistryRow("live_setup_object_drift", True, True, "artifacts/launch_readiness/snowflake_object_drift_gate_results.json", "snowflake_object_drift_validation", "tools/contracts/snowflake_object_drift_validation.py", ("launch_readiness.py", "production_release_candidate.py"), proof_rows_required=False),
    RegistryRow("metadata_probe_cap", True, True, "artifacts/launch_readiness/first_paint_slo_gate_results.json", "first_paint_slo", "tools/contracts/first_paint_slo.py", ("launch_readiness.py", "a_grade_execution_matrix.py")),
    RegistryRow("exact_action_matching", True, True, "artifacts/launch_readiness/action_click_gate_results.json", "action_click_gauntlet", "tools/contracts/action_click_gauntlet.py", ("launch_readiness.py",), proof_rows_required=False),
    RegistryRow("export_parse", True, True, "artifacts/launch_readiness/export_download_gate_results.json", "export_download_gauntlet", "tools/contracts/export_download_gauntlet.py", ("launch_readiness.py",), proof_rows_required=False),
    RegistryRow("sql_cleanup", True, True, "artifacts/launch_readiness/sql_cleanup_gate_results.json", "sql_value_inventory", "tools/contracts/sql_value_inventory.py", ("launch_readiness.py",), proof_rows_required=False),
    RegistryRow("stress_status", True, True, "artifacts/launch_readiness/user_stress_gate_results.json", "user_stress_test", "tools/contracts/user_stress_test.py", ("launch_readiness.py",), proof_rows_required=False),
    RegistryRow("route_action_replay", True, True, "artifacts/launch_readiness/route_action_replay_gate_results.json", "route_action_replay", "tools/contracts/route_action_replay.py", ("launch_readiness.py", "production_release_candidate.py", "a_grade_execution_matrix.py")),
    RegistryRow("metric_source_governance", True, True, "artifacts/launch_readiness/metric_source_governance_gate_results.json", "metric_source_governance", "tools/contracts/metric_source_governance.py", ("launch_readiness.py", "a_grade_execution_matrix.py"), proof_rows_required=False),
)


def _result_artifact_for_gate(artifact_path: str) -> str:
    """Return the producer result artifact paired with a launch gate when conventional."""
    if not artifact_path.startswith(f"{LAUNCH_READINESS_DIR}/"):
        return ""
    name = Path(artifact_path).name
    if not name.endswith("_gate_results.json"):
        return ""
    result_name = name.replace("_gate_results.json", "_results.json")
    return f"{FULL_APP_DIR}/{result_name}"


def iter_required_release_artifacts(
    *,
    production_deployable: bool = True,
    a_grade_ready: bool | None = None,
    include_support_artifacts: bool = True,
    require_proof_rows: bool = True,
) -> tuple[str, ...]:
    """Return the registry-owned artifact list used by release consumers.

    This is intentionally the canonical list; consumers should not maintain
    parallel tuples of required launch artifacts.
    """
    artifacts: list[str] = []
    seen: set[str] = set()
    for row in REGISTRY_ROWS:
        if not row.artifact_required:
            continue
        if require_proof_rows and not row.proof_rows_required:
            continue
        if production_deployable and not row.required_for_production_deployable:
            continue
        if a_grade_ready is True and not row.required_for_a_grade_ready:
            continue
        candidates = [row.artifact_path]
        if include_support_artifacts:
            candidates.extend(row.support_artifact_paths)
        for artifact in candidates:
            if artifact and artifact not in seen:
                seen.add(artifact)
                artifacts.append(artifact)
    return tuple(artifacts)


def required_artifacts_for_consumer(consumer: str, *, include_support_artifacts: bool = False) -> tuple[str, ...]:
    """Return registry artifacts that a contract consumer is expected to use."""
    requested = str(consumer or "").replace("\\", "/")
    artifacts: list[str] = []
    seen: set[str] = set()
    for row in REGISTRY_ROWS:
        if not any(str(item).replace("\\", "/").endswith(requested) or requested.endswith(str(item).replace("\\", "/")) for item in row.required_consumers):
            continue
        if not row.artifact_required:
            continue
        candidates = [row.artifact_path]
        if include_support_artifacts:
            candidates.extend(row.support_artifact_paths)
        for artifact in candidates:
            if artifact and artifact not in seen:
                seen.add(artifact)
                artifacts.append(artifact)
    return tuple(artifacts)


def registry_row_for_gate(gate_id_or_artifact_path: str) -> dict[str, Any]:
    """Return the normalized registry row for a gate id or artifact path."""
    needle = str(gate_id_or_artifact_path or "").replace("\\", "/")
    for row in REGISTRY_ROWS:
        if needle in {row.gate_id, row.artifact_path.replace("\\", "/")}:
            return {
                "gate_id": row.gate_id,
                "artifact_path": row.artifact_path,
                "support_artifact_paths": list(row.support_artifact_paths),
                "expected_producer": row.producer,
                "producer_file": row.producer_file,
                "required_consumers": list(row.required_consumers),
                "required_for_production_deployable": row.required_for_production_deployable,
                "required_for_a_grade_ready": row.required_for_a_grade_ready,
                "proof_rows_required": row.proof_rows_required,
                "artifact_required": row.artifact_required,
                "owner": row.owner,
                "blocker_severity": row.blocker_severity,
                "waiver_policy": row.waiver_policy,
                "launch_readiness_field": row.launch_readiness_field or f"{row.gate_id}_passed",
                "release_summary_field": row.release_summary_field or f"{row.gate_id}_passed",
                "blocking_reason": row.blocking_reason,
                "admin_only_allowed": row.admin_only_allowed,
                "daily_output_facing": row.daily_output_facing,
                "allowed_profiles": list(row.allowed_profiles),
            }
    raise KeyError(f"release evidence registry has no gate for {gate_id_or_artifact_path!r}")


def registry_gate_specs() -> tuple[dict[str, Any], ...]:
    """Return normalized gate metadata for A-grade and release summaries."""
    return tuple(
        {
            "gate_id": row.gate_id,
            "artifact_path": row.artifact_path,
            "support_artifact_paths": list(row.support_artifact_paths),
            "expected_producer": row.producer,
            "producer_file": row.producer_file,
            "required_for_production_deployable": row.required_for_production_deployable,
            "required_for_a_grade_ready": row.required_for_a_grade_ready,
            "proof_rows_required": row.proof_rows_required,
            "artifact_required": row.artifact_required,
            "owner": row.owner,
            "blocker_severity": row.blocker_severity,
            "waiver_policy": row.waiver_policy,
            "launch_readiness_field": row.launch_readiness_field or f"{row.gate_id}_passed",
            "release_summary_field": row.release_summary_field or f"{row.gate_id}_passed",
            "blocking_reason": row.blocking_reason,
        }
        for row in REGISTRY_ROWS
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _git_commit(root: Path) -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False, timeout=10)
    except OSError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _producer_signature() -> str:
    try:
        body = Path(__file__).read_bytes()
    except OSError:
        body = PRODUCER.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _row_signature(gate_id: str, commit_sha: str) -> str:
    return hashlib.sha256(f"{PRODUCER}|{gate_id}|{commit_sha}".encode("utf-8")).hexdigest()


def _load_json(root: Path, rel: str) -> Mapping[str, Any]:
    try:
        payload = json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {"rows": payload if isinstance(payload, list) else []}


def _proof_row_count(payload: Mapping[str, Any]) -> int:
    count = 0
    for key in ("proof_rows", "rows", "checks", "results", "actions", "events"):
        value = payload.get(key)
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, Mapping):
            count += len(value)
    return count


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value or 0)))
    except (TypeError, ValueError):
        return 0


def _consumer_has_artifact(root: Path, consumer: str, artifact_path: str) -> bool:
    path = root / "tools" / "contracts" / consumer
    if not path.exists():
        path = root / consumer
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    stem = Path(artifact_path).stem
    gate_token = stem.replace("_gate_results", "").replace("_results", "")
    uses_registry_helper = any(
        helper in text
        for helper in (
            "iter_required_release_artifacts",
            "required_artifacts_for_consumer",
            "registry_gate_specs",
        )
    )
    return (
        uses_registry_helper
        or artifact_path in text
        or stem in text
        or gate_token in text
        or gate_token.upper() in text
    )


def _release_blocking_artifacts(root: Path) -> set[str]:
    artifacts: set[str] = set()
    launch_dir = root / LAUNCH_READINESS_DIR
    if not launch_dir.exists():
        return artifacts
    for path in launch_dir.glob("*_gate_results.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping) and bool(payload.get("release_blocking")):
            artifacts.add(path.relative_to(root).as_posix())
    return artifacts


def _registry_row(root: Path, spec: RegistryRow, commit_sha: str) -> dict[str, Any]:
    payload = _load_json(root, spec.artifact_path)
    artifact_exists = (root / spec.artifact_path).exists()
    proof_rows = _proof_row_count(payload)
    consumer_misses = [
        consumer for consumer in spec.required_consumers if not _consumer_has_artifact(root, consumer, spec.artifact_path)
    ]
    reasons: list[str] = []
    strict_artifact = spec.artifact_required
    if spec.artifact_required and not artifact_exists:
        reasons.append("registered required artifact is missing")
    if artifact_exists and strict_artifact and not bool(payload.get("passed", True)):
        reasons.append(str(payload.get("failure_reason") or "registered artifact did not pass"))
    if artifact_exists and strict_artifact and _as_int(payload.get("failure_count")) > 0:
        reasons.append(f"registered artifact failure_count={_as_int(payload.get('failure_count'))}")
    if artifact_exists and bool(payload.get("raw_sql_included")):
        reasons.append("registered artifact has raw_sql_included=true")
    if artifact_exists and not str(payload.get("producer") or payload.get("source") or ""):
        reasons.append("registered artifact is missing producer")
    if artifact_exists and not str(payload.get("producer_signature") or payload.get("proof_source") or payload.get("source") or ""):
        reasons.append("registered artifact is missing producer_signature")
    payload_commit = str(payload.get("commit_sha") or payload.get("source_tree_sha") or "")
    if artifact_exists and payload_commit and payload_commit != commit_sha:
        reasons.append("registered artifact commit_sha mismatch")
    if artifact_exists and strict_artifact and spec.proof_rows_required and proof_rows <= 0:
        reasons.append("registered artifact lacks proof rows")
    if consumer_misses:
        reasons.append("required consumer does not import/use registry artifact helper: " + ", ".join(consumer_misses))
    if not spec.owner:
        reasons.append("registry row missing owner")
    if spec.blocker_severity == "advisory" and (not spec.owner or not spec.waiver_policy):
        reasons.append("advisory row lacks owner/rationale/follow-up")
    return {
        "row_id": spec.gate_id,
        "gate_id": spec.gate_id,
        "required_for_production_deployable": spec.required_for_production_deployable,
        "required_for_a_grade_ready": spec.required_for_a_grade_ready,
        "artifact_path": spec.artifact_path,
        "support_artifact_paths": list(spec.support_artifact_paths),
        "launch_readiness_artifact_path": spec.artifact_path,
        "artifact_exists": artifact_exists,
        "artifact_producer": str(payload.get("producer") or payload.get("source") or ""),
        "producer_file": spec.producer_file,
        "producer_signature_required": True,
        "commit_sha_required": True,
        "artifact_hash_required": True,
        "proof_rows_required": spec.proof_rows_required,
        "proof_row_count": proof_rows,
        "row_ids_required": [],
        "raw_sql_included_must_be_false": True,
        "admin_only_allowed": spec.admin_only_allowed,
        "daily_output_facing": spec.daily_output_facing,
        "allowed_profiles": list(spec.allowed_profiles),
        "required_consumers": list(spec.required_consumers),
        "consumer_mismatch_count": len(consumer_misses),
        "owner": spec.owner,
        "blocker_severity": spec.blocker_severity,
        "waiver_policy": spec.waiver_policy,
        "launch_readiness_field": spec.launch_readiness_field or f"{spec.gate_id}_passed",
        "release_summary_field": spec.release_summary_field or f"{spec.gate_id}_passed",
        "blocking_reason": spec.blocking_reason,
        "producer": PRODUCER,
        "producer_signature": _row_signature(spec.gate_id, commit_sha),
        "provenance_origin": "producer",
        "commit_sha": commit_sha,
        "passed": not reasons,
        "failure_reason": "; ".join(reasons),
        "raw_sql_included": False,
    }


def build_release_evidence_registry_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = _git_commit(root_path)
    registered_ids = {row.gate_id for row in REGISTRY_ROWS}
    missing_minimum = sorted(
        {
            "access_control_runtime",
            "runtime_event_ledger",
            "first_paint_slo",
            "performance_budget",
            "artifact_integrity",
            "release_evidence_registry",
            "targeted_evidence_sql_pushdown",
            "cost_overview_no_autoload",
            "query_search_autorun",
            "query_boundary_lint",
            "export_case_parity",
            "daily_ui_export_snapshot_leak_safety",
            "ci_artifact_reality",
            "a_grade_execution_matrix",
            "launch_readiness",
            "production_release_candidate",
            "ui_system_grade",
            "live_setup_object_drift",
            "metadata_probe_cap",
            "exact_action_matching",
            "export_parse",
            "sql_cleanup",
            "stress_status",
            "import_laziness",
            "metric_source_governance",
        }
        - registered_ids
    )
    rows = [_registry_row(root_path, spec, commit_sha) for spec in REGISTRY_ROWS]
    registered_artifacts = {row.artifact_path for row in REGISTRY_ROWS}
    unregistered = sorted(_release_blocking_artifacts(root_path) - registered_artifacts)
    for rel in unregistered:
        rows.append(
            {
                "row_id": f"unregistered::{rel}",
                "gate_id": "unregistered_release_blocking_artifact",
                "artifact_path": rel,
                "producer": PRODUCER,
                "producer_signature": _row_signature(f"unregistered::{rel}", commit_sha),
                "provenance_origin": "producer",
                "commit_sha": commit_sha,
                "passed": False,
                "failure_reason": "release-blocking artifact is not registered",
                "raw_sql_included": False,
            }
        )
    for gate_id in missing_minimum:
        rows.append(
            {
                "row_id": f"missing_registry_row::{gate_id}",
                "gate_id": gate_id,
                "producer": PRODUCER,
                "producer_signature": _row_signature(f"missing::{gate_id}", commit_sha),
                "provenance_origin": "producer",
                "commit_sha": commit_sha,
                "passed": False,
                "failure_reason": "minimum release registry gate is missing",
                "raw_sql_included": False,
            }
        )
    failures = [row for row in rows if not bool(row.get("passed"))]
    signature = _producer_signature()
    return {
        "source": "release_evidence_registry_results",
        "gate": "release_evidence_registry",
        "producer": PRODUCER,
        "producer_signature": signature,
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha,
        "passed": not failures,
        "failure_count": len(failures),
        "registered_gate_count": len(REGISTRY_ROWS),
        "required_artifact_count": sum(1 for row in REGISTRY_ROWS if row.required_for_production_deployable),
        "missing_artifact_count": sum(1 for row in rows if "missing" in str(row.get("failure_reason") or "").lower()),
        "unregistered_artifact_count": len(unregistered),
        "consumer_mismatch_count": sum(_as_int(row.get("consumer_mismatch_count")) for row in rows),
        "rows": rows,
        "proof_rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_release_evidence_registry_gate(results: Mapping[str, Any]) -> dict[str, Any]:
    rows_payload = results.get("rows")
    rows = rows_payload if isinstance(rows_payload, list) else []
    proof_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    failures = [row for row in proof_rows if not bool(row.get("passed"))]
    signature = _producer_signature()
    return {
        "source": "release_evidence_registry_gate_results",
        "gate": "release_evidence_registry",
        "producer": PRODUCER,
        "producer_signature": signature,
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": str(results.get("commit_sha") or ""),
        "passed": bool(results.get("passed")) and not failures,
        "failure_count": len(failures),
        "registered_gate_count": _as_int(results.get("registered_gate_count")),
        "required_artifact_count": _as_int(results.get("required_artifact_count")),
        "missing_artifact_count": _as_int(results.get("missing_artifact_count")),
        "unregistered_artifact_count": _as_int(results.get("unregistered_artifact_count")),
        "consumer_mismatch_count": _as_int(results.get("consumer_mismatch_count")),
        "rows": proof_rows,
        "proof_rows": proof_rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_release_evidence_registry_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_release_evidence_registry_results(root_path)
    gate = build_release_evidence_registry_gate(results)
    _write_json(root_path / RELEASE_EVIDENCE_REGISTRY_RESULTS_REL, results)
    _write_json(root_path / RELEASE_EVIDENCE_REGISTRY_GATE_REL, gate)
    return {
        RELEASE_EVIDENCE_REGISTRY_RESULTS_REL: results,
        RELEASE_EVIDENCE_REGISTRY_GATE_REL: gate,
    }


def main() -> int:
    artifacts = write_release_evidence_registry_artifacts(Path.cwd())
    return 0 if bool(artifacts[RELEASE_EVIDENCE_REGISTRY_GATE_REL].get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RELEASE_EVIDENCE_REGISTRY_GATE_REL",
    "RELEASE_EVIDENCE_REGISTRY_RESULTS_REL",
    "REGISTRY_ROWS",
    "build_release_evidence_registry_gate",
    "build_release_evidence_registry_results",
    "iter_required_release_artifacts",
    "registry_row_for_gate",
    "registry_gate_specs",
    "required_artifacts_for_consumer",
    "write_release_evidence_registry_artifacts",
]
