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
        self.assertEqual(results["silent_scrub_count"], 0)
        self.assertEqual(results["duplicate_command_brief_count"], 0)
        self.assertEqual(results["old_board_marker_count"], 0)
        self.assertTrue(results["credential_tile_rendered"])
        self.assertTrue(results["cortex_efficiency_rendered"])
        self.assertTrue(results["renderer_uses_single_command_brief"])
        self.assertEqual(results["section_layout_passed_count"], len(PRIMARY_SECTION_FILES))
        for row in results["section_layout_rows"]:
            self.assertTrue(row["command_brief_present"], row)
            self.assertEqual(row["decision_workspace_marker_count"], 1, row)
            self.assertEqual(row["duplicate_command_brief_count"], 0, row)
            self.assertTrue(row["metric_row_present"], row)
            self.assertTrue(row["attention_panel_present"], row)
            self.assertTrue(row["change_panel_present"], row)
            self.assertTrue(row["action_panel_present"], row)
            self.assertTrue(row["evidence_cta_present"], row)
            self.assertTrue(row["data_trust_present"], row)
            self.assertEqual(row["raw_source_token_count"], 0)
            self.assertEqual(row["old_board_marker_count"], 0)

    def test_alignment_gate_has_launch_summary_fields(self):
        from tools.contracts.ui_kit_alignment import build_ui_kit_alignment_results, evaluate_ui_kit_alignment_gate

        gate = evaluate_ui_kit_alignment_gate(build_ui_kit_alignment_results(ROOT))

        self.assertTrue(gate["passed"], gate["failures"])
        self.assertIn("command_brief_surface_count", gate)
        self.assertIn("source_footer_leak_count", gate)
        self.assertIn("silent_scrub_count", gate)
        self.assertIn("duplicate_command_brief_count", gate)
        self.assertIn("evidence_autoload_violation_count", gate)
        self.assertTrue(gate["renderer_uses_single_command_brief"])
        self.assertIn("section_layout_passed_count", gate)
        self.assertFalse(gate["raw_sql_included"])

    def test_section_layout_contract_has_launch_gate(self):
        from tools.contracts.ui_kit_alignment import (
            build_section_layout_contract_results,
            evaluate_section_layout_contract_gate,
        )

        payload = build_section_layout_contract_results(ROOT)
        gate = evaluate_section_layout_contract_gate(payload)

        self.assertTrue(payload["passed"], payload["failures"])
        self.assertTrue(gate["passed"], gate["failures"])
        self.assertEqual(gate["command_brief_count"], len(payload["section_rows"]))
        self.assertEqual(gate["duplicate_command_brief_count"], 0)
        self.assertEqual(gate["raw_source_token_count"], 0)

    def test_source_safe_footer_contract_blocks_silent_scrub_and_raw_tokens(self):
        from tools.contracts.ui_kit_alignment import (
            build_source_safe_footer_results,
            evaluate_source_safe_footer_gate,
        )

        payload = build_source_safe_footer_results(ROOT)
        gate = evaluate_source_safe_footer_gate(payload)

        self.assertTrue(payload["passed"], payload["failures"])
        self.assertTrue(gate["passed"], gate["failures"])
        self.assertEqual(gate["source_footer_leak_count"], 0)
        self.assertEqual(gate["silent_scrub_count"], 0)
        self.assertGreater(gate["mapped_source_count"], 0)

    def test_launch_readiness_requires_ui_kit_gate(self):
        from tools.contracts.launch_readiness import REQUIRED_LAUNCH_READINESS_ARTIFACTS
        from tools.contracts.full_app_gauntlet import REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS
        from tools.contracts.ui_kit_alignment import (
            SECTION_LAYOUT_CONTRACT_GATE_REL,
            SECTION_LAYOUT_CONTRACT_REL,
            SOURCE_SAFE_FOOTER_GATE_REL,
            SOURCE_SAFE_FOOTER_REL,
            UI_KIT_ALIGNMENT_GATE_REL,
            UI_KIT_ALIGNMENT_REL,
        )

        self.assertIn(UI_KIT_ALIGNMENT_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(SECTION_LAYOUT_CONTRACT_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(SOURCE_SAFE_FOOTER_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(UI_KIT_ALIGNMENT_REL, REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS)
        self.assertIn(SECTION_LAYOUT_CONTRACT_REL, REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS)
        self.assertIn(SOURCE_SAFE_FOOTER_REL, REQUIRED_FULL_APP_GAUNTLET_ARTIFACTS)


if __name__ == "__main__":
    unittest.main()
