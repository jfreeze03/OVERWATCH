from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from sections import dba_tools  # noqa: E402
from sections import dba_tools_common as common  # noqa: E402
from sections import dba_tools_contracts as contracts  # noqa: E402
from sections import dba_tools_data_compare as data_compare  # noqa: E402
from sections import dba_tools_schema_compare as schema_compare  # noqa: E402
from sections import dba_tools_setup as setup  # noqa: E402
from sections import dba_tools_warehouse_settings as wh_settings  # noqa: E402


class DbaToolsSplitTests(unittest.TestCase):
    def test_facade_reexports_moved_helpers(self):
        self.assertIs(dba_tools.SCHEMA_COMPARE_OBJECT_COVERAGE, contracts.SCHEMA_COMPARE_OBJECT_COVERAGE)
        self.assertIs(dba_tools.DATA_COMPARE_EXECUTION_STAGES, contracts.DATA_COMPARE_EXECUTION_STAGES)
        self.assertIs(dba_tools._current_role_allows_alter_account, common._current_role_allows_alter_account)
        self.assertIs(dba_tools._quote_identifier, common._quote_identifier)
        self.assertIs(dba_tools._build_warehouse_setting_plan, wh_settings._build_warehouse_setting_plan)
        self.assertIs(dba_tools._schema_compare_show_objects_sql, schema_compare._schema_compare_show_objects_sql)
        self.assertIs(dba_tools._build_schema_compare_frame, schema_compare._build_schema_compare_frame)
        self.assertIs(dba_tools._data_compare_hash_sql, data_compare._data_compare_hash_sql)
        self.assertIs(dba_tools._setup_status_df, setup._setup_status_df)

    def test_role_gate_identifier_helpers_and_select_option_contracts(self):
        self.assertTrue(common._current_role_allows_alter_account("ACCOUNTADMIN"))
        self.assertTrue(common._current_role_allows_alter_account("snow_accountadmins"))
        self.assertFalse(common._current_role_allows_alter_account("SYSADMIN"))
        self.assertFalse(common._current_role_allows_alter_account(""))

        self.assertEqual(common._quote_identifier('A"B'), '"A""B"')
        self.assertEqual(common._qualified_name("DB", "PUBLIC", "A B"), '"DB"."PUBLIC"."A B"')

        previous = dict(st.session_state)
        try:
            st.session_state.clear()
            st.session_state["choice"] = "LEGACY"
            with patch.object(common.st, "selectbox", side_effect=lambda label, options, index, key: options[index]) as selectbox:
                self.assertEqual(common._select_option("Tool", ["A", "B"], "choice", fallback="A"), "LEGACY")
                self.assertEqual(list(selectbox.call_args.args[1]), ["LEGACY", "A", "B"])

            st.session_state["choice"] = "LEGACY"
            with patch.object(common.st, "selectbox", side_effect=lambda label, options, index, key: options[index]):
                self.assertEqual(
                    common._select_option(
                        "Tool",
                        ["A", "B"],
                        "choice",
                        fallback="A",
                        allow_current_outside_options=False,
                    ),
                    "A",
                )
                self.assertEqual(st.session_state["choice"], "A")
        finally:
            st.session_state.clear()
            st.session_state.update(previous)

    def test_warehouse_setting_normalization_risk_review_and_plan(self):
        self.assertEqual(wh_settings._warehouse_size_sql("XSMALL"), "XSMALL")
        self.assertEqual(wh_settings._warehouse_size_sql("2XLARGE"), "XXLARGE")
        self.assertEqual(wh_settings._warehouse_size_sql("4XLARGE"), "X4LARGE")
        self.assertEqual(wh_settings._normalize_warehouse_setting("AUTO_RESUME", "yes"), "TRUE")
        self.assertEqual(wh_settings._normalize_warehouse_setting("AUTO_RESUME", "no"), "FALSE")
        self.assertEqual(wh_settings._normalize_warehouse_setting("SCALING_POLICY", "economy"), "ECONOMY")
        self.assertEqual(wh_settings._normalize_warehouse_setting("MAX_CONCURRENCY_LEVEL", "12.0"), "12")

        risk_cases = {
            "WAREHOUSE_SIZE": ("WAREHOUSE_SIZE", "SMALL", "MEDIUM", "resizing"),
            "AUTO_SUSPEND_ZERO": ("AUTO_SUSPEND", "600", "0", "never auto-suspend"),
            "AUTO_SUSPEND_HIGH": ("AUTO_SUSPEND", "60", "900", "10-minute DBA guardrail"),
            "AUTO_RESUME": ("AUTO_RESUME", "TRUE", "FALSE", "Availability risk"),
            "MIN_CLUSTER_COUNT": ("MIN_CLUSTER_COUNT", "1", "2", "extra clusters"),
            "MAX_CLUSTER_COUNT": ("MAX_CLUSTER_COUNT", "1", "2", "multi-cluster"),
            "ENABLE_QUERY_ACCELERATION": ("ENABLE_QUERY_ACCELERATION", "FALSE", "TRUE", "Serverless cost"),
            "QUERY_ACCELERATION_MAX_SCALE_FACTOR": ("QUERY_ACCELERATION_MAX_SCALE_FACTOR", "8", "0", "unlimited"),
            "STATEMENT_TIMEOUT_IN_SECONDS": ("STATEMENT_TIMEOUT_IN_SECONDS", "3600", "0", "Runaway query"),
        }
        for _, values in risk_cases.items():
            with self.subTest(values=values):
                param, current, requested, expected = values
                self.assertIn(expected, wh_settings._warehouse_setting_risk(param, current, requested))

        self.assertEqual(
            wh_settings._warehouse_setting_review_gate("MAX_CLUSTER_COUNT", "1", "2")["REVIEW_GATE"],
            "Capacity control",
        )
        self.assertEqual(
            wh_settings._warehouse_setting_review_gate("AUTO_SUSPEND", "600", "60")["REVIEW_GATE"],
            "Availability/cost control",
        )

        plan = wh_settings._build_warehouse_setting_plan(
            "COMPUTE_WH",
            pd.Series({
                "size": "Small",
                "auto_suspend": 600,
                "auto_resume": "true",
                "max_cluster_count": 1,
                "enable_query_acceleration": "false",
                "max_concurrency_level": None,
            }),
            {
                "WAREHOUSE_SIZE": "Small",
                "AUTO_SUSPEND": 0,
                "AUTO_RESUME": False,
                "MAX_CLUSTER_COUNT": 2,
                "ENABLE_QUERY_ACCELERATION": True,
                "MAX_CONCURRENCY_LEVEL": 16,
            },
        )
        self.assertIn('ALTER WAREHOUSE "COMPUTE_WH" SET', plan["alter_sql"])
        self.assertNotIn("WAREHOUSE_SIZE", plan["alter_sql"])
        self.assertIn("AUTO_SUSPEND = 0", plan["alter_sql"])
        self.assertIn("AUTO_RESUME = FALSE", plan["alter_sql"])
        self.assertIn("MAX_CLUSTER_COUNT = 2", plan["alter_sql"])
        self.assertIn("ENABLE_QUERY_ACCELERATION = TRUE", plan["alter_sql"])
        self.assertIn("AUTO_SUSPEND = 600", plan["rollback_sql"])
        self.assertIn('SHOW GRANTS ON WAREHOUSE "COMPUTE_WH"', plan["preflight_sql"])
        self.assertEqual(plan["confirmation_text"], "ALTER COMPUTE_WH")
        self.assertEqual(plan["skipped_df"].iloc[0]["PARAMETER"], "MAX_CONCURRENCY_LEVEL")
        self.assertIn("REVIEW_GATE", plan["changes_df"].columns)
        self.assertIn("rollback SQL", plan["control_context"])

    def test_schema_compare_helpers_keep_compare_contracts(self):
        self.assertEqual(schema_compare._schema_compare_normalize_kind("BASE TABLE"), "TABLE")
        self.assertEqual(schema_compare._schema_compare_get_ddl_type("dynamic table"), "DYNAMIC_TABLE")
        self.assertEqual(schema_compare._schema_compare_get_ddl_type("stored procedure"), "PROCEDURE")

        objects = schema_compare._schema_compare_normalize_show_objects(
            pd.DataFrame([{"name": "POLICY_FACT", "kind": "BASE TABLE", "rows": 10, "bytes": 2048}]),
            database="SRC_DB",
            schema="PUBLIC",
            side="SOURCE",
        )
        self.assertEqual(objects.iloc[0]["OBJECT_TYPE"], "TABLE")
        self.assertEqual(objects.iloc[0]["SOURCE_SIDE"], "SOURCE")
        self.assertIn("OBJECT_SIGNATURE", objects.columns)

        columns = schema_compare._schema_compare_normalize_columns(
            pd.DataFrame([{
                "OBJECT_NAME": "POLICY_FACT.POLICY_ID",
                "PARENT_OBJECT_NAME": "POLICY_FACT",
                "PARENT_OBJECT_TYPE": "BASE TABLE",
                "DATA_TYPE": "NUMBER",
                "IS_NULLABLE": "NO",
                "ORDINAL_POSITION": 1,
                "OBJECT_SIGNATURE": "NUMBER nullable=NO",
            }]),
            database="SRC_DB",
            schema="PUBLIC",
            side="SOURCE",
        )
        self.assertEqual(columns.iloc[0]["OBJECT_TYPE"], "COLUMN")
        self.assertEqual(columns.iloc[0]["PARENT_OBJECT_TYPE"], "TABLE")

        source = schema_compare._schema_compare_inventory(objects, columns, database="SRC_DB", schema="PUBLIC", side="SOURCE")
        target = schema_compare._schema_compare_inventory(pd.DataFrame(), pd.DataFrame(), database="TGT_DB", schema="PUBLIC", side="TARGET")
        compare = schema_compare._build_schema_compare_frame(
            source,
            target,
            source_db="SRC_DB",
            source_schema="PUBLIC",
            target_db="TGT_DB",
            target_schema="PUBLIC",
        )
        self.assertIn("Only in source", set(compare["COMPARE_STATUS"]))
        self.assertIn("DDL_REVIEW_SQL", compare.columns)

    def test_data_compare_helpers_keep_sql_and_safety_contracts(self):
        self.assertEqual(data_compare._data_compare_where_clause("ID > 10"), "WHERE ID > 10")
        for unsafe in ("ID > 10; DROP TABLE X", "A = 1 -- comment", "/* comment */ A = 1", "CALL BAD_PROC()"):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    data_compare._data_compare_where_clause(unsafe)

        hash_sql = data_compare._data_compare_hash_sql("SRC_DB", "PUBLIC", "POLICY_FACT", ["POLICY_ID"])
        bucket_sql = data_compare._data_compare_bucket_sql(
            "SRC_DB", "PUBLIC", "TGT_DB", "PUBLIC", "POLICY_FACT", ["POLICY_ID"], key_columns=["POLICY_ID"]
        )
        forensic_sql = data_compare._data_compare_forensic_sql(
            "SRC_DB", "PUBLIC", "TGT_DB", "PUBLIC", "POLICY_FACT", ["POLICY_ID"], key_columns=["POLICY_ID"]
        )
        self.assertIn('HASH_AGG("POLICY_ID")', hash_sql)
        self.assertIn('MOD(ABS(HASH("POLICY_ID"))', bucket_sql)
        self.assertIn("FULL OUTER JOIN target_bucket", bucket_sql)
        self.assertIn("FULL OUTER JOIN target_rows", forensic_sql)
        self.assertIn("ROW_HASH_MISMATCH", forensic_sql)

        plan = data_compare._build_data_compare_plan(
            pd.DataFrame([{"TABLE_NAME": "POLICY_FACT", "TABLE_TYPE": "BASE TABLE", "METADATA_ROW_COUNT": 1}]),
            pd.DataFrame([{"TABLE_NAME": "POLICY_FACT", "TABLE_TYPE": "BASE TABLE", "METADATA_ROW_COUNT": 1}]),
            pd.DataFrame([{"OBJECT_NAME": "POLICY_FACT.SHAPE", "PARENT_OBJECT_NAME": "POLICY_FACT", "DATA_TYPE": "GEOGRAPHY"}]),
            pd.DataFrame([{"OBJECT_NAME": "POLICY_FACT.SHAPE", "PARENT_OBJECT_NAME": "POLICY_FACT", "DATA_TYPE": "GEOGRAPHY"}]),
        )
        self.assertEqual(plan.iloc[0]["COMPARE_STATUS"], "No comparable columns")
        self.assertEqual(plan.iloc[0]["UNSUPPORTED_HASH_COLUMNS"], "SHAPE")

    def test_setup_status_features_and_alert_import_guard(self):
        with patch.object(setup, "_table_exists", side_effect=[True, False, None]) as table_exists:
            with patch.object(setup, "_task_exists", return_value=True) as task_exists:
                status = setup._setup_status_df(object())

        self.assertEqual(
            list(status["FEATURE"]),
            ["Annotation Windows", "Alert History", "Action Queue", "Anomaly Alert Task"],
        )
        self.assertEqual(list(status["STATUS"]), ["Present", "Missing", "Unknown", "Present"])
        self.assertEqual(table_exists.call_count, 3)
        self.assertEqual(task_exists.call_count, 1)

        for path in APP_ROOT.joinpath("sections").glob("dba_tools*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("utils.alerts", text)


if __name__ == "__main__":
    unittest.main()
