from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
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
        from sections import warehouse_health_capacity
        from sections import warehouse_health_contracts
        from sections import warehouse_health_dataframes
        from sections import warehouse_health_helpers
        from sections import warehouse_health_loader
        from sections import warehouse_health_overview_panels
        from sections import warehouse_health_panels
        from sections import warehouse_health_queue
        from sections import warehouse_health_rendering
        from sections import warehouse_health_setting_panels
        from sections import warehouse_health_sql
        from sections import warehouse_health_view_advisor
        from sections import warehouse_health_view_efficiency
        from sections import warehouse_health_view_heatmap
        from sections import warehouse_health_view_overview
        from sections import warehouse_health_view_spill

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
        self.assertIs(warehouse_health._warehouse_action_session, warehouse_health_loader._warehouse_action_session)
        self.assertIs(warehouse_health._warehouse_sql_exprs, warehouse_health_capacity._warehouse_sql_exprs)
        self.assertIs(warehouse_health._build_warehouse_capacity_sql, warehouse_health_capacity._build_warehouse_capacity_sql)
        self.assertIs(warehouse_health._build_warehouse_capacity_markdown, warehouse_health_capacity._build_warehouse_capacity_markdown)
        self.assertIs(warehouse_health._render_warehouse_watch_floor, warehouse_health_capacity._render_warehouse_watch_floor)
        self.assertIs(warehouse_health._queue_capacity_findings, warehouse_health_queue._queue_capacity_findings)
        self.assertIs(warehouse_health._queue_efficiency_findings, warehouse_health_queue._queue_efficiency_findings)
        self.assertIs(warehouse_health._render_capacity_brief, warehouse_health_panels._render_capacity_brief)
        self.assertIs(warehouse_health._render_warehouse_source_health, warehouse_health_panels._render_warehouse_source_health)
        self.assertIs(warehouse_health._apply_warehouse_fast_entry_default, warehouse_health_panels._apply_warehouse_fast_entry_default)
        self.assertIs(warehouse_health._render_warehouse_overview_exception_strip, warehouse_health_panels._render_warehouse_overview_exception_strip)
        self.assertIs(warehouse_health.render_operator_briefing, warehouse_health_rendering.render_operator_briefing)
        self.assertIs(warehouse_health._load_warehouse_overview, warehouse_health_view_overview._load_warehouse_overview)
        self.assertIs(warehouse_health._render_warehouse_overview_view, warehouse_health_view_overview._render_warehouse_overview_view)
        self.assertIs(warehouse_health._render_warehouse_efficiency_view, warehouse_health_view_efficiency._render_warehouse_efficiency_view)
        self.assertIs(warehouse_health._render_warehouse_spill_view, warehouse_health_view_spill._render_warehouse_spill_view)
        self.assertIs(warehouse_health._render_warehouse_heatmap_view, warehouse_health_view_heatmap._render_warehouse_heatmap_view)
        self.assertIs(warehouse_health._render_warehouse_advisor_view, warehouse_health_view_advisor._render_warehouse_advisor_view)

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

        review_sql = sql._warehouse_cost_control_review_sql("WH_ALFA_OVERWATCH", recommended_suspend=120)
        self.assertIn("Review only", review_sql)
        self.assertIn("SHOW WAREHOUSES LIKE", review_sql)
        self.assertIn("ALTER WAREHOUSE", review_sql)
        self.assertIn("AUTO_SUSPEND = 120", review_sql)

        setup_sql = sql._overwatch_dedicated_warehouse_setup_sql()
        self.assertIn("CREATE WAREHOUSE IF NOT EXISTS WH_ALFA_OVERWATCH", setup_sql)
        self.assertIn("AUTO_SUSPEND = 60", setup_sql)

        telemetry_sql = sql._warehouse_setting_review_sql("WH_ALFA_OVERWATCH", "Resize", days=5)
        self.assertIn("-- Review only: Resize for WH_ALFA_OVERWATCH", telemetry_sql)
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
        self.assertEqual(by_surface["Efficiency"]["STATE"], "Details available when needed")
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

    def test_warehouse_route_mapping_stays_stable(self):
        from sections import warehouse_health_actions as actions

        cases = [
            ({"WAREHOUSE_NAME": "ANY_WH", "SIGNAL": "Credit Spike"}, "DBA / Cost Route", "Cost attribution / DBA Lead", "Cost attribution / Cost Route"),
            ({"WAREHOUSE_NAME": "ETL_LOAD_TASK_WH", "SIGNAL": "Queue Pressure"}, "Data Engineering Route", "Pipeline Route / DBA Review", "Data Engineering Route / DBA Lead"),
            ({"WAREHOUSE_NAME": "BI_POWERBI_TABLEAU_WH", "SIGNAL": "Memory Spill"}, "BI Platform Route", "BI Product Route / DBA Lead", "BI Platform Route / Query Route"),
            ({"WAREHOUSE_NAME": "DEV_SAN_SIT_WH", "SIGNAL": "Latency Pressure"}, "Development Platform Route", "DBA Lead", "Development Platform Route / DBA Lead"),
            ({"WAREHOUSE_NAME": "CORE_WH", "SIGNAL": "Latency Pressure"}, "Platform DBA", "DBA Lead", "Platform DBA / DBA Lead"),
        ]
        for row, route, escalation, approval in cases:
            with self.subTest(row=row):
                context = actions._warehouse_owner_context(row)
                self.assertEqual(context["owner"], route)
                self.assertEqual(context["escalation"], escalation)
                self.assertEqual(actions._warehouse_approval_for({**row, "OWNER": route}), approval)

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
            "ALLOCATION_SOURCE": "Route map",
            "APPROVER": "DBA Lead",
            "APPROVAL_REQUIRED": "Yes",
            "APPROVAL_STATE": "Approved",
            "CHANGE_TICKET_ID": "CHG123",
            "ROLLBACK_REQUIRED": "Yes",
            "ROLLBACK_SQL": "ALTER WAREHOUSE APP_WH SET AUTO_SUSPEND = 600",
            "EXECUTION_STATUS": "Not Executed",
        }
        cases = [
            ({**base, "OWNER": "", "ALLOCATION_SOURCE": ""}, "Route Metadata Blocked", "escalation route"),
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
                "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
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
                "NAME": "WH_ALFA_OVERWATCH",
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

        self.assertEqual(by_wh["WH_ALFA_OVERWATCH"]["GUARDRAIL_STATE"], "Blocked")
        self.assertEqual(by_wh["READY_WH"]["GUARDRAIL_STATE"], "Ready")
        self.assertLess(by_wh["WH_ALFA_OVERWATCH"]["GUARDRAIL_SCORE"], by_wh["READY_WH"]["GUARDRAIL_SCORE"])
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
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
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
            "NAME": "WH_ALFA_OVERWATCH",
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
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
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

    def test_warehouse_sql_exprs_preserves_optional_column_fallbacks(self):
        from sections import warehouse_health_capacity as capacity

        def _columns(_session, table, _columns):
            if table.endswith("QUERY_HISTORY"):
                return [
                    "WAREHOUSE_SIZE",
                    "QUEUED_OVERLOAD_TIME",
                    "BYTES_SPILLED_TO_REMOTE_STORAGE",
                    "BYTES_SCANNED",
                ]
            return ["CREDITS_USED_COMPUTE"]

        with patch.object(capacity, "filter_existing_columns", side_effect=_columns):
            exprs = capacity._warehouse_sql_exprs(object())

        self.assertEqual(exprs["wh_size_expr"], "MAX(q.warehouse_size)")
        self.assertEqual(exprs["queue_avg_expr"], "AVG(q.queued_overload_time)/1000")
        self.assertEqual(exprs["local_spill_expr"], "0")
        self.assertEqual(exprs["remote_spill_expr"], "SUM(bytes_spilled_to_remote_storage)")
        self.assertEqual(exprs["bytes_scanned_expr"], "SUM(q.bytes_scanned)")
        self.assertEqual(exprs["compute_meter_expr"], "m.credits_used_compute")
        self.assertEqual(exprs["cloud_meter_expr"], "0::FLOAT")

        with patch.object(capacity, "filter_existing_columns", return_value=[]):
            fallback = capacity._warehouse_sql_exprs(object())
        self.assertEqual(fallback["wh_size_expr"], "NULL::VARCHAR")
        self.assertEqual(fallback["queue_sum_expr"], "0")
        self.assertEqual(fallback["remote_spill_sum_expr"], "0")
        self.assertEqual(fallback["compute_meter_expr"], "m.credits_used")

    def test_build_warehouse_capacity_sql_preserves_shape_filters_and_lookback(self):
        from sections import warehouse_health_capacity as capacity

        def _columns(_session, table, _columns):
            if table.endswith("QUERY_HISTORY"):
                return [
                    "WAREHOUSE_SIZE",
                    "QUEUED_OVERLOAD_TIME",
                    "QUEUED_PROVISIONING_TIME",
                    "QUEUED_REPAIR_TIME",
                    "BYTES_SPILLED_TO_LOCAL_STORAGE",
                    "BYTES_SPILLED_TO_REMOTE_STORAGE",
                ]
            return ["CREDITS_USED_COMPUTE", "CREDITS_USED"]

        with (
            patch.object(capacity, "filter_existing_columns", side_effect=_columns),
            patch.object(capacity, "get_global_filter_clause", return_value="AND q.company = 'ALFA'"),
            patch.object(capacity, "get_wh_filter_clause", return_value="AND m.warehouse_name LIKE 'ALFA%'"),
        ):
            summary_sql, exceptions_sql = capacity._build_warehouse_capacity_sql(object(), 9)

        combined_sql = f"{summary_sql}\n{exceptions_sql}".upper()
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", combined_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY", combined_sql)
        self.assertIn("DATEADD('DAY', -9, CURRENT_TIMESTAMP())", combined_sql)
        self.assertIn("COALESCE(Q.QUEUED_OVERLOAD_TIME, 0)", combined_sql)
        self.assertIn("COALESCE(Q.QUEUED_PROVISIONING_TIME, 0)", combined_sql)
        self.assertIn("COALESCE(Q.BYTES_SPILLED_TO_REMOTE_STORAGE, 0)", combined_sql)
        self.assertIn("AND Q.COMPANY = 'ALFA'", combined_sql)
        self.assertIn("AND M.WAREHOUSE_NAME LIKE 'ALFA%'", combined_sql)
        self.assertIn("LIMIT 100", combined_sql)
        self.assertIn("CAPACITY_SCORE", combined_sql)

    def test_build_warehouse_capacity_markdown_preserves_headings_and_exception_lines(self):
        from sections import warehouse_health_capacity as capacity

        markdown = capacity._build_warehouse_capacity_markdown(
            "ALFA",
            7,
            72,
            {
                "WAREHOUSES_ACTIVE": 2,
                "TOTAL_QUERIES": 100,
                "QUEUED_QUERIES": 4,
                "SPILL_QUERIES": 3,
                "CREDIT_SPIKE_PCT": 12.3,
            },
            pd.DataFrame([{
                "SEVERITY": "High",
                "SIGNAL": "Credit Spike",
                "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
                "METERED_CREDITS": 42.5,
                "SETTING_CHANGE_CANDIDATE": "Review AUTO_SUSPEND.",
            }]),
        )

        self.assertIn("# OVERWATCH Warehouse Capacity Brief - ALFA", markdown)
        self.assertIn("## DBA Narrative", markdown)
        self.assertIn("## Top Warehouse Exceptions", markdown)
        self.assertIn(
            "High | Credit Spike | WH_ALFA_OVERWATCH | 42.50 credits | "
            "Review AUTO_SUSPEND, MIN_CLUSTER_COUNT, MAX_CLUSTER_COUNT",
            markdown,
        )
        self.assertIn("## Settings Change Status", markdown)
        self.assertIn("## Telemetry Limits", markdown)

    def test_render_warehouse_watch_floor_preserves_button_keys_and_warehouse_scope_updates(self):
        from sections import warehouse_health_capacity as capacity

        exceptions = pd.DataFrame([{
            "SEVERITY": "Critical",
            "SIGNAL": "Queue Pressure",
            "WAREHOUSE_NAME": "ETL_WH",
            "QUEUED_QUERIES": 8,
            "SPILL_QUERIES": 1,
            "METERED_CREDITS": 12,
            "CAPACITY_SCORE": 45,
            "NEXT_ACTION": "Open queue workflow.",
            "NEXT_WORKFLOW": "Efficiency",
        }])
        session_state: dict = {}
        button_keys: list[str] = []

        def _button(_label, *, key, help, width):
            button_keys.append(key)
            return True

        with (
            patch.object(capacity.st, "session_state", session_state),
            patch.object(capacity.st, "success"),
            patch.object(capacity.st, "warning"),
            patch.object(capacity.st, "markdown"),
            patch.object(capacity.st, "caption"),
            patch.object(capacity.st, "columns", return_value=[_Context()]),
            patch.object(capacity.st, "button", side_effect=_button),
            patch.object(capacity.st, "rerun"),
            patch.object(capacity, "render_shell_snapshot"),
            patch.object(capacity, "render_escaped_bold_text"),
            patch.object(capacity, "format_credits", side_effect=lambda value: f"{value:.2f} credits"),
            patch.object(capacity, "_queue_warehouse_health_view") as queue_view,
        ):
            capacity._render_warehouse_watch_floor(55, exceptions, {"REMOTE_SPILL_GB": 1, "QUEUED_QUERIES": 8})

        self.assertEqual(button_keys, ["wh_watch_floor_0_Workload Heatmap"])
        self.assertEqual(session_state["global_warehouse"], "ETL_WH")
        self.assertEqual(session_state["wh_filter"], "ETL_WH")
        self.assertEqual(session_state["lm_wh"], "ETL_WH")
        queue_view.assert_called_once_with("Workload Heatmap")

    def test_queue_capacity_findings_builds_review_only_action_fields(self):
        from sections import warehouse_health_queue as queue

        captured: dict = {}

        def _upsert(_session, actions):
            captured["actions"] = actions
            return len(actions)

        exceptions = pd.DataFrame([{
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "SIGNAL": "Credit Spike",
            "SEVERITY": "High",
            "QUEUED_QUERIES": 2,
            "SPILL_QUERIES": 1,
            "HIGH_LATENCY_QUERIES": 3,
            "METERED_CREDITS": 44,
            "CAPACITY_SCORE": 52,
        }])
        with (
            patch.object(queue.st, "session_state", {"active_company": "ALFA", "global_environment": "PROD"}),
            patch.object(queue, "upsert_actions", side_effect=_upsert),
            patch.object(queue, "make_action_id", return_value="ACTION-1"),
        ):
            saved = queue._queue_capacity_findings(object(), exceptions)

        self.assertEqual(saved, 1)
        action = captured["actions"][0]
        self.assertEqual(action["Action ID"], "ACTION-1")
        self.assertEqual(action["Company"], "ALFA")
        self.assertEqual(action["Environment"], "PROD")
        self.assertEqual(action["Category"], "Warehouse Capacity")
        self.assertIn("Review from", action["Action"])
        self.assertIn("Do not execute a warehouse change", action["Generated SQL Fix"])
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", action["Telemetry Query"])
        self.assertTrue(action["Reviewer"])
        self.assertTrue(action["Route"])
        self.assertTrue(action["Route Basis"])
        self.assertIn("Closure uses post-change telemetry", action["Recovery Status"])

    def test_queue_efficiency_findings_builds_review_only_action_fields(self):
        from sections import warehouse_health_queue as queue

        captured: dict = {}

        def _upsert(_session, actions):
            captured["actions"] = actions
            return len(actions)

        findings = pd.DataFrame([{
            "WAREHOUSE_NAME": "BI_WH",
            "EFFICIENCY_SCORE": 48,
            "QUEUE_SEC_PER_CREDIT": 12.5,
            "REMOTE_SPILL_GB_PER_CREDIT": 1.2,
            "METERED_CREDITS": 19,
        }])
        with (
            patch.object(queue.st, "session_state", {"active_company": "Trexis", "global_environment": "PROD"}),
            patch.object(queue.st, "success"),
            patch.object(queue.st, "info"),
            patch.object(queue.st, "error"),
            patch.object(queue, "upsert_actions", side_effect=_upsert),
            patch.object(queue, "make_action_id", return_value="EFF-1"),
        ):
            queue._queue_efficiency_findings(object(), findings)

        action = captured["actions"][0]
        self.assertEqual(action["Company"], "Trexis")
        self.assertEqual(action["Environment"], "PROD")
        self.assertEqual(action["Category"], "Warehouse Efficiency")
        self.assertIn("Warehouse Settings Manager", action["Action"])
        self.assertIn("Do not execute warehouse changes", action["Generated SQL Fix"])
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", action["Telemetry Query"])
        self.assertTrue(action["Reviewer"])
        self.assertTrue(action["Route"])
        self.assertTrue(action["Route Basis"])
        self.assertIn("Closure uses queue/spill/credit telemetry", action["Recovery Status"])

    def test_render_capacity_brief_preserves_load_save_download_keys_and_session_writes(self):
        from sections import warehouse_health_panels as panels

        session_state: dict = {}
        button_keys: list[str] = []
        download_keys: list[str] = []
        summary = pd.DataFrame([{
            "QUEUED_QUERIES": 0,
            "SPILL_QUERIES": 0,
            "HIGH_LATENCY_QUERIES": 0,
            "TOTAL_QUERIES": 10,
            "CREDIT_SPIKE_PCT": 0,
            "METERED_CREDITS": 1.5,
            "REMOTE_SPILL_GB": 0,
        }])

        def _button(_label, *, key, **_kwargs):
            button_keys.append(key)
            return key == "wh_capacity_load"

        def _download_button(_label, _data, *, file_name, mime, key):
            download_keys.append(key)
            return False

        class _LoadStatus:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with (
            patch.object(panels.st, "session_state", session_state),
            patch.object(panels.st, "expander", return_value=_Context()),
            patch.object(panels.st, "button", side_effect=_button),
            patch.object(panels.st, "download_button", side_effect=_download_button),
            patch.object(panels.st, "success"),
            patch.object(panels.st, "info"),
            patch.object(panels.st, "warning"),
            patch.object(panels.st, "error"),
            patch.object(panels, "day_window_selectbox", return_value=7),
            patch.object(panels, "render_load_status", return_value=_LoadStatus()),
            patch.object(panels, "_warehouse_action_session", return_value=object()),
            patch.object(panels, "_build_warehouse_capacity_sql", return_value=("summary sql", "exceptions sql")),
            patch.object(panels, "run_query", side_effect=[summary, pd.DataFrame(), pd.DataFrame()]),
            patch.object(panels, "_warehouse_operability_fact_sql", return_value="operability sql"),
            patch.object(panels, "render_shell_snapshot"),
            patch.object(panels, "render_priority_dataframe"),
            patch.object(panels, "_render_warehouse_watch_floor"),
        ):
            panels._render_capacity_brief("ALFA", "PROD")

        self.assertIn("wh_capacity_load", button_keys)
        self.assertIn("wh_capacity_download", download_keys)
        self.assertIs(session_state["wh_capacity_summary"], summary)
        self.assertEqual(session_state["wh_capacity_sql"], {"summary": "summary sql", "exceptions": "exceptions sql"})
        self.assertEqual(session_state["wh_capacity_meta"]["company"], "ALFA")
        self.assertEqual(session_state["wh_capacity_meta"]["environment"], "PROD")
        self.assertEqual(session_state["wh_capacity_meta"]["days"], 7)
        self.assertIn("global_warehouse", session_state["wh_capacity_meta"])
        self.assertEqual(session_state["wh_operability_fact_sql"], "operability sql")
        self.assertIn("wh_operability_fact", session_state)

    def test_render_capacity_brief_preserves_review_and_queue_button_keys(self):
        from sections import warehouse_health_panels as panels

        button_keys: list[str] = []
        session_state = {
            "wh_capacity_summary": pd.DataFrame([{
                "QUEUED_QUERIES": 2,
                "SPILL_QUERIES": 1,
                "HIGH_LATENCY_QUERIES": 1,
                "TOTAL_QUERIES": 20,
                "CREDIT_SPIKE_PCT": 30,
                "METERED_CREDITS": 10,
                "REMOTE_SPILL_GB": 1,
            }]),
            "wh_capacity_exceptions": pd.DataFrame([{
                "SEVERITY": "High",
                "SIGNAL": "Credit Spike",
                "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
                "WAREHOUSE_SIZE": "XSMALL",
                "QUEUED_QUERIES": 2,
                "SPILL_QUERIES": 1,
                "HIGH_LATENCY_QUERIES": 1,
                "METERED_CREDITS": 10,
                "CAPACITY_SCORE": 65,
            }]),
            "wh_capacity_meta": {"company": "ALFA", "environment": "PROD", "days": 7},
            "wh_operability_fact": pd.DataFrame(),
        }

        def _button(_label, *, key, **_kwargs):
            button_keys.append(key)
            return False

        def _columns(spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [_Context() for _ in range(count)]

        with (
            patch.object(panels.st, "session_state", session_state),
            patch.object(panels.st, "expander", return_value=_Context()),
            patch.object(panels.st, "button", side_effect=_button),
            patch.object(panels.st, "download_button"),
            patch.object(panels.st, "columns", side_effect=_columns),
            patch.object(panels.st, "divider"),
            patch.object(panels.st, "success"),
            patch.object(panels.st, "info"),
            patch.object(panels.st, "warning"),
            patch.object(panels.st, "error"),
            patch.object(panels, "day_window_selectbox", return_value=7),
            patch.object(panels, "render_shell_snapshot"),
            patch.object(panels, "render_priority_dataframe"),
            patch.object(panels, "_render_warehouse_watch_floor"),
            patch.object(panels, "defer_source_note"),
        ):
            panels._render_capacity_brief("ALFA", "PROD")

        for key in [
            "wh_capacity_load",
            "wh_setting_execution_audit_load",
            "wh_setting_review_snapshot",
            "wh_setting_review_trend_load",
            "wh_action_closure_load",
            "wh_capacity_queue",
        ]:
            self.assertIn(key, button_keys)

    def test_render_warehouse_source_health_preserves_priority_columns(self):
        from sections import warehouse_health_panels as panels

        source_health = pd.DataFrame([{
            "SURFACE": "Overview",
            "STATE": "Loaded",
            "SOURCE": "Fast summary",
            "CONFIDENCE": "Fast summary",
            "ROWS": 3,
            "SCOPE": "ALFA/PROD",
            "NEXT_ACTION": "Review",
            "STATE_RANK": 0,
        }])
        captured: dict = {}

        def _render_priority_dataframe(frame, **kwargs):
            captured["frame"] = frame
            captured["kwargs"] = kwargs

        with (
            patch.object(panels.st, "session_state", {}),
            patch.object(panels.st, "expander", return_value=_Context()),
            patch.object(panels, "_warehouse_source_health_rows", return_value=source_health),
            patch.object(panels, "render_shell_snapshot"),
            patch.object(panels, "defer_source_note"),
            patch.object(panels, "render_priority_dataframe", side_effect=_render_priority_dataframe),
        ):
            panels._render_warehouse_source_health("ALFA", "PROD")

        self.assertEqual(captured["kwargs"]["title"], "Warehouse telemetry source and freshness")
        self.assertEqual(
            captured["kwargs"]["priority_columns"],
            ["SURFACE", "STATE", "SOURCE", "CONFIDENCE", "ROWS", "SCOPE", "NEXT_ACTION"],
        )
        self.assertEqual(captured["kwargs"]["sort_by"], ["STATE_RANK", "SURFACE"])

    def test_load_warehouse_overview_writes_same_session_keys(self):
        from sections import warehouse_health_view_overview as overview

        session_state: dict = {}
        data = pd.DataFrame([{"WAREHOUSE_NAME": "WH_ALFA_OVERWATCH"}])
        inventory = pd.DataFrame([{"NAME": "WH_ALFA_OVERWATCH"}])

        with (
            patch.object(overview.st, "session_state", session_state),
            patch.object(overview, "_warehouse_action_session", return_value=object()),
            patch.object(
                overview,
                "load_shared_warehouse_overview",
                return_value=SimpleNamespace(data=data, source="Fast warehouse summary"),
            ),
            patch.object(overview, "load_warehouse_inventory", return_value=inventory),
        ):
            overview._load_warehouse_overview("ALFA", "PROD", 7)

        self.assertIs(session_state["wh_df_wh"], data)
        self.assertEqual(session_state["wh_df_wh_source"], "Fast warehouse summary")
        self.assertEqual(session_state["wh_df_wh_meta"]["company"], "ALFA")
        self.assertEqual(session_state["wh_df_wh_meta"]["environment"], "PROD")
        self.assertEqual(session_state["wh_df_wh_meta"]["days"], 7)
        self.assertIs(session_state["wh_settings_inventory"], inventory)
        self.assertEqual(session_state["wh_settings_inventory_meta"]["company"], "ALFA")
        self.assertNotIn("wh_settings_inventory_error", session_state)

    def test_overview_renderer_preserves_buttons_charts_and_csv_contracts(self):
        from sections import warehouse_health_view_overview as overview

        session_state = {
            "warehouse_health_show_overview_evidence": True,
        }
        session_state["wh_df_wh_meta"] = overview._warehouse_scope_meta("ALFA", "PROD", 7, state=session_state)
        session_state["wh_settings_inventory_meta"] = overview._warehouse_scope_meta("ALFA", "PROD", 7, state=session_state)
        session_state["wh_scaling_meta"] = overview._warehouse_scope_meta("ALFA", "PROD", 7, state=session_state)
        session_state["wh_df_wh_source"] = "Fast warehouse summary"
        session_state["wh_df_wh"] = pd.DataFrame([{
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "WAREHOUSE_SIZE": "XSMALL",
            "TOTAL_QUERIES": 20,
            "TOTAL_REMOTE_SPILL_GB": 1.5,
            "AVG_QUEUED_SEC": 0.2,
            "AVG_ELAPSED_SEC": 2.0,
            "METERED_CREDITS": 4.0,
            "PRIOR_METERED_CREDITS": 3.0,
            "CREDIT_DELTA": 1.0,
            "CREDIT_DELTA_PCT": 33.3,
            "AVG_CACHE_PCT": 71.2,
            "P95_ELAPSED_SEC": 3.0,
        }])
        session_state["wh_settings_inventory"] = pd.DataFrame([{
            "NAME": "WH_ALFA_OVERWATCH",
            "AUTO_SUSPEND": 0,
            "RESOURCE_MONITOR": "",
            "STATEMENT_TIMEOUT_IN_SECONDS": 0,
            "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 0,
        }])
        session_state["wh_scaling_source"] = "SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY"
        session_state["wh_scaling"] = pd.DataFrame([{
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "WAREHOUSE_SIZE": "XSMALL",
            "START_TIME": "2026-06-01",
            "END_TIME": "2026-06-01",
            "CREDITS_USED": 1.0,
            "CREDITS_USED_COMPUTE": 0.9,
            "CREDITS_USED_CLOUD_SERVICES": 0.1,
        }])
        button_keys: list[str] = []
        chart_keys: list[str] = []
        downloads: list[str] = []

        def _button(_label, *, key, **_kwargs):
            button_keys.append(key)
            return False

        def _chart(_frame, **kwargs):
            chart_keys.append(kwargs["key"])

        def _download(_frame, file_name):
            downloads.append(file_name)

        with (
            patch.object(overview.st, "session_state", session_state),
            patch.object(overview.st, "subheader"),
            patch.object(overview.st, "button", side_effect=_button),
            patch.object(overview.st, "columns", return_value=[_Context(), _Context()]),
            patch.object(overview.st, "divider"),
            patch.object(overview, "day_window_selectbox", return_value=7),
            patch.object(overview, "render_data_freshness"),
            patch.object(overview, "render_shell_snapshot"),
            patch.object(overview, "defer_source_note"),
            patch.object(overview, "_render_warehouse_overview_exception_strip"),
            patch.object(overview, "render_priority_dataframe"),
            patch.object(overview, "_render_warehouse_setting_action_detail"),
            patch.object(overview, "_render_warehouse_cost_control_posture"),
            patch.object(overview, "render_drillable_bar_chart", side_effect=_chart),
            patch.object(overview, "download_csv", side_effect=_download),
        ):
            overview._render_warehouse_overview_view("ALFA", "PROD")

        for key in [
            "wh_load",
            "warehouse_health_hide_overview_evidence",
            "wh_scale_load",
        ]:
            self.assertIn(key, button_keys)
        self.assertIn("wh_cache_pct", chart_keys)
        for file_name in [
            "warehouse_guardrail_coverage.csv",
            "warehouse_setting_action_plan.csv",
            "warehouse_health.csv",
            "scaling_events.csv",
        ]:
            self.assertIn(file_name, downloads)

    def test_efficiency_renderer_preserves_keys_chart_and_download(self):
        from sections import warehouse_health_view_efficiency as efficiency

        session_state = {}
        session_state["wh_efficiency_meta"] = efficiency._warehouse_scope_meta("ALFA", "PROD", 7, state=session_state)
        session_state["wh_efficiency_source"] = "SNOWFLAKE.ACCOUNT_USAGE"
        session_state["wh_efficiency"] = pd.DataFrame([{
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "WAREHOUSE_SIZE": "XSMALL",
            "EFFICIENCY_SCORE": 48.0,
            "METERED_CREDITS": 12.0,
            "CREDITS_PER_QUERY": 0.2,
            "QUEUE_SEC_PER_CREDIT": 11.0,
            "REMOTE_SPILL_GB_PER_CREDIT": 0.4,
            "AVG_CACHE_PCT": 65.0,
        }])
        button_keys: list[str] = []
        chart_keys: list[str] = []
        downloads: list[str] = []

        def _button(_label, *, key, **_kwargs):
            button_keys.append(key)
            return False

        with (
            patch.object(efficiency.st, "session_state", session_state),
            patch.object(efficiency.st, "subheader"),
            patch.object(efficiency.st, "button", side_effect=_button),
            patch.object(efficiency, "day_window_selectbox", return_value=7),
            patch.object(efficiency, "render_shell_snapshot"),
            patch.object(efficiency, "defer_source_note"),
            patch.object(efficiency, "render_priority_dataframe"),
            patch.object(efficiency, "render_drillable_bar_chart", side_effect=lambda _frame, **kwargs: chart_keys.append(kwargs["key"])),
            patch.object(efficiency, "download_csv", side_effect=lambda _frame, file_name: downloads.append(file_name)),
        ):
            efficiency._render_warehouse_efficiency_view("ALFA", "PROD")

        self.assertIn("wh_eff_load", button_keys)
        self.assertIn("wh_eff_queue", button_keys)
        self.assertIn("wh_efficiency_review_priority", chart_keys)
        self.assertIn("warehouse_efficiency.csv", downloads)

    def test_spill_renderer_preserves_keys_chart_warning_and_download(self):
        from sections import warehouse_health_view_spill as spill

        session_state = {}
        session_state["wh_df_sp_meta"] = spill._warehouse_scope_meta("ALFA", "PROD", 7, state=session_state)
        session_state["wh_df_sp_source"] = "Live: SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY"
        session_state["wh_df_sp"] = pd.DataFrame([{
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "WAREHOUSE_SIZE": "XSMALL",
            "SPILL_QUERY_COUNT": 3,
            "LOCAL_SPILL_GB": 2.0,
            "REMOTE_SPILL_GB": 12.0,
            "AVG_ELAPSED_SEC": 33.0,
        }])
        button_keys: list[str] = []
        chart_keys: list[str] = []
        downloads: list[str] = []
        errors: list[str] = []

        with (
            patch.object(spill.st, "session_state", session_state),
            patch.object(spill.st, "subheader"),
            patch.object(spill.st, "button", side_effect=lambda _label, *, key, **_kwargs: button_keys.append(key) or False),
            patch.object(spill.st, "error", side_effect=lambda message: errors.append(message)),
            patch.object(spill, "day_window_selectbox", return_value=7),
            patch.object(spill, "render_shell_snapshot"),
            patch.object(spill, "defer_source_note"),
            patch.object(spill, "render_priority_dataframe"),
            patch.object(spill, "render_drillable_bar_chart", side_effect=lambda _frame, **kwargs: chart_keys.append(kwargs["key"])),
            patch.object(spill, "download_csv", side_effect=lambda _frame, file_name: downloads.append(file_name)),
        ):
            spill._render_warehouse_spill_view("ALFA", "PROD")

        self.assertIn("sp_load", button_keys)
        self.assertIn("wh_spill_total", chart_keys)
        self.assertIn("spill_report.csv", downloads)
        self.assertTrue(any("remote spill" in message for message in errors))

    def test_heatmap_renderer_preserves_keys_filters_and_day_name_pivot(self):
        from sections import warehouse_health_view_heatmap as heatmap

        rows = []
        for day in range(7):
            rows.append({
                "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
                "DAY_OF_WEEK": day,
                "HOUR_OF_DAY": 8,
                "QUERY_COUNT": day + 1,
                "AVG_ELAPSED_SEC": 2.5,
            })
        session_state = {}
        session_state["wh_df_hm_meta"] = heatmap._warehouse_scope_meta("ALFA", "PROD", 30, state=session_state)
        session_state["wh_df_hm_source"] = "Fast heatmap summary"
        session_state["wh_df_hm"] = pd.DataFrame(rows)
        button_keys: list[str] = []
        select_keys: list[str] = []
        captured: dict = {}

        def _dataframe(styler, **_kwargs):
            captured["pivot_index"] = list(styler.data.index)

        with (
            patch.object(heatmap.st, "session_state", session_state),
            patch.object(heatmap.st, "subheader"),
            patch.object(heatmap.st, "button", side_effect=lambda _label, *, key, **_kwargs: button_keys.append(key) or False),
            patch.object(heatmap.st, "selectbox", side_effect=lambda _label, options, *, key: select_keys.append(key) or options[0]),
            patch.object(heatmap.st, "dataframe", side_effect=_dataframe),
            patch.object(heatmap, "day_window_selectbox", return_value=30),
            patch.object(heatmap, "defer_source_note"),
            patch.object(heatmap, "render_shell_snapshot"),
        ):
            heatmap._render_warehouse_heatmap_view(
                "ALFA",
                "PROD",
                global_warehouse="COMPUTE",
                global_user="USER",
                global_role="ROLE",
                global_database="DB",
                global_start_date="2026-06-01",
                global_end_date="2026-06-22",
            )

        self.assertIn("hm_build", button_keys)
        self.assertIn("hm_wh_sel", select_keys)
        self.assertEqual(captured["pivot_index"], ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    def test_main_dispatch_routes_each_warehouse_view_to_moved_renderer(self):
        from sections import warehouse_health

        dispatch_cases = [
            ("Overview & Scaling", "_render_warehouse_overview_view"),
            ("Efficiency", "_render_warehouse_efficiency_view"),
            ("Spill & Memory", "_render_warehouse_spill_view"),
            ("Workload Heatmap", "_render_warehouse_heatmap_view"),
            ("Optimization Advisor", "_render_warehouse_advisor_view"),
        ]
        for view, target in dispatch_cases:
            with self.subTest(view=view):
                with (
                    patch.object(warehouse_health, "_render_warehouse_overview_view") as overview,
                    patch.object(warehouse_health, "_render_warehouse_efficiency_view") as efficiency,
                    patch.object(warehouse_health, "_render_warehouse_spill_view") as spill,
                    patch.object(warehouse_health, "_render_warehouse_heatmap_view") as heatmap,
                    patch.object(warehouse_health, "_render_warehouse_advisor_view") as advisor,
                ):
                    warehouse_health._render_selected_warehouse_health_view(
                        view,
                        "ALFA",
                        "PROD",
                        global_warehouse="COMPUTE",
                        global_user="USER",
                        global_role="ROLE",
                        global_database="DB",
                        global_start_date="2026-06-01",
                        global_end_date="2026-06-22",
                    )
                mocks = {
                    "_render_warehouse_overview_view": overview,
                    "_render_warehouse_efficiency_view": efficiency,
                    "_render_warehouse_spill_view": spill,
                    "_render_warehouse_heatmap_view": heatmap,
                    "_render_warehouse_advisor_view": advisor,
                }
                mocks[target].assert_called_once()
                self.assertEqual(sum(mock.call_count for mock in mocks.values()), 1)

    def test_warehouse_health_split_does_not_import_alert_facade(self):
        alert_facade_import = "utils" + ".alerts"
        for path in (
            APP_ROOT / "sections" / "warehouse_health.py",
            APP_ROOT / "sections" / "warehouse_health_actions.py",
            APP_ROOT / "sections" / "warehouse_health_capacity.py",
            APP_ROOT / "sections" / "warehouse_health_contracts.py",
            APP_ROOT / "sections" / "warehouse_health_dataframes.py",
            APP_ROOT / "sections" / "warehouse_health_helpers.py",
            APP_ROOT / "sections" / "warehouse_health_loader.py",
            APP_ROOT / "sections" / "warehouse_health_overview_panels.py",
            APP_ROOT / "sections" / "warehouse_health_panels.py",
            APP_ROOT / "sections" / "warehouse_health_queue.py",
            APP_ROOT / "sections" / "warehouse_health_rendering.py",
            APP_ROOT / "sections" / "warehouse_health_setting_panels.py",
            APP_ROOT / "sections" / "warehouse_health_sql.py",
            APP_ROOT / "sections" / "warehouse_health_view_advisor.py",
            APP_ROOT / "sections" / "warehouse_health_view_efficiency.py",
            APP_ROOT / "sections" / "warehouse_health_view_heatmap.py",
            APP_ROOT / "sections" / "warehouse_health_view_overview.py",
            APP_ROOT / "sections" / "warehouse_health_view_spill.py",
        ):
            with self.subTest(path=path.name):
                self.assertNotIn(alert_facade_import, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
