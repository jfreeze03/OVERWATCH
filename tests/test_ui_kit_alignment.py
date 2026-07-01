from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class UiKitAlignmentTests(unittest.TestCase):
    def test_alignment_results_cover_all_primary_sections(self):
        from tools.contracts.ui_kit_alignment import PRIMARY_SECTION_FILES, build_ui_kit_alignment_results

        results = build_ui_kit_alignment_results(ROOT)

        self.assertTrue(results["passed"], results["failures"])
        self.assertEqual(results["command_brief_surface_count"], len(PRIMARY_SECTION_FILES))
        self.assertEqual(results["source_footer_leak_count"], 0)
        self.assertEqual(results["old_board_marker_count"], 0)
        self.assertTrue(results["credential_tile_rendered"])
        self.assertTrue(results["cortex_efficiency_rendered"])

    def test_alignment_gate_has_launch_summary_fields(self):
        from tools.contracts.ui_kit_alignment import build_ui_kit_alignment_results, evaluate_ui_kit_alignment_gate

        gate = evaluate_ui_kit_alignment_gate(build_ui_kit_alignment_results(ROOT))

        self.assertTrue(gate["passed"], gate["failures"])
        self.assertIn("command_brief_surface_count", gate)
        self.assertIn("source_footer_leak_count", gate)
        self.assertIn("evidence_autoload_violation_count", gate)
        self.assertFalse(gate["raw_sql_included"])

    def test_launch_readiness_requires_ui_kit_gate(self):
        from tools.contracts.launch_readiness import REQUIRED_LAUNCH_READINESS_ARTIFACTS
        from tools.contracts.full_app_gauntlet import REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS
        from tools.contracts.ui_kit_alignment import UI_KIT_ALIGNMENT_GATE_REL, UI_KIT_ALIGNMENT_REL

        self.assertIn(UI_KIT_ALIGNMENT_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(UI_KIT_ALIGNMENT_REL, REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS)


if __name__ == "__main__":
    unittest.main()
