"""Canonical Cortex service-type classification for billing formulas."""

from __future__ import annotations

from typing import Any

import pandas as pd


CORTEX_SERVICE_TYPE_ALLOWLIST = frozenset(
    {
        "AI_SERVICES",
        "CORTEX",
        "CORTEX_AI",
        "CORTEX_ANALYST",
        "CORTEX_FUNCTIONS",
        "CORTEX_SEARCH",
        "DOCUMENT_AI",
        "FINE_TUNING",
    }
)

CORTEX_SERVICE_TYPE_PREFIXES = (
    "CORTEX_",
    "SNOWFLAKE_CORTEX_",
)


def normalize_service_type(value: object) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def is_cortex_service_type(value: object) -> bool:
    normalized = normalize_service_type(value)
    if normalized in CORTEX_SERVICE_TYPE_ALLOWLIST:
        return True
    return any(normalized.startswith(prefix) for prefix in CORTEX_SERVICE_TYPE_PREFIXES)


def cortex_service_type_mask(frame: pd.DataFrame | None, *, column: str = "SERVICE_TYPE") -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=bool)
    if column not in frame.columns:
        return pd.Series([False] * len(frame), index=frame.index)
    return frame[column].map(is_cortex_service_type).astype(bool)


def unknown_service_types_for_review(frame: pd.DataFrame | None, *, column: str = "SERVICE_TYPE") -> list[str]:
    if frame is None or frame.empty or column not in frame.columns:
        return []
    values = {
        normalize_service_type(value)
        for value in frame[column].dropna().tolist()
        if str(value or "").strip()
    }
    return sorted(value for value in values if value and not is_cortex_service_type(value))


def cortex_service_type_mapping_results(frame: pd.DataFrame | None = None) -> dict[str, Any]:
    unknown = unknown_service_types_for_review(frame)
    return {
        "source": "cortex_service_type_mapping",
        "passed": True,
        "allowlist": sorted(CORTEX_SERVICE_TYPE_ALLOWLIST),
        "approved_prefixes": list(CORTEX_SERVICE_TYPE_PREFIXES),
        "unknown_service_types": unknown,
        "unknown_service_type_count": len(unknown),
        "broad_ai_substring_match_enabled": False,
        "raw_sql_included": False,
    }


__all__ = [
    "CORTEX_SERVICE_TYPE_ALLOWLIST",
    "CORTEX_SERVICE_TYPE_PREFIXES",
    "cortex_service_type_mapping_results",
    "cortex_service_type_mask",
    "is_cortex_service_type",
    "normalize_service_type",
    "unknown_service_types_for_review",
]
