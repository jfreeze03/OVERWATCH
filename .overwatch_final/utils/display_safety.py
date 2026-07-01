"""Daily UI display-safety helpers.

These helpers translate implementation/source names into short operator labels.
Admin/setup surfaces may still show technical names through their own gates; the
default Decision Workspace should not.
"""

from __future__ import annotations

import re
from typing import Iterable


DAILY_SOURCE_LABELS = {
    "packet": "Packet",
    "source_object": "Packet",
    "account_usage": "Refresh-backed",
    "information_schema": "Deep diagnostics",
    "compact_mart": "Evidence cache",
    "live_deep": "Deep diagnostics",
}

RAW_SOURCE_TOKEN_PATTERN = re.compile(
    r"\b(?:SNOWFLAKE\.ACCOUNT_USAGE|ACCOUNT_USAGE|INFORMATION_SCHEMA|MART_[A-Z0-9_]*|"
    r"FACT_[A-Z0-9_]*|SP_[A-Z0-9_]*|CALL\s+SP_[A-Z0-9_]*|CREATE\s+OR\s+REPLACE|"
    r"SELECT\s+\*|OVERWATCH_ALERTS|ALERT_RUN_HISTORY|ALERT_REMEDIATION_LOG|LOGIN_HISTORY|"
    r"GRANTS_TO_ROLES|OBJECT_DEPENDENCIES|CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY|"
    r"CORTEX_CODE_CLI_USAGE_HISTORY|CREDENTIAL_ID|USER_ID|RAW_USER_ID)\b",
    re.IGNORECASE,
)

_COMPACT_OBJECT_PATTERN = re.compile(r"\b(?:MART|FACT)_[A-Z0-9_]+\b", re.IGNORECASE)
_PROCEDURE_PATTERN = re.compile(r"\bSP_[A-Z0-9_]+\b", re.IGNORECASE)
_ACCOUNT_USAGE_PATTERN = re.compile(r"\b(?:SNOWFLAKE\.)?ACCOUNT_USAGE\b", re.IGNORECASE)
_INFORMATION_SCHEMA_PATTERN = re.compile(r"\bINFORMATION_SCHEMA\b", re.IGNORECASE)
_EVIDENCE_OBJECT_PATTERN = re.compile(
    r"\b(?:OVERWATCH_ALERTS|ALERT_RUN_HISTORY|ALERT_REMEDIATION_LOG)\b",
    re.IGNORECASE,
)
_REFRESH_OBJECT_PATTERN = re.compile(
    r"\b(?:LOGIN_HISTORY|CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY|CORTEX_CODE_CLI_USAGE_HISTORY)\b",
    re.IGNORECASE,
)
_DEEP_DIAGNOSTIC_OBJECT_PATTERN = re.compile(
    r"\b(?:GRANTS_TO_ROLES|OBJECT_DEPENDENCIES)\b",
    re.IGNORECASE,
)
_RAW_IDENTIFIER_PATTERN = re.compile(r"\b(?:CREDENTIAL_ID|USER_ID|RAW_USER_ID)\b", re.IGNORECASE)
_SQL_BODY_PATTERN = re.compile(
    r"\b(?:CREATE\s+OR\s+REPLACE|SELECT\s+\*|CALL\s+SP_|WITH\s+[A-Z0-9_]+\s+AS)\b",
    re.IGNORECASE,
)


def contains_raw_source_token(value: object) -> bool:
    """Return whether text contains source/object/SQL terms unsafe for daily UI."""

    return bool(RAW_SOURCE_TOKEN_PATTERN.search(str(value or "")))


def source_family_for_display(value: object, *, source_key: object = "") -> str:
    """Classify source-ish text into a daily-safe display family."""

    text = " ".join(str(part or "") for part in (source_key, value)).strip()
    upper = text.upper()
    lowered = text.lower()
    if not text:
        return "packet"
    if "deep" in lowered or "live" in lowered or _INFORMATION_SCHEMA_PATTERN.search(text) or _PROCEDURE_PATTERN.search(text):
        return "live_deep"
    if _DEEP_DIAGNOSTIC_OBJECT_PATTERN.search(text):
        return "live_deep"
    if _ACCOUNT_USAGE_PATTERN.search(text) or _REFRESH_OBJECT_PATTERN.search(text):
        return "account_usage"
    if (
        _COMPACT_OBJECT_PATTERN.search(text)
        or _EVIDENCE_OBJECT_PATTERN.search(text)
        or "mart" in lowered
        or "fact" in lowered
        or "evidence" in lowered
        or "cache" in lowered
    ):
        return "compact_mart"
    if _SQL_BODY_PATTERN.search(text):
        return "live_deep"
    return "packet"


def safe_source_label(value: object, *, source_key: object = "", admin_only: bool = False) -> str:
    """Map a source name to the label allowed for the current surface."""

    text = str(value or source_key or "").strip()
    if admin_only and text:
        return text
    if _RAW_IDENTIFIER_PATTERN.search(text):
        return "Restricted identifier"
    return DAILY_SOURCE_LABELS[source_family_for_display(text, source_key=source_key)]


def scrub_daily_text(value: object, *, admin_only: bool = False) -> str:
    """Replace implementation/source names with daily-safe labels."""

    text = str(value or "")
    if admin_only or not text:
        return text
    text = _COMPACT_OBJECT_PATTERN.sub("Evidence cache", text)
    text = _ACCOUNT_USAGE_PATTERN.sub("Refresh-backed", text)
    text = _INFORMATION_SCHEMA_PATTERN.sub("Deep diagnostics", text)
    text = _EVIDENCE_OBJECT_PATTERN.sub("Evidence cache", text)
    text = _REFRESH_OBJECT_PATTERN.sub("Refresh-backed", text)
    text = _DEEP_DIAGNOSTIC_OBJECT_PATTERN.sub("Deep diagnostics", text)
    text = _PROCEDURE_PATTERN.sub("Deep diagnostics", text)
    text = _RAW_IDENTIFIER_PATTERN.sub("Restricted identifier", text)
    text = re.sub(r"\bCALL\s+Deep diagnostics\b", "Deep diagnostics", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCREATE\s+OR\s+REPLACE\b", "Setup detail", text, flags=re.IGNORECASE)
    text = re.sub(r"\bSELECT\s+\*\b", "Detailed query", text, flags=re.IGNORECASE)
    return text


def safe_source_footer_items(
    values: Iterable[object],
    *,
    admin_only: bool = False,
) -> tuple[str, ...]:
    """Return unique daily-safe source footer labels in stable order."""

    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = safe_source_label(value, admin_only=admin_only)
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    return tuple(labels or ("Packet",))


__all__ = [
    "DAILY_SOURCE_LABELS",
    "RAW_SOURCE_TOKEN_PATTERN",
    "contains_raw_source_token",
    "safe_source_footer_items",
    "safe_source_label",
    "scrub_daily_text",
    "source_family_for_display",
]
