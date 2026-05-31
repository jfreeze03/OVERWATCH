import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCORECARDS = ROOT / ".overwatch_final" / "utils" / "scorecards.py"

spec = importlib.util.spec_from_file_location("scorecards_under_test", SCORECARDS)
scorecards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorecards)


class ScorecardTests(unittest.TestCase):
    def test_clamp_score_bounds_values(self):
        self.assertEqual(scorecards.clamp_score(-5), 0.0)
        self.assertEqual(scorecards.clamp_score(105), 100.0)
        self.assertEqual(scorecards.clamp_score(88.88), 88.9)

    def test_executive_health_penalizes_multiple_risk_signals(self):
        healthy = scorecards.executive_health_score({
            "total_queries": 1000,
            "failed_queries": 0,
            "queued_queries": 0,
            "avg_elapsed_sec": 1,
            "task_runs": 100,
            "failed_tasks": 0,
            "active_warehouses": 10,
            "pressure_warehouses": 0,
            "current_credits": 100,
            "prior_credits": 100,
            "current_storage_tb": 10,
            "prior_storage_tb": 10,
        })
        risky = scorecards.executive_health_score({
            "total_queries": 1000,
            "failed_queries": 100,
            "queued_queries": 200,
            "avg_elapsed_sec": 25,
            "task_runs": 100,
            "failed_tasks": 20,
            "active_warehouses": 10,
            "pressure_warehouses": 4,
            "current_credits": 200,
            "prior_credits": 100,
            "current_storage_tb": 15,
            "prior_storage_tb": 10,
        })
        self.assertGreater(healthy["score"], risky["score"])
        self.assertEqual(healthy["label"], "Healthy")
        self.assertIn(risky["label"], {"At Risk", "Critical"})

    def test_service_health_weights_logins_less_than_task_and_query_failures(self):
        login_only = scorecards.service_health_scorecard({
            "total_queries": 1000,
            "failed_queries": 0,
            "queued_queries": 0,
            "blocked_queries": 0,
            "p95_elapsed_sec": 5,
            "warehouse_count": 10,
            "pressured_warehouses": 0,
            "task_runs": 100,
            "failed_tasks": 0,
            "login_events": 100,
            "failed_logins": 10,
            "load_events": 100,
            "failed_loads": 0,
        })
        task_query = scorecards.service_health_scorecard({
            "total_queries": 1000,
            "failed_queries": 50,
            "queued_queries": 100,
            "blocked_queries": 25,
            "p95_elapsed_sec": 90,
            "warehouse_count": 10,
            "pressured_warehouses": 2,
            "task_runs": 100,
            "failed_tasks": 10,
            "login_events": 100,
            "failed_logins": 0,
            "load_events": 100,
            "failed_loads": 0,
        })
        self.assertGreater(login_only["score"], task_query["score"])

    def test_dba_readiness_requires_all_components_for_95(self):
        near_perfect = {
            key: 100
            for key in scorecards.DBA_CONTROL_PLANE_COMPONENTS
        }
        near_perfect["governance_ownership"] = 89

        result = scorecards.dba_control_plane_readiness_score(near_perfect)

        self.assertLess(result["score"], 95)
        self.assertEqual(result["label"], "Near Target")
        self.assertTrue(result["caps"])

    def test_dba_readiness_caps_weak_admin_safety(self):
        feature_rich_but_unsafe = {
            key: 96
            for key in scorecards.DBA_CONTROL_PLANE_COMPONENTS
        }
        feature_rich_but_unsafe["admin_safety_audit"] = 70

        result = scorecards.dba_control_plane_readiness_score(feature_rich_but_unsafe)

        self.assertLessEqual(result["score"], 89)
        self.assertIn("Admin Safety & Audit", [row["COMPONENT"] for row in result["components"]])

    def test_dba_readiness_allows_95_only_when_control_dimensions_are_high(self):
        production_ready = {
            key: 95
            for key in scorecards.DBA_CONTROL_PLANE_COMPONENTS
        }

        result = scorecards.dba_control_plane_readiness_score(production_ready)

        self.assertEqual(result["score"], 95.0)
        self.assertEqual(result["label"], "95 Target")
        self.assertEqual(result["caps"], [])

    def test_dba_section_baseline_is_strict_and_repeatable(self):
        rows = scorecards.dba_control_plane_section_scorecards()
        by_section = {row["SECTION"]: row for row in rows}

        self.assertEqual(by_section["DBA Control Room"]["SCORE"], 93.0)
        self.assertEqual(by_section["DBA Control Room"]["LABEL"], "Near Target")
        self.assertEqual(by_section["Alert Center"]["SCORE"], 95.2)
        self.assertEqual(by_section["Alert Center"]["LABEL"], "95 Target")
        self.assertEqual(by_section["Warehouse Health"]["SCORE"], 94.6)
        self.assertEqual(by_section["Warehouse Health"]["LABEL"], "Near Target")
        self.assertEqual(by_section["Workload Operations"]["SCORE"], 95.7)
        self.assertEqual(by_section["Workload Operations"]["LABEL"], "95 Target")
        self.assertEqual(by_section["Cost & Contract"]["SCORE"], 96.4)
        self.assertEqual(by_section["Cost & Contract"]["LABEL"], "95 Target")
        self.assertEqual(by_section["Security Posture"]["SCORE"], 94.8)
        self.assertEqual(by_section["Security Posture"]["LABEL"], "Near Target")
        self.assertEqual(by_section["Security Posture"]["CAP_DRIVERS"], "none")
        self.assertEqual(by_section["Change & Drift"]["SCORE"], 94.2)
        self.assertEqual(by_section["Change & Drift"]["LABEL"], "Near Target")
        self.assertEqual(by_section["Change & Drift"]["CAP_DRIVERS"], "none")
        self.assertEqual(by_section["Account Health"]["SCORE"], 94.8)
        self.assertEqual(by_section["Account Health"]["LABEL"], "Near Target")
        self.assertGreaterEqual(max(row["SCORE"] for row in rows), 95)
        self.assertEqual(by_section["DBA Control Room"]["CAP_DRIVERS"], "none")
        self.assertIn("notification integration", by_section["Alert Center"]["NEXT_95_MOVE"])


if __name__ == "__main__":
    unittest.main()
