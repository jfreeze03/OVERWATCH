"""App-level Snowflake access and role checks for OVERWATCH.

The shell uses this module to decide whether it can render protected DBA
surfaces. Section-level dangerous actions still apply their own review gates.
"""
from __future__ import annotations

import threading
from pathlib import Path

import streamlit as st

from config import ADMIN_ACCESS_ROLES
from runtime_state import (
    ACCESS_GATE_STATE,
    ADMIN_CONNECTION_TEST_COUNT,
    CONNECTION_AVAILABLE,
    CONNECTION_UNAVAILABLE,
    CURRENT_ROLE,
    CURRENT_ROLE_SOURCE,
    LAST_ALLOWED_ROLE,
    get_state,
    set_state,
)


_SNOWFLAKE_AVAILABLE_PROCESS_CACHE: bool | None = None
_SNOWFLAKE_AVAILABLE_LOCK = threading.Lock()
_SNOWFLAKE_AVAILABLE_LOCK_WAIT_SECONDS = 0.25

_SENSITIVE_ERROR_MARKERS = (
    "token",
    "password",
    "secret",
    "private key",
    "credwrite",
    "traceback",
)


def seed_current_role_from_secrets() -> None:
    """Use configured Snowflake role as a zero-query startup hint when present."""
    if get_state(CURRENT_ROLE):
        return
    try:
        connections = st.secrets.get("connections", {})
        snowflake_cfg = connections.get("snowflake", {}) if connections else {}
        role = str(snowflake_cfg.get("role") or "").strip().upper()
    except Exception:
        role = ""
    if role:
        set_state(CURRENT_ROLE, role)
        set_state(CURRENT_ROLE_SOURCE, "secrets")
        if current_role_allows_app_access(role):
            set_state(LAST_ALLOWED_ROLE, role)


def get_current_role() -> str:
    """Return the current Snowflake role captured for the shell."""
    return str(get_state(CURRENT_ROLE, "") or "").upper()


def get_last_allowed_role() -> str:
    """Return the last captured admin role for smooth reruns during scope changes."""
    return str(get_state(LAST_ALLOWED_ROLE, "") or "").upper()


def get_stable_current_role() -> str:
    """Return the captured role, falling back to the last allowed role during transient reruns."""
    return get_current_role() or get_last_allowed_role()


def current_role_allows_app_access(role: str) -> bool:
    """Return whether the current Snowflake role may open the admin monitor."""
    return str(role or "").strip().upper() in set(ADMIN_ACCESS_ROLES)


def refresh_current_role_for_access(connection_available: bool) -> str:
    """Return the cached role without opening a session during shell paint.

    The first packet query owns the initial Snowflake session boundary. Opening
    a session from the shell just to render navigation makes first-paint proof
    ambiguous, so role capture is deferred until a packet/action path already
    has a justified boundary.
    """
    role = get_current_role()
    if not connection_available:
        return role or get_last_allowed_role()
    if role and get_state(CURRENT_ROLE_SOURCE) == "session":
        return role
    if role and get_state(CURRENT_ROLE_SOURCE) == "secrets":
        return role
    return get_stable_current_role()


def _bump_counter(key: str) -> None:
    set_state(key, int(get_state(key, 0) or 0) + 1)


def _set_access_gate_state(value: str) -> None:
    set_state(ACCESS_GATE_STATE, value)


def _sanitize_connection_error(exc: BaseException) -> str:
    """Return a daily-safe connection-test error without paths, SQL, or secrets."""
    text = str(exc or "").strip()
    if not text:
        return "Connection test failed."
    lower = text.lower()
    if any(marker in lower for marker in _SENSITIVE_ERROR_MARKERS):
        return "Connection test failed with a sanitized credential or runtime error."
    # Strip obvious local path fragments from Snowflake CLI/runtime messages.
    parts = []
    for token in text.replace("\\", "/").split():
        if ":/" in token or token.startswith("/") or Path(token).suffix.lower() in {".sql", ".txt", ".json"}:
            parts.append("[redacted-path]")
        else:
            parts.append(token)
    cleaned = " ".join(parts)
    if len(cleaned) > 240:
        cleaned = cleaned[:237].rstrip() + "..."
    return cleaned or "Connection test failed."


def _declared_snowflake_connection_configured() -> bool:
    """Return whether secrets/config declare Snowflake without opening a session."""
    try:
        connections = st.secrets.get("connections", {})
        snowflake_cfg = connections.get("snowflake", {}) if connections else {}
        return bool(snowflake_cfg)
    except Exception:
        return False


def cached_snowflake_available(default: bool = False) -> bool:
    """Return cached connection availability without probing Snowflake."""
    return bool(get_state(CONNECTION_AVAILABLE, default))


def cached_or_declared_snowflake_available(default: bool = False) -> bool:
    """Return cached or declared availability without opening/probing Snowflake."""
    global _SNOWFLAKE_AVAILABLE_PROCESS_CACHE
    if CONNECTION_AVAILABLE in st.session_state:
        available = cached_snowflake_available(default=default)
        _set_access_gate_state("cached_available" if available else "cached_unavailable")
        return available
    if _SNOWFLAKE_AVAILABLE_PROCESS_CACHE is not None:
        available = bool(_SNOWFLAKE_AVAILABLE_PROCESS_CACHE)
        set_state(CONNECTION_AVAILABLE, available)
        set_state(CONNECTION_UNAVAILABLE, not available)
        _set_access_gate_state("process_cached_available" if available else "process_cached_unavailable")
        return available
    declared = _declared_snowflake_connection_configured()
    if declared:
        set_state(CONNECTION_AVAILABLE, True)
        set_state(CONNECTION_UNAVAILABLE, False)
        _set_access_gate_state("declared_unprobed")
        return True
    _set_access_gate_state("unknown_unprobed")
    return bool(default)


def admin_access_is_allowed(role: str, connection_available: bool) -> bool:
    """Allow local no-connection shells, but gate Snowflake sessions to admin roles."""
    if not connection_available:
        return True
    return current_role_allows_app_access(role or get_last_allowed_role())


def get_session(*args, **kwargs):
    """Lazy admin-test session hook kept patchable without root import side effects."""
    from utils.session import get_session as _get_session

    return _get_session(*args, **kwargs)


def explicit_admin_connection_test() -> bool:
    """Run the real connection test only from explicit admin/setup actions."""
    global _SNOWFLAKE_AVAILABLE_PROCESS_CACHE
    _bump_counter(ADMIN_CONNECTION_TEST_COUNT)
    acquired = _SNOWFLAKE_AVAILABLE_LOCK.acquire(blocking=False)
    if not acquired:
        acquired = _SNOWFLAKE_AVAILABLE_LOCK.acquire(blocking=True)
    try:
        try:
            from streamlit.runtime.scriptrunner import StopException

            get_session(
                reason="explicit_admin_connection_test",
                query_boundary="explicit_connection_test",
                section="Settings/Admin Setup Health",
                defer_role_capture=True,
            )
            available = True
            sanitized_error = ""
        except StopException:
            available = False
            sanitized_error = "Connection test stopped cleanly."
        except Exception as exc:
            available = False
            sanitized_error = _sanitize_connection_error(exc)
        set_state(CONNECTION_AVAILABLE, available)
        set_state(CONNECTION_UNAVAILABLE, not available)
        set_state("_overwatch_connection_test_error", sanitized_error)
        _SNOWFLAKE_AVAILABLE_PROCESS_CACHE = available
        _set_access_gate_state("admin_connection_test_available" if available else "admin_connection_test_unavailable")
        return available
    finally:
        if acquired:
            _SNOWFLAKE_AVAILABLE_LOCK.release()


def probe_snowflake_available(force: bool = False) -> bool:
    """Return availability without shell-time Snowflake probes unless forced."""
    if force:
        return explicit_admin_connection_test()
    if not force and _SNOWFLAKE_AVAILABLE_PROCESS_CACHE is not None:
        return cached_or_declared_snowflake_available(default=False)
    # Non-forced probes are intentionally cache/config only. Do not call
    # get_active_session here; that silently opens the shell-time Snowflake
    # boundary that first-paint release proof is designed to catch.
    return cached_or_declared_snowflake_available(default=False)


__all__ = [
    "admin_access_is_allowed",
    "cached_or_declared_snowflake_available",
    "cached_snowflake_available",
    "current_role_allows_app_access",
    "explicit_admin_connection_test",
    "get_current_role",
    "get_last_allowed_role",
    "get_stable_current_role",
    "probe_snowflake_available",
    "refresh_current_role_for_access",
    "seed_current_role_from_secrets",
]
