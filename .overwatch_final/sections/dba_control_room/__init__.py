"""DBA Control Room - operational landing page for OVERWATCH.

This page is intentionally workflow-first. It summarizes exceptions that a DBA
must triage, routes each signal to the right specialist tool, and creates
report-ready notes for leadership without making executives use the app.

This package was split from a single large module into themed submodules.
The public import surface (``sections.dba_control_room``) is preserved: every
previously top-level name is re-exported here, and the data loaders that tests
monkeypatch via ``sections.dba_control_room.run_query`` are defined in this module
so the patch target resolves correctly.
"""
from __future__ import annotations

from datetime import date
from datetime import datetime
from utils.primitives import safe_float

from .types import (
    pd,
    get_active_environment,
    get_credit_price,
    metric_confidence_label,
    freshness_note,
    _gate_state_from_counts,
    render_operator_briefing,
    build_metered_credit_cte,
    build_task_failure_summary_sql,
    build_task_history_sql,
    credits_to_dollars,
    dba_control_plane_section_scorecards,
    dba_effective_readiness_score,
    download_csv,
    enrich_action_queue_view,
    format_credits,
    format_snowflake_error,
    filter_existing_columns,
    get_db_filter_clause,
    get_active_company,
    get_global_filter_clause,
    get_session,
    get_user_company_filter_clause,
    get_wh_filter_clause,
    get_owner_context_columns,
    build_mart_control_room_summary_sql,
    build_mart_control_room_credits_sql,
    build_mart_control_room_cost_drivers_sql,
    build_mart_control_room_warehouse_pressure_sql,
    build_mart_control_room_failed_queries_sql,
    build_mart_control_room_object_changes_sql,
    build_mart_control_room_failed_logins_sql,
    build_mart_control_room_task_failures_sql,
    build_mart_query_detail_recent_sql,
    build_mart_task_history_sql,
    build_mart_procedure_sla_sql,
    build_schema_migration_status_sql,
    load_latest_control_room_mart,
    load_task_inventory,
    load_action_queue,
    load_app_observability_detail,
    load_change_correlation_detail,
    load_change_event_detail,
    load_closed_loop_execution_plan_detail,
    load_closed_loop_verification_detail,
    load_closed_loop_workflow_detail,
    load_command_center_evidence_detail,
    load_command_center_finding_detail,
    load_command_center_recommendation_detail,
    load_data_trust_detail,
    load_executive_scorecard_detail,
    load_forecast_detail,
    load_production_validation_detail,
    run_query,
    sql_literal,
    resolve_owner_context,
    render_priority_dataframe,
    render_load_status,
    render_workflow_selector,
    DBA_CONTROL_SCOPE_FILTER_KEYS,
    DBA_CONTROL_ROOM_PANES,
    DBA_CONTROL_ROOM_PANE_LABELS,
    DBA_CONTROL_ROOM_DETAIL_PANES,
    DBA_CONTROL_ROOM_DERIVED_STATE_KEYS,
    DBA_CONTROL_ROOM_LIVE_FALLBACK_CAP_HOURS,
    DBA_CONTROL_ROOM_LIVE_FALLBACK_KEYS,
    _live_fallback_deferred_message,
    _clear_dba_control_room_derived_state,
    _empty_df,
    _dba_control_scope_value,
    _frame_or_empty,
    _row_value,
)
from .health import (
    _dba_control_ops_scope_key,
    _task_management_helpers,
    _cortex_helpers,
    _procedure_helpers,
    _dba_control_scope_meta,
    _dba_control_meta_matches,
    _dba_snapshot_scope_compatible,
    _dba_control_source_health_rows,
    _dba_task_status_task_summary,
    _normalize_focus_frame,
    _target_object_from_row,
    _focus_context_from_row,
    _first_focus_context,
    _top_warehouse_focus_context,
    _task_failure_root_cause,
    _build_task_failure_root_cause_timeline,
    _build_auto_release_readiness_gate,
    _evidence_surface_route,
    _evidence_freshness_core_surface,
    _build_evidence_freshness_gate,
    _snapshot_metric,
    _control_room_snapshot_to_data,
    _scalar_frame_value,
    _release_window_predicate,
    _clean_release_text,
    _aggregate_release_window,
    _pct_change,
    _release_signal,
    _compare_release_windows,
    _prepare_task_release_runs,
    _build_procedure_release_sql,
    _prepare_procedure_release_runs,
    _build_release_compare_report,
    _finalize_control_room_data,
    _dba_source_health_deployment_gate,
    _control_room_score,
)
from .queue import (
    _severity_rows,
    _priority_exceptions,
    _command_queue_route,
    _canonical_dba_route,
    _normalize_section_score_rows,
    _command_owner_entity_type,
    _command_value_present,
    _command_text_present,
    _command_named_owner,
    _enrich_command_owner_context,
    _command_requires_approval,
    _command_closure_issue_flags,
    _command_closure_next_action,
    _command_queue_closure_readiness,
    _command_execution_metadata,
    _build_command_queue,
    _command_queue_summary,
    _command_queue_route_readiness,
    _dba_section_proof_required,
    _dba_section_operability_board,
    _dba_operations_priority_state,
    _dba_operations_priority_index,
)
from .incidents import (
    _dba_incident_type,
    _dba_incident_rank,
    _dba_incident_sla_target,
    _dba_incident_containment_action,
    _dba_incident_investigation_path,
    _dba_incident_board,
    _dba_runbook_route_templates,
    _dba_template_route_for_signal,
    _dba_operator_runbook,
    _build_dba_operator_runbook_markdown,
    _dba_escalation_priority_level,
    _dba_escalation_go_no_go,
    _dba_escalation_packet,
    _build_dba_escalation_packet_markdown,
    _build_dba_incident_markdown,
)
from .handoff import (
    _dba_workload_morning_lanes,
    _dba_morning_brief_rows,
    _dba_morning_decision_contract,
    _add_dba_morning_decision_contract,
    _dba_morning_execution_contract,
    _dba_morning_focus_note,
    _dba_morning_command_queue,
    _dba_morning_brief_detail_view,
    _build_dba_morning_brief_markdown,
    _seed_dba_morning_route_context,
    _dba_action_brief,
    _dba_command_lanes,
    _dba_handoff_rows,
    _build_dba_shift_handoff_markdown,
)




def _load_release_compare(
    session,
    company: str,
    before_start: date,
    before_end: date,
    after_start: date,
    after_end: date,
    runtime_pct_threshold: float,
    runtime_delta_sec_threshold: float,
    credit_pct_threshold: float,
    credit_delta_threshold: float,
) -> dict:
    _, _, _, _, _query_detail_sql = _task_management_helpers()
    _, _, _, _query_history_has_root_query_id = _procedure_helpers()
    task_inventory = load_task_inventory(session, company)

    def load_task_window(label: str, start: date, end: date) -> pd.DataFrame:
        history = run_query(
            build_task_history_sql(
                session,
                _release_window_predicate("scheduled_time", start, end),
                limit=2000,
                company=company,
            ),
            ttl_key=f"dba_release_{company}_{label}_{start}_{end}_task_history",
            tier="historical",
            section="DBA Control Room",
        )
        query_details = _empty_df()
        if not history.empty and "QUERY_ID" in history.columns:
            qids = history["QUERY_ID"].dropna().astype(str).tolist()
            query_sql = _query_detail_sql(session, qids)
            if query_sql:
                query_details = run_query(
                    query_sql,
                    ttl_key=f"dba_release_{company}_{label}_{start}_{end}_task_query_detail_{len(qids)}",
                    tier="historical",
                    section="DBA Control Room",
                )
        return _prepare_task_release_runs(task_inventory, history, query_details)

    has_root_query_id = _query_history_has_root_query_id(session)

    def load_proc_window(label: str, start: date, end: date) -> pd.DataFrame:
        runs = run_query(
            _build_procedure_release_sql(session, company, start, end, has_root_query_id),
            ttl_key=f"dba_release_{company}_{label}_{start}_{end}_procedure_runs_{has_root_query_id}",
            tier="historical",
            section="DBA Control Room",
        )
        return _prepare_procedure_release_runs(runs)

    task_before = load_task_window("before", before_start, before_end)
    task_after = load_task_window("after", after_start, after_end)
    proc_before = load_proc_window("before", before_start, before_end)
    proc_after = load_proc_window("after", after_start, after_end)

    return {
        "task_compare": _compare_release_windows(
            task_before,
            task_after,
            "TASK_NAME",
            runtime_pct_threshold=runtime_pct_threshold,
            runtime_delta_sec_threshold=runtime_delta_sec_threshold,
            credit_pct_threshold=credit_pct_threshold,
            credit_delta_threshold=credit_delta_threshold,
        ),
        "procedure_compare": _compare_release_windows(
            proc_before,
            proc_after,
            "PROCEDURE_NAME",
            runtime_pct_threshold=runtime_pct_threshold,
            runtime_delta_sec_threshold=runtime_delta_sec_threshold,
            credit_pct_threshold=credit_pct_threshold,
            credit_delta_threshold=credit_delta_threshold,
        ),
        "task_before": task_before,
        "task_after": task_after,
        "procedure_before": proc_before,
        "procedure_after": proc_after,
        "before_label": f"{before_start.isoformat()} to {before_end.isoformat()}",
        "after_label": f"{after_start.isoformat()} to {after_end.isoformat()}",
        "thresholds": {
            "runtime_pct_threshold": safe_float(runtime_pct_threshold),
            "runtime_delta_sec_threshold": safe_float(runtime_delta_sec_threshold),
            "credit_pct_threshold": safe_float(credit_pct_threshold),
            "credit_delta_threshold": safe_float(credit_delta_threshold),
        },
    }



def _load_control_room(
    session,
    company: str,
    credit_price: float,
    lookback_hours: int,
    cortex_budget_usd: float,
    *,
    include_deep_evidence: bool = False,
    allow_live_fallback: bool = False,
) -> dict:
    _build_task_ops_frames, _, _, _, _query_detail_sql = _task_management_helpers()
    _build_procedure_sla_frames, _build_procedure_sla_sql, _, _query_history_has_root_query_id = _procedure_helpers()
    _build_cortex_control_sql, _, _ = _cortex_helpers()
    wh_q = get_wh_filter_clause("q.warehouse_name", company)
    wh_m = get_wh_filter_clause("warehouse_name", company)
    db_q = get_db_filter_clause("q.database_name", company)
    global_q = get_global_filter_clause(
        "q.start_time", "q.warehouse_name", "q.user_name", "q.role_name", "q.database_name", "q.schema_name"
    )
    live_lookback_hours = min(int(lookback_hours), DBA_CONTROL_ROOM_LIVE_FALLBACK_CAP_HOURS)

    data: dict[str, pd.DataFrame] = {}
    queries = {
        "summary": f"""
            SELECT
                COUNT(*) AS total_queries,
                SUM(CASE WHEN error_code IS NOT NULL
                           OR UPPER(execution_status) = 'FAILED_WITH_ERROR'
                         THEN 1 ELSE 0 END) AS failed_queries,
                SUM(CASE WHEN COALESCE(queued_overload_time, 0)
                            + COALESCE(queued_provisioning_time, 0)
                            + COALESCE(queued_repair_time, 0) > 0
                         THEN 1 ELSE 0 END) AS queued_queries,
                SUM(CASE WHEN COALESCE(bytes_spilled_to_remote_storage, 0) > 0
                         THEN 1 ELSE 0 END) AS remote_spill_queries,
                ROUND(AVG(total_elapsed_time) / 1000, 2) AS avg_elapsed_sec,
                ROUND(APPROX_PERCENTILE(total_elapsed_time / 1000, 0.95), 2) AS p95_elapsed_sec,
                COUNT(DISTINCT warehouse_name) AS active_warehouses,
                COUNT(DISTINCT user_name) AS active_users
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {global_q}
        """,
        "credits": f"""
            SELECT
                SUM(CASE WHEN start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
                         THEN credits_used ELSE 0 END) AS period_credits,
                SUM(CASE WHEN start_time >= DATEADD('hour', -{int(live_lookback_hours * 2)}, CURRENT_TIMESTAMP())
                          AND start_time < DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
                         THEN credits_used ELSE 0 END) AS prior_credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE start_time >= DATEADD('hour', -{int(live_lookback_hours * 2)}, CURRENT_TIMESTAMP())
              {wh_m}
        """,
        "cost_drivers": f"""
            WITH {build_metered_credit_cte(hours_back=live_lookback_hours, include_recent=True)}
            SELECT
                q.user_name,
                q.warehouse_name,
                COUNT(*) AS query_count,
                ROUND(SUM(COALESCE(pqc.metered_credits, 0)), 4) AS allocated_credits,
                ROUND(SUM(COALESCE(q.bytes_scanned, 0)) / POWER(1024, 3), 2) AS gb_scanned,
                ROUND(AVG(q.total_elapsed_time) / 1000, 2) AS avg_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            LEFT JOIN per_query_credits pqc ON q.query_id = pqc.query_id
            WHERE q.start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {global_q}
            GROUP BY q.user_name, q.warehouse_name
            HAVING SUM(COALESCE(pqc.metered_credits, 0)) > 0
            ORDER BY allocated_credits DESC
            LIMIT 10
        """,
        "warehouse_pressure": f"""
            SELECT
                q.warehouse_name,
                MAX(q.warehouse_size) AS warehouse_size,
                COUNT(*) AS total_queries,
                SUM(CASE WHEN COALESCE(q.queued_overload_time, 0)
                            + COALESCE(q.queued_provisioning_time, 0)
                            + COALESCE(q.queued_repair_time, 0) > 0
                         THEN 1 ELSE 0 END) AS queued_queries,
                SUM(CASE WHEN COALESCE(q.bytes_spilled_to_remote_storage, 0) > 0
                         THEN 1 ELSE 0 END) AS remote_spill_queries,
                ROUND(SUM(COALESCE(q.bytes_spilled_to_remote_storage, 0)) / POWER(1024, 3), 2) AS remote_spill_gb,
                ROUND(APPROX_PERCENTILE(q.total_elapsed_time / 1000, 0.95), 2) AS p95_elapsed_sec
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND q.warehouse_name IS NOT NULL
              {global_q}
            GROUP BY q.warehouse_name
            HAVING queued_queries > 0 OR remote_spill_queries > 0 OR p95_elapsed_sec >= 60
            ORDER BY queued_queries DESC, remote_spill_gb DESC, p95_elapsed_sec DESC
            LIMIT 10
        """,
        "failed_queries": f"""
            SELECT
                q.query_id,
                q.user_name,
                q.role_name,
                q.warehouse_name,
                q.database_name,
                q.query_type,
                q.error_code,
                LEFT(q.error_message, 240) AS error_message,
                q.start_time
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND (q.error_code IS NOT NULL OR UPPER(q.execution_status) = 'FAILED_WITH_ERROR')
              {global_q}
            ORDER BY q.start_time DESC
            LIMIT 25
        """,
        "object_changes": f"""
            SELECT
                q.start_time,
                q.user_name,
                q.role_name,
                q.query_type,
                q.database_name,
                q.schema_name,
                q.warehouse_name,
                LEFT(q.query_text, 220) AS query_preview
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
            WHERE q.start_time >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND (
                    q.query_type ILIKE 'CREATE%'
                 OR q.query_type ILIKE 'ALTER%'
                 OR q.query_type ILIKE 'DROP%'
                 OR q.query_type ILIKE 'GRANT%'
                 OR q.query_type ILIKE 'REVOKE%'
              )
              {global_q}
            ORDER BY q.start_time DESC
            LIMIT 25
        """,
        "failed_logins": f"""
            SELECT
                event_timestamp,
                user_name,
                client_ip,
                reported_client_type,
                error_code,
                error_message
            FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
            WHERE event_timestamp >= DATEADD('hour', -{live_lookback_hours}, CURRENT_TIMESTAMP())
              AND is_success = 'NO'
              {get_user_company_filter_clause("user_name", company)}
            ORDER BY event_timestamp DESC
            LIMIT 25
        """,
    }

    mart_queries = {
        "summary": build_mart_control_room_summary_sql(lookback_hours, company),
        "credits": build_mart_control_room_credits_sql(lookback_hours, company),
        "cost_drivers": build_mart_control_room_cost_drivers_sql(lookback_hours, company),
        "warehouse_pressure": build_mart_control_room_warehouse_pressure_sql(lookback_hours, company),
        "failed_queries": build_mart_control_room_failed_queries_sql(lookback_hours, company),
        "object_changes": build_mart_control_room_object_changes_sql(lookback_hours, company),
        "failed_logins": build_mart_control_room_failed_logins_sql(lookback_hours, company),
    }
    source_rows: list[dict] = []
    for key, sql in queries.items():
        try:
            try:
                data[key] = run_query(
                    mart_queries[key],
                    ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_{key}",
                    tier="historical",
                    section="DBA Control Room",
                )
                source_rows.append({"Source": key, "Mode": "Fast summary"})
            except Exception as mart_exc:
                if not allow_live_fallback:
                    data[key] = _empty_df()
                    data[f"{key}_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                    source_rows.append({
                        "Source": key,
                        "Mode": "Fast summary unavailable",
                        "Message": "Live fallback skipped to keep DBA Control Room responsive.",
                    })
                    continue
                if key not in DBA_CONTROL_ROOM_LIVE_FALLBACK_KEYS:
                    data[key] = _empty_df()
                    data[f"{key}_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                    source_rows.append({
                        "Source": key,
                        "Mode": "Live fallback deferred",
                        "Message": _live_fallback_deferred_message(key, mart_exc),
                    })
                    continue
                data[key] = run_query(
                    sql,
                    ttl_key=f"dba_control_room_live_{company}_{live_lookback_hours}_{key}",
                    tier="recent",
                    section="DBA Control Room",
                )
                source_rows.append({
                    "Source": key,
                    "Mode": "Limited live fallback",
                    "Message": (
                        f"Fast summary unavailable; ran a bounded ACCOUNT_USAGE probe capped at "
                        f"{live_lookback_hours}h. {format_snowflake_error(mart_exc)}"
                    ),
                })
        except Exception as exc:
            data[key] = _empty_df()
            data[f"{key}_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        try:
            data["task_failures"] = run_query(
                build_mart_control_room_task_failures_sql(lookback_hours, company),
                ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_task_failures",
                tier="historical",
                section="DBA Control Room",
            )
            source_rows.append({"Source": "task_failures", "Mode": "Fast summary"})
        except Exception as mart_exc:
            if not allow_live_fallback:
                data["task_failures"] = _empty_df()
                data["task_failures_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                source_rows.append({
                    "Source": "task_failures",
                    "Mode": "Fast summary unavailable",
                    "Message": "Live fallback skipped to keep DBA Control Room responsive.",
                })
            else:
                data["task_failures"] = _empty_df()
                data["task_failures_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(mart_exc)]})
                source_rows.append({
                    "Source": "task_failures",
                    "Mode": "Live fallback deferred",
                    "Message": _live_fallback_deferred_message("task_failures", mart_exc),
                })
    except Exception as exc:
        data["task_failures"] = _empty_df()
        data["task_failures_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    if include_deep_evidence and allow_live_fallback:
        try:
            from sections.workload_operations import _build_workload_task_status_sql

            environment = get_active_environment()
            data["workload_task_status"] = run_query(
                _build_workload_task_status_sql(company, environment, hours=min(int(lookback_hours), 24)),
                ttl_key=f"dba_control_room_{company}_{environment}_{lookback_hours}_workload_task_status",
                tier="metadata",
                section="DBA Control Room",
            )
            source_rows.append({"Source": "workload_task_status", "Mode": "Snowflake task metadata"})
        except Exception as exc:
            data["workload_task_status"] = _empty_df()
            data["workload_task_status_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})
            source_rows.append({
                "Source": "workload_task_status",
                "Mode": "Metadata unavailable",
                "Message": "Snowflake TASK_HISTORY summary unavailable; verify ACCOUNT_USAGE access or refresh later.",
            })
    else:
        data["workload_task_status"] = _empty_df()
        source_rows.append({
            "Source": "workload_task_status",
            "Mode": "Live fallback deferred" if allow_live_fallback else "Fast summary unavailable",
            "Message": "Snowflake TASK_HISTORY summary runs only when deep telemetry and live fallback are both enabled.",
        })

    try:
        data["schema_migration_status"] = run_query(
            build_schema_migration_status_sql(),
            ttl_key="dba_control_room_schema_migration_status",
            tier="metadata",
            section="DBA Control Room",
        )
        source_rows.append({"Source": "schema_migration_status", "Mode": "Snowflake metadata"})
    except Exception as exc:
        data["schema_migration_status"] = _empty_df()
        data["schema_migration_status_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})
        source_rows.append({
            "Source": "schema_migration_status",
            "Mode": "Metadata unavailable",
            "Message": "Release migration status unavailable; complete status or remediation review before release review.",
        })

    if not include_deep_evidence:
        data["task_sla_cost"] = _empty_df()
        data["task_latest_runs"] = _empty_df()
        data["procedure_sla_cost"] = _empty_df()
        data["procedure_latest_runs"] = _empty_df()
        data["cortex_summary"] = _empty_df()
        data["cortex_exceptions"] = _empty_df()
        source_rows.extend([
            {
                "Source": "task_sla_history",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Workload Operations for task run telemetry.",
            },
            {
                "Source": "procedure_sla",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Workload Operations for procedure SLA/cost telemetry.",
            },
            {
                "Source": "cortex_cost",
                "Mode": "Deferred",
                "Message": "Skipped for fast DBA Control Room triage. Use Cost & Contract for Cortex cost telemetry.",
            },
        ])
        try:
            data["action_queue"] = load_action_queue(session, limit=25)
        except Exception as exc:
            data["action_queue"] = _empty_df()
            data["action_queue_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})
        return _finalize_control_room_data(data, source_rows, credit_price, cortex_budget_usd)

    try:
        task_inventory = load_task_inventory(session, company)
        task_history_source = "Fast summary"
        try:
            task_history = run_query(
                build_mart_task_history_sql(max(1, int((lookback_hours + 23) / 24)), company=company, limit=1000),
                ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_task_sla_history",
                tier="historical",
                section="DBA Control Room",
            )
        except Exception as mart_exc:
            if not allow_live_fallback:
                task_history_source = "Fast summary unavailable"
                task_history = _empty_df()
            else:
                task_history_source = "Live fallback deferred"
                task_history = _empty_df()
            source_rows.append({
                "Source": "task_sla_history",
                "Mode": task_history_source,
                "Message": (
                    "Live fallback skipped to keep DBA Control Room responsive."
                    if not allow_live_fallback
                    else _live_fallback_deferred_message("task_sla_history", mart_exc)
                ),
            })
        if task_history_source == "Fast summary":
            source_rows.append({"Source": "task_sla_history", "Mode": task_history_source})
        task_query_details = _empty_df()
        if not task_history.empty and "QUERY_ID" in task_history.columns:
            qids = task_history["QUERY_ID"].dropna().astype(str).tolist()
            try:
                query_sql = build_mart_query_detail_recent_sql(qids)
                if query_sql:
                    task_query_details = run_query(
                        query_sql,
                        ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_task_query_detail_{len(qids)}",
                        tier="historical",
                        section="DBA Control Room",
                    )
                    source_rows.append({"Source": "task_query_detail", "Mode": "Fast summary"})
            except Exception as mart_exc:
                source_rows.append({
                    "Source": "task_query_detail",
                    "Mode": "Live fallback deferred",
                    "Message": _live_fallback_deferred_message("task_query_detail", mart_exc),
                })
        _, task_ops_exceptions, task_latest = _build_task_ops_frames(task_inventory, task_history, task_query_details)
        data["task_sla_cost"] = task_ops_exceptions[
            task_ops_exceptions.get("SIGNAL", pd.Series(dtype=str)).isin([
                "Long Running / SLA Risk",
                "Cost Drift / Release Regression",
            ])
        ].copy() if not task_ops_exceptions.empty else _empty_df()
        data["task_latest_runs"] = task_latest
    except Exception as exc:
        data["task_sla_cost"] = _empty_df()
        data["task_latest_runs"] = _empty_df()
        data["task_sla_cost_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        try:
            proc_runs = run_query(
                build_mart_procedure_sla_sql(max(1, int((lookback_hours + 23) / 24)), company=company),
                ttl_key=f"dba_control_room_mart_{company}_{lookback_hours}_procedure_sla",
                tier="historical",
                section="DBA Control Room",
            )
            source_rows.append({"Source": "procedure_sla", "Mode": "Fast summary"})
        except Exception as mart_exc:
            proc_runs = _empty_df()
            source_rows.append({
                "Source": "procedure_sla",
                "Mode": "Live fallback deferred" if allow_live_fallback else "Fast summary unavailable",
                "Message": (
                    _live_fallback_deferred_message("procedure_sla", mart_exc)
                    if allow_live_fallback
                    else "Live fallback skipped to keep DBA Control Room responsive."
                ),
            })
        _, proc_exceptions, proc_latest = _build_procedure_sla_frames(proc_runs)
        data["procedure_sla_cost"] = proc_exceptions
        data["procedure_latest_runs"] = proc_latest
    except Exception as exc:
        data["procedure_sla_cost"] = _empty_df()
        data["procedure_latest_runs"] = _empty_df()
        data["procedure_sla_cost_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        data["action_queue"] = load_action_queue(session, limit=100)
    except Exception as exc:
        data["action_queue"] = _empty_df()
        data["action_queue_error"] = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})

    try:
        cortex_summary_sql, cortex_exceptions_sql = _build_cortex_control_sql(30, cortex_budget_usd)
        data["cortex_summary"] = run_query(
            cortex_summary_sql,
            ttl_key=f"dba_control_room_{company}_cortex_summary_{cortex_budget_usd}",
            tier="historical",
            section="DBA Control Room",
        )
        data["cortex_exceptions"] = run_query(
            cortex_exceptions_sql,
            ttl_key=f"dba_control_room_{company}_cortex_exceptions_{cortex_budget_usd}",
            tier="historical",
            section="DBA Control Room",
        )
    except Exception as exc:
        data["cortex_summary"] = _empty_df()
        data["cortex_exceptions"] = _empty_df()
        cortex_error = pd.DataFrame({"ERROR": [format_snowflake_error(exc)]})
        data["cortex_summary_error"] = cortex_error
        data["cortex_exceptions_error"] = cortex_error

    data["_loaded_at"] = pd.DataFrame({"LOADED_AT": [datetime.now().isoformat()]})
    data["_credit_price"] = pd.DataFrame({"CREDIT_PRICE": [credit_price]})
    data["_cortex_budget_usd"] = pd.DataFrame({"BUDGET_USD": [safe_float(cortex_budget_usd)]})
    data["_source_modes"] = pd.DataFrame(source_rows)
    return data


from .render import (
    _render_consolidated_service_posture,
    _render_enterprise_diagnostics_gate,
    _render_production_readiness_gate,
    _render_executive_scorecard_driver_gate,
    _render_forecast_exception_gate,
    _render_change_intelligence_gate,
    _render_closed_loop_operations_gate,
    _render_command_center_investigation_gate,
    _set_admin_tool_focus,
    _render_admin_tools,
    _jump,
    _render_operations_priority_index,
    _render_dba_operator_runbook,
    _render_dba_escalation_packet,
    _render_dba_morning_brief,
    _render_command_queue_control,
    _render_dba_command_intelligence_contract,
    _render_watch_floor,
    _render_dba_action_brief,
    _render_shift_handoff_panel,
    _render_loaded_advisor_signals,
    _render_incident_board_panel,
    _render_control_room_source_health,
    _render_release_readiness_gate,
    _render_route_buttons,
    render,
)

__all__ = [
    'DBA_CONTROL_ROOM_DERIVED_STATE_KEYS',
    'DBA_CONTROL_ROOM_DETAIL_PANES',
    'DBA_CONTROL_ROOM_LIVE_FALLBACK_CAP_HOURS',
    'DBA_CONTROL_ROOM_LIVE_FALLBACK_KEYS',
    'DBA_CONTROL_ROOM_PANES',
    'DBA_CONTROL_ROOM_PANE_LABELS',
    'DBA_CONTROL_SCOPE_FILTER_KEYS',
    '_add_dba_morning_decision_contract',
    '_aggregate_release_window',
    '_build_auto_release_readiness_gate',
    '_build_command_queue',
    '_build_dba_escalation_packet_markdown',
    '_build_dba_incident_markdown',
    '_build_dba_morning_brief_markdown',
    '_build_dba_operator_runbook_markdown',
    '_build_dba_shift_handoff_markdown',
    '_build_evidence_freshness_gate',
    '_build_procedure_release_sql',
    '_build_release_compare_report',
    '_build_task_failure_root_cause_timeline',
    '_canonical_dba_route',
    '_clean_release_text',
    '_clear_dba_control_room_derived_state',
    '_command_closure_issue_flags',
    '_command_closure_next_action',
    '_command_execution_metadata',
    '_command_named_owner',
    '_command_owner_entity_type',
    '_command_queue_closure_readiness',
    '_command_queue_route',
    '_command_queue_route_readiness',
    '_command_queue_summary',
    '_command_requires_approval',
    '_command_text_present',
    '_command_value_present',
    '_compare_release_windows',
    '_control_room_score',
    '_control_room_snapshot_to_data',
    '_cortex_helpers',
    '_dba_action_brief',
    '_dba_command_lanes',
    '_dba_control_meta_matches',
    '_dba_control_ops_scope_key',
    '_dba_control_scope_meta',
    '_dba_control_scope_value',
    '_dba_control_source_health_rows',
    '_dba_escalation_go_no_go',
    '_dba_escalation_packet',
    '_dba_escalation_priority_level',
    '_dba_handoff_rows',
    '_dba_incident_board',
    '_dba_incident_containment_action',
    '_dba_incident_investigation_path',
    '_dba_incident_rank',
    '_dba_incident_sla_target',
    '_dba_incident_type',
    '_dba_morning_brief_detail_view',
    '_dba_morning_brief_rows',
    '_dba_morning_command_queue',
    '_dba_morning_decision_contract',
    '_dba_morning_execution_contract',
    '_dba_morning_focus_note',
    '_dba_operations_priority_index',
    '_dba_operations_priority_state',
    '_dba_operator_runbook',
    '_dba_runbook_route_templates',
    '_dba_section_operability_board',
    '_dba_section_proof_required',
    '_dba_snapshot_scope_compatible',
    '_dba_source_health_deployment_gate',
    '_dba_task_status_task_summary',
    '_dba_template_route_for_signal',
    '_dba_workload_morning_lanes',
    '_empty_df',
    '_enrich_command_owner_context',
    '_evidence_freshness_core_surface',
    '_evidence_surface_route',
    '_finalize_control_room_data',
    '_first_focus_context',
    '_focus_context_from_row',
    '_frame_or_empty',
    '_gate_state_from_counts',
    '_jump',
    '_live_fallback_deferred_message',
    '_load_control_room',
    '_load_release_compare',
    '_normalize_focus_frame',
    '_normalize_section_score_rows',
    '_pct_change',
    '_prepare_procedure_release_runs',
    '_prepare_task_release_runs',
    '_priority_exceptions',
    '_procedure_helpers',
    '_release_signal',
    '_release_window_predicate',
    '_render_admin_tools',
    '_render_change_intelligence_gate',
    '_render_closed_loop_operations_gate',
    '_render_command_center_investigation_gate',
    '_render_command_queue_control',
    '_render_consolidated_service_posture',
    '_render_control_room_source_health',
    '_render_dba_action_brief',
    '_render_dba_command_intelligence_contract',
    '_render_dba_escalation_packet',
    '_render_dba_morning_brief',
    '_render_dba_operator_runbook',
    '_render_enterprise_diagnostics_gate',
    '_render_executive_scorecard_driver_gate',
    '_render_forecast_exception_gate',
    '_render_incident_board_panel',
    '_render_loaded_advisor_signals',
    '_render_operations_priority_index',
    '_render_production_readiness_gate',
    '_render_release_readiness_gate',
    '_render_route_buttons',
    '_render_shift_handoff_panel',
    '_render_watch_floor',
    '_row_value',
    '_scalar_frame_value',
    '_seed_dba_morning_route_context',
    '_set_admin_tool_focus',
    '_severity_rows',
    '_snapshot_metric',
    '_target_object_from_row',
    '_task_failure_root_cause',
    '_task_management_helpers',
    '_top_warehouse_focus_context',
    'build_mart_control_room_cost_drivers_sql',
    'build_mart_control_room_credits_sql',
    'build_mart_control_room_failed_logins_sql',
    'build_mart_control_room_failed_queries_sql',
    'build_mart_control_room_object_changes_sql',
    'build_mart_control_room_summary_sql',
    'build_mart_control_room_task_failures_sql',
    'build_mart_control_room_warehouse_pressure_sql',
    'build_mart_procedure_sla_sql',
    'build_mart_query_detail_recent_sql',
    'build_mart_task_history_sql',
    'build_metered_credit_cte',
    'build_schema_migration_status_sql',
    'build_task_failure_summary_sql',
    'build_task_history_sql',
    'credits_to_dollars',
    'dba_control_plane_section_scorecards',
    'dba_effective_readiness_score',
    'download_csv',
    'enrich_action_queue_view',
    'filter_existing_columns',
    'format_credits',
    'format_snowflake_error',
    'freshness_note',
    'get_active_company',
    'get_active_environment',
    'get_credit_price',
    'get_db_filter_clause',
    'get_global_filter_clause',
    'get_owner_context_columns',
    'get_session',
    'get_user_company_filter_clause',
    'get_wh_filter_clause',
    'load_action_queue',
    'load_app_observability_detail',
    'load_change_correlation_detail',
    'load_change_event_detail',
    'load_closed_loop_execution_plan_detail',
    'load_closed_loop_verification_detail',
    'load_closed_loop_workflow_detail',
    'load_command_center_evidence_detail',
    'load_command_center_finding_detail',
    'load_command_center_recommendation_detail',
    'load_data_trust_detail',
    'load_executive_scorecard_detail',
    'load_forecast_detail',
    'load_latest_control_room_mart',
    'load_production_validation_detail',
    'load_task_inventory',
    'metric_confidence_label',
    'pd',
    'render',
    'render_load_status',
    'render_operator_briefing',
    'render_priority_dataframe',
    'render_workflow_selector',
    'resolve_owner_context',
    'run_query',
    'sql_literal',
]
