# sections/warehouse_health.py - Warehouse stats, scaling events, idle detection, spill, heatmap
from __future__ import annotations

import streamlit as st
from sections.base import lazy_pandas, lazy_util as _lazy_util
from utils.primitives import safe_float, safe_int
from utils.section_guidance import defer_section_note, defer_source_note
from config import DEFAULT_COMPANY, DEFAULTS, DEFAULT_ENVIRONMENT
from sections.shell_helpers import (
    consume_section_autoload_request,
    render_data_freshness,
    render_escaped_bold_text,
    render_shell_snapshot,
    with_loaded_at,
)

from sections.warehouse_health_actions import (
    _annotate_warehouse_admin_readiness,
    _build_warehouse_cost_control_posture,
    _build_warehouse_guardrail_coverage,
    _route_label,
    _warehouse_approval_for,
    _warehouse_capacity_priority_view,
    _warehouse_capacity_review_sql,
    _warehouse_intervention_matrix,
    _warehouse_owner_context,
    _warehouse_setting_action_plan,
    _warehouse_setting_audit_readiness_for_row,
    _warehouse_setting_candidate_for,
    _warehouse_setting_control_board,
    _warehouse_setting_detail_options,
    _warehouse_setting_review_insert_sql,
    _warehouse_setting_route,
)
from sections.warehouse_health_capacity import (
    _build_warehouse_capacity_markdown,
    _build_warehouse_capacity_sql,
    _render_warehouse_watch_floor,
    _warehouse_sql_exprs,
)
from sections.warehouse_health_contracts import (
    WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION,
    WAREHOUSE_HEALTH_BRIEF_WORKFLOWS,
    WAREHOUSE_HEALTH_DETAILS,
    WAREHOUSE_HEALTH_FAST_ENTRY_VERSION,
    WAREHOUSE_HEALTH_VIEWS,
    WAREHOUSE_OPERABILITY_FACT_TABLE,
    WAREHOUSE_SCOPE_FILTER_KEYS,
    WAREHOUSE_SETTING_REVIEW_TABLE,
)
from sections.warehouse_health_dataframes import (
    _frame_row_count,
    _scope_value,
    _source_confidence,
    _source_next_action,
    _warehouse_column_sum,
    _warehouse_frame_has_rows,
    _warehouse_frame_sum,
    _warehouse_looks_like_frame,
    _warehouse_meta_matches,
    _warehouse_operator_next_moves,
    _warehouse_overview_exceptions,
    _warehouse_period_movement,
    _warehouse_scope_meta,
    _warehouse_state_count,
    _warehouse_source_health_rows,
)
from sections.warehouse_health_helpers import (
    _warehouse_capacity_action_for,
    _warehouse_capacity_score,
    _warehouse_capacity_workflow_for,
)
from sections.warehouse_health_loader import _warehouse_action_session
from sections.warehouse_health_overview_panels import (
    _apply_queued_warehouse_health_view,
    _apply_warehouse_brief_first_default,
    _queue_warehouse_health_view,
    _render_warehouse_action_brief,
    _render_warehouse_brief_launchpad,
    _render_warehouse_operating_snapshot,
    _warehouse_action_brief,
    _warehouse_brief_workflow_rows,
    _warehouse_operating_snapshot,
    _warehouse_support_panels_have_state,
)
from sections.warehouse_health_panels import (
    _apply_warehouse_fast_entry_default,
    _render_capacity_brief,
    _render_warehouse_overview_exception_strip,
    _render_warehouse_source_health,
)
from sections.warehouse_health_queue import (
    _queue_capacity_findings,
    _queue_efficiency_findings,
)
from sections.warehouse_health_setting_panels import (
    _render_warehouse_cost_control_posture,
    _render_warehouse_setting_action_detail,
    _save_warehouse_setting_review_snapshot,
)
from sections.warehouse_health_sql import (
    _admin_audit_fqn,
    _overwatch_dedicated_warehouse_setup_sql,
    _warehouse_action_queue_closure_sql,
    _warehouse_capacity_verification_sql,
    _warehouse_cost_control_review_sql,
    _warehouse_operability_fact_sql,
    _warehouse_setting_execution_audit_sql,
    _warehouse_setting_review_history_sql,
    _warehouse_setting_review_sql,
    _warehouse_sql_identifier,
    build_warehouse_operability_fact_ddl,
    build_warehouse_operability_fact_migration_sql,
    build_warehouse_setting_review_ddl,
    build_warehouse_setting_review_migration_sql,
    warehouse_operability_fact_fqn,
    warehouse_setting_review_fqn,
)


pd = lazy_pandas()

get_session_for_action = _lazy_util("get_session_for_action")
format_credits = _lazy_util("format_credits")
download_csv = _lazy_util("download_csv")
render_drillable_bar_chart = _lazy_util("render_drillable_bar_chart")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
metric_confidence_label = _lazy_util("metric_confidence_label")
freshness_note = _lazy_util("freshness_note")
make_action_id = _lazy_util("make_action_id")
upsert_actions = _lazy_util("upsert_actions")
run_query = _lazy_util("run_query")
format_snowflake_error = _lazy_util("format_snowflake_error")
filter_existing_columns = _lazy_util("filter_existing_columns")
render_optimization_advisor = _lazy_util("render_optimization_advisor")
load_shared_warehouse_overview = _lazy_util("load_shared_warehouse_overview")
load_shared_warehouse_scaling_events = _lazy_util("load_shared_warehouse_scaling_events")
load_shared_warehouse_efficiency = _lazy_util("load_shared_warehouse_efficiency")
load_shared_warehouse_spill = _lazy_util("load_shared_warehouse_spill")
load_shared_warehouse_heatmap = _lazy_util("load_shared_warehouse_heatmap")
load_warehouse_inventory = _lazy_util("load_warehouse_inventory")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
render_load_status = _lazy_util("render_load_status")
render_workflow_selector = _lazy_util("render_workflow_selector")
day_window_selectbox = _lazy_util("day_window_selectbox")


def get_active_company() -> str:
    return str(st.session_state.get("active_company", DEFAULT_COMPANY) or DEFAULT_COMPANY)


def get_active_environment() -> str:
    return str(st.session_state.get("global_environment", DEFAULT_ENVIRONMENT) or DEFAULT_ENVIRONMENT)


def render_operator_briefing(items: list[tuple[str, str]], *, columns: int = 4) -> None:
    for label, detail in items:
        defer_section_note(f"{label}: {detail}")


def render():
    credit_price = st.session_state.get("credit_price", DEFAULTS["credit_price"])
    company = get_active_company()
    environment = get_active_environment()
    _apply_warehouse_fast_entry_default()
    _apply_warehouse_brief_first_default()
    _apply_queued_warehouse_health_view()
    global_warehouse = str(st.session_state.get("global_warehouse", "") or "").strip()
    global_user = str(st.session_state.get("global_user", "") or "").strip()
    global_role = str(st.session_state.get("global_role", "") or "").strip()
    global_database = str(st.session_state.get("global_database", "") or "").strip()
    global_start_date = st.session_state.get("global_start_date")
    global_end_date = st.session_state.get("global_end_date")

    selected_days = safe_int(st.session_state.get("wh_days", 7), 7) or 7
    if selected_days < 1 or selected_days > 30:
        selected_days = 7
    _render_warehouse_action_brief(_warehouse_action_brief(company, environment, selected_days))
    _render_warehouse_operating_snapshot(_warehouse_operating_snapshot(company, environment, selected_days))

    render_operator_briefing(
        [
            ("First move", "Decide whether pressure is queue, spill, latency, or cost drift."),
            ("Telemetry", "Use metering plus query history before changing size or clusters."),
            ("Control", "Tune routing, auto-suspend, QAS, size, or multi-cluster with measured context."),
            ("Output", "Create a warehouse capacity brief for release or cost review."),
        ],
        columns=4,
    )
    warehouse_view = render_workflow_selector(
        "Warehouse capacity workflow",
        "warehouse_health_view",
        WAREHOUSE_HEALTH_VIEWS,
        WAREHOUSE_HEALTH_DETAILS,
        columns=3,
    )
    if warehouse_view == "Overview & Scaling" and not _warehouse_frame_has_rows(st.session_state.get("wh_df_wh")):
        _render_warehouse_brief_launchpad()
    show_support_panels = bool(st.session_state.get("warehouse_health_support_panels_open"))
    if show_support_panels:
        if st.button("Hide Detail Panels", key="warehouse_health_hide_support_panels"):
            st.session_state["warehouse_health_support_panels_open"] = False
            st.rerun()
        _render_capacity_brief(company, environment)
        _render_warehouse_source_health(company, environment)
    elif st.button("Detail Panels", key="warehouse_health_open_support_panels"):
        st.session_state["warehouse_health_support_panels_open"] = True
        st.rerun()
    if st.session_state.get("exceptions_only_mode") and warehouse_view != "Overview & Scaling":
        return

    # -- OVERVIEW --------------------------------------------------------------
    if warehouse_view == "Overview & Scaling":
        st.subheader("Warehouse Capacity Overview")
        wh_days = day_window_selectbox("Lookback", key="wh_days", default=7)

        def _load_warehouse_overview() -> None:
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
            _load_warehouse_overview()

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

            # Cache efficiency chart
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

            # Scaling events
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

    elif warehouse_view == "Efficiency":
        st.subheader("Warehouse Efficiency Risks")
        eff_days = day_window_selectbox("Lookback", key="wh_eff_days", default=7)
        if st.button("Load Efficiency Metrics", key="wh_eff_load"):
            try:
                session = _warehouse_action_session("load warehouse efficiency metrics")
                if session is None:
                    return
                result = load_shared_warehouse_efficiency(
                    session,
                    eff_days,
                    company,
                    force=True,
                    section="Warehouse Health",
                )
                st.session_state["wh_efficiency"] = result.data
                st.session_state["wh_efficiency_meta"] = _warehouse_scope_meta(company, environment, eff_days)
                st.session_state["wh_efficiency_source"] = result.source
            except Exception as e:
                st.warning(f"Efficiency metrics unavailable in this role/context: {format_snowflake_error(e)}")

        df_eff = st.session_state.get("wh_efficiency")
        if (
            df_eff is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_efficiency_meta"),
                _warehouse_scope_meta(company, environment, eff_days),
            )
        ):
            st.info("Loaded efficiency metrics are stale for the active scope. Reload Efficiency Metrics before acting.")
        elif df_eff is not None and not df_eff.empty:
            low = df_eff[df_eff["EFFICIENCY_SCORE"] < 70]
            render_shell_snapshot((
                ("Warehouses Reviewed", len(df_eff)),
                ("Needs Review", len(low)),
                ("Total metered credits", format_credits(float(df_eff["METERED_CREDITS"].sum()))),
            ))
            defer_source_note(
                metric_confidence_label("allocated"),
                st.session_state.get("wh_efficiency_source", freshness_note("ACCOUNT_USAGE")),
            )
            df_eff_display = df_eff.rename(columns={"EFFICIENCY_SCORE": "REVIEW_PRIORITY"})
            render_priority_dataframe(
                df_eff_display,
                title="Warehouse efficiency risks",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "REVIEW_PRIORITY",
                    "METERED_CREDITS",
                    "CREDITS_PER_QUERY",
                    "QUEUE_SEC_PER_CREDIT",
                    "REMOTE_SPILL_GB_PER_CREDIT",
                    "AVG_CACHE_PCT",
                ],
                sort_by=["REVIEW_PRIORITY", "METERED_CREDITS"],
                ascending=[True, False],
                raw_label="All warehouse efficiency rows",
            )
            render_drillable_bar_chart(
                df_eff_display,
                dimension="WAREHOUSE_NAME",
                measure="REVIEW_PRIORITY",
                key="wh_efficiency_review_priority",
                drilldown_column="warehouse_name",
                lookback_hours=eff_days * 24,
            )
            download_csv(df_eff, "warehouse_efficiency.csv")
            if st.button("Save low-efficiency warehouses to Action Queue", key="wh_eff_queue"):
                session = _warehouse_action_session("save warehouse efficiency findings to the action queue")
                if session is not None:
                    _queue_efficiency_findings(session, df_eff)

    # -- SPILL -----------------------------------------------------------------
    elif warehouse_view == "Spill & Memory":
        st.subheader("Spill & Memory Pressure")
        sp_days = day_window_selectbox("Lookback", key="sp_days", default=7)

        if st.button("Load Spill Data", key="sp_load"):
            try:
                session = _warehouse_action_session("load warehouse spill data")
                if session is None:
                    return
                result = load_shared_warehouse_spill(
                    session,
                    sp_days,
                    company,
                    force=True,
                    section="Warehouse Health",
                )
                st.session_state["wh_df_sp"] = result.data
                st.session_state["wh_df_sp_meta"] = _warehouse_scope_meta(company, environment, sp_days)
                st.session_state["wh_df_sp_source"] = result.source
            except Exception as e:
                st.warning(f"Spill data unavailable in this role/context: {format_snowflake_error(e)}")

        if (
            st.session_state.get("wh_df_sp") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_sp_meta"),
                _warehouse_scope_meta(company, environment, sp_days),
            )
        ):
            st.info("Loaded spill data is stale for the active scope. Reload Spill Data before acting.")
        elif st.session_state.get("wh_df_sp") is not None and not st.session_state["wh_df_sp"].empty:
            df_sp = st.session_state["wh_df_sp"]
            render_shell_snapshot((
                ("Spilling Warehouses", len(df_sp)),
                ("Total Local Spill", f"{df_sp['LOCAL_SPILL_GB'].sum():.1f} GB"),
                ("Total Remote Spill", f"{df_sp['REMOTE_SPILL_GB'].sum():.1f} GB"),
            ))
            defer_source_note(st.session_state.get("wh_df_sp_source", "Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"))
            render_priority_dataframe(
                df_sp,
                title="Spill and memory pressure",
                priority_columns=[
                    "WAREHOUSE_NAME",
                    "WAREHOUSE_SIZE",
                    "SPILL_QUERY_COUNT",
                    "LOCAL_SPILL_GB",
                    "REMOTE_SPILL_GB",
                    "AVG_ELAPSED_SEC",
                ],
                sort_by=["REMOTE_SPILL_GB", "LOCAL_SPILL_GB", "AVG_ELAPSED_SEC"],
                ascending=[False, False, False],
                raw_label="All spill rows",
            )
            df_sp["TOTAL_SPILL_GB"] = df_sp["LOCAL_SPILL_GB"] + df_sp["REMOTE_SPILL_GB"]
            render_drillable_bar_chart(
                df_sp,
                dimension="WAREHOUSE_NAME",
                measure="TOTAL_SPILL_GB",
                key="wh_spill_total",
                drilldown_column="warehouse_name",
                lookback_hours=sp_days * 24,
            )
            for _, row in df_sp.iterrows():
                if row["REMOTE_SPILL_GB"] > 10:
                    st.error(f"**{row['WAREHOUSE_NAME']}**: {row['REMOTE_SPILL_GB']:.1f} GB remote spill - upsize immediately")
            download_csv(df_sp, "spill_report.csv")

    # -- HEATMAP ---------------------------------------------------------------
    elif warehouse_view == "Workload Heatmap":
        st.subheader("Workload Concurrency Heatmap")
        hm_days = day_window_selectbox("Lookback", key="hm_days", default=30)

        if st.button("Refresh Heatmap", key="hm_build"):
            try:
                result = load_shared_warehouse_heatmap(
                    hm_days,
                    company,
                    warehouse_contains=global_warehouse,
                    user_contains=global_user,
                    role_contains=global_role,
                    database_contains=global_database,
                    start_date=global_start_date,
                    end_date=global_end_date,
                    force=True,
                    section="Warehouse Health",
                )
                if result.message:
                    st.warning(result.message)
                st.session_state["wh_df_hm"] = result.data
                st.session_state["wh_df_hm_meta"] = _warehouse_scope_meta(company, environment, hm_days)
                st.session_state["wh_df_hm_source"] = result.source
            except Exception as e:
                st.warning(f"Workload heatmap unavailable in this role/context: {format_snowflake_error(e)}")

        if (
            st.session_state.get("wh_df_hm") is not None
            and not _warehouse_meta_matches(
                st.session_state.get("wh_df_hm_meta"),
                _warehouse_scope_meta(company, environment, hm_days),
            )
        ):
            st.info("Loaded workload heatmap is stale for the active scope. Refresh Heatmap before acting.")
        elif st.session_state.get("wh_df_hm") is not None and not st.session_state["wh_df_hm"].empty:
            df_hm = st.session_state["wh_df_hm"]
            if st.session_state.get("wh_df_hm_source"):
                defer_source_note(str(st.session_state.get("wh_df_hm_source")))
            whs = df_hm["WAREHOUSE_NAME"].unique()
            sel_wh = st.selectbox("Warehouse", whs, key="hm_wh_sel")

            if sel_wh:
                wh_data = df_hm[df_hm["WAREHOUSE_NAME"] == sel_wh]
                pivot = wh_data.pivot_table(
                    index="DAY_OF_WEEK", columns="HOUR_OF_DAY",
                    values="QUERY_COUNT", aggfunc="sum"
                ).fillna(0)
                day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
                pivot.index = pivot.index.map(lambda x: day_names.get(int(x), str(x)))
                st.subheader(f"Query Volume Heatmap - {sel_wh}")
                st.dataframe(pivot.style.background_gradient(cmap="YlOrRd"), width="stretch")
                render_shell_snapshot((
                    ("Total Queries", f"{int(wh_data['QUERY_COUNT'].sum()):,}"),
                    ("Peak Hour", f"{int(pivot.max().max()):,}"),
                    ("Avg Elapsed", f"{wh_data['AVG_ELAPSED_SEC'].mean():.1f}s"),
                ))

    elif warehouse_view == "Optimization Advisor":
        render_optimization_advisor()
