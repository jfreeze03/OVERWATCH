# sections/warehouse_health_setting_panels.py - Warehouse Health setting/action panels.
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.base import lazy_util as _lazy_util
from sections.shell_helpers import (
    render_escaped_labeled_text,
    render_shell_snapshot,
)
from sections.warehouse_health_actions import (
    _build_warehouse_cost_control_posture,
    _warehouse_setting_detail_options,
    _warehouse_setting_review_insert_sql,
)
from sections.warehouse_health_contracts import WAREHOUSE_HEALTH_VIEWS
from sections.warehouse_health_sql import (
    _overwatch_dedicated_warehouse_setup_sql,
    build_warehouse_setting_review_ddl,
    build_warehouse_setting_review_migration_sql,
)


download_csv = _lazy_util("download_csv")
format_snowflake_error = _lazy_util("format_snowflake_error")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _render_warehouse_setting_action_detail(plan: pd.DataFrame | None) -> None:
    options = _warehouse_setting_detail_options(plan)
    if options.empty:
        return
    st.markdown("**Open Warehouse Setting Action**")
    selected_label = st.selectbox(
        "Warehouse setting action",
        options["DETAIL_LABEL"].tolist(),
        key="warehouse_setting_action_select",
    )
    selected = options[options["DETAIL_LABEL"].eq(selected_label)]
    if selected.empty:
        return
    row = selected.iloc[0]
    render_shell_snapshot((
        ("Priority", str(row.get("PRIORITY") or "Review")),
        ("Warehouse", str(row.get("WAREHOUSE_NAME") or "Unknown")),
        ("State", str(row.get("CURRENT_STATE") or "Review")),
        ("Route", str(row.get("WORKFLOW_ROUTE") or "Overview & Scaling")),
    ))
    st.caption(str(row.get("WHY") or "Review the loaded warehouse telemetry before changing settings."))
    render_escaped_labeled_text(
        "Safe move",
        row.get("SAFE_SETTING_MOVE") or "Review telemetry before changing this warehouse.",
    )
    render_escaped_labeled_text(
        "Rollback check",
        row.get("ROLLBACK_CHECK") or "Compare credits, runtime, queue, spill, and failures after the change.",
    )
    review_sql = str(row.get("REVIEW_SQL") or "").strip()
    if review_sql:
        st.code(review_sql, language="sql")
    proof = str(row.get("PROOF_REQUIRED") or "").strip()
    if proof:
        st.caption(f"Proof: {proof}")
    route = str(row.get("WORKFLOW_ROUTE") or "").strip()
    if route in WAREHOUSE_HEALTH_VIEWS and st.button(f"Open {route}", key="warehouse_setting_action_route", width="stretch"):
        st.session_state["warehouse_health_view"] = route
        st.rerun()


def _render_warehouse_cost_control_posture(
    settings_inventory: pd.DataFrame | None,
    overview: pd.DataFrame | None = None,
) -> None:
    summary, posture = _build_warehouse_cost_control_posture(settings_inventory, overview)
    st.subheader("Warehouse Cost-Control Posture")
    if posture.empty:
        st.info("Load warehouse metadata to review AUTO_SUSPEND and AUTO_RESUME posture.")
        return

    render_shell_snapshot((
        ("Warehouses", f"{summary['warehouses']:,}"),
        ("Blocked", f"{summary['blocked']:,}"),
        ("Needs Review", f"{summary['review']:,}"),
        ("OVERWATCH candidates", f"{summary['overwatch_candidates']:,}"),
    ))
    render_priority_dataframe(
        posture,
        title="Suspend and resume posture",
        priority_columns=[
            "WAREHOUSE_NAME", "COST_CONTROL_STATE", "IDLE_RISK", "AUTO_SUSPEND_SEC",
            "AUTO_RESUME", "WAREHOUSE_SIZE", "STATE", "METERED_CREDITS",
            "RECOMMENDED_AUTO_SUSPEND_SEC", "RECOMMENDED_ACTION",
        ],
        sort_by=["POSTURE_RANK", "METERED_CREDITS", "WAREHOUSE_NAME"],
        ascending=[True, False, True],
        raw_label="All warehouse cost-control rows",
        height=320,
        max_rows=12,
    )
    download_csv(posture, "warehouse_cost_control_posture.csv")

    options = posture["WAREHOUSE_NAME"].astype(str).tolist()
    if options:
        selected_wh = st.selectbox(
            "Warehouse review SQL",
            options,
            key="warehouse_cost_control_sql_select",
        )
        selected = posture[posture["WAREHOUSE_NAME"].astype(str).eq(selected_wh)]
        if not selected.empty:
            st.code(str(selected.iloc[0].get("REVIEW_SQL") or ""), language="sql")

    with st.expander("Future dedicated OVERWATCH warehouse", expanded=False):
        st.code(_overwatch_dedicated_warehouse_setup_sql(), language="sql")


def _save_warehouse_setting_review_snapshot(
    session,
    findings: pd.DataFrame,
    *,
    company: str,
    environment: str,
    source: str = "",
) -> None:
    try:
        # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
        session.sql(build_warehouse_setting_review_ddl()).collect()
        for migration_sql in build_warehouse_setting_review_migration_sql():
            # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
            session.sql(migration_sql).collect()
        # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics owner=platform
        session.sql(_warehouse_setting_review_insert_sql(
            findings,
            company=company,
            environment=environment,
            source=source,
        )).collect()
        st.success("Saved the Warehouse Setting Review snapshot for review and telemetry tracking.")
    except Exception as exc:
        st.error(f"Could not save Warehouse Setting Review snapshot: {format_snowflake_error(exc)}")
        st.info("Warehouse setting review history is not available in this environment yet. Ask the DBA team to enable it, then retry this save.")
