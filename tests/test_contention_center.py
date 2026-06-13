from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections.contention_center import (  # noqa: E402
    _decision_rows,
    build_blocked_query_task_map_sql,
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

    def test_decision_rows_prioritize_contention_with_fix_guidance(self):
        decisions = _decision_rows(
            lock_waits=pd.DataFrame([{
                "SEVERITY": "Critical",
                "DATABASE_NAME": "APP_DB",
                "SCHEMA_NAME": "CORE",
                "OBJECT_NAME": "FACT_POLICY",
                "WAIT_SECONDS": 480,
                "WAITER_QUERY_ID": "01a",
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
                "NEXT_ACTION": "Open Task graphs.",
                "VERIFY_AFTER_FIX": "No blocked task query.",
            }]),
        )

        self.assertFalse(decisions.empty)
        self.assertEqual(decisions.iloc[0]["SIGNAL"], "Lock wait")
        self.assertIn("FACT_POLICY", decisions.iloc[0]["ENTITY"])
        self.assertIn("Serialize", " ".join(decisions["NEXT_ACTION"].astype(str)))
        self.assertIn("Hot locked object", set(decisions["SIGNAL"]))
        self.assertIn("Task-owned blocked write", set(decisions["SIGNAL"]))
