from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class UserStressTestTests(unittest.TestCase):
    def test_duplicate_summary_board_flag_fails(self):
        from tools.contracts.user_stress_test import build_user_stress_results, evaluate_user_stress_gate

        payload = [
            {"scenario": "rapid_section_switching", "passed": True, "duplicate_summary_board": True},
        ]
        results = build_user_stress_results(payload)
        gate = evaluate_user_stress_gate(results)

        self.assertFalse(results["passed"])
        self.assertFalse(gate["passed"])

    def test_full_existing_runtime_scenario_set_passes(self):
        from tools.contracts.user_stress_test import REQUIRED_STRESS_SCENARIOS, build_user_stress_results

        payload = [{"scenario": scenario, "passed": True, "elapsed_ms": 10, "elapsed_budget_ms": 100} for scenario in REQUIRED_STRESS_SCENARIOS]
        results = build_user_stress_results(payload)

        self.assertTrue(results["passed"], results)

