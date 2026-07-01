from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / ".overwatch_final"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class MetricSourceGovernanceTests(unittest.TestCase):
    def test_high_value_metric_families_are_governed(self):
        from tools.contracts.metric_source_governance import (
            METRIC_FAMILY_GATE_RELS,
            build_metric_source_governance_results,
            evaluate_metric_source_governance_gate,
        )

        results = build_metric_source_governance_results(ROOT)
        gate = evaluate_metric_source_governance_gate(results)

        self.assertTrue(results["passed"], results["failures"][:5])
        self.assertTrue(gate["passed"], gate["failures"][:5])
        self.assertEqual(results["new_metric_family_count"], len(METRIC_FAMILY_GATE_RELS))
        self.assertGreaterEqual(results["new_metric_packet_field_count"], 90)
        self.assertGreaterEqual(results["new_metric_evidence_action_count"], len(METRIC_FAMILY_GATE_RELS))
        self.assertEqual(results["new_metric_first_paint_violation_count"], 0)
        self.assertEqual(results["new_metric_raw_leak_count"], 0)
        self.assertTrue(results["app_health_gate_passed"])

    def test_every_family_gate_has_packet_export_and_evidence_metadata(self):
        from tools.contracts.metric_source_governance import (
            METRIC_FAMILY_GATE_RELS,
            build_metric_source_governance_results,
            evaluate_metric_family_gate,
        )

        results = build_metric_source_governance_results(ROOT)
        for family_id in METRIC_FAMILY_GATE_RELS:
            with self.subTest(family_id=family_id):
                gate = evaluate_metric_family_gate(results, family_id)
                self.assertTrue(gate["passed"], gate)
                self.assertGreater(gate["metric_count"], 0)
                self.assertGreater(gate["packet_field_count"], 0)
                self.assertGreater(gate["evidence_action_count"], 0)
                self.assertGreater(gate["export_count"], 0)
                self.assertEqual(gate["first_paint_violation_count"], 0)

    def test_account_usage_metrics_are_refresh_or_live_only(self):
        from tools.contracts.metric_source_governance import build_metric_source_governance_results

        results = build_metric_source_governance_results(ROOT)
        account_usage_rows = [row for row in results["rows"] if row["account_usage_source"]]
        self.assertTrue(account_usage_rows)
        for row in account_usage_rows:
            with self.subTest(metric_key=row["metric_key"]):
                self.assertFalse(row["first_paint_allowed"])
                self.assertIn(row["refresh_boundary"], {"refresh_fast", "refresh_full", "setup_admin", "live_validation"})
                self.assertIn("source_confirmed_zero", row["zero_policy"])
                self.assertRegex(row["unavailable_policy"].lower(), "pending|unavailable")

    def test_launch_readiness_requires_metric_source_governance_artifacts(self):
        from tools.contracts.launch_readiness import REQUIRED_LAUNCH_READINESS_ARTIFACTS
        from tools.contracts.metric_source_governance import (
            METRIC_FAMILY_GATE_RELS,
            METRIC_SOURCE_GOVERNANCE_GATE_REL,
        )

        self.assertIn(METRIC_SOURCE_GOVERNANCE_GATE_REL, REQUIRED_LAUNCH_READINESS_ARTIFACTS)
        for rel in METRIC_FAMILY_GATE_RELS.values():
            self.assertIn(rel, REQUIRED_LAUNCH_READINESS_ARTIFACTS)

    def test_sql_inventory_owns_new_metric_source_paths(self):
        from tools.contracts.metric_source_governance import FAMILY_SQL_PATH_IDS
        from tools.contracts.sql_value_inventory import build_sql_value_inventory

        inventory = build_sql_value_inventory(ROOT)
        rows = {row["path_id"]: row for row in inventory["rows"]}
        for family_id, path_ids in FAMILY_SQL_PATH_IDS.items():
            for path_id in path_ids:
                with self.subTest(family_id=family_id, path_id=path_id):
                    self.assertIn(path_id, rows)
                    self.assertTrue(rows[path_id]["owner"])
                    self.assertTrue(rows[path_id]["purpose"])
                    self.assertTrue(rows[path_id]["daily_safe"])
                    self.assertNotEqual(rows[path_id]["account_usage_use"], "daily_first_paint")

    def test_daily_leak_scan_blocks_new_raw_source_names(self):
        from tools.contracts.rendered_ui_leak_scan import FORBIDDEN_TOKENS

        for token in (
            "QUERY_INSIGHTS",
            "QUERY_ATTRIBUTION_HISTORY",
            "TABLE_STORAGE_METRICS",
            "ACCESS_HISTORY",
            "TRUST_CENTER_FINDINGS",
            "DYNAMIC_TABLE_REFRESH_HISTORY",
        ):
            self.assertIn(token, FORBIDDEN_TOKENS)


if __name__ == "__main__":
    unittest.main()
