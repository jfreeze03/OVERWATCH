from pathlib import Path
import math
import re
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections.account_health import _live_query_status_sql  # noqa: E402
from sections.adoption_analytics import _metric as adoption_metric  # noqa: E402
from sections.cost_center import (  # noqa: E402
    _bill_driver_summary,
    _build_bill_waterfall,
    _build_finance_movement_summary,
    _service_cost_category,
)
from sections.dba_control_room import (  # noqa: E402
    _build_report as _build_dba_control_report,
    _build_release_compare_report,
    _compare_release_windows,
    _control_room_snapshot_to_data,
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
    _build_change_drift_markdown,
    _change_action_for,
    _change_drift_rating,
    _change_drift_score,
)
from sections.query_workbench import (  # noqa: E402
    _build_root_cause_markdown,
    _root_cause_action_for,
    _root_cause_rating,
    _root_cause_score,
)
from sections.service_health import _value as service_value  # noqa: E402
from sections.security_posture import (  # noqa: E402
    _build_security_brief_markdown,
    _security_action_for,
    _security_rating,
    _security_score,
)
from sections.stored_proc_tracker import (  # noqa: E402
    _build_procedure_sla_frames,
    _build_procedure_ops_frames,
    _procedure_from_task_definition,
    _procedure_key,
)
from sections.task_management import (  # noqa: E402
    _admin_sql_for_graph,
    _admin_sql_for_task,
    _build_failure_console_frames,
    _build_failure_runbook_markdown,
    _build_task_graph_dot,
    _build_task_ops_frames,
    _build_task_ops_markdown,
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
    _build_warehouse_capacity_markdown,
    _warehouse_capacity_action_for,
    _warehouse_capacity_rating,
    _warehouse_capacity_score,
)
from utils.cost import build_metered_credit_cte  # noqa: E402
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
    build_mart_control_room_cost_drivers_sql,
    build_mart_control_room_summary_sql,
    build_mart_control_room_task_failures_sql,
    build_mart_pipeline_load_failures_sql,
    build_mart_query_bottleneck_sql,
    build_mart_query_degradation_sql,
    build_mart_recommendation_failed_tasks_sql,
    build_mart_recommendation_idle_sql,
    build_mart_recommendation_query_errors_sql,
    build_mart_recommendation_spill_sql,
)


def _python_sources():
    return [
        path
        for path in APP_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


class FormulaRegressionTests(unittest.TestCase):
    def test_metered_credit_cte_uses_compute_credits_with_total_fallback(self):
        sql = build_metered_credit_cte(hours_back=24, include_recent=True).upper()
        self.assertIn("WAREHOUSE_METERING_HISTORY", sql)
        self.assertIn("COALESCE(CREDITS_USED_COMPUTE, CREDITS_USED)", sql)
        self.assertIn("AS HOURLY_COMPUTE_CREDITS", sql)
        self.assertNotIn("SUM(CREDITS_USED)               AS HOURLY_COMPUTE_CREDITS", sql)

    def test_account_health_live_counts_prefer_information_schema(self):
        sql = _live_query_status_sql("", "", "").upper()
        self.assertIn("INFORMATION_SCHEMA.QUERY_HISTORY", sql)
        self.assertIn("QUEUED_OVERLOAD_TIME", sql)
        self.assertIn("QUEUED_PROVISIONING_TIME", sql)
        self.assertIn("QUEUED_REPAIR_TIME", sql)
        self.assertIn("RESUMING_WAREHOUSE", sql)

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
        self.assertEqual(confidence["Query-attributed workload"], "Allocated")
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
        self.assertIn("ACCOUNT_USAGE can lag", md)

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
                "STATE": ["SUCCEEDED", "FAILED"],
                "DURATION_SEC": [100, 400],
                "QUERY_ID": ["q1", "q2"],
                "ERROR_MESSAGE": ["", "bad object"],
            }
        )
        summary, exceptions, latest = _build_task_ops_frames(inventory, history)
        self.assertEqual(summary["TOTAL_TASKS"], 2)
        self.assertEqual(summary["FAILED_RUNS"], 1)
        self.assertEqual(summary["SUSPENDED_TASKS"], 1)
        self.assertIn("SP_ROOT", str(latest.get("PROCEDURE_NAME", "")))
        self.assertIn("Failed Task Run", set(exceptions["SIGNAL"]))
        self.assertIn("Suspended Task", set(exceptions["SIGNAL"]))

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
        self.assertEqual(failures.iloc[0]["PROCEDURE_NAME"], "ALFA_EDW_DEV.PUBLIC.SP_LOAD_POLICY")
        self.assertEqual(failures.iloc[0]["FAILURE_CATEGORY"], "Object Dependency / Drift")
        self.assertIn("EXECUTE TASK", failures.iloc[0]["RETRY_SQL"])
        self.assertEqual(patterns.iloc[0]["FAILURE_COUNT"], 1)
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
        self.assertEqual(_procedure_key("ALFA_EDW_DEV.PUBLIC.SP_ROOT()"), "SP_ROOT")
        self.assertEqual(_procedure_from_task_definition("CALL DB.SCH.SP_ROOT();"), "DB.SCH.SP_ROOT")
        self.assertIn("Orphan Procedure Candidate", set(exceptions["SIGNAL"]))
        self.assertIn("TASK_COUNT", joined.columns)

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


if __name__ == "__main__":
    unittest.main()
