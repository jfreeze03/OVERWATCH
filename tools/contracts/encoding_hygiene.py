"""Repo-wide encoding hygiene gate for launch readiness.

The gate is deliberately focused on broken encodings and hidden control
characters. It does not ban normal documented Unicode in prose, but it blocks
the mojibake/BOM/replacement-character classes that have caused release churn.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable


ROOT_ARTIFACT = "artifacts/encoding_hygiene_results.json"
LAUNCH_ARTIFACT = "artifacts/launch_readiness/encoding_hygiene_results.json"

TEXT_SUFFIXES = {
    ".csv",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".txt",
    ".yaml",
    ".yml",
}

EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}

MOJIBAKE_SIGNATURES = {
    "MOJIBAKE_LATIN_SMALL_A_WITH_CIRCUMFLEX": "\u00e2",
    "MOJIBAKE_LATIN_CAPITAL_A_WITH_TILDE": "\u00c3",
    "MOJIBAKE_LATIN_CAPITAL_A_WITH_CIRCUMFLEX": "\u00c2",
    "MOJIBAKE_I_WITH_DIAERESIS": "\u00ef",
    "MOJIBAKE_EURO_MARK": "\u20ac",
}

BIDI_RANGES = (
    (0x202A, 0x202E),
    (0x2066, 0x2069),
)

ALLOWED_CONTROL_CODES = {0x09, 0x0A, 0x0D}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _is_scan_target(path: Path, root: Path) -> bool:
    if not path.is_file():
        return False
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    rel_parts = path.relative_to(root).parts
    rel = str(path.relative_to(root)).replace("\\", "/")
    suffix = path.suffix.lower()
    if suffix not in TEXT_SUFFIXES:
        return False
    if rel.startswith("artifacts/"):
        return suffix in {".csv", ".json", ".md", ".txt"}
    if rel_parts and rel_parts[0] in {".overwatch_final", "tools", "tests", "snowflake", "docs", ".github"}:
        return True
    if len(rel_parts) == 1 and suffix in {".md", ".yaml", ".yml"}:
        return True
    return False


def iter_scan_files(root: Path | str) -> list[Path]:
    """Return deterministic repo files covered by the encoding gate."""

    root_path = Path(root).resolve()
    return [
        path
        for path in sorted(root_path.rglob("*"))
        if _is_scan_target(path, root_path)
    ]


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    previous_break = text.rfind("\n", 0, offset)
    column = offset + 1 if previous_break < 0 else offset - previous_break
    return line, column


def _control_code_findings(rel: str, text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        code = ord(char)
        if code in ALLOWED_CONTROL_CODES:
            continue
        is_c0_or_c1 = code < 0x20 or 0x7F <= code <= 0x9F
        is_bidi = any(start <= code <= end for start, end in BIDI_RANGES)
        if not is_c0_or_c1 and not is_bidi:
            continue
        line, column = _line_col(text, index)
        findings.append(
            {
                "file": rel,
                "code": "HIDDEN_BIDI_CONTROL" if is_bidi else "DISALLOWED_CONTROL_CHARACTER",
                "line": line,
                "column": column,
                "unicode_codepoint": f"U+{code:04X}",
                "recommendation": "Remove hidden control characters from launch-bound files.",
            }
        )
    return findings


def scan_file(path: Path, root: Path | str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Scan one file and return a row plus blocking findings."""

    root_path = Path(root).resolve()
    rel = str(path.relative_to(root_path)).replace("\\", "/")
    findings: list[dict[str, Any]] = []
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        findings.append(
            {
                "file": rel,
                "code": "UTF8_BOM",
                "line": 1,
                "column": 1,
                "recommendation": "Save the file as UTF-8 without byte-order mark.",
            }
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        findings.append(
            {
                "file": rel,
                "code": "UTF8_DECODE_ERROR",
                "line": 1,
                "column": exc.start + 1,
                "recommendation": "Re-save the file as valid UTF-8.",
            }
        )
        text = raw.decode("utf-8", errors="replace")
    for token_name, token in MOJIBAKE_SIGNATURES.items():
        start = 0
        while True:
            offset = text.find(token, start)
            if offset < 0:
                break
            line, column = _line_col(text, offset)
            findings.append(
                {
                    "file": rel,
                    "code": token_name,
                    "line": line,
                    "column": column,
                    "recommendation": "Replace mojibake with the intended text or escaped test fixture.",
                }
            )
            start = offset + len(token)
    replacement = "\ufffd"
    start = 0
    while True:
        offset = text.find(replacement, start)
        if offset < 0:
            break
        line, column = _line_col(text, offset)
        findings.append(
            {
                "file": rel,
                "code": "REPLACEMENT_CHARACTER",
                "line": line,
                "column": column,
                "recommendation": "Remove replacement characters and recover the original text.",
            }
        )
        start = offset + 1
    findings.extend(_control_code_findings(rel, text))
    row = {
        "file": rel,
        "status": "failed" if findings else "passed",
        "blocked_count": len(findings),
        "raw_sql_included": False,
    }
    return row, findings


def evaluate_encoding_hygiene(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for path in iter_scan_files(root_path):
        row, file_findings = scan_file(path, root_path)
        rows.append(row)
        findings.extend(file_findings)
    by_code: dict[str, int] = {}
    for finding in findings:
        code = str(finding.get("code") or "UNKNOWN")
        by_code[code] = by_code.get(code, 0) + 1
    return {
        "source": "encoding_hygiene",
        "proof_source": "static_source_scan",
        "generated_at": _utc_now(),
        "passed": not findings,
        "blocked_count": len(findings),
        "finding_count": len(findings),
        "findings": findings,
        "finding_count_by_code": dict(sorted(by_code.items())),
        "scanned_file_count": len(rows),
        "rows": rows,
        "scan_suffixes": sorted(TEXT_SUFFIXES),
        "raw_sql_included": False,
    }


def write_encoding_hygiene_artifacts(root: Path | str = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    payload = evaluate_encoding_hygiene(root_path)
    _write_json(root_path / ROOT_ARTIFACT, payload)
    _write_json(root_path / LAUNCH_ARTIFACT, payload)
    return {
        ROOT_ARTIFACT: payload,
        LAUNCH_ARTIFACT: payload,
    }


def main(argv: Iterable[str] | None = None) -> int:
    args = list(argv or [])
    root = Path(args[0]).resolve() if args else Path(".").resolve()
    payload = write_encoding_hygiene_artifacts(root)[ROOT_ARTIFACT]
    if not payload["passed"]:
        print(json.dumps(payload["findings"], indent=2, sort_keys=True))
        return 1
    print(f"encoding hygiene passed: {payload['scanned_file_count']} files scanned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LAUNCH_ARTIFACT",
    "ROOT_ARTIFACT",
    "evaluate_encoding_hygiene",
    "iter_scan_files",
    "scan_file",
    "write_encoding_hygiene_artifacts",
]
