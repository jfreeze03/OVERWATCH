"""Full app release sweep.

This umbrella gate consumes the runtime/render/click/export/stress artifacts
and converts them into a single launch-blocking release sweep. It deliberately
does not synthesize UI text; every passing surface must be backed by a
producer-written runtime artifact. Feature-specific launch gates are checked as
additional gates, never as substitutes for rendered/clicked/file-backed proof.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping, Sequence, cast

from tools.contracts.full_app_launch_gauntlet import PRIMARY_SECTIONS
from tools.contracts.rendered_ui_leak_scan import FORBIDDEN_TOKENS


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

FULL_APP_RELEASE_SWEEP_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/full_app_release_sweep_results.json"
FULL_APP_RELEASE_FAILURES_REL = f"{FULL_APP_VALIDATION_DIR}/full_app_release_failures.json"
FULL_APP_RELEASE_SWEEP_GATE_REL = f"{LAUNCH_READINESS_DIR}/full_app_release_sweep_gate_results.json"

PRIMARY_OVERVIEW_ALIASES: Mapping[str, Sequence[str]] = {
    "Executive Landing": ("Executive Overview", "Overview"),
    "DBA Control Room": ("Morning Cockpit", "Overview"),
    "Alert Center": ("Active Alerts", "Overview", "Open"),
    "Cost & Contract": ("Cost Overview", "Overview"),
    "Workload Operations": ("Workload Overview", "Overview"),
    "Security Monitoring": ("Security Overview", "Overview"),
}

REQUIRED_RELEASE_SURFACES: tuple[dict[str, Any], ...] = (
    *(
        {
            "area": "primary_overview",
            "section": section,
            "workflow": "Overview",
            "aliases": aliases,
            "require_command_brief": True,
        }
        for section, aliases in PRIMARY_OVERVIEW_ALIASES.items()
    ),
    {"area": "loaded_surface", "section": "Alert Center", "workflow": "Loaded", "aliases": ("Loaded",), "require_action": True},
    {"area": "loaded_surface", "section": "Cost & Contract", "workflow": "Loaded", "aliases": ("Loaded",), "require_action": True},
    {"area": "loaded_surface", "section": "Workload Operations", "workflow": "Loaded", "aliases": ("Loaded",), "require_action": True},
    {"area": "loaded_surface", "section": "Security Monitoring", "workflow": "Loaded", "aliases": ("Loaded",), "require_action": True},
    {"area": "query_search", "section": "Query Search", "workflow": "No click", "aliases": ("No click",)},
    {"area": "query_search", "section": "Query Search", "workflow": "Explicit search", "aliases": ("Explicit search",), "require_action": True},
    {"area": "advanced_scope", "section": "Advanced Scope", "workflow": "Default", "aliases": ("Default", "Active filters")},
    {"area": "advanced_scope", "section": "Advanced Scope", "workflow": "Active filters", "aliases": ("Active filters",)},
    {"area": "settings", "section": "Settings", "workflow": "Default", "aliases": ("Default",)},
    {"area": "settings_admin", "section": "Settings/Admin Setup Health", "workflow": "Setup Health", "aliases": ("Setup Health",)},
    {"area": "fallback", "section": "Packet Missing", "workflow": "Fallback", "aliases": ("Fallback",)},
    {"area": "fallback", "section": "Packet Closest Fallback", "workflow": "Fallback", "aliases": ("Fallback",)},
    {"area": "fallback", "section": "Snowflake Unavailable", "workflow": "Fallback", "aliases": ("Fallback",)},
    {"area": "fallback", "section": "Permission Denied", "workflow": "Fallback", "aliases": ("Fallback",)},
    {"area": "targeted_evidence", "section": "Targeted Evidence", "workflow": "Route action", "aliases": ("Route action",), "require_action": True},
    {"area": "targeted_evidence", "section": "Targeted Evidence", "workflow": "Evidence action", "aliases": ("Evidence action",), "require_action": True},
    {"area": "cost_workbench", "section": "Cost Workbench", "workflow": "Explicit action", "aliases": ("Explicit action",), "require_action": True},
    {
        "area": "cortex_efficiency",
        "section": "Cortex Efficiency",
        "workflow": "Explicit action",
        "aliases": ("Explicit action",),
        "require_action": True,
        "require_export": True,
        "require_case": True,
        "linked_gate": "cortex_token_efficiency_gate_results",
    },
    {
        "area": "security_credential",
        "section": "Security Credential Evidence",
        "workflow": "Explicit action",
        "aliases": ("Explicit action",),
        "require_action": True,
        "require_export": True,
        "require_case": True,
        "linked_gate": "security_credential_evidence_gate_results",
    },
)

RAW_SOURCE_TOKENS = tuple(
    token
    for token in FORBIDDEN_TOKENS
    if token not in {"SELECT", "WITH", "JOIN", "CALL"}
    if token.isupper()
    or "_" in token
    or token
    in {
        "raw SQL",
        "procedure name",
        "stack trace",
        "no Snowflake connection",
        "No Snowflake connection",
        "RoleGate",
        "Lock button",
    }
)
INTERNAL_WORDING_TOKENS = (
    "fixture",
    "mock",
    "proof",
    "internal test",
    "test mode",
    "synthetic",
    "deterministic",
    "no Snowflake connection",
    "demo role",
    "RoleGate",
    "Lock button",
)
DIAGNOSTIC_TOKENS = (
    "diagnostic card",
    "setup validation row",
    "Traceback",
    "StreamlitAPIException",
    "SnowflakeSQLException",
    "stack trace",
)
ACCEPTABLE_PROOF_SOURCES = {
    "rendered_app",
    "deterministic_streamlit_rendered",
    "browser_rendered",
    "clicked_action",
    "file_backed_export",
    "case_payload",
    "runtime_stress_sequence",
    "live_validation",
    "owner_skipped",
}
REJECTED_PROOF_SOURCES = {
    "synthetic_safe_fallback",
    "manual_safe_text",
    "static_contract_only",
    "test_constructed_payload",
    "post_stamped_provenance",
    "lower_artifact_rendered",
    "fixture",
}
REQUIRED_RUNTIME_ROW_FIELDS = (
    "producer",
    "producer_signature",
    "provenance_origin",
    "commit_sha",
    "generated_at",
    "source",
    "runtime_source",
    "section",
    "workflow",
)
REQUIRED_FIRST_PAINT_FIELDS = (
    "cold_first_paint_packet_query_count",
    "warm_first_paint_query_count",
    "evidence_query_count",
    "account_usage_count",
    "detail_query_count",
    "cost_workbench_query_count",
    "query_search_query_count",
    "direct_sql_count",
    "session_open_count",
    "elapsed_ms",
    "product_boundary",
    "execution_boundary",
    "passed",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_commit(root: Path | None = None) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root or Path.cwd()),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_int(value: object) -> int:
    try:
        return int(cast(Any, value) or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: object) -> float:
    try:
        return float(cast(Any, value) or 0)
    except (TypeError, ValueError):
        return 0.0


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_payloads(root: Path, rels: Iterable[str]) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for rel in sorted(set(rels)):
        path = root / rel
        if not path.exists():
            continue
        try:
            payloads[rel] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payloads[rel] = {"passed": False, "failure_reason": "malformed_json"}
    return payloads


def _text_from(row: Mapping[str, Any]) -> str:
    return "\n".join(
        str(row.get(key) or "")
        for key in (
            "html_fragment",
            "rendered_text",
            "first_viewport_text",
            "text",
            "fragment",
            "headline",
            "summary",
            "fallback_text",
        )
    )[:20000]


def _markup_from(row: Mapping[str, Any]) -> str:
    return str(row.get("html_fragment") or row.get("text") or row.get("rendered_text") or "")


def _token_count(text: str, tokens: Sequence[str]) -> int:
    lower = text.lower()
    upper = text.upper()
    count = 0
    for token in tokens:
        haystack = upper if token.isupper() or "_" in token else lower
        needle = token if token.isupper() or "_" in token else token.lower()
        if needle in haystack:
            count += 1
    return count


def _is_admin_allowed(section: str, workflow: str, row: Mapping[str, Any]) -> bool:
    return (
        bool(row.get("admin_only"))
        or section == "Settings/Admin Setup Health"
        or "setup health" in workflow.lower()
    )


def _render_sources(payloads: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    sources: list[tuple[str, Mapping[str, Any]]] = []
    for rel in (
        "artifacts/full_app_validation/view_results.json",
        "artifacts/full_app_validation/rendered_fragments.json",
    ):
        for row in _as_list(payloads.get(rel)):
            mapping = _as_mapping(row)
            if mapping:
                sources.append((rel, mapping))
    for row in _as_list(payloads.get("artifacts/full_app_validation/query_search_results.json")):
        mapping = _as_mapping(row)
        case = str(mapping.get("case") or "")
        if case == "render_no_click":
            mapping = {**mapping, "section": "Query Search", "workflow": "No click"}
        elif case in {"exact_query_id", "query_signature", "text_contains_explicit_search"}:
            mapping = {**mapping, "section": "Query Search", "workflow": "Explicit search"}
        else:
            continue
        sources.append(("artifacts/full_app_validation/query_search_results.json", mapping))
    return sources


def _find_render_row(
    payloads: Mapping[str, Any],
    section: str,
    aliases: Sequence[str],
) -> tuple[str, Mapping[str, Any]]:
    for rel, row in _render_sources(payloads):
        if str(row.get("section") or "") != section:
            continue
        workflow = str(row.get("workflow") or "")
        if not aliases or workflow in aliases:
            return rel, row
    return "", {}


def _first_paint_row(payloads: Mapping[str, Any], section: str, aliases: Sequence[str]) -> Mapping[str, Any]:
    perf = _as_mapping(payloads.get("artifacts/full_app_validation/first_paint_performance_results.json"))
    for row in _as_list(perf.get("rows")):
        mapping = _as_mapping(row)
        if str(mapping.get("section") or "") != section:
            continue
        if str(mapping.get("workflow") or "") in aliases or section not in PRIMARY_SECTIONS:
            return mapping
    for row in _as_list(perf.get("rows")):
        mapping = _as_mapping(row)
        if str(mapping.get("section") or "") == section:
            return mapping
    return {}


def _proof_source(row: Mapping[str, Any]) -> str:
    return str(row.get("source") or row.get("proof_source") or "").strip()


def _runtime_provenance_failures(row: Mapping[str, Any], *, current_commit: str) -> list[str]:
    reasons: list[str] = []
    if not row:
        return ["producer-backed runtime row missing"]
    missing = [field for field in REQUIRED_RUNTIME_ROW_FIELDS if not row.get(field)]
    if missing:
        reasons.append(f"runtime row missing provenance fields: {', '.join(missing)}")
    source = _proof_source(row)
    if source in REJECTED_PROOF_SOURCES:
        reasons.append(f"runtime row uses rejected proof source: {source}")
    elif source and source not in ACCEPTABLE_PROOF_SOURCES:
        reasons.append(f"runtime row uses unapproved proof source: {source}")
    if str(row.get("provenance_origin") or "") != "producer":
        reasons.append("runtime row provenance was not producer-written")
    row_commit = str(row.get("commit_sha") or "")
    if current_commit and row_commit and row_commit != current_commit:
        reasons.append("runtime row commit_sha does not match current commit")
    if bool(row.get("raw_sql_included")):
        reasons.append("runtime row included raw SQL")
    if bool(row.get("fixture_mode")) and str(row.get("launch_profile") or "") in {"internal_live", "prod_candidate"}:
        reasons.append("fixture-only runtime proof cannot satisfy live/prod release sweep")
    return reasons


def _first_paint_failures(row: Mapping[str, Any], *, current_commit: str) -> list[str]:
    reasons = _runtime_provenance_failures(row, current_commit=current_commit)
    missing = [field for field in REQUIRED_FIRST_PAINT_FIELDS if field not in row]
    if missing:
        reasons.append(f"first-paint row missing required fields: {', '.join(missing)}")
    if not str(row.get("product_boundary") or "").strip():
        reasons.append("first-paint row missing product_boundary")
    if not str(row.get("execution_boundary") or "").strip():
        reasons.append("first-paint row missing execution_boundary")
    if bool(row.get("raw_sql_included")):
        reasons.append("first-paint row included raw SQL")
    return reasons


def _gate(payloads: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _as_mapping(payloads.get(f"artifacts/launch_readiness/{key}.json")) or _as_mapping(
        payloads.get(key)
    )


def _action_failure_count(payloads: Mapping[str, Any]) -> int:
    gate = _gate(payloads, "action_click_gate_results")
    results = _as_mapping(payloads.get("artifacts/full_app_validation/action_click_results.json"))
    return _as_int(gate.get("failure_count")) or _as_int(results.get("failure_count"))


def _export_failure_count(payloads: Mapping[str, Any]) -> int:
    gate = _gate(payloads, "export_download_gate_results")
    return _as_int(gate.get("failure_count"))


def _rows_from_payload(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [_as_mapping(row) for row in value if isinstance(row, Mapping)]
    mapping = _as_mapping(value)
    for key in ("rows", "actions", "results", "cases", "features"):
        rows = mapping.get(key)
        if isinstance(rows, list):
            return [_as_mapping(row) for row in rows if isinstance(row, Mapping)]
    return []


def _artifact_rows(payloads: Mapping[str, Any], rel: str) -> list[Mapping[str, Any]]:
    return _rows_from_payload(payloads.get(rel))


def _row_id(row: Mapping[str, Any]) -> str:
    return str(
        row.get("id")
        or row.get("row_id")
        or row.get("validation_id")
        or row.get("stable_key")
        or row.get("key")
        or row.get("filename")
        or row.get("runtime_artifact_row_index")
        or ""
    )


def _row_matches(row: Mapping[str, Any], section: str, aliases: Sequence[str]) -> bool:
    if str(row.get("section") or "") != section:
        return False
    workflow = str(row.get("workflow") or "")
    return not aliases or workflow in aliases


def _find_action_row(
    payloads: Mapping[str, Any],
    *,
    section: str,
    aliases: Sequence[str],
    area: str,
) -> tuple[str, Mapping[str, Any]]:
    action_rels = (
        "artifacts/full_app_validation/button_click_results.json",
        "artifacts/full_app_validation/action_click_results.json",
        "artifacts/full_app_validation/query_search_results.json",
    )
    for rel in action_rels:
        for row in _artifact_rows(payloads, rel):
            if not bool(row.get("clicked", row.get("passed", False))):
                continue
            row_section = str(row.get("section") or "")
            row_workflow = str(row.get("workflow") or "")
            if area == "query_search":
                case = str(row.get("case") or "")
                if row_section in {"Workload Operations", "Query Search"} and case not in {"render_no_click", "text_contains_no_autorun", "warehouse_prefill_no_autorun"}:
                    return rel, row
            elif area == "loaded_surface":
                if row_section == section and str(row.get("action_area") or "") in {"evidence_action", "cost_workbench"}:
                    return rel, row
            elif area == "targeted_evidence":
                if str(row.get("action_area") or "") in {"route_action", "evidence_action", "cost_workbench"}:
                    return rel, row
            elif area == "cost_workbench":
                if str(row.get("action_area") or "") == "cost_workbench" and (row_section == "Cost & Contract" or row_section == section):
                    return rel, row
            elif row_section == section and (not aliases or row_workflow in aliases):
                return rel, row
    return "", {}


def _find_export_row(payloads: Mapping[str, Any], *, section: str, aliases: Sequence[str]) -> tuple[str, Mapping[str, Any]]:
    rel = "artifacts/full_app_validation/export_results.json"
    for row in _artifact_rows(payloads, rel):
        if _row_matches(row, section, aliases):
            return rel, row
    return "", {}


def _find_case_row(payloads: Mapping[str, Any], *, section: str, aliases: Sequence[str]) -> tuple[str, Mapping[str, Any]]:
    rel = "artifacts/full_app_validation/case_payload_results.json"
    for row in _artifact_rows(payloads, rel):
        if _row_matches(row, section, aliases):
            return rel, row
    return "", {}


def _resolve_payload_path(root: Path, payload_file: object) -> Path:
    raw = Path(str(payload_file or ""))
    return raw if raw.is_absolute() else root / raw


def _artifact_payload(payloads: Mapping[str, Any], root: Path, rel: str) -> Any:
    normalized = str(rel or "").replace("\\", "/")
    if normalized in payloads:
        return payloads[normalized]
    raw_path = Path(str(rel or ""))
    path = raw_path if raw_path.is_absolute() else root / normalized
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"passed": False, "failure_reason": "malformed_json"}


def _referenced_row(
    payloads: Mapping[str, Any],
    root: Path,
    *,
    artifact_path: str,
    row_id: object = "",
    row_index: object = None,
) -> Mapping[str, Any]:
    rows = _artifact_rows(payloads, artifact_path)
    if not rows:
        rows = _rows_from_payload(_artifact_payload(payloads, root, artifact_path))
    wanted_id = str(row_id or "").strip()
    if wanted_id:
        for row in rows:
            if _row_id(row) == wanted_id:
                return row
    try:
        index = int(cast(Any, row_index))
    except (TypeError, ValueError):
        index = -1
    if 0 <= index < len(rows):
        return rows[index]
    return {}


def _credential_export_content_failures(row: Mapping[str, Any], text: str) -> list[str]:
    if str(row.get("section") or "") != "Security Credential Evidence":
        return []
    reader = csv.DictReader(text.splitlines())
    columns = set(reader.fieldnames or [])
    parsed_rows = list(reader)
    required = {"User", "Credential", "Type", "Status", "Recommended action"}
    reasons = []
    missing = sorted(required - columns)
    if missing:
        reasons.append(f"credential export missing required columns: {', '.join(missing)}")
    if "Expires" not in columns and "Days left" not in columns:
        reasons.append("credential export missing Expires or Days left column")
    forbidden_columns = {"USER_ID", "RAW_USER_ID", "CREDENTIAL_ID", "SOURCE_OBJECT", "RAW_SQL", "query_text", "QUERY_TEXT"}
    leaked_columns = sorted(column for column in columns if column in forbidden_columns)
    if leaked_columns and not bool(row.get("admin_only")):
        reasons.append(f"credential default export leaks raw columns: {', '.join(leaked_columns)}")
    visible_rows = _as_int(row.get("visible_row_count") or row.get("row_count"))
    if visible_rows != len(parsed_rows):
        reasons.append("credential export parsed row count differs from visible row count")
    return reasons


def _credential_case_content_failures(row: Mapping[str, Any], text: str) -> list[str]:
    if str(row.get("section") or "") != "Security Credential Evidence":
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ["credential case payload is not valid JSON"]
    required = {
        "section",
        "workflow",
        "scope",
        "target",
        "freshness",
        "source_family",
        "summary",
        "row_count",
        "visible_row_count",
        "recommended_action",
        "expired_count",
        "expiring_30d_count",
        "next_expiration",
        "owner_labels",
    }
    missing = sorted(field for field in required if field not in payload)
    reasons = [f"credential case payload missing required fields: {', '.join(missing)}"] if missing else []
    if str(payload.get("source_family") or "") != "credential_expiration":
        reasons.append("credential case payload source_family must be credential_expiration")
    visible_rows = _as_int(row.get("visible_row_count") or row.get("row_count"))
    if visible_rows != _as_int(payload.get("visible_row_count")):
        reasons.append("credential case visible row count differs from payload")
    if "USER_ID" in text.upper() and not bool(row.get("admin_only")):
        reasons.append("credential default case payload leaks USER_ID")
    if "CREDENTIAL_ID" in text.upper() and not bool(row.get("admin_only")):
        reasons.append("credential default case payload leaks CREDENTIAL_ID")
    return reasons


def _file_backed_failures(row: Mapping[str, Any], *, root: Path, row_kind: str) -> list[str]:
    reasons: list[str] = []
    payload_file = str(row.get("payload_file") or "")
    if not payload_file:
        return [f"{row_kind} row missing payload_file"]
    path = _resolve_payload_path(root, payload_file)
    if not path.exists():
        return [f"{row_kind} payload file missing"]
    payload = path.read_bytes()
    size = len(payload)
    expected_size = _as_int(row.get("size_bytes") or row.get("content_length"))
    if expected_size and expected_size != size:
        reasons.append(f"{row_kind} payload size mismatch")
    expected_sha = str(row.get("sha256") or row.get("payload_hash") or "")
    if expected_sha:
        actual_sha = hashlib.sha256(payload).hexdigest()
        if actual_sha != expected_sha:
            reasons.append(f"{row_kind} payload sha256 mismatch")
    if size <= 0 and not bool(row.get("intentional_empty")):
        reasons.append(f"{row_kind} payload is empty without intentional_empty=true")
    parsed_rows = _as_int(row.get("parsed_row_count") or row.get("payload_row_count") or row.get("row_count"))
    visible_rows = _as_int(row.get("visible_row_count") or row.get("row_count"))
    if parsed_rows != visible_rows:
        reasons.append(f"{row_kind} parsed row count differs from visible row count")
    if not str(row.get("content_type") or row.get("mime") or "").strip():
        reasons.append(f"{row_kind} row missing content_type")
    text = payload.decode("utf-8", errors="ignore")
    if not bool(row.get("admin_only")):
        forbidden_count = (
            _token_count(text, RAW_SOURCE_TOKENS)
            + _token_count(text, INTERNAL_WORDING_TOKENS)
            + _token_count(text, DIAGNOSTIC_TOKENS)
        )
        if forbidden_count:
            reasons.append(f"{row_kind} default payload contains forbidden daily/internal token")
        if "QUERY_TEXT" in text.upper() or "query_text" in text:
            reasons.append(f"{row_kind} default payload contains query_text")
    if bool(row.get("raw_sql_included")):
        reasons.append(f"{row_kind} row included raw SQL")
    if row_kind == "export":
        reasons.extend(_credential_export_content_failures(row, text))
    if row_kind == "case payload":
        reasons.extend(_credential_case_content_failures(row, text))
    return reasons


def _linked_gate_reference_failures(
    linked_gate: Mapping[str, Any],
    payloads: Mapping[str, Any],
    *,
    root: Path,
    current_commit: str,
    expected_section: str,
    expected_workflow: str,
    aliases: Sequence[str],
) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    dereferenced: dict[str, Any] = {}
    specs = (
        ("rendered", "rendered_artifact_path", "rendered_row_id", "rendered_row_index", ""),
        ("action", "action_artifact_path", "action_row_id", "action_row_index", ""),
        ("export", "export_artifact_path", "export_row_id", "export_row_index", "export"),
        ("case payload", "case_payload_artifact_path", "case_payload_row_id", "case_payload_row_index", "case payload"),
    )
    for label, path_key, id_key, index_key, file_kind in specs:
        artifact_path = str(linked_gate.get(path_key) or "")
        row_id = linked_gate.get(id_key)
        row_index = linked_gate.get(index_key)
        if not artifact_path:
            reasons.append(f"linked feature gate missing {path_key}")
            continue
        if not row_id:
            reasons.append(f"linked feature gate missing {id_key}")
            continue
        row = _referenced_row(
            payloads,
            root,
            artifact_path=artifact_path,
            row_id=row_id,
            row_index=row_index,
        )
        if not row:
            reasons.append(f"linked feature gate {label} row not found")
            continue
        dereferenced[label] = row
        if str(row.get("section") or "") != expected_section:
            reasons.append(f"linked feature gate {label} row section mismatch")
        workflow = str(row.get("workflow") or "")
        if workflow not in aliases and workflow != expected_workflow:
            reasons.append(f"linked feature gate {label} row workflow mismatch")
        reasons.extend(f"{label}: {reason}" for reason in _runtime_provenance_failures(row, current_commit=current_commit))
        if label == "action" and not bool(row.get("clicked", row.get("passed", False))):
            reasons.append("linked feature gate action row was not clicked")
        if file_kind:
            reasons.extend(_file_backed_failures(row, root=root, row_kind=file_kind))

    visible_row_count = _as_int(linked_gate.get("visible_row_count"))
    exported_row_count = _as_int(linked_gate.get("exported_row_count"))
    case_row_count = _as_int(linked_gate.get("case_row_count") or linked_gate.get("case_payload_row_count"))
    export_row = _as_mapping(dereferenced.get("export"))
    case_row = _as_mapping(dereferenced.get("case payload"))
    if export_row:
        export_count = _as_int(export_row.get("parsed_row_count") or export_row.get("row_count"))
        if exported_row_count and export_count != exported_row_count:
            reasons.append("linked feature gate exported row count disagrees with export artifact")
        if visible_row_count and export_count != visible_row_count:
            reasons.append("linked feature gate visible row count disagrees with export artifact")
    if case_row:
        parsed_case_count = _as_int(case_row.get("parsed_row_count") or case_row.get("row_count"))
        if case_row_count and parsed_case_count != case_row_count:
            reasons.append("linked feature gate case row count disagrees with case artifact")
        if visible_row_count and parsed_case_count != visible_row_count:
            reasons.append("linked feature gate visible row count disagrees with case artifact")
    return reasons, dereferenced


def _global_gate_failed(payloads: Mapping[str, Any], key: str) -> bool:
    gate = _gate(payloads, key)
    return bool(gate) and not bool(gate.get("passed", False))


def _surface_row(surface: Mapping[str, Any], payloads: Mapping[str, Any], *, current_commit: str, root: Path) -> dict[str, Any]:
    section = str(surface["section"])
    workflow = str(surface["workflow"])
    aliases = tuple(str(item) for item in surface.get("aliases") or (workflow,))
    linked_gate_key = str(surface.get("linked_gate") or "")
    source_artifact = ""
    render_row: Mapping[str, Any] = {}
    source_artifact, render_row = _find_render_row(payloads, section, aliases)
    rendered = bool(render_row.get("rendered", True)) if render_row else False
    action_artifact = ""
    action_row: Mapping[str, Any] = {}
    export_artifact = ""
    export_row: Mapping[str, Any] = {}
    case_artifact = ""
    case_row: Mapping[str, Any] = {}
    if bool(surface.get("require_action")):
        action_artifact, action_row = _find_action_row(payloads, section=section, aliases=aliases, area=str(surface["area"]))
    if bool(surface.get("require_export")):
        export_artifact, export_row = _find_export_row(payloads, section=section, aliases=aliases)
    if bool(surface.get("require_case")):
        case_artifact, case_row = _find_case_row(payloads, section=section, aliases=aliases)

    text = _text_from(render_row)
    admin_allowed = _is_admin_allowed(section, workflow, render_row)
    diagnostic_leak_count = 0 if admin_allowed else _token_count(text, DIAGNOSTIC_TOKENS)
    internal_wording_leak_count = 0 if admin_allowed else _token_count(text, INTERNAL_WORDING_TOKENS)
    raw_source_leak_count = 0 if admin_allowed else _token_count(text, RAW_SOURCE_TOKENS)
    old_board_marker_count = _as_int(render_row.get("old_board_marker_count"))
    if text:
        old_board_marker_count += sum(
            text.lower().count(marker)
            for marker in ("card wall", "launchpad", "watch floor", "command deck", "lane board")
        )
    diagnostic_card_count = _as_int(render_row.get("diagnostic_card_count")) + diagnostic_leak_count
    synthetic = str(render_row.get("proof_source") or render_row.get("source") or "").lower() in {
        "synthetic_safe_fallback",
        "manual_safe_text",
        "static_contract_only",
        "test_constructed_payload",
        "lower_artifact_rendered",
        "fixture",
    }
    fp = _first_paint_row(payloads, section, aliases)
    missing_first_paint_row = section in PRIMARY_SECTIONS and not bool(fp)
    render_provenance_failures = _runtime_provenance_failures(render_row, current_commit=current_commit)
    action_provenance_failures = (
        _runtime_provenance_failures(action_row, current_commit=current_commit)
        if bool(surface.get("require_action"))
        else []
    )
    export_provenance_failures = (
        _runtime_provenance_failures(export_row, current_commit=current_commit)
        if bool(surface.get("require_export"))
        else []
    )
    case_provenance_failures = (
        _runtime_provenance_failures(case_row, current_commit=current_commit)
        if bool(surface.get("require_case"))
        else []
    )
    first_paint_provenance_failures = (
        ["first-paint row missing"]
        if missing_first_paint_row
        else (_first_paint_failures(fp, current_commit=current_commit) if section in PRIMARY_SECTIONS else [])
    )
    first_paint_query_count = _as_int(
        fp.get("cold_first_paint_packet_query_count")
        or fp.get("packet_query_count")
        or _as_mapping(render_row.get("first_paint")).get("observed_packet_queries")
    )
    warm_query_count = _as_int(fp.get("warm_first_paint_query_count") or _as_mapping(render_row.get("first_paint")).get("warm_packet_queries"))
    evidence_query_count = _as_int(fp.get("evidence_query_count"))
    account_usage_count = _as_int(fp.get("account_usage_count"))
    detail_query_count = _as_int(fp.get("detail_query_count"))
    cost_workbench_query_count = _as_int(fp.get("cost_workbench_query_count"))
    query_search_query_count = _as_int(fp.get("query_search_query_count"))
    direct_sql_count = _as_int(fp.get("direct_sql_count"))
    session_open_count = _as_int(fp.get("session_open_count"))
    elapsed_ms = _as_float(fp.get("elapsed_ms") or render_row.get("elapsed_ms"))
    markup = _markup_from(render_row)
    command_brief_count = _as_int(render_row.get("summary_board_count")) or markup.count("ow-kit-command-brief")
    marker_count = markup.count("ow-decision-workspace-marker")
    require_command_brief = bool(surface.get("require_command_brief"))

    action_failure_count = _action_failure_count(payloads) if surface["area"] in {"targeted_evidence", "cost_workbench", "settings", "settings_admin"} else 0
    export_failure_count = _export_failure_count(payloads) if surface["area"] in {"security_credential", "cortex_efficiency"} else 0
    clicked = bool(action_row) if bool(surface.get("require_action")) else surface["area"] not in {"primary_overview", "fallback", "advanced_scope"}
    exported = bool(export_row) and bool(case_row) if surface["area"] in {"security_credential", "cortex_efficiency"} else False

    reasons: list[str] = []
    if not source_artifact or not render_row:
        reasons.append("required surface missing")
    if not rendered:
        reasons.append("rendered proof missing")
    if synthetic:
        reasons.append("synthetic fallback cannot pass release sweep")
    reasons.extend(render_provenance_failures)
    if bool(surface.get("require_action")):
        if not action_artifact or not action_row:
            reasons.append("required action/click row missing")
        if action_row and not bool(action_row.get("clicked", action_row.get("passed", False))):
            reasons.append("required action was not clicked")
        reasons.extend(action_provenance_failures)
    if bool(surface.get("require_export")):
        if not export_artifact or not export_row:
            reasons.append("required export row missing")
        reasons.extend(export_provenance_failures)
        reasons.extend(_file_backed_failures(export_row, root=root, row_kind="export") if export_row else [])
    if bool(surface.get("require_case")):
        if not case_artifact or not case_row:
            reasons.append("required case payload row missing")
        reasons.extend(case_provenance_failures)
        reasons.extend(_file_backed_failures(case_row, root=root, row_kind="case payload") if case_row else [])
    if linked_gate_key:
        linked_gate = _gate(payloads, linked_gate_key)
        if not linked_gate:
            reasons.append("linked feature gate artifact missing")
        elif not bool(linked_gate.get("passed")):
            reasons.append("linked feature gate failed")
        else:
            linked_reasons, _linked_rows = _linked_gate_reference_failures(
                linked_gate,
                payloads,
                root=root,
                current_commit=current_commit,
                expected_section=section,
                expected_workflow=workflow,
                aliases=aliases,
            )
            reasons.extend(linked_reasons)
    if require_command_brief and command_brief_count != 1:
        reasons.append("primary overview must render exactly one CommandBrief")
    if require_command_brief and marker_count != 1:
        reasons.append("primary overview must render exactly one Decision Workspace marker")
    if old_board_marker_count:
        reasons.append("old board marker appears")
    if diagnostic_card_count:
        reasons.append("diagnostic/internal card leak appears")
    if internal_wording_leak_count:
        reasons.append("internal wording leak appears")
    if raw_source_leak_count:
        reasons.append("raw source token leak appears")
    if section in PRIMARY_SECTIONS:
        reasons.extend(first_paint_provenance_failures)
        if first_paint_query_count > 1:
            reasons.append("cold first paint exceeded one packet query")
        if warm_query_count:
            reasons.append("warm first paint ran queries")
        if (
            evidence_query_count
            or account_usage_count
            or detail_query_count
            or cost_workbench_query_count
            or query_search_query_count
            or direct_sql_count
        ):
            reasons.append("first paint crossed evidence/Account Usage/direct SQL boundary")
    if action_failure_count:
        reasons.append("visible action/click proof failed")
    if export_failure_count:
        reasons.append("export/download/case proof failed")

    return {
        "area": str(surface["area"]),
        "section": section,
        "workflow": workflow,
        "source_artifact": source_artifact,
        "action_artifact": action_artifact,
        "action_row_id": _row_id(action_row),
        "export_artifact": export_artifact,
        "export_row_id": _row_id(export_row),
        "case_payload_artifact": case_artifact,
        "case_payload_row_id": _row_id(case_row),
        "rendered": rendered,
        "clicked": clicked,
        "exported": exported,
        "first_paint_query_count": first_paint_query_count,
        "warm_query_count": warm_query_count,
        "evidence_query_count": evidence_query_count,
        "account_usage_count": account_usage_count,
        "detail_query_count": detail_query_count,
        "cost_workbench_query_count": cost_workbench_query_count,
        "query_search_query_count": query_search_query_count,
        "direct_sql_count": direct_sql_count,
        "session_open_count": session_open_count,
        "elapsed_ms": elapsed_ms,
        "diagnostic_leak_count": diagnostic_card_count,
        "internal_wording_leak_count": internal_wording_leak_count,
        "raw_source_leak_count": raw_source_leak_count,
        "old_board_marker_count": old_board_marker_count,
        "command_brief_count": command_brief_count,
        "decision_workspace_marker_count": marker_count,
        "action_failure_count": action_failure_count,
        "export_failure_count": export_failure_count,
        "missing_first_paint_row": missing_first_paint_row,
        "producer_provenance_failure_count": (
            len(render_provenance_failures)
            + len(action_provenance_failures)
            + len(export_provenance_failures)
            + len(case_provenance_failures)
            + len(first_paint_provenance_failures)
        ),
        "synthetic_render_used": synthetic,
        "passed": not reasons,
        "failure_reason": "; ".join(dict.fromkeys(reasons)),
        "raw_sql_included": False,
    }


def build_full_app_release_sweep(
    payloads: Mapping[str, Any],
    *,
    current_commit: str | None = None,
    root: Path | str = ".",
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved_commit = current_commit if current_commit is not None else _git_commit()
    root_path = Path(root).resolve()
    rows = [
        _surface_row(surface, payloads, current_commit=resolved_commit, root=root_path)
        for surface in REQUIRED_RELEASE_SURFACES
    ]
    gate_checks = (
        ("runtime_artifact_provenance", "runtime_artifact_provenance_gate_results"),
        ("rendered_ui_leak_scan", "rendered_ui_leak_gate_results"),
        ("action_click_gauntlet", "action_click_gate_results"),
        ("export_download_gauntlet", "export_download_gate_results"),
        ("settings_live_feature_gauntlet", "settings_live_feature_gate_results"),
        ("performance_budget_gate", "performance_budget_gate_results"),
        ("user_stress_test", "user_stress_gate_results"),
        ("sql_cleanup_gate", "sql_cleanup_gate_results"),
        ("delete_first_cleanup_gate", "delete_first_cleanup_gate_results"),
        ("security_credential_evidence", "security_credential_evidence_gate_results"),
        ("cortex_token_efficiency", "cortex_token_efficiency_gate_results"),
    )
    gate_rows: list[dict[str, Any]] = []
    for area, key in gate_checks:
        gate = _gate(payloads, key)
        if not gate:
            gate_rows.append(
                {
                    "area": area,
                    "section": area,
                    "workflow": "gate",
                    "source_artifact": f"artifacts/launch_readiness/{key}.json",
                    "rendered": False,
                    "clicked": False,
                    "exported": False,
                    "first_paint_query_count": 0,
                    "warm_query_count": 0,
                    "evidence_query_count": 0,
                    "account_usage_count": 0,
                    "direct_sql_count": 0,
                    "session_open_count": 0,
                    "elapsed_ms": 0,
                    "diagnostic_leak_count": 0,
                    "internal_wording_leak_count": 0,
                    "raw_source_leak_count": 0,
                    "old_board_marker_count": 0,
                    "action_failure_count": 0,
                    "export_failure_count": 0,
                    "passed": False,
                    "failure_reason": "required release gate artifact missing",
                    "raw_sql_included": False,
                }
            )
            continue
        gate_rows.append(
            {
                "area": area,
                "section": area,
                "workflow": "gate",
                "source_artifact": f"artifacts/launch_readiness/{key}.json",
                "rendered": True,
                "clicked": True,
                "exported": key == "export_download_gate_results",
                "first_paint_query_count": 0,
                "warm_query_count": 0,
                "evidence_query_count": 0,
                "account_usage_count": 0,
                "direct_sql_count": 0,
                "session_open_count": 0,
                "elapsed_ms": 0,
                "diagnostic_leak_count": _as_int(gate.get("diagnostic_leak_count")),
                "internal_wording_leak_count": _as_int(gate.get("internal_wording_leak_count")),
                "raw_source_leak_count": _as_int(gate.get("raw_sql_leak_count")),
                "old_board_marker_count": _as_int(gate.get("old_board_marker_count")),
                "action_failure_count": _as_int(gate.get("failed_action_count") or gate.get("failure_count"))
                if key == "action_click_gate_results"
                else 0,
                "export_failure_count": _as_int(gate.get("failure_count"))
                if key == "export_download_gate_results"
                else 0,
                "passed": bool(gate.get("passed")),
                "failure_reason": "" if gate.get("passed") else "required release gate failed",
                "raw_sql_included": False,
            }
        )
    rows.extend(gate_rows)

    failures = [row for row in rows if not bool(row.get("passed"))]
    diagnostic_leak_count = sum(_as_int(row.get("diagnostic_leak_count")) for row in rows)
    internal_wording_leak_count = sum(_as_int(row.get("internal_wording_leak_count")) for row in rows)
    raw_source_leak_count = sum(_as_int(row.get("raw_source_leak_count")) for row in rows)
    duplicate_command_brief_count = sum(
        max(0, _as_int(row.get("command_brief_count")) - 1)
        for row in rows
        if row.get("area") == "primary_overview"
    )
    credential_row = next((row for row in rows if row.get("area") == "security_credential"), {})
    first_paint_failure_count = sum(
        1
        for row in rows
        if row.get("section") in PRIMARY_SECTIONS
        and (
            bool(row.get("missing_first_paint_row"))
            or _as_int(row.get("producer_provenance_failure_count"))
            or _as_int(row.get("first_paint_query_count")) > 1
            or _as_int(row.get("warm_query_count"))
            or _as_int(row.get("evidence_query_count"))
            or _as_int(row.get("account_usage_count"))
            or _as_int(row.get("detail_query_count"))
            or _as_int(row.get("cost_workbench_query_count"))
            or _as_int(row.get("query_search_query_count"))
            or _as_int(row.get("direct_sql_count"))
        )
    )
    results = {
        "source": "full_app_release_sweep_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "surface_count": len(rows),
        "required_surface_count": len(REQUIRED_RELEASE_SURFACES),
        "diagnostic_leak_count": diagnostic_leak_count,
        "internal_wording_leak_count": internal_wording_leak_count,
        "raw_source_leak_count": raw_source_leak_count,
        "failed_action_count": sum(_as_int(row.get("action_failure_count")) for row in rows),
        "export_failure_count": sum(_as_int(row.get("export_failure_count")) for row in rows),
        "settings_failure_count": _as_int(_gate(payloads, "settings_live_feature_gate_results").get("settings_failure_count")),
        "live_feature_failure_count": _as_int(_gate(payloads, "settings_live_feature_gate_results").get("live_feature_failure_count")),
        "stress_failure_count": _as_int(_gate(payloads, "user_stress_gate_results").get("failure_count")),
        "sql_cleanup_failure_count": _as_int(_gate(payloads, "sql_cleanup_gate_results").get("failure_count")),
        "first_paint_failure_count": first_paint_failure_count,
        "missing_first_paint_row_count": sum(1 for row in rows if bool(row.get("missing_first_paint_row"))),
        "missing_render_surface_count": sum(1 for row in rows if not row.get("rendered")),
        "producer_provenance_failure_count": sum(_as_int(row.get("producer_provenance_failure_count")) for row in rows),
        "synthetic_render_count": sum(1 for row in rows if bool(row.get("synthetic_render_used"))),
        "duplicate_command_brief_count": duplicate_command_brief_count,
        "old_board_marker_count": sum(_as_int(row.get("old_board_marker_count")) for row in rows),
        "credential_tile_rendered": bool(_gate(payloads, "security_credential_render_gate_results").get("passed")),
        "credential_evidence_rendered": bool(credential_row.get("rendered")),
        "credential_action_clicked": bool(credential_row.get("clicked")),
        "credential_export_file_validated": bool(credential_row.get("exported")) and bool(credential_row.get("passed")),
        "credential_case_payload_validated": bool(credential_row.get("exported")) and bool(credential_row.get("passed")),
        "credential_live_validation_status": str(
            _gate(payloads, "security_credential_expiration_live_gate_results").get("live_validation_status") or ""
        ),
        "cortex_efficiency_rendered": bool(_gate(payloads, "cortex_token_efficiency_gate_results").get("passed")),
        "user_id_daily_leak_count": _as_int(_gate(payloads, "user_display_surface_gate_results").get("user_id_daily_leak_count")),
        "credential_id_daily_leak_count": _as_int(_gate(payloads, "security_credential_export_gate_results").get("credential_export_leak_count")),
        "rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }
    failure_payload = {
        "source": "full_app_release_failures",
        "generated_at": results["generated_at"],
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }
    return results, failure_payload


def evaluate_full_app_release_sweep_gate(payload: object) -> dict[str, Any]:
    results = _as_mapping(payload)
    failures = _as_list(results.get("failures"))
    if not bool(results.get("passed", False)) and not failures:
        failures = [{"code": "FULL_APP_RELEASE_SWEEP_FAILED"}]
    return {
        "source": "full_app_release_sweep_gate_results",
        "generated_at": _now(),
        "passed": bool(results.get("passed", False)) and not failures,
        "failure_count": len(failures),
        "diagnostic_leak_count": _as_int(results.get("diagnostic_leak_count")),
        "internal_wording_leak_count": _as_int(results.get("internal_wording_leak_count")),
        "raw_source_leak_count": _as_int(results.get("raw_source_leak_count")),
        "failed_action_count": _as_int(results.get("failed_action_count")),
        "export_failure_count": _as_int(results.get("export_failure_count")),
        "settings_failure_count": _as_int(results.get("settings_failure_count")),
        "live_feature_failure_count": _as_int(results.get("live_feature_failure_count")),
        "stress_failure_count": _as_int(results.get("stress_failure_count")),
        "sql_cleanup_failure_count": _as_int(results.get("sql_cleanup_failure_count")),
        "first_paint_failure_count": _as_int(results.get("first_paint_failure_count")),
        "missing_first_paint_row_count": _as_int(results.get("missing_first_paint_row_count")),
        "missing_render_surface_count": _as_int(results.get("missing_render_surface_count")),
        "producer_provenance_failure_count": _as_int(results.get("producer_provenance_failure_count")),
        "synthetic_render_count": _as_int(results.get("synthetic_render_count")),
        "duplicate_command_brief_count": _as_int(results.get("duplicate_command_brief_count")),
        "old_board_marker_count": _as_int(results.get("old_board_marker_count")),
        "credential_tile_rendered": bool(results.get("credential_tile_rendered")),
        "credential_evidence_rendered": bool(results.get("credential_evidence_rendered")),
        "credential_action_clicked": bool(results.get("credential_action_clicked")),
        "credential_export_file_validated": bool(results.get("credential_export_file_validated")),
        "credential_case_payload_validated": bool(results.get("credential_case_payload_validated")),
        "credential_live_validation_status": str(results.get("credential_live_validation_status") or ""),
        "cortex_efficiency_rendered": bool(results.get("cortex_efficiency_rendered")),
        "user_id_daily_leak_count": _as_int(results.get("user_id_daily_leak_count")),
        "credential_id_daily_leak_count": _as_int(results.get("credential_id_daily_leak_count")),
        "failures": failures,
        "raw_sql_included": False,
    }


def write_full_app_release_sweep_artifacts(
    root: Path | str = ".",
    payloads: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payloads is None:
        payloads = _load_payloads(
            root_path,
            (
                "artifacts/full_app_validation/view_results.json",
                "artifacts/full_app_validation/rendered_fragments.json",
                "artifacts/full_app_validation/query_search_results.json",
                "artifacts/full_app_validation/first_paint_performance_results.json",
                "artifacts/full_app_validation/action_click_results.json",
                "artifacts/full_app_validation/button_click_results.json",
                "artifacts/full_app_validation/export_results.json",
                "artifacts/full_app_validation/download_results.json",
                "artifacts/full_app_validation/case_payload_results.json",
                "artifacts/full_app_validation/stress_results.json",
                "artifacts/full_app_validation/user_stress_results.json",
                "artifacts/full_app_validation/runtime_artifact_provenance_results.json",
                "artifacts/launch_readiness/runtime_artifact_provenance_gate_results.json",
                "artifacts/launch_readiness/action_click_gate_results.json",
                "artifacts/launch_readiness/export_download_gate_results.json",
                "artifacts/launch_readiness/settings_live_feature_gate_results.json",
                "artifacts/launch_readiness/performance_budget_gate_results.json",
                "artifacts/launch_readiness/user_stress_gate_results.json",
                "artifacts/launch_readiness/sql_cleanup_gate_results.json",
                "artifacts/launch_readiness/delete_first_cleanup_gate_results.json",
                "artifacts/launch_readiness/rendered_ui_leak_gate_results.json",
                "artifacts/launch_readiness/security_credential_render_gate_results.json",
                "artifacts/launch_readiness/security_credential_evidence_gate_results.json",
                "artifacts/launch_readiness/security_credential_expiration_live_gate_results.json",
                "artifacts/launch_readiness/security_credential_export_gate_results.json",
                "artifacts/launch_readiness/user_display_surface_gate_results.json",
                "artifacts/launch_readiness/cortex_token_efficiency_gate_results.json",
            ),
        )
    results, failures = build_full_app_release_sweep(payloads, root=root_path)
    gate = evaluate_full_app_release_sweep_gate(results)
    artifacts = {
        FULL_APP_RELEASE_SWEEP_RESULTS_REL: results,
        FULL_APP_RELEASE_FAILURES_REL: failures,
        FULL_APP_RELEASE_SWEEP_GATE_REL: gate,
    }
    for rel, payload in artifacts.items():
        _write_json(root_path / rel, payload)
    return artifacts


__all__ = [
    "FULL_APP_RELEASE_FAILURES_REL",
    "FULL_APP_RELEASE_SWEEP_GATE_REL",
    "FULL_APP_RELEASE_SWEEP_RESULTS_REL",
    "REQUIRED_RELEASE_SURFACES",
    "build_full_app_release_sweep",
    "evaluate_full_app_release_sweep_gate",
    "write_full_app_release_sweep_artifacts",
]


if __name__ == "__main__":
    write_full_app_release_sweep_artifacts()
