"""DBA Control Room - operational landing page for OVERWATCH.

This page is intentionally workflow-first. It summarizes exceptions that a DBA
must triage, routes each signal to the right specialist tool, and creates
report-ready notes for leadership without making executives use the app.

The implementation is split across cohesive submodules (``types``, ``health``,
``queue``, ``incidents``, ``data``, ``handoff`` and ``render``). This package
re-exports every public symbol so the historical
``from sections.dba_control_room import ...`` and ``sections.dba_control_room``
import paths keep working unchanged.
"""
from __future__ import annotations

from . import types, health, queue, incidents, data, handoff, render as _render_module

for _mod in (types, health, queue, incidents, data, handoff, _render_module):
    for _name, _value in vars(_mod).items():
        if not _name.startswith("__"):
            globals()[_name] = _value

# Ensure the package-level ``render`` attribute is the entrypoint function (the
# app dispatches ``sections.dba_control_room.render()``), not the submodule.
render = _render_module.render

del _mod, _name, _value
