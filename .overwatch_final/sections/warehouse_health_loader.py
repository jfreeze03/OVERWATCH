# sections/warehouse_health_loader.py - Warehouse Health load/session helpers.
from __future__ import annotations

from sections.base import lazy_util as _lazy_util


get_session_for_action = _lazy_util("get_session_for_action")


def _warehouse_action_session(action: str):
    return get_session_for_action(
        action,
        surface="Warehouse Health",
        offline_note="Warehouse shell, source summaries, and cached telemetry remain visible without a live connection.",
    )
