from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class WarehouseHealthSplitTests(unittest.TestCase):
    def test_warehouse_health_reexports_moved_contract_sql_and_dataframe_helpers(self):
        from sections import warehouse_health
        from sections import warehouse_health_actions
        from sections import warehouse_health_contracts
        from sections import warehouse_health_dataframes
        from sections import warehouse_health_helpers
        from sections import warehouse_health_overview_panels
        from sections import warehouse_health_setting_panels
        from sections import warehouse_health_sql

        self.assertIs(warehouse_health.WAREHOUSE_HEALTH_VIEWS, warehouse_health_contracts.WAREHOUSE_HEALTH_VIEWS)
        self.assertIs(warehouse_health.WAREHOUSE_HEALTH_DETAILS, warehouse_health_contracts.WAREHOUSE_HEALTH_DETAILS)
        self.assertIs(warehouse_health.WAREHOUSE_HEALTH_BRIEF_WORKFLOWS, warehouse_health_contracts.WAREHOUSE_HEALTH_BRIEF_WORKFLOWS)
        self.assertIs(warehouse_health.warehouse_setting_review_fqn, warehouse_health_sql.warehouse_setting_review_fqn)
        self.assertIs(warehouse_health.build_warehouse_setting_review_ddl, warehouse_health_sql.build_warehouse_setting_review_ddl)
        self.assertIs(warehouse_health.build_warehouse_operability_fact_ddl, warehouse_health_sql.build_warehouse_operability_fact_ddl)
        self.assertIs(warehouse_health._warehouse_cost_control_review_sql, warehouse_health_sql._warehouse_cost_control_review_sql)
        self.assertIs(warehouse_health._warehouse_operability_fact_sql, warehouse_health_sql._warehouse_operability_fact_sql)
        self.assertIs(warehouse_health._warehouse_scope_meta, warehouse_health_dataframes._warehouse_scope_meta)
        self.assertIs(warehouse_health._warehouse_source_health_rows, warehouse_health_dataframes._warehouse_source_health_rows)
        self.assertIs(warehouse_health._warehouse_period_movement, warehouse_health_dataframes._warehouse_period_movement)
        self.assertIs(warehouse_health._warehouse_overview_exceptions, warehouse_health_dataframes._warehouse_overview_exceptions)
        self.assertIs(warehouse_health._warehouse_operator_next_moves, warehouse_health_dataframes._warehouse_operator_next_moves)
        self.assertIs(warehouse_health._warehouse_capacity_score, warehouse_health_helpers._warehouse_capacity_score)
        self.assertIs(warehouse_health._warehouse_capacity_action_for, warehouse_health_helpers._warehouse_capacity_action_for)
        self.assertIs(warehouse_health._route_label, warehouse_health_actions._route_label)
        self.assertIs(warehouse_health._warehouse_owner_context, warehouse_health_actions._warehouse_owner_context)
        self.assertIs(warehouse_health._warehouse_approval_for, warehouse_health_actions._warehouse_approval_for)
        self.assertIs(warehouse_health._warehouse_setting_candidate_for, warehouse_health_actions._warehouse_setting_candidate_for)
        self.assertIs(warehouse_health._warehouse_setting_audit_readiness_for_row, warehouse_health_actions._warehouse_setting_audit_readiness_for_row)
        self.assertIs(warehouse_health._warehouse_setting_control_board, warehouse_health_actions._warehouse_setting_control_board)
        self.assertIs(warehouse_health._build_warehouse_cost_control_posture, warehouse_health_actions._build_warehouse_cost_control_posture)
        self.assertIs(warehouse_health._build_warehouse_guardrail_coverage, warehouse_health_actions._build_warehouse_guardrail_coverage)
        self.assertIs(warehouse_health._warehouse_setting_route, warehouse_health_actions._warehouse_setting_route)
        self.assertIs(warehouse_health._warehouse_setting_detail_options, warehouse_health_actions._warehouse_setting_detail_options)
        self.assertIs(warehouse_health._warehouse_capacity_review_sql, warehouse_health_actions._warehouse_capacity_review_sql)
        self.assertIs(warehouse_health._warehouse_setting_review_insert_sql, warehouse_health_actions._warehouse_setting_review_insert_sql)
        self.assertIs(warehouse_health._render_warehouse_setting_action_detail, warehouse_health_setting_panels._render_warehouse_setting_action_detail)
        self.assertIs(warehouse_health._render_warehouse_cost_control_posture, warehouse_health_setting_panels._render_warehouse_cost_control_posture)
        self.assertIs(warehouse_health._save_warehouse_setting_review_snapshot, warehouse_health_setting_panels._save_warehouse_setting_review_snapshot)
        self.assertIs(warehouse_health._warehouse_action_brief, warehouse_health_overview_panels._warehouse_action_brief)
        self.assertIs(warehouse_health._render_warehouse_action_brief, warehouse_health_overview_panels._render_warehouse_action_brief)
        self.assertIs(warehouse_health._warehouse_operating_snapshot, warehouse_health_overview_panels._warehouse_operating_snapshot)
        self.assertIs(warehouse_health._render_warehouse_operating_snapshot, warehouse_health_overview_panels._render_warehouse_operating_snapshot)
        self.assertIs(warehouse_health._warehouse_brief_workflow_rows, warehouse_health_overview_panels._warehouse_brief_workflow_rows)
        self.assertIs(warehouse_health._render_warehouse_brief_launchpad, warehouse_health_overview_panels._render_warehouse_brief_launchpad)

    def test_workflow_contracts_and_alias_labels_stay_stable(self):
        from sections import warehouse_health_contracts as contracts

        self.assertEqual(
            contracts.WAREHOUSE_HEALTH_VIEWS,
            (
                "Overview & Scaling",
                "Efficiency",
                "Spill & Memory",
                "Workload Heatmap",
                "Optimization Advisor",
            ),
        )
        self.assertEqual(contracts.WAREHOUSE_HEALTH_FAST_ENTRY_VERSION, "2026-06-06-support-panels-explicit-v1")
        self.assertEqual(contracts.WAREHOUSE_HEALTH_BRIEF_FIRST_VERSION, 2)
        self.assertEqual(
            [row["BUTTON_LABEL"] for row in contracts.WAREHOUSE_HEALTH_BRIEF_WORKFLOWS],
            ["Open Overview", "Open Efficiency", "Open Spill", "Open Heatmap", "Open Advisor"],
        )

    def test_representative_sql_builders_preserve_review_only_contracts(self):
        from sections import warehouse_health_sql as sql

        ddl = sql.build_warehouse_setting_review_ddl()
        self.assertIn("CREATE TABLE IF NOT EXISTS", ddl)
        self.assertIn("OVERWATCH_WAREHOUSE_SETTING_REVIEW", ddl)
        self.assertIn("GENERATED_REVIEW_SQL", ddl)
        self.assertIn("POST_CHANGE_VERIFICATION_STATUS", ddl)

        migrations = sql.build_warehouse_setting_review_migration_sql()
        self.assertIn("ALTER TABLE", migrations[0])
        self.assertTrue(any("APPROVAL_STATE" in item for item in migrations))
        self.assertTrue(any("VERIFIED_MONTHLY_SAVINGS" in item for item in migrations))

        review_sql = sql._warehouse_cost_control_review_sql("COMPUTE_WH", recommended_suspend=120)
        self.assertIn("Review only", review_sql)
        self.assertIn("SHOW WAREHOUSES LIKE", review_sql)
        self.assertIn("ALTER WAREHOUSE", review_sql)
        self.assertIn("AUTO_SUSPEND = 120", review_sql)

        setup_sql = sql._overwatch_dedicated_warehouse_setup_sql()
        self.assertIn("CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH", setup_sql)
        self.assertIn("AUTO_SUSPEND = 60", setup_sql)

        telemetry_sql = sql._warehouse_setting_review_sql("COMPUTE_WH", "Resize", days=5)
        self.assertIn("-- Review only: Resize for COMPUTE_WH", telemetry_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", telemetry_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", telemetry_sql)

    def test_fast_operability_sql_preserves_scope_and_ordering_contract(self):
        from sections import warehouse_health_sql as sql

        query = sql._warehouse_operability_fact_sql(30, "ALFA", "PROD").upper()
        self.assertIn("FACT_WAREHOUSE_OPERABILITY_DAILY", query)
        self.assertIn("SNAPSHOT_DATE >= DATEADD('DAY', -30, CURRENT_DATE())", query)
        self.assertIn("COMPANY = 'ALFA'", query)
        self.assertIn("ORDER BY", query)
        self.assertIn("CONTROL_RANK", query)
        self.assertIn("LIMIT 100", query)

    def test_dataframe_scope_source_health_and_empty_behavior(self):
        from sections import warehouse_health_dataframes as dataframes

        matching_meta = dataframes._warehouse_scope_meta("ALFA", "PROD", 7, state={})
        state = {
            "wh_capacity_summary": pd.DataFrame([{"A": 1}]),
            "wh_capacity_meta": matching_meta,
            "wh_operability_fact": pd.DataFrame(),
            "wh_operability_fact_error": "permission denied",
            "wh_df_wh": pd.DataFrame([{"WAREHOUSE_NAME": "A_WH"}]),
            "wh_df_wh_meta": dataframes._warehouse_scope_meta("ALFA", "PROD", 14, state={}),
            "wh_scaling": pd.DataFrame(),
            "wh_scaling_meta": matching_meta,
        }
        rows = dataframes._warehouse_source_health_rows(state, "ALFA", "PROD")
        by_surface = {row["SURFACE"]: row for _, row in rows.iterrows()}

        self.assertEqual(by_surface["Capacity brief"]["STATE"], "Loaded")
        self.assertEqual(by_surface["Control summary"]["STATE"], "Unavailable")
        self.assertEqual(by_surface["Overview"]["STATE"], "Stale")
        self.assertEqual(by_surface["Scaling events"]["STATE"], "No Rows")
        self.assertEqual(by_surface["Efficiency"]["STATE"], "On demand")
        self.assertEqual(by_surface["Capacity brief"]["ROWS"], 1)
        self.assertEqual(by_surface["Overview"]["NEXT_ACTION"], "Reload after changing company, environment, lookback, or triage filters.")

        self.assertTrue(dataframes._warehouse_meta_matches(matching_meta, matching_meta))
        self.assertFalse(dataframes._warehouse_meta_matches({"days": 14}, {"days": 7}))

    def test_period_movement_and_exception_ranking_are_stable(self):
        from sections import warehouse_health_dataframes as dataframes

        movement = dataframes._warehouse_period_movement(pd.DataFrame([
            {"WAREHOUSE_NAME": "A_WH", "METERED_CREDITS": 5, "PRIOR_METERED_CREDITS": 10, "CREDIT_DELTA": -5},
            {"WAREHOUSE_NAME": "B_WH", "METERED_CREDITS": 20, "PRIOR_METERED_CREDITS": 0, "CREDIT_DELTA": 20},
            {"WAREHOUSE_NAME": "C_WH", "METERED_CREDITS": 8, "PRIOR_METERED_CREDITS": 8, "CREDIT_DELTA": 0},
        ]))
        self.assertEqual(movement["WAREHOUSE_NAME"].tolist(), ["B_WH", "A_WH", "C_WH"])
        self.assertEqual(movement["MOVEMENT_STATE"].tolist(), ["New or no prior baseline", "Lower than prior", "Stable"])
        self.assertNotIn("CREDIT_DELTA_ABS", movement.columns)

        exceptions = dataframes._warehouse_overview_exceptions(pd.DataFrame([
            {"WAREHOUSE_NAME": "QUEUE_WH", "AVG_QUEUED_SEC": 12, "TOTAL_REMOTE_SPILL_GB": 0, "P95_ELAPSED_SEC": 10, "CREDIT_DELTA": 0},
            {"WAREHOUSE_NAME": "SPILL_WH", "AVG_QUEUED_SEC": 0, "TOTAL_REMOTE_SPILL_GB": 20, "P95_ELAPSED_SEC": 10, "CREDIT_DELTA": 0},
            {"WAREHOUSE_NAME": "COST_WH", "AVG_QUEUED_SEC": 0, "TOTAL_REMOTE_SPILL_GB": 0, "P95_ELAPSED_SEC": 10, "CREDIT_DELTA": 30},
        ]))
        self.assertEqual([row["severity"] for row in exceptions], ["Critical", "Critical", "Review"])
        self.assertEqual(exceptions[0]["warehouse"], "QUEUE_WH")
        self.assertEqual(dataframes._warehouse_overview_exceptions(pd.DataFrame()), [])

    def test_operator_next_moves_preserves_gate_columns_and_ranking(self):
        from sections import warehouse_health_dataframes as dataframes

        moves = dataframes._warehouse_operator_next_moves(
            score=55,
            exceptions=pd.DataFrame([
                {"WAREHOUSE_NAME": "A_WH", "SIGNAL": "CREDIT_SPIKE", "METERED_CREDITS": 12, "IMPACT_TELEMETRY_REQUIRED": "Yes"},
            ]),
            closure=pd.DataFrame([{"OVERDUE_OPEN": 1, "FIXED_WITHOUT_VERIFICATION": 0}]),
            execution_audit=pd.DataFrame([{"FAILED_CHANGES": 1, "AUDIT_ROWS": 1}]),
            operability_fact=pd.DataFrame([{"QUEUE_PRESSURE_ROWS": 2, "SPILL_PRESSURE_ROWS": 1}]),
        )

        self.assertEqual(moves.iloc[0]["GATE"], "Closure status")
        self.assertEqual(moves.iloc[0]["STATE"], "Blocked")
        self.assertIn("PROOF_REQUIRED", moves.columns)
        self.assertIn("NEXT_ACTION", moves.columns)
        self.assertEqual(set(moves["GATE"]), {"Closure status", "Execution audit", "Telemetry route", "Capacity pressure", "Cost guardrail"})

    def test_warehouse_owner_routing_stays_stable(self):
        from sections import warehouse_health_actions as actions

        cases = [
            ({"WAREHOUSE_NAME": "ANY_WH", "SIGNAL": "Credit Spike"}, "DBA / Cost Route", "Cost owner / DBA Lead", "Cost owner / Warehouse Route"),
            ({"WAREHOUSE_NAME": "ETL_LOAD_TASK_WH", "SIGNAL": "Queue Pressure"}, "Data Engineering Route", "Pipeline Route / DBA On-Call", "Data Engineering Route / DBA Lead"),
            ({"WAREHOUSE_NAME": "BI_POWERBI_TABLEAU_WH", "SIGNAL": "Memory Spill"}, "BI Platform Route", "BI Product Route / DBA Lead", "BI Platform Route / Query Route"),
            ({"WAREHOUSE_NAME": "DEV_SAN_SIT_WH", "SIGNAL": "Latency Pressure"}, "Development Platform Route", "DBA Lead", "Development Platform Route / DBA Lead"),
            ({"WAREHOUSE_NAME": "CORE_WH", "SIGNAL": "Latency Pressure"}, "Platform DBA", "DBA Lead", "Platform DBA / DBA Lead"),
        ]
        for row, owner, escalation, approval in cases:
            with self.subTest(row=row):
                context = actions._warehouse_owner_context(row)
                self.assertEqual(context["owner"], owner)
                self.assertEqual(context["escalation"], escalation)
                self.assertEqual(actions._warehouse_approval_for({**row, "OWNER": owner}), approval)

    def test_warehouse_setting_candidates_stay_stable_by_signal(self):
        from sections import warehouse_health_actions as actions

        base = {
            "WAREHOUSE_NAME": "APP_WH",
            "QUEUED_QUERIES": 3,
            "SPILL_QUERIES": 4,
            "HIGH_LATENCY_QUERIES": 5,
            "CREDIT_SPIKE_PCT": 42.5,
            "P95_ELAPSED_SEC": 88.1,
        }
        expectations = [
            ("Queue Pressure", "MAX_CLUSTER_COUNT", "No"),
            ("Memory Spill", "WAREHOUSE_SIZE only after top spilling queries", "No"),
            ("Credit Spike", "AUTO_SUSPEND", "Yes"),
            ("Latency Pressure", "STATEMENT_TIMEOUT_IN_SECONDS", "No"),
        ]
        for signal, phrase, impact in expectations:
            with self.subTest(signal=signal):
                candidate = actions._warehouse_setting_candidate_for(pd.Series({**base, "SIGNAL": signal}))
                self.assertEqual(candidate["ADMIN_READINESS"], "Ready for DBA review")
                self.assertIn(phrase, candidate["SETTING_CHANGE_CANDIDATE"])
                self.assertEqual(candidate["APPROVAL_REQUIRED"], "Yes")
                self.assertEqual(candidate["ROLLBACK_REQUIRED"], "Yes")
                self.assertEqual(candidate["IMPACT_TELEMETRY_REQUIRED"], impact)
                self.assertIn("queued=3", candidate["PRESSURE_EVIDENCE"])

    def test_warehouse_setting_audit_readiness_states_are_stable(self):
        from sections import warehouse_health_actions as actions

        base = {
            "OWNER": "Platform DBA",
            "OWNER_SOURCE": "Route map",
            "APPROVER": "DBA Lead",
            "APPROVAL_REQUIRED": "Yes",
            "APPROVAL_STATE": "Approved",
            "CHANGE_TICKET_ID": "CHG123",
            "ROLLBACK_REQUIRED": "Yes",
            "ROLLBACK_SQL": "ALTER WAREHOUSE APP_WH SET AUTO_SUSPEND = 600",
            "EXECUTION_STATUS": "Not Executed",
        }
        cases = [
            ({**base, "OWNER": "", "OWNER_SOURCE": ""}, "Route Metadata Blocked", "escalation route"),
            ({**base, "APPROVAL_STATE": "Requested"}, "Pre-Change Blocked", "review status"),
            ({**base, "ROLLBACK_SQL": ""}, "Pre-Change Blocked", "rollback SQL"),
            ({**base, "EXECUTION_STATUS": "Failed"}, "Execution Failed", "None"),
            ({
                **base,
                "EXECUTION_STATUS": "Success",
                "EXECUTED_SQL_HASH": "abc123",
                "POST_CHANGE_VERIFICATION_STATUS": "Pending",
            }, "Telemetry Pending", "post-change telemetry"),
            ({
                **base,
                "EXECUTION_STATUS": "Success",
                "EXECUTED_SQL_HASH": "abc123",
                "POST_CHANGE_VERIFICATION_STATUS": "Verified",
                "POST_CHANGE_VERIFICATION_RESULT": "Queue, spill, and credits verified after change.",
                "IMPACT_TELEMETRY_REQUIRED": "Yes",
                "VERIFIED_MONTHLY_SAVINGS": 12.5,
            }, "Change Audit Linked", "None"),
        ]
        for row, readiness, blocker in cases:
            with self.subTest(readiness=readiness, blocker=blocker):
                result = actions._warehouse_setting_audit_readiness_for_row(row)
                self.assertEqual(result["AUDIT_READINESS"], readiness)
                self.assertIn(blocker, result["AUDIT_BLOCKERS"])
                self.assertTrue(result["NEXT_CONTROL_ACTION"])

    def test_cost_control_posture_preserves_states_and_review_sql(self):
        from sections import warehouse_health_actions as actions

        settings = pd.DataFrame([
            {"NAME": "BLOCKED_WH", "AUTO_SUSPEND": 0, "AUTO_RESUME": True, "WAREHOUSE_SIZE": "XSMALL", "STATE": "STARTED"},
            {"NAME": "REVIEW_WH", "AUTO_SUSPEND": 700, "AUTO_RESUME": True, "WAREHOUSE_SIZE": "SMALL", "STATE": "SUSPENDED"},
            {"NAME": "WATCH_WH", "AUTO_SUSPEND": 400, "AUTO_RESUME": True, "WAREHOUSE_SIZE": "SMALL", "STATE": "SUSPENDED"},
            {"NAME": "READY_WH", "AUTO_SUSPEND": 300, "AUTO_RESUME": True, "WAREHOUSE_SIZE": "SMALL", "STATE": "SUSPENDED"},
            {"NAME": "MISSING_WH", "AUTO_RESUME": True, "WAREHOUSE_SIZE": "SMALL", "STATE": "SUSPENDED"},
        ])
        overview = pd.DataFrame([
            {"WAREHOUSE_NAME": "BLOCKED_WH", "METERED_CREDITS": 20},
            {"WAREHOUSE_NAME": "READY_WH", "METERED_CREDITS": 2},
        ])
        summary, posture = actions._build_warehouse_cost_control_posture(settings, overview)
        states = dict(zip(posture["WAREHOUSE_NAME"], posture["COST_CONTROL_STATE"]))

        self.assertEqual(states["BLOCKED_WH"], "Blocked")
        self.assertEqual(states["REVIEW_WH"], "Needs Review")
        self.assertEqual(states["WATCH_WH"], "Watch")
        self.assertEqual(states["READY_WH"], "Ready")
        self.assertEqual(states["MISSING_WH"], "Data Missing")
        self.assertEqual(summary["warehouses"], 5)
        self.assertGreaterEqual(summary["blocked"], 1)
        self.assertTrue(posture["REVIEW_SQL"].str.contains("ALTER WAREHOUSE").all())
        self.assertTrue(posture["REVIEW_SQL"].str.contains("Review only").all())

    def test_guardrail_coverage_preserves_columns_states_score_and_next_action(self):
        from sections import warehouse_health_actions as actions

        overview = pd.DataFrame([
            {
                "WAREHOUSE_NAME": "COMPUTE_WH",
                "METERED_CREDITS": 75,
                "CREDIT_DELTA": 30,
                "CREDIT_DELTA_PCT": 80,
                "AVG_QUEUED_SEC": 5,
                "TOTAL_REMOTE_SPILL_GB": 20,
                "P95_ELAPSED_SEC": 90,
                "TOTAL_QUERIES": 100,
            },
            {
                "WAREHOUSE_NAME": "READY_WH",
                "METERED_CREDITS": 5,
                "CREDIT_DELTA": 0,
                "CREDIT_DELTA_PCT": 0,
                "AVG_QUEUED_SEC": 0,
                "TOTAL_REMOTE_SPILL_GB": 0,
                "P95_ELAPSED_SEC": 5,
                "TOTAL_QUERIES": 20,
            },
        ])
        settings = pd.DataFrame([
            {
                "NAME": "COMPUTE_WH",
                "AUTO_SUSPEND": 0,
                "RESOURCE_MONITOR": "",
                "STATEMENT_TIMEOUT_IN_SECONDS": 0,
                "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 0,
            },
            {
                "NAME": "READY_WH",
                "AUTO_SUSPEND": 300,
                "RESOURCE_MONITOR": "READY_RM",
                "STATEMENT_TIMEOUT_IN_SECONDS": 3600,
                "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 600,
            },
        ])
        summary, board = actions._build_warehouse_guardrail_coverage(overview, settings_inventory=settings)
        by_wh = {row["WAREHOUSE_NAME"]: row for _, row in board.iterrows()}

        self.assertEqual(by_wh["COMPUTE_WH"]["GUARDRAIL_STATE"], "Blocked")
        self.assertEqual(by_wh["READY_WH"]["GUARDRAIL_STATE"], "Ready")
        self.assertLess(by_wh["COMPUTE_WH"]["GUARDRAIL_SCORE"], by_wh["READY_WH"]["GUARDRAIL_SCORE"])
        self.assertEqual(summary["warehouses"], 2)
        self.assertGreaterEqual(summary["blocked"], 1)
        self.assertIn("RESOURCE_MONITOR_STATE", board.columns)
        self.assertIn("AUTO_SUSPEND_STATE", board.columns)
        self.assertIn("TIMEOUT_STATE", board.columns)
        self.assertIn("NEXT_ACTION", board.columns)

    def test_setting_detail_and_cost_control_panels_keep_streamlit_keys(self):
        from sections import warehouse_health_setting_panels as panels

        plan = pd.DataFrame([{
            "PRIORITY": "High",
            "WAREHOUSE_NAME": "COMPUTE_WH",
            "ACTION_TYPE": "Auto-suspend review",
            "CURRENT_STATE": "Blocked",
            "CURRENT_SETTING": "0",
            "SAFE_SETTING_MOVE": "Review idle burn.",
            "WHY": "Idle burn",
            "PROOF_REQUIRED": "SHOW WAREHOUSES",
            "ROLLBACK_CHECK": "Verify credits.",
            "REVIEW_SQL": "-- review only",
        }])
        settings = pd.DataFrame([{
            "NAME": "COMPUTE_WH",
            "AUTO_SUSPEND": 0,
            "AUTO_RESUME": True,
            "WAREHOUSE_SIZE": "XSMALL",
            "STATE": "STARTED",
        }])
        select_keys: list[str] = []
        button_keys: list[str] = []

        def _selectbox(_label, options, *, key):
            select_keys.append(key)
            return options[0]

        def _button(_label, *, key, width):
            button_keys.append(key)
            return False

        with (
            patch.object(panels.st, "markdown"),
            patch.object(panels.st, "caption"),
            patch.object(panels.st, "selectbox", side_effect=_selectbox),
            patch.object(panels.st, "button", side_effect=_button),
            patch.object(panels.st, "code"),
            patch.object(panels.st, "subheader"),
            patch.object(panels.st, "info"),
            patch.object(panels.st, "expander", return_value=_Context()),
            patch.object(panels, "render_shell_snapshot"),
            patch.object(panels, "render_escaped_labeled_text"),
            patch.object(panels, "render_priority_dataframe"),
            patch.object(panels, "download_csv"),
        ):
            panels._render_warehouse_setting_action_detail(plan)
            panels._render_warehouse_cost_control_posture(settings, pd.DataFrame())

        self.assertIn("warehouse_setting_action_select", select_keys)
        self.assertIn("warehouse_cost_control_sql_select", select_keys)
        self.assertIn("warehouse_setting_action_route", button_keys)

    def test_warehouse_setting_review_insert_sql_preserves_audit_columns(self):
        from sections import warehouse_health_actions as actions

        findings = pd.DataFrame([{
            "WAREHOUSE_NAME": "COMPUTE_WH",
            "SEVERITY": "High",
            "SIGNAL": "Credit Spike",
            "CAPACITY_SCORE": 55,
            "QUEUED_QUERIES": 2,
            "SPILL_QUERIES": 1,
            "HIGH_LATENCY_QUERIES": 3,
            "P95_ELAPSED_SEC": 90,
            "METERED_CREDITS": 44,
        }])
        sql = actions._warehouse_setting_review_insert_sql(
            findings,
            company="ALFA",
            environment="PROD",
            source="Unit Test",
            snapshot_id="SNAPSHOT_1",
        )
        self.assertIn("OVERWATCH_WAREHOUSE_SETTING_REVIEW", sql)
        self.assertIn("GENERATED_REVIEW_SQL", sql)
        self.assertIn("VERIFICATION_QUERY", sql)
        self.assertIn("AUDIT_READINESS", sql)
        self.assertIn("AUDIT_BLOCKERS", sql)
        self.assertIn("NEXT_CONTROL_ACTION", sql)
        self.assertIn("ROLLBACK_SQL", sql)
        self.assertIn("APPROVAL_STATE", sql)
        self.assertIn("Unit Test", sql)

    def test_warehouse_health_split_does_not_import_alert_facade(self):
        alert_facade_import = "utils" + ".alerts"
        for path in (
            APP_ROOT / "sections" / "warehouse_health.py",
            APP_ROOT / "sections" / "warehouse_health_actions.py",
            APP_ROOT / "sections" / "warehouse_health_contracts.py",
            APP_ROOT / "sections" / "warehouse_health_dataframes.py",
            APP_ROOT / "sections" / "warehouse_health_helpers.py",
            APP_ROOT / "sections" / "warehouse_health_overview_panels.py",
            APP_ROOT / "sections" / "warehouse_health_setting_panels.py",
            APP_ROOT / "sections" / "warehouse_health_sql.py",
        ):
            with self.subTest(path=path.name):
                self.assertNotIn(alert_facade_import, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
