"""Export, download, and case-payload launch proof."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from tools.contracts.full_app_launch_gauntlet import (
    DOWNLOAD_RESULTS_REL,
    EXPORT_DOWNLOAD_GATE_REL,
    build_download_results,
)


FULL_APP_VALIDATION_DIR = "artifacts/full_app_validation"
CASE_PAYLOAD_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/case_payload_results.json"
EXPORT_RESULTS_REL = f"{FULL_APP_VALIDATION_DIR}/export_results.json"
FORBIDDEN_DEFAULT_EXPORT_COLUMNS = {
    "USER_ID",
    "RAW_USER_ID",
    "CREDENTIAL_ID",
    "QUERY_TEXT",
    "RAW_SQL",
    "SOURCE_OBJECT",
    "PROCEDURE_NAME",
}
FORBIDDEN_DEFAULT_EXPORT_TOKENS = (
    "ACCOUNT_USAGE",
    "SNOWFLAKE.ACCOUNT_USAGE",
    "ACCOUNT_USAGE.CREDENTIALS",
    "INFORMATION_SCHEMA",
    "MART_",
    "FACT_",
    "SP_",
    "CALL SP_",
    "CREATE OR REPLACE",
    "SELECT *",
    "CREDENTIAL_ID",
    "USER_ID",
    "RAW_USER_ID",
    "query_text",
    "raw SQL",
    "procedure name",
    "Traceback",
    "StreamlitAPIException",
    "SnowflakeSQLException",
    "fixture",
    "mock",
    "proof",
    "internal test",
    "diagnostic card",
)

CORTEX_EFFICIENCY_EXPORT_FIELDS = {
    "TOTAL_TOKENS",
    "TOTAL_REQUESTS",
    "COST_USD",
    "TOTAL_CREDITS",
    "TOKENS_PER_REQUEST",
    "TOKENS_PER_DOLLAR",
    "COST_PER_1K_TOKENS_USD",
    "AI_CREDITS_PER_1K_TOKENS",
}
CREDENTIAL_EXPORT_FIELDS = {"User", "Credential", "Type", "Status", "Recommended action"}
CASE_REQUIRED_FIELDS = {
    "section",
    "workflow",
    "scope",
    "target",
    "freshness",
    "summary",
    "row_count",
    "visible_row_count",
    "recommended_action",
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_json(root: Path, rel: str) -> Any:
    path = root / rel
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _rows_from_payload(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        for key in ("rows", "exports", "cases", "results"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, Mapping)]
    return []


def _as_int(value: object) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, (int, float, str, bytes, bytearray)):
            return int(float(value))
    except (TypeError, ValueError):
        return 0
    return 0


def _resolve_payload_path(root: Path, payload_file: object) -> Path:
    raw = Path(str(payload_file or ""))
    return raw if raw.is_absolute() else root / raw


def _contains_forbidden(text: str) -> list[str]:
    upper_text = text.upper()
    lower_text = text.lower()
    hits: list[str] = []
    for token in FORBIDDEN_DEFAULT_EXPORT_TOKENS:
        if token.isupper() or "_" in token:
            if token.upper() in upper_text:
                hits.append(token)
        elif token.lower() in lower_text:
            hits.append(token)
    return sorted(set(hits))


def _csv_payload(text: str) -> tuple[list[str], list[dict[str, str]], str]:
    try:
        reader = csv.DictReader(text.splitlines())
        return list(reader.fieldnames or []), list(reader), ""
    except csv.Error as exc:
        return [], [], f"csv parse failed: {exc}"


def _json_payload(text: str) -> tuple[object, int, str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, 0, f"json parse failed: {exc}"
    if isinstance(payload, list):
        return payload, len(payload), ""
    if isinstance(payload, Mapping):
        return payload, _as_int(payload.get("visible_row_count") or payload.get("row_count") or 1), ""
    return payload, 1, ""


def _domain_from_row(row: Mapping[str, Any]) -> str:
    section = str(row.get("section") or "").lower()
    workflow = str(row.get("workflow") or "").lower()
    source_family = str(row.get("source_family") or row.get("source") or "").lower()
    filename = str(row.get("filename") or row.get("payload_file") or "").lower()
    text = " ".join((section, workflow, source_family, filename))
    if "credential" in text:
        return "security_credential"
    if "token_efficiency" in text or source_family == "cortex_token_efficiency" or section == "cortex efficiency":
        return "cortex_efficiency"
    if section == "alert center":
        return "alert"
    if "query" in text:
        return "query_search"
    if "cost" in text:
        return "cost"
    if "alert" in text:
        return "alert"
    if "workload" in text:
        return "workload"
    if "dba" in text:
        return "dba"
    if "executive" in text:
        return "executive"
    return "generic"


def _schema_failures(row: Mapping[str, Any], columns: set[str], text: str, *, payload_kind: str) -> list[str]:
    reasons: list[str] = []
    domain = _domain_from_row(row)
    if payload_kind == "export":
        if domain == "security_credential":
            missing = sorted(CREDENTIAL_EXPORT_FIELDS - columns)
            if missing:
                reasons.append(f"security credential export missing required columns: {', '.join(missing)}")
            if "Expires" not in columns and "Days left" not in columns:
                reasons.append("security credential export missing Expires or Days left")
        elif domain == "cortex_efficiency":
            label_present = bool({"USER_DISPLAY_NAME", "USER_CHART_LABEL"} & columns)
            missing = sorted(CORTEX_EFFICIENCY_EXPORT_FIELDS - columns)
            if not label_present:
                reasons.append("cortex efficiency export missing USER_DISPLAY_NAME or USER_CHART_LABEL")
            if missing:
                reasons.append(f"cortex efficiency export missing required columns: {', '.join(missing)}")
        elif domain == "query_search" and "query_text" in {column.lower() for column in columns}:
            reasons.append("query search default export includes query_text")
        elif domain == "cost":
            if "BILLING_BRIDGE_STATUS" not in columns:
                reasons.append("cost export missing BILLING_BRIDGE_STATUS")
            if not ({"ACCOUNT_BILLED_COST_USD", "SPEND_USD", "COST_USD"} & columns):
                reasons.append("cost export missing billed spend/cost field")
    if payload_kind == "case":
        payload, _count, error = _json_payload(text)
        if error:
            reasons.append(error)
        elif isinstance(payload, Mapping):
            source_present = bool(payload.get("source") or payload.get("source_family"))
            missing = sorted(field for field in CASE_REQUIRED_FIELDS if not payload.get(field))
            if not source_present:
                missing.append("source/source_family")
            if missing:
                reasons.append(f"case payload missing required fields: {', '.join(missing)}")
            if domain == "security_credential":
                credential_missing = [
                    field
                    for field in ("expired_count", "expiring_30d_count", "next_expiration", "owner_labels")
                    if field not in payload
                ]
                if credential_missing:
                    reasons.append(f"credential case payload missing fields: {', '.join(credential_missing)}")
            if domain == "cortex_efficiency":
                cortex_missing = [
                    field for field in ("total_tokens", "tokens_per_dollar", "cost_per_1k_tokens_usd") if field not in payload
                ]
                if cortex_missing:
                    reasons.append(f"cortex efficiency case payload missing fields: {', '.join(cortex_missing)}")
    if not bool(row.get("admin_only")):
        leaked_columns = sorted(column for column in columns if column.upper() in FORBIDDEN_DEFAULT_EXPORT_COLUMNS)
        if leaked_columns:
            reasons.append(f"default payload leaks forbidden columns: {', '.join(leaked_columns)}")
        leaked_tokens = _contains_forbidden(text)
        if leaked_tokens:
            reasons.append(f"default payload contains forbidden token: {', '.join(leaked_tokens[:5])}")
    return reasons


def _file_payload_failures(row: Mapping[str, Any], *, root: Path, payload_kind: str) -> tuple[list[dict[str, Any]], int]:
    reasons: list[dict[str, Any]] = []
    payload_file = str(row.get("payload_file") or row.get("artifact_path") or "")
    if not payload_file:
        if payload_kind == "case" and not row.get("payload_file"):
            reasons.append({"code": "PAYLOAD_FILE_MISSING", "section": row.get("section"), "payload_kind": payload_kind})
        return reasons, _as_int(row.get("parsed_row_count") or row.get("row_count"))
    path = _resolve_payload_path(root, payload_file)
    if not path.exists():
        return ([{"code": "PAYLOAD_FILE_MISSING", "section": row.get("section"), "payload_file": payload_file}], 0)
    payload = path.read_bytes()
    text = payload.decode("utf-8", errors="ignore")
    expected_sha = str(row.get("sha256") or row.get("payload_hash") or "")
    if expected_sha and hashlib.sha256(payload).hexdigest() != expected_sha:
        reasons.append({"code": "PAYLOAD_HASH_MISMATCH", "section": row.get("section"), "payload_file": payload_file})
    expected_size = _as_int(row.get("size_bytes") or row.get("content_length"))
    if expected_size and expected_size != len(payload):
        reasons.append({"code": "PAYLOAD_SIZE_MISMATCH", "section": row.get("section"), "payload_file": payload_file})
    if len(payload) <= 0 and not bool(row.get("intentional_empty")):
        reasons.append({"code": "PAYLOAD_EMPTY", "section": row.get("section"), "payload_file": payload_file})
    content_type = str(row.get("content_type") or row.get("mime") or "")
    if not content_type:
        reasons.append({"code": "PAYLOAD_CONTENT_TYPE_MISSING", "section": row.get("section"), "payload_file": payload_file})
    parsed_count = 0
    columns: set[str] = set()
    suffix = path.suffix.lower()
    if "json" in content_type.lower() or suffix == ".json":
        payload_obj, parsed_count, error = _json_payload(text)
        if error:
            reasons.append({"code": "PAYLOAD_PARSE_FAILED", "section": row.get("section"), "failure_reason": error})
        if isinstance(payload_obj, Mapping):
            columns = set(str(key) for key in payload_obj.keys())
    elif "csv" in content_type.lower() or suffix == ".csv":
        fieldnames, parsed_rows, error = _csv_payload(text)
        columns = set(fieldnames)
        parsed_count = len(parsed_rows)
        if error:
            reasons.append({"code": "PAYLOAD_PARSE_FAILED", "section": row.get("section"), "failure_reason": error})
    elif not row.get("payload_kind"):
        reasons.append({"code": "PAYLOAD_KIND_UNDECLARED", "section": row.get("section"), "payload_file": payload_file})
        parsed_count = _as_int(row.get("parsed_row_count") or row.get("row_count"))
    else:
        parsed_count = _as_int(row.get("parsed_row_count") or row.get("row_count"))
    visible_count = _as_int(row.get("visible_row_count") or row.get("row_count"))
    metadata_count = _as_int(row.get("parsed_row_count") or row.get("payload_row_count") or row.get("row_count"))
    if metadata_count and parsed_count != metadata_count:
        reasons.append({"code": "PAYLOAD_METADATA_ROW_COUNT_MISMATCH", "section": row.get("section"), "parsed_row_count": parsed_count, "metadata_row_count": metadata_count})
    if visible_count and parsed_count != visible_count:
        reasons.append({"code": "PAYLOAD_VISIBLE_ROW_COUNT_MISMATCH", "section": row.get("section"), "parsed_row_count": parsed_count, "visible_row_count": visible_count})
    for reason in _schema_failures(row, columns, text, payload_kind=payload_kind):
        reasons.append({"code": "PAYLOAD_SCHEMA_OR_LEAK_FAILURE", "section": row.get("section"), "failure_reason": reason})
    if bool(row.get("raw_sql_included")):
        reasons.append({"code": "RAW_SQL_INCLUDED", "section": row.get("section")})
    return reasons, parsed_count


def evaluate_export_download_gate(
    export_payload: object,
    download_payload: object,
    case_rows: object,
    root: Path | str = ".",
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    root_path = Path(root).resolve()
    export_summary = _as_mapping(export_payload)
    export_rows = _rows_from_payload(export_payload)
    download_summary = _as_mapping(download_payload)
    case_payload_rows = _rows_from_payload(case_rows)
    if export_rows and not export_summary:
        export_summary = {
            "passed": all(bool(_as_mapping(row).get("passed", True)) for row in export_rows),
            "export_count": len(export_rows),
            "failure_count": sum(1 for row in export_rows if not bool(_as_mapping(row).get("passed", True))),
        }
    parsed_export_count = 0
    parsed_case_count = 0
    for row in export_rows:
        if not isinstance(row, Mapping):
            continue
        row_failures, parsed_rows = _file_payload_failures(row, root=root_path, payload_kind="export")
        parsed_export_count += parsed_rows
        failures.extend(row_failures)
    for artifact, payload in ((EXPORT_RESULTS_REL, export_summary), (DOWNLOAD_RESULTS_REL, download_summary)):
        if not bool(payload.get("passed", True)):
            failures.append(
                {
                    "code": "EXPORT_DOWNLOAD_ARTIFACT_FAILED",
                    "artifact": artifact,
                    "failure_count": int(payload.get("failure_count") or 1),
                }
            )
    for row in case_payload_rows:
        if not isinstance(row, Mapping):
            continue
        row_file_failures, parsed_rows = _file_payload_failures(row, root=root_path, payload_kind="case")
        parsed_case_count += parsed_rows
        failures.extend(row_file_failures)
        missing = [
            field
            for field in ("section", "workflow", "scope", "target", "freshness", "summary", "row_count")
            if not row.get(field)
        ]
        if not (row.get("source") or row.get("source_family")):
            missing.append("source/source_family")
        if missing or not bool(row.get("passed", True)):
            failures.append(
                {
                    "code": "CASE_PAYLOAD_FAILED",
                    "section": row.get("section"),
                    "missing_fields": missing,
                }
            )
    return {
        "source": "export_download_gate_results",
        "generated_at": _now(),
        "passed": not failures,
        "failure_count": len(failures),
        "export_count": int(export_summary.get("export_count") or len(export_rows)),
        "download_count": int(download_summary.get("download_count") or 0),
        "case_payload_count": len(case_payload_rows),
        "parsed_export_row_count": parsed_export_count,
        "parsed_case_row_count": parsed_case_count,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_export_download_artifacts(root: Path | str = ".", payloads: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if payloads is None:
        payloads = {
            EXPORT_RESULTS_REL: _load_json(root_path, EXPORT_RESULTS_REL),
            CASE_PAYLOAD_RESULTS_REL: _load_json(root_path, CASE_PAYLOAD_RESULTS_REL),
        }
    download_payload = build_download_results(payloads, root_path)
    _write_json(root_path / DOWNLOAD_RESULTS_REL, download_payload)
    return {DOWNLOAD_RESULTS_REL: download_payload}


__all__ = [
    "CASE_PAYLOAD_RESULTS_REL",
    "DOWNLOAD_RESULTS_REL",
    "EXPORT_DOWNLOAD_GATE_REL",
    "EXPORT_RESULTS_REL",
    "evaluate_export_download_gate",
    "write_export_download_artifacts",
]
