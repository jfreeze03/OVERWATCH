"""Render-scoped performance helpers for primary Decision Workspace sections."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar

from performance import begin_first_paint, end_first_paint


T = TypeVar("T")


@contextmanager
def with_decision_first_paint(section: str, workflow: str = "") -> Iterator[str]:
    """Open and always close a first-paint window around the compact workspace render."""
    render_id = begin_first_paint(section, workflow)
    try:
        yield render_id
    finally:
        end_first_paint(render_id)


def render_with_decision_first_paint(section: str, workflow: str, callback: Callable[[], T]) -> T:
    """Run a callback inside a first-paint telemetry window."""
    with with_decision_first_paint(section, workflow):
        return callback()


__all__ = ["render_with_decision_first_paint", "with_decision_first_paint"]
