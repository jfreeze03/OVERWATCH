"""Snowflake-backed settings access with constant fallbacks.

The provider intentionally reuses an already-open app session only. It must not
open Snowflake from first paint or root imports just to replace config constants.
"""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from runtime_state import SF_SESSION, ensure_default_state, get_state, record_runtime_event
from utils.performance import is_first_paint_active
from utils.sql_safe import sql_literal


SETTINGS_CACHE_TTL_SECONDS = 300
_SETTINGS_CACHE_KEY = "_overwatch_settings_provider_cache"


def _row_to_mapping(row: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    if hasattr(row, "as_dict"):
        try:
            return row.as_dict()
        except Exception:
            return {}
    return {}


def _parse_setting_value(value: Any, value_type: str = "") -> Any:
    if value is None:
        return None
    normalized_type = str(value_type or "").strip().upper()
    if normalized_type in {"JSON", "ARRAY", "OBJECT", "VARIANT"}:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return None
        return value
    return value


def _cache() -> dict[str, tuple[float, Any]]:
    try:
        return ensure_default_state(_SETTINGS_CACHE_KEY, {})
    except Exception:
        return {}


def _cached_value(setting_name: str) -> Any:
    cache = _cache()
    entry = cache.get(setting_name.upper())
    if not entry:
        return None
    cached_at, value = entry
    if time.time() - float(cached_at or 0) > SETTINGS_CACHE_TTL_SECONDS:
        cache.pop(setting_name.upper(), None)
        return None
    return value


def _store_cached_value(setting_name: str, value: Any) -> None:
    try:
        _cache()[setting_name.upper()] = (time.time(), value)
    except Exception:
        pass


def _record_settings_fallback(setting_name: str, reason: str) -> None:
    try:
        record_runtime_event(
            event_type="settings_provider",
            boundary="metadata_bounded",
            query_tier="settings",
            ttl_key=setting_name,
            cache_hit=False,
            raw_sql_included=False,
            extra={
                "settings_fallback_used": True,
                "fallback_reason": reason[:120],
            },
        )
    except Exception:
        pass


def get_setting(setting_name: str, default: Any = None) -> Any:
    """Return a governed setting when safely available, otherwise ``default``.

    A missing session or active first-paint render is treated as an intentional
    fallback. This preserves the app's packet-only first paint while allowing
    user-triggered/admin paths to pick up Snowflake-managed settings.
    """
    normalized_name = str(setting_name or "").strip().upper()
    if not normalized_name:
        return default

    cached = _cached_value(normalized_name)
    if cached is not None:
        return cached

    if is_first_paint_active():
        _record_settings_fallback(normalized_name, "first_paint")
        return default

    session = get_state(SF_SESSION, None)
    if session is None:
        _record_settings_fallback(normalized_name, "session_unavailable")
        return default

    try:
        rows = session.sql(
            f"""
SELECT SETTING_VALUE, VALUE_TYPE
FROM OVERWATCH_SETTINGS
WHERE UPPER(SETTING_NAME) = UPPER({sql_literal(normalized_name)})
LIMIT 1
"""
        ).collect()
    except Exception as exc:
        _record_settings_fallback(normalized_name, f"settings_query_failed:{type(exc).__name__}")
        return default
    if not rows:
        _record_settings_fallback(normalized_name, "setting_missing")
        return default

    row = _row_to_mapping(rows[0])
    parsed = _parse_setting_value(row.get("SETTING_VALUE"), str(row.get("VALUE_TYPE", "")))
    if parsed is None:
        _record_settings_fallback(normalized_name, "setting_unparseable")
        return default
    _store_cached_value(normalized_name, parsed)
    return parsed


def get_string_setting(setting_name: str, default: str = "") -> str:
    value = get_setting(setting_name, default)
    text = str(value or "").strip()
    return text or default


def get_string_list_setting(setting_name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    value = get_setting(setting_name, list(default))
    if isinstance(value, str):
        candidates = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(part or "").strip() for part in value]
    else:
        candidates = []
    clean = tuple(part for part in candidates if part)
    return clean or tuple(default)


def get_default_alert_recipients(default: tuple[str, ...] = ()) -> tuple[str, ...]:
    return get_string_list_setting("DEFAULT_ALERT_EMAILS", default)


def get_default_alert_recipient(default: str = "") -> str:
    defaults = tuple(part.strip() for part in str(default or "").split(",") if part.strip())
    recipients = get_default_alert_recipients(defaults)
    return ",".join(recipients) or default
