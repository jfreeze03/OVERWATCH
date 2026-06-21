"""Backward-compatible DBA Control Room section facade."""

from __future__ import annotations

from . import render as _render

for _name in dir(_render):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_render, _name)

__all__ = [_name for _name in globals() if not _name.startswith("__")]
