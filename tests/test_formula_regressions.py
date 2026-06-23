from pathlib import Path
from datetime import datetime
import inspect
import math
import re
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


def _section_source(path: Path) -> str:
    """Read a section's source, transparently handling subpackages."""
    if path.suffix == ".py" and not path.exists():
        pkg = path.with_suffix("")
        if pkg.is_dir():
            return "\n".join(
                p.read_text(encoding="utf-8") for p in sorted(pkg.rglob("*.py"))
            )
    return path.read_text(encoding="utf-8")


from config import DEFAULTS, DEFAULT_ALERT_EMAIL  # noqa: E402
import sections.cost_contract as cost_contract  # noqa: E402
from sections.account_health import (  # noqa: E402
    _account_health_action_brief,
    _account_health_actionable_checklist,
    _account_health_visible_checklist,
    _account_health_access_hygiene_action_payload,
    _account_health_access_hygiene_sql,
    _account_health_access_hygiene_verification_sql,
    _annotate_account_health_access_hygiene,
    _annotate_account_health_checklist_readiness,
    _account_health_checklist_action_payload,
    _account_health_checklist_history_insert_sql,
    _account_health_checklist_history_sql,
    _account_health_closure_analytics_sql,
    _account_health_control_board,
    _account_health_intervention_matrix,
    _account_health_morning_exception_rows,
    _account_health_operability_fact_sql,
    _account_health_operator_next_moves,
    _account_health_source_health_rows,
    _build_account_health_dba_checklist,
    _enrich_account_health_checklist_owners,
    build_account_health_checklist_history_ddl,
    build_account_health_checklist_history_migration_sql,
    build_account_health_operability_fact_ddl,
    build_account_health_operability_fact_migration_sql,
    _load_live_query_status,
    _live_query_status_sql,
)
from sections.adoption_analytics import (  # noqa: E402
    _load_adoption_live,
    _metric as adoption_metric,
)
from sections.alert_center import (  # noqa: E402
    _alert_center_action_brief,
    _apply_alert_center_brief_first_default,
    _alert_center_brief_workflow_rows,
    _alert_center_exception_rows,
    _alert_center_pending_brief,
    _alert_center_operability_rows,
    _alert_center_health_score,
    _alert_domain_next_move_rows,
    _alert_integration_health_board,
    _alert_lifecycle_board,
    _alert_next_incident_packet,
    _alert_owner_route_board,
    _alert_operator_workflow_rows,
    _alert_operations_review_rows,
    _alert_company_scope_readiness_rows,
    _alert_threshold_tuning_rows,
)
from sections.query_analysis import (  # noqa: E402
    _build_ai_query_diagnosis_prompt,
    _build_query_diagnosis_action_contract,
    _build_query_optimization_candidates,
)
from utils.evidence_mode import (  # noqa: E402
    TRIAGE_MODE_ALL_EVIDENCE,
    TRIAGE_MODE_INVESTIGATE,
    TRIAGE_MODE_OPTIONS,
    TRIAGE_MODE_TRIAGE,
    current_evidence_mode,
    evidence_mode_from_exceptions,
    evidence_mode_is_all_evidence,
    evidence_mode_is_investigation,
    exceptions_enabled_from_evidence_mode,
    normalize_evidence_mode,
)
from sections.executive_landing import (  # noqa: E402
    _build_executive_observability_query_parts,
    _build_executive_observability_sql,
    _build_platform_operating_score,
    _executive_command_summary_rows,
    _executive_loaded_advisor_rows,
    _executive_priority_rows,
    _executive_pressure_rows,
    _render_command_center_summary,
    _summary_from_observability,
    _snapshot_matches_scope,
)
from sections.cost_center import (  # noqa: E402
    _annual_service_projection_metrics,
    _annual_service_projection_sql,
    _bill_driver_summary,
    _build_bill_waterfall,
    _build_finance_movement_summary,
    _chargeback_cost_verification_sql,
    _cost_explorer_gap_board,
    _cost_explorer_live_sql,
    _cost_explorer_summary,
    _prepare_cost_forecast_rows,
    _queue_cost_outliers,
    _normalize_cost_explorer_detail,
    _snowflake_admin_reconciliation_sql,
    _warehouse_cost_control_action,
    _service_cost_category,
    _warehouse_cost_verification_sql,
)
from sections.cost_contract import (  # noqa: E402
    _build_change_cost_correlation_board,
    _build_cost_advisor_board,
    _cost_advisor_action_summary,
    _cost_advisor_category_summary,
    _cost_advisor_detail_options,
    _build_cost_allocation_trust_board,
    _build_cost_closure_analytics,
    _build_cost_control_coverage_board,
    _build_cost_decomposition_board,
    _build_cost_cockpit_sql,
    _build_cost_monitor_service_trend_sql,
    _build_cost_drilldown_command_map,
    _build_cost_monitoring_alert_rows,
    _build_cost_incident_timeline,
    _build_cost_run_rate_sql,
    _build_cost_splash_cortex_sql,
    _build_cost_splash_warehouse_delta_sql,
    _build_cost_source_health_board,
    _build_cost_spike_root_cause_board,
    _build_resource_monitor_guardrail_sql,
    _build_attribution_gap_summary,
    _build_service_cost_lens_summary,
    _cost_spend_trend_rows,
    _cost_splash_next_move,
    _cost_splash_summary,
    _cost_warehouse_ranking_rows,
    _service_lens_movement_rows,
    build_cost_monitoring_mart_sql,
)
from sections.dba_control_room import (  # noqa: E402
    _build_command_queue,
    _command_queue_closure_readiness,
    _command_queue_summary,
    _command_queue_route_readiness,
    _build_dba_operator_runbook_markdown,
    _build_dba_escalation_packet_markdown,
    _build_dba_morning_brief_markdown,
    _dba_action_brief,
    _dba_escalation_packet,
    _dba_morning_brief_detail_view,
    _dba_morning_command_queue,
    _dba_morning_decision_contract,
    _dba_morning_brief_rows,
    _dba_workload_morning_lanes,
    _seed_dba_morning_route_context,
    _dba_operator_runbook,
    _dba_operations_priority_index,
    _dba_section_operability_board,
    _dba_section_proof_required,
    _dba_incident_board,
    _dba_handoff_rows,
    _dba_control_scope_meta,
    _dba_control_source_health_rows,
    _dba_snapshot_scope_compatible,
    _build_auto_release_readiness_gate,
    _build_evidence_freshness_gate,
    _build_dba_incident_markdown,
    _build_dba_shift_handoff_markdown,
    _build_release_compare_report,
    _build_task_failure_root_cause_timeline,
    _compare_release_windows,
    _control_room_snapshot_to_data,
    _load_control_room,
    _severity_rows as _dba_control_severity_rows,
)
from sections.cortex_monitor import (  # noqa: E402
    CORTEX_SERVICE_DETAIL_SOURCES,
    _build_cortex_control_markdown,
    _build_cortex_ai_functions_daily_sql,
    _cortex_candidate_columns,
    _cortex_action_for,
    _cortex_cost_rating,
    _cortex_cost_score,
    _cortex_service_detail_sql,
)
from sections.change_drift import (  # noqa: E402
    _change_blast_radius_sql,
    _change_action_queue_closure_sql,
    _build_change_control_readiness,
    _change_control_readiness_summary,
    _build_change_drift_markdown,
    _build_change_drift_sql,
    _build_mart_change_drift_sql,
    _change_action_for,
    _change_action_payload,
    _apply_change_brief_first_default,
    _change_brief_workflow_rows,
    _change_control_evidence_history_sql,
    _change_control_evidence_insert_sql,
    _change_drift_rating,
    _change_drift_score,
    _change_control_operability_fact_sql,
    _change_intervention_matrix,
    _change_operator_next_moves,
    _change_source_health_rows,
    _change_verification_sql,
    _enrich_change_control_evidence,
    build_change_control_evidence_ddl,
    build_change_control_evidence_migration_sql,
    build_change_control_operability_fact_ddl,
    build_change_control_operability_fact_migration_sql,
)
from sections.query_workbench import (  # noqa: E402
    _build_mart_root_cause_sql,
    _build_root_cause_markdown,
    _root_cause_cortex_prompt,
    _root_cause_action_for,
    _root_cause_priority_view,
    _root_cause_score,
    _seed_ai_query_diagnosis_from_row,
)
from sections.recommendations import (  # noqa: E402
    _build_warehouse_advisor_recommendations,
    _idle_warehouse_verification_sql,
    _query_failure_verification_sql,
    _remote_spill_verification_sql,
    _task_failure_verification_sql,
)
from sections.service_health import _value as service_value  # noqa: E402
from sections.security_posture import (  # noqa: E402
    _mfa_count_expr,
    _mfa_gap_predicate,
    _security_action_queue_closure_sql,
    _security_access_review_readiness_for_row,
    _annotate_security_privileged_grant_readiness,
    _privileged_grant_action_payload,
    _privileged_grant_verification_sql,
    _privilege_sprawl_summary,
    _build_security_access_review,
    _build_security_brief_markdown,
    _build_security_mart_brief_sql,
    _build_security_summary_sql,
    _security_control_board,
    _security_privileged_grant_review_sql,
    _security_operability_fact_sql,
    _security_source_health_rows,
    _security_access_review_history_sql,
    _security_access_review_insert_sql,
    _security_action_for,
    _security_exception_verification_sql,
    _security_exception_strip_rows,
    _security_brief_workflow_rows,
    _security_rating,
    _security_scope_meta,
    _security_workflow_for,
    _security_score,
    build_security_access_review_ddl,
    build_security_access_review_migration_sql,
    build_security_operability_fact_ddl,
    build_security_operability_fact_migration_sql,
)
from sections.security_access import (  # noqa: E402
    _build_mfa_coverage_sql,
    _user_mfa_column_exprs,
)
from sections.stored_proc_tracker import (  # noqa: E402
    _add_procedure_optimization_columns,
    _procedure_analysis_summary,
    _procedure_analysis_detail_options,
    _build_procedure_reliability_action,
    _build_procedure_reliability_slo_board,
    _build_procedure_sla_frames,
    _build_procedure_ops_frames,
    _procedure_from_task_definition,
    _procedure_key,
    _procedure_optimization_findings,
    _procedure_optimization_score,
)
from sections.task_management import (  # noqa: E402
    _admin_sql_for_graph,
    _admin_sql_for_task,
    _annotate_task_graph_impact,
    _build_failure_console_frames,
    _build_failure_runbook_markdown,
    _build_task_critical_path_snapshot,
    _build_task_status_error_board,
    _build_task_status_job_status_board,
    _build_task_reliability_action,
    _build_task_graph_dot,
    _build_task_ops_frames,
    _build_task_reliability_slo_board,
    _build_task_ops_markdown,
    _build_task_recovery_sla_frame,
    _task_recovery_command_board,
    build_admin_preflight_sql,
    _collect_graph_tasks,
    _extract_object_candidates,
    _failure_diagnosis,
    _parse_task_predecessors,
    _procedure_from_definition,
    _task_action_for,
    _task_ops_workflow_for,
    _task_ops_score,
    TASK_CONTROL_DETAILS,
    TASK_CONTROL_VIEWS,
)
from sections.usage_overview import _first_number as usage_first_number  # noqa: E402
from sections.warehouse_health import (  # noqa: E402
    _annotate_warehouse_admin_readiness,
    _warehouse_action_queue_closure_sql,
    _warehouse_setting_audit_readiness_for_row,
    _warehouse_setting_control_board,
    _warehouse_setting_execution_audit_sql,
    _warehouse_intervention_matrix,
    _warehouse_operator_next_moves,
    _build_warehouse_cost_control_posture,
    _build_warehouse_guardrail_coverage,
    _overwatch_dedicated_warehouse_setup_sql,
    _warehouse_setting_action_plan,
    _warehouse_setting_detail_options,
    _build_warehouse_capacity_markdown,
    _queue_efficiency_findings,
    _queue_capacity_findings,
    _warehouse_capacity_action_for,
    _warehouse_capacity_score,
    _warehouse_capacity_verification_sql,
    _warehouse_operability_fact_sql,
    _warehouse_source_health_rows,
    _apply_warehouse_brief_first_default,
    _warehouse_brief_workflow_rows,
    _warehouse_setting_review_history_sql,
    _warehouse_setting_review_insert_sql,
    build_warehouse_operability_fact_ddl,
    build_warehouse_operability_fact_migration_sql,
    build_warehouse_setting_review_ddl,
    build_warehouse_setting_review_migration_sql,
)
from utils.cost import (  # noqa: E402
    build_snowflake_service_cost_lens_sql,
    build_cost_reconciliation_sql,
    build_cost_efficiency_summary_sql,
    build_warehouse_efficiency_sql,
    build_clustering_cost_sql,
    build_idle_warehouse_sql,
    build_metered_credit_cte,
    credits_to_dollars,
    query_attribution_supported,
)
from utils.mart import build_mart_cost_service_lens_sql  # noqa: E402
from utils.compatibility import build_cost_formula_audit, clear_compatibility_process_cache  # noqa: E402
from utils.deployment import (  # noqa: E402
    OVERWATCH_SCHEMA_VERSION,
    STREAMLIT_DEPLOYMENT_DECISION_VERSION,
    build_schema_migration_contract,
    build_schema_migration_ddl,
    build_schema_migration_status_sql,
    build_streamlit_deployment_decision,
)
from utils.ask_overwatch import (  # noqa: E402
    answer_ask_overwatch,
    build_ask_overwatch_context,
    build_grounded_cortex_prompt,
    build_top_priority_brief_cards,
    filter_ask_overwatch_cards_by_domain,
    snapshot_ask_overwatch_state,
)
from utils.company_filter import (  # noqa: E402
    environment_label_for_database,
    get_environment_case_expr,
    get_environment_filter_clause,
    get_environment_filter_or_no_database_clause,
    get_global_filter_clause,
)
from utils.recommendation_intelligence import (  # noqa: E402
    build_automation_readiness_board,
    build_loaded_advisor_signal_board,
    duplicate_query_decision,
    harden_recommendation,
    recommendation_execution_contract,
    warehouse_sizing_decision,
)
from utils.action_queue import verification_query_safety_issues  # noqa: E402
from utils.alerts import (  # noqa: E402
    annotate_alert_triage_frame,
    alert_escalation_candidates,
    alert_history_to_actions,
    alert_rule_catalog,
    build_alert_digest_body,
    build_alert_digest_subject,
    build_alert_digest_summary,
    build_alert_acknowledgement_insert_sql,
    build_alert_delivery_log_ddl,
    build_alert_delivery_log_insert_sql,
    build_alert_delivery_mark_sql,
    build_alert_email_delivery_procedure_sql,
    build_alert_email_body,
    build_alert_email_subject,
    build_alert_escalation_ack_sql,
    build_alert_command_center_runbook_markdown,
    build_alert_command_center_setup_sql,
    build_alert_command_center_summary,
    build_alert_data_quality_check_seed_rows,
    build_alert_data_quality_checks_ddl,
    build_alert_event_materialization_sql,
    build_alert_incident_action_board,
    build_alert_native_deployment_review_rows,
    build_alert_native_deployment_review_sql,
    build_alert_native_object_registry_seed_rows,
    build_alert_native_registry_ddl,
    build_loaded_section_alert_signal_board,
    build_alert_morning_brief_rows,
    build_alert_optional_integrations,
    build_alert_owner_workload_board,
    build_alert_remediation_log_insert_sql,
    build_alert_remediation_contract,
    build_alert_remediation_policy_seed_rows,
    build_alert_remediation_policy_ddl,
    build_alert_required_privileges,
    build_alert_rule_audit_ddl,
    build_alert_rule_audit_insert_sql,
    build_alert_rule_update_sql,
    build_section_alert_signal_board,
    build_cost_cortex_alert_drilldown,
    build_alert_signal_query_catalog,
    build_alert_status_update_sql,
    build_alert_threshold_seed_rows,
    build_alert_triage_view_sql,
    build_dashboard_issue_rows,
    normalize_alert_rule_frame,
)
from utils.workload_audit import build_workload_recovery_audit_ddl  # noqa: E402
from utils.mart import (  # noqa: E402
    build_mart_account_health_change_sql,
    build_mart_account_health_cost_drivers_sql,
    build_mart_account_health_credits_sql,
    build_mart_account_health_failure_count_sql,
    build_mart_account_health_failure_types_sql,
    build_mart_account_health_long_queries_sql,
    build_mart_account_health_queued_sql,
    build_mart_account_health_storage_sql,
    build_mart_account_health_top_driver_sql,
    build_mart_account_health_ytd_credits_sql,
    build_mart_adoption_users_db_sql,
    build_mart_adoption_role_type_sql,
    build_mart_chargeback_sql,
    build_mart_cost_cockpit_sql,
    build_mart_cost_explorer_sql,
    build_mart_cost_run_rate_sql,
    build_mart_control_room_failed_logins_sql,
    build_mart_control_room_cost_drivers_sql,
    build_mart_control_room_summary_sql,
    build_mart_control_room_task_failures_sql,
    build_mart_procedure_calls_sql,
    build_mart_procedure_inventory_sql,
    build_mart_procedure_sla_sql,
    build_mart_usage_cost_drivers_sql,
    build_mart_usage_metering_sql,
    build_mart_warehouse_overview_sql,
    build_mart_pipeline_load_failures_sql,
    build_mart_query_bottleneck_sql,
    build_mart_query_degradation_sql,
    build_mart_recommendation_failed_tasks_sql,
    build_mart_recommendation_idle_sql,
    build_mart_recommendation_query_errors_sql,
    build_mart_recommendation_spill_sql,
    build_mart_storage_trend_sql,
    build_mart_task_critical_path_sql,
)


def _python_sources():
    return [
        path
        for path in APP_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


class FormulaRegressionTests(unittest.TestCase):
    def test_evidence_mode_contract_preserves_legacy_exception_state(self):
        self.assertEqual(
            TRIAGE_MODE_OPTIONS,
            (TRIAGE_MODE_TRIAGE, TRIAGE_MODE_INVESTIGATE, TRIAGE_MODE_ALL_EVIDENCE),
        )
        self.assertEqual(normalize_evidence_mode("Exceptions only"), TRIAGE_MODE_TRIAGE)
        self.assertEqual(normalize_evidence_mode("All evidence"), TRIAGE_MODE_ALL_EVIDENCE)
        self.assertEqual(evidence_mode_from_exceptions(True), TRIAGE_MODE_TRIAGE)
        self.assertEqual(evidence_mode_from_exceptions(False), TRIAGE_MODE_INVESTIGATE)
        self.assertTrue(exceptions_enabled_from_evidence_mode(TRIAGE_MODE_TRIAGE))
        self.assertFalse(exceptions_enabled_from_evidence_mode(TRIAGE_MODE_INVESTIGATE))
        self.assertTrue(evidence_mode_is_investigation({"triage_view_mode": TRIAGE_MODE_INVESTIGATE}))
        self.assertTrue(evidence_mode_is_investigation({"triage_view_mode": TRIAGE_MODE_ALL_EVIDENCE}))
        self.assertTrue(evidence_mode_is_all_evidence({"triage_view_mode": TRIAGE_MODE_ALL_EVIDENCE}))
        self.assertEqual(current_evidence_mode({"triage_view_mode": "bad saved value"}), TRIAGE_MODE_TRIAGE)

    def test_streamlit_and_mart_credit_defaults_stay_aligned(self):
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")

        self.assertEqual(DEFAULTS["credit_price"], 3.68)
        self.assertEqual(DEFAULTS["ai_credit_price"], 2.20)
        self.assertEqual(DEFAULTS["storage_cost_per_tb"], 23.00)
        self.assertIn("('CREDIT_PRICE_USD', '3.68'", setup_sql)
        self.assertIn("('AI_CREDIT_PRICE_USD', '2.20'", setup_sql)
        self.assertIn("('STORAGE_COST_PER_TB_USD', '23.00'", setup_sql)
        self.assertIn("credit_price := COALESCE(credit_price, 3.68)", setup_sql)
        self.assertIn("storage_cost_per_tb := COALESCE(storage_cost_per_tb, 23.00)", setup_sql)
        self.assertIn("ai_credit_price := COALESCE(ai_credit_price, 2.20)", setup_sql)
        daily_block = setup_sql.split("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_LOAD_DAILY()", 1)[1].split(
            "CREATE OR REPLACE PROCEDURE SP_OVERWATCH_LOAD_CORTEX()", 1
        )[0]
        self.assertIn("storage_cost_per_tb NUMBER(18,4) DEFAULT 23.00", daily_block)
        self.assertIn("SELECT TRY_TO_NUMBER(SETTING_VALUE) INTO :storage_cost_per_tb", daily_block)
        self.assertIn("WHERE SETTING_NAME = 'STORAGE_COST_PER_TB_USD'", daily_block)
        self.assertIn("storage_cost_per_tb := COALESCE(storage_cost_per_tb, 23.00)", daily_block)
        self.assertIn("AS STAGE_STORAGE_BYTES", daily_block)
        self.assertIn("COALESCE(s.STAGE_STORAGE_BYTES, 0) AS STAGE_BYTES", daily_block)
        self.assertIn("ALTER TABLE IF EXISTS FACT_STORAGE_DAILY ADD COLUMN IF NOT EXISTS STAGE_BYTES NUMBER;", setup_sql)
        self.assertNotIn("ADD COLUMN IF NOT EXISTS STAGE_BYTES NUMBER DEFAULT 0", setup_sql)
        self.assertEqual(credits_to_dollars(10, DEFAULTS["credit_price"]), 36.8)
        stale_fallbacks = []
        pattern = re.compile(r"session_state\.get\(\s*['\"]credit_price['\"]\s*,\s*3\.0+")
        for path in _python_sources():
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                stale_fallbacks.append(str(path.relative_to(ROOT)))
        self.assertEqual(stale_fallbacks, [])

    def test_executive_snapshot_scope_contract_and_pptx_removal(self):
        self.assertTrue(_snapshot_matches_scope({"meta": {"company": "Trexis", "environment": "DEV_ALL", "days": 30}}, "Trexis", "DEV_ALL", 30))
        self.assertFalse(_snapshot_matches_scope({"meta": {"company": "Trexis", "environment": "PROD", "days": 30}}, "Trexis", "DEV_ALL", 30))
        text = (APP_ROOT / "sections" / "executive_landing.py").read_text(encoding="utf-8")
        self.assertNotIn("_build_executive_snapshot_pptx", text)
        self.assertNotIn("Download PowerPoint", text)
        self.assertNotIn("PowerPoint support data", text)

    def test_executive_platform_operating_score_is_capped_by_evidence(self):
        source_health = pd.DataFrame([
            {"SOURCE": "Cost cockpit", "STATE": "Loaded"},
            {"SOURCE": "Alert evidence", "STATE": "Limited"},
            {"SOURCE": "Action queue", "STATE": "Loaded"},
            {"SOURCE": "Migration ledger", "STATE": "Loaded"},
        ])
        scorecard = _build_platform_operating_score(
            {
                "current_credits": 112.0,
                "prior_credits": 100.0,
                "cost_delta": 12.0,
                "critical_high_alerts": 1,
                "open_actions": 4,
                "high_actions": 1,
                "migration_blockers": 1,
                "top_cost_driver": "WH_TRXS_QUERY",
            },
            source_health,
        )
        drivers = scorecard["platform_score_drivers"]
        by_driver = {row["DRIVER"]: row for _, row in drivers.iterrows()}

        self.assertEqual(scorecard["score"], 61)
        self.assertEqual(scorecard["score_cap"], 74)
        self.assertIn("monitoring coverage blocker", scorecard["cap_reason"])
        self.assertEqual(scorecard["state"], "Executive Escalation")
        self.assertEqual(by_driver["Monitoring Coverage"]["SCORE_CAP"], 74)
        self.assertEqual(by_driver["Telemetry Coverage"]["SCORE_CAP"], 82)
        self.assertLess(by_driver["Reliability / Alerts"]["SCORE_IMPACT"], 0)

    def test_executive_observability_first_paint_uses_compact_mart(self):
        sql = _build_executive_observability_sql(
            "ALFA",
            "PROD",
            30,
            credit_price=3.68,
            ai_credit_price=2.20,
        ).upper()

        self.assertIn("MART_EXECUTIVE_OBSERVABILITY", sql)
        self.assertIn("WINDOW_DAYS = 30", sql)
        self.assertIn("ROW_NUMBER() OVER", sql)
        self.assertIn("UPPER(COMPANY) IN ('ALFA', 'ALL')", sql)
        self.assertNotIn("FACT_QUERY_HOURLY", sql)
        self.assertNotIn("FACT_COST_DAILY", sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", sql)

    def test_executive_observability_fallback_and_mart_include_metric_wall_panels(self):
        parts = _build_executive_observability_query_parts(
            "ALFA",
            "PROD",
            30,
            credit_price=3.68,
            ai_credit_price=2.20,
        )
        combined = "\n".join(sql for _, _, sql in parts).upper()
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()

        for panel in ["COST_DRIVER", "QUERY_DATABASE", "EXEC_STATUS"]:
            self.assertIn(panel, combined)
            self.assertIn(panel, setup_sql)

        self.assertIn("FACT_QUERY_DETAIL_RECENT", combined)
        self.assertIn("FACT_QUERY_DETAIL_RECENT", setup_sql)
        self.assertIn("FACT_COST_DAILY", combined)
        self.assertIn("FACT_QUERY_HOURLY", combined)

    def test_executive_pressure_index_uses_loaded_mart_kpis(self):
        board = pd.DataFrame([
            {"PANEL": "KPI", "METRIC": "Platform Health", "VALUE": 68, "VALUE_USD": 0},
            {"PANEL": "KPI", "METRIC": "Credits Used", "VALUE": 1200, "VALUE_USD": 4416},
            {"PANEL": "KPI", "METRIC": "Spend Delta", "VALUE": 200, "VALUE_USD": 736},
            {"PANEL": "KPI", "METRIC": "Cortex Spend", "VALUE": 30, "VALUE_USD": 66},
            {"PANEL": "KPI", "METRIC": "Queue Time", "VALUE": 900, "VALUE_USD": 0},
            {"PANEL": "KPI", "METRIC": "Remote Spill", "VALUE": 150, "VALUE_USD": 0},
            {"PANEL": "KPI", "METRIC": "Failed Queries", "VALUE": 3, "VALUE_USD": 0},
            {"PANEL": "KPI", "METRIC": "Failed Tasks", "VALUE": 2, "VALUE_USD": 0},
            {"PANEL": "KPI", "METRIC": "Critical High Alerts", "VALUE": 4, "VALUE_USD": 0},
            {"PANEL": "KPI", "METRIC": "Open Actions", "VALUE": 7, "VALUE_USD": 0},
            {"PANEL": "KPI", "METRIC": "Storage", "VALUE": 8, "VALUE_USD": 184},
        ])

        pressure = _executive_pressure_rows(board)
        lanes = set(pressure["LANE"])

        self.assertIn("Cost movement", lanes)
        self.assertIn("Spillage", lanes)
        self.assertIn("Alerts and actions", lanes)
        self.assertIn("OWNER_ROUTE", pressure.columns)
        self.assertGreater(float(pressure.iloc[0]["PRESSURE_SCORE"]), 0)
        self.assertLessEqual(float(pressure["PRESSURE_SCORE"].max()), 100)

    def test_executive_summary_includes_loaded_advisor_surfaces(self):
        board = pd.DataFrame([
            {"PANEL": "KPI", "METRIC": "Platform Health", "VALUE": 91, "VALUE_USD": 0},
            {"PANEL": "KPI", "METRIC": "Credits Used", "VALUE": 500, "VALUE_USD": 1840},
            {"PANEL": "KPI", "METRIC": "Spend Delta", "VALUE": 20, "VALUE_USD": 73.6},
            {"PANEL": "KPI", "METRIC": "Critical High Alerts", "VALUE": 0, "VALUE_USD": 0},
            {"PANEL": "KPI", "METRIC": "Open Actions", "VALUE": 1, "VALUE_USD": 0},
        ])
        advisor_state = {
            "cost_contract_cost_advisor_board": pd.DataFrame([
                {
                    "SEVERITY": "High",
                    "CATEGORY": "Warehouse pressure",
                    "ENTITY": "LOAD_WH",
                    "EST_MONTHLY_SAVINGS_USD": 250.0,
                    "EST_MONTHLY_IMPACT_USD": 1200.0,
                }
            ]),
            "rec_recommendations": [
                {
                    "Severity": "Medium",
                    "Category": "Query Optimization",
                    "Entity": "HASH_123",
                    "Estimated Monthly Savings": 75.0,
                }
            ],
            "opt_df_idle": pd.DataFrame([
                {"WAREHOUSE_NAME": "IDLE_WH", "IDLE_CREDITS": 14.0}
            ]),
            "opt_df_sz": pd.DataFrame([
                {"WAREHOUSE_NAME": "SPILL_WH", "REMOTE_SPILL_GB": 25.0, "AVG_QUEUE_SEC": 900.0, "TOTAL_CREDITS": 30.0}
            ]),
            "sp_sla_exceptions": pd.DataFrame([
                {"SEVERITY": "High", "PROCEDURE_NAME": "LOAD_PROC"}
            ]),
            "spt_df_sp_tracker": pd.DataFrame([
                {"PROCEDURE_NAME": "LOAD_PROC", "OPTIMIZATION_SCORE": 80, "EST_COST": 35.0, "TOTAL_ELAPSED_SEC": 7200.0}
            ]),
        }

        advisor_rows = _executive_loaded_advisor_rows(advisor_state)
        lanes = set(advisor_rows["LANE"])
        self.assertIn("Cost Advisor", lanes)
        self.assertIn("Recommendation Feed", lanes)
        self.assertIn("Warehouse Optimization", lanes)
        self.assertIn("Stored Procedure Advisor", lanes)

        summary = _summary_from_observability(board, credit_price=3.68, state=advisor_state)
        self.assertIsNotNone(summary)
        self.assertGreater(summary["advisor_findings"], 0)
        self.assertGreater(summary["advisor_high_findings"], 0)
        self.assertGreater(summary["advisor_estimated_monthly_savings_usd"], 0)

        priority = _executive_priority_rows(board, days=7, advisor_rows=advisor_rows)
        self.assertIn("Cost Advisor", set(priority["LANE"]))
        pressure = _executive_pressure_rows(board, advisor_rows=advisor_rows)
        self.assertIn("Advisor backlog", set(pressure["LANE"]))

    def test_executive_command_summary_includes_procedure_and_warehouse_controls(self):
        advisor_state = {
            "rec_warehouse_control_plan": pd.DataFrame([
                {
                    "PRIORITY": "High",
                    "WAREHOUSE_NAME": "LOAD_WH",
                    "ACTION_TYPE": "Auto-suspend review",
                    "CURRENT_STATE": "Blocked",
                    "SAFE_SETTING_MOVE": "Review AUTO_SUSPEND before changing settings.",
                    "REVIEW_SQL": "SHOW WAREHOUSES LIKE 'LOAD_WH';",
                }
            ]),
            "rec_warehouse_advisor_recommendations": pd.DataFrame([
                {
                    "PRIORITY": "High",
                    "WAREHOUSE_NAME": "LOAD_WH",
                    "ADVISOR_TYPE": "Auto-suspend savings",
                    "EST_MONTHLY_SAVINGS_USD": 250.0,
                }
            ]),
            "sp_analysis_board": pd.DataFrame([
                {
                    "SEVERITY": "High",
                    "PROCEDURE_NAME": "SP_LOAD_POLICY",
                    "RECOMMENDATION": "Review runtime spike.",
                }
            ]),
        }
        advisor_rows = _executive_loaded_advisor_rows(advisor_state)
        command = _executive_command_summary_rows(pd.DataFrame(), advisor_rows, days=7)
        by_area = {row["AREA"]: row for _, row in command.iterrows()}

        self.assertIn("Warehouse advisor", by_area)
        self.assertIn("Stored procedure advisor", by_area)
        self.assertIn("advisor recommendation", by_area["Warehouse advisor"]["CURRENT_SIGNAL"])
        self.assertIn("analysis signal", by_area["Stored procedure advisor"]["CURRENT_SIGNAL"])
        self.assertEqual(by_area["Warehouse advisor"]["ROUTE"], "Cost & Contract")

    def test_command_center_summary_sort_handles_tiny_integer_counts(self):
        findings = pd.DataFrame({
            "INVESTIGATION_TYPE": ["Cost Spike", "Failure / SLA"],
            "QUESTION_TEXT": ["Why did costs spike?", "Why did this fail?"],
            "FINDING_COUNT": pd.Series([2, 1], dtype="int8"),
            "HIGH_RISK_COUNT": pd.Series([1, 0], dtype="int8"),
            "OWNER_GAP_COUNT": pd.Series([0, 1], dtype="int8"),
            "EXPECTED_VALUE_USD": [250.0, 10.0],
            "TOP_ROOT_CAUSE_CANDIDATE": ["Warehouse pressure", "Task failure"],
            "TOP_EVIDENCE_SUMMARY": ["Spend rose after change.", "Task failed recently."],
            "TOP_RECOMMENDED_ACTION": ["Review warehouse.", "Review task."],
            "CONFIDENCE": ["estimated", "fallback"],
            "RISK_LEVEL": ["High", "Medium"],
            "LAST_REFRESHED_TS": ["2026-06-22 12:00:00", "2026-06-22 12:00:00"],
        })

        with (
            patch("sections.executive_landing.st.markdown"),
            patch("sections.executive_landing.st.caption"),
            patch("sections.executive_landing.st.dataframe") as dataframe,
            patch("sections.executive_landing.render_shell_snapshot"),
        ):
            _render_command_center_summary(findings)

        display_frame = dataframe.call_args.args[0]
        self.assertNotIn("_SORT_VALUE", display_frame.columns)
        self.assertIn("HIGH_RISK_COUNT", display_frame.columns)

    def test_priority_tables_add_cost_companions_for_credit_metrics(self):
        from utils.workflows import add_cost_companion_columns

        frame = pd.DataFrame({
            "WAREHOUSE_NAME": ["WH_TRXS_LOAD"],
            "CREDITS_USED": [10],
            "CREDIT_PRICE": [3.68],
            "TOTAL_COST_USD": [36.80],
            "QUEUE_SEC_PER_CREDIT": [12.5],
            "CREDIT_ALLOCATION_METHOD": ["exact metering"],
        })
        with patch("utils.workflows.get_credit_price", return_value=3.68):
            enriched = add_cost_companion_columns(frame)

        self.assertIn("CREDITS_USED_COST_USD", enriched.columns)
        self.assertAlmostEqual(float(enriched["CREDITS_USED_COST_USD"].iloc[0]), 36.80)
        self.assertNotIn("CREDIT_PRICE_COST_USD", enriched.columns)
        self.assertNotIn("TOTAL_COST_USD_COST_USD", enriched.columns)
        self.assertNotIn("QUEUE_SEC_PER_CREDIT_COST_USD", enriched.columns)
        self.assertNotIn("CREDIT_ALLOCATION_METHOD_COST_USD", enriched.columns)

        mixed_rates = pd.DataFrame({
            "CREDIT_TYPE": ["Snowflake credits", "Cortex AI credits"],
            "RATE_USD": [3.68, 2.20],
            "MONTHLY_LIMIT_CREDITS": [10.0, 10.0],
        })
        enriched_mixed = add_cost_companion_columns(mixed_rates)
        self.assertAlmostEqual(float(enriched_mixed["MONTHLY_LIMIT_CREDITS_COST_USD"].iloc[0]), 36.80)
        self.assertAlmostEqual(float(enriched_mixed["MONTHLY_LIMIT_CREDITS_COST_USD"].iloc[1]), 22.00)

    def test_priority_tables_use_operator_status_labels_for_display_only(self):
        from utils.workflows import apply_operator_status_labels

        raw = pd.DataFrame({
            "SURFACE": ["Source health", "Action closure", "Control review"],
            "STATE": ["Not Loaded", "Refresh Needed", "Loaded"],
            "VERIFICATION_STATUS": ["Pending", "Verified", ""],
            "OWNER_APPROVAL_STATUS": ["Pending", "", "Approved"],
            "RECOVERY_AUDIT_STATE": [
                "Checklist Verification Pending",
                "Closed",
                "Architecture Review Pending",
            ],
        })
        display = apply_operator_status_labels(raw)

        self.assertEqual(display.loc[0, "STATE"], "Load on demand")
        self.assertEqual(display.loc[1, "STATE"], "Refresh available")
        self.assertEqual(display.loc[0, "VERIFICATION_STATUS"], "Awaiting telemetry")
        self.assertEqual(display.loc[0, "OWNER_APPROVAL_STATUS"], "Awaiting review")
        self.assertEqual(display.loc[0, "RECOVERY_AUDIT_STATE"], "Checklist Telemetry Pending")
        self.assertEqual(display.loc[2, "RECOVERY_AUDIT_STATE"], "Monitoring Review Needed")
        self.assertEqual(raw.loc[0, "STATE"], "Not Loaded")
        self.assertEqual(raw.loc[0, "VERIFICATION_STATUS"], "Pending")

    def test_cost_contract_service_lens_sql_is_bounded(self):
        service_sql = build_snowflake_service_cost_lens_sql(
            14,
            credit_price=DEFAULTS["credit_price"],
            ai_credit_price=DEFAULTS["ai_credit_price"],
        ).upper()
        trend_sql = _build_cost_monitor_service_trend_sql(
            14,
            credit_price=DEFAULTS["credit_price"],
            ai_credit_price=DEFAULTS["ai_credit_price"],
        ).upper()
        mart_sql = build_mart_cost_service_lens_sql(
            14,
            credit_price=DEFAULTS["credit_price"],
            ai_credit_price=DEFAULTS["ai_credit_price"],
        ).upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY", service_sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY", service_sql)
        self.assertIn("SERVICE_CATEGORY", service_sql)
        self.assertIn("AI / CORTEX", service_sql)
        self.assertNotIn("ILIKE '%AI%'", service_sql)
        self.assertIn("SERVERLESS / MANAGED COMPUTE", service_sql)
        self.assertIn("SUM(COALESCE(CREDITS_USED, 0)) AS TOTAL_CREDITS", service_sql)
        self.assertIn("SUM(COALESCE(CREDITS_USED_COMPUTE, 0)) AS COMPUTE_CREDITS", service_sql)
        self.assertIn("SUM(COALESCE(CREDITS_USED_CLOUD_SERVICES, 0)) AS CLOUD_SERVICES_CREDITS", service_sql)
        self.assertIn("'OPENFLOW_COMPUTE_SNOWFLAKE'", service_sql)
        self.assertIn("CREDITS_BILLED", service_sql)
        self.assertIn("CREDITS_BILLED_PRIOR", service_sql)
        self.assertIn("CREDIT_DELTA", service_sql)
        self.assertIn("PCT_DELTA", service_sql)
        self.assertIn("COST_DELTA_USD", service_sql)
        self.assertIn("MAX(RATE_USD) AS RATE_USD", service_sql)
        self.assertIn("THEN 2.2000", service_sql)
        self.assertIn("ELSE 3.6800", service_sql)
        self.assertIn("TOTAL_CREDITS * RATE_USD", service_sql)
        self.assertIn("START_TIME >= DATEADD('DAY', -28, DATEADD('HOUR', -24, CURRENT_TIMESTAMP()))", service_sql)
        self.assertIn("START_TIME < DATEADD('HOUR', -24, CURRENT_TIMESTAMP())", service_sql)
        self.assertIn("WHEN DATE(START_TIME) > DATEADD('DAY', -14, DATEADD('HOUR', -24, CURRENT_TIMESTAMP()))", service_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY", trend_sql)
        self.assertIn("SUM(COALESCE(CREDITS_USED, 0)) AS TOTAL_CREDITS", trend_sql)
        self.assertIn("DAILY_SPEND_USD", trend_sql)
        self.assertIn("TOTAL_CREDITS * RATE_USD", trend_sql)
        self.assertIn("THEN 2.2000", trend_sql)
        self.assertIn("WHERE PERIOD = 'CURRENT'", trend_sql)
        self.assertIn("START_TIME < DATEADD('HOUR', -24, CURRENT_TIMESTAMP())", trend_sql)

        self.assertIn("FACT_COST_DAILY", mart_sql)
        self.assertIn("SERVICE_CATEGORY", mart_sql)
        self.assertIn("CREDITS_BILLED", mart_sql)
        self.assertIn("CREDITS_BILLED_PRIOR", mart_sql)
        self.assertIn("CREDIT_DELTA", mart_sql)
        self.assertIn("PCT_DELTA", mart_sql)
        self.assertIn("COST_DELTA_USD", mart_sql)
        self.assertIn("MAX(RATE_USD) AS RATE_USD", mart_sql)
        self.assertIn("THEN 2.2000", mart_sql)
        self.assertIn("ELSE 3.6800", mart_sql)
        self.assertIn("USAGE_DATE >= DATEADD('DAY', -28", mart_sql)
        self.assertIn("WHEN USAGE_DATE >= DATEADD('DAY', -14", mart_sql)
        self.assertIn("FAST COST SUMMARY", mart_sql)

    def test_cost_formula_audit_tracks_source_dashboard_parity(self):
        audit = build_cost_formula_audit()

        self.assertTrue({
            "METRIC",
            "SOURCE_DASHBOARD_FORMULA",
            "FORMULA",
            "CONFIDENCE",
            "PARITY_STATUS",
            "NOTES",
            "NEXT_REVIEW",
        }.issubset(set(audit.columns)))

        by_metric = audit.set_index("METRIC")
        self.assertEqual(by_metric.loc["Monthly service costs", "PARITY_STATUS"], "Aligned")
        self.assertIn("METERING_HISTORY", by_metric.loc["Monthly service costs", "SOURCE_DASHBOARD_FORMULA"])
        self.assertEqual(by_metric.loc["Forecast run rate", "PARITY_STATUS"], "Aligned with extension")
        self.assertIn("WAREHOUSE_METERING_HISTORY", by_metric.loc["Forecast run rate", "FORMULA"])
        self.assertEqual(by_metric.loc["Storage dollars", "PARITY_STATUS"], "Aligned")
        self.assertIn("hybrid", by_metric.loc["Storage dollars", "SOURCE_DASHBOARD_FORMULA"].lower())
        self.assertEqual(by_metric.loc["Cortex detailed sources", "PARITY_STATUS"], "Coverage expanded")
        self.assertIn("REST API", by_metric.loc["Cortex detailed sources", "SOURCE_DASHBOARD_FORMULA"])

    def test_annual_service_projection_uses_account_metering_history(self):
        sql = _annual_service_projection_sql().upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY", sql)
        self.assertIn("DATE_TRUNC('YEAR', CURRENT_DATE())", sql)
        self.assertIn("DATEADD('HOUR', -24, CURRENT_TIMESTAMP())", sql)
        self.assertIn("COUNT(DISTINCT SERVICE_TYPE)", sql)

        metrics = _annual_service_projection_metrics(
            pd.DataFrame({
                "USAGE_DATE": ["2026-06-15", "2026-06-16"],
                "DAILY_CREDITS": [10.0, 20.0],
            }),
            30,
        )

        self.assertEqual(metrics["YTD_ACTUAL_CREDITS"], 30.0)
        self.assertEqual(metrics["RECENT_DAILY_AVG_CREDITS"], 15.0)
        self.assertGreater(metrics["PROJECTED_YEAR_CREDITS"], 30.0)
        self.assertEqual(metrics["LATEST_USAGE_DATE"], "2026-06-16")

    def test_snowflake_admin_reconciliation_bridge_uses_official_account_sources(self):
        sql = _snowflake_admin_reconciliation_sql(30).upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY", sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("SNOWFLAKE ADMIN ACCOUNT TOTAL", sql)
        self.assertIn("OFFICIAL WAREHOUSE COMPUTE TOTAL", sql)
        self.assertIn("ACCOUNT SERVICE / OTHER CREDITS", sql)
        self.assertIn("METERING_HISTORY MINUS WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("DATEADD('HOUR', -24, CURRENT_TIMESTAMP())", sql)

    def test_metered_credit_cte_uses_compute_credits_with_total_fallback(self):
        sql = build_metered_credit_cte(hours_back=24, include_recent=True).upper()
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("COALESCE(CREDITS_USED_COMPUTE, CREDITS_USED)", sql)
        self.assertIn("AS HOURLY_COMPUTE_CREDITS", sql)
        self.assertNotIn("SUM(CREDITS_USED)               AS HOURLY_COMPUTE_CREDITS", sql)

    def test_metered_credit_cte_can_prefer_official_query_attribution(self):
        sql = build_metered_credit_cte(
            hours_back=24,
            include_recent=False,
            prefer_query_attribution=True,
        ).upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY", sql)
        self.assertIn("CREDITS_ATTRIBUTED_COMPUTE", sql)
        self.assertIn("CREDITS_USED_QUERY_ACCELERATION", sql)
        self.assertIn("OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS", sql)
        self.assertIn("ALLOCATED_METERED_CREDITS", sql)
        self.assertIn("QUERY_ATTRIBUTION_HISTORY", sql)
        self.assertIn("OVERWATCH_ALLOCATED", sql)

    def test_cost_reconciliation_exposes_attribution_source_columns(self):
        sql = build_cost_reconciliation_sql(30, prefer_query_attribution=True).upper()

        self.assertIn("QUERY_ATTRIBUTION_HISTORY", sql)
        self.assertIn("ATTRIBUTION_SOURCE", sql)
        self.assertIn("OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS", sql)
        self.assertIn("OVERWATCH_ALLOCATED_CREDITS", sql)
        self.assertIn("OFFICIAL_ATTRIBUTED_QUERIES", sql)

    def test_cost_efficiency_builders_use_bounded_account_usage_sources(self):
        summary_sql = build_cost_efficiency_summary_sql(14, company="ALFA", credit_price=3.68).upper()
        warehouse_sql = build_warehouse_efficiency_sql(14, company="ALFA", credit_price=3.68).upper()
        clustering_sql = build_clustering_cost_sql(14, company="ALFA", credit_price=3.68).upper()

        self.assertIn("COST_PER_QUERY_USD", summary_sql)
        self.assertIn("COST_PER_TB_USD", summary_sql)
        self.assertIn("FAILED_QUERY_WASTE_USD", summary_sql)
        self.assertIn("QUERY_ATTRIBUTION_HISTORY", summary_sql)
        self.assertIn("START_TIME < DATEADD('HOUR', -24, CURRENT_TIMESTAMP())", summary_sql)
        self.assertIn("CREDITS_PER_EXEC_HOUR", warehouse_sql)
        self.assertIn("QUEUE_SECONDS", warehouse_sql)
        self.assertIn("REMOTE_SPILL_GB", warehouse_sql)
        self.assertIn("FAILED_QUERY_WASTE_USD", warehouse_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY", clustering_sql)
        self.assertIn("COST_PER_TB_RECLUSTERED", clustering_sql)
        self.assertIn("NUM_BYTES_RECLUSTERED", clustering_sql)

    def test_cost_contract_source_health_and_gap_summaries(self):
        cockpit = pd.DataFrame([{"CURRENT_CREDITS": 12.0, "PRIOR_CREDITS": 9.0}])
        run_rate = pd.DataFrame([{"AVG_DAILY_7D": 1.5, "YOY_7D_PCT": 4.0, "YOY_30D_PCT": 3.0}])
        attribution = pd.DataFrame([
            {
                "WAREHOUSE_NAME": "COMPUTE_WH",
                "EXACT_METERED_CREDITS": 10.0,
                "ALLOCATED_QUERY_CREDITS": 6.0,
                "OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS": 5.5,
                "OFFICIAL_ATTRIBUTED_QUERIES": 12,
                "VARIANCE_CREDITS": 4.0,
            },
            {
                "WAREHOUSE_NAME": "COMPUTE_WH",
                "EXACT_METERED_CREDITS": 2.0,
                "ALLOCATED_QUERY_CREDITS": 1.5,
                "OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS": 1.5,
                "OFFICIAL_ATTRIBUTED_QUERIES": 3,
                "VARIANCE_CREDITS": 0.5,
            },
        ])
        service_lens = pd.DataFrame([
            {
                "SERVICE_CATEGORY": "Warehouse",
                "SERVICE_TYPE": "WAREHOUSE_METERING",
                "CREDITS_BILLED": 10.0,
                "CREDIT_DELTA": 0.5,
            },
            {
                "SERVICE_CATEGORY": "AI / Cortex",
                "SERVICE_TYPE": "CORTEX",
                "CREDITS_BILLED": 2.0,
                "CREDIT_DELTA": 1.5,
            },
            {
                "SERVICE_CATEGORY": "Serverless / Managed Compute",
                "SERVICE_TYPE": "SERVERLESS_TASK",
                "CREDITS_BILLED": 1.0,
                "CREDIT_DELTA": -3.25,
            },
        ])
        state = {"cost_contract_service_lens_source": "Official Cost Monitor: SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY"}

        source_summary, source_board = _build_cost_source_health_board(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=pd.DataFrame(),
            attribution=attribution,
            service_lens=service_lens,
            state=state,
        )
        by_source = dict(zip(source_board["SOURCE"], source_board["STATE"]))
        self.assertEqual(by_source["Warehouse metering"], "Ready")
        self.assertEqual(by_source["Query attribution gap"], "Ready")
        self.assertEqual(by_source["Account service lens"], "Ready")
        self.assertNotIn("Organization rate and currency", by_source)
        self.assertGreaterEqual(source_summary["score"], 90)

        gap = _build_attribution_gap_summary(attribution, DEFAULTS["credit_price"])
        self.assertEqual(gap["official_queries"], 15)
        self.assertAlmostEqual(gap["exact_credits"], 12.0)
        self.assertAlmostEqual(gap["query_credits"], 7.5)
        self.assertEqual(gap["top_gap_warehouse"], "COMPUTE_WH")

        service_summary = _build_service_cost_lens_summary(service_lens)
        self.assertAlmostEqual(service_summary["total_credits"], 13.0)
        self.assertAlmostEqual(service_summary["non_warehouse_credits"], 3.0)
        self.assertAlmostEqual(service_summary["ai_credits"], 2.0)
        self.assertAlmostEqual(service_summary["serverless_credits"], 1.0)
        self.assertEqual(service_summary["top_moving_service"], "SERVERLESS_TASK")
        self.assertAlmostEqual(service_summary["top_moving_delta"], -3.25)

    def test_cost_advisor_board_ranks_telemetry_backed_cost_findings(self):
        efficiency = pd.DataFrame([{
            "FAILED_QUERY_WASTE_USD": 70.0,
            "FAILED_QUERIES": 7,
            "QUERY_COUNT": 400,
            "TB_SCANNED": 12.5,
        }])
        warehouse_efficiency = pd.DataFrame([
            {
                "WAREHOUSE_NAME": "LOW_PRESSURE_WH",
                "COST_USD": 350.0,
                "QUERY_COUNT": 120,
                "QUEUE_SECONDS": 0.0,
                "REMOTE_SPILL_GB": 0.0,
                "FAILED_QUERY_WASTE_USD": 0.0,
                "AVG_CACHE_PCT": 82.0,
            },
            {
                "WAREHOUSE_NAME": "SPILLING_WH",
                "COST_USD": 500.0,
                "QUERY_COUNT": 80,
                "QUEUE_SECONDS": 900.0,
                "REMOTE_SPILL_GB": 25.0,
                "FAILED_QUERY_WASTE_USD": 60.0,
                "AVG_CACHE_PCT": 18.0,
            },
        ])
        clustering = pd.DataFrame([{
            "TABLE_NAME": "ALFA_DB.PUBLIC.FACT_BIG",
            "CLUSTERING_COST_USD": 90.0,
            "TB_RECLUSTERED": 4.5,
        }])
        reconciliation = pd.DataFrame([{
            "WAREHOUSE_NAME": "SPILLING_WH",
            "EXACT_METERED_CREDITS": 500.0,
            "ALLOCATED_QUERY_CREDITS": 450.0,
            "OFFICIAL_ATTRIBUTED_COMPUTE_CREDITS": 440.0,
            "OFFICIAL_ATTRIBUTED_QUERIES": 200,
            "VARIANCE_CREDITS": 50.0,
        }])
        service_lens = pd.DataFrame([{
            "SERVICE_CATEGORY": "Serverless / Managed Compute",
            "SERVICE_TYPE": "SERVERLESS_TASK",
            "CREDITS_BILLED": 100.0,
            "CREDITS_BILLED_PRIOR": 60.0,
            "CREDIT_DELTA": 40.0,
            "ESTIMATED_COST_USD": 368.0,
            "PRIOR_ESTIMATED_COST_USD": 220.8,
            "COST_DELTA_USD": 147.2,
        }])
        storage_tables = pd.DataFrame([{
            "TABLE_CATALOG": "ALFA_DB",
            "TABLE_SCHEMA": "PUBLIC",
            "TABLE_NAME": "FACT_RETENTION",
            "ACTIVE_GB": 80.0,
            "TIME_TRAVEL_GB": 512.0,
            "FAILSAFE_GB": 12.0,
            "CLONE_GB": 0.0,
        }])
        storage_db = pd.DataFrame([{
            "DATABASE_NAME": "ALFA_DB",
            "DATABASE_GB": 1500.0,
            "FAILSAFE_GB": 512.0,
            "EST_COST_USD": 80.0,
        }])

        summary, board = _build_cost_advisor_board(
            efficiency_summary=efficiency,
            warehouse_efficiency=warehouse_efficiency,
            clustering_cost=clustering,
            reconciliation=reconciliation,
            service_lens=service_lens,
            credit_price=DEFAULTS["credit_price"],
            days=7,
            storage_table_metrics=storage_tables,
            storage_db_detail=storage_db,
            storage_cost_per_tb=DEFAULTS["storage_cost_per_tb"],
        )
        categories = set(board["CATEGORY"])
        def advisor_row(category: str, entity: str) -> pd.Series:
            match = board[(board["CATEGORY"].eq(category)) & (board["ENTITY"].eq(entity))]
            self.assertFalse(match.empty, f"Missing advisor row for {category} / {entity}")
            return match.iloc[0]

        self.assertGreaterEqual(summary["findings"], 6)
        self.assertGreater(summary["estimated_monthly_savings"], 0)
        self.assertIn("Failed query waste", categories)
        self.assertIn("Warehouse pressure", categories)
        self.assertIn("Warehouse right-size review", categories)
        self.assertIn("Automatic clustering", categories)
        self.assertIn("Attribution gap", categories)
        self.assertIn("Service spend movement", categories)
        self.assertIn("Storage retention", categories)
        self.assertIn("Storage failsafe", categories)
        self.assertIn("TELEMETRY_SUMMARY", board.columns)
        self.assertIn("VALIDATION_NEEDED", board.columns)
        self.assertIn("ACTION_TYPE", board.columns)
        self.assertIn("WORKFLOW_ROUTE", board.columns)
        self.assertIn("PRIMARY_METRIC", board.columns)
        pressure = advisor_row("Warehouse pressure", "SPILLING_WH")
        right_size = advisor_row("Warehouse right-size review", "LOW_PRESSURE_WH")
        service = advisor_row("Service spend movement", "SERVERLESS_TASK")
        clustering_row = advisor_row("Automatic clustering", "ALFA_DB.PUBLIC.FACT_BIG")
        retention = advisor_row("Storage retention", "ALFA_DB.PUBLIC.FACT_RETENTION")
        failsafe = advisor_row("Storage failsafe", "ALFA_DB")
        self.assertEqual(pressure["PRIORITY"], "High")
        self.assertIn("Do not blindly upsize", pressure["DO_NOT_DO"])
        self.assertIn("Do not downsize", right_size["DO_NOT_DO"])
        self.assertIn("official account metering", service["CONFIDENCE"])
        self.assertGreater(clustering_row["EST_MONTHLY_SAVINGS_USD"], 0)
        self.assertIn("Do not lower retention", retention["DO_NOT_DO"])
        self.assertIn("not directly purgeable", failsafe["DO_NOT_DO"])
        category_summary = _cost_advisor_category_summary(board)
        self.assertFalse(category_summary.empty)
        self.assertIn("HIGH_FINDINGS", category_summary.columns)
        failed_summary = category_summary[category_summary["CATEGORY"].eq("Failed query waste")].iloc[0]
        self.assertGreaterEqual(failed_summary["FINDINGS"], 1)
        self.assertGreater(failed_summary["EST_MONTHLY_SAVINGS_USD"], 0)
        storage_summary = category_summary[category_summary["CATEGORY"].eq("Storage failsafe")].iloc[0]
        self.assertGreater(storage_summary["EST_MONTHLY_IMPACT_USD"], 0)
        action_summary = _cost_advisor_action_summary(board)
        self.assertFalse(action_summary.empty)
        self.assertIn("ACTION_TYPE", action_summary.columns)
        self.assertIn("WORKFLOW_ROUTE", action_summary.columns)
        self.assertIn("Fix failed workload", set(action_summary["ACTION_TYPE"]))
        self.assertIn("Review storage retention", set(action_summary["ACTION_TYPE"]))
        self.assertGreater(action_summary["EST_MONTHLY_IMPACT_USD"].sum(), 0)
        detail_options = _cost_advisor_detail_options(board)
        self.assertFalse(detail_options.empty)
        self.assertIn("DETAIL_LABEL", detail_options.columns)
        self.assertTrue(detail_options["DETAIL_LABEL"].astype(str).str.contains(" | ", regex=False).any())
        self.assertIn("WORKFLOW_ROUTE", detail_options.columns)

    def test_cost_contract_summary_rows_stay_data_first_without_pptx(self):
        splash = {
            "cockpit": pd.DataFrame([{
                "CURRENT_CREDITS": 100.0,
                "PRIOR_CREDITS": 80.0,
                "ACTIVE_WAREHOUSES": 4,
                "TOP_INCREASE_WAREHOUSE": "WH_TRXS_LOAD",
                "TOP_INCREASE_CREDITS": 12.5,
            }]),
            "trend": pd.DataFrame([
                {"USAGE_DATE": "2026-06-01", "DAILY_CREDITS": 10.0, "DAILY_SPEND_USD": 30.0},
                {"USAGE_DATE": "2026-06-02", "DAILY_CREDITS": 20.0, "DAILY_SPEND_USD": 55.0},
            ]),
            "warehouse_delta": pd.DataFrame([{
                "WAREHOUSE_NAME": "WH_TRXS_LOAD",
                "CURRENT_CREDITS": 50.0,
                "PRIOR_CREDITS": 37.5,
                "CREDIT_DELTA": 12.5,
            }]),
            "service_costs": pd.DataFrame([
                {
                    "SERVICE_CATEGORY": "Warehouse",
                    "SERVICE_TYPE": "WAREHOUSE_METERING",
                    "CREDITS_BILLED": 100.0,
                    "CREDITS_BILLED_PRIOR": 80.0,
                    "CREDIT_DELTA": 20.0,
                    "CREDITS_USED_COMPUTE": 90.0,
                    "CREDITS_USED_CLOUD_SERVICES": 10.0,
                    "ESTIMATED_COST_USD": 368.0,
                    "PRIOR_ESTIMATED_COST_USD": 294.4,
                    "COST_DELTA_USD": 73.6,
                },
                {
                    "SERVICE_CATEGORY": "AI / Cortex",
                    "SERVICE_TYPE": "CORTEX",
                    "CREDITS_BILLED": 5.0,
                    "CREDITS_BILLED_PRIOR": 5.0,
                    "CREDIT_DELTA": 0.0,
                    "CREDITS_USED_COMPUTE": 0.0,
                    "CREDITS_USED_CLOUD_SERVICES": 5.0,
                    "ESTIMATED_COST_USD": 11.0,
                    "PRIOR_ESTIMATED_COST_USD": 11.0,
                    "COST_DELTA_USD": 0.0,
                },
            ]),
            "cortex": pd.DataFrame([{
                "CORTEX_SPEND_USD": 42.0,
                "CORTEX_CREDITS": 19.0,
                "CORTEX_REQUESTS": 7,
                "TOP_CORTEX_USER": "SNOW_DTI_ANALYST",
                "TOP_CORTEX_USER_SPEND_USD": 25.0,
            }]),
            "run_rate": pd.DataFrame([{
                "PROJECTED_30D_FROM_7D": 450.0,
                "AVG_DAILY_7D": 15.0,
                "RUN_RATE_STATE": "Rising",
                "YOY_STATE": "YOY baseline ready",
                "YOY_7D_PCT": 8.5,
            }]),
        }
        summary = _cost_splash_summary(splash, DEFAULTS["credit_price"], 7)
        self.assertEqual(summary["cost_basis"], "Official account service total")
        self.assertAlmostEqual(summary["current_credits"], 105.0)
        self.assertAlmostEqual(summary["prior_credits"], 85.0)
        self.assertAlmostEqual(summary["compute_credits"], 90.0)
        self.assertAlmostEqual(summary["cloud_services_credits"], 15.0)
        self.assertAlmostEqual(summary["spend"], 379.0)
        self.assertAlmostEqual(summary["prior_spend"], 305.4)
        self.assertAlmostEqual(summary["spend_delta"], 73.6)
        self.assertEqual(summary["active_services"], 2)

        next_move = _cost_splash_next_move(summary)
        self.assertEqual(next_move[0], "Cost by Warehouse")
        self.assertEqual(next_move[1], "Usage movement")

        cortex_summary = dict(summary, delta_pct=0.0, top_warehouse_delta_spend=0.0)
        cortex_move = _cost_splash_next_move(cortex_summary)
        self.assertEqual(cortex_move[0], "Cost by User / Role")

        value_summary = dict(cortex_summary, cortex_spend=0.0, projected_30d_spend=0.0)
        value_move = _cost_splash_next_move(value_summary)
        self.assertEqual(value_move[0], "Cost Recommendations")

        service_summary = {"top_moving_service": "CORTEX", "top_moving_delta": 4.25}
        service_lens = pd.DataFrame([
            {
                "SERVICE_CATEGORY": "AI / Cortex",
                "SERVICE_TYPE": "CORTEX",
                "CREDITS_BILLED": 5.0,
                "CREDITS_BILLED_PRIOR": 2.0,
                "CREDIT_DELTA": 3.0,
                "ESTIMATED_COST_USD": 11.0,
                "PRIOR_ESTIMATED_COST_USD": 4.4,
                "COST_DELTA_USD": 6.6,
            }
        ])
        action_summary = {"open_actions": 3, "high_actions": 1, "estimated_savings": 250.0}

        movement = _service_lens_movement_rows(service_lens, DEFAULTS["credit_price"])
        trend_rows = _cost_spend_trend_rows(splash["trend"], DEFAULTS["credit_price"])
        ranking_rows = _cost_warehouse_ranking_rows(splash["warehouse_delta"], DEFAULTS["credit_price"])

        self.assertEqual(movement.iloc[0]["SERVICE_TYPE"], "CORTEX")
        self.assertAlmostEqual(float(movement.iloc[0]["COST_DELTA_USD"]), 6.6)
        self.assertIn("SPEND_USD", trend_rows.columns)
        self.assertIn("ROLLING_SPEND_USD", trend_rows.columns)
        self.assertAlmostEqual(float(trend_rows.iloc[1]["SPEND_USD"]), 55.0)
        self.assertIn("CURRENT_SPEND_USD", ranking_rows.columns)
        self.assertIn("DELTA_SPEND_USD", ranking_rows.columns)
        self.assertEqual(ranking_rows.iloc[0]["CURRENT_SPEND_LABEL"], "$184")
        self.assertEqual(ranking_rows.iloc[0]["DELTA_SPEND_LABEL"], "+$46")
        text = (APP_ROOT / "sections" / "cost_contract.py").read_text(encoding="utf-8")
        self.assertNotIn("_build_cost_snapshot_pptx", text)
        self.assertNotIn("Download PowerPoint", text)
        self.assertNotIn("PowerPoint support data", text)

    def test_query_attribution_support_requires_all_generated_sql_columns(self):
        import streamlit as st

        class Result:
            def __init__(self, columns=None):
                self.columns = columns or []

            def to_pandas(self):
                return pd.DataFrame(columns=self.columns)

            def collect(self):
                return []

        class Session:
            def __init__(self, columns):
                self.columns = columns

            def sql(self, _statement):
                return Result(self.columns)

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            clear_compatibility_process_cache()
            self.assertTrue(query_attribution_supported(Session([
                "QUERY_ID",
                "START_TIME",
                "CREDITS_ATTRIBUTED_COMPUTE",
                "CREDITS_USED_QUERY_ACCELERATION",
            ])))

            st.session_state.clear()
            clear_compatibility_process_cache()
            self.assertFalse(query_attribution_supported(Session([
                "QUERY_ID",
                "START_TIME",
                "CREDITS_ATTRIBUTED_COMPUTE",
            ])))
        finally:
            clear_compatibility_process_cache()
            st.session_state.clear()
            st.session_state.update(previous)

    def test_idle_warehouse_sql_uses_compute_credits_not_total_cloud_services(self):
        sql = build_idle_warehouse_sql(days_back=7, min_idle_credits=1.0).upper()

        self.assertIn("WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("COALESCE(CREDITS_USED_COMPUTE, CREDITS_USED)", sql)
        self.assertIn("START_TIME <  DATEADD('HOUR', -24, CURRENT_TIMESTAMP())", sql)

    def test_account_health_live_counts_prefer_information_schema(self):
        sql = _live_query_status_sql("", "", "").upper()
        self.assertIn("INFORMATION_SCHEMA.QUERY_HISTORY", sql)
        self.assertIn("QUEUED_OVERLOAD_TIME", sql)
        self.assertIn("QUEUED_PROVISIONING_TIME", sql)
        self.assertIn("QUEUED_REPAIR_TIME", sql)
        self.assertIn("RESUMING_WAREHOUSE", sql)

    def test_account_health_live_loader_runs_information_schema_before_lagged_fallback(self):
        calls = []

        def fake_run(sql):
            calls.append(sql.upper())
            return pd.DataFrame({
                "ACTIVE_COUNT": [1],
                "QUEUED_COUNT": [0],
                "BLOCKED_COUNT": [0],
            })

        with patch("sections.account_health.run_query_or_raise", side_effect=fake_run):
            df, source = _load_live_query_status("", "", "")

        self.assertEqual(source, "INFORMATION_SCHEMA")
        self.assertEqual(len(calls), 1)
        self.assertIn("INFORMATION_SCHEMA.QUERY_HISTORY", calls[0])
        self.assertEqual(int(df["ACTIVE_COUNT"].iloc[0]), 1)

    def test_account_health_builds_daily_dba_checklist(self):
        checklist = _build_account_health_dba_checklist(
            health_score=68,
            score_label="Degraded",
            err_count=14,
            queued=7,
            pct_delta=45.0,
            last24=120.0,
            stor_tb=4.2,
            failed_tasks=2,
            object_changes=3,
            control_mart_used=False,
            detail_source="Current account evidence",
        )
        by_check = {row["CHECK"]: row for _, row in checklist.iterrows()}

        self.assertEqual(by_check["Overall health escalation"]["OWNER"], "DBA Lead")
        self.assertEqual(by_check["Query failure review"]["SEVERITY"], "High")
        self.assertEqual(by_check["Task and procedure reliability"]["ROUTE"], "Workload Operations")
        self.assertIn("query_id", by_check["Change and drift review"]["PROOF_REQUIRED"])
        self.assertIn("Snapshot timestamp", by_check["Refresh source readiness"]["PROOF_REQUIRED"])

        routed = _annotate_account_health_checklist_readiness(checklist, environment="PROD")
        by_check = {row["CHECK"]: row for _, row in routed.iterrows()}
        self.assertEqual(by_check["Query failure review"]["ENVIRONMENT_SCOPE"], "PROD")
        self.assertEqual(by_check["Query failure review"]["DATABASE_CONTEXT"], "Yes")
        self.assertEqual(by_check["Query failure review"]["SCOPE_CONFIDENCE"], "Database Context")
        self.assertEqual(by_check["Query failure review"]["QUEUE_READINESS"], "Ready to Queue")
        self.assertEqual(by_check["Cost spike review"]["DATABASE_CONTEXT"], "Allocated / Estimated")
        self.assertEqual(by_check["Cost spike review"]["SCOPE_CONFIDENCE"], "Allocated Estimate")
        self.assertIn("allocated/estimated", by_check["Cost spike review"]["SCOPE_EVIDENCE"])

    def test_account_health_action_brief_prioritizes_single_operator_move(self):
        checklist = _build_account_health_dba_checklist(
            health_score=88,
            score_label="Watch",
            err_count=0,
            queued=28,
            pct_delta=4.0,
            last24=42.0,
            stor_tb=4.2,
            failed_tasks=0,
            object_changes=0,
            control_mart_used=True,
            detail_source="Fast summary",
        )
        brief = _account_health_action_brief(checklist)
        self.assertEqual(brief["target"], "Cost & Contract")
        self.assertEqual(brief["state"], "Needs DBA")
        self.assertIn("Queue pressure review", brief["detail"])

        clear = _account_health_action_brief(pd.DataFrame([
            {
                "CHECK": "Healthy",
                "STATUS": "OK",
                "SEVERITY": "Info",
                "EVIDENCE": "No action",
                "ROUTE": "Account Health",
                "NEXT_ACTION": "No action needed.",
            }
        ]))
        self.assertEqual(clear["target"], "Morning Report")
        self.assertEqual(clear["state"], "Clear")

    def test_account_health_checklist_actions_are_queue_ready(self):
        checklist = _build_account_health_dba_checklist(
            health_score=68,
            score_label="Degraded",
            err_count=14,
            queued=7,
            pct_delta=45.0,
            last24=120.0,
            stor_tb=4.2,
            failed_tasks=2,
            object_changes=3,
            control_mart_used=False,
            detail_source="Live fallback: ACCOUNT_USAGE",
        )
        actionable = _account_health_actionable_checklist(checklist)
        by_check = {row["CHECK"]: row for _, row in actionable.iterrows()}
        action = _account_health_checklist_action_payload(
            by_check["Query failure review"],
            company="ALFA",
            environment="DEV_ALL",
        )

        self.assertEqual(action["Category"], "Daily DBA Checklist")
        self.assertEqual(action["Entity"], "Query failure review")
        self.assertEqual(action["Verification Status"], "Requested")
        self.assertEqual(action["Review Group"], "Application Route / DBA On-Call")
        self.assertEqual(action["Oncall Primary"], "DBA Query Triage")
        self.assertIn("MONITORING_CONTEXT", action["Owner Source"])
        self.assertEqual(action["Recovery Audit State"], "Checklist Telemetry Pending")
        self.assertEqual(action["Recovery SLA Target Hours"], 24)
        self.assertEqual(action["Environment"], "DEV_ALL")
        self.assertIn("QUERY_HISTORY", action["Verification Query"])
        self.assertIn("Queue readiness: Ready to Queue", action["Verification Note"])
        self.assertIn("Scope: Database Context", action["Verification Note"])
        self.assertIn("Scope basis", action["Recovery Evidence"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])
        self.assertNotIn("ALTER", action["Generated SQL Fix"].upper())

    def test_account_health_visible_checklist_defaults_to_exceptions(self):
        checklist = pd.DataFrame([
            {
                "CHECK": "Healthy login posture",
                "STATUS": "OK",
                "SEVERITY": "Info",
                "EVIDENCE": "No action",
            },
            {
                "CHECK": "Query failure review",
                "STATUS": "Needs DBA",
                "SEVERITY": "High",
                "EVIDENCE": "14 failed queries",
            },
            {
                "CHECK": "Queue pressure review",
                "STATUS": "Watch",
                "SEVERITY": "Medium",
                "EVIDENCE": "7 queued queries",
            },
        ])

        default_view, title, raw_label = _account_health_visible_checklist(checklist)
        full_view, full_title, full_raw_label = _account_health_visible_checklist(
            checklist,
            show_full=True,
        )

        self.assertEqual(title, "Daily DBA checklist exceptions")
        self.assertEqual(raw_label, "Full daily DBA checklist rows")
        self.assertEqual(set(default_view["CHECK"]), {"Query failure review", "Queue pressure review"})
        self.assertEqual(full_title, "Daily DBA checklist")
        self.assertEqual(full_raw_label, "All daily DBA checklist rows")
        self.assertEqual(len(full_view), 3)

    def test_account_health_checklist_has_owner_and_escalation_context(self):
        checklist = pd.DataFrame([
            {
                "CHECK": "Queue pressure review",
                "STATUS": "Needs DBA",
                "SEVERITY": "Medium",
                "ROUTE": "Warehouse Health",
                "EVIDENCE": "7 queued",
            }
        ])
        enriched = _enrich_account_health_checklist_owners(checklist)
        row = enriched.iloc[0]

        self.assertEqual(row["OWNER"], "Platform DBA")
        self.assertEqual(row["ESCALATION_TARGET"], "Warehouse Route / DBA On-Call")
        self.assertIn("Checklist route map", row["OWNER_SOURCE"])
        self.assertIn("MONITORING_CONTEXT", row["OWNER_SOURCE"])
        self.assertEqual(row["ONCALL_PRIMARY"], "Platform DBA")
        self.assertEqual(row["OWNER_EVIDENCE"], "Derived from the loaded telemetry row.")

    def test_account_health_checklist_history_sql_is_persistable_and_scoped(self):
        checklist = _build_account_health_dba_checklist(
            health_score=68,
            score_label="Degraded",
            err_count=14,
            queued=7,
            pct_delta=45.0,
            last24=120.0,
            stor_tb=4.2,
            failed_tasks=2,
            object_changes=3,
            control_mart_used=False,
            detail_source="Live fallback: ACCOUNT_USAGE",
        )
        ddl = build_account_health_checklist_history_ddl().upper()
        insert_sql = _account_health_checklist_history_insert_sql(
            checklist,
            company="ALFA",
            environment="DEV_ALL",
            health_score=68,
            detail_source="Live fallback: ACCOUNT_USAGE",
            snapshot_id="SNAP1",
        ).upper()
        trend_sql = _account_health_checklist_history_sql(30, "ALFA", "DEV_ALL").upper()

        self.assertIn("CREATE TABLE IF NOT EXISTS", ddl)
        self.assertIn("OVERWATCH_DBA_CHECKLIST_HISTORY", ddl)
        self.assertIn("ESCALATION_TARGET", ddl)
        self.assertIn("INSERT INTO", insert_sql)
        self.assertIn("'SNAP1'", insert_sql)
        self.assertIn("ACTIONABLE", insert_sql)
        self.assertIn("MAX_BY(STATUS", trend_sql)
        self.assertIn("COMPANY = 'ALFA'", trend_sql)
        self.assertIn("ENVIRONMENT = 'DEV_ALL'", trend_sql)
        self.assertIn("QUEUE_READINESS", insert_sql)
        self.assertIn("VERIFICATION_QUERY", insert_sql)
        self.assertIn("CONTROL_READINESS", insert_sql)
        self.assertIn("CONTROL_BLOCKER_SNAPSHOTS", trend_sql)
        self.assertIn("NEXT_CONTROL_ACTION", trend_sql)

    def test_account_health_checklist_history_schema_has_control_board_fields(self):
        ddl = build_account_health_checklist_history_ddl().upper()
        migrations = "\n".join(build_account_health_checklist_history_migration_sql()).upper()

        for column in [
            "ENVIRONMENT_SCOPE",
            "DATABASE_CONTEXT",
            "SCOPE_CONFIDENCE",
            "APPROVAL_REQUIRED",
            "QUEUE_READINESS",
            "QUEUE_BLOCKERS",
            "VERIFICATION_QUERY",
            "RECOVERY_SLA_TARGET_HOURS",
            "CONTROL_READINESS",
            "CONTROL_BLOCKERS",
            "NEXT_CONTROL_ACTION",
        ]:
            self.assertIn(column, ddl)
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", migrations)

    def test_account_health_control_board_prioritizes_closure_route_and_hygiene_blocks(self):
        checklist = _build_account_health_dba_checklist(
            health_score=68,
            score_label="Degraded",
            err_count=14,
            queued=7,
            pct_delta=45.0,
            last24=120.0,
            stor_tb=4.2,
            failed_tasks=2,
            object_changes=3,
            control_mart_used=False,
            detail_source="Live fallback: ACCOUNT_USAGE",
        )
        closure = pd.DataFrame(
            {
                "CHECK_NAME": ["Query failure review", "Cost spike review"],
                "CLOSURE_READINESS": ["Overdue closure", "Fixed without verification"],
                "CLOSURE_RANK": [0, 1],
                "OPEN_ACTIONS": [1, 0],
                "OVERDUE_OPEN": [1, 0],
                "FIXED_WITHOUT_VERIFICATION": [0, 1],
                "RECOVERY_RISK_ROWS": [0, 1],
                "VERIFIED_CLOSURES": [0, 0],
                "NEXT_ACTION": ["Escalate query failure owner.", "Attach cost verification."],
            }
        )
        hygiene = pd.DataFrame(
            [
                {
                    "USER_NAME": "ALFA_ADMIN",
                    "SEVERITY": "High",
                    "POSTURE_FINDINGS": "privileged role grant; MFA signal missing",
                    "FAILED_LOGINS": 2,
                    "FAILED_IPS": 1,
                    "ADMIN_ROLE_COUNT": 1,
                    "ADMIN_ROLES": "ACCOUNTADMIN",
                    "MFA_SIGNAL": "false",
                    "DAYS_SINCE_SEEN": 4,
                    "DATABASE_CONTEXT": "No Database Context",
                    "ENVIRONMENT_SCOPE": "No Database Context",
                    "SCOPE_CONFIDENCE": "Account-Level Control",
                    "SCOPE_EVIDENCE": "USERS and LOGIN_HISTORY do not expose database context.",
                    "NEXT_ACTION": "Confirm IAM owner and admin-role business need.",
                    "PROOF_REQUIRED": "user, IAM ticket, admin-role evidence, owner approval",
                }
            ]
        )

        board = _account_health_control_board(
            checklist,
            closure=closure,
            access_hygiene=hygiene,
            environment="PROD",
        )
        gates = _account_health_operator_next_moves(
            health_score=68,
            checklist=checklist,
            control_board=board,
            closure=closure,
            access_hygiene=_annotate_account_health_access_hygiene(hygiene),
            source_health=pd.DataFrame([{
                "SOURCE": "Daily DBA checklist",
                "STATE": "Stale",
            }]),
        )
        matrix = _account_health_intervention_matrix(
            checklist=checklist,
            control_board=board,
            closure=closure,
            access_hygiene=_annotate_account_health_access_hygiene(hygiene),
        )
        by_check = {row["CHECK_NAME"]: row for _, row in board.iterrows()}
        by_gate = {row["GATE"]: row for _, row in gates.iterrows()}
        by_surface = {row["SURFACE"]: row for _, row in matrix.iterrows()}

        self.assertEqual(by_check["Query failure review"]["CONTROL_STATE"], "Closure Overdue")
        self.assertEqual(by_check["Cost spike review"]["CONTROL_STATE"], "Closure Status Pending")
        self.assertEqual(by_check["Refresh source readiness"]["CONTROL_STATE"], "Queue Required")
        self.assertEqual(by_check["Account access hygiene"]["CONTROL_STATE"], "Access Route Blocked")
        self.assertEqual(by_check["Account access hygiene"]["DATABASE_CONTEXT"], "No")
        self.assertIn("user hygiene", by_check["Account access hygiene"]["NEXT_CONTROL_ACTION"])
        self.assertEqual(by_gate["Closure status"]["STATE"], "Closure Blocked")
        self.assertEqual(by_gate["Checklist route"]["STATE"], "Route Blocked")
        self.assertEqual(by_gate["Access hygiene"]["STATE"], "Access Route Blocked")
        self.assertEqual(by_gate["Source readiness"]["STATE"], "Source Stale")
        self.assertEqual(by_surface["Query failure review"]["INTERVENTION_STATE"], "Closure Block")
        self.assertEqual(by_surface["Query failure review"]["DBA_PRIORITY"], "P0")
        self.assertEqual(by_surface["Refresh source readiness"]["INTERVENTION_STATE"], "Route Block")
        self.assertEqual(by_surface["Refresh source readiness"]["DBA_PRIORITY"], "P1")
        self.assertEqual(by_surface["Account access hygiene"]["SCOPE_CONFIDENCE"], "Account-Level Control")

    def test_account_health_morning_exception_rows_put_closure_and_failures_first(self):
        checklist = pd.DataFrame([
            {
                "CHECK": "Query failure review",
                "STATUS": "Needs DBA",
                "SEVERITY": "High",
                "EVIDENCE": "12 failed queries",
                "ROUTE": "Workload Operations",
                "NEXT_ACTION": "Open query diagnosis.",
            }
        ])
        gates = pd.DataFrame([
            {
                "GATE": "Closure proof",
                "STATE": "Closure Blocked",
                "COUNT": 2,
                "PROOF_REQUIRED": "verification result",
                "NEXT_ACTION": "Escalate overdue closures.",
                "GATE_RANK": 0,
            },
            {
                "GATE": "Source readiness",
                "STATE": "Current",
                "COUNT": 0,
                "PROOF_REQUIRED": "fresh source state",
                "NEXT_ACTION": "Loaded sources are current.",
                "GATE_RANK": 8,
            },
        ])
        interventions = pd.DataFrame([
            {
                "DBA_PRIORITY": "P1",
                "INTERVENTION_STATE": "Route Block",
                "SURFACE": "Refresh source readiness",
                "ROUTE": "Account Health",
                "COUNT": 1,
                "NEXT_DECISION": "Reload source evidence before queueing.",
                "PROOF_REQUIRED": "fresh source state",
            }
        ])

        rows = _account_health_morning_exception_rows(
            checklist=checklist,
            gates=gates,
            interventions=interventions,
            control_board=pd.DataFrame(),
            health_score=92,
            err_count=12,
            queued=3,
            pct_delta=35,
            failed_tasks=1,
        )

        self.assertEqual(rows.iloc[0]["SIGNAL"], "Closure Blocked")
        self.assertIn("Query failures", set(rows["SIGNAL"]))
        self.assertIn("Task failures", set(rows["SIGNAL"]))
        self.assertIn("Credit spike", set(rows["SIGNAL"]))
        self.assertNotIn("Current", set(rows["SIGNAL"]))
        self.assertLessEqual(len(rows), 6)

    def test_account_health_closure_analytics_sql_scores_action_queue_evidence(self):
        sql = _account_health_closure_analytics_sql(45, "ALFA", "PROD").upper()

        self.assertIn("OVERWATCH_ACTION_QUEUE", sql)
        self.assertIn("ACCOUNT HEALTH - DAILY DBA CHECKLIST", sql)
        self.assertIn("ACCOUNT HEALTH - ACCOUNT ACCESS HYGIENE", sql)
        self.assertIn("COMPANY = 'ALFA'", sql)
        self.assertIn("NO DATABASE CONTEXT", sql)
        self.assertIn("ENVIRONMENT", sql)
        self.assertIn("FIXED_WITHOUT_VERIFICATION", sql)
        self.assertIn("VERIFIED_CLOSURES", sql)
        self.assertIn("OVERDUE_OPEN", sql)
        self.assertIn("OWNER_APPROVAL_GAP_ROWS", sql)
        self.assertIn("CLOSURE_READINESS", sql)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_account_health_operability_fact_is_fast_and_keeps_account_scope_rows(self):
        ddl = build_account_health_operability_fact_ddl().upper()
        migrations = "\n".join(build_account_health_operability_fact_migration_sql()).upper()
        fact_sql = _account_health_operability_fact_sql(30, "ALFA", "DEV_ALL").upper()

        self.assertIn("FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY", ddl)
        self.assertIn("CONTROL_SOURCE", ddl)
        self.assertIn("CONTROL_RANK", ddl)
        self.assertIn("ACCESS_HYGIENE_ROWS", ddl)
        self.assertIn("FAILED_LOGIN_ROWS", ddl)
        self.assertIn("PRIVILEGED_GRANT_ROWS", ddl)
        self.assertIn("ADD COLUMN IF NOT EXISTS CONTROL_SOURCE", migrations)
        self.assertIn("ADD COLUMN IF NOT EXISTS ACCESS_HYGIENE_ROWS", migrations)
        self.assertIn("ADD COLUMN IF NOT EXISTS PRIVILEGED_GRANT_ROWS", migrations)
        self.assertIn("FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY", fact_sql)
        self.assertIn("SNAPSHOT_DATE >= DATEADD('DAY', -30", fact_sql)
        self.assertIn("COMPANY = 'ALFA'", fact_sql)
        self.assertIn("NO DATABASE CONTEXT", fact_sql)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, fact_sql)
        self.assertNotIn("ACCOUNT_USAGE", fact_sql)
        self.assertNotIn("OVERWATCH_ACTION_QUEUE", fact_sql)

    def test_account_health_source_health_flags_loaded_stale_and_unavailable_evidence(self):
        state = {
            "global_start_date": "",
            "global_end_date": "",
            "global_warehouse": "",
            "global_user": "",
            "global_role": "",
            "global_database": "",
            "health_data": {
                "_account_health_detail_source": "Fast summary",
                "_control_mart_source": "Fast control-room summary",
                "_control_mart": pd.DataFrame({"SNAPSHOT_TS": ["2026-05-31"]}),
                "_live_source": "ACCOUNT_USAGE",
                "live": pd.DataFrame({"ACTIVE_COUNT": [1]}),
            },
            "account_health_overview_meta": {
                "company": "ALFA",
                "environment": "PROD",
                "window": "24h",
                "global_start_date": "",
                "global_end_date": "",
                "global_warehouse": "",
                "global_user": "",
                "global_role": "",
                "global_database": "",
            },
            "account_health_operability_fact": pd.DataFrame(),
            "account_health_operability_fact_error": "FACT_ACCOUNT_HEALTH_OPERABILITY_DAILY missing",
            "account_health_access_hygiene_days": 30,
            "account_health_access_hygiene": pd.DataFrame({"USER_NAME": ["ALFA_ADMIN"]}),
            "account_health_access_hygiene_meta": {
                "company": "ALFA",
                "environment": "No Database Context",
                "window": "30d",
                "global_user": "",
            },
        }

        rows = _account_health_source_health_rows(state, company="ALFA", environment="PROD")
        by_surface = {row["SURFACE"]: row for _, row in rows.iterrows()}

        self.assertEqual(by_surface["Overview snapshot"]["STATE"], "Loaded")
        self.assertEqual(by_surface["Overview snapshot"]["CONFIDENCE"], "Fast summary")
        self.assertEqual(by_surface["Live status probe"]["STATE"], "Stale")
        self.assertEqual(by_surface["Control summary"]["STATE"], "Unavailable")
        self.assertEqual(by_surface["Access hygiene"]["STATE"], "Loaded")
        self.assertEqual(by_surface["Access hygiene"]["SCOPE"], "ALFA / No Database Context / 30d")
        self.assertEqual(by_surface["Access hygiene"]["CONFIDENCE"], "Live Snowflake metadata")
        self.assertEqual(by_surface["Checklist trend"]["STATE"], "On demand")
        self.assertIn("Current", by_surface["Access hygiene"]["NEXT_ACTION"])

    def test_account_health_access_hygiene_keeps_user_auth_scope_account_level(self):
        with patch(
            "sections.account_health.filter_existing_columns",
            return_value=["HAS_PASSWORD", "EXT_AUTHN_DUO", "LAST_SUCCESS_LOGIN"],
        ):
            sql = _account_health_access_hygiene_sql(None, 30, "ALFA", "DEV_ALL").upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.USERS", sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY", sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS", sql)
        self.assertIn("'NO DATABASE CONTEXT' AS DATABASE_CONTEXT", sql)
        self.assertIn("'NO DATABASE CONTEXT' AS ENVIRONMENT_SCOPE", sql)
        self.assertIn("'DEV_ALL' AS SELECTED_ENVIRONMENT", sql)
        self.assertIn("U.NAME NOT ILIKE 'TRXS_%'", sql)
        self.assertIn("LH.USER_NAME NOT ILIKE 'TRXS_%'", sql)
        self.assertNotIn("ALFA_EDW_DEV", sql)
        self.assertNotIn("TABLE_CATALOG", sql)
        self.assertNotIn("DATABASE_NAME", sql)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_account_health_access_hygiene_annotation_adds_queue_scope_and_owner(self):
        hygiene = pd.DataFrame([
            {
                "USER_NAME": "ALFA_ADMIN",
                "SEVERITY": "High",
                "POSTURE_FINDINGS": "privileged role grant; MFA signal missing",
                "FAILED_LOGINS": 2,
                "FAILED_IPS": 1,
                "ADMIN_ROLE_COUNT": 1,
                "ADMIN_ROLES": "ACCOUNTADMIN",
                "MFA_SIGNAL": "false",
                "DAYS_SINCE_SEEN": 4,
                "DATABASE_CONTEXT": "No Database Context",
                "ENVIRONMENT_SCOPE": "No Database Context",
                "SCOPE_CONFIDENCE": "Account-Level Control",
                "SCOPE_EVIDENCE": "USERS and LOGIN_HISTORY do not expose database context.",
                "NEXT_ACTION": "Confirm IAM owner and admin-role business need.",
                "PROOF_REQUIRED": "user, IAM ticket, admin-role evidence, owner approval",
            }
        ])
        annotated = _annotate_account_health_access_hygiene(hygiene)
        row = annotated.iloc[0]

        self.assertEqual(row["DATABASE_CONTEXT"], "No Database Context")
        self.assertEqual(row["ENVIRONMENT_SCOPE"], "No Database Context")
        self.assertEqual(row["SCOPE_CONFIDENCE"], "Account-Level Control")
        self.assertEqual(row["QUEUE_READINESS"], "Needs Routing Data")
        self.assertEqual(row["APPROVAL_REQUIRED"], "Yes")
        self.assertEqual(row["RECOVERY_SLA_TARGET_HOURS"], 24)
        self.assertIn("MONITORING_CONTEXT", row["OWNER_SOURCE"])
        self.assertEqual(row["QUEUE_BLOCKERS"], "review group")

    def test_account_health_access_hygiene_action_payload_is_review_only_and_account_scoped(self):
        hygiene = pd.DataFrame([
            {
                "USER_NAME": "ALFA_ADMIN",
                "SEVERITY": "High",
                "POSTURE_FINDINGS": "privileged role grant; MFA signal missing",
                "FAILED_LOGINS": 2,
                "FAILED_IPS": 1,
                "ADMIN_ROLE_COUNT": 1,
                "ADMIN_ROLES": "ACCOUNTADMIN",
                "MFA_SIGNAL": "false",
                "DAYS_SINCE_SEEN": 4,
                "DATABASE_CONTEXT": "No Database Context",
                "ENVIRONMENT_SCOPE": "No Database Context",
                "SCOPE_CONFIDENCE": "Account-Level Control",
                "SCOPE_EVIDENCE": "USERS and LOGIN_HISTORY do not expose database context.",
                "NEXT_ACTION": "Confirm IAM owner and admin-role business need.",
                "PROOF_REQUIRED": "user, IAM ticket, admin-role evidence, owner approval",
            }
        ])
        row = _annotate_account_health_access_hygiene(hygiene).iloc[0]
        action = _account_health_access_hygiene_action_payload(row, company="ALFA", days=30)
        verification_sql = _account_health_access_hygiene_verification_sql(row, days=30)

        self.assertEqual(action["Source"], "Account Health - Account Access Hygiene")
        self.assertEqual(action["Environment"], "No Database Context")
        self.assertEqual(action["Entity"], "ALFA_ADMIN")
        self.assertIn("Review only", action["Generated SQL Fix"])
        self.assertIn("do not grant, revoke, disable, or alter users", action["Generated SQL Fix"])
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.USERS", action["Verification Query"])
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS", verification_sql)
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])

    def test_cortex_ai_functions_sql_is_optional_and_live(self):
        sql = _build_cortex_ai_functions_daily_sql(
            30,
            include_user_filter=True,
            include_query_id=True,
        ).upper()
        self.assertIn("CORTEX_AI_FUNCTIONS_USAGE_HISTORY", sql)
        self.assertIn("SUM(COALESCE(F.CREDITS, 0))", sql)
        self.assertIn("COUNT(DISTINCT F.QUERY_ID)", sql)
        self.assertIn("LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS", sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS", sql)
        self.assertIn("ROLE_SCOPE.\"ROLE\" ILIKE '%TRXS%'", sql)

    def test_cortex_service_detail_sql_uses_available_service_columns(self):
        source = next(item for item in CORTEX_SERVICE_DETAIL_SOURCES if item["label"] == "Cortex AI Functions")
        candidates = _cortex_candidate_columns(source)
        self.assertIn("START_TIME", candidates)
        self.assertIn("CREDITS", candidates)

        sql, issue = _cortex_service_detail_sql(
            source,
            ["START_TIME", "CREDITS", "QUERY_ID", "USER_ID"],
            14,
            ai_credit_rate=2.2,
        )
        upper = sql.upper()

        self.assertEqual(issue, "")
        self.assertIn("CORTEX_AI_FUNCTIONS_USAGE_HISTORY", upper)
        self.assertIn("TO_DATE(RAW.START_TIME) AS USAGE_DATE", upper)
        self.assertIn("SUM(COALESCE(RAW.CREDITS, 0)) AS TOTAL_CREDITS", upper)
        self.assertIn("LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS", upper)
        self.assertIn("DATEADD('DAY', -14", upper)
        self.assertIn("* 2.2", upper)

    def test_cortex_service_detail_sql_requires_time_column(self):
        source = next(item for item in CORTEX_SERVICE_DETAIL_SOURCES if item["label"] == "Cortex REST API")
        sql, issue = _cortex_service_detail_sql(source, ["CREDITS"], 30, ai_credit_rate=2.2)

        self.assertEqual(sql, "")
        self.assertIn("usage time/date", issue)

    def test_cost_splash_cortex_sql_tracks_spend_and_top_user(self):
        mart_sql = _build_cost_splash_cortex_sql("ALFA", 90, DEFAULTS["ai_credit_price"], mart=True).upper()
        live_sql = _build_cost_splash_cortex_sql("Trexis", 60, DEFAULTS["ai_credit_price"], mart=False).upper()

        self.assertIn("FACT_CORTEX_DAILY", mart_sql)
        self.assertIn("CORTEX_SPEND_USD", mart_sql)
        self.assertIn("TOP_CORTEX_USER", mart_sql)
        self.assertIn("TOP_CORTEX_USER_SPEND_USD", mart_sql)
        self.assertIn("* 2.2", mart_sql)
        self.assertIn("DATEADD('DAY', -90", mart_sql)
        self.assertIn("CORTEX_CODE_SNOWSIGHT_USAGE_HISTORY", live_sql)
        self.assertIn("CORTEX_CODE_CLI_USAGE_HISTORY", live_sql)
        self.assertIn("TOKEN_CREDITS", live_sql)
        self.assertIn("* 2.2", live_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS", live_sql)
        self.assertIn("ROLE_SCOPE.\"ROLE\" ILIKE '%TRXS%'", live_sql)
        self.assertIn("DATEADD('DAY', -60", live_sql)

    def test_cost_splash_warehouse_delta_sql_reuses_shared_live_shape(self):
        import streamlit as st

        previous_state = dict(st.session_state)
        try:
            st.session_state["active_company"] = "ALFA"
            st.session_state["global_warehouse"] = "BI"
            mart_sql = _build_cost_splash_warehouse_delta_sql("ALFA", 7, mart=True).upper()
            live_sql = _build_cost_splash_warehouse_delta_sql("ALFA", 7, mart=False).upper()
        finally:
            st.session_state.clear()
            st.session_state.update(previous_state)

        self.assertIn("FACT_WAREHOUSE_HOURLY", mart_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", live_sql)
        self.assertIn("WITH BOUNDS AS", live_sql)
        self.assertIn("FULL OUTER JOIN", live_sql)
        self.assertIn("DATEADD('DAY', -14", live_sql)
        self.assertNotIn("WAREHOUSE_NAME ILIKE '%BI%'", live_sql)

    def test_recommendation_mart_sql_uses_preaggregated_facts(self):
        idle_sql = build_mart_recommendation_idle_sql("ALFA").upper()
        self.assertIn("FACT_WAREHOUSE_HOURLY", idle_sql)
        self.assertIn("FACT_QUERY_HOURLY", idle_sql)
        self.assertIn("COALESCE(Q.QUERY_COUNT, 0) = 0", idle_sql)
        self.assertNotIn("ACCOUNT_USAGE.QUERY_HISTORY", idle_sql)

        spill_sql = build_mart_recommendation_spill_sql("Trexis").upper()
        self.assertIn("FACT_QUERY_HOURLY", spill_sql)
        self.assertIn("TOTAL_SPILL_BYTES", spill_sql)
        self.assertIn("COMPANY = 'TREXIS'", spill_sql)

        task_sql = build_mart_recommendation_failed_tasks_sql("ALFA").upper()
        self.assertIn("FACT_TASK_RUN", task_sql)
        self.assertIn("'FAILED_WITH_ERROR'", task_sql)

        error_sql = build_mart_recommendation_query_errors_sql("ALFA", min_failures=7).upper()
        self.assertIn("FAILED_COUNT", error_sql)
        self.assertIn("HAVING FAILURES > 7", error_sql)

    def test_pipeline_load_failure_mart_sql_uses_copy_history_mart(self):
        sql = build_mart_pipeline_load_failures_sql(7, "ALFA").upper()
        self.assertIn("FACT_COPY_LOAD_DAILY", sql)
        self.assertIn("UPPER(COALESCE(STATUS, '')) <> 'LOADED'", sql)
        self.assertNotIn("ACCOUNT_USAGE.COPY_HISTORY", sql)

    def test_query_analysis_mart_sql_uses_recent_query_detail(self):
        bottleneck_sql = build_mart_query_bottleneck_sql(7, 300000, "ALFA").upper()
        self.assertIn("FACT_QUERY_DETAIL_RECENT", bottleneck_sql)
        self.assertIn("COALESCE(Q.TOTAL_ELAPSED_TIME, 0) > 300000", bottleneck_sql)
        self.assertIn("NULLIF(COALESCE(Q.PARTITIONS_TOTAL, 0), 0)", bottleneck_sql)
        self.assertNotIn("ACCOUNT_USAGE.QUERY_HISTORY", bottleneck_sql)

        degradation_sql = build_mart_query_degradation_sql("Trexis").upper()
        self.assertIn("FACT_QUERY_DETAIL_RECENT", degradation_sql)
        self.assertIn("COALESCE(Q.QUERY_HASH, SUBSTR(Q.QUERY_TEXT, 1, 200))", degradation_sql)
        self.assertIn("NULLIF(P.AVG_SEC, 0)", degradation_sql)
        self.assertIn("Q.COMPANY = 'TREXIS'", degradation_sql)

    def test_ai_query_diagnosis_model_is_evidence_bound(self):
        query_text = """
            SELECT *
            FROM PROD_DB.CORE.FACT_POLICY p
            JOIN PROD_DB.CORE.DIM_CUSTOMER c ON p.CUSTOMER_ID = c.CUSTOMER_ID
            JOIN PROD_DB.CORE.DIM_AGENT a ON p.AGENT_ID = a.AGENT_ID
            JOIN PROD_DB.CORE.DIM_PRODUCT pr ON p.PRODUCT_ID = pr.PRODUCT_ID
            JOIN PROD_DB.CORE.DIM_REGION r ON c.REGION_ID = r.REGION_ID
            WHERE TO_DATE(p.BIND_TS) = '2026-06-01'
              AND c.LAST_NAME ILIKE '%SMITH%'
            ORDER BY p.PREMIUM_AMOUNT
        """
        evidence = {
            "QUERY_ID": "01b123",
            "QUEUED_SEC": 42,
            "REMOTE_SPILL_GB": 8.5,
            "PARTITION_PCT": 97,
            "BYTES_SCANNED_GB": 180,
            "ROWS_PRODUCED": 125,
        }

        candidates = _build_query_optimization_candidates(query_text, evidence)
        signals = {row["SIGNAL"] for row in candidates}

        self.assertIn("Warehouse queue pressure", signals)
        self.assertIn("Remote spill", signals)
        self.assertIn("Full/high partition scan", signals)
        self.assertIn("Wide SELECT star", signals)
        self.assertIn("Leading wildcard text search", signals)
        self.assertIn("Function-wrapped predicate", signals)
        self.assertTrue(all(row["VERIFY_AFTER_FIX"] for row in candidates))

        prompt = _build_ai_query_diagnosis_prompt(
            query_text,
            evidence,
            candidates,
            "operator=JOIN; stats=remote spill observed",
        )
        self.assertIn("Every recommendation must cite exact telemetry", prompt)
        self.assertIn("Do not recommend indexes", prompt)
        self.assertIn("GET_QUERY_OPERATOR_STATS", prompt)
        self.assertIn("SYSTEM$CLUSTERING_INFORMATION", prompt)
        self.assertIn("Warehouse queue pressure", prompt)
        self.assertIn("Query Investigation action contract", prompt)
        self.assertIn("Do not invent table names", prompt)
        self.assertIn("Action decision", prompt)
        self.assertIn("Status check", prompt)

    def test_query_diagnosis_action_contract_is_specific_and_routed(self):
        query_text = """
            SELECT *
            FROM PROD_DB.CORE.FACT_POLICY p
            JOIN PROD_DB.CORE.DIM_CUSTOMER c ON p.CUSTOMER_ID = c.CUSTOMER_ID
            WHERE TO_DATE(p.BIND_TS) = '2026-06-01'
              AND c.LAST_NAME ILIKE '%SMITH%'
            ORDER BY p.PREMIUM_AMOUNT
        """
        evidence = {
            "QUERY_ID": "01specific",
            "WAREHOUSE_NAME": "WH_TRXS_QUERY",
            "QUEUED_SEC": 74,
            "REMOTE_SPILL_GB": 4.2,
            "PARTITION_PCT": 95,
            "BYTES_SCANNED_GB": 120,
            "ROWS_PRODUCED": 1000,
        }
        candidates = _build_query_optimization_candidates(query_text, evidence)
        contract = _build_query_diagnosis_action_contract(candidates, evidence, query_text)

        by_signal = {row["SIGNAL"]: row for row in contract}
        self.assertEqual(by_signal["Warehouse queue pressure"]["ACTION_DECISION"], "Route to Cost & Contract")
        self.assertIn("WH_TRXS_QUERY", by_signal["Warehouse queue pressure"]["FIRST_OPERATOR_MOVE"])
        self.assertIn("Do not rewrite SQL as the first fix", by_signal["Warehouse queue pressure"]["DO_NOT_DO"])
        self.assertEqual(by_signal["Remote spill"]["ACTION_DECISION"], "Inspect operator stats before rerun")
        self.assertIn("GET_QUERY_OPERATOR_STATS", by_signal["Remote spill"]["FIRST_OPERATOR_MOVE"])
        self.assertEqual(by_signal["Full/high partition scan"]["ACTION_DECISION"], "Fix pruning telemetry")
        self.assertIn("p.BIND_TS", by_signal["Full/high partition scan"]["EXACT_CHANGE"])
        self.assertEqual(by_signal["Leading wildcard text search"]["ACTION_DECISION"], "Redesign text lookup")
        self.assertIn("c.LAST_NAME", by_signal["Leading wildcard text search"]["EXACT_CHANGE"])
        self.assertTrue(all(row["VERIFY_AFTER_FIX"] for row in contract))

    def test_ai_query_diagnosis_prioritizes_lock_contention_evidence(self):
        query_text = """
            MERGE INTO PROD_DB.CORE.FACT_POLICY tgt
            USING STAGE_DB.LOAD.POLICY_DELTA src
              ON tgt.POLICY_ID = src.POLICY_ID
            WHEN MATCHED THEN UPDATE SET PREMIUM_AMOUNT = src.PREMIUM_AMOUNT
            WHEN NOT MATCHED THEN INSERT (POLICY_ID, PREMIUM_AMOUNT) VALUES (src.POLICY_ID, src.PREMIUM_AMOUNT)
        """
        evidence = {
            "QUERY_ID": "01blocked",
            "BLOCKED_SEC": 185,
            "QUEUED_SEC": 0,
            "ELAPSED_SEC": 540,
            "OPERATOR_NOTES": "Task overlap observed on shared final table.",
        }

        candidates = _build_query_optimization_candidates(query_text, evidence)
        signals = [row["SIGNAL"] for row in candidates]
        contract = _build_query_diagnosis_action_contract(candidates, evidence, query_text)

        self.assertEqual(signals[0], "Lock/write contention")
        self.assertIn("Write-path contention risk", signals)
        self.assertIn("Do not resize compute solely on blocked seconds", candidates[0]["SPECIFIC_RECOMMENDATION"])
        self.assertIn("TRANSACTION_BLOCKED_TIME", candidates[0]["VERIFY_AFTER_FIX"])
        self.assertEqual(contract[0]["ACTION_DECISION"], "Route to Contention Center before SQL tuning")
        self.assertIn("Do not resize the warehouse", contract[0]["DO_NOT_DO"])
        self.assertIn("DBA plus task/job route", contract[0]["OWNER_HANDOFF"])

        prompt = _build_ai_query_diagnosis_prompt(
            query_text,
            evidence,
            candidates,
            "operator=TableScan; stats=blocked writer",
        )
        self.assertIn("BLOCKED_SEC", prompt)
        self.assertIn("TRANSACTION_BLOCKED_TIME", prompt)
        self.assertIn("prioritize lock/write contention fixes", prompt)
        self.assertIn("Route to Contention Center before SQL tuning", prompt)

    def test_dba_control_room_mart_sql_uses_operational_facts(self):
        summary_sql = build_mart_control_room_summary_sql(24, "ALFA").upper()
        self.assertIn("FACT_QUERY_DETAIL_RECENT", summary_sql)
        self.assertIn("APPROX_PERCENTILE", summary_sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", summary_sql)

        driver_sql = build_mart_control_room_cost_drivers_sql(24, "Trexis").upper()
        self.assertIn("FACT_WAREHOUSE_HOURLY", driver_sql)
        self.assertIn("FACT_QUERY_DETAIL_RECENT", driver_sql)
        self.assertIn("WH_ELAPSED AS", driver_sql)
        self.assertIn("NULLIF(WE.WH_ELAPSED_MS, 0)", driver_sql)
        self.assertIn("Q.COMPANY = 'TREXIS'", driver_sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", driver_sql)

        task_sql = build_mart_control_room_task_failures_sql(24, "ALFA").upper()
        self.assertIn("FACT_TASK_RUN", task_sql)
        self.assertIn("'FAILED_WITH_ERROR'", task_sql)

    def test_task_critical_path_mart_sql_uses_persisted_graph_facts(self):
        sql = build_mart_task_critical_path_sql(7, "ALFA", database_contains="EDW").upper()

        self.assertIn("FACT_TASK_CRITICAL_PATH", sql)
        self.assertIn("CRITICAL_PATH_SCORE", sql)
        self.assertIn("APPROVAL_PATH", sql)
        self.assertIn("SOURCE_FRESHNESS", sql)
        self.assertIn("ROW_NUMBER() OVER", sql)
        self.assertIn("DATABASE_NAME ILIKE", sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY", sql)

    def test_account_health_mart_sql_uses_dashboard_facts(self):
        storage_sql = build_mart_account_health_storage_sql("ALFA").upper()
        self.assertIn("FACT_STORAGE_DAILY", storage_sql)
        self.assertIn("STORAGE_TB", storage_sql)
        self.assertNotIn("DATABASE_STORAGE_USAGE_HISTORY", storage_sql)

        trend_sql = build_mart_storage_trend_sql(30, "ALL").upper()
        self.assertIn("FACT_STORAGE_DAILY", trend_sql)
        self.assertIn("STAGE_BYTES", trend_sql)
        self.assertIn("HYBRID_TABLE_STORAGE_BYTES", trend_sql)
        self.assertIn("ARCHIVE_STORAGE_COOL_BYTES", trend_sql)
        self.assertIn("STANDARD_STORAGE_COST_USD", trend_sql)
        self.assertIn("ARCHIVE_COLD_COST_USD", trend_sql)

        cost_sql = build_mart_account_health_cost_drivers_sql(24, "Trexis").upper()
        self.assertIn("FACT_QUERY_DETAIL_RECENT", cost_sql)
        self.assertIn("FACT_WAREHOUSE_HOURLY", cost_sql)
        self.assertIn("AS TOTAL_CREDITS", cost_sql)
        self.assertIn("Q.COMPANY = 'TREXIS'", cost_sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", cost_sql)

        change_sql = build_mart_account_health_change_sql(24, "ALFA").upper()
        self.assertIn("FACT_QUERY_HOURLY", change_sql)
        self.assertIn("FACT_WAREHOUSE_HOURLY", change_sql)
        self.assertIn("QUERY_DELTA", change_sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", change_sql)

    def test_account_health_report_and_briefing_mart_sql_uses_facts(self):
        failures_sql = build_mart_account_health_failure_types_sql(12, "ALFA").upper()
        self.assertIn("FACT_QUERY_HOURLY", failures_sql)
        self.assertIn("FAIL_COUNT", failures_sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", failures_sql)

        long_sql = build_mart_account_health_long_queries_sql(12, "Trexis").upper()
        self.assertIn("FACT_QUERY_DETAIL_RECENT", long_sql)
        self.assertIn("ELAPSED_SEC", long_sql)
        self.assertIn("Q.COMPANY = 'TREXIS'", long_sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", long_sql)

        credits_sql = build_mart_account_health_credits_sql(24, "ALFA").upper()
        self.assertIn("FACT_WAREHOUSE_HOURLY", credits_sql)
        self.assertIn("PRIOR_PERIOD_CREDITS", credits_sql)
        self.assertIn("OVERNIGHT_CREDITS", credits_sql)

        count_sql = build_mart_account_health_failure_count_sql(24, "ALFA").upper()
        self.assertIn("FAIL_COUNT", count_sql)
        self.assertIn("FACT_QUERY_HOURLY", count_sql)

        top_sql = build_mart_account_health_top_driver_sql(24, "ALFA").upper()
        self.assertIn("AS CREDITS", top_sql)
        self.assertIn("FACT_QUERY_DETAIL_RECENT", top_sql)

        queued_sql = build_mart_account_health_queued_sql(1, "ALFA").upper()
        self.assertIn("AS QUEUED", queued_sql)
        self.assertIn("TOTAL_QUEUED_MS", queued_sql)

        ytd_sql = build_mart_account_health_ytd_credits_sql("ALFA").upper()
        self.assertIn("YTD_CREDITS", ytd_sql)
        self.assertIn("DATE_TRUNC('YEAR'", ytd_sql)

    def test_cost_contract_run_rate_sql_uses_complete_day_mart_and_yoy(self):
        mart_sql = build_mart_cost_run_rate_sql("ALFA").upper()
        live_sql = _build_cost_run_rate_sql("ALFA").upper()

        for sql in (mart_sql, live_sql):
            self.assertIn("DATE_TRUNC('DAY', CURRENT_TIMESTAMP())", sql)
            self.assertIn("DATEADD('DAY', -7", sql)
            self.assertIn("DATEADD('DAY', -30", sql)
            self.assertIn("DATEADD('YEAR', -1", sql)
            self.assertIn("AVG_DAILY_7D", sql)
            self.assertIn("AVG_DAILY_30D", sql)
            self.assertIn("PROJECTED_30D_FROM_7D", sql)
            self.assertIn("YOY_7D_PCT", sql)
            self.assertIn("YOY_30D_PCT", sql)
            self.assertIn("TOP_YOY_INCREASE_WAREHOUSE", sql)

        self.assertIn("FACT_WAREHOUSE_HOURLY", mart_sql)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", mart_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", live_sql)

    def test_cost_contract_cockpit_and_run_rate_use_shared_metering_builders(self):
        mart_cockpit = build_mart_cost_cockpit_sql("ALFA", 14).upper()
        live_cockpit = _build_cost_cockpit_sql("ALFA", 14).upper()
        mart_run_rate_source = inspect.getsource(build_mart_cost_run_rate_sql)
        live_run_rate_source = inspect.getsource(_build_cost_run_rate_sql)
        watch_floor_source = inspect.getsource(cost_contract._render_cost_watch_floor)
        detail_loader_source = inspect.getsource(cost_contract._refresh_cost_detail_state)

        for sql in (mart_cockpit, live_cockpit):
            self.assertIn("CURRENT_PERIOD", sql)
            self.assertIn("PRIOR_PERIOD", sql)
            self.assertIn("FULL OUTER JOIN", sql)
            self.assertIn("TOP_INCREASE_WAREHOUSE", sql)

        self.assertIn("FACT_WAREHOUSE_HOURLY", mart_cockpit)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", live_cockpit)
        self.assertIn("build_cost_run_rate_metering_sql", mart_run_rate_source)
        self.assertIn("build_cost_run_rate_metering_sql", live_run_rate_source)
        self.assertIn("_refresh_cost_detail_state(st.session_state, session, company, int(days), credit_price)", watch_floor_source)
        run_rate_refresh_line = next(
            line
            for line in detail_loader_source.splitlines()
            if 'state["cost_contract_run_rate"] = run_query_func(' in line
        )
        self.assertTrue(run_rate_refresh_line.startswith("        "))
        self.assertFalse(run_rate_refresh_line.startswith("            "))

    def test_cost_control_coverage_board_requires_drilldown_and_verified_savings(self):
        cockpit = pd.DataFrame([{"CURRENT_CREDITS": 10, "PRIOR_CREDITS": 8}])
        run_rate = pd.DataFrame([{"AVG_DAILY_7D": 1.2, "YOY_7D_PCT": 5.0, "YOY_30D_PCT": 3.0}])
        queue = pd.DataFrame([{
                "CATEGORY": "Cost Control",
                "STATUS": "New",
                "OWNER_SOURCE": "MONITORING_CONTEXT:COST_CONTROL_DEFAULT",
                "VERIFICATION_STATUS": "Pending",
            }])
        state = {
            "df_cost_explorer_detail": pd.DataFrame([{
                    "COMPANY": "ALFA",
                    "ENVIRONMENT_ROLLUP": "DEV_ALL",
                    "DATABASE_NAME": "ALFA_EDW_DEV",
                    "ROLE_NAME": "ETL_ROLE",
                    "USER_NAME": "ETL_USER",
                    "DEPARTMENT": "DATA",
                    "ALLOCATION_CONFIDENCE": "Allocated/Estimated",
                }]),
            "df_chargeback": pd.DataFrame([
                {
                    "COMPANY": "ALFA",
                    "ENVIRONMENT": "DEV",
                    "DATABASE_NAME": "ALFA_EDW_DEV",
                    "ALLOCATION_CONFIDENCE": "Allocated/Estimated",
                },
                {
                    "COMPANY": "ALFA",
                    "ENVIRONMENT": "DEV",
                    "DATABASE_NAME": "",
                    "ALLOCATION_CONFIDENCE": "Shared / No Database Context",
                },
            ]),
        }
        summary, board = _build_cost_control_coverage_board(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            state=state,
        )
        trust_summary, trust = _build_cost_allocation_trust_board(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            state=state,
        )
        drill_summary, drill_map = _build_cost_drilldown_command_map(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            state=state,
        )

        by_control = {row["CONTROL"]: row for _, row in board.iterrows()}
        by_trust = {row["CONTROL"]: row for _, row in trust.iterrows()}
        by_drill = {row["DRILLDOWN"]: row for _, row in drill_map.iterrows()}
        self.assertEqual(by_control["Exact warehouse metering"]["STATE"], "Ready")
        self.assertEqual(by_control["Role, user, and department drivers"]["STATE"], "Ready")
        self.assertEqual(by_control["Owned cost action queue"]["STATE"], "Ready")
        self.assertGreaterEqual(summary["score"], 90)
        self.assertEqual(by_trust["Contract and warehouse totals"]["TRUST_STATE"], "Exact")
        self.assertEqual(by_trust["Database attribution"]["TRUST_STATE"], "Allocated/Estimated")
        self.assertEqual(by_trust["Shared and no-database spend"]["TRUST_STATE"], "Allocated/Estimated")
        self.assertLess(trust_summary["score"], 100)
        self.assertEqual(by_drill["Warehouse usage movement"]["TRUST"], "Exact")
        self.assertEqual(by_drill["Warehouse usage movement"]["COMMAND_PRIORITY"], "P0")
        self.assertEqual(by_drill["Database, DEV rollup, no-database spend"]["TRUST"], "Allocated/Estimated")
        self.assertIn("no-database", by_drill["Database, DEV rollup, no-database spend"]["NEXT_ACTION"])
        self.assertGreaterEqual(drill_summary["ready"], 3)

        decomposition_summary, decomposition = _build_cost_decomposition_board(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            state=state,
        )
        by_driver = {row["DRIVER"]: row for _, row in decomposition.iterrows()}
        self.assertEqual(by_driver["Warehouse movement"]["TRUST"], "Exact")
        self.assertEqual(by_driver["Company and environment split"]["TRUST"], "Allocated/Estimated")
        self.assertEqual(by_driver["Open cost action queue"]["STATUS"], "Ready")
        self.assertGreaterEqual(decomposition_summary["score"], 80)

    def test_resource_monitor_guardrail_sql_is_review_only_and_assigns_warehouse(self):
        sql = _build_resource_monitor_guardrail_sql(
            "ALFA_WH",
            credit_quota=250,
            monitor_name="OVERWATCH_ALFA_WH_RM",
        ).upper()

        self.assertIn("RESOURCE MONITORS ARE WAREHOUSE-ONLY CONTROLS", sql)
        self.assertIn("CREATE RESOURCE MONITOR IF NOT EXISTS OVERWATCH_ALFA_WH_RM", sql)
        self.assertIn("TRIGGERS ON 75 PERCENT DO NOTIFY", sql)
        self.assertIn("ON 90 PERCENT DO SUSPEND", sql)
        self.assertIn("ALTER WAREHOUSE IF EXISTS ALFA_WH", sql)
        self.assertIn("SET RESOURCE_MONITOR = OVERWATCH_ALFA_WH_RM", sql)
        self.assertIn("SHOW RESOURCE MONITORS", sql)

    def test_cost_spike_root_cause_board_uses_loaded_dimensions_and_keeps_allocation_trust(self):
        cockpit = pd.DataFrame([{
            "CURRENT_CREDITS": 120,
            "PRIOR_CREDITS": 60,
            "TOP_INCREASE_WAREHOUSE": "ALFA_WH",
            "TOP_INCREASE_CREDITS": 55,
        }])
        run_rate = pd.DataFrame([{
            "AVG_DAILY_7D": 17,
            "AVG_DAILY_30D": 8.5,
            "PCT_VS_30D_AVG": 100,
            "YOY_7D_PCT": 42,
        }])
        queue = pd.DataFrame([{
            "CATEGORY": "Cost Control",
            "STATUS": "New",
            "EST_MONTHLY_SAVINGS": 700,
        }])
        state = {
            "df_chargeback": pd.DataFrame([{
                "COMPANY": "ALFA",
                "ENVIRONMENT": "PROD",
                "DATABASE_NAME": "ALFA_EDW_PROD",
                "TOTAL_CREDITS": 40,
            }]),
            "df_cost_explorer_detail": pd.DataFrame([{
                "ROLE_NAME": "ETL_ROLE",
                "USER_NAME": "ETL_USER",
                "DEPARTMENT": "DATA",
                "TOTAL_CREDITS": 30,
            }]),
        }

        summary, board = _build_cost_spike_root_cause_board(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            credit_price=4.0,
            state=state,
        )
        by_driver = {row["DRIVER"]: row for _, row in board.iterrows()}

        self.assertEqual(by_driver["Warehouse movement"]["ENTITY"], "ALFA_WH")
        self.assertEqual(by_driver["Warehouse movement"]["TRUST"], "Exact warehouse metering")
        self.assertEqual(by_driver["Database / DEV rollup"]["ENTITY"], "ALFA_EDW_PROD")
        self.assertEqual(by_driver["Database / DEV rollup"]["TRUST"], "Allocated / Estimated")
        self.assertEqual(by_driver["Role / user / department"]["ENTITY"], "ETL_ROLE")
        self.assertIn("post-period measurement", by_driver["Open savings queue"]["NEXT_ACTION"])
        self.assertEqual(summary["top_driver"], "Warehouse movement")
        self.assertLess(summary["score"], 100)

    def test_change_cost_correlation_board_flags_top_warehouse_change_risk(self):
        cockpit = pd.DataFrame([{
            "CURRENT_CREDITS": 120,
            "PRIOR_CREDITS": 60,
            "TOP_INCREASE_WAREHOUSE": "ALFA_WH",
            "TOP_INCREASE_CREDITS": 55,
        }])
        run_rate = pd.DataFrame([{"PCT_VS_30D_AVG": 40}])
        state = {
            "change_drift_exceptions": pd.DataFrame([{
                "SEVERITY": "High",
                "FINDING_TYPE": "Warehouse Setting Change",
                "ENTITY": "ALFA_WH",
                "WAREHOUSE_NAME": "ALFA_WH",
                "QUERY_ID": "01change",
                "USER_NAME": "DBA",
            }])
        }

        summary, board = _build_change_cost_correlation_board(
            cockpit=cockpit,
            run_rate=run_rate,
            state=state,
        )
        by_correlation = {row["CORRELATION"]: row for _, row in board.iterrows()}

        self.assertEqual(by_correlation["Top warehouse change proximity"]["SEVERITY"], "High")
        self.assertIn("ALFA_WH", by_correlation["Top warehouse change proximity"]["ENTITY"])
        self.assertIn("query_id", by_correlation["Top warehouse change proximity"]["PROOF_REQUIRED"].lower())
        self.assertIn("before tuning", by_correlation["Top warehouse change proximity"]["NEXT_ACTION"])
        self.assertLess(summary["score"], 100)

    def test_ask_overwatch_reads_cost_root_cause_and_change_correlation(self):
        state = {
            "cost_contract_spike_root_cause": pd.DataFrame([{
                "SEVERITY": "High",
                "DRIVER": "Warehouse movement",
                "ENTITY": "ALFA_WH",
                "ROOT_CAUSE_SIGNAL": "Top warehouse delta",
                "VALUE_AT_RISK_USD": 220,
                "CONFIDENCE": "High",
                "TRUST": "Exact warehouse metering",
                "EVIDENCE": "ALFA_WH moved 55 credits versus prior.",
                "NEXT_ACTION": "Confirm owner demand and warehouse setting changes before tuning.",
                "PROOF_REQUIRED": "WAREHOUSE_METERING_HISTORY current/prior window and top delta.",
                "ROUTE": "Cost & Contract > Cost by Warehouse",
            }]),
            "cost_contract_change_cost_correlation": pd.DataFrame([{
                "SEVERITY": "High",
                "CORRELATION": "Top warehouse change proximity",
                "ENTITY": "ALFA_WH",
                "COST_SIGNAL": "Top warehouse delta 55 credits.",
                "CHANGE_SIGNAL": "1 row mentions the top warehouse.",
                "EVIDENCE": "Warehouse setting change is a root-cause candidate.",
                "NEXT_ACTION": "Review query_id, actor, warehouse settings, and rollback evidence before tuning.",
                "PROOF_REQUIRED": "Change exception query_id and WAREHOUSE_METERING_HISTORY.",
                "ROUTE": "Change & Drift > Controlled DBA actions",
            }]),
        }

        result = answer_ask_overwatch(
            "What is the root cause of the cost spike on ALFA_WH?",
            state,
            active_section="Cost & Contract",
            company="ALFA",
            environment="PROD",
        )

        self.assertIn("Warehouse movement", result["answer"])
        self.assertIn("ALFA_WH", result["answer"])
        self.assertIn("before tuning", result["answer"])

    def test_cost_monitoring_alert_rows_promote_specific_cost_issues(self):
        root = pd.DataFrame([{
            "SEVERITY": "High",
            "DRIVER": "Warehouse movement",
            "ENTITY": "ALFA_WH",
            "VALUE_AT_RISK_USD": 680.0,
            "EVIDENCE": "ALFA_WH moved 170 credits versus prior window.",
            "NEXT_ACTION": "Confirm owner demand and setting changes before tuning.",
            "PROOF_REQUIRED": "WAREHOUSE_METERING_HISTORY current/prior window.",
            "ROUTE": "Cost & Contract > Cost by Warehouse",
        }])
        correlation = pd.DataFrame([{
            "SEVERITY": "High",
            "CORRELATION": "Top warehouse change proximity",
            "ENTITY": "ALFA_WH",
            "EVIDENCE": "ALTER WAREHOUSE change may explain the cost movement.",
            "NEXT_ACTION": "Compare change query_id to the cost window before tuning.",
            "PROOF_REQUIRED": "FACT_OBJECT_CHANGE query_id and rollback evidence.",
            "ROUTE": "Change & Drift > Controlled DBA actions",
        }])

        summary, alerts = _build_cost_monitoring_alert_rows(
            root_cause=root,
            correlation=correlation,
            email_target="dba-alerts@example.com",
        )
        by_type = {row["ALERT_TYPE"]: row for _, row in alerts.iterrows()}

        self.assertEqual(summary["critical_high"], 2)
        self.assertEqual(alerts.iloc[0]["ENTITY_NAME"], "ALFA_WH")
        self.assertEqual(by_type["Cost Root Cause Candidate"]["EMAIL_TARGET"], "dba-alerts@example.com")
        self.assertIn("current/prior", by_type["Cost Root Cause Candidate"]["PROOF_QUERY"])
        self.assertIn("before tuning", by_type["Change Cost Correlation"]["SUGGESTED_ACTION"])

    def test_cost_incident_timeline_orders_detection_root_cause_alert_and_verification(self):
        cockpit = pd.DataFrame([{
            "CURRENT_CREDITS": 220,
            "PRIOR_CREDITS": 90,
            "TOP_INCREASE_WAREHOUSE": "ALFA_WH",
            "TOP_INCREASE_CREDITS": 130,
        }])
        run_rate = pd.DataFrame([{"PCT_VS_30D_AVG": 34.0}])
        queue = pd.DataFrame([{
            "CATEGORY": "Cost Control",
            "STATUS": "New",
            "SEVERITY": "High",
        }])
        alerts = pd.DataFrame([{
            "SEVERITY": "High",
            "ALERT_TYPE": "Cost Root Cause Candidate",
            "ENTITY_NAME": "ALFA_WH",
            "MESSAGE": "ALFA_WH moved 130 credits.",
            "SUGGESTED_ACTION": "Route to DBA / Cost owner email triage.",
            "PROOF_QUERY": "SELECT * FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = 'ALFA_WH'",
            "VALUE_AT_RISK_USD": 478.4,
        }])
        state = {
            "cost_contract_spike_root_cause": pd.DataFrame([{
                "SEVERITY": "High",
                "ENTITY": "ALFA_WH",
                "EVIDENCE": "Top warehouse delta is the leading root-cause candidate.",
                "NEXT_ACTION": "Confirm owner demand before tuning.",
                "PROOF_REQUIRED": "Current/prior warehouse metering.",
                "ROUTE": "Cost & Contract",
            }]),
            "cost_contract_change_cost_correlation": pd.DataFrame([{
                "SEVERITY": "High",
                "ENTITY": "ALFA_WH",
                "EVIDENCE": "Recent warehouse setting change is near the cost window.",
                "NEXT_ACTION": "Compare query_id and rollback evidence.",
                "PROOF_REQUIRED": "FACT_OBJECT_CHANGE query_id.",
                "ROUTE": "Change & Drift",
            }]),
        }

        summary, timeline = _build_cost_incident_timeline(
            cockpit=cockpit,
            run_rate=run_rate,
            queue=queue,
            alert_rows=alerts,
            state=state,
        )

        self.assertEqual(list(timeline["EVENT_ORDER"]), [1, 2, 3, 4, 5])
        self.assertEqual(timeline.iloc[0]["INCIDENT_STEP"], "Cost movement detected")
        self.assertEqual(timeline.iloc[3]["INCIDENT_STEP"], "Alert routed")
        self.assertIn("post-period telemetry", timeline.iloc[4]["NEXT_ACTION"])
        self.assertEqual(summary["critical_high"], 5)

    def test_ask_overwatch_reads_cost_monitoring_alerts_and_timeline(self):
        state = {
            "cost_contract_monitoring_alerts": pd.DataFrame([{
                "SEVERITY": "High",
                "CATEGORY": "Cost Control",
                "ALERT_TYPE": "Cost Root Cause Candidate",
                "ENTITY_NAME": "ALFA_WH",
                "MESSAGE": "ALFA_WH moved 130 credits and needs owner-backed proof.",
                "SUGGESTED_ACTION": "Open Cost & Contract root-cause drilldown and route the alert.",
                "PROOF_QUERY": "SELECT * FROM FACT_WAREHOUSE_HOURLY WHERE WAREHOUSE_NAME = 'ALFA_WH'",
                "ROUTE": "Alert Center",
                "EMAIL_TARGET": "dba-alerts@example.com",
                "VALUE_AT_RISK_USD": 478.4,
            }]),
            "cost_contract_incident_timeline": pd.DataFrame([{
                "EVENT_ORDER": 4,
                "SEVERITY": "High",
                "INCIDENT_STEP": "Alert routed",
                "ENTITY": "ALFA_WH",
                "EVIDENCE": "Cost monitoring alert is ready for email triage.",
                "NEXT_ACTION": "Route the alert to DBA / Cost owner.",
                "PROOF_REQUIRED": "Alert proof query.",
                "ROUTE": "Alert Center",
            }]),
        }

        cards = build_ask_overwatch_context(state)
        result = answer_ask_overwatch(
            "What cost alert should we route?",
            state,
            active_section="Cost & Contract",
            company="ALFA",
            environment="PROD",
        )

        self.assertEqual(cards[0]["surface"], "Cost & Contract - Monitoring Alert Candidate")
        self.assertIn("ALFA_WH", result["answer"])
        self.assertIn("dba-alerts@example.com", result["answer"])
        self.assertIn("Alert Center", result["answer"])

    def test_overwatch_mart_setup_keeps_cost_monitoring_and_upgrade_contract(self):
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")
        setup_upper = setup_sql.upper()

        self.assertIn("ALTER TABLE IF EXISTS FACT_QUERY_HOURLY ADD COLUMN IF NOT EXISTS ENVIRONMENT", setup_upper)
        self.assertIn("ALTER TABLE IF EXISTS FACT_QUERY_DETAIL_RECENT ADD COLUMN IF NOT EXISTS ENVIRONMENT", setup_upper)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_MONITORING_SIGNAL", setup_upper)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_INCIDENT_TIMELINE", setup_upper)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_DAILY", setup_upper)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_COST_SOURCE_HEALTH_DAILY", setup_upper)
        self.assertNotIn("FACT_MONITORING_COST_DAILY", setup_upper)
        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS MART_EXECUTIVE_OBSERVABILITY", setup_upper)
        self.assertIn("EXECUTIVE_OBSERVABILITY", setup_upper)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS OVERWATCH_REFRESH_POLICY", setup_upper)
        self.assertNotIn("OVERWATCH_COMMAND_INTELLIGENCE_CAPABILITY", setup_upper)
        self.assertNotIn("OVERWATCH_COMPANY_SCOPE", setup_upper)
        self.assertNotIn("OVERWATCH_COMPLIANCE_READINESS_V", setup_upper)
        self.assertNotIn("OPTIONAL_DYNAMIC_TABLES", setup_upper)
        self.assertIn("ALTER TABLE IF EXISTS FACT_COST_DAILY ADD COLUMN IF NOT EXISTS RATE_USD", setup_upper)
        self.assertIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY", setup_upper)
        self.assertIn("CREATE OR REPLACE TASK OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH", setup_upper)
        self.assertIn("CALL SP_OVERWATCH_REFRESH_EXECUTIVE_OBSERVABILITY()", setup_upper)
        for panel in [
            "'DAILY_COST'",
            "'MONTHLY_COST'",
            "'DAILY_WORKLOAD'",
            "'QUERY_TYPE'",
            "'WAREHOUSE_PRESSURE'",
            "'FRESHNESS'",
        ]:
            self.assertIn(panel, setup_upper)
        for metric in [
            "'CREDITS USED'",
            "'SPEND DELTA'",
            "'CORTEX SPEND'",
            "'TOTAL QUERIES'",
            "'AVG RUNTIME'",
            "'P95 RUNTIME'",
            "'QUEUE TIME'",
            "'REMOTE SPILL'",
            "'FAILED QUERIES'",
            "'FAILED TASKS'",
            "'CRITICAL HIGH ALERTS'",
            "'OPEN ACTIONS'",
            "'STORAGE'",
            "'PLATFORM HEALTH'",
        ]:
            self.assertIn(metric, setup_upper)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY", setup_upper)
        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY", setup_upper)
        self.assertIn("AI_CREDIT_PRICE_USD", setup_upper)
        self.assertIn("AI_CREDIT_PRICE := COALESCE(AI_CREDIT_PRICE, 2.20)", setup_upper)
        self.assertIn("DATEADD('HOUR', -24, CURRENT_TIMESTAMP())", setup_upper)
        self.assertIn("ROUND(SUM(TOTAL_CREDITS * RATE_USD), 2) AS EST_COST_USD", setup_upper)
        self.assertIn("SERVICE_CATEGORY", setup_upper)
        self.assertIn("CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH", setup_upper)
        self.assertIn("STATEMENT_TIMEOUT_IN_SECONDS = 600", setup_upper)
        self.assertIn("CREATE RESOURCE MONITOR IF NOT EXISTS COMPUTE_WH_RM", setup_upper)
        self.assertIn("WITH CREDIT_QUOTA = 50", setup_upper)
        self.assertIn("TRIGGERS ON 80 PERCENT DO NOTIFY", setup_upper)
        self.assertIn("ON 100 PERCENT DO SUSPEND", setup_upper)
        self.assertIn("ALTER WAREHOUSE IF EXISTS COMPUTE_WH", setup_upper)
        self.assertIn("SET RESOURCE_MONITOR = COMPUTE_WH_RM", setup_upper)
        self.assertIn("WHEN SRC.SETTING_NAME = 'DEFAULT_ALERT_EMAIL'", setup_upper)
        self.assertIn("ILIKE '%YOURCOMPANY.COM%'", setup_upper)
        self.assertIn("'CONFIG_REQUIRED'", setup_upper)
        self.assertIn("CREATE OR REPLACE PROCEDURE SP_OVERWATCH_REFRESH_COST_MONITORING", setup_upper)
        self.assertIn("CREATE OR REPLACE TASK OVERWATCH_COST_MONITORING_REFRESH", setup_upper)
        self.assertIn("AFTER OVERWATCH_REFRESH_CONTROL_ROOM", setup_upper)
        self.assertIn("OVERWATCH_ALERTS", setup_upper)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_ANNOTATIONS", setup_upper)
        self.assertIn("WAREHOUSE = COMPUTE_WH", setup_upper)
        self.assertIn("WAREHOUSE_COST_MOVEMENT", setup_upper)
        self.assertIn("CORTEX_SPEND_AND_QUOTA", setup_upper)
        self.assertIn("CHANGE_COST_CORRELATION", setup_upper)
        self.assertIn("CREATE TABLE IF NOT EXISTS OVERWATCH_SCHEMA_MIGRATION", setup_upper)
        self.assertIn(OVERWATCH_SCHEMA_VERSION.upper(), setup_upper)

    def test_overwatch_mart_drop_script_covers_setup_objects(self):
        def strip_sql_comments(sql: str) -> str:
            return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())

        setup_sql = strip_sql_comments(
            (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")
        ).upper()
        drop_sql = (ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql").read_text(encoding="utf-8").upper()

        tables = re.findall(
            r"^\s*CREATE\s+(?:TRANSIENT\s+)?TABLE\s+IF\s+NOT\s+EXISTS\s+([A-Z0-9_]+)",
            setup_sql,
            flags=re.MULTILINE,
        )
        views = re.findall(r"^\s*CREATE\s+OR\s+REPLACE\s+VIEW\s+([A-Z0-9_]+)", setup_sql, flags=re.MULTILINE)
        tasks = re.findall(r"^\s*CREATE\s+OR\s+REPLACE\s+TASK\s+([A-Z0-9_]+)", setup_sql, flags=re.MULTILINE)
        functions = re.findall(
            r"^\s*CREATE\s+OR\s+REPLACE\s+FUNCTION\s+([A-Z0-9_]+)\s*\(",
            setup_sql,
            flags=re.MULTILINE,
        )
        procedures = re.findall(
            r"^\s*CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+([A-Z0-9_]+)\s*\(",
            setup_sql,
            flags=re.MULTILINE,
        )

        self.assertEqual(len(tables), 94)
        self.assertEqual(len(views), 3)
        self.assertEqual(len(tasks), 14)
        self.assertEqual(len(functions), 1)
        self.assertEqual(len(procedures), 17)

        for table in tables:
            self.assertIn(f"DROP TABLE IF EXISTS {table}", drop_sql)
        for view in views:
            self.assertIn(f"DROP VIEW IF EXISTS {view}", drop_sql)
        for task in tasks:
            self.assertIn(f"ALTER TASK IF EXISTS {task} SUSPEND", drop_sql)
            self.assertIn(f"DROP TASK IF EXISTS {task}", drop_sql)
        for function in functions:
            self.assertIn(f"DROP FUNCTION IF EXISTS {function}", drop_sql)
        for procedure in procedures:
            self.assertIn(f"DROP PROCEDURE IF EXISTS {procedure}", drop_sql)

    def test_mart_refresh_procedures_do_not_write_retired_objects(self):
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()
        retired_objects = [
            "FACT_MONITORING_COST_DAILY",
            "OVERWATCH_AUTOMATION_RUN",
            "OVERWATCH_EXECUTIVE_PACKET",
            "OVERWATCH_AUTOMATION_HEALTH_V",
            "OVERWATCH_EXTERNAL_CONTROL_FEED",
            "OVERWATCH_SOURCE_CONTROL_CHANGE",
            "OVERWATCH_OWNER_APPROVAL",
            "OVERWATCH_OWNER_DIRECTORY",
            "OVERWATCH_PLATFORM_FUTURES_CONTROL_REGISTER",
            "OVERWATCH_COST_SAVINGS_VERIFICATION_RUN",
        ]
        for retired in retired_objects:
            with self.subTest(retired=retired):
                self.assertNotIn(f"CREATE TABLE IF NOT EXISTS {retired}", setup_sql)
                self.assertNotIn(f"CREATE TRANSIENT TABLE IF NOT EXISTS {retired}", setup_sql)
                self.assertNotIn(f"CREATE OR REPLACE VIEW {retired}", setup_sql)
                self.assertNotIn(f"INSERT INTO {retired}", setup_sql)
                self.assertNotIn(f"MERGE INTO {retired}", setup_sql)
                self.assertNotIn(f"DELETE FROM {retired}", setup_sql)

    def test_schema_migration_contract_tracks_setup_ledger(self):
        contract = build_schema_migration_contract()
        ddl = build_schema_migration_ddl().upper()
        status_sql = build_schema_migration_status_sql().upper()

        self.assertIn("OVERWATCH_SCHEMA_MIGRATION", ddl)
        self.assertIn(OVERWATCH_SCHEMA_VERSION.upper(), ddl)
        self.assertNotIn("OVERWATCH_COST_SAVINGS_VERIFICATION_RUN", status_sql)
        self.assertNotIn("OVERWATCH_AUTOMATION_RUN", status_sql)
        self.assertNotIn("OVERWATCH_AUTOMATION_HEALTH_V", status_sql)
        self.assertNotIn("OVERWATCH_EXECUTIVE_PACKET", status_sql)
        self.assertIn("OVERWATCH_ALERT_DELIVERY_LOG", status_sql)
        self.assertIn("OVERWATCH_ANNOTATIONS", status_sql)
        self.assertIn("FACT_COST_DAILY", status_sql)
        self.assertIn("FACT_COST_SOURCE_HEALTH_DAILY", status_sql)
        self.assertIn("MART_EXECUTIVE_OBSERVABILITY", status_sql)
        self.assertIn("FACT_PROCEDURE_RUN", status_sql)
        self.assertNotIn("OVERWATCH_EXTERNAL_CONTROL_FEED", status_sql)
        self.assertNotIn("OVERWATCH_SOURCE_CONTROL_CHANGE", status_sql)
        self.assertNotIn("OVERWATCH_OWNER_APPROVAL", status_sql)
        self.assertNotIn("OVERWATCH_CHANGE_EVIDENCE_CSV_FORMAT", status_sql)
        self.assertIn("INFORMATION_SCHEMA.STAGES", status_sql)
        self.assertIn("INFORMATION_SCHEMA.FILE_FORMATS", status_sql)
        self.assertIn("VERSION DRIFT", status_sql)
        self.assertIn("Schema migration ledger", set(contract["COMPONENT"]))
        self.assertNotIn("Change evidence feed ingress", set(contract["COMPONENT"]))
        self.assertIn("Procedure runtime context", set(contract["COMPONENT"]))
        self.assertIn("Executive observability mart", set(contract["COMPONENT"]))
        self.assertIn("OVERWATCH_SCHEMA_MIGRATION", set(contract["REQUIRED_OBJECT"]))
        self.assertIn("FACT_COST_DAILY", set(contract["REQUIRED_OBJECT"]))
        self.assertIn("MART_EXECUTIVE_OBSERVABILITY", set(contract["REQUIRED_OBJECT"]))
        self.assertIn("FACT_PROCEDURE_RUN", set(contract["REQUIRED_OBJECT"]))
        self.assertIn("OVERWATCH_ANNOTATIONS", set(contract["REQUIRED_OBJECT"]))
        self.assertNotIn("OVERWATCH_AUTOMATION_RUN", set(contract["REQUIRED_OBJECT"]))
        self.assertNotIn("OVERWATCH_EXTERNAL_CONTROL_FEED", set(contract["REQUIRED_OBJECT"]))
        self.assertNotIn("No-touch automation", set(contract["COMPONENT"]))
        self.assertNotIn("Flyway", " ".join(contract["WHY_IT_MATTERS"].astype(str)))
        self.assertIn("Cost telemetry mart", set(contract["COMPONENT"]))

    def test_mart_validation_and_live_role_checklist_cover_deployment_proof(self):
        validation_sql = (ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql").read_text(encoding="utf-8").upper()
        checklist = (ROOT / "docs" / "LIVE_ROLE_PROOF_CHECKLIST.md").read_text(encoding="utf-8").upper()

        for required in [
            "MART_EXECUTIVE_OBSERVABILITY",
            "ALERT_ACKNOWLEDGEMENTS",
            "ALERT_REMEDIATION_LOG",
            "OVERWATCH_RECON_CONFIG",
            "OVERWATCH_SCHEMA_DIFF_RESULT",
            "FACT_TASK_RUN",
            "FACT_TASK_CRITICAL_PATH",
        ]:
            self.assertIn(required, validation_sql)

        for panel in [
            "DAILY_COST",
            "MONTHLY_COST",
            "QUERY_DATABASE",
            "EXEC_STATUS",
            "WAREHOUSE_PRESSURE",
            "SOURCE_STATUS",
        ]:
            self.assertIn(panel, validation_sql)

        self.assertIn("CURRENT_ROLE()", validation_sql)
        self.assertIn("SOURCE_CLASS AS FIRST_PAINT_SOURCE", validation_sql)
        self.assertIn("APPROVED_LIVE_FALLBACK AS LIVE_FALLBACK_ALLOWED", validation_sql)
        self.assertIn("REFRESH_STATE", validation_sql)
        self.assertIn("TARGET_FRESHNESS_MIN AS TARGET_FRESHNESS_MINUTES", validation_sql)
        self.assertIn("EXPECTED_COUNT", validation_sql)
        self.assertIn("ACTUAL_COUNT", validation_sql)
        self.assertIn("SHOW TASKS IN SCHEMA", validation_sql)
        self.assertIn("OVERWATCH_LOAD_HOURLY", validation_sql)
        self.assertIn("OVERWATCH_EXECUTIVE_OBSERVABILITY_REFRESH", validation_sql)
        self.assertIn("SHOW DYNAMIC TABLES IN SCHEMA", validation_sql)
        self.assertIn("DYNAMIC_TABLE_COLLISIONS", validation_sql)
        self.assertIn("SECURE_VIEW_COLLISIONS", validation_sql)
        self.assertNotIn("OVERWATCH_REFRESH_POLICY", validation_sql)
        self.assertIn("SNOW_ACCOUNTADMINS", checklist)
        self.assertIn("SNOW_SYSADMINS", checklist)
        self.assertNotIn("_DSA", checklist)
        self.assertNotIn("_DTI", checklist)
        self.assertIn("SNOWFLAKE OBSERVABILITY WALL", checklist)
        self.assertIn("COST & CONTRACT", checklist)
        self.assertIn("ACTION QUEUE", checklist)

    def test_streamlit_deployment_decision_pins_entrypoints(self):
        decision = build_streamlit_deployment_decision()
        by_runtime = {row["RUNTIME"]: row for _, row in decision.iterrows()}

        self.assertIn("2026.06.13", STREAMLIT_DEPLOYMENT_DECISION_VERSION)
        sis = by_runtime["Streamlit in Snowflake"]
        self.assertEqual(sis["MANIFEST"], ".overwatch_final/snowflake.yml")
        self.assertEqual(sis["ENTRYPOINT"], ".overwatch_final/app.py")
        self.assertEqual(sis["WAREHOUSE"], "COMPUTE_WH")
        self.assertEqual(sis["EXECUTE_AS"], "CALLER")
        self.assertIn("streamlit_app.py", sis["DO_NOT_USE"])
        self.assertNotIn("COMPUTE_WH", sis["DO_NOT_USE"])

        cloud = by_runtime["Streamlit Community Cloud"]
        self.assertEqual(cloud["ENTRYPOINT"], "streamlit_app.py")
        self.assertEqual(cloud["MANIFEST"], ".streamlit/config.toml")

        setup = by_runtime["Snowflake status"]
        self.assertEqual(setup["ENTRYPOINT"], "Approved DBA release process")
        self.assertIn("owned outside the Streamlit UI", setup["DEPLOY_CONTEXT"])

    def test_cost_monitoring_mart_sql_matches_setup_object_contract(self):
        sql = build_cost_monitoring_mart_sql().upper()

        self.assertIn("FACT_COST_MONITORING_SIGNAL", sql)
        self.assertIn("FACT_COST_INCIDENT_TIMELINE", sql)
        self.assertIn("SP_OVERWATCH_REFRESH_COST_MONITORING", sql)
        self.assertIn("OVERWATCH_COST_MONITORING_REFRESH", sql)
        self.assertIn("OVERWATCH_ALERTS", sql)
        self.assertIn("WAREHOUSE = COMPUTE_WH", sql)

    def test_control_room_snapshot_maps_to_watch_floor_shape(self):
        snapshot = pd.DataFrame([
            {
                "COMPANY": "ALFA",
                "HEALTH_SCORE": 91,
                "FAILED_QUERIES_24H": 2,
                "FAILED_TASKS_24H": 1,
                "QUEUED_MS_24H": 120000,
                "CREDITS_24H": 4.5,
                "CORTEX_COST_7D_USD": 70,
                "SECURITY_EVENTS_24H": 3,
                "OBJECT_CHANGES_24H": 4,
                "TOP_RISK": "Failed tasks",
            }
        ])
        data = _control_room_snapshot_to_data(snapshot)
        self.assertIn("summary", data)
        self.assertIn("credits", data)
        self.assertEqual(float(data["summary"].iloc[0]["FAILED_QUERIES"]), 2.0)
        self.assertEqual(float(data["credits"].iloc[0]["PERIOD_CREDITS"]), 4.5)
        self.assertFalse(data["task_failures"].empty)
        self.assertFalse(data["failed_logins"].empty)
        self.assertFalse(data["object_changes"].empty)
        self.assertIn("_mart_snapshot", data)

    def test_control_room_fast_triage_skips_live_fallback_by_default(self):
        called_sql = []

        def fail_mart(sql, **_kwargs):
            called_sql.append(str(sql).upper())
            raise RuntimeError("mart unavailable")

        with patch("sections.dba_control_room.data.run_query", side_effect=fail_mart), patch(
            "sections.dba_control_room.data.load_action_queue",
            return_value=pd.DataFrame(),
        ):
            data = _load_control_room(
                session=None,
                company="ALFA",
                credit_price=3.68,
                lookback_hours=24,
                cortex_budget_usd=5000,
            )

        self.assertIn("_source_modes", data)
        self.assertTrue(any(row.get("Mode") == "Fast summary unavailable" for _, row in data["_source_modes"].iterrows()))
        self.assertFalse(any("SNOWFLAKE.ACCOUNT_USAGE" in sql for sql in called_sql))

    def test_control_room_live_fallback_defers_heavy_account_scans(self):
        called_sql = []

        def fail_mart_and_capture_live(sql, **_kwargs):
            sql_upper = str(sql).upper()
            called_sql.append(sql_upper)
            if "SNOWFLAKE.ACCOUNT_USAGE" in sql_upper:
                return pd.DataFrame()
            raise RuntimeError("mart unavailable")

        with patch("sections.dba_control_room.data.run_query", side_effect=fail_mart_and_capture_live), patch(
            "sections.dba_control_room.data.load_action_queue",
            return_value=pd.DataFrame(),
        ):
            data = _load_control_room(
                session=None,
                company="ALFA",
                credit_price=3.68,
                lookback_hours=168,
                cortex_budget_usd=5000,
                allow_live_fallback=True,
            )

        live_sql = [sql for sql in called_sql if "SNOWFLAKE.ACCOUNT_USAGE" in sql]
        self.assertTrue(any("WAREHOUSE_METERING_HISTORY" in sql for sql in live_sql))
        self.assertTrue(any("QUERY_HISTORY" in sql and "FAILED_WITH_ERROR" in sql for sql in live_sql))
        self.assertTrue(any("LOGIN_HISTORY" in sql for sql in live_sql))
        self.assertFalse(any("APPROX_PERCENTILE" in sql for sql in live_sql))
        self.assertFalse(any("ALLOCATED_CREDITS" in sql for sql in live_sql))
        self.assertFalse(any("ILIKE 'CREATE%'" in sql or "ILIKE 'ALTER%'" in sql for sql in live_sql))
        self.assertFalse(any("TASK_HISTORY" in sql for sql in live_sql))
        self.assertFalse(any("DATEADD('HOUR', -168" in sql for sql in live_sql))

        source_modes = {
            str(row.get("Source")): str(row.get("Mode"))
            for _, row in data["_source_modes"].iterrows()
        }
        self.assertEqual(source_modes["credits"], "Limited live fallback")
        self.assertEqual(source_modes["failed_queries"], "Limited live fallback")
        self.assertEqual(source_modes["failed_logins"], "Limited live fallback")
        self.assertEqual(source_modes["summary"], "Live fallback deferred")
        self.assertEqual(source_modes["cost_drivers"], "Live fallback deferred")
        self.assertEqual(source_modes["warehouse_pressure"], "Live fallback deferred")
        self.assertEqual(source_modes["object_changes"], "Live fallback deferred")
        self.assertEqual(source_modes["task_failures"], "Live fallback deferred")

    def test_dba_control_room_source_health_flags_scope_stale_and_deferred_sources(self):
        data = {
            "summary": pd.DataFrame({"FAILED_QUERIES": [2]}),
            "credits": pd.DataFrame({"PERIOD_CREDITS": [4.2]}),
            "task_sla_cost": pd.DataFrame(),
            "procedure_sla_cost": pd.DataFrame(),
            "warehouse_pressure": pd.DataFrame({"WAREHOUSE_NAME": ["WH_ALFA_LOAD"]}),
            "failed_queries": pd.DataFrame(),
            "cortex_summary": pd.DataFrame(),
            "cortex_summary_error": pd.DataFrame({"ERROR": ["Cortex mart missing"]}),
            "_source_modes": pd.DataFrame([
                {"Source": "summary", "Mode": "Fast summary"},
                {"Source": "credits", "Mode": "Fast summary"},
                {"Source": "task_sla_history", "Mode": "Deferred"},
                {"Source": "procedure_sla", "Mode": "Deferred"},
                {"Source": "warehouse_pressure", "Mode": "Live fallback", "Message": "fast summary unavailable"},
                {"Source": "cortex_cost", "Mode": "Fast summary unavailable"},
            ]),
        }
        state = {
            "global_warehouse": "WH_ALFA",
            "global_user": "",
            "global_role": "",
            "global_database": "ALFA_EDW_PROD",
            "global_start_date": "",
            "global_end_date": "",
        }
        state["dba_control_room_meta"] = _dba_control_scope_meta(
            "ALFA",
            "PROD",
            24,
            5000,
            False,
            False,
            state=state,
        )

        rows = _dba_control_source_health_rows(
            data,
            state,
            company="ALFA",
            environment="PROD",
            lookback_hours=24,
            cortex_budget_usd=5250,
            include_deep_evidence=False,
            allow_live_fallback=False,
        )
        by_surface = {row["SURFACE"]: row for _, row in rows.iterrows()}

        self.assertEqual(by_surface["summary"]["STATE"], "Stale")
        self.assertEqual(by_surface["credits"]["MODE"], "Fast summary")
        self.assertEqual(by_surface["task_sla_cost"]["STATE"], "Deferred")
        self.assertEqual(by_surface["procedure_sla_cost"]["STATE"], "Deferred")
        self.assertEqual(by_surface["warehouse_pressure"]["MODE"], "Live fallback")
        self.assertEqual(by_surface["cortex_summary"]["STATE"], "Unavailable")
        self.assertIn("Reload DBA Control Room", by_surface["summary"]["NEXT_ACTION"])

    def test_dba_evidence_freshness_gate_blocks_unavailable_core_sources(self):
        source_health = pd.DataFrame(
            [
                {
                    "SURFACE": "summary",
                    "STATE": "Unavailable",
                    "MODE": "Fast summary unavailable",
                    "ROWS": 0,
                    "SCOPE": "ALFA / PROD / 24h",
                    "MESSAGE": "summary mart missing",
                    "NEXT_ACTION": "Refresh summary mart.",
                },
                {
                    "SURFACE": "credits",
                    "STATE": "Stale",
                    "MODE": "Fast summary",
                    "ROWS": 1,
                    "SCOPE": "ALFA / PROD / 24h",
                    "MESSAGE": "",
                    "NEXT_ACTION": "Reload DBA Control Room.",
                },
                {
                    "SURFACE": "task_sla_cost",
                    "STATE": "Deferred",
                    "MODE": "Deferred",
                    "ROWS": 0,
                    "SCOPE": "ALFA / PROD / 24h",
                    "MESSAGE": "",
                    "NEXT_ACTION": "Load deep task evidence only when needed.",
                },
                {
                    "SURFACE": "cortex_summary",
                    "STATE": "Unavailable",
                    "MODE": "Fast summary unavailable",
                    "ROWS": 0,
                    "SCOPE": "ALFA / PROD / 24h",
                    "MESSAGE": "cortex mart missing",
                    "NEXT_ACTION": "Refresh cortex mart.",
                },
            ]
        )
        data = {
            "schema_migration_status": pd.DataFrame([{
                "COMPONENT": "Setup ledger",
                "OBJECT_NAME": "OVERWATCH_SCHEMA_MIGRATION",
                "OBJECT_TYPE": "TABLE",
                "OBJECT_STATE": "Present",
                "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
                "DEPLOYED_VERSION": OVERWATCH_SCHEMA_VERSION,
                "MIGRATION_STATE": "Ready",
                "NEXT_ACTION": "No action.",
            }]),
            "task_failures": pd.DataFrame(),
            "task_sla_cost": pd.DataFrame(),
            "task_latest_runs": pd.DataFrame(),
        }

        source_summary, source_gate = _build_evidence_freshness_gate(source_health)
        release_summary, release_gate = _build_auto_release_readiness_gate(data, source_health)
        by_surface = {row["SURFACE"]: row for _, row in source_gate.iterrows()}
        by_gate = {row["GATE"]: row for _, row in release_gate.iterrows()}

        self.assertEqual(source_summary["blocked"], 1)
        self.assertEqual(source_summary["review"], 2)
        self.assertEqual(source_summary["deferred"], 1)
        self.assertEqual(by_surface["summary"]["GATE_STATE"], "Blocked")
        self.assertEqual(by_surface["summary"]["ROUTE"], "DBA Control Room")
        self.assertEqual(by_surface["credits"]["GATE_STATE"], "Review")
        self.assertEqual(by_surface["task_sla_cost"]["GATE_STATE"], "Deferred")
        self.assertEqual(by_surface["cortex_summary"]["ROUTE"], "Cost & Contract")
        self.assertEqual(by_gate["Telemetry status"]["STATE"], "Blocked")
        self.assertGreaterEqual(release_summary["blocked"], 1)

    def test_dba_control_room_loads_schema_migration_status_without_live_account_scan(self):
        called_sql = []

        def fake_run_query(sql, **_kwargs):
            sql_upper = str(sql).upper()
            called_sql.append(sql_upper)
            if "REQUIRED_OBJECTS AS" in sql_upper and "OVERWATCH_SCHEMA_MIGRATION" in sql_upper:
                return pd.DataFrame([{
                    "COMPONENT": "Alert delivery",
                    "OBJECT_NAME": "OVERWATCH_ANNOTATIONS",
                    "OBJECT_TYPE": "TABLE",
                    "OBJECT_STATE": "Present",
                    "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
                    "DEPLOYED_VERSION": OVERWATCH_SCHEMA_VERSION,
                    "MIGRATION_STATE": "Ready",
                    "NEXT_ACTION": "No action.",
                }])
            raise RuntimeError("mart unavailable")

        with patch("sections.dba_control_room.data.run_query", side_effect=fake_run_query), patch(
            "sections.dba_control_room.data.load_action_queue",
            return_value=pd.DataFrame(),
        ):
            data = _load_control_room(
                session=None,
                company="ALFA",
                credit_price=3.68,
                lookback_hours=24,
                cortex_budget_usd=5000,
            )

        self.assertFalse(data["schema_migration_status"].empty)
        self.assertTrue(any("OVERWATCH_SCHEMA_MIGRATION" in sql for sql in called_sql))
        self.assertFalse(any("SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY" in sql for sql in called_sql))

    def test_auto_release_gate_builds_task_root_cause_timeline(self):
        data = {
            "schema_migration_status": pd.DataFrame([{
                "COMPONENT": "Alert delivery",
                "OBJECT_NAME": "OVERWATCH_ANNOTATIONS",
                "OBJECT_TYPE": "TABLE",
                "OBJECT_STATE": "Missing",
                "REQUIRED_VERSION": OVERWATCH_SCHEMA_VERSION,
                "DEPLOYED_VERSION": "Unknown",
                "MIGRATION_STATE": "Blocked",
                "NEXT_ACTION": "Apply release remediation.",
            }]),
            "task_failures": pd.DataFrame([{
                "TASK_NAME": "OVERWATCH_ANOMALY_CHECK",
                "ROOT_TASK_NAME": "OVERWATCH_ANOMALY_CHECK",
                "FAILURES": 3,
                "LAST_FAILURE": "2026-06-04 10:00:00",
                "LAST_ERROR": "Object OVERWATCH_ANNOTATIONS does not exist or not authorized",
                "QUERY_ID": "01abc",
            }]),
            "object_changes": pd.DataFrame([{
                "START_TIME": "2026-06-04 09:45:00",
                "QUERY_TYPE": "CREATE_TABLE",
                "QUERY_PREVIEW": "CREATE TABLE OVERWATCH_ALERTS",
            }]),
            "failed_queries": pd.DataFrame([{
                "START_TIME": "2026-06-04 10:00:00",
                "QUERY_ID": "01abc",
                "ERROR_CODE": "002003",
                "ERROR_MESSAGE": "Object does not exist",
            }]),
            "task_sla_cost": pd.DataFrame(),
            "task_latest_runs": pd.DataFrame(),
        }

        summary, gate = _build_auto_release_readiness_gate(data)
        timeline = _build_task_failure_root_cause_timeline(data, company="ALFA", environment="PROD")
        exceptions = _dba_control_severity_rows(data, credit_price=3.68)

        self.assertGreaterEqual(summary["blocked"], 2)
        self.assertIn("Deployment object: OVERWATCH_ANNOTATIONS", set(gate["GATE"]))
        self.assertIn("Task failure recovery", set(gate["GATE"]))
        self.assertIn("Object/RBAC drift", set(timeline["ROOT_CAUSE_SIGNAL"]))
        self.assertIn("Yes", set(timeline["BLOCKS_RELEASE"]))
        self.assertIn("Operational status blocked", set(exceptions["Signal"]))

    def test_dba_action_brief_prioritizes_single_operator_move(self):
        exceptions = pd.DataFrame([
            {
                "Severity": "High",
                "Signal": "Queue pressure",
                "Action": "Check warehouse sizing and concurrency.",
                "Route": "Warehouse Health",
                "Workflow": "Queue pressure",
            }
        ])

        blocked = _dba_action_brief(
            {"blocked": 1, "review": 2, "not_loaded": 0},
            exceptions,
            queued_queries=734,
            failed_queries=0,
        )
        self.assertEqual(blocked["state"], "Blocked")
        self.assertEqual(blocked["target"], "DBA Control Room")
        self.assertEqual(blocked["workflow"], "Action Queue")
        self.assertIn("1 blocker", blocked["detail"])

        routed = _dba_action_brief(
            {"blocked": 0, "review": 0, "not_loaded": 0},
            exceptions,
            queued_queries=734,
            failed_queries=0,
        )
        self.assertEqual(routed["target"], "Cost & Contract")
        self.assertEqual(routed["workflow"], "Cost Recommendations")
        self.assertIn("Check warehouse sizing", routed["headline"])

        queue_only = _dba_action_brief(
            {"blocked": 0, "review": 0, "not_loaded": 0},
            pd.DataFrame(),
            queued_queries=25,
            failed_queries=0,
        )
        self.assertEqual(queue_only["target"], "Cost & Contract")
        self.assertIn("25 queued", queue_only["detail"])

    def test_dba_control_room_snapshot_is_only_available_for_unfiltered_all_environment(self):
        unfiltered = {
            "global_warehouse": "",
            "global_user": "",
            "global_role": "",
            "global_database": "",
            "global_start_date": "",
            "global_end_date": "",
        }
        filtered = dict(unfiltered)
        filtered["global_database"] = "ALFA_EDW_PROD"

        self.assertTrue(_dba_snapshot_scope_compatible("ALL", unfiltered))
        self.assertFalse(_dba_snapshot_scope_compatible("PROD", unfiltered))
        self.assertFalse(_dba_snapshot_scope_compatible("ALL", filtered))

    def test_dba_control_room_command_queue_flags_control_gaps(self):
        queue = pd.DataFrame([
            {
                "ACTION_ID": "A1",
                "CATEGORY": "Task & Procedure Reliability",
                "SEVERITY": "High",
                "ENTITY_NAME": "ALFA_EDW_DEV.PUBLIC.T_ROOT",
                "OWNER": "DBA",
                "STATUS": "New",
                "DUE_DATE": "2026-05-30",
                "PROOF_QUERY": "",
                "TICKET_ID": "",
                "APPROVER": "",
                "OWNER_APPROVAL_STATUS": "Requested",
                "RECOVERY_SLA_STATE": "Open Failure",
                "RECOVERY_EVIDENCE": "",
            },
            {
                "ACTION_ID": "A2",
                "CATEGORY": "Cost Control",
                "SEVERITY": "Medium",
                "ENTITY_NAME": "WH_LOAD",
                "OWNER": "Cost Owner",
                "STATUS": "Fixed",
                "DUE_DATE": "2026-05-29",
                "PROOF_QUERY": "SELECT 1",
            },
        ])

        command_queue = _build_command_queue(queue, today="2026-05-31")
        summary = _command_queue_summary(command_queue)

        self.assertEqual(len(command_queue), 1)
        self.assertEqual(command_queue.iloc[0]["ROUTE"], "Workload Operations")
        self.assertEqual(command_queue.iloc[0]["COMMAND_STATE"], "Escalate Overdue")
        self.assertEqual(command_queue.iloc[0]["COMMAND_EXECUTION_GATE"], "Escalate - Overdue")
        self.assertEqual(command_queue.iloc[0]["COMMAND_ROUTE_READINESS"], "Route Needed")
        self.assertEqual(command_queue.iloc[0]["ONCALL_PRIMARY"], "DBA")
        self.assertEqual(command_queue.iloc[0]["COMMAND_AUDIT_READINESS"], "Audit Gaps")
        self.assertEqual(summary["open"], 1)
        self.assertEqual(summary["overdue"], 1)
        self.assertEqual(summary["owner_gaps"], 0)
        self.assertEqual(summary["route_ready"], 0)
        self.assertGreater(summary["control_gaps"], 0)
        self.assertEqual(summary["audit_ready"], 0)

    def test_dba_control_room_command_queue_exposes_execution_gates(self):
        queue = pd.DataFrame([
            {
                "ACTION_ID": "C1",
                "CATEGORY": "Cost Control",
                "SEVERITY": "High",
                "ENTITY_NAME": "WH_ALFA_BI",
                "OWNER": "BI_PLATFORM_ROUTE",
                "STATUS": "In Progress",
                "DUE_DATE": "2026-06-02",
                "VERIFICATION_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                "TICKET_ID": "CHG-101",
                "APPROVER": "Cost owner",
                "BASELINE_VALUE": 100,
                "CURRENT_VALUE": 180,
                "OWNER_APPROVAL_STATUS": "Requested",
                "RECOVERY_SLA_STATE": "Savings Measurement Pending",
            },
            {
                "ACTION_ID": "C2",
                "CATEGORY": "Cost Control",
                "SEVERITY": "High",
                "ENTITY_NAME": "WH_ALFA_LOAD",
                "OWNER": "LOAD_PLATFORM_ROUTE",
                "ONCALL_PRIMARY": "Load Platform Queue",
                "STATUS": "Acknowledged",
                "DUE_DATE": "2026-06-02",
                "VERIFICATION_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                "TICKET_ID": "CHG-102",
                "APPROVER": "Cost owner",
                "BASELINE_VALUE": 200,
                "CURRENT_VALUE": 260,
                "OWNER_APPROVAL_STATUS": "Approved",
                "RECOVERY_SLA_STATE": "Savings Measurement Pending",
            },
        ])

        command_queue = _build_command_queue(queue, today="2026-05-31")
        summary = _command_queue_summary(command_queue)
        by_route = {row["ROUTE"]: row for _, row in _command_queue_route_readiness(command_queue).iterrows()}
        by_id = {row["ACTION_ID"]: row for _, row in command_queue.iterrows()}

        self.assertEqual(by_id["C1"]["COMMAND_EXECUTION_GATE"], "Blocked - Metadata")
        self.assertEqual(by_id["C1"]["COMMAND_EVIDENCE_REQUIRED"], "On-call route; Review status")
        self.assertEqual(by_id["C1"]["COMMAND_ROUTE_READINESS"], "Route Needed")
        self.assertEqual(by_id["C2"]["COMMAND_EXECUTION_GATE"], "Blocked - Metadata")
        self.assertEqual(by_id["C2"]["COMMAND_AUDIT_READINESS"], "Audit Gaps")
        self.assertEqual(summary["approval_blocks"], 0)
        self.assertEqual(summary["execution_ready"], 0)
        self.assertEqual(summary["audit_ready"], 0)
        self.assertEqual(summary["metadata_blocks"], 2)
        self.assertEqual(by_route["Cost & Contract"]["APPROVAL_BLOCKS"], 0)
        self.assertEqual(by_route["Cost & Contract"]["EXECUTION_READY"], 0)

    def test_dba_control_room_closure_rollup_keeps_fixed_items_auditable(self):
        queue = pd.DataFrame([
            {
                "ACTION_ID": "S1",
                "SOURCE": "Security Posture - Access Review",
                "CATEGORY": "Security Access Review",
                "SEVERITY": "High",
                "ENTITY_NAME": "ROLE_PAYROLL_ADMIN",
                "OWNER": "DBA",
                "STATUS": "New",
                "DUE_DATE": "2026-05-29",
                "TICKET_ID": "",
                "APPROVER": "",
                "OWNER_APPROVAL_STATUS": "Requested",
                "VERIFICATION_QUERY": "",
                "RECOVERY_SLA_STATE": "Open Failure",
                "RECOVERY_EVIDENCE": "",
            },
            {
                "ACTION_ID": "A1",
                "SOURCE": "Account Health",
                "CATEGORY": "Account Health Checklist",
                "SEVERITY": "Medium",
                "ENTITY_NAME": "MFA Coverage",
                "OWNER": "Account Health Owner",
                "STATUS": "Fixed",
                "DUE_DATE": "2026-05-30",
                "TICKET_ID": "CHG-200",
                "APPROVER": "DBA Lead",
                "OWNER_APPROVAL_STATUS": "Approved",
                "VERIFICATION_QUERY": "SELECT 1",
                "VERIFICATION_STATUS": "Pending",
                "VERIFICATION_RESULT": "",
                "RECOVERY_SLA_STATE": "Recovered",
                "RECOVERY_EVIDENCE": "",
            },
            {
                "ACTION_ID": "W1",
                "SOURCE": "Warehouse Health - Efficiency",
                "CATEGORY": "Warehouse Health",
                "SEVERITY": "Low",
                "ENTITY_NAME": "WH_REPORTING",
                "OWNER": "Warehouse Owner",
                "STATUS": "Fixed",
                "DUE_DATE": "2026-05-28",
                "TICKET_ID": "CHG-201",
                "APPROVER": "Capacity Lead",
                "OWNER_APPROVAL_STATUS": "Approved",
                "VERIFICATION_QUERY": "SELECT 1",
                "VERIFICATION_STATUS": "Verified",
                "VERIFICATION_RESULT": "Post-change credits and queue pressure improved.",
                "RECOVERY_SLA_STATE": "Recovered",
                "RECOVERY_EVIDENCE": "Rollback not needed; post-change evidence retained.",
            },
        ])

        rollup = _command_queue_closure_readiness(queue, today="2026-05-31")
        by_route = {row["ROUTE"]: row for _, row in rollup.iterrows()}

        self.assertEqual(by_route["Security Monitoring"]["CLOSURE_READINESS"], "Overdue closure")
        self.assertEqual(by_route["Security Monitoring"]["OVERDUE_OPEN"], 1)
        self.assertEqual(by_route["Security Monitoring"]["OWNER_GAP_ROWS"], 1)
        self.assertEqual(by_route["Security Monitoring"]["TICKET_GAP_ROWS"], 1)
        self.assertEqual(by_route["DBA Control Room"]["CLOSURE_READINESS"], "Closed pending telemetry")
        self.assertEqual(by_route["DBA Control Room"]["FIXED_WITHOUT_VERIFICATION"], 1)
        self.assertEqual(by_route["DBA Control Room"]["RECOVERY_RISK_ROWS"], 1)
        self.assertEqual(by_route["Cost & Contract"]["CLOSURE_READINESS"], "Closed")
        self.assertEqual(by_route["Cost & Contract"]["VERIFIED_CLOSURES"], 1)
        self.assertIn("wait for telemetry", by_route["DBA Control Room"]["NEXT_CONTROL_ACTION"])

    def test_dba_control_room_operability_board_joins_scores_with_live_blockers(self):
        queue = pd.DataFrame([
            {
                "ACTION_ID": "W1",
                "CATEGORY": "Warehouse Health",
                "SEVERITY": "High",
                "ENTITY_NAME": "WH_LOAD",
                "OWNER": "DBA",
                "STATUS": "New",
                "DUE_DATE": "2026-05-29",
                "TICKET_ID": "",
                "APPROVER": "",
                "OWNER_APPROVAL_STATUS": "Requested",
                "VERIFICATION_QUERY": "",
                "RECOVERY_SLA_STATE": "Open Failure",
                "RECOVERY_EVIDENCE": "",
            },
            {
                "ACTION_ID": "C1",
                "CATEGORY": "Cost Control",
                "SEVERITY": "High",
                "ENTITY_NAME": "WH_BI",
                "OWNER": "BI_PLATFORM_OWNER",
                "STATUS": "In Progress",
                "DUE_DATE": "2026-06-02",
                "TICKET_ID": "CHG-101",
                "APPROVER": "Cost owner",
                "OWNER_APPROVAL_STATUS": "Approved",
                "VERIFICATION_QUERY": "SELECT 1",
                "BASELINE_VALUE": 100,
                "CURRENT_VALUE": 80,
            },
        ])
        command_queue = _build_command_queue(queue, today="2026-05-31")
        closure = _command_queue_closure_readiness(queue, today="2026-05-31")
        section_rows = pd.DataFrame([
            {
                "SECTION": "Warehouse Health",
                "SCORE": 91.9,
                "LABEL": "Near Target",
                "LOWEST_COMPONENT": "Performance & Mart Strategy",
                "LOWEST_SCORE": 86,
                "CAP_DRIVERS": "none",
                "NEXT_95_MOVE": "Persist warehouse settings change audit.",
            },
            {
                "SECTION": "Cost & Contract",
                "SCORE": 96.2,
                "LABEL": "95 Target",
                "LOWEST_COMPONENT": "Performance & Mart Strategy",
                "LOWEST_SCORE": 94,
                "CAP_DRIVERS": "none",
                "NEXT_95_MOVE": "Maintain evidence.",
            },
            {
                "SECTION": "Security Posture",
                "SCORE": 92.6,
                "LABEL": "Near Target",
                "LOWEST_COMPONENT": "Performance & Mart Strategy",
                "LOWEST_SCORE": 85,
                "CAP_DRIVERS": "none",
                "NEXT_95_MOVE": "Connect IAM approvals.",
            },
        ])

        board = _dba_section_operability_board(section_rows, command_queue, closure)
        by_section = {row["SECTION"]: row for _, row in board.iterrows()}

        self.assertEqual(by_section["Cost & Contract"]["OPERABILITY_STATE"], "Escalate Now")
        self.assertEqual(by_section["Cost & Contract"]["OVERDUE"], 1)
        self.assertGreaterEqual(by_section["Cost & Contract"]["CLOSURE_BLOCKERS"], 1)
        self.assertIn("Escalate overdue", by_section["Cost & Contract"]["NEXT_CONTROL_ACTION"])
        self.assertIn("rollback SQL", by_section["Cost & Contract"]["PROOF_REQUIRED"])
        self.assertEqual(by_section["Cost & Contract"]["EXECUTION_READY"], 0)
        self.assertEqual(by_section["Security Monitoring"]["OPERABILITY_STATE"], "Build Toward 95")
        self.assertIn("Connect IAM", by_section["Security Monitoring"]["NEXT_CONTROL_ACTION"])
        self.assertIn("least-privilege", by_section["Security Monitoring"]["PROOF_REQUIRED"])

    def test_dba_operations_priority_index_ranks_hot_route_first(self):
        raw_queue = pd.DataFrame([
            {
                "ACTION_ID": "W1",
                "CATEGORY": "Warehouse Health",
                "SEVERITY": "High",
                "ENTITY_NAME": "BI_COMPUTE_WH",
                "OWNER": "Warehouse Owner",
                "STATUS": "New",
                "DUE_DATE": "2026-05-29",
                "TICKET_ID": "",
                "APPROVER": "",
                "OWNER_APPROVAL_STATUS": "Requested",
                "VERIFICATION_QUERY": "",
                "RECOVERY_SLA_STATE": "Open Failure",
                "RECOVERY_EVIDENCE": "",
            },
            {
                "ACTION_ID": "C1",
                "CATEGORY": "Cost Control",
                "SEVERITY": "Medium",
                "ENTITY_NAME": "WH_BATCH",
                "OWNER": "Cost Owner",
                "STATUS": "In Progress",
                "DUE_DATE": "2026-06-03",
                "TICKET_ID": "CHG-101",
                "APPROVER": "Cost owner",
                "OWNER_APPROVAL_STATUS": "Approved",
                "VERIFICATION_QUERY": "SELECT 1",
            },
        ])
        exceptions = pd.DataFrame([
            {
                "Severity": "High",
                "Signal": "Queue or warehouse pressure",
                "Evidence": "80 queued queries; 1 pressured warehouse",
                "Action": "Check warehouse sizing and concurrency pressure.",
                "Route": "Warehouse Health",
                "Workflow": "",
            }
        ])
        command_queue = _build_command_queue(raw_queue, today="2026-05-31")
        closure = _command_queue_closure_readiness(raw_queue, today="2026-05-31")
        section_rows = pd.DataFrame([
            {
                "SECTION": "Warehouse Health",
                "SCORE": 95.2,
                "LABEL": "95 Target",
                "LOWEST_COMPONENT": "DBA Workflow UX",
                "LOWEST_SCORE": 94,
                "CAP_DRIVERS": "none",
                "NEXT_95_MOVE": "Persist warehouse operating evidence.",
            },
            {
                "SECTION": "Cost & Contract",
                "SCORE": 97.6,
                "LABEL": "95 Target",
                "LOWEST_COMPONENT": "Workflow UX",
                "LOWEST_SCORE": 97,
                "CAP_DRIVERS": "none",
                "NEXT_95_MOVE": "Maintain cost evidence.",
            },
        ])
        section_board = _dba_section_operability_board(section_rows, command_queue, closure)
        incident_board = _dba_incident_board(exceptions, command_queue, closure, pd.DataFrame())

        priority_index = _dba_operations_priority_index(
            section_board,
            incident_board,
            command_queue,
            pd.DataFrame(),
        )
        top = priority_index.iloc[0]

        self.assertEqual(top["SECTION"], "Cost & Contract")
        self.assertEqual(top["OPERATIONS_PRIORITY_STATE"], "Contain Now")
        self.assertEqual(len(priority_index), 1)
        self.assertIn("Queue or warehouse pressure", top["WHY_NOW"])
        self.assertIn("Stabilize", top["FIRST_MOVE"])
        self.assertIn("rollback SQL", top["PROOF_REQUIRED"])

    def test_dba_operator_runbook_builds_route_specific_steps(self):
        priority_index = pd.DataFrame([
            {
                "SECTION": "Warehouse Health",
                "OPERATIONS_PRIORITY_STATE": "Contain Now",
                "PRIORITY_SCORE": 88.5,
                "WHY_NOW": "Queue or warehouse pressure; 1 overdue",
                "FIRST_MOVE": "Stabilize queue/spill pressure first.",
                "PROOF_REQUIRED": "capacity evidence, owner approval, rollback SQL",
            }
        ])

        plan = _dba_operator_runbook(
            priority_index,
            company="ALFA",
            environment="PROD",
            lookback_hours=24,
            generated_at=datetime(2026, 6, 1, 17, 30),
        )
        markdown = _build_dba_operator_runbook_markdown(
            plan,
            company="ALFA",
            environment="PROD",
            lookback_hours=24,
        )

        self.assertEqual(len(plan), 6)
        self.assertEqual(plan.iloc[0]["RUNBOOK_ID"], "DBA-RUNBOOK-202606011730")
        self.assertEqual(plan.iloc[0]["RUNBOOK_MODE"], "Advisory Only")
        self.assertEqual(plan.iloc[0]["RUNBOOK_STEP"], "Telemetry Check")
        self.assertIn("Telemetry current", plan["GO_NO_GO_GATE"].tolist())
        self.assertIn("Advisory only", plan["GO_NO_GO_GATE"].tolist())
        self.assertTrue(plan["PROOF_SQL"].str.contains("WAREHOUSE_METERING_HISTORY|QUERY_HISTORY", regex=True).any())
        self.assertIn("OVERWATCH DBA Operator Runbook", markdown)
        self.assertIn("Mode: Review-only guidance", markdown)
        self.assertIn("Rollback or Escalate", markdown)

    def test_dba_section_proof_required_names_section_evidence_contracts(self):
        self.assertIn("release-note/rollback", _dba_section_proof_required("Change & Drift"))
        self.assertIn("impact telemetry", _dba_section_proof_required("Cost & Contract"))
        self.assertIn("email status", _dba_section_proof_required("Alert Center"))

    def test_dba_incident_board_groups_signals_into_containment_lanes(self):
        exceptions = pd.DataFrame([
            {
                "Severity": "High",
                "Signal": "Queue or warehouse pressure",
                "Evidence": "80 queued queries; 1 pressured warehouse",
                "Action": "Check warehouse sizing and concurrency pressure.",
                "Route": "Warehouse Health",
                "Workflow": "",
            },
            {
                "Severity": "Medium",
                "Signal": "Object or grant changes",
                "Evidence": "6 recent object/access changes",
                "Action": "Validate change windows.",
                "Route": "Change & Drift",
                "Workflow": "Object and access changes",
            },
        ])
        raw_queue = pd.DataFrame([
            {
                "ACTION_ID": "W1",
                "CATEGORY": "Warehouse Health",
                "SEVERITY": "High",
                "ENTITY_NAME": "BI_COMPUTE_WH",
                "OWNER": "DBA",
                "STATUS": "New",
                "DUE_DATE": "2026-05-29",
                "TICKET_ID": "",
                "APPROVER": "",
                "OWNER_APPROVAL_STATUS": "Requested",
                "VERIFICATION_QUERY": "",
                "RECOVERY_SLA_STATE": "Open Failure",
                "RECOVERY_EVIDENCE": "",
            }
        ])
        command_queue = _build_command_queue(raw_queue, today="2026-05-31")
        closure = _command_queue_closure_readiness(raw_queue, today="2026-05-31")
        source_health = pd.DataFrame([
            {
                "SURFACE": "Task SLA / Cost",
                "STATE": "Unavailable",
                "ROWS": 0,
                "SCOPE": "ALFA/PROD",
                "NEXT_ACTION": "Refresh mart grants before relying on this surface.",
            }
        ])

        board = _dba_incident_board(exceptions, command_queue, closure, source_health)
        by_type = {row["INCIDENT_TYPE"]: row for _, row in board.iterrows()}

        self.assertEqual(by_type["Warehouse Capacity"]["STATUS"], "Containment Required")
        self.assertIn("Cost & Contract", by_type["Warehouse Capacity"]["AFFECTED_ROUTES"])
        self.assertIn("Stabilize queue", by_type["Warehouse Capacity"]["CONTAINMENT_ACTION"])
        self.assertIn("Contain", by_type["Warehouse Capacity"]["SLA_TARGET"])
        self.assertIn("Data Quality", by_type)
        self.assertEqual(by_type["Data Quality"]["STATUS"], "Telemetry Refresh Required")

    def test_dba_incident_markdown_is_containment_ready(self):
        board = pd.DataFrame([
            {
                "INCIDENT_ID": "DBA-01",
                "INCIDENT_TYPE": "Warehouse Capacity",
                "SEVERITY": "High",
                "STATUS": "Containment Required",
                "AFFECTED_ROUTES": "Warehouse Health",
                "SIGNALS": "Queue or warehouse pressure",
                "EVIDENCE": "80 queued queries",
                "OPEN_ACTIONS": 1,
                "OVERDUE": 1,
                "PROOF_BLOCKS": 3,
                "SOURCE_ISSUES": 0,
                "CONTAINMENT_ACTION": "Stabilize queue/spill pressure first.",
                "INVESTIGATION_PATH": "Warehouse Health",
                "SLA_TARGET": "Contain within 30 minutes.",
                "PROOF_REQUIRED": "capacity evidence, owner approval, rollback SQL",
            }
        ])

        markdown = _build_dba_incident_markdown(
            board,
            company="ALFA",
            environment="PROD",
            lookback_hours=24,
            source_mode="Fast triage summary",
        )

        self.assertIn("# OVERWATCH DBA Incident Detail", markdown)
        self.assertIn("Containment Required", markdown)
        self.assertIn("Operating Rules", markdown)
        self.assertIn("Refresh stale or unavailable telemetry", markdown)
        self.assertNotIn("owner", markdown.lower())
        self.assertNotIn("proof", markdown.lower())

    def test_dba_shift_handoff_combines_watch_queue_closure_and_source_health(self):
        exceptions = pd.DataFrame([
            {
                "Severity": "High",
                "Signal": "Queue or warehouse pressure",
                "Evidence": "80 queued queries; 1 pressured warehouse",
                "Action": "Open Cost & Contract and validate capacity pressure.",
                "Route": "Cost & Contract",
                "Workflow": "",
            }
        ])
        raw_queue = pd.DataFrame([
            {
                "ACTION_ID": "W1",
                "CATEGORY": "Warehouse Health",
                "SEVERITY": "High",
                "ENTITY_NAME": "BI_COMPUTE_WH",
                "OWNER": "DBA",
                "STATUS": "New",
                "DUE_DATE": "2026-05-29",
                "TICKET_ID": "",
                "APPROVER": "",
                "OWNER_APPROVAL_STATUS": "Requested",
                "VERIFICATION_QUERY": "",
                "RECOVERY_SLA_STATE": "Open Failure",
                "RECOVERY_EVIDENCE": "",
            }
        ])
        command_queue = _build_command_queue(raw_queue, today="2026-05-31")
        closure = _command_queue_closure_readiness(raw_queue, today="2026-05-31")
        source_health = pd.DataFrame([
            {
                "SURFACE": "Task SLA / Cost",
                "STATE": "Unavailable",
                "ROWS": 0,
                "SCOPE": "ALFA/PROD",
                "NEXT_ACTION": "Refresh mart grants before relying on this surface.",
            }
        ])

        advisor_rows = pd.DataFrame([{
            "SOURCE_SURFACE": "Cost Advisor",
            "SEVERITY": "High",
            "SIGNAL": "Idle warehouse",
            "ENTITY": "COMPUTE_WH",
            "ROUTE": "Cost & Contract",
            "NEXT_ACTION": "Review suspend setting.",
            "TELEMETRY_BASIS": "metering and warehouse history",
            "EST_MONTHLY_SAVINGS_USD": 840,
            "VALUE_AT_RISK_USD": 0,
            "DETAIL": "Idle 12 hours.",
            "PRIORITY_RANK": 1,
        }])

        handoff = _dba_handoff_rows(exceptions, command_queue, closure, source_health, advisor_rows)
        states = set(handoff["STATE"].astype(str))

        self.assertIn("High Exception", states)
        self.assertIn("High Advisor", states)
        self.assertIn("Escalate Overdue", states)
        self.assertIn("Overdue closure", states)
        self.assertIn("Unavailable", states)
        self.assertIn("Cost Advisor", set(handoff["SOURCE"].astype(str)))
        self.assertTrue(handoff["PROOF_REQUIRED"].astype(str).str.contains("telemetry", case=False).any())

    def test_dba_shift_handoff_markdown_is_email_ready(self):
        handoff = pd.DataFrame([
            {
                "STATE": "Overdue closure",
                "LANE": "Warehouse Health",
                "EVIDENCE": "1 open; 1 overdue; 0 fixed without verification",
                "OWNER_OR_ROUTE": "DBA",
                "NEXT_ACTION": "Escalate overdue work.",
                "PROOF_REQUIRED": "owner, ticket, approval, verification",
            }
        ])

        markdown = _build_dba_shift_handoff_markdown(
            handoff,
            company="ALFA",
            environment="PROD",
            lookback_hours=24,
            source_mode="Fast triage summary",
        )

        self.assertIn("# OVERWATCH DBA Shift Handoff", markdown)
        self.assertIn("Scope: ALFA / PROD", markdown)
        self.assertIn("Overdue closure", markdown)
        self.assertIn("Closure Standard", markdown)

    def test_dba_escalation_packet_merges_owner_routes_from_loaded_evidence(self):
        priority_index = pd.DataFrame([
            {
                "SECTION": "Warehouse Health",
                "OPERATIONS_PRIORITY_STATE": "Route Review",
                "PRIORITY_SCORE": 62,
                "WHY_NOW": "2 telemetry blockers",
                "WORST_SIGNAL": "Warehouse guardrail review",
                "FIRST_MOVE": "Review warehouse owner route.",
                "PROOF_REQUIRED": "capacity telemetry, route review, rollback SQL",
            }
        ])
        incident_board = pd.DataFrame([
            {
                "INCIDENT_ID": "DBA-01",
                "INCIDENT_TYPE": "Warehouse Capacity",
                "SEVERITY": "High",
                "STATUS": "Containment Required",
                "AFFECTED_ROUTES": "Cost & Contract",
                "SIGNALS": "Queue or warehouse pressure",
                "CONTAINMENT_ACTION": "Stabilize queue/spill pressure first.",
                "SLA_TARGET": "Contain within 30 minutes.",
                "PROOF_REQUIRED": "capacity telemetry, route review, rollback SQL",
                "INVESTIGATION_PATH": "Warehouse Health",
            }
        ])
        handoff = pd.DataFrame([
            {
                "PRIORITY_RANK": 1,
                "LANE": "Operations Detail",
                "STATE": "Unavailable",
                "EVIDENCE": "Task SLA / Cost unavailable",
                "OWNER_OR_ROUTE": "DBA / Platform",
                "NEXT_ACTION": "Refresh mart grants before relying on this surface.",
                "PROOF_REQUIRED": "current telemetry status",
                "SOURCE": "Operations Detail",
            }
        ])
        release_gate = pd.DataFrame([
            {
                "GATE": "Deployment object: OVERWATCH_ANNOTATIONS",
                "STATE": "Blocked",
                "SEVERITY": "Critical",
                "EVIDENCE": "OVERWATCH_ANNOTATIONS missing",
                "NEXT_ACTION": "Apply release remediation DDL.",
                "ROUTE": "Change & Drift",
                "WORKFLOW": "Operations Detail",
                "PROOF_REQUIRED": "object status, rollback SQL, task retry telemetry",
            }
        ])

        packet = _dba_escalation_packet(
            priority_index,
            incident_board,
            handoff,
            release_gate,
            company="ALFA",
            environment="PROD",
            lookback_hours=24,
        )
        by_route = {row["ROUTE"]: row for _, row in packet.iterrows()}

        self.assertEqual(packet.iloc[0]["ROUTE"], "Workload Operations")
        self.assertEqual(by_route["Workload Operations"]["ESCALATION_LEVEL"], "Escalate Now")
        self.assertIn("No-Go", by_route["Workload Operations"]["GO_NO_GO"])
        self.assertIn("Workload route", by_route["Workload Operations"]["OWNER_ROUTE"])
        self.assertEqual(by_route["Cost & Contract"]["ESCALATION_LEVEL"], "Escalate Now")
        self.assertIn("Warehouse route", by_route["Cost & Contract"]["OWNER_ROUTE"])
        self.assertIn("Incident Detail", by_route["Cost & Contract"]["SOURCE_SIGNALS"])
        self.assertIn("Stabilize queue", by_route["Cost & Contract"]["FIRST_MOVE"])
        self.assertIn("Go only", by_route["Operations Detail"]["GO_NO_GO"])
        self.assertTrue(packet["AUTO_GENERATED"].eq("Yes").all())

    def test_dba_escalation_packet_markdown_is_owner_ready(self):
        packet = pd.DataFrame([
            {
                "ESCALATION_ID": "ESC-01",
                "ESCALATION_LEVEL": "Escalate Now",
                "ROUTE": "Change & Drift",
                "OWNER_ROUTE": "Change route / DBA change reviewer",
                "WHY_NOW": "Operational status blocked by missing deployment object.",
                "FIRST_MOVE": "Apply release remediation DDL.",
                "GO_NO_GO": "No-Go until blocker proof is current.",
                "PROOF_REQUIRED": "object status, rollback SQL, task retry telemetry",
            }
        ])

        markdown = _build_dba_escalation_packet_markdown(
            packet,
            company="ALFA",
            environment="PROD",
            lookback_hours=24,
        )

        self.assertIn("# OVERWATCH DBA Escalation Packet", markdown)
        self.assertIn("Mode: Auto-generated from loaded OVERWATCH telemetry", markdown)
        self.assertIn("ESC-01", markdown)
        self.assertIn("No-Go", markdown)
        self.assertIn("Change route / DBA change reviewer", markdown)
        self.assertNotIn("owner", markdown.lower())
        self.assertNotIn("proof", markdown.lower())
        self.assertNotIn("ddl", markdown.lower())
        self.assertIn("Do not execute state-changing DBA actions", markdown)

    def test_dba_morning_brief_prioritizes_no_go_and_owner_proof(self):
        priority_index = pd.DataFrame([
            {
                "SECTION": "Warehouse Health",
                "OPERATIONS_PRIORITY_STATE": "Route Review",
                "PRIORITY_SCORE": 62,
                "WHY_NOW": "2 telemetry blockers",
                "WORST_SIGNAL": "Warehouse guardrail review",
                "FIRST_MOVE": "Review warehouse owner route.",
                "PROOF_REQUIRED": "capacity telemetry, route review, rollback SQL",
            }
        ])
        packet = pd.DataFrame([
            {
                "ESCALATION_ID": "ESC-01",
                "ESCALATION_LEVEL": "Escalate Now",
                "ROUTE": "Change & Drift",
                "OWNER_ROUTE": "Change route / DBA change reviewer",
                "PRIORITY_SCORE": 99,
                "STATE": "Operational Status Blocked",
                "WHY_NOW": "OVERWATCH_ANNOTATIONS missing",
                "FIRST_MOVE": "Apply release remediation DDL.",
                "GO_NO_GO": "No-Go until blocker proof is current.",
                "PROOF_REQUIRED": "object status, rollback SQL, task retry telemetry",
                "SOURCE_SIGNALS": "Operational Status: Deployment object",
            }
        ])
        handoff = pd.DataFrame([
            {
                "PRIORITY_RANK": 1,
                "LANE": "Operations Detail",
                "STATE": "Unavailable",
                "EVIDENCE": "Task SLA / Cost unavailable",
                "OWNER_OR_ROUTE": "DBA / Platform",
                "NEXT_ACTION": "Refresh mart grants before relying on this surface.",
                "PROOF_REQUIRED": "current telemetry status",
                "SOURCE": "Operations Detail",
            }
        ])

        brief = _dba_morning_brief_rows(priority_index, packet, handoff, max_rows=3)
        markdown = _build_dba_morning_brief_markdown(
            brief,
            company="ALFA",
            environment="PROD",
            lookback_hours=24,
        )

        self.assertEqual(brief.iloc[0]["ROUTE"], "Change & Drift")
        self.assertEqual(brief.iloc[0]["STATE"], "Escalate Now")
        self.assertEqual(brief.iloc[0]["MORNING_DECISION"], "No-Go / contain now")
        self.assertEqual(brief.iloc[0]["SLA_CLOCK"], "15 min containment; 30 min route update")
        self.assertEqual(brief.iloc[0]["OWNER_PROOF_STATE"], "Route/telemetry named")
        self.assertIn("No-Go", brief.iloc[0]["GO_NO_GO"])
        self.assertIn("object status", brief.iloc[0]["PROOF_REQUIRED"])
        self.assertIn("execution, rollback, and telemetry", brief.iloc[0]["ROUTE_ACTION"])
        self.assertIn("Do not release", brief.iloc[0]["STOP_RULE"])
        self.assertIn("Warehouse Health", set(brief["ROUTE"]))
        detail_view = _dba_morning_brief_detail_view(brief)
        self.assertEqual(len(detail_view.columns), len(set(detail_view.columns)))
        self.assertIn("ROUTE_TELEMETRY_STATE", detail_view.columns)
        self.assertIn("ESCALATION_ROUTE", detail_view.columns)
        self.assertNotIn("OWNER_PROOF_STATE", detail_view.columns)
        self.assertIn("# OVERWATCH DBA Daily Brief", markdown)
        self.assertIn("No irreversible DBA action", markdown)
        self.assertIn("Decision: No-Go / contain now", markdown)
        self.assertIn("SLA: 15 min containment", markdown)

    def test_dba_morning_decision_contract_classifies_operating_rows(self):
        no_go = _dba_morning_decision_contract({
            "STATE": "Escalate Now",
            "ROUTE": "Change & Drift",
            "GO_NO_GO": "No-Go until blocker telemetry is current.",
            "OWNER_ROUTE": "Change route / DBA release reviewer",
            "PROOF_REQUIRED": "schema migration ledger, route review, rollback SQL, telemetry",
            "PRIORITY_SCORE": 99,
        })
        queue = _dba_morning_decision_contract({
            "STATE": "SLA Risk",
            "ROUTE": "Workload Operations",
            "WORKFLOW": "Contention Center",
            "OWNER_ROUTE": "DBA on-call / workload route",
            "PROOF_REQUIRED": "QUERY_HISTORY blocked seconds and current source telemetry",
            "PRIORITY_SCORE": 82,
        })
        monitor = _dba_morning_decision_contract({
            "STATE": "Monitor",
            "ROUTE": "DBA Control Room",
            "PROOF_REQUIRED": "fresh Control Room load",
            "PRIORITY_SCORE": 0,
        })

        self.assertEqual(no_go["MORNING_DECISION"], "No-Go / contain now")
        self.assertEqual(no_go["OWNER_PROOF_STATE"], "Route/telemetry named")
        self.assertIn("Do not release", no_go["STOP_RULE"])

        self.assertEqual(queue["MORNING_DECISION"], "Contain same shift")
        self.assertEqual(queue["SLA_CLOCK"], "30 min triage; same-shift mitigation")
        self.assertIn("Workload Operations / Contention Center", queue["ROUTE_ACTION"])

        self.assertEqual(monitor["MORNING_DECISION"], "Monitor")
        self.assertEqual(monitor["OWNER_PROOF_STATE"], "Route gap")

    def test_dba_morning_brief_adds_specific_workload_lanes(self):
        data = {
            "summary": pd.DataFrame([{
                "FAILED_QUERIES": 12,
                "QUEUED_QUERIES": 24,
                "REMOTE_SPILL_QUERIES": 2,
                "P95_ELAPSED_SEC": 360,
            }]),
            "warehouse_pressure": pd.DataFrame([{
                "WAREHOUSE_NAME": "WH_TRXS_QUERY",
                "QUEUED_QUERIES": 9,
                "REMOTE_SPILL_GB": 4.2,
            }]),
            "failed_queries": pd.DataFrame([{
                "QUERY_ID": "01abc",
                "WAREHOUSE_NAME": "WH_TRXS_QUERY",
                "ERROR_MESSAGE": "statement timed out",
            }]),
            "task_failures": pd.DataFrame([{
                "TASK_NAME": "LOAD_POLICY",
                "ROOT_TASK_NAME": "ROOT_LOAD_POLICY",
                "FAILURES": 2,
            }]),
            "task_sla_cost": pd.DataFrame([{
                "SIGNAL": "Long Running / SLA Risk",
                "TASK_NAME": "LOAD_POLICY",
            }]),
            "procedure_sla_cost": pd.DataFrame([{
                "SIGNAL": "Procedure Cost Regression",
                "PROCEDURE_NAME": "SP_LOAD_POLICY",
            }]),
        }
        exceptions = pd.DataFrame([{
            "ROOT_CAUSE": "Lock Contention",
            "QUERY_ID": "01blocked",
            "WAREHOUSE_NAME": "WH_TRXS_LOAD",
            "DATABASE_NAME": "PROD_DB",
            "SCHEMA_NAME": "CORE",
            "OBJECT_NAME": "FACT_POLICY",
            "BLOCKED_SEC": 185,
        }])

        workload_lanes = _dba_workload_morning_lanes(data, exceptions)
        by_workflow = {row["WORKFLOW"]: row for row in workload_lanes.to_dict("records")}

        self.assertIn("Pipeline & Task Health", by_workflow)
        self.assertIn("Contention Center", by_workflow)
        self.assertIn("Query Investigation", by_workflow)
        self.assertIn("Stored procedures", by_workflow)
        self.assertIn("Snowflake task", by_workflow["Pipeline & Task Health"]["FIRST_MOVE"])
        self.assertIn("before resizing", by_workflow["Contention Center"]["FIRST_MOVE"])
        self.assertIn("Query Investigation", by_workflow["Query Investigation"]["FIRST_MOVE"])
        self.assertIn("QUERY_HISTORY blocked seconds", by_workflow["Contention Center"]["PROOF_REQUIRED"])
        self.assertEqual(by_workflow["Contention Center"]["FOCUS_QUERY_ID"], "01blocked")
        self.assertEqual(by_workflow["Contention Center"]["FOCUS_WAREHOUSE"], "WH_TRXS_LOAD")
        self.assertEqual(by_workflow["Contention Center"]["FOCUS_OBJECT"], "PROD_DB.CORE.FACT_POLICY")

        brief = _dba_morning_brief_rows(
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            workload_lanes,
            max_rows=4,
        )
        self.assertEqual(list(brief["WORKFLOW"]), ["Pipeline & Task Health", "Contention Center", "Query Investigation", "Stored procedures"])
        self.assertEqual(list(brief["MORNING_RANK"]), [1, 2, 3, 4])
        self.assertEqual(set(brief["ROUTE"]), {"Workload Operations"})
        self.assertIn("MORNING_DECISION", brief.columns)
        for column in [
            "APPROVAL_GATE",
            "EVIDENCE_PACKAGE",
            "VERIFY_NEXT",
            "EXECUTION_BOUNDARY",
            "CLOSURE_RULE",
        ]:
            self.assertIn(column, brief.columns)
        self.assertEqual(brief.iloc[0]["MORNING_DECISION"], "No-Go / contain now")
        self.assertEqual(brief.iloc[1]["MORNING_DECISION"], "No-Go / contain now")
        self.assertIn("No-Go for warehouse resizing", brief.iloc[1]["GO_NO_GO"])
        self.assertEqual(brief.iloc[1]["FOCUS_QUERY_ID"], "01blocked")
        task_row = brief[brief["WORKFLOW"].eq("Pipeline & Task Health")].iloc[0]
        contention_row = brief[brief["WORKFLOW"].eq("Contention Center")].iloc[0]
        query_row = brief[brief["WORKFLOW"].eq("Query Investigation")].iloc[0]
        self.assertIn("Snowflake task operator", task_row["APPROVAL_GATE"])
        self.assertIn("recovery SLA", task_row["EVIDENCE_PACKAGE"])
        self.assertIn("TASK_HISTORY run succeeded", task_row["VERIFY_NEXT"])
        self.assertIn("Pipeline & Task Health guarded controls", task_row["EXECUTION_BOUNDARY"])
        self.assertIn("Query route", contention_row["APPROVAL_GATE"])
        self.assertIn("post-action Query History", contention_row["EVIDENCE_PACKAGE"])
        self.assertIn("retry/recovery", contention_row["VERIFY_NEXT"])
        self.assertIn("OVERWATCH displays action SQL only", contention_row["EXECUTION_BOUNDARY"])
        self.assertIn("operator stats", query_row["EVIDENCE_PACKAGE"])
        self.assertIn("Query Investigation is advisory", query_row["EXECUTION_BOUNDARY"])

        command_queue = _dba_morning_command_queue(brief)
        self.assertEqual(len(command_queue), 3)
        self.assertEqual(list(command_queue["MORNING_RANK"]), [1, 2, 3])
        self.assertIn("TARGET", command_queue.columns)
        self.assertIn("ACTION", command_queue.columns)
        self.assertIn("GATE", command_queue.columns)
        self.assertIn("APPROVAL_GATE", command_queue.columns)
        self.assertIn("EVIDENCE_PACKAGE", command_queue.columns)
        self.assertIn("VERIFY_NEXT", command_queue.columns)
        self.assertIn("EXECUTION_BOUNDARY", command_queue.columns)
        self.assertIn("Workload Operations / Contention Center", set(command_queue["TARGET"]))
        contention_command = command_queue[command_queue["TARGET"].eq("Workload Operations / Contention Center")].iloc[0]
        self.assertIn("query=01blocked", contention_command["FOCUS"])
        self.assertIn("warehouse=WH_TRXS_LOAD", contention_command["FOCUS"])
        self.assertIn("No-Go", contention_command["GATE"])
        self.assertIn("Query route", contention_command["APPROVAL_GATE"])
        self.assertIn("post-action Query History", contention_command["EVIDENCE_PACKAGE"])
        self.assertIn("retry/recovery", contention_command["VERIFY_NEXT"])
        self.assertIn("OVERWATCH displays action SQL only", contention_command["EXECUTION_BOUNDARY"])
        self.assertNotIn("Stored procedures", set(command_queue["TARGET"]))

        markdown = _build_dba_morning_brief_markdown(
            brief,
            company="Trexis",
            environment="PROD",
            lookback_hours=24,
        )
        self.assertIn("Workload Operations / Contention Center", markdown)
        self.assertIn("Workload Operations / Query Investigation", markdown)
        self.assertIn("No-Go for warehouse resizing", markdown)
        self.assertIn("Review gate: Query route", markdown)
        self.assertIn("Telemetry package: Save precheck result", markdown)
        self.assertIn("Confirm next: Confirm cancellation state", markdown)
        self.assertIn("Boundary: OVERWATCH displays action SQL only", markdown)
        self.assertIn("Target signal: query=01blocked", markdown)
        self.assertIn("warehouse=WH_TRXS_LOAD", markdown)
        self.assertIn("object=PROD_DB.CORE.FACT_POLICY", markdown)

    def test_dba_morning_brief_uses_task_status_feed_without_task_failure_rollup(self):
        data = {
            "summary": pd.DataFrame([{
                "FAILED_QUERIES": 0,
                "QUEUED_QUERIES": 0,
                "REMOTE_SPILL_QUERIES": 0,
                "P95_ELAPSED_SEC": 22,
            }]),
            "warehouse_pressure": pd.DataFrame(),
            "failed_queries": pd.DataFrame(),
            "task_failures": pd.DataFrame(),
            "task_sla_cost": pd.DataFrame(),
            "procedure_sla_cost": pd.DataFrame(),
            "workload_task_status": pd.DataFrame([{
                "TASK_STATUS_ROWS": 12,
                "TASK_STATUS_FAILURE_ROWS": 3,
                "TASK_STATUS_LATE_ROWS": 2,
                "TASK_STATUS_ALERT_ROWS": 4,
                "TASK_STATUS_WATCH_ROWS": 1,
                "TASK_STATUS_LAST_SEEN_AT": "2026-06-13 07:00:00",
            }]),
        }

        workload_lanes = _dba_workload_morning_lanes(data, pd.DataFrame())
        self.assertEqual(len(workload_lanes), 1)
        lane = workload_lanes.iloc[0]
        self.assertEqual(lane["WORKFLOW"], "Pipeline & Task Health")
        self.assertEqual(lane["STATE"], "Blocked Scheduler Work")
        self.assertIn("Snowflake TASK_HISTORY", lane["WHY_NOW"])
        self.assertIn("failed/blocked=3", lane["WHY_NOW"])
        self.assertIn("TASK_HISTORY", lane["FIRST_MOVE"])
        self.assertIn("downstream SLA impact", lane["FIRST_MOVE"])
        self.assertIn("review status", lane["PROOF_REQUIRED"])
        self.assertIn("No-Go for dependent loads", lane["GO_NO_GO"])
        self.assertEqual(lane["SOURCE_SIGNALS"], "Snowflake TASK_HISTORY summary")

        brief = _dba_morning_brief_rows(
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            workload_lanes,
            max_rows=1,
        )
        self.assertEqual(brief.iloc[0]["WORKFLOW"], "Pipeline & Task Health")
        self.assertEqual(brief.iloc[0]["MORNING_DECISION"], "No-Go / contain now")
        self.assertIn("Snowflake task operator", brief.iloc[0]["APPROVAL_GATE"])
        self.assertIn("recovery SLA", brief.iloc[0]["EVIDENCE_PACKAGE"])

    def test_dba_morning_route_context_seeds_contention_focus(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            _seed_dba_morning_route_context({
                "ROUTE": "Workload Operations",
                "WORKFLOW": "Contention Center",
                "FOCUS_QUERY_ID": "01blocked",
                "FOCUS_WAREHOUSE": "WH_TRXS_LOAD",
                "FOCUS_USER": "ETL_USER",
                "FOCUS_OBJECT": "PROD_DB.CORE.FACT_POLICY",
            })

            self.assertEqual(st.session_state["contention_center_view"], "Brief")
            self.assertEqual(st.session_state["contention_focus_query_id"], "01blocked")
            self.assertEqual(st.session_state["contention_live_warehouse"], "WH_TRXS_LOAD")
            self.assertEqual(st.session_state["global_warehouse"], "WH_TRXS_LOAD")
            self.assertEqual(st.session_state["global_user"], "ETL_USER")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_company_scope_does_not_default_missing_company_to_alfa(self):
        offenders = []
        for path in _python_sources():
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "COALESCE(COMPANY, 'ALFA')" in text or 'COALESCE(COMPANY, "ALFA")' in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_status_comparisons_are_case_safe_for_account_usage(self):
        bad_patterns = [
            r"(?<!UPPER\()execution_status\s*=\s*'FAILED_WITH_ERROR'",
            r"(?<!UPPER\()execution_status\s*=\s*'SUCCESS'",
            r"(?<!UPPER\()execution_status\s+IN\s*\('RUNNING','QUEUED','BLOCKED'",
        ]
        offenders = []
        for path in _python_sources():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in bad_patterns:
                if re.search(pattern, text):
                    offenders.append(f"{path.relative_to(ROOT)} :: {pattern}")
        self.assertEqual(offenders, [])

    def test_cloud_service_credit_sums_are_null_safe(self):
        offenders = []
        pattern = re.compile(r"SUM\(\s*credits_used_cloud_services\s*\)", re.IGNORECASE)
        for path in _python_sources():
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_dashboard_metric_helpers_do_not_emit_nan(self):
        df = pd.DataFrame({"VALUE": [math.nan]})
        self.assertEqual(adoption_metric(df, "VALUE"), 0.0)
        self.assertEqual(service_value(df, "VALUE"), 0.0)
        self.assertEqual(usage_first_number(df, "VALUE"), 0.0)

    def test_adoption_role_mix_exposes_visible_error_rate(self):
        live_source = inspect.getsource(_load_adoption_live).upper()
        self.assertIn("AS ERROR_RATE", live_source)
        self.assertIn("AA_ROLE_TYPE", live_source)

        mart_sql = build_mart_adoption_role_type_sql(30, "ALFA").upper()
        self.assertIn("AS ERROR_RATE", mart_sql)
        self.assertIn("SUM(FAILED_COUNT)", mart_sql)

    def test_all_company_mode_does_not_filter_mart_to_literal_all(self):
        query_summary, query_exceptions = _build_mart_root_cause_sql(7, 50, "ALL")
        change_summary, change_exceptions = _build_mart_change_drift_sql(14, "ALL")
        combined_sql = "\n".join([query_summary, query_exceptions, change_summary, change_exceptions]).upper()
        self.assertNotIn("COMPANY = 'ALL'", combined_sql)
        self.assertIn("BLOCKED_QUERIES", query_summary.upper())
        self.assertIn("LOCK CONTENTION", query_exceptions.upper())
        self.assertIn("TRANSACTION_BLOCKED_TIME", query_exceptions.upper())
        self.assertIn("SECONDS BLOCKED", query_exceptions.upper())

        security_text = "\n".join([
            (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8"),
            (APP_ROOT / "utils" / "shared_metrics.py").read_text(encoding="utf-8"),
        ])
        self.assertIn('upper() == "ALL"', security_text)
        self.assertNotIn("lh.company = '{company}'", security_text)
        self.assertNotIn("g.company = '{company}'", security_text)

    def test_environment_filter_splits_alfa_prod_and_dev_databases(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            prod_clause = get_environment_filter_clause("q.database_name", "PROD").upper()
            self.assertIn("ALFA_EDW_PROD", prod_clause)

            dev_clause = get_environment_filter_clause("q.database_name", "DEV_ALL").upper()
            for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
                self.assertIn(db_name, dev_clause)
            self.assertNotIn("ALFA_EDW_PROD", dev_clause)

            optional_clause = get_environment_filter_or_no_database_clause("q.database_name", "PROD").upper()
            self.assertIn("Q.DATABASE_NAME IS NULL", optional_clause)
            self.assertIn("ALFA_EDW_PROD", optional_clause)

            st.session_state["active_company"] = "Trexis"
            trexis_prod_clause = get_environment_filter_clause("q.database_name", "PROD").upper()
            self.assertIn("TRXS_EDW_PRD", trexis_prod_clause)
            self.assertNotIn("TRXS_EDW_DEV", trexis_prod_clause)

            st.session_state["global_environment"] = "DEV_ALL"
            trexis_dev_clause = get_environment_filter_clause("q.database_name", "DEV_ALL").upper()
            self.assertIn("TRXS_EDW_DEV", trexis_dev_clause)
            self.assertIn("TRXS_EDW_SIT", trexis_dev_clause)
            self.assertNotIn("TRXS_EDW_PRD", trexis_dev_clause)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

        case_expr = get_environment_case_expr("q.database_name").upper()
        self.assertIn("THEN 'PROD'", case_expr)
        self.assertIn("THEN 'ALFA_EDW_DEV'", case_expr)
        self.assertIn("NO DATABASE CONTEXT", case_expr)
        self.assertEqual(environment_label_for_database("ALFA_EDW_PROD"), "PROD")
        self.assertEqual(environment_label_for_database("ALFA_EDW_SAN"), "ALFA_EDW_SAN")
        self.assertEqual(environment_label_for_database("TRXS_EDW_PRD"), "PROD")
        self.assertEqual(environment_label_for_database("TRXS_EDW_SIT"), "DEV_ALL")
        self.assertEqual(environment_label_for_database(""), "No Database Context")

    def test_global_filter_clause_includes_environment_when_database_column_exists(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["global_environment"] = "PROD"
            clause = get_global_filter_clause(
                date_col="q.start_time",
                wh_col="q.warehouse_name",
                user_col="q.user_name",
                role_col="q.role_name",
                db_col="q.database_name",
            ).upper()
            self.assertIn("ALFA_EDW_PROD", clause)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_mart_environment_scope_applies_only_to_database_facts(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            st.session_state["global_environment"] = "DEV_ALL"

            db_sql = build_mart_adoption_users_db_sql(30, "ALFA").upper()
            for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
                self.assertIn(db_name, db_sql)
            self.assertNotIn("ALFA_EDW_PROD", db_sql)

            login_sql = build_mart_control_room_failed_logins_sql(24, "ALFA").upper()
            self.assertNotIn("ALFA_EDW_DEV", login_sql)
            self.assertNotIn("DATABASE_NAME", login_sql)
            self.assertNotIn("ENVIRONMENT =", login_sql)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_mart_setup_adds_explicit_environment_dimensions(self):
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()
        self.assertIn("CREATE OR REPLACE FUNCTION OVERWATCH_DATABASE_ENVIRONMENT", setup_sql)
        self.assertIn("UPPER(DATABASE_NAME) = 'ALFA_EDW_PROD'", setup_sql)
        self.assertNotIn("OVERWATCH_COMPANY_SCOPE", setup_sql)

        env_tables = [
            "FACT_QUERY_HOURLY",
            "FACT_QUERY_DETAIL_RECENT",
            "FACT_TASK_RUN",
            "DIM_TASK_SNAPSHOT",
            "DIM_PROCEDURE_SNAPSHOT",
            "FACT_PROCEDURE_RUN",
            "FACT_OBJECT_CHANGE",
            "FACT_STORAGE_DAILY",
            "DIM_TABLE_SNAPSHOT",
            "FACT_COPY_LOAD_DAILY",
            "FACT_CHARGEBACK_DAILY",
        ]
        for table_name in env_tables:
            ddl_start = setup_sql.index(f"CREATE TRANSIENT TABLE IF NOT EXISTS {table_name}")
            ddl_end = setup_sql.index(");", ddl_start)
            ddl_block = setup_sql[ddl_start:ddl_end]
            self.assertIn("ENVIRONMENT", ddl_block, table_name)

        upgrade_columns = [
            ("FACT_QUERY_HOURLY", "ENVIRONMENT"),
            ("FACT_QUERY_DETAIL_RECENT", "ENVIRONMENT"),
            ("FACT_TASK_RUN", "ENVIRONMENT"),
            ("DIM_TASK_SNAPSHOT", "ENVIRONMENT"),
            ("DIM_PROCEDURE_SNAPSHOT", "ENVIRONMENT"),
            ("FACT_PROCEDURE_RUN", "DATABASE_NAME"),
            ("FACT_PROCEDURE_RUN", "ENVIRONMENT"),
            ("FACT_PROCEDURE_RUN", "SCHEMA_NAME"),
            ("FACT_OBJECT_CHANGE", "ENVIRONMENT"),
            ("FACT_STORAGE_DAILY", "ENVIRONMENT"),
            ("FACT_GRANT_DAILY", "CREATED_ON"),
            ("DIM_TABLE_SNAPSHOT", "ENVIRONMENT"),
            ("FACT_COPY_LOAD_DAILY", "ENVIRONMENT"),
            ("FACT_CHARGEBACK_DAILY", "ENVIRONMENT"),
            ("FACT_CHARGEBACK_DAILY", "ENVIRONMENT_ROLLUP"),
        ]
        for table_name, column_name in upgrade_columns:
            self.assertIn(
                f"ALTER TABLE IF EXISTS {table_name} ADD COLUMN IF NOT EXISTS {column_name}",
                setup_sql,
            )

        proc_start = setup_sql.index("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_PROCEDURE_RUN")
        proc_end = setup_sql.index(");", proc_start)
        self.assertIn("DATABASE_NAME", setup_sql[proc_start:proc_end])
        self.assertIn("SCHEMA_NAME", setup_sql[proc_start:proc_end])
        self.assertIn("PROCEDURE DATABASE/SCHEMA CONTEXT", setup_sql)
        self.assertIn(
            "GROUP BY COMPANY, ENVIRONMENT, DATABASE_NAME, SCHEMA_NAME, PROCEDURE_NAME",
            setup_sql,
        )
        self.assertIn("COALESCE(R.SCHEMA_NAME, '') = COALESCE(B.SCHEMA_NAME, '')", setup_sql)
        self.assertIn(
            "COALESCE(DATABASE_NAME || '.' || SCHEMA_NAME || '.', DATABASE_NAME || '.', '') || PROCEDURE_NAME",
            setup_sql,
        )
        self.assertIn("AND COALESCE(SCHEMA_NAME, '''')", setup_sql)

        expected_loads = [
            "OVERWATCH_DATABASE_ENVIRONMENT(DATABASE_NAME) AS ENVIRONMENT",
            "OVERWATCH_DATABASE_ENVIRONMENT(T.TASK_DATABASE) AS ENVIRONMENT",
            "OVERWATCH_DATABASE_ENVIRONMENT(P.PROCEDURE_CATALOG) AS ENVIRONMENT",
            "OVERWATCH_DATABASE_ENVIRONMENT(H.DATABASE_NAME) AS ENVIRONMENT",
            "OVERWATCH_DATABASE_ENVIRONMENT(Q.DATABASE_NAME) AS ENVIRONMENT",
            "OVERWATCH_DATABASE_ENVIRONMENT(TABLE_CATALOG) AS ENVIRONMENT",
            "OVERWATCH_DATABASE_ENVIRONMENT(TABLE_CATALOG_NAME) AS ENVIRONMENT",
        ]
        for expected in expected_loads:
            self.assertIn(expected, setup_sql)

    def test_chargeback_mart_sql_uses_daily_snapshot(self):
        sql = build_mart_chargeback_sql(
            30,
            "ALFA",
            warehouse_contains="BI",
            user_contains="ETL",
            role_contains="ROLE",
            database_contains="ALFA_EDW_DEV",
        ).upper()

        self.assertIn("FACT_CHARGEBACK_DAILY", sql)
        self.assertNotIn("ACCOUNT_USAGE", sql)
        self.assertIn("WAREHOUSE_NAME ILIKE", sql)
        self.assertIn("USER_NAME ILIKE", sql)
        self.assertIn("ROLE_NAME ILIKE", sql)
        self.assertIn("DATABASE_NAME ILIKE", sql)
        self.assertIn("ENVIRONMENT_ROLLUP", sql)

    def test_cost_explorer_mart_sql_exposes_cost_dimensions(self):
        sql = build_mart_cost_explorer_sql(
            45,
            "ALL",
            warehouse_contains="BI",
            user_contains="ETL",
            role_contains="REPORTING",
            database_contains="EDW",
            department_contains="Claims",
        ).upper()

        self.assertIn("FACT_CHARGEBACK_DAILY", sql)
        self.assertNotIn("ACCOUNT_USAGE", sql)
        for expected in (
            "COMPANY",
            "ENVIRONMENT_ROLLUP",
            "DATABASE_NAME",
            "USER_NAME",
            "ROLE_NAME",
            "WAREHOUSE_NAME",
            "WAREHOUSE_SIZE",
            "COST_OWNER",
            "OWNER_SOURCE",
            "OWNER_EVIDENCE",
            "ALLOCATION_CONFIDENCE",
            "CHARGEBACK_READY",
            "COUNT(DISTINCT USAGE_DATE) AS ACTIVE_DAYS",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, sql)
        self.assertIn("WAREHOUSE_NAME ILIKE", sql)
        self.assertIn("USER_NAME ILIKE", sql)
        self.assertIn("ROLE_NAME ILIKE", sql)
        self.assertIn("DATABASE_NAME ILIKE", sql)
        self.assertIn("COALESCE(COST_OWNER, 'UNASSIGNED') ILIKE", sql)

    def test_cost_explorer_live_sql_uses_owner_tags_without_over_grouping_warehouse_size(self):
        sql = _cost_explorer_live_sql(14, "ALFA", "MAX(q.warehouse_size)", "Claims").upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES", sql)
        self.assertIn("COST_CENTER", sql)
        self.assertIn("DEPARTMENT", sql)
        self.assertIn("BUSINESS_OWNER", sql)
        self.assertIn("COUNT(DISTINCT Q.START_TIME::DATE) AS ACTIVE_DAYS", sql)
        self.assertIn("COALESCE(T.COST_CENTER_TAG, T.OWNER_TAG, '') ILIKE", sql)
        compact_sql = sql.replace(" ", "")
        self.assertIn("GROUPBY1,2,3,4,5,6,8,9,10,11", compact_sql)
        self.assertNotIn("GROUPBY1,2,3,4,5,6,7,8,9,10,11", compact_sql)

    def test_cost_explorer_summary_surfaces_chargeback_gaps(self):
        raw = pd.DataFrame([
            {
                "COMPANY": "ALFA",
                "ENVIRONMENT": "PROD",
                "DATABASE_NAME": "ALFA_EDW_PROD",
                "USER_NAME": "ANALYST_1",
                "ROLE_NAME": "REPORTING_ROLE",
                "WAREHOUSE_NAME": "WH_ALFA_BI",
                "WAREHOUSE_SIZE": "MEDIUM",
                "COST_OWNER": "Claims",
                "OWNER_SOURCE": "WAREHOUSE_TAG",
                "OWNER_EVIDENCE": "COST_CENTER=Claims",
                "ALLOCATION_CONFIDENCE": "Allocated / Estimated",
                "CHARGEBACK_READY": "Ready",
                "QUERY_COUNT": 20,
                "TOTAL_CREDITS": 100.0,
                "FIRST_USAGE_DATE": "2026-05-01",
                "LAST_USAGE_DATE": "2026-05-07",
                "ACTIVE_DAYS": 7,
            },
            {
                "COMPANY": "Trexis",
                "ENVIRONMENT": "No Database Context",
                "DATABASE_NAME": "NO_DATABASE_CONTEXT",
                "USER_NAME": "UNKNOWN_USER",
                "ROLE_NAME": "SYSADMIN",
                "WAREHOUSE_NAME": "SHARED_ETL_WH",
                "WAREHOUSE_SIZE": "LARGE",
                "COST_OWNER": "",
                "OWNER_SOURCE": "QUERY_USER",
                "OWNER_EVIDENCE": "Query user only",
                "ALLOCATION_CONFIDENCE": "Shared / Low Confidence",
                "CHARGEBACK_READY": "No",
                "QUERY_COUNT": 5,
                "TOTAL_CREDITS": 50.0,
            },
        ])

        detail = _normalize_cost_explorer_detail(raw, 3.0)
        self.assertIn("PROD", set(detail["ENVIRONMENT_ROLLUP"]))
        self.assertIn("No Database Context", set(detail["ENVIRONMENT_ROLLUP"]))
        summary = _cost_explorer_summary(detail, "Department / Cost Center")
        by_dimension = {row["DIMENSION"]: row for _, row in summary.iterrows()}
        self.assertAlmostEqual(by_dimension["Claims"]["EST_COST"], 300.0)
        self.assertEqual(by_dimension["Claims"]["ROUTE_TELEMETRY"], "Tag Telemetry")
        self.assertEqual(by_dimension["Unassigned"]["CHARGEBACK_READY"], "Review Required")

        gaps = _cost_explorer_gap_board(detail, summary)
        by_gap = {row["GAP"]: row for _, row in gaps.iterrows()}
        self.assertEqual(by_gap["Missing department / cost-center telemetry"]["STATE"], "Action Needed")
        self.assertEqual(by_gap["No database context"]["STATE"], "Action Needed")
        self.assertEqual(by_gap["Not chargeback ready"]["STATE"], "Action Needed")
        self.assertGreater(by_gap["Cost concentration"]["EST_COST"], 0)

    def test_mart_procedure_runs_filter_by_environment(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            st.session_state["global_environment"] = "PROD"

            calls_sql = build_mart_procedure_calls_sql(7, "ALFA").upper()
            self.assertIn("FACT_PROCEDURE_RUN", calls_sql)
            self.assertIn("DATABASE_NAME", calls_sql)
            self.assertIn("SCHEMA_NAME", calls_sql)
            self.assertIn("GROUP BY DATABASE_NAME, SCHEMA_NAME, PROCEDURE_NAME", calls_sql)
            self.assertIn("UPPER(ENVIRONMENT)", calls_sql)
            self.assertIn("'PROD'", calls_sql)

            sla_sql = build_mart_procedure_sla_sql(7, "ALFA").upper()
            self.assertIn("FACT_PROCEDURE_RUN", sla_sql)
            self.assertIn("DATABASE_NAME", sla_sql)
            self.assertIn("SCHEMA_NAME", sla_sql)
            self.assertIn("UPPER(ENVIRONMENT)", sla_sql)
            self.assertIn("'PROD'", sla_sql)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_usage_overview_storage_sums_are_null_safe(self):
        usage_text = (APP_ROOT / "sections" / "usage_overview.py").read_text(encoding="utf-8")
        text = (APP_ROOT / "utils" / "shared_metrics_storage.py").read_text(encoding="utf-8")
        self.assertIn("load_shared_usage_storage_kpis", usage_text)
        self.assertIn("SUM(COALESCE(c.average_database_bytes, 0))", text)
        self.assertIn("SUM(COALESCE(c.average_failsafe_bytes, 0))", text)
        self.assertNotIn("SUM(c.average_database_bytes)", text)
        self.assertNotIn("SUM(c.average_failsafe_bytes)", text)

    def test_bill_driver_summary_handles_missing_baseline_and_empty_drivers(self):
        summary = _bill_driver_summary(
            delta_credits=10.0,
            current_credits=10.0,
            prior_credits=0.0,
            unallocated_pct=30.0,
            warehouse_deltas=pd.DataFrame(),
            user_drivers=pd.DataFrame(),
            query_type_drivers=pd.DataFrame(),
        )
        self.assertEqual(summary["severity"], "Watch")
        self.assertIn("new/no baseline", summary["headline"])
        self.assertIn("unallocated gap", summary["caveat"])

    def test_bill_waterfall_balances_to_current_total(self):
        wh = pd.DataFrame(
            {
                "WAREHOUSE_NAME": ["WH_A", "WH_B", "WH_C"],
                "CREDIT_DELTA": [20.0, -5.0, 2.0],
            }
        )
        wf = _build_bill_waterfall(
            wh,
            prior_credits=100.0,
            current_credits=117.0,
            credit_price=3.0,
            top_n=2,
        )
        self.assertEqual(wf.iloc[0]["Driver"], "Prior baseline")
        self.assertEqual(wf.iloc[-1]["Driver"], "Current total")
        self.assertAlmostEqual(float(wf.iloc[-1]["Credits"]), 117.0)
        movement = wf[~wf["Type"].isin(["Baseline", "Current"])]["Credits"].sum()
        self.assertAlmostEqual(float(movement), 17.0)

    def test_service_cost_categories_are_business_readable(self):
        self.assertEqual(_service_cost_category("SNOWPIPE"), "Data loading / ingestion")
        self.assertEqual(_service_cost_category("CORTEX_SEARCH"), "AI / Cortex")
        self.assertEqual(_service_cost_category("AUTO_CLUSTERING"), "Serverless features")
        self.assertEqual(_service_cost_category("AUTOMATIC_CLUSTERING"), "Serverless features")
        self.assertEqual(_service_cost_category("SNOWPARK_CONTAINER_SERVICES"), "Serverless features")
        self.assertEqual(_service_cost_category("OPENFLOW_COMPUTE_SNOWFLAKE"), "Data integration / Openflow")
        self.assertEqual(_service_cost_category("CLOUD_SERVICES"), "Cloud services / metadata")

    def test_finance_movement_summary_separates_source_basis_levels(self):
        service_df = pd.DataFrame(
            {
                "PERIOD": ["CURRENT", "PRIOR", "CURRENT"],
                "SERVICE_TYPE": ["SNOWPIPE", "SNOWPIPE", "CORTEX"],
                "CREDITS": [8.0, 3.0, 2.0],
            }
        )
        summary = _build_finance_movement_summary(
            current_credits=100.0,
            prior_credits=80.0,
            allocated_credits=70.0,
            unallocated_credits=30.0,
            service_drivers=service_df,
            credit_price=3.0,
        )
        categories = set(summary["Category"])
        self.assertIn("Warehouse metering", categories)
        self.assertIn("Query-attributed workload", categories)
        self.assertIn("Unallocated / idle / overhead", categories)
        self.assertIn("Data loading / ingestion", categories)
        self.assertIn("AI / Cortex", categories)
        source_basis = dict(zip(summary["Category"], summary["Measurement Basis"]))
        self.assertEqual(source_basis["Warehouse metering"], "Exact")
        self.assertEqual(source_basis["Query-attributed workload"], "Allocated / Estimated")
        self.assertEqual(source_basis["Data loading / ingestion"], "Account-wide")

    def test_security_score_weights_mfa_and_failures(self):
        strong = _security_score(
            failed_logins=0,
            failed_users=0,
            users_without_mfa=0,
            active_users=100,
            recent_grants=0,
            shared_databases=0,
        )
        risky = _security_score(
            failed_logins=40,
            failed_users=8,
            users_without_mfa=20,
            active_users=100,
            recent_grants=8,
            shared_databases=2,
        )
        self.assertEqual(strong, 100)
        self.assertLess(risky, 70)
        self.assertEqual(_security_rating(strong), "Strong")
        self.assertEqual(_security_rating(risky), "High Risk")

    def test_security_actions_are_finding_specific(self):
        self.assertEqual(_security_action_for("MFA Gap")[0], "User/Auth")
        self.assertEqual(_security_action_for("Recent Grant")[0], "Grant/Role")
        self.assertEqual(_security_action_for("Shared Database Exposure")[0], "Shared Data")

    def test_security_brief_launchpad_prioritizes_investigation_workflows(self):
        rows = _security_brief_workflow_rows()

        self.assertEqual(
            [row["WORKFLOW"] for row in rows],
            [
                "Security Overview",
                "Failed Logins",
                "Risky Grants",
                "Privilege Sprawl",
                "Access Changes",
                "Data Sharing Exposure",
                "Security Alerts",
                "Security Admin / Advanced",
            ],
        )
        by_workflow = {row["WORKFLOW"]: row for row in rows}
        self.assertIn("failed logins", by_workflow["Security Overview"]["DBA_MOVE"])
        self.assertIn("failed logins", by_workflow["Failed Logins"]["DBA_MOVE"])
        self.assertIn("admin roles", by_workflow["Risky Grants"]["DBA_MOVE"])
        self.assertIn("dormant high-privilege", by_workflow["Privilege Sprawl"]["DBA_MOVE"])
        self.assertIn("recent grants", by_workflow["Access Changes"]["DBA_MOVE"])
        self.assertIn("shared databases", by_workflow["Data Sharing Exposure"]["DBA_MOVE"])
        self.assertIn("security alerts", by_workflow["Security Alerts"]["DBA_MOVE"])
        self.assertIn("raw evidence", by_workflow["Security Admin / Advanced"]["DBA_MOVE"])
        self.assertIn("Open Overview", by_workflow["Security Overview"]["BUTTON_LABEL"])
        self.assertIn("Open Logins", by_workflow["Failed Logins"]["BUTTON_LABEL"])
        self.assertIn("MFA gaps", by_workflow["Failed Logins"]["SOURCES"])

    def test_security_mfa_coverage_sql_prefers_has_mfa_and_avoids_alias_grouping(self):
        exprs = _user_mfa_column_exprs({"HAS_MFA", "HAS_PASSWORD", "LAST_SUCCESS_LOGIN"})
        sql = _build_mfa_coverage_sql(exprs, "AND u.name LIKE 'ALFA_%'").upper()

        self.assertIn("TRY_TO_BOOLEAN(TO_VARCHAR(U.HAS_MFA))", sql)
        self.assertIn("'HAS_MFA' AS MFA_SOURCE", sql)
        self.assertIn("COALESCE(U.LAST_SUCCESS_LOGIN, U.CREATED_ON) AS LAST_LOGIN", sql)
        self.assertIn("COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(U.DISABLED)), FALSE) = FALSE", sql)
        self.assertIn("AND U.NAME LIKE 'ALFA_%'", sql)
        self.assertNotIn("LOGIN_HISTORY", sql)
        self.assertNotIn("GROUP BY U.NAME, HAS_PASSWORD, HAS_MFA", sql)

    def test_security_mfa_helpers_fallback_to_duo_and_block_when_unavailable(self):
        duo_exprs = _user_mfa_column_exprs({"EXT_AUTHN_DUO"})
        missing_exprs = _user_mfa_column_exprs(set())

        self.assertIn("TRY_TO_BOOLEAN(TO_VARCHAR(u.ext_authn_duo))", duo_exprs["mfa_expr"])
        self.assertIn("'EXT_AUTHN_DUO' AS mfa_source", duo_exprs["mfa_source_expr"])
        self.assertIn("NULL::BOOLEAN AS has_mfa", missing_exprs["mfa_expr"])
        self.assertEqual(_mfa_count_expr({"HAS_MFA"}), "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(has_mfa)), FALSE) = FALSE)")
        self.assertEqual(_mfa_count_expr({"EXT_AUTHN_DUO"}), "COUNT_IF(COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(ext_authn_duo)), FALSE) = FALSE)")
        self.assertEqual(_mfa_gap_predicate({"HAS_MFA"}), "AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.has_mfa)), FALSE) = FALSE")
        self.assertEqual(_mfa_gap_predicate({"EXT_AUTHN_DUO"}), "AND COALESCE(TRY_TO_BOOLEAN(TO_VARCHAR(u.ext_authn_duo)), FALSE) = FALSE")
        self.assertEqual(_mfa_gap_predicate(set()), "AND 1 = 0")

    def test_security_brief_markdown_contains_evidence_summary(self):
        summary_row = {
            "FAILED_LOGINS": 5,
            "FAILED_USERS": 2,
            "ACTIVE_USERS": 100,
            "USERS_WITHOUT_MFA": 3,
            "RECENT_GRANTS": 4,
            "SHARED_DATABASES": 1,
        }
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["High"],
                "FINDING_TYPE": ["MFA Gap"],
                "ENTITY": ["USER_A"],
                "EVENT_COUNT": [1],
            }
        )
        md = _build_security_brief_markdown(
            company="ALFA",
            days=30,
            score=91,
            summary_row=summary_row,
            exceptions=exceptions,
        )
        self.assertIn("OVERWATCH Security Summary - ALFA", md)
        self.assertIn("Security state:", md)
        self.assertNotIn("Security score", md)
        self.assertIn("## Data Notes", md)
        self.assertIn("MFA Gap", md)
        self.assertIn("Company scope uses user/database naming", md)

    def test_security_exception_strip_prioritizes_loaded_exceptions_then_summary(self):
        meta = _security_scope_meta("ALFA", "PROD", 30, state={})
        summary = pd.DataFrame([{
            "FAILED_LOGINS": 8,
            "FAILED_USERS": 2,
            "USERS_WITHOUT_MFA": 3,
            "RECENT_GRANTS": 40,
            "SHARED_DATABASES": 1,
        }])
        priority_exceptions = pd.DataFrame([{
            "SEVERITY": "High",
            "FINDING_TYPE": "MFA Gap",
            "ENTITY": "USER_A",
            "EVENT_COUNT": 1,
            "LAST_SEEN": "2026-06-01",
            "NEXT_ACTION": "Confirm MFA enforcement path.",
        }])

        exception_rows = _security_exception_strip_rows(
            summary,
            priority_exceptions,
            meta,
            company="ALFA",
            environment="PROD",
            days=30,
        )
        summary_rows = _security_exception_strip_rows(
            summary,
            pd.DataFrame(),
            meta,
            company="ALFA",
            environment="PROD",
            days=30,
        )
        stale_rows = _security_exception_strip_rows(
            summary,
            pd.DataFrame(),
            _security_scope_meta("ALFA", "PROD", 14, state={}),
            company="ALFA",
            environment="PROD",
            days=30,
        )

        self.assertEqual(exception_rows[0]["signal"], "MFA Gap")
        self.assertEqual(exception_rows[0]["entity"], "USER_A")
        self.assertEqual(
            [row["signal"] for row in summary_rows],
            ["MFA gaps", "Failed logins", "Grant-change volume", "Shared data exposure"],
        )
        self.assertEqual(stale_rows, [])

    def test_security_access_review_marks_login_only_rows_no_database_context(self):
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["High", "High", "Low", "High", "Medium"],
                "FINDING_TYPE": [
                    "Failed Login",
                    "MFA Gap",
                    "Recent Grant",
                    "Object Grant",
                    "Shared Database Exposure",
                ],
                "ENTITY": ["ALFA_USER", "ALFA_MFA_GAP", "ETL_RUNNER", "ALFA_EDW_DEV.PUBLIC.POLICY", "ALFA_EDW_PROD"],
                "DATABASE_NAME": ["", "", "", "ALFA_EDW_DEV", "ALFA_EDW_PROD"],
                "EVENT_COUNT": [12, 1, 4, 5, 1],
                "DISTINCT_SOURCES": [3, 0, 2, 2, 0],
                "LAST_SEEN": ["2026-05-01", "2026-05-02", "2026-05-03", "2026-05-03", "2026-05-04"],
                "PROOF_QUERY": [
                    "LOGIN_HISTORY",
                    "ACCOUNT_USAGE.USERS",
                    "FACT_GRANT_DAILY",
                    "ACCOUNT_USAGE.GRANTS_TO_ROLES",
                    "ACCOUNT_USAGE.DATABASES",
                ],
            }
        )

        review = _build_security_access_review(exceptions, "PROD")
        by_type = {row["FINDING_TYPE"]: row for _, row in review.iterrows()}

        for finding in ["Failed Login", "MFA Gap", "Recent Grant"]:
            self.assertFalse(by_type[finding]["DATABASE_CONTEXT"])
            self.assertEqual(by_type[finding]["ENVIRONMENT"], "No Database Context")
        self.assertTrue(by_type["Shared Database Exposure"]["DATABASE_CONTEXT"])
        self.assertEqual(by_type["Shared Database Exposure"]["ENVIRONMENT"], "PROD")
        self.assertTrue(by_type["Object Grant"]["DATABASE_CONTEXT"])
        self.assertEqual(by_type["Object Grant"]["DATABASE_NAME"], "ALFA_EDW_DEV")
        self.assertEqual(by_type["Object Grant"]["ENVIRONMENT"], "ALFA_EDW_DEV")
        self.assertEqual(by_type["Object Grant"]["SCOPE_CONFIDENCE"], "Database Context")
        self.assertEqual(by_type["Failed Login"]["OWNER"], "IAM / Security Route")
        self.assertEqual(by_type["MFA Gap"]["APPROVER"], "IAM / Security")
        self.assertEqual(by_type["Failed Login"]["ONCALL_PRIMARY"], "")
        self.assertIn("MONITORING_CONTEXT", by_type["Recent Grant"]["OWNER_SOURCE"])
        self.assertIn("MANAGE GRANTS", by_type["Recent Grant"]["ROLE_CAPABILITY_STATE"])

        for _, row in review.iterrows():
            self.assertEqual(verification_query_safety_issues(row["VERIFICATION_QUERY"]), [])
            self.assertEqual(verification_query_safety_issues(_security_exception_verification_sql(row)), [])

    def test_security_access_review_readiness_tracks_ticket_approval_and_verification(self):
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["High", "Medium"],
                "FINDING_TYPE": ["Failed Login", "Object Grant"],
                "ENTITY": ["ALFA_USER", "ALFA_EDW_DEV.PUBLIC.POLICY"],
                "DATABASE_NAME": ["", "ALFA_EDW_DEV"],
                "EVENT_COUNT": [12, 3],
                "DISTINCT_SOURCES": [2, 1],
                "LAST_SEEN": ["2026-05-01", "2026-05-02"],
                "PROOF_QUERY": ["LOGIN_HISTORY", "ACCOUNT_USAGE.GRANTS_TO_ROLES"],
            }
        )

        review = _build_security_access_review(exceptions, "DEV_ALL")
        by_type = {row["FINDING_TYPE"]: row for _, row in review.iterrows()}

        self.assertEqual(by_type["Failed Login"]["REVIEW_READINESS"], "Ticket / Review Date Blocked")
        self.assertEqual(by_type["Failed Login"]["REVIEW_SLA_HOURS"], 24)
        self.assertIn("access ticket", by_type["Failed Login"]["REVIEW_BLOCKERS"])
        self.assertIn("review/expiry date", by_type["Failed Login"]["REVIEW_BLOCKERS"])
        self.assertEqual(by_type["Object Grant"]["CONTROL_READINESS"], by_type["Object Grant"]["REVIEW_READINESS"])

        ready = _security_access_review_readiness_for_row({
            "SEVERITY": "High",
            "OWNER": "Security Owner",
            "OWNER_SOURCE": "MONITORING_CONTEXT exact",
            "ACCESS_TICKET_ID": "SEC-123",
            "REVIEW_BY_DATE": "2026-06-30",
            "OWNER_APPROVAL_STATUS": "Approved",
            "VERIFICATION_QUERY": "SELECT 1",
        })
        self.assertEqual(ready["REVIEW_READINESS"], "Ready for Action Queue")
        self.assertEqual(ready["REVIEW_BLOCKERS"], "None")

    def test_security_sql_adds_database_scoped_object_grants(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            st.session_state["global_environment"] = "DEV_ALL"

            live_summary, live_exceptions = _build_security_summary_sql(None, 14, "ALFA")
            mart_summary, mart_exceptions = _build_security_mart_brief_sql(None, 14, "ALFA")
            combined = "\n".join([live_exceptions, mart_exceptions]).upper()
            summary_sql = "\n".join([live_summary, mart_summary]).upper()

            self.assertIn("GRANTS_TO_ROLES", combined)
            self.assertIn("'OBJECT GRANT'", combined)
            self.assertIn("GOR.TABLE_CATALOG AS DATABASE_NAME", combined)
            self.assertIn("ALFA_EDW_DEV", combined)
            self.assertNotIn("UPPER(LH.DATABASE_NAME)", combined)
            self.assertNotIn("GRANTS_TO_ROLES", summary_sql)
            self.assertNotIn("OBJECT_GRANTS.OBJECT_GRANTS", summary_sql)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_security_privileged_grant_review_keeps_account_grants_under_environment_scope(self):
        sql = _security_privileged_grant_review_sql(30, "ALFA", "PROD")
        sql_upper = sql.upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS", sql_upper)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_ROLES", sql_upper)
        self.assertIn("'NO DATABASE CONTEXT' AS ENVIRONMENT", sql_upper)
        self.assertIn("PRIVILEGED_ROLE_GRANTS", sql_upper)
        self.assertIn("OBJECT_PRIVILEGE_GRANTS", sql_upper)
        self.assertIn("GOR.PRIVILEGE AS PRIVILEGE", sql_upper)
        self.assertIn("AS GRANT_OPTION", sql_upper)
        self.assertIn("GRANT_AGE_DAYS", sql_upper)
        self.assertIn("ALFA_EDW_PROD", sql_upper)
        self.assertNotIn("GTU.TABLE_CATALOG", sql_upper)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_security_privileged_grant_readiness_adds_owner_route_and_scope(self):
        grants = pd.DataFrame([
            {
                "FINDING_TYPE": "Privileged Role Grant",
                "SEVERITY": "Critical",
                "ENTITY": "JDOE",
                "ROLE_NAME": "ACCOUNTADMIN",
                "PRIVILEGE": "",
                "GRANT_OPTION": False,
                "OBJECT_NAME": "",
                "DATABASE_NAME": "",
                "DATABASE_CONTEXT": False,
                "ENVIRONMENT": "No Database Context",
                "GRANTED_BY": "SECURITYADMIN",
                "CREATED_ON": "2026-05-01",
                "GRANT_AGE_DAYS": 120,
                "PROOF_REQUIRED": "ticket and owner approval",
            },
            {
                "FINDING_TYPE": "Privileged Object Grant",
                "SEVERITY": "High",
                "ENTITY": "ETL_RUNNER",
                "ROLE_NAME": "",
                "PRIVILEGE": "OWNERSHIP",
                "GRANT_OPTION": True,
                "OBJECT_NAME": "ALFA_EDW_DEV.PUBLIC.POLICY_FACT",
                "DATABASE_NAME": "ALFA_EDW_DEV",
                "DATABASE_CONTEXT": True,
                "ENVIRONMENT": "ALFA_EDW_DEV",
                "GRANTED_BY": "SYSADMIN",
                "CREATED_ON": "2026-05-02",
                "GRANT_AGE_DAYS": 10,
                "PROOF_REQUIRED": "object route review",
            },
        ])

        readiness = _annotate_security_privileged_grant_readiness(grants)
        by_entity = {row["ENTITY"]: row for _, row in readiness.iterrows()}
        summary = _privilege_sprawl_summary(readiness)

        self.assertEqual(by_entity["JDOE"]["GRANT_REVIEW_STATE"], "Tier 0 role grant")
        self.assertEqual(by_entity["JDOE"]["GRANT_REVIEW_READINESS"], "Telemetry Pending")
        self.assertEqual(by_entity["JDOE"]["SCOPE_CONFIDENCE"], "Account/User Context")
        self.assertEqual(by_entity["JDOE"]["OWNER_ROUTE_READY"], "Yes")
        self.assertEqual(by_entity["ETL_RUNNER"]["GRANT_REVIEW_STATE"], "Privileged object grant")
        self.assertEqual(by_entity["ETL_RUNNER"]["SCOPE_CONFIDENCE"], "Database Context")
        self.assertIn("MONITORING_CONTEXT", by_entity["ETL_RUNNER"]["OWNER_SOURCE"])
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["tier0"], 1)
        self.assertEqual(summary["admin_role_grants"], 1)
        self.assertEqual(summary["object_privileges"], 1)
        self.assertEqual(summary["ownership_or_grant_option"], 1)
        self.assertEqual(summary["verification_required"], 2)
        self.assertEqual(summary["stale_admin_grants"], 1)
        self.assertEqual(_security_workflow_for("Privileged Object Grant"), "Privilege Sprawl")
        self.assertEqual(_security_workflow_for("MFA Gap"), "Failed Logins")

    def test_privileged_grant_action_payload_is_review_only_and_closure_tracked(self):
        row = {
            "FINDING_TYPE": "Privileged Role Grant",
            "SEVERITY": "Critical",
            "ENTITY": "JDOE",
            "ROLE_NAME": "ACCOUNTADMIN",
            "OBJECT_NAME": "",
            "DATABASE_NAME": "",
            "ENVIRONMENT": "No Database Context",
            "OWNER": "IAM / Security Route",
            "OWNER_EMAIL": "iam@example.com",
            "ONCALL_PRIMARY": "DBA On-Call",
            "APPROVAL_GROUP": "Security",
            "ESCALATION_TARGET": "DBA / Security Route",
            "OWNER_SOURCE": "MONITORING_CONTEXT exact",
            "OWNER_EVIDENCE": "role route map",
            "GRANT_REVIEW_STATE": "Tier 0 role grant",
            "GRANT_REVIEW_READINESS": "Telemetry Pending",
            "OWNER_ROUTE_READY": "Yes",
            "SCOPE_CONFIDENCE": "Account/User Context",
            "PROOF_REQUIRED": "role, grantee, reviewer, ticket, rollback/status",
        }

        verification_sql = _privileged_grant_verification_sql(row)
        action = _privileged_grant_action_payload(row, company="ALFA", environment="PROD")

        self.assertEqual(action["Source"], "Security Posture - Privileged Grant Status")
        self.assertEqual(action["Category"], "Security Access Review")
        self.assertEqual(action["Entity Type"], "Privileged Grant")
        self.assertEqual(action["Review Status"], "Requested")
        self.assertEqual(action["Environment"], "No Database Context")
        self.assertIn("ACCOUNTADMIN", action["Finding"])
        self.assertIn("Do not grant, revoke, or narrow access", action["Generated SQL Fix"])
        self.assertEqual(action["Verification Query"], verification_sql)
        self.assertIn("GRANTS_TO_USERS", verification_sql)
        self.assertIn("UPPER(role) = UPPER('ACCOUNTADMIN')", verification_sql)
        self.assertEqual(verification_query_safety_issues(verification_sql), [])

    def test_security_access_review_snapshot_sql_keeps_login_rows_under_env_filter(self):
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["High", "Medium"],
                "FINDING_TYPE": ["Failed Login", "Shared Database Exposure"],
                "ENTITY": ["ALFA_USER", "ALFA_EDW_PROD"],
                "EVENT_COUNT": [12, 1],
                "DISTINCT_SOURCES": [3, 0],
                "LAST_SEEN": ["2026-05-01", "2026-05-04"],
                "PROOF_QUERY": ["LOGIN_HISTORY", "ACCOUNT_USAGE.DATABASES"],
            }
        )
        review = _build_security_access_review(exceptions, "PROD")
        ddl = build_security_access_review_ddl().upper()
        insert_sql = _security_access_review_insert_sql(
            review,
            company="ALFA",
            environment="PROD",
            source="unit test",
            snapshot_id="SECURITYSNAP1",
        ).upper()
        history_sql = _security_access_review_history_sql(30, "ALFA", "PROD").upper()

        self.assertIn("CREATE TABLE IF NOT EXISTS", ddl)
        self.assertIn("OVERWATCH_SECURITY_ACCESS_REVIEW", ddl)
        self.assertIn("DATABASE_CONTEXT", ddl)
        self.assertIn("ROLE_CAPABILITY_STATE", ddl)
        self.assertIn("REVIEW_READINESS", ddl)
        self.assertIn("NEXT_CONTROL_ACTION", ddl)
        self.assertIn("INSERT INTO", insert_sql)
        self.assertIn("'SECURITYSNAP1'", insert_sql)
        self.assertIn("'NO DATABASE CONTEXT'", insert_sql)
        self.assertIn("IAM / SECURITY ROUTE", insert_sql)
        self.assertIn("LOGIN_HISTORY", insert_sql)
        self.assertIn("REVIEW_READINESS", insert_sql)
        self.assertIn("ACCESS_TICKET_ID", insert_sql)
        self.assertIn("ENVIRONMENT = 'PROD'", history_sql)
        self.assertIn("DATABASE_CONTEXT = FALSE", history_sql)
        self.assertIn("REVIEW_BLOCKER_ROWS", history_sql)
        self.assertIn("LAST_CONTROL_READINESS", history_sql)

        migration_sql = "\n".join(build_security_access_review_migration_sql()).upper()
        for column in [
            "ACCESS_TICKET_ID",
            "REVIEW_BY_DATE",
            "IAM_APPROVAL_STATE",
            "REVIEW_READINESS",
            "REVIEW_BLOCKERS",
            "REVIEW_SLA_HOURS",
            "VERIFICATION_STATUS",
            "VERIFICATION_RESULT",
            "CONTROL_READINESS",
            "CONTROL_BLOCKERS",
            "NEXT_CONTROL_ACTION",
        ]:
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", migration_sql)

    def test_security_control_board_prioritizes_closure_and_review_blockers(self):
        review = _build_security_access_review(
            pd.DataFrame(
                {
                    "SEVERITY": ["High", "High"],
                    "FINDING_TYPE": ["Failed Login", "Shared Database Exposure"],
                    "ENTITY": ["ALFA_USER", "ALFA_EDW_PROD"],
                    "DATABASE_NAME": ["", "ALFA_EDW_PROD"],
                    "EVENT_COUNT": [12, 1],
                    "DISTINCT_SOURCES": [3, 0],
                    "LAST_SEEN": ["2026-05-01", "2026-05-04"],
                    "PROOF_QUERY": ["LOGIN_HISTORY", "ACCOUNT_USAGE.DATABASES"],
                }
            ),
            "PROD",
        )
        closure = pd.DataFrame(
            [
                {
                    "ENTITY": "ALFA_USER",
                    "CLOSURE_READINESS": "Overdue closure",
                    "CLOSURE_RANK": 0,
                    "OPEN_ACTIONS": 1,
                    "OVERDUE_OPEN": 1,
                    "FIXED_WITHOUT_VERIFICATION": 0,
                    "RECOVERY_RISK_ROWS": 0,
                    "VERIFIED_CLOSURES": 0,
                    "NEXT_ACTION": "Escalate IAM owner.",
                }
            ]
        )

        board = _security_control_board(review, closure=closure, environment="PROD")
        by_entity = {row["ENTITY"]: row for _, row in board.iterrows()}

        self.assertEqual(by_entity["ALFA_USER"]["CONTROL_STATE"], "Closure Overdue")
        self.assertEqual(by_entity["ALFA_USER"]["CONTROL_RANK"], 0)
        self.assertEqual(by_entity["ALFA_EDW_PROD"]["CONTROL_STATE"], "Ticket / Review Date Blocked")
        self.assertIn("access ticket", by_entity["ALFA_EDW_PROD"]["CONTROL_BLOCKERS"])

    def test_security_action_queue_closure_sql_scores_evidence_gaps(self):
        sql = _security_action_queue_closure_sql(45, "ALFA", "DEV_ALL").upper()

        self.assertIn("OVERWATCH_ACTION_QUEUE", sql)
        self.assertIn("SECURITY POSTURE - SECURITY SUMMARY", sql)
        self.assertIn("SECURITY POSTURE - PRIVILEGED GRANT STATUS", sql)
        self.assertIn("COMPANY = 'ALFA'", sql)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, sql)
        self.assertIn("FIXED_WITHOUT_VERIFICATION", sql)
        self.assertIn("OWNER_APPROVAL_GAP_ROWS", sql)
        self.assertIn("CLOSURE_READINESS", sql)
        self.assertIn("SECURITY ROUTE AND TICKET", sql)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_security_operability_fact_is_fast_and_keeps_account_scope_rows(self):
        ddl = build_security_operability_fact_ddl().upper()
        migrations = "\n".join(build_security_operability_fact_migration_sql()).upper()
        fact_sql = _security_operability_fact_sql(30, "ALFA", "DEV_ALL").upper()

        self.assertIn("FACT_SECURITY_OPERABILITY_DAILY", ddl)
        self.assertIn("CONTROL_SOURCE", ddl)
        self.assertIn("CONTROL_RANK", ddl)
        self.assertIn("REVIEW_BLOCKER_ROWS", ddl)
        self.assertIn("OWNER_APPROVAL_GAP_ROWS", ddl)
        self.assertIn("ADD COLUMN IF NOT EXISTS CONTROL_SOURCE", migrations)
        self.assertIn("ADD COLUMN IF NOT EXISTS CONTROL_RANK", migrations)
        self.assertIn("ADD COLUMN IF NOT EXISTS REVIEW_BLOCKER_ROWS", migrations)
        self.assertIn("FACT_SECURITY_OPERABILITY_DAILY", fact_sql)
        self.assertIn("SNAPSHOT_DATE >= DATEADD('DAY', -30", fact_sql)
        self.assertIn("COMPANY = 'ALFA'", fact_sql)
        self.assertIn("NO DATABASE CONTEXT", fact_sql)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, fact_sql)
        self.assertNotIn("ACCOUNT_USAGE", fact_sql)
        self.assertNotIn("OVERWATCH_ACTION_QUEUE", fact_sql)

    def test_security_source_health_flags_stale_fallback_and_unavailable_evidence(self):
        state = {
            "global_user": "ALFA_USER",
            "global_database": "",
            "global_role": "",
            "global_start_date": "",
            "global_end_date": "",
            "security_posture_brief_days": 30,
            "security_posture_summary": pd.DataFrame({"FAILED_LOGINS": [3]}),
            "security_posture_exceptions": pd.DataFrame({"FINDING_TYPE": ["Failed Login"]}),
            "security_posture_source": "Live fallback: SNOWFLAKE.ACCOUNT_USAGE",
            "security_posture_meta": {
                "company": "ALFA",
                "environment": "PROD",
                "days": 30,
                "global_user": "ALFA_USER",
                "global_database": "",
                "global_role": "",
                "global_start_date": "",
                "global_end_date": "",
            },
            "security_operability_fact": pd.DataFrame(),
            "security_operability_fact_error": "FACT_SECURITY_OPERABILITY_DAILY missing",
            "security_priv_grant_days": 30,
            "security_privileged_grants": pd.DataFrame({"ENTITY": ["JDOE"]}),
            "security_privileged_grants_meta": {
                "company": "ALFA",
                "environment": "DEV_ALL",
                "days": 30,
                "global_user": "ALFA_USER",
                "global_database": "",
                "global_role": "",
                "global_start_date": "",
                "global_end_date": "",
            },
        }

        rows = _security_source_health_rows(state, company="ALFA", environment="PROD")
        by_surface = {row["SURFACE"]: row for _, row in rows.iterrows()}

        self.assertEqual(by_surface["Security summary"]["STATE"], "Loaded")
        self.assertEqual(by_surface["Security summary"]["CONFIDENCE"], "Live fallback")
        self.assertEqual(by_surface["Security exceptions"]["ROWS"], 1)
        self.assertEqual(by_surface["Control summary"]["STATE"], "Unavailable")
        self.assertEqual(by_surface["Privileged grants"]["STATE"], "Stale")
        self.assertEqual(by_surface["Access review trend"]["STATE"], "On demand")
        self.assertIn("Reload", by_surface["Privileged grants"]["NEXT_ACTION"])

    def test_change_drift_score_weights_destructive_and_policy_changes(self):
        clean = _change_drift_score(
            object_changes=0,
            access_changes=0,
            policy_changes=0,
            owner_changes=0,
            destructive_changes=0,
            manual_drift=0,
        )
        risky = _change_drift_score(
            object_changes=20,
            access_changes=15,
            policy_changes=3,
            owner_changes=2,
            destructive_changes=4,
            manual_drift=10,
        )
        self.assertEqual(clean, 100)
        self.assertLess(risky, 70)
        self.assertEqual(_change_drift_rating(clean), "Controlled")
        self.assertEqual(_change_drift_rating(risky), "High Drift Risk")

    def test_change_drift_actions_are_finding_specific(self):
        self.assertEqual(_change_action_for("Destructive Object Change")[0], "Object")
        self.assertEqual(_change_action_for("Policy or Tag Change")[0], "Policy/Tag")
        self.assertEqual(_change_action_for("Grant or Role Change")[0], "Grant/Role")
        self.assertEqual(_change_action_for("Manual Drift")[0], "Drift")

    def test_change_brief_launchpad_prioritizes_investigation_workflows(self):
        rows = _change_brief_workflow_rows()
        self.assertEqual(
            [row["WORKFLOW"] for row in rows],
            [
                "Object and access changes",
                "Schema and object drift",
                "Data movement and replication",
                "Stored procedure lineage",
                "Controlled DBA actions",
            ],
        )
        by_workflow = {row["WORKFLOW"]: row for row in rows}
        self.assertIn("recent object changes", by_workflow["Object and access changes"]["DBA_MOVE"])
        self.assertIn("Trace stored procedure", by_workflow["Stored procedure lineage"]["DBA_MOVE"])
        self.assertIn("Open DBA Actions", by_workflow["Controlled DBA actions"]["BUTTON_LABEL"])
        self.assertIn("Guarded admin", by_workflow["Controlled DBA actions"]["SOURCES"])

    def test_change_brief_first_default_resets_stale_unloaded_workflow(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["change_drift_view"] = "Change Workflows"
            _apply_change_brief_first_default()

            self.assertEqual(st.session_state["change_drift_view"], "Change Brief")
            self.assertEqual(st.session_state["_change_drift_brief_first_version"], 2)

            st.session_state["change_drift_view"] = "Change Workflows"
            _apply_change_brief_first_default()
            self.assertEqual(st.session_state["change_drift_view"], "Change Workflows")

            st.session_state.clear()
            st.session_state["change_drift_view"] = "Change Workflows"
            st.session_state["change_drift_summary"] = pd.DataFrame({"OBJECT_CHANGES": [1]})
            _apply_change_brief_first_default()
            self.assertEqual(st.session_state["change_drift_view"], "Change Workflows")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_change_drift_queue_payload_is_auditable_and_readonly(self):
        row = {
            "FINDING_TYPE": "Destructive Object Change",
            "SEVERITY": "High",
            "ENTITY": "ALFA_EDW_DEV.PUBLIC.POLICY_FACT",
            "USER_NAME": "DEPLOY_USER",
            "QUERY_ID": "01abc",
            "QUERY_TAG": "CHG-12345 deployment release",
        }
        action = _change_action_payload(row, company="ALFA", environment="ALFA_EDW_DEV")

        self.assertEqual(action["Category"], "Object Change Monitoring")
        self.assertEqual(action["Owner"], "DBA Change Route")
        self.assertEqual(action["Ticket ID"], "CHG-12345")
        self.assertEqual(action["Oncall Primary"], "")
        self.assertIn("MONITORING_CONTEXT", action["Owner Source"])
        self.assertEqual(action["Recovery Audit State"], "Query ID captured")
        self.assertNotIn("Owner Approval Status", action)
        self.assertEqual(action["Verification Status"], "Requested")
        self.assertIn("Data Route", action["Approver"])
        self.assertIn("QUERY_HISTORY", action["Verification Query"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])
        self.assertIn("OBJECT_DEPENDENCIES", action["Recovery Evidence"])
        self.assertIn("review/rollback status", action["Recovery Evidence"])
        self.assertIn("blast-radius", action["Generated SQL Fix"])
        self.assertNotIn("DROP TABLE", action["Generated SQL Fix"].upper())

    def test_change_control_readiness_requires_ticket_approval_and_proof(self):
        exceptions = pd.DataFrame([
            {
                "FINDING_TYPE": "Grant or Role Change",
                "SEVERITY": "Medium",
                "ENTITY": "ALFA_EDW_DEV.PUBLIC",
                "USER_NAME": "SECURITY_ADMIN",
                "QUERY_ID": "01def",
                "QUERY_TAG": "manual-console-change",
                "LAST_SEEN": "2026-05-31 10:00:00",
            }
        ])
        readiness = _build_change_control_readiness(exceptions)
        row = readiness.iloc[0]

        self.assertEqual(row["APPROVAL_REQUIRED"], "Yes")
        self.assertEqual(row["OWNER_APPROVAL_STATUS"], "Requested")
        self.assertEqual(row["TICKET_REQUIRED"], "Yes")
        self.assertEqual(row["BLAST_RADIUS_REQUIRED"], "Yes")
        self.assertEqual(row["CHANGE_CONTROL_STATE"], "Validate Review")
        self.assertEqual(row["CHANGE_TICKET_STATE"], "Missing ticket status")
        self.assertEqual(row["OWNER"], "Security Route")
        self.assertEqual(row["ONCALL_PRIMARY"], "")
        self.assertIn("MONITORING_CONTEXT", row["OWNER_SOURCE"])
        self.assertEqual(row["APPROVAL_ROUTE_READY"], "Yes")
        self.assertEqual(row["CHANGE_EVIDENCE_READINESS"], "Closure Blocked")
        self.assertEqual(row["EVIDENCE_BLOCKERS"], "change ticket")
        self.assertEqual(row["REVIEW_SLA_HOURS"], 72)
        self.assertIn("Record the ticket", row["NEXT_CONTROL_ACTION"])
        self.assertIn("Review telemetry state", row["IAC_RECONCILIATION_STATE"])
        self.assertIn("Query ID", row["EXECUTION_AUDIT_STATE"])
        self.assertIn("change ticket", row["PROOF_REQUIRED"])
        self.assertEqual(verification_query_safety_issues(row["VERIFICATION_QUERY"]), [])
        self.assertEqual(verification_query_safety_issues(row["BLAST_RADIUS_QUERY"]), [])

    def test_change_control_readiness_summary_groups_blockers_and_account_scope(self):
        exceptions = pd.DataFrame([
            {
                "FINDING_TYPE": "Policy or Tag Change",
                "SEVERITY": "High",
                "ENTITY": "ALFA_EDW_PROD.SECURE.CUSTOMER",
                "USER_NAME": "DEPLOY_USER",
                "ROLE_NAME": "SECURITYADMIN",
                "QUERY_ID": "01policy",
                "QUERY_TAG": "CHG-12345 deployment release",
                "LAST_SEEN": "2026-05-31 10:00:00",
            },
            {
                "FINDING_TYPE": "Grant or Role Change",
                "SEVERITY": "Medium",
                "ENTITY": "ACCOUNTADMIN",
                "USER_NAME": "SECURITY_ADMIN",
                "ROLE_NAME": "SECURITYADMIN",
                "QUERY_ID": "01grant",
                "QUERY_TAG": "manual-console-change",
                "LAST_SEEN": "2026-05-31 11:00:00",
            },
        ])

        readiness = _build_change_control_readiness(exceptions)
        summary = _change_control_readiness_summary(readiness)

        self.assertFalse(summary.empty)
        self.assertIn("READINESS", summary.columns)
        self.assertEqual(int(summary["TOTAL_CHANGES"].sum()), 2)
        self.assertEqual(int(summary["HIGH_RISK_CHANGES"].sum()), 1)
        self.assertEqual(int(summary["MISSING_TICKET_ROWS"].sum()), 1)
        self.assertGreaterEqual(int(summary["ACCOUNT_SCOPE_ROWS"].sum()), 1)
        self.assertIn("Closure Blocked", set(summary["READINESS"]))
        self.assertIn("Record missing ticket", " ".join(summary["NEXT_CONTROL_ACTION"].astype(str)))

    def test_change_control_evidence_snapshot_sql_is_scoped_and_auditable(self):
        readiness = _enrich_change_control_evidence(pd.DataFrame([
            {
                "FINDING_TYPE": "Policy or Tag Change",
                "SEVERITY": "High",
                "ENTITY": "ALFA_EDW_PROD.SECURE.CUSTOMER",
                "USER_NAME": "DEPLOY_USER",
                "ROLE_NAME": "SECURITYADMIN",
                "QUERY_ID": "01policy",
                "QUERY_TAG": "RFC98765 approved change",
                "LAST_SEEN": "2026-05-31 09:00:00",
                "CHANGE_CONTROL_STATE": "Approval Required",
                "CONTROL_GAP": "Needs approver, change ticket, and blast-radius note",
                "APPROVER": "Security Owner / Data Stewardship",
                "OWNER_APPROVAL_STATUS": "Requested",
                "APPROVAL_REQUIRED": "Yes",
                "TICKET_REQUIRED": "Yes",
                "BLAST_RADIUS_REQUIRED": "Yes",
                "PROOF_REQUIRED": "query_id, approver, change ticket, dependency/blast-radius note",
                "VERIFICATION_QUERY": _change_verification_sql("01policy"),
                "BLAST_RADIUS_QUERY": _change_blast_radius_sql("ALFA_EDW_PROD.SECURE.CUSTOMER"),
            }
        ]))
        ddl = build_change_control_evidence_ddl().upper()
        insert_sql = _change_control_evidence_insert_sql(
            readiness,
            company="ALFA",
            environment="PROD",
            source="unit test",
            snapshot_id="snap1",
        ).upper()
        trend_sql = _change_control_evidence_history_sql(30, "ALFA", "PROD").upper()
        migration_sql = "\n".join(build_change_control_evidence_migration_sql()).upper()

        self.assertIn("CREATE TABLE IF NOT EXISTS", ddl)
        self.assertIn("OVERWATCH_CHANGE_CONTROL_EVIDENCE", ddl)
        self.assertIn("CHANGE_TICKET_ID", ddl)
        self.assertIn("IAC_RECONCILIATION_STATE", ddl)
        self.assertIn("CHANGE_EVIDENCE_READINESS", ddl)
        self.assertIn("NEXT_CONTROL_ACTION", ddl)
        self.assertIn("ALTER TABLE", migration_sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS CHANGE_EVIDENCE_READINESS", migration_sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS NEXT_CONTROL_ACTION", migration_sql)
        self.assertIn("INSERT INTO", insert_sql)
        self.assertIn("'RFC98765'", insert_sql)
        self.assertIn("'PROD'", insert_sql)
        self.assertIn("REVIEW STATUS TAGGED", insert_sql)
        self.assertIn("REVIEW READY", insert_sql)
        self.assertIn("SNAPSHOT_TS >= DATEADD('DAY', -30", trend_sql)
        self.assertIn("COMPANY = 'ALFA'", trend_sql)
        self.assertIn("ENVIRONMENT = 'PROD'", trend_sql)
        self.assertIn("MISSING_TICKET_ROWS", trend_sql)

    def test_external_integration_placeholders_are_removed_from_change_contract(self):
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()
        change_text = (ROOT / ".overwatch_final" / "sections" / "change_drift.py").read_text(encoding="utf-8").upper()
        task_text = (ROOT / ".overwatch_final" / "sections" / "task_management.py").read_text(encoding="utf-8").upper()
        workload_text = (ROOT / ".overwatch_final" / "sections" / "workload_operations.py").read_text(encoding="utf-8").upper()

        for retired in [
            "OVERWATCH_EXTERNAL_CONTROL_FEED",
            "OVERWATCH_SOURCE_CONTROL_CHANGE",
            "OVERWATCH_OWNER_APPROVAL",
            "OVERWATCH_TASK_STATUS_FEED_STAGE",
            "SNOWFLAKE TASK FEED SETUP",
            "LOAD RELEASE EVIDENCE",
            "LOAD OWNER APPROVAL EVIDENCE",
        ]:
            self.assertNotIn(retired, setup_sql)
            self.assertNotIn(retired, change_text)
            self.assertNotIn(retired, task_text)

        self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY", workload_text)
        self.assertIn("OVERWATCH_CHANGE_CONTROL_EVIDENCE", setup_sql)
        self.assertIn("OVERWATCH_ACTION_QUEUE", setup_sql)

    def test_change_source_health_flags_loaded_stale_and_unavailable_evidence(self):
        state = {
            "global_warehouse": "",
            "global_user": "",
            "global_role": "",
            "global_database": "ALFA_EDW_PROD",
            "global_start_date": "",
            "global_end_date": "",
            "change_drift_brief_days": 14,
            "change_drift_summary": pd.DataFrame({"OBJECT_CHANGES": [3]}),
            "change_drift_exceptions": pd.DataFrame({"FINDING_TYPE": ["Manual Drift"]}),
            "change_drift_source": "Fast change summary",
            "change_drift_meta": {
                "company": "ALFA",
                "environment": "PROD",
                "days": 14,
                "global_warehouse": "",
                "global_user": "",
                "global_role": "",
                "global_database": "ALFA_EDW_PROD",
                "global_start_date": "",
                "global_end_date": "",
            },
            "change_control_operability_fact": pd.DataFrame(),
            "change_control_operability_fact_error": "FACT_CHANGE_CONTROL_OPERABILITY_DAILY missing",
            "change_drift_evidence_trend_days": 30,
            "change_drift_evidence_trend": pd.DataFrame({"FINDING_TYPE": ["Manual Drift"]}),
            "change_drift_evidence_trend_meta": {
                "company": "ALFA",
                "environment": "DEV_ALL",
                "days": 30,
                "global_warehouse": "",
                "global_user": "",
                "global_role": "",
                "global_database": "ALFA_EDW_PROD",
                "global_start_date": "",
                "global_end_date": "",
            },
            "change_integration_deployment_days": 14,
            "change_integration_owner_approval_days": 14,
        }

        rows = _change_source_health_rows(state, company="ALFA", environment="PROD")
        by_surface = {row["SURFACE"]: row for _, row in rows.iterrows()}

        self.assertEqual(by_surface["Change brief"]["STATE"], "Loaded")
        self.assertEqual(by_surface["Change brief"]["CONFIDENCE"], "Fast summary")
        self.assertEqual(by_surface["Change exceptions"]["ROWS"], 1)
        self.assertEqual(by_surface["Control summary"]["STATE"], "Unavailable")
        self.assertEqual(by_surface["Telemetry trend"]["STATE"], "Stale")
        self.assertEqual(by_surface["Closure analytics"]["STATE"], "On demand")
        self.assertNotIn("Release evidence", by_surface)
        self.assertNotIn("Owner approval evidence", by_surface)
        self.assertIn("Reload", by_surface["Telemetry trend"]["NEXT_ACTION"])

    def test_change_action_queue_closure_sql_scores_evidence_gaps(self):
        sql = _change_action_queue_closure_sql(45, "ALFA", "DEV_ALL").upper()

        self.assertIn("OVERWATCH_ACTION_QUEUE", sql)
        self.assertIn("CHANGE & DRIFT - BRIEF", sql)
        self.assertIn("COMPANY = 'ALFA'", sql)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, sql)
        self.assertIn("FIXED_WITHOUT_VERIFICATION", sql)
        self.assertIn("OWNER_APPROVAL_GAP_ROWS", sql)
        self.assertIn("CLOSURE_READINESS", sql)
        self.assertIn("BLAST-RADIUS TELEMETRY", sql)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_change_operator_next_moves_prioritize_route_proof_scope_and_closure(self):
        readiness_summary = pd.DataFrame(
            {
                "ROUTE_BLOCKED": [1],
                "CLOSURE_BLOCKED": [2],
                "MISSING_TICKET_ROWS": [1],
                "IAC_GAP_ROWS": [1],
                "MISSING_QUERY_ID_ROWS": [1],
                "ACCOUNT_SCOPE_ROWS": [1],
                "HIGH_RISK_CHANGES": [1],
            }
        )
        closure = pd.DataFrame(
            {
                "OVERDUE_OPEN": [1],
                "FIXED_WITHOUT_VERIFICATION": [1],
                "RECOVERY_RISK_ROWS": [0],
                "VERIFIED_CLOSURES": [0],
            }
        )
        exceptions = pd.DataFrame({
            "ENTITY": ["SNOWFLAKE ACCOUNT"],
            "FINDING_TYPE": ["Destructive Object Change"],
            "SEVERITY": ["High"],
            "USER_NAME": ["JFREEZE03"],
            "QUERY_ID": [""],
        })
        gates = _change_operator_next_moves(
            score=82,
            exceptions=exceptions,
            readiness_summary=readiness_summary,
            closure=closure,
        )
        matrix = _change_intervention_matrix(
            exceptions,
            readiness=_build_change_control_readiness(exceptions),
            closure=closure,
        )
        by_gate = {row["GATE"]: row for _, row in gates.iterrows()}

        self.assertEqual(by_gate["Review route"]["STATE"], "Route Blocked")
        self.assertEqual(by_gate["Closure status"]["STATE"], "Closure Blocked")
        self.assertEqual(by_gate["Scope confidence"]["STATE"], "Account-Scope Review")
        self.assertEqual(by_gate["Recovery readiness"]["STATE"], "Recovery Status Required")
        self.assertIn("database environment scope cannot prove", by_gate["Scope confidence"]["NEXT_ACTION"])
        self.assertEqual(matrix.iloc[0]["INTERVENTION_STATE"], "Recovery Block")
        self.assertEqual(matrix.iloc[0]["DBA_PRIORITY"], "P0")
        self.assertIn("blast radius", matrix.iloc[0]["NEXT_DECISION"])

    def test_change_verification_sql_is_read_only_for_missing_query_id(self):
        sql = _change_verification_sql("").upper()
        self.assertIn("WHERE 1 = 0", sql)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_change_blast_radius_sql_scopes_dependencies_by_entity(self):
        sql = _change_blast_radius_sql("ALFA_EDW_DEV.PUBLIC.POLICY_FACT").upper()
        self.assertIn("OBJECT_DEPENDENCIES", sql)
        self.assertIn("REFERENCED_DATABASE", sql)
        self.assertIn("REFERENCING_DATABASE", sql)
        self.assertIn("'ALFA_EDW_DEV'", sql)
        self.assertIn("'POLICY_FACT'", sql)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_change_blast_radius_sql_preserves_dots_inside_quoted_identifiers(self):
        sql = _change_blast_radius_sql('"DB.WITH.DOTS"."SCHEMA.ONE"."TABLE.TWO"')

        self.assertIn("'DB.WITH.DOTS'", sql)
        self.assertIn("'SCHEMA.ONE'", sql)
        self.assertIn("'TABLE.TWO'", sql)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_change_drift_environment_scope_retains_account_level_changes(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            st.session_state["global_environment"] = "PROD"
            st.session_state["global_warehouse"] = "BI_COMPUTE_WH"

            live_summary, live_exceptions = _build_change_drift_sql(None, 14, "ALFA")
            mart_summary, mart_exceptions = _build_mart_change_drift_sql(14, "ALFA")
            combined = "\n".join([live_summary, live_exceptions, mart_summary, mart_exceptions]).upper()
            mart_combined = "\n".join([mart_summary, mart_exceptions]).upper()

            self.assertIn("DATABASE_NAME IS NULL", combined)
            self.assertIn("ALFA_EDW_PROD", combined)
            self.assertIn("AS DATABASE_CONTEXT", combined)
            self.assertIn("AS SCOPE_CONFIDENCE", combined)
            self.assertIn("ACCOUNT_SCOPE_CHANGES", combined)
            self.assertNotIn("WAREHOUSE_NAME", mart_combined)
            self.assertNotIn("BI_COMPUTE_WH", mart_combined)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_source_health_helpers_do_not_read_empty_session_keys(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            helpers = [
                ("Account Health", _account_health_source_health_rows),
                ("Warehouse Health", _warehouse_source_health_rows),
                ("Security Posture", _security_source_health_rows),
                ("Change & Drift", _change_source_health_rows),
            ]

            for label, helper in helpers:
                with self.subTest(section=label):
                    rows = helper(st.session_state, company="ALFA", environment="PROD")
                    self.assertFalse(rows.empty)
                    self.assertIn("SURFACE", rows.columns)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_change_drift_markdown_contains_control_summary(self):
        summary_row = {
            "OBJECT_CHANGES": 3,
            "ACCESS_CHANGES": 2,
            "OWNER_CHANGES": 1,
            "POLICY_CHANGES": 1,
            "DESTRUCTIVE_CHANGES": 1,
            "MANUAL_DRIFT": 4,
        }
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["High"],
                "FINDING_TYPE": ["Destructive Object Change"],
                "USER_NAME": ["USER_A"],
                "ENTITY": ["DB.SCHEMA"],
            }
        )
        md = _build_change_drift_markdown(
            company="ALFA",
            days=14,
            score=81,
            summary_row=summary_row,
            exceptions=exceptions,
        )
        self.assertIn("OVERWATCH Object Change Brief - ALFA", md)
        self.assertIn("Control state:", md)
        self.assertNotIn("Control score", md)
        self.assertIn("## Data Notes", md)
        self.assertIn("Destructive Object Change", md)
        self.assertIn("Schema and access change detection", md)

    def test_query_root_cause_score_weights_failures_and_queue(self):
        stable = _root_cause_score(
            failed_queries=0,
            blocked_queries=0,
            queued_queries=0,
            spill_queries=0,
            full_scan_queries=1,
            slow_queries=1,
            total_queries=1000,
        )
        risky = _root_cause_score(
            failed_queries=20,
            blocked_queries=10,
            queued_queries=30,
            spill_queries=20,
            full_scan_queries=120,
            slow_queries=150,
            total_queries=500,
        )
        self.assertGreaterEqual(stable, 95)
        self.assertLess(risky, 70)

    def test_query_root_cause_actions_are_specific(self):
        self.assertEqual(_root_cause_action_for("Failed Query")[0], "Query")
        self.assertEqual(_root_cause_action_for("Lock Contention")[0], "Query/Transaction")
        self.assertEqual(_root_cause_action_for("Warehouse Queue")[0], "Warehouse")
        self.assertEqual(_root_cause_action_for("Remote Spill")[0], "Query/Warehouse")
        self.assertEqual(_root_cause_action_for("Full Scan")[0], "Object/Query")
        self.assertIn("Contention Center", _root_cause_action_for("Lock Contention")[1])
        self.assertIn("TRANSACTION_BLOCKED_TIME", _root_cause_action_for("Lock Contention")[2])
        self.assertIn("Query Investigation", _root_cause_action_for("Remote Spill")[1])
        self.assertIn("partition evidence", _root_cause_action_for("Full Scan")[1])
        self.assertIn("query ID evidence", _root_cause_action_for("Slow Query")[1])

    def test_query_root_cause_routes_sql_shape_to_ai_diagnosis(self):
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["Critical", "High", "High", "Critical"],
                "ROOT_CAUSE": ["Remote Spill", "Full Scan", "Warehouse Queue", "Lock Contention"],
                "QUERY_ID": ["01spill", "01scan", "01queue", "01blocked"],
                "USER_NAME": ["ETL_USER", "BI_USER", "BATCH_USER", "LOAD_USER"],
                "ROLE_NAME": ["SYSADMIN", "ANALYST", "SYSADMIN", "SYSADMIN"],
                "WAREHOUSE_NAME": ["WH_TRXS_QUERY", "BI_COMPUTE_WH", "LOAD_WH", "WH_TRXS_LOAD"],
                "WAREHOUSE_SIZE": ["Large", "Medium", "Large", "Large"],
                "DATABASE_NAME": ["PROD_DB", "PROD_DB", "PROD_DB", "PROD_DB"],
                "SCHEMA_NAME": ["CORE", "REPORTING", "LOAD", "CORE"],
                "EXECUTION_STATUS": ["SUCCESS", "SUCCESS", "SUCCESS", "RUNNING"],
                "START_TIME": ["2026-06-13 08:00", "2026-06-13 08:05", "2026-06-13 08:10", "2026-06-13 08:15"],
                "ELAPSED_SEC": [420.0, 310.0, 125.0, 600.0],
                "COMPILE_SEC": [2.0, 1.0, 1.0, 1.0],
                "EXEC_SEC": [410.0, 300.0, 80.0, 590.0],
                "QUEUED_SEC": [0.0, 0.0, 70.0, 0.0],
                "BLOCKED_SEC": [0.0, 0.0, 0.0, 185.0],
                "GB_SCANNED": [80.0, 240.0, 5.0, 20.0],
                "REMOTE_SPILL_GB": [8.2, 0.0, 0.0, 0.0],
                "PARTITION_PCT": [45.0, 98.0, 5.0, 10.0],
                "ROWS_PRODUCED": [1000, 250, 100, 0],
                "ERROR_MESSAGE": ["", "", "", ""],
                "QUERY_TEXT": [
                    "SELECT * FROM PROD_DB.CORE.FACT_POLICY p JOIN PROD_DB.CORE.DIM_CUSTOMER c ON p.CUSTOMER_ID = c.CUSTOMER_ID",
                    "SELECT POLICY_ID FROM PROD_DB.REPORTING.POLICY_SUMMARY WHERE TO_DATE(BIND_TS) = '2026-06-01'",
                    "SELECT COUNT(*) FROM PROD_DB.LOAD.BATCH_AUDIT",
                    "MERGE INTO PROD_DB.CORE.FACT_POLICY tgt USING STAGE_DB.LOAD.POLICY_DELTA src ON tgt.POLICY_ID = src.POLICY_ID WHEN MATCHED THEN UPDATE SET PREMIUM_AMOUNT = src.PREMIUM_AMOUNT",
                ],
                "IMPACT_VALUE": [8.2, 240.0, 70.0, 185.0],
                "IMPACT_UNIT": ["GB remote spill", "GB scanned", "seconds queued", "seconds blocked"],
            }
        )

        priority = _root_cause_priority_view(exceptions)
        by_query = {row["QUERY_ID"]: row for _, row in priority.iterrows()}

        self.assertEqual(by_query["01spill"]["NEXT_WORKFLOW"], "AI Diagnosis")
        self.assertEqual(by_query["01scan"]["NEXT_WORKFLOW"], "AI Diagnosis")
        self.assertEqual(by_query["01queue"]["NEXT_WORKFLOW"], "Live Triage")
        self.assertEqual(by_query["01blocked"]["NEXT_WORKFLOW"], "Contention Center")
        self.assertIn("safe action contract", by_query["01blocked"]["NEXT_ACTION"])

        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            _seed_ai_query_diagnosis_from_row(by_query["01spill"], days=7)

            self.assertEqual(st.session_state["workload_operations_workflow"], "Query Investigation")
            self.assertNotIn("workload_operations_query_focus", st.session_state)
            self.assertEqual(st.session_state["query_analysis_active_view"], "AI Diagnosis")
            self.assertEqual(st.session_state["ai_query_id"], "01spill")
            self.assertIn("FACT_POLICY", st.session_state["ai_query_text"])
            evidence = st.session_state["ai_query_evidence"]
            self.assertEqual(evidence["QUERY_ID"], "01spill")
            self.assertEqual(evidence["WAREHOUSE_NAME"], "WH_TRXS_QUERY")
            self.assertEqual(evidence["BYTES_SCANNED_GB"], 80.0)
            self.assertEqual(evidence["REMOTE_SPILL_GB"], 8.2)
            self.assertIn("Root-Cause Brief routed Remote Spill", evidence["OPERATOR_NOTES"])
            self.assertTrue(st.session_state["ai_query_operator_stats"].empty)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_query_root_cause_brief_markdown_contains_evidence_limits(self):
        summary_row = {
            "TOTAL_QUERIES": 100,
            "FAILED_QUERIES": 2,
            "BLOCKED_QUERIES": 1,
            "QUEUED_QUERIES": 4,
            "SPILL_QUERIES": 1,
            "FULL_SCAN_QUERIES": 8,
        }
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["High"],
                "ROOT_CAUSE": ["Warehouse Queue"],
                "QUERY_ID": ["01abc"],
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "IMPACT_VALUE": [45.0],
                "IMPACT_UNIT": ["seconds queued"],
            }
        )
        md = _build_root_cause_markdown(
            company="ALFA",
            days=7,
            score=82,
            summary_row=summary_row,
            exceptions=exceptions,
        )
        self.assertIn("OVERWATCH Query Root-Cause Brief - ALFA", md)
        self.assertNotIn("Root-cause score", md)
        self.assertIn("Failed queries: 2", md)
        self.assertIn("Blocked queries: 1", md)
        self.assertIn("Warehouse Queue", md)
        self.assertIn("QUERY_HISTORY can lag", md)

    def test_query_root_cause_cortex_prompt_is_evidence_bounded(self):
        summary_row = {
            "TOTAL_QUERIES": 100,
            "FAILED_QUERIES": 2,
            "BLOCKED_QUERIES": 1,
            "QUEUED_QUERIES": 4,
            "SPILL_QUERIES": 1,
            "FULL_SCAN_QUERIES": 8,
            "SLOW_QUERIES": 12,
            "AFFECTED_WAREHOUSES": 2,
            "AFFECTED_USERS": 3,
        }
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["High"],
                "ROOT_CAUSE": ["Warehouse Queue"],
                "QUERY_ID": ["01abc"],
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "DATABASE_NAME": ["ALFA_EDW_PROD"],
                "SCHEMA_NAME": ["PUBLIC"],
                "ELAPSED_SEC": [91.2],
                "QUEUED_SEC": [45.0],
                "BLOCKED_SEC": [12.0],
                "REMOTE_SPILL_GB": [0.0],
                "GB_SCANNED": [12.5],
                "PARTITION_PCT": [40.0],
                "IMPACT_VALUE": [45.0],
                "IMPACT_UNIT": ["seconds queued"],
            }
        )
        prompt = _root_cause_cortex_prompt(
            company="ALFA",
            days=7,
            score=82,
            summary_row=summary_row,
            exceptions=exceptions,
        )
        self.assertIn("Write exactly 3 concise sentences", prompt)
        self.assertIn("Use only the evidence below", prompt)
        self.assertIn("Do not invent", prompt)
        self.assertIn("query_id=01abc", prompt)
        self.assertIn("warehouse=BI_COMPUTE_WH", prompt)
        self.assertIn("queued_sec=45.00", prompt)
        self.assertIn("blocked=1", prompt)
        self.assertIn("blocked_sec=12.00", prompt)

    def test_warehouse_capacity_score_weights_queue_spill_and_credit_spikes(self):
        healthy = _warehouse_capacity_score(
            queued_queries=0,
            spill_queries=0,
            high_latency_queries=1,
            total_queries=1000,
            credit_spike_pct=0,
        )
        risky = _warehouse_capacity_score(
            queued_queries=60,
            spill_queries=30,
            high_latency_queries=90,
            total_queries=500,
            credit_spike_pct=80,
        )
        self.assertGreaterEqual(healthy, 95)
        self.assertLess(risky, 65)

    def test_warehouse_capacity_actions_are_signal_specific(self):
        self.assertIn("multi-cluster", _warehouse_capacity_action_for("Queue Pressure")[0])
        self.assertIn("spilling queries", _warehouse_capacity_action_for("Memory Spill")[0])
        self.assertIn("current burn", _warehouse_capacity_action_for("Credit Spike")[0])

    def test_warehouse_capacity_readiness_routes_setting_changes_safely(self):
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["High"],
                "SIGNAL": ["Queue Pressure"],
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "QUEUED_QUERIES": [44],
                "SPILL_QUERIES": [2],
                "HIGH_LATENCY_QUERIES": [7],
                "CREDIT_SPIKE_PCT": [10.0],
                "P95_ELAPSED_SEC": [64.5],
            }
        )

        annotated = _annotate_warehouse_admin_readiness(exceptions)

        self.assertEqual(annotated.iloc[0]["ADMIN_READINESS"], "Ready for DBA review")
        self.assertEqual(annotated.iloc[0]["APPROVAL_REQUIRED"], "Yes")
        self.assertEqual(annotated.iloc[0]["ROLLBACK_REQUIRED"], "Yes")
        self.assertEqual(annotated.iloc[0]["OWNER"], "BI Platform Route")
        self.assertEqual(annotated.iloc[0]["ONCALL_PRIMARY"], "")
        self.assertIn("MONITORING_CONTEXT", annotated.iloc[0]["OWNER_SOURCE"])
        self.assertIn("DBA Lead", annotated.iloc[0]["APPROVER"])
        self.assertIn("MAX_CLUSTER_COUNT", annotated.iloc[0]["SETTING_CHANGE_CANDIDATE"])
        self.assertIn("Warehouse Settings Manager", annotated.iloc[0]["SAFE_CHANGE_PATH"])
        self.assertEqual(annotated.iloc[0]["IMPACT_TELEMETRY_REQUIRED"], "No")

    def test_warehouse_capacity_verification_sql_is_read_only_and_environment_scoped(self):
        sql = _warehouse_capacity_verification_sql(
            "BI_COMPUTE_WH",
            days=7,
            environment="DEV_ALL",
            company="ALFA",
        )
        sql_upper = sql.upper()

        self.assertIn("QUERY_HISTORY", sql_upper)
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql_upper)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, sql_upper)
        self.assertNotIn("ALFA_EDW_PROD", sql_upper)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_warehouse_owner_inventory_path_stays_removed(self):
        warehouse_text = (APP_ROOT / "sections" / "warehouse_health.py").read_text(encoding="utf-8")

        self.assertNotIn("_warehouse_owner_inventory_sql", warehouse_text)
        self.assertNotIn("_annotate_warehouse_owner_inventory", warehouse_text)
        self.assertNotIn("OVERWATCH_OWNER_DIRECTORY", warehouse_text)

    def test_warehouse_guardrail_coverage_blocks_missing_monitor_and_never_suspend(self):
        overview = pd.DataFrame(
            {
                "WAREHOUSE_NAME": ["COMPUTE_WH", "BI_COMPUTE_WH"],
                "TOTAL_QUERIES": [120, 600],
                "AVG_QUEUED_SEC": [0.2, 3.5],
                "TOTAL_REMOTE_SPILL_GB": [0.0, 18.0],
                "P95_ELAPSED_SEC": [8.0, 72.0],
                "METERED_CREDITS": [12.0, 125.0],
                "CREDIT_DELTA": [4.0, 38.0],
                "CREDIT_DELTA_PCT": [20.0, 65.0],
            }
        )
        settings = pd.DataFrame(
            {
                "NAME": ["COMPUTE_WH", "BI_COMPUTE_WH"],
                "RESOURCE_MONITOR": ["", "BI_WH_RM"],
                "AUTO_SUSPEND": [300, 0],
                "STATEMENT_TIMEOUT_IN_SECONDS": [3600, 0],
                "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": [600, 0],
            }
        )
        summary, board = _build_warehouse_guardrail_coverage(
            overview,
            settings_inventory=settings,
        )
        by_wh = {row["WAREHOUSE_NAME"]: row for _, row in board.iterrows()}

        self.assertEqual(summary["blocked"], 2)
        self.assertEqual(by_wh["COMPUTE_WH"]["GUARDRAIL_STATE"], "Blocked")
        self.assertEqual(by_wh["COMPUTE_WH"]["RESOURCE_MONITOR_STATE"], "Blocked")
        self.assertEqual(by_wh["COMPUTE_WH"]["TIMEOUT_STATE"], "Ready")
        self.assertIn("COMPUTE_WH_RM", by_wh["COMPUTE_WH"]["NEXT_ACTION"])
        self.assertEqual(by_wh["BI_COMPUTE_WH"]["AUTO_SUSPEND_STATE"], "Blocked")
        self.assertEqual(by_wh["BI_COMPUTE_WH"]["TIMEOUT_STATE"], "Review")
        self.assertEqual(by_wh["BI_COMPUTE_WH"]["ESCALATION_ROUTE_STATE"], "Ready")
        self.assertEqual(by_wh["BI_COMPUTE_WH"]["CAPACITY_STATE"], "Review")
        self.assertIn("queued_timeout=0", by_wh["BI_COMPUTE_WH"]["EVIDENCE"])
        self.assertIn("timeout settings", by_wh["BI_COMPUTE_WH"]["PROOF_REQUIRED"])
        self.assertLess(summary["score"], 80)
        setting_plan = _warehouse_setting_action_plan(board)
        action_types = set(setting_plan["ACTION_TYPE"])
        self.assertIn("Resource monitor coverage", action_types)
        self.assertIn("Auto-suspend review", action_types)
        self.assertIn("Timeout guardrail review", action_types)
        self.assertIn("Capacity change review", action_types)
        self.assertIn("Cost movement review", action_types)
        self.assertIn("ROLLBACK_CHECK", setting_plan.columns)
        self.assertIn("SAFE_SETTING_MOVE", setting_plan.columns)
        detail_options = _warehouse_setting_detail_options(setting_plan)
        self.assertFalse(detail_options.empty)
        self.assertIn("DETAIL_LABEL", detail_options.columns)
        self.assertIn("WORKFLOW_ROUTE", detail_options.columns)
        self.assertIn("Optimization Advisor", set(detail_options["WORKFLOW_ROUTE"]))

    def test_warehouse_cost_control_posture_flags_shared_compute_idle_burn(self):
        settings = pd.DataFrame(
            {
                "NAME": ["COMPUTE_WH", "ANALYTICS_WH"],
                "WAREHOUSE_SIZE": ["XSMALL", "SMALL"],
                "STATE": ["SUSPENDED", "STARTED"],
                "AUTO_SUSPEND": [1001, 60],
                "AUTO_RESUME": ["true", "true"],
            }
        )
        overview = pd.DataFrame(
            {
                "WAREHOUSE_NAME": ["COMPUTE_WH", "ANALYTICS_WH"],
                "METERED_CREDITS": [8.0, 2.0],
            }
        )

        summary, posture = _build_warehouse_cost_control_posture(settings, overview)
        by_wh = {row["WAREHOUSE_NAME"]: row for _, row in posture.iterrows()}

        self.assertEqual(summary["warehouses"], 2)
        self.assertEqual(summary["overwatch_candidates"], 1)
        self.assertEqual(by_wh["COMPUTE_WH"]["COST_CONTROL_STATE"], "Needs Review")
        self.assertEqual(by_wh["COMPUTE_WH"]["IDLE_RISK"], "Longer than current 1000s session timeout")
        self.assertEqual(by_wh["COMPUTE_WH"]["RECOMMENDED_AUTO_SUSPEND_SEC"], 60)
        self.assertIn("ALTER WAREHOUSE", by_wh["COMPUTE_WH"]["REVIEW_SQL"])
        self.assertIn("AUTO_RESUME = TRUE", by_wh["COMPUTE_WH"]["REVIEW_SQL"])
        self.assertEqual(by_wh["ANALYTICS_WH"]["COST_CONTROL_STATE"], "Ready")

    def test_warehouse_cost_control_posture_blocks_never_suspend_and_documents_future_wh(self):
        settings = pd.DataFrame(
            {
                "NAME": ["COMPUTE_WH"],
                "WAREHOUSE_SIZE": ["XSMALL"],
                "STATE": ["STARTED"],
                "AUTO_SUSPEND": [0],
                "AUTO_RESUME": ["false"],
            }
        )

        summary, posture = _build_warehouse_cost_control_posture(settings)
        row = posture.iloc[0]

        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(row["COST_CONTROL_STATE"], "Blocked")
        self.assertEqual(row["IDLE_RISK"], "Never suspends")
        self.assertIn("AUTO_SUSPEND = 60", row["REVIEW_SQL"])
        setup_sql = _overwatch_dedicated_warehouse_setup_sql()
        self.assertIn("CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH", setup_sql)
        self.assertIn("AUTO_RESUME = TRUE", setup_sql)

    def test_warehouse_advisor_recommendations_show_savings_without_sql(self):
        plan = pd.DataFrame([
            {
                "PRIORITY": "Medium",
                "WAREHOUSE_NAME": "LOAD_WH",
                "ACTION_TYPE": "Timeout guardrail review",
                "CURRENT_STATE": "Review",
                "CURRENT_SETTING": "statement=0, queued=0",
                "SAFE_SETTING_MOVE": "Set or confirm statement and queued timeout guardrails.",
                "WHY": "Timeout settings need review.",
                "ROLLBACK_CHECK": "Verify timeout errors and queue stay expected.",
                "REVIEW_SQL": "ALTER WAREHOUSE LOAD_WH SET STATEMENT_TIMEOUT_IN_SECONDS = 3600;",
            }
        ])
        posture = pd.DataFrame([
            {
                "WAREHOUSE_NAME": "COMPUTE_WH",
                "COST_CONTROL_STATE": "Needs Review",
                "IDLE_RISK": "Longer than current 1000s session timeout",
                "AUTO_SUSPEND_SEC": 1001,
                "AUTO_RESUME": True,
                "WAREHOUSE_SIZE": "XSMALL",
                "STATE": "STARTED",
                "METERED_CREDITS": 8.0,
                "RECOMMENDED_AUTO_SUSPEND_SEC": 60,
                "RECOMMENDED_ACTION": "Validate workload impact, then consider AUTO_SUSPEND=60.",
                "REVIEW_SQL": "ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 60;",
            }
        ])
        overview = pd.DataFrame([
            {
                "WAREHOUSE_NAME": "SAVE_WH",
                "WAREHOUSE_SIZE": "LARGE",
                "TOTAL_QUERIES": 100,
                "AVG_QUEUED_SEC": 0.0,
                "TOTAL_REMOTE_SPILL_GB": 0.0,
                "P95_ELAPSED_SEC": 10.0,
                "METERED_CREDITS": 100.0,
            },
            {
                "WAREHOUSE_NAME": "SPILL_WH",
                "WAREHOUSE_SIZE": "MEDIUM",
                "TOTAL_QUERIES": 100,
                "AVG_QUEUED_SEC": 0.0,
                "TOTAL_REMOTE_SPILL_GB": 25.0,
                "P95_ELAPSED_SEC": 10.0,
                "METERED_CREDITS": 12.0,
            },
        ])

        advisor = _build_warehouse_advisor_recommendations(
            plan,
            posture,
            overview,
            days=7,
            credit_price=3.68,
        )

        self.assertIn("EST_MONTHLY_SAVINGS_USD", advisor.columns)
        self.assertIn("VERIFIED_MONTHLY_SAVINGS_USD", advisor.columns)
        self.assertIn("SAVINGS_STATUS", advisor.columns)
        self.assertIn("SAVINGS_ASSUMPTION", advisor.columns)
        self.assertIn("SAVINGS_TYPE", advisor.columns)
        self.assertIn("ACTION_POSTURE", advisor.columns)
        self.assertIn("EXPECTED_VERIFICATION_IMPACT", advisor.columns)
        self.assertIn("DO_NOT_EXECUTE_UNTIL", advisor.columns)
        self.assertIn("VERIFICATION_WINDOW_DAYS", advisor.columns)
        self.assertNotIn("REVIEW_SQL", advisor.columns)
        self.assertGreater(float(advisor["EST_MONTHLY_SAVINGS_USD"].sum()), 0)
        self.assertEqual(float(advisor["VERIFIED_MONTHLY_SAVINGS_USD"].sum()), 0.0)
        self.assertIn("Needs Verification", set(advisor["SAVINGS_STATUS"]))
        self.assertIn("Auto-suspend savings", set(advisor["ADVISOR_TYPE"]))
        self.assertIn("Downsize savings candidate", set(advisor["ADVISOR_TYPE"]))
        self.assertIn("Capacity or size review", set(advisor["ADVISOR_TYPE"]))
        self.assertIn("Guarded admin change candidate", set(advisor["ACTION_POSTURE"]))
        self.assertIn("Estimated right-size savings", set(advisor["SAVINGS_TYPE"]))
        self.assertTrue(advisor["DO_NOT_EXECUTE_UNTIL"].astype(str).str.len().gt(0).all())
        self.assertTrue(
            advisor["EXPECTED_VERIFICATION_IMPACT"].astype(str).str.contains(
                "queue|spill|p95|credits", case=False, regex=True
            ).any()
        )
        self.assertNotIn("ALTER WAREHOUSE", advisor.to_string().upper())
        self.assertIn("DBA Control Room > Admin > Warehouse Settings", advisor.to_string())

    def test_warehouse_guardrail_coverage_marks_missing_metadata_as_data_gap(self):
        overview = pd.DataFrame(
            {
                "WAREHOUSE_NAME": ["ETL_LOAD_WH"],
                "TOTAL_QUERIES": [50],
                "AVG_QUEUED_SEC": [0.0],
                "TOTAL_REMOTE_SPILL_GB": [0.0],
                "P95_ELAPSED_SEC": [12.0],
                "METERED_CREDITS": [3.0],
                "CREDIT_DELTA": [0.0],
                "CREDIT_DELTA_PCT": [0.0],
            }
        )

        summary, board = _build_warehouse_guardrail_coverage(overview)
        row = board.iloc[0]

        self.assertEqual(summary["unknown"], 1)
        self.assertEqual(row["GUARDRAIL_STATE"], "Data Missing")
        self.assertEqual(row["RESOURCE_MONITOR_STATE"], "Unknown")
        self.assertEqual(row["AUTO_SUSPEND_STATE"], "Unknown")
        self.assertEqual(row["TIMEOUT_STATE"], "Unknown")
        self.assertEqual(row["ESCALATION_ROUTE_STATE"], "Ready")
        self.assertIn("SHOW WAREHOUSES", row["PROOF_REQUIRED"])
        self.assertIn("timeout settings", row["PROOF_REQUIRED"])
        self.assertLess(row["GUARDRAIL_SCORE"], 100)

    def test_warehouse_capacity_brief_markdown_contains_evidence_limits(self):
        summary_row = {
            "WAREHOUSES_ACTIVE": 4,
            "TOTAL_QUERIES": 1000,
            "QUEUED_QUERIES": 20,
            "SPILL_QUERIES": 5,
            "CREDIT_SPIKE_PCT": 35.0,
        }
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["High"],
                "SIGNAL": ["Credit Spike"],
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "CAPACITY_SCORE": [72.0],
                "METERED_CREDITS": [44.5],
            }
        )
        md = _build_warehouse_capacity_markdown(
            company="ALFA",
            days=7,
            score=80,
            summary_row=summary_row,
            exceptions=exceptions,
        )
        self.assertIn("OVERWATCH Warehouse Capacity Brief - ALFA", md)
        self.assertNotIn("Capacity score", md)
        self.assertIn("Queued queries: 20", md)
        self.assertIn("Credit Spike", md)
        self.assertIn("Settings Change Status", md)
        self.assertIn("guarded warehouse settings workflow", md)
        self.assertIn("ACCOUNT_USAGE can lag", md)

    def test_warehouse_setting_review_snapshot_sql_is_persistable_and_scoped(self):
        findings = pd.DataFrame(
            {
                "SEVERITY": ["High"],
                "SIGNAL": ["Credit Spike"],
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "CAPACITY_SCORE": [71.0],
                "QUEUED_QUERIES": [3],
                "SPILL_QUERIES": [1],
                "HIGH_LATENCY_QUERIES": [2],
                "P95_ELAPSED_SEC": [52.5],
                "METERED_CREDITS": [120.0],
                "CREDIT_SPIKE_PCT": [88.0],
            }
        )
        ddl = build_warehouse_setting_review_ddl().upper()
        insert_sql = _warehouse_setting_review_insert_sql(
            findings,
            company="ALFA",
            environment="PROD",
            source="unit test",
            snapshot_id="whsnap1",
        ).upper()
        trend_sql = _warehouse_setting_review_history_sql(30, "ALFA", "PROD").upper()

        self.assertIn("CREATE TABLE IF NOT EXISTS", ddl)
        self.assertIn("OVERWATCH_WAREHOUSE_SETTING_REVIEW", ddl)
        self.assertIn("IMPACT_TELEMETRY_REQUIRED", ddl)
        self.assertIn("INSERT INTO", insert_sql)
        self.assertIn("'BI_COMPUTE_WH'", insert_sql)
        self.assertIn("'DBA / COST ROUTE'", insert_sql)
        self.assertIn("'PROD'", insert_sql)
        self.assertIn("WAREHOUSE_METERING_HISTORY", insert_sql)
        self.assertIn("SNAPSHOT_TS >= DATEADD('DAY', -30", trend_sql)
        self.assertIn("COMPANY = 'ALFA'", trend_sql)
        self.assertIn("ENVIRONMENT = 'PROD'", trend_sql)
        self.assertIn("IMPACT_TELEMETRY_ROWS", trend_sql)

    def test_warehouse_setting_review_schema_tracks_execution_audit_fields(self):
        ddl = build_warehouse_setting_review_ddl().upper()
        migrations = "\n".join(build_warehouse_setting_review_migration_sql()).upper()

        for column in [
            "APPROVAL_STATE",
            "CHANGE_TICKET_ID",
            "ROLLBACK_SQL",
            "EXECUTED_SQL_HASH",
            "POST_CHANGE_VERIFICATION_STATUS",
            "VERIFIED_MONTHLY_SAVINGS",
            "AUDIT_READINESS",
            "AUDIT_BLOCKERS",
            "NEXT_CONTROL_ACTION",
        ]:
            self.assertIn(column, ddl)
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", migrations)

    def test_warehouse_setting_audit_readiness_requires_ticket_rollback_and_verification(self):
        blocked = _warehouse_setting_audit_readiness_for_row(
            {
                "OWNER": "BI Platform Owner",
                "OWNER_SOURCE": "WAREHOUSE_TAG",
                "APPROVER": "BI Platform Owner / DBA Lead",
                "APPROVAL_REQUIRED": "Yes",
                "APPROVAL_STATE": "Requested",
                "ROLLBACK_REQUIRED": "Yes",
                "IMPACT_TELEMETRY_REQUIRED": "Yes",
                "EXECUTION_STATUS": "Not Executed",
            }
        )
        verified = _warehouse_setting_audit_readiness_for_row(
            {
                "OWNER": "BI Platform Owner",
                "OWNER_SOURCE": "WAREHOUSE_TAG",
                "APPROVER": "BI Platform Owner / DBA Lead",
                "APPROVAL_REQUIRED": "Yes",
                "APPROVAL_STATE": "Approved",
                "CHANGE_TICKET_ID": "CHG12345",
                "ROLLBACK_REQUIRED": "Yes",
                "ROLLBACK_SQL": "ALTER WAREHOUSE BI_COMPUTE_WH SET AUTO_SUSPEND = 300;",
                "IMPACT_TELEMETRY_REQUIRED": "Yes",
                "EXECUTION_STATUS": "Success",
                "EXECUTED_SQL_HASH": "abc123",
                "POST_CHANGE_VERIFICATION_STATUS": "Verified",
                "POST_CHANGE_VERIFICATION_RESULT": "Queue/spill/credit metrics improved over the post-change window.",
                "VERIFIED_MONTHLY_SAVINGS": 250.0,
            }
        )

        self.assertEqual(blocked["AUDIT_READINESS"], "Pre-Change Blocked")
        self.assertIn("review status", blocked["AUDIT_BLOCKERS"])
        self.assertIn("change ticket", blocked["AUDIT_BLOCKERS"])
        self.assertIn("rollback SQL", blocked["AUDIT_BLOCKERS"])
        self.assertEqual(verified["AUDIT_READINESS"], "Change Audit Linked")
        self.assertEqual(verified["AUDIT_BLOCKERS"], "None")

    def test_warehouse_setting_execution_audit_sql_joins_review_and_admin_audit(self):
        sql = _warehouse_setting_execution_audit_sql(45, "ALFA", "DEV_ALL")
        sql_upper = sql.upper()

        self.assertIn("OVERWATCH_WAREHOUSE_SETTING_REVIEW", sql_upper)
        self.assertIn("OVERWATCH_ADMIN_ACTION_AUDIT", sql_upper)
        self.assertIn("ALTER WAREHOUSE", sql_upper)
        self.assertIn("LAST_SQL_HASH", sql_upper)
        self.assertIn("LAST_EXECUTED_BY", sql_upper)
        self.assertIn("EXECUTION_AUDIT_READINESS", sql_upper)
        self.assertIn("COMPANY = 'ALFA'", sql_upper)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, sql_upper)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_warehouse_operability_fact_is_fast_estimated_and_environment_scoped(self):
        ddl = build_warehouse_operability_fact_ddl().upper()
        migrations = "\n".join(build_warehouse_operability_fact_migration_sql()).upper()
        fact_sql = _warehouse_operability_fact_sql(30, "ALFA", "DEV_ALL").upper()

        self.assertIn("FACT_WAREHOUSE_OPERABILITY_DAILY", ddl)
        self.assertIn("CONTROL_SOURCE", ddl)
        self.assertIn("CONTROL_RANK", ddl)
        self.assertIn("CREDIT_ALLOCATION_METHOD", ddl)
        self.assertIn("NEXT_CONTROL_ACTION", ddl)
        self.assertIn("ADD COLUMN IF NOT EXISTS CONTROL_SOURCE", migrations)
        self.assertIn("ADD COLUMN IF NOT EXISTS CONTROL_RANK", migrations)
        self.assertIn("ADD COLUMN IF NOT EXISTS CREDIT_ALLOCATION_METHOD", migrations)
        self.assertIn("FACT_WAREHOUSE_OPERABILITY_DAILY", fact_sql)
        self.assertIn("SNAPSHOT_DATE >= DATEADD('DAY', -30", fact_sql)
        self.assertIn("COMPANY = 'ALFA'", fact_sql)
        self.assertIn("CREDIT_ALLOCATION_METHOD", fact_sql)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, fact_sql)
        self.assertNotIn("ACCOUNT_USAGE", fact_sql)
        self.assertNotIn("OVERWATCH_ACTION_QUEUE", fact_sql)

    def test_warehouse_source_health_flags_loaded_stale_and_unavailable_evidence(self):
        state = {
            "global_warehouse": "ALFA",
            "global_user": "",
            "global_role": "",
            "global_database": "",
            "global_start_date": "",
            "global_end_date": "",
            "wh_capacity_days": 7,
            "wh_capacity_summary": pd.DataFrame({"WAREHOUSES_ACTIVE": [2]}),
            "wh_capacity_meta": {
                "company": "ALFA",
                "environment": "PROD",
                "days": 7,
                "global_warehouse": "ALFA",
                "global_user": "",
                "global_role": "",
                "global_database": "",
                "global_start_date": "",
                "global_end_date": "",
            },
            "wh_operability_fact": pd.DataFrame(),
            "wh_operability_fact_error": "FACT_WAREHOUSE_OPERABILITY_DAILY does not exist",
            "wh_days": 7,
            "wh_df_wh": pd.DataFrame({"WAREHOUSE_NAME": ["ALFA_WH"]}),
            "wh_df_wh_source": "Fast warehouse summary",
            "wh_df_wh_meta": {
                "company": "ALFA",
                "environment": "DEV_ALL",
                "days": 7,
                "global_warehouse": "ALFA",
                "global_user": "",
                "global_role": "",
                "global_database": "",
                "global_start_date": "",
                "global_end_date": "",
            },
        }

        rows = _warehouse_source_health_rows(state, company="ALFA", environment="PROD")
        by_surface = {row["SURFACE"]: row for _, row in rows.iterrows()}

        self.assertEqual(by_surface["Capacity brief"]["STATE"], "Loaded")
        self.assertEqual(by_surface["Capacity brief"]["ROWS"], 1)
        self.assertEqual(by_surface["Control summary"]["STATE"], "Unavailable")
        self.assertEqual(by_surface["Overview"]["STATE"], "Stale")
        self.assertEqual(by_surface["Overview"]["CONFIDENCE"], "Fast summary")
        self.assertEqual(by_surface["Scaling events"]["STATE"], "On demand")
        self.assertIn("Reload", by_surface["Overview"]["NEXT_ACTION"])

    def test_warehouse_setting_control_board_prioritizes_closure_owner_and_audit_blocks(self):
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["Critical", "High", "High"],
                "SIGNAL": ["Queue Pressure", "Credit Spike", "Memory Spill"],
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH", "LOAD_TASK_WH", "DEV_WH"],
                "CAPACITY_SCORE": [48.0, 66.0, 70.0],
                "METERED_CREDITS": [120.0, 90.0, 10.0],
                "QUEUED_QUERIES": [80, 2, 0],
                "SPILL_QUERIES": [4, 1, 20],
                "HIGH_LATENCY_QUERIES": [12, 4, 9],
                "CREDIT_SPIKE_PCT": [10.0, 75.0, 0.0],
            }
        )
        owner_inventory = pd.DataFrame(
            {
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH", "LOAD_TASK_WH", "DEV_WH"],
                "WAREHOUSE_SIZE": ["Medium", "Large", "Small"],
                "QUERY_COUNT": [500, 300, 50],
                "DATABASE_COUNT": [2, 1, 1],
                "OWNER_TAG": ["BI Product Owner", "", ""],
                "COST_CENTER_TAG": ["BI", "", ""],
                "ENVIRONMENT_TAG": ["PROD", "", ""],
            }
        )
        closure = pd.DataFrame(
            {
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "CLOSURE_READINESS": ["Overdue closure"],
                "CLOSURE_RANK": [0],
                "OVERDUE_OPEN": [1],
                "FIXED_WITHOUT_VERIFICATION": [0],
                "NEXT_ACTION": ["Escalate owner and due date."],
            }
        )
        audit = pd.DataFrame(
            {
                "WAREHOUSE_NAME": ["LOAD_TASK_WH"],
                "AUDIT_ROWS": [1],
                "SUCCESSFUL_CHANGES": [0],
                "FAILED_CHANGES": [1],
                "LAST_EXECUTION_STATUS": ["Failed"],
                "LAST_SQL_HASH": ["abc123"],
                "LAST_EXECUTED_AT": ["2026-05-31 10:00:00"],
            }
        )

        board = _warehouse_setting_control_board(exceptions, owner_inventory, closure, audit)
        matrix = _warehouse_intervention_matrix(exceptions, control_board=board, closure=closure)
        by_wh = {row["WAREHOUSE_NAME"]: row for _, row in board.iterrows()}
        by_matrix = {row["WAREHOUSE_NAME"]: row for _, row in matrix.iterrows()}

        self.assertEqual(by_wh["BI_COMPUTE_WH"]["CONTROL_STATE"], "Closure Overdue")
        self.assertEqual(by_wh["LOAD_TASK_WH"]["CONTROL_STATE"], "Execution Failed")
        self.assertEqual(by_wh["DEV_WH"]["CONTROL_STATE"], "Pre-Change Blocked")
        self.assertIn("rollback", by_wh["DEV_WH"]["AUDIT_BLOCKERS"].lower())
        self.assertEqual(by_matrix["BI_COMPUTE_WH"]["INTERVENTION_STATE"], "Telemetry Blocked")
        self.assertEqual(by_matrix["BI_COMPUTE_WH"]["DBA_PRIORITY"], "P0")
        self.assertEqual(by_matrix["LOAD_TASK_WH"]["INTERVENTION_STATE"], "Telemetry Blocked")
        self.assertIn("post-change", by_matrix["DEV_WH"]["PROOF_REQUIRED"])

    def test_warehouse_operator_next_moves_prioritize_closure_and_audit_gates(self):
        exceptions = pd.DataFrame(
            {
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "SIGNAL": ["Credit Spike"],
                "QUEUED_QUERIES": [80],
                "METERED_CREDITS": [42.5],
                "IMPACT_TELEMETRY_REQUIRED": ["Yes"],
            }
        )
        control_board = pd.DataFrame(
            {
                "CONTROL_STATE": ["Closure Overdue", "Execution Failed", "Pre-Change Blocked"],
                "OVERDUE": [1, 0, 0],
                "CLOSURE_BLOCKERS": [1, 0, 0],
                "FAILED_CHANGES": [0, 1, 0],
                "AUDIT_ROWS": [0, 1, 0],
                "AUDIT_READINESS": ["Verification Blocked", "Execution Failed", "Pre-Change Blocked"],
            }
        )
        gates = _warehouse_operator_next_moves(
            score=54,
            exceptions=exceptions,
            control_board=control_board,
            closure=pd.DataFrame({"OVERDUE_OPEN": [1], "FIXED_WITHOUT_VERIFICATION": [0]}),
            execution_audit=pd.DataFrame({"FAILED_CHANGES": [1], "AUDIT_ROWS": [1]}),
        )
        by_gate = {row["GATE"]: row for _, row in gates.iterrows()}

        self.assertEqual(by_gate["Closure status"]["STATE"], "Blocked")
        self.assertEqual(by_gate["Execution audit"]["STATE"], "Failed Execution")
        self.assertEqual(by_gate["Cost guardrail"]["STATE"], "Cost Impact Review")
        self.assertEqual(by_gate["Telemetry route"]["STATE"], "Review Route Blocked")
        self.assertIn("telemetry-pending", by_gate["Closure status"]["NEXT_ACTION"])

    def test_warehouse_action_queue_closure_sql_scores_evidence_gaps(self):
        sql = _warehouse_action_queue_closure_sql(45, "ALFA", "DEV_ALL").upper()

        self.assertIn("OVERWATCH_ACTION_QUEUE", sql)
        self.assertIn("WAREHOUSE HEALTH - CAPACITY BRIEF", sql)
        self.assertIn("WAREHOUSE HEALTH - EFFICIENCY", sql)
        self.assertIn("COMPANY = 'ALFA'", sql)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, sql)
        self.assertIn("FIXED_WITHOUT_VERIFICATION", sql)
        self.assertIn("OWNER_APPROVAL_GAP_ROWS", sql)
        self.assertIn("CLOSURE_READINESS", sql)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_warehouse_capacity_queue_actions_have_safe_verification_and_no_direct_alter(self):
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["Critical"],
                "SIGNAL": ["Credit Spike"],
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "CAPACITY_SCORE": [61.0],
                "QUEUED_QUERIES": [4],
                "SPILL_QUERIES": [1],
                "HIGH_LATENCY_QUERIES": [3],
                "CREDIT_SPIKE_PCT": [82.0],
                "METERED_CREDITS": [91.5],
            }
        )
        captured = {}

        def fake_upsert(_session, actions):
            captured["actions"] = actions
            return len(actions)

        with patch("sections.warehouse_health.get_active_company", return_value="ALFA"), patch(
            "sections.warehouse_health.get_active_environment", return_value="PROD"
        ), patch("sections.warehouse_health.upsert_actions", side_effect=fake_upsert):
            saved = _queue_capacity_findings(object(), exceptions)

        self.assertEqual(saved, 1)
        action = captured["actions"][0]
        self.assertEqual(action["Environment"], "PROD")
        self.assertEqual(action["Route"], "DBA / Cost Route")
        self.assertNotIn("Owner", action)
        self.assertNotIn("Owner Approval Status", action)
        self.assertIn("Cost Route", action["Reviewer"])
        self.assertEqual(action["Telemetry Status"], "Requested")
        self.assertEqual(verification_query_safety_issues(action["Telemetry Query"]), [])
        self.assertIn("post-change telemetry", action["Recovery Status"])
        self.assertIn("Warehouse Settings Manager", action["Generated SQL Fix"])
        self.assertNotIn("ALTER WAREHOUSE", action["Generated SQL Fix"].upper())

    def test_warehouse_efficiency_queue_actions_have_owner_and_closure_evidence(self):
        efficiency = pd.DataFrame(
            {
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "EFFICIENCY_SCORE": [42.0],
                "QUEUE_SEC_PER_CREDIT": [15.2],
                "REMOTE_SPILL_GB_PER_CREDIT": [0.8],
                "METERED_CREDITS": [55.5],
            }
        )
        captured = {}

        def fake_upsert(_session, actions):
            captured["actions"] = actions
            return len(actions)

        with patch("sections.warehouse_health.get_active_company", return_value="ALFA"), patch(
            "sections.warehouse_health.get_active_environment", return_value="PROD"
        ), patch("sections.warehouse_health.upsert_actions", side_effect=fake_upsert):
            _queue_efficiency_findings(object(), efficiency)

        action = captured["actions"][0]
        self.assertEqual(action["Environment"], "PROD")
        self.assertEqual(action["Route"], "BI Platform Route")
        self.assertNotIn("Owner", action)
        self.assertNotIn("Owner Approval Status", action)
        self.assertEqual(action["Recovery SLA Target Hours"], 24)
        self.assertIn("MONITORING_CONTEXT", action["Route Basis"])
        self.assertIn("Warehouse Settings Manager", action["Action"])
        self.assertIn("QUERY_HISTORY", action["Telemetry Query"])
        self.assertEqual(verification_query_safety_issues(action["Telemetry Query"]), [])
        self.assertNotIn("ALTER WAREHOUSE", action["Generated SQL Fix"].upper())

    def test_cortex_cost_score_tracks_threshold_and_user_spikes(self):
        controlled = _cortex_cost_score(
            projected_cost=500,
            budget_usd=1000,
            spike_users=0,
            active_users=20,
        )
        risky = _cortex_cost_score(
            projected_cost=1800,
            budget_usd=1000,
            spike_users=8,
            active_users=20,
        )
        self.assertEqual(_cortex_cost_rating(controlled), "Controlled")
        self.assertLess(risky, 70)
        self.assertEqual(_cortex_cost_rating(risky), "Spiral Risk")

    def test_cortex_cost_score_accepts_control_room_heavy_user_alias(self):
        alias_score = _cortex_cost_score(
            projected_cost=1800,
            budget_usd=1000,
            active_users=20,
            heavy_users=8,
        )
        direct_score = _cortex_cost_score(
            projected_cost=1800,
            budget_usd=1000,
            active_users=20,
            spike_users=8,
        )
        self.assertEqual(alias_score, direct_score)

    def test_cortex_actions_are_signal_specific(self):
        self.assertIn("daily credit limit", _cortex_action_for("Spend Threshold Breach")[0])
        self.assertIn("expected project demand", _cortex_action_for("Cost Per Request Spike")[0])

    def test_cortex_control_markdown_contains_threshold_context(self):
        summary_row = {
            "PROJECTED_30D_COST": 1250.0,
            "ACTIVE_USERS": 12,
            "TOTAL_REQUESTS": 400,
            "TOTAL_CREDITS": 44.5,
        }
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["Critical"],
                "SIGNAL": ["Spend Threshold Breach"],
                "USER_NAME": ["USER_A"],
                "SOURCE": ["CLI"],
                "PROJECTED_30D_COST": [1250.0],
            }
        )
        md = _build_cortex_control_markdown(
            company="ALFA",
            days=30,
            score=62,
            budget_usd=1000.0,
            summary_row=summary_row,
            exceptions=exceptions,
        )
        self.assertIn("OVERWATCH Cortex Cost Control Brief - ALFA", md)
        self.assertIn("Monthly spend threshold: $1,000.00", md)
        self.assertIn("Spend Threshold Breach", md)

    def test_dba_control_room_surfaces_task_and_procedure_regressions(self):
        data = {
            "summary": pd.DataFrame(
                {
                    "FAILED_QUERIES": [0],
                    "QUEUED_QUERIES": [0],
                    "REMOTE_SPILL_QUERIES": [0],
                    "P95_ELAPSED_SEC": [20],
                    "TOTAL_QUERIES": [100],
                }
            ),
            "credits": pd.DataFrame({"PERIOD_CREDITS": [10.0], "PRIOR_CREDITS": [9.0]}),
            "warehouse_pressure": pd.DataFrame(),
            "failed_queries": pd.DataFrame(),
            "task_failures": pd.DataFrame(),
            "task_sla_cost": pd.DataFrame(
                {
                    "SIGNAL": ["Long Running / SLA Risk", "Cost Drift / Release Regression"],
                    "SEVERITY": ["High", "Medium"],
                    "TASK_NAME": ["ROOT_TASK", "ROOT_TASK"],
                    "DETAIL": ["Latest 1,200s vs avg 300s", "Latest 0.05 credits vs avg 0.01"],
                    "PROCEDURE_NAME": ["SP_LOAD_POLICY", "SP_LOAD_POLICY"],
                    "IMPACT_OBJECTS": ["ALFA_EDW_DEV.PUBLIC.POLICY_FACT", "ALFA_EDW_DEV.PUBLIC.POLICY_FACT"],
                }
            ),
            "procedure_sla_cost": pd.DataFrame(
                {
                    "SIGNAL": ["Procedure Cost Regression"],
                    "SEVERITY": ["High"],
                    "PROCEDURE_NAME": ["ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY"],
                    "LATEST_ELAPSED_SEC": [1200],
                    "AVG_ELAPSED_SEC": [300],
                    "EST_TOTAL_CREDITS": [0.05],
                }
            ),
            "failed_logins": pd.DataFrame(),
            "object_changes": pd.DataFrame(),
            "action_queue": pd.DataFrame(),
        }
        exceptions = _dba_control_severity_rows(data, credit_price=3.0)
        self.assertIn("Task SLA or cost regression", set(exceptions["Signal"]))
        self.assertIn("Stored procedure release regression", set(exceptions["Signal"]))

    def test_release_compare_flags_task_and_procedure_regressions(self):
        before_tasks = pd.DataFrame(
            {
                "TASK_NAME": ["ROOT_TASK", "ROOT_TASK"],
                "STATE": ["SUCCEEDED", "SUCCEEDED"],
                "DURATION_SEC": [300, 330],
                "EST_TOTAL_CREDITS": [0.01, 0.01],
                "PROCEDURE_NAME": ["SP_LOAD_POLICY", "SP_LOAD_POLICY"],
                "IMPACT_OBJECTS": ["ALFA_EDW_DEV.PUBLIC.POLICY_FACT", ""],
            }
        )
        after_tasks = pd.DataFrame(
            {
                "TASK_NAME": ["ROOT_TASK", "ROOT_TASK", "ROOT_TASK"],
                "STATE": ["SUCCEEDED", "FAILED", "SUCCEEDED"],
                "ERROR_CODE": ["", "1001", ""],
                "DURATION_SEC": [900, 1200, 870],
                "EST_TOTAL_CREDITS": [0.04, 0.05, 0.04],
                "PROCEDURE_NAME": ["SP_LOAD_POLICY", "SP_LOAD_POLICY", "SP_LOAD_POLICY"],
                "IMPACT_OBJECTS": ["ALFA_EDW_DEV.PUBLIC.POLICY_FACT", "", ""],
            }
        )
        task_compare = _compare_release_windows(before_tasks, after_tasks, "TASK_NAME")
        self.assertEqual(task_compare.iloc[0]["SEVERITY"], "High")
        self.assertIn("more failures", task_compare.iloc[0]["SIGNAL"])
        self.assertGreater(task_compare.iloc[0]["AVG_DURATION_CHANGE_PCT"], 100)

        before_proc = pd.DataFrame(
            {
                "PROCEDURE_NAME": ["ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY"],
                "TOTAL_ELAPSED_SEC": [300],
                "EST_TOTAL_CREDITS": [0.01],
            }
        )
        after_proc = pd.DataFrame(
            {
                "PROCEDURE_NAME": ["ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY"],
                "TOTAL_ELAPSED_SEC": [900],
                "EST_TOTAL_CREDITS": [0.04],
            }
        )
        proc_compare = _compare_release_windows(before_proc, after_proc, "PROCEDURE_NAME")
        report = _build_release_compare_report(
            "ALFA",
            {
                "task_compare": task_compare,
                "procedure_compare": proc_compare,
                "before_label": "2026-05-01 to 2026-05-07",
                "after_label": "2026-05-08 to 2026-05-14",
            },
            3.0,
        )
        self.assertIn("OVERWATCH Release Compare - ALFA", report)
        self.assertIn("ROOT_TASK", report)
        self.assertIn("SP_LOAD_POLICY", report)

    def test_task_ops_score_weights_failures_suspensions_and_sla(self):
        stable = _task_ops_score(
            failed_runs=0,
            suspended_tasks=0,
            long_running_tasks=0,
            total_runs=100,
            total_tasks=20,
        )
        risky = _task_ops_score(
            failed_runs=15,
            suspended_tasks=5,
            long_running_tasks=20,
            total_runs=100,
            total_tasks=20,
        )
        self.assertGreaterEqual(stable, 95)
        self.assertLess(risky, 65)

    def test_task_definition_extracts_procedure_call(self):
        self.assertEqual(
            _procedure_from_definition("CALL ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY();"),
            "ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY",
        )
        self.assertEqual(_procedure_from_definition("SELECT 1"), "")

    def test_task_graph_dot_builds_dependency_edges(self):
        inventory = pd.DataFrame(
            {
                "NAME": ["ROOT_TASK", "CHILD_TASK"],
                "STATE": ["STARTED", "SUSPENDED"],
                "PREDECESSORS": ["[]", "ALFA_EDW_DEV.PUBLIC.ROOT_TASK"],
            }
        )
        self.assertEqual(_parse_task_predecessors("['DB.SCHEMA.ROOT_TASK']"), ["ROOT_TASK"])
        dot = _build_task_graph_dot(inventory)
        self.assertIn('"ROOT_TASK" -> "CHILD_TASK"', dot)
        self.assertIn("rankdir=LR", dot)

    def test_task_graph_control_sql_orders_resume_children_before_root(self):
        inventory = pd.DataFrame(
            {
                "DATABASE_NAME": ["ALFA_EDW_DEV", "ALFA_EDW_DEV", "ALFA_EDW_DEV"],
                "SCHEMA_NAME": ["PUBLIC", "PUBLIC", "PUBLIC"],
                "NAME": ["ROOT_TASK", "CHILD_TASK", "GRANDCHILD_TASK"],
                "STATE": ["SUSPENDED", "SUSPENDED", "SUSPENDED"],
                "PREDECESSORS": ["[]", "ALFA_EDW_DEV.PUBLIC.ROOT_TASK", "ALFA_EDW_DEV.PUBLIC.CHILD_TASK"],
            }
        )
        graph = _collect_graph_tasks(inventory, "ROOT_TASK")
        self.assertEqual(set(graph["NAME"]), {"ROOT_TASK", "CHILD_TASK", "GRANDCHILD_TASK"})
        resume_sql = _admin_sql_for_graph(graph, "ROOT_TASK", "RESUME")
        self.assertTrue(resume_sql[-1].endswith('"ROOT_TASK" RESUME'))
        self.assertIn('"CHILD_TASK" RESUME', resume_sql[0])
        suspend_sql = _admin_sql_for_graph(graph, "ROOT_TASK", "SUSPEND")
        self.assertEqual(len(suspend_sql), 1)
        self.assertTrue(suspend_sql[0].endswith('"ROOT_TASK" SUSPEND'))
        execute_sql = _admin_sql_for_task(inventory.iloc[0], "EXECUTE")
        self.assertEqual(execute_sql, ['EXECUTE TASK "ALFA_EDW_DEV"."PUBLIC"."ROOT_TASK"'])

    def test_admin_preflight_sql_is_read_only_and_privilege_oriented(self):
        row = pd.Series(
            {
                "DATABASE_NAME": "ALFA_EDW_DEV",
                "SCHEMA_NAME": "PUBLIC",
                "NAME": "ROOT_TASK",
            }
        )
        sql = build_admin_preflight_sql(row).upper()
        self.assertIn("CURRENT_ROLE()", sql)
        self.assertIn("SHOW GRANTS ON TASK", sql)
        self.assertIn("INFORMATION_SCHEMA.TASK_HISTORY", sql)
        self.assertNotIn("ALTER TASK", sql)
        self.assertNotIn("EXECUTE TASK", sql)

    def test_task_ops_frames_link_procedures_and_flag_exceptions(self):
        inventory = pd.DataFrame(
            {
                "DATABASE_NAME": ["ALFA_EDW_DEV", "ALFA_EDW_DEV"],
                "SCHEMA_NAME": ["PUBLIC", "PUBLIC"],
                "NAME": ["ROOT_TASK", "CHILD_TASK"],
                "STATE": ["started", "suspended"],
                "SCHEDULE": ["USING CRON", ""],
                "WAREHOUSE": ["BI_COMPUTE_WH", "BI_COMPUTE_WH"],
                "PREDECESSORS": ["[]", "ALFA_EDW_DEV.PUBLIC.ROOT_TASK"],
                "DEFINITION": [
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_ROOT();",
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_CHILD();",
                ],
            }
        )
        history = pd.DataFrame(
            {
                "TASK_NAME": ["ROOT_TASK", "ROOT_TASK"],
                "SCHEDULED_TIME": pd.to_datetime(["2026-05-01", "2026-05-02"]),
                "STATE": ["SUCCEEDED", "FAILED_WITH_ERROR"],
                "DURATION_SEC": [100, 400],
                "QUERY_ID": ["q1", "q2"],
                "ERROR_MESSAGE": ["", "bad object"],
            }
        )
        summary, exceptions, latest = _build_task_ops_frames(inventory, history)
        self.assertEqual(summary["TOTAL_TASKS"], 2)
        self.assertEqual(summary["FAILED_RUNS"], 1)
        self.assertEqual(summary["SUSPENDED_TASKS"], 1)
        self.assertEqual(summary["BLOCKED_RECOVERIES"], 3)
        self.assertEqual(summary["OPEN_RECOVERIES"], 1)
        self.assertEqual(summary["RECOVERY_SLA_BREACHES"], 1)
        self.assertIn("SP_ROOT", str(latest.get("PROCEDURE_NAME", "")))
        self.assertIn("Failed Task Run", set(exceptions["SIGNAL"]))
        self.assertIn("Suspended Task", set(exceptions["SIGNAL"]))
        self.assertIn("OWNER_APPROVAL_STATE", exceptions.columns)
        failed = exceptions[exceptions["SIGNAL"] == "Failed Task Run"].iloc[0]
        self.assertEqual(failed["INCIDENT_PRIORITY"], "P2 - Production Risk")
        self.assertEqual(failed["DOWNSTREAM_TASK_COUNT"], 1)
        self.assertEqual(failed["RECOVERY_READINESS"], "Blocked - fix failure root cause first")
        self.assertEqual(failed["RECOVERY_STATE"], "Open Failure")

    def test_task_ops_frames_flag_sla_and_cost_regression(self):
        inventory = pd.DataFrame(
            {
                "DATABASE_NAME": ["ALFA_EDW_DEV"],
                "SCHEMA_NAME": ["PUBLIC"],
                "NAME": ["ROOT_TASK"],
                "STATE": ["STARTED"],
                "SCHEDULE": ["USING CRON"],
                "WAREHOUSE": ["BI_COMPUTE_WH"],
                "PREDECESSORS": ["[]"],
                "DEFINITION": ["CALL ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY();"],
            }
        )
        history = pd.DataFrame(
            {
                "TASK_NAME": ["ROOT_TASK", "ROOT_TASK", "ROOT_TASK"],
                "SCHEDULED_TIME": pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"]),
                "STATE": ["SUCCEEDED", "SUCCEEDED", "SUCCEEDED"],
                "DURATION_SEC": [300, 320, 1200],
                "QUERY_ID": ["q1", "q2", "q3"],
                "ERROR_MESSAGE": ["", "", ""],
            }
        )
        query_details = pd.DataFrame(
            {
                "QUERY_ID": ["q1", "q2", "q3"],
                "WAREHOUSE_SIZE": ["Small", "Small", "Large"],
                "QUERY_ELAPSED_SEC": [300, 320, 1200],
                "CLOUD_CREDITS": [0.001, 0.001, 0.02],
                "QUERY_TEXT": [
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY();",
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY();",
                    "INSERT INTO ALFA_EDW_DEV.PUBLIC.POLICY_FACT SELECT * FROM ALFA_RAW.PUBLIC.POLICY;",
                ],
            }
        )
        summary, exceptions, latest = _build_task_ops_frames(inventory, history, query_details)
        self.assertEqual(summary["LONG_RUNNING_TASKS"], 1)
        self.assertEqual(summary["COST_DRIFT_TASKS"], 1)
        self.assertIn("Long Running / SLA Risk", set(exceptions["SIGNAL"]))
        self.assertIn("Cost Drift / Release Regression", set(exceptions["SIGNAL"]))
        self.assertIn("POLICY_FACT", str(latest.iloc[0]["IMPACT_OBJECTS"]))
        self.assertIn("INCIDENT_PRIORITY", exceptions.columns)

    def test_task_ops_frames_count_live_running_job_status(self):
        inventory = pd.DataFrame(
            {
                "DATABASE_NAME": ["ALFA_EDW_DEV"],
                "SCHEMA_NAME": ["PUBLIC"],
                "NAME": ["ROOT_TASK"],
                "STATE": ["STARTED"],
                "PREDECESSORS": ["[]"],
                "DEFINITION": ["CALL ALFA_EDW_DEV.PUBLIC.SP_ROOT();"],
            }
        )
        history = pd.DataFrame(
            {
                "TASK_NAME": ["ROOT_TASK", "ROOT_TASK"],
                "SCHEDULED_TIME": pd.to_datetime(["2026-05-01 00:00", "2026-05-01 01:00"]),
                "STATE": ["SUCCEEDED", "RUNNING"],
                "DURATION_SEC": [90, 180],
                "QUERY_ID": ["q_success", "q_running"],
                "ERROR_MESSAGE": ["", ""],
            }
        )

        summary, _exceptions, latest = _build_task_ops_frames(inventory, history)

        self.assertEqual(summary["RUNNING_TASKS"], 1)
        self.assertEqual(summary["LATEST_SUCCESS_TASKS"], 0)
        self.assertEqual(summary["LATEST_FAILED_TASKS"], 0)
        self.assertEqual(str(latest.iloc[0]["STATE"]), "RUNNING")

    def test_task_status_job_status_board_surfaces_performance_and_errors(self):
        summary = {
            "TOTAL_TASKS": 4,
            "TOTAL_RUNS": 12,
            "FAILED_RUNS": 2,
            "LATEST_FAILED_TASKS": 1,
            "RUNNING_TASKS": 1,
            "LONG_RUNNING_TASKS": 1,
            "COST_DRIFT_TASKS": 1,
            "OPEN_RECOVERIES": 1,
            "BLOCKED_RECOVERIES": 1,
            "RECOVERY_SLA_BREACHES": 1,
            "RECOVERY_SLA_TARGET_HOURS": 4,
            "P1_INCIDENTS": 0,
        }
        latest = pd.DataFrame(
            {
                "TASK_NAME": ["ROOT_TASK", "CHILD_TASK"],
                "ROOT_TASK_NAME": ["ROOT_TASK", "ROOT_TASK"],
                "STATE": ["FAILED_WITH_ERROR", "RUNNING"],
                "SCHEDULED_TIME": pd.to_datetime(["2026-05-01 10:00", "2026-05-01 10:05"]),
                "QUERY_ID": ["q_failed", "q_running"],
                "ERROR_MESSAGE": ["SQL compilation error: missing table", ""],
                "EST_TOTAL_CREDITS": [0.25, 0.0],
            }
        )
        exceptions = pd.DataFrame(
            {
                "INCIDENT_PRIORITY": ["P2 - Production Risk"],
                "SEVERITY": ["High"],
                "SIGNAL": ["Failed Task Run"],
                "TASK_NAME": ["ROOT_TASK"],
                "ROOT_TASK_NAME": ["ROOT_TASK"],
                "STATE": ["FAILED_WITH_ERROR"],
                "DETAIL": ["SQL compilation error: missing table"],
                "QUERY_ID": ["q_failed"],
                "EST_TOTAL_CREDITS": [0.25],
            }
        )

        board = _build_task_status_job_status_board(summary, latest, exceptions)
        errors = _build_task_status_error_board(exceptions, latest)
        by_view = {row["TASK_STATUS_VIEW"]: row for _, row in board.iterrows()}

        self.assertEqual(by_view["Job Status"]["STATE"], "Needs Triage")
        self.assertEqual(by_view["Performance Indicators"]["COUNT"], 2)
        self.assertEqual(by_view["Errors"]["COUNT"], 1)
        self.assertNotIn("Scheduler Feed", by_view)
        self.assertIn("FAILED_WITH_ERROR", by_view["Job Status"]["EVIDENCE"])
        self.assertFalse(errors.empty)
        self.assertIn("missing table", errors.iloc[0]["ERROR_SIGNATURE"])
        self.assertIn("EST_TOTAL_CREDITS", errors.columns)

    def test_task_status_external_feed_setup_is_removed(self):
        task_text = (ROOT / ".overwatch_final" / "sections" / "task_management.py").read_text(encoding="utf-8").upper()

        self.assertNotIn("OVERWATCH_EXTERNAL_CONTROL_FEED", task_text)
        self.assertNotIn("SNOWFLAKE TASK FEED SETUP", task_text)
        self.assertNotIn("OVERWATCH_TASK_STATUS_FEED_STAGE", task_text)

    def test_task_recovery_sla_frame_tracks_open_and_late_recoveries(self):
        inventory = pd.DataFrame(
            {
                "DATABASE_NAME": ["ALFA_EDW_DEV", "ALFA_EDW_DEV"],
                "SCHEMA_NAME": ["PUBLIC", "PUBLIC"],
                "NAME": ["ROOT_TASK", "CHILD_TASK"],
                "STATE": ["STARTED", "STARTED"],
                "PREDECESSORS": ["[]", "ALFA_EDW_DEV.PUBLIC.ROOT_TASK"],
                "DEFINITION": [
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_ROOT();",
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_CHILD();",
                ],
            }
        )
        history = pd.DataFrame(
            {
                "TASK_NAME": ["ROOT_TASK", "ROOT_TASK", "CHILD_TASK"],
                "SCHEDULED_TIME": pd.to_datetime(["2026-05-01 00:00", "2026-05-01 07:00", "2026-05-01 01:00"]),
                "COMPLETED_TIME": pd.to_datetime(["2026-05-01 00:10", "2026-05-01 07:10", "2026-05-01 01:05"]),
                "STATE": ["FAILED", "SUCCEEDED", "FAILED_WITH_ERROR"],
                "DURATION_SEC": [600, 610, 300],
                "QUERY_ID": ["q_fail_root", "q_success_root", "q_fail_child"],
                "ERROR_MESSAGE": ["object missing", "", "privilege denied"],
            }
        )

        recovery = _build_task_recovery_sla_frame(
            history,
            inventory,
            target_hours=4,
            current_time=pd.Timestamp("2026-05-01 08:00"),
        )

        by_task = {row["TASK_NAME"]: row for _, row in recovery.iterrows()}
        self.assertEqual(by_task["ROOT_TASK"]["RECOVERY_STATE"], "Recovered Late")
        self.assertAlmostEqual(float(by_task["ROOT_TASK"]["RECOVERY_HOURS"]), 7.0)
        self.assertEqual(by_task["CHILD_TASK"]["RECOVERY_STATE"], "Open Failure")
        self.assertEqual(by_task["CHILD_TASK"]["OWNER_APPROVAL_STATE"], "Root-cause review required")
        self.assertEqual(by_task["CHILD_TASK"]["ONCALL_PRIMARY"], "")
        self.assertEqual(by_task["CHILD_TASK"]["APPROVAL_GROUP"], "")
        self.assertIn("MONITORING_CONTEXT", by_task["CHILD_TASK"]["OWNER_SOURCE"])
        self.assertIn("P", by_task["CHILD_TASK"]["INCIDENT_PRIORITY"])

    def test_task_recovery_command_board_prioritizes_blocked_retries(self):
        exceptions = pd.DataFrame([{
            "INCIDENT_PRIORITY": "P1 - Graph Incident",
            "SEVERITY": "Critical",
            "SIGNAL": "Failed Task Run",
            "TASK_NAME": "CHILD_TASK",
            "ROOT_TASK_NAME": "ROOT_TASK",
            "GRAPH_ROLE": "Child",
            "DOWNSTREAM_TASK_COUNT": 4,
            "RECOVERY_READINESS": "Blocked - fix failure root cause first",
            "OWNER_APPROVAL_STATE": "Root-cause review required",
            "ONCALL_PRIMARY": "",
            "APPROVAL_GROUP": "Pipeline Route",
            "NEXT_ACTION": "Review task error and retry after correction.",
            "VERIFY_AFTER_FIX": "Latest TASK_HISTORY run succeeds.",
        }])
        recovery = pd.DataFrame([{
            "INCIDENT_PRIORITY": "P2 - Open Recovery",
            "TASK_NAME": "ROOT_TASK",
            "ROOT_TASK_NAME": "ROOT_TASK",
            "GRAPH_ROLE": "Root",
            "DOWNSTREAM_TASK_COUNT": 4,
            "RECOVERY_STATE": "Open Failure",
            "OWNER_APPROVAL_STATE": "Root-cause review required",
            "ONCALL_PRIMARY": "",
            "APPROVAL_GROUP": "Pipeline Route",
        }])

        board = _task_recovery_command_board(exceptions, recovery)

        self.assertFalse(board.empty)
        self.assertEqual(board.iloc[0]["COMMAND_STATE"], "Blocked")
        self.assertEqual(board.iloc[0]["INCIDENT_PRIORITY"], "P1 - Graph Incident")
        self.assertIn("root-cause review", " ".join(board["OWNER_APPROVAL_STATE"].astype(str)).lower())
        self.assertIn("confirm", " ".join(board["NEXT_ACTION"].astype(str)).lower())

    def test_task_critical_path_snapshot_ranks_graph_blast_radius(self):
        inventory = pd.DataFrame(
            {
                "NAME": ["ROOT_TASK", "CHILD_A", "CHILD_B", "LEAF_TASK"],
                "STATE": ["STARTED", "STARTED", "SUSPENDED", "STARTED"],
                "WAREHOUSE": ["WH_A", "WH_A", "WH_B", "WH_B"],
                "PREDECESSORS": ["[]", "ROOT_TASK", "ROOT_TASK", "CHILD_A"],
                "DEFINITION": [
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_ROOT();",
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_A();",
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_B();",
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_LEAF();",
                ],
            }
        )
        history = pd.DataFrame(
            {
                "TASK_NAME": ["ROOT_TASK", "CHILD_A", "CHILD_B"],
                "SCHEDULED_TIME": pd.to_datetime(["2026-05-01", "2026-05-01", "2026-05-01"]),
                "STATE": ["SUCCEEDED", "FAILED_WITH_ERROR", "SUCCEEDED"],
                "DURATION_SEC": [120, 900, 60],
                "ERROR_MESSAGE": ["", "bad column", ""],
            }
        )

        snapshot = _build_task_critical_path_snapshot(inventory, history)

        self.assertFalse(snapshot.empty)
        self.assertEqual(snapshot.iloc[0]["ROOT_TASK_NAME"], "ROOT_TASK")
        self.assertEqual(snapshot.iloc[0]["CRITICAL_PATH_STATE"], "Incident Path")
        self.assertGreaterEqual(int(snapshot.iloc[0]["DOWNSTREAM_TASK_COUNT"]), 3)
        self.assertIn("SP_ROOT", snapshot.iloc[0]["PROCEDURES"])

    def test_task_graph_impact_counts_downstream_tasks(self):
        inventory = pd.DataFrame(
            {
                "NAME": ["ROOT_TASK", "CHILD_A", "CHILD_B", "LEAF_TASK"],
                "PREDECESSORS": ["[]", "ROOT_TASK", "ROOT_TASK", "CHILD_A"],
            }
        )

        annotated = _annotate_task_graph_impact(inventory)
        root = annotated[annotated["NAME"] == "ROOT_TASK"].iloc[0]
        leaf = annotated[annotated["NAME"] == "LEAF_TASK"].iloc[0]

        self.assertEqual(root["DOWNSTREAM_TASK_COUNT"], 3)
        self.assertEqual(root["GRAPH_ROLE"], "Root")
        self.assertEqual(root["BLAST_RADIUS"], "Medium")
        self.assertEqual(leaf["DOWNSTREAM_TASK_COUNT"], 0)
        self.assertEqual(leaf["GRAPH_ROLE"], "Leaf")

    def test_extract_object_candidates_from_visible_sql(self):
        objects = _extract_object_candidates(
            "MERGE INTO ALFA_EDW_DEV.PUBLIC.TGT t USING ALFA_RAW.PUBLIC.SRC s "
            "ON t.ID=s.ID WHEN MATCHED THEN UPDATE SET t.C=1"
        )
        self.assertIn("ALFA_EDW_DEV.PUBLIC.TGT", objects)
        self.assertIn("ALFA_RAW.PUBLIC.SRC", objects)

    def test_task_ops_markdown_contains_snowflake_context(self):
        md = _build_task_ops_markdown(
            company="ALFA",
            days=7,
            score=88,
            summary={
                "TOTAL_TASKS": 10,
                "TOTAL_RUNS": 100,
                "FAILED_RUNS": 2,
                "SUSPENDED_TASKS": 1,
                "LONG_RUNNING_TASKS": 3,
                "COST_DRIFT_TASKS": 1,
            },
            exceptions=pd.DataFrame(
                {
                    "SEVERITY": ["High"],
                    "SIGNAL": ["Failed Task Run"],
                    "TASK_NAME": ["LOAD_POLICY"],
                    "PROCEDURE_NAME": ["SP_LOAD_POLICY"],
                    "DETAIL": ["bad object"],
                    "IMPACT_OBJECTS": ["ALFA_EDW_DEV.PUBLIC.POLICY"],
                }
            ),
        )
        self.assertIn("OVERWATCH Task Graph Operations Brief - ALFA", md)
        self.assertIn("Snowflake task operations view", md)
        self.assertIn("Snowflake task handoff state", md)
        self.assertIn("Failed Task Run", md)
        self.assertIn("Cost drift/release-regression candidates", md)
        self.assertIn("Admin actions require Snowflake task privileges", md)

    def test_task_actions_are_signal_specific(self):
        self.assertIn("retry the root task", _task_action_for("Failed Task Run")[0])
        self.assertIn("resume only after review", _task_action_for("Suspended Task")[0])
        self.assertIn("historical average", _task_action_for("Long Running / SLA Risk")[0])

    def test_task_management_defaults_to_task_status_job_status_brief(self):
        self.assertEqual(TASK_CONTROL_VIEWS[0], "Job Status Brief")
        self.assertIn("Snowflake task handoff", TASK_CONTROL_DETAILS["Job Status Brief"])
        self.assertEqual(_task_ops_workflow_for("Healthy task graph"), "Job Status Brief")
        self.assertEqual(_task_ops_workflow_for("Failed Task Run"), "Failure Console")
        self.assertEqual(_task_ops_workflow_for("Long Running / SLA Risk"), "SLA & Cost Drift")

    def test_failure_diagnosis_classifies_common_task_errors(self):
        self.assertEqual(
            _failure_diagnosis("SQL compilation error: invalid identifier WAREHOUSE_NAME")["CATEGORY"],
            "Object Dependency / Drift",
        )
        self.assertEqual(
            _failure_diagnosis("Insufficient privileges to operate on task")["CATEGORY"],
            "Privilege / RBAC",
        )
        self.assertEqual(
            _failure_diagnosis("Numeric value 'NONE' is not recognized")["CATEGORY"],
            "Data Quality / Type Conversion",
        )

    def test_failure_console_frames_enrich_and_group_failures(self):
        history = pd.DataFrame(
            {
                "TASK_NAME": ["ROOT_TASK", "CHILD_TASK"],
                "SCHEDULED_TIME": pd.to_datetime(["2026-05-28 10:00", "2026-05-28 11:00"]),
                "STATE": ["FAILED", "SUCCEEDED"],
                "DURATION_SEC": [130, 20],
                "QUERY_ID": ["q_failed", "q_ok"],
                "ERROR_MESSAGE": ["SQL compilation error: invalid identifier 'CUSTOMER_ID'", ""],
            }
        )
        inventory = pd.DataFrame(
            {
                "DATABASE_NAME": ["ALFA_EDW_DEV", "ALFA_EDW_DEV"],
                "SCHEMA_NAME": ["PUBLIC", "PUBLIC"],
                "NAME": ["ROOT_TASK", "CHILD_TASK"],
                "STATE": ["STARTED", "STARTED"],
                "WAREHOUSE": ["BI_COMPUTE_WH", "BI_COMPUTE_WH"],
                "PREDECESSORS": ["[]", "ALFA_EDW_DEV.PUBLIC.ROOT_TASK"],
                "DEFINITION": [
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY();",
                    "CALL ALFA_EDW_DEV.PUBLIC.SP_CHILD();",
                ],
            }
        )
        query_details = pd.DataFrame(
            {
                "QUERY_ID": ["q_failed"],
                "QUERY_TEXT": ["CALL ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY();"],
                "USER_NAME": ["RQ4336"],
                "ROLE_NAME": ["SNOW_BI_REPORTING"],
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "QUERY_ELAPSED_SEC": [128.5],
            }
        )

        summary, failures, patterns = _build_failure_console_frames(history, inventory, query_details)
        self.assertEqual(summary["FAILURES"], 1)
        self.assertEqual(summary["TASKS"], 1)
        self.assertEqual(summary["BLOCKED_RECOVERIES"], 1)
        self.assertEqual(failures.iloc[0]["PROCEDURE_NAME"], "ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY")
        self.assertEqual(failures.iloc[0]["FAILURE_CATEGORY"], "Object Dependency / Drift")
        self.assertEqual(failures.iloc[0]["INCIDENT_PRIORITY"], "P2 - Production Risk")
        self.assertEqual(failures.iloc[0]["RECOVERY_READINESS"], "Blocked - object dependency fix first")
        self.assertEqual(failures.iloc[0]["DOWNSTREAM_TASK_COUNT"], 1)
        self.assertIn("CUSTOMER_ID", failures.iloc[0]["VERIFY_AFTER_FIX"])
        self.assertIn("EXECUTE TASK", failures.iloc[0]["RETRY_SQL"])
        self.assertEqual(patterns.iloc[0]["FAILURE_COUNT"], 1)
        self.assertEqual(patterns.iloc[0]["TASK_COUNT"], 1)
        self.assertIn("RECOVERY_READINESS", patterns.columns)
        self.assertIn("RECOMMENDED_ACTION", patterns.columns)
        self.assertIn("CUSTOMER_ID", patterns.iloc[0]["ERROR_SIGNATURE"])

    def test_failure_runbook_markdown_contains_triage_context(self):
        failures = pd.DataFrame(
            {
                "TASK_NAME": ["ROOT_TASK"],
                "QUERY_ID": ["q_failed"],
                "PROCEDURE_NAME": ["ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY"],
                "FAILURE_CATEGORY": ["Object Dependency / Drift"],
                "PROBABLE_CAUSE": ["A referenced object changed."],
                "RECOMMENDED_ACTION": ["Validate object names and grants."],
                "RETRY_SQL": ['EXECUTE TASK "ALFA_EDW_DEV"."PUBLIC"."ROOT_TASK";'],
            }
        )
        patterns = pd.DataFrame(
            {
                "FAILURE_CATEGORY": ["Object Dependency / Drift"],
                "ERROR_SIGNATURE": ["invalid identifier CUSTOMER_ID"],
                "FAILURE_COUNT": [1],
                "TASKS": ["ROOT_TASK"],
            }
        )
        md = _build_failure_runbook_markdown(
            company="ALFA",
            days=7,
            summary={"FAILURES": 1, "TASKS": 1, "CATEGORIES": 1, "CRITICAL": 1},
            failures=failures,
            patterns=patterns,
        )
        self.assertIn("OVERWATCH Failure Runbook - ALFA", md)
        self.assertIn("Object Dependency / Drift", md)
        self.assertIn("Retry plan after fix", md)
        self.assertIn("P1 graph incidents", md)
        self.assertIn("Telemetry Limits", md)

    def test_procedure_ops_frames_identify_orphans_and_task_links(self):
        procedures = pd.DataFrame(
            {
                "PROCEDURE_CATALOG": ["ALFA_EDW_DEV", "ALFA_EDW_DEV"],
                "PROCEDURE_SCHEMA": ["PUBLIC", "PUBLIC"],
                "PROCEDURE_NAME": ["SP_ROOT", "SP_UNUSED"],
                "PROCEDURE_OWNER": ["OWNER_A", "OWNER_B"],
                "PROCEDURE_LANGUAGE": ["SQL", "SQL"],
                "LAST_ALTERED": pd.to_datetime(["2026-05-01", "2026-05-02"]),
            }
        )
        tasks = pd.DataFrame(
            {
                "NAME": ["ROOT_TASK"],
                "STATE": ["STARTED"],
                "DEFINITION": ["CALL ALFA_EDW_DEV.PUBLIC.SP_ROOT();"],
            }
        )
        calls = pd.DataFrame(
            {
                "PROCEDURE_NAME": ["ALFA_EDW_DEV.PUBLIC.SP_ROOT"],
                "CALL_COUNT": [4],
                "DOWNSTREAM_QUERY_COUNT": [12],
                "TOTAL_CREDITS": [1.5],
                "LAST_CALL": pd.to_datetime(["2026-05-03"]),
            }
        )
        summary, exceptions, joined = _build_procedure_ops_frames(procedures, tasks, calls)
        self.assertEqual(summary["PROCEDURES"], 2)
        self.assertEqual(summary["LINKED_TO_TASKS"], 1)
        self.assertEqual(summary["OWNER_REVIEW_REQUIRED"], 1)
        self.assertEqual(_procedure_key("ALFA_EDW_DEV.PUBLIC.SP_ROOT()"), "SP_ROOT")
        self.assertEqual(_procedure_from_task_definition("CALL DB.SCH.SP_ROOT();"), "DB.SCH.SP_ROOT")
        self.assertIn("Orphan Procedure Candidate", set(exceptions["SIGNAL"]))
        self.assertIn("TASK_COUNT", joined.columns)
        self.assertIn("ORCHESTRATION_STATUS", joined.columns)
        self.assertIn("DATABASE_NAME", joined.columns)
        self.assertIn("SCHEMA_NAME", joined.columns)
        self.assertIn("PROCEDURE_CONTEXT", joined.columns)
        unused = joined[joined["PROC_KEY"] == "SP_UNUSED"].iloc[0]
        self.assertEqual(unused["DATABASE_NAME"], "ALFA_EDW_DEV")
        self.assertEqual(unused["SCHEMA_NAME"], "PUBLIC")
        self.assertEqual(unused["PROCEDURE_CONTEXT"], "ALFA_EDW_DEV.PUBLIC.SP_UNUSED")
        self.assertEqual(unused["ORCHESTRATION_STATUS"], "No recent execution telemetry")
        self.assertEqual(unused["OWNER_REVIEW"], "Required")

    def test_procedure_sla_frames_flag_runtime_and_cost_regression(self):
        runs = pd.DataFrame(
            {
                "PROCEDURE_NAME": [
                    "ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY",
                    "ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY",
                    "ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY",
                ],
                "ROOT_QUERY_ID": ["q1", "q2", "q3"],
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH", "BI_COMPUTE_WH", "BI_COMPUTE_WH"],
                "WAREHOUSE_SIZE": ["Small", "Small", "Large"],
                "START_TIME": pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"]),
                "TOTAL_ELAPSED_SEC": [300, 310, 1300],
                "CLOUD_CREDITS": [0.001, 0.001, 0.02],
                "DOWNSTREAM_QUERY_COUNT": [4, 4, 12],
            }
        )
        summary, exceptions, latest = _build_procedure_sla_frames(runs)
        self.assertEqual(summary["PROCEDURES"], 1)
        self.assertEqual(summary["SLA_BREACHES"], 1)
        self.assertEqual(summary["COST_BREACHES"], 1)
        self.assertIn("Procedure Runtime SLA Breach", set(exceptions["SIGNAL"]))
        self.assertIn("Procedure Cost Regression", set(exceptions["SIGNAL"]))
        self.assertIn("DATABASE_NAME", latest.columns)
        self.assertIn("SCHEMA_NAME", latest.columns)
        self.assertEqual(latest.iloc[0]["DATABASE_NAME"], "ALFA_EDW_DEV")
        self.assertEqual(latest.iloc[0]["SCHEMA_NAME"], "PUBLIC")
        self.assertEqual(latest.iloc[0]["PROCEDURE_CONTEXT"], "ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY")
        self.assertGreater(latest.iloc[0]["RUNTIME_CHANGE_PCT"], 0)
        self.assertIn("OPTIMIZATION_SCORE", latest.columns)
        self.assertIn("OPTIMIZATION_ISSUE", exceptions.columns)
        self.assertIn("SAFE_NEXT_ACTION", exceptions.columns)
        self.assertGreater(latest.iloc[0]["OPTIMIZATION_SCORE"], 0)
        advisor_summary, advisor_board = _procedure_analysis_summary(latest, exceptions, credit_price=3.68)
        self.assertEqual(advisor_summary["runtime_regressions"], 1)
        self.assertEqual(advisor_summary["cost_regressions"], 1)
        self.assertGreater(advisor_summary["estimated_cost_usd"], 0)
        self.assertGreaterEqual(advisor_summary["findings"], 2)
        self.assertIn("ACTION_TYPE", advisor_board.columns)
        self.assertIn("SAFE_NEXT_ACTION", advisor_board.columns)
        self.assertIn("DO_NOT_DO", advisor_board.columns)
        self.assertIn("EST_TOTAL_COST_USD", advisor_board.columns)
        self.assertIn("CONFIDENCE", advisor_board.columns)
        self.assertIn("WORKFLOW_ROUTE", advisor_board.columns)
        self.assertIn("DECISION", advisor_board.columns)
        self.assertIn("REVIEW_STAGE", advisor_board.columns)
        self.assertIn("IMPACT_SUMMARY", advisor_board.columns)
        self.assertIn("VERIFY_NEXT", advisor_board.columns)
        self.assertIn("EXECUTION_GUARDRAIL", advisor_board.columns)
        self.assertIn("Fix runtime regression", set(advisor_board["ACTION_TYPE"]))
        self.assertIn("Review cost regression", set(advisor_board["ACTION_TYPE"]))
        self.assertIn("Review before next scheduled run", set(advisor_board["DECISION"]))
        self.assertTrue(advisor_board["VERIFY_NEXT"].astype(str).str.len().gt(0).all())
        self.assertTrue(
            advisor_board["EXECUTION_GUARDRAIL"].astype(str).str.contains("Do not", case=False).any()
        )
        detail_options = _procedure_analysis_detail_options(advisor_board)
        self.assertFalse(detail_options.empty)
        self.assertIn("DETAIL_LABEL", detail_options.columns)
        self.assertTrue(detail_options["DETAIL_LABEL"].astype(str).str.contains("SP_LOAD_POLICY").any())

    def test_procedure_optimization_triage_prioritizes_spill_pruning_and_regressions(self):
        row = pd.Series({
            "PROCEDURE_CONTEXT": "ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY",
            "REMOTE_SPILL_GB": 12.5,
            "GB_SCANNED": 180.0,
            "CACHE_PCT": 2.0,
            "PARTITION_PCT": 96.0,
            "TOTAL_ELAPSED_SEC": 1400.0,
            "RUNTIME_CHANGE_PCT": 160.0,
            "COST_CHANGE_PCT": 120.0,
            "DOWNSTREAM_QUERY_COUNT": 18,
        })

        findings = _procedure_optimization_findings(row)
        issues = {finding["ISSUE"] for finding in findings}

        self.assertIn("Remote spill inside procedure workload", issues)
        self.assertIn("Poor partition pruning in child queries", issues)
        self.assertIn("Large cold scan in procedure workload", issues)
        self.assertGreater(_procedure_optimization_score(row), _procedure_optimization_score({"TOTAL_ELAPSED_SEC": 10}))
        self.assertTrue(all(finding["SAFE_NEXT_ACTION"] for finding in findings))
        self.assertTrue(all(finding["DO_NOT_DO"] for finding in findings))

    def test_procedure_optimization_columns_keep_clean_rows_advisory_only(self):
        frame = _add_procedure_optimization_columns(pd.DataFrame([{
            "PROCEDURE_NAME": "SP_OK",
            "TOTAL_ELAPSED_SEC": 20,
            "REMOTE_SPILL_GB": 0,
            "GB_SCANNED": 1,
            "PARTITION_PCT": 5,
        }]))

        self.assertEqual(frame.iloc[0]["OPTIMIZATION_ISSUE"], "No clear procedure optimization anti-pattern")
        self.assertIn("Keep monitoring", frame.iloc[0]["SAFE_NEXT_ACTION"])
        self.assertIn("Do not create", frame.iloc[0]["DO_NOT_DO"])

    def test_procedure_mart_sql_qualifies_snapshot_timestamp(self):
        inventory_sql = build_mart_procedure_inventory_sql("ALFA").upper()
        self.assertIn("MAX(SNAPSHOT_TS) AS LATEST_SNAPSHOT_TS", inventory_sql)
        self.assertIn("P.SNAPSHOT_TS AS SNAPSHOT_TS", inventory_sql)
        self.assertIn("P.SNAPSHOT_TS = L.LATEST_SNAPSHOT_TS", inventory_sql)
        self.assertNotIn("JOIN LATEST L ON SNAPSHOT_TS =", inventory_sql)

        sla_sql = build_mart_procedure_sla_sql(7, "Trexis").upper()
        self.assertIn("FACT_PROCEDURE_RUN", sla_sql)
        self.assertIn("COMPANY = 'TREXIS'", sla_sql)

    def test_live_bugfixes_avoid_known_snowflake_identifier_and_type_errors(self):
        dynamic_text = (APP_ROOT / "sections" / "dba_tools_data_movement_view.py").read_text(encoding="utf-8")
        dynamic_block = dynamic_text[
            dynamic_text.index('refresh_object = "SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY"'):
            dynamic_text.index("def render_replication_tool")
        ].upper()
        requested_block = dynamic_block[
            dynamic_block.index("REQUESTED_COLS = ["):
            dynamic_block.index("AVAILABLE_COLS =")
        ]
        self.assertNotIn('"STATE"', requested_block)
        self.assertNotIn('"STATE": "LAST_REFRESH_STATE"', dynamic_block)

        security_text = (APP_ROOT / "sections" / "security_access.py").read_text(encoding="utf-8").upper()
        self.assertIn("COALESCE(TO_VARCHAR(SECOND_AUTHENTICATION_FACTOR), 'NONE')", security_text)
        self.assertIn("COALESCE(TO_VARCHAR(ERROR_CODE), 'NONE')", security_text)
        self.assertNotIn("COALESCE(ERROR_CODE, 'NONE')", security_text)

        account_text = (APP_ROOT / "sections" / "account_health.py").read_text(encoding="utf-8").upper()
        loader_block = account_text[
            account_text.index("DEF _LOAD_LIVE_QUERY_STATUS"):
            account_text.index("DEF _CAN_USE_CONTROL_ROOM_MART")
        ]
        self.assertLess(
            loader_block.index("RETURN RUN_QUERY_OR_RAISE(_LIVE_QUERY_STATUS_SQL"),
            loader_block.index("RETURN RUN_QUERY_OR_RAISE(FALLBACK_SQL)"),
        )
        self.assertIn('"INFORMATION_SCHEMA"', loader_block)
        self.assertIn('"ACCOUNT_USAGE"', loader_block)

    def test_connected_program_tracking_uses_auth_event_before_query_tag_fallback(self):
        security_text = (APP_ROOT / "sections" / "security_access.py").read_text(encoding="utf-8").upper()
        topology_text = (APP_ROOT / "sections" / "platform_topology.py").read_text(encoding="utf-8").upper()
        adoption_text = (APP_ROOT / "sections" / "adoption_analytics.py").read_text(encoding="utf-8").upper()
        compat_text = (APP_ROOT / "utils" / "compatibility.py").read_text(encoding="utf-8").upper()

        self.assertIn("CONNECTED PROGRAMS", security_text)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.SESSIONS", security_text)
        self.assertIn("SESSIONS CLIENT METADATA", security_text)
        self.assertIn("AUTHN_EVENT_ID", security_text)
        self.assertIn("L.EVENT_ID", security_text)
        self.assertIn("LOGIN-ONLY REPORTED CLIENT; NO DATABASE CONTEXT", security_text)
        self.assertIn("QUERY_TAG FALLBACK; NOT EXACT CONNECTED-PROGRAM IDENTITY", security_text)
        self.assertIn("CLIENT VALUE IS REPORTED, NOT AUTHENTICATED", security_text)

        for section_text in (topology_text, adoption_text):
            self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.SESSIONS", section_text)
            self.assertIn("SESSION_ID TO SESSIONS CLIENT METADATA", section_text)
            self.assertIn("AUTHN_EVENT_ID", section_text)
            self.assertIn("REPORTED_CLIENT_TYPE", section_text)
            self.assertIn("QUERY_TAG FALLBACK; NOT EXACT CONNECTED-PROGRAM IDENTITY", section_text)
            self.assertIn("SOURCE_CONFIDENCE", section_text)

        self.assertIn('"AUTHN_EVENT_ID"', compat_text)
        self.assertIn('"EVENT_ID"', compat_text)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.SESSIONS", compat_text)
        self.assertIn('"CLIENT_APPLICATION_ID"', compat_text)

    def test_dba_control_room_defers_specialist_section_imports(self):
        dba_text = _section_source(APP_ROOT / "sections" / "dba_control_room.py")

        for specialist in (
            "sections.task_management",
            "sections.cortex_monitor",
            "sections.stored_proc_tracker",
        ):
            # No module-level (column-0) import of a specialist section.
            self.assertNotIn(f"\nfrom {specialist} import", dba_text)
            # The import is deferred inside a helper function (indented).
            self.assertIn(f"    from {specialist} import", dba_text)
        self.assertIn("def _task_management_helpers", dba_text)
        self.assertIn("def _cortex_helpers", dba_text)
        self.assertIn("def _procedure_helpers", dba_text)

    def test_mart_usage_metering_window_condition_is_not_string_spliced(self):
        mart_text = (APP_ROOT / "utils" / "mart.py").read_text(encoding="utf-8")
        sql = build_mart_usage_metering_sql(
            7,
            "ALFA",
            start_date="2026-05-01",
            end_date="2026-05-07",
        ).upper()

        self.assertNotIn("REPLACE('AND ', '', 1)", mart_text.upper())
        self.assertNotIn("IFF(AND ", sql)
        self.assertIn("IFF(HOUR_START >=", sql)
        self.assertIn("HOUR_START < DATEADD('DAY', 1", sql)

    def test_usage_and_warehouse_mart_sql_exposes_period_movement(self):
        usage_sql = build_mart_usage_cost_drivers_sql(7, "ALFA").upper()
        warehouse_sql = build_mart_warehouse_overview_sql(7, "ALFA").upper()

        self.assertIn("FACT_WAREHOUSE_HOURLY", usage_sql)
        self.assertIn("PRIOR_CREDITS", usage_sql)
        self.assertIn("CREDIT_DELTA", usage_sql)
        self.assertIn("CREDIT_DELTA_PCT", usage_sql)
        self.assertIn("ORDER BY CREDIT_DELTA DESC", usage_sql)

        self.assertIn("PRIOR_METERED_CREDITS", warehouse_sql)
        self.assertIn("CREDIT_DELTA", warehouse_sql)
        self.assertIn("CREDIT_DELTA_PCT", warehouse_sql)
        self.assertIn("HOUR_START >= DATEADD('DAY', -14", warehouse_sql)

    def test_warehouse_brief_launchpad_prioritizes_investigation_workflows(self):
        rows = _warehouse_brief_workflow_rows()

        self.assertEqual(
            [row["VIEW"] for row in rows],
            [
                "Overview & Scaling",
                "Efficiency",
                "Spill & Memory",
                "Workload Heatmap",
                "Optimization Advisor",
            ],
        )
        by_view = {row["VIEW"]: row for row in rows}
        self.assertIn("warehouse pressure", by_view["Overview & Scaling"]["DBA_MOVE"])
        self.assertIn("credits per query", by_view["Efficiency"]["DBA_MOVE"])
        self.assertIn("remote spill", by_view["Spill & Memory"]["WHEN"])
        self.assertIn("Snowflake task", by_view["Workload Heatmap"]["WHEN"])
        self.assertIn("Open Advisor", by_view["Optimization Advisor"]["BUTTON_LABEL"])
        self.assertIn("Actionable sizing", by_view["Optimization Advisor"]["SOURCES"])

    def test_warehouse_brief_first_default_resets_stale_unloaded_workflow(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["warehouse_health_view"] = "Efficiency"
            _apply_warehouse_brief_first_default()

            self.assertEqual(st.session_state["warehouse_health_view"], "Overview & Scaling")
            self.assertEqual(st.session_state["_warehouse_health_brief_first_version"], 2)

            st.session_state["warehouse_health_view"] = "Workload Heatmap"
            _apply_warehouse_brief_first_default()
            self.assertEqual(st.session_state["warehouse_health_view"], "Workload Heatmap")

            st.session_state.clear()
            st.session_state["warehouse_health_view"] = "Efficiency"
            st.session_state["wh_df_wh"] = pd.DataFrame({"WAREHOUSE_NAME": ["WH_TRXS_LOAD"]})
            _apply_warehouse_brief_first_default()
            self.assertEqual(st.session_state["warehouse_health_view"], "Efficiency")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_explain_bill_driver_aliases_match_visible_columns(self):
        cost_text = (APP_ROOT / "sections" / "cost_center.py").read_text(encoding="utf-8").upper()
        explain_block = cost_text[
            cost_text.index('IF COST_VIEW == "EXPLAIN THIS BILL"'):
            cost_text.index('ELIF COST_VIEW == "USER LEADERBOARD"')
        ]
        self.assertIn("AS TOTAL_CREDITS", explain_block)
        self.assertIn("AS ALLOCATED_CREDITS", explain_block)
        self.assertIn("AS AVG_EXECUTION_SECONDS", explain_block)
        self.assertIn("AS AVG_ELAPSED_SEC", explain_block)
        self.assertIn('"TOTAL_CREDITS"', explain_block)
        self.assertIn('"AVG_EXECUTION_SECONDS"', explain_block)

    def test_cost_forecast_rows_normalize_snowflake_timezone_days(self):
        raw = pd.DataFrame({
            "DAY": pd.to_datetime([
                "2026-06-15 00:00:00+00:00",
                "2026-06-16 00:00:00+00:00",
            ], utc=True).astype("datetime64[us, UTC]"),
            "DAILY_CREDITS": [10.5, 21.0],
        })

        forecast = _prepare_cost_forecast_rows(raw, today="2026-06-16")

        self.assertEqual(len(forecast), 30)
        self.assertFalse(str(forecast["DAY"].dtype).endswith("UTC]"))
        self.assertEqual(float(forecast.loc[forecast["DAY"].eq(pd.Timestamp("2026-06-15")), "DAILY_CREDITS"].iloc[0]), 10.5)
        self.assertEqual(float(forecast.loc[forecast["DAY"].eq(pd.Timestamp("2026-06-16")), "DAILY_CREDITS"].iloc[0]), 21.0)
        self.assertEqual(float(forecast["DAILY_CREDITS"].sum()), 31.5)

    def test_cost_control_action_requires_verification_evidence(self):
        action = _warehouse_cost_control_action(
            pd.Series({
                "WAREHOUSE_NAME": "WH_ALFA_BI",
                "CREDIT_DELTA": 250,
                "CURRENT_CREDITS": 500,
                "PRIOR_CREDITS": 250,
                "OWNER_ROLE": "BI_PLATFORM_OWNER",
            }),
            credit_price=3.0,
            period_label="last 7 complete days",
            company="ALFA",
        )

        self.assertEqual(action["Owner"], "BI_PLATFORM_ROUTE")
        self.assertEqual(action["Category"], "Cost Control")
        self.assertEqual(action["Environment"], "")
        self.assertEqual(action["Approver"], "BI_PLATFORM_ROUTE / Cost owner")
        self.assertEqual(action["Verification Status"], "Requested")
        self.assertEqual(action["Baseline Value"], 250)
        self.assertEqual(action["Current Value"], 500)
        self.assertEqual(action["Measured Delta"], 250)
        self.assertNotIn("Owner Approval Status", action)
        self.assertEqual(action["Recovery SLA State"], "Savings Measurement Pending")
        self.assertEqual(action["Recovery SLA Target Hours"], 168.0)
        self.assertIn("next complete period", action["Verification Note"])
        self.assertIn("Exact warehouse metering", action["Action"])
        self.assertNotIn("owner", action["Action"].lower())
        self.assertIn("WAREHOUSE_METERING_HISTORY", action["Proof Query"])
        self.assertIn("measured delta", action["Proof Query"].lower())
        self.assertIn("Warehouse Settings Manager", action["Action"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])

    def test_chargeback_cost_verification_sql_is_runnable_and_scoped(self):
        sql = _chargeback_cost_verification_sql(
            pd.Series({
                "COMPANY": "ALFA",
                "ENVIRONMENT": "ALFA_EDW_DEV",
                "DATABASE_NAME": "ALFA_EDW_DEV",
                "USER_NAME": "ETL_RUNNER",
                "WAREHOUSE_NAME": "WH_ALFA_ETL",
            }),
            lookback_days=30,
            company="ALFA",
        )
        sql_upper = sql.upper()

        self.assertIn("QUERY_HISTORY", sql_upper)
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql_upper)
        self.assertIn("TAG_REFERENCES", sql_upper)
        self.assertIn("COST_OWNER", sql_upper)
        self.assertIn("Q.USER_NAME = 'ETL_RUNNER'", sql_upper)
        self.assertIn("Q.DATABASE_NAME = 'ALFA_EDW_DEV'", sql_upper)
        self.assertIn("ALLOCATED / ESTIMATED", sql_upper)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_chargeback_outlier_queue_uses_owner_review_and_verification_sql(self):
        import streamlit as st

        df = pd.DataFrame(
            {
                "COMPANY": ["ALFA"],
                "ENVIRONMENT": ["Other / Shared"],
                "DATABASE_NAME": ["NO_DATABASE_CONTEXT"],
                "USER_NAME": ["Unknown user"],
                "WAREHOUSE_NAME": ["BI_COMPUTE_WH"],
                "TOTAL_CREDITS": [400.0],
                "ALLOCATION_CONFIDENCE": ["Account-wide / Shared"],
                "ALLOCATION_BASIS": ["No database context; do not split PROD/DEV without tags or session lineage."],
                "CHARGEBACK_READY": ["No"],
                "SCOPE_REVIEW": ["Missing database context"],
            }
        )
        captured = {}

        def fake_upsert(_session, actions):
            captured["actions"] = actions
            return len(actions)

        previous_company = st.session_state.get("active_company")
        st.session_state["active_company"] = "ALFA"
        try:
            with patch("sections.cost_center.upsert_actions", side_effect=fake_upsert), patch(
                "sections.cost_center.get_active_environment", return_value="ALL"
            ):
                _queue_cost_outliers(object(), df, 3.0, "Cost & Contract - Chargeback")
        finally:
            if previous_company is None:
                st.session_state.pop("active_company", None)
            else:
                st.session_state["active_company"] = previous_company

        action = captured["actions"][0]
        self.assertEqual(action["Category"], "Chargeback Review")
        self.assertEqual(action["Owner"], "DBA / Cost owner")
        self.assertEqual(action["Environment"], "No Database Context")
        self.assertEqual(action["Approver"], "Cost owner / Cost Route")
        self.assertEqual(action["Verification Status"], "Requested")
        self.assertNotIn("Owner Approval Status", action)
        self.assertEqual(action["Recovery SLA State"], "Chargeback Telemetry Pending")
        self.assertEqual(action["Recovery SLA Target Hours"], 168.0)
        self.assertIn("route/tag telemetry", action["Action"])
        self.assertIn("not cleanly chargeback-ready", action["Action"])
        self.assertIn("Chargeback status: No", action["Generated SQL Fix"])
        self.assertNotIn("owner", action["Generated SQL Fix"].lower())
        self.assertIn("QUERY_HISTORY", action["Verification Query"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])

    def test_cost_contract_closure_analytics_separates_verified_and_estimated_savings(self):
        queue = pd.DataFrame([
            {
                "ACTION_ID": "COST_VERIFIED",
                "SOURCE": "Cost & Contract - Explain This Bill",
                "CATEGORY": "Cost Control",
                "SEVERITY": "High",
                "ENTITY_NAME": "WH_ALFA_BI",
                "OWNER": "BI_PLATFORM_OWNER",
                "STATUS": "Fixed",
                "EST_MONTHLY_SAVINGS": 600,
                "OWNER_APPROVAL_STATUS": "Approved",
                "VERIFICATION_STATUS": "Verified",
                "VERIFICATION_RESULT": "Post-period metering dropped below baseline.",
                "BASELINE_VALUE": 200,
                "CURRENT_VALUE": 150,
                "MEASURED_DELTA": -50,
                "RECOVERY_SLA_STATE": "Savings Verified",
                "QUEUE_PRIORITY": 1,
            },
            {
                "ACTION_ID": "COST_FIXED_GAP",
                "SOURCE": "Cost & Contract - Explain This Bill",
                "CATEGORY": "Cost Control",
                "SEVERITY": "Medium",
                "ENTITY_NAME": "WH_ALFA_ETL",
                "OWNER": "ETL_OWNER",
                "STATUS": "Fixed",
                "EST_MONTHLY_SAVINGS": 200,
                "OWNER_APPROVAL_STATUS": "Approved",
                "VERIFICATION_STATUS": "Pending",
                "VERIFICATION_RESULT": "",
                "BASELINE_VALUE": 100,
                "CURRENT_VALUE": 80,
                "MEASURED_DELTA": -20,
                "RECOVERY_SLA_STATE": "Savings Verification Pending",
                "QUEUE_PRIORITY": 2,
            },
            {
                "ACTION_ID": "COST_OPEN",
                "SOURCE": "Cost & Contract - User Leaderboard",
                "CATEGORY": "Cost",
                "SEVERITY": "Medium",
                "ENTITY_NAME": "ANALYST on WH_ALFA_BI",
                "OWNER": "ANALYTICS_OWNER",
                "STATUS": "New",
                "EST_MONTHLY_SAVINGS": 300,
                "OWNER_APPROVAL_STATUS": "Requested",
                "VERIFICATION_STATUS": "Pending",
                "BASELINE_VALUE": 100,
                "CURRENT_VALUE": 180,
                "MEASURED_DELTA": 80,
                "RECOVERY_SLA_STATE": "Savings Verification Pending",
                "QUEUE_PRIORITY": 3,
            },
            {
                "ACTION_ID": "CHARGEBACK_OPEN",
                "SOURCE": "Cost & Contract - Chargeback",
                "CATEGORY": "Chargeback Review",
                "SEVERITY": "High",
                "ENTITY_NAME": "NO_DATABASE_CONTEXT / Unknown user on BI_COMPUTE_WH",
                "OWNER": "DBA / Cost owner",
                "STATUS": "In Progress",
                "EST_MONTHLY_SAVINGS": 400,
                "OWNER_APPROVAL_STATUS": "Requested",
                "VERIFICATION_STATUS": "Pending",
                "BASELINE_VALUE": 0,
                "CURRENT_VALUE": 400,
                "MEASURED_DELTA": 400,
                "RECOVERY_SLA_STATE": "Chargeback Evidence Pending",
                "QUEUE_PRIORITY": 4,
            },
        ])

        summary, detail = _build_cost_closure_analytics(queue, 3.0)
        by_id = {row["ACTION_ID"]: row for _, row in detail.iterrows()}

        self.assertEqual(summary["cost_actions"], 4)
        self.assertEqual(summary["open_actions"], 2)
        self.assertEqual(summary["verified_savings_actions"], 1)
        self.assertEqual(summary["fixed_without_verification"], 1)
        self.assertEqual(summary["approval_pending_actions"], 2)
        self.assertEqual(summary["open_estimated_monthly_savings"], 700)
        self.assertEqual(summary["blocked_estimated_monthly_savings"], 700)
        self.assertEqual(summary["verified_estimated_monthly_savings"], 600)
        self.assertEqual(summary["verified_period_delta_dollars"], 150)
        self.assertEqual(by_id["COST_VERIFIED"]["CLOSURE_STATE"], "Measured improvement")
        self.assertEqual(by_id["COST_FIXED_GAP"]["CLOSURE_STATE"], "Fixed, awaiting measurement")
        self.assertEqual(by_id["COST_OPEN"]["CLOSURE_STATE"], "Review pending")
        self.assertEqual(by_id["CHARGEBACK_OPEN"]["CLOSURE_STATE"], "Chargeback telemetry pending")

    def test_cost_contract_closure_analytics_recognizes_verified_no_change(self):
        queue = pd.DataFrame([
            {
                "ACTION_ID": "COST_NO_CHANGE",
                "SOURCE": "Cost & Contract - Explain This Bill",
                "CATEGORY": "Cost Control",
                "SEVERITY": "High",
                "ENTITY_NAME": "WH_ALFA_BATCH",
                "OWNER": "BATCH_OWNER",
                "STATUS": "Fixed",
                "EST_MONTHLY_SAVINGS": 500,
                "OWNER_APPROVAL_STATUS": "Approved",
                "VERIFICATION_STATUS": "VERIFIED_NO_CHANGE",
                "VERIFICATION_RESULT": "Automated post-period verification found no measured savings.",
                "BASELINE_VALUE": 100,
                "CURRENT_VALUE": 125,
                "MEASURED_DELTA": 25,
                "RECOVERY_SLA_STATE": "Verified No Change",
                "QUEUE_PRIORITY": 1,
            },
        ])

        summary, detail = _build_cost_closure_analytics(queue, 3.0)

        self.assertEqual(summary["verified_savings_actions"], 0)
        self.assertEqual(summary["verified_no_change_actions"], 1)
        self.assertEqual(summary["fixed_without_verification"], 0)
        self.assertEqual(summary["audit_ready_pct"], 100.0)
        self.assertEqual(detail.iloc[0]["CLOSURE_STATE"], "Measured no improvement")
        self.assertEqual(detail.iloc[0]["MEASURED_IMPACT_DOLLARS"], 0.0)

    def test_recommendation_actions_have_runnable_verification_sql(self):
        queries = [
            _idle_warehouse_verification_sql("WH_ALFA_BI"),
            _remote_spill_verification_sql("WH_ALFA_BI"),
            _task_failure_verification_sql("LOAD_POLICY"),
            _query_failure_verification_sql("WH_ALFA_BI"),
        ]

        for sql in queries:
            self.assertEqual(verification_query_safety_issues(sql), [])

    def test_recommendations_are_decisive_and_evidence_backed(self):
        rec = harden_recommendation({
            "Source": "Idle warehouse detector",
            "Severity": "High",
            "Category": "Cost Control",
            "Entity Type": "Warehouse",
            "Entity": "COMPUTE_WH",
            "Finding": "COMPUTE_WH idle 12h, wasting 4.5 credits",
            "Action": "Reduce AUTO_SUSPEND",
            "Idle Hours": 12,
            "Estimated Monthly Savings": 72.5,
            "Proof Query": _idle_warehouse_verification_sql("COMPUTE_WH"),
            "Baseline Value": 4.5,
        })

        self.assertEqual(rec["Decision"], "Implement suspend control")
        self.assertIn("COMPUTE_WH", rec["Telemetry Summary"])
        self.assertIn("12 idle hour", rec["Telemetry Summary"])
        self.assertIn("AUTO_SUSPEND", rec["Safe Next Action"])
        self.assertIn("Telemetry query is available", rec["Telemetry Basis"])
        self.assertIn("Do not disable", rec["Do Not Do"])
        self.assertIn("Review Gate", rec)
        self.assertIn("Telemetry Summary", rec)
        self.assertIn("Verify Next", rec)
        self.assertIn("Execution Boundary", rec)
        self.assertIn("Closure Rule", rec)
        self.assertIn("DBA capacity review", rec["Review Gate"])
        self.assertIn("Do not disable", rec["Execution Boundary"])

    def test_recommendation_execution_contract_is_specific_by_surface(self):
        idle_contract = recommendation_execution_contract({
            "Source": "Idle warehouse detector",
            "Category": "Cost Control",
            "Entity Type": "Warehouse",
            "Entity": "COMPUTE_WH",
            "Finding": "Idle warehouse",
            "Evidence Packet": "COMPUTE_WH idle 12h",
            "Proof Required": "Rerun idle proof query.",
        })
        query_contract = duplicate_query_decision(pd.Series({
            "QUERY_SIG": "select * from FACT_POLICY where POLICY_ID = ?",
            "EXECUTION_COUNT": 25,
            "USER_COUNT": 4,
            "TOTAL_WASTED_SEC": 1800,
            "CLOUD_CREDITS": 0.12,
        }))

        self.assertIn("metering", idle_contract["VERIFY_NEXT"])
        self.assertIn("capacity review", idle_contract["APPROVAL_GATE"])
        self.assertIn("repeated query signature", query_contract["EVIDENCE_PACKAGE"])
        self.assertIn("materialized views", query_contract["EXECUTION_BOUNDARY"])
        self.assertIn("CLOSURE_RULE", query_contract)

    def test_loaded_advisor_signal_board_merges_loaded_section_outputs(self):
        state = {
            "cost_contract_cost_advisor_board": pd.DataFrame([{
                "SEVERITY": "High",
                "FINDING": "Idle warehouse",
                "ENTITY": "COMPUTE_WH",
                "WORKFLOW_ROUTE": "Cost & Contract > Advisor",
                "SAFE_NEXT_ACTION": "Review auto-suspend.",
                "VALIDATION_NEEDED": "metering telemetry",
                "EST_MONTHLY_SAVINGS_USD": 1200,
                "EST_MONTHLY_IMPACT_USD": 250,
                "TELEMETRY_SUMMARY": "12 idle hours.",
            }]),
            "wh_settings_action_plan": pd.DataFrame([{
                "PRIORITY": "Medium",
                "ACTION_TYPE": "Auto-suspend review",
                "WAREHOUSE_NAME": "LOAD_WH",
                "SAFE_SETTING_MOVE": "Lower auto-suspend after owner review.",
                "PROOF_REQUIRED": "warehouse metering telemetry",
                "WHY": "Long idle gaps.",
            }]),
            "sp_analysis_board": pd.DataFrame([{
                "PRIORITY": "High",
                "SIGNAL": "Procedure runtime spike",
                "PROCEDURE_CONTEXT": "DB.SCH.SP_LOAD",
                "SAFE_NEXT_ACTION": "Compare child-query telemetry.",
                "PROOF_REQUIRED": "procedure call telemetry",
                "EST_TOTAL_CREDITS": 14,
            }]),
            "cost_contract_monitoring_alerts": pd.DataFrame([{
                "SEVERITY": "Medium",
                "ALERT_TYPE": "Cost anomaly",
                "ENTITY_NAME": "CORTEX",
                "ROUTE": "Alert Center",
                "SUGGESTED_ACTION": "Review incident timeline.",
                "PROOF_QUERY": "cost monitoring telemetry",
                "VALUE_AT_RISK_USD": 500,
                "MESSAGE": "Spend moved outside normal range.",
            }]),
        }

        board = build_loaded_advisor_signal_board(state)
        sources = set(board["SOURCE_SURFACE"].astype(str))

        self.assertEqual(board.iloc[0]["SEVERITY"], "High")
        self.assertIn("Cost Advisor", sources)
        self.assertIn("Warehouse Settings Advisor", sources)
        self.assertIn("Stored Procedure Analysis", sources)
        self.assertIn("Cost Monitoring Alerts", sources)
        self.assertIn("PRIORITY_RANK", board.columns)
        self.assertGreater(board["EST_MONTHLY_SAVINGS_USD"].sum(), 0)
        self.assertGreater(board["VALUE_AT_RISK_USD"].sum(), 0)

    def test_warehouse_sizing_decision_blocks_blind_upsize(self):
        decision = warehouse_sizing_decision(pd.Series({
            "WAREHOUSE_NAME": "ALFA_WH",
            "WAREHOUSE_SIZE": "Medium",
            "TOTAL_QUERIES": 250,
            "TOTAL_CREDITS": 92.5,
            "AVG_QUEUE_SEC": 0.5,
            "REMOTE_SPILL_GB": 14.2,
            "AVG_CACHE_PCT": 20,
        }))

        self.assertEqual(decision["DECISION"], "Memory pressure: tune query shape first")
        self.assertIn("ALFA_WH", decision["EVIDENCE_PACKET"])
        self.assertIn("query profiles", decision["SAFE_NEXT_ACTION"])
        self.assertIn("Do not upsize blindly", decision["DO_NOT_DO"])
        self.assertIn("DBA capacity review", decision["APPROVAL_GATE"])
        self.assertIn("guarded controls", decision["EXECUTION_BOUNDARY"])
        self.assertIn("queue, spill, runtime", decision["VERIFY_NEXT"])

    def test_automation_readiness_identifies_guided_warehouse_change(self):
        board = build_automation_readiness_board([{
            "Source": "Idle warehouse detector",
            "Severity": "High",
            "Category": "Cost Control",
            "Entity Type": "Warehouse",
            "Entity": "COMPUTE_WH",
            "Owner": "OVERWATCH Platform Owner",
            "Approver": "DBA Lead",
            "Owner Approval Status": "Approved",
            "Finding": "COMPUTE_WH idle 12h, wasting 4.5 credits",
            "Action": "Reduce AUTO_SUSPEND",
            "Idle Hours": 12,
            "Estimated Monthly Savings": 72.5,
            "Generated SQL Fix": "ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 600;",
            "Proof Query": _idle_warehouse_verification_sql("COMPUTE_WH"),
            "Verification Query": _idle_warehouse_verification_sql("COMPUTE_WH"),
            "Baseline Value": 4.5,
        }])
        row = board.iloc[0]

        self.assertEqual(row["AUTOMATION_LANE"], "Telemetry Pending")
        self.assertEqual(row["SAFE_GUIDED_SQL"], "Yes")
        self.assertEqual(row["STATE_CHANGING_SQL"], "Yes")
        self.assertIn("telemetry status", row["BLOCKERS"])
        self.assertGreaterEqual(row["AUTOMATION_SCORE"], 70)
        self.assertIn("APPROVAL_GATE", board.columns)
        self.assertIn("EVIDENCE_PACKAGE", board.columns)
        self.assertIn("VERIFY_NEXT", board.columns)
        self.assertIn("EXECUTION_BOUNDARY", board.columns)
        self.assertIn("CLOSURE_RULE", board.columns)
        self.assertIn("DBA capacity review", row["APPROVAL_GATE"])
        self.assertIn("metering", row["VERIFY_NEXT"])

    def test_automation_readiness_blocks_unapproved_and_manual_actions(self):
        board = build_automation_readiness_board([
            {
                "Source": "Idle warehouse detector",
                "Severity": "High",
                "Category": "Cost Control",
                "Entity Type": "Warehouse",
                "Entity": "COMPUTE_WH",
                "Owner": "OVERWATCH Platform Owner",
                "Finding": "COMPUTE_WH idle 12h",
                "Generated SQL Fix": "ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 600;",
                "Proof Query": _idle_warehouse_verification_sql("COMPUTE_WH"),
            },
            {
                "Source": "Task failure detector",
                "Severity": "High",
                "Category": "Task & Procedure Reliability",
                "Entity Type": "Task",
                "Entity": "LOAD_POLICY",
                "Owner": "Data Engineering",
                "Approver": "Pipeline Owner",
                "Owner Approval Status": "Approved",
                "Finding": "Task failed repeatedly",
                "Generated SQL Fix": "EXECUTE TASK ALFA_EDW_PROD.PUBLIC.LOAD_POLICY;",
                "Proof Query": _task_failure_verification_sql("LOAD_POLICY"),
            },
        ])
        by_entity = {row["ENTITY"]: row for _, row in board.iterrows()}

        self.assertEqual(by_entity["COMPUTE_WH"]["AUTOMATION_LANE"], "Telemetry Pending")
        self.assertIn("telemetry status", by_entity["COMPUTE_WH"]["BLOCKERS"])
        self.assertEqual(by_entity["LOAD_POLICY"]["AUTOMATION_LANE"], "DBA Review")
        self.assertIn("DBA review", by_entity["LOAD_POLICY"]["BLOCKERS"])

    def test_ask_overwatch_refuses_when_no_loaded_evidence(self):
        result = answer_ask_overwatch(
            "What should I do first?",
            {},
            active_section="DBA Control Room",
            company="ALFA",
            environment="PROD",
            role="ACCOUNTADMIN",
        )

        self.assertEqual(result["confidence"], "No loaded telemetry")
        self.assertIn("not have enough loaded OVERWATCH telemetry", result["answer"])
        self.assertIn("will not invent best-practice advice", result["answer"])

    def test_top_priority_brief_cards_are_ranked_and_domain_filtered(self):
        state = {
            "rec_recommendations": [{
                "Source": "Idle warehouse detector",
                "Severity": "High",
                "Category": "Cost Control",
                "Entity Type": "Warehouse",
                "Entity": "COMPUTE_WH",
                "Finding": "COMPUTE_WH idle 12h, wasting 4.5 credits",
                "Action": "Reduce AUTO_SUSPEND",
                "Estimated Monthly Savings": 72.5,
                "Proof Query": _idle_warehouse_verification_sql("COMPUTE_WH"),
            }],
            "dba_control_room_data": {
                "summary": pd.DataFrame([{
                    "FAILED_QUERIES": 0,
                    "QUEUED_QUERIES": 24,
                    "REMOTE_SPILL_QUERIES": 3,
                    "P95_ELAPSED_SEC": 95,
                }])
            },
        }

        all_cards = build_top_priority_brief_cards(state, limit=5)
        cost_cards = build_top_priority_brief_cards(state, domain="Cost", limit=5)
        warehouse_cards = build_top_priority_brief_cards(
            {"dba_control_room_data": state["dba_control_room_data"]},
            domain="Warehouse",
            limit=5,
        )

        self.assertEqual(all_cards[0]["rank"], 1)
        self.assertLessEqual(len(all_cards), 5)
        self.assertIn("COMPUTE_WH", cost_cards[0]["entity"])
        self.assertIn("credit", cost_cards[0]["evidence"].lower())
        self.assertIn("Control-room workload risk", warehouse_cards[0]["signal"])
        self.assertIn("queued", warehouse_cards[0]["evidence"])
        self.assertEqual(build_top_priority_brief_cards({}, domain="All"), [])

    def test_top_priority_brief_reads_executive_landing_platform_score(self):
        state = {
            "executive_landing_platform_summary": {
                "score": 58,
                "raw_score": 63.5,
                "state": "Executive Escalation",
                "score_cap": 74,
                "cap_reason": "1 monitoring coverage blocker(s) cap the executive operating state.",
            },
            "executive_landing_snapshot": {
                "errors": ["Alert evidence unavailable: missing ALERT_EVENTS privilege."],
                "cost": pd.DataFrame([{
                    "CURRENT_CREDITS": 180.0,
                    "PRIOR_CREDITS": 120.0,
                    "TOP_INCREASE_WAREHOUSE": "WH_TRXS_QUERY",
                }]),
                "alerts": pd.DataFrame([{
                    "SEVERITY": "High",
                    "ALERT_NAME": "Failed production task",
                    "ENTITY": "TASK_LOAD_CUSTOMER",
                    "EVIDENCE": "3 failures in the executive window.",
                }]),
            },
        }

        cards = build_top_priority_brief_cards(state, domain="All", limit=5)
        alert_cards = build_top_priority_brief_cards(state, domain="Alerts", limit=5)

        self.assertEqual(cards[0]["surface"], "Executive Landing")
        self.assertEqual(cards[0]["signal"], "Platform operating state")
        self.assertEqual(cards[0]["severity"], "Critical")
        self.assertEqual(cards[0]["entity"], "Executive Escalation")
        self.assertIn("limiter=1 monitoring coverage blocker", cards[0]["evidence"])
        self.assertIn("Failed production task", {card["signal"] for card in alert_cards})

    def test_top_priority_brief_reads_security_posture_summary(self):
        state = {
            "security_posture_summary": pd.DataFrame([{
                "FAILED_LOGINS": 42,
                "FAILED_USERS": 6,
                "USERS_WITHOUT_MFA": 2,
                "RECENT_GRANTS": 31,
                "SHARED_DATABASES": 1,
            }]),
        }

        security_cards = build_top_priority_brief_cards(state, domain="Security", limit=5)
        signals = [card["signal"] for card in security_cards]

        self.assertIn("MFA gaps", signals)
        self.assertIn("Failed logins", signals)
        self.assertIn("Grant-change volume", signals)
        self.assertIn("Shared data exposure", signals)
        self.assertEqual(security_cards[0]["surface"], "Security Monitoring")
        mfa_card = next(card for card in security_cards if card["signal"] == "MFA gaps")
        self.assertIn("MFA", mfa_card["evidence"])

    def test_top_priority_brief_prioritizes_loaded_security_exceptions(self):
        state = {
            "security_posture_summary": pd.DataFrame([{
                "FAILED_LOGINS": 4,
                "FAILED_USERS": 1,
                "USERS_WITHOUT_MFA": 0,
                "RECENT_GRANTS": 0,
                "SHARED_DATABASES": 0,
            }]),
            "security_posture_exceptions": pd.DataFrame([
                {
                    "SEVERITY": "Medium",
                    "FINDING_TYPE": "Failed Login",
                    "ENTITY": "USER_LOW",
                    "EVENT_COUNT": 4,
                    "LAST_SEEN": "2026-06-01",
                },
                {
                    "SEVERITY": "High",
                    "FINDING_TYPE": "MFA Gap",
                    "ENTITY": "USER_HIGH",
                    "DATABASE_NAME": "NO DATABASE CONTEXT",
                    "EVENT_COUNT": 1,
                    "LAST_SEEN": "2026-06-02",
                    "NEXT_ACTION": "Confirm MFA enrollment.",
                },
            ]),
        }

        security_cards = build_top_priority_brief_cards(state, domain="Security", limit=3)

        self.assertEqual(security_cards[0]["surface"], "Security Monitoring - Security Exceptions")
        self.assertEqual(security_cards[0]["signal"], "MFA Gap")
        self.assertEqual(security_cards[0]["entity"], "USER_HIGH")
        self.assertIn("No Database Context", security_cards[0]["evidence"])
        self.assertIn("Confirm MFA enrollment", security_cards[0]["next_action"])

    def test_top_priority_brief_reads_account_health_morning_exceptions(self):
        state = {
            "account_health_morning_exceptions": pd.DataFrame([
                {
                    "PRIORITY": 0,
                    "SEVERITY": "High",
                    "SIGNAL": "Closure Blocked",
                    "ENTITY": "Closure proof",
                    "EVIDENCE": "2 row(s) need attention.",
                    "NEXT_ACTION": "Escalate overdue closures.",
                    "ROUTE": "Account Health",
                },
                {
                    "PRIORITY": 20,
                    "SEVERITY": "Medium",
                    "SIGNAL": "Queue pressure",
                    "ENTITY": "Warehouses",
                    "EVIDENCE": "3 queued workload signals.",
                    "NEXT_ACTION": "Review warehouse pressure.",
                    "ROUTE": "Warehouse Health",
                },
            ]),
            "account_health_operator_gates": pd.DataFrame([{
                "GATE": "Checklist route",
                "STATE": "Route Blocked",
                "COUNT": 4,
                "PROOF_REQUIRED": "owner and verification SQL",
                "NEXT_ACTION": "Complete route metadata.",
                "GATE_RANK": 1,
            }]),
        }

        cards = build_top_priority_brief_cards(state, domain="Reliability", limit=4)

        self.assertEqual(cards[0]["surface"], "DBA Control Room - Morning Exceptions")
        self.assertEqual(cards[0]["signal"], "Closure Blocked")
        self.assertIn("Escalate overdue closures", cards[0]["next_action"])
        self.assertIn("Route Blocked", {card["signal"] for card in cards})

    def test_priority_brief_domain_filter_preserves_loaded_cards_when_no_domain_match(self):
        cards = [
            {
                "surface": "Cost & Contract",
                "signal": "Credit spike",
                "entity": "WH_LOAD",
                "evidence": "credits increased",
                "next_action": "Open cost attribution",
            },
            {
                "surface": "Warehouse Health",
                "signal": "Queue pressure",
                "entity": "WH_QUERY",
                "evidence": "queue and spill",
                "next_action": "Review capacity",
            },
        ]

        self.assertEqual(filter_ask_overwatch_cards_by_domain(cards, "Cost"), [cards[0]])
        self.assertEqual(filter_ask_overwatch_cards_by_domain(cards, "Warehouse"), [cards[1]])
        self.assertEqual(filter_ask_overwatch_cards_by_domain(cards, "Unknown"), cards)

    def test_ask_overwatch_answers_from_specific_recommendation_evidence(self):
        result = answer_ask_overwatch(
            "What should I do first for cost?",
            {
                "rec_recommendations": [{
                    "Source": "Idle warehouse detector",
                    "Severity": "High",
                    "Category": "Cost Control",
                    "Entity Type": "Warehouse",
                    "Entity": "COMPUTE_WH",
                    "Finding": "COMPUTE_WH idle 12h, wasting 4.5 credits",
                    "Action": "Reduce AUTO_SUSPEND",
                    "Idle Hours": 12,
                    "Estimated Monthly Savings": 72.5,
                    "Proof Query": _idle_warehouse_verification_sql("COMPUTE_WH"),
                    "Baseline Value": 4.5,
                }]
            },
            active_section="Cost & Contract",
            company="ALFA",
            environment="PROD",
            role="SYSADMIN",
        )

        self.assertEqual(result["confidence"], "Telemetry-grounded")
        self.assertIn("COMPUTE_WH", result["answer"])
        self.assertIn("AUTO_SUSPEND", result["answer"])
        self.assertIn("Telemetry query is available", result["answer"])
        self.assertIn("Do not disable", result["answer"])

    def test_ask_overwatch_answers_from_automation_board(self):
        board = build_automation_readiness_board([{
            "Source": "Idle warehouse detector",
            "Severity": "High",
            "Category": "Cost Control",
            "Entity Type": "Warehouse",
            "Entity": "COMPUTE_WH",
            "Owner": "OVERWATCH Platform Owner",
            "Approver": "DBA Lead",
            "Owner Approval Status": "Approved",
            "Finding": "COMPUTE_WH idle 12h",
            "Generated SQL Fix": "ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 600;",
            "Proof Query": _idle_warehouse_verification_sql("COMPUTE_WH"),
        }])
        result = answer_ask_overwatch(
            "What can we automate?",
            {"rec_automation_board": board},
            active_section="Cost & Contract",
            company="ALFA",
            environment="ALL",
            role="SYSADMIN",
        )

        self.assertEqual(result["confidence"], "Telemetry-grounded")
        self.assertIn("COMPUTE_WH", result["answer"])
        self.assertIn("Telemetry Pending", result["answer"])
        self.assertIn("Telemetry Pending", result["cards"][0]["signal"])
        self.assertEqual(result["cards"][0]["surface"], "Queue Health")

    def test_ask_overwatch_uses_whitelisted_state_snapshot(self):
        app_text = (APP_ROOT / "app.py").read_text(encoding="utf-8")
        huge_frame = pd.DataFrame({"VALUE": list(range(100))})
        state = {
            "rec_recommendations": [{"Entity": "COMPUTE_WH", "Finding": "Idle warehouse"}],
            "rec_automation_board": pd.DataFrame([{"ENTITY": "COMPUTE_WH"}]),
            "unrelated_large_frame": huge_frame,
            "executive_landing_platform_summary": {"score": 58},
            "executive_landing_snapshot": {"errors": []},
            "dba_control_room_data": {"summary": pd.DataFrame()},
            "security_posture_summary": pd.DataFrame([{"FAILED_LOGINS": 3}]),
            "security_posture_exceptions": pd.DataFrame([{"FINDING_TYPE": "Failed Login"}]),
            "account_health_morning_exceptions": pd.DataFrame([{"SIGNAL": "Closure Blocked"}]),
            "account_health_operator_gates": pd.DataFrame([{"GATE": "Closure proof"}]),
        }
        snapshot = snapshot_ask_overwatch_state(state)

        self.assertNotIn("_snapshot_ask_overwatch_state(st.session_state)", app_text)
        self.assertNotIn("dict(st.session_state),", app_text)
        self.assertIn("rec_recommendations", snapshot)
        self.assertIn("rec_automation_board", snapshot)
        self.assertIn("executive_landing_platform_summary", snapshot)
        self.assertIn("executive_landing_snapshot", snapshot)
        self.assertIn("dba_control_room_data", snapshot)
        self.assertNotIn("arch_agentic_ai_scorecard", snapshot)
        self.assertIn("security_posture_summary", snapshot)
        self.assertIn("security_posture_exceptions", snapshot)
        self.assertIn("account_health_morning_exceptions", snapshot)
        self.assertIn("account_health_operator_gates", snapshot)
        self.assertNotIn("unrelated_large_frame", snapshot)

    def test_grounded_cortex_prompt_for_future_use_is_strict(self):
        prompt = build_grounded_cortex_prompt(
            "What should I do?",
            [{
                "surface": "Recommendations",
                "severity": "High",
                "entity": "COMPUTE_WH",
                "evidence": "12 idle hours",
                "next_action": "Set AUTO_SUSPEND",
                "proof": "Rerun idle proof query",
                "do_not": "Do not disable warehouse",
            }],
        )

        self.assertIn("Answer only from the telemetry", prompt)
        self.assertIn("Do not give generic Snowflake best practices", prompt)
        self.assertIn("Closure status", prompt)

    def test_task_reliability_action_includes_retry_guard_and_verification(self):
        action = _build_task_reliability_action(
            pd.Series({
                "SIGNAL": "Failed Task Run",
                "TASK_NAME": "LOAD_POLICY",
                "TASK_FQN": '"ALFA_EDW_PROD"."PUBLIC"."LOAD_POLICY"',
                "PROCEDURE_NAME": "SP_LOAD_POLICY",
                "QUERY_ID": "01abc",
                "FAILURE_CATEGORY": "Object Dependency / Drift",
                "ERROR_SIGNATURE": "table does not exist",
                "RETRY_SQL": 'EXECUTE TASK "ALFA_EDW_PROD"."PUBLIC"."LOAD_POLICY";',
                "ROLE_NAME": "TASK_OWNER_ROLE",
                "INCIDENT_PRIORITY": "P2 - Production Risk",
                "RECOVERY_READINESS": "Blocked - object dependency fix first",
                "RECOVERY_STATE": "Open Failure",
                "RECOVERY_HOURS": 2.25,
                "RECOVERY_SLA_TARGET_HOURS": 4,
                "OWNER_APPROVAL_STATE": "Root-cause review required",
                "VERIFY_AFTER_FIX": "Latest task run succeeds within recovery SLA.",
                "DOWNSTREAM_TASK_COUNT": 2,
                "GRAPH_ROLE": "Root",
            }),
            "ALFA",
            "Task Management - Failure Console",
        )

        self.assertEqual(action["Owner"], "TASK_OWNER_ROLE")
        self.assertEqual(action["Category"], "Task & Procedure Reliability")
        self.assertEqual(action["Approver"], "TASK_OWNER_ROLE")
        self.assertEqual(action["Oncall Primary"], "")
        self.assertIn("MONITORING_CONTEXT", action["Owner Source"])
        self.assertEqual(action["Recovery Audit State"], "Audit Required")
        self.assertIn("Environment", action)
        self.assertIn("P2 - Production Risk", action["Finding"])
        self.assertIn("Recovery status", action["Action"])
        self.assertEqual(action["Verification Status"], "Requested")
        self.assertIn("TASK_HISTORY", action["Verification Query"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])
        self.assertIn("Do not execute until root cause is fixed", action["Generated SQL Fix"])
        self.assertIn("downstream tasks: 2", action["Generated SQL Fix"])
        self.assertIn("TASK_HISTORY", action["Proof Query"])
        self.assertIn("QUERY_HISTORY", action["Proof Query"])
        self.assertIn("Confirm", action["Action"])
        self.assertEqual(action["Verification Status"], "Requested")
        self.assertIn("Root-cause review", action["Verification Note"])
        self.assertEqual(action["Recovery SLA State"], "Open Failure")
        self.assertEqual(action["Recovery SLA Hours"], 2.25)
        self.assertEqual(action["Recovery SLA Target Hours"], 4.0)
        self.assertIn("Latest task run succeeds", action["Recovery Evidence"])

    def test_procedure_reliability_action_includes_owner_and_baseline_verification(self):
        action = _build_procedure_reliability_action(
            pd.Series({
                "SIGNAL": "Procedure Cost Regression",
                "PROCEDURE_NAME": "ALFA_EDW_PROD.PUBLIC.SP_LOAD_POLICY",
                "ROOT_QUERY_ID": "01root",
                "RUNTIME_CHANGE_PCT": 25,
                "COST_CHANGE_PCT": 180,
                "PROCEDURE_OWNER": "PROC_OWNER_ROLE",
                "ORCHESTRATION_STATUS": "On-demand CALL only",
                "OWNER_REVIEW": "Required",
                "RECOMMENDED_ACTION": "Review child-query scan volume.",
            }),
            "ALFA",
            "Stored Procedures - SLA & Cost Watch",
        )

        self.assertEqual(action["Owner"], "PROC_OWNER_ROLE")
        self.assertEqual(action["Entity Type"], "Stored Procedure")
        self.assertEqual(action["Approver"], "PROC_OWNER_ROLE")
        self.assertEqual(action["Verification Status"], "Requested")
        self.assertEqual(action["Recovery SLA State"], "Procedure Cost Review Required")
        self.assertEqual(action["Recovery SLA Target Hours"], 24.0)
        self.assertEqual(action["Recovery Audit State"], "Audit Required")
        self.assertIn("MONITORING_CONTEXT", action["Owner Source"])
        self.assertEqual(action["Oncall Primary"], "")
        self.assertIn("Environment", action)
        self.assertEqual(action["Verification Status"], "Requested")
        self.assertIn("QUERY_HISTORY", action["Verification Query"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])
        self.assertNotIn("ROOT_QUERY_ID", action["Verification Query"].upper())
        self.assertIn("orchestration=On-demand CALL only", action["Finding"])
        self.assertIn("DBA review is required", action["Action"])
        self.assertIn("Procedure Cost Regression", action["Finding"])
        self.assertIn("QUERY_HISTORY", action["Proof Query"])
        self.assertIn("next procedure run", action["Proof Query"])
        self.assertIn("Confirm", action["Action"])

    def test_procedure_reliability_slo_board_summarizes_reliability_controls(self):
        summary = {
            "RUNS": 12,
            "SLA_BREACHES": 1,
            "COST_BREACHES": 2,
            "OWNER_REVIEW_REQUIRED": 1,
            "BLOCKED_BY_SUSPENDED_TASK": 0,
        }
        exceptions = pd.DataFrame([
            {"SEVERITY": "Critical", "ORCHESTRATION_STATUS": "On-demand CALL only"},
        ])
        slo_summary, slo_board = _build_procedure_reliability_slo_board(summary, exceptions)
        by_slo = {row["SLO"]: row for _, row in slo_board.iterrows()}

        self.assertEqual(by_slo["Runtime regressions"]["STATE"], "Review")
        self.assertEqual(by_slo["Suspended-task dependency"]["STATE"], "Ready")
        self.assertGreaterEqual(slo_summary["review"], 1)
        self.assertEqual(slo_summary["blocked"], 0)

    def test_task_reliability_slo_board_summarizes_task_and_recovery_risk(self):
        summary = {
            "FAILED_RUNS": 2,
            "SUSPENDED_TASKS": 1,
            "LONG_RUNNING_TASKS": 1,
            "COST_DRIFT_TASKS": 0,
            "OPEN_RECOVERIES": 1,
            "RECOVERY_SLA_BREACHES": 1,
            "P1_INCIDENTS": 1,
            "BLOCKED_RECOVERIES": 1,
        }
        exceptions = pd.DataFrame([
            {"INCIDENT_PRIORITY": "P1 - Production Risk", "RECOVERY_READINESS": "Blocked - dependency"},
        ])
        recovery_sla = pd.DataFrame([
            {"RECOVERY_STATE": "Open Failure"},
        ])
        slo_summary, slo_board = _build_task_reliability_slo_board(summary, exceptions, recovery_sla)
        by_slo = {row["SLO"]: row for _, row in slo_board.iterrows()}

        self.assertEqual(by_slo["Failed runs"]["STATE"], "Review")
        self.assertEqual(by_slo["Recovery SLA"]["STATE"], "Review")
        self.assertEqual(by_slo["Critical path risk"]["STATE"], "Review")
        self.assertGreaterEqual(slo_summary["review"], 1)

    def test_cost_center_chargeback_exposes_environment_and_database(self):
        cost_text = (APP_ROOT / "sections" / "cost_center.py").read_text(encoding="utf-8").upper()
        self.assertNotIn('COST_VIEW == "CONTRACT UTILIZATION"', cost_text)
        self.assertNotIn('"CONTRACT UTILIZATION"', cost_text)
        chargeback_block = cost_text[cost_text.index('ELIF COST_VIEW == "CHARGEBACK"'):]
        self.assertIn("AS ENVIRONMENT", chargeback_block)
        self.assertIn("AS DATABASE_NAME", chargeback_block)
        self.assertIn('"ENVIRONMENT"', chargeback_block)
        self.assertIn('"DATABASE_NAME"', chargeback_block)
        self.assertIn("ENVIRONMENT_ROLLUP", chargeback_block)
        self.assertIn("ALLOCATION_CONFIDENCE", chargeback_block)
        self.assertIn("CHARGEBACK_READY", chargeback_block)
        self.assertIn("CHARGEBACK INDIVIDUAL DEV DATABASES", chargeback_block)
        self.assertIn("GET_ACTIVE_ENVIRONMENT()", chargeback_block)
        self.assertIn("BUILD_MART_CHARGEBACK_SQL", chargeback_block)
        self.assertIn("FACT_CHARGEBACK_DAILY", chargeback_block)
        self.assertIn("LOAD_MART_TABLE", chargeback_block)
        self.assertIn("ROUTE_TELEMETRY", chargeback_block)
        self.assertIn("COST_OWNER", chargeback_block)
        self.assertIn("OWNER_EVIDENCE", chargeback_block)

    def test_ask_overwatch_reads_dba_operations_priority(self):
        priority_index = pd.DataFrame([
            {
                "OPERATIONS_PRIORITY_STATE": "Contain Now",
                "PRIORITY_SCORE": 88.5,
                "SECTION": "Warehouse Health",
                "WHY_NOW": "Queue or warehouse pressure; 1 overdue",
                "FIRST_MOVE": "Stabilize queue/spill pressure first.",
                "PROOF_REQUIRED": "capacity evidence, owner approval, rollback SQL",
            }
        ])
        cards = build_ask_overwatch_context({"dba_operations_priority_index": priority_index})

        self.assertEqual(cards[0]["surface"], "DBA Operations Priority")
        self.assertEqual(cards[0]["entity"], "Cost & Contract")
        self.assertIn("Queue or warehouse pressure", cards[0]["evidence"])
        self.assertIn("Stabilize", cards[0]["next_action"])

    def test_ask_overwatch_reads_dba_operator_runbook(self):
        plan = pd.DataFrame([
            {
                "RUNBOOK_ID": "DBA-RUNBOOK-202606011730",
                "PHASE_RANK": 1,
                "RUNBOOK_STEP": "Telemetry Check",
                "SECTION": "Warehouse Health",
                "OPERATIONS_PRIORITY_STATE": "Contain Now",
                "PRIORITY_SCORE": 88.5,
                "GO_NO_GO_GATE": "Evidence current",
                "DBA_MOVE": "Confirm operations route Warehouse Health.",
                "EVIDENCE_REQUIRED": "Queue or warehouse pressure; 1 overdue",
                "STOP_CONDITION": "Stop if source evidence is stale.",
            },
            {
                "RUNBOOK_ID": "DBA-RUNBOOK-202606011730",
                "PHASE_RANK": 2,
                "RUNBOOK_STEP": "Containment",
                "SECTION": "Warehouse Health",
                "OPERATIONS_PRIORITY_STATE": "Contain Now",
                "PRIORITY_SCORE": 88.5,
                "GO_NO_GO_GATE": "No irreversible changes",
                "DBA_MOVE": "Stabilize queue/spill pressure first.",
                "EVIDENCE_REQUIRED": "Warehouse route",
                "STOP_CONDITION": "Stop if source evidence is stale.",
            },
        ])
        cards = build_ask_overwatch_context({"dba_operator_runbook": plan})

        self.assertEqual(cards[0]["surface"], "DBA Operator Runbook")
        self.assertEqual(cards[0]["entity"], "Cost & Contract")
        self.assertIn("Telemetry current", cards[0]["evidence"])
        self.assertIn("Stabilize", cards[0]["next_action"])

    def test_alert_task_is_email_first_and_dba_focused(self):
        sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()

        self.assertIn("OVERWATCH_ANOMALY_CHECK", sql)
        self.assertIn("CONFIG_REQUIRED", sql)
        self.assertNotIn("DBA-ALERTS@YOURCOMPANY.COM", sql)
        self.assertIn("EMAIL_TARGET", sql)
        self.assertIn("EMAIL_SUBJECT", sql)
        self.assertIn("EMAIL_BODY", sql)
        self.assertIn("EMAIL_READY", sql)
        self.assertIn("TASK FAILURE", sql)
        self.assertIn("STORED PROCEDURE", sql)
        self.assertNotIn("COST SAVINGS VERIFICATION FAILURE", sql)
        self.assertNotIn("COST_SAVINGS_VERIFIER_FAILURE", sql)
        self.assertNotIn("OVERWATCH_COST_SAVINGS_VERIFY", sql)
        self.assertIn("GRANT/REVOKE ACTIVITY", sql)
        self.assertIn("WAREHOUSE SETTING CHANGE", sql)
        self.assertIn("OVERWATCH_ALERT_RULES", sql)
        self.assertIn("OVERWATCH_ALERT_RULE_AUDIT", sql)
        self.assertIn("OVERWATCH_ALERT_TRIAGE_V", sql)
        self.assertIn("OVERWATCH_ALERT_DELIVERY_LOG", sql)
        self.assertNotIn("OVERWATCH_OWNER_DIRECTORY", sql)
        self.assertNotIn("OVERWATCH_OWNER_DIRECTORY_ACTIVE_V", sql)
        self.assertIn("SP_OVERWATCH_SEND_ALERT_DIGEST", sql)
        self.assertIn("SYSTEM$SEND_EMAIL", sql)
        self.assertIn("EMAIL_DRY_RUN", sql)
        self.assertIn("OWNER_EMAIL", sql)
        self.assertIn("ONCALL_PRIMARY", sql)
        self.assertIn("APPROVAL_GROUP", sql)
        self.assertIn("OWNER_SOURCE", sql)
        self.assertIn("STATUS_REASON", sql)
        self.assertIn("LAST_DELIVERY_AT", sql)
        self.assertIn("ESCALATION_ACK_BY", sql)
        self.assertIn("ROUTED_TO_ACTION_QUEUE_AT", sql)
        self.assertNotIn("TEAMS_TARGET", sql)

    def test_alert_email_delivery_procedure_is_dry_run_guarded_and_audited(self):
        sql = build_alert_email_delivery_procedure_sql(email_target="dba-alerts@example.com").upper()

        self.assertIn("SP_OVERWATCH_SEND_ALERT_DIGEST", sql)
        self.assertIn("P_DRY_RUN BOOLEAN DEFAULT TRUE", sql)
        self.assertIn("SYSTEM$SEND_EMAIL", sql)
        self.assertIn("OVERWATCH_EMAIL_INT", sql)
        self.assertIn("OVERWATCH_ALERT_DELIVERY_LOG", sql)
        self.assertIn("EMAIL_DRY_RUN", sql)
        self.assertIn("LAST_DELIVERY_AT", sql)
        self.assertIn("DBA-ALERTS@EXAMPLE.COM", sql)

    def test_workload_recovery_audit_ddl_captures_owner_and_verification_evidence(self):
        sql = build_workload_recovery_audit_ddl().upper()

        self.assertIn("OVERWATCH_WORKLOAD_RECOVERY_AUDIT", sql)
        self.assertIn("OWNER_EMAIL", sql)
        self.assertIn("ONCALL_PRIMARY", sql)
        self.assertIn("APPROVAL_GROUP", sql)
        self.assertIn("OWNER_APPROVAL_STATUS", sql)
        self.assertIn("RECOVERY_SLA_STATE", sql)
        self.assertIn("VERIFICATION_QUERY", sql)
        self.assertIn("VERIFICATION_RESULT", sql)
        self.assertIn("OVERWATCH_WORKLOAD_RECOVERY_AUDIT_LATEST_V", sql)

    def test_alert_email_builders_and_unified_issue_rows(self):
        alert = pd.DataFrame([{
            "ALERT_TS": "2026-05-31 09:00:00",
            "COMPANY": "ALFA",
            "ENVIRONMENT": "PROD",
            "CATEGORY": "Reliability",
            "ALERT_TYPE": "Task Failure",
            "SEVERITY": "Critical",
            "ENTITY_NAME": "ALFA_EDW_PROD.PUBLIC.T_LOAD",
            "MESSAGE": "Task failed.",
            "SUGGESTED_ACTION": "Open task graph.",
            "OWNER": "DBA",
            "EMAIL_TARGET": "dba-alerts@example.com",
            "DELIVERY_STATUS": "EMAIL_READY",
            "STATUS": "New",
        }])
        queue = pd.DataFrame([{
            "UPDATED_AT": "2026-05-31 08:00:00",
            "SOURCE": "Warehouse Health",
            "CATEGORY": "Capacity",
            "SEVERITY": "Medium",
            "ENTITY_NAME": "WH_ALFA_LOAD",
            "STATUS": "New",
            "FINDING": "Queued workload.",
            "RECOMMENDED_ACTION": "Review settings.",
            "OWNER": "DBA",
        }])
        exceptions = pd.DataFrame([{
            "Severity": "High",
            "Signal": "Credit spike",
            "Evidence": "Credits rose 80%.",
            "Action": "Explain usage movement.",
            "Route": "Cost & Contract",
            "Workflow": "Cost by Warehouse",
        }])

        subject = build_alert_email_subject(alert.iloc[0], company="ALFA")
        body = build_alert_email_body(alert.iloc[0], company="ALFA")
        issues = build_dashboard_issue_rows(exceptions=exceptions, alerts=alert, queue=queue)

        self.assertIn("OVERWATCH Critical", subject)
        self.assertIn("dba-alerts@example.com", alert["EMAIL_TARGET"].iloc[0])
        self.assertIn("Environment: PROD", body)
        self.assertEqual(len(issues), 3)
        self.assertEqual(issues.iloc[0]["SEVERITY"], "Critical")
        self.assertEqual(set(issues["ISSUE_SOURCE"]), {"Alert History", "Action Queue", "Control Room Signal"})
        self.assertTrue(
            issues.loc[issues["ISSUE_SOURCE"].eq("Alert History"), "EMAIL_TARGET"]
            .astype(str)
            .str.contains("dba-alerts@example.com")
            .all()
        )
        self.assertTrue(
            (
                issues.loc[issues["ISSUE_SOURCE"].ne("Alert History"), "EMAIL_TARGET"]
                == DEFAULT_ALERT_EMAIL
            ).all()
        )
        self.assertNotIn("@yahoo.com", "\n".join(issues["EMAIL_TARGET"].astype(str)))

    def test_alert_lifecycle_sla_and_status_sql(self):
        df = pd.DataFrame([
            {
                "ALERT_ID": 10,
                "ALERT_TS": "2026-05-31 00:00:00",
                "ALERT_TYPE": "Task Failure",
                "SEVERITY": "High",
                "STATUS": "New",
                "OWNER": "DBA",
            },
            {
                "ALERT_ID": 11,
                "ALERT_TS": "2026-05-30 00:00:00",
                "ALERT_TYPE": "Credit Spike",
                "SEVERITY": "Medium",
                "STATUS": "Fixed",
                "OWNER": "DBA",
            },
        ])
        triage = annotate_alert_triage_frame(df, now="2026-05-31 12:00:00")
        status_sql = build_alert_status_update_sql(
            alert_id=10,
            status="Fixed",
            reason="Verified next task run succeeded under INC123.",
            actor="DBA_USER",
            columns={
                "STATUS", "RESOLVED", "ACKNOWLEDGED_BY", "ACKNOWLEDGED_AT",
                "STATUS_REASON", "LAST_STATUS_BY", "LAST_STATUS_AT",
            },
        ).upper()
        rules = alert_rule_catalog()

        self.assertEqual(triage.loc[triage["ALERT_ID"] == 10, "SLA_STATE"].iloc[0], "Overdue")
        self.assertEqual(triage.loc[triage["ALERT_ID"] == 11, "SLA_STATE"].iloc[0], "Closed")
        self.assertIn("STATUS = 'FIXED'", status_sql)
        self.assertIn("RESOLVED = TRUE", status_sql)
        self.assertIn("STATUS_REASON", status_sql)
        self.assertIn("LAST_STATUS_BY = 'DBA_USER'", status_sql)
        self.assertIn("WHERE ALERT_ID = 10", status_sql)
        self.assertIn("TASK_FAILURE", set(rules["RULE_ID"]))
        self.assertIn("SLA_HOURS", rules.columns)

    def test_alert_triage_preserves_snowflake_view_rule_outputs(self):
        df = pd.DataFrame([{
            "ALERT_ID": 12,
            "ALERT_TS": "2026-05-30 00:00:00",
            "ALERT_TYPE": "Task Failure",
            "SEVERITY": "High",
            "STATUS": "New",
            "OWNER": "Pipeline Owner",
            "SLA_TARGET_HOURS": 48,
            "ALERT_AGE_HOURS": 10,
            "SLA_STATE": "Within SLA",
            "ESCALATION_TARGET": "Pipeline Owner",
            "TRIAGE_PRIORITY": 777,
        }])

        triage = annotate_alert_triage_frame(df, now="2026-05-31 12:00:00")

        self.assertEqual(triage["SLA_TARGET_HOURS"].iloc[0], 48)
        self.assertEqual(triage["ALERT_AGE_HOURS"].iloc[0], 10)
        self.assertEqual(triage["SLA_STATE"].iloc[0], "Within SLA")
        self.assertEqual(triage["ESCALATION_TARGET"].iloc[0], "Pipeline Owner")
        self.assertEqual(triage["TRIAGE_PRIORITY"].iloc[0], 777)

    def test_alert_history_routes_task_and_procedure_alerts_with_recovery_routing(self):
        alerts = pd.DataFrame([
            {
                "ALERT_ID": 30,
                "ALERT_TS": "2026-05-31 10:00:00",
                "COMPANY": "ALFA",
                "ENVIRONMENT": "PROD",
                "DATABASE_NAME": "ALFA_EDW_PROD",
                "SCHEMA_NAME": "PUBLIC",
                "CATEGORY": "Reliability",
                "ALERT_TYPE": "Task Failure",
                "SEVERITY": "High",
                "STATUS": "New",
                "ENTITY_NAME": "ALFA_EDW_PROD.PUBLIC.T_LOAD_POLICY",
                "MESSAGE": "2 failed task run(s) in the last 24 hours. Sample: table does not exist.",
                "SUGGESTED_ACTION": "Open Workload Operations task graphs.",
                "PROOF_QUERY": "",
                "OWNER": "DBA / Pipeline Owner",
                "ESCALATION_TARGET": "Pipeline Owner",
                "SLA_TARGET_HOURS": 4,
                "ALERT_AGE_HOURS": 6.5,
                "SLA_STATE": "Overdue",
            },
            {
                "ALERT_ID": 31,
                "ALERT_TS": "2026-05-31 10:05:00",
                "COMPANY": "ALFA",
                "ENVIRONMENT": "ALFA_EDW_DEV",
                "DATABASE_NAME": "ALFA_EDW_DEV",
                "SCHEMA_NAME": "PUBLIC",
                "CATEGORY": "Reliability",
                "ALERT_TYPE": "Stored Procedure Runtime Spike",
                "SEVERITY": "High",
                "STATUS": "Acknowledged",
                "ENTITY_NAME": "ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY",
                "MESSAGE": "Average CALL duration 90.0s vs baseline 30.0s.",
                "SUGGESTED_ACTION": "Open Workload Operations stored procedures.",
                "PROOF_QUERY": "CALL BAD_PROC()",
                "OWNER": "Procedure Owner",
                "SLA_TARGET_HOURS": 8,
                "ALERT_AGE_HOURS": 2,
                "SLA_STATE": "Within SLA",
            },
            {
                "ALERT_ID": 32,
                "ALERT_TS": "2026-05-31 10:10:00",
                "COMPANY": "ALFA",
                "ENVIRONMENT": "No Database Context",
                "CATEGORY": "Cost Control",
                "ALERT_TYPE": "Credit Spike",
                "SEVERITY": "Medium",
                "STATUS": "New",
                "ENTITY_NAME": "WH_ALFA_LOAD",
                "MESSAGE": "Credits doubled.",
                "PROOF_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY LIMIT 10",
                "OWNER": "DBA / Cost owner",
            },
        ])

        actions = alert_history_to_actions(alerts, company="ALFA")
        by_entity = {action["Entity"]: action for action in actions}
        task = by_entity["ALFA_EDW_PROD.PUBLIC.T_LOAD_POLICY"]
        proc = by_entity["ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY"]
        cost = by_entity["WH_ALFA_LOAD"]

        self.assertEqual(task["Category"], "Task & Procedure Reliability")
        self.assertEqual(task["Entity Type"], "Task")
        self.assertNotIn("Owner Approval Status", task)
        self.assertNotIn("Approver", task)
        self.assertEqual(task["Oncall Primary"], "")
        self.assertIn("MONITORING_CONTEXT", task["Owner Source"])
        self.assertEqual(task["Recovery Audit State"], "Audit Required")
        self.assertEqual(task["Recovery SLA State"], "Recovery SLA Breach")
        self.assertEqual(task["Recovery SLA Target Hours"], 4.0)
        self.assertEqual(task["Recovery SLA Hours"], 6.5)
        self.assertEqual(task["Baseline Value"], 0.0)
        self.assertEqual(task["Current Value"], 2.0)
        self.assertIn("TASK_HISTORY", task["Verification Query"])
        self.assertNotIn("EXECUTE TASK", task["Generated SQL Fix"].upper())
        self.assertEqual(verification_query_safety_issues(task["Verification Query"]), [])

        self.assertEqual(proc["Category"], "Task & Procedure Reliability")
        self.assertEqual(proc["Entity Type"], "Stored Procedure")
        self.assertNotIn("Owner Approval Status", proc)
        self.assertNotIn("Approver", proc)
        self.assertEqual(proc["Oncall Primary"], "")
        self.assertEqual(proc["Recovery SLA State"], "Open Failure")
        self.assertEqual(proc["Baseline Value"], 30.0)
        self.assertEqual(proc["Current Value"], 90.0)
        self.assertIn("QUERY_HISTORY", proc["Verification Query"])
        self.assertIn("QUERY_TYPE = 'CALL'", proc["Verification Query"])
        self.assertEqual(verification_query_safety_issues(proc["Verification Query"]), [])

        self.assertEqual(cost["Category"], "Cost Control")
        self.assertNotIn("Owner Approval Status", cost)
        self.assertEqual(verification_query_safety_issues(cost["Verification Query"]), [])

    def test_alert_triage_view_sql_exposes_auditable_sla_state(self):
        sql = build_alert_triage_view_sql().upper()

        self.assertIn("CREATE OR REPLACE VIEW", sql)
        self.assertIn("OVERWATCH_ALERT_TRIAGE_V", sql)
        self.assertIn("SLA_TARGET_HOURS", sql)
        self.assertIn("SLA_STATE", sql)
        self.assertIn("ESCALATION_TARGET", sql)
        self.assertIn("TRIAGE_PRIORITY", sql)
        self.assertIn("OVERWATCH_ALERT_RULES", sql)

    def test_alert_rule_update_sql_is_guarded_and_configurable(self):
        rules = normalize_alert_rule_frame(pd.DataFrame([{
            "RULE_ID": "TASK_FAILURE",
            "CATEGORY": "Reliability",
            "ALERT_TYPE": "Task Failure",
            "DEFAULT_SEVERITY": "high",
            "SLA_HOURS": 8,
            "OWNER": "DBA",
            "ROUTE": "Alert Center",
            "RUNBOOK": "Review task graph evidence and route to owner.",
            "IS_ACTIVE": True,
        }]), source="Database")
        sql = build_alert_rule_update_sql(
            rule_id="TASK_FAILURE",
            default_severity="Critical",
            sla_hours=4,
            owner="DBA Lead",
            route="Workload Operations",
            runbook="Escalate failed critical task graph to the DBA lead and pipeline owner.",
            actor="DBA_USER",
        ).upper()
        audit_ddl = build_alert_rule_audit_ddl().upper()
        audit_insert = build_alert_rule_audit_insert_sql(
            rule_id="TASK_FAILURE",
            default_severity="Critical",
            sla_hours=4,
            owner="DBA Lead",
            route="Workload Operations",
            runbook="Escalate failed critical task graph to the DBA lead and pipeline owner.",
            actor="DBA_USER",
            reason="Tighten failed task SLA before production release.",
        ).upper()

        self.assertEqual(rules.iloc[0]["DEFAULT_SEVERITY"], "High")
        self.assertEqual(rules.iloc[0]["RULE_SOURCE"], "Database")
        self.assertIn("OVERWATCH_ALERT_RULE_AUDIT", audit_ddl)
        self.assertIn("PRIOR_DEFAULT_SEVERITY", audit_ddl)
        self.assertIn("INSERT INTO", audit_insert)
        self.assertIn("OVERWATCH_ALERT_RULE_AUDIT", audit_insert)
        self.assertIn("PRIOR_SLA_HOURS", audit_insert)
        self.assertIn("NEW_SLA_HOURS", audit_insert)
        self.assertIn("CHANGED_BY", audit_insert)
        self.assertIn("TIGHTEN FAILED TASK SLA", audit_insert)
        self.assertIn("UPDATE", sql)
        self.assertIn("OVERWATCH_ALERT_RULES", sql)
        self.assertIn("DEFAULT_SEVERITY = 'CRITICAL'", sql)
        self.assertIn("SLA_HOURS = 4", sql)
        self.assertIn("OWNER = 'DBA LEAD'", sql)
        self.assertIn("UPDATED_BY = 'DBA_USER'", sql)
        self.assertIn("WHERE RULE_ID = 'TASK_FAILURE'", sql)
        with self.assertRaises(ValueError):
            build_alert_rule_update_sql(
                rule_id="TASK_FAILURE",
                default_severity="High",
                sla_hours=0,
                owner="DBA",
                route="Alert Center",
                runbook="Too short.",
            )

    def test_alert_owner_route_and_lifecycle_boards_prioritize_operational_gaps(self):
        alerts = pd.DataFrame([
            {
                "ALERT_ID": "A1",
                "ALERT_TS": pd.Timestamp("2026-06-01 08:00"),
                "STATUS": "New",
                "SLA_STATE": "Overdue",
                "SEVERITY": "High",
                "CATEGORY": "Reliability",
                "ALERT_TYPE": "Task Failure",
                "ENTITY_NAME": "LOAD_POLICY",
                "OWNER": "DBA",
                "EMAIL_TARGET": "dba-alerts@example.com",
                "DELIVERY_STATUS": "EMAIL_READY",
                "SUGGESTED_ACTION": "Open task graph and assign owner.",
            },
            {
                "ALERT_ID": "A2",
                "ALERT_TS": pd.Timestamp("2026-06-01 09:00"),
                "STATUS": "New",
                "SLA_STATE": "Due Soon",
                "SEVERITY": "Medium",
                "CATEGORY": "Cost Control",
                "ALERT_TYPE": "Credit Spike",
                "ENTITY_NAME": "COMPUTE_WH",
                "OWNER": "DBA / Cost owner",
                "EMAIL_TARGET": "",
                "DELIVERY_STATUS": "",
                "SUGGESTED_ACTION": "Explain usage movement.",
            },
        ])
        queue = pd.DataFrame([{
            "STATUS": "New",
            "SEVERITY": "High",
            "CATEGORY": "Reliability",
            "ENTITY": "LOAD_POLICY",
            "OWNER": "Pipeline Owner Smith",
            "OWNER_EMAIL": "dba-alerts@example.com",
            "ONCALL_PRIMARY": "DBA On-Call",
            "ESCALATION_TARGET": "DBA Lead",
            "OWNER_SOURCE": "MONITORING_CONTEXT:TASK_DEFAULT",
            "RECOMMENDED_ACTION": "Work queued task incident.",
        }])

        route_summary, route_board = _alert_owner_route_board(alerts, queue)
        lifecycle = _alert_lifecycle_board(alerts, queue)
        integration = _alert_integration_health_board(
            alerts,
            queue,
            delivery_log=pd.DataFrame(),
        )
        integration_by_control = {row["CONTROL"]: row for _, row in integration.iterrows()}

        self.assertEqual(route_summary["route_gaps"], 2)
        self.assertIn("Needs named route", set(route_board["OWNER_ROUTE_STATE"]))
        self.assertEqual(lifecycle.iloc[0]["LIFECYCLE_STATE"], "Escalate now")
        self.assertIn("post-fix telemetry status", lifecycle.iloc[0]["CLOSURE_STATUS_REQUIRED"])
        self.assertEqual(integration.iloc[0]["CONTROL"], "Action queue lifecycle")
        self.assertEqual(integration_by_control["Snowflake notification integration"]["STATE"], "Review")
        self.assertEqual(integration_by_control["Action queue lifecycle"]["STATE"], "Review")

    def test_alert_delivery_audit_and_escalation_ack_sql(self):
        ddl = build_alert_delivery_log_ddl().upper()
        insert_sql = build_alert_delivery_log_insert_sql(
            alert_ids=[101, "102"],
            company="ALFA",
            environment="PROD",
            delivery_target="dba-alerts@example.com",
            email_subject="OVERWATCH Alert Digest",
            email_body="Digest body",
            actor="DBA_USER",
            notes="Sent digest through Outlook and opened INC123.",
        ).upper()
        mark_sql = build_alert_delivery_mark_sql(
            alert_ids=[101, 102],
            delivery_target="dba-alerts@example.com",
            actor="DBA_USER",
            columns={
                "DELIVERY_STATUS", "DELIVERY_TARGET", "EMAIL_TARGET",
                "LAST_DELIVERY_AT", "LAST_DELIVERY_BY", "DELIVERY_LOG_COUNT",
                "ESCALATED_TO", "ESCALATED_AT", "LAST_STATUS_BY", "LAST_STATUS_AT",
            },
        ).upper()
        ack_sql = build_alert_escalation_ack_sql(
            alert_id=101,
            actor="DBA_USER",
            note="Owner acknowledged escalation under INC123.",
            columns={
                "STATUS", "ACKNOWLEDGED_BY", "ACKNOWLEDGED_AT",
                "ESCALATION_ACK_BY", "ESCALATION_ACK_AT", "ESCALATION_ACK_NOTE",
                "LAST_STATUS_BY", "LAST_STATUS_AT",
            },
        ).upper()

        self.assertIn("CREATE TABLE IF NOT EXISTS", ddl)
        self.assertIn("OVERWATCH_ALERT_DELIVERY_LOG", ddl)
        self.assertIn("ALERT_IDS", ddl)
        self.assertIn("PARSE_JSON", insert_sql)
        self.assertIn("EMAIL_LOGGED", insert_sql)
        self.assertIn("LAST_DELIVERY_AT = CURRENT_TIMESTAMP()", mark_sql)
        self.assertIn("DELIVERY_LOG_COUNT = COALESCE", mark_sql)
        self.assertIn("ESCALATED_TO = COALESCE", mark_sql)
        self.assertIn("ESCALATION_ACK_BY = 'DBA_USER'", ack_sql)
        self.assertIn("ESCALATION_ACK_NOTE", ack_sql)
        self.assertIn("STATUS = CASE", ack_sql)
        with self.assertRaises(ValueError):
            build_alert_delivery_log_insert_sql(
                alert_ids=[],
                company="ALFA",
                environment="PROD",
                delivery_target="dba-alerts@example.com",
                email_subject="Subject",
                email_body="Body",
                actor="DBA_USER",
                notes="Sent email.",
            )

    def test_alert_digest_prioritizes_overdue_and_owner_gaps(self):
        now = pd.Timestamp.now()
        df = pd.DataFrame([
            {
                "ALERT_ID": 20,
                "ALERT_TS": now - pd.Timedelta(hours=10),
                "ALERT_TYPE": "Task Failure",
                "CATEGORY": "Reliability",
                "SEVERITY": "High",
                "STATUS": "New",
                "ENTITY_NAME": "ALFA_EDW_PROD.PUBLIC.T_LOAD",
                "OWNER": "DBA",
                "MESSAGE": "Task failed twice.",
                "SUGGESTED_ACTION": "Open task graph and assign owner.",
                "DELIVERY_STATUS": "EMAIL_READY",
            },
            {
                "ALERT_ID": 21,
                "ALERT_TS": now - pd.Timedelta(hours=6),
                "ALERT_TYPE": "Stored Procedure Failure / Runtime Spike",
                "CATEGORY": "Reliability",
                "SEVERITY": "High",
                "STATUS": "Acknowledged",
                "ENTITY_NAME": "ALFA_EDW_DEV.PUBLIC.P_LOAD",
                "OWNER": "ALFA Data Engineering",
                "MESSAGE": "Procedure runtime doubled.",
                "SUGGESTED_ACTION": "Compare child query history.",
                "DELIVERY_STATUS": "EMAIL_READY",
            },
            {
                "ALERT_ID": 22,
                "ALERT_TS": now - pd.Timedelta(hours=2),
                "ALERT_TYPE": "Credit Spike",
                "CATEGORY": "Cost Control",
                "SEVERITY": "Medium",
                "STATUS": "Fixed",
                "ENTITY_NAME": "WH_ALFA_LOAD",
                "OWNER": "DBA / Cost owner",
                "MESSAGE": "Credits returned to baseline.",
                "DELIVERY_STATUS": "EMAIL_READY",
            },
        ])

        summary = build_alert_digest_summary(df)
        subject = build_alert_digest_subject(df, company="ALFA", environment="PROD")
        body = build_alert_digest_body(df, company="ALFA", environment="PROD", recipient="dba-alerts@example.com")
        candidates = alert_escalation_candidates(df, limit=5)

        self.assertEqual(summary["open"], 2)
        self.assertEqual(summary["critical_high"], 2)
        self.assertGreaterEqual(summary["overdue"], 1)
        self.assertGreaterEqual(summary["needs_owner"], 1)
        self.assertIn("2 open", subject)
        self.assertIn("dba-alerts@example.com", body)
        self.assertIn("Escalate first", body)
        self.assertEqual(candidates.iloc[0]["ALERT_ID"], 20)
        self.assertIn("SLA_STATE", candidates.columns)

    def test_alert_center_operability_rows_flag_source_health_and_scope(self):
        alerts = pd.DataFrame([
            {
                "ALERT_ID": 501,
                "ALERT_TS": "2026-05-31 09:00:00",
                "CATEGORY": "Reliability",
                "ALERT_TYPE": "Task Failure",
                "SEVERITY": "High",
                "STATUS": "New",
                "SLA_STATE": "Overdue",
                "OWNER": "DBA",
                "DELIVERY_STATUS": "EMAIL_READY",
                "EMAIL_TARGET": "",
            }
        ])
        queue = pd.DataFrame([
            {"STATUS": "New", "CATEGORY": "Reliability", "ENTITY_NAME": "ALFA_EDW_PROD.PUBLIC.T_LOAD"},
            {"STATUS": "Fixed", "CATEGORY": "Capacity", "ENTITY_NAME": "WH_ALFA_LOAD"},
        ])
        rules = alert_rule_catalog()
        data = {
            "alerts": alerts,
            "action_queue": queue,
            "delivery_log": pd.DataFrame(),
            "rules": rules,
            "issues": pd.DataFrame([{"ISSUE_SOURCE": "Alert History", "SEVERITY": "High"}]),
            "delivery_error": "OVERWATCH_ALERT_DELIVERY_LOG missing",
        }

        rows = _alert_center_operability_rows(
            data,
            company="ALFA",
            environment="PROD",
            days=7,
            limit=200,
            loaded_scope=("ALFA", "DEV_ALL", 7, 200),
        )
        by_control = {row["CONTROL"]: row for _, row in rows.iterrows()}

        self.assertEqual(by_control["Loaded scope status"]["STATE"], "Scope Stale")
        self.assertEqual(by_control["Alert history input"]["STATE"], "Ready")
        self.assertIn("1 open", by_control["Alert history input"]["EVIDENCE"])
        self.assertEqual(by_control["Delivery audit input"]["STATE"], "Needs Data")
        self.assertEqual(by_control["Rule catalog input"]["STATE"], "Fallback")
        self.assertEqual(by_control["Email route"]["STATE"], "Review")
        self.assertEqual(by_control["Alert routing"]["STATE"], "Review")
        self.assertLess(_alert_center_health_score(rows), 100)

    def test_alert_center_operability_rows_score_ready_controls(self):
        data = {
            "alerts": pd.DataFrame(),
            "action_queue": pd.DataFrame(),
            "delivery_log": pd.DataFrame([{"DELIVERY_TS": "2026-05-31 09:00:00"}]),
            "rules": normalize_alert_rule_frame(pd.DataFrame([{
                "RULE_ID": "TASK_FAILURE",
                "CATEGORY": "Reliability",
                "ALERT_TYPE": "Task Failure",
                "DEFAULT_SEVERITY": "High",
                "SLA_HOURS": 8,
                "OWNER": "Pipeline Owner",
                "ROUTE": "Workload Operations",
                "RUNBOOK": "Review task graph evidence and route to owner.",
                "IS_ACTIVE": True,
            }]), source="Database"),
            "issues": pd.DataFrame(),
        }

        rows = _alert_center_operability_rows(
            data,
            company="ALFA",
            environment="PROD",
            days=7,
            limit=200,
            loaded_scope=("ALFA", "PROD", 7, 200),
        )

        self.assertEqual(_alert_center_health_score(rows), 100)
        self.assertEqual(
            rows.loc[rows["CONTROL"] == "Rule catalog input", "STATE"].iloc[0],
            "Ready",
        )

    def test_alert_center_action_brief_prioritizes_single_operator_move(self):
        blocked = _alert_center_action_brief(
            open_issues=3,
            open_alerts=2,
            critical_high=2,
            overdue=1,
            email_ready=2,
            email_logged=0,
            open_queue=1,
            readiness_rows=pd.DataFrame([{
                "CONTROL": "Delivery audit input",
                "STATE": "Needs Data",
                "EVIDENCE": "Delivery log table is missing.",
                "NEXT_ACTION": "Deploy delivery audit table.",
            }]),
        )
        self.assertEqual(blocked["target"], "Active Alerts")
        self.assertIn("Delivery audit input", blocked["detail"])
        self.assertIn("Deploy delivery audit table", blocked["detail"])

        overdue = _alert_center_action_brief(
            open_issues=3,
            open_alerts=2,
            critical_high=2,
            overdue=1,
            email_ready=2,
            email_logged=0,
            open_queue=1,
        )
        self.assertEqual(overdue["target"], "Active Alerts")
        self.assertIn("overdue", overdue["detail"])

        queue_only = _alert_center_action_brief(
            open_issues=1,
            open_alerts=0,
            critical_high=0,
            overdue=0,
            email_ready=0,
            email_logged=0,
            open_queue=4,
        )
        self.assertEqual(queue_only["target"], "Alert Settings / Admin")
        self.assertIn("4 open queue", queue_only["detail"])

        clear = _alert_center_action_brief(
            open_issues=0,
            open_alerts=0,
            critical_high=0,
            overdue=0,
            email_ready=0,
            email_logged=0,
            open_queue=0,
        )
        self.assertEqual(clear["state"], "Clear")

    def test_alert_center_exception_rows_prioritize_loaded_issue_signals(self):
        alerts = pd.DataFrame([
            {
                "SEVERITY": "Critical",
                "STATUS": "New",
                "SLA_STATE": "Overdue",
                "OWNER": "DBA",
                "DELIVERY_STATUS": "EMAIL_READY",
            },
            {
                "SEVERITY": "Low",
                "STATUS": "Closed",
                "SLA_STATE": "Ready",
                "OWNER": "Named Owner",
                "DELIVERY_STATUS": "EMAIL_LOGGED",
            },
        ])
        queue = pd.DataFrame([{"STATUS": "New"}])
        issues = pd.DataFrame([
            {"SEVERITY": "Critical"},
            {"SEVERITY": "Medium"},
        ])
        delivery_log = pd.DataFrame([{"DELIVERY_STATUS": "FAILED"}])
        readiness_rows = pd.DataFrame([{"STATE": "Needs Data"}])

        rows = _alert_center_exception_rows(
            alerts=alerts,
            queue=queue,
            issues=issues,
            delivery_log=delivery_log,
            readiness_rows=readiness_rows,
        )
        by_signal = {row["SIGNAL"]: row for _, row in rows.iterrows()}

        self.assertEqual(rows.iloc[0]["SEVERITY"], "High")
        self.assertEqual(by_signal["Critical/high alerts"]["COUNT"], 1)
        self.assertEqual(by_signal["Overdue alert SLAs"]["ROUTE"], "Active Alerts")
        self.assertEqual(by_signal["Generic alert routes"]["OWNER"], "Platform DBA")
        self.assertEqual(by_signal["Open action queue"]["COUNT"], 1)
        self.assertEqual(by_signal["Open action queue"]["ROUTE"], "Alert Settings / Admin")
        self.assertEqual(by_signal["Alert control blockers"]["ROUTE"], "Active Alerts")
        self.assertEqual(by_signal["Delivery failures"]["COUNT"], 1)
        self.assertEqual(by_signal["Delivery failures"]["ROUTE"], "Alert Settings / Admin")

    def test_alert_center_pending_state_uses_active_alerts_default(self):
        brief = _alert_center_pending_brief("Alert Brief", set())

        self.assertEqual(brief["state"], "Ready")
        self.assertIn("Load Active Alerts", brief["headline"])
        self.assertIn("Inputs on load", brief["detail"])

        workflows = _alert_center_brief_workflow_rows()
        self.assertEqual(
            [row["VIEW"] for row in workflows],
            [
                "Active Alerts",
                "Cost Alerts",
                "Reliability Alerts",
                "Security Alerts",
                "Alert History",
                "Alert Settings / Admin",
            ],
        )
        by_view = {row["VIEW"]: row for row in workflows}
        self.assertIn("Open Active Alerts", by_view["Active Alerts"]["BUTTON_LABEL"])
        self.assertIn("Cost", by_view["Cost Alerts"]["BUTTON_LABEL"])
        self.assertIn("alert history", by_view["Active Alerts"]["SOURCES"].lower())
        self.assertIn("Open Alert History", by_view["Alert History"]["BUTTON_LABEL"])
        self.assertIn("Open Alert Settings", by_view["Alert Settings / Admin"]["BUTTON_LABEL"])

    def test_alert_center_operator_workflow_spine_prioritizes_next_move(self):
        alerts = pd.DataFrame([{
            "SEVERITY": "Critical",
            "STATUS": "New",
            "CATEGORY": "Cost Control",
            "ALERT_TYPE": "Cortex spend spike",
            "ENTITY_NAME": "SNOW_ANALYST",
            "OWNER": "DBA / AI cost route",
            "ROUTE": "Cost & Contract",
            "SUGGESTED_ACTION": "Review Cortex user/source spend and quota route.",
            "PROOF_QUERY": "SELECT * FROM FACT_CORTEX_DAILY",
            "DELIVERY_STATUS": "EMAIL_READY",
            "REMEDIATION_MODE": "STATUS_REVIEW",
            "ALERT_TS": pd.Timestamp("2026-06-17 04:00:00"),
            "FIRST_SEEN_AT": pd.Timestamp("2026-06-17 04:00:00"),
        }])
        queue = pd.DataFrame([{
            "CATEGORY": "Cost Control",
            "ENTITY_NAME": "SNOW_ANALYST",
            "STATUS": "New",
            "TICKET_ID": "",
            "EVIDENCE_GAP": "Need Cortex baseline and quota evidence.",
            "APPROVAL_GROUP": "DBA / AI cost route",
        }])
        incident_board = build_alert_incident_action_board(
            alerts,
            queue,
            now=pd.Timestamp("2026-06-17 09:30:00"),
        )
        workflow = _alert_operator_workflow_rows(
            alerts=alerts,
            queue=queue,
            delivery_log=pd.DataFrame(),
            incident_board=incident_board,
            native_registry=pd.DataFrame([{"STATUS": "CANDIDATE"}]),
            remediation_policy=pd.DataFrame([{"POLICY_ID": "POLICY_CORTEX_QUOTA_REVIEW"}]),
            remediation_dry_run=pd.DataFrame([{"DRY_RUN_STATUS": "BLOCKED_REVIEW_REQUIRED"}]),
        )
        by_step = {row["STEP"]: row for _, row in workflow.iterrows()}

        self.assertEqual(by_step["1 Detect"]["COUNT"], 1)
        self.assertEqual(by_step["2 Triage"]["STATE"], "Escalate")
        self.assertEqual(by_step["3 Route"]["STATE"], "Review")
        self.assertEqual(by_step["4 Notify"]["COUNT"], 1)
        self.assertEqual(by_step["5 Dry-run"]["STATE"], "Candidate")
        self.assertIn("dry-run row", by_step["5 Dry-run"]["WHAT_TO_CHECK"])
        self.assertEqual(by_step["6 Close"]["COUNT"], 1)

        packet = _alert_next_incident_packet(incident_board)
        by_checkpoint = {row["CHECKPOINT"]: row for _, row in packet.iterrows()}
        self.assertIn("Cortex spend spike", by_checkpoint["What fired"]["DETAIL"])
        self.assertEqual(by_checkpoint["Owner and route"]["STATE"], "Review")
        self.assertEqual(by_checkpoint["Automation boundary"]["STATE"], "STATUS_REVIEW")
        self.assertIn("Dry-run/status review", by_checkpoint["Automation boundary"]["NEXT_ACTION"])

    def test_alert_domain_next_move_rows_show_owner_workflow_and_boundary(self):
        alerts = pd.DataFrame([{
            "SEVERITY": "High",
            "STATUS": "New",
            "CATEGORY": "Cost Control",
            "ALERT_TYPE": "Cortex spend spike",
            "ENTITY_NAME": "SNOW_DTI_ANALYST",
            "OWNER": "DBA / AI cost route",
            "ROUTE": "Cost & Contract",
            "SUGGESTED_ACTION": "Review Cortex spend and quota settings.",
            "PROOF_QUERY": "SELECT * FROM FACT_CORTEX_DAILY",
            "REMEDIATION_MODE": "RECOMMEND",
            "ALERT_TS": pd.Timestamp("2026-06-17 08:00:00"),
        }])
        board = build_section_alert_signal_board(alerts, section="Cost & Behavior")
        moves = _alert_domain_next_move_rows(board, "Cost & Behavior")
        by_move = {row["MOVE"]: row for _, row in moves.iterrows()}

        self.assertIn("Cortex spend spike", by_move["Confirm signal"]["DETAIL"])
        self.assertIn("Cost & Contract > Cost by User / Role", by_move["Open owner workflow"]["DETAIL"])
        self.assertIn("FACT_CORTEX_DAILY", by_move["Capture evidence"]["DETAIL"])
        self.assertEqual(by_move["Respect boundary"]["STATE"], "Recommend only")
        self.assertIn("Do not disable Cortex access", by_move["Respect boundary"]["DETAIL"])

    def test_alert_threshold_tuning_rows_use_loaded_alerts_and_seed_thresholds(self):
        alerts = pd.DataFrame([{
            "ALERT_KEY": "COST_CORTEX_SPEND_SPIKE",
            "ALERT_TYPE": "Cortex spend spike",
            "SEVERITY": "High",
            "STATUS": "New",
            "CATEGORY": "Cost",
            "COMPANY": "TREXIS",
            "ENVIRONMENT": "PROD",
        }])
        rules = pd.DataFrame([{
            "RULE_ID": "COST_CORTEX_SPEND_SPIKE",
            "ALERT_TYPE": "Cortex spend spike",
            "CATEGORY": "Cost",
            "RUNBOOK": "Review Cortex cost movement.",
        }])

        rows = _alert_threshold_tuning_rows(alerts, rules)
        by_key = {row["THRESHOLD_KEY"]: row for _, row in rows.iterrows()}

        self.assertEqual(by_key["COST_CORTEX_SPEND_SPIKE"]["REVIEW_STATE"], "Tune With Evidence")
        self.assertEqual(by_key["COST_CORTEX_SPEND_SPIKE"]["OPEN_ALERTS"], 1)
        self.assertEqual(by_key["COST_CORTEX_SPEND_SPIKE"]["RULE_ROWS"], 1)
        self.assertEqual(by_key["COST_CORTEX_SPEND_SPIKE"]["SOURCE_OBJECT"], "FACT_CORTEX_DAILY")
        self.assertEqual(by_key["PIPELINE_TASK_FAILURE"]["REVIEW_STATE"], "No Recent Signal")
        self.assertIn("Snowflake alert operations review", by_key["PIPELINE_TASK_FAILURE"]["NEXT_ACTION"])

    def test_alert_company_scope_readiness_rows_flag_unclassified_scope(self):
        alerts = pd.DataFrame([
            {"COMPANY": "TREXIS", "ENVIRONMENT": "PROD", "STATUS": "New"},
            {"COMPANY": "Shared/Unclassified", "ENVIRONMENT": "", "STATUS": "New"},
        ])
        queue = pd.DataFrame([{"STATUS": "New", "ENTITY_NAME": "WH_X"}])

        rows = _alert_company_scope_readiness_rows(alerts, queue)
        by_source = {row["SOURCE"]: row for _, row in rows.iterrows()}

        self.assertEqual(by_source["Alert events"]["STATE"], "Review Scope")
        self.assertEqual(by_source["Action queue"]["STATE"], "Needs Company")
        self.assertIn("Trexis=1", by_source["ALFA/Trexis split"]["COMPANY_VALUES"])
        self.assertIn("company-specific", by_source["ALFA/Trexis split"]["NEXT_ACTION"])

    def test_alert_operations_review_rows_link_deployment_threshold_scope_and_dynamic_review(self):
        alerts = pd.DataFrame([{
            "ALERT_KEY": "COST_WAREHOUSE_CREDIT_SPIKE",
            "SEVERITY": "High",
            "STATUS": "New",
            "COMPANY": "ALFA",
            "ENVIRONMENT": "PROD",
        }])
        queue = pd.DataFrame([{
            "STATUS": "New",
            "COMPANY": "ALFA",
            "ENVIRONMENT": "PROD",
        }])
        native_registry = pd.DataFrame([{
            "STATUS": "READY_TO_DEPLOY",
            "ENABLED_BY_DEFAULT": False,
        }])
        remediation_policy = pd.DataFrame([{
            "POLICY_ID": "POLICY_WAREHOUSE_SPIKE_COST_REVIEW",
            "AUTO_ELIGIBLE": False,
        }])
        dry_runs = pd.DataFrame([{"DRY_RUN_STATUS": "BLOCKED_REVIEW_REQUIRED"}])

        rows = _alert_operations_review_rows(
            alerts=alerts,
            queue=queue,
            native_registry=native_registry,
            remediation_policy=remediation_policy,
            remediation_dry_run=dry_runs,
        )
        by_area = {row["REVIEW_AREA"]: row for _, row in rows.iterrows()}

        self.assertEqual(by_area["Native alert promotion"]["STATE"], "Ready Candidate")
        self.assertIn("OVERWATCH_ALERT_OPERATIONS_REVIEW.sql", by_area["Native alert promotion"]["NEXT_ACTION"])
        self.assertEqual(by_area["Company scope"]["STATE"], "Ready")
        self.assertEqual(by_area["Dry-run automation"]["STATE"], "Ready")
        self.assertEqual(by_area["Dynamic table compatibility"]["STATE"], "Manual Review")
        self.assertIn("OVERWATCH_DYNAMIC_TABLE_SECURE_VIEW_AUDIT.sql", by_area["Dynamic table compatibility"]["NEXT_ACTION"])

    def test_alert_center_brief_first_default_preserves_explicit_data_view(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["alert_center_active_view"] = "Control Health"
            _apply_alert_center_brief_first_default()

            self.assertEqual(st.session_state["alert_center_active_view"], "Alert Settings / Admin")
            self.assertEqual(st.session_state["alert_center_admin_view"], "Delivery & Automation")
            self.assertEqual(st.session_state["_alert_center_brief_first_version"], 3)

            st.session_state["alert_center_active_view"] = "Retired Alert Pane"
            _apply_alert_center_brief_first_default()
            self.assertEqual(st.session_state["alert_center_active_view"], "Active Alerts")

            st.session_state.clear()
            _apply_alert_center_brief_first_default()
            self.assertEqual(st.session_state["alert_center_active_view"], "Active Alerts")

            st.session_state.clear()
            st.session_state["alert_center_active_view"] = "Control Health"
            st.session_state["alert_center_data"] = {"_loaded_sources": []}
            _apply_alert_center_brief_first_default()
            self.assertEqual(st.session_state["alert_center_active_view"], "Alert Settings / Admin")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_section_alert_signal_board_filters_loaded_alert_domains(self):
        alerts = pd.DataFrame([
            {
                "SEVERITY": "High",
                "STATUS": "New",
                "CATEGORY": "Cost Control",
                "ALERT_TYPE": "Cortex spend spike",
                "ENTITY_NAME": "SNOW_DTI_ANALYST",
                "OWNER": "DBA / AI cost route",
                "ROUTE": "Cost & Contract",
                "SUGGESTED_ACTION": "Review Cortex spend and quota settings.",
                "PROOF_QUERY": "SELECT * FROM FACT_CORTEX_DAILY",
                "ALERT_TS": pd.Timestamp("2026-06-17 08:00:00"),
            },
            {
                "SEVERITY": "Critical",
                "STATUS": "New",
                "CATEGORY": "Security",
                "ALERT_TYPE": "Privileged role grant",
                "ENTITY_NAME": "APP_USER",
                "OWNER": "Security Review",
                "ROUTE": "Security Monitoring",
                "SUGGESTED_ACTION": "Validate privileged role grant.",
                "ALERT_TS": pd.Timestamp("2026-06-17 07:00:00"),
            },
            {
                "SEVERITY": "High",
                "STATUS": "New",
                "CATEGORY": "Task / Pipeline",
                "ALERT_TYPE": "Stored procedure failure",
                "ENTITY_NAME": "SP_LOAD_POLICY",
                "OWNER": "DBA / Pipeline Route",
                "ROUTE": "Workload Operations",
                "SUGGESTED_ACTION": "Review procedure child query failures.",
                "ALERT_TS": pd.Timestamp("2026-06-17 06:00:00"),
            },
        ])
        cost_rows = build_section_alert_signal_board(alerts, section="Cost & Contract")
        security_rows = build_section_alert_signal_board(alerts, section="Security Monitoring")
        workload_rows = build_section_alert_signal_board(alerts, section="Workload Operations")
        executive_rows = build_section_alert_signal_board(alerts, section="Executive Landing")

        self.assertEqual(cost_rows.iloc[0]["SECTION_FOCUS"], "Cortex spend")
        self.assertEqual(cost_rows.iloc[0]["ENTITY"], "SNOW_DTI_ANALYST")
        self.assertEqual(cost_rows.iloc[0]["DESTINATION_SECTION"], "Cost & Contract")
        self.assertEqual(cost_rows.iloc[0]["DESTINATION_WORKFLOW"], "Cost by User / Role")
        self.assertEqual(cost_rows.iloc[0]["ALERT_CENTER_VIEW"], "Cost Alerts")
        self.assertIn("quota", cost_rows.iloc[0]["DRILLDOWN_HINT"].lower())
        self.assertEqual(cost_rows.iloc[0]["AUTOMATION_READINESS"], "Recommend only")
        self.assertEqual(security_rows.iloc[0]["CATEGORY"], "Security")
        self.assertEqual(security_rows.iloc[0]["DESTINATION_WORKFLOW"], "Failed Logins")
        self.assertEqual(workload_rows.iloc[0]["CATEGORY"], "Task / Pipeline")
        self.assertEqual(workload_rows.iloc[0]["DESTINATION_WORKFLOW"], "Pipeline & Task Health")
        self.assertEqual(len(executive_rows), 3)

        loaded_rows = build_loaded_section_alert_signal_board(
            {"alert_center_data": {"alerts": alerts, "action_queue": pd.DataFrame()}},
            section="Cost & Contract",
        )
        self.assertEqual(loaded_rows.iloc[0]["SECTION_FOCUS"], "Cortex spend")
        drilldown = build_cost_cortex_alert_drilldown(alerts, limit=4)
        self.assertFalse(drilldown.empty)
        self.assertEqual(drilldown.iloc[0]["FOCUS"], "Cortex spend")
        self.assertIn("Open Cost by User / Role", drilldown.iloc[0]["SAFE_ACTION"])
        self.assertIn("Advanced Cost Tools", drilldown.iloc[0]["SAFE_ACTION"])

    def test_alert_surfaces_are_consolidated_to_alert_center(self):
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        alert_text = (APP_ROOT / "sections" / "alert_center.py").read_text(encoding="utf-8")
        dba_tools_text = (APP_ROOT / "sections" / "dba_tools.py").read_text(encoding="utf-8")
        rec_text = (APP_ROOT / "sections" / "recommendations.py").read_text(encoding="utf-8")

        self.assertIn('"Alert Center"', config_text)
        self.assertIn('"sections.alert_center"', config_text)
        self.assertFalse((APP_ROOT / "sections" / "alert_center_shell.py").exists())
        self.assertIn('ALERT_CENTER_DEFAULT_VIEW = "Active Alerts"', alert_text)
        self.assertIn("consolidated Alert Center", dba_tools_text)
        self.assertNotIn("Alert Configuration", rec_text)
        self.assertNotIn("tab_alerts", rec_text)

    def test_alert_command_center_setup_sql_creates_required_contract_tables(self):
        sql = build_alert_command_center_setup_sql().upper()
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()

        for table in [
            "ALERT_CONFIG",
            "ALERT_EVENTS",
            "ALERT_RUN_HISTORY",
            "ALERT_ACKNOWLEDGEMENTS",
            "ALERT_REMEDIATION_LOG",
            "ALERT_REMEDIATION_POLICY",
            "ALERT_REMEDIATION_DRY_RUN",
            "ALERT_NATIVE_OBJECT_REGISTRY",
            "ALERT_NOTIFICATION_LOG",
            "ALERT_THRESHOLDS",
            "ALERT_OWNER_ROUTING",
        ]:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS", sql)
            self.assertIn(table, sql)
            self.assertIn(table, setup_sql)

        self.assertIn("REMEDIATION_MODE", sql)
        self.assertIn("DEDUP", sql)
        self.assertIn("SUPPRESSION_WINDOW_MINUTES", sql)
        self.assertIn("ACCOUNT_USAGE DELAYED", sql)
        self.assertIn("SECURITY_PRIVILEGE_ESCALATION", sql)
        self.assertIn("PIPELINE_TASK_FAILURE", sql)
        self.assertIn("COST_CORTEX_SPEND_SPIKE", sql)
        self.assertIn("COST_CORTEX_SPEND_SPIKE", setup_sql)
        self.assertIn("OVERWATCH_ALERT_CORTEX_SPEND_SPIKE", setup_sql)
        self.assertIn("POLICY_CORTEX_QUOTA_REVIEW", setup_sql)
        threshold_keys = {row["THRESHOLD_KEY"] for row in build_alert_threshold_seed_rows()}
        self.assertIn("COST_CORTEX_SPEND_SPIKE", threshold_keys)
        self.assertGreaterEqual(len(threshold_keys), 8)

    def test_native_alert_registry_and_remediation_policy_contracts_are_safe_by_default(self):
        native_rows = build_alert_native_object_registry_seed_rows()
        policy_rows = build_alert_remediation_policy_seed_rows()
        native_sql = "\n".join(row["GENERATED_CREATE_SQL"] for row in native_rows).upper()
        native_ddl = build_alert_native_registry_ddl().upper()
        deployment_sql = build_alert_native_deployment_review_sql().upper()
        deployment_rows = build_alert_native_deployment_review_rows(native_rows)
        policy_ddl = build_alert_remediation_policy_ddl().upper()
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()
        drop_sql = (ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql").read_text(encoding="utf-8").upper()
        validation_sql = (ROOT / "snowflake" / "OVERWATCH_MART_VALIDATION.sql").read_text(encoding="utf-8").upper()
        deployment_file = (ROOT / "snowflake" / "OVERWATCH_NATIVE_ALERT_DEPLOYMENT.sql").read_text(encoding="utf-8").upper()

        self.assertGreaterEqual(len(native_rows), 3)
        self.assertTrue(all(row["ENABLED_BY_DEFAULT"] is False for row in native_rows))
        self.assertTrue(any(row["ALERT_KEY"] == "COST_CORTEX_SPEND_SPIKE" for row in native_rows))
        self.assertTrue(any(row["ALERT_KEY"] == "COST_WAREHOUSE_CREDIT_SPIKE" for row in native_rows))
        self.assertTrue(any(row["ALERT_KEY"] == "BEHAVIOR_USER_QUERY_ANOMALY" for row in native_rows))
        self.assertIn("CREATE OR REPLACE ALERT", native_sql)
        self.assertIn("FACT_WAREHOUSE_HOURLY", native_sql)
        self.assertIn("CREDITS_USED", native_sql)
        self.assertNotIn("METERED_CREDITS", native_sql)
        self.assertIn("FACT_QUERY_DETAIL_RECENT", native_sql)
        self.assertIn("FACT_TASK_RUN", native_sql)
        self.assertIn("FACT_GRANT_DAILY", native_sql)
        self.assertIn("COMPANY, ENVIRONMENT", native_sql)
        self.assertIn("ALERT_NATIVE_OBJECT_REGISTRY", native_ddl)
        self.assertIn("ALERT_NATIVE_OBJECT_REGISTRY", setup_sql)
        self.assertIn("COMPANY              VARCHAR(100)", setup_sql)
        self.assertIn("ALTER TABLE IF EXISTS ALERT_EVENTS ADD COLUMN IF NOT EXISTS COMPANY", setup_sql)
        self.assertNotIn("SUM(METERED_CREDITS) > 10", setup_sql)
        self.assertIn("ENTITY_NAME, WAREHOUSE_NAME, CURRENT_VALUE", setup_sql)
        self.assertIn("NATIVE CANDIDATE DETECTED WAREHOUSE CREDITS ABOVE THRESHOLD", setup_sql)
        self.assertIn("GROUP BY COMPANY, WAREHOUSE_NAME HAVING SUM(CREDITS_USED) > 10", setup_sql)
        self.assertIn("DROP TABLE IF EXISTS ALERT_NATIVE_OBJECT_REGISTRY", drop_sql)
        self.assertIn("ALERT_NATIVE_OBJECT_REGISTRY", validation_sql)
        self.assertIn("ALERT_NATIVE_DEPLOYMENT_REVIEW_V", deployment_sql)
        self.assertIn("SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN", deployment_sql)
        self.assertIn("ALERT_NATIVE_DEPLOYMENT_REVIEW_V", setup_sql)
        self.assertIn("SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN", setup_sql)
        self.assertIn("DROP VIEW IF EXISTS ALERT_NATIVE_DEPLOYMENT_REVIEW_V", drop_sql)
        self.assertIn("DROP PROCEDURE IF EXISTS SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN", drop_sql)
        self.assertIn("ALERT_NATIVE_DEPLOYMENT_REVIEW_V", validation_sql)
        self.assertIn("OVERWATCH_NATIVE_ALERT_DEPLOYMENT", deployment_file)
        self.assertTrue(set(deployment_rows["DEPLOYMENT_STATE"]).issubset({
            "CANDIDATE_REVIEW_REQUIRED",
            "READY_FOR_MANUAL_DEPLOY",
            "DEPLOYED_MONITOR",
            "BLOCKED_ENABLED_BY_DEFAULT",
        }))

        self.assertGreaterEqual(len(policy_rows), 6)
        self.assertTrue(all(row["AUTO_ELIGIBLE"] is False for row in policy_rows))
        self.assertTrue(any(row["POLICY_ID"] == "POLICY_WAREHOUSE_SPIKE_COST_REVIEW" for row in policy_rows))
        self.assertTrue(any(row["POLICY_ID"] == "POLICY_USER_QUERY_BEHAVIOR_REVIEW" for row in policy_rows))
        self.assertIn("ALERT_REMEDIATION_POLICY", policy_ddl)
        self.assertIn("ALERT_REMEDIATION_DRY_RUN", policy_ddl)
        self.assertIn("POLICY_CORTEX_QUOTA_REVIEW", setup_sql)
        self.assertIn("POLICY_WAREHOUSE_SPIKE_COST_REVIEW", setup_sql)
        self.assertIn("POLICY_USER_QUERY_BEHAVIOR_REVIEW", setup_sql)
        self.assertIn("BEHAVIOR_USER_QUERY_ANOMALY", setup_sql)
        self.assertIn("DROP TABLE IF EXISTS ALERT_REMEDIATION_POLICY", drop_sql)
        self.assertIn("ALERT_REMEDIATION_DRY_RUN", validation_sql)

    def test_alert_lifecycle_insert_sql_targets_command_center_audit_tables(self):
        ack_sql = build_alert_acknowledgement_insert_sql(
            event_id=123,
            alert_key="SECURITY_PRIVILEGE_ESCALATION:USER1",
            note="Ticket INC123 assigned to Security owner.",
            actor="DBA_USER",
            owner="Security",
            status_after_ack="Acknowledged",
            next_checkpoint_hours=4,
        ).upper()
        remediation_sql = build_alert_remediation_log_insert_sql(
            event_id=123,
            alert_key="SECURITY_PRIVILEGE_ESCALATION:USER1",
            remediation_mode="STATUS_REVIEW",
            action_type="Revoke risky grant",
            action_sql="REVOKE ROLE ACCOUNTADMIN FROM USER USER1;",
            before_state="ACCOUNTADMIN granted",
            execution_status="REQUESTED",
            rollback_guidance="Re-grant only after DBA status review.",
            actor="DBA_USER",
        ).upper()

        self.assertIn("INSERT INTO", ack_sql)
        self.assertIn("ALERT_ACKNOWLEDGEMENTS", ack_sql)
        self.assertIn("TRY_TO_NUMBER('123')", ack_sql)
        self.assertIn("DATEADD('HOUR', 4, CURRENT_TIMESTAMP())", ack_sql)
        self.assertIn("INSERT INTO", remediation_sql)
        self.assertIn("ALERT_REMEDIATION_LOG", remediation_sql)
        self.assertIn("STATUS_REVIEW", remediation_sql)
        self.assertIn("REVOKE ROLE ACCOUNTADMIN", remediation_sql)

    def test_alert_data_quality_config_and_event_materialization_sql_are_deployable(self):
        dq_ddl = build_alert_data_quality_checks_ddl().upper()
        materialize_sql = build_alert_event_materialization_sql(days=7).upper()
        setup_sql = build_alert_command_center_setup_sql().upper()
        repo_setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8").upper()
        dq_rows = build_alert_data_quality_check_seed_rows()

        self.assertIn("CREATE TABLE IF NOT EXISTS", dq_ddl)
        self.assertIn("ALERT_DATA_QUALITY_CHECKS", dq_ddl)
        for column in [
            "DATABASE_NAME",
            "SCHEMA_NAME",
            "TABLE_NAME",
            "COLUMN_NAME",
            "CHECK_TYPE",
            "THRESHOLD_VALUE",
            "SEVERITY",
            "OWNER",
            "NOTIFICATION_CHANNEL",
            "ENABLED",
        ]:
            self.assertIn(column, dq_ddl)
        self.assertIn("ALERT_DATA_QUALITY_CHECKS", setup_sql)
        self.assertIn("ALERT_DATA_QUALITY_CHECKS", repo_setup_sql)
        self.assertGreaterEqual(len(dq_rows), 3)
        self.assertTrue(any(row["CHECK_TYPE"] == "FRESHNESS_SLA_HOURS" for row in dq_rows))

        self.assertIn("MERGE INTO", materialize_sql)
        self.assertIn("ALERT_EVENTS", materialize_sql)
        self.assertIn("OVERWATCH_ALERT_TRIAGE_V", materialize_sql)
        self.assertIn("COMPANY = SRC.COMPANY", materialize_sql)
        self.assertIn("ENVIRONMENT = SRC.ENVIRONMENT", materialize_sql)
        self.assertIn("(ALERT_KEY, COMPANY, ENVIRONMENT", materialize_sql)
        self.assertIn("ALERT_RUN_HISTORY", materialize_sql)
        self.assertIn("DEDUPE_KEY", materialize_sql)
        self.assertIn("SHA2", materialize_sql)
        self.assertIn("ACCOUNT_USAGE-BACKED ALERTS MAY LAG", materialize_sql)

    def test_alert_signal_query_catalog_covers_dba_critical_telemetry(self):
        catalog = build_alert_signal_query_catalog(hours=12)
        text = "\n".join(
            catalog["SQL"].astype(str).tolist()
            + catalog["TELEMETRY"].astype(str).tolist()
        ).upper()
        categories = set(catalog["CATEGORY"])

        self.assertTrue({"Security", "Cost", "Performance", "Task / Pipeline", "Data Quality", "Optimization"}.issubset(categories))
        for source in [
            "SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY",
            "SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS",
            "SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY",
            "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
            "FACT_CORTEX_DAILY",
            "CORTEX_SPEND_AND_QUOTA",
            "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
            "SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY",
            "SNOWFLAKE.ACCOUNT_USAGE.COPY_HISTORY",
            "SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY",
            "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSES",
        ]:
            self.assertIn(source, text)
        self.assertTrue(catalog["FRESHNESS"].astype(str).str.contains("ACCOUNT_USAGE|near-real-time", case=False, regex=True).any())

    def test_alert_command_center_summary_and_morning_brief_prioritize_business_impact(self):
        alerts = pd.DataFrame([
            {
                "ALERT_ID": 1,
                "ALERT_TS": pd.Timestamp("2026-06-13 06:00"),
                "FIRST_SEEN_AT": pd.Timestamp("2026-06-13 05:55"),
                "DETECTED_AT": pd.Timestamp("2026-06-13 06:00"),
                "CATEGORY": "Security",
                "ALERT_TYPE": "Privileged Role Grant",
                "SEVERITY": "Critical",
                "STATUS": "New",
                "ENTITY_NAME": "SVC_LOAD",
                "OWNER": "Security Approver",
                "SUGGESTED_ACTION": "Validate ticket, MFA posture, and approver.",
                "PROOF_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS;",
            },
            {
                "ALERT_ID": 2,
                "ALERT_TS": pd.Timestamp("2026-06-13 02:00"),
                "CATEGORY": "Task / Pipeline",
                "ALERT_TYPE": "Task Failure",
                "SEVERITY": "High",
                "STATUS": "Acknowledged",
                "ENTITY_NAME": "ALFA_EDW_PROD.PUBLIC.T_LOAD",
                "OWNER": "Pipeline Owner",
                "SUGGESTED_ACTION": "Identify failed child task and safe rerun path.",
                "PROOF_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY;",
            },
            {
                "ALERT_ID": 3,
                "ALERT_TS": pd.Timestamp("2026-06-12 02:00"),
                "RESOLVED_AT": pd.Timestamp("2026-06-12 04:00"),
                "CATEGORY": "Cost",
                "ALERT_TYPE": "Credit Spike",
                "SEVERITY": "Medium",
                "STATUS": "Resolved",
                "ENTITY_NAME": "WH_LOAD",
                "OWNER": "DBA / Cost owner",
                "SUGGESTED_ACTION": "Explain metering movement.",
            },
        ])

        summary = build_alert_command_center_summary(alerts, now=pd.Timestamp("2026-06-13 08:00"))
        metrics = {row["METRIC"]: row for _, row in summary["metrics"].iterrows()}
        morning = build_alert_morning_brief_rows(alerts)

        self.assertEqual(metrics["Open critical"]["VALUE"], 1)
        self.assertEqual(metrics["Warning alerts"]["VALUE"], 1)
        self.assertEqual(metrics["Resolved alerts"]["VALUE"], 1)
        self.assertGreater(summary["severity_score"], 100)
        self.assertEqual(summary["category_board"].iloc[0]["CATEGORY"], "Security")
        self.assertEqual(morning.iloc[0]["CATEGORY"], "Security")
        self.assertIn("Possible breach", morning.iloc[0]["WHY_THIS_MATTERS"])
        self.assertIn("TASK_HISTORY", "\n".join(morning["PROOF_QUERY"].astype(str)))

    def test_alert_incident_action_board_prioritizes_sla_owner_and_evidence(self):
        alerts = pd.DataFrame([
            {
                "ALERT_ID": "A1",
                "FIRST_SEEN_AT": pd.Timestamp("2026-06-13 00:00"),
                "CATEGORY": "Task / Pipeline",
                "ALERT_TYPE": "Root task failed",
                "SEVERITY": "High",
                "STATUS": "Acknowledged",
                "ENTITY_NAME": "ALFA_EDW_PROD.PUBLIC.T_LOAD_POLICY",
                "OWNER": "Pipeline Owner",
                "SUGGESTED_ACTION": "Fix failed child task before retrying graph.",
                "PROOF_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY;",
                "SLA_HOURS": 4,
                "REMEDIATION_MODE": "STATUS_REVIEW",
            },
            {
                "ALERT_ID": "A2",
                "FIRST_SEEN_AT": pd.Timestamp("2026-06-13 07:45"),
                "CATEGORY": "Optimization",
                "ALERT_TYPE": "Unused warehouse",
                "SEVERITY": "Medium",
                "STATUS": "New",
                "ENTITY_NAME": "WH_DEV_IDLE",
                "OWNER": "DBA / Cost owner",
                "SUGGESTED_ACTION": "Review warehouse ownership and auto-suspend.",
            },
        ])
        queue = pd.DataFrame([
            {
                "CATEGORY": "Task / Pipeline",
                "ENTITY_NAME": "ALFA_EDW_PROD.PUBLIC.T_LOAD_POLICY",
                "STATUS": "In Progress",
                "TICKET_ID": "INC123",
                "DUE_STATE": "Breached",
                "EVIDENCE_GAP": "Need retry proof after fix.",
                "APPROVAL_GROUP": "DBA CAB",
            }
        ])

        board = build_alert_incident_action_board(alerts, queue, now=pd.Timestamp("2026-06-13 08:00"))
        owners = build_alert_owner_workload_board(alerts, queue, now=pd.Timestamp("2026-06-13 08:00"))

        self.assertEqual(board.iloc[0]["INCIDENT_KEY"], "A1")
        self.assertEqual(board.iloc[0]["SLA_STATE"], "Breached")
        self.assertEqual(board.iloc[0]["TICKET_ID"], "INC123")
        self.assertEqual(board.iloc[0]["APPROVAL_GROUP"], "DBA CAB")
        self.assertIn("before state", board.iloc[0]["FIRST_RESPONSE"])
        self.assertIn("ACCOUNT_USAGE", board.iloc[0]["SOURCE_FRESHNESS"])
        self.assertEqual(owners.iloc[0]["OWNER"], "Pipeline Owner")
        self.assertEqual(owners.iloc[0]["SLA_BREACHED"], 1)
        self.assertEqual(owners.iloc[0]["TICKETS_ATTACHED"], 1)

        queue_only = build_alert_incident_action_board(pd.DataFrame(), queue, now=pd.Timestamp("2026-06-13 08:00"))
        self.assertFalse(queue_only.empty)
        self.assertEqual(queue_only.iloc[0]["TICKET_ID"], "INC123")
        self.assertEqual(queue_only.iloc[0]["QUEUE_STATE"], "In Progress")

    def test_alert_remediation_contract_blocks_dangerous_auto_actions(self):
        contract = build_alert_remediation_contract({
            "CATEGORY": "Security",
            "ALERT_TYPE": "Privilege Escalation",
            "ENTITY_NAME": "SVC_LOAD",
            "REMEDIATION_MODE": "AUTO",
            "REMEDIATION_SQL": "REVOKE ROLE ACCOUNTADMIN FROM USER SVC_LOAD;",
            "PROOF_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.GRANTS_TO_USERS;",
        })
        safe_contract = build_alert_remediation_contract({
            "CATEGORY": "Optimization",
            "ENTITY_NAME": "WH_LOAD",
            "REMEDIATION_MODE": "RECOMMEND",
            "REMEDIATION_SQL": "-- Recommend lowering auto-suspend after DBA review.",
        })

        self.assertEqual(contract["REMEDIATION_MODE"], "STATUS_REVIEW")
        self.assertEqual(contract["DANGEROUS_ACTION"], "Yes")
        self.assertIn("ALERT_REMEDIATION_LOG", contract["AUDIT_LOG_REQUIRED"])
        self.assertIn("ROLLBACK", contract["ROLLBACK_GUIDANCE"].upper())
        self.assertEqual(safe_contract["DANGEROUS_ACTION"], "No")
        self.assertEqual(safe_contract["REMEDIATION_MODE"], "RECOMMEND")

    def test_alert_monitoring_runbook_lists_privileges_and_integrations(self):
        privileges = build_alert_required_privileges()
        integrations = build_alert_optional_integrations()
        runbook = build_alert_command_center_runbook_markdown()

        self.assertIn("Imported privileges", privileges.iloc[0]["PRIVILEGE_ASSUMPTION"])
        self.assertIn("Notification integration usage", "\n".join(privileges["PRIVILEGE_ASSUMPTION"]))
        self.assertIn("Snowflake ALERT objects", "\n".join(integrations["INTEGRATION"]))
        self.assertIn("Event tables", "\n".join(integrations["INTEGRATION"]))
        self.assertIn("OVERWATCH Alert Monitoring Runbook", runbook)
        self.assertIn("ACCOUNT_USAGE views are authoritative", runbook)
        self.assertIn("AUTO is allowed only", runbook)


if __name__ == "__main__":
    unittest.main()
