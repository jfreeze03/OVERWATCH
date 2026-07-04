from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AccessControlRuntimeContractTests(unittest.TestCase):
    def test_runtime_probe_blocks_non_admin_session_open(self):
        from tools.contracts.access_control_runtime import evaluate_access_control_runtime

        first_paint = {
            "rows": [
                {
                    "section": section,
                    "workflow": "Overview",
                    "pre_first_paint_session_open_count": 0,
                    "shell_session_open_count": 0,
                    "active_session_probe_count": 0,
                    "admin_connection_test_count": 0,
                    "explicit_connection_test_count": 0,
                    "raw_sql_included": False,
                }
                for section in (
                    "Executive Landing",
                    "DBA Control Room",
                    "Alert Center",
                    "Cost & Contract",
                    "Workload Operations",
                    "Security Monitoring",
                )
            ]
        }

        results = evaluate_access_control_runtime(first_paint, root=ROOT)

        self.assertTrue(results["passed"], results.get("failures"))
        self.assertEqual(results["shell_session_open_count"], 0)
        self.assertEqual(results["active_session_probe_count"], 0)
        self.assertGreaterEqual(len(results["rows"]), 10)

    def test_missing_first_paint_telemetry_fails(self):
        from tools.contracts.access_control_runtime import evaluate_access_control_runtime

        results = evaluate_access_control_runtime({"rows": []}, root=ROOT)

        self.assertFalse(results["passed"])
        self.assertEqual(len([row for row in results["rows"] if not row["passed"]]), 6)


if __name__ == "__main__":
    unittest.main()
