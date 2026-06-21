"""Backward-compatible facade for the DBA Control Room package."""
from __future__ import annotations

from . import health as _health
from . import render as _render
from .render import *  # noqa: F403


def _sync_patchable_dependencies() -> None:
    """Keep legacy package-level monkeypatches visible to moved loaders."""
    for name in ("run_query", "load_action_queue"):
        if name in globals():
            setattr(_health, name, globals()[name])


def _load_control_room(*args, **kwargs):
    _sync_patchable_dependencies()
    return _health._load_control_room(*args, **kwargs)


render = _render.render

__all__ = [name for name in globals() if not name.startswith("__") and name != "annotations"]
