from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CortexTokenEfficiencyValidationTests(unittest.TestCase):
    def test_static_gate_proves_ratio_user_label_export_and_workbench_contracts(self):
        from tools.contracts.cortex_token_efficiency_validation import (
            build_cortex_token_efficiency_results,
            evaluate_cortex_token_efficiency_gate,
        )

        results = build_cortex_token_efficiency_results(ROOT)
        gate = evaluate_cortex_token_efficiency_gate(results)

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertTrue(gate["passed"], gate.get("failures"))
        self.assertEqual(results["cortex_token_metric_count"], 7)
        checks = {row["check"] for row in results["rows"]}
        self.assertIn("ranked_chart_recomputes_ratio_metrics", checks)
        self.assertIn("ranked_chart_groups_by_stable_key", checks)
        self.assertIn("cortex_efficiency_workbench_explicit_action", checks)
        self.assertIn("cortex_efficiency_exports_sanitized", checks)

    def test_fixture_live_gate_is_skipped_not_live_passed(self):
        from tools.contracts.cortex_token_efficiency_validation import (
            build_cortex_token_efficiency_live_results,
            evaluate_cortex_token_efficiency_live_gate,
        )

        live = build_cortex_token_efficiency_live_results(ROOT, "internal_fixture")
        gate = evaluate_cortex_token_efficiency_live_gate(live, "internal_fixture")

        self.assertTrue(gate["passed"])
        self.assertTrue(gate["live_skipped"])
        self.assertFalse(gate["live_executed"])
        self.assertFalse(gate["live_passed"])

    def test_internal_live_requires_live_or_waiver(self):
        from tools.contracts.cortex_token_efficiency_validation import (
            build_cortex_token_efficiency_live_results,
            evaluate_cortex_token_efficiency_live_gate,
        )

        live = build_cortex_token_efficiency_live_results(ROOT, "internal_live")
        gate = evaluate_cortex_token_efficiency_live_gate(live, "internal_live")

        self.assertFalse(gate["passed"])
        self.assertTrue(gate["live_required"])

    def test_launch_readiness_requires_cortex_token_efficiency_artifacts(self):
        from tools.contracts.cortex_token_efficiency_validation import (
            CORTEX_TOKEN_EFFICIENCY_GATE_REL,
            CORTEX_TOKEN_EFFICIENCY_LIVE_GATE_REL,
        )
        from tools.contracts.launch_readiness import REQUIRED_LAUNCH_READINESS_ARTIFACTS

        self.assertIn(CORTEX_TOKEN_EFFICIENCY_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        self.assertIn(CORTEX_TOKEN_EFFICIENCY_LIVE_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)


if __name__ == "__main__":
    unittest.main()
