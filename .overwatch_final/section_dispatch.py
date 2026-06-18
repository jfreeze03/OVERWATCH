"""Lazy section dispatch for OVERWATCH.

The shell calls this module to load only the selected monitoring section. The
`sections` package re-exports these functions for existing internal callers.
"""
from __future__ import annotations

import importlib

import streamlit as st

from config import SECTION_MODULES, normalize_section_name


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

    if module_path not in _loaded:
        try:
            _loaded[module_path] = importlib.import_module(module_path)
        except ImportError as exc:
            from utils.query import format_snowflake_error

            st.error(f"Failed to load section `{active_section}`: {format_snowflake_error(exc)}")
            return

    _loaded[module_path].render()
