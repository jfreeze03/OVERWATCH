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

DAILY_CREDENTIAL_COLUMNS = (
    "User",
    "Credential",
    "Type",
    "Domain",
    "Status",
    "Expires",
    "Days left",
    "Last used",
    "Recommended action",
)


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


def credential_expiration_tile_from_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Return daily-safe Security Monitoring tile text from packet fields."""

    status = str(packet.get("SECURITY_CREDENTIAL_EXPIRATION_STATUS") or "").strip().lower()
    source_confirmed_zero = bool(packet.get("SECURITY_CREDENTIAL_SOURCE_CONFIRMED_ZERO"))
    expired_raw = packet.get("SECURITY_CREDENTIALS_EXPIRED_COUNT")
    due_30_raw = packet.get("SECURITY_CREDENTIALS_EXPIRING_30D_COUNT")
    due_7_raw = packet.get("SECURITY_CREDENTIALS_EXPIRING_7D_COUNT")
    if (
        status in {"pending", "unavailable", "source_pending"}
        or (expired_raw is None and due_30_raw is None and due_7_raw is None)
    ):
        return {
            "title": "Credential expirations",
            "value": "Credential expiration source pending",
            "detail": "Security source pending",
            "severity": "Watch",
            "available": False,
        }

    expired = int(float(expired_raw or 0))
    due_30 = int(float(due_30_raw or 0))
    due_7 = int(float(due_7_raw or 0))
    next_user = str(packet.get("SECURITY_CREDENTIAL_NEXT_EXPIRATION_USER") or "").strip()
    next_type = str(packet.get("SECURITY_CREDENTIAL_NEXT_EXPIRATION_TYPE") or "credential").strip()
    next_ts = packet.get("SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS")
    days_left = days_to_expiration(next_ts)

    if expired <= 0 and due_30 <= 0 and not source_confirmed_zero and status not in {"no_credentials_due", "clear"}:
        return {
            "title": "Credential expirations",
            "value": "Credential expiration source pending",
            "detail": "Security source pending",
            "severity": "Watch",
            "available": False,
        }
    if expired > 0:
        value = f"{expired} expired - {due_30} due within 30d"
        severity = "Critical"
    elif due_7 > 0:
        value = f"{due_7} due within 7d"
        severity = "High"
    elif due_30 > 0:
        value = f"{due_30} due within 30d"
        severity = "Medium"
    else:
        value = "No credentials due within 30d"
        severity = "Clear"

    if next_user and days_left is not None:
        detail = f"Next: {next_user} - {next_type} - {days_left}d"
    elif next_user:
        detail = f"Next: {next_user} - {next_type}"
    else:
        detail = "No credential expiration exposure in the selected window"
    return {
        "title": "Credential expirations",
        "value": value,
        "detail": detail,
        "severity": severity,
        "available": True,
        "numeric_value": expired + due_30,
    }


def credential_expiration_findings(frame: pd.DataFrame, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Build actionable daily-safe credential expiration findings."""

    enriched = enrich_credential_expiration_rows(frame, now=now)
    if enriched.empty:
        return []
    active = enriched[
        enriched["CREDENTIAL_EXPIRED_FLAG"].fillna(False)
        | enriched["CREDENTIAL_EXPIRING_30D_FLAG"].fillna(False)
    ].copy()
    if active.empty:
        return []
    findings: list[dict[str, Any]] = []
    for _, row in active.sort_values(["DAYS_TO_EXPIRATION", "EXPIRATION_DATE"], kind="mergesort").iterrows():
        user_name = str(row.get("USER_NAME") or row.get("NAME") or "UNKNOWN_USER").strip() or "UNKNOWN_USER"
        credential_id = str(row.get("CREDENTIAL_ID") or row.get("CREDENTIAL_NAME") or "credential").strip() or "credential"
        owner_name = str(row.get("USER_DISPLAY_NAME") or "Unknown user").strip() or "Unknown user"
        days_left = row.get("DAYS_TO_EXPIRATION")
        due_ts = row.get("EXPIRATION_DATE")
        severity = str(row.get("CREDENTIAL_EXPIRATION_SEVERITY") or "Medium")
        sla_state = "Overdue" if isinstance(days_left, (int, float)) and days_left < 0 else "Due soon"
        finding_key = f"CREDENTIAL_EXPIRING::{user_name}::{credential_id}"
        findings.append(
            {
                "FINDING_KEY": finding_key,
                "DEDUPE_KEY": finding_key,
                "SEVERITY": severity,
                "SIGNAL": "Credential expirations",
                "ENTITY_TYPE": "USER_CREDENTIAL",
                "ENTITY_ID": user_name,
                "ENTITY_NAME": owner_name,
                "OWNER_ID": user_name,
                "OWNER_NAME": owner_name,
                "EVIDENCE_ID": f"credential_expiration::{credential_id}",
                "DUE_TS": due_ts,
                "SLA_STATE": sla_state,
                "ROUTE_SECTION": "Security Monitoring",
                "ROUTE_WORKFLOW": "Credential Expirations",
                "RECOMMENDED_ACTION": "Rotate or renew credential before expiration.",
                "TARGET_USER_NAME": user_name,
                "TARGET_CREDENTIAL_KEY": credential_id,
                "raw_sql_included": False,
            }
        )
    return findings


def credential_evidence_daily_frame(frame: pd.DataFrame, *, now: datetime | None = None) -> pd.DataFrame:
    """Return daily visible credential evidence columns only."""

    enriched = sanitize_credential_export(frame, admin_only=False)
    if enriched.empty:
        return pd.DataFrame(columns=DAILY_CREDENTIAL_COLUMNS)
    result = pd.DataFrame(
        {
            "User": enriched.get("USER_DISPLAY_NAME", pd.Series(dtype=object)),
            "Credential": enriched.get("CREDENTIAL_NAME", pd.Series(dtype=object)),
            "Type": enriched.get("TYPE", enriched.get("CREDENTIAL_TYPE", pd.Series(dtype=object))),
            "Domain": enriched.get("DOMAIN", pd.Series(dtype=object)),
            "Status": enriched.get("STATUS", enriched.get("CREDENTIAL_STATUS", pd.Series(dtype=object))),
            "Expires": enriched.get("EXPIRATION_DATE", pd.Series(dtype=object)),
            "Days left": enriched.get("DAYS_TO_EXPIRATION", pd.Series(dtype=object)),
            "Last used": enriched.get("LAST_USED_ON", pd.Series(dtype=object)),
            "Recommended action": enriched.get("RECOMMENDED_ACTION", pd.Series(dtype=object)),
        }
    )
    return result.loc[:, list(DAILY_CREDENTIAL_COLUMNS)]


def make_credential_case_payload(
    frame: pd.DataFrame,
    *,
    scope: str,
    target: str = "",
    freshness: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a sanitized credential-expiration case payload."""

    enriched = enrich_credential_expiration_rows(frame, now=now)
    daily = credential_evidence_daily_frame(enriched, now=now)
    summary = credential_expiration_summary(enriched, now=now)
    return {
        "section": "Security Monitoring",
        "workflow": "Credential Expirations",
        "scope": scope,
        "target": target,
        "freshness": freshness,
        "source": "credential_expiration",
        "row_count": int(len(enriched)),
        "visible_row_count": int(len(daily)),
        "expired_count": int(summary.get("SECURITY_CREDENTIALS_EXPIRED_COUNT") or 0),
        "expiring_30d_count": int(summary.get("SECURITY_CREDENTIALS_EXPIRING_30D_COUNT") or 0),
        "next_expiration": summary.get("SECURITY_CREDENTIAL_NEXT_EXPIRATION_TS"),
        "owner_labels": sorted({str(value) for value in daily.get("User", pd.Series(dtype=object)).dropna().tolist()}),
        "recommended_action": "Rotate or renew credential before expiration.",
        "raw_sql_included": False,
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
    "DAILY_CREDENTIAL_COLUMNS",
    "credential_evidence_daily_frame",
    "credential_expiration_findings",
    "credential_expiration_summary",
    "credential_expiration_tile_from_packet",
    "days_to_expiration",
    "enrich_credential_expiration_rows",
    "expiration_bucket",
    "expiration_severity",
    "make_credential_case_payload",
    "sanitize_credential_export",
]
