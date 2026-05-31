from pathlib import Path
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

from config import DEFAULTS  # noqa: E402
from sections.account_health import (  # noqa: E402
    _account_health_actionable_checklist,
    _account_health_access_hygiene_sql,
    _annotate_account_health_access_hygiene,
    _annotate_account_health_checklist_readiness,
    _account_health_checklist_action_payload,
    _account_health_checklist_history_insert_sql,
    _account_health_checklist_history_sql,
    _account_health_closure_analytics_sql,
    _account_health_control_board,
    _account_health_operability_fact_sql,
    _build_account_health_dba_checklist,
    _enrich_account_health_checklist_owners,
    build_account_health_checklist_history_ddl,
    build_account_health_checklist_history_migration_sql,
    build_account_health_operability_fact_ddl,
    build_account_health_operability_fact_migration_sql,
    _live_query_status_sql,
)
from sections.adoption_analytics import (  # noqa: E402
    _load_adoption_live,
    _metric as adoption_metric,
)
from sections.cost_center import (  # noqa: E402
    _bill_driver_summary,
    _build_bill_waterfall,
    _build_finance_movement_summary,
    _chargeback_cost_verification_sql,
    _queue_cost_outliers,
    _warehouse_cost_control_action,
    _service_cost_category,
    _warehouse_cost_verification_sql,
)
from sections.cost_contract import (  # noqa: E402
    _build_cost_closure_analytics,
    _build_savings_verification_task_summary,
)
from sections.dba_control_room import (  # noqa: E402
    _build_report as _build_dba_control_report,
    _build_command_queue,
    _command_queue_closure_readiness,
    _command_queue_summary,
    _command_queue_route_readiness,
    _dba_section_operability_board,
    _build_release_compare_report,
    _compare_release_windows,
    _control_room_snapshot_to_data,
    _load_control_room,
    _severity_rows as _dba_control_severity_rows,
)
from sections.cortex_monitor import (  # noqa: E402
    _build_cortex_control_markdown,
    _build_cortex_ai_functions_daily_sql,
    _cortex_action_for,
    _cortex_cost_rating,
    _cortex_cost_score,
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
    _change_control_evidence_history_sql,
    _change_control_evidence_insert_sql,
    _change_drift_rating,
    _change_drift_score,
    _change_control_operability_fact_sql,
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
    _root_cause_action_for,
    _root_cause_rating,
    _root_cause_score,
)
from sections.recommendations import (  # noqa: E402
    _idle_warehouse_verification_sql,
    _query_failure_verification_sql,
    _remote_spill_verification_sql,
    _task_failure_verification_sql,
)
from sections.service_health import _value as service_value  # noqa: E402
from sections.security_posture import (  # noqa: E402
    _security_action_queue_closure_sql,
    _security_access_review_readiness_for_row,
    _annotate_security_privileged_grant_readiness,
    _build_security_access_review,
    _build_security_brief_markdown,
    _build_security_mart_brief_sql,
    _build_security_summary_sql,
    _security_control_board,
    _security_privileged_grant_review_sql,
    _security_operability_fact_sql,
    _security_access_review_history_sql,
    _security_access_review_insert_sql,
    _security_action_for,
    _security_exception_verification_sql,
    _security_rating,
    _security_score,
    build_security_access_review_ddl,
    build_security_access_review_migration_sql,
    build_security_operability_fact_ddl,
    build_security_operability_fact_migration_sql,
)
from sections.stored_proc_tracker import (  # noqa: E402
    _build_procedure_reliability_action,
    _build_procedure_sla_frames,
    _build_procedure_ops_frames,
    _procedure_from_task_definition,
    _procedure_key,
)
from sections.task_management import (  # noqa: E402
    _admin_sql_for_graph,
    _admin_sql_for_task,
    _annotate_task_graph_impact,
    _build_failure_console_frames,
    _build_failure_runbook_markdown,
    _build_task_critical_path_snapshot,
    _build_task_reliability_action,
    _build_task_graph_dot,
    _build_task_ops_frames,
    _build_task_ops_markdown,
    _build_task_recovery_sla_frame,
    build_admin_preflight_sql,
    _collect_graph_tasks,
    _extract_object_candidates,
    _failure_diagnosis,
    _parse_task_predecessors,
    _procedure_from_definition,
    _task_action_for,
    _task_ops_rating,
    _task_ops_score,
)
from sections.usage_overview import _first_number as usage_first_number  # noqa: E402
from sections.warehouse_health import (  # noqa: E402
    _annotate_warehouse_admin_readiness,
    _annotate_warehouse_owner_inventory,
    _warehouse_action_queue_closure_sql,
    _warehouse_setting_audit_readiness_for_row,
    _warehouse_setting_control_board,
    _warehouse_setting_execution_audit_sql,
    _build_warehouse_capacity_markdown,
    _queue_efficiency_findings,
    _queue_capacity_findings,
    _warehouse_capacity_action_for,
    _warehouse_capacity_rating,
    _warehouse_capacity_score,
    _warehouse_capacity_verification_sql,
    _warehouse_owner_inventory_sql,
    _warehouse_operability_fact_sql,
    _warehouse_setting_review_history_sql,
    _warehouse_setting_review_insert_sql,
    build_warehouse_operability_fact_ddl,
    build_warehouse_operability_fact_migration_sql,
    build_warehouse_setting_review_ddl,
    build_warehouse_setting_review_migration_sql,
)
from utils.cost import (  # noqa: E402
    build_cost_reconciliation_sql,
    build_idle_warehouse_sql,
    build_metered_credit_cte,
    credits_to_dollars,
    query_attribution_supported,
)
from utils.company_filter import (  # noqa: E402
    environment_label_for_database,
    get_environment_case_expr,
    get_environment_filter_clause,
    get_environment_filter_or_no_database_clause,
    get_global_filter_clause,
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
    build_alert_delivery_log_ddl,
    build_alert_delivery_log_insert_sql,
    build_alert_delivery_mark_sql,
    build_alert_email_delivery_procedure_sql,
    build_alert_email_body,
    build_alert_email_subject,
    build_alert_escalation_ack_sql,
    build_alert_rule_audit_ddl,
    build_alert_rule_audit_insert_sql,
    build_alert_rule_update_sql,
    build_alert_status_update_sql,
    build_alert_task_sql,
    build_alert_triage_view_sql,
    build_dashboard_issue_rows,
    normalize_alert_rule_frame,
)
from utils.owner_directory import (  # noqa: E402
    build_owner_directory_ddl,
    default_owner_directory,
    enrich_owner_dataframe,
    resolve_owner_context,
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
    build_mart_control_room_failed_logins_sql,
    build_mart_control_room_cost_drivers_sql,
    build_mart_control_room_summary_sql,
    build_mart_control_room_task_failures_sql,
    build_mart_procedure_calls_sql,
    build_mart_procedure_inventory_sql,
    build_mart_procedure_sla_sql,
    build_mart_pipeline_load_failures_sql,
    build_mart_query_bottleneck_sql,
    build_mart_query_degradation_sql,
    build_mart_recommendation_failed_tasks_sql,
    build_mart_recommendation_idle_sql,
    build_mart_recommendation_query_errors_sql,
    build_mart_recommendation_spill_sql,
    build_mart_task_critical_path_sql,
)


def _python_sources():
    return [
        path
        for path in APP_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


class FormulaRegressionTests(unittest.TestCase):
    def test_streamlit_and_mart_credit_defaults_stay_aligned(self):
        setup_sql = (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")

        self.assertEqual(DEFAULTS["credit_price"], 3.68)
        self.assertIn("('CREDIT_PRICE_USD', '3.68'", setup_sql)
        self.assertIn("credit_price := COALESCE(credit_price, 3.68)", setup_sql)
        self.assertEqual(credits_to_dollars(10, DEFAULTS["credit_price"]), 36.8)

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
            self.assertTrue(query_attribution_supported(Session([
                "QUERY_ID",
                "START_TIME",
                "CREDITS_ATTRIBUTED_COMPUTE",
                "CREDITS_USED_QUERY_ACCELERATION",
            ])))

            st.session_state.clear()
            self.assertFalse(query_attribution_supported(Session([
                "QUERY_ID",
                "START_TIME",
                "CREDITS_ATTRIBUTED_COMPUTE",
            ])))
        finally:
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
            detail_source="Live fallback: ACCOUNT_USAGE",
        )
        by_check = {row["CHECK"]: row for _, row in checklist.iterrows()}

        self.assertEqual(by_check["Overall health escalation"]["OWNER"], "DBA Lead")
        self.assertEqual(by_check["Query failure review"]["SEVERITY"], "High")
        self.assertEqual(by_check["Task and procedure reliability"]["ROUTE"], "Workload Operations")
        self.assertIn("query_id", by_check["Change and drift review"]["PROOF_REQUIRED"])
        self.assertIn("Snapshot timestamp", by_check["Refresh source confidence"]["PROOF_REQUIRED"])

        routed = _annotate_account_health_checklist_readiness(checklist, environment="PROD")
        by_check = {row["CHECK"]: row for _, row in routed.iterrows()}
        self.assertEqual(by_check["Query failure review"]["ENVIRONMENT_SCOPE"], "PROD")
        self.assertEqual(by_check["Query failure review"]["DATABASE_CONTEXT"], "Yes")
        self.assertEqual(by_check["Query failure review"]["SCOPE_CONFIDENCE"], "Database Context")
        self.assertEqual(by_check["Query failure review"]["QUEUE_READINESS"], "Ready to Queue")
        self.assertEqual(by_check["Cost spike review"]["DATABASE_CONTEXT"], "Allocated / Estimated")
        self.assertEqual(by_check["Cost spike review"]["SCOPE_CONFIDENCE"], "Allocated Estimate")
        self.assertIn("allocated/estimated", by_check["Cost spike review"]["SCOPE_EVIDENCE"])

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
        self.assertEqual(action["Owner Approval Status"], "Requested")
        self.assertEqual(action["Approver"], "Application Owner / DBA On-Call")
        self.assertEqual(action["Oncall Primary"], "DBA On-Call")
        self.assertIn("OWNER_DIRECTORY", action["Owner Source"])
        self.assertEqual(action["Recovery Audit State"], "Checklist Verification Pending")
        self.assertEqual(action["Recovery SLA Target Hours"], 24)
        self.assertEqual(action["Environment"], "DEV_ALL")
        self.assertIn("QUERY_HISTORY", action["Verification Query"])
        self.assertIn("Queue readiness: Ready to Queue", action["Owner Approval Note"])
        self.assertIn("Scope: Database Context", action["Owner Approval Note"])
        self.assertIn("Scope evidence", action["Recovery Evidence"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])
        self.assertNotIn("ALTER", action["Generated SQL Fix"].upper())

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
        self.assertEqual(row["ESCALATION_TARGET"], "Warehouse Owner / DBA On-Call")
        self.assertIn("Checklist owner map", row["OWNER_SOURCE"])
        self.assertIn("OWNER_DIRECTORY", row["OWNER_SOURCE"])
        self.assertEqual(row["ONCALL_PRIMARY"], "DBA On-Call")
        self.assertIn("WAREHOUSE", row["OWNER_EVIDENCE"])

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
        by_check = {row["CHECK_NAME"]: row for _, row in board.iterrows()}

        self.assertEqual(by_check["Query failure review"]["CONTROL_STATE"], "Closure Overdue")
        self.assertEqual(by_check["Cost spike review"]["CONTROL_STATE"], "Closure Evidence Blocked")
        self.assertEqual(by_check["Refresh source confidence"]["CONTROL_STATE"], "Queue Required")
        self.assertEqual(by_check["Account access hygiene"]["CONTROL_STATE"], "High-Risk Access Review")
        self.assertEqual(by_check["Account access hygiene"]["DATABASE_CONTEXT"], "No")
        self.assertIn("user hygiene", by_check["Account access hygiene"]["NEXT_CONTROL_ACTION"])

    def test_account_health_closure_analytics_sql_scores_action_queue_evidence(self):
        sql = _account_health_closure_analytics_sql(45, "ALFA", "PROD").upper()

        self.assertIn("OVERWATCH_ACTION_QUEUE", sql)
        self.assertIn("ACCOUNT HEALTH - DAILY DBA CHECKLIST", sql)
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
        self.assertEqual(row["QUEUE_READINESS"], "Ready to Queue")
        self.assertEqual(row["APPROVAL_REQUIRED"], "Yes")
        self.assertEqual(row["RECOVERY_SLA_TARGET_HOURS"], 24)
        self.assertIn("OWNER_DIRECTORY", row["OWNER_SOURCE"])
        self.assertIn("Security", row["APPROVAL_GROUP"])

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

        with patch("sections.dba_control_room.run_query", side_effect=fail_mart), patch(
            "sections.dba_control_room.load_action_queue",
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
        self.assertTrue(any(row.get("Mode") == "Mart unavailable" for _, row in data["_source_modes"].iterrows()))
        self.assertFalse(any("SNOWFLAKE.ACCOUNT_USAGE" in sql for sql in called_sql))

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
                "OWNER": "FinOps Owner",
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
        self.assertEqual(command_queue.iloc[0]["COMMAND_ROUTE_READINESS"], "Route Ready")
        self.assertEqual(command_queue.iloc[0]["ONCALL_PRIMARY"], "DBA On-Call")
        self.assertEqual(command_queue.iloc[0]["COMMAND_AUDIT_READINESS"], "Audit Gaps")
        self.assertEqual(summary["open"], 1)
        self.assertEqual(summary["overdue"], 1)
        self.assertEqual(summary["owner_gaps"], 1)
        self.assertEqual(summary["route_ready"], 1)
        self.assertGreater(summary["control_gaps"], 0)
        self.assertEqual(summary["audit_ready"], 0)

    def test_dba_control_room_command_queue_exposes_execution_gates(self):
        queue = pd.DataFrame([
            {
                "ACTION_ID": "C1",
                "CATEGORY": "Cost Control",
                "SEVERITY": "High",
                "ENTITY_NAME": "WH_ALFA_BI",
                "OWNER": "BI_PLATFORM_OWNER",
                "STATUS": "In Progress",
                "DUE_DATE": "2026-06-02",
                "VERIFICATION_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                "TICKET_ID": "CHG-101",
                "APPROVER": "FinOps Lead",
                "BASELINE_VALUE": 100,
                "CURRENT_VALUE": 180,
                "OWNER_APPROVAL_STATUS": "Requested",
                "RECOVERY_SLA_STATE": "Savings Verification Pending",
            },
            {
                "ACTION_ID": "C2",
                "CATEGORY": "Cost Control",
                "SEVERITY": "High",
                "ENTITY_NAME": "WH_ALFA_LOAD",
                "OWNER": "LOAD_PLATFORM_OWNER",
                "STATUS": "Acknowledged",
                "DUE_DATE": "2026-06-02",
                "VERIFICATION_QUERY": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY",
                "TICKET_ID": "CHG-102",
                "APPROVER": "FinOps Lead",
                "BASELINE_VALUE": 200,
                "CURRENT_VALUE": 260,
                "OWNER_APPROVAL_STATUS": "Approved",
                "RECOVERY_SLA_STATE": "Savings Verification Pending",
            },
        ])

        command_queue = _build_command_queue(queue, today="2026-05-31")
        summary = _command_queue_summary(command_queue)
        by_route = {row["ROUTE"]: row for _, row in _command_queue_route_readiness(command_queue).iterrows()}
        by_id = {row["ACTION_ID"]: row for _, row in command_queue.iterrows()}

        self.assertEqual(by_id["C1"]["COMMAND_EXECUTION_GATE"], "Blocked - Owner Approval")
        self.assertEqual(by_id["C1"]["COMMAND_EVIDENCE_REQUIRED"], "Owner approval")
        self.assertEqual(by_id["C1"]["COMMAND_ROUTE_READINESS"], "Route Ready")
        self.assertEqual(by_id["C2"]["COMMAND_EXECUTION_GATE"], "Ready - High Risk")
        self.assertEqual(by_id["C2"]["COMMAND_AUDIT_READINESS"], "Audit Ready")
        self.assertEqual(summary["approval_blocks"], 1)
        self.assertEqual(summary["execution_ready"], 1)
        self.assertEqual(summary["audit_ready"], 1)
        self.assertEqual(by_route["Cost & Contract"]["APPROVAL_BLOCKS"], 1)
        self.assertEqual(by_route["Cost & Contract"]["EXECUTION_READY"], 1)

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

        self.assertEqual(by_route["Security Posture"]["CLOSURE_READINESS"], "Overdue closure")
        self.assertEqual(by_route["Security Posture"]["OVERDUE_OPEN"], 1)
        self.assertEqual(by_route["Security Posture"]["OWNER_GAP_ROWS"], 1)
        self.assertEqual(by_route["Security Posture"]["TICKET_GAP_ROWS"], 1)
        self.assertEqual(by_route["Account Health"]["CLOSURE_READINESS"], "Fixed without verification")
        self.assertEqual(by_route["Account Health"]["FIXED_WITHOUT_VERIFICATION"], 1)
        self.assertEqual(by_route["Account Health"]["RECOVERY_RISK_ROWS"], 1)
        self.assertEqual(by_route["Warehouse Health"]["CLOSURE_READINESS"], "Verified closure")
        self.assertEqual(by_route["Warehouse Health"]["VERIFIED_CLOSURES"], 1)
        self.assertIn("Attach verification", by_route["Account Health"]["NEXT_CONTROL_ACTION"])

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
                "APPROVER": "FinOps Lead",
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

        self.assertEqual(by_section["Warehouse Health"]["OPERABILITY_STATE"], "Escalate Now")
        self.assertEqual(by_section["Warehouse Health"]["OVERDUE"], 1)
        self.assertGreaterEqual(by_section["Warehouse Health"]["CLOSURE_BLOCKERS"], 1)
        self.assertIn("Escalate overdue", by_section["Warehouse Health"]["NEXT_CONTROL_ACTION"])
        self.assertEqual(by_section["Cost & Contract"]["OPERABILITY_STATE"], "Work Open Actions")
        self.assertEqual(by_section["Cost & Contract"]["EXECUTION_READY"], 1)
        self.assertEqual(by_section["Security Posture"]["OPERABILITY_STATE"], "Build Toward 95")
        self.assertIn("Connect IAM", by_section["Security Posture"]["NEXT_CONTROL_ACTION"])

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

        security_text = (APP_ROOT / "sections" / "security_posture.py").read_text(encoding="utf-8")
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
            self.assertIn("UPPER(Q.DATABASE_NAME) = 'ALFA_EDW_PROD'", prod_clause)

            dev_clause = get_environment_filter_clause("q.database_name", "DEV_ALL").upper()
            for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
                self.assertIn(db_name, dev_clause)
            self.assertNotIn("ALFA_EDW_PROD", dev_clause)

            optional_clause = get_environment_filter_or_no_database_clause("q.database_name", "PROD").upper()
            self.assertIn("Q.DATABASE_NAME IS NULL", optional_clause)
            self.assertIn("UPPER(Q.DATABASE_NAME) = 'ALFA_EDW_PROD'", optional_clause)

            st.session_state["active_company"] = "Trexis"
            self.assertEqual(get_environment_filter_clause("q.database_name", "PROD"), "")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

        case_expr = get_environment_case_expr("q.database_name").upper()
        self.assertIn("THEN 'PROD'", case_expr)
        self.assertIn("THEN 'ALFA_EDW_DEV'", case_expr)
        self.assertIn("NO DATABASE CONTEXT", case_expr)
        self.assertEqual(environment_label_for_database("ALFA_EDW_PROD"), "PROD")
        self.assertEqual(environment_label_for_database("ALFA_EDW_SAN"), "ALFA_EDW_SAN")
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
            self.assertIn("UPPER(Q.DATABASE_NAME) = 'ALFA_EDW_PROD'", clause)
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
                self.assertIn(f"ENVIRONMENT = '{db_name}'", db_sql)
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
        self.assertIn("'ALFA_EDW_PROD',         'EQUALS',    'PROD'", setup_sql)

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

            alter_stmt = f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS ENVIRONMENT"
            self.assertIn(alter_stmt, setup_sql, table_name)

        proc_start = setup_sql.index("CREATE TRANSIENT TABLE IF NOT EXISTS FACT_PROCEDURE_RUN")
        proc_end = setup_sql.index(");", proc_start)
        self.assertIn("DATABASE_NAME", setup_sql[proc_start:proc_end])

        expected_loads = [
            "OVERWATCH_DATABASE_ENVIRONMENT(DATABASE_NAME) AS ENVIRONMENT",
            "OVERWATCH_DATABASE_ENVIRONMENT(TASK_DATABASE) AS ENVIRONMENT",
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

    def test_mart_procedure_runs_filter_by_environment(self):
        import streamlit as st

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["active_company"] = "ALFA"
            st.session_state["global_environment"] = "PROD"

            calls_sql = build_mart_procedure_calls_sql(7, "ALFA").upper()
            self.assertIn("FACT_PROCEDURE_RUN", calls_sql)
            self.assertIn("ENVIRONMENT = 'PROD'", calls_sql)

            sla_sql = build_mart_procedure_sla_sql(7, "ALFA").upper()
            self.assertIn("FACT_PROCEDURE_RUN", sla_sql)
            self.assertIn("DATABASE_NAME", sla_sql)
            self.assertIn("ENVIRONMENT = 'PROD'", sla_sql)
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_usage_overview_storage_sums_are_null_safe(self):
        text = (APP_ROOT / "sections" / "usage_overview.py").read_text(encoding="utf-8")
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
        self.assertEqual(_service_cost_category("CLOUD_SERVICES"), "Cloud services / metadata")

    def test_finance_movement_summary_separates_confidence_levels(self):
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
            budget=250.0,
        )
        categories = set(summary["Category"])
        self.assertIn("Warehouse metering", categories)
        self.assertIn("Query-attributed workload", categories)
        self.assertIn("Unallocated / idle / overhead", categories)
        self.assertIn("Data loading / ingestion", categories)
        self.assertIn("AI / Cortex", categories)
        self.assertIn("Budget variance", categories)
        confidence = dict(zip(summary["Category"], summary["Confidence"]))
        self.assertEqual(confidence["Warehouse metering"], "Exact")
        self.assertEqual(confidence["Query-attributed workload"], "Allocated / Estimated")
        self.assertEqual(confidence["Data loading / ingestion"], "Account-wide")

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
        self.assertIn("OVERWATCH Security Brief - ALFA", md)
        self.assertIn("Security score: 91", md)
        self.assertIn("MFA Gap", md)
        self.assertIn("Company scope uses user/database naming", md)

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
        self.assertEqual(by_type["Failed Login"]["OWNER"], "IAM / Security Owner")
        self.assertEqual(by_type["MFA Gap"]["APPROVER"], "IAM / Security Owner")
        self.assertEqual(by_type["Failed Login"]["ONCALL_PRIMARY"], "DBA On-Call")
        self.assertIn("OWNER_DIRECTORY", by_type["Recent Grant"]["OWNER_SOURCE"])
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
        self.assertIn("IAM/security approval", by_type["Failed Login"]["REVIEW_BLOCKERS"])
        self.assertEqual(by_type["Object Grant"]["CONTROL_READINESS"], by_type["Object Grant"]["REVIEW_READINESS"])

        ready = _security_access_review_readiness_for_row({
            "SEVERITY": "High",
            "OWNER": "Security Owner",
            "OWNER_SOURCE": "OWNER_DIRECTORY exact",
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

            _, live_exceptions = _build_security_summary_sql(None, 14, "ALFA")
            _, mart_exceptions = _build_security_mart_brief_sql(None, 14, "ALFA")
            combined = "\n".join([live_exceptions, mart_exceptions]).upper()

            self.assertIn("GRANTS_TO_ROLES", combined)
            self.assertIn("'OBJECT GRANT'", combined)
            self.assertIn("GOR.TABLE_CATALOG AS DATABASE_NAME", combined)
            self.assertIn("ALFA_EDW_DEV", combined)
            self.assertNotIn("UPPER(LH.DATABASE_NAME)", combined)
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
        self.assertIn("UPPER(GOR.TABLE_CATALOG) = 'ALFA_EDW_PROD'", sql_upper)
        self.assertNotIn("GTU.TABLE_CATALOG", sql_upper)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_security_privileged_grant_readiness_adds_owner_route_and_scope(self):
        grants = pd.DataFrame([
            {
                "FINDING_TYPE": "Privileged Role Grant",
                "SEVERITY": "Critical",
                "ENTITY": "JDOE",
                "ROLE_NAME": "ACCOUNTADMIN",
                "OBJECT_NAME": "",
                "DATABASE_NAME": "",
                "DATABASE_CONTEXT": False,
                "ENVIRONMENT": "No Database Context",
                "GRANTED_BY": "SECURITYADMIN",
                "CREATED_ON": "2026-05-01",
                "PROOF_REQUIRED": "ticket and owner approval",
            },
            {
                "FINDING_TYPE": "Privileged Object Grant",
                "SEVERITY": "High",
                "ENTITY": "ETL_RUNNER",
                "ROLE_NAME": "",
                "OBJECT_NAME": "ALFA_EDW_DEV.PUBLIC.POLICY_FACT",
                "DATABASE_NAME": "ALFA_EDW_DEV",
                "DATABASE_CONTEXT": True,
                "ENVIRONMENT": "ALFA_EDW_DEV",
                "GRANTED_BY": "SYSADMIN",
                "CREATED_ON": "2026-05-02",
                "PROOF_REQUIRED": "object owner approval",
            },
        ])

        readiness = _annotate_security_privileged_grant_readiness(grants)
        by_entity = {row["ENTITY"]: row for _, row in readiness.iterrows()}

        self.assertEqual(by_entity["JDOE"]["GRANT_REVIEW_STATE"], "Tier 0 role grant")
        self.assertEqual(by_entity["JDOE"]["GRANT_REVIEW_READINESS"], "Owner Approval Required")
        self.assertEqual(by_entity["JDOE"]["SCOPE_CONFIDENCE"], "Account/User Context")
        self.assertEqual(by_entity["JDOE"]["OWNER_ROUTE_READY"], "Yes")
        self.assertEqual(by_entity["ETL_RUNNER"]["GRANT_REVIEW_STATE"], "Privileged object grant")
        self.assertEqual(by_entity["ETL_RUNNER"]["SCOPE_CONFIDENCE"], "Database Context")
        self.assertIn("OWNER_DIRECTORY", by_entity["ETL_RUNNER"]["OWNER_SOURCE"])

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
        self.assertIn("IAM / SECURITY OWNER", insert_sql)
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
        self.assertIn("SECURITY POSTURE - SECURITY BRIEF", sql)
        self.assertIn("COMPANY = 'ALFA'", sql)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, sql)
        self.assertIn("FIXED_WITHOUT_VERIFICATION", sql)
        self.assertIn("OWNER_APPROVAL_GAP_ROWS", sql)
        self.assertIn("CLOSURE_READINESS", sql)
        self.assertIn("SECURITY OWNER AND TICKET", sql)
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
        self.assertEqual(_change_action_for("Destructive DDL")[0], "Object")
        self.assertEqual(_change_action_for("Policy or Tag Change")[0], "Policy/Tag")
        self.assertEqual(_change_action_for("Grant or Role Change")[0], "Grant/Role")
        self.assertEqual(_change_action_for("Manual Drift")[0], "Drift")

    def test_change_drift_queue_payload_is_auditable_and_readonly(self):
        row = {
            "FINDING_TYPE": "Destructive DDL",
            "SEVERITY": "High",
            "ENTITY": "ALFA_EDW_DEV.PUBLIC.POLICY_FACT",
            "USER_NAME": "DEPLOY_USER",
            "QUERY_ID": "01abc",
            "QUERY_TAG": "CHG-12345 terraform release",
        }
        action = _change_action_payload(row, company="ALFA", environment="ALFA_EDW_DEV")

        self.assertEqual(action["Category"], "Change Control")
        self.assertEqual(action["Owner"], "DBA Change Owner")
        self.assertEqual(action["Ticket ID"], "CHG-12345")
        self.assertEqual(action["Oncall Primary"], "DBA On-Call")
        self.assertIn("OWNER_DIRECTORY", action["Owner Source"])
        self.assertEqual(action["Recovery Audit State"], "Query ID captured")
        self.assertEqual(action["Owner Approval Status"], "Requested")
        self.assertIn("Data Owner", action["Approver"])
        self.assertIn("QUERY_HISTORY", action["Verification Query"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])
        self.assertIn("OBJECT_DEPENDENCIES", action["Recovery Evidence"])
        self.assertIn("Codified / deployment-tagged", action["Recovery Evidence"])
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
        self.assertEqual(row["CHANGE_CONTROL_STATE"], "Validate Approval")
        self.assertEqual(row["CHANGE_TICKET_STATE"], "Missing ticket evidence")
        self.assertEqual(row["OWNER"], "Security Owner")
        self.assertEqual(row["ONCALL_PRIMARY"], "DBA On-Call")
        self.assertIn("OWNER_DIRECTORY", row["OWNER_SOURCE"])
        self.assertEqual(row["APPROVAL_ROUTE_READY"], "No")
        self.assertEqual(row["CHANGE_EVIDENCE_READINESS"], "Route Blocked")
        self.assertIn("owner directory evidence", row["EVIDENCE_BLOCKERS"])
        self.assertEqual(row["REVIEW_SLA_HOURS"], 72)
        self.assertIn("Attach the approved change ticket", row["NEXT_CONTROL_ACTION"])
        self.assertIn("Review source-control", row["IAC_RECONCILIATION_STATE"])
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
                "QUERY_TAG": "CHG-12345 terraform release",
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
        self.assertIn("Route Blocked", set(summary["READINESS"]))
        self.assertIn("Complete named owner", " ".join(summary["NEXT_CONTROL_ACTION"].astype(str)))

    def test_change_control_evidence_snapshot_sql_is_scoped_and_auditable(self):
        readiness = _enrich_change_control_evidence(pd.DataFrame([
            {
                "FINDING_TYPE": "Policy or Tag Change",
                "SEVERITY": "High",
                "ENTITY": "ALFA_EDW_PROD.SECURE.CUSTOMER",
                "USER_NAME": "DEPLOY_USER",
                "ROLE_NAME": "SECURITYADMIN",
                "QUERY_ID": "01policy",
                "QUERY_TAG": "RFC98765 flyway release",
                "LAST_SEEN": "2026-05-31 09:00:00",
                "CHANGE_CONTROL_STATE": "Approval Required",
                "CONTROL_GAP": "Needs approver, change ticket, and blast-radius note",
                "APPROVER": "Security Owner / Data Governance",
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
        self.assertIn("CODIFIED / DEPLOYMENT-TAGGED", insert_sql)
        self.assertIn("REVIEW READY", insert_sql)
        self.assertIn("SNAPSHOT_TS >= DATEADD('DAY', -30", trend_sql)
        self.assertIn("COMPANY = 'ALFA'", trend_sql)
        self.assertIn("ENVIRONMENT = 'PROD'", trend_sql)
        self.assertIn("MISSING_TICKET_ROWS", trend_sql)

    def test_change_control_operability_fact_is_fast_and_environment_scoped(self):
        ddl = build_change_control_operability_fact_ddl().upper()
        migration_sql = "\n".join(build_change_control_operability_fact_migration_sql()).upper()
        fact_sql = _change_control_operability_fact_sql(30, "ALFA", "DEV_ALL").upper()

        self.assertIn("CREATE TRANSIENT TABLE IF NOT EXISTS", ddl)
        self.assertIn("FACT_CHANGE_CONTROL_OPERABILITY_DAILY", ddl)
        self.assertIn("CONTROL_SOURCE", ddl)
        self.assertIn("CONTROL_RANK", ddl)
        self.assertIn("NEXT_CONTROL_ACTION", ddl)
        self.assertIn("ADD COLUMN IF NOT EXISTS CONTROL_SOURCE", migration_sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS CONTROL_RANK", migration_sql)
        self.assertIn("FACT_CHANGE_CONTROL_OPERABILITY_DAILY", fact_sql)
        self.assertIn("SNAPSHOT_DATE >= DATEADD('DAY', -30", fact_sql)
        self.assertIn("COMPANY = 'ALFA'", fact_sql)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, fact_sql)
        self.assertNotIn("ACCOUNT_USAGE.QUERY_HISTORY", fact_sql)
        self.assertNotIn("OVERWATCH_ACTION_QUEUE", fact_sql)

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
        self.assertIn("SOURCE-CONTROL OR ROLLBACK PROOF", sql)
        self.assertEqual(verification_query_safety_issues(sql), [])

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

            live_summary, live_exceptions = _build_change_drift_sql(None, 14, "ALFA")
            mart_summary, mart_exceptions = _build_mart_change_drift_sql(14, "ALFA")
            combined = "\n".join([live_summary, live_exceptions, mart_summary, mart_exceptions]).upper()

            self.assertIn("DATABASE_NAME IS NULL", combined)
            self.assertIn("UPPER(DATABASE_NAME) = 'ALFA_EDW_PROD'", combined)
            self.assertIn("AS DATABASE_CONTEXT", combined)
            self.assertIn("AS SCOPE_CONFIDENCE", combined)
            self.assertIn("ACCOUNT_SCOPE_CHANGES", combined)
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
                "FINDING_TYPE": ["Destructive DDL"],
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
        self.assertIn("OVERWATCH Change & Drift Brief - ALFA", md)
        self.assertIn("Control score: 81", md)
        self.assertIn("Destructive DDL", md)
        self.assertIn("DDL/DCL detection is text-pattern based", md)

    def test_query_root_cause_score_weights_failures_and_queue(self):
        stable = _root_cause_score(
            failed_queries=0,
            queued_queries=0,
            spill_queries=0,
            full_scan_queries=1,
            slow_queries=1,
            total_queries=1000,
        )
        risky = _root_cause_score(
            failed_queries=20,
            queued_queries=30,
            spill_queries=20,
            full_scan_queries=120,
            slow_queries=150,
            total_queries=500,
        )
        self.assertGreaterEqual(stable, 95)
        self.assertLess(risky, 70)
        self.assertEqual(_root_cause_rating(stable), "Stable")
        self.assertEqual(_root_cause_rating(risky), "Incident Risk")

    def test_query_root_cause_actions_are_specific(self):
        self.assertEqual(_root_cause_action_for("Failed Query")[0], "Query")
        self.assertEqual(_root_cause_action_for("Warehouse Queue")[0], "Warehouse")
        self.assertEqual(_root_cause_action_for("Remote Spill")[0], "Query/Warehouse")
        self.assertEqual(_root_cause_action_for("Full Scan")[0], "Object/Query")

    def test_query_root_cause_brief_markdown_contains_evidence_limits(self):
        summary_row = {
            "TOTAL_QUERIES": 100,
            "FAILED_QUERIES": 2,
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
        self.assertIn("Root-cause score: 82", md)
        self.assertIn("Warehouse Queue", md)
        self.assertIn("QUERY_HISTORY can lag", md)

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
        self.assertEqual(_warehouse_capacity_rating(healthy), "Healthy")
        self.assertEqual(_warehouse_capacity_rating(risky), "Capacity Risk")

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
        self.assertEqual(annotated.iloc[0]["OWNER"], "BI Platform Owner")
        self.assertEqual(annotated.iloc[0]["ONCALL_PRIMARY"], "DBA On-Call")
        self.assertIn("OWNER_DIRECTORY", annotated.iloc[0]["OWNER_SOURCE"])
        self.assertIn("DBA Lead", annotated.iloc[0]["APPROVER"])
        self.assertIn("MAX_CLUSTER_COUNT", annotated.iloc[0]["SETTING_CHANGE_CANDIDATE"])
        self.assertIn("Warehouse Settings Manager", annotated.iloc[0]["SAFE_CHANGE_PATH"])
        self.assertEqual(annotated.iloc[0]["SAVINGS_VERIFICATION_REQUIRED"], "No")

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

    def test_warehouse_owner_inventory_sql_uses_tags_and_environment_scope(self):
        sql = _warehouse_owner_inventory_sql(45, "ALFA", "DEV_ALL")
        sql_upper = sql.upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", sql_upper)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES", sql_upper)
        self.assertIn("OWNER_TAG", sql_upper)
        self.assertIn("COST_CENTER_TAG", sql_upper)
        self.assertIn("ENVIRONMENT_TAG", sql_upper)
        for db_name in ["ALFA_EDW_DEV", "ALFA_EDW_SAN", "ALFA_EDW_PHX", "ALFA_EDW_SEA", "ALFA_EDW_SIT"]:
            self.assertIn(db_name, sql_upper)
        self.assertNotIn("ALFA_EDW_PROD", sql_upper)
        self.assertEqual(verification_query_safety_issues(sql), [])

    def test_warehouse_owner_inventory_marks_tag_and_directory_readiness(self):
        inventory = pd.DataFrame([
            {
                "WAREHOUSE_NAME": "BI_COMPUTE_WH",
                "WAREHOUSE_SIZE": "Medium",
                "QUERY_COUNT": 500,
                "DATABASE_COUNT": 2,
                "OWNER_TAG": "BI Product Owner",
                "COST_CENTER_TAG": "BI",
                "ENVIRONMENT_TAG": "PROD",
            },
            {
                "WAREHOUSE_NAME": "LOAD_TASK_WH",
                "WAREHOUSE_SIZE": "Large",
                "QUERY_COUNT": 300,
                "DATABASE_COUNT": 1,
                "OWNER_TAG": "",
                "COST_CENTER_TAG": "",
                "ENVIRONMENT_TAG": "",
            },
        ])

        annotated = _annotate_warehouse_owner_inventory(inventory)
        by_wh = {row["WAREHOUSE_NAME"]: row for _, row in annotated.iterrows()}

        self.assertEqual(by_wh["BI_COMPUTE_WH"]["GOVERNANCE_READINESS"], "Tagged Owner Ready")
        self.assertEqual(by_wh["BI_COMPUTE_WH"]["OWNER"], "BI Product Owner")
        self.assertEqual(by_wh["BI_COMPUTE_WH"]["OWNER_SOURCE"], "WAREHOUSE_TAG")
        self.assertEqual(by_wh["BI_COMPUTE_WH"]["OWNER_ROUTE_READY"], "Yes")
        self.assertEqual(by_wh["LOAD_TASK_WH"]["GOVERNANCE_READINESS"], "Directory Route Only")
        self.assertEqual(by_wh["LOAD_TASK_WH"]["OWNER"], "Data Engineering Owner")
        self.assertEqual(by_wh["LOAD_TASK_WH"]["OWNER_TAG_STATE"], "Missing")
        self.assertIn("Add warehouse owner", by_wh["LOAD_TASK_WH"]["NEXT_OWNER_ACTION"])

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
        self.assertIn("Capacity score: 80", md)
        self.assertIn("Credit Spike", md)
        self.assertIn("Settings Change Readiness", md)
        self.assertIn("Warehouse Settings Manager", md)
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
        self.assertIn("SAVINGS_VERIFICATION_REQUIRED", ddl)
        self.assertIn("INSERT INTO", insert_sql)
        self.assertIn("'BI_COMPUTE_WH'", insert_sql)
        self.assertIn("'DBA / FINOPS OWNER'", insert_sql)
        self.assertIn("'PROD'", insert_sql)
        self.assertIn("WAREHOUSE_METERING_HISTORY", insert_sql)
        self.assertIn("SNAPSHOT_TS >= DATEADD('DAY', -30", trend_sql)
        self.assertIn("COMPANY = 'ALFA'", trend_sql)
        self.assertIn("ENVIRONMENT = 'PROD'", trend_sql)
        self.assertIn("SAVINGS_VERIFICATION_ROWS", trend_sql)

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
                "SAVINGS_VERIFICATION_REQUIRED": "Yes",
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
                "SAVINGS_VERIFICATION_REQUIRED": "Yes",
                "EXECUTION_STATUS": "Success",
                "EXECUTED_SQL_HASH": "abc123",
                "POST_CHANGE_VERIFICATION_STATUS": "Verified",
                "POST_CHANGE_VERIFICATION_RESULT": "Queue/spill/credit metrics improved over the post-change window.",
                "VERIFIED_MONTHLY_SAVINGS": 250.0,
            }
        )

        self.assertEqual(blocked["AUDIT_READINESS"], "Pre-Change Blocked")
        self.assertIn("owner approval", blocked["AUDIT_BLOCKERS"])
        self.assertIn("change ticket", blocked["AUDIT_BLOCKERS"])
        self.assertIn("rollback SQL", blocked["AUDIT_BLOCKERS"])
        self.assertEqual(verified["AUDIT_READINESS"], "Verified Change Audit")
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
        by_wh = {row["WAREHOUSE_NAME"]: row for _, row in board.iterrows()}

        self.assertEqual(by_wh["BI_COMPUTE_WH"]["CONTROL_STATE"], "Closure Overdue")
        self.assertEqual(by_wh["LOAD_TASK_WH"]["CONTROL_STATE"], "Execution Failed")
        self.assertEqual(by_wh["DEV_WH"]["CONTROL_STATE"], "Pre-Change Blocked")
        self.assertIn("rollback", by_wh["DEV_WH"]["AUDIT_BLOCKERS"].lower())

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
        self.assertEqual(action["Owner"], "DBA / FinOps Owner")
        self.assertEqual(action["Owner Approval Status"], "Requested")
        self.assertIn("FinOps", action["Approver"])
        self.assertEqual(action["Verification Status"], "Pending")
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])
        self.assertIn("post-change verification", action["Recovery Evidence"])
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
        self.assertEqual(action["Owner"], "BI Platform Owner")
        self.assertEqual(action["Owner Approval Status"], "Requested")
        self.assertEqual(action["Recovery SLA Target Hours"], 24)
        self.assertIn("OWNER_DIRECTORY", action["Owner Source"])
        self.assertIn("Warehouse Settings Manager", action["Action"])
        self.assertIn("QUERY_HISTORY", action["Verification Query"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])
        self.assertNotIn("ALTER WAREHOUSE", action["Generated SQL Fix"].upper())

    def test_cortex_cost_score_tracks_budget_and_user_spikes(self):
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
        self.assertIn("daily credit limit", _cortex_action_for("Budget Breach")[0])
        self.assertIn("approved project demand", _cortex_action_for("Cost Per Request Spike")[0])

    def test_cortex_control_markdown_contains_budget_context(self):
        summary_row = {
            "PROJECTED_30D_COST": 1250.0,
            "ACTIVE_USERS": 12,
            "TOTAL_REQUESTS": 400,
            "TOTAL_CREDITS": 44.5,
        }
        exceptions = pd.DataFrame(
            {
                "SEVERITY": ["Critical"],
                "SIGNAL": ["Budget Breach"],
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
        self.assertIn("Monthly budget: $1,000.00", md)
        self.assertIn("Budget Breach", md)

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
        report = _build_dba_control_report(data, exceptions, "ALFA", 3.0, 24)
        self.assertIn("Task SLA / Cost Regression Candidates", report)
        self.assertIn("Stored Procedure Release Regression Candidates", report)
        self.assertIn("SP_LOAD_POLICY", report)

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
        self.assertEqual(_task_ops_rating(stable), "Operational")
        self.assertLess(risky, 65)
        self.assertEqual(_task_ops_rating(risky), "Incident Risk")

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
        self.assertEqual(by_task["CHILD_TASK"]["OWNER_APPROVAL_STATE"], "Root-cause owner approval required")
        self.assertEqual(by_task["CHILD_TASK"]["ONCALL_PRIMARY"], "DBA On-Call")
        self.assertEqual(by_task["CHILD_TASK"]["APPROVAL_GROUP"], "Pipeline Owner")
        self.assertIn("OWNER_DIRECTORY", by_task["CHILD_TASK"]["OWNER_SOURCE"])
        self.assertIn("P", by_task["CHILD_TASK"]["INCIDENT_PRIORITY"])

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

    def test_task_ops_markdown_contains_informatica_context(self):
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
        self.assertIn("Informatica Monitor replacement", md)
        self.assertIn("Failed Task Run", md)
        self.assertIn("Cost drift/release-regression candidates", md)
        self.assertIn("Admin actions require", md)

    def test_task_actions_are_signal_specific(self):
        self.assertIn("retry the root task", _task_action_for("Failed Task Run")[0])
        self.assertIn("resume only after owner approval", _task_action_for("Suspended Task")[0])
        self.assertIn("historical average", _task_action_for("Long Running / SLA Risk")[0])

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
        self.assertIn("Retry SQL after fix", md)
        self.assertIn("P1 graph incidents", md)
        self.assertIn("Evidence Limits", md)

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
        unused = joined[joined["PROC_KEY"] == "SP_UNUSED"].iloc[0]
        self.assertEqual(unused["ORCHESTRATION_STATUS"], "No recent execution evidence")
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
        self.assertGreater(latest.iloc[0]["RUNTIME_CHANGE_PCT"], 0)

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
        dynamic_text = (APP_ROOT / "sections" / "dba_tools.py").read_text(encoding="utf-8")
        dynamic_block = dynamic_text[
            dynamic_text.index('refresh_object = "SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY"'):
            dynamic_text.index('if selected_tool == "Replication"')
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
            loader_block.index("RETURN RUN_QUERY_OR_RAISE(FALLBACK_SQL)"),
            loader_block.index("RETURN RUN_QUERY_OR_RAISE(_LIVE_QUERY_STATUS_SQL"),
        )

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

        self.assertEqual(action["Owner"], "BI_PLATFORM_OWNER")
        self.assertEqual(action["Category"], "Cost Control")
        self.assertEqual(action["Environment"], "")
        self.assertEqual(action["Approver"], "BI_PLATFORM_OWNER / FinOps Lead")
        self.assertEqual(action["Verification Status"], "Pending")
        self.assertEqual(action["Baseline Value"], 250)
        self.assertEqual(action["Current Value"], 500)
        self.assertEqual(action["Measured Delta"], 250)
        self.assertEqual(action["Owner Approval Status"], "Requested")
        self.assertEqual(action["Recovery SLA State"], "Savings Verification Pending")
        self.assertEqual(action["Recovery SLA Target Hours"], 168.0)
        self.assertIn("next complete period", action["Owner Approval Note"])
        self.assertIn("Exact warehouse metering", action["Action"])
        self.assertIn("WAREHOUSE_METERING_HISTORY", action["Proof Query"])
        self.assertIn("post-fix verification", action["Proof Query"].lower())
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
        self.assertEqual(action["Owner"], "DBA / FinOps")
        self.assertEqual(action["Environment"], "No Database Context")
        self.assertEqual(action["Approver"], "FinOps Lead / Cost Owner")
        self.assertEqual(action["Verification Status"], "Pending")
        self.assertEqual(action["Owner Approval Status"], "Requested")
        self.assertEqual(action["Recovery SLA State"], "Chargeback Evidence Pending")
        self.assertEqual(action["Recovery SLA Target Hours"], 168.0)
        self.assertIn("owner/tag evidence approval", action["Owner Approval Note"])
        self.assertIn("not cleanly chargeback-ready", action["Action"])
        self.assertIn("Chargeback readiness: No", action["Generated SQL Fix"])
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
                "OWNER": "DBA / FinOps",
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
        self.assertEqual(by_id["COST_VERIFIED"]["CLOSURE_STATE"], "Verified savings")
        self.assertEqual(by_id["COST_FIXED_GAP"]["CLOSURE_STATE"], "Fixed without verified savings")
        self.assertEqual(by_id["COST_OPEN"]["CLOSURE_STATE"], "Approval pending")
        self.assertEqual(by_id["CHARGEBACK_OPEN"]["CLOSURE_STATE"], "Chargeback evidence pending")

    def test_cost_contract_verification_health_surfaces_task_and_evidence_issues(self):
        health = pd.DataFrame([
            {
                "CONTROL_NAME": "Cost & Contract Savings Verification",
                "TASK_NAME": "OVERWATCH_COST_SAVINGS_VERIFY",
                "TASK_HEALTH_STATE": "Healthy",
                "LAST_TASK_STATE": "SUCCEEDED",
                "FAILED_RUNS_7D": 0,
                "LAST_VERIFICATION_RUN_AT": "2026-05-31 07:20:00",
                "LEDGER_RUN_ROWS_7D": 12,
                "CANDIDATES_LAST_RUN": 4,
                "VERIFIED_LAST_RUN": 1,
                "EVIDENCE_REQUIRED_LAST_RUN": 3,
                "NEXT_ACTION": "Review evidence-required cost actions.",
            }
        ])

        summary, detail = _build_savings_verification_task_summary(health)

        self.assertTrue(summary["loaded"])
        self.assertEqual(summary["health_state"], "Healthy")
        self.assertEqual(summary["issue_severity"], "Medium")
        self.assertEqual(summary["issue_count"], 3)
        self.assertEqual(summary["ledger_rows_7d"], 12)
        self.assertEqual(summary["verified_last_run"], 1)
        self.assertEqual(summary["evidence_required_last_run"], 3)
        self.assertEqual(detail.iloc[0]["ISSUE_SEVERITY"], "Medium")
        self.assertIn("Review evidence-required", detail.iloc[0]["ISSUE_DETAIL"])

    def test_cost_contract_verification_health_prioritizes_task_failures(self):
        health = pd.DataFrame([
            {
                "TASK_HEALTH_STATE": "Task Failed",
                "LAST_TASK_STATE": "FAILED",
                "FAILED_RUNS_7D": 2,
                "LEDGER_RUN_ROWS_7D": 0,
                "EVIDENCE_REQUIRED_LAST_RUN": 0,
                "NEXT_ACTION": "Inspect TASK_HISTORY error.",
            }
        ])

        summary, detail = _build_savings_verification_task_summary(health)

        self.assertEqual(summary["issue_severity"], "Critical")
        self.assertEqual(summary["issue_count"], 3)
        self.assertEqual(summary["failed_runs_7d"], 2)
        self.assertEqual(detail.iloc[0]["ISSUE_COUNT"], 3)
        self.assertIn("TASK_HISTORY", summary["next_action"])

    def test_recommendation_actions_have_runnable_verification_sql(self):
        queries = [
            _idle_warehouse_verification_sql("WH_ALFA_BI"),
            _remote_spill_verification_sql("WH_ALFA_BI"),
            _task_failure_verification_sql("LOAD_POLICY"),
            _query_failure_verification_sql("WH_ALFA_BI"),
        ]

        for sql in queries:
            self.assertEqual(verification_query_safety_issues(sql), [])

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
                "OWNER_APPROVAL_STATE": "Root-cause owner approval required",
                "VERIFY_AFTER_FIX": "Latest task run succeeds within recovery SLA.",
                "DOWNSTREAM_TASK_COUNT": 2,
                "GRAPH_ROLE": "Root",
            }),
            "ALFA",
            "Task Management - Failure Console",
        )

        self.assertEqual(action["Owner"], "TASK_OWNER_ROLE")
        self.assertEqual(action["Category"], "Task & Procedure Reliability")
        self.assertEqual(action["Approver"], "Pipeline Owner")
        self.assertEqual(action["Oncall Primary"], "DBA On-Call")
        self.assertIn("OWNER_DIRECTORY", action["Owner Source"])
        self.assertEqual(action["Recovery Audit State"], "Audit Required")
        self.assertIn("Environment", action)
        self.assertIn("P2 - Production Risk", action["Finding"])
        self.assertIn("Recovery readiness", action["Action"])
        self.assertEqual(action["Verification Status"], "Pending")
        self.assertIn("TASK_HISTORY", action["Verification Query"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])
        self.assertIn("Do not execute until root cause is fixed", action["Generated SQL Fix"])
        self.assertIn("downstream tasks: 2", action["Generated SQL Fix"])
        self.assertIn("TASK_HISTORY", action["Proof Query"])
        self.assertIn("QUERY_HISTORY", action["Proof Query"])
        self.assertIn("Verify", action["Action"])
        self.assertEqual(action["Owner Approval Status"], "Requested")
        self.assertIn("Root-cause owner approval", action["Owner Approval Note"])
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
                "ORCHESTRATION_STATUS": "Manual CALL only",
                "OWNER_REVIEW": "Required",
                "RECOMMENDED_ACTION": "Review child-query scan volume.",
            }),
            "ALFA",
            "Stored Procedures - SLA & Cost Watch",
        )

        self.assertEqual(action["Owner"], "PROC_OWNER_ROLE")
        self.assertEqual(action["Entity Type"], "Stored Procedure")
        self.assertEqual(action["Approver"], "Procedure Owner")
        self.assertEqual(action["Owner Approval Status"], "Requested")
        self.assertEqual(action["Recovery SLA State"], "Procedure Cost Review Required")
        self.assertEqual(action["Recovery SLA Target Hours"], 24.0)
        self.assertEqual(action["Recovery Audit State"], "Audit Required")
        self.assertIn("OWNER_DIRECTORY", action["Owner Source"])
        self.assertEqual(action["Oncall Primary"], "DBA On-Call")
        self.assertIn("Environment", action)
        self.assertEqual(action["Verification Status"], "Pending")
        self.assertIn("QUERY_HISTORY", action["Verification Query"])
        self.assertEqual(verification_query_safety_issues(action["Verification Query"]), [])
        self.assertNotIn("ROOT_QUERY_ID", action["Verification Query"].upper())
        self.assertIn("orchestration=Manual CALL only", action["Finding"])
        self.assertIn("Owner review is required", action["Action"])
        self.assertIn("Procedure Cost Regression", action["Finding"])
        self.assertIn("QUERY_HISTORY", action["Proof Query"])
        self.assertIn("next procedure run", action["Proof Query"])
        self.assertIn("Verify", action["Action"])

    def test_cost_center_chargeback_exposes_environment_and_database(self):
        cost_text = (APP_ROOT / "sections" / "cost_center.py").read_text(encoding="utf-8").upper()
        chargeback_block = cost_text[
            cost_text.index('ELIF COST_VIEW == "CHARGEBACK"'):
            cost_text.index('ELIF COST_VIEW == "CONTRACT UTILIZATION"')
        ]
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
        self.assertIn("OWNER_PROOF", chargeback_block)
        self.assertIn("COST_OWNER", chargeback_block)
        self.assertIn("OWNER_EVIDENCE", chargeback_block)

    def test_owner_directory_matches_wildcards_and_preserves_named_owner(self):
        directory = default_owner_directory()
        task_context = resolve_owner_context(
            {
                "ENTITY_NAME": "DBA_MAINT_DB.OVERWATCH.OVERWATCH_COST_SAVINGS_VERIFY",
                "OWNER": "DBA / FinOps",
                "CATEGORY": "Cost Control",
            },
            directory=directory,
            entity_type="Task",
            alert_type="Cost Savings Verification Failure",
        )
        proc_context = resolve_owner_context(
            {"PROCEDURE_NAME": "ALFA_EDW_PROD.PUBLIC.SP_LOAD_POLICY", "OWNER": "PROC_OWNER_ROLE"},
            directory=directory,
            entity_type="Procedure",
            category="Task & Procedure Reliability",
        )
        enriched = enrich_owner_dataframe(pd.DataFrame([{
            "ENTITY_NAME": "WH_ALFA_LOAD",
            "ENTITY_TYPE": "Warehouse",
            "OWNER": "DBA",
        }]), directory=directory)
        ddl = build_owner_directory_ddl().upper()

        self.assertEqual(task_context["APPROVAL_GROUP"], "FinOps Lead")
        self.assertEqual(task_context["ONCALL_PRIMARY"], "DBA On-Call")
        self.assertIn("COST_VERIFIER_TASK", task_context["OWNER_SOURCE"])
        self.assertEqual(proc_context["OWNER"], "PROC_OWNER_ROLE")
        self.assertEqual(proc_context["APPROVAL_GROUP"], "Procedure Owner")
        self.assertEqual(enriched.iloc[0]["APPROVAL_GROUP"], "Platform DBA Lead")
        self.assertIn("CHANGE_CONTROL_DEFAULT", set(directory["OWNER_KEY"]))
        self.assertIn("ACCOUNT_HEALTH_DEFAULT", set(directory["OWNER_KEY"]))
        self.assertIn("CREATE TABLE IF NOT EXISTS", ddl)
        self.assertIn("OVERWATCH_OWNER_DIRECTORY", ddl)
        self.assertIn("OVERWATCH_OWNER_DIRECTORY_ACTIVE_V", ddl)

    def test_alert_task_is_email_first_and_dba_focused(self):
        sql = build_alert_task_sql(email_target="jdees@alfains.com").upper()

        self.assertIn("OVERWATCH_ANOMALY_CHECK", sql)
        self.assertIn("JDEES@ALFAINS.COM", sql)
        self.assertIn("EMAIL_TARGET", sql)
        self.assertIn("EMAIL_SUBJECT", sql)
        self.assertIn("EMAIL_BODY", sql)
        self.assertIn("EMAIL_READY", sql)
        self.assertIn("TASK FAILURE", sql)
        self.assertIn("STORED PROCEDURE", sql)
        self.assertIn("COST SAVINGS VERIFICATION FAILURE", sql)
        self.assertIn("COST_SAVINGS_VERIFIER_FAILURE", sql)
        self.assertIn("OVERWATCH_COST_SAVINGS_VERIFY", sql)
        self.assertIn("GRANT/REVOKE ACTIVITY", sql)
        self.assertIn("WAREHOUSE SETTING CHANGE", sql)
        self.assertIn("OVERWATCH_ALERT_RULES", sql)
        self.assertIn("OVERWATCH_ALERT_RULE_AUDIT", sql)
        self.assertIn("OVERWATCH_ALERT_TRIAGE_V", sql)
        self.assertIn("OVERWATCH_ALERT_DELIVERY_LOG", sql)
        self.assertIn("OVERWATCH_OWNER_DIRECTORY", sql)
        self.assertIn("OVERWATCH_OWNER_DIRECTORY_ACTIVE_V", sql)
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
        sql = build_alert_email_delivery_procedure_sql(email_target="jdees@alfains.com").upper()

        self.assertIn("SP_OVERWATCH_SEND_ALERT_DIGEST", sql)
        self.assertIn("P_DRY_RUN BOOLEAN DEFAULT TRUE", sql)
        self.assertIn("SYSTEM$SEND_EMAIL", sql)
        self.assertIn("OVERWATCH_EMAIL_INT", sql)
        self.assertIn("OVERWATCH_ALERT_DELIVERY_LOG", sql)
        self.assertIn("EMAIL_DRY_RUN", sql)
        self.assertIn("LAST_DELIVERY_AT", sql)
        self.assertIn("JDEES@ALFAINS.COM", sql)

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
            "EMAIL_TARGET": "jdees@alfains.com",
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
            "Action": "Explain bill movement.",
            "Route": "Cost & Contract",
            "Workflow": "Explain bill / attribution / contract",
        }])

        subject = build_alert_email_subject(alert.iloc[0], company="ALFA")
        body = build_alert_email_body(alert.iloc[0], company="ALFA")
        issues = build_dashboard_issue_rows(exceptions=exceptions, alerts=alert, queue=queue)

        self.assertIn("OVERWATCH Critical", subject)
        self.assertIn("jdees@alfains.com", alert["EMAIL_TARGET"].iloc[0])
        self.assertIn("Environment: PROD", body)
        self.assertEqual(len(issues), 3)
        self.assertEqual(issues.iloc[0]["SEVERITY"], "Critical")
        self.assertEqual(set(issues["ISSUE_SOURCE"]), {"Alert History", "Action Queue", "Control Room Signal"})
        self.assertTrue((issues["EMAIL_TARGET"] == "jdees@alfains.com").all())

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

    def test_alert_history_routes_task_and_procedure_alerts_with_recovery_governance(self):
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
                "OWNER": "DBA / FinOps",
            },
            {
                "ALERT_ID": 33,
                "ALERT_TS": "2026-05-31 10:20:00",
                "COMPANY": "ALFA",
                "ENVIRONMENT": "No Database Context",
                "CATEGORY": "Cost Control",
                "ALERT_TYPE": "Cost Savings Verification Failure",
                "SEVERITY": "High",
                "STATUS": "New",
                "ENTITY_NAME": "OVERWATCH_DB.OVERWATCH.OVERWATCH_COST_SAVINGS_VERIFY",
                "MESSAGE": "2 failed savings verification task run(s) in the last 24 hours.",
                "SUGGESTED_ACTION": "Open Cost & Contract verifier health.",
                "PROOF_QUERY": "SELECT DATABASE_NAME, SCHEMA_NAME, NAME, STATE FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY WHERE UPPER(NAME) = 'OVERWATCH_COST_SAVINGS_VERIFY'",
                "OWNER": "DBA / FinOps",
                "ESCALATION_TARGET": "FinOps Lead",
                "SLA_TARGET_HOURS": 8,
                "ALERT_AGE_HOURS": 9,
                "SLA_STATE": "Overdue",
            },
        ])

        actions = alert_history_to_actions(alerts, company="ALFA")
        by_entity = {action["Entity"]: action for action in actions}
        task = by_entity["ALFA_EDW_PROD.PUBLIC.T_LOAD_POLICY"]
        proc = by_entity["ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY"]
        cost = by_entity["WH_ALFA_LOAD"]
        verifier = by_entity["OVERWATCH_DB.OVERWATCH.OVERWATCH_COST_SAVINGS_VERIFY"]

        self.assertEqual(task["Category"], "Task & Procedure Reliability")
        self.assertEqual(task["Entity Type"], "Task")
        self.assertEqual(task["Owner Approval Status"], "Requested")
        self.assertEqual(task["Approver"], "Pipeline Owner")
        self.assertEqual(task["Oncall Primary"], "DBA On-Call")
        self.assertIn("OWNER_DIRECTORY", task["Owner Source"])
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
        self.assertEqual(proc["Owner Approval Status"], "Requested")
        self.assertEqual(proc["Approver"], "Procedure Owner")
        self.assertEqual(proc["Oncall Primary"], "DBA On-Call")
        self.assertEqual(proc["Recovery SLA State"], "Open Failure")
        self.assertEqual(proc["Baseline Value"], 30.0)
        self.assertEqual(proc["Current Value"], 90.0)
        self.assertIn("QUERY_HISTORY", proc["Verification Query"])
        self.assertIn("QUERY_TYPE = 'CALL'", proc["Verification Query"])
        self.assertEqual(verification_query_safety_issues(proc["Verification Query"]), [])

        self.assertEqual(cost["Category"], "Cost Control")
        self.assertNotIn("Owner Approval Status", cost)
        self.assertEqual(verification_query_safety_issues(cost["Verification Query"]), [])

        self.assertEqual(verifier["Category"], "Cost Control")
        self.assertEqual(verifier["Entity Type"], "Cost Verification Task")
        self.assertEqual(verifier["Owner Approval Status"], "Requested")
        self.assertEqual(verifier["Approver"], "FinOps Lead")
        self.assertEqual(verifier["Oncall Primary"], "DBA On-Call")
        self.assertIn("COST_VERIFIER_TASK", verifier["Owner Source"])
        self.assertEqual(verifier["Recovery Audit State"], "Audit Required")
        self.assertEqual(verifier["Recovery SLA State"], "Recovery SLA Breach")
        self.assertEqual(verifier["Recovery SLA Target Hours"], 8.0)
        self.assertEqual(verifier["Recovery SLA Hours"], 9.0)
        self.assertEqual(verifier["Baseline Value"], 0.0)
        self.assertEqual(verifier["Current Value"], 2.0)
        self.assertIn("TASK_HISTORY", verifier["Verification Query"])
        self.assertIn("OVERWATCH_COST_SAVINGS_VERIFY", verifier["Verification Query"])
        self.assertNotIn("ALTER TASK", verifier["Generated SQL Fix"].upper())
        self.assertIn("clean run ledger", verifier["Action"])
        self.assertEqual(verification_query_safety_issues(verifier["Verification Query"]), [])

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

    def test_alert_delivery_audit_and_escalation_ack_sql(self):
        ddl = build_alert_delivery_log_ddl().upper()
        insert_sql = build_alert_delivery_log_insert_sql(
            alert_ids=[101, "102"],
            company="ALFA",
            environment="PROD",
            delivery_target="jdees@alfains.com",
            email_subject="OVERWATCH Alert Digest",
            email_body="Digest body",
            actor="DBA_USER",
            notes="Sent digest through Outlook and opened INC123.",
        ).upper()
        mark_sql = build_alert_delivery_mark_sql(
            alert_ids=[101, 102],
            delivery_target="jdees@alfains.com",
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
                delivery_target="jdees@alfains.com",
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
                "OWNER": "DBA / FinOps",
                "MESSAGE": "Credits returned to baseline.",
                "DELIVERY_STATUS": "EMAIL_READY",
            },
        ])

        summary = build_alert_digest_summary(df)
        subject = build_alert_digest_subject(df, company="ALFA", environment="PROD")
        body = build_alert_digest_body(df, company="ALFA", environment="PROD", recipient="jdees@alfains.com")
        candidates = alert_escalation_candidates(df, limit=5)

        self.assertEqual(summary["open"], 2)
        self.assertEqual(summary["critical_high"], 2)
        self.assertGreaterEqual(summary["overdue"], 1)
        self.assertGreaterEqual(summary["needs_owner"], 1)
        self.assertIn("2 open", subject)
        self.assertIn("jdees@alfains.com", body)
        self.assertIn("Escalate first", body)
        self.assertEqual(candidates.iloc[0]["ALERT_ID"], 20)
        self.assertIn("SLA_STATE", candidates.columns)

    def test_alert_surfaces_are_consolidated_to_alert_center(self):
        config_text = (APP_ROOT / "config.py").read_text(encoding="utf-8")
        dba_tools_text = (APP_ROOT / "sections" / "dba_tools.py").read_text(encoding="utf-8")
        rec_text = (APP_ROOT / "sections" / "recommendations.py").read_text(encoding="utf-8")

        self.assertIn('"Alert Center"', config_text)
        self.assertIn('"sections.alert_center"', config_text)
        self.assertIn("consolidated Alert Center", dba_tools_text)
        self.assertNotIn("Alert Configuration", rec_text)
        self.assertNotIn("tab_alerts", rec_text)


if __name__ == "__main__":
    unittest.main()
