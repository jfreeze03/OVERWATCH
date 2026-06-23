# sections/warehouse_health_view_overview.py - Warehouse Health overview workflow renderer.
from __future__ import annotations

import pandas as pd
import streamlit as st

from sections.base import lazy_util as _lazy_util
from sections.shell_helpers import consume_section_autoload_request, render_data_freshness, render_shell_snapshot, with_loaded_at
from sections.warehouse_health_actions import _build_warehouse_guardrail_coverage, _warehouse_setting_action_plan
from sections.warehouse_health_dataframes import _warehouse_meta_matches, _warehouse_period_movement, _warehouse_scope_meta
from sections.warehouse_health_loader import _warehouse_action_session
from sections.warehouse_health_panels import _render_warehouse_overview_exception_strip
from sections.warehouse_health_setting_panels import (
    _render_warehouse_cost_control_posture,
    _render_warehouse_setting_action_detail,
)
from utils.primitives import safe_int
from utils.section_guidance import defer_source_note


day_window_selectbox = _lazy_util("day_window_selectbox")
download_csv = _lazy_util("download_csv")
format_credits = _lazy_util("format_credits")
format_snowflake_error = _lazy_util("format_snowflake_error")
load_shared_warehouse_overview = _lazy_util("load_shared_warehouse_overview")
load_shared_warehouse_scaling_events = _lazy_util("load_shared_warehouse_scaling_events")
load_warehouse_inventory = _lazy_util("load_warehouse_inventory")
metric_confidence_label = _lazy_util("metric_confidence_label")
render_drillable_bar_chart = _lazy_util("render_drillable_bar_chart")
render_priority_dataframe = _lazy_util("render_priority_dataframe")


def _load_warehouse_overview(company: str, environment: str, wh_days: int) -> None:
    try:
        session = _warehouse_action_session("load warehouse overview")
        if session is None:
            return
        overview_result = load_shared_warehouse_overview(
            session,
            wh_days,
            company,
            force=True,
            section="Warehouse Health",
        )
        df_w = overview_result.data
        source = overview_result.source
        try:
            st.session_state["wh_settings_inventory"] = load_warehouse_inventory(
                session,
                company,
            )
            st.session_state["wh_settings_inventory_meta"] = with_loaded_at(
                _warehouse_scope_meta(
                    company,
                    environment,
                    wh_days,
                ),
                source="Warehouse guardrail metadata",
            )
            st.session_state.pop("wh_settings_inventory_error", None)
        except Exception as metadata_exc:
            st.session_state["wh_settings_inventory"] = pd.DataFrame()
            st.session_state["wh_settings_inventory_error"] = format_snowflake_error(metadata_exc)
        st.session_state["wh_df_wh"] = df_w
        st.session_state["wh_df_wh_source"] = source
        st.session_state["wh_df_wh_meta"] = with_loaded_at(
            _warehouse_scope_meta(company, environment, wh_days),
            source=source,
        )
    except Exception as e:
        st.warning(f"Warehouse overview unavailable in this role/context: {format_snowflake_error(e)}")


def _render_warehouse_overview_view(company: str, environment: str) -> None:
    st.subheader("Warehouse Capacity Overview")
    wh_days = day_window_selectbox("Lookback", key="wh_days", default=7)

    wh_expected_meta = _warehouse_scope_meta(company, environment, wh_days)
    loaded_wh_meta = st.session_state.get("wh_df_wh_meta", {})
    wh_current = (
        st.session_state.get("wh_df_wh") is not None
        and _warehouse_meta_matches(loaded_wh_meta, wh_expected_meta)
    )
    if consume_section_autoload_request("Warehouse Health") and not wh_current:
        st.caption("Warehouse capacity opened with a lightweight summary. Load warehouse data when current capacity detail is needed.")
    render_data_freshness(
        loaded_wh_meta if wh_current else {},
        source=st.session_state.get("wh_df_wh_source", "Warehouse overview"),
        target_minutes=30,
        delayed_note="Warehouse overview prefers fast summary telemetry; live account history refresh is explicit.",
    )

    if st.button("Load Warehouse Data", key="wh_load"):
        _load_warehouse_overview(company, environment, wh_days)

    if (
        st.session_state.get("wh_df_wh") is not None
        and not _warehouse_meta_matches(
            st.session_state.get("wh_df_wh_meta"),
            _warehouse_scope_meta(company, environment, wh_days),
        )
    ):
        st.info("Loaded warehouse overview is stale for the active scope. Reload Warehouse Data before acting.")
    elif st.session_state.get("wh_df_wh") is not None and not st.session_state["wh_df_wh"].empty:
        df_w = st.session_state["wh_df_wh"]

        render_shell_snapshot((
            ("Warehouses Active", len(df_w)),
            ("Total Queries", f"{int(df_w['TOTAL_QUERIES'].sum()):,}"),
            ("Total Remote Spill", f"{df_w['TOTAL_REMOTE_SPILL_GB'].sum():.1f} GB"),
            ("Credit Delta", format_credits(float(df_w.get("CREDIT_DELTA", pd.Series(dtype=float)).sum()))),
        ))
        wh_source = st.session_state.get("wh_df_wh_source", "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY")
        wh_source_lower = str(wh_source).lower()
        confidence = "estimated" if "fast" in wh_source_lower and "summary" in wh_source_lower else "exact"
        defer_source_note(metric_confidence_label(confidence), wh_source)
        _render_warehouse_overview_exception_strip(df_w)
        detail_key = "warehouse_health_show_overview_evidence"
        detail_open = bool(st.session_state.get(detail_key))
        detail_col, _ = st.columns([1.2, 4.0])
        with detail_col:
            if detail_open:
                if st.button("Hide Warehouse Detail", key="warehouse_health_hide_overview_evidence", width="stretch"):
                    st.session_state[detail_key] = False
                    st.rerun()
            elif st.button("Show Warehouse Detail", key="warehouse_health_show_overview_evidence_button", width="stretch"):
                st.session_state[detail_key] = True
                st.rerun()
        if not detail_open:
            return

        movement = _warehouse_period_movement(df_w)
        if not movement.empty:
            st.subheader("Warehouse Period Movement")
            render_priority_dataframe(
                movement,
                title="Current vs prior warehouse movement",
                priority_columns=[
                    "WAREHOUSE_NAME", "MOVEMENT_STATE", "METERED_CREDITS",
                    "PRIOR_METERED_CREDITS", "CREDIT_DELTA", "CREDIT_DELTA_PCT",
                    "AVG_QUEUED_SEC", "TOTAL_REMOTE_SPILL_GB", "NEXT_ACTION",
                ],
                sort_by=["CREDIT_DELTA", "METERED_CREDITS"],
                ascending=[False, False],
                raw_label="All warehouse period movement rows",
                height=320,
            )
        else:
            defer_source_note("Current/prior warehouse movement appears when the fast warehouse summary is available.")

        settings_inventory = st.session_state.get("wh_settings_inventory")
        if not _warehouse_meta_matches(
            st.session_state.get("wh_settings_inventory_meta"),
            _warehouse_scope_meta(company, environment, wh_days),
        ):
            settings_inventory = pd.DataFrame()

        guardrail_summary, guardrail_board = _build_warehouse_guardrail_coverage(
            df_w,
            settings_inventory=settings_inventory,
        )
        if not guardrail_board.empty:
            st.subheader("Warehouse Guardrail Coverage")
            render_shell_snapshot((
                ("Guardrail State", "Stable" if guardrail_summary["score"] >= 90 else "Review" if guardrail_summary["score"] >= 70 else "Critical"),
                ("Blocked", f"{guardrail_summary['blocked']:,}"),
                ("Needs Review", f"{guardrail_summary['review']:,}"),
                ("Data Missing", f"{guardrail_summary['unknown']:,}"),
            ))
            render_priority_dataframe(
                guardrail_board,
                title="Auto-derived warehouse guardrail coverage",
                priority_columns=[
                    "WAREHOUSE_NAME", "GUARDRAIL_STATE", "GUARDRAIL_SCORE", "SEVERITY",
                    "RESOURCE_MONITOR_STATE", "AUTO_SUSPEND_STATE", "TIMEOUT_STATE",
                    "ESCALATION_ROUTE_STATE", "CAPACITY_STATE", "COST_STATE",
                    "METERED_CREDITS", "CREDIT_DELTA",
                    "AVG_QUEUED_SEC", "TOTAL_REMOTE_SPILL_GB", "P95_ELAPSED_SEC",
                    "NEXT_ACTION", "PROOF_REQUIRED",
                ],
                sort_by=["GUARDRAIL_RANK", "GUARDRAIL_SCORE", "METERED_CREDITS"],
                ascending=[True, True, False],
                raw_label="All warehouse guardrail coverage rows",
                height=320,
                max_rows=12,
            )
            download_csv(guardrail_board, "warehouse_guardrail_coverage.csv")
            setting_plan = _warehouse_setting_action_plan(guardrail_board)
            st.session_state["wh_settings_action_plan"] = setting_plan
            if not setting_plan.empty:
                st.subheader("Warehouse Setting Action Plan")
                render_priority_dataframe(
                    setting_plan,
                    title="Recommended warehouse setting controls",
                    priority_columns=[
                        "PRIORITY", "WAREHOUSE_NAME", "ACTION_TYPE", "CURRENT_STATE",
                        "CURRENT_SETTING", "SAFE_SETTING_MOVE", "WHY", "ROLLBACK_CHECK",
                    ],
                    sort_by=["PRIORITY", "WAREHOUSE_NAME", "ACTION_TYPE"],
                    ascending=[True, True, True],
                    raw_label="All warehouse setting action rows",
                    height=320,
                    max_rows=12,
                )
                download_csv(setting_plan, "warehouse_setting_action_plan.csv")
                _render_warehouse_setting_action_detail(setting_plan)
            _render_warehouse_cost_control_posture(settings_inventory, df_w)
            if st.session_state.get("wh_settings_inventory_error"):
                defer_source_note(
                    "Warehouse metadata was unavailable for resource-monitor, timeout, and auto-suspend checks: "
                    f"{st.session_state.get('wh_settings_inventory_error')}"
                )
            elif settings_inventory is None or settings_inventory.empty:
                defer_source_note("Resource-monitor, timeout, and AUTO_SUSPEND checks need SHOW WAREHOUSES metadata.")

        render_priority_dataframe(
            df_w,
            title="Warehouse overview ranked by pressure",
            priority_columns=[
                "WAREHOUSE_NAME",
                "WAREHOUSE_SIZE",
                "TOTAL_QUERIES",
                "AVG_QUEUED_SEC",
                "TOTAL_REMOTE_SPILL_GB",
                "AVG_ELAPSED_SEC",
                "METERED_CREDITS",
                "PRIOR_METERED_CREDITS",
                "CREDIT_DELTA",
                "AVG_CACHE_PCT",
            ],
            sort_by=[
                "AVG_QUEUED_SEC",
                "TOTAL_REMOTE_SPILL_GB",
                "AVG_ELAPSED_SEC",
                "METERED_CREDITS",
            ],
            ascending=[False, False, False, False],
            raw_label="All warehouse overview rows",
        )

        cache_available = "AVG_CACHE_PCT" in df_w.columns and df_w["AVG_CACHE_PCT"].notna().any()
        if cache_available:
            st.subheader("Cache Hit % by Warehouse")
            render_drillable_bar_chart(
                df_w,
                dimension="WAREHOUSE_NAME",
                measure="AVG_CACHE_PCT",
                key="wh_cache_pct",
                drilldown_column="warehouse_name",
                lookback_hours=wh_days * 24,
            )
        else:
            defer_source_note("Cache hit percentage is a live ACCOUNT_USAGE-only metric and is not included in the fast warehouse summary.")

        download_csv(df_w, "warehouse_health.csv")

        st.divider()
        st.subheader("Scaling Events (WAREHOUSE_METERING_HISTORY)")
        if st.button("Load Scaling Events", key="wh_scale_load"):
            try:
                session = _warehouse_action_session("load warehouse scaling events")
                if session is None:
                    return
                scale_result = load_shared_warehouse_scaling_events(
                    session,
                    wh_days,
                    company,
                    force=True,
                    section="Warehouse Health",
                )
                st.session_state["wh_scaling"] = scale_result.data
                st.session_state["wh_scaling_source"] = scale_result.source
                st.session_state["wh_scaling_meta"] = _warehouse_scope_meta(company, environment, wh_days)
            except Exception as e:
                st.warning(f"Scaling events unavailable in this role/context: {format_snowflake_error(e)}")
        df_scale = st.session_state.get("wh_scaling")
        if (
            df_scale is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_scaling_meta"),
                _warehouse_scope_meta(company, environment, wh_days),
            )
        ):
            st.info("Loaded scaling events are stale for the active scope. Reload Scaling Events before acting.")
        elif df_scale is not None and not df_scale.empty:
            scale_source = st.session_state.get("wh_scaling_source", "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY")
            defer_source_note(metric_confidence_label("exact"), scale_source)
            render_priority_dataframe(
                df_scale,
                title="Largest scaling/metering events",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "START_TIME",
                    "END_TIME",
                    "CREDITS_USED",
                    "CREDITS_USED_COMPUTE",
                    "CREDITS_USED_CLOUD_SERVICES",
                ],
                sort_by=["CREDITS_USED", "CREDITS_USED_COMPUTE"],
                ascending=[False, False],
                raw_label="All scaling events",
            )
            download_csv(df_scale, "scaling_events.csv")
        elif df_scale is not None:
            st.info("No scaling or metering events found for the selected warehouse scope.")
