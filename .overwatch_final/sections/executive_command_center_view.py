"""Executive Landing command-center first viewport."""

from __future__ import annotations

import streamlit as st

from sections.command_center_components import (
    render_attention_panel,
    render_coco_ai_summary,
    render_coco_credit_consumption_panel,
    render_coco_kpi_row,
    render_coco_score_section,
    render_coco_warehouse_panel,
    render_operational_context_panel,
    render_recent_status_alerts_panel,
)
from sections.command_center_models import ExecutiveCommandCenterModel, build_executive_command_center_model
from sections.section_command_brief import SectionCommandBrief


def _render_recommended_actions_panel(model: ExecutiveCommandCenterModel) -> tuple[bool, bool]:
    """Render command-center action rows with real Streamlit buttons."""
    refresh_requested = False
    snapshot_requested = False
    with st.container(key="executive_cc_recommended_actions_panel", border=False):
        st.html(
            '<section class="ow-cc-card ow-cc-action-panel-heading" aria-label="Recommended Action">'
            '<header><h3>Recommended Action</h3><span aria-hidden="true">i</span></header>'
            "</section>"
        )
        for action in model.actions[:2]:
            label_col, button_col = st.columns([3.2, 1.6])
            with label_col:
                st.html(
                    '<div class="ow-cc-action-row-copy">'
                    f'<strong>{action.label}</strong>'
                    f'<small>{action.detail}</small>'
                    "</div>"
                )
            with button_col:
                if action.key == "refresh":
                    refresh_requested = bool(
                        st.button(
                            action.button_label,
                            key="executive_landing_command_brief_refresh_packet",
                            help="Refresh the Executive Landing summary packet for the current scope.",
                            width="stretch",
                        )
                    )
                elif action.key == "load_snapshot":
                    snapshot_requested = bool(
                        st.button(
                            action.button_label,
                            key="executive_cc_load_snapshot",
                            help="Load the heavier Executive Landing evidence snapshot for the selected scope.",
                            type="primary",
                            width="stretch",
                        )
                    )
    return refresh_requested, snapshot_requested


def render_executive_command_center_page(
    brief: SectionCommandBrief,
    *,
    company: str,
    environment: str,
    days: int,
    snapshot_loaded: bool = False,
    summary_frame: object = None,
) -> tuple[bool, bool]:
    """Render the redesigned Executive Landing command center.

    Returns ``(refresh_requested, snapshot_requested)`` so the shell keeps
    existing packet-refresh and explicit evidence-load boundaries.
    """
    model = build_executive_command_center_model(
        brief,
        company=company,
        environment=environment,
        days=int(days),
        snapshot_loaded=bool(snapshot_loaded),
        summary_frame=summary_frame,
    )
    st.html(
        '<main class="ow-cc-page ow-kit-command-brief" aria-label="Executive Landing command-center dashboard">'
        '<div class="ow-cc-page-marker ow-decision-workspace-marker" aria-hidden="true"></div>'
        "</main>"
    )
    render_coco_ai_summary(model)
    render_coco_score_section(model)
    render_coco_kpi_row(model)

    top_left, top_right = st.columns([1.38, 1.0], gap="small")
    with top_left:
        render_coco_credit_consumption_panel(model)
    with top_right:
        render_coco_warehouse_panel(model)

    mid_left, mid_right = st.columns([1.15, 1.0], gap="small")
    with mid_left:
        render_attention_panel(model)
    with mid_right:
        refresh_requested, snapshot_requested = _render_recommended_actions_panel(model)

    bottom_left, bottom_right = st.columns([1.8, 1.0], gap="small")
    with bottom_left:
        render_recent_status_alerts_panel(model)
    with bottom_right:
        render_operational_context_panel(model)

    return refresh_requested, snapshot_requested


__all__ = ["render_executive_command_center_page"]
