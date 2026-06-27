"""Alert Center Suppression Windows admin renderer."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st

from config import ALERT_DB, ALERT_SCHEMA
from utils import safe_identifier, sql_literal
from utils.explicit_load import explicit_load_dataframe, render_export_controls
from utils.workflows import render_priority_dataframe


ANNOTATION_TABLE = "OVERWATCH_ANNOTATIONS"


def _annotation_table_name() -> str:
    return (
        f"{safe_identifier(ALERT_DB)}."
        f"{safe_identifier(ALERT_SCHEMA)}."
        f"{safe_identifier(ANNOTATION_TABLE)}"
    )


def _suppression_window_insert_sql(
    *,
    table_name: str,
    entity: str,
    entity_type: str,
    window_start: str,
    window_end: str,
    annotation_type: str,
    description: str,
    suppress: bool,
) -> str:
    return f"""
        INSERT INTO {table_name}
            (CREATED_BY, ENTITY, ENTITY_TYPE, WINDOW_START, WINDOW_END,
             ANNOTATION_TYPE, DESCRIPTION, SUPPRESS_ALERTS, ACTIVE)
        VALUES (
            CURRENT_USER(),
            {sql_literal(entity.strip(), 500)},
            {sql_literal(entity_type)},
            {sql_literal(window_start.strip())}::TIMESTAMP_NTZ,
            {sql_literal(window_end.strip())}::TIMESTAMP_NTZ,
            {sql_literal(annotation_type)},
            {sql_literal(description, 2000)},
            {str(bool(suppress)).upper()},
            TRUE
        )
    """


def _suppression_windows_select_sql(table_name: str) -> str:
    return f"""
        SELECT
            ANNOTATION_ID,
            ENTITY,
            ENTITY_TYPE,
            WINDOW_START,
            WINDOW_END,
            ANNOTATION_TYPE,
            DESCRIPTION,
            SUPPRESS_ALERTS,
            ACTIVE,
            CREATED_BY,
            CREATED_AT
        FROM {table_name}
        WHERE WINDOW_END >= DATEADD('day', -7, CURRENT_TIMESTAMP())
        ORDER BY ACTIVE DESC, WINDOW_START DESC
        LIMIT 300
    """


def _suppression_window_deactivate_sql(annotation_id: int, table_name: str) -> str:
    return f"""
        UPDATE {table_name}
        SET ACTIVE = FALSE
        WHERE ANNOTATION_ID = {int(annotation_id)}
    """


def render_suppression_windows_pane(
    *,
    action_session_factory: Callable[[str], object | None],
    format_error: Callable[[Exception], str],
) -> None:
    table_name = _annotation_table_name()
    st.subheader("Suppression Windows")
    st.caption("Use suppression windows for planned maintenance, backfills, and noisy operating windows so the hourly alert task does not create duplicate noise.")

    with st.form("alert_center_annotation_create"):
        c1, c2, c3 = st.columns(3)
        with c1:
            entity_type = st.selectbox("Entity type", ["WAREHOUSE", "TASK", "USER", "GLOBAL"], key="alert_annotation_entity_type")
            entity = st.text_input(
                "Entity",
                value="*" if entity_type == "GLOBAL" else "",
                key="alert_annotation_entity",
                placeholder="Warehouse, task, user, or *",
            )
        with c2:
            window_start = st.text_input("Window start", key="alert_annotation_start", placeholder="2026-05-31 22:00:00")
            window_end = st.text_input("Window end", key="alert_annotation_end", placeholder="2026-06-01 02:00:00")
        with c3:
            annotation_type = st.selectbox(
                "Reason",
                ["DEPLOYMENT", "HIGH_VOLUME_VALIDATION", "PLANNED_MAINTENANCE", "BACKFILL", "OTHER"],
                key="alert_annotation_type",
            )
            suppress = st.checkbox("Suppress alerts", value=True, key="alert_annotation_suppress")
        description = st.text_area("Description", key="alert_annotation_description", placeholder="Release, migration, planned warehouse validation, etc.")
        submitted = st.form_submit_button("Create Suppression Window")
        if submitted:
            if not entity.strip() or not window_start.strip() or not window_end.strip():
                st.warning("Entity, window start, and window end are required.")
            else:
                try:
                    session = action_session_factory("create a suppression window")
                    if session is None:
                        return
                    # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
                    session.sql(_suppression_window_insert_sql(
                        table_name=table_name,
                        entity=entity,
                        entity_type=entity_type,
                        window_start=window_start,
                        window_end=window_end,
                        annotation_type=annotation_type,
                        description=description,
                        suppress=suppress,
                    )).collect()
                    st.success("Suppression window created.")
                    st.session_state.pop("alert_center_annotations", None)
                except Exception as exc:
                    st.error(f"Could not create suppression window: {format_error(exc)}")

    c1, c2 = st.columns([1, 3])
    with c1:
        def _load_suppression_windows() -> pd.DataFrame:
            from utils import run_query

            session = action_session_factory("load suppression windows")
            if session is None:
                return pd.DataFrame()
            return run_query(
                _suppression_windows_select_sql(table_name),
                ttl_key="alert_center_annotations",
                tier="recent",
                section="Alert Center",
            )

        def _suppression_window_error(exc: Exception) -> None:
            st.info(f"Suppression windows are not available in this environment yet. {format_error(exc)}")

        explicit_load_dataframe(
            button_label="Load Suppression Windows",
            button_key="alert_center_load_annotations",
            state_key="alert_center_annotations",
            loader=_load_suppression_windows,
            on_error=_suppression_window_error,
        )
    with c2:
        st.caption("Active global windows suppress every alert; entity windows suppress only the named warehouse, task, user, or alert entity.")

    df_ann = st.session_state.get("alert_center_annotations")
    if isinstance(df_ann, pd.DataFrame) and not df_ann.empty:
        render_priority_dataframe(
            df_ann,
            title="Suppression windows",
            priority_columns=[
                "ACTIVE", "ENTITY_TYPE", "ENTITY", "WINDOW_START", "WINDOW_END",
                "ANNOTATION_TYPE", "SUPPRESS_ALERTS", "DESCRIPTION",
            ],
            sort_by=["ACTIVE", "WINDOW_START"],
            ascending=[False, False],
            raw_label="All suppression windows",
            height=280,
        )
        render_export_controls(df_ann, "overwatch_alert_suppression_windows.csv", label="Export CSV")

        active_ids = df_ann.loc[df_ann.get("ACTIVE", pd.Series(dtype=bool)).astype(bool), "ANNOTATION_ID"].dropna().astype(int).tolist()
        if active_ids:
            selected_id = st.selectbox("Deactivate window", active_ids, key="alert_center_deactivate_id")
            if st.button("Deactivate Suppression Window", key="alert_center_deactivate_annotation"):
                try:
                    session = action_session_factory("deactivate a suppression window")
                    if session is None:
                        return
                    # DIRECT_SQL_ADMIN_OK boundary=admin reason=post_click_admin budget=advanced_diagnostics
                    session.sql(_suppression_window_deactivate_sql(int(selected_id), table_name)).collect()
                    st.success(f"Suppression window {int(selected_id)} deactivated.")
                    st.session_state.pop("alert_center_annotations", None)
                except Exception as exc:
                    st.error(f"Deactivate failed: {format_error(exc)}")
