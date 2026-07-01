"""Credential-expiration helpers for Security Monitoring.

The live Snowflake source is compacted during refresh; daily UI should consume
packet or mart rows, never query credential metadata on first paint.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from .user_display import apply_user_display_columns, sanitize_user_columns_for_export


ADMIN_ONLY_CREDENTIAL_COLUMNS = {
    "USER_ID",
    "CREDENTIAL_ID",
    "SOURCE_FAMILY",
    "SOURCE_OBJECT",
    "RAW_SQL",
}


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def days_to_expiration(expiration_date: Any, *, now: datetime | None = None) -> int | None:
    expires = _as_datetime(expiration_date)
    if expires is None:
        return None
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return int((expires.date() - current.date()).days)


def expiration_bucket(days_left: int | None) -> str:
    if days_left is None:
        return "no_expiration"
    if days_left < 0:
        return "expired"
    if days_left <= 7:
        return "expires_0_7_days"
    if days_left <= 30:
        return "expires_8_30_days"
    return "ok"


def expiration_severity(bucket: str) -> str:
    if bucket == "expired":
        return "Critical"
    if bucket == "expires_0_7_days":
        return "High"
    if bucket == "expires_8_30_days":
        return "Medium"
    return "Info"


def enrich_credential_expiration_rows(frame: pd.DataFrame, *, now: datetime | None = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame.copy()
    result = apply_user_display_columns(frame)
    days = [days_to_expiration(value, now=now) for value in result.get("EXPIRATION_DATE", pd.Series(dtype=object))]
    result["DAYS_TO_EXPIRATION"] = days
    result["EXPIRATION_BUCKET"] = [expiration_bucket(value) for value in days]
    result["CREDENTIAL_EXPIRING_30D_FLAG"] = [value is not None and 0 <= value <= 30 for value in days]
    result["CREDENTIAL_EXPIRING_7D_FLAG"] = [value is not None and 0 <= value <= 7 for value in days]
    result["CREDENTIAL_EXPIRED_FLAG"] = [value is not None and value < 0 for value in days]
    result["CREDENTIAL_EXPIRATION_SEVERITY"] = [
        expiration_severity(bucket) for bucket in result["EXPIRATION_BUCKET"].tolist()
    ]
    result["RECOMMENDED_ACTION"] = [
        "Rotate or renew credential before expiration."
        if bucket in {"expired", "expires_0_7_days", "expires_8_30_days"}
        else "No action needed."
        for bucket in result["EXPIRATION_BUCKET"].tolist()
    ]
    return result


def credential_expiration_summary(frame: pd.DataFrame, *, now: datetime | None = None) -> dict[str, Any]:
    enriched = enrich_credential_expiration_rows(frame, now=now)
    if enriched.empty:
        return {
            "SECURITY_CREDENTIALS_EXPIRING_30D_COUNT": 0,
            "SECURITY_CREDENTIALS_EXPIRING_7D_COUNT": 0,
            "SECURITY_CREDENTIALS_EXPIRED_COUNT": 0,
            "SECURITY_CREDENTIAL_EXPIRATION_STATUS": "no_credentials_due",
            "SECURITY_CREDENTIAL_EXPIRATION_FINDINGS": [],
        }
    due_or_expired = enriched[
        enriched["CREDENTIAL_EXPIRING_30D_FLAG"].fillna(False)
        | enriched["CREDENTIAL_EXPIRED_FLAG"].fillna(False)
    ].copy()
    if not due_or_expired.empty:
        due_or_expired = due_or_expired.sort_values("DAYS_TO_EXPIRATION", ascending=True, kind="mergesort")
    next_row = due_or_expired.iloc[0].to_dict() if not due_or_expired.empty else {}
    return {
        "SECURITY_CREDENTIALS_EXPIRING_30D_COUNT": int(enriched["CREDENTIAL_EXPIRING_30D_FLAG"].sum()),
        "SECURITY_CREDENTIALS_EXPIRING_7D_COUNT": int(enriched["CREDENTIAL_EXPIRING_7D_FLAG"].sum()),
        "SECURITY_CREDENTIALS_EXPIRED_COUNT": int(enriched["CREDENTIAL_EXPIRED_FLAG"].sum()),
        "SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS": next_row.get("EXPIRATION_DATE"),
        "SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER": next_row.get("USER_DISPLAY_NAME"),
        "SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE": next_row.get("TYPE"),
        "SECURITY_CREDENTIAL_EXPIRATION_STATUS": "due_or_expired" if not due_or_expired.empty else "no_credentials_due",
        "SECURITY_CREDENTIAL_EXPIRATION_FINDINGS": due_or_expired.to_dict(orient="records"),
    }


def sanitize_credential_export(frame: pd.DataFrame, *, admin_only: bool = False) -> pd.DataFrame:
    result = sanitize_user_columns_for_export(enrich_credential_expiration_rows(frame), admin_only=admin_only)
    if not admin_only:
        result = result.drop(
            columns=[column for column in result.columns if column.upper() in ADMIN_ONLY_CREDENTIAL_COLUMNS],
            errors="ignore",
        )
    return result


__all__ = [
    "credential_expiration_summary",
    "days_to_expiration",
    "enrich_credential_expiration_rows",
    "expiration_bucket",
    "expiration_severity",
    "sanitize_credential_export",
]
