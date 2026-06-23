from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
sys.path.insert(0, str(APP_ROOT))

from utils import mart  # noqa: E402


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

    def test_public_mart_builder_surface_still_exists(self):
        expected = (
            "MartResult",
            "mart_object_name",
            "load_mart_table",
            "load_latest_control_room_mart",
            "build_mart_control_room_summary_sql",
            "build_mart_cost_cockpit_sql",
            "build_mart_usage_overview_sql",
            "build_mart_warehouse_overview_sql",
            "build_mart_task_history_sql",
            "build_mart_service_query_health_sql",
            "mart_source_caption",
        )
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue(hasattr(mart, name))


if __name__ == "__main__":
    unittest.main()
