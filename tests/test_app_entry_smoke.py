from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AppEntrySmokeTests(unittest.TestCase):
    def test_app_entry_smoke_proves_lazy_import_and_main_execution(self):
        from tools.contracts.app_entry_smoke import build_app_entry_smoke_results, evaluate_app_entry_smoke_gate

        results = build_app_entry_smoke_results(ROOT)
        gate = evaluate_app_entry_smoke_gate(results)

        self.assertTrue(results["passed"], results)
        self.assertTrue(gate["passed"], gate)
        checks = {row["check"]: row for row in results["rows"]}
        self.assertIn("module_import_lazy", checks)
        self.assertIn("streamlit_style_main_execution", checks)
        self.assertFalse(checks["module_import_lazy"]["imported_streamlit"])
        self.assertFalse(checks["module_import_lazy"]["imported_shell"])
        self.assertEqual(checks["module_import_lazy"]["imported_section_modules"], [])
        self.assertEqual(checks["module_import_lazy"]["imported_query_modules"], [])
        self.assertFalse(checks["module_import_lazy"]["imported_pandas"])
        self.assertEqual(checks["streamlit_style_main_execution"]["set_page_config_count"], 1)
        self.assertEqual(checks["streamlit_style_main_execution"]["render_app_count"], 1)
        self.assertEqual(checks["streamlit_style_main_execution"]["record_app_entry_timing_count"], 1)
        self.assertEqual(checks["streamlit_style_main_execution"]["timing_arg_count"], 9)

    def test_missing_app_entry_smoke_results_fail_gate(self):
        from tools.contracts.app_entry_smoke import evaluate_app_entry_smoke_gate

        gate = evaluate_app_entry_smoke_gate({})

        self.assertFalse(gate["passed"])
        self.assertGreater(gate["failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
