# sections/warehouse_health_view_advisor.py - Warehouse Health advisor workflow renderer.
from __future__ import annotations

from sections.base import lazy_util as _lazy_util


render_optimization_advisor = _lazy_util("render_optimization_advisor")


def _render_warehouse_advisor_view() -> None:
    render_optimization_advisor()
