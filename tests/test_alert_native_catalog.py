from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import alert_native_catalog  # noqa: E402
from utils import alerts  # noqa: E402


class AlertNativeCatalogTests(unittest.TestCase):
    def test_alerts_facade_reexports_native_catalog_functions(self):
        for name in (
            "build_alert_threshold_seed_rows",
            "build_alert_data_quality_check_seed_rows",
            "build_alert_data_quality_checks_ddl",
            "build_alert_native_object_registry_seed_rows",
            "build_alert_native_registry_ddl",
            "build_alert_remediation_policy_seed_rows",
            "build_alert_remediation_policy_ddl",
            "build_alert_native_deployment_review_rows",
            "build_alert_native_deployment_review_sql",
            "load_alert_native_object_registry",
            "load_alert_remediation_policy",
            "load_alert_remediation_dry_runs",
        ):
            self.assertIs(getattr(alerts, name), getattr(alert_native_catalog, name))

    def test_threshold_native_and_policy_seed_contracts(self):
        threshold_keys = {
            row["THRESHOLD_KEY"]
            for row in alerts.build_alert_threshold_seed_rows()
        }
        self.assertIn("COST_CORTEX_SPEND_SPIKE", threshold_keys)
        self.assertIn("PIPELINE_TASK_FAILURE", threshold_keys)

        native_rows = alerts.build_alert_native_object_registry_seed_rows()
        native_by_key = {row["REGISTRY_KEY"]: row for row in native_rows}
        self.assertIn("NATIVE_PIPELINE_TASK_FAILURE", native_by_key)
        self.assertFalse(native_by_key["NATIVE_PIPELINE_TASK_FAILURE"]["ENABLED_BY_DEFAULT"])
        self.assertIn("CREATE OR REPLACE ALERT", native_by_key["NATIVE_PIPELINE_TASK_FAILURE"]["GENERATED_CREATE_SQL"])
        self.assertIn("DROP ALERT IF EXISTS", native_by_key["NATIVE_PIPELINE_TASK_FAILURE"]["GENERATED_DROP_SQL"])

        policy_rows = alerts.build_alert_remediation_policy_seed_rows()
        policy_by_id = {row["POLICY_ID"]: row for row in policy_rows}
        self.assertIn("POLICY_TASK_RERUN_STATUS_REVIEW", policy_by_id)
        task_policy = policy_by_id["POLICY_TASK_RERUN_STATUS_REVIEW"]
        self.assertEqual(task_policy["REMEDIATION_MODE"], "STATUS_REVIEW")
        self.assertFalse(task_policy["AUTO_ELIGIBLE"])
        self.assertIn("EXECUTE TASK", task_policy["EXECUTION_SQL_TEMPLATE"])
        self.assertIn("TASK_HISTORY", task_policy["VERIFICATION_SQL"])

    def test_native_ddl_and_deployment_sql_are_review_only(self):
        dq_ddl = alerts.build_alert_data_quality_checks_ddl().upper()
        native_ddl = alerts.build_alert_native_registry_ddl().upper()
        policy_ddl = alerts.build_alert_remediation_policy_ddl().upper()
        deployment_sql = alerts.build_alert_native_deployment_review_sql().upper()

        self.assertIn("ALERT_DATA_QUALITY_CHECKS", dq_ddl)
        self.assertIn("ALERT_NATIVE_OBJECT_REGISTRY", native_ddl)
        self.assertIn("ALERT_REMEDIATION_POLICY", policy_ddl)
        self.assertIn("ALERT_REMEDIATION_DRY_RUN", policy_ddl)
        self.assertIn("ALERT_NATIVE_DEPLOYMENT_REVIEW_V", deployment_sql)
        self.assertIn("SP_OVERWATCH_STAGE_ALERT_REMEDIATION_DRY_RUN", deployment_sql)
        self.assertIn("THIS SCRIPT NEVER EXECUTES GENERATED_CREATE_SQL", deployment_sql)
        self.assertNotIn("EXECUTE IMMEDIATE GENERATED_CREATE_SQL", deployment_sql)
        self.assertNotIn("EXECUTE IMMEDIATE GENERATED_DROP_SQL", deployment_sql)

    def test_deployment_review_rows_block_enabled_by_default(self):
        rows = alerts.build_alert_native_deployment_review_rows(pd.DataFrame([{
            "STATUS": "APPROVED",
            "ENABLED_BY_DEFAULT": True,
            "CATEGORY": "Cost",
            "ALERT_KEY": "COST_TEST",
            "ALERT_OBJECT_NAME": "OVERWATCH_ALERT_TEST",
            "TARGET_ROUTE": "Cost & Contract",
            "WAREHOUSE_NAME": "WH_ALFA_OVERWATCH",
            "SCHEDULE_TEXT": "60 MINUTE",
            "GENERATED_CREATE_SQL": "CREATE OR REPLACE ALERT OVERWATCH_ALERT_TEST ...",
            "GENERATED_DROP_SQL": "DROP ALERT IF EXISTS OVERWATCH_ALERT_TEST;",
            "SAFETY_NOTE": "Unit safety note.",
        }]))

        row = rows.iloc[0].to_dict()
        self.assertEqual(row["DEPLOYMENT_STATE"], "BLOCKED_ENABLED_BY_DEFAULT")
        self.assertTrue(row["DEPLOYMENT_SQL_PRESENT"])
        self.assertTrue(row["ROLLBACK_SQL_PRESENT"])
        self.assertIn("ENABLED_BY_DEFAULT", row["DEPLOYMENT_NEXT_STEP"])

    def test_remediation_dry_run_loader_clamps_and_pads_columns(self):
        captured: dict[str, object] = {}

        def fake_run_query(sql, **kwargs):
            captured["sql"] = sql
            captured["kwargs"] = kwargs
            return pd.DataFrame([{
                "DRY_RUN_ID": 7,
                "POLICY_ID": "POLICY_TASK_RERUN_STATUS_REVIEW",
                "ALERT_KEY": "PIPELINE_TASK_FAILURE",
            }])

        with patch("utils.alert_native_catalog.run_query", side_effect=fake_run_query):
            result = alerts.load_alert_remediation_dry_runs(days=999, limit=5000, section="Alert Center")

        self.assertIn("DATEADD('day', -365", str(captured["sql"]))
        self.assertIn("LIMIT 1000", str(captured["sql"]))
        self.assertEqual(captured["kwargs"]["max_rows"], 1000)
        self.assertEqual(result.iloc[0]["DRY_RUN_ID"], 7)
        self.assertIn("VERIFICATION_SQL", result.columns)
        self.assertIn("BLOCKING_REASON", result.columns)


if __name__ == "__main__":
    unittest.main()
