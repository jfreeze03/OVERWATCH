"""Current-role access control helpers for OVERWATCH v2."""

from __future__ import annotations

from functools import lru_cache
import json
from typing import Any, Iterable


DEFAULT_ADMIN_ROLES = frozenset({"ACCOUNTADMIN", "SYSADMIN", "OVERWATCH_ADMIN"})


def _scalar(row: Any, *names: str) -> str:
    if row is None:
        return ""
    if isinstance(row, dict):
        for name in names:
            if name in row:
                return str(row.get(name) or "")
        return str(next(iter(row.values()), "") or "")
    for name in names:
        if hasattr(row, name):
            return str(getattr(row, name) or "")
    try:
        return str(row[0] or "")
    except Exception:
        return ""


def get_current_role(session: Any) -> str | None:
    """Read CURRENT_ROLE from Snowflake; offline or failed lookups never elevate."""
    if session is None or not callable(getattr(session, "sql", None)):
        return None
    try:
        rows = session.sql("SELECT CURRENT_ROLE() AS CURRENT_ROLE").collect()
    except Exception:
        return None
    if not rows:
        return None
    role = _scalar(rows[0], "CURRENT_ROLE", "CURRENT_ROLE()").strip().upper()
    return role or None


@lru_cache(maxsize=32)
def _admin_roles_from_settings(role_probe: str) -> frozenset[str]:
    del role_probe
    return DEFAULT_ADMIN_ROLES


def _settings_roles(settings: Any) -> set[str]:
    if not settings:
        return set(DEFAULT_ADMIN_ROLES)
    if isinstance(settings, dict):
        raw = settings.get("OVERWATCH_ADMIN_ROLES", "")
        return _parse_role_list(raw) or set(DEFAULT_ADMIN_ROLES)
    return set(DEFAULT_ADMIN_ROLES)


def _parse_role_list(raw: object) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return set()
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return {str(item).strip().upper() for item in parsed if str(item).strip()}
        return {item.strip().strip('"').upper() for item in text.strip("[]").split(",") if item.strip()}
    if isinstance(raw, Iterable):
        return {str(item).strip().upper() for item in raw if str(item).strip()}
    return set()


def admin_roles(session: Any = None, settings: Any = None) -> set[str]:
    """Return configured admin roles, falling back closed on lookup failure."""
    if settings:
        return _settings_roles(settings)
    if session is None or not callable(getattr(session, "sql", None)):
        return set(DEFAULT_ADMIN_ROLES)
    try:
        rows = session.sql(
            "SELECT SETTING_VALUE FROM OVERWATCH_SETTINGS "
            "WHERE SETTING_NAME IN ('OVERWATCH_ADMIN_ROLES','V2_ADMIN_ROLES','ADMIN_ACCESS_ROLES') "
            "ORDER BY CASE SETTING_NAME WHEN 'OVERWATCH_ADMIN_ROLES' THEN 1 WHEN 'V2_ADMIN_ROLES' THEN 2 ELSE 3 END"
        ).collect()
    except Exception:
        return set(DEFAULT_ADMIN_ROLES)
    if not rows:
        return set(DEFAULT_ADMIN_ROLES)
    raw = _scalar(rows[0], "SETTING_VALUE").strip()
    return _parse_role_list(raw) or set(DEFAULT_ADMIN_ROLES)


def is_admin(session: Any = None, settings: Any = None) -> bool:
    role = get_current_role(session)
    if not role:
        return False
    return role in admin_roles(session, settings)
