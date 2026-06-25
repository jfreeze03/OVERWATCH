"""Session-only Operator Case File helpers.

The case file is a handoff artifact builder. It never loads Snowflake data;
sections must pass already-loaded summaries or preview rows explicitly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
from typing import Any

import streamlit as st

from utils.downloads import download_text


CASE_STATE_KEY = "operator_case_items"
_PREVIEW_LIMIT = 5


@dataclass(frozen=True)
class CaseEvidenceItem:
    """One operator-selected evidence summary for the current handoff packet."""

    section: str
    workflow: str
    scope: str
    freshness: str
    source: str
    summary: str
    next_action: str
    evidence_rows_preview: tuple[dict[str, str], ...] = ()
    created_at: str = ""


def _now_label() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _state(state: MutableMapping[str, Any] | None = None) -> MutableMapping[str, Any]:
    return st.session_state if state is None else state


def _clean_cell(value: object) -> str:
    text = str(value if value is not None else "").replace("\r", " ").replace("\n", " ").strip()
    return text[:220]


def preview_rows(rows: object, *, limit: int = _PREVIEW_LIMIT) -> tuple[dict[str, str], ...]:
    """Return a compact, serializable row preview from explicit loaded data."""

    if rows is None:
        return ()
    if hasattr(rows, "head") and hasattr(rows, "to_dict"):
        records = rows.head(limit).to_dict("records")
    elif isinstance(rows, Mapping):
        records = [rows]
    else:
        records = list(rows)[:limit] if isinstance(rows, Iterable) and not isinstance(rows, (str, bytes)) else []
    preview: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        preview.append({str(key): _clean_cell(value) for key, value in list(record.items())[:8]})
    return tuple(preview)


def make_case_evidence(
    *,
    section: str,
    workflow: str,
    scope: str,
    freshness: str,
    source: str,
    summary: str,
    next_action: str,
    evidence_rows_preview: object = (),
    created_at: str = "",
) -> CaseEvidenceItem:
    """Build a case item from already-loaded section data."""

    return CaseEvidenceItem(
        section=str(section or "Unknown section"),
        workflow=str(workflow or "Current view"),
        scope=str(scope or "Current scope"),
        freshness=str(freshness or "Freshness not recorded"),
        source=str(source or "Loaded session data"),
        summary=str(summary or "No summary provided."),
        next_action=str(next_action or "Review loaded evidence."),
        evidence_rows_preview=preview_rows(evidence_rows_preview),
        created_at=str(created_at or _now_label()),
    )


def add_case_evidence(item: CaseEvidenceItem | Mapping[str, Any], state: MutableMapping[str, Any] | None = None) -> int:
    """Add explicit evidence to the session case file and return the new count."""

    target = _state(state)
    if isinstance(item, CaseEvidenceItem):
        payload = asdict(item)
    else:
        payload = asdict(make_case_evidence(**dict(item)))
    items = list(target.get(CASE_STATE_KEY) or [])
    items.append(payload)
    target[CASE_STATE_KEY] = items
    return len(items)


def current_case_items(state: MutableMapping[str, Any] | None = None) -> tuple[CaseEvidenceItem, ...]:
    """Return current case items from session state."""

    items: list[CaseEvidenceItem] = []
    for raw in list(_state(state).get(CASE_STATE_KEY) or []):
        if isinstance(raw, CaseEvidenceItem):
            items.append(raw)
        elif isinstance(raw, Mapping):
            rows = raw.get("evidence_rows_preview") or ()
            items.append(
                CaseEvidenceItem(
                    section=str(raw.get("section") or "Unknown section"),
                    workflow=str(raw.get("workflow") or "Current view"),
                    scope=str(raw.get("scope") or "Current scope"),
                    freshness=str(raw.get("freshness") or "Freshness not recorded"),
                    source=str(raw.get("source") or "Loaded session data"),
                    summary=str(raw.get("summary") or "No summary provided."),
                    next_action=str(raw.get("next_action") or "Review loaded evidence."),
                    evidence_rows_preview=preview_rows(rows),
                    created_at=str(raw.get("created_at") or ""),
                )
            )
    return tuple(items)


def clear_case(state: MutableMapping[str, Any] | None = None) -> None:
    """Clear the session case file."""

    _state(state).pop(CASE_STATE_KEY, None)


def _markdown_table(rows: Sequence[Mapping[str, str]]) -> str:
    if not rows:
        return ""
    columns = tuple(rows[0].keys())
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(_clean_cell(row.get(col, "")).replace("|", "\\|") for col in columns) + " |")
    return "\n".join([header, divider, *body])


def build_case_markdown(items: Sequence[CaseEvidenceItem] | None = None) -> str:
    """Build a concise DBA handoff packet from session case items."""

    case_items = tuple(items if items is not None else current_case_items())
    generated_at = _now_label()
    lines = [
        "# OVERWATCH Operator Case File",
        "",
        f"- Generated: {generated_at}",
        f"- Evidence items: {len(case_items)}",
        "",
    ]
    if not case_items:
        lines.extend([
            "No evidence has been added yet.",
            "",
            "Load section evidence explicitly, then use Add to Case.",
        ])
        return "\n".join(lines).strip() + "\n"

    by_section: dict[str, list[CaseEvidenceItem]] = {}
    for item in case_items:
        by_section.setdefault(item.section, []).append(item)

    for section in sorted(by_section):
        lines.extend([f"## {section}", ""])
        for item in by_section[section]:
            lines.extend(
                [
                    f"### {item.workflow}",
                    "",
                    f"- Scope: {item.scope}",
                    f"- Freshness: {item.freshness}",
                    f"- Source: {item.source}",
                    f"- Captured: {item.created_at or 'Not recorded'}",
                    f"- Summary: {item.summary}",
                    f"- Recommended next action: {item.next_action}",
                    "",
                ]
            )
            table = _markdown_table(item.evidence_rows_preview)
            if table:
                lines.extend(["Evidence preview:", "", table, ""])
    return "\n".join(lines).strip() + "\n"


def render_add_to_case_button(
    item: CaseEvidenceItem | None,
    *,
    key: str,
    unavailable_message: str = "Load evidence first before adding it to the case file.",
) -> bool:
    """Render an explicit local-session Add to Case action."""

    if item is None:
        st.caption(unavailable_message)
        return False
    if st.button("Add to Case", key=key, width="stretch"):
        add_case_evidence(item)
        st.success("Added loaded evidence to the Operator Case File.")
        return True
    return False


def render_case_drawer() -> None:
    """Render a compact case drawer and explicit markdown export."""

    items = current_case_items()
    with st.expander(f"Operator Case File ({len(items)})", expanded=False):
        if not items:
            st.caption("No evidence added yet. Load evidence explicitly, then add it to the case file.")
            return
        sections = ", ".join(sorted({item.section for item in items}))
        st.caption(f"Sections represented: {sections}")
        missing_freshness = [item for item in items if "not" in item.freshness.lower() or not item.freshness.strip()]
        if missing_freshness:
            st.warning("One or more case items have missing or stale freshness notes.")
        for idx, item in enumerate(items, start=1):
            st.markdown(f"**{idx}. {escape(item.section)} / {escape(item.workflow)}**")
            st.caption(f"{item.scope} | {item.freshness} | {item.source}")
            st.caption(item.summary)
            if item.evidence_rows_preview:
                st.caption(f"Preview rows: {len(item.evidence_rows_preview)}")
        markdown = build_case_markdown(items)
        download_text(
            markdown,
            "overwatch_operator_case_file.md",
            label="Export Case Markdown",
            mime="text/markdown",
            key="operator_case_markdown",
        )
        if st.button("Clear Case File", key="operator_case_clear", width="stretch"):
            clear_case()
            st.rerun()


__all__ = [
    "CASE_STATE_KEY",
    "CaseEvidenceItem",
    "add_case_evidence",
    "build_case_markdown",
    "clear_case",
    "current_case_items",
    "make_case_evidence",
    "preview_rows",
    "render_add_to_case_button",
    "render_case_drawer",
]
