from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))


class WarehouseHealthSplitTests(unittest.TestCase):
    def test_warehouse_health_reexports_moved_contract_sql_and_dataframe_helpers(self):
        from sections import warehouse_health
        from sections import warehouse_health_contracts
        from sections import warehouse_health_dataframes
        from sections import warehouse_health_helpers
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

    def test_warehouse_health_split_does_not_import_alert_facade(self):
        alert_facade_import = "utils" + ".alerts"
        for path in (
            APP_ROOT / "sections" / "warehouse_health.py",
            APP_ROOT / "sections" / "warehouse_health_contracts.py",
            APP_ROOT / "sections" / "warehouse_health_dataframes.py",
            APP_ROOT / "sections" / "warehouse_health_helpers.py",
            APP_ROOT / "sections" / "warehouse_health_sql.py",
        ):
            with self.subTest(path=path.name):
                self.assertNotIn(alert_facade_import, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
