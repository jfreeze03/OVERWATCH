from pathlib import Path
from collections import Counter
import inspect
import re
import sys
import unittest
from unittest.mock import Mock, patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import mart  # noqa: E402
from utils import mart_account_health  # noqa: E402
from utils import mart_adoption  # noqa: E402
from utils import mart_contracts  # noqa: E402
from utils import mart_control_room  # noqa: E402
from utils import mart_cost  # noqa: E402
from utils import mart_filters  # noqa: E402
from utils import mart_loader  # noqa: E402
from utils import mart_names  # noqa: E402
from utils import mart_recommendations  # noqa: E402
from utils import mart_service_health  # noqa: E402
from utils import mart_storage_pipeline  # noqa: E402
from utils import mart_task_procedure  # noqa: E402
from utils import mart_usage  # noqa: E402
from utils import mart_warehouse  # noqa: E402


MART_SQL_BUILDER_GROUPS = {
    "control-room": (
        "build_mart_control_room_summary_sql",
        "build_mart_control_room_credits_sql",
        "build_mart_control_room_cost_drivers_sql",
        "build_mart_control_room_warehouse_pressure_sql",
        "build_mart_control_room_failed_queries_sql",
        "build_mart_control_room_object_changes_sql",
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
        "build_mart_account_health_ytd_credits_sql",
    ),
    "cost": (
        "build_mart_bill_summary_sql",
        "build_mart_bill_warehouse_delta_sql",
        "build_mart_chargeback_sql",
        "build_mart_cost_explorer_sql",
        "build_mart_cost_cockpit_sql",
        "build_mart_cost_service_lens_sql",
        "build_mart_cost_run_rate_sql",
    ),
    "warehouse-health": (
        "build_mart_warehouse_overview_sql",
        "build_mart_warehouse_heatmap_sql",
        "build_mart_warehouse_scaling_sql",
    ),
    "usage": (
        "build_mart_usage_overview_sql",
        "build_mart_usage_metering_sql",
        "build_mart_usage_storage_sql",
        "build_mart_usage_pressure_sql",
        "build_mart_usage_cost_drivers_sql",
        "build_mart_usage_query_mix_sql",
        "build_mart_usage_database_adoption_sql",
    ),
    "adoption": (
        "build_mart_adoption_summary_sql",
        "build_mart_adoption_warehouse_size_sql",
        "build_mart_adoption_trend_sql",
        "build_mart_adoption_users_wh_sql",
        "build_mart_adoption_users_db_sql",
        "build_mart_adoption_role_type_sql",
    ),
    "storage": (
        "build_mart_storage_trend_sql",
        "build_mart_storage_db_detail_sql",
    ),
    "pipeline": (
        "build_mart_pipeline_freshness_sql",
        "build_mart_pipeline_load_failures_sql",
        "build_mart_pipeline_volume_sql",
    ),
    "recommendations": (
        "build_mart_recommendation_idle_sql",
        "build_mart_recommendation_spill_sql",
        "build_mart_recommendation_failed_tasks_sql",
        "build_mart_recommendation_query_errors_sql",
        "build_mart_query_bottleneck_sql",
        "build_mart_query_degradation_sql",
    ),
    "task-procedure": (
        "build_mart_task_inventory_sql",
        "build_mart_task_history_sql",
        "build_mart_task_critical_path_sql",
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

MART_PUBLIC_SURFACE = {
    "core": (
        "MartResult",
        "mart_object_name",
        "load_mart_table",
        "mart_source_caption",
    ),
    "control-room": (
        "load_latest_control_room_mart",
        *MART_SQL_BUILDER_GROUPS["control-room"],
    ),
    **{group: names for group, names in MART_SQL_BUILDER_GROUPS.items() if group != "control-room"},
}

MART_SQL_BUILDER_CASES = {
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
        ("FACT_WAREHOUSE_HOURLY", "FACT_QUERY_DETAIL_RECENT"),
    ),
    "build_mart_control_room_warehouse_pressure_sql": (
        lambda: mart.build_mart_control_room_warehouse_pressure_sql(24, "ALFA"),
        ("FACT_QUERY_DETAIL_RECENT",),
    ),
    "build_mart_control_room_failed_queries_sql": (
        lambda: mart.build_mart_control_room_failed_queries_sql(24, "ALFA"),
        ("FACT_QUERY_DETAIL_RECENT",),
    ),
    "build_mart_control_room_object_changes_sql": (
        lambda: mart.build_mart_control_room_object_changes_sql(24, "ALFA"),
        ("FACT_OBJECT_CHANGE",),
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
        ("FACT_WAREHOUSE_HOURLY", "FACT_QUERY_DETAIL_RECENT"),
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
        ("FACT_WAREHOUSE_HOURLY", "FACT_QUERY_DETAIL_RECENT"),
    ),
    "build_mart_account_health_queued_sql": (
        lambda: mart.build_mart_account_health_queued_sql(24, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_account_health_ytd_credits_sql": (
        lambda: mart.build_mart_account_health_ytd_credits_sql("ALFA"),
        ("FACT_WAREHOUSE_HOURLY",),
    ),
    "build_mart_bill_summary_sql": (
        lambda: mart.build_mart_bill_summary_sql("2026-01-01", "2026-01-31", "2025-12-01", "2025-12-31", "ALFA", "WH"),
        ("FACT_WAREHOUSE_HOURLY",),
    ),
    "build_mart_bill_warehouse_delta_sql": (
        lambda: mart.build_mart_bill_warehouse_delta_sql(
            "2026-01-01",
            "2026-01-31",
            "2025-12-01",
            "2025-12-31",
            "ALFA",
            "WH",
        ),
        ("FACT_WAREHOUSE_HOURLY",),
    ),
    "build_mart_chargeback_sql": (
        lambda: mart.build_mart_chargeback_sql(30, "ALFA"),
        ("FACT_CHARGEBACK_DAILY",),
    ),
    "build_mart_cost_explorer_sql": (
        lambda: mart.build_mart_cost_explorer_sql(30, "ALFA"),
        ("FACT_CHARGEBACK_DAILY",),
    ),
    "build_mart_cost_cockpit_sql": (
        lambda: mart.build_mart_cost_cockpit_sql("ALFA", 7),
        ("FACT_WAREHOUSE_HOURLY",),
    ),
    "build_mart_cost_service_lens_sql": (
        lambda: mart.build_mart_cost_service_lens_sql(30, 2.0, 3.0),
        ("FACT_COST_DAILY",),
    ),
    "build_mart_cost_run_rate_sql": (
        lambda: mart.build_mart_cost_run_rate_sql("ALFA"),
        ("FACT_WAREHOUSE_HOURLY",),
    ),
    "build_mart_warehouse_overview_sql": (
        lambda: mart.build_mart_warehouse_overview_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY", "FACT_WAREHOUSE_HOURLY"),
    ),
    "build_mart_warehouse_heatmap_sql": (
        lambda: mart.build_mart_warehouse_heatmap_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_warehouse_scaling_sql": (
        lambda: mart.build_mart_warehouse_scaling_sql(30, "ALFA"),
        ("FACT_WAREHOUSE_HOURLY",),
    ),
    "build_mart_usage_overview_sql": (
        lambda: mart.build_mart_usage_overview_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_usage_metering_sql": (
        lambda: mart.build_mart_usage_metering_sql(30, "ALFA"),
        ("FACT_WAREHOUSE_HOURLY",),
    ),
    "build_mart_usage_storage_sql": (
        lambda: mart.build_mart_usage_storage_sql(30, "ALFA"),
        ("FACT_STORAGE_DAILY",),
    ),
    "build_mart_usage_pressure_sql": (
        lambda: mart.build_mart_usage_pressure_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_usage_cost_drivers_sql": (
        lambda: mart.build_mart_usage_cost_drivers_sql(30, "ALFA"),
        ("FACT_WAREHOUSE_HOURLY",),
    ),
    "build_mart_usage_query_mix_sql": (
        lambda: mart.build_mart_usage_query_mix_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_usage_database_adoption_sql": (
        lambda: mart.build_mart_usage_database_adoption_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_adoption_summary_sql": (
        lambda: mart.build_mart_adoption_summary_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_adoption_warehouse_size_sql": (
        lambda: mart.build_mart_adoption_warehouse_size_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_adoption_trend_sql": (
        lambda: mart.build_mart_adoption_trend_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_adoption_users_wh_sql": (
        lambda: mart.build_mart_adoption_users_wh_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_adoption_users_db_sql": (
        lambda: mart.build_mart_adoption_users_db_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_adoption_role_type_sql": (
        lambda: mart.build_mart_adoption_role_type_sql(30, "ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_storage_trend_sql": (
        lambda: mart.build_mart_storage_trend_sql(30, "ALFA"),
        ("FACT_STORAGE_DAILY",),
    ),
    "build_mart_storage_db_detail_sql": (
        lambda: mart.build_mart_storage_db_detail_sql("ALFA"),
        ("FACT_STORAGE_DAILY",),
    ),
    "build_mart_pipeline_freshness_sql": (
        lambda: mart.build_mart_pipeline_freshness_sql(24, "ALFA"),
        ("DIM_TABLE_SNAPSHOT",),
    ),
    "build_mart_pipeline_load_failures_sql": (
        lambda: mart.build_mart_pipeline_load_failures_sql(7, "ALFA"),
        ("FACT_COPY_LOAD_DAILY",),
    ),
    "build_mart_pipeline_volume_sql": (
        lambda: mart.build_mart_pipeline_volume_sql(1.5, "ALFA"),
        ("DIM_TABLE_SNAPSHOT",),
    ),
    "build_mart_recommendation_idle_sql": (
        lambda: mart.build_mart_recommendation_idle_sql("ALFA"),
        ("FACT_WAREHOUSE_HOURLY", "FACT_QUERY_HOURLY"),
    ),
    "build_mart_recommendation_spill_sql": (
        lambda: mart.build_mart_recommendation_spill_sql("ALFA"),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_recommendation_failed_tasks_sql": (
        lambda: mart.build_mart_recommendation_failed_tasks_sql("ALFA"),
        ("FACT_TASK_RUN",),
    ),
    "build_mart_recommendation_query_errors_sql": (
        lambda: mart.build_mart_recommendation_query_errors_sql("ALFA", 10),
        ("FACT_QUERY_HOURLY",),
    ),
    "build_mart_query_bottleneck_sql": (
        lambda: mart.build_mart_query_bottleneck_sql(30, 10000, "ALFA"),
        ("FACT_QUERY_DETAIL_RECENT",),
    ),
    "build_mart_query_degradation_sql": (
        lambda: mart.build_mart_query_degradation_sql("ALFA"),
        ("FACT_QUERY_DETAIL_RECENT",),
    ),
    "build_mart_task_inventory_sql": (
        lambda: mart.build_mart_task_inventory_sql("ALFA"),
        ("DIM_TASK_SNAPSHOT",),
    ),
    "build_mart_task_history_sql": (
        lambda: mart.build_mart_task_history_sql(7, "ALFA"),
        ("FACT_TASK_RUN",),
    ),
    "build_mart_task_critical_path_sql": (
        lambda: mart.build_mart_task_critical_path_sql(7, "ALFA"),
        ("FACT_TASK_CRITICAL_PATH",),
    ),
    "build_mart_query_detail_recent_sql": (
        lambda: mart.build_mart_query_detail_recent_sql(["01a", "02b"]),
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

    def test_mart_micro_split_reexports_preserve_identity(self):
        self.assertIs(mart.MartResult, mart_contracts.MartResult)
        self.assertIs(mart.mart_source_caption, mart_contracts.mart_source_caption)
        self.assertIs(mart.mart_object_name, mart_names.mart_object_name)
        self.assertIs(mart._mart_text_filter, mart_filters._mart_text_filter)
        self.assertIs(mart._mart_company_filter, mart_filters._mart_company_filter)
        self.assertIs(mart._mart_environment_column, mart_filters._mart_environment_column)
        self.assertIs(mart._mart_environment_filter, mart_filters._mart_environment_filter)
        self.assertIs(mart._mart_database_filter, mart_filters._mart_database_filter)
        self.assertIs(mart._mart_window_condition, mart_filters._mart_window_condition)
        self.assertIs(mart._mart_window_filter, mart_filters._mart_window_filter)
        self.assertIs(mart.load_mart_table, mart_loader.load_mart_table)
        self.assertIs(mart.load_latest_control_room_mart, mart_loader.load_latest_control_room_mart)

    def test_mart_sql_family_reexports_preserve_identity(self):
        focused_modules = {
            "control-room": mart_control_room,
            "account-health": mart_account_health,
            "cost": mart_cost,
            "warehouse-health": mart_warehouse,
            "usage": mart_usage,
            "adoption": mart_adoption,
            "storage": mart_storage_pipeline,
            "pipeline": mart_storage_pipeline,
            "recommendations": mart_recommendations,
            "service-health": mart_service_health,
            "task-procedure": mart_task_procedure,
        }
        for family, names in MART_SQL_BUILDER_GROUPS.items():
            for name in names:
                with self.subTest(family=family, name=name):
                    self.assertIs(getattr(mart, name), getattr(focused_modules[family], name))
        self.assertNotIn("load_latest_control_room_mart", mart_control_room.__all__)

    def test_mart_compatibility_all_exports_every_public_name(self):
        grouped = {name for names in MART_SQL_BUILDER_GROUPS.values() for name in names}
        for name in (*MART_PUBLIC_SURFACE["core"], "load_latest_control_room_mart", *grouped):
            with self.subTest(name=name):
                self.assertIn(name, mart.__all__)
                self.assertTrue(hasattr(mart, name))

        for name in mart.__all__:
            with self.subTest(export=name):
                self.assertTrue(hasattr(mart, name))

    def test_mart_compatibility_surface_is_now_loader_shell(self):
        source = (APP_ROOT / "utils" / "mart.py").read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 180)
        for fragment in (
            "def load_mart_table",
            "SELECT ",
            "FROM ",
            "run_query(",
            "def build_mart_bill_summary_sql",
            "def build_mart_warehouse_overview_sql",
            "def build_mart_usage_overview_sql",
            "def build_mart_adoption_summary_sql",
            "def build_mart_storage_trend_sql",
            "def build_mart_recommendation_idle_sql",
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)

    def test_mart_filter_helpers_preserve_behavior(self):
        self.assertEqual(mart._mart_text_filter("", ""), "")

        text_filter = mart._mart_text_filter("WAREHOUSE_NAME", "WH")
        self.assertIn("WAREHOUSE_NAME ILIKE", text_filter)
        self.assertIn("'WH'", text_filter)

        self.assertEqual(mart._mart_company_filter("ALL"), "")
        company_filter = mart._mart_company_filter("ALFA")
        self.assertIn("COMPANY", company_filter)
        self.assertIn("'ALFA'", company_filter)

        self.assertEqual(mart._mart_environment_column("DATABASE_NAME"), "ENVIRONMENT")
        self.assertEqual(mart._mart_environment_column("q.database_name"), "q.environment")

        with patch("utils.mart_filters.get_state", return_value="PROD"):
            database_filter = mart._mart_database_filter("DATABASE_NAME", "APP", "ALFA")
        self.assertIn("DATABASE_NAME ILIKE", database_filter)
        self.assertIn("UPPER(ENVIRONMENT)", database_filter)

        window_condition = mart._mart_window_condition(
            "HOUR_START",
            7,
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        self.assertIn("DATEADD('DAY', -7", window_condition)
        self.assertIn("2026-01-01 00:00:00", window_condition)
        self.assertIn("2026-01-31 00:00:00", window_condition)
        self.assertTrue(mart._mart_window_filter("HOUR_START", 7).startswith("AND "))

    def test_mart_micro_modules_stay_tiny_and_focused(self):
        contracts_source = (APP_ROOT / "utils" / "mart_contracts.py").read_text(encoding="utf-8")
        names_source = (APP_ROOT / "utils" / "mart_names.py").read_text(encoding="utf-8")
        filters_source = (APP_ROOT / "utils" / "mart_filters.py").read_text(encoding="utf-8")

        for fragment in ("SELECT ", "FROM ", "CREATE TABLE"):
            with self.subTest(module="mart_contracts", fragment=fragment):
                self.assertNotIn(fragment, contracts_source)
        for fragment in ("build_mart_", "SELECT ", "ACCOUNT_USAGE"):
            with self.subTest(module="mart_names", fragment=fragment):
                self.assertNotIn(fragment, names_source)
        for fragment in ("FACT_", "DIM_", "MART_DBA_CONTROL_ROOM"):
            with self.subTest(module="mart_filters", fragment=fragment):
                self.assertNotIn(fragment, filters_source)

    def test_public_mart_builder_surface_still_exists(self):
        for group, names in MART_PUBLIC_SURFACE.items():
            for name in names:
                with self.subTest(group=group, name=name):
                    self.assertTrue(hasattr(mart, name))

    def test_every_public_mart_sql_builder_is_grouped_exactly_once(self):
        grouped = [name for names in MART_SQL_BUILDER_GROUPS.values() for name in names]
        duplicates = sorted(name for name, count in Counter(grouped).items() if count > 1)
        self.assertEqual(duplicates, [])

        discovered = sorted(
            name
            for name, value in inspect.getmembers(mart, inspect.isfunction)
            if name.startswith("build_mart_") and name.endswith("_sql")
        )
        self.assertEqual(sorted(grouped), discovered)
        self.assertEqual(set(MART_SQL_BUILDER_CASES), set(discovered))

    def test_sql_builders_reference_expected_mart_objects_only(self):
        for name, (builder, expected_objects) in MART_SQL_BUILDER_CASES.items():
            with self.subTest(builder=name):
                sql = builder()
                self.assertIsInstance(sql, str)
                self.assertTrue(sql.strip())
                self.assertNotIn("SNOWFLAKE.ACCOUNT_USAGE", sql.upper())
                for object_name in expected_objects:
                    self.assertIn(mart.mart_object_name(object_name), sql)
                if "company" in inspect.signature(getattr(mart, name)).parameters:
                    self.assertIn("COMPANY", sql.upper())
                    self.assertIn("'ALFA'", sql)

    def test_query_detail_recent_builder_preserves_empty_id_behavior(self):
        self.assertEqual(mart.build_mart_query_detail_recent_sql([]), "")
        sql = mart.build_mart_query_detail_recent_sql(["01a'b"])
        self.assertIn(mart.mart_object_name("FACT_QUERY_DETAIL_RECENT"), sql)
        self.assertIn("'01a''b'", sql)

    def test_load_mart_table_reports_available_non_empty_results(self):
        df = pd.DataFrame({"A": [1]})
        with patch("utils.mart_loader.run_query", return_value=df) as run_query:
            result = mart.load_mart_table("FACT_QUERY_HOURLY", "SELECT 1", source_label="Fast source")

        self.assertTrue(result.available)
        self.assertIs(result.data, df)
        self.assertEqual(result.source, "Fast source")
        self.assertEqual(result.message, "")
        run_query.assert_called_once_with(
            "SELECT 1",
            ttl_key="mart_fact_query_hourly",
            tier="command_summary",
            section="Mart",
        )

    def test_load_mart_table_reports_empty_results_as_unavailable(self):
        df = pd.DataFrame()
        with patch("utils.mart_loader.run_query", return_value=df):
            result = mart.load_mart_table("FACT_QUERY_HOURLY", "SELECT 1")

        self.assertFalse(result.available)
        self.assertIs(result.data, df)
        self.assertEqual(result.source, mart.mart_object_name("FACT_QUERY_HOURLY"))
        self.assertEqual(result.message, "No summary rows returned.")

    def test_load_mart_table_reports_query_errors_without_raising(self):
        run_query = Mock(side_effect=RuntimeError("warehouse asleep"))
        with patch("utils.mart_loader.run_query", run_query):
            result = mart.load_mart_table("FACT_QUERY_HOURLY", "SELECT 1")

        self.assertFalse(result.available)
        self.assertTrue(result.data.empty)
        self.assertEqual(result.source, mart.mart_object_name("FACT_QUERY_HOURLY"))
        self.assertIn("warehouse asleep", result.message)

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
