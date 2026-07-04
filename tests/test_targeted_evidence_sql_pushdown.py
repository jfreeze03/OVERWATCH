from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class TargetedEvidenceSqlPushdownTests(unittest.TestCase):
    def test_build_target_plan_metadata_marks_pushed_predicate(self):
        from sections.decision_workspace_target_filters import build_target_plan_metadata

        metadata = build_target_plan_metadata(
            "Security Monitoring",
            {"entity_type": "user_credential", "entity_id": "JANE.DOE"},
            available_columns=("USER_NAME", "CREDENTIAL_NAME"),
        )

        self.assertEqual(metadata["query_boundary"], "evidence_targeted")
        self.assertTrue(metadata["target_predicate_marker_required"])
        self.assertTrue(metadata["target_predicate_marker_present"])
        self.assertIn("USER_NAME", metadata["matched_columns"])
        self.assertFalse(metadata["raw_sql_included"])

    def test_required_pushdown_cases_pass(self):
        from tools.contracts.targeted_evidence_sql_pushdown import evaluate_targeted_evidence_sql_pushdown

        results = evaluate_targeted_evidence_sql_pushdown(ROOT)

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertEqual(results["target_pushdown_violation_count"], 0)
        self.assertGreaterEqual(results["required_case_count"], 6)


if __name__ == "__main__":
    unittest.main()
