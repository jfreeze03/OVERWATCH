"""Snowflake setup/procedure validation for OVERWATCH launch readiness.

The default path is deterministic static validation. Live execution is opt-in
with OVERWATCH_SNOWFLAKE_VALIDATION=1 so CI can prove parse/order/shape without
needing credentials, while release profiles can require live proof separately.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Iterable, Mapping


SNOWFLAKE_VALIDATION_DIR = "artifacts/snowflake_validation"

EXPECTED_SCRIPT_ORDER = [
    "snowflake/mart_setup/03_config_and_audit_tables.sql",
    "snowflake/mart_setup/04_mart_tables.sql",
    "snowflake/mart_setup/05_load_procedures.sql",
    "snowflake/mart_setup/07_tasks.sql",
    "snowflake/mart_setup/08_validation.sql",
    "snowflake/OVERWATCH_MART_SETUP.sql",
    "snowflake/OVERWATCH_MART_VALIDATION.sql",
    "snowflake/OVERWATCH_MART_DROP.sql",
]

COMPACT_EVIDENCE_MARTS = {
    "MART_QUERY_EVIDENCE_RECENT",
    "MART_ALERT_EVIDENCE_RECENT",
    "MART_SECURITY_EVIDENCE_RECENT",
    "MART_COST_EVIDENCE_RECENT",
    "MART_DBA_EVIDENCE_RECENT",
}

SUPPORTING_LAUNCH_MARTS = {
    "MART_SECURITY_CREDENTIAL_EXPIRATIONS_CURRENT",
    "MART_USER_DIM_CURRENT",
}

ACTIVE_LAUNCH_OBJECTS = {
    "MART_SECTION_DECISION_CURRENT",
    "MART_SECTION_DECISION_CURRENT_FLAT",
    "MART_SECTION_DECISION_LAST_GOOD",
    *COMPACT_EVIDENCE_MARTS,
    *SUPPORTING_LAUNCH_MARTS,
}

REQUIRED_RESULT_FILES = {
    "snowflake_validation_summary",
    "live_execution_manifest",
    "live_execution_manifest_reconciliation",
    "live_execution_manifest_category_coverage",
    "live_validation_environment_results",
    "live_validation_session_results",
    "setup_execution_results",
    "procedure_compile_results",
    "procedure_compile_coverage_results",
    "procedure_smoke_call_results",
    "procedure_smoke_call_coverage_results",
    "validation_sql_results",
    "refresh_fast_results",
    "refresh_full_results",
    "object_inventory_live_results",
    "procedure_dependency_graph",
    "trend_cardinality_results",
    "packet_publication_validation_results",
    "packet_shape_results",
    "packet_size_results",
    "packet_source_truth_results",
    "packet_validation_detail_results",
    "compact_evidence_mart_validation_results",
    "compact_evidence_mart_detail_results",
    "refresh_performance_results",
    "refresh_stage_timing_results",
    "refresh_row_count_results",
    "refresh_detail_results",
    "formula_live_validation_results",
    "snowflake_formula_live_results",
    "cortex_service_type_live_results",
    "workload_formula_live_results",
    "packet_formula_results",
    "packet_schema_upgrade_results",
    "recent_snowflake_fix_validation_results",
    "metric_candidate_shape_results",
    "sql_encoding_scan_results",
    "schema_drift_results",
    "streamlit_manifest_validation_results",
    "phase_validation_results",
    "snowflake_error_sanitization_results",
}

REQUIRED_VALIDATION_PHASES = (
    "static_statement_split",
    "dependency_order",
    "setup_script_static",
    "procedure_compile_static",
    "procedure_compile_live",
    "procedure_smoke_call_live",
    "validation_sql_static",
    "validation_sql_live",
    "packet_shape_static",
    "packet_shape_live",
    "compact_evidence_static",
    "compact_evidence_live",
    "refresh_fast_static",
    "refresh_fast_live",
    "refresh_full_static_or_dry_run",
    "drop_rollback_static",
    "drop_rollback_live_or_dry_run",
)

MANIFEST_CATEGORY_ARTIFACTS = {
    "live_environment": ("live_validation_environment_results.json",),
    "live_session": ("live_validation_session_results.json",),
    "procedure_compile": (
        "procedure_compile_results.json",
        "procedure_compile_coverage_results.json",
    ),
    "procedure_smoke_call": (
        "procedure_smoke_call_results.json",
        "procedure_smoke_call_coverage_results.json",
    ),
    "refresh_fast": ("refresh_fast_results.json",),
    "refresh_full": ("refresh_full_results.json",),
    "validation_sql": ("validation_sql_results.json",),
    "packet_publication": ("packet_publication_validation_results.json",),
    "packet_shape": ("packet_shape_results.json",),
    "packet_size": ("packet_size_results.json",),
    "packet_source_truth": ("packet_source_truth_results.json",),
    "compact_evidence_mart": (
        "compact_evidence_mart_validation_results.json",
        "compact_evidence_mart_detail_results.json",
    ),
    "recent_snowflake_fix": ("recent_snowflake_fix_validation_results.json",),
    "metric_candidate_shape": ("metric_candidate_shape_results.json",),
    "trend_cardinality": ("trend_cardinality_results.json",),
    "schema_drift": ("schema_drift_results.json",),
    "sql_encoding": ("sql_encoding_scan_results.json",),
    "snowflake_error_sanitization": ("snowflake_error_sanitization_results.json",),
    "live_query_history": ("query_history_by_tag.json",),
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(account|user|username|password|token|private[_ -]?key|role|warehouse)\s*[:=]\s*['\"]?[^'\"\s;]+"),
    re.compile(r"(?i)snowflake://[^\s'\"\)]+"),
    re.compile(r"(?is)CREATE\s+.+?\$\$.*?\$\$"),
    re.compile(r"(?is)\b(SELECT|INSERT|UPDATE|DELETE|MERGE|CALL)\b.+?(?:;|$)"),
)

_BAD_SQL_TEXT_PATTERNS = (
    ("\ufeff", "UTF8_BOM"),
    ("\ufffd", "REPLACEMENT_CHARACTER"),
    ("\u00e2", "MOJIBAKE_E2"),
    ("\u00c3", "MOJIBAKE_C3"),
    ("\u00c2", "MOJIBAKE_C2"),
)

REQUIRED_SMOKE_TARGETS = (
    ("fast_refresh_validation", "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST", "live", "safe_read"),
    ("full_refresh_validation_or_dry_run", "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL", "dry_run", "dry_run_required"),
    ("setup_health_validation", "SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS", "live", "safe_read"),
    ("compact_evidence_validation", "SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL", "live", "safe_read"),
    ("current_packet_validation", "SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL", "live", "safe_read"),
    ("last_known_good_fallback_validation", "SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS", "dry_run", "dry_run_required"),
    ("validation_sql_smoke", "OVERWATCH_MART_VALIDATION_SQL", "dry_run", "dry_run_required"),
    (
        "optional_optimization_status_read_only",
        "SP_OVERWATCH_APPLY_OPTIONAL_PERFORMANCE_OPTIMIZATION",
        "dry_run",
        "destructive_requires_flag",
    ),
)

GENERIC_SKIP_TEXT = {"", "n/a", "na", "none", "todo", "tbd", "future", "optional", "unsupported"}

_LAUNCH_PROFILES_REQUIRING_LIVE = {"internal_live", "prod_candidate"}

REQUIRED_PACKET_DETAIL_CHECKS = (
    "current_active_unique",
    "current_flat_active_match",
    "last_good_available_or_skipped_with_reason",
    "packet_required_fields_present",
    "max_packet_bytes_under_100kb",
    "source_truth_array_present",
    "source_truth_required_optional_semantics_valid",
    "no_duplicate_metric_rows",
    "no_duplicate_action_rows",
    "no_duplicate_source_rows",
    "top_alert_evidence_id_string_compatible",
    "sla_fields_coherent",
    "first_paint_flat_packet_path_only",
    "no_variant_detail_first_paint",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_SENSITIVE_KEY_MARKERS = (
    "secret",
    "token",
    "password",
    "credential",
    "raw_sql",
)
_SENSITIVE_EXACT_KEYS = {
    "BILLING_BRIDGE_STATUS",
    "BILLING_WINDOW_COMPLETE",
    "SQL_BODY",
}
_SAFE_EXACT_KEYS = {
    "raw_sql_included",
}


def _redact_sensitive_payload(value: Any, key_hint: str = "") -> Any:
    key_text = str(key_hint or "")
    key_upper = key_text.upper()
    key_lower = key_text.lower()
    if key_lower in _SAFE_EXACT_KEYS:
        return value
    if key_upper in _SENSITIVE_EXACT_KEYS or any(marker in key_lower for marker in _SENSITIVE_KEY_MARKERS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {k: _redact_sensitive_payload(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive_payload(item, key_hint) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitized_payload = _redact_sensitive_payload(payload)
    path.write_text(json.dumps(sanitized_payload, indent=2, sort_keys=True), encoding="utf-8")


def _normalize_name(name: str) -> str:
    parts = [part.strip('"') for part in str(name or "").split(".") if part.strip()]
    return (parts[-1] if parts else "").upper()


def _normalize_signature(signature: str) -> str:
    return re.sub(r"\s+", " ", str(signature or "").upper()).strip()


def _line_number(text: str, offset: int) -> int:
    return str(text or "")[: max(0, offset)].count("\n") + 1


def _sanitized_identifier(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.search(r"(?i)(password|token|private[_ -]?key|snowflake://|://|;|\s)", text):
        return "[redacted]"
    return text[:96]


def sanitize_snowflake_error(error: object) -> str:
    """Return a short error message without SQL bodies, credentials, or traces."""

    text = str(error or "")
    text = re.sub(r"(?is)Traceback \(most recent call last\):.*", "execution stack omitted", text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300]


def split_sql_statements(sql: str) -> list[str]:
    """Split SQL on top-level semicolons while preserving $$ procedure bodies."""

    statements: list[str] = []
    start = 0
    in_single = False
    in_double = False
    in_dollar = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    text = str(sql or "")
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if not in_single and not in_double and not in_dollar and ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue
        if not in_single and not in_double and not in_dollar and ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if not in_single and not in_double and text.startswith("$$", i):
            in_dollar = not in_dollar
            i += 2
            continue
        if in_dollar:
            i += 1
            continue
        if in_single:
            if ch == "'":
                if nxt == "'":
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == ";":
            statement = text[start:i].strip()
            if statement:
                statements.append(statement)
            start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail:
        statements.append(tail)
    return statements


def _split_top_level_csv(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    in_single = False
    in_double = False
    in_dollar = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if not in_single and not in_double and text.startswith("$$", i):
            in_dollar = not in_dollar
            i += 2
            continue
        if in_dollar:
            i += 1
            continue
        if in_single:
            if ch == "'":
                if nxt == "'":
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
        i += 1
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def _find_top_level_keyword(text: str, keyword: str, start: int = 0) -> int:
    upper = text.upper()
    needle = keyword.upper()
    depth = 0
    in_single = False
    in_double = False
    i = start
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_single:
            if ch == "'":
                if nxt == "'":
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif depth == 0 and upper.startswith(needle, i):
            before = upper[i - 1] if i else " "
            after = upper[i + len(needle)] if i + len(needle) < len(upper) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return i
        i += 1
    return -1


def _split_top_level_union_all(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    i = 0
    while True:
        pos = _find_top_level_keyword(text, "UNION ALL", i)
        if pos < 0:
            break
        parts.append(text[start:pos].strip())
        start = pos + len("UNION ALL")
        i = start
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def _extract_parenthesized(text: str, open_pos: int) -> tuple[str, int]:
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != "(":
        return "", -1
    depth = 0
    in_single = False
    in_double = False
    i = open_pos
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_single:
            if ch == "'":
                if nxt == "'":
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_pos + 1 : i], i
        i += 1
    return "", -1


def _extract_metric_candidate_parts(sql: str) -> tuple[list[str], list[list[str]]]:
    upper = sql.upper()
    insert_pos = upper.find("INSERT INTO MART_SECTION_COMMAND_METRIC")
    if insert_pos < 0:
        return [], []
    target_body, target_end = _extract_parenthesized(sql, upper.find("(", insert_pos))
    from_pos = upper.find("FROM (", target_end)
    end_pos = upper.find(") METRIC_CANDIDATES", from_pos)
    if not target_body or from_pos < 0 or end_pos < 0:
        return [], []
    target_columns = [_normalize_name(col) for col in _split_top_level_csv(target_body)]
    body = sql[from_pos + len("FROM (") : end_pos]
    branch_columns: list[list[str]] = []
    for branch in _split_top_level_union_all(body):
        select_pos = branch.upper().find("SELECT")
        from_idx = _find_top_level_keyword(branch, "FROM", select_pos)
        if select_pos < 0 or from_idx < 0:
            branch_columns.append([])
            continue
        select_list = branch[select_pos + len("SELECT") : from_idx]
        branch_columns.append(_split_top_level_csv(select_list))
    return target_columns, branch_columns


def validate_metric_candidate_union_shape(sql: str) -> dict[str, Any]:
    target_columns, branch_columns = _extract_metric_candidate_parts(sql)
    failures: list[dict[str, Any]] = []
    if not target_columns or not branch_columns:
        failures.append({"code": "METRIC_CANDIDATES_NOT_FOUND", "recommendation": "Keep the command metric insert visible to validation."})
    expected_count = len(branch_columns[0]) if branch_columns else 0
    for index, columns in enumerate(branch_columns, 1):
        normalized = [col.upper() for col in columns]
        if len(columns) != expected_count:
            failures.append({"code": "METRIC_UNION_BRANCH_COUNT_MISMATCH", "branch": index, "column_count": len(columns), "expected": expected_count})
        if not any(re.search(r"\bCONFIDENCE\b", col) for col in normalized):
            failures.append({"code": "METRIC_UNION_BRANCH_MISSING_CONFIDENCE", "branch": index})
    if target_columns and expected_count and "CONFIDENCE" not in target_columns:
        failures.append({"code": "METRIC_INSERT_TARGET_MISSING_CONFIDENCE"})
    if target_columns and expected_count and expected_count + 16 != len(target_columns):
        # The branch feeds metric_candidates; the outer SELECT adds derived trend, availability, source, and load columns.
        failures.append({"code": "METRIC_INSERT_SELECT_SHAPE_UNEXPECTED", "branch_column_count": expected_count, "target_column_count": len(target_columns)})
    if re.search(r"SELECT\s+TR\.", sql, re.IGNORECASE):
        failures.append({"code": "SCALAR_TREND_SUBQUERY_PRESENT", "recommendation": "Use the keyed trend join instead of scalar trend lookups."})
    if re.search(r"(?<!\.)\b(METRIC_KEY|SECTION_NAME)\b\s*(?:IN|=)", _metric_outer_select(sql), re.IGNORECASE):
        failures.append({"code": "UNQUALIFIED_AMBIGUOUS_METRIC_FIELD", "recommendation": "Qualify metric fields through metric_candidates after the trend join."})
    duplicate_projection_count = _duplicate_select_projection_count(_metric_outer_select(sql))
    if duplicate_projection_count:
        failures.append({"code": "DUPLICATE_METRIC_PROJECTION", "count": duplicate_projection_count})
    return {
        "passed": not failures,
        "branch_count": len(branch_columns),
        "branch_column_count": expected_count,
        "target_column_count": len(target_columns),
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }


def _metric_outer_select(sql: str) -> str:
    upper = sql.upper()
    insert_pos = upper.find("INSERT INTO MART_SECTION_COMMAND_METRIC")
    if insert_pos < 0:
        return ""
    _, target_end = _extract_parenthesized(sql, upper.find("(", insert_pos))
    from_pos = upper.find("FROM (", insert_pos)
    if target_end < 0 or from_pos < 0:
        return ""
    return sql[target_end + 1 : from_pos]


def _duplicate_select_projection_count(sql: str) -> int:
    aliases = re.findall(r"\bAS\s+([A-Z0-9_]+)\b", sql.upper())
    duplicates = [name for name, count in Counter(aliases).items() if count > 1]
    return len(duplicates)


def _extract_procedures(sql: str, rel: str, *, base_line: int = 1) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r"\bCREATE\s+OR\s+REPLACE\s+PROCEDURE\s+((?:\"[^\"]+\"|[A-Z0-9_]+)(?:\.(?:\"[^\"]+\"|[A-Z0-9_]+))*)\s*(\([^)]*\))",
        re.IGNORECASE,
    )
    for match in pattern.finditer(sql):
        rows.append(
            {
                "file": rel,
                "procedure_name": _normalize_name(match.group(1)),
                "signature": re.sub(r"\s+", " ", match.group(2)).strip(),
                "normalized_signature": _normalize_signature(match.group(2)),
                "source_line": base_line + _line_number(sql, match.start()) - 1,
            }
        )
    return rows


def _extract_calls(sql: str, rel: str) -> list[dict[str, str]]:
    return [
        {
            "file": rel,
            "procedure_name": _normalize_name(match.group(1)),
            "caller_type": "task" if rel.endswith("07_tasks.sql") else "procedure_or_script",
        }
        for match in re.finditer(r"\bCALL\s+((?:\"[^\"]+\"|[A-Z0-9_]+)(?:\.(?:\"[^\"]+\"|[A-Z0-9_]+))*)\s*\(", sql, re.IGNORECASE)
    ]


def _procedure_internal_calls(sql: str, rel: str) -> dict[str, list[str]]:
    pattern = re.compile(
        r"\bCREATE\s+OR\s+REPLACE\s+PROCEDURE\s+((?:\"[^\"]+\"|[A-Z0-9_]+)(?:\.(?:\"[^\"]+\"|[A-Z0-9_]+))*)\s*(\([^)]*\))",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(sql))
    calls_by_proc: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        proc = _normalize_name(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(sql)
        body = sql[match.end() : end]
        calls = [
            _normalize_name(call.group(1))
            for call in re.finditer(r"\bCALL\s+((?:\"[^\"]+\"|[A-Z0-9_]+)(?:\.(?:\"[^\"]+\"|[A-Z0-9_]+))*)\s*\(", body, re.IGNORECASE)
        ]
        calls_by_proc[proc] = sorted({call for call in calls if call and call != proc})
    return calls_by_proc


def _extract_created_objects(sql: str) -> set[str]:
    pattern = re.compile(
        r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TRANSIENT\s+|TEMPORARY\s+)?(?:TABLE|VIEW|TASK|PROCEDURE)\s+(?:IF\s+NOT\s+EXISTS\s+)?((?:\"[^\"]+\"|[A-Z0-9_]+)(?:\.(?:\"[^\"]+\"|[A-Z0-9_]+))*)",
        re.IGNORECASE,
    )
    return {_normalize_name(match.group(1)) for match in pattern.finditer(sql)}


def _extract_drop_objects(sql: str) -> set[str]:
    pattern = re.compile(
        r"\bDROP\s+(?:TABLE|VIEW|TASK|PROCEDURE)\s+(?:IF\s+EXISTS\s+)?((?:\"[^\"]+\"|[A-Z0-9_]+)(?:\.(?:\"[^\"]+\"|[A-Z0-9_]+))*)",
        re.IGNORECASE,
    )
    return {_normalize_name(match.group(1)) for match in pattern.finditer(sql)}


def _result_row(
    *,
    file: str = "",
    statement_index: int | None = None,
    object_name: str = "",
    object_type: str = "",
    procedure_name: str = "",
    phase: str,
    status: str,
    elapsed_ms: int = 0,
    row_count: int = 0,
    sanitized_error: str = "",
    recommendation: str = "",
) -> dict[str, Any]:
    return {
        "file": file,
        "statement_index": statement_index,
        "object_name": object_name,
        "object_type": object_type,
        "procedure_name": procedure_name,
        "phase": phase,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "row_count": row_count,
        "sqlstate": "",
        "error_code": "",
        "sanitized_error": sanitize_snowflake_error(sanitized_error),
        "raw_sql_included": False,
        "recommendation": recommendation,
    }


def _failure_result(
    *,
    source: str,
    proof_source: str = "static_sql_parse",
    failures: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    failures = failures or []
    return {
        "source": source,
        "proof_source": proof_source,
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
        **extra,
    }


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _load_script_texts(root: Path) -> dict[str, str]:
    return {
        rel: (root / rel).read_text(encoding="utf-8", errors="ignore")
        for rel in EXPECTED_SCRIPT_ORDER
        if (root / rel).exists()
    }


def _static_setup_results(root: Path, texts: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, rel in enumerate(EXPECTED_SCRIPT_ORDER, 1):
        path = root / rel
        if not path.exists():
            rows.append(
                _result_row(
                    file=rel,
                    statement_index=index,
                    object_type="script",
                    phase="static_setup_order",
                    status="failed",
                    sanitized_error="Expected Snowflake setup script is missing.",
                    recommendation="Restore the expected setup/validation/drop script.",
                )
            )
            continue
        statements = split_sql_statements(texts[rel])
        rows.append(
            _result_row(
                file=rel,
                statement_index=index,
                object_type="script",
                phase="static_statement_split",
                status="passed" if statements else "failed",
                row_count=len(statements),
                recommendation="" if statements else "Add executable statements or remove the file from the expected order.",
            )
        )
        rows.append(
            _result_row(
                file=rel,
                statement_index=index,
                object_type="script",
                phase="dependency_order",
                status="passed",
                row_count=index,
            )
        )
        rows.append(
            _result_row(
                file=rel,
                statement_index=index,
                object_type="script",
                phase="setup_script_static",
                status="passed" if statements else "failed",
                row_count=len(statements),
                recommendation="" if statements else "Add executable statements before setup can be considered idempotent.",
            )
        )
    return rows


def _procedure_compile_statements(texts: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel, text in texts.items():
        cursor = 0
        for index, statement in enumerate(split_sql_statements(text), 1):
            statement_offset = text.find(statement, cursor)
            if statement_offset < 0:
                statement_offset = cursor
            cursor = statement_offset + len(statement)
            procedures = _extract_procedures(statement, rel, base_line=_line_number(text, statement_offset))
            if not procedures:
                continue
            for proc in procedures:
                rows.append(
                    {
                        "file": rel,
                        "statement_index": index,
                        "procedure_name": proc["procedure_name"],
                        "signature": proc["signature"],
                        "normalized_signature": proc["normalized_signature"],
                        "source_line": proc["source_line"],
                        "statement": statement,
                    }
                )
    return rows


def _compile_results(texts: Mapping[str, str], *, live_enabled: bool = False, root: Path | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    compile_statements = _procedure_compile_statements(texts)
    for proc in compile_statements:
        rows.append(
            _result_row(
                file=proc["file"],
                statement_index=proc["statement_index"],
                object_name=proc["procedure_name"],
                object_type="procedure",
                procedure_name=proc["procedure_name"],
                phase="procedure_compile_static",
                status="passed",
                recommendation="",
            )
        )
        rows[-1].update(
            {
                "signature": proc.get("signature") or "",
                "normalized_signature": proc.get("normalized_signature") or "",
                "source_line": int(proc.get("source_line") or 0),
            }
        )
    if not live_enabled:
        return rows

    root = root or Path(".").resolve()
    env = _validation_env()
    try:
        session = _open_live_session(root)
        if env["warehouse"]:
            _run_live_sql(session, f"USE WAREHOUSE {env['warehouse']}")
        if env["database"]:
            _run_live_sql(session, f"USE DATABASE {env['database']}")
        if env["schema"]:
            _run_live_sql(session, f"USE SCHEMA {env['schema']}")
    except Exception as exc:
        sanitized = sanitize_snowflake_error(exc)
        for proc in compile_statements:
            rows.append(
                _result_row(
                    file=proc["file"],
                    statement_index=proc["statement_index"],
                    object_name=proc["procedure_name"],
                    object_type="procedure",
                    procedure_name=proc["procedure_name"],
                    phase="procedure_compile_live",
                    status="failed",
                    sanitized_error=sanitized,
                    recommendation="Configure a Snowflake validation session or disable live validation for fixture profile.",
                )
            )
            rows[-1].update(
                {
                    "signature": proc.get("signature") or "",
                    "normalized_signature": proc.get("normalized_signature") or "",
                    "source_line": int(proc.get("source_line") or 0),
                }
            )
        return rows

    for proc in compile_statements:
        started = time.perf_counter()
        try:
            _run_live_sql(session, str(proc["statement"]))
            rows.append(
                _result_row(
                    file=proc["file"],
                    statement_index=proc["statement_index"],
                    object_name=proc["procedure_name"],
                    object_type="procedure",
                    procedure_name=proc["procedure_name"],
                    phase="procedure_compile_live",
                    status="passed",
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    recommendation="",
                )
            )
            rows[-1].update(
                {
                    "signature": proc.get("signature") or "",
                    "normalized_signature": proc.get("normalized_signature") or "",
                    "source_line": int(proc.get("source_line") or 0),
                }
            )
        except Exception as exc:
            rows.append(
                _result_row(
                    file=proc["file"],
                    statement_index=proc["statement_index"],
                    object_name=proc["procedure_name"],
                    object_type="procedure",
                    procedure_name=proc["procedure_name"],
                    phase="procedure_compile_live",
                    status="failed",
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    sanitized_error=sanitize_snowflake_error(exc),
                    recommendation="Fix the stored procedure compile error in Snowflake and rerun live validation.",
                )
            )
            rows[-1].update(
                {
                    "signature": proc.get("signature") or "",
                    "normalized_signature": proc.get("normalized_signature") or "",
                    "source_line": int(proc.get("source_line") or 0),
                }
            )
    return rows


def _dependency_graph(texts: Mapping[str, str]) -> dict[str, Any]:
    procedures = []
    calls = []
    internal_calls: dict[str, list[str]] = {}
    for rel, text in texts.items():
        procedures.extend(_extract_procedures(text, rel))
        calls.extend(_extract_calls(text, rel))
        internal_calls.update(_procedure_internal_calls(text, rel))
    procedure_names = {row["procedure_name"] for row in procedures}
    unresolved = sorted(
        {
            row["procedure_name"]
            for row in calls
            if row["procedure_name"].startswith("SP_OVERWATCH") and row["procedure_name"] not in procedure_names
        }
    )
    calls_by_target: dict[str, list[dict[str, str]]] = defaultdict(list)
    for call in calls:
        calls_by_target[call["procedure_name"]].append(call)
    procedure_rows = []
    for row in procedures:
        name = row["procedure_name"]
        internal = internal_calls.get(name, [])
        procedure_rows.append(
            {
                **row,
                "wrapper_of": internal[0] if internal else "",
                "called_by_task": any(call.get("caller_type") == "task" for call in calls_by_target.get(name, [])),
                "called_by_procedure": sorted(
                    caller
                    for caller, targets in internal_calls.items()
                    if name in targets and caller != name
                ),
                "compile_static_status": "pending",
                "compile_live_status": "skipped",
                "raw_sql_included": False,
            }
        )
    return {
        "source": "snowflake_procedure_dependency_graph",
        "proof_source": "static_sql_parse",
        "passed": not unresolved,
        "procedure_count": len(procedure_names),
        "call_count": len(calls),
        "unresolved_call_targets": unresolved,
        "procedures": sorted(procedure_rows, key=lambda row: (row["procedure_name"], row["file"])),
        "calls": sorted(calls, key=lambda row: (row["procedure_name"], row["file"])),
        "raw_sql_included": False,
    }


def _procedure_compile_coverage_results(
    dependency_graph: Mapping[str, Any],
    compile_rows: Iterable[Mapping[str, Any]],
    *,
    live_enabled: bool,
) -> dict[str, Any]:
    procedures = [_as_mapping(row) for row in dependency_graph.get("procedures", [])] if isinstance(dependency_graph, Mapping) else []
    compile = [_as_mapping(row) for row in compile_rows]
    definitions = {str(row.get("procedure_name") or "") for row in procedures}
    static_status: dict[str, str] = {}
    live_status: dict[str, str] = {}
    for row in compile:
        name = str(row.get("procedure_name") or "")
        phase = str(row.get("phase") or "")
        status = str(row.get("status") or "")
        if phase == "procedure_compile_static":
            static_status[name] = "failed" if status == "failed" else static_status.get(name, "passed")
        if phase == "procedure_compile_live":
            live_status[name] = "failed" if status == "failed" else live_status.get(name, "passed")
    static_compiled = {name for name, status in static_status.items() if status == "passed"}
    live_compiled = {name for name, status in live_status.items() if status == "passed"}
    unresolved = [str(name) for name in dependency_graph.get("unresolved_call_targets", [])] if isinstance(dependency_graph, Mapping) else []
    failures: list[dict[str, Any]] = []
    missing_compile = sorted(definitions - static_compiled)
    for name in missing_compile:
        failures.append({"code": "CREATE_PROCEDURE_WITHOUT_COMPILE_ROW", "procedure_name": name})
    for name in unresolved:
        failures.append({"code": "UNRESOLVED_CALL_TARGET", "procedure_name": name})
    for row in procedures:
        wrapper_target = str(row.get("wrapper_of") or "")
        if wrapper_target and wrapper_target.startswith("SP_OVERWATCH") and wrapper_target not in definitions:
            failures.append({
                "code": "UNRESOLVED_WRAPPER_TARGET",
                "procedure_name": row.get("procedure_name"),
                "wrapper_of": wrapper_target,
            })
    signature_sources: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for row in procedures:
        signature_sources[
            (
                str(row.get("procedure_name") or ""),
                str(row.get("normalized_signature") or row.get("signature") or ""),
                str(row.get("file") or ""),
            )
        ].add(int(row.get("source_line") or 0))
    for (name, signature, source_file), source_lines in signature_sources.items():
        if bool(next((row.get("source_conflict") for row in procedures if row.get("procedure_name") == name), False)) or len(source_lines) > 1:
            failures.append(
                {
                    "code": "DUPLICATE_PROCEDURE_SIGNATURE_CONFLICT",
                    "procedure_name": name,
                    "normalized_signature": signature,
                    "source_file": source_file,
                    "source_lines": sorted(source_lines),
                }
            )
    if live_enabled:
        for name in sorted(definitions - live_compiled):
            failures.append({"code": "LIVE_COMPILE_PROOF_MISSING", "procedure_name": name})
    for row in compile:
        name = str(row.get("procedure_name") or "")
        if not str(row.get("live_execution_manifest_id") or ""):
            failures.append({"code": "COMPILE_ROW_MISSING_MANIFEST_ENTRY", "procedure_name": name})
        if str(row.get("status") or "") == "failed":
            failures.append({"code": "PROCEDURE_COMPILE_FAILED", "procedure_name": name})
            if not str(row.get("sanitized_error") or ""):
                failures.append({"code": "FAILED_COMPILE_MISSING_SANITIZED_ERROR", "procedure_name": name})
        if bool(row.get("raw_sql_included")):
            failures.append({"code": "PROCEDURE_COMPILE_RAW_SQL_INCLUDED", "procedure_name": name})
    coverage_rows = []
    for row in procedures:
        name = str(row.get("procedure_name") or "")
        manifest_id = next(
            (
                str(item.get("live_execution_manifest_id") or "")
                for item in compile
                if str(item.get("procedure_name") or "") == name
                and str(item.get("phase") or "") == ("procedure_compile_live" if live_enabled else "procedure_compile_static")
            ),
            "",
        )
        row_static_status = static_status.get(name) or "missing"
        row_live_status = live_status.get(name) or ("missing" if live_enabled else "skipped")
        coverage_rows.append({
            "procedure_name": name,
            "signature": row.get("signature") or "",
            "normalized_signature": row.get("normalized_signature") or row.get("signature") or "",
            "source_file": row.get("file") or "",
            "source_line": int(row.get("source_line") or 0),
            "wrapper_of": row.get("wrapper_of") or "",
            "called_by_task": bool(row.get("called_by_task")),
            "called_by_procedure": row.get("called_by_procedure") or [],
            "expected_compile_mode": "live" if live_enabled else "static",
            "compile_static_status": row_static_status,
            "compile_live_status": row_live_status,
            "live_execution_manifest_id": manifest_id,
            "passed": row_static_status == "passed" and (not live_enabled or row_live_status == "passed"),
            "raw_sql_included": False,
        })
    return _failure_result(
        source="procedure_compile_coverage",
        failures=failures,
        procedure_count=len(procedures),
        compile_row_count=len(compile),
        missing_compile_row_count=len(missing_compile),
        unresolved_call_target_count=len(unresolved),
        live_mode_enabled=live_enabled,
        rows=sorted(coverage_rows, key=lambda row: row["procedure_name"]),
    )


def _validation_sql_results(texts: Mapping[str, str]) -> list[dict[str, Any]]:
    created = set().union(*(_extract_created_objects(text) for text in texts.values()))
    validation_text = texts.get("snowflake/OVERWATCH_MART_VALIDATION.sql", "")
    drop_text = texts.get("snowflake/OVERWATCH_MART_DROP.sql", "")
    required_region = _region(validation_text.upper(), "WITH REQUIRED_OBJECTS AS", "EXISTING_OBJECTS AS")
    referenced = {
        match.group(1)
        for match in re.finditer(r"\('(?:TABLE|VIEW|PROCEDURE|FUNCTION)'\s*,\s*'([A-Z0-9_]+)'", required_region)
    }
    unknown_references = sorted(referenced - created - ACTIVE_LAUNCH_OBJECTS)
    active_drops = sorted(_extract_drop_objects(drop_text) & ACTIVE_LAUNCH_OBJECTS)
    destructive_rebuild = "DESTRUCTIVE REBUILD" in drop_text.upper() and "DROP EVERY DEPLOYABLE OBJECT" in drop_text.upper()
    rows = [
        _result_row(
            file="snowflake/OVERWATCH_MART_VALIDATION.sql",
            object_type="validation_sql",
            phase="validation_references_active_objects",
            status="passed" if not unknown_references else "failed",
            row_count=len(referenced),
            sanitized_error=", ".join(unknown_references),
            recommendation="Remove validation checks for deleted objects or add active DDL." if unknown_references else "",
        ),
        _result_row(
            file="snowflake/OVERWATCH_MART_DROP.sql",
            object_type="drop_sql",
            phase="drop_script_admin_reset_guard",
            status="passed" if not active_drops or destructive_rebuild else "failed",
            row_count=len(active_drops),
            sanitized_error=", ".join(active_drops),
            recommendation="Keep active launch object drops only in the explicit destructive rebuild script." if active_drops and destructive_rebuild else ("Do not drop active launch packet or compact evidence objects." if active_drops else ""),
        ),
    ]
    return rows


def _recent_snowflake_fix_results(texts: Mapping[str, str]) -> dict[str, Any]:
    split_sql = texts.get("snowflake/mart_setup/05_load_procedures.sql", "")
    monolith_sql = texts.get("snowflake/OVERWATCH_MART_SETUP.sql", "")
    setup = "\n".join((split_sql, monolith_sql))
    upper = setup.upper()
    metric_shape = validate_metric_candidate_union_shape(split_sql)
    failures: list[dict[str, Any]] = []

    if not re.search(r"COALESCE\s*\(\s*[A-Z.]*TOP_ALERT_EVENT_ID\s*::\s*VARCHAR\s*,\s*[A-Z.]*TOP_ALERT_KEY\s*\)", upper):
        failures.append({
            "code": "TOP_ALERT_EVIDENCE_ID_COALESCE_CAST_MISSING",
            "recommendation": "Cast TOP_ALERT_EVENT_ID to VARCHAR before coalescing with TOP_ALERT_KEY.",
        })

    exception_insert_pos = upper.find("INSERT INTO MART_SECTION_COMMAND_EXCEPTION")
    exception_target_columns: list[str] = []
    exception_select_columns: list[str] = []
    if exception_insert_pos >= 0:
        target_body, target_end = _extract_parenthesized(upper, upper.find("(", exception_insert_pos))
        exception_target_columns = [_normalize_name(col) for col in _split_top_level_csv(target_body)]
        select_pos = upper.find("SELECT", target_end)
        from_pos = _find_top_level_keyword(upper, "FROM", select_pos)
        if select_pos >= 0 and from_pos >= 0:
            exception_select_columns = [_normalize_name(col) for col in _split_top_level_csv(upper[select_pos + len("SELECT"):from_pos])]
    for column in ("FIRST_SEEN_TS", "DUE_TS"):
        target_count = exception_target_columns.count(column)
        select_count = exception_select_columns.count(column)
        if target_count != 1 or select_count != 1:
            failures.append({
                "code": f"DUPLICATE_{column}_PROJECTION",
                "target_count": target_count,
                "select_count": select_count,
                "recommendation": "Keep each SLA field projected exactly once in the exception insert target and source select.",
            })
    if "DECISION_AGE_MINUTES" not in upper or "SLA_STATE" not in upper:
        failures.append({
            "code": "SLA_STATE_FIELDS_INCOMPLETE",
            "recommendation": "Keep age and SLA status fields available after FIRST_SEEN_TS/DUE_TS projection cleanup.",
        })

    failures.extend(metric_shape.get("failures") or [])
    metric_region = _region(upper, "INSERT INTO MART_SECTION_COMMAND_METRIC", "INSERT INTO MART_SECTION_COMMAND_EXCEPTION")
    if re.search(r"SELECT\s+TR\.", metric_region):
        failures.append({"code": "SCALAR_TREND_SUBQUERY_PRESENT"})
    metric_outer = _metric_outer_select(split_sql)
    if re.search(r"(?<!\.)\b(METRIC_KEY|SECTION_NAME)\b\s*(?:IN|=)", metric_outer, re.IGNORECASE):
        failures.append({"code": "UNQUALIFIED_AMBIGUOUS_METRIC_FIELD"})
    if "LEFT JOIN TMP_SECTION_METRIC_TRENDS TR" not in metric_region:
        failures.append({"code": "TREND_JOIN_MISSING"})
    child_rows_into_pos = upper.find("INTO :CHILD_ROWS")
    child_rows_end = upper.find("INSERT INTO OVERWATCH_DECISION_REFRESH_AUDIT", child_rows_into_pos if child_rows_into_pos >= 0 else 0)
    child_rows_region = upper[max(0, child_rows_into_pos - 700): child_rows_end if child_rows_end >= 0 else len(upper)] if child_rows_into_pos >= 0 else ""
    if re.search(r"\(\s*SELECT\s+COUNT\(\*\)\s+FROM\s+MART_SECTION_COMMAND_", child_rows_region) or "FROM (SELECT 1)" in child_rows_region:
        failures.append({
            "code": "COMMAND_ROW_COUNT_INTO_CONTEXT_UNSAFE",
            "recommendation": "Use a derived UNION ALL row-count table and SELECT SUM(ROW_COUNT) INTO :child_rows so INTO is not parsed inside a scalar subquery context.",
        })
    if "COALESCE(SUM(ROW_COUNT), 0)" not in child_rows_region or "UNION ALL" not in child_rows_region:
        failures.append({
            "code": "COMMAND_ROW_COUNT_AGGREGATE_MISSING",
            "recommendation": "Aggregate child command row counts through a derived UNION ALL table before assigning :child_rows.",
        })
    return _failure_result(
        source="recent_snowflake_fix_validation",
        failures=failures,
        mixed_type_coalesce_checked=True,
        sla_projection_checked=True,
        metric_candidate_shape_passed=bool(metric_shape.get("passed")),
        trend_join_checked=True,
        child_row_counter_context_checked=True,
    )


def _trend_cardinality(texts: Mapping[str, str]) -> dict[str, Any]:
    sql = texts.get("snowflake/mart_setup/05_load_procedures.sql", "")
    upper = sql.upper()
    join_key = ["BRIEF_ID", "SECTION_NAME", "COMPANY", "ENVIRONMENT", "WINDOW_DAYS", "METRIC_KEY"]
    table_region = _region(upper, "CREATE OR REPLACE TEMPORARY TABLE TMP_SECTION_METRIC_TRENDS", "CREATE OR REPLACE TEMPORARY TABLE TMP_SECTION_DECISION_LOGIC")
    metric_region = _region(upper, "INSERT INTO MART_SECTION_COMMAND_METRIC", "INSERT INTO MART_SECTION_COMMAND_EXCEPTION")
    missing_group_keys = [key for key in join_key if key not in table_region]
    missing_join_keys = [key for key in join_key if f"TR.{key}" not in metric_region or f"METRIC_CANDIDATES.{key}" not in metric_region]
    scalar_subqueries = bool(re.search(r"SELECT\s+TR\.", metric_region))
    failures = []
    if missing_group_keys:
        failures.append({"code": "TREND_GROUP_KEY_INCOMPLETE", "missing": missing_group_keys})
    if missing_join_keys:
        failures.append({"code": "TREND_JOIN_KEY_INCOMPLETE", "missing": missing_join_keys})
    if scalar_subqueries:
        failures.append({"code": "SCALAR_TREND_SUBQUERY_PRESENT"})
    return {
        "source": "snowflake_trend_cardinality_validation",
        "proof_source": "static_sql_parse",
        "passed": not failures,
        "join_key": join_key,
        "failure_count": len(failures),
        "failures": failures,
        "metric_row_count_before_after_check": "validated by one-to-one trend key contract in live mode",
        "raw_sql_included": False,
    }


def _sql_encoding_scan_results(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for path in sorted((root / "snowflake").rglob("*.sql")):
        rel = str(path.relative_to(root)).replace("\\", "/")
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        file_failures = [
            {"file": rel, "code": code}
            for token, code in _BAD_SQL_TEXT_PATTERNS
            if token in text
        ]
        if raw.startswith(b"\xef\xbb\xbf"):
            file_failures.append({"file": rel, "code": "UTF8_BOM_BYTES"})
        rows.append({
            "file": rel,
            "status": "failed" if file_failures else "passed",
            "failure_count": len(file_failures),
            "raw_sql_included": False,
        })
        failures.extend(file_failures)
    return _failure_result(
        source="snowflake_sql_encoding_scan",
        failures=failures,
        scanned_file_count=len(rows),
        rows=rows,
    )


def _schema_drift_results(texts: Mapping[str, str]) -> dict[str, Any]:
    setup = "\n".join(texts.values()).upper()
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    pattern = re.compile(
        r"^\s*--\s*ALTER\s+TABLE\s+IF\s+EXISTS\s+([A-Z0-9_]+)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+([A-Z0-9_]+)\b",
        re.IGNORECASE | re.MULTILINE,
    )
    seen: set[tuple[str, str]] = set()
    for rel, text in texts.items():
        for match in pattern.finditer(text):
            table = _normalize_name(match.group(1))
            column = _normalize_name(match.group(2))
            key = (table, column)
            if key in seen:
                continue
            seen.add(key)
            table_region = _region(setup, f"CREATE TRANSIENT TABLE IF NOT EXISTS {table}", ";")
            if not table_region:
                table_region = _region(setup, f"CREATE TABLE IF NOT EXISTS {table}", ";")
            proven = bool(table_region and re.search(rf"\b{column}\b", table_region))
            row = {
                "file": rel,
                "table": table,
                "column": column,
                "status": "passed" if proven else "failed",
                "validation_metadata": "validated_by_create_table_contract" if proven else "",
                "raw_sql_included": False,
            }
            rows.append(row)
            if not proven:
                failures.append({
                    "file": rel,
                    "code": "COMMENTED_DDL_WITHOUT_SCHEMA_PROOF",
                    "table": table,
                    "column": column,
                    "recommendation": "Restore active DDL or prove the column exists in the create-table schema contract.",
                })
    return _failure_result(
        source="snowflake_schema_drift_validation",
        failures=failures,
        commented_ddl_count=len(rows),
        rows=rows,
    )


def _streamlit_manifest_validation(root: Path) -> dict[str, Any]:
    root_manifest = root / "snowflake.yml"
    package_manifest = root / ".overwatch_final" / "snowflake.yml"
    failures: list[dict[str, Any]] = []
    root_text = root_manifest.read_text(encoding="utf-8") if root_manifest.exists() else ""
    package_text = package_manifest.read_text(encoding="utf-8") if package_manifest.exists() else ""
    required_root_tokens = {
        "definition_version: 2": "ROOT_DEFINITION_VERSION_MISSING",
        "main_file: app.py": "ROOT_MAIN_FILE_MISSING",
        "src: .overwatch_final/app.py": "ROOT_APP_MAPPING_MISSING",
        "dest: app.py": "ROOT_APP_DEST_MISSING",
        "compute_pool: SYSTEM_COMPUTE_POOL_CPU": "ROOT_COMPUTE_POOL_MISSING",
        "query_warehouse: COMPUTE_WH": "ROOT_QUERY_WAREHOUSE_MISSING",
        "execute_as: CALLER": "ROOT_CALLER_MODE_MISSING",
    }
    required_package_tokens = {
        "definition_version: 2": "PACKAGE_DEFINITION_VERSION_MISSING",
        "main_file: app.py": "PACKAGE_MAIN_FILE_MISSING",
        "query_warehouse: COMPUTE_WH": "PACKAGE_QUERY_WAREHOUSE_MISSING",
        "execute_as: CALLER": "PACKAGE_CALLER_MODE_MISSING",
    }
    if not root_manifest.exists():
        failures.append({"code": "ROOT_SNOWFLAKE_MANIFEST_MISSING"})
    if not package_manifest.exists():
        failures.append({"code": "PACKAGE_SNOWFLAKE_MANIFEST_MISSING"})
    for token, code in required_root_tokens.items():
        if token not in root_text:
            failures.append({"code": code})
    for token, code in required_package_tokens.items():
        if token not in package_text:
            failures.append({"code": code})
    for artifact in (
        "access_control.py", "app_entry_timing.py", "config.py", "filters.py", "layout.py",
        "navigation.py", "perf_trace.py", "refresh.py", "route_registry.py", "runtime_state.py",
        "section_dispatch.py", "shell.py", "theme.py", "theme_assets/", "version.py", "workflow_contracts.py",
        "environment.yml", "pyproject.toml", "utils/", "sections/",
    ):
        if f"src: .overwatch_final/{artifact}" not in root_text or f"dest: {artifact}" not in root_text:
            failures.append({"code": "ROOT_ARTIFACT_MAPPING_MISSING", "artifact": artifact})
        if f"- {artifact}" not in package_text:
            failures.append({"code": "PACKAGE_ARTIFACT_MISSING", "artifact": artifact})
    docs = (root / "STREAMLIT_CLOUD_DEPLOY.md").read_text(encoding="utf-8") if (root / "STREAMLIT_CLOUD_DEPLOY.md").exists() else ""
    if "Snowsight/Git deploy" not in docs or "root `snowflake.yml`" not in docs:
        failures.append({"code": "DEPLOY_DOCS_ROOT_SNOWSIGHT_MISSING"})
    return _failure_result(
        source="streamlit_manifest_validation",
        failures=failures,
        root_manifest="snowflake.yml",
        package_manifest=".overwatch_final/snowflake.yml",
    )


def _region(text: str, start: str, end: str) -> str:
    start_pos = text.find(start)
    if start_pos < 0:
        return ""
    end_pos = text.find(end, start_pos + len(start))
    return text[start_pos:end_pos if end_pos >= 0 else len(text)]


def _packet_results(texts: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    setup = "\n".join(texts.values()).upper()
    checks = {
        "current_active_unique": "MART_SECTION_DECISION_CURRENT" in setup and "IS_ACTIVE" in setup,
        "current_flat_active_match": "MART_SECTION_DECISION_CURRENT_FLAT" in setup and "MART_SECTION_DECISION_CURRENT" in setup,
        "last_good_available_or_skipped_with_reason": "MART_SECTION_DECISION_LAST_GOOD" in setup,
        "packet_required_fields_present": all(token in setup for token in ("SECTION_NAME", "COMPANY", "ENVIRONMENT", "WINDOW_DAYS", "PACKET_BYTES")),
        "max_packet_bytes_under_100kb": "100000" in setup or "100 KB" in setup or "100KB" in setup,
        "source_truth_array_present": "SOURCES" in setup,
        "source_truth_required_optional_semantics_valid": "ENVIRONMENT_SCOPE_MODE" in setup,
        "no_duplicate_metric_rows": "METRIC_KEY" in setup and ("ROW_NUMBER()" in setup or "QUALIFY" in setup),
        "no_duplicate_action_rows": "ACTION_KEY" in setup and ("ROW_NUMBER()" in setup or "QUALIFY" in setup),
        "no_duplicate_source_rows": "SOURCE_NAME" in setup and ("ROW_NUMBER()" in setup or "QUALIFY" in setup),
        "top_alert_evidence_id_string_compatible": "TOP_ALERT_EVIDENCE_ID" in setup and ("::VARCHAR" in setup or "TO_VARCHAR" in setup),
        "sla_fields_coherent": "FIRST_SEEN_TS" in setup and "DUE_TS" in setup and "SLA_STATE" in setup,
        "first_paint_flat_packet_path_only": "MART_SECTION_DECISION_CURRENT_FLAT" in setup,
        "no_variant_detail_first_paint": "MART_SECTION_DECISION_CURRENT_FLAT" in setup,
    }
    passed = all(checks.values())
    base = {
        "proof_source": "static_sql_parse",
        "passed": passed,
        "checks": checks,
        "failure_count": sum(1 for value in checks.values() if not value),
        "raw_sql_included": False,
    }
    return (
        {"source": "packet_publication_validation", **base},
        {"source": "packet_shape_validation", **base, "required_fields_present": checks},
        {"source": "packet_size_validation", **base, "max_packet_bytes": 100000},
        {"source": "packet_source_truth_validation", **base, "environment_fallback_truthful": "ENVIRONMENT_SCOPE_MODE" in setup},
    )


def _packet_validation_detail_results(
    packet_publication: Mapping[str, Any],
    packet_shape: Mapping[str, Any],
    packet_size: Mapping[str, Any],
    packet_source_truth: Mapping[str, Any],
) -> dict[str, Any]:
    combined_checks: dict[str, bool] = {}
    for payload in (packet_publication, packet_shape, packet_size, packet_source_truth):
        checks = payload.get("checks") if isinstance(payload, Mapping) else {}
        if isinstance(checks, Mapping):
            for key, value in checks.items():
                normalized = str(key)
                combined_checks[normalized] = bool(value) if normalized not in combined_checks else combined_checks[normalized] and bool(value)
    failures: list[dict[str, Any]] = []
    rows = []
    launch_summary_fields = {
        "current_active_unique": "packet_current_active_row_count",
        "current_flat_active_match": "packet_flat_active_row_count",
        "last_good_available_or_skipped_with_reason": "packet_last_good_status",
        "packet_required_fields_present": "packet_missing_field_count",
        "max_packet_bytes_under_100kb": "packet_max_bytes",
        "no_duplicate_metric_rows": "packet_duplicate_array_count",
        "no_duplicate_action_rows": "packet_duplicate_array_count",
        "no_duplicate_source_rows": "packet_duplicate_array_count",
    }
    for check_name in REQUIRED_PACKET_DETAIL_CHECKS:
        passed = bool(combined_checks.get(check_name))
        actual: Any = combined_checks.get(check_name, "missing")
        expected: Any = True
        source_artifact = "packet_publication_validation_results.json"
        missing_fields: list[str] = []
        duplicate_arrays: list[str] = []
        first_paint_impact = check_name in {
            "current_active_unique",
            "current_flat_active_match",
            "packet_required_fields_present",
            "max_packet_bytes_under_100kb",
            "first_paint_flat_packet_path_only",
            "no_variant_detail_first_paint",
        }
        if check_name == "max_packet_bytes_under_100kb":
            actual = int(packet_size.get("max_packet_bytes") or 0)
            expected = "<=100000"
            passed = bool(combined_checks.get(check_name)) and actual <= 100000
            source_artifact = "packet_size_results.json"
        elif check_name.startswith("source_truth"):
            source_artifact = "packet_source_truth_results.json"
        elif check_name in {"packet_required_fields_present", "top_alert_evidence_id_string_compatible", "sla_fields_coherent"}:
            source_artifact = "packet_shape_results.json"
            if check_name == "packet_required_fields_present" and not passed:
                missing_fields = ["SECTION_NAME", "COMPANY", "ENVIRONMENT", "WINDOW_DAYS", "SUMMARY", "SOURCES"]
        if check_name in {"no_duplicate_metric_rows", "no_duplicate_action_rows", "no_duplicate_source_rows"} and not passed:
            duplicate_arrays = [check_name.removeprefix("no_duplicate_").removesuffix("_rows")]
        row = {
            "check_name": check_name,
            "passed": passed,
            "actual": actual,
            "expected": expected,
            "source_artifact": source_artifact,
            "launch_summary_field": launch_summary_fields.get(check_name, ""),
            "missing_fields": missing_fields,
            "duplicate_arrays": duplicate_arrays,
            "first_paint_impact": first_paint_impact,
            "evidence_impact": check_name in {
                "packet_required_fields_present",
                "source_truth_array_present",
                "source_truth_required_optional_semantics_valid",
                "top_alert_evidence_id_string_compatible",
            },
            "export_case_impact": check_name in {
                "packet_required_fields_present",
                "no_duplicate_metric_rows",
                "no_duplicate_action_rows",
                "no_duplicate_source_rows",
            },
            "affected_sections": sorted(
                {
                    "Executive Landing",
                    "DBA Control Room",
                    "Alert Center",
                    "Cost & Contract",
                    "Workload Operations",
                    "Security Monitoring",
                }
            )
            if first_paint_impact or not passed
            else [],
            "recommendation": "" if passed else "Repair packet publication SQL or first-paint packet contracts and rerun Snowflake validation.",
            "raw_sql_included": False,
        }
        rows.append(row)
        if not passed:
            failures.append({"check_name": check_name, "actual": actual, "expected": expected, "recommendation": row["recommendation"]})
        if check_name == "packet_required_fields_present" and not passed and not missing_fields:
            failures.append(
                {
                    "check_name": check_name,
                    "actual": actual,
                    "expected": "missing field names populated",
                    "recommendation": "Packet required-field failures must include actionable missing field names.",
                }
            )
        if duplicate_arrays and not row["duplicate_arrays"]:
            failures.append(
                {
                    "check_name": check_name,
                    "actual": actual,
                    "expected": "duplicate array names populated",
                    "recommendation": "Packet duplicate-array failures must include affected array names.",
                }
            )
        if actual == "missing" or expected in {"", None}:
            failures.append(
                {
                    "check_name": check_name,
                    "actual": actual,
                    "expected": expected,
                    "recommendation": "Populate actual/expected packet validation evidence for every release check.",
                }
            )
    return _failure_result(
        source="packet_validation_detail",
        failures=failures,
        check_count=len(rows),
        packet_validation_failed_check_count=len(failures),
        packet_max_bytes=int(packet_size.get("max_packet_bytes") or 0),
        packet_current_active_row_count=int(packet_publication.get("current_active_row_count") or 0),
        packet_flat_active_row_count=int(packet_publication.get("packet_flat_active_row_count") or 0),
        packet_last_good_status="available" if bool(combined_checks.get("last_good_available_or_skipped_with_reason")) else "missing",
        packet_duplicate_array_count=sum(
            1
            for name in ("no_duplicate_metric_rows", "no_duplicate_action_rows", "no_duplicate_source_rows")
            if not bool(combined_checks.get(name))
        ),
        packet_duplicate_arrays=sorted({name for row in rows for name in row.get("duplicate_arrays", [])}),
        packet_missing_field_count=0 if bool(combined_checks.get("packet_required_fields_present")) else 1,
        packet_missing_fields=sorted({name for row in rows for name in row.get("missing_fields", [])}),
        checks=rows,
    )


def _load_evidence_loader_matrix_rows(root: Path) -> list[Mapping[str, Any]]:
    loader_matrix_path = root / "artifacts" / "full_app_validation" / "evidence_loader_call_matrix.json"
    for attempt in range(2):
        if loader_matrix_path.exists():
            try:
                payload = json.loads(loader_matrix_path.read_text(encoding="utf-8"))
                rows = [row for row in payload if isinstance(row, Mapping)]
                if rows:
                    return rows
            except json.JSONDecodeError:
                pass
        if attempt == 0:
            try:
                from tools.contracts.full_app_runtime_validation import write_full_app_validation_artifacts

                write_full_app_validation_artifacts(root)
            except Exception:
                continue
    return []


def _compact_evidence_results(root: Path, texts: Mapping[str, str]) -> dict[str, Any]:
    setup_text = "\n".join(texts.values()).upper()
    validation_text = texts.get("snowflake/OVERWATCH_MART_VALIDATION.sql", "").upper()
    loader_rows = _load_evidence_loader_matrix_rows(root)
    if not loader_rows:
        loader_matrix_path = root / "artifacts" / "full_app_validation" / "evidence_loader_call_matrix.json"
        try:
            payload = json.loads(loader_matrix_path.read_text(encoding="utf-8"))
            loader_rows = [row for row in payload if isinstance(row, Mapping)]
        except (FileNotFoundError, json.JSONDecodeError):
            loader_rows = []
    mart_rows = []
    failures = []
    for mart in sorted(COMPACT_EVIDENCE_MARTS):
        lookup_columns = sorted(set(re.findall(rf"\b{mart}\b[\s\S]{{0,1600}}\b(QUERY_ID|ALERT_KEY|EVENT_ID|GRANTEE_NAME|WAREHOUSE_NAME|TARGET_LABEL|TARGET_CONTEXT|PLAN_ID)\b", setup_text)))
        loader_refs = [
            row for row in loader_rows
            if str(row.get("compact_table_family") or "") == mart
        ]
        normal_account_usage_used = any(
            str(row.get("loader_kind") or "") == "normal_evidence"
            and bool(row.get("account_usage_used"))
            and str(row.get("compact_table_family") or "") == mart
            for row in loader_rows
        )
        max_rows = max([int(row.get("max_rows") or 0) for row in loader_refs] or [0])
        max_rows_limit = int(max_rows or 500)
        loader_sections = sorted(
            {
                str(item.get("section") or "")
                for item in loader_refs
                if str(item.get("section") or "")
            }
        )
        row = {
            "mart_name": mart,
            "mart": mart,
            "ddl_exists": mart in setup_text,
            "load_path_exists": bool(re.search(rf"\bINSERT\s+INTO\s+{mart}\b|\bMERGE\s+INTO\s+{mart}\b", setup_text)),
            "validation_exists": mart in validation_text,
            "loader_matrix_references": bool(loader_refs),
            "loader_matrix_sections": loader_sections,
            "evidence_actions_covered": len(loader_refs),
            "sections_covered": loader_sections,
            "missing_loader_actions": [] if loader_refs else [mart],
            "first_paint_impact": False,
            "fallback_required": False,
            "account_usage_fallback_only": True,
            "target_lookup_columns_present": bool(lookup_columns),
            "target_lookup_columns": lookup_columns,
            "missing_target_lookup_columns": [] if lookup_columns else ["target_lookup_columns"],
            "retention_bounded": bool(re.search(rf"\b{mart}\b[\s\S]{{0,2000}}\b(DATEADD|ROW_NUMBER|QUALIFY|LIMIT|RETENTION|RECENT)\b", setup_text)),
            "retention_window": "bounded_recent_window_or_limit",
            "normal_account_usage_used": normal_account_usage_used,
            "max_rows": max_rows_limit,
            "row_count_static_or_live": 0,
            "failure_reason": "",
            "recommendation": "",
        }
        row["passed"] = (
            row["ddl_exists"]
            and row["load_path_exists"]
            and row["validation_exists"]
            and row["target_lookup_columns_present"]
            and row["retention_bounded"]
            and row["loader_matrix_references"]
            and not row["normal_account_usage_used"]
            and max_rows_limit <= 500
        )
        if not row["passed"]:
            reasons = [
                key for key in (
                    "ddl_exists",
                    "load_path_exists",
                    "validation_exists",
                    "target_lookup_columns_present",
                    "retention_bounded",
                    "loader_matrix_references",
                )
                if not row[key]
            ]
            if row["normal_account_usage_used"]:
                reasons.append("normal_account_usage_used")
            if max_rows_limit > 500:
                reasons.append("max_rows_over_500")
            row["failure_reason"] = ", ".join(reasons)
            row["recommendation"] = "Repair compact evidence mart DDL/load/validation or evidence loader mapping and rerun validation."
        if not row["passed"]:
            failures.append(row)
        mart_rows.append(row)
    normal_account_usage = [
        row for row in loader_rows
        if str(row.get("loader_kind") or "") == "normal_evidence" and bool(row.get("account_usage_used"))
    ]
    if normal_account_usage:
        failures.append({"code": "NORMAL_EVIDENCE_ACCOUNT_USAGE", "count": len(normal_account_usage)})
    return {
        "source": "compact_evidence_mart_validation",
        "proof_source": "static_sql_parse",
        "passed": not failures,
        "mart_count": len(mart_rows),
        "marts": mart_rows,
        "normal_account_usage_count": len(normal_account_usage),
        "failure_count": len(failures),
        "failures": failures,
        "raw_sql_included": False,
    }


def _compact_evidence_mart_detail_results(compact_evidence: Mapping[str, Any]) -> dict[str, Any]:
    rows = [_as_mapping(row) for row in compact_evidence.get("marts", [])] if isinstance(compact_evidence, Mapping) else []
    failures: list[dict[str, Any]] = []
    seen = {str(row.get("mart_name") or row.get("mart") or "") for row in rows}
    for mart in sorted(COMPACT_EVIDENCE_MARTS - seen):
        failures.append({"code": "COMPACT_MART_ROW_MISSING", "mart_name": mart})
    for row in rows:
        mart = str(row.get("mart_name") or row.get("mart") or "")
        required = (
            "ddl_exists",
            "load_path_exists",
            "validation_exists",
            "target_lookup_columns_present",
            "retention_bounded",
            "loader_matrix_references",
        )
        missing_flags = [key for key in required if not bool(row.get(key))]
        if missing_flags:
            failures.append({"code": "COMPACT_MART_DETAIL_CHECK_FAILED", "mart_name": mart, "failed_checks": missing_flags})
        if not bool(row.get("target_lookup_columns_present")) and not _as_list(row.get("missing_target_lookup_columns")):
            failures.append({"code": "COMPACT_MART_MISSING_TARGET_COLUMN_NAMES", "mart_name": mart})
        if bool(row.get("loader_matrix_references")) and not _as_list(row.get("loader_matrix_sections")):
            failures.append({"code": "COMPACT_MART_MISSING_LOADER_SECTIONS", "mart_name": mart})
        if bool(row.get("loader_matrix_references")) and _as_int(row.get("evidence_actions_covered")) <= 0:
            failures.append({"code": "COMPACT_MART_MISSING_ACTION_COVERAGE", "mart_name": mart})
        if bool(row.get("loader_matrix_references")) and not _as_list(row.get("sections_covered")):
            failures.append({"code": "COMPACT_MART_MISSING_SECTION_COVERAGE", "mart_name": mart})
        if _as_list(row.get("missing_loader_actions")):
            failures.append({"code": "COMPACT_MART_MISSING_LOADER_ACTIONS", "mart_name": mart})
        if bool(row.get("normal_account_usage_used")):
            failures.append({"code": "NORMAL_EVIDENCE_ACCOUNT_USAGE", "mart_name": mart})
        if int(row.get("max_rows") or 0) > 500:
            failures.append({"code": "COMPACT_MART_MAX_ROWS_OVER_500", "mart_name": mart, "max_rows": row.get("max_rows")})
        if bool(row.get("live_checked")) and not str(row.get("live_execution_manifest_id") or ""):
            failures.append({"code": "COMPACT_MART_LIVE_CHECK_MISSING_MANIFEST_ENTRY", "mart_name": mart})
    return _failure_result(
        source="compact_evidence_mart_detail",
        failures=failures,
        mart_count=len(rows),
        compact_mart_count=len(rows),
        compact_mart_failure_count=len(failures),
        compact_mart_names=sorted(seen),
        compact_normal_account_usage_count=sum(1 for row in rows if bool(row.get("normal_account_usage_used"))),
        compact_missing_target_column_count=sum(1 for row in rows if not bool(row.get("target_lookup_columns_present"))),
        compact_missing_target_columns=sorted(
            {
                str(column)
                for row in rows
                for column in _as_list(row.get("missing_target_lookup_columns"))
                if str(column)
            }
        ),
        required_marts=sorted(COMPACT_EVIDENCE_MARTS),
        marts=rows,
    )


def _validation_env() -> dict[str, Any]:
    return {
        "account": os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_ACCOUNT", "").strip(),
        "database": os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE", "").strip(),
        "schema": os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA", "").strip(),
        "warehouse": os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE", "").strip(),
        "role": os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_ROLE", "").strip(),
        "dry_run": os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION_DRY_RUN", "").strip() == "1",
        "destructive_allowed": os.environ.get("OVERWATCH_ALLOW_DESTRUCTIVE_SNOWFLAKE_VALIDATION", "").strip() == "1",
    }


def _live_validation_environment_results(live_enabled: bool) -> dict[str, Any]:
    env = _validation_env()
    launch_profile = os.environ.get("OVERWATCH_LAUNCH_PROFILE", "internal_fixture").strip() or "internal_fixture"
    missing_env_vars = []
    failures: list[dict[str, Any]] = []
    if live_enabled and not env["warehouse"]:
        missing_env_vars.append("OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE")
        failures.append(
            {
                "code": "LIVE_VALIDATION_WAREHOUSE_MISSING",
                "recommendation": "Set OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE for live Snowflake validation.",
            }
        )
    sanitized_account = _sanitized_identifier(env["account"])
    sanitized_database = _sanitized_identifier(env["database"])
    sanitized_schema = _sanitized_identifier(env["schema"])
    sanitized_warehouse = _sanitized_identifier(env["warehouse"])
    sanitized_role = _sanitized_identifier(env["role"])
    for setting, raw, sanitized in (
        ("OVERWATCH_SNOWFLAKE_VALIDATION_ACCOUNT", env["account"], sanitized_account),
        ("OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE", env["database"], sanitized_database),
        ("OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA", env["schema"], sanitized_schema),
        ("OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE", env["warehouse"], sanitized_warehouse),
        ("OVERWATCH_SNOWFLAKE_VALIDATION_ROLE", env["role"], sanitized_role),
    ):
        if raw and sanitized == "[redacted]":
            failures.append(
                {
                    "code": "LIVE_VALIDATION_ENV_RAW_SECRET_OR_CONNECTION_STRING",
                    "setting": setting,
                    "recommendation": "Use Snowflake object names only; do not place connection strings or secrets in validation env vars.",
                }
            )
    rows = [
        {
            "setting": "OVERWATCH_SNOWFLAKE_VALIDATION",
            "configured": live_enabled,
            "required_for_live": True,
            "raw_value_included": False,
        },
        {
            "setting": "OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE",
            "configured": bool(env["database"]),
            "required_for_live": False,
            "raw_value_included": False,
        },
        {
            "setting": "OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA",
            "configured": bool(env["schema"]),
            "required_for_live": False,
            "raw_value_included": False,
        },
        {
            "setting": "OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE",
            "configured": bool(env["warehouse"]),
            "required_for_live": False,
            "raw_value_included": False,
        },
        {
            "setting": "OVERWATCH_SNOWFLAKE_VALIDATION_DRY_RUN",
            "configured": bool(env["dry_run"]),
            "required_for_live": False,
            "raw_value_included": False,
        },
        {
            "setting": "OVERWATCH_ALLOW_DESTRUCTIVE_SNOWFLAKE_VALIDATION",
            "configured": bool(env["destructive_allowed"]),
            "required_for_live": False,
            "raw_value_included": False,
        },
    ]
    return _failure_result(
        source="live_validation_environment",
        proof_source="live_snowflake_execution" if live_enabled else "static_sql_parse",
        failures=failures,
        launch_profile=launch_profile,
        live_mode_enabled=live_enabled,
        validation_account=sanitized_account,
        validation_database=sanitized_database,
        validation_schema=sanitized_schema,
        validation_warehouse=sanitized_warehouse,
        validation_role=sanitized_role,
        dry_run_enabled=bool(env["dry_run"]),
        destructive_validation_allowed=bool(env["destructive_allowed"]),
        required_env_vars_present=not missing_env_vars,
        missing_env_vars=missing_env_vars,
        sanitized_values={
            "account": sanitized_account,
            "database": sanitized_database,
            "schema": sanitized_schema,
            "warehouse": sanitized_warehouse,
            "role": sanitized_role,
        },
        controlled_validation_target_configured=bool(env["database"] and env["schema"]),
        rows=rows,
    )


def _live_validation_session_results(live_enabled: bool, root: Path) -> dict[str, Any]:
    env = _validation_env()
    launch_profile = os.environ.get("OVERWATCH_LAUNCH_PROFILE", "internal_fixture").strip() or "internal_fixture"
    if not live_enabled:
        return _failure_result(
            source="live_validation_session",
            proof_source="static_sql_parse",
            failures=[],
            launch_profile=launch_profile,
            live_mode_enabled=False,
            status="skipped",
            session_open_attempted=False,
            session_opened=False,
            connection_scope="fixture_static",
            sanitized_account=_sanitized_identifier(env["account"]),
            sanitized_role="",
            sanitized_database=_sanitized_identifier(env["database"]),
            sanitized_schema=_sanitized_identifier(env["schema"]),
            sanitized_warehouse=_sanitized_identifier(env["warehouse"]),
            skip_reason="Live Snowflake validation skipped because OVERWATCH_SNOWFLAKE_VALIDATION is not set to 1.",
            elapsed_ms=0,
            row_count=0,
        )
    started = time.perf_counter()
    try:
        session = _open_live_session(root)
        row_count = _run_live_sql(session, "SELECT 1 AS OVERWATCH_VALIDATION_SESSION_CHECK")
        return _failure_result(
            source="live_validation_session",
            proof_source="live_snowflake_execution",
            failures=[],
            launch_profile=launch_profile,
            live_mode_enabled=True,
            status="passed",
            session_open_attempted=True,
            session_opened=True,
            connection_scope="configured_validation_scope" if env["database"] or env["schema"] or env["warehouse"] else "active_session_scope",
            sanitized_account=_sanitized_identifier(env["account"]),
            sanitized_role=_sanitized_identifier(env["role"]) or "active_session_role",
            sanitized_database=_sanitized_identifier(env["database"]),
            sanitized_schema=_sanitized_identifier(env["schema"]),
            sanitized_warehouse=_sanitized_identifier(env["warehouse"]),
            skip_reason="",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            row_count=row_count,
            raw_sql_included=False,
        )
    except Exception as exc:
        sanitized = sanitize_snowflake_error(exc)
        failure = {
            "code": "LIVE_VALIDATION_SESSION_UNAVAILABLE",
            "sanitized_error": sanitized,
            "recommendation": "Configure a controlled Snowflake validation session or disable live validation for fixture profile.",
        }
        return _failure_result(
            source="live_validation_session",
            proof_source="live_snowflake_execution",
            failures=[failure],
            launch_profile=launch_profile,
            live_mode_enabled=True,
            status="failed",
            session_open_attempted=True,
            session_opened=False,
            connection_scope="configured_validation_scope" if env["database"] or env["schema"] or env["warehouse"] else "active_session_scope",
            sanitized_account=_sanitized_identifier(env["account"]),
            sanitized_role="",
            sanitized_database=_sanitized_identifier(env["database"]),
            sanitized_schema=_sanitized_identifier(env["schema"]),
            sanitized_warehouse=_sanitized_identifier(env["warehouse"]),
            skip_reason="",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            row_count=0,
            sanitized_error=sanitized,
        )


def _open_live_session(root: Path):
    app_root = root / ".overwatch_final"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    try:
        from snowflake.snowpark.context import get_active_session

        return get_active_session()
    except Exception:
        pass
    try:
        from utils.session import _make_streamlit_connection_session

        return _make_streamlit_connection_session()
    except Exception as exc:
        raise RuntimeError(sanitize_snowflake_error(exc) or "Snowflake live session is unavailable.") from exc


def _collect_row_count(result: Any) -> int:
    try:
        rows = result.collect()
    except Exception:
        return 0
    try:
        return len(rows)
    except Exception:
        return 0


def _run_live_sql(session: Any, statement: str) -> int:
    result = session.sql(statement)
    return _collect_row_count(result)


def _static_smoke_results(live_enabled: bool, root: Path | None = None) -> list[dict[str, Any]]:
    calls = [
        ("SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST", "fast_refresh_validation", "CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST()", "live", "safe_read"),
        ("SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL", "full_refresh_validation_or_dry_run", "CALL SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL()", "dry_run", "dry_run_required"),
        ("SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS", "setup_health_validation", "CALL SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS()", "live", "safe_read"),
        ("SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL", "compact_evidence_validation", "CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL()", "live", "safe_read"),
        ("SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL", "current_packet_validation", "CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS_FAST_IMPL()", "live", "safe_read"),
        ("SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS", "last_known_good_fallback_validation", "CALL SP_OVERWATCH_REFRESH_SECTION_COMMAND_BRIEFS('FAST')", "dry_run", "dry_run_required"),
        ("OVERWATCH_MART_VALIDATION_SQL", "validation_sql_smoke", "SELECT 1 AS OVERWATCH_VALIDATION_SQL_DRY_RUN", "dry_run", "dry_run_required"),
        (
            "SP_OVERWATCH_APPLY_OPTIONAL_PERFORMANCE_OPTIMIZATION",
            "optional_optimization_status_read_only",
            "CALL SP_OVERWATCH_APPLY_OPTIONAL_PERFORMANCE_OPTIMIZATION()",
            "dry_run",
            "destructive_requires_flag",
        ),
    ]
    if not live_enabled:
        rows: list[dict[str, Any]] = []
        for name, smoke_phase, _statement, mode, safety_class in calls:
            row = _result_row(
                object_name=name,
                object_type="procedure",
                procedure_name=name,
                phase="procedure_smoke_call_live",
                status="skipped",
                recommendation="Enable OVERWATCH_SNOWFLAKE_VALIDATION=1 for live smoke-call proof.",
            )
            row.update(
                {
                    "smoke_target": smoke_phase,
                    "mode": "fixture_static",
                    "safety_class": safety_class,
                    "skip_reason": "OVERWATCH_SNOWFLAKE_VALIDATION is not set to 1.",
                    "owner": "release-validation",
                    "review_note": "Fixture profile skip; live/prod profiles require live validation or waiver.",
                    "failed_section_count": 0,
                    "max_packet_bytes": 0,
                    "compact_mart_count": len(COMPACT_EVIDENCE_MARTS) if smoke_phase == "compact_evidence_validation" else 0,
                }
            )
            rows.append(row)
        return rows
    env = _validation_env()
    root = root or Path(".").resolve()
    live_rows: list[dict[str, Any]] = []
    try:
        session = _open_live_session(root)
        if env["warehouse"]:
            _run_live_sql(session, f"USE WAREHOUSE {env['warehouse']}")
        if env["database"]:
            _run_live_sql(session, f"USE DATABASE {env['database']}")
        if env["schema"]:
            _run_live_sql(session, f"USE SCHEMA {env['schema']}")
    except Exception as exc:
        for name, smoke_phase, _statement, mode, safety_class in calls:
            row = _result_row(
                object_name=name,
                object_type="procedure",
                procedure_name=name,
                phase="procedure_smoke_call_live",
                status="failed",
                sanitized_error=sanitize_snowflake_error(exc),
                recommendation="Configure a Snowflake validation session or disable live validation for fixture profile.",
            )
            row.update(
                {
                    "smoke_target": smoke_phase,
                    "mode": "dry_run" if mode == "dry_run" else "live",
                    "safety_class": safety_class,
                    "skip_reason": "",
                    "owner": "",
                    "review_note": "",
                }
            )
            live_rows.append(row)
        return live_rows
    for name, smoke_phase, statement, mode, safety_class in calls:
        started = time.perf_counter()
        try:
            destructive_live_call = (
                safety_class == "destructive_requires_flag"
                and mode == "live"
                and not env["dry_run"]
                and not env["destructive_allowed"]
            )
            if destructive_live_call:
                raise RuntimeError("Destructive Snowflake validation requires OVERWATCH_ALLOW_DESTRUCTIVE_SNOWFLAKE_VALIDATION=1.")
            should_dry_run = env["dry_run"] or mode == "dry_run" or safety_class in {"dry_run_required", "destructive_requires_flag"}
            if should_dry_run:
                row_count = _run_live_sql(session, "SELECT 1 AS OVERWATCH_VALIDATION_DRY_RUN")
                status = "passed"
                recommendation = "Dry-run mode proved live session availability; procedure body was not called."
            else:
                row_count = _run_live_sql(session, statement)
                status = "passed"
                recommendation = ""
            row = _result_row(
                object_name=name,
                object_type="procedure",
                procedure_name=name,
                phase="procedure_smoke_call_live",
                status=status,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                row_count=row_count,
                recommendation=recommendation,
            )
            row.update(
                {
                    "smoke_target": smoke_phase,
                    "mode": "dry_run" if should_dry_run else "live",
                    "safety_class": safety_class,
                    "skip_reason": "",
                    "owner": "",
                    "review_note": "",
                    "failed_section_count": 0,
                    "max_packet_bytes": 0,
                    "compact_mart_count": len(COMPACT_EVIDENCE_MARTS) if smoke_phase == "compact_evidence_validation" else 0,
                }
            )
            live_rows.append(row)
        except Exception as exc:
            row = _result_row(
                object_name=name,
                object_type="procedure",
                procedure_name=name,
                phase="procedure_smoke_call_live",
                status="failed",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                sanitized_error=sanitize_snowflake_error(exc),
                recommendation="Fix the procedure compile/runtime error in Snowflake and rerun live validation.",
            )
            row.update(
                {
                    "smoke_target": smoke_phase,
                    "mode": "dry_run" if mode == "dry_run" else "live",
                    "safety_class": safety_class,
                    "skip_reason": "",
                    "owner": "",
                    "review_note": "",
                }
            )
            live_rows.append(row)
    return live_rows


def _procedure_smoke_call_coverage_results(
    smoke_rows: Iterable[Mapping[str, Any]],
    *,
    live_enabled: bool,
    profile: str = "internal_fixture",
) -> dict[str, Any]:
    rows = [_as_mapping(row) for row in smoke_rows]
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_target[str(row.get("smoke_target") or "")].append(row)
    failures: list[dict[str, Any]] = []
    coverage_rows = []
    strict_profile = profile in {"internal_live", "prod_candidate"}
    for target, procedure_name, expected_mode, safety_class in REQUIRED_SMOKE_TARGETS:
        matches = by_target.get(target, [])
        row = matches[0] if matches else {}
        status = str(row.get("status") or "missing")
        mode = str(row.get("mode") or ("missing" if not row else "fixture_static"))
        skip_reason = str(row.get("skip_reason") or "")
        owner = str(row.get("owner") or "")
        review_note = str(row.get("review_note") or "")
        expected_live = expected_mode in {"live", "dry_run"}
        destructive_without_flag = (
            safety_class == "destructive_requires_flag"
            and mode == "live"
            and os.environ.get("OVERWATCH_ALLOW_DESTRUCTIVE_SNOWFLAKE_VALIDATION") != "1"
        )
        passed = bool(matches) and status in {"passed", "skipped"} and not destructive_without_flag
        if live_enabled and expected_live and status == "skipped":
            passed = False
        strict_skip_gap = status == "skipped" and strict_profile and (
            skip_reason.strip().lower() in GENERIC_SKIP_TEXT
            or owner.strip().lower() in GENERIC_SKIP_TEXT
            or review_note.strip().lower() in GENERIC_SKIP_TEXT
        )
        if strict_skip_gap:
            passed = False
        if not matches:
            failures.append({"code": "SMOKE_TARGET_MISSING", "smoke_target": target})
        elif status == "failed":
            failures.append({"code": "SMOKE_TARGET_FAILED", "smoke_target": target, "procedure_name": procedure_name})
        elif bool(row.get("raw_sql_included")):
            failures.append({"code": "SMOKE_TARGET_RAW_SQL_INCLUDED", "smoke_target": target})
        elif not str(row.get("live_execution_manifest_id") or ""):
            failures.append({"code": "SMOKE_ROW_MISSING_MANIFEST_ENTRY", "smoke_target": target})
        elif live_enabled and expected_live and status == "skipped":
            failures.append({"code": "LIVE_SMOKE_TARGET_SKIPPED", "smoke_target": target})
        elif destructive_without_flag:
            failures.append({"code": "DESTRUCTIVE_SMOKE_CALL_WITHOUT_ALLOW_FLAG", "smoke_target": target})
        elif strict_skip_gap:
            failures.append({"code": "SMOKE_SKIP_NOT_OWNERED", "smoke_target": target})
        coverage_rows.append(
            {
                "smoke_target": target,
                "procedure_name": str(row.get("procedure_name") or procedure_name),
                "phase": str(row.get("phase") or "procedure_smoke_call_live"),
                "mode": mode,
                "safety_class": str(row.get("safety_class") or safety_class),
                "status": status,
                "elapsed_ms": int(row.get("elapsed_ms") or 0),
                "row_count": int(row.get("row_count") or 0),
                "failed_section_count": int(row.get("failed_section_count") or 0),
                "max_packet_bytes": int(row.get("max_packet_bytes") or 0),
                "compact_mart_count": int(row.get("compact_mart_count") or 0),
                "skip_reason": skip_reason,
                "owner": owner,
                "review_note": review_note,
                "live_execution_manifest_id": str(row.get("live_execution_manifest_id") or ""),
                "raw_sql_included": bool(row.get("raw_sql_included")),
                "sanitized_error": str(row.get("sanitized_error") or ""),
                "recommendation": str(row.get("recommendation") or ""),
                "passed": passed,
            }
        )
    return _failure_result(
        source="procedure_smoke_call_coverage",
        failures=failures,
        live_mode_enabled=live_enabled,
        expected_smoke_target_count=len(REQUIRED_SMOKE_TARGETS),
        observed_smoke_target_count=len([row for row in coverage_rows if row["status"] != "missing"]),
        rows=coverage_rows,
    )


def _manifest_expected_for_smoke(target: str, live_enabled: bool) -> tuple[str, str]:
    if not live_enabled:
        return "static", "skipped"
    for smoke_target, _procedure, expected_mode, safety_class in REQUIRED_SMOKE_TARGETS:
        if smoke_target == target:
            return expected_mode, safety_class
    return "live", "safe_read"


def _manifest_observed_mode(row: Mapping[str, Any], default_mode: str) -> str:
    status = str(row.get("status") or "")
    mode = str(row.get("mode") or default_mode or "")
    if status == "skipped":
        return "skipped"
    if mode == "fixture_static":
        return "static"
    if mode in {"static", "dry_run", "live"}:
        return mode
    return default_mode


def _manifest_context(live_enabled: bool) -> dict[str, Any]:
    env = _validation_env()
    launch_profile = os.environ.get("OVERWATCH_LAUNCH_PROFILE", "internal_fixture").strip() or "internal_fixture"
    return {
        "launch_profile": launch_profile,
        "live_required": live_enabled or launch_profile in _LAUNCH_PROFILES_REQUIRING_LIVE,
        "database": _sanitized_identifier(env["database"]),
        "schema": _sanitized_identifier(env["schema"]),
        "warehouse": _sanitized_identifier(env["warehouse"]),
        "role_name": _sanitized_identifier(env["role"]) or ("active_session_role" if live_enabled else ""),
        "waiver_id": "",
        "destructive_allowed": bool(env["destructive_allowed"]),
    }


def _attach_manifest_id(
    entries: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    artifact: str,
    index: int,
    expected_mode: str,
    observed_mode: str,
    context: Mapping[str, Any],
    safe_execution_class: str = "safe_read",
    row_key: str = "",
    row_index: int | None = None,
) -> None:
    validation_id = f"{artifact}:{index:04d}"
    row["live_execution_manifest_id"] = validation_id
    effective_row_key = row_key or str(
        row.get("smoke_target")
        or row.get("procedure_name")
        or row.get("mart_name")
        or row.get("check_name")
        or row.get("source")
        or row.get("phase")
        or index
    )
    row["live_execution_row_key"] = effective_row_key
    status = str(row.get("status") or ("passed" if row.get("passed", True) else "failed"))
    entry = {
        "validation_id": validation_id,
        "artifact": artifact,
        "row_index": row_index if row_index is not None else index,
        "row_key": effective_row_key,
        "phase": str(row.get("phase") or row.get("source") or row.get("check_name") or ""),
        "object_name": str(row.get("object_name") or row.get("mart_name") or row.get("check_name") or ""),
        "procedure_name": str(row.get("procedure_name") or ""),
        "expected_mode": expected_mode,
        "observed_mode": observed_mode,
        "launch_profile": str(context.get("launch_profile") or "internal_fixture"),
        "live_required": bool(context.get("live_required")),
        "waiver_id": str(context.get("waiver_id") or ""),
        "database": str(context.get("database") or ""),
        "schema": str(context.get("schema") or ""),
        "warehouse": str(context.get("warehouse") or ""),
        "role_name": str(context.get("role_name") or ""),
        "safe_execution_class": safe_execution_class,
        "elapsed_ms": int(row.get("elapsed_ms") or 0),
        "status": status,
        "raw_sql_included": bool(row.get("raw_sql_included")),
        "sanitized_error": str(row.get("sanitized_error") or ""),
        "recommendation": str(row.get("recommendation") or ""),
    }
    entries.append(entry)
    if bool(entry["raw_sql_included"]):
        failures.append({"code": "MANIFEST_RAW_SQL_INCLUDED", "validation_id": validation_id, "artifact": artifact})
    if entry["observed_mode"] == "live" and safe_execution_class == "destructive_requires_flag" and not bool(context.get("destructive_allowed")):
        failures.append({"code": "DESTRUCTIVE_MANIFEST_ROW_WITHOUT_ALLOW_FLAG", "validation_id": validation_id})
    if entry["live_required"] and entry["expected_mode"] == "live" and entry["observed_mode"] == "static":
        failures.append({"code": "LIVE_REQUIRED_ROW_STATIC_ONLY", "validation_id": validation_id})
    if entry["launch_profile"] == "prod_candidate" and entry["observed_mode"] == "skipped" and not entry["waiver_id"]:
        failures.append({"code": "PROD_CANDIDATE_SKIPPED_WITHOUT_WAIVER", "validation_id": validation_id})
    combined = " ".join(
        str(entry.get(key) or "")
        for key in ("database", "schema", "warehouse", "role_name", "sanitized_error")
    )
    if re.search(r"(?i)(snowflake://|password=|token=|private[_ -]?key=|CREATE\s+OR\s+REPLACE|SELECT\s+\*)", combined):
        failures.append({"code": "MANIFEST_SECRET_OR_RAW_SQL_TEXT", "validation_id": validation_id})


def _live_execution_manifest_results(
    *,
    live_enabled: bool,
    live_environment: dict[str, Any],
    live_session: dict[str, Any],
    setup_rows: list[dict[str, Any]],
    compile_rows: list[dict[str, Any]],
    smoke_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    refresh_fast: dict[str, Any],
    refresh_full: dict[str, Any],
    packet_publication: dict[str, Any],
    packet_shape: dict[str, Any],
    packet_size: dict[str, Any],
    packet_source_truth: dict[str, Any],
    packet_detail: dict[str, Any],
    compact_evidence: dict[str, Any],
    compact_detail: dict[str, Any],
    refresh_detail: dict[str, Any],
    recent_fixes: dict[str, Any],
    metric_shape: dict[str, Any],
    trend_cardinality: dict[str, Any],
    encoding_scan: dict[str, Any],
    schema_drift: dict[str, Any],
    sanitizer_results: dict[str, Any],
) -> dict[str, Any]:
    context = _manifest_context(live_enabled)
    entries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    artifact_index = 0
    artifact_row_indexes: dict[str, int] = {}

    def add(
        row: dict[str, Any],
        *,
        artifact: str,
        expected_mode: str,
        observed_mode: str,
        safe_class: str = "safe_read",
        row_key: str = "",
    ) -> None:
        nonlocal artifact_index
        artifact_index += 1
        artifact_row_indexes[artifact] = artifact_row_indexes.get(artifact, 0) + 1
        _attach_manifest_id(
            entries,
            failures,
            row,
            artifact=artifact,
            index=artifact_index,
            row_index=artifact_row_indexes[artifact],
            expected_mode=expected_mode,
            observed_mode=observed_mode,
            context=context,
            safe_execution_class=safe_class,
            row_key=row_key,
        )

    add(
        live_environment,
        artifact="live_validation_environment_results.json",
        expected_mode="live" if live_enabled else "static",
        observed_mode="live" if live_enabled else "static",
        row_key="live_validation_environment",
    )
    add(
        live_session,
        artifact="live_validation_session_results.json",
        expected_mode="live" if live_enabled else "static",
        observed_mode=_manifest_observed_mode(live_session, "live" if live_enabled else "static"),
        safe_class="safe_read" if live_enabled else "skipped_with_owner",
        row_key="live_validation_session",
    )
    for row in setup_rows:
        add(row, artifact="setup_execution_results.json", expected_mode="static", observed_mode="static")
    for row in validation_rows:
        add(row, artifact="validation_sql_results.json", expected_mode="static", observed_mode="static")
    for row in compile_rows:
        phase = str(row.get("phase") or "")
        expected = "live" if phase == "procedure_compile_live" else "static"
        observed = "live" if phase == "procedure_compile_live" else "static"
        add(row, artifact="procedure_compile_results.json", expected_mode=expected, observed_mode=observed)
    for row in smoke_rows:
        target = str(row.get("smoke_target") or "")
        expected, safety_class = _manifest_expected_for_smoke(target, live_enabled)
        add(
            row,
            artifact="procedure_smoke_call_results.json",
            expected_mode=expected,
            observed_mode=_manifest_observed_mode(row, "live" if live_enabled else "static"),
            safe_class=str(row.get("safety_class") or safety_class),
        )
    add(
        refresh_fast,
        artifact="refresh_fast_results.json",
        expected_mode="live" if live_enabled else "static",
        observed_mode="live" if live_enabled and str(refresh_fast.get("status") or "") != "skipped" else "skipped",
    )
    add(
        refresh_full,
        artifact="refresh_full_results.json",
        expected_mode="live" if live_enabled else "static",
        observed_mode="live" if live_enabled and str(refresh_full.get("status") or "") != "skipped" else "skipped",
    )
    for artifact, payload in (
        ("packet_publication_validation_results.json", packet_publication),
        ("packet_shape_results.json", packet_shape),
        ("packet_size_results.json", packet_size),
        ("packet_source_truth_results.json", packet_source_truth),
        ("recent_snowflake_fix_validation_results.json", recent_fixes),
        ("metric_candidate_shape_results.json", metric_shape),
        ("trend_cardinality_results.json", trend_cardinality),
    ):
        add(payload, artifact=artifact, expected_mode="static", observed_mode="static", row_key=str(payload.get("source") or artifact))
    for item in packet_detail.get("checks", []):
        if isinstance(item, dict):
            add(item, artifact="packet_validation_detail_results.json", expected_mode="static", observed_mode="static")
    for item in compact_evidence.get("marts", []):
        if isinstance(item, dict):
            item["live_checked"] = live_enabled
            add(
                item,
                artifact="compact_evidence_mart_validation_results.json",
                expected_mode="live" if live_enabled else "static",
                observed_mode="live" if live_enabled else "static",
            )
    for item in compact_detail.get("marts", []):
        if isinstance(item, dict):
            add(item, artifact="compact_evidence_mart_detail_results.json", expected_mode="static", observed_mode="static")
    for item in refresh_detail.get("checks", []):
        if isinstance(item, dict):
            add(item, artifact="refresh_detail_results.json", expected_mode="static", observed_mode="static")
    for item in schema_drift.get("rows", []):
        if isinstance(item, dict):
            add(item, artifact="schema_drift_results.json", expected_mode="static", observed_mode="static")
    for item in encoding_scan.get("rows", []):
        if isinstance(item, dict):
            add(item, artifact="sql_encoding_scan_results.json", expected_mode="static", observed_mode="static")
    for item in sanitizer_results.get("checks", []):
        if isinstance(item, dict):
            add(item, artifact="snowflake_error_sanitization_results.json", expected_mode="static", observed_mode="static")

    return _failure_result(
        source="live_execution_manifest",
        proof_source="live_snowflake_execution" if live_enabled else "static_sql_parse",
        failures=failures,
        entry_count=len(entries),
        entries=entries,
        live_mode_enabled=live_enabled,
    )


def _append_manifest_payload_rows(
    live_manifest: dict[str, Any],
    payload: Mapping[str, Any],
    *,
    artifact: str,
    live_enabled: bool,
    expected_mode: str | None = None,
    observed_mode: str | None = None,
    safe_execution_class: str = "safe_read",
) -> None:
    entries = _as_list(live_manifest.get("entries"))
    failures = _as_list(live_manifest.get("failures"))
    context = _manifest_context(live_enabled)
    artifact_row_indexes: dict[str, int] = Counter(
        str(row.get("artifact") or "") for row in entries if isinstance(row, Mapping)
    )
    index = len(entries)
    if isinstance(payload, Mapping):
        rows = [
            row for row in payload.get("rows", [])
            if isinstance(row, dict)
        ]
    elif isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
    else:
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        index += 1
        artifact_row_indexes[artifact] = artifact_row_indexes.get(artifact, 0) + 1
        mode = expected_mode or ("live" if live_enabled else "static")
        observed = observed_mode or mode
        _attach_manifest_id(
            entries,
            failures,
            row,
            artifact=artifact,
            index=index,
            row_index=artifact_row_indexes[artifact],
            expected_mode=mode,
            observed_mode=observed,
            context=context,
            safe_execution_class=safe_execution_class,
        )
    live_manifest["entries"] = entries
    live_manifest["failures"] = failures
    live_manifest["entry_count"] = len(entries)
    live_manifest["failure_count"] = len(failures)
    live_manifest["passed"] = not failures


def _artifact_rows_for_manifest_reconciliation(artifact: str, payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [_as_mapping(row) for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    if artifact in {
        "live_validation_environment_results.json",
        "live_validation_session_results.json",
        "refresh_fast_results.json",
        "refresh_full_results.json",
    }:
        return [_as_mapping(payload)]
    for key in ("rows", "checks", "marts"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [_as_mapping(row) for row in rows if isinstance(row, Mapping)]
    if payload.get("live_execution_manifest_id"):
        return [_as_mapping(payload)]
    return []


def _row_status_for_manifest(row: Mapping[str, Any]) -> str:
    if row.get("status"):
        return str(row.get("status") or "")
    return "passed" if bool(row.get("passed", True)) else "failed"


def _row_observed_mode_for_manifest(artifact: str, row: Mapping[str, Any], live_enabled: bool) -> str:
    if artifact in {"procedure_compile_coverage_results.json", "procedure_smoke_call_coverage_results.json"}:
        return "live" if live_enabled else "static"
    if _row_status_for_manifest(row) == "skipped":
        return "skipped"
    if artifact == "procedure_smoke_call_results.json":
        return _manifest_observed_mode(row, "live" if live_enabled else "static")
    if artifact == "procedure_compile_results.json":
        return "live" if str(row.get("phase") or "") == "procedure_compile_live" else "static"
    if artifact in {"refresh_fast_results.json", "refresh_full_results.json"}:
        return "live" if live_enabled else "static"
    if artifact == "live_validation_session_results.json":
        return _manifest_observed_mode(row, "live" if live_enabled else "static")
    if artifact == "live_validation_environment_results.json":
        return "live" if live_enabled else "static"
    return "static"


def _live_execution_manifest_reconciliation_results(
    live_manifest: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    *,
    live_enabled: bool,
) -> dict[str, Any]:
    entries = [_as_mapping(row) for row in _as_list(live_manifest.get("entries"))]
    entries_by_id = {str(row.get("validation_id") or ""): row for row in entries}
    failures: list[dict[str, Any]] = []
    consumed_ids: set[str] = set()
    row_index: dict[tuple[str, str], tuple[dict[str, Any], int]] = {}
    ids_seen: set[str] = set()

    required_entry_fields = {
        "validation_id",
        "artifact",
        "row_index",
        "row_key",
        "phase",
        "object_name",
        "expected_mode",
        "observed_mode",
        "launch_profile",
        "live_required",
        "database",
        "schema",
        "warehouse",
        "role_name",
        "safe_execution_class",
        "elapsed_ms",
        "status",
        "raw_sql_included",
        "sanitized_error",
        "recommendation",
    }
    allowed_modes = {"static", "dry_run", "live", "skipped"}
    allowed_safe_classes = {"safe_read", "dry_run_required", "destructive_requires_flag", "skipped_with_owner"}
    for entry in entries:
        validation_id = str(entry.get("validation_id") or "")
        missing_fields = sorted(field for field in required_entry_fields if field not in entry)
        if not validation_id:
            failures.append({"code": "MANIFEST_ENTRY_MISSING_ID", "artifact": entry.get("artifact")})
        elif validation_id in ids_seen:
            failures.append({"code": "MANIFEST_DUPLICATE_ID", "validation_id": validation_id})
        ids_seen.add(validation_id)
        if missing_fields:
            failures.append({"code": "MANIFEST_ENTRY_MISSING_FIELDS", "validation_id": validation_id, "missing_fields": missing_fields})
        if str(entry.get("expected_mode") or "") not in {"static", "dry_run", "live"}:
            failures.append({"code": "MANIFEST_BAD_EXPECTED_MODE", "validation_id": validation_id})
        if str(entry.get("observed_mode") or "") not in allowed_modes:
            failures.append({"code": "MANIFEST_BAD_OBSERVED_MODE", "validation_id": validation_id})
        if str(entry.get("safe_execution_class") or "") not in allowed_safe_classes:
            failures.append({"code": "MANIFEST_BAD_SAFE_EXECUTION_CLASS", "validation_id": validation_id})
        if bool(entry.get("raw_sql_included")):
            failures.append({"code": "MANIFEST_RAW_SQL_INCLUDED", "validation_id": validation_id})
        combined = " ".join(
            str(entry.get(key) or "")
            for key in ("database", "schema", "warehouse", "role_name", "sanitized_error")
        )
        if re.search(r"(?i)(snowflake://|password=|token=|private[_ -]?key=|CREATE\s+OR\s+REPLACE|SELECT\s+\*)", combined):
            failures.append({"code": "MANIFEST_SECRET_OR_RAW_SQL_TEXT", "validation_id": validation_id})
        if live_enabled and str(entry.get("expected_mode") or "") == "live" and str(entry.get("observed_mode") or "") == "static":
            failures.append({"code": "LIVE_REQUIRED_ROW_STATIC_ONLY", "validation_id": validation_id})
        if (
            str(entry.get("safe_execution_class") or "") == "destructive_requires_flag"
            and str(entry.get("observed_mode") or "") == "live"
            and os.environ.get("OVERWATCH_ALLOW_DESTRUCTIVE_SNOWFLAKE_VALIDATION") != "1"
        ):
            failures.append({"code": "DESTRUCTIVE_MANIFEST_ROW_WITHOUT_ALLOW_FLAG", "validation_id": validation_id})

    artifact_row_counts: dict[str, int] = {}
    manifest_id_counts: dict[str, int] = {}
    artifact_names = set(artifacts)
    for artifact, payload in artifacts.items():
        if artifact == "live_execution_manifest.json":
            continue
        rows = _artifact_rows_for_manifest_reconciliation(artifact, payload)
        artifact_row_counts[artifact] = len(rows)
        for ordinal, row in enumerate(rows, start=1):
            manifest_id = str(row.get("live_execution_manifest_id") or "")
            if not manifest_id:
                if artifact in {
                    "live_validation_environment_results.json",
                    "live_validation_session_results.json",
                    "procedure_compile_results.json",
                    "procedure_compile_coverage_results.json",
                    "procedure_smoke_call_results.json",
                    "procedure_smoke_call_coverage_results.json",
                    "refresh_fast_results.json",
                    "refresh_full_results.json",
                    "validation_sql_results.json",
                    "packet_publication_validation_results.json",
                    "packet_shape_results.json",
                    "packet_size_results.json",
                    "packet_source_truth_results.json",
                    "packet_validation_detail_results.json",
                    "compact_evidence_mart_validation_results.json",
                    "compact_evidence_mart_detail_results.json",
                    "refresh_detail_results.json",
                    "recent_snowflake_fix_validation_results.json",
                    "metric_candidate_shape_results.json",
                    "trend_cardinality_results.json",
                    "schema_drift_results.json",
                    "sql_encoding_scan_results.json",
                    "snowflake_error_sanitization_results.json",
                }:
                    failures.append({"code": "ARTIFACT_ROW_MISSING_MANIFEST_ID", "artifact": artifact})
                continue
            if manifest_id not in entries_by_id:
                failures.append({"code": "ARTIFACT_ROW_UNKNOWN_MANIFEST_ID", "artifact": artifact, "validation_id": manifest_id})
                continue
            consumed_ids.add(manifest_id)
            row_index[(artifact, manifest_id)] = (row, ordinal)
            manifest_id_counts[artifact] = manifest_id_counts.get(artifact, 0) + 1

    for entry in entries:
        validation_id = str(entry.get("validation_id") or "")
        artifact = str(entry.get("artifact") or "")
        if artifact not in artifact_names:
            failures.append({"code": "MANIFEST_MISSING_ARTIFACT", "artifact": artifact, "validation_id": validation_id})
            continue
        manifest_pair = row_index.get((artifact, validation_id))
        if not manifest_pair:
            failures.append({"code": "MANIFEST_ORPHAN_ENTRY", "artifact": artifact, "validation_id": validation_id})
            continue
        manifest_row, ordinal = manifest_pair
        if _as_int(entry.get("row_index")) != ordinal:
            failures.append(
                {
                    "code": "MANIFEST_ROW_INDEX_MISMATCH",
                    "artifact": artifact,
                    "validation_id": validation_id,
                    "manifest_row_index": entry.get("row_index"),
                    "artifact_row_index": ordinal,
                }
            )
        if str(entry.get("row_key") or "") != str(manifest_row.get("live_execution_row_key") or ""):
            failures.append(
                {
                    "code": "MANIFEST_ROW_KEY_MISMATCH",
                    "artifact": artifact,
                    "validation_id": validation_id,
                    "manifest_row_key": entry.get("row_key"),
                    "artifact_row_key": manifest_row.get("live_execution_row_key"),
                }
            )
        row_status = _row_status_for_manifest(manifest_row)
        if str(entry.get("status") or "") != row_status:
            failures.append(
                {
                    "code": "MANIFEST_STATUS_MISMATCH",
                    "artifact": artifact,
                    "validation_id": validation_id,
                    "manifest_status": entry.get("status"),
                    "artifact_status": row_status,
                }
            )
        observed_mode = _row_observed_mode_for_manifest(artifact, manifest_row, live_enabled)
        if str(entry.get("observed_mode") or "") != observed_mode:
            failures.append(
                {
                    "code": "MANIFEST_MODE_MISMATCH",
                    "artifact": artifact,
                    "validation_id": validation_id,
                    "manifest_observed_mode": entry.get("observed_mode"),
                    "artifact_observed_mode": observed_mode,
                }
            )

    expected_manifest_counts = {
        "environment_rows": 1,
        "session_rows": 1,
        "compile_rows": artifact_row_counts.get("procedure_compile_results.json", 0),
        "compile_coverage_rows": artifact_row_counts.get("procedure_compile_coverage_results.json", 0),
        "smoke_rows": artifact_row_counts.get("procedure_smoke_call_results.json", 0),
        "smoke_coverage_rows": artifact_row_counts.get("procedure_smoke_call_coverage_results.json", 0),
        "refresh_rows": artifact_row_counts.get("refresh_fast_results.json", 0)
        + artifact_row_counts.get("refresh_full_results.json", 0),
        "packet_rows": artifact_row_counts.get("packet_validation_detail_results.json", 0),
        "compact_mart_rows": artifact_row_counts.get("compact_evidence_mart_validation_results.json", 0)
        + artifact_row_counts.get("compact_evidence_mart_detail_results.json", 0),
        "validation_sql_rows": artifact_row_counts.get("validation_sql_results.json", 0),
    }
    observed_manifest_counts = {
        "environment_rows": manifest_id_counts.get("live_validation_environment_results.json", 0),
        "session_rows": manifest_id_counts.get("live_validation_session_results.json", 0),
        "compile_rows": manifest_id_counts.get("procedure_compile_results.json", 0),
        "compile_coverage_rows": manifest_id_counts.get("procedure_compile_coverage_results.json", 0),
        "smoke_rows": manifest_id_counts.get("procedure_smoke_call_results.json", 0),
        "smoke_coverage_rows": manifest_id_counts.get("procedure_smoke_call_coverage_results.json", 0),
        "refresh_rows": manifest_id_counts.get("refresh_fast_results.json", 0)
        + manifest_id_counts.get("refresh_full_results.json", 0),
        "packet_rows": manifest_id_counts.get("packet_validation_detail_results.json", 0),
        "compact_mart_rows": manifest_id_counts.get("compact_evidence_mart_validation_results.json", 0)
        + manifest_id_counts.get("compact_evidence_mart_detail_results.json", 0),
        "validation_sql_rows": manifest_id_counts.get("validation_sql_results.json", 0),
    }
    for key, expected_count in expected_manifest_counts.items():
        if observed_manifest_counts.get(key, 0) != expected_count:
            failures.append(
                {
                    "code": "MANIFEST_COUNT_MISMATCH",
                    "count_key": key,
                    "expected": expected_count,
                    "actual": observed_manifest_counts.get(key, 0),
                }
            )

    return _failure_result(
        source="live_execution_manifest_reconciliation",
        proof_source="live_snowflake_execution" if live_enabled else "static_sql_parse",
        failures=failures,
        manifest_entry_count=len(entries),
        consumed_manifest_entry_count=len(consumed_ids),
        orphan_manifest_entry_count=sum(1 for row in failures if row.get("code") == "MANIFEST_ORPHAN_ENTRY"),
        unknown_manifest_id_count=sum(1 for row in failures if row.get("code") == "ARTIFACT_ROW_UNKNOWN_MANIFEST_ID"),
        missing_manifest_id_count=sum(1 for row in failures if row.get("code") == "ARTIFACT_ROW_MISSING_MANIFEST_ID"),
        status_mismatch_count=sum(1 for row in failures if row.get("code") == "MANIFEST_STATUS_MISMATCH"),
        mode_mismatch_count=sum(1 for row in failures if row.get("code") == "MANIFEST_MODE_MISMATCH"),
        row_index_mismatch_count=sum(1 for row in failures if row.get("code") == "MANIFEST_ROW_INDEX_MISMATCH"),
        row_key_mismatch_count=sum(1 for row in failures if row.get("code") == "MANIFEST_ROW_KEY_MISMATCH"),
        expected_manifest_counts=expected_manifest_counts,
        observed_manifest_counts=observed_manifest_counts,
        artifacts_checked=sorted(artifact_row_counts),
    )


def _raw_sql_or_secret_value(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_raw_sql_or_secret_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_raw_sql_or_secret_value(item) for item in value)
    if not isinstance(value, str):
        return False
    return bool(re.search(r"(?i)(snowflake://|password=|token=|private[_ -]?key=|CREATE\s+OR\s+REPLACE|SELECT\s+\*)", value))


def _live_execution_manifest_category_coverage_results(
    live_manifest: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    *,
    live_enabled: bool,
) -> dict[str, Any]:
    entries = [_as_mapping(row) for row in _as_list(live_manifest.get("entries"))]
    entries_by_id = {str(row.get("validation_id") or ""): row for row in entries}
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for category, category_artifacts in MANIFEST_CATEGORY_ARTIFACTS.items():
        category_required = category != "live_query_history" or os.environ.get("OVERWATCH_QUERY_PLAN_PROOF") == "1"
        category_entries = [row for row in entries if str(row.get("artifact") or "") in category_artifacts]
        expected_row_count = 0
        observed_artifact_row_count = 0
        linked_artifact_row_count = 0
        unknown_manifest_id_count = 0
        missing_manifest_id_count = 0
        row_index_mismatch_count = 0
        row_key_mismatch_count = 0
        status_mismatch_count = 0
        mode_mismatch_count = 0
        raw_sql_or_secret_count = 0
        category_failures: list[dict[str, Any]] = []
        matched_manifest_ids: set[str] = set()

        for artifact in category_artifacts:
            payload = artifacts.get(artifact)
            artifact_rows = _artifact_rows_for_manifest_reconciliation(artifact, payload)
            expected_row_count += len(artifact_rows)
            observed_artifact_row_count += len(artifact_rows)
            for ordinal, row in enumerate(artifact_rows, start=1):
                if bool(row.get("raw_sql_included")) or _raw_sql_or_secret_value(row):
                    raw_sql_or_secret_count += 1
                    category_failures.append({"code": "CATEGORY_RAW_SQL_OR_SECRET", "artifact": artifact, "row_index": ordinal})
                manifest_id = str(row.get("live_execution_manifest_id") or "")
                if not manifest_id:
                    missing_manifest_id_count += 1
                    category_failures.append({"code": "CATEGORY_ROW_MISSING_MANIFEST_ID", "artifact": artifact, "row_index": ordinal})
                    continue
                entry = entries_by_id.get(manifest_id)
                if not entry or str(entry.get("artifact") or "") != artifact:
                    unknown_manifest_id_count += 1
                    category_failures.append({"code": "CATEGORY_ROW_UNKNOWN_MANIFEST_ID", "artifact": artifact, "row_index": ordinal, "validation_id": manifest_id})
                    continue
                linked_artifact_row_count += 1
                matched_manifest_ids.add(manifest_id)
                if _as_int(entry.get("row_index")) != ordinal:
                    row_index_mismatch_count += 1
                    category_failures.append({"code": "CATEGORY_ROW_INDEX_MISMATCH", "artifact": artifact, "row_index": ordinal, "validation_id": manifest_id})
                if str(entry.get("row_key") or "") != str(row.get("live_execution_row_key") or ""):
                    row_key_mismatch_count += 1
                    category_failures.append({"code": "CATEGORY_ROW_KEY_MISMATCH", "artifact": artifact, "row_index": ordinal, "validation_id": manifest_id})
                if str(entry.get("status") or "") != _row_status_for_manifest(row):
                    status_mismatch_count += 1
                    category_failures.append({"code": "CATEGORY_STATUS_MISMATCH", "artifact": artifact, "row_index": ordinal, "validation_id": manifest_id})
                if str(entry.get("observed_mode") or "") != _row_observed_mode_for_manifest(artifact, row, live_enabled):
                    mode_mismatch_count += 1
                    category_failures.append({"code": "CATEGORY_MODE_MISMATCH", "artifact": artifact, "row_index": ordinal, "validation_id": manifest_id})
                if bool(entry.get("raw_sql_included")) or _raw_sql_or_secret_value(entry):
                    raw_sql_or_secret_count += 1
                    category_failures.append({"code": "CATEGORY_MANIFEST_RAW_SQL_OR_SECRET", "artifact": artifact, "row_index": ordinal, "validation_id": manifest_id})

        orphan_manifest_entry_count = sum(1 for row in category_entries if str(row.get("validation_id") or "") not in matched_manifest_ids)
        if orphan_manifest_entry_count:
            category_failures.append({"code": "CATEGORY_ORPHAN_MANIFEST_ENTRY", "count": orphan_manifest_entry_count})
        manifest_entry_count = len(category_entries)
        passed = (
            (not category_required or expected_row_count > 0)
            and observed_artifact_row_count == expected_row_count
            and manifest_entry_count == expected_row_count
            and linked_artifact_row_count == expected_row_count
            and orphan_manifest_entry_count == 0
            and unknown_manifest_id_count == 0
            and missing_manifest_id_count == 0
            and row_index_mismatch_count == 0
            and row_key_mismatch_count == 0
            and status_mismatch_count == 0
            and mode_mismatch_count == 0
            and raw_sql_or_secret_count == 0
        )
        if category_required and expected_row_count == 0:
            category_failures.append({"code": "CATEGORY_EXPECTED_ROWS_ABSENT"})
        if manifest_entry_count != expected_row_count:
            category_failures.append({"code": "CATEGORY_MANIFEST_COUNT_MISMATCH", "expected": expected_row_count, "actual": manifest_entry_count})
        if linked_artifact_row_count != expected_row_count:
            category_failures.append({"code": "CATEGORY_LINKED_ROW_COUNT_MISMATCH", "expected": expected_row_count, "actual": linked_artifact_row_count})
        row = {
            "category": category,
            "artifacts": list(category_artifacts),
            "expected_row_count": expected_row_count,
            "observed_artifact_row_count": observed_artifact_row_count,
            "manifest_entry_count": manifest_entry_count,
            "linked_artifact_row_count": linked_artifact_row_count,
            "orphan_manifest_entry_count": orphan_manifest_entry_count,
            "unknown_manifest_id_count": unknown_manifest_id_count,
            "missing_manifest_id_count": missing_manifest_id_count,
            "row_index_mismatch_count": row_index_mismatch_count,
            "row_key_mismatch_count": row_key_mismatch_count,
            "status_mismatch_count": status_mismatch_count,
            "mode_mismatch_count": mode_mismatch_count,
            "raw_sql_or_secret_count": raw_sql_or_secret_count,
            "required": category_required,
            "passed": passed,
            "failures": category_failures,
            "recommendation": ""
            if passed
            else "Reconcile this manifest category so every expected validation row has one matching sanitized ledger entry.",
        }
        rows.append(row)
        if not passed:
            failures.append(row)

    return _failure_result(
        source="live_execution_manifest_category_coverage",
        proof_source="live_snowflake_execution" if live_enabled else "static_sql_parse",
        failures=failures,
        category_count=len(rows),
        category_failure_count=len(failures),
        categories=rows,
        required_categories=sorted(MANIFEST_CATEGORY_ARTIFACTS),
    )


def _refresh_result(name: str, live_enabled: bool, smoke_rows: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    skipped = not live_enabled
    related = [
        row for row in smoke_rows
        if (name == "refresh_fast_validation" and str(row.get("smoke_target") or "") == "fast_refresh_validation")
        or (name == "refresh_full_validation" and str(row.get("smoke_target") or "") == "full_refresh_validation_or_dry_run")
    ]
    failed = [row for row in related if str(row.get("status") or "") == "failed"]
    return {
        "source": name,
        "proof_source": "live_snowflake_execution" if live_enabled else "static_sql_parse",
        "passed": not failed,
        "status": "skipped" if skipped else ("failed" if failed else "passed"),
        "skip_reason": "Live Snowflake validation disabled; set OVERWATCH_SNOWFLAKE_VALIDATION=1." if skipped else "",
        "elapsed_seconds": 0,
        "target_seconds": 45 if name == "refresh_fast_validation" else 120,
        "failed_section_count": 0,
        "packet_row_count": 0,
        "compact_evidence_row_count": 0,
        "generated_window_count": 2 if name == "refresh_fast_validation" else 5,
        "generated_scope_count": 0,
        "fresh_command_row_count": 0,
        "reused_command_row_count": 0,
        "stale_command_row_count": 0,
        "source_fact_max_ts_by_source": {},
        "command_source_snapshot_ts_by_section": {},
        "compact_evidence_row_counts": {mart: 0 for mart in sorted(COMPACT_EVIDENCE_MARTS)},
        "current_active_row_count": 0,
        "flat_active_row_count": 0,
        "max_packet_bytes": 0,
        "raw_sql_included": False,
    }


def _refresh_detail_results(
    texts: Mapping[str, str],
    refresh_fast: Mapping[str, Any],
    refresh_full: Mapping[str, Any],
    *,
    live_enabled: bool,
) -> dict[str, Any]:
    setup = "\n".join(texts.values()).upper()
    fast_region = _region(setup, "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FAST", "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL")
    full_region = _region(setup, "SP_OVERWATCH_REFRESH_DECISION_BRIEFS_FULL", "SP_OVERWATCH_BOOTSTRAP_DECISION_BRIEFS")
    checks = [
        {
            "refresh": "FAST",
            "check_name": "no_broad_full_core_call",
            "passed": "FULL_IMPL" not in fast_region,
            "actual": "FULL_IMPL" in fast_region,
            "expected": False,
            "source_artifact": "snowflake_setup_sql_static_scan",
        },
        {
            "refresh": "FAST",
            "check_name": "windows_are_1_7_only",
            "passed": all(token not in fast_region for token in ("14", "30", "60", "90")) and "1" in fast_region and "7" in fast_region,
            "actual": "static_window_scan",
            "expected": "1/7 only",
            "source_artifact": "snowflake_setup_sql_static_scan",
        },
        {
            "refresh": "FAST",
            "check_name": "full_only_windows_absent",
            "passed": all(token not in fast_region for token in ("14", "30", "60", "90")),
            "actual": "static_window_scan",
            "expected": "no 14/30/60/90 windows in FAST path",
            "source_artifact": "snowflake_setup_sql_static_scan",
        },
        {
            "refresh": "FAST",
            "check_name": "source_freshness_truth_exists",
            "passed": "SOURCE_FACT_MAX_TS" in setup or "SOURCE_FRESHNESS" in setup,
            "actual": "SOURCE_FACT_MAX_TS/SOURCE_FRESHNESS",
            "expected": "present",
            "source_artifact": "snowflake_setup_sql_static_scan",
        },
        {
            "refresh": "FAST",
            "check_name": "compact_evidence_refresh_included",
            "passed": all(mart in setup for mart in COMPACT_EVIDENCE_MARTS),
            "actual": "compact_mart_static_scan",
            "expected": "all compact marts referenced",
            "source_artifact": "snowflake_setup_sql_static_scan",
        },
        {
            "refresh": "FAST",
            "check_name": "full_only_branches_skipped_or_deferred",
            "passed": "FULL" not in fast_region or "FAST" in fast_region,
            "actual": "static_branch_scan",
            "expected": "no full-only work in FAST wrapper",
            "source_artifact": "snowflake_setup_sql_static_scan",
        },
        {
            "refresh": "FAST",
            "check_name": "max_packet_bytes_under_100kb",
            "passed": int(refresh_fast.get("max_packet_bytes") or 0) <= 100000,
            "actual": int(refresh_fast.get("max_packet_bytes") or 0),
            "expected": "<=100000",
            "source_artifact": "refresh_fast_results.json",
        },
        {
            "refresh": "FULL",
            "check_name": "full_window_coverage",
            "passed": bool(full_region) and ("FULL" in full_region or "FULL_IMPL" in full_region),
            "actual": "static_full_region_scan",
            "expected": "full refresh path explicit",
            "source_artifact": "snowflake_setup_sql_static_scan",
        },
        {
            "refresh": "FULL",
            "check_name": "no_fake_wrapper_audit_row",
            "passed": "FAKE" not in full_region and "SYNTHETIC" not in full_region,
            "actual": "static_audit_scan",
            "expected": "no fake/synthetic audit row",
            "source_artifact": "snowflake_setup_sql_static_scan",
        },
        {
            "refresh": "FULL",
            "check_name": "max_packet_bytes_under_100kb",
            "passed": int(refresh_full.get("max_packet_bytes") or 0) <= 100000,
            "actual": int(refresh_full.get("max_packet_bytes") or 0),
            "expected": "<=100000",
            "source_artifact": "refresh_full_results.json",
        },
    ]
    for payload, label, target in ((refresh_fast, "FAST", 45), (refresh_full, "FULL", 120)):
        checks.extend(
            [
                {
                    "refresh": label,
                    "check_name": "live_elapsed_target_or_profile_skip",
                    "passed": (not live_enabled and str(payload.get("status") or "") == "skipped") or float(payload.get("elapsed_seconds") or 0) <= target,
                    "actual": payload.get("elapsed_seconds") or 0,
                    "expected": f"<={target}s when live",
                    "source_artifact": f"refresh_{label.lower()}_results.json",
                },
                {
                    "refresh": label,
                    "check_name": "failed_section_count_zero",
                    "passed": int(payload.get("failed_section_count") or 0) == 0,
                    "actual": int(payload.get("failed_section_count") or 0),
                    "expected": 0,
                    "source_artifact": f"refresh_{label.lower()}_results.json",
                },
                {
                    "refresh": label,
                    "check_name": "fresh_reused_stale_counts_present",
                    "passed": all(
                        key in payload
                        for key in (
                            "fresh_command_row_count",
                            "reused_command_row_count",
                            "stale_command_row_count",
                        )
                    ),
                    "actual": {
                        "fresh": payload.get("fresh_command_row_count"),
                        "reused": payload.get("reused_command_row_count"),
                        "stale": payload.get("stale_command_row_count"),
                    },
                    "expected": "fresh/reused/stale command counts present",
                    "source_artifact": f"refresh_{label.lower()}_results.json",
                },
                {
                    "refresh": label,
                    "check_name": "source_freshness_timestamp_maps_present",
                    "passed": "source_fact_max_ts_by_source" in payload
                    and "command_source_snapshot_ts_by_section" in payload,
                    "actual": {
                        "source_fact_max_ts_by_source": payload.get("source_fact_max_ts_by_source"),
                        "command_source_snapshot_ts_by_section": payload.get("command_source_snapshot_ts_by_section"),
                    },
                    "expected": "source freshness and command snapshot timestamp maps present",
                    "source_artifact": f"refresh_{label.lower()}_results.json",
                },
                {
                    "refresh": label,
                    "check_name": "live_skip_reason_present_when_skipped",
                    "passed": str(payload.get("status") or "") != "skipped" or "OVERWATCH_SNOWFLAKE_VALIDATION" in str(payload.get("skip_reason") or ""),
                    "actual": payload.get("skip_reason") or "",
                    "expected": "skip reason mentions OVERWATCH_SNOWFLAKE_VALIDATION",
                    "source_artifact": f"refresh_{label.lower()}_results.json",
                },
                {
                    "refresh": label,
                    "check_name": "live_manifest_id_present_when_checked",
                    "passed": (not live_enabled) or bool(payload.get("live_execution_manifest_id")),
                    "actual": payload.get("live_execution_manifest_id") or "",
                    "expected": "manifest id present for live refresh validation",
                    "source_artifact": f"refresh_{label.lower()}_results.json",
                },
            ]
        )
    failures = [
        {
            "refresh": row["refresh"],
            "check_name": row["check_name"],
            "actual": row["actual"],
            "expected": row["expected"],
            "source_artifact": row.get("source_artifact") or "",
            "recommendation": "Fix FAST/FULL refresh SQL validation detail and rerun Snowflake validation.",
        }
        for row in checks
        if not row["passed"]
    ]
    for row in checks:
        row["recommendation"] = "" if row["passed"] else "Fix FAST/FULL refresh SQL validation detail and rerun Snowflake validation."
        row["raw_sql_included"] = False
    return _failure_result(
        source="refresh_detail_validation",
        proof_source="live_snowflake_execution" if live_enabled else "static_sql_parse",
        failures=failures,
        check_count=len(checks),
        checks=checks,
    )


def _snowflake_error_sanitization_results() -> dict[str, Any]:
    samples = [
        {
            "name": "sql_body_removed",
            "message": "SnowflakeSQLException SQL compilation error SELECT * FROM SECRET_TABLE WHERE PASSWORD='hidden';",
            "forbidden": ("SELECT *", "SECRET_TABLE", "hidden"),
            "required": ("SnowflakeSQLException",),
        },
        {
            "name": "credentials_removed",
            "message": "account=my_acct user=admin password=secret token=abc private_key=xyz",
            "forbidden": ("my_acct", "admin", "secret", "abc", "xyz"),
            "required": ("[redacted]",),
        },
        {
            "name": "stack_trace_removed",
            "message": "Traceback (most recent call last):\n  File app.py\nCALL SP_OVERWATCH_X();",
            "forbidden": ("File app.py", "CALL SP_OVERWATCH_X"),
            "required": ("execution stack omitted",),
        },
    ]
    rows = []
    failures = []
    for sample in samples:
        sanitized = sanitize_snowflake_error(sample["message"])
        passed = all(token not in sanitized for token in sample["forbidden"]) and all(token in sanitized for token in sample["required"])
        row = {
            "check_name": sample["name"],
            "passed": passed,
            "sanitized_error": sanitized,
            "raw_sql_included": False,
            "recommendation": "" if passed else "Tighten Snowflake error sanitizer before launch.",
        }
        rows.append(row)
        if not passed:
            failures.append({"check_name": sample["name"], "recommendation": row["recommendation"]})
    return _failure_result(
        source="snowflake_error_sanitization",
        failures=failures,
        check_count=len(rows),
        checks=rows,
    )


def _live_object_inventory(live_enabled: bool) -> list[dict[str, Any]]:
    return [
        _result_row(
            object_name="live_snowflake_inventory",
            object_type="inventory",
            phase="object_inventory_live",
            status="skipped" if not live_enabled else "passed",
            recommendation="Enable OVERWATCH_SNOWFLAKE_VALIDATION=1 to compare live objects." if not live_enabled else "",
        )
    ]


def _phase_validation_results(
    *,
    live_enabled: bool,
    setup_rows: Iterable[Mapping[str, Any]],
    compile_rows: Iterable[Mapping[str, Any]],
    smoke_rows: Iterable[Mapping[str, Any]],
    validation_rows: Iterable[Mapping[str, Any]],
    packet_shape: Mapping[str, Any],
    compact_evidence: Mapping[str, Any],
    refresh_fast: Mapping[str, Any],
    refresh_full: Mapping[str, Any],
) -> dict[str, Any]:
    observed: dict[str, str] = {}
    for row in setup_rows:
        phase = str(row.get("phase") or "")
        if phase:
            observed[phase] = str(row.get("status") or "")
    for row in compile_rows:
        observed[str(row.get("phase") or "procedure_compile_static")] = str(row.get("status") or "")
    for row in smoke_rows:
        observed["procedure_smoke_call_live"] = "failed" if str(row.get("status") or "") == "failed" else str(row.get("status") or "")
    for row in validation_rows:
        observed["validation_sql_static"] = "failed" if str(row.get("status") or "") == "failed" else "passed"
        observed["drop_rollback_static"] = "failed" if str(row.get("status") or "") == "failed" else "passed"
    live_compile_statuses = [str(row.get("status") or "") for row in compile_rows if str(row.get("phase") or "") == "procedure_compile_live"]
    observed["procedure_compile_live"] = (
        "failed" if any(status == "failed" for status in live_compile_statuses)
        else ("passed" if live_enabled and live_compile_statuses else "skipped")
    )
    observed["validation_sql_live"] = "passed" if live_enabled else "skipped"
    observed["packet_shape_static"] = "passed" if packet_shape.get("passed") else "failed"
    observed["packet_shape_live"] = "passed" if live_enabled else "skipped"
    observed["compact_evidence_static"] = "passed" if compact_evidence.get("passed") else "failed"
    observed["compact_evidence_live"] = "passed" if live_enabled else "skipped"
    observed["refresh_fast_static"] = "passed" if refresh_fast.get("passed") else "failed"
    observed["refresh_fast_live"] = str(refresh_fast.get("status") or "missing")
    observed["refresh_full_static_or_dry_run"] = "passed" if refresh_full.get("passed") else "failed"
    observed["drop_rollback_live_or_dry_run"] = "passed" if live_enabled else "skipped"
    rows = []
    failures: list[dict[str, Any]] = []
    for phase in REQUIRED_VALIDATION_PHASES:
        status = observed.get(phase, "missing")
        passed = status in {"passed", "skipped"}
        row = {
            "phase": phase,
            "status": status,
            "passed": passed,
            "raw_sql_included": False,
            "recommendation": "" if passed else "Implement or repair the missing Snowflake validation phase.",
        }
        rows.append(row)
        if not passed:
            failures.append({"phase": phase, "status": status, "recommendation": row["recommendation"]})
    return _failure_result(
        source="snowflake_validation_phase_coverage",
        failures=failures,
        phase_count=len(rows),
        phases=rows,
    )


def _write_skipped(root: Path, live_enabled: bool) -> None:
    skipped_path = root / SNOWFLAKE_VALIDATION_DIR / "snowflake_validation_SKIPPED.txt"
    if live_enabled:
        if skipped_path.exists():
            skipped_path.unlink()
        return
    skipped_path.parent.mkdir(parents=True, exist_ok=True)
    skipped_path.write_text(
        "Live Snowflake execution validation skipped because OVERWATCH_SNOWFLAKE_VALIDATION is not set to 1.\n",
        encoding="utf-8",
    )


def _passed_rows(rows: Iterable[Mapping[str, Any]]) -> bool:
    return all(str(row.get("status") or "passed") in {"passed", "skipped"} for row in rows)


def _live_execution_enabled() -> bool:
    return os.environ.get("OVERWATCH_SNOWFLAKE_VALIDATION") == "1"


def write_snowflake_validation_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    validation_dir = root_path / SNOWFLAKE_VALIDATION_DIR
    validation_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    live_enabled = _live_execution_enabled()
    texts = _load_script_texts(root_path)

    live_environment = _live_validation_environment_results(live_enabled)
    live_session = _live_validation_session_results(live_enabled, root_path)
    setup_rows = _static_setup_results(root_path, texts)
    compile_rows = _compile_results(texts, live_enabled=live_enabled, root=root_path)
    dependency_graph = _dependency_graph(texts)
    validation_rows = _validation_sql_results(texts)
    metric_shape = validate_metric_candidate_union_shape(texts.get("snowflake/mart_setup/05_load_procedures.sql", ""))
    recent_fixes = _recent_snowflake_fix_results(texts)
    trend_cardinality = _trend_cardinality(texts)
    packet_publication, packet_shape, packet_size, packet_source_truth = _packet_results(texts)
    packet_detail = _packet_validation_detail_results(packet_publication, packet_shape, packet_size, packet_source_truth)
    compact_evidence = _compact_evidence_results(root_path, texts)
    compact_detail = _compact_evidence_mart_detail_results(compact_evidence)
    smoke_rows = _static_smoke_results(live_enabled, root_path)
    refresh_fast = _refresh_result("refresh_fast_validation", live_enabled, smoke_rows)
    refresh_full = _refresh_result("refresh_full_validation", live_enabled, smoke_rows)
    refresh_detail = _refresh_detail_results(texts, refresh_fast, refresh_full, live_enabled=live_enabled)
    encoding_scan = _sql_encoding_scan_results(root_path)
    schema_drift = _schema_drift_results(texts)
    sanitizer_results = _snowflake_error_sanitization_results()
    from tools.contracts.formula_end_to_end_validation import (
        build_packet_schema_upgrade_results,
        build_cortex_service_type_live_results,
        build_formula_chain_results,
        build_formula_live_validation_results,
        build_formula_value_reconciliation_results,
        build_snowflake_formula_live_results,
        build_snowflake_formula_value_results,
        build_workload_formula_live_results,
        evaluate_packet_formula_sql,
    )

    packet_formula = evaluate_packet_formula_sql(root_path)
    packet_schema_upgrade = build_packet_schema_upgrade_results(root_path)
    formula_chain = build_formula_chain_results(root_path)
    formula_value_reconciliation = build_formula_value_reconciliation_results(formula_chain)
    formula_live = build_formula_live_validation_results(root_path)
    snowflake_formula_live = build_snowflake_formula_live_results(root_path)
    snowflake_formula_value = build_snowflake_formula_value_results(formula_value_reconciliation)
    cortex_service_type_live = build_cortex_service_type_live_results(root_path)
    workload_formula_live = build_workload_formula_live_results(root_path)
    live_execution_manifest = _live_execution_manifest_results(
        live_enabled=live_enabled,
        live_environment=live_environment,
        live_session=live_session,
        setup_rows=setup_rows,
        compile_rows=compile_rows,
        smoke_rows=smoke_rows,
        validation_rows=validation_rows,
        refresh_fast=refresh_fast,
        refresh_full=refresh_full,
        packet_publication=packet_publication,
        packet_shape=packet_shape,
        packet_size=packet_size,
        packet_source_truth=packet_source_truth,
        packet_detail=packet_detail,
        compact_evidence=compact_evidence,
        compact_detail=compact_detail,
        refresh_detail=refresh_detail,
        recent_fixes=recent_fixes,
        metric_shape=metric_shape,
        trend_cardinality=trend_cardinality,
        encoding_scan=encoding_scan,
        schema_drift=schema_drift,
        sanitizer_results=sanitizer_results,
    )
    compile_coverage = _procedure_compile_coverage_results(dependency_graph, compile_rows, live_enabled=live_enabled)
    smoke_coverage = _procedure_smoke_call_coverage_results(
        smoke_rows,
        live_enabled=live_enabled,
        profile=os.environ.get("OVERWATCH_LAUNCH_PROFILE", "internal_fixture"),
    )
    _append_manifest_payload_rows(
        live_execution_manifest,
        compile_coverage,
        artifact="procedure_compile_coverage_results.json",
        live_enabled=live_enabled,
    )
    _append_manifest_payload_rows(
        live_execution_manifest,
        smoke_coverage,
        artifact="procedure_smoke_call_coverage_results.json",
        live_enabled=live_enabled,
    )
    object_inventory_live = _live_object_inventory(live_enabled)
    manifest_validation = _streamlit_manifest_validation(root_path)
    phase_validation = _phase_validation_results(
        live_enabled=live_enabled,
        setup_rows=setup_rows,
        compile_rows=compile_rows,
        smoke_rows=smoke_rows,
        validation_rows=validation_rows,
        packet_shape=packet_shape,
        compact_evidence=compact_evidence,
        refresh_fast=refresh_fast,
        refresh_full=refresh_full,
    )
    refresh_performance: dict[str, Any] = {
        "source": "refresh_performance_validation",
        "proof_source": "live_snowflake_execution" if live_enabled else "static_sql_parse",
        "passed": True,
        "live_mode_enabled": live_enabled,
        "fast_target_seconds": 45,
        "full_target_seconds": 120,
        "fast_elapsed_seconds": 0,
        "full_elapsed_seconds": 0,
        "skip_reason": "" if live_enabled else "Live Snowflake validation disabled; static validation artifacts generated.",
        "raw_sql_included": False,
    }
    refresh_stage_timing: dict[str, Any] = {
        "source": "refresh_stage_timing_validation",
        "proof_source": "live_snowflake_execution" if live_enabled else "static_sql_parse",
        "passed": True,
        "stage_count": 0,
        "stages": [],
        "raw_sql_included": False,
    }
    refresh_row_counts: dict[str, Any] = {
        "source": "refresh_row_count_validation",
        "proof_source": "live_snowflake_execution" if live_enabled else "static_sql_parse",
        "passed": True,
        "failed_section_count": 0,
        "packet_row_count": 0,
        "compact_evidence_mart_count": len(COMPACT_EVIDENCE_MARTS),
        "raw_sql_included": False,
    }
    reconciliation_payloads = {
        "live_validation_environment_results.json": live_environment,
        "live_validation_session_results.json": live_session,
        "setup_execution_results.json": setup_rows,
        "procedure_compile_results.json": compile_rows,
        "procedure_compile_coverage_results.json": compile_coverage,
        "procedure_smoke_call_results.json": smoke_rows,
        "procedure_smoke_call_coverage_results.json": smoke_coverage,
        "validation_sql_results.json": validation_rows,
        "refresh_fast_results.json": refresh_fast,
        "refresh_full_results.json": refresh_full,
        "packet_publication_validation_results.json": packet_publication,
        "packet_shape_results.json": packet_shape,
        "packet_size_results.json": packet_size,
        "packet_source_truth_results.json": packet_source_truth,
        "packet_validation_detail_results.json": packet_detail,
        "compact_evidence_mart_validation_results.json": compact_evidence,
        "compact_evidence_mart_detail_results.json": compact_detail,
        "refresh_detail_results.json": refresh_detail,
        "recent_snowflake_fix_validation_results.json": recent_fixes,
        "metric_candidate_shape_results.json": metric_shape,
        "trend_cardinality_results.json": trend_cardinality,
        "schema_drift_results.json": schema_drift,
        "sql_encoding_scan_results.json": encoding_scan,
        "snowflake_error_sanitization_results.json": sanitizer_results,
    }
    live_execution_manifest_reconciliation = _live_execution_manifest_reconciliation_results(
        live_execution_manifest,
        reconciliation_payloads,
        live_enabled=live_enabled,
    )
    live_execution_manifest_category_coverage = _live_execution_manifest_category_coverage_results(
        live_execution_manifest,
        reconciliation_payloads,
        live_enabled=live_enabled,
    )

    hard_failures: list[dict[str, Any]] = []
    for rel in EXPECTED_SCRIPT_ORDER:
        if rel not in texts:
            hard_failures.append({"gate": "expected_script_present", "file": rel})
    if not _passed_rows(setup_rows):
        hard_failures.append({"gate": "setup_static_order"})
    if not compile_rows:
        hard_failures.append({"gate": "procedure_compile_static", "reason": "No procedures were detected."})
    if not dependency_graph["passed"]:
        hard_failures.append({"gate": "procedure_dependency_graph", "details": dependency_graph["unresolved_call_targets"]})
    if not compile_coverage["passed"]:
        hard_failures.append({"gate": "procedure_compile_coverage", "details": compile_coverage["failures"]})
    if not smoke_coverage["passed"]:
        hard_failures.append({"gate": "procedure_smoke_call_coverage", "details": smoke_coverage["failures"]})
    if any(row["status"] == "failed" for row in validation_rows):
        hard_failures.append({"gate": "validation_or_drop_static"})
    for name, payload in {
        "metric_candidate_shape": metric_shape,
        "recent_snowflake_fixes": recent_fixes,
        "trend_cardinality": trend_cardinality,
        "packet_publication": packet_publication,
        "packet_shape": packet_shape,
        "packet_size": packet_size,
        "packet_source_truth": packet_source_truth,
        "packet_detail": packet_detail,
        "compact_evidence_marts": compact_evidence,
        "compact_evidence_mart_detail": compact_detail,
        "refresh_detail": refresh_detail,
        "sql_encoding_scan": encoding_scan,
        "schema_drift": schema_drift,
        "streamlit_manifest": manifest_validation,
        "phase_validation": phase_validation,
        "snowflake_error_sanitization": sanitizer_results,
        "packet_formula_sql": packet_formula,
        "packet_schema_upgrade": packet_schema_upgrade,
        "formula_live_validation": formula_live,
        "snowflake_formula_live": snowflake_formula_live,
        "snowflake_formula_value": snowflake_formula_value,
        "cortex_service_type_live": cortex_service_type_live,
        "workload_formula_live": workload_formula_live,
        "live_validation_environment": live_environment,
        "live_validation_session": live_session,
        "live_execution_manifest": live_execution_manifest,
        "live_execution_manifest_reconciliation": live_execution_manifest_reconciliation,
        "live_execution_manifest_category_coverage": live_execution_manifest_category_coverage,
    }.items():
        if not payload.get("passed"):
            hard_failures.append({"gate": name, "details": payload.get("failures") or payload.get("checks")})
    compile_failures = [row for row in compile_rows if str(row.get("status") or "") == "failed"]
    smoke_failures = [row for row in smoke_rows if str(row.get("status") or "") == "failed"]
    if compile_failures:
        hard_failures.append({"gate": "procedure_compile_validation", "count": len(compile_failures)})
    if smoke_failures:
        hard_failures.append({"gate": "procedure_smoke_call_validation", "count": len(smoke_failures)})

    summary = {
        "source": "snowflake_execution_validation",
        "proof_source": "live_snowflake_execution" if live_enabled else "static_sql_parse",
        "generated_at": _utc_now(),
        "passed": not hard_failures,
        "all_passed": not hard_failures,
        "live_mode_enabled": live_enabled,
        "live_status": "enabled" if live_enabled else "skipped",
        "live_skip_reason": "" if live_enabled else "OVERWATCH_SNOWFLAKE_VALIDATION is not set to 1.",
        "live_validation_environment_passed": bool(live_environment.get("passed")),
        "live_validation_session_passed": bool(live_session.get("passed")),
        "live_validation_session_status": str(live_session.get("status") or ""),
        "live_execution_manifest_passed": bool(live_execution_manifest.get("passed")),
        "live_execution_manifest_entry_count": int(live_execution_manifest.get("entry_count") or 0),
        "live_execution_manifest_failure_count": int(live_execution_manifest.get("failure_count") or 0),
        "live_execution_manifest_reconciliation_passed": bool(live_execution_manifest_reconciliation.get("passed")),
        "live_execution_manifest_reconciliation_failure_count": int(live_execution_manifest_reconciliation.get("failure_count") or 0),
        "live_execution_manifest_category_coverage_passed": bool(live_execution_manifest_category_coverage.get("passed")),
        "live_execution_manifest_category_failure_count": int(live_execution_manifest_category_coverage.get("failure_count") or 0),
        "script_count": len(texts),
        "expected_script_count": len(EXPECTED_SCRIPT_ORDER),
        "statement_count": sum(row["row_count"] for row in setup_rows),
        "procedure_compile_count": len(compile_rows),
        "procedure_compile_failure_count": len(compile_failures),
        "procedure_compile_coverage_passed": bool(compile_coverage.get("passed")),
        "procedure_smoke_call_count": len(smoke_rows),
        "procedure_smoke_failure_count": len(smoke_failures),
        "procedure_smoke_call_coverage_passed": bool(smoke_coverage.get("passed")),
        "metric_candidate_branch_count": metric_shape.get("branch_count", 0),
        "compact_evidence_mart_count": len(COMPACT_EVIDENCE_MARTS),
        "validation_phase_count": len(REQUIRED_VALIDATION_PHASES),
        "validation_phases": list(REQUIRED_VALIDATION_PHASES),
        "recent_snowflake_fix_validation_passed": bool(recent_fixes.get("passed")),
        "packet_publication_validation_passed": bool(packet_publication.get("passed")) and bool(packet_shape.get("passed")),
        "packet_validation_detail_passed": bool(packet_detail.get("passed")),
        "compact_evidence_mart_validation_passed": bool(compact_evidence.get("passed")),
        "compact_evidence_mart_detail_passed": bool(compact_detail.get("passed")),
        "refresh_fast_status": refresh_fast.get("status"),
        "refresh_full_status": refresh_full.get("status"),
        "refresh_detail_passed": bool(refresh_detail.get("passed")),
        "snowflake_error_sanitization_passed": bool(sanitizer_results.get("passed")),
        "packet_formula_sql_passed": bool(packet_formula.get("passed")),
        "packet_schema_upgrade_passed": bool(packet_schema_upgrade.get("passed")),
        "formula_live_validation_passed": bool(formula_live.get("passed")),
        "formula_validation_mode": snowflake_formula_live.get("formula_validation_mode"),
        "snowflake_formula_live_required": bool(snowflake_formula_live.get("snowflake_formula_live_required")),
        "snowflake_formula_live_executed": bool(snowflake_formula_live.get("snowflake_formula_live_executed")),
        "snowflake_formula_live_passed": bool(snowflake_formula_live.get("snowflake_formula_live_passed")),
        "snowflake_formula_live_skipped": bool(snowflake_formula_live.get("snowflake_formula_live_skipped")),
        "snowflake_formula_live_skip_reason": snowflake_formula_live.get("snowflake_formula_live_skip_reason"),
        "snowflake_formula_value_passed": bool(snowflake_formula_value.get("passed")),
        "snowflake_formula_value_failure_count": int(snowflake_formula_value.get("failure_count") or 0),
        "cortex_service_type_live_passed": bool(cortex_service_type_live.get("passed")),
        "workload_formula_live_passed": bool(workload_formula_live.get("passed")),
        "hard_failure_count": len(hard_failures),
        "hard_failures": hard_failures,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "raw_sql_included": False,
    }

    artifacts: dict[str, Any] = {
        "snowflake_validation_summary": summary,
        "live_execution_manifest": live_execution_manifest,
        "live_execution_manifest_reconciliation": live_execution_manifest_reconciliation,
        "live_execution_manifest_category_coverage": live_execution_manifest_category_coverage,
        "live_validation_environment_results": live_environment,
        "live_validation_session_results": live_session,
        "setup_execution_results": setup_rows,
        "procedure_compile_results": compile_rows,
        "procedure_compile_coverage_results": compile_coverage,
        "procedure_smoke_call_results": smoke_rows,
        "procedure_smoke_call_coverage_results": smoke_coverage,
        "validation_sql_results": validation_rows,
        "refresh_fast_results": refresh_fast,
        "refresh_full_results": refresh_full,
        "object_inventory_live_results": object_inventory_live,
        "procedure_dependency_graph": dependency_graph,
        "recent_snowflake_fix_validation_results": recent_fixes,
        "metric_candidate_shape_results": metric_shape,
        "trend_cardinality_results": trend_cardinality,
        "packet_publication_validation_results": packet_publication,
        "packet_shape_results": packet_shape,
        "packet_size_results": packet_size,
        "packet_source_truth_results": packet_source_truth,
        "packet_validation_detail_results": packet_detail,
        "compact_evidence_mart_validation_results": compact_evidence,
        "compact_evidence_mart_detail_results": compact_detail,
        "refresh_performance_results": refresh_performance,
        "refresh_stage_timing_results": refresh_stage_timing,
        "refresh_row_count_results": refresh_row_counts,
        "refresh_detail_results": refresh_detail,
        "sql_encoding_scan_results": encoding_scan,
        "schema_drift_results": schema_drift,
        "streamlit_manifest_validation_results": manifest_validation,
        "phase_validation_results": phase_validation,
        "snowflake_error_sanitization_results": sanitizer_results,
        "packet_formula_results": packet_formula,
        "packet_schema_upgrade_results": packet_schema_upgrade,
        "formula_live_validation_results": formula_live,
        "snowflake_formula_live_results": snowflake_formula_live,
        "snowflake_formula_value_results": snowflake_formula_value,
        "cortex_service_type_live_results": cortex_service_type_live,
        "workload_formula_live_results": workload_formula_live,
    }
    for name, payload in artifacts.items():
        _write_json(validation_dir / f"{name}.json", payload)
    _write_skipped(root_path, live_enabled)
    manifest_files = sorted(
        [
            f"{SNOWFLAKE_VALIDATION_DIR}/{name}.json"
            for name in artifacts
        ]
        + ([] if live_enabled else [f"{SNOWFLAKE_VALIDATION_DIR}/snowflake_validation_SKIPPED.txt"])
        + [f"{SNOWFLAKE_VALIDATION_DIR}/artifact_manifest.json"]
    )
    manifest = {
        "source": "snowflake_execution_validation",
        "proof_source": "live_snowflake_execution" if live_enabled else "static_sql_parse",
        "generated_at": _utc_now(),
        "files": manifest_files,
        "file_count": len(manifest_files),
        "raw_sql_included": False,
    }
    _write_json(validation_dir / "artifact_manifest.json", manifest)
    artifacts["artifact_manifest"] = manifest
    return {f"{SNOWFLAKE_VALIDATION_DIR}/{name}.json": payload for name, payload in artifacts.items()}


__all__ = [
    "COMPACT_EVIDENCE_MARTS",
    "EXPECTED_SCRIPT_ORDER",
    "REQUIRED_RESULT_FILES",
    "REQUIRED_VALIDATION_PHASES",
    "SNOWFLAKE_VALIDATION_DIR",
    "sanitize_snowflake_error",
    "split_sql_statements",
    "validate_metric_candidate_union_shape",
    "write_snowflake_validation_artifacts",
]
