"""Account Health Overview renderer and explicit-load controller."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from runtime_state import set_state
from sections.account_health_access_hygiene_view import _render_account_health_access_hygiene
from sections.account_health_action_queue import _queue_account_health_checklist
from sections.account_health_checklist import (
    _account_health_actionable_checklist,
    _account_health_control_board,
    _account_health_morning_exception_rows,
    _account_health_operator_next_moves,
    _account_health_visible_checklist,
    _annotate_account_health_checklist_readiness,
    _build_account_health_dba_checklist,
    _mart_health_label,
    _render_account_health_action_brief,
    _render_account_health_exception_strip,
)
from sections.account_health_common import _account_health_action_session, render_operator_briefing
from sections.account_health_data import (
    _account_query_history_capabilities,
    _can_use_control_room_mart,
    _load_live_query_status,
    _task_failure_sql_or_empty,
    _task_health_sql_or_empty,
)
from sections.account_health_history import (
    _account_health_checklist_history_sql,
    _account_health_closure_analytics_sql,
    _account_health_operability_fact_sql,
    _save_account_health_checklist_snapshot,
)
from sections.account_health_models import (
    _account_health_has_source_state,
    _account_health_meta_matches,
    _account_health_scope_meta,
    _account_health_source_health_rows,
)
from sections.account_health_overview_models import (
    _account_health_intervention_matrix,
    _render_account_health_operating_snapshot,
)
from sections.account_health_source_health_view import _render_account_health_source_health
from sections.base import lazy_pandas, lazy_util as _lazy_util
from sections.navigation import apply_navigation_state
from sections.shell_helpers import render_shell_snapshot
from utils.primitives import safe_float, safe_int


pd = lazy_pandas()

run_query = _lazy_util("run_query")
format_credits = _lazy_util("format_credits")
credits_to_dollars = _lazy_util("credits_to_dollars")
mark_loaded = _lazy_util("mark_loaded")
show_loaded_time = _lazy_util("show_loaded_time")
build_metered_credit_cte = _lazy_util("build_metered_credit_cte")
render_drillable_bar_chart = _lazy_util("render_drillable_bar_chart")
executive_health_score = _lazy_util("executive_health_score")
get_wh_filter_clause = _lazy_util("get_wh_filter_clause")
get_db_filter_clause = _lazy_util("get_db_filter_clause")
get_global_filter_clause = _lazy_util("get_global_filter_clause")
get_active_environment = _lazy_util("get_active_environment")
load_latest_control_room_mart = _lazy_util("load_latest_control_room_mart")
mart_source_caption = _lazy_util("mart_source_caption")
build_mart_account_health_storage_sql = _lazy_util("build_mart_account_health_storage_sql")
build_mart_account_health_cost_drivers_sql = _lazy_util("build_mart_account_health_cost_drivers_sql")
build_mart_account_health_change_sql = _lazy_util("build_mart_account_health_change_sql")
build_mart_control_room_task_failures_sql = _lazy_util("build_mart_control_room_task_failures_sql")
build_mart_control_room_warehouse_pressure_sql = _lazy_util("build_mart_control_room_warehouse_pressure_sql")
format_snowflake_error = _lazy_util("format_snowflake_error")
render_priority_dataframe = _lazy_util("render_priority_dataframe")
day_window_selectbox = _lazy_util("day_window_selectbox")
load_shared_usage_storage_kpis = _lazy_util("load_shared_usage_storage_kpis")
load_shared_usage_metering_kpis = _lazy_util("load_shared_usage_metering_kpis")
load_shared_query_history_rollup = _lazy_util("load_shared_query_history_rollup")
load_shared_warehouse_pressure_summary = _lazy_util("load_shared_warehouse_pressure_summary")


def _drill_to(
    section: str,
    wh_filter: str = "",
    user_filter: str = "",
    workflow_key: str = "",
    workflow: str = "",
    extra_state: dict[str, object] | None = None,
):
    apply_navigation_state(section)
    if workflow_key and workflow:
        set_state(workflow_key, workflow)
    for key, value in (extra_state or {}).items():
        st.session_state[str(key)] = value
    if wh_filter:
        st.session_state["lm_wh"]     = wh_filter
        st.session_state["wh_filter"] = wh_filter
    if user_filter:
        st.session_state["global_user"] = user_filter
    st.rerun()


def render_account_health_overview(company: str, environment: str, credit_price: float) -> None:
    wh_filter_q = get_wh_filter_clause("q.warehouse_name", company)
    wh_filter_m = get_wh_filter_clause("warehouse_name", company)
    db_filter_q = get_db_filter_clause("q.database_name", company)
    query_scope_filter_q = get_global_filter_clause(
        "", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
    )
    global_filter_q = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name"
    )
    query_history_caps = None

    def _query_history_capabilities(action_session=None) -> dict:
        nonlocal query_history_caps
        if query_history_caps is None:
            if action_session is None:
                action_session = _account_health_action_session("load Account Health QUERY_HISTORY metadata")
            query_history_caps = _account_query_history_capabilities(action_session)
        return query_history_caps

    render_operator_briefing(
        [
            ("First move", "Refresh the health snapshot and read the exception signals."),
            ("Telemetry", "Use cost drivers, failed work, warehouse pressure, and changes since yesterday."),
            ("Control", "Drill into the guarded workflow before recommending action."),
            ("Output", "Build the DBA morning brief from verified Control Room and Account Health facts."),
        ],
        columns=4,
    )
    exceptions_only = bool(st.session_state.get("exceptions_only_mode", False))
    if exceptions_only:
        st.info("Leadership exceptions-only mode is on. Heavy drilldowns stay collapsed until you ask for detail.")
    if _account_health_has_source_state(st.session_state):
        _render_account_health_source_health(company, environment)

    cache_age = 999
    filter_sig = "|".join([
        str(company),
        str(st.session_state.get("global_start_date", "")),
        str(st.session_state.get("global_end_date", "")),
        str(st.session_state.get("global_warehouse", "")),
        str(st.session_state.get("global_user", "")),
        str(st.session_state.get("global_role", "")),
        str(st.session_state.get("global_database", "")),
    ])
    last_ts = st.session_state.get("_health_ts")
    if last_ts:
        cache_age = (datetime.now() - datetime.fromisoformat(last_ts)).total_seconds()

    health_loaded = isinstance(st.session_state.get("health_data"), dict) and bool(st.session_state.get("health_data"))
    stale_scope = health_loaded and st.session_state.get("_health_filter_sig") != filter_sig
    auto_refresh_health = (
        (not health_loaded or stale_scope)
        and st.session_state.get("_account_health_auto_load_attempt_scope") != filter_sig
    )
    if auto_refresh_health:
        st.session_state["_account_health_auto_load_attempt_scope"] = filter_sig
    refresh_health = st.button("Load / Refresh Health", key="health_refresh") or auto_refresh_health
    if not refresh_health:
        if not health_loaded:
            st.info("Health snapshot is available on demand. Refresh when you need current Account Health telemetry.")
        elif stale_scope:
            st.warning("Loaded health snapshot is stale for the active filters. Refresh before acting.")
        elif cache_age > 300:
            st.caption(f"Loaded health snapshot is {cache_age / 60:.1f} minutes old. Refresh when current telemetry matters.")

    if refresh_health:
        action_session = _account_health_action_session("load Account Health")
        if action_session is None:
            return
        hd = {}
        mart_ok, mart_reason = _can_use_control_room_mart(company)
        control_mart = load_latest_control_room_mart(company) if mart_ok else None
        use_control_mart = bool(
            control_mart is not None
            and control_mart.available
            and control_mart.data is not None
            and not control_mart.data.empty
        )
        hd["_control_mart"] = control_mart.data if control_mart is not None else pd.DataFrame()
        hd["_control_mart_source"] = (
            mart_source_caption(control_mart)
            if control_mart is not None
            else f"Live fallback: {mart_reason}"
        )
        hd["_control_mart_used"] = use_control_mart
        live_df, live_source = _load_live_query_status("", "", query_scope_filter_q)
        hd["live"] = live_df
        hd["_live_source"] = live_source
        if use_control_mart:
            query_plan = [
                ("storage", build_mart_account_health_storage_sql(company)),
                ("cost_drivers", build_mart_account_health_cost_drivers_sql(24, company)),
                ("failed_jobs", build_mart_control_room_task_failures_sql(24, company)),
                ("what_changed", build_mart_account_health_change_sql(24, company)),
            ]
            hd["_account_health_detail_source"] = "Fast summary"
        else:
            qh = _query_history_capabilities(action_session)
            cost_wh_size_expr = qh["cost_wh_size_expr"]
            cost_bytes_scanned_expr = qh["cost_bytes_scanned_expr"]
            failed_pred_q = qh["failed_pred_q"]
            queued_count_expr_q = qh["queued_count_expr_q"]
            query_plan = [
                ("cost_drivers", f"""
                WITH {build_metered_credit_cte(hours_back=48, include_recent=True)}
                SELECT q.user_name, q.warehouse_name, {cost_wh_size_expr} AS warehouse_size,
                       COUNT(*) AS query_count,
                       ROUND(SUM(COALESCE(pqc.metered_credits,0)), 4) AS total_credits,
                       ROUND({cost_bytes_scanned_expr}/POWER(1024,3), 2) AS gb_scanned
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
                WHERE q.start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                  AND q.warehouse_name IS NOT NULL
                  {global_filter_q}
                GROUP BY q.user_name, q.warehouse_name
                ORDER BY total_credits DESC
                LIMIT 5
            """),
            ("failed_jobs", _task_failure_sql_or_empty(
                action_session,
                "scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())",
                    5,
                    company,
                )),
                ("what_changed", f"""
                WITH today_q AS (
                    SELECT COUNT(*) AS q,
                           SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS fails
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    WHERE q.start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                      {query_scope_filter_q}
                ),
                yday_q AS (
                    SELECT COUNT(*) AS q,
                           SUM(CASE WHEN {failed_pred_q} THEN 1 ELSE 0 END) AS fails
                    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
                    WHERE q.start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
                      AND q.start_time <  DATEADD('hours', -24, CURRENT_TIMESTAMP())
                      {query_scope_filter_q}
                ),
                today_c AS (
                    SELECT SUM(credits_used) AS credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())
                      {wh_filter_m}
                ),
                yday_c AS (
                    SELECT SUM(credits_used) AS credits
                    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                    WHERE start_time >= DATEADD('hours', -48, CURRENT_TIMESTAMP())
                      AND start_time < DATEADD('hours', -24, CURRENT_TIMESTAMP())
                      {wh_filter_m}
                )
                SELECT today_q.q - yday_q.q AS query_delta,
                       ROUND(COALESCE(today_c.credits, 0) - COALESCE(yday_c.credits, 0), 4) AS credit_delta,
                       today_q.fails - yday_q.fails AS failure_delta
                FROM today_q, yday_q, today_c, yday_c
                """),
            ]
            hd["_account_health_detail_source"] = "Live fallback: ACCOUNT_USAGE"
        if not use_control_mart:
            burn_result = load_shared_usage_metering_kpis(
                action_session,
                1,
                company,
                force=True,
                section="Account Health",
            )
            if not burn_result.data.empty:
                burn_row = burn_result.data.iloc[0]
                last_24h = safe_float(burn_row.get("TOTAL_CREDITS", 0))
                prior_24h = safe_float(burn_row.get("PRIOR_CREDITS", 0))
            else:
                last_24h = 0.0
                prior_24h = 0.0
            hd["burn"] = pd.DataFrame([{
                "LAST_24H": last_24h,
                "PRIOR_24H": prior_24h,
            }])
            hd["_burn_source"] = burn_result.source
            query_rollup_result = load_shared_query_history_rollup(
                action_session,
                1,
                company,
                force=True,
                section="Account Health",
            )
            query_rollup = query_rollup_result.data
            if query_rollup is not None and not query_rollup.empty:
                rollup_row = query_rollup.iloc[0]
            else:
                rollup_row = {}
            failed_queries = safe_int(getattr(rollup_row, "get", lambda *_: 0)("FAILED_QUERIES", 0))
            hd["errors"] = pd.DataFrame([{"ERR_COUNT": failed_queries}])
            hd["query_stats"] = pd.DataFrame([{
                "TOTAL_QUERIES": safe_float(getattr(rollup_row, "get", lambda *_: 0)("TOTAL_QUERIES", 0)),
                "FAILED_QUERIES": safe_float(getattr(rollup_row, "get", lambda *_: 0)("FAILED_QUERIES", 0)),
                "QUEUED_QUERIES": safe_float(getattr(rollup_row, "get", lambda *_: 0)("QUEUED_QUERIES", 0)),
                "AVG_ELAPSED_SEC": safe_float(getattr(rollup_row, "get", lambda *_: 0)("AVG_ELAPSED_SEC", 0)),
            }])
            hd["_query_rollup_source"] = query_rollup_result.source

            pressure_result = load_shared_warehouse_pressure_summary(
                action_session,
                1,
                company,
                force=True,
                section="Account Health",
            )
            hd["warehouse_pressure"] = pressure_result.data
            hd["_warehouse_pressure_source"] = pressure_result.source
            storage_result = load_shared_usage_storage_kpis(
                1,
                company,
                force=True,
                section="Account Health",
            )
            storage_summary = storage_result.data
            if storage_summary is not None and not storage_summary.empty:
                storage_row = storage_summary.iloc[0]
                storage_tb = safe_float(storage_row.get("ACTIVE_STORAGE_TB", 0)) + safe_float(
                    storage_row.get("FAILSAFE_STORAGE_TB", 0)
                )
                hd["storage"] = pd.DataFrame([{"STORAGE_TB": storage_tb}])
            else:
                hd["storage"] = pd.DataFrame(columns=["STORAGE_TB"])
            hd["_storage_source"] = storage_result.source
            query_plan = [
            ("task_health", _task_health_sql_or_empty(
                action_session,
                "scheduled_time >= DATEADD('hours', -24, CURRENT_TIMESTAMP())",
                company,
            )),
            ] + query_plan
        for key, sql in query_plan:
            hd[key] = run_query(
                sql,
                ttl_key=f"account_health_live_{company}_{key}",
                tier="recent",
                section="Account Health",
            )

        st.session_state["health_data"] = hd
        st.session_state["_health_ts"]  = datetime.now().isoformat()
        st.session_state["_health_filter_sig"] = filter_sig
        st.session_state["account_health_overview_meta"] = _account_health_scope_meta(
            company, environment, window="24h"
        )
        st.session_state["account_health_live_status_meta"] = _account_health_scope_meta(
            company, environment, window="1h"
        )
        mark_loaded("account_health")

    hd = st.session_state.get("health_data", {})
    if not isinstance(hd, dict) or not hd:
        return

    live_df    = hd.get("live",    pd.DataFrame())
    live_source = hd.get("_live_source", "ACCOUNT_USAGE")
    burn_df    = hd.get("burn",    pd.DataFrame())
    err_df     = hd.get("errors",  pd.DataFrame())
    storage_df = hd.get("storage", pd.DataFrame())
    query_stats_df = hd.get("query_stats", pd.DataFrame())
    task_health_df = hd.get("task_health", pd.DataFrame())
    warehouse_pressure_df = hd.get("warehouse_pressure", pd.DataFrame())
    control_mart_df = hd.get("_control_mart", pd.DataFrame())
    control_mart_used = bool(hd.get("_control_mart_used", False)) and not control_mart_df.empty
    control_mart_row = control_mart_df.iloc[0] if control_mart_used else {}
    live_val  = safe_int(live_df["ACTIVE_COUNT"].iloc[0]) if not live_df.empty else 0
    queued    = safe_int(live_df["QUEUED_COUNT"].iloc[0]) if not live_df.empty else 0
    stor_tb   = safe_float(storage_df["STORAGE_TB"].iloc[0]) if not storage_df.empty else 0
    if control_mart_used:
        last24 = safe_float(control_mart_row.get("CREDITS_24H", 0))
        cost24 = safe_float(control_mart_row.get("COST_24H_USD", credits_to_dollars(last24, credit_price)))
        err_count = safe_int(control_mart_row.get("FAILED_QUERIES_24H", 0))
        failed_tasks = safe_int(control_mart_row.get("FAILED_TASKS_24H", 0))
        object_changes = safe_int(control_mart_row.get("OBJECT_CHANGES_24H", 0))
        queued_ms = safe_float(control_mart_row.get("QUEUED_MS_24H", 0))
        pct_delta = 0
        health_score = safe_float(control_mart_row.get("HEALTH_SCORE", 0))
        score_label = _mart_health_label(health_score)
        health_components = pd.DataFrame([
            {"Component": "Failed queries", "Observed": err_count, "Source": "Fast summary"},
            {"Component": "Failed tasks", "Observed": failed_tasks, "Source": "Fast summary"},
            {"Component": "Queued minutes", "Observed": round(queued_ms / 60000, 2), "Source": "Fast summary"},
            {"Component": "Security events", "Observed": safe_int(control_mart_row.get("SECURITY_EVENTS_24H", 0)), "Source": "Fast summary"},
            {"Component": "Object changes", "Observed": safe_int(control_mart_row.get("OBJECT_CHANGES_24H", 0)), "Source": "Fast summary"},
            {"Component": "Top risk", "Observed": control_mart_row.get("TOP_RISK", ""), "Source": "Fast summary"},
        ])
    else:
        last24 = safe_float(burn_df["LAST_24H"].iloc[0]) if not burn_df.empty else 0
        prior24 = safe_float(burn_df["PRIOR_24H"].iloc[0]) if not burn_df.empty else 0
        cost24 = credits_to_dollars(last24, credit_price)
        err_count = safe_int(err_df["ERR_COUNT"].iloc[0]) if not err_df.empty else 0
        failed_tasks = safe_int(task_health_df["FAILED_TASKS"].iloc[0]) if not task_health_df.empty else 0
        object_changes = 0
        pct_delta = ((last24 - prior24) / prior24 * 100) if prior24 > 0 else 0
        health = executive_health_score({
            "total_queries": safe_float(query_stats_df["TOTAL_QUERIES"].iloc[0]) if not query_stats_df.empty else 0,
            "failed_queries": err_count,
            "queued_queries": safe_float(query_stats_df["QUEUED_QUERIES"].iloc[0]) if not query_stats_df.empty else queued,
            "avg_elapsed_sec": safe_float(query_stats_df["AVG_ELAPSED_SEC"].iloc[0]) if not query_stats_df.empty else 0,
            "task_runs": safe_float(task_health_df["TASK_RUNS"].iloc[0]) if not task_health_df.empty else 0,
            "failed_tasks": safe_float(task_health_df["FAILED_TASKS"].iloc[0]) if not task_health_df.empty else 0,
            "active_warehouses": safe_float(warehouse_pressure_df["ACTIVE_WAREHOUSES"].iloc[0]) if not warehouse_pressure_df.empty else 0,
            "pressure_warehouses": safe_float(warehouse_pressure_df["PRESSURE_WAREHOUSES"].iloc[0]) if not warehouse_pressure_df.empty else 0,
            "current_credits": last24,
            "prior_credits": prior24,
            "current_storage_tb": stor_tb,
            "prior_storage_tb": stor_tb,
        })
        health_score = health["score"]
        score_label = health["label"]
        health_components = pd.DataFrame(health["components"])

    checklist = _build_account_health_dba_checklist(
        health_score=health_score,
        score_label=score_label,
        err_count=err_count,
        queued=queued,
        pct_delta=pct_delta,
        last24=last24,
        stor_tb=stor_tb,
        failed_tasks=failed_tasks,
        object_changes=object_changes,
        control_mart_used=control_mart_used,
        detail_source=hd.get("_account_health_detail_source", ""),
    )
    checklist = _annotate_account_health_checklist_readiness(
        checklist,
        environment=get_active_environment(),
    )
    _render_account_health_action_brief(checklist)
    _render_account_health_operating_snapshot(
        health_score=health_score,
        score_label=score_label,
        live_val=live_val,
        queued=queued,
        err_count=err_count,
        last24=last24,
        pct_delta=pct_delta,
        cost24=cost24,
        stor_tb=stor_tb,
        failed_tasks=failed_tasks,
        hd=hd,
        live_source=live_source,
        control_mart_used=control_mart_used,
        control_mart_row=control_mart_row,
    )
    if st.button("Load Control Summary", key="account_health_load_operability_fact"):
        try:
            operability_sql = _account_health_operability_fact_sql(30, company, get_active_environment())
            st.session_state["account_health_operability_fact_sql"] = operability_sql
            st.session_state["account_health_operability_fact"] = run_query(
                operability_sql,
                ttl_key=f"account_health_operability_fact_{company}_{get_active_environment()}_30",
                tier="standard",
                section="Account Health",
            )
            st.session_state["account_health_operability_fact_meta"] = _account_health_scope_meta(
                company, environment, window="30d"
            )
            st.session_state.pop("account_health_operability_fact_error", None)
        except Exception as fact_exc:
            st.session_state["account_health_operability_fact"] = pd.DataFrame()
            st.session_state["account_health_operability_fact_error"] = format_snowflake_error(fact_exc)
    operability_fact = st.session_state.get("account_health_operability_fact")
    account_control_board = _account_health_control_board(
        checklist,
        closure=st.session_state.get("account_health_closure_analytics"),
        access_hygiene=st.session_state.get("account_health_access_hygiene"),
        trend=st.session_state.get("account_health_checklist_trend"),
        environment=get_active_environment(),
    )
    operability_gate_fact = operability_fact if (
        operability_fact is not None
        and not operability_fact.empty
        and _account_health_meta_matches(
            st.session_state.get("account_health_operability_fact_meta"),
            _account_health_scope_meta(company, environment, window="30d"),
        )
    ) else pd.DataFrame()
    account_operator_gates = _account_health_operator_next_moves(
        health_score=health_score,
        checklist=checklist,
        control_board=account_control_board,
        closure=st.session_state.get("account_health_closure_analytics"),
        access_hygiene=st.session_state.get("account_health_access_hygiene"),
        operability_fact=operability_gate_fact,
        source_health=_account_health_source_health_rows(st.session_state, company, environment),
    )
    account_intervention_matrix = _account_health_intervention_matrix(
        checklist=checklist,
        control_board=account_control_board,
        closure=st.session_state.get("account_health_closure_analytics"),
        access_hygiene=st.session_state.get("account_health_access_hygiene"),
        operability_fact=operability_gate_fact,
    )
    account_morning_exceptions = _account_health_morning_exception_rows(
        checklist=checklist,
        gates=account_operator_gates,
        interventions=account_intervention_matrix,
        control_board=account_control_board,
        health_score=health_score,
        err_count=err_count,
        queued=queued,
        pct_delta=pct_delta,
        failed_tasks=failed_tasks,
    )
    st.session_state["account_health_checklist"] = checklist
    st.session_state["account_health_operator_gates"] = account_operator_gates
    st.session_state["account_health_control_board"] = account_control_board
    st.session_state["account_health_intervention_matrix"] = account_intervention_matrix
    st.session_state["account_health_morning_exceptions"] = account_morning_exceptions
    _render_account_health_exception_strip(account_morning_exceptions)
    account_detail = st.selectbox(
        "Account Health detail",
        ("Checklist", "Gates", "Interventions", "Controls", "Operability"),
        label_visibility="collapsed",
        key="account_health_overview_detail",
    )
    if account_detail == "Checklist":
        actionable_checklist = _account_health_actionable_checklist(checklist)
        show_full_checklist = st.toggle(
            "Show full checklist",
            key="account_health_show_full_checklist",
            value=False,
            help="Default keeps morning triage focused on checklist rows that need DBA action.",
        )
        checklist_view, checklist_title, checklist_raw_label = _account_health_visible_checklist(
            checklist,
            show_full=show_full_checklist,
        )
        if checklist_view.empty and not show_full_checklist:
            st.success("No Account Health checklist exceptions for this loaded snapshot.")
        else:
            render_priority_dataframe(
                checklist_view,
                title=checklist_title,
                priority_columns=[
                    "SEVERITY", "STATUS", "CHECK", "EVIDENCE", "OWNER",
                    "ESCALATION_TARGET", "ROUTE", "ENVIRONMENT_SCOPE",
                    "DATABASE_CONTEXT", "SCOPE_CONFIDENCE", "QUEUE_READINESS",
                    "QUEUE_BLOCKERS", "APPROVAL_REQUIRED", "RECOVERY_SLA_TARGET_HOURS",
                    "NEXT_ACTION", "PROOF_REQUIRED",
                ],
                sort_by=["SEVERITY", "CHECK"],
                ascending=[True, True],
                raw_label=checklist_raw_label,
                height=300,
                max_rows=12,
            )
    elif account_detail == "Gates":
        render_priority_dataframe(
            account_operator_gates,
            title="Account Health operator next-move gates",
            priority_columns=["GATE", "STATE", "COUNT", "PROOF_REQUIRED", "NEXT_ACTION"],
            sort_by=["GATE_RANK", "COUNT"],
            ascending=[True, False],
            raw_label="All Account Health operator gates",
            height=240,
            max_rows=5,
        )
    elif account_detail == "Interventions" and not account_intervention_matrix.empty:
        render_priority_dataframe(
            account_intervention_matrix,
            title="Account Health DBA intervention matrix",
            priority_columns=[
                "DBA_PRIORITY", "INTERVENTION_STATE", "SURFACE", "SEVERITY", "ROUTE", "OWNER",
                "CONTROL_STATE", "QUEUE_READINESS", "CLOSURE_READINESS",
                "SCOPE_CONFIDENCE", "COUNT", "NEXT_DECISION", "PROOF_REQUIRED",
            ],
            sort_by=["DBA_PRIORITY", "COUNT", "SURFACE"],
            ascending=[True, False, True],
            raw_label="All Account Health DBA intervention rows",
            height=280,
            max_rows=8,
        )
    elif account_detail == "Controls" and not account_control_board.empty:
        render_priority_dataframe(
            account_control_board,
            title="Account Health control board",
            priority_columns=[
                "CONTROL_STATE", "CHECK_NAME", "STATUS", "SEVERITY", "ROUTE",
                "OWNER", "ENVIRONMENT_SCOPE", "DATABASE_CONTEXT", "SCOPE_CONFIDENCE",
                "QUEUE_READINESS", "QUEUE_BLOCKERS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                "FIXED_WITHOUT_VERIFICATION", "RECOVERY_RISK_ROWS", "VERIFIED_CLOSURES",
                "ISSUE_SNAPSHOTS", "RECOVERY_SLA_TARGET_HOURS", "NEXT_CONTROL_ACTION",
            ],
            sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
            ascending=[True, False, False, False],
            raw_label="All Account Health control rows",
            height=320,
            max_rows=12,
        )
    elif account_detail == "Operability":
        if (
            operability_fact is not None
            and not _account_health_meta_matches(
                st.session_state.get("account_health_operability_fact_meta"),
                _account_health_scope_meta(company, environment, window="30d"),
            )
        ):
            st.info("Loaded Account Health control summary is stale for the active scope. Reload before acting.")
        elif operability_fact is not None and not operability_fact.empty:
            blocked_states = operability_fact["CONTROL_STATE"].astype(str).str.contains(
                "Blocked|Overdue|Required|Review", case=False, na=False
            )
            render_shell_snapshot((
                ("Rows", f"{len(operability_fact):,}"),
                ("Blocked Review", f"{int(blocked_states.sum()):,}"),
                ("Overdue", f"{int(operability_fact.get('OVERDUE_OPEN', pd.Series(dtype=int)).sum()):,}"),
                ("Verified", f"{int(operability_fact.get('VERIFIED_CLOSURES', pd.Series(dtype=int)).sum()):,}"),
            ))
            render_priority_dataframe(
                operability_fact,
                title="Account Health blockers",
                priority_columns=[
                    "SNAPSHOT_DATE", "CONTROL_STATE", "CONTROL_SOURCE", "CHECK_NAME",
                    "ROUTE", "SEVERITY", "ENVIRONMENT", "HEALTH_SCORE", "ISSUE_ROWS",
                    "ROUTE_BLOCKER_ROWS", "QUEUE_REQUIRED_ROWS", "ACCESS_HYGIENE_ROWS",
                    "FAILED_LOGIN_ROWS", "PRIVILEGED_GRANT_ROWS", "OPEN_ACTIONS",
                    "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "VERIFIED_CLOSURES",
                    "OWNER_APPROVAL_GAP_ROWS", "RECOVERY_RISK_ROWS", "NEXT_CONTROL_ACTION",
                ],
                sort_by=["CONTROL_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "ISSUE_ROWS"],
                ascending=[True, False, False, False],
                raw_label="All Account Health control rows",
                height=320,
                max_rows=12,
            )
            with st.expander("Account Health Control Status", expanded=False):
                render_shell_snapshot((
                    ("Control summary", "Ready"),
                    ("Routed actions", "Review"),
                    ("Telemetry", "Required"),
                    ("Execution", "Runbook only"),
                ))
        elif st.session_state.get("account_health_operability_fact_error"):
            st.caption("Account Health control summary is not available yet. Ask the DBA on-call to enable the fast blocker surface.")
        else:
            st.caption("Load the control summary when you need blockers, routes, and telemetry status.")
    elif account_detail in {"Interventions", "Controls"}:
        st.success(f"No {account_detail.lower()} rows for the loaded scope.")
    if account_detail == "Checklist":
        q1, q2, q3 = st.columns([1, 1, 3])
        with q1:
            if st.button(
                "Queue Checklist Issues",
                key="account_health_queue_checklist",
                width="stretch",
                disabled=actionable_checklist.empty,
            ):
                action_session = _account_health_action_session("queue Account Health checklist issues")
                if action_session is not None:
                    _queue_account_health_checklist(
                        action_session,
                        checklist,
                        company=company,
                        environment=get_active_environment(),
                    )
        with q2:
            if st.button(
                "Save Checklist Snapshot",
                key="account_health_save_checklist_snapshot",
                width="stretch",
            ):
                action_session = _account_health_action_session("save Account Health checklist snapshot")
                if action_session is not None:
                    _save_account_health_checklist_snapshot(
                        action_session,
                        checklist,
                        company=company,
                        environment=get_active_environment(),
                        health_score=health_score,
                        detail_source=hd.get("_account_health_detail_source", ""),
                    )
        with q3:
            if actionable_checklist.empty:
                st.caption("Daily checklist is clean for this snapshot; no queue item is needed. Save the snapshot for trend tracking.")
            else:
                ready_count = int((actionable_checklist.get("QUEUE_READINESS", pd.Series(dtype=str)) == "Ready to Queue").sum())
                st.caption(
                    f"{len(actionable_checklist):,} checklist issue(s) will be saved with route, reviewer, "
                    f"telemetry basis, and scope context. {ready_count:,} are route-ready without blockers."
                )
    _render_account_health_access_hygiene(
        company=company,
        environment=get_active_environment(),
    )
    with st.expander("Daily DBA Checklist Trend", expanded=False):
        trend_days = day_window_selectbox(
            "Checklist trend window",
            key="account_health_checklist_trend_days",
            default=30,
        )
        if st.button("Load Checklist Trend", key="account_health_load_checklist_trend"):
            try:
                trend_sql = _account_health_checklist_history_sql(
                    trend_days,
                    company=company,
                    environment=get_active_environment(),
                )
                st.session_state["account_health_checklist_trend"] = run_query(
                    trend_sql,
                    ttl_key=f"account_health_checklist_trend_{company}_{get_active_environment()}_{trend_days}",
                    tier="standard",
                    section="Account Health",
                )
                st.session_state["account_health_checklist_trend_sql"] = trend_sql
                st.session_state["account_health_checklist_trend_meta"] = _account_health_scope_meta(
                    company, environment, window=f"{int(trend_days)}d"
                )
            except Exception as exc:
                st.warning(f"Checklist trend unavailable: {format_snowflake_error(exc)}")
        trend = st.session_state.get("account_health_checklist_trend")
        if (
            trend is not None
            and not _account_health_meta_matches(
                st.session_state.get("account_health_checklist_trend_meta"),
                _account_health_scope_meta(company, environment, window=f"{int(trend_days)}d"),
            )
        ):
            st.info("Loaded checklist trend is stale for the active scope. Reload before acting.")
        elif trend is not None and not trend.empty:
            render_priority_dataframe(
                trend,
                title="Checklist issues by recurring snapshot",
                priority_columns=[
                    "CHECK_NAME", "ISSUE_SNAPSHOTS", "SNAPSHOT_ROWS", "LAST_STATUS",
                    "LAST_SEVERITY", "OWNER", "ESCALATION_TARGET", "ROUTE", "AVG_HEALTH_SCORE",
                    "QUEUE_READINESS", "QUEUE_BLOCKERS", "SCOPE_CONFIDENCE",
                    "CONTROL_READINESS", "CONTROL_BLOCKER_SNAPSHOTS", "NEXT_CONTROL_ACTION",
                ],
                sort_by=["ISSUE_SNAPSHOTS", "LAST_SNAPSHOT_TS"],
                ascending=[False, False],
                raw_label="All checklist trend rows",
                height=260,
            )
        elif trend is not None:
            st.info("No checklist history rows found for the selected scope.")
    with st.expander("Daily DBA Closure Analytics", expanded=False):
        st.caption(
            "Uses Account Health action-queue rows to show whether checklist issues are still open, "
            "overdue, or waiting for telemetry to confirm closure."
        )
        closure_days = day_window_selectbox(
            "Closure analytics window",
            key="account_health_closure_days",
            default=30,
        )
        if st.button("Load Closure Analytics", key="account_health_load_closure_analytics"):
            try:
                closure_sql = _account_health_closure_analytics_sql(
                    closure_days,
                    company=company,
                    environment=get_active_environment(),
                )
                st.session_state["account_health_closure_analytics_sql"] = closure_sql
                st.session_state["account_health_closure_analytics"] = run_query(
                    closure_sql,
                    ttl_key=f"account_health_closure_analytics_{company}_{get_active_environment()}_{closure_days}",
                    tier="standard",
                    section="Account Health",
                )
                st.session_state["account_health_closure_analytics_meta"] = _account_health_scope_meta(
                    company, environment, window=f"{int(closure_days)}d"
                )
            except Exception as exc:
                st.session_state["account_health_closure_analytics"] = pd.DataFrame()
                st.warning(f"Closure analytics unavailable: {format_snowflake_error(exc)}")
                st.info("The action queue is not available in this environment yet. Ask the DBA team to enable it, then retry.")
        closure = st.session_state.get("account_health_closure_analytics")
        if (
            closure is not None
            and not _account_health_meta_matches(
                st.session_state.get("account_health_closure_analytics_meta"),
                _account_health_scope_meta(company, environment, window=f"{int(closure_days)}d"),
            )
        ):
            st.info("Loaded closure analytics are stale for the active scope. Reload before acting.")
        elif closure is not None and not closure.empty:
            render_priority_dataframe(
                closure,
                title="Checklist closure status gaps",
                priority_columns=[
                    "CHECK_NAME", "CLOSURE_READINESS", "OWNER", "APPROVER",
                    "TOTAL_ACTIONS", "OPEN_ACTIONS", "OVERDUE_OPEN",
                    "VERIFIED_CLOSURES", "FIXED_WITHOUT_VERIFICATION",
                    "OWNER_GAP_ROWS", "TICKET_GAP_ROWS", "APPROVER_GAP_ROWS",
                    "OWNER_APPROVAL_GAP_ROWS", "VERIFICATION_QUERY_GAP_ROWS",
                    "RECOVERY_RISK_ROWS", "NEXT_DUE_DATE", "LAST_STATUS", "NEXT_ACTION",
                ],
                sort_by=["CLOSURE_RANK", "OVERDUE_OPEN", "FIXED_WITHOUT_VERIFICATION", "OPEN_ACTIONS"],
                ascending=[True, False, False, False],
                raw_label="All closure analytics rows",
                height=300,
            )
            with st.expander("Closure Analytics Status", expanded=False):
                render_shell_snapshot((
                    ("Closure status", "Ready"),
                    ("Telemetry", "Review"),
                    ("Telemetry", "Required"),
                    ("Execution", "Runbook only"),
                ))
        elif closure is not None:
            st.info("No Account Health checklist action-queue rows found for the selected scope.")
    st.divider()
    show_loaded_time("account_health")

    st.markdown("**Quick Nav**")
    qnav_cols = st.columns(4)

    def _jump(tgt, workflow=None):
        apply_navigation_state(tgt)
        if workflow:
            set_state("workload_operations_workflow", workflow)

    for idx, (lbl, tgt, workflow) in enumerate([
        ("Live", "Workload Operations", "Performance & Contention"),
        ("Query", "Workload Operations", "Query Investigation"),
        ("Cost", "Cost & Contract", None),
        ("DBA", "Security Monitoring", None),
    ]):
        with qnav_cols[idx]:
            st.button(lbl, key=f"jump_{lbl}", on_click=_jump, args=(tgt, workflow), width="stretch")

    secondary_sig = f"{filter_sig}|{environment}"
    secondary_loaded = st.session_state.get("_account_health_secondary_sig") == secondary_sig
    if st.button("Load Secondary Details", key="account_health_load_secondary_evidence"):
        st.session_state["_account_health_secondary_sig"] = secondary_sig
        secondary_loaded = True
    if not secondary_loaded:
        st.caption(
            "Secondary cost slices, monitoring-cost detail, and warehouse-pressure charts stay unloaded "
            "until they are needed for the current investigation."
        )
        return

    st.divider()
    st.markdown("**Executive Landing Signals**")
    e1, e2, e3, e4 = st.columns(4)

    with e1:
        st.markdown("**Top 5 cost drivers today**")
        cost_df = hd.get("cost_drivers", pd.DataFrame())
        if cost_df is not None and not cost_df.empty:
            cost_df["EST_COST"] = cost_df["TOTAL_CREDITS"].apply(
                lambda x: credits_to_dollars(x, credit_price)
            )
            render_priority_dataframe(
                cost_df,
                title="Top cost drivers today",
                priority_columns=[
                    "WAREHOUSE_NAME", "USER_NAME", "TOTAL_CREDITS",
                    "EST_COST", "QUERY_COUNT", "AVG_ELAPSED_SEC",
                ],
                sort_by=["TOTAL_CREDITS", "EST_COST"],
                ascending=[False, False],
                raw_label="All daily cost drivers",
                height=220,
            )
            if "USER_NAME" in cost_df.columns:
                sel_user = st.selectbox(
                    "-> Drill into user", ["(none)"] + cost_df["USER_NAME"].dropna().tolist(),
                    key="ah_drill_user", label_visibility="collapsed",
                )
                if sel_user and sel_user != "(none)":
                    if st.button(f"Open Cost & Contract for {sel_user}", key="ah_drill_user_btn"):
                        _drill_to(
                            "Cost & Contract",
                            user_filter=sel_user,
                            workflow_key="cost_contract_workflow",
                            workflow="Cost Explorer",
                            extra_state={"cost_center_view": "Cost Explorer", "cc_explorer_lens": "User / Role"},
                        )
        else:
            st.info("No cost driver data yet.")

    with e2:
        st.markdown("**Top 5 failed jobs/tasks**")
        failed_df = hd.get("failed_jobs", pd.DataFrame())
        if failed_df is not None and not failed_df.empty:
            render_priority_dataframe(
                failed_df,
                title="Failed jobs and tasks",
                priority_columns=[
                    "NAME", "TASK_NAME", "ROOT_TASK_NAME", "STATE",
                    "QUERY_ID", "ERROR_MESSAGE", "SCHEDULED_TIME",
                ],
                sort_by=["SCHEDULED_TIME", "COMPLETED_TIME"],
                ascending=[False, False],
                raw_label="All failed jobs/tasks",
                height=220,
            )
            if st.button("Task Management", key="ah_drill_tasks"):
                set_state("workload_operations_workflow", "Pipeline & Task Health")
                st.session_state["workload_operations_pipeline_focus"] = "Failed Tasks"
                _drill_to("Workload Operations")
        else:
            st.success("No failed tasks in the last 24h.")

    with e3:
        st.markdown("**What changed since yesterday**")
        change_df = hd.get("what_changed", pd.DataFrame())
        if change_df is not None and not change_df.empty:
            row = change_df.iloc[0]
            render_shell_snapshot(
                (
                    ("Queries", f"{safe_int(row.get('QUERY_DELTA', 0)):+,}"),
                    ("Credits", f"{safe_float(row.get('CREDIT_DELTA', 0)):+,.2f}"),
                    ("Failures", f"{safe_int(row.get('FAILURE_DELTA', 0)):+,}"),
                )
            )
        else:
            st.info("Change summary unavailable.")

    with e4:
        st.markdown("**Recommended next action**")
        st.info("Use Cost & Contract for optimization actions, action queue triage, and Teams-ready alerting.")
        if st.button("Open Cost & Contract", key="ah_open_recommendations"):
            _drill_to(
                "Cost & Contract",
                workflow_key="cost_contract_workflow",
                workflow="Cost Recommendations",
            )

    if exceptions_only:
        return

    st.divider()
    st.markdown("**Warehouse Pressure (last 1h)**")
    try:
        if control_mart_used:
            df_wp = run_query(
                build_mart_control_room_warehouse_pressure_sql(1, company),
                ttl_key=f"account_health_wh_pressure_mart_{company}",
                tier="historical",
                section="Account Health",
            )
            if df_wp is not None and not df_wp.empty:
                df_wp = df_wp.rename(columns={
                    "TOTAL_QUERIES": "QUERIES",
                    "QUEUED_QUERIES": "QUEUED",
                })
        else:
            qh = _query_history_capabilities()
            pressure_wh_size_expr = qh["pressure_wh_size_expr"]
            queued_count_expr_plain = qh["queued_count_expr_plain"]
            df_wp = run_query(f"""
                SELECT warehouse_name, {pressure_wh_size_expr} AS warehouse_size, COUNT(*) AS queries,
                       {queued_count_expr_plain} AS queued
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE start_time >= DATEADD('hours',-1,CURRENT_TIMESTAMP())
                  AND warehouse_name IS NOT NULL
                  {wh_filter_m}
                GROUP BY warehouse_name ORDER BY queries DESC LIMIT 8
            """, ttl_key=f"account_health_wh_pressure_live_{company}", tier="recent", section="Account Health")
        if not df_wp.empty:
            top_wh = df_wp.sort_values(["QUEUED","QUERIES"], ascending=False).iloc[0]
            render_shell_snapshot(
                (
                    ("Top pressure", top_wh["WAREHOUSE_NAME"]),
                    ("Queue / queries", f"{int(top_wh['QUEUED'])} queued / {int(top_wh['QUERIES'])} queries"),
                )
            )
            render_drillable_bar_chart(
                df_wp, dimension="WAREHOUSE_NAME", measure="QUERIES",
                key="ah_warehouse_pressure", title="Warehouse pressure drill-down",
                drilldown_column="warehouse_name", lookback_hours=24, top_n=8,
            )
            st.markdown("**Jump to Cost & Contract:**")
            wh_cols = st.columns(min(len(df_wp), 4))
            for idx, wh_row in df_wp.head(4).iterrows():
                wh_name = wh_row["WAREHOUSE_NAME"]
                with wh_cols[idx % 4]:
                    if st.button(wh_name, key=f"ah_wh_drill_{wh_name}"):
                        _drill_to("Cost & Contract", wh_filter=wh_name)
    except Exception as e:
        st.caption(f"Warehouse pressure unavailable: {format_snowflake_error(e)}")


__all__ = [
    "_drill_to",
    "render_account_health_overview",
]
