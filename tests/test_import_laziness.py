from pathlib import Path
import unittest
import tempfile


ROOT = Path(__file__).resolve().parents[1]


class ImportLazinessTests(unittest.TestCase):
    def test_current_root_modules_are_section_lazy(self):
        from tools.contracts.import_laziness import build_import_laziness_results

        results = build_import_laziness_results(ROOT)

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertEqual(results["top_level_section_import_count"], 0)
        self.assertEqual(results["top_level_query_import_count"], 0)
        self.assertEqual(results["top_level_account_usage_import_count"], 0)

    def test_top_level_section_import_fails(self):
        from tools.contracts.import_laziness import ROOT_MODULES, build_import_laziness_results

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_root = root / ".overwatch_final"
            app_root.mkdir()
            for module_name in ROOT_MODULES:
                (app_root / module_name).write_text("# lazy root\n", encoding="utf-8")
            (app_root / "layout.py").write_text(
                "from sections.decision_workspace_setup_health import render_decision_setup_health_panel\n",
                encoding="utf-8",
            )

            results = build_import_laziness_results(root)

        self.assertFalse(results["passed"])
        self.assertEqual(results["top_level_section_import_count"], 1)
        self.assertTrue(any(failure["module"] == "layout.py" for failure in results["failures"]))

    def test_missing_artifact_fails_gate(self):
        from tools.contracts.import_laziness import evaluate_import_laziness_gate

        gate = evaluate_import_laziness_gate({})

        self.assertFalse(gate["passed"])
        self.assertEqual(gate["failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
