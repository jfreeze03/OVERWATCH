from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class UserDisplaySurfaceAuditTests(unittest.TestCase):
    def test_surface_audit_covers_daily_user_surfaces_and_preserves_totals(self):
        from tools.contracts.user_display_surface_audit import build_user_display_surface_results

        results = build_user_display_surface_results(ROOT)

        self.assertTrue(results["passed"], results.get("failures"))
        surfaces = {row["surface"] for row in results["rows"]}
        for expected in (
            "Cortex Usage",
            "Cost Workbench",
            "Security credential expiration tile",
            "Security credential evidence",
            "Alert/action owner labels",
            "Security credential case payload",
        ):
            self.assertIn(expected, surfaces)
        for row in results["rows"]:
            self.assertIn("stable_user_key_column", row)
            self.assertIn("source_artifact", row)
            self.assertIn("total_value_before_label_join", row)
            self.assertIn("total_value_after_label_join", row)
            self.assertEqual(row["total_value_before_label_join"], row["total_value_after_label_join"])
            self.assertFalse(row["user_id_visible"] and not row["user_id_allowed"])


if __name__ == "__main__":
    unittest.main()
