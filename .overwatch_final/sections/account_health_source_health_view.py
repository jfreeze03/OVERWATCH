"""Account Health source-readiness renderer."""
from __future__ import annotations

import streamlit as st

from sections.account_health_models import _account_health_source_health_rows
from sections.base import lazy_util as _lazy_util
from sections.shell_helpers import render_shell_snapshot


render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _render_account_health_source_health(company: str, environment: str) -> None:
    source_health = _account_health_source_health_rows(st.session_state, company, environment)
    if source_health.empty:
        return
    with st.expander("Account Health Data Health", expanded=False):
        current = int(source_health["STATE"].isin(["Loaded", "No Rows"]).sum())
        stale = int(source_health["STATE"].eq("Stale").sum())
        unavailable = int(source_health["STATE"].eq("Unavailable").sum())
        mart_backed = int(
            source_health[
                source_health["STATE"].isin(["Loaded", "No Rows"])
                & source_health["SOURCE"].astype(str).str.contains("mart|FACT_", case=False, regex=True)
            ].shape[0]
        )
        render_shell_snapshot((
            ("Current", f"{current}/{len(source_health)}"),
            ("Fast Summary", f"{mart_backed:,}"),
            ("Stale", f"{stale:,}"),
            ("Unavailable", f"{unavailable:,}"),
        ))
        st.caption(
            "Use this before publishing the morning report or queueing checklist work. "
            "Account-level controls stay visible under environment filters when Snowflake has no database context."
        )
        render_priority_dataframe(
            source_health,
            title="Account Health telemetry freshness",
            priority_columns=[
                "SURFACE", "STATE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION",
            ],
            sort_by=["STATE_RANK", "SURFACE"],
            ascending=[True, True],
            raw_label="All Account Health data-health rows",
            height=320,
        )


__all__ = ["_render_account_health_source_health"]
