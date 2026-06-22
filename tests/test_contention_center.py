from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections.contention_center import (  # noqa: E402
    _cleanup_contract_view,
    _decision_rows,
    _focus_handoff_frame,
    _incident_cockpit_view,
    _live_incident_rows,
    build_contention_solution_summary,
    build_contention_safe_action_contract,
    build_contention_top_fix_path,
    build_blocked_query_task_map_sql,
    build_live_query_incident_sql,
    build_live_task_graphs_sql,
    build_live_warehouse_load_sql,
    build_lock_wait_history_sql,
    build_long_dml_sql,
    build_table_hotspot_sql,
    build_task_overlap_sql,
    build_warehouse_pressure_sql,
)


class ContentionCenterTests(unittest.TestCase):
    def test_contention_sql_uses_snowflake_lock_task_and_queue_sources(self):
        lock_sql = build_lock_wait_history_sql(7).upper()
        hotspot_sql = build_table_hotspot_sql(7).upper()
        task_sql = build_task_overlap_sql(7).upper()
        dml_sql = build_long_dml_sql(7).upper()
        task_map_sql = build_blocked_query_task_map_sql(7).upper()
        wh_sql = build_warehouse_pressure_sql(1).upper()

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY", lock_sql)
        self.assertIn("WAITER_QUERY_ID", lock_sql)
        self.assertIn("BLOCKER_TRANSACTION_ID", lock_sql)
        self.assertIn("SERIALIZE FINAL WRITES", lock_sql)

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY", hotspot_sql)
        self.assertIn("TOTAL_WAIT_SECONDS", hotspot_sql)
        self.assertIn("HOT LOCKED OBJECT", hotspot_sql)

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY", task_sql)
        self.assertIn("OVERLAP_SECONDS", task_sql)
        self.assertIn("NO_OVERLAP", task_sql)

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", dml_sql)
        self.assertIn("TRANSACTION_BLOCKED_TIME", dml_sql)
        self.assertIn("QUEUED_OVERLOAD_TIME", dml_sql)
        self.assertIn("BATCH LARGE MERGE", dml_sql)

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", task_map_sql)
        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY", task_map_sql)
        self.assertIn("TRANSACTION_BLOCKED_TIME", task_map_sql)
        self.assertIn("TASK-OWNED BLOCKED WRITE", task_map_sql)
        self.assertIn("WAIT_OBJECTS", task_map_sql)

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY", wh_sql)
        self.assertIn("AVG_QUEUED_LOAD", wh_sql)
        self.assertIn("AVG_BLOCKED", wh_sql)

    def test_live_incident_sql_uses_read_only_current_sources(self):
        query_sql = build_live_query_incident_sql(30, "WH_TRXS_LOAD").upper()
        task_sql = build_live_task_graphs_sql("APP_DB.CORE.ROOT_TASK").upper()
        wh_live_sql = build_live_warehouse_load_sql(30, "WH_TRXS_LOAD").upper()
        wh_fallback_sql = build_live_warehouse_load_sql(30, "").upper()

        self.assertIn("INFORMATION_SCHEMA.QUERY_HISTORY", query_sql)
        self.assertIn("TRANSACTION_BLOCKED_TIME", query_sql)
        self.assertIn("QUEUED_OVERLOAD_TIME", query_sql)
        self.assertIn("WAREHOUSE_NAME = 'WH_TRXS_LOAD'", query_sql)

        self.assertIn("INFORMATION_SCHEMA.CURRENT_TASK_GRAPHS", task_sql)
        self.assertIn("ROOT_TASK_NAME = 'APP_DB.CORE.ROOT_TASK'", task_sql)

        self.assertIn("INFORMATION_SCHEMA.WAREHOUSE_LOAD_HISTORY", wh_live_sql)
        self.assertIn("WAREHOUSE_NAME => 'WH_TRXS_LOAD'", wh_live_sql)
        self.assertIn("DATEADD('MINUTE', -1, CURRENT_TIMESTAMP())", wh_live_sql)

        self.assertIn("SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY", wh_fallback_sql)
        self.assertIn("AVG_QUEUED_LOAD", wh_fallback_sql)
        self.assertNotIn("CREATE TABLE", query_sql + task_sql + wh_live_sql + wh_fallback_sql)

    def test_decision_rows_prioritize_contention_with_fix_guidance(self):
        decisions = _decision_rows(
            lock_waits=pd.DataFrame([{
                "SEVERITY": "Critical",
                "DATABASE_NAME": "APP_DB",
                "SCHEMA_NAME": "CORE",
                "OBJECT_NAME": "FACT_POLICY",
                "WAIT_SECONDS": 480,
                "WAITER_QUERY_ID": "01a",
                "BLOCKER_TRANSACTION_ID": "tx_blocker_123",
                "NEXT_ACTION": "Serialize final writes to FACT_POLICY.",
                "VERIFY_AFTER_FIX": "No waits remain.",
            }]),
            table_hotspots=pd.DataFrame([{
                "SEVERITY": "High",
                "DATABASE_NAME": "APP_DB",
                "SCHEMA_NAME": "CORE",
                "OBJECT_NAME": "FACT_POLICY",
                "WAIT_EVENTS": 4,
                "TOTAL_WAIT_SECONDS": 900,
                "BLOCKER_TRANSACTIONS": 2,
                "NEXT_ACTION": "Serialize the final publish.",
                "VERIFY_AFTER_FIX": "Object clears hotspot list.",
            }]),
            task_overlap=pd.DataFrame([{
                "SEVERITY": "High",
                "TASK_NAME": "LOAD_FACT_POLICY",
                "OVERLAP_SECONDS": 330,
                "RUN_1_QUERY_ID": "01b",
                "RUN_2_QUERY_ID": "01c",
                "NEXT_ACTION": "Set NO_OVERLAP.",
                "VERIFY_AFTER_FIX": "No overlapping windows.",
            }]),
            long_dml=pd.DataFrame([{
                "SEVERITY": "Medium",
                "ROOT_CAUSE": "Blocked DML",
                "QUERY_ID": "01d",
                "QUERY_TYPE": "MERGE",
                "ELAPSED_SECONDS": 1200,
                "BLOCKED_SECONDS": 90,
                "NEXT_ACTION": "Batch the merge.",
                "VERIFY_AFTER_FIX": "Blocked seconds clear.",
            }]),
            warehouse_pressure=pd.DataFrame(),
            task_mapping=pd.DataFrame([{
                "SEVERITY": "Critical",
                "ROOT_CAUSE": "Task-owned blocked write",
                "QUERY_ID": "01e",
                "TASK_NAME": "PUBLISH_FACT_POLICY",
                "BLOCKED_SECONDS": 420,
                "WAIT_OBJECTS": "APP_DB.CORE.FACT_POLICY",
                "NEXT_ACTION": "Open Pipeline & Task Health.",
                "VERIFY_AFTER_FIX": "No blocked task query.",
            }]),
        )

        self.assertFalse(decisions.empty)
        self.assertEqual(decisions.iloc[0]["SIGNAL"], "Lock wait")
        self.assertIn("FACT_POLICY", decisions.iloc[0]["ENTITY"])
        self.assertIn("Lock wait / blocked transaction", set(decisions["BOTTLENECK_TYPE"]))
        self.assertIn("Repeated table/object lock hotspot", set(decisions["BOTTLENECK_TYPE"]))
        self.assertIn("Task graph overlap / blocked task write", set(decisions["BOTTLENECK_TYPE"]))
        self.assertIn("Active Locks", set(decisions["OWNER_ROUTE"]))
        self.assertIn("Pipeline & Task Health", set(decisions["OWNER_ROUTE"]))
        self.assertIn("Serialize", " ".join(decisions["NEXT_ACTION"].astype(str)))
        self.assertIn("bigger warehouse", " ".join(decisions["COMPUTE_DECISION"].astype(str)).lower())
        self.assertIn("OVERLAP_POLICY = NO_OVERLAP", " ".join(decisions["SAFE_FIX"].astype(str)))
        self.assertIn("QUERY_HISTORY TRANSACTION_BLOCKED_TIME", " ".join(decisions["PROOF_REQUIRED"].astype(str)))
        self.assertIn("Hot locked object", set(decisions["SIGNAL"]))
        self.assertIn("Task-owned blocked write", set(decisions["SIGNAL"]))
        self.assertIn("CLEANUP_DECISION", decisions.columns)
        self.assertIn("CLEANUP_READINESS", decisions.columns)
        self.assertIn("PRECHECK_SQL", decisions.columns)
        self.assertIn("APPROVAL_GATE", decisions.columns)
        self.assertIn("AUDIT_EVIDENCE_REQUIRED", decisions.columns)
        self.assertIn("RECOVERY_PLAN", decisions.columns)
        self.assertIn("EXECUTION_BOUNDARY", decisions.columns)
        self.assertIn("SYSTEM$ABORT_TRANSACTION('tx_blocker_123')", " ".join(decisions["MANUAL_ACTION_SQL"].astype(str)))
        self.assertIn("LOCK_WAIT_HISTORY", " ".join(decisions["PRECHECK_SQL"].astype(str)))
        self.assertIn("RECENT_WAIT_EVENTS", " ".join(decisions["VERIFY_SQL"].astype(str)))
        self.assertIn("DBA-controlled action", " ".join(decisions["ACTION_GUARDRAIL"].astype(str)))
        self.assertIn("scheduler review", " ".join(decisions["APPROVAL_GATE"].astype(str)).lower())

        cockpit = _incident_cockpit_view(decisions)
        self.assertIn("BLOCKER", cockpit.columns)
        self.assertIn("WAITER", cockpit.columns)
        self.assertIn("LOCKED_OBJECT", cockpit.columns)
        self.assertIn("APPROVAL_GATE", cockpit.columns)
        self.assertIn("RECOVERY_PLAN", cockpit.columns)
        first = cockpit.iloc[0]
        self.assertEqual(first["BLOCKER"], "transaction tx_blocker_123")
        self.assertEqual(first["WAITER"], "query 01a")
        self.assertEqual(first["LOCKED_OBJECT"], "APP_DB.CORE.FACT_POLICY")
        self.assertIn("DBA on-call", first["INCIDENT_OWNER"])
        self.assertIn("Run the precheck", first["DECISION_GATE"])
        self.assertIn("VERIFY_SQL", cockpit.columns)

        top_path = build_contention_top_fix_path(decisions)
        self.assertEqual(top_path.iloc[0]["TOP_ROUTE"], "Active Locks")
        self.assertEqual(top_path.iloc[0]["TOP_SEVERITY"], "Critical")
        self.assertEqual(top_path.iloc[0]["BLOCKER"], "transaction tx_blocker_123")
        self.assertEqual(top_path.iloc[0]["MANUAL_SQL_STATE"], "Available after review")
        self.assertIn("LOCK_WAIT_HISTORY", top_path.iloc[0]["PRECHECK_SQL"])
        self.assertIn("RECENT_WAIT_EVENTS", top_path.iloc[0]["VERIFY_SQL"])

    def test_decision_rows_separate_warehouse_queueing_from_locks(self):
        decisions = _decision_rows(
            lock_waits=pd.DataFrame(),
            table_hotspots=pd.DataFrame(),
            task_overlap=pd.DataFrame(),
            long_dml=pd.DataFrame([{
                "SEVERITY": "Medium",
                "ROOT_CAUSE": "Long DML lock window",
                "QUERY_ID": "01long",
                "QUERY_TYPE": "MERGE",
                "ELAPSED_SECONDS": 1800,
                "BLOCKED_SECONDS": 0,
                "QUERY_TEXT": "MERGE INTO APP_DB.CORE.FACT_POLICY t USING STAGE s ON t.ID = s.ID",
                "NEXT_ACTION": "Shorten transaction scope.",
                "VERIFY_AFTER_FIX": "Shorter write window.",
            }]),
            warehouse_pressure=pd.DataFrame([{
                "SEVERITY": "Medium",
                "ROOT_CAUSE": "Warehouse queueing",
                "WAREHOUSE_NAME": "WH_TRXS_LOAD",
                "MAX_BLOCKED": 0,
                "MAX_QUEUED_LOAD": 3.2,
                "NEXT_ACTION": "Review multi-cluster.",
            }]),
            task_mapping=pd.DataFrame(),
        )

        by_signal = {row["SIGNAL"]: row for row in decisions.to_dict("records")}
        self.assertEqual(by_signal["Long DML lock window"]["OWNER_ROUTE"], "Query Investigation")
        self.assertEqual(by_signal["Long DML lock window"]["TARGET_OBJECT"], "APP_DB.CORE.FACT_POLICY")
        self.assertIn("batch", by_signal["Long DML lock window"]["SAFE_FIX"].lower())
        self.assertEqual(by_signal["Warehouse queueing"]["OWNER_ROUTE"], "Cost & Contract")
        self.assertIn("compute concurrency", by_signal["Warehouse queueing"]["COMPUTE_DECISION"])
        self.assertIn("AVG_QUEUED_LOAD", by_signal["Warehouse queueing"]["PROOF_REQUIRED"])
        self.assertEqual(by_signal["Warehouse queueing"]["CLEANUP_DECISION"], "No cancel - capacity review")
        self.assertEqual(by_signal["Warehouse queueing"]["MANUAL_ACTION_SQL"], "")

    def test_safe_action_contract_separates_abort_cancel_and_queueing(self):
        abort_contract = build_contention_safe_action_contract({
            "SIGNAL": "Lock wait",
            "BLOCKER_TRANSACTION_ID": "tx123",
            "TARGET_OBJECT": "APP_DB.CORE.FACT_POLICY",
            "BLOCKED_SECONDS": 180,
        })
        cancel_contract = build_contention_safe_action_contract({
            "SIGNAL": "Live blocked query",
            "QUERY_ID": "01blocked",
            "TARGET_OBJECT": "APP_DB.CORE.FACT_POLICY",
            "BLOCKED_SECONDS": 180,
        })
        queue_contract = build_contention_safe_action_contract({
            "SIGNAL": "Warehouse queueing",
            "OWNER_ROUTE": "Cost & Contract",
            "WAREHOUSE_NAME": "WH_TRXS_QUERY",
            "MAX_QUEUED_LOAD": 2.5,
        })

        self.assertEqual(abort_contract["CLEANUP_DECISION"], "Abort blocker transaction candidate")
        self.assertIn("SYSTEM$ABORT_TRANSACTION('tx123')", abort_contract["MANUAL_ACTION_SQL"])
        self.assertIn("still active", abort_contract["PRECHECKS"])
        self.assertIn("SHOW TRANSACTIONS IN ACCOUNT", abort_contract["PRECHECK_SQL"])
        self.assertIn("LOCK_WAIT_HISTORY", abort_contract["PRECHECK_SQL"])
        self.assertIn("RECENT_WAIT_EVENTS", abort_contract["VERIFY_SQL"])
        self.assertIn("SHOW LOCKS", abort_contract["VERIFY_AFTER_CLEANUP"])
        self.assertIn("incident ticket", abort_contract["APPROVAL_GATE"])
        self.assertIn("rollback impact", abort_contract["APPROVAL_GATE"])
        self.assertIn("post-action Query History", abort_contract["AUDIT_EVIDENCE_REQUIRED"])
        self.assertIn("Snowflake worksheet", abort_contract["EXECUTION_BOUNDARY"])
        self.assertIn("after review", abort_contract["EXECUTION_BOUNDARY"])

        self.assertEqual(cancel_contract["CLEANUP_DECISION"], "Cancel blocked query candidate")
        self.assertIn("SYSTEM$CANCEL_QUERY('01blocked')", cancel_contract["MANUAL_ACTION_SQL"])
        self.assertIn("does not release the blocker lock", cancel_contract["PRECHECKS"])
        self.assertIn("Query route", cancel_contract["APPROVAL_GATE"])
        self.assertIn("waiter or blocker", cancel_contract["APPROVAL_GATE"])
        self.assertIn("route retry/recovery", cancel_contract["RECOVERY_PLAN"])
        self.assertIn("QUERY_HISTORY", cancel_contract["PRECHECK_SQL"])
        self.assertIn("QUERY_ID = '01blocked'", cancel_contract["PRECHECK_SQL"])
        self.assertIn("LOCK_WAIT_HISTORY", cancel_contract["PRECHECK_SQL"])
        self.assertIn("QUERY_HISTORY", cancel_contract["VERIFY_SQL"])
        self.assertIn("RECENT_WAIT_EVENTS", cancel_contract["VERIFY_SQL"])
        self.assertIn("DBA-controlled action", cancel_contract["ACTION_GUARDRAIL"])

        self.assertEqual(queue_contract["CLEANUP_DECISION"], "No cancel - capacity review")
        self.assertEqual(queue_contract["MANUAL_ACTION_SQL"], "")
        self.assertIn("No cleanup SQL", queue_contract["APPROVAL_GATE"])
        self.assertIn("No cancel or abort SQL", queue_contract["EXECUTION_BOUNDARY"])
        self.assertIn("warehouse load history", queue_contract["AUDIT_EVIDENCE_REQUIRED"].lower())
        self.assertIn("WAREHOUSE_LOAD_HISTORY", queue_contract["PRECHECK_SQL"])
        self.assertIn("WAREHOUSE_NAME = 'WH_TRXS_QUERY'", queue_contract["PRECHECK_SQL"])
        self.assertIn("WAREHOUSE_LOAD_HISTORY", queue_contract["VERIFY_SQL"])
        self.assertIn("Do not cancel or abort", queue_contract["WHEN_NOT_TO_RUN"])

    def test_contention_solution_summary_routes_fix_paths(self):
        summary = build_contention_solution_summary(pd.DataFrame([
            {
                "SEVERITY": "Critical",
                "SIGNAL": "Lock wait",
                "BOTTLENECK_TYPE": "Lock wait / blocked transaction",
                "TARGET_OBJECT": "APP_DB.CORE.FACT_POLICY",
                "FIRST_MOVE": "Run blocker precheck SQL.",
                "PROOF_REQUIRED": "LOCK_WAIT_HISTORY",
                "OWNER_ROUTE": "Active Locks",
                "CLEANUP_DECISION": "Abort blocker transaction candidate",
            },
            {
                "SEVERITY": "High",
                "SIGNAL": "Task overlap",
                "BOTTLENECK_TYPE": "Task graph overlap / blocked task write",
                "ENTITY": "LOAD_FACT_POLICY",
                "FIRST_MOVE": "Set NO_OVERLAP.",
                "PROOF_REQUIRED": "TASK_HISTORY",
                "OWNER_ROUTE": "Pipeline & Task Health",
                "CLEANUP_DECISION": "Task schedule cleanup",
            },
            {
                "SEVERITY": "Medium",
                "SIGNAL": "Warehouse queueing",
                "BOTTLENECK_TYPE": "Warehouse compute pressure",
                "ENTITY": "WH_TRXS_LOAD",
                "FIRST_MOVE": "Review concurrency.",
                "PROOF_REQUIRED": "WAREHOUSE_LOAD_HISTORY",
                "OWNER_ROUTE": "Cost & Contract",
                "CLEANUP_DECISION": "No cancel - capacity review",
            },
        ]))

        self.assertIn("Clean up blocker", set(summary["SOLUTION_ROUTE"]))
        self.assertIn("Serialize task graph", set(summary["SOLUTION_ROUTE"]))
        self.assertIn("Fix warehouse pressure", set(summary["SOLUTION_ROUTE"]))
        blocker = summary[summary["SOLUTION_ROUTE"].eq("Clean up blocker")].iloc[0]
        self.assertEqual(blocker["TOP_SEVERITY"], "Critical")
        self.assertIn("FACT_POLICY", blocker["PRIMARY_ENTITY"])

    def test_cleanup_contract_view_surfaces_manual_guardrails(self):
        decisions = pd.DataFrame([{
            "SEVERITY": "Critical",
            "HANDOFF_MATCH": "Selected query",
            "SIGNAL": "Live blocked query",
            "ENTITY": "01blocked",
            "TARGET_OBJECT": "APP_DB.CORE.FACT_POLICY",
            "QUERY_ID": "01blocked",
            "WAREHOUSE_NAME": "WH_TRXS_LOAD",
            "CLEANUP_DECISION": "Cancel blocked query candidate",
            "CLEANUP_READINESS": "Ready for DBA review",
            "ACTION_GUARDRAIL": "DBA-controlled action; OVERWATCH does not auto-cancel from this view.",
            "PRECHECKS": "Confirm whether this query is the blocker or the waiter.",
            "PRECHECK_SQL": "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE QUERY_ID = '01blocked';",
            "MANUAL_ACTION_SQL": "SELECT SYSTEM$CANCEL_QUERY('01blocked');",
            "APPROVAL_GATE": "Query route review required.",
            "AUDIT_EVIDENCE_REQUIRED": "Save precheck, review status, action SQL, and result.",
            "RECOVERY_PLAN": "Watch blocker state and route retry to the escalation route.",
            "EXECUTION_BOUNDARY": "OVERWATCH displays reviewed action SQL only.",
            "WHEN_NOT_TO_RUN": "Do not cancel for pure warehouse queueing.",
            "VERIFY_AFTER_CLEANUP": "Query History should show the selected query canceled.",
            "VERIFY_SQL": "SELECT COUNT(*) AS RECENT_WAIT_EVENTS FROM SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY;",
            "UNRELATED": "hidden",
        }])

        contract = _cleanup_contract_view(decisions)

        self.assertIn("MANUAL_ACTION_SQL", contract.columns)
        self.assertIn("PRECHECKS", contract.columns)
        self.assertIn("PRECHECK_SQL", contract.columns)
        self.assertIn("APPROVAL_GATE", contract.columns)
        self.assertIn("AUDIT_EVIDENCE_REQUIRED", contract.columns)
        self.assertIn("RECOVERY_PLAN", contract.columns)
        self.assertIn("EXECUTION_BOUNDARY", contract.columns)
        self.assertIn("VERIFY_AFTER_CLEANUP", contract.columns)
        self.assertIn("VERIFY_SQL", contract.columns)
        self.assertNotIn("UNRELATED", contract.columns)
        self.assertIn("SYSTEM$CANCEL_QUERY", contract.iloc[0]["MANUAL_ACTION_SQL"])
        self.assertIn("QUERY_HISTORY", contract.iloc[0]["PRECHECK_SQL"])
        self.assertIn("RECENT_WAIT_EVENTS", contract.iloc[0]["VERIFY_SQL"])

    def test_cleanup_sql_is_display_only(self):
        text = (APP_ROOT / "sections" / "contention_center.py").read_text(encoding="utf-8")

        self.assertIn("DBA-controlled action", text)
        self.assertNotIn("run_query(row.get(\"MANUAL_ACTION_SQL\"", text)
        self.assertNotIn("run_query(contract.get(\"MANUAL_ACTION_SQL\"", text)
        self.assertNotIn("run_query(manual_sql", text)
        self.assertNotIn("session.sql(manual_sql", text)

    def test_handoff_focus_promotes_selected_query_rows(self):
        frame = pd.DataFrame([
            {
                "SEVERITY": "High",
                "SIGNAL": "Warehouse queueing",
                "QUERY_ID": "01queued",
                "EVIDENCE": "45 seconds queued",
            },
            {
                "SEVERITY": "Critical",
                "SIGNAL": "Lock wait",
                "WAITER_QUERY_ID": "01blocked",
                "EVIDENCE": "180 seconds blocked",
            },
            {
                "SEVERITY": "High",
                "SIGNAL": "Task overlap",
                "RUN_1_QUERY_ID": "01task",
                "RUN_2_QUERY_ID": "01blocked",
                "EVIDENCE": "overlap with blocked publish",
            },
        ])

        focused = _focus_handoff_frame(frame, "01blocked")

        self.assertEqual(list(focused["HANDOFF_MATCH"].head(2)), ["Selected query", "Selected query"])
        self.assertEqual(set(focused.head(2)["SIGNAL"]), {"Lock wait", "Task overlap"})
        self.assertEqual(focused.iloc[-1]["SIGNAL"], "Warehouse queueing")

    def test_live_incident_rows_rank_active_blockers_and_queueing(self):
        live_rows = _live_incident_rows(
            active_locks=pd.DataFrame([{
                "RESOURCE": "APP_DB.CORE.FACT_POLICY",
                "TRANSACTION": "tx123",
                "USER": "ETL_USER",
            }]),
            transactions=pd.DataFrame([{"ID": "tx123", "STATE": "RUNNING"}]),
            live_queries=pd.DataFrame([
                {
                    "QUERY_ID": "01blocked",
                    "ROOT_CAUSE": "Live blocked query",
                    "WAREHOUSE_NAME": "WH_TRXS_LOAD",
                    "ELAPSED_SECONDS": 620,
                    "BLOCKED_SECONDS": 180,
                    "QUEUED_OVERLOAD_SECONDS": 0,
                    "QUERY_TEXT": "MERGE INTO APP_DB.CORE.FACT_POLICY t USING STAGE s ON t.ID = s.ID",
                },
                {
                    "QUERY_ID": "01queued",
                    "ROOT_CAUSE": "Live warehouse queueing",
                    "WAREHOUSE_NAME": "WH_TRXS_QUERY",
                    "ELAPSED_SECONDS": 90,
                    "BLOCKED_SECONDS": 0,
                    "QUEUED_OVERLOAD_SECONDS": 45,
                },
            ]),
            task_graphs=pd.DataFrame([{
                "ROOT_TASK_NAME": "ROOT_LOAD_FACT_POLICY",
                "STATE": "EXECUTING",
                "GRAPH_RUN_GROUP_ID": "graph1",
            }]),
            warehouse_load=pd.DataFrame([{
                "WAREHOUSE_NAME": "WH_TRXS_QUERY",
                "AVG_BLOCKED": 0,
                "AVG_QUEUED_LOAD": 2.5,
            }]),
        )

        self.assertFalse(live_rows.empty)
        by_signal = {row["SIGNAL"]: row for row in live_rows.to_dict("records")}
        self.assertEqual(by_signal["Active lock"]["OWNER_ROUTE"], "Active Locks")
        self.assertEqual(by_signal["Live blocked query"]["OWNER_ROUTE"], "Active Locks")
        self.assertEqual(by_signal["Live blocked query"]["TARGET_OBJECT"], "APP_DB.CORE.FACT_POLICY")
        self.assertIn("transaction fix first", by_signal["Live blocked query"]["COMPUTE_DECISION"].lower())
        self.assertEqual(by_signal["Live warehouse queueing"]["OWNER_ROUTE"], "Cost & Contract")
        self.assertEqual(by_signal["Current task graph"]["OWNER_ROUTE"], "Pipeline & Task Health")
        self.assertIn("OVERLAP_POLICY = NO_OVERLAP", by_signal["Current task graph"]["SAFE_FIX"])
        self.assertIn("WAREHOUSE_LOAD_HISTORY", by_signal["Live warehouse pressure"]["PROOF_REQUIRED"])
        self.assertEqual(by_signal["Active lock"]["CLEANUP_DECISION"], "Abort active transaction candidate")
        self.assertIn("SYSTEM$ABORT_TRANSACTION('tx123')", by_signal["Active lock"]["MANUAL_ACTION_SQL"])
        self.assertIn("SHOW TRANSACTIONS IN ACCOUNT", by_signal["Active lock"]["PRECHECK_SQL"])
        self.assertIn("SHOW TRANSACTIONS IN ACCOUNT", by_signal["Active lock"]["VERIFY_SQL"])
        self.assertEqual(by_signal["Live warehouse queueing"]["MANUAL_ACTION_SQL"], "")
        self.assertIn("WAREHOUSE_LOAD_HISTORY", by_signal["Live warehouse queueing"]["PRECHECK_SQL"])
        self.assertIn("WAREHOUSE_LOAD_HISTORY", by_signal["Live warehouse queueing"]["VERIFY_SQL"])
        self.assertEqual(by_signal["Current task graph"]["CLEANUP_DECISION"], "Task schedule cleanup")

        cockpit = _incident_cockpit_view(live_rows)
        by_class = {row["INCIDENT_CLASS"]: row for row in cockpit.to_dict("records")}
        self.assertEqual(by_class["Active lock"]["BLOCKER"], "transaction tx123")
        self.assertIn("DBA on-call", by_class["Active lock"]["INCIDENT_OWNER"])
        self.assertEqual(by_class["Live warehouse queueing"]["BLOCKER"], "No blocker proven")
