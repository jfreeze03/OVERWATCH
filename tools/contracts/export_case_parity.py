"""File-backed export/case parity gate.

This gate parses every runtime export/download/case payload from disk and
reconciles actual file contents against the runtime metadata. It intentionally
does not trust producer row-count metadata as proof.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping


FULL_APP_DIR = "artifacts/full_app_validation"
LAUNCH_READINESS_DIR = "artifacts/launch_readiness"

EXPORT_CASE_PARITY_RESULTS_REL = f"{FULL_APP_DIR}/export_case_parity_results.json"
EXPORT_CASE_PARITY_GATE_REL = f"{LAUNCH_READINESS_DIR}/export_case_parity_gate_results.json"

EXPORT_RESULTS_REL = f"{FULL_APP_DIR}/export_results.json"
DOWNLOAD_RESULTS_REL = f"{FULL_APP_DIR}/download_results.json"
CASE_PAYLOAD_RESULTS_REL = f"{FULL_APP_DIR}/case_payload_results.json"

PRODUCER = "export_case_parity"

FORBIDDEN_DEFAULT_COLUMNS = {
    "USER_ID",
    "RAW_USER_ID",
    "CREDENTIAL_ID",
    "QUERY_TEXT",
    "RAW_SQL",
    "SOURCE_OBJECT",
    "PROCEDURE_NAME",
}
FORBIDDEN_DEFAULT_TOKENS = (
    "SNOWFLAKE.ACCOUNT_USAGE.CREDENTIALS",
    "ACCOUNT_USAGE.CREDENTIALS",
    "ACCOUNT_USAGE",
    "INFORMATION_SCHEMA",
    "CREATE OR REPLACE",
    "SELECT *",
    "CALL SP_",
    "CREDENTIAL_ID",
    "RAW_USER_ID",
    "USER_ID",
    "token_file_path",
    "--token-file-path",
    "overwatch_snowflake_validation_",
    "Traceback",
    "StreamlitAPIException",
    "SnowflakeSQLException",
)
CORTEX_FIELDS = {
    "TOTAL_TOKENS",
    "TOTAL_REQUESTS",
    "COST_USD",
    "TOTAL_CREDITS",
    "TOKENS_PER_REQUEST",
    "TOKENS_PER_DOLLAR",
    "COST_PER_1K_TOKENS_USD",
    "AI_CREDITS_PER_1K_TOKENS",
}
CREDENTIAL_FIELDS = {"User", "Credential", "Type", "Status", "Recommended action"}
CASE_FIELDS = {
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


def _row_signature(row_id: str, commit_sha: str) -> str:
    return hashlib.sha256(f"{PRODUCER}|{row_id}|{commit_sha}".encode("utf-8")).hexdigest()


def _load_json(root: Path, rel: str) -> Any:
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("rows", "exports", "downloads", "cases", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    return []


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value or 0)))
    except (TypeError, ValueError):
        return 0


def _resolve(root: Path, payload_file: Any) -> Path:
    path = Path(str(payload_file or ""))
    return path if path.is_absolute() else root / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contains_forbidden(text: str) -> list[str]:
    upper = text.upper()
    hits = sorted({token for token in FORBIDDEN_DEFAULT_TOKENS if token.upper() in upper})
    path_patterns = {
        "token file path": r"(?i)([A-Za-z]:\\|/)[^\"'\r\n,]*token[^\"'\r\n,]*",
        "temp SQL path": r"(?i)([A-Za-z]:\\|/)[^\"'\r\n,]*overwatch_snowflake_validation_[^\"'\r\n,]*\.sql",
    }
    for label, pattern in path_patterns.items():
        if re.search(pattern, text):
            hits.append(label)
    return sorted(set(hits))


def _domain(row: Mapping[str, Any]) -> str:
    text = " ".join(
        str(row.get(key) or "").lower()
        for key in ("section", "workflow", "source", "source_family", "filename", "payload_file")
    )
    if "credential" in text:
        return "security_credential"
    if "token_efficiency" in text or "cortex efficiency" in text:
        return "cortex_efficiency"
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


def _parse_payload(path: Path, content_type: str) -> tuple[str, int, set[str], object, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    kind = "json" if "json" in content_type.lower() or path.suffix.lower() == ".json" else "csv"
    if kind == "json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return kind, 0, set(), {}, f"json parse failed: {exc.msg}"
        if isinstance(payload, list):
            columns: set[str] = set()
            for item in payload:
                if isinstance(item, Mapping):
                    columns.update(str(key) for key in item.keys())
            return kind, len(payload), columns, payload, ""
        if isinstance(payload, Mapping):
            count = _as_int(payload.get("visible_row_count") or payload.get("row_count") or 1)
            return kind, count, {str(key) for key in payload.keys()}, payload, ""
        return kind, 1, set(), payload, ""
    try:
        reader = csv.DictReader(text.splitlines())
        rows = list(reader)
    except csv.Error as exc:
        return kind, 0, set(), [], f"csv parse failed: {exc}"
    return kind, len(rows), set(reader.fieldnames or []), rows, ""


def _schema_reasons(row: Mapping[str, Any], domain: str, columns: set[str], payload: object, kind: str) -> list[str]:
    reasons: list[str] = []
    if not bool(row.get("admin_only")):
        leaked = sorted(column for column in columns if column.upper() in FORBIDDEN_DEFAULT_COLUMNS)
        if leaked:
            reasons.append(f"default payload leaks forbidden columns: {', '.join(leaked)}")
    if kind == "csv":
        if domain == "security_credential":
            missing = sorted(CREDENTIAL_FIELDS - columns)
            if missing:
                reasons.append(f"security credential export missing required columns: {', '.join(missing)}")
            if "Expires" not in columns and "Days left" not in columns:
                reasons.append("security credential export missing Expires or Days left")
        elif domain == "cortex_efficiency":
            if not ({"USER_DISPLAY_NAME", "USER_CHART_LABEL"} & columns):
                reasons.append("cortex efficiency export missing user display label")
            missing = sorted(CORTEX_FIELDS - columns)
            if missing:
                reasons.append(f"cortex efficiency export missing required columns: {', '.join(missing)}")
        elif domain == "cost":
            if not ({"ACCOUNT_BILLED_COST_USD", "SPEND_USD", "COST_USD"} & columns):
                reasons.append("cost export missing spend/cost field")
            if not any("BRIDGE" in column.upper() or "STATUS" in column.upper() for column in columns):
                reasons.append("cost export missing billing bridge/status field")
        elif domain == "query_search" and "query_text" in {column.lower() for column in columns}:
            reasons.append("query search default export includes query_text")
    if kind == "json" and isinstance(payload, Mapping):
        missing = sorted(field for field in CASE_FIELDS if not payload.get(field))
        source_present = bool(payload.get("source") or payload.get("source_family"))
        if not source_present:
            missing.append("source/source_family")
        if missing:
            reasons.append(f"case payload missing required fields: {', '.join(missing)}")
        if domain == "security_credential":
            for field in ("expired_count", "expiring_30d_count", "next_expiration", "owner_labels"):
                if field not in payload:
                    reasons.append(f"credential case payload missing {field}")
        if domain == "cortex_efficiency":
            for field in ("total_tokens", "tokens_per_dollar", "cost_per_1k_tokens_usd"):
                if field not in payload:
                    reasons.append(f"cortex efficiency case payload missing {field}")
    return reasons


def _validate_row(root: Path, row: Mapping[str, Any], *, rel: str, index: int, commit_sha: str, payload_kind: str) -> dict[str, Any]:
    row_id = str(row.get("id") or row.get("row_id") or row.get("stable_key") or row.get("filename") or f"{Path(rel).stem}[{index}]")
    payload_file = _resolve(root, row.get("payload_file"))
    reasons: list[str] = []
    exists = payload_file.exists() and payload_file.is_file()
    content_type = str(row.get("content_type") or "")
    actual_sha = ""
    actual_size = 0
    parsed_count = 0
    columns: set[str] = set()
    domain = _domain(row)
    forbidden_hits: list[str] = []
    parse_kind = ""
    if not exists:
        reasons.append("payload_file missing")
        parsed_payload: object = {}
    else:
        actual_sha = _sha256(payload_file)
        actual_size = payload_file.stat().st_size
        text = payload_file.read_text(encoding="utf-8", errors="replace")
        forbidden_hits = _contains_forbidden(text)
        parse_kind, parsed_count, columns, parsed_payload, parse_error = _parse_payload(payload_file, content_type)
        if parse_error:
            reasons.append(parse_error)
        reasons.extend(_schema_reasons(row, domain, columns, parsed_payload, parse_kind))
    if str(row.get("commit_sha") or "") != commit_sha:
        reasons.append("commit_sha mismatch")
    if str(row.get("sha256") or row.get("actual_sha256") or "") and str(row.get("sha256") or row.get("actual_sha256")) != actual_sha:
        reasons.append("sha256 mismatch")
    if _as_int(row.get("size_bytes")) and _as_int(row.get("size_bytes")) != actual_size:
        reasons.append("size_bytes mismatch")
    expected_visible = _as_int(row.get("visible_row_count"))
    if expected_visible != parsed_count:
        reasons.append(f"visible_row_count mismatch: expected {expected_visible}, parsed {parsed_count}")
    if _as_int(row.get("parsed_row_count")) and _as_int(row.get("parsed_row_count")) != parsed_count:
        reasons.append(f"parsed_row_count metadata mismatch: expected {_as_int(row.get('parsed_row_count'))}, parsed {parsed_count}")
    if bool(row.get("raw_sql_included")):
        reasons.append("raw_sql_included=true")
    if not str(row.get("producer") or ""):
        reasons.append("missing producer")
    if not str(row.get("producer_signature") or ""):
        reasons.append("missing producer_signature")
    if not bool(row.get("passed", True)):
        reasons.append(str(row.get("failure_reason") or "source row failed"))
    if forbidden_hits and not bool(row.get("admin_only")):
        reasons.append(f"forbidden token(s) in default payload: {', '.join(forbidden_hits[:5])}")
    if payload_kind in {"export", "case"}:
        if not str(row.get("rendered_action_id") or row.get("rendered_row_id") or ""):
            reasons.append("missing rendered action linkage")
        if not str(row.get("clicked_action_id") or row.get("action_row_id") or ""):
            reasons.append("missing click/action linkage")
    return {
        "row_id": row_id,
        "payload_kind": payload_kind,
        "source_artifact": rel,
        "payload_file": str(row.get("payload_file") or ""),
        "payload_exists": exists,
        "content_type": content_type,
        "domain": domain,
        "actual_sha256": actual_sha,
        "expected_sha256": str(row.get("sha256") or row.get("actual_sha256") or ""),
        "actual_size_bytes": actual_size,
        "expected_size_bytes": _as_int(row.get("size_bytes")),
        "parsed_row_count": parsed_count,
        "visible_row_count": expected_visible,
        "columns": sorted(columns),
        "forbidden_token_count": len(forbidden_hits),
        "forbidden_tokens": forbidden_hits,
        "section": str(row.get("section") or ""),
        "workflow": str(row.get("workflow") or ""),
        "producer": PRODUCER,
        "producer_signature": _row_signature(row_id, commit_sha),
        "provenance_origin": "producer",
        "commit_sha": commit_sha,
        "passed": not reasons,
        "failure_reason": "; ".join(dict.fromkeys(reason for reason in reasons if reason)),
        "raw_sql_included": False,
    }


def build_export_case_parity_results(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    commit_sha = _git_commit(root_path)
    source_sets = (
        (EXPORT_RESULTS_REL, "export"),
        (DOWNLOAD_RESULTS_REL, "download"),
        (CASE_PAYLOAD_RESULTS_REL, "case"),
    )
    rows: list[dict[str, Any]] = []
    for rel, payload_kind in source_sets:
        source_rows = _rows(_load_json(root_path, rel))
        if not source_rows:
            rows.append(
                {
                    "row_id": f"{payload_kind}::missing_rows",
                    "payload_kind": payload_kind,
                    "source_artifact": rel,
                    "producer": PRODUCER,
                    "producer_signature": _row_signature(f"{payload_kind}::missing_rows", commit_sha),
                    "provenance_origin": "producer",
                    "commit_sha": commit_sha,
                    "passed": False,
                    "failure_reason": f"missing {payload_kind} runtime rows",
                    "raw_sql_included": False,
                }
            )
            continue
        rows.extend(
            _validate_row(root_path, row, rel=rel, index=index, commit_sha=commit_sha, payload_kind=payload_kind)
            for index, row in enumerate(source_rows)
        )
    failures = [row for row in rows if not bool(row.get("passed"))]
    signature = _producer_signature()
    return {
        "source": "export_case_parity_results",
        "gate": "export_case_parity",
        "producer": PRODUCER,
        "producer_signature": signature,
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": commit_sha,
        "passed": not failures,
        "failure_count": len(failures),
        "row_count": len(rows),
        "export_parse_failure_count": sum(1 for row in failures if row.get("payload_kind") == "export"),
        "case_parse_failure_count": sum(1 for row in failures if row.get("payload_kind") == "case"),
        "download_parse_failure_count": sum(1 for row in failures if row.get("payload_kind") == "download"),
        "forbidden_token_count": sum(_as_int(row.get("forbidden_token_count")) for row in rows),
        "rows": rows,
        "proof_rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def build_export_case_parity_gate(results: Mapping[str, Any]) -> dict[str, Any]:
    rows = [dict(row) for row in _rows(results)]
    failures = [row for row in rows if not bool(row.get("passed"))]
    signature = _producer_signature()
    return {
        "source": "export_case_parity_gate_results",
        "gate": "export_case_parity",
        "producer": PRODUCER,
        "producer_signature": signature,
        "provenance_origin": "producer",
        "generated_at": _now(),
        "commit_sha": str(results.get("commit_sha") or ""),
        "passed": bool(results.get("passed")) and not failures,
        "failure_count": len(failures),
        "row_count": _as_int(results.get("row_count")),
        "export_parse_failure_count": _as_int(results.get("export_parse_failure_count")),
        "case_parse_failure_count": _as_int(results.get("case_parse_failure_count")),
        "download_parse_failure_count": _as_int(results.get("download_parse_failure_count")),
        "forbidden_token_count": _as_int(results.get("forbidden_token_count")),
        "rows": rows,
        "proof_rows": rows,
        "failures": failures,
        "raw_sql_included": False,
    }


def write_export_case_parity_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    results = build_export_case_parity_results(root_path)
    gate = build_export_case_parity_gate(results)
    _write_json(root_path / EXPORT_CASE_PARITY_RESULTS_REL, results)
    _write_json(root_path / EXPORT_CASE_PARITY_GATE_REL, gate)
    return {
        EXPORT_CASE_PARITY_RESULTS_REL: results,
        EXPORT_CASE_PARITY_GATE_REL: gate,
    }


def main() -> int:
    artifacts = write_export_case_parity_artifacts(Path.cwd())
    return 0 if bool(artifacts[EXPORT_CASE_PARITY_GATE_REL].get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXPORT_CASE_PARITY_GATE_REL",
    "EXPORT_CASE_PARITY_RESULTS_REL",
    "build_export_case_parity_gate",
    "build_export_case_parity_results",
    "write_export_case_parity_artifacts",
]
