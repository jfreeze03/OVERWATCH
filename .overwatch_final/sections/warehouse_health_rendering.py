# sections/warehouse_health_rendering.py - Small shared Warehouse Health rendering helpers.
from __future__ import annotations

from utils.section_guidance import defer_section_note


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")
