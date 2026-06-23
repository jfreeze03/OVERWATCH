from pathlib import Path
from collections import Counter
import re
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import mart  # noqa: E402


MART_PUBLIC_SURFACE = {
    "core": (
        "MartResult",
        "mart_object_name",
        "load_mart_table",
        "mart_source_caption",
    ),
    "control-room": (
        "load_latest_control_room_mart",
        "build_mart_control_room_summary_sql",
        "build_mart_control_room_credits_sql",
        "build_mart_control_room_cost_drivers_sql",
        "build_mart_control_room_warehouse_pressure_sql",
        "build_mart_control_room_failed_queries_sql",
        "build_mart_control_room_failed_logins_sql",
        "build_mart_control_room_task_failures_sql",
    ),
    "account-health": (
        "build_mart_account_health_storage_sql",
        "build_mart_account_health_cost_drivers_sql",
        "build_mart_account_health_change_sql",
        "build_mart_account_health_failure_types_sql",
        "build_mart_account_health_long_queries_sql",
        "build_mart_account_health_credits_sql",
        "build_mart_account_health_failure_count_sql",
        "build_mart_account_health_top_driver_sql",
        "build_mart_account_health_queued_sql",
    ),
    "task-procedure": (
        "build_mart_task_history_sql",
        "build_mart_query_detail_recent_sql",
        "build_mart_procedure_inventory_sql",
        "build_mart_procedure_calls_sql",
        "build_mart_procedure_sla_sql",
    ),
    "service-health": (
        "build_mart_service_query_health_sql",
        "build_mart_service_warehouse_health_sql",
        "build_mart_service_login_health_sql",
        "build_mart_service_task_health_sql",
    ),
}


def _setup_sql() -> str:
    return (ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql").read_text(encoding="utf-8")


def _drop_sql() -> str:
    return (ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql").read_text(encoding="utf-8")


def _created_object_names(kind: str) -> list[str]:
    pattern = re.compile(
        rf"CREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:TRANSIENT|TEMPORARY|SECURE)\s+)?"
        rf"{kind}\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.$\"]+)",
        re.IGNORECASE,
    )
    names = []
    for match in pattern.finditer(_setup_sql()):
        raw = match.group(1).strip().strip('"')
        names.append(raw.split(".")[-1].upper())
    return names


class MartContractTests(unittest.TestCase):
    def test_mart_rationalization_doc_is_static_inventory(self):
        doc_path = ROOT / "docs" / "OVERWATCH_MART_LOAD_RATIONALIZATION.md"
        self.assertTrue(doc_path.exists())
        text = doc_path.read_text(encoding="utf-8")

        self.assertIn("No mart objects were dropped or disabled", text)
        for family in (
            "Executive first-paint summaries",
            "Core cost and spend facts",
            "Query and workload facts",
            "Security and access facts",
            "Storage and data movement facts",
            "Workflow operability facts",
            "Governance and evidence tables",
        ):
            with self.subTest(family=family):
                self.assertIn(family, text)

    def test_mart_setup_and_drop_contract_files_remain(self):
        setup_path = ROOT / "snowflake" / "OVERWATCH_MART_SETUP.sql"
        drop_path = ROOT / "snowflake" / "OVERWATCH_MART_DROP.sql"

        self.assertTrue(setup_path.exists())
        self.assertTrue(drop_path.exists())

        drop_text = drop_path.read_text(encoding="utf-8")
        self.assertIn("Drop every deployable object created by snowflake/OVERWATCH_MART_SETUP.sql", drop_text)
        self.assertIn("Run before rerunning OVERWATCH_MART_SETUP.sql", drop_text)

        doc_text = (ROOT / "docs" / "OVERWATCH_MART_LOAD_RATIONALIZATION.md").read_text(encoding="utf-8")
        self.assertIn("reset-only runbook tool", doc_text)
        self.assertIn("not a rationalization plan", doc_text)

    def test_mart_object_name_behavior_is_stable(self):
        self.assertEqual(
            mart.mart_object_name("FACT_QUERY_HOURLY"),
            "DBA_MAINT_DB.OVERWATCH.FACT_QUERY_HOURLY",
        )
        with self.assertRaises(ValueError):
            mart.mart_object_name("FACT_QUERY_HOURLY; DROP TABLE X")
        with self.assertRaises(ValueError):
            mart.mart_object_name("")

    def test_public_mart_builder_surface_still_exists(self):
        for group, names in MART_PUBLIC_SURFACE.items():
            for name in names:
                with self.subTest(group=group, name=name):
                    self.assertTrue(hasattr(mart, name))

    def test_representative_sql_builders_reference_expected_mart_objects(self):
        cases = {
            "build_mart_control_room_summary_sql": (
                lambda: mart.build_mart_control_room_summary_sql(24, "ALFA"),
                ("FACT_QUERY_DETAIL_RECENT",),
            ),
            "build_mart_control_room_credits_sql": (
                lambda: mart.build_mart_control_room_credits_sql(24, "ALFA"),
                ("FACT_WAREHOUSE_HOURLY",),
            ),
            "build_mart_control_room_cost_drivers_sql": (
                lambda: mart.build_mart_control_room_cost_drivers_sql(24, "ALFA"),
                ("FACT_QUERY_DETAIL_RECENT", "FACT_WAREHOUSE_HOURLY"),
            ),
            "build_mart_control_room_warehouse_pressure_sql": (
                lambda: mart.build_mart_control_room_warehouse_pressure_sql(24, "ALFA"),
                ("FACT_QUERY_DETAIL_RECENT",),
            ),
            "build_mart_control_room_failed_queries_sql": (
                lambda: mart.build_mart_control_room_failed_queries_sql(24, "ALFA"),
                ("FACT_QUERY_DETAIL_RECENT",),
            ),
            "build_mart_control_room_failed_logins_sql": (
                lambda: mart.build_mart_control_room_failed_logins_sql(24, "ALFA"),
                ("FACT_LOGIN_DAILY",),
            ),
            "build_mart_control_room_task_failures_sql": (
                lambda: mart.build_mart_control_room_task_failures_sql(24, "ALFA"),
                ("FACT_TASK_RUN",),
            ),
            "build_mart_account_health_storage_sql": (
                lambda: mart.build_mart_account_health_storage_sql("ALFA"),
                ("FACT_STORAGE_DAILY",),
            ),
            "build_mart_account_health_cost_drivers_sql": (
                lambda: mart.build_mart_account_health_cost_drivers_sql(24, "ALFA"),
                ("FACT_QUERY_DETAIL_RECENT", "FACT_WAREHOUSE_HOURLY"),
            ),
            "build_mart_account_health_change_sql": (
                lambda: mart.build_mart_account_health_change_sql(24, "ALFA"),
                ("FACT_QUERY_HOURLY", "FACT_WAREHOUSE_HOURLY"),
            ),
            "build_mart_account_health_failure_types_sql": (
                lambda: mart.build_mart_account_health_failure_types_sql(24, "ALFA"),
                ("FACT_QUERY_HOURLY",),
            ),
            "build_mart_account_health_long_queries_sql": (
                lambda: mart.build_mart_account_health_long_queries_sql(24, "ALFA"),
                ("FACT_QUERY_DETAIL_RECENT",),
            ),
            "build_mart_account_health_credits_sql": (
                lambda: mart.build_mart_account_health_credits_sql(24, "ALFA"),
                ("FACT_WAREHOUSE_HOURLY",),
            ),
            "build_mart_account_health_failure_count_sql": (
                lambda: mart.build_mart_account_health_failure_count_sql(24, "ALFA"),
                ("FACT_QUERY_HOURLY",),
            ),
            "build_mart_account_health_top_driver_sql": (
                lambda: mart.build_mart_account_health_top_driver_sql(24, "ALFA"),
                ("FACT_QUERY_DETAIL_RECENT", "FACT_WAREHOUSE_HOURLY"),
            ),
            "build_mart_account_health_queued_sql": (
                lambda: mart.build_mart_account_health_queued_sql(24, "ALFA"),
                ("FACT_QUERY_HOURLY",),
            ),
            "build_mart_task_history_sql": (
                lambda: mart.build_mart_task_history_sql(7, "ALFA"),
                ("FACT_TASK_RUN",),
            ),
            "build_mart_query_detail_recent_sql": (
                lambda: mart.build_mart_query_detail_recent_sql(["01a"]),
                ("FACT_QUERY_DETAIL_RECENT",),
            ),
            "build_mart_procedure_inventory_sql": (
                lambda: mart.build_mart_procedure_inventory_sql("ALFA"),
                ("DIM_PROCEDURE_SNAPSHOT",),
            ),
            "build_mart_procedure_calls_sql": (
                lambda: mart.build_mart_procedure_calls_sql(7, "ALFA"),
                ("FACT_PROCEDURE_RUN",),
            ),
            "build_mart_procedure_sla_sql": (
                lambda: mart.build_mart_procedure_sla_sql(7, "ALFA"),
                ("FACT_PROCEDURE_RUN",),
            ),
            "build_mart_service_query_health_sql": (
                lambda: mart.build_mart_service_query_health_sql(24, "ALFA"),
                ("FACT_QUERY_HOURLY",),
            ),
            "build_mart_service_warehouse_health_sql": (
                lambda: mart.build_mart_service_warehouse_health_sql(24, "ALFA"),
                ("FACT_QUERY_HOURLY",),
            ),
            "build_mart_service_login_health_sql": (
                lambda: mart.build_mart_service_login_health_sql(24, "ALFA"),
                ("FACT_LOGIN_DAILY",),
            ),
            "build_mart_service_task_health_sql": (
                lambda: mart.build_mart_service_task_health_sql(24, "ALFA"),
                ("FACT_TASK_RUN",),
            ),
        }

        for name, (builder, expected_objects) in cases.items():
            with self.subTest(builder=name):
                sql = builder()
                self.assertIsInstance(sql, str)
                self.assertTrue(sql.strip())
                for object_name in expected_objects:
                    self.assertIn(mart.mart_object_name(object_name), sql)

    def test_mart_source_caption_behavior_is_stable(self):
        available = mart.MartResult(data=pd.DataFrame({"A": [1]}), available=True, source="MART")
        empty = mart.MartResult(data=pd.DataFrame(), available=True, source="MART")
        unavailable = mart.MartResult(data=pd.DataFrame({"A": [1]}), available=False, source="MART")

        self.assertEqual(mart.mart_source_caption(available, "ACCOUNT_USAGE"), "Fast summary")
        self.assertEqual(mart.mart_source_caption(empty, "ACCOUNT_USAGE"), "ACCOUNT_USAGE")
        self.assertEqual(mart.mart_source_caption(unavailable, "ACCOUNT_USAGE"), "ACCOUNT_USAGE")

    def test_setup_sql_has_unique_table_names_and_core_facts(self):
        table_names = _created_object_names("TABLE")
        self.assertGreater(len(table_names), 50)
        duplicates = sorted(name for name, count in Counter(table_names).items() if count > 1)
        self.assertEqual(duplicates, [])

        for object_name in (
            "FACT_COST_DAILY",
            "FACT_QUERY_HOURLY",
            "FACT_QUERY_DETAIL_RECENT",
            "FACT_TASK_RUN",
            "FACT_STORAGE_DAILY",
            "FACT_LOGIN_DAILY",
            "FACT_GRANT_DAILY",
            "FACT_OBJECT_CHANGE",
        ):
            with self.subTest(object_name=object_name):
                self.assertIn(object_name, table_names)

    def test_setup_sql_contains_task_and_procedure_families_without_live_execution(self):
        self.assertGreater(len(_created_object_names("TASK")), 5)
        self.assertGreater(len(_created_object_names("PROCEDURE")), 5)

    def test_drop_sql_remains_reset_only_for_mart_families(self):
        drop_text = _drop_sql().upper()
        doc_text = (ROOT / "docs" / "OVERWATCH_MART_LOAD_RATIONALIZATION.md").read_text(encoding="utf-8")

        for object_name in (
            "FACT_COST_DAILY",
            "FACT_QUERY_HOURLY",
            "FACT_TASK_RUN",
            "FACT_STORAGE_DAILY",
            "FACT_LOGIN_DAILY",
        ):
            with self.subTest(object_name=object_name):
                self.assertIn(f"DROP TABLE IF EXISTS {object_name}", drop_text)
        self.assertIn("reset-only runbook tool", doc_text)
        self.assertIn("not a rationalization plan", doc_text)


if __name__ == "__main__":
    unittest.main()
