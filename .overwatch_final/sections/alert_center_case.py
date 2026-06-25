from __future__ import annotations

from typing import Any, Iterable

from sections.operator_case import make_case_evidence, render_add_to_case_button


def _case_key(source_view: str) -> str:
    normalized = str(source_view).lower().replace(" ", "_").replace("&", "and")
    return f"alert_center_add_to_case_{normalized}"


def render_alert_center_add_to_case(
    source_view: str,
    company: str,
    environment: str,
    days: int,
    limit: int,
    data: dict[str, Any],
    loaded_summary: dict[str, Any],
    loaded_sources: Iterable[str],
    open_alert_count: int,
    critical_high_count: int,
    overdue_count: int,
    open_queue_count: int,
    exception_rows: Any,
    alerts: Any,
) -> None:
    render_add_to_case_button(
        make_case_evidence(
            section="Alert Center",
            workflow=source_view,
            scope=f"{company} / {environment} / {days} days / limit {limit:,}",
            freshness=str(data.get("loaded_at") or loaded_summary.get("freshness") or "Loaded alert data"),
            source=", ".join(sorted(loaded_sources)) or f"{source_view} loaded sources",
            summary=(
                f"{open_alert_count:,} open alerts, {critical_high_count:,} critical/high, "
                f"{overdue_count:,} overdue, {open_queue_count:,} open queue item(s)."
            ),
            next_action="Review priority alerts and route the highest-severity open issue.",
            evidence_rows_preview=exception_rows if not getattr(exception_rows, "empty", True) else alerts,
        ),
        key=_case_key(source_view),
    )
