import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_DIR = ROOT / ".overwatch_final"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class OperatorSimplificationTests(unittest.TestCase):
    def test_primary_navigation_has_exactly_four_operator_areas(self):
        from config import ALL_SECTIONS, SECTION_MODULES

        self.assertEqual(
            ALL_SECTIONS,
            ["COMMAND CENTER", "INCIDENTS", "OPTIMIZATION", "SETTINGS"],
        )
        self.assertEqual(
            SECTION_MODULES,
            {
                "COMMAND CENTER": "sections.command_center",
                "INCIDENTS": "sections.incidents",
                "OPTIMIZATION": "sections.optimization",
                "SETTINGS": "sections.operator_settings",
            },
        )

    def test_legacy_routes_redirect_to_operator_areas(self):
        from config import normalize_section_name

        self.assertEqual(normalize_section_name("Executive Landing"), "COMMAND CENTER")
        self.assertEqual(normalize_section_name("DBA Control Room"), "COMMAND CENTER")
        self.assertEqual(normalize_section_name("Alert Center"), "INCIDENTS")
        self.assertEqual(normalize_section_name("Workload Operations"), "INCIDENTS")
        self.assertEqual(normalize_section_name("Security Monitoring"), "INCIDENTS")
        self.assertEqual(normalize_section_name("Cost & Contract"), "OPTIMIZATION")
        self.assertEqual(normalize_section_name("Warehouse Health"), "OPTIMIZATION")
        self.assertEqual(normalize_section_name("Schema Compare"), "SETTINGS")

    def test_command_center_is_summary_first(self):
        text = (APP_DIR / "sections" / "command_center.py").read_text(encoding="utf-8")

        self.assertIn("load_operator_snapshot", text)
        self.assertNotIn("ACCOUNT_USAGE", text)
        self.assertNotIn("INFORMATION_SCHEMA", text)
        self.assertNotIn("Score formula", text)
        self.assertNotIn("Production readiness", text)
        self.assertNotIn("Value ledger", text)

    def test_settings_contains_moved_admin_tools(self):
        text = (APP_DIR / "sections" / "operator_settings.py").read_text(encoding="utf-8")

        for expected in (
            "Alert setup",
            "Suppression windows",
            "Schema and data compare",
            "Refresh diagnostics",
            "App observability",
            "Role readiness",
            "Mart validation",
        ):
            self.assertIn(expected, text)

    def test_incident_model_uses_simple_severities_and_categories(self):
        from utils.operator_model import CATEGORIES, SEVERITIES

        self.assertEqual(SEVERITIES, ("Critical", "Warning", "Info"))
        self.assertEqual(
            CATEGORIES,
            ("Cost", "Performance", "Security", "Pipeline", "Change", "Data Freshness"),
        )

    def test_retirement_script_is_review_only(self):
        script = (ROOT / "snowflake" / "OVERWATCH_DEPRECATED_OBJECT_RETIREMENT_DRAFT.sql").read_text(
            encoding="utf-8"
        )
        active_drops = [
            line for line in script.splitlines()
            if line.strip().upper().startswith("DROP ")
        ]
        self.assertEqual(active_drops, [])
        self.assertIn("review-only", script)


if __name__ == "__main__":
    unittest.main()

