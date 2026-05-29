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


if __name__ == "__main__":
    unittest.main()
