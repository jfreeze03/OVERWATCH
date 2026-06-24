"""Lazy section dispatch for OVERWATCH.

The shell calls this module to load only the selected monitoring section. The
`sections` package re-exports these functions for existing internal callers.
"""
from __future__ import annotations

import importlib

import streamlit as st

from config import SECTION_MODULES, normalize_section_name
from perf_trace import record_phase, trace


_loaded: dict[str, object] = {}


def reload_loaded_sections() -> None:
    """Reload lazy-loaded section modules after shared UI/helper changes."""
    for module_path, module in list(_loaded.items()):
        try:
            _loaded[module_path] = importlib.reload(module)
        except Exception:
            _loaded.pop(module_path, None)


def dispatch_section(active_section: str) -> None:
    """Lazy-load and render the selected OVERWATCH section."""
    active_section = normalize_section_name(active_section)
    module_path = SECTION_MODULES.get(active_section)

    if not module_path:
        st.warning(
            f"Section `{active_section}` is not registered. "
            "Check config.py SECTION_MODULES and NAV_GROUPS."
        )
        return

    module_cached = module_path in _loaded
    if not module_cached:
        try:
            with trace(
                f"section_dispatch:module_import:{module_path}",
                active_section=active_section,
                detail={"module_cached": False},
            ):
                _loaded[module_path] = importlib.import_module(module_path)
        except ImportError as exc:
            from utils.query import format_snowflake_error

            st.error(f"Failed to load section `{active_section}`: {format_snowflake_error(exc)}")
            return
    else:
        record_phase(
            f"section_dispatch:module_cached:{module_path}",
            active_section=active_section,
            detail={"module_cached": True},
        )

    with trace(
        f"section_dispatch:render:{active_section}",
        active_section=active_section,
        detail={"module_cached": module_cached},
    ):
        _loaded[module_path].render()
