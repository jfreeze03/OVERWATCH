"""User display-name helpers for daily UI and exports.

Snowflake usage views often carry a stable ``USER_NAME`` or ``USER_ID`` that is
useful for joins but hostile in daily charts. These helpers keep the stable
identifier available for admin/reconciliation paths while giving daily surfaces
a readable label.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

import pandas as pd


USER_ID_COLUMNS = {"USER_ID", "USERID", "RAW_USER_ID"}
USER_STABLE_COLUMNS = {"USER_NAME", "LOGIN_NAME"}
USER_DISPLAY_COLUMNS = {"USER_DISPLAY_NAME", "USER_CHART_LABEL", "USER_ADMIN_LABEL"}
UNKNOWN_USER_LABEL = "Unknown user"
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,}$")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def _first(row: Mapping[str, Any], *keys: str) -> str:
    upper = {str(key).upper(): value for key, value in row.items()}
    for key in keys:
        value = _clean(upper.get(key.upper()))
        if value:
            return value
    return ""


def looks_like_user_id(value: Any) -> bool:
    """Return True for opaque identifiers that should not appear in daily labels."""
    text = _clean(value)
    if not text:
        return False
    compact = text.replace("-", "")
    if text.isdigit() and len(text) >= 4:
        return True
    if _UUID_RE.match(text):
        return True
    if compact.isdigit() and len(compact) >= 8:
        return True
    if _OPAQUE_ID_RE.match(text) and any(char.isdigit() for char in text) and not any(char.isspace() for char in text):
        return True
    return False


def _safe_name(value: Any) -> str:
    text = _clean(value)
    if not text or looks_like_user_id(text):
        return ""
    return text


def _first_safe(row: Mapping[str, Any], *keys: str) -> str:
    upper = {str(key).upper(): value for key, value in row.items()}
    for key in keys:
        value = _safe_name(upper.get(key.upper()))
        if value:
            return value
    return ""


def full_name(row: Mapping[str, Any]) -> str:
    first = _first(row, "FIRST_NAME")
    last = _first(row, "LAST_NAME")
    return " ".join(part for part in (first, last) if part).strip()


def user_name(row: Mapping[str, Any]) -> str:
    return _first(row, "USER_NAME", "NAME", "LOGIN_NAME", "USER_ID")


def user_display_name(row: Mapping[str, Any]) -> str:
    return (
        full_name(row)
        or _safe_name(_first(row, "DISPLAY_NAME"))
        or _first_safe(row, "NAME", "LOGIN_NAME")
        or UNKNOWN_USER_LABEL
    )


def user_chart_label(row: Mapping[str, Any]) -> str:
    return full_name(row) or _first_safe(row, "NAME", "LOGIN_NAME") or UNKNOWN_USER_LABEL


def user_admin_label(row: Mapping[str, Any]) -> str:
    display = user_display_name(row)
    stable = _first(row, "NAME", "USER_NAME", "LOGIN_NAME", "USER_ID")
    if stable and stable != display:
        return f"{display} ({stable})"
    return display


def apply_user_display_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with USER_* display columns populated from Snowflake user fields."""
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame.copy()
    result = frame.copy()
    rows = result.to_dict(orient="records")
    if "USER_NAME" not in result.columns:
        result["USER_NAME"] = [user_name(row) for row in rows]
    result["USER_DISPLAY_NAME"] = [user_display_name(row) for row in rows]
    result["USER_CHART_LABEL"] = [user_chart_label(row) for row in rows]
    result["USER_ADMIN_LABEL"] = [user_admin_label(row) for row in rows]
    return result


def sanitize_user_columns_for_export(frame: pd.DataFrame, *, admin_only: bool = False) -> pd.DataFrame:
    """Hide raw user IDs in default exports while keeping friendly labels."""
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame.copy()
    result = apply_user_display_columns(frame)
    if not admin_only:
        result = result.drop(columns=[column for column in result.columns if column.upper() in USER_ID_COLUMNS], errors="ignore")
        admin_columns = [column for column in result.columns if column.upper() == "USER_ADMIN_LABEL"]
        result = result.drop(columns=admin_columns, errors="ignore")
        for column in ("USER_DISPLAY_NAME", "USER_CHART_LABEL"):
            if column in result.columns:
                result[column] = [
                    value if not looks_like_user_id(value) else UNKNOWN_USER_LABEL
                    for value in result[column].tolist()
                ]
        if "USER_NAME" in result.columns:
            result["USER_NAME"] = [
                value if not looks_like_user_id(value) else UNKNOWN_USER_LABEL
                for value in result["USER_NAME"].tolist()
            ]
    return result


__all__ = [
    "apply_user_display_columns",
    "full_name",
    "looks_like_user_id",
    "sanitize_user_columns_for_export",
    "user_admin_label",
    "user_chart_label",
    "user_display_name",
    "user_name",
]
