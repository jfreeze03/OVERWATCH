"""Compatibility facade for section dispatch.

The lazy loader lives in the top-level `section_dispatch` module so app shell
orchestration is not hidden inside the section package. Existing section imports
can keep using `sections.dispatch`.
"""
from __future__ import annotations

from section_dispatch import dispatch_section, reload_loaded_sections


def dispatch(active_section: str) -> None:
    """Backward-compatible wrapper for the shell section dispatcher."""
    dispatch_section(active_section)
